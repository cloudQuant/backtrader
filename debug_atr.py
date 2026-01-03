#!/usr/bin/env python
"""Debug script to compare ATR behavior between runonce modes"""
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
        
        class ATRCapture(bt.Strategy):
            atr_array = []
            
            def __init__(self):
                self.atr = btind.ATR(self.data, period=10)
            
            def stop(self):
                ATRCapture.atr_array = list(self.atr.lines[0].array[:len(self.data)])
        
        cerebro.addstrategy(ATRCapture)
        cerebro.run()
        
        print(f"\nrunonce={runonce}:")
        print(f"ATR array (first 20): {ATRCapture.atr_array[:20]}")
        print(f"ATR array (bars 10-15): {ATRCapture.atr_array[10:16]}")
        results[runonce] = ATRCapture.atr_array[:100]
    
    # Compare
    print(f"\n\nArrays match: {results[True] == results[False]}")
    if results[True] != results[False]:
        print("Differences (first 10):")
        diff_count = 0
        for i, (a, b) in enumerate(zip(results[True], results[False])):
            # Handle NaN comparison
            import math
            a_nan = isinstance(a, float) and math.isnan(a)
            b_nan = isinstance(b, float) and math.isnan(b)
            if a_nan and b_nan:
                continue
            if a_nan != b_nan or (not a_nan and abs(a - b) > 1e-9):
                print(f"  Index {i}: runonce=True -> {a}, runonce=False -> {b}")
                diff_count += 1
                if diff_count >= 10:
                    break


if __name__ == "__main__":
    main()
