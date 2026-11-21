"""Cerebro coverage for XMACDIndicator warm-up and once parity."""

import math

import backtrader as bt
import backtrader.indicators.contrib.xmacd_indicator as xmacd_module
import pandas as pd
import pytest


def _values(count, missing=()):
    values = [
        50.0 + ((index * 11) % 19) * 0.2 + math.sin(index * 0.31) * 3.0
        for index in range(count)
    ]
    for index in missing:
        values[index] = float("nan")
    return values


def _frame(values, *, index=None):
    return pd.DataFrame(
        {
            "open": values,
            "high": [value + 1.0 if math.isfinite(value) else value for value in values],
            "low": [value - 1.0 if math.isfinite(value) else value for value in values],
            "close": values,
            "volume": [1.0] * len(values),
            "openinterest": [0.0] * len(values),
        },
        index=(
            pd.date_range("2024-01-01", periods=len(values), freq="D")
            if index is None
            else index
        ),
    )


def _run(values, params, *, runonce, segment_size=None):
    once_ranges = []
    original_ema = xmacd_module.EMA
    original_sma = xmacd_module.SMA

    if segment_size is not None:

        class SegmentedEMA(bt.indicators.EMA):
            alias = ()

            def once(self, start, end):
                for left in range(start, end, segment_size):
                    right = min(left + segment_size, end)
                    once_ranges.append(("ema", left, right))
                    super().once(left, right)

        class SegmentedSMA(bt.indicators.SMA):
            alias = ()

            def once(self, start, end):
                for left in range(start, end, segment_size):
                    right = min(left + segment_size, end)
                    once_ranges.append(("sma", left, right))
                    super().once(left, right)

        xmacd_module.EMA = SegmentedEMA
        xmacd_module.SMA = SegmentedSMA

    result = {}

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.XMACDIndicator(self.data, **params)
            self.callback_lengths = []

        def prenext(self):
            self.callback_lengths.append(("prenext", len(self)))

        def nextstart(self):
            self.callback_lengths.append(("nextstart", len(self)))

        def next(self):
            self.callback_lengths.append(("next", len(self)))

        def stop(self):
            result.update(
                minperiod=self.indicator._minperiod,
                macd_minperiod=self.indicator.macd._minperiod,
                signal_minperiod=self.indicator.signal._minperiod,
                macd=[float(value) for value in self.indicator.macd.array],
                signal=[float(value) for value in self.indicator.signal.array],
                callback_lengths=list(self.callback_lengths),
            )

    try:
        cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
        cerebro.adddata(bt.feeds.PandasData(dataname=_frame(values)))
        cerebro.addstrategy(Probe)
        cerebro.run(runonce=runonce, preload=True)
    finally:
        xmacd_module.EMA = original_ema
        xmacd_module.SMA = original_sma

    result["once_ranges"] = once_ranges
    return result


def _run_with_sparse_secondary_feed(params, *, runonce):
    primary_values = _values(30)
    secondary_values = _values(15)
    primary_dates = pd.date_range("2024-01-01", periods=30, freq="D")
    secondary_dates = pd.date_range("2024-01-01", periods=15, freq="2D")
    rows = []
    result = {}

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.XMACDIndicator(
                self.data1, **params
            )

        def _capture(self, callback):
            source_date = self.data1.datetime.datetime(0).date()
            rows.append(
                (
                    callback,
                    len(self.data0),
                    len(self.data1),
                    source_date,
                    float(self.indicator.macd[0]),
                    float(self.indicator.signal[0]),
                )
            )

        def prenext(self):
            self._capture("prenext")

        def nextstart(self):
            self._capture("nextstart")

        def next(self):
            self._capture("next")

        def stop(self):
            result.update(
                macd=[float(value) for value in self.indicator.macd.array],
                signal=[float(value) for value in self.indicator.signal.array],
            )

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    cerebro.adddata(
        bt.feeds.PandasData(dataname=_frame(primary_values, index=primary_dates))
    )
    cerebro.adddata(
        bt.feeds.PandasData(
            dataname=_frame(secondary_values, index=secondary_dates)
        )
    )
    cerebro.addstrategy(Probe)
    cerebro.run(runonce=runonce, preload=True)
    result["rows"] = rows
    return result


def _assert_series_close(actual, expected):
    assert len(actual) == len(expected)
    for index, (actual_value, expected_value) in enumerate(zip(actual, expected)):
        if math.isnan(expected_value):
            assert math.isnan(actual_value), index
        else:
            assert actual_value == pytest.approx(expected_value, rel=1e-12, abs=1e-12), index


def _reference_sma(values, period):
    result = [float("nan")] * len(values)
    for index in range(period - 1, len(values)):
        window = values[index - period + 1 : index + 1]
        if not any(math.isnan(value) for value in window):
            result[index] = math.fsum(window) / period
    return result


def _reference_ema(values, period, *, source_start=0):
    result = [float("nan")] * len(values)
    seed_index = source_start + period - 1
    if seed_index >= len(values):
        return result

    seed = values[source_start : seed_index + 1]
    previous = (
        float("nan")
        if any(math.isnan(value) for value in seed)
        else math.fsum(seed) / period
    )
    result[seed_index] = previous
    alpha = 2.0 / (period + 1.0)
    alpha1 = 1.0 - alpha
    for index in range(seed_index + 1, len(values)):
        previous = previous * alpha1 + values[index] * alpha
        result[index] = previous
    return result


def _reference_xmacd(values, params):
    ma_function = _reference_ema if params["ma_method"] == "ema" else _reference_sma
    fast = ma_function(values, params["fast_period"])
    slow = ma_function(values, params["slow_period"])
    macd = [
        fast_value - slow_value
        if not math.isnan(fast_value) and not math.isnan(slow_value)
        else float("nan")
        for fast_value, slow_value in zip(fast, slow)
    ]

    if params["signal_method"] == "ema":
        signal = _reference_ema(
            macd,
            params["signal_period"],
            source_start=max(params["fast_period"], params["slow_period"]) - 1,
        )
    else:
        signal = _reference_sma(macd, params["signal_period"])
    return macd, signal


def test_minperiod_uses_the_composed_signal_warmup_once():
    params = {
        "ma_method": "sma",
        "signal_method": "sma",
        "fast_period": 3,
        "slow_period": 5,
        "signal_period": 2,
        "applied_price": "close",
    }

    next_result = _run(_values(40), params, runonce=False)
    once_result = _run(_values(40), params, runonce=True)

    # Keep the indicator's explicit 5-bar signal warm-up without adding the
    # whole child graph a second time.  The lines themselves are valid sooner.
    assert next_result["minperiod"] == 12
    assert once_result["minperiod"] == 12
    assert ("nextstart", 12) in next_result["callback_lengths"]
    assert ("nextstart", 12) in once_result["callback_lengths"]
    _assert_series_close(next_result["signal"], once_result["signal"])
    assert all(math.isnan(value) for value in once_result["signal"][:5])
    assert math.isfinite(once_result["signal"][5])


def test_period_one_ema_signal_has_no_artificial_runonce_gap():
    params = {
        "ma_method": "ema",
        "signal_method": "ema",
        "fast_period": 1,
        "slow_period": 1,
        "signal_period": 1,
        "applied_price": "close",
    }

    next_result = _run(_values(16), params, runonce=False)
    once_result = _run(_values(16), params, runonce=True)

    _assert_series_close(next_result["macd"], once_result["macd"])
    _assert_series_close(next_result["signal"], once_result["signal"])
    assert all(value == 0.0 for value in once_result["signal"])


@pytest.mark.parametrize("ma_method", ("ema", "sma"))
@pytest.mark.parametrize("signal_method", ("ema", "sma"))
def test_missing_values_and_segmented_once_match_streaming(
    ma_method, signal_method
):
    params = {
        "ma_method": ma_method,
        "signal_method": signal_method,
        "fast_period": 4,
        "slow_period": 9,
        "signal_period": 3,
        "applied_price": "typical",
    }
    values = _values(100, missing=(0, 36))
    expected_macd, expected_signal = _reference_xmacd(values, params)

    next_result = _run(values, params, runonce=False)
    once_result = _run(values, params, runonce=True)
    segmented_result = _run(values, params, runonce=True, segment_size=7)

    for field in ("macd", "signal"):
        _assert_series_close(once_result[field], next_result[field])
        _assert_series_close(segmented_result[field], next_result[field])
    _assert_series_close(next_result["macd"], expected_macd)
    _assert_series_close(next_result["signal"], expected_signal)
    assert len(segmented_result["once_ranges"]) > 6
    if ma_method == signal_method == "sma":
        # The NaN at bar 36 leaves the nine-bar slow window at bar 45;
        # the three-bar signal SMA is finite again at bar 47.
        assert math.isnan(next_result["signal"][46])
        assert math.isfinite(next_result["signal"][47])


@pytest.mark.parametrize("ma_method", ("ema", "sma"))
@pytest.mark.parametrize("signal_method", ("ema", "sma"))
def test_single_midstream_nan_matches_reference_and_execution_modes(
    ma_method, signal_method
):
    params = {
        "ma_method": ma_method,
        "signal_method": signal_method,
        "fast_period": 4,
        "slow_period": 9,
        "signal_period": 3,
        "applied_price": "close",
    }
    values = _values(100, missing=(36,))
    expected_macd, expected_signal = _reference_xmacd(values, params)

    next_result = _run(values, params, runonce=False)
    once_result = _run(values, params, runonce=True)
    segmented_result = _run(values, params, runonce=True, segment_size=7)

    for field, expected in (
        ("macd", expected_macd),
        ("signal", expected_signal),
    ):
        _assert_series_close(next_result[field], expected)
        _assert_series_close(once_result[field], expected)
        _assert_series_close(segmented_result[field], expected)

    if ma_method == "ema":
        assert all(math.isnan(value) for value in next_result["macd"][36:])
        assert all(math.isnan(value) for value in next_result["signal"][36:])
    else:
        assert math.isnan(next_result["macd"][44])
        assert math.isfinite(next_result["macd"][45])
        if signal_method == "ema":
            assert all(math.isnan(value) for value in next_result["signal"][36:])
        else:
            assert math.isnan(next_result["signal"][46])
            assert math.isfinite(next_result["signal"][47])


@pytest.mark.parametrize("runonce", (False, True))
def test_indicator_on_sparse_secondary_feed_tracks_its_own_clock(runonce):
    params = {
        "ma_method": "sma",
        "signal_method": "sma",
        "fast_period": 3,
        "slow_period": 5,
        "signal_period": 2,
        "applied_price": "close",
    }
    secondary_values = _values(15)
    expected_macd, expected_signal = _reference_xmacd(
        secondary_values, params
    )

    result = _run_with_sparse_secondary_feed(params, runonce=runonce)

    _assert_series_close(result["macd"], expected_macd)
    _assert_series_close(result["signal"], expected_signal)
    assert len(result["rows"]) == 30
    for primary_length, row in enumerate(result["rows"], start=1):
        _, captured_primary, source_length, source_date, macd, signal = row
        assert captured_primary == primary_length
        expected_source_length = (primary_length + 1) // 2
        assert source_length == expected_source_length
        assert source_date == pd.Timestamp("2024-01-01").date() + pd.Timedelta(
            days=2 * (expected_source_length - 1)
        )
        source_index = source_length - 1
        _assert_series_close([macd], [expected_macd[source_index]])
        _assert_series_close([signal], [expected_signal[source_index]])


def test_short_history_keeps_signal_missing_in_both_modes():
    params = {
        "ma_method": "ema",
        "signal_method": "sma",
        "fast_period": 4,
        "slow_period": 9,
        "signal_period": 3,
        "applied_price": "close",
    }

    next_result = _run(_values(6), params, runonce=False)
    once_result = _run(_values(6), params, runonce=True)

    _assert_series_close(once_result["macd"], next_result["macd"])
    _assert_series_close(once_result["signal"], next_result["signal"])
    assert all(math.isnan(value) for value in once_result["signal"])
