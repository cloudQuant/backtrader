#!/usr/bin/env python
import sys
sys.path.insert(0, '/home/yun/Documents/backtrader')
sys.path.insert(0, '/home/yun/Documents/backtrader/tests/original_tests')

import backtrader as bt
import testcommon

# Import the test strategy
from test_strategy_unoptimized import RunStrategy

# Get test data
datas = [testcommon.getdata(0)]

# Run with testcommon.runtest to match the test
print("Running with testcommon.runtest...")
cerebros = testcommon.runtest(datas,
                               RunStrategy,
                               printdata=False,  # Disable printdata to avoid ValueError
                               printops=False,
                               stocklike=False,
                               plot=False,
                               main=True)

print(f"\nRan {len(cerebros)} cerebro configurations")
for i, cerebro in enumerate(cerebros):
    if cerebro.runstrats:
        strat = cerebro.runstrats[0][0]
        value = cerebro.broker.getvalue()
        print(f"Config {i}: value={value:.2f}, buys={len(strat.buycreate)}, sells={len(strat.sellcreate)}")
        if abs(value - 10000.00) < 1:
            print(f"  ^^^ This config has NO trades (value=10000)!")
