#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
比较两种访问SMA的方式：
1. TestStrategy方式：在stop()中访问历史值 self.ind[chkpt]
2. RunStrategy方式：在next()中访问当前值 self.sma[0]
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import backtrader as bt
import backtrader.indicators as btind

class TestStrategyStyle(bt.Strategy):
    """模拟test_ind_sma.py的方式：在stop()访问历史值"""
    def __init__(self):
        self.sma = btind.SMA(self.data, period=15)
        
    def next(self):
        pass  # 不在next中访问指标
        
    def stop(self):
        print("\n=== TestStrategy Style (访问历史值) ===")
        # 访问几个历史点
        for i in [0, -100, -200]:
            try:
                val = self.sma[i]
                print(f"  self.sma[{i}] = {val}")
            except Exception as e:
                print(f"  self.sma[{i}] = ERROR: {e}")

class RunStrategyStyle(bt.Strategy):
    """模拟test_analyzer-sqn.py的方式：在next()中访问当前值"""
    def __init__(self):
        self.sma = btind.SMA(self.data, period=15)
        self.count = 0
        
    def next(self):
        self.count += 1
        if self.count <= 5 or self.count > 250:  # 前5个和最后几个
            try:
                val = self.sma[0]
                print(f"Bar {self.count}: self.sma[0] = {val}")
            except Exception as e:
                print(f"Bar {self.count}: self.sma[0] = ERROR: {e}")

if __name__ == '__main__':
    print("=" * 60)
    print("测试1: TestStrategy风格 - 在stop()访问历史值")
    print("=" * 60)
    
    cerebro1 = bt.Cerebro()
    data = bt.feeds.BacktraderCSVData(
        dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
    )
    cerebro1.adddata(data)
    cerebro1.addstrategy(TestStrategyStyle)
    cerebro1.run()
    
    print("\n" + "=" * 60)
    print("测试2: RunStrategy风格 - 在next()访问当前值")
    print("=" * 60)
    
    cerebro2 = bt.Cerebro()
    data = bt.feeds.BacktraderCSVData(
        dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
    )
    cerebro2.adddata(data)
    cerebro2.addstrategy(RunStrategyStyle)
    cerebro2.run()
