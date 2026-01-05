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

## Project Structure
```
poly/
├── src/poly/
│   ├── __init__.py       # Package exports
│   ├── client.py         # PolymarketClient - API interactions
│   ├── config.py         # Config class with env loading
│   ├── models.py         # Market, Order, Position, Trade models
│   ├── trading.py        # TradingEngine for strategy execution
│   └── utils.py          # Helpers (retry, formatting, EV calc)
├── tests/
│   └── test_client.py    # Unit tests for client and models
├── scripts/
│   ├── setup.sh          # Cross-platform setup (Mac/Ubuntu)
│   └── run.py            # Application entry point
├── requirements.txt      # Python dependencies
├── pyproject.toml        # Project config, tool settings
├── Dockerfile            # Multi-stage build (prod/dev)
├── docker-compose.yml    # Container orchestration
├── .env.example          # Environment variable template
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

## Development Commands
```bash
# Setup (Mac or Ubuntu)
./scripts/setup.sh

# Activate environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

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
