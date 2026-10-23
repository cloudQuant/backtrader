"""Shared deterministic fixtures and Cerebro helpers for Iteration 46.

The matrix oracle lives in :mod:`tests.test_utils.alpha101_full_reference` and
does not import Backtrader.  This module only adapts the already reviewed
Iteration 45 synthetic feed helpers to the production Alpha101 registry.
"""

from __future__ import annotations

from collections import OrderedDict
from types import MappingProxyType
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

import math
import os

import pandas as pd

import backtrader as bt
from backtrader.research.alpha101 import ALPHA_REGISTRY, get_alpha
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research.specs import FactorSpec, ResearchSpec
from tests.test_utils.alpha101_full_reference import (
    formula_ids,
    formula_metadata,
    history_h,
    reference,
)
from tests.unit.test_factor_research_representatives import (
    _factor_spec,
    _frames as _representative_frames,
    _research_feed,
    _research_spec as _representative_research_spec,
)

PROMOTED_ALPHA_IDS = (
    1,
    2,
    3,
    4,
    7,
    9,
    13,
    29,
    48,
    56,
    58,
    62,
    63,
    67,
    81,
    84,
    92,
    96,
    100,
    101,
)

# Keep these exact lists aligned with the five L2 implementation batches.  The
# first batch includes a few TS formulas because they share the same small
# source/operator closure; the remaining groups are risk-family oriented.
NEW_ALPHA_BATCHES: Mapping[str, Tuple[int, ...]] = MappingProxyType(
    OrderedDict(
        (
            ("a", (5, 6, 8, 10, 11, 12, 14, 15, 16, 17, 18, 19, 20)),
            ("b", tuple(value for value in range(21, 41) if value != 29)),
            ("c", tuple(value for value in range(41, 62) if value not in (48, 56, 58))),
            ("d", tuple(value for value in range(64, 81) if value != 67)),
            ("e", tuple(value for value in range(82, 100) if value not in (84, 92, 96))),
        )
    )
)

ALPHA_BATCHES: Mapping[str, Tuple[int, ...]] = MappingProxyType(
    OrderedDict((("promoted_20", PROMOTED_ALPHA_IDS), *NEW_ALPHA_BATCHES.items()))
)

_ORACLE_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vwap",
    "dollar_volume",
    "cap",
    "sector",
    "industry",
    "subindustry",
)
_BATCH_ENV = "BT_ALPHA101_NATIVE_BATCHES"
_IDS_ENV = "BT_ALPHA101_NATIVE_IDS"


def selected_alpha_batches(
    environ: Optional[Mapping[str, str]] = None,
) -> Tuple[Tuple[str, Tuple[int, ...]], ...]:
    """Resolve an optional focused batch/ID selection for ordinary pytest.

    With no environment selector this returns all six acceptance batches and
    therefore covers every ID.  ``BT_ALPHA101_NATIVE_BATCHES`` accepts comma-
    separated ``promoted_20,a,b,c,d,e`` names.  ``BT_ALPHA101_NATIVE_IDS``
    accepts comma-separated integer IDs.  Supplying both takes their
    intersection, which is useful when focusing one formula inside a batch.
    """

    env = os.environ if environ is None else environ
    requested_batches = _csv(env.get(_BATCH_ENV, ""))
    requested_ids = _parse_alpha_ids(env.get(_IDS_ENV, ""))
    unknown_batches = set(requested_batches) - set(ALPHA_BATCHES)
    if unknown_batches:
        raise ValueError("unknown Alpha101 batch selector(s): %s" % sorted(unknown_batches))
    catalog_ids = set(formula_ids())
    unknown_ids = requested_ids - catalog_ids
    if unknown_ids:
        raise ValueError("Alpha101 ID selector(s) must be in 1..101: %s" % sorted(unknown_ids))

    selected_names = requested_batches or tuple(ALPHA_BATCHES)
    focused = bool(requested_batches or requested_ids)
    result = []
    for batch_name in selected_names:
        ids = ALPHA_BATCHES[batch_name]
        if requested_ids:
            ids = tuple(alpha_id for alpha_id in ids if alpha_id in requested_ids)
        if ids:
            result.append((batch_name, tuple(ids)))
    if focused and not result:
        raise ValueError("the requested Alpha101 batch/ID selection is empty")
    return tuple(result)


def selection_is_focused(environ: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if environ is None else environ
    return bool(_csv(env.get(_BATCH_ENV, "")) or _csv(env.get(_IDS_ENV, "")))


def selected_alpha_ids(
    environ: Optional[Mapping[str, str]] = None,
) -> Tuple[int, ...]:
    return tuple(alpha_id for _, ids in selected_alpha_batches(environ) for alpha_id in ids)


def make_positive_fixture(periods: int = 320) -> Dict[str, pd.DataFrame]:
    """Return six deterministic assets with positive inputs and PIT classes."""

    if periods < 320:
        raise ValueError("the full Alpha101 matrix fixture requires at least 320 bars")
    return _representative_frames(periods=periods)


def oracle_frames(
    frames: Mapping[str, Any],
    *,
    grid: Optional[Sequence[Any]] = None,
) -> Dict[str, list]:
    """Project asset DataFrames into rectangular oracle time×asset matrices.

    Reindexing onto ``grid`` preserves real missing bars as NaNs without
    shifting later rows.  Classification values are passed through as the
    already projected PIT rows; this helper never backfills categories.
    """

    assets = tuple(frames)
    if not assets:
        raise ValueError("frames must include at least one asset")
    if grid is None:
        grid = tuple(next(iter(frames.values())).index)
    else:
        grid = tuple(grid)
    matrices: Dict[str, list] = {}
    for field in _ORACLE_FIELDS:
        series_by_asset = {
            asset: (frames[asset][field].reindex(grid) if field in frames[asset].columns else None)
            for asset in assets
        }
        rows = []
        for row_index, _point in enumerate(grid):
            row = []
            for asset in assets:
                series = series_by_asset[asset]
                if series is None:
                    row.append(math.nan)
                    continue
                value = series.iloc[row_index]
                if pd.isna(value):
                    row.append(math.nan)
                elif field in ("sector", "industry", "subindustry"):
                    row.append(value)
                else:
                    row.append(float(value))
            rows.append(row)
        matrices[field] = rows
    return matrices


def formula_universe_matrix(grid: Sequence[Any], assets: Sequence[str]) -> pd.Series:
    """Compatibility shim for the removed dynamic formula-universe table.

    The research API no longer takes ``formula_universe``: cross-sectional
    membership is now decided per grid point by real bars.  Callers keep using
    this helper to describe "all declared targets are eligible", which the
    strategy derives itself.
    """
    keys = pd.MultiIndex.from_product([list(grid), list(assets)], names=("time", "asset"))
    return pd.Series(True, index=keys, dtype=bool)


def assert_presence_matches_finite_values(strategy: Any, *args: Any, **kwargs: Any) -> None:
    """Every finite factor value must sit on a grid point with a real bar."""
    panel = strategy.get_panel()
    import numpy as np

    values = panel.factors.to_numpy(dtype="float64")
    finite = np.isfinite(values)
    assert finite.any(), "no finite factor values to witness"
    times = panel.factors.index.get_level_values("time")
    assets = panel.factors.index.get_level_values("asset")
    for index in np.argwhere(finite)[:200]:
        row, column = int(index[0]), int(index[1])
        data = next(item for item in strategy.datas if getattr(item, "_name", "") == assets[row])
        alignment = getattr(data, "_factor_research_alignment_v2", None)
        if alignment is None:
            continue
        grid = list(strategy._grid)
        position = grid.index(times[row].to_pydatetime())
        assert bool(
            alignment["present"][position]
        ), "finite value %r at %s/%s without a real bar" % (
            panel.factor_order[column],
            times[row],
            assets[row],
        )


def presence_matrix(frames: Mapping[str, Any], grid: Sequence[Any]) -> list:
    """Return the real-bar membership matrix for one fixture on the grid.

    Cross-sectional membership is ordinary bar presence in this API; there is
    no separate caller-supplied formula-universe table anymore.
    """
    assets = tuple(frames)
    return [[point in frames[asset].index for asset in assets] for point in grid]


def make_research_spec(
    frames: Mapping[str, Any],
    *,
    groups: Optional[Mapping[str, str]] = None,
) -> ResearchSpec:
    """Build the fixture ResearchSpec (calendar, targets, groups)."""
    return _representative_research_spec(frames, groups=groups)


def _assert_one_native_class_metadata(alpha_id: int, factor_class: Any) -> None:
    if not isinstance(factor_class, type) or not issubclass(factor_class, FactorIndicator):
        raise AssertionError("Alpha%d must be a FactorIndicator class" % alpha_id)

    metadata = formula_metadata(alpha_id)
    direct_fields = tuple(metadata["direct_market_fields"])
    formula_fields = tuple(metadata["formula_fields"])
    required_fields = tuple(metadata["required_input_fields"])
    if len(direct_fields) != len(set(direct_fields)):
        raise AssertionError("Alpha%d catalog direct fields contain duplicates" % alpha_id)
    if len(formula_fields) != len(set(formula_fields)):
        raise AssertionError("Alpha%d catalog formula fields contain duplicates" % alpha_id)
    logical_fields = set(direct_fields) | set(formula_fields)
    if set(required_fields) != logical_fields:
        raise AssertionError("Alpha%d catalog field closure is inconsistent" % alpha_id)

    # Native classes declare physical lines. The catalog names logical inputs:
    # `returns` is derived from close, while each advN line is supplied by the
    # explicit ADV alias and its dollar_volume source.
    expected_fields = set(logical_fields)
    if "returns" in expected_fields:
        expected_fields.remove("returns")
        expected_fields.add("close")
    if any(field.startswith("adv") and field[3:].isdigit() for field in logical_fields):
        expected_fields.add("dollar_volume")

    declared_fields = tuple(factor_class.formula_fields)
    if not declared_fields or len(declared_fields) != len(set(declared_fields)):
        raise AssertionError(
            "Alpha%d native formula_fields must be unique and non-empty" % alpha_id
        )
    # Neutralization levels are now ordinary declared fields, so the catalog
    # closure must be a subset of the declaration rather than equal to it.
    if not expected_fields.issubset(set(declared_fields)):
        raise AssertionError(
            "Alpha%d native formula_fields miss catalog inputs: declared=%r missing=%r"
            % (alpha_id, sorted(declared_fields), sorted(expected_fields - set(declared_fields)))
        )

    # Neutralization levels are ordinary declared formula fields; every level
    # the catalog requires must be declared as a bindable feed line.
    expected_levels = tuple(
        dict.fromkeys(call["level"] for call in metadata["classification_requirements"]["calls"])
    )
    if any(level not in declared_fields for level in expected_levels):
        raise AssertionError(
            "Alpha%d does not declare its catalog classification levels as formula fields: %r"
            % (alpha_id, expected_levels)
        )
    if any(level not in {"sector", "industry", "subindustry"} for level in expected_levels):
        raise AssertionError("Alpha%d catalog declares an unknown classification level" % alpha_id)

    declared_h = factor_class.lookback_h
    if type(declared_h) is not int or declared_h < 0 or declared_h != history_h(alpha_id):
        raise AssertionError(
            "Alpha%d native lookback_h differs from independent catalog H=%r"
            % (alpha_id, history_h(alpha_id))
        )


def assert_native_class_metadata(
    alpha_ids: Iterable[int], *, alpha_classes: Optional[Mapping[int, Any]] = None
) -> None:
    """Validate selected native class metadata before starting Cerebro."""

    ids = tuple(alpha_ids)
    if not ids:
        raise AssertionError("at least one Alpha101 ID is required for metadata validation")
    if any(type(alpha_id) is not int or alpha_id not in formula_ids() for alpha_id in ids):
        raise AssertionError("Alpha101 metadata validation requires IDs in 1..101")
    if len(ids) != len(set(ids)):
        raise AssertionError("Alpha101 metadata validation IDs must be unique")

    if alpha_classes is None:
        classes = {alpha_id: get_alpha(alpha_id) for alpha_id in ids}
    else:
        if any(type(alpha_id) is not int for alpha_id in alpha_classes):
            raise AssertionError("alpha_classes keys must be exact integer IDs")
        classes = dict(alpha_classes)
        if set(classes) != set(ids):
            raise AssertionError("alpha_classes must provide exactly the requested IDs")
    for alpha_id in ids:
        _assert_one_native_class_metadata(alpha_id, classes[alpha_id])


def run_native_batch(
    frames: Mapping[str, Any],
    alpha_ids: Iterable[int],
    *,
    runonce: bool,
    factor_mode: str = "native",
    factor_modes: Optional[Mapping[int, str]] = None,
    alpha_classes: Optional[Mapping[int, Any]] = None,
    research: Optional[ResearchSpec] = None,
    groups: Optional[Mapping[str, str]] = None,
) -> Any:
    """Run selected factor classes through real Cerebro and FactorStrategy."""

    ids = tuple(alpha_ids)
    if not ids:
        raise ValueError("at least one Alpha101 ID is required")
    if factor_mode not in ("native", "build"):
        raise ValueError("factor_mode must be 'native' or 'build'")
    if factor_modes is None:
        modes = dict.fromkeys(ids, factor_mode)
    else:
        modes = dict(factor_modes)
        if set(modes) != set(ids):
            raise ValueError("factor_modes must provide exactly the requested Alpha101 IDs")
        if any(mode not in ("native", "build") for mode in modes.values()):
            raise ValueError("factor_modes values must be 'native' or 'build'")
    if alpha_classes is None:
        classes = {alpha_id: get_alpha(alpha_id) for alpha_id in ids}
    else:
        classes = dict(alpha_classes)
        if set(classes) != set(ids):
            raise ValueError("alpha_classes must provide exactly the requested Alpha101 IDs")
    assert_native_class_metadata(ids, alpha_classes=classes)
    research = research or make_research_spec(frames, groups=groups)
    cerebro = bt.Cerebro(stdstats=False, runonce=bool(runonce))
    for asset, frame in frames.items():
        cerebro.adddata(_research_feed(frame, research, asset), name=asset)
    factors = {}
    for alpha_id in ids:
        name = alpha_name(alpha_id)
        base_spec = _factor_spec(name, classes[alpha_id])
        factors[name] = FactorSpec(
            name=base_spec.name,
            indicator=base_spec.indicator,
            panel_line=base_spec.panel_line,
            params=base_spec.params,
            field_bindings=base_spec.field_bindings,
            operator_profile=base_spec.operator_profile,
            direction=base_spec.direction,
            mode=modes[alpha_id],
        )
    if any(spec.mode != modes[int(name.removeprefix("alpha"))] for name, spec in factors.items()):
        raise AssertionError("Alpha101 FactorSpec mode differs from the explicit mode selection")
    cerebro.addstrategy(FactorStrategy, research=research, factors=factors)

    broker = cerebro.broker
    broker_calls = {"submit": 0, "cancel": 0}

    def counted_submit(*args: Any, **kwargs: Any) -> Any:
        broker_calls["submit"] += 1
        raise AssertionError("FactorStrategy unexpectedly submitted a broker order")

    def counted_cancel(*args: Any, **kwargs: Any) -> Any:
        broker_calls["cancel"] += 1
        raise AssertionError("FactorStrategy unexpectedly cancelled a broker order")

    broker.submit = counted_submit
    broker.cancel = counted_cancel
    strategy = cerebro.run()[0]
    strategy._alpha101_broker_call_counts = dict(broker_calls)
    strategy._alpha101_factor_modes_expected = {
        alpha_name(alpha_id): modes[alpha_id] for alpha_id in ids
    }
    strategy._alpha101_factor_specs = dict(factors)
    strategy._alpha101_factor_mode_witnesses = assert_factor_mode_witnesses(strategy, ids, modes)
    return strategy


def assert_factor_mode_witnesses(
    strategy: Any,
    alpha_ids: Iterable[int],
    expected_modes: Mapping[int, str],
) -> Dict[str, Dict[str, Any]]:
    """Verify the requested implementation mode on each actual bound instance."""
    witnesses: Dict[str, Dict[str, Any]] = {}
    for alpha_id in alpha_ids:
        name = alpha_name(alpha_id)
        expected = expected_modes[alpha_id]
        factor = strategy.factor_instances[name]
        instances = strategy._factor_instances_by_name.get(name)
        if not instances:
            raise AssertionError("%s has no bound FactorIndicator instance" % name)
        group_names = {
            id(instance): group
            for group, instance in getattr(factor, "group_instances", {}).items()
        }
        bound_instances = []
        for instance in instances:
            mode = getattr(instance, "factor_mode", None)
            if mode != expected:
                raise AssertionError(
                    "%s bound factor instance mode differs from requested %s: %r"
                    % (name, expected, mode)
                )
            _validate_factor_instance_witness(instance, mode, name)
            context = getattr(instance, "_expression_context", None)
            expression_node_count = len(instance._nodes) if context is not None else 0
            expression_context = context is not None
            descendants = []
            for child in FactorStrategy._factor_tree(instance)[1:]:
                child_mode = getattr(child, "factor_mode", None)
                _validate_factor_instance_witness(child, child_mode, name + " descendant")
                child_context = getattr(child, "_expression_context", None)
                descendants.append(
                    {
                        "class": "%s.%s"
                        % (child.__class__.__module__, child.__class__.__qualname__),
                        "factor_mode": child_mode,
                        "runtime_mode": child._factor_runtime.get("mode"),
                        "has_expression_context": child_context is not None,
                        "expression_node_count": (
                            len(child._nodes) if child_context is not None else 0
                        ),
                    }
                )
            bound_instances.append(
                {
                    "group": group_names.get(id(instance)),
                    "assets": list(instance._factor_runtime.get("asset_names", ())),
                    "factor_mode": mode,
                    "has_expression_context": expression_context,
                    "expression_node_count": expression_node_count,
                    "descendants": descendants,
                }
            )
        instance_modes = [item["factor_mode"] for item in bound_instances]
        if any(mode != expected for mode in instance_modes):
            raise AssertionError(
                "%s bound factor instances mix modes for requested %s: %r"
                % (name, expected, instance_modes)
            )
        witnesses[str(alpha_id)] = {
            "root_mode": instance_modes[0],
            "bound_instance_count": len(bound_instances),
            "bound_instances": bound_instances,
            "build_context_count": sum(item["has_expression_context"] for item in bound_instances),
            "build_node_count": sum(item["expression_node_count"] for item in bound_instances),
        }
    return witnesses


def _validate_factor_instance_witness(instance: Any, mode: Any, label: str) -> None:
    """Validate a real bound FactorIndicator against its own mode capability."""
    runtime = getattr(instance, "_factor_runtime", None)
    if not isinstance(runtime, Mapping) or mode not in ("native", "build"):
        raise AssertionError("%s has no valid bound factor mode" % label)
    if runtime.get("mode") != mode or getattr(instance, "factor_mode", None) != mode:
        raise AssertionError("%s public and runtime factor modes differ" % label)
    try:
        instance.__class__._resolve_factor_mode(mode)
    except (NotImplementedError, TypeError, ValueError) as exc:
        raise AssertionError("%s bound mode is not supported by its class" % label) from exc
    context = getattr(instance, "_expression_context", None)
    if mode == "build":
        nodes = getattr(instance, "_nodes", None)
        if (
            context is None
            or not isinstance(nodes, Mapping)
            or not nodes
            or getattr(context, "nodes", None) is not nodes
        ):
            raise AssertionError("%s build mode lacks bound expression node paths" % label)
    elif context is not None:
        raise AssertionError("%s native mode unexpectedly has a build context" % label)


def alpha_name(alpha_id: int) -> str:
    return "alpha%d" % alpha_id


def oracle_expected(
    alpha_id: int,
    frames: Mapping[str, Any],
    *,
    grid: Optional[Sequence[Any]] = None,
    groups: Optional[Mapping[str, str]] = None,
) -> Tuple[list, int]:
    matrices = oracle_frames(frames, grid=grid)
    oracle_groups = (
        tuple(groups[asset] for asset in frames) if isinstance(groups, Mapping) else groups
    )
    points = tuple(grid) if grid is not None else tuple(next(iter(frames.values())).index)
    # Membership is real-bar based in the current profile; the reference still
    # takes an explicit all-eligible matrix for its cross-sectional steps.
    formula_universe = [[True] * len(frames) for _ in points]
    expected = reference(
        alpha_id,
        matrices,
        formula_universe=formula_universe,
        groups=oracle_groups,
    )
    declared_h = history_h(alpha_id, matrices)
    # The panel preserves the formula's own finite/NaN output on every row;
    # only incomplete presence windows are masked by the collector.
    return [list(row) for row in expected], declared_h


def actual_matrix(strategy: Any, alpha_id: int, assets: Sequence[str], grid: Sequence[Any]) -> list:
    factors = strategy.get_panel().factors
    name = alpha_name(alpha_id)
    return [
        [float(factors.at[(point.to_pydatetime(), asset), name]) for asset in assets]
        for point in grid
    ]


def assert_matrix_matches(
    actual: Sequence[Sequence[float]], expected: Sequence[Sequence[float]], *, label: str
) -> None:
    if len(actual) != len(expected):
        raise AssertionError(
            "%s time-row count differs: %d != %d" % (label, len(actual), len(expected))
        )
    for row_index, (actual_row, expected_row) in enumerate(zip(actual, expected)):
        if len(actual_row) != len(expected_row):
            raise AssertionError("%s asset count differs at row %d" % (label, row_index))
        for asset_index, (got, wanted) in enumerate(zip(actual_row, expected_row)):
            got, wanted = float(got), float(wanted)
            location = "row %d asset %d" % (row_index, asset_index)
            if math.isnan(wanted):
                if not math.isnan(got):
                    raise AssertionError("%s %s: expected NaN, got %.17g" % (label, location, got))
                continue
            if not math.isfinite(wanted):
                raise AssertionError(
                    "%s oracle produced a non-finite expected result at %s" % (label, location)
                )
            if not math.isfinite(got):
                raise AssertionError(
                    "%s %s: expected finite %.17g, got %r" % (label, location, wanted, got)
                )
            # A 0/1 value is a discrete signal cell and is required to match
            # exactly. Continuous values use the fixed Alpha101 tolerance.
            if wanted in (0.0, 1.0):
                if got != wanted:
                    raise AssertionError(
                        "%s %s: discrete expected %.17g, got %.17g" % (label, location, wanted, got)
                    )
                continue
            tolerance = 1e-12 + 1e-10 * abs(wanted)
            if abs(got - wanted) > tolerance:
                raise AssertionError(
                    "%s %s: got %.17g expected %.17g tolerance %.17g"
                    % (label, location, got, wanted, tolerance)
                )
    actual_finite = sum(math.isfinite(float(value)) for row in actual for value in row)
    expected_finite = sum(math.isfinite(float(value)) for row in expected for value in row)
    if actual_finite != expected_finite:
        raise AssertionError(
            "%s finite-cell count differs: %d != %d" % (label, actual_finite, expected_finite)
        )


def assert_lifecycle(
    strategy: Any,
    alpha_ids: Iterable[int],
    grid: Sequence[Any],
    *,
    alpha_classes: Optional[Mapping[int, Any]] = None,
) -> None:
    expected_names = {alpha_name(alpha_id) for alpha_id in alpha_ids}
    expected_times = tuple(point.to_pydatetime() for point in grid)
    assert set(strategy.factor_instances) == expected_names
    assert strategy._alpha101_broker_call_counts == {"submit": 0, "cancel": 0}
    expected_modes_by_name = getattr(strategy, "_alpha101_factor_modes_expected", None)
    assert isinstance(
        expected_modes_by_name, Mapping
    ), "explicit FactorSpec modes were not retained"
    specs_by_name = getattr(strategy, "_alpha101_factor_specs", None)
    assert isinstance(specs_by_name, Mapping), "explicit FactorSpec objects were not retained"
    assert set(specs_by_name) == set(expected_modes_by_name)
    for name, spec in specs_by_name.items():
        assert spec.mode == expected_modes_by_name[name], "%s FactorSpec mode differs" % name
    assert_factor_mode_witnesses(
        strategy,
        (int(name.removeprefix("alpha")) for name in expected_names),
        {int(name.removeprefix("alpha")): mode for name, mode in expected_modes_by_name.items()},
    )
    broker = strategy.broker
    assert not broker.orders
    assert not broker.pending
    assert not broker.submitted
    for name in sorted(expected_names):
        alpha_id = int(name.removeprefix("alpha"))
        factor = strategy.factor_instances[name]
        factor_class = alpha_classes[alpha_id] if alpha_classes is not None else get_alpha(alpha_id)
        _assert_one_native_class_metadata(alpha_id, factor_class)
        assert factor._minperiod == factor_class.lookback_h + 1
        diagnostics = factor.lifecycle_diagnostics
        assert diagnostics["call_count"] == len(grid), "%s ran an unexpected number of times" % name
        assert diagnostics["grid_count"] == len(grid)
        assert diagnostics["grid_matches"]
        assert tuple(diagnostics["call_times"]) == expected_times
        for nested in FactorStrategy._factor_tree(factor):
            nested_diagnostics = nested.lifecycle_diagnostics
            assert nested_diagnostics["call_count"] == len(grid)
            assert nested_diagnostics["grid_count"] == len(grid)
            assert nested_diagnostics["grid_matches"]
            assert tuple(nested_diagnostics["call_times"]) == expected_times


def assert_panel_matches_oracle(
    strategy: Any,
    expected: Mapping[int, Sequence[Sequence[float]]],
    assets: Sequence[str],
    grid: Sequence[Any],
    *,
    label: str,
) -> None:
    """Compare every selected factor's panel column with the oracle matrix."""
    for alpha_id, matrix in expected.items():
        assert_matrix_matches(
            actual_matrix(strategy, alpha_id, assets, grid),
            matrix,
            label="%s Alpha%d" % (label, alpha_id),
        )


def assert_finite_witness(
    alpha_id: int, expected: Sequence[Sequence[float]], declared_h: int
) -> None:
    finite = [
        value for row in expected[declared_h:] for value in row if math.isfinite(float(value))
    ]
    assert finite, "Alpha%d positive fixture has no finite oracle witness after H=%d" % (
        alpha_id,
        declared_h,
    )


def _csv(value: str) -> Tuple[str, ...]:
    return tuple(token.strip() for token in value.split(",") if token.strip())


def _parse_alpha_ids(value: str) -> set:
    parsed = set()
    for token in _csv(value):
        try:
            alpha_id = int(token)
        except ValueError as exc:
            raise ValueError("Alpha101 ID selectors must be comma-separated integers") from exc
        if str(alpha_id) != token and token not in ("+%d" % alpha_id,):
            raise ValueError("Alpha101 ID selector is not a canonical integer: %r" % token)
        parsed.add(alpha_id)
    return parsed


def assert_batch_partition() -> None:
    seen = []
    for ids in ALPHA_BATCHES.values():
        seen.extend(ids)
    assert len(seen) == len(set(seen)), "Alpha101 batch lists overlap"
    assert set(seen) == set(formula_ids()) == set(range(1, 102))


def assert_registry_covers_all_ids() -> None:
    assert tuple(sorted(ALPHA_REGISTRY)) == tuple(formula_ids())
    for alpha_id in formula_ids():
        assert get_alpha(alpha_id) is ALPHA_REGISTRY[alpha_id]


def selected_scenario_ids(
    candidates: Sequence[int],
    environ: Optional[Mapping[str, str]] = None,
) -> Tuple[int, ...]:
    selected = set(selected_alpha_ids(environ))
    return tuple(alpha_id for alpha_id in candidates if alpha_id in selected)


__all__ = (
    "ALPHA_BATCHES",
    "NEW_ALPHA_BATCHES",
    "PROMOTED_ALPHA_IDS",
    "actual_matrix",
    "alpha_name",
    "assert_batch_partition",
    "assert_finite_witness",
    "assert_lifecycle",
    "assert_matrix_matches",
    "assert_native_class_metadata",
    "assert_panel_matches_oracle",
    "assert_registry_covers_all_ids",
    "make_positive_fixture",
    "make_research_spec",
    "oracle_expected",
    "oracle_frames",
    "presence_matrix",
    "run_native_batch",
    "selected_alpha_batches",
    "selected_alpha_ids",
    "selected_scenario_ids",
    "selection_is_focused",
)
