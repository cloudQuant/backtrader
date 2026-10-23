"""Focused Strategy._periodset traversal and clock-resolution coverage."""

from types import SimpleNamespace

import pytest

from backtrader.lineiterator import LineIterator
from backtrader.lineseries import Lines, MinimalClock
from backtrader.strategy import Strategy


def test_periodset_handles_shared_unhashable_tree_and_minimal_clock_precedence():
    """Shared indicators resolve once while feed/line clock owners keep order."""

    shared_line = object()

    class Feed:
        def __init__(self, lines, minperiod):
            self.lines = lines
            self._minperiod = minperiod

    class Indicator:
        __hash__ = None

        def __init__(self, data, children, minperiod):
            self.datas = (data,)
            self._children = children
            self._children_reads = 0
            self._clock = MinimalClock()
            self._minperiod_value = minperiod
            self._minperiod_reads = 0

        @property
        def _lineiterators(self):
            self._children_reads += 1
            return {LineIterator.IndType: self._children}

        @property
        def _minperiod(self):
            self._minperiod_reads += 1
            return self._minperiod_value

    def native_lines(*items):
        lines = Lines()
        lines.lines.extend(items)
        return lines

    primary = Feed(native_lines(shared_line), minperiod=2)
    secondary = Feed(native_lines(shared_line), minperiod=3)
    tertiary = Feed(native_lines(), minperiod=4)

    shared = Indicator(shared_line, [], minperiod=11)
    leaf = Indicator(shared_line, [], minperiod=13)
    left = Indicator(shared_line, [shared], minperiod=5)
    right = Indicator(shared_line, [shared, leaf], minperiod=7)
    direct_tertiary = Indicator(tertiary, [], minperiod=17)

    subject = SimpleNamespace(
        datas=[primary, secondary, tertiary],
        _lineiterators={LineIterator.IndType: [left, right, direct_tertiary]},
        _minperiod=1,
    )
    subject._get_strategy_lineactions = lambda: ()

    Strategy._periodset(subject)

    # MinimalClock fallback keeps the original first-feed owner for an input
    # line present in multiple feeds, while source attribution keeps its
    # separate last-owner behavior for the resolved secondary advance clock.
    assert [lineiter._clock for lineiter in (left, right, shared, leaf)] == [
        primary,
        primary,
        primary,
        primary,
    ]
    assert [
        lineiter._resolved_secondary_clock
        for lineiter in (left, right, shared, leaf)
    ] == [secondary, secondary, secondary, secondary]

    # A feed itself is also found by the precomputed owner map.
    assert direct_tertiary._clock is tertiary
    assert direct_tertiary._resolved_secondary_clock is tertiary
    assert subject._minperiods == [13, 3, 17]
    assert subject._minperiod == 17

    # The shared, unhashable node is visited once despite appearing in both
    # branches of the breadth-first indicator tree.
    assert [lineiter._children_reads for lineiter in (left, right, shared, leaf)] == [
        1,
        1,
        1,
        1,
    ]
    assert [
        lineiter._minperiod_reads
        for lineiter in (left, right, shared, leaf, direct_tertiary)
    ] == [2, 2, 2, 2, 2]


def test_periodset_keeps_original_scan_for_custom_line_iterables():
    """Custom line containers retain per-indicator iteration semantics."""

    shared_line = object()

    class DynamicLines:
        def __init__(self, snapshots):
            self._snapshots = iter(snapshots)
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            return iter(next(self._snapshots))

    class NonIterableLines:
        def __init__(self):
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            raise TypeError("synthetic line iteration failure")

    class Feed:
        def __init__(self, lines, minperiod):
            self.lines = lines
            self._minperiod = minperiod

    class Indicator:
        def __init__(self, data, minperiod):
            self.datas = (data,)
            self._clock = MinimalClock()
            self._minperiod = minperiod

    dynamic_lines = DynamicLines([[], [shared_line], [shared_line]])
    primary = Feed(dynamic_lines, minperiod=2)
    secondary_lines = Lines()
    secondary_lines.lines.append(shared_line)
    secondary = Feed(secondary_lines, minperiod=3)
    indicator = Indicator(shared_line, minperiod=5)
    subject = SimpleNamespace(
        datas=[primary, secondary],
        _lineiterators={LineIterator.IndType: [indicator]},
        _minperiod=1,
    )
    subject._get_strategy_lineactions = lambda: ()

    Strategy._periodset(subject)

    # The owner scan sees the line on its second iteration, even though the
    # earlier source-attribution scan saw an empty snapshot.
    assert dynamic_lines.iterations == 3
    assert indicator._clock is primary
    assert indicator._resolved_secondary_clock is secondary
    assert subject._minperiods == [5, 3]

    noniterable_lines = NonIterableLines()
    broken_feed = Feed(noniterable_lines, minperiod=2)
    broken_indicator = Indicator(shared_line, minperiod=5)
    broken_subject = SimpleNamespace(
        datas=[broken_feed],
        _lineiterators={LineIterator.IndType: [broken_indicator]},
        _minperiod=1,
    )
    broken_subject._get_strategy_lineactions = lambda: ()

    with pytest.raises(TypeError, match="synthetic line iteration failure"):
        Strategy._periodset(broken_subject)
    assert noniterable_lines.iterations == 2


def test_periodset_keeps_original_scan_for_dynamic_feed_lines_property():
    """A feed property returning standard Lines snapshots is still dynamic."""

    shared_line = object()

    def native_lines(*items):
        lines = Lines()
        lines.lines.extend(items)
        return lines

    class DynamicFeed:
        def __init__(self, snapshots, minperiod):
            self._snapshots = iter(snapshots)
            self.lines_reads = 0
            self._minperiod = minperiod

        @property
        def lines(self):
            self.lines_reads += 1
            return next(self._snapshots)

    class Feed:
        def __init__(self, lines, minperiod):
            self.lines = lines
            self._minperiod = minperiod

    class Indicator:
        def __init__(self, data, minperiod):
            self.datas = (data,)
            self._clock = MinimalClock()
            self._minperiod = minperiod

    primary = DynamicFeed(
        [
            native_lines(),
            native_lines(),
            native_lines(shared_line),
            native_lines(shared_line),
        ],
        minperiod=2,
    )
    secondary_lines = native_lines(shared_line)
    secondary = Feed(secondary_lines, minperiod=3)
    indicator = Indicator(shared_line, minperiod=5)
    subject = SimpleNamespace(
        datas=[primary, secondary],
        _lineiterators={LineIterator.IndType: [indicator]},
        _minperiod=1,
    )
    subject._get_strategy_lineactions = lambda: ()

    Strategy._periodset(subject)

    assert primary.lines_reads == 4
    assert indicator._clock is primary
    assert indicator._resolved_secondary_clock is secondary
    assert subject._minperiods == [5, 3]
