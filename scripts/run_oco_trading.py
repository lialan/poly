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

The script runs continuously until:
- Insufficient USDC balance for the next bet
- Insufficient USDC allowance for the exchange
- Manual interruption (Ctrl+C)

Usage:
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
import math
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from web3 import Web3

from poly import (
    PolymarketAPI,
    PolymarketConfig,
    OrderSide,
    Asset,
    MarketHorizon,
    get_slot_timestamp,
    slug_to_timestamp,
)
from poly.api.binance_ws import BinanceKlineStream, BTCUSDT, ETHUSDT, INTERVAL_1M


class TimeSync:
    """Synchronized time service using Binance server time as reference."""

    BINANCE_TIME_URL = "https://api.binance.com/api/v3/time"

    def __init__(self):
        self.offset_ms: int = 0  # Local time - server time (ms)
        self.last_sync: float = 0
        self.sync_count: int = 0

    def sync(self) -> bool:
        """Sync with Binance server time. Returns True if successful."""
        try:
            local_before = int(time.time() * 1000)
            resp = requests.get(self.BINANCE_TIME_URL, timeout=5)
            local_after = int(time.time() * 1000)

            if resp.status_code == 200:
                server_time = resp.json()["serverTime"]
                # Estimate local time at server response (midpoint of request)
                local_mid = (local_before + local_after) // 2
                self.offset_ms = local_mid - server_time
                self.last_sync = time.time()
                self.sync_count += 1
                return True
        except Exception:
            pass
        return False

    def now_ms(self) -> int:
        """Get current synchronized time in milliseconds."""
        return int(time.time() * 1000) - self.offset_ms

    def now(self) -> float:
        """Get current synchronized time in seconds."""
        return self.now_ms() / 1000

    def now_dt(self) -> datetime:
        """Get current synchronized time as datetime."""
        return datetime.fromtimestamp(self.now(), tz=timezone.utc)

    @property
    def offset_sec(self) -> float:
        """Get offset in seconds (positive = local ahead of server)."""
        return self.offset_ms / 1000

    def format_status(self) -> str:
        """Format sync status for display."""
        if self.sync_count == 0:
            return "not synced"
        return f"offset={self.offset_ms:+d}ms"

# Polygon contract addresses
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
POLYGON_RPC_URLS = [
    "https://polygon-rpc.com",
    "https://rpc-mainnet.matic.network",
]

ERC20_ABI = [
    {
        "name": "allowance",
        "type": "function",
        "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "balanceOf",
        "type": "function",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]


@dataclass
class PriceState:
    """Current price state from Binance with timestamp alignment."""
    open_price: Optional[float] = None
    close_price: Optional[float] = None
    kline_start_ms: Optional[int] = None  # Kline open time (Binance server time)
    kline_close_ms: Optional[int] = None  # Kline close time (Binance server time)
    update_time_ms: Optional[int] = None  # When we received this update (synced time)

    @property
    def log_delta_pct(self) -> Optional[float]:
        """Calculate log return as percentage."""
        if self.open_price and self.close_price and self.open_price > 0:
            return (math.log(self.close_price) - math.log(self.open_price)) * 100
        return None

    @property
    def kline_age_ms(self) -> Optional[int]:
        """How old is this kline data (ms since kline started)."""
        if self.kline_start_ms and self.update_time_ms:
            return self.update_time_ms - self.kline_start_ms
        return None

    @property
    def kline_progress_pct(self) -> Optional[float]:
        """Progress through the current kline (0-100%)."""
        if self.kline_start_ms and self.kline_close_ms and self.update_time_ms:
            duration = self.kline_close_ms - self.kline_start_ms
            elapsed = self.update_time_ms - self.kline_start_ms
            if duration > 0:
                return min(100.0, max(0.0, (elapsed / duration) * 100))
        return None

    def format_display(self) -> str:
        """Format price for status line display."""
        if not self.close_price:
            return "..."
        delta = self.log_delta_pct
        if delta is not None:
            return f"${self.close_price:,.0f} ({delta:+.3f}%)"
        return f"${self.close_price:,.0f}"

    def format_time_info(self) -> str:
        """Format kline timing info for display."""
        progress = self.kline_progress_pct
        if progress is not None:
            return f"{progress:.0f}%"
        return "-"


@dataclass
class TriggerInfo:
    """Information captured at trigger time."""
    side: str
    token_id: str
    trigger_price: float
    elapsed_seconds: int
    spot_price: Optional[float]
    spot_open: Optional[float]
    log_delta_pct: Optional[float]
    up_bid: Optional[float]
    up_ask: Optional[float]
    down_bid: Optional[float]
    down_ask: Optional[float]
    kline_progress_pct: Optional[float] = None  # Progress through current 1m kline
    trigger_time_ms: Optional[int] = None  # Synchronized trigger timestamp

    def print_details(self, threshold: float):
        """Print trigger details."""
        print(f"\n\n[TRIGGER] {self.side} reached {self.trigger_price:.3f} >= {threshold - 0.01:.2f}!")
        print(f"    Epoch time:  {self.elapsed_seconds}s")

        if self.spot_price and self.log_delta_pct is not None:
            kline_str = f", kline: {self.kline_progress_pct:.0f}%" if self.kline_progress_pct else ""
            print(f"    Spot price:  ${self.spot_price:,.2f} (open: ${self.spot_open:,.2f}, delta: {self.log_delta_pct:+.3f}%{kline_str})")
        elif self.spot_price:
            print(f"    Spot price:  ${self.spot_price:,.2f}")
        else:
            print(f"    Spot price:  -")

        if self.trigger_time_ms:
            trigger_dt = datetime.fromtimestamp(self.trigger_time_ms / 1000, tz=timezone.utc)
            print(f"    Trigger at:  {trigger_dt.strftime('%H:%M:%S.%f')[:-3]} UTC")

        up_bid_str = f"{self.up_bid:.3f}" if self.up_bid else "-"
        up_ask_str = f"{self.up_ask:.3f}" if self.up_ask else "-"
        down_bid_str = f"{self.down_bid:.3f}" if self.down_bid else "-"
        down_ask_str = f"{self.down_ask:.3f}" if self.down_ask else "-"
        print(f"    UP:   bid={up_bid_str} ask={up_ask_str}")
        print(f"    DOWN: bid={down_bid_str} ask={down_ask_str}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extreme threshold trading - bet when market shows conviction"
    )
    parser.add_argument("-b", "--bet", type=float, default=5.0,
                        help="Bet amount in USD (default: 5.0)")
    parser.add_argument("-a", "--asset", choices=["btc", "eth"], default="btc",
                        help="Asset to trade (default: btc)")
    parser.add_argument("--horizon", choices=["15m", "1h", "4h", "d1"], default="15m",
                        help="Market horizon (default: 15m)")
    parser.add_argument("-t", "--threshold", type=float, default=0.8,
                        help="Trigger threshold 0.5-0.95 (default: 0.8)")
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help="Simulate without placing real orders")
    parser.add_argument("--no-wait", action="store_true",
                        help="Exit after placing order (don't wait for resolution)")
    parser.add_argument("--once", action="store_true",
                        help="Run for single epoch only (don't loop)")
    parser.add_argument("-i", "--ignore-first-seconds", type=int, default=0, metavar="N",
                        help="Ignore triggers for first N seconds of epoch")
    parser.add_argument("--min-delta", type=float, default=0.005, metavar="PCT",
                        help="Min abs(log delta %%) to trigger (default: 0.005)")
    return parser.parse_args()


def horizon_from_str(s: str) -> MarketHorizon:
    """Convert string to MarketHorizon enum."""
    return {"15m": MarketHorizon.M15, "1h": MarketHorizon.H1,
            "4h": MarketHorizon.H4, "d1": MarketHorizon.D1}[s]


def check_balance_and_allowance(wallet_address: str, required_amount: float) -> tuple[bool, str]:
    """Check USDC balance and allowance for trading."""
    for rpc_url in POLYGON_RPC_URLS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 10}))
            if not w3.is_connected():
                continue

            usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_ADDRESS), abi=ERC20_ABI)
            wallet = Web3.to_checksum_address(wallet_address)
            exchange = Web3.to_checksum_address(EXCHANGE_ADDRESS)

            balance_raw = usdc.functions.balanceOf(wallet).call()
            allowance_raw = usdc.functions.allowance(wallet, exchange).call()
            balance, allowance = balance_raw / 1e6, allowance_raw / 1e6

            if balance < required_amount:
                return False, f"Insufficient USDC balance: ${balance:.2f} < ${required_amount:.2f}"
            if allowance_raw < 2**255 and allowance < required_amount:
                return False, f"Insufficient allowance: ${allowance:.2f} < ${required_amount:.2f}"

            allowance_str = 'unlimited' if allowance_raw >= 2**255 else f'${allowance:.2f}'
            return True, f"Balance: ${balance:.2f}, Allowance: {allowance_str}"
        except Exception:
            continue
    return False, "Failed to connect to Polygon RPC"


def print_epoch_result(result: dict):
    """Print the result of an epoch."""
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


async def place_order_and_check(api: PolymarketAPI, token_id: str, price: float,
                                 size: float, side_name: str) -> dict:
    """Place an order and check its fill status."""
    result = {"success": False}
    order_price = min(price + 0.01, 0.99)
    print(f"\n[3] Placing BUY {side_name} order at {order_price:.3f}...")

    order_result = await api.place_order(
        token_id=token_id, side=OrderSide.BUY, price=order_price, size=size
    )

    if order_result.success:
        print(f"    [OK] Order placed: {order_result.order_id[:20]}...")
        result.update({"success": True, "order_id": order_result.order_id, "order_price": order_price})

        await asyncio.sleep(1.0)
        try:
            order_info = await api.get_order(order_result.order_id)
            if order_info:
                result["size_matched"] = order_info.size_matched
                result["size_total"] = order_info.original_size
                print(f"    Filled: {order_info.size_matched}/{order_info.original_size} shares")
            else:
                print(f"    [INFO] Could not fetch order status")
        except Exception as e:
            print(f"    [INFO] Could not fetch order status: {e}")
    else:
        print(f"    [ERROR] Order failed: {order_result.error_message}")
        result["error"] = order_result.error_message

    return result


async def monitor_and_trade(
    api: PolymarketAPI,
    asset: Asset,
    horizon: MarketHorizon,
    threshold: float,
    size: float,
    dry_run: bool = False,
    wait_for_resolution_flag: bool = True,
    ignore_first_seconds: int = 0,
    min_delta_pct: float = 0.005,
    time_sync: Optional[TimeSync] = None,
) -> dict:
    """Monitor prices via WebSocket and place order when threshold is reached."""
    from poly.markets import fetch_current_prediction
    from poly.market_feed import MarketFeed

    # Fetch market info
    print("\n[1] Fetching market info...")
    market = await fetch_current_prediction(asset, horizon)
    if not market:
        return {"success": False, "error": "Failed to fetch market"}

    print(f"    Market: {market.slug}")
    print(f"    UP token:   0x{int(market.up_token_id):064x}"[:24] + "...")
    print(f"    DOWN token: 0x{int(market.down_token_id):064x}"[:24] + "...")

    # Calculate resolution time
    resolution_time = None
    try:
        resolution_ts = slug_to_timestamp(market.slug)
        resolution_time = datetime.fromtimestamp(resolution_ts, tz=timezone.utc)
        time_remaining = (resolution_time - datetime.now(timezone.utc)).total_seconds()
        print(f"    Resolves at: {resolution_time.strftime('%H:%M:%S UTC')} ({time_remaining:.0f}s remaining)")
    except Exception:
        pass

    # Initialize state
    result: dict = {"market_slug": market.slug, "success": False}
    threshold_decimal = Decimal(str(threshold))
    trigger_level = threshold_decimal - Decimal("0.01")

    # Use synchronized time if available, otherwise fall back to local time
    def get_now_ms() -> int:
        return time_sync.now_ms() if time_sync else int(time.time() * 1000)

    epoch_start_ts = slug_to_timestamp(market.slug) or int(time.time())
    epoch_start_ms = epoch_start_ts * 1000
    price_state = {"btc": PriceState(), "eth": PriceState()}
    triggered = asyncio.Event()
    order_placed = asyncio.Event()  # For post-bet monitoring
    trigger_info: Optional[TriggerInfo] = None

    def on_binance_kline(kline):
        """Update price state with kline data including timestamps."""
        key = "btc" if kline.symbol == "BTCUSDT" else "eth" if kline.symbol == "ETHUSDT" else None
        if key:
            ps = price_state[key]
            ps.open_price = float(kline.open)
            ps.close_price = float(kline.close)
            ps.kline_start_ms = kline.start_time  # Binance server time
            ps.kline_close_ms = kline.close_time  # Binance server time
            ps.update_time_ms = get_now_ms()      # Synchronized local time

    def on_update(update):
        nonlocal trigger_info
        state = feed.get_market(market.slug)
        if not state or not state.yes_mid or not state.no_mid:
            return

        up_price, down_price = state.yes_mid, state.no_mid
        now_ms = get_now_ms()
        elapsed = (now_ms - epoch_start_ms) // 1000
        ps = price_state["btc"] if asset == Asset.BTC else price_state["eth"]
        spot_str = ps.format_display()
        delta = ps.log_delta_pct
        kline_pct = ps.format_time_info()

        # Display status (continues even after order placed)
        prefix = "[POST]" if order_placed.is_set() else ""
        status = f"  {prefix}[{elapsed:4d}s|{kline_pct:>3}] {spot_str} | UP: {float(up_price):.3f} | DOWN: {float(down_price):.3f}"

        if triggered.is_set():
            # After trigger, just show status for study
            print(status + "      ", end="\r")
            return

        if elapsed < ignore_first_seconds:
            print(status + f" (ignoring until {ignore_first_seconds}s)", end="\r")
            return
        print(status, end="\r")

        # Check trigger - requires both price threshold AND delta threshold
        if up_price >= trigger_level or down_price >= trigger_level:
            # Guard: require abs(delta) > 0.005%
            if delta is None or abs(delta) < min_delta_pct:
                delta_str = f"{delta:+.3f}%" if delta is not None else "N/A"
                print(status + f" (delta {delta_str} < {min_delta_pct}%)", end="\r")
                return

            side = "UP" if up_price >= trigger_level else "DOWN"
            token_id = market.up_token_id if side == "UP" else market.down_token_id
            price = float(up_price) if side == "UP" else float(down_price)

            trigger_info = TriggerInfo(
                side=side, token_id=token_id, trigger_price=price,
                elapsed_seconds=elapsed, spot_price=ps.close_price, spot_open=ps.open_price,
                log_delta_pct=delta,
                up_bid=float(state.yes_bid) if state.yes_bid else None,
                up_ask=float(state.yes_ask) if state.yes_ask else None,
                down_bid=float(state.no_bid) if state.no_bid else None,
                down_ask=float(state.no_ask) if state.no_ask else None,
                kline_progress_pct=ps.kline_progress_pct,
                trigger_time_ms=now_ms,
            )
            triggered.set()

    # Setup WebSocket feeds
    feed = MarketFeed(on_update=on_update,
                      on_connect=lambda: print("    [WS] Connected"),
                      on_disconnect=lambda: print("\n    [WS] Reconnecting...") if not triggered.is_set() else None)
    await feed.add_market(market.slug, market.up_token_id, market.down_token_id)

    binance_symbol = BTCUSDT if asset == Asset.BTC else ETHUSDT
    binance_stream = BinanceKlineStream(symbol=binance_symbol, interval=INTERVAL_1M, on_kline=on_binance_kline)

    print(f"\n[2] Monitoring prices (WebSocket)...")
    print(f"    Waiting for UP >= {threshold - 0.01:.2f} or DOWN >= {threshold - 0.01:.2f}")
    print("    Press Ctrl+C to cancel\n")

    feed_task = asyncio.create_task(feed.start())
    binance_task = asyncio.create_task(binance_stream.start())

    try:
        await triggered.wait()
        trigger_info.print_details(threshold)

        # Place order (real or simulated)
        result["triggered_side"] = trigger_info.side
        result["trigger_price"] = trigger_info.trigger_price

        if dry_run:
            print(f"\n[3] [DRY RUN] Would place BUY {trigger_info.side} order at {trigger_info.trigger_price + 0.01:.3f}")
            result.update({"success": True, "order_id": "dry_run"})
        else:
            order_result = await place_order_and_check(api, trigger_info.token_id,
                                                        trigger_info.trigger_price, size, trigger_info.side)
            result.update(order_result)

        if result.get("success"):
            order_placed.set()

        # Wait for resolution (feeds keep running for study)
        if result.get("success") and wait_for_resolution_flag and resolution_time:
            print("\n[4] Monitoring continues during resolution wait...")
            print("    (Status updates continue in background)\n")

            now = datetime.now(timezone.utc)
            wait_seconds = (resolution_time - now).total_seconds()

            if wait_seconds > 0:
                print(f"    Resolution in {wait_seconds:.0f} seconds...")
                try:
                    while wait_seconds > 0:
                        sleep_chunk = min(wait_seconds, 30)
                        await asyncio.sleep(sleep_chunk)
                        wait_seconds -= sleep_chunk
                        if wait_seconds > 0:
                            print(f"    {wait_seconds:.0f}s remaining...")
                except (asyncio.CancelledError, KeyboardInterrupt):
                    print("\n    [CANCELLED] Stopped waiting")
                    result["cancelled"] = True

            # Check resolution result
            if not result.get("cancelled"):
                print("    Waiting for resolution to finalize...")
                await asyncio.sleep(10)

                print(f"\n[5] Checking resolution...")
                if dry_run:
                    print("    [DRY RUN] Would check market resolution")
                else:
                    market_info = await api.get_market_info(market.slug)
                    if market_info:
                        result["market_status"] = market_info.status.value
                        result["resolution"] = market_info.outcome
                        print(f"    Market status: {market_info.status.value}")
                        print(f"    Outcome: {market_info.outcome}")

                        if market_info.outcome:
                            won = ((result["triggered_side"] == "UP" and "up" in market_info.outcome.lower()) or
                                   (result["triggered_side"] == "DOWN" and "down" in market_info.outcome.lower()))
                            result["won"] = won
                            print(f"    Result: {'WON' if won else 'LOST'}")
                    else:
                        print("    Could not fetch market info")

    except (asyncio.CancelledError, KeyboardInterrupt):
        print("\n\n[CANCELLED] Monitoring stopped")
        result["cancelled"] = True
    finally:
        await feed.stop()
        await binance_stream.stop()
        for task in [feed_task, binance_task]:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return result


async def run_single_epoch(api: PolymarketAPI, asset: Asset, horizon: MarketHorizon,
                            threshold: float, size: float, dry_run: bool,
                            wait_for_resolution: bool, ignore_first_seconds: int = 0,
                            min_delta_pct: float = 0.005,
                            time_sync: Optional[TimeSync] = None) -> dict:
    """Run the strategy for a single epoch."""
    result = await monitor_and_trade(
        api=api, asset=asset, horizon=horizon, threshold=threshold, size=size,
        dry_run=dry_run, wait_for_resolution_flag=wait_for_resolution,
        ignore_first_seconds=ignore_first_seconds, min_delta_pct=min_delta_pct,
        time_sync=time_sync,
    )
    print_epoch_result(result)
    return result


async def main() -> int:
    # Require at least one argument to prevent accidental runs
    if len(sys.argv) == 1:
        print("Usage: run_oco_trading.py [OPTIONS]")
        print("")
        print("Examples:")
        print("  -n                    Dry run (no real orders)")
        print("  -b 10                 $10 bet (triggers at 79%)")
        print("  -b 5 -t 0.9           $5 bet (triggers at 89%)")
        print("  -n -b 5 -t 0.7        Dry run, $5 (triggers at 69%)")
        print("")
        print("Run with --help for all options.")
        return 1

    args = parse_args()
    size = args.bet / args.threshold
    asset = Asset.BTC if args.asset == "btc" else Asset.ETH
    horizon = horizon_from_str(args.horizon)
    loop_mode = not args.once

    # Print configuration
    print("\n" + "=" * 60)
    print("EXTREME THRESHOLD TRADING" + (" (CONTINUOUS)" if loop_mode else " (SINGLE EPOCH)"))
    print("=" * 60)
    print(f"\nConfiguration:")
    print(f"  Asset:      {asset.value}")
    print(f"  Horizon:    {horizon.name}")
    print(f"  Threshold:  {args.threshold:.0%} (triggers at {args.threshold - 0.01:.0%})")
    print(f"  Delta guard: abs(delta) > {args.min_delta}%")
    print(f"  Bet amount: ${args.bet:.2f}")
    print(f"  Size:       {size:.2f} shares")
    print(f"  Dry run:    {args.dry_run}")
    print(f"  Wait:       {'Yes' if not args.no_wait else 'No'}")
    print(f"  Mode:       {'Continuous loop' if loop_mode else 'Single epoch'}")
    if args.ignore_first_seconds > 0:
        print(f"  Ignore:     First {args.ignore_first_seconds}s of each epoch")

    # Initialize time sync with Binance server
    print("\nSyncing time with Binance...")
    time_sync = TimeSync()
    if time_sync.sync():
        print(f"  Time sync:  {time_sync.format_status()}")
    else:
        print("  Time sync:  FAILED (using local time)")

    # Load credentials
    poly_config = None
    if not args.dry_run:
        try:
            poly_config = PolymarketConfig.load()
            print(f"  Wallet:     {poly_config.wallet_address}")
            if not poly_config.has_trading_credentials:
                print("\n[ERROR] No trading credentials. Set POLYMARKET_PRIVATE_KEY")
                return 1
        except Exception as e:
            print(f"\n[ERROR] Failed to load config: {e}")
            return 1

    epoch_count, wins, losses = 0, 0, 0

    try:
        while True:
            epoch_count += 1
            print("\n" + "=" * 60)
            print(f"EPOCH {epoch_count}")
            print("=" * 60)

            # Check balance
            if not args.dry_run and poly_config:
                print("\n[0] Checking balance and allowance...")
                ok, msg = check_balance_and_allowance(poly_config.wallet_address, args.bet)
                print(f"    {msg}")
                if not ok:
                    print("\n[EXIT] Insufficient funds or allowance.")
                    break

            # Run epoch
            api = PolymarketAPI(poly_config) if not args.dry_run and poly_config else None
            try:
                result = await run_single_epoch(
                    api=api, asset=asset, horizon=horizon, threshold=args.threshold,
                    size=size, dry_run=args.dry_run, wait_for_resolution=not args.no_wait,
                    ignore_first_seconds=args.ignore_first_seconds, min_delta_pct=args.min_delta,
                    time_sync=time_sync,
                )
                if result.get("won") is True:
                    wins += 1
                elif result.get("won") is False:
                    losses += 1
                if result.get("cancelled"):
                    break
            finally:
                if api:
                    await api.close()

            if not loop_mode:
                break

            # Wait for next epoch with live price monitoring
            next_epoch_ts = get_slot_timestamp(horizon, 1)
            wait_seconds = next_epoch_ts - int(time.time())
            if wait_seconds > 0:
                next_time = datetime.fromtimestamp(next_epoch_ts, tz=timezone.utc)
                print(f"\n[NEXT EPOCH] Waiting {wait_seconds}s until {next_time.strftime('%H:%M:%S UTC')}...")
                print(f"             Stats: {wins}W / {losses}L / {epoch_count} epochs\n")

                # Start Binance WebSocket for price monitoring during wait
                price_state = PriceState()

                def on_kline(kline):
                    price_state.open_price = float(kline.open)
                    price_state.close_price = float(kline.close)
                    price_state.kline_start_ms = kline.start_time
                    price_state.kline_close_ms = kline.close_time
                    price_state.update_time_ms = time_sync.now_ms() if time_sync else int(time.time() * 1000)

                    remaining = next_epoch_ts - int(time.time())
                    spot_str = price_state.format_display()
                    kline_pct = price_state.format_time_info()
                    print(f"  [WAIT][{remaining:4d}s|{kline_pct:>3}] {spot_str}      ", end="\r")

                binance_symbol = BTCUSDT if asset == Asset.BTC else ETHUSDT
                binance_stream = BinanceKlineStream(symbol=binance_symbol, interval=INTERVAL_1M, on_kline=on_kline)
                binance_task = asyncio.create_task(binance_stream.start())

                try:
                    while wait_seconds > 0:
                        await asyncio.sleep(1)
                        wait_seconds = next_epoch_ts - int(time.time())
                except (asyncio.CancelledError, KeyboardInterrupt):
                    await binance_stream.stop()
                    binance_task.cancel()
                    break
                finally:
                    await binance_stream.stop()
                    binance_task.cancel()
                    try:
                        await binance_task
                    except asyncio.CancelledError:
                        pass
                print()  # Clear the line

    except KeyboardInterrupt:
        print("\n\n[EXIT] User interrupted.")

    # Final summary
    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    print(f"\n  Epochs:     {epoch_count}")
    print(f"  Wins:       {wins}")
    print(f"  Losses:     {losses}")
    if wins + losses > 0:
        print(f"  Win rate:   {wins / (wins + losses) * 100:.1f}%")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
