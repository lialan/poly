# Polymarket Trading Platform

## Project Overview
A Python-based platform for collecting and analyzing Polymarket crypto prediction markets (BTC and ETH).

## Tech Stack
- **Language**: Python 3.11+
- **APIs**: Polymarket CLOB API, Gamma Markets API
- **Price Feeds**: Binance REST API
- **Database**: Google Cloud Bigtable, SQLite (local)
- **Cloud**: Google Compute Engine (GCE)
- **Async**: asyncio, aiohttp
- **Testing**: pytest, pytest-asyncio
- **Package Manager**: uv

## Project Structure
```
poly/
├── src/poly/
│   ├── __init__.py           # Package exports
│   ├── markets.py            # Unified BTC/ETH prediction markets
│   ├── market_snapshot.py    # Orderbook snapshots
│   ├── market_feed.py        # WebSocket daemon for real-time data
│   ├── polymarket_api.py     # Async/sync API client (positions, trades)
│   ├── polymarket_config.py  # Config with Secret Manager support
│   ├── polymarket_ws.py      # Low-level WebSocket client
│   ├── binance_price.py      # Binance price data (REST)
│   ├── bigtable_writer.py    # Google Cloud Bigtable storage
│   ├── sqlite_writer.py      # SQLite database storage
│   ├── db_writer.py          # Database backend abstraction
│   ├── gamma.py              # Gamma API for public event data
│   ├── client.py             # PolymarketClient - API interactions
│   ├── config.py             # Config class with env loading
│   ├── models.py             # Market, Order, Position models
│   ├── trading.py            # TradingEngine for strategy execution
│   ├── trading_bot.py        # Monitoring bot with WebSocket + Bigtable
│   ├── project_config.py     # Centralized config loader
│   └── utils.py              # Helpers (retry, formatting)
├── scripts/
│   ├── cloudrun_collector.py # GCE data collector (BTC + ETH)
│   ├── query_bigtable.py     # Query Bigtable data
│   ├── collect_snapshots.py  # Local data collector (SQLite)
│   ├── test_polymarket_api.py    # Test API client
│   ├── test_polymarket_ws.py     # Test WebSocket
│   ├── test_market_feed.py       # Test market feed daemon
│   ├── benchmark_polymarket_apis.py  # API latency benchmarks
│   ├── run_trading_bot.py    # Trading bot runner
│   ├── setup.sh              # Dev environment setup
│   └── gce_setup.sh          # GCE instance setup
├── config/
│   └── poly.json             # Centralized project config
├── requirements.txt
├── pyproject.toml
├── DEPLOYMENT.md
└── .gitignore
```

## Core Modules

### `markets.py` - Crypto Prediction Markets
Unified module for BTC and ETH prediction markets across all time horizons.

**Enums:**
- `Asset`: BTC, ETH
- `MarketHorizon`: M15 (15min), H1 (1hr), H4 (4hr), D1 (daily)

**Key Functions:**
- `fetch_current_prediction(asset, horizon)`: Fetch current market
- `get_current_slug(asset, horizon)`: Generate slug for current slot
- `get_current_slot_timestamp(horizon)`: Get slot timestamp

**Slug Patterns:**
| Horizon | Pattern | Example |
|---------|---------|---------|
| 15m | `{asset}-updown-15m-{timestamp}` | `btc-updown-15m-1767749400` |
| 1h | `{name}-up-or-down-{month}-{day}-{hour}-et` | `bitcoin-up-or-down-january-6-9pm-et` |
| 4h | `{asset}-updown-4h-{timestamp}` | `btc-updown-4h-1767747600` |
| D1 | `{name}-up-or-down-on-{month}-{day}` | `bitcoin-up-or-down-on-january-7` |

**Timezone Notes:**
- 4h markets align to ET boundaries (0, 4, 8, 12, 16, 20 hours ET)
- Daily markets resolve at noon ET

### `market_snapshot.py` - Orderbook Snapshots
Minimal snapshot structure storing only non-derivable data.

**MarketSnapshot fields:**
- `timestamp`: When snapshot was taken
- `market_id`: Slug (encodes resolution time)
- `btc_price`: Asset price at snapshot time
- `yes_bids/asks`: Full YES token orderbook
- `no_bids/asks`: Full NO token orderbook

**Derived properties:** `best_yes_bid/ask`, `yes_mid`, `yes_spread`, etc.

### `polymarket_api.py` - API Client
Async and sync clients for querying wallet positions, trades, and market status.

**Classes:**
- `PolymarketAPI` - Async client (uses aiohttp)
- `PolymarketAPISync` - Sync wrapper

**Dataclasses:**
- `MarketPosition` - Position in a market (shares, value, PnL)
- `Trade` - Trade record with status
- `MarketInfo` - Market metadata and status

**Enums:**
- `OrderStatus`: LIVE, MATCHED, CANCELLED, DELAYED
- `TradeStatus`: MATCHED, MINED, CONFIRMED, RETRYING, FAILED
- `MarketStatus`: ACTIVE, RESOLVED, CLOSED

**Usage:**
```python
from poly import PolymarketAPI, PolymarketConfig

config = PolymarketConfig(wallet_address="0x...")
async with PolymarketAPI(config) as api:
    positions = await api.get_positions()
    trades = await api.get_trades(limit=10)
    shares = await api.get_shares_for_market("btc-updown-15m-...")
```

### `polymarket_config.py` - Configuration
Configuration with Google Secret Manager support and env var fallback.

**Classes:**
- `PolymarketConfig` - Main config dataclass
- `SecretManager` - GCP Secret Manager wrapper

**Loading priority:**
1. JSON config file (`config/polymarket.json`)
2. Google Secret Manager (production)
3. Environment variables (local testing)

**Env vars:**
- `POLYMARKET_WALLET_ADDRESS`
- `POLYMARKET_PRIVATE_KEY` (optional, for trading)

### `market_feed.py` - Real-time Data Feed
Daemon-like service for streaming market data via WebSocket. **One connection monitors multiple markets.**

**Classes:**
- `MarketFeed` - Main feed service
- `PriceUpdate` - Price update event
- `MarketState` - Current state of a market
- `FeedStats` - Connection statistics

**Usage:**
```python
from poly import MarketFeed

feed = MarketFeed(on_update=my_callback)
await feed.add_market("btc-15m-...", yes_token, no_token)
await feed.add_market("eth-15m-...", yes_token, no_token)

# Run as background task
task = asyncio.create_task(feed.start())

# Access current state
state = feed.get_market("btc-15m-...")
print(f"BTC probability: {state.implied_prob:.1%}")
```

**Performance:**
- Connection overhead: ~300ms (one-time)
- Update rate: ~70-100 updates/sec
- Latency per update: ~1-2ms

### `polymarket_ws.py` - Low-level WebSocket
Lower-level WebSocket client for custom implementations.

**Endpoint:** `wss://ws-subscriptions-clob.polymarket.com/ws/market`

**Message types:**
- `book` - Full orderbook snapshot (on subscribe)
- `price_change` - Best bid/ask updates

### `trading_bot.py` - Monitoring Trading Bot
Combines WebSocket real-time feed with Bigtable historical data for trading decisions.

**Classes:**
- `TradingBot` - Main bot with start/run/stop lifecycle
- `TradingBotConfig` - All configuration in one dataclass
- `MarketContext` - Data passed to decision function each cycle
- `DecisionResult` - Structured output from decision function
- `CycleTiming` - Timing breakdown for debugging

**Protocol:**
- `DecisionFunction` - Interface for custom trading strategies

**Architecture:**
1. Startup: Test REST APIs, initialize MarketFeed + BigtableWriter
2. Main loop (every N seconds):
   - Pre-fetch Bigtable data (configurable lookback window)
   - Build MarketContext with live + historical data
   - Call decision function
   - Log timing if debug enabled
3. Shutdown: Clean up on SIGINT/SIGTERM

**Usage:**
```python
from poly import TradingBot, TradingBotConfig, MarketContext, DecisionResult

def my_strategy(context: MarketContext) -> DecisionResult:
    prob = context.implied_prob
    if prob and prob < 0.35 and context.time_remaining_sec > 120:
        return DecisionResult(should_trade=True, signal="buy_yes", confidence=0.8)
    return DecisionResult(should_trade=False)

config = TradingBotConfig(
    asset=Asset.BTC,
    horizon=MarketHorizon.M15,
    decision_interval_sec=3.0,
    bigtable_lookback_sec=300.0,
)
bot = TradingBot(config, decision_fn=my_strategy)
await bot.run()
```

**MarketContext fields:**
- `live_state`: MarketState from WebSocket (yes_bid/ask, implied_prob)
- `historical_snapshots`: List of dicts from Bigtable
- `spot_price`: Current asset price
- `time_remaining_sec`: Seconds until market resolution
- `cycle_number`: Current decision cycle number

**Performance (typical):**
- Startup: ~450ms (REST test + WebSocket connect)
- Bigtable fetch: ~65-70ms per cycle
- Decision function: <1ms
- Total cycle: ~70ms

### `project_config.py` - Centralized Config
Single config file (`config/poly.json`) for all project scripts.

**Config Structure:**
```json
{
    "pythonpath": "src",
    "bigtable": {
        "project_id": "poly-collector",
        "instance_id": "poly-data"
    },
    "polymarket": {
        "wallet_address": null,
        "private_key": null
    },
    "collector": {
        "interval_sec": 5,
        "assets": ["btc", "eth"],
        "horizons": {"btc": ["15m", "1h", "4h", "d1"], "eth": ["15m", "1h", "4h"]}
    },
    "trading_bot": {
        "market": {"asset": "btc", "horizon": "15m"},
        "timing": {"decision_interval_sec": 3.0, "bigtable_lookback_sec": 300.0},
        "debug": {"timing": true, "log_level": "INFO"}
    },
    "telegram": {"bot_token": null, "chat_id": null}
}
```

**Usage:**
```python
from poly import load_config, get_bigtable_config

# Load full config
config = load_config()
print(config.bigtable.project_id)

# Get specific section
bigtable = get_bigtable_config()

# Get arbitrary value
value = get_config_value("trading_bot.timing.decision_interval_sec")
```

### `bigtable_writer.py` - Bigtable Storage
**Tables:**
- `btc_15m_snapshot`, `btc_1h_snapshot`, `btc_4h_snapshot`, `btc_d1_snapshot`
- `eth_15m_snapshot`, `eth_1h_snapshot`, `eth_4h_snapshot`

**Row key format:** `{inverted_timestamp}#{market_id}` (newest first)

### `cloudrun_collector.py` - Data Collector
Collects 7 markets every 5 seconds:
- **BTC**: 15m, 1h, 4h, daily
- **ETH**: 15m, 1h, 4h

Features:
- Concurrent price fetching (BTC + ETH independent)
- HTTP health endpoint on port 8080
- Runs as systemd service on GCE

Output format:
```
(1.2s) | BTC:$92,500 [15m:52% 1h:50% 4h:42% d1:48%] | ETH:$3,250 [15m:30% 1h:50% 4h:40%]
```

## GCE Deployment

### Production Setup
- **Instance**: `poly-collector` (e2-micro)
- **Zone**: us-central1-a
- **IP**: 35.224.204.208
- **Project**: poly-collector
- **Bigtable**: poly-data instance

### Deploy Commands
```bash
# Sync code
rsync -avz --exclude='*.pyc' --exclude='__pycache__' \
  -e "ssh -i ~/.ssh/google_compute_engine" \
  src/poly/ lialan@35.224.204.208:~/poly/src/poly/

scp -i ~/.ssh/google_compute_engine scripts/cloudrun_collector.py \
  lialan@35.224.204.208:~/poly/scripts/

# Restart service
gcloud compute ssh poly-collector --zone=us-central1-a --project=poly-collector \
  --command='sudo systemctl restart poly-collector'

# Check logs
gcloud compute ssh poly-collector --zone=us-central1-a --project=poly-collector \
  --command='sudo journalctl -u poly-collector -n 30 --no-pager'
```

### Query Bigtable
```bash
PYTHONPATH=src python scripts/query_bigtable.py --count 10
```

## Environment Variables
**GCE / Bigtable:**
- `DB_BACKEND` - `sqlite` or `bigtable`
- `BIGTABLE_PROJECT_ID` - GCP project ID
- `BIGTABLE_INSTANCE_ID` - Bigtable instance ID
- `COLLECT_INTERVAL` - Seconds between snapshots (default: 5)

**Trading Bot:**
- `TRADING_BOT_ASSET` - Asset to trade: `btc` or `eth` (default: btc)
- `DECISION_INTERVAL` - Seconds between decision cycles (default: 3.0)
- `BIGTABLE_LOOKBACK_SEC` - Historical data window in seconds (default: 300)
- `DEBUG_TIMING` - Enable timing output: `true` or `false` (default: true)

**Centralized Config:**
- `config/poly.json` - Single config file for all scripts (loaded automatically)

Config loading priority:
1. CLI arguments (highest)
2. `POLY_CONFIG_PATH` environment variable
3. `config/poly.json` (project root)
4. Environment variables (lowest)

## API Reference

### Polymarket APIs
| API | Base URL | Auth |
|-----|----------|------|
| Gamma API | `https://gamma-api.polymarket.com` | No |
| CLOB API | `https://clob.polymarket.com` | No (read) |
| Data API | `https://data-api.polymarket.com` | No |
| WebSocket | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | No |

**WebSocket subscription:**
```json
{"assets_ids": ["<token_id>", ...], "type": "market"}
```

### Binance API
- Base URL: `https://data-api.binance.vision/api/v3`
- `GET /ticker/price` - Current prices

## Development
```bash
# Setup
./scripts/setup.sh
source .venv/bin/activate

# Run tests
pytest tests/ -v

# Run collector locally
PYTHONPATH=src python scripts/cloudrun_collector.py

# Test Polymarket API
PYTHONPATH=src python scripts/test_polymarket_api.py --wallet 0x...

# Test WebSocket feed
PYTHONPATH=src python scripts/test_polymarket_ws.py --duration 10

# Test market feed daemon
PYTHONPATH=src python scripts/test_market_feed.py --duration 10

# Run trading bot (uses config/poly.json automatically)
PYTHONPATH=src python scripts/run_trading_bot.py

# Run trading bot with CLI overrides
PYTHONPATH=src python scripts/run_trading_bot.py --asset eth --interval 5

# Benchmark API latency
PYTHONPATH=src python scripts/benchmark_polymarket_apis.py
```
