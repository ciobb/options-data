#!/usr/bin/env python3
"""CLI entry point for the options scanner.

Usage:
    python main.py                          # default tickers, default thresholds
    python main.py --tickers AAPL,NVDA,TSLA --iv 0.8 --oi 5000
    python main.py --calls-only             # only call options
    python main.py --exclude-itm            # OTM only
    python main.py --provider ib            # use Interactive Brokers
"""

from __future__ import annotations

import argparse
import logging
import sys

from config import ScannerConfig
from scanner import run_scan


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan US stock options for high IV & Open Interest opportunities.",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated tickers (default: built-in list).",
    )
    parser.add_argument(
        "--iv",
        type=float,
        default=None,
        help="Minimum implied volatility, decimal (e.g. 1.0 = 100%%). Default: 1.0.",
    )
    parser.add_argument(
        "--oi",
        type=int,
        default=None,
        help="Minimum open interest in contracts. Default: 1000.",
    )
    parser.add_argument(
        "--calls-only",
        action="store_const",
        const="call",
        dest="option_type",
        default="any",
        help="Show only call options.",
    )
    parser.add_argument(
        "--puts-only",
        action="store_const",
        const="put",
        dest="option_type",
        help="Show only put options.",
    )
    parser.add_argument(
        "--min-strike",
        type=float,
        default=None,
        help="Minimum strike price.",
    )
    parser.add_argument(
        "--max-strike",
        type=float,
        default=None,
        help="Maximum strike price.",
    )
    parser.add_argument(
        "--min-volume",
        type=int,
        default=None,
        help="Minimum daily volume.",
    )
    parser.add_argument(
        "--exclude-itm",
        action="store_true",
        help="Exclude in-the-money options.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=25,
        help="Number of results to display (default: 25).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory for CSV/JSON output (default: output/).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        choices=["yfinance", "ib", "cboe"],
        help="Data provider: yfinance (free), cboe (free, accurate OI), or ib (requires TWS/Gateway).",
    )
    parser.add_argument(
        "--ib-host",
        type=str,
        default=None,
        help="IB TWS/Gateway host (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--ib-port",
        type=int,
        default=None,
        help="IB TWS/Gateway port (default: 7497).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config = ScannerConfig.from_env()

    if args.tickers:
        config.tickers = [t.strip().upper() for t in args.tickers.split(",")]

    if args.output_dir:
        config.output_dir = args.output_dir

    if args.provider:
        config.api_provider = args.provider
    if args.ib_host:
        config.ib_host = args.ib_host
    if args.ib_port:
        config.ib_port = args.ib_port

    tickers_str = config.tickers[:5]
    extra = f"+{len(config.tickers) - 5} more" if len(config.tickers) > 5 else ""
    provider_label = {"ib": "IB", "cboe": "CBOE"}.get(config.api_provider, "yfinance")
    print(f"\nScanning {', '.join(tickers_str)}{extra} | "
          f"IV > {config.iv_threshold * 100:.0f}% | OI >= {config.oi_threshold:,} | "
          f"Type: {args.option_type} | Provider: {provider_label}\n")

    try:
        run_scan(
            config=config,
            iv_threshold=args.iv,
            oi_threshold=args.oi,
            option_type=args.option_type,
            min_strike=args.min_strike,
            max_strike=args.max_strike,
            min_volume=args.min_volume,
            exclude_itm=args.exclude_itm,
            top_n=args.top,
        )
    except KeyboardInterrupt:
        print("\nScan cancelled.")
        sys.exit(0)
    except Exception as exc:
        logging.getLogger(__name__).exception("Scan failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
