"""SlidingRangeColor window, missing values and bounded-buffer regressions."""
import math

import backtrader as bt
import pandas as pd
import pytest


def _frame(missing=None):
    n = 45
    opens = [100.0 + (i % 6) for i in range(n)]
    closes = [value + (1.0 if i % 2 else -1.0) for i, value in enumerate(opens)]
    frame = pd.DataFrame({"open": opens, "close": closes,
                          "high": [max(a, b) + 2 for a, b in zip(opens, closes)],
                          "low": [min(a, b) - 2 for a, b in zip(opens, closes)],
                          "volume": [10.] * n, "openinterest": [0.] * n},
                         index=pd.date_range("2024-01-02 09:00", periods=n, freq="min"))
    if missing:
        frame.iloc[19, frame.columns.get_loc(missing)] = math.nan
        if missing == "open":
            frame.iloc[19, frame.columns.get_loc("close")] = 150.0
            frame.iloc[19, frame.columns.get_loc("high")] = 151.0
    return frame


def _run(frame, *, mode="next", bounded=False, params=None):
    class Probe(bt.Strategy):
        def __init__(self):
            config = params or dict(up_calc_period_range=4, up_calc_period_shift=1,
                                    dn_calc_period_range=3, dn_calc_period_shift=2)
            self.ind = bt.indicators.SlidingRangeColor(self.data, **config)
            self.rows = []

        def next(self):
            self.rows.append((len(self.data), *(float(getattr(self.data, f)[0])
                              for f in ("open", "high", "low", "close")),
                              *(float(getattr(self.ind, f)[0])
                              for f in ("color_idx", "upper", "lower"))))

    replay = mode == "replay"
    engine = bt.Cerebro(stdstats=False, runonce=mode == "once",
                        preload=not (bounded or replay), exactbars=int(bounded))
    data = bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes)
    if replay:
        engine.replaydata(data, timeframe=bt.TimeFrame.Minutes, compression=2)
    else:
        engine.adddata(data)
    engine.addstrategy(Probe)
    return engine.run()[0].rows


def _reference(rows):
    history = []
    previous = None
    outputs = []
    for length, op, high, low, close, *_ in rows:
        if length != previous:
            history.append((op, high, low, close))
        else:
            history[-1] = (op, high, low, close)
        previous = length
        highs = [row[1] for row in history[max(0, length-5):length-1]]
        lows = [row[2] for row in history[max(0, length-5):max(0, length-2)]]
        if not highs or not lows:
            col = 4.0 if all(math.isfinite(x) for x in (op, close, *highs, *lows)) else math.nan
            outputs.append((col, math.nan, math.nan))
            continue
        upper = round(sum(highs) / len(highs), 2)
        lower = round(sum(lows) / len(lows), 2)
        if not all(math.isfinite(x) for x in (op, close, upper, lower)):
            col = math.nan
        elif close > upper:
            col = 3.0 if close >= op else 2.0
        elif close < lower:
            col = 0.0 if close <= op else 1.0
        else:
            col = 4.0
        outputs.append((col, upper, lower))
    return outputs


def _assert_reference(rows):
    for row, expected in zip(rows, _reference(rows)):
        for actual, want in zip(row[-3:], expected):
            if math.isnan(want):
                assert math.isnan(actual), (row, expected)
            else:
                assert actual == pytest.approx(want), (row, expected)


@pytest.mark.parametrize("mode,bounded", [("next", False), ("once", False),
                                            ("next", True), ("replay", False), ("replay", True)])
def test_window_formula_including_partial_prefix_and_bounded_buffer(mode, bounded):
    rows = _run(_frame(), mode=mode, bounded=bounded)
    assert len(rows) == 45
    _assert_reference(rows)
    assert rows[0][-3] == rows[1][-3] == 4.0
    assert math.isfinite(rows[-1][-1])
    if mode == "replay":
        assert any(a[0] == b[0] for a, b in zip(rows, rows[1:]))


@pytest.mark.parametrize("field", ["open", "close", "high", "low"])
@pytest.mark.parametrize("mode,bounded", [("next", False), ("once", False), ("next", True)])
def test_missing_inputs_propagate_and_recover(field, mode, bounded):
    rows = _run(_frame(field), mode=mode, bounded=bounded)
    expected = _reference(rows)
    assert any(math.isnan(row[0]) for row in expected)
    _assert_reference(rows)
    assert math.isfinite(rows[-1][-3])


@pytest.mark.parametrize("field", ["open", "close"])
@pytest.mark.parametrize("bounded", [False, True])
def test_replay_missing_current_price_propagates(field, bounded):
    rows = _run(_frame(field), mode="replay", bounded=bounded)
    expected = _reference(rows)
    assert any(math.isnan(row[0]) for row in expected)
    _assert_reference(rows)
    assert math.isfinite(rows[-1][-3])


@pytest.mark.parametrize("mode", ["next", "replay"])
@pytest.mark.parametrize("params", [
    dict(up_calc_period_range=1, up_calc_period_shift=0,
         dn_calc_period_range=1, dn_calc_period_shift=0),
    dict(up_calc_period_range=5, up_calc_period_shift=6,
         dn_calc_period_range=3, dn_calc_period_shift=3),
    dict(up_calc_period_range=25, up_calc_period_shift=5,
         dn_calc_period_range=7, dn_calc_period_shift=2),
])
def test_bounded_buffer_matches_unbounded_for_distinct_windows(mode, params):
    expected = _run(_frame(), mode=mode, params=params)
    actual = _run(_frame(), mode=mode, bounded=True, params=params)
    assert len(actual) == len(expected) == 45
    for got, want in zip(actual, expected):
        assert got == pytest.approx(want, nan_ok=True)

@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("missing", [False, True])
def test_original_strategy_does_not_trade_on_missing_color(runonce, missing):
    from tests.functional.strategies.mean_reversion.test_0099_0295_exp_rj_slidingrangerj_digit_system_tm_plus import ExpRjSlidingRangeSystemTmPlusStrategy

    class Probe(ExpRjSlidingRangeSystemTmPlusStrategy):
        def __init__(self):
            super().__init__()
            self.entries = []
            self.colors = []

        def _submit_entry(self, side, reason):
            self.entries.append((len(self.signal_feed), side))

        def next(self):
            self.colors.append((len(self.signal_feed), float(self.channel.color_idx[0])))
            super().next()

    index = pd.date_range("2024-01-02 09:00", periods=20, freq="min")
    frame = pd.DataFrame({"open": [100.] * 20, "high": [101.] * 20,
                          "low": [99.] * 20, "close": [100.] * 20,
                          "volume": [10.] * 20, "openinterest": [0.] * 20}, index=index)
    frame.iloc[9, frame.columns.get_loc("open")] = 149.
    frame.iloc[9, frame.columns.get_loc("high")] = 151.
    frame.iloc[9, frame.columns.get_loc("close")] = 150.
    if missing:
        frame.iloc[10, frame.columns.get_loc("open")] = math.nan
    clean_execution = frame.copy()
    clean_execution.iloc[10, clean_execution.columns.get_loc("open")] = 100.
    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(bt.feeds.PandasData(dataname=clean_execution))
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.addstrategy(Probe, time_trade=False)
    result = engine.run(preload=True)[0]
    assert dict(result.colors)[10] == 3.0
    if missing:
        assert math.isnan(dict(result.colors)[11])
        assert not any(bar == 11 for bar, _ in result.entries)
    else:
        assert dict(result.colors)[11] == 4.0
        assert (11, "long") in result.entries

@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("field", ["high", "low"])
def test_strict_factor_rejects_finite_window_sum_overflow(runonce, field):
    from backtrader.errors import FactorComputationError
    from tests.unit.test_factor_research_representatives import _frames

    frame = _frames(periods=25)["asset-0"].copy()
    frame.loc[:, field] = 1e308 if field == "high" else -1e308
    with pytest.raises(FactorComputationError) as caught:
        _strict_run(frame, runonce)
    assert caught.value.code == "FACTOR_COMPUTATION_FAILED"
    assert isinstance(caught.value.__cause__, ArithmeticError)


def _strict_run(frame, runonce):
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    from tests.unit.test_factor_research_representatives import _research_feed, _research_spec

    research = _research_spec({"asset-0": frame})
    instances = []
    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = bt.indicators.SlidingRangeColor(self.data)
            instances.append(self)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.color_idx[0]

    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(_research_feed(frame, research, "asset-0"), name="asset-0")
    spec = FactorSpec(name="sliding", indicator=Factor, panel_line="factor",
                      field_bindings={"close": "feed:target:close"}, mode="native")
    engine.addstrategy(FactorStrategy, research=research, factors={"sliding": spec})
    engine.run(preload=True)
    return instances[0].child.color_idx.array


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("field", ["open", "close", "high", "low"])
def test_strict_factor_preserves_missing_and_recovers(runonce, field):
    from tests.unit.test_factor_research_representatives import _frames

    frame = _frames(periods=25)["asset-0"].copy()
    frame.iloc[12, frame.columns.get_loc(field)] = math.nan
    result = _strict_run(frame, runonce)
    assert math.isfinite(result[11]) and math.isnan(result[12])
    assert math.isfinite(result[17])

@pytest.mark.parametrize("runonce", [False, True])
def test_original_strategy_keeps_valid_previous_breakout_exit_on_current_gap(runonce):
    from tests.functional.strategies.mean_reversion.test_0099_0295_exp_rj_slidingrangerj_digit_system_tm_plus import ExpRjSlidingRangeSystemTmPlusStrategy

    class Probe(ExpRjSlidingRangeSystemTmPlusStrategy):
        def __init__(self):
            super().__init__()
            self.exits = []
            self.colors = []

        def _submit_close(self, reason):
            self.exits.append((len(self.signal_feed), reason, self.position.size))
            return super()._submit_close(reason)

        def next(self):
            self.colors.append((len(self.signal_feed), float(self.channel.color_idx[0])))
            if len(self.signal_feed) == 8:
                self.buy(size=1)
            super().next()

    index = pd.date_range("2024-01-02 09:00", periods=20, freq="min")
    frame = pd.DataFrame({"open": [100.] * 20, "high": [101.] * 20,
                          "low": [99.] * 20, "close": [100.] * 20,
                          "volume": [10.] * 20, "openinterest": [0.] * 20}, index=index)
    frame.iloc[9, frame.columns.get_loc("open")] = 51.
    frame.iloc[9, frame.columns.get_loc("low")] = 49.
    frame.iloc[9, frame.columns.get_loc("close")] = 50.
    frame.iloc[10, frame.columns.get_loc("open")] = math.nan
    clean_execution = frame.copy()
    clean_execution.iloc[10, clean_execution.columns.get_loc("open")] = 100.
    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(bt.feeds.PandasData(dataname=clean_execution))
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.addstrategy(Probe, time_trade=False)
    result = engine.run(preload=True)[0]
    assert dict(result.colors)[10] == 0.0
    assert math.isnan(dict(result.colors)[11])
    assert any(bar == 11 and reason == "channel down breakout close long" and size > 0
               for bar, reason, size in result.exits)

@pytest.mark.parametrize("bounded", [False, True])
def test_two_feeds_keep_independent_window_history(bounded):
    first = _frame()
    second = _frame().copy()
    for field in ("open", "high", "low", "close"):
        second[field] += 50.0
    first_params = dict(up_calc_period_range=4, up_calc_period_shift=1,
                        dn_calc_period_range=3, dn_calc_period_shift=2)
    second_params = dict(up_calc_period_range=8, up_calc_period_shift=3,
                         dn_calc_period_range=2, dn_calc_period_shift=0)
    expected_first = _run(first, bounded=bounded, params=first_params)
    expected_second = _run(second, bounded=bounded, params=second_params)

    class Probe(bt.Strategy):
        def __init__(self):
            self.a = bt.indicators.SlidingRangeColor(self.datas[0], **first_params)
            self.b = bt.indicators.SlidingRangeColor(self.datas[1], **second_params)
            self.rows = []

        def next(self):
            self.rows.append(tuple(float(getattr(ind, field)[0])
                                   for ind in (self.a, self.b)
                                   for field in ("color_idx", "upper", "lower")))

    engine = bt.Cerebro(stdstats=False, runonce=False, preload=not bounded,
                        exactbars=int(bounded))
    engine.adddata(bt.feeds.PandasData(dataname=first))
    engine.adddata(bt.feeds.PandasData(dataname=second))
    engine.addstrategy(Probe)
    rows = engine.run()[0].rows
    assert len(rows) == len(expected_first) == len(expected_second) == 45
    for got, a, b in zip(rows, expected_first, expected_second):
        assert got == pytest.approx(a[-3:] + b[-3:], nan_ok=True)
