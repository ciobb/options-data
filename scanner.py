"""Core orchestrator for the options scanner.

Ties together fetching, filtering, and reporting into a single workflow.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from config import ScannerConfig
from fetcher import fetch_chains
from filters import apply_filters, compute_summary, OptionType
from reporter import print_summary_table, save_results

logger = logging.getLogger(__name__)


def run_scan(
    config: ScannerConfig | None = None,
    *,
    tickers: list[str] | None = None,
    iv_threshold: float | None = None,
    oi_threshold: int | None = None,
    option_type: str = "any",
    min_strike: float | None = None,
    max_strike: float | None = None,
    min_volume: int | None = None,
    exclude_itm: bool = False,
    top_n: int = 25,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, str]]:
    """Run a full scan: fetch → filter → report → save.

    Args:
        config: A ScannerConfig instance.  All other kwargs override its values.
        tickers: Stock symbols to scan.
        iv_threshold: Minimum implied volatility (e.g. 1.0 = 100%).
        oi_threshold: Minimum open interest.
        option_type: 'call', 'put', or 'any'.
        min_strike: Minimum strike price.
        max_strike: Maximum strike price.
        min_volume: Minimum daily volume.
        exclude_itm: Exclude in-the-money contracts.
        top_n: Number of rows to show in summary table.

    Returns:
        (filtered DataFrame, summary dict, output_paths dict)
    """
    cfg = config or ScannerConfig()

    _tickers = tickers or cfg.tickers
    _iv = iv_threshold if iv_threshold is not None else cfg.iv_threshold
    _oi = oi_threshold if oi_threshold is not None else cfg.oi_threshold

    logger.info("Starting scan: %d tickers, IV > %.0f%%, OI >= %d",
                len(_tickers), _iv * 100, _oi)

    if cfg.api_provider == "ib":
        raw_df = fetch_chains(
            _tickers,
            ib_host=cfg.ib_host,
            ib_port=cfg.ib_port,
            ib_client_id=cfg.ib_client_id,
            ib_max_expirations=cfg.ib_max_expirations,
            ib_min_strike_pct=cfg.ib_min_strike_pct,
            ib_max_strike_pct=cfg.ib_max_strike_pct,
        )
    elif cfg.api_provider == "cboe":
        raw_df = fetch_chains(_tickers, use_cboe=True, cboe_delay=cfg.cboe_delay)
    else:
        raw_df = fetch_chains(_tickers, max_workers=cfg.max_concurrent)

    if raw_df.empty:
        logger.warning("No data fetched — aborting scan.")
        empty = pd.DataFrame()
        return empty, {"total_hits": 0, "unique_tickers": 0, "avg_iv": 0.0, "avg_oi": 0.0}, {}

    filtered = apply_filters(
        raw_df,
        iv_threshold=_iv,
        oi_threshold=_oi,
        min_strike=min_strike,
        max_strike=max_strike,
        min_volume=min_volume,
        option_type=OptionType(option_type),
        exclude_itm=exclude_itm,
    )

    summary = compute_summary(filtered)
    print_summary_table(filtered, summary, top_n=top_n)
    paths = save_results(filtered, output_dir=cfg.output_dir)

    return filtered, summary, paths
