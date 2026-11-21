"""SafeAMA reference, missing recovery, replay revisions and strict overflow."""
import math

import numpy as np
import pandas as pd
import pytest

import backtrader as bt
from backtrader.indicators.contrib.safe_adx import SafeAMA


def data(count=100, missing=None):
    values = [100.0 + math.sin(i * 0.19) * 3.0 + i * 0.03 for i in range(count)]
    f = pd.DataFrame(
        {
            "open": values,
            "high": [x + 1 for x in values],
            "low": [x - 1 for x in values],
            "close": values,
            "volume": [1.0] * count,
        },
        index=pd.date_range("2024-01-01", periods=count, freq="h"),
    )
    if missing is not None:
        for i in missing:
            f.iloc[i, f.columns.get_loc("close")] = math.nan
    return f


def calculate(data, period, state, fast_period=2, slow_period=30):
    prev, recovering = state
    price = float(data[0])
    if math.isnan(price):
        return math.nan, (None, True)
    if prev is None:
        if recovering and any(math.isnan(float(data[-k])) for k in range(1, period + 1)):
            return math.nan, (None, True)
        return price, (price, False)
    past = float(data[-period])
    if math.isnan(past):
        return math.nan, (None, True)
    direction = abs(price - past)
    volatility = 0.0
    for k in range(period):
        left, right = float(data[-k]), float(data[-k - 1])
        if math.isnan(left) or math.isnan(right):
            return math.nan, (None, True)
        volatility += abs(left - right)
    er = 0.0 if volatility <= 1e-12 else direction / volatility
    fast = 2.0 / (fast_period + 1.0)
    slow = 2.0 / (slow_period + 1.0)
    smoothing = (er * (fast - slow) + slow) ** 2
    current = prev + smoothing * (price - prev)
    return current, (current, False)


def reference(values, period, fast_period=2, slow_period=30):
    out = [math.nan] * len(values)
    state = (None, False)
    for i in range(period + 2, len(values)):
        value, state = calculate(
            {-k: values[i - k] for k in range(period + 1)}, period, state, fast_period, slow_period
        )
        out[i] = value
    return out


def run(data, period, once, exactbars=0, fast_period=2, slow_period=30):
    class S(bt.Strategy):
        def __init__(self):
            self.ind = SafeAMA(
                self.data, period=period, fast_period=fast_period, slow_period=slow_period
            )
            self.rows = []

        def next(self):
            self.rows.append((len(self.data) - 1, float(self.ind[0])))

    c = bt.Cerebro(stdstats=False, runonce=once, exactbars=exactbars, preload=not exactbars)
    c.adddata(bt.feeds.PandasData(dataname=data))
    c.addstrategy(S)
    return c.run()[0]


@pytest.mark.parametrize("period", [1, 3, 14])
@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("missing", ["none", "later", "first", "prior_seed"])
def test_formula_minperiod_seed_missing_and_recovery(period, once, missing):
    index = {"none": None, "later": [40], "first": [period + 2], "prior_seed": [period + 1]}[
        missing
    ]
    f = data(missing=index)
    s = run(f, period, once)
    expected = reference(list(f.close), period)
    assert s.ind._minperiod == period + 3
    for i, (actual, want) in enumerate(zip(s.ind.array, expected)):
        if math.isnan(want):
            assert math.isnan(actual), (i, actual)
        else:
            assert actual == pytest.approx(want, rel=1e-12, abs=1e-12), (i, actual, want)
    if missing == "later":
        assert all(math.isnan(v) for v in s.ind.array[40 : 41 + period])
        assert s.ind.array[41 + period] == f.close.iloc[41 + period]


@pytest.mark.parametrize("period", [1, 3, 14])
@pytest.mark.parametrize("once", [False, True])
def test_short_history_stays_unavailable(period, once):
    s = run(data(count=period + 2), period, once)
    assert s.ind._minperiod == period + 3
    assert all(math.isnan(v) for v in s.ind.array)


def test_exactbars_matches_independent_reference_after_missing():
    f = data(missing=[40])
    s = run(f, 3, False, exactbars=1)
    expected = reference(list(f.close), 3)
    for i, actual in s.rows:
        if math.isnan(expected[i]):
            assert math.isnan(actual)
        else:
            assert actual == pytest.approx(expected[i], rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("once", [False, True])
def test_replay_revisions_use_prebar_state_and_recover(once):
    f = data(count=240, missing=[90, 91, 92, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105])
    f.index = pd.date_range("2024-01-01", periods=len(f), freq="min")

    class S(bt.Strategy):
        def __init__(self):
            self.ind = SafeAMA(self.data, period=3)
            self.state = (None, False)
            self.before = None
            self.bar = None
            self.rows = []

        def next(self):
            n = len(self.data)
            if n != self.bar:
                self.bar = n
                self.before = self.state
            values = {-k: float(self.data.close[-k]) for k in range(4)}
            expected, self.state = calculate(values, 3, self.before)
            self.rows.append((n, float(self.ind[0]), expected))

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.replaydata(
        bt.feeds.PandasData(dataname=f, timeframe=bt.TimeFrame.Minutes),
        timeframe=bt.TimeFrame.Minutes,
        compression=5,
    )
    c.addstrategy(S)
    rows = c.run()[0].rows
    assert any(rows[i][0] == rows[i - 1][0] for i in range(1, len(rows)))
    assert any(math.isnan(w) for _, _, w in rows) and math.isfinite(rows[-1][2])
    for n, actual, want in rows:
        if math.isnan(want):
            assert math.isnan(actual), (n, actual, want)
        else:
            assert actual == pytest.approx(want, rel=1e-12, abs=1e-12), (n, actual, want)


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize(
    "scenario",
    [
        "direction",
        "volatility",
        "normal",
        "missing",
        "np64_fast",
        "np32_fast",
        "np64_slow",
        "np32_slow",
    ],
)
def test_factor_strict_overflow_and_recovery(once, scenario):
    from backtrader.errors import FactorComputationError
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    n = 30
    index = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC", name="close_time")
    if scenario == "direction":
        values = [1e308 if i % 2 else -1e308 for i in range(n)]
    elif scenario == "volatility":
        values = [9e307 if i % 2 else 0.0 for i in range(n)]
    else:
        values = [100.0 + i * 0.1 for i in range(n)]
    if scenario == "missing":
        values[10] = math.nan
    f = pd.DataFrame(
        {"open": values, "high": values, "low": values, "close": values, "volume": [1.0] * n},
        index=index,
    )
    spec = ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(hours=1)}, index=index),
        start=index[0],
        end=index[-1],
        targets=("asset",),
        source_timezone="UTC",
        snapshot_id="safeama",
        price_basis="synthetic",
        calendar_id="hourly",
        frequency="1h",
        feed_time_kind="close_time",
        groups={"asset": "market"},
    )

    class F(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            kwargs = {}
            if scenario.startswith("np64_"):
                kwargs[scenario.split("_")[1] + "_period"] = np.float64("inf")
            if scenario.startswith("np32_"):
                kwargs[scenario.split("_")[1] + "_period"] = np.float32("inf")
            self.child = SafeAMA(self.data, period=3, **kwargs)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child[0]

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(align_to_grid(f, spec, "asset").feed, name="asset")
    fs = FactorSpec(
        name="safeama",
        indicator=F,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        mode="native",
    )
    c.addstrategy(FactorStrategy, research=spec, factors={"safeama": fs})
    if scenario in ("direction", "volatility") or scenario.startswith("np"):
        with pytest.raises(FactorComputationError) as caught:
            c.run(preload=True)
        assert isinstance(caught.value.__cause__, ArithmeticError)
    else:
        s = c.run(preload=True)[0]
        line = s._factor_instances_by_name["safeama"][0].child.array
        if scenario == "missing":
            assert all(math.isnan(x) for x in line[10:14])
            assert line[14] == values[14]
        else:
            assert math.isfinite(line[-1])


@pytest.mark.parametrize("once", [False, True])
def test_nonstrict_finite_extreme_retains_legacy_sequence(once):
    f = data(count=20)
    values = [1e308 if i % 2 else -1e308 for i in range(20)]
    for col in ("open", "high", "low", "close"):
        f[col] = values
    s = run(f, 3, once)
    assert s.ind.array[5] == 1e308
    assert all(math.isnan(v) for v in s.ind.array[6:])


def test_write_failure_keeps_prior_bar_and_recovery_state(monkeypatch):
    s = run(data(), 3, False)
    ind = s.ind
    line = ind.lines.ama
    old_state = (ind._prev, ind._ama_recovering, ind._ama_source_length, ind._ama_prior_state)
    s.data.forward()
    s.data.close[0] = math.nan
    line_type = type(line)
    original = line_type.__setitem__

    def fail(target, ago, value):
        if target is line:
            raise RuntimeError("output write failed")
        return original(target, ago, value)

    monkeypatch.setattr(line_type, "__setitem__", fail)
    with pytest.raises(RuntimeError, match="output write failed"):
        ind.next()
    assert (
        ind._prev,
        ind._ama_recovering,
        ind._ama_source_length,
        ind._ama_prior_state,
    ) == old_state
    monkeypatch.setattr(line_type, "__setitem__", original)
    ind.next()
    assert ind._prev is None and ind._ama_recovering is True
    assert math.isnan(line[0])


@pytest.mark.parametrize("once", [False, True])
def test_slow_secondary_feed_repeated_master_callbacks_use_one_source_bar(once):
    primary = data(count=120)
    secondary = data(count=60, missing=[25])
    secondary.index = primary.index[::2]
    expected = reference(list(secondary.close), 3)

    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = SafeAMA(self.datas[1], period=3)
            self.rows = []

        def next(self):
            self.rows.append((len(self.datas[1]) - 1, float(self.ind[0])))

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(bt.feeds.PandasData(dataname=primary))
    c.adddata(bt.feeds.PandasData(dataname=secondary))
    c.addstrategy(Strategy)
    rows = c.run()[0].rows
    assert any(rows[i][0] == rows[i - 1][0] for i in range(1, len(rows)))
    for i, actual in rows:
        if math.isnan(expected[i]):
            assert math.isnan(actual), (i, actual)
        else:
            assert actual == pytest.approx(expected[i], rel=1e-12, abs=1e-12), (
                i,
                actual,
                expected[i],
            )


@pytest.mark.parametrize("once", [False, True])
def test_real_strategy_close_missing_defers_and_then_executes_reverse(once):
    import importlib.util
    import random
    import sys
    from pathlib import Path

    root = next(p for p in Path(__file__).resolve().parents if (p / "backtrader").is_dir())
    path = root / "tests/functional/strategies/mean_reversion/test_0082_0262_breadandbutter2.py"
    spec = importlib.util.spec_from_file_location("_safeama_bread", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(spec.name, None)

    class Probe(mod.BreadAndButter2Strategy):
        def __init__(self):
            super().__init__()
            self.actions = []
            self.orders = []
            self.pending_rows = []

        def log(self, *args):
            pass

        def next(self):
            super().next()
            self.pending_rows.append((len(self.data0_feed) - 1, self.pending_reverse))

        def _submit_entry(self, side, reason):
            self.actions.append((len(self.data0_feed) - 1, "entry", side, reason))
            return super()._submit_entry(side, reason)

        def _submit_close(self, reason, reverse=None):
            self.actions.append((len(self.data0_feed) - 1, "close", reverse, reason))
            return super()._submit_close(reason, reverse)

        def notify_order(self, o):
            self.orders.append(
                (len(self.data0_feed) - 1, o.getstatusname(), o.isbuy(), float(o.executed.size))
            )
            return super().notify_order(o)

    rng = random.Random(33)
    current = 100.0
    prices = []
    for _ in range(80):
        current += rng.uniform(-2, 2)
        prices.append(current)
    close = prices.copy()
    close[30] = math.nan
    f = pd.DataFrame(
        {
            "open": prices,
            "high": [x + 1 for x in prices],
            "low": [x - 1 for x in prices],
            "close": close,
            "volume": [1.0] * 80,
        },
        index=pd.date_range("2024-01-01", periods=80, freq="h"),
    )
    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(bt.feeds.PandasData(dataname=f))
    c.addstrategy(Probe, adx_period=3, ama_period=3, stoploss_pips=0, takeprofit_pips=0)
    s = c.run()[0]
    assert any(a[0] == 29 and a[1] == "close" for a in s.actions)
    assert any(o[0] == 31 and o[1] == "Completed" for o in s.orders)
    assert all(dict(s.pending_rows)[i] == "long" for i in (31, 32, 33, 34))
    assert not any(30 <= a[0] <= 34 and a[1] == "entry" for a in s.actions)
    assert any(a[0] == 35 and a[1] == "entry" and a[3] == "reverse after close" for a in s.actions)
    assert any(o[0] == 36 and o[1] == "Completed" and o[2] and o[3] > 0 for o in s.orders)


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("fast_period,slow_period", [(1, 5), (5, 20)])
def test_nondefault_smoothing_matches_independent_formula(once, fast_period, slow_period):
    f = data(missing=[40])
    s = run(f, 3, once, fast_period=fast_period, slow_period=slow_period)
    expected = reference(list(f.close), 3, fast_period, slow_period)
    for i, (actual, want) in enumerate(zip(s.ind.array, expected)):
        if math.isnan(want):
            assert math.isnan(actual), (i, actual)
        else:
            assert actual == pytest.approx(want, rel=1e-12, abs=1e-12), (i, actual, want)
