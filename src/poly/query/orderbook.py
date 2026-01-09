"""Simple orderbook query convenience functions.

These functions wrap the lower-level API calls for common orderbook queries.

Usage:
    from poly.query import get_orderbook, get_market_snapshot

    # Get orderbook for a token
    bids, asks = await get_orderbook(token_id)

    # Get full market snapshot
    snapshot = await get_btc_15m_snapshot()
"""

import asyncio
from decimal import Decimal
from typing import Optional

import aiohttp

from poly.market_snapshot import (
    MarketSnapshot,
    OrderLevel,
    fetch_orderbook as _fetch_orderbook,
    fetch_market_snapshot as _fetch_market_snapshot,
    fetch_current_snapshot as _fetch_current_snapshot,
)
from poly.markets import Asset, MarketHorizon


async def get_orderbook(token_id: str) -> tuple[list[OrderLevel], list[OrderLevel]]:
    """Get orderbook for a single token.

    Args:
        token_id: CLOB token ID.

    Returns:
        Tuple of (bids, asks) as OrderLevel lists.
    """
    async with aiohttp.ClientSession() as session:
        return await _fetch_orderbook(session, token_id)


async def get_market_snapshot(
    market_id: str,
    spot_price: Decimal,
    asset: Asset = Asset.BTC,
    horizon: MarketHorizon = MarketHorizon.M15,
) -> Optional[MarketSnapshot]:
    """Get full market snapshot (YES + NO orderbooks).

    Args:
        market_id: Market slug or timestamp.
        spot_price: Current asset price.
        asset: Asset type (BTC or ETH).
        horizon: Market horizon.

    Returns:
        MarketSnapshot or None if not found.
    """
    return await _fetch_market_snapshot(
        market_id=market_id,
        spot_price=spot_price,
        asset=asset,
        horizon=horizon,
    )


async def get_current_snapshot(
    spot_price: Decimal,
    asset: Asset = Asset.BTC,
    horizon: MarketHorizon = MarketHorizon.M15,
) -> Optional[MarketSnapshot]:
    """Get snapshot for the current market (based on current time).

    Args:
        spot_price: Current asset price.
        asset: Asset type (BTC or ETH).
        horizon: Market horizon.

    Returns:
        MarketSnapshot for current market or None.
    """
    return await _fetch_current_snapshot(spot_price, asset, horizon)


async def get_btc_15m_snapshot() -> Optional[MarketSnapshot]:
    """Get snapshot for current BTC 15m market.

    Automatically fetches current BTC price.

    Returns:
        MarketSnapshot or None if unavailable.
    """
    from poly.api.binance import get_btc_price

    price = await get_btc_price()
    if price is None:
        return None

    return await get_current_snapshot(price, Asset.BTC, MarketHorizon.M15)


async def get_eth_15m_snapshot() -> Optional[MarketSnapshot]:
    """Get snapshot for current ETH 15m market.

    Automatically fetches current ETH price.

    Returns:
        MarketSnapshot or None if unavailable.
    """
    from poly.api.binance import get_eth_price

    price = await get_eth_price()
    if price is None:
        return None

    return await get_current_snapshot(price, Asset.ETH, MarketHorizon.M15)


async def get_market_depth(token_id: str) -> dict:
    """Get total orderbook depth for a token.

    Args:
        token_id: CLOB token ID.

    Returns:
        Dict with bid_depth, ask_depth, total_depth.
    """
    bids, asks = await get_orderbook(token_id)

    bid_depth = sum(level.size for level in bids)
    ask_depth = sum(level.size for level in asks)

    return {
        "bid_depth": bid_depth,
        "ask_depth": ask_depth,
        "total_depth": bid_depth + ask_depth,
        "bid_levels": len(bids),
        "ask_levels": len(asks),
    }


async def get_yes_probability(
    market_id: str,
    asset: Asset = Asset.BTC,
    horizon: MarketHorizon = MarketHorizon.M15,
) -> Optional[float]:
    """Get current YES probability (mid price) for a market.

    Args:
        market_id: Market slug or timestamp.
        asset: Asset type.
        horizon: Market horizon.

    Returns:
        YES probability as float (0-1), or None.
    """
    from poly.api.binance import get_btc_price, get_eth_price

    if asset == Asset.BTC:
        price = await get_btc_price()
    else:
        price = await get_eth_price()

    if price is None:
        return None

    snapshot = await get_market_snapshot(market_id, price, asset, horizon)
    if snapshot and snapshot.yes_mid:
        return float(snapshot.yes_mid)
    return None


# Synchronous versions


def get_orderbook_sync(token_id: str) -> tuple[list[OrderLevel], list[OrderLevel]]:
    """Synchronous version of get_orderbook()."""
    return asyncio.run(get_orderbook(token_id))


def get_btc_15m_snapshot_sync() -> Optional[MarketSnapshot]:
    """Synchronous version of get_btc_15m_snapshot()."""
    return asyncio.run(get_btc_15m_snapshot())


def get_eth_15m_snapshot_sync() -> Optional[MarketSnapshot]:
    """Synchronous version of get_eth_15m_snapshot()."""
    return asyncio.run(get_eth_15m_snapshot())


__all__ = [
    # Async
    "get_orderbook",
    "get_market_snapshot",
    "get_current_snapshot",
    "get_btc_15m_snapshot",
    "get_eth_15m_snapshot",
    "get_market_depth",
    "get_yes_probability",
    # Sync
    "get_orderbook_sync",
    "get_btc_15m_snapshot_sync",
    "get_eth_15m_snapshot_sync",
]
