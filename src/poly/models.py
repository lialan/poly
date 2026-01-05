"""Data models for Polymarket trading."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


class Side(str, Enum):
    """Order side."""

    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    """Order status."""

    PENDING = "PENDING"
    LIVE = "LIVE"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class OrderType(str, Enum):
    """Order type."""

    LIMIT = "LIMIT"
    MARKET = "MARKET"


@dataclass
class Market:
    """Represents a Polymarket prediction market."""

    id: str
    question: str
    slug: str
    end_date: Optional[datetime] = None
    description: str = ""
    active: bool = True
    closed: bool = False
    tokens: list = field(default_factory=list)
    outcomes: list = field(default_factory=list)

    @property
    def is_tradeable(self) -> bool:
        """Check if market is currently tradeable."""
        return self.active and not self.closed


@dataclass
class Token:
    """Represents a market outcome token."""

    token_id: str
    outcome: str
    price: Decimal = Decimal("0")
    winner: Optional[bool] = None


@dataclass
class Order:
    """Represents a trading order."""

    id: str
    market_id: str
    token_id: str
    side: Side
    price: Decimal
    size: Decimal
    order_type: OrderType = OrderType.LIMIT
    status: OrderStatus = OrderStatus.PENDING
    filled_size: Decimal = Decimal("0")
    created_at: Optional[datetime] = None

    @property
    def is_active(self) -> bool:
        """Check if order is still active."""
        return self.status in (OrderStatus.PENDING, OrderStatus.LIVE)

    @property
    def remaining_size(self) -> Decimal:
        """Get unfilled order size."""
        return self.size - self.filled_size


@dataclass
class Position:
    """Represents a position in a market."""

    market_id: str
    token_id: str
    outcome: str
    size: Decimal
    avg_price: Decimal
    current_price: Decimal = Decimal("0")

    @property
    def value(self) -> Decimal:
        """Current position value."""
        return self.size * self.current_price

    @property
    def cost_basis(self) -> Decimal:
        """Total cost of position."""
        return self.size * self.avg_price

    @property
    def pnl(self) -> Decimal:
        """Unrealized profit/loss."""
        return self.value - self.cost_basis

    @property
    def pnl_percent(self) -> Decimal:
        """Unrealized P&L as percentage."""
        if self.cost_basis == 0:
            return Decimal("0")
        return (self.pnl / self.cost_basis) * 100


@dataclass
class Trade:
    """Represents an executed trade."""

    id: str
    order_id: str
    market_id: str
    token_id: str
    side: Side
    price: Decimal
    size: Decimal
    timestamp: datetime
