"""Small contracts for the uninstrumented native-collection pair runner."""

from __future__ import annotations

import csv
from pathlib import Path

from scripts.benchmark_factor_collection_pair import (
    _alternating_order,
    _check_worker_provenance,
    _compare_factor_csvs,
    _median_gate,
    _parser,
    _timing_summary,
)


def test_pair_order_alternates_and_uses_fresh_baseline_candidate_labels() -> None:
    assert _alternating_order(1) == ("baseline", "candidate")
    assert _alternating_order(2) == ("candidate", "baseline")


def test_timing_summary_keeps_median_and_observed_range() -> None:
    summary = _timing_summary([4.0, 1.0, 3.0])

    assert summary["count"] == 3
    assert summary["median_s"] == 3.0
    assert summary["min_s"] == 1.0
    assert summary["max_s"] == 4.0
    assert summary["range_s"] == 3.0
    assert summary["raw_s"] == [4.0, 1.0, 3.0]


def test_50_percent_gate_uses_wall_median_and_records_cpu_without_a_gate() -> None:
    records = []
    for side, values in (
        ("baseline", ((10.0, 8.0), (12.0, 9.0), (11.0, 10.0))),
        ("candidate", ((5.0, 12.0), (4.0, 10.0), (6.0, 14.0))),
    ):
        for wall_s, cpu_s in values:
            records.append(
                {
                    "side": side,
                    "collection_and_panel_timing": {
                        "wall_s": wall_s,
                        "process_cpu_s": cpu_s,
                    },
                }
            )

    summary = _median_gate(records)

    assert summary["wall_s"]["candidate_over_baseline_median"] <= 0.5
    assert summary["wall_s"]["gate_applied"] is True
    assert summary["process_cpu_s"]["candidate_over_baseline_median"] > 0.5
    assert summary["process_cpu_s"]["candidate"]["median_s"] == 12.0
    assert summary["process_cpu_s"]["gate_applied"] is False
    assert summary["process_cpu_s"]["median_50_percent_gate"] is None
    assert summary["pass"] is True


def test_factor_parity_compares_time_asset_keys_and_finite_values(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.csv"
    candidate = tmp_path / "candidate.csv"
    rows = [
        {"time": "2025-01-02T00:00:00+00:00", "asset": "AAA", "close_ma": "1.0"},
        {"time": "2025-01-03T00:00:00+00:00", "asset": "AAA", "close_ma": ""},
    ]
    for path, values in ((baseline, rows), (candidate, rows)):
        with path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=("time", "asset", "close_ma"))
            writer.writeheader()
            writer.writerows(values)

    comparison = _compare_factor_csvs(baseline, candidate)

    assert comparison["status"] == "OK"
    assert comparison["comparison_key"] == ["time", "asset"]
    assert comparison["rows_compared"] == 2
    assert comparison["finite_values_compared"] == 1


def test_worker_parser_accepts_the_minimal_fresh_process_contract() -> None:
    args = _parser().parse_args(
        [
            "--_worker",
            "--root",
            "/checkout",
            "--side",
            "baseline",
            "--example",
            "025",
            "--data-dir",
            "/data",
            "--symbols",
            "500",
            "--work-dir",
            "/tmp/run",
        ]
    )

    assert args._worker is True
    assert args.symbols == 500
    assert args.runnext is False


def test_worker_provenance_does_not_treat_missing_hashes_as_matching() -> None:
    result = {"status": "OK"}
    checked = _check_worker_provenance(
        result,
        side_metadata={"effective_config_sha256": {}},
        example="025",
        input_manifest={},
    )

    assert checked["status"] == "FAILED"
    assert checked["worker_provenance_checks"]["effective_config_matches_preflight"] is False
    assert checked["worker_provenance_checks"]["input_hashes_match_parent_inventory"] is False
