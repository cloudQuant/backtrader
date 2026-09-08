"""SpreadZScore indicator: rolling z-score of a two-leg price spread."""

import backtrader as bt
import backtrader.indicators as btind


def run_indicator(close0, close1, period):
    cerebro = bt.Cerebro()

    from backtrader.feeds import PandasData
    import pandas as pd

    index = pd.date_range("2026-01-01", periods=len(close0), freq="min")
    frame0 = pd.DataFrame(
        {
            "open": close0,
            "high": close0,
            "low": close0,
            "close": close0,
            "volume": 0,
            "openinterest": 0,
        },
        index=index,
    )
    frame1 = pd.DataFrame(
        {
            "open": close1,
            "high": close1,
            "low": close1,
            "close": close1,
            "volume": 0,
            "openinterest": 0,
        },
        index=index,
    )
    cerebro.adddata(PandasData(dataname=frame0), name="leg0")
    cerebro.adddata(PandasData(dataname=frame1), name="leg1")

    collected = []

    class Collector(bt.Strategy):
        params = (("period", period),)

        def __init__(self):
            self.z = btind.SpreadZScore(self.data0, self.data1, period=self.p.period)

        def next(self):
            collected.append(
                (len(self), self.z.lines.spread[0], self.z.lines.mean[0], self.z.lines.zscore[0])
            )

    cerebro.addstrategy(Collector)
    cerebro.run()
    return collected


def test_spread_zscore_warms_up_then_flags_jump():
    flat = [3500.0] * 8
    far_flat = [3470.0] * 8
    near = flat + [3508.0]
    far = far_flat + [3470.0]
    rows = run_indicator(near, far, period=5)

    # After the warm-up the spread is stable: mean=30, std=0 -> zscore 0.0.
    warm = [row for row in rows if row[0] == 6][0]
    assert warm[1] == 30.0 and warm[2] == 30.0
    assert warm[3] == 0.0

    # The jump bar: spread=38 against a 30 mean; with a window of five 30s
    # replaced one-by-one, mean=31.6 and the z-score is clearly positive.
    jump = rows[-1]
    assert jump[1] == 38.0
    assert jump[2] == 31.6
    assert jump[3] > 1.5


def test_spread_zscore_minperiod_equals_period():
    cerebro = bt.Cerebro()
    import pandas as pd
    from backtrader.feeds import PandasData

    index = pd.date_range("2026-01-01", periods=6, freq="min")
    frame = pd.DataFrame(
        {
            "open": [1.0] * 6,
            "high": [1.0] * 6,
            "low": [1.0] * 6,
            "close": [1.0] * 6,
            "volume": 0,
            "openinterest": 0,
        },
        index=index,
    )
    cerebro.adddata(PandasData(dataname=frame))
    cerebro.adddata(PandasData(dataname=frame.copy()))

    captured = {}

    class Probe(bt.Strategy):
        def __init__(self):
            z = btind.SpreadZScore(self.data0, self.data1, period=5)
            captured["minperiod"] = z._minperiod

    cerebro.addstrategy(Probe)
    cerebro.run()
    assert captured["minperiod"] == 5


def test_spread_zscore_registered_in_package_namespace():
    assert hasattr(btind, "SpreadZScore")
