#!/usr/bin/env python3
"""
Test Order Placement and Cancellation APIs
==========================================

Places a limit order that won't fill, then immediately cancels it.
Used to verify the order placement and cancellation APIs are working.

Usage:
    python scripts/test_order_api.py
    python scripts/test_order_api.py --dry-run  # Print what would happen without placing

Requirements:
    - POLYMARKET_WALLET_ADDRESS and POLYMARKET_PRIVATE_KEY must be set
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from poly import (
    PolymarketAPI,
    PolymarketConfig,
    OrderSide,
    Asset,
    MarketHorizon,
)
from poly.markets import fetch_current_prediction


async def main(dry_run: bool = False) -> int:
    print("=" * 60)
    print("TEST: Order Placement and Cancellation APIs")
    print("=" * 60)

    # Load config
    print("\n[1] Loading configuration...")
    try:
        config = PolymarketConfig.load()
        print(f"    Wallet: {config.wallet_address}")
    except Exception as e:
        print(f"    [ERROR] Failed to load config: {e}")
        return 1

    if not config.has_trading_credentials:
        print("    [ERROR] No trading credentials configured")
        print("    Set POLYMARKET_PRIVATE_KEY environment variable")
        return 1

    # Fetch current BTC 15m market
    print("\n[2] Fetching current BTC 15m market...")
    market = await fetch_current_prediction(Asset.BTC, MarketHorizon.M15)
    if not market:
        print("    [ERROR] No market found")
        return 1

    print(f"    Slug: {market.slug}")
    print(f"    UP token:   {market.up_token_id[:20]}...")
    print(f"    DOWN token: {market.down_token_id[:20]}...")
    print(f"    Current UP price: {market.up_price}")

    # We'll place a BUY order for UP token at the minimum price (0.001)
    # This ensures it won't fill since no one sells at this price
    # Minimum order size is $1, so we need 1000 shares at $0.001
    token_id = market.up_token_id
    side = OrderSide.BUY
    price = 0.001  # Minimum price - definitely won't fill
    size = 1000.0  # 1000 shares at $0.001 = $1 minimum

    print(f"\n[3] Order details:")
    print(f"    Token: UP (YES)")
    print(f"    Side:  {side.value}")
    print(f"    Price: {price} (very low - won't fill)")
    print(f"    Size:  {size} shares")
    print(f"    Cost if filled: ${price * size:.2f}")

    if dry_run:
        print("\n[DRY RUN] Would place order, then cancel it.")
        print("[DRY RUN] No actual orders placed.")
        return 0

    # Place the order
    print("\n[4] Placing limit order...")
    api = PolymarketAPI(config)
    try:
        result = await api.place_order(
            token_id=token_id,
            side=side,
            price=price,
            size=size,
        )

        if not result.success:
            print(f"    [ERROR] Order failed: {result.error_message}")
            await api.close()
            return 1

        print(f"    [OK] Order placed successfully!")
        print(f"    Order ID: {result.order_id}")
        print(f"    Submission time: {result.submission_time_ms:.1f}ms")
        print(f"    Timestamp: {result.timestamp}")

        order_id = result.order_id

        # Brief pause to let order settle
        print("\n[5] Waiting 1 second before cancellation...")
        await asyncio.sleep(1.0)

        # Cancel the order
        print("\n[6] Cancelling order...")
        cancel_success = await api.cancel_order(order_id)

        if cancel_success:
            print(f"    [OK] Order cancelled successfully!")
        else:
            print(f"    [WARN] Cancel returned False (order may have already been cancelled or filled)")

        # Try to get order status
        print("\n[7] Checking final order status...")
        try:
            order_info = await api.get_order(order_id)
            print(f"    Status: {order_info.status}")
            print(f"    Size matched: {order_info.size_matched}/{order_info.original_size}")
        except Exception as e:
            print(f"    [INFO] Could not fetch order status: {e}")

    except Exception as e:
        print(f"    [ERROR] {e}")
        await api.close()
        return 1
    finally:
        await api.close()

    print("\n" + "=" * 60)
    print("TEST COMPLETE - APIs are working!")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test order placement and cancellation APIs")
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Print what would happen without placing real orders",
    )
    args = parser.parse_args()

    sys.exit(asyncio.run(main(dry_run=args.dry_run)))
