"""Build, clean-install, and run the fixed fourteen-cell MCP acceptance matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SRC = (PRODUCT_ROOT / "src").resolve()
FIXED_TEST = PRODUCT_ROOT / "tests" / "test_acceptance_matrix.py"
FIXED_TEST_NODE = f"{FIXED_TEST}::test_structured_fourteen_cell_acceptance_matrix"


def _run(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _tail(process: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {
        "returncode": process.returncode,
        "stdout_tail": process.stdout[-2000:],
        "stderr_tail": process.stderr[-2000:],
    }


def _probe_installed(
    run_root: Path,
    environment: dict[str, str],
) -> tuple[dict[str, Any], subprocess.CompletedProcess[str]]:
    probe_code = """
import importlib.util
import json
import os
from pathlib import Path
import sys

import backtrader_mcp
from backtrader_mcp.audit import audit_independence

origin = Path(backtrader_mcp.__file__).resolve()
source_src = Path(os.environ["BACKTRADER_MCP_SOURCE_SRC"]).resolve()
resolved_paths = []
for value in sys.path:
    try:
        resolved_paths.append(str(Path(value or ".").resolve()))
    except OSError:
        resolved_paths.append(value)
print(json.dumps({
    "installed_origin": str(origin),
    "installed_package_root": str(origin.parent),
    "source_checkout_on_sys_path": str(source_src) in resolved_paths,
    "sys_path": resolved_paths,
    "sibling_checks": {
        "skills_absent": importlib.util.find_spec("backtrader_skills") is None,
        "agent_absent": importlib.util.find_spec("backtrader_agent") is None,
    },
    "independence": audit_independence(origin.parent),
}, sort_keys=True))
"""
    probe = _run(
        [sys.executable, "-c", probe_code],
        cwd=run_root,
        environment=environment,
    )
    if probe.returncode != 0:
        return {}, probe
    try:
        return json.loads(probe.stdout), probe
    except json.JSONDecodeError:
        return {}, probe


def _expected_matrix_passes(matrix_artifact: dict[str, Any]) -> bool:
    cells = matrix_artifact.get("cells")
    expected_pairs = {
        (archetype, profile)
        for archetype in (
            "single_data_indicator",
            "multi_indicator_system",
            "multi_asset_allocation",
            "multi_timeframe",
            "pairs_spread",
            "order_risk",
            "precomputed_ml",
        )
        for profile in ("single_test", "python_bundle")
    }
    required_stages = {
        "inspect",
        "register",
        "preview",
        "draft",
        "validate",
        "prepare_changes",
        "apply_changes",
        "prepare_run",
        "run",
        "compare",
    }
    observed_pairs = (
        {(cell.get("archetype"), cell.get("profile")) for cell in cells}
        if isinstance(cells, list)
        else set()
    )
    observed_formats = (
        {
            cell.get("dataset_profile", {}).get("input_format")
            for cell in cells
            if isinstance(cell, dict)
        }
        if isinstance(cells, list)
        else set()
    )
    execution = matrix_artifact.get("execution_environment", {})
    return (
        isinstance(cells, list)
        and len(cells) == 14
        and matrix_artifact.get("expected_cells") == 14
        and matrix_artifact.get("executed_cells") == 14
        and matrix_artifact.get("passed_cells") == 14
        and observed_pairs == expected_pairs
        and {
            "generic_csv",
            "backtrader_csv",
            "yahoo_csv",
            "mt5_csv",
            "pandas",
            "pandas_custom_lines",
        }
        <= observed_formats
        and all(
            cell.get("status") == "passed" and required_stages <= set(cell.get("stages", {}))
            for cell in cells
        )
        and execution.get("source_checkout_on_sys_path") is False
        and execution.get("origin_is_expected_installed_target") is True
        and execution.get("sibling_checks", {}).get("skills_absent") is True
        and execution.get("sibling_checks", {}).get("agent_absent") is True
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", choices=["all"], default="all")
    parser.add_argument("--require-no-skills", action="store_true")
    parser.add_argument("--require-no-agent", action="store_true")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="backtrader-mcp-wheel-acceptance-") as temporary:
        temporary_root = Path(temporary)
        wheel_root = temporary_root / "wheel"
        installed_target = temporary_root / "installed"
        run_root = temporary_root / "outside-workspace"
        wheel_root.mkdir()
        installed_target.mkdir()
        run_root.mkdir()
        build = _run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--disable-pip-version-check",
                "--no-deps",
                "--wheel-dir",
                str(wheel_root),
                str(PRODUCT_ROOT),
            ],
            cwd=run_root,
        )
        wheels = sorted(wheel_root.glob("backtrader_mcp-*.whl"))
        wheel = wheels[0] if build.returncode == 0 and len(wheels) == 1 else None
        install = (
            _run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-deps",
                    "--no-compile",
                    "--target",
                    str(installed_target),
                    str(wheel),
                ],
                cwd=run_root,
            )
            if wheel is not None
            else subprocess.CompletedProcess([], 1, "", "wheel build produced no unique artifact")
        )
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(installed_target)
        environment["BACKTRADER_MCP_SOURCE_SRC"] = str(SOURCE_SRC)
        environment["BACKTRADER_MCP_EXPECTED_INSTALLED_TARGET"] = str(installed_target.resolve())
        probe_data, probe = (
            _probe_installed(run_root, environment)
            if install.returncode == 0
            else ({}, subprocess.CompletedProcess([], 1, "", "wheel install failed"))
        )
        artifact_path = temporary_root / "matrix.json"
        environment["BACKTRADER_MCP_ACCEPTANCE_OUTPUT"] = str(artifact_path)
        matrix = (
            _run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    FIXED_TEST_NODE,
                    "-q",
                    "-p",
                    "no:cacheprovider",
                ],
                cwd=run_root,
                environment=environment,
            )
            if probe.returncode == 0
            else subprocess.CompletedProcess([], 1, "", "installed-package probe failed")
        )
        try:
            matrix_artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            artifact_error = None
        except (OSError, json.JSONDecodeError) as exc:
            matrix_artifact = {}
            artifact_error = f"{type(exc).__name__}: {exc}"

        wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest() if wheel is not None else None
        expected_origin_root = installed_target.resolve()
        installed_origin = probe_data.get("installed_origin")
        origin_is_installed = isinstance(installed_origin, str) and Path(
            installed_origin
        ).is_relative_to(expected_origin_root)
        source_checkout_on_sys_path = probe_data.get("source_checkout_on_sys_path")
        matrix_execution = matrix_artifact.get("execution_environment", {})
        installed_execution_passed = (
            origin_is_installed
            and source_checkout_on_sys_path is False
            and matrix_execution.get("installed_origin") == installed_origin
            and matrix_execution.get("source_checkout_on_sys_path") is False
            and matrix_execution.get("origin_is_expected_installed_target") is True
        )
        sibling_checks = probe_data.get(
            "sibling_checks",
            {"skills_absent": False, "agent_absent": False},
        )
        isolation_passed = (
            not args.require_no_skills or sibling_checks.get("skills_absent") is True
        ) and (not args.require_no_agent or sibling_checks.get("agent_absent") is True)
        independence = probe_data.get(
            "independence",
            {
                "schema_version": "independence-audit.v1",
                "status": "failed",
                "findings": [{"code": "installed_probe_failed"}],
            },
        )
        structured_cells_passed = _expected_matrix_passes(matrix_artifact)
        matrix_passed = (
            matrix.returncode == 0 and structured_cells_passed and installed_execution_passed
        )
        status = (
            "passed"
            if (
                build.returncode == 0
                and install.returncode == 0
                and probe.returncode == 0
                and wheel_hash is not None
                and matrix_passed
                and isolation_passed
                and independence.get("status") == "passed"
            )
            else "failed"
        )
        result = {
            "schema_version": "backtrader-mcp-acceptance-v1",
            "status": status,
            "distribution": {
                "wheel_file": wheel.name if wheel is not None else None,
                "wheel_sha256": wheel_hash,
                "installed_origin": installed_origin,
                "installed_target": str(expected_origin_root),
                "origin_is_installed_target": origin_is_installed,
                "source_checkout_on_sys_path": source_checkout_on_sys_path,
                "build": _tail(build),
                "install": _tail(install),
                "probe": _tail(probe),
            },
            "matrix": {
                "archetypes": 7,
                "profiles": 2,
                "executed_cells": matrix_artifact.get("executed_cells", 0),
                "passed_cells": matrix_artifact.get("passed_cells", 0),
                "passed": matrix_passed,
                "fixed_test": str(FIXED_TEST),
                "artifact_error": artifact_error,
                "execution_environment": matrix_execution,
                "cells": (
                    matrix_artifact.get("cells")
                    if isinstance(matrix_artifact.get("cells"), list)
                    else []
                ),
                **_tail(matrix),
            },
            "sibling_checks": sibling_checks,
            "independence": independence,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
