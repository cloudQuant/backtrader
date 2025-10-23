#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import backtrader as bt
import backtrader.indicators as btind

# Monkey patch to count loop iterations
original_runonce = bt.Cerebro._runonce

def counting_runonce(self, runstrats):
    # Call the original _once
    for strat in runstrats:
        strat._once()
        strat.reset()
    
    datas = sorted(self.datas, key=lambda x: (x._timeframe, x._compression))
    
    loop_count = 0
    while True:
        try:
            dts = [d.advance_peek() for d in datas]
            dt0 = min(dts)
            if dt0 == float("inf"):
                print(f"Loop ended: dt0={dt0}")
                break
            
            loop_count += 1
            
            for i, dti in enumerate(dts):
                if dti <= dt0:
                    datas[i].advance()
            
            self._check_timers(runstrats, dt0, cheat=True)
            if self.p.cheat_on_open:
                for strat in runstrats:
                    strat._oncepost_open()
                    if self._event_stop:
                        return
            
            self._brokernotify()
            if self._event_stop:
                return
            
            self._check_timers(runstrats, dt0, cheat=False)
            
            for strat in runstrats:
                strat._oncepost(dt0)
                if self._event_stop:
                    return
                self._next_writers(runstrats)
        except Exception as e:
            import traceback
            print(f"Error in _runonce: {traceback.format_exc()}")
            return
    
    print(f"Total loop iterations: {loop_count}")
    print("结束_runonce")

bt.Cerebro._runonce = counting_runonce

class TestStrategy(bt.Strategy):
    def __init__(self):
        btind.SMA()

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    # Add data
    data = bt.feeds.BacktraderCSVData(
        dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
    )
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy)
    
    # Run
    cerebro.run()
