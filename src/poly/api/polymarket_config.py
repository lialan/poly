"""
Polymarket Configuration Module

Handles loading and validation of Polymarket API credentials and wallet settings.
Configuration can be loaded from:
1. Google Secret Manager (production)
2. Environment variables (local testing)
3. JSON file (local development)
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class SecretManager:
    """Google Secret Manager client wrapper.

    Provides methods to fetch secrets from GCP Secret Manager with
    fallback to environment variables for local testing.
    """

    def __init__(self, project_id: Optional[str] = None):
        """Initialize Secret Manager client.

        Args:
            project_id: GCP project ID. If None, uses GOOGLE_CLOUD_PROJECT env var.
        """
        self.project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT")
        self._client = None

    def _get_client(self):
        """Lazy-load the Secret Manager client."""
        if self._client is None:
            try:
                from google.cloud import secretmanager
                self._client = secretmanager.SecretManagerServiceClient()
            except ImportError:
                raise ImportError(
                    "google-cloud-secret-manager is required. "
                    "Install with: pip install google-cloud-secret-manager"
                )
        return self._client

    def get_secret(
        self,
        secret_id: str,
        version: str = "latest",
        env_fallback: Optional[str] = None,
    ) -> Optional[str]:
        """Fetch a secret from Secret Manager or environment variable.

        Args:
            secret_id: The secret ID in Secret Manager
            version: Secret version (default: "latest")
            env_fallback: Environment variable name to use as fallback

        Returns:
            Secret value or None if not found

        Priority:
            1. Environment variable (if set) - allows local override
            2. Google Secret Manager
            3. None
        """
        # Check environment variable first (for local testing)
        if env_fallback:
            env_value = os.environ.get(env_fallback)
            if env_value:
                return env_value

        # Try Secret Manager
        if not self.project_id:
            return None

        try:
            client = self._get_client()
            name = f"projects/{self.project_id}/secrets/{secret_id}/versions/{version}"
            response = client.access_secret_version(request={"name": name})
            return response.payload.data.decode("UTF-8")
        except Exception:
            # Secret not found or access error
            return None

    def secret_exists(self, secret_id: str) -> bool:
        """Check if a secret exists in Secret Manager.

        Args:
            secret_id: The secret ID to check

        Returns:
            True if secret exists and is accessible
        """
        if not self.project_id:
            return False

        try:
            client = self._get_client()
            name = f"projects/{self.project_id}/secrets/{secret_id}"
            client.get_secret(request={"name": name})
            return True
        except Exception:
            return False


class SignerType:
    """Type of signer to use for trading."""
    LOCAL = "local"   # py-clob-client with local private key
    KMS = "kms"       # Google Cloud KMS
    EOA = "eoa"       # eth_account with local key (no py-clob-client)


@dataclass
class PolymarketConfig:
    """Configuration for Polymarket API interactions.

    Attributes:
        wallet_address: The user's Polygon wallet address (0x-prefixed)
        private_key: Private key for signing transactions (optional, for trading)
        proxy_wallet: Proxy wallet address if using smart wallet (optional)
        chain_id: Polygon chain ID (default: 137 for mainnet)
        signature_type: Signing method (0=EOA, 1=Magic, 2=Browser proxy)
        clob_api_url: CLOB API base URL
        data_api_url: Data API base URL
        gamma_api_url: Gamma API base URL
        signer_type: Type of signer to use (local, kms, or eoa)
        kms_key_path: Full KMS key path (for KMS signer)
    """

    wallet_address: str
    private_key: Optional[str] = None
    proxy_wallet: Optional[str] = None
    chain_id: int = 137
    signature_type: int = 0
    clob_api_url: str = "https://clob.polymarket.com"
    data_api_url: str = "https://data-api.polymarket.com"
    gamma_api_url: str = "https://gamma-api.polymarket.com"

    # Signer configuration
    signer_type: str = SignerType.LOCAL
    kms_key_path: Optional[str] = None

    # Secret Manager settings (class-level defaults)
    SECRET_WALLET_ADDRESS = "polymarket-wallet-address"
    SECRET_PRIVATE_KEY = "polymarket-private-key"
    SECRET_PROXY_WALLET = "polymarket-proxy-wallet"
    SECRET_KMS_KEY_PATH = "polymarket-kms-key-path"

    def __post_init__(self):
        """Validate configuration after initialization."""
        if not self.wallet_address:
            raise ValueError("wallet_address is required")

        if not self.wallet_address.startswith("0x"):
            raise ValueError("wallet_address must be 0x-prefixed")

        if len(self.wallet_address) != 42:
            raise ValueError("wallet_address must be 42 characters (0x + 40 hex)")

        # Normalize to lowercase
        self.wallet_address = self.wallet_address.lower()

        if self.proxy_wallet:
            self.proxy_wallet = self.proxy_wallet.lower()

    @classmethod
    def from_secret_manager(
        cls,
        project_id: Optional[str] = None,
        use_env_fallback: bool = True,
    ) -> "PolymarketConfig":
        """Load configuration from Google Secret Manager.

        Secret names (configurable via class attributes):
            - polymarket-wallet-address: Wallet address (required)
            - polymarket-private-key: Private key (optional)
            - polymarket-proxy-wallet: Proxy wallet (optional)

        Args:
            project_id: GCP project ID. If None, uses GOOGLE_CLOUD_PROJECT env var.
            use_env_fallback: If True, check environment variables first.
                             This allows local testing with env vars while
                             using Secret Manager in production.

        Environment variable fallbacks (when use_env_fallback=True):
            POLYMARKET_WALLET_ADDRESS
            POLYMARKET_PRIVATE_KEY
            POLYMARKET_PROXY_WALLET
            POLYMARKET_CHAIN_ID
            POLYMARKET_SIGNATURE_TYPE

        Returns:
            PolymarketConfig instance

        Raises:
            ValueError: If wallet_address is not found
        """
        sm = SecretManager(project_id)

        # Get wallet address (required)
        wallet_address = sm.get_secret(
            cls.SECRET_WALLET_ADDRESS,
            env_fallback="POLYMARKET_WALLET_ADDRESS" if use_env_fallback else None,
        )

        if not wallet_address:
            raise ValueError(
                f"wallet_address not found. Set secret '{cls.SECRET_WALLET_ADDRESS}' "
                "in Secret Manager or POLYMARKET_WALLET_ADDRESS environment variable."
            )

        # Get optional secrets
        private_key = sm.get_secret(
            cls.SECRET_PRIVATE_KEY,
            env_fallback="POLYMARKET_PRIVATE_KEY" if use_env_fallback else None,
        )

        proxy_wallet = sm.get_secret(
            cls.SECRET_PROXY_WALLET,
            env_fallback="POLYMARKET_PROXY_WALLET" if use_env_fallback else None,
        )

        kms_key_path = sm.get_secret(
            cls.SECRET_KMS_KEY_PATH,
            env_fallback="POLYMARKET_KMS_KEY_PATH" if use_env_fallback else None,
        )

        # Get non-secret config from env vars
        chain_id = int(os.environ.get("POLYMARKET_CHAIN_ID", "137"))
        signature_type = int(os.environ.get("POLYMARKET_SIGNATURE_TYPE", "0"))

        # Determine signer type
        signer_type = os.environ.get("POLYMARKET_SIGNER_TYPE", SignerType.LOCAL)
        if kms_key_path and signer_type == SignerType.LOCAL:
            # Auto-detect KMS if key path is provided
            signer_type = SignerType.KMS

        return cls(
            wallet_address=wallet_address,
            private_key=private_key,
            proxy_wallet=proxy_wallet,
            chain_id=chain_id,
            signature_type=signature_type,
            signer_type=signer_type,
            kms_key_path=kms_key_path,
        )

    @classmethod
    def from_json(cls, path: str) -> "PolymarketConfig":
        """Load configuration from a JSON file.

        Args:
            path: Path to JSON config file

        Returns:
            PolymarketConfig instance

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config is invalid
        """
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(config_path) as f:
            data = json.load(f)

        # Determine signer type
        signer_type = data.get("signer_type", SignerType.LOCAL)
        kms_key_path = data.get("kms_key_path")
        if kms_key_path and signer_type == SignerType.LOCAL:
            signer_type = SignerType.KMS

        return cls(
            wallet_address=data.get("wallet_address", ""),
            private_key=data.get("private_key"),
            proxy_wallet=data.get("proxy_wallet"),
            chain_id=data.get("chain_id", 137),
            signature_type=data.get("signature_type", 0),
            clob_api_url=data.get("clob_api_url", "https://clob.polymarket.com"),
            data_api_url=data.get("data_api_url", "https://data-api.polymarket.com"),
            gamma_api_url=data.get("gamma_api_url", "https://gamma-api.polymarket.com"),
            signer_type=signer_type,
            kms_key_path=kms_key_path,
        )

    @classmethod
    def from_env(cls) -> "PolymarketConfig":
        """Load configuration from environment variables only.

        Environment variables:
            POLYMARKET_WALLET_ADDRESS: Wallet address (required)
            POLYMARKET_PRIVATE_KEY: Private key (optional)
            POLYMARKET_PROXY_WALLET: Proxy wallet address (optional)
            POLYMARKET_CHAIN_ID: Chain ID (default: 137)
            POLYMARKET_SIGNATURE_TYPE: Signature type (default: 0)
            POLYMARKET_SIGNER_TYPE: Signer type (local, kms, or eoa)
            POLYMARKET_KMS_KEY_PATH: Full KMS key path (for KMS signer)

        Returns:
            PolymarketConfig instance

        Raises:
            ValueError: If required env vars are missing
        """
        wallet_address = os.environ.get("POLYMARKET_WALLET_ADDRESS", "")
        if not wallet_address:
            raise ValueError("POLYMARKET_WALLET_ADDRESS environment variable is required")

        kms_key_path = os.environ.get("POLYMARKET_KMS_KEY_PATH")
        signer_type = os.environ.get("POLYMARKET_SIGNER_TYPE", SignerType.LOCAL)
        if kms_key_path and signer_type == SignerType.LOCAL:
            signer_type = SignerType.KMS

        return cls(
            wallet_address=wallet_address,
            private_key=os.environ.get("POLYMARKET_PRIVATE_KEY"),
            proxy_wallet=os.environ.get("POLYMARKET_PROXY_WALLET"),
            chain_id=int(os.environ.get("POLYMARKET_CHAIN_ID", "137")),
            signature_type=int(os.environ.get("POLYMARKET_SIGNATURE_TYPE", "0")),
            signer_type=signer_type,
            kms_key_path=kms_key_path,
        )

    @classmethod
    def load(
        cls,
        config_path: Optional[str] = None,
        project_id: Optional[str] = None,
        prefer_secret_manager: bool = True,
    ) -> "PolymarketConfig":
        """Load configuration with automatic source detection.

        Loading priority:
            1. Explicit JSON file path (if provided)
            2. Default JSON file locations (if exist)
            3. Google Secret Manager with env fallback (if prefer_secret_manager=True)
            4. Environment variables only

        Args:
            config_path: Optional path to JSON config file
            project_id: GCP project ID for Secret Manager
            prefer_secret_manager: If True, try Secret Manager before pure env vars

        Returns:
            PolymarketConfig instance
        """
        # Try explicit path first
        if config_path:
            return cls.from_json(config_path)

        # Try default config locations
        default_paths = [
            Path("config/polymarket.json"),
            Path.home() / ".config" / "polymarket" / "config.json",
        ]

        for path in default_paths:
            if path.exists():
                return cls.from_json(str(path))

        # Try Secret Manager with env fallback
        if prefer_secret_manager:
            try:
                return cls.from_secret_manager(
                    project_id=project_id,
                    use_env_fallback=True,
                )
            except (ImportError, ValueError):
                # Secret Manager not available or secrets not found
                pass

        # Fall back to environment variables only
        return cls.from_env()

    @property
    def has_trading_credentials(self) -> bool:
        """Check if trading credentials are available.

        Returns True if either:
        - private_key is set (for local/EOA signing)
        - kms_key_path is set (for KMS signing)
        """
        return self.private_key is not None or self.kms_key_path is not None

    @property
    def is_kms_configured(self) -> bool:
        """Check if KMS signing is configured."""
        return self.signer_type == SignerType.KMS and self.kms_key_path is not None

    def get_signer(self) -> "Signer":
        """Create a Signer instance from this config.

        Returns:
            Appropriate Signer implementation based on signer_type

        Raises:
            ValueError: If required credentials are missing
            ImportError: If required packages are not installed
        """
        from .signer import (
            Signer,
            LocalSigner,
            KMSSigner,
            EOASigner,
            SignerType as SignerTypeEnum,
        )

        if self.signer_type == SignerType.KMS:
            if not self.kms_key_path:
                raise ValueError("kms_key_path is required for KMS signer")
            return KMSSigner(
                key_path=self.kms_key_path,
                wallet_address=self.wallet_address,
                chain_id=self.chain_id,
                clob_api_url=self.clob_api_url,
            )

        elif self.signer_type == SignerType.EOA:
            if not self.private_key:
                raise ValueError("private_key is required for EOA signer")
            return EOASigner(
                private_key=self.private_key,
                chain_id=self.chain_id,
                clob_api_url=self.clob_api_url,
            )

        else:  # LOCAL (default)
            if not self.private_key:
                raise ValueError("private_key is required for local signer")
            return LocalSigner(
                private_key=self.private_key,
                chain_id=self.chain_id,
                clob_api_url=self.clob_api_url,
                funder=self.proxy_wallet,
                signature_type=self.signature_type,
            )

    def to_dict(self, include_secrets: bool = False) -> dict:
        """Convert config to dictionary.

        Args:
            include_secrets: Include private key in output

        Returns:
            Dictionary representation
        """
        result = {
            "wallet_address": self.wallet_address,
            "proxy_wallet": self.proxy_wallet,
            "chain_id": self.chain_id,
            "signature_type": self.signature_type,
            "clob_api_url": self.clob_api_url,
            "data_api_url": self.data_api_url,
            "gamma_api_url": self.gamma_api_url,
            "signer_type": self.signer_type,
            "has_trading_credentials": self.has_trading_credentials,
            "is_kms_configured": self.is_kms_configured,
        }

        if include_secrets:
            if self.private_key:
                result["private_key"] = self.private_key
            if self.kms_key_path:
                result["kms_key_path"] = self.kms_key_path

        return result
