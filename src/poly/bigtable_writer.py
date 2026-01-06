"""Google Cloud Bigtable writer for market data and trading simulation.

This module mirrors the SQLiteWriter interface but uses Bigtable for storage.

Requires:
    pip install google-cloud-bigtable

Environment variables:
    GOOGLE_APPLICATION_CREDENTIALS: Path to service account JSON file
    BIGTABLE_PROJECT_ID: GCP project ID
    BIGTABLE_INSTANCE_ID: Bigtable instance ID
"""

import json
import os
import struct
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

from google.cloud import bigtable
from google.cloud.bigtable import column_family, row_filters

# Table names
TABLE_SNAPSHOTS = "market_snapshots"
TABLE_OPPORTUNITIES = "opportunities"
TABLE_TRADES = "simulated_trades"
TABLE_EQUITY = "equity_curve"

# Column family
CF_DATA = "data"

# Default TTL (30 days in seconds)
DEFAULT_TTL_SECONDS = 30 * 24 * 60 * 60


@dataclass
class BigtableConfig:
    """Configuration for Bigtable connection."""

    project_id: str
    instance_id: str

    @classmethod
    def from_env(cls) -> "BigtableConfig":
        """Load config from environment variables."""
        project_id = os.getenv("BIGTABLE_PROJECT_ID", "")
        instance_id = os.getenv("BIGTABLE_INSTANCE_ID", "")

        if not project_id or not instance_id:
            raise ValueError(
                "BIGTABLE_PROJECT_ID and BIGTABLE_INSTANCE_ID must be set"
            )

        return cls(project_id=project_id, instance_id=instance_id)


class BigtableWriter:
    """Writer for market data and trading simulation to Google Cloud Bigtable."""

    def __init__(
        self,
        project_id: Optional[str] = None,
        instance_id: Optional[str] = None,
        config: Optional[BigtableConfig] = None,
    ):
        """Initialize Bigtable writer.

        Args:
            project_id: GCP project ID (or use config/env).
            instance_id: Bigtable instance ID (or use config/env).
            config: BigtableConfig object (overrides project_id/instance_id).
        """
        if config:
            self.project_id = config.project_id
            self.instance_id = config.instance_id
        elif project_id and instance_id:
            self.project_id = project_id
            self.instance_id = instance_id
        else:
            cfg = BigtableConfig.from_env()
            self.project_id = cfg.project_id
            self.instance_id = cfg.instance_id

        self._client: Optional[bigtable.Client] = None
        self._instance: Optional[bigtable.Instance] = None
        self._tables: dict = {}

    def _get_client(self) -> bigtable.Client:
        """Get or create Bigtable client."""
        if self._client is None:
            self._client = bigtable.Client(project=self.project_id, admin=True)
            self._instance = self._client.instance(self.instance_id)
        return self._client

    def _get_table(self, table_name: str):
        """Get or create table reference."""
        if table_name not in self._tables:
            self._get_client()
            self._tables[table_name] = self._instance.table(table_name)
        return self._tables[table_name]

    def ensure_tables(self) -> None:
        """Create tables if they don't exist."""
        self._get_client()

        tables_to_create = [
            TABLE_SNAPSHOTS,
            TABLE_OPPORTUNITIES,
            TABLE_TRADES,
            TABLE_EQUITY,
        ]

        existing_tables = self._instance.list_tables()
        existing_names = {t.table_id for t in existing_tables}

        for table_name in tables_to_create:
            if table_name not in existing_names:
                table = self._instance.table(table_name)
                table.create()
                cf = table.column_family(
                    CF_DATA,
                    gc_rule=column_family.MaxAgeGCRule(
                        timedelta(seconds=DEFAULT_TTL_SECONDS)
                    ),
                )
                cf.create()
                print(f"Created table: {table_name}")

    def close(self) -> None:
        """Close Bigtable connection."""
        if self._client:
            self._client.close()
            self._client = None
            self._instance = None
            self._tables = {}

    def __enter__(self) -> "BigtableWriter":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @staticmethod
    def _ts_to_bytes(ts: float) -> bytes:
        """Convert timestamp to bytes for row key (big-endian for sorting)."""
        # Use inverted timestamp for reverse chronological order
        inverted = 9999999999.999999 - ts
        return struct.pack(">d", inverted)

    @staticmethod
    def _bytes_to_ts(b: bytes) -> float:
        """Convert bytes back to timestamp."""
        inverted = struct.unpack(">d", b)[0]
        return 9999999999.999999 - inverted

    @staticmethod
    def _encode_value(value) -> bytes:
        """Encode a value to bytes."""
        if value is None:
            return b""
        if isinstance(value, bool):
            return b"1" if value else b"0"
        if isinstance(value, (int, float)):
            return str(value).encode("utf-8")
        if isinstance(value, str):
            return value.encode("utf-8")
        return str(value).encode("utf-8")

    @staticmethod
    def _decode_value(b: bytes, dtype: type = str):
        """Decode bytes to a value."""
        if not b:
            return None
        s = b.decode("utf-8")
        if dtype == float:
            return float(s)
        if dtype == int:
            return int(s)
        if dtype == bool:
            return s == "1"
        return s

    # --- Market Snapshots ---

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
    ) -> None:
        """Write a market snapshot."""
        ts = ts or time.time()
        table = self._get_table(TABLE_SNAPSHOTS)

        # Row key: inverted_timestamp#market_id (for reverse chronological order)
        row_key = self._ts_to_bytes(ts) + b"#" + market_id.encode("utf-8")

        row = table.direct_row(row_key)
        row.set_cell(CF_DATA, b"ts", self._encode_value(ts))
        row.set_cell(CF_DATA, b"market_id", self._encode_value(market_id))
        row.set_cell(CF_DATA, b"horizon", self._encode_value(horizon))
        row.set_cell(CF_DATA, b"yes_bid", self._encode_value(yes_bid))
        row.set_cell(CF_DATA, b"yes_ask", self._encode_value(yes_ask))
        row.set_cell(CF_DATA, b"no_bid", self._encode_value(no_bid))
        row.set_cell(CF_DATA, b"no_ask", self._encode_value(no_ask))
        row.set_cell(CF_DATA, b"btc_price", self._encode_value(btc_price))
        row.set_cell(CF_DATA, b"depth_json", self._encode_value(depth_json))
        row.commit()

    def write_snapshot_from_obj(
        self, snapshot, horizon: str = "15m", btc_price: Optional[float] = None
    ) -> None:
        """Write a MarketSnapshot object to database."""
        depth_data = {
            "yes_bids": [(float(l.price), float(l.size)) for l in snapshot.depth_yes_bids],
            "yes_asks": [(float(l.price), float(l.size)) for l in snapshot.depth_yes_asks],
            "no_bids": [(float(l.price), float(l.size)) for l in snapshot.depth_no_bids],
            "no_asks": [(float(l.price), float(l.size)) for l in snapshot.depth_no_asks],
        }

        self.write_snapshot(
            market_id=snapshot.market_id,
            horizon=horizon,
            yes_bid=float(snapshot.best_yes_bid) if snapshot.best_yes_bid else None,
            yes_ask=float(snapshot.best_yes_ask) if snapshot.best_yes_ask else None,
            no_bid=float(snapshot.best_no_bid) if snapshot.best_no_bid else None,
            no_ask=float(snapshot.best_no_ask) if snapshot.best_no_ask else None,
            btc_price=btc_price,
            depth_json=json.dumps(depth_data),
            ts=snapshot.timestamp,
        )

    # --- Opportunities ---

    def write_opportunity(
        self,
        market_15m_id: str,
        market_1h_id: str,
        edge: float,
        est_success_prob: float,
        est_slippage: float,
        eligible: bool,
        ts: Optional[float] = None,
    ) -> None:
        """Write a trading opportunity."""
        ts = ts or time.time()
        table = self._get_table(TABLE_OPPORTUNITIES)

        row_key = self._ts_to_bytes(ts) + b"#" + market_15m_id.encode("utf-8")

        row = table.direct_row(row_key)
        row.set_cell(CF_DATA, b"ts", self._encode_value(ts))
        row.set_cell(CF_DATA, b"market_15m_id", self._encode_value(market_15m_id))
        row.set_cell(CF_DATA, b"market_1h_id", self._encode_value(market_1h_id))
        row.set_cell(CF_DATA, b"edge", self._encode_value(edge))
        row.set_cell(CF_DATA, b"est_success_prob", self._encode_value(est_success_prob))
        row.set_cell(CF_DATA, b"est_slippage", self._encode_value(est_slippage))
        row.set_cell(CF_DATA, b"eligible", self._encode_value(eligible))
        row.commit()

    # --- Simulated Trades ---

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
    ) -> None:
        """Write a simulated trade."""
        table = self._get_table(TABLE_TRADES)

        # Use ts_open + uuid for unique row key
        trade_id = str(uuid.uuid4())[:8]
        row_key = self._ts_to_bytes(ts_open) + b"#" + trade_id.encode("utf-8")

        row = table.direct_row(row_key)
        row.set_cell(CF_DATA, b"ts_open", self._encode_value(ts_open))
        row.set_cell(CF_DATA, b"ts_close", self._encode_value(ts_close))
        row.set_cell(CF_DATA, b"size_usd", self._encode_value(size_usd))
        row.set_cell(CF_DATA, b"quoted_edge", self._encode_value(quoted_edge))
        row.set_cell(CF_DATA, b"delay_sec", self._encode_value(delay_sec))
        row.set_cell(CF_DATA, b"realized_edge", self._encode_value(realized_edge))
        row.set_cell(CF_DATA, b"success", self._encode_value(success))
        row.set_cell(CF_DATA, b"pnl", self._encode_value(pnl))
        row.commit()

    # --- Equity Curve ---

    def write_equity(self, equity: float, ts: Optional[float] = None) -> None:
        """Write equity curve point."""
        ts = ts or time.time()
        table = self._get_table(TABLE_EQUITY)

        row_key = self._ts_to_bytes(ts)

        row = table.direct_row(row_key)
        row.set_cell(CF_DATA, b"ts", self._encode_value(ts))
        row.set_cell(CF_DATA, b"equity", self._encode_value(equity))
        row.commit()

    # --- Query Methods ---

    def _parse_row(self, row, columns: dict) -> dict:
        """Parse a Bigtable row into a dictionary."""
        result = {}
        cells = row.cells.get(CF_DATA, {})

        for col_name, dtype in columns.items():
            col_key = col_name.encode("utf-8")
            if col_key in cells and cells[col_key]:
                value = cells[col_key][0].value
                result[col_name] = self._decode_value(value, dtype)
            else:
                result[col_name] = None

        return result

    def get_snapshots(
        self,
        market_id: Optional[str] = None,
        horizon: Optional[str] = None,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Query market snapshots."""
        table = self._get_table(TABLE_SNAPSHOTS)

        columns = {
            "ts": float,
            "market_id": str,
            "horizon": str,
            "yes_bid": float,
            "yes_ask": float,
            "no_bid": float,
            "no_ask": float,
            "btc_price": float,
            "depth_json": str,
        }

        # Build row key range for time filtering
        if end_ts:
            start_key = self._ts_to_bytes(end_ts)
        else:
            start_key = b""

        if start_ts:
            end_key = self._ts_to_bytes(start_ts)
        else:
            end_key = b"\xff" * 8

        rows = table.read_rows(start_key=start_key, end_key=end_key, limit=limit)

        results = []
        for row in rows:
            data = self._parse_row(row, columns)

            # Apply filters
            if market_id and data.get("market_id") != market_id:
                continue
            if horizon and data.get("horizon") != horizon:
                continue

            results.append(data)

            if len(results) >= limit:
                break

        return results

    def get_opportunities(
        self,
        eligible_only: bool = False,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Query opportunities."""
        table = self._get_table(TABLE_OPPORTUNITIES)

        columns = {
            "ts": float,
            "market_15m_id": str,
            "market_1h_id": str,
            "edge": float,
            "est_success_prob": float,
            "est_slippage": float,
            "eligible": bool,
        }

        if end_ts:
            start_key = self._ts_to_bytes(end_ts)
        else:
            start_key = b""

        if start_ts:
            end_key = self._ts_to_bytes(start_ts)
        else:
            end_key = b"\xff" * 8

        rows = table.read_rows(start_key=start_key, end_key=end_key, limit=limit)

        results = []
        for row in rows:
            data = self._parse_row(row, columns)

            if eligible_only and not data.get("eligible"):
                continue

            results.append(data)

            if len(results) >= limit:
                break

        return results

    def get_trades(
        self,
        success_only: bool = False,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Query simulated trades."""
        table = self._get_table(TABLE_TRADES)

        columns = {
            "ts_open": float,
            "ts_close": float,
            "size_usd": float,
            "quoted_edge": float,
            "delay_sec": float,
            "realized_edge": float,
            "success": bool,
            "pnl": float,
        }

        if end_ts:
            start_key = self._ts_to_bytes(end_ts)
        else:
            start_key = b""

        if start_ts:
            end_key = self._ts_to_bytes(start_ts)
        else:
            end_key = b"\xff" * 8

        rows = table.read_rows(start_key=start_key, end_key=end_key, limit=limit)

        results = []
        for row in rows:
            data = self._parse_row(row, columns)

            if success_only and not data.get("success"):
                continue

            results.append(data)

            if len(results) >= limit:
                break

        return results

    def get_equity_curve(
        self,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
    ) -> list[dict]:
        """Query equity curve."""
        table = self._get_table(TABLE_EQUITY)

        columns = {
            "ts": float,
            "equity": float,
        }

        if end_ts:
            start_key = self._ts_to_bytes(end_ts)
        else:
            start_key = b""

        if start_ts:
            end_key = self._ts_to_bytes(start_ts)
        else:
            end_key = b"\xff" * 8

        rows = table.read_rows(start_key=start_key, end_key=end_key)

        results = []
        for row in rows:
            data = self._parse_row(row, columns)
            results.append(data)

        # Reverse to get chronological order
        return list(reversed(results))

    def get_stats(self) -> dict:
        """Get approximate row counts for each table."""
        stats = {}

        for table_name in [TABLE_SNAPSHOTS, TABLE_OPPORTUNITIES, TABLE_TRADES, TABLE_EQUITY]:
            try:
                table = self._get_table(table_name)
                # Count rows (limited scan for performance)
                count = sum(1 for _ in table.read_rows(limit=10000))
                stats[table_name] = count
            except Exception:
                stats[table_name] = 0

        return stats
