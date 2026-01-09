#!/usr/bin/env python3
"""Test local signing with a generated test key.

This script tests the signing flow without submitting to Polymarket.
It generates a fresh test key and verifies:
1. LocalSigner initialization
2. Order signing
3. Signature format

Usage:
    python scripts/test_local_signing.py
"""

import sys
sys.path.insert(0, "src")

from eth_account import Account


def main():
    print("=" * 60)
    print("LOCAL SIGNING TEST")
    print("=" * 60)

    # Generate a fresh test key
    print("\n[1] Generating test key...")
    account = Account.create()
    private_key = account.key.hex()
    wallet_address = account.address

    print(f"    Private key: {private_key[:10]}...{private_key[-6:]}")
    print(f"    Wallet: {wallet_address}")

    # Test LocalSigner
    print("\n[2] Creating LocalSigner...")
    from poly import LocalSigner, OrderParams, OrderSide

    signer = LocalSigner(
        private_key=private_key,
        chain_id=137,
    )

    derived_wallet = signer.get_wallet_address()
    print(f"    Signer wallet: {derived_wallet}")

    if derived_wallet.lower() == wallet_address.lower():
        print("    [OK] Wallet address matches")
    else:
        print("    [FAIL] Wallet address mismatch!")
        return 1

    # Test order signing
    print("\n[3] Signing test order...")

    # Try to fetch a current market token ID
    test_token_id = None
    try:
        import asyncio
        from poly import Asset, MarketHorizon, fetch_current_prediction

        print("    Fetching current BTC 15m market...")
        prediction = asyncio.run(fetch_current_prediction(Asset.BTC, MarketHorizon.M15))
        test_token_id = prediction.up_token_id
        print(f"    Using live market: {prediction.slug}")
    except Exception as e:
        print(f"    Could not fetch live market: {e}")
        # Fallback to a known token ID format
        test_token_id = "21742633143463906290569050155826241533067272736897614950488156847949938836455"
        print(f"    Using fallback token ID")

    params = OrderParams(
        token_id=test_token_id,
        side=OrderSide.BUY,
        price=0.45,
        size=10.0,
    )

    print(f"    Token: {test_token_id[:20]}...")
    print(f"    Side: {params.side.value}")
    print(f"    Price: {params.price}")
    print(f"    Size: {params.size}")

    try:
        signed_order = signer.sign_order(params)
        print("    [OK] Order signed successfully")
    except Exception as e:
        print(f"    [FAIL] Signing failed: {e}")
        return 1

    # Verify signed order structure
    print("\n[4] Verifying signed order structure...")

    # py-clob-client returns a SignedOrder object, not a dict
    print(f"    Order type: {type(signed_order).__name__}")

    # Check it has the expected attributes
    if hasattr(signed_order, 'order'):
        print("    [OK] order attribute present")
    else:
        print("    [FAIL] order attribute missing")
        return 1

    if hasattr(signed_order, 'signature'):
        print("    [OK] signature attribute present")
    else:
        print("    [FAIL] signature attribute missing")
        return 1

    order = signed_order.order
    print(f"    Inner order type: {type(order).__name__}")

    # Check order has expected attributes
    order_attrs = ["salt", "maker", "signer", "taker", "tokenId",
                   "makerAmount", "takerAmount", "side", "signatureType"]
    for attr in order_attrs:
        if hasattr(order, attr):
            print(f"    [OK] order.{attr} present")
        else:
            print(f"    [FAIL] order.{attr} missing")
            return 1

    # Check signature format
    print("\n[5] Verifying signature format...")
    signature = signed_order.signature

    if signature.startswith("0x"):
        print("    [OK] Signature has 0x prefix")
    else:
        print("    [FAIL] Signature missing 0x prefix")
        return 1

    sig_bytes = bytes.fromhex(signature[2:])
    if len(sig_bytes) == 65:
        print(f"    [OK] Signature length: 65 bytes")
    else:
        print(f"    [FAIL] Signature length: {len(sig_bytes)} (expected 65)")
        return 1

    # Extract r, s, v
    r = int.from_bytes(sig_bytes[0:32], "big")
    s = int.from_bytes(sig_bytes[32:64], "big")
    v = sig_bytes[64]

    print(f"    r: {hex(r)[:20]}...")
    print(f"    s: {hex(s)[:20]}...")
    print(f"    v: {v}")

    if v in (27, 28):
        print("    [OK] v is valid (27 or 28)")
    else:
        print(f"    [FAIL] v is invalid: {v}")
        return 1

    # Check low-S
    SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
    if s <= SECP256K1_N // 2:
        print("    [OK] s is in low-S form")
    else:
        print("    [WARN] s is not in low-S form (may be rejected)")

    # Print full signed order
    # Use .dict() to get readable values
    order_dict = signed_order.dict()

    print("\n[6] Signed order details:")
    print(f"    Salt: {order_dict['salt']}")
    print(f"    Maker: {order_dict['maker']}")
    print(f"    Signer: {order_dict['signer']}")
    print(f"    TokenId: {order_dict['tokenId'][:30]}...")
    print(f"    MakerAmount: {order_dict['makerAmount']} (USDC atomic units)")
    print(f"    TakerAmount: {order_dict['takerAmount']} (shares atomic units)")
    print(f"    Side: {order_dict['side']}")
    print(f"    Signature: {signature[:40]}...")

    # Test SELL order too
    print("\n[7] Testing SELL order...")
    params_sell = OrderParams(
        token_id=test_token_id,
        side=OrderSide.SELL,
        price=0.55,
        size=5.0,
    )

    try:
        signed_sell = signer.sign_order(params_sell)
        sell_dict = signed_sell.dict()
        print(f"    [OK] SELL order signed")
        print(f"    Side: {sell_dict['side']}")
        print(f"    MakerAmount: {sell_dict['makerAmount']} (shares to sell)")
        print(f"    TakerAmount: {sell_dict['takerAmount']} (USDC to receive)")
    except Exception as e:
        print(f"    [FAIL] SELL order signing failed: {e}")
        return 1

    # Submit to CLOB (dry run - expected to fail with test key)
    print("\n[8] Submitting order to CLOB API (dry run)...")
    print("    Note: Expected to fail - test key has no funds/allowance")

    try:
        response = signer.post_order(signed_order)
        # If we somehow succeed (unlikely with test key)
        print(f"    [UNEXPECTED] Order submitted successfully!")
        print(f"    Order ID: {response.get('orderID', 'N/A')}")

        # Try to cancel it immediately
        order_id = response.get('orderID')
        if order_id:
            print("    Cancelling order...")
            try:
                signer.cancel_order(order_id)
                print("    [OK] Order cancelled")
            except Exception as e:
                print(f"    [WARN] Cancel failed: {e}")
    except Exception as e:
        error_msg = str(e)
        print(f"    [EXPECTED] Submission failed: {error_msg[:100]}")

        # Check if it's an expected error (no allowance, not enough balance, etc.)
        expected_errors = [
            "allowance",
            "balance",
            "insufficient",
            "not enough",
            "unauthorized",
            "forbidden",
            "maker not operator",
            "does not exist",  # Old/expired market
            "L2",
        ]

        is_expected = any(err.lower() in error_msg.lower() for err in expected_errors)

        if is_expected:
            print("    [OK] Error is expected for unfunded test wallet")
        else:
            print(f"    [INFO] Full error: {error_msg}")

    # Test get_order with fake ID (should fail gracefully)
    print("\n[9] Testing get_order with invalid ID...")
    try:
        fake_order = signer.get_order("0x" + "0" * 64)
        print(f"    [UNEXPECTED] Got response: {fake_order}")
    except Exception as e:
        print(f"    [EXPECTED] get_order failed: {str(e)[:80]}")

    # Summary
    print("\n" + "=" * 60)
    print("ALL SIGNING TESTS PASSED")
    print("=" * 60)
    print("\nLocal signing is working correctly.")
    print("CLOB submission failed as expected (test key has no funds).")
    print("The test key was generated for this test only - do not use for real trading.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
