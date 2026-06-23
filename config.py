"""Configuration management for the options scanner.

Loads settings from environment variables and provides defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Final

from dotenv import load_dotenv

load_dotenv()

DEFAULT_TICKERS: Final[list[str]] = [
    "SPY", "QQQ", "AAPL", "NVDA", "TSLA", "AMD", "AMZN", "META",
    "MSFT", "GOOGL", "GME", "AMC", "PLTR", "SOFI", "RIOT", "MARA",
]

DEFAULT_IV_THRESHOLD: Final[float] = 1.0  # > 100%
DEFAULT_OI_THRESHOLD: Final[int] = 1000  # > 1,000 contracts
DEFAULT_MAX_CONCURRENT: Final[int] = 5
DEFAULT_OUTPUT_DIR: Final[str] = "output"
DEFAULT_OUTPUT_FORMAT: Final[str] = "csv"


@dataclass
class ScannerConfig:
    """Holds all configuration for the options scanner."""

    tickers: list[str] = field(default_factory=lambda: DEFAULT_TICKERS.copy())
    iv_threshold: float = DEFAULT_IV_THRESHOLD
    oi_threshold: int = DEFAULT_OI_THRESHOLD
    max_concurrent: int = DEFAULT_MAX_CONCURRENT
    output_dir: str = DEFAULT_OUTPUT_DIR
    output_format: str = DEFAULT_OUTPUT_FORMAT
    api_provider: str = "yfinance"
    ib_host: str = "127.0.0.1"
    ib_port: int = 7497
    ib_client_id: int = 1
    ib_max_expirations: int = 4
    ib_min_strike_pct: float = 0.70
    ib_max_strike_pct: float = 1.30
    cboe_delay: float = 0.5

    @classmethod
    def from_env(cls) -> ScannerConfig:
        """Build a ScannerConfig from environment variables with sensible defaults."""
        tickers_raw = os.getenv("SCANNER_TICKERS")
        tickers = (
            [t.strip().upper() for t in tickers_raw.split(",") if t.strip()]
            if tickers_raw
            else DEFAULT_TICKERS.copy()
        )

        return cls(
            tickers=tickers,
            iv_threshold=float(os.getenv("IV_THRESHOLD", DEFAULT_IV_THRESHOLD)),
            oi_threshold=int(os.getenv("OI_THRESHOLD", DEFAULT_OI_THRESHOLD)),
            max_concurrent=int(os.getenv("MAX_CONCURRENT_TICKERS", DEFAULT_MAX_CONCURRENT)),
            output_dir=os.getenv("OUTPUT_DIR", DEFAULT_OUTPUT_DIR),
            output_format=os.getenv("OUTPUT_FORMAT", DEFAULT_OUTPUT_FORMAT),
            api_provider=os.getenv("API_PROVIDER", "yfinance"),
            ib_host=os.getenv("IB_HOST", "127.0.0.1"),
            ib_port=int(os.getenv("IB_PORT", "7497")),
            ib_client_id=int(os.getenv("IB_CLIENT_ID", "1")),
            ib_max_expirations=int(os.getenv("IB_MAX_EXPIRATIONS", "4")),
            ib_min_strike_pct=float(os.getenv("IB_MIN_STRIKE_PCT", "0.70")),
            ib_max_strike_pct=float(os.getenv("IB_MAX_STRIKE_PCT", "1.30")),
            cboe_delay=float(os.getenv("CBOE_DELAY", "0.5")),
        )
