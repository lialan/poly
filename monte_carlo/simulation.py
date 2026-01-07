"""
Event Statistics Simulator

A pure event statistics engine to validate the theoretical claim:
P(1h up | 15min_N up) is monotonically increasing in N = 1,2,3,4.

This simulator removes all trading logic (PnL, positions, costs) and
focuses only on event probabilities via Monte Carlo simulation.
"""

import numpy as np
from dataclasses import dataclass
from typing import Optional


@dataclass
class SimulationConfig:
    """Configuration for event statistics simulation.

    Attributes:
        n_paths: Number of Monte Carlo paths
        mu: Drift per hour (set to 0 for pure symmetry test)
        sigma: Volatility per sqrt(hour)
        seed: RNG seed for reproducibility
    """
    n_paths: int = 1_000_000
    mu: float = 0.0           # Drift per hour
    sigma: float = 0.05       # Volatility per sqrt(hour)
    seed: Optional[int] = None


@dataclass
class SimulationResult:
    """Results from event statistics simulation.

    Attributes:
        config: The configuration used
        returns: Raw returns array of shape (n_paths, 4)
        probs: Dict mapping segment N (1-4) to P(1h up | N-th 15min up)
        unconditional_prob: P(1h up) unconditionally
        is_monotonic: Whether probabilities are monotonically increasing
        differences: List of probability differences [P2-P1, P3-P2, P4-P3]
        uncertainty_analysis: Dict with remaining uncertainty analysis per segment
    """
    config: SimulationConfig
    returns: np.ndarray
    probs: dict[int, float]
    unconditional_prob: float
    is_monotonic: bool
    differences: list[float]
    uncertainty_analysis: dict[int, dict]


def simulate_paths(config: SimulationConfig) -> np.ndarray:
    """Generate Monte Carlo log-return paths.

    Uses the model:
        log S_{t+dt} = log S_t + mu*dt + sigma*sqrt(dt)*Z
    where Z ~ N(0,1)

    Each path has 4 segments (15min each = 1 hour total).
    Time unit: 1 hour, so each segment is dt = 0.25 hours.

    Args:
        config: Simulation configuration

    Returns:
        returns: np.ndarray of shape (n_paths, 4)
                 returns[i, j] = log return of path i during 15min segment j
    """
    if config.seed is not None:
        np.random.seed(config.seed)

    n_paths = config.n_paths
    n_segments = 4
    dt = 0.25  # 15 minutes = 0.25 hours

    # Generate standard normal innovations
    Z = np.random.standard_normal((n_paths, n_segments))

    # Compute log returns for each segment
    # return = mu * dt + sigma * sqrt(dt) * Z
    returns = config.mu * dt + config.sigma * np.sqrt(dt) * Z

    return returns


def conditional_prob_1h_up_given_15min_up(
    returns: np.ndarray,
    segment_index: int,
) -> float:
    """Estimate P(1h up | N-th 15min up).

    Args:
        returns: Array of shape (n_paths, 4) with log returns
        segment_index: 0-based index (0..3 corresponding to N=1..4)

    Returns:
        Conditional probability estimate
    """
    # 15min up: return in that segment > 0
    mask_15m_up = returns[:, segment_index] > 0

    # 1h up: sum of all returns > 0
    mask_1h_up = returns.sum(axis=1) > 0

    # Conditional probability: P(1h up | 15min up)
    # = count(1h up AND 15min up) / count(15min up)
    if mask_15m_up.sum() == 0:
        return 0.0

    p = mask_1h_up[mask_15m_up].mean()
    return float(p)


def compute_all_conditional_probs(returns: np.ndarray) -> dict[int, float]:
    """Compute P(1h up | N-th 15min up) for N = 1,2,3,4.

    Args:
        returns: Array of shape (n_paths, 4) with log returns

    Returns:
        probs: Dict mapping N (1-4) to conditional probability
    """
    probs = {}
    for segment_index in range(4):
        N = segment_index + 1  # 1-based index
        probs[N] = conditional_prob_1h_up_given_15min_up(returns, segment_index)
    return probs


def compute_unconditional_prob(returns: np.ndarray) -> float:
    """Compute P(1h up) unconditionally.

    Args:
        returns: Array of shape (n_paths, 4) with log returns

    Returns:
        Unconditional probability of 1h being up
    """
    mask_1h_up = returns.sum(axis=1) > 0
    return float(mask_1h_up.mean())


def compute_information_conditional_probs(returns: np.ndarray) -> dict[int, float]:
    """Compute P(1h up | N-th 15min up, given cumulative sum of first N-1 segments = 0).

    This tests the TRUE position effect: how much does knowing the N-th segment
    is up tell you about the 1h outcome, given that you're at a "neutral" state
    (cumulative sum = 0) before the N-th segment.

    For a cleaner theoretical interpretation:
    - At position N, you've observed segments 1..N-1
    - If their sum is ~0, you're at a "fresh start"
    - Knowing segment N is up should provide different information value
      depending on how many segments remain

    Args:
        returns: Array of shape (n_paths, 4) with log returns

    Returns:
        probs: Dict mapping N (1-4) to conditional probability
    """
    probs = {}
    n_paths = returns.shape[0]

    for N in range(1, 5):
        segment_index = N - 1

        # Segment N is up
        mask_N_up = returns[:, segment_index] > 0

        # 1h up: sum of all returns > 0
        mask_1h_up = returns.sum(axis=1) > 0

        # For N > 1, also condition on prior sum being near zero
        # (within 1 std of segment returns)
        if N > 1:
            prior_sum = returns[:, :segment_index].sum(axis=1)
            threshold = returns[:, 0].std()  # Use 1 std as threshold
            mask_neutral = np.abs(prior_sum) < threshold
            mask_combined = mask_N_up & mask_neutral
        else:
            mask_combined = mask_N_up

        if mask_combined.sum() > 0:
            probs[N] = float(mask_1h_up[mask_combined].mean())
        else:
            probs[N] = 0.5

    return probs


def compute_remaining_uncertainty_effect(returns: np.ndarray) -> dict[int, dict]:
    """Compute the position effect based on remaining uncertainty.

    This directly tests: given segment N is up, how does the remaining
    uncertainty (from segments N+1 to 4) affect the probability of 1h up?

    The key insight: when segment N is up, the 1h outcome depends on:
    - Fixed contribution from segment N (positive)
    - Unknown contribution from segments N+1..4

    As N increases, fewer unknown segments remain, so the information
    value of "segment N is up" increases.

    Returns:
        Dict with segment stats including contribution analysis
    """
    results = {}
    n_paths = returns.shape[0]

    for N in range(1, 5):
        segment_index = N - 1

        # Segment N is up
        mask_N_up = returns[:, segment_index] > 0

        # 1h up
        mask_1h_up = returns.sum(axis=1) > 0

        # Basic conditional probability
        basic_prob = float(mask_1h_up[mask_N_up].mean()) if mask_N_up.sum() > 0 else 0.5

        # Analyze when segment N is up
        segment_N_values = returns[mask_N_up, segment_index]

        # Remaining segments' contribution (if any)
        if N < 4:
            remaining_sum = returns[mask_N_up, segment_index+1:].sum(axis=1)
            remaining_std = float(remaining_sum.std())
        else:
            remaining_std = 0.0

        # How often does "segment N up" lead to "1h up"?
        # This depends on: segment_N_value + remaining_sum > 0

        results[N] = {
            'prob': basic_prob,
            'n_up': int(mask_N_up.sum()),
            'avg_segment_value': float(segment_N_values.mean()),
            'remaining_segments': 4 - N,
            'remaining_std': remaining_std,
        }

    return results


def verify_monotonicity(probs: dict[int, float]) -> bool:
    """Check whether probabilities are monotonically increasing.

    Args:
        probs: Dict mapping N (1-4) to probability

    Returns:
        True if P1 <= P2 <= P3 <= P4
    """
    values = [probs[N] for N in sorted(probs.keys())]
    return all(values[i] <= values[i + 1] for i in range(len(values) - 1))


def monotonic_differences(probs: dict[int, float]) -> list[float]:
    """Compute differences between consecutive probabilities.

    Args:
        probs: Dict mapping N (1-4) to probability

    Returns:
        List of differences [P2-P1, P3-P2, P4-P3]
    """
    values = [probs[N] for N in sorted(probs.keys())]
    return [values[i + 1] - values[i] for i in range(len(values) - 1)]


def run_simulation(config: Optional[SimulationConfig] = None) -> SimulationResult:
    """Run the event statistics simulation.

    Args:
        config: Simulation configuration (uses defaults if None)

    Returns:
        SimulationResult with all computed statistics
    """
    if config is None:
        config = SimulationConfig()

    # Generate paths
    returns = simulate_paths(config)

    # Compute probabilities
    probs = compute_all_conditional_probs(returns)
    unconditional = compute_unconditional_prob(returns)

    # Verify monotonicity
    is_monotonic = verify_monotonicity(probs)
    differences = monotonic_differences(probs)

    # Compute uncertainty analysis
    uncertainty_analysis = compute_remaining_uncertainty_effect(returns)

    return SimulationResult(
        config=config,
        returns=returns,
        probs=probs,
        unconditional_prob=unconditional,
        is_monotonic=is_monotonic,
        differences=differences,
        uncertainty_analysis=uncertainty_analysis,
    )
