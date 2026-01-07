#!/usr/bin/env python3
"""Analyze BTC 15m data from Bigtable and compare to Monte Carlo theory.

Fetches last 12 hours of btc_15m_snapshot data and computes:
1. Actual price movements in each 15-min window
2. Empirical conditional probabilities P(1h up | N-th 15min up)
3. Comparison to theoretical Monte Carlo predictions

Usage:
    python scripts/analyze_btc_15m.py
"""

import sys
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dataclasses import dataclass
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from google.cloud import bigtable
import numpy as np

from monte_carlo.simulation import SimulationConfig, run_simulation


@dataclass
class Snapshot:
    """A single market snapshot."""
    timestamp: datetime
    market_id: str
    btc_price: float
    yes_mid: float  # Probability of "up"


def fetch_snapshots(
    hours: int = 12,
    project_id: str = "poly-collector",
    instance_id: str = "poly-data",
) -> list[Snapshot]:
    """Fetch btc_15m_snapshot data from Bigtable."""
    client = bigtable.Client(project=project_id, admin=True)
    instance = client.instance(instance_id)
    table = instance.table("btc_15m_snapshot")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    cutoff_ts = cutoff.timestamp()

    snapshots = []

    # Read all rows (newest first due to inverted timestamp)
    for row in table.read_rows(limit=50000):
        cells = row.cells.get("data", {})

        def get_val(key: bytes) -> str:
            if key in cells:
                return cells[key][0].value.decode()
            return ""

        ts_str = get_val(b"ts")
        if not ts_str:
            continue

        ts = float(ts_str)
        if ts < cutoff_ts:
            break  # Stop when we reach data older than cutoff

        dt = datetime.fromtimestamp(ts, tz=timezone.utc)

        market_id = get_val(b"market_id")
        btc_price_str = get_val(b"spot_price")
        orderbook_str = get_val(b"orderbook")

        if not all([market_id, btc_price_str]):
            continue

        btc_price = float(btc_price_str)

        # Parse orderbook JSON to get yes_mid
        yes_mid = 0.5  # default
        if orderbook_str:
            try:
                ob = json.loads(orderbook_str)
                yes_bids = ob.get("yes_bids", [])
                yes_asks = ob.get("yes_asks", [])
                if yes_bids and yes_asks:
                    best_bid = yes_bids[0][0] if yes_bids else 0
                    best_ask = yes_asks[0][0] if yes_asks else 1
                    yes_mid = (best_bid + best_ask) / 2
            except json.JSONDecodeError:
                pass

        snapshots.append(Snapshot(
            timestamp=dt,
            market_id=market_id,
            btc_price=btc_price,
            yes_mid=yes_mid,
        ))

    # Reverse to get oldest first
    snapshots.reverse()
    return snapshots


def group_by_market(snapshots: list[Snapshot]) -> dict[str, list[Snapshot]]:
    """Group snapshots by market_id."""
    by_market = defaultdict(list)
    for s in snapshots:
        by_market[s.market_id].append(s)
    return dict(by_market)


def analyze_market_outcome(snapshots: list[Snapshot]) -> dict:
    """Analyze a single market's outcome based on price movement."""
    if len(snapshots) < 2:
        return None

    # Sort by timestamp
    snapshots = sorted(snapshots, key=lambda s: s.timestamp)

    first = snapshots[0]
    last = snapshots[-1]

    price_start = first.btc_price
    price_end = last.btc_price
    price_change = price_end - price_start
    pct_change = (price_change / price_start) * 100 if price_start else 0

    # Market probability at start and end
    prob_start = first.yes_mid
    prob_end = last.yes_mid

    return {
        'market_id': first.market_id,
        'time_start': first.timestamp,
        'time_end': last.timestamp,
        'price_start': price_start,
        'price_end': price_end,
        'price_change': price_change,
        'pct_change': pct_change,
        'outcome_up': price_change > 0,
        'prob_start': prob_start,
        'prob_end': prob_end,
        'n_snapshots': len(snapshots),
    }


def extract_15m_slot(market_id: str) -> int:
    """Extract timestamp from market_id slug.

    Format: btc-updown-15m-{timestamp}
    """
    try:
        parts = market_id.split("-")
        return int(parts[-1])
    except:
        return 0


def group_into_1h_windows(outcomes: list[dict]) -> list[list[dict]]:
    """Group 15-min outcomes into 1-hour windows (4 consecutive)."""
    if not outcomes:
        return []

    # Sort by slot timestamp
    outcomes = sorted(outcomes, key=lambda o: extract_15m_slot(o['market_id']))

    # Each 15-min slot is 900 seconds apart
    windows = []
    i = 0
    while i + 4 <= len(outcomes):
        window = outcomes[i:i+4]

        # Check if they're consecutive (each 900 seconds apart)
        slots = [extract_15m_slot(o['market_id']) for o in window]
        is_consecutive = all(
            slots[j+1] - slots[j] == 900
            for j in range(3)
        )

        if is_consecutive:
            windows.append(window)
            i += 4  # Move to next window
        else:
            i += 1  # Try starting from next slot

    return windows


def compute_empirical_probs(windows: list[list[dict]]) -> dict:
    """Compute empirical P(1h up | N-th 15min up) from real data."""
    # For each N (1-4), count:
    # - How many times N-th segment was up
    # - Of those, how many times 1h was up

    counts = {N: {'n_up': 0, 'n_1h_up_given_n_up': 0} for N in range(1, 5)}

    for window in windows:
        # Determine if 1h was up (sum of price changes)
        total_change = sum(o['price_change'] for o in window)
        is_1h_up = total_change > 0

        for N in range(1, 5):
            outcome = window[N - 1]  # 0-indexed
            if outcome['outcome_up']:
                counts[N]['n_up'] += 1
                if is_1h_up:
                    counts[N]['n_1h_up_given_n_up'] += 1

    probs = {}
    for N in range(1, 5):
        n_up = counts[N]['n_up']
        n_1h_up = counts[N]['n_1h_up_given_n_up']
        probs[N] = n_1h_up / n_up if n_up > 0 else 0.5

    return probs, counts


def main():
    print("=" * 70)
    print("BTC 15M ANALYSIS - Last 12 Hours vs Monte Carlo Theory")
    print("=" * 70)

    # Fetch data
    print("\nFetching data from Bigtable...")
    snapshots = fetch_snapshots(hours=12)
    print(f"  Fetched {len(snapshots)} snapshots")

    if not snapshots:
        print("  No data found!")
        return

    # Group by market
    by_market = group_by_market(snapshots)
    print(f"  Found {len(by_market)} unique markets")

    # Analyze each market
    print("\nAnalyzing market outcomes...")
    outcomes = []
    for market_id, market_snapshots in by_market.items():
        result = analyze_market_outcome(market_snapshots)
        if result:
            outcomes.append(result)

    print(f"  Analyzed {len(outcomes)} markets")

    # Show recent outcomes
    print("\n" + "-" * 70)
    print("RECENT 15-MIN MARKET OUTCOMES (last 10)")
    print("-" * 70)
    print(f"{'Market ID':<35} {'Price Change':>12} {'Outcome':>8} {'Prob Start':>10}")
    print("-" * 70)

    for o in sorted(outcomes, key=lambda x: x['time_start'], reverse=True)[:10]:
        market_short = o['market_id'][-20:]
        direction = "UP" if o['outcome_up'] else "DOWN"
        print(f"...{market_short:<32} {o['pct_change']:>+10.3f}%  {direction:>8}  {o['prob_start']:>10.1%}")

    # Group into 1h windows
    windows = group_into_1h_windows(outcomes)
    print(f"\n  Found {len(windows)} complete 1-hour windows")

    if len(windows) < 3:
        print("\n  Not enough data for statistical analysis (need at least 3 windows)")
        print("  Running Monte Carlo simulation for comparison...\n")
    else:
        # Compute empirical probabilities
        print("\n" + "-" * 70)
        print("EMPIRICAL CONDITIONAL PROBABILITIES")
        print("-" * 70)

        emp_probs, counts = compute_empirical_probs(windows)

        print(f"{'N':>3}  {'P(1h up | N-th 15m up)':>25}  {'Sample Size':>12}")
        print("-" * 50)
        for N in range(1, 5):
            p = emp_probs[N]
            n = counts[N]['n_up']
            print(f"{N:>3}  {p:>25.4f}  {n:>12}")

    # Run Monte Carlo for comparison
    print("\n" + "=" * 70)
    print("MONTE CARLO SIMULATION (1M paths, theoretical)")
    print("=" * 70)

    config = SimulationConfig(n_paths=1_000_000, seed=42)
    result = run_simulation(config)

    print(f"\nTheoretical P(1h up) = {result.unconditional_prob:.4f}")
    print(f"\nConditional probabilities P(1h up | N-th 15min up):")
    print("-" * 50)
    print(f"{'N':>3}  {'Theoretical':>15}  {'Remaining Segs':>15}")
    print("-" * 50)
    for N in sorted(result.probs.keys()):
        p = result.probs[N]
        ua = result.uncertainty_analysis[N]
        remaining = ua['remaining_segments']
        print(f"{N:>3}  {p:>15.5f}  {remaining:>15}")

    print(f"\nMonotonicity: {result.is_monotonic}")
    print(f"Differences: {[f'{d:+.5f}' for d in result.differences]}")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    up_count = sum(1 for o in outcomes if o['outcome_up'])
    down_count = len(outcomes) - up_count

    print(f"\nLast 12 hours statistics:")
    print(f"  Total 15-min markets: {len(outcomes)}")
    print(f"  Up outcomes: {up_count} ({up_count/len(outcomes)*100:.1f}%)")
    print(f"  Down outcomes: {down_count} ({down_count/len(outcomes)*100:.1f}%)")

    if outcomes:
        avg_change = np.mean([o['pct_change'] for o in outcomes])
        std_change = np.std([o['pct_change'] for o in outcomes])
        print(f"  Avg price change: {avg_change:+.3f}%")
        print(f"  Std price change: {std_change:.3f}%")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
