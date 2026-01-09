#!/usr/bin/env python3
"""
Benchmark comparison between py-clob-client and polymarket-apis packages.

Tests the same operations 10 times with each package and compares latency.
Also tests WebSocket connections to see if persistent connections reduce latency.
"""

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# WebSocket endpoint
WS_ENDPOINT = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


# =============================================================================
# Test Configuration
# =============================================================================

NUM_RUNS = 10
TEST_MARKET_SLUG = "bitcoin-up-or-down-january-7-3pm-et"


def print_stats(name: str, times: list[float]):
    """Print statistics for timing results."""
    if not times:
        print(f"  {name}: No data")
        return

    avg = statistics.mean(times) * 1000
    min_t = min(times) * 1000
    max_t = max(times) * 1000
    std = statistics.stdev(times) * 1000 if len(times) > 1 else 0

    print(f"  {name}:")
    print(f"    Avg: {avg:.1f}ms | Min: {min_t:.1f}ms | Max: {max_t:.1f}ms | Std: {std:.1f}ms")


async def get_valid_token_id():
    """Get a valid token ID from an active market."""
    from poly.api.polymarket import PolymarketAPI
    from poly.api.polymarket_config import PolymarketConfig

    config = PolymarketConfig(wallet_address="0x56687bf447db6ffa42ffe2204a05edaa20f55839")
    async with PolymarketAPI(config) as api:
        market = await api.get_market_by_slug(TEST_MARKET_SLUG)
        if market and market.get("tokens"):
            tokens = market["tokens"]
            if tokens:
                return tokens[0].get("token_id")
    return None


# =============================================================================
# py-clob-client Tests
# =============================================================================

def test_py_clob_client(token_id: str):
    """Test py-clob-client package."""
    print("\n" + "=" * 60)
    print("Testing: py-clob-client (sync, uses requests)")
    print("=" * 60)

    try:
        from py_clob_client.client import ClobClient
    except ImportError as e:
        print(f"  Error importing py-clob-client: {e}")
        return None

    client = ClobClient("https://clob.polymarket.com")

    results = {
        "get_midpoint": [],
        "get_order_book": [],
        "get_simplified_markets": [],
    }

    # Warm up with simplified_markets (always works)
    print("  Warming up...")
    try:
        client.get_simplified_markets()
    except Exception as e:
        print(f"  Warmup error: {e}")

    print(f"  Running {NUM_RUNS} iterations...")

    # Test get_midpoint
    for i in range(NUM_RUNS):
        try:
            start = time.perf_counter()
            client.get_midpoint(token_id)
            results["get_midpoint"].append(time.perf_counter() - start)
        except Exception as e:
            if i == 0:
                print(f"    get_midpoint error: {e}")

    # Test get_order_book
    for i in range(NUM_RUNS):
        try:
            start = time.perf_counter()
            client.get_order_book(token_id)
            results["get_order_book"].append(time.perf_counter() - start)
        except Exception as e:
            if i == 0:
                print(f"    get_order_book error: {e}")

    # Test get_simplified_markets
    for i in range(NUM_RUNS):
        try:
            start = time.perf_counter()
            client.get_simplified_markets()
            results["get_simplified_markets"].append(time.perf_counter() - start)
        except Exception as e:
            if i == 0:
                print(f"    get_simplified_markets error: {e}")

    print("\n  Results:")
    for name, times in results.items():
        print_stats(name, times)

    return results


# =============================================================================
# polymarket-apis Tests (uses httpx)
# =============================================================================

def test_polymarket_apis_sync(token_id: str):
    """Test polymarket-apis package (sync methods)."""
    print("\n" + "=" * 60)
    print("Testing: polymarket-apis (sync, uses httpx)")
    print("=" * 60)

    try:
        from polymarket_apis import PolymarketGammaClient
    except ImportError as e:
        print(f"  Error importing polymarket-apis: {e}")
        return None

    gamma_client = PolymarketGammaClient()

    results = {
        "get_markets": [],
        "get_events": [],
    }

    # Warm up
    print("  Warming up...")
    try:
        gamma_client.get_markets(limit=1)
    except Exception as e:
        print(f"  Warmup error: {e}")

    print(f"  Running {NUM_RUNS} iterations...")

    # Test get_markets
    for i in range(NUM_RUNS):
        try:
            start = time.perf_counter()
            gamma_client.get_markets(limit=10)
            results["get_markets"].append(time.perf_counter() - start)
        except Exception as e:
            if i == 0:
                print(f"    get_markets error: {e}")

    # Test get_events
    for i in range(NUM_RUNS):
        try:
            start = time.perf_counter()
            gamma_client.get_events(limit=10)
            results["get_events"].append(time.perf_counter() - start)
        except Exception as e:
            if i == 0:
                print(f"    get_events error: {e}")

    print("\n  Results:")
    for name, times in results.items():
        print_stats(name, times)

    return results


# =============================================================================
# Our Custom API Tests
# =============================================================================

async def test_custom_api_async(token_id: str):
    """Test our custom PolymarketAPI."""
    print("\n" + "=" * 60)
    print("Testing: Custom PolymarketAPI (async, uses aiohttp)")
    print("=" * 60)

    from poly.api.polymarket import PolymarketAPI
    from poly.api.polymarket_config import PolymarketConfig

    config = PolymarketConfig(wallet_address="0x56687bf447db6ffa42ffe2204a05edaa20f55839")

    results = {
        "get_midpoint": [],
        "get_orderbook": [],
        "get_market_info": [],
    }

    async with PolymarketAPI(config) as api:
        # Warm up
        print("  Warming up...")
        try:
            await api.get_market_info(TEST_MARKET_SLUG)
        except Exception as e:
            print(f"  Warmup error: {e}")

        print(f"  Running {NUM_RUNS} iterations...")

        # Test get_midpoint
        for i in range(NUM_RUNS):
            try:
                start = time.perf_counter()
                await api.get_midpoint(token_id)
                results["get_midpoint"].append(time.perf_counter() - start)
            except Exception as e:
                if i == 0:
                    print(f"    get_midpoint error: {e}")

        # Test get_orderbook
        for i in range(NUM_RUNS):
            try:
                start = time.perf_counter()
                await api.get_orderbook(token_id)
                results["get_orderbook"].append(time.perf_counter() - start)
            except Exception as e:
                if i == 0:
                    print(f"    get_orderbook error: {e}")

        # Test get_market_info
        for i in range(NUM_RUNS):
            try:
                start = time.perf_counter()
                await api.get_market_info(TEST_MARKET_SLUG)
                results["get_market_info"].append(time.perf_counter() - start)
            except Exception as e:
                if i == 0:
                    print(f"    get_market_info error: {e}")

    print("\n  Results:")
    for name, times in results.items():
        print_stats(name, times)

    return results


def test_custom_api(token_id: str):
    """Wrapper to run async tests."""
    return asyncio.run(test_custom_api_async(token_id))


# =============================================================================
# Direct HTTP comparison (same endpoint, different libraries)
# =============================================================================

def test_requests_direct(token_id: str):
    """Test direct requests library (what py-clob-client uses)."""
    print("\n" + "=" * 60)
    print("Testing: Direct requests (sync)")
    print("=" * 60)

    import requests

    results = {"get_midpoint": [], "get_orderbook": []}

    # Warm up
    print("  Warming up...")
    try:
        requests.get(f"https://clob.polymarket.com/midpoint?token_id={token_id}")
    except:
        pass

    print(f"  Running {NUM_RUNS} iterations...")
    for i in range(NUM_RUNS):
        try:
            start = time.perf_counter()
            requests.get(f"https://clob.polymarket.com/midpoint?token_id={token_id}")
            results["get_midpoint"].append(time.perf_counter() - start)
        except:
            pass

    for i in range(NUM_RUNS):
        try:
            start = time.perf_counter()
            requests.get(f"https://clob.polymarket.com/book?token_id={token_id}")
            results["get_orderbook"].append(time.perf_counter() - start)
        except:
            pass

    print("\n  Results:")
    for name, times in results.items():
        print_stats(name, times)

    return results


async def test_aiohttp_direct(token_id: str):
    """Test direct aiohttp (what our custom API uses)."""
    print("\n" + "=" * 60)
    print("Testing: Direct aiohttp (async)")
    print("=" * 60)

    import aiohttp

    results = {"get_midpoint": [], "get_orderbook": []}

    async with aiohttp.ClientSession() as session:
        # Warm up
        print("  Warming up...")
        try:
            async with session.get(f"https://clob.polymarket.com/midpoint?token_id={token_id}"):
                pass
        except:
            pass

        print(f"  Running {NUM_RUNS} iterations...")
        for i in range(NUM_RUNS):
            try:
                start = time.perf_counter()
                async with session.get(f"https://clob.polymarket.com/midpoint?token_id={token_id}"):
                    pass
                results["get_midpoint"].append(time.perf_counter() - start)
            except:
                pass

        for i in range(NUM_RUNS):
            try:
                start = time.perf_counter()
                async with session.get(f"https://clob.polymarket.com/book?token_id={token_id}"):
                    pass
                results["get_orderbook"].append(time.perf_counter() - start)
            except:
                pass

    print("\n  Results:")
    for name, times in results.items():
        print_stats(name, times)

    return results


async def test_httpx_direct(token_id: str):
    """Test direct httpx (what polymarket-apis uses)."""
    print("\n" + "=" * 60)
    print("Testing: Direct httpx (async)")
    print("=" * 60)

    import httpx

    results = {"get_midpoint": [], "get_orderbook": []}

    async with httpx.AsyncClient() as client:
        # Warm up
        print("  Warming up...")
        try:
            await client.get(f"https://clob.polymarket.com/midpoint?token_id={token_id}")
        except:
            pass

        print(f"  Running {NUM_RUNS} iterations...")
        for i in range(NUM_RUNS):
            try:
                start = time.perf_counter()
                await client.get(f"https://clob.polymarket.com/midpoint?token_id={token_id}")
                results["get_midpoint"].append(time.perf_counter() - start)
            except:
                pass

        for i in range(NUM_RUNS):
            try:
                start = time.perf_counter()
                await client.get(f"https://clob.polymarket.com/book?token_id={token_id}")
                results["get_orderbook"].append(time.perf_counter() - start)
            except:
                pass

    print("\n  Results:")
    for name, times in results.items():
        print_stats(name, times)

    return results


# =============================================================================
# WebSocket Tests
# =============================================================================

async def test_websocket_aiohttp(token_id: str):
    """Test WebSocket using aiohttp for persistent connection."""
    print("\n" + "=" * 60)
    print("Testing: WebSocket via aiohttp (persistent connection)")
    print("=" * 60)

    import aiohttp

    results = {
        "connection_time": [],
        "first_message_time": [],
        "subsequent_messages": [],
    }

    for run in range(NUM_RUNS):
        try:
            # Measure connection time
            conn_start = time.perf_counter()
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(WS_ENDPOINT, timeout=10) as ws:
                    conn_time = time.perf_counter() - conn_start
                    results["connection_time"].append(conn_time)

                    # Subscribe to market data
                    subscribe_msg = {
                        "assets_ids": [token_id],
                        "type": "market"
                    }
                    await ws.send_json(subscribe_msg)

                    # Measure time to first message
                    first_msg_start = time.perf_counter()
                    try:
                        msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
                        first_msg_time = time.perf_counter() - first_msg_start
                        results["first_message_time"].append(first_msg_time)

                        # Try to get a few more messages to measure ongoing latency
                        for _ in range(3):
                            msg_start = time.perf_counter()
                            try:
                                msg = await asyncio.wait_for(ws.receive(), timeout=2.0)
                                msg_time = time.perf_counter() - msg_start
                                results["subsequent_messages"].append(msg_time)
                            except asyncio.TimeoutError:
                                break
                    except asyncio.TimeoutError:
                        if run == 0:
                            print("    Timeout waiting for first message")

        except Exception as e:
            if run == 0:
                print(f"    Connection error: {e}")

    print(f"  Completed {len(results['connection_time'])} connection(s)")
    print("\n  Results:")
    print_stats("connection_time", results["connection_time"])
    print_stats("first_message_time", results["first_message_time"])
    print_stats("subsequent_messages", results["subsequent_messages"])

    return results


async def test_websocket_websockets_lib(token_id: str):
    """Test WebSocket using websockets library."""
    print("\n" + "=" * 60)
    print("Testing: WebSocket via websockets library")
    print("=" * 60)

    try:
        import websockets
    except ImportError:
        print("  websockets library not installed, skipping")
        return None

    results = {
        "connection_time": [],
        "first_message_time": [],
        "subsequent_messages": [],
    }

    for run in range(NUM_RUNS):
        try:
            # Measure connection time
            conn_start = time.perf_counter()
            async with websockets.connect(WS_ENDPOINT, close_timeout=5) as ws:
                conn_time = time.perf_counter() - conn_start
                results["connection_time"].append(conn_time)

                # Subscribe to market data
                subscribe_msg = {
                    "assets_ids": [token_id],
                    "type": "market"
                }
                await ws.send(json.dumps(subscribe_msg))

                # Measure time to first message
                first_msg_start = time.perf_counter()
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    first_msg_time = time.perf_counter() - first_msg_start
                    results["first_message_time"].append(first_msg_time)

                    # Try to get a few more messages
                    for _ in range(3):
                        msg_start = time.perf_counter()
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                            msg_time = time.perf_counter() - msg_start
                            results["subsequent_messages"].append(msg_time)
                        except asyncio.TimeoutError:
                            break
                except asyncio.TimeoutError:
                    if run == 0:
                        print("    Timeout waiting for first message")

        except Exception as e:
            if run == 0:
                print(f"    Connection error: {e}")

    print(f"  Completed {len(results['connection_time'])} connection(s)")
    print("\n  Results:")
    print_stats("connection_time", results["connection_time"])
    print_stats("first_message_time", results["first_message_time"])
    print_stats("subsequent_messages", results["subsequent_messages"])

    return results


async def test_websocket_persistent_vs_polling(token_id: str):
    """Compare persistent WebSocket vs repeated HTTP polling."""
    print("\n" + "=" * 60)
    print("Testing: Persistent WebSocket vs HTTP Polling (20 requests)")
    print("=" * 60)

    import aiohttp

    num_requests = 20

    # Test HTTP polling
    print("\n  HTTP Polling (20 sequential requests):")
    http_times = []
    async with aiohttp.ClientSession() as session:
        # Warm up
        async with session.get(f"https://clob.polymarket.com/midpoint?token_id={token_id}"):
            pass

        total_start = time.perf_counter()
        for i in range(num_requests):
            start = time.perf_counter()
            async with session.get(f"https://clob.polymarket.com/midpoint?token_id={token_id}"):
                pass
            http_times.append(time.perf_counter() - start)
        total_http_time = time.perf_counter() - total_start

    print(f"    Total time for {num_requests} HTTP requests: {total_http_time*1000:.1f}ms")
    print(f"    Average per request: {statistics.mean(http_times)*1000:.1f}ms")

    # Test WebSocket (receive 20 messages)
    print("\n  WebSocket (receive up to 20 messages):")
    ws_times = []
    ws_connection_time = 0

    try:
        async with aiohttp.ClientSession() as session:
            conn_start = time.perf_counter()
            async with session.ws_connect(WS_ENDPOINT, timeout=10) as ws:
                ws_connection_time = time.perf_counter() - conn_start

                # Subscribe
                await ws.send_json({
                    "assets_ids": [token_id],
                    "type": "market"
                })

                total_start = time.perf_counter()
                messages_received = 0
                for i in range(num_requests):
                    try:
                        start = time.perf_counter()
                        msg = await asyncio.wait_for(ws.receive(), timeout=3.0)
                        ws_times.append(time.perf_counter() - start)
                        messages_received += 1
                    except asyncio.TimeoutError:
                        break
                total_ws_time = time.perf_counter() - total_start

        if ws_times:
            print(f"    Connection time: {ws_connection_time*1000:.1f}ms")
            print(f"    Messages received: {messages_received}")
            print(f"    Total time for {messages_received} messages: {total_ws_time*1000:.1f}ms")
            print(f"    Average per message: {statistics.mean(ws_times)*1000:.1f}ms")
        else:
            print("    No messages received (market may be inactive)")

    except Exception as e:
        print(f"    WebSocket error: {e}")

    # Summary comparison
    print("\n  Summary:")
    print(f"    HTTP avg latency:      {statistics.mean(http_times)*1000:.1f}ms per request")
    if ws_times:
        print(f"    WebSocket avg latency: {statistics.mean(ws_times)*1000:.1f}ms per message")
        print(f"    WebSocket is {statistics.mean(http_times)/statistics.mean(ws_times):.1f}x faster per message")
        print(f"    (but WebSocket connection overhead: {ws_connection_time*1000:.1f}ms)")

    return {
        "http_avg": statistics.mean(http_times) if http_times else 0,
        "ws_avg": statistics.mean(ws_times) if ws_times else 0,
        "ws_connection": ws_connection_time,
    }


# =============================================================================
# Comparison Summary
# =============================================================================

def compare_results(results_dict: dict):
    """Compare and summarize results."""
    print("\n" + "=" * 60)
    print("COMPARISON SUMMARY - get_midpoint (avg ms)")
    print("=" * 60)

    midpoint_results = []
    for name, results in results_dict.items():
        if results and results.get("get_midpoint"):
            avg = statistics.mean(results["get_midpoint"]) * 1000
            midpoint_results.append((name, avg))
            print(f"  {name:30s}: {avg:>8.1f}ms")

    if midpoint_results:
        winner = min(midpoint_results, key=lambda x: x[1])
        print(f"\n  Fastest: {winner[0]} ({winner[1]:.1f}ms)")

    print("\n" + "=" * 60)
    print("COMPARISON SUMMARY - get_orderbook (avg ms)")
    print("=" * 60)

    orderbook_results = []
    for name, results in results_dict.items():
        key = "get_orderbook" if "get_orderbook" in (results or {}) else "get_order_book"
        if results and results.get(key):
            avg = statistics.mean(results[key]) * 1000
            orderbook_results.append((name, avg))
            print(f"  {name:30s}: {avg:>8.1f}ms")

    if orderbook_results:
        winner = min(orderbook_results, key=lambda x: x[1])
        print(f"\n  Fastest: {winner[0]} ({winner[1]:.1f}ms)")

    print("\n" + "=" * 60)
    print("COMPARISON SUMMARY - get_markets/get_simplified_markets (avg ms)")
    print("=" * 60)

    markets_results = []
    for name, results in results_dict.items():
        for key in ["get_markets", "get_simplified_markets", "get_market_info"]:
            if results and results.get(key):
                avg = statistics.mean(results[key]) * 1000
                markets_results.append((f"{name} ({key})", avg))
                print(f"  {name:30s}: {avg:>8.1f}ms ({key})")
                break

    if markets_results:
        winner = min(markets_results, key=lambda x: x[1])
        print(f"\n  Fastest: {winner[0]} ({winner[1]:.1f}ms)")


def main():
    print("=" * 60)
    print("POLYMARKET API BENCHMARK")
    print(f"Running {NUM_RUNS} iterations per test")
    print("=" * 60)

    # Get a valid token ID first
    print("\nFetching valid token ID...")
    token_id = asyncio.run(get_valid_token_id())
    if not token_id:
        print("Could not get valid token ID, using fallback")
        token_id = "71321045679252212594626385532706912750332728571942532289631379312455583992563"

    print(f"Using token ID: {token_id[:20]}...")

    all_results = {}

    # Run direct HTTP library tests first (most fair comparison)
    all_results["requests (sync)"] = test_requests_direct(token_id)
    all_results["aiohttp (async)"] = asyncio.run(test_aiohttp_direct(token_id))
    all_results["httpx (async)"] = asyncio.run(test_httpx_direct(token_id))

    # Run package tests
    all_results["py-clob-client"] = test_py_clob_client(token_id)
    all_results["polymarket-apis"] = test_polymarket_apis_sync(token_id)
    all_results["custom API"] = test_custom_api(token_id)

    # Compare HTTP results
    compare_results(all_results)

    # WebSocket tests
    print("\n" + "=" * 60)
    print("WEBSOCKET TESTS")
    print("=" * 60)

    # Test WebSocket connection and message latency
    asyncio.run(test_websocket_aiohttp(token_id))
    asyncio.run(test_websocket_websockets_lib(token_id))

    # Compare WebSocket vs HTTP polling
    asyncio.run(test_websocket_persistent_vs_polling(token_id))

    print("\n" + "=" * 60)
    print("Benchmark complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
