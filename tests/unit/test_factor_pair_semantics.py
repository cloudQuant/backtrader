"""Keyed semantic checks for paired FactorPanel research outputs."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "verify_factor_research_pair_semantics.py"
)
_SPEC = importlib.util.spec_from_file_location("factor_pair_semantics", SCRIPT)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load comparator script")
_COMPARATOR = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_COMPARATOR)

TIME = "2025-01-02T00:00:00+00:00"
FACTOR_ORDER = ("close_ma", "kdj_j", "roc")


def _write_csv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(fields))
        writer.writeheader()
        writer.writerows(rows)


def _key_row(fields: Sequence[str]) -> Dict[str, str]:
    fixed = {
        "time": TIME,
        "asset": "ASSET_A",
        "period": "1",
        "factor": "close_ma",
        "kind": "factor",
        "direction": "1",
        "factor_left": "close_ma",
        "factor_right": "kdj_j",
        "lag": "1",
        "quantile": "5",
        "comparison": "ma_vs_equal_weight",
        "left": "close_ma",
        "right": "equal_weight",
        "stage": "evaluation",
        "severity": "info",
        "code": "OK",
        "message": "no diagnostic",
    }
    return {field: fixed.get(field, "key") for field in fields}


def _value_row(fields: Sequence[str]) -> Dict[str, str]:
    return {
        field: (
            "OK"
            if field == "status"
            else (
                "cross_section_rank"
                if field == "preprocess"
                else "all_symbols" if field == "group" else "0.5"
            )
        )
        for field in fields
    }


def _write_run(
    root: Path,
    *,
    factor_order: Sequence[str] = FACTOR_ORDER,
    factor_values: Mapping[str, Mapping[str, str]] | None = None,
    correlation_mean: str = "0.5",
    reverse_correlation_pair: bool = False,
    result_fingerprint: str = "a" * 64,
    evaluation_status: str = "OK",
    empty_tables: Sequence[str] = (),
    spec_combinations: Mapping[str, object] | None = None,
    spec_comparisons: Mapping[str, object] | None = None,
    manifest_row_overrides: Mapping[str, int] | None = None,
) -> None:
    evaluation_id = "eval-" + root.name
    evaluation = root / "evaluation" / evaluation_id
    evaluation.mkdir(parents=True)
    (root / "summary.json").write_text(
        json.dumps(
            {
                "status": "COMPLETED",
                "evaluation_status": evaluation_status,
                "evaluation_id": evaluation_id,
                "symbols": 2,
                "dates": 1,
            }
        ),
        encoding="utf-8",
    )
    values = factor_values or {
        "ASSET_A": {"close_ma": "1.0", "kdj_j": "3.0", "roc": "5.0"},
        "ASSET_B": {"close_ma": "2.0", "kdj_j": "4.0", "roc": "6.0"},
    }
    _write_csv(
        root / "factor_values.csv",
        ("time", "asset", *factor_order),
        (
            {"time": TIME, "asset": asset, **{name: row[name] for name in factor_order}}
            for asset, row in values.items()
        ),
    )

    tables = {}
    for filename, (key_fields, value_fields) in _COMPARATOR.TABLE_CONTRACTS.items():
        fields = (*key_fields, *value_fields)
        row = {**_key_row(key_fields), **_value_row(value_fields)}
        if filename == "correlation.csv":
            row["mean_correlation"] = correlation_mean
            if reverse_correlation_pair:
                row["factor_left"], row["factor_right"] = (
                    row["factor_right"],
                    row["factor_left"],
                )
        rows = () if filename[:-4] in empty_tables else (row,)
        _write_csv(evaluation / filename, fields, rows)
        table_key = filename[:-4]
        row_count = len(rows)
        if manifest_row_overrides and table_key in manifest_row_overrides:
            row_count = manifest_row_overrides[table_key]
        tables[table_key] = {"columns": list(fields), "rows": row_count}

    combinations = {} if spec_combinations is None else dict(spec_combinations)
    comparisons = {"ma_vs_equal_weight": {}} if spec_comparisons is None else dict(spec_comparisons)
    (evaluation / "manifest.json").write_text(
        json.dumps(
            {
                "evaluation_id": evaluation_id,
                "result_fingerprint": result_fingerprint,
                "tables": tables,
                "counts": {"factors": len(factor_order), "combinations": len(combinations)},
                "spec": {"combinations": combinations, "comparisons": comparisons},
            }
        ),
        encoding="utf-8",
    )


def _compare(tmp_path: Path, candidate_overrides: Mapping[str, object]) -> dict:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline)
    _write_run(candidate, **candidate_overrides)
    return _COMPARATOR.compare_runs(baseline, candidate)


def _set_mode_summary(root: Path, mode: str, *, factor_calculation: str = "RAN") -> None:
    path = root / "summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary.update(
        {
            "factor_mode": mode,
            "factor_calculation": factor_calculation,
            "factor_classes": {
                factor: "multi_factor_strategy.%s"
                % {
                    "close_ma": "CloseMAFactor",
                    "kdj_j": "KDJFactor",
                    "roc": "ROCFactor",
                }[factor]
                for factor in FACTOR_ORDER
            },
            "broker": {"submit": 0, "cancel": 0},
        }
    )
    path.write_text(json.dumps(summary), encoding="utf-8")


def _write_report(
    root: Path,
    metric_value: float = 0.5,
    *,
    summary_field: str = "reports",
    runner_creates_output: bool = False,
) -> Path:
    html_module = pytest.importorskip("fincore.report.factor.html")
    models = pytest.importorskip("fincore.report.models")
    pd = pytest.importorskip("pandas")
    dates = pd.date_range("2025-01-01", periods=2, tz="UTC")
    mean_returns = pd.DataFrame(
        {"1": [-0.01, 0.0, 0.01]},
        index=pd.Index([1, 2, 3], name="quantile"),
    )
    document = models.ReportDocument(
        domain="factor",
        title="Factor semantics",
        sections=(
            models.ReportSection(
                key="factor_summary",
                title="Factor summary",
                metrics={
                    "mean_information_coefficient.1": metric_value,
                    "observation_count": 4,
                    "finite_factor_count": 4,
                    "coverage_ratio": 1.0,
                    "quantile_count": 3,
                },
                tables={"quantile_statistics": pd.DataFrame({"count": [2, 1, 1]}, index=[1, 2, 3])},
                series={
                    "factor_cumulative_returns.1": pd.Series(
                        [1.0, 1.02], index=dates, name="growth"
                    )
                },
            ),
            models.ReportSection(
                key="factor_information",
                title="Information coefficient",
                tables={
                    "information_summary": pd.DataFrame(
                        {"Risk-Adjusted IC": [0.2], "t-stat(IC)": [0.4]}, index=["1"]
                    )
                },
                series={"ic.1": pd.Series([0.1, 0.2], index=dates, name="ic")},
            ),
            models.ReportSection(
                key="factor_returns",
                title="Factor returns",
                tables={
                    "returns_summary": pd.DataFrame({"value": [0.01]}, index=["spread"]),
                    "mean_returns_by_quantile": mean_returns,
                },
            ),
            models.ReportSection(
                key="factor_turnover",
                title="Turnover",
                tables={
                    "mean_turnover_by_quantile": pd.DataFrame(
                        {"1D": [0.1, 0.2, 0.3]}, index=[1, 2, 3]
                    ),
                    "rank_autocorrelation_summary": pd.DataFrame(
                        {"1D": [0.5]}, index=["autocorrelation"]
                    ),
                },
            ),
        ),
        metadata={"asset_count": 2, "date_count": 2, "start": dates[0], "end": dates[-1]},
    )
    report_path = root / "factor_report.html"
    summary_path = root / "summary.json"
    with _COMPARATOR.capture_report_semantics(root) as captured:
        assert not (root / _COMPARATOR.REPORT_SEMANTICS_FILENAME).exists()
        if runner_creates_output:
            root.mkdir()
        html_module.write_factor_html(document, report_path, language="en")
        assert len(captured) == 1
        summary = (
            json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
        )
        summary[summary_field] = (
            str(report_path) if summary_field == "report" else [str(report_path)]
        )
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        assert not (root / _COMPARATOR.REPORT_SEMANTICS_FILENAME).exists()
    return report_path


def _write_alpha003_run(
    root: Path,
    mode: str,
    *,
    rows: Sequence[Mapping[str, str]] | None = None,
    report: bool = False,
) -> None:
    import math

    default_rows = (
        {"time": TIME, "asset": "ASSET_A", "alpha003": "1.0"},
        {"time": TIME, "asset": "ASSET_B", "alpha003": "NaN"},
        {"time": "2025-01-03T00:00:00+00:00", "asset": "ASSET_A", "alpha003": "2.0"},
        {"time": "2025-01-03T00:00:00+00:00", "asset": "ASSET_B", "alpha003": "3.0"},
    )
    values = tuple(default_rows if rows is None else rows)
    root.mkdir(parents=True, exist_ok=True)
    _write_csv(root / "factor_values.csv", ("time", "asset", "alpha003"), values)
    finite = sum(math.isfinite(float(row["alpha003"])) for row in values)
    summary = {
        "status": "COMPLETED",
        "factor": "alpha003",
        "factor_mode": mode,
        "factor_calculation": "RAN",
        "indicator": "backtrader.research.alpha101.alpha003.Alpha003Native",
        "symbols": 2,
        "dates": 2,
        "cells": len(values),
        "finite": finite,
        "output": "factor_values.csv",
        "broker": {"submit": 0, "cancel": 0},
        "report": None,
        "elapsed_seconds": 0.1,
    }
    (root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    if report:
        _write_report(root, summary_field="report")


def _write_panel(root: Path) -> None:
    panel = root / "panel"
    panel.mkdir(parents=True, exist_ok=True)
    for name in sorted(_COMPARATOR.PANEL_CSV_FILES):
        (panel / name).write_text("name,value\nA,1\n", encoding="utf-8")


def test_reordered_factor_columns_are_reported_as_order_difference(tmp_path: Path):
    result = _compare(
        tmp_path,
        {
            "factor_order": ("close_ma", "roc", "kdj_j"),
            "result_fingerprint": "b" * 64,
        },
    )

    assert result["factor_order"]["same_set"] is True
    assert result["factor_order"]["same_order"] is False
    assert result["semantic_equal_ignoring_row_and_column_order"] is True
    assert result["ordering_equal"] is False
    assert result["only_observed_difference_is_ordering"] is False
    assert result["order_and_fingerprint_differ_with_equal_tables"] is True
    assert result["status"] == "ORDER_AND_FINGERPRINT_DIFFERENCES"


def test_asset_value_swap_is_not_hidden_by_equal_value_multiset(tmp_path: Path):
    result = _compare(
        tmp_path,
        {
            "factor_values": {
                "ASSET_A": {"close_ma": "2.0", "kdj_j": "3.0", "roc": "5.0"},
                "ASSET_B": {"close_ma": "1.0", "kdj_j": "4.0", "roc": "6.0"},
            }
        },
    )

    assert result["tables"]["factor_values.csv"]["semantic_equal"] is False
    assert result["tables"]["factor_values.csv"]["keyed"]["value_mismatches_by_field"] == {
        "close_ma": 2
    }
    assert result["status"] == "SEMANTIC_DIFFERENCES"


def test_nan_mask_difference_is_reported_at_asset_factor_key(tmp_path: Path):
    result = _compare(
        tmp_path,
        {
            "factor_values": {
                "ASSET_A": {"close_ma": "NaN", "kdj_j": "3.0", "roc": "5.0"},
                "ASSET_B": {"close_ma": "2.0", "kdj_j": "4.0", "roc": "6.0"},
            }
        },
    )

    factor_table = result["tables"]["factor_values.csv"]
    assert factor_table["semantic_equal"] is False
    assert factor_table["baseline"]["mask_counts"]["close_ma"]["finite"] == 2
    assert factor_table["candidate"]["mask_counts"]["close_ma"]["finite"] == 1
    assert factor_table["candidate"]["mask_counts"]["close_ma"]["nan"] == 1


def test_exact_float_comparison_catches_small_rank_relevant_change(tmp_path: Path):
    result = _compare(
        tmp_path,
        {
            "factor_values": {
                "ASSET_A": {
                    "close_ma": "1.0000000000000002",
                    "kdj_j": "3.0",
                    "roc": "5.0",
                },
                "ASSET_B": {"close_ma": "2.0", "kdj_j": "4.0", "roc": "6.0"},
            }
        },
    )

    assert result["tables"]["factor_values.csv"]["keyed"]["value_mismatches_by_field"] == {
        "close_ma": 1
    }


def test_correlation_kernel_difference_is_compared_by_pair_identity(tmp_path: Path):
    result = _compare(tmp_path, {"correlation_mean": "0.5000001"})

    correlation = result["tables"]["correlation.csv"]["keyed"]
    assert correlation["missing_in_candidate"] == 0
    assert correlation["extra_in_candidate"] == 0
    assert correlation["value_mismatches_by_field"] == {"mean_correlation": 1}
    assert result["status"] == "SEMANTIC_DIFFERENCES"


def test_unordered_pair_identity_is_kept_and_orientation_is_reported(tmp_path: Path):
    result = _compare(
        tmp_path,
        {
            "reverse_correlation_pair": True,
            "result_fingerprint": "c" * 64,
        },
    )

    correlation = result["tables"]["correlation.csv"]
    assert correlation["semantic_equal"] is True
    assert correlation["keyed"]["unordered_pair_orientation_mismatches"] == 1
    assert correlation["ordering_equal"] is False
    assert result["only_observed_difference_is_ordering"] is False
    assert result["order_and_fingerprint_differ_with_equal_tables"] is True


def test_identical_tables_order_and_fingerprint_pass_strict_comparison(tmp_path: Path):
    result = _compare(tmp_path, {})

    assert set(result["tables"]) == {"factor_values.csv", *_COMPARATOR.TABLE_CONTRACTS}
    assert result["semantic_equal_ignoring_row_and_column_order"] is True
    assert result["ordering_equal"] is True
    assert result["fingerprints"]["equal"] is True
    assert result["strict_equal"] is True
    assert result["status"] == "IDENTICAL"


def test_duplicate_semantic_keys_fail_comparison(tmp_path: Path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline)
    _write_run(candidate)
    factor_file = candidate / "factor_values.csv"
    with factor_file.open("a", encoding="utf-8") as stream:
        stream.write(f"{TIME},ASSET_A,1.0,3.0,5.0\n")

    result = _COMPARATOR.compare_runs(baseline, candidate)

    assert result["tables"]["factor_values.csv"]["candidate"]["duplicate_keys"] == 1
    assert result["tables"]["factor_values.csv"]["semantic_equal"] is False


def test_missing_evaluation_table_fails_closed(tmp_path: Path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline)
    _write_run(candidate)
    candidate_evaluation = next((candidate / "evaluation").iterdir())
    (candidate_evaluation / "diagnostics.csv").unlink()

    result = _COMPARATOR.compare_runs(baseline, candidate)

    diagnostics = result["tables"]["diagnostics.csv"]
    assert diagnostics["candidate"]["error"] == "missing CSV"
    assert diagnostics["semantic_equal"] is False


def test_empty_required_evaluation_table_fails_closed(tmp_path: Path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline)
    _write_run(candidate)
    candidate_evaluation = next((candidate / "evaluation").iterdir())
    ic_fields = _COMPARATOR.TABLE_CONTRACTS["ic.csv"][0] + _COMPARATOR.TABLE_CONTRACTS["ic.csv"][1]
    _write_csv(candidate_evaluation / "ic.csv", ic_fields, ())

    result = _COMPARATOR.compare_runs(baseline, candidate)

    ic = result["tables"]["ic.csv"]
    assert ic["candidate"]["error"] == "table has no data rows"
    assert ic["semantic_equal"] is False


def test_empty_labels_table_fails_closed(tmp_path: Path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline)
    _write_run(candidate)
    candidate_evaluation = next((candidate / "evaluation").iterdir())
    label_fields = (
        _COMPARATOR.TABLE_CONTRACTS["labels.csv"][0] + _COMPARATOR.TABLE_CONTRACTS["labels.csv"][1]
    )
    _write_csv(candidate_evaluation / "labels.csv", label_fields, ())

    result = _COMPARATOR.compare_runs(baseline, candidate)

    labels = result["tables"]["labels.csv"]
    assert labels["candidate"]["error"] == "table has no data rows"
    assert labels["semantic_equal"] is False


def test_manifest_declared_single_factor_empty_tables_are_accepted(tmp_path: Path):
    options = {
        "factor_order": ("close_ma",),
        "empty_tables": ("correlation", "comparisons"),
        "spec_combinations": {},
        "spec_comparisons": {},
    }
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline, **options)
    _write_run(candidate, **options)

    result = _COMPARATOR.compare_runs(baseline, candidate)

    for name in ("correlation.csv", "comparisons.csv"):
        table = result["tables"][name]
        assert table["baseline"]["row_count"] == 0
        assert table["candidate"]["row_count"] == 0
        assert table["baseline"]["error"] is None
        assert table["candidate"]["error"] is None
        assert table["semantic_equal"] is True
    assert result["strict_equal"] is True
    assert result["status"] == "IDENTICAL"


def test_empty_correlation_is_rejected_for_two_factor_panel(tmp_path: Path):
    options = {
        "factor_order": ("close_ma", "kdj_j"),
        "empty_tables": ("correlation",),
        "spec_combinations": {},
    }
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline, **options)
    _write_run(candidate, **options)

    result = _COMPARATOR.compare_runs(baseline, candidate)

    correlation = result["tables"]["correlation.csv"]
    assert correlation["candidate"]["error"] == "table has no data rows"
    assert correlation["semantic_equal"] is False
    assert result["strict_equal"] is False


def test_empty_comparisons_are_rejected_when_spec_still_requests_comparisons(
    tmp_path: Path,
):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline)
    _write_run(
        candidate,
        empty_tables=("comparisons",),
        spec_comparisons={"ma_vs_equal_weight": {}},
    )

    result = _COMPARATOR.compare_runs(baseline, candidate)

    comparisons = result["tables"]["comparisons.csv"]
    assert comparisons["candidate"]["error"] == "table has no data rows"
    assert comparisons["semantic_equal"] is False
    assert result["strict_equal"] is False


def test_one_sided_empty_table_is_rejected_when_manifest_claims_rows(tmp_path: Path):
    options = {
        "factor_order": ("close_ma",),
        "empty_tables": ("correlation", "comparisons"),
        "spec_combinations": {},
        "spec_comparisons": {},
    }
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline, **options)
    _write_run(candidate, **options, manifest_row_overrides={"correlation": 1})

    result = _COMPARATOR.compare_runs(baseline, candidate)

    correlation = result["tables"]["correlation.csv"]
    assert correlation["baseline"]["error"] is None
    assert correlation["candidate"]["row_count"] == 0
    assert correlation["candidate"]["error"] == "table has no data rows"
    assert correlation["semantic_equal"] is False


def test_empty_correlation_requires_spec_and_count_metadata(tmp_path: Path):
    for missing in ("spec", "counts"):
        case = tmp_path / missing
        baseline = case / "baseline"
        candidate = case / "candidate"
        options = {
            "factor_order": ("close_ma",),
            "empty_tables": ("correlation", "comparisons"),
            "spec_combinations": {},
            "spec_comparisons": {},
        }
        _write_run(baseline, **options)
        _write_run(candidate, **options)
        manifest_path = next((candidate / "evaluation").iterdir()) / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if missing == "spec":
            manifest.pop("spec")
        else:
            manifest["counts"].pop("combinations")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        result = _COMPARATOR.compare_runs(baseline, candidate)

        correlation = result["tables"]["correlation.csv"]
        assert correlation["candidate"]["error"] == "table has no data rows"
        assert correlation["semantic_equal"] is False


def test_empty_approved_table_still_requires_exact_csv_columns(tmp_path: Path):
    options = {
        "factor_order": ("close_ma",),
        "empty_tables": ("correlation", "comparisons"),
        "spec_combinations": {},
        "spec_comparisons": {},
    }
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline, **options)
    _write_run(candidate, **options)
    candidate_evaluation = next((candidate / "evaluation").iterdir())
    correlation_fields = (
        _COMPARATOR.TABLE_CONTRACTS["correlation.csv"][0]
        + _COMPARATOR.TABLE_CONTRACTS["correlation.csv"][1]
    )
    _write_csv(
        candidate_evaluation / "correlation.csv",
        correlation_fields[:-1],
        (),
    )

    result = _COMPARATOR.compare_runs(baseline, candidate)

    correlation = result["tables"]["correlation.csv"]
    assert correlation["candidate"]["error"] == "CSV columns differ from required schema"
    assert correlation["semantic_equal"] is False


def test_partial_evaluation_status_is_not_acceptable(tmp_path: Path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline)
    _write_run(candidate, evaluation_status="PARTIAL")

    result = _COMPARATOR.compare_runs(baseline, candidate)

    assert result["run_status"]["valid"] is False
    assert result["run_status"]["acceptable"] is False
    assert result["strict_equal"] is False
    assert result["status"] == "INVALID_RUN_STATE"


def test_missing_result_fingerprint_is_invalid_even_when_both_tables_match(tmp_path: Path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline)
    _write_run(candidate)
    candidate_manifest = next((candidate / "evaluation").iterdir()) / "manifest.json"
    manifest = json.loads(candidate_manifest.read_text(encoding="utf-8"))
    manifest.pop("result_fingerprint")
    candidate_manifest.write_text(json.dumps(manifest), encoding="utf-8")

    result = _COMPARATOR.compare_runs(baseline, candidate)

    assert result["fingerprints"]["valid"] is False
    assert result["fingerprints"]["equal"] is False
    assert result["strict_equal"] is False
    assert result["status"] == "INVALID_FINGERPRINT"


def test_identical_invalid_numeric_tokens_fail_closed(tmp_path: Path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    invalid_values = {
        "ASSET_A": {"close_ma": "not-a-number", "kdj_j": "3.0", "roc": "5.0"},
        "ASSET_B": {"close_ma": "2.0", "kdj_j": "4.0", "roc": "6.0"},
    }
    _write_run(baseline, factor_values=invalid_values)
    _write_run(candidate, factor_values=invalid_values)

    result = _COMPARATOR.compare_runs(baseline, candidate)

    factor_table = result["tables"]["factor_values.csv"]
    assert factor_table["baseline"]["mask_counts"]["close_ma"]["invalid_numeric"] == 1
    assert factor_table["candidate"]["mask_counts"]["close_ma"]["invalid_numeric"] == 1
    assert factor_table["baseline"]["error"] == "invalid numeric values: {'close_ma': 1}"
    assert factor_table["candidate"]["error"] == "invalid numeric values: {'close_ma': 1}"
    assert factor_table["semantic_equal"] is False
    assert result["strict_equal"] is False
    assert result["status"] == "SEMANTIC_DIFFERENCES"


def test_capture_report_semantics_wraps_real_writer_and_publishes_on_success(tmp_path: Path):
    html_module = pytest.importorskip("fincore.report.factor.html")
    output = tmp_path / "runner-created-output"
    original_writer = html_module.write_factor_html
    assert not output.exists()
    report_path = _write_report(output, 0.125, runner_creates_output=True)

    assert html_module.write_factor_html is original_writer
    sidecar_path = output / _COMPARATOR.REPORT_SEMANTICS_FILENAME
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    report = sidecar["reports"][0]
    html_path = output / report["html_path"]
    assert sidecar["schema_version"] == _COMPARATOR.REPORT_SEMANTICS_SCHEMA
    assert report["html_path"] == "factor_report.html"
    assert report_path == html_path
    assert report["html_sha256"] == __import__("hashlib").sha256(html_path.read_bytes()).hexdigest()
    assert report["semantic_payload"]["title"] == "Factor semantics"
    assert (
        report["semantic_payload"]["sections"][0]["metrics"]["mean_information_coefficient.1"]
        == 0.125
    )
    assert report["semantic_digest"] == _COMPARATOR._payload_digest(report["semantic_payload"])


def test_capture_report_semantics_allows_missing_output_directory(tmp_path: Path):
    html_module = pytest.importorskip("fincore.report.factor.html")
    missing = tmp_path / "not-created"
    original_writer = html_module.write_factor_html
    with _COMPARATOR.capture_report_semantics(missing) as captured:
        assert captured == []
        assert not missing.exists()
    assert not missing.exists()
    assert html_module.write_factor_html is original_writer
    assert not (missing / _COMPARATOR.REPORT_SEMANTICS_FILENAME).exists()


def test_capture_report_semantics_restores_writer_after_runner_exception(tmp_path: Path):
    html_module = pytest.importorskip("fincore.report.factor.html")
    output = tmp_path / "failed-output"
    original_writer = html_module.write_factor_html
    with pytest.raises(RuntimeError, match="abort"), _COMPARATOR.capture_report_semantics(output):
        output.mkdir()
        raise RuntimeError("abort")
    assert not (output / _COMPARATOR.REPORT_SEMANTICS_FILENAME).exists()
    assert html_module.write_factor_html is original_writer


def test_required_mode_pair_accepts_ran_native_build_and_zero_orders(tmp_path: Path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline)
    _write_run(candidate, result_fingerprint="b" * 64)
    _set_mode_summary(baseline, "native")
    _set_mode_summary(candidate, "build")

    result = _COMPARATOR.compare_runs(baseline, candidate, require_mode_pair=True)

    assert result["mode_pair"]["valid"] is True
    assert result["mode_pair"]["implementation_profile"] == (_COMPARATOR.SINGLE_CLASS_MODE_PROFILE)
    assert result["mode_pair"]["modes_differ_native_build"] is True
    assert result["mode_pair"]["summary_numeric_equal"] is True
    assert result["fingerprints"]["equal"] is False
    assert result["fingerprints"]["difference_allowed_by_mode_pair"] is True
    assert result["strict_equal"] is True
    assert result["schema_version"] == _COMPARATOR.PAIR_SEMANTICS_SCHEMA


@pytest.mark.parametrize("mode", ([], {}))
def test_mode_pair_invalid_unhashable_mode_fails_closed(tmp_path: Path, mode):
    baseline = {
        "status": "COMPLETED",
        "factor_mode": mode,
        "factor_calculation": "RAN",
        "factor_classes": {},
        "evaluation_status": "OK",
        "broker": {"submit": 0, "cancel": 0},
    }

    result = _COMPARATOR._compare_mode_pair(
        baseline, {**baseline, "factor_mode": "build"}, FACTOR_ORDER, alpha003=False
    )

    assert result["valid"] is False


@pytest.mark.parametrize("defect", ("same_mode", "not_ran", "wrong_identity", "numeric_summary"))
def test_required_mode_pair_rejects_invalid_or_nonpaired_modes(tmp_path: Path, defect: str):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline)
    _write_run(candidate)
    _set_mode_summary(baseline, "native")
    _set_mode_summary(
        candidate,
        "native" if defect == "same_mode" else "build",
        factor_calculation="NOT_RUN" if defect == "not_ran" else "RAN",
    )
    summary_path = candidate / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if defect == "wrong_identity":
        summary["factor_classes"]["roc"] = "multi_factor_strategy.ROCFactorBuild"
    elif defect == "numeric_summary":
        summary["dates"] = 2
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    result = _COMPARATOR.compare_runs(baseline, candidate, require_mode_pair=True)

    assert result["mode_pair"]["valid"] is False
    assert result["strict_equal"] is False


@pytest.mark.parametrize(
    "defect",
    (
        "missing_capture",
        "tampered_html",
        "changed_model",
        "missing_summary_path",
        "bad_payload_digest",
    ),
)
def test_required_report_semantics_rejects_incomplete_or_different_reports(
    tmp_path: Path, defect: str
):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline)
    _write_run(candidate)
    _set_mode_summary(baseline, "native")
    _set_mode_summary(candidate, "build")
    _write_report(baseline)
    candidate_report = _write_report(candidate, 0.75 if defect == "changed_model" else 0.5)

    if defect == "missing_capture":
        (candidate / _COMPARATOR.REPORT_SEMANTICS_FILENAME).unlink()
    elif defect == "tampered_html":
        candidate_report.write_text(
            candidate_report.read_text(encoding="utf-8") + "tampered", encoding="utf-8"
        )
    elif defect == "missing_summary_path":
        summary_path = candidate / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["reports"] = []
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
    elif defect == "bad_payload_digest":
        sidecar_path = candidate / _COMPARATOR.REPORT_SEMANTICS_FILENAME
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar["reports"][0]["semantic_payload"]["title"] = "altered without digest update"
        sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")

    result = _COMPARATOR.compare_runs(baseline, candidate, require_reports=True)

    assert result["report_semantics"]["equal"] is False
    assert result["strict_equal"] is False


def test_required_reports_compare_complete_semantic_payload_and_digest(tmp_path: Path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline)
    _write_run(candidate)
    _set_mode_summary(baseline, "native")
    _set_mode_summary(candidate, "build")
    _write_report(baseline, 0.5)
    _write_report(candidate, 0.5)

    result = _COMPARATOR.compare_runs(
        baseline, candidate, require_reports=True, require_mode_pair=True
    )

    assert result["report_semantics"]["baseline"]["valid"] is True
    assert result["report_semantics"]["semantic_payloads_equal"] is True
    assert result["report_semantics"]["semantic_digests_equal"] is True
    assert result["strict_equal"] is True


def test_required_panel_pair_compares_all_six_csv_files_exactly(tmp_path: Path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline)
    _write_run(candidate)
    _write_panel(baseline)
    _write_panel(candidate)

    result = _COMPARATOR.compare_runs(baseline, candidate, require_panel_pair=True)

    assert result["panel_pair"]["equal"] is True
    assert result["strict_equal"] is True


@pytest.mark.parametrize("defect", ("missing", "extra", "nested", "content"))
def test_required_panel_pair_rejects_missing_extra_or_changed_csv(tmp_path: Path, defect: str):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline)
    _write_run(candidate)
    _write_panel(baseline)
    _write_panel(candidate)
    if defect == "missing":
        (candidate / "panel" / "groups.csv").unlink()
    elif defect == "extra":
        (candidate / "panel" / "extra.csv").write_text("x\n1\n", encoding="utf-8")
    elif defect == "nested":
        (candidate / "panel" / "nested").mkdir()
    else:
        (candidate / "panel" / "groups.csv").write_text("name,value\nA,2\n", encoding="utf-8")

    result = _COMPARATOR.compare_runs(baseline, candidate, require_panel_pair=True)

    assert result["panel_pair"]["equal"] is False
    assert result["strict_equal"] is False


def test_alpha003_mode_pair_compares_complete_keyed_ordered_outputs_and_nan_masks(tmp_path: Path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_alpha003_run(baseline, "native")
    _write_alpha003_run(candidate, "build")

    result = _COMPARATOR.compare_runs(baseline, candidate, require_mode_pair=True)

    assert result["factor_order"]["same_order"] is True
    assert result["summary_shape"]["details"]["baseline"]["actual_finite"] == 3
    assert result["tables"]["factor_values.csv"]["semantic_equal"] is True
    assert result["tables"]["factor_values.csv"]["ordering_equal"] is True
    assert result["strict_equal"] is True


@pytest.mark.parametrize(
    ("broker", "remove_broker"),
    (
        (None, True),
        ({"submit": 1, "cancel": 0}, False),
        ({"submit": False, "cancel": 0}, False),
        ({"submit": 0}, False),
    ),
)
def test_alpha003_mode_pair_requires_actual_zero_broker_counts(
    tmp_path: Path, broker: Mapping[str, Any] | None, remove_broker: bool
):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_alpha003_run(baseline, "native")
    _write_alpha003_run(candidate, "build")
    summary_path = candidate / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if remove_broker:
        summary.pop("broker")
    else:
        summary["broker"] = broker
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    result = _COMPARATOR.compare_runs(baseline, candidate, require_mode_pair=True)

    assert result["mode_pair"]["candidate"]["valid"] is False
    assert any(
        "broker submit/cancel counts must both be zero" in error
        for error in result["mode_pair"]["candidate"]["errors"]
    )
    assert result["strict_equal"] is False


@pytest.mark.parametrize("defect", ("missing_row", "duplicate_key", "reordered", "nan_mask"))
def test_alpha003_mode_pair_rejects_incomplete_or_different_factor_rows(
    tmp_path: Path, defect: str
):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    rows = [
        {"time": TIME, "asset": "ASSET_A", "alpha003": "1.0"},
        {"time": TIME, "asset": "ASSET_B", "alpha003": "NaN"},
        {"time": "2025-01-03T00:00:00+00:00", "asset": "ASSET_A", "alpha003": "2.0"},
        {"time": "2025-01-03T00:00:00+00:00", "asset": "ASSET_B", "alpha003": "3.0"},
    ]
    _write_alpha003_run(baseline, "native")
    if defect == "missing_row":
        rows = rows[:-1]
    elif defect == "duplicate_key":
        rows = [*rows, dict(rows[0])]
    elif defect == "reordered":
        rows = list(reversed(rows))
    elif defect == "nan_mask":
        rows[0] = {**rows[0], "alpha003": "NaN"}
    _write_alpha003_run(candidate, "build", rows=rows)

    result = _COMPARATOR.compare_runs(baseline, candidate, require_mode_pair=True)

    assert result["strict_equal"] is False
    if defect == "reordered":
        assert result["tables"]["factor_values.csv"]["semantic_equal"] is True
        assert result["ordering_equal"] is False
    if defect == "duplicate_key":
        assert result["tables"]["factor_values.csv"]["candidate"]["duplicate_keys"] == 1


def test_alpha003_shared_infinity_is_invalid_even_with_matching_mode_outputs(tmp_path: Path):
    rows = [
        {"time": TIME, "asset": "ASSET_A", "alpha003": "1.0"},
        {"time": TIME, "asset": "ASSET_B", "alpha003": "inf"},
        {"time": "2025-01-03T00:00:00+00:00", "asset": "ASSET_A", "alpha003": "2.0"},
        {"time": "2025-01-03T00:00:00+00:00", "asset": "ASSET_B", "alpha003": "3.0"},
    ]
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_alpha003_run(baseline, "native", rows=rows)
    _write_alpha003_run(candidate, "build", rows=rows)

    result = _COMPARATOR.compare_runs(baseline, candidate, require_mode_pair=True)

    assert result["tables"]["factor_values.csv"]["semantic_equal"] is False
    assert result["tables"]["factor_values.csv"]["baseline"]["error"] == (
        "infinite Alpha003 values are invalid: 1"
    )
    assert result["strict_equal"] is False


def test_alpha003_report_mode_pair_uses_same_report_contract(tmp_path: Path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_alpha003_run(baseline, "native", report=True)
    _write_alpha003_run(candidate, "build", report=True)

    result = _COMPARATOR.compare_runs(
        baseline, candidate, require_mode_pair=True, require_reports=True
    )

    assert result["report_semantics"]["equal"] is True
    assert result["strict_equal"] is True


def test_cli_forwards_all_strict_contract_flags(monkeypatch, tmp_path: Path, capsys):
    captured = {}

    def fake_compare(baseline, candidate, **kwargs):
        captured.update(kwargs)
        return {"strict_equal": False}

    monkeypatch.setattr(_COMPARATOR, "compare_runs", fake_compare)
    code = _COMPARATOR.main(
        [
            str(tmp_path / "baseline"),
            str(tmp_path / "candidate"),
            "--require-reports",
            "--require-mode-pair",
            "--require-panel-pair",
        ]
    )

    assert code == 1
    assert captured == {
        "require_reports": True,
        "require_mode_pair": True,
        "require_panel_pair": True,
    }
    assert '"strict_equal": false' in capsys.readouterr().out
