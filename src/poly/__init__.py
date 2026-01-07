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
from .markets import (
    Asset,
    MarketHorizon,
    CryptoPrediction,
    fetch_current_prediction,
    get_current_slot_timestamp,
    timestamp_to_slug,
    slug_to_timestamp,
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
# Telegram notifier - optional (requires python-telegram-bot)
try:
    from .telegram_notifier import (
        TelegramNotifier,
        TelegramConfig,
        escape_markdown,
    )
except ImportError:
    TelegramNotifier = None
    TelegramConfig = None
    escape_markdown = None
from .market_snapshot import (
    MarketSnapshot,
    OrderLevel,
    fetch_market_snapshot,
    fetch_current_snapshot,
    fetch_orderbook,
    print_snapshot,
)
from .sqlite_writer import SQLiteWriter
from .db_writer import get_db_writer, DBWriter
from .binance_ws import (
    BinanceKlineStream,
    RealtimeKline,
    collect_klines,
    parse_kline_message,
)

# Lazy import for BigtableWriter (requires google-cloud-bigtable)
def __getattr__(name):
    if name == "BigtableWriter":
        from .bigtable_writer import BigtableWriter
        return BigtableWriter
    if name == "BigtableConfig":
        from .bigtable_writer import BigtableConfig
        return BigtableConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

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
    "Asset",
    "MarketHorizon",
    "CryptoPrediction",
    "fetch_current_prediction",
    "get_current_slot_timestamp",
    "timestamp_to_slug",
    "slug_to_timestamp",
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
    "MarketSnapshot",
    "OrderLevel",
    "fetch_market_snapshot",
    "fetch_current_snapshot",
    "fetch_orderbook",
    "print_snapshot",
    "SQLiteWriter",
    "BigtableWriter",
    "BigtableConfig",
    "get_db_writer",
    "DBWriter",
    "BinanceKlineStream",
    "RealtimeKline",
    "collect_klines",
    "parse_kline_message",
]
