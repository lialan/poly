#!/usr/bin/env python3
"""
Analyze BTC 15m market extreme probability behavior.

================================================================================
HOW THIS SCRIPT WORKS
================================================================================

CONCEPT:
    BTC 15-minute prediction markets on Polymarket have YES tokens representing
    "BTC will be UP from the start price at resolution". This script analyzes
    what happens when the YES probability hits extreme values (e.g., 85% or 15%).

    Key question: If the market hits 85% YES early, how often does UP actually win?

METHODOLOGY:
    1. Query all BTC 15m market snapshots from Bigtable
    2. For each market, track the YES probability over time
    3. Identify which extreme threshold was hit FIRST (high or low)
    4. Check the final outcome (UP won = prob >= 95%, DOWN won = prob <= 5%)
    5. Calculate P(UP wins | hit high% first) and P(DOWN wins | hit low% first)

THRESHOLDS:
    The -t flag sets the threshold percentage. For -t 15:
      - High threshold: 85% (100 - 15)
      - Low threshold:  15%
      - Approach zone:  ±5% from threshold (80% for high, 20% for low)

METRICS REPORTED:
    For each direction (hit high first / hit low first):

    1. P(success) - Probability that hitting the threshold leads to correct outcome

    2. Log(price) delta - BTC price change from market start to threshold hit
       Helps identify if price momentum correlates with prediction accuracy

    3. Time to threshold - How long from market start until threshold was hit
       - Delta time: Time spent in "approach zone" (threshold ±5%) before hitting
       - Distribution: Bucketed by time (0-3min, 3-6min, etc.) with success rates
       - Avg depth: Average orderbook depth at threshold hit per time bucket

USAGE:
    python scripts/query_btc_15m_extremes.py           # Default: 10% threshold
    python scripts/query_btc_15m_extremes.py -t 15    # 15% threshold (85%/15%)
    python scripts/query_btc_15m_extremes.py -t 20    # 20% threshold (80%/20%)

================================================================================
"""

import argparse
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from google.cloud import bigtable
import json


@dataclass
class MarketAnalysis:
    """Analysis results for a single market."""
    market_id: str
    first_extreme: str | None      # "high" or "low", or None if never hit
    final_outcome: str | None      # "up", "down", or None if unresolved
    log_price_delta: float | None  # log(threshold_price / start_price)
    time_to_threshold: float | None
    time_from_approach: float | None
    threshold_depth: float | None


def get_yes_mid_price(orderbook_json: str) -> float | None:
    """Extract YES mid price from orderbook JSON."""
    try:
        data = json.loads(orderbook_json)
        yes_bids = data.get("yes_bids", [])
        yes_asks = data.get("yes_asks", [])
        if not yes_bids or not yes_asks:
            return None
        best_bid = max(b[0] for b in yes_bids)
        best_ask = min(a[0] for a in yes_asks)
        return (best_bid + best_ask) / 2
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


def get_orderbook_depth(orderbook_json: str) -> float | None:
    """Extract total orderbook depth (shares) from orderbook JSON."""
    try:
        data = json.loads(orderbook_json)
        total = sum(
            order[1]
            for key in ["yes_bids", "yes_asks", "no_bids", "no_asks"]
            for order in data.get(key, [])
        )
        return total if total > 0 else None
    except (json.JSONDecodeError, KeyError, ValueError, TypeError, IndexError):
        return None


def analyze_market(snapshots: list[dict], threshold: float) -> MarketAnalysis | None:
    """Analyze a single market's probability trajectory."""
    if not snapshots:
        return None

    market_id = snapshots[0].get("market_id", "unknown")
    sorted_snaps = sorted(snapshots, key=lambda x: x.get("ts", 0))

    # Extract data points: (timestamp, probability, spot_price, orderbook_json)
    data_points = []
    for snap in sorted_snaps:
        orderbook = snap.get("orderbook", "{}")
        prob = get_yes_mid_price(orderbook)
        if prob is not None:
            data_points.append((
                snap.get("ts", 0),
                prob,
                snap.get("spot_price", 0),
                orderbook
            ))

    if not data_points:
        return None

    # Thresholds
    HIGH_THRESHOLD = (100 - threshold) / 100
    LOW_THRESHOLD = threshold / 100
    APPROACH_MARGIN = 0.05
    HIGH_APPROACH = HIGH_THRESHOLD - APPROACH_MARGIN
    LOW_APPROACH = LOW_THRESHOLD + APPROACH_MARGIN

    start_time = data_points[0][0]
    start_price = data_points[0][2] if data_points[0][2] > 0 else None

    # Find first extreme hit
    first_extreme = None
    threshold_time = None
    threshold_price = None
    threshold_depth = None
    approach_time = None

    for ts, prob, price, ob_json in data_points:
        # Track approach zone entry
        if approach_time is None:
            if HIGH_APPROACH <= prob < HIGH_THRESHOLD:
                approach_time = ts
            elif LOW_THRESHOLD < prob <= LOW_APPROACH:
                approach_time = ts

        if prob >= HIGH_THRESHOLD:
            first_extreme = "high"
            threshold_time = ts
            threshold_price = price if price > 0 else None
            threshold_depth = get_orderbook_depth(ob_json)
            if approach_time is None:
                approach_time = ts
            break
        elif prob <= LOW_THRESHOLD:
            first_extreme = "low"
            threshold_time = ts
            threshold_price = price if price > 0 else None
            threshold_depth = get_orderbook_depth(ob_json)
            if approach_time is None:
                approach_time = ts
            break

    # Calculate derived metrics
    log_price_delta = None
    if start_price and threshold_price and start_price > 0 and threshold_price > 0:
        log_price_delta = math.log(threshold_price) - math.log(start_price)

    time_to_threshold = threshold_time - start_time if threshold_time else None
    time_from_approach = threshold_time - approach_time if threshold_time and approach_time else None

    # Determine final outcome (95%+ = UP won, 5%- = DOWN won)
    final_prob = data_points[-1][1]
    final_outcome = "up" if final_prob >= 0.95 else "down" if final_prob <= 0.05 else None

    return MarketAnalysis(
        market_id=market_id,
        first_extreme=first_extreme,
        final_outcome=final_outcome,
        log_price_delta=log_price_delta,
        time_to_threshold=time_to_threshold,
        time_from_approach=time_from_approach,
        threshold_depth=threshold_depth,
    )


def query_all_markets(
    project_id: str = "poly-collector",
    instance_id: str = "poly-data",
    table_name: str = "btc_15m_snapshot",
    limit: int = 100000,
) -> dict[str, list[dict]]:
    """Query all snapshots from Bigtable and group by market_id."""
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
            return cells[key][0].value.decode() if key in cells else None

        market_id = get_val(b"market_id")
        if not market_id:
            continue

        markets[market_id].append({
            "ts": float(get_val(b"ts") or 0),
            "market_id": market_id,
            "orderbook": get_val(b"orderbook") or "{}",
            "spot_price": float(get_val(b"spot_price") or 0),
        })

        if row_count % 10000 == 0:
            print(f"  Processed {row_count} rows, {len(markets)} markets...")

    print(f"  Total: {row_count} rows, {len(markets)} markets")
    return dict(markets)


# ============================================================================
# Output helpers
# ============================================================================

def calc_stats(values: list[float]) -> tuple[float, float, float, float]:
    """Calculate min, max, mean, median for a list of values."""
    sorted_vals = sorted(values)
    return (
        min(values),
        max(values),
        sum(values) / len(values),
        sorted_vals[len(sorted_vals) // 2]
    )


def print_price_delta(label: str, analyses: list[MarketAnalysis]) -> None:
    """Print log price delta statistics."""
    deltas = [a.log_price_delta for a in analyses if a.log_price_delta is not None]
    if not deltas:
        return
    mn, mx, mean, median = calc_stats(deltas)
    print(f"\n  Log(price) delta when threshold hit ({label}):")
    print(f"    Count:  {len(deltas)}")
    print(f"    Min:    {mn*100:+.4f}%")
    print(f"    Max:    {mx*100:+.4f}%")
    print(f"    Mean:   {mean*100:+.4f}%")
    print(f"    Median: {median*100:+.4f}%")


def print_time_analysis(
    correct: list[MarketAnalysis],
    all_resolved: list[MarketAnalysis],
    is_correct_fn: Callable[[MarketAnalysis], bool],
    approach_label: str,
) -> None:
    """Print time to threshold analysis with distribution."""
    times_correct = [a.time_to_threshold for a in correct if a.time_to_threshold is not None]
    if not times_correct:
        return

    mn, mx, mean, median = calc_stats(times_correct)
    print(f"\n  Time to threshold (CORRECT predictions):")
    print(f"    Count:  {len(times_correct)}")
    print(f"    Min:    {mn:.1f}s")
    print(f"    Max:    {mx:.1f}s")
    print(f"    Mean:   {mean:.1f}s")
    print(f"    Median: {median:.1f}s")

    # Delta time (approach zone to threshold)
    delta_times = [a.time_from_approach for a in correct if a.time_from_approach is not None]
    if delta_times:
        _, _, delta_mean, delta_median = calc_stats(delta_times)
        print(f"    Delta ({approach_label}): min={min(delta_times):.1f}s, max={max(delta_times):.1f}s, mean={delta_mean:.1f}s, median={delta_median:.1f}s")

    # Distribution buckets (0-3min, 3-6min, 6-9min, 9-12min, 12-15min)
    buckets_correct = [0] * 5
    buckets_total = [0] * 5
    buckets_depth: list[list[float]] = [[] for _ in range(5)]

    for a in correct:
        if a.time_to_threshold is not None:
            idx = min(int(a.time_to_threshold // 180), 4)
            buckets_correct[idx] += 1
            if a.threshold_depth is not None:
                buckets_depth[idx].append(a.threshold_depth)

    for a in all_resolved:
        if a.time_to_threshold is not None:
            idx = min(int(a.time_to_threshold // 180), 4)
            buckets_total[idx] += 1

    print(f"    Distribution (with success rate and avg depth):")
    labels = ["0-3min", "3-6min", "6-9min", "9-12min", "12-15min"]
    for i, label in enumerate(labels):
        pct = buckets_correct[i] / len(times_correct) * 100 if times_correct else 0
        success_rate = buckets_correct[i] / buckets_total[i] * 100 if buckets_total[i] > 0 else 0
        avg_depth = sum(buckets_depth[i]) / len(buckets_depth[i]) if buckets_depth[i] else 0
        print(f"      {label:8s} {buckets_correct[i]:3d} ({pct:5.1f}%) | P(success): {success_rate:5.1f}% ({buckets_correct[i]}/{buckets_total[i]}) | Avg depth: {avg_depth:,.0f}")


def print_question_analysis(
    title: str,
    hit_first: list[MarketAnalysis],
    correct: list[MarketAnalysis],
    wrong: list[MarketAnalysis],
    prob_label: str,
    approach_label: str,
) -> None:
    """Print analysis for one question (Q1 or Q2)."""
    print(f"{'─' * 70}")
    print(title)
    print(f"{'─' * 70}")
    print(f"  Total:         {len(hit_first)}")
    print(f"  Correct:       {len(correct)}")
    print(f"  Wrong:         {len(wrong)}")

    resolved = len(correct) + len(wrong)
    if resolved > 0:
        prob = len(correct) / resolved * 100
        print(f"\n  {prob_label} = {prob:.1f}%")
        print(f"  (Based on {resolved} resolved markets)")

    print_price_delta("CORRECT", correct)

    all_resolved = correct + wrong
    print_time_analysis(correct, all_resolved, lambda a: a in correct, approach_label)

    print_price_delta("FAILED", wrong)
    print()


def main():
    parser = argparse.ArgumentParser(description="Analyze BTC 15m extreme probability behavior")
    parser.add_argument("-t", "--threshold", type=float, default=10,
                        help="Threshold %% (default: 10, meaning 90%% high / 10%% low)")
    args = parser.parse_args()

    threshold = args.threshold
    high_pct = 100 - threshold
    low_pct = threshold

    print("=" * 70)
    print("BTC 15M EXTREME PROBABILITY ANALYSIS")
    print(f"Threshold: {threshold}% (High: {high_pct}%, Low: {low_pct}%)")
    print("=" * 70)

    markets_data = query_all_markets()
    if not markets_data:
        print("\nNo data found!")
        return 1

    print(f"\nAnalyzing {len(markets_data)} markets...")
    analyses = [a for a in (analyze_market(snaps, threshold) for snaps in markets_data.values()) if a]

    # Categorize markets
    hit_high = [a for a in analyses if a.first_extreme == "high"]
    hit_high_up = [a for a in hit_high if a.final_outcome == "up"]
    hit_high_down = [a for a in hit_high if a.final_outcome == "down"]

    hit_low = [a for a in analyses if a.first_extreme == "low"]
    hit_low_down = [a for a in hit_low if a.final_outcome == "down"]
    hit_low_up = [a for a in hit_low if a.final_outcome == "up"]

    resolved = [a for a in analyses if a.final_outcome is not None]

    print(f"\n{'─' * 70}")
    print("RESULTS")
    print(f"{'─' * 70}")
    print(f"\nTotal markets analyzed: {len(analyses)}")
    print(f"Markets with resolved outcome: {len(resolved)}\n")

    # Q1: Hit high threshold first
    print_question_analysis(
        title=f"Q1: Markets that hit {high_pct:.0f}%+ UP before hitting {low_pct:.0f}%- UP",
        hit_first=hit_high,
        correct=hit_high_up,
        wrong=hit_high_down,
        prob_label=f"P(UP wins | hit {high_pct:.0f}% first)",
        approach_label=f"{high_pct-5:.0f}%→{high_pct:.0f}%",
    )

    # Q2: Hit low threshold first
    print_question_analysis(
        title=f"Q2: Markets that hit {low_pct:.0f}%- UP before hitting {high_pct:.0f}%+ UP",
        hit_first=hit_low,
        correct=hit_low_down,
        wrong=hit_low_up,
        prob_label=f"P(DOWN wins | hit {low_pct:.0f}% first)",
        approach_label=f"{low_pct+5:.0f}%→{low_pct:.0f}%",
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
