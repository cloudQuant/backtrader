#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import backtrader as bt
import backtrader.indicators as btind

class SignalStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        self.sma = btind.SMA(self.data, period=self.p.period)
        self.cross = btind.CrossOver(self.data.close, self.sma)
        self.buy_signals = 0
        self.sell_signals = 0
        
    def next(self):
        cross_val = self.cross[0]
        
        # Count signals
        if cross_val > 0:
            self.buy_signals += 1
            if self.buy_signals <= 5:
                print(f"Bar {len(self)}: BUY SIGNAL! cross={cross_val:.2f}, close={self.data.close[0]:.2f}, sma={self.sma[0]:.2f}")
                
        elif cross_val < 0:
            self.sell_signals += 1
            if self.sell_signals <= 5:
                print(f"Bar {len(self)}: SELL SIGNAL! cross={cross_val:.2f}, close={self.data.close[0]:.2f}, sma={self.sma[0]:.2f}")
                
    def stop(self):
        print(f"\n=== Summary ===")
        print(f"Total Buy Signals: {self.buy_signals}")
        print(f"Total Sell Signals: {self.sell_signals}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    data = bt.feeds.BacktraderCSVData(
        dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
    )
    cerebro.adddata(data)
    cerebro.addstrategy(SignalStrategy)
    cerebro.run()
