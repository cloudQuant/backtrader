#!/usr/bin/env python
# Debug script for parameter filtering

import sys
sys.path.append('tests/original_tests')
import testcommon
import backtrader as bt

def debug_params_filter():
    print("Testing parameter filtering...")
    
    # Test creating a TestStrategy instance directly
    try:
        print("\n1. Testing direct instantiation with kwargs...")
        strategy = testcommon.TestStrategy(main=False, chkind=[], chkmin=30)
        print("SUCCESS: Direct instantiation worked!")
        print(f"Strategy.p.main: {strategy.p.main}")
        print(f"Strategy.p.chkind: {strategy.p.chkind}")
        print(f"Strategy.p.chkmin: {strategy.p.chkmin}")
    except Exception as e:
        print(f"FAILED: Direct instantiation failed: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n2. Testing with datas...")
    try:
        # Create some dummy data
        data = bt.feeds.BacktraderCSVData(dataname='tests/original_tests/../datas/2006-day-001.txt')
        strategy = testcommon.TestStrategy(data, main=False, chkind=[], chkmin=30)
        print("SUCCESS: Instantiation with data worked!")
    except Exception as e:
        print(f"FAILED: Instantiation with data failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_params_filter() 