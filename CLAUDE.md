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
│   ├── binance_price.py      # Binance price data (REST)
│   ├── bigtable_writer.py    # Google Cloud Bigtable storage
│   ├── sqlite_writer.py      # SQLite database storage
│   ├── db_writer.py          # Database backend abstraction
│   ├── gamma.py              # Gamma API for public event data
│   ├── client.py             # PolymarketClient - API interactions
│   ├── config.py             # Config class with env loading
│   ├── models.py             # Market, Order, Position models
│   ├── trading.py            # TradingEngine for strategy execution
│   └── utils.py              # Helpers (retry, formatting)
├── scripts/
│   ├── cloudrun_collector.py # GCE data collector (BTC + ETH)
│   ├── query_bigtable.py     # Query Bigtable data
│   ├── collect_snapshots.py  # Local data collector (SQLite)
│   ├── setup.sh              # Dev environment setup
│   └── gce_setup.sh          # GCE instance setup
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

## API Reference

### Polymarket APIs
| API | Base URL | Auth |
|-----|----------|------|
| Gamma API | `https://gamma-api.polymarket.com` | No |
| CLOB API | `https://clob.polymarket.com` | No (read) |

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
```
