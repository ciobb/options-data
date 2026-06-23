#!/usr/bin/env python3
"""Daily auto-scan scheduler.

Runs the options scanner 1 hour after US market close (21:00 UTC / 5:00 AM HKT)
for all S&P 500 stocks, then cleans up data older than 30 days.

Usage (one-time setup):
    python scheduler.py              # run once now
    python scheduler.py --daemon     # run as background daemon, repeat daily
    python scheduler.py --setup-cron # print crontab line for macOS/Linux
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger("scheduler")

# 1 hour after US market close (4pm ET = 20:00 UTC summer, 21:00 UTC winter)
# Using 21:00 UTC to be safe year-round → 5:00 AM HKT next day
SCAN_HOUR_UTC = 21
SCAN_MINUTE = 0
DATA_RETENTION_DAYS = 30
MAX_WORKERS = 5  # yfinance concurrent fetchers


def run_daily_scan() -> None:
    """Fetch all S&P 500 options data, save snapshots, clean old data."""
    from sp500 import fetch_sp500_tickers
    from fetcher import fetch_chains
    from oi_history import cleanup_old_snapshots

    tickers = fetch_sp500_tickers()
    if not tickers:
        logger.error("No S&P 500 tickers fetched — aborting")
        return

    logger.info("Starting daily scan: %d S&P 500 tickers", len(tickers))
    start = time.time()

    try:
        df = fetch_chains(tickers, max_workers=MAX_WORKERS)
        if df.empty:
            logger.warning("No options data returned")
        else:
            logger.info("Fetched %d contracts across %d tickers in %.0fs",
                        len(df), df["ticker"].nunique(), time.time() - start)
    except Exception as exc:
        logger.exception("Scan failed: %s", exc)

    # Clean old data
    removed = cleanup_old_snapshots(keep_days=DATA_RETENTION_DAYS)
    if removed:
        logger.info("Removed %d old snapshot files", removed)

    # Optionally push to GitHub
    try:
        from github_sync import commit_and_push, has_remote
        if has_remote():
            ok, msg = commit_and_push()
            logger.info("GitHub push: %s", msg)
    except Exception:
        pass


def seconds_until_next_scan() -> float:
    now = datetime.utcnow()
    target = now.replace(hour=SCAN_HOUR_UTC, minute=SCAN_MINUTE, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def daemon_mode() -> None:
    """Run continuously, scanning daily at the scheduled time."""
    logger.info("Daemon started. Daily scan at %02d:%02d UTC (1h after US close)",
                SCAN_HOUR_UTC, SCAN_MINUTE)
    while True:
        wait = seconds_until_next_scan()
        next_run = datetime.utcnow() + timedelta(seconds=wait)
        logger.info("Next scan: %s UTC (in %.0f minutes)",
                    next_run.strftime("%Y-%m-%d %H:%M"), wait / 60)
        time.sleep(wait)
        try:
            run_daily_scan()
        except Exception as exc:
            logger.exception("Unhandled error in daily scan: %s", exc)


def print_crontab() -> None:
    """Print macOS crontab line."""
    script = os.path.abspath(__file__)
    python = sys.executable
    # macOS: use launchd instead of cron for reliability
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.options-scanner.daily</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>{script}</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>5</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>/tmp/options-scanner.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/options-scanner.err</string>
</dict>
</plist>"""
    plist_path = os.path.expanduser("~/Library/LaunchAgents/com.options-scanner.daily.plist")
    print("=== macOS LaunchAgent (recommended) ===")
    print(f"Save this XML to: {plist_path}")
    print(f"Then run: launchctl load {plist_path}")
    print()
    print(plist)

    print("\n=== Alternative: crontab (less reliable on macOS) ===")
    print(f"{SCAN_MINUTE} {SCAN_HOUR_UTC} * * * cd {os.path.dirname(script)} && {python} {script}")
    print()
    print("Install with: crontab -e  (paste the line above)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily options scanner scheduler")
    parser.add_argument("--daemon", action="store_true", help="Run as background daemon")
    parser.add_argument("--setup-cron", action="store_true", help="Print crontab/launchd config")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler()],
    )

    if args.setup_cron:
        print_crontab()
    elif args.daemon:
        daemon_mode()
    else:
        run_daily_scan()


if __name__ == "__main__":
    main()
