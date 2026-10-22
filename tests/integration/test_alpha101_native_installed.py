"""Installed-wheel acceptance for the complete native Alpha101 registry.

This acceptance test is intentionally opt-in.  It must run from an external,
clean test tree against the committed Backtrader and fincore wheels; running it
from the source checkout could silently test the checkout instead.

External test-tree contents (relative to the tree root):

* ``tests/integration/test_alpha101_native_installed.py`` (this file)
* ``tests/test_utils/alpha101_full_reference.py``
* ``tests/test_utils/alpha101_native_harness.py``
* ``tests/test_utils/alpha101_trace_validation.py``
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
_INSTALLED_ROOTS_ENV = "BT_FACTOR_RESEARCH_INSTALLED_ROOTS"
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
    roots = [prefix]
    configured = os.environ.get(_INSTALLED_ROOTS_ENV)
    if configured:
        roots.extend(Path(value).expanduser().resolve() for value in json.loads(configured))
    for root in roots:
        if origin.is_relative_to(root):
            if root == prefix:
                relative = origin.relative_to(prefix)
                assert any(
                    part.lower() in ("site-packages", "dist-packages") for part in relative.parts
                ), "%s did not load from site-packages: %s" % (name, origin)
            return str(origin)
    raise AssertionError("%s did not load underneath an approved install root: %s" % (name, origin))


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
        "backtrader": importlib.metadata.version("back-trader-python"),
        "fincore": importlib.metadata.version("fincore"),
    }
    assert backtrader.__version__ == versions["backtrader"]
    assert fincore.__version__ == versions["fincore"]
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
    trace = importlib.import_module("tests.test_utils.alpha101_trace_validation")
    fixture = importlib.import_module("tests.unit.test_factor_research_representatives")
    return {"reference": reference, "harness": harness, "trace": trace, "fixture": fixture}


def _sha256_sources(external_root: Path) -> Mapping[str, str]:
    inputs = {
        "installed_test": external_root / "tests" / "integration" / Path(__file__).name,
        "full_reference": external_root / "tests" / "test_utils" / "alpha101_full_reference.py",
        "native_harness": external_root / "tests" / "test_utils" / "alpha101_native_harness.py",
        "trace_validator": external_root / "tests" / "test_utils" / "alpha101_trace_validation.py",
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
    factor_matrices: Mapping[int, Sequence[Sequence[float]]],
    frames: Mapping[str, Any],
    grid: Sequence[Any],
    assets: Sequence[str],
) -> Mapping[str, int]:
    import pandas as pd

    window = tuple(range(_EVALUATION_START, _EVALUATION_END + 1))
    label_rows = result.labels
    assert set(label_rows["period"]) == {"1D"}
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

    ic = result.ic
    expected_ic_keys = {
        (signal, timestamp)
        for signal, timestamp, _metric in expected
        if expected[(signal, timestamp, "pearson")][0] != "INSUFFICIENT_ASSETS"
    }
    actual_ic_keys = [(row.factor, pd.Timestamp(row.time)) for row in ic.itertuples()]
    assert len(actual_ic_keys) == len(set(actual_ic_keys))
    assert set(actual_ic_keys) == expected_ic_keys
    assert {factor for factor, _ in actual_ic_keys} == {
        "alpha%d" % evaluation_id for evaluation_id in _EVALUATION_IDS
    }
    finite_count = degenerate_count = 0
    for row in ic.itertuples():
        timestamp = pd.Timestamp(row.time)
        reason, _ = expected[(row.factor, timestamp, "pearson")]
        if reason is not None:
            assert reason in ("CONSTANT_FACTOR", "CONSTANT_RETURN")
            assert pd.isna(row.ic) and pd.isna(row.rank_ic)
            degenerate_count += 1
            continue
        alpha_id = int(row.factor.removeprefix("alpha"))
        expected_asset_count = sum(
            math.isfinite(factor_matrices[alpha_id][grid.index(timestamp)][column])
            for column in range(len(assets))
        )
        assert row.n_assets == expected_asset_count
        for metric, actual in (("pearson", row.ic), ("spearman", row.rank_ic)):
            _, wanted = expected[(row.factor, timestamp, metric)]
            assert math.isfinite(float(actual))
            assert wanted is not None
            assert abs(float(actual) - wanted) <= 1e-12 + 1e-10 * abs(wanted)
        finite_count += 1
    assert finite_count > 0 and degenerate_count > 0
    return {
        "label_rows": len(label_rows),
        "finite_ic_rows": finite_count,
        "degenerate_ic_rows": degenerate_count,
    }


def _evaluation_window_panel(
    collected: Any,
) -> Any:
    """Select evaluation factors while retaining the full price-label tail."""
    from backtrader.research import FactorPanel

    grid = collected.grid
    start = grid.index[_EVALUATION_START]
    end = grid.index[_EVALUATION_END]
    evaluation_times = grid.index[(grid.index >= start) & (grid.index <= end)]
    factor_names = tuple("alpha%d" % alpha_id for alpha_id in _EVALUATION_IDS)
    times = collected.factors.index.get_level_values("time")
    factors = collected.factors.loc[times.isin(evaluation_times), list(factor_names)]
    universe = collected.universe.loc[evaluation_times]
    return FactorPanel(
        factors=factors,
        grid=collected.grid,
        prices_open=collected.prices_open,
        prices_close=collected.prices_close,
        universe=universe,
        groups=collected.groups,
        start=start,
        end=end,
        target_order=collected.target_order,
        factor_order=factor_names,
        directions={name: collected.directions[name] for name in factor_names},
    )


def _evaluation_spec(panel: Any) -> Any:
    from fincore.factor_analysis.research import ResearchEvaluationSpec

    return ResearchEvaluationSpec(
        targets=panel.target_order,
        start=panel.start,
        end=panel.end,
        snapshot_id="iteration46-alpha101-installed-v1",
        price_basis="synthetic unadjusted independent OHLC and VWAP units",
        calendar_id="synthetic-daily-v1",
        frequency="1session",
        source_timezone="UTC",
        feed_time_kind="close_time",
        periods=(1,),
        label="next_open_to_open",
        min_assets=2,
        quantiles=1,
        min_quantile_assets=1,
        preprocess="none",
        stability_lags=(1,),
        max_loss=1.0,
    )


@pytest.mark.parametrize(
    ("batch_name", "alpha_ids"),
    _BATCHES,
    ids=["promoted_20"] + ["batch_%s" % name for name, _ in _BATCHES[1:]],
)
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_installed_alpha101_batch_and_promoted_fincore_acceptance(
    tmp_path, batch_name, alpha_ids, runonce
):
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
    trace_validator = helpers["trace"]
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
    groups = dict.fromkeys(assets, "market")
    oracle_matrices = harness.oracle_frames(frames, grid=grid)
    histories = {
        alpha_id: reference.history_h(alpha_id, oracle_matrices)
        for alpha_id in reference.formula_ids()
    }

    strategy = harness.run_native_batch(
        frames,
        alpha_ids,
        runonce=runonce,
        groups=groups,
    )
    trace_results = {}
    production_matrices = {}
    expected_ic = None
    for alpha_id in alpha_ids:
        factor_class = alpha101.get_alpha(alpha_id)
        label = "%s Alpha%d installed %s" % (
            batch_name,
            alpha_id,
            "runonce" if runonce else "runnext",
        )
        assert factor_class.lookback_h == histories[alpha_id], label
        trace = trace_validator.validate_factor_trace(
            strategy.factor_instances["alpha%d" % alpha_id],
            alpha_id,
            frames,
            assets,
            grid,
            strategy=strategy,
        )
        assert not trace["failures"], "%s trace failed:\n%s" % (
            label,
            "\n".join(trace["failures"]),
        )
        assert trace["finite_witness"], label
        assert trace["matched_nodes"] > 0, label
        harness.assert_finite_witness(alpha_id, trace["expected"], histories[alpha_id])
        trace_results[alpha_id] = trace
        if alpha_id in _EVALUATION_IDS:
            # The independent formula trace validates this collector output
            # before it becomes the IC oracle input. This keeps exact
            # production ties for rank-based IC while labels remain
            # independently computed from fixture prices.
            production_matrices[alpha_id] = trace["panel_actual"]
    harness.assert_lifecycle(strategy, alpha_ids, grid)
    if batch_name == "promoted_20":
        assert set(production_matrices) == set(_EVALUATION_IDS)
        expected_ic = _ic_expectations(production_matrices, frames, grid, assets)
    batch_report = {
        batch_name: {
            "alpha_ids": list(alpha_ids),
            "formula_count": len(alpha_ids),
            "engine_mode": "runonce" if runonce else "runnext",
            "trace_nodes": {
                str(alpha_id): trace_results[alpha_id]["matched_nodes"] for alpha_id in alpha_ids
            },
            "lookback_h": {str(alpha_id): histories[alpha_id] for alpha_id in alpha_ids},
            "finite_cells": {
                str(alpha_id): sum(
                    math.isfinite(float(value))
                    for row in trace_results[alpha_id]["actual"]
                    for value in row
                )
                for alpha_id in alpha_ids
            },
            "broker_calls": strategy._alpha101_broker_call_counts,
        }
    }

    fincore_evaluation: Mapping[str, Any]
    if batch_name == "promoted_20":
        assert expected_ic is not None
        # Keep the 320-row native collector evidence above. The evaluator
        # panel declares only its 260..285 factor interval, while retaining
        # the complete grid and price frames for the forward-label tail.
        collected = strategy.get_panel()
        panel = _evaluation_window_panel(collected)
        evaluation_grid = tuple(grid[_EVALUATION_START : _EVALUATION_END + 1])
        assert tuple(panel.grid.index) == tuple(grid)
        assert panel.start == grid[_EVALUATION_START]
        assert panel.end == grid[_EVALUATION_END]
        assert len(panel.factors) == len(evaluation_grid) * len(assets)
        assert panel.factor_order == ("alpha3", "alpha9", "alpha101")
        label_tail_end = grid[_EVALUATION_END + 2]
        assert panel.prices_open.index[-1] >= label_tail_end
        assert panel.prices_close.index[-1] >= label_tail_end

        snapshot_path = tmp_path / "alpha101-native-panel"
        panel.to_csv(snapshot_path)
        from backtrader.research import FactorPanel, evaluate_frames

        restored_panel = FactorPanel.from_csv(
            snapshot_path,
            start=panel.start,
            end=panel.end,
            directions=panel.directions,
            target_order=panel.target_order,
            factor_order=panel.factor_order,
            groups=panel.groups,
        )
        assert tuple(restored_panel.grid.index) == tuple(grid)
        assert restored_panel.start == grid[_EVALUATION_START]
        assert restored_panel.end == grid[_EVALUATION_END]
        assert restored_panel.factor_order == ("alpha3", "alpha9", "alpha101")
        assert panel.factors.equals(restored_panel.factors)
        assert panel.grid.equals(restored_panel.grid)
        assert panel.prices_open.equals(restored_panel.prices_open)
        assert panel.prices_close.equals(restored_panel.prices_close)
        assert panel.universe.equals(restored_panel.universe)
        assert len(restored_panel.factors) == len(evaluation_grid) * len(assets)

        borrowed = {
            name: getattr(restored_panel, name)
            for name in ("factors", "grid", "prices_open", "prices_close", "universe")
        }
        borrowed_before = {name: frame.copy(deep=True) for name, frame in borrowed.items()}
        result = evaluate_frames(restored_panel, _evaluation_spec(restored_panel))
        for name, frame in borrowed.items():
            import pandas as pd

            pd.testing.assert_frame_equal(frame, borrowed_before[name])
        assert production_matrices is not None
        fincore_report = _assert_ic_and_labels(
            result, expected_ic, production_matrices, frames, grid, assets
        )
        assert set(result.labels["asset"]) == set(assets)
        assert set(result.ic["factor"]) == {
            "alpha%d" % evaluation_id for evaluation_id in _EVALUATION_IDS
        }
        fincore_evaluation = {
            "status": "run_by_promoted_20_case",
            "formula_ids": list(_EVALUATION_IDS),
            "evaluation_rows": [_EVALUATION_START, _EVALUATION_END],
            "constant_return_row": _CONSTANT_RETURN_OFFSET,
            "factor_panel_csv_files": sorted(path.name for path in snapshot_path.iterdir()),
            "result_fingerprint": result.manifest["result_fingerprint"],
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
            "INSTALLED_WHEEL_ALPHA101_BATCH_%s_TRACE_%s%s"
            % (
                batch_name.upper(),
                "RUNONCE" if runonce else "RUNNEXT",
                "_AND_FINCORE_SUBSET" if batch_name == "promoted_20" else "",
            )
        ),
        "selected_batch": batch_name,
        "selected_batch_alpha_ids": list(alpha_ids),
        "selected_engine_mode": "runonce" if runonce else "runnext",
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
        "membership": {
            "semantics": "real-bar presence on the declared grid",
            "input_rows": len(grid),
            "target_count": len(assets),
        },
        "trace_validation": {
            "formula_count": len(trace_results),
            "matched_native_nodes": sum(trace["matched_nodes"] for trace in trace_results.values()),
            "finite_witnesses": sum(
                int(trace["finite_witness"]) for trace in trace_results.values()
            ),
        },
        "fincore_evaluation": fincore_evaluation,
        "oracle_context": {
            "grid_rows": len(grid),
            "asset_count": len(assets),
            "formula_count": len(trace_results),
            "lookback_h": {str(alpha_id): histories[alpha_id] for alpha_id in alpha_ids},
        },
    }
    record_path = tmp_path / "alpha101-native-installed-acceptance.json"
    record_path.write_text(
        json.dumps(acceptance_record, indent=2, sort_keys=True), encoding="utf-8"
    )
    assert record_path.is_file()
