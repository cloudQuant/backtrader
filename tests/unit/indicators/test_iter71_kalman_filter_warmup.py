"""KalmanFilterIndicator first real callback and recurrence on synthetic bars."""

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.kalman_filter_indicator import KalmanFilterIndicator


def _frame(count, *, missing=None, every="D"):
    close = [100.0 + 0.7 * i + 2.0 * math.sin(i * 0.5) for i in range(count)]
    if missing is not None:
        close[missing] = math.nan
    return pd.DataFrame(
        {
            "open": [v - 0.3 for v in close],
            "high": [v + 1.0 for v in close],
            "low": [v - 0.5 for v in close],
            "close": close,
            "volume": [100.0] * count,
        },
        index=pd.date_range("2024-01-01", periods=count, freq=every),
    )


def _expected(frame, *, k, shift, mode):
    prices = (2.0 * frame.close + frame.high + frame.low) / 4.0
    values = [math.nan] * len(prices)
    colors = [math.nan] * len(prices)
    if len(prices) < 2:
        return values, colors
    values[1] = float(prices.iloc[1])
    colors[1] = 0.0 if math.isfinite(values[1]) else math.nan
    velocity = 0.0
    for i in range(2, len(prices)):
        previous = values[i - 1]
        distance = float(prices.iloc[i]) - previous
        velocity += distance * (k / 100.0)
        values[i] = previous + distance * math.sqrt(k / 100.0) + velocity + shift
        if not math.isfinite(values[i]):
            colors[i] = math.nan
        elif mode == "Trend":
            colors[i] = 0.0 if previous > values[i] else 1.0
        else:
            colors[i] = 1.0 if velocity > 0 else 0.0
    return values, colors


def _run(frame, *, runonce, k=1.0, shift=0, mode="Kalman", primary=None):
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = KalmanFilterIndicator(
                self.datas[-1], k=k, point=0.25, price_shift=shift, signal_mode=mode
            )

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    if primary is not None:
        cerebro.adddata(bt.feeds.PandasData(dataname=primary))
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Probe)
    return cerebro.run()[0].indicator


def _assert_series(actual, expected):
    assert len(actual) == len(expected)
    for a, e in zip(actual, expected):
        if math.isnan(e):
            assert math.isnan(a)
        else:
            assert a == pytest.approx(e, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("k,shift,mode", [(1.0, 0, "Kalman"), (4.0, 3, "Trend")])
def test_first_callback_seeds_and_complete_sequence_matches_reference(runonce, k, shift, mode):
    frame = _frame(60)
    indicator = _run(frame, runonce=runonce, k=k, shift=shift, mode=mode)
    assert indicator._minperiod == 2
    expected = _expected(frame, k=k, shift=0.25 * shift, mode=mode)
    _assert_series(indicator.value.array, expected[0])
    _assert_series(indicator.color_idx.array, expected[1])
    assert math.isfinite(indicator.value.array[1])


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("count", [1, 2])
def test_short_history_stays_unseeded_until_first_real_callback(runonce, count):
    frame = _frame(count)
    indicator = _run(frame, runonce=runonce)
    expected = _expected(frame, k=1.0, shift=0.0, mode="Kalman")
    _assert_series(indicator.value.array, expected[0])
    _assert_series(indicator.color_idx.array, expected[1])


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("missing", [1, 8], ids=["seed", "later"])
@pytest.mark.parametrize("mode", ["Kalman", "Trend"])
def test_missing_price_is_not_silently_reseeded(runonce, missing, mode):
    frame = _frame(30, missing=missing)
    indicator = _run(frame, runonce=runonce, mode=mode)
    expected = _expected(frame, k=1.0, shift=0.0, mode=mode)
    _assert_series(indicator.value.array, expected[0])
    _assert_series(indicator.color_idx.array, expected[1])
    assert all(math.isnan(v) for v in indicator.value.array[missing:])
    assert all(math.isnan(v) for v in indicator.color_idx.array[missing:])
    if missing > 1:
        assert math.isfinite(indicator.color_idx.array[missing - 1])


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_secondary_feed_uses_its_own_clock(runonce):
    frame = _frame(30, every="3D")
    indicator = _run(frame, runonce=runonce, primary=_frame(90))
    expected = _expected(frame, k=1.0, shift=0.0, mode="Kalman")
    _assert_series(indicator.value.array, expected[0])
    _assert_series(indicator.color_idx.array, expected[1])


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_subclass_previous_finite_value_is_not_replaced_by_seed(runonce):
    class CustomWarmup(KalmanFilterIndicator):
        def prenext(self):
            self.lines.value[0] = 90.0

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = CustomWarmup(self.data)

    frame = _frame(2)
    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Probe)
    indicator = cerebro.run()[0].indicator
    row = frame.iloc[1]
    price = (2.0 * row.close + row.high + row.low) / 4.0
    assert indicator.value.array[1] == pytest.approx(90.0 + 0.11 * (price - 90.0))
    assert indicator.color_idx.array[1] == 1.0


def test_replayed_first_bar_reseeds_each_update_without_losing_previous_price():
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = KalmanFilterIndicator(self.data)
            self.first_bar_updates = []

        def next(self):
            if len(self.data) == 2:
                price = (2 * self.data.close[0] + self.data.high[0] + self.data.low[0]) / 4
                self.first_bar_updates.append(
                    (float(self.indicator.value[0]), float(self.indicator.color_idx[0]), float(price))
                )

    cerebro = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    cerebro.replaydata(
        bt.feeds.PandasData(dataname=_frame(40, every="min")),
        timeframe=bt.TimeFrame.Minutes,
        compression=5,
    )
    cerebro.addstrategy(Probe)
    updates = cerebro.run()[0].first_bar_updates
    assert len(updates) > 1
    for actual, color, price in updates:
        assert actual == pytest.approx(price)
        assert color == 0.0


def test_replay_recomputes_each_revision_from_completed_bar_state():
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = KalmanFilterIndicator(self.data)
            self.rows = []

        def next(self):
            price = (2 * self.data.close[0] + self.data.high[0] + self.data.low[0]) / 4
            self.rows.append((len(self.data), float(price), float(self.indicator.value[0])))

    cerebro = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    cerebro.replaydata(
        bt.feeds.PandasData(dataname=_frame(80, every="min")),
        timeframe=bt.TimeFrame.Minutes,
        compression=5,
    )
    cerebro.addstrategy(Probe)
    rows = cerebro.run()[0].rows
    assert any(a[0] == b[0] for a, b in zip(rows, rows[1:]))
    bar = None
    previous_value = previous_velocity = None
    current_value = current_velocity = None
    for length, price, actual in rows:
        if length != bar:
            previous_value, previous_velocity = current_value, current_velocity
            bar = length
        if length == 2:
            current_value, current_velocity = price, 0.0
        else:
            distance = price - previous_value
            current_velocity = previous_velocity + distance * 0.01
            current_value = previous_value + distance * 0.1 + current_velocity
        assert actual == pytest.approx(current_value, rel=1e-12, abs=1e-12)

@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("overflow", [False, True], ids=["finite", "overflow"])
@pytest.mark.parametrize("output", ["value", "color_idx"])
def test_strict_factor_context_observes_filter_output(runonce, overflow, output):
    from backtrader.errors import FactorComputationError
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    from tests.unit.test_factor_research_representatives import _frames, _research_feed, _research_spec

    frame = _frames(periods=25)["asset-0"].copy()
    if overflow:
        for field in ("open", "high", "low", "close"):
            frame.loc[:, field] = 1e308
    research = _research_spec({"asset-0": frame})

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = KalmanFilterIndicator(self.data)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = getattr(self.child, output)[0]

    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(_research_feed(frame, research, "asset-0"), name="asset-0")
    spec = FactorSpec(name="kalman", indicator=Factor, panel_line="factor",
                      field_bindings={"close": "feed:target:close"}, mode="native")
    engine.addstrategy(FactorStrategy, research=research, factors={"kalman": spec})
    if overflow:
        with pytest.raises(FactorComputationError) as caught:
            engine.run(preload=True)
        assert caught.value.code == "FACTOR_COMPUTATION_FAILED"
        assert isinstance(caught.value.__cause__, ArithmeticError)
    else:
        engine.run(preload=True)


@pytest.mark.parametrize("mode", ["Kalman", "Trend"])
@pytest.mark.parametrize("missing_index", [2, 8], ids=["seed_revision", "later_revision"])
def test_replay_invalid_revision_recovers_within_same_bar(mode, missing_index):
    frame = _frame(35, every="min")
    frame.iloc[missing_index, frame.columns.get_loc("close")] = math.nan

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = KalmanFilterIndicator(self.data, applied_price="PRICE_CLOSE", signal_mode=mode)
            self.rows = []

        def next(self):
            self.rows.append((len(self.data), float(self.data.close[0]),
                              float(self.indicator.value[0]), float(self.indicator.color_idx[0])))

    engine = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    engine.replaydata(bt.feeds.PandasData(dataname=frame),
                      timeframe=bt.TimeFrame.Minutes, compression=5)
    engine.addstrategy(Probe)
    rows = engine.run()[0].rows
    invalid = [i for i, row in enumerate(rows) if math.isnan(row[1])]
    assert len(invalid) == 1
    index = invalid[0]
    bar, _, value, color = rows[index]
    assert math.isnan(value) and math.isnan(color)
    assert rows[index + 1][0] == bar
    assert all(math.isfinite(v) for v in rows[index + 1][1:])
