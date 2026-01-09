#!/usr/bin/env python3
"""
Test OCO Limit Strategy (Dry Run)
=================================

Demonstrates the OCO (One-Cancels-Other) limit order strategy
in dry-run mode. No real orders are placed.

The strategy:
1. Fetches current market for specified asset/horizon
2. Places two limit BUY orders (UP and DOWN) at threshold price (0.8)
3. When either order's trade reaches MINED status, cancels the other
4. Reports the winner

Usage:
    python scripts/test_oco_strategy.py

"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from poly.markets import Asset, MarketHorizon
from poly.strategies import (
    OCOLimitStrategy,
    OCOConfig,
    OCOState,
    OrderUpdateEvent,
    WinnerSide,
)


async def simulate_order_events(strategy: OCOLimitStrategy) -> None:
    """Simulate order lifecycle events."""
    print("\n--- Simulating order lifecycle ---\n")

    up_order_id = strategy.up_order_id
    down_order_id = strategy.down_order_id

    # Simulate: Both orders go LIVE
    print("1. Both orders are LIVE in orderbook at threshold 0.8...")
    await asyncio.sleep(0.5)

    # Simulate: DOWN order gets matched first (DOWN prob hit 80%)
    print("2. DOWN order gets a match (DOWN prob >= 80%, UP fell to <= 20%)...")
    await strategy.on_order_update(OrderUpdateEvent(
        order_id=down_order_id,
        order_status="MATCHED",
        trade_id="trade_down_001",
        trade_status="MATCHED",
    ))
    await asyncio.sleep(0.5)

    # Simulate: DOWN trade goes to MINED (on-chain)
    print("3. DOWN trade is MINED on-chain -> triggers OCO!")
    await strategy.on_order_update(OrderUpdateEvent(
        order_id=down_order_id,
        order_status="MATCHED",
        trade_id="trade_down_001",
        trade_status="MINED",  # <-- This triggers OCO
    ))


async def main():
    print("=" * 60)
    print("OCO LIMIT STRATEGY - DRY RUN TEST")
    print("=" * 60)

    # Configure the strategy
    config = OCOConfig(
        asset=Asset.BTC,
        horizon=MarketHorizon.M15,
        size=100.0,       # 100 shares
        threshold=0.8,    # Threshold price for both orders
        dry_run=True,     # No real orders placed
    )

    print(f"\nConfiguration:")
    print(f"  Asset:      {config.asset.value}")
    print(f"  Horizon:    {config.horizon.name}")
    print(f"  Threshold:  {config.threshold}")
    print(f"  Size:       {config.size}")
    print(f"  Dry run:    {config.dry_run}")

    # Create strategy (no API needed for dry run)
    strategy = OCOLimitStrategy(config, api=None)

    print(f"\nInitial state: {strategy.state}")

    # Start the strategy (places both orders)
    print("\n--- Starting strategy ---")
    await strategy.start()

    print(f"\nState after start: {strategy.state}")
    print(f"UP order ID:   {strategy.up_order_id}")
    print(f"DOWN order ID: {strategy.down_order_id}")

    # Simulate order events
    await simulate_order_events(strategy)

    # Check final result
    print("\n--- Final Result ---")
    print(f"State:  {strategy.state}")
    print(f"Done:   {strategy.is_done}")

    result = strategy.result
    if result:
        print(f"\nMarket slug:     {result.market_slug}")
        print(f"UP token:        {result.up_token_id}")
        print(f"DOWN token:      {result.down_token_id}")
        print(f"\nWinner:          {result.winner.value}")
        print(f"Winning order:   {result.winning_order_id}")
        print(f"Winning trade:   {result.winning_trade_id}")
        print(f"Losing order:    {result.losing_order_id}")
        print(f"Cancel success:  {result.cancel_success}")
        print(f"Anomaly:         {result.anomaly}")
        print(f"Duration:        {result.duration_sec:.3f}s")

    # Show action log
    print("\n--- Action Log ---")
    for entry in strategy.action_log:
        ts = entry.pop("timestamp")
        action = entry.pop("action")
        dry = entry.pop("dry_run")
        print(f"  [{action}] {entry}")

    print("\n" + "=" * 60)
    print("DRY RUN COMPLETE")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
