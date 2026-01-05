"""Configuration management for Polymarket client."""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """Configuration for Polymarket API access."""

    api_key: str
    api_secret: str
    passphrase: str
    private_key: str
    chain_id: int = 137  # Polygon mainnet
    host: str = "https://clob.polymarket.com"
    gamma_host: str = "https://gamma-api.polymarket.com"

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        api_key = os.getenv("POLYMARKET_API_KEY")
        api_secret = os.getenv("POLYMARKET_SECRET")
        passphrase = os.getenv("POLYMARKET_PASSPHRASE")
        private_key = os.getenv("PRIVATE_KEY")

        if not all([api_key, api_secret, passphrase, private_key]):
            raise ValueError(
                "Missing required environment variables. "
                "Ensure POLYMARKET_API_KEY, POLYMARKET_SECRET, "
                "POLYMARKET_PASSPHRASE, and PRIVATE_KEY are set."
            )

        return cls(
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            private_key=private_key,
            chain_id=int(os.getenv("CHAIN_ID", "137")),
            host=os.getenv("POLYMARKET_HOST", "https://clob.polymarket.com"),
            gamma_host=os.getenv("GAMMA_HOST", "https://gamma-api.polymarket.com"),
        )

    @classmethod
    def from_env_optional(cls) -> Optional["Config"]:
        """Load configuration from environment, returning None if not available."""
        try:
            return cls.from_env()
        except ValueError:
            return None
