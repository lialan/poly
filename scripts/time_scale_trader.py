#!/usr/bin/env python3
"""
Time-Scale Consistency Trader

Implements the 15min vs 1h market consistency model from
implementation_guide_time_scale_consistency.md.

Uses Bigtable historical data for backtesting.
"""

import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scipy.stats import norm  # For Gaussian CDF and inverse CDF

# ============================================================================
# Configuration
# ============================================================================

@dataclass
class TradingConfig:
    """Trading configuration parameters."""

    # Capital management
    initial_capital: float = 100.0  # Starting capital in USD
    bet_size: float = 10.0  # Fixed bet size per trade

    # Profit taking
    profit_target_pct: float = 0.25  # Take profit at 25% gain

    # Mispricing thresholds
    min_mispricing: float = 0.05  # Minimum mispricing to consider (5%)
    max_mispricing: float = 0.50  # Maximum (likely data error)

    # Order book depth requirements
    min_depth_usd: float = 50.0  # Minimum depth in USD to trade

    # Time constraints
    min_time_remaining_sec: float = 60.0  # Don't enter with < 1 min left

    # Transaction costs
    slippage_pct: float = 0.01  # 1% slippage
    tx_fee_pct: float = 0.01  # 1% transaction fee

    # Safety
    epsilon: float = 0.001  # Numerical safety margin for probabilities


# ============================================================================
# Probability Mapping Functions (from implementation guide)
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
    # Clamp probability away from 0 and 1
    p_short = max(epsilon, min(1 - epsilon, p_short))

    # Convert probability to z-score: z = Φ⁻¹(p_short)
    z = norm.ppf(p_short)

    # Scale by time horizon: z_long = sqrt(T) * z
    z_long = math.sqrt(T) * z

    # Convert back to probability: p_long = Φ(z_long)
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

    Position matters:
    - k=1: First 15min of the hour (4 intervals remain, weak signal)
    - k=4: Last 15min of the hour (1 interval remains, strong signal)

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

    # Remaining intervals determines effective time horizon
    # k=1 -> 4 remain, k=4 -> 1 remains
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

    mispricing = p_1h_market - p_1h_model

    - > 0: 1h market is more bullish than model implies (SHORT 1h or LONG 15m)
    - < 0: 1h market is more bearish than model implies (LONG 1h or SHORT 15m)

    Args:
        p_15: 15min market probability
        p_1h: 1h market probability
        k: Position index
        N: Total intervals
        epsilon: Numerical safety

    Returns:
        Signed mispricing value
    """
    p_1h_model = implied_1h_prob_from_15m(p_15, k, N, epsilon)
    return p_1h - p_1h_model


def get_position_in_hour(timestamp: float) -> int:
    """
    Get which 15-minute slot we're in within the hour (1-4).

    Args:
        timestamp: Unix timestamp

    Returns:
        Position k (1, 2, 3, or 4)
    """
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
# Order Book Analysis
# ============================================================================

def parse_depth_json(depth_json: Optional[str]) -> dict:
    """Parse depth JSON from Bigtable snapshot."""
    if not depth_json:
        return {"yes_bids": [], "yes_asks": [], "no_bids": [], "no_asks": []}
    try:
        return json.loads(depth_json)
    except json.JSONDecodeError:
        return {"yes_bids": [], "yes_asks": [], "no_bids": [], "no_asks": []}


def calculate_available_liquidity(
    depth: dict,
    side: str,  # "yes" or "no"
    direction: str,  # "buy" or "sell"
    max_price_impact: float = 0.02  # 2% max slippage
) -> tuple[float, float]:
    """
    Calculate available liquidity within price impact tolerance.

    Args:
        depth: Parsed depth dict
        side: "yes" or "no" token
        direction: "buy" or "sell"
        max_price_impact: Maximum acceptable price slippage

    Returns:
        Tuple of (available_size_usd, avg_price)
    """
    if direction == "buy":
        # Buying means lifting asks
        levels = depth.get(f"{side}_asks", [])
        if not levels:
            return 0.0, 0.0

        # Best ask is the lowest price (last element after sorting)
        levels_sorted = sorted(levels, key=lambda x: x[0])
        best_price = levels_sorted[0][0] if levels_sorted else 0
        max_price = best_price * (1 + max_price_impact)

    else:  # sell
        # Selling means hitting bids
        levels = depth.get(f"{side}_bids", [])
        if not levels:
            return 0.0, 0.0

        # Best bid is the highest price
        levels_sorted = sorted(levels, key=lambda x: x[0], reverse=True)
        best_price = levels_sorted[0][0] if levels_sorted else 0
        max_price = best_price * (1 - max_price_impact)

    # Sum up liquidity within tolerance
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

    entry_time: float
    market_id: str
    side: str  # "yes" or "no"
    size_shares: float
    entry_price: float
    cost_usd: float

    # Tracking
    peak_value: float = 0.0

    @property
    def current_value(self) -> float:
        return self.size_shares * self.entry_price  # Will be updated with mark price


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
    exit_reason: str  # "profit_target", "market_close", "stop_loss"


@dataclass
class TradingState:
    """Current trading state."""

    capital: float
    position: Optional[Position] = None
    trades: list[Trade] = field(default_factory=list)

    # Metrics
    total_pnl: float = 0.0
    winning_trades: int = 0
    losing_trades: int = 0

    @property
    def win_rate(self) -> float:
        total = self.winning_trades + self.losing_trades
        return self.winning_trades / total if total > 0 else 0.0


# ============================================================================
# Trading Logic
# ============================================================================

def evaluate_opportunity(
    snapshot: dict,
    config: TradingConfig,
    state: TradingState,
) -> Optional[dict]:
    """
    Evaluate if current snapshot presents a trading opportunity.

    Args:
        snapshot: Market snapshot from Bigtable
        config: Trading configuration
        state: Current trading state

    Returns:
        Opportunity dict or None
    """
    # Skip if already in position
    if state.position is not None:
        return None

    # Skip if not enough capital
    if state.capital < config.bet_size:
        return None

    # Parse snapshot data
    ts = snapshot.get("ts", 0)
    market_id = snapshot.get("market_id", "")
    yes_bid = snapshot.get("yes_bid")
    yes_ask = snapshot.get("yes_ask")
    no_bid = snapshot.get("no_bid")
    no_ask = snapshot.get("no_ask")

    # Need valid prices
    if not all([yes_bid, yes_ask, no_bid, no_ask]):
        return None

    # Calculate mid prices (market-implied probabilities)
    yes_mid = (yes_bid + yes_ask) / 2
    no_mid = (no_bid + no_ask) / 2

    # Get position in hour
    k = get_position_in_hour(ts)

    # For now, we only have 15m markets, not 1h markets
    # So we'll use the 15m probability and look for extreme deviations
    # from the model-implied "fair" value

    # Calculate what the probability "should" be based on time remaining
    # If k=4 (last 15m), the probability should be close to 50% if BTC is flat
    # If k=1 (first 15m), there's more uncertainty

    # Simple strategy: Look for extreme probabilities that suggest mean reversion
    # High yes_mid (>0.70) in early slots -> likely to revert
    # Low yes_mid (<0.30) in early slots -> likely to revert

    # Parse depth for liquidity check
    depth = parse_depth_json(snapshot.get("depth_json"))

    opportunity = {
        "ts": ts,
        "market_id": market_id,
        "k": k,
        "yes_mid": yes_mid,
        "no_mid": no_mid,
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": no_bid,
        "no_ask": no_ask,
        "depth": depth,
        "signal": None,
        "side": None,
        "entry_price": None,
    }

    # Strategy: Bet on mean reversion when probability is extreme
    # This is a simplified approach - the full model would compare 15m vs 1h

    # Check for BUY YES opportunity (probability seems too low)
    if yes_mid < 0.35:  # Market thinks DOWN is likely
        # Check if we can buy YES
        liq_usd, avg_price = calculate_available_liquidity(depth, "yes", "buy")
        if liq_usd >= config.min_depth_usd and avg_price > 0:
            # Calculate implied mispricing assuming 50% is "fair"
            implied_mispricing = 0.50 - yes_mid
            if implied_mispricing >= config.min_mispricing:
                opportunity["signal"] = "buy_yes"
                opportunity["side"] = "yes"
                opportunity["entry_price"] = yes_ask  # Buy at ask
                opportunity["mispricing"] = implied_mispricing
                opportunity["available_liq"] = liq_usd
                return opportunity

    # Check for BUY NO opportunity (probability seems too high)
    if yes_mid > 0.65:  # Market thinks UP is likely
        # Check if we can buy NO
        liq_usd, avg_price = calculate_available_liquidity(depth, "no", "buy")
        if liq_usd >= config.min_depth_usd and avg_price > 0:
            # Calculate implied mispricing
            implied_mispricing = yes_mid - 0.50
            if implied_mispricing >= config.min_mispricing:
                opportunity["signal"] = "buy_no"
                opportunity["side"] = "no"
                opportunity["entry_price"] = no_ask  # Buy at ask
                opportunity["mispricing"] = implied_mispricing
                opportunity["available_liq"] = liq_usd
                return opportunity

    return None


def execute_entry(
    opportunity: dict,
    config: TradingConfig,
    state: TradingState,
) -> Optional[Position]:
    """
    Execute entry into a position.

    Args:
        opportunity: Opportunity from evaluate_opportunity
        config: Trading configuration
        state: Current trading state

    Returns:
        New Position or None
    """
    if opportunity is None:
        return None

    entry_price = opportunity["entry_price"]
    if entry_price <= 0:
        return None

    # Apply slippage to entry price (buying at higher price)
    entry_price_with_slippage = entry_price * (1 + config.slippage_pct)

    # Apply transaction fee to bet size
    effective_bet = config.bet_size * (1 - config.tx_fee_pct)

    # Calculate shares: effective_bet / price_with_slippage
    size_shares = effective_bet / entry_price_with_slippage

    # Create position
    position = Position(
        entry_time=opportunity["ts"],
        market_id=opportunity["market_id"],
        side=opportunity["side"],
        size_shares=size_shares,
        entry_price=entry_price_with_slippage,
        cost_usd=config.bet_size,  # Total cost including fees
    )

    # Update state
    state.capital -= config.bet_size
    state.position = position

    return position


def check_exit(
    position: Position,
    snapshot: dict,
    config: TradingConfig,
) -> Optional[tuple[str, float, float]]:
    """
    Check if position should be exited.

    Args:
        position: Current position
        snapshot: Current market snapshot
        config: Trading configuration

    Returns:
        Tuple of (exit_reason, exit_price, current_value) or None
    """
    ts = snapshot.get("ts", 0)
    market_id = snapshot.get("market_id", "")

    # Get current prices for our side
    if position.side == "yes":
        bid = snapshot.get("yes_bid")
        ask = snapshot.get("yes_ask")
    else:
        bid = snapshot.get("no_bid")
        ask = snapshot.get("no_ask")

    if not bid or not ask:
        return None

    # Apply slippage to exit price (selling at lower price)
    exit_price_with_slippage = bid * (1 - config.slippage_pct)

    # Apply transaction fee to proceeds
    gross_value = position.size_shares * exit_price_with_slippage
    current_value = gross_value * (1 - config.tx_fee_pct)

    pnl_pct = (current_value - position.cost_usd) / position.cost_usd

    # Check profit target
    if pnl_pct >= config.profit_target_pct:
        return ("profit_target", exit_price_with_slippage, current_value)

    # Check if market is about to close (different market_id)
    if market_id != position.market_id:
        # Market changed, force exit at last known price
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
    """
    Execute exit from a position.

    Args:
        position: Position to close
        exit_reason: Reason for exit
        exit_price: Exit price
        current_value: Current position value
        exit_time: Exit timestamp
        state: Trading state

    Returns:
        Completed Trade
    """
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

    # Update state
    state.capital += current_value
    state.total_pnl += pnl
    state.trades.append(trade)
    state.position = None

    if pnl > 0:
        state.winning_trades += 1
    else:
        state.losing_trades += 1

    return trade


# ============================================================================
# Backtester
# ============================================================================

def run_backtest(
    snapshots: list[dict],
    config: TradingConfig,
    verbose: bool = True,
) -> TradingState:
    """
    Run backtest on historical snapshots.

    Args:
        snapshots: List of snapshots sorted by timestamp
        config: Trading configuration
        verbose: Print trade details

    Returns:
        Final TradingState
    """
    state = TradingState(capital=config.initial_capital)

    if verbose:
        print("=" * 70)
        print("BACKTEST STARTING")
        print("=" * 70)
        print(f"Initial Capital: ${config.initial_capital:.2f}")
        print(f"Bet Size: ${config.bet_size:.2f}")
        print(f"Profit Target: {config.profit_target_pct * 100:.1f}%")
        print(f"Min Mispricing: {config.min_mispricing * 100:.1f}%")
        print(f"Slippage: {config.slippage_pct * 100:.1f}%")
        print(f"TX Fee: {config.tx_fee_pct * 100:.1f}%")
        print(f"Snapshots: {len(snapshots)}")
        print("=" * 70)

    last_market_id = None

    for snapshot in snapshots:
        ts = snapshot.get("ts", 0)
        market_id = snapshot.get("market_id", "")

        # Check for market change (force close position)
        if state.position and market_id != state.position.market_id:
            if verbose:
                print(f"\n[MARKET CHANGE] {state.position.market_id} -> {market_id}")

            # Get last snapshot's prices for the old market
            if state.position.side == "yes":
                exit_price = snapshot.get("yes_bid", state.position.entry_price)
            else:
                exit_price = snapshot.get("no_bid", state.position.entry_price)

            # Apply slippage and fees
            if exit_price:
                exit_price_with_slippage = exit_price * (1 - config.slippage_pct)
                gross_value = state.position.size_shares * exit_price_with_slippage
                current_value = gross_value * (1 - config.tx_fee_pct)
            else:
                exit_price_with_slippage = state.position.entry_price
                current_value = state.position.cost_usd

            trade = execute_exit(
                state.position,
                "market_close",
                exit_price_with_slippage,
                current_value,
                ts,
                state,
            )

            if verbose:
                print(f"  Exit: ${trade.proceeds_usd:.2f} | PnL: ${trade.pnl:.2f} ({trade.pnl_pct*100:.1f}%)")

        # If in position, check for exit
        if state.position:
            exit_info = check_exit(state.position, snapshot, config)
            if exit_info:
                exit_reason, exit_price, current_value = exit_info
                trade = execute_exit(
                    state.position,
                    exit_reason,
                    exit_price,
                    current_value,
                    ts,
                    state,
                )

                if verbose:
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    print(f"\n[EXIT {exit_reason.upper()}] {dt.strftime('%H:%M:%S')}")
                    print(f"  {trade.side.upper()} | Entry: ${trade.entry_price:.4f} -> Exit: ${trade.exit_price:.4f}")
                    print(f"  PnL: ${trade.pnl:.2f} ({trade.pnl_pct*100:.1f}%)")
                    print(f"  Capital: ${state.capital:.2f}")

        # If no position, look for entry
        if state.position is None:
            opp = evaluate_opportunity(snapshot, config, state)
            if opp:
                position = execute_entry(opp, config, state)

                if verbose and position:
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    print(f"\n[ENTRY] {dt.strftime('%H:%M:%S')} | {market_id}")
                    print(f"  Signal: {opp['signal']} | Mispricing: {opp.get('mispricing', 0)*100:.1f}%")
                    print(f"  {position.side.upper()} @ ${position.entry_price:.4f}")
                    print(f"  Shares: {position.size_shares:.2f} | Cost: ${position.cost_usd:.2f}")
                    print(f"  Available Liq: ${opp.get('available_liq', 0):.2f}")

        last_market_id = market_id

    # Force close any remaining position
    if state.position:
        # Use last snapshot prices
        last_snapshot = snapshots[-1] if snapshots else {}
        if state.position.side == "yes":
            exit_price = last_snapshot.get("yes_bid", state.position.entry_price)
        else:
            exit_price = last_snapshot.get("no_bid", state.position.entry_price)

        # Apply slippage and fees
        if exit_price:
            exit_price_with_slippage = exit_price * (1 - config.slippage_pct)
            gross_value = state.position.size_shares * exit_price_with_slippage
            current_value = gross_value * (1 - config.tx_fee_pct)
        else:
            exit_price_with_slippage = state.position.entry_price
            current_value = state.position.cost_usd

        trade = execute_exit(
            state.position,
            "backtest_end",
            exit_price_with_slippage,
            current_value,
            last_snapshot.get("ts", 0),
            state,
        )

        if verbose:
            print(f"\n[BACKTEST END] Force close")
            print(f"  PnL: ${trade.pnl:.2f} ({trade.pnl_pct*100:.1f}%)")

    if verbose:
        print("\n" + "=" * 70)
        print("BACKTEST COMPLETE")
        print("=" * 70)
        print(f"Final Capital: ${state.capital:.2f}")
        print(f"Total PnL: ${state.total_pnl:.2f} ({state.total_pnl/config.initial_capital*100:.1f}%)")
        print(f"Trades: {len(state.trades)} (Win: {state.winning_trades}, Loss: {state.losing_trades})")
        print(f"Win Rate: {state.win_rate*100:.1f}%")
        print("=" * 70)

        if state.trades:
            print("\nTrade Summary:")
            for i, trade in enumerate(state.trades):
                dt_entry = datetime.fromtimestamp(trade.entry_time, tz=timezone.utc)
                dt_exit = datetime.fromtimestamp(trade.exit_time, tz=timezone.utc)
                print(f"  {i+1}. {dt_entry.strftime('%H:%M')} -> {dt_exit.strftime('%H:%M')} | "
                      f"{trade.side.upper()} | PnL: ${trade.pnl:.2f} ({trade.pnl_pct*100:.1f}%) | {trade.exit_reason}")

    return state


# ============================================================================
# Data Loading
# ============================================================================

def load_snapshots_from_bigtable(
    start_ts: float,
    end_ts: Optional[float] = None,
    limit: int = 10000,
) -> list[dict]:
    """
    Load snapshots from Bigtable.

    Args:
        start_ts: Start timestamp
        end_ts: End timestamp (default: now)
        limit: Maximum snapshots to load

    Returns:
        List of snapshots sorted by timestamp
    """
    # Direct import to avoid loading full poly package
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bigtable_writer",
        Path(__file__).parent.parent / "src" / "poly" / "bigtable_writer.py"
    )
    bt_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bt_module)
    BigtableWriter = bt_module.BigtableWriter

    if end_ts is None:
        import time
        end_ts = time.time()

    writer = BigtableWriter()
    snapshots = writer.get_snapshots(start_ts=start_ts, end_ts=end_ts, limit=limit)

    # Sort by timestamp (oldest first for chronological backtest)
    snapshots.sort(key=lambda x: x.get("ts", 0))

    return snapshots


# ============================================================================
# Main
# ============================================================================

def main():
    import argparse
    import time

    parser = argparse.ArgumentParser(description="Time-Scale Consistency Trader Backtest")
    parser.add_argument("--hours-ago", type=float, default=6.0, help="Start backtest N hours ago")
    parser.add_argument("--capital", type=float, default=100.0, help="Initial capital")
    parser.add_argument("--bet-size", type=float, default=10.0, help="Bet size per trade")
    parser.add_argument("--profit-target", type=float, default=0.25, help="Profit target (0.25 = 25%%)")
    parser.add_argument("--min-mispricing", type=float, default=0.05, help="Minimum mispricing to trade")
    parser.add_argument("--verbose", action="store_true", default=True, help="Print detailed output")

    args = parser.parse_args()

    # Configure
    config = TradingConfig(
        initial_capital=args.capital,
        bet_size=args.bet_size,
        profit_target_pct=args.profit_target,
        min_mispricing=args.min_mispricing,
    )

    # Calculate time range
    now = time.time()
    start_ts = now - (args.hours_ago * 3600)

    print(f"Loading data from {args.hours_ago} hours ago...")
    print(f"Start: {datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"End: {datetime.fromtimestamp(now, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

    # Load data
    snapshots = load_snapshots_from_bigtable(start_ts, now)
    print(f"Loaded {len(snapshots)} snapshots")

    if not snapshots:
        print("No data found!")
        return

    # Run backtest
    state = run_backtest(snapshots, config, verbose=args.verbose)

    return state


if __name__ == "__main__":
    main()
