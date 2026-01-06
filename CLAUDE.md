# Polymarket Trading Platform

## Project Overview
A Python-based trading platform for interacting with Polymarket prediction markets.

## Tech Stack
- **Language**: Python 3.11+
- **APIs**: Polymarket CLOB API (`py-clob-client`), Gamma Markets API
- **Blockchain**: web3.py, eth-account for Polygon network
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
│   ├── market_snapshot.py    # Orderbook snapshots for markets
│   ├── telegram_notifier.py  # Telegram notification alerts
│   └── sqlite_writer.py      # SQLite database storage
├── tests/
│   └── test_client.py        # Unit tests for client and models
├── scripts/
│   ├── setup.sh              # Cross-platform setup (Mac/Ubuntu)
│   ├── run.py                # Application entry point
│   ├── test_btc_15m.py       # Test BTC 15m predictions
│   ├── test_binance.py       # Test Binance price fetching
│   ├── test_telegram.py      # Test Telegram notifications
│   ├── test_market_snapshot.py  # Test market snapshots
│   ├── test_sqlite.py        # Test SQLite writer
│   └── collect_snapshots.py  # Continuous data collector
├── config/                   # Config files (gitignored)
│   └── telegram.json         # Telegram bot credentials
├── requirements.txt          # Python dependencies
├── pyproject.toml            # Project config, tool settings
├── Dockerfile                # Multi-stage build (prod/dev)
├── docker-compose.yml        # Container orchestration
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

### `sqlite_writer.py` - Database Storage
- `SQLiteWriter`: Write/query market data to SQLite
- Tables: `market_snapshots`, `opportunities`, `simulated_trades`, `equity_curve`
- `write_snapshot_from_obj(snapshot)`: Store MarketSnapshot directly
- `write_opportunity()`, `write_trade()`, `write_equity()`: Store trading data
- `get_snapshots()`, `get_trades()`, `get_equity_curve()`: Query methods
- Default DB: `poly_data.db` in project root (gitignored)

### `scripts/collect_snapshots.py` - Data Collector
- Continuous market snapshot collector
- Configurable interval: `--interval SECONDS` (default: 5)
- Custom database: `--db PATH`
- Adjusts sleep time based on query duration
- Graceful shutdown with Ctrl+C

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
Required (see `.env.example`):
- `POLYMARKET_API_KEY` - API key from Polymarket
- `POLYMARKET_SECRET` - API secret
- `POLYMARKET_PASSPHRASE` - API passphrase
- `PRIVATE_KEY` - Ethereum private key (no 0x prefix)

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
- Base URL: `https://api.binance.com/api/v3`
- `GET /ticker/price` - Current prices
- `GET /ticker/24hr` - 24h statistics
- `GET /klines` - Candlestick/OHLCV data

### BTC 15m Market Slug Pattern
```
btc-updown-15m-{unix_timestamp}
```
- Timestamp marks the start of each 15-minute slot
- Intervals: 900 seconds (15 minutes)
- Example: `btc-updown-15m-1767646800` → resolves at timestamp + 900
