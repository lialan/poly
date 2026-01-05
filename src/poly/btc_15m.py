"""Bitcoin 15-minute prediction market utilities."""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import aiohttp

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
POLYMARKET_BASE = "https://polymarket.com"
INTERVAL_SECONDS = 900  # 15 minutes


@dataclass
class BTC15mPrediction:
    """Represents a 15-minute BTC Up/Down prediction market."""

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
    def time_remaining(self) -> float:
        """Get seconds remaining until this slot ends."""
        ts = slug_to_timestamp(self.slug)
        if ts:
            slot_end = datetime.fromtimestamp(ts + INTERVAL_SECONDS, tz=timezone.utc)
            now = datetime.now(timezone.utc)
            return (slot_end - now).total_seconds()
        return 0

    @property
    def is_live(self) -> bool:
        """Check if market is currently in its trading window."""
        now = datetime.now(timezone.utc)
        # Use slug timestamp as authoritative start time
        ts = slug_to_timestamp(self.slug)
        if ts:
            slot_start = datetime.fromtimestamp(ts, tz=timezone.utc)
            slot_end = datetime.fromtimestamp(ts + INTERVAL_SECONDS, tz=timezone.utc)
            return slot_start <= now < slot_end and self.active and not self.closed
        return self.active and not self.closed


def get_current_slot_timestamp() -> int:
    """Get the Unix timestamp for the current 15-minute slot."""
    now = int(time.time())
    return (now // INTERVAL_SECONDS) * INTERVAL_SECONDS


def get_slot_timestamps(count: int = 5, include_current: bool = True) -> list[int]:
    """Get timestamps for current and upcoming 15-minute slots.

    Args:
        count: Number of slots to return.
        include_current: Whether to include the current slot.

    Returns:
        List of Unix timestamps.
    """
    current = get_current_slot_timestamp()
    start = current if include_current else current + INTERVAL_SECONDS
    return [start + (i * INTERVAL_SECONDS) for i in range(count)]


def timestamp_to_slug(timestamp: int) -> str:
    """Convert Unix timestamp to BTC 15m market slug."""
    return f"btc-updown-15m-{timestamp}"


def slug_to_timestamp(slug: str) -> Optional[int]:
    """Extract Unix timestamp from BTC 15m market slug."""
    try:
        parts = slug.split("-")
        return int(parts[-1])
    except (IndexError, ValueError):
        return None


def timestamp_to_url(timestamp: int) -> str:
    """Convert Unix timestamp to Polymarket URL."""
    slug = timestamp_to_slug(timestamp)
    return f"{POLYMARKET_BASE}/event/{slug}"


async def fetch_btc_15m_prediction(timestamp: int) -> Optional[BTC15mPrediction]:
    """Fetch a specific 15-minute BTC prediction market.

    Args:
        timestamp: Unix timestamp for the 15-minute slot.

    Returns:
        BTC15mPrediction object or None if not found.
    """
    slug = timestamp_to_slug(timestamp)
    url = f"{GAMMA_API_BASE}/events?slug={slug}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                return None

            data = await response.json()
            if not data:
                return None

            event = data[0] if isinstance(data, list) else data
            return _parse_btc_15m_event(event)


async def fetch_current_and_upcoming(count: int = 5) -> list[BTC15mPrediction]:
    """Fetch current and upcoming BTC 15-minute predictions.

    Args:
        count: Number of predictions to fetch (including current).

    Returns:
        List of BTC15mPrediction objects.
    """
    timestamps = get_slot_timestamps(count)

    async with aiohttp.ClientSession() as session:
        tasks = [_fetch_single(session, ts) for ts in timestamps]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    predictions = []
    for result in results:
        if isinstance(result, BTC15mPrediction):
            predictions.append(result)

    return predictions


async def _fetch_single(session: aiohttp.ClientSession, timestamp: int) -> Optional[BTC15mPrediction]:
    """Fetch a single prediction using existing session."""
    slug = timestamp_to_slug(timestamp)
    url = f"{GAMMA_API_BASE}/events?slug={slug}"

    try:
        async with session.get(url) as response:
            if response.status != 200:
                return None

            data = await response.json()
            if not data:
                return None

            event = data[0] if isinstance(data, list) else data
            return _parse_btc_15m_event(event)
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


def _parse_btc_15m_event(data: dict) -> Optional[BTC15mPrediction]:
    """Parse BTC 15m event data from API response."""
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

    if not start_time or not end_time:
        # Fallback: derive from slug timestamp
        slug = data.get("slug", "")
        ts = slug_to_timestamp(slug)
        if ts:
            start_time = datetime.fromtimestamp(ts, tz=timezone.utc)
            end_time = datetime.fromtimestamp(ts + INTERVAL_SECONDS, tz=timezone.utc)

    return BTC15mPrediction(
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


def print_predictions(predictions: list[BTC15mPrediction]) -> None:
    """Print predictions in a formatted table."""
    print("\n" + "=" * 80)
    print("BTC 15-Minute Predictions")
    print("=" * 80)

    for i, pred in enumerate(predictions):
        status = "LIVE" if pred.is_live else ("UPCOMING" if not pred.closed else "CLOSED")
        remaining = pred.time_remaining

        if remaining > 0:
            mins, secs = divmod(int(remaining), 60)
            time_str = f"{mins}m {secs}s remaining"
        else:
            time_str = "Ended"

        print(f"\n[{i+1}] {pred.title}")
        print(f"    Status: {status} | {time_str}")
        print(f"    UP: {pred.up_probability:.1f}% | DOWN: {pred.down_probability:.1f}%")
        print(f"    Liquidity: ${pred.liquidity:,.2f} | Volume: ${pred.volume:,.2f}")
        print(f"    URL: {pred.url}")

    print("\n" + "=" * 80)
