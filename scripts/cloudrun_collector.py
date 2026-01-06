#!/usr/bin/env python3
"""Cloud Run / GCE collector with HTTP health endpoint.

Runs the snapshot collector alongside a minimal HTTP server for health checks.
Uses Binance REST API for BTC price data.
"""

import asyncio
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from decimal import Decimal
from typing import Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from poly.market_snapshot import fetch_current_snapshot
from poly.db_writer import get_db_writer
from poly.binance_price import get_btc_price

# Collector state
collector_healthy = True
last_success_time = 0
latest_btc_price: Optional[Decimal] = None

# Timeout for API calls (seconds)
FETCH_TIMEOUT = 5.0


class HealthHandler(BaseHTTPRequestHandler):
    """Simple health check handler."""

    def do_GET(self):
        if self.path == "/" or self.path == "/health":
            if collector_healthy:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                price_str = f"${latest_btc_price:,.2f}" if latest_btc_price else "N/A"
                self.wfile.write(f"OK - BTC: {price_str}".encode())
            else:
                self.send_response(503)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Collector unhealthy")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress HTTP logs
        pass


def run_health_server(port: int):
    """Run HTTP health check server."""
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"Health server listening on port {port}")
    server.serve_forever()


async def run_collector(interval: float):
    """Run the snapshot collector loop."""
    global collector_healthy, last_success_time, latest_btc_price
    import time
    from datetime import datetime, timezone

    # Get configuration from environment
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

    success_count = 0
    error_count = 0

    print(f"Collection loop starting (timeout: {FETCH_TIMEOUT}s)")
    sys.stdout.flush()

    loop_count = 0
    while True:
        loop_count += 1
        start_time = time.time()
        timestamp = datetime.now(timezone.utc).strftime('%H:%M:%S')
        print(f"[{timestamp}] Loop {loop_count}: fetching...", end=" ", flush=True)

        try:
            # Fetch snapshot and BTC price concurrently with timeout
            snapshot, btc_price = await asyncio.wait_for(
                asyncio.gather(
                    fetch_current_snapshot(),
                    get_btc_price(),
                ),
                timeout=FETCH_TIMEOUT,
            )

            if snapshot and btc_price:
                latest_btc_price = btc_price
                btc_price_float = float(btc_price)
                writer.write_snapshot_from_obj(snapshot, horizon="15m", btc_price=btc_price_float)

                # Calculate real market probability
                real_yes_bid = snapshot.depth_yes_bids[-1].price if snapshot.depth_yes_bids else None
                real_yes_ask = snapshot.depth_yes_asks[-1].price if snapshot.depth_yes_asks else None
                if real_yes_bid and real_yes_ask:
                    real_mid = (float(real_yes_bid) + float(real_yes_ask)) / 2
                    elapsed = time.time() - start_time
                    print(f"OK ({elapsed:.1f}s) | {snapshot.market_id} | BTC: ${btc_price_float:,.0f} | "
                          f"Market: {real_mid*100:.1f}%", flush=True)
                else:
                    elapsed = time.time() - start_time
                    print(f"OK ({elapsed:.1f}s) | {snapshot.market_id} | BTC: ${btc_price_float:,.0f}", flush=True)

                success_count += 1
                error_count = 0  # Reset consecutive errors on success
                last_success_time = time.time()
                collector_healthy = True
            else:
                print("SKIP (no data)", flush=True)

        except asyncio.TimeoutError:
            print(f"SKIP (timeout {FETCH_TIMEOUT}s)", flush=True)

        except Exception as e:
            error_count += 1
            print(f"ERROR: {type(e).__name__}: {e}", flush=True)

        # Mark unhealthy after 10 consecutive errors
        if error_count >= 10:
            collector_healthy = False
            if error_count == 10:
                print(f"[{timestamp}] Marking collector unhealthy after {error_count} consecutive errors")

        # Calculate sleep time to maintain interval
        query_time = time.time() - start_time
        sleep_time = max(0.1, interval - query_time)
        await asyncio.sleep(sleep_time)


def main():
    # Get configuration from environment
    port = int(os.getenv("PORT", "8080"))
    interval = float(os.getenv("COLLECT_INTERVAL", "5"))

    print("=" * 60)
    print("POLYMARKET DATA COLLECTOR")
    print("=" * 60)
    print(f"Health port: {port}")
    print(f"Collect interval: {interval}s")
    print(f"Fetch timeout: {FETCH_TIMEOUT}s")
    print(f"Price source: Binance REST API")
    print("=" * 60)

    # Start health server in background thread
    health_thread = threading.Thread(target=run_health_server, args=(port,), daemon=True)
    health_thread.start()

    # Run collector
    try:
        asyncio.run(run_collector(interval))
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()
