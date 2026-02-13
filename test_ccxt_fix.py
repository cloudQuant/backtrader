#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Simple test to verify CCXT broker and store integration fix."""

import backtrader as bt

# Test 1: Verify that store can be created
print("Test 1: Creating CCXTStore...")
try:
    # Use binance which doesn't require password for test
    store = bt.stores.CCXTStore(
        exchange='binance',
        currency='USDT',
        config={},  # No API keys for public data
        retries=3
    )
    print("[OK] CCXTStore created successfully")
except Exception as e:
    print(f"[FAIL] Failed to create CCXTStore: {e}")
    exit(1)

# Test 2: Verify that getbroker works with store instance
print("\nTest 2: Getting broker from store...")
try:
    broker = store.getbroker()
    print("[OK] Broker created from store successfully")
    print(f"  Broker type: {type(broker).__name__}")
    print(f"  Broker store: {type(broker.store).__name__}")
    print(f"  Same store instance: {broker.store is store}")
except Exception as e:
    print(f"[FAIL] Failed to get broker: {e}")
    exit(1)

# Test 3: Verify that getdata works with store instance
print("\nTest 3: Getting data feed from store...")
try:
    data = store.getdata(
        dataname='BTC/USDT',
        name='BTC/USDT',
        timeframe=bt.TimeFrame.Minutes,
        compression=1
    )
    print("[OK] Data feed created from store successfully")
    print(f"  Data feed type: {type(data).__name__}")
    print(f"  Data feed store: {type(data.store).__name__}")
    print(f"  Same store instance: {data.store is store}")
except Exception as e:
    print(f"[FAIL] Failed to get data feed: {e}")
    exit(1)

# Test 4: Verify that broker and data share the same store
print("\nTest 4: Verifying broker and data share same store...")
if broker.store is data.store:
    print("[OK] Broker and data feed share the same store instance")
else:
    print("[FAIL] Broker and data feed use different store instances")
    exit(1)

print("\n" + "="*50)
print("All tests passed!")
print("="*50)
print("\nSummary of fixes:")
print("1. CCXTStore.getbroker() now passes store instance to broker")
print("2. CCXTStore.getdata() now passes store instance to data feed")
print("3. CCXTBroker.__init__() accepts optional store parameter")
print("4. CCXTFeed.__init__() accepts optional store parameter")
print("5. CCXTFeed is properly registered with CCXTStore")
print("6. CCXTFeed now calls parent __init__() method")
