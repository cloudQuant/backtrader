"""Installed-wheel acceptance for the complete native Alpha101 registry.

This acceptance test is intentionally opt-in.  It must run from an external,
clean test tree against the committed Backtrader and fincore wheels; running it
from the source checkout could silently test the checkout instead.

External test-tree contents (relative to the tree root):

* ``tests/integration/test_alpha101_native_installed.py`` (this file)
* ``tests/test_utils/alpha101_full_reference.py``
* ``tests/test_utils/alpha101_native_harness.py``
* ``tests/unit/test_factor_research_representatives.py``
* ``tests/fixtures/research/alpha101_dependencies.json`` (the pinned public
  formula catalog copied from the source checkout)
* Empty ``__init__.py`` files in ``tests/``, ``tests/integration/``,
  ``tests/test_utils/`` and ``tests/unit/`` so the helper imports resolve to
  this external tree.

Run pytest with the external tree as the working directory, without setting
``PYTHONPATH``.  Set ``BT_ALPHA101_NATIVE_INSTALLED_ACCEPTANCE=1`` and
``BT_ALPHA101_NATIVE_PROVENANCE_JSON`` to a public JSON manifest with this
shape before invoking the test::

    {
      "schema": "iteration46-installed-alpha101-provenance-v1",
      "backtrader": {
        "source_commit": "<40- or 64-character commit hash>",
        "version": "<installed distribution version>",
        "wheel_path": "<path to the exact installed .whl>",
        "wheel_sha256": "<sha256 of that wheel>"
      },
      "fincore": { ... same four fields ... }
    }

The test hashes both supplied wheel files itself and records their hashes,
source commits, installed versions, exact import origins, copied oracle inputs,
matrix batches and the fincore result in ``alpha101-native-installed-acceptance.json``
under pytest's retained ``--basetemp`` directory.  This test does not build or
install either wheel.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
from typing import Any, Dict, Mapping, Sequence, Tuple

import pytest

_RUN_ENV = "BT_ALPHA101_NATIVE_INSTALLED_ACCEPTANCE"
_PROVENANCE_ENV = "BT_ALPHA101_NATIVE_PROVENANCE_JSON"
_IC_METRICS = ("pearson", "spearman")
_BATCHES: Tuple[Tuple[str, Tuple[int, ...]], ...] = (
    (
        "promoted_20",
        (1, 2, 3, 4, 7, 9, 13, 29, 48, 56, 58, 62, 63, 67, 81, 84, 92, 96, 100, 101),
    ),
    ("a", (5, 6, 8, 10, 11, 12, 14, 15, 16, 17, 18, 19, 20)),
    ("b", (21, 22, 23, 24, 25, 26, 27, 28, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40)),
    ("c", (41, 42, 43, 44, 45, 46, 47, 49, 50, 51, 52, 53, 54, 55, 57, 59, 60, 61)),
    ("d", (64, 65, 66, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80)),
    ("e", (82, 83, 85, 86, 87, 88, 89, 90, 91, 93, 94, 95, 97, 98, 99)),
)
_EVALUATION_IDS = (3, 9, 101)
_EVALUATION_START = 260
_EVALUATION_END = 285
_CONSTANT_RETURN_OFFSET = 278
_MASK_EXIT_START = 290
_MASK_EXIT_END = 292
_MASK_REENTRY = 302
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")

pytestmark = pytest.mark.skipif(
    os.environ.get(_RUN_ENV) != "1",
    reason="requires explicit installed Alpha101 wheel-acceptance authorization",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _installed_origin(module: Any, *, name: str) -> str:
    origin_value = getattr(module, "__file__", None)
    assert isinstance(origin_value, str) and origin_value, "%s has no file origin" % name
    origin = Path(origin_value).resolve()
    prefix = Path(sys.prefix).resolve()
    try:
        relative = origin.relative_to(prefix)
    except ValueError as exc:
        raise AssertionError("%s did not load underneath sys.prefix: %s" % (name, origin)) from exc
    assert any(
        part.lower() in ("site-packages", "dist-packages") for part in relative.parts
    ), "%s did not load from site-packages: %s" % (name, origin)
    return str(origin)


def _installed_packages() -> Tuple[Mapping[str, Any], Mapping[str, str]]:
    assert not os.environ.get("PYTHONPATH"), "installed acceptance must run without PYTHONPATH"
    backtrader = importlib.import_module("backtrader")
    factor_indicator = importlib.import_module("backtrader.research.factor_indicator")
    factor_strategy = importlib.import_module("backtrader.research.factor_strategy")
    fincore_adapter = importlib.import_module("backtrader.research.fincore_adapter")
    alpha101 = importlib.import_module("backtrader.research.alpha101")
    alpha_helpers = importlib.import_module("backtrader.research._helpers")
    alpha_metadata = importlib.import_module("backtrader.research.alpha101._metadata")
    alpha_modules = {}
    alpha_class_module_names = {}
    alpha_class_module_origins = {}
    for alpha_id in alpha101.list_alphas():
        factor_class = alpha101.get_alpha(alpha_id)
        module_name = "backtrader.research.alpha101.alpha%03d" % alpha_id
        assert factor_class.__module__ == module_name, (
            "Alpha%d class is not defined by its per-alpha module" % alpha_id
        )
        module = importlib.import_module(module_name)
        assert getattr(module, factor_class.__name__) is factor_class
        alpha_modules[alpha_id] = module
        alpha_class_module_names[str(alpha_id)] = module_name
        alpha_class_module_origins[str(alpha_id)] = _installed_origin(module, name=module_name)
    fincore = importlib.import_module("fincore")
    fincore_research = importlib.import_module("fincore.factor_analysis.research")
    origins = {
        "backtrader": _installed_origin(backtrader, name="backtrader"),
        "backtrader.research.factor_indicator": _installed_origin(
            factor_indicator, name="backtrader.research.factor_indicator"
        ),
        "backtrader.research.factor_strategy": _installed_origin(
            factor_strategy, name="backtrader.research.factor_strategy"
        ),
        "backtrader.research.fincore_adapter": _installed_origin(
            fincore_adapter, name="backtrader.research.fincore_adapter"
        ),
        "backtrader.research.alpha101": _installed_origin(
            alpha101, name="backtrader.research.alpha101"
        ),
        "backtrader.research._helpers": _installed_origin(
            alpha_helpers, name="backtrader.research._helpers"
        ),
        "backtrader.research.alpha101._metadata": _installed_origin(
            alpha_metadata, name="backtrader.research.alpha101._metadata"
        ),
        **{
            "backtrader.research.alpha101.alpha%03d" % int(alpha_id): module_origin
            for alpha_id, module_origin in alpha_class_module_origins.items()
        },
        "fincore": _installed_origin(fincore, name="fincore"),
        "fincore.factor_analysis.research": _installed_origin(
            fincore_research, name="fincore.factor_analysis.research"
        ),
    }
    versions = {
        "backtrader": importlib.metadata.version("backtrader"),
        "fincore": importlib.metadata.version("fincore"),
    }
    return {
        "backtrader": backtrader,
        "alpha101": alpha101,
        "alpha_modules": alpha_modules,
        "alpha_class_module_names": alpha_class_module_names,
        "alpha_class_module_origins": alpha_class_module_origins,
        "fincore": fincore,
    }, origins | {
        "backtrader_version": versions["backtrader"],
        "fincore_version": versions["fincore"],
    }


def _provenance(manifest_path_value: str, versions: Mapping[str, str]) -> Mapping[str, Any]:
    assert manifest_path_value, "%s is required" % _PROVENANCE_ENV
    manifest_path = Path(manifest_path_value).expanduser().resolve()
    assert manifest_path.is_file(), "installed-artifact provenance manifest is absent"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest.get("schema") == "iteration46-installed-alpha101-provenance-v1"
    result: Dict[str, Any] = {"manifest_sha256": _sha256_file(manifest_path)}
    for distribution in ("backtrader", "fincore"):
        item = manifest.get(distribution)
        assert isinstance(item, dict), "provenance is missing %s" % distribution
        source_commit = item.get("source_commit")
        wheel_sha256 = item.get("wheel_sha256")
        wheel_path_value = item.get("wheel_path")
        version = item.get("version")
        assert isinstance(source_commit, str) and _COMMIT_RE.fullmatch(source_commit), (
            "%s source_commit is not a full commit hash" % distribution
        )
        assert isinstance(wheel_sha256, str) and _HASH_RE.fullmatch(wheel_sha256), (
            "%s wheel_sha256 is not a lowercase SHA-256" % distribution
        )
        assert isinstance(wheel_path_value, str) and wheel_path_value
        wheel_path = Path(wheel_path_value).expanduser().resolve()
        assert wheel_path.is_file() and wheel_path.suffix.lower() == ".whl", (
            "%s wheel_path must name the installed wheel artifact" % distribution
        )
        actual_sha256 = _sha256_file(wheel_path)
        assert actual_sha256 == wheel_sha256, "%s wheel hash differs from provenance" % distribution
        assert version == versions[distribution], (
            "%s installed version differs from provenance" % distribution
        )
        result[distribution] = {
            "source_commit": source_commit,
            "version": version,
            "wheel_file": wheel_path.name,
            "wheel_sha256": actual_sha256,
        }
    return result


def _load_helpers() -> Mapping[str, Any]:
    reference = importlib.import_module("tests.test_utils.alpha101_full_reference")
    harness = importlib.import_module("tests.test_utils.alpha101_native_harness")
    fixture = importlib.import_module("tests.unit.test_factor_research_representatives")
    return {"reference": reference, "harness": harness, "fixture": fixture}


def _sha256_sources(external_root: Path) -> Mapping[str, str]:
    inputs = {
        "installed_test": external_root / "tests" / "integration" / Path(__file__).name,
        "full_reference": external_root / "tests" / "test_utils" / "alpha101_full_reference.py",
        "native_harness": external_root / "tests" / "test_utils" / "alpha101_native_harness.py",
        "representative_fixture": external_root
        / "tests"
        / "unit"
        / "test_factor_research_representatives.py",
        "formula_catalog": external_root
        / "tests"
        / "fixtures"
        / "research"
        / "alpha101_dependencies.json",
    }
    for name, path in inputs.items():
        assert path.is_file(), "external acceptance input is missing: %s" % name
    return {name: _sha256_file(path) for name, path in inputs.items()}


def _force_constant_forward_return(frames: Mapping[str, Any], offset: int) -> None:
    """Make one known next-open label constant while keeping valid OHLC ranges."""

    index = next(iter(frames.values())).index
    for row, open_value in ((offset + 1, 100.0), (offset + 2, 101.0)):
        point = index[row]
        for frame in frames.values():
            frame.loc[point, "open"] = open_value
            close = float(frame.loc[point, "close"])
            frame.loc[point, "high"] = max(open_value, close) + 0.28
            frame.loc[point, "low"] = min(open_value, close) - 0.20


def _formula_universe(index: Sequence[Any], assets: Sequence[str]) -> list:
    harness = importlib.import_module("tests.test_utils.alpha101_native_harness")
    members = harness.formula_universe_matrix(index, assets)
    excluded = assets.index("asset-5")
    for row in members:
        row[excluded] = False
    temporarily_excluded = assets.index("asset-4")
    for row in range(_MASK_EXIT_START, _MASK_EXIT_END + 1):
        members[row][temporarily_excluded] = False
    return members


def _oracle_matrices(
    frames: Mapping[str, Any],
    members: Sequence[Sequence[bool]],
    groups: Mapping[str, str],
) -> Tuple[Mapping[int, Sequence[Sequence[float]]], Mapping[int, int], Mapping[str, Any]]:
    helpers = _load_helpers()
    reference = helpers["reference"]
    harness = helpers["harness"]
    grid = tuple(next(iter(frames.values())).index)
    matrices = harness.oracle_frames(frames, grid=grid)
    group_values = tuple(groups.values())
    raw = reference.reference_all(
        matrices,
        groups=group_values,
    )
    expected: Dict[int, Sequence[Sequence[float]]] = {}
    histories: Dict[int, int] = {}
    for alpha_id in reference.formula_ids():
        history = reference.history_h(alpha_id, matrices)
        values = [list(row) for row in raw[alpha_id]]
        # H defines structural warmup only.  The independent expression
        # oracle has already applied membership at each cross-sectional
        # operation and at the final output, so do not impose a second,
        # blanket H-bar membership delay after re-entry.
        for offset in range(min(history, len(values))):
            values[offset] = [math.nan] * len(values[offset])
        expected[alpha_id] = values
        histories[alpha_id] = history
        harness.assert_finite_witness(alpha_id, values, history)
    return expected, histories, {"grid": grid, "assets": tuple(frames), "matrices": matrices}


def _average_ranks(values: Sequence[float]) -> list:
    return [
        1
        + sum(other < value for other in values)
        + (sum(other == value for other in values) - 1) / 2
        for value in values
    ]


def _pearson(left: Sequence[float], right: Sequence[float]) -> float:
    left_mean = statistics.mean(left)
    right_mean = statistics.mean(right)
    left_centered = [value - left_mean for value in left]
    right_centered = [value - right_mean for value in right]
    denominator = math.sqrt(
        math.fsum(value * value for value in left_centered)
        * math.fsum(value * value for value in right_centered)
    )
    return math.fsum(x * y for x, y in zip(left_centered, right_centered)) / denominator


def _ic_expectations(
    expected: Mapping[int, Sequence[Sequence[float]]],
    frames: Mapping[str, Any],
    grid: Sequence[Any],
    assets: Sequence[str],
) -> Mapping[Tuple[str, Any, str], Tuple[str | None, float | None]]:
    output: Dict[Tuple[str, Any, str], Tuple[str | None, float | None]] = {}
    for alpha_id in _EVALUATION_IDS:
        signal = "alpha%d" % alpha_id
        matrix = expected[alpha_id]
        finite_count = 0
        usable_count = 0
        for offset in range(_EVALUATION_START, _EVALUATION_END + 1):
            paired = []
            timestamp = grid[offset]
            for column, asset in enumerate(assets):
                factor_value = float(matrix[offset][column])
                next_open = float(frames[asset]["open"].iloc[offset + 1])
                following_open = float(frames[asset]["open"].iloc[offset + 2])
                label_value = following_open / next_open - 1.0
                if math.isfinite(factor_value) and math.isfinite(label_value):
                    paired.append((factor_value, label_value))
            left = [item[0] for item in paired]
            right = [item[1] for item in paired]
            if len(paired) < 2:
                reason = "INSUFFICIENT_ASSETS"
            elif len(set(left)) < 2:
                reason = "CONSTANT_FACTOR"
            elif len(set(right)) < 2:
                reason = "CONSTANT_RETURN"
            else:
                reason = None
            for metric in _IC_METRICS:
                key = (signal, timestamp, metric)
                if reason is not None:
                    output[key] = (reason, None)
                else:
                    metric_left = _average_ranks(left) if metric == "spearman" else left
                    metric_right = _average_ranks(right) if metric == "spearman" else right
                    output[key] = (None, _pearson(metric_left, metric_right))
                    usable_count += 1
            finite_count += len(paired)
        assert finite_count > 0, "%s has no finite evaluation pairs" % signal
        assert usable_count > 0, "%s has no finite independent IC witness" % signal
    assert any(
        reason == "CONSTANT_RETURN" for reason, _ in output.values()
    ), "the fixed fixture must contain a constant-return IC witness"
    return output


def _assert_ic_and_labels(
    result: Any,
    expected: Mapping[Tuple[str, Any, str], Tuple[str | None, float | None]],
    frames: Mapping[str, Any],
    grid: Sequence[Any],
    assets: Sequence[str],
) -> Mapping[str, int]:
    import pandas as pd

    window = tuple(range(_EVALUATION_START, _EVALUATION_END + 1))
    label_rows = result.labels
    assert set(label_rows["horizon"]) == {1}
    actual_label_keys = [(pd.Timestamp(row.time), row.asset) for row in label_rows.itertuples()]
    expected_label_keys = {
        (pd.Timestamp(grid[offset]), asset) for offset in window for asset in assets
    }
    assert len(actual_label_keys) == len(set(actual_label_keys))
    assert set(actual_label_keys) == expected_label_keys
    assert len(label_rows) == len(expected_label_keys)
    for row in label_rows.itertuples():
        offset = grid.index(pd.Timestamp(row.time))
        wanted = (
            float(frames[row.asset]["open"].iloc[offset + 2])
            / float(frames[row.asset]["open"].iloc[offset + 1])
            - 1.0
        )
        assert math.isfinite(float(row.value))
        assert abs(float(row.value) - wanted) <= 1e-12 + 1e-12 * abs(wanted)

    ic = result.ic.loc[(result.ic.record_type == "period") & (result.ic.variant == "raw")]
    actual_ic_keys = [(row.signal, pd.Timestamp(row.time), row.metric) for row in ic.itertuples()]
    assert len(actual_ic_keys) == len(set(actual_ic_keys))
    assert set(actual_ic_keys) == set(expected)
    assert len(ic) == len(expected)
    finite_count = degenerate_count = 0
    for row in ic.itertuples():
        reason, wanted = expected[(row.signal, pd.Timestamp(row.time), row.metric)]
        if reason is not None:
            assert pd.isna(row.value) and row.status == "UNEVALUABLE"
            assert row.reason == reason
            degenerate_count += 1
            continue
        assert row.metric in _IC_METRICS
        assert math.isfinite(float(row.value))
        assert pd.isna(row.reason)
        assert wanted is not None
        assert abs(float(row.value) - wanted) <= 1e-12 + 1e-10 * abs(wanted)
        finite_count += 1
    assert finite_count > 0 and degenerate_count > 0
    return {
        "label_rows": len(label_rows),
        "finite_ic_rows": finite_count,
        "degenerate_ic_rows": degenerate_count,
    }


def _evaluation_window_dataset(
    collected: Any,
    harness: Any,
    frames: Mapping[str, Any],
    members: Sequence[Sequence[bool]],
    groups: Mapping[str, str],
) -> Any:
    """Declare the fincore interval while retaining the full calculation grid."""

    from backtrader.research import ResearchDataset, ResearchSpec

    base = harness.make_research_spec(frames, formula_universe=members, groups=groups)
    grid = base.grid
    start = grid.index[_EVALUATION_START]
    end = grid.index[_EVALUATION_END]
    evaluation_times = grid.index[(grid.index >= start) & (grid.index <= end)]
    formula_times = grid.index[grid.index <= end]

    factor_names = tuple("alpha%d" % alpha_id for alpha_id in _EVALUATION_IDS)
    raw = collected.factors
    raw_times = raw.index.get_level_values("time")
    raw_window = raw.loc[raw_times.isin(evaluation_times), factor_names]

    availability = collected.availability
    availability_times = availability.index.get_level_values("time")
    availability_factors = availability.index.get_level_values("factor")
    availability_window = availability.loc[
        availability_times.isin(evaluation_times) & availability_factors.isin(factor_names)
    ]

    universe = base.universe
    universe = universe.loc[universe.index.get_level_values("time").isin(evaluation_times)]
    formula_universe = base.formula_universe
    formula_universe = formula_universe.loc[
        formula_universe.index.get_level_values("time").isin(formula_times)
    ]
    research = ResearchSpec(
        grid=grid,
        start=start,
        end=end,
        targets=base.targets,
        source_timezone=base.source_timezone,
        snapshot_id=base.snapshot_id,
        price_basis=base.price_basis,
        calendar_id=base.calendar_id,
        frequency=base.frequency,
        feed_time_kind=base.feed_time_kind,
        groups=base.groups,
        universe=universe,
        formula_fields=base.formula_fields,
        classifications=base.classifications,
    )

    provenance = collected.metadata["provenance"]
    factor_directions = provenance.get("factor_directions")
    assert isinstance(factor_directions, Mapping)
    assert set(factor_names).issubset(factor_directions)
    window_provenance = dict(provenance)
    window_provenance["factor_directions"] = {
        name: factor_directions[name] for name in factor_names
    }
    return ResearchDataset.from_collection(
        research=research,
        raw_factors=raw_window,
        availability=availability_window,
        prices=collected.prices,
        formula_inputs=base.formula_fields,
        classifications=base.classifications,
        provenance=window_provenance,
    )


def _formula_reentry_oracle_summary(
    expected: Mapping[int, Sequence[Sequence[float]]], assets: Sequence[str]
) -> Mapping[str, Any]:
    asset_index = assets.index("asset-4")
    for alpha_id, matrix in expected.items():
        assert all(
            not math.isfinite(float(matrix[row][asset_index]))
            for row in range(_MASK_EXIT_START, _MASK_EXIT_END + 1)
        ), ("oracle did not exclude asset-4 during Alpha%d exit" % alpha_id)
    first_finite = {}
    for alpha_id, matrix in expected.items():
        first_finite[str(alpha_id)] = next(
            (
                row
                for row in range(_MASK_EXIT_END + 1, len(matrix))
                if math.isfinite(float(matrix[row][asset_index]))
            ),
            None,
        )
    # Alpha3's outer rolling correlation consumes its recent cross-sectional
    # rank values, so the gap's final ineligible row remains in that rolling
    # window through row 301.  This is formula-graph propagation, not a
    # blanket application of FactorSpec.lookback_h to every formula.
    assert first_finite["3"] == _MASK_REENTRY == 302
    assert first_finite["1"] == _MASK_EXIT_END + 1
    return {
        "temporary_exit_rows": [_MASK_EXIT_START, _MASK_EXIT_END],
        "asset": "asset-4",
        "first_finite_row_by_alpha": first_finite,
        "projection": "independent expression graph membership propagation; no blanket H-bar delay",
    }


@pytest.mark.parametrize(
    ("batch_name", "alpha_ids"),
    _BATCHES,
    ids=["promoted_20"] + ["batch_%s" % name for name, _ in _BATCHES[1:]],
)
def test_installed_alpha101_batch_and_promoted_fincore_acceptance(tmp_path, batch_name, alpha_ids):
    packages, origins = _installed_packages()
    versions = {
        "backtrader": origins["backtrader_version"],
        "fincore": origins["fincore_version"],
    }
    provenance = _provenance(os.environ.get(_PROVENANCE_ENV, ""), versions)
    external_root = Path(__file__).resolve().parents[2]
    source_pins = _sha256_sources(external_root)

    helpers = _load_helpers()
    harness = helpers["harness"]
    reference = helpers["reference"]
    alpha101 = packages["alpha101"]
    assert tuple(harness.ALPHA_BATCHES.items()) == _BATCHES
    assert not harness.selection_is_focused(), "installed acceptance must cover the whole registry"
    harness.assert_batch_partition()
    harness.assert_registry_covers_all_ids()
    assert tuple(alpha101.list_alphas()) == tuple(reference.formula_ids()) == tuple(range(1, 102))
    alpha_modules = packages["alpha_modules"]
    class_module_names = packages["alpha_class_module_names"]
    class_module_origins = packages["alpha_class_module_origins"]
    for _, registry_alpha_ids in _BATCHES:
        for alpha_id in registry_alpha_ids:
            factor_class = alpha101.get_alpha(alpha_id)
            expected_module_name = "backtrader.research.alpha101.alpha%03d" % alpha_id
            assert factor_class.__module__ == expected_module_name
            module = alpha_modules[alpha_id]
            assert getattr(module, factor_class.__name__) is factor_class
            assert class_module_names[str(alpha_id)] == expected_module_name
            assert class_module_origins[str(alpha_id)] == origins[expected_module_name]

    frames = harness.make_positive_fixture(periods=320)
    _force_constant_forward_return(frames, _CONSTANT_RETURN_OFFSET)
    grid = tuple(next(iter(frames.values())).index)
    assets = tuple(frames)
    members = _formula_universe(grid, assets)
    groups = dict.fromkeys(assets, "market")
    expected, histories, oracle_context = _oracle_matrices(frames, members, groups)
    reentry_oracle = _formula_reentry_oracle_summary(expected, assets)
    expected_ic = (
        _ic_expectations(expected, frames, grid, assets) if batch_name == "promoted_20" else None
    )

    strategy = harness.run_native_batch(
        frames,
        alpha_ids,
        runonce=False,
        groups=groups,
    )
    for alpha_id in alpha_ids:
        factor_class = alpha101.get_alpha(alpha_id)
        label = "%s Alpha%d installed runnext" % (batch_name, alpha_id)
        assert factor_class.lookback_h == histories[alpha_id], label
        actual = harness.actual_matrix(strategy, alpha_id, assets, grid)
        harness.assert_matrix_matches(actual, expected[alpha_id], label=label)
        harness.assert_finite_witness(alpha_id, expected[alpha_id], histories[alpha_id])
    harness.assert_lifecycle(strategy, alpha_ids, grid)
    harness.assert_availability_matches_values(strategy, alpha_ids, grid, assets)
    batch_report = {
        batch_name: {
            "alpha_ids": list(alpha_ids),
            "formula_count": len(alpha_ids),
            "lookback_h": {str(alpha_id): histories[alpha_id] for alpha_id in alpha_ids},
            "finite_cells": {
                str(alpha_id): sum(
                    math.isfinite(float(value)) for row in expected[alpha_id] for value in row
                )
                for alpha_id in alpha_ids
            },
            "broker_calls": strategy._alpha101_broker_call_counts,
        }
    }

    fincore_evaluation: Mapping[str, Any]
    if batch_name == "promoted_20":
        assert expected_ic is not None
        # Keep the 320-row native collector evidence above.  The evaluator
        # dataset declares only its 260..285 factor interval, while retaining
        # the complete grid for warm-up and forward-label tail rows.
        collected = strategy.get_panel()
        # The mask includes a permanent excluded target and a temporary exit
        # with an explicit eligible re-entry.  Check the lifecycle reason on
        # the native availability pane as well as matrix NaN equality.
        availability = collected.availability
        exit_key = (grid[_MASK_EXIT_START].to_pydatetime(), "asset-4", "alpha3")
        reentry_key = (grid[_MASK_REENTRY].to_pydatetime(), "asset-4", "alpha3")
        assert availability.loc[exit_key, "reason"] == "FORMULA_INELIGIBLE"
        assert not bool(availability.loc[exit_key, "ready"])
        assert not bool(availability.loc[exit_key, "valid"])
        assert math.isfinite(expected[3][_MASK_REENTRY][assets.index("asset-4")])
        assert availability.loc[reentry_key, "reason"] == "READY"
        assert bool(availability.loc[reentry_key, "ready"])
        assert bool(availability.loc[reentry_key, "valid"])

        dataset = _evaluation_window_dataset(collected, harness, frames, members, groups)
        evaluation_grid = tuple(grid[_EVALUATION_START : _EVALUATION_END + 1])
        for evaluation_id in _EVALUATION_IDS:
            actual = harness.actual_matrix(strategy, evaluation_id, assets, evaluation_grid)
            harness.assert_matrix_matches(
                actual,
                expected[evaluation_id][_EVALUATION_START : _EVALUATION_END + 1],
                label="evaluation Alpha%d" % evaluation_id,
            )
        harness.assert_availability_matches_values(
            strategy, _EVALUATION_IDS, evaluation_grid, assets
        )
        assert tuple(dataset.grid.index) == tuple(grid)
        assert dataset.start == grid[_EVALUATION_START]
        assert dataset.end == grid[_EVALUATION_END]
        assert len(dataset.formula_universe) == (_EVALUATION_END + 1) * len(assets)
        assert len(dataset.factors) == len(evaluation_grid) * len(assets)
        assert set(dataset.factor_names) == {"alpha3", "alpha9", "alpha101"}

        snapshot_path = tmp_path / "alpha101-native-dataset"
        dataset.save(snapshot_path)
        from backtrader.research import load_dataset

        restored_dataset = load_dataset(snapshot_path)
        assert restored_dataset.dataset_id == dataset.dataset_id
        assert tuple(restored_dataset.grid.index) == tuple(grid)
        assert restored_dataset.start == grid[_EVALUATION_START]
        assert restored_dataset.end == grid[_EVALUATION_END]
        assert set(restored_dataset.factor_names) == {"alpha3", "alpha9", "alpha101"}
        assert dataset.factors.equals(restored_dataset.factors)
        assert dataset.availability.equals(restored_dataset.availability)
        assert dataset.formula_universe.equals(restored_dataset.formula_universe)
        assert len(restored_dataset.factors) == len(evaluation_grid) * len(assets)
        for evaluation_id in _EVALUATION_IDS:
            restored = (
                restored_dataset.factors["alpha%d" % evaluation_id]
                .unstack("asset")
                .reindex(index=evaluation_grid, columns=assets)
            )
            restored_values = restored.to_numpy().tolist()
            harness.assert_matrix_matches(
                restored_values,
                expected[evaluation_id][_EVALUATION_START : _EVALUATION_END + 1],
                label="snapshot Alpha%d" % evaluation_id,
            )

        result = restored_dataset.evaluate(
            label="next_open_to_open",
            start=grid[_EVALUATION_START],
            end=grid[_EVALUATION_END],
            periods=(1,),
            min_assets=2,
            quantiles=2,
            min_quantile_assets=1,
            stability_lags=(1,),
            max_loss=1.0,
        )
        fincore_report = _assert_ic_and_labels(result, expected_ic, frames, grid, assets)
        assert set(result.labels["asset"]) == set(assets)
        assert set(result.ic.loc[result.ic.variant == "raw", "signal"]) == {
            "alpha%d" % evaluation_id for evaluation_id in _EVALUATION_IDS
        }
        fincore_evaluation = {
            "status": "run_by_promoted_20_case",
            "formula_ids": list(_EVALUATION_IDS),
            "evaluation_rows": [_EVALUATION_START, _EVALUATION_END],
            "constant_return_row": _CONSTANT_RETURN_OFFSET,
            "dataset_id": restored_dataset.dataset_id,
            "result_status": result.status,
            "metrics": list(_IC_METRICS),
            **fincore_report,
        }
    else:
        assert expected_ic is None
        fincore_evaluation = {"status": "not_run_by_this_batch"}

    acceptance_record = {
        "schema": "iteration46-installed-alpha101-acceptance-v1",
        "evidence_level": (
            "INSTALLED_WHEEL_ALPHA101_BATCH_%s_ORACLE_MATRIX%s"
            % (
                batch_name.upper(),
                "_AND_FINCORE_SUBSET" if batch_name == "promoted_20" else "",
            )
        ),
        "selected_batch": batch_name,
        "selected_batch_alpha_ids": list(alpha_ids),
        "python": sys.version,
        "sys_prefix": str(Path(sys.prefix).resolve()),
        "origins": {key: value for key, value in origins.items() if not key.endswith("_version")},
        "alpha_class_implementation_modules": class_module_names,
        "alpha_class_module_origins": class_module_origins,
        "installed_versions": versions,
        "artifact_provenance": provenance,
        "external_test_inputs": source_pins,
        "oracle_formula_ids": list(reference.formula_ids()),
        "matrix_batches": batch_report,
        "formula_universe_mask": {
            "permanently_excluded_asset": "asset-5",
            "temporary_exit_asset": "asset-4",
            "exit_rows": [_MASK_EXIT_START, _MASK_EXIT_END],
            "reentry_row": _MASK_REENTRY,
            "exit_reason": "FORMULA_INELIGIBLE",
            "oracle_reentry": reentry_oracle,
        },
        "fincore_evaluation": fincore_evaluation,
        "oracle_context": {
            "grid_rows": len(oracle_context["grid"]),
            "asset_count": len(oracle_context["assets"]),
            "formula_count": len(expected),
            "lookback_h": {
                str(alpha_id): histories[alpha_id] for alpha_id in reference.formula_ids()
            },
        },
    }
    record_path = tmp_path / "alpha101-native-installed-acceptance.json"
    record_path.write_text(
        json.dumps(acceptance_record, indent=2, sort_keys=True), encoding="utf-8"
    )
    assert record_path.is_file()
