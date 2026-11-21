"""Execution-mode regressions for StochasticHistogramIndicator."""

import math

import pandas as pd
import pytest

import backtrader as bt


_K_PERIOD = 5
_SLOWING = 3
_D_PERIOD = 3
_MINPERIOD = 13  # Preserve the migrated indicator's published warm-up.


def _bars(size, missing=False):
    close = [100.0 + index * 0.17 + ((index * 7) % 13) * 0.31 for index in range(size)]
    high = [value + 0.4 + ((index * 5) % 7) * 0.13 for index, value in enumerate(close)]
    low = [value - 0.6 - ((index * 3) % 5) * 0.19 for index, value in enumerate(close)]

    if missing:
        # Place missing high/low/close values at different positions within
        # otherwise finite %K windows, including their older and newer ends.
        high[15] = float("nan")
        low[20] = float("nan")
        close[24] = float("nan")

    return pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": [1.0] * size,
        },
        index=pd.date_range("2020-01-01", periods=size, freq="D"),
    )


class _CaptureStrategy(bt.Strategy):
    params = (
        ("ma_method", "sma"),
        ("indicator_type", bt.indicators.StochasticHistogramIndicator),
    )

    def __init__(self):
        self.indicator = self.p.indicator_type(
            self.data,
            k_period=_K_PERIOD,
            slowing=_SLOWING,
            d_period=_D_PERIOD,
            ma_method=self.p.ma_method,
        )
        self.downstream = bt.indicators.SimpleMovingAverage(self.indicator.main, period=2)
        self.prenext_calls = 0
        self.nextstart_calls = 0
        self.next_calls = 0
        self.samples = []

    def prenext(self):
        self.prenext_calls += 1

    def nextstart(self):
        self.nextstart_calls += 1
        super().nextstart()

    def next(self):
        self.next_calls += 1
        self.samples.append(
            (
                len(self.data),
                float(self.indicator.main[0]),
                float(self.indicator.signal[0]),
                float(self.indicator.hist_base[0]),
                float(self.indicator.color_state[0]),
                float(self.downstream[0]),
            )
        )


class _CustomWarmupHistogram(bt.indicators.StochasticHistogramIndicator):
    """Represent a legal subclass with its own warm-up callback."""

    def __init__(self):
        super().__init__()
        self.custom_prenext_calls = 0

    def prenext(self):
        self.custom_prenext_calls += 1
        super().prenext()


class _InheritedHistogram(bt.indicators.StochasticHistogramIndicator):
    """Represent a subclass that keeps every indicator hook unchanged."""


class _DynamicPeriodStrategy(_CaptureStrategy):
    """Mutate a period after outputs start to exercise the legacy fallback."""

    def next(self):
        super().next()
        if self.next_calls == 1:
            self.indicator.p.k_period = 4


class _MultiClockCaptureStrategy(_CaptureStrategy):
    """Capture repeated callbacks while a secondary feed advances."""

    def __init__(self):
        super().__init__()
        self.clock_samples = []

    def next(self):
        super().next()
        self.clock_samples.append(
            (
                len(self.data0),
                len(self.data1),
                (
                    float(self.data0.high[0]),
                    float(self.data0.low[0]),
                    float(self.data0.close[0]),
                ),
                float(self.indicator.main[0]),
                float(self.indicator.signal[0]),
                self.indicator._stream_force_legacy,
            )
        )


class _ReplayCaptureStrategy(bt.Strategy):
    """Compare replay updates with a full-history scalar reference."""

    params = (("ma_method", "ema"),)

    def __init__(self):
        self.indicator = bt.indicators.StochasticHistogramIndicator(
            self.data,
            k_period=_K_PERIOD,
            slowing=_SLOWING,
            d_period=_D_PERIOD,
            ma_method=self.p.ma_method,
        )
        self.samples = []

    def next(self):
        index = self.data.high.idx
        highs = list(self.data.high.array)[: index + 1]
        lows = list(self.data.low.array)[: index + 1]
        closes = list(self.data.close.array)[: index + 1]
        reference = _reference(
            pd.DataFrame({"high": highs, "low": lows, "close": closes}),
            self.p.ma_method,
        )
        self.samples.append(
            (
                len(self.data),
                index,
                (highs[-1], lows[-1], closes[-1]),
                float(self.indicator.main[0]),
                float(self.indicator.signal[0]),
                reference["main"][-1],
                reference["signal"][-1],
                self.indicator._stream_force_legacy,
            )
        )


def _run(
    bars,
    *,
    ma_method="sma",
    runonce,
    preload=None,
    exactbars=0,
    indicator_type=None,
    strategy_type=_CaptureStrategy,
):
    if preload is None:
        preload = runonce
    cerebro = bt.Cerebro(
        runonce=runonce,
        preload=preload,
        exactbars=exactbars,
        stdstats=False,
    )
    cerebro.adddata(bt.feeds.PandasData(dataname=bars))
    kwargs = {"ma_method": ma_method}
    if indicator_type is not None:
        kwargs["indicator_type"] = indicator_type
    cerebro.addstrategy(strategy_type, **kwargs)
    strategy = cerebro.run()[0]
    return strategy


def _run_secondary_clock(method):
    slow = _bars(24)
    slow.index = pd.date_range("2020-01-01 12:00", periods=len(slow), freq="D")
    timestamps = [
        day + pd.Timedelta(hours=hour)
        for day in pd.date_range("2020-01-01", periods=len(slow), freq="D")
        for hour in (8, 10, 14, 18)
    ]
    fast = _bars(len(timestamps))
    fast.index = timestamps

    cerebro = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=slow), name="slow")
    cerebro.adddata(bt.feeds.PandasData(dataname=fast), name="fast")
    cerebro.addstrategy(_MultiClockCaptureStrategy, ma_method=method)
    return cerebro.run()[0]


def _run_replay(method):
    closes = [100.0]
    for index in range(1, 100):
        closes.append(closes[-1] + ((index * 17) % 11 - 5) * 0.13)
    minute_bars = pd.DataFrame(
        {
            "open": [value - 0.04 for value in closes],
            "high": [value + 0.2 + (index % 3) * 0.07 for index, value in enumerate(closes)],
            "low": [value - 0.25 - (index % 4) * 0.03 for index, value in enumerate(closes)],
            "close": closes,
            "volume": [1.0] * len(closes),
        },
        index=pd.date_range("2020-01-01 09:00", periods=len(closes), freq="min"),
    )
    source = bt.feeds.PandasData(
        dataname=minute_bars,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    cerebro.replaydata(source, timeframe=bt.TimeFrame.Minutes, compression=5)
    cerebro.addstrategy(_ReplayCaptureStrategy, ma_method=method)
    return cerebro.run()[0]


def _reference_ma(values, period, previous, method):
    """Independent scalar definition of the migrated SMA/EMA/SMMA/LWMA modes."""
    if not values:
        return float("nan")

    value = float(values[-1])
    normalized = str(method).strip().lower()
    if normalized in {"ema", "mode_ema"}:
        if previous is None or math.isnan(previous):
            return value
        alpha = 2.0 / (period + 1.0)
        return previous + alpha * (value - previous)
    if normalized in {"smma", "mode_smma"}:
        if previous is None or math.isnan(previous):
            return value
        return ((period - 1.0) * previous + value) / period
    if normalized in {"lwma", "wma", "mode_lwma"}:
        weight_total = len(values) * (len(values) + 1) / 2.0
        return sum(float(item) * weight for weight, item in enumerate(values, 1)) / weight_total
    return sum(float(item) for item in values) / len(values)


def _reference(bars, method):
    highs = [float(value) for value in bars["high"]]
    lows = [float(value) for value in bars["low"]]
    closes = [float(value) for value in bars["close"]]
    fast_values = []
    for index in range(len(bars)):
        if index < _K_PERIOD - 1:
            fast_values.append(float("nan"))
            continue
        # The batch implementation uses chronological built-in min/max. Keep
        # that existing NaN ordering behavior as the parity reference.
        window_low = lows[index - _K_PERIOD + 1 : index + 1]
        window_high = highs[index - _K_PERIOD + 1 : index + 1]
        lowest = min(window_low)
        highest = max(window_high)
        denominator = highest - lowest
        fast_values.append(100.0 * (closes[index] - lowest) / denominator if denominator else 50.0)

    main_values = []
    signal_values = []
    previous_main = None
    previous_signal = None
    for index, fast in enumerate(fast_values):
        main = _reference_ma(
            fast_values[max(0, index - _SLOWING + 1) : index + 1],
            _SLOWING,
            previous_main,
            method,
        )
        main_values.append(main)
        previous_main = main

        signal = _reference_ma(
            main_values[max(0, index - _D_PERIOD + 1) : index + 1],
            _D_PERIOD,
            previous_signal,
            method,
        )
        signal_values.append(signal)
        previous_signal = signal

    start = _MINPERIOD - 1
    expected = {"main": [], "signal": [], "hist_base": [], "color_state": []}
    for index, main in enumerate(main_values):
        if index < start:
            for values in expected.values():
                values.append(float("nan"))
            continue

        expected["main"].append(main)
        expected["signal"].append(signal_values[index])
        expected["hist_base"].append(50.0)
        color = 0.0 if main > 60.0 else 2.0 if main < 40.0 else 1.0
        expected["color_state"].append(color)
    return expected


def _assert_series_equal(actual, expected):
    assert len(actual) == len(expected)
    for index, (got, want) in enumerate(zip(actual, expected)):
        if math.isnan(want):
            assert math.isnan(got), (index, got, want)
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12), (index, got, want)


@pytest.mark.parametrize("method", ["sma", "ema", "smma", "lwma", "unknown"])
def test_runnext_matches_full_batch_series_and_independent_formula(method):
    bars = _bars(40)
    streaming = _run(bars, ma_method=method, runonce=False)
    batch = _run(bars, ma_method=method, runonce=True)
    expected = _reference(bars, method)

    assert streaming.indicator._minperiod == _MINPERIOD
    assert batch.indicator._minperiod == _MINPERIOD
    assert streaming.downstream._minperiod == _MINPERIOD + 1
    assert batch.downstream._minperiod == _MINPERIOD + 1

    for name in ("main", "signal", "hist_base", "color_state"):
        streaming_values = list(getattr(streaming.indicator.lines, name).array)
        batch_values = list(getattr(batch.indicator.lines, name).array)
        _assert_series_equal(batch_values, expected[name])
        _assert_series_equal(streaming_values, expected[name])
        _assert_series_equal(streaming_values, batch_values)

    _assert_series_equal(
        list(streaming.downstream.lines[0].array),
        list(batch.downstream.lines[0].array),
    )


@pytest.mark.parametrize("method", ["sma", "ema", "smma", "lwma"])
def test_runnext_matches_batch_when_ohlc_contains_missing_values(method):
    bars = _bars(40, missing=True)
    streaming = _run(bars, ma_method=method, runonce=False)
    batch = _run(bars, ma_method=method, runonce=True)
    expected = _reference(bars, method)

    for name in ("main", "signal", "hist_base", "color_state"):
        streaming_values = list(getattr(streaming.indicator.lines, name).array)
        batch_values = list(getattr(batch.indicator.lines, name).array)
        _assert_series_equal(batch_values, expected[name])
        _assert_series_equal(streaming_values, expected[name])


def test_short_history_keeps_existing_minperiod_and_does_not_publish_outputs():
    bars = _bars(_MINPERIOD - 1)
    for runonce in (False, True):
        strategy = _run(bars, runonce=runonce)
        assert strategy.indicator._minperiod == _MINPERIOD
        assert strategy.downstream._minperiod == _MINPERIOD + 1
        for line in strategy.indicator.lines:
            assert not any(math.isfinite(value) for value in line.array)
        assert strategy.nextstart_calls == 0
        assert strategy.next_calls == 0


def test_streaming_does_not_add_callbacks_and_custom_prenext_keeps_legacy_path():
    bars = _bars(18)
    ordinary = _run(bars, runonce=False)
    assert ordinary.prenext_calls == _MINPERIOD
    assert ordinary.nextstart_calls == 1
    assert ordinary.next_calls == len(bars) - _MINPERIOD

    custom = _run(bars, runonce=False, indicator_type=_CustomWarmupHistogram)
    assert custom.indicator.custom_prenext_calls == _MINPERIOD - 1
    assert custom.indicator._stream_state_params is None


def test_streaming_matches_with_preload_and_bounded_buffers():
    bars = _bars(40)
    unpreloaded = _run(bars, runonce=False, preload=False)
    preloaded = _run(bars, runonce=False, preload=True)
    bounded = _run(bars, runonce=False, preload=False, exactbars=1)

    for candidate in (preloaded, bounded):
        assert [sample[0] for sample in candidate.samples] == [
            sample[0] for sample in unpreloaded.samples
        ]
        for column in range(1, 6):
            _assert_series_equal(
                [sample[column] for sample in candidate.samples],
                [sample[column] for sample in unpreloaded.samples],
            )

    assert len(bounded.indicator._stream_fast_values) <= _SLOWING
    assert len(bounded.indicator._stream_main_values) <= _D_PERIOD


def test_unmodified_indicator_subclass_uses_the_same_streaming_history():
    bars = _bars(28)
    inherited = _run(bars, runonce=False, indicator_type=_InheritedHistogram)
    batch = _run(bars, runonce=True, indicator_type=_InheritedHistogram)

    for name in ("main", "signal", "hist_base", "color_state"):
        _assert_series_equal(
            list(getattr(inherited.indicator.lines, name).array),
            list(getattr(batch.indicator.lines, name).array),
        )


def test_dynamic_period_change_switches_to_the_original_line_path():
    strategy = _run(
        _bars(24),
        runonce=False,
        strategy_type=_DynamicPeriodStrategy,
    )

    assert strategy.next_calls > 1
    assert strategy.indicator.p.k_period == 4
    assert strategy.indicator._stream_force_legacy


@pytest.mark.parametrize("method", ["ema", "smma"])
def test_multiclock_repeated_source_length_does_not_advance_or_replace_state(method):
    strategy = _run_secondary_clock(method)
    samples = strategy.clock_samples
    repeated = [
        (previous, current)
        for previous, current in zip(samples, samples[1:])
        if previous[0] == current[0] and previous[2] == current[2]
    ]

    assert repeated
    assert not strategy.indicator._stream_force_legacy
    for previous, current in repeated:
        assert current[3] == pytest.approx(previous[3], rel=0, abs=0)
        assert current[4] == pytest.approx(previous[4], rel=0, abs=0)


@pytest.mark.parametrize("method", ["ema", "smma"])
def test_replay_recomputes_revised_bar_from_its_prebar_state(method):
    strategy = _run_replay(method)
    samples = strategy.samples
    repeated = [
        (previous, current)
        for previous, current in zip(samples, samples[1:])
        if previous[0] == current[0]
    ]

    assert repeated
    assert not strategy.indicator._stream_force_legacy
    assert any(previous[2] != current[2] for previous, current in repeated)
    for sample in samples:
        assert sample[3] == pytest.approx(sample[5], rel=1e-12, abs=1e-12)
        assert sample[4] == pytest.approx(sample[6], rel=1e-12, abs=1e-12)
    for previous, current in zip(samples, samples[1:]):
        if previous[0] == current[0] and previous[2] == current[2]:
            assert current[3] == pytest.approx(previous[3], rel=0, abs=0)
            assert current[4] == pytest.approx(previous[4], rel=0, abs=0)


@pytest.mark.parametrize("method", ["sma", "ema", "smma", "lwma", "unknown"])
def test_exactbars_bounded_buffers_match_batch_and_unbounded_for_all_methods(method):
    bars = _bars(45)
    unbounded = _run(bars, ma_method=method, runonce=False, preload=False, exactbars=0)
    bounded = _run(bars, ma_method=method, runonce=False, preload=False, exactbars=1)
    batch = _run(bars, ma_method=method, runonce=True, preload=True, exactbars=0)

    assert not bounded.indicator._stream_force_legacy
    assert len(bounded.indicator._stream_fast_values) <= _SLOWING
    assert len(bounded.indicator._stream_main_values) <= _D_PERIOD
    assert [s[0] for s in bounded.samples] == [s[0] for s in unbounded.samples]
    assert [s[0] for s in bounded.samples] == [s[0] for s in batch.samples]
    for column in range(1, 6):
        _assert_series_equal(
            [s[column] for s in bounded.samples],
            [s[column] for s in unbounded.samples],
        )
        _assert_series_equal(
            [s[column] for s in bounded.samples],
            [s[column] for s in batch.samples],
        )


@pytest.mark.parametrize("method", ["sma", "ema", "smma"])
def test_exactbars_bounded_replay_matches_unbounded_replay(method):
    closes = [100.0]
    for index in range(1, 100):
        closes.append(closes[-1] + ((index * 17) % 11 - 5) * 0.13)
    minute_bars = pd.DataFrame(
        {
            "open": [value - 0.04 for value in closes],
            "high": [value + 0.2 + (index % 3) * 0.07 for index, value in enumerate(closes)],
            "low": [value - 0.25 - (index % 4) * 0.03 for index, value in enumerate(closes)],
            "close": closes,
            "volume": [1.0] * len(closes),
        },
        index=pd.date_range("2020-01-01 09:00", periods=len(closes), freq="min"),
    )

    def _run_eb_replay(exactbars):
        source = bt.feeds.PandasData(
            dataname=minute_bars,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
        )
        cerebro = bt.Cerebro(
            runonce=False, preload=False, exactbars=exactbars, stdstats=False
        )
        cerebro.replaydata(source, timeframe=bt.TimeFrame.Minutes, compression=5)
        cerebro.addstrategy(_CaptureStrategy, ma_method=method)
        return cerebro.run()[0]

    unbounded = _run_eb_replay(0)
    bounded = _run_eb_replay(1)
    assert not bounded.indicator._stream_force_legacy
    assert len(bounded.samples) == len(unbounded.samples)
    for column in range(1, 6):
        _assert_series_equal(
            [s[column] for s in bounded.samples],
            [s[column] for s in unbounded.samples],
        )


def test_failed_output_write_rolls_back_partial_outputs_and_preserves_stream_state():
    """A mid-write exception on a replay revision must keep prior committed state."""
    closes = [100.0]
    for index in range(1, 110):
        closes.append(closes[-1] + ((index * 13) % 9 - 4) * 0.19)
    minute_bars = pd.DataFrame(
        {
            "open": [value - 0.04 for value in closes],
            "high": [value + 0.25 + (index % 3) * 0.08 for index, value in enumerate(closes)],
            "low": [value - 0.25 - (index % 4) * 0.05 for index, value in enumerate(closes)],
            "close": closes,
            "volume": [1.0] * len(closes),
        },
        index=pd.date_range("2020-01-01 09:00", periods=len(closes), freq="min"),
    )

    fail_length = _MINPERIOD + 2
    failure = RuntimeError("synthetic signal line write failure")

    class _FailSignalBinding:
        def __init__(self):
            self._is_datetime_line = False
            self.fail_next = False
            self.failed = False

        def updateminperiod(self, minperiod):
            pass

        def __setitem__(self, idx, value):
            if self.fail_next:
                self.fail_next = False
                self.failed = True
                raise failure

    class _Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.StochasticHistogramIndicator(
                self.data,
                k_period=_K_PERIOD,
                slowing=_SLOWING,
                d_period=_D_PERIOD,
                ma_method="ema",
            )
            self._signal_binding = _FailSignalBinding()
            self.indicator.lines.signal.addbinding(self._signal_binding)
            self.calls_at_fail = 0
            self.last_ok_at_fail = None
            self.post_fail_outputs = None
            self.next_bar_sample = None

        def _next(self):
            if len(self.data) == fail_length:
                self.calls_at_fail += 1
                if self.calls_at_fail == 2:
                    self._signal_binding.fail_next = True
            try:
                return super()._next()
            except RuntimeError as exc:
                if exc is not failure:
                    raise
                self.post_fail_outputs = (
                    float(self.indicator.main[0]),
                    float(self.indicator.signal[0]),
                    float(self.indicator.color_state[0]),
                    float(self.indicator.hist_base[0]),
                )

        def next(self):
            cur = (
                float(self.indicator.main[0]),
                float(self.indicator.signal[0]),
                float(self.indicator.color_state[0]),
                float(self.indicator.hist_base[0]),
            )
            if len(self.data) == fail_length:
                self.last_ok_at_fail = cur
            elif len(self.data) == fail_length + 1 and self.next_bar_sample is None:
                self.next_bar_sample = (
                    cur,
                    self.indicator._stream_state_count,
                    self.indicator._stream_force_legacy,
                )

    source = bt.feeds.PandasData(
        dataname=minute_bars,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    cerebro.replaydata(source, timeframe=bt.TimeFrame.Minutes, compression=5)
    cerebro.addstrategy(_Probe)
    strategy = cerebro.run()[0]

    assert strategy._signal_binding.failed
    assert strategy.last_ok_at_fail is not None
    assert strategy.post_fail_outputs == strategy.last_ok_at_fail
    assert strategy.next_bar_sample is not None
    assert strategy.next_bar_sample[1] == fail_length + 1
    assert not strategy.next_bar_sample[2]
