#!/usr/bin/env python3
"""Test script for BTC 15-minute predictions."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from poly.btc_15m import (
    fetch_current_and_upcoming,
    print_predictions,
    get_slot_timestamps,
    timestamp_to_url,
)


async def main():
    print("Fetching BTC 15-minute predictions...")
    print()

    # Show the URLs we're going to fetch
    timestamps = get_slot_timestamps(5)
    print("Target URLs:")
    for i, ts in enumerate(timestamps):
        label = "CURRENT" if i == 0 else f"NEXT {i}"
        print(f"  [{label}] {timestamp_to_url(ts)}")

    print()

    # Fetch predictions
    predictions = await fetch_current_and_upcoming(5)

    if not predictions:
        print("No predictions found!")
        return

    # Print formatted output
    print_predictions(predictions)

    # Also print raw data for first prediction
    if predictions:
        pred = predictions[0]
        print("\nRAW DATA (first prediction):")
        print(f"  slug = {pred.slug!r}")
        print(f"  event_id = {pred.event_id!r}")
        print(f"  start_time = {pred.start_time}")
        print(f"  end_time = {pred.end_time}")
        print(f"  up_token_id = {pred.up_token_id[:40]}..." if pred.up_token_id else "  up_token_id = None")
        print(f"  down_token_id = {pred.down_token_id[:40]}..." if pred.down_token_id else "  down_token_id = None")


if __name__ == "__main__":
    asyncio.run(main())
