"""CBOE (Chicago Board Options Exchange) data provider for options chains.

Provides free delayed options data including open interest, implied volatility,
greeks, bid/ask, volume — all from a single API call per ticker.

No API key or subscription required. Data is delayed ~15 minutes.

API reference:
    https://cdn.cboe.com/api/global/delayed_quotes/options/{TICKER}.json
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{ticker}.json"
CBOE_TIMEOUT = 15

OPTION_COLUMNS: list[str] = [
    "contractSymbol",
    "strike",
    "lastPrice",
    "bid",
    "ask",
    "volume",
    "openInterest",
    "impliedVolatility",
    "delta",
    "gamma",
    "vega",
    "theta",
    "inTheMoney",
]

# INTC261120C00175000
_CONTRACT_RE = re.compile(
    r"^(?P<ticker>[A-Z]{1,6})"
    r"(?P<expiry>\d{6})"
    r"(?P<type>[CP])"
    r"(?P<strike>\d{8})$"
)


def _parse_contract(symbol: str) -> dict[str, Any] | None:
    m = _CONTRACT_RE.match(symbol)
    if not m:
        return None
    exp = m.group("expiry")  # YYMMDD
    year = 2000 + int(exp[:2])
    month = exp[2:4]
    day = exp[4:6]
    return {
        "ticker": m.group("ticker"),
        "expiration": f"{year}-{month}-{day}",
        "optionType": "call" if m.group("type") == "C" else "put",
        "strike": int(m.group("strike")) / 1000.0,
    }


def fetch_cboe_chain(ticker: str) -> pd.DataFrame:
    """Fetch all option contracts for a single ticker from CBOE.

    Returns:
        DataFrame with standardized columns.
    """
    url = CBOE_URL.format(ticker=ticker.upper())
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        r = requests.get(url, headers=headers, timeout=CBOE_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.error("CBOE fetch failed for %s: %s", ticker, exc)
        return pd.DataFrame()

    options = data.get("data", {}).get("options", [])
    if not options:
        logger.warning("No options returned by CBOE for %s", ticker)
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for opt in options:
        symbol = opt.get("option", "")
        parsed = _parse_contract(symbol)
        if not parsed:
            continue

        iv = opt.get("iv", 0) or 0
        oi = opt.get("open_interest", 0) or 0

        rows.append({
            "contractSymbol": symbol,
            "ticker": parsed["ticker"],
            "expiration": parsed["expiration"],
            "optionType": parsed["optionType"],
            "strike": parsed["strike"],
            "lastPrice": opt.get("last_trade_price"),
            "bid": opt.get("bid"),
            "ask": opt.get("ask"),
            "volume": opt.get("volume"),
            "openInterest": int(oi) if oi else 0,
            "impliedVolatility": float(iv) if iv else 0.0,
            "delta": opt.get("delta"),
            "gamma": opt.get("gamma"),
            "vega": opt.get("vega"),
            "theta": opt.get("theta"),
            "inTheMoney": None,
        })

    df = pd.DataFrame(rows)
    df["retrievedAt"] = datetime.utcnow().isoformat()
    logger.info("CBOE fetched %d contracts for %s", len(df), ticker)
    return df


def fetch_cboe_all(
    tickers: list[str],
    delay: float = 0.5,
    progress_callback: Any = None,
) -> pd.DataFrame:
    """Fetch CBOE options chains for multiple tickers sequentially.

    Args:
        tickers: List of stock symbols.
        delay: Seconds between requests to respect CBOE rate limits.
        progress_callback: Optional callable(completed, total).

    Returns:
        Combined DataFrame.
    """
    all_frames: list[pd.DataFrame] = []
    total = len(tickers)

    for i, ticker in enumerate(tickers):
        try:
            df = fetch_cboe_chain(ticker)
            if not df.empty:
                all_frames.append(df)
        except Exception as exc:
            logger.error("CBOE error for %s: %s", ticker, exc)

        if progress_callback:
            progress_callback(i + 1, total)

        if i < total - 1 and delay > 0:
            time.sleep(delay)

    if not all_frames:
        return pd.DataFrame()

    return pd.concat(all_frames, ignore_index=True)
