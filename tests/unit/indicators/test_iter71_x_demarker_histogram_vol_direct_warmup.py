"""Warmup and clock regressions for the migrated DeMarker histogram."""

import datetime as dt
import math

import backtrader as bt
import pandas as pd
import pytest


_LINE_NAMES = (
    "value",
    "color_zone",
    "color_direct",
    "upper2",
    "upper1",
    "lower1",
    "lower2",
)


def _rows(count):
    """Return deterministic bars with nontrivial DeMarker and volume signals."""
    rows = []
    for index in range(count):
        close = 100.0 + index * 0.37 + (index * 7 % 9) * 0.83
        rows.append(
            {
                "open": close - (index % 3) * 0.11,
                "high": close + 1.0 + (index % 3) * 0.2,
                "low": close - 0.8 - (index % 4) * 0.1,
                "close": close,
                "volume": 10.0 + index % 7,
                "openinterest": 20.0 + index % 5,
            }
        )
    return rows


def _frame(rows, *, day_step=1, start=dt.datetime(2025, 1, 1)):
    index = [start + dt.timedelta(days=day_step * i) for i in range(len(rows))]
    return pd.DataFrame(rows, index=index)


def _reference(rows, de_marker_period, ma_length):
    """Compute the documented rolling formula without using BT indicators."""
    de_marker_period = max(int(de_marker_period), 1)
    ma_length = max(int(ma_length), 1)
    demax = []
    demin = []
    raw = []
    volume_window = []
    result = {name: [math.nan] * len(rows) for name in _LINE_NAMES}

    for index in range(1, len(rows)):
        high_now = float(rows[index]["high"])
        high_prev = float(rows[index - 1]["high"])
        low_now = float(rows[index]["low"])
        low_prev = float(rows[index - 1]["low"])
        volume = float(rows[index]["volume"])
        if not math.isfinite(volume):
            volume = 0.0

        demax.append(max(high_now - high_prev, 0.0))
        demin.append(max(low_prev - low_now, 0.0))
        del demax[:-de_marker_period]
        del demin[:-de_marker_period]

        value = math.nan
        color_zone = math.nan
        color_direct = (
            result["color_direct"][index - 1]
            if math.isfinite(result["color_direct"][index - 1])
            else math.nan
        )
        bands = (math.nan, math.nan, math.nan, math.nan)

        if len(demax) >= de_marker_period and len(demin) >= de_marker_period:
            sum_max = sum(demax)
            sum_min = sum(demin)
            denom = sum_max + sum_min
            demarker = (
                math.nan if math.isnan(denom) else (sum_max / denom if denom > 0 else 0.5)
            )
            raw.append(((demarker * 100.0) - 50.0) * volume)
            volume_window.append(volume)
            del raw[:-ma_length]
            del volume_window[:-ma_length]

            if len(raw) >= ma_length and len(volume_window) >= ma_length:
                value = sum(raw) / len(raw)
                avg_volume = sum(volume_window) / len(volume_window)
                bands = (
                    20.0 * avg_volume,
                    15.0 * avg_volume,
                    -15.0 * avg_volume,
                    -20.0 * avg_volume,
                )
                upper2, upper1, lower1, lower2 = bands
                if value > upper2:
                    color_zone = 0.0
                elif value > upper1:
                    color_zone = 1.0
                elif value < lower2:
                    color_zone = 4.0
                elif value < lower1:
                    color_zone = 3.0
                else:
                    color_zone = 2.0

                previous_value = result["value"][index - 1]
                previous_direct = result["color_direct"][index - 1]
                if not math.isfinite(previous_direct):
                    previous_direct = 1.0
                if not math.isfinite(previous_value):
                    color_direct = previous_direct
                elif value > previous_value:
                    color_direct = 0.0
                elif value < previous_value:
                    color_direct = 1.0
                else:
                    color_direct = previous_direct
                if math.isnan(value):
                    color_zone = math.nan
                    color_direct = math.nan

        result["value"][index] = value
        result["color_zone"][index] = color_zone
        result["color_direct"][index] = color_direct
        for name, band in zip(("upper2", "upper1", "lower1", "lower2"), bands):
            result[name][index] = band

    return result


def _assert_lines(actual, expected, *, start=0):
    assert actual.keys() == expected.keys()
    for name in expected:
        got = actual[name]
        want = expected[name]
        assert len(got) == len(want), name
        for index in range(start, len(want)):
            if math.isnan(want[index]):
                assert math.isnan(got[index]), (name, index, got[index])
            else:
                assert got[index] == pytest.approx(
                    want[index], rel=1e-12, abs=1e-12
                ), (name, index)


def _run_once_or_next(rows, de_marker_period, ma_length, runonce):
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.XDeMarkerHistogramVolDirectIndicator(
                self.data,
                de_marker_period=de_marker_period,
                ma_length=ma_length,
            )
            self.callback_lengths = []

        def next(self):
            self.callback_lengths.append(len(self.data))

        def stop(self):
            self.result = {
                "minperiod": self.indicator._minperiod,
                "callback_lengths": list(self.callback_lengths),
                "lines": {
                    name: list(getattr(self.indicator.lines, name).array)
                    for name in _LINE_NAMES
                },
            }

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(rows)))
    cerebro.addstrategy(Probe)
    return cerebro.run(runonce=runonce, preload=True)[0].result


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
@pytest.mark.parametrize(
    "de_marker_period,ma_length", [(3, 2), (14, 12)], ids=["small", "defaults"]
)
def test_first_values_match_formula_without_losing_prenext_bars(
    runonce, de_marker_period, ma_length
):
    rows = _rows(80)
    expected = _reference(rows, de_marker_period, ma_length)
    result = _run_once_or_next(rows, de_marker_period, ma_length, runonce)
    first = de_marker_period + ma_length - 1

    assert result["minperiod"] == de_marker_period + ma_length
    assert result["callback_lengths"][0] == result["minperiod"]
    for name in _LINE_NAMES:
        assert next(
            index for index, value in enumerate(result["lines"][name])
            if math.isfinite(value)
        ) == first, name
    _assert_lines(result["lines"], expected)


def test_missing_ohlc_recovers_after_its_rolling_windows_expire():
    rows = _rows(80)
    for name in ("high", "low"):
        rows[9][name] = math.nan
    rows[17]["volume"] = math.nan
    expected = _reference(rows, 3, 2)

    for runonce in (False, True):
        result = _run_once_or_next(rows, 3, 2, runonce)
        _assert_lines(result["lines"], expected)
        assert math.isfinite(result["lines"]["value"][-1])
        assert math.isfinite(result["lines"]["color_zone"][-1])


def _bar_at(data, ago):
    return {
        name: float(getattr(data, name)[-ago])
        for name in ("open", "high", "low", "close", "volume", "openinterest")
    }


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_unequal_feed_clock_does_not_sample_slow_bar_more_than_once(runonce):
    slow_rows = _rows(40)
    fast_rows = _rows(120)

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.XDeMarkerHistogramVolDirectIndicator(
                self.datas[1], de_marker_period=3, ma_length=2
            )
            self.clock_observations = []

        def next(self):
            self.clock_observations.append((len(self.data0), len(self.data1)))

        def stop(self):
            self.result = {
                "lines": {
                    name: list(getattr(self.indicator.lines, name).array)
                    for name in _LINE_NAMES
                },
                "clock_observations": list(self.clock_observations),
            }

    cerebro = bt.Cerebro(runonce=runonce, preload=runonce, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(fast_rows)))
    cerebro.adddata(
        bt.feeds.PandasData(dataname=_frame(slow_rows, day_step=3))
    )
    cerebro.addstrategy(Probe)
    result = cerebro.run(runonce=runonce, preload=runonce)[0].result

    repeated = {}
    for fast_length, slow_length in result["clock_observations"]:
        repeated.setdefault(slow_length, set()).add(fast_length)
    if not runonce:
        assert any(len(fast_lengths) > 1 for fast_lengths in repeated.values())
    _assert_lines(result["lines"], _reference(slow_rows, 3, 2))


def _run_replay():
    daily = _rows(36)
    ticks = []
    dates = []
    for day, row in enumerate(daily):
        middle = (row["open"] + row["close"]) / 2.0
        ticks.extend(
            (
                {
                    "open": row["open"],
                    "high": row["open"] + 0.1,
                    "low": row["open"] - 0.1,
                    "close": row["open"],
                    "volume": 2.0,
                    "openinterest": row["openinterest"],
                },
                {
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": middle,
                    "volume": 3.0,
                    "openinterest": row["openinterest"],
                },
                {
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "volume": 5.0,
                    "openinterest": row["openinterest"],
                },
            )
        )
        dates.extend(
            dt.datetime(2025, 1, 1) + dt.timedelta(days=day, hours=hour + 9)
            for hour in range(3)
        )

    class Probe(bt.Strategy):
        def __init__(self):
            self.replay = self.datas[1]
            self.indicator = bt.indicators.XDeMarkerHistogramVolDirectIndicator(
                self.replay, de_marker_period=3, ma_length=2
            )
            self.observations = []

        def next(self):
            count = len(self.replay)
            if not count:
                return
            bars = [
                _bar_at(self.replay, ago)
                for ago in range(count - 1, -1, -1)
            ]
            self.observations.append(
                {
                    "fast_length": len(self.data0),
                    "replay_length": count,
                    "current": tuple(bars[-1][name] for name in ("high", "low", "close", "volume")),
                    "bars": bars,
                    "value": float(self.indicator.value[0]),
                    "color_zone": float(self.indicator.color_zone[0]),
                    "color_direct": float(self.indicator.color_direct[0]),
                }
            )

        def stop(self):
            self.result = list(self.observations)

    fast_frame = _frame(ticks, start=dt.datetime(2025, 1, 1, 9, 0))
    cerebro = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    fast = bt.feeds.PandasData(
        dataname=fast_frame,
        timeframe=bt.TimeFrame.Minutes,
        compression=60,
    )
    replay_source = bt.feeds.PandasData(
        dataname=fast_frame.copy(),
        timeframe=bt.TimeFrame.Minutes,
        compression=60,
    )
    cerebro.adddata(fast, name="hourly-clock")
    cerebro.replaydata(
        replay_source,
        name="daily-replay",
        timeframe=bt.TimeFrame.Days,
        compression=1,
    )
    cerebro.addstrategy(Probe)
    return cerebro.run(runonce=False, preload=False)[0].result


def test_replay_revisions_replace_the_current_bar_sample():
    observations = _run_replay()
    grouped = {}
    for item in observations:
        grouped.setdefault(item["replay_length"], []).append(item)

    assert any(
        len({item["current"] for item in updates}) > 1
        for updates in grouped.values()
    )
    for item in observations:
        expected = _reference(item["bars"], 3, 2)
        index = item["replay_length"] - 1
        for name in ("value", "color_zone", "color_direct"):
            want = expected[name][index]
            got = item[name]
            if math.isnan(want):
                assert math.isnan(got), (item["replay_length"], name)
            else:
                assert got == pytest.approx(want, rel=1e-12, abs=1e-12), (
                    item["replay_length"], name
                )


def test_failed_final_replay_revision_preserves_last_success_for_next_bar():
    daily = _rows(24)
    fail_bar_index = 7
    fail_length = fail_bar_index + 1
    ticks = []
    dates = []
    for day, row in enumerate(daily):
        middle = (row["open"] + row["close"]) / 2.0
        ticks.extend(
            (
                {
                    **row,
                    "high": row["open"] + 0.1,
                    "low": row["open"] - 0.1,
                    "close": row["open"],
                    "volume": 2.0,
                },
                {**row, "close": middle, "volume": 3.0},
                {**row, "volume": 5.0},
            )
        )
        dates.extend(
            dt.datetime(2025, 2, 1) + dt.timedelta(days=day, hours=hour + 9)
            for hour in range(3)
        )

    failure = RuntimeError("synthetic final replay revision failure")

    class FailingRevisionIndicator(
        bt.indicators.XDeMarkerHistogramVolDirectIndicator
    ):
        def __init__(self):
            self.failure = failure
            self.failure_seen = False
            self.calls_at_fail_length = 0
            super().__init__()

        def _bar_volume(self):
            if len(self.data) == fail_length:
                self.calls_at_fail_length += 1
                if not self.failure_seen and self.calls_at_fail_length == 2:
                    self.failure_seen = True
                    raise self.failure
            return super()._bar_volume()

    class Probe(bt.Strategy):
        def __init__(self):
            self.replay = self.datas[1]
            self.indicator = FailingRevisionIndicator(
                self.replay, de_marker_period=3, ma_length=2
            )
            self.successful_rows = {}
            self.successful_outputs = {}
            self.failures = []
            self.recovered = []

        def _next(self):
            try:
                return super()._next()
            except RuntimeError as exc:
                if exc is not self.indicator.failure:
                    raise
                self.failures.append(
                    {
                        "exception": exc,
                        "length": len(self.replay),
                        "outputs": {
                            name: float(getattr(self.indicator.lines, name)[0])
                            for name in _LINE_NAMES
                        },
                    }
                )

        def next(self):
            count = len(self.replay)
            if not count:
                return
            bars = [
                _bar_at(self.replay, ago)
                for ago in range(count - 1, -1, -1)
            ]
            self.successful_rows[count] = bars[-1]
            outputs = {
                name: float(getattr(self.indicator.lines, name)[0])
                for name in _LINE_NAMES
            }
            self.successful_outputs[count] = outputs

            if count > fail_length:
                bars[fail_bar_index] = self.successful_rows[fail_length]
                expected = _reference(bars, 3, 2)
                index = count - 1
                self.recovered.append(
                    {
                        "length": count,
                        "actual": outputs,
                        "expected": {
                            name: expected[name][index]
                            for name in _LINE_NAMES
                        },
                    }
                )

        def stop(self):
            self.result = {
                "failed": self.indicator.failure_seen,
                "failures": list(self.failures),
                "successful_rows": dict(self.successful_rows),
                "successful_outputs": dict(self.successful_outputs),
                "recovered": list(self.recovered),
            }

    frame = _frame(
        ticks,
        start=dt.datetime(2025, 2, 1, 9, 0),
    )
    cerebro = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    source = bt.feeds.PandasData(
        dataname=frame,
        timeframe=bt.TimeFrame.Minutes,
        compression=60,
    )
    replay_source = bt.feeds.PandasData(
        dataname=frame.copy(),
        timeframe=bt.TimeFrame.Minutes,
        compression=60,
    )
    cerebro.adddata(source, name="hourly-clock")
    cerebro.replaydata(
        replay_source,
        name="daily-replay",
        timeframe=bt.TimeFrame.Days,
        compression=1,
    )
    cerebro.addstrategy(Probe)
    result = cerebro.run(runonce=False, preload=False)[0].result

    assert result["failed"]
    assert len(result["failures"]) == 1
    failed = result["failures"][0]
    assert failed["exception"] is failure
    assert failed["length"] == fail_length
    assert failed["outputs"] == result["successful_outputs"][fail_length]
    assert result["successful_rows"][fail_length]["volume"] == pytest.approx(3.0)
    assert result["recovered"]
    first_next_bar = result["recovered"][0]
    assert first_next_bar["length"] == fail_length + 1
    for name in _LINE_NAMES:
        got = first_next_bar["actual"][name]
        want = first_next_bar["expected"][name]
        if math.isnan(want):
            assert math.isnan(got), name
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12), name


class _FailFirstStringConversion:
    def __init__(self):
        self.failed = False

    def __str__(self):
        if not self.failed:
            self.failed = True
            raise RuntimeError("synthetic one-shot configuration read failure")
        return "MODE_SMA_"


def test_retried_exception_does_not_commit_a_partial_current_bar():
    rows = _rows(50)
    flaky_method = _FailFirstStringConversion()

    class RetryIndicator(bt.indicators.XDeMarkerHistogramVolDirectIndicator):
        def __init__(self):
            self.retry_count = 0
            super().__init__()

        def next(self):
            try:
                return super().next()
            except RuntimeError as exc:
                if str(exc) != "synthetic one-shot configuration read failure":
                    raise
                self.retry_count += 1
                return super().next()

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = RetryIndicator(
                self.data,
                de_marker_period=3,
                ma_length=2,
                ma_method=flaky_method,
            )

        def stop(self):
            self.result = {
                "retry_count": self.indicator.retry_count,
                "lines": {
                    name: list(getattr(self.indicator.lines, name).array)
                    for name in _LINE_NAMES
                },
            }

    cerebro = bt.Cerebro(runonce=False, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(rows)))
    cerebro.addstrategy(Probe)
    result = cerebro.run(runonce=False, preload=True)[0].result

    assert result["retry_count"] == 1
    assert flaky_method.failed
    _assert_lines(result["lines"], _reference(rows, 3, 2))


def test_failed_midwrite_replay_revision_rolls_back_value_and_keeps_next_color_direct():
    """Independent-review regression: failure after writing ``value[0]`` on a
    same-bar replay revision must restore ``value[0]`` so the next bar's
    ``color_direct`` compares against the last successful revision (0.0) rather
    than the aborted higher revision (which would flip it to 1.0).
    """
    daily = _rows(16)
    fail_bar_index = 7
    fail_length = fail_bar_index + 1

    # Construct replay ticks so that:
    # - Revision 1 of bar `fail_bar_index` commits a low value `v1`.
    # - Revision 2 (final tick) of bar `fail_bar_index` has a much higher
    #   high/volume (producing `v2 >> v1`) and fails AFTER `lines.value[0]` is
    #   written while writing `lines.color_zone[0]`.
    # - The next bar (`fail_bar_index + 1`) produces `v_next` with `v1 < v_next < v2`,
    #   so reference `color_direct` is 0.0 (up vs v1), whereas an unrolled-back
    #   `lines.value[0] == v2` would corrupt `color_direct` to 1.0!
    ticks = []
    for day, row in enumerate(daily):
        if day == fail_bar_index:
            ticks.extend(
                (
                    {
                        **row,
                        "high": row["open"] - 2.0,
                        "low": row["open"] - 8.0,
                        "close": row["open"] - 6.0,
                        "volume": 20.0,
                    },
                    {
                        **row,
                        "high": row["open"] + 40.0,
                        "low": row["open"] - 8.0,
                        "close": row["open"] + 38.0,
                        "volume": 200.0,
                    },
                )
            )
        elif day == fail_bar_index + 1:
            ticks.extend(
                (
                    {
                        **row,
                        "high": row["open"] + 30.0,
                        "low": row["open"] + 2.0,
                        "close": row["open"] + 28.0,
                        "volume": 40.0,
                    },
                    {
                        **row,
                        "high": row["open"] + 30.0,
                        "low": row["open"] + 2.0,
                        "close": row["open"] + 28.0,
                        "volume": 40.0,
                    },
                )
            )
        else:
            ticks.extend(
                (
                    {**row, "volume": 10.0},
                    {**row, "volume": 10.0},
                )
            )

    dates = [
        dt.datetime(2025, 3, 1) + dt.timedelta(days=day, hours=9 + tick)
        for day in range(len(daily))
        for tick in range(2)
    ]
    frame = pd.DataFrame(ticks, index=dates)

    write_failure = RuntimeError("synthetic color_zone write failure")

    class _FailingZoneBinding:
        def __init__(self, value_line):
            self._is_datetime_line = False
            self._value_line = value_line
            self.arm = False
            self.failed = False
            self.aborted_value_seen = None

        def updateminperiod(self, minperiod):
            pass

        def __setitem__(self, idx, value):
            if self.arm:
                self.arm = False
                self.failed = True
                self.aborted_value_seen = float(self._value_line[0])
                raise write_failure

    class Probe(bt.Strategy):
        def __init__(self):
            self.replay = self.datas[1]
            self.indicator = bt.indicators.XDeMarkerHistogramVolDirectIndicator(
                self.replay, de_marker_period=3, ma_length=2
            )
            self._zone_binding = _FailingZoneBinding(self.indicator.lines.value)
            self.indicator.lines.color_zone.addbinding(self._zone_binding)
            self.calls_at_fail = 0
            self.successful_rows = {}
            self.successful_outputs = {}
            self.failure_outputs = None
            self.next_bar_check = None

        def _next(self):
            if len(self.replay) == fail_length:
                self.calls_at_fail += 1
                if self.calls_at_fail == 2:
                    self._zone_binding.arm = True
            try:
                return super()._next()
            except RuntimeError as exc:
                if exc is not write_failure:
                    raise
                self.failure_outputs = {
                    name: float(getattr(self.indicator.lines, name)[0])
                    for name in _LINE_NAMES
                }

        def next(self):
            count = len(self.replay)
            if not count:
                return
            bars = [_bar_at(self.replay, ago) for ago in range(count - 1, -1, -1)]
            outputs = {
                name: float(getattr(self.indicator.lines, name)[0])
                for name in _LINE_NAMES
            }
            self.successful_rows[count] = bars[-1]
            self.successful_outputs[count] = outputs

            if count == fail_length + 1 and self.next_bar_check is None:
                bars[fail_bar_index] = self.successful_rows[fail_length]
                expected = _reference(bars, 3, 2)
                self.next_bar_check = {
                    "actual": outputs,
                    "expected": {name: expected[name][count - 1] for name in _LINE_NAMES},
                    "prev_value_committed": self.successful_outputs[fail_length]["value"],
                }

    cerebro = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    cerebro.adddata(
        bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes, compression=60),
        name="hourly",
    )
    cerebro.replaydata(
        bt.feeds.PandasData(
            dataname=frame.copy(), timeframe=bt.TimeFrame.Minutes, compression=60
        ),
        name="daily-replay",
        timeframe=bt.TimeFrame.Days,
        compression=1,
    )
    cerebro.addstrategy(Probe)
    strategy = cerebro.run(runonce=False, preload=False)[0]

    assert strategy._zone_binding.failed
    assert strategy.failure_outputs == strategy.successful_outputs[fail_length]
    assert strategy.next_bar_check is not None
    # Prove the exact HOLD trigger condition: committed v1 < next bar value <
    # aborted revision v2, so an unrolled-back value[0] would have flipped
    # color_direct from 0.0 to 1.0.
    v1 = strategy.next_bar_check["prev_value_committed"]
    v_next = strategy.next_bar_check["actual"]["value"]
    v2_aborted = strategy._zone_binding.aborted_value_seen
    assert v1 < v_next < v2_aborted
    assert strategy.next_bar_check["expected"]["color_direct"] == 0.0
    assert strategy.next_bar_check["actual"]["color_direct"] == 0.0
    for name in _LINE_NAMES:
        got = strategy.next_bar_check["actual"][name]
        want = strategy.next_bar_check["expected"][name]
        assert got == pytest.approx(want, rel=1e-12, abs=1e-12), name


def test_double_failure_during_output_rollback_keeps_original_exception_and_state():
    """If rolling back an earlier output slot also fails, keep the original
    exception authoritative while still restoring rolling state.
    """
    rows = _rows(20)
    orig_err = RuntimeError("primary color_zone failure")
    rollback_err = RuntimeError("secondary value rollback failure")

    class _FailOnRollbackBinding:
        def __init__(self):
            self._is_datetime_line = False
            self.writes = 0
            self.fail_on_second_write = False

        def updateminperiod(self, minperiod):
            pass

        def __setitem__(self, idx, value):
            self.writes += 1
            if self.fail_on_second_write and self.writes == 2:
                raise rollback_err

    class _FailOnceBinding:
        def __init__(self):
            self._is_datetime_line = False
            self.arm = False

        def updateminperiod(self, minperiod):
            pass

        def __setitem__(self, idx, value):
            if self.arm:
                self.arm = False
                raise orig_err

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.XDeMarkerHistogramVolDirectIndicator(
                self.data, de_marker_period=3, ma_length=2
            )
            self.val_binding = _FailOnRollbackBinding()
            self.zone_binding = _FailOnceBinding()
            self.indicator.lines.value.addbinding(self.val_binding)
            self.indicator.lines.color_zone.addbinding(self.zone_binding)
            self.caught = None
            self.state_before = None
            self.state_after_fail = None

        def _next(self):
            if len(self.data) == 8:
                self.state_before = self.indicator._state_snapshot()
                self.val_binding.writes = 0
                self.val_binding.fail_on_second_write = True
                self.zone_binding.arm = True
            try:
                return super()._next()
            except RuntimeError as exc:
                self.caught = exc
                self.state_after_fail = self.indicator._state_snapshot()
                self.val_binding.fail_on_second_write = False

    cerebro = bt.Cerebro(runonce=False, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(rows)))
    cerebro.addstrategy(Probe)
    strategy = cerebro.run(runonce=False, preload=True)[0]

    assert strategy.caught is orig_err
    assert strategy.state_after_fail == strategy.state_before


def test_exactbars_bounded_buffer_matches_reference_formula():
    rows = _rows(40)
    expected = _reference(rows, 3, 2)

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.XDeMarkerHistogramVolDirectIndicator(
                self.data, de_marker_period=3, ma_length=2
            )
            self.captured = {name: [] for name in _LINE_NAMES}
            self.lengths = []

        def next(self):
            self.lengths.append(len(self.data))
            for name in _LINE_NAMES:
                self.captured[name].append(float(getattr(self.indicator.lines, name)[0]))

    cerebro = bt.Cerebro(runonce=False, preload=False, exactbars=1, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(rows)))
    cerebro.addstrategy(Probe)
    strategy = cerebro.run()[0]

    assert strategy.lengths == list(range(5, len(rows) + 1))
    for name in _LINE_NAMES:
        for idx, got in zip(strategy.lengths, strategy.captured[name]):
            want = expected[name][idx - 1]
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12), (name, idx)
