#!/usr/bin/env python
"""Attribute factor-research performance to the float64 kernel and fincore report reuse.

Examples (run with the repository's Anaconda environment)::

    conda run -n base python scripts/benchmark_factor_research_attribution.py \
        --mode kernel --output /tmp/alpha-attribution-kernel
    conda run -n base python scripts/benchmark_factor_research_attribution.py \
        --mode reports --output /tmp/alpha-attribution-reports

``--smoke`` runs one alternating pair after warmups and marks performance as
not evaluated. The default comparison uses one warmup and three alternating
fresh-process groups. Report mode exports one immutable set of current factor
and price frames, then feeds those exact CSV bytes to git-archived fincore
5399498 and the selected candidate ref (default: the fincore checkout's HEAD).
No performance claim is made by this harness itself.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_SCRIPT = REPO_ROOT / "scripts" / "benchmark_factor_research.py"
EXAMPLES = ("025", "026", "027")
EXAMPLE_DIRS = {
    "025": REPO_ROOT / "examples" / "backtest" / "025_factor_single",
    "026": REPO_ROOT / "examples" / "backtest" / "026_factor_multi",
    "027": REPO_ROOT / "examples" / "backtest" / "027_alpha003_panel_acceptance",
}
KERNEL_BASELINE_REVISION = "4ce64007"
FINCORE_BASELINE_REVISION = "5399498"
FINCORE_ARCHIVE_PATHS = ("fincore", "pyproject.toml")
KERNEL_CLASSES = ("RollingCovariance", "RollingCorrelation")
KERNEL_TARGET_REDUCTION = 0.20
REPORT_TARGET_REDUCTION = 0.25
FACTOR_ABS_TOL = 1e-12
FACTOR_REL_TOL = 1e-10


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return _sha256_bytes(payload)


def _git_text(repo: Path, revision: str, relative_path: str) -> str:
    completed = subprocess.run(
        ["git", "show", "%s:%s" % (revision, relative_path)],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise RuntimeError(
            "cannot read %s:%s: %s" % (revision, relative_path, completed.stderr.strip())
        )
    return completed.stdout


def _kernel_method_sources(source: str) -> Dict[str, str]:
    """Extract only the two rolling pair evaluators from an operators source."""
    tree = ast.parse(source)
    result: Dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name not in KERNEL_CLASSES:
            continue
        methods = [
            item
            for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == "_evaluate"
        ]
        if len(methods) != 1:
            raise ValueError("%s must define exactly one _evaluate" % node.name)
        method_source = ast.get_source_segment(source, methods[0])
        if not method_source:
            raise ValueError("could not recover %s._evaluate source" % node.name)
        result[node.name] = textwrap.dedent(method_source)
    if set(result) != set(KERNEL_CLASSES):
        raise ValueError("operator source is missing a rolling covariance/correlation kernel")
    return result


def _kernel_hashes(source: str) -> Dict[str, str]:
    return {
        name: _sha256_bytes(method.encode("utf-8"))
        for name, method in _kernel_method_sources(source).items()
    }


def _install_legacy_kernel(operator_module: Any, source: str) -> Dict[str, str]:
    """Install just two historical methods in this worker process."""
    methods = _kernel_method_sources(source)
    import ast as ast_module
    from decimal import Decimal, localcontext
    from fractions import Fraction

    hashes = {}
    for class_name, method_source in methods.items():
        parsed = ast_module.parse(method_source)
        function = next(node for node in parsed.body if isinstance(node, ast_module.FunctionDef))
        namespace = dict(operator_module.__dict__)
        namespace.update({"Decimal": Decimal, "Fraction": Fraction, "localcontext": localcontext})
        exec(
            compile(
                ast_module.Module(body=[function], type_ignores=[]), "<git-archive-kernel>", "exec"
            ),
            namespace,
        )
        setattr(getattr(operator_module, class_name), "_evaluate", namespace["_evaluate"])
        hashes[class_name] = _sha256_bytes(method_source.encode("utf-8"))
    return hashes


def _alternating_order(group: int) -> Tuple[str, str]:
    return ("old", "new") if group % 2 == 0 else ("new", "old")


def _effective_groups(groups: int, smoke: bool) -> int:
    if smoke:
        return 1
    if groups < 3:
        raise ValueError("non-smoke attribution requires at least 3 measured groups")
    return groups


def _validate_symbol_count(requested: int, actual: int) -> None:
    if int(requested) != int(actual):
        raise ValueError(
            "requested %d symbols but the loaded panel contains %d" % (int(requested), int(actual))
        )


def _read_factor_csv(path: Path) -> Tuple[Any, Dict[str, Any]]:
    import numpy as np
    import pandas as pd

    frame = pd.read_csv(
        path,
        dtype={"time": "string", "asset": "string", "factor": "string"},
        float_precision="round_trip",
    )
    required = {"time", "asset", "factor", "value"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError("factor CSV is missing columns: %s" % sorted(missing))
    if frame.empty:
        raise ValueError("factor CSV is empty: %s" % path)
    keys = ["time", "asset", "factor"]
    if frame[keys].isna().any().any():
        raise ValueError("factor CSV contains null time/asset/factor keys: %s" % path)
    if frame.duplicated(keys).any():
        raise ValueError("factor CSV contains duplicate time/asset/factor keys: %s" % path)
    values = frame["value"].to_numpy(dtype="float64", copy=False)
    if np.isinf(values).any():
        raise ValueError("factor CSV contains infinite values: %s" % path)
    by_factor: Dict[str, Any] = {}
    for factor_name, rows in frame.groupby("factor", sort=True, dropna=False):
        factor_values = rows["value"].to_numpy(dtype="float64", copy=False)
        finite_count = int(np.isfinite(factor_values).sum())
        if finite_count <= 0:
            raise ValueError("factor %s has no finite output cells in %s" % (factor_name, path))
        by_factor[str(factor_name)] = {
            "rows": int(len(rows)),
            "finite_count": finite_count,
            "nan_count": int(np.isnan(factor_values).sum()),
        }
    summary = {
        "path": str(path.resolve()),
        "sha256": _sha256_file(path),
        "rows": int(len(frame)),
        "assets": sorted(str(value) for value in frame["asset"].drop_duplicates()),
        "factors": by_factor,
    }
    return frame, summary


def _factor_csv_summary(path: Path) -> Dict[str, Any]:
    return _read_factor_csv(path)[1]


def _compare_factor_csvs(old_path: Path, new_path: Path) -> Dict[str, Any]:
    import numpy as np

    old, old_summary = _read_factor_csv(old_path)
    new, new_summary = _read_factor_csv(new_path)
    keys = ["time", "asset", "factor"]
    merged = old.merge(
        new,
        on=keys,
        how="outer",
        sort=True,
        validate="one_to_one",
        indicator=True,
        suffixes=("_old", "_new"),
    )
    keys_match = bool(merged["_merge"].eq("both").all())
    both = merged.loc[merged["_merge"] == "both"].copy()
    old_values = both["value_old"].to_numpy(dtype="float64", copy=False)
    new_values = both["value_new"].to_numpy(dtype="float64", copy=False)
    old_nan = np.isnan(old_values)
    new_nan = np.isnan(new_values)
    nan_mask_match = bool(np.array_equal(old_nan, new_nan))
    finite_pairs = np.isfinite(old_values) & np.isfinite(new_values)
    deltas = np.abs(new_values[finite_pairs] - old_values[finite_pairs])
    limits = FACTOR_ABS_TOL + FACTOR_REL_TOL * np.abs(old_values[finite_pairs])
    within_tolerance = bool(np.all(deltas <= limits)) if len(deltas) else False

    factor_records: Dict[str, Any] = {}
    factor_names = sorted(set(old_summary["factors"]) | set(new_summary["factors"]))
    for name in factor_names:
        rows = both.loc[both["factor"] == name]
        left = rows["value_old"].to_numpy(dtype="float64", copy=False)
        right = rows["value_new"].to_numpy(dtype="float64", copy=False)
        common_finite = np.isfinite(left) & np.isfinite(right)
        error = np.abs(right[common_finite] - left[common_finite])
        allowed = FACTOR_ABS_TOL + FACTOR_REL_TOL * np.abs(left[common_finite])
        factor_records[name] = {
            "common_key_rows": int(len(rows)),
            "finite_pairs": int(common_finite.sum()),
            "nan_mask_match": bool(np.array_equal(np.isnan(left), np.isnan(right))),
            "max_abs_error": float(error.max()) if len(error) else None,
            "within_tolerance": bool(np.all(error <= allowed)) if len(error) else False,
        }
    asset_records: Dict[str, Any] = {}
    for asset in sorted(set(old_summary["assets"]) | set(new_summary["assets"])):
        rows = merged.loc[merged["asset"] == asset]
        shared_rows = rows.loc[rows["_merge"] == "both"]
        left = shared_rows["value_old"].to_numpy(dtype="float64", copy=False)
        right = shared_rows["value_new"].to_numpy(dtype="float64", copy=False)
        common_finite = np.isfinite(left) & np.isfinite(right)
        error = np.abs(right[common_finite] - left[common_finite])
        allowed = FACTOR_ABS_TOL + FACTOR_REL_TOL * np.abs(left[common_finite])
        asset_keys_match = not bool((rows["_merge"] != "both").any())
        asset_nan_mask_match = bool(np.array_equal(np.isnan(left), np.isnan(right)))
        asset_records[asset] = {
            "common_key_rows": int(len(shared_rows)),
            "old_only_rows": int((rows["_merge"] == "left_only").sum()),
            "new_only_rows": int((rows["_merge"] == "right_only").sum()),
            "keys_match": asset_keys_match,
            "finite_pairs": int(common_finite.sum()),
            "nan_mask_match": asset_nan_mask_match,
            "max_abs_error": float(error.max()) if len(error) else None,
            "within_tolerance": bool(
                asset_keys_match
                and asset_nan_mask_match
                and (bool(np.all(error <= allowed)) if len(error) else True)
            ),
        }
    return {
        "matches": bool(
            keys_match
            and nan_mask_match
            and within_tolerance
            and set(old_summary["factors"]) == set(new_summary["factors"])
            and all(item["within_tolerance"] for item in asset_records.values())
        ),
        "keys_match": keys_match,
        "nan_mask_match": nan_mask_match,
        "within_tolerance": within_tolerance,
        "tolerance": {"absolute": FACTOR_ABS_TOL, "relative": FACTOR_REL_TOL},
        "common_key_rows": int(len(both)),
        "old_only_rows": int((merged["_merge"] == "left_only").sum()),
        "new_only_rows": int((merged["_merge"] == "right_only").sum()),
        "finite_pairs": int(finite_pairs.sum()),
        "max_abs_error": float(deltas.max()) if len(deltas) else None,
        "assets": sorted(set(old_summary["assets"]) | set(new_summary["assets"])),
        "per_asset": asset_records,
        "old_factor_csv_sha256": old_summary["sha256"],
        "new_factor_csv_sha256": new_summary["sha256"],
        "per_factor": factor_records,
    }


def _frame_source_hash(panel: Mapping[str, Any]) -> str:
    import pandas as pd

    digest = hashlib.sha256()
    grid = panel["grid"]
    digest.update(grid.index.asi8.tobytes())
    digest.update(pd.util.hash_pandas_object(grid, index=True).values.tobytes())
    for asset in panel["assets"]:
        frame = panel["feeds"][asset]
        digest.update(str(asset).encode("utf-8"))
        digest.update(frame.index.asi8.tobytes())
        digest.update(frame.to_numpy(dtype="float64", copy=False).tobytes(order="C"))
        digest.update("\0".join(str(name) for name in frame.columns).encode("utf-8"))
    return digest.hexdigest()


def _kernel_worker(
    *, variant: str, symbols: int, data_dir: Optional[str], output: Path, operator_source: Path
) -> Dict[str, Any]:
    import benchmark_factor_research as benchmark
    import backtrader
    import backtrader.research.operators as operators

    source_path = REPO_ROOT / "backtrader" / "research" / "operators.py"
    source_text = source_path.read_text(encoding="utf-8")
    current_hashes = _kernel_hashes(source_text)
    patched_hashes: Dict[str, str] = {}
    before = {name: getattr(getattr(operators, name), "_evaluate") for name in KERNEL_CLASSES}
    if variant == "old":
        patched_hashes = _install_legacy_kernel(
            operators, operator_source.read_text(encoding="utf-8")
        )
    changed = [
        name
        for name in KERNEL_CLASSES
        if getattr(getattr(operators, name), "_evaluate") is not before[name]
    ]
    expected_changed = list(KERNEL_CLASSES) if variant == "old" else []
    if changed != expected_changed:
        raise RuntimeError("unexpected kernel patch scope: %r" % changed)

    module = benchmark._load_module("027")
    config = dict(module._load_config())
    config["data"] = dict(config["data"])
    config["data"]["max_symbols"] = int(symbols)
    if data_dir:
        config["data"]["directory"] = str(Path(data_dir).expanduser().resolve())
    panel = module.load_daily_panel(config["data"])
    actual_symbols = len(panel["assets"])
    _validate_symbol_count(symbols, actual_symbols)
    input_hash = _frame_source_hash(panel)
    stages = dict.fromkeys(benchmark.STAGE_NAMES)
    csv_dir = output / "panel"
    artifacts: Dict[str, Any] = {"report_dir": str(output), "csv_dir": str(csv_dir)}
    resident: Dict[str, int] = {}
    states = benchmark._stage_states(
        SimpleNamespace(csv=False, report=False, evaluate=False), "027"
    )
    started = time.perf_counter()
    cpu_started = time.process_time()
    benchmark._run_panel(
        "027",
        config,
        panel,
        stages,
        artifacts,
        runnext=True,
        # CSV export runs after the timed Cerebro stage and supplies final factor
        # values for the paired old/new kernel attribution check.
        write_csv=True,
        report=False,
        evaluate=False,
        resident=resident,
        stage_states=states,
        module=module,
    )
    process_wall = time.perf_counter() - started
    process_cpu = time.process_time() - cpu_started
    from backtrader.research.alpha101 import get_alpha

    formula_class = get_alpha(3)
    formula_module = __import__(formula_class.__module__, fromlist=["__file__"])
    formula_path = Path(formula_module.__file__).resolve()
    factor_csv = csv_dir / "factors.csv"
    factor_output = _factor_csv_summary(factor_csv)
    panel_assets = sorted(str(asset) for asset in panel["assets"])
    if factor_output["assets"] != panel_assets:
        raise RuntimeError("final factor CSV assets do not match the loaded input panel")
    if set(factor_output["factors"]) != {"alpha003"}:
        raise RuntimeError("027 kernel attribution must export exactly alpha003")
    return {
        "status": "OK",
        "variant": variant,
        "pipeline": "027 current lightweight pipeline; runnext; only RollingCovariance/RollingCorrelation._evaluate vary",
        "stage_wall_s": stages["cerebro"],
        "worker_wall_s": process_wall,
        "worker_cpu_s": process_cpu,
        "peak_rss_bytes": benchmark._peak_rss(),
        "resident_rss_bytes": benchmark._rss(),
        "input": {
            "frame_sha256": input_hash,
            "requested_symbols": int(symbols),
            "actual_symbols": actual_symbols,
            "assets": len(panel["assets"]),
            "asset_names": panel_assets,
            "grid_rows": len(panel["grid"]),
            "feed_rows": sum(len(frame) for frame in panel["feeds"].values()),
            "config_sha256": _canonical_hash(config),
            "data_directory": str(module._resolve_path(config["data"]["directory"])),
        },
        "formula_class": "%s.%s" % (formula_class.__module__, formula_class.__qualname__),
        "formula_file": str(formula_path),
        "formula_file_sha256": _sha256_file(formula_path),
        "module_file": str(Path(backtrader.__file__).resolve()),
        "operators_file": str(source_path.resolve()),
        "environment": {
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
            "numpy": str(getattr(__import__("numpy"), "__version__", "unknown")),
            "pandas": str(getattr(__import__("pandas"), "__version__", "unknown")),
        },
        "kernel_method_sha256": current_hashes,
        "installed_legacy_method_sha256": patched_hashes,
        "patched_classes": changed,
        "stage_states": states,
        "shapes": artifacts.get("shapes"),
        "factor_output": factor_output,
    }


def _read_kernel_source(repo: Path) -> Tuple[str, str, str]:
    source = _git_text(repo, KERNEL_BASELINE_REVISION, "backtrader/research/operators.py")
    methods = _kernel_method_sources(source)
    if not all(token in "\n".join(methods.values()) for token in ("Fraction", "Decimal")):
        raise ValueError("the pinned legacy kernels are not the expected Fraction/Decimal code")
    full_commit = subprocess.run(
        ["git", "rev-parse", KERNEL_BASELINE_REVISION],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return source, full_commit, _canonical_hash(_kernel_hashes(source))


def _process_environment(python_path: Path) -> Dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONPATH"] = str(python_path.resolve())
    return env


def _measure_child(command: Sequence[str], *, cwd: Path, env: Mapping[str, str]) -> Dict[str, Any]:
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError("psutil is required for subprocess RSS attribution") from exc

    started = time.perf_counter()
    cpu_by_pid: Dict[int, float] = {}
    peak_rss = 0
    with tempfile.TemporaryFile(
        mode="w+t", encoding="utf-8"
    ) as stdout_file, tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr_file:
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            env=dict(env),
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
        )
        while process.poll() is None:
            try:
                root = psutil.Process(process.pid)
                processes = [root] + root.children(recursive=True)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                processes = []
            rss_total = 0
            for child in processes:
                try:
                    rss_total += int(child.memory_info().rss)
                    cpu = child.cpu_times()
                    cpu_by_pid[child.pid] = max(
                        cpu_by_pid.get(child.pid, 0.0), float(cpu.user + cpu.system)
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            peak_rss = max(peak_rss, rss_total)
            time.sleep(0.02)
        returncode = process.wait()
        wall = time.perf_counter() - started
        try:
            root = psutil.Process(process.pid)
            processes = [root] + root.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            processes = []
        for child in processes:
            try:
                cpu = child.cpu_times()
                cpu_by_pid[child.pid] = max(
                    cpu_by_pid.get(child.pid, 0.0), float(cpu.user + cpu.system)
                )
                peak_rss = max(peak_rss, int(child.memory_info().rss))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read()
        stderr = stderr_file.read()
    return {
        "returncode": returncode,
        "wall_s": wall,
        "cpu_tree_s": sum(cpu_by_pid.values()),
        "peak_rss_tree_bytes": peak_rss,
        "stdout": stdout[-4000:],
        "stderr": stderr[-4000:],
    }


def _load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("worker output must be a JSON object")
    return value


def _archive_revision(repo: Path, revision: str, destination: Path) -> str:
    if destination.exists():
        raise FileExistsError("archive destination already exists: %s" % destination)
    destination.mkdir(parents=True)
    with tempfile.TemporaryFile() as tar_file:
        completed = subprocess.run(
            ["git", "archive", "--format=tar", revision, *FINCORE_ARCHIVE_PATHS],
            cwd=str(repo),
            stdout=tar_file,
            stderr=subprocess.PIPE,
            text=True,
        )
        if completed.returncode:
            raise RuntimeError("git archive %s failed: %s" % (revision, completed.stderr.strip()))
        tar_file.seek(0)
        with tarfile.open(fileobj=tar_file, mode="r:") as archive:
            root = destination.resolve()
            for member in archive.getmembers():
                path = (destination / member.name).resolve()
                if path != root and root not in path.parents:
                    raise ValueError(
                        "archive member escapes extraction directory: %s" % member.name
                    )
            archive.extractall(destination)
    full_commit = subprocess.run(
        ["git", "rev-parse", revision], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout.strip()
    return full_commit


def _save_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _manifest_actual_symbol_count(manifest: Mapping[str, Any]) -> int:
    panel_dir = Path(manifest["panel_csv_dir"])
    assets = _wide_price_asset_order(panel_dir / "prices_open.csv")
    actual = len(assets)
    if manifest.get("actual_symbols") is not None:
        _validate_symbol_count(manifest["actual_symbols"], actual)
    if manifest.get("asset_order") is not None and list(manifest["asset_order"]) != assets:
        raise ValueError("prices_open.csv asset columns do not match the manifest order")
    if manifest.get("requested_symbols") is not None:
        _validate_symbol_count(manifest["requested_symbols"], actual)
    return actual


def _wide_price_asset_order(path: Path) -> List[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        try:
            header = next(csv.reader(handle))
        except StopIteration as exc:
            raise ValueError("wide price CSV is empty: %s" % path) from exc
    if not header or header[0] != "close_time":
        raise ValueError("wide price CSV must start with a close_time column: %s" % path)
    assets = [str(name) for name in header[1:]]
    if not assets or any(not asset for asset in assets):
        raise ValueError("wide price CSV must contain named asset columns: %s" % path)
    if len(set(assets)) != len(assets):
        raise ValueError("wide price CSV contains duplicate asset columns: %s" % path)
    return assets


def _read_wide_price_csv(
    path: Path, *, expected_assets: Optional[Sequence[str]] = None
) -> Tuple[Any, List[str]]:
    import pandas as pd

    assets = _wide_price_asset_order(path)
    if expected_assets is not None and list(expected_assets) != assets:
        raise ValueError("wide price CSV asset columns changed order or count: %s" % path)
    frame = pd.read_csv(path, dtype={"close_time": "string"}, float_precision="round_trip")
    if [str(column) for column in frame.columns] != ["close_time", *assets]:
        raise ValueError("wide price CSV header changed while loading: %s" % path)
    if frame.empty:
        raise ValueError("wide price CSV contains no rows: %s" % path)
    frame["close_time"] = pd.to_datetime(frame["close_time"], utc=True)
    if frame["close_time"].duplicated().any() or not frame["close_time"].is_monotonic_increasing:
        raise ValueError("wide price CSV timestamps must be unique and increasing: %s" % path)
    frame = frame.set_index("close_time")
    frame.index.name = "close_time"
    frame.columns = pd.Index(assets)
    return frame.astype("float64"), assets


def _run_kernel_mode(args: argparse.Namespace, output: Path) -> Dict[str, Any]:
    source, old_commit, old_bundle_hash = _read_kernel_source(REPO_ROOT)
    old_source_path = output / "legacy-operators.py"
    old_source_path.write_text(source, encoding="utf-8")
    current_source = (REPO_ROOT / "backtrader" / "research" / "operators.py").read_text(
        encoding="utf-8"
    )
    current_hashes = _kernel_hashes(current_source)
    groups = _effective_groups(args.groups, args.smoke)
    warmups = 1 if args.smoke else args.warmups
    if warmups < 1:
        raise ValueError("warmups must be positive")
    records: List[Dict[str, Any]] = []
    factor_output_comparisons: List[Dict[str, Any]] = []
    run_number = 0

    def run_one(variant: str, phase: str, group: Optional[int]) -> None:
        nonlocal run_number
        run_number += 1
        run_dir = output / "runs" / ("%s-%02d" % (phase, run_number))
        run_dir.mkdir(parents=True)
        result_path = run_dir / "worker.json"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--_worker",
            "kernel",
            "--variant",
            variant,
            "--symbols",
            str(args.symbols),
            "--output",
            str(run_dir),
            "--output-json",
            str(result_path),
            "--operator-source",
            str(old_source_path),
        ]
        if args.data_dir:
            command.extend(["--data-dir", str(Path(args.data_dir).expanduser().resolve())])
        measured = _measure_child(command, cwd=REPO_ROOT, env=_process_environment(REPO_ROOT))
        worker = _load_json(result_path) if result_path.is_file() else None
        record = {
            "variant": variant,
            "phase": phase,
            "group": group,
            "command": command,
            "measurement": measured,
            "worker": worker,
        }
        records.append(record)
        if measured["returncode"] != 0 or worker is None or worker.get("status") != "OK":
            raise RuntimeError("kernel %s %s failed: %s" % (variant, phase, measured["stderr"]))

    for index in range(warmups):
        start = len(records)
        for variant in _alternating_order(index):
            run_one(variant, "warmup", None)
        pair = {record["variant"]: record for record in records[start:]}
        comparison = _compare_factor_csvs(
            Path(pair["old"]["worker"]["factor_output"]["path"]),
            Path(pair["new"]["worker"]["factor_output"]["path"]),
        )
        if not comparison["matches"]:
            raise RuntimeError("warmup old/new factor CSV mismatch: %r" % comparison)
        factor_output_comparisons.append(
            {"phase": "warmup", "group": index, "comparison": comparison}
        )
    group_records: List[Dict[str, Any]] = []
    for group in range(groups):
        start = len(records)
        for variant in _alternating_order(group):
            run_one(variant, "measure", group)
        pair = {record["variant"]: record for record in records[start:]}
        comparison = _compare_factor_csvs(
            Path(pair["old"]["worker"]["factor_output"]["path"]),
            Path(pair["new"]["worker"]["factor_output"]["path"]),
        )
        if not comparison["matches"]:
            raise RuntimeError("measurement old/new factor CSV mismatch: %r" % comparison)
        factor_output_comparisons.append(
            {"phase": "measure", "group": group, "comparison": comparison}
        )
        group_records.append(
            {
                "group": group,
                "order": list(_alternating_order(group)),
                "records": records[start:],
                "factor_output_comparison": comparison,
            }
        )

    measured = {
        variant: [
            float(record["worker"]["stage_wall_s"])
            for record in records
            if record["phase"] == "measure" and record["variant"] == variant
        ]
        for variant in ("old", "new")
    }
    medians = {name: statistics.median(values) for name, values in measured.items()}
    minima = {name: min(values) for name, values in measured.items()}
    maxima = {name: max(values) for name, values in measured.items()}
    reduction = 1.0 - medians["new"] / medians["old"] if medians["old"] else None
    input_signatures = {
        record["worker"]["input"]["frame_sha256"]
        for record in records
        if record["worker"] is not None
    }
    config_signatures = {
        record["worker"]["input"]["config_sha256"]
        for record in records
        if record["worker"] is not None
    }
    if len(input_signatures) != 1 or len(config_signatures) != 1:
        raise RuntimeError("kernel variants did not receive identical input frames/config")
    return {
        "schema_version": "alpha101-attribution-v1",
        "mode": "kernel",
        "status": "SMOKE_ONLY" if args.smoke else "MEASURED",
        "acceptance": {
            "target_reduction": KERNEL_TARGET_REDUCTION,
            "median_reduction": reduction,
            "target_met": (
                None
                if args.smoke
                else bool(reduction is not None and reduction >= KERNEL_TARGET_REDUCTION)
            ),
            "scope": "027 Cerebro stage wall only; process-tree wall/CPU/RSS retained per fresh child",
            "measurement_status": "NOT_EVALUATED_SMOKE" if args.smoke else "EVALUATED",
        },
        "parameters": {
            "symbols": args.symbols,
            "warmups": warmups,
            "groups": groups,
            "alternation": "old/new, new/old",
        },
        "source": {
            "legacy_revision": old_commit,
            "legacy_operators_source_sha256": _sha256_bytes(source.encode("utf-8")),
            "legacy_kernel_bundle_sha256": old_bundle_hash,
            "legacy_kernel_method_sha256": _kernel_hashes(source),
            "candidate_revision": subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), capture_output=True, text=True
            ).stdout.strip(),
            "candidate_operator_file_sha256": _sha256_file(
                REPO_ROOT / "backtrader" / "research" / "operators.py"
            ),
            "candidate_kernel_method_sha256": current_hashes,
            "candidate_git_status": subprocess.run(
                ["git", "status", "--porcelain", "--", "backtrader/research/operators.py"],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
            ).stdout,
            "patch_scope": ["RollingCovariance._evaluate", "RollingCorrelation._evaluate"],
        },
        "environment": {
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "raw_records": records,
        "groups": group_records,
        "factor_output_comparisons": factor_output_comparisons,
        "summary": {
            "stage_wall_s": measured,
            "min_stage_wall_s": minima,
            "median_stage_wall_s": medians,
            "max_stage_wall_s": maxima,
        },
    }


def _report_config(example: str, config_path: Path) -> Dict[str, Any]:
    import yaml

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if example == "027":
        definitions = {"alpha003": {"direction": 1}}
    else:
        definitions = config.get("factors")
    if definitions is None:
        definitions = {config.get("factor", {}).get("name", "alpha003"): config.get("factor", {})}
    report_config = config.get("evaluation", {})
    factor_specs = {
        str(name): {"direction": int(definition.get("direction", 1))}
        for name, definition in definitions.items()
    }
    return {
        "example": example,
        "config_sha256": _sha256_file(config_path),
        "factors": factor_specs,
        "periods": list(report_config.get("periods", (1, 5, 20))),
        "label": report_config.get("label", "next_open_to_open"),
        "quantiles": int(report_config.get("quantiles", 5)),
        "max_loss": float(report_config.get("max_loss", 1.0)),
        "language": "zh",
        "title_prefix": "alpha-research attribution %s" % example,
    }


def _export_report_frames(args: argparse.Namespace, output: Path) -> Path:
    import pandas as pd

    frame_root = output / "frames"
    frame_root.mkdir()
    for example in EXAMPLES:
        export_root = frame_root / ("export-%s" % example)
        command = [
            sys.executable,
            str(BENCHMARK_SCRIPT),
            "--example",
            example,
            "--symbols",
            str(args.symbols),
            "--csv",
            "--no-isolate",
            "--output",
            str(export_root),
        ]
        if args.data_dir:
            command.extend(["--data-dir", str(Path(args.data_dir).expanduser().resolve())])
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            env=_process_environment(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        if completed.returncode:
            raise RuntimeError(
                "current frame export failed for %s: %s" % (example, completed.stderr[-2000:])
            )
        result = _load_json(export_root / "benchmark.json")
        runs = result.get("results", [])
        if len(runs) != 1 or runs[0].get("status") != "OK":
            raise RuntimeError("current frame export did not complete for %s" % example)
        panel_dir = Path(runs[0]["artifacts"]["csv_dir"]).resolve()
        actual_symbols = int(runs[0]["artifacts"].get("symbols", 0))
        _validate_symbol_count(args.symbols, actual_symbols)
        if not panel_dir.is_dir():
            raise RuntimeError("frame export omitted the FactorPanel CSVs for %s" % example)
        asset_order = _wide_price_asset_order(panel_dir / "prices_open.csv")
        close_asset_order = _wide_price_asset_order(panel_dir / "prices_close.csv")
        if asset_order != close_asset_order:
            raise RuntimeError("open/close price CSV asset columns differ for %s" % example)
        _validate_symbol_count(args.symbols, len(asset_order))
        exported_factor_assets = pd.read_csv(
            panel_dir / "factors.csv", usecols=["asset"], dtype={"asset": str}
        )["asset"]
        if set(exported_factor_assets.drop_duplicates()) != set(asset_order):
            raise RuntimeError(
                "factor CSV assets do not match the wide price columns for %s" % example
            )
        manifest = _report_config(example, EXAMPLE_DIRS[example] / "config.yaml")
        csv_hashes = {
            path.name: _sha256_file(path)
            for path in sorted(panel_dir.glob("*.csv"), key=lambda item: item.name)
        }
        if not {"factors.csv", "prices_open.csv", "prices_close.csv"}.issubset(csv_hashes):
            raise RuntimeError(
                "frame export lacks required factor/open/close inputs for %s" % example
            )
        manifest.update(
            {
                "requested_symbols": int(args.symbols),
                "actual_symbols": actual_symbols,
                "asset_order": asset_order,
                "panel_csv_dir": str(panel_dir),
                "csv_sha256": csv_hashes,
                "input_manifest_sha256": _canonical_hash(csv_hashes),
                "source_export_benchmark": str(BENCHMARK_SCRIPT),
                "source_export_git_head": result.get("metadata", {}).get("head"),
                "source_export_metadata": {
                    key: result.get("metadata", {}).get(key)
                    for key in (
                        "head",
                        "python",
                        "python_executable",
                        "platform",
                        "numpy",
                        "pandas",
                        "fincore",
                        "hashes_before",
                        "hashes_after",
                        "hash_drift",
                    )
                },
            }
        )
        _save_json(frame_root / ("%s.json" % example), manifest)
    return frame_root


def _extract_html_timestamp(rendered: str) -> Tuple[str, Optional[str]]:
    import re

    pattern = r"(<span[^>]*>)(\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC)(</span>)"
    matches = list(re.finditer(pattern, rendered))
    if len(matches) != 1:
        return rendered, None
    timestamp = matches[0].group(2)
    return re.sub(pattern, r"\1<generated-time>\3", rendered, count=1), timestamp


def _report_worker(*, revision_root: Path, manifest_path: Path, output: Path) -> Dict[str, Any]:
    import pandas as pd
    import numpy as np
    import fincore
    from fincore.factor_analysis.analysis import analyze_factor
    from fincore.factor_analysis.data import prepare_factor_data
    from fincore.report.factor import (
        build_factor_report,
        write_factor_report,
    )

    module_file = Path(fincore.__file__).resolve()
    try:
        module_file.relative_to(revision_root.resolve())
    except ValueError as exc:
        raise RuntimeError(
            "fincore imported outside the requested git archive: %s" % module_file
        ) from exc

    manifest = _load_json(manifest_path)
    source_modules = {
        name: str(Path(sys.modules[name].__file__).resolve())
        for name in (
            "fincore.factor_analysis.analysis",
            "fincore.factor_analysis.data",
            "fincore.factor_analysis.models",
            "fincore.report.factor.compute",
            "fincore.report.factor.html",
            "fincore.report.models",
        )
        if name in sys.modules
    }
    if len(source_modules) != 6:
        raise RuntimeError("the expected public fincore analysis/report modules were not imported")
    for name, filename in source_modules.items():
        try:
            Path(filename).relative_to(revision_root.resolve())
        except ValueError as exc:
            raise RuntimeError(
                "%s imported outside the git archive: %s" % (name, filename)
            ) from exc
    panel_dir = Path(manifest["panel_csv_dir"])
    input_hashes = manifest["csv_sha256"]
    for filename, digest in input_hashes.items():
        if _sha256_file(panel_dir / filename) != digest:
            raise RuntimeError("input frame changed after export: %s" % filename)
    factors = pd.read_csv(
        panel_dir / "factors.csv", dtype={"asset": str}, float_precision="round_trip"
    )
    factors["time"] = pd.to_datetime(factors["time"], utc=True)
    expected_assets = manifest.get("asset_order")
    opens, open_assets = _read_wide_price_csv(
        panel_dir / "prices_open.csv", expected_assets=expected_assets
    )
    closes, close_assets = _read_wide_price_csv(
        panel_dir / "prices_close.csv", expected_assets=open_assets
    )
    if close_assets != open_assets:
        raise ValueError("open/close price CSV asset columns differ")
    actual_symbols = len(open_assets)
    if manifest.get("actual_symbols") is not None:
        _validate_symbol_count(manifest["actual_symbols"], actual_symbols)
    if manifest.get("requested_symbols") is not None:
        _validate_symbol_count(manifest["requested_symbols"], actual_symbols)

    periods = tuple(int(value) for value in manifest["periods"])
    if periods != (1, 5, 20):
        raise ValueError("attribution report periods must be exactly (1, 5, 20)")
    label = manifest["label"]
    if label not in ("next_open_to_open", "close_to_close"):
        raise ValueError("unsupported factor report label: %s" % label)
    prices = opens if label == "next_open_to_open" else closes
    next_open = label == "next_open_to_open"
    factor_names = list(manifest["factors"])
    expected_counts = {"025": 1, "026": 3, "027": 1}
    if len(factor_names) != expected_counts[manifest["example"]]:
        raise ValueError("factor count does not match the 025/026/027 report contract")
    if {str(value) for value in factors["asset"].drop_duplicates()} != set(open_assets):
        raise ValueError("factor CSV assets do not match the shared price panel")
    finite_factor_counts: Dict[str, int] = {}
    for name in factor_names:
        values = factors.loc[factors["factor"] == name, "value"].to_numpy(
            dtype="float64", copy=False
        )
        if np.isinf(values).any():
            raise ValueError("factor %s contains infinite output cells" % name)
        finite_count = int(np.isfinite(values).sum())
        if finite_count <= 0:
            raise ValueError("factor %s has no finite output cells" % name)
        finite_factor_counts[name] = finite_count

    output.mkdir(parents=True, exist_ok=False)
    hashes_before = {filename: _sha256_file(panel_dir / filename) for filename in input_hashes}
    started = time.perf_counter()
    outputs = []
    for name in factor_names:
        selected = factors.loc[factors["factor"] == name, ["time", "asset", "value"]].copy()
        if selected.empty:
            raise ValueError("exported input does not contain factor %s" % name)
        factor = pd.Series(
            selected["value"].to_numpy(dtype="float64", copy=True)
            * int(manifest["factors"][name]["direction"]),
            index=pd.MultiIndex.from_arrays(
                [selected["time"], selected["asset"]], names=("date", "asset")
            ),
            name="factor",
            dtype="float64",
        )
        title = "%s %s" % (manifest["title_prefix"], name)
        path = output / ("factor_report_%s.html" % name)
        write_factor_report(
            factor,
            prices,
            path,
            periods=periods,
            quantiles=int(manifest["quantiles"]),
            max_loss=float(manifest["max_loss"]),
            title=title,
            language=str(manifest["language"]),
            next_open=next_open,
        )
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError("HTML report was not written: %s" % path)
        outputs.append({"factor": name, "path": str(path), "html_bytes": path.stat().st_size})
    report_wall = time.perf_counter() - started

    # This untimed public-API pass records the complete analytical model and
    # report semantics. It deliberately does not reimplement fincore math.
    semantic_records = []
    for name in factor_names:
        selected = factors.loc[factors["factor"] == name, ["time", "asset", "value"]].copy()
        factor = pd.Series(
            selected["value"].to_numpy(dtype="float64", copy=True)
            * int(manifest["factors"][name]["direction"]),
            index=pd.MultiIndex.from_arrays(
                [selected["time"], selected["asset"]], names=("date", "asset")
            ),
            name="factor",
            dtype="float64",
        )
        prepared_prices = prices.shift(-1) if next_open else prices
        prepared = prepare_factor_data(
            factor,
            prepared_prices,
            periods=periods,
            quantiles=int(manifest["quantiles"]),
            max_loss=float(manifest["max_loss"]),
        )
        model = analyze_factor(prepared.data, periods=None, turnover_periods=periods)
        title = "%s %s" % (manifest["title_prefix"], name)
        report_model = build_factor_report(model, title=title)
        report_model_digest = getattr(report_model, "semantic_digest", None)
        if not report_model_digest and callable(getattr(report_model, "semantic_payload", None)):
            report_model_digest = _canonical_hash(report_model.semantic_payload())
        if not report_model_digest:
            raise RuntimeError("fincore report model exposes no semantic payload or digest")
        loss = prepared.loss_report
        loss_values = {
            field: getattr(loss, field)
            for field in (
                "input_count",
                "finite_factor_count",
                "forward_returns_count",
                "binning_count",
                "total_loss",
            )
            if hasattr(loss, field)
        }
        model_digest = str(getattr(model, "result_fingerprint", ""))
        if not model_digest:
            raise RuntimeError("fincore factor model has no result_fingerprint")
        semantic_records.append(
            {
                "factor": name,
                "model_result_fingerprint": model_digest,
                "report_semantic_digest": str(report_model_digest),
                "preparation_loss": loss_values,
                "complete_semantic_digest": _canonical_hash(
                    {
                        "model_result_fingerprint": model_digest,
                        "report_semantic_digest": str(report_model_digest),
                        "preparation_loss": loss_values,
                        "periods": periods,
                        "direction": int(manifest["factors"][name]["direction"]),
                        "label": label,
                        "quantiles": int(manifest["quantiles"]),
                        "max_loss": float(manifest["max_loss"]),
                        "title": title,
                    }
                ),
            }
        )

    html_records = []
    for item in outputs:
        path = Path(item["path"])
        rendered = path.read_text(encoding="utf-8")
        normalized, generated_at = _extract_html_timestamp(rendered)
        html_records.append(
            {
                "factor": item["factor"],
                "path": str(path),
                "raw_sha256": _sha256_file(path),
                "normalized_html_sha256": _sha256_bytes(normalized.encode("utf-8")),
                "generated_at_utc": generated_at,
                "html_bytes": item["html_bytes"],
            }
        )
    hashes_after = {filename: _sha256_file(panel_dir / filename) for filename in input_hashes}
    if hashes_before != hashes_after:
        raise RuntimeError("fincore mutated the shared exported input frames")
    return {
        "status": "OK",
        "example": manifest["example"],
        "revision_root": str(revision_root.resolve()),
        "fincore_module_file": str(module_file),
        "fincore_module_sources": source_modules,
        "fincore_version": str(getattr(fincore, "__version__", "unknown")),
        "environment": {
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
            "numpy": str(getattr(__import__("numpy"), "__version__", "unknown")),
            "pandas": str(getattr(pd, "__version__", "unknown")),
        },
        "report_stage_wall_s": report_wall,
        "report_count": len(outputs),
        "factor_count": len(factor_names),
        "requested_symbols": manifest.get("requested_symbols"),
        "actual_symbols": actual_symbols,
        "periods": list(periods),
        "label": label,
        "directions": {name: manifest["factors"][name]["direction"] for name in factor_names},
        "quantiles": int(manifest["quantiles"]),
        "max_loss": float(manifest["max_loss"]),
        "input_csv_sha256": input_hashes,
        "factor_cells": int(len(factors)),
        "finite_factor_cells": finite_factor_counts,
        "semantic_records": semantic_records,
        "html_records": html_records,
        "peak_rss_bytes": int(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            * (1 if sys.platform == "darwin" else 1024)
        ),
        "resident_rss_bytes": _current_rss_bytes(),
    }


def _current_rss_bytes() -> int:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except ImportError:
        return -1


def _run_reports_mode(args: argparse.Namespace, output: Path) -> Dict[str, Any]:
    fincore_repo = Path(args.fincore_repo).expanduser().resolve()
    if not (fincore_repo / ".git").exists():
        raise ValueError("--fincore-repo must be a git checkout: %s" % fincore_repo)
    frame_root = (
        Path(args.frames_dir).expanduser().resolve()
        if args.frames_dir
        else _export_report_frames(args, output)
    )
    for example in EXAMPLES:
        manifest = _load_json(frame_root / ("%s.json" % example))
        actual_symbols = _manifest_actual_symbol_count(manifest)
        _validate_symbol_count(args.symbols, actual_symbols)
        if manifest.get("requested_symbols") is not None:
            _validate_symbol_count(args.symbols, manifest["requested_symbols"])
    archive_roots: Dict[str, Path] = {}
    full_commits = {}
    candidate_revision = getattr(args, "fincore_candidate_revision", "HEAD")
    revision_refs = {"old": FINCORE_BASELINE_REVISION, "new": candidate_revision}
    for variant, revision in revision_refs.items():
        archive_root = output / "archives" / variant
        archive_root.parent.mkdir(parents=True, exist_ok=True)
        full_commits[variant] = _archive_revision(fincore_repo, revision, archive_root)
        archive_roots[variant] = archive_root

    groups = _effective_groups(args.groups, args.smoke)
    warmups = 1 if args.smoke else args.warmups
    if warmups < 1:
        raise ValueError("warmups must be positive")
    records: List[Dict[str, Any]] = []
    run_number = 0

    def run_one(variant: str, example: str, phase: str, group: Optional[int]) -> None:
        nonlocal run_number
        run_number += 1
        output_dir = output / "runs" / ("%s-%02d" % (phase, run_number)) / example / variant
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        if output_dir.exists():
            raise FileExistsError("run output already exists: %s" % output_dir)
        result_path = output_dir.parent / (variant + ".json")
        manifest_path = frame_root / ("%s.json" % example)
        manifest = _load_json(manifest_path)
        input_dir = Path(manifest["panel_csv_dir"])
        for filename, digest in manifest["csv_sha256"].items():
            if _sha256_file(input_dir / filename) != digest:
                raise RuntimeError("shared report input changed before %s run" % variant)
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--_worker",
            "report",
            "--revision-root",
            str(archive_roots[variant]),
            "--manifest",
            str(manifest_path),
            "--output",
            str(output_dir),
            "--output-json",
            str(result_path),
        ]
        measurement = _measure_child(
            command, cwd=archive_roots[variant], env=_process_environment(archive_roots[variant])
        )
        worker = _load_json(result_path) if result_path.is_file() else None
        record = {
            "variant": variant,
            "example": example,
            "phase": phase,
            "group": group,
            "command": command,
            "measurement": measurement,
            "worker": worker,
        }
        records.append(record)
        if measurement["returncode"] != 0 or worker is None or worker.get("status") != "OK":
            raise RuntimeError(
                "report %s %s failed: %s"
                % (
                    example,
                    variant,
                    (
                        worker.get("traceback", worker.get("error"))
                        if worker is not None
                        else measurement["stderr"]
                    ),
                )
            )

    for index in range(warmups):
        for example in EXAMPLES:
            for variant in _alternating_order(index):
                run_one(variant, example, "warmup", None)
    group_records = []
    for group in range(groups):
        start = len(records)
        for example in EXAMPLES:
            for variant in _alternating_order(group):
                run_one(variant, example, "measure", group)
        group_records.append(
            {"group": group, "order": list(_alternating_order(group)), "records": records[start:]}
        )

    parity: Dict[str, Any] = {}
    medians: Dict[str, Dict[str, float]] = {}
    minima: Dict[str, Dict[str, float]] = {}
    maxima: Dict[str, Dict[str, float]] = {}
    reductions: Dict[str, float] = {}
    for example in EXAMPLES:
        example_records = [
            record
            for record in records
            if record["phase"] == "measure" and record["example"] == example
        ]
        by_variant = {
            variant: [
                record["worker"] for record in example_records if record["variant"] == variant
            ]
            for variant in ("old", "new")
        }
        semantic_by_variant = {
            variant: [
                {
                    item["factor"]: item["complete_semantic_digest"]
                    for item in worker["semantic_records"]
                }
                for worker in workers
            ]
            for variant, workers in by_variant.items()
        }
        html_by_variant = {
            variant: [
                {item["factor"]: item["normalized_html_sha256"] for item in worker["html_records"]}
                for worker in workers
            ]
            for variant, workers in by_variant.items()
        }
        semantic_equal = all(
            item == semantic_by_variant["old"][0]
            for values in semantic_by_variant.values()
            for item in values
        )
        html_equal = all(
            item == html_by_variant["old"][0]
            for values in html_by_variant.values()
            for item in values
        )
        old_times = [float(worker["report_stage_wall_s"]) for worker in by_variant["old"]]
        new_times = [float(worker["report_stage_wall_s"]) for worker in by_variant["new"]]
        old_median = statistics.median(old_times)
        new_median = statistics.median(new_times)
        minima[example] = {"old_report_s": min(old_times), "new_report_s": min(new_times)}
        maxima[example] = {"old_report_s": max(old_times), "new_report_s": max(new_times)}
        reduction = 1.0 - new_median / old_median if old_median else 0.0
        medians[example] = {"old_report_s": old_median, "new_report_s": new_median}
        reductions[example] = reduction
        parity[example] = {
            "model_and_report_semantics_equal": semantic_equal,
            "normalized_html_equal": html_equal,
            "old_complete_semantic_digests": semantic_by_variant["old"],
            "new_complete_semantic_digests": semantic_by_variant["new"],
            "old_normalized_html_sha256": html_by_variant["old"],
            "new_normalized_html_sha256": html_by_variant["new"],
        }
    return {
        "schema_version": "alpha101-attribution-v1",
        "mode": "reports",
        "status": "SMOKE_ONLY" if args.smoke else "MEASURED",
        "acceptance": {
            "target_reduction_each_example": REPORT_TARGET_REDUCTION,
            "median_reduction_by_example": reductions,
            "target_met_by_example": {
                example: None if args.smoke else reductions[example] >= REPORT_TARGET_REDUCTION
                for example in EXAMPLES
            },
            "measurement_status": "NOT_EVALUATED_SMOKE" if args.smoke else "EVALUATED",
            "semantic_parity": all(
                parity[example]["model_and_report_semantics_equal"]
                and parity[example]["normalized_html_equal"]
                for example in EXAMPLES
            ),
        },
        "parameters": {"warmups": warmups, "groups": groups, "alternation": "old/new, new/old"},
        "source": {
            "fincore_repo": str(fincore_repo),
            "requested_revisions": revision_refs,
            "revisions": full_commits,
            "archive_mode": "git archive",
        },
        "environment": {
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "frame_bundle": str(frame_root.resolve()),
        "per_example_medians_s": medians,
        "per_example_minima_s": minima,
        "per_example_maxima_s": maxima,
        "per_example_raw_report_s": {
            example: {
                variant: [float(worker["report_stage_wall_s"]) for worker in workers]
                for variant, workers in {
                    name: [
                        record["worker"]
                        for record in records
                        if record["phase"] == "measure"
                        and record["example"] == example
                        and record["variant"] == name
                    ]
                    for name in ("old", "new")
                }.items()
            }
            for example in EXAMPLES
        },
        "parity": parity,
        "raw_records": records,
        "groups": group_records,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("kernel", "reports"))
    parser.add_argument(
        "--output", required=True, help="new result directory; existing paths are rejected"
    )
    parser.add_argument("--symbols", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--groups", type=int, default=3)
    parser.add_argument("--data-dir", help="optional fixed input CSV directory")
    parser.add_argument("--fincore-repo", default="/Users/yunjinqi/Documents/new_projects/fincore")
    parser.add_argument(
        "--fincore-candidate-revision",
        default="HEAD",
        help="candidate fincore ref (default: current fincore HEAD; resolved SHA is recorded)",
    )
    parser.add_argument(
        "--frames-dir", help="reuse an existing 025.json/026.json/027.json panel bundle"
    )
    parser.add_argument(
        "--smoke", action="store_true", help="one alternating group; never evaluates target"
    )
    parser.add_argument("--_worker", choices=("kernel", "report"), help=argparse.SUPPRESS)
    parser.add_argument("--variant", choices=("old", "new"), help=argparse.SUPPRESS)
    parser.add_argument("--operator-source", help=argparse.SUPPRESS)
    parser.add_argument("--revision-root", help=argparse.SUPPRESS)
    parser.add_argument("--manifest", help=argparse.SUPPRESS)
    parser.add_argument("--output-json", help=argparse.SUPPRESS)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if args._worker:
        try:
            if not args.output_json:
                raise ValueError("worker requires --output-json")
            if args._worker == "kernel":
                if not args.variant or not args.operator_source:
                    raise ValueError("kernel worker requires --variant and --operator-source")
                result = _kernel_worker(
                    variant=args.variant,
                    symbols=args.symbols,
                    data_dir=args.data_dir,
                    output=Path(args.output_json).resolve().parent,
                    operator_source=Path(args.operator_source),
                )
            else:
                if not args.revision_root or not args.manifest:
                    raise ValueError("report worker requires --revision-root and --manifest")
                result = _report_worker(
                    revision_root=Path(args.revision_root),
                    manifest_path=Path(args.manifest),
                    output=Path(args.output).resolve(),
                )
            _save_json(Path(args.output_json), result)
            return 0
        except Exception as exc:
            if args.output_json:
                _save_json(
                    Path(args.output_json),
                    {
                        "status": "FAILED",
                        "error": "%s: %s" % (type(exc).__name__, exc),
                        "traceback": traceback.format_exc(),
                    },
                )
            print("worker failed: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
            return 1
    if not args.mode:
        print("--mode is required", file=sys.stderr)
        return 2
    if args.symbols < 1 or args.warmups < 1 or args.groups < 1:
        print("--symbols, --warmups, and --groups must be positive", file=sys.stderr)
        return 2
    if not args.smoke and args.groups < 3:
        print("non-smoke attribution requires --groups >= 3", file=sys.stderr)
        return 2
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        print("output directory already exists: %s" % output, file=sys.stderr)
        return 3
    output.mkdir(parents=True)
    try:
        result = (
            _run_kernel_mode(args, output)
            if args.mode == "kernel"
            else _run_reports_mode(args, output)
        )
        result["command"] = list(sys.argv if argv is None else [sys.argv[0]] + list(argv))
        _save_json(output / "attribution.json", result)
        print("attribution: %s" % (output / "attribution.json"))
        if args.smoke:
            print("SMOKE_ONLY: performance targets were not evaluated")
            return 0
        acceptance = result["acceptance"]
        if args.mode == "kernel" and not acceptance["target_met"]:
            return 1
        if args.mode == "reports":
            if not acceptance["semantic_parity"]:
                return 1
            if not all(acceptance["target_met_by_example"].values()):
                return 1
        return 0
    except Exception as exc:
        _save_json(
            output / "attribution.json",
            {
                "schema_version": "alpha101-attribution-v1",
                "mode": args.mode,
                "status": "FAILED",
                "error": "%s: %s" % (type(exc).__name__, exc),
                "command": list(sys.argv if argv is None else [sys.argv[0]] + list(argv)),
            },
        )
        print("FAILED: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
