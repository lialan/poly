#!/usr/bin/env python3
"""Test script for Binance price fetching."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from poly.api.binance import (
    get_btc_price,
    get_eth_price,
    get_prices,
    get_btc_stats,
    get_eth_stats,
    print_stats,
    BTCUSDT,
    ETHUSDT,
)


async def main():
    print("=" * 50)
    print("Binance Price Query Test")
    print("=" * 50)

    # Get individual prices
    print("\n--- Current Prices ---")
    btc = await get_btc_price()
    eth = await get_eth_price()

    if btc:
        print(f"BTC/USDT: ${btc:,.2f}")
    else:
        print("BTC/USDT: Failed to fetch")

    if eth:
        print(f"ETH/USDT: ${eth:,.2f}")
    else:
        print("ETH/USDT: Failed to fetch")

    # Get multiple prices at once
    print("\n--- Batch Price Query ---")
    prices = await get_prices(BTCUSDT, ETHUSDT, "SOLUSDT", "BNBUSDT")
    for symbol, price in prices.items():
        print(f"{symbol}: ${price:,.2f}")

    # Get 24h stats
    print("\n--- 24h Statistics ---")
    btc_stats = await get_btc_stats()
    if btc_stats:
        print_stats(btc_stats)

    print()
    eth_stats = await get_eth_stats()
    if eth_stats:
        print_stats(eth_stats)

    print("\n" + "=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
