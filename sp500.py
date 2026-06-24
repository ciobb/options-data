"""S&P 500 constituent list fetcher.

Gets the current S&P 500 tickers from Wikipedia (free, no API key).
"""

from __future__ import annotations

import io
import logging
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def fetch_sp500_tickers() -> list[str]:
    """Return sorted list of current S&P 500 stock symbols."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        r = requests.get(SP500_URL, headers=headers, timeout=15)
        r.raise_for_status()

        # Use html.parser explicitly, parse from bytes to avoid encoding issues
        tables = pd.read_html(io.BytesIO(r.content), flavor="lxml")
        df = tables[0]
        if "Symbol" not in df.columns:
            logger.error("S&P 500 table format changed, columns: %s", df.columns.tolist())
            return []

        tickers = sorted(df["Symbol"].str.replace(".", "-", regex=False).tolist())
        logger.info("Fetched %d S&P 500 tickers", len(tickers))
        return tickers
    except requests.RequestException as exc:
        logger.error("HTTP error fetching S&P 500 list: %s", exc)
        return []
    except Exception as exc:
        logger.error("Failed to fetch S&P 500 list: %s", exc)
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tickers = fetch_sp500_tickers()
    print(f"Total: {len(tickers)}")
    if tickers:
        print(", ".join(tickers[:10]) + " ...")
