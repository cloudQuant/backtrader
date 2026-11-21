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
]


def frame(v=V):
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


def reference(cl, hi, lo, kind):
    trs = [max(hi[i], cl[i - 1]) - min(lo[i], cl[i - 1]) for i in range(1, len(cl))]
    if kind == "sma":
        return sum(trs[-3:]) / 3
    a = sum(trs[:3]) / 3
    alpha = {"ema": 0.5, "wilder": 1 / 3}[kind]
    for tr in trs[3:]:
        a = a * (1 - alpha) + tr * alpha
    return a


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("kind", ["sma", "ema", "wilder"])
@pytest.mark.parametrize("layout", ["single", "replay", "secondary"])
def test_full_strategy(mode, kind, layout):
    opts = {
        "sma": bt.ind.MovAv.Simple,
        "ema": bt.ind.MovAv.Exponential,
        "wilder": bt.ind.MovAv.Smoothed,
    }
    rows = []
    metadata = {}

    class S(bt.Strategy):
        def __init__(self):
            self.datax = self.data1 if layout == "secondary" else self.data0
            self.atr = bt.ind.ATR(self.datax, period=3, movav=opts[kind])
            metadata["min"] = self.atr._minperiod

        def next(self):
            n = len(self.datax)
            cl = [self.datax.close[-j] for j in range(n - 1, -1, -1)]
            hi = [self.datax.high[-j] for j in range(n - 1, -1, -1)]
            lo = [self.datax.low[-j] for j in range(n - 1, -1, -1)]
            rows.append((self.atr[0], reference(cl, hi, lo, kind)))

    c = bt.Cerebro(stdstats=False)
    d = bt.feeds.PandasData(dataname=frame(), timeframe=bt.TimeFrame.Minutes)
    if layout == "replay":
        c.replaydata(d, timeframe=bt.TimeFrame.Minutes, compression=3)
    else:
        c.adddata(d)
        if layout == "secondary":
            c.adddata(
                bt.feeds.PandasData(
                    dataname=frame().iloc[::2], timeframe=bt.TimeFrame.Minutes
                )
            )
    c.addstrategy(S)
    c.run(runonce=mode, preload=True)
    assert metadata["min"] == 4
    assert len(rows) > 3
    for actual, expected in rows:
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize(
    "kind", [bt.ind.MovAv.Simple, bt.ind.MovAv.Exponential, bt.ind.MovAv.Smoothed]
)
def test_short(mode, kind):
    out = {}

    class S(bt.Strategy):
        def __init__(self):
            self.a = bt.ind.ATR(self.data, period=3, movav=kind)

        def stop(self):
            out["a"] = list(self.a.array)

    c = bt.Cerebro(stdstats=False)
    c.adddata(bt.feeds.PandasData(dataname=frame(V[:3])))
    c.addstrategy(S)
    c.run(runonce=mode, preload=True)
    assert len(out["a"]) == 3 and all(math.isnan(x) for x in out["a"])


@pytest.mark.parametrize("mode", [False, True])
def test_custom_minperiod(mode):
    class Delayed(bt.Indicator):
        lines = ("avg",)
        params = (("period", 3),)

        def __init__(self):
            super().__init__()
            self.addminperiod(self.p.period + 2)

        def next(self):
            self.lines.avg[0] = sum(self.data[-j] for j in range(5)) / 5

        def once(self, start, end):
            for i in range(start, end):
                self.lines.avg.array[i] = (
                    sum(self.data.array[i - j] for j in range(5)) / 5
                )

    out = {}

    class S(bt.Strategy):
        def __init__(self):
            self.a = bt.ind.ATR(self.data, period=3, movav=Delayed)
            out["min"] = self.a._minperiod

        def stop(self):
            out["values"] = list(self.a.array)

    c = bt.Cerebro(stdstats=False)
    c.adddata(bt.feeds.PandasData(dataname=frame()))
    c.addstrategy(S)
    c.run(runonce=mode, preload=True)
    assert out["min"] == 6
    assert all(math.isnan(x) for x in out["values"][:5])
    for i in range(5, len(V)):
        trs = [
            max(V[j] + 1, V[j - 1]) - min(V[j] - 1, V[j - 1])
            for j in range(i - 4, i + 1)
        ]
        assert out["values"][i] == pytest.approx(sum(trs) / 5)


@pytest.mark.parametrize("mode", [False, True])
def test_missing_window_sma(mode):
    v = V.copy()
    v[7] = float("nan")
    out = {}

    class S(bt.Strategy):
        def __init__(self):
            self.a = bt.ind.ATR(self.data, period=3, movav=bt.ind.MovAv.Simple)

        def stop(self):
            out["v"] = list(self.a.array)

    c = bt.Cerebro(stdstats=False)
    c.adddata(bt.feeds.PandasData(dataname=frame(v)))
    c.addstrategy(S)
    c.run(runonce=mode, preload=True)
    assert all(math.isnan(out["v"][i]) for i in (7, 8, 9))
    assert out["v"][10] == pytest.approx(
        reference(v[:11], [x + 1 for x in v[:11]], [x - 1 for x in v[:11]], "sma")
    )
