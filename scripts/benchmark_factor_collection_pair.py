"""Paired timing of native factor collection and panel/dataset finalization.

Each run uses a fresh interpreter. The example module, config and daily input
panel are prepared before the measured interval; the only measured call is the
example's real ``_run_native_collection(config, panel, runnext)``. Validation
and keyed factor CSV export happen after the timer. This measures collection
plus the returned legacy ResearchDataset or current FactorPanel; it does not
measure report rendering, fincore evaluation, CSV persistence, or full
end-to-end example runtime.

The default 500-symbol run uses one full-input warmup per side/example and
three alternating measured pairs. Explicit ``--symbols 50`` runs remain
DIAGNOSTIC_ONLY. Performance gates are reported independently for 025/026 and
require candidate median collection wall time to be at most half the baseline
median. Process CPU medians and ranges are recorded without a separate gate.
This tool does not replace end-to-end acceptance.

Example::

    /Users/yunjinqi/opt/anaconda3/bin/conda run -n base python \\
        scripts/benchmark_factor_collection_pair.py \\
        --baseline-root /path/to/4ce64007 \\
        --candidate-root /path/to/current-backtrader \\
        --baseline-revision 4ce64007 --data-dir /path/to/tests/datas/a_stocks \\
        --output /tmp/factor-collection-pair
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import statistics
import subprocess
import sys
import time
import traceback
from itertools import zip_longest
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

EXAMPLES = ("025", "026")
EXAMPLE_DIRS = {
    "025": Path("examples/backtest/025_factor_single"),
    "026": Path("examples/backtest/026_factor_multi"),
}
FORMAL_SYMBOL_FLOOR = 500
DIAGNOSTIC_SYMBOLS = 50
EXPECTED_GRID_ROWS = 243
MEASURED_PAIRS = 3
FACTOR_VALUE_TOLERANCE = 1e-12
DIAGNOSTIC_CLASS = "DIAGNOSTIC_ONLY"
FORMAL_CLASS = "FORMAL_COLLECTION_COMPARISON"
_MISSING = object()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_write(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _pair_helpers() -> Any:
    path = Path(__file__).resolve().with_name("benchmark_factor_research_pair.py")
    if not path.is_file():
        raise FileNotFoundError("existing paired benchmark helpers are missing: %s" % path)
    spec = importlib.util.spec_from_file_location("_factor_collection_pair_helpers", path)
    if spec is None or spec.loader is None:
        raise ImportError("could not load paired benchmark helpers from %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _safe_input_path(data_dir: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("input manifest contains unsafe file path: %s" % relative)
    result = (data_dir / path).resolve()
    if not _path_inside(result, data_dir):
        raise ValueError("input file resolves outside data directory: %s" % relative)
    return result


def _path_inside(path: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((str(path.resolve()), str(parent.resolve()))) == str(
            parent.resolve()
        )
    except ValueError:
        return False


def _input_inventory(data_dir: Path, symbols: int) -> Dict[str, Any]:
    metadata = data_dir / "_metadata"
    manifest_path = metadata / "manifest.json"
    calendar_path = metadata / "observed_calendar.csv"
    if not manifest_path.is_file() or not calendar_path.is_file():
        raise FileNotFoundError("data-dir requires manifest.json and observed_calendar.csv")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("output", {}).get("symbols")
    if not isinstance(entries, list) or not entries:
        raise ValueError("input manifest has no output.symbols entries")
    if symbols > len(entries):
        raise ValueError(
            "input manifest has only %d symbols; requested %d" % (len(entries), symbols)
        )
    step = len(entries) / float(symbols)
    selected = [entries[int(index * step)] for index in range(symbols)]
    names = [str(item.get("symbol", "")) for item in selected if isinstance(item, Mapping)]
    if len(names) != symbols or any(not name for name in names) or len(set(names)) != symbols:
        raise ValueError("selected input symbols must be unique non-empty names")
    file_hashes = {}
    for item, name in zip(selected, names):
        if not isinstance(item, Mapping) or not isinstance(item.get("file"), str):
            raise ValueError("selected input entry has no file path: %s" % name)
        path = _safe_input_path(data_dir, item["file"])
        if not path.is_file():
            raise FileNotFoundError("selected input CSV is missing: %s" % path)
        file_hashes[name] = _sha256(path)
    with calendar_path.open("r", encoding="utf-8", newline="") as source:
        calendar_rows = max(0, sum(1 for _ in source) - 1)
    if calendar_rows != EXPECTED_GRID_ROWS:
        raise ValueError(
            "formal collection input requires %d calendar rows; found %d"
            % (EXPECTED_GRID_ROWS, calendar_rows)
        )
    return {
        "data_dir": str(data_dir.resolve()),
        "manifest_sha256": _sha256(manifest_path),
        "calendar_sha256": _sha256(calendar_path),
        "calendar_rows": calendar_rows,
        "requested_symbols": symbols,
        "selected_symbols": names,
        "selected_symbol_file_sha256": file_hashes,
        "selected_symbol_file_map_sha256": _canonical_hash(file_hashes),
    }


def _alternating_order(pair_index: int) -> Tuple[str, str]:
    if pair_index < 1:
        raise ValueError("pair_index is one-based and must be positive")
    return ("baseline", "candidate") if pair_index % 2 else ("candidate", "baseline")


def _timing_summary(values: Sequence[float]) -> Dict[str, Any]:
    if not values:
        return {"count": 0, "median_s": None, "min_s": None, "max_s": None, "range_s": None}
    minimum = min(values)
    maximum = max(values)
    return {
        "count": len(values),
        "median_s": statistics.median(values),
        "min_s": minimum,
        "max_s": maximum,
        "range_s": maximum - minimum,
        "raw_s": list(values),
    }


def _load_example(root: Path, example: str) -> Any:
    example_dir = root / EXAMPLE_DIRS[example]
    path = example_dir / "run.py"
    if not path.is_file():
        raise FileNotFoundError("selected root lacks native example entry: %s" % path)
    for value in (str(root), str(example_dir)):
        if value not in sys.path:
            sys.path.insert(0, value)
    spec = importlib.util.spec_from_file_location("_collection_entry_%s" % example, path)
    if spec is None or spec.loader is None:
        raise ImportError("could not load example entry at %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    required = ("_load_config", "load_daily_panel", "_run_native_collection")
    missing = [name for name in required if not callable(getattr(module, name, None))]
    if missing:
        raise AttributeError("%s lacks native collection API: %s" % (path, missing))
    return module


def _module_origins(root: Path) -> Dict[str, Any]:
    import backtrader
    import backtrader.research

    origins: Dict[str, Any] = {
        "backtrader": str(Path(backtrader.__file__).resolve()),
        "backtrader.research": str(Path(backtrader.research.__file__).resolve()),
    }
    for name in ("backtrader", "backtrader.research"):
        if not _path_inside(Path(origins[name]), root):
            raise ImportError("%s imported outside selected root: %s" % (name, origins[name]))
    spec = importlib.util.find_spec("fincore")
    fincore_origin = None if spec is None else spec.origin
    origins["fincore"] = fincore_origin
    origins["fincore_search_locations"] = (
        []
        if spec is None or spec.submodule_search_locations is None
        else list(spec.submodule_search_locations)
    )
    try:
        origins["fincore_version"] = importlib.metadata.version("fincore")
    except importlib.metadata.PackageNotFoundError:
        origins["fincore_version"] = None
    if fincore_origin and Path(fincore_origin).is_file():
        origins["fincore_source_sha256"] = _sha256(Path(fincore_origin))
    else:
        origins["fincore_source_sha256"] = None
    return origins


def _panel_values(value: Any) -> Tuple[Any, Any, Tuple[str, ...], Tuple[str, ...]]:
    if hasattr(value, "raw_factors"):
        frame = value.raw_factors
        targets = tuple(value.targets)
        factor_names = tuple(value.factor_names)
    else:
        frame = value.factors
        targets = tuple(value.target_order)
        factor_names = tuple(value.factor_order)
    return value, frame, targets, factor_names


def _validate_collection_result(
    *,
    result: Any,
    input_panel: Mapping[str, Any],
    expected_factors: Sequence[str],
    requested_symbols: int,
) -> Tuple[Dict[str, Any], Any]:
    import numpy as np
    import pandas as pd

    panel, factors, targets, factor_names = _panel_values(result)
    input_targets = tuple(input_panel["assets"])
    input_grid = input_panel["grid"]
    output_grid = panel.grid
    if not isinstance(output_grid, pd.DataFrame):
        raise TypeError("returned dataset/panel grid must be a DataFrame")
    if tuple(targets) != input_targets:
        raise ValueError("returned target order differs from loaded panel asset order")
    if tuple(factor_names) != tuple(expected_factors):
        raise ValueError("returned factor order differs from effective config")
    if len(targets) != requested_symbols:
        raise ValueError("returned target count differs from requested symbol count")
    if len(output_grid) != EXPECTED_GRID_ROWS or not output_grid.index.equals(input_grid.index):
        raise ValueError("returned full grid differs from the 243-row loaded input grid")
    if "open_time" not in output_grid or not output_grid["open_time"].equals(
        input_grid["open_time"]
    ):
        raise ValueError("returned full-grid open_time values differ from loaded input")
    study_index = output_grid.index[
        (output_grid.index >= panel.start) & (output_grid.index <= panel.end)
    ]
    expected_start = input_grid.index[int(input_panel["research_start_position"])]
    expected_end = input_grid.index[int(input_panel["research_end_position"])]
    if panel.start != expected_start or panel.end != expected_end:
        raise ValueError("returned research interval differs from configured input interval")
    if len(study_index) != EXPECTED_GRID_ROWS:
        raise ValueError("research interval must cover all 243 expected grid points")
    if not isinstance(factors, pd.DataFrame) or tuple(factors.columns) != tuple(expected_factors):
        raise TypeError("returned factor values must be an ordered DataFrame")
    if not isinstance(factors.index, pd.MultiIndex) or tuple(factors.index.names) != (
        "time",
        "asset",
    ):
        raise ValueError("factor values must be keyed by (time, asset)")
    if not factors.index.is_unique:
        raise ValueError("factor values contain duplicate (time, asset) keys")
    expected_keys = pd.MultiIndex.from_product([study_index, targets], names=("time", "asset"))
    if len(factors) != len(expected_keys) or set(factors.index.tolist()) != set(
        expected_keys.tolist()
    ):
        raise ValueError("factor values do not exactly cover research grid x targets")
    if len(factors) == 0:
        raise ValueError("factor values contain no rows")
    numeric = factors.to_numpy(dtype="float64", copy=False)
    finite = np.isfinite(numeric)
    if np.isinf(numeric).any():
        raise ValueError("factor values contain infinity")
    finite_counts = {
        name: int(finite[:, position].sum()) for position, name in enumerate(expected_factors)
    }
    if any(count == 0 for count in finite_counts.values()):
        raise ValueError("at least one requested factor has no finite values")
    grid_summary = {
        "rows": len(output_grid),
        "start": str(output_grid.index[0]),
        "end": str(output_grid.index[-1]),
        "index_sha256": _canonical_hash([str(value) for value in output_grid.index]),
    }
    target_summary = {
        "count": len(targets),
        "order": list(targets),
        "order_sha256": _canonical_hash(list(targets)),
    }
    factor_summary = {
        "rows": len(factors),
        "factor_order": list(expected_factors),
        "finite_values": finite_counts,
        "finite_total": int(finite.sum()),
    }
    summary = {
        "status": "OK",
        "grid": grid_summary,
        "targets": target_summary,
        "research_interval": {
            "start": str(panel.start),
            "end": str(panel.end),
            "rows": len(study_index),
        },
        "factors": factor_summary,
    }
    return summary, factors


def _write_factor_csv(frame: Any, factor_names: Sequence[str], destination: Path) -> Dict[str, Any]:
    normalized = frame.loc[:, list(factor_names)].sort_index()
    flattened = normalized.reset_index()
    if list(flattened.columns[:2]) != ["time", "asset"]:
        raise ValueError("factor CSV keys must be named time and asset")
    flattened["time"] = flattened["time"].map(
        lambda value: value.isoformat() if hasattr(value, "isoformat") else str(value)
    )
    flattened["asset"] = flattened["asset"].astype(str)
    flattened.to_csv(destination, index=False, float_format="%.17g", na_rep="")
    return {
        "path": str(destination),
        "rows": len(flattened),
        "columns": list(flattened.columns),
        "size_bytes": destination.stat().st_size,
        "sha256": _sha256(destination),
        "keys": ["time", "asset"],
        "written_after_collection_timer": True,
    }


def _worker(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve()
    data_dir = Path(args.data_dir).expanduser().resolve()
    output_dir = Path(args.work_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "worker-result.json"
    result: Dict[str, Any] = {
        "classification": DIAGNOSTIC_CLASS,
        "mode": "native_collection",
        "side": args.side,
        "example": args.example,
        "root": str(root),
        "data_dir": str(data_dir),
        "requested_symbols": args.symbols,
        "runnext": bool(args.runnext),
        "python_executable": sys.executable,
        "collection_timer_scope": (
            "perf_counter and process_time around only the real _run_native_collection(config, panel, runnext) call; includes alignment, Cerebro.run, and legacy get_dataset/current get_panel"
        ),
        "excluded_from_collection_timer": [
            "example module import",
            "config load and data-directory/symbol-limit override",
            "daily panel loading and input hashes",
            "returned dataset/panel validation",
            "keyed factor CSV export",
            "reports and fincore evaluation",
        ],
    }
    error = None
    try:
        if not (root / "backtrader" / "__init__.py").is_file():
            raise ValueError("root is not a Backtrader source root: %s" % root)
        if args.example not in EXAMPLES:
            raise ValueError("example must be 025 or 026")
        inventory = _input_inventory(data_dir, args.symbols)
        module = _load_example(root, args.example)
        config = copy.deepcopy(module._load_config())
        config["data"]["directory"] = str(data_dir)
        config["data"]["max_symbols"] = args.symbols
        config_hash = _canonical_hash(config)
        input_panel = module.load_daily_panel(config["data"])
        loaded_assets = tuple(input_panel.get("assets", ()))
        if loaded_assets != tuple(inventory["selected_symbols"]):
            raise ValueError(
                "example data loader selected a different asset order than the manifest"
            )
        if len(loaded_assets) != args.symbols:
            raise ValueError(
                "data loader returned %d symbols for a %d-symbol request"
                % (len(loaded_assets), args.symbols)
            )
        if len(input_panel.get("grid", ())) != EXPECTED_GRID_ROWS:
            raise ValueError("loaded input panel does not contain exactly 243 grid rows")
        configured_factor_names = (
            [str(config["factor"]["name"])]
            if args.example == "025"
            else [str(name) for name in config["factors"]]
        )
        result.update(
            {
                "input_manifest": inventory,
                "effective_config_sha256": config_hash,
                "effective_config": config,
                "loaded_panel": {
                    "symbols": len(loaded_assets),
                    "asset_order": list(loaded_assets),
                    "grid_rows": len(input_panel["grid"]),
                    "grid_start": str(input_panel["grid"].index[0]),
                    "grid_end": str(input_panel["grid"].index[-1]),
                    "research_start_position": input_panel["research_start_position"],
                    "research_end_position": input_panel["research_end_position"],
                },
            }
        )

        wall_started = time.perf_counter()
        cpu_started = time.process_time()
        strategy, dataset_or_panel, broker = module._run_native_collection(
            config, input_panel, bool(args.runnext)
        )
        collection_cpu_s = time.process_time() - cpu_started
        collection_wall_s = time.perf_counter() - wall_started
        result["collection_and_panel_timing"] = {
            "wall_s": collection_wall_s,
            "process_cpu_s": collection_cpu_s,
            "nested_policy": "single enclosing _run_native_collection duration; no nested stage durations are added",
        }
        result["strategy_type"] = "%s.%s" % (type(strategy).__module__, type(strategy).__name__)
        result["broker_orders"] = {
            "submit": getattr(broker, "submit_count", None),
            "cancel": getattr(broker, "cancel_count", None),
        }
        if result["broker_orders"] != {"submit": 0, "cancel": 0}:
            raise ValueError("collection example performed broker orders or lacked order counters")
        shape_contract, factor_frame = _validate_collection_result(
            result=dataset_or_panel,
            input_panel=input_panel,
            expected_factors=configured_factor_names,
            requested_symbols=args.symbols,
        )
        result["returned_panel_contract"] = shape_contract
        result["factor_values_csv"] = _write_factor_csv(
            factor_frame, configured_factor_names, output_dir / "factor_values_keyed.csv"
        )
        origins = _module_origins(root)
        example_path = root / EXAMPLE_DIRS[args.example] / "run.py"
        result["module_origins"] = origins
        result["source_hashes"] = {
            "example_run_py": _sha256(example_path),
            "backtrader_init": _sha256(Path(origins["backtrader"])),
            "research_init": _sha256(Path(origins["backtrader.research"])),
            "fincore": origins["fincore_source_sha256"],
        }
        result["status"] = "OK"
    except Exception:
        error = traceback.format_exc()
        result["status"] = "FAILED"
        result["error"] = error
    _json_write(result_path, result)
    print(json.dumps({"status": result["status"], "result": str(result_path)}))
    return 0 if result["status"] == "OK" else 2


def _compare_factor_csvs(left_path: Path, right_path: Path) -> Dict[str, Any]:
    with left_path.open("r", encoding="utf-8", newline="") as left_source, right_path.open(
        "r", encoding="utf-8", newline=""
    ) as right_source:
        left_reader = csv.DictReader(left_source)
        right_reader = csv.DictReader(right_source)
        left_fields = list(left_reader.fieldnames or ())
        right_fields = list(right_reader.fieldnames or ())
        columns_match = left_fields == right_fields and left_fields[:2] == ["time", "asset"]
        factor_names = left_fields[2:] if columns_match else []
        key_mismatches = 0
        finite_mask_mismatches = 0
        value_mismatches = 0
        invalid_values = 0
        compared_values = 0
        max_abs_diff = 0.0
        rows = 0
        extra_rows = 0
        for left_row, right_row in zip_longest(left_reader, right_reader, fillvalue=_MISSING):
            if left_row is _MISSING or right_row is _MISSING:
                extra_rows += 1
                continue
            rows += 1
            if (left_row.get("time"), left_row.get("asset")) != (
                right_row.get("time"),
                right_row.get("asset"),
            ):
                key_mismatches += 1
            for name in factor_names:
                left_value, left_invalid = _parse_factor_cell(left_row.get(name, ""))
                right_value, right_invalid = _parse_factor_cell(right_row.get(name, ""))
                invalid_values += int(left_invalid) + int(right_invalid)
                if (left_value is None) != (right_value is None):
                    finite_mask_mismatches += 1
                elif left_value is not None and right_value is not None:
                    compared_values += 1
                    difference = abs(left_value - right_value)
                    max_abs_diff = max(max_abs_diff, difference)
                    if difference > FACTOR_VALUE_TOLERANCE:
                        value_mismatches += 1
    status = (
        "OK"
        if columns_match
        and rows > 0
        and extra_rows == 0
        and key_mismatches == 0
        and finite_mask_mismatches == 0
        and invalid_values == 0
        and value_mismatches == 0
        and compared_values > 0
        else "FAILED"
    )
    return {
        "status": status,
        "left": str(left_path),
        "right": str(right_path),
        "factor_names": factor_names,
        "columns_match": columns_match,
        "rows_compared": rows,
        "extra_rows": extra_rows,
        "key_mismatches": key_mismatches,
        "finite_mask_mismatches": finite_mask_mismatches,
        "finite_values_compared": compared_values,
        "invalid_values": invalid_values,
        "max_abs_diff": max_abs_diff,
        "absolute_tolerance": FACTOR_VALUE_TOLERANCE,
        "value_mismatches": value_mismatches,
        "comparison_key": ["time", "asset"],
    }


def _parse_factor_cell(value: Any) -> Tuple[Optional[float], bool]:
    if value is None or value == "":
        return None, False
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None, True
    if math.isnan(parsed):
        return None, False
    if not math.isfinite(parsed):
        return None, True
    return parsed, False


def _worker_command(
    args: argparse.Namespace,
    root: Path,
    side: str,
    example: str,
    work_dir: Path,
) -> List[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--_worker",
        "--root",
        str(root),
        "--side",
        side,
        "--example",
        example,
        "--data-dir",
        str(Path(args.data_dir).expanduser().resolve()),
        "--symbols",
        str(args.symbols),
        "--work-dir",
        str(work_dir),
    ]
    if args.runnext:
        command.append("--runnext")
    return command


def _run_worker(
    args: argparse.Namespace,
    root: Path,
    side: str,
    example: str,
    kind: str,
    group: Optional[int],
    run_dir: Path,
) -> Dict[str, Any]:
    command = _worker_command(args, root, side, example, run_dir)
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONPATH"] = str(root.resolve())
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=str(root),
        env=environment,
        capture_output=True,
        text=True,
    )
    worker_total_wall_s = time.perf_counter() - started
    result_path = run_dir / "worker-result.json"
    if result_path.is_file():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            result = {"status": "FAILED", "error": "invalid worker result: %s" % exc}
    else:
        result = {"status": "FAILED", "error": "worker result file was not written"}
    result.update(
        {
            "kind": kind,
            "group": group,
            "worker_command": command,
            "worker_returncode": completed.returncode,
            "worker_total_wall_s_excludes_collection_scope": worker_total_wall_s,
            "worker_stdout_tail": completed.stdout[-2000:],
            "worker_stderr_tail": completed.stderr[-2000:],
            "worker_result_path": str(result_path),
        }
    )
    return result


def _check_worker_provenance(
    result: Dict[str, Any],
    *,
    side_metadata: Mapping[str, Any],
    example: str,
    input_manifest: Mapping[str, Any],
) -> Dict[str, Any]:
    probe = side_metadata.get("module_probe", {})
    expected_modules = probe.get("modules", {}) if isinstance(probe, Mapping) else {}
    actual_modules = result.get("module_origins", {})
    config_hashes = side_metadata.get("effective_config_sha256", {})
    expected_config_hash = (
        config_hashes.get(example) if isinstance(config_hashes, Mapping) else None
    )
    actual_config_hash = result.get("effective_config_sha256")
    input_hashes_present = (
        isinstance(result.get("input_manifest"), Mapping)
        and bool(result["input_manifest"].get("manifest_sha256"))
        and bool(result["input_manifest"].get("calendar_sha256"))
        and bool(result["input_manifest"].get("selected_symbol_file_sha256"))
    )
    checks = {
        "input_hashes_match_parent_inventory": input_hashes_present
        and result.get("input_manifest") == input_manifest,
        "effective_config_matches_preflight": isinstance(expected_config_hash, str)
        and len(expected_config_hash) == 64
        and isinstance(actual_config_hash, str)
        and actual_config_hash == expected_config_hash,
        "backtrader_origin_matches_probe": isinstance(actual_modules, Mapping)
        and isinstance(expected_modules, Mapping)
        and bool(actual_modules.get("backtrader"))
        and actual_modules.get("backtrader") == expected_modules.get("backtrader"),
        "research_origin_matches_probe": isinstance(actual_modules, Mapping)
        and isinstance(expected_modules, Mapping)
        and bool(actual_modules.get("backtrader.research"))
        and actual_modules.get("backtrader.research") == expected_modules.get("research"),
        "fincore_origin_matches_probe": isinstance(actual_modules, Mapping)
        and isinstance(expected_modules, Mapping)
        and "fincore" in actual_modules
        and "fincore" in expected_modules
        and actual_modules.get("fincore") == expected_modules.get("fincore"),
    }
    errors = [name for name, passed in checks.items() if not passed]
    result["worker_provenance_checks"] = checks
    if errors:
        result["status"] = "FAILED"
        result["worker_provenance_errors"] = errors
    return result


def _median_gate(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for metric in ("wall_s", "process_cpu_s"):
        by_side: Dict[str, List[float]] = {"baseline": [], "candidate": []}
        for record in records:
            timing = record.get("collection_and_panel_timing", {})
            side = record.get("side")
            value = timing.get(metric) if isinstance(timing, Mapping) else None
            if side in by_side and isinstance(value, (int, float)) and math.isfinite(value):
                by_side[side].append(float(value))
        baseline_stats = _timing_summary(by_side["baseline"])
        candidate_stats = _timing_summary(by_side["candidate"])
        baseline_median = baseline_stats["median_s"]
        candidate_median = candidate_stats["median_s"]
        ratio = (
            candidate_median / baseline_median
            if baseline_median and candidate_median is not None
            else None
        )
        result[metric] = {
            "baseline": baseline_stats,
            "candidate": candidate_stats,
            "candidate_over_baseline_median": ratio,
            "gate_applied": metric == "wall_s",
            "median_50_percent_gate": (
                ratio is not None and ratio <= 0.5 if metric == "wall_s" else None
            ),
        }
    result["pass"] = bool(result["wall_s"]["median_50_percent_gate"])
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root")
    parser.add_argument("--candidate-root")
    parser.add_argument("--baseline-revision", help="source revision for an archive without .git")
    parser.add_argument("--candidate-revision", help="source revision for an archive without .git")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output")
    parser.add_argument("--symbols", type=int, default=FORMAL_SYMBOL_FLOOR)
    parser.add_argument("--runnext", action="store_true", help="diagnostic event-driven collection")
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--root", help=argparse.SUPPRESS)
    parser.add_argument("--side", choices=("baseline", "candidate"), help=argparse.SUPPRESS)
    parser.add_argument("--example", choices=EXAMPLES, help=argparse.SUPPRESS)
    parser.add_argument("--work-dir", help=argparse.SUPPRESS)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args._worker:
        if not all((args.root, args.side, args.example, args.data_dir, args.work_dir)):
            parser.error("worker mode requires root, side, example, data-dir, and work-dir")
        return _worker(args)

    if not args.baseline_root or not args.candidate_root or not args.output:
        parser.error("parent mode requires baseline-root, candidate-root, and output")

    output = Path(args.output).expanduser().resolve()
    payload: Dict[str, Any] = {
        "schema_version": "factor-collection-paired-v1",
        "classification": DIAGNOSTIC_CLASS,
        "status": "FAILED",
        "command": list(sys.argv if argv is None else [sys.argv[0], *argv]),
        "parameters": {
            "examples": list(EXAMPLES),
            "symbols": args.symbols,
            "formal_symbol_floor": FORMAL_SYMBOL_FLOOR,
            "diagnostic_symbol_profile": DIAGNOSTIC_SYMBOLS,
            "measured_pairs_per_example": MEASURED_PAIRS,
            "warmups_per_side_example": 1,
            "runnext": args.runnext,
            "python_executable": sys.executable,
            "performance_gate": "per example, candidate median collection wall <= 0.50 x baseline median; process CPU is descriptive",
            "end_to_end_acceptance": False,
        },
        "harness_source": {
            "path": str(Path(__file__).resolve()),
            "sha256": _sha256(Path(__file__).resolve()),
        },
        "runs": [],
    }
    output_created = False
    try:
        if args.symbols != DIAGNOSTIC_SYMBOLS and args.symbols < FORMAL_SYMBOL_FLOOR:
            raise ValueError(
                "use the explicit 50-symbol diagnostic profile or request at least 500 symbols"
            )
        if args.symbols < 1:
            raise ValueError("--symbols must be positive")
        if args.runnext and args.symbols >= FORMAL_SYMBOL_FLOOR:
            payload["parameters"]["formal_eligible"] = False
            payload["parameters"]["formal_ineligibility_reason"] = "--runnext is diagnostic only"
        if output.exists():
            raise FileExistsError("output directory already exists: %s" % output)
        output.mkdir(parents=True)
        output_created = True
        roots = {
            "baseline": Path(args.baseline_root).expanduser().resolve(),
            "candidate": Path(args.candidate_root).expanduser().resolve(),
        }
        data_dir = Path(args.data_dir).expanduser().resolve()
        input_manifest = _input_inventory(data_dir, args.symbols)
        payload["input_manifest"] = input_manifest
        helpers = _pair_helpers()
        execution_environment = helpers._dependency_snapshot()
        payload["execution_environment"] = execution_environment
        payload["execution_environment_sha256"] = _canonical_hash(execution_environment)
        payload["pair_runner_helper_sha256"] = _sha256(
            Path(__file__).resolve().with_name("benchmark_factor_research_pair.py")
        )
        sides: Dict[str, Dict[str, Any]] = {}
        for side, root in roots.items():
            if not (root / "backtrader" / "__init__.py").is_file():
                raise ValueError("%s is not a Backtrader root: %s" % (side, root))
            source_hashes = helpers._source_manifest(root)
            git_head = helpers._git_head(root)
            declared_revision = getattr(args, "%s_revision" % side)
            revision = git_head or declared_revision
            if not revision:
                raise ValueError("%s archive needs --%s-revision" % (side, side))
            module_probe = helpers._probe_modules(root)
            if module_probe.get("returncode") != 0 or "modules" not in module_probe:
                raise RuntimeError("%s selected-root module probe failed" % side)
            modules = module_probe["modules"]
            for name in ("backtrader", "research"):
                if not helpers._path_inside(Path(modules[name]), root):
                    raise RuntimeError("%s %s module resolves outside selected root" % (side, name))
            configs = {
                example: helpers._effective_config(root, example, data_dir, args.symbols)
                for example in EXAMPLES
            }
            sides[side] = {
                "root": str(root),
                "git_head": git_head,
                "source_revision": revision,
                "revision_method": "git" if git_head else "explicit_cli",
                "source_hashes": source_hashes,
                "source_manifest_sha256": _canonical_hash(source_hashes),
                "git_status": helpers._git_status(root),
                "git_status_sha256": _canonical_hash(helpers._git_status(root)),
                "module_probe": module_probe,
                "effective_configs": configs,
                "effective_config_sha256": {
                    example: _canonical_hash(configs[example]) for example in EXAMPLES
                },
                "dependency_declaration_sha256": {
                    path: digest
                    for path, digest in source_hashes.items()
                    if path.startswith("requirements")
                    or path
                    in {
                        "setup.py",
                        "pyproject.toml",
                        "setup.cfg",
                        "Pipfile.lock",
                        "poetry.lock",
                        "uv.lock",
                        "conda-lock.yml",
                        "environment.yml",
                    }
                },
            }
        payload["sides"] = sides
        config_differences = {
            example: helpers._config_differences(
                sides["baseline"]["effective_configs"][example],
                sides["candidate"]["effective_configs"][example],
            )
            for example in EXAMPLES
        }
        payload["effective_config_comparison"] = {
            "differences": config_differences,
            "all_equal": not any(config_differences.values()),
        }
        if any(config_differences.values()):
            raise ValueError("025/026 effective configurations must be identical")
        payload["timer_contract"] = {
            "measured_function": "example.run._run_native_collection(config, loaded_panel, runnext)",
            "phase_name": "native_collection_and_panel_return",
            "includes": [
                "research/factor spec assembly",
                "feed alignment",
                "Cerebro.run",
                "legacy get_dataset or current get_panel finalization",
            ],
            "excludes": [
                "module/config/input loading",
                "post-run dataset/panel validation",
                "factor CSV export/parity",
                "reports",
                "fincore evaluation",
            ],
            "nested_stage_policy": "only the enclosing native collection duration is measured; nested work is not added",
        }
        payload["output_contract"] = {
            "factor_csv": "each fresh run writes factor_values_keyed.csv after the timer with time/asset keys",
            "legacy_new_api_difference": "baseline returns ResearchDataset via get_dataset; candidate returns FactorPanel via get_panel; shared output purpose is keyed factor values, schemas remain different",
            "end_to_end_boundary": "collection/panel timing does not establish report/evaluation/full-example performance acceptance",
        }

        # Same-input warmup once per side and example, in alternating order.
        for example_index, example in enumerate(EXAMPLES, start=1):
            for side in _alternating_order(example_index):
                run_dir = output / "runs" / example / "warmup" / side
                run_dir.mkdir(parents=True)
                record = _run_worker(args, roots[side], side, example, "warmup", None, run_dir)
                record = _check_worker_provenance(
                    record,
                    side_metadata=sides[side],
                    example=example,
                    input_manifest=input_manifest,
                )
                payload["runs"].append(record)
                if record.get("status") != "OK" or record.get("worker_returncode") != 0:
                    raise RuntimeError("%s %s warmup validation failed" % (side, example))

        parity = {}
        for pair in range(1, MEASURED_PAIRS + 1):
            for example in EXAMPLES:
                pair_records = {}
                for side in _alternating_order(pair):
                    run_dir = output / "runs" / example / ("pair-%02d" % pair) / side
                    run_dir.mkdir(parents=True)
                    record = _run_worker(
                        args, roots[side], side, example, "measured", pair, run_dir
                    )
                    record = _check_worker_provenance(
                        record,
                        side_metadata=sides[side],
                        example=example,
                        input_manifest=input_manifest,
                    )
                    payload["runs"].append(record)
                    pair_records[side] = record
                    if record.get("status") != "OK" or record.get("worker_returncode") != 0:
                        raise RuntimeError(
                            "%s %s pair %d validation failed" % (side, example, pair)
                        )
                parity_key = "%s-pair-%02d" % (example, pair)
                parity[parity_key] = _compare_factor_csvs(
                    Path(pair_records["baseline"]["factor_values_csv"]["path"]),
                    Path(pair_records["candidate"]["factor_values_csv"]["path"]),
                )
                if parity[parity_key]["status"] != "OK":
                    raise RuntimeError("keyed factor parity failed for %s" % parity_key)
        payload["measured_factor_parity"] = parity

        hashes_after = {side: helpers._source_manifest(root) for side, root in roots.items()}
        payload["source_hashes_after"] = hashes_after
        drift = {
            side: {
                name: [digest, hashes_after[side].get(name)]
                for name, digest in sides[side]["source_hashes"].items()
                if hashes_after[side].get(name) != digest
            }
            for side in roots
        }
        payload["source_hash_drift"] = drift
        if any(drift.values()):
            raise RuntimeError("source files changed during native-collection timing")

        performance = {}
        for example in EXAMPLES:
            records = [
                record
                for record in payload["runs"]
                if record.get("kind") == "measured" and record.get("example") == example
            ]
            performance[example] = _median_gate(records)
        payload["performance_by_example"] = performance
        structural_valid = all(
            record.get("status") == "OK" and record.get("worker_returncode") == 0
            for record in payload["runs"]
        ) and all(item.get("status") == "OK" for item in parity.values())
        formal_eligible = args.symbols >= FORMAL_SYMBOL_FLOOR and not args.runnext
        payload["sample_scope"] = {
            "requested_symbols": args.symbols,
            "formal_symbol_floor": FORMAL_SYMBOL_FLOOR,
            "formal_eligible": formal_eligible,
            "classification": (FORMAL_CLASS if formal_eligible else DIAGNOSTIC_CLASS),
        }
        payload["classification"] = FORMAL_CLASS if formal_eligible else DIAGNOSTIC_CLASS
        if not structural_valid:
            payload["status"] = "FAILED"
        elif not formal_eligible:
            payload["status"] = DIAGNOSTIC_CLASS
        elif all(performance[example]["pass"] for example in EXAMPLES):
            payload["status"] = "PASS_COLLECTION_GATE"
        else:
            payload["status"] = "FAIL_COLLECTION_GATE"
    except Exception as exc:
        payload["error"] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        if output_created:
            _json_write(output / "benchmark.json", payload)
            print("results: %s" % (output / "benchmark.json"))
    return 0 if payload["status"] in ("PASS_COLLECTION_GATE", DIAGNOSTIC_CLASS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
