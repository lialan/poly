"""Chainlink price feed utilities using on-chain data.

Uses Chainlink's decentralized price feeds on Ethereum mainnet.
BTC/USD: 0xf4030086522a5beea4988f8ca5b36dbc97bee88c
"""

import asyncio
from decimal import Decimal
from typing import Optional

from web3 import Web3

# Public Ethereum RPC endpoints (ordered by reliability)
ETH_RPC_ENDPOINTS = [
    "https://eth.llamarpc.com",
    "https://ethereum.publicnode.com",
    "https://1rpc.io/eth",
    "https://eth.drpc.org",
]

# Chainlink Price Feed addresses (Ethereum mainnet)
BTC_USD_FEED = "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c"
ETH_USD_FEED = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"

# Chainlink Aggregator V3 ABI (minimal - just latestRoundData)
AGGREGATOR_ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
]


def _get_web3() -> Optional[Web3]:
    """Get a connected Web3 instance."""
    for rpc_url in ETH_RPC_ENDPOINTS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
            if w3.is_connected():
                return w3
        except Exception:
            continue
    return None


def _get_price_sync(feed_address: str) -> Optional[Decimal]:
    """Synchronously get price from Chainlink feed."""
    w3 = _get_web3()
    if not w3:
        return None

    try:
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(feed_address),
            abi=AGGREGATOR_ABI,
        )

        # Get decimals and latest price
        decimals = contract.functions.decimals().call()
        round_data = contract.functions.latestRoundData().call()

        # round_data[1] is the answer (price)
        price = Decimal(round_data[1]) / Decimal(10 ** decimals)
        return price
    except Exception:
        return None


async def get_btc_price() -> Optional[Decimal]:
    """Get current BTC/USD price from Chainlink."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_price_sync, BTC_USD_FEED)


async def get_eth_price() -> Optional[Decimal]:
    """Get current ETH/USD price from Chainlink."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_price_sync, ETH_USD_FEED)


async def get_prices() -> dict[str, Optional[Decimal]]:
    """Get BTC and ETH prices concurrently."""
    btc, eth = await asyncio.gather(
        get_btc_price(),
        get_eth_price(),
    )
    return {"BTC": btc, "ETH": eth}
