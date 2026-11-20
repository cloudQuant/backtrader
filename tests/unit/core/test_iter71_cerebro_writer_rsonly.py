"""Regression coverage for Cerebro writer scheduling and mixed data clocks."""

import csv
import io

import pandas as pd
import pytest

import backtrader as bt


_RUN_MODES = ((False, False), (False, True), (True, False), (True, True))


def _frame(start, closes):
    index = pd.date_range(start, periods=len(closes), freq="D")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=index,
    )


def _run_writer_case(oldsync, runonce, tags, stop_tag=None, stop_date=None):
    closes = [10.0, 11.0, 12.0]
    dates = ["2020-01-01", "2020-01-02", "2020-01-03"]
    events = []
    calls = dict.fromkeys(tags, 0)
    frame = _frame(dates[0], closes)
    data = bt.feeds.PandasData(dataname=frame)

    class RecordingStrategy(bt.Strategy):
        params = (("tag", ""),)

        def next(self):
            calls[self.p.tag] += 1
            current_date = self.data.datetime.date(0).isoformat()
            events.append(("strategy", self.p.tag, calls[self.p.tag], current_date))
            if self.p.tag == stop_tag and current_date == stop_date:
                self.cerebro.runstop()

    class RecordingWriter(bt.WriterStringIO):
        def next(self):
            current_date = data.datetime.date(0).isoformat()
            snapshot = tuple((tag, calls[tag]) for tag in tags)
            events.append(("writer", snapshot, current_date))
            super().next()

    cerebro = bt.Cerebro(oldsync=oldsync, runonce=runonce, stdstats=False)
    cerebro.adddata(data, name="base")
    cerebro.addwriter(RecordingWriter, csv=True)
    for tag in tags:
        cerebro.addstrategy(RecordingStrategy, tag=tag)

    cerebro.run()
    writer = cerebro.runwriters[0]
    rows = [
        row
        for row in csv.reader(io.StringIO(writer.getvalue()))
        if row and row[0].isdigit()
    ]
    return events, rows


@pytest.mark.parametrize(("oldsync", "runonce"), _RUN_MODES)
@pytest.mark.parametrize("tags", [("A",), ("A", "B")])
def test_multi_strategy_writer_runs_once_after_all_callbacks(oldsync, runonce, tags):
    events, rows = _run_writer_case(oldsync, runonce, tags)

    expected = []
    for bar_index, current_date in enumerate(
        ("2020-01-01", "2020-01-02", "2020-01-03"), start=1
    ):
        for tag in tags:
            expected.append(("strategy", tag, bar_index, current_date))
        expected.append(
            ("writer", tuple((tag, bar_index) for tag in tags), current_date)
        )

    assert events == expected
    assert len(rows) == len(expected) // (len(tags) + 1)
    assert [int(row[0]) for row in rows] == [0, 1, 2]
    assert [row[3].split()[0] for row in rows] == [
        "2020-01-01",
        "2020-01-02",
        "2020-01-03",
    ]


@pytest.mark.parametrize(("oldsync", "runonce"), _RUN_MODES)
def test_writer_stop_keeps_partial_strategy_cycle_unwritten(oldsync, runonce):
    events, rows = _run_writer_case(
        oldsync,
        runonce,
        ("A", "B"),
        stop_tag="A",
        stop_date="2020-01-02",
    )

    assert events == [
        ("strategy", "A", 1, "2020-01-01"),
        ("strategy", "B", 1, "2020-01-01"),
        ("writer", (("A", 1), ("B", 1)), "2020-01-01"),
        ("strategy", "A", 2, "2020-01-02"),
    ]
    assert len(rows) == 1
    assert rows[0][3].startswith("2020-01-01")


@pytest.mark.parametrize(("oldsync", "runonce"), _RUN_MODES)
@pytest.mark.parametrize(("tags", "stop_tag"), [(('A',), 'A'), (('A', 'B'), 'B')])
def test_writer_stop_on_last_strategy_does_not_write_trigger_bar(
    oldsync, runonce, tags, stop_tag
):
    events, rows = _run_writer_case(
        oldsync,
        runonce,
        tags,
        stop_tag=stop_tag,
        stop_date="2020-01-02",
    )

    expected = [
        ("strategy", tag, 1, "2020-01-01")
        for tag in tags
    ]
    expected.append(
        ("writer", tuple((tag, 1) for tag in tags), "2020-01-01")
    )
    expected.extend(
        ("strategy", tag, 2, "2020-01-02")
        for tag in tags
    )

    assert events == expected
    assert len(rows) == 1
    assert rows[0][3].startswith("2020-01-01")


def test_mixed_resample_replay_clock_keeps_replay_as_master_after_raw_ends():
    raw_dates = pd.date_range("2020-01-03", periods=8, freq="D")
    transformed_dates = pd.date_range("2020-01-01", periods=12, freq="D")
    raw_values = [200.0 + index for index in range(len(raw_dates))]
    transformed_values = [100.0 + index for index in range(len(transformed_dates))]
    raw = _frame(raw_dates[0], raw_values)
    transformed = _frame(transformed_dates[0], transformed_values)

    class ClockStrategy(bt.Strategy):
        def __init__(self):
            self.clock_rows = []

        def next(self):
            row = []
            for data in self.datas:
                current = data.datetime.date(0).isoformat() if len(data) else None
                row.append((len(data), current))
            self.clock_rows.append(tuple(row))

    cerebro = bt.Cerebro(oldsync=False, runonce=False, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=raw), name="raw")
    resampled = cerebro.resampledata(
        bt.feeds.PandasData(dataname=transformed),
        name="resampled",
        timeframe=bt.TimeFrame.Weeks,
        compression=1,
    )
    replayed = cerebro.replaydata(
        bt.feeds.PandasData(dataname=transformed),
        name="replayed",
        timeframe=bt.TimeFrame.Weeks,
        compression=1,
    )
    assert resampled.resampling and not resampled.replaying
    assert replayed.replaying
    cerebro.addstrategy(ClockStrategy)

    strategy = cerebro.run()[0]

    expected = [
        ((3, "2020-01-05"), (1, "2020-01-05"), (1, "2020-01-05")),
        ((4, "2020-01-06"), (1, "2020-01-05"), (2, "2020-01-06")),
        ((5, "2020-01-07"), (1, "2020-01-05"), (2, "2020-01-07")),
        ((6, "2020-01-08"), (1, "2020-01-05"), (2, "2020-01-08")),
        ((7, "2020-01-09"), (1, "2020-01-05"), (2, "2020-01-09")),
        ((8, "2020-01-10"), (1, "2020-01-05"), (2, "2020-01-10")),
        ((8, "2020-01-10"), (1, "2020-01-05"), (2, "2020-01-11")),
        ((8, "2020-01-10"), (1, "2020-01-05"), (2, "2020-01-12")),
        ((8, "2020-01-10"), (2, "2020-01-12"), (2, "2020-01-12")),
    ]
    assert strategy.clock_rows == expected
