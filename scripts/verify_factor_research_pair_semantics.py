#!/usr/bin/env python
"""Strict, keyed comparison of paired native-factor outputs without pandas."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import itertools
import json
import math
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


TABLE_CONTRACTS: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    "labels.csv": (("time", "asset", "period"), ("value",)),
    "coverage.csv": (
        ("factor", "kind", "direction"),
        ("input_cells", "finite_cells", "label_cells", "evaluable_cells", "status"),
    ),
    "correlation.csv": (
        ("factor_left", "factor_right"),
        ("mean_correlation", "std_correlation", "n_dates"),
    ),
    "stability.csv": (
        ("factor", "lag"),
        ("mean_rank_autocorrelation", "std_rank_autocorrelation", "n_dates"),
    ),
    "ic.csv": (("time", "factor", "period"), ("ic", "rank_ic", "n_assets")),
    "diagnostics.csv": (
        ("factor", "stage", "severity", "code", "message"),
        (),
    ),
    "turnover.csv": (
        ("time", "factor", "period", "quantile"),
        ("turnover",),
    ),
    "comparisons.csv": (
        ("comparison", "left", "right", "period"),
        (
            "mean_ic",
            "icir",
            "mean_ic_left",
            "mean_ic_right",
            "icir_left",
            "icir_right",
            "n_dates_left",
            "n_dates_right",
        ),
    ),
    "signals.csv": (
        ("time", "asset", "factor", "direction"),
        ("value", "processed_value", "preprocess", "group"),
    ),
    "ic_summary.csv": (
        ("factor", "period"),
        (
            "mean_ic",
            "std_ic",
            "icir",
            "mean_rank_ic",
            "std_rank_ic",
            "rank_icir",
            "n_dates",
        ),
    ),
    "spreads.csv": (
        ("time", "factor", "period"),
        ("spread", "top_quantile", "bottom_quantile"),
    ),
    "quantile_returns.csv": (
        ("time", "factor", "period", "quantile"),
        ("mean_return", "n_assets"),
    ),
}

FACTOR_VALUE_KEYS = ("time", "asset")
TEXT_VALUE_FIELDS = {"status", "preprocess", "group"}
MAX_SAMPLES = 8
SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


class ComparisonError(ValueError):
    """An input directory does not satisfy the paired-output contract."""


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ComparisonError("cannot read JSON %s: %s" % (path, exc)) from exc
    if not isinstance(value, Mapping):
        raise ComparisonError("JSON root must be an object: %s" % path)
    return value


def _evaluation_directory(run_dir: Path) -> Tuple[Path, Mapping[str, Any], Mapping[str, Any]]:
    summary = _load_json(run_dir / "summary.json")
    evaluation_id = summary.get("evaluation_id")
    if not isinstance(evaluation_id, str) or not evaluation_id:
        raise ComparisonError("summary has no evaluation_id: %s" % run_dir)
    evaluation_dir = run_dir / "evaluation" / evaluation_id
    manifest = _load_json(evaluation_dir / "manifest.json")
    if manifest.get("evaluation_id") != evaluation_id:
        raise ComparisonError("evaluation manifest id does not match summary: %s" % evaluation_dir)
    return evaluation_dir, summary, manifest


def _normalize_key(field: str, value: str) -> str:
    if field != "time" or not value:
        return value
    timestamp_text = value.replace("Z", "+00:00")
    try:
        timestamp = dt.datetime.fromisoformat(timestamp_text)
    except ValueError:
        return value
    if timestamp.tzinfo is not None:
        timestamp = timestamp.astimezone(dt.timezone.utc)
    return timestamp.isoformat()


def _typed_cell(field: str, value: Optional[str], numeric_fields: Sequence[str]) -> List[Any]:
    raw = "" if value is None else value
    if field not in numeric_fields:
        return ["text", raw]
    stripped = raw.strip()
    if not stripped or stripped.lower() in {"nan", "+nan", "-nan"}:
        return ["nan", None]
    try:
        number = float(stripped)
    except ValueError:
        return ["invalid_numeric", raw]
    if math.isnan(number):
        return ["nan", None]
    if math.isinf(number):
        return ["positive_infinity" if number > 0 else "negative_infinity", None]
    return ["finite", number.hex()]


def _read_header(path: Path) -> List[str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source)
            header = next(reader)
    except (OSError, StopIteration, csv.Error) as exc:
        raise ComparisonError("cannot read CSV header %s: %s" % (path, exc)) from exc
    if not header or len(set(header)) != len(header):
        raise ComparisonError("CSV header is empty or has duplicate columns: %s" % path)
    return header


def _insert_table(
    connection: sqlite3.Connection,
    path: Path,
    table_name: str,
    side: str,
    key_fields: Sequence[str],
    value_fields: Sequence[str],
    numeric_fields: Sequence[str],
    expected_fields: Optional[Sequence[str]] = None,
    unordered_pair: bool = False,
) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {
        "path": str(path),
        "header": [],
        "row_count": 0,
        "duplicate_keys": 0,
        "mask_counts": {},
        "error": None,
    }
    if not path.is_file():
        metadata["error"] = "missing CSV"
        return metadata
    try:
        header = _read_header(path)
        metadata["header"] = header
        if expected_fields is not None and set(header) != set(expected_fields):
            metadata["error"] = "CSV columns differ from required schema"
            return metadata
        missing = set(key_fields) - set(header)
        missing_values = set(value_fields) - set(header)
        if missing or missing_values:
            metadata["error"] = "missing required columns: %s" % sorted(missing | missing_values)
            return metadata

        counters: Dict[str, Dict[str, int]] = {
            field: {"finite": 0, "nan": 0, "positive_infinity": 0,
                    "negative_infinity": 0, "invalid_numeric": 0}
            for field in numeric_fields
        }
        record_insert = (
            "INSERT OR IGNORE INTO semantic_rows "
            "(table_name, side, key_json, payload_json, orientation_json) VALUES (?, ?, ?, ?, ?)"
        )
        order_insert = (
            "INSERT INTO row_order (table_name, side, seq, key_json) VALUES (?, ?, ?, ?)"
        )
        record_batch = []
        order_batch = []

        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames != header:
                raise ComparisonError("CSV header changed while reading: %s" % path)
            for sequence, row in enumerate(reader):
                key_values = [_normalize_key(field, row.get(field, "")) for field in key_fields]
                if unordered_pair:
                    key_values = sorted(key_values)
                    orientation = [
                        _normalize_key("factor", row.get("factor_left", "")),
                        _normalize_key("factor", row.get("factor_right", "")),
                    ]
                else:
                    orientation = None
                key_json = json.dumps(key_values, ensure_ascii=True, separators=(",", ":"))
                payload = {
                    field: _typed_cell(field, row.get(field), numeric_fields)
                    for field in value_fields
                }
                for field, cell in payload.items():
                    if field in counters:
                        counters[field][cell[0]] = counters[field].get(cell[0], 0) + 1
                payload_json = json.dumps(payload, ensure_ascii=True, sort_keys=True,
                                          separators=(",", ":"))
                orientation_json = (
                    None if orientation is None else json.dumps(orientation, separators=(",", ":"))
                )
                record_batch.append((table_name, side, key_json, payload_json, orientation_json))
                order_batch.append((table_name, side, sequence, key_json))
                if len(record_batch) >= 5000:
                    before = connection.total_changes
                    connection.executemany(record_insert, record_batch)
                    inserted = connection.total_changes - before
                    metadata["duplicate_keys"] += len(record_batch) - inserted
                    connection.executemany(order_insert, order_batch)
                    record_batch.clear()
                    order_batch.clear()
                metadata["row_count"] += 1
            if record_batch:
                before = connection.total_changes
                connection.executemany(record_insert, record_batch)
                inserted = connection.total_changes - before
                metadata["duplicate_keys"] += len(record_batch) - inserted
                connection.executemany(order_insert, order_batch)
        metadata["mask_counts"] = counters
        invalid_numeric = {
            field: counts["invalid_numeric"]
            for field, counts in counters.items()
            if counts["invalid_numeric"]
        }
        if invalid_numeric:
            metadata["error"] = "invalid numeric values: %s" % invalid_numeric
        connection.commit()
    except (OSError, csv.Error, KeyError, sqlite3.Error, ComparisonError) as exc:
        metadata["error"] = "%s: %s" % (type(exc).__name__, exc)
        connection.rollback()
    return metadata


def _compare_payloads(
    left_json: str, right_json: str
) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
    left = json.loads(left_json)
    right = json.loads(right_json)
    mismatches: Dict[str, int] = {}
    samples: List[Dict[str, Any]] = []
    fields = sorted(set(left) | set(right))
    for field in fields:
        left_value = left.get(field, ["missing", None])
        right_value = right.get(field, ["missing", None])
        if left_value != right_value:
            mismatches[field] = mismatches.get(field, 0) + 1
            if len(samples) < MAX_SAMPLES:
                samples.append({"field": field, "baseline": left_value, "candidate": right_value})
    return mismatches, samples


def _compare_semantic_rows(
    connection: sqlite3.Connection, table_name: str
) -> Dict[str, Any]:
    left_cursor = connection.execute(
        "SELECT key_json, payload_json, orientation_json FROM semantic_rows "
        "WHERE table_name = ? AND side = 'baseline' ORDER BY key_json",
        (table_name,),
    )
    right_cursor = connection.execute(
        "SELECT key_json, payload_json, orientation_json FROM semantic_rows "
        "WHERE table_name = ? AND side = 'candidate' ORDER BY key_json",
        (table_name,),
    )
    left_item = left_cursor.fetchone()
    right_item = right_cursor.fetchone()
    missing_in_candidate = 0
    extra_in_candidate = 0
    missing_samples: List[str] = []
    extra_samples: List[str] = []
    value_mismatches: Dict[str, int] = {}
    value_samples: List[Dict[str, Any]] = []
    orientation_mismatches = 0
    orientation_samples: List[Dict[str, Any]] = []

    while left_item is not None or right_item is not None:
        if right_item is None or (left_item is not None and left_item[0] < right_item[0]):
            missing_in_candidate += 1
            if len(missing_samples) < MAX_SAMPLES:
                missing_samples.append(left_item[0])
            left_item = left_cursor.fetchone()
            continue
        if left_item is None or right_item[0] < left_item[0]:
            extra_in_candidate += 1
            if len(extra_samples) < MAX_SAMPLES:
                extra_samples.append(right_item[0])
            right_item = right_cursor.fetchone()
            continue

        field_counts, samples = _compare_payloads(left_item[1], right_item[1])
        for field, count in field_counts.items():
            value_mismatches[field] = value_mismatches.get(field, 0) + count
        for sample in samples:
            if len(value_samples) < MAX_SAMPLES:
                value_samples.append({"key": left_item[0], **sample})
        if left_item[2] != right_item[2]:
            orientation_mismatches += 1
            if len(orientation_samples) < MAX_SAMPLES:
                orientation_samples.append(
                    {"key": left_item[0], "baseline": left_item[2], "candidate": right_item[2]}
                )
        left_item = left_cursor.fetchone()
        right_item = right_cursor.fetchone()

    return {
        "missing_in_candidate": missing_in_candidate,
        "extra_in_candidate": extra_in_candidate,
        "missing_key_samples": missing_samples,
        "extra_key_samples": extra_samples,
        "value_mismatches_by_field": value_mismatches,
        "value_mismatch_samples": value_samples,
        "unordered_pair_orientation_mismatches": orientation_mismatches,
        "orientation_samples": orientation_samples,
        "semantic_equal": not (
            missing_in_candidate or extra_in_candidate or value_mismatches
        ),
    }


def _compare_row_order(
    connection: sqlite3.Connection, table_name: str
) -> Dict[str, Any]:
    left = connection.execute(
        "SELECT key_json FROM row_order WHERE table_name = ? AND side = 'baseline' ORDER BY seq",
        (table_name,),
    )
    right = connection.execute(
        "SELECT key_json FROM row_order WHERE table_name = ? AND side = 'candidate' ORDER BY seq",
        (table_name,),
    )
    mismatch_positions = 0
    first_mismatch: Optional[Dict[str, Any]] = None
    for position, pair in enumerate(itertools.zip_longest(left, right)):
        left_row, right_row = pair
        left_key = None if left_row is None else left_row[0]
        right_key = None if right_row is None else right_row[0]
        if left_key != right_key:
            mismatch_positions += 1
            if first_mismatch is None:
                first_mismatch = {
                    "position": position,
                    "baseline": left_key,
                    "candidate": right_key,
                }
    return {
        "same": mismatch_positions == 0,
        "mismatch_positions": mismatch_positions,
        "first_mismatch": first_mismatch,
    }


def compare_runs(baseline_dir: Path, candidate_dir: Path) -> Dict[str, Any]:
    baseline_dir = baseline_dir.expanduser().resolve()
    candidate_dir = candidate_dir.expanduser().resolve()
    baseline_eval, baseline_summary, baseline_manifest = _evaluation_directory(baseline_dir)
    candidate_eval, candidate_summary, candidate_manifest = _evaluation_directory(candidate_dir)
    baseline_header_path = baseline_dir / "factor_values.csv"
    candidate_header_path = candidate_dir / "factor_values.csv"
    baseline_factor_header = _read_header(baseline_header_path)
    candidate_factor_header = _read_header(candidate_header_path)
    baseline_factors = [field for field in baseline_factor_header if field not in FACTOR_VALUE_KEYS]
    candidate_factors = [
        field for field in candidate_factor_header if field not in FACTOR_VALUE_KEYS
    ]
    if not baseline_factors or not candidate_factors:
        raise ComparisonError("factor_values.csv must contain factor columns")

    connections: List[sqlite3.Connection] = []
    try:
        with tempfile.TemporaryDirectory(prefix="factor-pair-semantic-") as scratch:
            db_path = Path(scratch) / "semantic.sqlite3"
            connection = sqlite3.connect(str(db_path))
            connections.append(connection)
            connection.executescript(
                "CREATE TABLE semantic_rows ("
                "table_name TEXT NOT NULL, side TEXT NOT NULL, key_json TEXT NOT NULL, "
                "payload_json TEXT NOT NULL, orientation_json TEXT, "
                "PRIMARY KEY(table_name, side, key_json));"
                "CREATE TABLE row_order ("
                "table_name TEXT NOT NULL, side TEXT NOT NULL, seq INTEGER NOT NULL, "
                "key_json TEXT NOT NULL, PRIMARY KEY(table_name, side, seq));"
            )

            metadata: Dict[str, Dict[str, Dict[str, Any]]] = {"baseline": {}, "candidate": {}}
            for side, run_dir, evaluation_dir, factors in (
                ("baseline", baseline_dir, baseline_eval, baseline_factors),
                ("candidate", candidate_dir, candidate_eval, candidate_factors),
            ):
                factor_expected = tuple(FACTOR_VALUE_KEYS) + tuple(factors)
                metadata[side]["factor_values.csv"] = _insert_table(
                    connection,
                    run_dir / "factor_values.csv",
                    "factor_values.csv",
                    side,
                    FACTOR_VALUE_KEYS,
                    factors,
                    factors,
                    expected_fields=factor_expected,
                )
                metadata[side]["factor_values.csv"]["header"] = _read_header(
                    run_dir / "factor_values.csv"
                )
                for filename, (key_fields, value_fields) in TABLE_CONTRACTS.items():
                    fields = tuple(key_fields) + tuple(value_fields)
                    if filename == "diagnostics.csv":
                        fields = tuple(key_fields)
                    metadata[side][filename] = _insert_table(
                        connection,
                        evaluation_dir / filename,
                        filename,
                        side,
                        key_fields,
                        value_fields,
                        tuple(field for field in value_fields if field not in TEXT_VALUE_FIELDS),
                        expected_fields=fields,
                        unordered_pair=filename == "correlation.csv",
                    )
                    if (
                        filename != "diagnostics.csv"
                        and metadata[side][filename]["row_count"] == 0
                        and metadata[side][filename]["error"] is None
                    ):
                        metadata[side][filename]["error"] = "table has no data rows"

            table_results: Dict[str, Dict[str, Any]] = {}
            semantic_equal = True
            ordering_equal = baseline_factor_header == candidate_factor_header
            for table_name in ("factor_values.csv", *TABLE_CONTRACTS):
                left_meta = metadata["baseline"][table_name]
                right_meta = metadata["candidate"][table_name]
                keyed = _compare_semantic_rows(connection, table_name)
                row_order = _compare_row_order(connection, table_name)
                header_equal = left_meta["header"] == right_meta["header"]
                header_set_equal = set(left_meta["header"]) == set(right_meta["header"])
                table_semantic_equal = (
                    keyed["semantic_equal"]
                    and left_meta["error"] is None
                    and right_meta["error"] is None
                    and header_set_equal
                    and not left_meta["duplicate_keys"]
                    and not right_meta["duplicate_keys"]
                )
                table_order_equal = (
                    header_equal
                    and row_order["same"]
                    and keyed["unordered_pair_orientation_mismatches"] == 0
                )
                left_rows = left_meta["row_count"]
                right_rows = right_meta["row_count"]
                table_results[table_name] = {
                    "baseline": left_meta,
                    "candidate": right_meta,
                    "rows_equal_count": left_rows == right_rows,
                    "keyed": keyed,
                    "row_order": row_order,
                    "header_order_equal": header_equal,
                    "header_set_equal": header_set_equal,
                    "semantic_equal": table_semantic_equal,
                    "ordering_equal": table_order_equal,
                }
                semantic_equal = semantic_equal and table_semantic_equal
                ordering_equal = ordering_equal and table_order_equal

            fingerprint_left = baseline_manifest.get("result_fingerprint")
            fingerprint_right = candidate_manifest.get("result_fingerprint")
            baseline_state = {
                "run": baseline_summary.get("status"),
                "evaluation": baseline_summary.get("evaluation_status"),
            }
            candidate_state = {
                "run": candidate_summary.get("status"),
                "evaluation": candidate_summary.get("evaluation_status"),
            }
            run_states_valid = all(
                state["run"] == "COMPLETED" and state["evaluation"] == "OK"
                for state in (baseline_state, candidate_state)
            )
            run_states_equal = baseline_state == candidate_state
            run_state_acceptable = run_states_valid and run_states_equal
            fingerprints_valid = all(
                isinstance(value, str) and SHA256_HEX_RE.fullmatch(value) is not None
                for value in (fingerprint_left, fingerprint_right)
            )
            fingerprints_equal = (
                fingerprints_valid and fingerprint_left.lower() == fingerprint_right.lower()
            )
            summary_shape = {
                "baseline": {
                    "symbols": baseline_summary.get("symbols"),
                    "dates": baseline_summary.get("dates"),
                },
                "candidate": {
                    "symbols": candidate_summary.get("symbols"),
                    "dates": candidate_summary.get("dates"),
                },
            }
            summary_shape_valid = all(
                type(value) is int and value > 0
                for shape in summary_shape.values()
                for value in shape.values()
            )
            summary_shape_equal = summary_shape["baseline"] == summary_shape["candidate"]
            factor_rows_match_summary = {
                side: (
                    metadata[side]["factor_values.csv"]["row_count"]
                    == summary_shape[side]["symbols"] * summary_shape[side]["dates"]
                    if summary_shape_valid
                    else False
                )
                for side in ("baseline", "candidate")
            }
            factor_row_counts_valid = all(factor_rows_match_summary.values())
            strict_equal = (
                semantic_equal
                and ordering_equal
                and fingerprints_valid
                and fingerprints_equal
                and run_state_acceptable
                and summary_shape_valid
                and summary_shape_equal
                and factor_row_counts_valid
            )
            return {
                "schema_version": "factor-research-pair-semantic-v1",
                "baseline_run": str(baseline_dir),
                "candidate_run": str(candidate_dir),
                "factor_order": {
                    "baseline": baseline_factors,
                    "candidate": candidate_factors,
                    "same_set": set(baseline_factors) == set(candidate_factors),
                    "same_order": baseline_factors == candidate_factors,
                },
                "fingerprints": {
                    "baseline": fingerprint_left,
                    "candidate": fingerprint_right,
                    "valid": fingerprints_valid,
                    "equal": fingerprints_equal,
                },
                "run_status": {
                    "baseline": baseline_state["run"],
                    "candidate": candidate_state["run"],
                    "baseline_evaluation": baseline_state["evaluation"],
                    "candidate_evaluation": candidate_state["evaluation"],
                    "valid": run_states_valid,
                    "equal": run_states_equal,
                    "acceptable": run_state_acceptable,
                },
                "summary_shape": {
                    **summary_shape,
                    "valid": summary_shape_valid,
                    "equal": summary_shape_equal,
                    "factor_value_rows_match_symbols_x_dates": factor_rows_match_summary,
                    "factor_row_counts_valid": factor_row_counts_valid,
                },
                "tables": table_results,
                "semantic_equal_ignoring_row_and_column_order": semantic_equal,
                "ordering_equal": ordering_equal,
                "strict_equal": strict_equal,
                "tables_equal_ignoring_order": semantic_equal,
                "only_observed_difference_is_ordering": (
                    semantic_equal
                    and not ordering_equal
                    and fingerprints_equal
                    and run_state_acceptable
                    and summary_shape_valid
                    and summary_shape_equal
                    and factor_row_counts_valid
                ),
                "order_and_fingerprint_differ_with_equal_tables": (
                    semantic_equal
                    and not ordering_equal
                    and fingerprints_valid
                    and not fingerprints_equal
                    and run_state_acceptable
                    and summary_shape_valid
                    and summary_shape_equal
                    and factor_row_counts_valid
                ),
                "status": (
                    "IDENTICAL"
                    if strict_equal
                    else "INVALID_RUN_STATE"
                    if not run_states_valid
                    else "RUN_STATE_DIFFERENCES"
                    if not run_states_equal
                    else "INVALID_SUMMARY_SHAPE"
                    if not summary_shape_valid or not factor_row_counts_valid
                    else "SUMMARY_SHAPE_DIFFERENCES"
                    if not summary_shape_equal
                    else "INVALID_FINGERPRINT"
                    if not fingerprints_valid
                    else "ORDER_ONLY_DIFFERENCES"
                    if semantic_equal and not ordering_equal and fingerprints_equal
                    else "ORDER_AND_FINGERPRINT_DIFFERENCES"
                    if semantic_equal and not ordering_equal and not fingerprints_equal
                    else "FINGERPRINT_DIFFERENCE"
                    if semantic_equal and ordering_equal and fingerprints_valid and not fingerprints_equal
                    else "SEMANTIC_DIFFERENCES"
                ),
            }
    finally:
        for connection in connections:
            connection.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_run", type=Path)
    parser.add_argument("candidate_run", type=Path)
    parser.add_argument("--output", type=Path, help="write the JSON result to this new file")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = compare_runs(args.baseline_run, args.candidate_run)
    except ComparisonError as exc:
        print("COMPARISON_ERROR: %s" % exc, file=sys.stderr)
        return 2
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(rendered)
    else:
        output = args.output.expanduser().resolve()
        if output.exists():
            print("COMPARISON_ERROR: output already exists: %s" % output, file=sys.stderr)
            return 2
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print("results: %s" % output)
    return 0 if result["strict_equal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
