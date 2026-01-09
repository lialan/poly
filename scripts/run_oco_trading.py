#!/usr/bin/env python3
"""
Extreme Threshold Trading Strategy (Continuous Loop)
=====================================================

Monitors BTC/ETH prediction markets via WebSocket and places a bet when
the probability reaches an extreme threshold (default 80%).

Strategy:
1. Connect to Polymarket WebSocket for real-time price updates
2. Monitor until UP >= threshold-0.01 OR DOWN >= threshold-0.01
3. Place a single BUY order on the triggered side
4. Wait for market to resolve and report result
5. Automatically restart for the next epoch

This is a "momentum" strategy - betting that when the market shows strong
conviction (80%+), it will likely be correct.

The script runs continuously until:
- Insufficient USDC balance for the next bet
- Insufficient USDC allowance for the exchange
- Manual interruption (Ctrl+C)

Usage:
    python scripts/run_oco_trading.py                  # Interactive mode
    python scripts/run_oco_trading.py --bet 5          # $5 bet, continuous mode
    python scripts/run_oco_trading.py --bet 10 --threshold 0.7  # $10 at 70%
    python scripts/run_oco_trading.py --asset eth      # Trade ETH instead
    python scripts/run_oco_trading.py -n               # Dry run (no real orders)
    python scripts/run_oco_trading.py --once           # Single epoch only

Requirements:
    - POLYMARKET_WALLET_ADDRESS and POLYMARKET_PRIVATE_KEY must be set
    - USDC balance and allowance sufficient for bet size
"""

import argparse
import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from web3 import Web3

from poly import (
    PolymarketAPI,
    PolymarketConfig,
    OrderSide,
    Asset,
    MarketHorizon,
    get_slot_timestamp,
)

# Polygon contract addresses for balance/allowance checks
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
POLYGON_RPC_URLS = [
    "https://polygon-rpc.com",
    "https://rpc-mainnet.matic.network",
]

# ERC20 ABI (minimal for balance/allowance checks)
ERC20_ABI = [
    {
        "name": "allowance",
        "type": "function",
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "balanceOf",
        "type": "function",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extreme threshold trading - bet when market shows conviction"
    )
    parser.add_argument(
        "--bet",
        type=float,
        default=5.0,
        help="Bet amount in USD (default: 5.0, min ~$4 for 5 shares)",
    )
    parser.add_argument(
        "--asset",
        choices=["btc", "eth"],
        default="btc",
        help="Asset to trade (default: btc)",
    )
    parser.add_argument(
        "--horizon",
        choices=["15m", "1h", "4h", "d1"],
        default="15m",
        help="Market horizon (default: 15m)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.8,
        help="Trigger threshold 0.5-0.95 (default: 0.8 = 80%%)",
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Simulate without placing real orders",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Exit after placing order (don't wait for market resolution)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run for single epoch only (don't loop)",
    )
    return parser.parse_args()


def check_balance_and_allowance(wallet_address: str, required_amount: float) -> tuple[bool, str]:
    """Check USDC balance and allowance for trading.

    Args:
        wallet_address: Wallet address to check
        required_amount: Required USDC amount for the bet

    Returns:
        Tuple of (ok, message). ok=True if sufficient funds/allowance.
    """
    for rpc_url in POLYGON_RPC_URLS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 10}))
            if not w3.is_connected():
                continue

            usdc = w3.eth.contract(
                address=Web3.to_checksum_address(USDC_ADDRESS),
                abi=ERC20_ABI
            )
            wallet = Web3.to_checksum_address(wallet_address)
            exchange = Web3.to_checksum_address(EXCHANGE_ADDRESS)

            # Get balance and allowance
            balance_raw = usdc.functions.balanceOf(wallet).call()
            allowance_raw = usdc.functions.allowance(wallet, exchange).call()

            # Convert from 6 decimals
            balance = balance_raw / 1e6
            allowance = allowance_raw / 1e6

            # Check balance
            if balance < required_amount:
                return False, f"Insufficient USDC balance: ${balance:.2f} < ${required_amount:.2f}"

            # Check allowance (unless unlimited)
            if allowance_raw < 2**255 and allowance < required_amount:
                return False, f"Insufficient allowance: ${allowance:.2f} < ${required_amount:.2f}"

            return True, f"Balance: ${balance:.2f}, Allowance: {'unlimited' if allowance_raw >= 2**255 else f'${allowance:.2f}'}"

        except Exception as e:
            continue

    return False, "Failed to connect to Polygon RPC"


def horizon_from_str(s: str) -> MarketHorizon:
    """Convert string to MarketHorizon enum."""
    mapping = {
        "15m": MarketHorizon.M15,
        "1h": MarketHorizon.H1,
        "4h": MarketHorizon.H4,
        "d1": MarketHorizon.D1,
    }
    return mapping[s]


async def monitor_and_trade(
    api: PolymarketAPI,
    asset: Asset,
    horizon: MarketHorizon,
    threshold: float,
    size: float,
    dry_run: bool = False,
    wait_for_resolution: bool = True,
) -> dict:
    """Monitor prices via WebSocket and place order when threshold is reached.

    Uses real-time WebSocket feed for low-latency price monitoring.

    Args:
        api: Polymarket API client
        asset: Asset to trade (BTC/ETH)
        horizon: Market horizon (15m/1h/4h/d1)
        threshold: Trigger threshold (0.5-0.95)
        size: Order size in shares
        dry_run: If True, don't place real orders
        wait_for_resolution: If True, wait for market to resolve after order

    Returns:
        dict with winner, order_id, market_slug, resolution, etc.
    """
    from decimal import Decimal
    from poly.markets import fetch_current_prediction, slug_to_timestamp
    from poly.market_feed import MarketFeed

    # First fetch market info to get token IDs
    print("\n[1] Fetching market info...")
    market = await fetch_current_prediction(asset, horizon)
    if not market:
        return {"success": False, "error": "Failed to fetch market"}

    print(f"    Market: {market.slug}")
    up_hex = f"0x{int(market.up_token_id):064x}"
    down_hex = f"0x{int(market.down_token_id):064x}"
    print(f"    UP token:   {up_hex[:18]}...")
    print(f"    DOWN token: {down_hex[:18]}...")

    # Calculate resolution time
    try:
        resolution_ts = slug_to_timestamp(market.slug)
        resolution_time = datetime.fromtimestamp(resolution_ts, tz=timezone.utc)
        time_remaining = (resolution_time - datetime.now(timezone.utc)).total_seconds()
        print(f"    Resolves at: {resolution_time.strftime('%H:%M:%S UTC')} ({time_remaining:.0f}s remaining)")
    except:
        resolution_time = None
        time_remaining = None

    # Result container
    result: dict = {"market_slug": market.slug, "success": False}
    threshold_decimal = Decimal(str(threshold))
    start_time = asyncio.get_event_loop().time()

    # Create an event to signal when threshold is reached
    triggered = asyncio.Event()

    def on_update(update):
        """Callback for price updates."""
        if triggered.is_set():
            return

        state = feed.get_market(market.slug)
        if not state:
            return

        up_price = state.yes_mid
        down_price = state.no_mid

        if not up_price or not down_price:
            return

        elapsed = asyncio.get_event_loop().time() - start_time
        print(f"  [{elapsed:6.1f}s] UP: {float(up_price):.3f} | DOWN: {float(down_price):.3f}", end="\r")

        # Trigger at threshold - 0.01 (e.g., 0.79 for 0.8 threshold)
        trigger_level = threshold_decimal - Decimal("0.01")
        if up_price >= trigger_level:
            result.update({
                "triggered_side": "UP",
                "token_id": market.up_token_id,
                "trigger_price": float(up_price),
            })
            triggered.set()
        elif down_price >= trigger_level:
            result.update({
                "triggered_side": "DOWN",
                "token_id": market.down_token_id,
                "trigger_price": float(down_price),
            })
            triggered.set()

    def on_connect():
        print("    [WS] Connected")

    def on_disconnect():
        if not triggered.is_set():
            print("\n    [WS] Reconnecting...")

    # Create and configure feed
    feed = MarketFeed(on_update=on_update, on_connect=on_connect, on_disconnect=on_disconnect)
    await feed.add_market(market.slug, market.up_token_id, market.down_token_id)

    print(f"\n[2] Monitoring prices (WebSocket)...")
    trigger_at = threshold - 0.01
    print(f"    Waiting for UP >= {trigger_at:.2f} or DOWN >= {trigger_at:.2f}")
    print("    Press Ctrl+C to cancel\n")

    feed_task = asyncio.create_task(feed.start())

    try:
        # Wait for trigger
        await triggered.wait()
        side = result["triggered_side"]
        price = result["trigger_price"]

        print(f"\n\n[TRIGGER] {side} reached {price:.3f} >= {threshold}!")

        if dry_run:
            print(f"    [DRY RUN] Would place BUY {side} order")
            result["order_id"] = "dry_run"
            result["success"] = True
        else:
            # Place order at slightly above current price to ensure fill
            order_price = min(price + 0.01, 0.99)
            print(f"\n[3] Placing BUY {side} order at {order_price:.3f}...")

            order_result = await api.place_order(
                token_id=result["token_id"],
                side=OrderSide.BUY,
                price=order_price,
                size=size,
            )

            if order_result.success:
                print(f"    [OK] Order placed: {order_result.order_id[:20]}...")
                result["order_id"] = order_result.order_id
                result["order_price"] = order_price
                result["success"] = True

                # Check if order was filled
                await asyncio.sleep(1.0)
                try:
                    order_info = await api.get_order(order_result.order_id)
                    if order_info:
                        result["size_matched"] = order_info.size_matched
                        result["size_total"] = order_info.original_size
                        print(f"    Filled: {order_info.size_matched}/{order_info.original_size} shares")
                    else:
                        print(f"    [INFO] Could not fetch order status (order may still be processing)")
                except Exception as e:
                    print(f"    [INFO] Could not fetch order status: {e}")
            else:
                print(f"    [ERROR] Order failed: {order_result.error_message}")
                result["error"] = order_result.error_message

    except (asyncio.CancelledError, KeyboardInterrupt):
        print("\n\n[CANCELLED] Monitoring stopped")
        result["cancelled"] = True
    finally:
        await feed.stop()
        feed_task.cancel()
        try:
            await feed_task
        except asyncio.CancelledError:
            pass

    # Wait for market resolution if requested
    if result.get("success") and wait_for_resolution and not dry_run and resolution_time:
        print(f"\n[4] Waiting for market resolution...")
        now = datetime.now(timezone.utc)
        wait_seconds = (resolution_time - now).total_seconds()

        if wait_seconds > 0:
            print(f"    Resolution in {wait_seconds:.0f} seconds...")
            try:
                # Wait with periodic status updates
                while wait_seconds > 0:
                    wait_chunk = min(wait_seconds, 30)
                    await asyncio.sleep(wait_chunk)
                    wait_seconds -= wait_chunk
                    if wait_seconds > 0:
                        print(f"    {wait_seconds:.0f}s remaining...")

                # Give extra time for resolution to propagate
                print("    Waiting for resolution to finalize...")
                await asyncio.sleep(10)

                # Check final result
                print(f"\n[5] Checking resolution...")
                market_info = await api.get_market_info(market.slug)
                if market_info:
                    result["market_status"] = market_info.status.value
                    result["resolution"] = market_info.outcome
                    print(f"    Market status: {market_info.status.value}")
                    print(f"    Outcome: {market_info.outcome}")

                    # Check if we won
                    if market_info.outcome:
                        our_side = result["triggered_side"]
                        won = (our_side == "UP" and "up" in market_info.outcome.lower()) or \
                              (our_side == "DOWN" and "down" in market_info.outcome.lower())
                        result["won"] = won
                        print(f"    Result: {'WON' if won else 'LOST'}")
                else:
                    print("    Could not fetch market info")

            except (asyncio.CancelledError, KeyboardInterrupt):
                print("\n    [CANCELLED] Stopped waiting for resolution")

    return result


def interactive_config() -> dict:
    """Interactive configuration when run without arguments."""
    print("\n" + "=" * 50)
    print("EXTREME THRESHOLD TRADING - SETUP")
    print("=" * 50)
    print("\nThis strategy monitors prices and places a bet when")
    print("the market shows strong conviction (reaches threshold).")

    # Bet amount
    while True:
        bet_str = input("\nBet amount in USD [5]: ").strip() or "5"
        try:
            bet = float(bet_str)
            if bet < 4:
                print("Minimum bet is ~$4 (5 shares minimum)")
                continue
            break
        except ValueError:
            print("Enter a valid number")

    # Asset
    asset_str = input("Asset (btc/eth) [btc]: ").strip().lower() or "btc"
    if asset_str not in ("btc", "eth"):
        asset_str = "btc"

    # Threshold
    while True:
        thresh_str = input("Threshold % (50-95) [80]: ").strip() or "80"
        try:
            threshold_pct = float(thresh_str)
            if not 50 <= threshold_pct <= 95:
                print("Threshold must be between 50 and 95")
                continue
            threshold = threshold_pct / 100.0
            break
        except ValueError:
            print("Enter a valid number")

    # Dry run?
    dry_run = input("Dry run (no real orders)? (y/N): ").strip().lower() == "y"

    return {
        "bet": bet,
        "asset": asset_str,
        "threshold": threshold,
        "dry_run": dry_run,
    }


async def run_single_epoch(
    api: PolymarketAPI,
    asset: Asset,
    horizon: MarketHorizon,
    threshold: float,
    size: float,
    dry_run: bool,
    wait_for_resolution: bool,
) -> dict:
    """Run the strategy for a single epoch.

    Returns:
        dict with result including 'success', 'won', 'cancelled', 'error' keys.
    """
    result = await monitor_and_trade(
        api=api,
        asset=asset,
        horizon=horizon,
        threshold=threshold,
        size=size,
        dry_run=dry_run,
        wait_for_resolution=wait_for_resolution,
    )

    # Print epoch summary
    print("\n" + "=" * 60)
    print("EPOCH RESULT")
    print("=" * 60)

    if result.get("success"):
        print(f"\n  Side:       {result.get('triggered_side', 'N/A')}")
        print(f"  Market:     {result.get('market_slug', 'N/A')}")
        print(f"  Trigger:    {result.get('trigger_price', 0):.3f}")
        order_id = result.get('order_id', 'N/A')
        print(f"  Order ID:   {order_id[:20] if order_id and order_id != 'dry_run' else order_id}...")
        if result.get("size_matched"):
            print(f"  Filled:     {result['size_matched']}/{result['size_total']} shares")
        if result.get("won") is not None:
            print(f"\n  OUTCOME:    {'WON!' if result['won'] else 'LOST'}")
    elif result.get("cancelled"):
        print("\n  Cancelled by user")
    else:
        print(f"\n  Error: {result.get('error', 'Unknown error')}")

    return result


async def main() -> int:
    args = parse_args()

    # Interactive mode if run without arguments (check if all defaults)
    if args.bet == 5.0 and args.threshold == 0.8 and not args.dry_run:
        # Looks like defaults - offer interactive config
        try:
            response = input("\nRun with defaults ($5, 80% threshold)? (Y/n): ").strip().lower()
            if response == "n":
                config = interactive_config()
                if config is None:
                    print("Cancelled.")
                    return 0
                args.bet = config["bet"]
                args.asset = config["asset"]
                args.threshold = config["threshold"]
                args.dry_run = config["dry_run"]
        except (EOFError, KeyboardInterrupt):
            # Non-interactive mode, use defaults
            pass

    # Calculate size from bet amount
    size = args.bet / args.threshold

    asset = Asset.BTC if args.asset == "btc" else Asset.ETH
    horizon = horizon_from_str(args.horizon)
    loop_mode = not args.once

    print("\n" + "=" * 60)
    print("EXTREME THRESHOLD TRADING" + (" (CONTINUOUS)" if loop_mode else " (SINGLE EPOCH)"))
    print("=" * 60)
    print(f"\nConfiguration:")
    print(f"  Asset:      {asset.value}")
    print(f"  Horizon:    {horizon.name}")
    print(f"  Threshold:  {args.threshold:.0%} (triggers at {args.threshold - 0.01:.0%})")
    print(f"  Bet amount: ${args.bet:.2f}")
    print(f"  Size:       {size:.2f} shares")
    print(f"  Dry run:    {args.dry_run}")
    print(f"  Wait:       {'Yes' if not args.no_wait else 'No'}")
    print(f"  Mode:       {'Continuous loop' if loop_mode else 'Single epoch'}")

    # Load credentials (unless dry run)
    poly_config = None
    api = None
    if not args.dry_run:
        try:
            poly_config = PolymarketConfig.load()
            print(f"\n  Wallet:     {poly_config.wallet_address}")
            if not poly_config.has_trading_credentials:
                print("\n[ERROR] No trading credentials configured")
                print("Set POLYMARKET_PRIVATE_KEY environment variable")
                return 1
        except Exception as e:
            print(f"\n[ERROR] Failed to load config: {e}")
            return 1

    epoch_count = 0
    wins = 0
    losses = 0

    try:
        while True:
            epoch_count += 1

            print("\n" + "=" * 60)
            print(f"EPOCH {epoch_count}")
            print("=" * 60)

            # Check balance and allowance before each epoch (unless dry run)
            if not args.dry_run and poly_config:
                print("\n[0] Checking balance and allowance...")
                ok, msg = check_balance_and_allowance(poly_config.wallet_address, args.bet)
                print(f"    {msg}")
                if not ok:
                    print("\n[EXIT] Insufficient funds or allowance. Stopping.")
                    break

            # Create fresh API connection for each epoch
            if not args.dry_run and poly_config:
                api = PolymarketAPI(poly_config)

            try:
                result = await run_single_epoch(
                    api=api,
                    asset=asset,
                    horizon=horizon,
                    threshold=args.threshold,
                    size=size,
                    dry_run=args.dry_run,
                    wait_for_resolution=not args.no_wait,
                )

                # Track results
                if result.get("won") is True:
                    wins += 1
                elif result.get("won") is False:
                    losses += 1

                # Check for cancellation
                if result.get("cancelled"):
                    print("\n[EXIT] User cancelled. Stopping.")
                    break

            finally:
                if api:
                    await api.close()
                    api = None

            # Exit if single epoch mode
            if not loop_mode:
                break

            # Wait for next epoch
            next_epoch_ts = get_slot_timestamp(horizon, 1)
            now_ts = int(time.time())
            wait_seconds = next_epoch_ts - now_ts

            if wait_seconds > 0:
                next_time = datetime.fromtimestamp(next_epoch_ts, tz=timezone.utc)
                print(f"\n[NEXT EPOCH] Waiting {wait_seconds}s until {next_time.strftime('%H:%M:%S UTC')}...")
                print(f"             Stats: {wins}W / {losses}L / {epoch_count} epochs")

                try:
                    # Sleep in chunks to allow Ctrl+C to work
                    while wait_seconds > 0:
                        sleep_chunk = min(wait_seconds, 30)
                        await asyncio.sleep(sleep_chunk)
                        wait_seconds -= sleep_chunk
                        if wait_seconds > 0:
                            print(f"             {wait_seconds}s remaining...", end="\r")
                except (asyncio.CancelledError, KeyboardInterrupt):
                    print("\n[EXIT] User interrupted during wait. Stopping.")
                    break

    except KeyboardInterrupt:
        print("\n\n[EXIT] User interrupted. Stopping.")

    # Final summary
    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    print(f"\n  Epochs:     {epoch_count}")
    print(f"  Wins:       {wins}")
    print(f"  Losses:     {losses}")
    if wins + losses > 0:
        win_rate = wins / (wins + losses) * 100
        print(f"  Win rate:   {win_rate:.1f}%")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
