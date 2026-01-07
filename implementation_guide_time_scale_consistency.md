# Implementation Guide: Time‑Scale Consistency Between 15min and 1h Prediction Markets

This document is an **engineering‑oriented specification**, not a theory paper.
Its purpose is to clearly describe **what functions should be written**, **what inputs they require**, and **how they should be implemented**, so that you can translate the theory into executable code.

The focus is on **15min ↔ 1h markets**, with explicit handling of **position effects** (1st vs 4th 15min).

---

## 1. Core Concept to Implement

You are implementing a **model‑consistency checker**, not an arbitrage engine.

At a high level:

> Use short‑horizon market probabilities to infer a **model‑implied probability** for a longer horizon, and compare it to the market price of that longer‑horizon contract.

The output is a **mispricing signal**, which can later be used for alpha discovery, filtering, or trading decisions.

---

## 2. Data Model and Definitions

### 2.1 Time Horizons

- Base horizon: **15 minutes**
- Aggregated horizon: **1 hour = 4 × 15 minutes**

### 2.2 Events

- `B_i`: the event that the *i‑th* 15min interval is UP
- `A`: the event that the full 1h interval is UP

### 2.3 Market Inputs

All prices are assumed to be **binary prediction prices**, i.e. market‑implied probabilities.

---

## 3. Required Inputs (Minimal Set)

To compute mispricing, your code needs **only market probabilities and time structure**.

### Mandatory Inputs

| Name | Type | Description |
|---|---|---|
| `p_15` | float | Market‑implied probability that a given 15min interval is UP |
| `p_1h` | float | Market‑implied probability that the 1h interval is UP |
| `k` | int | Index of the 15min interval (1, 2, 3, or 4) |
| `N` | int | Number of 15min intervals in the 1h window (fixed at 4) |

### Optional (but Practical) Inputs

| Name | Type | Purpose |
|---|---|---|
| `tx_cost` | float | Fee / slippage threshold |
| `epsilon` | float | Numerical safety margin |

---

## 4. Functions You Should Implement

### 4.1 Probability Mapping Function

This function converts a **short‑horizon probability** into a **model‑implied long‑horizon probability**.

#### Purpose

Encodes the assumption:

- Log‑returns are i.i.d.
- CLT applies
- Time aggregation scales with √T

#### Function Signature (suggested)

```python
def implied_long_prob(p_short: float, T: float) -> float:
    """
    Map short-horizon UP probability to long-horizon UP probability
    under Gaussian i.i.d / CLT assumption.
    """
```

#### Implementation Logic

1. Convert probability to z‑score:
   
   `z = Φ⁻¹(p_short)`

2. Scale by time horizon:

   `z_long = sqrt(T) * z`

3. Convert back to probability:

   `p_long = Φ(z_long)`

---

## 5. Position‑Aware Adjustment (Key Part)

The **same 15min probability means different things depending on position**.

### 5.1 Why Position Matters

- Early 15min → weak information about final 1h outcome
- Late 15min → strong constraint on final 1h outcome

Therefore, your implementation **must not treat all 15min equally**.

---

### 5.2 Position Weighting Function

You should explicitly encode how much of the 1h uncertainty remains.

#### Recommended Definition

Let:

```
remaining_intervals = N - k + 1
```

Define an **effective horizon multiplier**:

```
T_eff = remaining_intervals
```

This reflects that:

- k = 1 → 4 intervals remain
- k = 4 → 1 interval remains (almost resolved)

---

### 5.3 Position‑Aware Implied Probability

#### Function Signature

```python
def implied_1h_prob_from_15m(
    p_15: float,
    k: int,
    N: int = 4
) -> float:
    """
    Compute model-implied 1h UP probability
    given the k-th 15min UP probability.
    """
```

#### Implementation Steps

1. Validate inputs (`1 <= k <= N`)
2. Compute remaining intervals:

   `T_eff = N - k + 1`

3. Apply probability mapping using `T_eff`

---

## 6. Mispricing Computation

### Definition

Mispricing is defined as:

```
mispricing = p_1h_market - p_1h_model
```

- `> 0` → 1h market is more bullish than model implies
- `< 0` → 1h market is more bearish than model implies

---

### Function Signature

```python
def mispricing_15m_vs_1h(
    p_15: float,
    p_1h: float,
    k: int,
    N: int = 4
) -> float:
    """
    Compute probability mispricing between
    k-th 15min market and 1h market.
    """
```

### Internal Logic

1. Call `implied_1h_prob_from_15m`
2. Subtract model-implied value from market price
3. Return signed mispricing

---

## 7. Validation & Safety Checks

You should enforce:

- `0 < p_15 < 1`
- `0 < p_1h < 1`
- `k ∈ {1,2,3,4}`

Optionally clamp probabilities away from 0 and 1 using `epsilon`.

---

## 8. Interpretation Guidelines (Non‑Trading)

This code produces a **diagnostic signal**, not a trade.

Interpretation:

- Small mispricing → noise / fees dominate
- Large mispricing → potential inconsistency
- Late‑interval mispricing is **structurally more meaningful** than early‑interval mispricing

---

## 9. What This Implementation Is *Not*

- ❌ Not a proof of arbitrage
- ❌ Not a pricing oracle
- ❌ Not strategy logic

It is intentionally modular so that you can later:

- Plug it into a backtest
- Add fees / thresholds
- Extend to 1h ↔ 24h

---

## 10. Next Extensions (Optional)

After you implement this, natural extensions are:

- Generalize to arbitrary Δt → T
- Replace Gaussian assumption
- Add confidence intervals via historical calibration
- Use late‑interval dominance as a hard constraint

---

**This document is meant to be translated directly into code.**

