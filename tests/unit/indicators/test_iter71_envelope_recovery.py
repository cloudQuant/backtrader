"""R71-150 regressions for source and moving-average envelopes."""

import math
from array import array
from types import SimpleNamespace

import pandas as pd
import pytest

import backtrader as bt
from backtrader.indicators.envelope import EnvelopeMixIn, _EnvelopeBase


def _frame(values):
    return pd.DataFrame(
        {
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": [1] * len(values),
        },
        index=pd.date_range("2024-01-01", periods=len(values), freq="D"),
    )


def _run(frame, strategy, runonce):
    cerebro = bt.Cerebro(
        stdstats=False,
        runonce=runonce,
        preload=runonce,
    )
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(strategy)
    return cerebro.run()[0]


def _sma(values, period):
    result = []
    for index in range(len(values)):
        start = index - period + 1
        if start < 0:
            result.append(float("nan"))
            continue

        window = values[start : index + 1]
        if any(math.isnan(value) for value in window):
            result.append(float("nan"))
        else:
            result.append(sum(window) / period)
    return result


def _ema(values, period):
    result = [float("nan")] * len(values)
    if len(values) < period:
        return result

    seed = sum(values[:period]) / period
    seed_index = period - 1
    result[seed_index] = seed
    alpha = 2.0 / (period + 1.0)
    for index in range(period, len(values)):
        result[index] = result[index - 1] * (1.0 - alpha) + values[index] * alpha
    return result


def _bands(values, perc):
    factor = perc / 100.0
    return (
        [value * (1.0 + factor) for value in values],
        [value * (1.0 - factor) for value in values],
    )


def _assert_values(actual, expected):
    actual = list(actual)
    assert len(actual) == len(expected)
    for index, (observed, wanted) in enumerate(zip(actual, expected)):
        if math.isnan(wanted):
            assert math.isnan(observed), index
        else:
            assert math.isclose(observed, wanted, rel_tol=1e-12, abs_tol=1e-12), index


def test_copy_source_once_empty_range_is_noop_and_other_range_is_bounded():
    source = SimpleNamespace(array=array("d"))
    source_line = SimpleNamespace(array=array("d"))
    probe = SimpleNamespace(data=source, lines=SimpleNamespace(src=source_line))

    _EnvelopeBase._copy_source_once(probe, 2, 2)

    assert list(source_line.array) == []

    probe.data.array = array("d", [10.0, 11.0, 12.0, 13.0])
    probe.lines.src.array = array("d", [-1.0, -1.0, -1.0, -1.0])
    _EnvelopeBase._copy_source_once(probe, 1, 3)

    assert list(probe.lines.src.array) == [-1.0, 11.0, 12.0, -1.0]


def test_envelope_once_empty_range_is_noop_and_other_range_is_bounded():
    top = SimpleNamespace(array=array("d"))
    bot = SimpleNamespace(array=array("d"))

    class Probe(SimpleNamespace):
        _envelope_factor = EnvelopeMixIn._envelope_factor

    probe = Probe(
        p=SimpleNamespace(perc=10.0),
        lines=SimpleNamespace(top=top, bot=bot),
    )
    baseline = SimpleNamespace(array=array("d"))

    EnvelopeMixIn._envelope_once(probe, baseline, 2, 2)

    assert list(top.array) == []
    assert list(bot.array) == []

    top.array = array("d", [-1.0, -1.0, -1.0, -1.0])
    bot.array = array("d", [-1.0, -1.0, -1.0, -1.0])
    baseline.array = array("d", [10.0, 20.0, 30.0, 40.0])
    EnvelopeMixIn._envelope_once(probe, baseline, 1, 3)

    assert list(top.array) == [-1.0, 22.0, 33.0, -1.0]
    assert list(bot.array) == [-1.0, 18.0, 27.0, -1.0]


@pytest.mark.parametrize("runonce", [False, True])
def test_envelope_and_sma_envelope_use_perc_and_preserve_warmup(runonce):
    values = [10.0, 12.0, 11.0, 14.0, 13.0, 15.0, 16.0, 12.0]

    class Probe(bt.Strategy):
        def __init__(self):
            self.source = bt.indicators.Envelope(self.data.close, perc=10.0)
            self.default_source = bt.indicators.Envelope(self.data.close)
            self.sma = bt.indicators.SMAEnvelope(self.data.close, period=3, perc=5.0)

    strategy = _run(_frame(values), Probe, runonce)
    expected_top, expected_bot = _bands(values, 10.0)
    default_top, default_bot = _bands(values, 2.5)
    expected_sma = _sma(values, 3)
    sma_top, sma_bot = _bands(expected_sma, 5.0)

    assert strategy.source.p.perc == 10.0
    assert strategy.default_source.p.perc == 2.5
    assert strategy.sma.p.perc == 5.0
    _assert_values(strategy.source.lines.src.array, values)
    _assert_values(strategy.source.lines.top.array, expected_top)
    _assert_values(strategy.source.lines.bot.array, expected_bot)
    _assert_values(strategy.default_source.lines.top.array, default_top)
    _assert_values(strategy.default_source.lines.bot.array, default_bot)
    _assert_values(strategy.sma.lines.sma.array, expected_sma)
    _assert_values(strategy.sma.lines.top.array, sma_top)
    _assert_values(strategy.sma.lines.bot.array, sma_bot)


@pytest.mark.parametrize("runonce", [False, True])
def test_generated_ema_envelope_and_nested_envelopes_match_independent_formulas(
    runonce,
):
    values = [10.0, 12.0, 11.0, 14.0, 13.0, 15.0, 16.0, 12.0, 17.0, 18.0]

    class Probe(bt.Strategy):
        def __init__(self):
            self.ema = bt.indicators.EMA(self.data.close, period=2)
            self.ema_envelope = bt.indicators.EMAEnvelope(
                self.data.close, period=2, perc=7.0
            )
            self.nested_sma_envelope = bt.indicators.SMAEnvelope(
                self.ema, period=3, perc=10.0
            )
            self.nested_source_envelope = bt.indicators.Envelope(self.ema, perc=4.0)

    strategy = _run(_frame(values), Probe, runonce)
    ema_values = _ema(values, 2)
    ema_top, ema_bot = _bands(ema_values, 7.0)
    nested_sma = _sma(ema_values, 3)
    nested_top, nested_bot = _bands(nested_sma, 10.0)
    source_top, source_bot = _bands(ema_values, 4.0)

    _assert_values(strategy.ema.lines.ema.array, ema_values)
    _assert_values(strategy.ema_envelope.lines.ema.array, ema_values)
    _assert_values(strategy.ema_envelope.lines.top.array, ema_top)
    _assert_values(strategy.ema_envelope.lines.bot.array, ema_bot)
    _assert_values(strategy.nested_sma_envelope.lines.sma.array, nested_sma)
    _assert_values(strategy.nested_sma_envelope.lines.top.array, nested_top)
    _assert_values(strategy.nested_sma_envelope.lines.bot.array, nested_bot)
    _assert_values(strategy.nested_source_envelope.lines.src.array, ema_values)
    _assert_values(strategy.nested_source_envelope.lines.top.array, source_top)
    _assert_values(strategy.nested_source_envelope.lines.bot.array, source_bot)


@pytest.mark.parametrize("runonce", [False, True])
def test_envelopes_follow_daily_and_resampled_weekly_clocks(runonce):
    values = [10.0, 12.0, 11.0, 14.0, 13.0, 15.0, 16.0, 12.0, 17.0, 18.0, 14.0, 20.0, 19.0, 23.0, 22.0]

    class Probe(bt.Strategy):
        def __init__(self):
            self.daily = bt.indicators.Envelope(self.data0.close, perc=5.0)
            self.weekly = bt.indicators.SMAEnvelope(self.data1.close, period=2, perc=10.0)

    cerebro = bt.Cerebro(
        stdstats=False,
        runonce=runonce,
        preload=runonce,
    )
    daily = bt.feeds.PandasData(dataname=_frame(values))
    cerebro.adddata(daily)
    cerebro.resampledata(daily, timeframe=bt.TimeFrame.Weeks, compression=1)
    cerebro.addstrategy(Probe)
    strategy = cerebro.run()[0]

    daily_top, daily_bot = _bands(values, 5.0)
    weekly_closes = list(strategy.data1.close.array)
    weekly_sma = _sma(weekly_closes, 2)
    weekly_top, weekly_bot = _bands(weekly_sma, 10.0)

    assert len(strategy.daily.lines.src.array) == len(values)
    assert len(strategy.weekly.lines.sma.array) == len(weekly_closes)
    _assert_values(strategy.daily.lines.src.array, values)
    _assert_values(strategy.daily.lines.top.array, daily_top)
    _assert_values(strategy.daily.lines.bot.array, daily_bot)
    _assert_values(strategy.weekly.lines.sma.array, weekly_sma)
    _assert_values(strategy.weekly.lines.top.array, weekly_top)
    _assert_values(strategy.weekly.lines.bot.array, weekly_bot)
