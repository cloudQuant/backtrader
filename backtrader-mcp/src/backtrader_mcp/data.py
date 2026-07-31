"""Immutable canonical CSV registry and product-owned derivations."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .errors import InvalidRequest, NotFound
from .security import confined_path
from .settings import Settings
from .state import StateStore
from .util import atomic_write, file_hash, sha256_bytes, sha256_json, utc_now

BASE_COLUMNS = ("datetime", "open", "high", "low", "close", "volume", "openinterest")
REQUIRED_COLUMNS = ("datetime", "open", "high", "low", "close")
INPUT_FORMAT_ADAPTERS = {
    "generic_csv": "backtrader.feeds.GenericCSVData",
    "backtrader_csv": "backtrader.feeds.BacktraderCSVData",
    "yahoo_csv": "backtrader.feeds.YahooFinanceCSVData",
    "mt5_csv": "backtrader.feeds.MT4CSVData",
    "pandas": "backtrader.feeds.PandasData",
    "pandas_custom_lines": "backtrader.feeds.PandasData(custom-lines)",
    "canonical_csv_v1": "backtrader.feeds.GenericCSVData",
}
TIMEFRAMES = {
    "ticks",
    "microseconds",
    "seconds",
    "minutes",
    "days",
    "weeks",
    "months",
    "years",
}


def _number(value: str, name: str) -> str:
    try:
        number = Decimal(value.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise InvalidRequest(f"invalid numeric value in {name}: {value!r}") from exc
    if not number.is_finite():
        raise InvalidRequest(f"non-finite numeric value in {name}")
    return format(number.normalize(), "f")


def _datetime(value: str) -> str:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        for pattern in (
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y-%m-%d %H:%M:%S",
            "%Y.%m.%d %H:%M",
            "%Y.%m.%d %H:%M:%S",
        ):
            try:
                parsed = datetime.strptime(raw, pattern)
                break
            except ValueError:
                continue
        else:
            raise InvalidRequest(f"invalid datetime value: {value!r}")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.isoformat(timespec="seconds")


def _encode_rows(fieldnames: list[str], rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


class DatasetService:
    def __init__(self, settings: Settings, state: StateStore):
        self.settings = settings
        self.state = state

    def _source(self, root_id: str, relative_path: str) -> Path:
        root = self.settings.source_roots.get(root_id)
        if root is None:
            raise NotFound(f"source root not registered: {root_id}")
        path = confined_path(root, relative_path, must_exist=True)
        if not path.is_file():
            raise InvalidRequest("dataset source must be a regular file")
        size = path.stat().st_size
        if size > self.settings.max_dataset_bytes:
            raise InvalidRequest(f"dataset exceeds {self.settings.max_dataset_bytes} bytes")
        return path

    def inspect_dataset(self, root_id: str, relative_path: str) -> dict[str, Any]:
        path = self._source(root_id, relative_path)
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            sample = stream.read(64 * 1024)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            reader = csv.reader(io.StringIO(sample), dialect)
            header = next(reader)
            sample_rows = [row for _, row in zip(range(5), reader)]
        except (csv.Error, StopIteration) as exc:
            raise InvalidRequest("source is not a readable delimited table") from exc
        return {
            "root_id": root_id,
            "relative_path": relative_path,
            "byte_size": path.stat().st_size,
            "source_sha256": file_hash(path),
            "delimiter": dialect.delimiter,
            "columns": header,
            "sample_rows": sample_rows,
        }

    def register_dataset(
        self,
        root_id: str,
        relative_path: str,
        column_map: dict[str, str],
        *,
        feed_descriptor: dict[str, Any] | None = None,
        declared_transforms: list[dict[str, Any]] | None = None,
        extra_columns: tuple[str, ...] = (),
        adapter_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        allowed_columns = {*BASE_COLUMNS, *extra_columns}
        if any(name not in allowed_columns for name in column_map):
            raise InvalidRequest("column map contains an unsupported canonical column")
        missing = [name for name in REQUIRED_COLUMNS if name not in column_map]
        if missing:
            raise InvalidRequest(f"column map is missing required columns: {', '.join(missing)}")
        path = self._source(root_id, relative_path)
        before = file_hash(path)
        raw = path.read_bytes()
        after = file_hash(path)
        if before != after or sha256_bytes(raw) != before:
            raise InvalidRequest("source changed while it was being registered")
        text = raw.decode("utf-8-sig")
        try:
            dialect = csv.Sniffer().sniff(text[: 64 * 1024], delimiters=",;\t|")
            reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        except csv.Error as exc:
            raise InvalidRequest("source CSV could not be parsed") from exc
        if reader.fieldnames is None:
            raise InvalidRequest("source CSV has no header")
        unknown = [source for source in column_map.values() if source not in reader.fieldnames]
        if unknown:
            raise InvalidRequest(f"mapped source columns do not exist: {', '.join(unknown)}")
        rows: list[dict[str, str]] = []
        previous_datetime: str | None = None
        options = adapter_options or {}
        time_column = options.get("time_column")
        for index, source_row in enumerate(reader, start=2):
            row: dict[str, str] = {}
            try:
                datetime_value = source_row[column_map["datetime"]]
                if time_column is not None:
                    datetime_value = f"{datetime_value} {source_row[time_column]}"
                row["datetime"] = _datetime(datetime_value)
                for column in BASE_COLUMNS[1:]:
                    if column in column_map:
                        row[column] = _number(source_row[column_map[column]], column)
                    elif column == "volume":
                        row[column] = "0"
                    elif column == "openinterest":
                        row[column] = "0"
                for column in extra_columns:
                    row[column] = _number(source_row[column_map[column]], column)
            except (KeyError, TypeError) as exc:
                raise InvalidRequest(f"row {index} is malformed") from exc
            if previous_datetime is not None and row["datetime"] <= previous_datetime:
                raise InvalidRequest("datetime values must be unique and strictly increasing")
            previous_datetime = row["datetime"]
            rows.append(row)
        if not rows:
            raise InvalidRequest("dataset contains no data rows")
        canonical_columns = [*BASE_COLUMNS, *extra_columns]
        canonical = _encode_rows(canonical_columns, rows)
        return self._store(
            canonical,
            canonical_columns,
            len(rows),
            {
                "type": "registered_csv",
                "root_id": root_id,
                "relative_path": relative_path,
                "source_sha256": before,
                "column_map": column_map,
            },
            feed_descriptor=feed_descriptor,
            declared_transforms=declared_transforms,
        )

    @staticmethod
    def _bar_operation(feed: dict[str, Any]) -> dict[str, Any]:
        extensions = feed.get("extensions", {})
        if not isinstance(extensions, dict) or set(extensions) - {
            "adapter_options",
            "bar_operation",
        }:
            raise InvalidRequest("DataSpec feed extensions are invalid")
        operation = extensions.get("bar_operation", {"mode": "direct"})
        if not isinstance(operation, dict) or operation.get("mode") not in {
            "direct",
            "resample",
            "replay",
        }:
            raise InvalidRequest("DataSpec feed bar_operation is invalid")
        if operation["mode"] == "direct":
            if set(operation) != {"mode"}:
                raise InvalidRequest("direct bar_operation accepts only mode")
        elif (
            set(operation) != {"mode", "timeframe", "compression"}
            or operation["timeframe"] not in TIMEFRAMES
            or not isinstance(operation["compression"], int)
            or isinstance(operation["compression"], bool)
            or operation["compression"] < 1
        ):
            raise InvalidRequest(
                "resample/replay bar_operation requires typed timeframe and compression"
            )
        return operation

    @staticmethod
    def _adapter_options(feed: dict[str, Any]) -> dict[str, Any]:
        extensions = feed.get("extensions", {})
        options = extensions.get("adapter_options", {})
        if not isinstance(options, dict):
            raise InvalidRequest("DataSpec adapter_options must be an object")
        if feed["format"] in {"backtrader_csv", "mt5_csv"}:
            if set(options) - {"time_column"} or (
                "time_column" in options
                and (not isinstance(options["time_column"], str) or not options["time_column"])
            ):
                raise InvalidRequest(
                    "Backtrader/MT5 adapter_options supports only a time_column name"
                )
        elif options:
            raise InvalidRequest("adapter_options are not supported for this feed format")
        return options

    def register_local_dataset(self, data_spec: dict[str, Any]) -> dict[str, Any]:
        """Register a complete typed DataSpec without exposing executable local paths."""

        if not isinstance(data_spec, dict) or data_spec.get("schema_version") != "data-spec-v1":
            raise InvalidRequest("DataSpec must use schema_version data-spec-v1")
        expected_hash = data_spec.get("spec_hash")
        hash_payload = {key: value for key, value in data_spec.items() if key != "spec_hash"}
        if not isinstance(expected_hash, str) or expected_hash != sha256_json(hash_payload):
            raise InvalidRequest("DataSpec spec_hash does not match its canonical content")
        allowed = {
            "schema_version",
            "spec_hash",
            "feeds",
            "master_feed",
            "alignment",
            "transforms",
            "extensions",
        }
        if set(data_spec) - allowed:
            raise InvalidRequest("DataSpec contains unsupported fields")
        feeds = data_spec.get("feeds")
        if not isinstance(feeds, list) or not 1 <= len(feeds) <= 32:
            raise InvalidRequest("DataSpec feeds must contain 1-32 typed feed descriptors")
        names = [feed.get("name") for feed in feeds if isinstance(feed, dict)]
        if len(names) != len(feeds) or any(
            not isinstance(name, str) or not name.isidentifier() for name in names
        ):
            raise InvalidRequest("DataSpec feed names must be Python identifiers")
        if len(set(names)) != len(names):
            raise InvalidRequest("DataSpec feed names must be unique")
        master_feed = data_spec.get("master_feed")
        if master_feed not in names:
            raise InvalidRequest("DataSpec master_feed must name a declared feed")
        alignment = data_spec.get("alignment")
        if (
            not isinstance(alignment, dict)
            or set(alignment) != {"mode", "minimum_overlap"}
            or alignment["mode"] not in {"intersection", "left", "explicit_asof"}
            or not isinstance(alignment["minimum_overlap"], (int, float))
            or isinstance(alignment["minimum_overlap"], bool)
            or not 0 <= alignment["minimum_overlap"] <= 1
        ):
            raise InvalidRequest("DataSpec alignment is invalid")
        transforms = data_spec.get("transforms")
        if not isinstance(transforms, list):
            raise InvalidRequest("DataSpec transforms must be an array")
        for transform in transforms:
            if (
                not isinstance(transform, dict)
                or set(transform) != {"profile_id", "parameters"}
                or not isinstance(transform["profile_id"], str)
                or not transform["profile_id"]
                or not isinstance(transform["parameters"], dict)
            ):
                raise InvalidRequest("DataSpec transform descriptor is invalid")

        child_manifests: list[dict[str, Any]] = []
        for index, feed in enumerate(feeds):
            required = {
                "name",
                "role",
                "symbol",
                "source",
                "format",
                "timeframe",
                "timezone",
                "columns",
            }
            if not required <= set(feed):
                raise InvalidRequest("DataSpec feed descriptor is missing required fields")
            if set(feed) - {
                *required,
                "compression",
                "extensions",
                "lines",
                "tradable",
            }:
                raise InvalidRequest("DataSpec feed descriptor contains unsupported fields")
            if feed["role"] not in {
                "execution",
                "signal",
                "benchmark",
                "hedge",
                "cash_proxy",
            }:
                raise InvalidRequest("DataSpec feed role is invalid")
            source = feed["source"]
            source_type = (
                "materialized_dataframe"
                if feed["format"] in {"pandas", "pandas_custom_lines"}
                else "local_file"
            )
            if (
                not isinstance(source, dict)
                or source.get("source_type") != source_type
                or set(source) != {"root_id", "relative_path", "source_type"}
            ):
                raise InvalidRequest("local DataSpec feed source is invalid")
            if feed["format"] not in INPUT_FORMAT_ADAPTERS:
                raise InvalidRequest("DataSpec feed format is not supported")
            if source_type == "materialized_dataframe" and not source[
                "relative_path"
            ].lower().endswith(".csv"):
                raise InvalidRequest("Pandas feeds must be materialized from a local CSV")
            timeframe = feed["timeframe"]
            compression = feed.get("compression", 1)
            if (
                timeframe not in TIMEFRAMES
                or not isinstance(compression, int)
                or isinstance(compression, bool)
                or compression < 1
            ):
                raise InvalidRequest("DataSpec feed timeframe/compression is invalid")
            if feed["format"] == "yahoo_csv" and timeframe not in {
                "days",
                "weeks",
                "months",
                "years",
            }:
                raise InvalidRequest("Yahoo CSV feeds support daily-or-coarser bars")
            if not isinstance(feed["symbol"], str) or not feed["symbol"]:
                raise InvalidRequest("DataSpec feed symbol is invalid")
            if not isinstance(feed["timezone"], str) or not feed["timezone"]:
                raise InvalidRequest("DataSpec feed timezone is invalid")
            columns = feed["columns"]
            if not isinstance(columns, dict) or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in columns.items()
            ):
                raise InvalidRequest("DataSpec feed columns must map canonical to source names")
            lines = feed.get("lines", list(BASE_COLUMNS))
            if (
                not isinstance(lines, list)
                or any(
                    not isinstance(line, str) or not line.isidentifier() or line.startswith("_")
                    for line in lines
                )
                or len(set(lines)) != len(lines)
            ):
                raise InvalidRequest("DataSpec feed lines are invalid")
            custom_lines = tuple(
                line for line in lines if line not in BASE_COLUMNS and line != "datetime"
            )
            if any(line not in columns for line in custom_lines):
                raise InvalidRequest("every custom line must have a source column mapping")
            if feed["format"] == "pandas_custom_lines" and not custom_lines:
                raise InvalidRequest("pandas_custom_lines requires at least one custom line")
            if feed["format"] != "pandas_custom_lines" and custom_lines:
                raise InvalidRequest("custom lines require the pandas_custom_lines format")
            operation = self._bar_operation(feed)
            adapter_options = self._adapter_options(feed)
            descriptor = {
                "name": feed["name"],
                "role": feed["role"],
                "symbol": feed["symbol"],
                "timeframe": timeframe,
                "timezone": feed["timezone"],
                "compression": compression,
                "input_format": feed["format"],
                "adapter": INPUT_FORMAT_ADAPTERS[feed["format"]],
                "lines": [*BASE_COLUMNS, *custom_lines],
                "custom_lines": list(custom_lines),
                "bar_operation": operation,
                "source_type": source_type,
            }
            child_manifests.append(
                self.register_dataset(
                    source["root_id"],
                    source["relative_path"],
                    columns,
                    feed_descriptor=descriptor,
                    declared_transforms=transforms
                    or [
                        {
                            "profile_id": "canonicalize_csv_v1",
                            "parameters": {"feed_index": index},
                        }
                    ],
                    extra_columns=custom_lines,
                    adapter_options=adapter_options,
                )
            )

        feed_objects = {
            feed["name"]: child["extensions"]["feed_objects"][feed["name"]]
            for feed, child in zip(feeds, child_manifests)
        }
        timestamp_sets: dict[str, set[str]] = {}
        for name, item in feed_objects.items():
            path = confined_path(
                self.settings.state_root, item["cas_relative_path"], must_exist=True
            )
            with path.open("r", encoding="utf-8", newline="") as stream:
                timestamp_sets[name] = {row["datetime"] for row in csv.DictReader(stream)}
        master_timestamps = timestamp_sets[master_feed]
        common = set.intersection(*timestamp_sets.values())
        overlap = len(common) / len(master_timestamps) if master_timestamps else 0.0
        if overlap < float(alignment["minimum_overlap"]):
            raise InvalidRequest("DataSpec feeds do not satisfy minimum_overlap")

        semantic_hash = sha256_json(
            {
                "spec_hash": expected_hash,
                "feed_objects": {
                    name: item["sha256"] for name, item in sorted(feed_objects.items())
                },
            }
        )
        dataset_id = f"ds_{semantic_hash}"
        registered_feeds = [child["feeds"][0] for child in child_manifests]
        master_object = feed_objects[master_feed]
        manifest = {
            "schema_version": "dataset-manifest-v1",
            "dataset_id": dataset_id,
            "spec_hash": expected_hash,
            "semantic_hash": semantic_hash,
            "feeds": registered_feeds,
            "master_feed": master_feed,
            "alignment": alignment,
            "status": "valid",
            "diagnostics": [],
            "transforms": transforms,
            "provenance": {
                "type": "typed-local-data-spec-v1",
                "source_dataset_ids": [child["dataset_id"] for child in child_manifests],
                "observed_overlap": overlap,
            },
            "extensions": {
                "data_spec": data_spec,
                "feed_objects": feed_objects,
                "content_sha256": master_object["sha256"],
                "cas_relative_path": master_object["cas_relative_path"],
                "columns": list(BASE_COLUMNS),
                "row_count": len(master_timestamps),
                "byte_size": sum(
                    (self.settings.state_root / item["cas_relative_path"]).stat().st_size
                    for item in feed_objects.values()
                ),
                "created_at": utc_now(),
            },
        }
        manifest["manifest_hash"] = sha256_json(manifest)
        existing = self.state.maybe_get("dataset", dataset_id)
        if existing is None:
            self.state.put("dataset", dataset_id, manifest)
            self.state.audit(
                "dataset.registered_typed",
                dataset_id,
                {"semantic_hash": semantic_hash, "feed_count": len(registered_feeds)},
            )
        return existing or manifest

    def _store(
        self,
        content: bytes,
        columns: list[str],
        row_count: int,
        provenance: dict[str, Any],
        *,
        feed_descriptor: dict[str, Any] | None = None,
        declared_transforms: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        content_digest = sha256_bytes(content)
        descriptor = feed_descriptor or {}
        feed_name = descriptor.get("name", "primary")
        source_type = descriptor.get(
            "source_type",
            "local_file" if provenance.get("root_id") != "cas" else "content_addressed",
        )
        source = {
            "root_id": provenance.get("root_id", "cas"),
            "relative_path": provenance.get(
                "relative_path", provenance.get("source_dataset_id", "derived")
            ),
            "source_type": source_type,
        }
        mapping = {name: index for index, name in enumerate(columns)}
        input_format = descriptor.get("input_format", "canonical_csv_v1")
        adapter = descriptor.get("adapter", INPUT_FORMAT_ADAPTERS[input_format])
        lines = descriptor.get("lines", list(BASE_COLUMNS))
        custom_lines = descriptor.get("custom_lines", [])
        bar_operation = descriptor.get("bar_operation", {"mode": "direct"})
        feed_spec = {
            "name": feed_name,
            "role": descriptor.get("role", "execution"),
            "symbol": descriptor.get("symbol", feed_name),
            "source": source,
            "format": input_format,
            "columns": mapping,
            "timeframe": descriptor.get("timeframe", "unspecified"),
            "compression": descriptor.get("compression", 1),
            "timezone": descriptor.get("timezone", "UTC"),
            "lines": lines,
            "extensions": {
                "storage_format": "canonical_csv_v1",
                "bar_operation": bar_operation,
            },
        }
        transforms = declared_transforms or [
            {
                "profile_id": provenance.get("transform_profile_id", "canonicalize_csv_v1"),
                "parameters": provenance.get(
                    "typed_params", {"column_map": provenance.get("column_map", {})}
                ),
            }
        ]
        data_spec_core = {
            "schema_version": "data-spec-v1",
            "feeds": [feed_spec],
            "master_feed": feed_name,
            "alignment": {"mode": "intersection", "minimum_overlap": 1.0},
            "transforms": transforms,
        }
        spec_hash = sha256_json(data_spec_core)
        data_spec = {**data_spec_core, "spec_hash": spec_hash}
        semantic_hash = sha256_json(
            {
                "content_sha256": content_digest,
                "spec_hash": spec_hash,
                "columns": columns,
                "transforms": transforms,
            }
        )
        dataset_id = f"ds_{semantic_hash}"
        path = (
            self.settings.state_root
            / "cas"
            / "sha256"
            / content_digest[:2]
            / f"{content_digest}.csv"
        )
        if path.exists():
            if file_hash(path) != content_digest:
                raise InvalidRequest("CAS collision or corruption detected")
        else:
            atomic_write(path, content, mode=0o600)
        manifest = {
            "schema_version": "dataset-manifest-v1",
            "dataset_id": dataset_id,
            "spec_hash": spec_hash,
            "semantic_hash": semantic_hash,
            "feeds": [
                {
                    "name": feed_name,
                    "role": feed_spec["role"],
                    "symbol": feed_spec["symbol"],
                    "timeframe": feed_spec["timeframe"],
                    "source": {
                        **source,
                        "sha256": provenance.get("source_sha256", content_digest),
                        "bytes": len(content),
                    },
                    "format": input_format,
                    "adapter": adapter,
                    "columns": mapping,
                    "lines": lines,
                    "object": {
                        "sha256": content_digest,
                        "file": f"{content_digest}.csv",
                    },
                    "summary": {"row_count": row_count},
                    "quality": {"errors": [], "warnings": []},
                }
            ],
            "master_feed": feed_name,
            "alignment": {"mode": "intersection", "minimum_overlap": 1.0},
            "status": "valid",
            "diagnostics": [],
            "transforms": transforms,
            "provenance": provenance,
            "extensions": {
                "content_sha256": content_digest,
                "format": "canonical_csv_v1",
                "columns": columns,
                "row_count": row_count,
                "byte_size": len(content),
                "cas_relative_path": str(path.relative_to(self.settings.state_root)),
                "created_at": utc_now(),
                "data_spec": data_spec,
                "feed_objects": {
                    feed_name: {
                        "sha256": content_digest,
                        "cas_relative_path": str(path.relative_to(self.settings.state_root)),
                        "input_format": input_format,
                        "adapter": adapter,
                        "source_timeframe": feed_spec["timeframe"],
                        "source_compression": feed_spec["compression"],
                        "custom_lines": custom_lines,
                        "bar_operation": bar_operation,
                    }
                },
            },
        }
        manifest["manifest_hash"] = sha256_json(manifest)
        existing = self.state.maybe_get("dataset", dataset_id)
        if existing is None:
            self.state.put("dataset", dataset_id, manifest)
            self.state.audit(
                "dataset.registered",
                dataset_id,
                {
                    "semantic_hash": semantic_hash,
                    "content_sha256": content_digest,
                },
            )
        return existing or manifest

    def _content_path(self, dataset: dict[str, Any]) -> Path:
        path = confined_path(
            self.settings.state_root,
            dataset["extensions"]["cas_relative_path"],
            must_exist=True,
        )
        if file_hash(path) != dataset["extensions"]["content_sha256"]:
            raise InvalidRequest("registered dataset content no longer matches its manifest")
        return path

    def content_paths(self, dataset: dict[str, Any]) -> dict[str, Path]:
        """Resolve and verify every product-owned CAS object in manifest feed order."""

        objects = dataset["extensions"].get("feed_objects")
        if not isinstance(objects, dict) or not objects:
            raise InvalidRequest("dataset has no feed object bindings")
        paths: dict[str, Path] = {}
        for feed in dataset["feeds"]:
            name = feed["name"]
            item = objects.get(name)
            if not isinstance(item, dict):
                raise InvalidRequest(f"dataset feed object is missing: {name}")
            path = confined_path(
                self.settings.state_root, item["cas_relative_path"], must_exist=True
            )
            if file_hash(path) != item["sha256"]:
                raise InvalidRequest(f"dataset feed object failed hash verification: {name}")
            paths[name] = path
        return paths

    def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        dataset = self.state.get("dataset", dataset_id)
        manifest_without_hash = {
            key: value for key, value in dataset.items() if key != "manifest_hash"
        }
        if sha256_json(manifest_without_hash) != dataset["manifest_hash"]:
            raise InvalidRequest("registered dataset manifest failed its hash check")
        self._content_path(dataset)
        return dataset

    def preview_dataset(self, dataset_id: str, limit: int = 20) -> dict[str, Any]:
        if not isinstance(limit, int) or limit < 1 or limit > self.settings.max_preview_rows:
            raise InvalidRequest(
                f"preview limit must be between 1 and {self.settings.max_preview_rows}"
            )
        dataset = self.get_dataset(dataset_id)
        with self._content_path(dataset).open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            rows = [row for _, row in zip(range(limit), reader)]
        return {
            "dataset": dataset,
            "rows": rows,
            "truncated": dataset["extensions"]["row_count"] > len(rows),
        }

    def derive_tabular_dataset(
        self,
        source_dataset_id: str,
        transform_profile_id: str,
        typed_params: dict[str, Any],
        expected_manifest_hash: str,
    ) -> dict[str, Any]:
        source = self.get_dataset(source_dataset_id)
        if source["manifest_hash"] != expected_manifest_hash:
            raise InvalidRequest("source dataset manifest hash is stale")
        with self._content_path(source).open("r", encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        columns = list(source["extensions"]["columns"])
        if transform_profile_id == "identity":
            if typed_params:
                raise InvalidRequest("identity transform takes no parameters")
        elif transform_profile_id == "dropna":
            selected = typed_params.get("columns")
            if (
                not isinstance(selected, list)
                or not selected
                or any(not isinstance(item, str) or item not in columns for item in selected)
                or set(typed_params) != {"columns"}
            ):
                raise InvalidRequest("dropna requires a non-empty typed columns list")
            rows = [row for row in rows if all(row.get(column, "").strip() for column in selected)]
        elif transform_profile_id in {"returns", "sma"}:
            column = typed_params.get("column", "close")
            if not isinstance(column, str) or column not in columns:
                raise InvalidRequest("transform column is invalid")
            values = [float(row[column]) for row in rows]
            if transform_profile_id == "returns":
                if set(typed_params) - {"column", "output"}:
                    raise InvalidRequest("returns has unknown parameters")
                output = typed_params.get("output", f"{column}_return")
                derived = [""] + [
                    (
                        format((values[index] / values[index - 1]) - 1.0, ".17g")
                        if values[index - 1] != 0
                        else ""
                    )
                    for index in range(1, len(values))
                ]
            else:
                if set(typed_params) - {"column", "output", "period"}:
                    raise InvalidRequest("sma has unknown parameters")
                period = typed_params.get("period")
                if not isinstance(period, int) or period < 2 or period > 10000:
                    raise InvalidRequest("sma period must be an integer between 2 and 10000")
                output = typed_params.get("output", f"{column}_sma_{period}")
                derived = []
                rolling = 0.0
                for index, value in enumerate(values):
                    rolling += value
                    if index >= period:
                        rolling -= values[index - period]
                    derived.append("" if index + 1 < period else format(rolling / period, ".17g"))
            if (
                not isinstance(output, str)
                or not output.isidentifier()
                or output in columns
                or output.startswith("_")
            ):
                raise InvalidRequest("transform output must be a new public identifier")
            columns.append(output)
            for row, value in zip(rows, derived):
                row[output] = value
        else:
            raise InvalidRequest("unknown transform profile")
        content = _encode_rows(columns, rows)
        return self._store(
            content,
            columns,
            len(rows),
            {
                "type": "derived_tabular_v1",
                "root_id": "cas",
                "relative_path": source_dataset_id,
                "source_dataset_id": source_dataset_id,
                "source_manifest_hash": expected_manifest_hash,
                "transform_profile_id": transform_profile_id,
                "typed_params": typed_params,
            },
        )

    def materialization(self, dataset_id: str) -> dict[str, Any]:
        """Return ordered trusted worker-only paths and a controlled feed mapping."""
        dataset = self.get_dataset(dataset_id)
        paths = self.content_paths(dataset)
        return {
            "dataset_id": dataset_id,
            "feeds": [
                {
                    "name": feed["name"],
                    "role": feed["role"],
                    "symbol": feed["symbol"],
                    "timeframe": feed["timeframe"],
                    "canonical_csv_path": str(paths[feed["name"]]),
                    "content_sha256": dataset["extensions"]["feed_objects"][feed["name"]]["sha256"],
                    "input_format": dataset["extensions"]["feed_objects"][feed["name"]][
                        "input_format"
                    ],
                    "adapter": dataset["extensions"]["feed_objects"][feed["name"]]["adapter"],
                    "source_compression": dataset["extensions"]["feed_objects"][feed["name"]][
                        "source_compression"
                    ],
                    "custom_lines": dataset["extensions"]["feed_objects"][feed["name"]][
                        "custom_lines"
                    ],
                    "bar_operation": dataset["extensions"]["feed_objects"][feed["name"]][
                        "bar_operation"
                    ],
                    "adapter_params": {
                        "dtformat": "%Y-%m-%dT%H:%M:%S",
                        "datetime": 0,
                        "open": 1,
                        "high": 2,
                        "low": 3,
                        "close": 4,
                        "volume": 5,
                        "openinterest": 6,
                        "headers": True,
                    },
                }
                for feed in dataset["feeds"]
            ],
        }
