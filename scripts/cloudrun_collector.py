#!/usr/bin/env python3
"""Cloud Run collector with HTTP health endpoint.

Runs the snapshot collector alongside a minimal HTTP server for Cloud Run health checks.
"""

import asyncio
import os
import signal
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from poly.market_snapshot import fetch_current_snapshot
from poly.db_writer import get_db_writer
from poly.chainlink_price import get_btc_price

# Collector state
collector_healthy = True
last_success_time = 0


class HealthHandler(BaseHTTPRequestHandler):
    """Simple health check handler."""

    def do_GET(self):
        if self.path == "/" or self.path == "/health":
            if collector_healthy:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"OK")
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
    global collector_healthy, last_success_time
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

    while True:
        start_time = time.time()

        try:
            # Fetch snapshot and BTC price (from Chainlink) concurrently
            snapshot, btc_price = await asyncio.gather(
                fetch_current_snapshot(),
                get_btc_price(),
            )

            if snapshot:
                btc_price_float = float(btc_price) if btc_price else 0.0
                writer.write_snapshot_from_obj(snapshot, horizon="15m", btc_price=btc_price_float)

                # Calculate real market probability
                real_yes_bid = snapshot.depth_yes_bids[-1].price if snapshot.depth_yes_bids else None
                real_yes_ask = snapshot.depth_yes_asks[-1].price if snapshot.depth_yes_asks else None
                if real_yes_bid and real_yes_ask:
                    real_mid = (float(real_yes_bid) + float(real_yes_ask)) / 2
                    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] "
                          f"{snapshot.market_id} | BTC: ${btc_price_float:,.0f} | "
                          f"Market: {real_mid*100:.1f}%")

                success_count += 1
                last_success_time = time.time()
                collector_healthy = True
            else:
                error_count += 1
                print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Failed to fetch snapshot")

        except Exception as e:
            error_count += 1
            print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Error: {e}")

            # Mark unhealthy after 5 consecutive errors
            if error_count > 5 and success_count == 0:
                collector_healthy = False

        # Calculate sleep time
        query_time = time.time() - start_time
        sleep_time = max(0.1, interval - query_time)
        await asyncio.sleep(sleep_time)


def main():
    # Get configuration from environment
    port = int(os.getenv("PORT", "8080"))
    interval = float(os.getenv("COLLECT_INTERVAL", "5"))

    print("=" * 60)
    print("POLYMARKET CLOUD RUN COLLECTOR")
    print("=" * 60)
    print(f"Health port: {port}")
    print(f"Collect interval: {interval}s")
    print("=" * 60)

    # Start health server in background thread
    health_thread = threading.Thread(target=run_health_server, args=(port,), daemon=True)
    health_thread.start()

    # Run collector in main thread
    try:
        asyncio.run(run_collector(interval))
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()
