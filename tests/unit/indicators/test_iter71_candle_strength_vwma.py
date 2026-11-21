"""Finite synthetic OHLCV contract checks for two candle indicators."""
import math

import backtrader as bt
import pandas as pd
import pytest


def _frame(missing, missing_value=float("nan"), doji=False):
    n = 60
    opens = [100.0 + (i % 7) for i in range(n)]
    closes = [v + (1.5 if i % 8 < 3 else -1.0 if i % 8 < 6 else 0.0)
              for i, v in enumerate(opens)]
    if doji:
        opens = [100.0] * n
        closes = opens[:]
    volumes = [float(i % 4 - 1) for i in range(n)]
    volumes[30:34] = [0.0] * 4
    frame = pd.DataFrame({"open": opens, "close": closes,
                          "high": [max(o, c) + 1 for o, c in zip(opens, closes)],
                          "low": [min(o, c) - 1 for o, c in zip(opens, closes)],
                          "volume": volumes,
                          "openinterest": [float(i % 3) for i in range(n)]},
                         index=pd.date_range("2024-01-02 09:00", periods=n, freq="min"))
    if missing:
        frame.loc[frame.index[19], missing] = missing_value
    return frame


def _run(kind, field, runonce, replay=False, use_tick_volume=True,
         missing_value=float("nan"), doji=False):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = (bt.indicators.UpDownCandleStrength(self.data, period=4)
                        if kind == "strength" else
                        bt.indicators.VWMACandle(self.data, length=4,
                                                use_tick_volume=use_tick_volume))
            self.rows = []

        def next(self):
            history = [(float(self.data.open[-i]), float(self.data.close[-i]),
                        float(self.data.volume[-i] if use_tick_volume
                              else self.data.openinterest[-i])) for i in range(4)]
            self.rows.append((len(self.data), history, float(self.ind.lines[0][0])))

    c = bt.Cerebro(stdstats=False, runonce=runonce, preload=not replay)
    data = bt.feeds.PandasData(dataname=_frame(field, missing_value, doji),
                              timeframe=bt.TimeFrame.Minutes)
    if replay:
        c.replaydata(data, timeframe=bt.TimeFrame.Minutes, compression=2)
    else:
        c.adddata(data)
    c.addstrategy(Probe)
    return c.run()[0].rows


def _expected(kind, history):
    if kind == "strength":
        if any(not math.isfinite(o) or not math.isfinite(c) for o, c, _ in history):
            return float("nan")
        up = sum(c > o for o, c, _ in history)
        down = sum(c < o for o, c, _ in history)
        return up / (up + down) if up + down else 0.5
    if any(not math.isfinite(x) for row in history for x in row):
        return float("nan")
    weights = [max(0.0, row[2]) for row in history]
    total = sum(weights)
    if total:
        weighted_open = sum(row[0] * w for row, w in zip(history, weights)) / total
        weighted_close = sum(row[1] * w for row, w in zip(history, weights)) / total
    else:
        weighted_open, weighted_close, _ = history[0]
    return 2.0 if weighted_close > weighted_open else 0.0 if weighted_close < weighted_open else 1.0


@pytest.mark.parametrize("kind", ["strength", "vwma"])
@pytest.mark.parametrize("mode", ["next", "once", "replay"])
def test_candle_indicators_clean_window_formula(kind, mode):
    rows = _run(kind, None, mode == "once", mode == "replay")
    assert rows
    if mode == "replay":
        assert any(a[0] == b[0] for a, b in zip(rows, rows[1:]))
    for _, history, value in rows:
        assert value == pytest.approx(_expected(kind, history))
    assert len({row[2] for row in rows}) > 1
    if kind == "vwma" and mode != "replay":
        assert any(all(row[2] <= 0 for row in history) for _, history, _ in rows)


@pytest.mark.parametrize("kind,field", [("strength", "open"), ("strength", "close"),
                                        ("vwma", "open"), ("vwma", "close"),
                                        ("vwma", "volume")])
@pytest.mark.parametrize("mode", ["next", "once", "replay"])
def test_candle_indicators_missing_window_does_not_become_neutral(kind, field, mode):
    rows = _run(kind, field, mode == "once", mode == "replay")
    expected = [_expected(kind, row[1]) for row in rows]
    assert any(math.isnan(value) for value in expected)
    for (_, _, value), want in zip(rows, expected):
        if math.isnan(want):
            assert math.isnan(value)
        else:
            assert value == pytest.approx(want)
    assert math.isfinite(rows[-1][2])


@pytest.mark.parametrize("mode", ["next", "once", "replay"])
def test_equal_finite_candles_are_neutral(mode):
    for kind, neutral in [("strength", 0.5), ("vwma", 1.0)]:
        rows = _run(kind, None, mode == "once", mode == "replay", doji=True)
        assert rows and all(row[2] == neutral for row in rows)


@pytest.mark.parametrize("mode", ["next", "once", "replay"])
def test_vwma_openinterest_missing_does_not_become_neutral(mode):
    rows = _run("vwma", "openinterest", mode == "once", mode == "replay",
                use_tick_volume=False)
    assert any(math.isnan(_expected("vwma", row[1])) for row in rows)
    for _, history, value in rows:
        want = _expected("vwma", history)
        assert math.isnan(value) if math.isnan(want) else value == pytest.approx(want)
    assert math.isfinite(rows[-1][2])



@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("case", ["open_product", "close_product", "sum", "weight_sum"])
def test_vwma_strict_factor_rejects_finite_intermediate_overflow(runonce, case):
    from backtrader.errors import FactorComputationError
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    from tests.unit.test_factor_research_representatives import _frames, _research_feed, _research_spec

    frame = _frames(periods=25)["asset-0"].copy()
    frame.loc[:, ["open", "close"]] = 1.0
    frame.loc[:, "volume"] = 1.0
    if case == "open_product":
        frame.loc[:, "open"] = 1e308
        frame.loc[:, "volume"] = 2.0
    elif case == "close_product":
        frame.loc[:, "close"] = -1e308
        frame.loc[:, "volume"] = 2.0
    elif case == "sum":
        frame.loc[:, "open"] = 1e308
    else:
        frame.loc[:, "volume"] = 1e308
    research = _research_spec({"asset-0": frame})

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = bt.indicators.VWMACandle(self.data, length=4)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.color[0]

    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(_research_feed(frame, research, "asset-0"), name="asset-0")
    spec = FactorSpec(name="vwma", indicator=Factor, panel_line="factor",
                      field_bindings={"close": "feed:target:close"}, mode="native")
    engine.addstrategy(FactorStrategy, research=research, factors={"vwma": spec})
    with pytest.raises(FactorComputationError) as caught:
        engine.run(preload=True)
    assert caught.value.code == "FACTOR_COMPUTATION_FAILED"
    assert isinstance(caught.value.__cause__, ArithmeticError)


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("coexisting_large", [False, True])
def test_vwma_strict_factor_preserves_missing_and_recovers(runonce, coexisting_large):
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    from tests.unit.test_factor_research_representatives import _frames, _research_feed, _research_spec

    frame = _frames(periods=25)["asset-0"].copy()
    frame.iloc[12, frame.columns.get_loc("open")] = math.nan
    if coexisting_large:
        frame.iloc[12, frame.columns.get_loc("close")] = 1e308
    research = _research_spec({"asset-0": frame})
    instances = []

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = bt.indicators.VWMACandle(self.data, length=4)
            instances.append(self)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.color[0]

    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(_research_feed(frame, research, "asset-0"), name="asset-0")
    spec = FactorSpec(name="vwma", indicator=Factor, panel_line="factor",
                      field_bindings={"close": "feed:target:close"}, mode="native")
    engine.addstrategy(FactorStrategy, research=research, factors={"vwma": spec})
    engine.run(preload=True)
    actual = instances[0].child.color.array
    assert math.isfinite(actual[11])
    assert all(math.isnan(actual[i]) for i in range(12, 16))
    assert math.isfinite(actual[16])
