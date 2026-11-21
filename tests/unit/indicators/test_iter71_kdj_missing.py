"""Independent rolling KDJ checks against complete source windows."""

import importlib.util
import math
from pathlib import Path
import sys

import backtrader as bt
import pandas as pd
import pytest
from backtrader.indicators.contrib.kdj_indicator import KDJIndicator

PERIOD, M1, M2 = 5, 2, 3
ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "backtrader").is_dir() and (parent / "tests" / "functional").is_dir()
)
STRATEGY = (
    ROOT
    / "tests/functional/strategies/mean_reversion/test_0239_0515_kdj_trading_system.py"
)


def data_frame(n=100, *, missing=None, freq="h"):
    close = [
        100 + math.sin(i * 0.43) * 4 + i * 0.03 + math.sin(i * 0.13) for i in range(n)
    ]
    high = [x + 1 + 0.2 * math.sin(i * 0.2) for i, x in enumerate(close)]
    low = [x - 1 - 0.1 * math.cos(i * 0.3) for i, x in enumerate(close)]
    frame = pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": [10.0] * n},
        index=pd.date_range("2024-01-01", periods=n, freq=freq),
    )
    if missing:
        field, index = missing
        frame.iloc[index, frame.columns.get_loc(field)] = math.nan
    return frame


def reference(data):
    size = len(data)
    result = {key: [math.nan] * size for key in ("rsv", "k", "d", "kdc")}
    for index in range(PERIOD + M2 + 1, size):
        highs = list(data.high.iloc[index - PERIOD + 1 : index + 1])
        lows = list(data.low.iloc[index - PERIOD + 1 : index + 1])
        close = data.close.iloc[index]
        if all(math.isfinite(v) for v in highs + lows + [close]):
            hi = max(highs)
            lo = min(lows)
            result["rsv"][index] = (close - lo) / (hi - lo) * 100 if hi != lo else 1.0
        rsv = result["rsv"][index - M1 + 1 : index + 1]
        result["k"][index] = sum(rsv) / M1
        k = result["k"][index - M2 + 1 : index + 1]
        result["d"][index] = sum(k) / M2
        result["kdc"][index] = result["k"][index] - result["d"][index]
    return result


def equal(actual, expected):
    assert len(actual) == len(expected)
    for i, (a, e) in enumerate(zip(actual, expected)):
        if math.isnan(e):
            assert math.isnan(a), (i, a, e)
        else:
            assert a == pytest.approx(e, rel=1e-11, abs=1e-11), (i, a, e)


def run_indicator(data, once, primary=None):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = KDJIndicator(self.datas[-1], kdj_period=PERIOD, m1=M1, m2=M2)

    c = bt.Cerebro(stdstats=False, runonce=once)
    if primary is not None:
        c.adddata(bt.feeds.PandasData(dataname=primary))
    c.adddata(bt.feeds.PandasData(dataname=data))
    c.addstrategy(Probe)
    return c.run()[0].ind


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize(
    "missing",
    [None, ("high", 60), ("low", 60), ("close", 60)],
    ids=["finite", "high", "low", "close"],
)
def test_complete_windows_and_recovery(once, missing):
    data = data_frame(missing=missing)
    indicator = run_indicator(data, once)
    assert indicator._minperiod == PERIOD + M2 + 2
    expected = reference(data)
    for name, values in expected.items():
        equal(list(getattr(indicator.lines, name).array), values)
    if missing:
        assert math.isfinite(indicator.kdc.array[75])


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
def test_second_feed_clock(once):
    data = data_frame(80, missing=("high", 60), freq="3h")
    indicator = run_indicator(data, once, primary=data_frame(240))
    for name, values in reference(data).items():
        equal(list(getattr(indicator.lines, name).array), values)


def load_strategy():
    spec = importlib.util.spec_from_file_location("public_kdj_strategy", STRATEGY)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.KDJTradingSystemStrategy


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
def test_real_strategy_does_not_sell_on_incomplete_signal_window(once):
    original = load_strategy()

    class Observed(original):
        def __init__(self):
            super().__init__()
            self.signal_orders = []

        def next(self):
            if len(self.data_h1) < 61:
                return
            super().next()

        def buy(self, *args, **kwargs):
            self.signal_orders.append((len(self.data_h1) - 1, "buy"))
            return super().buy(*args, **kwargs)

        def sell(self, *args, **kwargs):
            self.signal_orders.append((len(self.data_h1) - 1, "sell"))
            return super().sell(*args, **kwargs)

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(bt.feeds.PandasData(dataname=data_frame()))
    c.adddata(bt.feeds.PandasData(dataname=data_frame(missing=("high", 60))))
    c.addstrategy(Observed, kdj_period=PERIOD, m1=M1, m2=M2)
    strategy = c.run()[0]
    assert not [
        (index, side) for index, side in strategy.signal_orders if 60 <= index <= 64
    ]
    assert any(index >= 68 for index, _ in strategy.signal_orders)


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize(
    "length", [1, 9, 10, 14], ids=["one", "before", "first", "later"]
)
def test_short_history(once, length):
    data = data_frame(length)
    indicator = run_indicator(data, once)
    for name, values in reference(data).items():
        equal(list(getattr(indicator.lines, name).array), values)


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
def test_flat_window_preserves_existing_rsv_fallback(once):
    data = data_frame(40)
    for field in ("open", "high", "low", "close"):
        data.loc[:, field] = 100.0
    indicator = run_indicator(data, once)
    for name, values in reference(data).items():
        equal(list(getattr(indicator.lines, name).array), values)
    assert list(indicator.rsv.array[PERIOD + M2 + 1 :]) == [1.0] * (
        len(data) - PERIOD - M2 - 1
    )


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
def test_strict_context_missing_remains_missing_and_recovers(once):
    from backtrader.errors import FactorComputationContext

    data = data_frame(missing=("high", 60))

    class Probe(bt.Strategy):
        def __init__(self):
            self._factor_strict_context = FactorComputationContext("kdj", phase="next")
            self.ind = KDJIndicator(self.data, kdj_period=PERIOD, m1=M1, m2=M2)

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(bt.feeds.PandasData(dataname=data))
    c.addstrategy(Probe)
    indicator = c.run()[0].ind
    for name, values in reference(data).items():
        equal(list(getattr(indicator.lines, name).array), values)


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("output", ["rsv", "k", "d", "kdc"])
def test_real_factor_graph_rejects_finite_intermediate_overflow(once, output):
    from backtrader.errors import FactorComputationError
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    data = data_frame(30)
    data.index = data.index.tz_localize("UTC")
    data.loc[:, "high"] = 1e308
    data.loc[:, "low"] = -1e308
    data.loc[:, "close"] = 0.0
    index = data.index.rename("close_time")
    grid = pd.DataFrame({"open_time": index - pd.Timedelta(hours=1)}, index=index)
    research = ResearchSpec(
        grid=grid,
        start=index[0],
        end=index[-1],
        targets=("asset-0",),
        source_timezone="UTC",
        snapshot_id="kdj-oracle",
        price_basis="synthetic",
        calendar_id="hourly",
        frequency="1h",
        feed_time_kind="close_time",
        groups={"asset-0": "market"},
    )

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("high", "low", "close")
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = KDJIndicator(self.data, kdj_period=PERIOD, m1=M1, m2=M2)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = getattr(self.child.lines, output)[0]

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(align_to_grid(data, research, "asset-0").feed, name="asset-0")
    spec = FactorSpec(
        name="kdj",
        indicator=Factor,
        panel_line="factor",
        field_bindings={f: f"feed:target:{f}" for f in Factor.required_fields},
        mode="native",
    )
    c.addstrategy(FactorStrategy, research=research, factors={"kdj": spec})
    with pytest.raises(FactorComputationError):
        c.run(preload=True)


def test_replay_each_revision_uses_visible_complete_window():
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = KDJIndicator(self.data, kdj_period=PERIOD, m1=M1, m2=M2)
            self.rows = []

        def next(self):
            n = len(self.data)
            data = {
                field: list(getattr(self.data, field).get(size=n))
                for field in ("open", "high", "low", "close", "volume")
            }
            self.rows.append(
                (
                    n,
                    pd.DataFrame(data),
                    {
                        name: float(getattr(self.ind.lines, name)[0])
                        for name in ("rsv", "k", "d", "kdc")
                    },
                )
            )

    c = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    c.replaydata(
        bt.feeds.PandasData(
            dataname=data_frame(160, missing=("close", 80), freq="min")
        ),
        timeframe=bt.TimeFrame.Minutes,
        compression=5,
    )
    c.addstrategy(Probe)
    rows = c.run()[0].rows
    assert rows and any(a[0] == b[0] for a, b in zip(rows, rows[1:]))
    saw_missing = False
    for n, data, actual in rows:
        expected = reference(data)
        saw_missing |= math.isnan(expected["rsv"][-1])
        for name, value in actual.items():
            equal([value], [expected[name][-1]])
    assert saw_missing


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("m1", [1, 3], ids=["k-sum", "rsv-sum"])
@pytest.mark.parametrize("output", ["rsv", "k", "d", "kdc"])
def test_strict_overflow_cannot_be_masked_by_later_nan(once, m1, output):
    from backtrader.errors import FactorComputationError
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    index = pd.date_range(
        "2024-01-01", periods=23, freq="h", tz="UTC", name="close_time"
    )
    close = [0.5] * 23
    close[20] = math.nan
    close[21] = close[22] = 1e306
    data = pd.DataFrame(
        {
            "open": [0.5] * 23,
            "high": [1.0] * 23,
            "low": [0.0] * 23,
            "close": close,
            "volume": [1.0] * 23,
        },
        index=index,
    )
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(hours=1)}, index=index),
        start=index[0],
        end=index[-1],
        targets=("asset-0",),
        source_timezone="UTC",
        snapshot_id="kdj-masked-overflow",
        price_basis="synthetic",
        calendar_id="hourly",
        frequency="1h",
        feed_time_kind="close_time",
        groups={"asset-0": "market"},
    )

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("high", "low", "close")
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = KDJIndicator(self.data, kdj_period=3, m1=m1, m2=3)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = getattr(self.child.lines, output)[0]

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(align_to_grid(data, research, "asset-0").feed, name="asset-0")
    spec = FactorSpec(
        name="kdj",
        indicator=Factor,
        panel_line="factor",
        field_bindings={
            field: f"feed:target:{field}" for field in Factor.required_fields
        },
        mode="native",
    )
    c.addstrategy(FactorStrategy, research=research, factors={"kdj": spec})
    with pytest.raises(FactorComputationError) as caught:
        c.run(preload=True)
    assert isinstance(caught.value.__cause__, ArithmeticError)


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
def test_interpreter_native_sum_is_preserved_for_cancellation(once):
    data = data_frame(23)
    data.loc[:, "high"] = 1.0
    data.loc[:, "low"] = 0.0
    data.loc[:, "close"] = 0.5
    data.iloc[20, data.columns.get_loc("close")] = -1e14
    data.iloc[21, data.columns.get_loc("close")] = 0.01
    data.iloc[22, data.columns.get_loc("close")] = 1e14

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = KDJIndicator(self.data, kdj_period=3, m1=3, m2=3)

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(bt.feeds.PandasData(dataname=data))
    c.addstrategy(Probe)
    indicator = c.run()[0].ind
    assert indicator.k.array[-1] == sum([1e16, 1.0, -1e16]) / 3.0


def test_sum_uses_current_builtin_binding(monkeypatch):
    import builtins

    original = builtins.sum
    calls = []

    def replacement(values, *args):
        calls.append(tuple(values))
        return original(values, *args) + 7

    monkeypatch.setattr(builtins, "sum", replacement)
    assert KDJIndicator._sum_checked(None, [1.0, 2.0]) == 10.0
    assert calls == [(1.0, 2.0)]


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("strict", [False, True], ids=["ordinary", "strict"])
def test_finite_zero_range_does_not_evaluate_unused_numerator(once, strict):
    from backtrader.errors import FactorComputationContext

    data = data_frame(30)
    data.loc[:, "high"] = -1e308
    data.loc[:, "low"] = -1e308
    data.loc[:, "close"] = 1e308

    class Probe(bt.Strategy):
        def __init__(self):
            if strict:
                self._factor_strict_context = FactorComputationContext(
                    "kdj-flat", phase="next"
                )
            self.ind = KDJIndicator(self.data, kdj_period=3, m1=3, m2=3)

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(bt.feeds.PandasData(dataname=data))
    c.addstrategy(Probe)
    ind = c.run()[0].ind
    assert ind.rsv.array[-1] == 1.0 and ind.k.array[-1] == 1.0
    assert ind.d.array[-1] == 1.0 and ind.kdc.array[-1] == 0.0


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("output", ["rsv", "k", "d", "kdc"])
def test_factor_graph_finite_zero_range_keeps_original_fallback(once, output):
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    data = data_frame(30)
    data.index = data.index.tz_localize("UTC")
    data.loc[:, "high"] = -1e308
    data.loc[:, "low"] = -1e308
    data.loc[:, "close"] = 1e308
    index = data.index.rename("close_time")
    grid = pd.DataFrame({"open_time": index - pd.Timedelta(hours=1)}, index=index)
    research = ResearchSpec(
        grid=grid,
        start=index[0],
        end=index[-1],
        targets=("asset-0",),
        source_timezone="UTC",
        snapshot_id="kdj-flat-branch",
        price_basis="synthetic",
        calendar_id="hourly",
        frequency="1h",
        feed_time_kind="close_time",
        groups={"asset-0": "market"},
    )
    captured = []

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("high", "low", "close")
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = KDJIndicator(self.data, kdj_period=3, m1=3, m2=3)
            captured.append(self)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = getattr(self.child.lines, output)[0]

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(align_to_grid(data, research, "asset-0").feed, name="asset-0")
    spec = FactorSpec(
        name="kdj",
        indicator=Factor,
        panel_line="factor",
        field_bindings={f: f"feed:target:{f}" for f in Factor.required_fields},
        mode="native",
    )
    c.addstrategy(FactorStrategy, research=research, factors={"kdj": spec})
    c.run(preload=True)
    assert captured and getattr(captured[-1].child.lines, output).array[-1] == (
        0.0 if output == "kdc" else 1.0
    )
