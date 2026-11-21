"""Independent SafeADX DX-like window and BreadAndButter2 missing-data checks."""
import importlib.util
import math
import random
import sys
from pathlib import Path

import pandas as pd
import pytest

import backtrader as bt
from backtrader.indicators.contrib.safe_adx import SafeADX

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "backtrader").is_dir())
STRATEGY = ROOT / "tests/functional/strategies/mean_reversion/test_0082_0262_breadandbutter2.py"


def frame(seed=3, count=80, missing=None):
    rng = random.Random(seed)
    close = []
    current = 100.0
    for _ in range(count):
        current += rng.uniform(-2.0, 2.0)
        close.append(current)
    data = pd.DataFrame(
        {
            "open": close,
            "high": [x + 1 for x in close],
            "low": [x - 1 for x in close],
            "close": close,
            "volume": [1.0] * count,
        },
        index=pd.date_range("2024-01-01", periods=count, freq="h"),
    )
    if missing:
        field, index = missing
        data.loc[data.index[index], field] = math.nan
    return data


def reference(data, period):
    out = [math.nan] * len(data)
    for i in range(period + 2, len(data)):
        pdm = mdm = tr = 0.0
        valid = True
        for k in range(period):
            j = i - k
            h0, h1 = float(data.high.iloc[j]), float(data.high.iloc[j - 1])
            l0, l1 = float(data.low.iloc[j]), float(data.low.iloc[j - 1])
            c1 = float(data.close.iloc[j - 1])
            if any(math.isnan(x) for x in (h0, h1, l0, l1, c1)):
                valid = False
                break
            up = h0 - h1
            down = l1 - l0
            pdm += up if up > down and up > 0 else 0.0
            mdm += down if down > up and down > 0 else 0.0
            tr += max(h0 - l0, abs(h0 - c1), abs(l0 - c1))
        if not valid:
            continue
        if tr <= 1e-12:
            out[i] = 0.0
            continue
        pdi, mdi = 100.0 * pdm / tr, 100.0 * mdm / tr
        out[i] = 0.0 if pdi + mdi <= 1e-12 else 100.0 * abs(pdi - mdi) / (pdi + mdi)
    return out


def run_indicator(data, period, once, exactbars=0):
    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = SafeADX(self.data, period=period)
            self.rows = []

        def next(self):
            self.rows.append((len(self.data) - 1, float(self.ind[0])))

    c = bt.Cerebro(stdstats=False, runonce=once, exactbars=exactbars, preload=not exactbars)
    c.adddata(bt.feeds.PandasData(dataname=data))
    c.addstrategy(Strategy)
    return c.run()[0]


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("period", [1, 3, 14])
@pytest.mark.parametrize("missing", [None, ("high", 40), ("low", 40), ("close", 40)])
def test_full_series_warmup_missing_and_recovery(once, period, missing):
    data = frame(missing=missing)
    s = run_indicator(data, period, once)
    assert s.ind._minperiod == period + 3
    for i, expected in enumerate(reference(data, period)):
        actual = s.ind.lines.adx.array[i]
        if math.isnan(expected):
            assert math.isnan(actual), (i, actual)
        else:
            assert actual == pytest.approx(expected, abs=1e-12, rel=1e-12)
    if missing and missing[0] == "close":
        assert math.isfinite(s.ind.lines.adx.array[40])  # current close is not read
        assert math.isnan(s.ind.lines.adx.array[41])
    if missing:
        assert math.isnan(s.ind.lines.adx.array[40 + period])
        assert math.isfinite(s.ind.lines.adx.array[41 + period])


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("period", [1, 3, 14])
def test_short_history_stays_unavailable(once, period):
    s = run_indicator(frame(count=period + 2), period, once)
    assert s.ind._minperiod == period + 3
    assert all(math.isnan(x) for x in s.ind.lines.adx.array)


def test_bounded_history_matches_formula_at_every_callback():
    data = frame(missing=("high", 40))
    s = run_indicator(data, 3, False, exactbars=1)
    expected = reference(data, 3)
    for i, value in s.rows:
        if math.isnan(expected[i]):
            assert math.isnan(value)
        else:
            assert value == pytest.approx(expected[i], abs=1e-12, rel=1e-12)


def strategy_run(seed, once):
    spec = importlib.util.spec_from_file_location("_safeadx_functional", STRATEGY)
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
            self.adx_rows = []

        def log(self, *args):
            pass

        def next(self):
            if len(self.data0_feed) >= self.p.adx_period + 3:
                self.adx_rows.append((len(self.data0_feed) - 1, float(self.adx[0])))
            super().next()

        def _submit_entry(self, side, reason):
            self.actions.append(
                (
                    len(self.data0_feed) - 1,
                    "entry",
                    side,
                    reason,
                    float(self.adx[0]),
                    float(self.adx[-1]),
                )
            )
            return super()._submit_entry(side, reason)

        def _submit_close(self, reason, reverse=None):
            self.actions.append(
                (
                    len(self.data0_feed) - 1,
                    "close",
                    reverse,
                    reason,
                    float(self.adx[0]),
                    float(self.adx[-1]),
                )
            )
            return super()._submit_close(reason, reverse)

        def notify_order(self, order):
            self.orders.append(
                (
                    len(self.data0_feed) - 1,
                    order.getstatusname(),
                    order.isbuy(),
                    float(order.executed.size),
                )
            )
            return super().notify_order(order)

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(bt.feeds.PandasData(dataname=frame(seed, missing=("high", 30))))
    c.addstrategy(Probe, adx_period=3, ama_period=3, stoploss_pips=0, takeprofit_pips=0)
    return c.run()[0]


@pytest.mark.parametrize("once", [False, True])
def test_real_strategy_does_not_enter_from_fabricated_previous_adx(once):
    s = strategy_run(3, once)
    assert math.isnan(dict(s.adx_rows)[33])
    assert not any(a[0] == 34 and a[1] == "entry" for a in s.actions)


@pytest.mark.parametrize("once", [False, True])
def test_real_strategy_defers_reversal_and_retains_executed_close(once):
    s = strategy_run(33, once)
    assert not any(30 <= a[0] <= 34 and a[1] == "entry" for a in s.actions)
    assert any(a[0] == 35 and a[1] == "entry" and a[3] == "reverse after close" for a in s.actions)
    assert any(o[0] == 31 and o[1] == "Completed" for o in s.orders)
    assert any(o[0] == 36 and o[1] == "Completed" for o in s.orders)


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("scenario", ["width", "trsum", "percent", "normal", "missing"])
def test_real_factor_strict_overflow_and_missing(once, scenario):
    from backtrader.errors import FactorComputationError
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    n = 30
    index = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC", name="close_time")
    if scenario == "width":
        high, low = [1e308] * n, [-1e308] * n
    elif scenario == "trsum":
        high, low = [9e307] * n, [0.0] * n
    elif scenario == "percent":
        high, low = [i * 1e306 for i in range(n)], [0.0] * n
    else:
        high, low = [102.0 + i * 0.2 for i in range(n)], [98.0 + i * 0.2 for i in range(n)]
    data = pd.DataFrame(
        {"open": [100.0] * n, "high": high, "low": low, "close": [100.0] * n, "volume": [10.0] * n},
        index=index,
    )
    if scenario == "missing":
        data.iloc[10, data.columns.get_loc("high")] = math.nan
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index),
        start=index[0],
        end=index[-1],
        targets=("asset",),
        source_timezone="UTC",
        snapshot_id="safeadx",
        price_basis="synthetic",
        calendar_id="synthetic",
        frequency="1session",
        feed_time_kind="close_time",
        groups={"asset": "market"},
    )

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("high", "low", "close")
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = SafeADX(self.data, period=3)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child[0]

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(align_to_grid(data, research, "asset").feed, name="asset")
    spec = FactorSpec(
        name="safeadx",
        indicator=Factor,
        panel_line="factor",
        field_bindings={f: f"feed:target:{f}" for f in Factor.required_fields},
        mode="native",
    )
    c.addstrategy(FactorStrategy, research=research, factors={"safeadx": spec})
    if scenario in ("width", "trsum", "percent"):
        with pytest.raises(FactorComputationError) as caught:
            c.run(preload=True)
        assert isinstance(caught.value.__cause__, ArithmeticError)
    else:
        strategy = c.run(preload=True)[0]
        child = strategy._factor_instances_by_name["safeadx"][0].child
        if scenario == "missing":
            assert math.isnan(child.array[13])
            assert math.isfinite(child.array[14])
        else:
            assert math.isfinite(child.array[13])


@pytest.mark.parametrize("once", [False, True])
def test_replay_revisions_match_direct_window_formula(once):
    data = frame(count=240)
    data.index = pd.date_range("2024-01-01", periods=len(data), freq="min")
    data.loc[data.index[90:110], "close"] = math.nan

    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = SafeADX(self.data, period=3)
            self.rows = []

        def next(self):
            required = []
            pdm = mdm = tr = 0.0
            for k in range(3):
                h0, h1 = float(self.data.high[-k]), float(self.data.high[-k - 1])
                l0, l1 = float(self.data.low[-k]), float(self.data.low[-k - 1])
                c1 = float(self.data.close[-k - 1])
                required.extend((h0, h1, l0, l1, c1))
                up = h0 - h1
                down = l1 - l0
                pdm += up if up > down and up > 0 else 0.0
                mdm += down if down > up and down > 0 else 0.0
                tr += max(h0 - l0, abs(h0 - c1), abs(l0 - c1))
            if any(math.isnan(v) for v in required):
                expected = math.nan
            elif tr <= 1e-12:
                expected = 0.0
            else:
                pdi, mdi = 100.0 * pdm / tr, 100.0 * mdm / tr
                expected = 0.0 if pdi + mdi <= 1e-12 else 100.0 * abs(pdi - mdi) / (pdi + mdi)
            value = float(self.ind[0])
            self.rows.append((len(self.data), value, expected))

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.replaydata(
        bt.feeds.PandasData(dataname=data, timeframe=bt.TimeFrame.Minutes),
        timeframe=bt.TimeFrame.Minutes,
        compression=10,
    )
    c.addstrategy(Strategy)
    rows = c.run()[0].rows
    assert any(rows[i][0] == rows[i - 1][0] for i in range(1, len(rows)))
    assert any(math.isnan(expected) for _, _, expected in rows)
    assert math.isfinite(rows[-1][2])
    for length, value, expected in rows:
        if math.isnan(expected):
            assert math.isnan(value), length
        else:
            assert value == pytest.approx(expected, abs=1e-12, rel=1e-12)


@pytest.mark.parametrize("once", [False, True])
def test_slow_secondary_feed_matches_its_own_window(once):
    primary = frame(seed=8, count=120)
    secondary = frame(seed=3, count=60, missing=("high", 20))
    secondary.index = primary.index[::2]

    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = SafeADX(self.datas[1], period=3)
            self.rows = []

        def next(self):
            self.rows.append((len(self.datas[1]) - 1, float(self.ind[0])))

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(bt.feeds.PandasData(dataname=primary))
    c.adddata(bt.feeds.PandasData(dataname=secondary))
    c.addstrategy(Strategy)
    rows = c.run()[0].rows
    expected = reference(secondary, 3)
    assert any(rows[i][0] == rows[i - 1][0] for i in range(1, len(rows)))
    for index, value in rows:
        if math.isnan(expected[index]):
            assert math.isnan(value), (index, value)
        else:
            assert value == pytest.approx(expected[index], rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize(
    "scenario,expected", [("width", 0.0), ("trsum", 0.0), ("percent", math.nan)]
)
def test_non_strict_overflow_preserves_original_behavior(once, scenario, expected):
    data = frame(count=30)
    if scenario == "width":
        data["high"], data["low"] = 1e308, -1e308
    elif scenario == "trsum":
        data["high"], data["low"] = 9e307, 0.0
    else:
        data["high"], data["low"] = [i * 1e306 for i in range(len(data))], 0.0
    data["close"] = 100.0
    actual = run_indicator(data, 3, once).ind.array[-1]
    if math.isnan(expected):
        assert math.isnan(actual)
    else:
        assert actual == expected
