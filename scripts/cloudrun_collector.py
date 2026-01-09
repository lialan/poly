#!/usr/bin/env python3
"""GCE collector with HTTP health endpoint.

Collects BTC and ETH prediction market data:
- BTC: 15m, 1h
- ETH: 15m, 1h, 4h

Uses Binance REST API for price data.
Stores: timestamp, market_id, price, orderbook
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

from poly.storage.db_writer import get_db_writer
from poly.api.binance import get_btc_price, get_eth_price
from poly.storage.bigtable import (
    TABLE_BTC_15M, TABLE_BTC_1H, TABLE_BTC_4H, TABLE_BTC_D1,
    TABLE_ETH_15M, TABLE_ETH_1H, TABLE_ETH_4H,
)
from poly.markets import (
    Asset,
    MarketHorizon,
    CryptoPrediction,
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
    """Configuration for a market type."""

    label: str
    table_name: str
    asset: Asset
    horizon: MarketHorizon

    async def fetch_snapshot(self, price: Decimal) -> Optional[MarketSnapshot]:
        """Fetch snapshot for this market type.

        Args:
            price: Current asset price (BTC or ETH).

        Returns:
            MarketSnapshot or None if not available.
        """
        try:
            prediction = await fetch_current_prediction(self.asset, self.horizon)
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
                spot_price=price,
                yes_bids=yes_bids,
                yes_asks=yes_asks,
                no_bids=no_bids,
                no_asks=no_asks,
            )
        except Exception as e:
            print(f"Error fetching {self.label} snapshot: {e}")
            return None

    @property
    def horizon_str(self) -> str:
        """Short horizon string (15m, 1h, 4h, d1)."""
        return {
            MarketHorizon.M15: "15m",
            MarketHorizon.H1: "1h",
            MarketHorizon.H4: "4h",
            MarketHorizon.D1: "d1",
        }[self.horizon]

    def process_snapshot(
        self,
        snapshot: Optional[MarketSnapshot],
        writer,
    ) -> tuple[Optional[str], Optional[str]]:
        """Write snapshot and return (result_str, market_id)."""
        if not snapshot:
            return None, None

        writer.write_snapshot_from_obj(snapshot, table_name=self.table_name)

        if snapshot.yes_mid:
            mid = float(snapshot.yes_mid) * 100
            result = f"{self.horizon_str}:{mid:.0f}%"
        else:
            result = f"{self.horizon_str}:OK"

        return result, snapshot.market_id


# Market type configurations
BTC_MARKETS = [
    MarketType("BTC-15m", TABLE_BTC_15M, Asset.BTC, MarketHorizon.M15),
    MarketType("BTC-1h", TABLE_BTC_1H, Asset.BTC, MarketHorizon.H1),
    MarketType("BTC-4h", TABLE_BTC_4H, Asset.BTC, MarketHorizon.H4),
    MarketType("BTC-d1", TABLE_BTC_D1, Asset.BTC, MarketHorizon.D1),
]

ETH_MARKETS = [
    MarketType("ETH-15m", TABLE_ETH_15M, Asset.ETH, MarketHorizon.M15),
    MarketType("ETH-1h", TABLE_ETH_1H, Asset.ETH, MarketHorizon.H1),
    MarketType("ETH-4h", TABLE_ETH_4H, Asset.ETH, MarketHorizon.H4),
]

ALL_MARKETS = BTC_MARKETS + ETH_MARKETS


# Collector state
collector_healthy = True
last_success_time = 0
latest_prices: dict[str, Optional[Decimal]] = {"BTC": None, "ETH": None}
latest_markets: dict[str, Optional[str]] = {}


class HealthHandler(BaseHTTPRequestHandler):
    """Simple health check handler."""

    def do_GET(self):
        if self.path == "/" or self.path == "/health":
            if collector_healthy:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                btc = latest_prices.get("BTC")
                eth = latest_prices.get("ETH")
                btc_str = f"${btc:,.0f}" if btc else "N/A"
                eth_str = f"${eth:,.0f}" if eth else "N/A"
                self.wfile.write(f"OK | BTC:{btc_str} | ETH:{eth_str}".encode())
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


async def collect_asset_markets(
    markets: list[MarketType],
    price: Decimal,
    writer,
) -> list[str]:
    """Collect all markets for an asset concurrently.

    Returns list of result strings.
    """
    # Fetch all snapshots concurrently
    snapshots = await asyncio.gather(
        *[m.fetch_snapshot(price) for m in markets],
        return_exceptions=True
    )

    results = []
    for market, snapshot in zip(markets, snapshots):
        if isinstance(snapshot, Exception):
            continue
        result, market_id = market.process_snapshot(snapshot, writer)
        if result:
            results.append(result)
            latest_markets[market.label] = market_id

    return results


async def run_collector(interval: float):
    """Run the snapshot collector loop."""
    global collector_healthy, last_success_time, latest_prices

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
    print(f"BTC markets: {', '.join(m.label for m in BTC_MARKETS)}")
    print(f"ETH markets: {', '.join(m.label for m in ETH_MARKETS)}")
    sys.stdout.flush()

    loop_count = 0
    while True:
        loop_count += 1
        start_time = time_module.time()
        timestamp = datetime.now(timezone.utc).strftime('%H:%M:%S')
        print(f"[{timestamp}] Loop {loop_count}: fetching...", end=" ", flush=True)

        try:
            # Fetch BTC and ETH prices concurrently (with individual error handling)
            btc_price_result, eth_price_result = await asyncio.gather(
                get_btc_price(),
                get_eth_price(),
                return_exceptions=True,
            )

            btc_price = btc_price_result if not isinstance(btc_price_result, Exception) else None
            eth_price = eth_price_result if not isinstance(eth_price_result, Exception) else None

            if btc_price:
                latest_prices["BTC"] = btc_price
            if eth_price:
                latest_prices["ETH"] = eth_price

            # Collect BTC and ETH markets concurrently (independent of each other)
            btc_task = collect_asset_markets(BTC_MARKETS, btc_price, writer) if btc_price else None
            eth_task = collect_asset_markets(ETH_MARKETS, eth_price, writer) if eth_price else None

            tasks = [t for t in [btc_task, eth_task] if t is not None]
            if tasks:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=FETCH_TIMEOUT,
                )
                # Map results back
                result_idx = 0
                btc_results = []
                eth_results = []
                if btc_task:
                    r = results[result_idx]
                    btc_results = r if not isinstance(r, Exception) else []
                    result_idx += 1
                if eth_task:
                    r = results[result_idx]
                    eth_results = r if not isinstance(r, Exception) else []
            else:
                btc_results = []
                eth_results = []

            # Build output
            elapsed = time_module.time() - start_time
            parts = [f"({elapsed:.1f}s)"]

            if btc_price:
                btc_str = f"${float(btc_price):,.0f}"
                btc_markets = ' '.join(btc_results) if btc_results else "none"
                parts.append(f"BTC:{btc_str} [{btc_markets}]")
            else:
                parts.append("BTC:ERR")

            if eth_price:
                eth_str = f"${float(eth_price):,.0f}"
                eth_markets = ' '.join(eth_results) if eth_results else "none"
                parts.append(f"ETH:{eth_str} [{eth_markets}]")
            else:
                parts.append("ETH:ERR")

            print(" | ".join(parts), flush=True)

            if btc_results or eth_results:
                error_count = 0
                last_success_time = time_module.time()
                collector_healthy = True

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
    print("POLYMARKET DATA COLLECTOR (BTC + ETH)")
    print("=" * 60)
    print(f"Health port: {port}")
    print(f"Collect interval: {interval}s")
    print(f"Fetch timeout: {FETCH_TIMEOUT}s")
    print(f"Price source: Binance REST API")
    print(f"BTC: {len(BTC_MARKETS)} markets")
    print(f"ETH: {len(ETH_MARKETS)} markets")
    print("=" * 60)

    health_thread = threading.Thread(target=run_health_server, args=(port,), daemon=True)
    health_thread.start()

    try:
        asyncio.run(run_collector(interval))
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()
