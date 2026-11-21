"""RSI histogram color must not classify a missing or invalid RSI value."""

import math
from types import SimpleNamespace

import backtrader as bt
import pandas as pd
import pytest

from backtrader.errors import FactorComputationContext, FactorComputationError
from backtrader.indicators.contrib.rsi_histogram_indicator import RSIHistogramIndicator
from tests.functional.strategies.mean_reversion.test_0271_0932_rsi_histogram import (
    ExpRSIHistogramStrategy,
)


def _frame(count=60):
    values = [100 + i * 0.13 + math.sin(i * 0.27) * 3 for i in range(count)]
    return pd.DataFrame(
        {"open": values, "high": [v + 1 for v in values],
         "low": [v - 1 for v in values], "close": values, "volume": [1.0] * count},
        index=pd.date_range("2024-01-01 09:00", periods=count, freq="D"),
    )


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("missing", [False, True])
def test_rsi_histogram_color_matches_value_or_is_missing(runonce, missing):
    frame = _frame()
    if missing:
        frame.iloc[30, frame.columns.get_loc("close")] = math.nan

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = RSIHistogramIndicator(self.data, rsi_period=3, high_level=60, low_level=40)

    engine = bt.Cerebro(runonce=runonce, stdstats=False)
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.addstrategy(Probe)
    ind = engine.run()[0].ind
    pairs = list(zip(ind.value.array, ind.color_state.array))
    seen_missing = 0
    for value, color in pairs[ind._minperiod - 1:]:
        if not math.isfinite(value):
            seen_missing += 1
            assert math.isnan(color)
        else:
            assert color == (0.0 if value > 60 else 2.0 if value < 40 else 1.0)
    assert (seen_missing > 0) is missing


def test_replay_missing_revision_recovers_on_same_bar():
    values = _frame(40)
    rows = []
    for day, row in values.iterrows():
        for hour in (0, 1):
            copy = row.copy()
            if len(rows) == 40:
                copy["close"] = math.nan
            rows.append((day + pd.Timedelta(hours=hour), copy))
    frame = pd.DataFrame([row for _, row in rows], index=[day for day, _ in rows])

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = RSIHistogramIndicator(self.data, rsi_period=3, high_level=60, low_level=40)
            self.samples = []

        def next(self):
            if len(self.data) == 21:
                self.samples.append((float(self.data.close[0]), float(self.ind.value[0]),
                                     float(self.ind.color_state[0])))

    engine = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    feed = bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes, compression=60)
    engine.replaydata(feed, timeframe=bt.TimeFrame.Days)
    engine.addstrategy(Probe)
    first, second = engine.run()[0].samples
    assert all(math.isnan(v) for v in first)
    assert math.isfinite(second[0]) and math.isfinite(second[1])
    assert second[2] == (0.0 if second[1] > 60 else 2.0 if second[1] < 40 else 1.0)


@pytest.mark.parametrize("prior,current,expected", [
    (math.nan, 0.0, []), (math.nan, 2.0, []), (0.0, math.nan, []),
    (2.0, math.nan, []), (1.0, 0.0, ["buy"]), (1.0, 2.0, ["sell"]),
])
def test_existing_strategy_does_not_treat_missing_as_crossing(prior, current, expected):
    class Line:
        def __getitem__(self, index):
            return prior if index == -1 else current

    class Feed:
        close = [100.0]

        def __len__(self):
            return 20

    calls = []
    actor = SimpleNamespace(
        bar_num=0, base=Feed(), signal_data=Feed(), _check_exit_levels=lambda: False,
        p=SimpleNamespace(signal_bar=1, rsi_period=3, fixed_lot=0.1,
                          sell_pos_close=True, buy_pos_open=True,
                          buy_pos_close=True, sell_pos_open=True),
        _last_signal_len=0, indicator=SimpleNamespace(color_state=Line()),
        position=SimpleNamespace(size=0), signal_count=0, log=lambda _msg: None,
        buy=lambda **_kwargs: calls.append("buy"),
        sell=lambda **_kwargs: calls.append("sell"),
        close=lambda: calls.append("close"),
    )
    ExpRSIHistogramStrategy.next(actor)
    assert calls == expected


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_raw_rsi_is_not_a_color(value):
    class Output:
        def __init__(self):
            self.value = None

        def __setitem__(self, _index, result):
            self.value = result

    target = SimpleNamespace(
        rsi=[value], p=SimpleNamespace(high_level=60, low_level=40),
        lines=SimpleNamespace(value=Output(), midline=Output(), color_state=Output()),
    )
    RSIHistogramIndicator.next(target)
    assert math.isnan(target.lines.color_state.value)


@pytest.mark.parametrize("runonce", [False, True])
def test_strict_infinite_upstream_read_still_raises(runonce):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = RSIHistogramIndicator(self.data, rsi_period=3)

        def next(self):
            if len(self) == 20:
                line = self.ind.rsi.lines[0]
                old = line.array[line.idx]
                line.array[line.idx] = math.inf
                line._factor_strict_context = FactorComputationContext("rsi", phase="next")
                try:
                    with pytest.raises(FactorComputationError):
                        self.ind.next()
                finally:
                    line.array[line.idx] = old
                    del line._factor_strict_context

    engine = bt.Cerebro(runonce=runonce, stdstats=False)
    engine.adddata(bt.feeds.PandasData(dataname=_frame()))
    engine.addstrategy(Probe)
    engine.run()
