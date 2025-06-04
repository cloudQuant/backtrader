#!/usr/bin/env python

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'tests'))

import backtrader as bt
import original_tests.testcommon as testcommon

class TestStrat(bt.Strategy):
    def __init__(self):
        print('In TestStrat.__init__, creating SMA...')
        self.ind = bt.indicators.SMA(self.data, period=25)
        print(f'Created SMA: {self.ind}')
        print(f'Type: {type(self.ind)}')
        print(f'Hasattr len: {hasattr(self.ind, "__len__")}')
    
    def stop(self):
        print('In stop method...')
        print(f'self.ind: {self.ind}')
        print(f'Type: {type(self.ind)}')
        try:
            l = len(self.ind)
            print(f'Length: {l}')
        except Exception as e:
            print(f'Error getting length: {e}')
            print(f'Dir of self.ind: {[x for x in dir(self.ind) if not x.startswith("_")]}')

try:
    data = testcommon.getdata(0)
    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrat)
    cerebro.run()
except Exception as e:
    print(f'Error: {e}')
    import traceback
    traceback.print_exc() 