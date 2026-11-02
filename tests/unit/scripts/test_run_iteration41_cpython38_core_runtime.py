"""Contract tests for the CPython 3.8 core compatibility CI harness."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "ci" / "run_iteration41_cpython38_core_runtime.py"
WINDOWS_SMOKE_SCRIPT = ROOT / "scripts" / "ci" / "run_iteration41_ctp_private_windows_smoke.py"


def _load_harness():
    specification = importlib.util.spec_from_file_location("iteration41_cpython38_harness", SCRIPT)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_cpython38_harness_targets_current_core_contracts_only() -> None:
    harness = _load_harness()

    command = harness.build_pytest_command("python3.8")

    assert command[:6] == ["python3.8", "-m", "pytest", "-q", "-p", "no:asyncio"]
    assert command[6:] == [
        "tests/unit/core/test_errors.py",
        "tests/unit/core/test_store.py",
        "tests/unit/scripts/test_run_iteration41_cpython38_core_runtime.py",
    ]
    assert all((ROOT / target).is_file() for target in command[6:])
    assert all("tests/unit/runtime/" not in target for target in command[6:])
    assert all("bt_api" not in target for target in command[6:])


def test_retired_runtime_is_absent_from_active_source() -> None:
    harness = _load_harness()

    assert harness._retired_runtime_paths_present() == []
    assert not (ROOT / "backtrader_runtime").exists()
    assert not (ROOT / "backtrader" / "runtime").exists()


@pytest.mark.parametrize(
    "relative_path",
    (
        "backtrader_runtime",
        "backtrader_runtime.py",
        "backtrader/runtime",
        "backtrader/runtime.py",
    ),
)
def test_retired_runtime_guard_detects_real_temporary_source_paths(
    tmp_path: Path, relative_path: str
) -> None:
    harness = _load_harness()
    retired_path = tmp_path / relative_path
    if relative_path.endswith(".py"):
        retired_path.parent.mkdir(parents=True, exist_ok=True)
        retired_path.write_text("# retired import path\n", encoding="utf-8")
    else:
        retired_path.mkdir(parents=True)

    assert harness._retired_runtime_paths_present(tmp_path) == [relative_path]


def test_retired_runtime_reappearance_stops_before_pytest(tmp_path: Path, monkeypatch) -> None:
    harness = _load_harness()
    output = tmp_path / "cpython38-core-compatibility.json"
    monkeypatch.setattr(harness, "_is_cpython38", lambda: True)
    monkeypatch.setattr(
        harness, "_retired_runtime_paths_present", lambda: ["backtrader_runtime"]
    )
    monkeypatch.setattr(
        harness,
        "_interpreter_metadata",
        lambda: {
            "implementation": "CPython",
            "version": "3.8.0",
            "executable": "python",
            "platform": "test-platform",
        },
    )

    def unexpected_pytest(*args, **kwargs):
        raise AssertionError("pytest must not run while the retired source path is present")

    monkeypatch.setattr(harness.subprocess, "run", unexpected_pytest)

    status = harness.main(["--output", str(output)])

    assert status == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "FAILED_RETIRED_RUNTIME_SOURCE_PRESENT"
    assert payload["execution_performed"] is False
    assert payload["retired_runtime_source_paths_present"] == ["backtrader_runtime"]


def test_print_command_never_claims_that_cpython38_tests_were_executed(
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    output = tmp_path / "cpython38-core-compatibility.json"

    status = harness.main(["--print-command", "--output", str(output)])

    assert status == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "COMMAND_READY"
    assert payload["execution_performed"] is False
    assert payload["required_interpreter"] == "CPython 3.8"
    assert payload["scope"] == "cpython38_backtrader_core_compatibility_runtime_removal_no_sdk"
    assert payload["retired_runtime_source_paths_present"] == []
    assert payload["managed_sdk_exclusions"]


def test_wrong_interpreter_is_recorded_as_not_executed(tmp_path: Path, monkeypatch) -> None:
    harness = _load_harness()
    output = tmp_path / "cpython38-core-compatibility.json"
    monkeypatch.setattr(harness, "_is_cpython38", lambda: False)

    status = harness.main(["--output", str(output)])

    assert status == 2
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "NOT_EXECUTED_UNSUPPORTED_INTERPRETER"
    assert payload["execution_performed"] is False


def test_ci_workflow_requires_core_compatibility_and_release_wheel_jobs() -> None:
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job_start = workflow.index("  cpython38-core-compatibility:")
    job_end = workflow.index("\n  sdk:", job_start)
    job = workflow[job_start:job_end]

    assert "name: Backtrader Core Compatibility CPython 3.8" in job
    assert "runs-on: ubuntu-22.04" in job
    assert "python-version: '3.8'" in job
    assert "run_iteration41_cpython38_core_runtime.py" in job
    assert "python -m pip install -e ." in job
    assert "cpython38-core-compatibility.json" in job
    assert (
        "needs: [test, cpython38-core-compatibility, sdk, performance, wheel-consumer]"
        in workflow
    )
    assert "needs['cpython38-core-compatibility'].result" in workflow
    assert "needs['wheel-consumer'].result" in workflow
    assert "verify_release_wheel.py" in workflow


def test_ci_workflow_has_no_archived_runtime_collectors() -> None:
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    harness = _load_harness()

    assert "tests/unit/runtime/" not in workflow
    assert "iteration41-posix-runtime-directory:" not in workflow
    assert "iteration41-ctp-private-windows-smoke:" not in workflow
    assert "run_iteration41_ctp_private_windows_smoke.py" not in workflow
    assert WINDOWS_SMOKE_SCRIPT.is_file()
    assert "retained Iteration 41 Windows smoke helper is historical" in harness.__doc__
    assert "is not invoked by the active CI workflow" in harness.__doc__
