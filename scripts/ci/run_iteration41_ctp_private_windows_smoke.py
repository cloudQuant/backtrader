"""Run the synthetic Iteration 41 CTP fail-closed CLI smoke on Windows.

The selected regression builds a temporary, synthetic CTP config with TEST-NET
front addresses and placeholder credentials. It guards provider/runner imports,
credential resolution, socket use, and runtime dispatch. This harness never
opens the ignored private runtime config or installs/imports a CTP SDK.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from xml.etree import ElementTree


SMOKE_TEST_TARGETS = (
    "tests/unit/runtime/test_ctp_simnow_operator_route.py::"
    "test_shared_private_runtime_parses_live_config_but_default_cli_stops_before_dispatch",
)
_EXPECTED_CASE_NAMES = tuple(target.rsplit("::", 1)[-1] for target in SMOKE_TEST_TARGETS)
_REQUIRED_PLATFORM = "Windows"
_REQUIRED_PYTHON = (3, 11)
_ARTIFACT_STEM = "iteration41-ctp-private-windows-smoke"


def _source_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_pytest_command(output_dir: Path, executable: Optional[str] = None) -> List[str]:
    """Return the exact synthetic-config, no-SDK CLI regression command."""

    junit_path = output_dir / (_ARTIFACT_STEM + ".junit.xml")
    return [
        executable or sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:asyncio",
        "--junitxml=" + str(junit_path),
        *SMOKE_TEST_TARGETS,
    ]


def _interpreter_metadata() -> Dict[str, str]:
    return {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "executable": sys.executable,
        "system": platform.system(),
        "platform": platform.platform(),
    }


def _supported_interpreter() -> bool:
    return (
        platform.system() == _REQUIRED_PLATFORM
        and platform.python_implementation() == "CPython"
        and sys.version_info[:2] == _REQUIRED_PYTHON
    )


def _isolated_environment() -> Dict[str, str]:
    """Keep only Windows process basics; do not forward account/provider env."""

    retained_names = {
        "COMSPEC",
        "HOMEDRIVE",
        "HOMEPATH",
        "PATHEXT",
        "PATH",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
    environment = {
        name: value for name, value in os.environ.items() if name.upper() in retained_names
    }
    environment.update(
        {
            "PYTEST_ADDOPTS": "",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONNOUSERSITE": "1",
        }
    )
    return environment


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _classify_results(junit_path: Path):
    parse_error = None
    cases = []
    try:
        cases = list(ElementTree.parse(junit_path).getroot().iter("testcase"))
    except (OSError, ElementTree.ParseError) as error:
        parse_error = type(error).__name__

    results = []
    for case in cases:
        name = case.attrib.get("name", "")
        if case.find("skipped") is not None:
            result = "skipped"
        elif case.find("failure") is not None or case.find("error") is not None:
            result = "failed"
        else:
            result = "passed"
        results.append({"name": name, "result": result})
    return results, parse_error


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the synthetic Windows CPython 3.11 Iteration 41 CTP fail-closed CLI smoke."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for the smoke log, JUnit XML, and JSON summary.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.output_dir / (_ARTIFACT_STEM + ".log")
    junit_path = args.output_dir / (_ARTIFACT_STEM + ".junit.xml")
    summary_path = args.output_dir / (_ARTIFACT_STEM + ".json")
    command = build_pytest_command(args.output_dir)

    if not _supported_interpreter():
        message = (
            "No tests were executed; this smoke requires Windows CPython 3.11. "
            "Observed {0} {1}.".format(platform.python_implementation(), platform.python_version())
        )
        log_path.write_text(message + "\n", encoding="utf-8")
        _write_json(
            summary_path,
            {
                "schema_version": 1,
                "status": "NOT_EXECUTED_UNSUPPORTED_INTERPRETER",
                "execution_performed": False,
                "scope": "iteration41_ctp_private_synthetic_cli_fail_closed_no_provider_io",
                "required_platform": _REQUIRED_PLATFORM,
                "required_interpreter": "CPython 3.11",
                "interpreter": _interpreter_metadata(),
                "included_test_targets": list(SMOKE_TEST_TARGETS),
                "message": message,
            },
        )
        return 2

    try:
        completed = subprocess.run(
            command,
            cwd=str(_source_root()),
            env=_isolated_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        stdout = getattr(error, "stdout", None) or ""
        stderr = getattr(error, "stderr", None) or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        log_path.write_text(
            "".join((stdout, stderr, "\nsmoke runner error: ", type(error).__name__, "\n")),
            encoding="utf-8",
        )
        _write_json(
            summary_path,
            {
                "schema_version": 1,
                "status": "FAILED_TO_START" if isinstance(error, OSError) else "TIMEOUT",
                "execution_performed": False,
                "scope": "iteration41_ctp_private_synthetic_cli_fail_closed_no_provider_io",
                "required_platform": _REQUIRED_PLATFORM,
                "required_interpreter": "CPython 3.11",
                "interpreter": _interpreter_metadata(),
                "included_test_targets": list(SMOKE_TEST_TARGETS),
                "error_type": type(error).__name__,
            },
        )
        return 1

    log_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    results, parse_error = _classify_results(junit_path)
    names = [item["name"] for item in results]
    valid = (
        completed.returncode == 0
        and parse_error is None
        and sorted(names) == sorted(_EXPECTED_CASE_NAMES)
        and all(item["result"] == "passed" for item in results)
    )
    payload = {
        "schema_version": 1,
        "status": "PASSED" if valid else "FAILED",
        "execution_performed": True,
        "scope": "iteration41_ctp_private_synthetic_cli_fail_closed_no_provider_io",
        "required_platform": _REQUIRED_PLATFORM,
        "required_interpreter": "CPython 3.11",
        "runner_image": "windows-2022",
        "interpreter": _interpreter_metadata(),
        "pytest_command": command,
        "included_test_targets": list(SMOKE_TEST_TARGETS),
        "test_results": results,
        "passed_count": sum(item["result"] == "passed" for item in results),
        "skipped_count": sum(item["result"] == "skipped" for item in results),
        "failed_count": sum(item["result"] == "failed" for item in results),
        "pytest_exit_code": completed.returncode,
        "junit_parse_error": parse_error,
        "zero_activity_assertions": "passed" if valid else "not_verified",
        "asserted_zero_activity": (
            {
                "provider_or_runner_imports": 0,
                "credential_resolver_calls": 0,
                "socket_attempts": 0,
                "runtime_dispatch_calls": 0,
            }
            if valid
            else None
        ),
        "test_fixture_boundary": "temporary synthetic config with placeholder credentials and TEST-NET fronts",
        "real_private_config_used": False,
        "provider_sdk_used": False,
        "provider_network_used": False,
    }
    _write_json(summary_path, payload)
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if valid else 1


if __name__ == "__main__":  # pragma: no cover - exercised through the CI command
    raise SystemExit(main())
