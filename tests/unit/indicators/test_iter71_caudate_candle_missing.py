"""Caudate candle colors must not classify incomplete input windows."""

import math
from types import SimpleNamespace

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.caudate_x_period_candle_color import (
    CaudateXPeriodCandleColor,
)


NAMES = ("color_idx", "xopen", "xclose", "xhigh", "xlow")


def _frame(count=80, field=None):
    close = [100 + i * .1 + 3 * math.sin(i * .37) for i in range(count)]
    opens = [x + math.sin(i * .61) for i, x in enumerate(close)]
    high = [max(o, c) + 1 for o, c in zip(opens, close)]
    low = [min(o, c) - 1 for o, c in zip(opens, close)]
    result = pd.DataFrame({"open": opens, "high": high, "low": low, "close": close,
                           "volume": [10.0] * count},
                          index=pd.date_range("2020-01-01", periods=count, freq="D"))
    if field:
        result.iloc[30, result.columns.get_loc(field)] = math.nan
    return result


def _reference(frame, index, ma=3, lookback=5):
    def smoothed(field, at):
        if at < ma - 1:
            return math.nan
        window = list(frame[field].iloc[at - ma + 1:at + 1])
        return math.fsum(window) / ma if all(math.isfinite(v) for v in window) else math.nan

    xopen = smoothed("open", index - lookback + 1)
    xclose = smoothed("close", index)
    highs = [smoothed("high", index - i) for i in range(lookback)]
    lows = [smoothed("low", index - i) for i in range(lookback)]
    xhigh = max(highs) if all(math.isfinite(v) for v in highs) else math.nan
    xlow = min(lows) if all(math.isfinite(v) for v in lows) else math.nan
    if not all(math.isfinite(v) for v in (xopen, xclose, xhigh, xlow)):
        return math.nan, xopen, xclose, xhigh, xlow
    half = (xhigh + xlow) / 2.0
    color = 2.0 if xopen <= xclose else 4.0
    if xopen > half and xclose > half:
        color = 0.0 if xopen <= xclose else 1.0
    elif xopen < half and xclose < half:
        color = 6.0 if xopen >= xclose else 5.0
    return color, xopen, xclose, xhigh, xlow


def _run(frame, runonce, *, primary=None):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = CaudateXPeriodCandleColor(self.datas[-1])

    engine = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    if primary is not None:
        engine.adddata(bt.feeds.PandasData(dataname=primary))
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.addstrategy(Probe)
    return engine.run()[0].ind


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("field", [None, "open", "high", "low", "close"])
def test_color_matches_independent_windows_and_recovers(runonce, field):
    frame = _frame(field=field)
    ind = _run(frame, runonce)
    assert ind._minperiod == 8
    for index in range(7, len(frame)):
        expected = _reference(frame, index)
        actual = [getattr(ind.lines, name).array[index] for name in NAMES]
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12, nan_ok=True)
    if field:
        assert math.isfinite(ind.color_idx.array[29])
        assert any(math.isnan(v) for v in ind.color_idx.array[30:38])
        assert math.isfinite(ind.color_idx.array[40])


@pytest.mark.parametrize("runonce", [False, True])
def test_slow_second_feed_uses_its_own_complete_windows(runonce):
    secondary = _frame(count=45, field="high")
    secondary.index = pd.date_range("2020-01-01", periods=len(secondary), freq="3D")
    ind = _run(secondary, runonce, primary=_frame(count=135))
    for index in range(7, len(secondary)):
        assert [getattr(ind.lines, name).array[index] for name in NAMES] == pytest.approx(
            _reference(secondary, index), rel=1e-12, abs=1e-12, nan_ok=True
        )


def test_nonfinite_previous_extreme_is_not_hidden_by_max_or_min():
    class Line:
        def __init__(self, values):
            self.values = values
        def __getitem__(self, ago):
            return self.values[-ago]
        def __setitem__(self, ago, value):
            self.values[-ago] = value

    out = SimpleNamespace(**{name: Line([0.0]) for name in NAMES})
    obj = SimpleNamespace(p=SimpleNamespace(cperiod=3), lines=out,
                          smooth_open=Line([10.0, 10.0, 10.0]),
                          smooth_close=Line([11.0, 11.0, 11.0]),
                          smooth_high=Line([12.0, math.nan, 12.0]),
                          smooth_low=Line([9.0, 9.0, 9.0]))
    CaudateXPeriodCandleColor.next(obj)
    assert math.isnan(out.xhigh[0]) and math.isnan(out.color_idx[0])
    assert out.xopen[0] == 10.0 and out.xclose[0] == 11.0 and out.xlow[0] == 9.0


def test_replay_current_bar_revisions_match_window_reference():
    values = [100 + i * .4 + 2 * math.sin(i * .7) for i in range(24)]
    records = []
    dates = []
    for i, value in enumerate(values):
        for hour, adjustment in ((9, 0.0), (10, 1.0), (11, -.4)):
            close = value + adjustment
            records.append({"open": value, "high": max(value, close) + 1,
                            "low": min(value, close) - 1, "close": close, "volume": 1.0})
            dates.append(pd.Timestamp("2020-01-01") + pd.Timedelta(days=i, hours=hour))
    frame = pd.DataFrame(records, index=pd.DatetimeIndex(dates))

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = CaudateXPeriodCandleColor(self.data)
            self.bars = []
            self.seen = []

        def prenext(self):
            self.next()

        def next(self):
            n = len(self.data)
            bar = {name: float(getattr(self.data, name)[0])
                   for name in ("open", "high", "low", "close")}
            if len(self.bars) < n:
                self.bars.append(bar)
            else:
                self.bars[-1] = bar
            if n >= self.ind._minperiod:
                expected = _reference(pd.DataFrame(self.bars), n - 1)
                actual = [float(getattr(self.ind.lines, name)[0]) for name in NAMES]
                self.seen.append((n, actual, expected))

    engine = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    feed = bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes, compression=60)
    engine.replaydata(feed, timeframe=bt.TimeFrame.Days)
    engine.addstrategy(Probe)
    seen = engine.run()[0].seen
    assert len(seen) >= 40
    for _, actual, expected in seen:
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12, nan_ok=True)


def test_replay_replaced_smoothed_high_recomputes_color():
    daily = _frame(24)
    records = []
    dates = []
    for index in range(len(daily)):
        for hour in (9, 10, 11):
            records.append(daily.iloc[index].to_dict())
            dates.append(pd.Timestamp("2020-01-01") + pd.Timedelta(days=index, hours=hour))
    frame = pd.DataFrame(records, index=pd.DatetimeIndex(dates))

    class Injected(CaudateXPeriodCandleColor):
        def next(self):
            if len(self.data) == 14:
                hour = self.data.datetime.datetime(0).hour
                if hour == 9:
                    self.saved_high = float(self.smooth_high[0])
                elif hour == 10:
                    self.smooth_high[0] = math.nan
                elif hour == 11:
                    # Explicitly replace the child line: replay need not
                    # recompute a child whose source high did not change.
                    self.smooth_high[0] = self.saved_high
            super().next()

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = Injected(self.data)
            self.seen = []

        def next(self):
            self.seen.append((len(self.data), self.data.datetime.datetime(0).hour,
                              float(self.ind.color_idx[0])))

    engine = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    feed = bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes, compression=60)
    engine.replaydata(feed, timeframe=bt.TimeFrame.Days)
    engine.addstrategy(Probe)
    seen = [row for row in engine.run()[0].seen if row[0] == 14]
    assert [hour for _, hour, _ in seen] == [9, 10, 11]
    assert math.isfinite(seen[0][2])
    assert math.isnan(seen[1][2])
    assert math.isfinite(seen[2][2])


@pytest.mark.parametrize("runonce", [False, True])
def test_original_strategy_does_not_close_long_on_missing_candle(runonce):
    from tests.functional.strategies.mean_reversion.test_0108_0345_exp_caudatexperiodcandle_tm_plus import (
        ExpCaudateXPeriodCandleTmPlusStrategy,
    )

    class Probe(ExpCaudateXPeriodCandleTmPlusStrategy):
        def __init__(self):
            super().__init__()
            self.close_calls = []
            self.gap_color = None

        def close(self, *args, **kwargs):
            self.close_calls.append(len(self.signal_feed))
            return super().close(*args, **kwargs)

        def next(self):
            bar = len(self.signal_feed)
            if bar == 29:
                self.buy(size=1)
            elif bar == 31:
                assert self.position.size == 1
                self.gap_color = float(self.channel.color_idx[0])
                super().next()

    engine = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    engine.adddata(bt.feeds.PandasData(dataname=_frame()))
    engine.adddata(bt.feeds.PandasData(dataname=_frame(field="close")))
    engine.addstrategy(Probe, time_trade=False)
    result = engine.run()[0]
    assert math.isnan(result.gap_color)
    assert result.close_calls == []
    assert result.position.size == 1


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("output", ["color_idx", "xhigh"])
def test_strict_factor_rejects_midpoint_overflow(runonce, output):
    from backtrader.errors import FactorComputationError
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    from tests.unit.test_factor_research_representatives import _frames, _research_feed, _research_spec

    frame = _frames(periods=25)["asset-0"].copy()
    for field in ("open", "high", "low", "close"):
        frame.loc[:, field] = 1e308
    research = _research_spec({"asset-0": frame})

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = CaudateXPeriodCandleColor(self.data, ma_length=1, cperiod=1)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = getattr(self.child, output)[0]

    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(_research_feed(frame, research, "asset-0"), name="asset-0")
    spec = FactorSpec(name="caudate", indicator=Factor, panel_line="factor",
                      field_bindings={"close": "feed:target:close"}, mode="native")
    engine.addstrategy(FactorStrategy, research=research, factors={"caudate": spec})
    with pytest.raises(FactorComputationError) as caught:
        engine.run(preload=True)
    assert caught.value.code == "FACTOR_COMPUTATION_FAILED"
    assert isinstance(caught.value.__cause__, ArithmeticError)
