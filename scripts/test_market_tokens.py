#!/usr/bin/env python3
"""
Test Market Token ID Queries

Fetches and displays current BTC market slugs and token IDs for 15m, 1h, and 4h horizons.

Usage:
    python scripts/test_market_tokens.py
"""

import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, "src")

from poly import Asset, MarketHorizon, get_slug, PolymarketAPI
from poly.polymarket_config import PolymarketConfig


async def main():
    """Fetch and display BTC market tokens for all horizons."""
    print("=" * 70)
    print("BTC MARKET TOKENS")
    print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 70)

    # Use dummy wallet for read-only queries
    config = PolymarketConfig(
        wallet_address="0x0000000000000000000000000000000000000000"
    )

    api = PolymarketAPI(config)

    horizons = [
        ("15m", MarketHorizon.M15),
        ("1h", MarketHorizon.H1),
        ("4h", MarketHorizon.H4),
    ]

    try:
        for name, horizon in horizons:
            print(f"\n[BTC {name}]")

            # Get current slug
            slug = get_slug(Asset.BTC, horizon)
            print(f"  Slug: {slug}")

            # Fetch tokens from API
            tokens = await api.get_market_tokens(slug)

            if tokens:
                up_token = tokens.get("up", "")
                down_token = tokens.get("down", "")
                print(f"  UP:   {up_token}")
                print(f"  DOWN: {down_token}")
            else:
                print("  [No tokens found]")

    finally:
        await api.close()

    print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
