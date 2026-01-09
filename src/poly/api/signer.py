"""
Order Signing Interface for Polymarket CLOB API.

Provides pluggable signing implementations:
- LocalSigner: Uses py-clob-client with local private key (default)
- KMSSigner: Uses eth_account with Google Cloud KMS

Usage:
    # Local signing (default, uses py-clob-client)
    signer = LocalSigner(private_key="0x...")

    # KMS signing
    signer = KMSSigner(
        key_path="projects/my-project/locations/us-central1/keyRings/my-ring/cryptoKeys/my-key/cryptoKeyVersions/1",
        wallet_address="0x...",
    )

    # Create order and sign
    signed_order = signer.sign_order(order_data)
"""

import hashlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, TypedDict


class OrderSide(str, Enum):
    """Order side for trading."""
    BUY = "BUY"
    SELL = "SELL"


class SignerType(str, Enum):
    """Type of signer to use."""
    LOCAL = "local"       # py-clob-client with local key
    KMS = "kms"           # Google Cloud KMS
    EOA = "eoa"           # eth_account with local key (no py-clob-client)


@dataclass
class OrderParams:
    """Parameters for creating an order.

    Attributes:
        token_id: The token ID (YES or NO token address)
        side: BUY or SELL
        price: Limit price (0.0 to 1.0)
        size: Number of shares
        fee_rate_bps: Fee rate in basis points (default: 0)
        nonce: Order nonce (auto-generated if None)
        expiration: Order expiration timestamp (default: 0 = no expiration)
    """
    token_id: str
    side: OrderSide
    price: float
    size: float
    fee_rate_bps: int = 0
    nonce: Optional[int] = None
    expiration: int = 0


class SignedOrder(TypedDict):
    """Signed order ready for submission to CLOB API."""
    order: dict
    signature: str
    owner: str
    orderType: str


class Signer(ABC):
    """Abstract base class for order signing.

    Implementations must provide:
    - sign_order(): Create and sign an order
    - get_wallet_address(): Return the signer's wallet address
    - derive_api_credentials(): Get or derive API key/secret for CLOB
    """

    @abstractmethod
    def sign_order(self, params: OrderParams) -> SignedOrder:
        """Create and sign an order.

        Args:
            params: Order parameters

        Returns:
            Signed order dict ready for CLOB API submission
        """
        pass

    @abstractmethod
    def get_wallet_address(self) -> str:
        """Get the wallet address associated with this signer."""
        pass

    @abstractmethod
    def derive_api_credentials(self) -> tuple[str, str, str]:
        """Derive or retrieve API credentials for CLOB.

        Returns:
            Tuple of (api_key, api_secret, api_passphrase)
        """
        pass

    @property
    @abstractmethod
    def signer_type(self) -> SignerType:
        """Return the type of this signer."""
        pass


class LocalSigner(Signer):
    """Local signer using py-clob-client.

    This is the default signer that uses py-clob-client for all
    signing operations. The private key is stored in memory.
    """

    def __init__(
        self,
        private_key: str,
        chain_id: int = 137,
        clob_api_url: str = "https://clob.polymarket.com",
        funder: Optional[str] = None,
        signature_type: int = 0,
    ):
        """Initialize local signer.

        Args:
            private_key: Hex-encoded private key (with or without 0x prefix)
            chain_id: Polygon chain ID (137 for mainnet)
            clob_api_url: CLOB API base URL
            funder: Proxy wallet address (if using smart wallet)
            signature_type: Signing method (0=EOA, 1=Magic, 2=Browser proxy)
        """
        self._private_key = private_key
        self._chain_id = chain_id
        self._clob_api_url = clob_api_url
        self._funder = funder
        self._signature_type = signature_type
        self._clob_client = None
        self._api_creds = None
        self._wallet_address: Optional[str] = None

    def _get_clob_client(self) -> Any:
        """Get or create the CLOB client."""
        if self._clob_client is None:
            try:
                from py_clob_client.client import ClobClient
            except ImportError:
                raise ImportError(
                    "py-clob-client is required for LocalSigner. "
                    "Install with: pip install py-clob-client"
                )

            self._clob_client = ClobClient(
                host=self._clob_api_url,
                key=self._private_key,
                chain_id=self._chain_id,
                signature_type=self._signature_type,
                funder=self._funder,
            )

            # Derive and set API credentials
            if self._api_creds is None:
                self._api_creds = self._clob_client.create_or_derive_api_creds()
            self._clob_client.set_api_creds(self._api_creds)

            # Cache wallet address
            self._wallet_address = self._clob_client.get_address()

        return self._clob_client

    def sign_order(self, params: OrderParams) -> SignedOrder:
        """Create and sign an order using py-clob-client."""
        from py_clob_client.order_builder.constants import BUY, SELL
        from py_clob_client.clob_types import OrderArgs

        client = self._get_clob_client()

        # Map side to py-clob-client constant
        clob_side = BUY if params.side == OrderSide.BUY else SELL

        # Build OrderArgs - only include nonce if explicitly set
        # py-clob-client doesn't accept nonce=None
        kwargs = {
            "token_id": params.token_id,
            "price": params.price,
            "size": params.size,
            "side": clob_side,
            "fee_rate_bps": params.fee_rate_bps,
            "expiration": params.expiration,
        }
        if params.nonce is not None:
            kwargs["nonce"] = params.nonce

        order_args = OrderArgs(**kwargs)

        # Create signed order
        order = client.create_order(order_args)

        return order

    def post_order(self, signed_order: SignedOrder) -> dict:
        """Submit a signed order to CLOB API.

        Args:
            signed_order: Signed order from sign_order()

        Returns:
            API response with order_id
        """
        client = self._get_clob_client()
        return client.post_order(signed_order)

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order.

        Args:
            order_id: The order ID to cancel

        Returns:
            True if cancelled successfully
        """
        client = self._get_clob_client()
        client.cancel(order_id)
        return True

    def get_order(self, order_id: str) -> dict:
        """Get order status.

        Args:
            order_id: The order ID/hash

        Returns:
            Order data from CLOB API
        """
        client = self._get_clob_client()
        return client.get_order(order_id)

    def get_wallet_address(self) -> str:
        """Get the wallet address."""
        if self._wallet_address is None:
            # Need to initialize client to get address
            self._get_clob_client()
        return self._wallet_address or ""

    def derive_api_credentials(self) -> tuple[str, str, str]:
        """Get API credentials."""
        if self._api_creds is None:
            self._get_clob_client()

        if self._api_creds is None:
            raise RuntimeError("Failed to derive API credentials")

        return (
            self._api_creds.api_key,
            self._api_creds.api_secret,
            self._api_creds.api_passphrase,
        )

    @property
    def signer_type(self) -> SignerType:
        return SignerType.LOCAL


class KMSSigner(Signer):
    """Signer using Google Cloud KMS for key storage.

    Uses eth_account for EIP-712 message construction and Google Cloud KMS
    for the actual signing operation. The private key never leaves KMS.

    Requirements:
        - google-cloud-kms package
        - eth_account package
        - KMS key must be EC_SIGN_SECP256K1_SHA256

    Note: This signer constructs Polymarket orders manually and signs using
    KMS. It does not use py-clob-client for signing (only for API submission).
    """

    # Polymarket CLOB contract addresses (Polygon mainnet)
    EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
    COLLATERAL_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e
    CONDITIONAL_TOKENS_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

    # EIP-712 domain for Polymarket
    DOMAIN_NAME = "Polymarket CTF Exchange"
    DOMAIN_VERSION = "1"

    def __init__(
        self,
        key_path: str,
        wallet_address: str,
        chain_id: int = 137,
        clob_api_url: str = "https://clob.polymarket.com",
        project_id: Optional[str] = None,
    ):
        """Initialize KMS signer.

        Args:
            key_path: Full resource path to KMS key version, e.g.:
                "projects/my-project/locations/us/keyRings/my-ring/cryptoKeys/my-key/cryptoKeyVersions/1"
            wallet_address: The Ethereum wallet address derived from this KMS key
            chain_id: Polygon chain ID (137 for mainnet)
            clob_api_url: CLOB API base URL
            project_id: GCP project ID (extracted from key_path if not provided)
        """
        self._key_path = key_path
        self._wallet_address = wallet_address.lower()
        self._chain_id = chain_id
        self._clob_api_url = clob_api_url
        self._project_id = project_id
        self._kms_client = None
        self._api_creds: Optional[tuple[str, str, str]] = None

        # For submitting orders, we still need py-clob-client (without signing)
        self._clob_client = None

    def _get_kms_client(self) -> Any:
        """Get or create the KMS client."""
        if self._kms_client is None:
            try:
                from google.cloud import kms
            except ImportError:
                raise ImportError(
                    "google-cloud-kms is required for KMSSigner. "
                    "Install with: pip install google-cloud-kms"
                )
            self._kms_client = kms.KeyManagementServiceClient()
        return self._kms_client

    def _sign_digest(self, digest: bytes) -> bytes:
        """Sign a digest using KMS.

        Args:
            digest: 32-byte hash to sign

        Returns:
            DER-encoded ECDSA signature
        """
        from google.cloud import kms

        client = self._get_kms_client()

        # Create the sign request
        sign_request = kms.AsymmetricSignRequest(
            name=self._key_path,
            digest=kms.Digest(sha256=digest),
        )

        # Sign using KMS
        response = client.asymmetric_sign(request=sign_request)
        return response.signature

    def _der_to_rs(self, der_sig: bytes) -> tuple[int, int]:
        """Convert DER-encoded signature to (r, s) integers.

        Args:
            der_sig: DER-encoded ECDSA signature

        Returns:
            Tuple of (r, s) as integers
        """
        # DER format: 0x30 [total-length] 0x02 [r-length] [r] 0x02 [s-length] [s]
        if der_sig[0] != 0x30:
            raise ValueError("Invalid DER signature: missing sequence tag")

        # Skip sequence tag and length
        pos = 2

        # Read r
        if der_sig[pos] != 0x02:
            raise ValueError("Invalid DER signature: missing r integer tag")
        pos += 1
        r_len = der_sig[pos]
        pos += 1
        r_bytes = der_sig[pos:pos + r_len]
        pos += r_len

        # Read s
        if der_sig[pos] != 0x02:
            raise ValueError("Invalid DER signature: missing s integer tag")
        pos += 1
        s_len = der_sig[pos]
        pos += 1
        s_bytes = der_sig[pos:pos + s_len]

        r = int.from_bytes(r_bytes, "big")
        s = int.from_bytes(s_bytes, "big")

        return r, s

    def _normalize_s(self, s: int) -> int:
        """Normalize s to low-S form per BIP-62.

        Ethereum requires s to be in the lower half of the curve order.
        """
        # secp256k1 curve order
        SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

        if s > SECP256K1_N // 2:
            s = SECP256K1_N - s
        return s

    def _recover_v(self, digest: bytes, r: int, s: int) -> int:
        """Recover the v value (recovery id) for the signature.

        Args:
            digest: The message digest that was signed
            r: Signature r value
            s: Signature s value

        Returns:
            v value (27 or 28)
        """
        from eth_account._utils.signing import to_standard_signature_bytes
        from eth_keys import keys

        # Try both recovery IDs
        for v in (27, 28):
            try:
                # Construct signature bytes
                sig_bytes = (
                    r.to_bytes(32, "big") +
                    s.to_bytes(32, "big") +
                    bytes([v - 27])
                )

                # Try to recover the public key
                signature = keys.Signature(signature_bytes=sig_bytes)
                recovered_pub = signature.recover_public_key_from_msg_hash(digest)
                recovered_addr = recovered_pub.to_checksum_address().lower()

                if recovered_addr == self._wallet_address:
                    return v
            except Exception:
                continue

        raise ValueError("Failed to recover v value - address mismatch")

    def _build_order_hash(self, params: OrderParams, salt: int) -> bytes:
        """Build the EIP-712 order hash for Polymarket.

        Args:
            params: Order parameters
            salt: Random salt for the order

        Returns:
            32-byte order hash
        """
        from eth_abi import encode
        from eth_utils import keccak

        # EIP-712 domain separator
        domain_type_hash = keccak(
            b"EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
        )

        domain_separator = keccak(encode(
            ["bytes32", "bytes32", "bytes32", "uint256", "address"],
            [
                domain_type_hash,
                keccak(self.DOMAIN_NAME.encode()),
                keccak(self.DOMAIN_VERSION.encode()),
                self._chain_id,
                bytes.fromhex(self.EXCHANGE_ADDRESS[2:]),
            ]
        ))

        # Order type hash for Polymarket
        order_type_hash = keccak(
            b"Order(uint256 salt,address maker,address signer,address taker,"
            b"uint256 tokenId,uint256 makerAmount,uint256 takerAmount,"
            b"uint256 expiration,uint256 nonce,uint256 feeRateBps,uint8 side,"
            b"uint8 signatureType)"
        )

        # Calculate amounts from price and size
        # For BUY: makerAmount = USDC needed, takerAmount = shares to receive
        # For SELL: makerAmount = shares to sell, takerAmount = USDC to receive

        # Polymarket uses 6 decimals for USDC and specific share calculations
        size_raw = int(params.size * 1_000_000)  # 6 decimals
        price_raw = int(params.price * 1_000_000)  # Price in basis points (6 decimals)

        if params.side == OrderSide.BUY:
            maker_amount = int(size_raw * price_raw / 1_000_000)
            taker_amount = size_raw
            side = 0
        else:
            maker_amount = size_raw
            taker_amount = int(size_raw * price_raw / 1_000_000)
            side = 1

        # Build order struct hash
        order_struct_hash = keccak(encode(
            [
                "bytes32", "uint256", "address", "address", "address",
                "uint256", "uint256", "uint256", "uint256", "uint256",
                "uint256", "uint8", "uint8"
            ],
            [
                order_type_hash,
                salt,
                bytes.fromhex(self._wallet_address[2:]),  # maker
                bytes.fromhex(self._wallet_address[2:]),  # signer
                bytes.fromhex("0" * 40),  # taker (any)
                int(params.token_id, 16) if params.token_id.startswith("0x") else int(params.token_id),
                maker_amount,
                taker_amount,
                params.expiration,
                params.nonce or 0,
                params.fee_rate_bps,
                side,
                0,  # signatureType (EOA)
            ]
        ))

        # Final EIP-712 hash
        message = b"\x19\x01" + domain_separator + order_struct_hash
        return keccak(message)

    def sign_order(self, params: OrderParams) -> SignedOrder:
        """Create and sign an order using KMS."""
        import secrets

        # Generate salt if nonce not provided
        salt = params.nonce or secrets.randbits(256)

        # Build the order hash
        order_hash = self._build_order_hash(params, salt)

        # Sign with KMS
        der_signature = self._sign_digest(order_hash)

        # Convert to (r, s) and normalize
        r, s = self._der_to_rs(der_signature)
        s = self._normalize_s(s)

        # Recover v
        v = self._recover_v(order_hash, r, s)

        # Build signature hex
        signature = (
            r.to_bytes(32, "big") +
            s.to_bytes(32, "big") +
            bytes([v])
        )
        signature_hex = "0x" + signature.hex()

        # Calculate amounts (same as in _build_order_hash)
        size_raw = int(params.size * 1_000_000)
        price_raw = int(params.price * 1_000_000)

        if params.side == OrderSide.BUY:
            maker_amount = int(size_raw * price_raw / 1_000_000)
            taker_amount = size_raw
            side = "BUY"
        else:
            maker_amount = size_raw
            taker_amount = int(size_raw * price_raw / 1_000_000)
            side = "SELL"

        # Return signed order in CLOB API format
        return {
            "order": {
                "salt": str(salt),
                "maker": self._wallet_address,
                "signer": self._wallet_address,
                "taker": "0x" + "0" * 40,
                "tokenId": params.token_id,
                "makerAmount": str(maker_amount),
                "takerAmount": str(taker_amount),
                "expiration": str(params.expiration),
                "nonce": str(params.nonce or 0),
                "feeRateBps": str(params.fee_rate_bps),
                "side": side,
                "signatureType": "0",
            },
            "signature": signature_hex,
            "owner": self._wallet_address,
            "orderType": "GTC",
        }

    def get_wallet_address(self) -> str:
        """Get the wallet address."""
        return self._wallet_address

    def derive_api_credentials(self) -> tuple[str, str, str]:
        """Derive API credentials by signing a message.

        Note: CLOB API credentials are derived by signing a specific message.
        For KMS, we need to implement this ourselves.
        """
        if self._api_creds is not None:
            return self._api_creds

        # The CLOB API credential derivation message
        # This is what py-clob-client signs to derive credentials
        timestamp = int(time.time() * 1000)
        message = f"I want to access Polymarket CLOB API at timestamp {timestamp}"

        # Hash the message (Ethereum signed message format)
        from eth_utils import keccak
        prefix = f"\x19Ethereum Signed Message:\n{len(message)}"
        message_hash = keccak((prefix + message).encode())

        # Sign with KMS
        der_signature = self._sign_digest(message_hash)
        r, s = self._der_to_rs(der_signature)
        s = self._normalize_s(s)
        v = self._recover_v(message_hash, r, s)

        signature = (
            r.to_bytes(32, "big") +
            s.to_bytes(32, "big") +
            bytes([v])
        )
        signature_hex = "0x" + signature.hex()

        # Derive credentials from signature (same as py-clob-client)
        # API key is derived from signature hash
        api_key = hashlib.sha256(signature_hex.encode()).hexdigest()[:32]
        api_secret = hashlib.sha256((signature_hex + "secret").encode()).hexdigest()
        api_passphrase = hashlib.sha256((signature_hex + "passphrase").encode()).hexdigest()[:16]

        self._api_creds = (api_key, api_secret, api_passphrase)
        return self._api_creds

    @property
    def signer_type(self) -> SignerType:
        return SignerType.KMS


class EOASigner(Signer):
    """Signer using eth_account directly (without py-clob-client).

    This signer uses eth_account's sign_typed_data for EIP-712 signing.
    Useful when py-clob-client is not desired or for testing.
    """

    def __init__(
        self,
        private_key: str,
        chain_id: int = 137,
        clob_api_url: str = "https://clob.polymarket.com",
    ):
        """Initialize EOA signer.

        Args:
            private_key: Hex-encoded private key
            chain_id: Polygon chain ID (137 for mainnet)
            clob_api_url: CLOB API base URL
        """
        try:
            from eth_account import Account
        except ImportError:
            raise ImportError(
                "eth_account is required for EOASigner. "
                "Install with: pip install eth_account"
            )

        self._private_key = private_key
        self._chain_id = chain_id
        self._clob_api_url = clob_api_url
        self._account = Account.from_key(private_key)
        self._wallet_address = self._account.address.lower()
        self._api_creds: Optional[tuple[str, str, str]] = None

    def sign_order(self, params: OrderParams) -> SignedOrder:
        """Create and sign an order using eth_account."""
        # For simplicity, we delegate to LocalSigner implementation
        # as it already handles the complex order building
        raise NotImplementedError(
            "EOASigner.sign_order() not implemented. "
            "Use LocalSigner for full py-clob-client support or "
            "KMSSigner for KMS-based signing."
        )

    def get_wallet_address(self) -> str:
        """Get the wallet address."""
        return self._wallet_address

    def derive_api_credentials(self) -> tuple[str, str, str]:
        """Derive API credentials."""
        if self._api_creds is not None:
            return self._api_creds

        timestamp = int(time.time() * 1000)
        message = f"I want to access Polymarket CLOB API at timestamp {timestamp}"

        # Sign with eth_account
        from eth_account.messages import encode_defunct
        signable = encode_defunct(text=message)
        signed = self._account.sign_message(signable)
        signature_hex = signed.signature.hex()

        # Derive credentials
        api_key = hashlib.sha256(signature_hex.encode()).hexdigest()[:32]
        api_secret = hashlib.sha256((signature_hex + "secret").encode()).hexdigest()
        api_passphrase = hashlib.sha256((signature_hex + "passphrase").encode()).hexdigest()[:16]

        self._api_creds = (api_key, api_secret, api_passphrase)
        return self._api_creds

    @property
    def signer_type(self) -> SignerType:
        return SignerType.EOA


def create_signer(
    signer_type: SignerType = SignerType.LOCAL,
    private_key: Optional[str] = None,
    kms_key_path: Optional[str] = None,
    wallet_address: Optional[str] = None,
    chain_id: int = 137,
    clob_api_url: str = "https://clob.polymarket.com",
    **kwargs,
) -> Signer:
    """Factory function to create a signer.

    Args:
        signer_type: Type of signer (LOCAL, KMS, or EOA)
        private_key: Private key (required for LOCAL and EOA)
        kms_key_path: KMS key resource path (required for KMS)
        wallet_address: Wallet address (required for KMS)
        chain_id: Polygon chain ID
        clob_api_url: CLOB API URL
        **kwargs: Additional arguments passed to signer constructor

    Returns:
        Signer instance
    """
    if signer_type == SignerType.LOCAL:
        if not private_key:
            raise ValueError("private_key is required for LocalSigner")
        return LocalSigner(
            private_key=private_key,
            chain_id=chain_id,
            clob_api_url=clob_api_url,
            **kwargs,
        )

    elif signer_type == SignerType.KMS:
        if not kms_key_path:
            raise ValueError("kms_key_path is required for KMSSigner")
        if not wallet_address:
            raise ValueError("wallet_address is required for KMSSigner")
        return KMSSigner(
            key_path=kms_key_path,
            wallet_address=wallet_address,
            chain_id=chain_id,
            clob_api_url=clob_api_url,
            **kwargs,
        )

    elif signer_type == SignerType.EOA:
        if not private_key:
            raise ValueError("private_key is required for EOASigner")
        return EOASigner(
            private_key=private_key,
            chain_id=chain_id,
            clob_api_url=clob_api_url,
        )

    else:
        raise ValueError(f"Unknown signer type: {signer_type}")
