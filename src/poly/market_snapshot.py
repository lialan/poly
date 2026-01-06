"""Market snapshot for Polymarket orderbook data."""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import aiohttp

from .btc_15m import (
    BTC15mPrediction,
    fetch_btc_15m_prediction,
    get_current_slot_timestamp,
    slug_to_timestamp,
    INTERVAL_SECONDS,
)

CLOB_API_BASE = "https://clob.polymarket.com"


@dataclass
class OrderLevel:
    """Single price level in orderbook."""

    price: Decimal
    size: Decimal

    def __repr__(self) -> str:
        return f"({float(self.price):.4f}, {float(self.size):.2f})"


@dataclass
class MarketSnapshot:
    """Snapshot of market orderbook state."""

    timestamp: float
    market_id: str
    resolution_time: datetime

    # Best bid/ask for YES token
    best_yes_bid: Optional[Decimal] = None
    best_yes_ask: Optional[Decimal] = None

    # Best bid/ask for NO token
    best_no_bid: Optional[Decimal] = None
    best_no_ask: Optional[Decimal] = None

    # Orderbook depth - separate bids and asks
    depth_yes_bids: list[OrderLevel] = field(default_factory=list)
    depth_yes_asks: list[OrderLevel] = field(default_factory=list)
    depth_no_bids: list[OrderLevel] = field(default_factory=list)
    depth_no_asks: list[OrderLevel] = field(default_factory=list)

    # Volume (from Gamma API - total market volume, not 1m/5m)
    volume_total: Decimal = Decimal("0")

    # Token IDs for reference
    yes_token_id: str = ""
    no_token_id: str = ""

    @property
    def depth_yes(self) -> list[tuple[float, float]]:
        """Combined YES depth as (price, size) tuples."""
        return [(float(l.price), float(l.size)) for l in self.depth_yes_bids + self.depth_yes_asks]

    @property
    def depth_no(self) -> list[tuple[float, float]]:
        """Combined NO depth as (price, size) tuples."""
        return [(float(l.price), float(l.size)) for l in self.depth_no_bids + self.depth_no_asks]

    @property
    def yes_mid(self) -> Optional[Decimal]:
        """Mid price for YES token."""
        if self.best_yes_bid and self.best_yes_ask:
            return (self.best_yes_bid + self.best_yes_ask) / 2
        return self.best_yes_bid or self.best_yes_ask

    @property
    def no_mid(self) -> Optional[Decimal]:
        """Mid price for NO token."""
        if self.best_no_bid and self.best_no_ask:
            return (self.best_no_bid + self.best_no_ask) / 2
        return self.best_no_bid or self.best_no_ask

    @property
    def yes_spread(self) -> Optional[Decimal]:
        """Spread for YES token."""
        if self.best_yes_bid and self.best_yes_ask:
            return self.best_yes_ask - self.best_yes_bid
        return None

    @property
    def no_spread(self) -> Optional[Decimal]:
        """Spread for NO token."""
        if self.best_no_bid and self.best_no_ask:
            return self.best_no_ask - self.best_no_bid
        return None

    @property
    def yes_depth_total(self) -> Decimal:
        """Total size in YES orderbook."""
        return sum((level.size for level in self.depth_yes_bids + self.depth_yes_asks), Decimal("0"))

    @property
    def no_depth_total(self) -> Decimal:
        """Total size in NO orderbook."""
        return sum((level.size for level in self.depth_no_bids + self.depth_no_asks), Decimal("0"))


async def fetch_orderbook(
    session: aiohttp.ClientSession, token_id: str
) -> tuple[list[OrderLevel], list[OrderLevel]]:
    """Fetch orderbook for a token from CLOB API.

    Args:
        session: aiohttp session.
        token_id: CLOB token ID.

    Returns:
        Tuple of (bids, asks) as OrderLevel lists.
    """
    url = f"{CLOB_API_BASE}/book"
    params = {"token_id": token_id}

    try:
        async with session.get(url, params=params) as response:
            if response.status != 200:
                return [], []

            data = await response.json()

            bids = [
                OrderLevel(
                    price=Decimal(str(level["price"])),
                    size=Decimal(str(level["size"])),
                )
                for level in data.get("bids", [])
            ]

            asks = [
                OrderLevel(
                    price=Decimal(str(level["price"])),
                    size=Decimal(str(level["size"])),
                )
                for level in data.get("asks", [])
            ]

            return bids, asks
    except Exception:
        return [], []


async def fetch_market_snapshot(
    market_id: str,
    prediction: Optional[BTC15mPrediction] = None,
) -> Optional[MarketSnapshot]:
    """Fetch market snapshot for a BTC 15m prediction market.

    Args:
        market_id: Market ID (can be slug, event_id, or timestamp).
        prediction: Optional pre-fetched BTC15mPrediction.

    Returns:
        MarketSnapshot or None if not found.
    """
    # If prediction not provided, fetch it
    if prediction is None:
        # Try to parse market_id as timestamp
        try:
            timestamp = int(market_id)
        except ValueError:
            # Could be a slug like btc-updown-15m-1234567890
            timestamp = slug_to_timestamp(market_id)
            if timestamp is None:
                return None

        prediction = await fetch_btc_15m_prediction(timestamp)
        if prediction is None:
            return None

    # Fetch orderbooks for both tokens in parallel
    async with aiohttp.ClientSession() as session:
        yes_task = fetch_orderbook(session, prediction.up_token_id)
        no_task = fetch_orderbook(session, prediction.down_token_id)

        (yes_bids, yes_asks), (no_bids, no_asks) = await asyncio.gather(
            yes_task, no_task
        )

    # Calculate resolution time from slug
    ts = slug_to_timestamp(prediction.slug)
    resolution_time = (
        datetime.fromtimestamp(ts + INTERVAL_SECONDS, tz=timezone.utc)
        if ts
        else prediction.end_time
    )

    return MarketSnapshot(
        timestamp=time.time(),
        market_id=prediction.slug,
        resolution_time=resolution_time,
        # YES (UP) token
        best_yes_bid=yes_bids[0].price if yes_bids else None,
        best_yes_ask=yes_asks[0].price if yes_asks else None,
        depth_yes_bids=yes_bids,  # All bid levels
        depth_yes_asks=yes_asks,  # All ask levels
        # NO (DOWN) token
        best_no_bid=no_bids[0].price if no_bids else None,
        best_no_ask=no_asks[0].price if no_asks else None,
        depth_no_bids=no_bids,
        depth_no_asks=no_asks,
        # Volume from Gamma API
        volume_total=prediction.volume,
        # Token IDs
        yes_token_id=prediction.up_token_id,
        no_token_id=prediction.down_token_id,
    )


async def fetch_current_snapshot() -> Optional[MarketSnapshot]:
    """Fetch snapshot for the current 15-minute slot."""
    timestamp = get_current_slot_timestamp()
    return await fetch_market_snapshot(str(timestamp))


def print_snapshot(snapshot: MarketSnapshot) -> None:
    """Print a formatted market snapshot."""
    print("\n" + "=" * 70)
    print("MARKET SNAPSHOT")
    print("=" * 70)

    print(f"\nMarket: {snapshot.market_id}")
    print(f"Resolution: {snapshot.resolution_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Snapshot Time: {datetime.fromtimestamp(snapshot.timestamp, tz=timezone.utc).strftime('%H:%M:%S %Z')}")

    print("\n--- YES (UP) Token ---")
    if snapshot.best_yes_bid or snapshot.best_yes_ask:
        bid_str = f"{float(snapshot.best_yes_bid):.4f}" if snapshot.best_yes_bid else "N/A"
        ask_str = f"{float(snapshot.best_yes_ask):.4f}" if snapshot.best_yes_ask else "N/A"
        mid_str = f"{float(snapshot.yes_mid):.4f}" if snapshot.yes_mid else "N/A"
        spread_str = f"{float(snapshot.yes_spread):.4f}" if snapshot.yes_spread else "N/A"
        print(f"  Best Bid: {bid_str}  |  Best Ask: {ask_str}")
        print(f"  Mid: {mid_str}  |  Spread: {spread_str}")
    else:
        print("  No orderbook data")

    # Print YES depth
    if snapshot.depth_yes_bids or snapshot.depth_yes_asks:
        print(f"  Depth: {len(snapshot.depth_yes_bids)} bid levels, {len(snapshot.depth_yes_asks)} ask levels")
        print(f"  Total Depth Size: {float(snapshot.yes_depth_total):.2f}")

    print("\n--- NO (DOWN) Token ---")
    if snapshot.best_no_bid or snapshot.best_no_ask:
        bid_str = f"{float(snapshot.best_no_bid):.4f}" if snapshot.best_no_bid else "N/A"
        ask_str = f"{float(snapshot.best_no_ask):.4f}" if snapshot.best_no_ask else "N/A"
        mid_str = f"{float(snapshot.no_mid):.4f}" if snapshot.no_mid else "N/A"
        spread_str = f"{float(snapshot.no_spread):.4f}" if snapshot.no_spread else "N/A"
        print(f"  Best Bid: {bid_str}  |  Best Ask: {ask_str}")
        print(f"  Mid: {mid_str}  |  Spread: {spread_str}")
    else:
        print("  No orderbook data")

    # Print NO depth
    if snapshot.depth_no_bids or snapshot.depth_no_asks:
        print(f"  Depth: {len(snapshot.depth_no_bids)} bid levels, {len(snapshot.depth_no_asks)} ask levels")
        print(f"  Total Depth Size: {float(snapshot.no_depth_total):.2f}")

    print(f"\nTotal Volume: ${float(snapshot.volume_total):,.2f}")
    print("\n" + "=" * 70)
