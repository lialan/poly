"""Crypto prediction market utilities for BTC and ETH markets."""

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from enum import Enum
from typing import Optional

import aiohttp

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
POLYMARKET_BASE = "https://polymarket.com"

# Months for 1h slug generation
MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december"
]


class Asset(Enum):
    """Supported crypto assets."""
    BTC = "btc"
    ETH = "eth"


class MarketHorizon(Enum):
    """Market time horizon."""
    M15 = 900       # 15 minutes
    H1 = 3600       # 1 hour
    H4 = 14400      # 4 hours
    D1 = 86400      # 1 day


@dataclass
class CryptoPrediction:
    """Represents a crypto Up/Down prediction market."""

    slug: str
    event_id: str
    title: str
    asset: Asset
    horizon: MarketHorizon
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    up_price: Decimal
    down_price: Decimal
    up_token_id: str
    down_token_id: str
    liquidity: Decimal
    volume: Decimal
    active: bool
    closed: bool

    @property
    def url(self) -> str:
        """Get Polymarket URL for this prediction."""
        return f"{POLYMARKET_BASE}/event/{self.slug}"

    @property
    def up_probability(self) -> float:
        """Get probability of UP outcome as percentage."""
        return float(self.up_price) * 100

    @property
    def down_probability(self) -> float:
        """Get probability of DOWN outcome as percentage."""
        return float(self.down_price) * 100

    @property
    def resolution_time(self) -> Optional[datetime]:
        """Get the resolution time."""
        return self.end_time

    @property
    def time_remaining(self) -> float:
        """Get seconds remaining until this market resolves."""
        if self.horizon in (MarketHorizon.M15, MarketHorizon.H4):
            ts = slug_to_timestamp(self.slug)
            if ts:
                slot_end = datetime.fromtimestamp(ts + self.horizon.value, tz=timezone.utc)
                now = datetime.now(timezone.utc)
                return (slot_end - now).total_seconds()
        elif self.end_time:
            now = datetime.now(timezone.utc)
            return (self.end_time - now).total_seconds()
        return 0

    @property
    def is_live(self) -> bool:
        """Check if market is currently in its trading window."""
        if self.horizon in (MarketHorizon.M15, MarketHorizon.H4):
            now = datetime.now(timezone.utc)
            ts = slug_to_timestamp(self.slug)
            if ts:
                slot_start = datetime.fromtimestamp(ts, tz=timezone.utc)
                slot_end = datetime.fromtimestamp(ts + self.horizon.value, tz=timezone.utc)
                return slot_start <= now < slot_end and self.active and not self.closed
        return self.active and not self.closed


# ============================================================================
# Slug Generation Functions
# ============================================================================

def get_current_slot_timestamp(horizon: MarketHorizon) -> int:
    """Get the Unix timestamp for the current slot.

    For 4h markets, aligns to ET timezone boundaries (0, 4, 8, 12, 16, 20 hours ET).
    """
    now = int(time.time())

    if horizon == MarketHorizon.H4:
        # 4h markets align to ET timezone (UTC-5)
        # Convert to ET, find 4h boundary, convert back
        et_offset = 5 * 3600  # 5 hours in seconds
        now_et = now - et_offset
        slot_start_et = (now_et // horizon.value) * horizon.value
        return slot_start_et + et_offset
    else:
        return (now // horizon.value) * horizon.value


def timestamp_to_slug(asset: Asset, horizon: MarketHorizon, timestamp: int) -> str:
    """Convert Unix timestamp to market slug (for 15m and 4h markets)."""
    asset_str = asset.value  # "btc" or "eth"
    if horizon == MarketHorizon.M15:
        return f"{asset_str}-updown-15m-{timestamp}"
    elif horizon == MarketHorizon.H4:
        return f"{asset_str}-updown-4h-{timestamp}"
    else:
        raise ValueError(f"timestamp_to_slug not supported for {horizon}")


def slug_to_timestamp(slug: str) -> Optional[int]:
    """Extract Unix timestamp from market slug."""
    try:
        parts = slug.split("-")
        return int(parts[-1])
    except (IndexError, ValueError):
        return None


def get_current_hour_et() -> datetime:
    """Get the current hour in ET timezone (UTC-5)."""
    utc_now = datetime.now(timezone.utc)
    et_offset = timedelta(hours=-5)
    et_now = utc_now + et_offset
    return et_now.replace(minute=0, second=0, microsecond=0)


def datetime_to_slug_1h(asset: Asset, dt: datetime) -> str:
    """Convert a datetime (in ET) to 1h market slug."""
    month = MONTHS[dt.month - 1]
    day = dt.day
    hour = dt.hour

    if hour == 0:
        hour_str = "12am"
    elif hour < 12:
        hour_str = f"{hour}am"
    elif hour == 12:
        hour_str = "12pm"
    else:
        hour_str = f"{hour - 12}pm"

    # BTC uses "bitcoin", ETH uses "ethereum"
    asset_name = "bitcoin" if asset == Asset.BTC else "ethereum"
    return f"{asset_name}-up-or-down-{month}-{day}-{hour_str}-et"


def datetime_to_slug_d1(asset: Asset, dt: datetime) -> str:
    """Convert a datetime (in ET) to daily market slug.

    Daily markets resolve at noon ET comparing to previous day noon.
    Slug format: bitcoin-up-or-down-on-january-7
    """
    month = MONTHS[dt.month - 1]
    day = dt.day

    # BTC uses "bitcoin", ETH uses "ethereum"
    asset_name = "bitcoin" if asset == Asset.BTC else "ethereum"
    return f"{asset_name}-up-or-down-on-{month}-{day}"


def get_current_day_et() -> datetime:
    """Get the current day in ET timezone (UTC-5), aligned to noon."""
    utc_now = datetime.now(timezone.utc)
    et_offset = timedelta(hours=-5)
    et_now = utc_now + et_offset

    # If before noon ET, we're in yesterday's market (resolving at today's noon)
    # If after noon ET, we're in today's market (resolving at tomorrow's noon)
    if et_now.hour < 12:
        # Current market resolves today at noon
        return et_now.replace(hour=12, minute=0, second=0, microsecond=0)
    else:
        # Current market resolves tomorrow at noon
        return (et_now + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)


def get_current_slug(asset: Asset, horizon: MarketHorizon) -> str:
    """Get the slug for the current market slot.

    Args:
        asset: Crypto asset (BTC or ETH).
        horizon: Market time horizon.

    Returns:
        Slug string for the current market.
    """
    if horizon == MarketHorizon.H1:
        et_now = get_current_hour_et()
        resolution_hour = et_now + timedelta(hours=1)
        return datetime_to_slug_1h(asset, resolution_hour)
    elif horizon == MarketHorizon.D1:
        resolution_day = get_current_day_et()
        return datetime_to_slug_d1(asset, resolution_day)
    else:  # M15 or H4
        timestamp = get_current_slot_timestamp(horizon)
        return timestamp_to_slug(asset, horizon, timestamp)


# ============================================================================
# Fetch Functions
# ============================================================================

def _parse_json_field(value, default=None):
    """Parse a field that might be a JSON string or already parsed."""
    if value is None:
        return default if default is not None else []
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default if default is not None else []
    return value


def _detect_asset_from_slug(slug: str) -> Asset:
    """Detect asset type from slug."""
    slug_lower = slug.lower()
    if slug_lower.startswith("eth") or slug_lower.startswith("ethereum"):
        return Asset.ETH
    return Asset.BTC


def _parse_crypto_event(data: dict, asset: Asset, horizon: MarketHorizon) -> Optional[CryptoPrediction]:
    """Parse crypto event data from API response."""
    markets = data.get("markets", [])
    if not markets:
        return None

    market = markets[0]

    # Parse outcomes and prices
    outcomes = _parse_json_field(market.get("outcomes"), [])
    prices = _parse_json_field(market.get("outcomePrices"), [])
    token_ids = _parse_json_field(market.get("clobTokenIds"), [])

    # Find Up and Down indices
    up_idx = None
    down_idx = None
    for i, outcome in enumerate(outcomes):
        if outcome.lower() == "up":
            up_idx = i
        elif outcome.lower() == "down":
            down_idx = i

    if up_idx is None or down_idx is None:
        return None

    # Parse dates
    start_time = None
    end_time = None

    if market.get("startDate"):
        try:
            start_time = datetime.fromisoformat(market["startDate"].replace("Z", "+00:00"))
        except ValueError:
            pass

    if market.get("endDate"):
        try:
            end_time = datetime.fromisoformat(market["endDate"].replace("Z", "+00:00"))
        except ValueError:
            pass

    # For timestamp-based markets, derive times from slug if not available
    if horizon in (MarketHorizon.M15, MarketHorizon.H4) and (not start_time or not end_time):
        slug = data.get("slug", "")
        ts = slug_to_timestamp(slug)
        if ts:
            start_time = datetime.fromtimestamp(ts, tz=timezone.utc)
            end_time = datetime.fromtimestamp(ts + horizon.value, tz=timezone.utc)

    return CryptoPrediction(
        slug=data.get("slug", ""),
        event_id=str(data.get("id", "")),
        title=data.get("title", ""),
        asset=asset,
        horizon=horizon,
        start_time=start_time,
        end_time=end_time,
        up_price=Decimal(str(prices[up_idx])) if up_idx < len(prices) else Decimal("0"),
        down_price=Decimal(str(prices[down_idx])) if down_idx < len(prices) else Decimal("0"),
        up_token_id=token_ids[up_idx] if up_idx < len(token_ids) else "",
        down_token_id=token_ids[down_idx] if down_idx < len(token_ids) else "",
        liquidity=Decimal(str(data.get("liquidity", 0))),
        volume=Decimal(str(data.get("volume", 0))),
        active=data.get("active", False),
        closed=data.get("closed", False),
    )


async def _fetch_prediction_by_slug(
    slug: str, asset: Asset, horizon: MarketHorizon
) -> Optional[CryptoPrediction]:
    """Fetch a prediction by slug."""
    url = f"{GAMMA_API_BASE}/events?slug={slug}"

    # Disable brotli to avoid aiohttp compatibility issues
    headers = {"Accept-Encoding": "gzip, deflate"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    return None

                data = await response.json()
                if not data:
                    return None

                event = data[0] if isinstance(data, list) else data
                return _parse_crypto_event(event, asset, horizon)
    except Exception:
        return None


async def fetch_current_prediction(
    asset: Asset, horizon: MarketHorizon
) -> Optional[CryptoPrediction]:
    """Fetch the current prediction market.

    Args:
        asset: Crypto asset (BTC or ETH).
        horizon: Market time horizon.

    Returns:
        CryptoPrediction or None if not found.
    """
    slug = get_current_slug(asset, horizon)
    return await _fetch_prediction_by_slug(slug, asset, horizon)


