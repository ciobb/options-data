"""Filtering logic for the options scanner.

Applies user-configurable thresholds to options chain data.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class OptionType(str, Enum):
    CALL = "call"
    PUT = "put"
    ANY = "any"


def apply_filters(
    df: pd.DataFrame,
    iv_threshold: float = 1.0,
    oi_threshold: int = 1000,
    min_strike: float | None = None,
    max_strike: float | None = None,
    min_volume: int | None = None,
    option_type: OptionType = OptionType.ANY,
    exclude_itm: bool = False,
) -> pd.DataFrame:
    """Filter the raw options DataFrame against configurable thresholds.

    Args:
        df: Raw options data with at minimum columns `impliedVolatility` and `openInterest`.
        iv_threshold: Minimum implied volatility (decimal, e.g. 1.0 = 100%).
        oi_threshold: Minimum open interest in contracts.
        min_strike: Optional minimum strike price filter.
        max_strike: Optional maximum strike price filter.
        min_volume: Optional minimum daily volume filter.
        option_type: Restrict to 'call', 'put', or 'any'.
        exclude_itm: If True, exclude in-the-money options.

    Returns:
        Filtered DataFrame sorted by descending openInterest.
    """
    filtered = df.copy()

    if filtered.empty:
        logger.warning("Input DataFrame is empty — nothing to filter.")
        return filtered

    row_count = len(filtered)

    # ----- Implied Volatility -----
    if "impliedVolatility" in filtered.columns:
        before = len(filtered)
        filtered = filtered[filtered["impliedVolatility"] > iv_threshold]
        logger.debug("IV > %.0f%% : %d → %d", iv_threshold * 100, before, len(filtered))
    else:
        logger.warning("Column 'impliedVolatility' not found — skipping IV filter.")

    # ----- Open Interest -----
    if "openInterest" in filtered.columns:
        before = len(filtered)
        filtered = filtered[filtered["openInterest"] >= oi_threshold]
        logger.debug("OI >= %d : %d → %d", oi_threshold, before, len(filtered))
    else:
        logger.warning("Column 'openInterest' not found — skipping OI filter.")

    # ----- Strike range -----
    if min_strike is not None and "strike" in filtered.columns:
        filtered = filtered[filtered["strike"] >= min_strike]
    if max_strike is not None and "strike" in filtered.columns:
        filtered = filtered[filtered["strike"] <= max_strike]

    # ----- Volume -----
    if min_volume is not None and "volume" in filtered.columns:
        filtered = filtered[filtered["volume"] >= min_volume]

    # ----- Option type (call / put) -----
    if option_type != OptionType.ANY and "optionType" in filtered.columns:
        filtered = filtered[filtered["optionType"] == option_type.value]

    # ----- Exclude ITM -----
    if exclude_itm and "inTheMoney" in filtered.columns:
        filtered = filtered[~filtered["inTheMoney"]]

    # ----- Sort -----
    sort_by = "openInterest" if "openInterest" in filtered.columns else "volume"
    if sort_by in filtered.columns:
        filtered = filtered.sort_values(sort_by, ascending=False)

    logger.info("Filters applied: %d → %d rows", row_count, len(filtered))
    return filtered


def compute_summary(df: pd.DataFrame) -> dict[str, Any]:
    """Produce a summary dictionary from a filtered DataFrame."""
    if df.empty:
        return {"total_hits": 0, "unique_tickers": 0, "avg_iv": 0.0, "avg_oi": 0.0}

    avg_iv = float(df["impliedVolatility"].mean()) if "impliedVolatility" in df.columns else 0.0
    avg_oi = float(df["openInterest"].mean()) if "openInterest" in df.columns else 0.0

    return {
        "total_hits": len(df),
        "unique_tickers": int(df["ticker"].nunique()) if "ticker" in df.columns else 0,
        "avg_iv": round(avg_iv * 100, 1),
        "avg_oi": round(avg_oi, 1),
    }
