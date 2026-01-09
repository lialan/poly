"""Binance WebSocket price collector for real-time kline data."""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Optional

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

# Binance WebSocket endpoint
BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"

# Symbols
BTCUSDT = "btcusdt"
ETHUSDT = "ethusdt"

# Intervals
INTERVAL_1M = "1m"
INTERVAL_5M = "5m"
INTERVAL_15M = "15m"
INTERVAL_1H = "1h"


@dataclass
class RealtimeKline:
    """Real-time kline data from WebSocket stream."""

    symbol: str
    interval: str
    start_time: int  # Unix timestamp in ms
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    close_time: int  # Unix timestamp in ms
    quote_volume: Decimal
    num_trades: int
    taker_buy_volume: Decimal
    taker_buy_quote_volume: Decimal
    is_final: bool  # True if candle is closed

    @property
    def start_time_dt(self) -> datetime:
        """Get start time as datetime."""
        return datetime.fromtimestamp(self.start_time / 1000, tz=timezone.utc)

    @property
    def close_time_dt(self) -> datetime:
        """Get close time as datetime."""
        return datetime.fromtimestamp(self.close_time / 1000, tz=timezone.utc)

    @property
    def is_bullish(self) -> bool:
        """Check if candle closed higher than it opened."""
        return self.close >= self.open

    @property
    def price_float(self) -> float:
        """Get close price as float."""
        return float(self.close)


def parse_kline_message(data: dict) -> Optional[RealtimeKline]:
    """Parse WebSocket kline message into RealtimeKline object.

    Args:
        data: Raw WebSocket message data.

    Returns:
        RealtimeKline object or None if parsing fails.
    """
    try:
        kline = data.get("k", {})
        if not kline:
            return None

        return RealtimeKline(
            symbol=kline["s"].upper(),
            interval=kline["i"],
            start_time=kline["t"],
            open=Decimal(kline["o"]),
            high=Decimal(kline["h"]),
            low=Decimal(kline["l"]),
            close=Decimal(kline["c"]),
            volume=Decimal(kline["v"]),
            close_time=kline["T"],
            quote_volume=Decimal(kline["q"]),
            num_trades=kline["n"],
            taker_buy_volume=Decimal(kline["V"]),
            taker_buy_quote_volume=Decimal(kline["Q"]),
            is_final=kline["x"],
        )
    except (KeyError, ValueError) as e:
        logger.error(f"Failed to parse kline message: {e}")
        return None


def print_kline(kline: RealtimeKline) -> None:
    """Print kline in formatted output."""
    status = "CLOSED" if kline.is_final else "OPEN"
    direction = "▲" if kline.is_bullish else "▼"
    print(
        f"[{kline.start_time_dt.strftime('%H:%M:%S')}] "
        f"{kline.symbol} {kline.interval} {direction} "
        f"${kline.close:,.2f} ({status})"
    )


class BinanceKlineStream:
    """WebSocket client for Binance kline streams with auto-reconnect."""

    def __init__(
        self,
        symbol: str = BTCUSDT,
        interval: str = INTERVAL_1M,
        on_kline: Optional[Callable[[RealtimeKline], None]] = None,
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 60.0,
    ):
        """Initialize the kline stream.

        Args:
            symbol: Trading pair symbol (lowercase, e.g., 'btcusdt').
            interval: Kline interval (e.g., '1m', '15m').
            on_kline: Callback function for each kline update.
            reconnect_delay: Initial delay between reconnection attempts.
            max_reconnect_delay: Maximum delay between reconnection attempts.
        """
        self.symbol = symbol.lower()
        self.interval = interval
        self.on_kline = on_kline or print_kline
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        self._running = False
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._current_delay = reconnect_delay

    @property
    def stream_url(self) -> str:
        """Get the WebSocket stream URL."""
        return f"{BINANCE_WS_URL}/{self.symbol}@kline_{self.interval}"

    async def start(self) -> None:
        """Start the WebSocket stream with auto-reconnect."""
        self._running = True
        logger.info(f"Starting kline stream for {self.symbol} @ {self.interval}")

        while self._running:
            try:
                await self._connect()
            except Exception as e:
                if not self._running:
                    break
                logger.error(f"Connection error: {e}")
                await self._handle_reconnect()

    async def _connect(self) -> None:
        """Connect to WebSocket and process messages."""
        logger.info(f"Connecting to {self.stream_url}")

        async with websockets.connect(self.stream_url) as ws:
            self._ws = ws
            self._current_delay = self.reconnect_delay  # Reset delay on success
            logger.info("WebSocket connection opened")

            async for message in ws:
                if not self._running:
                    break
                await self._process_message(message)

    async def _process_message(self, message: str) -> None:
        """Process incoming WebSocket message."""
        try:
            data = json.loads(message)
            kline = parse_kline_message(data)
            if kline:
                self.on_kline(kline)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode message: {e}")

    async def _handle_reconnect(self) -> None:
        """Handle reconnection with exponential backoff."""
        logger.info(f"Reconnecting in {self._current_delay:.1f}s...")
        await asyncio.sleep(self._current_delay)
        self._current_delay = min(
            self._current_delay * 2, self.max_reconnect_delay
        )

    async def stop(self) -> None:
        """Stop the WebSocket stream."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("WebSocket stream stopped")


async def collect_klines(
    symbol: str = BTCUSDT,
    interval: str = INTERVAL_1M,
    on_kline: Optional[Callable[[RealtimeKline], None]] = None,
    duration: Optional[float] = None,
) -> None:
    """Collect kline data from WebSocket stream.

    Args:
        symbol: Trading pair symbol (lowercase).
        interval: Kline interval.
        on_kline: Callback for each kline update.
        duration: Run duration in seconds (None for indefinite).
    """
    stream = BinanceKlineStream(symbol, interval, on_kline)

    if duration:
        async def run_with_timeout():
            task = asyncio.create_task(stream.start())
            await asyncio.sleep(duration)
            await stream.stop()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await run_with_timeout()
    else:
        await stream.start()


async def main():
    """Example usage of the kline stream."""
    print("Starting BTC/USDT 1m kline WebSocket stream...")
    print("Press Ctrl+C to stop\n")

    # Collect for 30 seconds as a demo
    await collect_klines(
        symbol=BTCUSDT,
        interval=INTERVAL_1M,
        duration=30,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    asyncio.run(main())
