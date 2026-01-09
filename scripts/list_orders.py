#!/usr/bin/env python3
"""
Manage Orders and Positions
===========================

Lists open orders and positions on Polymarket. Allows cancelling orders
and selling positions.

Usage:
    python scripts/list_orders.py                 # List open orders
    python scripts/list_orders.py -p              # List positions (shares held)
    python scripts/list_orders.py -c              # List orders and cancel interactively
    python scripts/list_orders.py -s              # List positions and sell interactively
    python scripts/list_orders.py -x ORDER_ID     # Cancel specific order by ID/hash

Requirements:
    - POLYMARKET_WALLET_ADDRESS and POLYMARKET_PRIVATE_KEY must be set
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, "src")

from poly import PolymarketAPI, PolymarketConfig, OrderSide
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


def format_position(pos, index: int) -> str:
    """Format a position for display.

    Args:
        pos: MarketPosition object
        index: Display index (1-based)

    Returns:
        Formatted string for display
    """
    # Format end date
    end_str = "N/A"
    if pos.end_date:
        end_str = pos.end_date.strftime("%Y-%m-%d %H:%M")

    pnl_sign = "+" if pos.cash_pnl >= 0 else ""

    lines = [
        f"[{index}] {pos.title[:50]}..." if len(pos.title) > 50 else f"[{index}] {pos.title}",
        f"    Outcome: {pos.outcome}  Shares: {pos.size:.2f}  Avg Price: {pos.avg_price:.4f}",
        f"    Current: {pos.current_price:.4f}  Value: ${pos.current_value:.2f}  PnL: {pnl_sign}${pos.cash_pnl:.2f} ({pnl_sign}{pos.percent_pnl:.1f}%)",
        f"    Ends: {end_str}  Slug: {pos.slug[:30]}..." if len(pos.slug) > 30 else f"    Ends: {end_str}  Slug: {pos.slug}",
    ]
    return "\n".join(lines)


async def get_orderbook_price(api: PolymarketAPI, token_id: str, side: str) -> float:
    """Get best bid or ask price from orderbook.

    Args:
        api: Polymarket API client
        token_id: Token ID to query
        side: "bid" or "ask"

    Returns:
        Best price (0 if no orders)
    """
    try:
        orderbook = await api.get_orderbook(token_id)
        if side == "bid":
            bids = orderbook.get("bids", [])
            if bids:
                return max(float(b["price"]) for b in bids)
        else:
            asks = orderbook.get("asks", [])
            if asks:
                return min(float(a["price"]) for a in asks)
    except Exception:
        pass
    return 0.0


async def sell_position(api: PolymarketAPI, pos, price: float = None, market_order: bool = False) -> bool:
    """Sell all shares of a position.

    Args:
        api: Polymarket API client
        pos: MarketPosition object
        price: Limit price (None = use best bid, ignored if market_order=True)
        market_order: If True, use aggressive price (0.01) to fill immediately

    Returns:
        True if order placed successfully
    """
    try:
        if market_order:
            # Market order: use minimum price to ensure immediate fill
            price = 0.01
            print(f"    Market order at {price:.2f} (will fill at best bid)")
        elif price is None:
            # Limit order at best bid
            price = await get_orderbook_price(api, pos.asset, "bid")
            if price <= 0:
                print(f"    [ERROR] No bids available for {pos.outcome}")
                return False
            print(f"    Using best bid: {price:.4f}")

        # Place sell order
        result = await api.place_order(
            token_id=pos.asset,
            side=OrderSide.SELL,
            price=price,
            size=pos.size,
        )

        if result.success:
            print(f"    [OK] Sell order placed: {result.order_id}")
            return True
        else:
            print(f"    [ERROR] {result.error_message}")
            return False

    except Exception as e:
        print(f"    [ERROR] Failed to sell: {e}")
        return False


async def interactive_sell(api: PolymarketAPI, positions: list) -> int:
    """Interactive mode to sell positions.

    Args:
        api: Polymarket API client
        positions: List of MarketPosition objects

    Returns:
        Number of positions sold
    """
    if not positions:
        print("\nNo positions to sell.")
        return 0

    print("\nEnter position number to sell (or 'q' to quit, 'a' to sell all as market order):")

    sold = 0
    while True:
        try:
            choice = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            break

        if choice == "q" or choice == "":
            break

        if choice == "a":
            print("\nSelling all positions as market orders...")
            for pos in positions:
                print(f"  Selling {pos.size:.2f} {pos.outcome} shares of {pos.title[:30]}...")
                if await sell_position(api, pos, market_order=True):
                    sold += 1
            break

        try:
            idx = int(choice)
            if 1 <= idx <= len(positions):
                pos = positions[idx - 1]
                print(f"  Selling {pos.size:.2f} {pos.outcome} shares...")
                if await sell_position(api, pos):
                    sold += 1
                    positions.pop(idx - 1)
                    if not positions:
                        print("\nAll positions sold.")
                        break
                    print("\nRemaining positions:")
                    for i, p in enumerate(positions, 1):
                        print(format_position(p, i))
                    print("\nEnter position number to sell (or 'q' to quit):")
            else:
                print(f"Invalid selection. Enter 1-{len(positions)}, 'a' for all, or 'q' to quit.")
        except ValueError:
            print("Invalid input. Enter a number, 'a' for all, or 'q' to quit.")

    return sold


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
    # Determine mode
    show_positions = args.positions or args.sell
    title = "POLYMARKET POSITIONS" if show_positions else "POLYMARKET OPEN ORDERS"

    print("=" * 60)
    print(title)
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

    if not config.has_trading_credentials:
        print("    [ERROR] No trading credentials configured")
        print("    Set POLYMARKET_PRIVATE_KEY environment variable")
        return 1

    # Cancel specific order by ID if provided
    if args.cancel_id:
        order_id = args.cancel_id
        print(f"\n[2] Cancelling order: {order_id}")

        api = PolymarketAPI(config)
        try:
            if await cancel_order_by_id(api, order_id):
                print("    [OK] Order cancelled successfully")
                return 0
            else:
                return 1
        finally:
            await api.close()

    # Show positions mode
    if show_positions:
        print("\n[2] Fetching positions...")
        api = PolymarketAPI(config)
        try:
            positions = await api.get_positions(size_threshold=0.01)
            print(f"    Found {len(positions)} position(s)")

            if not positions:
                print("\n    No positions.")
                return 0

            # Display positions
            print("\n" + "=" * 60)
            print("POSITIONS")
            print("=" * 60)
            for i, pos in enumerate(positions, 1):
                print()
                print(format_position(pos, i))

            total_value = sum(p.current_value for p in positions)
            total_pnl = sum(p.cash_pnl for p in positions)
            pnl_sign = "+" if total_pnl >= 0 else ""
            print()
            print(f"Total: {len(positions)} position(s)  Value: ${total_value:.2f}  PnL: {pnl_sign}${total_pnl:.2f}")

            # Interactive sell mode
            if args.sell:
                sold = await interactive_sell(api, list(positions))
                print(f"\nPlaced {sold} sell order(s)")

        finally:
            await api.close()

        return 0

    # Show orders mode (default)
    print("\n[2] Fetching open orders...")

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
        api = PolymarketAPI(config)
        try:
            cancelled = await interactive_cancel(api, orders)
            print(f"\nCancelled {cancelled} order(s)")
        finally:
            await api.close()

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Manage orders and positions on Polymarket",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # List all open orders (default)
    python scripts/list_orders.py

    # List orders and prompt to cancel
    python scripts/list_orders.py -c

    # Cancel a specific order by ID/hash
    python scripts/list_orders.py -x ORDER_ID_HERE

    # List current positions (shares held)
    python scripts/list_orders.py -p

    # List positions and prompt to sell
    python scripts/list_orders.py -s
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

    parser.add_argument(
        "-p", "--positions",
        action="store_true",
        help="Show current positions (shares held) instead of orders",
    )

    parser.add_argument(
        "-s", "--sell",
        action="store_true",
        help="Interactive sell mode: list positions then prompt to sell",
    )

    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
