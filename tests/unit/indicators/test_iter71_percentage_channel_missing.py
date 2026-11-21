"""Independent PercentageCrossoverChannel price and replay checks."""

import math

import pandas as pd
import pytest

import backtrader as bt


def frame(count=60, missing=None):
    prices = [100 + 2 * math.sin(i * 0.37) + i * 0.03 for i in range(count)]
    if missing is not None:
        prices[missing] = math.nan
    return pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1.0] * count,
        },
        index=pd.date_range("2024-01-01", periods=count, freq="min"),
    )


def reference(prices, percent=50):
    plus = 1 + max(percent, 0.001) / 10000.0
    minus = 1 - max(percent, 0.001) / 10000.0
    middle = [math.nan] * len(prices)
    upper = [math.nan] * len(prices)
    lower = [math.nan] * len(prices)
    for i in range(1, len(prices)):
        price = prices[i]
        if not math.isfinite(price):
            continue
        previous = middle[i - 1]
        if math.isnan(previous):
            value = price
        elif price * minus > previous:
            value = price * minus
        elif price * plus < previous:
            value = price * plus
        else:
            value = previous
        middle[i] = value
        upper[i] = value * plus
        lower[i] = value * minus
    return upper, middle, lower


def compare(actual, expected):
    assert len(actual) == len(expected)
    for i, (a, e) in enumerate(zip(actual, expected)):
        if math.isnan(e):
            assert math.isnan(a), (i, a, e)
        else:
            assert a == pytest.approx(e, rel=1e-12, abs=1e-12), (i, a, e)


def run(data, mode, percent=50):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = bt.ind.PercentageCrossoverChannel(self.data, percent=percent)

    engine = bt.Cerebro(stdstats=False, runonce=mode, preload=True)
    engine.adddata(bt.feeds.PandasData(dataname=data))
    engine.addstrategy(Probe)
    return engine.run()[0].ind


@pytest.mark.parametrize("mode", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("percent", [0, 50, 300])
def test_independent_finite_formula(mode, percent):
    data = frame()
    actual = run(data, mode, percent)
    assert actual._minperiod == 2
    for line, expected in zip(actual.lines, reference(data.close.tolist(), percent)):
        compare(line.array, expected)


@pytest.mark.parametrize("mode", [False, True], ids=["next", "once"])
def test_missing_price_is_unavailable_then_reseeds(mode):
    data = frame(missing=20)
    actual = run(data, mode)
    for line, expected in zip(actual.lines, reference(data.close.tolist())):
        compare(line.array, expected)
        assert math.isnan(line.array[20])
        assert math.isfinite(line.array[21])
    assert actual.middle.array[21] == data.close.iloc[21]


@pytest.mark.parametrize("missing", [None, 31, 33], ids=["finite", "gap1", "gap2"])
def test_single_source_replay_each_revision_matches_reference(missing):
    data = frame(180, missing=missing)

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = bt.ind.PercentageCrossoverChannel(self.data)
            self.rows = []

        def next(self):
            n = len(self.data)
            self.rows.append(
                (
                    n,
                    list(self.data.close.get(size=n)),
                    tuple(float(line[0]) for line in self.ind.lines),
                )
            )

    engine = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    engine.replaydata(
        bt.feeds.PandasData(dataname=data),
        timeframe=bt.TimeFrame.Minutes,
        compression=5,
    )
    engine.addstrategy(Probe)
    rows = engine.run()[0].rows
    assert any(rows[i][0] == rows[i + 1][0] for i in range(len(rows) - 1))
    for _, prices, actual in rows:
        expected = [line[-1] for line in reference(prices)]
        compare(actual, expected)


@pytest.mark.parametrize("mode", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("kind", ["missing", "overflow"])
def test_strict_factor_missing_and_finite_overflow(mode, kind):
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
        data.loc[data.index[20], "close"] = math.nan
    else:
        data.loc[:, "close"] = 9e307
    research = _research_spec({"asset-0": data})
    indicators = []

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.ind = bt.ind.PercentageCrossoverChannel(
                self.data, percent=20000 if kind == "overflow" else 50
            )
            indicators.append(self.ind)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.ind.middle[0]

    engine = bt.Cerebro(stdstats=False, runonce=mode)
    engine.adddata(_research_feed(data, research, "asset-0"), name="asset-0")
    spec = FactorSpec(
        name="pc",
        indicator=Factor,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        mode="native",
    )
    engine.addstrategy(FactorStrategy, research=research, factors={"pc": spec})
    if kind == "overflow":
        with pytest.raises(FactorComputationError) as caught:
            engine.run(preload=True)
        assert isinstance(caught.value.__cause__, ArithmeticError)
    else:
        engine.run(preload=True)
        assert math.isnan(indicators[0].middle.array[20])
        assert math.isfinite(indicators[0].middle.array[21])


@pytest.mark.parametrize("mode", [False, True], ids=["next", "once"])
def test_real_strategy_skips_crosses_using_a_missing_channel_bar(mode):
    from tests.functional.strategies.trend_following.test_0040_0467_percentage_crossover_channel import (
        PercentageCrossoverChannelStrategy,
    )

    data = frame(60)
    data.loc[:, "open"] = 100.0
    data.loc[:, "high"] = 100.2
    data.loc[:, "low"] = 99.8
    data.loc[:, "close"] = 100.0
    for i in (10, 20, 25):
        data.loc[data.index[i], "low"] = 99.0
    data.loc[data.index[20], "close"] = math.nan

    class Observed(PercentageCrossoverChannelStrategy):
        def __init__(self):
            super().__init__()
            self.submissions = []

        def buy(self, *args, **kwargs):
            self.submissions.append((len(self.data), "buy"))

        def sell(self, *args, **kwargs):
            self.submissions.append((len(self.data), "sell"))

    engine = bt.Cerebro(stdstats=False, runonce=mode)
    engine.adddata(bt.feeds.PandasData(dataname=data))
    engine.addstrategy(Observed, cross_middle=False)
    strategy = engine.run(preload=True)[0]
    assert strategy.submissions
    assert any(n < 21 for n, _ in strategy.submissions)
    assert any(n > 23 for n, _ in strategy.submissions)
    assert all(n not in (22, 23) for n, _ in strategy.submissions)


@pytest.mark.parametrize("mode", [False, True], ids=["next", "once"])
def test_finite_execution_does_not_use_module_math_proxy(monkeypatch, mode):
    import backtrader.indicators.contrib.percentage_crossover_channel as module

    class MathProxy:
        def isfinite(self, value):
            raise AssertionError("unexpected external math callback")

    monkeypatch.setattr(module, "math", MathProxy(), raising=False)
    data = frame()
    indicator = run(data, mode)
    for line, expected in zip(indicator.lines, reference(data.close.tolist())):
        compare(line.array, expected)


@pytest.mark.parametrize(
    "invalid",
    [math.nan, math.inf, -math.inf],
    ids=["nan", "positive_inf", "negative_inf"],
)
def test_nonfinite_price_visible_at_indicator_boundary(invalid):
    from types import SimpleNamespace

    from backtrader.indicators.contrib.percentage_crossover_channel import (
        PercentageCrossoverChannel,
    )

    class Read:
        def __getitem__(self, index):
            assert index == 0
            return invalid

    class Write:
        def __init__(self):
            self.value = None

        def __setitem__(self, index, value):
            assert index == 0
            self.value = value

    lines = SimpleNamespace(middle=Write(), upper=Write(), lower=Write())
    fake = SimpleNamespace(data=SimpleNamespace(close=Read()), lines=lines)
    PercentageCrossoverChannel.next(fake)
    assert all(
        math.isnan(line.value) for line in (lines.middle, lines.upper, lines.lower)
    )


@pytest.mark.parametrize(
    "invalid", [math.inf, -math.inf], ids=["positive_inf", "negative_inf"]
)
def test_infinite_price_at_indicator_boundary_is_rejected_in_strict_context(invalid):
    from types import SimpleNamespace

    from backtrader.indicators.contrib.percentage_crossover_channel import (
        PercentageCrossoverChannel,
    )
    from backtrader.research.strict import computation_scope

    class Read:
        def __getitem__(self, index):
            return invalid

    class Write:
        def __setitem__(self, index, value):
            raise AssertionError("strict rejection must precede output writes")

    class Context:
        phase = None

        def asset_for(self, operation):
            return None

        def wrap(self, error, phase, asset):
            return RuntimeError("strict infinity")

    lines = SimpleNamespace(middle=Write(), upper=Write(), lower=Write())
    fake = SimpleNamespace(data=SimpleNamespace(close=Read()), lines=lines)
    with (
        computation_scope(Context(), "next"),
        pytest.raises(RuntimeError, match="strict infinity") as caught,
    ):
        PercentageCrossoverChannel.next(fake)
    assert isinstance(caught.value.__cause__, ArithmeticError)
