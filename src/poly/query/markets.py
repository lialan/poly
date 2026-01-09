"""Simple market query convenience functions.

These functions wrap the lower-level API calls for market discovery.

Usage:
    from poly.query import get_market, find_markets

    # Get market info
    market = await get_market("btc-updown-15m-1234567890")

    # Search for markets
    markets = await find_markets("bitcoin")
"""

import asyncio
from typing import Optional

from poly.api.gamma import (
    Event,
    SubMarket,
    OutcomeToken,
    fetch_event_by_slug,
    fetch_event_by_id,
    search_events,
    fetch_markets_by_event,
)
from poly.markets import (
    Asset,
    MarketHorizon,
    CryptoPrediction,
    fetch_current_prediction as _fetch_current_prediction,
    get_current_slot_timestamp,
    timestamp_to_slug,
)


async def get_market(slug: str) -> Optional[Event]:
    """Get market/event info by slug.

    Args:
        slug: Market slug (e.g., "btc-updown-15m-1234567890").

    Returns:
        Event object with market details, or None.
    """
    return await fetch_event_by_slug(slug)


async def get_market_by_id(event_id: str) -> Optional[Event]:
    """Get market/event info by event ID.

    Args:
        event_id: Polymarket event ID.

    Returns:
        Event object, or None.
    """
    return await fetch_event_by_id(event_id)


async def find_markets(query: str, limit: int = 10) -> list[Event]:
    """Search for markets by keyword.

    Args:
        query: Search query.
        limit: Maximum results to return.

    Returns:
        List of matching Event objects.
    """
    return await search_events(query, limit)


async def get_submarkets(slug: str) -> list[SubMarket]:
    """Get all submarkets for an event.

    Args:
        slug: Event slug.

    Returns:
        List of SubMarket objects.
    """
    return await fetch_markets_by_event(slug)


async def get_current_market(
    asset: Asset = Asset.BTC,
    horizon: MarketHorizon = MarketHorizon.M15,
) -> Optional[CryptoPrediction]:
    """Get the current crypto prediction market.

    Args:
        asset: Asset type (BTC or ETH).
        horizon: Market horizon (M15, H1, H4, D1).

    Returns:
        CryptoPrediction with token IDs and slug.
    """
    return await _fetch_current_prediction(asset, horizon)


async def get_btc_15m_market() -> Optional[CryptoPrediction]:
    """Get current BTC 15-minute prediction market.

    Returns:
        CryptoPrediction or None if unavailable.
    """
    return await get_current_market(Asset.BTC, MarketHorizon.M15)


async def get_btc_1h_market() -> Optional[CryptoPrediction]:
    """Get current BTC 1-hour prediction market.

    Returns:
        CryptoPrediction or None if unavailable.
    """
    return await get_current_market(Asset.BTC, MarketHorizon.H1)


async def get_btc_4h_market() -> Optional[CryptoPrediction]:
    """Get current BTC 4-hour prediction market.

    Returns:
        CryptoPrediction or None if unavailable.
    """
    return await get_current_market(Asset.BTC, MarketHorizon.H4)


async def get_btc_daily_market() -> Optional[CryptoPrediction]:
    """Get current BTC daily prediction market.

    Returns:
        CryptoPrediction or None if unavailable.
    """
    return await get_current_market(Asset.BTC, MarketHorizon.D1)


async def get_eth_15m_market() -> Optional[CryptoPrediction]:
    """Get current ETH 15-minute prediction market.

    Returns:
        CryptoPrediction or None if unavailable.
    """
    return await get_current_market(Asset.ETH, MarketHorizon.M15)


async def get_eth_1h_market() -> Optional[CryptoPrediction]:
    """Get current ETH 1-hour prediction market.

    Returns:
        CryptoPrediction or None if unavailable.
    """
    return await get_current_market(Asset.ETH, MarketHorizon.H1)


async def get_market_token_ids(
    asset: Asset = Asset.BTC,
    horizon: MarketHorizon = MarketHorizon.M15,
) -> Optional[tuple[str, str]]:
    """Get YES and NO token IDs for current market.

    Args:
        asset: Asset type.
        horizon: Market horizon.

    Returns:
        Tuple of (yes_token_id, no_token_id), or None.
    """
    market = await get_current_market(asset, horizon)
    if market:
        return (market.up_token_id, market.down_token_id)
    return None


async def get_market_slug(
    asset: Asset = Asset.BTC,
    horizon: MarketHorizon = MarketHorizon.M15,
) -> str:
    """Get slug for current market.

    Args:
        asset: Asset type.
        horizon: Market horizon.

    Returns:
        Market slug string.
    """
    timestamp = get_current_slot_timestamp(horizon)
    return timestamp_to_slug(asset, horizon, timestamp)


# Synchronous versions


def get_market_sync(slug: str) -> Optional[Event]:
    """Synchronous version of get_market()."""
    return asyncio.run(get_market(slug))


def find_markets_sync(query: str, limit: int = 10) -> list[Event]:
    """Synchronous version of find_markets()."""
    return asyncio.run(find_markets(query, limit))


def get_btc_15m_market_sync() -> Optional[CryptoPrediction]:
    """Synchronous version of get_btc_15m_market()."""
    return asyncio.run(get_btc_15m_market())


def get_eth_15m_market_sync() -> Optional[CryptoPrediction]:
    """Synchronous version of get_eth_15m_market()."""
    return asyncio.run(get_eth_15m_market())


__all__ = [
    # Async
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
    # Sync
    "get_market_sync",
    "find_markets_sync",
    "get_btc_15m_market_sync",
    "get_eth_15m_market_sync",
]
