"""Secondary replay must not advance indicators while its future bar is withheld."""

import math

import pandas as pd
import pytest

import backtrader as bt


class _Identity(bt.Indicator):
    lines = ("value",)

    def next(self):
        self.lines.value[0] = self.data.close[0]


class _ReplayClockLengthMismatch(AssertionError):
    """The known replay defect, distinct from setup or unrelated failures."""


def _run(*, replay):
    days = pd.date_range("2020-01-01", periods=5, freq="D")
    primary_times = [
        day + pd.Timedelta(hours=9, minutes=minute)
        for day in days
        for minute in (0, 30, 60, 90)
    ]
    secondary_times = [day + pd.Timedelta(hours=9 + hour) for day in days for hour in (0, 1)]

    def frame(index, values):
        return pd.DataFrame(
            {"open": values, "high": values, "low": values, "close": values,
             "volume": [1.0] * len(values)},
            index=index,
        )

    class Capture(bt.Strategy):
        def __init__(self):
            self.identity = _Identity(self.datas[1])
            self.rows = []

        def prenext(self):
            self.next()

        def next(self):
            data = self.datas[1]
            data_value = float(data.close[0]) if len(data) else None
            value = float(self.identity[0]) if len(self.identity) else None
            delivered = bool(len(data) and data.datetime[0] == self.datas[0].datetime[0])
            self.rows.append(
                (len(self.datas[0]), len(data), len(self.identity), data_value, value, delivered)
            )

    cerebro = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(
        dataname=frame(primary_times, [200.0] * len(primary_times)),
        timeframe=bt.TimeFrame.Minutes,
        compression=30,
    ))
    secondary = bt.feeds.PandasData(
        dataname=frame(secondary_times, [100.0 + i for i in range(len(secondary_times))]),
        timeframe=bt.TimeFrame.Minutes,
        compression=60,
    )
    if replay:
        cerebro.replaydata(secondary, timeframe=bt.TimeFrame.Days)
    else:
        cerebro.adddata(secondary)
    cerebro.addstrategy(Capture)
    return cerebro.run()[0].rows


def _assert_visible_values(rows):
    delivered_count = 0
    for _, data_len, indicator_len, data_value, value, delivered in rows:
        if delivered:
            delivered_count += 1
            assert data_len and indicator_len
            assert math.isfinite(data_value) and value == data_value
    assert delivered_count == 10


def test_secondary_regular_feed_identity_tracks_source():
    rows = _run(replay=False)
    assert len(rows) == 20
    assert rows[-1][:3] == (20, 10, 10)
    assert all(data_len == indicator_len for _, data_len, indicator_len, _, _, _ in rows)
    _assert_visible_values(rows)


def test_secondary_replay_identity_values_on_delivered_events():
    rows = _run(replay=True)
    assert len(rows) == 20
    _assert_visible_values(rows)


@pytest.mark.xfail(
    strict=True,
    raises=_ReplayClockLengthMismatch,
    reason="secondary replay indicator accumulates slots beyond delivered source bars",
)
def test_secondary_replay_identity_does_not_accumulate_extra_slots():
    rows = _run(replay=True)
    assert len(rows) == 20
    # A temporary source rewind may leave the indicator at its last delivered
    # slot. It must not create more slots than source bars delivered so far.
    delivered_max = 0
    excess = []
    for row in rows:
        _, data_len, indicator_len, _, _, delivered = row
        if delivered:
            delivered_max = max(delivered_max, data_len)
        if indicator_len > delivered_max:
            excess.append((row, delivered_max))
    if excess:
        raise _ReplayClockLengthMismatch(
            f"{len(excess)} excess advances; first={excess[0]!r}; last={rows[-1]!r}"
        )
    assert rows[-1][2] == rows[-1][1]
