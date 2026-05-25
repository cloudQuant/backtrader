#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backtrader as bt


class SequenceStrategy(bt.Strategy):
    def __init__(self):
        self.stage = 0
        self.rebalance_refs = {}
        self.statuses = {}

    def next(self):
        equity, bond, gold, crypto = self.datas

        if self.stage == 0:
            self.buy(data=equity, size=4)
            self.buy(data=gold, size=4)
            self.stage = 1
            return

        if self.stage == 1:
            if self.getposition(equity).size != 4 or self.getposition(gold).size != 4:
                return
            self.rebalance_refs['equity_sell'] = self.sell(data=equity, size=2).ref
            self.rebalance_refs['bond_buy'] = self.buy(data=bond, size=6).ref
            self.rebalance_refs['gold_sell'] = self.sell(data=gold, size=2).ref
            self.rebalance_refs['crypto_buy'] = self.buy(data=crypto, size=5).ref
            self.stage = 2

    def notify_order(self, order):
        self.statuses.setdefault(order.ref, []).append(order.getstatusname())


def _write_csv(path, rows):
    with open(path, 'w', encoding='utf-8') as handle:
        for row in rows:
            handle.write(','.join(map(str, row)) + '\n')


def _make_feed(path):
    return bt.feeds.GenericCSVData(
        dataname=str(path),
        dtformat='%Y-%m-%d',
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=6,
        headers=False,
        timeframe=bt.TimeFrame.Days,
    )


def test_check_submitted_rolls_back_failed_trial(tmp_path):
    dates = ['2020-01-01', '2020-01-02', '2020-01-03', '2020-01-04']
    rows = [(dt, 10, 10, 10, 10, 0, 0) for dt in dates]

    cerebro = bt.Cerebro()
    for name in ['equity', 'bond', 'gold', 'crypto']:
        path = tmp_path / f'{name}.csv'
        _write_csv(path, rows)
        cerebro.adddata(_make_feed(path), name=name)

    cerebro.addstrategy(SequenceStrategy)
    cerebro.broker.setcash(100.0)
    strat = cerebro.run()[0]

    by_name = {}
    for key, ref in strat.rebalance_refs.items():
        by_name[key] = strat.statuses.get(ref, [])

    assert 'Margin' in by_name['bond_buy']
    assert 'Completed' in by_name['crypto_buy']
    assert strat.getpositionbyname('equity').size == 2
    assert strat.getpositionbyname('bond').size == 0
    assert strat.getpositionbyname('gold').size == 2
    assert strat.getpositionbyname('crypto').size == 5
