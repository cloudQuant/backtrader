"""Opt-in native/build parity through the pinned public fincore APIs.

Set ``BT_ALPHA101_BUILD_PAIR=1`` to enable the pair check.  The default
selection is the full 1..101 registry; ``BT_ALPHA101_NATIVE_IDS`` is the only
supported development selector and is never intersected with an available
subset.  Formal evidence output requires all 101 IDs.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import pytest

from tests.test_utils.alpha101_full_reference import formula_ids, history_h
from tests.test_utils.alpha101_native_harness import (
    alpha_name,
    assert_finite_witness,
    assert_lifecycle,
    make_positive_fixture,
    run_native_batch,
)
from tests.test_utils.alpha101_trace_validation import validate_factor_trace

_OPT_IN_ENV = "BT_ALPHA101_BUILD_PAIR"
_IDS_ENV = "BT_ALPHA101_NATIVE_IDS"
_EVIDENCE_ENV = "BT_ALPHA101_BUILD_PAIR_EVIDENCE"
_EXPECTED_FINCORE_COMMIT = "4b8f31b1b59707480d5db9603704d83bbf7e6946"
_BATCH_SIZE = 20
_PERIODS = (1, 5)
_COLLECTION_PERIODS = 326
_EVALUATION_START = 0
_EVALUATION_END = 319
_FORWARD_TAIL_BARS = 6
_TABLES = (
    "signals",
    "labels",
    "ic",
    "ic_summary",
    "quantile_returns",
    "turnover",
    "spreads",
    "stability",
    "correlation",
    "comparisons",
    "coverage",
    "diagnostics",
)

pytestmark = [
    pytest.mark.slow,
]


def _selected_ids() -> tuple[int, ...]:
    if os.environ.get("BT_ALPHA101_NATIVE_BATCHES"):
        raise AssertionError(
            "the build/fincore pair accepts only BT_ALPHA101_NATIVE_IDS; "
            "a batch selector would silently narrow the requested scope"
        )
    raw = os.environ.get(_IDS_ENV, "")
    if not raw.strip():
        return tuple(range(1, 102))

    tokens = [token.strip() for token in raw.split(",")]
    if any(not token for token in tokens):
        raise AssertionError("BT_ALPHA101_NATIVE_IDS contains an empty ID")
    ids = []
    for token in tokens:
        try:
            alpha_id = int(token)
        except ValueError as exc:
            raise AssertionError("BT_ALPHA101_NATIVE_IDS must contain integers") from exc
        if str(alpha_id) != token:
            raise AssertionError("BT_ALPHA101_NATIVE_IDS must use canonical integer IDs")
        ids.append(alpha_id)
    if len(ids) != len(set(ids)):
        raise AssertionError("BT_ALPHA101_NATIVE_IDS must not repeat an ID")
    unknown = set(ids) - set(formula_ids())
    if unknown:
        raise AssertionError("BT_ALPHA101_NATIVE_IDS contains unknown IDs: %s" % sorted(unknown))
    selected = tuple(sorted(ids))
    assert selected
    return selected


def _batches(ids: Sequence[int]) -> tuple[tuple[int, ...], ...]:
    return tuple(
        tuple(ids[start : start + _BATCH_SIZE]) for start in range(0, len(ids), _BATCH_SIZE)
    )


def _balanced_positive_fixture(
    source_frames: Mapping[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Give local Alpha101 inputs three balanced pairs of feed classifications."""

    balanced = {}
    for asset_index, (asset, source) in enumerate(source_frames.items()):
        frame = source.copy(deep=True)
        frame["sector"] = 0
        frame["industry"] = 0
        frame["subindustry"] = asset_index // 2
        balanced[asset] = frame
    return balanced


def _quantile_edge_profile(
    signal_values: Sequence[float],
    label_values: Sequence[float],
    quantiles: int,
) -> dict[str, Any]:
    """Independently inspect linear qcut edges after finite signal/label intersection."""

    signals = np.asarray(signal_values, dtype="float64")
    labels = np.asarray(label_values, dtype="float64")
    if signals.shape != labels.shape:
        raise AssertionError("signal and label arrays must have identical shapes")
    finite = np.isfinite(signals) & np.isfinite(labels)
    values = signals[finite]
    if values.size == 0:
        return {
            "finite_intersection": int(values.size),
            "cardinality": int(np.unique(values).size),
            "edges": [],
            "duplicate_edge_positions": [],
        }
    edges = np.quantile(
        values,
        np.linspace(0.0, 1.0, quantiles + 1),
        method="linear",
    )
    duplicates = [
        edge_index
        for edge_index in range(1, len(edges))
        if edges[edge_index] == edges[edge_index - 1]
    ]
    return {
        "finite_intersection": int(values.size),
        "cardinality": int(np.unique(values).size),
        "edges": [float(edge) for edge in edges],
        "duplicate_edge_positions": duplicates,
    }


def _require_duplicate_edges(
    profiles: Sequence[Mapping[str, Any]],
    *,
    factor: str,
    period: str,
) -> list[Mapping[str, Any]]:
    # Quantization precedes fincore's min_assets IC filter, so even one finite
    # signal/label pair is an applicable date whose qcut edges must be checked.
    applicable = [profile for profile in profiles if profile["finite_intersection"] > 0]
    if not applicable:
        raise AssertionError(
            "%s %s has no date with a finite signal/label intersection" % (factor, period)
        )
    unique_edge_dates = [
        profile for profile in applicable if not profile["duplicate_edge_positions"]
    ]
    if unique_edge_dates:
        dates = [str(profile["time"]) for profile in unique_edge_dates]
        raise AssertionError(
            "%s %s is empty despite unique linear quantile edges on dates %s"
            % (factor, period, dates[:10])
        )
    return applicable


def _date_quantile_profiles(
    result: Any,
    factor: str,
    period: str,
    *,
    combination_weights: Mapping[str, float],
    quantiles: int,
) -> list[dict[str, Any]]:
    signals = result.signals
    if factor == "fixed_weight_combo":
        weights = {name: weight for name, weight in combination_weights.items() if weight != 0.0}
        members = signals.loc[
            signals["factor"].isin(weights),
            ["time", "asset", "factor", "processed_value", "group"],
        ]
        values = members.pivot(index=["time", "asset"], columns="factor", values="processed_value")
        missing_members = set(weights) - set(values.columns)
        if missing_members:
            raise AssertionError("combination signals omit members %s" % sorted(missing_members))
        combined = sum(float(weight) * values[name] for name, weight in weights.items())
        first_member = next(iter(weights))
        selected = signals.loc[
            signals["factor"] == first_member,
            ["time", "asset", "group"],
        ].copy(deep=True)
        combined_values = combined.rename("processed_value").reset_index()
        selected = selected.merge(
            combined_values,
            on=["time", "asset"],
            how="left",
            validate="one_to_one",
        )
    else:
        selected = signals.loc[
            signals["factor"] == factor,
            ["time", "asset", "group", "processed_value"],
        ].copy(deep=True)
    labels = result.labels.loc[
        result.labels["period"] == period,
        ["time", "asset", "value"],
    ].rename(columns={"value": "label_value"})
    joined = selected.merge(
        labels,
        on=["time", "asset"],
        how="left",
        validate="one_to_one",
    )
    profiles = []
    for time, rows in joined.groupby("time", observed=False, sort=True):
        profile = _quantile_edge_profile(
            rows["processed_value"].to_numpy(dtype="float64"),
            rows["label_value"].to_numpy(dtype="float64"),
            quantiles,
        )
        profile["time"] = pd.Timestamp(time).isoformat()
        profiles.append(profile)
    return profiles


def _uncomputable_edge_evidence(
    result: Any,
    *,
    combination_weights: Mapping[str, float],
    periods: Sequence[int],
    quantiles: int,
) -> list[dict[str, Any]]:
    empty_diagnostics = result.diagnostics.loc[result.diagnostics["code"] == "no_evaluable_cells"]
    evidence = []
    found: set[tuple[str, str]] = set()
    for diagnostic in empty_diagnostics.to_dict("records"):
        factor = str(diagnostic["factor"])
        message = str(diagnostic["message"])
        if not message.startswith("period ") or ", factor " not in message:
            raise AssertionError(
                "no_evaluable_cells diagnostic has no recognizable horizon: %s" % message
            )
        period = message.split("period ", 1)[1].split(", factor ", 1)[0]
        if period not in {"%dD" % value for value in periods}:
            raise AssertionError(
                "no_evaluable_cells diagnostic names an unexpected period: %s" % period
            )
        key = (factor, period)
        if key in found:
            raise AssertionError("duplicate no_evaluable_cells diagnostics for %s %s" % key)
        found.add(key)
        profiles = _date_quantile_profiles(
            result,
            factor,
            period,
            combination_weights=combination_weights if factor == "fixed_weight_combo" else {},
            quantiles=quantiles,
        )
        applicable = _require_duplicate_edges(profiles, factor=factor, period=period)
        for table_name in ("ic", "quantile_returns", "spreads"):
            table = getattr(result, table_name)
            rows = table.loc[(table["factor"] == factor) & (table["period"] == period)]
            if not rows.empty:
                raise AssertionError(
                    "%s %s has no_evaluable_cells but %s contains rows"
                    % (factor, period, table_name)
                )
        evidence.append(
            {
                "factor": factor,
                "period": period,
                "diagnostic_code": "no_evaluable_cells",
                "diagnostic_message": message,
                "reason": "linear quantile edges duplicate after finite signal/label intersection",
                "date_count": len(profiles),
                "applicable_date_count": len(applicable),
                "finite_intersection_total": int(
                    sum(profile["finite_intersection"] for profile in profiles)
                ),
                "cardinality_by_date": [
                    {
                        "time": profile["time"],
                        "finite_intersection": profile["finite_intersection"],
                        "cardinality": profile["cardinality"],
                    }
                    for profile in profiles
                ],
                "duplicate_edge_date_count": len(applicable),
                "duplicate_edge_count": int(
                    sum(len(profile["duplicate_edge_positions"]) for profile in applicable)
                ),
                "profiles": profiles,
                "zero_rows": {"ic": True, "quantile_returns": True, "spreads": True},
            }
        )

    unevaluable = result.coverage.loc[result.coverage["status"] == "UNEVALUABLE"]
    expected_periods = {"%dD" % value for value in periods}
    for factor in unevaluable["factor"].astype(str):
        missing = expected_periods - {period for name, period in found if name == factor}
        if missing:
            raise AssertionError(
                "UNEVALUABLE factor/combination %s lacks matching no_evaluable_cells diagnostics for %s"
                % (factor, sorted(missing))
            )
    return evidence


def test_quantile_degeneracy_verifier_uses_finite_label_intersection():
    signal_values = np.asarray([0, 0, 1, 1, 2, 2], dtype="float64")
    all_labels = np.ones(6, dtype="float64")
    unfiltered = _quantile_edge_profile(signal_values, all_labels, quantiles=3)
    assert unfiltered["duplicate_edge_positions"] == []
    with pytest.raises(AssertionError, match="unique linear quantile edges"):
        _require_duplicate_edges([{"time": "t0", **unfiltered}], factor="alphaX", period="1D")

    labels_without_last_pair = np.asarray([1, 1, 1, 1, np.nan, np.nan], dtype="float64")
    intersected = _quantile_edge_profile(signal_values, labels_without_last_pair, quantiles=3)
    assert intersected["finite_intersection"] == 4
    assert intersected["duplicate_edge_positions"]
    assert _require_duplicate_edges([{"time": "t0", **intersected}], factor="alphaX", period="1D")

    singleton = _quantile_edge_profile([1.0], [0.01], quantiles=3)
    assert singleton["finite_intersection"] == 1
    assert singleton["duplicate_edge_positions"] == [1, 2, 3]
    assert _require_duplicate_edges([{"time": "t1", **singleton}], factor="alphaX", period="1D")

    empty = _quantile_edge_profile([np.nan], [0.01], quantiles=3)
    assert empty["finite_intersection"] == 0
    assert empty["duplicate_edge_positions"] == []
    with pytest.raises(AssertionError, match="no date with a finite signal/label intersection"):
        _require_duplicate_edges([{"time": "t2", **empty}], factor="alphaX", period="1D")


def _fincore_identity() -> dict[str, str]:
    import fincore

    repository_root = Path(__file__).resolve().parents[2]
    expected_root = repository_root.parent / "fincore"
    origin = Path(fincore.__file__).resolve()
    package_root = expected_root / "fincore"
    if not origin.is_relative_to(package_root):
        raise AssertionError("fincore did not load from the pinned sibling checkout: %s" % origin)
    commit = subprocess.run(
        ["git", "-C", str(expected_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if commit != _EXPECTED_FINCORE_COMMIT:
        raise AssertionError(
            "fincore checkout must be %s, got %s" % (_EXPECTED_FINCORE_COMMIT, commit)
        )
    try:
        distribution_version = importlib.metadata.version("fincore")
    except importlib.metadata.PackageNotFoundError:
        distribution_version = "unavailable"
    return {
        "origin": str(origin),
        "version": str(fincore.__version__),
        "distribution_version": distribution_version,
        "commit": commit,
    }


def _new_report_capture_helper() -> Any:
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts" / "verify_factor_research_pair_semantics.py"
    spec = importlib.util.spec_from_file_location("alpha101_build_pair_semantics", path)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load the existing report semantics helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not callable(getattr(module, "capture_report_semantics", None)):
        raise AssertionError("the report semantics helper has no capture_report_semantics API")
    return module


def _collect_pair(
    frames: Mapping[str, pd.DataFrame],
    ids: Sequence[int],
    *,
    build: bool,
) -> tuple[pd.DataFrame, dict[int, Any], dict[int, dict[str, Any]]]:
    import backtrader.research.alpha101 as alpha101

    grid = tuple(next(iter(frames.values())).index)
    assets = tuple(frames)
    expected_index = pd.MultiIndex.from_product([grid, assets], names=("time", "asset"))
    columns = []
    strategies = {}
    traces = {}
    for batch in _batches(ids):
        mode = "build" if build else "native"
        classes = {alpha_id: alpha101.get_alpha(alpha_id) for alpha_id in batch}
        strategy = run_native_batch(
            frames,
            batch,
            runonce=False,
            factor_mode=mode,
            alpha_classes=classes,
        )
        assert_lifecycle(strategy, batch, grid, alpha_classes=classes)
        panel = strategy.get_panel()
        if not panel.factors.index.equals(expected_index):
            raise AssertionError(
                "%s batch %s did not preserve the complete ordered time/asset product"
                % ("build" if build else "native", batch)
            )
        if tuple(panel.factor_order) != tuple(alpha_name(alpha_id) for alpha_id in batch):
            raise AssertionError("factor panel order differs from the explicit ID selection")
        for alpha_id in batch:
            name = alpha_name(alpha_id)
            factor = strategy.factor_instances[name]
            trace = validate_factor_trace(
                factor,
                alpha_id,
                frames,
                assets,
                grid,
                strategy=strategy,
            )
            if trace["failures"]:
                raise AssertionError(
                    "%s Alpha%d trace failed:\n%s"
                    % (
                        "build" if build else "native",
                        alpha_id,
                        "\n".join(trace["failures"][:20]),
                    )
                )
            assert_finite_witness(alpha_id, trace["expected"], history_h(alpha_id))
            if not trace.get("finite_witness") or trace.get("matched_nodes", 0) <= 0:
                raise AssertionError("Alpha%d has no independent finite trace witness" % alpha_id)
            values = panel.factors[name]
            if not np.isfinite(values.to_numpy(dtype="float64")).any():
                raise AssertionError("Alpha%d panel has no finite factor value" % alpha_id)
            columns.append(values.rename(name).copy(deep=True))
            strategies[alpha_id] = strategy
            traces[alpha_id] = trace

    factors = pd.concat(columns, axis=1)
    expected_names = tuple(alpha_name(alpha_id) for alpha_id in ids)
    if tuple(factors.columns) != expected_names:
        raise AssertionError("assembled factor columns differ from the explicit ID order")
    return factors, strategies, traces


def _evaluation_panel(
    factors: pd.DataFrame,
    source_panel: Any,
    ids: Sequence[int],
    grid: Sequence[Any],
) -> Any:
    from backtrader.research import FactorPanel

    evaluation_times = pd.DatetimeIndex(grid[_EVALUATION_START : _EVALUATION_END + 1])
    factor_times = factors.index.get_level_values("time")
    selected = factors.loc[factor_times.isin(evaluation_times)].copy(deep=True)
    expected_index = pd.MultiIndex.from_product(
        [evaluation_times, source_panel.target_order], names=("time", "asset")
    )
    if not selected.index.equals(expected_index):
        raise AssertionError("evaluation panel does not retain the ordered time/asset product")
    for alpha_id in ids:
        name = alpha_name(alpha_id)
        if not np.isfinite(selected[name].to_numpy(dtype="float64")).any():
            raise AssertionError(
                "Alpha%d has no finite witness inside evaluation offsets %d..%d"
                % (alpha_id, _EVALUATION_START, _EVALUATION_END)
            )
    directions = {
        alpha_name(alpha_id): (1 if index % 2 == 0 else -1) for index, alpha_id in enumerate(ids)
    }
    return FactorPanel(
        factors=selected,
        grid=source_panel.grid,
        prices_open=source_panel.prices_open,
        prices_close=source_panel.prices_close,
        universe=source_panel.universe.loc[evaluation_times],
        groups=source_panel.groups,
        start=evaluation_times[0],
        end=evaluation_times[-1],
        target_order=source_panel.target_order,
        factor_order=tuple(alpha_name(alpha_id) for alpha_id in ids),
        directions=directions,
    )


def _combination_weights(ids: Sequence[int]) -> dict[str, float]:
    if len(ids) == 1:
        return {alpha_name(ids[0]): 1.0}
    return {alpha_name(ids[0]): 0.4, alpha_name(ids[1]): 0.6}


def _evaluation_spec(panel: Any, ids: Sequence[int]) -> Any:
    from fincore.factor_analysis.research import ResearchEvaluationSpec

    return ResearchEvaluationSpec(
        targets=panel.target_order,
        start=panel.start,
        end=panel.end,
        snapshot_id="iteration49-alpha101-single-class-mode-pair-v1",
        price_basis="synthetic-unadjusted-USD",
        calendar_id="synthetic-daily-v1",
        frequency="1session",
        source_timezone="UTC",
        feed_time_kind="close_time",
        periods=_PERIODS,
        label="next_open_to_open",
        min_assets=2,
        quantiles=3,
        min_quantile_assets=1,
        preprocess="cross_section_rank",
        stability_lags=(1,),
        max_loss=1.0,
        combinations={"fixed_weight_combo": _combination_weights(ids)},
    )


def _snapshot_panel(panel: Any) -> dict[str, Any]:
    fields = ("factors", "grid", "prices_open", "prices_close", "universe")
    return {
        "frames": {name: getattr(panel, name).copy(deep=True) for name in fields},
        "attrs": {name: dict(getattr(panel, name).attrs) for name in fields},
        "groups": dict(panel.groups),
        "directions": dict(panel.directions),
    }


def _assert_panel_unchanged(panel: Any, snapshot: Mapping[str, Any]) -> None:
    for name, before in snapshot["frames"].items():
        current = getattr(panel, name)
        pd.testing.assert_frame_equal(current, before, check_exact=True, check_like=False)
        if dict(current.attrs) != snapshot["attrs"][name]:
            raise AssertionError("evaluation changed borrowed panel %s attrs" % name)
    if dict(panel.groups) != snapshot["groups"]:
        raise AssertionError("evaluation changed borrowed panel groups")
    if dict(panel.directions) != snapshot["directions"]:
        raise AssertionError("evaluation changed borrowed panel directions")


def _compare_results(
    native: Any,
    build: Any,
    *,
    expected_directions: Mapping[str, int],
    combination_weights: Mapping[str, float],
) -> dict[str, dict[str, Any]]:
    if native.status not in ("OK", "PARTIAL") or build.status != native.status:
        raise AssertionError("native/build fincore result status is not a valid equal evaluation")
    if dict(native.manifest) != dict(build.manifest):
        raise AssertionError("native/build fincore manifests differ")

    table_summary = {}
    for name in _TABLES:
        left = getattr(native, name)
        right = getattr(build, name)
        pd.testing.assert_frame_equal(
            left,
            right,
            check_dtype=True,
            check_exact=True,
            check_like=False,
            check_names=True,
            check_categorical=True,
        )
        manifest_table = native.manifest["tables"][name]
        if manifest_table["rows"] != len(left):
            raise AssertionError("fincore manifest row count differs for %s" % name)
        if manifest_table["columns"] != [str(column) for column in left.columns]:
            raise AssertionError("fincore manifest columns differ for %s" % name)
        if left.empty:
            raise AssertionError("%s has no functional rows in the fixed evaluation" % name)
        table_summary[name] = {"status": "PRESENT", "rows": int(len(left))}

    if not native.labels["period"].isin(("1D", "5D")).all():
        raise AssertionError("label table does not contain the configured 1D/5D horizons")
    degeneracy_evidence = _uncomputable_edge_evidence(
        native,
        combination_weights=combination_weights,
        periods=_PERIODS,
        quantiles=3,
    )
    if "alpha48" in expected_directions:
        for period in ("1D", "5D"):
            for table_name in ("ic", "quantile_returns", "spreads"):
                table = getattr(native, table_name)
                rows = table.loc[(table["factor"] == "alpha48") & (table["period"] == period)]
                if rows.empty:
                    raise AssertionError(
                        "balanced Alpha48 must have %s metric rows for %s" % (table_name, period)
                    )
    if set(native.signals["direction"].unique()) != set(expected_directions.values()):
        raise AssertionError("signals did not witness the configured positive/negative directions")
    for name, direction in expected_directions.items():
        observed = set(native.signals.loc[native.signals["factor"] == name, "direction"])
        if observed != {direction}:
            raise AssertionError("signals direction differs for %s" % name)
    manifest_weights = native.manifest["spec"]["combinations"].get("fixed_weight_combo")
    if manifest_weights != dict(combination_weights) or not any(
        weight != 0.0 for weight in manifest_weights.values()
    ):
        raise AssertionError("the manifest does not record the configured non-zero weights")
    for name in combination_weights:
        member_signals = native.signals.loc[native.signals["factor"] == name]
        if not np.isfinite(member_signals["value"].to_numpy(dtype="float64")).any():
            raise AssertionError("fixed-weight member %s has no finite signal witness" % name)
        if not np.isfinite(member_signals["processed_value"].to_numpy(dtype="float64")).any():
            raise AssertionError("fixed-weight member %s has no processed signal witness" % name)
    comparison_rows = native.comparisons.loc[native.comparisons["left"] == "fixed_weight_combo"]
    if set(comparison_rows["right"]) != set(combination_weights):
        raise AssertionError("comparison table does not cover every fixed-weight member")
    combo_coverage = native.coverage.loc[
        (native.coverage["factor"] == "fixed_weight_combo")
        & (native.coverage["kind"] == "combination")
    ]
    if (
        len(combo_coverage) != 1
        or int(combo_coverage.iloc[0]["finite_cells"]) <= 0
        or int(combo_coverage.iloc[0]["evaluable_cells"]) <= 0
    ):
        raise AssertionError("fixed-weight combination has no evaluable finite coverage")
    for table_name in ("ic", "quantile_returns", "spreads"):
        rows = getattr(native, table_name).loc[
            getattr(native, table_name)["factor"] == "fixed_weight_combo"
        ]
        if rows.empty:
            raise AssertionError("fixed-weight combination has no %s metric rows" % table_name)
    combo_diagnostics = native.diagnostics.loc[
        (native.diagnostics["factor"] == "fixed_weight_combo")
        & (native.diagnostics["code"] == "combination_built")
    ]
    if len(combo_diagnostics) != 1 or any(
        name not in str(combo_diagnostics.iloc[0]["message"]) for name in combination_weights
    ):
        raise AssertionError("diagnostics do not witness the configured combination members")
    table_summary["manifest"] = {
        "status": "STRICT_EQUAL",
        "evaluation_id": native.manifest["evaluation_id"],
        "result_fingerprint": native.manifest["result_fingerprint"],
    }
    table_summary["uncomputable_horizons"] = degeneracy_evidence
    return table_summary


def _export_table_hashes(result: Any, root: Path) -> dict[str, dict[str, Any]]:
    exported = result.export(root, charts=False)
    summary = {}
    for name in _TABLES:
        path = exported / (name + ".csv")
        summary[name] = {
            "status": "PRESENT" if len(getattr(result, name)) else "EMPTY",
            "rows": int(len(getattr(result, name))),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    return summary


def _capture_reports(
    panel: Any,
    ids: Sequence[int],
    root: Path,
    helper: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    from backtrader.research import write_factor_report

    root.mkdir(parents=True, exist_ok=True)
    render_errors = []
    with helper.capture_report_semantics(root) as captured:
        for alpha_id in ids:
            name = alpha_name(alpha_id)
            output = root / (name + ".html")
            try:
                report_path = write_factor_report(
                    panel,
                    name,
                    output,
                    periods=_PERIODS,
                    quantiles=3,
                    max_loss=1.0,
                    label="next_open_to_open",
                    language="zh",
                )
            except Exception as error:
                render_errors.append(
                    {
                        "factor": name,
                        "error_type": type(error).__name__,
                        "error": str(error),
                    }
                )
                continue
            if Path(report_path).resolve() != output.resolve() or not output.is_file():
                raise AssertionError("%s report did not render to its requested HTML path" % name)
    if len(captured) != len(ids) - len(render_errors):
        raise AssertionError("report capture count differs from successful Alpha101 HTML renders")
    return captured, render_errors


def _report_map(reports: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    mapped = {}
    for report in reports:
        path = Path(str(report["html_path"]))
        name = path.stem
        if name in mapped:
            raise AssertionError("report semantics contain a duplicate factor report")
        mapped[name] = report
    return mapped


@pytest.mark.skipif(
    os.environ.get(_OPT_IN_ENV) != "1",
    reason="set BT_ALPHA101_BUILD_PAIR=1 for the pinned native/build fincore pair",
)
def test_alpha101_native_build_match_fincore_and_reports(tmp_path):
    ids = _selected_ids()
    evidence_value = os.environ.get(_EVIDENCE_ENV)
    if evidence_value and ids != tuple(range(1, 102)):
        raise AssertionError(
            "formal evidence output requires the exact full Alpha101 ID set 1..101"
        )

    fincore_identity = _fincore_identity()
    prefix_frames = make_positive_fixture(periods=320)
    source_frames = make_positive_fixture(periods=_COLLECTION_PERIODS)
    if len(source_frames) != len(prefix_frames):
        raise AssertionError("fixture asset membership changed with the collection period")
    for asset, prefix in prefix_frames.items():
        extended_prefix = source_frames[asset].iloc[: len(prefix)]
        pd.testing.assert_frame_equal(
            extended_prefix,
            prefix,
            check_dtype=True,
            check_exact=True,
            check_like=False,
            check_categorical=True,
        )
    frames = _balanced_positive_fixture(source_frames)
    frames_before = {asset: frame.copy(deep=True) for asset, frame in frames.items()}
    grid = tuple(next(iter(frames.values())).index)
    if len(grid) != _COLLECTION_PERIODS:
        raise AssertionError("the Alpha101 pair did not collect the required 326 fixture bars")
    if (
        _EVALUATION_START != 0
        or _EVALUATION_END != 319
        or len(grid) - (_EVALUATION_END + 1) != _FORWARD_TAIL_BARS
        or _EVALUATION_END + max(_PERIODS) + 1 >= len(grid)
    ):
        raise AssertionError("the first-320 evaluation window lacks its six-bar label tail")

    native_factors, native_strategies, _ = _collect_pair(frames, ids, build=False)
    build_factors, build_strategies, _ = _collect_pair(frames, ids, build=True)
    pd.testing.assert_frame_equal(
        native_factors,
        build_factors,
        check_dtype=True,
        check_exact=True,
        check_like=False,
        check_names=True,
        check_categorical=True,
    )
    for asset, before in frames_before.items():
        pd.testing.assert_frame_equal(frames[asset], before, check_exact=True)

    from backtrader.research import evaluate_frames

    first_native_strategy = native_strategies[ids[0]]
    native_source_panel = first_native_strategy.get_panel()
    build_source_panel = build_strategies[ids[0]].get_panel()
    evaluation_panel_native = _evaluation_panel(native_factors, native_source_panel, ids, grid)
    evaluation_panel_build = _evaluation_panel(build_factors, build_source_panel, ids, grid)
    for field in ("grid", "prices_open", "prices_close", "universe"):
        pd.testing.assert_frame_equal(
            getattr(evaluation_panel_native, field),
            getattr(evaluation_panel_build, field),
            check_exact=True,
            check_like=False,
        )
    pd.testing.assert_frame_equal(
        evaluation_panel_native.factors,
        evaluation_panel_build.factors,
        check_exact=True,
        check_like=False,
    )
    if evaluation_panel_native.directions != evaluation_panel_build.directions:
        raise AssertionError("native/build report directions differ")
    if ids == tuple(range(1, 102)) and set(evaluation_panel_native.directions.values()) != {-1, 1}:
        raise AssertionError("the full registry evaluation must exercise both directions")
    if len(ids) >= 2 and set(evaluation_panel_native.directions.values()) != {-1, 1}:
        raise AssertionError("multi-factor selections must exercise both directions")

    spec = _evaluation_spec(evaluation_panel_native, ids)
    native_panel_snapshot = _snapshot_panel(evaluation_panel_native)
    build_panel_snapshot = _snapshot_panel(evaluation_panel_build)
    native_result = evaluate_frames(evaluation_panel_native, spec)
    build_result = evaluate_frames(evaluation_panel_build, spec)
    table_summary = _compare_results(
        native_result,
        build_result,
        expected_directions=evaluation_panel_native.directions,
        combination_weights=_combination_weights(ids),
    )

    evidence_root = (
        Path(evidence_value).expanduser().resolve()
        if evidence_value
        else (tmp_path / "alpha101-build-fincore")
    )
    if evidence_root.exists() and any(evidence_root.iterdir()):
        raise AssertionError("evidence directory must be empty before the pair run")
    evidence_root.mkdir(parents=True, exist_ok=True)
    native_hashes = _export_table_hashes(native_result, evidence_root / "native-evaluation")
    build_hashes = _export_table_hashes(build_result, evidence_root / "build-evaluation")
    for name in _TABLES:
        if native_hashes[name]["sha256"] != build_hashes[name]["sha256"]:
            raise AssertionError("exported %s table hashes differ" % name)
        table_summary[name]["sha256"] = native_hashes[name]["sha256"]

    report_helper = _new_report_capture_helper()
    native_reports, native_report_errors = _capture_reports(
        evaluation_panel_native, ids, evidence_root / "native-reports", report_helper
    )
    build_reports, build_report_errors = _capture_reports(
        evaluation_panel_build, ids, evidence_root / "build-reports", report_helper
    )
    _assert_panel_unchanged(evaluation_panel_native, native_panel_snapshot)
    _assert_panel_unchanged(evaluation_panel_build, build_panel_snapshot)
    for asset, before in frames_before.items():
        pd.testing.assert_frame_equal(frames[asset], before, check_exact=True)

    native_report_map = _report_map(native_reports)
    build_report_map = _report_map(build_reports)
    expected_names = {alpha_name(alpha_id) for alpha_id in ids}
    if set(native_report_map) != set(build_report_map):
        raise AssertionError("native/build report semantics cover different rendered factors")
    if not set(native_report_map).issubset(expected_names):
        raise AssertionError("report semantics include an unselected factor")
    report_summary = []
    for name in sorted(native_report_map, key=lambda value: int(value.removeprefix("alpha"))):
        alpha_id = int(name.removeprefix("alpha"))
        native_report = native_report_map[name]
        build_report = build_report_map[name]
        if (
            native_report["semantic_payload"] != build_report["semantic_payload"]
            or native_report["semantic_digest"] != build_report["semantic_digest"]
        ):
            raise AssertionError("%s native/build ReportDocument semantics differ" % name)
        report_summary.append(
            {
                "alpha_id": alpha_id,
                "status": "PASS",
                "strict_equal": True,
                "semantic_digest": native_report["semantic_digest"],
                "native_html_sha256": native_report["html_sha256"],
                "build_html_sha256": build_report["html_sha256"],
            }
        )
    if native_report_errors or build_report_errors:
        raise AssertionError(
            "actual write_factor_report HTML rendering failed; native=%s build=%s; "
            "strictly compared rendered reports=%s"
            % (
                native_report_errors,
                build_report_errors,
                [row["alpha_id"] for row in report_summary],
            )
        )
    if set(native_report_map) != expected_names:
        raise AssertionError("report semantics do not cover exactly the selected factors")
    broker_state = {}
    for kind, strategies in (("native", native_strategies), ("build", build_strategies)):
        calls = {"submit": 0, "cancel": 0}
        for strategy in strategies.values():
            calls = strategy._alpha101_broker_call_counts
            if calls != {"submit": 0, "cancel": 0}:
                raise AssertionError("%s FactorStrategy attempted broker calls" % kind)
            if strategy.broker.orders or strategy.broker.pending or strategy.broker.submitted:
                raise AssertionError("%s FactorStrategy left broker orders" % kind)
        broker_state[kind] = calls

    if evidence_value:
        evidence = {
            "schema_version": 2,
            "acceptance_profile": "iteration49-single-class-modes",
            "status": "PASS",
            "selected_alpha_ids": list(ids),
            "full_registry": ids == tuple(range(1, 102)),
            "fincore": fincore_identity,
            "evaluation": {
                "engine": "runnext",
                "fixture": "balanced-subindustry-pairs(T326)",
                "collection_periods": _COLLECTION_PERIODS,
                "evaluation_window_offsets_inclusive": [
                    _EVALUATION_START,
                    _EVALUATION_END,
                ],
                "evaluation_periods": _EVALUATION_END - _EVALUATION_START + 1,
                "forward_tail_bars": _FORWARD_TAIL_BARS,
                "collection_prefix_matches_T320": True,
                "forward_periods": list(_PERIODS),
                "label": "next_open_to_open",
                "combination": {"fixed_weight_combo": _combination_weights(ids)},
                "direction_by_factor": evaluation_panel_native.directions,
            },
            "tables": table_summary,
            "manifest": {
                "status": "STRICT_EQUAL",
                "evaluation_id": native_result.manifest["evaluation_id"],
                "result_fingerprint": native_result.manifest["result_fingerprint"],
            },
            "reports": {
                "status": "PASS",
                "strict_equal": True,
                "count": len(report_summary),
                "per_factor": report_summary,
                "scope": "actual HTML rendering and captured ReportDocument semantic payloads",
            },
            "broker": broker_state,
            "factor_mode_witnesses": {
                "native": {
                    str(alpha_id): native_strategies[alpha_id]._alpha101_factor_mode_witnesses[
                        str(alpha_id)
                    ]
                    for alpha_id in ids
                },
                "build": {
                    str(alpha_id): build_strategies[alpha_id]._alpha101_factor_mode_witnesses[
                        str(alpha_id)
                    ]
                    for alpha_id in ids
                },
            },
            "input_unchanged": True,
        }
        evidence_path = evidence_root / "alpha101-build-fincore.json"
        with evidence_path.open("x", encoding="utf-8") as stream:
            json.dump(evidence, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
