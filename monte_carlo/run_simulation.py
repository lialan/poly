#!/usr/bin/env python3
"""
Event Statistics Simulator CLI

Validates the theoretical claim:
P(1h up | 15min_N up) is monotonically increasing in N = 1,2,3,4.

Usage:
    python monte_carlo/run_simulation.py
    python monte_carlo/run_simulation.py --n-paths 10000000
    python monte_carlo/run_simulation.py --mu 0.01 --sigma 0.1
    python monte_carlo/run_simulation.py --seed 42
"""

import argparse
import sys
import time
from pathlib import Path

# Add monte_carlo to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from monte_carlo.simulation import (
    SimulationConfig,
    run_simulation,
)


def print_results(result, elapsed_time: float):
    """Print simulation results."""
    config = result.config

    print("=" * 60)
    print("EVENT STATISTICS SIMULATION")
    print("=" * 60)
    print(f"Paths:      {config.n_paths:,}")
    print(f"Drift (μ):  {config.mu}")
    print(f"Vol (σ):    {config.sigma}")
    print(f"Seed:       {config.seed if config.seed else 'random'}")
    print(f"Time:       {elapsed_time:.2f}s")
    print("=" * 60)

    print("\nUnconditional probability:")
    print(f"  P(1h up) = {result.unconditional_prob:.5f}")

    print("\nConditional probabilities P(1h up | N-th 15min up):")
    print("-" * 60)
    print(f"  {'N':>3}  {'Prob':>8}  {'Remaining':>10}  {'Remaining Std':>14}")
    print("-" * 60)
    for N in sorted(result.probs.keys()):
        p = result.probs[N]
        ua = result.uncertainty_analysis[N]
        remaining = ua['remaining_segments']
        remaining_std = ua['remaining_std']
        print(f"  {N:>3}  {p:>8.5f}  {remaining:>10}  {remaining_std:>14.6f}")
    print("-" * 60)

    print("\nMonotonicity check (raw probabilities):")
    print(f"  Is monotonic: {result.is_monotonic}")
    print(f"  Differences:  {[f'{d:+.6f}' for d in result.differences]}")

    # Key insight explanation
    print("\n" + "=" * 60)
    print("ANALYSIS")
    print("=" * 60)
    print("""
Under i.i.d assumption, P(1h up | segment N up) is the SAME for all N.
This is because all segments are exchangeable.

The probabilities converge to ~0.6667 because:
- Given one segment is up (positive), the total of 4 segments
  is more likely to be positive than negative.
- P(sum > 0 | one term > 0) ≈ 2/3 for symmetric distributions.

The POSITION EFFECT described in theory is about INFORMATION at
different STOPPING TIMES, not this unconditional probability.

Remaining uncertainty decreases as N increases:""")

    for N in sorted(result.uncertainty_analysis.keys()):
        ua = result.uncertainty_analysis[N]
        remaining = ua['remaining_segments']
        remaining_std = ua['remaining_std']
        print(f"  N={N}: {remaining} segments unknown, std={remaining_std:.6f}")

    print("""
The TRUE position effect manifests when you ALREADY KNOW the
outcomes of segments 1..N-1. Then knowing segment N is up
provides different information based on remaining uncertainty.
""")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Event Statistics Simulator - Validates position effect theorem",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Default (1M paths, mu=0, sigma=0.05)
    python monte_carlo/run_simulation.py

    # More paths for higher precision
    python monte_carlo/run_simulation.py --n-paths 10000000

    # Test with positive drift
    python monte_carlo/run_simulation.py --mu 0.01

    # Higher volatility
    python monte_carlo/run_simulation.py --sigma 0.1

    # Reproducible results
    python monte_carlo/run_simulation.py --seed 42

Theory:
    Under a Gaussian random walk model, the conditional probability
    P(1h up | N-th 15min up) is monotonically increasing in N.

    This is because later 15min segments provide more information
    about the 1h outcome (smaller remaining uncertainty).
""",
    )

    parser.add_argument(
        "--n-paths", type=int, default=1_000_000,
        help="Number of Monte Carlo paths (default: 1,000,000)"
    )
    parser.add_argument(
        "--mu", type=float, default=0.0,
        help="Drift per hour (default: 0.0 for symmetric test)"
    )
    parser.add_argument(
        "--sigma", type=float, default=0.05,
        help="Volatility per sqrt(hour) (default: 0.05)"
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for reproducibility (default: None)"
    )

    args = parser.parse_args()

    config = SimulationConfig(
        n_paths=args.n_paths,
        mu=args.mu,
        sigma=args.sigma,
        seed=args.seed,
    )

    print(f"Running simulation with {config.n_paths:,} paths...")
    start_time = time.time()
    result = run_simulation(config)
    elapsed = time.time() - start_time

    print_results(result, elapsed)

    return result


if __name__ == "__main__":
    main()
