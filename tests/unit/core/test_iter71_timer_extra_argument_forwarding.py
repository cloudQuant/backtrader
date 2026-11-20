"""Regression coverage for timer callback argument forwarding."""

from __future__ import annotations

import datetime

import pytest

pd = pytest.importorskip("pandas")

import backtrader as bt


_TIMER_TIME = datetime.time(9, 30)
_COMMON_TIMER_ARGS = (
    _TIMER_TIME,
    datetime.timedelta(),
    datetime.timedelta(),
    None,
    False,
    None,
    True,
    None,
    None,
)


class _TimerArgumentProbe(bt.Strategy):
    _timer_callback_kwargs = {
        "owner": "strategy-callback-owner",
        "strats": "strategy-callback-strats",
        "source": "strategy",
        "keyword_token": 23,
    }

    def __init__(self):
        self.timer_events = []
        strategy_timer_args = _COMMON_TIMER_ARGS + (False, "strategy-positional")
        self.strategy_timer = self.add_timer(*strategy_timer_args, **self._timer_callback_kwargs)

    def notify_timer(self, timer, when, *args, **kwargs):
        self.timer_events.append((timer, when, args, kwargs))


class _TimerOwnerCerebro(bt.Cerebro):
    def __init__(self, *args, **kwargs):
        self.timer_events = []
        super().__init__(*args, **kwargs)

    def notify_timer(self, timer, when, *args, **kwargs):
        self.timer_events.append((timer, when, args, kwargs))


def _cerebro_with_probe(strategy_count=1, strategy_cls=_TimerArgumentProbe):
    index = pd.to_datetime(
        ["2024-01-02 09:30:00", "2024-01-02 09:31:00", "2024-01-02 09:32:00"]
    )
    closes = [100.0, 101.0, 102.0]
    frame = pd.DataFrame(
        {
            "Open": closes,
            "High": [value + 1.0 for value in closes],
            "Low": [value - 1.0 for value in closes],
            "Close": closes,
            "Volume": [1000, 1001, 1002],
            "OpenInterest": [0, 0, 0],
        },
        index=index,
    )
    data = bt.feeds.PandasData(
        dataname=frame,
        sessionstart=datetime.time(9, 30),
        sessionend=datetime.time(16, 0),
    )
    cerebro = _TimerOwnerCerebro(runonce=False, stdstats=False)
    cerebro.adddata(data)
    for _ in range(strategy_count):
        cerebro.addstrategy(strategy_cls)
    return cerebro


def test_cerebro_timer_forwards_owner_kwarg_and_broadcasts_once_to_each_strategy():
    cerebro = _cerebro_with_probe(strategy_count=2)
    callback_args = _COMMON_TIMER_ARGS + (True, False, "cerebro-positional")

    timer = cerebro.add_timer(
        *callback_args,
        owner="cerebro-callback-owner",
        keyword_token=17,
    )
    strategies = cerebro.run()

    assert timer.params.owner is cerebro
    assert timer.params.strats is True
    assert timer.args == ("cerebro-positional",)
    assert timer.kwargs == {"owner": "cerebro-callback-owner", "keyword_token": 17}
    assert len(cerebro.timer_events) == 1
    assert cerebro.timer_events[0][0] is timer
    assert cerebro.timer_events[0][2:] == (
        ("cerebro-positional",),
        {"owner": "cerebro-callback-owner", "keyword_token": 17},
    )
    for strategy in strategies:
        strategy_notifications = [
            event for event in strategy.timer_events if event[0] is timer
        ]
        assert len(strategy_notifications) == 1
        assert strategy_notifications[0][2:] == (
            ("cerebro-positional",),
            {"owner": "cerebro-callback-owner", "keyword_token": 17},
        )


@pytest.mark.parametrize(
    "callback_kwargs",
    [
        pytest.param({"owner": "strategy-callback-owner"}, id="owner"),
        pytest.param({"strats": "strategy-callback-strats"}, id="strats"),
        pytest.param(
            {
                "owner": "strategy-callback-owner",
                "strats": "strategy-callback-strats",
                "source": "strategy",
                "keyword_token": 23,
            },
            id="both-reserved-keywords",
        ),
    ],
)
def test_strategy_timer_forwards_callback_args_and_kwargs(callback_kwargs):
    strategy_cls = type(
        "ReservedKeywordTimerProbe",
        (_TimerArgumentProbe,),
        {"_timer_callback_kwargs": callback_kwargs},
    )
    cerebro = _cerebro_with_probe(strategy_cls=strategy_cls)

    strategy = cerebro.run()[0]

    assert strategy.strategy_timer.params.owner is strategy
    assert strategy.strategy_timer.params.strats is False
    assert strategy.strategy_timer.args == ("strategy-positional",)
    assert strategy.strategy_timer.kwargs == callback_kwargs
    strategy_notifications = [
        event for event in strategy.timer_events if event[0] is strategy.strategy_timer
    ]
    assert len(strategy_notifications) == 1
    timer, _when, args, kwargs = strategy_notifications[0]
    assert timer is strategy.strategy_timer
    assert args == ("strategy-positional",)
    assert kwargs == callback_kwargs
