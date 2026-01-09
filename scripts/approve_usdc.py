#!/usr/bin/env python3
"""
Approve USDC spending for Polymarket exchange.

This script approves the Polymarket CTF Exchange contract to spend USDC
from your wallet. This is required before placing orders.

Usage:
    # Approve unlimited USDC (recommended)
    python scripts/approve_usdc.py

    # Approve specific amount
    python scripts/approve_usdc.py --amount 100

    # Dry run (show transaction without sending)
    python scripts/approve_usdc.py --dry-run

    # Revoke approval (set to 0)
    python scripts/approve_usdc.py --revoke

Requirements:
    - POLYMARKET_WALLET_ADDRESS and POLYMARKET_PRIVATE_KEY must be set
    - Wallet must have MATIC for gas fees
"""

import argparse
import sys
from decimal import Decimal

sys.path.insert(0, "src")

from web3 import Web3
from eth_account import Account

from poly import PolymarketConfig

# Polymarket contract addresses (Polygon mainnet)
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

# Polygon RPC endpoints
POLYGON_RPC_URLS = [
    "https://polygon-rpc.com",
    "https://rpc-mainnet.matic.network",
    "https://polygon-mainnet.g.alchemy.com/v2/demo",
]

# ERC20 ABI (only functions we need)
ERC20_ABI = [
    {
        "name": "approve",
        "type": "function",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "allowance",
        "type": "function",
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "balanceOf",
        "type": "function",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "decimals",
        "type": "function",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint8"}],
    },
]

# Max uint256 for unlimited approval
MAX_UINT256 = 2**256 - 1


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


def format_usdc(amount_raw: int, decimals: int = 6) -> str:
    """Format raw USDC amount to human readable."""
    if amount_raw >= MAX_UINT256 - 10**18:  # Near max = unlimited
        return "unlimited"
    return f"${amount_raw / 10**decimals:,.2f}"


def main():
    parser = argparse.ArgumentParser(
        description="Approve USDC spending for Polymarket exchange",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Approve unlimited USDC
    python scripts/approve_usdc.py

    # Approve $100 USDC
    python scripts/approve_usdc.py --amount 100

    # Dry run
    python scripts/approve_usdc.py --dry-run

    # Revoke approval
    python scripts/approve_usdc.py --revoke
        """,
    )

    parser.add_argument(
        "--amount", "-a",
        type=float,
        default=None,
        help="Amount of USDC to approve (default: unlimited)",
    )

    parser.add_argument(
        "--revoke", "-r",
        action="store_true",
        help="Revoke approval (set allowance to 0)",
    )

    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show transaction without sending",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("APPROVE USDC FOR POLYMARKET")
    print("=" * 60)

    # Load config
    print("\n[1] Loading configuration...")
    try:
        config = PolymarketConfig.load()
        print(f"    Wallet: {config.wallet_address}")

        if not config.has_trading_credentials:
            print("    [ERROR] No private key configured")
            print("    Set POLYMARKET_PRIVATE_KEY environment variable")
            return 1

        print("    [OK] Private key available")
    except Exception as e:
        print(f"    [ERROR] Failed to load config: {e}")
        return 1

    # Connect to Polygon
    print("\n[2] Connecting to Polygon...")
    try:
        w3 = get_web3()
        chain_id = w3.eth.chain_id
        print(f"    Chain ID: {chain_id}")
        if chain_id != 137:
            print(f"    [WARN] Expected Polygon (137), got {chain_id}")
    except Exception as e:
        print(f"    [ERROR] Failed to connect: {e}")
        return 1

    # Get current balances
    print("\n[3] Checking current state...")
    usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_ADDRESS), abi=ERC20_ABI)
    wallet = Web3.to_checksum_address(config.wallet_address)
    exchange = Web3.to_checksum_address(EXCHANGE_ADDRESS)

    try:
        matic_balance = w3.eth.get_balance(wallet)
        usdc_balance = usdc.functions.balanceOf(wallet).call()
        current_allowance = usdc.functions.allowance(wallet, exchange).call()

        print(f"    MATIC Balance: {w3.from_wei(matic_balance, 'ether'):.4f} MATIC")
        print(f"    USDC Balance:  {format_usdc(usdc_balance)}")
        print(f"    Current Allowance: {format_usdc(current_allowance)}")
        print(f"    Exchange: {EXCHANGE_ADDRESS}")

        if matic_balance < w3.to_wei(0.01, 'ether'):
            print("    [WARN] Low MATIC balance - may not have enough for gas")

    except Exception as e:
        print(f"    [ERROR] Failed to query balances: {e}")
        return 1

    # Determine approval amount
    if args.revoke:
        approval_amount = 0
        approval_display = "$0 (revoke)"
    elif args.amount is not None:
        approval_amount = int(args.amount * 10**6)  # USDC has 6 decimals
        approval_display = f"${args.amount:,.2f}"
    else:
        approval_amount = MAX_UINT256
        approval_display = "unlimited"

    print(f"\n[4] Approval details:")
    print(f"    Spender: {EXCHANGE_ADDRESS}")
    print(f"    Amount:  {approval_display}")

    if approval_amount == current_allowance:
        print("    [INFO] Allowance already set to this value")
        if not args.dry_run:
            print("    No transaction needed")
            return 0

    # Build transaction
    print("\n[5] Building transaction...")
    try:
        # Get nonce and gas price
        nonce = w3.eth.get_transaction_count(wallet)
        gas_price = w3.eth.gas_price

        # Build approve transaction
        tx = usdc.functions.approve(exchange, approval_amount).build_transaction({
            'from': wallet,
            'nonce': nonce,
            'gas': 100000,  # Approval typically uses ~46k gas
            'gasPrice': gas_price,
            'chainId': 137,
        })

        # Estimate gas
        try:
            estimated_gas = w3.eth.estimate_gas(tx)
            tx['gas'] = int(estimated_gas * 1.2)  # 20% buffer
        except Exception:
            pass  # Use default if estimation fails

        gas_cost_wei = tx['gas'] * gas_price
        gas_cost_matic = w3.from_wei(gas_cost_wei, 'ether')

        print(f"    Nonce: {nonce}")
        print(f"    Gas Price: {w3.from_wei(gas_price, 'gwei'):.2f} gwei")
        print(f"    Gas Limit: {tx['gas']}")
        print(f"    Est. Cost: {gas_cost_matic:.6f} MATIC")

    except Exception as e:
        print(f"    [ERROR] Failed to build transaction: {e}")
        return 1

    if args.dry_run:
        print("\n[6] DRY RUN - Transaction not sent")
        print("    Remove --dry-run flag to send transaction")
        return 0

    # Sign and send transaction
    print("\n[6] Signing and sending transaction...")
    try:
        # Sign transaction
        signed_tx = w3.eth.account.sign_transaction(tx, config.private_key)

        # Send transaction
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"    TX Hash: {tx_hash.hex()}")
        print(f"    Polygonscan: https://polygonscan.com/tx/{tx_hash.hex()}")

    except Exception as e:
        print(f"    [ERROR] Failed to send transaction: {e}")
        return 1

    # Wait for confirmation
    print("\n[7] Waiting for confirmation...")
    try:
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

        if receipt['status'] == 1:
            print(f"    [OK] Transaction confirmed!")
            print(f"    Block: {receipt['blockNumber']}")
            print(f"    Gas Used: {receipt['gasUsed']}")

            # Verify new allowance
            new_allowance = usdc.functions.allowance(wallet, exchange).call()
            print(f"    New Allowance: {format_usdc(new_allowance)}")
        else:
            print("    [ERROR] Transaction failed!")
            return 1

    except Exception as e:
        print(f"    [ERROR] Failed to get receipt: {e}")
        print("    Transaction may still be pending - check Polygonscan")
        return 1

    print("\n" + "=" * 60)
    print("APPROVAL COMPLETE")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
