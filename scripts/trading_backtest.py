#!/usr/bin/env python3
"""
Time-Scale Consistency Trader

Implements the 15min vs 1h market consistency model.
Supports both BTC and ETH markets using the same code.

Uses Bigtable historical data for backtesting.
"""

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scipy.stats import norm

from poly.markets import Asset, MarketHorizon
from poly.storage.bigtable import (
    BigtableWriter,
    TABLE_BTC_15M, TABLE_BTC_1H, TABLE_BTC_4H, TABLE_BTC_D1,
    TABLE_ETH_15M, TABLE_ETH_1H, TABLE_ETH_4H,
)

# ============================================================================
# Table Mapping
# ============================================================================

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


# ============================================================================
# Configuration
# ============================================================================

@dataclass
class TradingConfig:
    """Trading configuration parameters."""

    # Asset selection
    asset: Asset = Asset.BTC

    # Capital management
    initial_capital: float = 100.0
    bet_size: float = 10.0

    # Profit taking
    profit_target_pct: float = 0.25

    # Mispricing thresholds
    min_mispricing: float = 0.05
    max_mispricing: float = 0.50

    # Order book depth requirements
    min_depth_usd: float = 50.0

    # Time constraints
    min_time_remaining_sec: float = 60.0

    # Multi-trade settings
    trade_interval_sec: float = 60.0  # Minimum seconds between new trades

    # Transaction costs
    slippage_pct: float = 0.01
    tx_fee_pct: float = 0.01

    # Safety
    epsilon: float = 0.001


# ============================================================================
# Probability Mapping Functions
# ============================================================================

def implied_long_prob(p_short: float, T: float, epsilon: float = 0.001) -> float:
    """
    Map short-horizon UP probability to long-horizon UP probability
    under Gaussian i.i.d / CLT assumption.

    Args:
        p_short: Short-horizon probability (0-1)
        T: Time horizon multiplier (e.g., 4 for 1h from 15m)
        epsilon: Numerical safety margin

    Returns:
        Long-horizon probability
    """
    p_short = max(epsilon, min(1 - epsilon, p_short))
    z = norm.ppf(p_short)
    z_long = math.sqrt(T) * z
    p_long = norm.cdf(z_long)
    return p_long


def implied_1h_prob_from_15m(
    p_15: float,
    k: int,
    N: int = 4,
    epsilon: float = 0.001
) -> float:
    """
    Compute model-implied 1h UP probability given the k-th 15min UP probability.

    Args:
        p_15: Market-implied probability of 15min UP
        k: Position index (1, 2, 3, or 4)
        N: Total intervals (default 4)
        epsilon: Numerical safety

    Returns:
        Model-implied 1h UP probability
    """
    if not (1 <= k <= N):
        raise ValueError(f"k must be between 1 and {N}, got {k}")

    T_eff = N - k + 1
    return implied_long_prob(p_15, T_eff, epsilon)


def mispricing_15m_vs_1h(
    p_15: float,
    p_1h: float,
    k: int,
    N: int = 4,
    epsilon: float = 0.001
) -> float:
    """
    Compute probability mispricing between k-th 15min market and 1h market.

    Returns:
        Signed mispricing value (positive = 1h market too bullish)
    """
    p_1h_model = implied_1h_prob_from_15m(p_15, k, N, epsilon)
    return p_1h - p_1h_model


def get_position_in_hour(timestamp: float) -> int:
    """Get which 15-minute slot we're in within the hour (1-4)."""
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    minute = dt.minute

    if minute < 15:
        return 1
    elif minute < 30:
        return 2
    elif minute < 45:
        return 3
    else:
        return 4


# ============================================================================
# Snapshot Parsing
# ============================================================================

def parse_orderbook_json(orderbook_json: Optional[str]) -> dict:
    """Parse orderbook JSON from Bigtable snapshot.

    New format stores full orderbook as:
    {
        "yes_bids": [[price, size], ...],
        "yes_asks": [[price, size], ...],
        "no_bids": [[price, size], ...],
        "no_asks": [[price, size], ...]
    }
    """
    if not orderbook_json:
        return {"yes_bids": [], "yes_asks": [], "no_bids": [], "no_asks": []}
    try:
        return json.loads(orderbook_json)
    except json.JSONDecodeError:
        return {"yes_bids": [], "yes_asks": [], "no_bids": [], "no_asks": []}


def get_best_prices(orderbook: dict) -> dict:
    """Extract best bid/ask prices from orderbook.

    Bids are sorted ascending (best = last).
    Asks are sorted descending (best = last).
    """
    result = {
        "yes_bid": None,
        "yes_ask": None,
        "no_bid": None,
        "no_ask": None,
    }

    yes_bids = orderbook.get("yes_bids", [])
    yes_asks = orderbook.get("yes_asks", [])
    no_bids = orderbook.get("no_bids", [])
    no_asks = orderbook.get("no_asks", [])

    if yes_bids:
        # Best bid is highest price (last element if sorted ascending)
        result["yes_bid"] = max(level[0] for level in yes_bids)
    if yes_asks:
        # Best ask is lowest price (last element if sorted descending)
        result["yes_ask"] = min(level[0] for level in yes_asks)
    if no_bids:
        result["no_bid"] = max(level[0] for level in no_bids)
    if no_asks:
        result["no_ask"] = min(level[0] for level in no_asks)

    return result


def calculate_available_liquidity(
    orderbook: dict,
    side: str,
    direction: str,
    max_price_impact: float = 0.02
) -> tuple[float, float]:
    """Calculate available liquidity within price impact tolerance."""
    if direction == "buy":
        levels = orderbook.get(f"{side}_asks", [])
        if not levels:
            return 0.0, 0.0
        levels_sorted = sorted(levels, key=lambda x: x[0])
        best_price = levels_sorted[0][0]
        max_price = best_price * (1 + max_price_impact)
    else:
        levels = orderbook.get(f"{side}_bids", [])
        if not levels:
            return 0.0, 0.0
        levels_sorted = sorted(levels, key=lambda x: x[0], reverse=True)
        best_price = levels_sorted[0][0]
        max_price = best_price * (1 - max_price_impact)

    total_size = 0.0
    weighted_price = 0.0

    for price, size in levels_sorted:
        if direction == "buy" and price > max_price:
            break
        if direction == "sell" and price < max_price:
            break
        total_size += size
        weighted_price += price * size

    avg_price = weighted_price / total_size if total_size > 0 else 0
    total_usd = total_size * avg_price if avg_price > 0 else 0

    return total_usd, avg_price


# ============================================================================
# Position and Trade Tracking
# ============================================================================

@dataclass
class Position:
    """Represents an open position."""
    id: int  # Unique identifier for tracking
    entry_time: float
    market_id: str
    side: str
    size_shares: float
    entry_price: float
    cost_usd: float
    peak_value: float = 0.0


@dataclass
class Trade:
    """Completed trade record."""
    entry_time: float
    exit_time: float
    market_id: str
    side: str
    size_shares: float
    entry_price: float
    exit_price: float
    cost_usd: float
    proceeds_usd: float
    pnl: float
    pnl_pct: float
    exit_reason: str


@dataclass
class TradingState:
    """Current trading state with support for multiple parallel positions."""
    asset: Asset
    capital: float
    positions: list[Position] = field(default_factory=list)  # Multiple parallel positions
    trades: list[Trade] = field(default_factory=list)
    total_pnl: float = 0.0
    winning_trades: int = 0
    losing_trades: int = 0
    last_entry_time: float = 0.0  # Track last entry for cooldown
    next_position_id: int = 1  # Auto-increment position ID

    @property
    def win_rate(self) -> float:
        total = self.winning_trades + self.losing_trades
        return self.winning_trades / total if total > 0 else 0.0

    @property
    def open_position_count(self) -> int:
        return len(self.positions)


# ============================================================================
# Market Data Container
# ============================================================================

@dataclass
class MarketData:
    """Combined market data for a single timestamp."""
    timestamp: float
    asset: Asset
    asset_price: float

    # 15m market data
    m15_market_id: Optional[str] = None
    m15_orderbook: Optional[dict] = None
    m15_prices: Optional[dict] = None

    # 1h market data (optional, for future use)
    h1_market_id: Optional[str] = None
    h1_orderbook: Optional[dict] = None
    h1_prices: Optional[dict] = None

    @property
    def yes_mid_15m(self) -> Optional[float]:
        if self.m15_prices and self.m15_prices.get("yes_bid") and self.m15_prices.get("yes_ask"):
            return (self.m15_prices["yes_bid"] + self.m15_prices["yes_ask"]) / 2
        return None

    @property
    def yes_mid_1h(self) -> Optional[float]:
        if self.h1_prices and self.h1_prices.get("yes_bid") and self.h1_prices.get("yes_ask"):
            return (self.h1_prices["yes_bid"] + self.h1_prices["yes_ask"]) / 2
        return None


# ============================================================================
# Trading Logic
# ============================================================================

def evaluate_opportunity(
    data: MarketData,
    config: TradingConfig,
    state: TradingState,
) -> Optional[dict]:
    """Evaluate if current data presents a trading opportunity."""
    # Check if we have enough capital
    if state.capital < config.bet_size:
        return None

    # Check cooldown since last trade
    time_since_last_entry = data.timestamp - state.last_entry_time
    if time_since_last_entry < config.trade_interval_sec:
        return None

    if not data.m15_prices or not data.m15_orderbook:
        return None

    yes_bid = data.m15_prices.get("yes_bid")
    yes_ask = data.m15_prices.get("yes_ask")
    no_bid = data.m15_prices.get("no_bid")
    no_ask = data.m15_prices.get("no_ask")

    if not all([yes_bid, yes_ask, no_bid, no_ask]):
        return None

    yes_mid = (yes_bid + yes_ask) / 2
    k = get_position_in_hour(data.timestamp)

    opportunity = {
        "ts": data.timestamp,
        "market_id": data.m15_market_id,
        "asset": data.asset,
        "k": k,
        "yes_mid": yes_mid,
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": no_bid,
        "no_ask": no_ask,
        "orderbook": data.m15_orderbook,
        "signal": None,
        "side": None,
        "entry_price": None,
        # Include 1h data for logging/analysis (not used in algorithm yet)
        "yes_mid_1h": data.yes_mid_1h,
    }

    # Strategy: Bet on mean reversion when probability is extreme
    if yes_mid < 0.35:
        liq_usd, avg_price = calculate_available_liquidity(data.m15_orderbook, "yes", "buy")
        if liq_usd >= config.min_depth_usd and avg_price > 0:
            implied_mispricing = 0.50 - yes_mid
            if implied_mispricing >= config.min_mispricing:
                opportunity["signal"] = "buy_yes"
                opportunity["side"] = "yes"
                opportunity["entry_price"] = yes_ask
                opportunity["mispricing"] = implied_mispricing
                opportunity["available_liq"] = liq_usd
                return opportunity

    if yes_mid > 0.65:
        liq_usd, avg_price = calculate_available_liquidity(data.m15_orderbook, "no", "buy")
        if liq_usd >= config.min_depth_usd and avg_price > 0:
            implied_mispricing = yes_mid - 0.50
            if implied_mispricing >= config.min_mispricing:
                opportunity["signal"] = "buy_no"
                opportunity["side"] = "no"
                opportunity["entry_price"] = no_ask
                opportunity["mispricing"] = implied_mispricing
                opportunity["available_liq"] = liq_usd
                return opportunity

    return None


def execute_entry(
    opportunity: dict,
    config: TradingConfig,
    state: TradingState,
) -> Optional[Position]:
    """Execute entry into a position."""
    if opportunity is None:
        return None

    entry_price = opportunity["entry_price"]
    if entry_price <= 0:
        return None

    entry_price_with_slippage = entry_price * (1 + config.slippage_pct)
    effective_bet = config.bet_size * (1 - config.tx_fee_pct)
    size_shares = effective_bet / entry_price_with_slippage

    position = Position(
        id=state.next_position_id,
        entry_time=opportunity["ts"],
        market_id=opportunity["market_id"],
        side=opportunity["side"],
        size_shares=size_shares,
        entry_price=entry_price_with_slippage,
        cost_usd=config.bet_size,
    )

    state.capital -= config.bet_size
    state.positions.append(position)
    state.last_entry_time = opportunity["ts"]
    state.next_position_id += 1

    return position


def check_exit(
    position: Position,
    data: MarketData,
    config: TradingConfig,
) -> Optional[tuple[str, float, float]]:
    """Check if position should be exited."""
    if not data.m15_prices:
        return None

    if position.side == "yes":
        bid = data.m15_prices.get("yes_bid")
    else:
        bid = data.m15_prices.get("no_bid")

    if not bid:
        return None

    exit_price_with_slippage = bid * (1 - config.slippage_pct)
    gross_value = position.size_shares * exit_price_with_slippage
    current_value = gross_value * (1 - config.tx_fee_pct)
    pnl_pct = (current_value - position.cost_usd) / position.cost_usd

    if pnl_pct >= config.profit_target_pct:
        # If probability > 80%, hold till end instead of taking profit
        if bid > 0.80:
            pass  # Don't exit, let it ride to market close
        else:
            return ("profit_target", exit_price_with_slippage, current_value)

    if data.m15_market_id != position.market_id:
        return ("market_close", exit_price_with_slippage, current_value)

    return None


def execute_exit(
    position: Position,
    exit_reason: str,
    exit_price: float,
    current_value: float,
    exit_time: float,
    state: TradingState,
) -> Trade:
    """Execute exit from a position."""
    pnl = current_value - position.cost_usd
    pnl_pct = pnl / position.cost_usd if position.cost_usd > 0 else 0

    trade = Trade(
        entry_time=position.entry_time,
        exit_time=exit_time,
        market_id=position.market_id,
        side=position.side,
        size_shares=position.size_shares,
        entry_price=position.entry_price,
        exit_price=exit_price,
        cost_usd=position.cost_usd,
        proceeds_usd=current_value,
        pnl=pnl,
        pnl_pct=pnl_pct,
        exit_reason=exit_reason,
    )

    state.capital += current_value
    state.total_pnl += pnl
    state.trades.append(trade)

    # Remove position from list
    state.positions = [p for p in state.positions if p.id != position.id]

    if pnl > 0:
        state.winning_trades += 1
    else:
        state.losing_trades += 1

    return trade


# ============================================================================
# Backtester
# ============================================================================

def run_backtest(
    market_data: list[MarketData],
    config: TradingConfig,
    verbose: bool = True,
) -> TradingState:
    """Run backtest on historical market data with support for parallel trades."""
    state = TradingState(asset=config.asset, capital=config.initial_capital)

    if verbose:
        print("=" * 70)
        print(f"BACKTEST: {config.asset.value.upper()} (Multi-Trade Mode)")
        print("=" * 70)
        print(f"Initial Capital: ${config.initial_capital:.2f}")
        print(f"Bet Size: ${config.bet_size:.2f}")
        print(f"Profit Target: {config.profit_target_pct * 100:.1f}%")
        print(f"Min Mispricing: {config.min_mispricing * 100:.1f}%")
        print(f"Trade Interval: {config.trade_interval_sec:.0f}s")
        print(f"Data Points: {len(market_data)}")
        print("=" * 70)

    for data in market_data:
        # Check for market changes - exit positions whose market has changed
        positions_to_close = [p for p in state.positions if data.m15_market_id != p.market_id]
        for position in positions_to_close:
            if verbose:
                print(f"\n[MARKET CHANGE] Pos #{position.id}: {position.market_id} -> {data.m15_market_id}")

            if data.m15_prices:
                if position.side == "yes":
                    exit_price = data.m15_prices.get("yes_bid") or position.entry_price
                else:
                    exit_price = data.m15_prices.get("no_bid") or position.entry_price

                exit_price_with_slippage = exit_price * (1 - config.slippage_pct)
                gross_value = position.size_shares * exit_price_with_slippage
                current_value = gross_value * (1 - config.tx_fee_pct)
            else:
                exit_price_with_slippage = position.entry_price
                current_value = position.cost_usd

            trade = execute_exit(
                position,
                "market_close",
                exit_price_with_slippage,
                current_value,
                data.timestamp,
                state,
            )

            if verbose:
                print(f"  Exit: ${trade.proceeds_usd:.2f} | PnL: ${trade.pnl:.2f} ({trade.pnl_pct*100:.1f}%)")

        # Check for exits on all remaining positions
        positions_snapshot = list(state.positions)  # Copy to avoid modification during iteration
        for position in positions_snapshot:
            exit_info = check_exit(position, data, config)
            if exit_info:
                exit_reason, exit_price, current_value = exit_info
                trade = execute_exit(
                    position,
                    exit_reason,
                    exit_price,
                    current_value,
                    data.timestamp,
                    state,
                )

                if verbose:
                    dt = datetime.fromtimestamp(data.timestamp, tz=timezone.utc)
                    print(f"\n[EXIT {exit_reason.upper()}] Pos #{position.id} @ {dt.strftime('%H:%M:%S')}")
                    print(f"  {trade.side.upper()} | Entry: ${trade.entry_price:.4f} -> Exit: ${trade.exit_price:.4f}")
                    print(f"  PnL: ${trade.pnl:.2f} ({trade.pnl_pct*100:.1f}%)")

        # Look for new entry (cooldown is checked in evaluate_opportunity)
        opp = evaluate_opportunity(data, config, state)
        if opp:
            position = execute_entry(opp, config, state)

            if verbose and position:
                dt = datetime.fromtimestamp(data.timestamp, tz=timezone.utc)
                h1_str = f" | 1h: {opp['yes_mid_1h']*100:.0f}%" if opp.get('yes_mid_1h') else ""
                pos_count = f" | Open: {state.open_position_count}"
                print(f"\n[ENTRY] Pos #{position.id} @ {dt.strftime('%H:%M:%S')} | {data.m15_market_id}")
                print(f"  Signal: {opp['signal']} | Mispricing: {opp.get('mispricing', 0)*100:.1f}%{h1_str}{pos_count}")
                print(f"  {position.side.upper()} @ ${position.entry_price:.4f}")
                print(f"  Shares: {position.size_shares:.2f} | Cost: ${position.cost_usd:.2f}")

    # Force close all remaining positions
    if state.positions and market_data:
        last_data = market_data[-1]
        positions_to_close = list(state.positions)  # Copy list

        if verbose and positions_to_close:
            print(f"\n[BACKTEST END] Force closing {len(positions_to_close)} position(s)")

        for position in positions_to_close:
            if last_data.m15_prices:
                if position.side == "yes":
                    exit_price = last_data.m15_prices.get("yes_bid") or position.entry_price
                else:
                    exit_price = last_data.m15_prices.get("no_bid") or position.entry_price

                exit_price_with_slippage = exit_price * (1 - config.slippage_pct)
                gross_value = position.size_shares * exit_price_with_slippage
                current_value = gross_value * (1 - config.tx_fee_pct)
            else:
                exit_price_with_slippage = position.entry_price
                current_value = position.cost_usd

            trade = execute_exit(
                position,
                "backtest_end",
                exit_price_with_slippage,
                current_value,
                last_data.timestamp,
                state,
            )

            if verbose:
                print(f"  Pos #{position.id}: PnL ${trade.pnl:.2f} ({trade.pnl_pct*100:.1f}%)")

    # Always print results summary
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"Final Capital: ${state.capital:.2f}")
    print(f"Total PnL: ${state.total_pnl:.2f} ({state.total_pnl/config.initial_capital*100:.1f}%)")
    print(f"Trades: {len(state.trades)} (Win: {state.winning_trades}, Loss: {state.losing_trades})")
    print(f"Win Rate: {state.win_rate*100:.1f}%")
    print("=" * 70)

    return state


# ============================================================================
# Data Loading
# ============================================================================

def load_market_data(
    asset: Asset,
    start_ts: float,
    end_ts: float,
    include_1h: bool = True,
) -> list[MarketData]:
    """
    Load market data from Bigtable.

    Args:
        asset: Asset to load (BTC or ETH)
        start_ts: Start timestamp
        end_ts: End timestamp
        include_1h: Also load 1h data if available

    Returns:
        List of MarketData sorted by timestamp
    """
    writer = BigtableWriter()

    tables = ASSET_TABLES.get(asset, {})
    table_15m = tables.get(MarketHorizon.M15)
    table_1h = tables.get(MarketHorizon.H1)

    if not table_15m:
        print(f"No 15m table for {asset.value}")
        return []

    # Load 15m snapshots
    snapshots_15m = writer.get_snapshots(
        start_ts=start_ts,
        end_ts=end_ts,
        table_name=table_15m,
        limit=50000,
    )
    print(f"Loaded {len(snapshots_15m)} 15m snapshots from {table_15m}")

    # Load 1h snapshots if requested
    snapshots_1h = []
    if include_1h and table_1h:
        snapshots_1h = writer.get_snapshots(
            start_ts=start_ts,
            end_ts=end_ts,
            table_name=table_1h,
            limit=50000,
        )
        print(f"Loaded {len(snapshots_1h)} 1h snapshots from {table_1h}")

    # Index 1h snapshots by approximate timestamp (within 30 seconds)
    h1_by_ts = {}
    for snap in snapshots_1h:
        ts = snap.get("ts", 0)
        # Round to nearest minute for matching
        ts_key = int(ts // 60) * 60
        h1_by_ts[ts_key] = snap

    # Build MarketData list
    market_data = []
    for snap in snapshots_15m:
        ts = snap.get("ts", 0)
        market_id = snap.get("market_id", "")
        price = snap.get("spot_price", 0)
        orderbook_json = snap.get("orderbook")

        orderbook = parse_orderbook_json(orderbook_json)
        prices = get_best_prices(orderbook)

        # Find matching 1h snapshot
        ts_key = int(ts // 60) * 60
        h1_snap = h1_by_ts.get(ts_key)
        h1_orderbook = None
        h1_prices = None
        h1_market_id = None

        if h1_snap:
            h1_market_id = h1_snap.get("market_id")
            h1_orderbook = parse_orderbook_json(h1_snap.get("orderbook"))
            h1_prices = get_best_prices(h1_orderbook)

        data = MarketData(
            timestamp=ts,
            asset=asset,
            asset_price=price,
            m15_market_id=market_id,
            m15_orderbook=orderbook,
            m15_prices=prices,
            h1_market_id=h1_market_id,
            h1_orderbook=h1_orderbook,
            h1_prices=h1_prices,
        )
        market_data.append(data)

    # Sort by timestamp
    market_data.sort(key=lambda x: x.timestamp)

    return market_data


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Time-Scale Consistency Trader (Multi-Trade)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -t 12 -q              # 12 hours, quiet mode
  %(prog)s -a eth -t 24          # ETH, 24 hours
  %(prog)s -c 1000 -b 50 -t 12   # $1000 capital, $50 bets, 12 hours
""")
    parser.add_argument("-a", "--asset", type=str, default="btc", choices=["btc", "eth"],
                        help="Asset to trade (default: btc)")
    parser.add_argument("-t", "--hours-ago", type=float, default=6.0,
                        help="Hours of history to backtest (default: 6)")
    parser.add_argument("-c", "--capital", type=float, default=100.0,
                        help="Initial capital in USD (default: 100)")
    parser.add_argument("-b", "--bet-size", type=float, default=10.0,
                        help="Bet size per trade in USD (default: 10)")
    parser.add_argument("-p", "--profit-target", type=float, default=0.25,
                        help="Profit target ratio, 0.25 = 25%% (default: 0.25)")
    parser.add_argument("-m", "--min-mispricing", type=float, default=0.05,
                        help="Minimum mispricing to trade (default: 0.05)")
    parser.add_argument("-i", "--trade-interval", type=float, default=60.0,
                        help="Seconds between trades (default: 60)")
    parser.add_argument("--include-1h", action="store_true", default=True,
                        help="Load 1h data alongside 15m")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress trade-by-trade output")

    args = parser.parse_args()

    asset = Asset.BTC if args.asset.lower() == "btc" else Asset.ETH

    config = TradingConfig(
        asset=asset,
        initial_capital=args.capital,
        bet_size=args.bet_size,
        profit_target_pct=args.profit_target,
        min_mispricing=args.min_mispricing,
        trade_interval_sec=args.trade_interval,
    )

    now = time.time()
    start_ts = now - (args.hours_ago * 3600)

    print(f"Loading {asset.value.upper()} data from {args.hours_ago} hours ago...")
    print(f"Start: {datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"End: {datetime.fromtimestamp(now, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

    market_data = load_market_data(asset, start_ts, now, include_1h=args.include_1h)

    if not market_data:
        print("No data found!")
        return

    state = run_backtest(market_data, config, verbose=not args.quiet)

    return state


if __name__ == "__main__":
    main()
