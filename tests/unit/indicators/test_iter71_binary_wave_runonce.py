"""Runonce parity regression coverage for BinaryWaveIndicator."""

import math

import backtrader as bt
import pandas as pd
import pytest


def _run_binary_wave(
    bar_count,
    runonce,
    *,
    segment_size=None,
    input_nan_at=None,
    output_nan_at=None,
    indicator_params=None,
):
    """Run BinaryWaveIndicator in a real Cerebro and return both output lines."""
    close = [
        100.0 + index * 0.13 + ((index * 7) % 13) * 0.47
        + math.sin(index * 0.3) * 2.2
        for index in range(bar_count)
    ]
    high = [
        value + 1.1 + (index % 4) * 0.2
        for index, value in enumerate(close)
    ]
    low = [
        value - 0.9 - (index % 3) * 0.25
        for index, value in enumerate(close)
    ]
    if input_nan_at is not None:
        close[input_nan_at] = float("nan")
        high[input_nan_at] = float("nan")
        low[input_nan_at] = float("nan")
    frame = pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": [1000.0] * bar_count,
            "openinterest": [0.0] * bar_count,
        },
        index=pd.date_range("2026-01-01", periods=bar_count, freq="D"),
    )

    class BinaryWaveProbeIndicator(bt.indicators.BinaryWaveIndicator):
        def next(self):
            super().next()
            if output_nan_at == len(self.data) - 1:
                self.lines.raw[0] = float("nan")
                self.lines.wave[0] = float("nan")

        def once(self, start, end):
            if start >= end:
                super().once(start, end)
                return

            cursor = start
            while cursor < end:
                width = segment_size if segment_size is not None else end - start
                chunk_end = min(cursor + width, end)
                if output_nan_at is not None and cursor <= output_nan_at < chunk_end:
                    chunk_end = output_nan_at + 1

                super().once(cursor, chunk_end)
                if output_nan_at is not None and cursor <= output_nan_at < chunk_end:
                    self.lines.raw.array[output_nan_at] = float("nan")
                    self.lines.wave.array[output_nan_at] = float("nan")

                cursor = chunk_end
                # Exercise zero-length ranges between adjacent once segments.
                super().once(cursor, cursor)

    class BinaryWaveProbe(bt.Strategy):
        def __init__(self):
            self.wave = BinaryWaveProbeIndicator(
                self.data, **(indicator_params or {})
            )

        def stop(self):
            self.result = {
                "minperiod": self.wave._minperiod,
                "raw": list(self.wave.raw.array),
                "wave": list(self.wave.wave.array),
                "cci": list(self.wave.cci.array),
            }

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(BinaryWaveProbe)
    return cerebro.run()[0].result


def _ema_reference(raw, smooth_period):
    """Independently smooth raw scores, keeping undefined warmup values."""
    alpha = 2.0 / (smooth_period + 1.0)
    expected = []
    previous = None
    for score in raw:
        if math.isnan(score):
            expected.append(float("nan"))
            previous = None
            continue

        value = score if previous is None else previous + alpha * (score - previous)
        expected.append(value)
        previous = value
    return expected


def _assert_series_equal(actual, expected):
    assert len(actual) == len(expected)
    for index, (got, want) in enumerate(zip(actual, expected)):
        if math.isnan(want):
            assert math.isnan(got), f"index {index}: expected NaN, got {got!r}"
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12), (
                f"index {index}: expected {want!r}, got {got!r}"
            )


@pytest.mark.parametrize("bar_count", (41, 900))
def test_binary_wave_runonce_continues_smoothing_after_minperiod(bar_count):
    """Batch ranges carry prior state across the oncestart and empty ranges."""
    runnext = _run_binary_wave(bar_count, runonce=False)
    runonce = _run_binary_wave(bar_count, runonce=True)
    segmented = _run_binary_wave(bar_count, runonce=True, segment_size=13)

    assert runnext["minperiod"] == runonce["minperiod"] == 40
    assert runnext["minperiod"] == segmented["minperiod"]
    for result in (runnext, runonce, segmented):
        assert len(result["raw"]) == bar_count
        assert len(result["wave"]) == bar_count
    assert all(math.isnan(value) for value in runnext["raw"][:39])
    assert all(math.isnan(value) for value in runnext["wave"][:39])
    assert math.isfinite(runnext["raw"][39])
    assert math.isfinite(runnext["wave"][39])
    assert abs(runnext["raw"][40] - runnext["raw"][39]) > 1.0

    reference = _ema_reference(runnext["raw"], smooth_period=5)
    _assert_series_equal(runnext["wave"], reference)

    _assert_series_equal(runonce["raw"], runnext["raw"])
    _assert_series_equal(runonce["wave"], reference)
    _assert_series_equal(segmented["raw"], runnext["raw"])
    _assert_series_equal(segmented["wave"], reference)


def test_binary_wave_runtime_nan_input_matches_both_execution_modes():
    """NaN OHLC stays visible without resetting the finite EMA state."""
    # CCI has its own runnext/runonce NaN-window disagreement. Disable only its
    # BinaryWave weight here so this test isolates the wave's handling of the
    # missing OHLC row without changing that separate indicator.
    indicator_params = {"weight_cci": 0.0}
    runnext = _run_binary_wave(
        900,
        runonce=False,
        input_nan_at=100,
        indicator_params=indicator_params,
    )
    runonce = _run_binary_wave(
        900,
        runonce=True,
        segment_size=11,
        input_nan_at=100,
        indicator_params=indicator_params,
    )

    assert not math.isnan(runnext["raw"][100])
    assert not math.isnan(runonce["raw"][100])
    assert runnext["wave"][99] != 0.0
    assert runnext["wave"][100] != runnext["raw"][100]

    reference = _ema_reference(runnext["raw"], smooth_period=5)
    _assert_series_equal(runnext["wave"], reference)
    _assert_series_equal(runonce["raw"], runnext["raw"])
    _assert_series_equal(runonce["wave"], reference)


def test_binary_wave_default_cci_nan_input_matches_full_series():
    """Default CCI weighting preserves full-series runnext/runonce parity."""
    runnext = _run_binary_wave(160, runonce=False, input_nan_at=100)
    runonce = _run_binary_wave(160, runonce=True, input_nan_at=100)

    for result in (runnext, runonce):
        assert len(result["raw"]) == 160
        assert len(result["wave"]) == 160
        assert len(result["cci"]) == 160

    reference = _ema_reference(runnext["raw"], smooth_period=5)
    _assert_series_equal(runnext["cci"], runonce["cci"])
    _assert_series_equal(runnext["raw"], runonce["raw"])
    _assert_series_equal(runnext["wave"], reference)
    _assert_series_equal(runonce["wave"], reference)


def test_binary_wave_nan_previous_wave_reseeds_like_next():
    """A missing wave output remains NaN, then the next raw score reseeds it."""
    runnext = _run_binary_wave(160, runonce=False, output_nan_at=100)
    runonce = _run_binary_wave(
        160,
        runonce=True,
        segment_size=13,
        output_nan_at=100,
    )

    assert math.isnan(runnext["raw"][100])
    assert math.isnan(runnext["wave"][100])
    assert runnext["wave"][101] == runnext["raw"][101]

    reference = _ema_reference(runnext["raw"], smooth_period=5)
    _assert_series_equal(runnext["wave"], reference)
    _assert_series_equal(runonce["raw"], runnext["raw"])
    _assert_series_equal(runonce["wave"], reference)
