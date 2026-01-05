#!/usr/bin/env python3
"""Entry point for Polymarket trading platform."""

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

from poly import PolymarketClient, TradingEngine
from poly.config import Config
from poly.utils import setup_logging


async def main():
    """Main entry point."""
    # Load environment variables
    load_dotenv()

    # Setup logging
    setup_logging(logging.INFO)
    logger = logging.getLogger(__name__)

    # Load configuration
    config = Config.from_env_optional()
    if not config:
        logger.warning(
            "No API credentials found. Running in demo mode.\n"
            "Set environment variables or create .env file to enable trading."
        )
        print("\n" + "=" * 50)
        print("Polymarket Trading Platform")
        print("=" * 50)
        print("\nStatus: Demo Mode (no credentials)")
        print("\nTo enable trading, set these environment variables:")
        print("  - POLYMARKET_API_KEY")
        print("  - POLYMARKET_SECRET")
        print("  - POLYMARKET_PASSPHRASE")
        print("  - PRIVATE_KEY")
        print("\nSee .env.example for reference.")
        print("=" * 50 + "\n")
        return

    # Initialize client
    async with PolymarketClient(config) as client:
        logger.info("Connected to Polymarket")

        # Create trading engine
        engine = TradingEngine(client)
        await engine.start()

        try:
            # Fetch and display markets
            print("\n" + "=" * 50)
            print("Polymarket Trading Platform")
            print("=" * 50)

            markets = await client.get_markets(limit=10)
            print(f"\nFound {len(markets)} active markets:\n")

            for i, market in enumerate(markets, 1):
                status = "Active" if market.is_tradeable else "Closed"
                print(f"{i}. [{status}] {market.question[:60]}...")
                if market.tokens:
                    for token in market.tokens[:2]:
                        print(f"   - Token ID: {token.get('token_id', 'N/A')[:20]}...")

            # Display positions
            positions = await client.get_positions()
            if positions:
                print(f"\nYour Positions ({len(positions)}):")
                for pos in positions:
                    print(f"  - {pos.outcome}: {pos.size} @ {pos.avg_price}")
            else:
                print("\nNo open positions.")

            # Display open orders
            orders = await client.get_open_orders()
            if orders:
                print(f"\nOpen Orders ({len(orders)}):")
                for order in orders:
                    print(f"  - {order.side.value} {order.size} @ {order.price}")
            else:
                print("\nNo open orders.")

            print("\n" + "=" * 50)
            print("Platform initialized successfully!")
            print("=" * 50 + "\n")

        finally:
            await engine.stop()


if __name__ == "__main__":
    asyncio.run(main())
