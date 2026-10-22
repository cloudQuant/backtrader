#!/usr/bin/env python
"""Strict, keyed comparison of paired native-factor outputs without pandas."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import importlib
import itertools
import json
import math
import re
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

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
REPORT_SEMANTICS_FILENAME = "report_semantics.json"
REPORT_SEMANTICS_SCHEMA = "factor-report-semantics-v1"
PANEL_CSV_FILES = frozenset(
    {
        "factors.csv",
        "grid.csv",
        "groups.csv",
        "prices_close.csv",
        "prices_open.csv",
        "universe.csv",
    }
)


class ComparisonError(ValueError):
    """An input directory does not satisfy the paired-output contract."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _payload_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@contextmanager
def capture_report_semantics(output_dir: Path) -> Iterator[List[Dict[str, Any]]]:
    """Capture the actual ReportDocument passed to fincore's HTML writer.

    The example owns creation of ``output_dir``. This context never creates it,
    and publishes the sidecar only after the wrapped report run exits normally.
    """

    root = Path(output_dir).expanduser().resolve()
    html_module = importlib.import_module("fincore.report.factor.html")
    original_writer = html_module.write_factor_html
    captured: List[Dict[str, Any]] = []
    sidecar = root / REPORT_SEMANTICS_FILENAME

    def wrapped_writer(document: Any, target: Any, *args: Any, **kwargs: Any) -> Any:
        result = original_writer(document, target, *args, **kwargs)
        html_path = Path(result).expanduser().resolve()
        try:
            relative_html_path = html_path.relative_to(root).as_posix()
        except ValueError as exc:
            raise ComparisonError(
                "factor report is outside output directory: %s" % html_path
            ) from exc
        if not html_path.is_file():
            raise ComparisonError("factor report writer did not create %s" % html_path)
        payload = document.semantic_payload()
        digest = document.semantic_digest
        if not isinstance(payload, Mapping) or not isinstance(digest, str):
            raise ComparisonError("ReportDocument semantic payload or digest has an invalid type")
        payload_copy = json.loads(_canonical_json(payload))
        payload_digest = _payload_digest(payload_copy)
        if digest.lower() != payload_digest:
            raise ComparisonError("ReportDocument semantic digest does not match its payload")
        captured.append(
            {
                "html_path": relative_html_path,
                "html_sha256": hashlib.sha256(html_path.read_bytes()).hexdigest(),
                "semantic_payload": payload_copy,
                "semantic_digest": digest.lower(),
            }
        )
        return result

    if sidecar.exists():
        raise ComparisonError("report semantics sidecar already exists: %s" % sidecar)
    html_module.write_factor_html = wrapped_writer
    try:
        yield captured
    except BaseException:
        raise
    else:
        if captured:
            rendered = (
                json.dumps(
                    {"schema_version": REPORT_SEMANTICS_SCHEMA, "reports": captured},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
            created = False
            try:
                with sidecar.open("x", encoding="utf-8") as stream:
                    created = True
                    stream.write(rendered)
            except BaseException:
                if created:
                    sidecar.unlink(missing_ok=True)
                raise
    finally:
        html_module.write_factor_html = original_writer


def _manifest_declares_empty_table(
    manifest: Mapping[str, Any], table_name: str, expected_fields: Sequence[str]
) -> bool:
    tables = manifest.get("tables")
    table_key = table_name[:-4] if table_name.endswith(".csv") else table_name
    entry = tables.get(table_key) if isinstance(tables, Mapping) else None
    return (
        isinstance(entry, Mapping)
        and type(entry.get("rows")) is int
        and entry["rows"] == 0
        and entry.get("columns") == list(expected_fields)
    )


def _empty_table_is_contractual(
    table_name: str,
    manifest: Mapping[str, Any],
    factor_count: int,
    expected_fields: Sequence[str],
) -> bool:
    if not _manifest_declares_empty_table(manifest, table_name, expected_fields):
        return False
    spec = manifest.get("spec")
    if not isinstance(spec, Mapping):
        return False
    if table_name == "comparisons.csv":
        return type(spec.get("comparisons")) is dict and spec["comparisons"] == {}
    if table_name == "correlation.csv":
        counts = manifest.get("counts")
        return (
            factor_count == 1
            and type(spec.get("combinations")) is dict
            and spec["combinations"] == {}
            and isinstance(counts, Mapping)
            and type(counts.get("factors")) is int
            and counts["factors"] == 1
            and type(counts.get("combinations")) is int
            and counts["combinations"] == 0
        )
    return False


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
            field: {
                "finite": 0,
                "nan": 0,
                "positive_infinity": 0,
                "negative_infinity": 0,
                "invalid_numeric": 0,
            }
            for field in numeric_fields
        }
        record_insert = (
            "INSERT OR IGNORE INTO semantic_rows "
            "(table_name, side, key_json, payload_json, orientation_json) VALUES (?, ?, ?, ?, ?)"
        )
        order_insert = "INSERT INTO row_order (table_name, side, seq, key_json) VALUES (?, ?, ?, ?)"
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
                payload_json = json.dumps(
                    payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
                )
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


def _compare_semantic_rows(connection: sqlite3.Connection, table_name: str) -> Dict[str, Any]:
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
        "semantic_equal": not (missing_in_candidate or extra_in_candidate or value_mismatches),
    }


def _compare_row_order(connection: sqlite3.Connection, table_name: str) -> Dict[str, Any]:
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


def _summary_report_paths(summary: Mapping[str, Any], run_dir: Path) -> Tuple[List[str], List[str]]:
    if "reports" in summary:
        raw_reports = summary.get("reports")
        if not isinstance(raw_reports, list):
            return [], ["summary reports must be a list"]
    elif "report" in summary:
        raw_report = summary.get("report")
        raw_reports = [] if raw_report is None else [raw_report]
    else:
        return [], ["summary does not declare report paths"]

    root = run_dir.resolve()
    normalized: List[str] = []
    errors: List[str] = []
    for value in raw_reports:
        if not isinstance(value, str) or not value:
            errors.append("summary report path is not a non-empty string")
            continue
        path = Path(value).expanduser()
        path = path.resolve() if path.is_absolute() else (root / path).resolve()
        try:
            normalized.append(path.relative_to(root).as_posix())
        except ValueError:
            errors.append("summary report path is outside run directory: %s" % value)
    if len(set(normalized)) != len(normalized):
        errors.append("summary contains duplicate report paths")
    return normalized, errors


def _read_report_semantics(run_dir: Path) -> Dict[str, Any]:
    errors: List[str] = []
    sidecar_path = run_dir / REPORT_SEMANTICS_FILENAME
    try:
        sidecar = _load_json(sidecar_path)
    except ComparisonError as exc:
        return {"valid": False, "errors": [str(exc)], "reports": []}
    if sidecar.get("schema_version") != REPORT_SEMANTICS_SCHEMA:
        errors.append("report semantics schema_version is missing or unsupported")
    reports = sidecar.get("reports")
    if not isinstance(reports, list):
        errors.append("report semantics reports must be a list")
        reports = []

    normalized: List[Dict[str, Any]] = []
    seen_paths = set()
    root = run_dir.resolve()
    for index, report in enumerate(reports):
        if not isinstance(report, Mapping):
            errors.append("report semantics item %d must be an object" % index)
            continue
        relative = report.get("html_path")
        if not isinstance(relative, str) or not relative:
            errors.append("report semantics item %d has no html_path" % index)
            continue
        relative_path = Path(relative)
        if relative_path.is_absolute():
            errors.append("report semantics html_path must be relative: %s" % relative)
            continue
        html_path = (root / relative_path).resolve()
        try:
            normalized_path = html_path.relative_to(root).as_posix()
        except ValueError:
            errors.append("report semantics html_path is outside run directory: %s" % relative)
            continue
        if normalized_path in seen_paths:
            errors.append("report semantics contains duplicate html_path: %s" % normalized_path)
        seen_paths.add(normalized_path)

        html_digest = report.get("html_sha256")
        if not isinstance(html_digest, str) or SHA256_HEX_RE.fullmatch(html_digest) is None:
            errors.append("report semantics item %d has an invalid html_sha256" % index)
        elif not html_path.is_file():
            errors.append("captured HTML file is missing: %s" % normalized_path)
        else:
            actual_html_digest = hashlib.sha256(html_path.read_bytes()).hexdigest()
            if actual_html_digest != html_digest.lower():
                errors.append("captured HTML hash does not match: %s" % normalized_path)

        payload = report.get("semantic_payload")
        digest = report.get("semantic_digest")
        payload_text: Optional[str] = None
        if not isinstance(payload, Mapping):
            errors.append("report semantics item %d has no object semantic_payload" % index)
        else:
            try:
                payload_text = _canonical_json(payload)
            except (TypeError, ValueError) as exc:
                errors.append("report semantics item %d has invalid payload: %s" % (index, exc))
        if not isinstance(digest, str) or SHA256_HEX_RE.fullmatch(digest) is None:
            errors.append("report semantics item %d has an invalid semantic_digest" % index)
        elif payload_text is not None:
            actual_payload_digest = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            if actual_payload_digest != digest.lower():
                errors.append("report semantic digest does not match payload: %s" % normalized_path)
        normalized.append(
            {
                "html_path": normalized_path,
                "html_sha256": html_digest.lower() if isinstance(html_digest, str) else None,
                "semantic_payload": payload,
                "semantic_payload_json": payload_text,
                "semantic_digest": digest.lower() if isinstance(digest, str) else None,
            }
        )
    return {"valid": not errors, "errors": errors, "reports": normalized}


def _compare_reports(
    baseline_dir: Path,
    candidate_dir: Path,
    baseline_summary: Mapping[str, Any],
    candidate_summary: Mapping[str, Any],
) -> Dict[str, Any]:
    sides: Dict[str, Dict[str, Any]] = {}
    for side, run_dir, summary in (
        ("baseline", baseline_dir, baseline_summary),
        ("candidate", candidate_dir, candidate_summary),
    ):
        expected_paths, path_errors = _summary_report_paths(summary, run_dir)
        captured = _read_report_semantics(run_dir)
        errors = [*path_errors, *captured["errors"]]
        captured_paths = [report["html_path"] for report in captured["reports"]]
        if not expected_paths:
            errors.append("summary declares no report paths")
        if len(expected_paths) != len(captured_paths):
            errors.append("summary report count does not match captured report count")
        if expected_paths != captured_paths:
            errors.append("summary report paths do not match captured HTML paths")
        sides[side] = {
            "valid": not errors,
            "errors": errors,
            "reports": [
                {
                    "html_path": report["html_path"],
                    "html_sha256": report["html_sha256"],
                    "semantic_digest": report["semantic_digest"],
                }
                for report in captured["reports"]
            ],
            "semantic_payloads": [
                report["semantic_payload_json"] for report in captured["reports"]
            ],
            "semantic_digests": [report["semantic_digest"] for report in captured["reports"]],
        }
    left = sides["baseline"]["semantic_payloads"]
    right = sides["candidate"]["semantic_payloads"]
    payloads_equal = (
        sides["baseline"]["valid"]
        and sides["candidate"]["valid"]
        and left == right
        and sides["baseline"]["semantic_digests"] == sides["candidate"]["semantic_digests"]
    )
    return {
        "required": True,
        "baseline": {
            key: value for key, value in sides["baseline"].items() if key != "semantic_payloads"
        },
        "candidate": {
            key: value for key, value in sides["candidate"].items() if key != "semantic_payloads"
        },
        "semantic_payloads_equal": payloads_equal,
        "semantic_digests_equal": (
            sides["baseline"]["semantic_digests"] == sides["candidate"]["semantic_digests"]
        ),
        "equal": bool(payloads_equal),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compare_panel_pair(baseline_dir: Path, candidate_dir: Path) -> Dict[str, Any]:
    sides: Dict[str, Dict[str, Any]] = {}
    for side, run_dir in (("baseline", baseline_dir), ("candidate", candidate_dir)):
        panel_dir = run_dir / "panel"
        errors: List[str] = []
        if not panel_dir.is_dir():
            files: List[Path] = []
            errors.append("panel directory is missing")
        else:
            entries = sorted(panel_dir.iterdir())
            files = [path for path in entries if path.is_file()]
            names = {path.name for path in files}
            if names != PANEL_CSV_FILES or len(entries) != len(PANEL_CSV_FILES):
                errors.append(
                    "panel must contain exactly six contract CSV files; missing=%s extra=%s"
                    % (
                        sorted(PANEL_CSV_FILES - names),
                        sorted(names - PANEL_CSV_FILES)
                        + [path.name for path in entries if not path.is_file()],
                    )
                )
        hashes = {path.name: _sha256_file(path) for path in files if path.name in PANEL_CSV_FILES}
        sides[side] = {"valid": not errors, "errors": errors, "sha256": hashes}
    equal = (
        sides["baseline"]["valid"]
        and sides["candidate"]["valid"]
        and sides["baseline"]["sha256"] == sides["candidate"]["sha256"]
    )
    return {"required": True, **sides, "equal": bool(equal)}


_SUMMARY_METADATA_KEYS = {
    "factor_mode",
    "factor_calculation",
    "factor_classes",
    "indicator",
    "operator_profile",
    "evaluation_id",
    "run_id",
    "output",
    "output_dir",
    "report",
    "reports",
    "elapsed_seconds",
    "duration_seconds",
    "runtime_seconds",
    "generated_at",
    "started_at",
    "finished_at",
    "source_fingerprint",
    "source_hash",
    "source_path",
}


def _summary_numeric_values(summary: Mapping[str, Any]) -> Dict[str, str]:
    numeric: Dict[str, str] = {}

    def walk(value: Any, prefix: str = "") -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                key_text = str(key)
                folded = key_text.casefold()
                if (
                    folded in _SUMMARY_METADATA_KEYS
                    or "source" in folded
                    or "timestamp" in folded
                    or "elapsed" in folded
                    or "duration" in folded
                    or folded.endswith(("_path", "_file"))
                ):
                    continue
                walk(item, prefix + "." + key_text if prefix else key_text)
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                walk(item, "%s[%d]" % (prefix, index))
        elif type(value) is int:
            numeric[prefix] = "int:%d" % value
        elif type(value) is float:
            numeric[prefix] = (
                "float:%s" % value.hex() if math.isfinite(value) else "float:%s" % value
            )

    walk(summary)
    return numeric


def _mode_contract_for_summary(
    summary: Mapping[str, Any], factor_order: Sequence[str], *, alpha003: bool
) -> Dict[str, Any]:
    mode = summary.get("factor_mode")
    errors: List[str] = []
    if mode not in ("native", "build"):
        errors.append("factor_mode must be native or build")
    if summary.get("status") != "COMPLETED":
        errors.append("run status must be COMPLETED")
    if summary.get("factor_calculation") != "RAN":
        errors.append("factor_calculation must be RAN")

    if alpha003:
        expected = (
            "backtrader.research.alpha101.alpha003.Alpha003Native"
            if mode == "native"
            else "backtrader.research.alpha101.alpha003.Alpha003Build"
        )
        actual = summary.get("indicator")
        if actual != expected:
            errors.append("indicator identity does not match factor_mode")
        broker = summary.get("broker")
        if not isinstance(broker, Mapping) or any(
            type(broker.get(field)) is not int or broker.get(field) != 0
            for field in ("submit", "cancel")
        ):
            errors.append("broker submit/cancel counts must both be zero")
    else:
        if summary.get("evaluation_status") != "OK":
            errors.append("evaluation_status must be OK")
        classes = summary.get("factor_classes")
        if not isinstance(classes, Mapping):
            classes = {}
            errors.append("factor_classes must be an object")
        if tuple(factor_order) == ("close_ma",):
            module = "close_ma_factor_strategy"
            expected_names = ("close_ma",)
        elif tuple(factor_order) == ("close_ma", "kdj_j", "roc"):
            module = "multi_factor_strategy"
            expected_names = ("close_ma", "kdj_j", "roc")
        else:
            module = ""
            expected_names = ()
            errors.append("factor column order is not a supported quick example contract")
        class_names = {
            "close_ma": "CloseMAFactor" if mode == "native" else "CloseMAFactorBuild",
            "kdj_j": "KDJFactor" if mode == "native" else "KDJFactorBuild",
            "roc": "ROCFactor" if mode == "native" else "ROCFactorBuild",
        }
        expected_classes = {
            factor: "%s.%s" % (module, class_names[factor]) for factor in expected_names
        }
        if dict(classes) != expected_classes:
            errors.append("factor_classes identities do not match factor_mode and example")
        if module == "multi_factor_strategy" and tuple(factor_order) != (
            "close_ma",
            "kdj_j",
            "roc",
        ):
            errors.append("026 factor order must be close_ma,kdj_j,roc")
        broker = summary.get("broker")
        if not isinstance(broker, Mapping) or any(
            type(broker.get(field)) is not int or broker.get(field) != 0
            for field in ("submit", "cancel")
        ):
            errors.append("broker submit/cancel counts must both be zero")
    return {"mode": mode, "valid": not errors, "errors": errors}


def _compare_mode_pair(
    baseline_summary: Mapping[str, Any],
    candidate_summary: Mapping[str, Any],
    factor_order: Sequence[str],
    *,
    alpha003: bool,
) -> Dict[str, Any]:
    baseline = _mode_contract_for_summary(baseline_summary, factor_order, alpha003=alpha003)
    candidate = _mode_contract_for_summary(candidate_summary, factor_order, alpha003=alpha003)
    modes_differ = (baseline["mode"], candidate["mode"]) in (
        ("native", "build"),
        ("build", "native"),
    )
    numeric_baseline = _summary_numeric_values(baseline_summary)
    numeric_candidate = _summary_numeric_values(candidate_summary)
    numeric_equal = numeric_baseline == numeric_candidate
    return {
        "required": True,
        "baseline": baseline,
        "candidate": candidate,
        "modes_differ_native_build": modes_differ,
        "summary_numeric_equal": numeric_equal,
        "summary_numeric_values": {
            "baseline": numeric_baseline,
            "candidate": numeric_candidate,
        },
        "valid": baseline["valid"] and candidate["valid"] and modes_differ and numeric_equal,
    }


def _factor_key_dimensions(path: Path) -> Tuple[int, int, List[str]]:
    times = set()
    assets = set()
    errors: List[str] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            for row_index, row in enumerate(reader, start=2):
                time_value = row.get("time")
                asset_value = row.get("asset")
                if not time_value or not asset_value:
                    errors.append("blank time/asset key at CSV row %d" % row_index)
                    continue
                times.add(_normalize_key("time", time_value))
                assets.add(asset_value)
    except (OSError, csv.Error) as exc:
        errors.append("cannot read factor key dimensions: %s" % exc)
    return len(times), len(assets), errors


def _compare_alpha003_runs(
    baseline_dir: Path,
    candidate_dir: Path,
    *,
    require_reports: bool,
    require_mode_pair: bool,
    require_panel_pair: bool,
) -> Dict[str, Any]:
    summaries = {
        "baseline": _load_json(baseline_dir / "summary.json"),
        "candidate": _load_json(candidate_dir / "summary.json"),
    }
    factors_by_side: Dict[str, List[str]] = {}
    metadata: Dict[str, Dict[str, Any]] = {"baseline": {}, "candidate": {}}
    key_dimensions: Dict[str, Dict[str, Any]] = {}
    connections: List[sqlite3.Connection] = []
    try:
        with tempfile.TemporaryDirectory(prefix="factor-pair-alpha003-") as scratch:
            connection = sqlite3.connect(str(Path(scratch) / "semantic.sqlite3"))
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
            for side, run_dir in (("baseline", baseline_dir), ("candidate", candidate_dir)):
                header = _read_header(run_dir / "factor_values.csv")
                factors = [field for field in header if field not in FACTOR_VALUE_KEYS]
                factors_by_side[side] = factors
                table = _insert_table(
                    connection,
                    run_dir / "factor_values.csv",
                    "factor_values.csv",
                    side,
                    FACTOR_VALUE_KEYS,
                    ("alpha003",),
                    ("alpha003",),
                    expected_fields=("time", "asset", "alpha003"),
                )
                if table["header"] != ["time", "asset", "alpha003"]:
                    table["error"] = (
                        table["error"] or "Alpha003 CSV columns/order differ from contract"
                    )
                counts = table["mask_counts"].get("alpha003", {})
                infinite_count = counts.get("positive_infinity", 0) + counts.get(
                    "negative_infinity", 0
                )
                if infinite_count:
                    table["error"] = "infinite Alpha003 values are invalid: %d" % infinite_count
                metadata[side]["factor_values.csv"] = table
                time_count, asset_count, key_errors = _factor_key_dimensions(
                    run_dir / "factor_values.csv"
                )
                key_dimensions[side] = {
                    "times": time_count,
                    "assets": asset_count,
                    "errors": key_errors,
                }

            table_results: Dict[str, Dict[str, Any]] = {}
            left_meta = metadata["baseline"]["factor_values.csv"]
            right_meta = metadata["candidate"]["factor_values.csv"]
            keyed = _compare_semantic_rows(connection, "factor_values.csv")
            row_order = _compare_row_order(connection, "factor_values.csv")
            header_equal = left_meta["header"] == right_meta["header"]
            header_set_equal = set(left_meta["header"]) == set(right_meta["header"])
            table_equal = (
                keyed["semantic_equal"]
                and left_meta["error"] is None
                and right_meta["error"] is None
                and header_equal
                and not left_meta["duplicate_keys"]
                and not right_meta["duplicate_keys"]
            )
            table_order_equal = header_equal and row_order["same"]
            table_results["factor_values.csv"] = {
                "baseline": left_meta,
                "candidate": right_meta,
                "rows_equal_count": left_meta["row_count"] == right_meta["row_count"],
                "keyed": keyed,
                "row_order": row_order,
                "header_order_equal": header_equal,
                "header_set_equal": header_set_equal,
                "semantic_equal": table_equal,
                "ordering_equal": table_order_equal,
            }

            shape: Dict[str, Dict[str, Any]] = {}
            shape_valid_sides: Dict[str, bool] = {}
            for side in ("baseline", "candidate"):
                summary = summaries[side]
                table = metadata[side]["factor_values.csv"]
                symbols = summary.get("symbols")
                dates = summary.get("dates")
                cells = summary.get("cells")
                finite = summary.get("finite")
                counts = table["mask_counts"].get("alpha003", {})
                actual_finite = counts.get("finite", 0)
                expected_rows = (
                    symbols * dates
                    if type(symbols) is int and type(dates) is int and symbols > 0 and dates > 0
                    else None
                )
                rows_match = expected_rows is not None and table["row_count"] == expected_rows
                dimension_match = (
                    key_dimensions[side]["times"] == dates
                    and key_dimensions[side]["assets"] == symbols
                )
                valid = (
                    summary.get("factor") == "alpha003"
                    and summary.get("status") == "COMPLETED"
                    and summary.get("factor_calculation") == "RAN"
                    and type(symbols) is int
                    and symbols > 0
                    and type(dates) is int
                    and dates > 0
                    and type(cells) is int
                    and cells == table["row_count"]
                    and type(finite) is int
                    and finite == actual_finite
                    and finite > 0
                    and rows_match
                    and dimension_match
                    and not table["duplicate_keys"]
                    and table["error"] is None
                    and not key_dimensions[side]["errors"]
                )
                shape_valid_sides[side] = valid
                shape[side] = {
                    "symbols": symbols,
                    "dates": dates,
                    "cells": cells,
                    "finite": finite,
                    "actual_rows": table["row_count"],
                    "actual_finite": actual_finite,
                    "key_dimensions": key_dimensions[side],
                    "valid": valid,
                }

            shape_equal = all(
                shape["baseline"][key] == shape["candidate"][key]
                for key in ("symbols", "dates", "cells", "finite")
            )
            factor_order_equal = (
                factors_by_side["baseline"] == factors_by_side["candidate"] == ["alpha003"]
            )
            output_equal = table_equal and table_order_equal and factor_order_equal
            mode_pair = (
                _compare_mode_pair(
                    summaries["baseline"],
                    summaries["candidate"],
                    ("alpha003",),
                    alpha003=True,
                )
                if require_mode_pair
                else None
            )
            reports = (
                _compare_reports(
                    baseline_dir,
                    candidate_dir,
                    summaries["baseline"],
                    summaries["candidate"],
                )
                if require_reports
                else None
            )
            panels = (
                {
                    "required": True,
                    "equal": False,
                    "errors": ["027 Alpha003 output has no paired FactorPanel CSV contract"],
                }
                if require_panel_pair
                else None
            )
            strict_equal = (
                output_equal
                and all(shape_valid_sides.values())
                and shape_equal
                and (mode_pair is None or mode_pair["valid"])
                and (reports is None or reports["equal"])
                and (panels is None or panels["equal"])
            )
            return {
                "schema_version": "factor-research-pair-semantic-v1",
                "baseline_run": str(baseline_dir),
                "candidate_run": str(candidate_dir),
                "factor_order": {
                    "baseline": factors_by_side["baseline"],
                    "candidate": factors_by_side["candidate"],
                    "same_set": set(factors_by_side["baseline"])
                    == set(factors_by_side["candidate"]),
                    "same_order": factor_order_equal,
                },
                "summary_shape": {
                    "baseline": {key: shape["baseline"][key] for key in ("symbols", "dates")},
                    "candidate": {key: shape["candidate"][key] for key in ("symbols", "dates")},
                    "details": shape,
                    "valid": all(shape_valid_sides.values()),
                    "equal": shape_equal,
                    "factor_value_rows_match_symbols_x_dates": {
                        side: (
                            shape[side]["actual_rows"]
                            == shape[side]["symbols"] * shape[side]["dates"]
                            if shape[side]["valid"]
                            else False
                        )
                        for side in ("baseline", "candidate")
                    },
                },
                "tables": table_results,
                "semantic_equal_ignoring_row_and_column_order": table_equal,
                "ordering_equal": table_order_equal,
                "mode_pair": mode_pair,
                "report_semantics": reports,
                "panel_pair": panels,
                "strict_equal": strict_equal,
                "status": "IDENTICAL" if strict_equal else "SEMANTIC_DIFFERENCES",
            }
    finally:
        for connection in connections:
            connection.close()


def _is_alpha003_run(summary: Mapping[str, Any]) -> bool:
    return summary.get("factor") == "alpha003" and not summary.get("evaluation_id")


def compare_runs(
    baseline_dir: Path,
    candidate_dir: Path,
    *,
    require_reports: bool = False,
    require_mode_pair: bool = False,
    require_panel_pair: bool = False,
) -> Dict[str, Any]:
    baseline_dir = baseline_dir.expanduser().resolve()
    candidate_dir = candidate_dir.expanduser().resolve()
    baseline_summary = _load_json(baseline_dir / "summary.json")
    candidate_summary = _load_json(candidate_dir / "summary.json")
    if _is_alpha003_run(baseline_summary) or _is_alpha003_run(candidate_summary):
        return _compare_alpha003_runs(
            baseline_dir,
            candidate_dir,
            require_reports=require_reports,
            require_mode_pair=require_mode_pair,
            require_panel_pair=require_panel_pair,
        )
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
            for side, run_dir, evaluation_dir, manifest, factors in (
                ("baseline", baseline_dir, baseline_eval, baseline_manifest, baseline_factors),
                ("candidate", candidate_dir, candidate_eval, candidate_manifest, candidate_factors),
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
                        and not _empty_table_is_contractual(
                            filename, manifest, len(factors), fields
                        )
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
            mode_pair = (
                _compare_mode_pair(
                    baseline_summary,
                    candidate_summary,
                    baseline_factors,
                    alpha003=False,
                )
                if require_mode_pair
                else None
            )
            fingerprint_gate_passed = fingerprints_valid and (
                fingerprints_equal or (mode_pair is not None and mode_pair["valid"])
            )
            reports = (
                _compare_reports(
                    baseline_dir,
                    candidate_dir,
                    baseline_summary,
                    candidate_summary,
                )
                if require_reports
                else None
            )
            panels = (
                _compare_panel_pair(baseline_dir, candidate_dir) if require_panel_pair else None
            )
            strict_equal = (
                semantic_equal
                and ordering_equal
                and fingerprint_gate_passed
                and run_state_acceptable
                and summary_shape_valid
                and summary_shape_equal
                and factor_row_counts_valid
                and (mode_pair is None or mode_pair["valid"])
                and (reports is None or reports["equal"])
                and (panels is None or panels["equal"])
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
                    "difference_allowed_by_mode_pair": bool(
                        mode_pair is not None
                        and mode_pair["valid"]
                        and fingerprints_valid
                        and not fingerprints_equal
                    ),
                    "comparison_gate_passed": fingerprint_gate_passed,
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
                "mode_pair": mode_pair,
                "report_semantics": reports,
                "panel_pair": panels,
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
                    and (mode_pair is None or mode_pair["valid"])
                    and (reports is None or reports["equal"])
                    and (panels is None or panels["equal"])
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
                    and (mode_pair is None or mode_pair["valid"])
                    and (reports is None or reports["equal"])
                    and (panels is None or panels["equal"])
                ),
                "status": (
                    "IDENTICAL"
                    if strict_equal
                    else (
                        "INVALID_MODE_PAIR"
                        if mode_pair is not None
                        and (
                            not mode_pair["baseline"]["valid"]
                            or not mode_pair["candidate"]["valid"]
                        )
                        else (
                            "MODE_PAIR_DIFFERENCES"
                            if mode_pair is not None and not mode_pair["valid"]
                            else (
                                "REPORT_SEMANTIC_DIFFERENCES"
                                if reports is not None and not reports["equal"]
                                else (
                                    "PANEL_DIFFERENCES"
                                    if panels is not None and not panels["equal"]
                                    else (
                                        "INVALID_RUN_STATE"
                                        if not run_states_valid
                                        else (
                                            "RUN_STATE_DIFFERENCES"
                                            if not run_states_equal
                                            else (
                                                "INVALID_SUMMARY_SHAPE"
                                                if not summary_shape_valid
                                                or not factor_row_counts_valid
                                                else (
                                                    "SUMMARY_SHAPE_DIFFERENCES"
                                                    if not summary_shape_equal
                                                    else (
                                                        "INVALID_FINGERPRINT"
                                                        if not fingerprints_valid
                                                        else (
                                                            "ORDER_ONLY_DIFFERENCES"
                                                            if semantic_equal
                                                            and not ordering_equal
                                                            and fingerprints_equal
                                                            else (
                                                                "ORDER_AND_FINGERPRINT_DIFFERENCES"
                                                                if semantic_equal
                                                                and not ordering_equal
                                                                and not fingerprints_equal
                                                                else (
                                                                    "FINGERPRINT_DIFFERENCE"
                                                                    if semantic_equal
                                                                    and ordering_equal
                                                                    and fingerprints_valid
                                                                    and not fingerprints_equal
                                                                    else "SEMANTIC_DIFFERENCES"
                                                                )
                                                            )
                                                        )
                                                    )
                                                )
                                            )
                                        )
                                    )
                                )
                            )
                        )
                    )
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
    parser.add_argument(
        "--require-reports",
        action="store_true",
        help="require captured full report payloads and verified HTML hashes",
    )
    parser.add_argument(
        "--require-mode-pair",
        action="store_true",
        help="require one completed native run and one completed build run",
    )
    parser.add_argument(
        "--require-panel-pair",
        action="store_true",
        help="require and exactly compare both six-CSV FactorPanel exports",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = compare_runs(
            args.baseline_run,
            args.candidate_run,
            require_reports=args.require_reports,
            require_mode_pair=args.require_mode_pair,
            require_panel_pair=args.require_panel_pair,
        )
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
