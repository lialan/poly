"""Tests for Polymarket client."""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from poly.config import Config
from poly.client import PolymarketClient
from poly.models import Market, Order, Side, OrderType


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    return Config(
        api_key="test_key",
        api_secret="test_secret",
        passphrase="test_pass",
        private_key="0x" + "1" * 64,
    )


@pytest.fixture
def client(mock_config):
    """Create a client instance."""
    return PolymarketClient(mock_config)


class TestConfig:
    """Tests for Config class."""

    def test_config_creation(self):
        """Test Config can be created with required fields."""
        config = Config(
            api_key="key",
            api_secret="secret",
            passphrase="pass",
            private_key="pk",
        )
        assert config.api_key == "key"
        assert config.chain_id == 137  # Default

    def test_config_defaults(self):
        """Test Config has correct defaults."""
        config = Config(
            api_key="key",
            api_secret="secret",
            passphrase="pass",
            private_key="pk",
        )
        assert config.chain_id == 137
        assert config.host == "https://clob.polymarket.com"
        assert config.gamma_host == "https://gamma-api.polymarket.com"

    def test_from_env_missing_vars(self):
        """Test from_env raises when vars missing."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="Missing required"):
                Config.from_env()

    def test_from_env_optional_returns_none(self):
        """Test from_env_optional returns None when vars missing."""
        with patch.dict("os.environ", {}, clear=True):
            assert Config.from_env_optional() is None


class TestPolymarketClient:
    """Tests for PolymarketClient class."""

    def test_client_not_initialized(self, client):
        """Test client raises when not initialized."""
        with pytest.raises(RuntimeError, match="not initialized"):
            client._ensure_initialized()

    @pytest.mark.asyncio
    async def test_context_manager(self, client):
        """Test client can be used as context manager."""
        with patch.object(client, "initialize", new_callable=AsyncMock):
            with patch.object(client, "close", new_callable=AsyncMock):
                async with client as c:
                    assert c is client

    @pytest.mark.asyncio
    async def test_initialize_without_package(self, client):
        """Test initialize raises when py-clob-client not installed."""
        with patch.dict("sys.modules", {"py_clob_client": None}):
            with pytest.raises(ImportError):
                await client.initialize()


class TestModels:
    """Tests for data models."""

    def test_market_is_tradeable(self):
        """Test Market.is_tradeable property."""
        active_market = Market(
            id="123",
            question="Test?",
            slug="test",
            active=True,
            closed=False,
        )
        assert active_market.is_tradeable

        closed_market = Market(
            id="456",
            question="Test?",
            slug="test",
            active=True,
            closed=True,
        )
        assert not closed_market.is_tradeable

    def test_order_properties(self):
        """Test Order computed properties."""
        order = Order(
            id="ord1",
            market_id="mkt1",
            token_id="tok1",
            side=Side.BUY,
            price=Decimal("0.50"),
            size=Decimal("100"),
            filled_size=Decimal("40"),
        )
        assert order.is_active
        assert order.remaining_size == Decimal("60")

    def test_position_pnl(self):
        """Test Position P&L calculations."""
        from poly.models import Position

        position = Position(
            market_id="mkt1",
            token_id="tok1",
            outcome="Yes",
            size=Decimal("100"),
            avg_price=Decimal("0.40"),
            current_price=Decimal("0.50"),
        )
        assert position.value == Decimal("50")
        assert position.cost_basis == Decimal("40")
        assert position.pnl == Decimal("10")
        assert position.pnl_percent == Decimal("25")


class TestUtils:
    """Tests for utility functions."""

    def test_round_price(self):
        """Test price rounding."""
        from poly.utils import round_price

        assert round_price(Decimal("0.123456"), 4) == Decimal("0.1234")
        assert round_price(Decimal("0.999999"), 2) == Decimal("0.99")

    def test_calculate_implied_probability(self):
        """Test implied probability calculation."""
        from poly.utils import calculate_implied_probability

        result = calculate_implied_probability(
            Decimal("0.52"),
            Decimal("0.52"),
        )
        assert result["yes_probability"] == pytest.approx(0.5, rel=0.01)
        assert result["vig"] == pytest.approx(0.04, rel=0.01)

    def test_calculate_expected_value(self):
        """Test expected value calculation."""
        from poly.utils import calculate_expected_value

        # If you think true prob is 60% and price is 50%, EV should be positive
        ev = calculate_expected_value(0.6, Decimal("0.50"), "BUY")
        assert ev > 0

        # If you think true prob is 40% and price is 50%, EV should be negative
        ev = calculate_expected_value(0.4, Decimal("0.50"), "BUY")
        assert ev < 0
