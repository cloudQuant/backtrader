#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试data.close的类型和IndexError行为
"""

import backtrader as bt
import pandas as pd
import datetime

# 创建策略来检查data.close的类型
class TestStrategy(bt.Strategy):
    def __init__(self):
        print("\n=== Strategy Init ===")
        data = self.datas[0]
        print(f"Data type: {type(data)}")
        print(f"Data class name: {type(data).__name__}")
        
        close = data.close
        print(f"\ndata.close type: {type(close)}")
        print(f"data.close class name: {type(close).__name__}")
        print(f"data.close has __getitem__: {hasattr(close, '__getitem__')}")
        
        # Check if it's a LineSeries
        from backtrader.lineseries import LineSeries
        print(f"Is LineSeries: {isinstance(close, LineSeries)}")
        
        # Check if it has lines
        if hasattr(close, 'lines'):
            print(f"close.lines: {close.lines}")
            if close.lines:
                line0 = close.lines[0]
                print(f"close.lines[0] type: {type(line0)}")
                print(f"close.lines[0] has _is_data_feed_line: {hasattr(line0, '_is_data_feed_line')}")
                if hasattr(line0, '_is_data_feed_line'):
                    print(f"close.lines[0]._is_data_feed_line: {line0._is_data_feed_line}")
    
    def next(self):
        if len(self) == 5:
            # On last bar, test accessing future data
            print(f"\n=== Last bar (len={len(self)}) ===")
            close = self.data.close
            print(f"close type in next(): {type(close).__name__}")
            
            try:
                # Try to access 3 bars into future from last bar
                print("Attempting close[3]...")
                val = close[3]
                print(f"close[3] = {val} (should have raised IndexError!)")
            except IndexError as e:
                print(f"close[3] raised IndexError: {e} (CORRECT!)")
            except Exception as e:
                print(f"close[3] raised {type(e).__name__}: {e}")

if __name__ == '__main__':
    # 创建测试数据 - 只有5个bars
    dates = pd.date_range('2020-01-01', periods=5, freq='D')
    df = pd.DataFrame({
        'open': [100 + i for i in range(5)],
        'high': [101 + i for i in range(5)],
        'low': [99 + i for i in range(5)],
        'close': [100.5 + i for i in range(5)],
        'volume': [1000 for i in range(5)],
    }, index=dates)
    
    cerebro = bt.Cerebro()
    
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)
    
    cerebro.addstrategy(TestStrategy)
    
    print("Running test...")
    cerebro.run()
    print("\nTest complete")
