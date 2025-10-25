#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import sys
import os

tests_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tests', 'add_tests')
sys.path.insert(0, tests_path)

import testcommon
import backtrader as bt
import backtrader.indicators as btind

run_count = 0

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.sma = btind.SMA(self.data, period=30)
        
    def stop(self):
        global run_count
        run_count += 1
        
        print(f"\n=== RUN #{run_count} ===")
        print(f"  len(data): {len(self.data)}")
        print(f"  len(sma): {len(self.sma)}")
        
        if hasattr(self.sma.lines, 'sma'):
            line = self.sma.lines.sma
            print(f"  sma.line.lencount: {line.lencount if hasattr(line, 'lencount') else 'N/A'}")
            print(f"  sma.line._idx: {line._idx if hasattr(line, '_idx') else 'N/A'}")
            print(f"  sma.line.array len: {len(line.array) if hasattr(line, 'array') else 'N/A'}")
            
            if hasattr(line, 'array') and len(line.array) >= 5:
                print(f"  Last 5 array values: {[line.array[i] for i in range(len(line.array) - 5, len(line.array))]}")
        
        l = len(self.sma)
        mp = 30
        chkpts = [0, -l + mp, (-l + mp) // 2]
        
        print(f"  chkpts: {chkpts}")
        for i, chkpt in enumerate(chkpts):
            try:
                val = self.sma[chkpt]
                print(f"  sma[{chkpt}]: {val}")
            except Exception as e:
                print(f"  sma[{chkpt}]: ERROR - {e}")

datas = [testcommon.getdata(0)]
testcommon.runtest(datas,
                  TestStrategy,
                  main=False,
                  plot=False)

print(f"\n{'='*80}")
print(f"TOTAL RUNS: {run_count}")

