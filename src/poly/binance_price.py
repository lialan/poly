"""Binance price fetching utilities (no API key required for public endpoints)."""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import aiohttp

BINANCE_API_BASE = "https://api.binance.com/api/v3"

# Common trading pairs
BTCUSDT = "BTCUSDT"
ETHUSDT = "ETHUSDT"
BTCUSD = "BTCUSD"
ETHUSD = "ETHUSD"


@dataclass
class TickerPrice:
    """Represents a ticker price from Binance."""

    symbol: str
    price: Decimal

    @property
    def price_float(self) -> float:
        """Get price as float."""
        return float(self.price)


@dataclass
class TickerStats:
    """24-hour ticker statistics from Binance."""

    symbol: str
    price: Decimal
    price_change: Decimal
    price_change_percent: Decimal
    high_24h: Decimal
    low_24h: Decimal
    volume_24h: Decimal
    quote_volume_24h: Decimal

    @property
    def price_float(self) -> float:
        return float(self.price)

    @property
    def change_percent_float(self) -> float:
        return float(self.price_change_percent)


async def get_price(symbol: str = BTCUSDT) -> Optional[TickerPrice]:
    """Get current price for a symbol.

    Args:
        symbol: Trading pair symbol (e.g., 'BTCUSDT', 'ETHUSDT').

    Returns:
        TickerPrice object or None if failed.
    """
    url = f"{BINANCE_API_BASE}/ticker/price?symbol={symbol}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                return None

            data = await response.json()
            return TickerPrice(
                symbol=data["symbol"],
                price=Decimal(data["price"]),
            )


async def get_btc_price() -> Optional[Decimal]:
    """Get current BTC/USDT price.

    Returns:
        BTC price in USDT or None if failed.
    """
    ticker = await get_price(BTCUSDT)
    return ticker.price if ticker else None


async def get_eth_price() -> Optional[Decimal]:
    """Get current ETH/USDT price.

    Returns:
        ETH price in USDT or None if failed.
    """
    ticker = await get_price(ETHUSDT)
    return ticker.price if ticker else None


async def get_prices(*symbols: str) -> dict[str, Decimal]:
    """Get prices for multiple symbols concurrently.

    Args:
        symbols: Trading pair symbols.

    Returns:
        Dict mapping symbol to price.
    """
    if not symbols:
        symbols = (BTCUSDT, ETHUSDT)

    async with aiohttp.ClientSession() as session:
        tasks = [_fetch_price(session, s) for s in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    prices = {}
    for symbol, result in zip(symbols, results):
        if isinstance(result, Decimal):
            prices[symbol] = result

    return prices


async def _fetch_price(session: aiohttp.ClientSession, symbol: str) -> Optional[Decimal]:
    """Fetch a single price using existing session."""
    url = f"{BINANCE_API_BASE}/ticker/price?symbol={symbol}"

    try:
        async with session.get(url) as response:
            if response.status != 200:
                return None
            data = await response.json()
            return Decimal(data["price"])
    except Exception:
        return None


async def get_24h_stats(symbol: str = BTCUSDT) -> Optional[TickerStats]:
    """Get 24-hour statistics for a symbol.

    Args:
        symbol: Trading pair symbol.

    Returns:
        TickerStats object or None if failed.
    """
    url = f"{BINANCE_API_BASE}/ticker/24hr?symbol={symbol}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                return None

            data = await response.json()
            return TickerStats(
                symbol=data["symbol"],
                price=Decimal(data["lastPrice"]),
                price_change=Decimal(data["priceChange"]),
                price_change_percent=Decimal(data["priceChangePercent"]),
                high_24h=Decimal(data["highPrice"]),
                low_24h=Decimal(data["lowPrice"]),
                volume_24h=Decimal(data["volume"]),
                quote_volume_24h=Decimal(data["quoteVolume"]),
            )


async def get_btc_stats() -> Optional[TickerStats]:
    """Get 24-hour BTC/USDT statistics."""
    return await get_24h_stats(BTCUSDT)


async def get_eth_stats() -> Optional[TickerStats]:
    """Get 24-hour ETH/USDT statistics."""
    return await get_24h_stats(ETHUSDT)


def print_price(ticker: TickerPrice) -> None:
    """Print ticker price in formatted output."""
    print(f"{ticker.symbol}: ${ticker.price:,.2f}")


def print_stats(stats: TickerStats) -> None:
    """Print 24h stats in formatted output."""
    change_sign = "+" if stats.price_change >= 0 else ""
    print(f"{stats.symbol}")
    print(f"  Price:    ${stats.price:,.2f}")
    print(f"  24h:      {change_sign}{stats.price_change_percent:.2f}%")
    print(f"  High:     ${stats.high_24h:,.2f}")
    print(f"  Low:      ${stats.low_24h:,.2f}")
    print(f"  Volume:   {stats.volume_24h:,.2f}")
