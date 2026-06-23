"""S&P 500 constituent list fetcher.

Gets the current S&P 500 tickers from Wikipedia (free, no API key).
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def fetch_sp500_tickers() -> list[str]:
    """Return sorted list of current S&P 500 stock symbols."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        r = requests.get(SP500_URL, headers=headers, timeout=15)
        r.raise_for_status()
        tables = pd.read_html(r.text)
        df = tables[0]
        if "Symbol" not in df.columns:
            logger.error("S&P 500 table format changed")
            return []
        tickers = sorted(df["Symbol"].str.replace(".", "-", regex=False).tolist())
        logger.info("Fetched %d S&P 500 tickers", len(tickers))
        return tickers
    except Exception as exc:
        logger.error("Failed to fetch S&P 500 list: %s", exc)
        return []


if __name__ == "__main__":
    tickers = fetch_sp500_tickers()
    print(f"Total: {len(tickers)}")
    print(", ".join(tickers[:20]) + " ...")
