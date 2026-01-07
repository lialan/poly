#!/usr/bin/env python3
"""
Test script for Polymarket API module.

Usage:
    # Test with a known wallet address (read-only)
    python scripts/test_polymarket_api.py --wallet 0x1234...

    # Test with config file
    python scripts/test_polymarket_api.py --config config/polymarket.json

    # Test with Secret Manager (requires GOOGLE_CLOUD_PROJECT env var)
    python scripts/test_polymarket_api.py --use-secret-manager

    # Test with env vars (local testing)
    POLYMARKET_WALLET_ADDRESS=0x1234... python scripts/test_polymarket_api.py

    # Test market query
    python scripts/test_polymarket_api.py --wallet 0x1234... --market btc-updown-15m-1767795300
"""

import argparse
import asyncio
import sys
import time
from contextlib import contextmanager
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from poly.polymarket_config import PolymarketConfig
from poly.polymarket_api import (
    PolymarketAPI,
    PolymarketAPISync,
    MarketStatus,
    TradeStatus,
)


@contextmanager
def timed(description: str):
    """Context manager to time a block of code."""
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    print(f"  [{elapsed*1000:.1f}ms] {description}")


async def timed_async(coro, description: str):
    """Time an async coroutine and print the result."""
    start = time.perf_counter()
    result = await coro
    elapsed = time.perf_counter() - start
    print(f"  [{elapsed*1000:.1f}ms] {description}")
    return result


async def test_async_api(config: PolymarketConfig, market_slug: str = None):
    """Test async API methods."""
    print("=" * 60)
    print("Testing Async PolymarketAPI")
    print("=" * 60)
    print(f"Wallet: {config.wallet_address}")
    print()

    total_start = time.perf_counter()

    async with PolymarketAPI(config) as api:
        # Test get_positions
        print("Fetching positions...")
        try:
            positions = await timed_async(
                api.get_positions(limit=10),
                "get_positions(limit=10)"
            )
            print(f"  Found {len(positions)} position(s)")

            for pos in positions[:5]:  # Show first 5
                print(f"    - {pos}")

            if positions:
                total_value = sum(p.current_value for p in positions)
                print(f"\n  Total value of shown positions: ${total_value:.2f}")
        except Exception as e:
            print(f"  Error fetching positions: {e}")

        # Test market query if provided
        if market_slug:
            print(f"\nFetching market: {market_slug}")
            try:
                market = await timed_async(
                    api.get_market_by_slug(market_slug),
                    "get_market_by_slug()"
                )
                if market:
                    print(f"    Title: {market.get('question', 'N/A')}")
                    print(f"    Condition ID: {market.get('conditionId', 'N/A')}")

                    # Get positions for this market
                    market_positions = await timed_async(
                        api.get_position_for_market(market_slug),
                        "get_position_for_market()"
                    )
                    print(f"    Positions in this market: {len(market_positions)}")

                    # Get shares
                    shares = await timed_async(
                        api.get_shares_for_market(market_slug),
                        "get_shares_for_market()"
                    )
                    print(f"    Yes shares: {shares.get('Yes', 0):.2f}")
                    print(f"    No shares: {shares.get('No', 0):.2f}")

                    # Get market status
                    market_info = await timed_async(
                        api.get_market_info(market_slug),
                        "get_market_info()"
                    )
                    if market_info:
                        print(f"    Status: {market_info.status.value}")
                        print(f"    Active: {market_info.is_active}")
                        print(f"    Resolved: {market_info.is_resolved}")
                        if market_info.end_date:
                            print(f"    End date: {market_info.end_date}")
                else:
                    print(f"    Market not found")
            except Exception as e:
                print(f"  Error: {e}")

        # Test trade queries
        print("\nFetching trades...")
        try:
            trades = await timed_async(
                api.get_trades(limit=5),
                "get_trades(limit=5)"
            )
            print(f"  Found {len(trades)} trade(s)")
            for trade in trades[:3]:
                print(f"    - {trade}")
                print(f"      Status: {trade.status.value}, Confirmed: {trade.is_confirmed}")
        except Exception as e:
            print(f"  Error fetching trades: {e}")

    total_elapsed = time.perf_counter() - total_start
    print(f"\nAsync API test complete (total: {total_elapsed*1000:.1f}ms)")


def test_sync_api(config: PolymarketConfig, market_slug: str = None):
    """Test sync API methods."""
    print("=" * 60)
    print("Testing Sync PolymarketAPISync")
    print("=" * 60)
    print(f"Wallet: {config.wallet_address}")
    print()

    total_start = time.perf_counter()
    api = PolymarketAPISync(config)

    try:
        # Test get_positions
        print("Fetching positions...")
        with timed("get_positions(limit=10)"):
            positions = api.get_positions(limit=10)
        print(f"  Found {len(positions)} position(s)")

        for pos in positions[:5]:
            print(f"    - {pos}")

        # Test market query if provided
        if market_slug:
            print(f"\nFetching shares for market: {market_slug}")
            with timed("get_shares_for_market()"):
                shares = api.get_shares_for_market(market_slug)
            print(f"    Yes shares: {shares.get('Yes', 0):.2f}")
            print(f"    No shares: {shares.get('No', 0):.2f}")

    except Exception as e:
        print(f"  Error: {e}")
    finally:
        api.close()

    total_elapsed = time.perf_counter() - total_start
    print(f"\nSync API test complete (total: {total_elapsed*1000:.1f}ms)")


def main():
    parser = argparse.ArgumentParser(description="Test Polymarket API")
    parser.add_argument(
        "--wallet", type=str,
        help="Wallet address to query (0x-prefixed)"
    )
    parser.add_argument(
        "--config", type=str,
        help="Path to config file"
    )
    parser.add_argument(
        "--use-secret-manager", action="store_true",
        help="Load config from Google Secret Manager"
    )
    parser.add_argument(
        "--project-id", type=str,
        help="GCP project ID for Secret Manager"
    )
    parser.add_argument(
        "--market", type=str,
        help="Market slug to query"
    )
    parser.add_argument(
        "--sync", action="store_true",
        help="Test sync API instead of async"
    )

    args = parser.parse_args()

    # Create config
    config_start = time.perf_counter()
    if args.config:
        config = PolymarketConfig.from_json(args.config)
        config_source = "JSON file"
    elif args.wallet:
        config = PolymarketConfig(wallet_address=args.wallet)
        config_source = "CLI argument"
    elif args.use_secret_manager:
        try:
            config = PolymarketConfig.from_secret_manager(
                project_id=args.project_id,
                use_env_fallback=True,
            )
            config_source = f"Secret Manager (project: {args.project_id or 'default'})"
        except Exception as e:
            print(f"Error loading from Secret Manager: {e}")
            return
    else:
        # Try default config location (includes Secret Manager with env fallback)
        try:
            config = PolymarketConfig.load(project_id=args.project_id)
            config_source = "auto-detect"
        except Exception as e:
            print(f"Error loading config: {e}")
            print("\nUsage:")
            print("  python scripts/test_polymarket_api.py --wallet 0x...")
            print("  python scripts/test_polymarket_api.py --config config/polymarket.json")
            print("  python scripts/test_polymarket_api.py --use-secret-manager")
            print("  POLYMARKET_WALLET_ADDRESS=0x... python scripts/test_polymarket_api.py")
            return

    config_elapsed = time.perf_counter() - config_start
    print(f"Config loaded from {config_source} [{config_elapsed*1000:.1f}ms]")
    print()

    if args.sync:
        test_sync_api(config, args.market)
    else:
        asyncio.run(test_async_api(config, args.market))


if __name__ == "__main__":
    main()
