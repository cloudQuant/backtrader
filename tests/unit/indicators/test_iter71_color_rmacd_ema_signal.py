"""ColorRMACD EMA signal uses its actual source line's warmup."""

import importlib
import math

import backtrader as bt
import pandas as pd
import pytest


def _frame(*, missing=False, count=220):
    open_ = [100.0 + i * 0.13 + math.sin(i * 0.23) for i in range(count)]
    close = [value + math.sin(i * 0.39) * 1.2 for i, value in enumerate(open_)]
    high = [max(a, b) + 0.9 + (i % 3) * 0.1 for i, (a, b) in enumerate(zip(open_, close))]
    low = [min(a, b) - 0.8 - (i % 4) * 0.1 for i, (a, b) in enumerate(zip(open_, close))]
    if missing:
        close[130] = math.nan
    return pd.DataFrame(
        {
            "open": open_, "high": high, "low": low, "close": close,
            "volume": [100.0 + (i % 9) * 30 for i in range(count)],
            "openinterest": [300.0 + (i % 7) * 17 for i in range(count)],
        },
        index=pd.date_range("2020-01-01", periods=count),
    )


def _run(runonce, *, signal_period, missing=False, signal_method="ema", count=220):
    frame = _frame(missing=missing, count=count)

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.ColorRMACDIndicator(
                self.data, signal_method=signal_method, signal_xma=signal_period
            )

        def stop(self):
            self.result = (
                self.indicator._minperiod,
                list(self.indicator.rmacd.array),
                list(self.indicator.signal.array),
            )

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Probe)
    return cerebro.run()[0].result


def _assert_equal(actual, expected):
    assert len(actual) == len(expected)
    for index, (got, want) in enumerate(zip(actual, expected)):
        if math.isnan(want):
            assert math.isnan(got), f"index {index}: expected NaN, got {got!r}"
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12), f"index {index}"


@pytest.mark.parametrize("signal_period", [3, 9])
@pytest.mark.parametrize("missing", [False, True], ids=["finite", "missing-close"])
def test_ema_signal_matches_independent_reference_and_next(signal_period, missing):
    runnext = _run(False, signal_period=signal_period, missing=missing)
    runonce = _run(True, signal_period=signal_period, missing=missing)
    assert runnext[0] == runonce[0] == 71 + signal_period
    _assert_equal(runonce[1], runnext[1])
    _assert_equal(runonce[2], runnext[2])

    source = runnext[1]
    first_source = 33
    first_signal = first_source + signal_period - 1
    assert math.isfinite(source[first_source])
    assert all(math.isnan(value) for value in source[:first_source])
    previous = math.fsum(source[first_source : first_signal + 1]) / signal_period
    expected = [math.nan] * first_signal + [previous]
    alpha = 2.0 / (signal_period + 1.0)
    for value in source[first_signal + 1 :]:
        previous = previous * (1.0 - alpha) + value * alpha
        expected.append(previous)
    _assert_equal(runnext[2], expected)


@pytest.mark.parametrize("method", ["sma", "smma", "wma"])
def test_other_signal_methods_keep_mode_parity(method):
    runnext = _run(False, signal_period=9, signal_method=method)
    runonce = _run(True, signal_period=9, signal_method=method)
    assert runnext[0] == runonce[0]
    _assert_equal(runnext[1], runonce[1])
    _assert_equal(runnext[2], runonce[2])


@pytest.mark.parametrize("runonce", [False, True])
def test_short_history_does_not_publish_a_signal(runonce):
    minperiod, _rmacd, signal = _run(runonce, signal_period=9, count=20)
    assert minperiod == 80
    assert all(math.isnan(value) for value in signal)


def test_rmacd_binding_precedes_signal_registration(monkeypatch):
    module = importlib.import_module("backtrader.indicators.contrib.trvi_indicator")
    original_resolve = module.resolve_ma_class
    observed = {}

    def capture_resolve(name):
        ma_class = original_resolve(name)

        def capture_signal(source, *args, **kwargs):
            owner = source._owner
            assert any(line is owner.lines.rmacd for line in source.bindings)
            assert any(child is source for child in owner._lineiterators[0])
            signal = ma_class(source, *args, **kwargs)
            assert signal.data is source
            assert signal._owner is owner
            observed.update(source=source, signal=signal, owner=owner)
            return signal

        return capture_signal

    monkeypatch.setattr(module, "resolve_ma_class", capture_resolve)
    _run(False, signal_period=9)
    source, signal, owner = observed["source"], observed["signal"], observed["owner"]
    children = owner._lineiterators[0]
    assert next(i for i, child in enumerate(children) if child is source) < next(
        i for i, child in enumerate(children) if child is signal
    )
    assert any(line is owner.lines.signal for line in signal.lines[0].bindings)


def _run_trvi(runonce, *, missing, segmented=False):
    class SegmentedTRVI(bt.indicators.TRVIIndicator):
        def once(self, start, end):
            for index in range(start, end):
                super().once(index, index + 1)

    class Probe(bt.Strategy):
        def __init__(self):
            indicator_class = SegmentedTRVI if segmented else bt.indicators.TRVIIndicator
            self.indicator = indicator_class(self.data, period=5, volume_type="tick")

        def stop(self):
            self.result = (
                self.indicator._minperiod,
                list(self.indicator.trvi.array),
                list(self.indicator.signal.array),
            )

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(missing=missing)))
    cerebro.addstrategy(Probe)
    return cerebro.run()[0].result


def _trvi_reference(frame, period):
    first = period + 7
    raw_numerator, raw_denominator = [], []
    trvi = [math.nan] * first
    signal = [math.nan] * first
    body = list(frame["close"] - frame["open"])
    ranges = list(frame["high"] - frame["low"])
    volumes = list(frame["volume"])

    def count(values, index):
        return sum(
            weight * volumes[index - lag] * values[index - lag]
            for lag, weight in enumerate((1.0, 8.0, 8.0, 1.0))
        )

    def weighted(values):
        window = values[-period:]
        weights = range(len(window), 0, -1)
        return sum(value * weight for value, weight in zip(window, weights)) / sum(
            range(1, len(window) + 1)
        )

    for index in range(first, len(frame)):
        raw_numerator.append(count(body, index))
        raw_denominator.append(count(ranges, index))

        numerator = weighted(raw_numerator)
        denominator = weighted(raw_denominator)
        trvi.append(numerator / denominator if denominator else 0.0)
        if len(trvi) - first < 4:
            signal.append(trvi[-1])
        else:
            signal.append(sum(value * weight for value, weight in zip(trvi[-4:], (1, 2, 3, 4))) / 10.0)
    return trvi, signal


@pytest.mark.parametrize("missing", [False, True], ids=["finite", "missing-close"])
def test_trvi_next_once_and_segmented_match_reference(missing):
    expected = _trvi_reference(_frame(missing=missing), period=5)
    for result in (
        _run_trvi(False, missing=missing),
        _run_trvi(True, missing=missing),
        _run_trvi(True, missing=missing, segmented=True),
    ):
        assert result[0] == 13
        _assert_equal(result[1], expected[0])
        _assert_equal(result[2], expected[1])
