#!/usr/bin/env python
"""Debug script to trace SuperTrend indicator behavior"""
import sys
import os
import datetime
from pathlib import Path

sys.path.insert(0, '.')

import backtrader as bt
import backtrader.indicators as btind

BASE_DIR = Path(__file__).resolve().parent / "tests" / "strategies"

def resolve_data_path(filename: str) -> Path:
    search_paths = [
        BASE_DIR / filename,
        BASE_DIR.parent / filename,
        BASE_DIR / "datas" / filename,
        BASE_DIR.parent / "datas" / filename,
    ]
    for p in search_paths:
        if p.exists():
            return p
    raise FileNotFoundError(f"Cannot find data file: {filename}")


class SuperTrendIndicator(bt.Indicator):
    """超级趋势指标 - copy from test"""
    lines = ('supertrend', 'direction')
    params = dict(
        period=10,
        multiplier=3.0,
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.period)
        self.hl2 = (self.data.high + self.data.low) / 2.0

    def next(self):
        if len(self) < self.p.period + 1:
            self.lines.supertrend[0] = self.hl2[0]
            self.lines.direction[0] = 1
            return
            
        atr = self.atr[0]
        hl2 = self.hl2[0]
        
        upper_band = hl2 + self.p.multiplier * atr
        lower_band = hl2 - self.p.multiplier * atr
        
        prev_supertrend = self.lines.supertrend[-1]
        prev_direction = self.lines.direction[-1]
        
        if prev_direction == 1:
            if self.data.close[0] < prev_supertrend:
                self.lines.supertrend[0] = upper_band
                self.lines.direction[0] = -1
            else:
                self.lines.supertrend[0] = max(lower_band, prev_supertrend)
                self.lines.direction[0] = 1
        else:
            if self.data.close[0] > prev_supertrend:
                self.lines.supertrend[0] = lower_band
                self.lines.direction[0] = 1
            else:
                self.lines.supertrend[0] = min(upper_band, prev_supertrend)
                self.lines.direction[0] = -1


def main():
    results = {}
    
    for runonce in [True, False]:
        data_path = resolve_data_path("orcl-1995-2014.txt")
        data = bt.feeds.GenericCSVData(
            dataname=str(data_path),
            dtformat='%Y-%m-%d',
            datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
            fromdate=datetime.datetime(2010, 1, 1),
            todate=datetime.datetime(2014, 12, 31),
        )
        
        cerebro = bt.Cerebro(runonce=runonce, preload=True)
        cerebro.adddata(data)
        
        class STCapture(bt.Strategy):
            direction_array = []
            supertrend_array = []
            buy_count = 0
            sell_count = 0
            
            def __init__(self):
                self.supertrend = SuperTrendIndicator(self.data, period=10, multiplier=3.0)
                self.order = None
            
            def notify_order(self, order):
                if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
                    return
                if order.status == order.Completed:
                    if order.isbuy():
                        STCapture.buy_count += 1
                    else:
                        STCapture.sell_count += 1
                self.order = None
            
            def next(self):
                if self.order:
                    return
                if not self.position:
                    if self.supertrend.direction[0] == 1 and self.supertrend.direction[-1] == -1:
                        self.order = self.buy(size=10)
                else:
                    if self.supertrend.direction[0] == -1:
                        self.order = self.sell(size=10)
            
            def stop(self):
                STCapture.direction_array = list(self.supertrend.lines.direction.array[:len(self.data)])
                STCapture.supertrend_array = list(self.supertrend.lines.supertrend.array[:len(self.data)])
        
        # Reset counters
        STCapture.buy_count = 0
        STCapture.sell_count = 0
        
        cerebro.addstrategy(STCapture)
        cerebro.broker.setcash(100000)
        cerebro.broker.setcommission(commission=0.001)
        cerebro.run()
        
        final_value = cerebro.broker.getvalue()
        
        print(f"\nrunonce={runonce}:")
        print(f"  buy_count: {STCapture.buy_count}, sell_count: {STCapture.sell_count}")
        print(f"  final_value: {final_value:.2f}")
        print(f"  direction (first 20): {STCapture.direction_array[:20]}")
        
        # Find direction changes (potential trade signals)
        direction_changes = []
        for i in range(1, min(50, len(STCapture.direction_array))):
            if STCapture.direction_array[i] != STCapture.direction_array[i-1]:
                direction_changes.append((i, STCapture.direction_array[i-1], STCapture.direction_array[i]))
        print(f"  direction changes (first 50 bars): {direction_changes}")
        
        results[runonce] = {
            'direction': STCapture.direction_array[:200],
            'buy_count': STCapture.buy_count,
            'sell_count': STCapture.sell_count,
            'final_value': final_value
        }
    
    # Compare
    print(f"\n\nDirection arrays match: {results[True]['direction'] == results[False]['direction']}")
    if results[True]['direction'] != results[False]['direction']:
        print("Direction differences:")
        for i, (a, b) in enumerate(zip(results[True]['direction'], results[False]['direction'])):
            if a != b:
                print(f"  Index {i}: runonce=True -> {a}, runonce=False -> {b}")


if __name__ == "__main__":
    main()
