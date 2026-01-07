"""Centralized project configuration loader.

All scripts in the project should use this module to load configuration.

Usage:
    from poly.project_config import load_config, get_bigtable_config, get_trading_bot_config

    # Load full config
    config = load_config()

    # Get specific sections
    bigtable = get_bigtable_config()
    trading = get_trading_bot_config()

Config file locations (in order of priority):
    1. Path specified in POLY_CONFIG_PATH environment variable
    2. config/poly.json (project root)
    3. ~/.config/poly/config.json (user home)
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any

# Default config file locations
CONFIG_PATHS = [
    Path(__file__).parent.parent.parent / "config" / "poly.json",
    Path.home() / ".config" / "poly" / "config.json",
]


@dataclass
class BigtableConfig:
    """Bigtable connection configuration."""
    project_id: str
    instance_id: str

    @classmethod
    def from_dict(cls, data: dict) -> "BigtableConfig":
        return cls(
            project_id=data.get("project_id", ""),
            instance_id=data.get("instance_id", ""),
        )


@dataclass
class PolymarketConfig:
    """Polymarket API configuration."""
    wallet_address: Optional[str] = None
    private_key: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "PolymarketConfig":
        return cls(
            wallet_address=data.get("wallet_address"),
            private_key=data.get("private_key"),
        )


@dataclass
class CollectorConfig:
    """Data collector configuration."""
    interval_sec: int = 5
    assets: list[str] = None
    horizons: dict[str, list[str]] = None

    def __post_init__(self):
        if self.assets is None:
            self.assets = ["btc", "eth"]
        if self.horizons is None:
            self.horizons = {
                "btc": ["15m", "1h", "4h", "d1"],
                "eth": ["15m", "1h", "4h"],
            }

    @classmethod
    def from_dict(cls, data: dict) -> "CollectorConfig":
        return cls(
            interval_sec=data.get("interval_sec", 5),
            assets=data.get("assets", ["btc", "eth"]),
            horizons=data.get("horizons", {}),
        )


@dataclass
class TelegramConfig:
    """Telegram notification configuration."""
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "TelegramConfig":
        return cls(
            bot_token=data.get("bot_token"),
            chat_id=data.get("chat_id"),
        )


class ProjectConfig:
    """Main project configuration container."""

    def __init__(self, data: dict):
        self._data = data
        self.pythonpath = data.get("pythonpath", "src")
        self.bigtable = BigtableConfig.from_dict(data.get("bigtable", {}))
        self.polymarket = PolymarketConfig.from_dict(data.get("polymarket", {}))
        self.collector = CollectorConfig.from_dict(data.get("collector", {}))
        self.telegram = TelegramConfig.from_dict(data.get("telegram", {}))
        self._trading_bot_data = data.get("trading_bot", {})

    def get(self, key: str, default: Any = None) -> Any:
        """Get a raw config value by key path (e.g., 'bigtable.project_id')."""
        keys = key.split(".")
        value = self._data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default

    def get_trading_bot_section(self) -> dict:
        """Get raw trading_bot section for TradingBotConfig."""
        return self._trading_bot_data

    def to_env_exports(self) -> str:
        """Generate shell export commands for all config values."""
        exports = []
        exports.append(f'export PYTHONPATH="{self.pythonpath}"')
        exports.append(f'export BIGTABLE_PROJECT_ID="{self.bigtable.project_id}"')
        exports.append(f'export BIGTABLE_INSTANCE_ID="{self.bigtable.instance_id}"')
        if self.polymarket.wallet_address:
            exports.append(f'export POLYMARKET_WALLET_ADDRESS="{self.polymarket.wallet_address}"')
        if self.telegram.bot_token:
            exports.append(f'export TELEGRAM_BOT_TOKEN="{self.telegram.bot_token}"')
        if self.telegram.chat_id:
            exports.append(f'export TELEGRAM_CHAT_ID="{self.telegram.chat_id}"')
        return "\n".join(exports)


_config_cache: Optional[ProjectConfig] = None


def load_config(path: Optional[str | Path] = None, reload: bool = False) -> ProjectConfig:
    """Load project configuration from JSON file.

    Args:
        path: Explicit config file path. If None, searches default locations.
        reload: Force reload even if cached.

    Returns:
        ProjectConfig instance.

    Raises:
        FileNotFoundError: If no config file found.
    """
    global _config_cache

    if _config_cache is not None and not reload and path is None:
        return _config_cache

    # Determine config path
    config_path = None

    if path:
        config_path = Path(path)
    elif os.getenv("POLY_CONFIG_PATH"):
        config_path = Path(os.getenv("POLY_CONFIG_PATH"))
    else:
        for default_path in CONFIG_PATHS:
            if default_path.exists():
                config_path = default_path
                break

    if config_path is None or not config_path.exists():
        # Return default config if no file found
        _config_cache = ProjectConfig({})
        return _config_cache

    with open(config_path) as f:
        data = json.load(f)

    _config_cache = ProjectConfig(data)
    return _config_cache


def get_bigtable_config(path: Optional[str | Path] = None) -> BigtableConfig:
    """Get Bigtable configuration."""
    return load_config(path).bigtable


def get_polymarket_config(path: Optional[str | Path] = None) -> PolymarketConfig:
    """Get Polymarket API configuration."""
    return load_config(path).polymarket


def get_collector_config(path: Optional[str | Path] = None) -> CollectorConfig:
    """Get collector configuration."""
    return load_config(path).collector


def get_telegram_config(path: Optional[str | Path] = None) -> TelegramConfig:
    """Get Telegram configuration."""
    return load_config(path).telegram


def get_config_value(key: str, default: Any = None, path: Optional[str | Path] = None) -> Any:
    """Get a specific config value by key path."""
    return load_config(path).get(key, default)
