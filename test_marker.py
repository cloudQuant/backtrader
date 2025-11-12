#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试_is_data_feed_line标记是否正确设置
"""

import backtrader as bt
import pandas as pd
import datetime

# 创建一个简单的数据源
class TestData(bt.feeds.PandasData):
    pass

# 创建简单的策略来测试
class TestStrategy(bt.Strategy):
    def __init__(self):
        print("\n=== Strategy Init ===")
        data = self.datas[0]
        print(f"Data type: {type(data)}")
        print(f"Has lines: {hasattr(data, 'lines')}")
        
        if hasattr(data, 'lines') and data.lines:
            print(f"Number of lines: {len(data.lines)}")
            for i, line in enumerate(data.lines):
                marker = getattr(line, '_is_data_feed_line', 'NOT SET')
                print(f"Line {i}: {type(line).__name__}, _is_data_feed_line = {marker}")
    
    def next(self):
        if len(self) == 2:
            # Test IndexError - when we're at bar 2 (index 1 in 0-indexed), 
            # accessing close[3] means accessing 3 bars into the future
            # With only 5 bars total, we can't access that far
            print(f"\n=== Bar {len(self)} ===")
            try:
                # This should work - current bar
                val0 = self.data.close[0]
                print(f"close[0] = {val0} (OK)")
                
                # This should raise IndexError - 3 bars into future, but only 3 bars left total
                val3 = self.data.close[3]
                print(f"close[3] = {val3} (should raise IndexError!)")
            except IndexError as e:
                print(f"close[3] raised IndexError: {e} (CORRECT!)")
            except Exception as e:
                print(f"close[3] raised {type(e).__name__}: {e}")
        
        if len(self) == 5:
            # On last bar, test accessing future data that doesn't exist
            print(f"\n=== Last bar (len={len(self)}) ===")
            try:
                # Try to access 3 bars into future from last bar
                val = self.data.close[3]
                print(f"close[3] = {val} (should raise IndexError!)")
            except IndexError as e:
                print(f"close[3] raised IndexError: {e} (CORRECT!)")
            except Exception as e:
                print(f"close[3] raised {type(e).__name__}: {e}")

if __name__ == '__main__':
    # 创建测试数据 - 只有5个bars，这样在第3个bar时，访问close[3]会超出范围
    dates = pd.date_range('2020-01-01', periods=5, freq='D')
    df = pd.DataFrame({
        'open': [100 + i for i in range(5)],
        'high': [101 + i for i in range(5)],
        'low': [99 + i for i in range(5)],
        'close': [100.5 + i for i in range(5)],
        'volume': [1000 for i in range(5)],
    }, index=dates)
    
    cerebro = bt.Cerebro()
    
    data = TestData(dataname=df)
    cerebro.adddata(data)
    
    cerebro.addstrategy(TestStrategy)
    
    print("Running test...")
    cerebro.run()
    print("\nTest complete")
