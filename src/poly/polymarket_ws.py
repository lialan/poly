"""WebSocket-based Polymarket API for real-time market data streaming.

This module provides persistent WebSocket connections for low-latency
market data updates. Prefer this over HTTP polling when:
- Streaming continuous updates
- Running a trading bot
- Need latency < 150ms per update

Usage:
    async with PolymarketWS() as ws:
        # Subscribe to a market
        await ws.subscribe(token_id)

        # Receive updates
        async for update in ws.updates():
            print(f"Price: {update.price}, Size: {update.size}")

    # Or with callback:
    async with PolymarketWS(on_update=handle_update) as ws:
        await ws.subscribe(token_id)
        await ws.run_forever()
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import AsyncIterator, Callable, Optional

import aiohttp

logger = logging.getLogger(__name__)

WS_ENDPOINT = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
RECONNECT_DELAY_BASE = 1.0  # Base delay in seconds
RECONNECT_DELAY_MAX = 30.0  # Maximum delay
HEARTBEAT_INTERVAL = 30.0  # Seconds between heartbeats


class UpdateType(str, Enum):
    """Type of market update."""

    BOOK = "book"  # Full orderbook snapshot
    PRICE_CHANGE = "price_change"  # Best price changed
    TRADE = "trade"  # Trade executed
    UNKNOWN = "unknown"


@dataclass
class OrderLevel:
    """Single price level in orderbook."""

    price: Decimal
    size: Decimal

    def __repr__(self) -> str:
        return f"({float(self.price):.4f}, {float(self.size):.2f})"


@dataclass
class MarketUpdate:
    """Real-time market update from WebSocket."""

    token_id: str
    timestamp: float
    update_type: UpdateType = UpdateType.UNKNOWN

    # Price data (for price_change updates)
    best_bid: Optional[Decimal] = None
    best_ask: Optional[Decimal] = None
    mid_price: Optional[Decimal] = None

    # Full orderbook (for book updates)
    bids: list[OrderLevel] = field(default_factory=list)
    asks: list[OrderLevel] = field(default_factory=list)

    # Trade data (for trade updates)
    trade_price: Optional[Decimal] = None
    trade_size: Optional[Decimal] = None
    trade_side: Optional[str] = None  # "buy" or "sell"

    # Raw message for debugging
    raw: Optional[dict] = None

    @property
    def spread(self) -> Optional[Decimal]:
        """Bid-ask spread."""
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None

    def __repr__(self) -> str:
        if self.update_type == UpdateType.PRICE_CHANGE:
            bid = f"{float(self.best_bid):.4f}" if self.best_bid else "N/A"
            ask = f"{float(self.best_ask):.4f}" if self.best_ask else "N/A"
            return f"MarketUpdate(token={self.token_id[:16]}..., bid={bid}, ask={ask})"
        elif self.update_type == UpdateType.BOOK:
            return f"MarketUpdate(token={self.token_id[:16]}..., bids={len(self.bids)}, asks={len(self.asks)})"
        elif self.update_type == UpdateType.TRADE:
            return f"MarketUpdate(token={self.token_id[:16]}..., trade={self.trade_side}@{self.trade_price})"
        return f"MarketUpdate(token={self.token_id[:16]}..., type={self.update_type})"


@dataclass
class ConnectionStats:
    """WebSocket connection statistics."""

    connected_at: Optional[float] = None
    messages_received: int = 0
    reconnect_count: int = 0
    last_message_at: Optional[float] = None
    total_bytes_received: int = 0

    @property
    def uptime_seconds(self) -> float:
        """Connection uptime in seconds."""
        if self.connected_at:
            return time.time() - self.connected_at
        return 0.0

    @property
    def messages_per_second(self) -> float:
        """Average messages per second."""
        if self.uptime_seconds > 0:
            return self.messages_received / self.uptime_seconds
        return 0.0


class PolymarketWS:
    """WebSocket client for real-time Polymarket data.

    Features:
    - Persistent connection with auto-reconnect
    - Subscribe/unsubscribe to multiple markets
    - Callback or async iterator interface
    - Connection statistics tracking

    Args:
        endpoint: WebSocket endpoint URL.
        on_update: Optional callback for updates.
        on_connect: Optional callback when connected.
        on_disconnect: Optional callback when disconnected.
        auto_reconnect: Whether to auto-reconnect on disconnect.
        max_reconnect_attempts: Max reconnection attempts (0 = unlimited).
    """

    def __init__(
        self,
        endpoint: str = WS_ENDPOINT,
        on_update: Optional[Callable[[MarketUpdate], None]] = None,
        on_connect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
        auto_reconnect: bool = True,
        max_reconnect_attempts: int = 0,
    ):
        self.endpoint = endpoint
        self.on_update = on_update
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.auto_reconnect = auto_reconnect
        self.max_reconnect_attempts = max_reconnect_attempts

        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._subscribed_tokens: set[str] = set()
        self._running = False
        self._update_queue: asyncio.Queue[MarketUpdate] = asyncio.Queue()
        self._reconnect_count = 0
        self.stats = ConnectionStats()

    async def __aenter__(self) -> "PolymarketWS":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()

    async def connect(self) -> None:
        """Establish WebSocket connection."""
        if self._session is None:
            self._session = aiohttp.ClientSession()

        try:
            logger.info(f"Connecting to {self.endpoint}")
            self._ws = await self._session.ws_connect(
                self.endpoint,
                timeout=aiohttp.ClientTimeout(total=10),
                heartbeat=HEARTBEAT_INTERVAL,
            )
            self.stats.connected_at = time.time()
            self._running = True

            # Resubscribe to tokens if reconnecting
            if self._subscribed_tokens:
                await self._send_subscription(list(self._subscribed_tokens))

            if self.on_connect:
                self.on_connect()

            logger.info("WebSocket connected")

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            raise

    async def close(self) -> None:
        """Close WebSocket connection and cleanup."""
        self._running = False

        if self._ws and not self._ws.closed:
            await self._ws.close()
            self._ws = None

        if self._session:
            await self._session.close()
            self._session = None

        if self.on_disconnect:
            self.on_disconnect()

        logger.info("WebSocket closed")

    async def subscribe(self, token_ids: str | list[str]) -> None:
        """Subscribe to market updates for token(s).

        Args:
            token_ids: Single token ID or list of token IDs.
        """
        if isinstance(token_ids, str):
            token_ids = [token_ids]

        new_tokens = set(token_ids) - self._subscribed_tokens
        if not new_tokens:
            return

        self._subscribed_tokens.update(new_tokens)
        await self._send_subscription(list(new_tokens))
        logger.info(f"Subscribed to {len(new_tokens)} token(s)")

    async def unsubscribe(self, token_ids: str | list[str]) -> None:
        """Unsubscribe from market updates.

        Args:
            token_ids: Single token ID or list of token IDs.
        """
        if isinstance(token_ids, str):
            token_ids = [token_ids]

        self._subscribed_tokens -= set(token_ids)
        # Note: Polymarket WS doesn't have explicit unsubscribe
        # Just remove from our tracking set
        logger.info(f"Unsubscribed from {len(token_ids)} token(s)")

    async def _send_subscription(self, token_ids: list[str]) -> None:
        """Send subscription message."""
        if not self._ws or self._ws.closed:
            raise RuntimeError("WebSocket not connected")

        message = {
            "assets_ids": token_ids,
            "type": "market",
        }
        await self._ws.send_json(message)
        logger.debug(f"Sent subscription for {len(token_ids)} tokens")

    async def _handle_message(self, msg: aiohttp.WSMessage) -> Optional[MarketUpdate]:
        """Parse WebSocket message into MarketUpdate."""
        self.stats.messages_received += 1
        self.stats.last_message_at = time.time()

        if msg.type == aiohttp.WSMsgType.TEXT:
            self.stats.total_bytes_received += len(msg.data)
            try:
                data = json.loads(msg.data)
                return self._parse_update(data)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse message: {e}")
                return None

        elif msg.type == aiohttp.WSMsgType.BINARY:
            self.stats.total_bytes_received += len(msg.data)
            try:
                data = json.loads(msg.data.decode())
                return self._parse_update(data)
            except Exception as e:
                logger.warning(f"Failed to parse binary message: {e}")
                return None

        elif msg.type == aiohttp.WSMsgType.ERROR:
            logger.error(f"WebSocket error: {msg.data}")
            return None

        elif msg.type == aiohttp.WSMsgType.CLOSED:
            logger.info("WebSocket closed by server")
            return None

        return None

    def _parse_update(self, data: dict | list) -> Optional[MarketUpdate]:
        """Parse raw message data into MarketUpdate.

        Polymarket WS message formats:
        1. Initial book: list with single dict containing full orderbook
           [{"market": "...", "asset_id": "...", "bids": [...], "asks": [...], "event_type": "book"}]
        2. Price changes: dict with price_changes array
           {"market": "...", "price_changes": [...], "event_type": "price_change"}
        """
        # Handle list of updates (initial book snapshot)
        if isinstance(data, list):
            if not data:
                return None
            # Process first item (usually the only one)
            data = data[0] if len(data) == 1 else data[0]

        if not isinstance(data, dict):
            return None

        event_type = data.get("event_type", "")
        token_id = data.get("asset_id") or ""

        # Full orderbook update (event_type: "book")
        if event_type == "book" or ("bids" in data and "asks" in data):
            bids = [
                OrderLevel(
                    price=Decimal(str(level.get("price", 0))),
                    size=Decimal(str(level.get("size", 0))),
                )
                for level in data.get("bids", [])
            ]
            asks = [
                OrderLevel(
                    price=Decimal(str(level.get("price", 0))),
                    size=Decimal(str(level.get("size", 0))),
                )
                for level in data.get("asks", [])
            ]

            # Bids are sorted ascending, best (highest) is last
            # Asks are sorted descending, best (lowest) is last
            best_bid = bids[-1].price if bids else None
            best_ask = asks[-1].price if asks else None
            mid = (best_bid + best_ask) / 2 if best_bid and best_ask else None

            # Get last trade price if available
            last_trade = data.get("last_trade_price")
            trade_price = Decimal(str(last_trade)) if last_trade else None

            return MarketUpdate(
                token_id=token_id,
                timestamp=time.time(),
                update_type=UpdateType.BOOK,
                bids=bids,
                asks=asks,
                best_bid=best_bid,
                best_ask=best_ask,
                mid_price=mid,
                trade_price=trade_price,
                raw=data,
            )

        # Price change update (event_type: "price_change")
        elif event_type == "price_change" or "price_changes" in data:
            price_changes = data.get("price_changes", [])
            if not price_changes:
                return None

            # Return first price change (usually for subscribed token)
            change = price_changes[0]
            token_id = change.get("asset_id", "")
            best_bid = change.get("best_bid")
            best_ask = change.get("best_ask")

            return MarketUpdate(
                token_id=token_id,
                timestamp=time.time(),
                update_type=UpdateType.PRICE_CHANGE,
                best_bid=Decimal(str(best_bid)) if best_bid else None,
                best_ask=Decimal(str(best_ask)) if best_ask else None,
                mid_price=(Decimal(str(best_bid)) + Decimal(str(best_ask))) / 2
                if best_bid and best_ask else None,
                trade_price=Decimal(str(change.get("price", 0))),
                trade_size=Decimal(str(change.get("size", 0))),
                trade_side=change.get("side"),
                raw=data,
            )

        # Trade update
        elif "trade" in data or (data.get("side") and "price" in data):
            return MarketUpdate(
                token_id=token_id,
                timestamp=time.time(),
                update_type=UpdateType.TRADE,
                trade_price=Decimal(str(data.get("price", 0))),
                trade_size=Decimal(str(data.get("size", 0))),
                trade_side=data.get("side"),
                raw=data,
            )

        # Unknown format - return with raw data
        return MarketUpdate(
            token_id=token_id,
            timestamp=time.time(),
            update_type=UpdateType.UNKNOWN,
            raw=data,
        )

    async def updates(self) -> AsyncIterator[MarketUpdate]:
        """Async iterator for receiving updates.

        Usage:
            async for update in ws.updates():
                process(update)
        """
        while self._running:
            if not self._ws or self._ws.closed:
                if self.auto_reconnect:
                    await self._reconnect()
                    continue
                else:
                    break

            try:
                msg = await asyncio.wait_for(
                    self._ws.receive(),
                    timeout=60.0,
                )

                if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                    if self.auto_reconnect:
                        await self._reconnect()
                        continue
                    break

                update = await self._handle_message(msg)
                if update:
                    yield update

            except asyncio.TimeoutError:
                # No message received, continue waiting
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error receiving message: {e}")
                if self.auto_reconnect:
                    await self._reconnect()
                else:
                    break

    async def run_forever(self) -> None:
        """Run WebSocket loop with callback mode.

        Use this when providing on_update callback.
        """
        async for update in self.updates():
            if self.on_update:
                try:
                    self.on_update(update)
                except Exception as e:
                    logger.error(f"Error in update callback: {e}")

    async def receive_one(self, timeout: float = 5.0) -> Optional[MarketUpdate]:
        """Receive a single update with timeout.

        Args:
            timeout: Seconds to wait for message.

        Returns:
            MarketUpdate or None if timeout.
        """
        if not self._ws or self._ws.closed:
            raise RuntimeError("WebSocket not connected")

        try:
            msg = await asyncio.wait_for(
                self._ws.receive(),
                timeout=timeout,
            )
            return await self._handle_message(msg)
        except asyncio.TimeoutError:
            return None

    async def _reconnect(self) -> None:
        """Attempt to reconnect with exponential backoff."""
        if self.max_reconnect_attempts > 0 and self._reconnect_count >= self.max_reconnect_attempts:
            logger.error("Max reconnection attempts reached")
            self._running = False
            return

        delay = min(
            RECONNECT_DELAY_BASE * (2 ** self._reconnect_count),
            RECONNECT_DELAY_MAX,
        )
        self._reconnect_count += 1
        self.stats.reconnect_count += 1

        logger.info(f"Reconnecting in {delay:.1f}s (attempt {self._reconnect_count})")
        await asyncio.sleep(delay)

        try:
            if self._ws and not self._ws.closed:
                await self._ws.close()

            await self.connect()
            self._reconnect_count = 0  # Reset on successful connection

        except Exception as e:
            logger.error(f"Reconnection failed: {e}")

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._ws is not None and not self._ws.closed

    @property
    def subscribed_tokens(self) -> set[str]:
        """Get set of subscribed token IDs."""
        return self._subscribed_tokens.copy()


class MultiMarketWS:
    """Manage WebSocket subscriptions for multiple markets.

    Provides a higher-level interface for subscribing to markets
    by slug instead of token ID.

    Usage:
        async with MultiMarketWS() as ws:
            await ws.add_market("btc-updown-15m-1234567890")
            async for slug, update in ws.updates():
                print(f"{slug}: {update}")
    """

    def __init__(self, **kwargs):
        """Initialize with same options as PolymarketWS."""
        self._ws = PolymarketWS(**kwargs)
        self._token_to_slug: dict[str, str] = {}
        self._slug_to_tokens: dict[str, tuple[str, str]] = {}  # (yes_token, no_token)

    async def __aenter__(self) -> "MultiMarketWS":
        await self._ws.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self._ws.close()

    async def add_market(
        self,
        slug: str,
        yes_token_id: str,
        no_token_id: str,
    ) -> None:
        """Add a market to track by slug and token IDs.

        Args:
            slug: Market slug (e.g., "btc-updown-15m-1234567890").
            yes_token_id: Token ID for YES outcome.
            no_token_id: Token ID for NO outcome.
        """
        self._slug_to_tokens[slug] = (yes_token_id, no_token_id)
        self._token_to_slug[yes_token_id] = slug
        self._token_to_slug[no_token_id] = slug

        await self._ws.subscribe([yes_token_id, no_token_id])

    async def remove_market(self, slug: str) -> None:
        """Remove a market from tracking."""
        if slug not in self._slug_to_tokens:
            return

        yes_token, no_token = self._slug_to_tokens.pop(slug)
        self._token_to_slug.pop(yes_token, None)
        self._token_to_slug.pop(no_token, None)

        await self._ws.unsubscribe([yes_token, no_token])

    async def updates(self) -> AsyncIterator[tuple[str, str, MarketUpdate]]:
        """Async iterator yielding (slug, side, update) tuples.

        side is "yes" or "no" depending on which token updated.
        """
        async for update in self._ws.updates():
            slug = self._token_to_slug.get(update.token_id)
            if slug:
                tokens = self._slug_to_tokens.get(slug)
                if tokens:
                    side = "yes" if update.token_id == tokens[0] else "no"
                    yield slug, side, update

    @property
    def is_connected(self) -> bool:
        return self._ws.is_connected

    @property
    def stats(self) -> ConnectionStats:
        return self._ws.stats


# =============================================================================
# Convenience Functions
# =============================================================================


async def stream_market(
    token_id: str,
    callback: Callable[[MarketUpdate], None],
    duration: Optional[float] = None,
) -> None:
    """Stream market updates for a single token.

    Args:
        token_id: Token ID to subscribe to.
        callback: Function to call with each update.
        duration: Optional duration in seconds (None = forever).
    """
    start = time.time()

    async with PolymarketWS() as ws:
        await ws.subscribe(token_id)

        async for update in ws.updates():
            callback(update)

            if duration and (time.time() - start) >= duration:
                break


async def get_orderbook_updates(
    token_id: str,
    count: int = 10,
    timeout: float = 30.0,
) -> list[MarketUpdate]:
    """Get a specific number of orderbook updates.

    Args:
        token_id: Token ID to subscribe to.
        count: Number of updates to collect.
        timeout: Maximum time to wait.

    Returns:
        List of MarketUpdate objects.
    """
    updates = []
    start = time.time()

    async with PolymarketWS() as ws:
        await ws.subscribe(token_id)

        async for update in ws.updates():
            updates.append(update)

            if len(updates) >= count:
                break

            if (time.time() - start) >= timeout:
                break

    return updates
