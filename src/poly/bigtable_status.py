"""Bigtable collection status checker.

Queries latest snapshots from Bigtable tables to verify
data collection is running and up-to-date.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from google.cloud import bigtable


# All snapshot tables
SNAPSHOT_TABLES = [
    "btc_15m_snapshot",
    "btc_1h_snapshot",
    "btc_4h_snapshot",
    "btc_d1_snapshot",
    "eth_15m_snapshot",
    "eth_1h_snapshot",
    "eth_4h_snapshot",
]


@dataclass
class TableStatus:
    """Status of a single Bigtable table."""

    table_name: str
    latest_timestamp: Optional[datetime]
    row_count: int
    age_seconds: Optional[float]

    @property
    def is_healthy(self) -> bool:
        """Check if data is recent (within 60 seconds)."""
        if self.age_seconds is None:
            return False
        return self.age_seconds < 60

    @property
    def status_emoji(self) -> str:
        """Get status emoji."""
        if self.age_seconds is None:
            return "?"
        if self.age_seconds < 30:
            return "OK"
        if self.age_seconds < 60:
            return "OK"
        if self.age_seconds < 300:
            return "WARN"
        return "STALE"

    @property
    def age_str(self) -> str:
        """Human-readable age string."""
        if self.age_seconds is None:
            return "no data"
        if self.age_seconds < 60:
            return f"{self.age_seconds:.0f}s ago"
        if self.age_seconds < 3600:
            return f"{self.age_seconds / 60:.0f}m ago"
        return f"{self.age_seconds / 3600:.1f}h ago"


@dataclass
class CollectionStatus:
    """Overall collection status across all tables."""

    tables: list[TableStatus]
    check_time: datetime

    @property
    def healthy_count(self) -> int:
        """Number of healthy tables."""
        return sum(1 for t in self.tables if t.is_healthy)

    @property
    def total_count(self) -> int:
        """Total number of tables."""
        return len(self.tables)

    @property
    def is_healthy(self) -> bool:
        """Check if all tables are healthy."""
        return self.healthy_count == self.total_count

    @property
    def summary(self) -> str:
        """One-line summary of collection status."""
        if not self.tables:
            return "No tables found"

        healthy = self.healthy_count
        total = self.total_count

        if healthy == total:
            return f"All {total} tables OK"
        elif healthy == 0:
            return f"All {total} tables STALE"
        else:
            return f"{healthy}/{total} tables OK"


def get_table_status(
    table,
    table_name: str,
    count: int = 5,
) -> TableStatus:
    """Get status for a single table."""
    now = datetime.now(timezone.utc)
    latest_ts = None
    row_count = 0

    try:
        for row in table.read_rows(limit=count):
            row_count += 1
            cells = row.cells.get("data", {})

            if b"ts" in cells:
                ts = float(cells[b"ts"][0].value.decode())
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                if latest_ts is None or dt > latest_ts:
                    latest_ts = dt
    except Exception:
        pass

    age_seconds = None
    if latest_ts:
        age_seconds = (now - latest_ts).total_seconds()

    return TableStatus(
        table_name=table_name,
        latest_timestamp=latest_ts,
        row_count=row_count,
        age_seconds=age_seconds,
    )


def check_collection_status(
    project_id: str = "poly-collector",
    instance_id: str = "poly-data",
    tables: Optional[list[str]] = None,
) -> CollectionStatus:
    """Check collection status across all tables.

    Args:
        project_id: GCP project ID
        instance_id: Bigtable instance ID
        tables: List of tables to check (default: all snapshot tables)

    Returns:
        CollectionStatus with status for each table
    """
    if tables is None:
        tables = SNAPSHOT_TABLES

    client = bigtable.Client(project=project_id, admin=True)
    instance = client.instance(instance_id)

    table_statuses = []
    for table_name in tables:
        table = instance.table(table_name)
        status = get_table_status(table, table_name)
        table_statuses.append(status)

    return CollectionStatus(
        tables=table_statuses,
        check_time=datetime.now(timezone.utc),
    )


def print_status(status: CollectionStatus) -> None:
    """Print collection status to console."""
    print(f"\n  BIGTABLE COLLECTION STATUS")
    print(f"  {'─' * 50}")
    print(f"  Checked at: {status.check_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  Summary: {status.summary}")
    print()

    # Group by asset
    btc_tables = [t for t in status.tables if t.table_name.startswith("btc_")]
    eth_tables = [t for t in status.tables if t.table_name.startswith("eth_")]

    for asset, tables in [("BTC", btc_tables), ("ETH", eth_tables)]:
        if tables:
            print(f"  {asset}:")
            for t in tables:
                horizon = t.table_name.split("_")[1]  # e.g., "15m" from "btc_15m_snapshot"
                print(f"    {horizon:4s} [{t.status_emoji:5s}] {t.age_str}")
    print()
