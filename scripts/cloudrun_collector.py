#!/usr/bin/env python3
"""GCE collector with HTTP health endpoint.

Runs the snapshot collector alongside a minimal HTTP server for health checks.
Collects both 15-minute and 1-hour BTC prediction market data.
Uses Binance REST API for BTC price data.

Stores minimal snapshot data:
- timestamp, market_id, btc_price, orderbook (yes_bids, yes_asks, no_bids, no_asks)
"""

import asyncio
import os
import sys
import time as time_module
import threading
from dataclasses import dataclass
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import aiohttp

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from poly.db_writer import get_db_writer
from poly.binance_price import get_btc_price
from poly.bigtable_writer import TABLE_SNAPSHOTS_15M, TABLE_SNAPSHOTS_1H
from poly.btc_markets import (
    BTCPrediction,
    MarketHorizon,
    fetch_current_prediction,
)
from poly.market_snapshot import (
    MarketSnapshot,
    fetch_orderbook,
)

# Timeout for API calls (seconds)
FETCH_TIMEOUT = 5.0


@dataclass
class MarketType:
    """Configuration for a market type (15m or 1h)."""

    label: str
    table_name: str
    horizon: MarketHorizon

    async def fetch_snapshot(self, btc_price: Decimal) -> Optional[MarketSnapshot]:
        """Fetch snapshot for this market type.

        Args:
            btc_price: Current BTC price.

        Returns:
            MarketSnapshot or None if not available.
        """
        try:
            prediction = await fetch_current_prediction(self.horizon)
            if not prediction:
                return None

            async with aiohttp.ClientSession() as session:
                (yes_bids, yes_asks), (no_bids, no_asks) = await asyncio.gather(
                    fetch_orderbook(session, prediction.up_token_id),
                    fetch_orderbook(session, prediction.down_token_id),
                )

            return MarketSnapshot(
                timestamp=time_module.time(),
                market_id=prediction.slug,
                btc_price=btc_price,
                yes_bids=yes_bids,
                yes_asks=yes_asks,
                no_bids=no_bids,
                no_asks=no_asks,
            )
        except Exception as e:
            print(f"Error fetching {self.label} snapshot: {e}")
            return None

    def process_snapshot(
        self,
        snapshot: Optional[MarketSnapshot],
        writer,
    ) -> tuple[Optional[str], Optional[str]]:
        """Write snapshot and return (result_str, market_id).

        Args:
            snapshot: MarketSnapshot to process.
            writer: Database writer.

        Returns:
            Tuple of (result_string, market_id) or (None, None) if no snapshot.
        """
        if not snapshot:
            return None, None

        writer.write_snapshot_from_obj(snapshot, table_name=self.table_name)

        if snapshot.yes_mid:
            mid = float(snapshot.yes_mid) * 100
            result = f"{self.label}:{mid:.0f}%"
        else:
            result = f"{self.label}:OK"

        return result, snapshot.market_id


# Market type configurations
MARKET_15M = MarketType(
    label="15m",
    table_name=TABLE_SNAPSHOTS_15M,
    horizon=MarketHorizon.M15,
)

MARKET_1H = MarketType(
    label="1h",
    table_name=TABLE_SNAPSHOTS_1H,
    horizon=MarketHorizon.H1,
)

MARKET_TYPES = [MARKET_15M, MARKET_1H]


# Collector state
collector_healthy = True
last_success_time = 0
latest_btc_price: Optional[Decimal] = None
latest_markets: dict[str, Optional[str]] = {"15m": None, "1h": None}


class HealthHandler(BaseHTTPRequestHandler):
    """Simple health check handler."""

    def do_GET(self):
        if self.path == "/" or self.path == "/health":
            if collector_healthy:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                price_str = f"${latest_btc_price:,.2f}" if latest_btc_price else "N/A"
                m15 = latest_markets.get("15m")
                m1h = latest_markets.get("1h")
                m15_str = m15[-20:] if m15 else "N/A"
                m1h_str = m1h[-20:] if m1h else "N/A"
                self.wfile.write(f"OK - BTC: {price_str} | 15m: {m15_str} | 1h: {m1h_str}".encode())
            else:
                self.send_response(503)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Collector unhealthy")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def run_health_server(port: int):
    """Run HTTP health check server."""
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"Health server listening on port {port}")
    server.serve_forever()


async def run_collector(interval: float):
    """Run the snapshot collector loop."""
    global collector_healthy, last_success_time, latest_btc_price, latest_markets

    backend = os.getenv("DB_BACKEND", "bigtable")
    project_id = os.getenv("BIGTABLE_PROJECT_ID", "")
    instance_id = os.getenv("BIGTABLE_INSTANCE_ID", "")

    print(f"Starting collector with backend: {backend}")
    if backend == "bigtable":
        print(f"  Project: {project_id}")
        print(f"  Instance: {instance_id}")

    writer = get_db_writer(
        backend=backend,
        project_id=project_id,
        instance_id=instance_id,
    )

    if hasattr(writer, 'ensure_tables'):
        try:
            writer.ensure_tables()
            print("Tables verified/created")
        except Exception as e:
            print(f"Warning: Could not verify tables: {e}")

    error_count = 0

    print(f"Collection loop starting (timeout: {FETCH_TIMEOUT}s)")
    print(f"Markets: {', '.join(m.label for m in MARKET_TYPES)}")
    print("Storing: timestamp, market_id, btc_price, orderbook")
    sys.stdout.flush()

    loop_count = 0
    while True:
        loop_count += 1
        start_time = time_module.time()
        timestamp = datetime.now(timezone.utc).strftime('%H:%M:%S')
        print(f"[{timestamp}] Loop {loop_count}: fetching...", end=" ", flush=True)

        try:
            # Fetch BTC price first
            btc_price = await asyncio.wait_for(get_btc_price(), timeout=FETCH_TIMEOUT)

            if not btc_price:
                print("SKIP (no BTC price)", flush=True)
                await asyncio.sleep(interval)
                continue

            latest_btc_price = btc_price

            # Fetch all snapshots concurrently
            snapshots = await asyncio.wait_for(
                asyncio.gather(*[m.fetch_snapshot(btc_price) for m in MARKET_TYPES]),
                timeout=FETCH_TIMEOUT,
            )

            # Process each snapshot
            results = []
            for market_type, snapshot in zip(MARKET_TYPES, snapshots):
                result, market_id = market_type.process_snapshot(snapshot, writer)
                if result:
                    results.append(result)
                    latest_markets[market_type.label] = market_id

            if results:
                elapsed = time_module.time() - start_time
                btc_str = f"${float(btc_price):,.0f}"
                print(f"OK ({elapsed:.1f}s) | BTC:{btc_str} | {' | '.join(results)}", flush=True)

                error_count = 0
                last_success_time = time_module.time()
                collector_healthy = True
            else:
                print("SKIP (no data)", flush=True)

        except asyncio.TimeoutError:
            print(f"SKIP (timeout {FETCH_TIMEOUT}s)", flush=True)

        except Exception as e:
            error_count += 1
            print(f"ERROR: {type(e).__name__}: {e}", flush=True)

        if error_count >= 10:
            collector_healthy = False
            if error_count == 10:
                print(f"[{timestamp}] Marking collector unhealthy after {error_count} consecutive errors")

        query_time = time_module.time() - start_time
        sleep_time = max(0.1, interval - query_time)
        await asyncio.sleep(sleep_time)


def main():
    port = int(os.getenv("PORT", "8080"))
    interval = float(os.getenv("COLLECT_INTERVAL", "5"))

    print("=" * 60)
    print("POLYMARKET DATA COLLECTOR")
    print("=" * 60)
    print(f"Health port: {port}")
    print(f"Collect interval: {interval}s")
    print(f"Fetch timeout: {FETCH_TIMEOUT}s")
    print(f"Price source: Binance REST API")
    print(f"Markets: {', '.join(m.label for m in MARKET_TYPES)}")
    print("=" * 60)

    health_thread = threading.Thread(target=run_health_server, args=(port,), daemon=True)
    health_thread.start()

    try:
        asyncio.run(run_collector(interval))
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()
