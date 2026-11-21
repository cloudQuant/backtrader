"""MUV cloud uses complete finite delta windows in both execution modes."""

import datetime as dt
import math

import backtrader as bt
import pytest

from backtrader.indicators.contrib.muv_nor_diff_cloud_indicator import _cloud_values


class _CloseFeed(bt.feed.DataBase):
    params = (("price_values", ()), ("day_step", 1))

    def __init__(self):
        super().__init__()
        self.index = 0

    def _load(self):
        if self.index == len(self.p.price_values):
            return False
        value = self.p.price_values[self.index]
        self.datetime[0] = bt.date2num(
            dt.datetime(2020, 1, 1) + dt.timedelta(days=self.index * self.p.day_step)
        )
        self.open[0] = self.high[0] = self.low[0] = self.close[0] = value
        self.volume[0], self.openinterest[0] = 1.0, 0.0
        self.index += 1
        return True


def _prices(count):
    return [100.0 + i * .08 + 3.0 * math.sin(i * .27) + (i % 7) * .13 for i in range(count)]


def _reference(values, ma_period, momentum, kperiod):
    """Calculate SMA, SMA-seeded EMA and complete delta windows directly."""
    n = len(values)
    sma = [math.nan] * n
    ema = [math.nan] * n
    for i in range(ma_period - 1, n):
        sma[i] = sum(values[i - ma_period + 1:i + 1]) / ma_period
    if n >= ma_period:
        ema[ma_period - 1] = sum(values[:ma_period]) / ma_period
        alpha = 2.0 / (ma_period + 1.0)
        for i in range(ma_period, n):
            ema[i] = ema[i - 1] * (1.0 - alpha) + values[i] * alpha
    return _reference_cloud(sma, ema, ma_period + momentum + kperiod + 5, momentum, kperiod)


def _reference_cloud(sma, ema, minperiod, momentum, kperiod):
    result = {name: [math.nan] * len(sma) for name in ("buy", "sell", "sma_res", "ema_res")}
    for index in range(minperiod - 1, len(sma)):
        deltas = []
        for series in (sma, ema):
            deltas.append([series[index - j] - series[index - j - momentum] for j in range(kperiod)])
        if not all(math.isfinite(value) for window in deltas for value in window):
            result["buy"][index] = result["sell"][index] = 0.0
            continue
        normalized = []
        for window in deltas:
            upper, lower = max(window), min(window)
            normalized.append(100.0 - 200.0 * (upper - window[0]) / (upper - lower)
                              if upper > lower else 100.0)
        result["sma_res"][index], result["ema_res"][index] = normalized
        result["buy"][index] = 100.0 if 100.0 in normalized else 0.0
        result["sell"][index] = -100.0 if -100.0 in normalized else 0.0
    return result


def _run(values, runonce, *, ma_period=14, momentum=1, kperiod=14, multifeed=False):
    class Probe(bt.Strategy):
        def __init__(self):
            data = self.datas[1] if multifeed else self.data
            self.ind = bt.indicators.MUVNorDiffCloudIndicator(
                data, ma_period=ma_period, momentum=momentum, kperiod=kperiod
            )

        def stop(self):
            self.output = {name: list(getattr(self.ind, name).array)
                           for name in self.ind.lines.getlinealiases()}

    engine = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    if multifeed:
        engine.adddata(_CloseFeed(price_values=_prices(len(values) * 3)))
    engine.adddata(_CloseFeed(price_values=values, day_step=3 if multifeed else 1))
    engine.addstrategy(Probe)
    return engine.run(runonce=runonce, preload=True)[0]


def _assert_output(actual, expected):
    assert actual.keys() == expected.keys()
    for name in expected:
        assert actual[name] == pytest.approx(expected[name], rel=1e-11, abs=1e-11, nan_ok=True)


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
@pytest.mark.parametrize("gap", [None, 2, 60])
@pytest.mark.parametrize("ma_period,momentum,kperiod", [(14, 1, 14), (5, 2, 4)])
def test_complete_window_and_missing_close(runonce, gap, ma_period, momentum, kperiod):
    values = _prices(120)
    if gap is not None:
        values[gap] = math.nan
    result = _run(values, runonce, ma_period=ma_period, momentum=momentum, kperiod=kperiod)
    assert result.ind._minperiod == ma_period + momentum + kperiod + 5
    _assert_output(result.output, _reference(values, ma_period, momentum, kperiod))
    if gap == 60:
        assert all(value == 0.0 for value in result.output["buy"][60:])
        assert all(value == 0.0 for value in result.output["sell"][60:])
        assert all(math.isnan(value) for value in result.output["ema_res"][60:])


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
@pytest.mark.parametrize("count", [5, 33, 34])
def test_short_history_and_first_complete_value(runonce, count):
    values = _prices(count)
    result = _run(values, runonce)
    _assert_output(result.output, _reference(values, 14, 1, 14))


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_secondary_feed_clock(runonce):
    values = _prices(80)
    values[60] = math.nan
    result = _run(values, runonce, ma_period=5, momentum=2, kperiod=4, multifeed=True)
    _assert_output(result.output, _reference(values, 5, 2, 4))


@pytest.mark.parametrize("missing_line", ["sma", "ema", "both"])
def test_once_segments_preserve_unrequested_and_resume_when_inputs_recover(missing_line):
    result = _run(_prices(100), True, ma_period=5, momentum=2, kperiod=4)
    indicator = result.ind
    sma, ema = indicator._sma.array, indicator._ema.array
    if missing_line in ("sma", "both"):
        sma[50] = math.nan
    if missing_line in ("ema", "both"):
        ema[50] = math.nan
    expected = _reference_cloud(list(sma), list(ema), indicator._minperiod, 2, 4)
    for line in indicator.lines:
        for index in range(len(line.array)):
            line.array[index] = -999.0
    indicator.once(45, 53)
    indicator.once(53, 70)
    for name in expected:
        actual = list(getattr(indicator, name).array)
        assert actual[:45] == [-999.0] * 45
        assert actual[70:] == [-999.0] * 30
        assert actual[45:70] == pytest.approx(expected[name][45:70], rel=1e-11, abs=1e-11, nan_ok=True)
    assert all(indicator.buy.array[index] == indicator.sell.array[index] == 0.0 for index in range(50, 56))
    assert math.isfinite(indicator.sma_res.array[56])
    assert math.isfinite(indicator.ema_res.array[56])


@pytest.mark.parametrize("sma", [[0.0, 1e307], [-1e308, 1e308]])
def test_finite_deltas_with_overflowing_normalization_emit_no_signal(sma):
    buy, sell, sma_res, ema_res = _cloud_values(sma, [1.0, 0.0])
    assert buy == sell == 0.0
    assert math.isnan(sma_res) and math.isnan(ema_res)


def test_finite_deltas_with_infinite_range_cannot_fake_a_signal():
    buy, sell, sma_res, ema_res = _cloud_values(
        [9.99e307, 1e308, -1e308], [0.0, 1.0, -1.0]
    )
    assert buy == sell == 0.0
    assert math.isnan(sma_res) and math.isnan(ema_res)


def test_real_once_range_overflow_cannot_fake_a_signal():
    result = _run(_prices(100), True, ma_period=5, momentum=1, kperiod=3)
    indicator = result.ind
    for index, value in enumerate([0.0, -1e308, 0.0, 9.99e307], start=47):
        indicator._sma.array[index] = value
    for index, value in enumerate([0.0, -1.0, 0.0, 0.0], start=47):
        indicator._ema.array[index] = value
    indicator.once(50, 51)
    assert indicator.buy.array[50] == indicator.sell.array[50] == 0.0
    assert math.isnan(indicator.sma_res.array[50])
    assert math.isnan(indicator.ema_res.array[50])


def test_real_next_range_overflow_cannot_fake_a_signal():
    result = _run(_prices(100), False, ma_period=5, momentum=1, kperiod=3)
    indicator = result.ind
    end = len(indicator._sma.array)
    for index, value in enumerate([0.0, -1e308, 0.0, 9.99e307], start=end - 4):
        indicator._sma.array[index] = value
    for index, value in enumerate([0.0, -1.0, 0.0, 0.0], start=end - 4):
        indicator._ema.array[index] = value
    indicator.next()
    assert indicator.buy[0] == indicator.sell[0] == 0.0
    assert math.isnan(indicator.sma_res[0])
    assert math.isnan(indicator.ema_res[0])


@pytest.mark.parametrize("runonce,phase", [(False, "next"), (True, "once")])
@pytest.mark.parametrize("line", ["buy", "sma_res"])
def test_strict_factor_rejects_intermediate_range_overflow(runonce, phase, line):
    from backtrader.errors import FactorComputationError
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    from tests.unit.test_factor_research_representatives import _frames, _research_feed, _research_spec

    frame = _frames(periods=40)["asset-0"].copy()
    frame.loc[:, "close"] = 0.0
    for index, value in zip((17, 18, 19, 20), (0.0, -1e308, 0.0, 9.99e307)):
        frame.iloc[index, frame.columns.get_loc("close")] = value
    research = _research_spec({"asset-0": frame})

    class MUVFactor(FactorIndicator):
        lines = ("factor",)
        formula_fields = ("close",)
        required_fields = formula_fields
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = bt.indicators.MUVNorDiffCloudIndicator(
                self.data, ma_period=1, momentum=1, kperiod=3
            )

        def next(self):
            self.outputs[self.datas[0]].factor[0] = getattr(self.child, line)[0]

    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(_research_feed(frame, research, "asset-0"), name="asset-0")
    spec = FactorSpec(name="muv", indicator=MUVFactor, panel_line="factor",
                      field_bindings={"close": "feed:target:close"}, mode="native")
    engine.addstrategy(FactorStrategy, research=research, factors={"muv": spec})
    with pytest.raises(FactorComputationError) as caught:
        engine.run(preload=True)
    assert caught.value.code == "FACTOR_COMPUTATION_FAILED"
    assert caught.value.phase == phase
    assert isinstance(caught.value.__cause__, ArithmeticError)


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_strict_factor_missing_input_remains_neutral(runonce):
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    from tests.unit.test_factor_research_representatives import _frames, _research_feed, _research_spec

    frame = _frames(periods=40)["asset-0"].copy()
    frame.iloc[20, frame.columns.get_loc("close")] = math.nan
    research = _research_spec({"asset-0": frame})

    class MUVFactor(FactorIndicator):
        lines = ("factor",)
        formula_fields = ("close",)
        required_fields = formula_fields
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = bt.indicators.MUVNorDiffCloudIndicator(
                self.data, ma_period=1, momentum=1, kperiod=3
            )

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.buy[0]

    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(_research_feed(frame, research, "asset-0"), name="asset-0")
    spec = FactorSpec(name="muv", indicator=MUVFactor, panel_line="factor",
                      field_bindings={"close": "feed:target:close"}, mode="native")
    engine.addstrategy(FactorStrategy, research=research, factors={"muv": spec})
    result = engine.run(preload=True)[0].factor_instances["muv"].child
    assert result.buy.array[20] == result.sell.array[20] == 0.0
    assert math.isnan(result.sma_res.array[20]) and math.isnan(result.ema_res.array[20])
