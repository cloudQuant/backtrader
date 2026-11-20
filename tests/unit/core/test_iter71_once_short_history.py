"""Runonce phases must stay within the available input history."""

import csv
import math
from datetime import date, timedelta

import pytest

import backtrader as bt
from tests.test_utils.alpha101_native_harness import (
    actual_matrix,
    make_positive_fixture,
    run_native_batch,
)


@pytest.mark.parametrize(
    "length, expected",
    [
        (0, []),
        (2, [("pre", 0, 2)]),
        (4, [("pre", 0, 3), ("start", 3, 4)]),
        (5, [("pre", 0, 3), ("start", 3, 4), ("once", 4, 5)]),
    ],
)
def test_once_phases_respect_buffer_length(tmp_path, length, expected):
    calls = []

    class Indicator(bt.Indicator):
        lines = ("value",)

        def __init__(self):
            self.addminperiod(4)

        def preonce(self, start, end):
            if start < end:
                calls.append(("pre", start, end))

        def oncestart(self, start, end):
            if start < end:
                calls.append(("start", start, end))

        def once(self, start, end):
            if start < end:
                calls.append(("once", start, end))

    class Strategy(bt.Strategy):
        def __init__(self):
            self.indicator = Indicator(self.data)

    path = tmp_path / "data.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Date", "Open", "High", "Low", "Close", "Volume", "OpenInterest"])
        for i in range(length):
            writer.writerow(
                [(date(2025, 1, 1) + timedelta(days=i)).isoformat(), 10, 10, 10, 10, 1, 0]
            )

    cerebro = bt.Cerebro(stdstats=False, runonce=True)
    cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=str(path)))
    cerebro.addstrategy(Strategy)
    cerebro.run()

    assert calls == expected


@pytest.mark.parametrize("runonce", [False, True])
def test_alpha024_handles_history_shorter_than_lookback(runonce):
    frames = {name: frame.iloc[:150].copy() for name, frame in make_positive_fixture().items()}

    strategy = run_native_batch(frames, (24,), runonce=runonce)

    assert strategy.factor_instances["alpha24"]._minperiod == 200
    matrix = actual_matrix(strategy, 24, tuple(frames), tuple(next(iter(frames.values())).index))
    assert len(matrix) == 150
    assert all(math.isnan(value) for row in matrix for value in row)
