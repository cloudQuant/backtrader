import math
import pandas as pd
import pytest
import backtrader as bt

V = [
    10.0,
    11.0,
    12.0,
    17.0,
    18.0,
    21.0,
    25.0,
    26.0,
    28.0,
    23.0,
    19.0,
    20.0,
    22.0,
    24.0,
    20.0,
    23.0,
    27.0,
    29.0,
    28.0,
    25.0,
    24.0,
    22.0,
    21.0,
    20.0,
    22.0,
    24.0,
    18.0,
    17.0,
    19.0,
    21.0,
    20.0,
    23.0,
]


def frame(v):
    return pd.DataFrame(
        {
            "open": v,
            "high": [x + 1 for x in v],
            "low": [x - 1 for x in v],
            "close": v,
            "volume": [1] * len(v),
        },
        index=pd.date_range("2020-01-01", periods=len(v), freq="min"),
    )


def reference(v, period, lookback, kind, safe):
    out = [float("nan")] * len(v)
    ups = []
    downs = []
    pu = None
    pdn = None
    for i in range(lookback, len(v)):
        delta = v[i] - v[i - lookback]
        ups.append(max(delta, 0))
        downs.append(max(-delta, 0))
        if len(ups) < period:
            continue
        if kind == "sma":
            u = sum(ups[-period:]) / period
            d = sum(downs[-period:]) / period
        elif pu is None:
            u = sum(ups[-period:]) / period
            d = sum(downs[-period:]) / period
        else:
            a = 2 / (period + 1) if kind == "ema" else 1 / period
            u = pu * (1 - a) + ups[-1] * a
            d = pdn * (1 - a) + downs[-1] * a
        pu, pdn = u, d
        out[i] = (50 if safe and u == 0 else 100) if d == 0 else 100 - 100 / (1 + u / d)
    return out


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("kind", ["sma", "ema", "wilder"])
@pytest.mark.parametrize("lookback", [1, 2])
@pytest.mark.parametrize("layout", ["single", "replay", "secondary"])
def test_rsi(mode, kind, lookback, layout):
    avg = {
        "sma": bt.ind.MovAv.Simple,
        "ema": bt.ind.MovAv.Exponential,
        "wilder": bt.ind.MovAv.Smoothed,
    }
    events = []
    out = {}

    class S(bt.Strategy):
        def __init__(self):
            self.d = self.data1 if layout == "secondary" else self.data0
            self.a = bt.ind.RSI(
                self.d, period=3, lookback=lookback, movav=avg[kind], safediv=True
            )
            out["min"] = self.a._minperiod

        def next(self):
            v = [self.d.close[-j] for j in range(len(self.d) - 1, -1, -1)]
            events.append(
                (len(v), self.a[0], reference(v, 3, lookback, kind, True)[-1])
            )

        def stop(self):
            out["a"] = list(self.a.array)
            out["v"] = list(self.d.close.array)

    c = bt.Cerebro(stdstats=False)
    d = bt.feeds.PandasData(dataname=frame(V), timeframe=bt.TimeFrame.Minutes)
    if layout == "replay":
        c.replaydata(d, timeframe=bt.TimeFrame.Minutes, compression=3)
    else:
        c.adddata(d)
        if layout == "secondary":
            c.adddata(
                bt.feeds.PandasData(
                    dataname=frame(V).iloc[::2], timeframe=bt.TimeFrame.Minutes
                )
            )
    c.addstrategy(S)
    c.run(runonce=mode, preload=True)
    assert out["min"] == 3 + lookback
    assert len(events) > 3
    for n, a, b in events:
        if math.isnan(b):
            assert math.isnan(a), (n, a, b)
        else:
            assert a == pytest.approx(b, rel=1e-11, abs=1e-11), (n, a, b)
    if layout != "replay":
        for a, b in zip(out["a"], reference(out["v"], 3, lookback, kind, True)):
            if math.isnan(b):
                assert math.isnan(a)
            else:
                assert a == pytest.approx(b)


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("kind", ["sma", "ema", "wilder"])
@pytest.mark.parametrize("position", [0, 2, 7])
def test_missing(mode, kind, position):
    avg = {
        "sma": bt.ind.MovAv.Simple,
        "ema": bt.ind.MovAv.Exponential,
        "wilder": bt.ind.MovAv.Smoothed,
    }
    v = V.copy()
    v[position] = float("nan")
    out = {}

    class S(bt.Strategy):
        def __init__(self):
            self.a = bt.ind.RSI(self.data, period=3, movav=avg[kind], safediv=True)

        def stop(self):
            out["a"] = list(self.a.array)

    c = bt.Cerebro(stdstats=False)
    c.adddata(bt.feeds.PandasData(dataname=frame(v)))
    c.addstrategy(S)
    c.run(runonce=mode)
    for i, (a, b) in enumerate(zip(out["a"], reference(v, 3, 1, kind, True))):
        if math.isnan(b):
            assert math.isnan(a), (i, a, b)
        else:
            assert a == pytest.approx(b), (i, a, b)


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("safe", [False, True])
@pytest.mark.parametrize("shape", ["flat", "up", "down"])
def test_flat_and_one_direction(mode, safe, shape):
    v = {
        "flat": [9.0] * 10,
        "up": [float(i) for i in range(10)],
        "down": [float(10 - i) for i in range(10)],
    }[shape]
    out = {}

    class S(bt.Strategy):
        def __init__(self):
            self.a = bt.ind.RSI(self.data, period=3, safediv=safe)

        def stop(self):
            out["a"] = list(self.a.array)

    c = bt.Cerebro(stdstats=False)
    c.adddata(bt.feeds.PandasData(dataname=frame(v)))
    c.addstrategy(S)
    c.run(runonce=mode)
    for a, b in zip(out["a"], reference(v, 3, 1, "wilder", safe)):
        if math.isnan(b):
            assert math.isnan(a)
        else:
            assert a == pytest.approx(b)


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("kind", ["sma", "ema", "wilder"])
@pytest.mark.parametrize("layout", ["single", "replay", "secondary"])
def test_chained(mode, kind, layout):
    avg = {
        "sma": bt.ind.MovAv.Simple,
        "ema": bt.ind.MovAv.Exponential,
        "wilder": bt.ind.MovAv.Smoothed,
    }
    events = []
    out = {}

    class S(bt.Strategy):
        def __init__(self):
            self.d = self.data1 if layout == "secondary" else self.data0
            self.s = bt.ind.SMA(self.d, period=4)
            self.a = bt.ind.RSI(self.s, period=3, movav=avg[kind], safediv=True)
            out["min"] = self.a._minperiod

        def next(self):
            v = [self.d.close[-j] for j in range(len(self.d) - 1, -1, -1)]
            upstream = [sum(v[i - 3 : i + 1]) / 4 for i in range(3, len(v))]
            events.append(
                (len(v), self.a[0], reference(upstream, 3, 1, kind, True)[-1])
            )

    c = bt.Cerebro(stdstats=False)
    d = bt.feeds.PandasData(dataname=frame(V), timeframe=bt.TimeFrame.Minutes)
    if layout == "replay":
        c.replaydata(d, timeframe=bt.TimeFrame.Minutes, compression=3)
    else:
        c.adddata(d)
        if layout == "secondary":
            c.adddata(
                bt.feeds.PandasData(
                    dataname=frame(V).iloc[::2], timeframe=bt.TimeFrame.Minutes
                )
            )
    c.addstrategy(S)
    c.run(runonce=mode, preload=True)
    assert out["min"] == 7
    assert len(events) > 2
    for n, a, b in events:
        if math.isnan(b):
            assert math.isnan(a), (n, a, b)
        else:
            assert a == pytest.approx(b, rel=1e-11, abs=1e-11), (n, a, b)


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("length", [1, 2, 3])
def test_short(mode, length):
    out = {}

    class S(bt.Strategy):
        def __init__(self):
            self.a = bt.ind.RSI(self.data, period=3, safediv=True)

        def stop(self):
            out["a"] = list(self.a.array)

    c = bt.Cerebro(stdstats=False)
    c.adddata(bt.feeds.PandasData(dataname=frame(V[:length])))
    c.addstrategy(S)
    c.run(runonce=mode)
    assert len(out["a"]) == length
    assert all(math.isnan(x) for x in out["a"])
