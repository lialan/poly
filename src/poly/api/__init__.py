"""Polymarket API clients and external service integrations."""

# Polymarket REST API
from .polymarket import (
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
from .polymarket_ws import (
    PolymarketWS,
    MultiMarketWS,
    MarketUpdate,
    UpdateType,
    OrderLevel,
    ConnectionStats,
    stream_market,
    get_orderbook_updates,
)

# Polymarket config
from .polymarket_config import (
    PolymarketConfig,
    SecretManager,
    SignerType,
)

# Signing
from .signer import (
    Signer,
    LocalSigner,
    KMSSigner,
    EOASigner,
    OrderParams,
    SignedOrder,
    OrderSide as SignerOrderSide,
    SignerType as SignerTypeEnum,
    create_signer,
)

# Gamma API (Polymarket public data)
from .gamma import (
    Event,
    SubMarket,
    OutcomeToken,
    fetch_event_by_slug,
    fetch_event_by_id,
    fetch_event_from_url,
    fetch_markets_by_event,
    search_events,
    extract_slug_from_url,
)

# Binance REST API
from .binance import (
    get_btc_price,
    get_eth_price,
    get_price,
    get_prices,
    get_btc_stats,
    get_eth_stats,
    get_24h_stats,
    get_klines,
    get_latest_kline,
    get_btc_15m_kline,
    get_eth_15m_kline,
    get_kline_at_time,
    TickerPrice,
    TickerStats,
    Kline,
    print_price,
    print_stats,
    print_kline,
    BTCUSDT,
    ETHUSDT,
)

# Binance WebSocket
from .binance_ws import (
    BinanceKlineStream,
    RealtimeKline,
    collect_klines,
    parse_kline_message,
    print_kline as print_realtime_kline,
)

# Chainlink on-chain prices (optional - requires web3)
try:
    from .chainlink import (
        get_btc_price as get_btc_price_chainlink,
        get_eth_price as get_eth_price_chainlink,
        get_prices as get_prices_chainlink,
    )
except ImportError:
    get_btc_price_chainlink = None
    get_eth_price_chainlink = None
    get_prices_chainlink = None


__all__ = [
    # Polymarket REST
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
    # Polymarket WebSocket
    "PolymarketWS",
    "MultiMarketWS",
    "MarketUpdate",
    "UpdateType",
    "OrderLevel",
    "ConnectionStats",
    "stream_market",
    "get_orderbook_updates",
    # Config
    "PolymarketConfig",
    "SecretManager",
    "SignerType",
    # Signing
    "Signer",
    "LocalSigner",
    "KMSSigner",
    "EOASigner",
    "OrderParams",
    "SignedOrder",
    "SignerOrderSide",
    "SignerTypeEnum",
    "create_signer",
    # Gamma
    "Event",
    "SubMarket",
    "OutcomeToken",
    "fetch_event_by_slug",
    "fetch_event_by_id",
    "fetch_event_from_url",
    "fetch_markets_by_event",
    "search_events",
    "extract_slug_from_url",
    # Binance REST
    "get_btc_price",
    "get_eth_price",
    "get_price",
    "get_prices",
    "get_btc_stats",
    "get_eth_stats",
    "get_24h_stats",
    "get_klines",
    "get_latest_kline",
    "get_btc_15m_kline",
    "get_eth_15m_kline",
    "get_kline_at_time",
    "TickerPrice",
    "TickerStats",
    "Kline",
    "print_price",
    "print_stats",
    "print_kline",
    "BTCUSDT",
    "ETHUSDT",
    # Binance WebSocket
    "BinanceKlineStream",
    "RealtimeKline",
    "collect_klines",
    "parse_kline_message",
    "print_realtime_kline",
    # Chainlink
    "get_btc_price_chainlink",
    "get_eth_price_chainlink",
    "get_prices_chainlink",
]
