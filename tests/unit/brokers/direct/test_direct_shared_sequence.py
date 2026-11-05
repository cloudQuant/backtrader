"""D62-04b1/b2: backtest and live runs of one strategy directory share its local sequence."""

from __future__ import annotations

import datetime as dt

import pytest

import backtrader as bt
from backtrader.brokers._btapi_direct_mode import DirectModeError

from ._fakes import SYMBOL, position


class _ListData(bt.feeds.DataBase):
    params = (("rows", ()),)

    def start(self):
        super().start()
        self._i = 0

    def _load(self):
        if self._i >= len(self.p.rows):
            return False
        when, price = self.p.rows[self._i]
        self._i += 1
        self.lines.datetime[0] = bt.date2num(when)
        for name in ("open", "high", "low", "close"):
            getattr(self.lines, name)[0] = price
        self.lines.volume[0] = 10.0
        self.lines.openinterest[0] = 0.0
        return True


class _ThreeOrders(bt.Strategy):
    def __init__(self):
        self.seqs = []

    def next(self):
        if len(self.seqs) < 3:
            order = self.buy(size=1)
            self.seqs.append(order.info.get("local_seq"))


def _backtest(strategy_dir):
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker = bt.brokers.BackBroker(strategy_dir=str(strategy_dir))
    rows = [(dt.datetime(2026, 11, 2) + dt.timedelta(days=i), 100.0 + i) for i in range(6)]
    cerebro.adddata(_ListData(rows=rows), name=SYMBOL)
    cerebro.addstrategy(_ThreeOrders)
    (strategy,) = cerebro.run()
    return strategy.seqs


def test_backtests_of_one_directory_continue_the_same_sequence(tmp_path):
    (tmp_path / "strategy").mkdir()  # like live_state, a missing directory is refused
    first = _backtest(tmp_path / "strategy")
    second = _backtest(tmp_path / "strategy")
    assert first == [1, 2, 3]
    assert second == [4, 5, 6]


def test_plain_backtest_without_strategy_dir_allocates_nothing(tmp_path):
    cerebro = bt.Cerebro(stdstats=False)
    rows = [(dt.datetime(2026, 11, 2) + dt.timedelta(days=i), 100.0) for i in range(4)]
    cerebro.adddata(_ListData(rows=rows), name=SYMBOL)
    cerebro.addstrategy(_ThreeOrders)
    (strategy,) = cerebro.run()
    assert strategy.seqs == [None, None, None]
    assert not (tmp_path / "strategy").exists()


def test_live_run_continues_the_backtest_sequence_after_its_own_first_init(env):
    assert _backtest(env.strategy_dir) == [1, 2, 3]
    with pytest.raises(DirectModeError) as info:
        env.start()  # identity exists (backtest) but no live snapshot yet
    assert info.value.code == "first_init_required"
    broker = env.start(first_init=True)
    order = broker.buy(
        env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, offset="open"
    )
    assert order.info["local_seq"] == 4
    assert env.state().snapshot.read()["mode"] == "live"


def test_live_first_init_of_a_backtest_directory_still_needs_a_flat_account(env):
    _backtest(env.strategy_dir)
    env.api.positions = [position("long", 1, 1, 0)]
    with pytest.raises(DirectModeError) as info:
        env.start(first_init=True)
    assert info.value.code == "first_init_requires_flat_account"
