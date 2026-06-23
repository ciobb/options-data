"""Open Interest history tracker.

Records daily OI snapshots to disk and computes changes over time.
Snapshots are stored in output/oi_history/ as timestamped JSON records.

Usage:
    save_snapshot(df)         # call after each fetch
    get_changes_for_ticker()  # get OI changes vs oldest snapshot
    get_history_table()       # get all snapshots for display
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

_HISTORY_DIR = "output/oi_history"
_PREFIX = "oi_snapshot"


def _ensure_dir() -> str:
    os.makedirs(_HISTORY_DIR, exist_ok=True)
    return _HISTORY_DIR


def save_snapshot(df: pd.DataFrame) -> str:
    """Save current OI and IV values for all contracts in the DataFrame."""
    required = {"ticker", "contractSymbol", "openInterest"}
    if not required.issubset(df.columns):
        return ""

    cols = ["ticker", "contractSymbol", "openInterest"]
    if "impliedVolatility" in df.columns:
        cols.append("impliedVolatility")

    subset = df[df["openInterest"] > 0][cols].copy()
    if subset.empty:
        return ""

    subset["openInterest"] = subset["openInterest"].astype(int)
    subset["snapshotAt"] = datetime.utcnow().isoformat()

    records = subset.to_dict(orient="records")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(_ensure_dir(), f"{_PREFIX}_{ts}.json")
    with open(path, "w") as f:
        json.dump(records, f, indent=2)
    return path


def _load_snapshots(lookback_days: int = 7) -> pd.DataFrame:
    """Load all snapshots from the past N days."""
    base = _ensure_dir()
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    all_records: list[dict[str, Any]] = []

    try:
        for fname in sorted(os.listdir(base)):
            if not fname.startswith(_PREFIX) or not fname.endswith(".json"):
                continue
            path = os.path.join(base, fname)
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
            if mtime < cutoff:
                continue
            with open(path) as f:
                records = json.load(f)
            for r in records:
                r["file"] = fname
            all_records.extend(records)
    except FileNotFoundError:
        pass

    if not all_records:
        return pd.DataFrame()
    return pd.DataFrame(all_records)


def get_history_table(ticker: str, contracts: list[str],
                      lookback_days: int = 7) -> pd.DataFrame:
    """Return a pivot-style DataFrame showing OI per contract per snapshot date.

    Columns: Contract, then one column per snapshot date.
    """
    snapshots = _load_snapshots(lookback_days)
    if snapshots.empty:
        return pd.DataFrame()

    subset = snapshots[snapshots["contractSymbol"].isin(contracts)]
    if subset.empty:
        return pd.DataFrame()

    subset["date"] = pd.to_datetime(subset["snapshotAt"]).dt.date

    pivot = subset.pivot_table(
        index="contractSymbol",
        columns="date",
        values="openInterest",
        aggfunc="max",
    )
    pivot = pivot.sort_index(axis=1)
    pivot = pivot.reset_index()
    pivot = pivot.rename(columns={"contractSymbol": "Contract"})
    return pivot


def oi_change_for_contract(contract: str, lookback_days: int = 7) -> dict[str, Any] | None:
    """Get OI change for a single contract (oldest → newest)."""
    snapshots = _load_snapshots(lookback_days)
    if snapshots.empty:
        return None
    subset = snapshots[snapshots["contractSymbol"] == contract].sort_values("snapshotAt")
    if len(subset) < 2:
        return None

    first = subset.iloc[0]
    last = subset.iloc[-1]
    oi_old = int(first["openInterest"])
    oi_new = int(last["openInterest"])
    delta = oi_new - oi_old
    pct = (delta / oi_old * 100) if oi_old else 0.0
    d1 = datetime.fromisoformat(first["snapshotAt"])
    d2 = datetime.fromisoformat(last["snapshotAt"])
    days = (d2 - d1).days or 1

    return {
        "oldest_oi": oi_old,
        "newest_oi": oi_new,
        "change": delta,
        "pct_change": round(pct, 1),
        "days": days,
        "first_date": first["snapshotAt"][:10],
        "last_date": last["snapshotAt"][:10],
    }


def get_changes_for_ticker(ticker: str, contracts: list[str],
                           lookback_days: int = 7) -> dict[str, dict[str, Any] | None]:
    """Get OI changes for a list of contracts."""
    snapshots = _load_snapshots(lookback_days)
    if snapshots.empty:
        return {c: None for c in contracts}

    result: dict[str, dict[str, Any] | None] = {}
    for c in contracts:
        result[c] = oi_change_for_contract(c, lookback_days)
    return result


def snapshot_count() -> int:
    """Number of snapshot files available."""
    base = _ensure_dir()
    try:
        return len([f for f in os.listdir(base) if f.startswith(_PREFIX)])
    except FileNotFoundError:
        return 0


def iv_rank_for_contract(contract: str, lookback_days: int = 365) -> dict[str, Any] | None:
    """Compute IV Rank and Percentile for a single contract from historical snapshots.

    Deduplicates to one snapshot per day. Requires at least 3 distinct days.
    """
    snapshots = _load_snapshots(lookback_days)
    if snapshots.empty or "impliedVolatility" not in snapshots.columns:
        return None

    subset = snapshots[snapshots["contractSymbol"] == contract].copy()
    if len(subset) < 2:
        return None

    # Deduplicate to one snapshot per day (take the last of each day)
    subset["date"] = pd.to_datetime(subset["snapshotAt"]).dt.date
    subset = subset.sort_values("snapshotAt").drop_duplicates("date", keep="last")

    ivs = subset["impliedVolatility"].dropna().values
    if len(ivs) < 3:
        return None  # Need at least 3 distinct days

    current = float(ivs[-1])
    iv_min = float(ivs.min())
    iv_max = float(ivs.max())
    iv_range = iv_max - iv_min

    if iv_range == 0:
        rank = 50.0
    else:
        rank = round((current - iv_min) / iv_range * 100, 1)

    pct = round((ivs < current).sum() / len(ivs) * 100, 1)

    return {
        "current_iv": round(current * 100, 1),
        "iv_rank": rank,
        "iv_percentile": pct,
        "iv_min": round(iv_min * 100, 1),
        "iv_max": round(iv_max * 100, 1),
        "snapshots": len(ivs),
    }


def get_iv_stats_for_ticker(ticker: str, contracts: list[str],
                            lookback_days: int = 365) -> dict[str, dict[str, Any] | None]:
    """Get IV rank/percentile for a list of contracts."""
    return {c: iv_rank_for_contract(c, lookback_days) for c in contracts}
