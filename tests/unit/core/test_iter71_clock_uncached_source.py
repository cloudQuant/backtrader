from pathlib import Path

import pandas as pd
import pytest

import backtrader as bt
import backtrader.lineiterator as module
from backtrader.linebuffer import LineActions
from backtrader.lineiterator import _lineaction_source_clock


class Clock:
    def __init__(self, n):
        self.n = n

    def __len__(self):
        return self.n


class Action(LineActions):
    @property
    def _clock(self):
        state = object.__getattribute__(self, "__dict__")
        state["reads"] += 1
        if state.get("broken"):
            raise ValueError("clock sentinel")
        return state.get("current")


def new_action(clock):
    a = object.__new__(Action)
    a.__dict__.update({"reads": 0, "current": clock})
    return a


def test_dynamic_clock_replacement_without_manual_cache_invalidation():
    a = new_action(Clock(1))
    old = a.__dict__["current"]
    assert _lineaction_source_clock(a) is old
    changed = Clock(2)
    a.__dict__["current"] = changed
    assert _lineaction_source_clock(a) is changed and a.__dict__["reads"] == 2
    assert "_lineaction_source_clock_cache" not in a.__dict__


def test_dynamic_clock_exception_and_read_count():
    a = new_action(Clock(1))
    a.__dict__["broken"] = True
    with pytest.raises(ValueError, match="clock sentinel"):
        _lineaction_source_clock(a)
    assert a.__dict__["reads"] == 1


def test_nested_source_dynamic_replacement():
    first = Clock(1)
    second = Clock(2)
    b = new_action(first)
    a = new_action(b)
    assert _lineaction_source_clock(a) is first
    b.__dict__["current"] = second
    assert _lineaction_source_clock(a) is second
    assert (a.__dict__["reads"], b.__dict__["reads"]) == (2, 2)


def test_external_seen_rejects_cycle_without_getter():
    a = new_action(None)
    assert _lineaction_source_clock(a, {id(a)}) is None
    assert a.__dict__["reads"] == 0


@pytest.mark.parametrize("bounded", [False, True])
def test_real_cerebro_resolves_changed_action_clock(bounded):
    assert (
        Path(module.__file__).resolve()
        == (
            Path(__file__).resolve().parents[3] / "backtrader" / "lineiterator.py"
        ).resolve()
    )

    class S(bt.Strategy):
        def __init__(self):
            self.expr = self.data0.close + 1.0
            self.ind = bt.ind.SMA(self.expr, period=2)
            self.observed = []

        def next(self):
            n = len(self.data0)
            if n == 3:
                self.expr._clock = self.data1
            if n in (4, 5):
                self.observed.append(
                    (
                        n,
                        self.ind._clock is self.data1,
                        "_lineaction_source_clock_cache" in self.expr.__dict__,
                    )
                )

    f = pd.DataFrame(
        {
            "open": [1.0] * 12,
            "high": [2.0] * 12,
            "low": [0.0] * 12,
            "close": [1.0] * 12,
            "volume": [1.0] * 12,
        },
        index=pd.date_range("2024-01-01", periods=12, freq="min"),
    )
    c = bt.Cerebro(
        stdstats=False, runonce=False, exactbars=int(bounded), preload=not bounded
    )
    c.adddata(bt.feeds.PandasData(dataname=f))
    c.adddata(bt.feeds.PandasData(dataname=f))
    c.addstrategy(S)
    assert c.run()[0].observed == [(4, True, False), (5, True, False)]
