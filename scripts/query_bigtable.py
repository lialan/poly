#!/usr/bin/env python3
"""Query latest data from Bigtable.

Usage:
    python scripts/query_bigtable.py [--count N] [--table TABLE]
    python scripts/query_bigtable.py --status

Examples:
    python scripts/query_bigtable.py
    python scripts/query_bigtable.py --count 10
    python scripts/query_bigtable.py --table btc_15m_snapshot --count 5
    python scripts/query_bigtable.py --status
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from google.cloud import bigtable

from poly.bigtable_status import check_collection_status, print_status


def query_snapshots(
    project_id: str = "poly-collector",
    instance_id: str = "poly-data",
    table_name: str = "market_snapshots",
    count: int = 5,
    show_depth: bool = False,
):
    """Query latest snapshots from Bigtable."""
    client = bigtable.Client(project=project_id, admin=True)
    instance = client.instance(instance_id)
    table = instance.table(table_name)

    print(f"Latest {count} rows from {table_name}:")
    print("=" * 80)

    # Read rows (newest first due to inverted timestamp)
    row_count = 0
    for row in table.read_rows(limit=count):
        row_count += 1
        cells = row.cells.get("data", {})

        # Extract values
        def get_val(key: bytes) -> str:
            if key in cells:
                return cells[key][0].value.decode()
            return "N/A"

        ts = float(get_val(b"ts")) if get_val(b"ts") != "N/A" else 0
        dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None

        print(f"[{row_count}] {get_val(b'market_id')}")
        print(f"    Time:      {dt.strftime('%Y-%m-%d %H:%M:%S UTC') if dt else 'N/A'}")
        print(f"    Spot Price: ${float(get_val(b'spot_price')):,.2f}" if get_val(b"spot_price") != "N/A" else "    Spot Price: N/A")
        print(f"    YES:       bid={get_val(b'yes_bid')} / ask={get_val(b'yes_ask')}")
        print(f"    NO:        bid={get_val(b'no_bid')} / ask={get_val(b'no_ask')}")

        if show_depth and b"depth_json" in cells:
            depth = json.loads(get_val(b"depth_json"))
            print(f"    Depth YES: {len(depth.get('yes_bids', []))} bids, {len(depth.get('yes_asks', []))} asks")
            print(f"    Depth NO:  {len(depth.get('no_bids', []))} bids, {len(depth.get('no_asks', []))} asks")

        print()

    print(f"Total: {row_count} rows")


def list_tables(
    project_id: str = "poly-collector",
    instance_id: str = "poly-data",
):
    """List all tables in the Bigtable instance."""
    client = bigtable.Client(project=project_id, admin=True)
    instance = client.instance(instance_id)

    print(f"Tables in {instance_id}:")
    for table in instance.list_tables():
        print(f"  - {table.table_id}")


def main():
    parser = argparse.ArgumentParser(description="Query Bigtable data")
    parser.add_argument("--project", default="poly-collector", help="GCP project ID")
    parser.add_argument("--instance", default="poly-data", help="Bigtable instance ID")
    parser.add_argument("--table", default="btc_15m_snapshot", help="Table name")
    parser.add_argument("--count", type=int, default=5, help="Number of rows to fetch")
    parser.add_argument("--depth", action="store_true", help="Show orderbook depth info")
    parser.add_argument("--list-tables", action="store_true", help="List all tables")
    parser.add_argument("--status", action="store_true", help="Show collection status for all tables")

    args = parser.parse_args()

    if args.status:
        status = check_collection_status(args.project, args.instance)
        print_status(status)
    elif args.list_tables:
        list_tables(args.project, args.instance)
    else:
        query_snapshots(
            project_id=args.project,
            instance_id=args.instance,
            table_name=args.table,
            count=args.count,
            show_depth=args.depth,
        )


if __name__ == "__main__":
    main()
