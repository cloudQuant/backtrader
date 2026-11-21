"""GO and TPO formulas on complete OHLC windows and replay revisions.

GO's zero for non-finite input and both indicators' period-plus-one warmup are
observed existing behavior, rather than a claim about external signal quality.
"""

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.go_indicator import GOIndicator
from backtrader.indicators.contrib.j_tpo_proxy import JTpoProxy
from backtrader.errors import FactorComputationContext, FactorComputationError


def frame(n, freq="D", missing=False):
    close = [100 + i * 0.1 + 2 * math.sin(i * 0.7) + (i % 4) * 0.2 for i in range(n)]
    data = pd.DataFrame(
        {
            "open": [x + math.sin(i * 0.41) for i, x in enumerate(close)],
            "high": [x + 2 + i % 3 * 0.1 for i, x in enumerate(close)],
            "low": [x - 1 - i % 4 * 0.1 for i, x in enumerate(close)],
            "close": close,
            "volume": [20.0 + i % 9 for i in range(n)],
        },
        index=pd.date_range("2024-01-01", periods=n, freq=freq),
    )
    if missing and n > 20:
        data.iloc[18, data.columns.get_loc("high")] = math.nan
        data.iloc[19, data.columns.get_loc("close")] = math.nan
        data.iloc[23, data.columns.get_loc("volume")] = math.nan
    return data


def ma(values, p, method):
    out = [math.nan] * len(values)
    if method in ("SMA", "WMA"):
        for i in range(p - 1, len(values)):
            w = values[i - p + 1 : i + 1]
            out[i] = (
                sum(w) / p
                if method == "SMA"
                else sum((j + 1) * x for j, x in enumerate(w)) / (p * (p + 1) / 2)
            )
    elif len(values) >= p:
        out[p - 1] = sum(values[:p]) / p
        alpha = 2 / (p + 1) if method == "EMA" else 1 / p
        for i in range(p, len(values)):
            out[i] = out[i - 1] * (1 - alpha) + values[i] * alpha
    return out


def reference(data, p, kind, method="SMA"):
    values = {name: list(data[name]) for name in ("open", "high", "low", "close", "volume")}
    avg = {name: ma(values[name], p, method) for name in ("open", "high", "low", "close")}
    out = [math.nan] * len(data)
    for i in range(p, len(data)):
        if kind == "tpo":
            out[i] = values["close"][i] - avg["close"][i]
            continue
        o, h, l, c = (avg[name][i] for name in ("open", "high", "low", "close"))
        v = values["volume"][i]
        out[i] = 3.0 * (c - o) * v if all(math.isfinite(x) for x in (o, h, l, c, v)) else 0.0
    return out


def equal(actual, expected):
    assert len(actual) == len(expected)
    for i, (a, b) in enumerate(zip(actual, expected)):
        if math.isnan(b):
            assert math.isnan(a), i
        else:
            assert a == pytest.approx(b, rel=1e-10, abs=1e-10), i


def run(data, kind, once, method="SMA", primary=None, period=3):
    class Probe(bt.Strategy):
        def __init__(self):
            params = {} if period is None else {"period": period}
            self.ind = (
                GOIndicator(self.datas[-1], ma_method=method, **params)
                if kind == "go"
                else JTpoProxy(self.datas[-1], **params)
            )

    c = bt.Cerebro(stdstats=False, runonce=once, preload=True)
    if primary is not None:
        c.adddata(bt.feeds.PandasData(dataname=primary))
    c.adddata(bt.feeds.PandasData(dataname=data))
    c.addstrategy(Probe)
    return c.run()[0].ind


@pytest.mark.parametrize(
    "kind,method", [("go", "SMA"), ("go", "WMA"), ("go", "EMA"), ("go", "SMMA"), ("tpo", "SMA")]
)
@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("n,missing", [(2, False), (4, False), (50, False), (50, True)])
def test_reference(kind, method, once, n, missing):
    data = frame(n, missing=missing)
    ind = run(data, kind, once, method)
    assert ind._minperiod == 4
    equal(list(ind.lines[0].array), reference(data, 3, kind, method))


@pytest.mark.parametrize("kind", ["go", "tpo"])
@pytest.mark.parametrize("once", [False, True])
def test_secondary(kind, once):
    data = frame(40, freq="3D")
    ind = run(data, kind, once, primary=frame(120))
    equal(list(ind.lines[0].array), reference(data, 3, kind))


@pytest.mark.parametrize("kind,period", [("go", 174), ("tpo", 14)])
@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("extra", [-1, 0, 1, 26], ids=["short", "at-window", "first", "later"])
def test_default_period_boundary(kind, period, once, extra):
    data = frame(period + extra)
    ind = run(data, kind, once, period=None)
    assert ind._minperiod == period + 1
    equal(list(ind.lines[0].array), reference(data, period, kind))


@pytest.mark.parametrize("method", ["SMA", "WMA", "EMA", "SMMA"])
@pytest.mark.parametrize("secondary", [False, True], ids=["primary", "secondary"])
def test_go_subclass_next_override_runs_in_both_modes(method, secondary):
    class CustomGO(GOIndicator):
        def next(self):
            super().next()
            self.lines.go[0] += 7.0

    def run_custom(once):
        class Probe(bt.Strategy):
            def __init__(self):
                self.indicator = CustomGO(self.datas[-1], period=3, ma_method=method)

        cerebro = bt.Cerebro(stdstats=False, runonce=once)
        if secondary:
            cerebro.adddata(bt.feeds.PandasData(dataname=frame(75)))
        cerebro.adddata(bt.feeds.PandasData(dataname=frame(25, freq="3D" if secondary else "D")))
        cerebro.addstrategy(Probe)
        return list(cerebro.run()[0].indicator.go.array)

    expected = reference(frame(25), 3, "go", method)
    expected = [value + 7.0 for value in expected]
    equal(run_custom(False), expected)
    equal(run_custom(True), expected)


def test_go_subclass_warmup_callbacks_run_in_both_modes():
    class CustomGO(GOIndicator):
        def prenext(self):
            self.lines.go[0] = -9.0

        def nextstart(self):
            super().nextstart()
            self.lines.go[0] += 7.0

    def run_custom(once):
        class Probe(bt.Strategy):
            def __init__(self):
                self.indicator = CustomGO(self.data, period=3)

        cerebro = bt.Cerebro(stdstats=False, runonce=once)
        cerebro.adddata(bt.feeds.PandasData(dataname=frame(25)))
        cerebro.addstrategy(Probe)
        return list(cerebro.run()[0].indicator.go.array)

    expected = reference(frame(25), 3, "go")
    expected[:3] = [-9.0] * 3
    expected[3] += 7.0
    equal(run_custom(False), expected)
    equal(run_custom(True), expected)


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
def test_go_strict_context_rejects_result_overflow(once):
    data = frame(10)
    data.loc[:, "volume"] = 1e308

    class Probe(bt.Strategy):
        def __init__(self):
            self._factor_strict_context = FactorComputationContext("go", phase="next")
            self.indicator = GOIndicator(self.data, period=3)

    cerebro = bt.Cerebro(stdstats=False, runonce=once)
    cerebro.adddata(bt.feeds.PandasData(dataname=data))
    cerebro.addstrategy(Probe)
    with pytest.raises(FactorComputationError):
        cerebro.run()


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
def test_go_strict_context_rejects_intermediate_overflow(once):
    data = frame(10)
    data.loc[:, "open"] = -1e308
    data.loc[:, "high"] = 1e308
    data.loc[:, ["low", "close"]] = 0.0

    class Probe(bt.Strategy):
        def __init__(self):
            self._factor_strict_context = FactorComputationContext("go", phase="next")
            self.indicator = GOIndicator(self.data, period=1)

    cerebro = bt.Cerebro(stdstats=False, runonce=once)
    cerebro.adddata(bt.feeds.PandasData(dataname=data))
    cerebro.addstrategy(Probe)
    with pytest.raises(FactorComputationError):
        cerebro.run()


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
def test_go_strict_context_preserves_existing_missing_zero(once):
    data = frame(10)
    data.loc[:, "volume"] = math.nan

    class Probe(bt.Strategy):
        def __init__(self):
            self._factor_strict_context = FactorComputationContext("go", phase="next")
            self.indicator = GOIndicator(self.data, period=3)

    cerebro = bt.Cerebro(stdstats=False, runonce=once)
    cerebro.adddata(bt.feeds.PandasData(dataname=data))
    cerebro.addstrategy(Probe)
    values = list(cerebro.run()[0].indicator.go.array)
    assert values[3:] == [0.0] * 7


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
def test_go_strict_factor_graph_rejects_overflow(once):
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    from tests.unit.test_factor_research_representatives import (
        _frames,
        _research_feed,
        _research_spec,
    )

    data = _frames(periods=25)["asset-0"].copy()
    data.loc[:, "close"] = data["open"] + 1.0
    data.loc[:, "high"] = data["close"] + 1.0
    data.loc[:, "low"] = data["open"] - 1.0
    data.loc[:, "volume"] = 1e308
    research = _research_spec({"asset-0": data})

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("open", "high", "low", "close", "volume")
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = GOIndicator(self.data, period=3)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.go[0]

    cerebro = bt.Cerebro(stdstats=False, runonce=once)
    cerebro.adddata(_research_feed(data, research, "asset-0"), name="asset-0")
    spec = FactorSpec(
        name="go",
        indicator=Factor,
        panel_line="factor",
        field_bindings={field: f"feed:target:{field}" for field in Factor.required_fields},
        mode="native",
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"go": spec})
    with pytest.raises(FactorComputationError):
        cerebro.run(preload=True)


@pytest.mark.parametrize(
    "kind,method", [("go", "SMA"), ("go", "WMA"), ("go", "EMA"), ("go", "SMMA"), ("tpo", "SMA")]
)
@pytest.mark.parametrize("missing", [False, True], ids=["finite", "missing"])
def test_replay(kind, method, missing):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = (
                GOIndicator(self.data, period=3, ma_method=method)
                if kind == "go"
                else JTpoProxy(self.data, period=3)
            )
            self.rows = []

        def next(self):
            n = len(self.data)
            d = {
                name: list(getattr(self.data, name).get(size=n))
                for name in ("open", "high", "low", "close", "volume")
            }
            self.rows.append((n, pd.DataFrame(d), float(self.ind[0])))

    c = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    c.replaydata(
        bt.feeds.PandasData(dataname=frame(90, freq="min", missing=missing)),
        timeframe=bt.TimeFrame.Minutes,
        compression=5,
    )
    c.addstrategy(Probe)
    rows = c.run()[0].rows
    assert rows and any(a[0] == b[0] for a, b in zip(rows, rows[1:]))
    if missing:
        assert any(data.isna().any().any() for _, data, _ in rows)
    for n, data, value in rows:
        expected = reference(data, 3, kind, method)[-1]
        if math.isnan(expected):
            assert math.isnan(value), (n, data.iloc[-1])
        else:
            assert value == pytest.approx(expected, rel=1e-10, abs=1e-10), (n, data.iloc[-1])
