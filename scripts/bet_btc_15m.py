#!/usr/bin/env python3
"""
Bet on BTC 15-minute prediction market.

Places a market order on the current live BTC 15m UP/DOWN market.

Usage:
    # Bet $10 on UP
    python scripts/bet_btc_15m.py --side up --amount 10

    # Bet $5 on DOWN
    python scripts/bet_btc_15m.py --side down --amount 5

    # Dry run (don't actually place order)
    python scripts/bet_btc_15m.py --side up --amount 10 --dry-run

    # Use specific price instead of market price
    python scripts/bet_btc_15m.py --side up --amount 10 --price 0.55

Requirements:
    - POLYMARKET_WALLET_ADDRESS and POLYMARKET_PRIVATE_KEY must be set
    - Wallet must have USDC balance and allowance on Polymarket
"""

import argparse
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
    OrderSide,
)


# Polymarket contract addresses (Polygon mainnet)
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
POLYGON_RPC = "https://polygon-rpc.com"


def get_usdc_balance_and_allowance(wallet_address: str) -> dict:
    """Get USDC balance and allowance for Polymarket exchange.

    Returns dict with balance, allowance (in USDC, 6 decimals), and raw values.
    """
    import requests

    # ERC20 function signatures
    # balanceOf(address) = 0x70a08231
    # allowance(address,address) = 0xdd62ed3e

    wallet_padded = wallet_address.lower().replace("0x", "").zfill(64)
    exchange_padded = EXCHANGE_ADDRESS.lower().replace("0x", "").zfill(64)

    def eth_call(to: str, data: str) -> str:
        resp = requests.post(POLYGON_RPC, json={
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [{"to": to, "data": data}, "latest"],
            "id": 1,
        })
        result = resp.json()
        if "error" in result:
            raise Exception(result["error"]["message"])
        return result["result"]

    # Get balance
    balance_data = f"0x70a08231{wallet_padded}"
    balance_hex = eth_call(USDC_ADDRESS, balance_data)
    balance_raw = int(balance_hex, 16)
    balance = balance_raw / 1e6  # USDC has 6 decimals

    # Get allowance
    allowance_data = f"0xdd62ed3e{wallet_padded}{exchange_padded}"
    allowance_hex = eth_call(USDC_ADDRESS, allowance_data)
    allowance_raw = int(allowance_hex, 16)
    allowance = allowance_raw / 1e6

    return {
        "balance": balance,
        "allowance": allowance,
        "balance_raw": balance_raw,
        "allowance_raw": allowance_raw,
    }


async def get_market_info(api: PolymarketAPI, token_id: str) -> dict:
    """Get current orderbook for a token."""
    try:
        orderbook = await api.get_orderbook(token_id)
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])

        # API returns bids/asks in arbitrary order - use max/min to find best prices
        best_bid = max(float(b["price"]) for b in bids) if bids else 0
        best_ask = min(float(a["price"]) for a in asks) if asks else 1

        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": best_ask - best_bid,
            "mid": (best_bid + best_ask) / 2,
            "bid_depth": len(bids),
            "ask_depth": len(asks),
        }
    except Exception as e:
        return {"error": str(e)}


async def place_bet(
    side: str,
    amount: float,
    price: float | None = None,
    dry_run: bool = False,
) -> int:
    """Place a bet on the current BTC 15m market.

    Args:
        side: "up" or "down"
        amount: Amount in USD to bet
        price: Limit price (None = use best ask for BUY)
        dry_run: If True, don't actually place the order

    Returns:
        0 on success, 1 on error
    """
    print("=" * 60)
    print("BTC 15M BET")
    print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    # Load config
    print("\n[1] Loading configuration...")
    config = None
    try:
        config = PolymarketConfig.load()
        print(f"    Wallet: {config.wallet_address}")

        if not config.has_trading_credentials:
            if not dry_run:
                print("    [ERROR] No trading credentials configured")
                print("    Set POLYMARKET_PRIVATE_KEY environment variable")
                return 1
            print("    [WARN] No trading credentials (dry-run only)")
        else:
            print("    [OK] Trading credentials available")
    except Exception as e:
        if not dry_run:
            print(f"    [ERROR] Failed to load config: {e}")
            return 1
        # For dry-run, create a dummy config
        print(f"    [WARN] No config found (dry-run mode)")
        config = PolymarketConfig(wallet_address="0x" + "0" * 40)

    # Check USDC balance and allowance
    print("\n[2] Checking USDC balance and allowance...")
    try:
        wallet_info = get_usdc_balance_and_allowance(config.wallet_address)
        print(f"    USDC Balance:   ${wallet_info['balance']:.2f}")
        print(f"    USDC Allowance: ${wallet_info['allowance']:.2f}")
        print(f"    Exchange: {EXCHANGE_ADDRESS}")

        if wallet_info["balance"] < amount:
            print(f"    [WARN] Insufficient balance for ${amount:.2f} bet")
        if wallet_info["allowance"] < amount:
            print(f"    [WARN] Insufficient allowance for ${amount:.2f} bet")
            print(f"    You need to approve USDC spending on Polymarket first")
    except Exception as e:
        print(f"    [WARN] Could not check balance: {e}")

    # Fetch current market
    print("\n[3] Fetching current BTC 15m market...")
    try:
        prediction = await fetch_current_prediction(Asset.BTC, MarketHorizon.M15)
        print(f"    Market: {prediction.slug}")
        print(f"    Current UP probability: {prediction.up_probability:.1f}%")

        # time_remaining is in seconds
        if prediction.time_remaining is not None:
            remaining_sec = prediction.time_remaining
            print(f"    Time remaining: {remaining_sec:.0f}s")
            if remaining_sec < 30:
                print("    [WARN] Less than 30 seconds remaining!")
    except Exception as e:
        print(f"    [ERROR] Failed to fetch market: {e}")
        return 1

    # Determine token based on side
    side_lower = side.lower()
    if side_lower in ("up", "yes"):
        token_id = prediction.up_token_id
        outcome = "UP"
    elif side_lower in ("down", "no"):
        token_id = prediction.down_token_id
        outcome = "DOWN"
    else:
        print(f"    [ERROR] Invalid side: {side}. Use 'up' or 'down'")
        return 1

    print(f"\n[4] Betting on {outcome}...")
    print(f"    Token ID: {token_id[:30]}...")

    # Get orderbook (use a simple HTTP request for dry-run without credentials)
    print("\n[5] Fetching orderbook...")

    if dry_run and not config.has_trading_credentials:
        # Fetch orderbook directly without full API client
        import requests
        url = f"https://clob.polymarket.com/book?token_id={token_id}"
        resp = requests.get(url)
        if resp.status_code == 200:
            orderbook = resp.json()
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            # API returns bids/asks in arbitrary order - use max/min to find best prices
            best_bid = max(float(b["price"]) for b in bids) if bids else 0
            best_ask = min(float(a["price"]) for a in asks) if asks else 1
            market_info = {
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread": best_ask - best_bid,
                "bid_depth": len(bids),
                "ask_depth": len(asks),
            }
        else:
            print(f"    [ERROR] Failed to fetch orderbook: {resp.status_code}")
            return 1
        api = None
    else:
        api = PolymarketAPI(config)
        market_info = await get_market_info(api, token_id)

        if "error" in market_info:
            print(f"    [ERROR] {market_info['error']}")
            await api.close()
            return 1

    print(f"    Best bid: {market_info['best_bid']:.4f}")
    print(f"    Best ask: {market_info['best_ask']:.4f}")
    print(f"    Spread: {market_info['spread']:.4f}")
    print(f"    Depth: {market_info['bid_depth']} bids, {market_info['ask_depth']} asks")

    # Determine order price
    if price is not None:
        order_price = price
        print(f"\n[6] Using specified price: {order_price:.4f}")
    else:
        # For BUY, use best ask (take liquidity)
        order_price = market_info["best_ask"]
        print(f"\n[6] Using market price (best ask): {order_price:.4f}")

    if order_price <= 0 or order_price >= 1:
        print(f"    [ERROR] Invalid price: {order_price}")
        return 1

    # Calculate size (shares = amount / price)
    size = amount / order_price
    cost = size * order_price

    print(f"\n[7] Order details:")
    print(f"    Side: BUY {outcome}")
    print(f"    Price: {order_price:.4f}")
    print(f"    Size: {size:.2f} shares")
    print(f"    Cost: ${cost:.2f} USDC")
    print(f"    Potential payout: ${size:.2f} (if {outcome} wins)")
    print(f"    Potential profit: ${size - cost:.2f} ({(size - cost) / cost * 100:.1f}%)")

    if dry_run:
        print("\n[8] DRY RUN - Order not placed")
        print("    Remove --dry-run flag to place real order")
        if api:
            await api.close()
        return 0

    # Place order
    print("\n[8] Placing order...")
    try:
        result = await api.place_order(
            token_id=token_id,
            side=OrderSide.BUY,
            price=order_price,
            size=size,
        )

        if result.success:
            print(f"    [OK] Order placed!")
            print(f"    Order ID: {result.order_id}")
            print(f"    Submission time: {result.submission_time_ms:.0f}ms")

            # Check order status
            print("\n[9] Checking order status...")
            try:
                order_info = await api.get_order(result.order_id)
                print(f"    Status: {order_info.status}")
                print(f"    Filled: {order_info.size_matched} / {order_info.original_size}")
            except Exception as e:
                print(f"    [WARN] Could not get status: {e}")

            await api.close()
            return 0
        else:
            print(f"    [ERROR] Order failed: {result.error_message}")
            await api.close()
            return 1

    except Exception as e:
        print(f"    [ERROR] Order placement failed: {e}")
        if api:
            await api.close()
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Bet on BTC 15-minute prediction market",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Bet $10 on UP
    python scripts/bet_btc_15m.py --side up --amount 10

    # Bet $5 on DOWN with specific price
    python scripts/bet_btc_15m.py --side down --amount 5 --price 0.45

    # Dry run (preview without placing)
    python scripts/bet_btc_15m.py --side up --amount 10 --dry-run
        """,
    )

    parser.add_argument(
        "--side", "-s",
        required=True,
        choices=["up", "down", "UP", "DOWN"],
        help="Side to bet on: 'up' or 'down'",
    )

    parser.add_argument(
        "--amount", "-a",
        type=float,
        required=True,
        help="Amount in USD to bet",
    )

    parser.add_argument(
        "--price", "-p",
        type=float,
        default=None,
        help="Limit price (default: use best ask)",
    )

    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Preview order without placing it",
    )

    args = parser.parse_args()

    # Validate amount
    if args.amount <= 0:
        print("Error: Amount must be positive")
        return 1

    if args.amount < 1:
        print("Warning: Minimum practical bet is ~$1 due to fees")

    # Validate price if specified
    if args.price is not None:
        if args.price <= 0 or args.price >= 1:
            print("Error: Price must be between 0 and 1 (exclusive)")
            return 1

    return asyncio.run(place_bet(
        side=args.side,
        amount=args.amount,
        price=args.price,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    sys.exit(main())
