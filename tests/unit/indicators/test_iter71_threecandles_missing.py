"""ThreeCandlesIndicator missing-input and strict calculation regressions."""
import math

import backtrader as bt
import pandas as pd
import pytest


def _frame(missing="close", bearish=False, replay=False, final_close=None, missing_at=4):
    # Bars 1-3 satisfy the documented pattern; bar 4 determines its label.
    pattern = [(10., 10.5, 11., 9.), (10., 11., 12., 9.),
               (10.5, 11.5, 12., 10.), (12., 10., 13., 9.),
               (10., 11., 12., 9.)]
    if bearish:
        pattern = [(22-o, 22-c, 22-low, 22-high) for o, c, high, low in pattern]
    bars = [list(row) for row in pattern + pattern]
    volume = [10., 10., 11., 12., 10.] * 2
    if missing is not None:
        if missing == "volume":
            volume[missing_at] = math.nan
        else:
            bars[missing_at][{"open": 0, "close": 1, "high": 2, "low": 3}[missing]] = math.nan
    if final_close is not None:
        bars[9][1] = final_close
    if replay:
        bars = [bars[0], *[bar for bar in bars[1:] for _ in range(2)]]
        volume = [volume[0], *[v for v in volume[1:] for _ in range(2)]]
    return pd.DataFrame({"open": [x[0] for x in bars], "close": [x[1] for x in bars],
                         "high": [x[2] for x in bars], "low": [x[3] for x in bars],
                         "volume": volume, "openinterest": [0.0] * len(bars)},
                        index=pd.date_range("2024-01-02 09:00", periods=len(bars), freq="min"))


def _run(missing, bearish, runonce=False, replay=False, final_close=None,
         missing_at=4, volume_type="none", max_bar1=300):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = bt.indicators.ThreeCandlesIndicator(
                self.data, volume_type=volume_type, max_bar1=max_bar1)
            self.rows = []

        def next(self):
            self.rows.append((len(self.data), float(self.ind.signal[0])))

    engine = bt.Cerebro(stdstats=False, runonce=runonce, preload=not replay)
    data = bt.feeds.PandasData(dataname=_frame(missing, bearish, replay, final_close, missing_at),
                               timeframe=bt.TimeFrame.Minutes)
    if replay:
        engine.replaydata(data, timeframe=bt.TimeFrame.Minutes, compression=2)
    else:
        engine.adddata(data)
    engine.addstrategy(Probe)
    return engine.run()[0].rows


@pytest.mark.parametrize("mode", ["next", "once", "replay"])
@pytest.mark.parametrize("missing", ["open", "close"])
@pytest.mark.parametrize("bearish", [False, True])
def test_current_missing_candle_no_fake_signal_then_recovers(mode, missing, bearish):
    rows = _run(missing, bearish, runonce=mode == "once", replay=mode == "replay")
    gap = [signal for bar, signal in rows if bar == 5]
    recovered = [signal for bar, signal in rows if bar == 10]
    assert gap and all(math.isnan(signal) for signal in gap)
    assert recovered and all(signal == (3.0 if bearish else 1.0) for signal in recovered)
    if mode == "replay":
        assert len(gap) == 2 and len(recovered) == 2


@pytest.mark.parametrize("mode", ["next", "once", "replay"])
@pytest.mark.parametrize("bearish,close,expected", [
    (False, 9.0, 0.0), (False, 11.0, 1.0),
    (True, 11.0, 3.0), (True, 13.0, 4.0),
])
def test_finite_candle_preserves_each_pattern_label(mode, bearish, close, expected):
    rows = _run(None, bearish, runonce=mode == "once", replay=mode == "replay",
                final_close=close)
    final = [signal for bar, signal in rows if bar == 10]
    assert final and all(signal == expected for signal in final)


@pytest.mark.parametrize("bearish", [False, True])
@pytest.mark.parametrize("field,index,mode", [
    (field, index, mode)
    for field, index in [
        ("open", 1), ("close", 1), ("open", 2), ("close", 2),
        ("open", 3), ("close", 3), ("high", 1), ("low", 1),
        ("volume", 1), ("volume", 2), ("volume", 3),
    ]
    # The standard replay aggregator supplies finite extrema for this input;
    # it does not pass the inserted high/low NaNs through to the indicator.
    for mode in (["next", "once"] if field in ("high", "low") else ["next", "once", "replay"])
])
def test_required_historical_missing_is_unknown_and_recovers(mode, bearish, field, index):
    rows = _run(field, bearish, runonce=mode == "once", replay=mode == "replay",
                missing_at=index, volume_type="tick")
    gap = [signal for bar, signal in rows if bar == 5]
    recovered = [signal for bar, signal in rows if bar == 10]
    assert gap and all(math.isnan(signal) for signal in gap)
    assert recovered and all(signal == (3.0 if bearish else 1.0) for signal in recovered)


@pytest.mark.parametrize("mode", ["next", "once", "replay"])
@pytest.mark.parametrize("volume_type,max_bar1", [("none", 300), ("tick", 0)])
def test_missing_unused_volume_does_not_block_signal(mode, volume_type, max_bar1):
    rows = _run("volume", False, runonce=mode == "once", replay=mode == "replay",
                missing_at=1, volume_type=volume_type, max_bar1=max_bar1)
    gap = [signal for bar, signal in rows if bar == 5]
    assert gap and all(signal == 1.0 for signal in gap)


@pytest.mark.parametrize("runonce", [False, True])
def test_finite_volume_filter_rejects_unchanged_volume(runonce):
    frame = _frame(None)
    frame.loc[:, "volume"] = 10.0

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = bt.indicators.ThreeCandlesIndicator(self.data, volume_type="tick")

    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.addstrategy(Probe)
    result = engine.run(preload=True)[0]
    assert result.ind.signal.array[4] == 2.0


def test_replay_revises_missing_current_close_before_bar_finishes():
    frame = _frame("close", replay=True)
    frame.iloc[8, frame.columns.get_loc("close")] = 11.0

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = bt.indicators.ThreeCandlesIndicator(self.data, volume_type="tick")
            self.rows = []

        def next(self):
            if len(self.data) == 5:
                self.rows.append((float(self.data.close[0]), float(self.ind.signal[0])))

    engine = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    data = bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes)
    engine.replaydata(data, timeframe=bt.TimeFrame.Minutes, compression=2)
    engine.addstrategy(Probe)
    rows = engine.run()[0].rows
    assert len(rows) == 2 and math.isnan(rows[0][0]) and math.isnan(rows[0][1])
    assert rows[1] == (11.0, 1.0)


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("field,index,bearish,volume_type,side", [
    ("close", 4, False, "none", "sell"),
    ("low", 1, False, "tick", "sell"),
    ("high", 1, True, "tick", "buy"),
    ("volume", 2, False, "tick", "sell"),
])
def test_original_three_candles_strategy_does_not_open_on_gap(
    runonce, field, index, bearish, volume_type, side
):
    from tests.functional.strategies.mean_reversion.test_0143_0636_exp_threecandles import ExpThreeCandlesStrategy

    class Probe(ExpThreeCandlesStrategy):
        def __init__(self):
            super().__init__()
            self.entries = []
            self.observations = []

        def _enter_side(self, side, price):
            self.entries.append((len(self.data), side, price))
            return super()._enter_side(side, price)

        def next(self):
            self.observations.append((len(self.data), float(self.signal.signal[0])))
            super().next()

    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(bt.feeds.PandasData(dataname=_frame(field, bearish, missing_at=index)))
    engine.addstrategy(Probe, volume_type=volume_type)
    result = engine.run(preload=True)[0]
    assert math.isnan(dict(result.observations)[5])
    assert not any(bar == 5 for bar, _, _ in result.entries)
    assert any(bar == 10 and actual_side == side for bar, actual_side, _ in result.entries)


def _strict_run(frame, runonce, volume_type="none"):
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    from tests.unit.test_factor_research_representatives import _research_feed, _research_spec

    frame = frame.copy()
    frame.index = frame.index.tz_localize("UTC")
    for field in ("vwap", "dollar_volume", "cap", "sector", "industry", "subindustry"):
        frame[field] = 1.0
    research = _research_spec({"asset-0": frame})
    instances = []
    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = bt.indicators.ThreeCandlesIndicator(self.data, volume_type=volume_type)
            instances.append(self)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.signal[0]

    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(_research_feed(frame, research, "asset-0"), name="asset-0")
    spec = FactorSpec(name="three", indicator=Factor, panel_line="factor",
                      field_bindings={"close": "feed:target:close"}, mode="native")
    engine.addstrategy(FactorStrategy, research=research, factors={"three": spec})
    engine.run(preload=True)
    return instances[0].child.signal.array


@pytest.mark.parametrize("runonce", [False, True])
def test_strict_factor_preserves_missing_signal_and_recovers(runonce):
    result = _strict_run(_frame(), runonce)
    assert math.isnan(result[4])
    assert result[9] == 1.0


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("field,index,bearish", [
    ("low", 1, False), ("high", 1, True), ("volume", 2, False),
])
def test_strict_factor_preserves_historical_missing_and_recovers(runonce, field, index, bearish):
    result = _strict_run(_frame(field, bearish, missing_at=index), runonce, volume_type="tick")
    assert math.isnan(result[4])
    assert result[9] == (3.0 if bearish else 1.0)


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("case", ["range_subtraction", "range_scaling"])
def test_strict_factor_rejects_finite_range_overflow(runonce, case):
    from backtrader.errors import FactorComputationError
    frame = _frame()
    frame.loc[:, "close"] = 1.0
    frame.loc[:, "open"] = 1.0
    frame.loc[:, "high"] = 1e308
    frame.loc[:, "low"] = -1e308 if case == "range_subtraction" else 0.0
    with pytest.raises(FactorComputationError) as caught:
        _strict_run(frame, runonce)
    assert caught.value.code == "FACTOR_COMPUTATION_FAILED"
    assert isinstance(caught.value.__cause__, ArithmeticError)
