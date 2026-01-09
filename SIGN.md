# Order Signing Guide

Developer guide for signing and placing orders in the poly trading platform.

## Quick Start

### 1. Configure Credentials

```bash
# Option A: Environment variables
export POLYMARKET_WALLET_ADDRESS="0x..."
export POLYMARKET_PRIVATE_KEY="0x..."

# Option B: Config file (config/polymarket.json)
{
  "wallet_address": "0x...",
  "private_key": "0x..."
}
```

### 2. Place an Order

```python
import asyncio
from poly import PolymarketAPI, PolymarketConfig, OrderSide

async def main():
    config = PolymarketConfig.load()

    async with PolymarketAPI(config) as api:
        result = await api.place_order(
            token_id="0x...",  # YES or NO token
            side=OrderSide.BUY,
            price=0.45,
            size=10.0,
        )
        print(f"Order ID: {result.order_id}")

asyncio.run(main())
```

---

## Using PolymarketAPI (Recommended)

The `PolymarketAPI` class handles all signing internally via `LocalSigner`.

### Basic Order Placement

```python
from poly import PolymarketAPI, PolymarketConfig, OrderSide, OrderTimeInForce

config = PolymarketConfig.load()

async with PolymarketAPI(config) as api:
    # Place order by token ID
    result = await api.place_order(
        token_id="21742633143463906290569050155826241533067272736897614950488156847949938836455",
        side=OrderSide.BUY,
        price=0.45,
        size=10.0,
        time_in_force=OrderTimeInForce.GTC,  # Good Till Cancelled
    )

    if result.success:
        print(f"Order placed: {result.order_id}")
        print(f"Submission time: {result.submission_time_ms:.0f}ms")
    else:
        print(f"Failed: {result.error_message}")
```

### Order by Market Slug

```python
# More convenient - resolves token ID automatically
result = await api.place_order_by_slug(
    market_slug="btc-updown-15m-1767795300",
    outcome="Up",  # "Up", "Down", "Yes", or "No"
    side=OrderSide.BUY,
    price=0.45,
    size=10.0,
)
```

### Execute and Wait for Fill

```python
from poly import ExecutionConfig

exec_config = ExecutionConfig(
    order_timeout_sec=30.0,   # Wait up to 30s for order to match
    trade_timeout_sec=60.0,   # Wait up to 60s for trade to be mined
)

result = await api.execute_order(
    token_id="0x...",
    side=OrderSide.BUY,
    price=0.45,
    size=10.0,
    config=exec_config,
)

if result.success:
    print(f"Filled! TX hashes: {result.transaction_hashes}")
    print(f"Total time: {result.total_execution_time_ms:.0f}ms")
```

### Cancel Order

```python
await api.cancel_order(order_id="0x...")
```

### Get Order Status

```python
order_info = await api.get_order(order_id="0x...")
print(f"Status: {order_info.status}")
print(f"Filled: {order_info.size_matched} / {order_info.original_size}")
```

---

## Using LocalSigner Directly

For more control, use `LocalSigner` directly (wraps py-clob-client).

### Create Signer

```python
from poly import LocalSigner

signer = LocalSigner(
    private_key="0x...",
    chain_id=137,  # Polygon mainnet
)

# Get wallet address
print(f"Wallet: {signer.get_wallet_address()}")
```

### Sign and Post Order

```python
from poly import LocalSigner, OrderParams, OrderSide

signer = LocalSigner(private_key="0x...")

# Create order parameters
params = OrderParams(
    token_id="21742633143463906290569050155826241533067272736897614950488156847949938836455",
    side=OrderSide.BUY,
    price=0.45,
    size=10.0,
    fee_rate_bps=0,
    expiration=0,  # No expiration
)

# Sign the order
signed_order = signer.sign_order(params)

# Post to CLOB API
response = signer.post_order(signed_order)
print(f"Order ID: {response['orderID']}")
```

### Cancel and Query

```python
# Cancel
signer.cancel_order(order_id="0x...")

# Get order status
order = signer.get_order(order_id="0x...")
print(f"Status: {order['status']}")
```

---

## Using py-clob-client Directly

If you need direct access to the underlying py-clob-client:

```python
from py_clob_client.client import ClobClient
from py_clob_client.order_builder.constants import BUY, SELL

# Create client
client = ClobClient(
    host="https://clob.polymarket.com",
    key="0x...",  # Private key
    chain_id=137,
)

# Derive API credentials (required for authenticated endpoints)
creds = client.create_or_derive_api_creds()
client.set_api_creds(creds)

# Create and post order
order = client.create_order(
    token_id="21742633143463906290569050155826241533067272736897614950488156847949938836455",
    price=0.45,
    size=10.0,
    side=BUY,
)

response = client.post_order(order)
print(f"Order ID: {response['orderID']}")

# Cancel
client.cancel(order_id="0x...")

# Get order
order = client.get_order(order_id="0x...")
```

### Access via LocalSigner

```python
from poly import LocalSigner

signer = LocalSigner(private_key="0x...")

# Get the underlying ClobClient
clob_client = signer._get_clob_client()

# Now use py-clob-client directly
orderbook = clob_client.get_order_book(token_id="0x...")
```

---

## Configuration Reference

### PolymarketConfig

```python
from poly import PolymarketConfig

# Load from env/config file automatically
config = PolymarketConfig.load()

# Or explicit construction
config = PolymarketConfig(
    wallet_address="0x...",
    private_key="0x...",
    chain_id=137,
    clob_api_url="https://clob.polymarket.com",
)

# Check if trading is enabled
if config.has_trading_credentials:
    print("Trading enabled")
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `POLYMARKET_WALLET_ADDRESS` | Your wallet address (required) |
| `POLYMARKET_PRIVATE_KEY` | Private key for signing (required for trading) |
| `POLYMARKET_CHAIN_ID` | Chain ID (default: 137) |
| `POLYMARKET_SIGNER_TYPE` | `local` (default), `kms`, or `eoa` |

### Config File (config/polymarket.json)

```json
{
  "wallet_address": "0x...",
  "private_key": "0x...",
  "chain_id": 137
}
```

---

## OrderParams Reference

```python
from poly import OrderParams, OrderSide

params = OrderParams(
    token_id="0x...",           # YES or NO token address
    side=OrderSide.BUY,         # BUY or SELL
    price=0.45,                 # 0.01 to 0.99
    size=10.0,                  # Number of shares
    fee_rate_bps=0,             # Fee in basis points (default: 0)
    nonce=None,                 # Auto-generated if None
    expiration=0,               # 0 = no expiration
)
```

### Price and Size

- **Price**: Between 0.01 and 0.99 (probability)
- **Size**: Number of shares (contracts)
- **Cost** (BUY): `size * price` USDC
- **Proceeds** (SELL): `size * price` USDC

Example: BUY 100 shares at 0.45 costs 45 USDC.

---

## Order Types

```python
from poly import OrderTimeInForce

# Good Till Cancelled (default)
OrderTimeInForce.GTC

# Good Till Day
OrderTimeInForce.GTD

# Fill Or Kill
OrderTimeInForce.FOK

# Fill And Kill (Immediate or Cancel)
OrderTimeInForce.FAK
```

---

## Error Handling

```python
from poly import (
    TradingNotConfiguredError,
    TradingError,
    OrderCanceledError,
    OrderExpiredError,
    ExecutionTimeoutError,
)

try:
    result = await api.place_order(...)
except TradingNotConfiguredError:
    print("Missing private_key in config")
except TradingError as e:
    print(f"Trading error: {e}")
```

---

## Complete Example

```python
#!/usr/bin/env python3
"""Complete trading example."""

import asyncio
from poly import (
    PolymarketAPI,
    PolymarketConfig,
    OrderSide,
    Asset,
    MarketHorizon,
    fetch_current_prediction,
)


async def main():
    # Load config
    config = PolymarketConfig.load()
    print(f"Wallet: {config.wallet_address}")

    # Get current BTC 15m market
    prediction = await fetch_current_prediction(Asset.BTC, MarketHorizon.M15)
    print(f"Market: {prediction.slug}")
    print(f"Current UP prob: {prediction.up_probability:.1%}")

    async with PolymarketAPI(config) as api:
        # Get orderbook
        orderbook = await api.get_orderbook(prediction.up_token_id)
        best_bid = float(orderbook['bids'][0]['price']) if orderbook['bids'] else 0
        best_ask = float(orderbook['asks'][0]['price']) if orderbook['asks'] else 1
        print(f"Orderbook: {best_bid:.2f} / {best_ask:.2f}")

        # Place order below market (won't fill)
        test_price = round(best_bid * 0.8, 2)

        result = await api.place_order_by_slug(
            market_slug=prediction.slug,
            outcome="Up",
            side=OrderSide.BUY,
            price=test_price,
            size=1.0,
        )

        if result.success:
            print(f"Order placed: {result.order_id}")

            # Cancel it
            await api.cancel_order(result.order_id)
            print("Order cancelled")
        else:
            print(f"Failed: {result.error_message}")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Testing

### Dry Run (No Real Orders)

```bash
python scripts/trade_dry_run.py
```

### Test Order (Cancelled Immediately)

```bash
python scripts/trade_dry_run.py --live --size 1.0
```

---

## Sync API

For non-async code:

```python
from poly import PolymarketAPISync, OrderSide

api = PolymarketAPISync(config)

result = api.place_order(
    token_id="0x...",
    side=OrderSide.BUY,
    price=0.45,
    size=10.0,
)

api.close()
```

---

## KMS Signing (Production)

For production with Google Cloud KMS:

```python
from poly import PolymarketConfig, SignerType

config = PolymarketConfig(
    wallet_address="0x...",  # Derived from KMS public key
    signer_type=SignerType.KMS,
    kms_key_path="projects/PROJECT/locations/LOCATION/keyRings/RING/cryptoKeys/KEY/cryptoKeyVersions/1",
)

# Use same API
async with PolymarketAPI(config) as api:
    result = await api.place_order(...)
```

See the KMS section below for setup instructions.

---

## Appendix: KMS Setup

### Create KMS Key

```bash
# Create key ring
gcloud kms keyrings create polymarket \
  --location=us-central1 \
  --project=YOUR_PROJECT

# Create signing key (secp256k1)
gcloud kms keys create trading \
  --keyring=polymarket \
  --location=us-central1 \
  --purpose=asymmetric-signing \
  --default-algorithm=ec-sign-secp256k1-sha256 \
  --project=YOUR_PROJECT
```

### Get Key Path

```bash
gcloud kms keys versions list \
  --key=trading \
  --keyring=polymarket \
  --location=us-central1 \
  --project=YOUR_PROJECT
```

### Derive Wallet Address

```python
from google.cloud import kms
from cryptography.hazmat.primitives.serialization import load_pem_public_key, Encoding, PublicFormat
from eth_utils import keccak

def get_address_from_kms(key_path: str) -> str:
    client = kms.KeyManagementServiceClient()
    response = client.get_public_key(name=key_path)

    public_key = load_pem_public_key(response.pem.encode())
    public_bytes = public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)

    address = keccak(public_bytes[1:])[-20:]
    return "0x" + address.hex()

wallet = get_address_from_kms("projects/.../cryptoKeyVersions/1")
print(f"Wallet: {wallet}")
```

### Grant Permissions

```bash
gcloud kms keys add-iam-policy-binding trading \
  --keyring=polymarket \
  --location=us-central1 \
  --member="serviceAccount:YOUR_SA@YOUR_PROJECT.iam.gserviceaccount.com" \
  --role="roles/cloudkms.signerVerifier" \
  --project=YOUR_PROJECT
```
