"""Run the CPython 3.8 core compatibility and retired-runtime contract.

This harness covers selected Backtrader core behavior and the Store base
export, and checks that the retired runtime package and
``backtrader.runtime`` facade stay out of the active source tree.  The release
wheel job separately verifies the built artifact.  This harness does not
install or import optional managed-execution SDKs or contact a provider or
account.  The retained Iteration 41 Windows smoke helper is historical and
is not invoked by the active CI workflow because its target was retired.

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


CORE_COMPATIBILITY_TEST_TARGETS = (
    "tests/unit/core/test_errors.py",
    "tests/unit/core/test_store.py",
    "tests/unit/scripts/test_run_iteration41_cpython38_core_runtime.py",
)

_RETIRED_RUNTIME_SOURCE_PATHS = (
    "backtrader_runtime",
    "backtrader/runtime",
)

_MANAGED_SDK_EXCLUSIONS = (
    "bt_api_py and bt_api_execution declare Python >=3.11",
    "bt_api_base, bt_api_risk, and bt_api_monitor declare Python >=3.9",
    "no provider, account, gateway, or managed-execution SDK path is covered",
    "the retired Store-owned CTP managed-order contract is not covered",
)


def _source_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_pytest_command(executable: Optional[str] = None) -> List[str]:
    """Return the exact no-SDK core compatibility command for this interpreter."""

    return [
        executable or sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:asyncio",
        *CORE_COMPATIBILITY_TEST_TARGETS,
    ]


def _retired_runtime_paths_present(root: Optional[Path] = None) -> List[str]:
    """Find retired runtime package and module paths in a source layout.

    Only the active package and facade locations are checked.
    """

    source_root = _source_root() if root is None else root
    present = []
    for relative in _RETIRED_RUNTIME_SOURCE_PATHS:
        for candidate in (relative, relative + ".py"):
            path = source_root / candidate
            if path.exists() or path.is_symlink():
                present.append(candidate)
    return present


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
        "scope": "cpython38_backtrader_core_compatibility_runtime_removal_no_sdk",
        "included_test_targets": list(CORE_COMPATIBILITY_TEST_TARGETS),
        "retired_runtime_source_paths_present": _retired_runtime_paths_present(),
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
        description="Run the CPython 3.8 core compatibility and retired-runtime contract."
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
    """Run the current core contract on CPython 3.8, fail-closed."""

    args = _parse_args(argv)
    if args.print_command:
        payload = _result_payload(status="COMMAND_READY", execution_performed=False)
        payload["message"] = "No tests were executed; run this command under CPython 3.8."
        _write_payload(payload, args.output)
        return 0

    retired_paths = _retired_runtime_paths_present()
    if retired_paths:
        payload = _result_payload(
            status="FAILED_RETIRED_RUNTIME_SOURCE_PRESENT", execution_performed=False
        )
        payload["message"] = "A retired runtime import path exists in the active source tree."
        payload["retired_runtime_source_paths_present"] = retired_paths
        _write_payload(payload, args.output)
        return 1

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
