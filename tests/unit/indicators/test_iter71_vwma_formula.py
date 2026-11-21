import math

import backtrader as bt
import pandas as pd
import pytest


def _frame():
    closes = [10.0 + ((i * 7) % 11) for i in range(24)]
    volumes = [float(i % 5 - 1) for i in range(24)]
    volumes[9] = float("nan")
    volumes[15:19] = [0.0] * 4
    return pd.DataFrame({"open": [x - 1 for x in closes], "high": [x + 2 for x in closes],
                         "low": [x - 2 for x in closes], "close": closes,
                         "volume": volumes, "openinterest": [float(i % 4) for i in range(24)]},
                        index=pd.date_range("2024-01-02 09:00", periods=24, freq="min"))


def _run(*, runonce, replay, use_tick_volume):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = bt.indicators.VolumeWeightedMAIndicator(
                self.data, length=4, ipc=5, use_tick_volume=use_tick_volume)
            self.rows = []

        def next(self):
            window = [(float(self.data.high[-i]), float(self.data.low[-i]),
                       float(self.data.close[-i]),
                       float(self.data.volume[-i] if use_tick_volume else self.data.openinterest[-i]))
                      for i in range(4)]
            self.rows.append((window, float(self.ind.vwma[0])))

    c = bt.Cerebro(stdstats=False, runonce=runonce, preload=not replay)
    data = bt.feeds.PandasData(dataname=_frame(), timeframe=bt.TimeFrame.Minutes)
    if replay:
        c.replaydata(data, timeframe=bt.TimeFrame.Minutes, compression=2)
    else:
        c.adddata(data)
    c.addstrategy(Probe)
    return c.run()[0].rows


def _expected(window):
    prices = [(high + low + close) / 3.0 for high, low, close, _ in window]
    weights = [max(weight, 0.0) if not math.isnan(weight) else weight
               for _, _, _, weight in window]
    total = sum(weights)
    if total == 0.0:
        return prices[0]
    return sum(price * (weight / total) for price, weight in zip(prices, weights))


@pytest.mark.parametrize("use_tick_volume", [False, True])
@pytest.mark.parametrize("runonce,replay", [(False, False), (True, False), (False, True)])
def test_vwma_uses_current_window_and_weight_policy(runonce, replay, use_tick_volume):
    rows = _run(runonce=runonce, replay=replay, use_tick_volume=use_tick_volume)
    assert rows
    for window, value in rows:
        expected = _expected(window)
        if math.isnan(expected):
            assert math.isnan(value)
        else:
            assert value == pytest.approx(expected)
    if use_tick_volume and not replay:
        assert any(math.isnan(value) for _, value in rows)
        assert any(sum(max(weight, 0.0) for _, _, _, weight in window) == 0
                   for window, _ in rows if all(math.isfinite(x[3]) for x in window))
        assert math.isfinite(rows[-1][1])
