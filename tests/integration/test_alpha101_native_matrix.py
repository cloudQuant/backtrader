"""Strict long-history Alpha101 matrix against the independent paper AST."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

import pytest

from backtrader.research.alpha101 import get_alpha
from tests.test_utils.alpha101_full_reference import formula_ids, history_h
from tests.test_utils.alpha101_native_harness import (
    assert_finite_witness,
    assert_lifecycle,
    make_positive_fixture,
    selected_alpha_batches,
    run_native_batch,
)
from tests.test_utils.alpha101_trace_validation import compare_factor_graphs, validate_factor_trace

BATCH_SIZE = 20
HISTORY_LENGTHS = (320, 640, 1280)
BUILD_PAIR_ENV = "BT_ALPHA101_BUILD_PAIR"
BUILD_PAIR_EVIDENCE_ENV = "BT_ALPHA101_BUILD_PAIR_EVIDENCE"


def _batches():
    ids = list(formula_ids())
    return [ids[index : index + BATCH_SIZE] for index in range(0, len(ids), BATCH_SIZE)]


def _long_history_fixture(periods):
    """Keep the union grid intact while exercising real gaps and source NaNs."""
    frames = {asset: frame.copy() for asset, frame in make_positive_fixture(periods).items()}
    grid = tuple(next(iter(frames.values())).index)
    # Asset-0 remains the full calendar source so every missing asset-1 bar is
    # represented by a real NaN slot in the rectangular reference matrix.
    missing_bar = grid[periods // 2]
    frames["asset-1"] = frames["asset-1"].drop(index=missing_bar)
    frames["asset-3"].loc[grid[periods // 4], "high"] = math.nan
    frames["asset-4"].loc[grid[-4], "close"] = math.nan
    return frames


@pytest.mark.slow
@pytest.mark.parametrize("periods", HISTORY_LENGTHS, ids=lambda value: "T%d" % value)
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_alpha101_matrix_matches_causal_float64_ast(periods, runonce):
    frames = _long_history_fixture(periods)
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    failures = []
    checked = 0

    for batch in _batches():
        strategy = run_native_batch(frames, batch, runonce=runonce)
        for alpha_id in batch:
            factor = strategy.factor_instances["alpha%d" % alpha_id]
            report = validate_factor_trace(
                factor, alpha_id, frames, assets, grid, strategy=strategy
            )
            failures.extend(report["failures"])
            assert_finite_witness(alpha_id, report["expected"], history_h(alpha_id))
            checked += 1

    assert checked == 101
    assert not failures, "Alpha101 trace deviations:\n" + "\n".join(failures[:30])


def _exact_panel_summary(matrix):
    digest = hashlib.sha256()
    columns = len(matrix[0]) if matrix else 0
    digest.update(("%d,%d;" % (len(matrix), columns)).encode("ascii"))
    finite = 0
    nan = 0
    for row in matrix:
        if len(row) != columns:
            raise AssertionError("factor panel rows have inconsistent asset counts")
        for raw in row:
            value = float(raw)
            if math.isnan(value):
                nan += 1
                digest.update(b"N;")
            elif math.isinf(value):
                raise AssertionError("factor panel contains infinity")
            else:
                finite += 1
                token = "0;" if value == 0.0 else value.hex() + ";"
                digest.update(token.encode("ascii"))
    return {
        "cells": len(matrix) * columns,
        "finite_cells": finite,
        "nan_cells": nan,
        "sha256": digest.hexdigest(),
    }


def _assert_exact_panels(left, right, *, label):
    if len(left) != len(right):
        raise AssertionError("%s row count differs" % label)
    for row_index, (left_row, right_row) in enumerate(zip(left, right)):
        if len(left_row) != len(right_row):
            raise AssertionError("%s asset count differs at row %d" % (label, row_index))
        for asset_index, (left_value, right_value) in enumerate(zip(left_row, right_row)):
            left_value, right_value = float(left_value), float(right_value)
            location = "%s row %d asset %d" % (label, row_index, asset_index)
            if math.isnan(left_value) or math.isnan(right_value):
                if not (math.isnan(left_value) and math.isnan(right_value)):
                    raise AssertionError("%s NaN mask differs" % location)
            elif math.isinf(left_value) or math.isinf(right_value):
                raise AssertionError("%s contains infinity" % location)
            elif left_value != right_value:
                raise AssertionError(
                    "%s exact values differ: %.17g != %.17g" % (location, left_value, right_value)
                )
    return _exact_panel_summary(left)


def _pair_record(report):
    if not report["equal"]:
        raise AssertionError(
            "Alpha%d graph pair failed: %s" % (report["alpha_id"], report["failures"][:8])
        )
    return {
        key: report[key]
        for key in (
            "equal",
            "node_count_left",
            "node_count_right",
            "matched_node_count",
            "node_value_cells",
            "node_reason_cells",
            "node_value_sha256",
            "node_reason_sha256",
            "result_output_cells",
            "result_output_sha256",
            "grid_rows",
            "assets",
        )
    }


def _write_pair_evidence(periods, record):
    evidence_root = os.environ.get(BUILD_PAIR_EVIDENCE_ENV)
    if not evidence_root:
        return
    complete = record.get("complete_registry_coverage") is True
    aggregate = record.get("aggregate", {})
    if record.get("status") == "PASS" and not complete:
        raise AssertionError("partial Alpha101 selection cannot be written as PASS evidence")
    if aggregate.get("all_pass") is True and not complete:
        raise AssertionError("partial Alpha101 selection cannot claim all_pass evidence")
    output_dir = Path(evidence_root).expanduser()
    output_path = output_dir / ("alpha101-build-pair-T%d.json" % periods)
    if output_path.exists():
        raise AssertionError(
            "refusing to overwrite existing Alpha101 pair evidence: %s" % output_path
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(output_dir),
        prefix=".alpha101-pair-",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
        json.dump(record, temporary, sort_keys=True, indent=2, allow_nan=False)
        temporary.write("\n")
    os.replace(str(temporary_path), str(output_path))


@pytest.mark.slow
@pytest.mark.parametrize("periods", HISTORY_LENGTHS, ids=lambda value: "T%d" % value)
def test_alpha101_native_build_pair_graph_matrix(periods):
    if os.environ.get(BUILD_PAIR_ENV) != "1":
        pytest.skip("set %s=1 to run the opt-in native/build graph matrix" % BUILD_PAIR_ENV)

    batches = selected_alpha_batches()
    alpha_ids = tuple(alpha_id for _name, batch in batches for alpha_id in batch)
    if not alpha_ids:
        raise AssertionError("Alpha101 native/build pair selection is empty")
    frames = _long_history_fixture(periods)
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    modes = ("native", "build")
    engines = (("runnext", False), ("runonce", True))
    lane_keys = tuple((mode, engine_name) for mode in modes for engine_name, _ in engines)
    alpha_records = {}
    lane_totals = {
        key: {
            "alpha_ids": [],
            "factor_classes": {},
            "oracle_pass_count": 0,
            "finite_witness_count": 0,
            "lifecycle_pass_count": 0,
            "factor_panel": {"cells": 0, "finite_cells": 0, "nan_cells": 0},
            "panel_digest": hashlib.sha256(),
        }
        for key in lane_keys
    }
    pair_counts = {
        "same_engine_build_pair_count": 0,
        "cross_engine_graph_pair_count": 0,
        "node_value_cells": 0,
        "node_reason_cells": 0,
        "result_output_cells": 0,
        "cross_engine_panel_cells": 0,
        "cross_engine_panel_finite_cells": 0,
        "cross_engine_panel_nan_cells": 0,
    }

    for _batch_name, batch in batches:
        lane_strategies = {}
        lane_classes = {}
        lane_panels = {}
        for mode in modes:
            classes = {alpha_id: get_alpha(alpha_id, mode=mode) for alpha_id in batch}
            for engine_name, runonce in engines:
                key = (mode, engine_name)
                strategy = run_native_batch(
                    frames,
                    batch,
                    runonce=runonce,
                    factor_mode=mode,
                    alpha_classes=classes,
                )
                assert_lifecycle(strategy, batch, grid, alpha_classes=classes)
                if strategy._alpha101_broker_call_counts != {"submit": 0, "cancel": 0}:
                    raise AssertionError("Alpha101 research lane invoked broker submit/cancel")
                lane_strategies[key] = strategy
                lane_classes[key] = classes
                lane_totals[key]["alpha_ids"].extend(batch)
                lane_totals[key]["lifecycle_pass_count"] += len(batch)

                for alpha_id in batch:
                    factor = strategy.factor_instances["alpha%d" % alpha_id]
                    trace = validate_factor_trace(
                        factor, alpha_id, frames, assets, grid, strategy=strategy
                    )
                    if trace["failures"]:
                        raise AssertionError(
                            "Alpha%d %s/%s oracle trace failed: %s"
                            % (alpha_id, mode, engine_name, trace["failures"][:8])
                        )
                    assert_finite_witness(alpha_id, trace["expected"], history_h(alpha_id))
                    lane_totals[key]["oracle_pass_count"] += 1
                    lane_totals[key]["finite_witness_count"] += 1
                    factor_class = classes[alpha_id]
                    lane_totals[key]["factor_classes"][str(alpha_id)] = "%s.%s" % (
                        factor_class.__module__,
                        factor_class.__qualname__,
                    )
                    panel = [list(row) for row in trace["panel_actual"]]
                    summary = _exact_panel_summary(panel)
                    lane_panels[(key, alpha_id)] = panel
                    lane_total = lane_totals[key]["factor_panel"]
                    for field in ("cells", "finite_cells", "nan_cells"):
                        lane_total[field] += summary[field]
                    lane_totals[key]["panel_digest"].update((str(alpha_id) + ":").encode("ascii"))
                    lane_totals[key]["panel_digest"].update(summary["sha256"].encode("ascii"))
                    entry = alpha_records.setdefault(
                        alpha_id,
                        {
                            "oracle_pass": True,
                            "finite_witness": True,
                            "lifecycle_pass": True,
                            "lookback_h": history_h(alpha_id),
                            "factor_classes": {},
                            "same_engine_build_pair": {},
                            "cross_engine": {},
                        },
                    )
                    entry["factor_classes"]["%s/%s" % (mode, engine_name)] = lane_totals[key][
                        "factor_classes"
                    ][str(alpha_id)]

        for alpha_id in batch:
            alpha_entry = alpha_records[alpha_id]
            # Native/build graph and panel must agree within each Cerebro engine.
            for engine_name, _runonce in engines:
                native_key = ("native", engine_name)
                build_key = ("build", engine_name)
                graph_pair = compare_factor_graphs(
                    lane_strategies[native_key].factor_instances["alpha%d" % alpha_id],
                    lane_strategies[build_key].factor_instances["alpha%d" % alpha_id],
                    alpha_id,
                )
                pair = _pair_record(graph_pair)
                pair["factor_panel"] = _assert_exact_panels(
                    lane_panels[(native_key, alpha_id)],
                    lane_panels[(build_key, alpha_id)],
                    label="Alpha%d same-engine native/build %s panel" % (alpha_id, engine_name),
                )
                alpha_entry["same_engine_build_pair"][engine_name] = pair
                pair_counts["same_engine_build_pair_count"] += 1
                pair_counts["node_value_cells"] += pair["node_value_cells"]
                pair_counts["node_reason_cells"] += pair["node_reason_cells"]
                pair_counts["result_output_cells"] += pair["result_output_cells"]

            # Each mode's runnext and runonce graphs, result arrays, and panels agree.
            for mode in modes:
                next_key = (mode, "runnext")
                once_key = (mode, "runonce")
                graph_pair = compare_factor_graphs(
                    lane_strategies[next_key].factor_instances["alpha%d" % alpha_id],
                    lane_strategies[once_key].factor_instances["alpha%d" % alpha_id],
                    alpha_id,
                )
                pair = _pair_record(graph_pair)
                pair["factor_panel"] = _assert_exact_panels(
                    lane_panels[(next_key, alpha_id)],
                    lane_panels[(once_key, alpha_id)],
                    label="Alpha%d %s runnext/runonce panel" % (alpha_id, mode),
                )
                alpha_entry["cross_engine"][mode] = pair
                pair_counts["cross_engine_graph_pair_count"] += 1
                pair_counts["node_value_cells"] += pair["node_value_cells"]
                pair_counts["node_reason_cells"] += pair["node_reason_cells"]
                pair_counts["result_output_cells"] += pair["result_output_cells"]
                pair_counts["cross_engine_panel_cells"] += pair["factor_panel"]["cells"]
                pair_counts["cross_engine_panel_finite_cells"] += pair["factor_panel"][
                    "finite_cells"
                ]
                pair_counts["cross_engine_panel_nan_cells"] += pair["factor_panel"]["nan_cells"]

    engine_runs = []
    for mode, engine_name in lane_keys:
        key = (mode, engine_name)
        totals = lane_totals[key]
        engine_runs.append(
            {
                "factor_mode": mode,
                "engine": engine_name,
                "runonce": engine_name == "runonce",
                "alpha_ids": list(alpha_ids),
                "factor_classes": totals["factor_classes"],
                "oracle_pass_count": totals["oracle_pass_count"],
                "finite_witness_count": totals["finite_witness_count"],
                "lifecycle_pass_count": totals["lifecycle_pass_count"],
                "broker": {"submit": 0, "cancel": 0},
                "factor_panel": dict(
                    totals["factor_panel"], sha256=totals["panel_digest"].hexdigest()
                ),
            }
        )

    complete_registry = tuple(sorted(alpha_ids)) == tuple(formula_ids())
    aggregate = {
        "alpha_count": len(alpha_ids),
        "engine_run_count": len(engine_runs),
        "oracle_pass_count": sum(run["oracle_pass_count"] for run in engine_runs),
        "finite_witness_count": sum(run["finite_witness_count"] for run in engine_runs),
        "lifecycle_pass_count": sum(run["lifecycle_pass_count"] for run in engine_runs),
        **pair_counts,
        "all_pass": complete_registry,
    }
    record = {
        "schema_version": 1,
        "status": "PASS" if complete_registry else "INCOMPLETE",
        "periods": periods,
        "alpha_ids": list(alpha_ids),
        "complete_registry_coverage": complete_registry,
        "engine_runs": engine_runs,
        "per_alpha": {str(alpha_id): alpha_records[alpha_id] for alpha_id in alpha_ids},
        "aggregate": aggregate,
    }
    _write_pair_evidence(periods, record)
