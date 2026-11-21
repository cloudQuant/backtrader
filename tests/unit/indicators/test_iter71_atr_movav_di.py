import math
import pandas as pd
import pytest
import backtrader as bt

VALUES = [
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


def independent(kind):
    high = [x + 1 for x in VALUES]
    low = [x - 1 for x in VALUES]
    tr = []
    plus = []
    minus = []
    for i in range(1, len(VALUES)):
        tr.append(max(high[i], VALUES[i - 1]) - min(low[i], VALUES[i - 1]))
        u = high[i] - high[i - 1]
        d = low[i - 1] - low[i]
        plus.append(u if u > d and u > 0 else 0.0)
        minus.append(d if d > u and d > 0 else 0.0)

    def avg(vals):
        if kind == "sma":
            return [sum(vals[i - 2 : i + 1]) / 3 for i in range(2, len(vals))]
        alpha = 0.5 if kind == "ema" else 1 / 3
        a = sum(vals[:3]) / 3
        out = [a]
        for value in vals[3:]:
            a = a * (1 - alpha) + value * alpha
            out.append(a)
        return out

    ts, ps, ms = map(avg, (tr, plus, minus))
    return [(100 * p / t, 100 * m / t) for p, m, t in zip(ps, ms, ts)]


@pytest.mark.parametrize(
    "kind,movav",
    [
        ("wilder", bt.ind.MovAv.Smoothed),
        ("sma", bt.ind.MovAv.Simple),
        ("ema", bt.ind.MovAv.Exponential),
    ],
)
@pytest.mark.parametrize("mode", [False, True])
def test_directional_indicator(kind, movav, mode):
    frame = pd.DataFrame(
        {
            "open": VALUES,
            "high": [x + 1 for x in VALUES],
            "low": [x - 1 for x in VALUES],
            "close": VALUES,
            "volume": [1] * len(VALUES),
        },
        index=pd.date_range("2020-01-01", periods=len(VALUES)),
    )
    result = {}

    class S(bt.Strategy):
        def __init__(self):
            self.di = bt.ind.DirectionalIndicator(self.data, period=3, movav=movav)

        def stop(self):
            result["plus"] = list(self.di.plusDI.array)
            result["minus"] = list(self.di.minusDI.array)
            result["min"] = self.di._minperiod

    c = bt.Cerebro(stdstats=False)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(S)
    c.run(runonce=mode)
    assert result["min"] == 4
    for i, (p, m) in enumerate(independent(kind), start=3):
        assert result["plus"][i] == pytest.approx(p)
        assert result["minus"][i] == pytest.approx(m)
