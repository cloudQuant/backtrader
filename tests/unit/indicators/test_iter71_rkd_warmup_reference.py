"""Complete-window RKD warmup in real Cerebro execution modes."""

import datetime as dt
import math

import backtrader as bt
import pytest


class _OHLC(bt.feed.DataBase):
    params = (("rows", ()), ("step_days", 1))

    def __init__(self):
        super().__init__()
        self.index = 0

    def _load(self):
        if self.index == len(self.p.rows):
            return False
        opening, high, low, close = self.p.rows[self.index]
        self.datetime[0] = bt.date2num(
            dt.datetime(2020, 1, 1) + dt.timedelta(days=self.index * self.p.step_days)
        )
        self.open[0], self.high[0], self.low[0], self.close[0] = opening, high, low, close
        self.volume[0], self.openinterest[0] = 1.0, 0.0
        self.index += 1
        return True


def _rows(count):
    result = []
    for index in range(count):
        close = 100.0 + index * .07 + math.sin(index * .27) * 3.0
        opening = close + math.sin(index * .71) * 1.2
        result.append((opening, max(opening, close) + .8, min(opening, close) - .6, close))
    return result


def _reference(rows, period, m1, m2):
    rsv = [math.nan] * len(rows)
    k = [math.nan] * len(rows)
    d = [math.nan] * len(rows)
    for index in range(period - 1, len(rows)):
        # Most-recent-first ordering matches the existing high/low NaN behavior.
        window = list(reversed(rows[index - period + 1:index + 1]))
        high = max(row[1] for row in window)
        low = min(row[2] for row in window)
        rsv[index] = (rows[index][3] - low) / (high - low) * 100 if high != low else 0.0
    for index in range(period + m1 - 2, len(rows)):
        k[index] = sum(rsv[index - offset] for offset in range(m1)) / m1
    for index in range(period + m1 + m2 - 3, len(rows)):
        d[index] = sum(k[index - offset] for offset in range(m2)) / m2
    return rsv, k, d


def _run(rows, period, m1, m2, runonce, *, multifeed=False):
    class Probe(bt.Strategy):
        def __init__(self):
            self.rkd = bt.indicators.RKDIndicator(
                self.datas[1] if multifeed else self.data,
                kd_period=period, m1=m1, m2=m2,
            )
            self.first = None

        def next(self):
            if self.first is None:
                self.first = (len(self.rkd.data), self.rkd.k[0], self.rkd.d[0])

        def stop(self):
            self.output = tuple(list(line.array) for line in self.rkd.lines)
            self.period = self.rkd._minperiod

    engine = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    if multifeed:
        engine.adddata(_OHLC(rows=_rows(len(rows) * 3)))
    engine.adddata(_OHLC(rows=rows, step_days=3 if multifeed else 1))
    engine.addstrategy(Probe)
    return engine.run(runonce=runonce, preload=True)[0]


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
@pytest.mark.parametrize("period,m1,m2", [(30, 3, 6), (5, 3, 2), (4, 1, 1), (3, 5, 2)])
def test_complete_windows_and_minperiod_match_independent_reference(period, m1, m2, runonce):
    rows = _rows(100)
    result = _run(rows, period, m1, m2, runonce)
    assert result.period == period + m1 + m2 - 2
    assert result.first[0] == result.period
    assert all(math.isfinite(value) for value in result.first[1:])
    for actual, expected in zip(result.output, _reference(rows, period, m1, m2)):
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12, nan_ok=True)


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
@pytest.mark.parametrize("count", [29, 30, 32, 36, 37])
def test_short_histories_keep_intermediate_lines_and_first_complete_d(count, runonce):
    rows = _rows(count)
    result = _run(rows, 30, 3, 6, runonce)
    assert result.period == 37
    for actual, expected in zip(result.output, _reference(rows, 30, 3, 6)):
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12, nan_ok=True)
    assert (result.first is None) == (count < 37)


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
@pytest.mark.parametrize("missing_index,field", [(5, 3), (20, 1), (40, 2)])
def test_missing_inputs_preserve_existing_window_and_nan_semantics(missing_index, field, runonce):
    rows = _rows(75)
    row = list(rows[missing_index])
    row[field] = math.nan
    rows[missing_index] = tuple(row)
    result = _run(rows, 5, 3, 2, runonce)
    for actual, expected in zip(result.output, _reference(rows, 5, 3, 2)):
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12, nan_ok=True)


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_secondary_feed_uses_its_own_clock(runonce):
    rows = _rows(60)
    result = _run(rows, 5, 3, 2, runonce, multifeed=True)
    assert result.period == 8
    for actual, expected in zip(result.output, _reference(rows, 5, 3, 2)):
        assert len(actual) == len(rows)
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12, nan_ok=True)


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_flat_price_preserves_zero_denominator_result(runonce):
    rows = [(2.0, 2.0, 2.0, 2.0)] * 20
    result = _run(rows, 5, 3, 2, runonce)
    for actual, expected in zip(result.output, _reference(rows, 5, 3, 2)):
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12, nan_ok=True)
    assert all(line[-1] == 0.0 for line in result.output)


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_unsupported_zero_smoothing_still_raises(runonce):
    with pytest.raises(ZeroDivisionError):
        _run(_rows(40), 5, 0, 2, runonce)
