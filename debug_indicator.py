#!/usr/bin/env python
"""Debug indicator hl2 access patterns"""
import sys
import datetime
from pathlib import Path

sys.path.insert(0, '.')

import backtrader as bt

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


class HL2Indicator(bt.Indicator):
    """Simple indicator that just traces hl2"""
    lines = ('hl2out',)
    
    def __init__(self):
        self.hl2 = (self.data.high + self.data.low) / 2.0
        self._bar = 0
    
    def next(self):
        self._bar += 1
        hl2_val = self.hl2[0]
        high_val = self.data.high[0]
        low_val = self.data.low[0]
        expected = (high_val + low_val) / 2.0
        
        self.lines.hl2out[0] = hl2_val
        
        if self._bar <= 10:
            match = "OK" if abs(hl2_val - expected) < 0.001 else "MISMATCH!"
            print(f"  IND bar={self._bar}: high={high_val:.4f}, low={low_val:.4f}, "
                  f"hl2={hl2_val:.4f}, expected={expected:.4f} [{match}]")


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
        
        class TestStrategy(bt.Strategy):
            def __init__(self):
                self.ind = HL2Indicator(self.data)
        
        cerebro.addstrategy(TestStrategy)
        cerebro.run()


if __name__ == "__main__":
    main()
