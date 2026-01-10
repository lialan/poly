#!/usr/bin/env python3
"""CCXT.pro based Binance orderbook depth collector.

Collects Binance orderbook data via WebSocket using ccxt.pro and stores
aggregated depth buckets to Bigtable.

Features:
- Uses ccxt.pro WebSocket for real-time orderbook updates
- Aggregates orderbook into log-delta buckets (configurable step/steps)
- Stores aggregated data to Bigtable with epoch timestamp (1s aligned)
- Collects BTC/USDT only

Usage:
    # Dry run (no database writes)
    python ccxt_depth_collector.py --dry-run

    # Production with default settings (0.002% step, 40 steps = 0.08% depth)
    python ccxt_depth_collector.py --step 0.00002 --steps 40

    # Custom interval
    python ccxt_depth_collector.py --interval 1
"""

import argparse
import asyncio
import json
import math
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import ccxt.pro as ccxtpro

# Add src to path for poly imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

# Bigtable table name
TABLE_BTC_DEPTH = "binance_btc_depth"


def get_epoch_timestamp() -> int:
    """Get current Unix timestamp aligned to 1-second boundary.

    Similar to polymarket's slug timestamp format but at 1s granularity.
    """
    return int(time.time())


@dataclass
class AggregatedDepth:
    """Aggregated orderbook depth snapshot."""
    symbol: str
    timestamp: float       # Actual collection timestamp
    epoch: int             # 1-second aligned epoch (like polymarket slug format)
    best_bid: float
    best_ask: float
    bid_buckets: list[float]  # USDT value per bucket
    ask_buckets: list[float]  # USDT value per bucket
    step_pct: float
    num_steps: int

    @property
    def spread_bps(self) -> float:
        """Spread in basis points."""
        if self.best_bid > 0:
            mid = (self.best_bid + self.best_ask) / 2
            return ((self.best_ask - self.best_bid) / mid) * 10000
        return 0.0

    @property
    def total_bid_usdt(self) -> float:
        """Total bid liquidity in USDT."""
        return sum(self.bid_buckets)

    @property
    def total_ask_usdt(self) -> float:
        """Total ask liquidity in USDT."""
        return sum(self.ask_buckets)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "epoch": self.epoch,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "bid_buckets": self.bid_buckets,
            "ask_buckets": self.ask_buckets,
            "step_pct": self.step_pct,
            "num_steps": self.num_steps,
        }

    def summary(self) -> str:
        """Human-readable summary."""
        return (
            f"{self.symbol} ${self.best_bid:,.2f}/{self.best_ask:,.2f} | "
            f"spread: {self.spread_bps:.1f}bps | "
            f"bids: ${self.total_bid_usdt/1e6:.1f}M | "
            f"asks: ${self.total_ask_usdt/1e6:.1f}M | "
            f"epoch: {self.epoch}"
        )


def aggregate_orderbook(levels: list, ref_price: float, step_pct: float, num_steps: int) -> list[float]:
    """Aggregate order book levels into buckets by log delta (in USDT).

    Args:
        levels: List of [price, amount] pairs
        ref_price: Reference price (best bid or best ask)
        step_pct: Log delta percentage per step (e.g., 0.00002 for 0.002%)
        num_steps: Number of aggregation buckets

    Returns:
        List of USDT values per bucket
    """
    buckets = [0.0] * num_steps

    for price, amount in levels:
        if price <= 0 or ref_price <= 0:
            continue
        log_delta = abs(math.log(ref_price) - math.log(price))
        bucket_idx = int(log_delta / step_pct)
        if bucket_idx < num_steps:
            buckets[bucket_idx] += amount * price  # Convert to USDT

    return buckets


class CCXTDepthCollector:
    """Collector for Binance orderbook depth using ccxt.pro WebSocket."""

    def __init__(
        self,
        step_pct: float = 0.00002,
        num_steps: int = 40,
        interval_sec: float = 1.0,
        dry_run: bool = False,
        backend: str = "bigtable",
    ):
        """Initialize the collector.

        Args:
            step_pct: Log delta percentage per step (default: 0.002% = 0.00002).
            num_steps: Number of aggregation buckets (default: 40).
            interval_sec: Collection interval in seconds.
            dry_run: If True, don't write to database.
            backend: Database backend ('bigtable' or 'sqlite').
        """
        self.symbol = "BTC/USDT"
        self.step_pct = step_pct
        self.num_steps = num_steps
        self.interval_sec = interval_sec
        self.dry_run = dry_run
        self.backend = backend

        self._running = False
        self._exchange: Optional[ccxtpro.binance] = None
        self._writer = None

        # Stats
        self.snapshots_collected = 0
        self.errors = 0

    def _init_writer(self):
        """Initialize database writer."""
        if self.dry_run:
            return

        from poly.storage.db_writer import get_db_writer

        self._writer = get_db_writer(
            backend=self.backend,
            project_id=os.getenv("BIGTABLE_PROJECT_ID"),
            instance_id=os.getenv("BIGTABLE_INSTANCE_ID"),
        )

    def _write_snapshot(self, depth: AggregatedDepth):
        """Write snapshot to database."""
        if self.dry_run or self._writer is None:
            return

        # Store aggregated data as JSON with epoch
        orderbook_json = json.dumps({
            "epoch": depth.epoch,
            "bid_buckets": depth.bid_buckets,
            "ask_buckets": depth.ask_buckets,
            "best_bid": depth.best_bid,
            "best_ask": depth.best_ask,
            "step_pct": depth.step_pct,
            "num_steps": depth.num_steps,
        })

        self._writer.write_binance_depth(
            symbol=depth.symbol.replace("/", ""),
            price=(depth.best_bid + depth.best_ask) / 2,
            orderbook_json=orderbook_json,
            ts=depth.timestamp,
            table_name=TABLE_BTC_DEPTH,
        )

    async def run(self):
        """Run the collector loop."""
        self._running = True
        self._init_writer()

        self._exchange = ccxtpro.binance()
        total_depth_pct = self.step_pct * self.num_steps * 100

        print(f"\n[COLLECTOR] Starting ccxt.pro depth collection")
        print(f"    Symbol: {self.symbol}")
        print(f"    Step: {self.step_pct*100:.4f}%")
        print(f"    Steps: {self.num_steps}")
        print(f"    Total depth: {total_depth_pct:.4f}%")
        print(f"    Interval: {self.interval_sec}s")
        print(f"    Backend: {self.backend}")
        print(f"    Dry run: {self.dry_run}")
        print()

        try:
            while self._running:
                start = time.time()
                timestamp = time.time()
                epoch = get_epoch_timestamp()
                timestamp_str = datetime.now(timezone.utc).strftime("%H:%M:%S")

                try:
                    orderbook = await self._exchange.watch_order_book(self.symbol, limit=5000)

                    if not orderbook['bids'] or not orderbook['asks']:
                        print(f"[{timestamp_str}] No orderbook data")
                        await asyncio.sleep(self.interval_sec)
                        continue

                    best_bid = orderbook['bids'][0][0]
                    best_ask = orderbook['asks'][0][0]

                    bid_buckets = aggregate_orderbook(
                        orderbook['bids'], best_bid, self.step_pct, self.num_steps
                    )
                    ask_buckets = aggregate_orderbook(
                        orderbook['asks'], best_ask, self.step_pct, self.num_steps
                    )

                    depth = AggregatedDepth(
                        symbol=self.symbol,
                        timestamp=timestamp,
                        epoch=epoch,
                        best_bid=best_bid,
                        best_ask=best_ask,
                        bid_buckets=bid_buckets,
                        ask_buckets=ask_buckets,
                        step_pct=self.step_pct,
                        num_steps=self.num_steps,
                    )

                    self._write_snapshot(depth)
                    self.snapshots_collected += 1

                    # Print status
                    elapsed = time.time() - start
                    print(f"[{timestamp_str}] ({elapsed:.2f}s) | {depth.summary()}")

                except Exception as e:
                    self.errors += 1
                    print(f"[{timestamp_str}] ERROR: {e}")

                # Sleep until next interval
                elapsed = time.time() - start
                sleep_time = max(0.1, self.interval_sec - elapsed)
                await asyncio.sleep(sleep_time)

        finally:
            if self._exchange:
                await self._exchange.close()

    async def stop(self):
        """Stop the collector."""
        self._running = False

        if self._writer:
            self._writer.close()

        print(f"\n[COLLECTOR] Stopped")
        print(f"    Snapshots: {self.snapshots_collected}")
        print(f"    Errors: {self.errors}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="CCXT.pro Binance orderbook depth collector"
    )
    parser.add_argument(
        "--step",
        type=float,
        default=0.00002,
        help="Log delta percentage per step (default: 0.00002 = 0.002%%)",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=40,
        help="Number of aggregation steps (default: 40)",
    )
    parser.add_argument(
        "--interval", "-i",
        type=float,
        default=1.0,
        help="Collection interval in seconds (default: 1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write to database, just print",
    )
    parser.add_argument(
        "--backend",
        type=str,
        choices=["sqlite", "bigtable"],
        default=os.getenv("DB_BACKEND", "bigtable"),
        help="Database backend (default: bigtable or DB_BACKEND env)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Run duration in seconds (default: indefinite)",
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    print("=" * 60)
    print("CCXT.PRO BINANCE DEPTH COLLECTOR")
    print("=" * 60)

    collector = CCXTDepthCollector(
        step_pct=args.step,
        num_steps=args.steps,
        interval_sec=args.interval,
        dry_run=args.dry_run,
        backend=args.backend,
    )

    # Handle shutdown
    loop = asyncio.get_event_loop()

    def shutdown():
        print("\n[SHUTDOWN] Stopping collector...")
        asyncio.create_task(collector.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown)

    try:
        if args.duration:
            task = asyncio.create_task(collector.run())
            await asyncio.sleep(args.duration)
            await collector.stop()
            task.cancel()
        else:
            await collector.run()
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    asyncio.run(main())
