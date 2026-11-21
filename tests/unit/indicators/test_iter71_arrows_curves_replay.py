"""Hourly-to-daily replay checks for ArrowsCurves bar-state replacement."""

import datetime as dt
import math

import backtrader as bt
import pandas as pd
import pytest


def _frame(missing_revision=None):
    rows = []
    dates = []
    for day in range(18):
        base = 100.0 + day * 2.0
        for hour, close in ((9, base + 8), (10, base - 12), (11, base + 10)):
            dates.append(dt.datetime(2025, 1, 1, hour) + dt.timedelta(days=day))
            rows.append(
                {
                    "open": base,
                    "high": max(base, close) + 1,
                    "low": min(base, close) - 1,
                    "close": close,
                    "volume": 1.0,
                    "openinterest": 0.0,
                }
            )
    if missing_revision is not None:
        rows[8 * 3 + missing_revision]["close"] = math.nan
    return pd.DataFrame(rows, index=dates)


def _expected(bars):
    up = old = up2 = old2 = False
    current = None
    for index in range(5, len(bars)):
        history = bars[index - 3 : index]
        high = max(row[0] for row in history)
        low = min(row[1] for row in history)
        close = bars[index][2]
        if math.isnan(close) or any(math.isnan(value) for row in history for value in row[:2]):
            current = (math.nan,) * 8
            continue
        smax, smin = high, low
        smax2 = high - (high - low) * 0.3
        smin2 = low + (high - low) * 0.3
        sell = buy = sell_stop = buy_stop = 0.0
        if close < smin and close < smax and up2 is True:
            up = False
        if close > smax and close > smin and up2 is False:
            up = True
        if (close > smax2 or close > smin2) and up is False:
            up2 = False
        if (close < smin2 or close < smax2) and up is True:
            up2 = True
        if close < smin and close < smax and up2 is False:
            sell, up2 = low, True
        if close > smax and close > smin and up2 is True:
            buy, up2 = high, False
        if up != old and up is False:
            sell = low
        if up != old and up is True:
            buy = high
        if up2 != old2 and up2 is True:
            buy_stop = smax2
        if up2 != old2 and up2 is False:
            sell_stop = smin2
        current = (sell, buy, sell_stop, buy_stop, smax, smin, smax2, smin2)
        old, old2 = up, up2
    return current


def _run(missing_revision, runonce):
    frame = _frame(missing_revision)

    class Probe(bt.Strategy):
        def __init__(self):
            self.replayed = self.datas[1]
            self.indicator = bt.ind.ArrowsCurvesIndicator(self.replayed, ssp=3, relay=1)
            self.observations = []

        def next(self):
            count = len(self.replayed)
            bars = [
                (
                    float(self.replayed.high[-j]),
                    float(self.replayed.low[-j]),
                    float(self.replayed.close[-j]),
                )
                for j in range(count - 1, -1, -1)
            ]
            self.observations.append(
                (
                    count,
                    self.replayed.datetime.datetime(0),
                    _expected(bars),
                    tuple(float(line[0]) for line in self.indicator.lines),
                )
            )

    engine = bt.Cerebro(stdstats=False, runonce=runonce, preload=False)
    engine.adddata(
        bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes, compression=60)
    )
    engine.replaydata(
        bt.feeds.PandasData(dataname=frame.copy(), timeframe=bt.TimeFrame.Minutes, compression=60),
        timeframe=bt.TimeFrame.Days,
    )
    engine.addstrategy(Probe)
    return engine.run(runonce=runonce, preload=False)[0].observations


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("missing_revision", [None, 1, 2])
def test_replay_revision_replaces_state_from_previous_completed_bar(runonce, missing_revision):
    observations = _run(missing_revision, runonce)
    assert len(observations) == 39
    for count, stamp, expected, actual in observations:
        assert expected is not None
        for got, want in zip(actual, expected):
            if math.isnan(want):
                assert math.isnan(got), (count, stamp, actual, expected)
            else:
                assert got == pytest.approx(want), (count, stamp, actual, expected)
    if missing_revision is not None:
        revisions = [row for row in observations if row[0] == 9]
        assert len(revisions) == 3
        for offset, revision in enumerate(revisions):
            check = math.isnan if offset == missing_revision else math.isfinite
            assert all(check(value) for value in revision[3])


@pytest.mark.parametrize("runonce", [False, True])
def test_real_strategy_runs_on_replayed_hourly_bars(runonce):
    import importlib.util
    import sys
    from pathlib import Path

    root = next(path for path in Path(__file__).resolve().parents if (path / "backtrader").is_dir())
    path = (
        root / "tests/functional/strategies/trend_following/test_0197_0479_arrows_and_curves_ea.py"
    )
    spec = importlib.util.spec_from_file_location("_replayed_arrows_strategy", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)

    class Probe(module.ArrowsAndCurvesEAStrategy):
        def __init__(self):
            super().__init__()
            self.actions = []

        def buy(self, *args, **kwargs):
            self.actions.append(("buy", len(self.data), self.data.datetime.datetime(0)))
            return super().buy(*args, **kwargs)

        def sell(self, *args, **kwargs):
            self.actions.append(("sell", len(self.data), self.data.datetime.datetime(0)))
            return super().sell(*args, **kwargs)

    engine = bt.Cerebro(stdstats=False, runonce=runonce, preload=False)
    engine.replaydata(
        bt.feeds.PandasData(dataname=_frame(), timeframe=bt.TimeFrame.Minutes, compression=60),
        timeframe=bt.TimeFrame.Days,
    )
    engine.addstrategy(Probe, ssp=3, relay=1, stop_loss_pips=0, take_profit_pips=0)
    strategy = engine.run(runonce=runonce, preload=False)[0]
    assert strategy.actions == [("buy", 7, dt.datetime(2025, 1, 7, 9))]
    assert engine.broker.getvalue() == pytest.approx(10003.2)


@pytest.mark.parametrize("runonce", [False, True])
def test_real_strategy_ignores_replaced_replay_buy_signal(runonce):
    import importlib.util
    import sys
    from pathlib import Path

    root = next(path for path in Path(__file__).resolve().parents if (path / "backtrader").is_dir())
    path = (
        root / "tests/functional/strategies/trend_following/test_0197_0479_arrows_and_curves_ea.py"
    )
    spec = importlib.util.spec_from_file_location("_delayed_arrows_strategy", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)

    class Probe(module.ArrowsAndCurvesEAStrategy):
        def __init__(self):
            super().__init__()
            self.actions = []

        def next(self):
            # Expose the false final revision without an earlier open position.
            if len(self.data) < 8:
                return None
            return super().next()

        def buy(self, *args, **kwargs):
            self.actions.append(("buy", len(self.data)))
            return super().buy(*args, **kwargs)

        def sell(self, *args, **kwargs):
            self.actions.append(("sell", len(self.data)))
            return super().sell(*args, **kwargs)

    engine = bt.Cerebro(stdstats=False, runonce=runonce, preload=False)
    engine.replaydata(
        bt.feeds.PandasData(dataname=_frame(), timeframe=bt.TimeFrame.Minutes, compression=60),
        timeframe=bt.TimeFrame.Days,
    )
    engine.addstrategy(Probe, ssp=3, relay=1, stop_loss_pips=0, take_profit_pips=0)
    strategy = engine.run(runonce=runonce, preload=False)[0]
    assert strategy.actions == []
    assert engine.broker.getvalue() == 10000.0
