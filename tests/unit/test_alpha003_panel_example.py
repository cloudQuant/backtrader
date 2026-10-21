"""Independent, deterministic acceptance checks for the local Alpha003 example."""

from fractions import Fraction
import importlib.util
import json
import math
from pathlib import Path
import sys

import pandas as pd
import pytest


_FIELDS = ("open", "high", "low", "close", "volume")
_FACTOR = "alpha003"
_EXAMPLE = Path(__file__).resolve().parents[2] / "examples/backtest/027_alpha003_panel_acceptance"


@pytest.fixture
def example(monkeypatch):
    """Load the standalone example without leaking its generic module names."""
    local_modules = ("alpha003_strategy",)
    with monkeypatch.context() as context:
        context.setattr(sys, "path", list(sys.path))
        context.syspath_prepend(str(_EXAMPLE))
        for name in local_modules:
            context.delitem(sys.modules, name, raising=False)
        spec = importlib.util.spec_from_file_location("_alpha003_example_run", _EXAMPLE / "run.py")
        module = importlib.util.module_from_spec(spec)
        context.setitem(sys.modules, spec.name, module)
        try:
            spec.loader.exec_module(module)
            yield module
        finally:
            for name in local_modules:
                sys.modules.pop(name, None)


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _copy_inputs(inputs):
    return {asset: frame.copy(deep=True) for asset, frame in inputs.items()}


def _field_values(inputs, timestamp, field):
    """Return present finite values for a cross-sectional field at one grid time."""
    key = pd.Timestamp(timestamp)
    values = {}
    for asset, frame in inputs.items():
        if key not in frame.index:
            continue
        value = frame.at[key, field]
        if pd.isna(value):
            continue
        value = float(value)
        if math.isinf(value):
            raise ValueError("infinite source value for %s/%s" % (asset, field))
        if math.isfinite(value):
            values[asset] = value
    return values


def _fractional_ranks(values):
    """Average ranks normalized to [0, 1], using exact pairwise comparisons."""
    count = len(values)
    ranks = {}
    for asset, value in values.items():
        less = sum(other < value for other in values.values())
        equal = sum(other == value for other in values.values())
        ranks[asset] = Fraction(2 * less + equal + 1, 2 * count)
    return ranks


def reference_alpha003(inputs, grid, period=10):
    """Build full-grid -corr(rank(open), rank(volume), 10) without the panel engine."""
    assets = tuple(inputs)
    grid = tuple(grid)
    _require(bool(assets) and bool(grid), "reference requires assets and grid rows")
    _require(len(set(assets)) == len(assets), "reference asset names must be unique")
    for asset, frame in inputs.items():
        _require(isinstance(frame, pd.DataFrame), "input for %s must be a DataFrame" % asset)
        _require(isinstance(frame.index, pd.DatetimeIndex), "input index must be DatetimeIndex")
        _require(frame.index.is_unique, "input timestamps must be unique")
        _require(
            {"open", "volume"}.issubset(frame.columns),
            "reference needs open and volume columns",
        )

    ranks = {"open": [], "volume": []}
    for timestamp in grid:
        for field in ranks:
            ranks[field].append(_fractional_ranks(_field_values(inputs, timestamp, field)))

    rows = []
    for position, timestamp in enumerate(grid):
        for asset in assets:
            result = math.nan
            if position >= period - 1:
                window_open = [
                    row.get(asset) for row in ranks["open"][position - period + 1 : position + 1]
                ]
                window_volume = [
                    row.get(asset) for row in ranks["volume"][position - period + 1 : position + 1]
                ]
                if all(value is not None for value in window_open + window_volume):
                    n = period
                    sum_x, sum_y = sum(window_open), sum(window_volume)
                    cov = sum(x * y for x, y in zip(window_open, window_volume)) - sum_x * sum_y / n
                    var_x = sum(x * x for x in window_open) - sum_x * sum_x / n
                    var_y = sum(y * y for y in window_volume) - sum_y * sum_y / n
                    if var_x and var_y:
                        result = -float(cov) / math.sqrt(float(var_x * var_y))
            rows.append(((timestamp, asset), result))
    index = pd.MultiIndex.from_tuples([key for key, _ in rows], names=("time", "asset"))
    return pd.DataFrame({_FACTOR: [value for _, value in rows]}, index=index)


def _compare_dataset(strategy, expected, label):
    actual = strategy.get_dataset().raw_factors
    _require(isinstance(actual, pd.DataFrame), "%s: get_dataset() must return a DataFrame" % label)
    _require(
        isinstance(actual.index, pd.MultiIndex) and actual.index.nlevels == 2,
        "%s: dataset index must be MultiIndex(time, asset)" % label,
    )
    _require(
        tuple(actual.index.names) == ("time", "asset"),
        "%s: dataset index names must be time, asset" % label,
    )
    _require(not actual.index.has_duplicates, "%s: dataset contains duplicate rows" % label)
    _require(_FACTOR in actual.columns, "%s: dataset is missing alpha003" % label)
    _require(
        set(actual.index) == set(expected.index), "%s: dataset does not cover the full grid" % label
    )
    actual = actual.reindex(expected.index)
    for key, wanted in expected[_FACTOR].items():
        got = actual.at[key, _FACTOR]
        if pd.isna(wanted):
            _require(pd.isna(got), "%s: expected missing value at %r, got %r" % (label, key, got))
        else:
            _require(not pd.isna(got), "%s: expected finite value at %r" % (label, key))
            _require(
                math.isclose(float(got), float(wanted), rel_tol=1e-12, abs_tol=1e-12),
                "%s: value mismatch at %r: got %r, expected %r" % (label, key, got, wanted),
            )
    return actual


def _run_case(run_experiment, inputs, grid, label, **options):
    expected = reference_alpha003(inputs, grid)
    strategy = run_experiment(inputs, grid, **options)
    actual = _compare_dataset(strategy, expected, label)
    return strategy, expected, actual


def _run_modes(run_experiment, inputs, grid, label):
    return [
        _run_case(
            run_experiment,
            _copy_inputs(inputs),
            grid,
            "%s runonce=%s" % (label, runonce),
            runonce=runonce,
        )
        for runonce in (False, True)
    ]


def _assert_native(strategy, grid, assets):
    import backtrader as bt
    from backtrader.research import FactorIndicator

    assert set(strategy.factor_instances) == set(strategy.get_dataset().raw_factors.columns)
    for factor in strategy.factor_instances.values():
        assert isinstance(factor, FactorIndicator)
        assert isinstance(factor, bt.Indicator)
        assert any(item is factor for item in strategy.getindicators())
        assert len(factor.datas) == len(assets)
        assert {data._name for data in factor.datas} == set(assets)
        assert factor.evaluation_count == len(grid)
        for data in factor.datas:
            output = factor.outputs[data].factor
            assert isinstance(output, bt.LineBuffer)
            assert len(output) == len(grid)
            assert output.buflen() == len(grid)


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize(
    "case",
    [
        "base",
        "reorder",
        "cross_asset",
        "ties",
        "one_gap",
        "all_gap",
        "late_early",
        "trailing",
        "constant",
    ],
)
def test_native_alpha003_full_grid_oracle(example, monkeypatch, runonce, case):
    import backtrader as bt

    calls = {"submit": 0, "cancel": 0}

    def forbidden_submit(*args, **kwargs):
        calls["submit"] += 1
        raise AssertionError("factor research submitted an order")

    def forbidden_cancel(*args, **kwargs):
        calls["cancel"] += 1
        raise AssertionError("factor research cancelled an order")

    monkeypatch.setattr(bt.brokers.BackBroker, "submit", forbidden_submit)
    monkeypatch.setattr(bt.brokers.BackBroker, "cancel", forbidden_cancel)
    inputs = example.make_inputs()
    grid = inputs["A"].index
    options = {}
    if case == "reorder":
        options["asset_order"] = ("C", "B", "A")
    elif case == "cross_asset":
        inputs["B"].loc[grid[-1], "open"] = 9.5
    elif case == "ties":
        inputs["B"].loc[grid[-1], "open"] = inputs["A"].loc[grid[-1], "open"]
    elif case == "one_gap":
        inputs["C"] = inputs["C"].drop(grid[4])
    elif case == "all_gap":
        inputs = {asset: frame.drop(grid[4]) for asset, frame in inputs.items()}
    elif case == "late_early":
        inputs["A"] = inputs["A"].drop([grid[0], grid[-1]])
    elif case == "trailing":
        inputs = {asset: frame.drop(grid[-1]) for asset, frame in inputs.items()}
    elif case == "constant":
        for frame in inputs.values():
            frame["open"], frame["volume"] = 10.0, 100.0
    strategy, expected, actual = _run_case(
        example.run_experiment, inputs, grid, case, runonce=runonce, **options
    )
    _assert_native(strategy, grid, inputs)
    assert calls == {"submit": 0, "cancel": 0}
    if case == "base":
        assert actual.loc[grid[-1], "alpha003"].tolist() == pytest.approx([17 / 23, 1, 17 / 23])
        assert actual.iloc[:27].isna().all().all()
    if case == "cross_asset":
        assert actual.at[(grid[-1], "A"), "alpha003"] == pytest.approx(math.sqrt(20 / 23))


@pytest.mark.parametrize("runonce", [False, True])
def test_native_future_prefix_and_instance_isolation(example, runonce):
    inputs = example.make_inputs()
    grid = inputs["A"].index
    base = example.run_experiment(inputs, grid, runonce=runonce)
    prefix = base.get_dataset().raw_factors
    future = grid[-1] + pd.Timedelta(days=1)
    for offset, frame in enumerate(inputs.values()):
        frame.loc[future, list(_FIELDS)] = (1000 + offset, 2000, 0.5, 1000, 9000 - offset * 1000)
    extended = grid.append(pd.DatetimeIndex([future]))
    strategy, _, _ = _run_case(
        example.run_experiment,
        inputs,
        extended,
        "future",
        runonce=runonce,
        factor_classes={
            "alpha003": example.Alpha003Indicator,
            "duplicate": example.Alpha003Indicator,
        },
    )
    pd.testing.assert_frame_equal(
        strategy.get_dataset().raw_factors.loc[prefix.index, ["alpha003"]], prefix
    )
    left, right = strategy.factor_instances.values()
    assert left is not right
    for data in left.datas:
        assert left.outputs[data].factor is not right.outputs[data].factor
    pd.testing.assert_series_equal(
        strategy.get_dataset().raw_factors["alpha003"],
        strategy.get_dataset().raw_factors["duplicate"],
        check_names=False,
    )
    _assert_native(strategy, extended, inputs)
    # A fresh run must not inherit an earlier instance's rolling history.
    fresh_inputs = example.make_inputs()
    fresh = example.run_experiment(fresh_inputs, grid, runonce=runonce)
    pd.testing.assert_frame_equal(fresh.get_dataset().raw_factors, prefix)


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("asset_names", [("A",), ("A", "B"), ("A", "B", "C", "资产.D")])
def test_native_variable_asset_output_lines(example, runonce, asset_names):
    original = example.make_inputs()
    inputs = {name: original[("A", "B", "C")[i % 3]].copy() for i, name in enumerate(asset_names)}
    grid = original["A"].index
    strategy, _, _ = _run_case(example.run_experiment, inputs, grid, "asset count", runonce=runonce)
    _assert_native(strategy, grid, asset_names)


@pytest.mark.parametrize("runonce", [False, True])
def test_native_real_sma_roc_and_cross_section_to_time_series(example, runonce):
    import backtrader as bt
    from backtrader.research import FactorIndicator

    class NativeChildren(FactorIndicator):
        lines = ("factor",)
        panel_mode = "next"
        params = (("period", 3),)
        formula_fields = ("close",)

        @classmethod
        def lookback_h(cls, period=3):
            return period - 1

        def __init__(self):
            super().__init__()
            self.means = {data: bt.ind.SMA(data.close, period=self.p.period) for data in self.datas}
            self.rocs = {
                data: bt.ind.ROC(data.close, period=self.p.period - 1) for data in self.datas
            }

        def next(self):
            for data in self.datas:
                self.outputs[data].factor[0] = self.means[data][0] + self.rocs[data][0]

    class DailyRank(FactorIndicator):
        lines = ("factor",)
        panel_mode = "next"
        formula_fields = ("open",)

        @classmethod
        def lookback_h(cls):
            return 0

        def next(self):
            values = {data: data.open[0] for data in self.datas}
            finite = [v for v in values.values() if math.isfinite(v)]
            for data, value in values.items():
                self.outputs[data].factor[0] = (
                    (sum(v < value for v in finite) + (sum(v == value for v in finite) + 1) / 2)
                    / len(finite)
                    if math.isfinite(value)
                    else math.nan
                )

    class SmoothedRank(FactorIndicator):
        lines = ("factor",)
        panel_mode = "next"
        formula_fields = ("open",)

        @classmethod
        def lookback_h(cls):
            return 2

        def __init__(self):
            super().__init__()
            self.rank = DailyRank.bind(*self.datas)
            self.means = {
                data: bt.ind.SMA(self.rank.outputs[data].factor, period=3) for data in self.datas
            }

        def next(self):
            for data in self.datas:
                self.outputs[data].factor[0] = self.means[data][0]

    inputs = example.make_inputs()
    grid = inputs["A"].index
    for i, frame in enumerate(inputs.values()):
        frame["close"] = [10.0 + i + j * j for j in range(len(grid))]
    strategy = example.run_experiment(
        inputs,
        grid,
        runonce=runonce,
        factor_classes={"native_children": NativeChildren, "smoothed_rank": SmoothedRank},
    )
    actual = strategy.get_dataset().raw_factors
    ranks = [_fractional_ranks(_field_values(inputs, t, "open")) for t in grid]
    for position, t in enumerate(grid):
        for asset, frame in inputs.items():
            if position < 2:
                assert actual.loc[(t, asset)].isna().all()
            else:
                close = frame["close"].iloc[position - 2 : position + 1].tolist()
                expected = sum(close) / 3 + close[-1] / close[0] - 1
                assert actual.at[(t, asset), "native_children"] == pytest.approx(expected)
                expected_rank = float(sum(r[asset] for r in ranks[position - 2 : position + 1]) / 3)
                assert actual.at[(t, asset), "smoothed_rank"] == pytest.approx(expected_rank)
    for factor in strategy.factor_instances.values():
        assert factor.getindicators()
        assert all(child._owner is factor for child in factor.getindicators())


@pytest.mark.parametrize(
    "bad", ["missing_column", "outside_grid", "infinite_open", "infinite_volume"]
)
def test_native_example_rejects_invalid_inputs(example, bad):
    inputs = example.make_inputs()
    grid = inputs["A"].index
    if bad == "missing_column":
        inputs["A"] = inputs["A"].drop(columns="volume")
    elif bad == "outside_grid":
        inputs["A"].loc[grid[-1] + pd.Timedelta(days=1), list(_FIELDS)] = (11, 20, 0.5, 10, 100)
    else:
        inputs["A"].loc[grid[0], bad.removeprefix("infinite_")] = math.inf
    with pytest.raises(ValueError):
        example.run_experiment(inputs, grid)


def test_example_run_only_computes_and_exports(example, monkeypatch, tmp_path, capsys):
    run_experiment = example.run_experiment
    calls = []

    def counted_run(*args, **kwargs):
        calls.append(1)
        return run_experiment(*args, **kwargs)

    monkeypatch.setattr(example, "run_experiment", counted_run)
    assert example.main(["--output-dir", str(tmp_path)]) == 0
    assert len(calls) == 1
    assert {path.name for path in tmp_path.iterdir()} == {
        "input_bars.csv",
        "node_values.csv",
        "factor_values.csv",
        "run_summary.json",
    }
    report = json.loads((tmp_path / "run_summary.json").read_text(encoding="utf-8"))
    assert report["status"] == "COMPLETED"
    assert "checks" not in report
    values = pd.read_csv(tmp_path / "factor_values.csv")
    assert len(values) == 30
    assert values["alpha003"].iloc[:27].isna().all()
    assert values["alpha003"].iloc[-3:].tolist() == pytest.approx([17 / 23, 1, 17 / 23])
    stdout = capsys.readouterr().out
    assert "COMPLETED:" in stdout
    assert "PASS:" not in stdout


@pytest.mark.parametrize(
    "invalid", ["execution", "line", "inputs", "ordinary", "expression", "missing_output"]
)
def test_native_research_has_one_explicit_entry(example, invalid):
    import backtrader as bt
    from backtrader.research import FactorIndicator, FactorStrategy

    if invalid == "expression":
        with pytest.raises(TypeError, match="panel_mode"):

            class ExpressionWithNext(FactorIndicator):
                lines = ("factor",)
                panel_mode = "expression"

                def next(self):
                    raise AssertionError("unsupported expression mode reached calculation")

                @classmethod
                def build(cls, ctx):
                    return ctx.open

        return

    inputs = example.make_inputs()
    cerebro = bt.Cerebro(stdstats=False)
    for asset, frame in inputs.items():
        cerebro.adddata(bt.feeds.PandasData(dataname=frame), name=asset)
    spec = {"indicator": example.Alpha003Indicator, "panel_line": "factor"}
    if invalid in {"execution", "line", "inputs"}:
        spec[invalid] = {"execution": "indicator", "line": "factor", "inputs": ("target",)}[invalid]
    elif invalid == "ordinary":
        spec["indicator"] = bt.ind.SMA
    else:
        del spec["panel_line"]
    cerebro.addstrategy(
        FactorStrategy,
        factors={"alpha003": spec},
        research=example.make_research(inputs["A"].index, tuple(inputs)),
    )
    with pytest.raises((TypeError, ValueError)):
        cerebro.run()
