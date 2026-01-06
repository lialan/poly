# Polymarket Trading Platform

## Project Overview
A Python-based trading platform for interacting with Polymarket prediction markets.

## Tech Stack
- **Language**: Python 3.11+
- **APIs**: Polymarket CLOB API (`py-clob-client`), Gamma Markets API
- **Blockchain**: web3.py, eth-account for Polygon network
- **Price Feeds**: Chainlink on-chain oracles (Ethereum mainnet)
- **Database**: Google Cloud Bigtable, SQLite (local)
- **Cloud**: Google Cloud Run, Cloud Build, Artifact Registry
- **Async**: asyncio, aiohttp
- **Testing**: pytest, pytest-asyncio
- **Linting**: ruff, black, mypy
- **Package Manager**: uv (fast Python package installer)

## Project Structure
```
poly/
├── src/poly/
│   ├── __init__.py           # Package exports
│   ├── client.py             # PolymarketClient - API interactions
│   ├── config.py             # Config class with env loading
│   ├── models.py             # Market, Order, Position, Trade models
│   ├── trading.py            # TradingEngine for strategy execution
│   ├── utils.py              # Helpers (retry, formatting, EV calc)
│   ├── gamma.py              # Gamma API for public event data
│   ├── btc_15m.py            # BTC 15-minute prediction markets
│   ├── binance_price.py      # Binance price and kline data
│   ├── chainlink_price.py    # Chainlink on-chain price feeds
│   ├── market_snapshot.py    # Orderbook snapshots for markets
│   ├── telegram_notifier.py  # Telegram notification alerts
│   ├── sqlite_writer.py      # SQLite database storage
│   ├── bigtable_writer.py    # Google Cloud Bigtable storage
│   └── db_writer.py          # Database backend abstraction
├── tests/
│   └── test_client.py        # Unit tests for client and models
├── scripts/
│   ├── setup.sh              # Cross-platform setup (Mac/Ubuntu)
│   ├── run.py                # Application entry point
│   ├── cloudrun_collector.py # Cloud Run collector with health endpoint
│   ├── collect_snapshots.py  # Local data collector (SQLite)
│   ├── test_btc_15m.py       # Test BTC 15m predictions
│   ├── test_binance.py       # Test Binance price fetching
│   ├── test_telegram.py      # Test Telegram notifications
│   ├── test_market_snapshot.py  # Test market snapshots
│   └── test_sqlite.py        # Test SQLite writer
├── config/                   # Config files (gitignored)
│   └── telegram.json         # Telegram bot credentials
├── requirements.txt          # Python dependencies
├── pyproject.toml            # Project config, tool settings
├── Dockerfile                # Multi-stage build (prod/dev/cloudrun)
├── docker-compose.yml        # Container orchestration
├── cloudbuild.yaml           # Google Cloud Build config
├── DEPLOYMENT.md             # Cloud Run deployment guide
├── .env.example              # Environment variable template
└── .gitignore
```

## Module Overview

### `client.py` - PolymarketClient
- Async context manager for API lifecycle
- Market fetching (`get_markets`, `get_market`)
- Orderbook and price queries
- Order placement and cancellation
- Position and open order retrieval

### `trading.py` - TradingEngine
- Strategy registration and execution
- Market order with slippage protection
- Limit order placement
- Batch order cancellation
- Portfolio value calculation
- Market monitoring with callbacks

### `models.py` - Data Models
- `Market`: Prediction market with tokens
- `Order`: Trading order with status tracking
- `Position`: Holdings with P&L calculation
- `Token`, `Trade`: Supporting types
- Enums: `Side`, `OrderStatus`, `OrderType`

### `utils.py` - Utilities
- Price/size rounding
- Probability conversion
- Implied probability and vig calculation
- Expected value computation
- Async retry with exponential backoff

### `gamma.py` - Gamma API (No Auth Required)
- `fetch_event_from_url()`: Fetch event data from Polymarket URL
- `fetch_event_by_slug()`: Fetch event by slug name
- `search_events()`: Search events by query
- Data models: `Event`, `SubMarket`, `OutcomeToken`
- Parses multi-outcome markets with token IDs and prices

### `btc_15m.py` - BTC 15-Minute Predictions
- `BTC15mPrediction`: Dataclass with slug, prices, token IDs, status
- `fetch_current_and_upcoming(count=5)`: Get current + next N predictions
- `fetch_btc_15m_prediction(timestamp)`: Fetch specific 15m slot
- Slug pattern: `btc-updown-15m-{unix_timestamp}` (900-second intervals)
- Properties: `is_live`, `time_remaining`, `up_probability`, `down_probability`

### `binance_price.py` - Binance Price Data
- `get_btc_price()`, `get_eth_price()`: Current spot prices
- `get_prices(symbols)`: Batch price queries (concurrent)
- `get_btc_stats()`, `get_eth_stats()`: 24h statistics
- `get_klines(symbol, interval, limit)`: OHLCV candlestick data
- `get_btc_15m_kline()`, `get_eth_15m_kline()`: Convenience functions
- Data models: `TickerPrice`, `TickerStats`, `Kline`
- Base URL: `https://data-api.binance.vision/api/v3` (Cloud Run compatible)

### `chainlink_price.py` - Chainlink On-Chain Price Feeds
- `get_btc_price()`: BTC/USD from Chainlink oracle
- `get_eth_price()`: ETH/USD from Chainlink oracle
- `get_prices()`: Both BTC and ETH prices concurrently
- Uses Ethereum mainnet Chainlink aggregator contracts
- Feed addresses:
  - BTC/USD: `0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c`
  - ETH/USD: `0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419`
- RPC endpoints: eth.llamarpc.com, ethereum.publicnode.com, 1rpc.io/eth

### `market_snapshot.py` - Orderbook Snapshots
- `MarketSnapshot`: Dataclass with bid/ask prices, depth, volume
- `fetch_market_snapshot(market_id)`: Get snapshot by timestamp or slug
- `fetch_current_snapshot()`: Get snapshot for current 15m slot
- `fetch_orderbook(session, token_id)`: Raw orderbook from CLOB API
- Fields: `best_yes_bid/ask`, `best_no_bid/ask`, `depth_yes`, `depth_no`
- Properties: `yes_mid`, `no_mid`, `yes_spread`, `no_spread`
- Uses public CLOB API: `https://clob.polymarket.com/book`

### `telegram_notifier.py` - Telegram Alerts
- `TelegramNotifier`: Send alerts with rate limiting and retries
- `TelegramConfig.load()`: Auto-detect config (JSON file or env vars)
- `send_btc_15m_alert()`: BTC 15m prediction alerts
- `send_price_alert()`: Price movement alerts
- `send_prediction_alert()`: Generic prediction alerts
- Config: `config/telegram.json` or `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` env vars

### `sqlite_writer.py` - SQLite Storage (Local)
- `SQLiteWriter`: Write/query market data to SQLite
- Tables: `market_snapshots`, `opportunities`, `simulated_trades`, `equity_curve`
- `write_snapshot_from_obj(snapshot)`: Store MarketSnapshot directly
- `write_opportunity()`, `write_trade()`, `write_equity()`: Store trading data
- `get_snapshots()`, `get_trades()`, `get_equity_curve()`: Query methods
- Default DB: `poly_data.db` in project root (gitignored)

### `bigtable_writer.py` - Google Cloud Bigtable Storage
- `BigtableWriter`: Write market data to Bigtable
- Tables: `market_snapshots`, `opportunities`, `simulated_trades`, `equity_curve`
- `write_snapshot_from_obj(snapshot, horizon, btc_price)`: Store snapshot with price
- `ensure_tables()`: Create tables and column families if needed
- Row key format: `{inverted_timestamp}#{market_id}` (newest first)
- Column family: `data` with JSON-encoded values

### `db_writer.py` - Database Backend Abstraction
- `get_db_writer(backend, project_id, instance_id)`: Factory function
- Supported backends: `sqlite`, `bigtable`
- Returns appropriate writer instance based on backend type
- Environment variables: `DB_BACKEND`, `BIGTABLE_PROJECT_ID`, `BIGTABLE_INSTANCE_ID`

### `scripts/collect_snapshots.py` - Local Data Collector
- Continuous market snapshot collector (SQLite backend)
- Configurable interval: `--interval SECONDS` (default: 5)
- Custom database: `--db PATH`
- Adjusts sleep time based on query duration
- Graceful shutdown with Ctrl+C

### `scripts/cloudrun_collector.py` - Cloud Run Collector
- Cloud Run compatible collector with HTTP health endpoint
- Concurrent fetching: Polymarket snapshots + Chainlink BTC price
- Health server on configurable port (default: 8080)
- Environment variables:
  - `PORT`: Health check port (set by Cloud Run)
  - `COLLECT_INTERVAL`: Seconds between snapshots (default: 5)
  - `DB_BACKEND`: Storage backend (default: bigtable)
  - `BIGTABLE_PROJECT_ID`: GCP project ID
  - `BIGTABLE_INSTANCE_ID`: Bigtable instance ID

## Development Commands
```bash
# Setup (Mac or Ubuntu) - uses uv for fast package management
./scripts/setup.sh

# Activate virtual environment
source .venv/bin/activate

# Deactivate when done
deactivate

# Install dependencies (with uv)
uv pip install -r requirements.txt

# Add a new package
uv pip install <package>

# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=poly --cov-report=term-missing

# Lint
ruff check src/
black --check src/

# Type check
mypy src/

# Run the application
python scripts/run.py
```

## Environment Variables
Required for trading (see `.env.example`):
- `POLYMARKET_API_KEY` - API key from Polymarket
- `POLYMARKET_SECRET` - API secret
- `POLYMARKET_PASSPHRASE` - API passphrase
- `PRIVATE_KEY` - Ethereum private key (no 0x prefix)

Cloud Run / Bigtable:
- `DB_BACKEND` - Storage backend: `sqlite` or `bigtable`
- `BIGTABLE_PROJECT_ID` - GCP project ID
- `BIGTABLE_INSTANCE_ID` - Bigtable instance ID
- `COLLECT_INTERVAL` - Seconds between snapshots (default: 5)

Optional:
- `CHAIN_ID` - Network ID (default: 137 for Polygon)
- `POLYMARKET_HOST` - CLOB API host
- `GAMMA_HOST` - Gamma API host
- `LOG_LEVEL` - Logging level
- `TELEGRAM_BOT_TOKEN` - Telegram bot token (or use `config/telegram.json`)
- `TELEGRAM_CHAT_ID` - Telegram chat ID for alerts
- `TELEGRAM_TIMEZONE` - Timezone for alert timestamps (default: UTC)

## Docker
```bash
# Build production image
docker build -t poly .

# Run with env file
docker run --env-file .env poly

# Docker Compose
docker-compose up poly           # Production
docker-compose --profile dev up  # Development
docker-compose --profile test up # Run tests
```

## Code Style
- Type hints for all function signatures
- Async/await for I/O operations
- Docstrings for public functions
- Single-purpose modules
- Decimal for financial calculations

## Testing Guidelines
- Test all public interfaces
- Use pytest fixtures for setup
- Mock external API calls
- Test edge cases (empty orderbooks, missing data)

## API Endpoints Reference

### Polymarket APIs
| API | Base URL | Auth Required |
|-----|----------|---------------|
| Gamma API | `https://gamma-api.polymarket.com` | No |
| CLOB API (read) | `https://clob.polymarket.com` | No |
| CLOB API (trade) | `https://clob.polymarket.com` | Yes (L2 Header) |

Key endpoints:
- `GET /events?slug={slug}` - Gamma API, fetch event by slug
- `GET /book?token_id={id}` - CLOB API, orderbook data
- `GET /prices-history?market={id}` - CLOB API, price history

### Binance API
- Base URL: `https://data-api.binance.vision/api/v3` (Cloud Run compatible)
- `GET /ticker/price` - Current prices
- `GET /ticker/24hr` - 24h statistics
- `GET /klines` - Candlestick/OHLCV data

### Chainlink Price Feeds (Ethereum Mainnet)
- BTC/USD: `0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c`
- ETH/USD: `0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419`
- Uses `latestRoundData()` from Aggregator V3 interface

### BTC 15m Market Slug Pattern
```
btc-updown-15m-{unix_timestamp}
```
- Timestamp marks the start of each 15-minute slot
- Intervals: 900 seconds (15 minutes)
- Example: `btc-updown-15m-1767646800` → resolves at timestamp + 900
