"""Bitcoin prediction market utilities for 15-minute and 1-hour markets."""

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


class MarketHorizon(Enum):
    """Market time horizon."""
    M15 = 900      # 15 minutes
    H1 = 3600      # 1 hour


@dataclass
class BTCPrediction:
    """Represents a BTC Up/Down prediction market (15m or 1h)."""

    slug: str
    event_id: str
    title: str
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
        if self.horizon == MarketHorizon.M15:
            ts = slug_to_timestamp_15m(self.slug)
            if ts:
                slot_end = datetime.fromtimestamp(ts + MarketHorizon.M15.value, tz=timezone.utc)
                now = datetime.now(timezone.utc)
                return (slot_end - now).total_seconds()
        elif self.end_time:
            now = datetime.now(timezone.utc)
            return (self.end_time - now).total_seconds()
        return 0

    @property
    def is_live(self) -> bool:
        """Check if market is currently in its trading window."""
        if self.horizon == MarketHorizon.M15:
            now = datetime.now(timezone.utc)
            ts = slug_to_timestamp_15m(self.slug)
            if ts:
                slot_start = datetime.fromtimestamp(ts, tz=timezone.utc)
                slot_end = datetime.fromtimestamp(ts + MarketHorizon.M15.value, tz=timezone.utc)
                return slot_start <= now < slot_end and self.active and not self.closed
        return self.active and not self.closed


# ============================================================================
# Slug Generation Functions
# ============================================================================

def get_current_slot_timestamp_15m() -> int:
    """Get the Unix timestamp for the current 15-minute slot."""
    now = int(time.time())
    return (now // MarketHorizon.M15.value) * MarketHorizon.M15.value


def timestamp_to_slug_15m(timestamp: int) -> str:
    """Convert Unix timestamp to BTC 15m market slug."""
    return f"btc-updown-15m-{timestamp}"


def slug_to_timestamp_15m(slug: str) -> Optional[int]:
    """Extract Unix timestamp from BTC 15m market slug."""
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


def datetime_to_slug_1h(dt: datetime) -> str:
    """Convert a datetime (in ET) to 1h BTC market slug."""
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

    return f"bitcoin-up-or-down-{month}-{day}-{hour_str}-et"


def get_current_slug(horizon: MarketHorizon) -> str:
    """Get the slug for the current market slot.

    Args:
        horizon: Market time horizon (M15 or H1).

    Returns:
        Slug string for the current market.
    """
    if horizon == MarketHorizon.M15:
        timestamp = get_current_slot_timestamp_15m()
        return timestamp_to_slug_15m(timestamp)
    else:  # H1
        et_now = get_current_hour_et()
        resolution_hour = et_now + timedelta(hours=1)
        return datetime_to_slug_1h(resolution_hour)


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


def _parse_btc_event(data: dict, horizon: MarketHorizon) -> Optional[BTCPrediction]:
    """Parse BTC event data from API response."""
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

    # For 15m markets, derive times from slug if not available
    if horizon == MarketHorizon.M15 and (not start_time or not end_time):
        slug = data.get("slug", "")
        ts = slug_to_timestamp_15m(slug)
        if ts:
            start_time = datetime.fromtimestamp(ts, tz=timezone.utc)
            end_time = datetime.fromtimestamp(ts + MarketHorizon.M15.value, tz=timezone.utc)

    return BTCPrediction(
        slug=data.get("slug", ""),
        event_id=str(data.get("id", "")),
        title=data.get("title", ""),
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


async def _fetch_prediction_by_slug(slug: str, horizon: MarketHorizon) -> Optional[BTCPrediction]:
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
                return _parse_btc_event(event, horizon)
    except Exception:
        return None


async def fetch_current_prediction(horizon: MarketHorizon) -> Optional[BTCPrediction]:
    """Fetch the current BTC prediction market.

    Args:
        horizon: Market time horizon (M15 or H1).

    Returns:
        BTCPrediction or None if not found.
    """
    slug = get_current_slug(horizon)
    return await _fetch_prediction_by_slug(slug, horizon)


async def _fetch_multiple_predictions(slugs: list[str], horizon: MarketHorizon) -> list[BTCPrediction]:
    """Fetch multiple predictions concurrently."""
    # Disable brotli to avoid aiohttp compatibility issues
    headers = {"Accept-Encoding": "gzip, deflate"}

    async with aiohttp.ClientSession() as session:
        async def fetch_one(slug: str) -> Optional[BTCPrediction]:
            url = f"{GAMMA_API_BASE}/events?slug={slug}"
            try:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        return None
                    data = await response.json()
                    if not data:
                        return None
                    event = data[0] if isinstance(data, list) else data
                    return _parse_btc_event(event, horizon)
            except Exception:
                return None

        results = await asyncio.gather(*[fetch_one(slug) for slug in slugs], return_exceptions=True)

    predictions = []
    for result in results:
        if isinstance(result, BTCPrediction):
            predictions.append(result)

    return predictions


# ============================================================================
# Convenience Functions (for backward compatibility)
# ============================================================================

async def fetch_current_15m_prediction() -> Optional[BTCPrediction]:
    """Fetch the current 15-minute BTC prediction market."""
    return await fetch_current_prediction(MarketHorizon.M15)


async def fetch_current_1h_prediction() -> Optional[BTCPrediction]:
    """Fetch the current 1-hour BTC prediction market."""
    return await fetch_current_prediction(MarketHorizon.H1)


async def fetch_btc_15m_prediction(timestamp: int) -> Optional[BTCPrediction]:
    """Fetch a specific 15-minute BTC prediction market."""
    slug = timestamp_to_slug_15m(timestamp)
    return await _fetch_prediction_by_slug(slug, MarketHorizon.M15)


async def fetch_btc_1h_prediction(slug: str) -> Optional[BTCPrediction]:
    """Fetch a specific 1-hour BTC prediction market."""
    return await _fetch_prediction_by_slug(slug, MarketHorizon.H1)


def get_slot_timestamps_15m(count: int = 5, include_current: bool = True) -> list[int]:
    """Get timestamps for current and upcoming 15-minute slots."""
    current = get_current_slot_timestamp_15m()
    start = current if include_current else current + MarketHorizon.M15.value
    return [start + (i * MarketHorizon.M15.value) for i in range(count)]


def get_slot_slugs_1h(count: int = 3, include_current: bool = True) -> list[str]:
    """Get slugs for current and upcoming 1-hour slots."""
    et_now = get_current_hour_et()
    start_offset = 1 if include_current else 2

    slugs = []
    for i in range(count):
        resolution_hour = et_now + timedelta(hours=start_offset + i)
        slugs.append(datetime_to_slug_1h(resolution_hour))

    return slugs


async def fetch_upcoming_15m_predictions(count: int = 5) -> list[BTCPrediction]:
    """Fetch current and upcoming 15-minute BTC predictions."""
    timestamps = get_slot_timestamps_15m(count)
    return await _fetch_multiple_predictions(
        [timestamp_to_slug_15m(ts) for ts in timestamps],
        MarketHorizon.M15
    )


async def fetch_upcoming_1h_predictions(count: int = 3) -> list[BTCPrediction]:
    """Fetch current and upcoming 1-hour BTC predictions."""
    slugs = get_slot_slugs_1h(count)
    return await _fetch_multiple_predictions(slugs, MarketHorizon.H1)


def print_predictions(predictions: list[BTCPrediction], title: str = "BTC Predictions") -> None:
    """Print predictions in a formatted table."""
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)

    for i, pred in enumerate(predictions):
        status = "LIVE" if pred.is_live else ("UPCOMING" if not pred.closed else "CLOSED")
        remaining = pred.time_remaining
        horizon_str = "15m" if pred.horizon == MarketHorizon.M15 else "1h"

        if remaining > 0:
            hours, remainder = divmod(int(remaining), 3600)
            mins, secs = divmod(remainder, 60)
            if hours > 0:
                time_str = f"{hours}h {mins}m remaining"
            else:
                time_str = f"{mins}m {secs}s remaining"
        else:
            time_str = "Ended"

        print(f"\n[{i+1}] [{horizon_str}] {pred.title}")
        print(f"    Status: {status} | {time_str}")
        print(f"    UP: {pred.up_probability:.1f}% | DOWN: {pred.down_probability:.1f}%")
        print(f"    Liquidity: ${pred.liquidity:,.2f} | Volume: ${pred.volume:,.2f}")
        print(f"    URL: {pred.url}")

    print("\n" + "=" * 80)


# ============================================================================
# Backward Compatibility Aliases
# ============================================================================

# For btc_15m.py compatibility
BTC15mPrediction = BTCPrediction
get_current_slot_timestamp = get_current_slot_timestamp_15m
get_slot_timestamps = get_slot_timestamps_15m
timestamp_to_slug = timestamp_to_slug_15m
slug_to_timestamp = slug_to_timestamp_15m
INTERVAL_SECONDS = MarketHorizon.M15.value

# For btc_1h.py compatibility
BTC1hPrediction = BTCPrediction
get_current_slot_slug = lambda: get_current_slug(MarketHorizon.H1)
get_slot_slugs = get_slot_slugs_1h
datetime_to_slug = datetime_to_slug_1h
