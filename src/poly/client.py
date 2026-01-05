"""Main Polymarket client for API interactions."""

import asyncio
import logging
from decimal import Decimal
from typing import Optional

from .config import Config
from .models import Market, Order, Position, Side, OrderType

logger = logging.getLogger(__name__)


class PolymarketClient:
    """Client for interacting with Polymarket APIs."""

    def __init__(self, config: Config):
        """Initialize the Polymarket client.

        Args:
            config: Configuration object with API credentials.
        """
        self.config = config
        self._clob_client = None
        self._gamma_client = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize API clients and authenticate."""
        if self._initialized:
            return

        try:
            from py_clob_client.client import ClobClient

            self._clob_client = ClobClient(
                host=self.config.host,
                key=self.config.private_key,
                chain_id=self.config.chain_id,
                creds={
                    "apiKey": self.config.api_key,
                    "secret": self.config.api_secret,
                    "passphrase": self.config.passphrase,
                },
            )
            self._initialized = True
            logger.info("Polymarket client initialized successfully")
        except ImportError:
            logger.warning(
                "py-clob-client not installed. "
                "Install with: pip install py-clob-client"
            )
            raise
        except Exception as e:
            logger.error(f"Failed to initialize client: {e}")
            raise

    async def close(self) -> None:
        """Clean up resources."""
        self._initialized = False
        self._clob_client = None
        logger.info("Polymarket client closed")

    async def __aenter__(self) -> "PolymarketClient":
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()

    def _ensure_initialized(self) -> None:
        """Raise if client not initialized."""
        if not self._initialized:
            raise RuntimeError("Client not initialized. Call initialize() first.")

    async def get_markets(self, limit: int = 100, active_only: bool = True) -> list[Market]:
        """Fetch available markets.

        Args:
            limit: Maximum number of markets to return.
            active_only: Only return active markets.

        Returns:
            List of Market objects.
        """
        self._ensure_initialized()

        try:
            response = self._clob_client.get_markets()
            markets = []
            for m in response[:limit]:
                if active_only and not m.get("active", False):
                    continue
                markets.append(
                    Market(
                        id=m["condition_id"],
                        question=m.get("question", ""),
                        slug=m.get("slug", ""),
                        description=m.get("description", ""),
                        active=m.get("active", False),
                        closed=m.get("closed", False),
                        tokens=m.get("tokens", []),
                    )
                )
            return markets
        except Exception as e:
            logger.error(f"Failed to fetch markets: {e}")
            raise

    async def get_market(self, market_id: str) -> Optional[Market]:
        """Fetch a specific market by ID.

        Args:
            market_id: The market condition ID.

        Returns:
            Market object or None if not found.
        """
        self._ensure_initialized()

        try:
            m = self._clob_client.get_market(market_id)
            if not m:
                return None
            return Market(
                id=m["condition_id"],
                question=m.get("question", ""),
                slug=m.get("slug", ""),
                description=m.get("description", ""),
                active=m.get("active", False),
                closed=m.get("closed", False),
                tokens=m.get("tokens", []),
            )
        except Exception as e:
            logger.error(f"Failed to fetch market {market_id}: {e}")
            raise

    async def get_orderbook(self, token_id: str) -> dict:
        """Fetch orderbook for a token.

        Args:
            token_id: The token ID.

        Returns:
            Orderbook data with bids and asks.
        """
        self._ensure_initialized()

        try:
            return self._clob_client.get_order_book(token_id)
        except Exception as e:
            logger.error(f"Failed to fetch orderbook for {token_id}: {e}")
            raise

    async def get_price(self, token_id: str) -> Optional[Decimal]:
        """Get current price for a token.

        Args:
            token_id: The token ID.

        Returns:
            Current mid price or None.
        """
        self._ensure_initialized()

        try:
            book = await self.get_orderbook(token_id)
            bids = book.get("bids", [])
            asks = book.get("asks", [])

            if bids and asks:
                best_bid = Decimal(str(bids[0]["price"]))
                best_ask = Decimal(str(asks[0]["price"]))
                return (best_bid + best_ask) / 2
            elif bids:
                return Decimal(str(bids[0]["price"]))
            elif asks:
                return Decimal(str(asks[0]["price"]))
            return None
        except Exception as e:
            logger.error(f"Failed to get price for {token_id}: {e}")
            raise

    async def place_order(
        self,
        token_id: str,
        side: Side,
        price: Decimal,
        size: Decimal,
        order_type: OrderType = OrderType.LIMIT,
    ) -> Order:
        """Place an order.

        Args:
            token_id: The token ID to trade.
            side: BUY or SELL.
            price: Limit price.
            size: Order size.
            order_type: LIMIT or MARKET.

        Returns:
            Created Order object.
        """
        self._ensure_initialized()

        try:
            from py_clob_client.order_builder.constants import BUY, SELL

            clob_side = BUY if side == Side.BUY else SELL

            order = self._clob_client.create_order(
                token_id=token_id,
                price=float(price),
                size=float(size),
                side=clob_side,
            )
            response = self._clob_client.post_order(order)

            return Order(
                id=response.get("orderID", ""),
                market_id="",  # Would need to look up
                token_id=token_id,
                side=side,
                price=price,
                size=size,
                order_type=order_type,
            )
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            raise

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order.

        Args:
            order_id: The order ID to cancel.

        Returns:
            True if cancelled successfully.
        """
        self._ensure_initialized()

        try:
            self._clob_client.cancel(order_id)
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            raise

    async def get_positions(self) -> list[Position]:
        """Get current positions.

        Returns:
            List of Position objects.
        """
        self._ensure_initialized()

        try:
            # Note: This would use the CLOB client's position methods
            # Placeholder implementation
            logger.warning("get_positions not fully implemented")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            raise

    async def get_open_orders(self) -> list[Order]:
        """Get open orders.

        Returns:
            List of active Order objects.
        """
        self._ensure_initialized()

        try:
            response = self._clob_client.get_orders()
            orders = []
            for o in response:
                orders.append(
                    Order(
                        id=o.get("id", ""),
                        market_id=o.get("market", ""),
                        token_id=o.get("asset_id", ""),
                        side=Side.BUY if o.get("side") == "BUY" else Side.SELL,
                        price=Decimal(str(o.get("price", 0))),
                        size=Decimal(str(o.get("original_size", 0))),
                        filled_size=Decimal(str(o.get("size_matched", 0))),
                    )
                )
            return orders
        except Exception as e:
            logger.error(f"Failed to fetch open orders: {e}")
            raise
