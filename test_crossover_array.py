#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import backtrader as bt
import backtrader.indicators as btind

class DebugStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        self.sma = btind.SMA(self.data, period=self.p.period)
        self.cross = btind.CrossOver(self.data.close, self.sma)
        
    def next(self):
        pass
        
    def stop(self):
        print("\n=== CrossOver Array Debug ===")
        print(f"CrossOver type: {type(self.cross)}")
        
        if hasattr(self.cross, 'lines') and hasattr(self.cross.lines, 'crossover'):
            co_line = self.cross.lines.crossover
            print(f"lines.crossover type: {type(co_line)}")
            if hasattr(co_line, 'array'):
                print(f"lines.crossover.array length: {len(co_line.array)}")
                # Count non-zero values
                non_zero = [v for v in co_line.array if v != 0.0 and not (isinstance(v, float) and v != v)]
                print(f"Non-zero values count: {len(non_zero)}")
                if non_zero:
                    print(f"First few non-zero values: {non_zero[:10]}")
                    # Find indices of non-zero values
                    indices = [i for i, v in enumerate(co_line.array) if v != 0.0 and not (isinstance(v, float) and v != v)]
                    print(f"Indices of first 10 non-zero: {indices[:10]}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    data = bt.feeds.BacktraderCSVData(
        dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
    )
    cerebro.adddata(data)
    cerebro.addstrategy(DebugStrategy)
    cerebro.run()
