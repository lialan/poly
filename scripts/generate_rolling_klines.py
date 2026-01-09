#!/usr/bin/env python3
"""
Generate rolling N-minute klines from 1-minute kline data.

================================================================================
HOW THIS SCRIPT WORKS
================================================================================

CONCEPT:
    For each 1-minute kline, generate a corresponding N-minute kline that
    aggregates the current candle plus the next N-1 candles (T, T+1, ..., T+N-1).

    This creates a rolling/sliding window view of the market at N-minute scale.

AGGREGATION RULES:
    For klines at times T, T+1, ..., T+N-1:
    - open_time:  T (start of first candle)
    - close_time: T+N-1's close_time (end of last candle)
    - open:       T's open price
    - high:       max(all highs in window)
    - low:        min(all lows in window)
    - close:      T+N-1's close price
    - volume:     sum of all volumes
    - trades:     sum of all trades

INPUT:
    SQLite database with 1-minute klines (from download_binance_klines.py)
    Default: binance_klines.db

OUTPUT:
    New SQLite database with N-minute rolling klines
    Default: binance_rolling_{N}min_klines.db

USAGE:
    python scripts/generate_rolling_klines.py                    # 3-minute (default)
    python scripts/generate_rolling_klines.py --window 5         # 5-minute
    python scripts/generate_rolling_klines.py --window 15        # 15-minute
    python scripts/generate_rolling_klines.py --symbol ETHUSDT --window 5

================================================================================
"""

import argparse
import sqlite3
from pathlib import Path

# Default paths
DEFAULT_INPUT_DB = Path(__file__).parent.parent / "binance_klines.db"


def get_schema(window: int) -> str:
    """Get schema for N-minute klines table."""
    return f"""
DROP TABLE IF EXISTS klines_{window}min;

CREATE TABLE klines_{window}min (
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

CREATE INDEX IF NOT EXISTS idx_klines_{window}min_symbol_time ON klines_{window}min(symbol, open_time);
"""


def aggregate_klines(klines: list[dict], window: int) -> dict | None:
    """Aggregate multiple 1-min klines into a single N-min kline.

    Args:
        klines: List of N consecutive 1-minute kline dicts.
        window: Number of minutes to aggregate.

    Returns:
        Aggregated N-minute kline dict, or None if invalid input.
    """
    if len(klines) < window:
        return None

    return {
        "symbol": klines[0]["symbol"],
        "open_time": klines[0]["open_time"],
        "open": klines[0]["open"],
        "high": max(k["high"] for k in klines),
        "low": min(k["low"] for k in klines),
        "close": klines[-1]["close"],
        "volume": sum(k["volume"] for k in klines),
        "close_time": klines[-1]["close_time"],
        "trades": sum(k["trades"] for k in klines),
    }


def generate_rolling_klines(
    input_db: Path,
    output_db: Path,
    symbol: str = "BTCUSDT",
    window: int = 3,
) -> tuple[int, int]:
    """Generate N-minute rolling klines from 1-minute data.

    Args:
        input_db: Path to input SQLite database with 1-min klines.
        output_db: Path to output SQLite database for N-min klines.
        symbol: Trading pair symbol to process.
        window: Rolling window size in minutes.

    Returns:
        Tuple of (total_1min_klines, generated_Nmin_klines).
    """
    # Delete existing output file if it exists
    if output_db.exists():
        print(f"Removing existing database: {output_db}")
        output_db.unlink()

    # Connect to input database
    input_conn = sqlite3.connect(str(input_db))
    input_conn.row_factory = sqlite3.Row

    # Connect to output database and create schema
    output_conn = sqlite3.connect(str(output_db))
    output_conn.executescript(get_schema(window))
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

    if total_1min < window:
        print(f"Not enough 1-minute klines ({total_1min}) to generate {window}-minute klines")
        input_conn.close()
        output_conn.close()
        return total_1min, 0

    print(f"Processing {total_1min:,} 1-minute klines for {symbol}...")

    # Generate N-minute klines using sliding window
    generated = 0
    batch = []
    batch_size = 10000

    for i in range(len(klines) - window + 1):
        kline_window = klines[i:i + window]
        kline_nmin = aggregate_klines(kline_window, window)

        if kline_nmin:
            batch.append(kline_nmin)
            generated += 1

            if len(batch) >= batch_size:
                _insert_batch(output_conn, batch, window)
                batch = []
                print(f"  Generated {generated:,} {window}-minute klines...")

    # Insert remaining batch
    if batch:
        _insert_batch(output_conn, batch, window)

    input_conn.close()
    output_conn.close()

    return total_1min, generated


def _insert_batch(conn: sqlite3.Connection, klines: list[dict], window: int) -> None:
    """Insert a batch of N-minute klines."""
    conn.executemany(
        f"""
        INSERT OR REPLACE INTO klines_{window}min
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


def get_stats(db_path: Path, symbol: str, window: int) -> dict:
    """Get statistics for N-minute klines in database."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    cursor = conn.execute(
        f"SELECT COUNT(*) as count FROM klines_{window}min WHERE symbol = ?",
        (symbol,)
    )
    count = cursor.fetchone()["count"]

    cursor = conn.execute(
        f"""
        SELECT MIN(open_time) as min_time, MAX(open_time) as max_time
        FROM klines_{window}min WHERE symbol = ?
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
        description="Generate rolling N-minute klines from 1-minute data"
    )
    parser.add_argument(
        "--window", "-w",
        type=int,
        default=3,
        help="Rolling window size in minutes (default: 3)",
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
        help="Output SQLite database path (default: binance_rolling_{N}min_klines.db)",
    )
    args = parser.parse_args()

    input_db = Path(args.input) if args.input else DEFAULT_INPUT_DB
    output_db = Path(args.output) if args.output else (
        Path(__file__).parent.parent / f"binance_rolling_{args.window}min_klines.db"
    )

    if not input_db.exists():
        print(f"Error: Input database not found: {input_db}")
        print("Run download_binance_klines.py first to download 1-minute kline data.")
        return 1

    print("=" * 60)
    print(f"GENERATE {args.window}-MINUTE ROLLING KLINES")
    print("=" * 60)
    print(f"Input:  {input_db}")
    print(f"Output: {output_db}")
    print(f"Symbol: {args.symbol}")
    print(f"Window: {args.window} minutes")
    print()

    total_1min, generated = generate_rolling_klines(
        input_db, output_db, args.symbol, args.window
    )

    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"1-minute klines processed: {total_1min:,}")
    print(f"{args.window}-minute klines generated: {generated:,}")

    if generated > 0:
        stats = get_stats(output_db, args.symbol, args.window)
        print(f"\nDatabase stats:")
        print(f"  Total {args.window}-min klines: {stats['count']:,}")

    return 0


if __name__ == "__main__":
    exit(main())
