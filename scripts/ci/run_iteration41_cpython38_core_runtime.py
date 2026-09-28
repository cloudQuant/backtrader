"""Run the CPython 3.8 Iteration 41 core-runtime compatibility contract.

This harness deliberately covers only the configuration-first operator path:
schema-v4 ``config.yaml``, sealed registry policy, and ``bt-runtime``
bootstrap/doctor/run behavior with local in-memory runners.  It does not
install or import the optional managed-execution SDKs.  Those SDK packages
declare Python 3.9 or 3.11 minimum versions, so their managed runtime is not a
supported CPython 3.8 configuration.

The default command refuses every interpreter except CPython 3.8.  A caller
can use ``--print-command`` on another interpreter to inspect the exact
command, but that mode never reports execution as passed.
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


CORE_RUNTIME_TEST_TARGETS = (
    "tests/unit/runtime/test_runtime_package_import_boundary.py",
    "tests/unit/runtime/test_runtime_config.py",
    "tests/unit/runtime/test_runtime_operator_flow.py",
    "tests/unit/runtime/test_runtime_operator_guidance.py",
    "tests/unit/runtime/test_runtime_batch_bootstrap.py",
)

_MANAGED_SDK_EXCLUSIONS = (
    "bt_api_py and bt_api_execution declare Python >=3.11",
    "bt_api_base, bt_api_risk, and bt_api_monitor declare Python >=3.9",
    "no provider, account, gateway, or managed-execution SDK path is covered",
)


def _source_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_pytest_command(executable: Optional[str] = None) -> List[str]:
    """Return the exact no-SDK compatibility command for the active interpreter."""

    return [
        executable or sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:asyncio",
        *CORE_RUNTIME_TEST_TARGETS,
    ]


def _interpreter_metadata() -> Dict[str, str]:
    return {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "executable": sys.executable,
        "platform": platform.platform(),
    }


def _is_cpython38() -> bool:
    return (
        platform.python_implementation() == "CPython"
        and sys.version_info.major == 3
        and sys.version_info.minor == 8
    )


def _result_payload(*, status: str, execution_performed: bool) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "status": status,
        "execution_performed": execution_performed,
        "required_interpreter": "CPython 3.8",
        "interpreter": _interpreter_metadata(),
        "scope": "iteration41_core_config_operator_no_sdk",
        "included_test_targets": list(CORE_RUNTIME_TEST_TARGETS),
        "managed_sdk_exclusions": list(_MANAGED_SDK_EXCLUSIONS),
        "pytest_command": build_pytest_command(),
    }


def _write_payload(payload: Dict[str, Any], output: Optional[Path]) -> None:
    rendered = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(rendered)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(output)


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the CPython 3.8 Iteration 41 core config/operator compatibility contract."
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON result path. The result is otherwise written to stdout.",
    )
    parser.add_argument(
        "--print-command",
        action="store_true",
        help="Describe the exact command without executing it; this never records a pass.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the isolated core contract, refusing a non-CPython-3.8 interpreter."""

    args = _parse_args(argv)
    if args.print_command:
        payload = _result_payload(status="COMMAND_READY", execution_performed=False)
        payload["message"] = "No tests were executed; run this command under CPython 3.8."
        _write_payload(payload, args.output)
        return 0

    if not _is_cpython38():
        payload = _result_payload(
            status="NOT_EXECUTED_UNSUPPORTED_INTERPRETER", execution_performed=False
        )
        payload["message"] = (
            "No tests were executed because the active interpreter is not CPython 3.8."
        )
        _write_payload(payload, args.output)
        return 2

    environment = os.environ.copy()
    # A clean plugin surface makes this contract independent of optional SDK,
    # provider and pytest plugin installations on the CI worker.
    environment["PYTEST_ADDOPTS"] = ""
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    command = build_pytest_command()
    try:
        completed = subprocess.run(command, cwd=str(_source_root()), env=environment, check=False)
    except OSError as error:
        payload = _result_payload(status="FAILED_TO_START", execution_performed=False)
        payload["message"] = "The CPython 3.8 core-runtime command could not be started."
        payload["error_type"] = type(error).__name__
        _write_payload(payload, args.output)
        return 1

    payload = _result_payload(
        status="PASSED" if completed.returncode == 0 else "FAILED",
        execution_performed=True,
    )
    payload["pytest_exit_code"] = completed.returncode
    _write_payload(payload, args.output)
    return completed.returncode


if __name__ == "__main__":  # pragma: no cover - exercised through the CI command
    raise SystemExit(main())
