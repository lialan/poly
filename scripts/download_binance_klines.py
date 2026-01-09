#!/usr/bin/env python3
"""Download Binance spot klines data and store in SQLite.

Downloads 1-minute kline data for the previous 10 days from Binance public data.
Data source: https://github.com/binance/binance-public-data

Usage:
    python scripts/download_binance_klines.py
    python scripts/download_binance_klines.py --symbol ETHUSDT --days 5
    python scripts/download_binance_klines.py --symbol BTCUSDT --interval 5m
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

    async def download_range(self, days: int = 10) -> tuple[int, int]:
        """Download kline data for the past N days.

        Args:
            days: Number of days to download (default: 10).

        Returns:
            Tuple of (total_records, inserted_records).
        """
        # Calculate date range: T-days to T-1 (yesterday)
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        dates = [today - timedelta(days=d) for d in range(1, days + 1)]
        dates.reverse()  # Oldest first

        print(f"Downloading {self.symbol} {self.interval} klines")
        print(f"Date range: {dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")
        print(f"Database: {self.db_path}")
        print()

        total_records = 0
        total_inserted = 0

        async with aiohttp.ClientSession() as session:
            for date in dates:
                records = await self.download_day(session, date)
                if records:
                    inserted = self.store_records(records)
                    total_records += len(records)
                    total_inserted += inserted

        return total_records, total_inserted

    def get_stats(self) -> dict:
        """Get database statistics."""
        conn = self._get_connection()

        cursor = conn.execute(
            "SELECT COUNT(*) as count FROM klines WHERE symbol = ? AND interval = ?",
            (self.symbol, self.interval),
        )
        count = cursor.fetchone()["count"]

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
            # open_time is in microseconds (from Binance data)
            min_dt = datetime.fromtimestamp(min_time / 1_000_000, tz=timezone.utc)
            max_dt = datetime.fromtimestamp(max_time / 1_000_000, tz=timezone.utc)
        else:
            min_dt = max_dt = None

        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "count": count,
            "min_time": min_dt,
            "max_time": max_dt,
        }


async def main():
    parser = argparse.ArgumentParser(
        description="Download Binance kline data to SQLite"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="BTCUSDT",
        help="Trading pair symbol (default: BTCUSDT)",
    )
    parser.add_argument(
        "--interval",
        type=str,
        default="1m",
        help="Kline interval (default: 1m)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=10,
        help="Number of days to download (default: 10)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="SQLite database path (default: binance_klines.db)",
    )
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else None
    downloader = KlineDownloader(
        db_path=db_path,
        symbol=args.symbol,
        interval=args.interval,
    )

    try:
        total, inserted = await downloader.download_range(days=args.days)

        print()
        print("=" * 50)
        print(f"Downloaded: {total:,} klines")
        print(f"Inserted:   {inserted:,} (new records)")
        print(f"Skipped:    {total - inserted:,} (duplicates)")

        stats = downloader.get_stats()
        print()
        print("Database stats:")
        print(f"  Total {stats['symbol']} {stats['interval']} klines: {stats['count']:,}")
        if stats["min_time"] and stats["max_time"]:
            print(f"  Time range: {stats['min_time']} to {stats['max_time']}")

    finally:
        downloader.close()


if __name__ == "__main__":
    asyncio.run(main())
