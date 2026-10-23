#!/usr/bin/env python
"""Verify fixed-500 Iteration 49 full-output runs and exact A/B equivalence.

The verifier reads public output files only. It never imports an example, runs
an example, reads credentials, or changes the benchmark inputs. Each run is
identified by three ``--run EXAMPLE=PATH`` arguments, where PATH is either an
example output directory or its parent containing ``example/``. For A/B use
three ``--baseline`` and three ``--candidate`` arguments instead.

Every F-mode report run must include ``report_semantics.json`` produced by
``scripts.verify_factor_research_pair_semantics.capture_report_semantics``.
That sidecar binds the full-precision ReportDocument passed to the renderer to
the actual HTML file hash; rendered HTML bytes are never compared as a whole.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import html.parser
import json
import math
import re
import struct
import sys
import zlib
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / "tests" / "datas" / "a_stocks"
DEFAULT_SELECTION = (
    REPO_ROOT
    / "docs"
    / "_internal"
    / "opts"
    / "requirements"
    / "迭代49-因子分析性能优化"
    / "benchmark-500-7col.json"
)
REPORT_SEMANTICS_NAME = "report_semantics.json"
REPORT_SEMANTICS_SCHEMA = "factor-report-semantics-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
EXPECTED_SELECTION_SHA256 = "14f789a9d9e649987b93bc0477a0f94acc5223edd7ccd70166c8ea4b33ba35dc"

EXPECTED_EXAMPLES = ("025", "026", "027")
EXPECTED_FACTORS = {
    "025": ("close_ma",),
    "026": ("close_ma", "kdj_j", "roc"),
    "027": ("alpha003",),
}
EXPECTED_REPORTS = {
    "025": ("factor_report_close_ma.html",),
    "026": (
        "factor_report_close_ma.html",
        "factor_report_kdj_j.html",
        "factor_report_roc.html",
    ),
    "027": ("factor_report_alpha003.html",),
}
EVALUATION_CSVS = (
    "signals.csv",
    "labels.csv",
    "ic.csv",
    "ic_summary.csv",
    "quantile_returns.csv",
    "turnover.csv",
    "spreads.csv",
    "stability.csv",
    "correlation.csv",
    "comparisons.csv",
    "coverage.csv",
    "diagnostics.csv",
)
EVALUATION_PNGS = ("ic_series.png", "quantile_returns.png")
EVALUATION_EXPORTS = (*EVALUATION_CSVS, *EVALUATION_PNGS)
LABEL_PERIODS = ("1D", "5D", "20D")

# The table schemas are part of the full-output contract. A new or reordered
# field requires an intentional verifier update instead of passing as unknown.
TABLE_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "signals.csv": ("time", "asset", "factor", "direction", "value", "processed_value", "preprocess", "group"),
    "labels.csv": ("time", "asset", "period", "value"),
    "ic.csv": ("time", "factor", "period", "ic", "rank_ic", "n_assets"),
    "ic_summary.csv": (
        "factor", "period", "mean_ic", "std_ic", "icir", "mean_rank_ic", "std_rank_ic", "rank_icir", "n_dates"
    ),
    "quantile_returns.csv": ("time", "factor", "period", "quantile", "mean_return", "n_assets"),
    "turnover.csv": ("time", "factor", "period", "quantile", "turnover"),
    "spreads.csv": ("time", "factor", "period", "spread", "top_quantile", "bottom_quantile"),
    "stability.csv": ("factor", "lag", "mean_rank_autocorrelation", "std_rank_autocorrelation", "n_dates"),
    "correlation.csv": ("factor_left", "factor_right", "mean_correlation", "std_correlation", "n_dates"),
    "comparisons.csv": (
        "comparison", "left", "right", "period", "mean_ic", "icir", "mean_ic_left", "mean_ic_right",
        "icir_left", "icir_right", "n_dates_left", "n_dates_right"
    ),
    "coverage.csv": (
        "factor", "kind", "direction", "input_cells", "finite_cells", "label_cells", "evaluable_cells", "status"
    ),
    "diagnostics.csv": ("factor", "stage", "severity", "code", "message"),
}
TABLE_KEYS: Dict[str, Tuple[str, ...]] = {
    "signals.csv": ("time", "asset", "factor", "direction"),
    "labels.csv": ("time", "asset", "period"),
    "ic.csv": ("time", "factor", "period"),
    "ic_summary.csv": ("factor", "period"),
    "quantile_returns.csv": ("time", "factor", "period", "quantile"),
    "turnover.csv": ("time", "factor", "period", "quantile"),
    "spreads.csv": ("time", "factor", "period"),
    "stability.csv": ("factor", "lag"),
    "correlation.csv": ("factor_left", "factor_right"),
    "comparisons.csv": ("comparison", "left", "right", "period"),
    "coverage.csv": ("factor", "kind", "direction"),
    "diagnostics.csv": (),
}
TABLE_NUMERIC: Dict[str, Set[str]] = {
    name: set(columns) - set(TABLE_KEYS[name]) - {
        "preprocess", "group", "status", "factor", "kind", "direction", "stage", "severity", "code",
        "message", "comparison", "left", "right", "period", "factor_left", "factor_right", "asset",
        "time",
    }
    for name, columns in TABLE_COLUMNS.items()
}

# Dynamic fields are intentionally narrow. Financial metadata and unrecognized
# fields remain part of equality checks. Report output paths are validated
# against the current directory before they are excluded from A/B comparison.
SUMMARY_DYNAMIC_FIELDS = {
    "025": ("output_dir", "report", "reports"),
    "026": ("output_dir", "report", "reports"),
    "027": ("output_dir", "report", "reports", "elapsed_seconds"),
}
MANIFEST_DYNAMIC_FIELDS = ("generated_at", "generated_at_utc", "created_at", "output_path", "output_dir")


class VerificationError(ValueError):
    """Raised when the fixed public input selection cannot be verified."""


def _reject_constant(token: str) -> None:
    raise ValueError("non-finite JSON constant %s" % token)


def _unique_object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key %r" % key)
        result[key] = value
    return result


def _read_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8-sig"),
        parse_constant=_reject_constant,
        object_pairs_hook=_unique_object,
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expect(condition: bool, errors: List[str], message: str) -> None:
    if not condition:
        errors.append(message)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _validate_dynamic_manifest_fields(manifest: Mapping[str, Any], eval_dir: Path) -> None:
    for key in ("generated_at", "generated_at_utc", "created_at"):
        if key in manifest:
            value = manifest[key]
            if not isinstance(value, str) or not value:
                raise VerificationError("evaluation manifest %s must be a non-empty timestamp" % key)
            try:
                datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise VerificationError("evaluation manifest %s is not an ISO timestamp" % key) from exc
    for key in ("output_path", "output_dir"):
        if key in manifest:
            value = manifest[key]
            if not isinstance(value, str) or not value:
                raise VerificationError("evaluation manifest %s must be a non-empty path" % key)
            path = Path(value).expanduser()
            resolved = path.resolve() if path.is_absolute() else (eval_dir / path).resolve()
            if not _is_within(resolved, eval_dir):
                raise VerificationError("evaluation manifest %s escapes its evaluation directory" % key)


def _load_fixed_inputs(data_root: Path, selection_path: Path) -> Dict[str, Any]:
    data_root = data_root.expanduser().resolve()
    selection_path = selection_path.expanduser().resolve()
    manifest_path = data_root / "_metadata" / "manifest.json"
    calendar_path = data_root / "_metadata" / "observed_calendar.csv"
    try:
        selection = _read_json(selection_path)
        manifest = _read_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise VerificationError("could not read fixed selection or public input manifest: %s" % exc) from exc
    if not isinstance(selection, Mapping) or not isinstance(manifest, Mapping):
        raise VerificationError("fixed selection and public input manifest must be JSON objects")
    entries = manifest.get("output", {}).get("symbols") if isinstance(manifest.get("output"), Mapping) else None
    if not isinstance(entries, list):
        raise VerificationError("public input manifest has no output.symbols list")
    if manifest.get("status") != "complete":
        raise VerificationError("public input manifest status is not complete")
    source_count = len(entries)
    selected_count = selection.get("selected_symbol_count")
    if selection.get("schema") != "iteration49.benchmark500.v1":
        raise VerificationError("fixed selection schema is unknown")
    if _sha256_file(selection_path) != EXPECTED_SELECTION_SHA256:
        raise VerificationError("fixed benchmark-500.json differs from the frozen selection")
    if selection.get("status") != "FIXED_INPUT_SELECTION_NOT_A_BENCHMARK_RESULT":
        raise VerificationError("fixed selection status is not the frozen input-only status")
    if (
        type(selected_count) is not int
        or selected_count != 500
        or type(selection.get("source_symbol_count")) is not int
        or selection.get("source_symbol_count") != source_count
    ):
        raise VerificationError("fixed selection must describe 500 symbols from the current manifest")
    if selection.get("source_manifest_sha256") != _sha256_file(manifest_path):
        raise VerificationError("public input manifest hash differs from benchmark-500.json")
    if selection.get("source_calendar_sha256") != _sha256_file(calendar_path):
        raise VerificationError("public observed calendar hash differs from benchmark-500.json")
    if source_count != 5471:
        raise VerificationError("public input manifest has %d symbols, expected 5471" % source_count)

    source_by_position: List[Mapping[str, Any]] = []
    for item in entries:
        if not isinstance(item, Mapping):
            raise VerificationError("public input manifest contains a malformed symbol row")
        symbol, filename, sha = item.get("symbol"), item.get("file"), item.get("sha256")
        if (
            not isinstance(symbol, str)
            or not symbol
            or not isinstance(filename, str)
            or not filename
            or Path(filename).name != filename
            or PureWindowsPath(filename).name != filename
        ):
            raise VerificationError("public input manifest contains an invalid symbol or filename")
        if not isinstance(sha, str) or SHA256_RE.fullmatch(sha) is None:
            raise VerificationError("public input manifest contains an invalid CSV digest")
        source_by_position.append(item)

    expected_positions = [int(index * (source_count / float(500))) for index in range(500)]
    expected_entries = [source_by_position[position] for position in expected_positions]
    fixed_entries = selection.get("entries")
    if not isinstance(fixed_entries, list) or len(fixed_entries) != 500:
        raise VerificationError("benchmark-500.json must contain exactly 500 selected entries")
    symbols: List[str] = []
    for index, (position, expected, recorded) in enumerate(zip(expected_positions, expected_entries, fixed_entries)):
        if not isinstance(recorded, Mapping):
            raise VerificationError("benchmark-500.json entry %d is malformed" % index)
        expected_row = {
            "position": position,
            "symbol": expected["symbol"],
            "file": expected["file"],
            "sha256": expected["sha256"],
        }
        actual_row = {key: recorded.get(key) for key in expected_row}
        if actual_row != expected_row:
            raise VerificationError("benchmark-500.json entry %d differs from the manifest selection" % index)
        csv_path = data_root / str(expected["file"])
        if not csv_path.is_file() or _sha256_file(csv_path) != expected["sha256"]:
            raise VerificationError("selected public CSV is missing or changed: %s" % expected["file"])
        symbols.append(str(expected["symbol"]))
    if len(set(symbols)) != 500:
        raise VerificationError("fixed selection contains duplicate symbols")
    ordered_digest = hashlib.sha256(("\n".join(symbols) + "\n").encode("utf-8")).hexdigest()
    if selection.get("ordered_symbols_sha256") != ordered_digest:
        raise VerificationError("ordered fixed symbol digest differs from benchmark-500.json")

    dates: List[str] = []
    timestamps: List[str] = []
    source_timezone = ZoneInfo("Asia/Shanghai")
    try:
        with calendar_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required_calendar_fields = {"trade_date", "last_trade_time"}
            if not reader.fieldnames or not required_calendar_fields.issubset(reader.fieldnames):
                raise VerificationError("public observed calendar lacks trade_date/last_trade_time")
            for row in reader:
                trade_date = row.get("trade_date")
                last_trade_time = row.get("last_trade_time")
                if not trade_date or not last_trade_time:
                    raise VerificationError("public observed calendar contains an incomplete date row")
                try:
                    local_close = datetime.datetime.fromisoformat(last_trade_time).replace(tzinfo=source_timezone)
                except ValueError as exc:
                    raise VerificationError("public observed calendar contains an invalid last_trade_time") from exc
                if local_close.date().isoformat() != trade_date:
                    raise VerificationError("public observed calendar close date differs from trade_date")
                dates.append(trade_date)
                timestamps.append(
                    local_close.astimezone(datetime.timezone.utc).isoformat(sep=" ")
                )
    except (OSError, csv.Error) as exc:
        raise VerificationError("could not read public observed calendar: %s" % exc) from exc
    if len(dates) != 243 or len(set(dates)) != 243:
        raise VerificationError("public observed calendar must contain 243 unique dates")
    if (
        type(selection.get("date_count")) is not int
        or selection.get("date_count") != 243
        or type(selection.get("expected_grid_cells")) is not int
        or selection.get("expected_grid_cells") != 121500
    ):
        raise VerificationError("benchmark-500.json date/grid counts are not the fixed 500 x 243 contract")
    if selection.get("date_range") != [dates[0], dates[-1]]:
        raise VerificationError("benchmark-500.json date range differs from the public calendar")
    return {
        "data_root": str(data_root),
        "selection_path": str(selection_path),
        "selection_sha256": _sha256_file(selection_path),
        "manifest_sha256": _sha256_file(manifest_path),
        "calendar_sha256": _sha256_file(calendar_path),
        "source_symbol_count": source_count,
        "symbols": symbols,
        "dates": dates,
        "timestamps": timestamps,
        "grid_cells": 121500,
    }


def _resolve_example_dir(value: Path) -> Path:
    path = value.expanduser().resolve()
    candidates = [path, path / "example"]
    matches = [candidate for candidate in candidates if (candidate / "summary.json").is_file()]
    if len(matches) != 1:
        raise VerificationError("path must identify one output directory containing summary.json: %s" % path)
    return matches[0]


def _parse_assignment(value: str) -> Tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("expected EXAMPLE=PATH")
    example, raw_path = value.split("=", 1)
    example = example.strip()
    raw_path = raw_path.strip().strip('"')
    if example not in EXPECTED_EXAMPLES or not raw_path:
        raise argparse.ArgumentTypeError("EXAMPLE must be 025, 026, or 027 and PATH must be non-empty")
    return example, Path(raw_path)


def _collect_assignments(
    values: Optional[Sequence[Tuple[str, Path]]], label: str, *, require_all: bool = True
) -> Dict[str, Path]:
    result: Dict[str, Path] = {}
    for example, path in values or ():
        if example in result:
            raise VerificationError("%s repeats example %s" % (label, example))
        result[example] = path
    if not result:
        raise VerificationError("%s must name at least one example" % label)
    if require_all and set(result) != set(EXPECTED_EXAMPLES):
        missing = sorted(set(EXPECTED_EXAMPLES) - set(result))
        extra = sorted(set(result) - set(EXPECTED_EXAMPLES))
        raise VerificationError("%s must name exactly 025, 026, and 027 (missing=%s extra=%s)" % (label, missing, extra))
    return result


def _expected_report_paths(example: str, summary: Mapping[str, Any], root: Path, errors: List[str]) -> List[Path]:
    if example == "026":
        declared = summary.get("reports")
        if summary.get("report") is not None:
            errors.append("026 summary.report must be null when reports is a list")
        if not isinstance(declared, list):
            errors.append("026 summary.reports must be a list")
            declared = []
    else:
        declared = summary.get("report")
        if not isinstance(declared, str) or not declared:
            errors.append("%s summary.report must name its HTML report" % example)
            declared = []
        else:
            declared = [declared]
    expected_names = EXPECTED_REPORTS[example]
    names: List[str] = []
    for item in declared:
        if not isinstance(item, str) or not item:
            errors.append("%s report path is not a non-empty string" % example)
            continue
        name = PureWindowsPath(item.replace("/", "\\")).name
        names.append(name)
        raw = Path(item)
        if raw.is_absolute():
            try:
                if raw.resolve() != (root / name).resolve():
                    errors.append("summary report path does not point into this run: %s" % item)
            except OSError:
                errors.append("summary report path cannot be resolved: %s" % item)
        else:
            try:
                if (root / raw).resolve() != (root / name).resolve():
                    errors.append("summary report path does not point into this run: %s" % item)
            except OSError:
                errors.append("summary report path cannot be resolved: %s" % item)
    if tuple(names) != expected_names:
        errors.append("%s report filenames/order differ from the full-mode contract" % example)
    return [root / name for name in expected_names]


class _TableParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.tables: List[List[Tuple[str, ...]]] = []
        self.current_table: Optional[List[Tuple[str, ...]]] = None
        self.current_row: Optional[List[str]] = None
        self.current_cell: Optional[List[str]] = None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() == "table":
            if self.depth == 0:
                self.current_table = []
                self.tables.append(self.current_table)
            self.depth += 1
        elif self.depth and tag.lower() == "tr":
            self.current_row = []
        elif self.depth and tag.lower() in ("th", "td"):
            self.current_cell = []
        elif self.depth and tag.lower() == "br" and self.current_cell is not None:
            self.current_cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.depth and tag in ("th", "td") and self.current_cell is not None:
            value = " ".join("".join(self.current_cell).split())
            if self.current_row is None:
                self.current_row = []
            self.current_row.append(value)
            self.current_cell = None
        elif self.depth and tag == "tr" and self.current_row is not None:
            if self.current_table is not None:
                self.current_table.append(tuple(self.current_row))
            self.current_row = None
        elif self.depth and tag == "table":
            self.depth -= 1
            if self.depth == 0:
                self.current_table = None
                self.current_row = None
                self.current_cell = None

    def handle_data(self, data: str) -> None:
        if self.current_cell is not None:
            self.current_cell.append(data)


def _read_html_products(path: Path) -> Dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise VerificationError("could not read report HTML %s: %s" % (path.name, exc)) from exc
    prefix = "const DATA = "
    start = content.find(prefix)
    if start < 0 or content.find(prefix, start + len(prefix)) >= 0:
        raise VerificationError("report HTML must contain exactly one embedded const DATA payload: %s" % path.name)
    decoder = json.JSONDecoder(parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    try:
        data, end = decoder.raw_decode(content[start + len(prefix) :])
    except (ValueError, json.JSONDecodeError) as exc:
        raise VerificationError("embedded chart DATA is invalid JSON in %s: %s" % (path.name, exc)) from exc
    remainder = content[start + len(prefix) + end :].lstrip()
    if not remainder.startswith(";"):
        raise VerificationError("embedded chart DATA is not terminated as expected in %s" % path.name)
    if not isinstance(data, Mapping):
        raise VerificationError("embedded chart DATA must be an object in %s" % path.name)
    required_keys = {"ic", "cumulative", "distribution", "quantile", "turnover"}
    if set(data) != required_keys:
        raise VerificationError("embedded chart DATA keys are unknown or incomplete in %s" % path.name)
    parser = _TableParser()
    parser.feed(content)
    parser.close()
    if len(parser.tables) != 14 or any(not table or any(not row for row in table) for table in parser.tables):
        raise VerificationError("report HTML does not contain all 14 non-empty semantic tables: %s" % path.name)
    return {
        "name": path.name,
        "sha256": _sha256_file(path),
        "chart_data": data,
        "chart_data_json": _canonical_json(data),
        "tables": parser.tables,
    }


def _read_report_semantics(root: Path, expected_paths: Sequence[Path]) -> Dict[str, Any]:
    sidecar_path = root / REPORT_SEMANTICS_NAME
    try:
        sidecar = _read_json(sidecar_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise VerificationError("missing or invalid %s: %s" % (REPORT_SEMANTICS_NAME, exc)) from exc
    if not isinstance(sidecar, Mapping) or sidecar.get("schema_version") != REPORT_SEMANTICS_SCHEMA:
        raise VerificationError("report semantics sidecar has an unknown schema")
    reports = sidecar.get("reports")
    if not isinstance(reports, list) or len(reports) != len(expected_paths):
        raise VerificationError("report semantics count differs from the full-mode HTML count")
    normalized: Dict[str, Dict[str, Any]] = {}
    html_products: Dict[str, Dict[str, Any]] = {}
    for index, (entry, expected_path) in enumerate(zip(reports, expected_paths)):
        if not isinstance(entry, Mapping):
            raise VerificationError("report semantics entry %d is malformed" % index)
        relative = entry.get("html_path")
        if not isinstance(relative, str) or not relative:
            raise VerificationError("report semantics entry %d has no relative html_path" % index)
        relative_path = PurePosixPath(relative.replace("\\", "/"))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise VerificationError("report semantics path escapes the run directory: %s" % relative)
        html_path = (root / Path(*relative_path.parts)).resolve()
        try:
            html_path.relative_to(root.resolve())
        except ValueError as exc:
            raise VerificationError("report semantics path escapes the run directory: %s" % relative) from exc
        if html_path != expected_path.resolve():
            raise VerificationError("report semantics path/order differs from declared HTML reports")
        digest = entry.get("html_sha256")
        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
            raise VerificationError("report semantics entry %d has invalid html_sha256" % index)
        actual_html_digest = _sha256_file(html_path)
        if actual_html_digest != digest.lower():
            raise VerificationError("report semantics HTML digest mismatch: %s" % html_path.name)
        payload = entry.get("semantic_payload")
        semantic_digest = entry.get("semantic_digest")
        if not isinstance(payload, Mapping) or not isinstance(semantic_digest, str) or SHA256_RE.fullmatch(semantic_digest) is None:
            raise VerificationError("report semantics entry %d lacks a full model payload or digest" % index)
        payload_json = _canonical_json(payload)
        actual_semantic_digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if actual_semantic_digest != semantic_digest.lower():
            raise VerificationError("ReportDocument semantic digest mismatch: %s" % html_path.name)
        if payload.get("domain") != "factor" or not isinstance(payload.get("sections"), list) or not payload.get("sections"):
            raise VerificationError("ReportDocument payload is not a complete factor report: %s" % html_path.name)
        report_name = expected_path.name
        if report_name in normalized:
            raise VerificationError("duplicate report model for %s" % report_name)
        normalized[report_name] = {
            "payload": payload,
            "payload_json": payload_json,
            "semantic_digest": semantic_digest.lower(),
        }
        html_products[report_name] = _read_html_products(html_path)
    if tuple(normalized) != tuple(path.name for path in expected_paths):
        raise VerificationError("report model ordering differs from the expected report list")
    return {"models": normalized, "html": html_products}


def _png_info(path: Path) -> Dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise VerificationError("could not read PNG %s: %s" % (path.name, exc)) from exc
    if len(raw) < 45 or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise VerificationError("PNG is missing, empty, or has an invalid signature: %s" % path.name)
    offset = 8
    width = height = bit_depth = color_type = interlace = None
    idat: List[bytes] = []
    saw_iend = False
    previous_type: Optional[bytes] = None
    saw_idat_end = False
    while offset < len(raw):
        if len(raw) - offset < 12:
            raise VerificationError("truncated PNG chunk in %s" % path.name)
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        chunk_type = raw[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(raw):
            raise VerificationError("PNG chunk length exceeds file size in %s" % path.name)
        chunk_data = raw[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", raw[offset + 8 + length : end])[0]
        actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise VerificationError("PNG chunk CRC mismatch in %s" % path.name)
        if offset == 8 and (chunk_type != b"IHDR" or length != 13):
            raise VerificationError("PNG must begin with a 13-byte IHDR in %s" % path.name)
        if chunk_type == b"IHDR":
            if width is not None or length != 13:
                raise VerificationError("duplicate or malformed PNG IHDR in %s" % path.name)
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", chunk_data)
            if not width or not height or compression != 0 or filtering != 0 or interlace not in (0, 1):
                raise VerificationError("invalid PNG IHDR values in %s" % path.name)
        elif chunk_type == b"IDAT":
            if width is None or saw_idat_end:
                raise VerificationError("PNG IDAT chunks are misplaced or non-contiguous in %s" % path.name)
            idat.append(chunk_data)
        else:
            if previous_type == b"IDAT":
                saw_idat_end = True
            if chunk_type == b"IEND":
                if length != 0:
                    raise VerificationError("PNG IEND must be empty in %s" % path.name)
                saw_iend = True
                offset = end
                break
        previous_type = chunk_type
        offset = end
    if not saw_iend or offset != len(raw) or not idat or width is None or height is None:
        raise VerificationError("PNG lacks complete IHDR/IDAT/IEND data: %s" % path.name)
    try:
        decompressed = zlib.decompress(b"".join(idat))
    except zlib.error as exc:
        raise VerificationError("PNG IDAT stream is not valid zlib data in %s" % path.name) from exc
    if not decompressed:
        raise VerificationError("PNG IDAT stream decoded to no image data in %s" % path.name)
    if interlace == 0:
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
        if channels is None:
            raise VerificationError("unknown PNG color type in %s" % path.name)
        expected_bytes = height * (1 + (width * channels * bit_depth + 7) // 8)
        if len(decompressed) != expected_bytes:
            raise VerificationError("PNG decoded row bytes do not match IHDR in %s" % path.name)
    return {"name": path.name, "bytes": len(raw), "width": width, "height": height, "decoded_bytes": len(decompressed)}


def _float_cell(token: Optional[str], where: str) -> Tuple[str, Optional[bytes]]:
    text = "" if token is None else token.strip()
    if not text:
        return "nan", None
    try:
        value = float(text)
    except (ValueError, OverflowError) as exc:
        raise VerificationError("invalid numeric cell at %s: %r" % (where, text)) from exc
    if math.isnan(value):
        return "nan", None
    if math.isinf(value):
        raise VerificationError("infinite numeric cell at %s" % where)
    return "finite", struct.pack(">d", value)


def _factor_float_cell(token: Optional[str], where: str) -> Tuple[str, Optional[bytes]]:
    text = "" if token is None else token.strip()
    if not text:
        return "nan", None
    try:
        value = float(text)
    except (ValueError, OverflowError) as exc:
        raise VerificationError("invalid numeric cell at %s: %r" % (where, text)) from exc
    if math.isnan(value):
        return "nan", None
    if math.isinf(value):
        return "infinite", None
    return "finite", struct.pack(">d", value)


def _factor_csv(path: Path, inputs: Mapping[str, Any], example: str) -> Dict[str, Any]:
    errors: List[str] = []
    expected_symbols = inputs["symbols"]
    expected_dates = inputs["dates"]
    expected_header = ("time", "asset", *EXPECTED_FACTORS[example])
    counts = {name: {"finite": 0, "nan": 0, "infinite": 0, "invalid": 0} for name in EXPECTED_FACTORS[example]}
    values: Dict[str, List[Optional[bytes]]] = {name: [] for name in EXPECTED_FACTORS[example]}
    timestamps: List[str] = []
    row_count = 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream)
            header = next(reader, None)
            if tuple(header or ()) != expected_header:
                errors.append("factor_values.csv columns/order differ from the %s full-mode contract" % example)
            else:
                cells = len(expected_symbols) * len(expected_dates)
                for row_index, row in enumerate(reader):
                    row_count += 1
                    if len(row) != len(expected_header):
                        if len(errors) < 20:
                            errors.append("factor_values.csv row %d has the wrong number of columns" % (row_index + 2))
                        continue
                    if row_index >= cells:
                        if len(errors) < 20:
                            errors.append("factor_values.csv has rows beyond the fixed grid")
                        continue
                    date_index = row_index // len(expected_symbols)
                    symbol_index = row_index % len(expected_symbols)
                    expected_timestamp = inputs["timestamps"][date_index]
                    expected_symbol = expected_symbols[symbol_index]
                    timestamp, asset = row[0].strip(), row[1].strip()
                    if timestamp != expected_timestamp or asset != expected_symbol:
                        if len(errors) < 20:
                            errors.append(
                                "factor_values.csv row %d is out of fixed UTC timestamp/asset order (expected %s/%s, got %s/%s)"
                                % (row_index + 2, expected_timestamp, expected_symbol, timestamp, asset)
                            )
                    if symbol_index == 0:
                        timestamps.append(timestamp)
                    elif timestamps and timestamp != timestamps[-1]:
                        if len(errors) < 20:
                            errors.append("factor_values.csv timestamps differ between assets on %s" % expected_timestamp)
                    for index, factor in enumerate(EXPECTED_FACTORS[example], start=2):
                        try:
                            kind, bits = _factor_float_cell(
                                row[index], "factor_values.csv row %d column %s" % (row_index + 2, factor)
                            )
                        except VerificationError as exc:
                            counts[factor]["invalid"] += 1
                            if len(errors) < 20:
                                errors.append(str(exc))
                            values[factor].append(None)
                            continue
                        counts[factor][kind] += 1
                        if kind == "infinite" and len(errors) < 20:
                            errors.append(
                                "infinite factor value at row %d column %s" % (row_index + 2, factor)
                            )
                        values[factor].append(bits)
    except (OSError, csv.Error, StopIteration) as exc:
        errors.append("could not read factor_values.csv: %s" % exc)
    expected_rows = len(expected_symbols) * len(expected_dates)
    if row_count != expected_rows:
        errors.append("factor_values.csv has %d rows, expected %d" % (row_count, expected_rows))
    if len(timestamps) != len(expected_dates):
        errors.append("factor_values.csv has %d date timestamps, expected %d" % (len(timestamps), len(expected_dates)))
    for factor, factor_counts in counts.items():
        if sum(factor_counts.values()) != row_count:
            errors.append("factor %s parsed cell count differs from row count" % factor)
        if factor_counts["infinite"] or factor_counts["invalid"]:
            errors.append("factor %s contains infinite or invalid values" % factor)
    return {
        "valid": not errors,
        "errors": errors,
        "path": str(path),
        "columns": list(expected_header),
        "rows": row_count,
        "expected_rows": expected_rows,
        "factor_counts": counts,
        "timestamps": timestamps,
        "values": values,
    }


def _validate_pngs(eval_dir: Path) -> List[Dict[str, Any]]:
    return [_png_info(eval_dir / name) for name in EVALUATION_PNGS]


def _read_eval_rows(path: Path, expected_header: Sequence[str], filename: str) -> Iterator[Tuple[Any, ...]]:
    numeric_fields = TABLE_NUMERIC[filename]
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != tuple(expected_header):
            raise VerificationError("%s header differs from manifest" % filename)
        for row_index, row in enumerate(reader, start=2):
            if None in row or any(row.get(field) is None for field in expected_header):
                raise VerificationError("%s row %d has a malformed width" % (filename, row_index))
            normalized: List[Any] = []
            for field in expected_header:
                if field in numeric_fields:
                    normalized.append(_float_cell(row[field], "%s row %d/%s" % (filename, row_index, field)))
                else:
                    normalized.append(row[field])
            yield tuple(normalized)


def _validate_eval_csv(path: Path, filename: str, entry: Mapping[str, Any]) -> Dict[str, Any]:
    expected_columns = TABLE_COLUMNS[filename]
    manifest_columns = entry.get("columns")
    if manifest_columns != list(expected_columns):
        raise VerificationError("manifest table schema is unknown or reordered for %s" % filename)
    row_count = 0
    seen_keys: Set[Tuple[Any, ...]] = set()
    first_duplicate: Optional[List[str]] = None
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != expected_columns:
            raise VerificationError("%s columns/order differ from full-mode schema" % filename)
        for row_index, row in enumerate(reader, start=2):
            if None in row or any(row.get(field) is None for field in expected_columns):
                raise VerificationError("%s row %d has malformed width" % (filename, row_index))
            row_count += 1
            for field in TABLE_NUMERIC[filename]:
                _float_cell(row[field], "%s row %d/%s" % (filename, row_index, field))
            key_columns = TABLE_KEYS[filename]
            if key_columns:
                key = tuple(row[field] for field in key_columns)
                if key in seen_keys:
                    if first_duplicate is None:
                        first_duplicate = list(key)
                else:
                    seen_keys.add(key)
    if row_count != entry.get("rows"):
        raise VerificationError("%s has %d rows, manifest declares %r" % (filename, row_count, entry.get("rows")))
    if type(entry.get("rows")) is not int:
        raise VerificationError("%s manifest row count must be an integer" % filename)
    if first_duplicate is not None:
        raise VerificationError("%s contains duplicate row key %r" % (filename, first_duplicate))
    return {"name": filename, "columns": list(expected_columns), "rows": row_count, "unique_keys": len(seen_keys)}


def _evaluation(example: str, root: Path, summary: Mapping[str, Any], inputs: Mapping[str, Any]) -> Dict[str, Any]:
    if example == "027":
        if summary.get("evaluation_id") is not None or summary.get("evaluation_status") is not None:
            raise VerificationError("027 must not claim a research evaluation")
        evaluation_root = root / "evaluation"
        if evaluation_root.exists():
            raise VerificationError("027 full output must not contain an evaluation directory")
        return {"status": "NOT_APPLICABLE_BY_027", "evaluation_id": None, "result_fingerprint": None}

    if summary.get("evaluation_status") != "OK":
        raise VerificationError("%s evaluation status is not exactly OK" % example)
    evaluation_id = summary.get("evaluation_id")
    if not isinstance(evaluation_id, str) or SHA256_RE.fullmatch(evaluation_id) is None:
        raise VerificationError("%s summary has no valid evaluation_id" % example)
    evaluation_root = root / "evaluation"
    if not evaluation_root.is_dir():
        raise VerificationError("%s full output lacks evaluation directory" % example)
    children = list(evaluation_root.iterdir())
    if len(children) != 1 or not children[0].is_dir() or children[0].name != evaluation_id:
        raise VerificationError("%s evaluation directory must contain exactly its evaluation_id folder" % example)
    eval_dir = children[0]
    manifest_path = eval_dir / "manifest.json"
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, Mapping):
        raise VerificationError("evaluation manifest must be an object")
    _validate_dynamic_manifest_fields(manifest, eval_dir)
    if manifest.get("status") != "OK" or manifest.get("evaluation_id") != evaluation_id:
        raise VerificationError("evaluation manifest is partial or disagrees with summary")
    fingerprint = manifest.get("result_fingerprint")
    if not isinstance(fingerprint, str) or SHA256_RE.fullmatch(fingerprint) is None:
        raise VerificationError("evaluation manifest has no valid result_fingerprint")
    counts = manifest.get("counts")
    expected_counts = {
        "targets": 500,
        "study_dates": 243,
        "panel_cells": 121500,
        "factors": len(EXPECTED_FACTORS[example]),
        "signal_rows": 121500 * len(EXPECTED_FACTORS[example]),
        "label_rows": 121500 * len(LABEL_PERIODS),
    }
    if not isinstance(counts, Mapping):
        raise VerificationError("evaluation manifest has no counts object")
    for key, expected in expected_counts.items():
        if type(counts.get(key)) is not int or counts.get(key) != expected:
            raise VerificationError("evaluation manifest count %s=%r, expected %d" % (key, counts.get(key), expected))
    for key in ("result_schema_version", "evaluation_config_schema_version"):
        if type(manifest.get(key)) is not int or manifest.get(key) != 1:
            raise VerificationError("evaluation manifest %s is unknown or unsupported" % key)
    if manifest.get("api_version") != "1.0":
        raise VerificationError("evaluation manifest API version is unknown or unsupported")
    if manifest.get("label_mode") != "next_open_to_open":
        raise VerificationError("evaluation manifest label mode is unknown or unsupported")
    if manifest.get("labels") != list(LABEL_PERIODS):
        raise VerificationError("evaluation forward-return labels differ from the full-mode contract")
    spec = manifest.get("spec")
    targets = spec.get("targets") if isinstance(spec, Mapping) else None
    if targets != inputs["symbols"]:
        raise VerificationError("evaluation spec target order differs from the fixed 500-symbol selection")
    if (
        not isinstance(spec, Mapping)
        or spec.get("label") != "next_open_to_open"
        or spec.get("periods") != [1, 5, 20]
    ):
        raise VerificationError("evaluation spec label/periods differ from the full v1 contract")
    if not isinstance(manifest.get("inputs"), Mapping):
        raise VerificationError("evaluation manifest lacks input fingerprints")
    groups = manifest["inputs"].get("groups")
    if not isinstance(groups, Mapping) or set(groups) != set(inputs["symbols"]):
        raise VerificationError("evaluation input group metadata does not cover the fixed 500 symbols")
    if any(not isinstance(group, str) or not group for group in groups.values()):
        raise VerificationError("evaluation input group metadata has an invalid group label")
    tables = manifest.get("tables")
    if not isinstance(tables, Mapping) or set(tables) != {name[:-4] for name in EVALUATION_CSVS}:
        raise VerificationError("evaluation manifest table set is missing or unknown")
    exports = manifest.get("exports")
    if exports != list(EVALUATION_EXPORTS):
        raise VerificationError("evaluation manifest export set/order differs from full mode")
    expected_files = {"manifest.json", *EVALUATION_EXPORTS}
    actual_files = {path.name for path in eval_dir.iterdir() if path.is_file()}
    actual_dirs = [path.name for path in eval_dir.iterdir() if path.is_dir()]
    if actual_files != expected_files or actual_dirs:
        raise VerificationError("evaluation output file inventory is partial or contains unknown products")

    csv_records = []
    for filename in EVALUATION_CSVS:
        table = tables.get(filename[:-4])
        if not isinstance(table, Mapping):
            raise VerificationError("evaluation manifest table metadata is malformed for %s" % filename)
        csv_records.append(_validate_eval_csv(eval_dir / filename, filename, table))
        linked_count = {
            "signals.csv": "signal_rows",
            "labels.csv": "label_rows",
            "ic.csv": "ic_rows",
            "diagnostics.csv": "diagnostics",
        }.get(filename)
        if linked_count and type(table.get("rows")) is int and table["rows"] != counts.get(linked_count):
            raise VerificationError(
                "%s table rows disagree with manifest counts.%s" % (filename, linked_count)
            )
    png_records = _validate_pngs(eval_dir)
    return {
        "status": "OK",
        "directory": str(eval_dir),
        "evaluation_id": evaluation_id,
        "result_fingerprint": fingerprint,
        "counts": dict(counts),
        "labels": list(manifest["labels"]),
        "manifest": manifest,
        "csv_files": csv_records,
        "png_files": png_records,
    }


def _summary_report_paths(example: str, summary: Mapping[str, Any], root: Path, errors: List[str]) -> List[Path]:
    return _expected_report_paths(example, summary, root, errors)


def _verify_run(example: str, input_path: Path, inputs: Mapping[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    errors: List[str] = []
    try:
        root = _resolve_example_dir(input_path)
    except VerificationError as exc:
        return {"valid": False, "input_path": str(input_path), "errors": [str(exc)]}, {}
    record: Dict[str, Any] = {"valid": False, "directory": str(root), "errors": errors}
    internal: Dict[str, Any] = {"root": root}
    try:
        summary = _read_json(root / "summary.json")
        if not isinstance(summary, Mapping):
            raise VerificationError("summary.json must be an object")
        internal["summary"] = dict(summary)
    except (OSError, ValueError, json.JSONDecodeError, VerificationError) as exc:
        errors.append("could not read summary.json: %s" % exc)
        record["errors"] = errors
        return record, internal
    summary = internal["summary"]
    output_dir = summary.get("output_dir")
    if example in ("025", "026"):
        if not isinstance(output_dir, str) or not output_dir:
            errors.append("%s summary.output_dir must identify its output directory" % example)
        else:
            try:
                if Path(output_dir).expanduser().resolve() != root.resolve():
                    errors.append("%s summary.output_dir does not match the run directory" % example)
            except OSError:
                errors.append("%s summary.output_dir cannot be resolved" % example)
    elif summary.get("output") != "factor_values.csv":
        errors.append("027 summary.output does not identify factor_values.csv")
    if example == "027":
        elapsed = summary.get("elapsed_seconds")
        if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed <= 0:
            errors.append("027 summary.elapsed_seconds must be a finite positive duration")
    record["example"] = example
    record["summary"] = {
        "status": summary.get("status"),
        "factor_mode": summary.get("factor_mode"),
        "symbols": summary.get("symbols"),
        "dates": summary.get("dates"),
        "factor_calculation": summary.get("factor_calculation"),
        "broker": summary.get("broker"),
    }
    _expect(summary.get("status") == "COMPLETED", errors, "summary status is not COMPLETED")
    _expect(summary.get("factor_mode") == "native", errors, "F-mode factor_mode is not native")
    _expect(summary.get("factor_calculation") == "RAN", errors, "factor_calculation is not RAN")
    _expect(type(summary.get("symbols")) is int and summary.get("symbols") == 500, errors, "summary symbol count is not 500")
    _expect(type(summary.get("dates")) is int and summary.get("dates") == 243, errors, "summary date count is not 243")
    broker = summary.get("broker")
    _expect(
        isinstance(broker, Mapping)
        and set(broker) == {"cancel", "submit"}
        and all(type(broker.get(key)) is int and broker.get(key) == 0 for key in ("cancel", "submit")),
        errors,
        "summary broker does not report zero orders",
    )
    if example in ("025", "026"):
        _expect(summary.get("evaluation_status") == "OK", errors, "evaluation status is not exactly OK")
        factor_classes = summary.get("factor_classes")
        _expect(
            isinstance(factor_classes, Mapping)
            and tuple(factor_classes.keys()) == EXPECTED_FACTORS[example]
            and all(isinstance(value, str) and value for value in factor_classes.values()),
            errors,
            "factor_classes are missing, unknown, or reordered",
        )
    else:
        _expect(summary.get("factor") == "alpha003", errors, "027 summary factor is not alpha003")
        _expect(summary.get("operator_profile") == "alpha101-v2", errors, "027 summary operator_profile is not alpha101-v2")
        _expect(isinstance(summary.get("indicator"), str) and "Alpha003" in summary.get("indicator", ""), errors, "027 summary indicator is unknown")
        _expect(
            type(summary.get("cells")) is int and summary.get("cells") == 121500,
            errors,
            "027 summary cells is not 121500",
        )

    factor = _factor_csv(root / "factor_values.csv", inputs, example)
    internal["factor"] = factor
    record["factor_values"] = {key: value for key, value in factor.items() if key not in ("values", "timestamps", "errors")}
    errors.extend(factor["errors"])
    if example == "027":
        finite = factor["factor_counts"].get("alpha003", {}).get("finite")
        if summary.get("finite") != finite:
            errors.append("027 summary finite count differs from factor_values.csv")

    expected_reports = _summary_report_paths(example, summary, root, errors)
    for report_path in expected_reports:
        if not report_path.is_file() or report_path.stat().st_size <= 0:
            errors.append("required report HTML is missing or empty: %s" % report_path.name)
    internal["report_paths"] = expected_reports
    try:
        semantics = _read_report_semantics(root, expected_reports)
        internal["report_semantics"] = semantics
        record["reports"] = {
            name: {
                "semantic_digest": item["semantic_digest"],
                "html_sha256": semantics["html"][name]["sha256"],
                "chart_data_keys": sorted(semantics["html"][name]["chart_data"].keys()),
                "table_count": len(semantics["html"][name]["tables"]),
            }
            for name, item in semantics["models"].items()
        }
    except VerificationError as exc:
        errors.append(str(exc))

    try:
        evaluation = _evaluation(example, root, summary, inputs)
        internal["evaluation"] = evaluation
        record["evaluation"] = {key: value for key, value in evaluation.items() if key != "manifest"}
    except (OSError, csv.Error, ValueError, VerificationError, KeyError) as exc:
        errors.append("evaluation outputs: %s" % exc)

    dynamic_fields = SUMMARY_DYNAMIC_FIELDS[example]
    internal["normalized_summary"] = {key: value for key, value in summary.items() if key not in dynamic_fields}
    expected_top = {
        "summary.json",
        "factor_values.csv",
        REPORT_SEMANTICS_NAME,
        *EXPECTED_REPORTS[example],
    }
    if example in ("025", "026"):
        expected_top.add("evaluation")
    actual_top = {path.name for path in root.iterdir()}
    if actual_top != expected_top:
        errors.append(
            "run output inventory differs from full mode (missing=%s extra=%s)"
            % (sorted(expected_top - actual_top), sorted(actual_top - expected_top))
        )
    record["valid"] = not errors
    record["errors"] = errors
    return record, internal


def _normalized_manifest(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in manifest.items() if key not in MANIFEST_DYNAMIC_FIELDS}


def _compare_factor(left: Mapping[str, Any], right: Mapping[str, Any]) -> Dict[str, Any]:
    left_factor = left.get("factor", {})
    right_factor = right.get("factor", {})
    result: Dict[str, Any] = {"columns_equal": False, "row_order_equal": False, "values_equal": False, "first_mismatch": None}
    if left_factor.get("columns") != right_factor.get("columns"):
        return result
    result["columns_equal"] = True
    left_timestamps = left_factor.get("timestamps", [])
    right_timestamps = right_factor.get("timestamps", [])
    result["row_order_equal"] = left_timestamps == right_timestamps
    if not result["row_order_equal"]:
        result["first_mismatch"] = {"field": "date_timestamps"}
        return result
    lvalues = left_factor.get("values", {})
    rvalues = right_factor.get("values", {})
    for factor in left_factor.get("columns", [])[2:]:
        if lvalues.get(factor) != rvalues.get(factor):
            mismatch = next(
                (index for index, pair in enumerate(zip(lvalues.get(factor, ()), rvalues.get(factor, ()))) if pair[0] != pair[1]),
                None,
            )
            result["first_mismatch"] = {"factor": factor, "cell_index": mismatch}
            return result
    result["row_order_equal"] = left_factor.get("rows") == right_factor.get("rows")
    result["values_equal"] = True
    return result


def _compare_eval_table(left_path: Path, right_path: Path, filename: str) -> Dict[str, Any]:
    left_header = TABLE_COLUMNS[filename]
    right_header = TABLE_COLUMNS[filename]
    result: Dict[str, Any] = {"columns_equal": left_header == right_header, "row_order_equal": False, "rows_compared": 0, "first_mismatch": None}
    if not result["columns_equal"]:
        return result
    left_iter = _read_eval_rows(left_path, left_header, filename)
    right_iter = _read_eval_rows(right_path, right_header, filename)
    sentinel = object()
    for row_index, (left_row, right_row) in enumerate(zip_longest(left_iter, right_iter, fillvalue=sentinel), start=1):
        if left_row is sentinel or right_row is sentinel:
            result["first_mismatch"] = {"row": row_index, "reason": "row_count"}
            return result
        result["rows_compared"] = row_index
        if left_row != right_row:
            differing = [
                field
                for field, left_value, right_value in zip(left_header, left_row, right_row)
                if left_value != right_value
            ]
            result["first_mismatch"] = {"row": row_index, "fields": differing}
            return result
    result["row_order_equal"] = True
    return result


def zip_longest(*iterables: Iterable[Any], fillvalue: Any = None) -> Iterator[Tuple[Any, ...]]:
    """Small local zip_longest to keep this verifier standard-library-only."""
    iterators = [iter(iterable) for iterable in iterables]
    active = len(iterators)
    while active:
        values: List[Any] = []
        for index, iterator in enumerate(iterators):
            if iterator is None:
                values.append(fillvalue)
                continue
            try:
                values.append(next(iterator))
            except StopIteration:
                iterators[index] = None  # type: ignore[assignment]
                active -= 1
                values.append(fillvalue)
        if active:
            yield tuple(values)


def _compare_pair(example: str, left: Mapping[str, Any], right: Mapping[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    if not left.get("valid") or not right.get("valid"):
        return {"valid": False, "errors": ["both runs must pass single-run validation before comparison"]}
    ldata = left["internal"]
    rdata = right["internal"]
    summary_equal = _canonical_json(ldata["normalized_summary"]) == _canonical_json(rdata["normalized_summary"])
    if not summary_equal:
        errors.append("summary metadata differs after the explicit path/time allowlist")
    left_eval = ldata.get("evaluation", {})
    right_eval = rdata.get("evaluation", {})
    evaluation_ids_equal = left_eval.get("evaluation_id") == right_eval.get("evaluation_id")
    fingerprints_equal = left_eval.get("result_fingerprint") == right_eval.get("result_fingerprint")
    if not evaluation_ids_equal:
        errors.append("evaluation_id differs (v1 identity must remain stable)")
    if not fingerprints_equal:
        errors.append("result_fingerprint differs (v1 identity must remain stable)")
    manifests_equal = True
    if example in ("025", "026"):
        manifests_equal = _canonical_json(_normalized_manifest(left_eval["manifest"])) == _canonical_json(
            _normalized_manifest(right_eval["manifest"])
        )
        if not manifests_equal:
            errors.append("evaluation manifest metadata differs after the explicit dynamic-field allowlist")
        eval_dir_left = Path(left_eval["directory"])
        eval_dir_right = Path(right_eval["directory"])
        table_results = {
            filename: _compare_eval_table(eval_dir_left / filename, eval_dir_right / filename, filename)
            for filename in EVALUATION_CSVS
        }
        for filename, item in table_results.items():
            if not item["columns_equal"] or not item["row_order_equal"]:
                errors.append("evaluation table differs: %s" % filename)
    else:
        table_results = {}

    factor_result = _compare_factor(ldata, rdata)
    if not all(factor_result[key] for key in ("columns_equal", "row_order_equal", "values_equal")):
        errors.append("factor_values.csv differs by columns, row order, NaN mask, or exact float64 cell")

    left_reports = ldata.get("report_semantics", {}).get("models", {})
    right_reports = rdata.get("report_semantics", {}).get("models", {})
    report_results: Dict[str, Any] = {}
    if tuple(left_reports) != tuple(right_reports):
        errors.append("HTML report model names/order differ")
    else:
        for name in left_reports:
            left_model = left_reports[name]
            right_model = right_reports[name]
            left_html = ldata["report_semantics"]["html"][name]
            right_html = rdata["report_semantics"]["html"][name]
            model_equal = left_model["payload_json"] == right_model["payload_json"]
            digest_equal = left_model["semantic_digest"] == right_model["semantic_digest"]
            plot_data_equal = left_html["chart_data_json"] == right_html["chart_data_json"]
            tables_equal = left_html["tables"] == right_html["tables"]
            report_results[name] = {
                "model_tables_and_series_equal": model_equal,
                "semantic_digest_equal": digest_equal,
                "embedded_plot_data_equal": plot_data_equal,
                "rendered_table_cells_equal": tables_equal,
            }
            if not (model_equal and digest_equal and plot_data_equal and tables_equal):
                errors.append("HTML report model or embedded products differ: %s" % name)
    return {
        "valid": not errors,
        "errors": errors,
        "summary_metadata_equal": summary_equal,
        "evaluation_id_equal": evaluation_ids_equal,
        "result_fingerprint_equal": fingerprints_equal,
        "evaluation_manifest_equal": manifests_equal,
        "factor_values": factor_result,
        "evaluation_tables": table_results,
        "reports": report_results,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--run", action="append", type=_parse_assignment, help="one-run check: repeat EXAMPLE=PATH for 025/026/027")
    parser.add_argument("--baseline", action="append", type=_parse_assignment, help="A/B baseline: repeat EXAMPLE=PATH for 025/026/027")
    parser.add_argument("--candidate", action="append", type=_parse_assignment, help="A/B candidate: repeat EXAMPLE=PATH for 025/026/027")
    parser.add_argument("--output", type=Path, help="write a new JSON result file (must not already exist)")
    return parser


def _run_record(example: str, path: Path, inputs: Mapping[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    public, internal = _verify_run(example, path, inputs)
    return public, internal


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    mode: str
    try:
        if args.run:
            if args.baseline or args.candidate:
                raise VerificationError("--run cannot be combined with --baseline/--candidate")
            mode = "single-run"
            run_paths = {"run": _collect_assignments(args.run, "--run", require_all=False)}
        else:
            if not args.baseline or not args.candidate:
                raise VerificationError("provide all three --run arguments or all three --baseline and --candidate arguments")
            mode = "ab-pair"
            run_paths = {
                "baseline": _collect_assignments(args.baseline, "--baseline"),
                "candidate": _collect_assignments(args.candidate, "--candidate"),
            }
    except (VerificationError, OSError, csv.Error, ValueError, TypeError, KeyError) as exc:
        result = {
            "schema": "iteration49.fixed500_output_verification.v1",
            "status": "FAIL",
            "mode": "invalid-invocation",
            "valid": False,
            "global_errors": [str(exc)],
        }
        _emit(result, None)
        return 1

    if args.output:
        destination = args.output.expanduser().resolve()
        protected_roots = [args.data_root.expanduser().resolve()]
        protected_paths = [args.selection.expanduser().resolve()]
        for paths in run_paths.values():
            for path in paths.values():
                resolved_input = path.expanduser().resolve()
                protected_roots.extend((resolved_input, resolved_input / "example"))
                try:
                    protected_roots.append(_resolve_example_dir(path))
                except VerificationError:
                    continue
        if destination.exists() or any(_is_within(destination, root) for root in protected_roots) or any(
            destination == path for path in protected_paths
        ):
            result = {
                "schema": "iteration49.fixed500_output_verification.v1",
                "status": "FAIL",
                "mode": "invalid-invocation",
                "valid": False,
                "global_errors": [
                    "--output must be a new file outside fixed inputs and every compared run directory"
                ],
            }
            _emit(result, None)
            return 1

    try:
        inputs = _load_fixed_inputs(args.data_root, args.selection)
    except (VerificationError, OSError, csv.Error, ValueError, TypeError, KeyError) as exc:
        result = {
            "schema": "iteration49.fixed500_output_verification.v1",
            "status": "FAIL",
            "mode": mode,
            "valid": False,
            "global_errors": [str(exc)],
        }
        _emit(result, args.output)
        return 1

    runs: Dict[str, Dict[str, Any]] = {}
    internal: Dict[str, Dict[str, Any]] = {}
    for side, paths in run_paths.items():
        runs[side] = {}
        internal[side] = {}
        for example in paths:
            try:
                public, private = _run_record(example, paths[example], inputs)
            except Exception as exc:
                public = {
                    "valid": False,
                    "input_path": str(paths[example]),
                    "errors": ["validation failed closed (%s): %s" % (type(exc).__name__, exc)],
                }
                private = {}
            runs[side][example] = public
            private["valid"] = public.get("valid", False)
            internal[side][example] = private
    comparisons: Dict[str, Any] = {}
    if mode == "ab-pair":
        for example in EXPECTED_EXAMPLES:
            left_public = dict(runs["baseline"][example])
            right_public = dict(runs["candidate"][example])
            left_public["internal"] = internal["baseline"][example]
            right_public["internal"] = internal["candidate"][example]
            comparisons[example] = _compare_pair(example, left_public, right_public)

    all_runs_valid = all(run.get("valid") for side in runs.values() for run in side.values())
    all_pairs_valid = mode != "ab-pair" or all(item.get("valid") for item in comparisons.values())
    valid = all_runs_valid and all_pairs_valid
    result = {
        "schema": "iteration49.fixed500_output_verification.v1",
        "status": "PASS" if valid else "FAIL",
        "mode": mode,
        "valid": valid,
        "scope_complete": all(set(paths) == set(EXPECTED_EXAMPLES) for paths in run_paths.values()),
        "fixed_input": {
            "selection": inputs["selection_path"],
            "selection_sha256": inputs["selection_sha256"],
            "data_root": inputs["data_root"],
            "manifest_sha256": inputs["manifest_sha256"],
            "calendar_sha256": inputs["calendar_sha256"],
            "symbol_count": len(inputs["symbols"]),
            "date_count": len(inputs["dates"]),
            "grid_cells": inputs["grid_cells"],
            "ordered_symbols_sha256": hashlib.sha256(("\n".join(inputs["symbols"]) + "\n").encode("utf-8")).hexdigest(),
        },
        "runs": runs,
        "comparisons": comparisons,
        "limitations": [
            "This readback verifies outputs and A/B semantic equivalence; it does not verify benchmark timing or source/runtime provenance.",
            "Report semantic equality requires report_semantics.json captured from the actual ReportDocument passed to the HTML writer.",
            "PNG files are parsed and checked for valid dimensions/CRC/zlib image data; pixel identity is not required.",
        ],
    }
    _emit(result, args.output)
    return 0 if valid else 1


def _emit(result: Mapping[str, Any], output: Optional[Path]) -> None:
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if output is None:
        sys.stdout.write(rendered)
        return
    destination = output.expanduser().resolve()
    if destination.exists():
        raise VerificationError("output already exists: %s" % destination)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        raise VerificationError("could not write report JSON: %s" % exc) from exc
    print("result: %s" % destination)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VerificationError as exc:
        print("VERIFICATION_ERROR: %s" % exc, file=sys.stderr)
        raise SystemExit(2) from None
