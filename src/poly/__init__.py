"""Polymarket Trading Platform.

Package structure:
    poly.api      - External API clients (Polymarket, Binance, Gamma, Chainlink)
    poly.query    - Simple query convenience functions
    poly.storage  - Database backends (Bigtable, SQLite)

Quick usage:
    from poly import get_btc_price, get_btc_15m_market
    from poly.api import PolymarketAPI
    from poly.query import get_btc_15m_snapshot
    from poly.storage import BigtableWriter
"""

__version__ = "0.1.0"

# Core data models (top-level)
from .client import PolymarketClient
from .config import Config
from .models import Market, Order, Position
from .trading import TradingEngine

# Markets module (top-level)
from .markets import (
    Asset,
    MarketHorizon,
    CryptoPrediction,
    fetch_current_prediction,
    get_current_slot_timestamp,
    get_slug,
    get_slot_timestamp,
    get_market_slugs,
    timestamp_to_slug,
    slug_to_timestamp,
)

# Market snapshot (top-level)
from .market_snapshot import (
    MarketSnapshot,
    OrderLevel,
    fetch_market_snapshot,
    fetch_current_snapshot,
    fetch_orderbook,
    print_snapshot,
)

# Market feed (top-level)
from .market_feed import (
    MarketFeed,
    PriceUpdate,
    MarketState,
    FeedStats,
    Side,
)

# Trading bot (top-level)
from .trading_bot import (
    TradingBot,
    TradingBotConfig,
    MarketContext,
    DecisionResult,
    DecisionFunction,
    CycleTiming,
    no_op_decision,
)

# Project config (top-level)
from .project_config import (
    load_config,
    get_bigtable_config,
    get_polymarket_config,
    get_collector_config,
    get_telegram_config,
    get_config_value,
    ProjectConfig,
)

# Bigtable status (top-level)
from .bigtable_status import (
    check_collection_status,
    CollectionStatus,
    TableStatus,
    SNAPSHOT_TABLES,
)

# Telegram notifier (optional)
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

# ============================================================================
# Re-exports from strategies/ submodule
# ============================================================================

from .strategies.oco_limit import (
    OCOLimitStrategy,
    OCOConfig,
    OCOState,
    OCOResult,
    OrderUpdateEvent,
    WinnerSide,
    create_order_update_from_polling,
)

# ============================================================================
# Re-exports from api/ submodule (for backward compatibility)
# ============================================================================

# Polymarket REST API
from .api.polymarket import (
    PolymarketAPI,
    PolymarketAPISync,
    MarketPosition,
    Trade,
    MarketInfo,
    OrderStatus,
    TradeStatus,
    MarketStatus,
    OrderResult,
    OrderSide,
    OrderTimeInForce,
    TradingError,
    TradingNotConfiguredError,
    ExecutionConfig,
    OrderInfo,
    ExecutionResult,
    OrderExpiredError,
    OrderCanceledError,
    TradeMiningFailedError,
    ExecutionTimeoutError,
)

# Polymarket WebSocket
from .api.polymarket_ws import (
    PolymarketWS,
    MultiMarketWS,
    MarketUpdate,
    UpdateType,
    ConnectionStats,
    stream_market,
    get_orderbook_updates,
)

# Polymarket config
from .api.polymarket_config import (
    PolymarketConfig,
    SecretManager,
    SignerType,
)

# Signing
from .api.signer import (
    Signer,
    LocalSigner,
    KMSSigner,
    EOASigner,
    OrderParams,
    SignedOrder,
    SignerType as SignerTypeEnum,
    create_signer,
)

# Gamma API
from .api.gamma import (
    Event,
    SubMarket,
    OutcomeToken,
    fetch_event_by_slug,
    fetch_event_from_url,
    search_events,
)

# Binance REST API
from .api.binance import (
    get_btc_price,
    get_eth_price,
    get_prices,
    get_btc_stats,
    get_eth_stats,
    TickerPrice,
    TickerStats,
)

# Binance WebSocket
from .api.binance_ws import (
    BinanceKlineStream,
    RealtimeKline,
    collect_klines,
    parse_kline_message,
)

# ============================================================================
# Re-exports from storage/ submodule (for backward compatibility)
# ============================================================================

from .storage.sqlite import SQLiteWriter
from .storage.db_writer import get_db_writer, DBWriter

# Lazy import for BigtableWriter (requires google-cloud-bigtable)
def __getattr__(name):
    if name == "BigtableWriter":
        from .storage.bigtable import BigtableWriter
        return BigtableWriter
    if name == "BigtableConfig":
        from .storage.bigtable import BigtableConfig
        return BigtableConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Core
    "PolymarketClient",
    "Config",
    "Market",
    "Order",
    "Position",
    "TradingEngine",
    # Markets
    "Asset",
    "MarketHorizon",
    "CryptoPrediction",
    "fetch_current_prediction",
    "get_current_slot_timestamp",
    "get_slug",
    "get_slot_timestamp",
    "get_market_slugs",
    "timestamp_to_slug",
    "slug_to_timestamp",
    # Snapshot
    "MarketSnapshot",
    "OrderLevel",
    "fetch_market_snapshot",
    "fetch_current_snapshot",
    "fetch_orderbook",
    "print_snapshot",
    # Market feed
    "MarketFeed",
    "PriceUpdate",
    "MarketState",
    "FeedStats",
    "Side",
    # Trading bot
    "TradingBot",
    "TradingBotConfig",
    "MarketContext",
    "DecisionResult",
    "DecisionFunction",
    "CycleTiming",
    "no_op_decision",
    # Project config
    "load_config",
    "get_bigtable_config",
    "get_polymarket_config",
    "get_collector_config",
    "get_telegram_config",
    "get_config_value",
    "ProjectConfig",
    # Bigtable status
    "check_collection_status",
    "CollectionStatus",
    "TableStatus",
    "SNAPSHOT_TABLES",
    # Telegram (optional)
    "TelegramNotifier",
    "TelegramConfig",
    "escape_markdown",
    # API: Polymarket REST
    "PolymarketAPI",
    "PolymarketAPISync",
    "MarketPosition",
    "Trade",
    "MarketInfo",
    "OrderStatus",
    "TradeStatus",
    "MarketStatus",
    "OrderResult",
    "OrderSide",
    "OrderTimeInForce",
    "TradingError",
    "TradingNotConfiguredError",
    "ExecutionConfig",
    "OrderInfo",
    "ExecutionResult",
    "OrderExpiredError",
    "OrderCanceledError",
    "TradeMiningFailedError",
    "ExecutionTimeoutError",
    # API: Polymarket WebSocket
    "PolymarketWS",
    "MultiMarketWS",
    "MarketUpdate",
    "UpdateType",
    "ConnectionStats",
    "stream_market",
    "get_orderbook_updates",
    # API: Config
    "PolymarketConfig",
    "SecretManager",
    "SignerType",
    # API: Signing
    "Signer",
    "LocalSigner",
    "KMSSigner",
    "EOASigner",
    "OrderParams",
    "SignedOrder",
    "create_signer",
    # API: Gamma
    "Event",
    "SubMarket",
    "OutcomeToken",
    "fetch_event_by_slug",
    "fetch_event_from_url",
    "search_events",
    # API: Binance
    "get_btc_price",
    "get_eth_price",
    "get_prices",
    "get_btc_stats",
    "get_eth_stats",
    "TickerPrice",
    "TickerStats",
    "BinanceKlineStream",
    "RealtimeKline",
    "collect_klines",
    "parse_kline_message",
    # Storage
    "SQLiteWriter",
    "BigtableWriter",
    "BigtableConfig",
    "get_db_writer",
    "DBWriter",
    # Strategies
    "OCOLimitStrategy",
    "OCOConfig",
    "OCOState",
    "OCOResult",
    "OrderUpdateEvent",
    "WinnerSide",
    "create_order_update_from_polling",
]
