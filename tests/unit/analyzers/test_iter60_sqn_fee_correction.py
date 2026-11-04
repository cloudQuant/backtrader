"""Iteration 60: SQN uses a closed trade's corrected net P&L after a late fee.

SQN stores each closed trade's ``pnlcomm`` and computes at ``stop``; a later
fee-only correction (``notify_fee_correction``) must replace that stored
value, or the quality number keeps the uncorrected profit.
"""

from __future__ import annotations

import datetime as dt
import math

import pandas as pd
import pytest

import backtrader as bt


class _TwoRoundTrips(bt.Strategy):
    params = (("delta", 0.0),)

    def __init__(self):
        self.closed = []
        self.corrected = False

    def next(self):
        if len(self) in (2, 6):
            self.buy(size=1)
        elif len(self) in (4, 8):
            self.close()
        elif len(self) == 10 and self.p.delta and not self.corrected:
            trade = self.closed[0]
            trade.commission += self.p.delta
            trade.pnlcomm = trade.pnl - trade.commission
            for analyzer in self.analyzers:
                analyzer.notify_fee_correction(None, trade, self.p.delta, "USD")
            self.corrected = True

    def notify_trade(self, trade):
        if trade.isclosed:
            self.closed.append(trade)


def _run(delta):
    base = dt.datetime(2024, 1, 1)
    closes = [10.0, 10.0, 10.0, 12.0, 12.0, 11.0, 11.0, 14.0, 14.0, 14.0, 14.0, 14.0]
    frame = pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes,
         "volume": [100.0] * len(closes), "openinterest": [0.0] * len(closes)},
        index=[base + dt.timedelta(days=i) for i in range(len(closes))],
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(_TwoRoundTrips, delta=delta)
    cerebro.addanalyzer(bt.analyzers.SQN, _name="sqn")
    strategy = cerebro.run()[0]
    return strategy, strategy.analyzers.sqn


def test_a_late_fee_changes_the_stored_trade_pnl_and_the_sqn():
    _, plain = _run(0.0)
    strategy, corrected = _run(0.5)
    assert strategy.corrected and len(strategy.closed) == 2
    assert corrected.pnl[0] == pytest.approx(plain.pnl[0] - 0.5)
    assert corrected.pnl[1] == pytest.approx(plain.pnl[1])
    # stop() computed the number from the corrected list (same formula as SQN).
    from backtrader.mathsupport import average, standarddev

    pnl = corrected.pnl
    expected = math.sqrt(len(pnl)) * average(pnl) / standarddev(pnl)
    assert corrected.get_analysis().sqn == pytest.approx(expected)
    assert corrected.get_analysis().sqn != pytest.approx(plain.get_analysis().sqn)


def test_a_correction_for_an_unseen_trade_is_ignored():
    _, analyzer = _run(0.0)
    unseen = type("T", (), {"ref": 10_000, "pnlcomm": -99.0})()
    before = list(analyzer.pnl)
    analyzer.notify_fee_correction(None, unseen, 1.0, "USD")
    analyzer.notify_fee_correction(None, None, 1.0, "USD")
    assert analyzer.pnl == before
