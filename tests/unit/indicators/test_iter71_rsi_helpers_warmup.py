import math
import pandas as pd
import pytest
import backtrader as bt

VALUES = [
    10.0,
    12.0,
    11.0,
    14.0,
    15.0,
    13.0,
    16.0,
    12.0,
    12.0,
    15.0,
    17.0,
    14.0,
    18.0,
    13.0,
    15.0,
    16.0,
    12.0,
    11.0,
    16.0,
    20.0,
]
KINDS = [bt.ind.UpDay, bt.ind.DownDay, bt.ind.UpDayBool, bt.ind.DownDayBool]


def frame(v):
    return pd.DataFrame(
        {"open": v, "high": v, "low": v, "close": v, "volume": [1] * len(v)},
        index=pd.date_range("2020", periods=len(v), freq="min"),
    )


def expected(values, i, period, kind):
    change = values[i] - values[i - period]
    if kind == bt.ind.UpDay:
        return max(change, 0.0)
    if kind == bt.ind.DownDay:
        return max(-change, 0.0)
    if kind == bt.ind.UpDayBool:
        return float(change > 0.0)
    return float(change < 0.0)


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("period", [1, 2])
@pytest.mark.parametrize("chained", [False, True])
def test_helper(mode, kind, period, chained):
    out = {}

    class S(bt.Strategy):
        def __init__(self):
            self.src = bt.ind.SMA(self.data, period=3) if chained else self.data.close
            self.x = kind(self.src, period=period)
            out["min"] = self.x._minperiod

        def stop(self):
            out["values"] = list(self.x.array)

    c = bt.Cerebro(stdstats=False)
    c.adddata(bt.feeds.PandasData(dataname=frame(VALUES)))
    c.addstrategy(S)
    c.run(runonce=mode, preload=True)
    source = (
        [sum(VALUES[i - 2 : i + 1]) / 3 for i in range(2, len(VALUES))]
        if chained
        else VALUES
    )
    offset = 2 if chained else 0
    first = offset + period
    assert out["min"] == first + 1
    assert len(out["values"]) == len(VALUES)
    for i, a in enumerate(out["values"]):
        if i < first:
            assert math.isnan(a), (i, a)
        else:
            assert a == pytest.approx(expected(source, i - offset, period, kind))


@pytest.mark.parametrize("kind", KINDS)
def test_partial_once_does_not_overwrite_outside_slice(kind):
    out = {}

    class S(bt.Strategy):
        def __init__(self):
            self.x = kind(self.data, period=2)

        def stop(self):
            out["x"] = self.x

    c = bt.Cerebro(stdstats=False)
    c.adddata(bt.feeds.PandasData(dataname=frame(VALUES)))
    c.addstrategy(S)
    c.run(runonce=False, preload=True)
    x = out["x"]
    for i in range(len(VALUES)):
        x.lines[0].array[i] = 123456.0
    x.once(5, 8)
    for i, a in enumerate(x.lines[0].array):
        if 5 <= i < 8:
            assert a == expected(VALUES, i, 2, kind)
        else:
            assert a == 123456.0, (i, a)


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("layout", ["replay", "secondary"])
def test_replay_and_secondary(mode, kind, layout):
    out = []

    class S(bt.Strategy):
        def __init__(self):
            self.d = self.data1 if layout == "secondary" else self.data0
            self.x = kind(self.d, period=2)

        def next(self):
            values = [self.d.close[-j] for j in range(len(self.d) - 1, -1, -1)]
            out.append(
                (len(values), self.x[0], expected(values, len(values) - 1, 2, kind))
            )

    c = bt.Cerebro(stdstats=False)
    d = bt.feeds.PandasData(dataname=frame(VALUES), timeframe=bt.TimeFrame.Minutes)
    if layout == "replay":
        c.replaydata(d, timeframe=bt.TimeFrame.Minutes, compression=3)
    else:
        c.adddata(d)
        c.adddata(
            bt.feeds.PandasData(
                dataname=frame(VALUES).iloc[::2], timeframe=bt.TimeFrame.Minutes
            )
        )
    c.addstrategy(S)
    c.run(runonce=mode, preload=True)
    assert len(out) > 3
    for n, a, b in out:
        assert a == pytest.approx(b), (n, a, b)


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("position", [0, 1, 6])
def test_missing(mode, kind, position):
    values = VALUES.copy()
    values[position] = float("nan")
    out = {}

    class S(bt.Strategy):
        def __init__(self):
            self.x = kind(self.data, period=2)

        def stop(self):
            out["v"] = list(self.x.array)

    c = bt.Cerebro(stdstats=False)
    c.adddata(bt.feeds.PandasData(dataname=frame(values)))
    c.addstrategy(S)
    c.run(runonce=mode)
    for i, a in enumerate(out["v"]):
        b = float("nan") if i < 2 else expected(values, i, 2, kind)
        if math.isnan(b):
            assert math.isnan(a), (i, a, b)
        else:
            assert a == pytest.approx(b), (i, a, b)


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("period", [2, 4])
@pytest.mark.parametrize("length", [1, 2])
def test_short_history(mode, kind, period, length):
    out = {}

    class S(bt.Strategy):
        def __init__(self):
            self.x = kind(self.data, period=period)

        def stop(self):
            out["v"] = list(self.x.array)

    c = bt.Cerebro(stdstats=False)
    c.adddata(bt.feeds.PandasData(dataname=frame(VALUES[:length])))
    c.addstrategy(S)
    c.run(runonce=mode)
    assert len(out["v"]) == length
    assert all(math.isnan(x) for x in out["v"])
