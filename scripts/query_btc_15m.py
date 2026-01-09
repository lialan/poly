#!/usr/bin/env python3
"""
Query current BTC 15-minute prediction market status.

Shows market info, probabilities, orderbook, and time remaining.
"""

import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, "src")

from poly import (
    Asset,
    MarketHorizon,
    fetch_current_prediction,
    PolymarketAPI,
    PolymarketConfig,
)


async def get_orderbook_info(token_id: str) -> dict:
    """Fetch orderbook info for a token."""
    import requests

    url = f"https://clob.polymarket.com/book?token_id={token_id}"
    resp = requests.get(url)
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}"}

    orderbook = resp.json()
    bids = orderbook.get("bids", [])
    asks = orderbook.get("asks", [])

    best_bid = max(float(b["price"]) for b in bids) if bids else 0
    best_ask = min(float(a["price"]) for a in asks) if asks else 1

    # Calculate depth at various levels
    bid_volume = sum(float(b["size"]) for b in bids)
    ask_volume = sum(float(a["size"]) for a in asks)

    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": best_ask - best_bid,
        "mid": (best_bid + best_ask) / 2,
        "bid_depth": len(bids),
        "ask_depth": len(asks),
        "bid_volume": bid_volume,
        "ask_volume": ask_volume,
    }


async def query_market() -> int:
    """Query and display current BTC 15m market status."""
    print("=" * 60)
    print("BTC 15M MARKET STATUS")
    print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    # Fetch current market
    print("\n[1] Fetching current market...")
    try:
        prediction = await fetch_current_prediction(Asset.BTC, MarketHorizon.M15)
    except Exception as e:
        print(f"    [ERROR] Failed to fetch market: {e}")
        return 1

    print(f"\n{'─' * 60}")
    print("MARKET INFO")
    print(f"{'─' * 60}")
    print(f"  Slug:        {prediction.slug}")
    print(f"  URL:         https://polymarket.com/event/{prediction.slug}")

    # Time remaining
    if prediction.time_remaining is not None:
        remaining = prediction.time_remaining
        mins, secs = divmod(int(remaining), 60)
        print(f"  Remaining:   {mins}m {secs}s")
        if remaining < 60:
            print(f"               ⚠ CLOSING SOON!")
    else:
        print(f"  Remaining:   Unknown")

    # Fetch orderbooks for both sides first
    print(f"\n{'─' * 60}")
    print("ORDERBOOK - UP TOKEN")
    print(f"{'─' * 60}")

    up_book = await get_orderbook_info(prediction.up_token_id)
    if "error" in up_book:
        print(f"  [ERROR] {up_book['error']}")
    else:
        print(f"  Best Bid:    {up_book['best_bid']:.4f}")
        print(f"  Best Ask:    {up_book['best_ask']:.4f}")
        print(f"  Spread:      {up_book['spread']:.4f} ({up_book['spread']*100:.2f}%)")
        print(f"  Depth:       {up_book['bid_depth']} bids, {up_book['ask_depth']} asks")
        print(f"  Volume:      {up_book['bid_volume']:.0f} bid, {up_book['ask_volume']:.0f} ask")

    print(f"\n{'─' * 60}")
    print("ORDERBOOK - DOWN TOKEN")
    print(f"{'─' * 60}")

    down_book = await get_orderbook_info(prediction.down_token_id)
    if "error" in down_book:
        print(f"  [ERROR] {down_book['error']}")
    else:
        print(f"  Best Bid:    {down_book['best_bid']:.4f}")
        print(f"  Best Ask:    {down_book['best_ask']:.4f}")
        print(f"  Spread:      {down_book['spread']:.4f} ({down_book['spread']*100:.2f}%)")
        print(f"  Depth:       {down_book['bid_depth']} bids, {down_book['ask_depth']} asks")
        print(f"  Volume:      {down_book['bid_volume']:.0f} bid, {down_book['ask_volume']:.0f} ask")

    # Calculate probabilities from orderbook mid prices (more accurate than Gamma API)
    print(f"\n{'─' * 60}")
    print("PROBABILITIES (from orderbook)")
    print(f"{'─' * 60}")
    if "error" not in up_book:
        up_prob = up_book['mid'] * 100
        down_prob = 100 - up_prob
        print(f"  UP:   {up_prob:5.1f}%  {'█' * int(up_prob / 5)}")
        print(f"  DOWN: {down_prob:5.1f}%  {'█' * int(down_prob / 5)}")
    else:
        print(f"  [ERROR] Could not calculate probabilities")

    # Token IDs
    print(f"\n{'─' * 60}")
    print("TOKEN IDs")
    print(f"{'─' * 60}")
    print(f"  UP:   {prediction.up_token_id[:40]}...")
    print(f"  DOWN: {prediction.down_token_id[:40]}...")

    print()
    return 0


def main():
    return asyncio.run(query_market())


if __name__ == "__main__":
    sys.exit(main())
