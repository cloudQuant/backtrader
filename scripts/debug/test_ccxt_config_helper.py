#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test script for CCXT config helper module."""

import sys
from pathlib import Path

# Add backtrader to path if needed
sys.path.insert(0, str(Path(__file__).parent))

from backtrader.ccxt import (
    load_ccxt_config_from_env,
    get_exchange_credentials,
    list_supported_exchanges,
    load_dotenv_file,
)

print("=" * 60)
print("CCXT Config Helper Test")
print("=" * 60)

# Test 1: List supported exchanges
print("\n[Test 1] Listing supported exchanges...")
try:
    exchanges = list_supported_exchanges()
    print(f"[OK] Found {len(exchanges)} supported exchanges:")
    for exch in exchanges:
        print(f"  - {exch}")
except Exception as e:
    print(f"[FAIL] {e}")
    exit(1)

# Test 2: Load dotenv file
print("\n[Test 2] Loading .env file...")
try:
    env_path = Path(__file__).parent / ".env"
    loaded = load_dotenv_file(str(env_path))
    if loaded:
        print("[OK] .env file loaded successfully")
    else:
        print("[WARN] .env file not found (this is OK if you haven't created one)")
except Exception as e:
    print(f"[WARN] {e}")

# Test 3: Load OKX config (should work if .env exists)
print("\n[Test 3] Loading OKX configuration from environment...")
try:
    config = load_ccxt_config_from_env('okx', enable_rate_limit=True)
    print("[OK] OKX config loaded successfully:")
    print(f"  - apiKey: {'*' * 20}{config.get('apiKey', '')[-4:] if config.get('apiKey') else 'N/A'}")
    print(f"  - secret: {'*' * 20}{config.get('secret', '')[-4:] if config.get('secret') else 'N/A'}")
    print(f"  - password: {'*' * 20}{config.get('password', '')[-4:] if config.get('password') else 'N/A'}")
    print(f"  - enableRateLimit: {config.get('enableRateLimit', False)}")
except ValueError as e:
    print(f"[EXPECTED] {e}")
    print("  (This is expected if you haven't set up OKX credentials in .env)")
except Exception as e:
    print(f"[FAIL] {e}")
    exit(1)

# Test 4: Load Binance config
print("\n[Test 4] Loading Binance configuration from environment...")
try:
    config = load_ccxt_config_from_env('binance', enable_rate_limit=True)
    print("[OK] Binance config loaded successfully:")
    print(f"  - apiKey: {'*' * 20}{config.get('apiKey', '')[-4:] if config.get('apiKey') else 'N/A'}")
    print(f"  - secret: {'*' * 20}{config.get('secret', '')[-4:] if config.get('secret') else 'N/A'}")
    print(f"  - enableRateLimit: {config.get('enableRateLimit', False)}")
except ValueError as e:
    print(f"[EXPECTED] {e}")
    print("  (This is expected if you haven't set up Binance credentials in .env)")
except Exception as e:
    print(f"[FAIL] {e}")
    exit(1)

# Test 5: Get credentials only
print("\n[Test 5] Getting exchange credentials (OKX)...")
try:
    creds = get_exchange_credentials('okx')
    print("[OK] OKX credentials retrieved:")
    print(f"  - Keys: {list(creds.keys())}")
except ValueError as e:
    print(f"[EXPECTED] {e}")
    print("  (This is expected if you haven't set up credentials in .env)")
except Exception as e:
    print(f"[FAIL] {e}")
    exit(1)

# Test 6: Create backtrader store using config helper
print("\n[Test 6] Creating CCXTStore using config helper...")
try:
    import backtrader as bt

    config = load_ccxt_config_from_env('binance', enable_rate_limit=True)
    store = bt.stores.CCXTStore(
        exchange='binance',
        currency='USDT',
        config=config,
        retries=3
    )
    print("[OK] CCXTStore created successfully using config helper")
    print(f"  - Store type: {type(store).__name__}")
    print(f"  - Exchange: {store.exchange_id}")
except ValueError as e:
    print(f"[EXPECTED] {e}")
    print("  (This is expected if you haven't set up credentials in .env)")
except Exception as e:
    print(f"[FAIL] {e}")
    exit(1)

print("\n" + "=" * 60)
print("All tests completed!")
print("=" * 60)

print("\nUsage Example:")
print("-" * 60)
print("""
# Load config from .env
from backtrader.ccxt import load_ccxt_config_from_env
import backtrader as bt

# For OKX
config = load_ccxt_config_from_env('okx')
store = bt.stores.CCXTStore(
    exchange='okx',
    currency='USDT',
    config=config,
    retries=5
)

# For Binance
config = load_ccxt_config_from_env('binance')
store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config=config,
    retries=5
)
""")
print("-" * 60)
