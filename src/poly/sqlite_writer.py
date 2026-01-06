"""SQLite database writer for market data and trading simulation."""

import json
import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional, Union

DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "poly_data.db"

# Schema definitions
SCHEMA = """
CREATE TABLE IF NOT EXISTS market_snapshots (
    ts REAL,
    market_id TEXT,
    horizon TEXT,
    yes_bid REAL,
    yes_ask REAL,
    no_bid REAL,
    no_ask REAL,
    btc_price REAL,
    depth_json TEXT
);

CREATE TABLE IF NOT EXISTS opportunities (
    ts REAL,
    market_15m_id TEXT,
    market_1h_id TEXT,
    edge REAL,
    est_success_prob REAL,
    est_slippage REAL,
    eligible INTEGER
);

CREATE TABLE IF NOT EXISTS simulated_trades (
    ts_open REAL,
    ts_close REAL,
    size_usd REAL,
    quoted_edge REAL,
    delay_sec REAL,
    realized_edge REAL,
    success INTEGER,
    pnl REAL
);

CREATE TABLE IF NOT EXISTS equity_curve (
    ts REAL,
    equity REAL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON market_snapshots(ts);
CREATE INDEX IF NOT EXISTS idx_snapshots_market ON market_snapshots(market_id);
CREATE INDEX IF NOT EXISTS idx_opportunities_ts ON opportunities(ts);
CREATE INDEX IF NOT EXISTS idx_trades_ts_open ON simulated_trades(ts_open);
CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity_curve(ts);
"""


class SQLiteWriter:
    """Writer for market data and trading simulation to SQLite."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        """Initialize SQLite writer.

        Args:
            db_path: Path to SQLite database file. Defaults to poly_data.db in project root.
        """
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create database and tables if they don't exist."""
        conn = self._get_connection()
        conn.executescript(SCHEMA)
        conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "SQLiteWriter":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

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
        """Write a market snapshot.

        Args:
            market_id: Market identifier (slug or ID).
            horizon: Market horizon ('15m' or '1h').
            yes_bid: Best YES bid price.
            yes_ask: Best YES ask price.
            no_bid: Best NO bid price.
            no_ask: Best NO ask price.
            btc_price: Current BTC price from Binance.
            depth_json: JSON string of orderbook depth.
            ts: Timestamp (defaults to current time).
        """
        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO market_snapshots
            (ts, market_id, horizon, yes_bid, yes_ask, no_bid, no_ask, btc_price, depth_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts or time.time(),
                market_id,
                horizon,
                yes_bid,
                yes_ask,
                no_bid,
                no_ask,
                btc_price,
                depth_json,
            ),
        )
        conn.commit()

    def write_snapshot_from_obj(
        self, snapshot, horizon: str = "15m", btc_price: Optional[float] = None
    ) -> None:
        """Write a MarketSnapshot object to database.

        Args:
            snapshot: MarketSnapshot object.
            horizon: Market horizon ('15m' or '1h').
            btc_price: Current BTC price from Binance.
        """
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
        """Write a trading opportunity.

        Args:
            market_15m_id: 15-minute market ID.
            market_1h_id: 1-hour market ID.
            edge: Calculated edge.
            est_success_prob: Estimated success probability.
            est_slippage: Estimated slippage.
            eligible: Whether opportunity is eligible for trading.
            ts: Timestamp (defaults to current time).
        """
        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO opportunities
            (ts, market_15m_id, market_1h_id, edge, est_success_prob, est_slippage, eligible)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts or time.time(),
                market_15m_id,
                market_1h_id,
                edge,
                est_success_prob,
                est_slippage,
                1 if eligible else 0,
            ),
        )
        conn.commit()

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
        """Write a simulated trade.

        Args:
            ts_open: Trade open timestamp.
            ts_close: Trade close timestamp.
            size_usd: Trade size in USD.
            quoted_edge: Edge at time of quote.
            delay_sec: Execution delay in seconds.
            realized_edge: Actual realized edge.
            success: Whether trade was successful.
            pnl: Profit/loss in USD.
        """
        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO simulated_trades
            (ts_open, ts_close, size_usd, quoted_edge, delay_sec, realized_edge, success, pnl)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts_open,
                ts_close,
                size_usd,
                quoted_edge,
                delay_sec,
                realized_edge,
                1 if success else 0,
                pnl,
            ),
        )
        conn.commit()

    # --- Equity Curve ---

    def write_equity(self, equity: float, ts: Optional[float] = None) -> None:
        """Write equity curve point.

        Args:
            equity: Current equity value.
            ts: Timestamp (defaults to current time).
        """
        conn = self._get_connection()
        conn.execute(
            "INSERT INTO equity_curve (ts, equity) VALUES (?, ?)",
            (ts or time.time(), equity),
        )
        conn.commit()

    # --- Query Methods ---

    def get_snapshots(
        self,
        market_id: Optional[str] = None,
        horizon: Optional[str] = None,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Query market snapshots.

        Args:
            market_id: Filter by market ID.
            horizon: Filter by horizon ('15m' or '1h').
            start_ts: Start timestamp.
            end_ts: End timestamp.
            limit: Maximum rows to return.

        Returns:
            List of snapshot dictionaries.
        """
        conn = self._get_connection()
        query = "SELECT * FROM market_snapshots WHERE 1=1"
        params = []

        if market_id:
            query += " AND market_id = ?"
            params.append(market_id)
        if horizon:
            query += " AND horizon = ?"
            params.append(horizon)
        if start_ts:
            query += " AND ts >= ?"
            params.append(start_ts)
        if end_ts:
            query += " AND ts <= ?"
            params.append(end_ts)

        query += f" ORDER BY ts DESC LIMIT {limit}"

        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_opportunities(
        self,
        eligible_only: bool = False,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Query opportunities."""
        conn = self._get_connection()
        query = "SELECT * FROM opportunities WHERE 1=1"
        params = []

        if eligible_only:
            query += " AND eligible = 1"
        if start_ts:
            query += " AND ts >= ?"
            params.append(start_ts)
        if end_ts:
            query += " AND ts <= ?"
            params.append(end_ts)

        query += f" ORDER BY ts DESC LIMIT {limit}"

        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_trades(
        self,
        success_only: bool = False,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Query simulated trades."""
        conn = self._get_connection()
        query = "SELECT * FROM simulated_trades WHERE 1=1"
        params = []

        if success_only:
            query += " AND success = 1"
        if start_ts:
            query += " AND ts_open >= ?"
            params.append(start_ts)
        if end_ts:
            query += " AND ts_open <= ?"
            params.append(end_ts)

        query += f" ORDER BY ts_open DESC LIMIT {limit}"

        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_equity_curve(
        self,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
    ) -> list[dict]:
        """Query equity curve."""
        conn = self._get_connection()
        query = "SELECT * FROM equity_curve WHERE 1=1"
        params = []

        if start_ts:
            query += " AND ts >= ?"
            params.append(start_ts)
        if end_ts:
            query += " AND ts <= ?"
            params.append(end_ts)

        query += " ORDER BY ts ASC"

        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_stats(self) -> dict:
        """Get database statistics."""
        conn = self._get_connection()

        stats = {}
        for table in ["market_snapshots", "opportunities", "simulated_trades", "equity_curve"]:
            cursor = conn.execute(f"SELECT COUNT(*) as count FROM {table}")
            stats[table] = cursor.fetchone()["count"]

        return stats
