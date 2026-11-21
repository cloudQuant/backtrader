import math

import backtrader as bt
import pandas as pd
import pytest


def _frame(index, closes):
    return pd.DataFrame({"open": closes, "high": closes, "low": closes,
                         "close": closes, "volume": 1.0, "openinterest": 0.0}, index=index)


def _run(frame, *, runonce, replay=False, exactbars=0, retry=False):
    class RetryTimeLine(bt.indicators.TimeLine):
        def next(self):
            before = (self.day_close_price_list[:], self._bar_base_prices[:],
                      self._current_bar_length, self._reset_pending,
                      self.lines.day_avg_price[0])
            try:
                super().next()
            except ValueError:
                after = (self.day_close_price_list[:], self._bar_base_prices[:],
                         self._current_bar_length, self._reset_pending,
                         self.lines.day_avg_price[0])
                assert after[:-1] == before[:-1]
                assert after[-1] == before[-1] or (math.isnan(after[-1]) and math.isnan(before[-1]))
                super().next()

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = (RetryTimeLine if retry else bt.indicators.TimeLine)(self.data)
            self.rows = []

        def next(self):
            self.rows.append((len(self.data), self.data.datetime.datetime(0),
                              float(self.data.close[0]), float(self.ind.day_avg_price[0])))

    c = bt.Cerebro(stdstats=False, runonce=runonce, preload=not replay and not exactbars,
                   exactbars=exactbars)
    data = bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes)
    if replay:
        c.replaydata(data, timeframe=bt.TimeFrame.Minutes, compression=7)
    else:
        c.adddata(data)
    c.addstrategy(Probe)
    return c.run()[0].rows


def _reference(rows):
    # Each running bar contributes its latest close exactly once; 15:00 is
    # included in the outgoing session, after which the next bar starts afresh.
    committed = []
    pending = []
    last_len = None
    reset_seen = False
    expected = []
    for length, when, close, _ in rows:
        if length != last_len or reset_seen:
            committed = pending
        current = committed + [close]
        expected.append(sum(current) / len(current))
        pending = [] if (when.hour, when.minute) == (15, 0) else current
        reset_seen = (when.hour, when.minute) == (15, 0)
        last_len = length
    return expected


def _assert_reference(rows):
    for row, want in zip(rows, _reference(rows)):
        got = row[-1]
        if math.isnan(want):
            assert math.isnan(got)
        else:
            assert got == pytest.approx(want)


@pytest.mark.parametrize("runonce", [False, True])
def test_timeline_session_reset_and_missing_close(runonce):
    index = pd.to_datetime(["2024-01-02 14:58", "2024-01-02 14:59",
                            "2024-01-02 15:00", "2024-01-03 09:00",
                            "2024-01-03 09:01", "2024-01-03 15:00",
                            "2024-01-04 09:00"])
    closes = [2.0, 4.0, 6.0, 8.0, float("nan"), 12.0, 14.0]
    rows = _run(_frame(index, closes), runonce=runonce)
    assert len(rows) == len(closes)
    _assert_reference(rows)
    assert rows[2][-1] == 4.0
    assert rows[3][-1] == 8.0
    assert math.isnan(rows[5][-1])
    assert rows[6][-1] == 14.0


@pytest.mark.parametrize("exactbars", [0, 1])
def test_timeline_replay_replaces_unfinished_bar_close(exactbars):
    index = pd.date_range("2024-01-02 14:51", periods=14, freq="min")
    rows = _run(_frame(index, list(map(float, range(1, 15)))), runonce=False,
                replay=True, exactbars=exactbars)
    assert any(a[0] == b[0] for a, b in zip(rows, rows[1:]))
    assert any(row[1].hour == 15 and row[1].minute == 0 for row in rows)
    at_reset = next(i for i, row in enumerate(rows) if row[1].hour == 15 and row[1].minute == 0)
    assert rows[at_reset][0] == rows[at_reset + 1][0]
    assert rows[at_reset + 1][-1] == rows[at_reset + 1][2]
    _assert_reference(rows)


@pytest.mark.parametrize("runonce", [False, True])
def test_timeline_missing_reset_minute_preserves_existing_accumulation(runonce):
    index = pd.to_datetime(["2024-01-02 14:59", "2024-01-02 15:01", "2024-01-03 09:00"])
    rows = _run(_frame(index, [2.0, 4.0, 6.0]), runonce=runonce)
    assert [row[-1] for row in rows] == [2.0, 3.0, 4.0]


@pytest.mark.parametrize("failed_minute", [59, 0, 1])
def test_timeline_exception_retry_does_not_commit_partial_bar(monkeypatch, failed_minute):
    import importlib

    module = importlib.import_module("backtrader.indicators.contrib.time_line")
    original = module.num2date
    calls = {"remaining": 1}

    def fail_once(value):
        result = original(value)
        hour = 14 if failed_minute == 59 else 15
        if result.hour == hour and result.minute == failed_minute and calls["remaining"]:
            calls["remaining"] -= 1
            raise ValueError("injected clock conversion failure")
        return result

    index = pd.date_range("2024-01-02 14:51", periods=14, freq="min")
    frame = _frame(index, list(map(float, range(1, 15))))
    baseline = _run(frame, runonce=False, replay=True)
    monkeypatch.setattr(module, "num2date", fail_once)
    retried = _run(frame, runonce=False, replay=True, retry=True)
    assert calls["remaining"] == 0
    assert retried == baseline


def test_timeline_replay_recovers_when_unfinished_close_is_replaced():
    index = pd.date_range("2024-01-02 09:00", periods=9, freq="min")
    closes = [1.0, 2.0, float("nan"), 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    rows = _run(_frame(index, closes), runonce=False, replay=True)
    assert any(math.isnan(row[2]) for row in rows)
    _assert_reference(rows)
    assert math.isfinite(rows[-1][-1])
