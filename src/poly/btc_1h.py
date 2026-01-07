"""Bitcoin 1-hour prediction market utilities."""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

import aiohttp

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
POLYMARKET_BASE = "https://polymarket.com"
INTERVAL_SECONDS = 3600  # 1 hour

# Months for slug generation
MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december"
]


@dataclass
class BTC1hPrediction:
    """Represents a 1-hour BTC Up/Down prediction market."""

    slug: str
    event_id: str
    title: str
    start_time: datetime
    end_time: datetime
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
        """Get the resolution time (end of the 1-hour candle)."""
        return self.end_time

    @property
    def time_remaining(self) -> float:
        """Get seconds remaining until this market resolves."""
        if self.end_time:
            now = datetime.now(timezone.utc)
            return (self.end_time - now).total_seconds()
        return 0

    @property
    def is_live(self) -> bool:
        """Check if market is currently in its trading window."""
        return self.active and not self.closed


def get_current_hour_et() -> datetime:
    """Get the current hour in ET timezone."""
    # ET is UTC-5 (EST) or UTC-4 (EDT)
    # For simplicity, we'll use UTC-5 (EST)
    utc_now = datetime.now(timezone.utc)
    et_offset = timedelta(hours=-5)
    et_now = utc_now + et_offset
    # Round down to the current hour
    return et_now.replace(minute=0, second=0, microsecond=0)


def datetime_to_slug(dt: datetime) -> str:
    """Convert a datetime to 1h BTC market slug.

    Args:
        dt: Datetime in ET timezone (hour should be the resolution hour)

    Returns:
        Slug like 'bitcoin-up-or-down-january-6-9pm-et'
    """
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


def get_current_slot_slug() -> str:
    """Get the slug for the current 1-hour slot."""
    et_now = get_current_hour_et()
    # The market resolves at the END of the hour, so current hour's market
    # is the one that resolves at the next hour
    resolution_hour = et_now + timedelta(hours=1)
    return datetime_to_slug(resolution_hour)


def get_slot_slugs(count: int = 3, include_current: bool = True) -> list[str]:
    """Get slugs for current and upcoming 1-hour slots.

    Args:
        count: Number of slots to return.
        include_current: Whether to include the current slot.

    Returns:
        List of slugs.
    """
    et_now = get_current_hour_et()
    start_offset = 1 if include_current else 2  # +1 because resolution is next hour

    slugs = []
    for i in range(count):
        resolution_hour = et_now + timedelta(hours=start_offset + i)
        slugs.append(datetime_to_slug(resolution_hour))

    return slugs


async def fetch_btc_1h_prediction(slug: str) -> Optional[BTC1hPrediction]:
    """Fetch a specific 1-hour BTC prediction market.

    Args:
        slug: Market slug like 'bitcoin-up-or-down-january-6-9pm-et'

    Returns:
        BTC1hPrediction object or None if not found.
    """
    url = f"{GAMMA_API_BASE}/events?slug={slug}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                return None

            data = await response.json()
            if not data:
                return None

            event = data[0] if isinstance(data, list) else data
            return _parse_btc_1h_event(event)


async def fetch_current_1h_prediction() -> Optional[BTC1hPrediction]:
    """Fetch the current 1-hour BTC prediction market."""
    slug = get_current_slot_slug()
    return await fetch_btc_1h_prediction(slug)


async def fetch_current_and_upcoming_1h(count: int = 3) -> list[BTC1hPrediction]:
    """Fetch current and upcoming 1-hour BTC predictions.

    Args:
        count: Number of predictions to fetch (including current).

    Returns:
        List of BTC1hPrediction objects.
    """
    slugs = get_slot_slugs(count)

    async with aiohttp.ClientSession() as session:
        tasks = [_fetch_single(session, slug) for slug in slugs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    predictions = []
    for result in results:
        if isinstance(result, BTC1hPrediction):
            predictions.append(result)

    return predictions


async def _fetch_single(session: aiohttp.ClientSession, slug: str) -> Optional[BTC1hPrediction]:
    """Fetch a single prediction using existing session."""
    url = f"{GAMMA_API_BASE}/events?slug={slug}"

    try:
        async with session.get(url) as response:
            if response.status != 200:
                return None

            data = await response.json()
            if not data:
                return None

            event = data[0] if isinstance(data, list) else data
            return _parse_btc_1h_event(event)
    except Exception:
        return None


def _parse_json_field(value, default=None):
    """Parse a field that might be a JSON string or already parsed."""
    import json
    if value is None:
        return default if default is not None else []
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default if default is not None else []
    return value


def _parse_btc_1h_event(data: dict) -> Optional[BTC1hPrediction]:
    """Parse BTC 1h event data from API response."""
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

    return BTC1hPrediction(
        slug=data.get("slug", ""),
        event_id=str(data.get("id", "")),
        title=data.get("title", ""),
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


def print_predictions(predictions: list[BTC1hPrediction]) -> None:
    """Print predictions in a formatted table."""
    print("\n" + "=" * 80)
    print("BTC 1-Hour Predictions")
    print("=" * 80)

    for i, pred in enumerate(predictions):
        status = "LIVE" if pred.is_live else ("UPCOMING" if not pred.closed else "CLOSED")
        remaining = pred.time_remaining

        if remaining > 0:
            hours, remainder = divmod(int(remaining), 3600)
            mins, secs = divmod(remainder, 60)
            if hours > 0:
                time_str = f"{hours}h {mins}m remaining"
            else:
                time_str = f"{mins}m {secs}s remaining"
        else:
            time_str = "Ended"

        print(f"\n[{i+1}] {pred.title}")
        print(f"    Status: {status} | {time_str}")
        print(f"    UP: {pred.up_probability:.1f}% | DOWN: {pred.down_probability:.1f}%")
        print(f"    Liquidity: ${pred.liquidity:,.2f} | Volume: ${pred.volume:,.2f}")
        print(f"    URL: {pred.url}")

    print("\n" + "=" * 80)
