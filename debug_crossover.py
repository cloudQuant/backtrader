#!/usr/bin/env python
"""Debug script to trace CrossOver indicator behavior"""
import sys
import os
sys.path.insert(0, '.')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'tests', 'original_tests'))

import backtrader as bt
import backtrader.indicators as btind
import testcommon

class DebugStrategy(bt.Strategy):
    params = (
        ("period", 5),
    )

    def __init__(self):
        self.sma = btind.SMA(self.data, period=self.p.period)
        self.cross = btind.CrossOver(self.data.close, self.sma, plot=True)
        
    def start(self):
        print(f"\n{'='*80}")
        print(f"Period: {self.p.period}")
        print(f"CrossOver minperiod: {self.cross._minperiod}")
        print(f"SMA minperiod: {self.sma._minperiod}")
        print(f"{'='*80}")
        
    def prenext(self):
        bar = len(self)
        close = self.data.close[0]
        sma_val = self.sma[0] if len(self.sma) > 0 else float('nan')
        cross_val = self.cross[0] if len(self.cross) > 0 else float('nan')
        print(f"PRENEXT bar={bar}: close={close:.2f}, sma={sma_val:.2f}, cross={cross_val}")
        
    def nextstart(self):
        bar = len(self)
        close = self.data.close[0]
        sma_val = self.sma[0]
        cross_val = self.cross[0]
        print(f"NEXTSTART bar={bar}: close={close:.2f}, sma={sma_val:.2f}, cross={cross_val}")
        
    def next(self):
        bar = len(self)
        close = self.data.close[0]
        sma_val = self.sma[0]
        cross_val = self.cross[0]
        if bar <= 15:  # Only print first 15 bars
            print(f"NEXT bar={bar}: close={close:.2f}, sma={sma_val:.2f}, cross={cross_val}")

def main():
    # Test both runonce modes to compare behavior
    results = {}
    for runonce in [True, False]:
        preload = True
        print(f"\n\n{'#'*80}")
        print(f"# runonce={runonce}, preload={preload}")
        print(f"{'#'*80}")
        
        datas = [testcommon.getdata(0)]
        
        cerebro = bt.Cerebro(runonce=runonce, preload=preload)
        cerebro.adddata(datas[0])
        cerebro.addstrategy(DebugStrategy, period=5)
        cerebro.run()
        
    # Now compare the crossover arrays directly
    print(f"\n\n{'='*80}")
    print("Direct CrossOver array comparison")
    print(f"{'='*80}")
    
    for runonce in [True, False]:
        datas = [testcommon.getdata(0)]
        cerebro = bt.Cerebro(runonce=runonce, preload=True)
        cerebro.adddata(datas[0])
        
        class ArrayCapture(bt.Strategy):
            params = (("period", 5),)
            crossarray = []
            smaarray = []
            
            def __init__(self):
                self.sma = btind.SMA(self.data, period=self.p.period)
                self.cross = btind.CrossOver(self.data.close, self.sma)
            
            def stop(self):
                # Capture the arrays
                ArrayCapture.crossarray = list(self.cross.lines[0].array[:len(self.data)])
                ArrayCapture.smaarray = list(self.sma.lines[0].array[:len(self.data)])
        
        cerebro.addstrategy(ArrayCapture)
        cerebro.run()
        
        print(f"\nrunonce={runonce}:")
        print(f"CrossOver array (first 20): {ArrayCapture.crossarray[:20]}")
        print(f"SMA array (first 10): {ArrayCapture.smaarray[:10]}")
        results[runonce] = ArrayCapture.crossarray[:50]
    
    # Compare
    print(f"\n\nArrays match: {results[True] == results[False]}")
    if results[True] != results[False]:
        print("Differences:")
        for i, (a, b) in enumerate(zip(results[True], results[False])):
            if a != b:
                print(f"  Index {i}: runonce=True -> {a}, runonce=False -> {b}")

if __name__ == "__main__":
    main()
