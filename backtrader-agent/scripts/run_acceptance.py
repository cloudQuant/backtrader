"""Fixed product-owned P0 acceptance entrypoint; it never accepts a test target."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from backtrader_agent.audit import IndependenceAuditor  # noqa: E402
from backtrader_agent.contracts import ARCHETYPES  # noqa: E402
from backtrader_agent.doctor import diagnose  # noqa: E402


def _pytest(
    targets: List[str],
    environment: Dict[str, str],
    *,
    cwd: Path,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *targets,
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _failed_process(message: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 1, stdout="", stderr=message)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _prepare_clean_install(
    temporary_root: Path,
) -> Tuple[Dict[str, Any], Optional[Dict[str, str]], Optional[Path]]:
    source_copy = temporary_root / "wheel-source"
    shutil.copytree(
        PROJECT_ROOT,
        source_copy,
        ignore=shutil.ignore_patterns(
            "build",
            "dist",
            "*.egg-info",
            "__pycache__",
            ".pytest_cache",
            "*.pyc",
        ),
    )
    wheel_root = temporary_root / "wheel"
    wheel_root.mkdir()
    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            str(source_copy),
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_root),
        ],
        cwd=temporary_root,
        capture_output=True,
        text=True,
        check=False,
    )
    record: Dict[str, Any] = {
        "build_passed": build.returncode == 0,
        "build_stdout_tail": build.stdout[-1000:],
        "build_stderr_tail": build.stderr[-1000:],
        "install_passed": False,
        "probe_passed": False,
        "wheel_sha256": None,
        "installed_origin": None,
        "source_checkout_absent": False,
        "passed": False,
    }
    wheels = sorted(wheel_root.glob("backtrader_agent-*.whl"))
    if build.returncode != 0 or len(wheels) != 1:
        return record, None, None
    wheel = wheels[0]
    record["wheel_filename"] = wheel.name
    record["wheel_sha256"] = hashlib.sha256(wheel.read_bytes()).hexdigest()
    clean_site = temporary_root / "clean-site"
    install = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(clean_site),
            str(wheel),
        ],
        cwd=temporary_root,
        capture_output=True,
        text=True,
        check=False,
    )
    record["install_passed"] = install.returncode == 0
    record["install_stdout_tail"] = install.stdout[-1000:]
    record["install_stderr_tail"] = install.stderr[-1000:]
    if install.returncode != 0:
        return record, None, None

    clean_work = temporary_root / "clean-work"
    clean_tests = clean_work / "tests"
    clean_tests.mkdir(parents=True)
    for name in (
        "helpers.py",
        "test_cli_extended_actions.py",
        "test_run_resume.py",
        "test_runner_installer_audit.py",
    ):
        shutil.copy2(PROJECT_ROOT / "tests" / name, clean_tests / name)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(clean_site)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["BACKTRADER_AGENT_ACCEPTANCE_ENGINE_ROOT"] = str(PROJECT_ROOT.parent)
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib.util,json,pathlib,sys,backtrader_agent;"
                "print(json.dumps({"
                "'origin':str(pathlib.Path(backtrader_agent.__file__).resolve()),"
                "'sys_path':[str(pathlib.Path(item).resolve()) for item in sys.path if item],"
                "'mcp_absent':importlib.util.find_spec('backtrader_mcp') is None,"
                "'skills_absent':importlib.util.find_spec('backtrader_skills') is None"
                "},sort_keys=True))"
            ),
        ],
        cwd=clean_work,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        attestation = json.loads(probe.stdout)
        installed_origin = Path(attestation["origin"]).resolve()
        sys_path = [Path(item).resolve() for item in attestation["sys_path"]]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        attestation = {}
        installed_origin = Path("/")
        sys_path = [PROJECT_ROOT]
    source_checkout_absent = (
        _is_within(installed_origin, clean_site)
        and not _is_within(installed_origin, PROJECT_ROOT)
        and all(not _is_within(path, PROJECT_ROOT) for path in sys_path)
    )
    record.update(
        {
            "probe_passed": probe.returncode == 0,
            "probe_stderr_tail": probe.stderr[-1000:],
            "installed_origin": attestation.get("origin"),
            "source_checkout_absent": source_checkout_absent,
            "clean_sys_path": attestation.get("sys_path", []),
            "mcp_absent": attestation.get("mcp_absent", False),
            "skills_absent": attestation.get("skills_absent", False),
        }
    )
    record["passed"] = bool(
        record["build_passed"]
        and record["install_passed"]
        and record["probe_passed"]
        and record["source_checkout_absent"]
        and record["mcp_absent"]
        and record["skills_absent"]
    )
    return record, environment, clean_work


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", choices=["all"], default="all")
    parser.add_argument("--require-no-mcp", action="store_true")
    parser.add_argument(
        "--require-no-skills",
        "--require-no-backtrader-skills",
        dest="require_no_skills",
        action="store_true",
    )
    parser.parse_args(argv)
    doctor = diagnose(PROJECT_ROOT)
    audit = IndependenceAuditor(PROJECT_ROOT).audit()
    with tempfile.TemporaryDirectory(prefix="backtrader-agent-acceptance-") as name:
        temporary_root = Path(name)
        evidence_root = temporary_root / "evidence"
        clean_install, environment, clean_work = _prepare_clean_install(temporary_root)
        if environment is None or clean_work is None:
            matrix = _failed_process("clean wheel installation failed")
            crash_resume = _failed_process("clean wheel installation failed")
            repair = _failed_process("clean wheel installation failed")
        else:
            environment["BACKTRADER_AGENT_ACCEPTANCE_EVIDENCE_DIR"] = str(evidence_root)
            matrix = _pytest(
                [
                    "tests/test_runner_installer_audit.py::"
                    "test_controlled_end_to_end_run_and_report"
                ],
                environment,
                cwd=clean_work,
            )
            crash_resume = _pytest(
                [
                    "tests/test_run_resume.py::"
                    "test_partial_report_and_paused_session_resume_same_effect"
                ],
                environment,
                cwd=clean_work,
            )
            repair = _pytest(
                [
                    "tests/test_cli_extended_actions.py::"
                    "test_failed_session_repair_revises_spec_and_rerenders_owned_draft"
                ],
                environment,
                cwd=clean_work,
            )
        cells = []
        for path in sorted(evidence_root.glob("*.json")):
            try:
                cells.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                cells = []
                break
    expected_cells = {
        f"{archetype}:{profile}"
        for archetype in ARCHETYPES
        for profile in ("python_bundle", "single_test")
    }
    observed_cells = {cell.get("cell_id") for cell in cells}
    adapter_coverage = {
        adapter for cell in cells for adapter in cell.get("data", {}).get("formats", [])
    }
    specialized = {
        "multi_data": all(
            cell.get("data", {}).get("feed_count", 0) >= 2
            for cell in cells
            if cell.get("archetype") in {"multi_asset_allocation", "pairs_spread"}
        ),
        "multi_timeframe": all(
            any(
                item.get("profile_id") in {"resample", "replay"}
                for item in cell.get("data", {}).get("transforms", [])
            )
            for cell in cells
            if cell.get("archetype") == "multi_timeframe"
        ),
        "precomputed_ml": all(
            "signal" in cell.get("data", {}).get("custom_lines", [])
            for cell in cells
            if cell.get("archetype") == "precomputed_ml"
        ),
    }
    matrix_passed = (
        clean_install["passed"]
        and matrix.returncode == 0
        and observed_cells == expected_cells
        and len(cells) == 14
        and adapter_coverage
        == {
            "generic_csv",
            "backtrader_csv",
            "yahoo_csv",
            "mt5_csv",
            "pandas",
            "pandas_custom_lines",
        }
        and all(specialized.values())
        and all(
            cell.get("status") == "passed"
            and set(cell.get("modes", {})) == {"runonce", "runnext"}
            and cell.get("comparison", {}).get("status") == "passed"
            for cell in cells
        )
    )
    gates = {
        "crash_resume": {
            "passed": crash_resume.returncode == 0,
            "stdout_tail": crash_resume.stdout[-1000:],
            "stderr_tail": crash_resume.stderr[-1000:],
        },
        "repair": {
            "passed": repair.returncode == 0,
            "stdout_tail": repair.stdout[-1000:],
            "stderr_tail": repair.stderr[-1000:],
        },
    }
    sibling_checks = {
        "mcp_absent": bool(clean_install.get("mcp_absent")),
        "skills_absent": bool(clean_install.get("skills_absent")),
    }
    isolation_passed = sibling_checks["mcp_absent"] and sibling_checks["skills_absent"]
    result = {
        "schema_version": "acceptance-report-v1",
        "status": (
            "passed"
            if (
                doctor["status"] == "ready"
                and audit["status"] == "passed"
                and matrix_passed
                and isolation_passed
                and all(gate["passed"] for gate in gates.values())
            )
            else "failed"
        ),
        "doctor": doctor,
        "independence": audit,
        "clean_install": clean_install,
        "sibling_checks": sibling_checks,
        "matrix": {
            "archetypes": 7,
            "profiles": 2,
            "modes_per_cell": ["runonce", "runnext"],
            "executed_cells": 14 if matrix_passed else 0,
            "passed": matrix_passed,
            "adapter_coverage": sorted(adapter_coverage),
            "specialized_data": specialized,
            "cells": cells,
            "fixed_test": (
                "tests/test_runner_installer_audit.py::" "test_controlled_end_to_end_run_and_report"
            ),
            "stdout_tail": matrix.stdout[-2000:],
            "stderr_tail": matrix.stderr[-2000:],
        },
        "independent_gates": gates,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
