#!/usr/bin/env python3
"""Download Binance spot klines data and store in SQLite.

Incrementally downloads 1-minute kline data from Binance public data.
Only downloads data that is missing from the local database.
Data source: https://github.com/binance/binance-public-data

Usage:
    python scripts/download_binance_klines.py              # Incremental update
    python scripts/download_binance_klines.py -s ETHUSDT   # Different symbol
    python scripts/download_binance_klines.py -d 100       # Ensure 100 days of history
    python scripts/download_binance_klines.py -c           # Check for gaps only
    python scripts/download_binance_klines.py -d 10 -f     # Force re-download
"""

import argparse
import asyncio
import io
import sqlite3
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import aiohttp

# Data URL format
BASE_URL = "https://data.binance.vision/data/spot/daily/klines"

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent / "binance_klines.db"

# Kline CSV columns (from Binance documentation)
KLINE_COLUMNS = [
    "open_time",       # Kline open time (ms timestamp)
    "open",            # Open price
    "high",            # High price
    "low",             # Low price
    "close",           # Close price
    "volume",          # Volume
    "close_time",      # Kline close time (ms timestamp)
    "quote_volume",    # Quote asset volume
    "trades",          # Number of trades
    "taker_buy_base",  # Taker buy base asset volume
    "taker_buy_quote", # Taker buy quote asset volume
    "ignore",          # Ignore
]

# SQLite schema
SCHEMA = """
CREATE TABLE IF NOT EXISTS klines (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    open_time INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    close_time INTEGER NOT NULL,
    quote_volume REAL NOT NULL,
    trades INTEGER NOT NULL,
    taker_buy_base REAL NOT NULL,
    taker_buy_quote REAL NOT NULL,
    PRIMARY KEY (symbol, interval, open_time)
);

CREATE INDEX IF NOT EXISTS idx_klines_symbol_time ON klines(symbol, interval, open_time);
"""


class KlineDownloader:
    """Downloads and stores Binance kline data."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        symbol: str = "BTCUSDT",
        interval: str = "1m",
    ):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.symbol = symbol.upper()
        self.interval = interval
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create database and tables if they don't exist."""
        conn = self._get_connection()
        conn.executescript(SCHEMA)
        conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def get_download_url(self, date: datetime) -> str:
        """Generate download URL for a specific date.

        Args:
            date: Date to download data for.

        Returns:
            Full URL to the zip file.
        """
        date_str = date.strftime("%Y-%m-%d")
        filename = f"{self.symbol}-{self.interval}-{date_str}.zip"
        return f"{BASE_URL}/{self.symbol}/{self.interval}/{filename}"

    async def download_day(
        self,
        session: aiohttp.ClientSession,
        date: datetime,
    ) -> list[dict]:
        """Download kline data for a single day.

        Args:
            session: aiohttp session.
            date: Date to download.

        Returns:
            List of kline records as dictionaries.
        """
        url = self.get_download_url(date)
        date_str = date.strftime("%Y-%m-%d")

        try:
            async with session.get(url) as resp:
                if resp.status == 404:
                    print(f"  [{date_str}] Not available (404)")
                    return []
                elif resp.status != 200:
                    print(f"  [{date_str}] HTTP {resp.status}")
                    return []

                data = await resp.read()

        except aiohttp.ClientError as e:
            print(f"  [{date_str}] Download error: {e}")
            return []

        # Extract and parse CSV from zip
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                # Get the first (and only) file in the zip
                csv_name = zf.namelist()[0]
                csv_data = zf.read(csv_name).decode("utf-8")

        except zipfile.BadZipFile:
            print(f"  [{date_str}] Invalid zip file")
            return []

        # Parse CSV lines
        records = []
        for line in csv_data.strip().split("\n"):
            if not line:
                continue
            values = line.split(",")
            if len(values) < 12:
                continue

            record = {
                "symbol": self.symbol,
                "interval": self.interval,
                "open_time": int(values[0]),
                "open": float(values[1]),
                "high": float(values[2]),
                "low": float(values[3]),
                "close": float(values[4]),
                "volume": float(values[5]),
                "close_time": int(values[6]),
                "quote_volume": float(values[7]),
                "trades": int(values[8]),
                "taker_buy_base": float(values[9]),
                "taker_buy_quote": float(values[10]),
            }
            records.append(record)

        print(f"  [{date_str}] Downloaded {len(records):,} klines")
        return records

    def store_records(self, records: list[dict]) -> int:
        """Store kline records in SQLite.

        Args:
            records: List of kline dictionaries.

        Returns:
            Number of records inserted.
        """
        if not records:
            return 0

        conn = self._get_connection()
        cursor = conn.cursor()

        inserted = 0
        for record in records:
            try:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO klines (
                        symbol, interval, open_time, open, high, low, close,
                        volume, close_time, quote_volume, trades,
                        taker_buy_base, taker_buy_quote
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["symbol"],
                        record["interval"],
                        record["open_time"],
                        record["open"],
                        record["high"],
                        record["low"],
                        record["close"],
                        record["volume"],
                        record["close_time"],
                        record["quote_volume"],
                        record["trades"],
                        record["taker_buy_base"],
                        record["taker_buy_quote"],
                    ),
                )
                if cursor.rowcount > 0:
                    inserted += 1
            except sqlite3.IntegrityError:
                pass  # Duplicate, skip

        conn.commit()
        return inserted

    async def download_dates(
        self,
        dates: list[datetime],
        show_progress: bool = True,
    ) -> tuple[int, int]:
        """Download kline data for specific dates.

        Args:
            dates: List of dates to download.
            show_progress: Whether to print progress messages.

        Returns:
            Tuple of (total_records, inserted_records).
        """
        if not dates:
            return 0, 0

        total_records = 0
        total_inserted = 0

        async with aiohttp.ClientSession() as session:
            for date in sorted(dates):
                records = await self.download_day(session, date)
                if records:
                    inserted = self.store_records(records)
                    total_records += len(records)
                    total_inserted += inserted

        return total_records, total_inserted

    async def update(self, target_days: int = 10) -> dict:
        """Incrementally update database with missing data.

        This method:
        1. Checks existing data range
        2. Finds missing dates (older history + newer data)
        3. Finds dates with gaps
        4. Downloads only what's needed
        5. Verifies continuity

        Args:
            target_days: Desired number of days of history.

        Returns:
            Dictionary with update statistics.
        """
        print(f"Updating {self.symbol} {self.interval} klines")
        print(f"Database: {self.db_path}")
        print(f"Target history: {target_days} days")
        print()

        # Check current state
        oldest, newest = self.get_time_range()
        if oldest and newest:
            print(f"Current data range: {oldest.strftime('%Y-%m-%d %H:%M')} to {newest.strftime('%Y-%m-%d %H:%M')}")
        else:
            print("No existing data found")

        # Find missing dates
        missing_dates = self.get_missing_dates(target_days)

        # Find dates with gaps (need re-download)
        print("Checking for gaps...")
        dates_with_gaps = self.get_dates_with_gaps()

        # Combine: missing dates + dates with gaps
        all_dates_to_download = set(missing_dates) | dates_with_gaps

        # Filter out today (not available yet)
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        all_dates_to_download = {d for d in all_dates_to_download if d < today}

        if not all_dates_to_download:
            print("\nDatabase is up to date! No downloads needed.")
            return {
                "downloaded": 0,
                "inserted": 0,
                "dates_checked": len(missing_dates) + len(dates_with_gaps),
                "gaps_before": len(dates_with_gaps),
                "gaps_after": 0,
            }

        print(f"\nDates to download: {len(all_dates_to_download)}")
        if missing_dates:
            print(f"  - Missing dates: {len(missing_dates)}")
        if dates_with_gaps:
            print(f"  - Dates with gaps: {len(dates_with_gaps)}")
        print()

        # Download
        total_records, total_inserted = await self.download_dates(
            list(all_dates_to_download)
        )

        # Verify continuity after download
        print("\nVerifying continuity...")
        remaining_gaps = self.find_gaps()

        return {
            "downloaded": total_records,
            "inserted": total_inserted,
            "dates_downloaded": len(all_dates_to_download),
            "gaps_before": len(dates_with_gaps),
            "gaps_after": len(remaining_gaps),
        }

    async def download_range(self, days: int = 10) -> tuple[int, int]:
        """Download kline data for the past N days (legacy method).

        Prefer using update() for incremental downloads.

        Args:
            days: Number of days to download (default: 10).

        Returns:
            Tuple of (total_records, inserted_records).
        """
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        dates = [today - timedelta(days=d) for d in range(1, days + 1)]
        return await self.download_dates(dates)

    def _normalize_timestamp(self, ts: int) -> int:
        """Normalize timestamp to milliseconds.

        Handles both millisecond (13 digits) and microsecond (16 digits) formats.
        """
        if ts > 10_000_000_000_000:  # More than 13 digits = microseconds
            return ts // 1000
        return ts

    def get_time_range(self) -> tuple[Optional[datetime], Optional[datetime]]:
        """Get the time range of existing data in the database.

        Returns:
            Tuple of (oldest_time, newest_time) as datetime objects, or (None, None) if empty.
        """
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT MIN(open_time) as min_time, MAX(open_time) as max_time
            FROM klines WHERE symbol = ? AND interval = ?
            """,
            (self.symbol, self.interval),
        )
        row = cursor.fetchone()

        min_time = row["min_time"]
        max_time = row["max_time"]

        if min_time and max_time:
            # Normalize to milliseconds and convert to datetime
            min_ms = self._normalize_timestamp(min_time)
            max_ms = self._normalize_timestamp(max_time)
            min_dt = datetime.fromtimestamp(min_ms / 1000, tz=timezone.utc)
            max_dt = datetime.fromtimestamp(max_ms / 1000, tz=timezone.utc)
            return min_dt, max_dt

        return None, None

    def get_missing_dates(self, target_days: int) -> list[datetime]:
        """Find dates that need to be downloaded.

        Args:
            target_days: Desired number of days of history.

        Returns:
            List of dates (as datetime) that need downloading.
        """
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)

        # Target date range
        target_start = today - timedelta(days=target_days)

        oldest, newest = self.get_time_range()

        if oldest is None or newest is None:
            # No data at all - download everything
            return [today - timedelta(days=d) for d in range(1, target_days + 1)]

        missing_dates = []

        # Check for dates older than what we have
        current = target_start
        while current < oldest.replace(hour=0, minute=0, second=0, microsecond=0):
            if current < today:  # Don't try to download today
                missing_dates.append(current)
            current += timedelta(days=1)

        # Check for dates newer than what we have (up to yesterday)
        newest_date = newest.replace(hour=0, minute=0, second=0, microsecond=0)
        current = newest_date + timedelta(days=1)
        while current <= yesterday:
            missing_dates.append(current)
            current += timedelta(days=1)

        return sorted(missing_dates)

    def find_gaps(self) -> list[tuple[datetime, datetime]]:
        """Find gaps in the kline data.

        Returns:
            List of (gap_start, gap_end) tuples representing missing time ranges.
        """
        conn = self._get_connection()

        # Get interval in milliseconds
        interval_ms = self._get_interval_ms()

        # Query all timestamps ordered
        cursor = conn.execute(
            """
            SELECT open_time FROM klines
            WHERE symbol = ? AND interval = ?
            ORDER BY open_time ASC
            """,
            (self.symbol, self.interval),
        )

        gaps = []
        prev_time = None

        for row in cursor:
            ts = self._normalize_timestamp(row["open_time"])

            if prev_time is not None:
                expected_next = prev_time + interval_ms
                if ts > expected_next:
                    # Gap detected
                    gap_start = datetime.fromtimestamp(expected_next / 1000, tz=timezone.utc)
                    gap_end = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                    gaps.append((gap_start, gap_end))

            prev_time = ts

        return gaps

    def _get_interval_ms(self) -> int:
        """Get interval duration in milliseconds."""
        interval_map = {
            "1m": 60 * 1000,
            "3m": 3 * 60 * 1000,
            "5m": 5 * 60 * 1000,
            "15m": 15 * 60 * 1000,
            "30m": 30 * 60 * 1000,
            "1h": 60 * 60 * 1000,
            "4h": 4 * 60 * 60 * 1000,
            "1d": 24 * 60 * 60 * 1000,
        }
        return interval_map.get(self.interval, 60 * 1000)

    def get_dates_with_gaps(self) -> set[datetime]:
        """Get dates that have gaps and need re-downloading.

        Returns:
            Set of dates (as midnight datetime) that have gaps.
        """
        gaps = self.find_gaps()
        dates_with_gaps = set()

        for gap_start, gap_end in gaps:
            # Add all dates covered by this gap
            current = gap_start.replace(hour=0, minute=0, second=0, microsecond=0)
            gap_end_date = gap_end.replace(hour=0, minute=0, second=0, microsecond=0)
            while current <= gap_end_date:
                dates_with_gaps.add(current)
                current += timedelta(days=1)

        return dates_with_gaps

    def get_stats(self) -> dict:
        """Get database statistics."""
        conn = self._get_connection()

        cursor = conn.execute(
            "SELECT COUNT(*) as count FROM klines WHERE symbol = ? AND interval = ?",
            (self.symbol, self.interval),
        )
        count = cursor.fetchone()["count"]

        oldest, newest = self.get_time_range()

        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "count": count,
            "min_time": oldest,
            "max_time": newest,
        }


def print_gaps(gaps: list[tuple[datetime, datetime]], max_show: int = 10) -> None:
    """Print gap information."""
    if not gaps:
        print("  No gaps found - data is continuous!")
        return

    print(f"  Found {len(gaps)} gap(s):")
    for i, (start, end) in enumerate(gaps[:max_show]):
        duration = end - start
        minutes = int(duration.total_seconds() / 60)
        print(f"    {i+1}. {start.strftime('%Y-%m-%d %H:%M')} to {end.strftime('%Y-%m-%d %H:%M')} ({minutes} minutes)")

    if len(gaps) > max_show:
        print(f"    ... and {len(gaps) - max_show} more gaps")


async def main():
    parser = argparse.ArgumentParser(
        description="Download Binance kline data to SQLite (incremental)"
    )
    parser.add_argument(
        "-s", "--symbol",
        type=str,
        default="BTCUSDT",
        help="Trading pair symbol (default: BTCUSDT)",
    )
    parser.add_argument(
        "-i", "--interval",
        type=str,
        default="1m",
        help="Kline interval (default: 1m)",
    )
    parser.add_argument(
        "-d", "--days",
        type=int,
        default=10,
        help="Target days of history to maintain (default: 10)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="SQLite database path (default: binance_klines.db)",
    )
    parser.add_argument(
        "-c", "--check",
        action="store_true",
        help="Check for gaps only, don't download",
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Force re-download of all dates in range (not incremental)",
    )
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else None
    downloader = KlineDownloader(
        db_path=db_path,
        symbol=args.symbol,
        interval=args.interval,
    )

    try:
        if args.check:
            # Just check for gaps
            print(f"Checking {args.symbol} {args.interval} data for gaps...")
            print(f"Database: {downloader.db_path}")
            print()

            stats = downloader.get_stats()
            print(f"Total klines: {stats['count']:,}")
            if stats["min_time"] and stats["max_time"]:
                print(f"Time range: {stats['min_time']} to {stats['max_time']}")
                days_span = (stats["max_time"] - stats["min_time"]).days
                print(f"Days span: {days_span}")
            print()

            gaps = downloader.find_gaps()
            print_gaps(gaps)

            # Show what would be downloaded
            missing = downloader.get_missing_dates(args.days)
            if missing:
                print(f"\nMissing dates for {args.days}-day target: {len(missing)}")
                for d in missing[:5]:
                    print(f"  - {d.strftime('%Y-%m-%d')}")
                if len(missing) > 5:
                    print(f"  ... and {len(missing) - 5} more")

        elif args.force:
            # Force re-download everything
            print(f"Force downloading {args.days} days of {args.symbol} {args.interval} data...")
            total, inserted = await downloader.download_range(days=args.days)

            print()
            print("=" * 50)
            print(f"Downloaded: {total:,} klines")
            print(f"Inserted:   {inserted:,} (new records)")
            print(f"Skipped:    {total - inserted:,} (duplicates)")

        else:
            # Incremental update (default)
            result = await downloader.update(target_days=args.days)

            print()
            print("=" * 50)
            print("UPDATE SUMMARY")
            print("=" * 50)
            print(f"Downloaded: {result['downloaded']:,} klines")
            print(f"Inserted:   {result['inserted']:,} (new records)")
            if result['downloaded'] > 0:
                print(f"Skipped:    {result['downloaded'] - result['inserted']:,} (duplicates)")

            if result['gaps_before'] > 0:
                print(f"\nGaps before: {result['gaps_before']}")
                print(f"Gaps after:  {result['gaps_after']}")
                if result['gaps_after'] == 0:
                    print("All gaps have been filled!")
                elif result['gaps_after'] > 0:
                    print("\nRemaining gaps (data may not be available from Binance):")
                    remaining = downloader.find_gaps()
                    print_gaps(remaining, max_show=5)

        # Always show final stats
        stats = downloader.get_stats()
        print()
        print("Database stats:")
        print(f"  Total {stats['symbol']} {stats['interval']} klines: {stats['count']:,}")
        if stats["min_time"] and stats["max_time"]:
            print(f"  Time range: {stats['min_time']} to {stats['max_time']}")
            # Calculate expected vs actual
            expected_minutes = int((stats["max_time"] - stats["min_time"]).total_seconds() / 60) + 1
            actual = stats["count"]
            if expected_minutes > 0:
                coverage = (actual / expected_minutes) * 100
                print(f"  Coverage: {coverage:.1f}% ({actual:,} of {expected_minutes:,} expected)")

    finally:
        downloader.close()


if __name__ == "__main__":
    asyncio.run(main())
