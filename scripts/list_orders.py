#!/usr/bin/env python3
"""
List and Cancel Open Orders
============================

Lists all open orders on Polymarket and allows cancellation.

Usage:
    python scripts/list_orders.py                 # List all open orders
    python scripts/list_orders.py -c              # List and prompt to cancel
    python scripts/list_orders.py -x ORDER_ID     # Cancel specific order by ID/hash

Requirements:
    - POLYMARKET_WALLET_ADDRESS and POLYMARKET_PRIVATE_KEY must be set
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, "src")

from poly import PolymarketAPI, PolymarketConfig
from poly.api.signer import LocalSigner


def get_open_orders(config: PolymarketConfig) -> list[dict]:
    """Fetch all open orders for the configured wallet using py-clob-client.

    Args:
        config: Polymarket configuration with credentials

    Returns:
        List of open order dictionaries
    """
    if not config.private_key:
        raise ValueError("Private key required to fetch orders")

    signer = LocalSigner(private_key=config.private_key)
    client = signer._get_clob_client()

    # Fetch open orders (LIVE state)
    orders = client.get_orders()

    # Filter to only LIVE orders
    return [o for o in orders if o.get("status") == "LIVE" or o.get("state") == "LIVE"]


def format_order(order: dict, index: int) -> str:
    """Format an order for display.

    Args:
        order: Order dictionary from API
        index: Display index (1-based)

    Returns:
        Formatted string for display
    """
    order_id = order.get("id", "N/A")
    token_id = order.get("asset_id", order.get("token_id", "N/A"))
    side = order.get("side", "N/A")
    price = float(order.get("price", 0))
    size = float(order.get("original_size", order.get("size", 0)))
    size_matched = float(order.get("size_matched", 0))
    remaining = size - size_matched
    created = order.get("created_at", order.get("timestamp", "N/A"))

    # Try to parse timestamp
    if isinstance(created, (int, float)):
        try:
            dt = datetime.fromtimestamp(created / 1000, tz=timezone.utc)
            created = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError):
            pass

    lines = [
        f"[{index}] Order ID: {order_id[:20]}..." if len(str(order_id)) > 20 else f"[{index}] Order ID: {order_id}",
        f"    Side: {side}  Price: {price:.4f}  Size: {remaining:.2f}/{size:.2f}",
        f"    Token: {token_id[:40]}..." if len(str(token_id)) > 40 else f"    Token: {token_id}",
        f"    Created: {created}",
    ]
    return "\n".join(lines)


async def cancel_order_by_id(api: PolymarketAPI, order_id: str) -> bool:
    """Cancel a specific order.

    Args:
        api: Polymarket API client
        order_id: Order ID to cancel

    Returns:
        True if cancelled successfully
    """
    try:
        result = await api.cancel_order(order_id)
        return result
    except Exception as e:
        print(f"    [ERROR] Failed to cancel: {e}")
        return False


async def interactive_cancel(api: PolymarketAPI, orders: list[dict]) -> int:
    """Interactive mode to cancel orders.

    Args:
        api: Polymarket API client
        orders: List of open orders

    Returns:
        Number of orders cancelled
    """
    if not orders:
        print("\nNo open orders to cancel.")
        return 0

    print("\nEnter order number to cancel (or 'q' to quit, 'a' to cancel all):")

    cancelled = 0
    while True:
        try:
            choice = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            break

        if choice == "q" or choice == "":
            break

        if choice == "a":
            print("\nCancelling all orders...")
            for order in orders:
                order_id = order.get("id")
                if order_id:
                    print(f"  Cancelling {order_id[:20]}...", end=" ")
                    if await cancel_order_by_id(api, order_id):
                        print("[OK]")
                        cancelled += 1
                    else:
                        print("[FAILED]")
            break

        try:
            idx = int(choice)
            if 1 <= idx <= len(orders):
                order = orders[idx - 1]
                order_id = order.get("id")
                if order_id:
                    print(f"  Cancelling order {idx}...", end=" ")
                    if await cancel_order_by_id(api, order_id):
                        print("[OK]")
                        cancelled += 1
                        # Remove from list
                        orders.pop(idx - 1)
                        if not orders:
                            print("\nAll orders cancelled.")
                            break
                        print("\nRemaining orders:")
                        for i, o in enumerate(orders, 1):
                            print(format_order(o, i))
                        print("\nEnter order number to cancel (or 'q' to quit):")
                    else:
                        print("[FAILED]")
            else:
                print(f"Invalid selection. Enter 1-{len(orders)}, 'a' for all, or 'q' to quit.")
        except ValueError:
            print("Invalid input. Enter a number, 'a' for all, or 'q' to quit.")

    return cancelled


async def main_async(args: argparse.Namespace) -> int:
    """Main async function.

    Args:
        args: Parsed command line arguments

    Returns:
        Exit code (0 for success)
    """
    print("=" * 60)
    print("POLYMARKET OPEN ORDERS")
    print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    # Load config
    print("\n[1] Loading configuration...")
    try:
        config = PolymarketConfig.load()
        print(f"    Wallet: {config.wallet_address}")
    except Exception as e:
        print(f"    [ERROR] Failed to load config: {e}")
        return 1

    # Cancel specific order by ID if provided
    if args.cancel_id:
        order_id = args.cancel_id
        print(f"\n[2] Cancelling order: {order_id}")

        if not config.has_trading_credentials:
            print("    [ERROR] No trading credentials configured")
            return 1

        api = PolymarketAPI(config)
        try:
            if await cancel_order_by_id(api, order_id):
                print("    [OK] Order cancelled successfully")
                return 0
            else:
                return 1
        finally:
            await api.close()

    # Fetch open orders
    print("\n[2] Fetching open orders...")

    if not config.has_trading_credentials:
        print("    [ERROR] No trading credentials configured")
        print("    Set POLYMARKET_PRIVATE_KEY environment variable")
        return 1

    try:
        orders = get_open_orders(config)
        print(f"    Found {len(orders)} open order(s)")
    except Exception as e:
        print(f"    [ERROR] {e}")
        return 1

    if not orders:
        print("\n    No open orders.")
        return 0

    # Display orders
    print("\n" + "=" * 60)
    print("OPEN ORDERS")
    print("=" * 60)
    for i, order in enumerate(orders, 1):
        print()
        print(format_order(order, i))

    print()
    print(f"Total: {len(orders)} order(s)")

    # Interactive cancel mode
    if args.cancel:
        if not config.has_trading_credentials:
            print("\n[ERROR] No trading credentials - cannot cancel orders")
            print("Set POLYMARKET_PRIVATE_KEY environment variable")
            return 1

        api = PolymarketAPI(config)
        try:
            cancelled = await interactive_cancel(api, orders)
            print(f"\nCancelled {cancelled} order(s)")
        finally:
            await api.close()

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="List and cancel open orders on Polymarket",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # List all open orders
    python scripts/list_orders.py

    # List orders and prompt to cancel
    python scripts/list_orders.py -c

    # Cancel a specific order by ID/hash
    python scripts/list_orders.py -x ORDER_ID_HERE
        """,
    )

    parser.add_argument(
        "-c", "--cancel",
        action="store_true",
        help="Interactive cancel mode: list orders then prompt to cancel",
    )

    parser.add_argument(
        "-x", "--cancel-id",
        type=str,
        metavar="ORDER_ID",
        help="Cancel a specific order by ID/hash",
    )

    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
