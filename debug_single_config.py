#!/usr/bin/env python
import sys
sys.path.insert(0, '/home/yun/Documents/backtrader')
sys.path.insert(0, '/home/yun/Documents/backtrader/tests/original_tests')

import backtrader as bt
import testcommon
from test_strategy_unoptimized import RunStrategy

# Monkey patch stop() to not assert
original_stop = RunStrategy.stop
def patched_stop(self):
    # Just print the value without asserting
    print(f"Stop called: value={self.broker.getvalue():.2f}, cash={self.broker.getcash():.2f}")

RunStrategy.stop = patched_stop

# Get test data
datas = [testcommon.getdata(0)]

# Create cerebro testing exactbars parameter
cerebro = bt.Cerebro(runonce=True, preload=True, exactbars=False)
cerebro.adddata(datas[0])
cerebro.addstrategy(RunStrategy, printdata=False, printops=False, stocklike=False)

print("Running: preload=True, runonce=True, exactbars=FALSE")
strats = cerebro.run()
strat = strats[0]
value = cerebro.broker.getvalue()
cash = cerebro.broker.getcash()
print(f"\nFinal Value: {value:.2f} (expected 12795.00)")
print(f"Final Cash: {cash:.2f} (expected 11795.00)")
print(f"Buys: {len(strat.buycreate)}, Sells: {len(strat.sellcreate)}")
print(f"Position: {strat.position.size}")

if len(strat.buycreate) == 0:
    print("\nNO TRADES - CrossOver not working!")
else:
    print(f"\nBuy prices: {strat.buycreate[:5]}")
    print(f"Sell prices: {strat.sellcreate[:5]}")
