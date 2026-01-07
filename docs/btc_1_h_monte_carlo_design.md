# Monte Carlo 模拟器设计文档：验证 15min（第 N 段）↔ 1h 概率关系

> 目标：用 **Monte Carlo 随机游走** 模拟 BTC 在 1 小时内的价格路径，
> 并验证：
>
> - 第 **N 个 15min** 为「涨」的条件下，
> - 1 小时为「涨」的条件概率如何变化。

本文档是一个**实现导向（engineering-first）**的设计说明，直接对应 Python 代码结构。

---

## 1. 模拟目标（What we want to verify）

我们希望通过模拟回答以下问题：

> 对于 N = 1,2,3,4：
>
> \[\mathbb P(\text{1h up} \mid \text{15min}_N \text{ up})\]
>
> 是否随 N 单调上升？

这用于验证之前的理论结论：

> **15min 的“位置”决定其对 1h 结果的信息含量**。

---

## 2. 模型假设（可配置）

### 2.1 基础价格模型

我们采用最简单、可解释性最强的模型作为起点：

- **对数价格随机游走（Geometric Brownian Motion 的离散版本）**

\[
\log S_{t+\Delta t} = \log S_t + \mu\,\Delta t + \sigma\,\sqrt{\Delta t}\,Z
\]

其中：
- \(Z \sim \mathcal N(0,1)\)

> ⚠️ 这里不是为了“逼真”，而是为了**控制变量、验证理论结构**。

---

### 2.2 时间离散

- 总时间：1 小时
- 步长：15 分钟
- 步数：4

---

## 3. 核心可配置参数（必须）

```python
SimulationConfig:
    n_paths: int          # Monte Carlo 路径数（如 1_000_000）
    mu: float             # 漂移（每小时）
    sigma: float          # 波动率（每 sqrt(hour)）
    seed: Optional[int]   # 随机种子（可复现）
```

说明：
- `mu = 0`：纯对称随机游走（验证“无条件等价性”）
- `mu > 0`：带趋势（验证趋势放大效应）

---

## 4. 核心定义（事件与符号）

### 4.1 路径表示

- 对数收益数组：

```python
returns.shape == (n_paths, 4)
```

其中 `returns[:, i]` 表示第 `i+1` 个 15min 的对数收益。

---

### 4.2 事件定义

```text
B_N : 第 N 个 15min 为涨
      returns[:, N-1] > 0

A   : 1h 为涨
      returns.sum(axis=1) > 0
```

---

## 5. 主要函数设计

### 5.1 路径生成函数

```python
def simulate_paths(config: SimulationConfig) -> np.ndarray:
    """
    Generate Monte Carlo log-return paths.

    Returns
    -------
    returns : np.ndarray, shape (n_paths, 4)
        Log returns for each 15min segment.
    """
```

---

### 5.2 条件概率计算函数

```python
def conditional_prob_1h_up_given_15min_up(
    returns: np.ndarray,
    segment_index: int,
) -> float:
    """
    Compute P(1h up | N-th 15min up).

    Parameters
    ----------
    segment_index : int
        0-based index (0,1,2,3) corresponding to N=1..4
    """
```

---

### 5.3 批量计算（N = 1..4）

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

## 6. 主执行函数（main）

```python
def main():
    # 1. 读取 / 定义参数
    config = SimulationConfig(
        n_paths=1_000_000,
        mu=0.0,
        sigma=0.05,
        seed=42,
    )

    # 2. 生成 Monte Carlo 路径
    returns = simulate_paths(config)

    # 3. 计算条件概率
    results = compute_all_conditional_probs(returns)

    # 4. 打印结果
    for N, p in results.items():
        print(f"P(1h up | {N}th 15min up) = {p:.4f}")
```

---

## 7. 预期结果（理论对照）

### 在 mu = 0（对称随机游走）下

- \(P(1h up) \approx 0.5\)
- \(P(1h up | B_1) \approx P(1h up | B_2)\)
- **但**：

\[
P(1h up | B_1)
< P(1h up | B_2)
< P(1h up | B_3)
< P(1h up | B_4)
\]

这验证：

> **位置效应来自信息结构，而非漂移或分布不对称**。

---

## 8. 可扩展方向（后续）

- 非高斯噪声（t 分布 / jump diffusion）
- 条件在“前 k 个 15min 已知”的概率
- 用 entropy / mutual information 量化信息增益
- 对比 Monte Carlo 与市场隐含概率

---

## 9. 本文档的角色

- ✅ 实验设计说明
- ✅ Monte Carlo 验证理论的最小实现蓝图
- ✅ 后续论文 / whitepaper 的实验章节雏形

---

*下一步可以直接：*
- 把本设计转成 **完整 Python 实现**
- 或在此基础上加入 **统计检验与可视化**

