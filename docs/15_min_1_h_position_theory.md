# 15-Minute and 1-Hour Position Theory

## Overview

This document describes the theoretical framework for combining 15-minute and 1-hour prediction market signals to inform trading decisions. The approach uses multi-timescale analysis where shorter-term markets provide entry/exit timing while longer-term markets provide directional bias.

## Market Structure

### Time Horizons

| Horizon | Duration | Resolution | Use Case |
|---------|----------|------------|----------|
| 15m | 15 minutes | Every 15 min | Entry/exit timing, momentum |
| 1h | 1 hour | Every hour | Directional bias, trend |

### Data Points (5-second intervals)

- **15m market**: ~180 snapshots per market window
- **1h market**: ~720 snapshots per market window
- **Overlap**: 4 complete 15m markets fit within each 1h market

## Mathematical Framework

### Simulation Configuration

```python
import numpy as np
from dataclasses import dataclass
from typing import Optional

@dataclass
class SimulationConfig:
    """Configuration for position simulation.

    Default values are non-biased (no directional preference).
    """
    # Time parameters
    step_seconds: float = 5.0          # Simulation step size

    # Position limits
    max_position: float = 1.0          # Maximum position size (normalized)
    min_position: float = -1.0         # Minimum position size (normalized)

    # Signal thresholds (symmetric around 0.5)
    entry_threshold: float = 0.0       # No threshold bias
    exit_threshold: float = 0.0        # No threshold bias

    # Weighting (equal weight = non-biased)
    weight_15m: float = 0.5            # Weight for 15m signal
    weight_1h: float = 0.5             # Weight for 1h signal

    # Transaction costs
    fee_rate: float = 0.0              # No fees in default simulation
    slippage_bps: float = 0.0          # No slippage in default simulation

    # Risk parameters
    stop_loss: Optional[float] = None  # No stop loss by default
    take_profit: Optional[float] = None  # No take profit by default

    def __post_init__(self):
        assert abs(self.weight_15m + self.weight_1h - 1.0) < 1e-9, "Weights must sum to 1.0"
        assert self.max_position >= self.min_position, "Invalid position limits"
```

### Signal Extraction

The mid-price of the YES token represents the market's implied probability:

```python
def extract_signal(yes_bid: float, yes_ask: float) -> float:
    """Extract probability signal from orderbook.

    Args:
        yes_bid: Best bid for YES token (0-1)
        yes_ask: Best ask for YES token (0-1)

    Returns:
        Mid-price as probability estimate (0-1)
    """
    if yes_bid is None or yes_ask is None:
        return 0.5  # No signal = neutral
    return (yes_bid + yes_ask) / 2.0
```

### Multi-Timescale Signal Combination

```python
def combine_signals(
    signal_15m: float,
    signal_1h: float,
    config: SimulationConfig,
) -> float:
    """Combine signals from different time horizons.

    Args:
        signal_15m: 15-minute market probability (0-1)
        signal_1h: 1-hour market probability (0-1)
        config: Simulation configuration

    Returns:
        Combined signal (-1 to 1), where:
          - Positive = bullish (price will go up)
          - Negative = bearish (price will go down)
          - Zero = neutral
    """
    # Convert probabilities to centered signals (-0.5 to 0.5)
    centered_15m = signal_15m - 0.5
    centered_1h = signal_1h - 0.5

    # Weighted combination
    combined = (
        config.weight_15m * centered_15m +
        config.weight_1h * centered_1h
    )

    # Scale to (-1, 1) range
    return np.clip(combined * 2.0, -1.0, 1.0)
```

## Position Sizing

### Signal-to-Position Mapping

```python
def signal_to_position(
    signal: float,
    config: SimulationConfig,
) -> float:
    """Convert combined signal to target position.

    Args:
        signal: Combined signal (-1 to 1)
        config: Simulation configuration

    Returns:
        Target position (min_position to max_position)
    """
    # Apply entry threshold (dead zone around zero)
    if abs(signal) < config.entry_threshold:
        return 0.0

    # Linear mapping from signal to position
    if signal > 0:
        position = signal * config.max_position
    else:
        position = signal * abs(config.min_position)

    return np.clip(position, config.min_position, config.max_position)
```

### Position Update with Constraints

```python
def update_position(
    current_position: float,
    target_position: float,
    config: SimulationConfig,
) -> tuple[float, float]:
    """Update position towards target with transaction costs.

    Args:
        current_position: Current position
        target_position: Target position from signal
        config: Simulation configuration

    Returns:
        (new_position, transaction_cost)
    """
    delta = target_position - current_position

    # Apply exit threshold (don't close small positions)
    if abs(target_position) < config.exit_threshold and abs(delta) < abs(current_position):
        return current_position, 0.0

    # Calculate transaction cost
    cost = abs(delta) * (config.fee_rate + config.slippage_bps / 10000)

    return target_position, cost
```

## Simulation Engine

### State Representation

```python
@dataclass
class SimulationState:
    """State at each simulation step."""
    timestamp: float
    spot_price: float
    signal_15m: float
    signal_1h: float
    combined_signal: float
    position: float
    pnl: float
    cumulative_cost: float
```

### Step Function

```python
def simulation_step(
    prev_state: SimulationState,
    snapshot_15m: dict,
    snapshot_1h: dict,
    config: SimulationConfig,
) -> SimulationState:
    """Execute one simulation step.

    Args:
        prev_state: Previous state
        snapshot_15m: Current 15m market snapshot
        snapshot_1h: Current 1h market snapshot
        config: Simulation configuration

    Returns:
        New simulation state
    """
    # Extract current signals
    signal_15m = extract_signal(
        snapshot_15m.get('yes_bid'),
        snapshot_15m.get('yes_ask'),
    )
    signal_1h = extract_signal(
        snapshot_1h.get('yes_bid'),
        snapshot_1h.get('yes_ask'),
    )

    # Combine signals
    combined = combine_signals(signal_15m, signal_1h, config)

    # Calculate target position
    target_position = signal_to_position(combined, config)

    # Update position
    new_position, cost = update_position(
        prev_state.position,
        target_position,
        config,
    )

    # Calculate PnL from price movement
    spot_price = snapshot_15m.get('spot_price', prev_state.spot_price)
    price_change = spot_price - prev_state.spot_price
    step_pnl = prev_state.position * price_change - cost

    return SimulationState(
        timestamp=snapshot_15m['timestamp'],
        spot_price=spot_price,
        signal_15m=signal_15m,
        signal_1h=signal_1h,
        combined_signal=combined,
        position=new_position,
        pnl=prev_state.pnl + step_pnl,
        cumulative_cost=prev_state.cumulative_cost + cost,
    )
```

## Signal Alignment

### Temporal Matching

When combining signals, snapshots must be aligned by timestamp:

```python
def align_snapshots(
    snapshots_15m: list[dict],
    snapshots_1h: list[dict],
    step_seconds: float = 5.0,
) -> list[tuple[dict, dict]]:
    """Align 15m and 1h snapshots by timestamp.

    For each 15m snapshot, find the most recent 1h snapshot
    with timestamp <= 15m timestamp.

    Args:
        snapshots_15m: List of 15m snapshots (sorted by timestamp)
        snapshots_1h: List of 1h snapshots (sorted by timestamp)
        step_seconds: Expected step size

    Returns:
        List of (snapshot_15m, snapshot_1h) pairs
    """
    aligned = []
    h1_idx = 0

    for snap_15m in snapshots_15m:
        ts = snap_15m['timestamp']

        # Advance 1h index to most recent snapshot before this timestamp
        while (h1_idx + 1 < len(snapshots_1h) and
               snapshots_1h[h1_idx + 1]['timestamp'] <= ts):
            h1_idx += 1

        if h1_idx < len(snapshots_1h):
            aligned.append((snap_15m, snapshots_1h[h1_idx]))

    return aligned
```

## Theoretical Properties

### Non-Bias Conditions

The default `SimulationConfig` satisfies non-bias conditions:

1. **Symmetric weights**: `weight_15m = weight_1h = 0.5`
2. **Zero thresholds**: No directional preference in entry/exit
3. **Symmetric position limits**: `max_position = -min_position`
4. **Zero friction**: No fees or slippage that could favor one direction

### Expected Value Under Null Hypothesis

Under the null hypothesis (markets are efficient):

```
E[combined_signal] = 0
E[position] = 0
E[PnL] = -cumulative_cost (transaction costs only)
```

### Signal Interpretation

| Combined Signal | Interpretation |
|-----------------|----------------|
| +1.0 | Strong bullish (both horizons agree, high confidence) |
| +0.5 | Moderate bullish (one horizon bullish, one neutral) |
| 0.0 | Neutral (no signal or conflicting signals) |
| -0.5 | Moderate bearish (one horizon bearish, one neutral) |
| -1.0 | Strong bearish (both horizons agree, high confidence) |

## Simulation Metrics

### Performance Metrics

```python
def calculate_metrics(states: list[SimulationState]) -> dict:
    """Calculate performance metrics from simulation states.

    Args:
        states: List of simulation states

    Returns:
        Dictionary of metrics
    """
    pnls = np.array([s.pnl for s in states])
    positions = np.array([s.position for s in states])

    # Returns
    final_pnl = pnls[-1] if len(pnls) > 0 else 0.0

    # Risk metrics
    max_drawdown = np.min(pnls - np.maximum.accumulate(pnls))

    # Position metrics
    avg_position = np.mean(np.abs(positions))
    position_changes = np.sum(np.abs(np.diff(positions)))

    # Sharpe-like ratio (using 5-second returns)
    returns = np.diff(pnls)
    sharpe = np.mean(returns) / (np.std(returns) + 1e-10) * np.sqrt(720)  # Annualized to 1h

    return {
        'final_pnl': final_pnl,
        'max_drawdown': max_drawdown,
        'avg_position': avg_position,
        'total_turnover': position_changes,
        'sharpe_ratio': sharpe,
        'num_steps': len(states),
        'total_cost': states[-1].cumulative_cost if states else 0.0,
    }
```

## Position Effect Theory

### Problem Setting

Consider a 1-hour window `[t, t+60]` divided into 4 consecutive 15-minute intervals:

```
Δ₁₅⁽ⁱ⁾ = X_{t+15i} - X_{t+15(i-1)}, for i = 1,2,3,4
```

Define events:
- `Bᵢ`: The i-th 15min is "up" (Δ₁₅⁽ⁱ⁾ > 0)
- `A`: The 1h is "up" (Σᵢ Δ₁₅⁽ⁱ⁾ > 0)

### Information Structure

| 15min Position | Time Interval | Information Known at Order Time |
|----------------|---------------|--------------------------------|
| 1st | [t, t+15] | Only Xₜ |
| 2nd | [t+15, t+30] | 1st result known |
| 3rd | [t+30, t+45] | 1st and 2nd results known |
| 4th | [t+45, t+60] | 1st, 2nd, 3rd results known |

### Key Insight: Information Monotonicity

The conditional probability spaces are strictly different σ-algebras:

```
P(A | ℱ_{t+15}), P(A | ℱ_{t+30}), P(A | ℱ_{t+45})
```

**Theorem (Position Effect)**: Under unconditional probability, B₁,...,B₄ are equivalent. But in real prediction markets, Bᵢ belongs to different information σ-algebras, and the constraint strength on A increases monotonically with i.

### Alpha Implications

| Position | Information Value | Trading Implication |
|----------|-------------------|---------------------|
| 1st 15m | Low | Noise trading, mean reversion |
| 2nd 15m | Medium-Low | Early trend detection |
| 3rd 15m | Medium-High | Trend confirmation |
| 4th 15m | High | Near-arbitrage opportunity |

The 4th 15-minute interval provides the strongest constraint on the 1-hour outcome - if the first 3 intervals have already moved significantly, the 4th interval's market price should reflect this, creating potential alpha from information asymmetry.

## Usage Example

```python
import numpy as np

# Create non-biased configuration
config = SimulationConfig()

# Load data (from Bigtable)
snapshots_15m = load_snapshots('btc_15m_snapshot', start_ts, end_ts)
snapshots_1h = load_snapshots('btc_1h_snapshot', start_ts, end_ts)

# Align by timestamp
aligned = align_snapshots(snapshots_15m, snapshots_1h, config.step_seconds)

# Initialize state
initial_state = SimulationState(
    timestamp=aligned[0][0]['timestamp'],
    spot_price=aligned[0][0]['spot_price'],
    signal_15m=0.5,
    signal_1h=0.5,
    combined_signal=0.0,
    position=0.0,
    pnl=0.0,
    cumulative_cost=0.0,
)

# Run simulation
states = [initial_state]
for snap_15m, snap_1h in aligned[1:]:
    new_state = simulation_step(states[-1], snap_15m, snap_1h, config)
    states.append(new_state)

# Calculate metrics
metrics = calculate_metrics(states)
print(f"Final PnL: {metrics['final_pnl']:.2f}")
print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
print(f"Max Drawdown: {metrics['max_drawdown']:.2f}")
```

## Appendix: Time Constants

```python
# Step size
STEP_SECONDS = 5.0

# Market durations
MARKET_15M_SECONDS = 15 * 60  # 900 seconds
MARKET_1H_SECONDS = 60 * 60   # 3600 seconds

# Snapshots per market window
SNAPSHOTS_PER_15M = int(MARKET_15M_SECONDS / STEP_SECONDS)  # 180
SNAPSHOTS_PER_1H = int(MARKET_1H_SECONDS / STEP_SECONDS)    # 720

# 15m markets per 1h market
MARKETS_15M_PER_1H = int(MARKET_1H_SECONDS / MARKET_15M_SECONDS)  # 4
```
