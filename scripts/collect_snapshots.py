#!/usr/bin/env python3
"""Continuous market snapshot collector.

Queries Polymarket BTC 15m prediction markets and stores to SQLite.

Usage:
    python scripts/collect_snapshots.py [--interval SECONDS] [--db PATH]

Examples:
    python scripts/collect_snapshots.py
    python scripts/collect_snapshots.py --interval 10
    python scripts/collect_snapshots.py --db /path/to/data.db
"""

import argparse
import asyncio
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from poly.market_snapshot import fetch_current_snapshot, MarketSnapshot
from poly.storage.db_writer import get_db_writer
from poly.api.binance import get_btc_price

# Global flag for graceful shutdown
running = True


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    global running
    print("\n\nShutting down...")
    running = False


def print_snapshot(snapshot: MarketSnapshot, btc_price: float, query_time: float) -> None:
    """Print snapshot in a compact format."""
    now = datetime.now(timezone.utc)

    # Time remaining until resolution
    resolution_delta = (snapshot.resolution_time - now).total_seconds()
    if resolution_delta > 0:
        mins, secs = divmod(int(resolution_delta), 60)
        time_left = f"{mins}m {secs}s"
    else:
        time_left = "RESOLVED"

    print(f"[{now.strftime('%H:%M:%S')}] {snapshot.market_id}")
    print(f"  BTC: ${btc_price:,.2f}")

    # Calculate real bid/ask from deepest levels (where orders actually meet)
    real_yes_bid = snapshot.depth_yes_bids[-1].price if snapshot.depth_yes_bids else None
    real_yes_ask = snapshot.depth_yes_asks[-1].price if snapshot.depth_yes_asks else None
    if real_yes_bid and real_yes_ask:
        real_mid = (float(real_yes_bid) + float(real_yes_ask)) / 2
        real_spread = float(real_yes_ask) - float(real_yes_bid)
        print(f"  Market: {float(real_yes_bid):.2f} / {float(real_yes_ask):.2f} (mid={real_mid*100:.1f}%, spread={real_spread:.2f})")
    else:
        print(f"  Market: N/A")

    # Print orderbook depth (top 3 levels each side, with total count)
    yes_bids_count = len(snapshot.depth_yes_bids)
    yes_asks_count = len(snapshot.depth_yes_asks)
    no_bids_count = len(snapshot.depth_no_bids)
    no_asks_count = len(snapshot.depth_no_asks)

    if snapshot.depth_yes_bids:
        yes_bids_str = " ".join([f"{float(l.price):.2f}:{float(l.size):.0f}" for l in snapshot.depth_yes_bids[-3:]])
        print(f"  YES Bids ({yes_bids_count}): [...{yes_bids_str}]")
    else:
        print(f"  YES Bids (0): []")
    if snapshot.depth_yes_asks:
        yes_asks_str = " ".join([f"{float(l.price):.2f}:{float(l.size):.0f}" for l in snapshot.depth_yes_asks[-3:]])
        print(f"  YES Asks ({yes_asks_count}): [...{yes_asks_str}]")
    else:
        print(f"  YES Asks (0): []")
    if snapshot.depth_no_bids:
        no_bids_str = " ".join([f"{float(l.price):.2f}:{float(l.size):.0f}" for l in snapshot.depth_no_bids[-3:]])
        print(f"  NO Bids  ({no_bids_count}): [...{no_bids_str}]")
    else:
        print(f"  NO Bids  (0): []")
    if snapshot.depth_no_asks:
        no_asks_str = " ".join([f"{float(l.price):.2f}:{float(l.size):.0f}" for l in snapshot.depth_no_asks[-3:]])
        print(f"  NO Asks  ({no_asks_count}): [...{no_asks_str}]")
    else:
        print(f"  NO Asks  (0): []")

    print(f"  Resolution in: {time_left} | Query: {query_time*1000:.0f}ms")
    print("-" * 70)


async def fetch_and_store(writer) -> tuple[bool, float]:
    """Fetch snapshot and store to database.

    Returns:
        Tuple of (success, query_time_seconds)
    """
    start_time = time.time()

    try:
        # Fetch snapshot and BTC price concurrently
        snapshot, btc_price = await asyncio.gather(
            fetch_current_snapshot(),
            get_btc_price(),
        )
        query_time = time.time() - start_time

        if snapshot is None:
            print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Failed to fetch snapshot")
            return False, query_time

        btc_price_float = float(btc_price) if btc_price else 0.0

        # Store to database (with BTC price in depth_json)
        writer.write_snapshot_from_obj(snapshot, horizon="15m", btc_price=btc_price_float)

        # Print snapshot
        print_snapshot(snapshot, btc_price_float, query_time)

        return True, query_time

    except Exception as e:
        query_time = time.time() - start_time
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Error: {e}")
        return False, query_time


async def main(
    interval: float,
    backend: str,
    db_path: str,
    project_id: str,
    instance_id: str,
):
    """Main collection loop."""
    global running

    # Setup signal handler
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("=" * 60)
    print("POLYMARKET SNAPSHOT COLLECTOR")
    print("=" * 60)
    print(f"Interval: {interval}s")
    print(f"Backend: {backend}")
    if backend == "sqlite":
        print(f"Database: {db_path}")
    else:
        print(f"Project: {project_id}")
        print(f"Instance: {instance_id}")
    print("Press Ctrl+C to stop")
    print("=" * 60)
    print()

    writer = get_db_writer(
        backend=backend,
        sqlite_path=db_path if backend == "sqlite" else None,
        project_id=project_id if backend == "bigtable" else None,
        instance_id=instance_id if backend == "bigtable" else None,
    )

    success_count = 0
    error_count = 0

    try:
        while running:
            success, query_time = await fetch_and_store(writer)

            if success:
                success_count += 1
            else:
                error_count += 1

            # Calculate sleep time (interval minus query time)
            sleep_time = max(0.1, interval - query_time)

            # Sleep in small increments to check running flag
            sleep_end = time.time() + sleep_time
            while running and time.time() < sleep_end:
                await asyncio.sleep(0.1)

    finally:
        writer.close()

        print()
        print("=" * 60)
        print("COLLECTION SUMMARY")
        print("=" * 60)
        print(f"Successful queries: {success_count}")
        print(f"Failed queries: {error_count}")
        print(f"Backend: {backend}")

        # Show final stats
        try:
            stats = writer.get_stats()
            print(f"Total snapshots in DB: {stats['market_snapshots']}")
        except Exception:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Collect Polymarket BTC 15m snapshots to database"
    )
    parser.add_argument(
        "--interval", "-i",
        type=float,
        default=5.0,
        help="Query interval in seconds (default: 5)"
    )
    parser.add_argument(
        "--backend", "-b",
        type=str,
        default="sqlite",
        choices=["sqlite", "bigtable"],
        help="Database backend (default: sqlite)"
    )
    parser.add_argument(
        "--db", "-d",
        type=str,
        default=str(Path(__file__).parent.parent / "poly_data.db"),
        help="SQLite database path (default: poly_data.db)"
    )
    parser.add_argument(
        "--project",
        type=str,
        default="",
        help="GCP project ID (for bigtable backend)"
    )
    parser.add_argument(
        "--instance",
        type=str,
        default="",
        help="Bigtable instance ID (for bigtable backend)"
    )

    args = parser.parse_args()

    asyncio.run(main(
        interval=args.interval,
        backend=args.backend,
        db_path=args.db,
        project_id=args.project,
        instance_id=args.instance,
    ))
