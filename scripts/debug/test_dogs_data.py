#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""DOGS/USDT spot data loading test.

This script tests whether DOGS/USDT spot data can be loaded correctly.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv
import backtrader as bt
from backtrader.brokers.ccxtbroker import *
from backtrader.feeds.ccxtfeed import *
from backtrader.stores.ccxtstore import *
from backtrader.ccxt import load_ccxt_config_from_env


def test_dogs_usdt_data():
    """Test DOGS/USDT spot data loading.

    Returns:
        bool: True if data loading successful, False otherwise.
    """
    # Load environment variables
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=env_path)

    print("=" * 80)
    print("DOGS/USDT Spot Data Loading Test")
    print("=" * 80)

    # Load OKX configuration
    try:
        config = load_ccxt_config_from_env('okx')
        print("[OK] API configuration loaded successfully")
    except ValueError as e:
        print(f"[FAIL] API configuration failed: {e}")
        return False

    # Create Cerebro
    cerebro = bt.Cerebro()

    # Create store
    store = CCXTStore(
        exchange='okx',
        currency='USDT',
        config=config,
        retries=5,
        debug=False
    )

    # Get spot data
    print("\nLoading DOGS/USDT spot data...")
    data = store.getdata(
        dataname='DOGS/USDT',
        name='DOGS/USDT',
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        fromdate=datetime.utcnow() - timedelta(minutes=200),
        todate=datetime.utcnow(),
        backfill_start=True,
        historical=False,
        ohlcv_limit=100,
        drop_newest=False,
        debug=False
    )

    cerebro.adddata(data)

    # Create simple data check strategy
    class TestDataStrategy(bt.Strategy):
        """Strategy to verify data reception and display OHLCV values."""

        def __init__(self):
            """Initialize test strategy counters."""
            self.bar_count = 0
            self.data_start = None

        def start(self):
            """Record data start time."""
            self.data_start = datetime.now()
            print(f"Data start time: {self.data_start}")

        def next(self):
            """Process each bar and print data periodically."""
            self.bar_count += 1

            # Print every 10 bars
            if self.bar_count % 10 == 0:
                print(f"Received {self.bar_count} bars")

            # Show detailed info for first 3 bars and every 30 bars
            if self.bar_count <= 3 or self.bar_count % 30 == 0:
                print(f"\n--- Bar #{self.bar_count} ---")
                print(f"Time: {self.data.datetime.datetime(0)}")
                print(f"Open: ${self.data.open[0]:.6f}")
                print(f"High: ${self.data.high[0]:.6f}")
                print(f"Low: ${self.data.low[0]:.6f}")
                print(f"Close: ${self.data.close[0]:.6f}")
                print(f"Volume: {self.data.volume[0]:.0f}")

            # Stop after collecting 65 bars
            if self.bar_count >= 65:
                print(f"\nData collection complete! Total {self.bar_count} bars")
                elapsed = (datetime.now() - self.data_start).total_seconds()
                print(f"Elapsed time: {elapsed:.2f} seconds")
                self.stop()

    cerebro.addstrategy(TestDataStrategy)

    print("\nStarting data load...")
    try:
        cerebro.run()
        print("\n[OK] Data loading test complete!")
        return True
    except Exception as e:
        print(f"\n[FAIL] Data loading failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    """Run the DOGS/USDT data loading test."""
    success = test_dogs_usdt_data()
    print("\n" + "=" * 80)
    if success:
        print("[SUCCESS] Ready to run strategy!")
        print("\nRun command:")
        print("python examples/backtrader_ccxt_okx_dogs_bollinger.py")
    else:
        print("[ERROR] Data loading failed, please check:")
        print("1. API configuration is correct")
        print("2. Network connection is working")
        print("3. DOGS/USDT trading pair is available")
    print("=" * 80)
