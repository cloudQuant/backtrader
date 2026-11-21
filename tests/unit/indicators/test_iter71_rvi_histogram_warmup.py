"""RVI histogram warms its rolling state before the public minimum period."""

import datetime as dt
import math

import backtrader as bt
import pytest
from backtrader.indicators.contrib import rvi_histogram_indicator as rvi_module


class _OHLC(bt.feed.DataBase):
    params = (("rows", ()), ("day_step", 1), ("dates", ()))

    def __init__(self):
        super().__init__()
        self._row = 0

    def _load(self):
        if self._row >= len(self.p.rows):
            return False
        opening, high, low, close = self.p.rows[self._row]
        moment = (self.p.dates[self._row] if self.p.dates
                  else dt.datetime(2020, 1, 1) + dt.timedelta(days=self._row * self.p.day_step))
        self.lines.datetime[0] = bt.date2num(moment)
        self.lines.open[0] = opening
        self.lines.high[0] = high
        self.lines.low[0] = low
        self.lines.close[0] = close
        self.lines.volume[0] = 1.0
        self.lines.openinterest[0] = 0.0
        self._row += 1
        return True


def _rows(size):
    rows = []
    for index in range(size):
        opening = 100.0 + 0.17 * index + math.sin(index * 0.37)
        close = opening + 0.6 * math.sin(index * 0.61) + 0.2 * math.cos(index * 0.23)
        rows.append((opening, max(opening, close) + 0.7,
                     min(opening, close) - 0.4, close))
    return rows


def _reference(rows, period):
    co = [close - opening for opening, _high, _low, close in rows]
    hl = [high - low for _opening, high, low, _close in rows]
    def weighted(values, index):
        return (values[index] + 2.0 * values[index - 1]
                + 2.0 * values[index - 2] + values[index - 3]) / 6.0
    def main(index):
        start = index - period + 1
        num = sum(weighted(co, pos) for pos in range(start, index + 1)) / period
        den = sum(weighted(hl, pos) for pos in range(start, index + 1)) / period
        return num / den if abs(den) > 1e-12 else 0.0
    result = []
    for index in range(period + 5, len(rows)):
        current = main(index)
        signal = (current + 2.0 * main(index - 1) + 2.0 * main(index - 2)
                  + main(index - 3)) / 6.0
        color = 0.0 if current > 0.3 else 2.0 if current < -0.3 else 1.0
        result.append((current, signal, 0.0, color))
    return result


def _run(rows, period, runonce, indicator_type=bt.indicators.RVIHistogramIndicator):
    class Probe(bt.Strategy):
        def __init__(self):
            self.rvi = indicator_type(self.data, rvi_period=period)
        def stop(self):
            self.output = tuple(list(line.array) for line in self.rvi.lines)
            self.minperiod = self.rvi._minperiod
    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(_OHLC(rows=rows))
    cerebro.addstrategy(Probe)
    return cerebro.run(runonce=runonce, preload=True)[0]


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
@pytest.mark.parametrize("missing_index,field", [(4, 0), (4, 1), (12, 0), (12, 1)])
def test_missing_ohlc_preserves_existing_denominator_projection(runonce, missing_index, field):
    rows = _rows(40)
    row = list(rows[missing_index])
    row[field] = float("nan")
    rows[missing_index] = tuple(row)
    result = _run(rows, 3, runonce)
    expected = _reference(rows, 3)
    for line_index, actual in enumerate(result.output):
        assert actual[8:] == pytest.approx(
            [values[line_index] for values in expected], rel=1e-12, abs=1e-12, nan_ok=True
        )


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_prenext_update_exception_propagates_and_retry_does_not_duplicate(monkeypatch, runonce):
    error = RuntimeError("synthetic rolling failure")
    original = rvi_module._RollingWeightedAverage4.update
    attempts = []

    def fail_after_update_once(self, value):
        result = original(self, value)
        if not attempts:
            attempts.append(error)
            raise error
        return result

    monkeypatch.setattr(rvi_module._RollingWeightedAverage4, "update", fail_after_update_once)

    class RetryRvi(bt.indicators.RVIHistogramIndicator):
        def prenext(self):
            try:
                super().prenext()
            except RuntimeError as exc:
                assert exc is error
                super().prenext()

    rows = _rows(30)
    result = _run(rows, 3, runonce, RetryRvi)
    assert attempts == [error]
    expected = _reference(rows, 3)
    for line_index, actual in enumerate(result.output):
        assert actual[8:] == pytest.approx([values[line_index] for values in expected], rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_next_update_exception_restores_state_and_preserves_exception(monkeypatch, runonce):
    error = RuntimeError("synthetic published-bar failure")
    original = rvi_module._RollingWeightedAverage4.update
    calls = 0
    holder = {}
    before = []

    def fail_after_update(self, value):
        nonlocal calls
        calls += 1
        if calls == 25:  # first update of bar 9, the first published bar
            before.extend(tuple(average.values) for average in holder["rvi"]._rolling_averages)
            original(self, value)
            raise error
        return original(self, value)

    monkeypatch.setattr(rvi_module._RollingWeightedAverage4, "update", fail_after_update)

    class Probe(bt.Strategy):
        def __init__(self):
            holder["rvi"] = bt.indicators.RVIHistogramIndicator(self.data, rvi_period=3)

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(_OHLC(rows=_rows(30)))
    cerebro.addstrategy(Probe)
    with pytest.raises(RuntimeError) as exc:
        cerebro.run(runonce=runonce, preload=True)
    assert exc.value is error
    assert before == [tuple(average.values) for average in holder["rvi"]._rolling_averages]


@pytest.mark.parametrize("period", [3, 14])
@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_first_published_value_has_full_prior_input_history(period, runonce):
    rows = _rows(80)
    result = _run(rows, period, runonce)
    assert result.minperiod == period + 6
    expected = _reference(rows, period)
    first = period + 5
    assert abs(expected[0][0]) > 1e-6 and abs(expected[0][1]) > 1e-6
    for line_index, actual in enumerate(result.output):
        assert all(math.isnan(value) for value in actual[:first])
        assert actual[first:] == pytest.approx([values[line_index] for values in expected], rel=1e-12, abs=1e-12)


def test_unequal_data_clocks_do_not_resample_one_signal_bar():
    class Probe(bt.Strategy):
        def __init__(self):
            self.rvi = bt.indicators.RVIHistogramIndicator(self.datas[1], rvi_period=3)
        def stop(self):
            self.output = tuple(list(line.array) for line in self.rvi.lines)
            self.minperiod = self.rvi._minperiod
    slow = _rows(70)
    cerebro = bt.Cerebro(runonce=False, preload=True, stdstats=False)
    cerebro.adddata(_OHLC(rows=_rows(210)))
    cerebro.adddata(_OHLC(rows=slow, day_step=3))
    cerebro.addstrategy(Probe)
    result = cerebro.run(runonce=False, preload=True)[0]
    assert result.minperiod == 9
    expected = _reference(slow, 3)
    for line_index, actual in enumerate(result.output):
        assert len(actual) == len(slow)
        assert all(math.isnan(value) for value in actual[:8])
        assert actual[8:] == pytest.approx([values[line_index] for values in expected], rel=1e-12, abs=1e-12)


def test_replay_updates_current_bar_without_double_sampling():
    class Probe(bt.Strategy):
        def __init__(self):
            self.rvi = bt.indicators.RVIHistogramIndicator(self.data, rvi_period=3)
        def stop(self):
            self.output = tuple(list(line.array) for line in self.rvi.lines)
            self.minperiod = self.rvi._minperiod
    ticks, dates, daily = [], [], []
    for day, (opening, high, low, close) in enumerate(_rows(40)):
        middle = (opening + close) / 2.0
        day_rows = [(opening, opening + 0.1, opening - 0.1, opening),
                    (opening, high, low, middle),
                    (middle, max(middle, close) + 0.1, min(middle, close) - 0.1, close)]
        ticks.extend(day_rows)
        dates.extend(dt.datetime(2020, 1, 1, 9, 0) + dt.timedelta(days=day, hours=hour)
                     for hour in range(3))
        daily.append((day_rows[0][0], max(row[1] for row in day_rows),
                      min(row[2] for row in day_rows), day_rows[-1][3]))
    cerebro = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    cerebro.replaydata(_OHLC(rows=ticks, dates=dates, timeframe=bt.TimeFrame.Minutes,
                            compression=60), timeframe=bt.TimeFrame.Days)
    cerebro.addstrategy(Probe)
    result = cerebro.run(runonce=False, preload=False)[0]
    assert result.minperiod == 9
    expected = _reference(daily, 3)
    for line_index, actual in enumerate(result.output):
        assert len(actual) == len(daily)
        assert all(math.isnan(value) for value in actual[:8])
        assert actual[8:] == pytest.approx([values[line_index] for values in expected], rel=1e-12, abs=1e-12)
