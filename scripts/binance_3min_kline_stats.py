#!/usr/bin/env python3
"""
Generate rolling 3-minute klines from 1-minute kline data.

================================================================================
HOW THIS SCRIPT WORKS
================================================================================

CONCEPT:
    For each 1-minute kline, generate a corresponding 3-minute kline that
    aggregates the current candle plus the next 2 candles (T, T+1, T+2).

    This creates a rolling/sliding window view of the market at 3-minute scale.

AGGREGATION RULES:
    For klines at times T, T+1, T+2:
    - open_time:  T (start of first candle)
    - close_time: T+2's close_time (end of third candle)
    - open:       T's open price
    - high:       max(T.high, T+1.high, T+2.high)
    - low:        min(T.low, T+1.low, T+2.low)
    - close:      T+2's close price
    - volume:     sum of all volumes
    - trades:     sum of all trades

INPUT:
    SQLite database with 1-minute klines (from download_binance_klines.py)
    Default: binance_klines.db

OUTPUT:
    New SQLite database with 3-minute rolling klines
    Default: binance_3min_klines.db

USAGE:
    python scripts/binance_3min_kline_stats.py
    python scripts/binance_3min_kline_stats.py --symbol ETHUSDT
    python scripts/binance_3min_kline_stats.py --input custom.db --output custom_3min.db

================================================================================
"""

import argparse
import sqlite3
from pathlib import Path

# Default paths
DEFAULT_INPUT_DB = Path(__file__).parent.parent / "binance_klines.db"
DEFAULT_OUTPUT_DB = Path(__file__).parent.parent / "binance_3min_klines.db"

# Schema for 3-minute klines
SCHEMA = """
CREATE TABLE IF NOT EXISTS klines_3min (
    symbol TEXT NOT NULL,
    open_time INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    close_time INTEGER NOT NULL,
    trades INTEGER NOT NULL,
    PRIMARY KEY (symbol, open_time)
);

CREATE INDEX IF NOT EXISTS idx_klines_3min_symbol_time ON klines_3min(symbol, open_time);
"""


def aggregate_klines(klines: list[dict]) -> dict | None:
    """Aggregate multiple 1-min klines into a single 3-min kline.

    Args:
        klines: List of 3 consecutive 1-minute kline dicts.

    Returns:
        Aggregated 3-minute kline dict, or None if invalid input.
    """
    if len(klines) < 3:
        return None

    k0, k1, k2 = klines[0], klines[1], klines[2]

    return {
        "symbol": k0["symbol"],
        "open_time": k0["open_time"],
        "open": k0["open"],
        "high": max(k0["high"], k1["high"], k2["high"]),
        "low": min(k0["low"], k1["low"], k2["low"]),
        "close": k2["close"],
        "volume": k0["volume"] + k1["volume"] + k2["volume"],
        "close_time": k2["close_time"],
        "trades": k0["trades"] + k1["trades"] + k2["trades"],
    }


def generate_3min_klines(
    input_db: Path,
    output_db: Path,
    symbol: str = "BTCUSDT",
) -> tuple[int, int]:
    """Generate 3-minute rolling klines from 1-minute data.

    Args:
        input_db: Path to input SQLite database with 1-min klines.
        output_db: Path to output SQLite database for 3-min klines.
        symbol: Trading pair symbol to process.

    Returns:
        Tuple of (total_1min_klines, generated_3min_klines).
    """
    # Connect to input database
    input_conn = sqlite3.connect(str(input_db))
    input_conn.row_factory = sqlite3.Row

    # Connect to output database and create schema
    output_conn = sqlite3.connect(str(output_db))
    output_conn.executescript(SCHEMA)
    output_conn.commit()

    # Query all 1-minute klines for the symbol, ordered by time
    cursor = input_conn.execute(
        """
        SELECT symbol, open_time, open, high, low, close, volume, close_time, trades
        FROM klines
        WHERE symbol = ? AND interval = '1m'
        ORDER BY open_time ASC
        """,
        (symbol,)
    )

    # Load all klines into memory (for sliding window)
    klines = [dict(row) for row in cursor.fetchall()]
    total_1min = len(klines)

    if total_1min < 3:
        print(f"Not enough 1-minute klines ({total_1min}) to generate 3-minute klines")
        input_conn.close()
        output_conn.close()
        return total_1min, 0

    print(f"Processing {total_1min:,} 1-minute klines for {symbol}...")

    # Generate 3-minute klines using sliding window
    generated = 0
    batch = []
    batch_size = 10000

    for i in range(len(klines) - 2):  # Stop 2 before end (need 3 candles)
        window = klines[i:i+3]
        kline_3min = aggregate_klines(window)

        if kline_3min:
            batch.append(kline_3min)
            generated += 1

            if len(batch) >= batch_size:
                _insert_batch(output_conn, batch)
                batch = []
                print(f"  Generated {generated:,} 3-minute klines...")

    # Insert remaining batch
    if batch:
        _insert_batch(output_conn, batch)

    input_conn.close()
    output_conn.close()

    return total_1min, generated


def _insert_batch(conn: sqlite3.Connection, klines: list[dict]) -> None:
    """Insert a batch of 3-minute klines."""
    conn.executemany(
        """
        INSERT OR REPLACE INTO klines_3min
        (symbol, open_time, open, high, low, close, volume, close_time, trades)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                k["symbol"],
                k["open_time"],
                k["open"],
                k["high"],
                k["low"],
                k["close"],
                k["volume"],
                k["close_time"],
                k["trades"],
            )
            for k in klines
        ]
    )
    conn.commit()


def get_stats(db_path: Path, symbol: str) -> dict:
    """Get statistics for 3-minute klines in database."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    cursor = conn.execute(
        "SELECT COUNT(*) as count FROM klines_3min WHERE symbol = ?",
        (symbol,)
    )
    count = cursor.fetchone()["count"]

    cursor = conn.execute(
        """
        SELECT MIN(open_time) as min_time, MAX(open_time) as max_time
        FROM klines_3min WHERE symbol = ?
        """,
        (symbol,)
    )
    row = cursor.fetchone()

    conn.close()

    return {
        "symbol": symbol,
        "count": count,
        "min_time": row["min_time"],
        "max_time": row["max_time"],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate rolling 3-minute klines from 1-minute data"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="BTCUSDT",
        help="Trading pair symbol (default: BTCUSDT)",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="Input SQLite database path (default: binance_klines.db)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output SQLite database path (default: binance_3min_klines.db)",
    )
    args = parser.parse_args()

    input_db = Path(args.input) if args.input else DEFAULT_INPUT_DB
    output_db = Path(args.output) if args.output else DEFAULT_OUTPUT_DB

    if not input_db.exists():
        print(f"Error: Input database not found: {input_db}")
        print("Run download_binance_klines.py first to download 1-minute kline data.")
        return 1

    print("=" * 60)
    print("GENERATE 3-MINUTE ROLLING KLINES")
    print("=" * 60)
    print(f"Input:  {input_db}")
    print(f"Output: {output_db}")
    print(f"Symbol: {args.symbol}")
    print()

    total_1min, generated = generate_3min_klines(input_db, output_db, args.symbol)

    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"1-minute klines processed: {total_1min:,}")
    print(f"3-minute klines generated: {generated:,}")

    if generated > 0:
        stats = get_stats(output_db, args.symbol)
        print(f"\nDatabase stats:")
        print(f"  Total 3-min klines: {stats['count']:,}")

    return 0


if __name__ == "__main__":
    exit(main())
