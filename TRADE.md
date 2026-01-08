# Trade Execution API

This document describes the trade execution functionality in `polymarket_api.py`.

## Overview

The trade execution system provides:
1. **Order Placement**: Submit limit orders to Polymarket CLOB
2. **Execution Tracking**: Wait for orders to match and trades to be mined on-chain
3. **Transaction Hashes**: Get on-chain transaction hashes for confirmed trades

## State Machine

### Order States
```
LIVE → MATCHED (has associate_trades)
LIVE → CANCELED (user canceled)
LIVE → EXPIRED (time limit reached)
```

### Trade States
```
MATCHED → MINED (on-chain, no finality)
MATCHED → RETRYING (tx failed, resubmitting)
MINED → CONFIRMED (probabilistic finality)
MATCHED/RETRYING → FAILED (permanent failure)
```

## Quick Start

### Basic Order Placement (Fire and Forget)

```python
from poly import PolymarketAPI, OrderSide

async with PolymarketAPI(config) as api:
    # Place order by token ID
    result = await api.place_order(
        token_id="0x...",
        side=OrderSide.BUY,
        price=0.45,
        size=100.0,
    )
    print(f"Order ID: {result.order_id}")
    print(f"Submission time: {result.submission_time_ms:.0f}ms")
```

### Full Execution (Wait for MINED)

```python
from poly import PolymarketAPI, OrderSide, ExecutionConfig

config = ExecutionConfig(
    order_timeout_sec=30.0,
    trade_timeout_sec=60.0,
)

async with PolymarketAPI(pm_config) as api:
    result = await api.execute_order(
        token_id="0x...",
        side=OrderSide.BUY,
        price=0.45,
        size=100.0,
        config=config,
    )

    if result.success:
        print(f"Order {result.order_id} executed!")
        print(f"Transaction hashes: {result.transaction_hashes}")
        print(f"Total time: {result.total_execution_time_ms:.0f}ms")
    else:
        print(f"Failed: {result.error_message}")
```

### Using Market Slug (Convenience)

```python
# Place order by market slug and outcome
# Outcome can be: "Yes", "No", "Up", or "Down" (aliases supported)
result = await api.place_order_by_slug(
    market_slug="btc-updown-15m-1767795300",
    outcome="Up",  # or "Yes" - both work
    side=OrderSide.BUY,
    price=0.45,
    size=100.0,
)

# Or execute with full tracking
result = await api.execute_order_by_slug(
    market_slug="btc-updown-15m-1767795300",
    outcome="Up",
    side=OrderSide.BUY,
    price=0.45,
    size=100.0,
)
```

**Note**: Crypto markets use "Up"/"Down" outcomes while other markets may use "Yes"/"No". The API accepts both interchangeably:
- "Yes" / "Up" → first outcome (index 0)
- "No" / "Down" → second outcome (index 1)

## API Reference

### Configuration

#### `ExecutionConfig`

Controls polling behavior and timeouts:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `order_poll_interval_sec` | float | 0.5 | Interval between order status polls |
| `order_timeout_sec` | float | 30.0 | Max time to wait for order to have trades |
| `trade_poll_interval_sec` | float | 1.0 | Interval between trade status polls |
| `trade_timeout_sec` | float | 60.0 | Max time to wait for trade to be MINED |

### Result Types

#### `OrderResult`

Returned by `place_order()` and `place_order_by_slug()`:

| Field | Type | Description |
|-------|------|-------------|
| `order_id` | str | CLOB order ID |
| `success` | bool | Whether order was placed |
| `submission_time_ms` | float | Time to submit order |
| `error_message` | str | Error if failed |
| `token_id` | str | Token that was traded |
| `side` | OrderSide | BUY or SELL |
| `price` | float | Order price |
| `size` | float | Order size |

#### `ExecutionResult`

Returned by `execute_order()` and `execute_order_by_slug()`:

| Field | Type | Description |
|-------|------|-------------|
| `order_id` | str | CLOB order ID |
| `trades` | list[Trade] | All trades (MINED or CONFIRMED) |
| `transaction_hashes` | list[str] | On-chain tx hashes |
| `total_size_matched` | float | Total filled size |
| `total_execution_time_ms` | float | Total time from order to MINED |
| `success` | bool | Whether execution completed |
| `error_message` | str | Error if failed |

#### `OrderInfo`

Returned by `get_order()`:

| Field | Type | Description |
|-------|------|-------------|
| `order_id` | str | Order hash |
| `status` | str | LIVE, MATCHED, CANCELED, EXPIRED |
| `associate_trades` | list[str] | Trade IDs from fills |
| `size_matched` | float | Filled quantity |
| `original_size` | float | Original order size |

### Methods

#### Order Placement

```python
# By token ID
await api.place_order(token_id, side, price, size, time_in_force=GTC) -> OrderResult

# By market slug
await api.place_order_by_slug(market_slug, outcome, side, price, size, time_in_force=GTC) -> OrderResult

# Cancel order
await api.cancel_order(order_id) -> bool
```

#### Execution Tracking

```python
# Full execution (place + wait for MINED)
await api.execute_order(token_id, side, price, size, time_in_force=GTC, config=None) -> ExecutionResult

# Full execution by slug
await api.execute_order_by_slug(market_slug, outcome, side, price, size, time_in_force=GTC, config=None) -> ExecutionResult

# Get order status
await api.get_order(order_id) -> OrderInfo

# Wait for order to have trades
await api.wait_for_order_match(order_id, config=None) -> list[str]  # returns trade IDs

# Wait for trade to be MINED
await api.wait_for_trade_mined(trade_id, config=None) -> Trade
```

### Enums

```python
class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderTimeInForce(str, Enum):
    GTC = "GTC"  # Good Till Cancelled
    GTD = "GTD"  # Good Till Day
    FOK = "FOK"  # Fill Or Kill
    FAK = "FAK"  # Fill And Kill (Immediate or Cancel)
```

### Exceptions

All inherit from `TradingError`:

| Exception | When Raised |
|-----------|-------------|
| `TradingNotConfiguredError` | `private_key` not in config |
| `OrderCanceledError` | Order was canceled |
| `OrderExpiredError` | Order expired before filling |
| `TradeMiningFailedError` | Trade failed to be mined on-chain |
| `ExecutionTimeoutError` | Timeout waiting for state transition |

## Sync API

For non-async contexts, use `PolymarketAPISync`:

```python
from poly import PolymarketAPISync, OrderSide

api = PolymarketAPISync(config)

# All methods available as blocking calls
result = api.execute_order(
    token_id="0x...",
    side=OrderSide.BUY,
    price=0.45,
    size=100.0,
)

api.close()
```

## Configuration Requirements

Trading requires `private_key` in your Polymarket config:

```python
# Via environment variable
export POLYMARKET_PRIVATE_KEY="0x..."

# Or via config file (config/polymarket.json)
{
    "wallet_address": "0x...",
    "private_key": "0x..."
}

# Or via Secret Manager
# Secret: polymarket-private-key
```

## Error Handling

```python
from poly import (
    TradingNotConfiguredError,
    OrderCanceledError,
    OrderExpiredError,
    TradeMiningFailedError,
    ExecutionTimeoutError,
)

try:
    result = await api.execute_order(...)
    if not result.success:
        print(f"Execution failed: {result.error_message}")
except TradingNotConfiguredError:
    print("Missing private_key - configure credentials")
except OrderCanceledError:
    print("Order was canceled")
except OrderExpiredError:
    print("Order expired before matching")
except TradeMiningFailedError:
    print("Trade failed to be mined on-chain")
except ExecutionTimeoutError:
    print("Timeout waiting for execution")
```

## Testing with Dry Run

Before placing real orders, use the dry run script to verify your setup:

```bash
# Basic dry run (read-only, no orders placed)
python scripts/trade_dry_run.py

# Test specific market
python scripts/trade_dry_run.py --market btc-updown-15m-1767795300

# Test with a real order (will be canceled immediately)
python scripts/trade_dry_run.py --live --size 1.0
```

The dry run verifies:
1. Configuration and credentials
2. Market resolution (slug → token_id)
3. Order book access
4. CLOB client initialization
5. API endpoint connectivity

## Notes

1. **One order can generate multiple trades**: The system handles this by iterating through all `associate_trades` from the order status.

2. **MINED is the cutoff**: The execution waits until trades reach MINED status, at which point `transaction_hash` is available.

3. **py-clob-client dependency**: Trading requires `py-clob-client` package for order signing:
   ```bash
   pip install py-clob-client
   ```

4. **Price range**: Prices must be between 0 and 1 exclusive (0 < price < 1).

5. **Token resolution**: Use `*_by_slug` methods to automatically resolve token IDs from market slugs and outcome names.

6. **Outcome aliases**: Both "Yes"/"Up" and "No"/"Down" are accepted and treated as equivalent.
