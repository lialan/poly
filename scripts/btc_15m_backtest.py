#!/usr/bin/env python3
"""BTC 15m backtest - Compare real data to Monte Carlo theory.

Fetches last 12 hours of BTC 15-minute market data from Bigtable,
analyzes outcomes, and compares to theoretical predictions.
"""

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add monte_carlo to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from google.cloud import bigtable

from monte_carlo.simulation import SimulationConfig, run_simulation


@dataclass
class Snapshot:
    timestamp: datetime
    market_id: str
    btc_price: float
    yes_mid: float


def fetch_snapshots(hours: int = 12) -> list[Snapshot]:
    """Fetch btc_15m_snapshot data from Bigtable."""
    client = bigtable.Client(project="poly-collector", admin=True)
    table = client.instance("poly-data").table("btc_15m_snapshot")
    cutoff_ts = (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()

    snapshots = []
    for row in table.read_rows(limit=50000):
        cells = row.cells.get("data", {})
        get = lambda k: cells[k][0].value.decode() if k in cells else ""

        ts_str = get(b"ts")
        if not ts_str:
            continue
        ts = float(ts_str)
        if ts < cutoff_ts:
            break

        market_id = get(b"market_id")
        price_str = get(b"spot_price")
        if not market_id or not price_str:
            continue

        # Parse orderbook for yes_mid
        yes_mid = 0.5
        ob_str = get(b"orderbook")
        if ob_str:
            try:
                ob = json.loads(ob_str)
                bids, asks = ob.get("yes_bids", []), ob.get("yes_asks", [])
                if bids and asks:
                    yes_mid = (bids[0][0] + asks[0][0]) / 2
            except json.JSONDecodeError:
                pass

        snapshots.append(Snapshot(
            timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
            market_id=market_id,
            btc_price=float(price_str),
            yes_mid=yes_mid,
        ))

    snapshots.reverse()
    return snapshots


def analyze_outcomes(snapshots: list[Snapshot]) -> list[dict]:
    """Analyze price movements for each market."""
    by_market = defaultdict(list)
    for s in snapshots:
        by_market[s.market_id].append(s)

    outcomes = []
    for market_id, snaps in by_market.items():
        if len(snaps) < 2:
            continue
        snaps = sorted(snaps, key=lambda s: s.timestamp)
        first, last = snaps[0], snaps[-1]
        change = last.btc_price - first.btc_price
        outcomes.append({
            'market_id': market_id,
            'time': first.timestamp,
            'price_change': change,
            'pct_change': change / first.btc_price * 100,
            'up': change > 0,
        })
    return outcomes


def get_slot_ts(market_id: str) -> int:
    """Extract timestamp from market_id (btc-updown-15m-{ts})."""
    try:
        return int(market_id.split("-")[-1])
    except:
        return 0


def find_1h_windows(outcomes: list[dict]) -> list[list[dict]]:
    """Find consecutive 4x15min windows."""
    outcomes = sorted(outcomes, key=lambda o: get_slot_ts(o['market_id']))
    windows = []
    i = 0
    while i + 4 <= len(outcomes):
        window = outcomes[i:i+4]
        slots = [get_slot_ts(o['market_id']) for o in window]
        if all(slots[j+1] - slots[j] == 900 for j in range(3)):
            windows.append(window)
            i += 4
        else:
            i += 1
    return windows


def compute_empirical_probs(windows: list[list[dict]]) -> tuple[dict, dict]:
    """Compute P(1h up | N-th 15min up)."""
    counts = {N: {'up': 0, '1h_up': 0} for N in range(1, 5)}
    for window in windows:
        total = sum(o['price_change'] for o in window)
        is_1h_up = total > 0
        for N in range(1, 5):
            if window[N-1]['up']:
                counts[N]['up'] += 1
                if is_1h_up:
                    counts[N]['1h_up'] += 1
    probs = {N: c['1h_up']/c['up'] if c['up'] else 0.5 for N, c in counts.items()}
    return probs, counts


def main():
    print("=" * 60)
    print("BTC 15M BACKTEST - Real Data vs Monte Carlo")
    print("=" * 60)

    # Fetch and analyze
    print("\nFetching from Bigtable...")
    snapshots = fetch_snapshots(hours=12)
    if not snapshots:
        print("No data found!")
        return

    outcomes = analyze_outcomes(snapshots)
    print(f"  {len(snapshots)} snapshots, {len(outcomes)} markets")

    # Recent outcomes
    print("\n" + "-" * 60)
    print("RECENT OUTCOMES (last 10)")
    print("-" * 60)
    for o in sorted(outcomes, key=lambda x: x['time'], reverse=True)[:10]:
        ts = get_slot_ts(o['market_id'])
        direction = "UP" if o['up'] else "DOWN"
        print(f"  {ts}  {o['pct_change']:+.3f}%  {direction}")

    # 1-hour windows
    windows = find_1h_windows(outcomes)
    print(f"\n  {len(windows)} complete 1-hour windows")

    if windows:
        probs, counts = compute_empirical_probs(windows)
        print("\n" + "-" * 60)
        print("EMPIRICAL P(1h up | N-th 15m up)")
        print("-" * 60)
        for N in range(1, 5):
            print(f"  N={N}: {probs[N]:.3f}  (n={counts[N]['up']})")

    # Monte Carlo comparison
    print("\n" + "=" * 60)
    print("MONTE CARLO (1M paths)")
    print("=" * 60)
    result = run_simulation(SimulationConfig(n_paths=1_000_000, seed=42))
    print(f"\nP(1h up) = {result.unconditional_prob:.4f}")
    print("\nP(1h up | N-th 15m up):")
    for N, p in sorted(result.probs.items()):
        print(f"  N={N}: {p:.4f}")
    print(f"\nMonotonic: {result.is_monotonic}")

    # Summary
    up = sum(1 for o in outcomes if o['up'])
    print("\n" + "=" * 60)
    print("SUMMARY (last 12h)")
    print("=" * 60)
    print(f"  Markets: {len(outcomes)}")
    print(f"  Up: {up} ({up/len(outcomes)*100:.1f}%)")
    print(f"  Down: {len(outcomes)-up} ({(len(outcomes)-up)/len(outcomes)*100:.1f}%)")
    print(f"  Avg change: {np.mean([o['pct_change'] for o in outcomes]):+.3f}%")
    print(f"  Std change: {np.std([o['pct_change'] for o in outcomes]):.3f}%")
    print("=" * 60)


if __name__ == "__main__":
    main()
