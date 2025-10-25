#!/usr/bin/env python
import sys
sys.path.insert(0, '/home/yun/Documents/backtrader')
sys.path.insert(0, '/home/yun/Documents/backtrader/tests/original_tests')

import backtrader as bt

# Patch sell() to add debug output
original_sell = bt.Strategy.sell

def debug_sell(self, *args, **kwargs):
    print(f"\n=== sell() called at len={len(self)} ===")
    print(f"  self.data.datetime._idx = {self.data.datetime._idx if hasattr(self.data.datetime, '_idx') else 'NO _idx'}")
    if hasattr(self.data.datetime, 'array'):
        print(f"  self.data.datetime.array length = {len(self.data.datetime.array)}")
        if hasattr(self.data.datetime, '_idx') and self.data.datetime._idx >= 0 and self.data.datetime._idx < len(self.data.datetime.array):
            print(f"  self.data.datetime.array[_idx] = {self.data.datetime.array[self.data.datetime._idx]}")
    dt_value = self.data.datetime[0]
    print(f"  self.data.datetime[0] = {dt_value}")
    return original_sell(self, *args, **kwargs)

bt.Strategy.sell = debug_sell

# Run the SQN test
import testcommon
from test_analyzer_sqn import RunStrategy

chkdatas = 1
datas = [testcommon.getdata(i) for i in range(chkdatas)]

cerebros = testcommon.runtest(datas,
                              RunStrategy,
                              printdata=False,
                              stocklike=False,
                              maxtrades=None,
                              printops=False,
                              plot=False,
                              analyzer=(bt.analyzers.SQN, {}))

for cerebro in cerebros:
    strat = cerebro.runstrats[0][0]
    analyzer = strat.analyzers[0]
    analysis = analyzer.get_analysis()
    print(f"\nSQN Analysis: {analysis}")
