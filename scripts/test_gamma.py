#!/usr/bin/env python3
"""Test script for Gamma API event fetching."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from poly.api.gamma import fetch_event_from_url, fetch_event_by_slug


async def main():
    url = "https://polymarket.com/event/bitcoin-price-on-january-6?tid=1767632823580"

    print("=" * 60)
    print("Fetching Polymarket Event Data")
    print("=" * 60)
    print(f"\nURL: {url}\n")

    event = await fetch_event_from_url(url)

    if not event:
        print("Failed to fetch event data")
        return

    print(f"Event ID: {event.id}")
    print(f"Title: {event.title}")
    print(f"Slug: {event.slug}")
    print(f"Active: {event.active}")
    print(f"Closed: {event.closed}")
    print(f"Total Liquidity: ${event.liquidity:,.2f}")
    print(f"Total Volume: ${event.volume:,.2f}")
    print(f"Number of Markets: {event.num_markets}")

    if event.end_date:
        print(f"End Date: {event.end_date}")

    print("\n" + "-" * 60)
    print("MARKETS (Sub-outcomes)")
    print("-" * 60)

    for i, market in enumerate(event.markets, 1):
        print(f"\n[{i}] {market.question}")
        print(f"    Condition ID: {market.condition_id}")
        print(f"    Liquidity: ${market.liquidity:,.2f}")
        print(f"    Volume: ${market.volume:,.2f}")
        print(f"    Active: {market.active} | Closed: {market.closed}")

        print("    Tokens:")
        for token in market.tokens:
            prob_pct = float(token.price) * 100
            print(f"      - {token.outcome}: {prob_pct:.1f}% (${token.price})")
            print(f"        Token ID: {token.token_id[:40]}..." if len(token.token_id) > 40 else f"        Token ID: {token.token_id}")

    print("\n" + "=" * 60)
    print("RAW DATA SAMPLE (first market)")
    print("=" * 60)

    if event.markets:
        m = event.markets[0]
        print(f"\nmarket.id = {m.id!r}")
        print(f"market.condition_id = {m.condition_id!r}")
        print(f"market.question = {m.question!r}")
        print(f"market.outcomes = {m.outcomes!r}")
        print(f"market.outcome_prices = {m.outcome_prices!r}")
        print(f"market.tokens[0].token_id = {m.tokens[0].token_id!r}" if m.tokens else "No tokens")


if __name__ == "__main__":
    asyncio.run(main())
