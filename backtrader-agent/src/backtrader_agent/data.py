"""Offline dataset inspection, canonicalization, registration, and preview."""

import csv
import io
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .canonical import atomic_write_bytes, atomic_write_json, hash_object, read_json, sha256_bytes
from .contracts import DatasetManifest
from .errors import AgentError
from .roots import RootRegistry

STANDARD_COLUMNS = ("datetime", "open", "high", "low", "close", "volume", "openinterest")
ALLOWED_FORMATS = {
    "generic_csv",
    "backtrader_csv",
    "yahoo_csv",
    "mt5_csv",
    "pandas",
    "pandas_custom_lines",
}
TIMEFRAMES = {
    "Ticks",
    "MicroSeconds",
    "Seconds",
    "Minutes",
    "Days",
    "Weeks",
    "Months",
    "Years",
}
TRANSFORM_PROFILES = {"resample", "replay"}
DEFAULT_COLUMN_NAMES = {
    "generic_csv": {
        "datetime": "datetime",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
        "openinterest": "openinterest",
    },
    "backtrader_csv": {
        "datetime": "date",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
        "openinterest": "openinterest",
    },
    "yahoo_csv": {
        "datetime": "Date",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
        "openinterest": None,
    },
    "mt5_csv": {
        "datetime": "<DATE>",
        "open": "<OPEN>",
        "high": "<HIGH>",
        "low": "<LOW>",
        "close": "<CLOSE>",
        "volume": "<TICKVOL>",
        "openinterest": None,
    },
    "pandas": {
        "datetime": "datetime",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
        "openinterest": "openinterest",
    },
    "pandas_custom_lines": {
        "datetime": "datetime",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
        "openinterest": "openinterest",
    },
}


def _number(value: Any, name: str, *, default: Optional[str] = None) -> str:
    text = "" if value is None else str(value).strip()
    if not text and default is not None:
        text = default
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise AgentError(
            "BTAG-DATA-NUMERIC", f"column '{name}' contains a non-numeric value"
        ) from exc
    if not number.is_finite():
        raise AgentError("BTAG-DATA-FINITE", f"column '{name}' contains NaN or Infinity")
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def _parse_datetime(text: str, configured_format: Optional[str]) -> datetime:
    stripped = text.strip()
    formats = [configured_format] if configured_format else []
    formats.extend(
        [
            "%Y-%m-%d",
            "%Y-%m-%d %H:%M:%S",
            "%Y.%m.%d %H:%M:%S",
            "%Y%m%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
        ]
    )
    parsed: Optional[datetime] = None
    for date_format in formats:
        if not date_format:
            continue
        try:
            parsed = datetime.strptime(stripped, date_format)
            break
        except ValueError:
            continue
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AgentError("BTAG-DATA-DATETIME", "datetime value cannot be parsed") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _source_value(
    row: Sequence[str],
    header: Sequence[str],
    mapping: Any,
    field: str,
    *,
    optional: bool = False,
) -> Optional[str]:
    if mapping is None:
        if optional:
            return None
        raise AgentError("BTAG-DATA-MAPPING", f"required mapping '{field}' is missing")
    if isinstance(mapping, int):
        index = mapping
    elif isinstance(mapping, str):
        try:
            index = list(header).index(mapping)
        except ValueError as exc:
            if optional:
                return None
            raise AgentError("BTAG-DATA-MAPPING", f"mapped column '{field}' is absent") from exc
    else:
        raise AgentError("BTAG-DATA-MAPPING", f"mapping '{field}' must be a name or index")
    if index < 0 or index >= len(row):
        if optional:
            return None
        raise AgentError("BTAG-DATA-MAPPING", f"mapped column '{field}' is out of range")
    return row[index]


class DatasetService:
    MAX_FILE_BYTES = 64 * 1024 * 1024
    MAX_ROWS = 2_000_000
    MAX_FEEDS = 16
    MAX_COLUMNS = 64

    def __init__(self, roots: RootRegistry, state_root: Path) -> None:
        self.roots = roots
        self.state_root = Path(state_root)
        self.cas_root = self.state_root / "data" / "sha256"
        self.manifest_root = self.state_root / "datasets"

    def _normalize_spec(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        if spec.get("schema_version") not in {"data-spec-v1", "dataset-manifest-v1"}:
            raise AgentError("BTAG-DATA-SPEC-VERSION", "DataSpec must use data-spec-v1")
        feeds = spec.get("feeds")
        if not isinstance(feeds, list) or not feeds or len(feeds) > self.MAX_FEEDS:
            raise AgentError("BTAG-DATA-FEEDS", "DataSpec must contain 1 to 16 feeds")
        names = set()
        normalized_feeds = []
        for feed in feeds:
            if not isinstance(feed, dict):
                raise AgentError("BTAG-DATA-FEEDS", "feed descriptor must be an object")
            if feed.get("format") not in ALLOWED_FORMATS:
                raise AgentError("BTAG-DATA-FORMAT", "data format is not allowlisted")
            name = feed.get("name")
            if not isinstance(name, str) or not name or name in names:
                raise AgentError("BTAG-DATA-FEED-NAME", "feed names must be non-empty and unique")
            names.add(name)
            if feed.get("role") not in {
                "execution",
                "signal",
                "benchmark",
                "hedge",
                "cash_proxy",
            }:
                raise AgentError("BTAG-DATA-ROLE", "feed role is not allowlisted")
            if not isinstance(feed.get("columns", {}), dict):
                raise AgentError("BTAG-DATA-COLUMNS", "column mappings must be an object")
            if len(feed.get("columns", {})) > self.MAX_COLUMNS:
                raise AgentError("BTAG-DATA-COLUMNS", "too many columns")
            source = feed.get("source")
            if not isinstance(source, dict):
                source = {
                    "root_id": feed.get("root_id"),
                    "relative_path": feed.get("relative_path"),
                    "source_type": "local_file",
                }
            if (
                set(source) != {"root_id", "relative_path", "source_type"}
                or source.get("source_type") != "local_file"
                or not isinstance(source.get("root_id"), str)
                or not isinstance(source.get("relative_path"), str)
            ):
                raise AgentError("BTAG-DATA-SOURCE", "DataSpec source is invalid")
            if feed["format"] in {"pandas", "pandas_custom_lines"}:
                suffix = Path(source["relative_path"]).suffix.lower()
                if suffix not in {".csv", ".txt", ".tsv"}:
                    raise AgentError(
                        "BTAG-DATA-PANDAS-MATERIALIZED",
                        "Pandas adapters require materialized tabular text; pickle is forbidden",
                    )
            timeframe = str(feed.get("timeframe", "Days"))
            compression = int(feed.get("compression", 1))
            if timeframe not in TIMEFRAMES or compression < 1:
                raise AgentError(
                    "BTAG-DATA-TIMEFRAME",
                    "feed timeframe and compression must use the typed P0 allowlist",
                )
            normalized_feeds.append(
                {
                    "name": name,
                    "role": feed["role"],
                    "symbol": str(feed.get("symbol", name)),
                    "source": source,
                    "format": feed["format"],
                    "columns": dict(feed.get("columns", {})),
                    "timeframe": timeframe,
                    "compression": compression,
                    "timezone": str(feed.get("timezone", "UTC")),
                    "lines": sorted(
                        {
                            *STANDARD_COLUMNS[1:],
                            *(
                                name
                                for name in feed.get("columns", {})
                                if name not in STANDARD_COLUMNS
                            ),
                        }
                    ),
                    "extensions": {
                        "adapter_options": {
                            key: feed[key]
                            for key in (
                                "datetime_format",
                                "delimiter",
                                "headers",
                                "encoding",
                                "duplicate_policy",
                                "bar_semantics",
                            )
                            if key in feed
                        }
                    },
                }
            )
        alignment = spec.get("alignment", {"mode": "intersection", "minimum_overlap": 1})
        if (
            not isinstance(alignment, dict)
            or set(alignment) != {"mode", "minimum_overlap"}
            or alignment.get("mode") not in {"intersection", "left", "explicit_asof"}
            or not isinstance(alignment.get("minimum_overlap"), (int, float))
            or isinstance(alignment.get("minimum_overlap"), bool)
            or not 0 <= alignment["minimum_overlap"] <= 1
        ):
            raise AgentError("BTAG-DATA-ALIGNMENT", "alignment mode is unsupported")
        master_feed = spec.get(
            "master_feed",
            next(
                (feed["name"] for feed in normalized_feeds if feed["role"] == "execution"),
                normalized_feeds[0]["name"],
            ),
        )
        if master_feed not in names:
            raise AgentError("BTAG-DATA-MASTER", "master_feed must name a declared feed")
        transforms = spec.get("transforms", [])
        if not isinstance(transforms, list):
            raise AgentError("BTAG-DATA-TRANSFORM", "transform descriptors are invalid")
        normalized_transforms = []
        transformed_feeds = set()
        for item in transforms:
            if (
                not isinstance(item, dict)
                or set(item) != {"profile_id", "parameters"}
                or item.get("profile_id") not in TRANSFORM_PROFILES
                or not isinstance(item.get("parameters"), dict)
                or set(item["parameters"]) != {"feed", "timeframe", "compression"}
            ):
                raise AgentError("BTAG-DATA-TRANSFORM", "transform descriptor is not typed")
            parameters = item["parameters"]
            feed_name = parameters.get("feed")
            target_timeframe = parameters.get("timeframe")
            compression = parameters.get("compression")
            if (
                feed_name not in names
                or feed_name in transformed_feeds
                or target_timeframe not in TIMEFRAMES
                or not isinstance(compression, int)
                or isinstance(compression, bool)
                or compression < 1
            ):
                raise AgentError("BTAG-DATA-TRANSFORM", "transform parameters are invalid")
            transformed_feeds.add(feed_name)
            normalized_transforms.append(
                {
                    "profile_id": item["profile_id"],
                    "parameters": {
                        "feed": feed_name,
                        "timeframe": target_timeframe,
                        "compression": compression,
                    },
                }
            )
        core = {
            "schema_version": "data-spec-v1",
            "feeds": normalized_feeds,
            "master_feed": master_feed,
            "alignment": alignment,
            "transforms": normalized_transforms,
            "extensions": {"backtrader_agent": {"name": str(spec.get("name", "dataset"))}},
        }
        computed_hash = hash_object(core)
        supplied_hash = spec.get("spec_hash")
        if supplied_hash is not None and supplied_hash != computed_hash:
            raise AgentError("BTAG-DATA-SPEC-HASH", "DataSpec spec_hash is invalid")
        return {**core, "spec_hash": computed_hash}

    def _read_source(self, path: Path) -> Tuple[bytes, os.stat_result]:
        before = path.stat()
        if before.st_size > self.MAX_FILE_BYTES:
            raise AgentError("BTAG-DATA-SIZE", "dataset file exceeds the P0 size limit")
        data = path.read_bytes()
        after = path.stat()
        if (
            before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or len(data) != after.st_size
        ):
            raise AgentError("BTAG-DATA-TOCTOU", "dataset changed while it was being read")
        return data, after

    def _canonicalize_feed(self, feed: Dict[str, Any]) -> Dict[str, Any]:
        source = feed["source"]
        source_path = self.roots.resolve(
            source["root_id"], source["relative_path"], require_file=True
        )
        raw_bytes, stat_result = self._read_source(source_path)
        try:
            options = feed.get("extensions", {}).get("adapter_options", {})
            text = raw_bytes.decode(options.get("encoding", "utf-8-sig"))
        except (LookupError, UnicodeDecodeError) as exc:
            raise AgentError(
                "BTAG-DATA-ENCODING", "dataset must use an allowlisted text encoding"
            ) from exc
        delimiter = options.get("delimiter")
        if delimiter is None:
            delimiter = "\t" if feed.get("format") == "mt5_csv" else ","
        if delimiter not in {",", "\t", ";", "|"}:
            raise AgentError("BTAG-DATA-DELIMITER", "delimiter is not allowlisted")
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        if not rows:
            raise AgentError("BTAG-DATA-EMPTY", "dataset contains no rows")
        has_header = bool(options.get("headers", True))
        header = rows[0] if has_header else [str(index) for index in range(len(rows[0]))]
        body = rows[1:] if has_header else rows
        if len(body) > self.MAX_ROWS:
            raise AgentError("BTAG-DATA-ROWS", "dataset exceeds the P0 row limit")
        mappings = dict(DEFAULT_COLUMN_NAMES[feed["format"]])
        mappings.update(feed.get("columns", {}))
        custom_names = sorted(name for name in mappings if name not in STANDARD_COLUMNS)
        output_header = list(STANDARD_COLUMNS) + custom_names
        canonical_rows: List[List[str]] = []
        previous: Optional[datetime] = None
        duplicate_count = 0
        null_counts = dict.fromkeys(output_header, 0)
        for row_index, row in enumerate(body, start=2 if has_header else 1):
            if not row or all(not value.strip() for value in row):
                continue
            raw_date = _source_value(row, header, mappings.get("datetime"), "datetime")
            assert raw_date is not None
            current = _parse_datetime(raw_date, options.get("datetime_format"))
            if previous is not None:
                if current < previous:
                    raise AgentError(
                        "BTAG-DATA-ORDER",
                        "timestamps must be monotonic",
                        details={"row": row_index},
                    )
                if current == previous:
                    duplicate_count += 1
            previous = current
            normalized: Dict[str, str] = {"datetime": _canonical_datetime(current)}
            for name in ("open", "high", "low", "close"):
                normalized[name] = _number(
                    _source_value(row, header, mappings.get(name), name), name
                )
            normalized["volume"] = _number(
                _source_value(row, header, mappings.get("volume"), "volume", optional=True),
                "volume",
                default="0",
            )
            normalized["openinterest"] = _number(
                _source_value(
                    row,
                    header,
                    mappings.get("openinterest"),
                    "openinterest",
                    optional=True,
                ),
                "openinterest",
                default="0",
            )
            high = Decimal(normalized["high"])
            low = Decimal(normalized["low"])
            open_value = Decimal(normalized["open"])
            close = Decimal(normalized["close"])
            if high < max(open_value, low, close) or low > min(open_value, high, close):
                raise AgentError(
                    "BTAG-DATA-OHLC",
                    "OHLC relationship is invalid",
                    details={"row": row_index},
                )
            for name in custom_names:
                raw = _source_value(row, header, mappings[name], name, optional=True)
                normalized[name] = "" if raw is None else raw.strip()
                if not normalized[name]:
                    null_counts[name] += 1
            canonical_rows.append([normalized[name] for name in output_header])
        if not canonical_rows:
            raise AgentError("BTAG-DATA-EMPTY", "dataset contains no data rows")
        duplicate_policy = options.get("duplicate_policy", "reject")
        if duplicate_count and duplicate_policy == "reject":
            raise AgentError("BTAG-DATA-DUPLICATE", "duplicate timestamps are not permitted")
        if duplicate_policy not in {"reject", "allow"}:
            raise AgentError("BTAG-DATA-DUPLICATE-POLICY", "duplicate policy is unsupported")

        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(output_header)
        writer.writerows(canonical_rows)
        canonical_bytes = output.getvalue().encode("utf-8")
        first_row = dict(zip(output_header, canonical_rows[0]))
        last_row = dict(zip(output_header, canonical_rows[-1]))
        return {
            "name": feed["name"],
            "symbol": feed["symbol"],
            "role": feed["role"],
            "format": feed["format"],
            "source": {
                "root_id": source["root_id"],
                "relative_path": source["relative_path"],
                "source_type": source["source_type"],
                "bytes": stat_result.st_size,
                "sha256": sha256_bytes(raw_bytes),
            },
            "columns": {name: mappings[name] for name in sorted(mappings)},
            "canonical_columns": output_header,
            "datetime_format": "%Y-%m-%dT%H:%M:%SZ",
            "timeframe": feed.get("timeframe", "Days"),
            "compression": int(feed.get("compression", 1)),
            "timezone": feed.get("timezone", "UTC"),
            "session": feed.get("session"),
            "bar_semantics": options.get("bar_semantics", "close"),
            "row_count": len(canonical_rows),
            "first_datetime": first_row["datetime"],
            "last_datetime": last_row["datetime"],
            "duplicate_count": duplicate_count,
            "null_counts": null_counts,
            "normalized_sha256": sha256_bytes(canonical_bytes),
            "_canonical_bytes": canonical_bytes,
        }

    def inspect(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        normalized_spec = self._normalize_spec(spec)
        feeds = [self._canonicalize_feed(feed) for feed in normalized_spec["feeds"]]
        public_feeds = []
        for feed in feeds:
            clean = {key: value for key, value in feed.items() if not key.startswith("_")}
            public_feeds.append(clean)
        semantic = {
            "schema_version": "dataset-manifest-v1",
            "feeds": public_feeds,
            "master_feed": normalized_spec["master_feed"],
            "alignment": normalized_spec["alignment"],
            "transforms": normalized_spec["transforms"],
        }
        semantic_hash = hash_object(semantic)
        return {
            **semantic,
            "dataset_id": f"ds_{semantic_hash}",
            "spec_hash": normalized_spec["spec_hash"],
            "semantic_hash": semantic_hash,
            "status": "valid",
            "diagnostics": [],
            "provenance": {
                "dataset_name": normalized_spec["extensions"]["backtrader_agent"]["name"],
                "sources": [
                    {
                        "root_id": feed["source"]["root_id"],
                        "relative_path": feed["source"]["relative_path"],
                        "sha256": feed["source"]["sha256"],
                    }
                    for feed in public_feeds
                ],
            },
            "extensions": {
                "backtrader_agent": {
                    "policy_version": "dataset-policy-v1",
                    "canonical_format": "utf-8-csv-v1",
                    "data_spec": normalized_spec,
                }
            },
            "_canonical_feeds": feeds,
        }

    def register(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        inspected = self.inspect(spec)
        canonical_feeds = inspected.pop("_canonical_feeds")
        for feed, canonical in zip(inspected["feeds"], canonical_feeds):
            digest = feed["normalized_sha256"]
            relative = Path("data") / "sha256" / digest[:2] / f"{digest}.csv"
            destination = self.state_root / relative
            content = canonical["_canonical_bytes"]
            if destination.exists():
                if sha256_bytes(destination.read_bytes()) != digest:
                    raise AgentError("BTAG-CAS-COLLISION", "CAS object does not match its digest")
            else:
                atomic_write_bytes(destination, content, create_only=True)
                try:
                    destination.chmod(0o444)
                except OSError:
                    pass
            feed.setdefault("extensions", {})["backtrader_agent"] = {
                "cas_relative_path": relative.as_posix()
            }
        manifest_payload = {
            key: value for key, value in inspected.items() if not key.startswith("_")
        }
        manifest_payload["manifest_hash"] = hash_object(
            {key: value for key, value in manifest_payload.items() if key != "manifest_hash"}
        )
        DatasetManifest.from_dict(manifest_payload)
        manifest_path = self.manifest_root / f"{manifest_payload['dataset_id']}.json"
        if manifest_path.exists():
            existing = read_json(manifest_path)
            if existing != manifest_payload:
                raise AgentError("BTAG-DATASET-CONFLICT", "dataset ID has conflicting content")
        else:
            atomic_write_json(manifest_path, manifest_payload, create_only=True)
        return manifest_payload

    def load(self, dataset_id: str) -> Dict[str, Any]:
        if (
            not dataset_id.startswith("ds_")
            or len(dataset_id) != 67
            or any(character not in "0123456789abcdef" for character in dataset_id[3:])
        ):
            raise AgentError("BTAG-DATASET-ID", "dataset ID is malformed")
        path = self.manifest_root / f"{dataset_id}.json"
        if not path.exists():
            raise AgentError("BTAG-DATASET-UNKNOWN", "dataset is not registered")
        manifest = read_json(path)
        expected = manifest.get("manifest_hash")
        actual = hash_object(
            {key: value for key, value in manifest.items() if key != "manifest_hash"}
        )
        if expected != actual:
            raise AgentError("BTAG-DATASET-HASH", "dataset manifest hash is invalid")
        return manifest

    def preview(self, dataset_id: str, *, rows: int = 5) -> Dict[str, Any]:
        if rows < 1 or rows > 50:
            raise AgentError("BTAG-DATA-PREVIEW", "preview rows must be between 1 and 50")
        manifest = self.load(dataset_id)
        previews = []
        for feed in manifest["feeds"]:
            cas_relative = feed["extensions"]["backtrader_agent"]["cas_relative_path"]
            cas_path = self.state_root / cas_relative
            content = cas_path.read_bytes()
            if sha256_bytes(content) != feed["normalized_sha256"]:
                raise AgentError("BTAG-CAS-HASH", "registered CAS object has changed")
            records = list(csv.DictReader(io.StringIO(content.decode("utf-8"))))
            previews.append(
                {
                    "name": feed["name"],
                    "role": feed["role"],
                    "row_count": len(records),
                    "head": records[:rows],
                    "tail": records[-rows:],
                }
            )
        return {
            "dataset_id": dataset_id,
            "manifest_hash": manifest["manifest_hash"],
            "feeds": previews,
        }
