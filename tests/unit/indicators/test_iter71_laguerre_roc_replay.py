"""Independent Laguerre ROC reference for clocks and missing inputs."""

import math
from unittest.mock import patch

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.laguerre_roc_indicator import LaguerreRocIndicator


PERIOD = 2
GAMMA = 0.5
POINT = 0.01
MINPERIOD = PERIOD + 4


def _reference(prices):
    output = [(math.nan, math.nan, math.nan)] * len(prices)
    state = None
    for i in range(MINPERIOD - 1, len(prices)):
        reference = prices[i - PERIOD]
        if not math.isfinite(reference) or not math.isfinite(prices[i]):
            roc = math.nan
        else:
            roc = POINT if reference == 0 else (prices[i] - reference) / reference + POINT
        if state is None:
            state = (roc,) * 4
        a, b, c, d = state
        l0 = (1 - GAMMA) * roc + GAMMA * a
        l1 = -GAMMA * l0 + a + GAMMA * b
        l2 = -GAMMA * l1 + b + GAMMA * c
        l3 = -GAMMA * l2 + c + GAMMA * d
        state = (l0, l1, l2, l3)
        if not all(math.isfinite(value) for value in state):
            output[i] = (math.nan, .5, math.nan)
            continue
        differences = (l0 - l1, l1 - l2, l2 - l3)
        upward = sum(max(diff, 0.0) for diff in differences)
        downward = sum(max(-diff, 0.0) for diff in differences)
        value = upward / (upward + downward) if upward + downward else .5
        color = 4 if value > .75 else 3 if value > .5 else 0 if value < .25 else 1 if value < .5 else 2
        output[i] = (value, .5, float(color))
    return output


def _run(values, *, once=False, replay=False, secondary=False, exactbars=0,
         indicator=LaguerreRocIndicator):
    days = pd.date_range('2022-01-01', periods=len(values), freq='D')
    times = [day + pd.Timedelta(hours=h) for day in days for h in (9, 10)] if replay else days
    prices = [p for value in values for p in (value - .2, value)] if replay else values
    frame = pd.DataFrame({name: prices for name in ('open', 'high', 'low', 'close')}, index=times)

    class Probe(bt.Strategy):
        def __init__(self):
            self.source = self.datas[-1]
            self.ind = indicator(self.source, vperiod=PERIOD, gamma=GAMMA, point=POINT)
            self.prices, self.samples = [], []
            self.clocks = []

        def prenext(self): self._record()
        def nextstart(self): self._record()
        def next(self): self._record()

        def _record(self):
            if not len(self.source):
                return
            price = float(self.source.close[0])
            if len(self.prices) == len(self.source):
                self.prices[-1] = price
            else:
                self.prices.append(price)
            self.samples.append((list(self.prices), float(self.ind.lroc[0]),
                                 float(self.ind.midline[0]), float(self.ind.color[0])))
            self.clocks.append((len(self.source), len(self.ind), len(self.data)))

    c = bt.Cerebro(runonce=once, preload=not replay and not exactbars,
                   exactbars=exactbars, stdstats=False)
    if secondary:
        offsets = (pd.Timedelta(hours=9), pd.Timedelta(hours=9, minutes=30),
                   pd.Timedelta(hours=10), pd.Timedelta(hours=10, minutes=30))
        times_primary = [day + offset for day in days for offset in offsets]
        primary_values = [p for v in values for p in (v, v, v, v)]
        primary = pd.DataFrame({name: primary_values for name in ('open', 'high', 'low', 'close')}, index=times_primary)
        c.adddata(bt.feeds.PandasData(dataname=primary, timeframe=bt.TimeFrame.Minutes, compression=60))
    feed = bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes if replay else bt.TimeFrame.Days,
                               compression=60 if replay else 1)
    if replay:
        c.replaydata(feed, timeframe=bt.TimeFrame.Days, compression=1)
    else:
        c.adddata(feed)
    c.addstrategy(Probe)
    return c.run()[0]


def _assert_row(actual, expected):
    for a, e in zip(actual, expected):
        if math.isnan(e):
            assert math.isnan(a)
        else:
            assert a == pytest.approx(e, rel=1e-12, abs=1e-12)


def _values():
    return [100 + .12 * i + 3 * math.sin(.37 * i) for i in range(40)]


@pytest.mark.parametrize('once', (False, True), ids=('next', 'once'))
@pytest.mark.parametrize('case', ('finite', 'missing', 'zero_reference', 'missing_with_zero_reference'))
def test_independent_reference_and_nonfinite_color(once, case):
    values = _values()
    if case == 'missing':
        values[15] = math.nan
    elif case == 'zero_reference':
        values[15] = 0.0
    elif case == 'missing_with_zero_reference':
        values[15], values[17] = 0.0, math.nan
    result = _run(values, once=once)
    assert result.ind._minperiod == MINPERIOD
    rows = zip(result.ind.lroc.array, result.ind.midline.array, result.ind.color.array)
    for actual, expected in zip(rows, _reference(values)):
        _assert_row(actual, expected)


@pytest.mark.parametrize('once', (False, True), ids=('next', 'once'))
def test_secondary_clock_independent_reference(once):
    result = _run(_values(), once=once, secondary=True)
    for prices, *actual in result.samples:
        _assert_row(actual, _reference(prices)[-1])


def test_replay_every_revision_matches_reference():
    result = _run(_values(), replay=True)
    assert len(result.samples) >= 79
    for prices, *actual in result.samples:
        _assert_row(actual, _reference(prices)[-1])


def test_secondary_replay_clock_regression_is_visible():
    result = _run(_values(), replay=True, secondary=True)
    assert len(result.samples) >= 3 * len(_values())
    # Existing engine behavior rewinds this secondary source while the
    # indicator follows the primary clock; independent per-bar parity for this
    # combination is not established by this test.
    assert any(current[0] < previous[0] for previous, current in zip(result.clocks, result.clocks[1:]))
    assert any(source != indicator for source, indicator, _ in result.clocks)


def test_exactbars_and_subclass_repeated_calls():
    class Twice(LaguerreRocIndicator):
        def next(self):
            super().next()
            super().next()

    result = _run(_values(), exactbars=1, indicator=Twice)
    for prices, *actual in result.samples:
        _assert_row(actual, _reference(prices)[-1])


def test_failed_color_write_leaves_state_uncommitted_and_retry_is_safe():
    class FailOnce(LaguerreRocIndicator):
        failed = False

        def next(self):
            if len(self) == 8 and not self.failed:
                target = self.lines.color
                line_type = type(target)
                original_setitem = line_type.__setitem__
                state = self._initialized, self._l0, self._l1, self._l2, self._l3

                def fail_color(line, ago, value):
                    if line is target:
                        raise ValueError('synthetic write failure')
                    return original_setitem(line, ago, value)

                self.failed = True
                with patch.object(line_type, '__setitem__', fail_color):
                    with pytest.raises(ValueError, match='synthetic write failure'):
                        super().next()
                assert (self._initialized, self._l0, self._l1, self._l2, self._l3) == state
            super().next()

    result = _run(_values(), replay=True, indicator=FailOnce)
    assert result.ind.failed
    for prices, *actual in result.samples:
        _assert_row(actual, _reference(prices)[-1])


@pytest.mark.parametrize('once', (False, True), ids=('next', 'once'))
@pytest.mark.parametrize('failure', ('roc_subtraction', 'roc_division', 'recursive_intermediate',
                                     'up_threshold', 'down_threshold'))
def test_factor_strategy_strict_rejects_intermediate_overflow(once, failure):
    from backtrader.errors import FactorComputationError
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    from tests.unit.test_factor_research_representatives import _frames, _research_feed, _research_spec

    data = _frames(periods=25)['asset-0'].copy()
    data.loc[:, 'close'] = [100.0 + i for i in range(len(data))]
    if failure == 'roc_subtraction':
        data.loc[data.index[3], 'close'] = -1e308
        data.loc[data.index[5], 'close'] = 1e308
    elif failure == 'roc_division':
        data.loc[data.index[3], 'close'] = 1e-200
        data.loc[data.index[5], 'close'] = 1e308
    research = _research_spec({'asset-0': data})

    class Factor(FactorIndicator):
        lines = ('factor',)
        formula_fields = required_fields = ('close',)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = LaguerreRocIndicator(self.data, vperiod=PERIOD,
                                               gamma=1e308 if failure == 'recursive_intermediate' else GAMMA,
                                               up_level=math.inf if failure == 'up_threshold' else .75,
                                               dn_level=math.inf if failure == 'down_threshold' else .25)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.lroc[0]

    engine = bt.Cerebro(stdstats=False, runonce=once)
    engine.adddata(_research_feed(data, research, 'asset-0'), name='asset-0')
    spec = FactorSpec(name='lroc', indicator=Factor, panel_line='factor',
                      field_bindings={'close': 'feed:target:close'}, mode='native')
    engine.addstrategy(FactorStrategy, research=research, factors={'lroc': spec})
    with pytest.raises(FactorComputationError):
        engine.run(preload=True)
