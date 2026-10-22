"""Lightweight contracts for the factor research benchmark harnesses."""

from __future__ import annotations

import json
import os
import sys
from argparse import Namespace
from pathlib import Path

from scripts import benchmark_factor_research as staged_benchmark
from scripts import benchmark_factor_research_pair as pair_benchmark


def _write_report(output_dir: Path, factor: str) -> str:
    report = output_dir / ("factor_report_%s.html" % factor)
    report.write_text("<html>report</html>", encoding="utf-8")
    return str(report)


def _valid_summary(example: str, output_dir: Path, charts_enabled: bool = True) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    factors = pair_benchmark.EXPECTED_FACTORS[example]
    header = "time,asset," + ",".join(factors) + "\n"
    values = "".join(
        "2025-01-01,%06d," % index + ",".join("1.25" for _ in factors) + "\n"
        for index in range(20)
    )
    (output_dir / "factor_values.csv").write_text(header + values, encoding="utf-8")
    reports = [_write_report(output_dir, factor) for factor in pair_benchmark.EXPECTED_FACTORS[example]]
    if example in ("025", "026"):
        panel_dir = output_dir / "panel"
        panel_dir.mkdir()
        for filename in sorted(pair_benchmark.EXPECTED_PANEL_CSVS):
            (panel_dir / filename).write_text("time,asset,value\n2025-01-01,000001,1\n", encoding="utf-8")
        evaluation_id = "synthetic-evaluation"
        evaluation_dir = output_dir / "evaluation" / evaluation_id
        evaluation_dir.mkdir(parents=True)
        exports = ["labels.csv", "ic.csv", "signals.csv"]
        if charts_enabled:
            exports.extend(["ic_series.png", "quantile_returns.png"])
            for filename in exports[-2:]:
                (evaluation_dir / filename).write_bytes(b"synthetic png bytes")
        (evaluation_dir / "manifest.json").write_text(
            json.dumps({"exports": exports}) + "\n", encoding="utf-8"
        )
        (evaluation_dir / "labels.csv").write_text(
            "time,asset,period,value\n2025-01-01,000001,1,0.1\n", encoding="utf-8"
        )
        (evaluation_dir / "ic.csv").write_text(
            "time,factor,period,ic,rank_ic,n_assets\n2025-01-01,close_ma,1,0.2,0.3,1\n",
            encoding="utf-8",
        )
        (evaluation_dir / "signals.csv").write_text(
            "time,asset,factor,direction,value\n2025-01-01,000001,close_ma,1,0.1\n",
            encoding="utf-8",
        )
        return {
            "status": "COMPLETED",
            "symbols": 20,
            "dates": 1,
            "broker": {"submit": 0, "cancel": 0},
            "evaluation_id": evaluation_id,
            "evaluation_status": "OK",
            "report": reports[0] if example == "025" else None,
            "reports": reports if example == "026" else None,
        }
    return {
        "status": "COMPLETED",
        "symbols": 20,
        "dates": 1,
        "cells": 20,
        "finite": 20,
        "report": reports[0],
    }


def test_command_runs_example_entrypoint_with_fixed_inputs_and_required_outputs(tmp_path: Path):
    root = tmp_path / "checkout"
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "out"

    command_025 = pair_benchmark._build_command(root, "025", output_dir, data_dir, 20)
    command_026 = pair_benchmark._build_command(root, "026", output_dir, data_dir, 20)
    command_027 = pair_benchmark._build_command(root, "027", output_dir, data_dir, 20)
    legacy_command = pair_benchmark._build_command(
        root, "025", output_dir, data_dir, 20, "legacy_research_dataset"
    )

    assert command_025[1] == str(root / pair_benchmark.EXAMPLE_DIRS["025"] / "run.py")
    assert command_025[-1] == "--save-panel"
    assert command_026[-1] == "--save-panel"
    assert "--no-charts" not in command_025
    assert "--no-charts" not in command_026
    assert "--report" in command_027
    assert "--save-panel" not in command_027
    assert command_027[command_027.index("--max-symbols") + 1] == "20"
    assert "--save-dataset" in legacy_command
    assert "--save-panel" not in legacy_command
    diagnostic_command = pair_benchmark._build_command(
        root, "025", output_dir, data_dir, 20, "factor_panel_csv", no_charts=True
    )
    assert diagnostic_command[-2:] == ["--save-panel", "--no-charts"]


def test_pair_runner_requires_exact_ok_evaluation_and_nonempty_report(tmp_path: Path):
    good_dir = tmp_path / "good"
    summary = _valid_summary("025", good_dir)

    good = pair_benchmark._validate_run(
        "025", summary, 0, good_dir, save_mode="factor_panel_csv", requested_symbols=20
    )
    assert good["status"] == "OK"
    assert good["evaluation"] == {"requested": True, "applicable": True, "status": "OK"}
    assert good["sample_count"] == {
        "requested": 20,
        "effective": 20,
        "reported_dates": 1,
        "factor_value_rows": 20,
        "status": "OK",
    }
    assert good["orders"] == {
        "applicable": True,
        "status": "OK",
        "submit": 0,
        "cancel": 0,
    }
    assert good["factor_values_csv"]["finite_factors"] == {"close_ma": 20}
    assert good["evaluation_results"]["status"] == "OK"
    assert good["charts"]["status"] == "OK"
    assert good["charts"]["expected"] == ["ic_series.png", "quantile_returns.png"]
    assert len(good["charts"]["files"]) == 2
    assert all(item["sha256"] for item in good["charts"]["files"])
    assert good["saved_data_artifact"]["csv_contract"]["exact_match"] is True

    summary["evaluation_status"] = "PARTIAL"
    partial = pair_benchmark._validate_run(
        "025", summary, 0, good_dir, save_mode="factor_panel_csv", requested_symbols=20
    )
    assert partial["status"] == "FAILED"
    assert any("expected OK" in issue for issue in partial["problems"])

    summary["evaluation_status"] = "OK"
    (good_dir / "factor_report_close_ma.html").write_text("", encoding="utf-8")
    empty_report = pair_benchmark._validate_run(
        "025", summary, 0, good_dir, save_mode="factor_panel_csv", requested_symbols=20
    )
    assert empty_report["status"] == "FAILED"
    assert empty_report["reports"][0]["exists_nonempty"] is False


def test_pair_runner_rejects_missing_process_exit_status(tmp_path: Path):
    result = pair_benchmark._validate_run("027", None, None, tmp_path)

    assert result["status"] == "FAILED"
    assert any("did not start or return" in issue for issue in result["problems"])


def test_pair_runner_validates_all_026_reports_and_marks_027_evaluation_na(tmp_path: Path):
    multi_dir = tmp_path / "multi"
    multi = _valid_summary("026", multi_dir)
    assert pair_benchmark._validate_run(
        "026", multi, 0, multi_dir, save_mode="factor_panel_csv", requested_symbols=20
    )["status"] == "OK"

    multi["reports"].pop()
    invalid_multi = pair_benchmark._validate_run(
        "026", multi, 0, multi_dir, save_mode="factor_panel_csv", requested_symbols=20
    )
    assert invalid_multi["status"] == "FAILED"

    alpha_dir = tmp_path / "alpha"
    alpha = _valid_summary("027", alpha_dir)
    alpha_result = pair_benchmark._validate_run(
        "027", alpha, 0, alpha_dir, requested_symbols=20
    )
    assert alpha_result["status"] == "OK"
    assert alpha_result["evaluation"] == {
        "requested": False,
        "applicable": False,
        "status": "NOT_APPLICABLE",
    }


def test_pair_runner_records_legacy_dataset_and_current_panel_schema(tmp_path: Path):
    legacy_dir = tmp_path / "legacy"
    summary = _valid_summary("025", legacy_dir)
    dataset_dir = legacy_dir / "dataset"
    dataset_dir.mkdir()
    (dataset_dir / "manifest.json").write_text("{}", encoding="utf-8")

    legacy = pair_benchmark._validate_run(
        "025", summary, 0, legacy_dir, save_mode="legacy_research_dataset", requested_symbols=20
    )
    assert legacy["status"] == "OK"
    assert legacy["saved_data_artifact"]["api"] == "--save-dataset"
    assert legacy["saved_data_artifact"]["files"][0]["sha256"]

    current = pair_benchmark._validate_run(
        "025", summary, 0, legacy_dir, save_mode="factor_panel_csv", requested_symbols=20
    )
    assert current["status"] == "OK"
    assert current["saved_data_artifact"]["api"] == "--save-panel"
    assert current["saved_data_artifact"]["files"]


def test_pair_runner_fails_closed_on_undersampling_and_records_counts(tmp_path: Path):
    output_dir = tmp_path / "undersampled"
    summary = _valid_summary("025", output_dir)

    result = pair_benchmark._validate_run(
        "025", summary, 0, output_dir, save_mode="factor_panel_csv", requested_symbols=500
    )

    assert result["status"] == "FAILED"
    assert result["sample_count"] == {
        "requested": 500,
        "effective": 20,
        "reported_dates": 1,
        "factor_value_rows": 20,
        "status": "INSUFFICIENT",
    }
    assert any("insufficient input symbols" in issue for issue in result["problems"])


def test_pair_runner_rejects_broker_activity_and_factor_columns_without_finite_data(
    tmp_path: Path,
):
    output_dir = tmp_path / "invalid-factor"
    summary = _valid_summary("025", output_dir)
    summary["broker"]["submit"] = 1
    (output_dir / "factor_values.csv").write_text(
        "time,asset,close_ma\n2025-01-01,000001,\n", encoding="utf-8"
    )

    result = pair_benchmark._validate_run(
        "025", summary, 0, output_dir, save_mode="factor_panel_csv", requested_symbols=20
    )

    assert result["status"] == "FAILED"
    assert result["orders"]["status"] == "FAILED"
    assert result["factor_values_csv"]["finite_factors"]["close_ma"] == 0
    assert any("unexpected broker activity" in issue for issue in result["problems"])
    assert any("no finite values" in issue for issue in result["problems"])


def test_pair_runner_requires_nonempty_core_evaluation_tables(tmp_path: Path):
    output_dir = tmp_path / "empty-evaluation"
    summary = _valid_summary("025", output_dir)
    evaluation_dir = output_dir / "evaluation" / summary["evaluation_id"]
    (evaluation_dir / "ic.csv").write_text(
        "time,factor,period,ic,rank_ic,n_assets\n", encoding="utf-8"
    )

    result = pair_benchmark._validate_run(
        "025", summary, 0, output_dir, save_mode="factor_panel_csv", requested_symbols=20
    )

    assert result["status"] == "FAILED"
    assert result["evaluation_results"]["tables"]["ic.csv"]["rows"] == 0
    assert any("evaluation table has no records: ic.csv" in issue for issue in result["problems"])


def test_pair_runner_checks_manifest_declared_pngs_and_supports_diagnostic_export(
    tmp_path: Path,
):
    output_dir = tmp_path / "chart-run"
    summary = _valid_summary("025", output_dir, charts_enabled=True)
    png = output_dir / "evaluation" / summary["evaluation_id"] / "ic_series.png"
    png.unlink()

    missing_png = pair_benchmark._validate_run(
        "025", summary, 0, output_dir, save_mode="factor_panel_csv", requested_symbols=20
    )
    assert missing_png["status"] == "FAILED"
    assert missing_png["charts"]["status"] == "FAILED"
    assert any("PNG set does not match manifest exports" in issue for issue in missing_png["problems"])

    no_chart_dir = tmp_path / "diagnostic-run"
    no_chart_summary = _valid_summary("025", no_chart_dir, charts_enabled=False)
    diagnostic = pair_benchmark._validate_run(
        "025",
        no_chart_summary,
        0,
        no_chart_dir,
        save_mode="factor_panel_csv",
        requested_symbols=20,
        charts_enabled=False,
    )
    assert diagnostic["status"] == "OK"
    assert diagnostic["charts"]["status"] == "NOT_REQUESTED"


def test_pair_runner_requires_exactly_the_six_candidate_panel_csvs(tmp_path: Path):
    output_dir = tmp_path / "wrong-panel"
    summary = _valid_summary("025", output_dir)
    panel_dir = output_dir / "panel"
    (panel_dir / "groups.csv").unlink()
    (panel_dir / "extra.csv").write_text("value\n1\n", encoding="utf-8")

    result = pair_benchmark._validate_run(
        "025", summary, 0, output_dir, save_mode="factor_panel_csv", requested_symbols=20
    )

    assert result["status"] == "FAILED"
    contract = result["saved_data_artifact"]["csv_contract"]
    assert contract["exact_match"] is False
    assert "groups.csv" in contract["expected"]
    assert "extra.csv" in contract["actual"]
    assert any("exact non-empty six-file contract" in issue for issue in result["problems"])


def test_pair_runner_rejects_empty_member_of_candidate_panel_csv_contract(tmp_path: Path):
    output_dir = tmp_path / "empty-panel-csv"
    summary = _valid_summary("025", output_dir)
    (output_dir / "panel" / "groups.csv").write_text("", encoding="utf-8")

    result = pair_benchmark._validate_run(
        "025", summary, 0, output_dir, save_mode="factor_panel_csv", requested_symbols=20
    )

    assert result["status"] == "FAILED"
    assert result["saved_data_artifact"]["csv_contract"]["exact_match"] is False
    assert any("exact non-empty six-file contract" in issue for issue in result["problems"])


def test_small_sample_scope_is_explicitly_smoke_only():
    smoke = pair_benchmark._sample_scope(20)
    formal = pair_benchmark._sample_scope(500)
    no_charts = pair_benchmark._sample_scope(500, no_charts=True)

    assert smoke["run_status"] == "SMOKE_ONLY"
    assert smoke["formal_sample_floor_met"] is False
    assert formal["run_status"] == "OK"
    assert formal["formal_sample_floor_met"] is True
    assert no_charts["run_status"] == "DIAGNOSTIC_ONLY"
    assert no_charts["formal_sample_floor_met"] is True
    assert no_charts["formal_eligible"] is False


def test_run_environment_replaces_inherited_pythonpath(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/unrelated/checkout")

    environment = pair_benchmark._process_environment(tmp_path)

    assert environment["PYTHONPATH"] == str(tmp_path.resolve())
    assert environment["PYTHONPATH"] != os.environ.get("PYTHONPATH")


def test_run_dir_leaves_leaf_for_entrypoint_to_create(tmp_path: Path):
    output_dir = pair_benchmark._run_dir(tmp_path, "025", "warmup", "baseline", None)

    assert not output_dir.exists()
    assert output_dir.parent.is_dir()


def test_pair_groups_alternate_start_side_and_config_diff_is_reported():
    assert pair_benchmark._alternating_order(1) == ("baseline", "candidate")
    assert pair_benchmark._alternating_order(2) == ("candidate", "baseline")
    assert pair_benchmark._alternating_order(3) == ("baseline", "candidate")
    assert pair_benchmark._config_differences({"data": {"n": 20}}, {"data": {"n": 21}}) == [
        {"path": "data.n", "baseline": 20, "candidate": 21}
    ]


def test_config_difference_allowlist_is_exact_and_labeled_as_end_to_end_only():
    profile_difference = {
        "027": [
            {
                "path": "operator_profile",
                "baseline": "alpha101-v1",
                "candidate": "alpha101-v2",
            }
        ]
    }

    denied = pair_benchmark._classify_config_differences(profile_difference, [])
    assert denied["compatible"] is False
    approved = pair_benchmark._classify_config_differences(
        profile_difference, ["operator_profile"]
    )
    assert approved["compatible"] is True
    assert approved["allowed_differences"][0]["approved"] is True
    assert "end-to-end comparison only" in approved["allowed_differences"][0]["scope"]

    wrong_profile = {
        "027": [
            {
                "path": "operator_profile",
                "baseline": "alpha101-v0",
                "candidate": "alpha101-v2",
            }
        ]
    }
    rejected = pair_benchmark._classify_config_differences(
        wrong_profile, ["operator_profile"]
    )
    assert rejected["compatible"] is False


def test_parent_measurement_records_wall_cpu_and_process_tree_rss():
    measured = pair_benchmark._measure_process(
        [sys.executable, "-c", "import time; time.sleep(0.08)"], Path.cwd(), 0.02
    )

    assert measured["returncode"] == 0
    assert measured["wall_s"] > 0
    assert measured["cpu_tree_s"] >= 0
    assert measured["peak_rss_tree_bytes"] > 0
    assert measured["samples"]


def test_staged_benchmark_marks_nested_and_inapplicable_stages():
    args = Namespace(csv=False, report=True, evaluate=True)

    states_025 = staged_benchmark._stage_states(args, "025")
    states_027 = staged_benchmark._stage_states(args, "027")

    assert states_025["evaluate"] == {
        "requested": True,
        "applicable": True,
        "status": "NOT_RUN",
        "nested": False,
        "nested_in": None,
    }
    assert states_025["cerebro"]["nested"] is False
    assert states_025["collect"]["nested"] is True
    assert states_025["collect"]["nested_in"] == "cerebro"
    assert states_025["panel"]["nested"] is False
    staged_benchmark._mark_collection_included(states_025)
    assert states_025["collect"]["status"] == "INCLUDED_IN_CEREBRO"
    assert states_027["evaluate"]["status"] == "NOT_APPLICABLE"
    assert states_027["evaluate"]["applicable"] is False


def test_staged_benchmark_keeps_setup_failures_as_failed_records():
    args = Namespace(csv=False, report=True, evaluate=True, runnext=False, symbols=20)

    result = staged_benchmark._failed_result(args, "025", 0, ImportError("fincore unavailable"))

    assert result["status"] == "FAILED"
    assert result["stages_s"]["cerebro"] is None
    assert result["stage_states"]["evaluate"]["requested"] is True
    assert result["stage_states"]["evaluate"]["status"] == "NOT_RUN"
