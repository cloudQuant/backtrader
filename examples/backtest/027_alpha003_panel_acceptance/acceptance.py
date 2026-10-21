"""Independent, deterministic acceptance checks for the local Alpha003 example."""

from datetime import timedelta
from fractions import Fraction
import math

import pandas as pd


_FIELDS = ("open", "high", "low", "close", "volume")
_FACTOR = "alpha003"


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


def reference_alpha003(inputs, grid):
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
            if position >= 9:
                window_open = [row.get(asset) for row in ranks["open"][position - 9 : position + 1]]
                window_volume = [
                    row.get(asset) for row in ranks["volume"][position - 9 : position + 1]
                ]
                if all(value is not None for value in window_open + window_volume):
                    n = 10
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
    actual = strategy.get_dataset()
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


def _check_strategy_contract(strategy, grid, assets, label):
    _require(not strategy.getindicators(), "%s: declarations must not create BT indicators" % label)
    nodes = strategy.engine.nodes
    _require(
        isinstance(nodes, tuple) and len(nodes) == 6,
        "%s: Alpha003 graph must contain six shared nodes" % label,
    )
    counts = strategy.engine.evaluation_counts
    _require(
        isinstance(counts, dict) and len(counts) == 6,
        "%s: each graph node must expose an evaluation count" % label,
    )
    _require(
        all(type(count) is int and count == len(grid) for count in counts.values()),
        "%s: each graph node must evaluate once per grid step" % label,
    )
    diagnostics = strategy.get_diagnostics()
    required = {"time", "asset", "node", "operation", "value", "reason"}
    _require(
        isinstance(diagnostics, pd.DataFrame) and required.issubset(diagnostics.columns),
        "%s: diagnostics schema is incomplete" % label,
    )
    _require(
        len(diagnostics) == len(grid) * len(assets) * len(nodes),
        "%s: diagnostics must include each node/asset/grid evaluation" % label,
    )

    broker = strategy.broker
    _require(
        hasattr(broker, "get_orders_open") and not broker.get_orders_open(),
        "%s: example left open orders" % label,
    )
    _require(
        hasattr(broker, "orders") and not broker.orders, "%s: example submitted an order" % label
    )


def _must_reject(label, expected_exception, operation):
    try:
        operation()
    except expected_exception:
        return
    except Exception as exc:
        raise AssertionError("%s: wrong rejection type %s" % (label, type(exc).__name__)) from exc
    raise AssertionError("%s: invalid input was accepted" % label)


def _local_declarations():
    from alpha003_strategy import Alpha003Indicator
    from factor_strategy import PanelFactorIndicator

    alpha_class = Alpha003Indicator
    base_class = PanelFactorIndicator
    _require(
        issubclass(alpha_class, base_class),
        "Alpha003Indicator must be a local PanelFactorIndicator declaration",
    )
    return alpha_class, base_class


def run_acceptance(make_inputs, run_experiment):
    """Run local deterministic checks; this is not provider or Iteration45 acceptance."""
    alpha_class, panel_base = _local_declarations()
    inputs = make_inputs()
    assets = tuple(inputs)
    _require(len(assets) == 3, "fixture must contain exactly three assets")
    grid = tuple(inputs[assets[0]].index.to_pydatetime())
    _require(len(grid) == 10, "fixture must contain ten grid dates")
    checks = []
    run_counts = {"attempted": 0, "successful": 0}

    def counted_run(*args, **kwargs):
        run_counts["attempted"] += 1
        result = run_experiment(*args, **kwargs)
        run_counts["successful"] += 1
        return result

    base_runs = _run_modes(counted_run, inputs, grid, "base")
    for runonce, (strategy, expected, _) in zip((False, True), base_runs):
        label = "runonce=%s" % runonce
        _check_strategy_contract(strategy, grid, assets, label)
    checks.append("both Cerebro modes match the independent full-grid oracle")

    for asset, value in (("A", 17.0 / 23.0), ("B", 1.0), ("C", 17.0 / 23.0)):
        _require(
            math.isclose(
                float(expected.at[(grid[-1], asset), _FACTOR]), value, rel_tol=1e-12, abs_tol=1e-12
            ),
            "hand-calculated day-10 Alpha003 value failed for %s" % asset,
        )
    _require(
        expected.iloc[: 9 * len(assets)][_FACTOR].isna().all(),
        "the first nine grid rows must be missing during warmup",
    )
    checks.append("day-10 hand values and ten-bar warmup match")

    reverse_inputs = {asset: inputs[asset].copy(deep=True) for asset in reversed(assets)}
    _run_case(
        counted_run,
        reverse_inputs,
        grid,
        "reversed feed order",
        runonce=False,
        asset_order=tuple(reversed(assets)),
    )
    checks.append("reversing feed order preserves every value")

    changed_open = _copy_inputs(inputs)
    changed_open["B"].loc[pd.Timestamp(grid[-1]), "open"] = 9.5
    _, changed_expected, _ = _run_case(
        counted_run, changed_open, grid, "cross-asset rank change", runonce=False
    )
    _require(
        math.isclose(
            float(changed_expected.at[(grid[-1], "A"), _FACTOR]),
            math.sqrt(20.0 / 23.0),
            rel_tol=1e-12,
            abs_tol=1e-12,
        ),
        "changing B's current open must change A through the cross-sectional rank",
    )
    checks.append("B open=9.5 changes A's current rank and yields sqrt(20/23)")

    perturbed = _copy_inputs(inputs)
    future = grid[-1] + timedelta(days=1)
    for offset, asset in enumerate(assets):
        perturbed[asset].loc[pd.Timestamp(future), list(_FIELDS)] = (
            1000.0 + offset,
            2000.0 + offset,
            0.5,
            1000.0 + offset,
            9000.0 - 1000.0 * offset,
        )
    future_grid = grid + (future,)
    future_runs = _run_modes(counted_run, perturbed, future_grid, "future perturbation")
    for future_strategy, _, _ in future_runs:
        prefix = future_strategy.get_dataset().reindex(expected.index)
        for key, wanted in expected[_FACTOR].items():
            got = prefix.at[key, _FACTOR]
            _require(
                (pd.isna(got) and pd.isna(wanted))
                or (
                    not pd.isna(got)
                    and not pd.isna(wanted)
                    and math.isclose(float(got), float(wanted), rel_tol=1e-12, abs_tol=1e-12)
                ),
                "future perturbation changed prefix value at %r" % (key,),
            )
    checks.append("future observations do not alter the prior prefix")

    changed = _copy_inputs(inputs)
    changed["B"].loc[pd.Timestamp(grid[-1]), "open"] = float(
        changed["A"].loc[pd.Timestamp(grid[-1]), "open"]
    )
    tied_ranks = _fractional_ranks(_field_values(changed, grid[-1], "open"))
    _require(
        tied_ranks["A"] == tied_ranks["B"] == Fraction(1, 2),
        "exact tie ranks must use normalized average ranks",
    )
    _run_case(counted_run, changed, grid, "exact-tie ranks", runonce=False)
    checks.append("exact current-date ties match pairwise Fraction ranks")

    missing_one = _copy_inputs(inputs)
    missing_one["C"] = missing_one["C"].drop(pd.Timestamp(grid[4]))
    missing_expected = _run_modes(counted_run, missing_one, grid, "single-feed gap")[0][1]
    _require(
        pd.isna(missing_expected.at[(grid[-1], "C"), _FACTOR]),
        "a missing bar inside C's ten-date window must invalidate C",
    )
    checks.append("single-feed gap matches the oracle in both Cerebro modes")

    missing_all = _copy_inputs(inputs)
    for asset in assets:
        missing_all[asset] = missing_all[asset].drop(pd.Timestamp(grid[4]))
    all_gap_runs = _run_modes(counted_run, missing_all, grid, "all-feed gap")
    for _, _, all_missing_actual in all_gap_runs:
        _require(
            len(all_missing_actual) == len(grid) * len(assets),
            "an all-feed gap must not remove the requested grid date",
        )
        gap_values = all_missing_actual.xs(pd.Timestamp(grid[4]), level="time")[_FACTOR]
        _require(gap_values.isna().all(), "an all-feed gap must emit full-grid missing values")
    checks.append("all-feed interior gap matches the oracle in both modes")

    partial_primary = _copy_inputs(inputs)
    partial_primary["A"] = partial_primary["A"].drop(
        [pd.Timestamp(grid[0]), pd.Timestamp(grid[-1])]
    )
    _run_modes(counted_run, partial_primary, grid, "late-start/early-end primary")
    checks.append("late-start/early-end primary feed matches the full-grid oracle")

    trailing_gap = _copy_inputs(inputs)
    for asset in assets:
        trailing_gap[asset] = trailing_gap[asset].drop(pd.Timestamp(grid[-1]))
    trailing_runs = _run_modes(counted_run, trailing_gap, grid, "all-feed trailing gap")
    for _, _, trailing_actual in trailing_runs:
        _require(
            trailing_actual.xs(pd.Timestamp(grid[-1]), level="time")[_FACTOR].isna().all(),
            "stop must materialize the final requested grid date as missing",
        )
    checks.append("all-feed trailing gap preserves the final grid date in both modes")

    constant = _copy_inputs(inputs)
    for frame in constant.values():
        frame["open"] = 10.0
        frame["volume"] = 100.0
    _, constant_expected, _ = _run_case(
        counted_run, constant, grid, "zero-variance ranks", runonce=False
    )
    _require(
        constant_expected[_FACTOR].isna().all(),
        "constant ranks must produce missing correlation values",
    )
    checks.append("zero-variance windows fail closed as missing")

    duplicate, _, _ = _run_case(
        counted_run,
        _copy_inputs(inputs),
        grid,
        "shared duplicate declaration",
        runonce=False,
        factor_classes={_FACTOR: alpha_class, "alpha003_duplicate": alpha_class},
    )
    _check_strategy_contract(duplicate, grid, assets, "shared duplicate declaration")
    duplicate_data = duplicate.get_dataset()
    _require(
        "alpha003_duplicate" in duplicate_data.columns,
        "second declaration output column is missing",
    )
    _require(
        duplicate_data["alpha003_duplicate"].equals(duplicate_data[_FACTOR]),
        "duplicate declaration output must equal alpha003",
    )
    checks.append("duplicate declaration shares six nodes evaluated once per grid step")

    class UnknownSourceDeclaration(panel_base):
        @classmethod
        def build(cls, ctx):
            return ctx.unknown_source

    _must_reject(
        "unknown panel source",
        AttributeError,
        lambda: counted_run(
            _copy_inputs(inputs),
            grid,
            runonce=False,
            factor_classes={_FACTOR: UnknownSourceDeclaration},
        ),
    )

    missing_column = _copy_inputs(inputs)
    missing_column["A"] = missing_column["A"].drop(columns=["volume"])
    _must_reject(
        "missing required source column",
        ValueError,
        lambda: counted_run(missing_column, grid, runonce=False),
    )

    unknown_time = _copy_inputs(inputs)
    extra_time = pd.Timestamp(grid[-1]) + pd.Timedelta(days=1)
    unknown_time["A"].loc[extra_time, list(_FIELDS)] = (11.0, 20.0, 0.5, 10.0, 100.0)
    _must_reject(
        "timestamp outside explicit grid",
        ValueError,
        lambda: counted_run(unknown_time, grid, runonce=False),
    )

    for field in ("open", "volume"):
        infinite = _copy_inputs(inputs)
        infinite["A"].loc[pd.Timestamp(grid[0]), field] = math.inf
        _must_reject(
            "infinite %s source" % field,
            ValueError,
            lambda infinite=infinite: counted_run(infinite, grid, runonce=False),
        )
    checks.append("unknown sources, absent columns, outside-grid rows, and infinities reject")

    return {
        "status": "PASS",
        "evidence_level": "LOCAL_ALPHA003_PROTOTYPE_ONLY",
        "checks": checks,
        "cerebro_modes": ["runonce=False", "runonce=True"],
        "experiment_attempts": run_counts["attempted"],
        "successful_experiment_runs": run_counts["successful"],
        "rejected_input_cases": run_counts["attempted"] - run_counts["successful"],
        "assets": list(assets),
        "grid_rows": len(grid),
        "expected_value_cells": expected.size,
        "reference": "exact Fraction ranks and rolling Pearson covariance",
    }
