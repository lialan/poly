"""Simple price query convenience functions.

These functions wrap the lower-level API calls for common price queries.

Usage:
    from poly.query import get_btc_price, get_eth_price

    # Async
    price = await get_btc_price()

    # Sync
    price = get_btc_price_sync()
"""

import asyncio
from decimal import Decimal
from typing import Optional

from poly.api.binance import (
    get_btc_price as _get_btc_price,
    get_eth_price as _get_eth_price,
    get_price as _get_price,
    get_prices as _get_prices,
    get_btc_stats as _get_btc_stats,
    get_eth_stats as _get_eth_stats,
    get_24h_stats,
    TickerPrice,
    TickerStats,
)


async def get_btc_price() -> Optional[Decimal]:
    """Get current BTC/USDT price from Binance.

    Returns:
        BTC price in USDT, or None if unavailable.
    """
    return await _get_btc_price()


async def get_eth_price() -> Optional[Decimal]:
    """Get current ETH/USDT price from Binance.

    Returns:
        ETH price in USDT, or None if unavailable.
    """
    return await _get_eth_price()


async def get_price(symbol: str) -> Optional[TickerPrice]:
    """Get current price for any trading pair.

    Args:
        symbol: Trading pair (e.g., "BTCUSDT", "ETHUSDT").

    Returns:
        TickerPrice object, or None if unavailable.
    """
    return await _get_price(symbol)


async def get_prices(*symbols: str) -> dict[str, Decimal]:
    """Get prices for multiple trading pairs concurrently.

    Args:
        symbols: Trading pairs to query.

    Returns:
        Dict mapping symbol to price.
    """
    return await _get_prices(*symbols)


async def get_btc_stats() -> Optional[TickerStats]:
    """Get BTC 24h statistics from Binance.

    Returns:
        TickerStats with 24h high/low/volume/change.
    """
    return await _get_btc_stats()


async def get_eth_stats() -> Optional[TickerStats]:
    """Get ETH 24h statistics from Binance.

    Returns:
        TickerStats with 24h high/low/volume/change.
    """
    return await _get_eth_stats()


async def get_btc_24h_change() -> Optional[float]:
    """Get BTC 24h price change percentage.

    Returns:
        Price change as percentage (e.g., 2.5 for +2.5%).
    """
    stats = await get_24h_stats("BTCUSDT")
    return float(stats.price_change_percent) if stats else None


async def get_eth_24h_change() -> Optional[float]:
    """Get ETH 24h price change percentage.

    Returns:
        Price change as percentage (e.g., -1.2 for -1.2%).
    """
    stats = await get_24h_stats("ETHUSDT")
    return float(stats.price_change_percent) if stats else None


# Synchronous versions for convenience


def get_btc_price_sync() -> Optional[Decimal]:
    """Synchronous version of get_btc_price()."""
    return asyncio.run(get_btc_price())


def get_eth_price_sync() -> Optional[Decimal]:
    """Synchronous version of get_eth_price()."""
    return asyncio.run(get_eth_price())


def get_price_sync(symbol: str) -> Optional[TickerPrice]:
    """Synchronous version of get_price()."""
    return asyncio.run(get_price(symbol))


def get_btc_stats_sync() -> Optional[TickerStats]:
    """Synchronous version of get_btc_stats()."""
    return asyncio.run(get_btc_stats())


def get_eth_stats_sync() -> Optional[TickerStats]:
    """Synchronous version of get_eth_stats()."""
    return asyncio.run(get_eth_stats())


__all__ = [
    # Async
    "get_btc_price",
    "get_eth_price",
    "get_price",
    "get_prices",
    "get_btc_stats",
    "get_eth_stats",
    "get_btc_24h_change",
    "get_eth_24h_change",
    # Sync
    "get_btc_price_sync",
    "get_eth_price_sync",
    "get_price_sync",
    "get_btc_stats_sync",
    "get_eth_stats_sync",
]
