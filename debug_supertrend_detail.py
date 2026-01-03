#!/usr/bin/env python
"""Debug script to trace SuperTrend access patterns in detail"""
import sys
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


class SuperTrendDebug(bt.Indicator):
    """SuperTrend indicator with debug output"""
    lines = ('supertrend', 'direction')
    params = dict(period=10, multiplier=3.0)

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.period)
        self.hl2 = (self.data.high + self.data.low) / 2.0
        self._call_count = 0

    def next(self):
        self._call_count += 1
        bar = self._call_count
        
        if bar <= self.p.period:
            self.lines.supertrend[0] = self.hl2[0]
            self.lines.direction[0] = 1
            if bar <= 15:
                print(f"  bar={bar}: warmup, hl2={self.hl2[0]:.4f}, supertrend={self.lines.supertrend[0]:.4f}, dir=1")
            return
            
        atr = self.atr[0]
        hl2 = self.hl2[0]
        close = self.data.close[0]
        
        upper_band = hl2 + self.p.multiplier * atr
        lower_band = hl2 - self.p.multiplier * atr
        
        prev_supertrend = self.lines.supertrend[-1]
        prev_direction = self.lines.direction[-1]
        
        if prev_direction == 1:
            if close < prev_supertrend:
                self.lines.supertrend[0] = upper_band
                self.lines.direction[0] = -1
            else:
                self.lines.supertrend[0] = max(lower_band, prev_supertrend)
                self.lines.direction[0] = 1
        else:
            if close > prev_supertrend:
                self.lines.supertrend[0] = lower_band
                self.lines.direction[0] = 1
            else:
                self.lines.supertrend[0] = min(upper_band, prev_supertrend)
                self.lines.direction[0] = -1
        
        if bar <= 15 or (prev_direction != self.lines.direction[0]):
            print(f"  bar={bar}: close={close:.4f}, hl2={hl2:.4f}, atr={atr:.4f}, "
                  f"prev_st={prev_supertrend:.4f}, prev_dir={prev_direction}, "
                  f"new_st={self.lines.supertrend[0]:.4f}, new_dir={self.lines.direction[0]}")


def main():
    for runonce in [True, False]:
        print(f"\n{'='*80}")
        print(f"runonce={runonce}")
        print(f"{'='*80}")
        
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
        
        class STStrategy(bt.Strategy):
            def __init__(self):
                self.st = SuperTrendDebug(self.data, period=10, multiplier=3.0)
        
        cerebro.addstrategy(STStrategy)
        cerebro.run()


if __name__ == "__main__":
    main()
