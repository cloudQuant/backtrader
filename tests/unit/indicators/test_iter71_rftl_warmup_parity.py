"""RFTL's weighted window must not expose incomplete-history partial sums."""

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.rftl_indicator import RFTL_WEIGHTS


def _frame(values, *, minutes=False):
    index = pd.date_range("2024-01-01", periods=len(values), freq="min" if minutes else "D")
    return pd.DataFrame({"open": values, "high": values, "low": values, "close": values, "volume": 1.0}, index=index)


def _reference(values, weights):
    output = []
    for i in range(len(values)):
        if i < len(weights) - 1:
            output.append(math.nan)
        else:
            total = 0.0
            for offset, weight in enumerate(weights):
                total += float(weight) * values[i - offset]
            output.append(total)
    return output


def _assert_sequence(actual, expected):
    assert len(actual) == len(expected)
    for index, (got, wanted) in enumerate(zip(actual, expected)):
        if math.isnan(wanted):
            assert math.isnan(got), (index, got, wanted)
        else:
            assert got == pytest.approx(wanted, rel=1e-12, abs=1e-12), index


def _run(values, weights, runonce):
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.RFTLIndicator(self.data, weights=weights)

        def stop(self):
            self.output = list(self.indicator.rftl.array)

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(values)))
    cerebro.addstrategy(Probe)
    result = cerebro.run()[0]
    return result.output, result.indicator._minperiod


@pytest.mark.parametrize("weights", [tuple(RFTL_WEIGHTS), (0.7, -0.4, 0.2), (2.0,)])
@pytest.mark.parametrize("size", [5, 20, 45])
def test_full_sequence_and_short_history(weights, size):
    values = [10.0 + 0.3 * i + (i % 4) * 0.17 for i in range(size)]
    reference = _reference(values, weights)
    for runonce in (False, True):
        output, minimum = _run(values, weights, runonce)
        _assert_sequence(output, reference)
        assert minimum == 2 * len(weights)


def test_missing_value_propagates_only_in_its_window():
    values = [10.0 + i for i in range(45)]
    values[22] = math.nan
    for runonce in (False, True):
        output, _ = _run(values, tuple(RFTL_WEIGHTS), runonce)
        _assert_sequence(output, _reference(values, RFTL_WEIGHTS))


def test_input_close_minperiod_keeps_historical_schedule():
    class Probe(bt.Strategy):
        def __init__(self):
            self.data.close.addminperiod(4)
            self.indicator = bt.indicators.RFTLIndicator(self.data, weights=(0.7, -0.4, 0.2))

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame([10.0 + i for i in range(20)])))
    cerebro.addstrategy(Probe)
    indicator = cerebro.run()[0].indicator
    assert indicator._minperiod == 9
    assert indicator.rftl._minperiod == 9


def test_empty_weights_remain_invalid():
    with pytest.raises(TypeError):
        _run([1.0, 2.0, 3.0], (), False)


def test_unsized_weights_remain_invalid():
    with pytest.raises(TypeError, match="has no len"):
        _run([1.0, 2.0, 3.0], (weight for weight in (0.7, -0.4, 0.2)), False)


@pytest.mark.parametrize("runonce", [False, True])
def test_source_line_binding_survives_feed_attribute_replacement(runonce):
    values = [10.0 + i for i in range(20)]
    frame = _frame(values)
    frame["open"] = [100.0 + i for i in range(20)]

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.RFTLIndicator(self.data, weights=(1.0,))
            self.data.close = self.data.open

        def stop(self):
            self.output = list(self.indicator.rftl.array)

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Probe)
    output = cerebro.run()[0].output
    _assert_sequence(output, values)


@pytest.mark.parametrize("runonce", [False, True])
def test_non_strict_overflow_retains_line_operation_result(runonce):
    values = [50.0 + i * 0.1 for i in range(45)]
    values[25] = 1e308
    output, _ = _run(values, (2.0, 1.0), runonce)
    assert output[25] == pytest.approx(52.4)


@pytest.mark.parametrize("runonce,phase", [(False, "next"), (True, "once")])
@pytest.mark.parametrize("weights", [(1e308, -1e308), (1e308,) + (0.0,) * 9, (0.0,) * 9 + (math.inf,)])
def test_factor_intermediate_overflow_fails_closed(runonce, phase, weights):
    from backtrader.errors import FactorComputationError
    from backtrader.research.factor_indicator import FactorIndicator
    from tests.unit.test_iter71_factor_strict_context_fastpath import _build_factor_run

    class OverflowFactor(FactorIndicator):
        lines = ("factor",)
        formula_fields = ("close",)
        required_fields = formula_fields
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = bt.indicators.RFTLIndicator(self.data, weights=weights)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child[0]

    cerebro, _ = _build_factor_run(runonce=runonce, factor_class=OverflowFactor, overflow=True)
    with pytest.raises(FactorComputationError) as caught:
        cerebro.run(preload=True)
    assert caught.value.code == "FACTOR_COMPUTATION_FAILED"
    assert caught.value.phase == phase
    assert isinstance(caught.value.__cause__, ArithmeticError)


def test_once_segments_preserve_unrequested_positions():
    values = [10.0 + i * 0.3 for i in range(40)]
    weights = (0.7, -0.4, 0.2)
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.RFTLIndicator(self.data, weights=weights)

    cerebro = bt.Cerebro(stdstats=False, runonce=True, preload=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(values)))
    cerebro.addstrategy(Probe)
    indicator = cerebro.run()[0].indicator
    target = indicator.rftl.array
    for i in range(len(values)):
        target[i] = -999.0
    indicator.preonce(0, 1)
    assert target[1] == -999.0
    indicator.once(1, 13)
    assert target[13] == -999.0
    indicator.once(13, 13)
    assert target[13] == -999.0
    indicator.once(13, len(values))
    _assert_sequence(list(target), _reference(values, weights))


def test_replay_uses_current_partial_bar_and_complete_history():
    values = [100.0 + i for i in range(45)]
    weights = (0.7, -0.4, 0.2)
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.RFTLIndicator(self.data, weights=weights)
            self.observations = []

        def prenext(self):
            self.next()

        def next(self):
            history = list(self.data.close.get(size=min(len(self.data), len(weights))))
            self.observations.append((len(self.data), history, float(self.indicator[0])))

    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    feed = bt.feeds.PandasData(dataname=_frame(values, minutes=True), timeframe=bt.TimeFrame.Minutes)
    cerebro.replaydata(feed, timeframe=bt.TimeFrame.Minutes, compression=3)
    cerebro.addstrategy(Probe)
    observations = cerebro.run()[0].observations
    assert len(observations) > 10
    assert any(len(h) < len(weights) for _, h, _ in observations)
    assert any(len(h) == len(weights) for _, h, _ in observations)
    assert any(a[0] == b[0] and a[1][-1] != b[1][-1] for a, b in zip(observations, observations[1:]))
    for _, history, actual in observations:
        expected = _reference(history, weights)[-1]
        _assert_sequence([actual], [expected])
