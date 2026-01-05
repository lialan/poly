#!/usr/bin/env python3
"""Test script for Telegram notifier."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

# Load .env file
load_dotenv()

from poly.telegram_notifier import TelegramNotifier, TelegramConfig


async def test_basic_message():
    """Test sending a basic message."""
    config = TelegramConfig.load()
    notifier = TelegramNotifier.from_config(config) if config else None

    if not notifier or not notifier.is_enabled:
        print("Telegram notifier not configured.")
        print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env file.")
        return False

    print("Sending test message...")
    success = await notifier.send_plain("🧪 Test message from Polymarket Trading Platform")

    if success:
        print("✓ Basic message sent successfully!")
    else:
        print("✗ Failed to send basic message")

    return success


async def test_price_alert():
    """Test sending a price alert."""
    config = TelegramConfig.load()
    notifier = TelegramNotifier.from_config(config) if config else None

    if not notifier or not notifier.is_enabled:
        return False

    print("Sending price alert...")
    success = await notifier.send_price_alert(
        symbol="BTCUSDT",
        price=94000.00,
        change_percent=2.5,
        alert_type="INFO",
    )

    if success:
        print("✓ Price alert sent successfully!")
    else:
        print("✗ Failed to send price alert")

    return success


async def test_btc_15m_alert():
    """Test sending a BTC 15m prediction alert."""
    config = TelegramConfig.load()
    notifier = TelegramNotifier.from_config(config) if config else None

    if not notifier or not notifier.is_enabled:
        return False

    print("Sending BTC 15m prediction alert...")
    success = await notifier.send_btc_15m_alert(
        market_title="Bitcoin Up or Down - January 5, 12:30PM-12:45PM ET",
        up_prob=0.55,
        down_prob=0.45,
        url="https://polymarket.com/event/btc-updown-15m-1767634200",
        btc_price=94000.00,
    )

    if success:
        print("✓ BTC 15m alert sent successfully!")
    else:
        print("✗ Failed to send BTC 15m alert")

    return success


async def test_prediction_alert():
    """Test sending a generic prediction alert."""
    config = TelegramConfig.load()
    notifier = TelegramNotifier.from_config(config) if config else None

    if not notifier or not notifier.is_enabled:
        return False

    print("Sending prediction alert...")
    success = await notifier.send_prediction_alert(
        title="Will Bitcoin reach $100k by end of January?",
        prediction="YES",
        probability=0.65,
        url="https://polymarket.com/event/bitcoin-100k",
        extra_info="High volume market",
    )

    if success:
        print("✓ Prediction alert sent successfully!")
    else:
        print("✗ Failed to send prediction alert")

    return success


async def main():
    print("=" * 50)
    print("Telegram Notifier Test")
    print("=" * 50)
    print()

    # Check if configured - try JSON config first, then env
    config = TelegramConfig.load()
    if not config:
        print("❌ Telegram not configured!")
        print()
        print("Option 1: Create config/telegram.json:")
        print('  {"token": "your_token", "chat_id": "your_chat_id"}')
        print()
        print("Option 2: Add to .env file:")
        print("  TELEGRAM_BOT_TOKEN=your_bot_token")
        print("  TELEGRAM_CHAT_ID=your_chat_id")
        print()
        print("Get bot token from @BotFather on Telegram")
        print("Get chat ID by messaging @userinfobot")
        return

    print(f"Bot token: {config.bot_token[:10]}...{config.bot_token[-5:]}")
    print(f"Chat ID: {config.chat_id}")
    print(f"Timezone: {config.timezone}")
    print()

    # Run tests
    results = []

    results.append(("Basic message", await test_basic_message()))
    await asyncio.sleep(3)  # Rate limit

    results.append(("Price alert", await test_price_alert()))
    await asyncio.sleep(3)

    results.append(("BTC 15m alert", await test_btc_15m_alert()))
    await asyncio.sleep(3)

    results.append(("Prediction alert", await test_prediction_alert()))

    # Summary
    print()
    print("=" * 50)
    print("Results:")
    print("=" * 50)
    for name, success in results:
        status = "✓" if success else "✗"
        print(f"  {status} {name}")

    all_passed = all(r[1] for r in results)
    print()
    if all_passed:
        print("All tests passed! ✓")
    else:
        print("Some tests failed. Check your configuration.")


if __name__ == "__main__":
    asyncio.run(main())
