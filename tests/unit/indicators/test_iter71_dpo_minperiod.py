"""Regression coverage for DPO's shifted moving-average warmup."""

import math

import pandas as pd
import pytest

import backtrader as bt


DOWNSTREAM_PERIOD = 3


def _historical_dpo(values, period):
    """Compute DPO from its source window without using Backtrader lines."""
    lookback = max(period // 2 - 1, 0)
    result = [float("nan")] * len(values)

    for index in range(len(values)):
        ma_index = index - lookback
        first_source_index = ma_index - period + 1
        if first_source_index < 0:
            continue

        window = values[first_source_index:ma_index + 1]
        if not all(math.isfinite(value) for value in window):
            continue

        moving_average = sum(window) / period
        result[index] = values[index] - moving_average

    return result


def _historical_sma(values, period):
    """Compute a trailing SMA, preserving NaNs until a full finite window."""
    result = [float("nan")] * len(values)

    for index in range(period - 1, len(values)):
        window = values[index - period + 1:index + 1]
        if all(math.isfinite(value) for value in window):
            result[index] = sum(window) / period

    return result


def _run_cerebro(values, period, runonce, upstream_period=None):
    frame = pd.DataFrame(
        {"close": values},
        index=pd.date_range("2024-01-01", periods=len(values), freq="D"),
    )

    class Probe(bt.Strategy):
        def __init__(self):
            source = self.data.close
            if upstream_period is not None:
                source = bt.indicators.SMA(source, period=upstream_period)
            self.dpo = bt.indicators.DPO(source, period=period)
            self.downstream = bt.indicators.SMA(
                self.dpo, period=DOWNSTREAM_PERIOD
            )
            self.records = []
            self.first_nextstart = None

        def _record(self):
            self.records.append(
                (len(self), float(self.dpo[0]), float(self.downstream[0]))
            )

        def prenext(self):
            self._record()

        def nextstart(self):
            self.first_nextstart = len(self)
            self._record()

        def next(self):
            self._record()

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Probe)
    return cerebro.run()[0]


def _assert_sequence_matches(actual, expected):
    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected):
        if math.isnan(expected_value):
            assert math.isnan(actual_value)
        else:
            assert actual_value == pytest.approx(expected_value)


@pytest.mark.parametrize("period", [1, 2, 5, 6, 20])
@pytest.mark.parametrize("runonce", [False, True])
def test_dpo_minperiod_and_full_sequence_follow_shifted_history(period, runonce):
    values = [float((index * index) % 37 + index / 10.0) for index in range(45)]
    lookback = max(period // 2 - 1, 0)
    expected_minperiod = period + lookback
    expected_dpo = _historical_dpo(values, period)
    expected_downstream = _historical_sma(expected_dpo, DOWNSTREAM_PERIOD)

    result = _run_cerebro(values, period, runonce)

    assert result.dpo._minperiod == expected_minperiod
    assert result.dpo.lines.dpo._minperiod == expected_minperiod
    assert result.downstream._minperiod == expected_minperiod + DOWNSTREAM_PERIOD - 1
    assert result.downstream.lines.sma._minperiod == expected_minperiod + DOWNSTREAM_PERIOD - 1
    assert result.first_nextstart == expected_minperiod + DOWNSTREAM_PERIOD - 1
    assert [record[0] for record in result.records] == list(range(1, len(values) + 1))
    _assert_sequence_matches([record[1] for record in result.records], expected_dpo)
    _assert_sequence_matches(
        [record[2] for record in result.records], expected_downstream
    )


@pytest.mark.parametrize("runonce", [False, True])
def test_dpo_short_history_stays_nan_without_reaching_downstream(runonce):
    period = 20
    lookback = max(period // 2 - 1, 0)
    expected_minperiod = period + lookback
    values = [float(index + 1) for index in range(expected_minperiod - 1)]

    result = _run_cerebro(values, period, runonce)

    assert result.dpo._minperiod == expected_minperiod
    assert result.downstream._minperiod == expected_minperiod + DOWNSTREAM_PERIOD - 1
    assert result.first_nextstart is None
    assert len(result.records) == len(values)
    assert all(math.isnan(record[1]) for record in result.records)
    assert all(math.isnan(record[2]) for record in result.records)


@pytest.mark.parametrize("runonce", [False, True])
def test_dpo_period_one_preserves_upstream_warmup_and_short_history(runonce):
    upstream_period = 3
    values = [float(index * 2 + 5) for index in range(12)]
    upstream = _historical_sma(values, upstream_period)
    expected_dpo = _historical_dpo(upstream, period=1)

    result = _run_cerebro(values, period=1, runonce=runonce,
                          upstream_period=upstream_period)

    assert result.dpo.lookback == 0
    assert result.dpo._minperiod == upstream_period
    assert result.dpo.lines.dpo._minperiod == upstream_period
    assert result.downstream._minperiod == upstream_period + DOWNSTREAM_PERIOD - 1
    assert result.downstream.lines.sma._minperiod == upstream_period + DOWNSTREAM_PERIOD - 1
    assert result.first_nextstart == upstream_period + DOWNSTREAM_PERIOD - 1
    _assert_sequence_matches(
        [record[1] for record in result.records], expected_dpo
    )
    assert all(
        value == pytest.approx(0.0)
        for value in [record[1] for record in result.records]
        if math.isfinite(value)
    )

    short_result = _run_cerebro(
        values[:upstream_period - 1], period=1, runonce=runonce,
        upstream_period=upstream_period,
    )
    assert short_result.dpo._minperiod == upstream_period
    assert short_result.first_nextstart is None
    assert all(math.isnan(record[1]) for record in short_result.records)
    assert all(math.isnan(record[2]) for record in short_result.records)
