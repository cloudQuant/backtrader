"""Recover the retired 026 ROC gates and KDJ intermediate-line contract.

Only synthetic bars are used; the oracle is calculated directly from the bars.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import backtrader as bt
import pandas as pd
import pytest

from backtrader.errors import FactorComputationError
from backtrader.research import FactorSpec, ResearchSpec, align_to_grid
from backtrader.strategies.factor_strategy import FactorStrategy

_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "examples/backtest/026_factor_multi/multi_factor_strategy.py"
)
_SPEC = importlib.util.spec_from_file_location("iter61_edge_multi", _SOURCE)
_MULTI = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MULTI
_SPEC.loader.exec_module(_MULTI)


def _bars(count=40):
    index = pd.date_range("2025-01-01 16:00", periods=count, freq="D", tz="UTC", name="close_time")
    rows = []
    for i in range(count):
        if i < 15:
            rows.append((100.0, 100.0, 100.0, 100.0, 1000.0 + i))
        else:
            close = 100.0 + 0.7 * i + 0.13 * ((i % 5) - 2)
            rows.append((close - 0.2, close + 0.8, close - 0.6, close, 1000.0 + i))
    return pd.DataFrame(rows, columns=("open", "high", "low", "close", "volume"), index=index)


def _run(frame, name, factor_class, params, mode, runonce, strict=True):
    index = frame.index
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index),
        start=index[0],
        end=index[-1],
        targets=("A",),
        source_timezone="UTC",
        snapshot_id="iter61-edge-synthetic",
        price_basis="synthetic",
        calendar_id="synthetic",
        frequency="1day",
        groups={"A": "all"},
    )
    factor = FactorSpec(
        name=name,
        indicator=factor_class,
        panel_line="factor",
        mode=mode,
        params=params,
        field_bindings={field: "feed:target:" + field for field in factor_class.formula_fields},
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(align_to_grid(frame, research, "A").feed, name="A")
    if strict:
        cerebro.addstrategy(FactorStrategy, research=research, factors={name: factor})
    else:

        class NonStrictFactorStrategy(bt.Strategy):
            def __init__(self):
                instance = factor_class._bind_for_research(
                    *self.datas,
                    output_datas=self.datas,
                    asset_names=("A",),
                    factor_name=name,
                    field_bindings=factor.field_bindings,
                    research=research,
                    available_datas=self.datas,
                    strict=False,
                    mode=mode,
                    **params,
                )
                self.factor_instances = {name: instance}

        cerebro.addstrategy(NonStrictFactorStrategy)
    strategy = cerebro.run(runonce=runonce, preload=True)[0]
    instance = strategy.factor_instances[name]
    assert instance.factor_mode == mode
    return strategy, instance


def _line(line, count):
    return [float(value) for value in line.get(size=count)]


def _assert_series(actual, expected):
    assert len(actual) == len(expected)
    assert any(math.isfinite(value) for value in expected)
    for i, (observed, wanted) in enumerate(zip(actual, expected)):
        assert not math.isinf(observed), i
        assert math.isnan(observed) == math.isnan(wanted), i
        if math.isfinite(wanted):
            assert observed == pytest.approx(wanted, rel=1e-12, abs=1e-12), i


def _roc_expected(frame):
    closes = frame.close.to_list()
    out = [math.nan]
    for previous, current in zip(closes, closes[1:]):
        value = math.nan
        if math.isfinite(previous) and math.isfinite(current) and previous != 0.0:
            candidate = (current - previous) / previous
            if math.isfinite(candidate):
                value = candidate
        out.append(value)
    return out


@pytest.mark.parametrize(
    "scenario", ("difference-overflow", "division-overflow", "zero", "nan", "normal")
)
@pytest.mark.parametrize("strict", (True, False), ids=("strict", "non-strict"))
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_roc_strict_and_non_strict_edge_gates(scenario, strict, runonce):
    frame = _bars(18)
    if scenario == "difference-overflow":
        frame.loc[frame.index[:2], "close"] = [-1.7e308, 1.7e308]
    elif scenario == "division-overflow":
        frame.loc[frame.index[:2], "close"] = [1e-309, 1.0]
    elif scenario == "zero":
        frame.loc[frame.index[:2], "close"] = [0.0, 10.0]
    elif scenario == "nan":
        frame.loc[frame.index[3], "close"] = math.nan
    expected = _roc_expected(frame)
    assert any(math.isfinite(value) for value in expected)
    if scenario != "normal":
        assert math.isnan(expected[1 if scenario != "nan" else 3])
    if scenario == "nan":
        assert math.isnan(expected[4]) and math.isfinite(expected[5])
    outcomes = []
    for mode in ("native", "build"):
        if strict and scenario.endswith("overflow"):
            with pytest.raises(FactorComputationError) as caught:
                _run(frame, "roc", _MULTI.ROCFactor, {"period": 1}, mode, runonce, strict)
            assert caught.value.factor == "roc"
            assert caught.value.asset == "A"
            assert isinstance(caught.value.__cause__, ArithmeticError)
            outcomes.append(caught.value.phase)
        else:
            strategy, instance = _run(
                frame, "roc", _MULTI.ROCFactor, {"period": 1}, mode, runonce, strict
            )
            actual = _line(instance.outputs[strategy.datas[0]].factor, len(frame))
            _assert_series(actual, expected)
            outcomes.append(actual)
    if strict and scenario.endswith("overflow"):
        assert outcomes[0] == outcomes[1]
    else:
        _assert_series(outcomes[0], outcomes[1])


def _kdj_expected(frame, period, fast, slow):
    columns = {name: frame[name].to_list() for name in ("high", "low", "close")}
    result = {key: [math.nan] * len(frame) for key in ("highest", "lowest", "rsv", "k", "d", "j")}
    for i in range(len(frame)):
        if i >= period - 1:
            high = max(columns["high"][i - period + 1 : i + 1])
            low = min(columns["low"][i - period + 1 : i + 1])
            close = columns["close"][i]
            result["highest"][i] = high
            result["lowest"][i] = low
            if all(math.isfinite(value) for value in (high, low, close)) and high > low:
                result["rsv"][i] = 100.0 * (close - low) / (high - low)
        for target, source, size in (("k", "rsv", fast), ("d", "k", slow)):
            if i >= size - 1:
                window = result[source][i - size + 1 : i + 1]
                if all(math.isfinite(value) for value in window):
                    result[target][i] = sum(window) / size
        if math.isfinite(result["k"][i]) and math.isfinite(result["d"][i]):
            result["j"][i] = 3 * result["k"][i] - 2 * result["d"][i]
    return result


def _kdj_lines(strategy, instance, mode, count):
    if mode == "native":
        data = strategy.datas[0]
        rsv = instance._rsv[data]
        return {
            "highest": _line(rsv._highest.lines.highest, count),
            "lowest": _line(rsv._lowest.lines.lowest, count),
            "rsv": _line(rsv.lines.rsv, count),
            "k": _line(instance._k[data].lines.sma, count),
            "d": _line(instance._d[data].lines.sma, count),
            "j": _line(instance.outputs[data].factor, count),
        }
    nodes = tuple(instance._nodes.values())
    highest = [node for node in nodes if isinstance(node, bt.indicators.Highest)]
    lowest = [node for node in nodes if isinstance(node, bt.indicators.Lowest)]
    sma = [node for node in nodes if isinstance(node, bt.indicators.SMA)]
    rsv = [node for node in nodes if getattr(node.p, "function", None) is _MULTI._kdj_rsv]
    j = [node for node in nodes if getattr(node.p, "function", None) is _MULTI._kdj_j]
    assert tuple(map(len, (highest, lowest, sma, rsv, j))) == (1, 1, 2, 1, 1)
    return {
        "highest": _line(highest[0].lines.highest, count),
        "lowest": _line(lowest[0].lines.lowest, count),
        "rsv": _line(rsv[0].lines.value, count),
        "k": _line(sma[0].lines.sma, count),
        "d": _line(sma[1].lines.sma, count),
        "j": _line(j[0].lines.value, count),
    }


@pytest.mark.parametrize("params", ((9, 3, 3), (5, 2, 4)), ids=("default", "period-variant"))
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_kdj_intermediate_lines_and_nan_positions_against_oracle(params, runonce):
    frame = _bars()
    frame.loc[frame.index[20], "high"] = math.nan
    frame.loc[frame.index[24], "low"] = math.nan
    frame.loc[frame.index[28], "close"] = math.nan
    period, fast, slow = params
    expected = _kdj_expected(frame, period, fast, slow)
    assert math.isnan(expected["rsv"][period - 1])  # flat window
    assert math.isnan(expected["rsv"][28])  # missing current close
    assert math.isfinite(expected["j"][-1])
    native = built = None
    for mode in ("native", "build"):
        strategy, instance = _run(
            frame,
            "kdj",
            _MULTI.KDJFactor,
            {"period": period, "period_dfast": fast, "period_dslow": slow},
            mode,
            runonce,
        )
        actual = _kdj_lines(strategy, instance, mode, len(frame))
        for name, values in actual.items():
            _assert_series(values, expected[name])
        if mode == "native":
            native = actual
        else:
            built = actual
            _assert_series(
                _line(instance.outputs[strategy.datas[0]].factor, len(frame)), actual["j"]
            )
    for name in expected:
        _assert_series(native[name], built[name])


@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_kdj_flat_extreme_guard_matches_independent_oracle(mode, runonce):
    """A zero range must be rejected before extreme RSV arithmetic occurs."""
    frame = _bars(16)
    frame.loc[frame.index[0], ["high", "low", "close"]] = (1e307, 1e307, 1.7e308)
    for index in range(1, len(frame)):
        frame.loc[frame.index[index], ["high", "low", "close"]] = (
            101.0 + index,
            99.0 + index,
            100.0 + index,
        )
    expected = _kdj_expected(frame, period=1, fast=1, slow=1)
    assert expected["highest"][0] == expected["lowest"][0] == 1e307
    assert all(math.isnan(expected[name][0]) for name in ("rsv", "k", "d", "j"))
    assert all(value == 50.0 for value in expected["j"][1:])

    strategy, instance = _run(
        frame,
        "kdj",
        _MULTI.KDJFactor,
        {"period": 1, "period_dfast": 1, "period_dslow": 1},
        mode,
        runonce,
    )
    actual = _kdj_lines(strategy, instance, mode, len(frame))
    for name, values in actual.items():
        _assert_series(values, expected[name])
    _assert_series(_line(instance.outputs[strategy.datas[0]].factor, len(frame)), expected["j"])


@pytest.mark.parametrize("factor_name", ("close_ma", "roc"))
@pytest.mark.parametrize("scenario", ("flat", "flat-zero"))
@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_flat_ma_and_roc_outputs_and_child_lines_against_oracle(
    factor_name, scenario, mode, runonce
):
    frame = _bars(18)
    close = [
        10.0,
        10.0,
        10.0,
        10.0,
        12.0,
        12.0,
        12.0,
        15.0,
        14.0,
        16.0,
        17.0,
        18.0,
        19.0,
        20.0,
        21.0,
        22.0,
        23.0,
        24.0,
    ]
    if scenario == "flat-zero":
        close[:4] = [0.0] * 4
        close[4:7] = [2.0] * 3
    frame.loc[:, "close"] = close
    child_expected = [math.nan] * len(close)
    factor_expected = [math.nan] * len(close)
    if factor_name == "close_ma":
        factor_class, child_type, period = _MULTI.CloseMAFactor, bt.indicators.SMA, 3
        for i in range(period - 1, len(close)):
            average = sum(close[i - period + 1 : i + 1]) / period
            child_expected[i] = average
            if average != 0.0:
                factor_expected[i] = close[i] / average
    else:
        factor_class, child_type, period = _MULTI.ROCFactor, bt.indicators.ROC, 2
        for i in range(period, len(close)):
            previous = close[i - period]
            # ROC's raw child defines zero for a zero denominator. The factor
            # independently treats that point as unavailable (NaN).
            child_expected[i] = (close[i] - previous) / previous if previous else 0.0
            if previous != 0.0:
                factor_expected[i] = (close[i] - previous) / previous

    strategy, instance = _run(frame, factor_name, factor_class, {"period": period}, mode, runonce)
    data = strategy.datas[0]
    if mode == "native":
        child = instance._averages[data] if factor_name == "close_ma" else instance._roc[data]
    else:
        children = [node for node in instance._nodes.values() if isinstance(node, child_type)]
        assert len(children) == 1
        child = children[0]
    child_line = child.lines.sma if factor_name == "close_ma" else child.lines.roc
    actual_child = _line(child_line, len(frame))
    actual_factor = _line(instance.outputs[data].factor, len(frame))
    _assert_series(actual_child, child_expected)
    _assert_series(actual_factor, factor_expected)

    assert all(math.isnan(value) for value in actual_factor[:2])
    if scenario == "flat":
        assert actual_factor[2] == pytest.approx(1.0 if factor_name == "close_ma" else 0.0)
        assert actual_factor[4] == pytest.approx(1.125 if factor_name == "close_ma" else 0.2)
    else:
        assert actual_child[2] == 0.0 and math.isnan(actual_factor[2])
        assert actual_child[3] == 0.0 and math.isnan(actual_factor[3])
        assert math.isfinite(actual_factor[6])
        if factor_name == "roc":
            assert actual_child[4] == 0.0 and math.isnan(actual_factor[4])
