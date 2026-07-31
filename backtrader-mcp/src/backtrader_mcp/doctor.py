"""Read-only installation, configuration, and Backtrader runtime diagnostics."""

from __future__ import annotations

import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from . import __version__
from .data import INPUT_FORMAT_ADAPTERS
from .jobs import RUN_PROFILES
from .settings import Settings

_RUNTIME_PROBE = """
import json
from pathlib import Path
import backtrader

print(json.dumps({
    "module_file": str(Path(backtrader.__file__).resolve()),
    "version": str(getattr(backtrader, "__version__", "unknown")),
    "capabilities": {
        "cerebro": hasattr(backtrader, "Cerebro"),
        "strategy": hasattr(backtrader, "Strategy"),
        "generic_csv": hasattr(backtrader.feeds, "GenericCSVData"),
        "pandas_data": hasattr(backtrader.feeds, "PandasData"),
    },
}, sort_keys=True))
""".strip()


def _version_pair(value: str) -> tuple[int, int] | None:
    match = re.match(r"^(\d+)\.(\d+)", value)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _distribution(name: str, compatible: bool) -> dict[str, Any]:
    try:
        version = metadata.version(name)
    except metadata.PackageNotFoundError:
        return {"installed": False, "version": None, "compatible": False}
    return {"installed": True, "version": version, "compatible": compatible}


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _root_report(root_id: str, path: Path, role: str) -> dict[str, Any]:
    exists = path.exists()
    is_directory = path.is_dir() if exists else False
    parent = _nearest_existing_parent(path)
    readable = exists and is_directory and os.access(path, os.R_OK | os.X_OK)
    writable = (
        os.access(path, os.W_OK | os.X_OK)
        if exists and is_directory
        else parent.is_dir() and os.access(parent, os.W_OK | os.X_OK)
    )
    return {
        "root_id": root_id,
        "role": role,
        "path": str(path),
        "exists": exists,
        "is_directory": is_directory,
        "readable": readable,
        "writable": writable,
        "will_create": not exists and role == "state",
    }


def _git_value(root: Path, *arguments: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else None


def _runtime_report(runtime_id: str, root: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    report: dict[str, Any] = {
        "runtime_id": runtime_id,
        "root": str(root),
        "exists": root.is_dir(),
        "package_marker": (root / "backtrader" / "__init__.py").is_file(),
        "module_file": None,
        "version": None,
        "commit": _git_value(root, "rev-parse", "HEAD"),
        "branch": _git_value(root, "rev-parse", "--abbrev-ref", "HEAD"),
        "capabilities": {},
        "status": "failed",
    }
    issues: list[dict[str, str]] = []
    if not report["exists"] or not report["package_marker"]:
        issues.append(
            {
                "code": "invalid_runtime_root",
                "severity": "error",
                "subject": runtime_id,
                "message": "runtime root must contain backtrader/__init__.py",
            }
        )
        return report, issues

    environment = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "PYTHONPATH": str(root),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    try:
        completed = subprocess.run(
            [sys.executable, "-B", "-c", _RUNTIME_PROBE],
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        issues.append(
            {
                "code": "runtime_probe_failed",
                "severity": "error",
                "subject": runtime_id,
                "message": f"runtime probe did not complete: {type(exc).__name__}",
            }
        )
        return report, issues
    try:
        probe = json.loads(completed.stdout)
    except json.JSONDecodeError:
        probe = {}
    if completed.returncode != 0 or not isinstance(probe, dict):
        issues.append(
            {
                "code": "runtime_import_failed",
                "severity": "error",
                "subject": runtime_id,
                "message": f"Backtrader import probe exited with status {completed.returncode}",
            }
        )
        return report, issues

    report.update(
        {
            "module_file": probe.get("module_file"),
            "version": probe.get("version"),
            "capabilities": probe.get("capabilities", {}),
        }
    )
    expected_package = (root / "backtrader").resolve()
    module_value = report["module_file"]
    try:
        origin_matches = isinstance(module_value, str) and Path(
            module_value
        ).resolve().is_relative_to(expected_package)
    except OSError:
        origin_matches = False
    report["origin_matches_runtime"] = origin_matches
    required_capabilities = report["capabilities"]
    capabilities_pass = isinstance(required_capabilities, dict) and all(
        required_capabilities.get(name) is True
        for name in ("cerebro", "strategy", "generic_csv", "pandas_data")
    )
    if not origin_matches:
        issues.append(
            {
                "code": "runtime_origin_mismatch",
                "severity": "error",
                "subject": runtime_id,
                "message": "imported Backtrader is outside the registered runtime root",
            }
        )
    if not capabilities_pass:
        issues.append(
            {
                "code": "runtime_capability_missing",
                "severity": "error",
                "subject": runtime_id,
                "message": "runtime is missing a required Cerebro, Strategy, or feed capability",
            }
        )
    if report["commit"] is None:
        issues.append(
            {
                "code": "runtime_commit_unavailable",
                "severity": "warning",
                "subject": runtime_id,
                "message": "runtime is not a Git checkout; commit provenance is unavailable",
            }
        )
    report["status"] = (
        "passed" if not any(issue["severity"] == "error" for issue in issues) else "failed"
    )
    return report, issues


def doctor_report(settings: Settings) -> dict[str, Any]:
    """Return a deterministic, read-only diagnostic report for one installation."""

    issues: list[dict[str, str]] = []
    try:
        mcp_version = metadata.version("mcp")
    except metadata.PackageNotFoundError:
        mcp_version = ""
    try:
        pandas_version = metadata.version("pandas")
    except metadata.PackageNotFoundError:
        pandas_version = ""
    mcp_pair = _version_pair(mcp_version)
    pandas_pair = _version_pair(pandas_version)
    dependencies = {
        "mcp": _distribution("mcp", mcp_pair == (2, 0)),
        "pandas": _distribution(
            "pandas",
            pandas_pair is not None
            and (pandas_pair[0] in {2, 3} or pandas_pair[0] == 1 and pandas_pair[1] >= 5),
        ),
    }
    if sys.version_info < (3, 10):
        issues.append(
            {
                "code": "unsupported_python",
                "severity": "error",
                "subject": "python",
                "message": "backtrader-mcp requires Python 3.10 or newer",
            }
        )
    for name, dependency in dependencies.items():
        if not dependency["compatible"]:
            issues.append(
                {
                    "code": "dependency_incompatible",
                    "severity": "error",
                    "subject": name,
                    "message": f"{name} is missing or outside the supported version range",
                }
            )

    state = _root_report("state", settings.state_root, "state")
    if (state["exists"] and not state["is_directory"]) or not state["writable"]:
        issues.append(
            {
                "code": "state_root_unwritable",
                "severity": "error",
                "subject": "state",
                "message": "state root is not a writable directory and cannot be created",
            }
        )

    source_roots = [
        _root_report(root_id, path, "source")
        for root_id, path in sorted(settings.source_roots.items())
    ]
    if not source_roots:
        issues.append(
            {
                "code": "source_roots_empty",
                "severity": "warning",
                "subject": "source_roots",
                "message": "no local dataset or source corpus root is registered",
            }
        )
    for root in source_roots:
        if not root["exists"] or not root["is_directory"] or not root["readable"]:
            issues.append(
                {
                    "code": "source_root_unreadable",
                    "severity": "error",
                    "subject": root["root_id"],
                    "message": "source root must be an existing readable directory",
                }
            )

    target_roots = [
        _root_report(root_id, path, "target")
        for root_id, path in sorted(settings.target_roots.items())
    ]
    if not target_roots:
        issues.append(
            {
                "code": "target_roots_empty",
                "severity": "error",
                "subject": "target_roots",
                "message": "at least one writable strategy target root is required",
            }
        )
    for root in target_roots:
        if not root["exists"] or not root["is_directory"] or not root["writable"]:
            issues.append(
                {
                    "code": "target_root_unwritable",
                    "severity": "error",
                    "subject": root["root_id"],
                    "message": "target root must be an existing writable directory",
                }
            )

    runtimes: list[dict[str, Any]] = []
    if not settings.runtimes:
        issues.append(
            {
                "code": "runtimes_empty",
                "severity": "error",
                "subject": "runtimes",
                "message": "at least one Backtrader source runtime is required",
            }
        )
    for runtime_id, root in sorted(settings.runtimes.items()):
        runtime, runtime_issues = _runtime_report(runtime_id, root)
        runtimes.append(runtime)
        issues.extend(runtime_issues)

    product_origin = Path(__file__).resolve().with_name("__init__.py")
    return {
        "schema_version": "backtrader-mcp-doctor-v1",
        "status": ("failed" if any(issue["severity"] == "error" for issue in issues) else "passed"),
        "product": {
            "name": "backtrader-mcp",
            "version": __version__,
            "module_file": str(product_origin),
            "python_executable": sys.executable,
            "python_version": ".".join(str(value) for value in sys.version_info[:3]),
            "dependencies": dependencies,
        },
        "roots": {
            "state": state,
            "sources": source_roots,
            "targets": target_roots,
        },
        "runtimes": runtimes,
        "capabilities": {
            "transport": "stdio",
            "offline_backtest_only": True,
            "tasks_extension": False,
            "run_profiles": sorted(RUN_PROFILES),
            "data_adapters": sorted(INPUT_FORMAT_ADAPTERS),
            "approval_channels": ["trusted_local_change", "trusted_local_run"],
        },
        "issues": issues,
    }
