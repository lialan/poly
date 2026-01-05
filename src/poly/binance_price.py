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

# Kline intervals
INTERVAL_1M = "1m"
INTERVAL_5M = "5m"
INTERVAL_15M = "15m"
INTERVAL_1H = "1h"
INTERVAL_4H = "4h"
INTERVAL_1D = "1d"


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


@dataclass
class Kline:
    """Represents a candlestick/kline from Binance."""

    symbol: str
    interval: str
    open_time: int  # Unix timestamp in ms
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal  # Base asset volume
    close_time: int  # Unix timestamp in ms
    quote_volume: Decimal  # Quote asset volume (e.g., USDT)
    num_trades: int
    taker_buy_volume: Decimal
    taker_buy_quote_volume: Decimal

    @property
    def open_time_dt(self):
        """Get open time as datetime."""
        from datetime import datetime, timezone
        return datetime.fromtimestamp(self.open_time / 1000, tz=timezone.utc)

    @property
    def close_time_dt(self):
        """Get close time as datetime."""
        from datetime import datetime, timezone
        return datetime.fromtimestamp(self.close_time / 1000, tz=timezone.utc)

    @property
    def is_bullish(self) -> bool:
        """Check if candle closed higher than it opened."""
        return self.close >= self.open

    @property
    def body_size(self) -> Decimal:
        """Get the absolute size of the candle body."""
        return abs(self.close - self.open)

    @property
    def range_size(self) -> Decimal:
        """Get the full range (high - low)."""
        return self.high - self.low


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


async def get_klines(
    symbol: str = BTCUSDT,
    interval: str = INTERVAL_15M,
    limit: int = 10,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
) -> list[Kline]:
    """Get candlestick/kline data.

    Args:
        symbol: Trading pair symbol (e.g., 'BTCUSDT').
        interval: Kline interval (e.g., '15m', '1h', '1d').
        limit: Number of klines to return (max 1000).
        start_time: Start time in milliseconds.
        end_time: End time in milliseconds.

    Returns:
        List of Kline objects, oldest first.
    """
    url = f"{BINANCE_API_BASE}/klines?symbol={symbol}&interval={interval}&limit={limit}"

    if start_time:
        url += f"&startTime={start_time}"
    if end_time:
        url += f"&endTime={end_time}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                return []

            data = await response.json()
            return [_parse_kline(symbol, interval, k) for k in data]


async def get_latest_kline(
    symbol: str = BTCUSDT,
    interval: str = INTERVAL_15M,
) -> Optional[Kline]:
    """Get the most recent (current) kline.

    Args:
        symbol: Trading pair symbol.
        interval: Kline interval.

    Returns:
        The current/latest Kline or None.
    """
    klines = await get_klines(symbol, interval, limit=1)
    return klines[0] if klines else None


async def get_btc_15m_kline() -> Optional[Kline]:
    """Get the current 15-minute BTC/USDT kline."""
    return await get_latest_kline(BTCUSDT, INTERVAL_15M)


async def get_eth_15m_kline() -> Optional[Kline]:
    """Get the current 15-minute ETH/USDT kline."""
    return await get_latest_kline(ETHUSDT, INTERVAL_15M)


async def get_kline_at_time(
    symbol: str,
    interval: str,
    timestamp_ms: int,
) -> Optional[Kline]:
    """Get the kline that contains a specific timestamp.

    Args:
        symbol: Trading pair symbol.
        interval: Kline interval.
        timestamp_ms: Unix timestamp in milliseconds.

    Returns:
        The Kline containing that timestamp or None.
    """
    # Fetch a small window around the timestamp
    klines = await get_klines(
        symbol=symbol,
        interval=interval,
        limit=2,
        start_time=timestamp_ms - 1,
        end_time=timestamp_ms + 1,
    )

    for kline in klines:
        if kline.open_time <= timestamp_ms <= kline.close_time:
            return kline

    return klines[0] if klines else None


def _parse_kline(symbol: str, interval: str, data: list) -> Kline:
    """Parse raw kline array into Kline object.

    Binance kline format:
    [
        0: Open time (ms),
        1: Open,
        2: High,
        3: Low,
        4: Close,
        5: Volume,
        6: Close time (ms),
        7: Quote asset volume,
        8: Number of trades,
        9: Taker buy base asset volume,
        10: Taker buy quote asset volume,
        11: Ignore
    ]
    """
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time=int(data[0]),
        open=Decimal(str(data[1])),
        high=Decimal(str(data[2])),
        low=Decimal(str(data[3])),
        close=Decimal(str(data[4])),
        volume=Decimal(str(data[5])),
        close_time=int(data[6]),
        quote_volume=Decimal(str(data[7])),
        num_trades=int(data[8]),
        taker_buy_volume=Decimal(str(data[9])),
        taker_buy_quote_volume=Decimal(str(data[10])),
    )


def print_kline(kline: Kline) -> None:
    """Print kline in formatted output."""
    direction = "▲" if kline.is_bullish else "▼"
    print(f"{kline.symbol} {kline.interval} {direction}")
    print(f"  Time:     {kline.open_time_dt} - {kline.close_time_dt}")
    print(f"  Open:     ${kline.open:,.2f}")
    print(f"  High:     ${kline.high:,.2f}")
    print(f"  Low:      ${kline.low:,.2f}")
    print(f"  Close:    ${kline.close:,.2f}")
    print(f"  Volume:   {kline.volume:,.4f} BTC")
    print(f"  Quote Vol: ${kline.quote_volume:,.2f}")
    print(f"  Trades:   {kline.num_trades:,}")
