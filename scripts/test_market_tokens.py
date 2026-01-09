#!/usr/bin/env python3
"""
Test Market Token ID Queries

Fetches and displays BTC market slugs and token IDs for 15m, 1h, and 4h horizons.
Shows current and next 3 future markets for each horizon.

Usage:
    python scripts/test_market_tokens.py
"""

import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, "src")

from poly import Asset, MarketHorizon, get_slug, PolymarketAPI
from poly.api.polymarket_config import PolymarketConfig


SLOT_LABELS = ["current", "next", "next+1", "next+2"]


async def main():
    """Fetch and display BTC market tokens for all horizons."""
    print("=" * 80)
    print("BTC MARKET TOKENS")
    print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 80)

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

            for i, label in enumerate(SLOT_LABELS):
                slug = get_slug(Asset.BTC, horizon, slots_ahead=i)
                tokens = await api.get_market_tokens(slug)

                if tokens:
                    up = tokens.get("up", "")
                    down = tokens.get("down", "")
                    print(f"  {label:8} {slug}")
                    print(f"           UP:   {up}")
                    print(f"           DOWN: {down}")
                else:
                    print(f"  {label:8} {slug} [No tokens]")

    finally:
        await api.close()

    print("\n" + "=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
