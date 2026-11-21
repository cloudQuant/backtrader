"""Real replay and multi-clock checks for XFisher's same-bar updates."""

from datetime import datetime, timedelta
import math

import backtrader as bt
import pandas as pd
import pytest


_FLENGTH = 3
_MA_LENGTH = 2
_MINPERIOD = _FLENGTH + _MA_LENGTH + 2


def _minute_frame(day_count=12):
    rows = []
    timestamps = []
    start = datetime(2022, 1, 3, 9, 0)
    for day in range(day_count):
        opening = 100.0 + day * 0.29 + math.sin(day * 0.23) * 1.4
        middle = opening + math.cos(day * 0.47) * 2.3
        closing = opening + math.sin(day * 0.61) * 1.8 - 0.2
        ticks = (
            (opening, opening + 0.35, opening - 0.25, opening),
            (opening, max(opening, middle) + 0.55,
             min(opening, middle) - 0.4, middle),
            (middle, max(middle, closing) + 0.45,
             min(middle, closing) - 0.65, closing),
        )
        for tick, (open_, high, low, close) in enumerate(ticks):
            rows.append(
                {
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": 1.0 + day + tick,
                    "openinterest": 0.0,
                }
            )
            timestamps.append(
                start + timedelta(days=day, hours=tick * 3)
            )
    return pd.DataFrame(rows, index=pd.DatetimeIndex(timestamps))


def _reference_current(bars):
    """Recompute Fisher state over finalized bars plus current replay bar."""
    previous_value = 0.0
    previous_fish = 0.0
    previous_smooth = None
    alpha = 2.0 / (_MA_LENGTH + 1.0)

    for index in range(_FLENGTH - 1, len(bars)):
        window = bars[index - _FLENGTH + 1 : index + 1]
        smax = max(bar[1] for bar in window)
        smin = min(bar[2] for bar in window)
        spread = smax - smin
        if spread == 0.0:
            spread = 1e-12

        wpr = (bars[index][3] - smin) / spread
        value = (wpr - 0.5) + 0.67 * previous_value
        value = max(min(value, 0.999), -0.999)
        ratio = max((1.0 + value) / (1.0 - value), 1e-7)
        fish = 0.5 * math.log(ratio) + 0.5 * previous_fish
        smooth = (
            fish
            if previous_smooth is None
            else previous_smooth + alpha * (fish - previous_smooth)
        )
        previous_value, previous_fish, previous_smooth = value, fish, smooth

    return previous_smooth


def _run_replay():
    frame = _minute_frame()

    class Probe(bt.Strategy):
        def __init__(self):
            self.fast = self.datas[0]
            self.replay = self.datas[1]
            self.indicator = bt.indicators.XFisherIndicator(
                self.replay, flength=_FLENGTH, ma_length=_MA_LENGTH
            )
            self.observations = []

        def next(self):
            count = len(self.replay)
            bars = [
                (
                    float(self.replay.open[-ago]),
                    float(self.replay.high[-ago]),
                    float(self.replay.low[-ago]),
                    float(self.replay.close[-ago]),
                )
                for ago in range(count - 1, -1, -1)
            ]
            self.observations.append(
                {
                    "fast_length": len(self.fast),
                    "replay_length": count,
                    "current": bars[-1],
                    "bars": bars,
                    "xfisher": float(self.indicator.xfisher[0]),
                }
            )

        def stop(self):
            self.result = {
                "minperiod": self.indicator._minperiod,
                "observations": list(self.observations),
            }

    cerebro = bt.Cerebro(stdstats=False)
    minute = bt.feeds.PandasData(
        dataname=frame,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    replay_source = bt.feeds.PandasData(
        dataname=frame,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro.adddata(minute, name="minute-clock")
    cerebro.replaydata(
        replay_source,
        name="daily-replay",
        timeframe=bt.TimeFrame.Days,
        compression=1,
    )
    cerebro.addstrategy(Probe)
    result = cerebro.run(runonce=False, preload=False)[0].result
    return result


def test_x_fisher_replay_revisions_recompute_from_prebar_state():
    result = _run_replay()
    observations = result["observations"]

    assert result["minperiod"] == _MINPERIOD
    repeated_lengths = {
        item["replay_length"]
        for item in observations
        if sum(other["replay_length"] == item["replay_length"]
               for other in observations) > 1
    }
    assert repeated_lengths
    assert any(
        len({item["current"] for item in observations
             if item["replay_length"] == length}) > 1
        for length in repeated_lengths
    )
    assert any(
        len({item["fast_length"] for item in observations
             if item["replay_length"] == length}) > 1
        for length in repeated_lengths
    )

    checked = [
        item for item in observations
        if item["replay_length"] >= _MINPERIOD
    ]
    assert checked
    for item in checked:
        expected = _reference_current(item["bars"])
        assert item["xfisher"] == pytest.approx(
            expected, rel=1e-12, abs=1e-12
        ), (item["fast_length"], item["replay_length"], item["current"])
