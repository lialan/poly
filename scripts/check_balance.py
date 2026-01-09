#!/usr/bin/env python3
"""
Check wallet balances, positions, orders, and trade history for Polymarket.

Shows:
- MATIC (for gas), USDC.e (for trading), native USDC balances
- USDC.e allowance for Polymarket exchange
- Current positions
- Open orders
- Recent trade history

Usage:
    python scripts/check_balance.py

    # Check specific wallet
    python scripts/check_balance.py --wallet 0x...

    # Show more trades
    python scripts/check_balance.py --trades 20
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, "src")

import requests

from poly import PolymarketConfig, PolymarketAPI

# Contract addresses (Polygon mainnet)
USDC_E_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # Bridged USDC (Polymarket uses this)
USDC_NATIVE_ADDRESS = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"  # Native USDC
EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"  # Polymarket CTF Exchange

POLYGON_RPC = "https://polygon-rpc.com"


def eth_call(to: str, data: str) -> str:
    """Make an eth_call to Polygon RPC."""
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


def get_matic_balance(wallet: str) -> float:
    """Get native MATIC balance."""
    resp = requests.post(POLYGON_RPC, json={
        "jsonrpc": "2.0",
        "method": "eth_getBalance",
        "params": [wallet, "latest"],
        "id": 1,
    })
    result = resp.json()
    if "error" in result:
        raise Exception(result["error"]["message"])
    return int(result["result"], 16) / 1e18


def get_erc20_balance(token: str, wallet: str, decimals: int = 6) -> float:
    """Get ERC20 token balance."""
    wallet_padded = wallet.lower().replace("0x", "").zfill(64)
    data = f"0x70a08231{wallet_padded}"
    result = eth_call(token, data)
    return int(result, 16) / (10 ** decimals)


def get_erc20_allowance(token: str, wallet: str, spender: str, decimals: int = 6) -> float:
    """Get ERC20 allowance."""
    wallet_padded = wallet.lower().replace("0x", "").zfill(64)
    spender_padded = spender.lower().replace("0x", "").zfill(64)
    data = f"0xdd62ed3e{wallet_padded}{spender_padded}"
    result = eth_call(token, data)
    raw = int(result, 16)
    # Check for unlimited approval
    if raw >= 2**255:
        return float("inf")
    return raw / (10 ** decimals)


def format_amount(amount: float, symbol: str = "$") -> str:
    """Format amount for display."""
    if amount == float("inf"):
        return "unlimited"
    if symbol == "$":
        return f"${amount:,.2f}"
    return f"{amount:,.4f} {symbol}"


def format_time_ago(dt: datetime) -> str:
    """Format datetime as time ago string."""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt

    if diff.days > 0:
        return f"{diff.days}d ago"
    hours = diff.seconds // 3600
    if hours > 0:
        return f"{hours}h ago"
    minutes = diff.seconds // 60
    if minutes > 0:
        return f"{minutes}m ago"
    return "just now"


async def fetch_positions_and_trades(config: PolymarketConfig, num_trades: int):
    """Fetch positions, open orders, and trade history."""
    positions = []
    open_orders = []
    trades = []

    async with PolymarketAPI(config) as api:
        # Fetch positions
        try:
            positions = await api.get_positions(limit=20)
        except Exception as e:
            print(f"  [WARN] Could not fetch positions: {e}")

        # Fetch trades
        try:
            trades = await api.get_trades(limit=num_trades)
        except Exception as e:
            print(f"  [WARN] Could not fetch trades: {e}")

    # Fetch open orders (requires py-clob-client with auth)
    if config.has_trading_credentials:
        try:
            from poly import LocalSigner
            signer = LocalSigner(
                private_key=config.private_key,
                chain_id=config.chain_id,
            )
            client = signer._get_clob_client()
            open_orders = client.get_orders()
        except Exception as e:
            # This is expected if no orders exist
            if "not found" not in str(e).lower():
                pass  # Silently ignore - user may not have any orders

    return positions, open_orders, trades


def main():
    parser = argparse.ArgumentParser(
        description="Check wallet balances, positions, and trade history for Polymarket",
    )
    parser.add_argument(
        "--wallet", "-w",
        type=str,
        default=None,
        help="Wallet address to check (default: from config)",
    )
    parser.add_argument(
        "--trades", "-t",
        type=int,
        default=10,
        help="Number of recent trades to show (default: 10)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("POLYMARKET WALLET STATUS")
    print("=" * 60)

    # Get wallet address and config
    config = None
    if args.wallet:
        wallet = args.wallet
        print(f"\nWallet: {wallet}")
        config = PolymarketConfig(wallet_address=wallet)
    else:
        try:
            config = PolymarketConfig.load()
            wallet = config.wallet_address
            print(f"\nWallet: {wallet}")
            if config.has_trading_credentials:
                print("Trading: Enabled (private key configured)")
            else:
                print("Trading: Disabled (no private key)")
        except Exception as e:
            print(f"\n[ERROR] No wallet configured: {e}")
            print("Use --wallet flag or set POLYMARKET_WALLET_ADDRESS")
            return 1

    print("\n" + "-" * 60)
    print("BALANCES")
    print("-" * 60)

    try:
        # MATIC balance
        matic = get_matic_balance(wallet)
        matic_status = "✓" if matic >= 0.01 else "✗ Need MATIC for gas"
        print(f"MATIC (gas):     {format_amount(matic, 'MATIC'):>20}  {matic_status}")

        # USDC.e balance (what Polymarket uses)
        usdc_e = get_erc20_balance(USDC_E_ADDRESS, wallet)
        print(f"USDC.e (trade):  {format_amount(usdc_e):>20}  ← Polymarket uses this")

        # Native USDC balance
        usdc_native = get_erc20_balance(USDC_NATIVE_ADDRESS, wallet)
        if usdc_native > 0:
            print(f"USDC (native):   {format_amount(usdc_native):>20}  ⚠ Swap to USDC.e to use")
        else:
            print(f"USDC (native):   {format_amount(usdc_native):>20}")

    except Exception as e:
        print(f"[ERROR] Failed to fetch balances: {e}")
        return 1

    print("\n" + "-" * 60)
    print("ALLOWANCES (Polymarket Exchange)")
    print("-" * 60)

    try:
        # USDC.e allowance
        allowance = get_erc20_allowance(USDC_E_ADDRESS, wallet, EXCHANGE_ADDRESS)
        if allowance == float("inf"):
            allowance_str = "unlimited"
            allowance_status = "✓"
        elif allowance > 0:
            allowance_str = format_amount(allowance)
            allowance_status = "✓" if allowance >= usdc_e else "⚠ May need to increase"
        else:
            allowance_str = "$0.00"
            allowance_status = "✗ Run approve_usdc.py"
        print(f"USDC.e:          {allowance_str:>20}  {allowance_status}")

    except Exception as e:
        print(f"[ERROR] Failed to fetch allowance: {e}")
        return 1

    # Fetch positions, orders, and trades
    print("\n" + "-" * 60)
    print("POSITIONS & ORDERS")
    print("-" * 60)

    positions, open_orders, trades = asyncio.run(
        fetch_positions_and_trades(config, args.trades)
    )

    # Display positions
    if positions:
        print(f"\nOpen Positions ({len(positions)}):")
        for pos in positions[:10]:  # Show max 10
            side = "YES" if pos.outcome == "Yes" else "NO"
            pnl = pos.cash_pnl
            pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
            slug = pos.slug[:40] if pos.slug else pos.condition_id[:40]
            print(f"  {slug:<40}")
            print(f"    {side}: {pos.size:.2f} shares @ ${pos.avg_price:.2f} | PnL: {pnl_str}")
    else:
        print("\nNo open positions")

    # Display open orders
    if open_orders:
        print(f"\nOpen Orders ({len(open_orders)}):")
        for order in open_orders[:10]:  # Show max 10
            side = order.get("side", "?")
            price = float(order.get("price", 0))
            size = float(order.get("original_size", 0))
            filled = float(order.get("size_matched", 0))
            token_id = order.get("asset_id", "")[:20]
            print(f"  {side} {size:.2f} @ {price:.2f} (filled: {filled:.2f}) | {token_id}...")
    else:
        print("\nNo open orders")

    # Display trade history
    print("\n" + "-" * 60)
    print(f"RECENT TRADES (last {args.trades})")
    print("-" * 60)

    if trades:
        for trade in trades:
            side = trade.side if hasattr(trade, 'side') else "?"
            price = trade.price if hasattr(trade, 'price') else 0
            size = trade.size if hasattr(trade, 'size') else 0
            status = trade.status.value if hasattr(trade, 'status') else "?"

            # Get time
            time_str = ""
            if hasattr(trade, 'timestamp') and trade.timestamp:
                time_str = format_time_ago(trade.timestamp)

            # Get market info
            market = ""
            if hasattr(trade, 'market_slug') and trade.market_slug:
                market = trade.market_slug[:35]
            elif hasattr(trade, 'asset_id') and trade.asset_id:
                market = trade.asset_id[:35]

            print(f"  {side:4} {size:>8.2f} @ {price:.2f} | {status:9} | {time_str:>8} | {market}")
    else:
        print("No recent trades")

    # Contract addresses
    print("\n" + "-" * 60)
    print("CONTRACT ADDRESSES")
    print("-" * 60)
    print(f"USDC.e:   {USDC_E_ADDRESS}")
    print(f"USDC:     {USDC_NATIVE_ADDRESS}")
    print(f"Exchange: {EXCHANGE_ADDRESS}")

    # Trading readiness check
    print("\n" + "-" * 60)
    print("TRADING READINESS")
    print("-" * 60)

    ready = True
    if matic < 0.01:
        print("✗ Need MATIC for gas fees")
        ready = False
    if usdc_e <= 0:
        print("✗ Need USDC.e balance to trade")
        if usdc_native > 0:
            print("  → Swap your native USDC to USDC.e on Uniswap/QuickSwap")
        ready = False
    if allowance <= 0:
        print("✗ Need to approve USDC.e spending")
        print("  → Run: python scripts/approve_usdc.py")
        ready = False

    if ready:
        print("✓ Ready to trade on Polymarket!")
        print(f"  Available: {format_amount(min(usdc_e, allowance if allowance != float('inf') else usdc_e))}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
