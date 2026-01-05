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
from .btc_15m import (
    BTC15mPrediction,
    fetch_current_and_upcoming,
    fetch_btc_15m_prediction,
    print_predictions,
)
from .binance_price import (
    get_btc_price,
    get_eth_price,
    get_prices,
    get_btc_stats,
    get_eth_stats,
    TickerPrice,
    TickerStats,
)
from .telegram_notifier import (
    TelegramNotifier,
    TelegramConfig,
    escape_markdown,
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
    "BTC15mPrediction",
    "fetch_current_and_upcoming",
    "fetch_btc_15m_prediction",
    "print_predictions",
    "get_btc_price",
    "get_eth_price",
    "get_prices",
    "get_btc_stats",
    "get_eth_stats",
    "TickerPrice",
    "TickerStats",
    "TelegramNotifier",
    "TelegramConfig",
    "escape_markdown",
]
