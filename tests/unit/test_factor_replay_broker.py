"""Actual Cerebro/BackBroker matching after immutable source availability."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import backtrader as bt
from backtrader.brokers.factor_replay import CausalReplayBroker, ReplayBarTiming


BASE = datetime(2026, 10, 21, 2, 0, tzinfo=timezone.utc)


def _fixture(delay=2):
    timings = tuple(
        ReplayBarTiming(
            BASE + timedelta(minutes=index - 1),
            BASE + timedelta(minutes=index),
            BASE + timedelta(minutes=index, seconds=delay),
        )
        for index in range(5)
    )
    frame = pd.DataFrame(
        {
            "open": [100.0, 10.0, 30.0, 40.0, 50.0],
            "high": [101.0, 11.0, 31.0, 41.0, 51.0],
            "low": [99.0, 9.0, 29.0, 39.0, 49.0],
            "close": [100.0, 10.0, 30.0, 40.0, 50.0],
            "volume": [100.0] * 5,
        },
        index=pd.DatetimeIndex([item.end for item in timings]),
    )
    return bt.feeds.PandasData(dataname=frame), timings


def _run(*, delay=2, exectype=bt.Order.Market, cutoff="valid", mutate=False, cancel=False):
    data, timings = _fixture(delay)
    broker = CausalReplayBroker(cash=1000.0)
    broker.bind_data_timing(data, timings)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.setbroker(broker)
    cerebro.adddata(data)

    class Strategy(bt.Strategy):
        def __init__(self):
            self.order = None
            self.events = []
            self.positions_seen = []

        def next(self):
            self.positions_seen.append(self.position.size)
            if len(self) == 1:
                info = {}
                if cutoff != "missing":
                    value = timings[0].available_at
                    if cutoff == "early":
                        value = timings[0].end
                    elif cutoff == "naive":
                        value = value.replace(tzinfo=None)
                    info["decision_available_at"] = value
                self.order = self.buy(size=1, exectype=exectype, price=100.0, **info)
                if mutate:
                    self.order.addinfo(decision_available_at=BASE - timedelta(days=1))
            elif len(self) == 2 and cancel:
                self.cancel(self.order)

        def notify_order(self, order):
            self.events.append((order.status, order.executed.size, order.executed.price))

    cerebro.addstrategy(Strategy)
    strategy = cerebro.run(runonce=False, preload=False)[0]
    return strategy, broker, data, timings


@pytest.mark.parametrize("exectype", [bt.Order.Market, bt.Order.Limit])
def test_delayed_bar_cannot_fill_at_earlier_open(exectype):
    strategy, broker, data, timings = _run(exectype=exectype)
    assert strategy.order.status == bt.Order.Completed
    assert strategy.order.executed.price == 30.0
    assert strategy.positions_seen[:3] == [0, 0, 1]
    assert broker.getposition(data).size == 1
    assert broker.getcash() == 970.0
    assert [row[0] for row in strategy.events] == [
        bt.Order.Submitted,
        bt.Order.Accepted,
        bt.Order.Completed,
    ]
    assert not broker._replay_order_cutoffs
    assert broker.current_bar_timing(data) is timings[-1]


def test_exact_open_boundary_is_eligible_when_data_is_already_available():
    strategy, broker, _data, _timings = _run(delay=0)
    assert strategy.order.status == bt.Order.Completed
    assert strategy.order.executed.price == 10.0
    assert broker.getcash() == 990.0


@pytest.mark.parametrize("cutoff", ["missing", "early", "naive"])
def test_missing_or_invalid_decision_time_rejects_through_real_notifications(cutoff):
    strategy, broker, data, _timings = _run(cutoff=cutoff)
    assert strategy.order.status == bt.Order.Rejected
    assert strategy.order.info.replay_rejection == "REPLAY_SUBMISSION_TIME_INVALID"
    assert strategy.order.executed.size == 0
    assert broker.getposition(data).size == 0
    assert [row[0] for row in strategy.events] == [bt.Order.Rejected]


def test_mutating_public_order_info_does_not_backdate_sealed_decision():
    strategy, broker, data, _timings = _run(mutate=True)
    assert strategy.order.status == bt.Order.Rejected
    assert strategy.order.info.replay_rejection == "REPLAY_MATCH_TIME_INVALID"
    assert broker.getposition(data).size == 0
    assert bt.Order.Completed not in [row[0] for row in strategy.events]


def test_cancel_waiting_order_uses_normal_broker_lifecycle():
    strategy, broker, data, _timings = _run(cancel=True)
    assert strategy.order.status == bt.Order.Canceled
    assert strategy.order.executed.size == 0
    assert broker.getposition(data).size == 0
    assert not broker._replay_order_cutoffs


def test_timing_is_immutable_bounded_and_requires_ordered_bar_labels():
    data, timings = _fixture()
    broker = CausalReplayBroker()
    with pytest.raises(FrozenInstanceError):
        timings[0].available_at = BASE
    with pytest.raises(ValueError, match="already bound"):
        broker.bind_data_timing(data, timings)
        broker.bind_data_timing(data, timings)
    data2, _ = _fixture()
    with pytest.raises(ValueError, match="nonempty finite"):
        broker.bind_data_timing(data2, iter(timings))
    with pytest.raises(ValueError, match="nonoverlapping"):
        CausalReplayBroker().bind_data_timing(data, tuple(reversed(timings)))
    limited = CausalReplayBroker()
    limited.MAX_TOTAL_TIMINGS = 4
    with pytest.raises(ValueError, match="capacity"):
        limited.bind_data_timing(data, timings)
    with pytest.raises(ValueError):
        ReplayBarTiming(BASE, BASE + timedelta(minutes=1), BASE)


def test_out_of_order_source_availability_is_preserved_without_backdated_fill():
    data, timings = _fixture()
    delayed = (ReplayBarTiming(timings[0].start, timings[0].end, BASE + timedelta(seconds=90)),)
    delayed += timings[1:]
    assert delayed[0].available_at > delayed[1].available_at
    broker = CausalReplayBroker(cash=1000.0)
    broker.bind_data_timing(data, delayed)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(data)
    cerebro.setbroker(broker)

    class Strategy(bt.Strategy):
        def next(self):
            if len(self) == 1:
                self.order = self.buy(size=1, decision_available_at=delayed[0].available_at)

    cerebro.addstrategy(Strategy)
    strategy = cerebro.run(runonce=False, preload=False)[0]
    assert strategy.order.executed.price == 40.0
    assert strategy.order.status == bt.Order.Completed


@pytest.mark.parametrize("use_complete_batch", [False, True])
def test_untraded_member_availability_also_constrains_the_order(use_complete_batch):
    first, timings = _fixture()
    second, _ = _fixture()
    later = tuple(
        ReplayBarTiming(t.start, t.end, t.available_at + timedelta(seconds=90)) for t in timings
    )
    broker = CausalReplayBroker(cash=1000.0)
    broker.bind_data_timing(first, timings)
    broker.bind_data_timing(second, later)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(first)
    cerebro.adddata(second)
    cerebro.setbroker(broker)

    class Strategy(bt.Strategy):
        def next(self):
            if len(self) == 1:
                cutoff = (
                    broker.current_decision_floor()
                    if use_complete_batch
                    else timings[0].available_at
                )
                self.order = self.buy(data=first, size=1, decision_available_at=cutoff)

    cerebro.addstrategy(Strategy)
    strategy = cerebro.run(runonce=False, preload=False)[0]
    if use_complete_batch:
        assert strategy.order.status == bt.Order.Completed
        assert strategy.order.executed.price == 40.0
    else:
        assert strategy.order.status == bt.Order.Rejected
        assert strategy.order.executed.size == 0


@pytest.mark.parametrize("mode", ["coc", "coo"])
def test_cheat_modes_cannot_bypass_source_time_admission(mode):
    data, timings = _fixture()
    broker = CausalReplayBroker(**{mode: True})
    broker.bind_data_timing(data, timings)
    with pytest.raises(ValueError, match="cheat"):
        broker.start()


def test_replay_binding_cannot_change_during_or_after_run():
    _strategy, broker, data, timings = _run()
    with pytest.raises(ValueError, match="after start"):
        broker.bind_data_timing(data, timings)
    with pytest.raises(ValueError, match="one run"):
        broker.start()
