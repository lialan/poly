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
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
from urllib.parse import urlencode

import aiohttp

from poly.polymarket_config import PolymarketConfig


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
    For trading operations, use py-clob-client directly.
    """

    def __init__(self, config: Optional[PolymarketConfig] = None):
        """Initialize the API client.

        Args:
            config: Polymarket configuration. If None, loads from default location.
        """
        self.config = config or PolymarketConfig.load()
        self._session: Optional[aiohttp.ClientSession] = None

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

    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

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

    def _run(self, coro):
        """Run async coroutine synchronously."""
        return asyncio.get_event_loop().run_until_complete(coro)

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

    def close(self):
        """Close the HTTP session."""
        if self._api:
            self._run(self._api.close())
