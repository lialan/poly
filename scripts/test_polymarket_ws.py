#!/usr/bin/env python3
"""Test script for Polymarket WebSocket API.

Usage:
    # Test with a known token ID
    python scripts/test_polymarket_ws.py --token-id <token_id>

    # Test with auto-detected token from a market
    python scripts/test_polymarket_ws.py --market btc-updown-15m-1767795300

    # Stream for specific duration
    python scripts/test_polymarket_ws.py --duration 30

    # Compare WebSocket vs HTTP latency
    python scripts/test_polymarket_ws.py --benchmark
"""

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from poly.polymarket_ws import (
    PolymarketWS,
    MultiMarketWS,
    MarketUpdate,
    stream_market,
    get_orderbook_updates,
)


async def get_token_id_from_market(market_slug: str = None) -> tuple[str, str, str] | None:
    """Get YES and NO token IDs from market slug or current BTC 15m market.

    Returns:
        Tuple of (yes_token_id, no_token_id, slug) or None.
    """
    from poly.markets import fetch_current_prediction, Asset, MarketHorizon

    # Always try to get fresh tokens from current market first
    pred = await fetch_current_prediction(Asset.BTC, MarketHorizon.M15)
    if pred:
        return pred.up_token_id, pred.down_token_id, pred.slug

    # Fall back to API query if prediction fails
    if market_slug:
        from poly.polymarket_api import PolymarketAPI
        from poly.polymarket_config import PolymarketConfig

        config = PolymarketConfig(wallet_address="0x56687bf447db6ffa42ffe2204a05edaa20f55839")
        async with PolymarketAPI(config) as api:
            market = await api.get_market_by_slug(market_slug)
            if market and market.get("tokens"):
                tokens = market["tokens"]
                if len(tokens) >= 2:
                    return tokens[0].get("token_id"), tokens[1].get("token_id"), market_slug

    return None


async def test_basic_connection(token_id: str):
    """Test basic WebSocket connection and subscription."""
    print("\n" + "=" * 60)
    print("Testing: Basic WebSocket Connection")
    print("=" * 60)
    print(f"Token ID: {token_id[:40]}...")

    start = time.perf_counter()

    async with PolymarketWS() as ws:
        connect_time = time.perf_counter() - start
        print(f"  Connection time: {connect_time*1000:.1f}ms")
        print(f"  Connected: {ws.is_connected}")

        # Subscribe
        sub_start = time.perf_counter()
        await ws.subscribe(token_id)
        sub_time = time.perf_counter() - sub_start
        print(f"  Subscription time: {sub_time*1000:.1f}ms")

        # Receive a few messages
        print("\n  Receiving messages...")
        message_times = []

        for i in range(5):
            msg_start = time.perf_counter()
            update = await ws.receive_one(timeout=5.0)
            msg_time = time.perf_counter() - msg_start

            if update:
                message_times.append(msg_time)
                print(f"    [{i+1}] {msg_time*1000:.1f}ms - {update}")
            else:
                print(f"    [{i+1}] Timeout")

        # Stats
        print(f"\n  Stats:")
        print(f"    Messages received: {ws.stats.messages_received}")
        print(f"    Bytes received: {ws.stats.total_bytes_received}")
        if message_times:
            print(f"    Avg message time: {statistics.mean(message_times)*1000:.1f}ms")

    print("\n  Disconnected")


async def test_streaming(token_id: str, duration: float = 10.0):
    """Test streaming updates for a duration."""
    print("\n" + "=" * 60)
    print(f"Testing: Stream Updates for {duration}s")
    print("=" * 60)
    print(f"Token ID: {token_id[:40]}...")

    updates_received = 0
    start_time = time.time()

    def on_update(update: MarketUpdate):
        nonlocal updates_received
        updates_received += 1
        elapsed = time.time() - start_time
        print(f"  [{elapsed:.1f}s] #{updates_received}: {update}")

    await stream_market(token_id, on_update, duration=duration)

    print(f"\n  Total updates: {updates_received}")
    if updates_received > 0:
        print(f"  Rate: {updates_received/duration:.1f} updates/sec")


async def test_multi_market(yes_token: str, no_token: str, slug: str):
    """Test MultiMarketWS for tracking a market."""
    print("\n" + "=" * 60)
    print("Testing: MultiMarketWS")
    print("=" * 60)
    print(f"Market: {slug}")

    async with MultiMarketWS() as ws:
        await ws.add_market(slug, yes_token, no_token)

        print("  Receiving updates...")
        count = 0
        async for market_slug, side, update in ws.updates():
            count += 1
            print(f"    [{count}] {market_slug} ({side}): {update}")

            if count >= 10:
                break

        print(f"\n  Stats:")
        print(f"    Messages: {ws.stats.messages_received}")
        print(f"    Uptime: {ws.stats.uptime_seconds:.1f}s")


async def test_batch_updates(token_id: str, count: int = 10):
    """Test collecting a batch of updates."""
    print("\n" + "=" * 60)
    print(f"Testing: Collect {count} Updates")
    print("=" * 60)

    start = time.perf_counter()
    updates = await get_orderbook_updates(token_id, count=count, timeout=30.0)
    elapsed = time.perf_counter() - start

    print(f"  Collected {len(updates)} updates in {elapsed:.1f}s")
    for i, update in enumerate(updates[:5]):
        print(f"    [{i+1}] {update}")

    if len(updates) > 5:
        print(f"    ... and {len(updates) - 5} more")


async def benchmark_ws_vs_http(token_id: str, iterations: int = 20):
    """Benchmark WebSocket vs HTTP for fetching data."""
    print("\n" + "=" * 60)
    print("Benchmark: WebSocket vs HTTP")
    print("=" * 60)
    print(f"Iterations: {iterations}")

    import aiohttp

    # HTTP benchmark
    print("\n  HTTP (aiohttp):")
    http_times = []
    async with aiohttp.ClientSession() as session:
        # Warmup
        async with session.get(f"https://clob.polymarket.com/book?token_id={token_id}"):
            pass

        for _ in range(iterations):
            start = time.perf_counter()
            async with session.get(f"https://clob.polymarket.com/book?token_id={token_id}"):
                pass
            http_times.append(time.perf_counter() - start)

    print(f"    Avg: {statistics.mean(http_times)*1000:.1f}ms")
    print(f"    Min: {min(http_times)*1000:.1f}ms")
    print(f"    Max: {max(http_times)*1000:.1f}ms")

    # WebSocket benchmark
    print("\n  WebSocket:")
    ws_times = []
    connection_time = 0

    async with PolymarketWS(auto_reconnect=False) as ws:
        connection_time = ws.stats.uptime_seconds

        await ws.subscribe(token_id)

        count = 0
        async for update in ws.updates():
            start = ws.stats.last_message_at or time.time()
            ws_times.append(time.time() - start)
            count += 1

            if count >= iterations:
                break

    if ws_times:
        print(f"    Connection overhead: {connection_time*1000:.1f}ms")
        print(f"    Avg message time: {statistics.mean(ws_times)*1000:.1f}ms")
        print(f"    Min: {min(ws_times)*1000:.1f}ms")
        print(f"    Max: {max(ws_times)*1000:.1f}ms")
    else:
        print("    No messages received")

    # Summary
    print("\n  Summary:")
    http_total = sum(http_times)
    print(f"    HTTP total for {iterations} requests: {http_total*1000:.1f}ms")
    print(f"    HTTP avg per request: {statistics.mean(http_times)*1000:.1f}ms")

    if ws_times:
        # For WS, the "total time" is more about message intervals
        print(f"    WS connection + {len(ws_times)} messages")
        print(f"    Break-even point: ~{connection_time / statistics.mean(http_times):.0f} requests")


async def test_reconnect():
    """Test auto-reconnect behavior."""
    print("\n" + "=" * 60)
    print("Testing: Auto-reconnect (disconnect after 5 messages)")
    print("=" * 60)

    # This simulates what happens when connection drops
    ws = PolymarketWS(auto_reconnect=True, max_reconnect_attempts=3)

    print("  Note: This test requires manual connection interruption")
    print("  Skipping for automated testing")


async def main():
    parser = argparse.ArgumentParser(description="Test Polymarket WebSocket API")
    parser.add_argument(
        "--token-id",
        type=str,
        help="Token ID to subscribe to",
    )
    parser.add_argument(
        "--market",
        type=str,
        default="bitcoin-up-or-down-january-7-3pm-et",
        help="Market slug to get token ID from",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Duration for streaming test (seconds)",
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Run WS vs HTTP benchmark",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all tests",
    )

    args = parser.parse_args()

    # Get token ID
    if args.token_id:
        yes_token = args.token_id
        no_token = None
        slug = "unknown"
    else:
        print("Fetching token IDs from current BTC 15m market...")
        result = await get_token_id_from_market(args.market)
        if result:
            yes_token, no_token, slug = result
            print(f"  Market: {slug}")
            print(f"  YES token: {yes_token[:40]}...")
            print(f"  NO token: {no_token[:40]}..." if no_token else "")
        else:
            print("Could not fetch token IDs")
            return

    # Run tests
    if args.all:
        await test_basic_connection(yes_token)
        await test_batch_updates(yes_token, count=5)
        await test_streaming(yes_token, duration=min(args.duration, 5.0))
        if no_token:
            await test_multi_market(yes_token, no_token, slug)
        await benchmark_ws_vs_http(yes_token, iterations=10)
    elif args.benchmark:
        await benchmark_ws_vs_http(yes_token, iterations=20)
    else:
        await test_basic_connection(yes_token)
        await test_streaming(yes_token, duration=args.duration)


if __name__ == "__main__":
    asyncio.run(main())
