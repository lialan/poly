"""Market snapshot for Polymarket orderbook data."""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import aiohttp

from .markets import (
    CryptoPrediction,
    Asset,
    MarketHorizon,
    get_current_slot_timestamp,
    slug_to_timestamp,
    timestamp_to_slug,
    _fetch_prediction_by_slug,
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
    """Minimal snapshot of market orderbook state.

    Contains only non-derivable data:
    - timestamp: when snapshot was taken
    - market_id: slug (encodes resolution time)
    - btc_price: BTC price at snapshot time
    - yes_bids/asks: full YES token orderbook
    - no_bids/asks: full NO token orderbook

    All other fields (best prices, mid, spread, resolution_time)
    can be derived from these.
    """

    timestamp: float
    market_id: str
    btc_price: Decimal
    yes_bids: list[OrderLevel] = field(default_factory=list)
    yes_asks: list[OrderLevel] = field(default_factory=list)
    no_bids: list[OrderLevel] = field(default_factory=list)
    no_asks: list[OrderLevel] = field(default_factory=list)

    # --- Derived properties ---

    @property
    def best_yes_bid(self) -> Optional[Decimal]:
        """Best (highest) YES bid price."""
        return self.yes_bids[-1].price if self.yes_bids else None

    @property
    def best_yes_ask(self) -> Optional[Decimal]:
        """Best (lowest) YES ask price."""
        return self.yes_asks[-1].price if self.yes_asks else None

    @property
    def best_no_bid(self) -> Optional[Decimal]:
        """Best (highest) NO bid price."""
        return self.no_bids[-1].price if self.no_bids else None

    @property
    def best_no_ask(self) -> Optional[Decimal]:
        """Best (lowest) NO ask price."""
        return self.no_asks[-1].price if self.no_asks else None

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
        return sum((level.size for level in self.yes_bids + self.yes_asks), Decimal("0"))

    @property
    def no_depth_total(self) -> Decimal:
        """Total size in NO orderbook."""
        return sum((level.size for level in self.no_bids + self.no_asks), Decimal("0"))

    @property
    def resolution_time(self) -> Optional[datetime]:
        """Derive resolution time from market_id (slug)."""
        ts = slug_to_timestamp(self.market_id)
        if ts:
            # Determine horizon from slug pattern
            if "-15m-" in self.market_id:
                horizon = MarketHorizon.M15
            elif "-4h-" in self.market_id:
                horizon = MarketHorizon.H4
            else:
                horizon = MarketHorizon.H1
            return datetime.fromtimestamp(ts + horizon.value, tz=timezone.utc)
        return None


async def fetch_orderbook(
    session: aiohttp.ClientSession, token_id: str
) -> tuple[list[OrderLevel], list[OrderLevel]]:
    """Fetch orderbook for a token from CLOB API.

    Args:
        session: aiohttp session.
        token_id: CLOB token ID.

    Returns:
        Tuple of (bids, asks) as OrderLevel lists.
        Bids sorted ascending (best = last), asks sorted descending (best = last).
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
    btc_price: Decimal,
    prediction: Optional[CryptoPrediction] = None,
    asset: Asset = Asset.BTC,
    horizon: MarketHorizon = MarketHorizon.M15,
) -> Optional[MarketSnapshot]:
    """Fetch market snapshot for a prediction market.

    Args:
        market_id: Market ID (can be slug, event_id, or timestamp).
        btc_price: Current asset price.
        prediction: Optional pre-fetched CryptoPrediction.
        asset: Asset type (BTC or ETH).
        horizon: Market horizon (M15, H1, H4).

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

        slug = timestamp_to_slug(asset, horizon, timestamp)
        prediction = await _fetch_prediction_by_slug(slug, asset, horizon)
        if prediction is None:
            return None

    # Fetch orderbooks for both tokens in parallel
    async with aiohttp.ClientSession() as session:
        (yes_bids, yes_asks), (no_bids, no_asks) = await asyncio.gather(
            fetch_orderbook(session, prediction.up_token_id),
            fetch_orderbook(session, prediction.down_token_id),
        )

    return MarketSnapshot(
        timestamp=time.time(),
        market_id=prediction.slug,
        btc_price=btc_price,
        yes_bids=yes_bids,
        yes_asks=yes_asks,
        no_bids=no_bids,
        no_asks=no_asks,
    )


async def fetch_current_snapshot(
    price: Decimal,
    asset: Asset = Asset.BTC,
    horizon: MarketHorizon = MarketHorizon.M15,
) -> Optional[MarketSnapshot]:
    """Fetch snapshot for the current market slot.

    Args:
        price: Current asset price.
        asset: Asset type (BTC or ETH).
        horizon: Market horizon (M15, H1, H4).
    """
    timestamp = get_current_slot_timestamp(horizon)
    return await fetch_market_snapshot(str(timestamp), price, asset=asset, horizon=horizon)


def print_snapshot(snapshot: MarketSnapshot) -> None:
    """Print a formatted market snapshot."""
    print("\n" + "=" * 70)
    print("MARKET SNAPSHOT")
    print("=" * 70)

    print(f"\nMarket: {snapshot.market_id}")
    if snapshot.resolution_time:
        print(f"Resolution: {snapshot.resolution_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Snapshot Time: {datetime.fromtimestamp(snapshot.timestamp, tz=timezone.utc).strftime('%H:%M:%S %Z')}")
    print(f"BTC Price: ${float(snapshot.btc_price):,.2f}")

    print("\n--- YES (UP) Token ---")
    if snapshot.best_yes_bid or snapshot.best_yes_ask:
        bid_str = f"{float(snapshot.best_yes_bid):.4f}" if snapshot.best_yes_bid else "N/A"
        ask_str = f"{float(snapshot.best_yes_ask):.4f}" if snapshot.best_yes_ask else "N/A"
        mid_str = f"{float(snapshot.yes_mid):.4f}" if snapshot.yes_mid else "N/A"
        spread_str = f"{float(snapshot.yes_spread):.4f}" if snapshot.yes_spread else "N/A"
        print(f"  Best Bid: {bid_str}  |  Best Ask: {ask_str}")
        print(f"  Mid: {mid_str}  |  Spread: {spread_str}")
        print(f"  Depth: {len(snapshot.yes_bids)} bid levels, {len(snapshot.yes_asks)} ask levels")
    else:
        print("  No orderbook data")

    print("\n--- NO (DOWN) Token ---")
    if snapshot.best_no_bid or snapshot.best_no_ask:
        bid_str = f"{float(snapshot.best_no_bid):.4f}" if snapshot.best_no_bid else "N/A"
        ask_str = f"{float(snapshot.best_no_ask):.4f}" if snapshot.best_no_ask else "N/A"
        mid_str = f"{float(snapshot.no_mid):.4f}" if snapshot.no_mid else "N/A"
        spread_str = f"{float(snapshot.no_spread):.4f}" if snapshot.no_spread else "N/A"
        print(f"  Best Bid: {bid_str}  |  Best Ask: {ask_str}")
        print(f"  Mid: {mid_str}  |  Spread: {spread_str}")
        print(f"  Depth: {len(snapshot.no_bids)} bid levels, {len(snapshot.no_asks)} ask levels")
    else:
        print("  No orderbook data")

    print("\n" + "=" * 70)
