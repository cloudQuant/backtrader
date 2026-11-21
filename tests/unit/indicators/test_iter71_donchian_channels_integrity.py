"""Donchian color must not turn incomplete prices into a trading signal."""

import math

import pandas as pd
import pytest

import backtrader as bt
from backtrader.indicators.contrib.donchian_channels_system import DonchianChannelsSystem


PERIOD, SHIFT, MARGINS = 3, 1, 0


def _frame(n=36):
    # Both sides of the channel and both candle directions occur.
    closes = [10 + (0, 2, 4, -2, -4, 0)[i % 6] for i in range(n)]
    opens = [c + (1 if i % 2 else -1) for i, c in enumerate(closes)]
    return pd.DataFrame(
        dict(open=opens, high=[max(o, c) + 0.5 for o, c in zip(opens, closes)],
             low=[min(o, c) - 0.5 for o, c in zip(opens, closes)], close=closes,
             volume=[1.0] * n),
        index=pd.date_range("2024-01-01", periods=n, freq="min"),
    ).astype(float)


def _reference(open_, close, highs, lows, margins=MARGINS):
    if not all(math.isfinite(x) for x in [open_, close, *highs, *lows]):
        return math.nan
    hi, lo = max(highs), min(lows)
    lower = lo + (hi - lo) * margins / 100
    upper = hi - (hi - lo) * margins / 100
    if not math.isfinite(lower) or not math.isfinite(upper):
        return math.nan
    result = 4.0 if open_ <= close else 3.0
    result = result if close > upper else 2.0
    if close < lower:
        return 0.0 if open_ > close else 1.0
    return result


def _assert_equal(actual, expected):
    if math.isnan(expected):
        assert math.isnan(actual)
    else:
        assert actual == expected


def _run(frame, runonce, *, replay=False, second_feed=False, inject=None, margins=MARGINS,
         indicator_cls=DonchianChannelsSystem):
    class InjectingFeed(bt.feeds.PandasData):
        def _load(self):
            loaded = super()._load()
            if loaded and inject is not None and len(self) == 16:
                line = getattr(self.lines, inject[0])
                # Deliberately inject after line assignment to exercise the
                # indicator's contract for values that reach its buffer.
                line.array[line.idx] = inject[1]
            return loaded

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = indicator_cls(
                self.datas[0], period=PERIOD, shift=SHIFT, margins=margins
            )
            self.rows = []

        def next(self):
            data = self.datas[0]
            high = [float(data.high[-(SHIFT + i)]) for i in range(PERIOD)]
            low = [float(data.low[-(SHIFT + i)]) for i in range(PERIOD)]
            self.rows.append((len(data), float(data.open[0]), float(data.close[0]),
                              high, low, float(self.ind.color[0])))

    cerebro = bt.Cerebro(stdstats=False)
    feed = InjectingFeed(dataname=frame, timeframe=bt.TimeFrame.Minutes)
    if replay:
        cerebro.replaydata(feed, timeframe=bt.TimeFrame.Minutes, compression=3)
    else:
        cerebro.adddata(feed)
    if second_feed:
        other = _frame(len(frame)).copy()
        for col in ("open", "high", "low", "close"):
            other[col] += 1000
        cerebro.adddata(bt.feeds.PandasData(dataname=other, timeframe=bt.TimeFrame.Minutes))
    cerebro.addstrategy(Probe)
    return cerebro.run(runonce=runonce, preload=True)[0].rows


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("field", ["open", "close", "high", "low"])
def test_missing_input_and_recovery(runonce, field):
    frame = _frame()
    rows = _run(frame, runonce, inject=(field, float("nan")))
    for length, open_, close, highs, lows, actual in rows:
        # The upstream feed projection is observed explicitly; comparison only
        # asserts information that actually reached this indicator.
        _assert_equal(actual, _reference(open_, close, highs, lows))
        if field in ("open", "close") and length == 16:
            assert math.isnan(actual)
        if field in ("high", "low") and 17 <= length <= 19:
            assert math.isnan(actual)
    assert math.isfinite(rows[-1][-1])


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("missing", [float("inf"), -float("inf")])
def test_pandas_feed_can_project_infinity_before_indicator(runonce, missing):
    frame = _frame()
    frame.loc[frame.index[15], "close"] = missing
    row = next(row for row in _run(frame, runonce) if row[0] == 16)
    # PandasData currently transforms this input into a finite close. This is
    # upstream behavior; the indicator cannot reject the original value.
    assert math.isfinite(row[2])
    _assert_equal(row[-1], _reference(row[1], row[2], row[3], row[4]))


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("margins", [0, -2, 60])
def test_clean_formula_and_multifeed_binding(runonce, margins):
    frame = _frame()
    single = _run(frame, runonce, margins=margins)
    multi = _run(frame, runonce, second_feed=True, margins=margins)
    assert [row[-1] for row in single] == [row[-1] for row in multi]
    if margins == 0:
        assert {row[-1] for row in single} == {0., 1., 2., 3., 4.}
    for length, open_, close, highs, lows, actual in single:
        pos = length - 1
        assert highs == list(frame.high.iloc[pos - SHIFT - PERIOD + 1:pos - SHIFT + 1][::-1])
        assert lows == list(frame.low.iloc[pos - SHIFT - PERIOD + 1:pos - SHIFT + 1][::-1])
        _assert_equal(actual, _reference(open_, close, highs, lows, margins))


def test_replay_each_update_matches_current_aggregated_window():
    rows = _run(_frame(90), False, replay=True)
    assert len(rows) > len({row[0] for row in rows})
    for _, open_, close, highs, lows, actual in rows:
        _assert_equal(actual, _reference(open_, close, highs, lows))


@pytest.mark.parametrize("runonce", [False, True])
def test_finite_parameter_conversion_remains_once_per_boundary(runonce):
    class ChangingMargins:
        def __init__(self):
            self.calls = 0

        def __float__(self):
            self.calls += 1
            return -2.0 if self.calls % 2 else 60.0

    margins = ChangingMargins()
    rows = _run(_frame(), runonce, margins=margins)
    assert margins.calls == 2 * len(rows)
    for _, open_, close, highs, lows, actual in rows:
        high, low = max(highs), min(lows)
        lower = low + (high - low) * -2.0 / 100.0
        upper = high - (high - low) * 60.0 / 100.0
        expected = 4.0 if close > upper and open_ <= close else 3.0 if close > upper else 2.0
        if close < lower:
            expected = 0.0 if open_ > close else 1.0
        assert actual == expected


@pytest.mark.parametrize("runonce", [False, True])
def test_valid_input_read_and_parameter_conversion_order(runonce, monkeypatch):
    from backtrader.linebuffer import LineBuffer

    recorded = []
    state = {"active": False, "lines": {}, "events": None}
    original_getitem = LineBuffer.__getitem__

    def getitem(line, ago):
        if state["active"]:
            for name, expected in state["lines"].items():
                if line is expected:
                    state["events"].append(name)
                    break
        return original_getitem(line, ago)

    class TracedMargins:
        def __float__(self):
            if state["active"]:
                state["events"].append("margins")
            return 0.0

    class TracedChannel(DonchianChannelsSystem):
        def next(self):
            state["lines"] = {name: getattr(self.data, name)
                              for name in ("high", "low", "close", "open")}
            events = []
            state["events"], state["active"] = events, True
            try:
                super().next()
            finally:
                state["active"] = False
            recorded.append((len(self.data), events))

    monkeypatch.setattr(LineBuffer, "__getitem__", getitem)
    _run(_frame(), runonce, inject=("high", math.nan),
         margins=TracedMargins(), indicator_cls=TracedChannel)
    valid_order = ["high"] * PERIOD + ["low"] * PERIOD + ["margins"] * 2 + ["close", "open"]
    assert recorded
    for length, events in recorded:
        if 17 <= length <= 19:
            # An incomplete historical channel intentionally stops before the
            # parameter or current candle is read.
            assert events == ["high"] * PERIOD + ["low"] * PERIOD
        else:
            assert events == valid_order


@pytest.mark.parametrize("runonce", [False, True])
def test_finite_input_channel_arithmetic_overflow_is_not_signal(runonce):
    frame = _frame()
    frame.loc[frame.index[15], "high"] = 1e308
    frame.loc[frame.index[15], "low"] = -1e308
    rows = _run(frame, runonce)
    assert all(math.isnan(row[-1]) for row in rows if 17 <= row[0] <= 19)
    assert math.isfinite(rows[-1][-1])


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("case", ["span", "scaled", "bound", "missing", "margin_posinf", "margin_neginf", "margin_nan"])
def test_real_factor_strict_context_overflow_and_missing(runonce, case):
    from backtrader.errors import FactorComputationError
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    frame = _frame(36)
    frame.index = frame.index.tz_localize("UTC")
    if case == "span":
        frame.loc[:, "high"] = 1e308
        frame.loc[:, "low"] = -1e308
    elif case == "scaled":
        frame.loc[:, "high"] = 1e307
        frame.loc[:, "low"] = 0.0
    elif case == "bound":
        frame.loc[:, "high"] = 1.795e308
        frame.loc[:, "low"] = 1.79e308
    elif case == "missing":
        frame.loc[frame.index[15], "high"] = math.nan
    else:
        frame.loc[:, "high"] = 10.0
        frame.loc[:, "low"] = 10.0

    index = frame.index.rename("close_time")
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(minutes=1)}, index=index),
        start=index[0], end=index[-1], targets=("asset",), source_timezone="UTC",
        snapshot_id="donchian-strict-test", price_basis="synthetic",
        calendar_id="synthetic", frequency="1min", feed_time_kind="close_time",
        groups={"asset": "market"},
    )
    seen, values = [], []

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("open", "high", "low", "close")
        lookback_h = 0

        def __init__(self):
            super().__init__()
            margins = {"span": 0, "scaled": 100, "bound": -100,
                       "margin_posinf": math.inf, "margin_neginf": -math.inf,
                       "margin_nan": math.nan}.get(case, 0)
            self.child = DonchianChannelsSystem(self.data, period=3, shift=1, margins=margins)
            seen.append(self)

        def next(self):
            values.append(float(self.child.color[0]))
            self.outputs[self.datas[0]].factor[0] = self.child.color[0]

    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(align_to_grid(frame, research, "asset").feed, name="asset")
    bindings = {field: "feed:target:" + field for field in Factor.formula_fields}
    spec = FactorSpec(name="donchian", indicator=Factor, panel_line="factor",
                      field_bindings=bindings, mode="native")
    engine.addstrategy(FactorStrategy, research=research, factors={"donchian": spec})
    if case in ("missing", "margin_nan"):
        engine.run(preload=True)
        assert seen and not seen[0]._factor_strict_context.failed
        assert any(math.isnan(value) for value in values)
        if case == "missing":
            assert math.isfinite(values[-1])
        else:
            assert all(math.isnan(value) for value in values)
    else:
        with pytest.raises(FactorComputationError) as caught:
            engine.run(preload=True)
        assert caught.value.code == "FACTOR_COMPUTATION_FAILED"
        assert isinstance(caught.value.__cause__, ArithmeticError)
        assert seen and seen[0]._factor_strict_context.failed


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("margins", [math.inf, -math.inf, math.nan])
def test_nonfinite_margins_in_plain_mode_are_missing(runonce, margins):
    frame = _frame()
    frame.loc[:, "high"] = 10.0
    frame.loc[:, "low"] = 10.0
    rows = _run(frame, runonce, margins=margins)
    assert rows and all(math.isnan(row[-1]) for row in rows)
