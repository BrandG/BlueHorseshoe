"""
Watchlist monitor for live IBKR quote polling.

Polls quotes for a watchlist of symbols at a configurable interval,
displays a live terminal dashboard, and logs to CSV.
"""
import csv
import logging
import os
import sys
import time
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from bluehorseshoe.core.config import REPO_ROOT
from bluehorseshoe.core.market_calendar import nyse_holidays_for_year
from bluehorseshoe.data.ibkr_client import IBKRClient, QuoteData

logger = logging.getLogger(__name__)

DEFAULT_WATCHLIST_PATH = f"{REPO_ROOT}/src/watchlist.txt"

# Backward-compatible alias retained for existing imports and tests.
_nyse_holidays_for_year = nyse_holidays_for_year


def load_watchlist(path: str = DEFAULT_WATCHLIST_PATH) -> List[str]:
    """
    Read a watchlist file, returning a list of uppercase symbols.

    Lines starting with '#' are comments; blank lines are skipped.
    Returns an empty list if the file does not exist.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            symbols = []
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                symbols.append(stripped.upper())
            return symbols
    except FileNotFoundError:
        logger.warning("Watchlist file not found: %s", path)
        return []
    except (OSError, IOError) as e:
        logger.error("Error reading watchlist file: %s", e)
        return []


class WatchlistMonitor:
    """
    Long-running monitor that polls IBKR quotes at a fixed interval,
    displays a live terminal table, and logs snapshots to CSV.
    """

    def __init__(
        self,
        client: IBKRClient,
        symbols: List[str],
        poll_interval: int = 60,
        csv_path: Optional[str] = None,
    ):
        self._client = client
        self._symbols = symbols
        self._poll_interval = poll_interval
        self._csv_path = csv_path or self._default_csv_path()
        self._csv_initialized = False

    @staticmethod
    def _default_csv_path() -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        return f"{REPO_ROOT}/src/logs/watchlist_{today}.csv"

    def run(self) -> None:
        """Main loop: poll → display → log → sleep. Ctrl-C for clean exit."""
        print(f"Monitoring {len(self._symbols)} symbols every {self._poll_interval}s")
        print(f"CSV log: {self._csv_path}")
        print("Press Ctrl-C to stop.\n")

        try:
            while True:
                if self._is_market_open():
                    quotes = self._poll()
                    self._display(quotes)
                    self._log_csv(quotes)
                else:
                    self._display_closed()
                self._countdown(self._poll_interval)
        except KeyboardInterrupt:
            print("\nMonitor stopped.")

    @staticmethod
    def _is_market_open(now: Optional[datetime] = None) -> bool:
        """Check if US equity market is currently open (Mon-Fri 9:30-16:00 ET)."""
        eastern = ZoneInfo("America/New_York")
        now_et = now or datetime.now(eastern)
        if now_et.tzinfo is None:
            now_et = now_et.replace(tzinfo=eastern)
        # Weekend: Monday=0 .. Sunday=6
        if now_et.weekday() >= 5:
            return False
        # NYSE holidays
        if now_et.date() in nyse_holidays_for_year(now_et.year):
            return False
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        return market_open <= now_et < market_close

    def _display_closed(self) -> None:
        """Show a market-closed banner instead of quote data."""
        sys.stdout.write("\033[H\033[J")
        eastern = ZoneInfo("America/New_York")
        now_et = datetime.now(eastern)
        print(f"  Watchlist Monitor  |  {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}  |  {len(self._symbols)} symbols")
        print("=" * 90)
        print("  Market is closed. Waiting for next open (Mon-Fri 9:30-16:00 ET, excluding holidays)...")
        print("=" * 90)
        sys.stdout.flush()

    def _poll(self) -> List[QuoteData]:
        """Fetch snapshot quotes for all symbols."""
        return self._client.get_quotes(self._symbols)

    def _display(self, quotes: List[QuoteData]) -> None:
        """Clear terminal and print a formatted quote table."""
        # ANSI clear screen
        sys.stdout.write("\033[H\033[J")

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"  Watchlist Monitor  |  {now}  |  {len(self._symbols)} symbols")
        print("=" * 90)
        print(
            f"  {'Symbol':<8} {'Last':>10} {'Bid':>10} {'Ask':>10} "
            f"{'Change':>10} {'Volume':>12} {'Time':>10}"
        )
        print("-" * 90)

        for q in quotes:
            if q.error:
                print(f"  {q.symbol:<8} ERROR: {q.error}")
                continue

            last_str = f"${q.last:.2f}" if q.last is not None else "N/A"
            bid_str = f"${q.bid:.2f}" if q.bid is not None else "N/A"
            ask_str = f"${q.ask:.2f}" if q.ask is not None else "N/A"
            vol_str = f"{q.volume:,}" if q.volume is not None else "N/A"
            ts_str = q.timestamp.strftime("%H:%M:%S") if q.timestamp else "N/A"

            # Calculate change from close if available
            if q.last is not None and q.close is not None and q.close != 0:
                change = q.last - q.close
                change_pct = (change / q.close) * 100
                change_str = f"{change:+.2f} ({change_pct:+.1f}%)"
            else:
                change_str = "N/A"

            print(
                f"  {q.symbol:<8} {last_str:>10} {bid_str:>10} {ask_str:>10} "
                f"{change_str:>10} {vol_str:>12} {ts_str:>10}"
            )

        print("=" * 90)
        sys.stdout.flush()

    def _log_csv(self, quotes: List[QuoteData]) -> None:
        """Append quote data to CSV file, creating header on first write."""
        header = ["timestamp", "symbol", "last", "bid", "ask", "open", "high", "low", "volume"]
        write_header = not self._csv_initialized and not os.path.exists(self._csv_path)

        os.makedirs(os.path.dirname(self._csv_path), exist_ok=True)

        with open(self._csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(header)
            self._csv_initialized = True

            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for q in quotes:
                if q.error:
                    continue
                writer.writerow([
                    now,
                    q.symbol,
                    f"{q.last:.2f}" if q.last is not None else "",
                    f"{q.bid:.2f}" if q.bid is not None else "",
                    f"{q.ask:.2f}" if q.ask is not None else "",
                    f"{q.open:.2f}" if q.open is not None else "",
                    f"{q.high:.2f}" if q.high is not None else "",
                    f"{q.low:.2f}" if q.low is not None else "",
                    q.volume if q.volume is not None else "",
                ])

    @staticmethod
    def _countdown(seconds: int) -> None:
        """Sleep with a visible countdown on the last line."""
        for remaining in range(seconds, 0, -1):
            sys.stdout.write(f"\r  Next refresh in {remaining:3d}s... ")
            sys.stdout.flush()
            time.sleep(1)
