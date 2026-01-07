#!/usr/bin/env python3
"""Trading bot runner script.

Usage:
    python scripts/run_trading_bot.py
    python scripts/run_trading_bot.py --asset btc --interval 3.0
    python scripts/run_trading_bot.py --lookback 600  # 10 minutes of history
    python scripts/run_trading_bot.py --no-timing     # Disable timing output
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from poly.markets import Asset, MarketHorizon
from poly.trading_bot import (
    TradingBot,
    TradingBotConfig,
    MarketContext,
    DecisionResult,
    no_op_decision,
)


def setup_logging(level: str = "INFO"):
    """Configure logging for the trading bot."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args():
    parser = argparse.ArgumentParser(description="Polymarket Trading Bot")
    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to JSON config file (default: config/trading_bot.json)"
    )
    parser.add_argument(
        "--asset", type=str, default=None, choices=["btc", "eth"],
        help="Asset to trade (overrides config)"
    )
    parser.add_argument(
        "--horizon", type=str, default=None, choices=["15m", "1h", "4h", "d1"],
        help="Market horizon (overrides config)"
    )
    parser.add_argument(
        "--interval", type=float, default=None,
        help="Decision interval in seconds (overrides config)"
    )
    parser.add_argument(
        "--lookback", type=float, default=None,
        help="Bigtable lookback window in seconds (overrides config)"
    )
    parser.add_argument(
        "--no-rest-test", action="store_true",
        help="Skip REST API connectivity test at startup"
    )
    parser.add_argument(
        "--no-timing", action="store_true",
        help="Disable timing debug output"
    )
    parser.add_argument(
        "--log-level", type=str, default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (overrides config)"
    )
    return parser.parse_args()


def example_decision(context: MarketContext) -> DecisionResult:
    """Example decision function that logs market state.

    This demonstrates how to access context data for trading decisions.
    Always returns should_trade=False (observation mode).
    """
    # Early return if no live data
    if not context.live_state:
        return DecisionResult(should_trade=False, reason="No live data")

    # Get current implied probability
    prob = context.live_state.implied_prob
    if prob is None:
        return DecisionResult(should_trade=False, reason="No implied probability")

    # Format live state
    yes_bid = f"{context.live_state.yes_bid:.3f}" if context.live_state.yes_bid else "----"
    yes_ask = f"{context.live_state.yes_ask:.3f}" if context.live_state.yes_ask else "----"

    # Format historical data info
    n_snaps = len(context.historical_snapshots)
    spot_str = f"${context.spot_price:,.0f}" if context.spot_price else "N/A"

    # Print current state
    print(
        f"  {context.asset.value.upper()}: {spot_str} | "
        f"YES: {yes_bid}/{yes_ask} ({prob*100:.1f}%) | "
        f"Time: {context.time_remaining_sec:.0f}s | "
        f"History: {n_snaps} snaps"
    )

    # Example decision logic (always returns False for now)
    # You can add real logic here, e.g.:
    # if prob < 0.35 and context.time_remaining_sec > 120:
    #     return DecisionResult(
    #         should_trade=True,
    #         signal="buy_yes",
    #         confidence=0.8,
    #         reason=f"Underpriced at {prob:.1%}",
    #     )

    return DecisionResult(should_trade=False, reason="Observation mode")


async def main():
    args = parse_args()

    # Load config from file or environment
    config = TradingBotConfig.load(args.config)

    # Apply CLI overrides
    if args.asset:
        config.asset = Asset.BTC if args.asset == "btc" else Asset.ETH
    if args.horizon:
        horizon_map = {"15m": MarketHorizon.M15, "1h": MarketHorizon.H1, "4h": MarketHorizon.H4, "d1": MarketHorizon.D1}
        config.horizon = horizon_map[args.horizon]
    if args.interval is not None:
        config.decision_interval_sec = args.interval
    if args.lookback is not None:
        config.bigtable_lookback_sec = args.lookback
    if args.no_rest_test:
        config.test_rest_apis = False
    if args.no_timing:
        config.debug_timing = False
    if args.log_level:
        config.log_level = args.log_level

    # Setup logging with config level
    setup_logging(config.log_level)

    # Print banner
    print("=" * 60)
    print("POLYMARKET TRADING BOT")
    print("=" * 60)
    print(f"Asset: {config.asset.value.upper()}")
    print(f"Horizon: {config.horizon.name}")
    print(f"Decision interval: {config.decision_interval_sec}s")
    print(f"Bigtable lookback: {config.bigtable_lookback_sec}s")
    print(f"Debug timing: {config.debug_timing}")
    print("=" * 60)
    print()

    # Create and run bot with example decision function
    bot = TradingBot(config, decision_fn=example_decision)

    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"\nError: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
