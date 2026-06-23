"""Output / reporting layer for the options scanner.

Writes results to CSV or JSON and prints a formatted summary table.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

import pandas as pd
from tabulate import tabulate

logger = logging.getLogger(__name__)

DISPLAY_COLUMNS: list[str] = [
    "ticker", "contractSymbol", "optionType", "strike", "expiration",
    "impliedVolatility", "openInterest", "volume", "lastPrice",
]


def _prepare_display_df(df: pd.DataFrame) -> pd.DataFrame:
    """Trim and format a DataFrame for display."""
    cols = [c for c in DISPLAY_COLUMNS if c in df.columns]
    display = df[cols].copy()

    if "impliedVolatility" in display.columns:
        display["impliedVolatility"] = (display["impliedVolatility"] * 100).round(1)

    return display


def save_results(
    df: pd.DataFrame,
    output_dir: str = "output",
    prefix: str = "scan",
    formats: tuple[str, ...] = ("csv", "json"),
) -> dict[str, str]:
    """Persist results to disk.

    Args:
        df: The filtered DataFrame to save.
        output_dir: Directory to write files into (created if missing).
        prefix: Filename prefix (timestamps appended).
        formats: Which file formats to produce ('csv', 'json').

    Returns:
        Dict mapping format to output path.
    """
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    paths: dict[str, str] = {}

    if "csv" in formats:
        csv_path = os.path.join(output_dir, f"{prefix}_{ts}.csv")
        df.to_csv(csv_path, index=False)
        paths["csv"] = csv_path
        logger.info("Saved CSV → %s (%d rows)", csv_path, len(df))

    if "json" in formats:
        json_path = os.path.join(output_dir, f"{prefix}_{ts}.json")
        records = df.where(df.notna(), None).to_dict(orient="records")
        with open(json_path, "w") as fh:
            json.dump(records, fh, indent=2, default=str)
        paths["json"] = json_path
        logger.info("Saved JSON → %s (%d rows)", json_path, len(df))

    return paths


def print_summary_table(
    df: pd.DataFrame,
    summary: dict[str, Any],
    top_n: int = 25,
) -> None:
    """Print a human-readable summary to stdout."""
    print("\n" + "=" * 80)
    print("  OPTIONS SCANNER — RESULTS")
    print("=" * 80)

    print(f"\n  Total hits:         {summary['total_hits']}")
    print(f"  Unique tickers:     {summary['unique_tickers']}")
    print(f"  Average IV:         {summary['avg_iv']}%")
    print(f"  Average OI:         {summary['avg_oi']:,}")

    if df.empty:
        print("\n  No contracts matched. Try relaxing thresholds.\n")
        return

    display = _prepare_display_df(df).head(top_n)
    table = tabulate(display, headers="keys", tablefmt="grid", showindex=False,
                     floatfmt=".2f", numalign="right", stralign="left")

    print(f"\n  Top {min(top_n, len(df))} Results (sorted by Open Interest):\n")
    print(table)
    print("\n" + "=" * 80 + "\n")
