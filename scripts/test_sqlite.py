#!/usr/bin/env python3
"""Test script for SQLite writer."""

import asyncio
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from poly.storage.sqlite import SQLiteWriter
from poly.market_snapshot import fetch_current_snapshot

# Use a test database
TEST_DB = Path(__file__).parent.parent / "test_poly_data.db"


def test_basic_writes():
    """Test basic write operations."""
    print("\n" + "=" * 60)
    print("TEST 1: Basic write operations")
    print("=" * 60)

    # Clean up test db
    if TEST_DB.exists():
        TEST_DB.unlink()

    with SQLiteWriter(TEST_DB) as writer:
        # Write snapshot
        writer.write_snapshot(
            market_id="btc-updown-15m-1234567890",
            horizon="15m",
            yes_bid=0.45,
            yes_ask=0.55,
            no_bid=0.44,
            no_ask=0.56,
            depth_json='{"yes_bids": [[0.45, 100]], "yes_asks": [[0.55, 100]]}',
        )
        print("✓ Wrote market snapshot")

        # Write opportunity
        writer.write_opportunity(
            market_15m_id="btc-updown-15m-1234567890",
            market_1h_id="btc-updown-1h-1234567200",
            edge=0.05,
            est_success_prob=0.65,
            est_slippage=0.01,
            eligible=True,
        )
        print("✓ Wrote opportunity")

        # Write trade
        writer.write_trade(
            ts_open=time.time() - 100,
            ts_close=time.time(),
            size_usd=100.0,
            quoted_edge=0.05,
            delay_sec=2.5,
            realized_edge=0.04,
            success=True,
            pnl=4.0,
        )
        print("✓ Wrote simulated trade")

        # Write equity
        writer.write_equity(equity=1000.0)
        writer.write_equity(equity=1004.0)
        print("✓ Wrote equity curve points")

        # Get stats
        stats = writer.get_stats()
        print(f"\nDatabase stats: {stats}")

    return True


def test_queries():
    """Test query operations."""
    print("\n" + "=" * 60)
    print("TEST 2: Query operations")
    print("=" * 60)

    with SQLiteWriter(TEST_DB) as writer:
        # Query snapshots
        snapshots = writer.get_snapshots(limit=10)
        print(f"✓ Got {len(snapshots)} snapshots")
        if snapshots:
            print(f"  Latest: {snapshots[0]['market_id']}")

        # Query opportunities
        opps = writer.get_opportunities(eligible_only=True)
        print(f"✓ Got {len(opps)} eligible opportunities")

        # Query trades
        trades = writer.get_trades()
        print(f"✓ Got {len(trades)} trades")
        if trades:
            print(f"  Latest PnL: ${trades[0]['pnl']:.2f}")

        # Query equity curve
        equity = writer.get_equity_curve()
        print(f"✓ Got {len(equity)} equity points")
        if len(equity) >= 2:
            print(f"  Start: ${equity[0]['equity']:.2f} -> End: ${equity[-1]['equity']:.2f}")

    return True


async def test_with_real_snapshot():
    """Test writing a real market snapshot."""
    print("\n" + "=" * 60)
    print("TEST 3: Write real market snapshot")
    print("=" * 60)

    snapshot = await fetch_current_snapshot()
    if not snapshot:
        print("✗ Could not fetch current snapshot")
        return False

    with SQLiteWriter(TEST_DB) as writer:
        writer.write_snapshot_from_obj(snapshot, horizon="15m")
        print(f"✓ Wrote real snapshot: {snapshot.market_id}")

        # Verify it was written
        snapshots = writer.get_snapshots(market_id=snapshot.market_id)
        if snapshots:
            print(f"✓ Verified: found {len(snapshots)} snapshot(s) for {snapshot.market_id}")
            s = snapshots[0]
            print(f"  YES: bid={s['yes_bid']}, ask={s['yes_ask']}")
            print(f"  NO:  bid={s['no_bid']}, ask={s['no_ask']}")
        else:
            print("✗ Could not find written snapshot")
            return False

    return True


def test_default_path():
    """Test default database path."""
    print("\n" + "=" * 60)
    print("TEST 4: Default database path")
    print("=" * 60)

    writer = SQLiteWriter()
    print(f"Default DB path: {writer.db_path}")
    print(f"DB exists: {writer.db_path.exists()}")

    # Write something
    writer.write_equity(equity=9999.99)
    stats = writer.get_stats()
    print(f"Stats: {stats}")
    writer.close()

    return True


async def main():
    print("=" * 60)
    print("SQLITE WRITER TEST SUITE")
    print("=" * 60)

    results = []

    results.append(("Basic writes", test_basic_writes()))
    results.append(("Query operations", test_queries()))
    results.append(("Real snapshot", await test_with_real_snapshot()))
    results.append(("Default path", test_default_path()))

    # Summary
    print("\n" + "=" * 60)
    print("TEST RESULTS")
    print("=" * 60)

    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name}")

    # Cleanup test db
    if TEST_DB.exists():
        TEST_DB.unlink()
        print(f"\nCleaned up test database: {TEST_DB}")

    all_passed = all(r[1] for r in results)
    print()
    if all_passed:
        print("All tests passed! ✓")
    else:
        print("Some tests failed.")


if __name__ == "__main__":
    asyncio.run(main())
