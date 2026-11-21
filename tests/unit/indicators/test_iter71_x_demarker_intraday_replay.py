"""Exercise real intraday updates and failed revisions of a daily replay bar."""

import datetime as dt
import math

import pandas as pd
import pytest

import backtrader as bt


def _input_frame():
    rows = []
    times = []
    for day in range(20):
        base = 100.0 + day * 0.2 + ((day * 7) % 9) * 0.4
        for hour, high, low, close, volume in (
            (9, base + 0.1, base - 0.1, base, 2.0),
            (10, base + 1.0 + day % 3 * 0.1, base - 0.7, base + 0.4, 3.0),
            (11, base + 1.5, base - 1.0, base + 0.7, 5.0),
        ):
            times.append(dt.datetime(2025, 1, 1, hour) + dt.timedelta(days=day))
            rows.append(
                {
                    "open": base,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "openinterest": 0.0,
                }
            )
    return pd.DataFrame(rows, index=times)


def _expected(bars):
    """Calculate the full p=3, q=2 formula from current replay bars."""
    maxima, minima, raw, volumes = [], [], [], []
    last_value = math.nan
    last_direction = math.nan
    result = None
    for index in range(1, len(bars)):
        current, previous = bars[index], bars[index - 1]
        maxima.append(max(current["high"] - previous["high"], 0.0))
        minima.append(max(previous["low"] - current["low"], 0.0))
        maxima, minima = maxima[-3:], minima[-3:]
        if len(maxima) < 3:
            continue
        denominator = sum(maxima) + sum(minima)
        ratio = sum(maxima) / denominator if denominator > 0.0 else 0.5
        raw.append((100.0 * ratio - 50.0) * current["volume"])
        volumes.append(current["volume"])
        raw, volumes = raw[-2:], volumes[-2:]
        if len(raw) < 2:
            continue
        value = sum(raw) / 2.0
        avg = sum(volumes) / 2.0
        upper2, upper1, lower1, lower2 = 20 * avg, 15 * avg, -15 * avg, -20 * avg
        if value > upper2:
            zone = 0.0
        elif value > upper1:
            zone = 1.0
        elif value < lower2:
            zone = 4.0
        elif value < lower1:
            zone = 3.0
        else:
            zone = 2.0
        direction = last_direction if math.isfinite(last_direction) else 1.0
        if math.isfinite(last_value):
            if value > last_value:
                direction = 0.0
            elif value < last_value:
                direction = 1.0
        last_value, last_direction = value, direction
        result = (value, zone, direction, upper2, upper1, lower1, lower2)
    return result


@pytest.mark.parametrize("inject_failure", [False, True])
def test_intraday_replay_replaces_bar_and_retries_after_failure(inject_failure):
    failure = RuntimeError("second intraday revision")

    class Indicator(bt.indicators.XDeMarkerHistogramVolDirectIndicator):
        alias = ()

        def __init__(self):
            self.revisions = 0
            self.failed = False
            super().__init__()

        def _bar_volume(self):
            if len(self.data) == 8:
                self.revisions += 1
                if inject_failure and self.revisions == 2:
                    self.failed = True
                    raise failure
            return super()._bar_volume()

    class Strategy(bt.Strategy):
        def __init__(self):
            self.signal = self.datas[1]
            self.indicator = Indicator(self.signal, de_marker_period=3, ma_length=2)
            self.observations = []
            self.failures = []
            self.last_success = {}

        def _next(self):
            try:
                return super()._next()
            except RuntimeError as error:
                if error is not failure:
                    raise
                values = tuple(float(line[0]) for line in self.indicator.lines)
                self.failures.append(
                    (len(self.signal), values, self.last_success[len(self.signal)])
                )

        def next(self):
            size = len(self.signal)
            bars = [
                {
                    name: float(getattr(self.signal, name)[-ago])
                    for name in ("high", "low", "volume")
                }
                for ago in range(size - 1, -1, -1)
            ]
            values = tuple(float(line[0]) for line in self.indicator.lines)
            self.last_success[size] = values
            self.observations.append((size, bars[-1]["volume"], values, _expected(bars)))

    frame = _input_frame()
    engine = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    engine.adddata(
        bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes, compression=60)
    )
    engine.replaydata(
        bt.feeds.PandasData(dataname=frame.copy(), timeframe=bt.TimeFrame.Minutes, compression=60),
        timeframe=bt.TimeFrame.Days,
        compression=1,
    )
    engine.addstrategy(Strategy)
    strategy = engine.run(runonce=False, preload=False)[0]

    assert strategy.observations
    for _size, _volume, actual, expected in strategy.observations:
        assert expected is not None
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12)
    eighth = [item for item in strategy.observations if item[0] == 8]
    assert [item[1] for item in eighth] == ([2.0, 10.0] if inject_failure else [2.0, 5.0, 10.0])
    assert bool(strategy.failures) == inject_failure
    if inject_failure:
        assert len(strategy.failures) == 1
        length, after_failure, before_failure = strategy.failures[0]
        assert length == 8
        assert after_failure == before_failure
        assert any(size == 9 for size, *_rest in strategy.observations)
