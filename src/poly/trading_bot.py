"""Trading bot with WebSocket data feed and configurable decision function.

A monitoring bot that:
1. Maintains a WebSocket connection for real-time market data
2. Pre-fetches historical data from Bigtable each decision cycle
3. Runs a configurable decision function at fixed intervals
4. Provides detailed timing information for debugging

Usage:
    from poly.trading_bot import TradingBot, TradingBotConfig, MarketContext, DecisionResult

    def my_decision(context: MarketContext) -> DecisionResult:
        # Your trading logic here
        return DecisionResult(should_trade=False)

    config = TradingBotConfig(asset=Asset.BTC, horizon=MarketHorizon.M15)
    bot = TradingBot(config, decision_fn=my_decision)
    await bot.run()
"""

import asyncio
import json
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Protocol, Any

from .markets import (
    Asset,
    MarketHorizon,
    fetch_current_prediction,
    slug_to_timestamp,
    CryptoPrediction,
)
from .market_feed import MarketFeed, MarketState, PriceUpdate
from .storage.bigtable import (
    BigtableWriter,
    TABLE_BTC_15M,
    TABLE_BTC_1H,
    TABLE_BTC_4H,
    TABLE_BTC_D1,
    TABLE_ETH_15M,
    TABLE_ETH_1H,
    TABLE_ETH_4H,
)
from .api.polymarket import PolymarketAPI
from .api.polymarket_config import PolymarketConfig

logger = logging.getLogger(__name__)

# Map asset/horizon to Bigtable table name
ASSET_TABLES = {
    Asset.BTC: {
        MarketHorizon.M15: TABLE_BTC_15M,
        MarketHorizon.H1: TABLE_BTC_1H,
        MarketHorizon.H4: TABLE_BTC_4H,
        MarketHorizon.D1: TABLE_BTC_D1,
    },
    Asset.ETH: {
        MarketHorizon.M15: TABLE_ETH_15M,
        MarketHorizon.H1: TABLE_ETH_1H,
        MarketHorizon.H4: TABLE_ETH_4H,
    },
}


@dataclass
class TradingBotConfig:
    """Configuration for the trading bot."""

    # Market configuration
    asset: Asset = Asset.BTC
    horizon: MarketHorizon = MarketHorizon.M15

    # Timing configuration
    decision_interval_sec: float = 3.0
    bigtable_lookback_sec: float = 300.0  # 5 minutes of historical data
    bigtable_fetch_limit: int = 100

    # REST API test configuration
    test_rest_apis: bool = True
    api_timeout_sec: float = 10.0

    # Debug/logging
    debug_timing: bool = True
    log_level: str = "INFO"

    # Bigtable configuration (optional overrides)
    bigtable_project_id: Optional[str] = None
    bigtable_instance_id: Optional[str] = None

    # Polymarket wallet (for REST API testing)
    wallet_address: Optional[str] = None

    @classmethod
    def from_env(cls) -> "TradingBotConfig":
        """Load config from environment variables with defaults."""
        asset_str = os.getenv("TRADING_BOT_ASSET", "btc").lower()
        asset = Asset.BTC if asset_str == "btc" else Asset.ETH

        return cls(
            asset=asset,
            decision_interval_sec=float(os.getenv("DECISION_INTERVAL", "3.0")),
            bigtable_lookback_sec=float(os.getenv("BIGTABLE_LOOKBACK_SEC", "300.0")),
            bigtable_project_id=os.getenv("BIGTABLE_PROJECT_ID"),
            bigtable_instance_id=os.getenv("BIGTABLE_INSTANCE_ID"),
            debug_timing=os.getenv("DEBUG_TIMING", "true").lower() == "true",
            wallet_address=os.getenv("POLYMARKET_WALLET_ADDRESS"),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "TradingBotConfig":
        """Load config from structured JSON file.

        Expected structure:
        {
            "market": {"asset": "btc", "horizon": "15m"},
            "timing": {"decision_interval_sec": 3.0, "bigtable_lookback_sec": 300.0, "bigtable_fetch_limit": 100},
            "bigtable": {"project_id": "...", "instance_id": "..."},
            "api": {"test_rest_apis": true, "wallet_address": null},
            "debug": {"timing": true, "log_level": "INFO"}
        }
        """
        path = Path(path)
        with open(path) as f:
            data = json.load(f)

        # Extract sections
        market = data.get("market", {})
        timing = data.get("timing", {})
        bigtable = data.get("bigtable", {})
        api = data.get("api", {})
        debug = data.get("debug", {})

        # Parse asset
        asset_str = market.get("asset", "btc").lower()
        asset = Asset.BTC if asset_str == "btc" else Asset.ETH

        # Parse horizon
        horizon_str = market.get("horizon", "15m").lower()
        horizon_map = {"15m": MarketHorizon.M15, "1h": MarketHorizon.H1, "4h": MarketHorizon.H4, "d1": MarketHorizon.D1}
        horizon = horizon_map.get(horizon_str, MarketHorizon.M15)

        return cls(
            asset=asset,
            horizon=horizon,
            decision_interval_sec=float(timing.get("decision_interval_sec", 3.0)),
            bigtable_lookback_sec=float(timing.get("bigtable_lookback_sec", 300.0)),
            bigtable_fetch_limit=int(timing.get("bigtable_fetch_limit", 100)),
            test_rest_apis=api.get("test_rest_apis", True),
            debug_timing=debug.get("timing", True),
            log_level=debug.get("log_level", "INFO"),
            bigtable_project_id=bigtable.get("project_id"),
            bigtable_instance_id=bigtable.get("instance_id"),
            wallet_address=api.get("wallet_address"),
        )

    @classmethod
    def from_project_config(cls, config_path: Optional[str | Path] = None) -> "TradingBotConfig":
        """Load from centralized project config (config/poly.json).

        Uses the trading_bot section of the project config plus bigtable section.
        """
        from .project_config import load_config

        project_config = load_config(config_path)
        trading = project_config.get_trading_bot_section()

        # Extract nested sections
        market = trading.get("market", {})
        timing = trading.get("timing", {})
        api = trading.get("api", {})
        debug = trading.get("debug", {})

        # Parse asset
        asset_str = market.get("asset", "btc").lower()
        asset = Asset.BTC if asset_str == "btc" else Asset.ETH

        # Parse horizon
        horizon_str = market.get("horizon", "15m").lower()
        horizon_map = {"15m": MarketHorizon.M15, "1h": MarketHorizon.H1, "4h": MarketHorizon.H4, "d1": MarketHorizon.D1}
        horizon = horizon_map.get(horizon_str, MarketHorizon.M15)

        return cls(
            asset=asset,
            horizon=horizon,
            decision_interval_sec=float(timing.get("decision_interval_sec", 3.0)),
            bigtable_lookback_sec=float(timing.get("bigtable_lookback_sec", 300.0)),
            bigtable_fetch_limit=int(timing.get("bigtable_fetch_limit", 100)),
            test_rest_apis=api.get("test_rest_apis", True),
            debug_timing=debug.get("timing", True),
            log_level=debug.get("log_level", "INFO"),
            bigtable_project_id=project_config.bigtable.project_id,
            bigtable_instance_id=project_config.bigtable.instance_id,
            wallet_address=project_config.polymarket.wallet_address,
        )

    @classmethod
    def load(cls, config_path: Optional[str | Path] = None) -> "TradingBotConfig":
        """Load config with smart detection.

        Priority:
        1. Explicit config_path if provided (can be poly.json or trading_bot.json)
        2. config/poly.json if exists (centralized config)
        3. config/trading_bot.json if exists (legacy)
        4. Environment variables
        """
        # Check explicit path
        if config_path:
            path = Path(config_path)
            if path.name == "poly.json":
                return cls.from_project_config(config_path)
            return cls.from_json(config_path)

        # Check centralized config
        poly_json = Path(__file__).parent.parent.parent / "config" / "poly.json"
        if poly_json.exists():
            return cls.from_project_config(poly_json)

        # Check legacy trading_bot.json
        default_json = Path(__file__).parent.parent.parent / "config" / "trading_bot.json"
        if default_json.exists():
            return cls.from_json(default_json)

        # Fall back to environment variables
        return cls.from_env()


@dataclass
class MarketContext:
    """Context passed to the decision function each cycle."""

    # Current timestamp
    timestamp: float

    # Current market info
    market_slug: str
    asset: Asset
    horizon: MarketHorizon

    # Live WebSocket data (from MarketFeed)
    live_state: Optional[MarketState]

    # Historical data (pre-fetched from Bigtable)
    historical_snapshots: list[dict]

    # Asset spot price
    spot_price: Optional[float]

    # Timing info
    time_remaining_sec: float
    cycle_number: int

    @property
    def implied_prob(self) -> Optional[float]:
        """Get implied probability from live state."""
        if self.live_state:
            return self.live_state.implied_prob
        return None


@dataclass
class DecisionResult:
    """Result from the decision function."""

    should_trade: bool
    signal: Optional[str] = None  # e.g., "buy_yes", "buy_no", "sell_yes", "sell_no"
    confidence: Optional[float] = None  # 0.0 to 1.0
    reason: Optional[str] = None
    metadata: Optional[dict] = None


class DecisionFunction(Protocol):
    """Protocol for decision functions.

    Users implement this protocol to create custom trading strategies.
    """

    def __call__(self, context: MarketContext) -> DecisionResult:
        ...


def no_op_decision(context: MarketContext) -> DecisionResult:
    """Default decision function that always returns False (no trading)."""
    return DecisionResult(
        should_trade=False,
        reason="Default no-op decision function",
    )


@dataclass
class CycleTiming:
    """Timing breakdown for a single decision cycle."""

    cycle_number: int
    timestamp: float

    # Timing in milliseconds
    bigtable_fetch_ms: float
    context_build_ms: float
    decision_ms: float
    total_ms: float

    # Data counts
    snapshots_fetched: int
    ws_update_count: int

    def __str__(self) -> str:
        return (
            f"Cycle {self.cycle_number}: "
            f"BT={self.bigtable_fetch_ms:.1f}ms, "
            f"CTX={self.context_build_ms:.1f}ms, "
            f"DEC={self.decision_ms:.1f}ms, "
            f"TOTAL={self.total_ms:.1f}ms | "
            f"snaps={self.snapshots_fetched}, ws_updates={self.ws_update_count}"
        )


class TradingBot:
    """Trading bot with WebSocket feed and configurable decision function.

    Architecture:
    1. Startup: Test REST APIs, initialize MarketFeed and BigtableWriter
    2. Main loop: Every N seconds:
       a. Fetch recent Bigtable data (pre-fetched window)
       b. Build MarketContext with live + historical data
       c. Call decision function
       d. Log timing if debug enabled
    3. Shutdown: Clean up resources on SIGINT/SIGTERM
    """

    def __init__(
        self,
        config: TradingBotConfig,
        decision_fn: Optional[DecisionFunction] = None,
    ):
        self.config = config
        self.decision_fn = decision_fn or no_op_decision

        # Components (initialized in start())
        self._feed: Optional[MarketFeed] = None
        self._bigtable: Optional[BigtableWriter] = None

        # State
        self._running = False
        self._cycle_count = 0
        self._current_prediction: Optional[CryptoPrediction] = None
        self._last_market_slug: Optional[str] = None

        # Signal handling
        self._shutdown_event: Optional[asyncio.Event] = None
        self._original_sigint = None
        self._original_sigterm = None

    async def start(self) -> None:
        """Initialize all components and test connectivity."""
        logger.info("Starting trading bot...")
        t_start = time.time()

        # 1. Setup signal handlers
        self._setup_signal_handlers()
        self._shutdown_event = asyncio.Event()

        # 2. Initialize Bigtable
        t0 = time.time()
        try:
            self._bigtable = BigtableWriter(
                project_id=self.config.bigtable_project_id,
                instance_id=self.config.bigtable_instance_id,
            )
            if self.config.debug_timing:
                logger.info(f"  Bigtable init: {(time.time()-t0)*1000:.1f}ms")
        except Exception as e:
            logger.warning(f"  Bigtable init failed: {e} (continuing without historical data)")
            self._bigtable = None

        # 3. Test REST APIs
        if self.config.test_rest_apis:
            t0 = time.time()
            api_ok = await self._test_rest_apis()
            if self.config.debug_timing:
                logger.info(f"  REST API test: {(time.time()-t0)*1000:.1f}ms ({'OK' if api_ok else 'FAILED'})")

        # 4. Initialize current market
        t0 = time.time()
        if not await self._initialize_market():
            raise RuntimeError("Failed to initialize market - could not fetch prediction")
        if self.config.debug_timing:
            logger.info(f"  Market init: {(time.time()-t0)*1000:.1f}ms")

        # 5. Initialize MarketFeed
        t0 = time.time()
        self._feed = MarketFeed(on_update=self._on_ws_update)
        await self._feed.add_market(
            self._current_prediction.slug,
            self._current_prediction.up_token_id,
            self._current_prediction.down_token_id,
        )
        if self.config.debug_timing:
            logger.info(f"  MarketFeed init: {(time.time()-t0)*1000:.1f}ms")

        self._running = True
        self._last_market_slug = self._current_prediction.slug
        logger.info(f"Trading bot started in {(time.time()-t_start)*1000:.1f}ms")
        logger.info(f"  Market: {self._current_prediction.slug}")
        logger.info(f"  Asset: {self.config.asset.value.upper()}")
        logger.info(f"  Horizon: {self.config.horizon.name}")

    async def run(self) -> None:
        """Main entry point. Runs until shutdown signal received."""
        await self.start()

        # Start WebSocket feed as background task
        feed_task = asyncio.create_task(self._feed.start())

        # Run decision loop
        try:
            await self._run_decision_loop()
        except asyncio.CancelledError:
            logger.info("Decision loop cancelled")
        finally:
            await self.stop()
            feed_task.cancel()
            try:
                await feed_task
            except asyncio.CancelledError:
                pass

    async def stop(self) -> None:
        """Clean shutdown of all components."""
        logger.info("Stopping trading bot...")
        self._running = False

        if self._feed:
            await self._feed.stop()
            self._feed = None

        if self._bigtable:
            self._bigtable.close()
            self._bigtable = None

        # Restore signal handlers
        self._restore_signal_handlers()

        logger.info("Trading bot stopped")

    async def _test_rest_apis(self) -> bool:
        """Test REST API connectivity at startup."""
        try:
            # Just test we can fetch current market
            prediction = await fetch_current_prediction(self.config.asset, self.config.horizon)
            if prediction:
                logger.info(f"    REST API OK: Fetched {prediction.slug}")
                return True
            else:
                logger.warning("    REST API: Could not fetch current market")
                return False
        except Exception as e:
            logger.error(f"    REST API error: {e}")
            return False

    async def _initialize_market(self) -> bool:
        """Fetch current market and prepare for monitoring."""
        self._current_prediction = await fetch_current_prediction(
            self.config.asset, self.config.horizon
        )
        return self._current_prediction is not None

    async def _run_decision_loop(self) -> None:
        """Main decision loop running every decision_interval_sec."""
        logger.info(
            f"Decision loop started: interval={self.config.decision_interval_sec}s, "
            f"lookback={self.config.bigtable_lookback_sec}s"
        )

        while self._running and not self._shutdown_event.is_set():
            cycle_start = time.time()

            try:
                # Check if market has changed (new slot)
                await self._check_market_refresh()

                # Execute decision cycle
                timing = await self._execute_cycle()

                if self.config.debug_timing:
                    ts_str = datetime.now().strftime("%H:%M:%S")
                    print(f"[{ts_str}] {timing}")

            except Exception as e:
                logger.error(f"Cycle error: {e}", exc_info=True)

            # Sleep for remaining interval time
            elapsed = time.time() - cycle_start
            sleep_time = max(0.1, self.config.decision_interval_sec - elapsed)

            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=sleep_time,
                )
                break  # Shutdown requested
            except asyncio.TimeoutError:
                pass  # Normal timeout, continue loop

    async def _check_market_refresh(self) -> None:
        """Check if we need to switch to a new market slot."""
        # For 15m markets, check if time remaining is very low
        if self._current_prediction and self._current_prediction.time_remaining < 0:
            logger.info("Market slot expired, refreshing...")
            await self._initialize_market()

            if self._current_prediction and self._current_prediction.slug != self._last_market_slug:
                # New market, update WebSocket subscription
                if self._feed:
                    await self._feed.remove_market(self._last_market_slug)
                    await self._feed.add_market(
                        self._current_prediction.slug,
                        self._current_prediction.up_token_id,
                        self._current_prediction.down_token_id,
                    )
                self._last_market_slug = self._current_prediction.slug
                logger.info(f"Switched to new market: {self._current_prediction.slug}")

    async def _execute_cycle(self) -> CycleTiming:
        """Execute a single decision cycle with timing."""
        self._cycle_count += 1
        cycle_start = time.time()

        # 1. Fetch Bigtable data
        t0 = time.time()
        historical_snapshots = await self._fetch_bigtable_data()
        bigtable_ms = (time.time() - t0) * 1000

        # 2. Build context
        t0 = time.time()
        context = self._build_context(historical_snapshots)
        context_ms = (time.time() - t0) * 1000

        # 3. Call decision function
        t0 = time.time()
        result = self.decision_fn(context)
        decision_ms = (time.time() - t0) * 1000

        # 4. Log decision result if trading
        if result.should_trade:
            logger.info(
                f"DECISION: {result.signal} | conf={result.confidence:.2f if result.confidence else 'N/A'} | {result.reason}"
            )

        # 5. Build timing info
        total_ms = (time.time() - cycle_start) * 1000
        live_state = self._get_live_state()

        return CycleTiming(
            cycle_number=self._cycle_count,
            timestamp=cycle_start,
            bigtable_fetch_ms=bigtable_ms,
            context_build_ms=context_ms,
            decision_ms=decision_ms,
            total_ms=total_ms,
            snapshots_fetched=len(historical_snapshots),
            ws_update_count=live_state.update_count if live_state else 0,
        )

    async def _fetch_bigtable_data(self) -> list[dict]:
        """Pre-fetch recent snapshots from Bigtable."""
        if not self._bigtable:
            return []

        now = time.time()
        start_ts = now - self.config.bigtable_lookback_sec

        # Get the appropriate table name
        table_map = ASSET_TABLES.get(self.config.asset, {})
        table_name = table_map.get(self.config.horizon)
        if not table_name:
            return []

        # Run in executor since BigtableWriter is sync
        loop = asyncio.get_event_loop()
        try:
            snapshots = await loop.run_in_executor(
                None,
                lambda: self._bigtable.get_snapshots(
                    start_ts=start_ts,
                    end_ts=now,
                    limit=self.config.bigtable_fetch_limit,
                    table_name=table_name,
                )
            )
            return snapshots
        except Exception as e:
            logger.warning(f"Bigtable fetch error: {e}")
            return []

    def _build_context(self, historical_snapshots: list[dict]) -> MarketContext:
        """Build MarketContext from live and historical data."""
        live_state = self._get_live_state()

        # Get spot price from latest snapshot
        spot_price = None
        if historical_snapshots:
            spot_price = historical_snapshots[0].get("spot_price")

        # Calculate time remaining
        time_remaining = 0.0
        if self._current_prediction:
            time_remaining = max(0, self._current_prediction.time_remaining)

        return MarketContext(
            timestamp=time.time(),
            market_slug=self._current_prediction.slug if self._current_prediction else "",
            asset=self.config.asset,
            horizon=self.config.horizon,
            live_state=live_state,
            historical_snapshots=historical_snapshots,
            spot_price=spot_price,
            time_remaining_sec=time_remaining,
            cycle_number=self._cycle_count,
        )

    def _get_live_state(self) -> Optional[MarketState]:
        """Get current market state from WebSocket feed."""
        if self._feed and self._current_prediction:
            return self._feed.get_market(self._current_prediction.slug)
        return None

    def _on_ws_update(self, update: PriceUpdate) -> None:
        """Callback for WebSocket updates (for logging/debugging)."""
        # Can be overridden or extended for custom handling
        pass

    def _setup_signal_handlers(self) -> None:
        """Setup SIGINT/SIGTERM handlers for clean shutdown."""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating shutdown...")
            self._running = False
            if self._shutdown_event:
                self._shutdown_event.set()

        self._original_sigint = signal.signal(signal.SIGINT, signal_handler)
        self._original_sigterm = signal.signal(signal.SIGTERM, signal_handler)

    def _restore_signal_handlers(self) -> None:
        """Restore original signal handlers."""
        if self._original_sigint:
            signal.signal(signal.SIGINT, self._original_sigint)
        if self._original_sigterm:
            signal.signal(signal.SIGTERM, self._original_sigterm)

    @property
    def is_running(self) -> bool:
        """Check if bot is running."""
        return self._running

    @property
    def cycle_count(self) -> int:
        """Get number of completed cycles."""
        return self._cycle_count

    @property
    def current_market(self) -> Optional[CryptoPrediction]:
        """Get current market prediction."""
        return self._current_prediction
