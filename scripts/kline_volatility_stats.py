#!/usr/bin/env python3
"""
Calculate volatility statistics from rolling N-minute klines using log returns.

Generates rolling klines on-the-fly from 1-minute data with configurable window.

Volatility metrics:
1. Intra-candle range: log(high/low) - price range within each candle
2. Close-to-close return: log(close_t / close_{t-1}) - return between candles
3. Open-to-close return: log(close/open) - directional move within candle

Usage:
    python scripts/kline_volatility_stats.py           # 3-minute (default)
    python scripts/kline_volatility_stats.py -w 5      # 5-minute
    python scripts/kline_volatility_stats.py -w 15     # 15-minute
    python scripts/kline_volatility_stats.py -s ETHUSDT -w 5
"""

import argparse
import math
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).parent.parent / "binance_klines.db"


def calc_stats(values: list[float]) -> dict:
    """Calculate statistics for a list of values."""
    if not values:
        return {}

    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mean = sum(values) / n
    median = sorted_vals[n // 2]

    # Standard deviation
    variance = sum((x - mean) ** 2 for x in values) / n
    std = math.sqrt(variance)

    # Percentiles
    p5 = sorted_vals[int(n * 0.05)]
    p25 = sorted_vals[int(n * 0.25)]
    p66 = sorted_vals[int(n * 0.66)]
    p75 = sorted_vals[int(n * 0.75)]
    p95 = sorted_vals[int(n * 0.95)]
    p99 = sorted_vals[int(n * 0.99)]

    return {
        "count": n,
        "mean": mean,
        "median": median,
        "std": std,
        "min": sorted_vals[0],
        "max": sorted_vals[-1],
        "p5": p5,
        "p25": p25,
        "p66": p66,
        "p75": p75,
        "p95": p95,
        "p99": p99,
    }


def aggregate_klines(klines: list[dict], window: int) -> list[dict]:
    """Aggregate 1-minute klines into rolling N-minute klines.

    Args:
        klines: List of 1-minute kline dicts with open/high/low/close.
        window: Number of minutes to aggregate.

    Returns:
        List of aggregated klines.
    """
    if len(klines) < window:
        return []

    result = []
    for i in range(len(klines) - window + 1):
        w = klines[i:i + window]
        result.append({
            "open": w[0]["open"],
            "high": max(k["high"] for k in w),
            "low": min(k["low"] for k in w),
            "close": w[-1]["close"],
        })

    return result


def main():
    parser = argparse.ArgumentParser(description="Calculate kline volatility statistics")
    parser.add_argument("--db", type=str, default=None, help="Database path (1-min klines)")
    parser.add_argument("-s", "--symbol", type=str, default="BTCUSDT", help="Symbol (default: BTCUSDT)")
    parser.add_argument("-w", "--window", type=int, default=3, help="Rolling window in minutes (default: 3)")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else DEFAULT_DB

    if not db_path.exists():
        print(f"Error: Database not found: {db_path}")
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Query all 1-minute klines
    cursor = conn.execute(
        """
        SELECT open, high, low, close
        FROM klines
        WHERE symbol = ? AND interval = '1m'
        ORDER BY open_time ASC
        """,
        (args.symbol,)
    )

    klines_1m = [dict(row) for row in cursor.fetchall()]
    conn.close()

    if len(klines_1m) < args.window:
        print(f"Not enough data (need at least {args.window} klines)")
        return 1

    print("=" * 70)
    print(f"VOLATILITY ANALYSIS - {args.symbol} {args.window}-MINUTE ROLLING KLINES")
    print("=" * 70)
    print(f"1-minute klines: {len(klines_1m):,}")

    # Generate rolling klines
    klines = aggregate_klines(klines_1m, args.window)
    print(f"{args.window}-minute klines: {len(klines):,}")
    print()

    # Calculate log returns
    intra_range = []      # log(high/low)
    open_to_close = []    # log(close/open)
    close_to_close = []   # log(close_t / close_{t-1})
    open_to_high = []     # log(open/high) - always <= 0
    open_to_low = []      # log(open/low) - always >= 0
    max_excursion = []    # max(|log(O/H)|, |log(O/L)|) - max move from open

    prev_close = None
    for k in klines:
        # Intra-candle range
        if k["high"] > 0 and k["low"] > 0:
            intra_range.append(math.log(k["high"] / k["low"]))

        # Open to close
        if k["close"] > 0 and k["open"] > 0:
            open_to_close.append(math.log(k["close"] / k["open"]))

        # Close to close (consecutive)
        if prev_close and k["close"] > 0:
            close_to_close.append(math.log(k["close"] / prev_close))

        # Open to high and low (extremes)
        if k["open"] > 0 and k["high"] > 0 and k["low"] > 0:
            o_to_h = math.log(k["open"] / k["high"])  # <= 0
            o_to_l = math.log(k["open"] / k["low"])   # >= 0
            open_to_high.append(o_to_h)
            open_to_low.append(o_to_l)
            max_excursion.append(max(abs(o_to_h), abs(o_to_l)))

        prev_close = k["close"]

    # Calculate and print statistics
    def print_stats(name: str, values: list[float], multiplier: float = 100):
        """Print statistics, converting to percentage."""
        stats = calc_stats(values)
        if not stats:
            return

        print(f"{'─' * 70}")
        print(f"{name}")
        print(f"{'─' * 70}")
        print(f"  Count:   {stats['count']:,}")
        print(f"  Mean:    {stats['mean'] * multiplier:+.4f}%")
        print(f"  Median:  {stats['median'] * multiplier:+.4f}%")
        print(f"  Std Dev: {stats['std'] * multiplier:.4f}%")
        print(f"  Min:     {stats['min'] * multiplier:+.4f}%")
        print(f"  Max:     {stats['max'] * multiplier:+.4f}%")
        print(f"  P5:      {stats['p5'] * multiplier:+.4f}%")
        print(f"  P25:     {stats['p25'] * multiplier:+.4f}%")
        print(f"  P75:     {stats['p75'] * multiplier:+.4f}%")
        print(f"  P95:     {stats['p95'] * multiplier:+.4f}%")
        print()

        return stats

    print()

    # 1. Intra-candle range (always positive)
    intra_stats = print_stats("1. INTRA-CANDLE RANGE: log(high/low)", intra_range)

    # 2. Open-to-close return (can be positive or negative)
    otc_stats = print_stats("2. OPEN-TO-CLOSE RETURN: log(close/open)", open_to_close)

    # 3. Close-to-close return
    ctc_stats = print_stats("3. CLOSE-TO-CLOSE RETURN: log(close_t / close_{t-1})", close_to_close)

    # 4. Open to high (always <= 0)
    print_stats("4. OPEN-TO-HIGH: log(open/high)", open_to_high)

    # 5. Open to low (always >= 0)
    print_stats("5. OPEN-TO-LOW: log(open/low)", open_to_low)

    # Absolute returns for volatility measure
    abs_otc = [abs(x) for x in open_to_close]
    abs_ctc = [abs(x) for x in close_to_close]
    abs_oth = [abs(x) for x in open_to_high]
    abs_otl = [abs(x) for x in open_to_low]

    print("=" * 70)
    print("ABSOLUTE RETURNS (for volatility measurement)")
    print("=" * 70)
    print()

    print_stats("6. |OPEN-TO-CLOSE|: Absolute intra-candle move", abs_otc)
    print_stats("7. |CLOSE-TO-CLOSE|: Absolute inter-candle move", abs_ctc)
    print_stats("8. |OPEN-TO-HIGH|: Upside excursion from open", abs_oth)
    print_stats("9. |OPEN-TO-LOW|: Downside excursion from open", abs_otl)
    print_stats("10. MAX-EXCURSION: max(|log(O/H)|, |log(O/L)|)", max_excursion)

    # Summary table
    print("=" * 70)
    print(f"SUMMARY: {args.window}-minute {args.symbol} volatility (log returns)")
    print("=" * 70)

    intra_stats = calc_stats(intra_range)
    abs_otc_stats = calc_stats(abs_otc)
    abs_ctc_stats = calc_stats(abs_ctc)
    abs_oth_stats = calc_stats(abs_oth)
    abs_otl_stats = calc_stats(abs_otl)
    max_exc_stats = calc_stats(max_excursion)

    # Table header
    metrics = ["Mean", "Median", "StdDev", "P66", "P75", "P95", "P99"]
    col_width = 9

    # Row labels
    rows = [
        ("log(H/L)", intra_stats),
        ("|log(C/O)|", abs_otc_stats),
        ("|log(Ct/Ct-1)|", abs_ctc_stats),
        ("|log(O/H)|", abs_oth_stats),
        ("|log(O/L)|", abs_otl_stats),
        ("MaxExcursion", max_exc_stats),
    ]

    # Print header
    print()
    print(f"  {'Metric':<15}", end="")
    for m in metrics:
        print(f"{m:>{col_width}}", end="")
    print()
    print(f"  {'-' * 15}", end="")
    for _ in metrics:
        print(f"{'-' * col_width}", end="")
    print()

    # Print rows
    for label, stats in rows:
        print(f"  {label:<15}", end="")
        print(f"{stats['mean'] * 100:>{col_width}.4f}", end="")
        print(f"{stats['median'] * 100:>{col_width}.4f}", end="")
        print(f"{stats['std'] * 100:>{col_width}.4f}", end="")
        print(f"{stats['p66'] * 100:>{col_width}.4f}", end="")
        print(f"{stats['p75'] * 100:>{col_width}.4f}", end="")
        print(f"{stats['p95'] * 100:>{col_width}.4f}", end="")
        print(f"{stats['p99'] * 100:>{col_width}.4f}")

    print()
    print("  All values in % (multiply by 100 for basis points)")
    print()

    return 0


if __name__ == "__main__":
    exit(main())
