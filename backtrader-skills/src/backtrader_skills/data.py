"""Controlled local dataset inspection, immutable registration, and bounded preview."""

from __future__ import annotations

import csv
import io
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .canonical import (
    atomic_write_bytes,
    atomic_write_json,
    bytes_hash,
    canonical_hash,
    file_hash,
    load_json,
    resolve_inside,
    safe_identifier,
)
from .errors import ContractError, IntegrityError, PathPolicyError
from .runtime import RuntimePaths
from .state import utc_now

ADAPTERS = {
    "generic_csv",
    "backtrader_csv",
    "yahoo_csv",
    "mt5_csv",
    "pandas",
    "pandas_custom_lines",
}
ROLES = {"execution", "signal", "benchmark", "hedge", "cash_proxy"}
ALIGNMENTS = {"intersection", "left", "explicit_asof"}
STANDARD_LINES = ("datetime", "open", "high", "low", "close", "volume", "openinterest")
REQUIRED_LINES = ("datetime", "open", "high", "low", "close")
DATETIME_FORMATS = (
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y%m%d",
    "%Y.%m.%d %H:%M:%S",
    "%Y.%m.%d",
    "%m/%d/%Y",
)


def _slug_header(value: str) -> str:
    value = value.strip().strip("<>").lower()
    return re.sub(r"[^a-z0-9_]+", "_", value).strip("_")


HEADER_ALIASES = {
    "date": "datetime",
    "datetime": "datetime",
    "time": "time",
    "timestamp": "datetime",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "adj_close": "close",
    "volume": "volume",
    "tickvol": "volume",
    "tick_volume": "volume",
    "vol": "volume",
    "openinterest": "openinterest",
    "open_interest": "openinterest",
}


@dataclass(frozen=True)
class ParsedFeed:
    rows: list[dict[str, str]]
    canonical_bytes: bytes
    summary: dict[str, Any]
    quality: dict[str, Any]
    mapping: dict[str, str]


class DataRegistry:
    """Manage opaque roots and immutable, content-addressed dataset manifests."""

    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths.ensure()

    def _roots(self) -> dict[str, Any]:
        if not self.paths.data_roots.is_file():
            return {"schema_version": "data-roots-v1", "roots": {}}
        value = load_json(self.paths.data_roots)
        if value.get("schema_version") != "data-roots-v1":
            raise IntegrityError("unsupported data root registry version")
        return cast(dict[str, Any], value)

    def add_root(self, directory: Path, *, root_id: str | None = None) -> dict[str, Any]:
        resolved = directory.resolve(strict=True)
        if not resolved.is_dir():
            raise PathPolicyError("data root must be a directory")
        registry = self._roots()
        if root_id is None:
            root_id = f"root_{canonical_hash({'path': str(resolved)})[:16]}"
        safe_identifier(root_id, field="root_id")
        previous = registry["roots"].get(root_id)
        if previous and Path(previous["local_path"]).resolve() != resolved:
            raise IntegrityError("root_id is already bound to a different directory")
        registry["roots"][root_id] = {
            "local_path": str(resolved),
            "read_only": True,
            "registered_at": previous.get("registered_at") if previous else utc_now(),
        }
        atomic_write_json(self.paths.data_roots, registry)
        return {"root_id": root_id, "read_only": True}

    def root_path(self, root_id: str) -> Path:
        safe_identifier(root_id, field="root_id")
        record = self._roots()["roots"].get(root_id)
        if record is None:
            raise PathPolicyError(f"unknown data root: {root_id}")
        path = Path(record["local_path"]).resolve(strict=True)
        if not path.is_dir():
            raise PathPolicyError("configured data root is unavailable")
        return path

    def inspect(self, feed_spec: dict[str, Any], *, sample_limit: int = 20) -> dict[str, Any]:
        _validate_feed_spec(feed_spec)
        source = feed_spec["source"]
        source_path = resolve_inside(
            self.root_path(source["root_id"]), source["relative_path"], must_exist=True
        )
        if not source_path.is_file():
            raise PathPolicyError("dataset source must be a regular file")
        parsed = _parse_feed(source_path, feed_spec, sample_limit=sample_limit)
        return {
            "schema_version": "dataset-inspection-v1",
            "feed": feed_spec["name"],
            "source": {
                "root_id": source["root_id"],
                "relative_path": source["relative_path"],
                "sha256": file_hash(source_path),
                "bytes": source_path.stat().st_size,
            },
            "mapping": parsed.mapping,
            "summary": parsed.summary,
            "quality": parsed.quality,
            "sample": parsed.rows[:sample_limit],
        }

    def register(self, data_spec: dict[str, Any]) -> dict[str, Any]:
        normalized_spec = _validate_data_spec(data_spec)
        registered_feeds: list[dict[str, Any]] = []
        for feed_spec in normalized_spec["feeds"]:
            source = feed_spec["source"]
            source_path = resolve_inside(
                self.root_path(source["root_id"]), source["relative_path"], must_exist=True
            )
            if not source_path.is_file():
                raise PathPolicyError("dataset source must be a regular file")
            source_sha = file_hash(source_path)
            parsed = _parse_feed(source_path, feed_spec)
            if parsed.quality["errors"]:
                raise ContractError(
                    f"feed {feed_spec['name']} failed quality checks",
                    details={"diagnostics": parsed.quality["errors"]},
                )
            object_sha = bytes_hash(parsed.canonical_bytes)
            object_name = f"{object_sha}.csv"
            object_path = self.paths.dataset_objects / object_name
            if object_path.exists():
                if file_hash(object_path) != object_sha:
                    raise IntegrityError("content-addressed dataset object is corrupt")
            else:
                atomic_write_bytes(object_path, parsed.canonical_bytes)
            registered_feeds.append(
                {
                    "name": feed_spec["name"],
                    "symbol": feed_spec["symbol"],
                    "role": feed_spec["role"],
                    "tradable": feed_spec["tradable"],
                    "source": {
                        "root_id": source["root_id"],
                        "relative_path": source["relative_path"],
                        "source_type": source.get("source_type", "local_file"),
                        "sha256": source_sha,
                        "bytes": source_path.stat().st_size,
                    },
                    "adapter": feed_spec["format"],
                    "format": "canonical_csv_v1",
                    "object": {"sha256": object_sha, "file": object_name},
                    "timeframe": feed_spec["timeframe"],
                    "compression": feed_spec["compression"],
                    "timezone": feed_spec["timezone"],
                    "datetime_format": "%Y-%m-%dT%H:%M:%S%z",
                    "columns": parsed.mapping,
                    "custom_lines": feed_spec.get("custom_lines", []),
                    "fromdate": feed_spec.get("fromdate"),
                    "todate": feed_spec.get("todate"),
                    "resample": feed_spec.get("resample"),
                    "replay": feed_spec.get("replay"),
                    "transforms": feed_spec.get("transforms", []),
                    "summary": parsed.summary,
                    "quality": parsed.quality,
                }
            )
        alignment_evidence = _validate_alignment(
            registered_feeds,
            normalized_spec["master_feed"],
            normalized_spec["alignment"],
            normalized_spec["minimum_overlap"],
        )
        spec_hash = canonical_hash(normalized_spec)
        transform_ids = sorted(
            {transform for feed in normalized_spec["feeds"] for transform in feed["transforms"]}
        )
        transforms = [{"profile_id": transform, "parameters": {}} for transform in transform_ids]
        provenance = {
            "parser": "stdlib-csv-v1",
            "alignment_evidence": alignment_evidence,
            "source_hashes": [
                {
                    "feed": feed["name"],
                    "sha256": feed["source"]["sha256"],
                }
                for feed in registered_feeds
            ],
        }
        semantic_payload = {
            "schema_version": "dataset-manifest-v1",
            "feeds": [
                {key: value for key, value in feed.items() if key not in {"source", "quality"}}
                | {
                    "source_sha256": feed["source"]["sha256"],
                    "source_relative_path": feed["source"]["relative_path"],
                }
                for feed in registered_feeds
            ],
            "master_feed": normalized_spec["master_feed"],
            "alignment": {
                "mode": normalized_spec["alignment"],
                "minimum_overlap": normalized_spec["minimum_overlap"],
            },
            "transforms": transforms,
            "parser": provenance["parser"],
        }
        semantic_hash = canonical_hash(semantic_payload)
        dataset_id = f"ds_{semantic_hash}"
        diagnostics = [
            {
                "feed": feed["name"],
                **diagnostic,
            }
            for feed in registered_feeds
            for diagnostic in (feed["quality"]["errors"] + feed["quality"]["warnings"])
        ]
        manifest = {
            "schema_version": "dataset-manifest-v1",
            "dataset_id": dataset_id,
            "spec_hash": spec_hash,
            "semantic_hash": semantic_hash,
            "manifest_hash": "",
            "feeds": registered_feeds,
            "master_feed": normalized_spec["master_feed"],
            "alignment": {
                "mode": normalized_spec["alignment"],
                "minimum_overlap": normalized_spec["minimum_overlap"],
            },
            "status": "valid",
            "diagnostics": diagnostics,
            "transforms": transforms,
            "provenance": provenance,
            "extensions": {
                "backtrader_skills": {
                    "product_version": "0.1.0",
                    "created_at": utc_now(),
                    "license": normalized_spec["license"],
                    "sensitivity": normalized_spec["sensitivity"],
                    "derived_writes_allowed": normalized_spec["derived_writes_allowed"],
                    "compatibility": {"strategy_spec_v1": True},
                }
            },
        }
        hash_payload = dict(manifest)
        hash_payload.pop("manifest_hash")
        manifest["manifest_hash"] = canonical_hash(hash_payload)
        destination = self.paths.dataset_manifests / f"{dataset_id}.json"
        if destination.exists():
            existing = load_json(destination)
            if existing["semantic_hash"] != semantic_hash:
                raise IntegrityError("dataset_id collision")
            return cast(dict[str, Any], existing)
        atomic_write_json(destination, manifest)
        return manifest

    def get_manifest(self, dataset_id: str, *, verify: bool = True) -> dict[str, Any]:
        safe_identifier(dataset_id, field="dataset_id")
        path = self.paths.dataset_manifests / f"{dataset_id}.json"
        if not path.is_file():
            raise ContractError(f"unknown dataset_id: {dataset_id}")
        manifest = load_json(path)
        if verify:
            self.verify_manifest(manifest)
        return cast(dict[str, Any], manifest)

    def verify_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        expected_hash = manifest.get("manifest_hash")
        hash_payload = dict(manifest)
        hash_payload.pop("manifest_hash", None)
        if expected_hash != canonical_hash(hash_payload):
            raise IntegrityError("DatasetManifest hash is invalid")
        for feed in manifest["feeds"]:
            source = feed["source"]
            source_path = resolve_inside(
                self.root_path(source["root_id"]), source["relative_path"], must_exist=True
            )
            if file_hash(source_path) != source["sha256"]:
                raise IntegrityError(f"dataset source changed after registration: {feed['name']}")
            object_path = resolve_inside(
                self.paths.dataset_objects, feed["object"]["file"], must_exist=True
            )
            if file_hash(object_path) != feed["object"]["sha256"]:
                raise IntegrityError(f"dataset object is corrupt: {feed['name']}")
        return {
            "dataset_id": manifest["dataset_id"],
            "manifest_hash": expected_hash,
            "verified": True,
        }

    def preview(self, dataset_id: str, *, rows: int = 5) -> dict[str, Any]:
        if rows < 1 or rows > 50:
            raise ContractError("preview rows must be between 1 and 50")
        manifest = self.get_manifest(dataset_id)
        result: list[dict[str, Any]] = []
        for feed in manifest["feeds"]:
            object_path = resolve_inside(
                self.paths.dataset_objects, feed["object"]["file"], must_exist=True
            )
            with object_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                sample = []
                for index, row in enumerate(reader):
                    if index >= rows:
                        break
                    sample.append(row)
            result.append(
                {
                    "name": feed["name"],
                    "symbol": feed["symbol"],
                    "columns": list(sample[0]) if sample else [],
                    "sample": sample,
                    "summary": feed["summary"],
                    "quality": feed["quality"],
                }
            )
        return {
            "schema_version": "dataset-preview-v1",
            "dataset_id": dataset_id,
            "manifest_hash": manifest["manifest_hash"],
            "feeds": result,
            "truncated": True,
        }


def _validate_data_spec(value: dict[str, Any]) -> dict[str, Any]:
    source_value = dict(value)
    if "feeds" not in source_value and {
        "root_id",
        "relative_path",
    }.issubset(source_value):
        mapping = source_value.get("feed_mapping", source_value.get("columns", {}))
        source_value["feeds"] = [
            {
                "name": source_value.get("name", "data0"),
                "symbol": source_value.get("symbol", "data0"),
                "root_id": source_value["root_id"],
                "relative_path": source_value["relative_path"],
                "format": source_value.get("format", "generic_csv"),
                "columns": mapping,
                "timeframe": source_value.get("timeframe", "days"),
                "timezone": source_value.get("timezone", "UTC"),
                "transforms": source_value.get("transforms", source_value.get("transform", [])),
            }
        ]
    if source_value.get("schema_version") not in {"dataset-manifest-v1", "data-spec-v1"}:
        raise ContractError("DataSpec schema_version must be data-spec-v1")
    feeds = source_value.get("feeds")
    if not isinstance(feeds, list) or not feeds:
        raise ContractError("DataSpec must contain at least one feed")
    normalized_feeds = [_validate_feed_spec(feed) for feed in feeds]
    names = [feed["name"] for feed in normalized_feeds]
    if len(names) != len(set(names)):
        raise ContractError("feed names must be unique")
    master = source_value.get("master_feed", names[0])
    if master not in names:
        raise ContractError("master_feed must name one of the feeds")
    alignment = source_value.get("alignment", "intersection")
    if alignment not in ALIGNMENTS:
        raise ContractError(f"unsupported alignment: {alignment}")
    minimum_overlap = float(source_value.get("minimum_overlap", 1.0))
    if not 0.0 <= minimum_overlap <= 1.0:
        raise ContractError("minimum_overlap must be between 0 and 1")
    return {
        "schema_version": "data-spec-v1",
        "feeds": normalized_feeds,
        "master_feed": master,
        "alignment": alignment,
        "minimum_overlap": minimum_overlap,
        "license": str(source_value.get("license", "unspecified")),
        "sensitivity": str(source_value.get("sensitivity", "internal")),
        "derived_writes_allowed": bool(source_value.get("derived_writes_allowed", True)),
    }


def _validate_alignment(
    feeds: list[dict[str, Any]],
    master_feed: str,
    alignment: str,
    minimum_overlap: float,
) -> dict[str, Any]:
    def parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    ranges = {
        feed["name"]: (
            parse(feed["summary"]["first_datetime"]),
            parse(feed["summary"]["last_datetime"]),
        )
        for feed in feeds
    }
    common_start = max(value[0] for value in ranges.values())
    common_end = min(value[1] for value in ranges.values())
    master_start, master_end = ranges[master_feed]
    master_seconds = max((master_end - master_start).total_seconds(), 1.0)
    overlap_seconds = max((common_end - common_start).total_seconds(), 0.0)
    overlap_ratio = overlap_seconds / master_seconds
    if len(feeds) == 1:
        overlap_ratio = 1.0
    if common_end < common_start or overlap_ratio < minimum_overlap:
        raise ContractError(
            "feed ranges do not satisfy the declared alignment overlap",
            details={
                "alignment": alignment,
                "minimum_overlap": minimum_overlap,
                "observed_overlap": overlap_ratio,
            },
        )
    return {
        "alignment": alignment,
        "master_feed": master_feed,
        "minimum_overlap": minimum_overlap,
        "observed_overlap": overlap_ratio,
        "common_start": common_start.isoformat().replace("+00:00", "Z"),
        "common_end": common_end.isoformat().replace("+00:00", "Z"),
    }


def _validate_feed_spec(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("feed specification must be an object")
    name = safe_identifier(str(value.get("name", "")), field="feed name")
    symbol = str(value.get("symbol", name))
    role = value.get("role", "execution")
    if role not in ROLES:
        raise ContractError(f"unsupported feed role: {role}")
    adapter = value.get("format", value.get("adapter", "generic_csv"))
    if adapter not in ADAPTERS:
        raise ContractError(f"unsupported adapter: {adapter}")
    source = value.get("source", value)
    if not isinstance(source, dict):
        raise ContractError("feed source is required")
    root_id = safe_identifier(str(source.get("root_id", "")), field="root_id")
    relative_path = source.get("relative_path", source.get("path"))
    if not isinstance(relative_path, str) or not relative_path:
        raise ContractError("feed source path is required")
    path_value = Path(relative_path)
    if path_value.is_absolute() or ".." in path_value.parts:
        raise PathPolicyError("feed source path must be a safe relative path")
    source_type = source.get("source_type", source.get("type", "local_file"))
    if source_type not in {"local_file", "materialized_dataframe"}:
        raise ContractError(f"unsupported source type: {source_type}")
    timezone_name = str(value.get("timezone", "UTC"))
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise ContractError(f"unknown timezone: {timezone_name}") from error
    compression = int(value.get("compression", 1))
    if compression < 1:
        raise ContractError("compression must be positive")
    mapping = value.get("columns", {})
    if not isinstance(mapping, dict):
        raise ContractError("columns must be an object")
    transforms = value.get("transforms", value.get("transform", []))
    if isinstance(transforms, str):
        transforms = [transforms]
    if not isinstance(transforms, list):
        raise ContractError("transforms must be a list")
    if transforms:
        for transform in transforms:
            if transform not in {"drop_null_rows", "sort_datetime", "deduplicate_exact"}:
                raise ContractError(f"unsupported deterministic transform: {transform}")
    return {
        "name": name,
        "symbol": symbol,
        "role": role,
        "tradable": bool(value.get("tradable", role == "execution")),
        "source": {
            "root_id": root_id,
            "relative_path": relative_path,
            "source_type": source_type,
        },
        "format": adapter,
        "delimiter": value.get("delimiter"),
        "encoding": value.get("encoding", "utf-8-sig"),
        "datetime_format": value.get("datetime_format"),
        "columns": {str(key): str(item) for key, item in mapping.items()},
        "custom_lines": [str(item) for item in value.get("custom_lines", [])],
        "timeframe": str(value.get("timeframe", "days")),
        "compression": compression,
        "timezone": timezone_name,
        "fromdate": value.get("fromdate"),
        "todate": value.get("todate"),
        "resample": value.get("resample"),
        "replay": value.get("replay"),
        "transforms": list(transforms),
    }


def _detect_delimiter(sample: str, configured: str | None, adapter: str) -> str:
    if configured:
        if configured not in {",", "\t", ";", "|"}:
            raise ContractError("delimiter must be one of comma, tab, semicolon, or pipe")
        return configured
    if adapter == "mt5_csv" and "\t" in sample.splitlines()[0]:
        return "\t"
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
    except csv.Error:
        return ","


def _read_dict_rows(path: Path, feed_spec: dict[str, Any]) -> tuple[list[dict[str, str]], str]:
    encoding = feed_spec["encoding"]
    try:
        text = path.read_text(encoding=encoding)
    except (UnicodeDecodeError, LookupError) as error:
        raise ContractError(f"cannot decode dataset using {encoding}") from error
    delimiter = _detect_delimiter(text[:8192], feed_spec.get("delimiter"), feed_spec["format"])
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise ContractError("CSV header is required")
    rows = [dict(row) for row in reader]
    if not rows:
        raise ContractError("dataset contains no rows")
    return rows, delimiter


def _resolve_mapping(
    headers: Iterable[str], configured: dict[str, str], custom_lines: list[str]
) -> dict[str, str]:
    header_list = list(headers)
    normalized = {_slug_header(header): header for header in header_list}
    reverse_aliases: dict[str, str] = {}
    for normalized_name, original in normalized.items():
        reverse_aliases.setdefault(HEADER_ALIASES.get(normalized_name, normalized_name), original)
    mapping: dict[str, str] = {}
    for line in STANDARD_LINES:
        requested = configured.get(line)
        if requested is not None:
            if requested not in header_list:
                raise ContractError(f"configured column does not exist: {requested}")
            mapping[line] = requested
        elif line == "datetime" and "date" in normalized and "time" in normalized:
            mapping[line] = f"{normalized['date']}+{normalized['time']}"
        elif line in reverse_aliases:
            mapping[line] = reverse_aliases[line]
    for line in custom_lines:
        requested = configured.get(line, reverse_aliases.get(_slug_header(line)))
        if requested is None or requested not in header_list:
            raise ContractError(f"custom line column does not exist: {line}")
        mapping[line] = requested
    missing = [line for line in REQUIRED_LINES if line not in mapping]
    if missing:
        raise ContractError(f"required columns are missing: {', '.join(missing)}")
    return mapping


def _parse_datetime(raw: str, feed_spec: dict[str, Any]) -> datetime:
    configured = feed_spec.get("datetime_format")
    formats = (configured,) if configured else DATETIME_FORMATS
    parsed: datetime | None = None
    for date_format in formats:
        if date_format is None:
            continue
        try:
            parsed = datetime.strptime(raw.strip(), date_format)
            break
        except ValueError:
            continue
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        except ValueError as error:
            raise ContractError(f"unparseable datetime value: {raw!r}") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(feed_spec["timezone"]))
    return parsed.astimezone(timezone.utc)


def _parse_number(raw: str | None, *, line: str, required: bool) -> float | None:
    if raw is None or not raw.strip():
        if required:
            raise ContractError(f"missing numeric value for {line}")
        return None
    try:
        value = float(raw.replace(",", "").strip())
    except ValueError as error:
        raise ContractError(f"invalid numeric value for {line}: {raw!r}") from error
    if not math.isfinite(value):
        raise ContractError(f"non-finite numeric value for {line}")
    return value


def _format_number(value: float | None) -> str:
    if value is None:
        return ""
    return format(value, ".15g")


def _parse_boundary(value: str | None, feed_spec: dict[str, Any]) -> datetime | None:
    return _parse_datetime(value, feed_spec) if value else None


def _parse_feed(
    path: Path, feed_spec: dict[str, Any], *, sample_limit: int | None = None
) -> ParsedFeed:
    raw_rows, delimiter = _read_dict_rows(path, feed_spec)
    mapping = _resolve_mapping(raw_rows[0].keys(), feed_spec["columns"], feed_spec["custom_lines"])
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    normalized_rows: list[dict[str, Any]] = []
    fromdate = _parse_boundary(feed_spec.get("fromdate"), feed_spec)
    todate = _parse_boundary(feed_spec.get("todate"), feed_spec)
    for row_number, raw in enumerate(raw_rows, start=2):
        try:
            datetime_column = mapping["datetime"]
            if "+" in datetime_column and datetime_column not in raw:
                date_column, time_column = datetime_column.split("+", maxsplit=1)
                raw_datetime = f"{raw.get(date_column, '')} {raw.get(time_column, '')}"
            else:
                raw_datetime = raw.get(datetime_column, "")
            timestamp = _parse_datetime(raw_datetime, feed_spec)
            if fromdate and timestamp < fromdate:
                continue
            if todate and timestamp > todate:
                continue
            values = {
                line: _parse_number(
                    raw.get(mapping[line]) if line in mapping else None,
                    line=line,
                    required=line in {"open", "high", "low", "close"},
                )
                for line in STANDARD_LINES[1:]
            }
            opening = cast(float, values["open"])
            high = cast(float, values["high"])
            low = cast(float, values["low"])
            close = cast(float, values["close"])
            if high < max(opening, close, low):
                raise ContractError("high is below another OHLC value")
            if low > min(opening, close, high):
                raise ContractError("low is above another OHLC value")
            custom = {
                line: _parse_number(raw.get(mapping[line]), line=line, required=False)
                for line in feed_spec["custom_lines"]
            }
            normalized_rows.append(
                {
                    "datetime": timestamp,
                    **values,
                    **custom,
                }
            )
        except ContractError as error:
            if "drop_null_rows" in feed_spec["transforms"] and str(error).startswith(
                "missing numeric value"
            ):
                warnings.append(
                    {
                        "code": "DATA_NULL_ROW_DROPPED",
                        "row": row_number,
                        "message": str(error),
                    }
                )
                continue
            errors.append(
                {
                    "code": "DATA_ROW_INVALID",
                    "row": row_number,
                    "message": str(error),
                }
            )
            if len(errors) >= 50:
                break
    if not normalized_rows:
        errors.append({"code": "DATA_EMPTY_AFTER_FILTER", "message": "no valid rows remain"})
    if "deduplicate_exact" in feed_spec["transforms"]:
        unique_rows: list[dict[str, Any]] = []
        seen_rows: dict[datetime, dict[str, Any]] = {}
        for row in normalized_rows:
            previous = seen_rows.get(row["datetime"])
            if previous is None:
                seen_rows[row["datetime"]] = row
                unique_rows.append(row)
            elif previous == row:
                warnings.append(
                    {
                        "code": "DATA_EXACT_DUPLICATE_DROPPED",
                        "message": "an exact duplicate timestamp row was removed",
                    }
                )
            else:
                unique_rows.append(row)
        normalized_rows = unique_rows
    timestamps = [row["datetime"] for row in normalized_rows]
    if timestamps != sorted(timestamps):
        if "sort_datetime" in feed_spec["transforms"]:
            normalized_rows.sort(key=lambda row: row["datetime"])
            warnings.append(
                {"code": "DATA_SORTED", "message": "rows were sorted by deterministic transform"}
            )
        else:
            errors.append({"code": "DATA_NOT_SORTED", "message": "timestamps are not increasing"})
    duplicate_counts = Counter(timestamps)
    duplicates = [timestamp for timestamp, count in duplicate_counts.items() if count > 1]
    if duplicates:
        errors.append(
            {
                "code": "DATA_DUPLICATE_DATETIME",
                "message": f"{len(duplicates)} duplicate timestamp values",
            }
        )
    intervals = [
        int((right - left).total_seconds())
        for left, right in zip(timestamps, timestamps[1:])
        if right > left
    ]
    modal_interval = Counter(intervals).most_common(1)[0][0] if intervals else None
    custom_lines = feed_spec["custom_lines"]
    output = io.StringIO(newline="")
    fieldnames = [*STANDARD_LINES, *custom_lines]
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    portable_rows: list[dict[str, str]] = []
    for row in normalized_rows:
        portable = {
            "datetime": row["datetime"].strftime("%Y-%m-%dT%H:%M:%S%z"),
            **{line: _format_number(row[line]) for line in STANDARD_LINES[1:]},
            **{line: _format_number(row[line]) for line in custom_lines},
        }
        writer.writerow(portable)
        portable_rows.append(portable)
    summary = {
        "rows": len(normalized_rows),
        "first_datetime": (
            min(timestamps).isoformat().replace("+00:00", "Z") if timestamps else None
        ),
        "last_datetime": (
            max(timestamps).isoformat().replace("+00:00", "Z") if timestamps else None
        ),
        "modal_interval_seconds": modal_interval,
        "delimiter": "\\t" if delimiter == "\t" else delimiter,
        "columns": fieldnames,
    }
    quality = {
        "errors": errors,
        "warnings": warnings,
        "sorted": timestamps == sorted(timestamps),
        "duplicate_timestamps": len(duplicates),
        "finite_ohlc": not any(item["code"] == "DATA_ROW_INVALID" for item in errors),
        "ohlc_valid": not any(item["code"] == "DATA_ROW_INVALID" for item in errors),
    }
    visible_rows = portable_rows if sample_limit is None else portable_rows[:sample_limit]
    return ParsedFeed(
        rows=visible_rows,
        canonical_bytes=output.getvalue().encode("utf-8"),
        summary=summary,
        quality=quality,
        mapping=mapping,
    )
