import math

import pandas as pd
import pytest

import backtrader as bt

PERIOD = 4


def frame(n=130, missing=None):
    rows = []
    for i in range(n):
        c = 100 + 2 * math.sin(i * 0.43) + math.sin(i * 0.11)
        o = c + 1.2 * math.sin(i * 0.67)
        rows.append(
            [
                o,
                max(o, c) + 0.4 + (i % 3) * 0.05,
                min(o, c) - 0.4 - (i % 4) * 0.04,
                c,
                100.0,
            ]
        )
    data = pd.DataFrame(
        rows,
        columns=["open", "high", "low", "close", "volume"],
        index=pd.date_range("2024-01-01", periods=n, freq="min"),
    )
    if missing:
        data.loc[data.index[45], missing] = math.nan
    return data


def step(prior, opens, highs, lows, closes):
    values = [opens[-1], closes[-1], *highs[-PERIOD:], *lows[-PERIOD:]]
    if not all(math.isfinite(x) for x in values):
        return prior, math.nan
    o, c = opens[-1], closes[-1]
    hi = max(highs[-PERIOD:])
    lo = min(lows[-PERIOD:])
    threshold = (hi - lo) * 0.236
    if o > c:
        trend = -1 if prior < 0 and threshold < c - lo else 1
    else:
        trend = 1 if prior > 0 and threshold < hi - c else -1
    # Preserve source's existing synthetic candle colour mapping, including doji.
    color = 0.0 if o == c or trend < 0 else 1.0
    return trend, color


def expected(data):
    trend = 1
    outputs = [math.nan] * len(data)
    for i in range(PERIOD, len(data)):
        trend, outputs[i] = step(
            trend,
            *(data[k].iloc[: i + 1].tolist() for k in ("open", "high", "low", "close")),
        )
    return outputs


def run(data, mode):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = bt.indicators.FiboCandlesIndicator(self.data, period=PERIOD)

    engine = bt.Cerebro(stdstats=False, preload=True, runonce=mode)
    engine.adddata(bt.feeds.PandasData(dataname=data))
    engine.addstrategy(Probe)
    return list(engine.run()[0].ind.color.array)


def compare(a, b):
    assert len(a) == len(b)
    for index, (actual, want) in enumerate(zip(a, b)):
        if math.isnan(want):
            assert math.isnan(actual), (index, actual, want)
        else:
            assert actual == want, (index, actual, want)


@pytest.mark.parametrize("mode", [False, True], ids=["next", "once"])
def test_finite_reference(mode):
    data = frame()
    compare(run(data, mode), expected(data))


@pytest.mark.parametrize("mode", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_missing_is_unavailable_without_mutating_previous_trend(mode, field):
    data = frame(missing=field)
    compare(run(data, mode), expected(data))


@pytest.mark.parametrize("mode", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("kind", ["missing", "overflow", "distance_overflow"])
def test_factor_strict_missing_and_finite_range_overflow(mode, kind):
    from backtrader.errors import FactorComputationError
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    from tests.unit.test_factor_research_representatives import (
        _frames,
        _research_feed,
        _research_spec,
    )

    data = _frames(periods=35)["asset-0"].copy()
    if kind == "missing":
        data.iloc[20, data.columns.get_loc("close")] = math.nan
    elif kind == "overflow":
        data.loc[:, "high"] = 1e308
        data.loc[:, "low"] = -1e308
    else:
        data.loc[:, "high"] = 1e308
        data.loc[:, "low"] = 0.0
        data.loc[:, "open"] = -1e308
        data.loc[:, "close"] = -1e308
    research = _research_spec({"asset-0": data})
    indicators = []

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.ind = bt.indicators.FiboCandlesIndicator(self.data, period=PERIOD)
            indicators.append(self.ind)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.ind.color[0]

    engine = bt.Cerebro(stdstats=False, runonce=mode)
    engine.adddata(_research_feed(data, research, "asset-0"), name="asset-0")
    spec = FactorSpec(
        name="fibo",
        indicator=Factor,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        mode="native",
    )
    engine.addstrategy(FactorStrategy, research=research, factors={"fibo": spec})
    if kind != "missing":
        with pytest.raises(FactorComputationError) as caught:
            engine.run(preload=True)
        assert isinstance(caught.value.__cause__, ArithmeticError)
    else:
        engine.run(preload=True)
        assert math.isnan(indicators[0].color.array[20])


@pytest.mark.parametrize("mode", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("count", [1, 4, 5])
def test_short_history_and_first_bar(mode, count):
    data = frame(count)
    compare(run(data, mode), expected(data))


@pytest.mark.parametrize("missing_index", [31, 33])
def test_replay_missing_close_revision_remains_unavailable(missing_index):
    data = frame(180)
    data.loc[data.index[missing_index], "close"] = math.nan

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = bt.indicators.FiboCandlesIndicator(self.data, period=PERIOD)
            self.rows = []

        def next(self):
            self.rows.append(
                (
                    len(self.data),
                    float(self.data.close[0]),
                    float(self.ind.color[0]),
                    self.ind._trend,
                )
            )

    engine = bt.Cerebro(stdstats=False, preload=False, runonce=False)
    engine.replaydata(
        bt.feeds.PandasData(dataname=data),
        timeframe=bt.TimeFrame.Minutes,
        compression=5,
    )
    engine.addstrategy(Probe)
    rows = engine.run()[0].rows
    indexes = [i for i, row in enumerate(rows) if math.isnan(row[1])]
    assert len(indexes) == 1
    i = indexes[0]
    assert math.isnan(rows[i][2])
    assert rows[i][3] == rows[i - 1][3]
    assert rows[i + 1][0] == rows[i][0] and math.isfinite(rows[i + 1][2])


@pytest.mark.parametrize("mode", [False, True], ids=["next", "once"])
def test_finite_callback_does_not_invoke_custom_context_resolver_twice(mode):
    class Custom(bt.indicators.FiboCandlesIndicator):
        def __init__(self):
            super().__init__()
            self.inside_next = False
            self.resolver_calls = 0

        def _factor_strict_context_for_callback(self):
            self.resolver_calls += 1
            if self.inside_next:
                raise RuntimeError("unexpected nested resolver call")
            return super()._factor_strict_context_for_callback()

        def next(self):
            self.inside_next = True
            try:
                return super().next()
            finally:
                self.inside_next = False

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = Custom(self.data, period=PERIOD)

    engine = bt.Cerebro(stdstats=False, runonce=mode)
    engine.adddata(bt.feeds.PandasData(dataname=frame(20)))
    engine.addstrategy(Probe)
    instance = engine.run(preload=True)[0].ind
    assert instance.resolver_calls > 0
