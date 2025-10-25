#!/usr/bin/env python
import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon
from test_strategy_unoptimized import RunStrategy

# Test runonce=False (uses _runnext mode)
datas = [testcommon.getdata(0)]
cerebro = bt.Cerebro(runonce=False, preload=True, exactbars=False)
cerebro.adddata(datas[0])
cerebro.addstrategy(RunStrategy, printdata=False, printops=False, stocklike=False)
print("Testing runonce=False, exact bars=False:")
strats = cerebro.run()
strat = strats[0]
value = cerebro.broker.getvalue()
print(f"Value: {value:.2f}, Buys: {len(strat.buycreate)}, Sells: {len(strat.sellcreate)}")
print(f"Expected: 12795.00, 12 buys, 11 sells")
print(f"Result: {'PASS' if abs(value - 12795.00) < 1.0 and len(strat.buycreate) == 12 else 'FAIL'}")
