"""Simple query convenience functions.

This module provides easy-to-use query functions that wrap the lower-level API clients.

Prices:
    from poly.query import get_btc_price, get_eth_price
    price = await get_btc_price()  # Returns Decimal

Orderbooks:
    from poly.query import get_btc_15m_snapshot
    snapshot = await get_btc_15m_snapshot()  # Returns MarketSnapshot

Markets:
    from poly.query import get_btc_15m_market, find_markets
    market = await get_btc_15m_market()  # Returns CryptoPrediction
    results = await find_markets("bitcoin")  # Returns list[Event]

Synchronous versions are available with _sync suffix:
    from poly.query import get_btc_price_sync
    price = get_btc_price_sync()
"""

# Price queries
from .prices import (
    get_btc_price,
    get_eth_price,
    get_price,
    get_prices,
    get_btc_stats,
    get_eth_stats,
    get_btc_24h_change,
    get_eth_24h_change,
    get_btc_price_sync,
    get_eth_price_sync,
    get_price_sync,
    get_btc_stats_sync,
    get_eth_stats_sync,
)

# Orderbook queries
from .orderbook import (
    get_orderbook,
    get_market_snapshot,
    get_current_snapshot,
    get_btc_15m_snapshot,
    get_eth_15m_snapshot,
    get_market_depth,
    get_yes_probability,
    get_orderbook_sync,
    get_btc_15m_snapshot_sync,
    get_eth_15m_snapshot_sync,
)

# Market queries
from .markets import (
    get_market,
    get_market_by_id,
    find_markets,
    get_submarkets,
    get_current_market,
    get_btc_15m_market,
    get_btc_1h_market,
    get_btc_4h_market,
    get_btc_daily_market,
    get_eth_15m_market,
    get_eth_1h_market,
    get_market_token_ids,
    get_market_slug,
    get_market_sync,
    find_markets_sync,
    get_btc_15m_market_sync,
    get_eth_15m_market_sync,
)


__all__ = [
    # Prices
    "get_btc_price",
    "get_eth_price",
    "get_price",
    "get_prices",
    "get_btc_stats",
    "get_eth_stats",
    "get_btc_24h_change",
    "get_eth_24h_change",
    "get_btc_price_sync",
    "get_eth_price_sync",
    "get_price_sync",
    "get_btc_stats_sync",
    "get_eth_stats_sync",
    # Orderbooks
    "get_orderbook",
    "get_market_snapshot",
    "get_current_snapshot",
    "get_btc_15m_snapshot",
    "get_eth_15m_snapshot",
    "get_market_depth",
    "get_yes_probability",
    "get_orderbook_sync",
    "get_btc_15m_snapshot_sync",
    "get_eth_15m_snapshot_sync",
    # Markets
    "get_market",
    "get_market_by_id",
    "find_markets",
    "get_submarkets",
    "get_current_market",
    "get_btc_15m_market",
    "get_btc_1h_market",
    "get_btc_4h_market",
    "get_btc_daily_market",
    "get_eth_15m_market",
    "get_eth_1h_market",
    "get_market_token_ids",
    "get_market_slug",
    "get_market_sync",
    "find_markets_sync",
    "get_btc_15m_market_sync",
    "get_eth_15m_market_sync",
]
