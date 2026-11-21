"""Cerebro coverage for DigitalMacd FIR accumulation (R71-046)."""

from datetime import datetime, timedelta
import math

import backtrader as bt
import pandas as pd
import pytest


_SIGNAL_PERIOD = 4
_POINT = 0.01
_BAR_COUNT = 420


def _closes():
    """Include cancellation, overflow, and non-finite windows with recovery."""
    values = [
        (-1.0 if index % 2 else 1.0) * 1.0e16 + (index % 13) * 0.25
        for index in range(_BAR_COUNT)
    ]
    # Make the first complete fast FIR window a finite near-overflow sum. The
    # point scaling makes MACD non-finite, exercising the signal's existing
    # finite-history gate without changing the FIR accumulation.
    fast_coeffs = bt.indicators.DigitalMacd.FAST_COEFFS
    for tap, coefficient in enumerate(fast_coeffs):
        values[len(fast_coeffs) - tap - 1] = math.copysign(1.0e308, coefficient)

    values[145] = float("nan")
    values[235] = float("inf")
    values[325] = float("-inf")
    return tuple(values)


_CLOSES = _closes()


class _DigitalMacdProbe(bt.Strategy):
    def __init__(self):
        self.indicator = bt.indicators.DigitalMacd(
            self.data, signal_period=_SIGNAL_PERIOD, point=_POINT
        )

    def start(self):
        # Parameters are captured by the indicator at construction. Mutating
        # p later does not resize its history or change its scaling mid-run.
        self.indicator.p.signal_period = 2
        self.indicator.p.point = 0.5


def _frame_for_closes(closes):
    start = datetime(2025, 1, 1)
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=pd.DatetimeIndex(
            [start + timedelta(minutes=index) for index in range(len(closes))]
        ),
    )


def _run_cerebro(runonce):
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame_for_closes(_CLOSES)))
    cerebro.addstrategy(_DigitalMacdProbe)
    return cerebro.run(runonce=runonce, preload=True)[0]


def _reference(closes):
    """Use the prior tuple/index accumulation order as an independent oracle."""
    indicator_type = bt.indicators.DigitalMacd
    fast_coeffs = tuple(float(value) for value in indicator_type.FAST_COEFFS)
    slow_coeffs = tuple(float(value) for value in indicator_type.SLOW_COEFFS)
    lookback = max(len(fast_coeffs), len(slow_coeffs))

    macd = [float("nan")] * len(closes)
    signal = [float("nan")] * len(closes)
    history = []
    for end in range(len(closes)):
        if end + 1 < lookback:
            value = float("nan")
        else:
            window = tuple(closes[end - offset] for offset in range(lookback))
            fast = 0.0
            for index, coefficient in enumerate(fast_coeffs):
                fast += coefficient * window[index]
            slow = 0.0
            for index, coefficient in enumerate(slow_coeffs):
                slow += coefficient * window[index]
            value = (fast - slow) / _POINT
            # Cerebro's line buffer represents non-finite indicator writes as
            # NaN, which is also what the consumer observes from DigitalMacd.
            if not math.isfinite(value):
                value = float("nan")

        macd[end] = value
        history.append(value)
        if len(history) > _SIGNAL_PERIOD:
            history.pop(0)
        if len(history) == _SIGNAL_PERIOD and all(math.isfinite(item) for item in history):
            signal_value = sum(history) / _SIGNAL_PERIOD
            if math.isfinite(signal_value):
                signal[end] = signal_value

    return macd, signal, lookback


def _assert_exact(actual, expected):
    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected):
        if math.isnan(expected_value):
            assert math.isnan(actual_value)
        else:
            assert actual_value == expected_value


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_digital_macd_convolution_preserves_fir_order_and_init_period(runonce):
    strategy = _run_cerebro(runonce)
    indicator = strategy.indicator
    # Reference the values Cerebro's PandasData feed exposes to the indicator;
    # for example, its input projection normalizes infinity to 0.0.
    expected_macd, expected_signal, lookback = _reference(
        list(strategy.data.close.array)
    )
    actual_macd = list(indicator.macd.array)
    actual_signal = list(indicator.signal.array)

    _assert_exact(actual_macd, expected_macd)
    _assert_exact(actual_signal, expected_signal)
    assert indicator._signal_period == _SIGNAL_PERIOD
    assert indicator._point == _POINT
    assert indicator.p.signal_period == 2
    assert indicator.p.point == 0.5
    assert indicator._minperiod == lookback + _SIGNAL_PERIOD - 1
    assert math.isnan(actual_macd[lookback - 1])
    assert math.isnan(actual_signal[lookback - 1])
    assert math.isfinite(actual_macd[145 + lookback])
    assert math.isfinite(actual_signal[145 + lookback + _SIGNAL_PERIOD - 1])


class _SegmentedDigitalMacd(bt.indicators.DigitalMacd):
    """Split once() into mixed small (<16) and large (>=16) segments."""

    def __init__(self):
        self._once_ranges = []
        super().__init__()

    def once(self, start, end):
        if end - start <= 1:
            self._once_ranges.append((start, end))
            return super().once(start, end)
        chunk_sizes = (1, 5, 13, 37, 64)
        cursor = start
        step_idx = 0
        while cursor < end:
            chunk = chunk_sizes[step_idx % len(chunk_sizes)]
            seg_end = min(cursor + chunk, end)
            self._once_ranges.append((cursor, seg_end))
            super().once(cursor, seg_end)
            cursor = seg_end
            step_idx += 1


def test_digital_macd_segmented_once_and_python_fallback_match_bit_exact(monkeypatch):
    import backtrader.indicators.contrib.digital_macd as dm_mod

    class _SegProbe(bt.Strategy):
        def __init__(self):
            self.indicator = _SegmentedDigitalMacd(
                self.data, signal_period=_SIGNAL_PERIOD, point=_POINT
            )

    def _run_seg():
        cerebro = bt.Cerebro(stdstats=False)
        cerebro.adddata(bt.feeds.PandasData(dataname=_frame_for_closes(_CLOSES)))
        cerebro.addstrategy(_SegProbe)
        return cerebro.run(runonce=True, preload=True)[0]

    seg_strategy = _run_seg()
    expected_macd, expected_signal, _ = _reference(
        list(seg_strategy.data.close.array)
    )
    assert len(seg_strategy.indicator._once_ranges) > 6
    _assert_exact(list(seg_strategy.indicator.macd.array), expected_macd)
    _assert_exact(list(seg_strategy.indicator.signal.array), expected_signal)

    # Also verify pure-Python once() fallback when NumPy is unavailable.
    monkeypatch.setattr(dm_mod, "_np", None)
    py_strategy = _run_cerebro(runonce=True)
    _assert_exact(list(py_strategy.indicator.macd.array), expected_macd)
    _assert_exact(list(py_strategy.indicator.signal.array), expected_signal)


def test_digital_macd_exactbars_and_subclass_override():
    class _CaptureProbe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.DigitalMacd(
                self.data, signal_period=_SIGNAL_PERIOD, point=_POINT
            )
            self.rows = []

        def next(self):
            self.rows.append(
                (
                    len(self.data),
                    float(self.indicator.macd[0]),
                    float(self.indicator.signal[0]),
                )
            )

    cerebro_eb = bt.Cerebro(stdstats=False, exactbars=1)
    cerebro_eb.adddata(bt.feeds.PandasData(dataname=_frame_for_closes(_CLOSES)))
    cerebro_eb.addstrategy(_CaptureProbe)
    eb_strat = cerebro_eb.run(runonce=False, preload=False)[0]

    batch_strat = _run_cerebro(runonce=True)
    expected_macd = list(batch_strat.indicator.macd.array)
    expected_signal = list(batch_strat.indicator.signal.array)
    assert eb_strat.rows
    for length, got_m, got_s in eb_strat.rows:
        idx = length - 1
        if math.isnan(expected_macd[idx]):
            assert math.isnan(got_m)
        else:
            assert got_m == expected_macd[idx]
        if math.isnan(expected_signal[idx]):
            assert math.isnan(got_s)
        else:
            assert got_s == expected_signal[idx]

    class _CustomNextDigitalMacd(bt.indicators.DigitalMacd):
        def __init__(self):
            self.custom_next_calls = 0
            super().__init__()

        def next(self):
            self.custom_next_calls += 1
            super().next()

    class _CustomProbe(bt.Strategy):
        def __init__(self):
            self.indicator = _CustomNextDigitalMacd(
                self.data, signal_period=_SIGNAL_PERIOD, point=_POINT
            )

    cerebro_custom = bt.Cerebro(stdstats=False)
    cerebro_custom.adddata(bt.feeds.PandasData(dataname=_frame_for_closes(_CLOSES[:100])))
    cerebro_custom.addstrategy(_CustomProbe)
    custom_strat = cerebro_custom.run(runonce=True, preload=True)[0]
    assert custom_strat.indicator.custom_next_calls == 100
