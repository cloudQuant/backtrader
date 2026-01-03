#!/usr/bin/env python
"""Debug LinesOperation access patterns"""
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
        
        class HL2Debug(bt.Strategy):
            def __init__(self):
                self.hl2 = (self.data.high + self.data.low) / 2.0
                self._bar = 0
            
            def next(self):
                self._bar += 1
                if self._bar <= 10:
                    # Get values using different methods
                    high_val = self.data.high[0]
                    low_val = self.data.low[0]
                    hl2_direct = (high_val + low_val) / 2.0
                    hl2_op = self.hl2[0]
                    
                    # Also check high/low arrays
                    high_idx = getattr(self.data.high, 'idx', '?')
                    low_idx = getattr(self.data.low, 'idx', '?')
                    hl2_idx = getattr(self.hl2, 'idx', '?')
                    
                    print(f"  bar={self._bar}: high={high_val:.4f} (idx={high_idx}), "
                          f"low={low_val:.4f} (idx={low_idx}), "
                          f"hl2_direct={hl2_direct:.4f}, hl2_op={hl2_op:.4f} (idx={hl2_idx})")
                    
                    if abs(hl2_direct - hl2_op) > 0.0001:
                        print(f"    *** MISMATCH! ***")
        
        cerebro.addstrategy(HL2Debug)
        cerebro.run()


if __name__ == "__main__":
    main()
