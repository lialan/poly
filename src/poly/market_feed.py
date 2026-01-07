"""Market data feed service using WebSocket.

A daemon-like service that maintains a persistent WebSocket connection
and streams real-time market data for multiple markets.

Usage:
    # Create feed with callback
    feed = MarketFeed(on_update=handle_update)

    # Add markets to monitor
    await feed.add_market("btc-updown-15m-1234567890", yes_token, no_token)
    await feed.add_market("eth-updown-15m-1234567890", yes_token, no_token)

    # Start the feed (runs forever)
    await feed.start()

    # Or run in background
    task = asyncio.create_task(feed.start())
    # ... do other things ...
    await feed.stop()
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Callable, Optional

import aiohttp

logger = logging.getLogger(__name__)

WS_ENDPOINT = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
RECONNECT_DELAY_BASE = 1.0
RECONNECT_DELAY_MAX = 30.0
HEARTBEAT_INTERVAL = 30.0


class Side(str, Enum):
    YES = "yes"
    NO = "no"


@dataclass
class PriceUpdate:
    """Simplified price update for a market."""

    timestamp: float
    market_slug: str
    side: Side
    best_bid: Optional[Decimal] = None
    best_ask: Optional[Decimal] = None
    last_price: Optional[Decimal] = None
    last_size: Optional[Decimal] = None
    last_side: Optional[str] = None  # "BUY" or "SELL"

    @property
    def mid(self) -> Optional[Decimal]:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return self.best_bid or self.best_ask

    @property
    def spread(self) -> Optional[Decimal]:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None

    def __repr__(self) -> str:
        bid = f"{self.best_bid:.4f}" if self.best_bid else "N/A"
        ask = f"{self.best_ask:.4f}" if self.best_ask else "N/A"
        return f"PriceUpdate({self.market_slug}, {self.side.value}: {bid}/{ask})"


@dataclass
class MarketState:
    """Current state of a monitored market."""

    slug: str
    yes_token_id: str
    no_token_id: str

    # Latest prices
    yes_bid: Optional[Decimal] = None
    yes_ask: Optional[Decimal] = None
    no_bid: Optional[Decimal] = None
    no_ask: Optional[Decimal] = None

    # Last update time
    last_update: float = 0.0
    update_count: int = 0

    @property
    def yes_mid(self) -> Optional[Decimal]:
        if self.yes_bid and self.yes_ask:
            return (self.yes_bid + self.yes_ask) / 2
        return self.yes_bid or self.yes_ask

    @property
    def no_mid(self) -> Optional[Decimal]:
        if self.no_bid and self.no_ask:
            return (self.no_bid + self.no_ask) / 2
        return self.no_bid or self.no_ask

    @property
    def implied_prob(self) -> Optional[float]:
        """Implied probability from YES mid price."""
        if self.yes_mid:
            return float(self.yes_mid)
        return None


@dataclass
class FeedStats:
    """Statistics for the market feed."""

    connected_at: Optional[float] = None
    messages_received: int = 0
    updates_processed: int = 0
    reconnect_count: int = 0
    last_message_at: Optional[float] = None
    bytes_received: int = 0

    @property
    def uptime(self) -> float:
        if self.connected_at:
            return time.time() - self.connected_at
        return 0.0

    @property
    def msg_per_sec(self) -> float:
        if self.uptime > 0:
            return self.messages_received / self.uptime
        return 0.0


class MarketFeed:
    """Daemon-like service for streaming market data.

    Maintains a single WebSocket connection to monitor multiple markets.
    Automatically reconnects on disconnection.

    Args:
        on_update: Callback for price updates. Called with PriceUpdate.
        on_connect: Callback when connected.
        on_disconnect: Callback when disconnected.
        endpoint: WebSocket endpoint URL.
    """

    def __init__(
        self,
        on_update: Optional[Callable[[PriceUpdate], None]] = None,
        on_connect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
        endpoint: str = WS_ENDPOINT,
    ):
        self.endpoint = endpoint
        self.on_update = on_update
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect

        # Market tracking
        self._markets: dict[str, MarketState] = {}  # slug -> MarketState
        self._token_to_market: dict[str, tuple[str, Side]] = {}  # token_id -> (slug, side)

        # Connection state
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._running = False
        self._reconnect_count = 0

        # Stats
        self.stats = FeedStats()

        # Update queue for async consumers
        self._update_queue: asyncio.Queue[PriceUpdate] = asyncio.Queue()

    async def add_market(
        self,
        slug: str,
        yes_token_id: str,
        no_token_id: str,
    ) -> None:
        """Add a market to monitor.

        Args:
            slug: Market slug (e.g., "btc-updown-15m-1234567890").
            yes_token_id: Token ID for YES/UP outcome.
            no_token_id: Token ID for NO/DOWN outcome.
        """
        # Store market state
        self._markets[slug] = MarketState(
            slug=slug,
            yes_token_id=yes_token_id,
            no_token_id=no_token_id,
        )

        # Map tokens to market
        self._token_to_market[yes_token_id] = (slug, Side.YES)
        self._token_to_market[no_token_id] = (slug, Side.NO)

        # Subscribe if already connected
        if self._ws and not self._ws.closed:
            await self._subscribe([yes_token_id, no_token_id])

        logger.info(f"Added market: {slug}")

    async def remove_market(self, slug: str) -> None:
        """Remove a market from monitoring."""
        if slug not in self._markets:
            return

        market = self._markets.pop(slug)
        self._token_to_market.pop(market.yes_token_id, None)
        self._token_to_market.pop(market.no_token_id, None)

        logger.info(f"Removed market: {slug}")

    def get_market(self, slug: str) -> Optional[MarketState]:
        """Get current state of a market."""
        return self._markets.get(slug)

    def get_all_markets(self) -> dict[str, MarketState]:
        """Get all monitored markets."""
        return self._markets.copy()

    async def start(self) -> None:
        """Start the feed service. Runs forever until stop() is called."""
        self._running = True

        while self._running:
            try:
                await self._connect()
                await self._run_loop()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Feed error: {e}")
                if self._running:
                    await self._reconnect()

        await self._cleanup()

    async def stop(self) -> None:
        """Stop the feed service."""
        self._running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()

    async def updates(self):
        """Async iterator for updates (alternative to callback)."""
        while self._running:
            try:
                update = await asyncio.wait_for(
                    self._update_queue.get(),
                    timeout=1.0,
                )
                yield update
            except asyncio.TimeoutError:
                continue

    async def _connect(self) -> None:
        """Establish WebSocket connection."""
        if self._session is None:
            self._session = aiohttp.ClientSession()

        logger.info(f"Connecting to {self.endpoint}")
        self._ws = await self._session.ws_connect(
            self.endpoint,
            timeout=aiohttp.ClientTimeout(total=10),
            heartbeat=HEARTBEAT_INTERVAL,
        )

        self.stats.connected_at = time.time()
        self._reconnect_count = 0

        # Subscribe to all markets
        all_tokens = []
        for market in self._markets.values():
            all_tokens.extend([market.yes_token_id, market.no_token_id])

        if all_tokens:
            await self._subscribe(all_tokens)

        if self.on_connect:
            self.on_connect()

        logger.info(f"Connected, subscribed to {len(self._markets)} market(s)")

    async def _subscribe(self, token_ids: list[str]) -> None:
        """Send subscription message."""
        if not self._ws or self._ws.closed:
            return

        message = {
            "assets_ids": token_ids,
            "type": "market",
        }
        await self._ws.send_json(message)

    async def _run_loop(self) -> None:
        """Main message processing loop."""
        while self._running and self._ws and not self._ws.closed:
            try:
                msg = await asyncio.wait_for(
                    self._ws.receive(),
                    timeout=60.0,
                )

                if msg.type == aiohttp.WSMsgType.TEXT:
                    self.stats.messages_received += 1
                    self.stats.last_message_at = time.time()
                    self.stats.bytes_received += len(msg.data)

                    await self._handle_message(msg.data)

                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                    logger.info("WebSocket closed")
                    break

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {msg.data}")
                    break

            except asyncio.TimeoutError:
                continue

    async def _handle_message(self, data: str) -> None:
        """Parse and process a WebSocket message."""
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            return

        # Handle list (initial book snapshot)
        if isinstance(parsed, list):
            for item in parsed:
                await self._process_update(item)
        else:
            await self._process_update(parsed)

    async def _process_update(self, data: dict) -> None:
        """Process a single update message."""
        event_type = data.get("event_type", "")

        if event_type == "book":
            # Full orderbook snapshot
            token_id = data.get("asset_id", "")
            if token_id not in self._token_to_market:
                return

            slug, side = self._token_to_market[token_id]
            market = self._markets.get(slug)
            if not market:
                return

            bids = data.get("bids", [])
            asks = data.get("asks", [])

            best_bid = Decimal(str(bids[-1]["price"])) if bids else None
            best_ask = Decimal(str(asks[-1]["price"])) if asks else None

            # Update market state
            if side == Side.YES:
                market.yes_bid = best_bid
                market.yes_ask = best_ask
            else:
                market.no_bid = best_bid
                market.no_ask = best_ask

            market.last_update = time.time()
            market.update_count += 1
            self.stats.updates_processed += 1

            # Create update and dispatch
            update = PriceUpdate(
                timestamp=time.time(),
                market_slug=slug,
                side=side,
                best_bid=best_bid,
                best_ask=best_ask,
                last_price=Decimal(str(data.get("last_trade_price", 0))) if data.get("last_trade_price") else None,
            )

            await self._dispatch_update(update)

        elif event_type == "price_change":
            # Price change updates
            for change in data.get("price_changes", []):
                token_id = change.get("asset_id", "")
                if token_id not in self._token_to_market:
                    continue

                slug, side = self._token_to_market[token_id]
                market = self._markets.get(slug)
                if not market:
                    continue

                best_bid = change.get("best_bid")
                best_ask = change.get("best_ask")

                if best_bid:
                    best_bid = Decimal(str(best_bid))
                if best_ask:
                    best_ask = Decimal(str(best_ask))

                # Update market state
                if side == Side.YES:
                    if best_bid:
                        market.yes_bid = best_bid
                    if best_ask:
                        market.yes_ask = best_ask
                else:
                    if best_bid:
                        market.no_bid = best_bid
                    if best_ask:
                        market.no_ask = best_ask

                market.last_update = time.time()
                market.update_count += 1
                self.stats.updates_processed += 1

                # Create update and dispatch
                update = PriceUpdate(
                    timestamp=time.time(),
                    market_slug=slug,
                    side=side,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    last_price=Decimal(str(change.get("price", 0))) if change.get("price") else None,
                    last_size=Decimal(str(change.get("size", 0))) if change.get("size") else None,
                    last_side=change.get("side"),
                )

                await self._dispatch_update(update)

    async def _dispatch_update(self, update: PriceUpdate) -> None:
        """Dispatch update to callback and queue."""
        # Callback
        if self.on_update:
            try:
                self.on_update(update)
            except Exception as e:
                logger.error(f"Update callback error: {e}")

        # Queue for async consumers
        try:
            self._update_queue.put_nowait(update)
        except asyncio.QueueFull:
            pass  # Drop if queue is full

    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        delay = min(
            RECONNECT_DELAY_BASE * (2 ** self._reconnect_count),
            RECONNECT_DELAY_MAX,
        )
        self._reconnect_count += 1
        self.stats.reconnect_count += 1

        logger.info(f"Reconnecting in {delay:.1f}s (attempt {self._reconnect_count})")

        if self.on_disconnect:
            self.on_disconnect()

        await asyncio.sleep(delay)

    async def _cleanup(self) -> None:
        """Clean up resources."""
        if self._ws and not self._ws.closed:
            await self._ws.close()

        if self._session:
            await self._session.close()
            self._session = None

        if self.on_disconnect:
            self.on_disconnect()

        logger.info("Feed stopped")

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._ws is not None and not self._ws.closed

    @property
    def market_count(self) -> int:
        """Number of monitored markets."""
        return len(self._markets)
