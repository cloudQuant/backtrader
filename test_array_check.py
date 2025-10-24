#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import backtrader as bt
import datetime
import os

# Create cerebro
cerebro = bt.Cerebro()

# Add data
datapath = os.path.join(os.path.dirname(__file__), 'tests/datas/2006-day-001.txt')
data = bt.feeds.BacktraderCSVData(
    dataname=datapath,
    fromdate=datetime.datetime(2006, 1, 1),
    todate=datetime.datetime(2006, 12, 31))
cerebro.adddata(data)

# Preload data through cerebro
cerebro._datas = [data]
for d in cerebro._datas:
    d._start()
    if cerebro.p.preload:
        d.preload()

# Check the array
print(f"Data array length: {len(data.lines.close.array)}")
print(f"Data _idx: {data.lines.close._idx}")
print(f"Data idx: {data.lines.close.idx}")
print(f"First 10 values in close array:")
for i in range(min(10, len(data.lines.close.array))):
    print(f"  array[{i}] = {data.lines.close.array[i]}")

print(f"\nAccessing via __getitem__:")
data.lines.close._idx = 0
print(f"  close[0] with _idx=0: {data.lines.close[0]}")
data.lines.close._idx = 1
print(f"  close[0] with _idx=1: {data.lines.close[0]}")
data.lines.close._idx = 2
print(f"  close[0] with _idx=2: {data.lines.close[0]}")
