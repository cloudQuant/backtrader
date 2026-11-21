"""Blau CSI must distinguish missing operands from a finite zero range."""

import importlib.util
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

import backtrader as bt


def _frame(count=100, flat=False):
    opens = [100.0 if flat else 100.0 + i * 0.08 + math.sin(i * 0.31) for i in range(count)]
    return pd.DataFrame(
        {
            "open": opens,
            "high": [
                x if flat else x + 1.0 + 0.15 * math.sin(i * 0.23) for i, x in enumerate(opens)
            ],
            "low": [
                x if flat else x - 1.0 - 0.12 * math.cos(i * 0.19) for i, x in enumerate(opens)
            ],
            "close": [x if flat else x + 0.3 * math.sin(i * 0.43) for i, x in enumerate(opens)],
            "volume": [1.0] * count,
        },
        index=pd.date_range("2024-01-01", periods=count, freq="h"),
    )


def _ema(values, period):
    output = [math.nan] * len(values)
    first = next((i for i, value in enumerate(values) if math.isfinite(value)), len(values))
    seed = first + period - 1
    if seed >= len(values):
        return output
    output[seed] = math.fsum(values[first : seed + 1]) / period
    alpha = 2.0 / (period + 1.0)
    for index in range(seed + 1, len(values)):
        output[index] = alpha * values[index] + (1.0 - alpha) * output[index - 1]
    return output


def _reference(data, length, periods):
    momentum = [math.nan] * len(data)
    price_range = [math.nan] * len(data)
    for index in range(length - 1, len(data)):
        start = index - length + 1
        momentum[index] = float(data.close.iloc[index] - data.open.iloc[start])
        price_range[index] = float(data.high.iloc[start : index + 1].max()) - float(
            data.low.iloc[start : index + 1].min()
        )
    for period in periods:
        momentum = _ema(momentum, period)
        price_range = _ema(price_range, period)
    return [
        math.nan if math.isnan(a) or math.isnan(b) else (100.0 * a / b if b else 0.0)
        for a, b in zip(momentum, price_range)
    ]


def _run(data, once, length=1, periods=(4, 3, 2)):
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.ind.BlauCSI(
                self.data,
                xlength=length,
                xlength1=periods[0],
                xlength2=periods[1],
                xlength3=periods[2],
            )
            self.sma = bt.ind.SMA(self.indicator, period=2)

    engine = bt.Cerebro(stdstats=False, runonce=once)
    engine.adddata(bt.feeds.PandasData(dataname=data))
    engine.addstrategy(Probe)
    return engine.run()[0]


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize(
    "length,periods,flat",
    [(1, (4, 3, 2), False), (3, (4, 3, 2), False), (1, (20, 5, 3), False), (1, (4, 3, 2), True)],
)
def test_full_formula_and_warmup(once, length, periods, flat):
    data = _frame(flat=flat)
    result = _run(data, once, length, periods)
    required = length + sum(periods) - 3
    assert result.indicator._minperiod == required
    assert result.sma._minperiod == required + 1
    for actual, expected in zip(
        result.indicator.lines.main.array, _reference(data, length, periods)
    ):
        if math.isnan(expected):
            assert math.isnan(actual)
        else:
            assert actual == pytest.approx(expected, rel=1e-10, abs=1e-10)


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
@pytest.mark.parametrize("flat", [False, True])
def test_visible_missing_operand_is_not_zero(once, field, flat):
    data = _frame(count=30, flat=flat)
    data.iloc[14, data.columns.get_loc(field)] = math.nan
    indicator = _run(data, once, periods=(1, 1, 1)).indicator
    assert math.isnan(indicator.lines.main.array[14])
    if flat:
        assert indicator.lines.main.array[13] == 0.0


@pytest.mark.parametrize("once", [False, True])
def test_real_strategy_does_not_trade_on_missing_close(once):
    root = next(p for p in Path(__file__).resolve().parents if (p / "backtrader").is_dir())
    path = root / "tests/functional/strategies/mean_reversion/test_0305_1114_blau_csi.py"
    spec = importlib.util.spec_from_file_location("_iter71_blaucsi_strategy", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)

    class Probe(module.BlauCSIStrategy):
        def __init__(self):
            super().__init__()
            self.actions = []

        def sell(self, *args, **kwargs):
            self.actions.append(("sell", len(self.data) - 1))
            return super().sell(*args, **kwargs)

    data = _frame(count=90, flat=True)
    data["high"] = 101.0
    data["low"] = 99.0
    data["close"] = 99.5
    data.iloc[60, data.columns.get_loc("close")] = math.nan
    engine = bt.Cerebro(stdstats=False, runonce=once)
    engine.adddata(bt.feeds.PandasData(dataname=data))
    engine.addstrategy(Probe, mode="breakdown", stop_loss_points=0, take_profit_points=0)
    strategy = engine.run()[0]
    assert strategy.osc.main.array[59] == pytest.approx(-25.0)
    assert math.isnan(strategy.osc.main.array[60])
    assert strategy.actions == []


@pytest.mark.parametrize("once", [False, True])
def test_strict_factor_preserves_nan_even_if_range_is_zero(once):
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    data = _frame(count=30, flat=True)
    data.index = data.index.tz_localize("UTC").rename("close_time")
    data.iloc[14, data.columns.get_loc("close")] = math.nan
    index = data.index
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(hours=1)}, index=index),
        start=index[0],
        end=index[-1],
        targets=("asset",),
        source_timezone="UTC",
        snapshot_id="blau-csi-missing",
        price_basis="synthetic",
        calendar_id="synthetic",
        frequency="1h",
        feed_time_kind="close_time",
        groups={"asset": "market"},
    )
    seen = []

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("open", "high", "low", "close")
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = bt.ind.BlauCSI(self.data, xlength=1, xlength1=1, xlength2=1, xlength3=1)
            seen.append(self)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.main[0]

    engine = bt.Cerebro(stdstats=False, runonce=once)
    engine.adddata(align_to_grid(data, research, "asset").feed, name="asset")
    spec = FactorSpec(
        name="blau",
        indicator=Factor,
        panel_line="factor",
        field_bindings={field: f"feed:target:{field}" for field in Factor.required_fields},
        mode="native",
    )
    engine.addstrategy(FactorStrategy, research=research, factors={"blau": spec})
    engine.run(preload=True)
    assert seen[0].child.main.array[13] == 0.0
    assert math.isnan(seen[0].child.main.array[14])


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("missing", [False, True])
def test_slower_secondary_feed_matches_its_own_formula(once, missing):
    slow = _frame(count=40)
    slow.index = pd.date_range("2024-01-01", periods=len(slow), freq="D")
    if missing:
        slow.iloc[18, slow.columns.get_loc("close")] = math.nan
    fast = _frame(count=120)
    fast.index = pd.date_range("2024-01-01", periods=len(fast), freq="8h")

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.ind.BlauCSI(
                self.datas[1], xlength=1, xlength1=4, xlength2=3, xlength3=2
            )

    engine = bt.Cerebro(stdstats=False, runonce=once)
    engine.adddata(bt.feeds.PandasData(dataname=fast))
    engine.adddata(bt.feeds.PandasData(dataname=slow))
    engine.addstrategy(Probe)
    indicator = engine.run()[0].indicator
    for actual, expected in zip(indicator.lines.main.array, _reference(slow, 1, (4, 3, 2))):
        if math.isnan(expected):
            assert math.isnan(actual)
        else:
            assert actual == pytest.approx(expected, rel=1e-10, abs=1e-10)
