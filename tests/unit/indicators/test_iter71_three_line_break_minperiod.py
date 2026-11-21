"""Cerebro regressions for ThreeLineBreakIndicator's first valid window."""

import math

import pandas as pd
import pytest

import backtrader as bt
from backtrader.linebuffer import LineBuffer
from backtrader.indicators.contrib.three_line_break_indicator import (
    ThreeLineBreakIndicator,
)


def _bars_with_first_bearish_break(period):
    """Return bars whose first complete prior-period window breaks bearish."""
    rows = []
    for index in range(period):
        low = 9.0 + index * 0.1
        high = 10.0 + index * 0.1
        rows.append((high, low))

    # This is the first bar with ``period`` prior bars. It breaks their lows.
    rows.append((9.0, 8.0))

    # Keep the established bearish state until the final bullish breakout.
    for offset in range(1, period + 2):
        rows.append((9.0 - offset * 0.1, 8.0 + offset * 0.1))
    rows.append((11.0, 8.5))
    return rows


def _expected_trend(rows, period):
    """Return the trend from the documented prior-window breakout rule."""
    swing = True
    result = []
    for index, (high, low) in enumerate(rows):
        if index < period:
            result.append(0.0 if swing else 1.0)
            continue

        previous = rows[index - period : index]
        highest = max(bar_high for bar_high, _ in previous)
        lowest = min(bar_low for _, bar_low in previous)
        if swing and low < lowest:
            swing = False
        if not swing and high > highest:
            swing = True
        result.append(0.0 if swing else 1.0)
    return result


def _run_indicator(rows, period, runonce):
    """Run the indicator on a real Cerebro feed and return its full trend line."""
    closes = [(high + low) / 2.0 for high, low in rows]
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": [high for high, _ in rows],
            "low": [low for _, low in rows],
            "close": closes,
            "volume": [1.0] * len(rows),
            "openinterest": [0.0] * len(rows),
        },
        index=pd.date_range("2026-01-01", periods=len(rows), freq="D"),
    )

    class ProbeStrategy(bt.Strategy):
        def __init__(self):
            self.indicator = ThreeLineBreakIndicator(self.data, lines_break=period)

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(ProbeStrategy)
    strategy = cerebro.run()[0]
    return (
        strategy.indicator._minperiod,
        list(strategy.indicator.trend.array),
        list(strategy.indicator.line_high.array),
        list(strategy.indicator.line_low.array),
    )


@pytest.mark.parametrize("period", [1, 3, 5])
@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_three_line_break_uses_first_complete_lookback(period, runonce):
    """The first breakout is evaluated with exactly ``period`` prior bars."""
    rows = _bars_with_first_bearish_break(period)
    minperiod, trend, _, _ = _run_indicator(rows, period, runonce)

    # Keep the strategy's existing lifecycle threshold while calculating
    # partial trend values during prenext/preonce.
    assert minperiod == period + 2
    assert len(trend) == len(rows)
    assert trend[:period] == pytest.approx([0.0] * period)
    assert trend[period] == pytest.approx(1.0)
    assert all(value == pytest.approx(1.0) for value in trend[period:-1])
    assert trend[-1] == pytest.approx(0.0)


def test_three_line_break_run_modes_match_with_a_missing_bar():
    """A missing OHLC sample does not reset swing state or split-mode parity."""
    period = 3
    rows = _bars_with_first_bearish_break(period)
    missing_index = period + 2
    rows[missing_index] = (float("nan"), float("nan"))

    next_minperiod, next_trend, next_high, next_low = _run_indicator(rows, period, runonce=False)
    once_minperiod, once_trend, once_high, once_low = _run_indicator(rows, period, runonce=True)

    assert next_minperiod == once_minperiod == period + 2
    assert len(next_trend) == len(once_trend) == len(rows)
    for next_value, once_value in zip(next_trend, once_trend):
        if math.isnan(float(next_value)):
            assert math.isnan(float(once_value))
        else:
            assert once_value == pytest.approx(next_value)

    for next_values, once_values in ((next_high, once_high), (next_low, once_low)):
        for next_value, once_value in zip(next_values, once_values):
            if math.isnan(float(next_value)):
                assert math.isnan(float(once_value))
            else:
                assert once_value == pytest.approx(next_value)

    assert next_trend[:period] == pytest.approx([0.0] * period)
    assert next_trend[period] == pytest.approx(1.0)
    assert math.isnan(float(next_high[missing_index]))
    assert math.isnan(float(next_low[missing_index]))
    assert next_trend[missing_index] == pytest.approx(1.0)
    assert next_trend[missing_index + 1] == pytest.approx(1.0)
    assert next_trend[-1] == pytest.approx(0.0)


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_three_line_break_secondary_clock_matches_source_bars(runonce):
    """Warmup output follows the secondary clock when the primary is faster."""
    period = 3
    signal_rows = _bars_with_first_bearish_break(period)
    signal_dates = pd.date_range("2026-01-01", periods=len(signal_rows), freq="3D")
    signal_frame = pd.DataFrame(
        {
            "open": [(high + low) / 2.0 for high, low in signal_rows],
            "high": [high for high, _ in signal_rows],
            "low": [low for _, low in signal_rows],
            "close": [(high + low) / 2.0 for high, low in signal_rows],
            "volume": [1.0] * len(signal_rows),
            "openinterest": [0.0] * len(signal_rows),
        },
        index=signal_dates,
    )
    primary_dates = pd.date_range(signal_dates[0], periods=(len(signal_rows) - 1) * 3 + 1, freq="D")
    primary_values = [100.0 + index for index in range(len(primary_dates))]
    primary_frame = pd.DataFrame(
        {
            "open": primary_values,
            "high": [value + 1.0 for value in primary_values],
            "low": [value - 1.0 for value in primary_values],
            "close": primary_values,
            "volume": [1.0] * len(primary_values),
            "openinterest": [0.0] * len(primary_values),
        },
        index=primary_dates,
    )

    class ProbeStrategy(bt.Strategy):
        def __init__(self):
            self.indicator = ThreeLineBreakIndicator(self.datas[1], lines_break=period)

    cerebro = bt.Cerebro(runonce=runonce, preload=runonce, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=primary_frame))
    cerebro.adddata(bt.feeds.PandasData(dataname=signal_frame))
    cerebro.addstrategy(ProbeStrategy)
    strategy = cerebro.run()[0]

    trend = list(strategy.indicator.trend.array)
    assert len(trend) == len(signal_rows)
    assert trend == pytest.approx(_expected_trend(signal_rows, period))


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_three_line_break_subclass_next_keeps_its_warmup_contract(runonce):
    """An overridden ``next`` is not newly invoked during base warmup."""
    period = 3
    rows = _bars_with_first_bearish_break(period)
    closes = [(high + low) / 2.0 for high, low in rows]
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": [high for high, _ in rows],
            "low": [low for _, low in rows],
            "close": closes,
            "volume": [1.0] * len(rows),
            "openinterest": [0.0] * len(rows),
        },
        index=pd.date_range("2026-01-01", periods=len(rows), freq="D"),
    )

    class CountingIndicator(ThreeLineBreakIndicator):
        def __init__(self):
            self.call_lengths = []
            super().__init__()

        def next(self):
            self.call_lengths.append(len(self.data))
            super().next()

    class ProbeStrategy(bt.Strategy):
        def __init__(self):
            self.indicator = CountingIndicator(self.data, lines_break=period)

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(ProbeStrategy)
    strategy = cerebro.run()[0]

    assert strategy.indicator.call_lengths == list(range(period + 2, len(rows) + 1))


def test_three_line_break_replay_uses_finalized_bar_values():
    """Replay updates of one source bar do not double-count the trend state."""
    period = 3
    daily_rows = _bars_with_first_bearish_break(period)
    minute_rows = []
    minute_dates = []
    for day, (high, low) in enumerate(daily_rows):
        middle = (high + low) / 2.0
        minute_rows.extend(
            [
                (middle, middle, middle),
                (middle, high, low),
                (middle, high, low),
            ]
        )
        start = pd.Timestamp("2026-01-01") + pd.Timedelta(days=day)
        minute_dates.extend([start + pd.Timedelta(hours=9 + hour) for hour in range(3)])
    closes = [close for close, _, _ in minute_rows]
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": [high for _, high, _ in minute_rows],
            "low": [low for _, _, low in minute_rows],
            "close": closes,
            "volume": [1.0] * len(minute_rows),
            "openinterest": [0.0] * len(minute_rows),
        },
        index=minute_dates,
    )

    class ProbeStrategy(bt.Strategy):
        def __init__(self):
            self.indicator = ThreeLineBreakIndicator(self.data, lines_break=period)

    cerebro = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    source = bt.feeds.PandasData(
        dataname=frame,
        timeframe=bt.TimeFrame.Minutes,
        compression=60,
    )
    cerebro.replaydata(source, timeframe=bt.TimeFrame.Days, compression=1)
    cerebro.addstrategy(ProbeStrategy)
    strategy = cerebro.run(runonce=False, preload=False)[0]

    trend = list(strategy.indicator.trend.array)
    assert len(trend) == len(daily_rows)
    assert trend == pytest.approx(_expected_trend(daily_rows, period))


def test_three_line_break_retries_same_bar_after_output_write_failure(monkeypatch):
    """A failed line write must not commit state or suppress a same-bar retry."""
    period = 3
    rows = _bars_with_first_bearish_break(period)
    closes = [(high + low) / 2.0 for high, low in rows]
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": [high for high, _ in rows],
            "low": [low for _, low in rows],
            "close": closes,
            "volume": [1.0] * len(rows),
            "openinterest": [0.0] * len(rows),
        },
        index=pd.date_range("2026-01-01", periods=len(rows), freq="D"),
    )
    bindings = {}
    failed = False
    original_setitem = LineBuffer.__setitem__

    def fail_low_once(line, ago, value):
        nonlocal failed
        indicator = bindings.get("indicator")
        if (
            not failed
            and indicator is not None
            and line is bindings["line_low"]
            and len(indicator.data) == period + 1
            and ago == 0
        ):
            failed = True
            raise RuntimeError("synthetic line write failure")
        return original_setitem(line, ago, value)

    monkeypatch.setattr(LineBuffer, "__setitem__", fail_low_once)

    class RetryIndicator(ThreeLineBreakIndicator):
        def __init__(self):
            self.retry_failures = 0
            self.retried = False
            self.retry_state = None
            super().__init__()
            bindings["indicator"] = self
            bindings["line_low"] = self.lines.line_low

        def prenext(self):
            if len(self.data) == period + 1 and not self.retried:
                try:
                    super().prenext()
                except RuntimeError as exc:
                    assert str(exc) == "synthetic line write failure"
                    self.retry_failures += 1
                    super().prenext()
                    self.retry_state = (
                        self._swing,
                        float(self.trend[0]),
                        float(self.line_low[0]),
                    )
                    self.retried = True
                return
            super().prenext()

    class ProbeStrategy(bt.Strategy):
        def __init__(self):
            self.indicator = RetryIndicator(self.data, lines_break=period)

    cerebro = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(ProbeStrategy)
    strategy = cerebro.run()[0]

    indicator = strategy.indicator
    assert indicator.retry_failures == 1
    assert indicator.retried
    assert indicator.retry_state == (False, 1.0, rows[period][1])


def test_three_line_break_revision_failure_does_not_leave_mixed_outputs(monkeypatch):
    """A failed B revision cannot poison a later return to committed A."""
    period = 3
    rows = _bars_with_first_bearish_break(period)
    closes = [(high + low) / 2.0 for high, low in rows]
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": [high for high, _ in rows],
            "low": [low for _, low in rows],
            "close": closes,
            "volume": [1.0] * len(rows),
            "openinterest": [0.0] * len(rows),
        },
        index=pd.date_range("2026-01-01", periods=len(rows), freq="D"),
    )
    bindings = {}
    failed = False
    original_setitem = LineBuffer.__setitem__

    def fail_revision_low_once(line, ago, value):
        nonlocal failed
        indicator = bindings.get("indicator")
        if (
            not failed
            and indicator is not None
            and line is bindings["line_low"]
            and len(indicator.data) == period + 1
            and float(indicator.data.high[0]) == 19.0
            and ago == 0
        ):
            failed = True
            raise RuntimeError("synthetic revision write failure")
        return original_setitem(line, ago, value)

    monkeypatch.setattr(LineBuffer, "__setitem__", fail_revision_low_once)

    class RevisionIndicator(ThreeLineBreakIndicator):
        def __init__(self):
            self.revision_result = None
            self.revision_failed = False
            super().__init__()
            bindings["indicator"] = self
            bindings["line_low"] = self.lines.line_low

        def prenext(self):
            if len(self.data) == period + 1 and self.revision_result is None:
                # Revision A is successfully published first.
                super().prenext()
                assert self._swing is False
                assert self.line_high[0] == pytest.approx(rows[period][0])

                # Revision B writes line_high and then fails on line_low.
                self.data.high[0] = 19.0
                self.data.low[0] = 7.0
                with pytest.raises(RuntimeError, match="synthetic revision write failure"):
                    super().prenext()
                self.revision_failed = True

                # Returning to A must recompute or have restored all outputs.
                self.data.high[0], self.data.low[0] = rows[period]
                super().prenext()
                self.revision_result = (
                    self._swing,
                    float(self.trend[0]),
                    float(self.line_high[0]),
                    float(self.line_low[0]),
                )
                return
            super().prenext()

    class ProbeStrategy(bt.Strategy):
        def __init__(self):
            self.indicator = RevisionIndicator(self.data, lines_break=period)

    cerebro = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(ProbeStrategy)
    strategy = cerebro.run()[0]

    assert failed
    assert strategy.indicator.revision_failed
    assert strategy.indicator.revision_result == (
        False,
        1.0,
        rows[period][0],
        rows[period][1],
    )


def test_three_line_break_repeats_invalid_empty_window_failure():
    """A failed calculation leaves no signature that can swallow a retry."""
    rows = [(10.0, 9.0), (10.1, 9.1), (10.2, 9.2)]
    closes = [(high + low) / 2.0 for high, low in rows]
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": [high for high, _ in rows],
            "low": [low for _, low in rows],
            "close": closes,
            "volume": [1.0] * len(rows),
            "openinterest": [0.0] * len(rows),
        },
        index=pd.date_range("2026-01-01", periods=len(rows), freq="D"),
    )
    observations = {}

    class RetryInvalidPeriodIndicator(ThreeLineBreakIndicator):
        def prenext(self):
            errors = []
            for _ in range(2):
                try:
                    super().prenext()
                except ValueError as exc:
                    errors.append(str(exc))
            observations["errors"] = errors
            observations["signature"] = self._last_calculation_signature
            observations["bar_len"] = self._last_calculation_bar_len
            raise ValueError(errors[0])

    class ProbeStrategy(bt.Strategy):
        def __init__(self):
            self.indicator = RetryInvalidPeriodIndicator(self.data, lines_break=0)

    cerebro = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(ProbeStrategy)
    with pytest.raises(ValueError, match="max\(\) arg is an empty sequence"):
        cerebro.run()

    assert observations["errors"] == [
        "max() arg is an empty sequence",
        "max() arg is an empty sequence",
    ]
    assert observations["signature"] is None
    assert observations["bar_len"] is None


def test_three_line_break_replay_correction_restarts_from_bar_state():
    """A corrected current replay bar can retract its provisional breakout."""
    period = 3
    rows = _bars_with_first_bearish_break(period)
    closes = [(high + low) / 2.0 for high, low in rows]
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": [high for high, _ in rows],
            "low": [low for _, low in rows],
            "close": closes,
            "volume": [1.0] * len(rows),
            "openinterest": [0.0] * len(rows),
        },
        index=pd.date_range("2026-01-01", periods=len(rows), freq="D"),
    )

    class ProbeStrategy(bt.Strategy):
        def __init__(self):
            self.indicator = ThreeLineBreakIndicator(self.data, lines_break=period)
            self.correction = None

        def prenext(self):
            if len(self.data) == period + 1 and self.correction is None:
                assert self.indicator.trend[0] == pytest.approx(1.0)
                self.data.low[0] = 9.2
                self.indicator.next()
                self.correction = (
                    self.indicator._swing,
                    float(self.indicator.trend[0]),
                    float(self.indicator.line_low[0]),
                )

    cerebro = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(ProbeStrategy)
    strategy = cerebro.run()[0]

    assert strategy.correction == (True, 0.0, 9.2)
