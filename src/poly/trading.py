"""Trading engine for executing strategies."""

import asyncio
import logging
from decimal import Decimal
from typing import Callable, Optional

from .client import PolymarketClient
from .models import Market, Order, Position, Side, OrderType

logger = logging.getLogger(__name__)


class TradingEngine:
    """Engine for managing trading operations."""

    def __init__(self, client: PolymarketClient):
        """Initialize trading engine.

        Args:
            client: Initialized PolymarketClient.
        """
        self.client = client
        self._running = False
        self._strategies: list[Callable] = []

    async def start(self) -> None:
        """Start the trading engine."""
        if self._running:
            logger.warning("Trading engine already running")
            return

        self._running = True
        logger.info("Trading engine started")

    async def stop(self) -> None:
        """Stop the trading engine."""
        self._running = False
        logger.info("Trading engine stopped")

    @property
    def is_running(self) -> bool:
        """Check if engine is running."""
        return self._running

    def register_strategy(self, strategy: Callable) -> None:
        """Register a trading strategy.

        Args:
            strategy: Async callable that takes the engine and market.
        """
        self._strategies.append(strategy)
        logger.info(f"Registered strategy: {strategy.__name__}")

    async def execute_market_order(
        self,
        token_id: str,
        side: Side,
        size: Decimal,
        slippage: Decimal = Decimal("0.01"),
    ) -> Optional[Order]:
        """Execute a market order with slippage protection.

        Args:
            token_id: Token to trade.
            side: BUY or SELL.
            size: Order size.
            slippage: Maximum allowed slippage (default 1%).

        Returns:
            Executed order or None if price moved too much.
        """
        if not self._running:
            raise RuntimeError("Trading engine not running")

        try:
            # Get current price
            price = await self.client.get_price(token_id)
            if price is None:
                logger.error(f"Could not get price for {token_id}")
                return None

            # Calculate limit price with slippage
            if side == Side.BUY:
                limit_price = price * (1 + slippage)
            else:
                limit_price = price * (1 - slippage)

            logger.info(
                f"Executing {side.value} order: {size} @ {limit_price} "
                f"(mid: {price}, slippage: {slippage})"
            )

            return await self.client.place_order(
                token_id=token_id,
                side=side,
                price=limit_price,
                size=size,
                order_type=OrderType.LIMIT,
            )
        except Exception as e:
            logger.error(f"Failed to execute market order: {e}")
            raise

    async def execute_limit_order(
        self,
        token_id: str,
        side: Side,
        price: Decimal,
        size: Decimal,
    ) -> Order:
        """Execute a limit order.

        Args:
            token_id: Token to trade.
            side: BUY or SELL.
            price: Limit price.
            size: Order size.

        Returns:
            Created order.
        """
        if not self._running:
            raise RuntimeError("Trading engine not running")

        logger.info(f"Placing limit {side.value} order: {size} @ {price}")

        return await self.client.place_order(
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            order_type=OrderType.LIMIT,
        )

    async def cancel_all_orders(self) -> int:
        """Cancel all open orders.

        Returns:
            Number of orders cancelled.
        """
        orders = await self.client.get_open_orders()
        cancelled = 0

        for order in orders:
            try:
                await self.client.cancel_order(order.id)
                cancelled += 1
            except Exception as e:
                logger.error(f"Failed to cancel order {order.id}: {e}")

        logger.info(f"Cancelled {cancelled} orders")
        return cancelled

    async def get_portfolio_value(self) -> Decimal:
        """Calculate total portfolio value.

        Returns:
            Total value of all positions.
        """
        positions = await self.client.get_positions()
        return sum(p.value for p in positions)

    async def run_strategies(self, market: Market) -> None:
        """Run all registered strategies on a market.

        Args:
            market: Market to analyze/trade.
        """
        if not self._running:
            return

        for strategy in self._strategies:
            try:
                await strategy(self, market)
            except Exception as e:
                logger.error(f"Strategy {strategy.__name__} failed: {e}")

    async def monitor_market(
        self,
        market: Market,
        interval: float = 5.0,
        callback: Optional[Callable] = None,
    ) -> None:
        """Monitor a market with periodic updates.

        Args:
            market: Market to monitor.
            interval: Seconds between updates.
            callback: Optional callback on each update.
        """
        logger.info(f"Starting market monitor for {market.id}")

        while self._running:
            try:
                # Refresh market data
                updated_market = await self.client.get_market(market.id)
                if updated_market:
                    market = updated_market

                # Run strategies
                await self.run_strategies(market)

                # Call optional callback
                if callback:
                    await callback(market)

                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(interval)

        logger.info(f"Market monitor stopped for {market.id}")
