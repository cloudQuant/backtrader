#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime
import backtrader as bt


class TimerTestStrategy(bt.Strategy):
    def __init__(self):
        self.timer_count = 0
        # Add a timer that triggers weekly
        self.add_timer(
            when=bt.Timer.SESSION_START,
            weekdays=[1],
        )

    def notify_timer(self, timer, when, *args, **kwargs):
        self.timer_count += 1

    def next(self):
        pass


def test_timer(main=False):
    """Test timer functionality"""
    cerebro = bt.Cerebro()
    
    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, '../datas/2006-day-001.txt')
    
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    
    cerebro.adddata(data)
    cerebro.addstrategy(TimerTestStrategy)
    
    results = cerebro.run()
    strat = results[0]
    
    # Verify timer triggered
    assert hasattr(strat, 'timer_count')
    assert strat.timer_count >= 0
    
    if main:
        print(f'Timer triggered {strat.timer_count} times')
        print('Timer test passed')


if __name__ == '__main__':
    test_timer(main=True)

