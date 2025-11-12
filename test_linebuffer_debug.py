#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
调试LineBuffer的索引访问行为
"""

import backtrader as bt
import pandas as pd

class DebugStrategy(bt.Strategy):
    def next(self):
        current_bar = len(self)
        
        # Test on every bar to see what happens
        if current_bar >= 5:
            data = self.datas[1]  # Data7Bars
            print(f"\n=== Bar {current_bar}, Data {data._name} ===")
            print(f"len(data) = {len(data)}")
            
            close_line = data.close.lines[0]  # Get the underlying LineBuffer
            print(f"close_line type: {type(close_line).__name__}")
            print(f"close_line._idx: {close_line._idx}")
            print(f"close_line.array length: {len(close_line.array)}")
            print(f"close_line.buflen(): {close_line.buflen()}")
            print(f"close_line.lencount (len): {len(close_line)}")
            print(f"close_line.extension: {close_line.extension}")
            print(f"close_line._is_data_feed_line: {getattr(close_line, '_is_data_feed_line', 'NOT SET')}")
            
            # Try to access close[3]
            print(f"\nTrying to access close[3]...")
            print(f"This will access array[{close_line._idx} + 3] = array[{close_line._idx + 3}]")
            print(f"Array length is {len(close_line.array)}, so index {close_line._idx + 3} is {'IN' if close_line._idx + 3 < len(close_line.array) else 'OUT OF'} range")
            
            try:
                val = data.close[3]
                print(f"close[3] = {val} (no IndexError)")
            except IndexError as e:
                print(f"close[3] raised IndexError: {e}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    # Create data feed 1: 10 bars
    dates1 = pd.date_range('2020-01-01', periods=10, freq='D')
    df1 = pd.DataFrame({
        'open': [100 + i for i in range(10)],
        'high': [101 + i for i in range(10)],
        'low': [99 + i for i in range(10)],
        'close': [100.5 + i for i in range(10)],
        'volume': [1000 for i in range(10)],
    }, index=dates1)
    data1 = bt.feeds.PandasData(dataname=df1, name='Data10Bars')
    cerebro.adddata(data1)
    
    # Create data feed 2: only 7 bars
    dates2 = pd.date_range('2020-01-01', periods=7, freq='D')
    df2 = pd.DataFrame({
        'open': [200 + i for i in range(7)],
        'high': [201 + i for i in range(7)],
        'low': [199 + i for i in range(7)],
        'close': [200.5 + i for i in range(7)],
        'volume': [2000 for i in range(7)],
    }, index=dates2)
    data2 = bt.feeds.PandasData(dataname=df2, name='Data7Bars')
    cerebro.adddata(data2)
    
    cerebro.addstrategy(DebugStrategy)
    
    print("Running debug test...")
    cerebro.run()
    print("\nTest complete")
