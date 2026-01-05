"""Polymarket Trading Platform."""

__version__ = "0.1.0"

from .client import PolymarketClient
from .config import Config
from .models import Market, Order, Position
from .trading import TradingEngine
from .gamma import (
    Event,
    SubMarket,
    OutcomeToken,
    fetch_event_by_slug,
    fetch_event_from_url,
    search_events,
)

__all__ = [
    "PolymarketClient",
    "Config",
    "Market",
    "Order",
    "Position",
    "TradingEngine",
    "Event",
    "SubMarket",
    "OutcomeToken",
    "fetch_event_by_slug",
    "fetch_event_from_url",
    "search_events",
]
