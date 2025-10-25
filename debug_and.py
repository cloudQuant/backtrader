#!/usr/bin/env python
import sys
sys.path.insert(0, '/home/yun/Documents/backtrader')

import backtrader as bt
from backtrader.indicators.crossover import NonZeroDifference

class TestStrat(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=15)
        
        # Manually create components like CrossUp does
        nzd = NonZeroDifference(self.data.close, self.sma)
        before = nzd(-1) <= 0.0  # previous diff <= 0
        after = self.data.close > self.sma  # now close > sma
        
        print(f"\n=== Checking And inputs ===")
        print(f"before type: {type(before)}")
        print(f"after type: {type(after)}")
        print(f"before has array: {hasattr(before, 'array')}")
        print(f"after has array: {hasattr(after, 'array')}")
        
        and_result = bt.functions.And(before, after)
        print(f"And created, args length: {len(and_result.args) if hasattr(and_result, 'args') else 'NO ARGS'}")
        if hasattr(and_result, 'args'):
            for i, arg in enumerate(and_result.args):
                print(f"  arg[{i}] type: {type(arg)}")
        
        self.and_result = and_result
        self.before = before
        self.after = after
    
    def next(self):
        if len(self) == 19:
            print(f"\nBar 19 (close should cross above sma):")
            print(f"  close={self.data.close[0]:.2f}, sma={self.sma[0]:.2f}")
            print(f"  before={self.before[0]:.2f}")
            print(f"  after={self.after[0]:.2f}")
            print(f"  and_result={self.and_result[0]:.2f}")

cerebro = bt.Cerebro()
data = bt.feeds.BacktraderCSVData(
    dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
)
cerebro.adddata(data)
cerebro.addstrategy(TestStrat)
cerebro.run()
