"""Iteration 60 F5: TradeAnalyzer applies fee-only corrections to closed trades."""

from __future__ import annotations

import datetime as dt

import backtrader as bt
import pytest


class _RoundTrip(bt.Strategy):
    params = (("delta", 1.5), ("flip", False))

    def __init__(self):
        self.closed_trade = None
        self.corrected = False

    def next(self):
        if len(self) == 2:
            self.buy(size=1)
        elif len(self) == 4:
            self.close()
        elif self.closed_trade is not None and not self.corrected:
            delta = self.p.delta
            if self.p.flip:
                delta = self.closed_trade.pnlcomm + 10.0  # pushes a winner below zero
            trade = self.closed_trade
            trade.commission += delta
            trade.pnlcomm = trade.pnl - trade.commission
            for analyzer in self.analyzers:
                analyzer.notify_fee_correction(None, trade, delta, "USD")
            self.corrected = True
            self.applied_delta = delta

    def notify_trade(self, trade):
        if trade.isclosed:
            self.closed_trade = trade


def _run(**params):
    base = dt.datetime(2024, 1, 1)
    closes = [10.0, 10.0, 10.0, 12.0, 12.0, 12.0, 12.0, 12.0]
    import pandas as pd

    frame = pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [100.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=[base + dt.timedelta(days=i) for i in range(len(closes))],
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(_RoundTrip, **params)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="ta")
    strategy = cerebro.run()[0]
    return strategy, strategy.analyzers.ta.get_analysis()


def test_correction_reduces_net_totals_of_the_counted_buckets():
    _, before = _run(delta=0.0)
    strategy, after = _run(delta=1.5)
    assert strategy.corrected
    assert after.pnl.net.total == pytest.approx(before.pnl.net.total - 1.5)
    assert after.won.pnl.total == pytest.approx(before.won.pnl.total - 1.5)
    assert after.long.pnl.total == pytest.approx(before.long.pnl.total - 1.5)
    assert after.long.pnl.won.total == pytest.approx(before.long.pnl.won.total - 1.5)
    assert after.pnl.gross.total == pytest.approx(before.pnl.gross.total)
    assert after.fee_corrections.count == 1
    assert after.fee_corrections.total == pytest.approx(1.5)
    assert after.fee_corrections.currencies == ("USD",)
    assert "reclassification_pending" not in after.fee_corrections


def test_zero_correction_leaves_the_analysis_unchanged():
    _, analysis = _run(delta=0.0)
    assert "fee_corrections" not in analysis


def test_sign_flip_is_reported_not_silently_rebucketed():
    strategy, after = _run(flip=True)
    assert strategy.closed_trade.pnlcomm < 0
    assert after.won.total == 1 and after.lost.total == 0  # buckets unchanged
    assert after.fee_corrections.reclassification_pending == 1
