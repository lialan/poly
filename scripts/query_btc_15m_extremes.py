#!/usr/bin/env python3
"""
Analyze BTC 15m market extreme probability behavior.

Queries Bigtable to find:
1. P(UP wins | hit high threshold first) - How often does hitting high% first lead to UP winning?
2. P(DOWN wins | hit low threshold first) - How often does hitting low% first lead to DOWN winning?

Usage:
    # Default: 10% threshold (90% high, 10% low)
    python scripts/query_btc_15m_extremes.py

    # Custom threshold: 15% (85% high, 15% low)
    python scripts/query_btc_15m_extremes.py -t 15

    # Multiple thresholds
    python scripts/query_btc_15m_extremes.py -t 5
    python scripts/query_btc_15m_extremes.py -t 20
"""

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from google.cloud import bigtable
import json


@dataclass
class MarketAnalysis:
    """Analysis results for a single market."""
    market_id: str
    snapshots: int
    first_extreme: str | None  # "high" or "low", or None
    final_outcome: str | None  # "up" (100%), "down" (0%), or None
    min_prob: float
    max_prob: float
    first_extreme_time: float | None
    final_time: float | None


def get_yes_mid_price(orderbook_json: str) -> float | None:
    """Extract YES mid price from orderbook JSON."""
    try:
        data = json.loads(orderbook_json)
        yes_bids = data.get("yes_bids", [])
        yes_asks = data.get("yes_asks", [])

        if not yes_bids or not yes_asks:
            return None

        # bids and asks are [(price, size), ...]
        best_bid = max(b[0] for b in yes_bids)
        best_ask = min(a[0] for a in yes_asks)

        return (best_bid + best_ask) / 2
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


def analyze_market(snapshots: list[dict], threshold: float) -> MarketAnalysis:
    """Analyze a single market's probability trajectory.

    Args:
        snapshots: List of market snapshots.
        threshold: Percentage threshold (e.g., 15 means high=85%, low=15%).
    """
    if not snapshots:
        return None

    market_id = snapshots[0].get("market_id", "unknown")

    # Sort by timestamp (oldest first)
    sorted_snaps = sorted(snapshots, key=lambda x: x.get("ts", 0))

    # Track probability over time
    probs = []
    for snap in sorted_snaps:
        orderbook = snap.get("orderbook", "{}")
        prob = get_yes_mid_price(orderbook)
        if prob is not None:
            probs.append((snap.get("ts", 0), prob))

    if not probs:
        return MarketAnalysis(
            market_id=market_id,
            snapshots=len(snapshots),
            first_extreme=None,
            final_outcome=None,
            min_prob=0,
            max_prob=0,
            first_extreme_time=None,
            final_time=None,
        )

    # Calculate thresholds from input percentage
    HIGH_THRESHOLD = (100 - threshold) / 100  # e.g., 15 -> 0.85
    LOW_THRESHOLD = threshold / 100            # e.g., 15 -> 0.15

    # Find first extreme
    first_extreme = None
    first_extreme_time = None

    for ts, prob in probs:
        if prob >= HIGH_THRESHOLD:
            first_extreme = "high"
            first_extreme_time = ts
            break
        elif prob <= LOW_THRESHOLD:
            first_extreme = "low"
            first_extreme_time = ts
            break

    # Determine final outcome from last snapshot
    final_ts, final_prob = probs[-1]
    final_outcome = None

    # Consider 95%+ as UP won, 5%- as DOWN won
    FINAL_HIGH = 0.95
    FINAL_LOW = 0.05

    if final_prob >= FINAL_HIGH:
        final_outcome = "up"
    elif final_prob <= FINAL_LOW:
        final_outcome = "down"

    min_prob = min(p for _, p in probs)
    max_prob = max(p for _, p in probs)

    return MarketAnalysis(
        market_id=market_id,
        snapshots=len(snapshots),
        first_extreme=first_extreme,
        final_outcome=final_outcome,
        min_prob=min_prob,
        max_prob=max_prob,
        first_extreme_time=first_extreme_time,
        final_time=final_ts,
    )


def query_all_markets(
    project_id: str = "poly-collector",
    instance_id: str = "poly-data",
    table_name: str = "btc_15m_snapshot",
    limit: int = 100000,
) -> dict[str, list[dict]]:
    """Query all snapshots and group by market_id."""
    client = bigtable.Client(project=project_id, admin=True)
    instance = client.instance(instance_id)
    table = instance.table(table_name)

    print(f"Querying {table_name}...")

    markets = defaultdict(list)
    row_count = 0

    for row in table.read_rows(limit=limit):
        row_count += 1
        cells = row.cells.get("data", {})

        def get_val(key: bytes) -> str | None:
            if key in cells:
                return cells[key][0].value.decode()
            return None

        market_id = get_val(b"market_id")
        if not market_id:
            continue

        snap = {
            "ts": float(get_val(b"ts") or 0),
            "market_id": market_id,
            "orderbook": get_val(b"orderbook") or "{}",
        }

        markets[market_id].append(snap)

        if row_count % 10000 == 0:
            print(f"  Processed {row_count} rows, {len(markets)} markets...")

    print(f"  Total: {row_count} rows, {len(markets)} markets")
    return dict(markets)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze BTC 15m market extreme probability behavior",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Default: 10% threshold (90% high, 10% low)
    python scripts/query_btc_15m_extremes.py

    # 15% threshold (85% high, 15% low)
    python scripts/query_btc_15m_extremes.py -t 15

    # 5% threshold (95% high, 5% low)
    python scripts/query_btc_15m_extremes.py -t 5
        """,
    )
    parser.add_argument(
        "-t", "--threshold",
        type=float,
        default=10,
        help="Threshold percentage (default: 10, meaning 90%% high / 10%% low)",
    )
    args = parser.parse_args()

    threshold = args.threshold
    high_pct = 100 - threshold
    low_pct = threshold

    print("=" * 70)
    print("BTC 15M EXTREME PROBABILITY ANALYSIS")
    print(f"Threshold: {threshold}% (High: {high_pct}%, Low: {low_pct}%)")
    print("=" * 70)

    # Query all markets
    markets_data = query_all_markets()

    if not markets_data:
        print("\nNo data found!")
        return 1

    # Analyze each market
    print(f"\nAnalyzing {len(markets_data)} markets...")
    analyses = []

    for market_id, snapshots in markets_data.items():
        analysis = analyze_market(snapshots, threshold)
        if analysis:
            analyses.append(analysis)

    # Calculate statistics
    print(f"\n{'─' * 70}")
    print("RESULTS")
    print(f"{'─' * 70}")

    # Markets that hit high% first (before low%)
    hit_high_first = [a for a in analyses if a.first_extreme == "high"]
    hit_high_then_up = [a for a in hit_high_first if a.final_outcome == "up"]
    hit_high_then_down = [a for a in hit_high_first if a.final_outcome == "down"]

    # Markets that hit low% first (before high%)
    hit_low_first = [a for a in analyses if a.first_extreme == "low"]
    hit_low_then_down = [a for a in hit_low_first if a.final_outcome == "down"]
    hit_low_then_up = [a for a in hit_low_first if a.final_outcome == "up"]

    # Markets that never hit either extreme
    no_extreme = [a for a in analyses if a.first_extreme is None]

    # Markets with resolved outcome
    resolved = [a for a in analyses if a.final_outcome is not None]

    print(f"\nTotal markets analyzed: {len(analyses)}")
    print(f"Markets with resolved outcome: {len(resolved)}")
    print()

    # Question 1: P(UP wins | hit high% first)
    print(f"{'─' * 70}")
    print(f"Q1: Markets that hit {high_pct:.0f}%+ UP before hitting {low_pct:.0f}%- UP")
    print(f"{'─' * 70}")
    print(f"  Total:           {len(hit_high_first)}")
    print(f"  Then UP won:     {len(hit_high_then_up)}")
    print(f"  Then DOWN won:   {len(hit_high_then_down)}")
    if hit_high_first:
        resolved_high = len(hit_high_then_up) + len(hit_high_then_down)
        if resolved_high > 0:
            prob = len(hit_high_then_up) / resolved_high * 100
            print(f"\n  P(UP wins | hit {high_pct:.0f}% first) = {prob:.1f}%")
            print(f"  (Based on {resolved_high} resolved markets)")

    print()

    # Question 2: P(DOWN wins | hit low% first)
    print(f"{'─' * 70}")
    print(f"Q2: Markets that hit {low_pct:.0f}%- UP before hitting {high_pct:.0f}%+ UP")
    print(f"{'─' * 70}")
    print(f"  Total:           {len(hit_low_first)}")
    print(f"  Then DOWN won:   {len(hit_low_then_down)}")
    print(f"  Then UP won:     {len(hit_low_then_up)}")
    if hit_low_first:
        resolved_low = len(hit_low_then_down) + len(hit_low_then_up)
        if resolved_low > 0:
            prob = len(hit_low_then_down) / resolved_low * 100
            print(f"\n  P(DOWN wins | hit {low_pct:.0f}% first) = {prob:.1f}%")
            print(f"  (Based on {resolved_low} resolved markets)")

    print()

    # Summary
    print(f"{'─' * 70}")
    print("SUMMARY")
    print(f"{'─' * 70}")
    print(f"  Markets never hitting {high_pct:.0f}% or {low_pct:.0f}%: {len(no_extreme)}")

    # Show some example markets
    if hit_high_first:
        print(f"\n  Example markets that hit {high_pct:.0f}% first:")
        for a in hit_high_first[:3]:
            outcome = a.final_outcome or "unresolved"
            print(f"    {a.market_id}: max={a.max_prob:.1%}, final={outcome}")

    if hit_low_first:
        print(f"\n  Example markets that hit {low_pct:.0f}% first:")
        for a in hit_low_first[:3]:
            outcome = a.final_outcome or "unresolved"
            print(f"    {a.market_id}: min={a.min_prob:.1%}, final={outcome}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
