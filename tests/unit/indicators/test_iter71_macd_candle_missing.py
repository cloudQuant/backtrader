import importlib.util
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import backtrader as bt
import pandas as pd
import pytest

import backtrader.indicators.contrib.macd_candle_indicator as module
from backtrader.errors import FactorComputationError
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.specs import FactorSpec
from backtrader.strategies.factor_strategy import FactorStrategy
from tests.unit.test_factor_research_representatives import _frames, _research_feed, _research_spec


def strategy_class(monkeypatch):
    path = (
        Path(__file__).resolve().parents[3]
        / "tests/functional/strategies/mean_reversion/test_0187_0952_macdcandle.py"
    )
    spec = importlib.util.spec_from_file_location("macd_candle_strategy_fixture", path)
    obj = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, obj)
    spec.loader.exec_module(obj)
    return obj.MacdCandleStrategy


def data_frame():
    values = [101.0] * 35
    values[14] = math.nan
    return pd.DataFrame(
        {
            "open": [100.0] * len(values),
            "high": [102.0] * len(values),
            "low": [99.0] * len(values),
            "close": values,
            "volume": [1.0] * len(values),
        },
        index=pd.date_range("2024-01-01", periods=len(values), freq="min"),
    )


def direct_macd(line, **kwargs):
    return SimpleNamespace(macd=line, signal=line)


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("mode", ["signal", "macd"])
@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_candle_missing_color_and_recovery(runonce, mode, field, monkeypatch):
    monkeypatch.setattr(module, "MACD", direct_macd)
    frame = data_frame()
    frame.loc[:, "close"] = 101.0
    frame.loc[frame.index[14], field] = math.nan
    frame.loc[frame.index[18], "close"] = 100.0
    frame.loc[frame.index[19], "close"] = 99.0

    class Driver(bt.Strategy):
        def __init__(self):
            self.ind = module.MacdCandleIndicator(
                self.data, fast_ema_period=1, slow_ema_period=1, signal_period=1, mode=mode
            )

    c = bt.Cerebro(stdstats=False, runonce=runonce)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(Driver)
    ind = c.run(preload=True)[0].ind
    if field in ("open", "close"):
        assert math.isnan(ind.lines.color.array[14])
    else:
        assert ind.lines.color.array[14] == 2
    for line, name in zip(ind.lines[:4], ("open", "high", "low", "close")):
        actual, expected = line.array[14], frame[name].iloc[14]
        assert math.isnan(actual) if math.isnan(expected) else actual == expected
    assert ind.lines.color.array[13] == 2
    assert ind.lines.color.array[15] == 2
    assert ind.lines.color.array[18] == 1
    assert ind.lines.color.array[19] == 0


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("field", ["open", "close"])
@pytest.mark.parametrize("direction", [-1, 1])
def test_actual_strategy_does_not_enter_on_recovery_from_missing_color(
    runonce, field, direction, monkeypatch
):
    monkeypatch.setattr(module, "MACD", direct_macd)
    cls = strategy_class(monkeypatch)
    frame = data_frame()
    frame.loc[:, "close"] = 101.0 if direction > 0 else 99.0
    frame.loc[frame.index[14], field] = math.nan

    class Recorder(cls):
        def __init__(self):
            super().__init__()
            self.entries = []

        def _submit_entry(self, direction, reason):
            self.entries.append((len(self.data), direction))
            return False

    c = bt.Cerebro(stdstats=False, runonce=runonce)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(
        Recorder,
        fast_ema_period=1,
        slow_ema_period=1,
        signal_period=1,
        stop_loss_points=0,
        take_profit_points=0,
    )
    strategy = c.run(preload=True)[0]
    assert strategy.entries == []


@pytest.mark.parametrize("runonce", [False, True])
def test_actual_strategy_still_executes_protective_stop_on_missing(runonce, monkeypatch):
    monkeypatch.setattr(module, "MACD", direct_macd)
    cls = strategy_class(monkeypatch)

    class Recorder(cls):
        def __init__(self):
            super().__init__()
            self.stops = []

        def next(self):
            if len(self.data) == 11:
                self.pending_entry_direction = 1
                self.entry_side = "long"
                self.order = self.buy(size=0.1)
            super().next()

        def _check_exit_levels(self):
            before = self.order
            stopped = super()._check_exit_levels()
            if stopped and before is None:
                self.stops.append(len(self.data))
            return stopped

    frame = data_frame()
    frame.loc[frame.index[14], "low"] = 90.0
    c = bt.Cerebro(stdstats=False, runonce=runonce)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(
        Recorder,
        fast_ema_period=1,
        slow_ema_period=1,
        signal_period=1,
        point=1.0,
        stop_loss_points=3,
        take_profit_points=0,
    )
    strategy = c.run(preload=True)[0]
    assert strategy.stops == [15]


def test_replay_combination_tracks_each_visible_revision(monkeypatch):
    monkeypatch.setattr(module, "MACD", direct_macd)
    frame = data_frame()
    frame.loc[:, "close"] = 101.0
    frame.loc[frame.index[13], "close"] = math.nan

    class Driver(bt.Strategy):
        def __init__(self):
            self.ind = module.MacdCandleIndicator(
                self.data, fast_ema_period=1, slow_ema_period=1, signal_period=1
            )
            self.samples = []

        def next(self):
            self.samples.append(
                (
                    len(self.data),
                    float(self.data.open[0]),
                    float(self.data.close[0]),
                    float(self.ind.color[0]),
                )
            )

    c = bt.Cerebro(stdstats=False)
    c.replaydata(
        bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes),
        timeframe=bt.TimeFrame.Minutes,
        compression=3,
    )
    c.addstrategy(Driver)
    samples = c.run()[0].samples
    assert len(samples) > 20
    assert any(math.isnan(close) for _, _, close, _ in samples)
    assert any(
        left[0] == right[0] and math.isnan(left[2]) and math.isfinite(right[2])
        for left, right in zip(samples, samples[1:])
    )
    for _, op, close, color in samples:
        if math.isnan(op) or math.isnan(close):
            assert math.isnan(color)
        else:
            assert color == (2 if op < close else 0 if op > close else 1)


def ema(values, period):
    out = [math.nan] * len(values)
    out[period - 1] = sum(values[:period]) / period
    alpha = 2.0 / (period + 1.0)
    for index in range(period, len(values)):
        out[index] = alpha * values[index] + (1 - alpha) * out[index - 1]
    return out


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("mode", ["signal", "macd"])
def test_actual_macd_all_lines_and_independent_warmup(runonce, mode):
    count = 60
    frame = pd.DataFrame(
        {
            name: [100.0 + math.sin(i * (0.3 + j * 0.02)) + j for i in range(count)]
            for j, name in enumerate(("open", "high", "low", "close"))
        },
        index=pd.date_range("2024-01-01", periods=count, freq="min"),
    )

    class Driver(bt.Strategy):
        def __init__(self):
            self.ind = module.MacdCandleIndicator(
                self.data, fast_ema_period=3, slow_ema_period=5, signal_period=3, mode=mode
            )

    c = bt.Cerebro(stdstats=False, runonce=runonce)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(Driver)
    ind = c.run(preload=True)[0].ind
    assert ind._minperiod == 11
    expected = []
    for name in ("open", "high", "low", "close"):
        values = list(frame[name])
        fast, slow = ema(values, 3), ema(values, 5)
        macd = [a - b for a, b in zip(fast, slow)]
        sig = [math.nan] * 4 + ema(macd[4:], 3)
        expected.append(sig if mode == "signal" else macd)
    for i in range(count):
        for line, values in zip(ind.lines[:4], expected):
            actual = line.array[i]
            if i < 10:
                assert math.isnan(actual)
            else:
                assert actual == pytest.approx(values[i])
        actual_color = ind.lines.color.array[i]
        if i < 10:
            assert math.isnan(actual_color)
        else:
            op, cl = expected[0][i], expected[3][i]
            assert actual_color == (2 if op < cl else 0 if op > cl else 1)


@pytest.mark.parametrize("runonce", [False, True])
def test_factor_strict_raw_infinite_subline_still_fails(runonce, monkeypatch):
    class Raw(bt.Indicator):
        lines = ("value",)

        def next(self):
            self.lines.value.array[self.lines.value.idx] = (
                math.inf if len(self) == 15 else float(self.data[0])
            )

        def once(self, start, end):
            for i in range(start, end):
                self.lines.value.array[i] = math.inf if i == 14 else float(self.data.array[i])

    def raw_macd(line, **kwargs):
        raw = Raw(line)
        return SimpleNamespace(macd=raw.lines.value, signal=raw.lines.value)

    monkeypatch.setattr(module, "MACD", raw_macd)

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = ("open", "high", "low", "close")
        required_fields = formula_fields
        lookback_h = 0

        def __init__(self):
            super().__init__()
            Factor.instance = self
            self.candle = module.MacdCandleIndicator(
                self.data, fast_ema_period=1, slow_ema_period=1, signal_period=1
            )

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.candle.color[0]

    frames = _frames(periods=25)
    frame = frames["asset-0"]
    research = _research_spec({"asset-0": frame})
    c = bt.Cerebro(stdstats=False, runonce=runonce)
    c.adddata(_research_feed(frame, research, "asset-0"), name="asset-0")
    factor = FactorSpec(
        name="candle",
        indicator=Factor,
        panel_line="factor",
        field_bindings={name: f"feed:target:{name}" for name in Factor.formula_fields},
        mode="native",
    )
    c.addstrategy(FactorStrategy, research=research, factors={factor.name: factor})
    with pytest.raises(FactorComputationError) as caught:
        c.run(preload=True)
    assert caught.value.factor == "candle"
    assert caught.value.phase == ("once_via_next" if runonce else "next")
    assert isinstance(caught.value.__cause__, ArithmeticError)
    assert Factor.instance._factor_strict_context.failed is True
