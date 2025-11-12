#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试边界检查是否正确工作
"""

import backtrader as bt
import pandas as pd

class TestStrategy(bt.Strategy):
    def next(self):
        current_bar = len(self)
        print(f"\n=== Bar {current_bar} ===")
        
        # Test data 0 (10 bars)
        data0 = self.datas[0]
        print(f"Data0 ({data0._name}): len={len(data0)}")
        try:
            val = data0.close[3]
            print(f"  data0.close[3] = {val:.2f}")
        except IndexError as e:
            print(f"  data0.close[3] raised IndexError: {e}")
        
        # Test data 1 (7 bars)
        data1 = self.datas[1]
        print(f"Data1 ({data1._name}): len={len(data1)}")
        try:
            val = data1.close[3]
            print(f"  data1.close[3] = {val:.2f}")
        except IndexError as e:
            print(f"  data1.close[3] raised IndexError: {e}")

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
    
    cerebro.addstrategy(TestStrategy)
    
    print("Running test...")
    print(f"Cerebro runonce: {cerebro.p.runonce}")
    results = cerebro.run(runonce=False)
    print(f"Results: {results}")
    print("\nTest complete")
