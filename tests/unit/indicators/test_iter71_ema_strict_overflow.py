import math

import pandas as pd
import pytest

import backtrader as bt
from backtrader.errors import FactorComputationError
from backtrader.research import align_to_grid
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.specs import FactorSpec, ResearchSpec
from backtrader.strategies.factor_strategy import FactorStrategy


def run_factor(values, once, kind="ema", period=3, movav=None):
    index = pd.date_range(
        "2024-01-01", periods=len(values), freq="min", tz="UTC", name="close_time"
    )
    frame = pd.DataFrame(
        {
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": 1.0,
            "openinterest": 0.0,
        },
        index=index,
    )
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(minutes=1)}, index=index),
        start=index[0],
        end=index[-1],
        targets=("asset",),
        source_timezone="UTC",
        snapshot_id="test",
        price_basis="synthetic",
        calendar_id="synthetic",
        frequency="1min",
        feed_time_kind="close_time",
        groups={"asset": "market"},
    )
    seen = []

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            if kind == "ema":
                self.child = bt.ind.EMA(self.data.close, period=period)
            elif movav is None:
                self.child = bt.ind.TRIX(self.data.close, period=period)
            else:
                self.child = bt.ind.TRIX(self.data.close, period=period, _movav=movav)
            seen.append(self)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child[0]

    cerebro = bt.Cerebro(stdstats=False, runonce=once)
    cerebro.adddata(align_to_grid(frame, research, "asset").feed, name="asset")
    spec = FactorSpec(
        name="strict",
        indicator=Factor,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        mode="native",
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"strict": spec})
    try:
        cerebro.run(preload=True)
    except FactorComputationError as error:
        return error, seen
    return None, seen


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("kind", ["ema", "trix"])
def test_finite_seed_overflow_fails(once, kind):
    error, seen = run_factor([1e308] * 50, once, kind)
    assert isinstance(error, FactorComputationError)
    assert isinstance(error.__cause__, ArithmeticError)
    assert seen and seen[0]._factor_strict_context.failed


@pytest.mark.parametrize("once", [False, True])
def test_finite_trix_ratio_overflow_fails(once):
    error, seen = run_factor([1e-308, 1e308] + [1e308] * 18, once, "trix", period=1)
    assert isinstance(error, FactorComputationError)
    assert isinstance(error.__cause__, ArithmeticError)
    assert seen and seen[0]._factor_strict_context.failed


@pytest.mark.parametrize("once", [False, True])
def test_strict_valid_ema_matches_recurrence(once):
    values = [10.0, 12.0, 14.0, 15.0, 13.0, 18.0, 20.0, 19.0]
    error, seen = run_factor(values, once, "ema")
    assert error is None
    got = list(seen[0].child.lines[0].array)
    prev = sum(values[:3]) / 3
    expected = [math.nan, math.nan, prev]
    for value in values[3:]:
        prev = 0.5 * prev + 0.5 * value
        expected.append(prev)
    assert len(got) == len(expected)
    for a, b in zip(got, expected):
        assert math.isnan(a) if math.isnan(b) else a == pytest.approx(b)


@pytest.mark.parametrize("once", [False, True])
def test_custom_movav_supported(once):
    values = [10.0, 12.0, 14.0, 15.0, 13.0, 18.0, 20.0, 19.0]
    error, seen = run_factor(values, once, "trix", period=1, movav=bt.ind.SMA)
    assert error is None
    result = list(seen[0].child.lines[0].array)
    assert result[-1] == pytest.approx(100 * (values[-1] / values[-2] - 1))


def test_operation_source_failure_strict_and_plain():
    from backtrader.errors import FactorComputationContext
    from backtrader.research.strict import computation_scope

    values = [100.0 + i for i in range(25)]
    frame = pd.DataFrame(
        dict.fromkeys(("open", "high", "low", "close"), values),
        index=pd.date_range("2024-01-01", periods=len(values), freq="D"),
    )

    class Strategy(bt.Strategy):
        def __init__(self):
            self.operation = self.data.close * 1.0
            self.ema = bt.ind.EMA(self.operation, period=3)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Strategy)
    strategy = cerebro.run(runonce=False)[0]
    source = strategy.ema.data
    calls = []

    def fail(*args):
        calls.append(args)
        raise ArithmeticError("operation failed")

    source.once = fail
    strategy.ema.once(3, 5)
    assert calls == [(0, 5)]
    context = FactorComputationContext("test", phase="once")
    with computation_scope(context, "once"), pytest.raises(FactorComputationError) as caught:
        strategy.ema.once(3, 5)
    assert isinstance(caught.value.__cause__, ArithmeticError)
    assert context.failed and calls == [(0, 5), (0, 5)]


def test_strict_intermediate_infinities_cannot_hide_as_nan():
    from backtrader.errors import FactorComputationContext
    from backtrader.research.strict import computation_scope

    values = [100.0 + i for i in range(25)]
    frame = pd.DataFrame(
        dict.fromkeys(("open", "high", "low", "close"), values),
        index=pd.date_range("2024-01-01", periods=len(values), freq="D"),
    )

    class Strategy(bt.Strategy):
        def __init__(self):
            self.ema = bt.ind.EMA(self.data.close, period=3)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Strategy)
    ema = cerebro.run(runonce=False)[0].ema
    ema.alpha = -2.0
    ema.alpha1 = 3.0
    ema.lines[0].array[4] = 1e308
    ema.data.array[5] = 1e308
    context = FactorComputationContext("test", phase="once")
    with pytest.raises(FactorComputationError), computation_scope(context, "once"):
        ema.once(5, 6)
    assert context.failed
    ema.once(5, 6)
    assert math.isnan(ema.lines[0].array[5])


def test_plain_once_does_not_read_strict_descriptor(monkeypatch):
    from backtrader.linebuffer import LineBuffer

    values = [100.0 + i for i in range(25)]
    frame = pd.DataFrame(
        dict.fromkeys(("open", "high", "low", "close"), values),
        index=pd.date_range("2024-01-01", periods=len(values), freq="D"),
    )

    class Strategy(bt.Strategy):
        def __init__(self):
            self.ema = bt.ind.EMA(self.data.close, period=3)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Strategy)
    ema = cerebro.run(runonce=False)[0].ema

    def unexpected(self):
        raise RuntimeError("strict descriptor was read")

    monkeypatch.setattr(LineBuffer, "_factor_strict_context", property(unexpected), raising=False)
    ema.once(3, 5)


@pytest.mark.parametrize("once", [False, True])
def test_custom_movav_intermediate_is_not_coerced(once):
    class Product:
        def __float__(self):
            raise RuntimeError("unexpected product coercion")

        def __add__(self, other):
            return 7.0

    class Alpha:
        def __rmul__(self, left):
            return Product()

    class CustomEMA(bt.ind.EMA):
        alias = ()

        def __init__(self):
            super().__init__()
            self.alpha1 = Alpha()

    error, seen = run_factor([100.0 + i for i in range(30)], once, "trix", movav=CustomEMA)
    assert error is None
    assert seen
