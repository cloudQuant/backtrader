"""Run paired, fresh-process benchmarks for factor-research examples 025-027.

The harness executes each checkout's real ``run.py`` with the selected data
snapshot and symbol limit. One full-size warmup runs per checkout/example,
followed by alternating baseline/candidate runs for every measured group.
Parent-side psutil samples record wall time, process-tree CPU, and peak RSS.
Examples 025/026 export the PNGs declared by fincore's evaluation manifest by
default; ``--no-charts`` selects diagnostic-only runs.
The default 500-symbol profile is the minimum formal sample floor; runs with a
smaller explicit symbol limit are labeled ``SMOKE_ONLY`` in the result manifest.
"""

from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

EXAMPLES = ("025", "026", "027")
EXAMPLE_DIRS = {
    "025": Path("examples/backtest/025_factor_single"),
    "026": Path("examples/backtest/026_factor_multi"),
    "027": Path("examples/backtest/027_alpha003_panel_acceptance"),
}
FORMAL_MINIMUM_SYMBOLS = 500
EXPECTED_PANEL_CSVS = frozenset(
    {
        "factors.csv",
        "grid.csv",
        "groups.csv",
        "prices_close.csv",
        "prices_open.csv",
        "universe.csv",
    }
)
REQUIRED_EVALUATION_TABLES = ("labels.csv", "ic.csv", "signals.csv")
EXPECTED_FACTORS = {
    "025": ("close_ma",),
    "026": ("close_ma", "roc", "kdj_j"),
    "027": ("alpha003",),
}
SOURCE_SUFFIXES = {".py", ".yaml"}
CONFIG_DIFFERENCE_ALLOWLIST = {
    "operator_profile": {
        "example": "027",
        "baseline": "alpha101-v1",
        "candidate": "alpha101-v2",
        "reason": "native Alpha003 moved to the alpha101-v2 float64 operator profile; the frozen alpha101-v1 runtime cannot run that profile",
        "scope": "allowed for end-to-end comparison only; not evidence for isolated structural or float-profile attribution",
    }
}
PROBE_SOURCE = r"""
import importlib.util, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path.cwd()))
import backtrader
import backtrader.research as research
fincore = importlib.util.find_spec('fincore')
print(json.dumps({
    'backtrader': str(pathlib.Path(backtrader.__file__).resolve()),
    'research': str(pathlib.Path(research.__file__).resolve()),
    'fincore': None if fincore is None else fincore.origin,
    'python': sys.executable,
}))
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _process_environment(root: Path) -> Dict[str, str]:
    """Bind imports to this checkout and drop any inherited PYTHONPATH."""
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONPATH"] = str(root.resolve())
    return environment


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _git_head(root: Path) -> Optional[str]:
    top_level = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=str(root), capture_output=True, text=True
    )
    if top_level.returncode != 0 or Path(top_level.stdout.strip()).resolve() != root.resolve():
        return None
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"], cwd=str(root), capture_output=True, text=True
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _git_status(root: Path) -> str:
    top_level = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=str(root), capture_output=True, text=True
    )
    if top_level.returncode != 0 or Path(top_level.stdout.strip()).resolve() != root.resolve():
        return ""
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout


def _source_manifest(root: Path) -> Dict[str, str]:
    paths = set()
    for package in ("backtrader", "backtrader_runtime", "scripts"):
        directory = root / package
        if directory.is_dir():
            paths.update(directory.rglob("*.py"))
    for relative in EXAMPLE_DIRS.values():
        directory = root / relative
        if directory.is_dir():
            paths.update(
                path
                for path in directory.rglob("*")
                if path.is_file() and (path.suffix in SOURCE_SUFFIXES or path.name == "config.yaml")
            )
    for path in root.glob("requirements*.txt"):
        if path.is_file():
            paths.add(path)
    for filename in (
        "setup.py",
        "pyproject.toml",
        "setup.cfg",
        "Pipfile.lock",
        "poetry.lock",
        "uv.lock",
        "conda-lock.yml",
        "environment.yml",
    ):
        path = root / filename
        if path.is_file():
            paths.add(path)
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(paths, key=lambda item: item.as_posix())
    }


def _dependency_snapshot() -> Dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True
    )
    if completed.returncode != 0:
        raise RuntimeError("pip freeze failed: %s" % completed.stderr[-2000:])
    packages = sorted(line.strip() for line in completed.stdout.splitlines() if line.strip())
    return {
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "pip_freeze_returncode": completed.returncode,
        "pip_freeze": packages,
        "pip_freeze_sha256": _canonical_hash(packages),
        "pip_freeze_stderr": completed.stderr[-2000:],
    }


def _effective_config(root: Path, example: str, data_dir: Path, symbols: int) -> Dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to record benchmark input configuration") from exc
    path = root / EXAMPLE_DIRS[example] / "config.yaml"
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("data"), dict):
        raise ValueError("invalid example config: %s" % path)
    value = copy.deepcopy(value)
    value["data"]["directory"] = str(data_dir)
    value["data"]["max_symbols"] = symbols
    return value


def _probe_modules(root: Path) -> Dict[str, Any]:
    environment = _process_environment(root)
    completed = subprocess.run(
        [sys.executable, "-c", PROBE_SOURCE],
        cwd=str(root),
        env=environment,
        capture_output=True,
        text=True,
    )
    details: Dict[str, Any] = {
        "command": [sys.executable, "-c", PROBE_SOURCE],
        "returncode": completed.returncode,
        "stdout": completed.stdout[-2000:],
        "stderr": completed.stderr[-2000:],
    }
    if completed.returncode == 0:
        try:
            details["modules"] = json.loads(completed.stdout.strip().splitlines()[-1])
            details["module_source_sha256"] = {}
            for name, source in details["modules"].items():
                if name not in ("backtrader", "research", "fincore"):
                    continue
                path = Path(source) if isinstance(source, str) else None
                details["module_source_sha256"][name] = (
                    _sha256(path) if path is not None and path.is_file() else None
                )
        except (ValueError, IndexError):
            details["parse_error"] = "module probe did not return JSON"
    return details


def _probe_entrypoint(root: Path, example: str) -> Dict[str, Any]:
    script = root / EXAMPLE_DIRS[example] / "run.py"
    command = [sys.executable, str(script), "--help"]
    completed = subprocess.run(
        command,
        cwd=str(root),
        env=_process_environment(root),
        capture_output=True,
        text=True,
    )
    help_text = completed.stdout + completed.stderr
    option_names = (
        "--data-dir",
        "--max-symbols",
        "--report",
        "--no-charts",
        "--save-panel",
        "--save-dataset",
    )
    options = {option: option in help_text for option in option_names}
    if completed.returncode != 0:
        raise RuntimeError("%s %s --help failed: %s" % (example, script, help_text[-2000:]))
    for required in ("--data-dir", "--max-symbols", "--report"):
        if not options[required]:
            raise RuntimeError("%s entrypoint does not support %s" % (script, required))
    if example in ("025", "026"):
        if options["--save-panel"]:
            save_mode = "factor_panel_csv"
        elif options["--save-dataset"]:
            save_mode = "legacy_research_dataset"
        else:
            raise RuntimeError("%s supports neither --save-panel nor --save-dataset" % script)
    else:
        save_mode = "factor_values_csv_only"
    return {
        "command": command,
        "returncode": completed.returncode,
        "options": options,
        "save_mode": save_mode,
        "help_sha256": hashlib.sha256(help_text.encode("utf-8")).hexdigest(),
        "help_tail": help_text[-2000:],
    }


def _inspect_side(
    root: Path,
    name: str,
    data_dir: Path,
    symbols: int,
    declared_revision: Optional[str],
    execution_environment: Mapping[str, Any],
) -> Dict[str, Any]:
    if not (root / "backtrader" / "__init__.py").is_file():
        raise ValueError("%s root is not a Backtrader source checkout: %s" % (name, root))
    configs = {}
    config_hashes = {}
    for example in EXAMPLES:
        config_path = root / EXAMPLE_DIRS[example] / "config.yaml"
        for filename in ("run.py", "config.yaml"):
            if not (config_path.parent / filename).is_file():
                raise FileNotFoundError("missing benchmark input: %s" % (config_path.parent / filename))
        configs[example] = _effective_config(root, example, data_dir, symbols)
        config_hashes[example] = _sha256(config_path)
    entrypoints = {example: _probe_entrypoint(root, example) for example in EXAMPLES}
    source_hashes = _source_manifest(root)
    git_status = _git_status(root)
    git_head = _git_head(root)
    return {
        "name": name,
        "root": str(root),
        "git_head": git_head,
        "source_revision": git_head or declared_revision,
        "source_revision_method": "git" if git_head else "explicit_cli",
        "git_status": git_status,
        "git_status_sha256": hashlib.sha256(git_status.encode("utf-8")).hexdigest(),
        "source_hashes": source_hashes,
        "source_manifest_sha256": _canonical_hash(source_hashes),
        "config_sha256": config_hashes,
        "effective_config_sha256": {
            example: _canonical_hash(configs[example]) for example in EXAMPLES
        },
        "effective_configs": configs,
        "entrypoints": entrypoints,
        "pythonpath": str(root),
        "module_probe": _probe_modules(root),
        "execution_environment_sha256": _canonical_hash(execution_environment),
        "dependency_declaration_sha256": {
            path: digest
            for path, digest in source_hashes.items()
            if path.startswith("requirements")
            or path in {
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


def _config_differences(left: Any, right: Any, prefix: str = "") -> List[Dict[str, Any]]:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        keys = sorted(set(left) | set(right))
        differences = []
        for key in keys:
            path = "%s.%s" % (prefix, key) if prefix else str(key)
            if key not in left or key not in right:
                differences.append(
                    {"path": path, "baseline": left.get(key), "candidate": right.get(key)}
                )
            else:
                differences.extend(_config_differences(left[key], right[key], path))
        return differences
    if left != right:
        return [{"path": prefix, "baseline": left, "candidate": right}]
    return []


def _classify_config_differences(
    differences: Mapping[str, Sequence[Mapping[str, Any]]],
    requested_allowlist: Sequence[str],
) -> Dict[str, Any]:
    """Allow only explicitly named, exact input migrations; fail on all others."""
    requested = set(requested_allowlist)
    allowed = []
    unapproved = []
    for example, items in differences.items():
        for difference in items:
            key = str(difference.get("path"))
            policy = CONFIG_DIFFERENCE_ALLOWLIST.get(key)
            approved = bool(
                policy
                and key in requested
                and example == policy["example"]
                and difference.get("baseline") == policy["baseline"]
                and difference.get("candidate") == policy["candidate"]
            )
            entry = {"example": example, **dict(difference)}
            if approved:
                entry["approved"] = True
                entry["reason"] = policy["reason"]
                entry["scope"] = policy["scope"]
                allowed.append(entry)
            else:
                entry["approved"] = False
                unapproved.append(entry)
    return {
        "allowed_differences": allowed,
        "unapproved_differences": unapproved,
        "compatible": not unapproved,
    }


def _build_command(
    root: Path,
    example: str,
    output_dir: Path,
    data_dir: Path,
    symbols: int,
    save_mode: Optional[str] = None,
    no_charts: bool = False,
) -> List[str]:
    command = [
        sys.executable,
        str(root / EXAMPLE_DIRS[example] / "run.py"),
        "--output-dir",
        str(output_dir),
        "--data-dir",
        str(data_dir),
        "--max-symbols",
        str(symbols),
        "--report",
    ]
    if example in ("025", "026"):
        if save_mode == "legacy_research_dataset":
            command.append("--save-dataset")
        elif save_mode in (None, "factor_panel_csv"):
            command.append("--save-panel")
        else:
            raise ValueError("unsupported saved-panel API for %s: %s" % (example, save_mode))
        if no_charts:
            command.append("--no-charts")
    return command


def _path_inside(path: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((str(path.resolve()), str(parent.resolve()))) == str(
            parent.resolve()
        )
    except ValueError:
        return False


def _artifact_manifest(path: Path) -> List[Dict[str, Any]]:
    if path.is_file():
        files = [path]
    elif path.is_dir():
        files = [item for item in path.rglob("*") if item.is_file()]
    else:
        return []
    manifest = []
    for item in sorted(files, key=lambda item: item.as_posix()):
        entry: Dict[str, Any] = {
            "path": item.relative_to(path if path.is_dir() else path.parent).as_posix(),
            "size_bytes": item.stat().st_size,
            "sha256": _sha256(item),
        }
        if item.suffix.lower() == ".csv":
            with item.open("r", encoding="utf-8-sig", newline="") as handle:
                entry["csv_header"] = handle.readline().rstrip("\r\n")
        manifest.append(entry)
    return manifest


def _summary_report_paths(example: str, summary: Mapping[str, Any], output_dir: Path) -> List[Path]:
    if example == "026":
        values = summary.get("reports")
        if not isinstance(values, list):
            return []
    else:
        value = summary.get("report")
        values = [] if not isinstance(value, str) or not value else [value]
    paths = []
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        path = Path(value)
        if not path.is_absolute():
            path = output_dir / path
        paths.append(path.resolve())
    return paths


def _csv_stats(path: Path) -> Dict[str, Any]:
    """Read CSV shape and count finite numeric values without retaining all rows."""
    rows = 0
    finite_values: Dict[str, int] = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = reader.fieldnames or []
            finite_values = dict.fromkeys(headers, 0)
            for row in reader:
                rows += 1
                for header in headers:
                    value = row.get(header)
                    try:
                        is_finite = math.isfinite(float(value))
                    except (TypeError, ValueError):
                        is_finite = False
                    if is_finite:
                        finite_values[header] += 1
    except (OSError, UnicodeError, csv.Error) as exc:
        return {
            "path": str(path),
            "exists": path.is_file(),
            "rows": 0,
            "headers": [],
            "finite_values": {},
            "error": "%s: %s" % (type(exc).__name__, exc),
        }
    return {
        "path": str(path),
        "exists": True,
        "rows": rows,
        "headers": headers,
        "finite_values": finite_values,
        "error": None,
    }


def _finite_columns_present(stats: Mapping[str, Any], columns: Sequence[str]) -> bool:
    finite_values = stats.get("finite_values", {})
    return all(
        column in stats.get("headers", [])
        and isinstance(finite_values.get(column), int)
        and finite_values[column] > 0
        for column in columns
    )


def _validate_run(
    example: str,
    summary: Optional[Mapping[str, Any]],
    returncode: Optional[int],
    output_dir: Path,
    save_mode: Optional[str] = None,
    requested_symbols: Optional[int] = None,
    charts_enabled: bool = True,
) -> Dict[str, Any]:
    problems = []
    evaluation = {
        "requested": example in ("025", "026"),
        "applicable": example in ("025", "026"),
        "status": "NOT_APPLICABLE" if example == "027" else "MISSING",
    }
    if returncode is None:
        problems.append("run.py process did not start or return an exit status")
    elif returncode != 0:
        problems.append("run.py exited with status %d" % returncode)
    if summary is None:
        problems.append("summary.json is missing or invalid")
    else:
        if summary.get("status") != "COMPLETED":
            problems.append("summary status is %r" % summary.get("status"))
        effective_symbols = summary.get("symbols")
        if (
            isinstance(effective_symbols, bool)
            or not isinstance(effective_symbols, int)
            or effective_symbols < 1
        ):
            problems.append("summary symbols is missing or invalid")
        elif requested_symbols is not None and effective_symbols < requested_symbols:
            problems.append(
                "insufficient input symbols: requested %d, effective %d"
                % (requested_symbols, effective_symbols)
            )
        if example in ("025", "026"):
            status = str(summary.get("evaluation_status", "MISSING")).upper()
            evaluation["status"] = status
            if status != "OK":
                problems.append("evaluation status is %s, expected OK" % status)

    sample_count = {
        "requested": requested_symbols,
        "effective": summary.get("symbols") if summary is not None else None,
        "reported_dates": summary.get("dates") if summary is not None else None,
        "factor_value_rows": None,
        "status": "MISSING",
    }
    if summary is not None:
        effective_symbols = summary.get("symbols")
        if isinstance(effective_symbols, int) and not isinstance(effective_symbols, bool):
            if requested_symbols is None or effective_symbols >= requested_symbols:
                sample_count["status"] = "OK"
            else:
                sample_count["status"] = "INSUFFICIENT"
        elif effective_symbols is not None:
            sample_count["status"] = "INVALID"

    orders: Dict[str, Any] = {
        "applicable": example in ("025", "026"),
        "status": "NOT_APPLICABLE" if example == "027" else "MISSING",
    }
    if summary is not None and example in ("025", "026"):
        broker = summary.get("broker")
        if not isinstance(broker, Mapping):
            problems.append("summary broker order counts are missing or invalid")
        else:
            submit = broker.get("submit")
            cancel = broker.get("cancel")
            orders.update({"submit": submit, "cancel": cancel})
            if any(
                isinstance(count, bool) or not isinstance(count, int) or count < 0
                for count in (submit, cancel)
            ):
                orders["status"] = "INVALID"
                problems.append("summary broker order counts are missing or invalid")
            elif submit != 0 or cancel != 0:
                orders["status"] = "FAILED"
                problems.append(
                    "unexpected broker activity: submit=%d cancel=%d" % (submit, cancel)
                )
            else:
                orders["status"] = "OK"
    elif summary is not None and example == "027" and isinstance(summary.get("broker"), Mapping):
        broker = summary["broker"]
        orders.update({"submit": broker.get("submit"), "cancel": broker.get("cancel")})
        if broker.get("submit") != 0 or broker.get("cancel") != 0:
            orders["applicable"] = True
            orders["status"] = "FAILED"
            problems.append("unexpected broker activity in 027 summary")

    expected_csv = output_dir / "factor_values.csv"
    csv_exists = expected_csv.is_file() and expected_csv.stat().st_size > 0
    factor_stats = _csv_stats(expected_csv) if csv_exists else {
        "path": str(expected_csv), "exists": False, "rows": 0, "headers": [],
        "finite_values": {}, "error": "CSV is missing or empty",
    }
    if not csv_exists or factor_stats["rows"] < 1:
        problems.append("factor_values.csv is missing or empty")
    missing_factors = [
        factor
        for factor in EXPECTED_FACTORS[example]
        if factor not in factor_stats["headers"]
    ]
    empty_factors = [
        factor
        for factor in EXPECTED_FACTORS[example]
        if factor in factor_stats["headers"]
        and factor_stats["finite_values"].get(factor, 0) < 1
    ]
    if missing_factors:
        problems.append("factor_values.csv is missing factor columns: %s" % missing_factors)
    if empty_factors:
        problems.append("factor_values.csv has no finite values for factors: %s" % empty_factors)
    sample_count["factor_value_rows"] = factor_stats["rows"]
    if summary is not None:
        reported_dates = summary.get("dates")
        effective_symbols = summary.get("symbols")
        if (
            isinstance(reported_dates, bool)
            or not isinstance(reported_dates, int)
            or reported_dates < 1
        ):
            problems.append("summary dates is missing or invalid")
        elif (
            isinstance(effective_symbols, int)
            and not isinstance(effective_symbols, bool)
            and factor_stats["rows"] != effective_symbols * reported_dates
        ):
            problems.append(
                "factor_values.csv row count does not match summary symbols x dates: %d != %d x %d"
                % (factor_stats["rows"], effective_symbols, reported_dates)
            )
        if example == "027":
            reported_cells = summary.get("cells")
            reported_finite = summary.get("finite")
            factor_finite = factor_stats["finite_values"].get("alpha003", 0)
            if (
                isinstance(reported_cells, bool)
                or not isinstance(reported_cells, int)
                or reported_cells != factor_stats["rows"]
            ):
                problems.append("027 summary cells does not match factor_values.csv rows")
            if (
                isinstance(reported_finite, bool)
                or not isinstance(reported_finite, int)
                or reported_finite != factor_finite
            ):
                problems.append(
                    "027 summary finite does not match factor_values.csv finite factor values"
                )

    evaluation_results: Dict[str, Any] = {
        "status": "NOT_APPLICABLE" if example == "027" else "MISSING",
        "evaluation_id": None,
        "tables": {},
    }
    charts: Dict[str, Any] = {
        "requested": example in ("025", "026") and charts_enabled,
        "applicable": example in ("025", "026"),
        "status": "NOT_APPLICABLE" if example == "027" else "MISSING",
        "expected": [],
        "actual": [],
        "files": [],
    }
    if summary is not None and example in ("025", "026"):
        evaluation_id = summary.get("evaluation_id")
        evaluation_results["evaluation_id"] = evaluation_id
        evaluation_dir = output_dir / "evaluation" / str(evaluation_id)
        evaluation_results["path"] = str(evaluation_dir)
        if not isinstance(evaluation_id, str) or not evaluation_id:
            problems.append("summary evaluation_id is missing or invalid")
        elif not _path_inside(evaluation_dir, output_dir):
            problems.append("evaluation output resolves outside the run output")
        else:
            evaluation_manifest = evaluation_dir / "manifest.json"
            if not evaluation_manifest.is_file() or evaluation_manifest.stat().st_size < 1:
                problems.append("evaluation manifest is missing or empty")
                export_manifest: Optional[Mapping[str, Any]] = None
            else:
                try:
                    loaded_manifest = json.loads(
                        evaluation_manifest.read_text(encoding="utf-8")
                    )
                    export_manifest = (
                        loaded_manifest if isinstance(loaded_manifest, Mapping) else None
                    )
                except (OSError, ValueError) as exc:
                    export_manifest = None
                    problems.append(
                        "evaluation manifest is invalid: %s: %s"
                        % (type(exc).__name__, exc)
                    )
            exports = None if export_manifest is None else export_manifest.get("exports")
            if not isinstance(exports, list) or any(not isinstance(item, str) for item in exports):
                problems.append("evaluation manifest exports list is missing or invalid")
                exports = []
            expected_pngs = []
            for export in exports:
                relative = Path(export)
                if relative.is_absolute() or ".." in relative.parts:
                    problems.append("evaluation manifest contains an unsafe export path")
                    continue
                if relative.suffix.lower() == ".png":
                    expected_pngs.append(relative.as_posix())
            actual_pngs = sorted(
                path.relative_to(evaluation_dir).as_posix()
                for path in evaluation_dir.rglob("*")
                if path.is_file() and path.suffix.lower() == ".png"
            )
            charts.update(
                {
                    "expected": sorted(expected_pngs),
                    "actual": actual_pngs,
                }
            )
            if charts_enabled:
                if not expected_pngs:
                    problems.append("evaluation export manifest declares no PNG charts")
                if sorted(expected_pngs) != actual_pngs:
                    problems.append(
                        "evaluation PNG set does not match manifest exports: expected=%s actual=%s"
                        % (sorted(expected_pngs), actual_pngs)
                    )
                for relative_path in sorted(expected_pngs):
                    png_path = evaluation_dir / relative_path
                    inside = _path_inside(png_path, evaluation_dir)
                    exists_nonempty = png_path.is_file() and png_path.stat().st_size > 0
                    chart_file = {
                        "path": str(png_path),
                        "manifest_path": relative_path,
                        "exists_nonempty": exists_nonempty,
                        "inside_evaluation_dir": inside,
                        "size_bytes": png_path.stat().st_size if png_path.is_file() else 0,
                        "sha256": _sha256(png_path) if png_path.is_file() else None,
                    }
                    charts["files"].append(chart_file)
                    if not exists_nonempty or not inside:
                        problems.append(
                            "evaluation PNG is missing, empty, or outside the export directory: %s"
                            % relative_path
                        )
                charts["status"] = (
                    "OK"
                    if expected_pngs
                    and sorted(expected_pngs) == actual_pngs
                    and all(item["exists_nonempty"] and item["inside_evaluation_dir"] for item in charts["files"])
                    else "FAILED"
                )
            else:
                if expected_pngs or actual_pngs:
                    problems.append("no-charts diagnostic unexpectedly exported PNG charts")
                charts["status"] = "NOT_REQUESTED" if not expected_pngs and not actual_pngs else "FAILED"
            for table_name in REQUIRED_EVALUATION_TABLES:
                table_path = evaluation_dir / table_name
                stats = _csv_stats(table_path) if table_path.is_file() else {
                    "path": str(table_path), "exists": False, "rows": 0,
                    "headers": [], "finite_values": {},
                    "error": "CSV is missing",
                }
                evaluation_results["tables"][table_name] = stats
                if not stats["exists"] or stats["error"]:
                    problems.append("evaluation table is missing or unreadable: %s" % table_name)
                elif stats["rows"] < 1:
                    problems.append("evaluation table has no records: %s" % table_name)
            finite_evaluation_values = {
                "labels.csv": ("value",),
                "ic.csv": ("ic", "rank_ic"),
                "signals.csv": ("value",),
            }
            for table_name, columns in finite_evaluation_values.items():
                stats = evaluation_results["tables"].get(table_name, {})
                if not any(
                    _finite_columns_present(stats, (column,)) for column in columns
                ):
                    problems.append(
                        "evaluation table has no finite values in %s: %s"
                        % (columns, table_name)
                    )
        evaluation_results["status"] = (
            "OK"
            if not any(
                "evaluation" in problem or "factor_values.csv" in problem
                for problem in problems
            )
            and evaluation.get("status") == "OK"
            else "FAILED"
        )
        evaluation_results["charts"] = charts

    saved_data_artifact: Dict[str, Any] = {"mode": save_mode}
    panel_files: List[str] = []
    if example in ("025", "026"):
        if save_mode == "legacy_research_dataset":
            saved_path = output_dir / "dataset"
            saved_files = _artifact_manifest(saved_path)
            saved_data_artifact.update(
                {
                    "api": "--save-dataset",
                    "path": str(saved_path),
                    "format": "legacy ResearchDataset bundle",
                    "schema_note": "legacy dataset schema and identity are retained; output differs from current FactorPanel CSV by design",
                    "files": saved_files,
                    "inside_output_dir": _path_inside(saved_path, output_dir),
                }
            )
            if not saved_files:
                problems.append("legacy saved dataset is missing or empty")
            if not saved_data_artifact["inside_output_dir"]:
                problems.append("legacy saved dataset resolves outside the run output")
        elif save_mode == "factor_panel_csv":
            panel_dir = output_dir / "panel"
            saved_files = _artifact_manifest(panel_dir)
            panel_files = [
                str(panel_dir / item["path"])
                for item in saved_files
                if item["path"].lower().endswith(".csv") and item["size_bytes"] > 0
            ]
            saved_data_artifact.update(
                {
                    "api": "--save-panel",
                    "path": str(panel_dir),
                    "format": "current FactorPanel CSV bundle",
                    "schema_note": "current panel CSV schema; legacy identity fields are not retained as part of the planned structural change",
                    "files": saved_files,
                    "inside_output_dir": _path_inside(panel_dir, output_dir),
                }
            )
            if not panel_files:
                problems.append("saved panel has no non-empty CSV files")
            panel_csv_paths = sorted(
                item["path"]
                for item in saved_files
                if item["path"].lower().endswith(".csv")
            )
            nonempty_panel_csv_paths = sorted(
                item["path"]
                for item in saved_files
                if item["path"].lower().endswith(".csv") and item["size_bytes"] > 0
            )
            expected_panel_paths = sorted(EXPECTED_PANEL_CSVS)
            panel_csv_contract = {
                "expected": expected_panel_paths,
                "actual": panel_csv_paths,
                "nonempty": nonempty_panel_csv_paths,
                "exact_match": (
                    panel_csv_paths == expected_panel_paths
                    and nonempty_panel_csv_paths == expected_panel_paths
                ),
            }
            saved_data_artifact["csv_contract"] = panel_csv_contract
            if not panel_csv_contract["exact_match"]:
                problems.append(
                    "saved panel CSV set differs from the exact non-empty six-file contract: missing=%s empty=%s extra=%s"
                    % (
                        sorted(set(expected_panel_paths) - set(nonempty_panel_csv_paths)),
                        sorted(set(panel_csv_paths) - set(nonempty_panel_csv_paths)),
                        sorted(set(panel_csv_paths) - set(expected_panel_paths)),
                    )
                )
            if not saved_data_artifact["inside_output_dir"]:
                problems.append("saved panel resolves outside the run output")
        else:
            panel_files = []
            problems.append("saved panel API was not identified")
    else:
        panel_files = []
        saved_data_artifact.update(
            {
                "api": "factor_values.csv",
                "path": str(expected_csv),
                "format": "factor value CSV",
                "files": _artifact_manifest(expected_csv),
            }
        )

    reports = []
    if summary is not None:
        reports = _summary_report_paths(example, summary, output_dir)
    expected_reports = [
        (output_dir / ("factor_report_%s.html" % factor)).resolve()
        for factor in EXPECTED_FACTORS[example]
    ]
    if len(reports) != len(expected_reports):
        problems.append(
            "summary references %d reports; expected %d"
            % (len(reports), len(expected_reports))
        )
    report_artifacts = []
    for expected in expected_reports:
        exists = expected.is_file() and expected.stat().st_size > 0
        referenced = expected in reports
        inside = _path_inside(expected, output_dir)
        report_artifacts.append(
            {
                "path": str(expected),
                "exists_nonempty": exists,
                "referenced_by_summary": referenced,
                "inside_output_dir": inside,
                "size_bytes": expected.stat().st_size if expected.is_file() else 0,
                "sha256": _sha256(expected) if expected.is_file() else None,
            }
        )
        if not exists or not referenced or not inside:
            problems.append("report is missing, empty, unreferenced, or outside output: %s" % expected)

    return {
        "status": "OK" if not problems else "FAILED",
        "problems": problems,
        "evaluation": evaluation,
        "charts": charts,
        "sample_count": sample_count,
        "orders": orders,
        "evaluation_results": evaluation_results,
        "factor_values_csv": {
            **factor_stats,
            "exists_nonempty": csv_exists,
            "expected_factors": list(EXPECTED_FACTORS[example]),
            "finite_factors": {
                factor: factor_stats["finite_values"].get(factor, 0)
                for factor in EXPECTED_FACTORS[example]
            },
        },
        "saved_panel_csvs": panel_files,
        "saved_data_artifact": saved_data_artifact,
        "reports": report_artifacts,
    }


def _measure_process(
    command: Sequence[str],
    cwd: Path,
    interval_s: float,
    environment: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Capture subprocess wall/CPU and sampled RSS for its full process tree."""
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError("psutil is required for parent process-tree measurements") from exc

    cpu_by_pid: Dict[int, float] = {}
    samples = []
    peak_rss = 0
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout_file, tempfile.TemporaryFile(
        mode="w+t", encoding="utf-8"
    ) as stderr_file:
        started_at = dt.datetime.now(dt.timezone.utc).isoformat()
        started = time.perf_counter()
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            env=None if environment is None else dict(environment),
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
        )

        def sample() -> None:
            nonlocal peak_rss
            try:
                root = psutil.Process(process.pid)
                processes = [root] + root.children(recursive=True)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                processes = []
            rss_total = 0
            cpu_total = 0.0
            pids = []
            for item in processes:
                try:
                    rss = int(item.memory_info().rss)
                    cpu_times = item.cpu_times()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                cpu = float(cpu_times.user + cpu_times.system)
                rss_total += rss
                cpu_total += cpu
                pids.append(item.pid)
                cpu_by_pid[item.pid] = max(cpu_by_pid.get(item.pid, 0.0), cpu)
            peak_rss = max(peak_rss, rss_total)
            samples.append(
                {
                    "elapsed_s": time.perf_counter() - started,
                    "rss_tree_bytes": rss_total,
                    "cpu_tree_s": cpu_total,
                    "pids": pids,
                }
            )

        while process.poll() is None:
            sample()
            time.sleep(interval_s)
        sample()
        returncode = process.wait()
        wall_s = time.perf_counter() - started
        ended_at = dt.datetime.now(dt.timezone.utc).isoformat()
        stdout_file.seek(0)
        stderr_file.seek(0)
        return {
            "started_at_utc": started_at,
            "ended_at_utc": ended_at,
            "returncode": returncode,
            "wall_s": wall_s,
            "cpu_tree_s": sum(cpu_by_pid.values()),
            "peak_rss_tree_bytes": peak_rss,
            "sample_interval_s": interval_s,
            "samples": samples,
            "stdout": stdout_file.read(),
            "stderr": stderr_file.read(),
        }


def _run_case(
    *,
    side: str,
    root: Path,
    example: str,
    output_dir: Path,
    data_dir: Path,
    symbols: int,
    interval_s: float,
    kind: str,
    group: Optional[int],
    entrypoint: Mapping[str, Any],
    module_origins: Mapping[str, Any],
    charts_enabled: bool = True,
) -> Dict[str, Any]:
    save_mode = str(entrypoint["save_mode"])
    command = _build_command(
        root, example, output_dir, data_dir, symbols, save_mode, no_charts=not charts_enabled
    )
    output_contract = {
        "save_mode": save_mode,
        "evaluation_charts": "enabled" if charts_enabled and example in ("025", "026") else (
            "disabled_diagnostic" if example in ("025", "026") else "not_applicable"
        ),
        "chart_validation_source": (
            "fincore evaluation manifest exports"
            if example in ("025", "026")
            else "not_applicable"
        ),
        "artifact_path": "dataset" if save_mode == "legacy_research_dataset" else (
            "panel" if save_mode == "factor_panel_csv" else "factor_values.csv"
        ),
        "contract_change_note": (
            "legacy ResearchDataset serialization and current FactorPanel CSV serialization have different schemas and identity retention by design; timing is end-to-end and does not isolate serialization"
            if save_mode in ("legacy_research_dataset", "factor_panel_csv")
            else "027 emits its existing factor_values.csv without a saved panel option"
        ),
    }
    result: Dict[str, Any] = {
        "side": side,
        "example": example,
        "kind": kind,
        "group": group,
        "requested_symbols": symbols,
        "output_dir": str(output_dir),
        "command": command,
        "python_executable": sys.executable,
        "pythonpath": str(root.resolve()),
        "entrypoint_api": dict(entrypoint),
        "expected_module_origins": dict(module_origins),
        "module_import_binding": "run.py executes with PYTHONPATH set to this side's source root and no inherited PYTHONPATH",
        "output_contract": output_contract,
    }
    try:
        measured = _measure_process(
            command, root, interval_s, environment=_process_environment(root)
        )
        result.update(
            {
                "started_at_utc": measured["started_at_utc"],
                "ended_at_utc": measured["ended_at_utc"],
                "returncode": measured["returncode"],
                "wall_s": measured["wall_s"],
                "cpu_tree_s": measured["cpu_tree_s"],
                "peak_rss_tree_bytes": measured["peak_rss_tree_bytes"],
                "sample_interval_s": measured["sample_interval_s"],
                "process_samples": measured["samples"],
                "stdout_tail": measured["stdout"][-3000:],
                "stderr_tail": measured["stderr"][-3000:],
            }
        )
    except Exception as exc:
        result.update(
            {
                "returncode": None,
                "wall_s": None,
                "cpu_tree_s": None,
                "peak_rss_tree_bytes": None,
                "harness_error": "%s: %s" % (type(exc).__name__, exc),
            }
        )

    summary_path = output_dir / "summary.json"
    summary = None
    summary_error = None
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            summary_error = "%s: %s" % (type(exc).__name__, exc)
    else:
        summary_error = "summary.json is missing"
    result["summary_path"] = str(summary_path)
    result["summary_sha256"] = _sha256(summary_path) if summary_path.is_file() else None
    result["summary"] = summary
    result["effective_symbols"] = summary.get("symbols") if summary is not None else None
    result["summary_error"] = summary_error
    validation = _validate_run(
        example,
        summary,
        result.get("returncode"),
        output_dir,
        save_mode=save_mode,
        requested_symbols=symbols,
        charts_enabled=charts_enabled,
    )
    if result.get("harness_error"):
        validation["status"] = "FAILED"
        validation["problems"].append(result["harness_error"])
    if summary_error and summary_error not in validation["problems"]:
        validation["problems"].append(summary_error)
        validation["status"] = "FAILED"
    result["validation"] = validation
    output_files = _artifact_manifest(output_dir)
    result["output_files"] = output_files
    result["output_files_sha256"] = _canonical_hash(output_files)
    return result


def _run_dir(output: Path, example: str, kind: str, side: str, group: Optional[int]) -> Path:
    suffix = "warmup" if group is None else "group-%02d" % group
    directory = output / "runs" / example / suffix / (kind + "-" + side)
    directory.parent.mkdir(parents=True, exist_ok=True)
    if directory.exists():
        raise FileExistsError("run output directory already exists: %s" % directory)
    return directory


def _alternating_order(group: int) -> Tuple[str, str]:
    if group % 2:
        return "baseline", "candidate"
    return "candidate", "baseline"


def _median_stats(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    metrics = ("wall_s", "cpu_tree_s", "peak_rss_tree_bytes")
    return {
        metric: statistics.median(
            float(item[metric]) for item in records if isinstance(item.get(metric), (int, float))
        )
        for metric in metrics
    }


def _sample_scope(requested_symbols: int, no_charts: bool = False) -> Dict[str, Any]:
    symbol_floor_met = requested_symbols >= FORMAL_MINIMUM_SYMBOLS
    formal = symbol_floor_met and not no_charts
    run_status = "OK" if formal else "DIAGNOSTIC_ONLY" if no_charts else "SMOKE_ONLY"
    scope_status = (
        "FORMAL_SCOPE_MET"
        if formal
        else "DIAGNOSTIC_NO_CHARTS"
        if no_charts
        else "INSUFFICIENT_FOR_FORMAL_SAMPLE_FLOOR"
    )
    return {
        "run_status": run_status,
        "status": scope_status,
        "requested_symbols": requested_symbols,
        "formal_minimum_symbols": FORMAL_MINIMUM_SYMBOLS,
        "formal_sample_floor_met": symbol_floor_met,
        "formal_eligible": formal,
        "charts_enabled": not no_charts,
        "note": (
            "Harness checks passed at or above the formal symbol-count floor; performance acceptance is assessed separately."
            if formal
            else "This no-charts run is diagnostic only and cannot be formal benchmark evidence."
            if no_charts
            else "All process/output checks passed, but this reduced-symbol run is not formal benchmark evidence."
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", required=True, help="frozen source checkout")
    parser.add_argument("--candidate-root", required=True, help="candidate source checkout")
    parser.add_argument("--baseline-revision", help="revision represented by a source archive")
    parser.add_argument("--candidate-revision", help="revision represented by a source archive")
    parser.add_argument("--data-dir", required=True, help="fixed input data directory")
    parser.add_argument("--output", required=True, help="new evidence directory")
    parser.add_argument(
        "--symbols",
        type=int,
        default=FORMAL_MINIMUM_SYMBOLS,
        help="requested symbols (default 500; values below 500 are smoke-only)",
    )
    parser.add_argument(
        "--no-charts",
        action="store_true",
        help="disable 025/026 evaluation PNGs for diagnostics only; result cannot be formal",
    )
    parser.add_argument("--groups", type=int, default=3)
    parser.add_argument("--sample-interval", type=float, default=0.05)
    parser.add_argument(
        "--allow-config-difference",
        action="append",
        choices=sorted(CONFIG_DIFFERENCE_ALLOWLIST),
        default=[],
        help="approve only the documented exact migration for this input field",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    output = Path(args.output).expanduser().resolve()
    payload: Dict[str, Any] = {
        "schema_version": "factor-research-paired-benchmark-v1",
        "status": "FAILED",
        "command": list(sys.argv if argv is None else [sys.argv[0]] + list(argv)),
        "parameters": {
            "examples": list(EXAMPLES),
            "symbols": args.symbols,
            "formal_minimum_symbols": FORMAL_MINIMUM_SYMBOLS,
            "groups": args.groups,
            "warmups_per_side_example": 1,
            "report": True,
            "save_panel_examples": ["025", "026"],
            "charts_enabled": not args.no_charts,
            "chart_examples": ["025", "026"],
            "no_charts_diagnostic": args.no_charts,
            "sample_interval_s": args.sample_interval,
            "python_executable": sys.executable,
            "allow_config_differences": list(args.allow_config_difference),
        },
        "runs": [],
    }
    created_output = False
    try:
        if args.symbols < 1:
            raise ValueError("--symbols must be positive")
        if args.groups < 3:
            raise ValueError("--groups must be at least 3")
        if args.sample_interval <= 0:
            raise ValueError("--sample-interval must be positive")
        if output.exists():
            raise FileExistsError("output directory already exists: %s" % output)
        output.mkdir(parents=True)
        created_output = True
        roots = {
            "baseline": Path(args.baseline_root).expanduser().resolve(),
            "candidate": Path(args.candidate_root).expanduser().resolve(),
        }
        revisions = {
            "baseline": args.baseline_revision,
            "candidate": args.candidate_revision,
        }
        data_dir = Path(args.data_dir).expanduser().resolve()
        manifest_path = data_dir / "_metadata" / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError("data manifest not found: %s" % manifest_path)
        payload["input"] = {
            "data_dir": str(data_dir),
            "manifest_path": str(manifest_path),
            "manifest_sha256": _sha256(manifest_path),
            "manifest_size_bytes": manifest_path.stat().st_size,
        }
        execution_environment = _dependency_snapshot()
        payload["execution_environment"] = execution_environment
        sides = {
            name: _inspect_side(
                root, name, data_dir, args.symbols, revisions[name], execution_environment
            )
            for name, root in roots.items()
        }
        payload["sides"] = sides
        if args.no_charts:
            unsupported = [
                "%s:%s" % (side, example)
                for side, metadata in sides.items()
                for example in ("025", "026")
                if not metadata["entrypoints"][example]["options"]["--no-charts"]
            ]
            if unsupported:
                raise RuntimeError("no-charts diagnostic is unsupported by entrypoints: %s" % unsupported)
        payload["output_contract_comparison"] = {
            "shared_outputs": [
                "factor_values.csv",
                "summary.json",
                "factor_report_*.html",
                "evaluation export files generated by each example",
            ],
            "save_api_by_side": {
                side: {
                    example: sides[side]["entrypoints"][example]["save_mode"]
                    for example in EXAMPLES
                }
                for side in sides
            },
            "planned_025_026_difference": "baseline uses --save-dataset and retains the legacy ResearchDataset schema/identity in dataset/; candidate uses --save-panel and writes the current FactorPanel CSV schema to panel/",
            "comparison_limit": "the saved data purpose is shared, while storage schema and identity retention intentionally differ; process wall is end-to-end and does not isolate serialization",
            "preserve_report_and_evaluation_outputs": True,
            "evaluation_chart_contract": "default 025/026 run exports every PNG named in fincore evaluation manifest.exports; each must be present and non-empty; --no-charts is explicit diagnostic-only mode",
        }
        for name, metadata in sides.items():
            if not metadata["source_revision"]:
                raise ValueError(
                    "%s has no git HEAD; pass --%s-revision for its source archive"
                    % (name, name)
                )
        differences = {
            example: _config_differences(
                sides["baseline"]["effective_configs"][example],
                sides["candidate"]["effective_configs"][example],
            )
            for example in EXAMPLES
        }
        payload["input_configuration_comparison"] = {
            "equal": not any(differences.values()),
            "differences": differences,
            **_classify_config_differences(differences, args.allow_config_difference),
        }
        if not payload["input_configuration_comparison"]["compatible"]:
            raise ValueError(
                "effective input configuration has unapproved differences: %s"
                % json.dumps(
                    payload["input_configuration_comparison"]["unapproved_differences"],
                    ensure_ascii=False,
                )
            )
        for side, metadata in sides.items():
            probe = metadata["module_probe"]
            if probe.get("returncode") != 0 or "modules" not in probe:
                raise RuntimeError("%s module source probe failed" % side)
            modules = probe["modules"]
            for module_name in ("backtrader", "research"):
                module_path = Path(modules[module_name])
                if not _path_inside(module_path, roots[side]):
                    raise RuntimeError(
                        "%s %s imported outside its checkout: %s"
                        % (side, module_name, module_path)
                    )

        # Full-size warmups use fresh interpreters and the same inputs/options.
        for example in EXAMPLES:
            for side in _alternating_order(EXAMPLES.index(example) + 1):
                run_dir = _run_dir(output, example, "warmup", side, None)
                record = _run_case(
                    side=side,
                    root=roots[side],
                    example=example,
                    output_dir=run_dir,
                    data_dir=data_dir,
                    symbols=args.symbols,
                    interval_s=args.sample_interval,
                    kind="warmup",
                    group=None,
                    entrypoint=sides[side]["entrypoints"][example],
                    module_origins=sides[side]["module_probe"]["modules"],
                    charts_enabled=not args.no_charts,
                )
                payload["runs"].append(record)
                if record["validation"]["status"] != "OK":
                    raise RuntimeError(
                        "%s %s warmup failed: %s"
                        % (side, example, "; ".join(record["validation"]["problems"]))
                    )

        for group in range(1, args.groups + 1):
            for example in EXAMPLES:
                for side in _alternating_order(group):
                    run_dir = _run_dir(output, example, "measured", side, group)
                    record = _run_case(
                        side=side,
                        root=roots[side],
                        example=example,
                        output_dir=run_dir,
                        data_dir=data_dir,
                        symbols=args.symbols,
                        interval_s=args.sample_interval,
                        kind="measured",
                        group=group,
                        entrypoint=sides[side]["entrypoints"][example],
                        module_origins=sides[side]["module_probe"]["modules"],
                        charts_enabled=not args.no_charts,
                    )
                    payload["runs"].append(record)

        hashes_after = {name: _source_manifest(root) for name, root in roots.items()}
        payload["source_hashes_after"] = hashes_after
        payload["source_hash_drift"] = {
            name: {
                path: [digest, hashes_after[name].get(path)]
                for path, digest in sides[name]["source_hashes"].items()
                if hashes_after[name].get(path) != digest
            }
            for name in roots
        }
        if any(payload["source_hash_drift"].values()):
            raise RuntimeError("source hashes changed during benchmark")

        metrics = {}
        for example in EXAMPLES:
            metrics[example] = {}
            for side in roots:
                records = [
                    record
                    for record in payload["runs"]
                    if record["kind"] == "measured"
                    and record["example"] == example
                    and record["side"] == side
                ]
                metrics[example][side] = _median_stats(records)
            metrics[example]["candidate_over_baseline"] = {
                metric: (
                    metrics[example]["candidate"][metric]
                    / metrics[example]["baseline"][metric]
                    if metrics[example]["baseline"][metric]
                    else None
                )
                for metric in ("wall_s", "cpu_tree_s", "peak_rss_tree_bytes")
            }
        payload["summary_stats"] = metrics
        failures = [
            record
            for record in payload["runs"]
            if record.get("validation", {}).get("status") != "OK"
        ]
        if failures:
            raise RuntimeError("one or more measured runs failed validation")
        payload["sample_scope"] = _sample_scope(args.symbols, no_charts=args.no_charts)
        payload["status"] = payload["sample_scope"]["run_status"]
    except Exception as exc:
        payload["error"] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        if created_output and output.is_dir():
            result_path = output / "benchmark.json"
            result_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print("results: %s" % result_path)
    return 0 if payload["status"] in ("OK", "SMOKE_ONLY") else 1


if __name__ == "__main__":
    raise SystemExit(main())
