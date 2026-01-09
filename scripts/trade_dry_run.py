#!/usr/bin/env python3
"""
Trade Execution Dry Run

Tests the trade execution API without placing real orders.
Verifies:
- Configuration and credentials
- Market resolution (slug -> token_id)
- Order book access
- CLOB client initialization
- API endpoint connectivity

Usage:
    python scripts/trade_dry_run.py
    python scripts/trade_dry_run.py --market btc-updown-15m-1767795300
    python scripts/trade_dry_run.py --live  # Actually place a tiny test order
"""

import argparse
import asyncio
import sys
import time
from datetime import datetime, timezone

# Add src to path for imports
sys.path.insert(0, "src")

from poly import (
    Asset,
    MarketHorizon,
    fetch_current_prediction,
    PolymarketAPI,
    OrderSide,
    OrderTimeInForce,
    ExecutionConfig,
    TradingNotConfiguredError,
)
from poly.api.polymarket_config import PolymarketConfig
from poly.project_config import get_polymarket_config


def load_polymarket_config() -> PolymarketConfig:
    """Load PolymarketConfig from various sources.

    Tries in order:
    1. Project config (config/poly.json -> polymarket section)
    2. Standard PolymarketConfig.load() (config/polymarket.json, env vars, etc.)
    """
    # Try project config first
    try:
        proj_config = get_polymarket_config()
        if proj_config.wallet_address:
            return PolymarketConfig(
                wallet_address=proj_config.wallet_address,
                private_key=proj_config.private_key,
            )
    except Exception:
        pass

    # Fall back to standard loading
    return PolymarketConfig.load()


class DryRunResult:
    """Tracks dry run test results."""

    def __init__(self):
        self.passed = []
        self.failed = []
        self.warnings = []

    def ok(self, test: str, detail: str = ""):
        self.passed.append((test, detail))
        status = f"  [OK] {test}"
        if detail:
            status += f" - {detail}"
        print(status)

    def fail(self, test: str, error: str):
        self.failed.append((test, error))
        print(f"  [FAIL] {test} - {error}")

    def warn(self, test: str, message: str):
        self.warnings.append((test, message))
        print(f"  [WARN] {test} - {message}")

    def summary(self):
        print("\n" + "=" * 60)
        print("DRY RUN SUMMARY")
        print("=" * 60)
        print(f"  Passed:   {len(self.passed)}")
        print(f"  Failed:   {len(self.failed)}")
        print(f"  Warnings: {len(self.warnings)}")

        if self.failed:
            print("\nFailed tests:")
            for test, error in self.failed:
                print(f"  - {test}: {error}")

        if self.warnings:
            print("\nWarnings:")
            for test, msg in self.warnings:
                print(f"  - {test}: {msg}")

        return len(self.failed) == 0


async def run_dry_run(
    market_slug: str | None = None,
    live: bool = False,
    outcome: str = "Yes",
    size: float = 1.0,
) -> bool:
    """Run the dry run tests.

    Args:
        market_slug: Specific market to test (or auto-detect current 15m)
        live: If True, place a real test order
        outcome: Outcome to test ("Yes" or "No")
        size: Size for live test order

    Returns:
        True if all tests passed
    """
    result = DryRunResult()

    print("=" * 60)
    print("TRADE EXECUTION DRY RUN")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    # =========================================================================
    # Step 1: Configuration
    # =========================================================================
    print("\n[1/6] Configuration")

    try:
        config = load_polymarket_config()
        result.ok("Config loaded", f"wallet: {config.wallet_address[:10]}...")
    except ValueError as e:
        result.fail("Config loaded", str(e))
        print("\n  Hint: Set credentials in one of:")
        print("    - config/poly.json (polymarket.wallet_address)")
        print("    - config/polymarket.json")
        print("    - POLYMARKET_WALLET_ADDRESS env var")
        return result.summary()
    except Exception as e:
        result.fail("Config loaded", str(e))
        return result.summary()

    if config.private_key:
        result.ok("Private key available", "trading enabled")
    else:
        result.warn("Private key", "not configured - trading disabled")

    # =========================================================================
    # Step 2: Market Resolution
    # =========================================================================
    print("\n[2/6] Market Resolution")

    # Get current market if not specified
    if not market_slug:
        try:
            prediction = await asyncio.wait_for(
                fetch_current_prediction(Asset.BTC, MarketHorizon.M15),
                timeout=10.0,
            )
            market_slug = prediction.slug
            result.ok("Current market fetched", market_slug)
        except asyncio.TimeoutError:
            result.fail("Current market fetch", "timeout after 10s")
            return result.summary()
        except Exception as e:
            result.fail("Current market fetch", str(e))
            return result.summary()
    else:
        result.ok("Using specified market", market_slug)

    # =========================================================================
    # Step 3: API Connection
    # =========================================================================
    print("\n[3/6] API Connection")

    api = PolymarketAPI(config)

    try:
        # Test market lookup via Gamma API
        start = time.time()
        market = await asyncio.wait_for(
            api.get_market_by_slug(market_slug),
            timeout=10.0,
        )
        elapsed = (time.time() - start) * 1000

        if market:
            result.ok("Gamma API", f"market found ({elapsed:.0f}ms)")
        else:
            result.fail("Gamma API", f"market not found: {market_slug}")
            await api.close()
            return result.summary()
    except asyncio.TimeoutError:
        result.fail("Gamma API", "timeout after 10s")
        await api.close()
        return result.summary()
    except Exception as e:
        result.fail("Gamma API", str(e))
        await api.close()
        return result.summary()

    # =========================================================================
    # Step 4: Token Resolution
    # =========================================================================
    print("\n[4/6] Token Resolution")

    # Handle both token formats
    import json
    tokens = market.get("tokens", [])
    clob_token_ids = market.get("clobTokenIds", [])
    outcomes_list = market.get("outcomes", [])

    # Parse JSON strings if needed (API returns these as JSON-encoded strings)
    if isinstance(clob_token_ids, str):
        clob_token_ids = json.loads(clob_token_ids)
    if isinstance(outcomes_list, str):
        outcomes_list = json.loads(outcomes_list)

    up_token = None
    down_token = None

    if tokens:
        # Old format: tokens array
        for token in tokens:
            token_outcome = token.get("outcome", "").lower()
            if token_outcome in ("yes", "up"):
                up_token = token.get("token_id")
            elif token_outcome in ("no", "down"):
                down_token = token.get("token_id")
    elif clob_token_ids and outcomes_list:
        # New format: parallel arrays
        for i, outcome_name in enumerate(outcomes_list):
            if outcome_name.lower() in ("yes", "up"):
                up_token = clob_token_ids[i]
            elif outcome_name.lower() in ("no", "down"):
                down_token = clob_token_ids[i]

    if up_token:
        result.ok("UP/YES token", f"{up_token[:20]}...")
    else:
        result.fail("UP/YES token", "not found in market")

    if down_token:
        result.ok("DOWN/NO token", f"{down_token[:20]}...")
    else:
        result.fail("DOWN/NO token", "not found in market")

    # Test internal resolver
    try:
        resolved_token = await api._resolve_token_id(market_slug, outcome)
        result.ok(f"Token resolver ({outcome})", f"{resolved_token[:20]}...")
    except ValueError as e:
        result.fail(f"Token resolver ({outcome})", str(e))

    # =========================================================================
    # Step 5: Order Book Access
    # =========================================================================
    print("\n[5/6] Order Book Access")

    test_token = up_token  # Use the UP/YES token for orderbook test
    bids = []  # Initialize for use in live test section

    if test_token:
        try:
            start = time.time()
            orderbook = await asyncio.wait_for(
                api.get_orderbook(test_token),
                timeout=10.0,
            )
            elapsed = (time.time() - start) * 1000

            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])

            result.ok("CLOB orderbook", f"{len(bids)} bids, {len(asks)} asks ({elapsed:.0f}ms)")

            if bids:
                best_bid = float(bids[0].get("price", 0))
                result.ok("Best bid", f"${best_bid:.4f}")
            else:
                result.warn("Best bid", "no bids in orderbook")

            if asks:
                best_ask = float(asks[0].get("price", 0))
                result.ok("Best ask", f"${best_ask:.4f}")
            else:
                result.warn("Best ask", "no asks in orderbook")

        except asyncio.TimeoutError:
            result.fail("CLOB orderbook", "timeout after 10s")
        except Exception as e:
            result.fail("CLOB orderbook", str(e))

    # =========================================================================
    # Step 6: CLOB Client (Trading)
    # =========================================================================
    print("\n[6/6] CLOB Client Setup")

    if not config.private_key:
        result.warn("CLOB client", "skipped - no private key")
    else:
        try:
            # This will initialize the CLOB client and derive API credentials
            start = time.time()
            clob_client = api._get_clob_client()
            elapsed = (time.time() - start) * 1000
            result.ok("CLOB client initialized", f"({elapsed:.0f}ms)")

            # Check API credentials were derived
            if api._api_creds:
                result.ok("API credentials derived")
            else:
                result.warn("API credentials", "not cached")

        except TradingNotConfiguredError as e:
            result.fail("CLOB client", str(e))
        except ImportError as e:
            result.fail("CLOB client", f"missing dependency: {e}")
        except Exception as e:
            result.fail("CLOB client", str(e))

    # =========================================================================
    # Live Test (Optional)
    # =========================================================================
    if live and config.private_key:
        print("\n[LIVE] Placing Test Order")
        print("  WARNING: This will place a REAL order!")

        # Get best bid to place order well below market
        if bids:
            best_bid = float(bids[0].get("price", 0))
            # Place order 20% below best bid (unlikely to fill)
            test_price = round(best_bid * 0.8, 2)
            test_price = max(0.01, min(0.99, test_price))  # Clamp to valid range
        else:
            test_price = 0.10  # Default low price

        print(f"  Market: {market_slug}")
        print(f"  Side: BUY")
        print(f"  Outcome: {outcome}")
        print(f"  Price: ${test_price:.2f} (below market)")
        print(f"  Size: {size}")

        try:
            start = time.time()
            order_result = await api.place_order_by_slug(
                market_slug=market_slug,
                outcome=outcome,
                side=OrderSide.BUY,
                price=test_price,
                size=size,
                time_in_force=OrderTimeInForce.GTC,
            )
            elapsed = (time.time() - start) * 1000

            if order_result.success:
                result.ok("Order placed", f"{order_result.order_id[:16]}... ({elapsed:.0f}ms)")

                # Cancel the test order
                print("  Canceling test order...")
                try:
                    await api.cancel_order(order_result.order_id)
                    result.ok("Order canceled")
                except Exception as e:
                    result.warn("Order cancel", str(e))
            else:
                result.fail("Order placement", order_result.error_message)

        except Exception as e:
            result.fail("Order placement", str(e))
    elif live and not config.private_key:
        result.warn("Live test", "skipped - no private key configured")

    # =========================================================================
    # Cleanup
    # =========================================================================
    await api.close()

    # =========================================================================
    # Summary
    # =========================================================================
    return result.summary()


def main():
    parser = argparse.ArgumentParser(
        description="Trade execution dry run - test API without placing orders"
    )
    parser.add_argument(
        "--market",
        type=str,
        help="Market slug to test (default: current BTC 15m market)",
    )
    parser.add_argument(
        "--outcome",
        type=str,
        default="Yes",
        choices=["Yes", "No"],
        help="Outcome to test (default: Yes)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Place a real test order (will be canceled immediately)",
    )
    parser.add_argument(
        "--size",
        type=float,
        default=1.0,
        help="Size for live test order (default: 1.0)",
    )

    args = parser.parse_args()

    success = asyncio.run(run_dry_run(
        market_slug=args.market,
        live=args.live,
        outcome=args.outcome,
        size=args.size,
    ))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
