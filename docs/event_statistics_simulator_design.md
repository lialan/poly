# Minimal Conversion: From Trading Simulator to Event Statistics Simulator

## Goal

Convert the existing **price-path Monte Carlo simulator** into a **pure event statistics engine** with **minimal changes**, in order to validate the theoretical claim:

> \[ P(1h\ \text{up} \mid 15min_N\ \text{up}) \] is **monotonically increasing** in \(N = 1,2,3,4\).

This document intentionally **removes PnL, positions, turnover, and execution logic**, and focuses only on **event probabilities**.

---

## Conceptual Shift (Very Important)

### Before (Trading Simulator)

- Continuous signals (15m, 1h)
- Continuous positions
- PnL, Sharpe, drawdown
- Execution frequency (e.g. every 5 seconds)

### After (Event Statistics Simulator)

- **Binary events only**
- No positions, no trading, no costs
- Monte Carlo paths → event counters

This aligns the simulation **exactly** with the theoretical questions discussed earlier.

---

## Model Assumptions (Unchanged)

We keep the **same stochastic model** to ensure minimal modification:

- Log-price random walk
- Gaussian increments
- 4 × 15min steps per 1h

\[
\log S_{t+\Delta t} = \log S_t + \mu\,\Delta t + \sigma\sqrt{\Delta t}\,Z
\]

where \(Z \sim \mathcal N(0,1)\).

---

## Required Inputs (Configurable)

```python
SimulationConfig:
    n_paths: int        # Number of Monte Carlo paths
    mu: float           # Drift per hour
    sigma: float        # Volatility per sqrt(hour)
    seed: Optional[int] # RNG seed (reproducibility)
```

Notes:
- Set `mu = 0` to test the **pure symmetry / information effect**
- Increase `n_paths` (≥ 1e6) to reduce Monte Carlo noise

---

## Core Event Definitions

Let `returns` be a NumPy array of shape `(n_paths, 4)`:

```text
returns[i, j] = log return of path i during 15min segment j
```

### Events

- **15min up (segment N)**
  ```python
  B_N = returns[:, N-1] > 0
  ```

- **1h up**
  ```python
  A = returns.sum(axis=1) > 0
  ```

---

## Minimal Function Set

### 1. Path Generator (unchanged core)

```python
def simulate_paths(config: SimulationConfig) -> np.ndarray:
    """
    Generate Monte Carlo log-return paths.

    Returns
    -------
    returns : np.ndarray, shape (n_paths, 4)
    """
```

---

### 2. Conditional Probability Estimator

```python
def conditional_prob_1h_up_given_15min_up(
    returns: np.ndarray,
    segment_index: int,
) -> float:
    """
    Estimate P(1h up | N-th 15min up).

    Parameters
    ----------
    segment_index : int
        0-based index (0..3 corresponding to N=1..4)
    """
```

Implementation logic:

```python
mask_15m_up = returns[:, segment_index] > 0
mask_1h_up  = returns.sum(axis=1) > 0

p = mask_1h_up[mask_15m_up].mean()
```

---

### 3. Batch Evaluation for N = 1..4

```python
def compute_all_conditional_probs(returns: np.ndarray) -> dict:
    """
    Returns
    -------
    probs : dict
        {N: P(1h up | N-th 15min up)}
    """
```

---

## Monotonicity Verification Code (Core Requirement)

The following code **directly tests the theoretical claim**.

```python
import numpy as np

def verify_monotonicity(probs: dict) -> bool:
    """
    Check whether probabilities are monotonically increasing.

    probs : {N: probability}, N = 1..4
    """
    values = [probs[N] for N in sorted(probs.keys())]
    return all(values[i] <= values[i+1] for i in range(len(values)-1))
```

Optional: report differences

```python
def monotonic_differences(probs: dict):
    values = [probs[N] for N in sorted(probs.keys())]
    return [values[i+1] - values[i] for i in range(len(values)-1)]
```

---

## Main Execution Function

```python
def main():
    config = SimulationConfig(
        n_paths=1_000_000,
        mu=0.0,
        sigma=0.05,
        seed=42,
    )

    returns = simulate_paths(config)
    probs = compute_all_conditional_probs(returns)

    print("Conditional probabilities:")
    for N, p in probs.items():
        print(f"P(1h up | {N}th 15min up) = {p:.5f}")

    is_monotone = verify_monotonicity(probs)
    print("\nMonotonicity holds:", is_monotone)

    print("Differences:", monotonic_differences(probs))
```

---

## Expected Results (Sanity Check)

### Case 1: `mu = 0` (symmetric random walk)

- Unconditional: `P(1h up) ≈ 0.5`
- Conditional:

```text
P(1h up | 1st 15min up)
< P(1h up | 2nd 15min up)
< P(1h up | 3rd 15min up)
< P(1h up | 4th 15min up)
```

Monotonicity should hold **almost surely** with enough paths.

---

### Case 2: `mu > 0` (positive drift)

- All probabilities shift upward
- **Monotonic structure remains**

This shows the effect is **informational**, not driven by drift.

---

## Why This Design Is Theoretically Correct

- Events correspond exactly to σ-algebras at different stopping times
- No execution noise
- No path-dependent bias
- Monte Carlo error is the only randomness

This is the **cleanest numerical experiment** to validate the position-effect theorem.

---

## Next Natural Extensions

- Confidence intervals via bootstrap
- Mutual information estimation
- Extension to 1h ↔ 24h
- Comparison with market-implied probabilities

---

*This document is suitable as an experimental methodology section in a research note or whitepaper.*
