"""Utility functions for Polymarket trading."""

import asyncio
import logging
from decimal import Decimal, ROUND_DOWN
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def setup_logging(level: int = logging.INFO) -> None:
    """Configure logging for the application.

    Args:
        level: Logging level (default INFO).
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def round_price(price: Decimal, decimals: int = 4) -> Decimal:
    """Round price to specified decimal places.

    Args:
        price: Price to round.
        decimals: Number of decimal places.

    Returns:
        Rounded price.
    """
    quantize_str = "0." + "0" * decimals
    return price.quantize(Decimal(quantize_str), rounding=ROUND_DOWN)


def round_size(size: Decimal, decimals: int = 2) -> Decimal:
    """Round order size to specified decimal places.

    Args:
        size: Size to round.
        decimals: Number of decimal places.

    Returns:
        Rounded size.
    """
    quantize_str = "0." + "0" * decimals
    return size.quantize(Decimal(quantize_str), rounding=ROUND_DOWN)


def probability_to_price(probability: float) -> Decimal:
    """Convert probability (0-1) to price.

    Args:
        probability: Probability value between 0 and 1.

    Returns:
        Price as Decimal.
    """
    if not 0 <= probability <= 1:
        raise ValueError("Probability must be between 0 and 1")
    return round_price(Decimal(str(probability)))


def price_to_probability(price: Decimal) -> float:
    """Convert price to probability.

    Args:
        price: Price value.

    Returns:
        Probability as float.
    """
    return float(price)


def calculate_implied_probability(yes_price: Decimal, no_price: Decimal) -> dict:
    """Calculate implied probabilities from token prices.

    Args:
        yes_price: YES token price.
        no_price: NO token price.

    Returns:
        Dict with normalized probabilities and vig.
    """
    total = yes_price + no_price
    vig = float(total - 1) if total > 1 else 0

    # Normalize to sum to 1
    if total > 0:
        yes_prob = float(yes_price / total)
        no_prob = float(no_price / total)
    else:
        yes_prob = no_prob = 0.5

    return {
        "yes_probability": yes_prob,
        "no_probability": no_prob,
        "vig": vig,
        "vig_percent": vig * 100,
    }


def calculate_expected_value(
    probability: float,
    price: Decimal,
    side: str,
) -> Decimal:
    """Calculate expected value of a trade.

    Args:
        probability: Your estimated true probability (0-1).
        price: Current market price.
        side: "BUY" or "SELL".

    Returns:
        Expected value as Decimal.
    """
    price_float = float(price)

    if side.upper() == "BUY":
        # Buying YES: win (1-price) if correct, lose price if wrong
        ev = probability * (1 - price_float) - (1 - probability) * price_float
    else:
        # Selling YES: win price if wrong, lose (1-price) if correct
        ev = (1 - probability) * price_float - probability * (1 - price_float)

    return Decimal(str(round(ev, 6)))


async def retry_async(
    func,
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
) -> T:
    """Retry an async function with exponential backoff.

    Args:
        func: Async callable to retry.
        max_retries: Maximum retry attempts.
        delay: Initial delay between retries.
        backoff: Multiplier for delay on each retry.
        exceptions: Tuple of exceptions to catch.

    Returns:
        Result of the function call.
    """
    last_exception = None
    current_delay = delay

    for attempt in range(max_retries + 1):
        try:
            return await func()
        except exceptions as e:
            last_exception = e
            if attempt < max_retries:
                logger.warning(
                    f"Attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {current_delay}s..."
                )
                await asyncio.sleep(current_delay)
                current_delay *= backoff
            else:
                logger.error(f"All {max_retries + 1} attempts failed")

    raise last_exception


def format_currency(amount: Decimal, symbol: str = "$") -> str:
    """Format amount as currency string.

    Args:
        amount: Amount to format.
        symbol: Currency symbol.

    Returns:
        Formatted string.
    """
    return f"{symbol}{amount:,.2f}"


def format_percentage(value: float, decimals: int = 2) -> str:
    """Format value as percentage string.

    Args:
        value: Value to format (0.5 = 50%).
        decimals: Decimal places.

    Returns:
        Formatted percentage string.
    """
    return f"{value * 100:.{decimals}f}%"
