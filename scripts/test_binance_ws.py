#!/usr/bin/env python3
"""Test script for Binance WebSocket kline stream."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from poly.api.binance_ws import (
    BinanceKlineStream,
    RealtimeKline,
    BTCUSDT,
    INTERVAL_1M,
    print_kline,
)


def custom_handler(kline: RealtimeKline) -> None:
    """Custom kline handler with more details."""
    status = "CLOSED" if kline.is_final else "LIVE"
    direction = "▲" if kline.is_bullish else "▼"

    print(f"\n{'=' * 50}")
    print(f"Real-time Kline: {kline.symbol} {kline.interval}")
    print(f"{'=' * 50}")
    print(f"  Time:      {kline.start_time_dt.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  Status:    {status}")
    print(f"  Open:      ${kline.open:,.2f}")
    print(f"  High:      ${kline.high:,.2f}")
    print(f"  Low:       ${kline.low:,.2f}")
    print(f"  Close:     ${kline.close:,.2f} {direction}")
    print(f"  Volume:    {kline.volume:,.4f} BTC")
    print(f"  Trades:    {kline.num_trades:,}")


async def main():
    print("=" * 50)
    print("Binance WebSocket Kline Stream Test")
    print("=" * 50)
    print(f"Symbol:   BTCUSDT")
    print(f"Interval: 1m")
    print(f"Duration: 15 seconds")
    print("=" * 50)
    print("\nConnecting to Binance WebSocket...")

    stream = BinanceKlineStream(
        symbol=BTCUSDT,
        interval=INTERVAL_1M,
        on_kline=custom_handler,
    )

    # Run for 15 seconds
    task = asyncio.create_task(stream.start())

    try:
        await asyncio.sleep(15)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    finally:
        await stream.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    print("\n" + "=" * 50)
    print("Test completed!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
