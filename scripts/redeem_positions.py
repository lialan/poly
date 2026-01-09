#!/usr/bin/env python3
"""
Redeem winning positions on Polymarket.

Redeems only winning positions from resolved markets to get USDC.e back.
Losing positions are skipped (they have no value to redeem).

Usage:
    # List redeemable positions (dry run)
    python scripts/redeem_positions.py --dry-run

    # Redeem all resolved positions
    python scripts/redeem_positions.py

    # Redeem specific condition ID only
    python scripts/redeem_positions.py --condition 0x...

Requirements:
    - POLYMARKET_WALLET_ADDRESS and POLYMARKET_PRIVATE_KEY must be set
    - Wallet must have MATIC for gas fees
"""

import argparse
import asyncio
import sys

sys.path.insert(0, "src")

from web3 import Web3

from poly import PolymarketConfig, PolymarketAPI

# Contract addresses (Polygon mainnet)
CTF_CONTRACT = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"  # Conditional Tokens Framework
USDC_E_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # Collateral token

# Polygon RPC
POLYGON_RPC_URLS = [
    "https://polygon-rpc.com",
    "https://rpc-mainnet.matic.network",
]

# CTF ABI (only redeemPositions function)
CTF_ABI = [
    {
        "name": "redeemPositions",
        "type": "function",
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"},
        ],
        "outputs": [],
    },
]


def get_web3() -> Web3:
    """Connect to Polygon RPC."""
    for rpc_url in POLYGON_RPC_URLS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url))
            if w3.is_connected():
                return w3
        except Exception:
            continue
    raise Exception("Failed to connect to Polygon RPC")


async def get_redeemable_positions(config: PolymarketConfig) -> list:
    """Fetch positions that can be redeemed."""
    async with PolymarketAPI(config) as api:
        positions = await api.get_positions(redeemable=True, limit=100)
        return positions


def redeem_position(
    w3: Web3,
    private_key: str,
    condition_id: str,
    dry_run: bool = False,
) -> dict:
    """Redeem a single position.

    Args:
        w3: Web3 instance
        private_key: Private key for signing
        condition_id: Condition ID (hex string with 0x prefix)
        dry_run: If True, don't actually send transaction

    Returns:
        dict with tx_hash or error
    """
    account = w3.eth.account.from_key(private_key)
    wallet = account.address

    ctf = w3.eth.contract(
        address=Web3.to_checksum_address(CTF_CONTRACT),
        abi=CTF_ABI,
    )

    # Ensure condition_id is bytes32
    if isinstance(condition_id, str):
        if condition_id.startswith("0x"):
            condition_bytes = bytes.fromhex(condition_id[2:])
        else:
            condition_bytes = bytes.fromhex(condition_id)
        condition_id = condition_bytes.ljust(32, b'\x00')

    # For binary markets: indexSets = [1, 2] (covers both outcomes)
    # 1 = 0b01 = first outcome (Yes/Up)
    # 2 = 0b10 = second outcome (No/Down)
    index_sets = [1, 2]

    # Parent collection ID is null (bytes32(0)) for Polymarket
    parent_collection_id = b'\x00' * 32

    if dry_run:
        return {"dry_run": True, "condition_id": condition_id.hex()}

    try:
        # Build transaction
        nonce = w3.eth.get_transaction_count(wallet)
        gas_price = w3.eth.gas_price

        tx = ctf.functions.redeemPositions(
            Web3.to_checksum_address(USDC_E_ADDRESS),
            parent_collection_id,
            condition_id,
            index_sets,
        ).build_transaction({
            'from': wallet,
            'nonce': nonce,
            'gas': 200000,
            'gasPrice': gas_price,
            'chainId': 137,
        })

        # Estimate gas
        try:
            estimated_gas = w3.eth.estimate_gas(tx)
            tx['gas'] = int(estimated_gas * 1.2)
        except Exception as e:
            return {"error": f"Gas estimation failed: {e}"}

        # Sign and send
        signed_tx = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        return {
            "success": True,
            "tx_hash": tx_hash.hex(),
            "polygonscan": f"https://polygonscan.com/tx/{tx_hash.hex()}",
        }

    except Exception as e:
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(
        description="Redeem all resolved positions on Polymarket",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # List redeemable positions
    python scripts/redeem_positions.py --dry-run

    # Redeem all
    python scripts/redeem_positions.py

    # Redeem specific condition
    python scripts/redeem_positions.py --condition 0xfa119265...
        """,
    )

    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="List positions without redeeming",
    )

    parser.add_argument(
        "--condition", "-c",
        type=str,
        default=None,
        help="Redeem specific condition ID only",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("REDEEM RESOLVED POSITIONS")
    print("=" * 60)

    # Load config
    print("\n[1] Loading configuration...")
    try:
        config = PolymarketConfig.load()
        print(f"    Wallet: {config.wallet_address}")

        if not config.has_trading_credentials:
            print("    [ERROR] No private key configured")
            return 1

        print("    [OK] Credentials available")
    except Exception as e:
        print(f"    [ERROR] Failed to load config: {e}")
        return 1

    # Connect to Polygon
    print("\n[2] Connecting to Polygon...")
    try:
        w3 = get_web3()
        print(f"    Chain ID: {w3.eth.chain_id}")

        # Check MATIC balance
        matic = w3.eth.get_balance(Web3.to_checksum_address(config.wallet_address))
        matic_balance = w3.from_wei(matic, 'ether')
        print(f"    MATIC: {matic_balance:.4f}")

        if matic_balance < 0.01:
            print("    [WARN] Low MATIC balance for gas")
    except Exception as e:
        print(f"    [ERROR] Failed to connect: {e}")
        return 1

    # Fetch redeemable positions
    print("\n[3] Fetching redeemable positions...")
    positions = asyncio.run(get_redeemable_positions(config))

    if not positions:
        print("    No redeemable positions found")
        return 0

    # Filter by condition if specified
    if args.condition:
        condition_lower = args.condition.lower()
        positions = [p for p in positions if p.condition_id.lower() == condition_lower]
        if not positions:
            print(f"    No position found for condition: {args.condition}")
            return 1

    # Filter to only winning positions (no point redeeming losses)
    winning_positions = [p for p in positions if p.cash_pnl > 0]
    losing_positions = [p for p in positions if p.cash_pnl <= 0]

    if losing_positions:
        print(f"    Skipping {len(losing_positions)} losing position(s) (no value to redeem)")

    if not winning_positions:
        print("    No winning positions to redeem")
        return 0

    positions = winning_positions
    print(f"    Found {len(positions)} winning position(s) to redeem:")
    print()

    total_pnl = 0
    for pos in positions:
        slug = pos.slug[:40] if pos.slug else pos.condition_id[:40]
        side = "YES" if pos.outcome == "Yes" else "NO"
        pnl = pos.cash_pnl
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        result = "WON" if pnl > 0 else "LOST" if pnl < 0 else "PUSH"
        total_pnl += pnl

        print(f"    {slug}")
        print(f"      {side}: {pos.size:.2f} shares | {result} {pnl_str}")
        print(f"      Condition: {pos.condition_id[:20]}...")
        print()

    total_str = f"+${total_pnl:.2f}" if total_pnl >= 0 else f"-${abs(total_pnl):.2f}"
    print(f"    Total PnL: {total_str}")

    if args.dry_run:
        print("\n[4] DRY RUN - No transactions sent")
        print("    Remove --dry-run to redeem positions")
        return 0

    # Redeem each position
    print(f"\n[4] Redeeming {len(positions)} position(s)...")

    success_count = 0
    for i, pos in enumerate(positions, 1):
        slug = pos.slug[:30] if pos.slug else pos.condition_id[:30]
        print(f"\n    [{i}/{len(positions)}] {slug}...")

        result = redeem_position(
            w3=w3,
            private_key=config.private_key,
            condition_id=pos.condition_id,
            dry_run=False,
        )

        if result.get("success"):
            print(f"      [OK] TX: {result['tx_hash'][:20]}...")
            print(f"      Polygonscan: {result['polygonscan']}")
            success_count += 1
        elif result.get("error"):
            print(f"      [ERROR] {result['error'][:60]}")
        else:
            print(f"      [SKIP] {result}")

    print("\n" + "=" * 60)
    print(f"REDEMPTION COMPLETE: {success_count}/{len(positions)} succeeded")
    print("=" * 60)
    print("Run check_balance.py to verify updated balance.")

    return 0 if success_count == len(positions) else 1


if __name__ == "__main__":
    sys.exit(main())
