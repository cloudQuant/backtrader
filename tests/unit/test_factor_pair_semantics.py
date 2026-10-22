"""Keyed semantic checks for paired FactorPanel research outputs."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
from typing import Dict, Iterable, Mapping, Sequence

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "verify_factor_research_pair_semantics.py"
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
            else "cross_section_rank"
            if field == "preprocess"
            else "all_symbols"
            if field == "group"
            else "0.5"
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
    comparisons = (
        {"ma_vs_equal_weight": {}}
        if spec_comparisons is None
        else dict(spec_comparisons)
    )
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
    ic_fields = (
        _COMPARATOR.TABLE_CONTRACTS["ic.csv"][0]
        + _COMPARATOR.TABLE_CONTRACTS["ic.csv"][1]
    )
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
        _COMPARATOR.TABLE_CONTRACTS["labels.csv"][0]
        + _COMPARATOR.TABLE_CONTRACTS["labels.csv"][1]
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
