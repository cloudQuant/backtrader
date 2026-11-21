import importlib.util
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

import backtrader as bt
from backtrader.indicators.contrib.arrows_curves_indicator import ArrowsCurvesIndicator

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "backtrader").is_dir())
STRATEGY = (
    ROOT / "tests/functional/strategies/trend_following/test_0197_0479_arrows_and_curves_ea.py"
)


def data(missing=None, count=32):
    close = [10.0] * count
    close[6] = 15.0
    high = [12.0] * count
    high[6] = 16.0
    frame = pd.DataFrame(
        {
            "open": [10.0] * count,
            "high": high,
            "low": [8.0] * count,
            "close": close,
            "volume": [1.0] * count,
        },
        index=pd.date_range("2024-01-01", periods=count, freq="h"),
    )
    if missing:
        frame.loc[frame.index[missing[1]], missing[0]] = math.nan
    return frame


def reference(frame, ssp=3, relay=1, channel=0.0, ch_stop=30.0):
    rows = []
    up = old = up2 = old2 = False
    for i in range(len(frame)):
        if i < ssp + relay + 1:
            rows.append([math.nan] * 8)
            continue
        highs = [float(frame.high.iloc[i - j]) for j in range(relay, relay + ssp)]
        lows = [float(frame.low.iloc[i - j]) for j in range(relay, relay + ssp)]
        close = float(frame.close.iloc[i])
        if not all(math.isfinite(v) for v in (*highs, *lows, close)):
            rows.append([math.nan] * 8)
            continue
        hi, lo = max(highs), min(lows)
        smax = hi - (lo - hi) * channel / 100.0
        smin = lo + (hi - lo) * channel / 100.0
        smax2 = hi - (hi - lo) * (channel + ch_stop) / 100.0
        smin2 = lo + (hi - lo) * (channel + ch_stop) / 100.0
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
            sell = lo
            up2 = True
        if close > smax and close > smin and up2 is True:
            buy = hi
            up2 = False
        if up != old and up is False:
            sell = lo
        if up != old and up is True:
            buy = hi
        if up2 != old2 and up2 is True:
            buy_stop = smax2
        if up2 != old2 and up2 is False:
            sell_stop = smin2
        rows.append([sell, buy, sell_stop, buy_stop, smax, smin, smax2, smin2])
        old, old2 = up, up2
    return rows


def run(frame, once, **kwargs):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = ArrowsCurvesIndicator(self.data, **kwargs)

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(Probe)
    return c.run()[0].ind


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("missing", [None, ("high", 4), ("low", 4), ("close", 6)])
@pytest.mark.parametrize("ssp,relay,channel,ch_stop", [(3, 1, 0, 30), (4, 2, 25, 10)])
def test_window_missing_recovery_and_formula(once, missing, ssp, relay, channel, ch_stop):
    frame = data(missing)
    ind = run(frame, once, ssp=ssp, relay=relay, channel=channel, ch_stop=ch_stop)
    expected = reference(frame, ssp, relay, channel, ch_stop)
    for i, row in enumerate(expected):
        for line, value in zip(ind.lines, row):
            actual = line.array[i]
            if math.isnan(value):
                assert math.isnan(actual), (i, actual)
            else:
                assert actual == pytest.approx(value), (i, actual, value)


@pytest.mark.parametrize("once", [False, True])
def test_real_strategy_does_not_open_on_missing_window(once):
    spec = importlib.util.spec_from_file_location("_arrows_functional", STRATEGY)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)

    class Probe(module.ArrowsAndCurvesEAStrategy):
        def __init__(self):
            super().__init__()
            self.orders = []

        def buy(self, *args, **kwargs):
            self.orders.append(("buy", len(self.data) - 1))
            return super().buy(*args, **kwargs)

        def sell(self, *args, **kwargs):
            self.orders.append(("sell", len(self.data) - 1))
            return super().sell(*args, **kwargs)

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(bt.feeds.PandasData(dataname=data(("high", 4))))
    c.addstrategy(Probe, ssp=3, relay=1, stop_loss_pips=0, take_profit_pips=0)
    assert c.run()[0].orders == []


@pytest.mark.parametrize("once", [False, True])
def test_replay_observable_missing_window_does_not_publish_finite_lines(once):
    frame = data(count=240)
    frame.index = pd.date_range("2024-01-01", periods=len(frame), freq="min")
    frame.loc[frame.index[100:110], "close"] = math.nan

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = ArrowsCurvesIndicator(self.data, ssp=3, relay=1)
            self.missing = 0

        def next(self):
            highs = [float(self.data.high[-j]) for j in range(1, 4)]
            lows = [float(self.data.low[-j]) for j in range(1, 4)]
            required = (*highs, *lows, float(self.data.close[0]))
            if not all(math.isfinite(x) for x in required):
                self.missing += 1
                assert all(math.isnan(line[0]) for line in self.ind.lines)

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.replaydata(
        bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes),
        timeframe=bt.TimeFrame.Minutes,
        compression=10,
    )
    c.addstrategy(Probe)
    assert c.run()[0].missing > 0


@pytest.mark.parametrize("once", [False, True])
def test_custom_channel_can_return_non_numeric_intermediate(once):
    class Product:
        def __init__(self, value):
            self.value = value

        def __truediv__(self, divisor):
            return self.value / divisor

    class Channel:
        def __rmul__(self, value):
            return Product(value)

        def __add__(self, other):
            return 0.0

    ind = run(data(), once, ssp=3, relay=1, channel=Channel())
    assert ind.smax.array[10] == pytest.approx(12.04)
    assert ind.smin.array[10] == pytest.approx(8.04)


@pytest.mark.parametrize("once", [False, True])
def test_ordinary_finite_extreme_inputs_keep_legacy_results(once):
    frame = data()
    frame["high"] = 1e308
    frame["low"] = -1e308
    frame["close"] = 0.0
    ind = run(frame, once, ssp=3, relay=1)
    assert [line.array[10] for line in ind.lines][:4] == [0.0] * 4
    assert all(math.isnan(line.array[10]) for line in tuple(ind.lines)[4:])


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("missing", [False, True])
def test_strict_factor_missing_window_and_finite_control(once, missing):
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("high", "low", "close")
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = ArrowsCurvesIndicator(self.data, ssp=3, relay=1)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.smax[0]

    frame = data(("high", 4) if missing else None, count=32)
    frame.index = frame.index.tz_localize("UTC")
    index = frame.index.rename("close_time")
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(hours=1)}, index=index),
        start=index[0],
        end=index[-1],
        targets=("asset",),
        source_timezone="UTC",
        snapshot_id="arrows-missing",
        price_basis="synthetic",
        calendar_id="hourly",
        frequency="1h",
        feed_time_kind="close_time",
        groups={"asset": "market"},
    )
    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(align_to_grid(frame, research, "asset").feed, name="asset")
    fs = FactorSpec(
        name="arrows",
        indicator=Factor,
        panel_line="factor",
        field_bindings={f: f"feed:target:{f}" for f in Factor.required_fields},
        mode="native",
    )
    c.addstrategy(FactorStrategy, research=research, factors={"arrows": fs})
    strategy = c.run(preload=True)[0]
    child = strategy._factor_instances_by_name["arrows"][0].child
    if missing:
        assert all(math.isnan(line.array[6]) for line in child.lines)
    else:
        assert child.smax.array[6] == 12.0
    assert math.isfinite(child.smax.array[8])
