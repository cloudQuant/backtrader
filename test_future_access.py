#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试访问未来数据的IndexError行为
"""

import backtrader as bt
import pandas as pd

class TestStrategy(bt.Strategy):
    def __init__(self):
        print("\n=== Strategy Init ===")
        print(f"Total data feeds: {len(self.datas)}")
        for i, data in enumerate(self.datas):
            print(f"Data {i}: {data._name}, has {len(data)} bars preloaded")
    
    def next(self):
        current_bar = len(self)
        
        # Test each data feed
        for i, data in enumerate(self.datas):
            data_len = len(data)
            data_name = data._name
            
            # Only test on specific bars
            if current_bar in [1, 5, 8, 10]:
                print(f"\n=== Bar {current_bar}, Data {data_name} (len={data_len}) ===")
                
                # Try to access close[0] (current)
                try:
                    val0 = data.close[0]
                    print(f"  close[0] = {val0:.2f} (OK)")
                except IndexError as e:
                    print(f"  close[0] raised IndexError: {e}")
                
                # Try to access close[3] (3 bars into future)
                try:
                    val3 = data.close[3]
                    print(f"  close[3] = {val3:.2f} (OK - future data accessible)")
                except IndexError as e:
                    print(f"  close[3] raised IndexError: {e} (CORRECT - insufficient future data)")

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
    
    # Create data feed 2: only 7 bars (will end early)
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
    
    cerebro.addstrategy(TestStrategy)
    
    print("Running test with preload=True (default)...")
    cerebro.run()
    print("\nTest complete")
