"""S&P 500 constituent list fetcher.

Gets the current S&P 500 tickers from a reliable CSV dataset on GitHub
(free, no API key). Ticker list is cached locally and refreshed weekly.

Usage:
    fetch_sp500_tickers()  # returns cached list, refreshes weekly
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

SP500_URL = (
    "https://raw.githubusercontent.com/datasets/"
    "s-and-p-500-companies/main/data/constituents.csv"
)
CACHE_FILE = "sp500_cache.json"
REFRESH_DAYS = 7  # refresh once per week


def fetch_sp500_tickers() -> list[str]:
    """Return sorted list of current S&P 500 stock symbols (cached weekly)."""
    # Try cache first
    cached = _load_cache()
    if cached:
        age = datetime.utcnow() - datetime.fromisoformat(cached["fetched_at"])
        if age < timedelta(days=REFRESH_DAYS):
            logger.info("Using cached S&P 500 list (%d tickers, %d days old)",
                        len(cached["tickers"]), age.days)
            return cached["tickers"]

    # Fetch fresh
    tickers = _fetch_tickers()
    if tickers:
        _save_cache(tickers)
        return tickers

    # Fallback to stale cache
    if cached:
        logger.warning("Fetch failed, using stale cache (%d days old)",
                       (datetime.utcnow() - datetime.fromisoformat(cached["fetched_at"])).days)
        return cached["tickers"]

    logger.error("No S&P 500 tickers available (fetch failed, no cache)")
    return []


def _load_cache() -> dict | None:
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _save_cache(tickers: list[str]) -> None:
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump({"tickers": tickers, "fetched_at": datetime.utcnow().isoformat()}, f)
        logger.info("Cached %d S&P 500 tickers", len(tickers))
    except Exception as exc:
        logger.warning("Failed to save cache: %s", exc)


def _fetch_tickers() -> list[str]:
    try:
        r = requests.get(SP500_URL, timeout=15)
        r.raise_for_status()

        reader = csv.DictReader(io.StringIO(r.text))
        if "Symbol" not in (reader.fieldnames or []):
            logger.error("S&P 500 CSV format changed, columns: %s", reader.fieldnames)
            return []

        tickers = sorted(row["Symbol"].strip() for row in reader)
        logger.info("Fetched %d S&P 500 tickers from CSV", len(tickers))
        return tickers
    except requests.RequestException as exc:
        logger.error("HTTP error fetching S&P 500 list: %s", exc)
        return []
    except Exception as exc:
        logger.error("Failed to fetch S&P 500 list: %s", exc)
        return []
