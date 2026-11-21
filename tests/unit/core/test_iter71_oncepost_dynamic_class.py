"""Runonce must honor dynamically selected indicator state and methods."""

import math

import pandas as pd
import pytest

import backtrader as bt


def _run(strategy):
    close = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    frame = pd.DataFrame(
        {name: close for name in ("open", "high", "low", "close", "volume")},
        index=pd.date_range("2024-01-01", periods=len(close)),
    )
    engine = bt.Cerebro(stdstats=False, runonce=True, preload=True)
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.addstrategy(strategy)
    return engine.run()[0]


@pytest.mark.parametrize("descriptor", [False, True], ids=["class-attribute", "non-data-descriptor"])
def test_dynamic_once_flag_still_synchronizes_indicator_lines(descriptor):
    class Flag:
        value = False

        def __get__(self, instance, owner):
            return self.value

    flag = Flag()

    class _ToggleSMA(bt.ind.SMA):
        _once_called = flag if descriptor else False

    class Strategy(bt.Strategy):
        def __init__(self):
            self.indicator = _ToggleSMA(self.data.close, period=2)
            self.rows = []

        def next(self):
            self.rows.append((len(self), len(self.indicator), self.indicator[0]))
            if len(self) == 3:
                if descriptor:
                    flag.value = True
                else:
                    _ToggleSMA._once_called = True
                # Simulate an indicator whose counter fell behind the strategy.
                self.indicator.lines[0].lencount = 0

    result = _run(Strategy)
    assert result.rows == [(2, 2, 1.5), (3, 3, 2.5), (4, 4, 3.5), (5, 5, 4.5), (6, 6, 5.5)]



def test_data_descriptor_added_over_existing_instance_flag_is_observed():
    class _ToggleSMA(bt.ind.SMA):
        pass

    class Strategy(bt.Strategy):
        def __init__(self):
            self.indicator = _ToggleSMA(self.data.close, period=2)
            self.indicator._once_called = False
            self.rows = []

        def next(self):
            self.rows.append((len(self), len(self.indicator), self.indicator[0]))
            if len(self) == 3:
                _ToggleSMA._once_called = property(lambda _self: True)
                self.indicator.lines[0].lencount = 0

    result = _run(Strategy)
    assert result.rows == [(2, 2, 1.5), (3, 3, 2.5), (4, 4, 3.5), (5, 5, 4.5), (6, 6, 5.5)]

def test_indicator_instance_advance_override_is_called():
    class Strategy(bt.Strategy):
        def __init__(self):
            self.indicator = bt.ind.SMA(self.data.close, period=2)
            self.calls = []
            self.rows = []
            original = self.indicator.advance

            def advance(*args, **kwargs):
                self.calls.append(len(self.data))
                return original(*args, **kwargs)

            self.indicator.advance = advance

        def next(self):
            self.rows.append((len(self), len(self.indicator), self.indicator[0]))

    result = _run(Strategy)
    assert result.calls == [1, 2, 3, 4, 5, 6]
    assert result.rows == [(2, 2, 1.5), (3, 3, 2.5), (4, 4, 3.5), (5, 5, 4.5), (6, 6, 5.5)]


def test_line_lencount_setter_runs_when_counter_is_already_synchronized():
    class Strategy(bt.Strategy):
        def __init__(self):
            self.indicator = bt.ind.SMA(self.data.close, period=2)
            self.indicator._once_called = True
            line = self.indicator.lines[0]

            class _ObservedLine(type(line)):
                @property
                def lencount(self):
                    return self.__dict__["_observed_count"]

                @lencount.setter
                def lencount(self, value):
                    self.__dict__["_observed_count"] = value
                    self.__dict__.setdefault("_count_writes", []).append(value)

            line.__class__ = _ObservedLine
            line.__dict__["_observed_count"] = line.__dict__.pop("lencount")
            line.__dict__["_count_writes"] = []
            self.rows = []

        def next(self):
            line = self.indicator.lines[0]
            self.rows.append((len(self), self.indicator[0], tuple(line._count_writes)))
            line._count_writes.clear()

    result = _run(Strategy)
    # Each bar advances the line and then performs the existing post-step write.
    assert result.rows[1:] == [(3, 2.5, (3, 3)), (4, 3.5, (4, 4)), (5, 4.5, (5, 5)), (6, 5.5, (6, 6))]


@pytest.mark.parametrize("descriptor", [False, True], ids=["instance-false", "descriptor-false"])
def test_explicit_false_once_flag_takes_priority_over_internal_marker(descriptor):
    class _ToggleSMA(bt.ind.SMA):
        pass

    class Strategy(bt.Strategy):
        def __init__(self):
            self.indicator = _ToggleSMA(self.data.close, period=2)
            self.indicator._once_called = True
            self.rows = []

        def next(self):
            self.rows.append((len(self), len(self.indicator), self.indicator[0]))
            if len(self) == 3:
                if descriptor:
                    _ToggleSMA._once_called = property(lambda _self: False)
                else:
                    self.indicator._once_called = False
                self.indicator._bt_once_executed = True
                self.indicator.lines[0].lencount = 0

    result = _run(Strategy)
    assert result.rows[:2] == [(2, 2, 1.5), (3, 3, 2.5)]
    assert result.rows[2][:2] == (4, 1)
    assert math.isnan(result.rows[2][2])
    assert result.rows[3:] == [(5, 2, 1.5), (6, 3, 2.5)]


def test_other_clock_flag_exception_does_not_prevent_same_clock_sync():
    class _BadSMA(bt.ind.SMA):
        @property
        def _once_called(self):
            raise ValueError("other clock flag must not be read")

    class Strategy(bt.Strategy):
        def __init__(self):
            self.other = _BadSMA(self.data1.close, period=2)
            self.indicator = bt.ind.SMA(self.data0.close, period=2)
            self.indicator._once_called = True
            self.rows = []

        def next(self):
            self.rows.append((len(self), len(self.indicator), self.indicator[0]))
            if len(self) == 3:
                self.indicator.lines[0].lencount = 0

    close = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    frame = pd.DataFrame(
        {name: close for name in ("open", "high", "low", "close", "volume")},
        index=pd.date_range("2024-01-01", periods=len(close)),
    )
    engine = bt.Cerebro(stdstats=False, runonce=True, preload=True)
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.addstrategy(Strategy)
    result = engine.run()[0]
    assert result.other._clock is not result._clock
    assert result.rows == [(2, 2, 1.5), (3, 3, 2.5), (4, 4, 3.5), (5, 5, 4.5), (6, 6, 5.5)]


def test_later_same_clock_flag_error_preserves_prior_indicator_sync():
    class _BadSMA(bt.ind.SMA):
        @property
        def _once_called(self):
            raise ValueError("later indicator flag")

    class Strategy(bt.Strategy):
        def __init__(self):
            self.indicator = bt.ind.SMA(self.data.close, period=2)
            self.indicator._once_called = True
            self.bad = _BadSMA(self.data.close, period=2)
            self.rows = []

        def next(self):
            self.rows.append((len(self), len(self.indicator), self.indicator[0]))
            if len(self) == 3:
                self.indicator.lines[0].lencount = 0

    result = _run(Strategy)
    assert result.bad._clock is result._clock
    assert result.rows == [(2, 2, 1.5), (3, 3, 2.5), (4, 4, 3.5), (5, 5, 4.5), (6, 6, 5.5)]


def test_stateful_flag_descriptor_keeps_existing_two_reads_per_bar():
    class _ToggleSMA(bt.ind.SMA):
        pass

    calls = []

    def changing_flag(_indicator):
        calls.append(None)
        return len(calls) % 2 == 0

    class Strategy(bt.Strategy):
        def __init__(self):
            self.indicator = _ToggleSMA(self.data.close, period=2)
            self.rows = []

        def next(self):
            self.rows.append((len(self), len(self.indicator), self.indicator[0]))
            if len(self) == 3:
                _ToggleSMA._once_called = property(changing_flag)
                self.indicator.lines[0].lencount = 0

    result = _run(Strategy)
    assert result.rows == [(2, 2, 1.5), (3, 3, 2.5), (4, 4, 3.5), (5, 5, 4.5), (6, 6, 5.5)]
    assert len(calls) == 6


def test_notify_replacing_indicator_list_changes_post_step_sync_target():
    from backtrader.lineiterator import LineIterator

    class Strategy(bt.Strategy):
        def __init__(self):
            self.first = bt.ind.SMA(self.data.close, period=2)
            self.second = bt.ind.SMA(self.data.close, period=3)
            self.first._once_called = True
            self.second._once_called = True
            self.swapped = False
            self.rows = []

        def _notify(self, *args, **kwargs):
            super()._notify(*args, **kwargs)
            if len(self) == 3 and not self.swapped:
                self.first.lines[0].lencount = 0
                self.second.lines[0].lencount = 0
                self._lineiterators[LineIterator.IndType] = [self.second]
                self.swapped = True

        def next(self):
            self.rows.append((len(self), len(self.first), len(self.second)))

    result = _run(Strategy)
    assert result.rows == [(3, 0, 3), (4, 0, 4), (5, 0, 5), (6, 0, 6)]


def test_dynamic_indicator_clock_is_checked_outside_and_inside_advance():
    class _AlternatingClock:
        def __init__(self):
            self.values = []

        def __len__(self):
            value = 100 if len(self.values) % 2 == 0 else 0
            self.values.append(value)
            return value

    class Strategy(bt.Strategy):
        def __init__(self):
            self.indicator = bt.ind.SMA(self.data.close, period=2)
            self.rows = []
            self.clock = _AlternatingClock()

        def next(self):
            self.rows.append((len(self), len(self.indicator), self.indicator[0]))
            if len(self) == 3:
                self.indicator._clock = self.clock

    result = _run(Strategy)
    assert result.rows == [(2, 2, 1.5), (3, 3, 2.5), (4, 3, 2.5), (5, 3, 2.5), (6, 3, 2.5)]
    assert result.clock.values == [100, 0, 100, 0, 100, 0]


def test_clock_alias_probe_does_not_invoke_custom_lines_or_dict_descriptors():
    from backtrader.linebuffer import LineBuffer
    from backtrader.strategy import _safe_indicator_clock_alias

    class _CustomLines:
        @property
        def lines(self):
            raise AssertionError("lines descriptor must not be invoked")

    class _CustomDict:
        @property
        def __dict__(self):
            raise AssertionError("dict descriptor must not be invoked")

    clock = LineBuffer()
    assert not _safe_indicator_clock_alias(_CustomLines(), clock)
    assert not _safe_indicator_clock_alias(_CustomDict(), clock)


def test_clock_alias_probe_does_not_invoke_custom_metaclass_or_module():
    from backtrader.linebuffer import LineBuffer
    from backtrader.strategy import _safe_indicator_clock_alias

    class _Meta(type):
        def __getattribute__(cls, name):
            if name == "__getattribute__":
                raise AssertionError("custom metaclass must not be invoked")
            return super().__getattribute__(name)

    class _WithMeta(metaclass=_Meta):
        pass

    class _Module:
        def startswith(self, _prefix):
            raise AssertionError("custom module must not be invoked")

    class _WithModule:
        pass

    _WithModule.__module__ = _Module()
    clock = LineBuffer()
    assert not _safe_indicator_clock_alias(_WithMeta(), clock)
    assert not _safe_indicator_clock_alias(_WithModule(), clock)


def test_clock_alias_probe_does_not_invoke_class_getattribute_descriptor():
    from backtrader.linebuffer import LineBuffer
    from backtrader.strategy import _safe_indicator_clock_alias

    class _GetAttribute:
        def __get__(self, instance, owner):
            if instance is None:
                raise AssertionError("class descriptor must not be invoked")
            return object.__getattribute__.__get__(instance, owner)

    class _Custom:
        __getattribute__ = _GetAttribute()

    assert not _safe_indicator_clock_alias(_Custom(), LineBuffer())
