"""Gamma API client for fetching Polymarket event data (no auth required)."""

import asyncio
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional
from datetime import datetime

import aiohttp

logger = logging.getLogger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"


@dataclass
class OutcomeToken:
    """Represents an outcome token in a market."""

    token_id: str
    outcome: str
    price: Decimal
    winner: Optional[bool] = None


@dataclass
class SubMarket:
    """Represents a sub-market (specific outcome) within an event."""

    id: str
    condition_id: str
    question: str
    slug: str
    outcomes: list[str]
    outcome_prices: list[Decimal]
    tokens: list[OutcomeToken]
    liquidity: Decimal
    volume: Decimal
    active: bool
    closed: bool
    end_date: Optional[datetime] = None
    description: str = ""


@dataclass
class Event:
    """Represents a Polymarket event with multiple markets."""

    id: str
    slug: str
    title: str
    description: str
    markets: list[SubMarket]
    liquidity: Decimal
    volume: Decimal
    active: bool
    closed: bool
    end_date: Optional[datetime] = None

    @property
    def num_markets(self) -> int:
        return len(self.markets)

    def get_market_by_outcome(self, outcome: str) -> Optional[SubMarket]:
        """Find a market by its outcome name (case-insensitive partial match)."""
        outcome_lower = outcome.lower()
        for market in self.markets:
            if outcome_lower in market.question.lower():
                return market
        return None


async def fetch_event_by_slug(slug: str) -> Optional[Event]:
    """Fetch event data from Gamma API by slug.

    Args:
        slug: The event slug (e.g., 'bitcoin-price-on-january-6')

    Returns:
        Event object or None if not found.
    """
    url = f"{GAMMA_API_BASE}/events?slug={slug}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                logger.error(f"Failed to fetch event: HTTP {response.status}")
                return None

            data = await response.json()

            if not data:
                return None

            # API returns a list, get first item
            event_data = data[0] if isinstance(data, list) else data
            return _parse_event(event_data)


async def fetch_event_by_id(event_id: str) -> Optional[Event]:
    """Fetch event data from Gamma API by ID.

    Args:
        event_id: The event ID.

    Returns:
        Event object or None if not found.
    """
    url = f"{GAMMA_API_BASE}/events/{event_id}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                logger.error(f"Failed to fetch event: HTTP {response.status}")
                return None

            data = await response.json()
            return _parse_event(data) if data else None


async def fetch_markets_by_event(slug: str) -> list[SubMarket]:
    """Fetch all markets for an event.

    Args:
        slug: The event slug.

    Returns:
        List of SubMarket objects.
    """
    event = await fetch_event_by_slug(slug)
    return event.markets if event else []


async def search_events(query: str, limit: int = 10) -> list[Event]:
    """Search for events by query string.

    Args:
        query: Search query.
        limit: Maximum results to return.

    Returns:
        List of matching Event objects.
    """
    url = f"{GAMMA_API_BASE}/events?title_contains={query}&limit={limit}&active=true"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                logger.error(f"Failed to search events: HTTP {response.status}")
                return []

            data = await response.json()
            return [_parse_event(e) for e in data if e]


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


def _parse_event(data: dict) -> Event:
    """Parse event data from API response."""
    markets = []

    for m in data.get("markets", []):
        tokens = []

        # Parse outcomes (comes as JSON string like '["Yes", "No"]')
        outcomes = _parse_json_field(m.get("outcomes"), [])

        # Parse outcome prices (comes as JSON string)
        outcome_prices_raw = _parse_json_field(m.get("outcomePrices"), [])
        outcome_prices = [Decimal(str(p)) for p in outcome_prices_raw]

        # Build tokens from clobTokenIds
        clob_tokens = _parse_json_field(m.get("clobTokenIds"), [])

        for i, outcome in enumerate(outcomes):
            token_id = clob_tokens[i] if i < len(clob_tokens) else ""
            price = outcome_prices[i] if i < len(outcome_prices) else Decimal("0")
            tokens.append(OutcomeToken(
                token_id=token_id,
                outcome=outcome,
                price=price,
            ))

        # Parse end date
        end_date = None
        if m.get("endDate"):
            try:
                end_date = datetime.fromisoformat(m["endDate"].replace("Z", "+00:00"))
            except ValueError:
                pass

        markets.append(SubMarket(
            id=str(m.get("id", "")),
            condition_id=m.get("conditionId", ""),
            question=m.get("question", ""),
            slug=m.get("slug", ""),
            outcomes=outcomes,
            outcome_prices=outcome_prices,
            tokens=tokens,
            liquidity=Decimal(str(m.get("liquidity", 0))),
            volume=Decimal(str(m.get("volume", 0))),
            active=m.get("active", False),
            closed=m.get("closed", False),
            end_date=end_date,
            description=m.get("description", ""),
        ))

    # Parse event end date
    end_date = None
    if data.get("endDate"):
        try:
            end_date = datetime.fromisoformat(data["endDate"].replace("Z", "+00:00"))
        except ValueError:
            pass

    return Event(
        id=str(data.get("id", "")),
        slug=data.get("slug", ""),
        title=data.get("title", ""),
        description=data.get("description", ""),
        markets=markets,
        liquidity=Decimal(str(data.get("liquidity", 0))),
        volume=Decimal(str(data.get("volume", 0))),
        active=data.get("active", False),
        closed=data.get("closed", False),
        end_date=end_date,
    )


def extract_slug_from_url(url: str) -> Optional[str]:
    """Extract event slug from a Polymarket URL.

    Args:
        url: Full Polymarket URL (e.g., https://polymarket.com/event/bitcoin-price-on-january-6)

    Returns:
        Event slug or None.
    """
    import re
    match = re.search(r'/event/([^/?]+)', url)
    return match.group(1) if match else None


# Convenience function for direct URL fetching
async def fetch_event_from_url(url: str) -> Optional[Event]:
    """Fetch event data directly from a Polymarket URL.

    Args:
        url: Full Polymarket event URL.

    Returns:
        Event object or None.
    """
    slug = extract_slug_from_url(url)
    if not slug:
        logger.error(f"Could not extract slug from URL: {url}")
        return None
    return await fetch_event_by_slug(slug)
