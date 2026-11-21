"""Vinin LRMA fan score and requested second smoothing on public synthetic data."""

import math
import backtrader as bt
import pandas as pd
import pytest
from backtrader.indicators.contrib.lrma_indicator import VininITrendLRMAIndicator

LR = 3
FAN = (3, 7, 11)
LENGTH = 5
MINIMUM = LR + max(FAN) + LENGTH + 5


def frame(n=120, missing=None, freq="D"):
    close = [
        100 + i * 0.05 + 3 * math.sin(i * 0.31) + 1.2 * math.cos(i * 0.11)
        for i in range(n)
    ]
    if missing is not None:
        close[missing] = math.nan
    return pd.DataFrame(
        {
            "open": close,
            "high": [x + 1 for x in close],
            "low": [x - 1 for x in close],
            "close": close,
            "volume": [1.0] * n,
        },
        index=pd.date_range("2024-01-01", periods=n, freq=freq),
    )


def reference(data, method, fan_method="sma"):
    values = list(data.close)
    n = len(values)
    lrma = [math.nan] * n
    x = range(LR)
    mean_x = sum(x) / LR
    den = sum((i - mean_x) ** 2 for i in x)
    for i in range(LR - 1, n):
        w = values[i - LR + 1 : i + 1]
        if all(math.isfinite(v) for v in w):
            y = sum(w) / LR
            slope = sum((j - mean_x) * (v - y) for j, v in enumerate(w)) / den
            lrma[i] = y + slope * (LR - 1 - mean_x)
    avgs = []
    for period in FAN:
        a = [math.nan] * n
        for i in range(LR + period - 2, n):
            w = lrma[i - period + 1 : i + 1]
            if fan_method in ("ema", "smma") and i > LR + period - 2:
                alpha = 2 / (period + 1) if fan_method == "ema" else 1 / period
                a[i] = (1 - alpha) * a[i - 1] + alpha * lrma[i]
            elif all(math.isfinite(v) for v in w):
                a[i] = (
                    sum((j + 1) * v for j, v in enumerate(w))
                    / (period * (period + 1) / 2)
                    if fan_method == "lwma"
                    else sum(w) / period
                )
        avgs.append(a)
    raw = [math.nan] * n
    for i in range(n):
        vals = [a[i] for a in avgs]
        if math.isfinite(lrma[i]) and all(math.isfinite(v) for v in vals):
            raw[i] = 100 * sum(1 if lrma[i] > v else -1 for v in vals) / len(vals)
    trend = [math.nan] * n
    for i in range(MINIMUM - 1, n):
        if not math.isfinite(raw[i]):
            continue
        if method in ("ema", "jjma"):
            prev = trend[i - 1] if i else math.nan
            if not math.isfinite(prev):
                prev = raw[i]
            trend[i] = (2 / (LENGTH + 1)) * raw[i] + (1 - 2 / (LENGTH + 1)) * prev
        elif method in ("sma", "lwma"):
            w = raw[i - LENGTH + 1 : i + 1]
            if len(w) == LENGTH and all(math.isfinite(x) for x in w):
                trend[i] = (
                    sum(w) / LENGTH
                    if method == "sma"
                    else sum((j + 1) * v for j, v in enumerate(w))
                    / (LENGTH * (LENGTH + 1) / 2)
                )
        elif method == "smma":
            prev = trend[i - 1] if i else math.nan
            if math.isfinite(prev):
                trend[i] = (prev * (LENGTH - 1) + raw[i]) / LENGTH
            else:
                w = raw[i - LENGTH + 1 : i + 1]
                if len(w) == LENGTH and all(math.isfinite(x) for x in w):
                    trend[i] = sum(w) / LENGTH
    return raw, trend


def equal(actual, expected):
    assert len(actual) == len(expected)
    for i, (a, e) in enumerate(zip(actual, expected)):
        if math.isnan(e):
            assert math.isnan(a), (i, a, e)
        else:
            assert a == pytest.approx(e, rel=1e-10, abs=1e-10), (i, a, e)


def run(
    data, method, once, *, primary=None, length=LENGTH, phase=100, fan_method="sma"
):
    class S(bt.Strategy):
        def __init__(self):
            self.ind = VininITrendLRMAIndicator(
                self.datas[-1],
                lrma_period=LR,
                length1=3,
                ma_step=4,
                ma_count=3,
                ma_method1=fan_method,
                length2=length,
                ma_method2=method,
                phase2=phase,
            )

    c = bt.Cerebro(stdstats=False, runonce=once)
    if primary is not None:
        c.adddata(bt.feeds.PandasData(dataname=primary))
    c.adddata(bt.feeds.PandasData(dataname=data))
    c.addstrategy(S)
    return c.run()[0].ind


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("method", ["jjma", "ema", "sma", "smma", "lwma"])
@pytest.mark.parametrize("missing", [None, 60], ids=["finite", "gap"])
def test_score_smoothing_and_recovery(method, once, missing):
    data = frame(missing=missing)
    indicator = run(data, method, once)
    assert indicator._minperiod == MINIMUM
    _, expected = reference(data, method)
    equal(list(indicator.trend.array), expected)
    assert math.isfinite(indicator.trend.array[-1])


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
def test_methods_are_not_all_default_ema(once):
    data = frame()
    out = {
        m: list(run(data, m, once).trend.array)
        for m in ("jjma", "ema", "sma", "smma", "lwma")
    }
    equal(out["jjma"], out["ema"])
    for method in ("sma", "smma", "lwma"):
        assert any(
            math.isfinite(a) and math.isfinite(b) and abs(a - b) > 1e-8
            for a, b in zip(out["ema"], out[method])
        )


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("method", ["jjma", "ema", "sma", "smma", "lwma"])
def test_factor_graph_rejects_finite_lrma_intermediate_overflow(once, method):
    from backtrader.errors import FactorComputationError
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    data = frame(60)
    data.index = data.index.tz_localize("UTC")
    for field in ("open", "high", "low", "close"):
        data.loc[:, field] = 1e308
    index = data.index.rename("close_time")
    grid = pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index)
    research = ResearchSpec(
        grid=grid,
        start=index[0],
        end=index[-1],
        targets=("asset",),
        source_timezone="UTC",
        snapshot_id="vinin-lrma-strict",
        price_basis="synthetic",
        calendar_id="daily",
        frequency="1session",
        feed_time_kind="close_time",
        groups={"asset": "market"},
    )

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = VininITrendLRMAIndicator(
                self.data,
                lrma_period=LR,
                length1=3,
                ma_step=4,
                ma_count=3,
                length2=LENGTH,
                ma_method2=method,
            )

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.trend[0]

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(align_to_grid(data, research, "asset").feed, name="asset")
    spec = FactorSpec(
        name="vinin",
        indicator=Factor,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        mode="native",
    )
    c.addstrategy(FactorStrategy, research=research, factors={"vinin": spec})
    with pytest.raises(FactorComputationError):
        c.run(preload=True)


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize(
    "name,method",
    [
        ("SMA", "sma"),
        ("mode_sma", "sma"),
        ("SMMA", "smma"),
        ("mode_smma", "smma"),
        ("LWMA", "lwma"),
        ("mode_lwma", "lwma"),
        ("WMA", "lwma"),
        ("EMA", "ema"),
        ("mode_ema", "ema"),
    ],
)
def test_classic_method_aliases(once, name, method):
    data = frame()
    ind = run(data, name, once)
    equal(list(ind.trend.array), reference(data, method)[1])


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("name", ["jjma", "t3", "ama", "vidya", "unrecognised"])
def test_legacy_other_names_keep_existing_ema_proxy(once, name):
    data = frame()
    ind = run(data, name, once)
    equal(list(ind.trend.array), reference(data, "ema")[1])


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("method", ["jjma", "ema", "sma", "smma", "lwma"])
def test_unit_smoothing_period_is_raw_score(once, method):
    data = frame()
    ind = run(data, method, once, length=1)
    assert ind._minperiod == LR + max(FAN) + 1 + 5
    raw, _ = reference(data, "ema")
    expected = [math.nan] * (LR + max(FAN) + 1 + 5 - 1) + raw[
        LR + max(FAN) + 1 + 5 - 1 :
    ]
    equal(list(ind.trend.array), expected)


@pytest.mark.parametrize(
    "method,once",
    [("jjma", False)]
    + [
        pytest.param(
            "jjma",
            True,
            marks=pytest.mark.xfail(
                strict=True, reason="existing default secondary-clock recovery mismatch"
            ),
        )
    ]
    + [(method, once) for method in ("sma", "smma", "lwma") for once in (False, True)],
)
def test_secondary_feed_clock(once, method):
    data = frame(80, missing=40, freq="3D")
    ind = run(data, method, once, primary=frame(240))
    equal(list(ind.trend.array), reference(data, method)[1])


@pytest.mark.parametrize("method", ["jjma", "ema", "sma", "smma", "lwma"])
def test_replay_each_revision_matches_reference(method):
    class S(bt.Strategy):
        def __init__(self):
            self.ind = VininITrendLRMAIndicator(
                self.data,
                lrma_period=LR,
                length1=3,
                ma_step=4,
                ma_count=3,
                length2=LENGTH,
                ma_method2=method,
            )
            self.rows = []

        def next(self):
            n = len(self.data)
            values = list(self.data.close.get(size=n))
            self.rows.append((n, values, float(self.ind.trend[0])))

    c = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    c.replaydata(
        bt.feeds.PandasData(dataname=frame(300, missing=200, freq="min")),
        timeframe=bt.TimeFrame.Minutes,
        compression=5,
    )
    c.addstrategy(S)
    rows = c.run()[0].rows
    assert rows and any(a[0] == b[0] for a, b in zip(rows, rows[1:]))
    saw_missing = False
    for _, values, actual in rows:
        expected = reference(pd.DataFrame({"close": values}), method)[1][-1]
        if math.isnan(expected):
            saw_missing = True
            assert math.isnan(actual)
        else:
            assert actual == pytest.approx(expected, rel=1e-10, abs=1e-10)
    assert saw_missing


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("method", ["sma", "smma", "lwma"])
@pytest.mark.parametrize("fan_method", ["sma", "ema", "smma", "lwma"])
@pytest.mark.parametrize("secondary", [False, True], ids=["single", "secondary"])
def test_nondefault_smoothing_with_each_classic_fan(
    once, method, fan_method, secondary
):
    data = frame(80, freq="3D" if secondary else "D")
    ind = run(
        data,
        method,
        once,
        fan_method=fan_method,
        primary=frame(240) if secondary else None,
    )
    equal(list(ind.trend.array), reference(data, method, fan_method)[1])


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("method", ["jjma", "ema", "sma", "smma", "lwma"])
@pytest.mark.parametrize(
    "count", [MINIMUM - 1, MINIMUM, MINIMUM + 2], ids=["before", "first", "later"]
)
def test_warmup_boundaries(once, method, count):
    data = frame(count)
    ind = run(data, method, once)
    assert ind._minperiod == MINIMUM
    equal(list(ind.trend.array), reference(data, method)[1])


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("method", ["jjma", "ema", "sma", "smma", "lwma"])
def test_factor_graph_allows_missing_and_recovers(once, method):
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    data = frame(120, missing=60)
    data.index = data.index.tz_localize("UTC")
    index = data.index.rename("close_time")
    grid = pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index)
    research = ResearchSpec(
        grid=grid,
        start=index[0],
        end=index[-1],
        targets=("asset",),
        source_timezone="UTC",
        snapshot_id="vinin-lrma-gap",
        price_basis="synthetic",
        calendar_id="daily",
        frequency="1session",
        feed_time_kind="close_time",
        groups={"asset": "market"},
    )
    captured = []

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = VininITrendLRMAIndicator(
                self.data,
                lrma_period=LR,
                length1=3,
                ma_step=4,
                ma_count=3,
                length2=LENGTH,
                ma_method2=method,
            )
            captured.append(self)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.trend[0]

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(align_to_grid(data, research, "asset").feed, name="asset")
    spec = FactorSpec(
        name="vinin",
        indicator=Factor,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        mode="native",
    )
    c.addstrategy(FactorStrategy, research=research, factors={"vinin": spec})
    c.run(preload=True)
    assert captured
    equal(list(captured[-1].child.trend.array), reference(data, method)[1])


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("missing", [None, 20], ids=["finite", "gap"])
def test_standalone_lrma_formula_and_missing_recovery(once, missing):
    from backtrader.indicators.contrib.lrma_indicator import LRMAIndicator

    data = frame(50, missing=missing)
    values = list(data.close)
    expected = [math.nan] * len(values)
    mx = sum(range(LR)) / LR
    den = sum((i - mx) ** 2 for i in range(LR))
    for i in range(LR - 1, len(values)):
        w = values[i - LR + 1 : i + 1]
        if all(math.isfinite(v) for v in w):
            mean = sum(w) / LR
            slope = sum((j - mx) * (v - mean) for j, v in enumerate(w)) / den
            expected[i] = mean + slope * (LR - 1 - mx)

    class S(bt.Strategy):
        def __init__(self):
            self.ind = LRMAIndicator(self.data.close, period=LR)

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(bt.feeds.PandasData(dataname=data))
    c.addstrategy(S)
    equal(list(c.run()[0].ind.lrma.array), expected)


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("primary", [False, True])
@pytest.mark.parametrize(
    "initial,replacement",
    [
        ("jjma", "sma"),
        ("jjma", "smma"),
        ("jjma", "lwma"),
        ("sma", "smma"),
        ("smma", "lwma"),
        ("lwma", "jjma"),
    ],
)
def test_secondary_method_is_selected_at_construction(
    runonce, primary, initial, replacement
):
    def frame(count, freq):
        values = [
            100 + i * 0.05 + 3 * math.sin(i * 0.31) + 1.2 * math.cos(i * 0.11)
            for i in range(count)
        ]
        return pd.DataFrame(
            {
                "open": values,
                "high": [v + 1 for v in values],
                "low": [v - 1 for v in values],
                "close": values,
                "volume": [1.0] * count,
            },
            index=pd.date_range("2024-01-01", periods=count, freq=freq),
        )

    class Strategy(bt.Strategy):
        params = (("switch", False),)

        def __init__(self):
            self.ind = bt.ind.VininITrendLRMAIndicator(
                self.datas[-1],
                lrma_period=3,
                length1=3,
                ma_step=4,
                ma_count=3,
                length2=5,
                ma_method1="sma",
                ma_method2=initial,
            )
            self.switched = False

        def next(self):
            if self.p.switch and not self.switched and len(self.datas[-1]) >= 31:
                self.ind.p.ma_method2 = replacement
                self.switched = True

    def run(switch):
        engine = bt.Cerebro(stdstats=False, runonce=runonce)
        if primary:
            engine.adddata(bt.feeds.PandasData(dataname=frame(240, "D")))
        engine.adddata(bt.feeds.PandasData(dataname=frame(80, "3D")))
        engine.addstrategy(Strategy, switch=switch)
        result = engine.run()[0]
        if switch:
            assert result.switched
        return list(result.ind.trend.array)

    assert run(True) == pytest.approx(run(False), rel=1e-10, abs=1e-10, nan_ok=True)
