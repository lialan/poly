"""
OCO (One-Cancels-Other) Limit Order Strategy for Polymarket.

============================================================
STRATEGY OVERVIEW
============================================================

This is a client-side OCO strategy. Polymarket does NOT support OCO natively.

The strategy:
1. Fetches the current market for the specified asset/horizon
2. Places TWO limit BUY orders simultaneously at threshold price (default 0.8):
   - Order A: BUY UP (YES) token at threshold (fills when UP prob >= 80%)
   - Order B: BUY DOWN (NO) token at threshold (fills when DOWN prob >= 80%)

3. Monitors order/trade status updates.

4. When either order's trade reaches MINED status:
   - Cancels the other order immediately
   - Transitions to terminal DONE state
   - Stops processing further events

============================================================
WHY MINED (NOT FILLED/MATCHED)?
============================================================

Order lifecycle:
  Order:  LIVE -> MATCHED (filled, has trades) -> terminal
  Trade:  MATCHED -> MINED -> CONFIRMED

- MATCHED (Order): Order was matched in the orderbook. However, the trade
  has NOT yet been executed on-chain. It could still fail (RETRYING/FAILED).

- MINED (Trade): The trade has been observed ON-CHAIN. This is the point
  of no return - the trade WILL complete (even if confirmation takes time).

We trigger OCO on MINED because:
1. It guarantees the winning side has committed on-chain
2. MATCHED is premature - the trade could still fail/retry
3. CONFIRMED is too late - we want to cancel the other side ASAP

============================================================
WHY LIMIT ORDERS ACT AS TRIGGERS
============================================================

Limit BUY at price P means: "Execute ONLY if someone sells at <= P"

In prediction markets:
- If UP probability rises sharply -> UP token price rises -> DOWN falls
- Our DOWN limit buy at P becomes more likely to fill
- Conversely for UP

The limit orders act as IMPLICIT triggers based on market movement.
We don't need to poll prices - the orderbook matching does the work.

============================================================
STATE MACHINE
============================================================

    INIT ──[place orders]──> WAIT
                               │
         ┌─────────────────────┴─────────────────────┐
         │                                           │
    [UP trade MINED]                          [DOWN trade MINED]
         │                                           │
         v                                           v
    cancel DOWN                                 cancel UP
         │                                           │
         └─────────────────────┬─────────────────────┘
                               │
                               v
                             DONE

Edge cases:
- Both MINED simultaneously -> record anomaly, no further cancellation
- Cancel fails -> log failure, still transition to DONE
- Timeout (optional) -> cancel both, winner=None

============================================================
USAGE
============================================================

```python
from poly import PolymarketAPI, PolymarketConfig, Asset, MarketHorizon
from poly.strategies import OCOLimitStrategy, OCOConfig

config = OCOConfig(
    asset=Asset.BTC,           # BTC or ETH
    horizon=MarketHorizon.M15, # M15, H1, H4, or D1
    size=100.0,                # Size in shares
    threshold=0.8,             # Limit price for both (default: 0.8)
    dry_run=False,             # Set True for simulation
)

async with PolymarketAPI(PolymarketConfig.load()) as api:
    strategy = OCOLimitStrategy(config, api)
    await strategy.start()

    # Feed order updates (from polling loop or external source)
    while not strategy.is_done:
        # Poll for updates or receive from event source
        event = await get_next_order_event()  # Your implementation
        await strategy.on_order_update(event)

    result = strategy.result
    print(f"Winner: {result.winner}, Order ID: {result.winning_order_id}")
```

============================================================
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional, Protocol

if TYPE_CHECKING:
    from poly.api.polymarket import PolymarketAPI

logger = logging.getLogger(__name__)


# ============================================================
# Enums
# ============================================================


class OCOState(str, Enum):
    """Strategy state machine states."""

    INIT = "INIT"  # Not yet started
    WAIT = "WAIT"  # Orders placed, waiting for MINED
    DONE = "DONE"  # Terminal state


class WinnerSide(str, Enum):
    """Which side won the OCO race."""

    UP = "UP"      # UP (YES) order was MINED first
    DOWN = "DOWN"  # DOWN (NO) order was MINED first
    NONE = "NONE"  # No winner (timeout or both cancelled)


class TradeStatusValue(str, Enum):
    """Expected trade status values (mirrors poly.api.polymarket.TradeStatus)."""

    MATCHED = "MATCHED"
    MINED = "MINED"
    CONFIRMED = "CONFIRMED"
    RETRYING = "RETRYING"
    FAILED = "FAILED"


# ============================================================
# Data Classes
# ============================================================


@dataclass
class OCOConfig:
    """Configuration for OCO strategy.

    Attributes:
        asset: Crypto asset (BTC or ETH)
        horizon: Market time horizon (M15, H1, H4, D1)
        threshold: Limit price for both UP and DOWN orders (default: 0.8)
                   - UP order: BUY at threshold (fills when UP prob >= threshold)
                   - DOWN order: BUY at threshold (fills when DOWN prob >= threshold)
        size: Order size in shares
        dry_run: If True, no real orders are placed
        timeout_sec: Optional timeout after which both orders are cancelled
    """

    asset: "Asset"
    horizon: "MarketHorizon"
    size: float
    threshold: float = 0.8
    dry_run: bool = False
    timeout_sec: Optional[float] = None

    def __post_init__(self):
        if not 0 < self.threshold < 1:
            raise ValueError(f"Threshold must be between 0 and 1, got {self.threshold}")
        if self.size <= 0:
            raise ValueError(f"Size must be positive, got {self.size}")


@dataclass
class OrderUpdateEvent:
    """Event representing an order or trade status update.

    This is the event structure the strategy expects to receive.
    Can be constructed from polling results or external event sources.

    Attributes:
        order_id: The order ID this event relates to
        order_status: Current order status (LIVE, MATCHED, CANCELLED, etc.)
        trade_id: Optional trade ID if this is a trade update
        trade_status: Optional trade status (MATCHED, MINED, CONFIRMED, etc.)
        timestamp: When this event occurred
    """

    order_id: str
    order_status: str
    trade_id: Optional[str] = None
    trade_status: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_trade_mined(self) -> bool:
        """Check if this event indicates a trade reached MINED status."""
        return self.trade_status == TradeStatusValue.MINED.value


@dataclass
class OCOResult:
    """Terminal result of the OCO strategy.

    Attributes:
        winner: Which side won (UP, DOWN, or NONE)
        winning_order_id: Order ID of the winning side
        winning_trade_id: Trade ID that triggered the win
        losing_order_id: Order ID of the cancelled side
        cancel_success: Whether cancellation succeeded
        dry_run: Whether this was a dry run
        anomaly: Description of any anomaly (e.g., both MINED)
        start_time: When strategy started
        end_time: When strategy reached terminal state
        market_slug: The market slug that was traded
        up_token_id: UP token ID
        down_token_id: DOWN token ID
    """

    winner: WinnerSide
    winning_order_id: Optional[str] = None
    winning_trade_id: Optional[str] = None
    losing_order_id: Optional[str] = None
    cancel_success: Optional[bool] = None
    dry_run: bool = False
    anomaly: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    market_slug: Optional[str] = None
    up_token_id: Optional[str] = None
    down_token_id: Optional[str] = None

    @property
    def duration_sec(self) -> Optional[float]:
        """Duration from start to end in seconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


@dataclass
class _OrderState:
    """Internal state for tracking an order."""

    order_id: Optional[str] = None
    status: str = "PENDING"
    trade_ids: list[str] = field(default_factory=list)
    is_mined: bool = False


# ============================================================
# API Protocol (for type checking and testing)
# ============================================================


class OrderAPI(Protocol):
    """Protocol for order placement/cancellation API."""

    async def place_order(
        self,
        token_id: str,
        side: "OrderSide",
        price: float,
        size: float,
    ) -> "OrderResult":
        ...

    async def cancel_order(self, order_id: str) -> bool:
        ...


# ============================================================
# OCO Strategy
# ============================================================


class OCOLimitStrategy:
    """
    Event-driven OCO (One-Cancels-Other) limit order strategy.

    Places two limit BUY orders (UP and DOWN) simultaneously.
    When either order's trade reaches MINED status, cancels the other.

    Thread-safety: This class is NOT thread-safe. All method calls
    should come from the same async context.
    """

    def __init__(
        self,
        config: OCOConfig,
        api: Optional["PolymarketAPI"] = None,
    ):
        """
        Initialize the OCO strategy.

        Args:
            config: Strategy configuration
            api: Polymarket API client (required if dry_run=False)
        """
        self._config = config
        self._api = api
        self._state = OCOState.INIT
        self._result: Optional[OCOResult] = None
        self._start_time: Optional[datetime] = None

        # Market info (populated in start())
        self._market_slug: Optional[str] = None
        self._up_token_id: Optional[str] = None
        self._down_token_id: Optional[str] = None

        # Internal order tracking
        self._up_order = _OrderState()
        self._down_order = _OrderState()

        # Action log for dry-run and debugging
        self._action_log: list[dict] = []

        # Validate API requirement
        if not config.dry_run and api is None:
            raise ValueError("API client required when dry_run=False")

    # ============================================================
    # Public Properties
    # ============================================================

    @property
    def state(self) -> OCOState:
        """Current strategy state."""
        return self._state

    @property
    def is_done(self) -> bool:
        """Whether strategy has reached terminal state."""
        return self._state == OCOState.DONE

    @property
    def result(self) -> Optional[OCOResult]:
        """Terminal result (None if not done)."""
        return self._result

    @property
    def config(self) -> OCOConfig:
        """Strategy configuration."""
        return self._config

    @property
    def action_log(self) -> list[dict]:
        """Log of all actions taken (useful for dry-run analysis)."""
        return self._action_log.copy()

    @property
    def up_order_id(self) -> Optional[str]:
        """UP order ID (None if not placed)."""
        return self._up_order.order_id

    @property
    def down_order_id(self) -> Optional[str]:
        """DOWN order ID (None if not placed)."""
        return self._down_order.order_id

    # ============================================================
    # Public Methods
    # ============================================================

    async def start(self) -> None:
        """
        Start the strategy by fetching current market and placing both limit orders.

        Transitions: INIT -> WAIT

        Raises:
            RuntimeError: If strategy already started or market not found
            TradingError: If order placement fails (live mode)
        """
        if self._state != OCOState.INIT:
            raise RuntimeError(f"Cannot start: state is {self._state}, expected INIT")

        self._start_time = datetime.now(timezone.utc)

        # Fetch current market to get token IDs
        await self._fetch_market()

        logger.info(
            f"OCO strategy starting: {self._config.asset.value}/{self._config.horizon.name} "
            f"slug={self._market_slug} "
            f"threshold={self._config.threshold} size={self._config.size} "
            f"dry_run={self._config.dry_run}"
        )

        # Place both orders at the threshold price
        up_order_id = await self._place_order("UP", self._up_token_id)
        down_order_id = await self._place_order("DOWN", self._down_token_id)

        self._up_order.order_id = up_order_id
        self._up_order.status = "LIVE"
        self._down_order.order_id = down_order_id
        self._down_order.status = "LIVE"

        self._state = OCOState.WAIT
        logger.info(
            f"OCO orders placed: UP={up_order_id} DOWN={down_order_id} -> WAIT state"
        )

    async def on_order_update(self, event: OrderUpdateEvent) -> None:
        """
        Process an order/trade status update event.

        This is the main event handler. Call this method whenever
        you receive an order or trade status update.

        The strategy will:
        - Ignore events if already DONE
        - Ignore events for unknown order IDs
        - Trigger OCO logic if a trade reaches MINED

        Args:
            event: The order update event to process
        """
        # Ignore events after terminal state (idempotent)
        if self._state == OCOState.DONE:
            logger.debug(f"Ignoring event in DONE state: {event}")
            return

        # Ignore events before started
        if self._state == OCOState.INIT:
            logger.debug(f"Ignoring event in INIT state: {event}")
            return

        # Identify which order this event is for
        is_up = event.order_id == self._up_order.order_id
        is_down = event.order_id == self._down_order.order_id

        if not is_up and not is_down:
            logger.debug(f"Ignoring event for unknown order: {event.order_id}")
            return

        order_state = self._up_order if is_up else self._down_order
        side = "UP" if is_up else "DOWN"

        # Update order status
        order_state.status = event.order_status
        if event.trade_id and event.trade_id not in order_state.trade_ids:
            order_state.trade_ids.append(event.trade_id)

        self._log_action("order_update", {
            "side": side,
            "order_id": event.order_id,
            "order_status": event.order_status,
            "trade_id": event.trade_id,
            "trade_status": event.trade_status,
        })

        # Check for MINED trigger
        if event.is_trade_mined:
            logger.info(f"Trade MINED detected for {side}: {event.trade_id}")
            await self._handle_mined(side, event)

    async def cancel_all(self, reason: str = "manual") -> None:
        """
        Cancel all orders and transition to DONE.

        Use this for timeout handling or manual abort.

        Args:
            reason: Reason for cancellation
        """
        if self._state == OCOState.DONE:
            return

        logger.info(f"Cancelling all orders: reason={reason}")

        up_cancelled = await self._cancel_order("UP", self._up_order.order_id)
        down_cancelled = await self._cancel_order("DOWN", self._down_order.order_id)

        self._finalize(
            winner=WinnerSide.NONE,
            winning_order_id=None,
            winning_trade_id=None,
            losing_order_id=None,
            cancel_success=up_cancelled and down_cancelled,
            anomaly=f"cancelled: {reason}",
        )

    # ============================================================
    # Private Methods
    # ============================================================

    async def _fetch_market(self) -> None:
        """Fetch current market to get token IDs."""
        from poly.markets import fetch_current_prediction

        self._log_action("fetch_market", {
            "asset": self._config.asset.value,
            "horizon": self._config.horizon.name,
        })

        if self._config.dry_run:
            # Generate fake token IDs for dry run
            self._market_slug = f"dry_run_{self._config.asset.value}_{self._config.horizon.name}"
            self._up_token_id = f"0xUP_{self._config.asset.value}_{id(self)}"
            self._down_token_id = f"0xDOWN_{self._config.asset.value}_{id(self)}"
            logger.info(f"[DRY RUN] Using fake market: {self._market_slug}")
            return

        market = await fetch_current_prediction(
            self._config.asset,
            self._config.horizon,
        )

        if not market:
            raise RuntimeError(
                f"No market found for {self._config.asset.value}/{self._config.horizon.name}"
            )

        self._market_slug = market.slug
        self._up_token_id = market.up_token_id
        self._down_token_id = market.down_token_id

        logger.info(
            f"Fetched market: {market.slug} "
            f"UP={market.up_token_id[:16]}... DOWN={market.down_token_id[:16]}..."
        )

    async def _place_order(self, side: str, token_id: str) -> str:
        """Place a limit BUY order at threshold price."""
        self._log_action("place_order", {
            "side": side,
            "token_id": token_id,
            "price": self._config.threshold,
            "size": self._config.size,
        })

        if self._config.dry_run:
            # Generate fake order ID for dry run
            fake_id = f"dry_run_{side.lower()}_{id(self)}"
            logger.info(f"[DRY RUN] Would place {side} order: {fake_id}")
            return fake_id

        # Import here to avoid circular imports
        from poly.api.polymarket import OrderSide

        result = await self._api.place_order(
            token_id=token_id,
            side=OrderSide.BUY,
            price=self._config.threshold,
            size=self._config.size,
        )

        if not result.success:
            raise RuntimeError(f"Failed to place {side} order: {result.error_message}")

        logger.info(f"Placed {side} order: {result.order_id}")
        return result.order_id

    async def _cancel_order(self, side: str, order_id: Optional[str]) -> bool:
        """Cancel an order. Returns True if successful or not needed."""
        if order_id is None:
            return True

        self._log_action("cancel_order", {
            "side": side,
            "order_id": order_id,
        })

        if self._config.dry_run:
            logger.info(f"[DRY RUN] Would cancel {side} order: {order_id}")
            return True

        try:
            success = await self._api.cancel_order(order_id)
            if success:
                logger.info(f"Cancelled {side} order: {order_id}")
            else:
                logger.warning(f"Cancel returned False for {side} order: {order_id}")
            return success
        except Exception as e:
            # Cancellation failure should NOT crash the strategy
            logger.error(f"Failed to cancel {side} order {order_id}: {e}")
            self._log_action("cancel_failed", {
                "side": side,
                "order_id": order_id,
                "error": str(e),
            })
            return False

    async def _handle_mined(self, winning_side: str, event: OrderUpdateEvent) -> None:
        """Handle a trade reaching MINED status."""
        other_side = "DOWN" if winning_side == "UP" else "UP"
        other_order = self._down_order if winning_side == "UP" else self._up_order
        winning_order = self._up_order if winning_side == "UP" else self._down_order

        # Check for race condition: both already MINED
        if winning_order.is_mined and other_order.is_mined:
            logger.error("ANOMALY: Both orders already MINED!")
            self._finalize(
                winner=WinnerSide.UP if winning_side == "UP" else WinnerSide.DOWN,
                winning_order_id=event.order_id,
                winning_trade_id=event.trade_id,
                losing_order_id=other_order.order_id,
                cancel_success=False,
                anomaly="both_orders_mined",
            )
            return

        # Mark as MINED
        winning_order.is_mined = True

        # Check if other side also just got MINED (race)
        if other_order.is_mined:
            logger.error(f"ANOMALY: {other_side} was already MINED when {winning_side} MINED!")
            self._finalize(
                winner=WinnerSide.UP if winning_side == "UP" else WinnerSide.DOWN,
                winning_order_id=event.order_id,
                winning_trade_id=event.trade_id,
                losing_order_id=other_order.order_id,
                cancel_success=False,
                anomaly="race_condition_both_mined",
            )
            return

        # Normal case: cancel the other order
        logger.info(f"{winning_side} MINED first, cancelling {other_side}")
        cancel_success = await self._cancel_order(other_side, other_order.order_id)

        self._finalize(
            winner=WinnerSide.UP if winning_side == "UP" else WinnerSide.DOWN,
            winning_order_id=event.order_id,
            winning_trade_id=event.trade_id,
            losing_order_id=other_order.order_id,
            cancel_success=cancel_success,
            anomaly=None if cancel_success else "cancel_failed",
        )

    def _finalize(
        self,
        winner: WinnerSide,
        winning_order_id: Optional[str],
        winning_trade_id: Optional[str],
        losing_order_id: Optional[str],
        cancel_success: Optional[bool],
        anomaly: Optional[str],
    ) -> None:
        """Transition to terminal DONE state."""
        end_time = datetime.now(timezone.utc)

        self._result = OCOResult(
            winner=winner,
            winning_order_id=winning_order_id,
            winning_trade_id=winning_trade_id,
            losing_order_id=losing_order_id,
            cancel_success=cancel_success,
            dry_run=self._config.dry_run,
            anomaly=anomaly,
            start_time=self._start_time,
            end_time=end_time,
            market_slug=self._market_slug,
            up_token_id=self._up_token_id,
            down_token_id=self._down_token_id,
        )

        self._state = OCOState.DONE

        self._log_action("finalize", {
            "winner": winner.value,
            "winning_order_id": winning_order_id,
            "market_slug": self._market_slug,
            "anomaly": anomaly,
            "duration_sec": self._result.duration_sec,
        })

        logger.info(
            f"OCO strategy DONE: winner={winner.value} "
            f"market={self._market_slug} "
            f"order={winning_order_id} "
            f"duration={self._result.duration_sec:.2f}s "
            f"anomaly={anomaly}"
        )

    def _log_action(self, action: str, details: dict) -> None:
        """Log an action for debugging/dry-run analysis."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "dry_run": self._config.dry_run,
            **details,
        }
        self._action_log.append(entry)
        logger.debug(f"Action: {action} - {details}")


# ============================================================
# Convenience Functions
# ============================================================


def create_order_update_from_polling(
    order_id: str,
    order_info: "OrderInfo",
    trade: Optional["Trade"] = None,
) -> OrderUpdateEvent:
    """
    Create an OrderUpdateEvent from polling results.

    Helper function to convert PolymarketAPI polling results
    into the event format expected by OCOLimitStrategy.

    Args:
        order_id: The order ID
        order_info: OrderInfo from api.get_order()
        trade: Optional Trade from api.wait_for_trade_mined()

    Returns:
        OrderUpdateEvent for on_order_update()
    """
    return OrderUpdateEvent(
        order_id=order_id,
        order_status=order_info.status,
        trade_id=trade.id if trade else None,
        trade_status=trade.status.value if trade else None,
    )
