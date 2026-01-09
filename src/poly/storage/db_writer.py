"""Unified database writer interface.

Provides a common interface for SQLite (local) and Bigtable (cloud) storage.

Usage:
    # Use SQLite (default)
    writer = get_db_writer()

    # Use SQLite with custom path
    writer = get_db_writer(backend="sqlite", sqlite_path="my_data.db")

    # Use Bigtable
    writer = get_db_writer(
        backend="bigtable",
        project_id="my-project",
        instance_id="my-instance"
    )

    # Use Bigtable from environment variables
    # Set BIGTABLE_PROJECT_ID and BIGTABLE_INSTANCE_ID
    writer = get_db_writer(backend="bigtable")
"""

import os
from typing import Optional, Union, Protocol, runtime_checkable

from .sqlite import SQLiteWriter


@runtime_checkable
class DBWriter(Protocol):
    """Protocol defining the database writer interface."""

    def write_snapshot(
        self,
        market_id: str,
        horizon: str,
        yes_bid: Optional[float],
        yes_ask: Optional[float],
        no_bid: Optional[float],
        no_ask: Optional[float],
        btc_price: Optional[float] = None,
        depth_json: Optional[str] = None,
        ts: Optional[float] = None,
    ) -> None: ...

    def write_snapshot_from_obj(
        self, snapshot, horizon: str = "15m", btc_price: Optional[float] = None
    ) -> None: ...

    def write_opportunity(
        self,
        market_15m_id: str,
        market_1h_id: str,
        edge: float,
        est_success_prob: float,
        est_slippage: float,
        eligible: bool,
        ts: Optional[float] = None,
    ) -> None: ...

    def write_trade(
        self,
        ts_open: float,
        ts_close: float,
        size_usd: float,
        quoted_edge: float,
        delay_sec: float,
        realized_edge: float,
        success: bool,
        pnl: float,
    ) -> None: ...

    def write_equity(self, equity: float, ts: Optional[float] = None) -> None: ...

    def get_snapshots(
        self,
        market_id: Optional[str] = None,
        horizon: Optional[str] = None,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
        limit: int = 1000,
    ) -> list[dict]: ...

    def get_opportunities(
        self,
        eligible_only: bool = False,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
        limit: int = 1000,
    ) -> list[dict]: ...

    def get_trades(
        self,
        success_only: bool = False,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
        limit: int = 1000,
    ) -> list[dict]: ...

    def get_equity_curve(
        self,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
    ) -> list[dict]: ...

    def get_stats(self) -> dict: ...

    def close(self) -> None: ...


def get_db_writer(
    backend: str = "sqlite",
    sqlite_path: Optional[str] = None,
    project_id: Optional[str] = None,
    instance_id: Optional[str] = None,
) -> DBWriter:
    """Create a database writer instance.

    Args:
        backend: "sqlite" or "bigtable"
        sqlite_path: Path to SQLite database (for sqlite backend)
        project_id: GCP project ID (for bigtable backend)
        instance_id: Bigtable instance ID (for bigtable backend)

    Returns:
        A database writer instance implementing DBWriter protocol.

    Environment variables (for bigtable):
        BIGTABLE_PROJECT_ID: GCP project ID
        BIGTABLE_INSTANCE_ID: Bigtable instance ID
        DB_BACKEND: Default backend ("sqlite" or "bigtable")
    """
    # Check environment for default backend
    backend = os.getenv("DB_BACKEND", backend)

    if backend == "sqlite":
        return SQLiteWriter(sqlite_path)

    elif backend == "bigtable":
        from .bigtable import BigtableWriter

        writer = BigtableWriter(
            project_id=project_id or os.getenv("BIGTABLE_PROJECT_ID"),
            instance_id=instance_id or os.getenv("BIGTABLE_INSTANCE_ID"),
        )
        writer.ensure_tables()
        return writer

    else:
        raise ValueError(f"Unknown backend: {backend}. Use 'sqlite' or 'bigtable'.")
