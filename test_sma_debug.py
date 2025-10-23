#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import backtrader as bt
import backtrader.indicators as btind

# Monkey patch SMA to add debug output
original_sma_next = btind.SMA.next
call_count = 0

def debug_sma_next(self):
    global call_count
    call_count += 1
    if call_count <= 20:  # Only first 20 calls
        print(f"SMA.next() call {call_count}:")
        print(f"  self._idx: {getattr(self, '_idx', 'N/A')}")
        print(f"  hasattr(self.data, 'array'): {hasattr(self.data, 'array')}")
        if hasattr(self.data, 'array'):
            print(f"  len(self.data.array): {len(self.data.array)}")
        if hasattr(self.data, '_idx'):
            print(f"  self.data._idx: {self.data._idx}")
        try:
            val = self.data[0]
            print(f"  self.data[0]: {val}")
        except Exception as e:
            print(f"  self.data[0] error: {e}")
        
        if hasattr(self.data, 'array') and hasattr(self, '_idx'):
            try:
                if 0 <= self._idx < len(self.data.array):
                    val = self.data.array[self._idx]
                    print(f"  self.data.array[{self._idx}]: {val}")
            except Exception as e:
                print(f"  self.data.array[{self._idx}] error: {e}")
    
    return original_sma_next(self)

btind.SMA.next = debug_sma_next

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.sma = btind.SMA(self.data, period=15)

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    # Add data
    data = bt.feeds.BacktraderCSVData(
        dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
    )
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy)
    
    # Run
    cerebro.run()
    print(f"\nTotal SMA.next() calls: {call_count}")
