#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import backtrader as bt
import backtrader.indicators as btind

class TestStrategy(bt.Strategy):
    params = (('period', 15),)

    def __init__(self):
        self.sma = btind.SMA(self.data, period=self.p.period)
        self.cross = btind.CrossOver(self.data.close, self.sma)
        print(f"\n=== Indicator Setup ===")
        print(f"SMA type: {type(self.sma)}")
        print(f"CrossOver type: {type(self.cross)}")
        print(f"CrossOver has next: {hasattr(self.cross, 'next')}")
        print(f"CrossOver has lines: {hasattr(self.cross, 'lines')}")
        
        # Check if crossover has a line
        if hasattr(self.cross, 'lines'):
            print(f"CrossOver lines: {self.cross.lines}")
            if hasattr(self.cross.lines, 'crossover'):
                print(f"CrossOver.lines.crossover: {self.cross.lines.crossover}")

    def next(self):
        if len(self) < 20:  # Only print first 20 bars
            sma_val = self.sma[0] if hasattr(self.sma, '__getitem__') else float('nan')
            cross_val = self.cross[0] if hasattr(self.cross, '__getitem__') else float('nan')
            print(f"Bar {len(self)}: Close={self.data.close[0]:.2f}, SMA={sma_val:.2f}, Cross={cross_val}")
            
            # Check if cross > 0
            if cross_val > 0:
                print(f"  -> BUY SIGNAL!")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    # Add data
    data = bt.feeds.BacktraderCSVData(
        dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
    )
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy)
    
    print("Running backtest...")
    cerebro.run()
    print("\nDone!")
