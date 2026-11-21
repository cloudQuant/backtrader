"""Indicator.advance must honor dynamic clocks and their access semantics."""

import pandas as pd
import pytest

import backtrader as bt


class AlternatingClockSMA(bt.ind.SMA):
    pass


class RaisingClockSMA(bt.ind.SMA):
    pass


class SecondaryDescriptorSMA(bt.ind.SMA):
    pass


def _run(strategy):
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    frame = pd.DataFrame(
        dict.fromkeys(("open", "high", "low", "close", "volume"), values),
        index=pd.date_range("2024-01-01", periods=len(values)),
    )
    engine = bt.Cerebro(stdstats=False, runonce=True, preload=True)
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.addstrategy(strategy)
    return engine.run()[0]


def test_dynamic_clock_descriptor_is_read_inside_indicator_advance(monkeypatch):
    class AlternatingClock:
        def __init__(self):
            self.reads = []

        def __len__(self):
            value = 100 if len(self.reads) % 2 == 0 else 0
            self.reads.append(value)
            return value

    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = AlternatingClockSMA(self.data.close, period=2)
            self.rows = []
            self.clock = AlternatingClock()
            self.getter_reads = 0

        def next(self):
            self.rows.append((len(self), len(self.ind), self.ind[0]))
            if len(self) == 3:
                def clock_property(_indicator):
                    self.getter_reads += 1
                    return self.clock

                monkeypatch.setattr(AlternatingClockSMA, "_clock", property(clock_property), raising=False)

    result = _run(Strategy)
    assert result.rows == [(2, 2, 1.5), (3, 3, 2.5), (4, 3, 2.5), (5, 3, 2.5), (6, 3, 2.5)]
    assert result.clock.reads == [100, 0, 100, 0, 100, 0]
    assert result.getter_reads == 10


def test_clock_descriptor_exception_propagates_from_advance(monkeypatch):
    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = RaisingClockSMA(self.data.close, period=2)

    result = _run(Strategy)

    def failed_clock(_indicator):
        raise ValueError("dynamic clock failed")

    monkeypatch.setattr(RaisingClockSMA, "_clock", property(failed_clock), raising=False)
    with pytest.raises(ValueError, match="dynamic clock failed"):
        result.ind.advance()


def test_false_secondary_clock_uses_primary_clock_and_checks_truth():
    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = bt.ind.SMA(self.data.close, period=2)

    result = _run(Strategy)

    class Clock:
        def __init__(self, length):
            self.length = length
            self.reads = 0

        def __len__(self):
            self.reads += 1
            return self.length

    secondary, primary = Clock(0), Clock(100)
    result.ind._resolved_secondary_clock = secondary
    result.ind._clock = primary
    before = len(result.ind)
    result.ind.advance()
    assert len(result.ind) == before + 1
    assert (secondary.reads, primary.reads) == (1, 1)


def test_secondary_descriptor_overrides_instance_value(monkeypatch):
    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = SecondaryDescriptorSMA(self.data.close, period=2)

    indicator = _run(Strategy).ind
    indicator._resolved_secondary_clock = None

    class Clock:
        reads = 0

        def __len__(self):
            self.reads += 1
            return 100

    clock = Clock()
    reads = []

    def secondary_property(_indicator):
        reads.append(None)
        return clock

    monkeypatch.setattr(
        SecondaryDescriptorSMA, "_resolved_secondary_clock", property(secondary_property), raising=False
    )
    before = len(indicator)
    indicator.advance()
    assert len(indicator) == before + 1
    assert len(reads) == 1
    assert clock.reads == 2  # truth test, then comparison


def test_external_line_clock_does_not_read_custom_lines_property():
    class Host:
        _resolved_secondary_clock = bt.LineBuffer()
        _clock = ()

        def __len__(self):
            return 1

        @property
        def lines(self):
            raise ValueError("lines getter must not be read")

    bt.Indicator.advance(Host())


def test_external_line_clock_does_not_read_custom_dict_property():
    class Host:
        _resolved_secondary_clock = bt.LineBuffer()
        _clock = ()

        def __len__(self):
            return 1

        @property
        def __dict__(self):
            raise ValueError("dict getter must not be read")

    bt.Indicator.advance(Host())


def test_external_line_clock_does_not_access_getattribute_descriptor_on_class():
    class InstanceOnlyGetattribute:
        def __get__(self, instance, owner):
            if instance is None:
                raise ValueError("class descriptor must not be read")
            return object.__getattribute__.__get__(instance, owner)

    class Host:
        __getattribute__ = InstanceOnlyGetattribute()
        _resolved_secondary_clock = bt.LineBuffer()
        _clock = ()

        def __len__(self):
            return 1

    bt.Indicator.advance(Host())


def test_external_line_clock_does_not_access_custom_metaclass_mro():
    class Meta(type):
        @property
        def __mro__(cls):
            raise ValueError("metaclass mro getter must not be read")

    class Host(metaclass=Meta):
        _resolved_secondary_clock = bt.LineBuffer()
        _clock = ()

        def __len__(self):
            return 1

    bt.Indicator.advance(Host())


def test_external_line_clock_does_not_access_descriptor_type_metaclass():
    class Meta(type):
        def __getattribute__(cls, name):
            if name in ("__set__", "__delete__"):
                raise ValueError("descriptor metaclass must not be read")
            return super().__getattribute__(name)

    class Descriptor(metaclass=Meta):
        def __get__(self, instance, owner):
            return None

    class Host:
        lines = Descriptor()
        _resolved_secondary_clock = bt.LineBuffer()
        _clock = ()

        def __len__(self):
            return 1

    bt.Indicator.advance(Host())


def test_external_line_clock_does_not_use_custom_module_value():
    class ModuleValue:
        def startswith(self, prefix):
            raise ValueError("module value must not be called")

    class Host:
        _resolved_secondary_clock = bt.LineBuffer()
        _clock = ()

        def __len__(self):
            return 1

    Host.__module__ = ModuleValue()
    bt.Indicator.advance(Host())


def test_advance_does_not_truth_test_child_indicator_iterable():
    from backtrader.lineiterator import LineIterator

    class Children:
        def __bool__(self):
            raise ValueError("child iterable must not be truth tested")

        def __iter__(self):
            return iter(())

    class Lines:
        advances = 0

        def advance(self, size):
            self.advances += size

    class Host:
        _resolved_secondary_clock = None
        _clock = (0, 0)
        _lineiterators = {LineIterator.IndType: Children()}
        lines = Lines()

        def __len__(self):
            return 1

    host = Host()
    bt.Indicator.advance(host)
    assert host.lines.advances == 1
