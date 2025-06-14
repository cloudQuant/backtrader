#!/usr/bin/env python
import sys
sys.path.insert(0, '.')
import backtrader as bt
from backtrader.indicators.basicops import Average

class TestStrategy(bt.Strategy):
    def __init__(self):
        print('Creating Average indicator...')
        self.avg = Average(self.data, period=15)
        print(f'Average created with _minperiod: {self.avg._minperiod}')
    
    def next(self):
        print(f'Bar: Average={self.avg[0]}')
        if len(self) > 20:
            self.env.stop()

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    cerebro.addstrategy(TestStrategy)
    cerebro.run(runonce=False) 