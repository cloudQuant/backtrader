"""Contract tests for the explicit CPython 3.8 core-runtime CI harness."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


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


def test_cpython38_harness_has_a_fixed_no_sdk_core_runtime_scope() -> None:
    harness = _load_harness()

    command = harness.build_pytest_command("python3.8")

    assert command[:6] == ["python3.8", "-m", "pytest", "-q", "-p", "no:asyncio"]
    assert command[6:] == list(harness.CORE_RUNTIME_TEST_TARGETS)
    assert all("managed_execution" not in target for target in harness.CORE_RUNTIME_TEST_TARGETS)
    assert all("bt_api" not in target for target in harness.CORE_RUNTIME_TEST_TARGETS)


def test_print_command_never_claims_that_cpython38_tests_were_executed(tmp_path: Path) -> None:
    harness = _load_harness()
    output = tmp_path / "cpython38-core-runtime.json"

    status = harness.main(["--print-command", "--output", str(output)])

    assert status == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "COMMAND_READY"
    assert payload["execution_performed"] is False
    assert payload["required_interpreter"] == "CPython 3.8"
    assert payload["scope"] == "iteration41_core_config_operator_no_sdk"
    assert payload["managed_sdk_exclusions"]


def test_wrong_interpreter_is_recorded_as_not_executed(tmp_path: Path, monkeypatch) -> None:
    harness = _load_harness()
    output = tmp_path / "cpython38-core-runtime.json"
    monkeypatch.setattr(harness, "_is_cpython38", lambda: False)

    status = harness.main(["--output", str(output)])

    assert status == 2
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "NOT_EXECUTED_UNSUPPORTED_INTERPRETER"
    assert payload["execution_performed"] is False


def test_ci_workflow_requires_the_scope_labelled_cpython38_contract() -> None:
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job_start = workflow.index("  iteration41-cpython38-core-runtime:")
    job_end = workflow.index("\n  iteration41-posix-runtime-directory:", job_start)
    job = workflow[job_start:job_end]

    assert "iteration41-cpython38-core-runtime:" in workflow
    assert "name: Iteration 41 Core Runtime CPython 3.8" in workflow
    assert "runs-on: ubuntu-22.04" in workflow
    assert "python-version: '3.8'" in workflow
    assert "run_iteration41_cpython38_core_runtime.py" in workflow
    assert (
        "needs: [test, iteration41-cpython38-core-runtime, iteration41-posix-runtime-directory, iteration41-ctp-private-windows-smoke, sdk, performance, wheel-consumer]"
        in workflow
    )
    assert "needs['iteration41-cpython38-core-runtime'].result" in workflow
    assert "if: always()" in job
    assert "path: ${{ runner.temp }}/iteration41-cpython38-core-runtime.json" in job
    assert "if-no-files-found: error" in job


def test_ci_workflow_runs_and_requires_posix_filesystem_evidence() -> None:
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job_start = workflow.index("  iteration41-posix-runtime-directory:")
    job_end = workflow.index("\n  iteration41-ctp-private-windows-smoke:", job_start)
    job = workflow[job_start:job_end]

    assert "name: Iteration 41 POSIX Runtime Directory Filesystem" in job
    assert "runs-on: ubuntu-22.04" in job
    assert "python-version: '3.11'" in job
    assert 'platform.system() == "Linux"' in job
    assert "test_posix_runner_capability_keeps_local_output_off_a_replacement_path" in job
    assert "test_posix_runner_capability_rejects_a_symlinked_child_component" in job
    assert (
        'python -m pytest -q -p no:asyncio --junitxml="$junit" "${targets[@]}" 2>&1 | tee "$log"'
        in job
    )
    assert 'result = "skipped"' in job
    assert 'all(item["result"] == "passed" for item in results)' in job
    assert "sorted(names) == sorted(expected)" in job
    assert "name: iteration41-posix-runtime-directory-ubuntu-22.04" in job
    assert "if-no-files-found: error" in job
    assert "iteration41-posix-runtime-directory-junit.xml" in job
    assert "iteration41-posix-runtime-directory.log" in job
    assert "iteration41-posix-runtime-directory.json" in job
    assert job.count("if: always()") == 2
    assert 'test -s "$RUNNER_TEMP/iteration41-posix-runtime-directory.log"' in job
    assert 'test -s "$RUNNER_TEMP/iteration41-posix-runtime-directory-junit.xml"' in job
    assert 'test -s "$RUNNER_TEMP/iteration41-posix-runtime-directory.json"' in job
    assert '"pytest_command": [' in job
    assert '"status": "PASSED" if valid else "FAILED"' in job
    assert (
        "needs: [test, iteration41-cpython38-core-runtime, iteration41-posix-runtime-directory, iteration41-ctp-private-windows-smoke, sdk, performance, wheel-consumer]"
        in workflow
    )
    assert "needs['iteration41-posix-runtime-directory'].result" in workflow


def test_windows_ctp_smoke_has_fixed_synthetic_fail_closed_scope() -> None:
    specification = importlib.util.spec_from_file_location(
        "iteration41_ctp_private_windows_smoke", WINDOWS_SMOKE_SCRIPT
    )
    assert specification is not None
    assert specification.loader is not None
    harness = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(harness)

    command = harness.build_pytest_command(Path("evidence"), "python")

    assert command[:6] == ["python", "-m", "pytest", "-q", "-p", "no:asyncio"]
    assert command[-1] == (
        "tests/unit/runtime/test_ctp_simnow_operator_route.py::"
        "test_shared_private_runtime_parses_live_config_but_default_cli_stops_before_dispatch"
    )
    assert harness._REQUIRED_PLATFORM == "Windows"
    assert harness._REQUIRED_PYTHON == (3, 11)


def test_ci_workflow_requires_synthetic_windows_ctp_smoke_and_artifact() -> None:
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job_start = workflow.index("  iteration41-ctp-private-windows-smoke:")
    job_end = workflow.index("\n  sdk:", job_start)
    job = workflow[job_start:job_end]

    assert "name: Iteration 41 CTP Private Synthetic Windows Smoke" in job
    assert "runs-on: windows-2022" in job
    assert "python-version: '3.11'" in job
    assert '"pytest>=8.2,<9" "pytest-asyncio>=0.24,<1"' in job
    assert "run_iteration41_ctp_private_windows_smoke.py" in job
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD: '1'" in job
    assert "iteration41-ctp-private-windows-smoke.junit.xml" in job
    assert "iteration41-ctp-private-windows-smoke.log" in job
    assert "iteration41-ctp-private-windows-smoke.json" in job
    assert "name: iteration41-ctp-private-windows-smoke-windows-2022" in job
    assert "if-no-files-found: error" in job
    assert job.count("if: always()") == 2
    assert (
        "needs: [test, iteration41-cpython38-core-runtime, iteration41-posix-runtime-directory, iteration41-ctp-private-windows-smoke, sdk, performance, wheel-consumer]"
        in workflow
    )
    assert "needs['iteration41-ctp-private-windows-smoke'].result" in workflow
