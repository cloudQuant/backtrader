import math
import backtrader as bt
import pandas as pd
import pytest


def frame(count=60, missing=None):
    data = []
    for i in range(count):
        c = 100 + i * 0.1 + 3 * math.sin(i * 0.25)
        o = c + 0.6 * math.sin(i * 0.8)
        data.append([o, max(c, o) + 0.7, min(c, o) - 0.8, c, 100 + i])
    result = pd.DataFrame(
        data,
        columns=["open", "high", "low", "close", "volume"],
        index=pd.date_range("2024-01-01", periods=count, freq="min"),
    )
    if missing is not None:
        result.loc[result.index[20], missing] = math.nan
    return result


def ref(xs, p=8):
    values = [math.nan] * len(xs)
    if len(xs) < p:
        return values
    ema = sum(xs[:p]) / p
    alpha = 2 / (p + 1)
    for i in range(p - 1, len(xs)):
        if i > p - 1:
            ema = ema * (1 - alpha) + xs[i] * alpha
        if i < p + 1:
            continue
        sma = sum(xs[i - p + 1 : i + 1]) / p
        values[i] = 0.0 if sma == 0 else 100 * (ema / sma - 1)
    return values


def run(data, mode):
    class Probe(bt.Strategy):
        def __init__(self):
            self.momline = bt.indicators.AnchoredMomentumLine(self.data.close)
            self.candle = bt.indicators.AnchoredMomentumCandleIndicator(self.data)

    engine = bt.Cerebro(stdstats=False, preload=True, runonce=mode)
    engine.adddata(bt.feeds.PandasData(dataname=data))
    engine.addstrategy(Probe)
    return engine.run()[0]


def same(a, e):
    if math.isnan(e):
        assert math.isnan(a)
    else:
        assert a == pytest.approx(e, abs=1e-10, rel=1e-10)


@pytest.mark.parametrize("mode", [False, True])
def test_finite_independent_formula(mode):
    data = frame()
    s = run(data, mode)
    r = {k: ref(data[k].tolist()) for k in ("open", "high", "low", "close")}
    for i in range(len(data)):
        m = r["close"][i]
        same(s.momline.momentum.array[i], m)
        if i < 9:
            continue
        o, h, l, c = [r[k][i] for k in ("open", "high", "low", "close")]
        expected = (o, max(h, o, c), min(l, o, c), c, 2 if o < c else 0 if o > c else 1)
        for line, e in zip(s.candle.lines, expected):
            same(line.array[i], e)
        same(s.momline.zone.array[i], 2 if m > 0.025 else 0 if m < -0.025 else 1)


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_missing_does_not_create_finite_dependent_values(mode, field):
    s = run(frame(missing=field), mode)
    if field == "close":
        assert all(math.isnan(v) for v in s.momline.momentum.array[20:])
        assert all(math.isnan(v) for v in s.momline.zone.array[20:])
    if field in ("open", "close"):
        assert all(math.isnan(v) for v in s.candle.color.array[20:])
    else:
        assert all(math.isfinite(v) for v in s.candle.color.array[20:])
    if field in ("open", "close", "high"):
        assert all(math.isnan(v) for v in s.candle.a_high.array[20:])
    else:
        assert all(math.isfinite(v) for v in s.candle.a_high.array[20:])
    if field in ("open", "close", "low"):
        assert all(math.isnan(v) for v in s.candle.a_low.array[20:])
    else:
        assert all(math.isfinite(v) for v in s.candle.a_low.array[20:])


def test_single_feed_replay_each_revision_against_recursion():
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = bt.indicators.AnchoredMomentumLine(self.data.close)
            self.rows = []

        def next(self):
            prices = list(self.data.close.get(size=len(self.data)))
            self.rows.append(
                (len(self.data), prices, float(self.ind.momentum[0]), float(self.ind.zone[0]))
            )

    engine = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    engine.replaydata(
        bt.feeds.PandasData(dataname=frame(150)), timeframe=bt.TimeFrame.Minutes, compression=5
    )
    engine.addstrategy(Probe)
    rows = engine.run()[0].rows
    assert any(a[0] == b[0] for a, b in zip(rows, rows[1:]))
    for _, prices, value, zone in rows:
        expected = ref(prices)[-1]
        same(value, expected)
        same(zone, 2 if expected > 0.025 else 0 if expected < -0.025 else 1)


@pytest.mark.parametrize("mode", [False, True], ids=["next", "once"])
def test_zero_sma_does_not_mask_missing_recursive_ema(mode):
    data = frame()
    data.loc[:, "close"] = 0.0
    data.loc[data.index[20], "close"] = math.nan
    result = run(data, mode).momline
    assert result.momentum.array[19] == 0.0
    assert all(math.isnan(value) for value in result.momentum.array[20:])
    assert all(math.isnan(value) for value in result.zone.array[20:])


@pytest.mark.parametrize("missing_index", [61, 63])
def test_replay_missing_close_revision_restores_indicator(missing_index):
    data = frame(150)
    data.loc[data.index[missing_index], "close"] = math.nan

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = bt.indicators.AnchoredMomentumLine(self.data.close)
            self.rows = []

        def next(self):
            prices = list(self.data.close.get(size=len(self.data)))
            self.rows.append(
                (len(self.data), prices, float(self.ind.momentum[0]), float(self.ind.zone[0]))
            )

    engine = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    engine.replaydata(
        bt.feeds.PandasData(dataname=data), timeframe=bt.TimeFrame.Minutes, compression=5
    )
    engine.addstrategy(Probe)
    rows = engine.run()[0].rows
    invalid = [i for i, (_, prices, _, _) in enumerate(rows) if math.isnan(prices[-1])]
    assert len(invalid) == 1
    i = invalid[0]
    assert math.isnan(rows[i][2]) and math.isnan(rows[i][3])
    assert rows[i + 1][0] == rows[i][0]
    assert all(math.isfinite(v) for v in rows[i + 1][2:])
    for _, prices, value, zone in rows:
        expected = ref(prices)[-1]
        same(value, expected)
        same(
            zone,
            math.nan
            if not math.isfinite(expected)
            else 2
            if expected > 0.025
            else 0
            if expected < -0.025
            else 1,
        )


@pytest.mark.parametrize("mode", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("output", ["momentum", "zone"])
def test_strict_factor_context_preserves_missing_values(mode, output):
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    from tests.unit.test_factor_research_representatives import (
        _frames,
        _research_feed,
        _research_spec,
    )

    data = _frames(periods=35)["asset-0"].copy()
    data.loc[data.index[20], "close"] = math.nan
    research = _research_spec({"asset-0": data})
    instances = []

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.ind = bt.indicators.AnchoredMomentumLine(self.data.close)
            instances.append(self.ind)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = getattr(self.ind, output)[0]

    engine = bt.Cerebro(stdstats=False, runonce=mode)
    engine.adddata(_research_feed(data, research, "asset-0"), name="asset-0")
    spec = FactorSpec(
        name="anchored",
        indicator=Factor,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        mode="native",
    )
    engine.addstrategy(FactorStrategy, research=research, factors={"anchored": spec})
    engine.run(preload=True)
    assert all(math.isnan(v) for v in getattr(instances[0], output).array[20:])
