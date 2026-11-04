"""Synthetic recovery of selected retired example formula contracts.

The values below are calculated from input bars, without production formula
helpers.  No historical panel parity or example CLI acceptance is implied.
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

_ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, _ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_SINGLE = _load(
    "iter61_recovery_single", "examples/backtest/025_factor_single/close_ma_factor_strategy.py"
)
_MULTI = _load(
    "iter61_recovery_multi", "examples/backtest/026_factor_multi/multi_factor_strategy.py"
)
_FACTORS = {
    "single_ma": _SINGLE.CloseMAFactor,
    "multi_ma": _MULTI.CloseMAFactor,
    "roc": _MULTI.ROCFactor,
    "kdj": _MULTI.KDJFactor,
}
_DEFAULT_LOOKBACK = {"single_ma": 19, "multi_ma": 19, "roc": 20, "kdj": 12}
_DEFAULT_FIRST_FINITE = {"single_ma": 19, "multi_ma": 19, "roc": 20, "kdj": 12}


def _bars(count=42, flat=False):
    index = pd.date_range("2025-01-01 16:00", periods=count, freq="D", tz="UTC", name="close_time")
    rows = []
    for i in range(count):
        if flat and i < 15:
            rows.append((100.0, 100.0, 100.0, 100.0, 1.0))
        else:
            close = 100.0 + 0.7 * i + 0.13 * ((i % 5) - 2)
            rows.append((close - 0.2, close + 0.8, close - 0.6, close, 1000.0 + i))
    return pd.DataFrame(rows, columns=("open", "high", "low", "close", "volume"), index=index)


def _run(frames, name, mode, runonce, *, groups=None, order=None, params=None):
    order = tuple(order or frames)
    index = max(frames.values(), key=len).index
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index),
        start=index[0],
        end=index[-1],
        targets=order,
        source_timezone="UTC",
        snapshot_id="iter61-synthetic",
        price_basis="synthetic",
        calendar_id="synthetic",
        frequency="1day",
        groups=groups or dict.fromkeys(order, "all"),
    )
    factor_class = _FACTORS[name]
    factor = FactorSpec(
        name=name,
        indicator=factor_class,
        panel_line="factor",
        mode=mode,
        params=params or {},
        field_bindings={field: "feed:target:" + field for field in factor_class.formula_fields},
    )
    cerebro = bt.Cerebro(stdstats=False)
    for asset in order:
        cerebro.adddata(align_to_grid(frames[asset], research, asset).feed, name=asset)
    cerebro.addstrategy(FactorStrategy, research=research, factors={name: factor})
    strategy = cerebro.run(runonce=runonce, preload=True)[0]
    assert strategy._factor_specs_by_name[name].mode == mode
    for instance in strategy._factor_instances_by_name[name]:
        assert instance.factor_mode == mode
        assert instance.lifecycle_diagnostics["coverage_matches"]
    return strategy


def _oracle(frame, name):
    close = frame.close.to_list()
    result = [math.nan] * len(frame)
    if name in ("single_ma", "multi_ma"):
        for i in range(19, len(frame)):
            avg = sum(close[i - 19 : i + 1]) / 20
            if math.isfinite(avg) and avg != 0:
                result[i] = close[i] / avg
    elif name == "roc":
        for i in range(20, len(frame)):
            if close[i - 20] != 0:
                result[i] = (close[i] - close[i - 20]) / close[i - 20]
    else:
        return _kdj_oracle(frame)["j"]
    return result


def _kdj_oracle(frame):
    high, low, close = frame.high.to_list(), frame.low.to_list(), frame.close.to_list()
    n = len(frame)
    result = {key: [math.nan] * n for key in ("rsv", "k", "d", "j")}
    for i in range(n):
        if i >= 8:
            maximum, minimum = max(high[i - 8 : i + 1]), min(low[i - 8 : i + 1])
            if maximum > minimum:
                result["rsv"][i] = 100.0 * (close[i] - minimum) / (maximum - minimum)
        for current, source in (("k", "rsv"), ("d", "k")):
            if i >= 2:
                window = result[source][i - 2 : i + 1]
                if all(math.isfinite(value) for value in window):
                    result[current][i] = sum(window) / 3
        if math.isfinite(result["k"][i]) and math.isfinite(result["d"][i]):
            result["j"][i] = 3 * result["k"][i] - 2 * result["d"][i]
    return result


def _assert_values(actual, expected):
    assert len(actual) == len(expected)
    assert any(math.isfinite(value) for value in expected)
    for index, (got, wanted) in enumerate(zip(actual, expected)):
        assert math.isnan(got) == math.isnan(wanted), index
        assert not math.isinf(got), index
        if math.isfinite(wanted):
            assert got == pytest.approx(wanted, rel=1e-12, abs=1e-12), index


def _values(strategy, name, asset):
    return strategy.get_panel().factors.xs(asset, level="asset")[name].tolist()


def _values_differ(left, right):
    return any(
        math.isfinite(a)
        and math.isfinite(b)
        and not math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10)
        for a, b in zip(left, right)
    )


@pytest.mark.parametrize("name", tuple(_FACTORS))
@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_default_formula_values_against_independent_oracle(name, mode, runonce):
    frame = _bars(flat=name == "kdj")
    strategy = _run({"A": frame}, name, mode, runonce)
    _assert_values(_values(strategy, name, "A"), _oracle(frame, name))


@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_default_kdj_intermediate_lines_against_independent_oracle(mode, runonce):
    frame = _bars(flat=True)
    strategy = _run({"A": frame}, "kdj", mode, runonce)
    factor = strategy.factor_instances["kdj"]
    data = strategy.datas[0]
    if mode == "native":
        lines = {
            "rsv": factor._rsv[data].rsv,
            "k": factor._k[data].lines.sma,
            "d": factor._d[data].lines.sma,
        }
    else:
        nodes = tuple(factor._nodes.values())
        rsv = [node for node in nodes if getattr(node.p, "function", None) is _MULTI._kdj_rsv]
        averages = [node for node in nodes if isinstance(node, bt.indicators.SMA)]
        assert len(rsv) == 1 and len(averages) == 2
        lines = {"rsv": rsv[0].lines.value, "k": averages[0].lines.sma, "d": averages[1].lines.sma}
    oracle = _kdj_oracle(frame)
    for name, line in lines.items():
        _assert_values([float(value) for value in line.get(size=len(frame))], oracle[name])
    _assert_values(_values(strategy, "kdj", "A"), oracle["j"])


@pytest.mark.parametrize("name", tuple(_FACTORS))
@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_group_value_changes_and_asset_reordering_leave_other_assets_unchanged(name, mode, runonce):
    base = _bars()
    frames = {asset: base.copy() for asset in ("A", "B", "C")}
    for index in range(len(base)):
        for asset, delta in (
            ("B", 2.3 * ((index % 7) - 3)),
            ("C", 1.7 * ((index % 11) - 5)),
        ):
            frames[asset].iloc[index, :4] += delta
    oracle = {asset: _oracle(frame, name) for asset, frame in frames.items()}
    assert all(
        _values_differ(oracle[first], oracle[second])
        for first, second in (("A", "B"), ("A", "C"), ("B", "C"))
    )
    groups = {"A": "g1", "B": "g2", "C": "g2"}
    original = _run(frames, name, mode, runonce, groups=groups)
    changed = {asset: frame.copy() for asset, frame in frames.items()}
    for index in range(22, 29):
        changed["B"].iloc[index, :4] += 7.0 + 1.7 * (index - 22)
    changed_oracle = _oracle(changed["B"], name)
    assert _values_differ(oracle["B"], changed_oracle)
    altered = _run(changed, name, mode, runonce, groups=groups, order=("C", "B", "A"))
    assert tuple(original.get_panel().target_order) == ("A", "B", "C")
    assert tuple(altered.get_panel().target_order) == ("C", "B", "A")
    for asset in ("A", "B", "C"):
        expected_after = changed_oracle if asset == "B" else oracle[asset]
        _assert_values(_values(original, name, asset), oracle[asset])
        _assert_values(_values(altered, name, asset), expected_after)
    assert _values_differ(_values(original, name, "B"), _values(altered, name, "B"))
    for asset in ("A", "C"):
        _assert_values(_values(altered, name, asset), _values(original, name, asset))


@pytest.mark.parametrize("name", tuple(_FACTORS))
@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_missing_bar_and_lookback_do_not_contaminate_another_group(name, mode, runonce):
    frame = _bars(55)
    missing_index = 23
    frames = {"A": frame.drop(frame.index[missing_index]), "B": frame.copy()}
    strategy = _run(frames, name, mode, runonce, groups={"A": "g1", "B": "g2"})
    expected = _oracle(frame, name)
    lookback = _DEFAULT_LOOKBACK[name]
    for index in range(missing_index, min(len(expected), missing_index + lookback + 1)):
        expected[index] = math.nan
    actual = _values(strategy, name, "A")
    _assert_values(actual, expected)
    assert math.isfinite(actual[missing_index - 1])
    assert all(math.isnan(value) for value in actual[missing_index : missing_index + lookback + 1])
    assert math.isfinite(actual[missing_index + lookback + 1])
    _assert_values(_values(strategy, name, "B"), _oracle(frame, name))


@pytest.mark.parametrize("name", tuple(_FACTORS))
@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("gap", ("first_bar", "mid_warmup", "before_first_finite"))
def test_warmup_gap_has_independent_first_finite_and_recovery(name, mode, runonce, gap):
    frame = _bars(55)
    first = _DEFAULT_FIRST_FINITE[name]
    missing_index = {"first_bar": 0, "mid_warmup": first // 2, "before_first_finite": first - 1}[
        gap
    ]
    recovery = missing_index + _DEFAULT_LOOKBACK[name] + 1
    expected = _oracle(frame, name)
    assert next(i for i, value in enumerate(expected) if math.isfinite(value)) == first
    for index in range(missing_index, recovery):
        expected[index] = math.nan
    assert next(i for i, value in enumerate(expected) if math.isfinite(value)) == recovery

    frames = {"A": frame.drop(frame.index[missing_index]), "B": frame.copy()}
    strategy = _run(frames, name, mode, runonce, groups={"A": "g1", "B": "g2"})
    actual = _values(strategy, name, "A")
    _assert_values(actual, expected)
    assert all(math.isnan(value) for value in actual[:recovery])
    assert math.isfinite(actual[recovery])
    _assert_values(_values(strategy, name, "B"), _oracle(frame, name))


@pytest.mark.parametrize("name", tuple(_FACTORS))
@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_future_tail_perturbation_cannot_change_earlier_values(name, mode, runonce):
    frame = _bars()
    changed = frame.copy()
    changed.iloc[30:, changed.columns.get_loc("close")] += 100
    changed.iloc[30:, changed.columns.get_loc("high")] += 250
    changed.iloc[30:, changed.columns.get_loc("low")] -= 125
    before = _values(_run({"A": frame}, name, mode, runonce), name, "A")
    after = _values(_run({"A": changed}, name, mode, runonce), name, "A")
    _assert_values(before[:30], _oracle(frame, name)[:30])
    _assert_values(after[:30], before[:30])


@pytest.mark.parametrize("scenario", ("roc_difference", "roc_division", "ma_ratio", "kdj_rsv"))
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_strict_finite_input_overflow_propagates_factor_context(scenario, runonce):
    frame = _bars(25)
    if scenario == "roc_difference":
        name, params = "roc", {"period": 1}
        frame.loc[frame.index[:2], "close"] = [-1.7e308, 1.7e308]
    elif scenario == "roc_division":
        name, params = "roc", {"period": 1}
        frame.loc[frame.index[:2], "close"] = [1e-309, 1.0]
    elif scenario == "ma_ratio":
        name, params = "single_ma", {"period": 3}
        frame.loc[frame.index[:3], "close"] = [-1.7e308, 2e-309, 1.7e308]
    else:
        name, params = "kdj", {"period": 1, "period_dfast": 1, "period_dslow": 1}
        frame.loc[frame.index[0], ["high", "low", "close"]] = [1e307, 0.0, 1e307]
    errors = []
    control = frame.copy()
    if scenario == "roc_difference":
        control.loc[control.index[:2], "close"] = [1.0, 2.0]
        control_index, control_value = 1, 1.0
    elif scenario == "roc_division":
        control.loc[control.index[:2], "close"] = [1.0, 1.0]
        control_index, control_value = 1, 0.0
    elif scenario == "ma_ratio":
        control.loc[control.index[:3], "close"] = [1.0, 2.0, 3.0]
        control_index, control_value = 2, 1.5
    else:
        control.loc[control.index[0], ["high", "low", "close"]] = [2.0, 0.0, 1.0]
        control_index, control_value = 0, 50.0
    for mode in ("native", "build"):
        normal = _run({"A": control}, name, mode, runonce, params=params)
        assert _values(normal, name, "A")[control_index] == pytest.approx(control_value)
        with pytest.raises(FactorComputationError) as caught:
            _run({"A": frame}, name, mode, runonce, params=params)
        errors.append(caught.value)
        assert caught.value.factor == name
        assert caught.value.asset == "A"
        assert caught.value.phase == ("once_via_next" if runonce else "next")
        assert caught.value.code == "FACTOR_COMPUTATION_FAILED"
        assert type(caught.value.__cause__) is ArithmeticError
        assert caught.value.report["exception_type"] == "ArithmeticError"
    assert errors[0].phase == errors[1].phase


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_sma_sum_overflow_is_equivalent_in_strict_native_and_build(runonce):
    frame = _bars(25)
    frame.loc[frame.index[:2], "close"] = [1.7e308, 1.7e308]
    control = frame.copy()
    control.loc[control.index[:2], "close"] = [8.0, 12.0]
    results = []
    for mode in ("native", "build"):
        normal = _run({"A": control}, "single_ma", mode, runonce, params={"period": 2})
        assert _values(normal, "single_ma", "A")[1] == pytest.approx(1.2)
        try:
            strategy = _run({"A": frame}, "single_ma", mode, runonce, params={"period": 2})
        except FactorComputationError as exc:
            results.append(exc)
        else:
            results.append(_values(strategy, "single_ma", "A"))
    if isinstance(results[0], FactorComputationError):
        assert isinstance(results[1], FactorComputationError)
        assert (results[0].factor, results[0].phase) == (results[1].factor, results[1].phase)
        for error in results:
            assert error.factor == "single_ma"
            assert error.asset == "A"
            assert error.code == "FACTOR_COMPUTATION_FAILED"
            assert isinstance(error.__cause__, ArithmeticError)
    else:
        assert isinstance(results[1], list)
        _assert_values(results[0], results[1])
        assert math.isnan(results[0][1]) and math.isfinite(results[0][2])


@pytest.mark.parametrize("name", ("single_ma", "roc"))
@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_zero_denominator_is_missing_then_recovers(name, mode, runonce):
    frame = _bars(25)
    frame.loc[frame.index[:2], "close"] = [0.0, 0.0] if name == "single_ma" else [0.0, 10.0]
    params = {"period": 2 if name == "single_ma" else 1}
    values = _values(_run({"A": frame}, name, mode, runonce, params=params), name, "A")
    assert math.isnan(values[1])
    assert math.isfinite(values[2])
