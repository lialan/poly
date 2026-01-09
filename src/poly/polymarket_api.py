"""
Polymarket API Client

Provides interfaces for interacting with Polymarket APIs:
- Data API: Read-only queries for positions, markets, activity, trades
- CLOB API: Order book data and trading (requires py-clob-client for trading)
- Gamma API: Public event and market data

For trading operations, install py-clob-client:
    pip install py-clob-client

For more comprehensive features, consider polymarket-apis:
    pip install polymarket-apis
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Optional, TypeVar
from urllib.parse import urlencode

import aiohttp

from poly.polymarket_config import PolymarketConfig

# TypeVar for generic return type in sync wrapper
T = TypeVar("T")


# =============================================================================
# Enums for Order and Trade Status
# =============================================================================

class OrderStatus(str, Enum):
    """Order status states in Polymarket CLOB."""
    LIVE = "LIVE"           # Order is active in the order book
    MATCHED = "MATCHED"     # Order has been fully matched
    CANCELLED = "CANCELLED" # Order was cancelled
    DELAYED = "DELAYED"     # Order is delayed (being processed)


class TradeStatus(str, Enum):
    """Trade status states for on-chain settlement."""
    MATCHED = "MATCHED"     # Trade matched, sent to executor service
    MINED = "MINED"         # Trade observed on-chain, no finality yet
    CONFIRMED = "CONFIRMED" # Trade has strong probabilistic finality
    RETRYING = "RETRYING"   # Transaction failed, being resubmitted
    FAILED = "FAILED"       # Trade failed, no retry


class MarketStatus(str, Enum):
    """Market resolution status."""
    ACTIVE = "active"       # Market is open for trading
    RESOLVED = "resolved"   # Market has been resolved
    CLOSED = "closed"       # Market is closed (no more trading)


class OrderSide(str, Enum):
    """Order side for trading."""
    BUY = "BUY"
    SELL = "SELL"


class OrderTimeInForce(str, Enum):
    """Time in force for orders."""
    GTC = "GTC"  # Good Till Cancelled
    GTD = "GTD"  # Good Till Day
    FOK = "FOK"  # Fill Or Kill
    FAK = "FAK"  # Fill And Kill (Immediate or Cancel)


# =============================================================================
# Trading Exceptions
# =============================================================================

class TradingError(Exception):
    """Exception raised for trading-related errors."""
    pass


class TradingNotConfiguredError(TradingError):
    """Exception raised when trading is attempted without proper credentials."""
    pass


# =============================================================================
# Order Result Dataclass
# =============================================================================

@dataclass
class OrderResult:
    """Result of an order placement.

    Attributes:
        order_id: The CLOB order ID assigned to this order
        success: Whether the order was successfully placed
        submission_time_ms: Time taken to submit the order in milliseconds
        error_message: Error message if order failed (None if success)
        token_id: The token ID that was traded
        side: BUY or SELL
        price: Order price
        size: Order size
        time_in_force: Order time in force (GTC, GTD, FOK, FAK)
        timestamp: When the order was submitted (UTC)
    """
    order_id: Optional[str]
    success: bool
    submission_time_ms: float
    error_message: Optional[str]
    token_id: str
    side: OrderSide
    price: float
    size: float
    time_in_force: OrderTimeInForce
    timestamp: datetime

    @classmethod
    def from_success(
        cls,
        order_id: str,
        token_id: str,
        side: OrderSide,
        price: float,
        size: float,
        time_in_force: OrderTimeInForce,
        submission_time_ms: float,
    ) -> "OrderResult":
        """Create a successful order result."""
        return cls(
            order_id=order_id,
            success=True,
            submission_time_ms=submission_time_ms,
            error_message=None,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            time_in_force=time_in_force,
            timestamp=datetime.now(timezone.utc),
        )

    @classmethod
    def from_error(
        cls,
        error_message: str,
        token_id: str,
        side: OrderSide,
        price: float,
        size: float,
        time_in_force: OrderTimeInForce,
        submission_time_ms: float,
    ) -> "OrderResult":
        """Create a failed order result."""
        return cls(
            order_id=None,
            success=False,
            submission_time_ms=submission_time_ms,
            error_message=error_message,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            time_in_force=time_in_force,
            timestamp=datetime.now(timezone.utc),
        )

    def __str__(self) -> str:
        if self.success:
            return (
                f"Order {self.order_id[:8]}... SUCCESS: "
                f"{self.side.value} {self.size:.4f} @ ${self.price:.4f} "
                f"({self.submission_time_ms:.1f}ms)"
            )
        return f"Order FAILED: {self.error_message} ({self.submission_time_ms:.1f}ms)"


# =============================================================================
# Execution Tracking Dataclasses
# =============================================================================

@dataclass
class ExecutionConfig:
    """Configuration for trade execution tracking.

    Attributes:
        order_poll_interval_sec: Interval between order status polls
        order_timeout_sec: Max time to wait for order to have trades
        trade_poll_interval_sec: Interval between trade status polls
        trade_timeout_sec: Max time to wait for trade to be MINED
    """
    order_poll_interval_sec: float = 0.5
    order_timeout_sec: float = 30.0
    trade_poll_interval_sec: float = 1.0
    trade_timeout_sec: float = 60.0


@dataclass
class OrderInfo:
    """Order status from CLOB API.

    Attributes:
        order_id: Order identifier (hash)
        status: Current order status (LIVE, MATCHED, CANCELED, EXPIRED)
        associate_trades: Trade IDs where order was partially/fully filled
        size_matched: Quantity of order that has been filled
        original_size: Order size at initial placement
        market: Market ID (condition ID)
        side: Buy or sell
        price: Order price
        asset_id: Token identifier
        created_at: Unix timestamp of order creation
    """
    order_id: str
    status: str
    associate_trades: list[str]
    size_matched: float
    original_size: float
    market: str
    side: str
    price: float
    asset_id: str
    created_at: Optional[float] = None

    @classmethod
    def from_api_response(cls, data: dict) -> "OrderInfo":
        """Create OrderInfo from CLOB API response."""
        return cls(
            order_id=data.get("id", ""),
            status=data.get("status", ""),
            associate_trades=data.get("associate_trades", []) or [],
            size_matched=float(data.get("size_matched", 0)),
            original_size=float(data.get("original_size", 0)),
            market=data.get("market", ""),
            side=data.get("side", ""),
            price=float(data.get("price", 0)),
            asset_id=data.get("asset_id", ""),
            created_at=float(data.get("created_at")) if data.get("created_at") else None,
        )

    @property
    def is_terminal(self) -> bool:
        """Check if order is in a terminal state."""
        return self.status in ("CANCELED", "EXPIRED", "MATCHED")

    @property
    def has_trades(self) -> bool:
        """Check if order has associated trades."""
        return len(self.associate_trades) > 0

    def __str__(self) -> str:
        trades_str = f", trades={len(self.associate_trades)}" if self.associate_trades else ""
        return f"Order {self.order_id[:8]}... [{self.status}] {self.size_matched}/{self.original_size} filled{trades_str}"


@dataclass
class ExecutionResult:
    """Result of a complete order execution (through MINED).

    Attributes:
        order_id: The CLOB order ID
        trades: All trades with status >= MINED
        transaction_hashes: On-chain transaction hashes
        total_size_matched: Total size filled across all trades
        total_execution_time_ms: Time from order submission to all trades MINED
        success: Whether execution completed successfully
        error_message: Error message if failed
    """
    order_id: str
    trades: list["Trade"]
    transaction_hashes: list[str]
    total_size_matched: float
    total_execution_time_ms: float
    success: bool
    error_message: Optional[str] = None

    @classmethod
    def from_success(
        cls,
        order_id: str,
        trades: list,
        transaction_hashes: list[str],
        total_size_matched: float,
        total_execution_time_ms: float,
    ) -> "ExecutionResult":
        """Create a successful execution result."""
        return cls(
            order_id=order_id,
            trades=trades,
            transaction_hashes=transaction_hashes,
            total_size_matched=total_size_matched,
            total_execution_time_ms=total_execution_time_ms,
            success=True,
            error_message=None,
        )

    @classmethod
    def from_error(
        cls,
        order_id: str,
        error_message: str,
        total_execution_time_ms: float,
        trades: Optional[list] = None,
    ) -> "ExecutionResult":
        """Create a failed execution result."""
        return cls(
            order_id=order_id,
            trades=trades or [],
            transaction_hashes=[],
            total_size_matched=0.0,
            total_execution_time_ms=total_execution_time_ms,
            success=False,
            error_message=error_message,
        )

    def __str__(self) -> str:
        if self.success:
            return (
                f"Execution SUCCESS: {len(self.trades)} trade(s), "
                f"{len(self.transaction_hashes)} tx(s), "
                f"{self.total_execution_time_ms:.0f}ms"
            )
        return f"Execution FAILED: {self.error_message}"


# =============================================================================
# Execution Exceptions
# =============================================================================

class OrderExpiredError(TradingError):
    """Exception raised when order expires before being filled."""
    pass


class OrderCanceledError(TradingError):
    """Exception raised when order is canceled."""
    pass


class TradeMiningFailedError(TradingError):
    """Exception raised when trade fails to be mined on-chain."""
    pass


class ExecutionTimeoutError(TradingError):
    """Exception raised when execution times out waiting for state transition."""
    pass


@dataclass
class MarketPosition:
    """Represents a position in a Polymarket market.

    Attributes:
        condition_id: Market condition ID
        asset: Token contract address
        outcome: Outcome name (e.g., "Yes", "No")
        outcome_index: Outcome index (0 or 1)
        size: Number of shares held
        avg_price: Average entry price
        current_price: Current market price
        initial_value: Initial position value in USDC
        current_value: Current position value in USDC
        cash_pnl: Realized + unrealized PnL in USDC
        percent_pnl: PnL as percentage
        realized_pnl: Realized PnL in USDC
        title: Market title
        slug: Market slug (URL identifier)
        event_slug: Event slug
        end_date: Market end/resolution date
        redeemable: Whether position can be redeemed
        mergeable: Whether position can be merged
    """

    condition_id: str
    asset: str
    outcome: str
    outcome_index: int
    size: float
    avg_price: float
    current_price: float
    initial_value: float
    current_value: float
    cash_pnl: float
    percent_pnl: float
    realized_pnl: float
    title: str
    slug: str
    event_slug: str
    end_date: Optional[datetime]
    redeemable: bool
    mergeable: bool

    @classmethod
    def from_api_response(cls, data: dict) -> "MarketPosition":
        """Create Position from API response data."""
        end_date = None
        if data.get("endDate"):
            try:
                end_date = datetime.fromisoformat(data["endDate"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        return cls(
            condition_id=data.get("conditionId", ""),
            asset=data.get("asset", ""),
            outcome=data.get("outcome", ""),
            outcome_index=data.get("outcomeIndex", 0),
            size=float(data.get("size", 0)),
            avg_price=float(data.get("avgPrice", 0)),
            current_price=float(data.get("curPrice", 0)),
            initial_value=float(data.get("initialValue", 0)),
            current_value=float(data.get("currentValue", 0)),
            cash_pnl=float(data.get("cashPnl", 0)),
            percent_pnl=float(data.get("percentPnl", 0)),
            realized_pnl=float(data.get("realizedPnl", 0)),
            title=data.get("title", ""),
            slug=data.get("slug", ""),
            event_slug=data.get("eventSlug", ""),
            end_date=end_date,
            redeemable=data.get("redeemable", False),
            mergeable=data.get("mergeable", False),
        )

    @property
    def unrealized_pnl(self) -> float:
        """Calculate unrealized PnL."""
        return self.cash_pnl - self.realized_pnl

    @property
    def market_url(self) -> str:
        """Get Polymarket URL for this position's market."""
        if self.event_slug:
            return f"https://polymarket.com/event/{self.event_slug}"
        return ""

    def __str__(self) -> str:
        return (
            f"{self.title} [{self.outcome}]: "
            f"{self.size:.2f} shares @ ${self.avg_price:.4f} "
            f"(current: ${self.current_price:.4f}, PnL: ${self.cash_pnl:.2f})"
        )


@dataclass
class Trade:
    """Represents a trade/transaction in Polymarket.

    Attributes:
        id: Unique trade ID
        taker_order_id: Taker's order ID
        market: Market/condition ID
        asset: Token contract address
        side: Trade side (BUY or SELL)
        size: Number of shares traded
        price: Trade price
        status: Trade status (MATCHED, MINED, CONFIRMED, etc.)
        match_time: When trade was matched
        outcome: Outcome name
        fee_rate_bps: Fee rate in basis points
        transaction_hash: On-chain transaction hash (if mined)
        bucket_index: Bucket index for the trade
    """

    id: str
    taker_order_id: str
    market: str
    asset: str
    side: str
    size: float
    price: float
    status: TradeStatus
    match_time: Optional[datetime]
    outcome: str
    fee_rate_bps: float
    transaction_hash: Optional[str]
    bucket_index: Optional[int]

    @classmethod
    def from_api_response(cls, data: dict) -> "Trade":
        """Create Trade from API response data."""
        match_time = None
        if data.get("matchTime"):
            try:
                # Handle Unix timestamp
                ts = data["matchTime"]
                if isinstance(ts, (int, float)):
                    match_time = datetime.fromtimestamp(ts)
                else:
                    match_time = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        status_str = data.get("status", "MATCHED").upper()
        try:
            status = TradeStatus(status_str)
        except ValueError:
            status = TradeStatus.MATCHED

        return cls(
            id=data.get("id", ""),
            taker_order_id=data.get("takerOrderId", ""),
            market=data.get("market", data.get("conditionId", "")),
            asset=data.get("asset", data.get("assetId", "")),
            side=data.get("side", ""),
            size=float(data.get("size", 0)),
            price=float(data.get("price", 0)),
            status=status,
            match_time=match_time,
            outcome=data.get("outcome", ""),
            fee_rate_bps=float(data.get("feeRateBps", 0)),
            transaction_hash=data.get("transactionHash"),
            bucket_index=data.get("bucketIndex"),
        )

    @property
    def is_confirmed(self) -> bool:
        """Check if trade is confirmed on-chain."""
        return self.status == TradeStatus.CONFIRMED

    @property
    def is_pending(self) -> bool:
        """Check if trade is still pending settlement."""
        return self.status in (TradeStatus.MATCHED, TradeStatus.MINED, TradeStatus.RETRYING)

    @property
    def is_failed(self) -> bool:
        """Check if trade failed."""
        return self.status == TradeStatus.FAILED

    def __str__(self) -> str:
        return (
            f"Trade {self.id[:8]}... [{self.status.value}]: "
            f"{self.side} {self.size:.2f} @ ${self.price:.4f}"
        )


@dataclass
class MarketInfo:
    """Extended market information including status.

    Attributes:
        condition_id: Market condition ID
        question_id: Question ID
        slug: Market slug (URL identifier)
        question: Market question/title
        description: Market description
        status: Market status (active, resolved, closed)
        outcome: Winning outcome (if resolved)
        resolution_date: When market was resolved
        end_date: Market end date
        tokens: List of token info (Yes/No tokens)
        active: Whether market is active
        closed: Whether market is closed
        resolved: Whether market is resolved
    """

    condition_id: str
    question_id: str
    slug: str
    question: str
    description: str
    status: MarketStatus
    outcome: Optional[str]
    resolution_date: Optional[datetime]
    end_date: Optional[datetime]
    tokens: list[dict]
    active: bool
    closed: bool

    @classmethod
    def from_api_response(cls, data: dict) -> "MarketInfo":
        """Create MarketInfo from API response data."""
        resolution_date = None
        if data.get("resolutionDate"):
            try:
                resolution_date = datetime.fromisoformat(
                    data["resolutionDate"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        end_date = None
        if data.get("endDate"):
            try:
                end_date = datetime.fromisoformat(
                    data["endDate"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        # Determine status
        active = data.get("active", True)
        closed = data.get("closed", False)
        resolved = data.get("resolved", False) or resolution_date is not None

        if resolved:
            status = MarketStatus.RESOLVED
        elif closed:
            status = MarketStatus.CLOSED
        else:
            status = MarketStatus.ACTIVE

        return cls(
            condition_id=data.get("conditionId", ""),
            question_id=data.get("questionId", ""),
            slug=data.get("slug", ""),
            question=data.get("question", ""),
            description=data.get("description", ""),
            status=status,
            outcome=data.get("outcome"),
            resolution_date=resolution_date,
            end_date=end_date,
            tokens=data.get("tokens", []),
            active=active,
            closed=closed,
        )

    @property
    def is_resolved(self) -> bool:
        """Check if market is resolved."""
        return self.status == MarketStatus.RESOLVED

    @property
    def is_active(self) -> bool:
        """Check if market is still active for trading."""
        return self.status == MarketStatus.ACTIVE

    @property
    def is_closed(self) -> bool:
        """Check if market is closed."""
        return self.status == MarketStatus.CLOSED or self.closed

    def __str__(self) -> str:
        status_str = f"[{self.status.value}]"
        if self.is_resolved and self.outcome:
            status_str = f"[RESOLVED: {self.outcome}]"
        return f"{self.question} {status_str}"


class PolymarketAPI:
    """Client for Polymarket APIs.

    Provides methods to query positions, markets, and account data.
    Also supports order placement via CLOB client (requires private_key or KMS in config).

    Trading credentials can be provided via:
    - Local private key (py-clob-client)
    - Google Cloud KMS key path
    - Custom Signer implementation
    """

    def __init__(
        self,
        config: Optional[PolymarketConfig] = None,
        signer: Optional["Signer"] = None,
    ):
        """Initialize the API client.

        Args:
            config: Polymarket configuration. If None, loads from default location.
            signer: Optional custom Signer. If None, created from config when needed.
        """
        self.config = config or PolymarketConfig.load()
        self._session: Optional[aiohttp.ClientSession] = None
        # Lazy-initialized signer for trading
        self._signer = signer
        # Legacy: keep _clob_client for backward compatibility
        self._clob_client = None
        self._api_creds = None  # Cached API credentials

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            # Disable auto decompression to avoid brotli issues
            self._session = aiohttp.ClientSession(
                headers={
                    "Accept-Encoding": "gzip, deflate",
                    "Accept": "application/json",
                }
            )
        return self._session

    async def close(self) -> None:
        """Close the HTTP session and clean up resources."""
        if self._session and not self._session.closed:
            await self._session.close()
        # CLOB client doesn't need explicit cleanup
        self._clob_client = None

    async def __aenter__(self) -> "PolymarketAPI":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[object],
    ) -> None:
        await self.close()

    # =========================================================================
    # Trading Setup (Signer Interface)
    # =========================================================================

    def _ensure_trading_configured(self) -> None:
        """Ensure trading credentials are available.

        Raises:
            TradingNotConfiguredError: If no trading credentials configured
        """
        if not self.config.has_trading_credentials:
            raise TradingNotConfiguredError(
                "Trading requires credentials in config. "
                "Set POLYMARKET_PRIVATE_KEY (for local signing) or "
                "POLYMARKET_KMS_KEY_PATH (for KMS signing) environment variable, "
                "or add to config/polymarket.json"
            )

    def _get_signer(self) -> "Signer":
        """Get or create the Signer for trading.

        Returns:
            Signer instance (LocalSigner, KMSSigner, or custom)

        Raises:
            TradingNotConfiguredError: If credentials not configured
            ImportError: If required packages not installed
        """
        self._ensure_trading_configured()

        if self._signer is None:
            self._signer = self.config.get_signer()

        return self._signer

    def _get_clob_client(self) -> Any:
        """Get or create the CLOB client for trading (sync).

        For backward compatibility. Uses LocalSigner internally.

        Returns:
            ClobClient instance (from py-clob-client package)

        Raises:
            TradingNotConfiguredError: If credentials not configured
            ImportError: If py-clob-client not installed
        """
        from poly.signer import LocalSigner

        signer = self._get_signer()

        # For LocalSigner, return the internal CLOB client
        if isinstance(signer, LocalSigner):
            return signer._get_clob_client()

        # For other signers, we need to create a CLOB client for API calls
        # but use the signer for signing
        if self._clob_client is None:
            if not self.config.private_key:
                raise TradingNotConfiguredError(
                    "Direct CLOB client access requires private_key. "
                    "Use the Signer interface for KMS-based signing."
                )

            try:
                from py_clob_client.client import ClobClient
            except ImportError:
                raise ImportError(
                    "py-clob-client is required for trading. "
                    "Install with: pip install py-clob-client"
                )

            self._clob_client = ClobClient(
                host=self.config.clob_api_url,
                key=self.config.private_key,
                chain_id=self.config.chain_id,
                signature_type=self.config.signature_type,
                funder=self.config.proxy_wallet,
            )

            if self._api_creds is None:
                self._api_creds = self._clob_client.create_or_derive_api_creds()
            self._clob_client.set_api_creds(self._api_creds)

        return self._clob_client

    @property
    def signer(self) -> "Signer":
        """Get the signer instance.

        Useful for advanced use cases where direct signer access is needed.
        """
        return self._get_signer()

    # =========================================================================
    # Position Queries (Data API)
    # =========================================================================

    async def get_positions(
        self,
        wallet_address: Optional[str] = None,
        market: Optional[str] = None,
        event_id: Optional[str] = None,
        size_threshold: float = 0.0,
        redeemable: Optional[bool] = None,
        mergeable: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "TOKENS",
        sort_direction: str = "DESC",
    ) -> list[MarketPosition]:
        """Get current positions for a wallet.

        Args:
            wallet_address: Wallet to query (defaults to config wallet)
            market: Filter by condition ID(s), comma-separated
            event_id: Filter by event ID(s), comma-separated
            size_threshold: Minimum position size (default: 0)
            redeemable: Filter for redeemable positions
            mergeable: Filter for mergeable positions
            limit: Results per page (max 500)
            offset: Pagination offset
            sort_by: Sort field (CURRENT, INITIAL, TOKENS, CASHPNL, etc.)
            sort_direction: ASC or DESC

        Returns:
            List of Position objects
        """
        address = wallet_address or self.config.wallet_address

        params = {
            "user": address,
            "limit": min(limit, 500),
            "offset": offset,
            "sortBy": sort_by,
            "sortDirection": sort_direction,
        }

        if size_threshold > 0:
            params["sizeThreshold"] = size_threshold

        if market:
            params["market"] = market

        if event_id:
            params["eventId"] = event_id

        if redeemable is not None:
            params["redeemable"] = str(redeemable).lower()

        if mergeable is not None:
            params["mergeable"] = str(mergeable).lower()

        url = f"{self.config.data_api_url}/positions?{urlencode(params)}"

        session = await self._get_session()
        async with session.get(url) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"API error {response.status}: {error_text}")

            data = await response.json()

        return [MarketPosition.from_api_response(item) for item in data]

    async def get_position_for_market(
        self,
        market_slug: str,
        wallet_address: Optional[str] = None,
    ) -> list[MarketPosition]:
        """Get positions for a specific market by slug.

        Args:
            market_slug: Market slug (e.g., "btc-updown-15m-1767795300")
            wallet_address: Wallet to query (defaults to config wallet)

        Returns:
            List of Position objects for that market
        """
        # First, get the condition ID from the market slug via Gamma API
        condition_id = await self._get_condition_id_from_slug(market_slug)

        if not condition_id:
            return []

        return await self.get_positions(
            wallet_address=wallet_address,
            market=condition_id,
        )

    async def get_shares_for_market(
        self,
        market_slug: str,
        outcome: Optional[str] = None,
        wallet_address: Optional[str] = None,
    ) -> dict[str, float]:
        """Get share counts for a specific market.

        Args:
            market_slug: Market slug
            outcome: Optional filter for specific outcome ("Yes" or "No")
            wallet_address: Wallet to query (defaults to config wallet)

        Returns:
            Dictionary mapping outcome to share count, e.g.:
            {"Yes": 100.5, "No": 0.0}
        """
        positions = await self.get_position_for_market(market_slug, wallet_address)

        result = {"Yes": 0.0, "No": 0.0}
        for pos in positions:
            if pos.outcome in result:
                result[pos.outcome] = pos.size

        if outcome:
            return {outcome: result.get(outcome, 0.0)}

        return result

    async def get_total_position_value(
        self,
        wallet_address: Optional[str] = None,
    ) -> float:
        """Get total value of all positions.

        Args:
            wallet_address: Wallet to query (defaults to config wallet)

        Returns:
            Total position value in USDC
        """
        positions = await self.get_positions(
            wallet_address=wallet_address,
            limit=500,
        )

        return sum(pos.current_value for pos in positions)

    # =========================================================================
    # Market Data (Gamma API)
    # =========================================================================

    async def _get_condition_id_from_slug(self, slug: str) -> Optional[str]:
        """Get condition ID for a market slug.

        Args:
            slug: Market slug

        Returns:
            Condition ID or None if not found
        """
        url = f"{self.config.gamma_api_url}/markets?slug={slug}"

        session = await self._get_session()
        async with session.get(url) as response:
            if response.status != 200:
                return None

            data = await response.json()

        if data and len(data) > 0:
            return data[0].get("conditionId")

        return None

    async def get_market_by_slug(self, slug: str) -> Optional[dict]:
        """Get market data by slug.

        Args:
            slug: Market slug

        Returns:
            Market data dictionary or None
        """
        url = f"{self.config.gamma_api_url}/markets?slug={slug}"

        session = await self._get_session()
        async with session.get(url) as response:
            if response.status != 200:
                return None

            data = await response.json()

        if data and len(data) > 0:
            return data[0]

        return None

    # =========================================================================
    # Order Book (CLOB API)
    # =========================================================================

    async def get_orderbook(self, token_id: str) -> dict:
        """Get order book for a token.

        Args:
            token_id: Token ID (asset address)

        Returns:
            Order book data with bids and asks
        """
        url = f"{self.config.clob_api_url}/book?token_id={token_id}"

        session = await self._get_session()
        async with session.get(url) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"API error {response.status}: {error_text}")

            return await response.json()

    async def get_midpoint(self, token_id: str) -> Optional[float]:
        """Get midpoint price for a token.

        Args:
            token_id: Token ID (asset address)

        Returns:
            Midpoint price or None
        """
        url = f"{self.config.clob_api_url}/midpoint?token_id={token_id}"

        session = await self._get_session()
        async with session.get(url) as response:
            if response.status != 200:
                return None

            data = await response.json()
            return float(data.get("mid", 0))

    # =========================================================================
    # Trade Queries (Data API)
    # =========================================================================

    async def get_trades(
        self,
        wallet_address: Optional[str] = None,
        market: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Trade]:
        """Get trade history for a wallet.

        Args:
            wallet_address: Wallet to query (defaults to config wallet)
            market: Filter by condition ID
            limit: Results per page (max 500)
            offset: Pagination offset

        Returns:
            List of Trade objects
        """
        address = wallet_address or self.config.wallet_address

        params = {
            "user": address,
            "limit": min(limit, 500),
            "offset": offset,
        }

        if market:
            params["market"] = market

        url = f"{self.config.data_api_url}/trades?{urlencode(params)}"

        session = await self._get_session()
        async with session.get(url) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"API error {response.status}: {error_text}")

            data = await response.json()

        return [Trade.from_api_response(item) for item in data]

    async def get_trade_by_id(self, trade_id: str) -> Optional[Trade]:
        """Get a specific trade by ID.

        Args:
            trade_id: Trade ID

        Returns:
            Trade object or None if not found
        """
        url = f"{self.config.data_api_url}/trades/{trade_id}"

        session = await self._get_session()
        async with session.get(url) as response:
            if response.status == 404:
                return None
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"API error {response.status}: {error_text}")

            data = await response.json()

        return Trade.from_api_response(data)

    async def get_trades_for_market(
        self,
        market_slug: str,
        wallet_address: Optional[str] = None,
        limit: int = 100,
    ) -> list[Trade]:
        """Get trades for a specific market.

        Args:
            market_slug: Market slug
            wallet_address: Wallet to query (defaults to config wallet)
            limit: Maximum number of trades to return

        Returns:
            List of Trade objects
        """
        condition_id = await self._get_condition_id_from_slug(market_slug)

        if not condition_id:
            return []

        return await self.get_trades(
            wallet_address=wallet_address,
            market=condition_id,
            limit=limit,
        )

    # =========================================================================
    # Market Status Queries
    # =========================================================================

    async def get_market_info(self, slug: str) -> Optional[MarketInfo]:
        """Get detailed market information including status.

        Args:
            slug: Market slug

        Returns:
            MarketInfo object or None if not found
        """
        url = f"{self.config.gamma_api_url}/markets?slug={slug}"

        session = await self._get_session()
        async with session.get(url) as response:
            if response.status != 200:
                return None

            data = await response.json()

        if data and len(data) > 0:
            return MarketInfo.from_api_response(data[0])

        return None

    async def get_market_status(self, slug: str) -> Optional[MarketStatus]:
        """Get just the status of a market (active, resolved, closed).

        Args:
            slug: Market slug

        Returns:
            MarketStatus enum or None if market not found
        """
        market_info = await self.get_market_info(slug)
        if market_info:
            return market_info.status
        return None

    async def is_market_resolved(self, slug: str) -> bool:
        """Check if a market has been resolved.

        Args:
            slug: Market slug

        Returns:
            True if market is resolved, False otherwise
        """
        status = await self.get_market_status(slug)
        return status == MarketStatus.RESOLVED

    async def is_market_active(self, slug: str) -> bool:
        """Check if a market is still active for trading.

        Args:
            slug: Market slug

        Returns:
            True if market is active, False otherwise
        """
        status = await self.get_market_status(slug)
        return status == MarketStatus.ACTIVE

    # =========================================================================
    # Token Resolution Helper
    # =========================================================================

    async def _resolve_token_id(
        self,
        market_slug: str,
        outcome: str,
    ) -> str:
        """Resolve token ID from market slug and outcome.

        Handles multiple API response formats:
        - tokens: [{outcome, token_id}, ...]  (older format)
        - clobTokenIds + outcomes: parallel arrays (newer format)

        Supports outcome aliases:
        - "Yes" / "Up" (index 0)
        - "No" / "Down" (index 1)

        Args:
            market_slug: Market slug (e.g., "btc-updown-15m-1767795300")
            outcome: "Yes", "No", "Up", or "Down"

        Returns:
            Token ID for the specified outcome

        Raises:
            ValueError: If market not found or outcome invalid
        """
        market = await self.get_market_by_slug(market_slug)
        if not market:
            raise ValueError(f"Market not found: {market_slug}")

        outcome_lower = outcome.lower()

        # Try tokens array format first (older API response)
        tokens = market.get("tokens", [])
        for token in tokens:
            if token.get("outcome", "").lower() == outcome_lower:
                token_id = token.get("token_id")
                if token_id:
                    return token_id

        # Try clobTokenIds + outcomes format (newer API response)
        clob_token_ids = market.get("clobTokenIds", [])
        outcomes = market.get("outcomes", [])

        # Parse JSON strings if needed (API returns these as JSON-encoded strings)
        if isinstance(clob_token_ids, str):
            import json
            clob_token_ids = json.loads(clob_token_ids)
        if isinstance(outcomes, str):
            import json
            outcomes = json.loads(outcomes)

        if clob_token_ids and outcomes and len(clob_token_ids) == len(outcomes):
            # Normalize outcome aliases (Yes/Up -> index 0, No/Down -> index 1)
            outcome_aliases = {
                "yes": 0, "up": 0,
                "no": 1, "down": 1,
            }

            target_index = outcome_aliases.get(outcome_lower)

            if target_index is not None and target_index < len(clob_token_ids):
                return clob_token_ids[target_index]

            # Also try matching by name in outcomes array
            for i, outcome_name in enumerate(outcomes):
                if outcome_name.lower() == outcome_lower:
                    return clob_token_ids[i]

        raise ValueError(
            f"Token not found for outcome '{outcome}' in market {market_slug}. "
            f"Available outcomes: {outcomes or [t.get('outcome') for t in tokens]}"
        )

    # =========================================================================
    # Token ID Queries
    # =========================================================================

    async def get_market_tokens(self, market_slug: str) -> dict[str, str]:
        """Get token IDs for a market by slug.

        Args:
            market_slug: Market slug (e.g., "btc-updown-15m-1767795300")

        Returns:
            Dictionary with token IDs:
            - "up" or "yes": First outcome token ID
            - "down" or "no": Second outcome token ID
            Returns empty dict if market not found or has no tokens.

        Example:
            >>> tokens = await api.get_market_tokens("btc-updown-15m-1767882600")
            >>> print(tokens)
            {'up': '349296...', 'down': '200744...'}
        """
        market = await self.get_market_by_slug(market_slug)
        if not market:
            return {}

        # Parse token IDs and outcomes
        clob_token_ids = market.get("clobTokenIds", [])
        outcomes = market.get("outcomes", [])

        if isinstance(clob_token_ids, str):
            import json
            clob_token_ids = json.loads(clob_token_ids)
        if isinstance(outcomes, str):
            import json
            outcomes = json.loads(outcomes)

        if not clob_token_ids or not outcomes:
            # Try tokens array format
            tokens = market.get("tokens", [])
            result = {}
            for token in tokens:
                outcome = token.get("outcome", "").lower()
                token_id = token.get("token_id", "")
                if outcome and token_id:
                    result[outcome] = token_id
            return result

        # Map outcomes to token IDs
        result = {}
        for i, outcome in enumerate(outcomes):
            if i < len(clob_token_ids):
                result[outcome.lower()] = clob_token_ids[i]

        return result

    async def get_token_ids_for_markets(
        self,
        slugs: list[str],
    ) -> dict[str, dict[str, str]]:
        """Get token IDs for multiple markets.

        Args:
            slugs: List of market slugs

        Returns:
            Dictionary mapping slug to token dict:
            {
                "btc-updown-15m-1767882600": {"up": "...", "down": "..."},
                "btc-updown-15m-1767883500": {"up": "...", "down": "..."},
            }
            Markets not found will have empty dicts.
        """
        results = {}
        for slug in slugs:
            results[slug] = await self.get_market_tokens(slug)
        return results

    async def get_btc_market_tokens(
        self,
        horizon: str = "15m",
        slots_ahead: int = 0,
    ) -> dict[str, str]:
        """Get token IDs for a BTC market.

        Args:
            horizon: Market horizon ("15m", "1h", "4h")
            slots_ahead: Number of slots ahead (0 = current, 1 = next, etc.)

        Returns:
            Dictionary with token IDs {"up": "...", "down": "..."}
            Returns empty dict if market not found.

        Example:
            >>> tokens = await api.get_btc_market_tokens("15m", slots_ahead=0)
            >>> print(f"Current 15m UP token: {tokens.get('up', 'N/A')}")
        """
        from poly.markets import Asset, MarketHorizon, get_slug

        horizon_map = {
            "15m": MarketHorizon.M15,
            "1h": MarketHorizon.H1,
            "4h": MarketHorizon.H4,
        }

        market_horizon = horizon_map.get(horizon.lower())
        if not market_horizon:
            return {}

        slug = get_slug(Asset.BTC, market_horizon, slots_ahead)
        return await self.get_market_tokens(slug)

    async def get_btc_market_token_list(
        self,
        horizon: str = "15m",
        count: int = 5,
        include_current: bool = True,
    ) -> list[dict]:
        """Get token IDs for multiple BTC markets (current and future).

        Args:
            horizon: Market horizon ("15m", "1h", "4h")
            count: Number of markets to fetch
            include_current: If True, include current market

        Returns:
            List of dicts with slug and tokens:
            [
                {"slug": "btc-updown-15m-...", "up": "...", "down": "..."},
                ...
            ]

        Example:
            >>> markets = await api.get_btc_market_token_list("15m", count=3)
            >>> for m in markets:
            ...     print(f"{m['slug']}: UP={m.get('up', 'N/A')[:8]}...")
        """
        from poly.markets import Asset, MarketHorizon, get_market_slugs

        horizon_map = {
            "15m": MarketHorizon.M15,
            "1h": MarketHorizon.H1,
            "4h": MarketHorizon.H4,
        }

        market_horizon = horizon_map.get(horizon.lower())
        if not market_horizon:
            return []

        slugs = get_market_slugs(Asset.BTC, market_horizon, count, include_current)
        results = []

        for slug in slugs:
            tokens = await self.get_market_tokens(slug)
            results.append({
                "slug": slug,
                **tokens,
            })

        return results

    # =========================================================================
    # Order Placement (CLOB API)
    # =========================================================================

    async def place_order(
        self,
        token_id: str,
        side: OrderSide,
        price: float,
        size: float,
        time_in_force: OrderTimeInForce = OrderTimeInForce.GTC,
    ) -> OrderResult:
        """Place an order on the Polymarket CLOB.

        Args:
            token_id: The token ID (YES or NO token address) to trade
            side: BUY or SELL
            price: Limit price (0.0 to 1.0)
            size: Number of shares to trade
            time_in_force: Order time in force (default: GTC)

        Returns:
            OrderResult with order_id, timing info, and status

        Raises:
            TradingNotConfiguredError: If private_key not configured
            ValueError: If parameters are invalid

        Example:
            >>> async with PolymarketAPI(config) as api:
            ...     result = await api.place_order(
            ...         token_id="0x...",
            ...         side=OrderSide.BUY,
            ...         price=0.45,
            ...         size=100.0,
            ...     )
            ...     print(f"Order placed: {result.order_id}")
        """
        # Validate inputs
        if not token_id:
            raise ValueError("token_id is required")
        if price <= 0 or price >= 1:
            raise ValueError("price must be between 0 and 1 exclusive")
        if size <= 0:
            raise ValueError("size must be positive")

        start_time = time.time()

        try:
            # Run the sync CLOB client in executor (blocking calls)
            loop = asyncio.get_running_loop()
            order_id = await loop.run_in_executor(
                None,
                self._place_order_sync,
                token_id,
                side,
                price,
                size,
                time_in_force,
            )

            submission_time_ms = (time.time() - start_time) * 1000

            return OrderResult.from_success(
                order_id=order_id,
                token_id=token_id,
                side=side,
                price=price,
                size=size,
                time_in_force=time_in_force,
                submission_time_ms=submission_time_ms,
            )

        except TradingNotConfiguredError:
            # Re-raise without wrapping
            raise
        except Exception as e:
            submission_time_ms = (time.time() - start_time) * 1000
            return OrderResult.from_error(
                error_message=str(e),
                token_id=token_id,
                side=side,
                price=price,
                size=size,
                time_in_force=time_in_force,
                submission_time_ms=submission_time_ms,
            )

    def _place_order_sync(
        self,
        token_id: str,
        side: OrderSide,
        price: float,
        size: float,
        time_in_force: OrderTimeInForce,
    ) -> str:
        """Synchronous order placement (runs in executor).

        Uses the Signer interface for signing. For LocalSigner, this delegates
        to py-clob-client. For KMSSigner, uses custom EIP-712 signing.

        Returns:
            order_id from CLOB response

        Raises:
            TradingError: If order placement fails
        """
        from poly.signer import LocalSigner, KMSSigner, OrderParams
        from poly.signer import OrderSide as SignerOrderSide

        signer = self._get_signer()

        # Map OrderSide enum
        signer_side = SignerOrderSide.BUY if side == OrderSide.BUY else SignerOrderSide.SELL

        if isinstance(signer, LocalSigner):
            # Use LocalSigner's built-in post_order (wraps py-clob-client)
            params = OrderParams(
                token_id=token_id,
                side=signer_side,
                price=price,
                size=size,
            )
            signed_order = signer.sign_order(params)
            response = signer.post_order(signed_order)

        elif isinstance(signer, KMSSigner):
            # Use KMSSigner for signing, then submit via HTTP
            params = OrderParams(
                token_id=token_id,
                side=signer_side,
                price=price,
                size=size,
            )
            signed_order = signer.sign_order(params)

            # Submit order via REST API
            import requests
            url = f"{self.config.clob_api_url}/order"
            response = requests.post(url, json=signed_order)
            response.raise_for_status()
            response = response.json()

        else:
            # Generic fallback: try to use CLOB client
            from py_clob_client.order_builder.constants import BUY, SELL

            client = self._get_clob_client()
            clob_side = BUY if side == OrderSide.BUY else SELL

            order = client.create_order(
                token_id=token_id,
                price=price,
                size=size,
                side=clob_side,
            )
            response = client.post_order(order)

        # Extract order ID from response
        order_id = response.get("orderID") or response.get("order_id")
        if not order_id:
            raise TradingError(f"No order ID in response: {response}")

        return order_id

    async def place_order_by_slug(
        self,
        market_slug: str,
        outcome: str,
        side: OrderSide,
        price: float,
        size: float,
        time_in_force: OrderTimeInForce = OrderTimeInForce.GTC,
    ) -> OrderResult:
        """Place an order using market slug and outcome name.

        This is a convenience method that resolves the token_id automatically.

        Args:
            market_slug: Market slug (e.g., "btc-updown-15m-1767795300")
            outcome: "Yes" or "No"
            side: BUY or SELL
            price: Limit price (0.0 to 1.0)
            size: Number of shares to trade
            time_in_force: Order time in force (default: GTC)

        Returns:
            OrderResult with order_id, timing info, and status

        Raises:
            ValueError: If market not found or invalid outcome
        """
        token_id = await self._resolve_token_id(market_slug, outcome)
        return await self.place_order(
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            time_in_force=time_in_force,
        )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order.

        Args:
            order_id: The order ID to cancel

        Returns:
            True if cancelled successfully

        Raises:
            TradingNotConfiguredError: If credentials not configured
            TradingError: If cancellation fails
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._cancel_order_sync,
            order_id,
        )

    def _cancel_order_sync(self, order_id: str) -> bool:
        """Synchronous order cancellation (runs in executor)."""
        from poly.signer import LocalSigner

        signer = self._get_signer()

        if isinstance(signer, LocalSigner):
            signer.cancel_order(order_id)
        else:
            # For KMS signer, use direct CLOB client (cancel doesn't need signing)
            client = self._get_clob_client()
            client.cancel(order_id)

        return True

    # =========================================================================
    # Order Status Queries (CLOB API)
    # =========================================================================

    async def get_order(self, order_id: str) -> OrderInfo:
        """Get order status from CLOB API.

        Args:
            order_id: The order ID/hash

        Returns:
            OrderInfo with status and associate_trades

        Raises:
            TradingNotConfiguredError: If credentials not configured
            TradingError: If query fails
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._get_order_sync,
            order_id,
        )

    def _get_order_sync(self, order_id: str) -> OrderInfo:
        """Synchronous order status query (runs in executor)."""
        from poly.signer import LocalSigner

        signer = self._get_signer()

        if isinstance(signer, LocalSigner):
            response = signer.get_order(order_id)
        else:
            # For other signers, use direct CLOB client
            client = self._get_clob_client()
            response = client.get_order(order_id)

        return OrderInfo.from_api_response(response)

    # =========================================================================
    # Execution Tracking (Wait for State Transitions)
    # =========================================================================

    async def wait_for_order_match(
        self,
        order_id: str,
        config: Optional[ExecutionConfig] = None,
    ) -> list[str]:
        """Wait for order to have associated trades.

        Polls order status until associate_trades is non-empty or order
        reaches a terminal state (CANCELED, EXPIRED).

        State machine:
            LIVE -> (waiting for match) -> MATCHED (has associate_trades)
            LIVE -> CANCELED (user canceled)
            LIVE -> EXPIRED (time limit reached)

        Args:
            order_id: The order ID/hash
            config: Execution configuration (uses defaults if None)

        Returns:
            List of trade IDs from associate_trades

        Raises:
            OrderCanceledError: If order was canceled
            OrderExpiredError: If order expired
            ExecutionTimeoutError: If timeout waiting for trades
        """
        config = config or ExecutionConfig()
        start_time = time.time()

        while True:
            # Check timeout before polling
            elapsed = time.time() - start_time
            if elapsed > config.order_timeout_sec:
                raise ExecutionTimeoutError(
                    f"Timeout waiting for order {order_id} to match "
                    f"after {elapsed:.1f}s"
                )

            # Poll order status from CLOB API
            order_info = await self.get_order(order_id)

            # Terminal failure states - order cannot progress further
            if order_info.status == "CANCELED":
                raise OrderCanceledError(f"Order {order_id} was canceled")
            if order_info.status == "EXPIRED":
                raise OrderExpiredError(f"Order {order_id} expired")

            # Success: order has been matched and has associated trades
            if order_info.has_trades:
                return order_info.associate_trades

            # Still waiting - poll again after interval
            await asyncio.sleep(config.order_poll_interval_sec)

    async def wait_for_trade_mined(
        self,
        trade_id: str,
        config: Optional[ExecutionConfig] = None,
    ) -> Trade:
        """Wait for trade to be MINED on-chain.

        Polls trade status until status is MINED or CONFIRMED.

        State machine:
            MATCHED -> (sent to executor) -> MINED (on-chain, no finality)
            MATCHED -> RETRYING (tx failed, resubmitting)
            MINED -> CONFIRMED (probabilistic finality)
            MATCHED/RETRYING -> FAILED (permanent failure)

        Args:
            trade_id: The trade ID
            config: Execution configuration (uses defaults if None)

        Returns:
            Trade object with transaction_hash populated

        Raises:
            TradeMiningFailedError: If trade status is FAILED
            ExecutionTimeoutError: If timeout waiting for MINED
        """
        config = config or ExecutionConfig()
        start_time = time.time()

        while True:
            # Check timeout before polling
            elapsed = time.time() - start_time
            if elapsed > config.trade_timeout_sec:
                raise ExecutionTimeoutError(
                    f"Timeout waiting for trade {trade_id} to be mined "
                    f"after {elapsed:.1f}s"
                )

            # Poll trade status from Data API
            trade = await self.get_trade_by_id(trade_id)

            if trade is None:
                # Trade not visible in API yet - common immediately after match
                await asyncio.sleep(config.trade_poll_interval_sec)
                continue

            # Terminal failure - trade will not be retried
            if trade.status == TradeStatus.FAILED:
                raise TradeMiningFailedError(
                    f"Trade {trade_id} failed to be mined"
                )

            # Success: trade is on-chain (MINED) or has finality (CONFIRMED)
            if trade.status in (TradeStatus.MINED, TradeStatus.CONFIRMED):
                return trade

            # Still in progress (MATCHED or RETRYING) - poll again
            await asyncio.sleep(config.trade_poll_interval_sec)

    # =========================================================================
    # High-Level Execution (Place + Wait for MINED)
    # =========================================================================

    async def execute_order(
        self,
        token_id: str,
        side: OrderSide,
        price: float,
        size: float,
        time_in_force: OrderTimeInForce = OrderTimeInForce.GTC,
        config: Optional[ExecutionConfig] = None,
    ) -> ExecutionResult:
        """Execute an order and wait for all trades to be MINED.

        This is the high-level method that:
        1. Places the order
        2. Waits for order to have associated trades
        3. Waits for each trade to be MINED on-chain
        4. Returns all transaction hashes

        Args:
            token_id: The token ID to trade
            side: BUY or SELL
            price: Limit price (0.0 to 1.0)
            size: Number of shares
            time_in_force: Order time in force (default: GTC)
            config: Execution configuration (uses defaults if None)

        Returns:
            ExecutionResult with trades and transaction_hashes

        Example:
            >>> result = await api.execute_order(
            ...     token_id="0x...",
            ...     side=OrderSide.BUY,
            ...     price=0.45,
            ...     size=100.0,
            ... )
            >>> if result.success:
            ...     print(f"Tx hashes: {result.transaction_hashes}")
        """
        config = config or ExecutionConfig()
        start_time = time.time()

        # Step 1: Place order
        order_result = await self.place_order(
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            time_in_force=time_in_force,
        )

        if not order_result.success:
            return ExecutionResult.from_error(
                order_id=order_result.order_id or "",
                error_message=order_result.error_message or "Order placement failed",
                total_execution_time_ms=(time.time() - start_time) * 1000,
            )

        order_id = order_result.order_id

        try:
            # Step 2: Wait for order to have trades
            trade_ids = await self.wait_for_order_match(order_id, config)

            # Step 3: Wait for each trade to be MINED
            trades = []
            tx_hashes = []
            total_size = 0.0

            for trade_id in trade_ids:
                trade = await self.wait_for_trade_mined(trade_id, config)
                trades.append(trade)
                if trade.transaction_hash:
                    tx_hashes.append(trade.transaction_hash)
                total_size += trade.size

            return ExecutionResult.from_success(
                order_id=order_id,
                trades=trades,
                transaction_hashes=tx_hashes,
                total_size_matched=total_size,
                total_execution_time_ms=(time.time() - start_time) * 1000,
            )

        except (OrderCanceledError, OrderExpiredError, TradeMiningFailedError,
                ExecutionTimeoutError) as e:
            return ExecutionResult.from_error(
                order_id=order_id,
                error_message=str(e),
                total_execution_time_ms=(time.time() - start_time) * 1000,
            )

    async def execute_order_by_slug(
        self,
        market_slug: str,
        outcome: str,
        side: OrderSide,
        price: float,
        size: float,
        time_in_force: OrderTimeInForce = OrderTimeInForce.GTC,
        config: Optional[ExecutionConfig] = None,
    ) -> ExecutionResult:
        """Execute an order using market slug and wait for MINED.

        Convenience method that resolves token_id from slug first.

        Args:
            market_slug: Market slug (e.g., "btc-updown-15m-1767795300")
            outcome: "Yes" or "No"
            side: BUY or SELL
            price: Limit price (0.0 to 1.0)
            size: Number of shares
            time_in_force: Order time in force (default: GTC)
            config: Execution configuration (uses defaults if None)

        Returns:
            ExecutionResult with trades and transaction_hashes
        """
        start_time = time.time()

        try:
            token_id = await self._resolve_token_id(market_slug, outcome)
        except ValueError as e:
            return ExecutionResult.from_error(
                order_id="",
                error_message=str(e),
                total_execution_time_ms=(time.time() - start_time) * 1000,
            )

        return await self.execute_order(
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            time_in_force=time_in_force,
            config=config,
        )


# =========================================================================
# Synchronous Wrapper
# =========================================================================

class PolymarketAPISync:
    """Synchronous wrapper for PolymarketAPI.

    Provides blocking methods for environments without async support.
    """

    def __init__(self, config: Optional[PolymarketConfig] = None):
        """Initialize the sync API client."""
        self.config = config or PolymarketConfig.load()
        self._api: Optional[PolymarketAPI] = None

    def _get_api(self) -> PolymarketAPI:
        """Get or create async API instance."""
        if self._api is None:
            self._api = PolymarketAPI(self.config)
        return self._api

    def _run(self, coro: Awaitable[T]) -> T:
        """Run async coroutine synchronously.

        Note: Uses asyncio.get_event_loop() which works in sync contexts.
        For Python 3.10+, this is the standard pattern for sync wrappers.
        """
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro)

    def get_positions(self, **kwargs) -> list[MarketPosition]:
        """Get current positions. See PolymarketAPI.get_positions for args."""
        return self._run(self._get_api().get_positions(**kwargs))

    def get_position_for_market(
        self,
        market_slug: str,
        wallet_address: Optional[str] = None,
    ) -> list[MarketPosition]:
        """Get positions for a specific market."""
        return self._run(
            self._get_api().get_position_for_market(market_slug, wallet_address)
        )

    def get_shares_for_market(
        self,
        market_slug: str,
        outcome: Optional[str] = None,
        wallet_address: Optional[str] = None,
    ) -> dict[str, float]:
        """Get share counts for a specific market."""
        return self._run(
            self._get_api().get_shares_for_market(market_slug, outcome, wallet_address)
        )

    def get_total_position_value(
        self,
        wallet_address: Optional[str] = None,
    ) -> float:
        """Get total value of all positions."""
        return self._run(self._get_api().get_total_position_value(wallet_address))

    def get_market_by_slug(self, slug: str) -> Optional[dict]:
        """Get market data by slug."""
        return self._run(self._get_api().get_market_by_slug(slug))

    def get_orderbook(self, token_id: str) -> dict:
        """Get order book for a token."""
        return self._run(self._get_api().get_orderbook(token_id))

    def get_midpoint(self, token_id: str) -> Optional[float]:
        """Get midpoint price for a token."""
        return self._run(self._get_api().get_midpoint(token_id))

    # Trade queries
    def get_trades(self, **kwargs) -> list[Trade]:
        """Get trade history. See PolymarketAPI.get_trades for args."""
        return self._run(self._get_api().get_trades(**kwargs))

    def get_trade_by_id(self, trade_id: str) -> Optional[Trade]:
        """Get a specific trade by ID."""
        return self._run(self._get_api().get_trade_by_id(trade_id))

    def get_trades_for_market(
        self,
        market_slug: str,
        wallet_address: Optional[str] = None,
        limit: int = 100,
    ) -> list[Trade]:
        """Get trades for a specific market."""
        return self._run(
            self._get_api().get_trades_for_market(market_slug, wallet_address, limit)
        )

    # Market status queries
    def get_market_info(self, slug: str) -> Optional[MarketInfo]:
        """Get detailed market information including status."""
        return self._run(self._get_api().get_market_info(slug))

    def get_market_status(self, slug: str) -> Optional[MarketStatus]:
        """Get just the status of a market."""
        return self._run(self._get_api().get_market_status(slug))

    def is_market_resolved(self, slug: str) -> bool:
        """Check if a market has been resolved."""
        return self._run(self._get_api().is_market_resolved(slug))

    def is_market_active(self, slug: str) -> bool:
        """Check if a market is still active for trading."""
        return self._run(self._get_api().is_market_active(slug))

    # Trading methods
    def place_order(
        self,
        token_id: str,
        side: OrderSide,
        price: float,
        size: float,
        time_in_force: OrderTimeInForce = OrderTimeInForce.GTC,
    ) -> OrderResult:
        """Place an order. See PolymarketAPI.place_order for details."""
        return self._run(
            self._get_api().place_order(token_id, side, price, size, time_in_force)
        )

    def place_order_by_slug(
        self,
        market_slug: str,
        outcome: str,
        side: OrderSide,
        price: float,
        size: float,
        time_in_force: OrderTimeInForce = OrderTimeInForce.GTC,
    ) -> OrderResult:
        """Place an order by market slug. See PolymarketAPI.place_order_by_slug."""
        return self._run(
            self._get_api().place_order_by_slug(
                market_slug, outcome, side, price, size, time_in_force
            )
        )

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order. See PolymarketAPI.cancel_order for details."""
        return self._run(self._get_api().cancel_order(order_id))

    # Execution tracking methods
    def get_order(self, order_id: str) -> OrderInfo:
        """Get order status. See PolymarketAPI.get_order for details."""
        return self._run(self._get_api().get_order(order_id))

    def wait_for_order_match(
        self,
        order_id: str,
        config: Optional[ExecutionConfig] = None,
    ) -> list[str]:
        """Wait for order to have trades. See PolymarketAPI.wait_for_order_match."""
        return self._run(self._get_api().wait_for_order_match(order_id, config))

    def wait_for_trade_mined(
        self,
        trade_id: str,
        config: Optional[ExecutionConfig] = None,
    ) -> Trade:
        """Wait for trade to be MINED. See PolymarketAPI.wait_for_trade_mined."""
        return self._run(self._get_api().wait_for_trade_mined(trade_id, config))

    def execute_order(
        self,
        token_id: str,
        side: OrderSide,
        price: float,
        size: float,
        time_in_force: OrderTimeInForce = OrderTimeInForce.GTC,
        config: Optional[ExecutionConfig] = None,
    ) -> ExecutionResult:
        """Execute order and wait for MINED. See PolymarketAPI.execute_order."""
        return self._run(
            self._get_api().execute_order(
                token_id, side, price, size, time_in_force, config
            )
        )

    def execute_order_by_slug(
        self,
        market_slug: str,
        outcome: str,
        side: OrderSide,
        price: float,
        size: float,
        time_in_force: OrderTimeInForce = OrderTimeInForce.GTC,
        config: Optional[ExecutionConfig] = None,
    ) -> ExecutionResult:
        """Execute order by slug and wait for MINED. See PolymarketAPI.execute_order_by_slug."""
        return self._run(
            self._get_api().execute_order_by_slug(
                market_slug, outcome, side, price, size, time_in_force, config
            )
        )

    # Token ID query methods
    def get_market_tokens(self, market_slug: str) -> dict[str, str]:
        """Get token IDs for a market by slug."""
        return self._run(self._get_api().get_market_tokens(market_slug))

    def get_token_ids_for_markets(self, slugs: list[str]) -> dict[str, dict[str, str]]:
        """Get token IDs for multiple markets."""
        return self._run(self._get_api().get_token_ids_for_markets(slugs))

    def get_btc_market_tokens(
        self,
        horizon: str = "15m",
        slots_ahead: int = 0,
    ) -> dict[str, str]:
        """Get token IDs for a BTC market."""
        return self._run(self._get_api().get_btc_market_tokens(horizon, slots_ahead))

    def get_btc_market_token_list(
        self,
        horizon: str = "15m",
        count: int = 5,
        include_current: bool = True,
    ) -> list[dict]:
        """Get token IDs for multiple BTC markets."""
        return self._run(
            self._get_api().get_btc_market_token_list(horizon, count, include_current)
        )

    def close(self) -> None:
        """Close the HTTP session."""
        if self._api:
            self._run(self._api.close())
