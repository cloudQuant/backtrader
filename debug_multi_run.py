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
    params = dict(chkind=None, chkargs=dict())
    
    def __init__(self):
        self.ind = self.p.chkind(self.data, **self.p.chkargs)
        
    def stop(self):
        global run_count
        run_count += 1
        
        l = len(self.ind)
        chkpts = [0, -l + 20, (-l + 20) // 2]  # For period=20
        
        print(f"\n=== RUN #{run_count} ===")
        print(f"  len(data): {len(self.data)}")
        print(f"  len(ind): {l}")
        print(f"  chkpts: {chkpts}")
        
        if hasattr(self.ind.lines, 'highest'):
            line = self.ind.lines.highest
            print(f"  ind.line.lencount: {line.lencount if hasattr(line, 'lencount') else 'N/A'}")
            print(f"  ind.line._idx: {line._idx if hasattr(line, '_idx') else 'N/A'}")
            print(f"  ind.line.array len: {len(line.array) if hasattr(line, 'array') else 'N/A'}")
        
        for i, chkpt in enumerate(chkpts):
            try:
                val = self.ind[chkpt]
                print(f"  ind[{chkpt}]: {val}")
            except Exception as e:
                print(f"  ind[{chkpt}]: ERROR - {e}")

datas = [testcommon.getdata(0)]
testcommon.runtest(datas,
                  TestStrategy,
                  main=False,
                  plot=False,
                  chkind=btind.Highest,
                  chkargs={'period': 20})

print(f"\n{'='*80}")
print(f"TOTAL RUNS: {run_count}")
print(f"{'='*80}")

