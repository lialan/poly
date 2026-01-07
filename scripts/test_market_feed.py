#!/usr/bin/env python3
"""Test script for MarketFeed daemon service.

Usage:
    python scripts/test_market_feed.py
    python scripts/test_market_feed.py --duration 30
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from poly.market_feed import MarketFeed, PriceUpdate, Side
from poly.markets import fetch_current_prediction, Asset, MarketHorizon


def print_update(update: PriceUpdate):
    """Callback to print updates."""
    side_char = "UP" if update.side == Side.YES else "DN"
    bid = f"{update.best_bid:.4f}" if update.best_bid else "----"
    ask = f"{update.best_ask:.4f}" if update.best_ask else "----"
    mid = f"{update.mid:.4f}" if update.mid else "----"

    # Extract market name from slug
    market = update.market_slug.split("-")[0].upper()

    print(f"[{market}] {side_char}: {bid}/{ask} (mid: {mid})")


async def main():
    parser = argparse.ArgumentParser(description="Test MarketFeed")
    parser.add_argument("--duration", type=int, default=10, help="Run duration in seconds")
    args = parser.parse_args()

    print("Fetching current markets...")

    # Get current BTC and ETH 15m markets
    btc_pred = await fetch_current_prediction(Asset.BTC, MarketHorizon.M15)
    eth_pred = await fetch_current_prediction(Asset.ETH, MarketHorizon.M15)

    if not btc_pred:
        print("Could not fetch BTC market")
        return

    print(f"  BTC: {btc_pred.slug}")
    if eth_pred:
        print(f"  ETH: {eth_pred.slug}")

    # Create feed with callback
    feed = MarketFeed(
        on_update=print_update,
        on_connect=lambda: print("\n[CONNECTED]"),
        on_disconnect=lambda: print("\n[DISCONNECTED]"),
    )

    # Add markets
    await feed.add_market(
        btc_pred.slug,
        btc_pred.up_token_id,
        btc_pred.down_token_id,
    )

    if eth_pred:
        await feed.add_market(
            eth_pred.slug,
            eth_pred.up_token_id,
            eth_pred.down_token_id,
        )

    print(f"\nMonitoring {feed.market_count} market(s) for {args.duration}s...")
    print("-" * 50)

    # Run feed in background
    feed_task = asyncio.create_task(feed.start())

    # Wait for duration
    await asyncio.sleep(args.duration)

    # Stop feed
    await feed.stop()
    await feed_task

    # Print stats
    print("-" * 50)
    print(f"\nStats:")
    print(f"  Messages received: {feed.stats.messages_received}")
    print(f"  Updates processed: {feed.stats.updates_processed}")
    print(f"  Bytes received: {feed.stats.bytes_received:,}")
    print(f"  Msg/sec: {feed.stats.msg_per_sec:.1f}")
    print(f"  Reconnects: {feed.stats.reconnect_count}")

    # Print final market states
    print(f"\nFinal market states:")
    for slug, market in feed.get_all_markets().items():
        print(f"  {slug}:")
        print(f"    YES: {market.yes_bid}/{market.yes_ask} (mid: {market.yes_mid})")
        print(f"    NO:  {market.no_bid}/{market.no_ask} (mid: {market.no_mid})")
        print(f"    Implied prob: {market.implied_prob:.1%}" if market.implied_prob else "")
        print(f"    Updates: {market.update_count}")


if __name__ == "__main__":
    asyncio.run(main())
