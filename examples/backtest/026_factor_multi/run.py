"""Run the self-contained Iteration 45 multi-factor research example."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import os
import subprocess
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
GENERATOR_VERSION = "synthetic-ohlcv-sha256-v1"
EXAMPLE_ID = "026_factor_multi"
EVIDENCE_LEVEL = "SYNTHETIC_OFFLINE_FACTOR_RESEARCH_ONLY"
OPTIONAL_EVALUATION_TABLES = ("diagnostics",)
_EXPORT_REQUIRED_COLUMNS = {
    "signals": (
        "time",
        "asset",
        "signal",
        "variant",
        "pool_id",
        "group",
        "value",
        "quantile",
        "eligible",
        "pool_member",
        "candidate_count",
        "pool_member_count",
        "formation_loss_count",
        "formation_loss_rate",
        "value_status",
        "quantile_status",
        "value_reason",
        "quantile_reason",
        "reason",
        "detail",
    ),
    "labels": (
        "time",
        "asset",
        "horizon",
        "value",
        "entry_time",
        "exit_time",
        "entry_bar",
        "exit_bar",
        "reason",
        "detail",
    ),
    "ic": (
        "record_type",
        "time",
        "signal",
        "variant",
        "horizon",
        "segment_id",
        "segment_role",
        "pool_id",
        "group",
        "metric",
        "value",
        "status",
        "reason",
        "n_assets",
        "period",
        "mean",
        "sample_std",
        "information_ratio",
        "positive_fraction",
        "n_periods_total",
        "n_periods_valid",
    ),
    "ic_summary": (
        "record_type",
        "time",
        "period",
        "signal",
        "variant",
        "horizon",
        "segment_id",
        "segment_role",
        "pool_id",
        "group",
        "metric",
        "mean",
        "sample_std",
        "information_ratio",
        "positive_fraction",
        "n_periods_total",
        "n_periods_valid",
        "status",
        "reason",
    ),
    "quantile_returns": (
        "record_type",
        "time",
        "signal",
        "variant",
        "horizon",
        "segment_id",
        "segment_role",
        "pool_id",
        "group",
        "quantile",
        "mean",
        "status",
        "reason",
        "n_assets",
    ),
    "spreads": (
        "record_type",
        "time",
        "signal",
        "variant",
        "horizon",
        "segment_id",
        "segment_role",
        "pool_id",
        "group",
        "lower_quantile",
        "upper_quantile",
        "value",
        "status",
        "reason",
        "n_assets",
    ),
    "stability": (
        "record_type",
        "time",
        "signal",
        "variant",
        "segment_id",
        "segment_role",
        "pool_id",
        "group",
        "metric",
        "lag",
        "quantile",
        "value",
        "status",
        "reason",
        "n_assets",
    ),
    "correlation": (
        "record_type",
        "time",
        "segment_id",
        "segment_role",
        "signal_left",
        "signal_right",
        "variant_left",
        "variant_right",
        "pool_id",
        "group",
        "metric",
        "value",
        "status",
        "reason",
        "n_assets",
        "n_periods",
        "n_periods_total",
    ),
    "comparisons": (
        "record_type",
        "period",
        "segment_id",
        "segment_role",
        "comparison_id",
        "left_signal",
        "right_signal",
        "variant_left",
        "variant_right",
        "horizon",
        "pool_id",
        "group",
        "metric",
        "delta",
        "mean_delta",
        "sample_std_delta",
        "positive_delta_fraction",
        "status",
        "reason",
        "paired_period_count",
        "n_periods_total",
    ),
    "coverage": (
        "record_type",
        "time",
        "signal",
        "variant",
        "horizon",
        "segment_id",
        "segment_role",
        "pool_id",
        "group",
        "period_count",
        "excluded_count",
        "candidate_count",
        "pool_member_count",
        "finite_value_count",
        "factor_loss_count",
        "label_loss_count",
        "label_count",
        "paired_count",
        "quantile_valid_count",
        "quantile_loss_count",
        "quantile_loss_rate",
        "formation_loss_count",
        "analysis_loss_count",
        "segment_boundary_count",
        "loss_rate",
        "factor_loss_rate",
        "label_loss_rate",
        "status",
        "reason",
    ),
    "diagnostics": ("signal", "variant", "pool_id", "group", "reason", "count"),
}
_EXPORT_LOGICAL_TYPES = {
    "time": "utc_datetime",
    "entry_time": "utc_datetime",
    "exit_time": "utc_datetime",
    "period": "timestamp_or_label",
    "asset": "string",
    "signal": "string",
    "variant": "string",
    "pool_id": "string",
    "group": "string",
    "segment_id": "string",
    "segment_role": "string",
    "comparison_id": "string",
    "left_signal": "string",
    "right_signal": "string",
    "signal_left": "string",
    "signal_right": "string",
    "variant_left": "string",
    "variant_right": "string",
    "metric": "string",
    "status": "string",
    "reason": "string",
    "detail": "string",
    "record_type": "string",
    "value_status": "string",
    "quantile_status": "string",
    "value_reason": "string",
    "quantile_reason": "string",
    "eligible": "boolean",
    "pool_member": "boolean",
    "horizon": "integer",
    "entry_bar": "integer",
    "exit_bar": "integer",
    "quantile": "integer",
    "lower_quantile": "integer",
    "upper_quantile": "integer",
    "lag": "integer",
    "n_assets": "integer",
    "n_periods": "integer",
    "n_periods_total": "integer",
    "n_periods_valid": "integer",
    "paired_period_count": "integer",
    "candidate_count": "integer",
    "pool_member_count": "integer",
    "excluded_count": "integer",
    "finite_value_count": "integer",
    "label_count": "integer",
    "paired_count": "integer",
    "quantile_valid_count": "integer",
    "quantile_loss_count": "integer",
    "formation_loss_count": "integer",
    "analysis_loss_count": "integer",
    "segment_boundary_count": "integer",
    "period_count": "integer",
    "count": "integer",
    "value": "number",
    "mean": "number",
    "sample_std": "number",
    "information_ratio": "number",
    "positive_fraction": "number",
    "loss_rate": "number",
    "formation_loss_rate": "number",
    "quantile_loss_rate": "number",
    "factor_loss_rate": "number",
    "label_loss_rate": "number",
    "delta": "number",
    "mean_delta": "number",
    "sample_std_delta": "number",
    "positive_delta_fraction": "number",
}
_EXPORT_LOGICAL_TYPE_OVERRIDES = {
    ("signals", "quantile"): "number",
    ("ic_summary", "period"): "string",
}
_EXPORT_INTEGER_VALUE_COLUMNS = {"signals": ("quantile",)}


def _evaluation_exit_code(status: str, required_validation: Mapping[str, Any]) -> int:
    """Return zero only when the requested mandatory research outputs pass."""
    normalized_status = str(status).upper()
    if normalized_status in {"OK", "PARTIAL"} and required_validation.get("passed") is True:
        return 0
    return 1


def _failure_result(exc: BaseException) -> Tuple[str, int]:
    """Map prerequisite, output, interruption, and required-result failures."""
    if isinstance(exc, KeyboardInterrupt):
        return "INTERRUPTED", 3
    if isinstance(exc, OSError):
        return "OUTPUT_ERROR", 3
    error_code = getattr(exc, "code", None)
    if isinstance(exc, ImportError) or error_code == "DEPENDENCY_UNAVAILABLE":
        return "BLOCKED_DEPENDENCY", 2
    if error_code in {
        "INVALID_CONFIG",
        "INVALID_DATASET",
        "UNKNOWN_UNIVERSE",
        "MISSING_INPUT",
    }:
        return "INVALID_INPUT", 2
    return "FAILED", 1


def _load_config(path: Path = CONFIG_PATH) -> Dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("the example requires PyYAML to read config.yaml") from exc
    with path.open("r", encoding="utf-8") as source:
        value = yaml.safe_load(source)
    if not isinstance(value, dict) or value.get("example_id") != EXAMPLE_ID:
        raise ValueError("config.yaml does not describe %s" % EXAMPLE_ID)
    return value


def _stable_unit(seed: int, asset: str, bar: int, field: str) -> float:
    payload = "%s\0%d\0%s\0%d\0%s" % (
        GENERATOR_VERSION,
        seed,
        asset,
        bar,
        field,
    )
    raw = hashlib.sha256(payload.encode("utf-8")).digest()
    return int.from_bytes(raw[:8], "big") / float(1 << 64)


def build_synthetic_panel(data_config: Mapping[str, Any]) -> Dict[str, Any]:
    """Build deterministic OHLCV feeds and their full UTC session grid."""
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("the example requires the installed pandas dependency") from exc

    seed = data_config.get("seed")
    asset_count = data_config.get("asset_count")
    warmup = data_config.get("warmup_bars")
    research_bars = data_config.get("research_bars")
    tail = data_config.get("tail_bars")
    counts = (seed, asset_count, warmup, research_bars, tail)
    if any(type(value) is not int or value <= 0 for value in counts):
        raise ValueError("seed and all bar/asset counts must be positive integers")
    if research_bars != 260 or warmup < 20 or tail < 21 or asset_count < 20:
        raise ValueError(
            "the example requires 20 assets, 260 research bars, warm-up, and a 21-bar tail"
        )
    if data_config.get("generator_version") != GENERATOR_VERSION:
        raise ValueError("unsupported synthetic generator version")
    if data_config.get("source_timezone") != "UTC":
        raise ValueError("the synthetic session grid is explicitly UTC")

    start_value = data_config.get("start_date")
    start_date = (
        start_value if isinstance(start_value, date) else date.fromisoformat(str(start_value))
    )
    open_clock = time.fromisoformat(str(data_config["open_time_utc"]))
    close_clock = time.fromisoformat(str(data_config["close_time_utc"]))
    if open_clock >= close_clock:
        raise ValueError("each synthetic session must open before it closes")

    total_bars = warmup + research_bars + tail
    dates = []
    cursor = start_date
    while len(dates) < total_bars:
        if cursor.weekday() < 5:
            dates.append(cursor)
        cursor += timedelta(days=1)

    utc = timezone.utc
    open_times = [datetime.combine(day, open_clock).replace(tzinfo=utc) for day in dates]
    close_times = [datetime.combine(day, close_clock).replace(tzinfo=utc) for day in dates]
    close_index = pd.DatetimeIndex(close_times, name="close_time")
    grid = pd.DataFrame(
        {"open_time": pd.DatetimeIndex(open_times)},
        index=close_index,
    )

    prefix = data_config.get("asset_prefix")
    if not isinstance(prefix, str) or not prefix:
        raise ValueError("asset_prefix must be a non-empty string")
    assets = tuple("%s%02d" % (prefix, index) for index in range(asset_count))
    frames = {}
    for asset_index, asset in enumerate(assets):
        base = 70.0 + asset_index * 2.75
        previous_close = base
        rows = []
        for bar in range(total_bars):
            if bar < 15:
                # A shared zero-range prefix makes the KDJ recovery fixture
                # deterministic without changing the formula implementation.
                open_value = high_value = low_value = close_value = base
            else:
                overnight = (_stable_unit(seed, asset, bar, "overnight") - 0.5) * 0.006
                intraday = (_stable_unit(seed, asset, bar, "intraday") - 0.5) * 0.018
                open_value = previous_close * (1.0 + overnight)
                close_value = open_value * (1.0 + intraday)
                wick = 0.002 + _stable_unit(seed, asset, bar, "wick") * 0.012
                high_value = max(open_value, close_value) * (1.0 + wick)
                low_value = min(open_value, close_value) * (1.0 - wick)
            volume = 1000.0 + asset_index * 17.0 + 900.0 * _stable_unit(seed, asset, bar, "volume")
            rows.append((open_value, high_value, low_value, close_value, volume))
            previous_close = close_value
        frame = pd.DataFrame(
            rows,
            index=close_index,
            columns=("open", "high", "low", "close", "volume"),
            dtype="float64",
        )
        frames[asset] = frame

    prices = {
        field: pd.DataFrame(
            {asset: frames[asset][field].to_numpy(copy=True) for asset in assets},
            index=close_index,
            dtype="float64",
        )
        for field in ("open", "close")
    }
    digest = hashlib.sha256()
    for stamp in close_index:
        digest.update(stamp.isoformat().encode("ascii"))
        digest.update(b"\0")
        digest.update(grid.at[stamp, "open_time"].isoformat().encode("ascii"))
        digest.update(b"\n")
    for asset in assets:
        digest.update(asset.encode("utf-8"))
        digest.update(b"\0")
        for field in ("open", "high", "low", "close", "volume"):
            digest.update(field.encode("ascii"))
            digest.update(b"\0")
            for value in frames[asset][field].to_numpy():
                digest.update(float(value).hex().encode("ascii"))
                digest.update(b"\n")

    return {
        "grid": grid,
        "assets": assets,
        "feeds": frames,
        "prices": prices,
        "ohlcv_sha256": digest.hexdigest(),
        "bar_count": total_bars,
        "research_start_position": warmup,
        "research_end_position": warmup + research_bars - 1,
    }


def _resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (SCRIPT_DIR / path).resolve()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as target:
        json.dump(
            value,
            target,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )
        target.write("\n")
        target.flush()
        os.fsync(target.fileno())
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _invalid_export_value_column(table_name: str, record: Mapping[str, Any]) -> Optional[str]:
    """Check value semantics that are narrower than a serialized logical type."""
    for column_name in _EXPORT_INTEGER_VALUE_COLUMNS.get(table_name, ()):
        value = record.get(column_name)
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            return column_name
        if isinstance(value, str):
            try:
                number = float(value)
            except ValueError:
                return column_name
        elif isinstance(value, (int, float)):
            number = float(value)
        else:
            return column_name
        if not math.isfinite(number) or not number.is_integer():
            return column_name
    return None


def _artifact_manifest(root: Path) -> Dict[str, Dict[str, Any]]:
    artifacts = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name in {"run_manifest.json", "run_manifest.json.tmp"}:
            continue
        relative = path.relative_to(root).as_posix()
        artifacts[relative] = {"bytes": path.stat().st_size, "sha256": _sha256_file(path)}
    return artifacts


def _validate_export_output(
    path: Path,
    charts_requested: bool,
    expected_status: str,
    optional_tables: Sequence[str] = OPTIONAL_EVALUATION_TABLES,
    expected_evaluation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate the exported result against its declared, versioned file schemas."""
    if not path.is_dir():
        return {"passed": False, "reason": "evaluation_directory_missing"}
    table_names = tuple(_EXPORT_REQUIRED_COLUMNS)
    optional = tuple(optional_tables)
    if any(name not in table_names for name in optional):
        return {"passed": False, "reason": "unknown_optional_evaluation_table"}
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file() or manifest_path.stat().st_size == 0:
        return {"passed": False, "reason": "evaluation_manifest_missing_or_empty"}
    try:
        with manifest_path.open("r", encoding="utf-8") as source:
            manifest = json.load(source)
    except (OSError, ValueError):
        return {"passed": False, "reason": "evaluation_manifest_invalid"}
    if not isinstance(manifest, dict) or manifest.get("complete") is not True:
        return {"passed": False, "reason": "evaluation_manifest_incomplete"}
    if (
        manifest.get("schema") != "fincore-factor-research-result-v1"
        or manifest.get("result_schema_version") != 1
        or manifest.get("export_schema_version") != 1
    ):
        return {"passed": False, "reason": "evaluation_manifest_identity_invalid"}
    evaluation_id = manifest.get("evaluation_id")
    if (
        not isinstance(evaluation_id, str)
        or not evaluation_id
        or (expected_evaluation_id is not None and evaluation_id != expected_evaluation_id)
        or str(manifest.get("status", "")).upper() != expected_status
    ):
        return {"passed": False, "reason": "evaluation_manifest_status_or_id_missing"}

    schemas = manifest.get("result_table_schemas")
    tables = manifest.get("tables")
    file_records = manifest.get("files")
    expected_table_files = {name + suffix for name in table_names for suffix in (".csv", ".json")}
    expected_file_records = expected_table_files | (
        {"ic_summary.png"} if charts_requested else set()
    )
    if (
        not isinstance(schemas, dict)
        or set(schemas) != set(table_names)
        or not isinstance(tables, dict)
        or set(tables) != set(table_names)
        or not isinstance(file_records, dict)
        or set(file_records) != expected_file_records
    ):
        return {"passed": False, "reason": "evaluation_manifest_table_inventory_invalid"}

    allowed_types = {"utc_datetime", "timestamp_or_label", "string", "integer", "number", "boolean"}
    validated_files = 0
    validated_rows = 0
    for table_name in table_names:
        schema = schemas[table_name]
        columns = schema.get("columns") if isinstance(schema, dict) else None
        if not isinstance(columns, list) or not columns:
            return {
                "passed": False,
                "reason": "evaluation_table_schema_missing",
                "table": table_name,
            }
        column_names = []
        for column in columns:
            if not isinstance(column, dict) or set(column) != {"name", "type"}:
                return {
                    "passed": False,
                    "reason": "evaluation_table_schema_invalid",
                    "table": table_name,
                }
            name, logical_type = column["name"], column["type"]
            if (
                not isinstance(name, str)
                or not name
                or not isinstance(logical_type, str)
                or logical_type not in allowed_types
            ):
                return {
                    "passed": False,
                    "reason": "evaluation_table_schema_invalid",
                    "table": table_name,
                }
            expected_type = _EXPORT_LOGICAL_TYPE_OVERRIDES.get(
                (table_name, name), _EXPORT_LOGICAL_TYPES.get(name)
            )
            if expected_type is not None and logical_type != expected_type:
                return {
                    "passed": False,
                    "reason": "evaluation_table_column_type_invalid",
                    "table": table_name,
                    "column": name,
                }
            column_names.append(name)
        if len(set(column_names)) != len(column_names):
            return {
                "passed": False,
                "reason": "evaluation_table_schema_duplicate_column",
                "table": table_name,
            }
        if tuple(column_names) != _EXPORT_REQUIRED_COLUMNS[table_name]:
            return {
                "passed": False,
                "reason": "evaluation_table_schema_columns_mismatch",
                "table": table_name,
            }

        table_manifest = tables[table_name]
        if not isinstance(table_manifest, dict) or table_manifest != {
            "csv": table_name + ".csv",
            "json": table_name + ".json",
        }:
            return {
                "passed": False,
                "reason": "evaluation_manifest_table_identity_invalid",
                "table": table_name,
            }
        table_row_counts = []
        for suffix, media_type in (
            (".csv", "text/csv; charset=utf-8"),
            (".json", "application/json"),
        ):
            filename = table_name + suffix
            table_path = path / filename
            file_record = file_records.get(filename)
            if not table_path.is_file() or not isinstance(file_record, dict):
                return {
                    "passed": False,
                    "reason": "evaluation_table_file_missing",
                    "file": filename,
                }
            if (
                isinstance(file_record.get("bytes"), bool)
                or not isinstance(file_record.get("bytes"), int)
                or file_record["bytes"] != table_path.stat().st_size
                or file_record.get("sha256") != _sha256_file(table_path)
                or isinstance(file_record.get("rows"), bool)
                or not isinstance(file_record.get("rows"), int)
                or file_record.get("media_type") != media_type
            ):
                return {
                    "passed": False,
                    "reason": "evaluation_table_file_manifest_mismatch",
                    "file": filename,
                }
            try:
                if suffix == ".csv":
                    with table_path.open("r", encoding="utf-8", newline="") as source:
                        reader = csv.reader(source)
                        header = next(reader, None)
                        if header != column_names:
                            return {
                                "passed": False,
                                "reason": "evaluation_csv_schema_mismatch",
                                "file": filename,
                            }
                        row_count = 0
                        for row in reader:
                            if len(row) != len(column_names):
                                return {
                                    "passed": False,
                                    "reason": "evaluation_csv_row_width_mismatch",
                                    "file": filename,
                                }
                            invalid_column = _invalid_export_value_column(
                                table_name, dict(zip(column_names, row))
                            )
                            if invalid_column is not None:
                                return {
                                    "passed": False,
                                    "reason": "evaluation_table_value_semantic_invalid",
                                    "file": filename,
                                    "column": invalid_column,
                                    "row": row_count + 2,
                                }
                            row_count += 1
                else:
                    with table_path.open("r", encoding="utf-8") as source:
                        records = json.load(source)
                    if not isinstance(records, list):
                        return {
                            "passed": False,
                            "reason": "evaluation_json_records_invalid",
                            "file": filename,
                        }
                    for record_index, record in enumerate(records):
                        if not isinstance(record, dict) or list(record) != column_names:
                            return {
                                "passed": False,
                                "reason": "evaluation_json_schema_mismatch",
                                "file": filename,
                            }
                        invalid_column = _invalid_export_value_column(table_name, record)
                        if invalid_column is not None:
                            return {
                                "passed": False,
                                "reason": "evaluation_table_value_semantic_invalid",
                                "file": filename,
                                "column": invalid_column,
                                "row": record_index + 1,
                            }
                    row_count = len(records)
            except (OSError, UnicodeError, csv.Error, ValueError):
                return {
                    "passed": False,
                    "reason": "evaluation_table_content_invalid",
                    "file": filename,
                }
            if row_count != file_record["rows"]:
                return {
                    "passed": False,
                    "reason": "evaluation_table_row_count_mismatch",
                    "file": filename,
                }
            table_row_counts.append(row_count)
            validated_files += 1
        if table_row_counts[0] != table_row_counts[1]:
            return {
                "passed": False,
                "reason": "evaluation_csv_json_row_count_mismatch",
                "table": table_name,
            }
        validated_rows += table_row_counts[0]

    chart_path = path / "ic_summary.png"
    chart_file_count = 0
    if charts_requested:
        chart_record = file_records.get("ic_summary.png")
        if not chart_path.is_file() or not isinstance(chart_record, dict):
            return {"passed": False, "reason": "requested_chart_missing"}
        chart_bytes = chart_path.stat().st_size
        if (
            chart_bytes <= 0
            or isinstance(chart_record.get("bytes"), bool)
            or not isinstance(chart_record.get("bytes"), int)
            or chart_record["bytes"] != chart_bytes
            or chart_record.get("sha256") != _sha256_file(chart_path)
            or chart_record.get("media_type") != "image/png"
            or set(chart_record) != {"sha256", "bytes", "media_type"}
        ):
            return {"passed": False, "reason": "evaluation_chart_manifest_mismatch"}
        chart_file_count = 1
    return {
        "passed": True,
        "table_file_count": validated_files,
        "table_row_count": validated_rows,
        "chart_file_count": chart_file_count,
        "evaluation_id": evaluation_id,
        "optional_tables": list(optional),
    }


def _package_version(name: str) -> Optional[str]:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _source_root(path: Path) -> Optional[Path]:
    for parent in path.parents:
        if (parent / ".git").exists():
            return parent
    return None


def _module_facts(module_name: str, distribution: str) -> Dict[str, Any]:
    import importlib

    module = importlib.import_module(module_name)
    module_path = Path(module.__file__).resolve()
    facts: Dict[str, Any] = {
        "version": getattr(module, "__version__", None) or _package_version(distribution),
        "module_file": str(module_path),
    }
    root = _source_root(module_path)
    if root is not None:
        try:
            completed = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        else:
            facts["source_commit"] = completed.stdout.strip()
    return facts


def _create_research_spec(config: Mapping[str, Any], panel: Mapping[str, Any]) -> Any:
    from backtrader.research import ResearchSpec

    data_config = config["data"]
    grid = panel["grid"]
    first = panel["research_start_position"]
    last = panel["research_end_position"]
    groups = dict.fromkeys(panel["assets"], data_config["group"])
    return ResearchSpec(
        grid=grid,
        start=grid.index[first],
        end=grid.index[last],
        targets=panel["assets"],
        source_timezone=data_config["source_timezone"],
        snapshot_id=data_config["snapshot_id"],
        price_basis=data_config["price_basis"],
        calendar_id=data_config["calendar_id"],
        frequency=data_config["frequency"],
        feed_time_kind="close_time",
        groups=groups,
    )


def _validate_dataset(config: Mapping[str, Any], dataset: Any) -> Dict[str, Any]:
    from backtrader.research.errors import DatasetError

    data_config = config["data"]
    expected_grid_rows = (
        data_config["warmup_bars"] + data_config["research_bars"] + data_config["tail_bars"]
    )
    expected_targets = tuple(
        "%s%02d" % (data_config["asset_prefix"], index)
        for index in range(data_config["asset_count"])
    )
    if tuple(dataset.targets) != expected_targets:
        raise DatasetError("dataset targets do not match this multi-factor example")
    if len(dataset.grid) != expected_grid_rows:
        raise DatasetError("dataset grid does not preserve warm-up, research, and tail bars")
    expected_factors = tuple(sorted(config["factors"]))
    if tuple(dataset.factor_names) != expected_factors:
        raise DatasetError("dataset factor schema does not match this multi-factor example")
    grid = dataset.grid
    research_rows = grid.index[(grid.index >= dataset.start) & (grid.index <= dataset.end)]
    if len(research_rows) != data_config["research_bars"]:
        raise DatasetError("dataset research interval does not contain 260 bars")
    expected_start = grid.index[data_config["warmup_bars"]]
    expected_end = grid.index[data_config["warmup_bars"] + data_config["research_bars"] - 1]
    if dataset.start != expected_start or dataset.end != expected_end:
        raise DatasetError(
            "dataset research interval does not preserve the configured bar positions"
        )
    metadata = dataset.metadata.get("research", {})
    for field in ("snapshot_id", "price_basis", "calendar_id", "frequency", "source_timezone"):
        if metadata.get(field) != data_config[field]:
            raise DatasetError("dataset %s does not match this example" % field)
    if metadata.get("feed_time_kind") != "close_time":
        raise DatasetError("dataset feed time kind does not match this example")
    if set(dataset.groups.values()) != {data_config["group"]}:
        raise DatasetError("dataset group mapping does not match this example")
    prices = dataset.prices
    if set(prices) != {"open", "close"}:
        raise DatasetError("dataset must preserve full-grid open and close prices")
    for name, frame in prices.items():
        if frame.shape != (expected_grid_rows, len(expected_targets)):
            raise DatasetError("dataset %s prices do not cover the full grid" % name)
        if tuple(frame.columns) != expected_targets:
            raise DatasetError("dataset %s price columns do not match the target order" % name)
        if any(not math.isfinite(float(value)) for value in frame.to_numpy().ravel()):
            raise DatasetError("dataset %s prices contain missing or non-finite values" % name)
    expected_factor_rows = data_config["research_bars"] * len(expected_targets)
    if len(dataset.raw_factors) != expected_factor_rows:
        raise DatasetError("dataset factor panel does not cover every research asset/bar")
    return {
        "dataset_id": dataset.dataset_id,
        "targets": len(dataset.targets),
        "grid_rows": len(dataset.grid),
        "research_rows": len(dataset.raw_factors),
        "factor_names": list(dataset.factor_names),
    }


def _evaluation_spec(config: Mapping[str, Any], dataset: Any, periods: Sequence[int]) -> Any:
    from fincore.factor_analysis.research import ResearchEvaluationSpec

    research = dataset.metadata["research"]
    grid = dataset.grid
    research_times = grid.index[(grid.index >= dataset.start) & (grid.index <= dataset.end)]
    configured = config["evaluation"]
    segments = {}
    for name, definition in configured["segments"].items():
        first = definition["research_bar_start"]
        last = definition["research_bar_end"]
        if (
            type(first) is not int
            or type(last) is not int
            or not (0 <= first <= last < len(research_times))
        ):
            raise ValueError("configured segment positions must fall inside the research grid")
        segments[name] = (research_times[first], research_times[last], definition["role"])
    return ResearchEvaluationSpec(
        targets=dataset.targets,
        start=dataset.start,
        end=dataset.end,
        snapshot_id=research["snapshot_id"],
        price_basis=research["price_basis"],
        calendar_id=research["calendar_id"],
        frequency=research["frequency"],
        source_timezone=research.get("source_timezone", "UTC"),
        feed_time_kind=research.get("feed_time_kind", "close_time"),
        periods=tuple(periods),
        label=configured["label"],
        precomputed_entry=configured["precomputed_entry"],
        quantiles=configured["quantiles"],
        min_assets=configured["min_assets"],
        min_quantile_assets=configured["min_quantile_assets"],
        preprocess=configured["preprocess"],
        max_loss=configured["max_loss"],
        stability_lags=tuple(configured["stability_lags"]),
        direction_overrides={},
        combinations=configured.get("combinations", {}),
        comparisons=configured.get("comparisons", {}),
        segments=segments,
    )


def _validate_result(
    result: Any,
    expected_signals: Mapping[str, Sequence[str]],
    periods: Sequence[int],
    *,
    group: str,
    segment_bars: Mapping[str, int],
    asset_count: int,
    research_times: Sequence[Any],
    target_assets: Sequence[str],
    grid_close_times: Sequence[Any],
    grid_open_times: Sequence[Any],
    quantiles: int,
    stability_lags: Sequence[int],
    comparison_id: str,
    base_signals: Sequence[str],
    segment_times: Mapping[str, Sequence[Any]],
    max_loss: float,
    required_optional_tables: Sequence[str] = (),
    signal_pools: Optional[Mapping[str, Sequence[str]]] = None,
) -> Dict[str, Any]:
    """Check requested research coverage without judging signal performance."""
    status_value = getattr(result, "status", None)
    status = getattr(status_value, "value", status_value)
    if status is None:
        manifest = getattr(result, "manifest", {}) or {}
        status = manifest.get("status") if hasattr(manifest, "get") else None
    status = str(status).upper()
    if status not in {"OK", "PARTIAL"}:
        return {
            "passed": False,
            "reason": "evaluation_status_%s" % (status or "MISSING"),
            "status": status,
        }

    schemas = {
        "signals": ("time", "asset", "signal", "variant", "pool_id", "group", "value"),
        "labels": (
            "time",
            "asset",
            "horizon",
            "value",
            "entry_time",
            "exit_time",
            "entry_bar",
            "exit_bar",
        ),
        "ic": (
            "time",
            "segment_id",
            "signal",
            "variant",
            "pool_id",
            "group",
            "horizon",
            "metric",
            "value",
            "status",
            "reason",
            "n_assets",
        ),
        "ic_summary": (
            "record_type",
            "time",
            "segment_id",
            "period",
            "signal",
            "variant",
            "pool_id",
            "group",
            "horizon",
            "metric",
            "mean",
            "sample_std",
            "information_ratio",
            "positive_fraction",
            "n_periods_total",
            "n_periods_valid",
            "status",
            "reason",
        ),
        "quantile_returns": (
            "record_type",
            "time",
            "segment_id",
            "signal",
            "variant",
            "pool_id",
            "group",
            "horizon",
            "quantile",
            "mean",
            "status",
            "reason",
            "n_assets",
        ),
        "spreads": (
            "record_type",
            "time",
            "segment_id",
            "signal",
            "variant",
            "pool_id",
            "group",
            "horizon",
            "lower_quantile",
            "upper_quantile",
            "value",
            "status",
            "reason",
            "n_assets",
        ),
        "stability": (
            "time",
            "segment_id",
            "segment_role",
            "signal",
            "variant",
            "pool_id",
            "group",
            "metric",
            "lag",
            "quantile",
            "value",
            "status",
            "reason",
            "n_assets",
        ),
        "coverage": (
            "record_type",
            "time",
            "segment_id",
            "segment_role",
            "signal",
            "variant",
            "pool_id",
            "group",
            "horizon",
            "candidate_count",
            "pool_member_count",
            "finite_value_count",
            "label_count",
            "paired_count",
            "formation_loss_count",
            "analysis_loss_count",
            "segment_boundary_count",
            "loss_rate",
            "status",
            "reason",
            "period_count",
        ),
        "correlation": (
            "record_type",
            "time",
            "segment_id",
            "signal_left",
            "signal_right",
            "variant_left",
            "variant_right",
            "pool_id",
            "group",
            "metric",
            "value",
            "status",
            "reason",
            "n_assets",
            "n_periods",
        ),
        "comparisons": (
            "record_type",
            "period",
            "segment_id",
            "comparison_id",
            "left_signal",
            "right_signal",
            "variant_left",
            "variant_right",
            "horizon",
            "pool_id",
            "group",
            "metric",
            "delta",
            "mean_delta",
            "sample_std_delta",
            "positive_delta_fraction",
            "paired_period_count",
            "n_periods_total",
            "status",
            "reason",
        ),
    }
    if "diagnostics" in required_optional_tables:
        schemas["diagnostics"] = ("signal", "variant", "pool_id", "group", "reason", "count")
    tables = {}
    missing_tables = []
    for name, columns in schemas.items():
        table = getattr(result, name, None)
        if table is None or not hasattr(table, "columns"):
            missing_tables.append(name)
            continue
        if getattr(table, "empty", False):
            missing_tables.append(name)
            continue
        records = table
        if set(columns) - set(records.columns):
            try:
                records = records.reset_index()
            except (TypeError, ValueError):
                missing_tables.append(name + ":schema")
                continue
        if set(columns) - set(records.columns):
            missing_tables.append(name + ":schema")
            continue
        tables[name] = records
    if missing_tables:
        return {
            "passed": False,
            "reason": "required_result_tables_missing_or_incompatible",
            "missing_tables": sorted(missing_tables),
            "status": status,
        }

    def finite(value: Any) -> bool:
        try:
            return not isinstance(value, bool) and math.isfinite(float(value))
        except (TypeError, ValueError, OverflowError):
            return False

    def timestamp_key(value: Any) -> str:
        if hasattr(value, "to_pydatetime"):
            value = value.to_pydatetime()
        if isinstance(value, datetime) and value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    def selected(table_name: str, **criteria: Any) -> Any:
        frame = tables[table_name]
        for column, value in criteria.items():
            frame = frame.loc[frame[column].eq(value)]
        return frame

    def has_finite(table_name: str, value_column: str, **criteria: Any) -> bool:
        rows = selected(table_name, **criteria)
        if rows.empty:
            return False
        if "status" in rows.columns:
            rows = rows.loc[rows["status"].eq("OK")]
        return bool(rows[value_column].map(finite).any())

    def has_expected_period_rows(
        table_name: str,
        value_column: str,
        time_column: str,
        expected_times: Sequence[Any],
        boundary_times: Sequence[Any],
        **criteria: Any,
    ) -> bool:
        rows = selected(table_name, **criteria)
        expected_keys = {timestamp_key(value) for value in expected_times}
        boundary_keys = {timestamp_key(value) for value in boundary_times}
        actual_keys = {timestamp_key(value) for value in rows[time_column]}
        if (
            len(rows) != len(expected_keys)
            or rows[time_column].map(timestamp_key).duplicated().any()
            or actual_keys != expected_keys
        ):
            return False
        for _, row in rows.iterrows():
            key = timestamp_key(row[time_column])
            state = str(row["status"]).upper()
            if key in boundary_keys:
                if state not in {"PARTIAL", "UNEVALUABLE"} or finite(row[value_column]):
                    return False
                if not isinstance(row["reason"], str) or not row["reason"].strip():
                    return False
            elif state != "OK" or not finite(row[value_column]):
                return False
        return True

    def expected_boundary_times(segment_id: str, horizon: int) -> Tuple[Any, ...]:
        if segment_id == "full":
            return ()
        times = segment_times[segment_id]
        return tuple(times[-min(horizon + 1, len(times)) :])

    axes = []
    for signal, variants in expected_signals.items():
        for variant in variants:
            pools = (signal_pools or {}).get(signal, ("own:" + signal,))
            axes.extend((signal, variant, pool_id) for pool_id in pools)
            common_pool = "common:" + comparison_id
            if common_pool not in pools:
                axes.append((signal, variant, common_pool))
    missing = []

    def record_missing(kind: str, **key: Any) -> None:
        missing.append({"table": kind, **key})

    expected_label_keys = {
        (timestamp_key(stamp), asset) for stamp in research_times for asset in target_assets
    }
    close_positions = {timestamp_key(stamp): index for index, stamp in enumerate(grid_close_times)}
    open_positions = {timestamp_key(stamp): index for index, stamp in enumerate(grid_open_times)}
    for horizon in periods:
        rows = selected("labels", horizon=horizon)
        expected_rows = len(expected_label_keys)
        valid_values = rows["value"].map(finite)
        valid_times = rows["entry_time"].notna() & rows["exit_time"].notna()
        actual_label_keys = {
            (timestamp_key(stamp), asset) for stamp, asset in zip(rows["time"], rows["asset"])
        }
        valid_bars = rows.apply(
            lambda row, expected_horizon=horizon: (
                finite(row["entry_bar"])
                and finite(row["exit_bar"])
                and float(row["entry_bar"]).is_integer()
                and float(row["exit_bar"]).is_integer()
                and timestamp_key(row["time"]) in close_positions
                and timestamp_key(row["entry_time"]) in open_positions
                and timestamp_key(row["exit_time"]) in open_positions
                and open_positions[timestamp_key(row["entry_time"])]
                == close_positions[timestamp_key(row["time"])] + 1
                and int(row["entry_bar"]) == open_positions[timestamp_key(row["entry_time"])]
                and int(row["exit_bar"]) == open_positions[timestamp_key(row["exit_time"])]
                and int(row["exit_bar"]) - int(row["entry_bar"]) == expected_horizon
            ),
            axis=1,
        )
        if (
            len(rows) != expected_rows
            or actual_label_keys != expected_label_keys
            or rows.duplicated(["time", "asset"]).any()
            or not bool(valid_values.all())
            or not bool(valid_times.all())
            or not bool(valid_bars.all())
        ):
            record_missing(
                "labels", horizon=horizon, expected_rows=expected_rows, actual_rows=len(rows)
            )

    for signal, variant, pool_id in axes:
        rows = selected("signals", signal=signal, variant=variant, pool_id=pool_id, group=group)
        actual_keys = {
            (timestamp_key(stamp), asset) for stamp, asset in zip(rows["time"], rows["asset"])
        }
        if (
            len(rows) != len(expected_label_keys)
            or rows.duplicated(["time", "asset"]).any()
            or actual_keys != expected_label_keys
        ):
            record_missing("signals", signal=signal, variant=variant, pool_id=pool_id, group=group)

    for signal, variant, pool_id in axes:
        for segment_id in segment_bars:
            for horizon in periods:
                boundary_times = expected_boundary_times(segment_id, horizon)
                for metric in ("pearson", "spearman"):
                    key = {
                        "signal": signal,
                        "variant": variant,
                        "pool_id": pool_id,
                        "group": group,
                        "segment_id": segment_id,
                        "horizon": horizon,
                        "metric": metric,
                    }
                    if not has_expected_period_rows(
                        "ic", "value", "time", segment_times[segment_id], boundary_times, **key
                    ):
                        record_missing("ic", **key)
                    summary_key = dict(key)
                    summary_key["record_type"] = "summary"
                    summary_key["period"] = "all"
                    summary = selected("ic_summary", **summary_key)
                    if len(summary) != 1:
                        record_missing("ic_summary", **summary_key)
                    else:
                        row = summary.iloc[0]
                        expected_valid_periods = segment_bars[segment_id] - len(boundary_times)
                        # FinCore may keep a finite summary status at OK while
                        # reporting excluded segment-edge periods in the counts.
                        expected_summary_statuses = (
                            {"OK"} if not boundary_times else {"OK", "PARTIAL"}
                        )
                        if (
                            str(row["status"]).upper() not in expected_summary_statuses
                            or not finite(row["mean"])
                            or not finite(row["sample_std"])
                            or not finite(row["information_ratio"])
                            or not finite(row["positive_fraction"])
                            or not finite(row["n_periods_total"])
                            or not finite(row["n_periods_valid"])
                            or float(row["n_periods_total"]) != segment_bars[segment_id]
                            or float(row["n_periods_valid"]) != expected_valid_periods
                        ):
                            record_missing("ic_summary", **summary_key)
                for quantile in range(1, quantiles + 1):
                    key = {
                        "signal": signal,
                        "variant": variant,
                        "pool_id": pool_id,
                        "group": group,
                        "segment_id": segment_id,
                        "horizon": horizon,
                        "quantile": quantile,
                    }
                    key["record_type"] = "period"
                    if not has_expected_period_rows(
                        "quantile_returns",
                        "mean",
                        "time",
                        segment_times[segment_id],
                        boundary_times,
                        **key,
                    ):
                        record_missing("quantile_returns", **key)
                spread_key = {
                    "signal": signal,
                    "variant": variant,
                    "pool_id": pool_id,
                    "group": group,
                    "segment_id": segment_id,
                    "horizon": horizon,
                    "record_type": "period",
                }
                if not has_expected_period_rows(
                    "spreads",
                    "value",
                    "time",
                    segment_times[segment_id],
                    boundary_times,
                    **spread_key,
                ):
                    record_missing("spreads", **spread_key)

                coverage_key = {
                    "record_type": "summary",
                    "signal": signal,
                    "variant": variant,
                    "pool_id": pool_id,
                    "group": group,
                    "segment_id": segment_id,
                    "horizon": horizon,
                }
                coverage = selected("coverage", **coverage_key)
                expected_candidates = segment_bars[segment_id] * asset_count
                expected_boundary_count = len(boundary_times) * asset_count
                expected_paired_count = expected_candidates - expected_boundary_count
                if len(coverage) != 1:
                    record_missing(
                        "coverage", **coverage_key, expected_candidates=expected_candidates
                    )
                else:
                    row = coverage.iloc[0]
                    count_columns = (
                        "candidate_count",
                        "pool_member_count",
                        "finite_value_count",
                        "label_count",
                        "paired_count",
                        "formation_loss_count",
                        "analysis_loss_count",
                        "segment_boundary_count",
                    )
                    counts_valid = all(
                        finite(row[column])
                        and float(row[column]) >= 0
                        and float(row[column]).is_integer()
                        and float(row[column]) <= expected_candidates
                        for column in count_columns
                    )
                    rates_valid = all(
                        finite(row[column]) and 0.0 <= float(row[column]) <= 1.0
                        for column in ("loss_rate",)
                    )
                    if (
                        not counts_valid
                        or not rates_valid
                        or str(row["status"]).upper() != ("PARTIAL" if boundary_times else "OK")
                        or int(row["candidate_count"]) != expected_candidates
                        or int(row["pool_member_count"]) != expected_candidates
                        or int(row["finite_value_count"]) != expected_candidates
                        or int(row["label_count"]) != expected_candidates
                        or int(row["paired_count"]) != expected_paired_count
                        or int(row["formation_loss_count"]) != 0
                        # Segment boundaries are analysis losses and are also
                        # broken out explicitly in segment_boundary_count.
                        or int(row["analysis_loss_count"]) != expected_boundary_count
                        or int(row["segment_boundary_count"]) != expected_boundary_count
                        or float(row["loss_rate"]) > max_loss
                        or not finite(row["period_count"])
                        or not float(row["period_count"]).is_integer()
                        or int(row["period_count"]) != segment_bars[segment_id]
                    ):
                        record_missing(
                            "coverage", **coverage_key, expected_candidates=expected_candidates
                        )

            for lag in stability_lags:
                for metric in ("rank_autocorrelation", "quantile_turnover"):
                    rows = selected(
                        "stability",
                        signal=signal,
                        variant=variant,
                        pool_id=pool_id,
                        group=group,
                        segment_id=segment_id,
                        lag=lag,
                        metric=metric,
                    )
                    if metric == "quantile_turnover":
                        for quantile in range(1, quantiles + 1):
                            if not has_finite(
                                "stability",
                                "value",
                                signal=signal,
                                variant=variant,
                                pool_id=pool_id,
                                group=group,
                                segment_id=segment_id,
                                lag=lag,
                                metric=metric,
                                quantile=quantile,
                            ):
                                record_missing(
                                    "stability",
                                    signal=signal,
                                    variant=variant,
                                    pool_id=pool_id,
                                    group=group,
                                    segment_id=segment_id,
                                    lag=lag,
                                    metric=metric,
                                    quantile=quantile,
                                )
                    elif rows.empty or not bool(
                        rows.loc[rows["status"].eq("OK"), "value"].map(finite).any()
                    ):
                        record_missing(
                            "stability",
                            signal=signal,
                            variant=variant,
                            pool_id=pool_id,
                            group=group,
                            segment_id=segment_id,
                            lag=lag,
                            metric=metric,
                        )

    base_pairs = tuple(
        (base_signals[left], base_signals[right])
        for left in range(len(base_signals))
        for right in range(left + 1, len(base_signals))
    )
    for segment_id in segment_bars:
        for left, right in base_pairs:
            for metric in ("pearson", "spearman"):
                rows = selected(
                    "correlation",
                    record_type="summary",
                    signal_left=right,
                    signal_right=left,
                    variant_left="transformed",
                    variant_right="transformed",
                    pool_id="common:" + comparison_id,
                    group=group,
                    segment_id=segment_id,
                    metric=metric,
                )
                if rows.empty:
                    rows = selected(
                        "correlation",
                        record_type="summary",
                        signal_left=left,
                        signal_right=right,
                        variant_left="transformed",
                        variant_right="transformed",
                        pool_id="common:" + comparison_id,
                        group=group,
                        segment_id=segment_id,
                        metric=metric,
                    )
                if (
                    len(rows) != 1
                    or str(rows.iloc[0]["status"]).upper() != "OK"
                    or not finite(rows.iloc[0]["value"])
                    or not finite(rows.iloc[0]["n_periods"])
                    or float(rows.iloc[0]["n_periods"]) != segment_bars[segment_id]
                ):
                    record_missing(
                        "correlation",
                        signal_left=left,
                        signal_right=right,
                        pool_id="common:" + comparison_id,
                        group=group,
                        segment_id=segment_id,
                        metric=metric,
                    )

    # Require every unordered pair in the configured common-pool family,
    # including the generated leave-one-out ablations.
    full_combo = expected_signals.get("equal_weight", ())
    comparison_signals = tuple(expected_signals)
    comparison_variants = {
        name: "transformed" if name in base_signals else "composite" for name in comparison_signals
    }
    for left_index, left in enumerate(comparison_signals):
        for right in comparison_signals[left_index + 1 :]:
            left_variant = comparison_variants[left]
            right_variant = comparison_variants[right]
            for segment_id in segment_bars:
                for horizon in periods:
                    boundary_times = expected_boundary_times(segment_id, horizon)
                    expected_valid_periods = segment_bars[segment_id] - len(boundary_times)
                    for metric in ("pearson", "spearman"):
                        rows = selected(
                            "comparisons",
                            record_type="summary",
                            period="all",
                            comparison_id=comparison_id,
                            left_signal=left,
                            right_signal=right,
                            variant_left=left_variant,
                            variant_right=right_variant,
                            pool_id="common:" + comparison_id,
                            group=group,
                            segment_id=segment_id,
                            horizon=horizon,
                            metric=metric,
                        )
                        if rows.empty:
                            rows = selected(
                                "comparisons",
                                record_type="summary",
                                period="all",
                                comparison_id=comparison_id,
                                left_signal=right,
                                right_signal=left,
                                variant_left=right_variant,
                                variant_right=left_variant,
                                pool_id="common:" + comparison_id,
                                group=group,
                                segment_id=segment_id,
                                horizon=horizon,
                                metric=metric,
                            )
                        if len(rows) != 1 or str(rows.iloc[0]["status"]).upper() != (
                            "PARTIAL" if boundary_times else "OK"
                        ):
                            record_missing(
                                "comparisons",
                                signal_left=left,
                                signal_right=right,
                                pool_id="common:" + comparison_id,
                                group=group,
                                segment_id=segment_id,
                                horizon=horizon,
                                metric=metric,
                            )
                            continue
                        row = rows.iloc[0]
                        if (
                            not finite(row["mean_delta"])
                            or not finite(row["sample_std_delta"])
                            or float(row["sample_std_delta"]) < 0.0
                            or not finite(row["positive_delta_fraction"])
                            or not 0.0 <= float(row["positive_delta_fraction"]) <= 1.0
                            or not finite(row["paired_period_count"])
                            or not float(row["paired_period_count"]).is_integer()
                            or float(row["paired_period_count"]) != expected_valid_periods
                            or not finite(row["n_periods_total"])
                            or not float(row["n_periods_total"]).is_integer()
                            or float(row["n_periods_total"]) != segment_bars[segment_id]
                        ):
                            record_missing(
                                "comparisons",
                                signal_left=left,
                                signal_right=right,
                                pool_id="common:" + comparison_id,
                                group=group,
                                segment_id=segment_id,
                                horizon=horizon,
                                metric=metric,
                            )
                            continue
                        period_key = {
                            "comparison_id": comparison_id,
                            "left_signal": left,
                            "right_signal": right,
                            "variant_left": left_variant,
                            "variant_right": right_variant,
                            "pool_id": "common:" + comparison_id,
                            "group": group,
                            "segment_id": segment_id,
                            "horizon": horizon,
                            "metric": metric,
                            "record_type": "period",
                        }
                        if not has_expected_period_rows(
                            "comparisons",
                            "delta",
                            "period",
                            segment_times[segment_id],
                            boundary_times,
                            **period_key,
                        ):
                            reversed_period_key = dict(period_key)
                            reversed_period_key.update(
                                {
                                    "left_signal": right,
                                    "right_signal": left,
                                    "variant_left": right_variant,
                                    "variant_right": left_variant,
                                }
                            )
                            if not has_expected_period_rows(
                                "comparisons",
                                "delta",
                                "period",
                                segment_times[segment_id],
                                boundary_times,
                                **reversed_period_key,
                            ):
                                record_missing(
                                    "comparisons_periods",
                                    signal_left=left,
                                    signal_right=right,
                                    pool_id="common:" + comparison_id,
                                    group=group,
                                    segment_id=segment_id,
                                    horizon=horizon,
                                    metric=metric,
                                )

    return {
        "passed": not missing,
        "reason": None if not missing else "required_signal_variant_segment_outputs_missing",
        "missing_count": len(missing),
        "missing_examples": missing[:25],
        "status": status,
        "table_rows": {name: len(value) for name, value in tables.items()},
        "required_axes": len(axes),
        "combo_variants": list(full_combo),
    }


def _run_native_collection(
    config: Mapping[str, Any], panel: Mapping[str, Any], runnext: bool
) -> Tuple[Any, Any, Any]:
    import backtrader as bt
    from backtrader.brokers import BackBroker
    from backtrader.research import FactorSpec, FactorStrategy
    from backtrader.research.inputs import prealign_bars
    from multi_factor_strategy import CloseMAFactor, KDJFactor, ROCFactor

    class CountingBroker(BackBroker):
        def __init__(self):
            super().__init__()
            self.submit_count = 0
            self.cancel_count = 0

        def submit(self, order):
            self.submit_count += 1
            return super().submit(order)

        def cancel(self, order):
            self.cancel_count += 1
            return super().cancel(order)

    research = _create_research_spec(config, panel)
    indicator_classes = {
        "close_ma": CloseMAFactor,
        "roc": ROCFactor,
        "kdj_j": KDJFactor,
    }
    factors = {}
    for name, definition in config["factors"].items():
        factors[name] = FactorSpec(
            name=name,
            indicator=indicator_classes[name],
            params=dict(definition["params"]),
            panel_line=definition["panel_line"],
            direction=definition["direction"],
            field_bindings={
                field: "feed:target:%s" % field for field in indicator_classes[name].formula_fields
            },
        )
    cerebro = bt.Cerebro(stdstats=False)
    broker = CountingBroker()
    cerebro.setbroker(broker)
    for asset in panel["assets"]:
        aligned = prealign_bars(
            panel["feeds"][asset],
            research,
            asset,
            data_version=config["data"]["data_version"],
        )
        cerebro.adddata(aligned.feed, name=asset)
    cerebro.addstrategy(FactorStrategy, research=research, factors=factors)
    strategies = cerebro.run(runonce=not runnext, preload=True)
    if len(strategies) != 1:
        raise RuntimeError("the native collection did not return exactly one strategy")
    return strategies[0], strategies[0].get_dataset(), broker


def _parse_periods(values: Optional[Sequence[int]], default: Sequence[int]) -> Tuple[int, ...]:
    result = tuple(default if values is None else values)
    if not result or any(type(value) is not int or value <= 0 for value in result):
        raise ValueError("periods must be one or more positive integers")
    if len(set(result)) != len(result):
        raise ValueError("periods must not contain duplicates")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Exit codes: 0 means all mandatory outputs passed (PARTIAL is allowed when "
            "only declared optional diagnostics are absent); 1 means required output "
            "validation failed or the evaluation is UNEVALUABLE; 2 means invalid input, "
            "a missing prerequisite, or a blocked dependency; 3 means interrupted work "
            "or an output I/O failure."
        ),
    )
    parser.add_argument(
        "--output-dir", required=True, help="new output directory; relative to this script"
    )
    parser.add_argument(
        "--dataset", help="saved ResearchDataset directory for offline reevaluation"
    )
    parser.add_argument("--periods", nargs="+", type=int, help="label horizons for this evaluation")
    parser.add_argument(
        "--no-charts", action="store_true", help="write tables without PNG rendering"
    )
    parser.add_argument("--runnext", action="store_true", help="use Backtrader's event-driven loop")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = _load_config()
        periods = _parse_periods(args.periods, config["evaluation"]["periods"])
        output_dir = _resolve_path(args.output_dir)
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir()
        started_at_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _write_json(
            output_dir / "run_manifest.json",
            {
                "schema_version": "iteration45-example-run-v1",
                "example_id": EXAMPLE_ID,
                "status": "RUNNING",
                "exit_code": None,
                "evidence_level": EVIDENCE_LEVEL,
                "acceptance_status": "NOT_CLAIMED",
                "output_dir": str(output_dir),
                "started_at_utc": started_at_utc,
            },
        )
    except (ImportError, RuntimeError) as exc:
        print("BLOCKED: %s" % exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print("OUTPUT_ERROR: %s" % exc, file=sys.stderr)
        return 3
    except (TypeError, ValueError) as exc:
        print("INVALID_INPUT: %s" % exc, file=sys.stderr)
        return 2

    run_record: Dict[str, Any] = {
        "schema_version": "iteration45-example-run-v1",
        "example_id": EXAMPLE_ID,
        "status": "RUNNING",
        "exit_code": None,
        "evidence_level": EVIDENCE_LEVEL,
        "acceptance_status": "NOT_CLAIMED",
        "generator_version": GENERATOR_VERSION,
        "seed": config["data"]["seed"],
        "requested_periods": list(periods),
        "charts_requested": not args.no_charts,
        "mode": "dataset_reevaluation" if args.dataset else "native_cerebro_collection",
        "execution_mode": "runnext"
        if args.runnext and not args.dataset
        else "runonce"
        if not args.runnext and not args.dataset
        else "offline",
        "output_dir": str(output_dir),
        "config_sha256": _sha256_file(CONFIG_PATH),
        "strategy_sha256": _sha256_file(SCRIPT_DIR / "multi_factor_strategy.py"),
        "declared_factors": config["factors"],
        "declared_segments": config["evaluation"]["segments"],
        "declared_combinations": config["evaluation"]["combinations"],
        "declared_comparisons": config["evaluation"]["comparisons"],
        "versions": {"python": sys.version.split()[0]},
        "started_at_utc": started_at_utc,
    }
    _write_json(output_dir / "run_manifest.json", run_record)
    try:
        try:
            if args.dataset:
                from backtrader.research.storage import load_dataset

                dataset_path = _resolve_path(args.dataset)
                dataset = load_dataset(dataset_path)
                panel_summary = _validate_dataset(config, dataset)
                panel_summary["dataset_path"] = str(dataset_path)
                broker_counts = {"submit": 0, "cancel": 0, "observed": False}
            else:
                panel = build_synthetic_panel(config["data"])
                run_record["generator"] = {
                    "version": GENERATOR_VERSION,
                    "data_version": config["data"]["data_version"],
                    "seed": config["data"]["seed"],
                    "asset_count": len(panel["assets"]),
                    "bar_count": panel["bar_count"],
                    "warmup_bars": config["data"]["warmup_bars"],
                    "research_bars": config["data"]["research_bars"],
                    "tail_bars": config["data"]["tail_bars"],
                    "calendar_id": config["data"]["calendar_id"],
                    "frequency": config["data"]["frequency"],
                    "grid_sha256": hashlib.sha256(
                        "\n".join(stamp.isoformat() for stamp in panel["grid"].index).encode(
                            "ascii"
                        )
                    ).hexdigest(),
                    "ohlcv_sha256": panel["ohlcv_sha256"],
                }
                strategy, dataset, broker = _run_native_collection(config, panel, args.runnext)
                broker_counts = {
                    "submit": broker.submit_count,
                    "cancel": broker.cancel_count,
                    "observed": True,
                }
                if (broker.submit_count, broker.cancel_count) != (0, 0):
                    raise RuntimeError("research-only Cerebro run submitted or cancelled an order")
                if len(dataset.grid) != panel["bar_count"] or len(dataset.targets) != len(
                    panel["assets"]
                ):
                    raise RuntimeError(
                        "collected dataset does not preserve the full grid and target set"
                    )
                panel_summary = _validate_dataset(config, dataset)
                dataset_dir = output_dir / config["outputs"]["dataset_directory"]
                dataset.save(dataset_dir)
                panel_summary.update(
                    {
                        "dataset_path": str(dataset_dir),
                        "factor_strategy_type": type(strategy).__name__,
                    }
                )

            eval_spec = _evaluation_spec(config, dataset, periods)
            result = dataset.evaluate(eval_spec)
            result_status_value = getattr(result, "status", None)
            result_status = str(
                getattr(result_status_value, "value", result_status_value) or ""
            ).upper()
            configured_segments = config["evaluation"]["segments"]
            research_times = tuple(
                dataset.grid.index[
                    (dataset.grid.index >= dataset.start) & (dataset.grid.index <= dataset.end)
                ]
            )
            segment_times = {"full": research_times}
            segment_times.update(
                {
                    name: research_times[
                        definition["research_bar_start"] : definition["research_bar_end"] + 1
                    ]
                    for name, definition in configured_segments.items()
                }
            )
            segment_bars = {name: len(values) for name, values in segment_times.items()}
            base_signals = tuple(config["factors"])
            expected_signals = dict.fromkeys(base_signals, ("raw", "oriented", "transformed"))
            combo_names = tuple(config["evaluation"]["combinations"])
            if combo_names != ("equal_weight",):
                raise ValueError("this example requires its single fixed equal_weight combination")
            expected_signals["equal_weight"] = ("composite",)
            comparison_names = tuple(config["evaluation"]["comparisons"])
            if comparison_names != ("all_variants",):
                raise ValueError("this example requires the all_variants common-pool comparison")
            ablation_signals = tuple("equal_weight::without::%s" % name for name in base_signals)
            expected_signals.update(dict.fromkeys(ablation_signals, ("composite",)))
            required = _validate_result(
                result,
                expected_signals,
                periods,
                group=config["data"]["group"],
                segment_bars=segment_bars,
                segment_times=segment_times,
                max_loss=config["evaluation"]["max_loss"],
                asset_count=config["data"]["asset_count"],
                research_times=research_times,
                target_assets=dataset.targets,
                grid_close_times=tuple(dataset.grid.index),
                grid_open_times=tuple(dataset.grid["open_time"]),
                quantiles=config["evaluation"]["quantiles"],
                stability_lags=config["evaluation"]["stability_lags"],
                comparison_id=comparison_names[0],
                base_signals=base_signals,
                required_optional_tables=tuple(
                    name
                    for name in OPTIONAL_EVALUATION_TABLES
                    if name not in config["outputs"].get("optional_evaluation_tables", ())
                ),
                signal_pools=dict.fromkeys(ablation_signals, ("common:" + comparison_names[0],)),
            )
            run_record.update(
                {
                    "evaluation_status": result_status,
                    "required_output_validation": required,
                    "dataset": panel_summary,
                    "broker": broker_counts,
                }
            )
            evaluation_exit_code = _evaluation_exit_code(result_status, required)
            if evaluation_exit_code != 0:
                raise RuntimeError(
                    "required evaluation output validation failed: %s (%s)"
                    % (required["reason"], required.get("missing_examples", []))
                )
            evaluation_dir = output_dir / config["outputs"]["evaluation_directory"]
            result_manifest = getattr(result, "manifest", {}) or {}
            evaluation_id = getattr(result, "evaluation_id", None)
            if evaluation_id is None and hasattr(result_manifest, "get"):
                evaluation_id = result_manifest.get("evaluation_id")
            result.export(evaluation_dir, charts=not args.no_charts)
            exported = _validate_export_output(
                evaluation_dir,
                charts_requested=not args.no_charts,
                expected_status=result_status,
                optional_tables=config["outputs"].get("optional_evaluation_tables", ()),
                expected_evaluation_id=evaluation_id,
            )
            if not exported["passed"]:
                raise RuntimeError("evaluation export validation failed: %s" % exported["reason"])
            run_record.update(
                {
                    "status": "COMPLETED",
                    "exit_code": evaluation_exit_code,
                    "evaluation_status": result_status,
                    "evaluation_id": evaluation_id,
                    "dataset": panel_summary,
                    "broker": broker_counts,
                    "required_output_validation": required,
                    "export_validation": exported,
                    "versions": {
                        "python": sys.version.split()[0],
                        "backtrader": _module_facts("backtrader", "backtrader"),
                        "fincore": _module_facts("fincore", "fincore"),
                    },
                    "artifacts": _artifact_manifest(output_dir),
                    "completed_at_utc": datetime.now(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                }
            )
        except (ImportError, KeyboardInterrupt, OSError) as exc:
            status, exit_code = _failure_result(exc)
            run_record.update(
                {
                    "status": status,
                    "exit_code": exit_code,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
        except Exception as exc:
            status, exit_code = _failure_result(exc)
            error_code = getattr(exc, "code", None)
            run_record.update(
                {
                    "status": status,
                    "exit_code": exit_code,
                    "error_type": type(exc).__name__,
                    "error_code": error_code,
                    "error": str(exc),
                }
            )
        finally:
            run_record.setdefault(
                "finished_at_utc",
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            )
            _write_json(output_dir / "summary.json", run_record)
            _write_json(output_dir / "run_manifest.json", run_record)
    except OSError as exc:
        print("OUTPUT_ERROR: %s" % exc, file=sys.stderr)
        return 3

    print("%s: %s (exit %s)" % (EXAMPLE_ID, run_record["status"], run_record["exit_code"]))
    return int(run_record["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
