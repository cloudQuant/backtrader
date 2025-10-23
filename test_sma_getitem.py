#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import backtrader as bt
import backtrader.indicators as btind

class DebugStrategy(bt.Strategy):
    def __init__(self):
        self.sma = btind.SMA(self.data, period=15)
        self.count = 0
        
    def next(self):
        self.count += 1
        if self.count == 20:  # Check at bar 20
            print(f"\n=== Bar {self.count} Debug ===")
            print(f"self.sma type: {type(self.sma)}")
            print(f"self.sma._idx: {getattr(self.sma, '_idx', 'N/A')}")
            
            if hasattr(self.sma, 'lines') and hasattr(self.sma.lines, 'sma'):
                sma_line = self.sma.lines.sma
                print(f"sma_line._idx: {getattr(sma_line, '_idx', 'N/A')}")
                print(f"sma_line.array length: {len(sma_line.array) if hasattr(sma_line, 'array') else 'N/A'}")
                if hasattr(sma_line, 'array') and len(sma_line.array) > 19:
                    print(f"sma_line.array[19]: {sma_line.array[19]}")
                
                # Try different access methods
                print(f"\nTrying to access value:")
                try:
                    val1 = self.sma[0]
                    print(f"  self.sma[0]: {val1}")
                except Exception as e:
                    print(f"  self.sma[0] error: {e}")
                    
                try:
                    val2 = self.sma.lines.sma[0]
                    print(f"  self.sma.lines.sma[0]: {val2}")
                except Exception as e:
                    print(f"  self.sma.lines.sma[0] error: {e}")
                    
                try:
                    # Direct array access
                    if hasattr(sma_line, '_idx') and hasattr(sma_line, 'array'):
                        idx = sma_line._idx
                        if 0 <= idx < len(sma_line.array):
                            val3 = sma_line.array[idx]
                            print(f"  sma_line.array[{idx}]: {val3}")
                except Exception as e:
                    print(f"  Direct array access error: {e}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    data = bt.feeds.BacktraderCSVData(
        dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
    )
    cerebro.adddata(data)
    cerebro.addstrategy(DebugStrategy)
    cerebro.run()
