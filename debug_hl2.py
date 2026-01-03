#!/usr/bin/env python
"""Debug script to compare hl2 (LinesOperation) values between runonce modes"""
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
        
        class HL2Capture(bt.Strategy):
            hl2_array = []
            high_array = []
            low_array = []
            
            def __init__(self):
                self.hl2 = (self.data.high + self.data.low) / 2.0
            
            def stop(self):
                # Capture arrays
                HL2Capture.hl2_array = list(self.hl2.array[:len(self.data)])
                HL2Capture.high_array = list(self.data.high.array[:len(self.data)])
                HL2Capture.low_array = list(self.data.low.array[:len(self.data)])
        
        cerebro.addstrategy(HL2Capture)
        cerebro.run()
        
        print(f"\nrunonce={runonce}:")
        print(f"  high (first 15): {HL2Capture.high_array[:15]}")
        print(f"  low (first 15): {HL2Capture.low_array[:15]}")
        print(f"  hl2 (first 15): {HL2Capture.hl2_array[:15]}")
        
        # Calculate expected hl2
        expected = [(h + l) / 2.0 for h, l in zip(HL2Capture.high_array[:15], HL2Capture.low_array[:15])]
        print(f"  expected hl2: {expected}")
        
        results[runonce] = HL2Capture.hl2_array[:100]
    
    # Compare
    print(f"\n\nHL2 arrays match: {results[True] == results[False]}")
    if results[True] != results[False]:
        print("Differences:")
        import math
        for i, (a, b) in enumerate(zip(results[True], results[False])):
            a_nan = isinstance(a, float) and math.isnan(a)
            b_nan = isinstance(b, float) and math.isnan(b)
            if a_nan and b_nan:
                continue
            if a_nan != b_nan or (not a_nan and abs(a - b) > 1e-9):
                print(f"  Index {i}: runonce=True -> {a}, runonce=False -> {b}")


if __name__ == "__main__":
    main()
