"""Telegram notification utilities for Polymarket alerts."""

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from telegram import Bot
from telegram.error import RetryAfter, TelegramError
import pytz

logger = logging.getLogger(__name__)


def escape_markdown(text: str) -> str:
    """Escapes special characters for Telegram MarkdownV2."""
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    translation = str.maketrans({char: f'\\{char}' for char in escape_chars})
    return text.translate(translation)


@dataclass
class TelegramConfig:
    """Configuration for Telegram notifications."""

    bot_token: str
    chat_id: str
    timezone: str = "UTC"

    @classmethod
    def from_env(cls) -> Optional["TelegramConfig"]:
        """Load config from environment variables."""
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

        if not bot_token or not chat_id:
            return None

        return cls(
            bot_token=bot_token,
            chat_id=chat_id,
            timezone=os.getenv("TELEGRAM_TIMEZONE", "UTC"),
        )


class TelegramNotifier:
    """Sends notifications to Telegram."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        alert_timezone: str = "UTC",
    ):
        """Initialize the Telegram notifier.

        Args:
            bot_token: Telegram bot token from @BotFather.
            chat_id: Chat ID to send messages to.
            alert_timezone: Timezone for timestamps in alerts.
        """
        if not bot_token or not chat_id:
            logger.warning("Telegram bot_token or chat_id not set. Notifier disabled.")
            self.bot = None
            self.chat_id = None
        else:
            self.bot = Bot(token=bot_token)
            self.chat_id = chat_id
            logger.info("TelegramNotifier initialized.")

        try:
            self.alert_tz = pytz.timezone(alert_timezone)
        except pytz.UnknownTimeZoneError:
            logger.warning(f"Unknown timezone '{alert_timezone}'. Defaulting to UTC.")
            self.alert_tz = pytz.utc

        # Rate limiting parameters
        self.last_message_time = 0
        self.min_interval_seconds = 3
        self.max_retries = 5
        self.base_delay = 1

    @classmethod
    def from_env(cls) -> Optional["TelegramNotifier"]:
        """Create notifier from environment variables."""
        config = TelegramConfig.from_env()
        if not config:
            return None
        return cls(
            bot_token=config.bot_token,
            chat_id=config.chat_id,
            alert_timezone=config.timezone,
        )

    @classmethod
    def from_config(cls, config: TelegramConfig) -> "TelegramNotifier":
        """Create notifier from config object."""
        return cls(
            bot_token=config.bot_token,
            chat_id=config.chat_id,
            alert_timezone=config.timezone,
        )

    @property
    def is_enabled(self) -> bool:
        """Check if notifier is enabled and configured."""
        return self.bot is not None and self.chat_id is not None

    async def send_message(
        self,
        message: str,
        parse_mode: str = "MarkdownV2",
    ) -> bool:
        """Send a message to Telegram with rate limiting and retries.

        Args:
            message: Message text to send.
            parse_mode: Telegram parse mode ('MarkdownV2', 'HTML', or None).

        Returns:
            True if message sent successfully.
        """
        if not self.is_enabled:
            logger.debug("Telegram notifier disabled; not sending message.")
            return False

        # Rate limiting
        current_time = time.time()
        time_since_last = current_time - self.last_message_time

        if time_since_last < self.min_interval_seconds:
            wait_time = self.min_interval_seconds - time_since_last
            logger.debug(f"Rate limiting: waiting {wait_time:.2f}s")
            await asyncio.sleep(wait_time)

        # Send with retries
        retries = 0
        while retries <= self.max_retries:
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    parse_mode=parse_mode,
                )
                logger.info("Successfully sent message to Telegram.")
                self.last_message_time = time.time()
                return True
            except RetryAfter as e:
                retry_seconds = e.retry_after
                logger.warning(f"Rate limit exceeded. Retrying in {retry_seconds}s.")
                await asyncio.sleep(retry_seconds)
                retries += 1
            except TelegramError as e:
                logger.error(f"Telegram error: {e}")
                delay = self.base_delay * (2 ** retries)
                logger.info(f"Retrying in {delay}s (attempt {retries+1}/{self.max_retries+1})")
                await asyncio.sleep(delay)
                retries += 1
            except Exception as e:
                logger.error(f"Failed to send Telegram message: {e}", exc_info=True)
                return False

        logger.error(f"Failed to send message after {self.max_retries+1} attempts")
        return False

    async def send_plain(self, message: str) -> bool:
        """Send a plain text message (no markdown parsing)."""
        return await self.send_message(message, parse_mode=None)

    async def send_prediction_alert(
        self,
        title: str,
        prediction: str,
        probability: float,
        url: str,
        extra_info: Optional[str] = None,
    ) -> bool:
        """Send a formatted prediction market alert.

        Args:
            title: Market title/question.
            prediction: The predicted outcome (e.g., "UP", "DOWN").
            probability: Probability as decimal (0-1).
            url: URL to the market.
            extra_info: Optional additional information.
        """
        emoji = "🟢" if prediction.upper() in ("UP", "YES", "LONG") else "🔴"

        now = datetime.now(self.alert_tz)
        time_str = now.strftime("%Y-%m-%d %H:%M %Z")

        # Build message with escaped markdown
        message_parts = [
            f"{emoji} *PREDICTION ALERT*",
            "",
            f"*Market:* {escape_markdown(title)}",
            f"*Prediction:* `{escape_markdown(prediction)}`",
            f"*Probability:* `{escape_markdown(f'{probability*100:.1f}%')}`",
            f"*Time:* `{escape_markdown(time_str)}`",
        ]

        if extra_info:
            message_parts.append(f"*Info:* {escape_markdown(extra_info)}")

        message_parts.append(f"\n[View Market]({escape_markdown(url)})")

        message = "\n".join(message_parts)
        return await self.send_message(message)

    async def send_price_alert(
        self,
        symbol: str,
        price: float,
        change_percent: Optional[float] = None,
        alert_type: str = "INFO",
    ) -> bool:
        """Send a price alert.

        Args:
            symbol: Trading symbol (e.g., "BTCUSDT").
            price: Current price.
            change_percent: Optional price change percentage.
            alert_type: Alert type (INFO, WARNING, CRITICAL).
        """
        emoji_map = {
            "INFO": "ℹ️",
            "WARNING": "⚠️",
            "CRITICAL": "🚨",
        }
        emoji = emoji_map.get(alert_type.upper(), "ℹ️")

        now = datetime.now(self.alert_tz)
        time_str = now.strftime("%H:%M %Z")

        message_parts = [
            f"{emoji} *PRICE ALERT*",
            "",
            f"*Symbol:* `{escape_markdown(symbol)}`",
            f"*Price:* `{escape_markdown(f'${price:,.2f}')}`",
        ]

        if change_percent is not None:
            sign = "+" if change_percent >= 0 else ""
            message_parts.append(
                f"*Change:* `{escape_markdown(f'{sign}{change_percent:.2f}%')}`"
            )

        message_parts.append(f"*Time:* `{escape_markdown(time_str)}`")

        message = "\n".join(message_parts)
        return await self.send_message(message)

    async def send_btc_15m_alert(
        self,
        market_title: str,
        up_prob: float,
        down_prob: float,
        url: str,
        btc_price: Optional[float] = None,
    ) -> bool:
        """Send a BTC 15-minute prediction alert.

        Args:
            market_title: Market title.
            up_prob: UP probability (0-1).
            down_prob: DOWN probability (0-1).
            url: Market URL.
            btc_price: Optional current BTC price.
        """
        # Determine which is more likely
        if up_prob > down_prob:
            emoji = "🟢"
            prediction = "UP"
            prob = up_prob
        else:
            emoji = "🔴"
            prediction = "DOWN"
            prob = down_prob

        now = datetime.now(self.alert_tz)
        time_str = now.strftime("%H:%M %Z")

        message_parts = [
            f"{emoji} *BTC 15m Prediction*",
            "",
            f"*Market:* {escape_markdown(market_title)}",
            f"*Prediction:* `{prediction}` \\({escape_markdown(f'{prob*100:.1f}%')}\\)",
            f"UP: `{escape_markdown(f'{up_prob*100:.1f}%')}` \\| DOWN: `{escape_markdown(f'{down_prob*100:.1f}%')}`",
        ]

        if btc_price:
            message_parts.append(f"*BTC Price:* `{escape_markdown(f'${btc_price:,.2f}')}`")

        message_parts.extend([
            f"*Time:* `{escape_markdown(time_str)}`",
            f"\n[View Market]({escape_markdown(url)})",
        ])

        message = "\n".join(message_parts)
        return await self.send_message(message)
