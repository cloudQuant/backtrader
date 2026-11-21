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
    if kind == "wma":
        return sum(v * w for v, w in zip(trs[-3:], (1, 2, 3))) / 6
    if kind == "sma":
        return sum(trs[-3:]) / 3
    a = sum(trs[:3]) / 3
    alpha = {"ema": 0.5, "wilder": 1 / 3}[kind]
    for tr in trs[3:]:
        a = a * (1 - alpha) + tr * alpha
    return a


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("kind", ["wma"])
@pytest.mark.parametrize("layout", ["single", "replay", "secondary"])
def test_full_strategy(mode, kind, layout):
    opts = {
        "wma": bt.ind.MovAv.Weighted,
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
