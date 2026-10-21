"""Deterministic CSV/JSON persistence for :mod:`backtrader.research.dataset`."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from .errors import DatasetError, DependencyError


SCHEMA_VERSION = 1
_MISSING = ""
_TABLE_KINDS = frozenset(("bool", "datetime", "float", "int", "json", "text"))


def _pandas() -> Any:
    import sys

    if sys.version_info < (3, 11):
        raise DependencyError(
            "factor research storage requires Python 3.11 or newer",
            code="DEPENDENCY_UNAVAILABLE",
        )
    try:
        import pandas as pd
    except ImportError as exc:
        raise DependencyError(
            "factor research storage requires pandas",
            code="DEPENDENCY_UNAVAILABLE",
        ) from exc
    return pd


def _fail(message: str) -> DatasetError:
    return DatasetError(message, code="INVALID_DATASET")


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise _fail("dataset manifest contains a non-canonical JSON value") from exc


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_missing(value: Any, pd: Any) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    try:
        answer = pd.isna(value)
    except (TypeError, ValueError):
        return False
    if isinstance(answer, bool) or type(answer).__name__ == "bool_":
        return bool(answer)
    return False


def _index_parts(
    frame: Any, pd: Any
) -> Tuple[List[str], List[Tuple[str, str]], List[Tuple[Any, ...]]]:
    index = frame.index
    if isinstance(index, pd.MultiIndex):
        names = list(index.names)
        arrays = [index.get_level_values(i) for i in range(index.nlevels)]
    else:
        names = [index.name]
        arrays = [index]
    fields = []
    for position, (name, values) in enumerate(zip(names, arrays)):
        field_name = name if isinstance(name, str) and name else "__index_%d__" % position
        fields.append((field_name, _kind_for_array(values, pd)))
    if len({field for field, _ in fields}) != len(fields):
        raise _fail("dataset table has duplicate index names")
    if {field for field, _ in fields}.intersection(str(column) for column in frame.columns):
        raise _fail("dataset table index names collide with data columns")
    index_rows = []
    if isinstance(index, pd.MultiIndex):
        index_rows = [tuple(row) for row in index.tolist()]
    else:
        index_rows = [(value,) for value in index.tolist()]
    return names, fields, index_rows


def _kind_for_array(values: Any, pd: Any) -> str:
    if isinstance(values, pd.DatetimeIndex):
        if values.tz is None:
            raise _fail("dataset datetimes must be timezone-aware")
        return "datetime"
    nonmissing = [item for item in values if not _is_missing(item, pd)]
    return _kind_for_values(nonmissing, getattr(values, "dtype", None), pd)


def _kind_for_series(series: Any, pd: Any) -> str:
    return _kind_for_values(
        [item for item in series.tolist() if not _is_missing(item, pd)], series.dtype, pd
    )


def _kind_for_values(values: Sequence[Any], dtype: Any, pd: Any) -> str:
    if pd.api.types.is_bool_dtype(dtype):
        return "bool"
    if pd.api.types.is_integer_dtype(dtype):
        return "int"
    if pd.api.types.is_float_dtype(dtype):
        return "float"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        if getattr(dtype, "tz", None) is None:
            raise _fail("dataset datetimes must be timezone-aware")
        return "datetime"
    if not values:
        return "text"
    if all(isinstance(item, (bool,)) for item in values):
        return "bool"
    if all(isinstance(item, int) and not isinstance(item, bool) for item in values):
        return "int"
    if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in values):
        return "float"
    if all(isinstance(item, str) for item in values):
        return "text"
    if all(hasattr(item, "tzinfo") and item.tzinfo is not None for item in values):
        return "datetime"
    return "json"


def _json_value(value: Any, pd: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _fail("dataset JSON cells cannot contain non-finite numbers")
        return value
    if isinstance(value, (pd.Timestamp,)):
        if value.tzinfo is None:
            raise _fail("dataset JSON timestamps must be timezone-aware")
        return value.tz_convert("UTC").isoformat().replace("+00:00", "Z")
    if isinstance(value, (list, tuple)):
        return [_json_value(item, pd) for item in value]
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _fail("dataset JSON object keys must be strings")
            result[key] = _json_value(item, pd)
        return result
    item = getattr(value, "item", None)
    if callable(item):
        converted = item()
        if converted is not value:
            return _json_value(converted, pd)
    raise _fail("dataset contains an unsupported cell value")


def _encode(value: Any, kind: str, pd: Any) -> str:
    if _is_missing(value, pd):
        return _MISSING
    if kind == "text":
        text_value = str(value)
        if not text_value:
            raise _fail("non-missing dataset text values cannot be empty")
        return text_value
    if kind == "bool":
        if value not in (True, False, 0, 1):
            raise _fail("dataset bool column contains a non-boolean value")
        return "true" if bool(value) else "false"
    if kind == "int":
        if isinstance(value, bool) or int(value) != value:
            raise _fail("dataset integer column contains a non-integer value")
        return str(int(value))
    if kind == "float":
        result = float(value)
        if not math.isfinite(result):
            raise _fail("dataset float columns cannot contain infinity")
        return format(result, ".17g")
    if kind == "datetime":
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None:
            raise _fail("dataset datetimes must be timezone-aware")
        return str(stamp.tz_convert("UTC").isoformat()).replace("+00:00", "Z")
    if kind == "json":
        return json.dumps(
            _json_value(value, pd),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    raise _fail("dataset uses an unknown table type")


def _table_bytes(frame: Any) -> Tuple[bytes, Dict[str, Any]]:
    pd = _pandas()
    if not isinstance(frame, pd.DataFrame):
        raise _fail("only DataFrames can be serialized as dataset tables")
    if frame.index.has_duplicates:
        raise _fail("dataset table index contains duplicate keys")
    try:
        frame = frame.sort_index(kind="mergesort").reindex(
            columns=sorted(frame.columns, key=lambda value: str(value))
        )
    except (TypeError, ValueError) as exc:
        raise _fail("dataset table cannot be sorted into canonical order") from exc
    index_names, index_fields, index_rows = _index_parts(frame, pd)
    columns = []
    for name in frame.columns:
        if not isinstance(name, str) or not name:
            raise _fail("dataset table column names must be non-empty strings")
        columns.append((name, _kind_for_series(frame[name], pd)))
    header = [field for field, _ in index_fields] + [name for name, _ in columns]
    if len(set(header)) != len(header):
        raise _fail("dataset table contains duplicate serialized column names")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(header)
    data_rows = frame.itertuples(index=False, name=None)
    index_kinds = [kind for _, kind in index_fields]
    column_kinds = [kind for _, kind in columns]
    for index_values, row in zip(index_rows, data_rows):
        writer.writerow(
            [_encode(value, kind, pd) for value, kind in zip(index_values, index_kinds)]
            + [_encode(value, kind, pd) for value, kind in zip(row, column_kinds)]
        )
    payload = output.getvalue().encode("utf-8")
    schema = {
        "index_names": index_names,
        "index_fields": [{"name": name, "kind": kind} for name, kind in index_fields],
        "columns": [{"name": name, "kind": kind} for name, kind in columns],
    }
    return payload, schema


def _table_attrs(logical_name: str, frame: Any, pd: Any) -> Dict[str, Any]:
    if not logical_name.startswith("formula_inputs:"):
        return {}
    source_metadata = frame.attrs.get("source_metadata")
    if source_metadata is None:
        return {}
    if not isinstance(source_metadata, Mapping):
        raise _fail("formula input source_metadata must be a JSON mapping")
    return {"source_metadata": _json_value(source_metadata, pd)}


def _table_specs(dataset: Any) -> Dict[str, Tuple[str, Any]]:
    specs = {
        "grid": ("grid.csv", dataset._grid),
        "factors": ("factors.csv", dataset._raw_factors),
        "availability": ("availability.csv", dataset._availability),
        "universe": ("universe.csv", dataset._universe.to_frame("eligible")),
        "formula_universe": (
            "formula_universe.csv",
            dataset._formula_universe.to_frame("eligible"),
        ),
    }
    for key in ("open", "close"):
        if key in dataset._prices:
            specs["prices_" + key] = ("prices_%s.csv" % key, dataset._prices[key])
    if dataset._precomputed_returns is not None:
        specs["precomputed_returns"] = (
            "precomputed_returns.csv",
            dataset._precomputed_returns,
        )
    for category, named_tables in (
        ("formula_inputs", dataset._formula_inputs),
        ("classifications", dataset._classifications),
    ):
        for name in sorted(named_tables):
            key = hashlib.sha256(name.encode("utf-8")).hexdigest()
            logical = "%s:%s" % (category, name)
            specs[logical] = ("%s/%s.csv" % (category, key), named_tables[name])
    return specs


def _payloads_and_descriptors(
    dataset: Any,
) -> Tuple[Dict[str, Tuple[str, bytes]], Dict[str, Dict[str, Any]]]:
    payloads = {}
    descriptors = {}
    pd = _pandas()
    for logical_name, (relative_path, frame) in sorted(_table_specs(dataset).items()):
        payload, schema = _table_bytes(frame)
        rows = len(frame)
        descriptors[logical_name] = {
            "file": relative_path,
            "rows": rows,
            "sha256": _sha256(payload),
            "schema": schema,
            "attrs": _table_attrs(logical_name, frame, pd),
        }
        payloads[logical_name] = (relative_path, payload)
    return payloads, descriptors


def _identity_payload(dataset: Any, descriptors: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "targets": list(dataset._targets),
        "factor_names": list(dataset._factor_names),
        "groups": {key: dataset._groups[key] for key in sorted(dataset._groups)},
        "metadata": dataset._metadata,
        "tables": descriptors,
    }


def compute_dataset_id(dataset: Any) -> str:
    """Return the content-derived snapshot ID, independent of output path/time."""
    _, descriptors = _payloads_and_descriptors(dataset)
    return _sha256(_canonical_json(_identity_payload(dataset, descriptors)))


def save_dataset(dataset: Any, path: Any) -> Path:
    """Persist a complete dataset atomically, refusing to replace any path."""
    _pandas()
    target = Path(path).expanduser().absolute()
    if target.exists():
        raise _fail("refusing to overwrite an existing dataset path")
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    payloads, descriptors = _payloads_and_descriptors(dataset)
    identity = _identity_payload(dataset, descriptors)
    expected_id = _sha256(_canonical_json(identity))
    if dataset._dataset_id != expected_id:
        raise _fail("in-memory dataset content changed after snapshot construction")
    temporary = Path(tempfile.mkdtemp(prefix=".%s.tmp-" % target.name, dir=str(parent)))
    try:
        for relative, payload in payloads.values():
            destination = temporary.joinpath(*PurePosixPath(relative).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "complete": True,
            "dataset_id": expected_id,
            "targets": list(dataset._targets),
            "factor_names": list(dataset._factor_names),
            "groups": {key: dataset._groups[key] for key in sorted(dataset._groups)},
            "metadata": dataset._metadata,
            "tables": descriptors,
        }
        with (temporary / "manifest.json").open("wb") as stream:
            stream.write(_canonical_json(manifest))
            stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        # Parse the just-written directory, validate all digests and ensure a
        # complete decode has exactly the same content ID before publishing it.
        loaded = load_dataset(temporary)
        if loaded.dataset_id != expected_id:
            raise _fail("serialized dataset did not round-trip to its content identity")
        os.replace(str(temporary), str(target))
        return target
    except BaseException:
        if temporary.exists():
            shutil.rmtree(str(temporary), ignore_errors=True)
        raise


def _safe_relative_file(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise _fail("manifest table path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise _fail("manifest table path escapes the dataset directory")
    return value


def _decode(value: str, kind: str, pd: Any) -> Any:
    if value == _MISSING:
        return None
    try:
        if kind == "text":
            return value
        if kind == "bool":
            if value not in ("true", "false"):
                raise ValueError("invalid boolean")
            return value == "true"
        if kind == "int":
            return int(value)
        if kind == "float":
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("non-finite float")
            return number
        if kind == "datetime":
            stamp = pd.Timestamp(value)
            if stamp.tzinfo is None:
                raise ValueError("naive datetime")
            return stamp.tz_convert("UTC")
        if kind == "json":
            return json.loads(
                value, parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item))
            )
    except (TypeError, ValueError, OverflowError, RecursionError, json.JSONDecodeError) as exc:
        raise _fail("dataset CSV cell does not match its declared type") from exc
    raise _fail("dataset table uses an unknown type")


def _read_table(root: Path, logical_name: str, descriptor: Mapping[str, Any]) -> Any:
    pd = _pandas()
    if not isinstance(descriptor, Mapping) or set(descriptor) != {
        "file",
        "rows",
        "sha256",
        "schema",
        "attrs",
    }:
        raise _fail("manifest table descriptor has an invalid schema")
    attrs = descriptor["attrs"]
    if not isinstance(attrs, dict):
        raise _fail("manifest table attrs are invalid")
    if logical_name.startswith("formula_inputs:"):
        if set(attrs) - {"source_metadata"}:
            raise _fail("manifest formula input attrs are invalid")
        if "source_metadata" in attrs:
            source_metadata = attrs["source_metadata"]
            if (
                not isinstance(source_metadata, dict)
                or not source_metadata
                or any(
                    not isinstance(key, str)
                    or not key
                    or not (
                        value is None
                        or isinstance(value, (str, bool, int))
                        or (isinstance(value, float) and math.isfinite(value))
                    )
                    for key, value in source_metadata.items()
                )
            ):
                raise _fail("manifest formula input source_metadata is invalid")
    elif attrs:
        raise _fail("manifest table has unsupported attrs")
    row_count = descriptor["rows"]
    if type(row_count) is not int or row_count < 0:
        raise _fail("manifest table row count is invalid")
    digest = descriptor["sha256"]
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise _fail("manifest table checksum is invalid")
    relative = _safe_relative_file(descriptor["file"])
    path = root.joinpath(*PurePosixPath(relative).parts)
    root_resolved = root.resolve()
    try:
        path.resolve().relative_to(root_resolved)
    except (OSError, ValueError) as exc:
        raise _fail("dataset table path resolves outside the dataset directory") from exc
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise _fail("dataset table is missing or unreadable: %s" % relative) from exc
    if _sha256(payload) != digest:
        raise _fail("dataset table checksum mismatch: %s" % relative)
    schema = descriptor["schema"]
    if not isinstance(schema, Mapping) or set(schema) != {"index_names", "index_fields", "columns"}:
        raise _fail("dataset table schema is invalid")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _fail("dataset CSV is not UTF-8") from exc
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader)
    except StopIteration as exc:
        raise _fail("dataset CSV has no header") from exc
    except csv.Error as exc:
        raise _fail("dataset CSV header syntax is invalid") from exc
    index_fields = schema["index_fields"]
    columns = schema["columns"]
    index_names = schema["index_names"]
    if (
        not isinstance(index_fields, list)
        or not index_fields
        or not isinstance(columns, list)
        or not isinstance(index_names, list)
        or len(index_names) != len(index_fields)
    ):
        raise _fail("dataset table schema fields are invalid")
    if any(name is not None and (not isinstance(name, str) or not name) for name in index_names):
        raise _fail("dataset index names are invalid")
    for item in index_fields + columns:
        if (
            not isinstance(item, dict)
            or set(item) != {"name", "kind"}
            or not isinstance(item["name"], str)
            or not item["name"]
            or not isinstance(item["kind"], str)
            or item["kind"] not in _TABLE_KINDS
        ):
            raise _fail("dataset table field descriptor is invalid")
    for position, (name, field) in enumerate(zip(index_names, index_fields)):
        expected_index_field = name if name else "__index_%d__" % position
        if field["name"] != expected_index_field:
            raise _fail("dataset index field differs from its declared index name")
    expected_header = [item["name"] for item in index_fields] + [item["name"] for item in columns]
    if header != expected_header:
        raise _fail("dataset CSV header differs from its manifest schema")
    if len(set(expected_header)) != len(expected_header):
        raise _fail("dataset table schema contains duplicate field names")
    records = []
    try:
        for record in reader:
            if len(record) != len(expected_header):
                raise _fail("dataset CSV row has the wrong number of fields")
            records.append(record)
    except csv.Error as exc:
        raise _fail("dataset CSV syntax is invalid") from exc
    if len(records) != row_count:
        raise _fail("dataset table row count differs from its manifest")
    kinds = [item["kind"] for item in index_fields + columns]
    decoded = [[_decode(value, kind, pd) for value, kind in zip(row, kinds)] for row in records]
    index_count = len(index_fields)
    index_values = [[row[position] for row in decoded] for position in range(index_count)]
    for position, field in enumerate(index_fields):
        if field["kind"] == "datetime":
            try:
                index_values[position] = pd.DatetimeIndex(
                    pd.to_datetime(index_values[position], utc=True)
                )
            except (TypeError, ValueError) as exc:
                raise _fail("dataset datetime index cannot be reconstructed") from exc
    if index_count > 1:
        index = pd.MultiIndex.from_arrays(index_values, names=index_names)
    elif index_fields[0]["kind"] == "datetime":
        index = pd.DatetimeIndex(index_values[0], name=index_names[0])
    else:
        index = pd.Index(index_values[0], name=index_names[0])
    column_data = {}
    for offset, field in enumerate(columns, start=index_count):
        values = [row[offset] for row in decoded]
        kind = field["kind"]
        try:
            if kind == "bool":
                column_data[field["name"]] = pd.Series(
                    values,
                    index=index,
                    dtype="boolean" if any(value is None for value in values) else bool,
                )
            elif kind == "int":
                column_data[field["name"]] = pd.Series(
                    values,
                    index=index,
                    dtype="Int64" if any(v is None for v in values) else "int64",
                )
            elif kind == "float":
                column_data[field["name"]] = pd.Series(values, index=index, dtype="float64")
            elif kind == "datetime":
                column_data[field["name"]] = pd.Series(
                    pd.to_datetime(values, utc=True), index=index
                )
            else:
                column_data[field["name"]] = pd.Series(values, index=index, dtype=object)
        except (TypeError, ValueError, OverflowError) as exc:
            raise _fail("dataset CSV column cannot be reconstructed") from exc
    frame = pd.DataFrame(column_data, index=index)
    # Empty datasets still retain the declared column order and dtype class.
    if not records:
        frame = pd.DataFrame(index=index)
        for field in columns:
            kind = field["kind"]
            if kind == "bool":
                frame[field["name"]] = pd.Series(index=index, dtype=bool)
            elif kind == "int":
                frame[field["name"]] = pd.Series(index=index, dtype="int64")
            elif kind == "float":
                frame[field["name"]] = pd.Series(index=index, dtype="float64")
            elif kind == "datetime":
                frame[field["name"]] = pd.Series(index=index, dtype="datetime64[ns, UTC]")
            else:
                frame[field["name"]] = pd.Series(index=index, dtype=object)
    frame = frame.reindex(columns=[field["name"] for field in columns])
    if "source_metadata" in attrs:
        frame.attrs["source_metadata"] = attrs["source_metadata"]
    return frame


def load_dataset(path: Any) -> Any:
    """Load and fully validate a complete dataset; never unpickle or import code."""
    _pandas()
    from .dataset import ResearchDataset

    root = Path(path).expanduser().absolute()
    manifest_path = root / "manifest.json"
    if not root.is_dir() or not manifest_path.is_file():
        raise _fail("dataset is incomplete: manifest.json is absent")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise _fail("dataset manifest is unreadable or invalid JSON") from exc
    required = {
        "schema_version",
        "complete",
        "dataset_id",
        "targets",
        "factor_names",
        "groups",
        "metadata",
        "tables",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise _fail("dataset manifest fields are invalid")
    if type(manifest["schema_version"]) is not int:
        raise _fail("dataset schema version is invalid")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise _fail("unsupported dataset schema version")
    if manifest["complete"] is not True:
        raise _fail("dataset is incomplete")
    if (
        not isinstance(manifest["dataset_id"], str)
        or len(manifest["dataset_id"]) != 64
        or any(character not in "0123456789abcdef" for character in manifest["dataset_id"])
    ):
        raise _fail("dataset_id is invalid")
    if not isinstance(manifest["tables"], dict):
        raise _fail("dataset table manifest is invalid")
    allowed_logical = {
        "grid",
        "factors",
        "availability",
        "universe",
        "formula_universe",
        "prices_open",
        "prices_close",
        "precomputed_returns",
    }
    for logical in manifest["tables"]:
        if not isinstance(logical, str) or not logical:
            raise _fail("dataset manifest contains an invalid table name")
        if logical.startswith(("formula_inputs:", "classifications:")):
            prefix, name = logical.split(":", 1)
            if not name or prefix not in {"formula_inputs", "classifications"}:
                raise _fail("dataset manifest contains an invalid named table")
            continue
        if logical not in allowed_logical:
            raise _fail("dataset manifest contains an unknown table")
    for required_table in ("grid", "factors", "availability", "universe", "formula_universe"):
        if required_table not in manifest["tables"]:
            raise _fail("dataset manifest is missing required table %s" % required_table)
    loaded = {}
    seen_paths = set()
    for logical_name, descriptor in manifest["tables"].items():
        relative = _safe_relative_file(
            descriptor.get("file") if isinstance(descriptor, dict) else None
        )
        if relative in seen_paths:
            raise _fail("manifest maps multiple tables to the same file")
        seen_paths.add(relative)
        loaded[logical_name] = _read_table(root, logical_name, descriptor)
    tables = manifest["tables"]
    if ("prices_open" in tables) != ("prices_close" in tables):
        # Price mode requires both OHLC label matrices. A valid precomputed
        # return dataset may omit both, but partial price pairs are ambiguous.
        raise _fail("dataset must store both open and close prices or neither")
    prices = {}
    if "prices_open" in loaded:
        prices["open"] = loaded["prices_open"]
        prices["close"] = loaded["prices_close"]
    formula_inputs = {}
    classifications = {}
    for logical_name, frame in loaded.items():
        if logical_name.startswith("formula_inputs:"):
            formula_inputs[logical_name.split(":", 1)[1]] = frame
        elif logical_name.startswith("classifications:"):
            classifications[logical_name.split(":", 1)[1]] = frame
    metadata = manifest["metadata"]
    if not isinstance(metadata, dict) or set(metadata) != {"research", "provenance", "metadata"}:
        raise _fail("dataset metadata schema is invalid")
    research_metadata = metadata["research"]
    if (
        not isinstance(research_metadata, dict)
        or not isinstance(metadata["provenance"], dict)
        or not isinstance(metadata["metadata"], dict)
    ):
        raise _fail("dataset metadata members must be mappings")
    spec = dict(research_metadata)
    dataset = ResearchDataset(
        loaded["grid"],
        loaded["factors"],
        loaded["availability"],
        research_spec=spec,
        prices=prices or None,
        universe=loaded["universe"]["eligible"],
        groups=manifest["groups"],
        formula_universe=loaded["formula_universe"]["eligible"],
        formula_inputs=formula_inputs,
        classifications=classifications,
        precomputed_returns=loaded.get("precomputed_returns"),
        provenance=metadata["provenance"],
        metadata=metadata["metadata"],
    )
    if dataset.targets != tuple(manifest["targets"]):
        raise _fail("dataset target list differs from its reconstructed tables")
    if dataset.factor_names != tuple(manifest["factor_names"]):
        raise _fail("dataset factor list differs from its reconstructed tables")
    if dataset.dataset_id != manifest["dataset_id"]:
        raise _fail("dataset content identity does not match the manifest")
    return dataset


__all__ = ("save_dataset", "load_dataset", "compute_dataset_id", "SCHEMA_VERSION")
