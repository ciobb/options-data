"""Interactive Brokers data provider for options chains.

Connects to TWS or IB Gateway and fetches option chain market data
including bid/ask, open interest, volume and implied volatility.

Requirements:
    - TWS or IB Gateway running locally with API enabled
    - ib_insync package installed
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pandas as pd

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

MARKET_DATA_GENERIC_TICKS = "106"


class IBProvider:
    """Fetches options chain data from Interactive Brokers."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 1,
        rate_limit_per_sec: int = 45,
    ):
        self._host = host
        self._port = port
        self._client_id = client_id
        self._rate_limit = rate_limit_per_sec
        self._ib: Any = None

    @property
    def ib(self) -> Any:
        if self._ib is None:
            from ib_insync import IB

            self._ib = IB()
        return self._ib

    def connect(self) -> None:
        if self.ib.isConnected():
            return
        self.ib.connect(self._host, self._port, clientId=self._client_id)
        logger.info("Connected to IB at %s:%d", self._host, self._port)

    def disconnect(self) -> None:
        if self._ib is not None and self._ib.isConnected():
            self._ib.disconnect()
            logger.info("Disconnected from IB")

    def fetch_chain(
        self,
        ticker: str,
        max_expirations: int = 4,
        min_strike_pct: float = 0.70,
        max_strike_pct: float = 1.30,
    ) -> pd.DataFrame:
        """Fetch the options chain for a single ticker.

        Args:
            ticker: Stock symbol (e.g. "AAPL").
            max_expirations: Maximum number of nearest expirations to fetch.
            min_strike_pct: Minimum strike as fraction of underlying price.
            max_strike_pct: Maximum strike as fraction of underlying price.

        Returns:
            DataFrame with canonical option columns.
        """
        from ib_insync import Stock, Option

        stock = Stock(ticker, "SMART", "USD")
        self.ib.qualifyContracts(stock)

        chains = self.ib.reqSecDefOptParams(
            stock.symbol, "", stock.secType, stock.conId
        )

        if not chains:
            logger.warning("No option chain params for %s", ticker)
            return pd.DataFrame()

        underlying_price = self._get_underlying_price(stock)

        all_contracts: list[Option] = []
        seen: set[tuple[str, float, str]] = set()

        for chain in chains:
            sorted_exps = sorted(chain.expirations)[:max_expirations]

            for expiry in sorted_exps:
                for strike in chain.strikes:
                    if underlying_price is not None:
                        if strike < underlying_price * min_strike_pct:
                            continue
                        if strike > underlying_price * max_strike_pct:
                            continue

                    for right in ("C", "P"):
                        key = (expiry, strike, right)
                        if key in seen:
                            continue
                        seen.add(key)

                        opt = Option(
                            ticker,
                            expiry,
                            strike,
                            right,
                            "SMART",
                            tradingClass=chain.tradingClass,
                        )
                        all_contracts.append(opt)

        if not all_contracts:
            logger.warning("No contracts built for %s", ticker)
            return pd.DataFrame()

        all_contracts = self.ib.qualifyContracts(*all_contracts)
        if not isinstance(all_contracts, list):
            all_contracts = [all_contracts]

        rows: list[dict[str, Any]] = []
        pace_seconds = 1.0 / self._rate_limit

        for i, contract in enumerate(all_contracts):
            if i > 0 and i % self._rate_limit == 0:
                self.ib.sleep(1)

            t = self.ib.reqMktData(contract, MARKET_DATA_GENERIC_TICKS, True, False)
            self.ib.sleep(pace_seconds)

            row = self._extract_row(contract, t, ticker)
            if row:
                rows.append(row)

            self.ib.cancelMktData(contract)

        if not rows:
            logger.warning("No market data returned for %s", ticker)
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["retrievedAt"] = datetime.utcnow().isoformat()
        logger.info("IB fetched %d contracts for %s", len(df), ticker)
        return df

    def fetch_all_chains(
        self,
        tickers: list[str],
        max_expirations: int = 4,
        min_strike_pct: float = 0.70,
        max_strike_pct: float = 1.30,
        progress_callback: Any = None,
    ) -> pd.DataFrame:
        """Fetch options chains for multiple tickers.

        Args:
            tickers: List of stock symbols.
            max_expirations: Max number of nearest expirations per ticker.
            min_strike_pct: Minimum strike as fraction of underlying.
            max_strike_pct: Maximum strike as fraction of underlying.
            progress_callback: Optional callable(completed, total) for progress.

        Returns:
            Combined DataFrame of all options data.
        """
        all_frames: list[pd.DataFrame] = []
        total = len(tickers)

        for i, ticker in enumerate(tickers):
            try:
                df = self.fetch_chain(
                    ticker,
                    max_expirations=max_expirations,
                    min_strike_pct=min_strike_pct,
                    max_strike_pct=max_strike_pct,
                )
                if not df.empty:
                    all_frames.append(df)
            except Exception as exc:
                logger.error("IB fetch failed for %s: %s", ticker, exc)

            if progress_callback:
                progress_callback(i + 1, total)

        if not all_frames:
            return pd.DataFrame()

        return pd.concat(all_frames, ignore_index=True)

    def _get_underlying_price(self, stock: Any) -> float | None:
        try:
            ticker = self.ib.reqMktData(stock, "", True, False)
            self.ib.sleep(0.1)
            price = ticker.last if ticker.last != 1e100 else ticker.close
            self.ib.cancelMktData(stock)
            if price and price != 1e100:
                return float(price)
        except Exception:
            pass
        return None

    def _extract_row(
        self,
        contract: Any,
        ticker_data: Any,
        symbol: str,
    ) -> dict[str, Any] | None:
        try:
            iv = None
            if hasattr(ticker_data, "modelGreeks") and ticker_data.modelGreeks:
                iv = ticker_data.modelGreeks.impliedVol
                if iv == 1e100 or iv == 0.0:
                    iv = None

            bid = _safe_float(ticker_data.bid)
            ask = _safe_float(ticker_data.ask)
            last = _safe_float(ticker_data.last)

            mid = None
            if bid is not None and ask is not None:
                mid = (bid + ask) / 2

            oi_source = (
                ticker_data.callOpenInterest
                if contract.right == "C"
                else ticker_data.putOpenInterest
            )
            oi = _safe_int(oi_source)

            return {
                "contractSymbol": contract.localSymbol,
                "strike": contract.strike,
                "expiration": _format_expiry(contract.lastTradeDateOrContractMonth),
                "optionType": contract.right.lower(),
                "lastPrice": last if last is not None else mid,
                "bid": bid,
                "ask": ask,
                "volume": _safe_int(ticker_data.volume),
                "openInterest": oi,
                "impliedVolatility": iv,
                "inTheMoney": None,
                "ticker": symbol,
            }
        except Exception as exc:
            logger.debug("Failed to extract row for %s: %s", contract.localSymbol, exc)
            return None


def _safe_float(value: Any) -> float | None:
    if value is None or value == 1e100:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    if value is None or value == 1e100:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_expiry(raw: str) -> str:
    if not raw or len(raw) < 8:
        return raw
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
