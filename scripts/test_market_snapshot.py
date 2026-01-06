#!/usr/bin/env python3
"""Test script for market snapshot functionality."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from poly.market_snapshot import (
    MarketSnapshot,
    fetch_market_snapshot,
    fetch_current_snapshot,
    print_snapshot,
)
from poly.btc_15m import (
    fetch_current_and_upcoming,
    get_current_slot_timestamp,
    print_predictions,
)


async def test_current_snapshot():
    """Test fetching snapshot for current 15m slot."""
    print("\n" + "=" * 70)
    print("TEST 1: Fetch current market snapshot")
    print("=" * 70)

    snapshot = await fetch_current_snapshot()

    if snapshot:
        print_snapshot(snapshot)
        return True
    else:
        print("Failed to fetch current snapshot")
        return False


async def test_snapshot_by_timestamp():
    """Test fetching snapshot by timestamp."""
    print("\n" + "=" * 70)
    print("TEST 2: Fetch snapshot by timestamp")
    print("=" * 70)

    timestamp = get_current_slot_timestamp()
    print(f"Current slot timestamp: {timestamp}")

    snapshot = await fetch_market_snapshot(str(timestamp))

    if snapshot:
        print(f"✓ Successfully fetched snapshot for timestamp {timestamp}")
        print(f"  Market ID: {snapshot.market_id}")
        print(f"  YES Mid: {snapshot.yes_mid}")
        print(f"  NO Mid: {snapshot.no_mid}")
        return True
    else:
        print(f"✗ Failed to fetch snapshot for timestamp {timestamp}")
        return False


async def test_snapshot_by_slug():
    """Test fetching snapshot by slug."""
    print("\n" + "=" * 70)
    print("TEST 3: Fetch snapshot by slug")
    print("=" * 70)

    timestamp = get_current_slot_timestamp()
    slug = f"btc-updown-15m-{timestamp}"
    print(f"Testing with slug: {slug}")

    snapshot = await fetch_market_snapshot(slug)

    if snapshot:
        print(f"✓ Successfully fetched snapshot by slug")
        print(f"  Resolution: {snapshot.resolution_time}")
        return True
    else:
        print(f"✗ Failed to fetch snapshot by slug")
        return False


async def test_orderbook_depth():
    """Test orderbook depth data."""
    print("\n" + "=" * 70)
    print("TEST 4: Orderbook depth analysis")
    print("=" * 70)

    snapshot = await fetch_current_snapshot()

    if not snapshot:
        print("✗ Failed to fetch snapshot")
        return False

    print(f"\nYES (UP) Token: {snapshot.yes_token_id[:20]}...")
    print(f"  Bid levels: {len(snapshot.depth_yes_bids)}, Ask levels: {len(snapshot.depth_yes_asks)}")
    if snapshot.depth_yes_bids:
        print("  Top 3 bids (buyers):")
        for i, level in enumerate(snapshot.depth_yes_bids[:3]):
            print(f"    {i+1}. Price: {float(level.price):.4f}, Size: {float(level.size):.2f}")
    if snapshot.depth_yes_asks:
        print("  Top 3 asks (sellers):")
        for i, level in enumerate(snapshot.depth_yes_asks[:3]):
            print(f"    {i+1}. Price: {float(level.price):.4f}, Size: {float(level.size):.2f}")

    print(f"\nNO (DOWN) Token: {snapshot.no_token_id[:20]}...")
    print(f"  Bid levels: {len(snapshot.depth_no_bids)}, Ask levels: {len(snapshot.depth_no_asks)}")
    if snapshot.depth_no_bids:
        print("  Top 3 bids (buyers):")
        for i, level in enumerate(snapshot.depth_no_bids[:3]):
            print(f"    {i+1}. Price: {float(level.price):.4f}, Size: {float(level.size):.2f}")
    if snapshot.depth_no_asks:
        print("  Top 3 asks (sellers):")
        for i, level in enumerate(snapshot.depth_no_asks[:3]):
            print(f"    {i+1}. Price: {float(level.price):.4f}, Size: {float(level.size):.2f}")

    # Show depth_yes and depth_no as list of tuples
    print(f"\n  depth_yes (tuples): {snapshot.depth_yes[:3]}...")
    print(f"  depth_no (tuples): {snapshot.depth_no[:3]}...")

    return True


async def test_with_prediction():
    """Test using pre-fetched prediction."""
    print("\n" + "=" * 70)
    print("TEST 5: Use with pre-fetched prediction")
    print("=" * 70)

    # First get predictions
    predictions = await fetch_current_and_upcoming(count=2)

    if not predictions:
        print("✗ No predictions available")
        return False

    print(f"Got {len(predictions)} predictions")

    for pred in predictions:
        print(f"\nFetching snapshot for: {pred.title}")
        snapshot = await fetch_market_snapshot(pred.slug, prediction=pred)

        if snapshot:
            yes_prob = float(snapshot.yes_mid or 0) * 100
            no_prob = float(snapshot.no_mid or 0) * 100
            print(f"  ✓ YES prob: {yes_prob:.1f}%, NO prob: {no_prob:.1f}%")
            if snapshot.yes_spread:
                print(f"  ✓ YES spread: {float(snapshot.yes_spread):.4f}")
        else:
            print("  ✗ Failed to fetch snapshot")

    return True


async def main():
    print("=" * 70)
    print("MARKET SNAPSHOT TEST SUITE")
    print("=" * 70)

    results = []

    results.append(("Current snapshot", await test_current_snapshot()))
    results.append(("By timestamp", await test_snapshot_by_timestamp()))
    results.append(("By slug", await test_snapshot_by_slug()))
    results.append(("Orderbook depth", await test_orderbook_depth()))
    results.append(("With prediction", await test_with_prediction()))

    # Summary
    print("\n" + "=" * 70)
    print("TEST RESULTS")
    print("=" * 70)

    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name}")

    all_passed = all(r[1] for r in results)
    print()
    if all_passed:
        print("All tests passed! ✓")
    else:
        print("Some tests failed.")


if __name__ == "__main__":
    asyncio.run(main())
