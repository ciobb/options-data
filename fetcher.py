"""Data ingestion layer — fetches options chains for a list of tickers.

Supports multiple providers: yfinance (default) and Interactive Brokers.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Callable

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

OPTION_COLUMNS: list[str] = [
    "contractSymbol",
    "strike",
    "lastPrice",
    "bid",
    "ask",
    "volume",
    "openInterest",
    "impliedVolatility",
    "inTheMoney",
]

ProgressCallback = Callable[[int, int], None] | None


def _flatten_option_chain(
    ticker: str,
    expiry: str,
    chain_data: Any,
    option_type: str,
) -> pd.DataFrame:
    if chain_data is None or (hasattr(chain_data, "empty") and chain_data.empty):
        return pd.DataFrame()

    df = chain_data.copy()
    df["ticker"] = ticker
    df["expiration"] = expiry
    df["optionType"] = option_type

    existing_cols = [c for c in OPTION_COLUMNS if c in df.columns]
    return df[["ticker", "expiration", "optionType"] + existing_cols]


def _fetch_one_ticker(ticker: str) -> pd.DataFrame:
    """Fetch all options for a single ticker via yfinance."""
    try:
        t = yf.Ticker(ticker)
        expirations: list[str] = t.options

        if not expirations:
            return pd.DataFrame()

        frames: list[pd.DataFrame] = []
        for expiry in expirations:
            try:
                chain = t.option_chain(expiry)
                calls = _flatten_option_chain(ticker, expiry, chain.calls, "call")
                puts = _flatten_option_chain(ticker, expiry, chain.puts, "put")
                if not calls.empty:
                    frames.append(calls)
                if not puts.empty:
                    frames.append(puts)
            except Exception:
                continue

        if frames:
            result = pd.concat(frames, ignore_index=True)
            return result
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def fetch_all_chains(
    tickers: list[str],
    max_workers: int = 5,
    progress_callback: ProgressCallback = None,
) -> pd.DataFrame:
    """Fetch options chains for multiple tickers via yfinance (concurrent).

    Args:
        tickers: List of stock symbols.
        max_workers: Maximum number of concurrent threads.
        progress_callback: Optional callable(completed, total).

    Returns:
        Combined DataFrame of all options data.
    """
    logger.info(
        "Fetching options chains for %d tickers (%d workers)",
        len(tickers),
        max_workers,
    )

    all_frames: list[pd.DataFrame] = []
    total = len(tickers)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_fetch_one_ticker, t): t for t in tickers}
        completed = 0
        for future in as_completed(future_map):
            ticker = future_map[future]
            completed += 1
            try:
                df = future.result()
                if not df.empty:
                    all_frames.append(df)
            except Exception as exc:
                logger.error("Unhandled error for %s: %s", ticker, exc)
            if progress_callback:
                progress_callback(completed, total)

    if not all_frames:
        logger.warning("No options data retrieved for any ticker.")
        return pd.DataFrame()

    combined = pd.concat(all_frames, ignore_index=True)
    combined["retrievedAt"] = datetime.utcnow().isoformat()
    return combined


def fetch_via_ib(
    tickers: list[str],
    *,
    host: str = "127.0.0.1",
    port: int = 7497,
    client_id: int = 1,
    max_expirations: int = 4,
    min_strike_pct: float = 0.70,
    max_strike_pct: float = 1.30,
    progress_callback: ProgressCallback = None,
) -> pd.DataFrame:
    """Fetch options chains via Interactive Brokers.

    Args:
        tickers: List of stock symbols.
        host: IB TWS/Gateway host.
        port: IB TWS/Gateway port.
        client_id: IB API client ID.
        max_expirations: Max nearest expirations per ticker.
        min_strike_pct: Min strike as fraction of underlying price.
        max_strike_pct: Max strike as fraction of underlying price.
        progress_callback: Optional callable(completed, total).

    Returns:
        Combined DataFrame of all options data.
    """
    from ib_provider import IBProvider

    provider = IBProvider(host=host, port=port, client_id=client_id)

    try:
        provider.connect()
        return provider.fetch_all_chains(
            tickers,
            max_expirations=max_expirations,
            min_strike_pct=min_strike_pct,
            max_strike_pct=max_strike_pct,
            progress_callback=progress_callback,
        )
    finally:
        provider.disconnect()


def fetch_via_cboe(
    tickers: list[str],
    *,
    delay: float = 0.5,
    progress_callback: ProgressCallback = None,
) -> pd.DataFrame:
    """Fetch options chains via CBOE free delayed API.

    Args:
        tickers: List of stock symbols.
        delay: Seconds between requests.
        progress_callback: Optional callable(completed, total).

    Returns:
        Combined DataFrame of all options data.
    """
    from cboe_provider import fetch_cboe_all
    return fetch_cboe_all(tickers, delay=delay, progress_callback=progress_callback)


def fetch_chains(
    tickers: list[str],
    max_workers: int = 5,
    progress_callback: ProgressCallback = None,
    *,
    # IB options — if ib_host is provided, uses IB instead of yfinance
    ib_host: str | None = None,
    ib_port: int = 7497,
    ib_client_id: int = 1,
    ib_max_expirations: int = 4,
    ib_min_strike_pct: float = 0.70,
    ib_max_strike_pct: float = 1.30,
    # CBOE options — if cboe is True, uses CBOE instead
    use_cboe: bool = False,
    cboe_delay: float = 0.5,
) -> pd.DataFrame:
    """Fetch options chains, routing to the appropriate provider.

    Priority: ib_host > use_cboe > yfinance (default).
    """
    if ib_host is not None:
        return fetch_via_ib(
            tickers,
            host=ib_host,
            port=ib_port,
            client_id=ib_client_id,
            max_expirations=ib_max_expirations,
            min_strike_pct=ib_min_strike_pct,
            max_strike_pct=ib_max_strike_pct,
            progress_callback=progress_callback,
        )
    if use_cboe:
        return fetch_via_cboe(tickers, delay=cboe_delay, progress_callback=progress_callback)
    return fetch_all_chains(tickers, max_workers=max_workers, progress_callback=progress_callback)
