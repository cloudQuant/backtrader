"""Reference coverage for Laguerre filter and revisable replay bars."""

import math
from unittest.mock import patch

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.laguerre_filter_indicator import LaguerreFilterIndicator
from backtrader.errors import FactorComputationContext, FactorComputationError


GAMMA = 0.7


def _reference(prices):
    laguerre = [math.nan] * len(prices)
    fir = [math.nan] * len(prices)
    if len(prices) < 4:
        return laguerre, fir
    l0 = l1 = l2 = l3 = prices[3]
    laguerre[3] = fir[3] = prices[3]
    for i in range(4, len(prices)):
        old0, old1, old2, old3 = l0, l1, l2, l3
        l0 = (1 - GAMMA) * prices[i] + GAMMA * old0
        l1 = -GAMMA * l0 + old0 + GAMMA * old1
        l2 = -GAMMA * l1 + old1 + GAMMA * old2
        l3 = -GAMMA * l2 + old2 + GAMMA * old3
        laguerre[i] = (l0 + 2 * l1 + 2 * l2 + l3) / 6
        fir[i] = (prices[i] + 2 * prices[i-1] + 2 * prices[i-2] + prices[i-3]) / 6
    return laguerre, fir


def _run(values, *, once=False, replay=False, exactbars=0, secondary=False,
         indicator=LaguerreFilterIndicator):
    days = pd.date_range('2022-01-01', periods=len(values), freq='D')
    if replay:
        timestamps = [day + pd.Timedelta(hours=h) for day in days for h in (9, 10)]
        prices = [p for value in values for p in (value - 0.2, value)]
    else:
        timestamps, prices = days, values
    frame = pd.DataFrame({name: prices for name in ('open', 'high', 'low', 'close')},
                         index=timestamps)

    class Probe(bt.Strategy):
        def __init__(self):
            self.source = self.datas[-1]
            self.ind = indicator(self.source, gamma=GAMMA)
            self.prices = []
            self.samples = []

        def prenext(self):
            self._record()

        def nextstart(self):
            self._record()

        def next(self):
            self._record()

        def _record(self):
            if not len(self.source):
                return
            midpoint = (float(self.source.high[0]) + float(self.source.low[0])) / 2
            if len(self.prices) == len(self.source):
                self.prices[-1] = midpoint
            else:
                self.prices.append(midpoint)
            self.samples.append((list(self.prices), float(self.ind.laguerre[0]),
                                 float(self.ind.fir[0])))

    c = bt.Cerebro(runonce=once, preload=not replay and not exactbars,
                   exactbars=exactbars, stdstats=False)
    feed = bt.feeds.PandasData(dataname=frame,
                               timeframe=bt.TimeFrame.Minutes if replay else bt.TimeFrame.Days,
                               compression=60 if replay else 1)
    if secondary:
        primary_times = [day + pd.Timedelta(hours=h) for day in days for h in (9, 10)]
        primary_values = [p for value in values for p in (value, value)]
        primary = pd.DataFrame({name: primary_values for name in ('open', 'high', 'low', 'close')},
                               index=primary_times)
        c.adddata(bt.feeds.PandasData(dataname=primary, timeframe=bt.TimeFrame.Minutes,
                                     compression=60))
    if replay:
        c.replaydata(feed, timeframe=bt.TimeFrame.Days, compression=1)
    else:
        c.adddata(feed)
    c.addstrategy(Probe)
    return c.run()[0]


def _assert_value(actual, expected):
    if math.isnan(expected):
        assert math.isnan(actual)
    elif math.isinf(expected):
        # LineBuffer normalizes published infinity to its NaN default.
        assert math.isnan(actual)
    else:
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12)


def _values():
    return [100 + .12 * i + 3 * math.sin(.37 * i) for i in range(40)]


@pytest.mark.parametrize('once', (False, True), ids=('next', 'once'))
@pytest.mark.parametrize('missing', (False, True), ids=('finite', 'missing'))
def test_reference_and_missing_propagation(once, missing):
    values = _values()
    if missing:
        values[15] = math.nan
    result = _run(values, once=once)
    expected_laguerre, expected_fir = _reference(result.prices)
    assert result.ind._minperiod == 4
    for actual, expected in zip(result.ind.laguerre.array, expected_laguerre):
        _assert_value(actual, expected)
    for actual, expected in zip(result.ind.fir.array, expected_fir):
        _assert_value(actual, expected)
    if missing:
        assert math.isnan(result.ind.laguerre.array[-1])
        assert math.isfinite(result.ind.fir.array[-1])


@pytest.mark.parametrize('once', (False, True), ids=('next', 'once'))
def test_secondary_feed_uses_one_state_transition_per_source_bar(once):
    result = _run(_values(), once=once, secondary=True)
    assert len(result.prices) == 40
    for prices, laguerre, fir in result.samples:
        expected_laguerre, expected_fir = _reference(prices)
        _assert_value(laguerre, expected_laguerre[-1])
        _assert_value(fir, expected_fir[-1])


def test_subclass_repeated_calls_are_idempotent():
    class Twice(LaguerreFilterIndicator):
        def next(self):
            super().next()
            super().next()

    result = _run(_values(), indicator=Twice)
    expected_laguerre, expected_fir = _reference(result.prices)
    for actual, expected in zip(result.ind.laguerre.array, expected_laguerre):
        _assert_value(actual, expected)
    for actual, expected in zip(result.ind.fir.array, expected_fir):
        _assert_value(actual, expected)


def test_price_read_failure_can_retry_same_bar_without_advancing_state():
    class FailOnce(LaguerreFilterIndicator):
        failed = False

        def _price(self, ago=0):
            if len(self) == 8 and ago == 0 and not self.failed:
                self.failed = True
                raise ValueError('synthetic read failure')
            return super()._price(ago)

        def next(self):
            if len(self) == 8 and not self.failed:
                with pytest.raises(ValueError, match='synthetic read failure'):
                    super().next()
            super().next()

    result = _run(_values(), indicator=FailOnce, replay=True)
    assert result.ind.failed
    for prices, laguerre, fir in result.samples:
        expected_laguerre, expected_fir = _reference(prices)
        _assert_value(laguerre, expected_laguerre[-1])
        _assert_value(fir, expected_fir[-1])


def test_output_write_failure_can_retry_same_bar_without_advancing_state():
    class FailWriteOnce(LaguerreFilterIndicator):
        failed = False

        def next(self):
            if len(self) == 8 and not self.failed:
                target = self.lines.fir
                line_type = type(target)
                original_setitem = line_type.__setitem__

                def fail_fir(line, ago, value):
                    if line is target:
                        raise ValueError('synthetic write failure')
                    return original_setitem(line, ago, value)

                state_before = self._l0, self._l1, self._l2, self._l3
                self.failed = True
                with patch.object(line_type, '__setitem__', fail_fir):
                    with pytest.raises(ValueError, match='synthetic write failure'):
                        super().next()
                assert (self._l0, self._l1, self._l2, self._l3) == state_before
            super().next()

    result = _run(_values(), indicator=FailWriteOnce, replay=True)
    assert result.ind.failed
    for prices, laguerre, fir in result.samples:
        expected_laguerre, expected_fir = _reference(prices)
        _assert_value(laguerre, expected_laguerre[-1])
        _assert_value(fir, expected_fir[-1])


def test_strict_output_overflow_raises_without_committing_filter_state():
    context = FactorComputationContext('laguerre-overflow')

    class StrictOverflow(LaguerreFilterIndicator):
        failed = False

        def next(self):
            if len(self) == 16 and not self.failed:
                before = self._l0, self._l1, self._l2, self._l3
                self.lines.fir._factor_strict_context = context
                self.failed = True
                try:
                    with pytest.raises(FactorComputationError) as caught:
                        super().next()
                    assert isinstance(caught.value.__cause__, ArithmeticError)
                    assert (self._l0, self._l1, self._l2, self._l3) == before
                    assert context.failed
                finally:
                    self.lines.fir._factor_strict_context = None
            super().next()

    values = _values()
    values[15] = 1e308
    result = _run(values, indicator=StrictOverflow)
    assert result.ind.failed


@pytest.mark.parametrize('once', (False, True), ids=('next', 'once'))
def test_extreme_and_nonfinite_inputs_propagate_without_reseeding(once):
    values = _values()
    values[15] = 1e308
    result = _run(values, once=once)
    assert math.isinf(result.prices[15])
    expected_laguerre, expected_fir = _reference(result.prices)
    for actual, expected in zip(result.ind.laguerre.array, expected_laguerre):
        _assert_value(actual, expected)
    for actual, expected in zip(result.ind.fir.array, expected_fir):
        _assert_value(actual, expected)
    assert math.isnan(result.ind.laguerre.array[-1])
    assert math.isfinite(result.ind.fir.array[-1])


def test_exactbars_reference():
    result = _run(_values(), exactbars=1)
    for prices, laguerre, fir in result.samples:
        expected_laguerre, expected_fir = _reference(prices)
        _assert_value(laguerre, expected_laguerre[-1])
        _assert_value(fir, expected_fir[-1])


def test_replay_each_update_and_final_values_match_reference():
    values = _values()
    result = _run(values, replay=True)
    assert len(result.prices) == len(values)
    assert len(result.samples) >= 2 * len(values) - 1
    for prices, laguerre, fir in result.samples:
        expected_laguerre, expected_fir = _reference(prices)
        _assert_value(laguerre, expected_laguerre[-1])
        _assert_value(fir, expected_fir[-1])
    expected_laguerre, expected_fir = _reference(result.prices)
    for actual, expected in zip(result.ind.laguerre.array, expected_laguerre):
        _assert_value(actual, expected)
    for actual, expected in zip(result.ind.fir.array, expected_fir):
        _assert_value(actual, expected)
