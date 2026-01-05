"""Polymarket Trading Platform."""

__version__ = "0.1.0"

from .client import PolymarketClient
from .config import Config
from .models import Market, Order, Position
from .trading import TradingEngine

__all__ = [
    "PolymarketClient",
    "Config",
    "Market",
    "Order",
    "Position",
    "TradingEngine",
]
