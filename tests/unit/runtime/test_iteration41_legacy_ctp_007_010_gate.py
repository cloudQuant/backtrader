"""P0-A through P0-D regression coverage for retired direct CTP entrypoints.

The tests use fresh processes that reject framework/provider imports and every
socket operation. They prove the configuration fence, rather than relying on
missing credentials or a provider being unreachable.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Iterable

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CTP_ROOT = REPOSITORY_ROOT / "examples" / "007_ctp"
LIVE_EXAMPLES_ROOT = REPOSITORY_ROOT / "examples" / "010_live_examples"

CTP_DIRECT_RUNNER = CTP_ROOT / "ctp_mixbroker_examples" / "live" / "run.py"
CTP_CASE_RUNNER = CTP_ROOT / "live_certification" / "simnow_penetration" / "run_case.py"
CTP_DIRECT_CASE = (
    CTP_ROOT / "live_certification" / "simnow_penetration" / "cases" / "T01_open_order.py"
)
CTP_HONGYUAN_DIRECT_CASE = (
    CTP_ROOT / "live_certification" / "hongyuan_penetration" / "cases" / "T01_open_order.py"
)
SIMNOW_TEST_RUNNER = LIVE_EXAMPLES_ROOT / "test_simnow_ctp.py"
SIMNOW_TRADE_LOGGER_RUNNER = LIVE_EXAMPLES_ROOT / "test_simnow_trade_logger_certification.py"
OKX_PUBLIC_DEMO_RUNNER = LIVE_EXAMPLES_ROOT / "live_mixbroker_okx_demo.py"
SA_STRATEGY_RUNNER = CTP_ROOT / "ctp_sa_dual_ma_strategy.py"

# This test starts a clean pytest interpreter while the parent suite may have
# eight CPU-bound xdist workers.  The deadline guards a genuinely wedged child;
# it is deliberately not a latency contract for the retired-module fence.
_FRESH_PYTEST_COLLECTION_TIMEOUT_SECONDS = 180

RUNTIME_SPECS = (
    (
        "example.007_ctp.legacy_direct",
        CTP_ROOT / "runtime" / "config.example.yaml",
        "examples.007_ctp.run_runtime",
    ),
    (
        "example.010_live_examples.simnow_legacy",
        LIVE_EXAMPLES_ROOT / "runtime" / "config.example.yaml",
        "examples.010_live_examples.run_runtime",
    ),
)


def _guarded_script_run(
    path: Path, arguments: Iterable[str] = ()
) -> subprocess.CompletedProcess[str]:
    """Execute a legacy script with framework/provider imports and sockets blocked."""

    program = r"""
import importlib.abc
import runpy
import socket
import sys

def reject(*args, **kwargs):
    raise AssertionError("legacy config gate attempted network I/O")

class RejectTradingImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"backtrader", "bt_api_py", "ctpbeebt"}:
            raise AssertionError("legacy config gate imported a framework/provider before rejection")

socket.getaddrinfo = reject
socket.create_connection = reject
socket.socket.connect = reject
socket.socket.connect_ex = reject
socket.socket.sendto = reject
sys.meta_path.insert(0, RejectTradingImports())
script = sys.argv[1]
sys.argv = [script, *sys.argv[2:]]
runpy.run_path(script, run_name="__main__")
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT)
    for name in (
        "BT_RUNTIME_MODE",
        "BT_RUNTIME_PRESET",
        "BACKTRADER_RUNTIME_MODE",
        "BACKTRADER_RUNTIME_PRESET",
    ):
        environment.pop(name, None)
    return subprocess.run(
        [sys.executable, "-c", program, str(path), *arguments],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _error(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.returncode == 2, result.stderr
    return json.loads(result.stderr)


@pytest.mark.parametrize(
    "path",
    (
        CTP_DIRECT_RUNNER,
        CTP_CASE_RUNNER,
        CTP_DIRECT_CASE,
        CTP_HONGYUAN_DIRECT_CASE,
        SIMNOW_TEST_RUNNER,
        SIMNOW_TRADE_LOGGER_RUNNER,
    ),
)
def test_direct_ctp_simnow_entrypoints_require_config_or_safe_replay_before_framework_or_network(
    path: Path,
) -> None:
    """P0 direct scripts cannot fall through to an old account/provider route."""

    result = _guarded_script_run(path)
    if result.returncode == 2:
        error = _error(result)
        assert error["error_code"] == "CONFIG_REQUIRED"
        assert error["reason"] == "missing_config"
        return

    # A local operator may already have bootstrapped the ignored config.yaml.
    # That configuration may enter only the registered no-action replay; the
    # fresh-process import/socket guards above still apply to this branch.
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "completed"
    assert (report["mode"], report["preset"]) == ("simulation", "replay")
    assert report["allows_network"] is False
    assert report["allows_external_writes"] is False
    replay = report["report"]["result"]
    assert replay["admission_status"] == "LOCAL_REPLAY_ONLY"
    assert replay["external_request_counts"] == {"network": 0, "order_write": 0}


@pytest.mark.parametrize(
    ("path", "arguments"),
    (
        (CTP_DIRECT_RUNNER, ("--dry-run",)),
        (CTP_DIRECT_RUNNER, ("--mode", "live")),
        (CTP_DIRECT_RUNNER, ("--live",)),
        (CTP_CASE_RUNNER, ("--list",)),
        (CTP_DIRECT_CASE, ("--report-dir", "ignored")),
        (SIMNOW_TEST_RUNNER, ("--subprocess-case", "order_placement")),
        (SIMNOW_TRADE_LOGGER_RUNNER, ("--subprocess-case", "runtime_audit")),
        (OKX_PUBLIC_DEMO_RUNNER, ("--duration", "30")),
        (SA_STRATEGY_RUNNER, ("--config", "ignored.yaml")),
    ),
)
def test_direct_ctp_simnow_legacy_flags_are_rejected_before_framework_or_network(
    path: Path, arguments: tuple[str, ...]
) -> None:
    """Dry-run, case selection, and child-process flags cannot revive direct execution."""

    error = _error(_guarded_script_run(path, arguments))

    assert error["error_code"] == "PRESET_POLICY_VIOLATION"
    assert error["reason"] == "legacy_cli_arguments_not_supported"


@pytest.mark.parametrize("script", tuple(CTP_ROOT.glob("ctp_*_examples/*/run.py")))
def test_every_retired_007_runner_has_an_early_config_first_script_fence(script: Path) -> None:
    """Keep all five backtest/live families from regressing one runner at a time."""

    source = script.read_text(encoding="utf-8")
    gate = source.index('if __name__ == "__main__":\n    raise SystemExit(_run_config_first_cli())')
    framework_import = source.index("import backtrader")

    assert "run_legacy_config_first_cli" in source
    assert gate < framework_import
    assert "def _legacy_main():\n    raise _iteration41_legacy_direct_execution_error(" in source
    assert source.count("if __name__") == 1


@pytest.mark.parametrize(
    "script",
    (
        CTP_ROOT / "ctp_sa_dual_ma_strategy.py",
        CTP_ROOT / "live_certification" / "simnow_penetration" / "run_case.py",
        CTP_ROOT / "live_certification" / "simnow_penetration" / "run_all.py",
        CTP_ROOT / "live_certification" / "hongyuan_penetration" / "run_case.py",
        CTP_ROOT / "live_certification" / "hongyuan_penetration" / "run_all.py",
    ),
)
def test_other_007_legacy_top_level_entrypoints_have_config_first_fences(script: Path) -> None:
    source = script.read_text(encoding="utf-8")
    gate = source.index('if __name__ == "__main__":\n    raise SystemExit(_run_config_first_cli())')

    assert "run_legacy_config_first_cli" in source
    assert source.count("if __name__") == 1
    if script.name == "run_case.py":
        assert 'def _legacy_main():\n    """Main entry point' in source
        legacy_main = source.index("def _legacy_main():")
        parser = source.index("parser = argparse.ArgumentParser", legacy_main)
        assert "raise _iteration41_legacy_direct_execution_error" in source[legacy_main:parser]
    if "import backtrader" in source:
        assert gate < source.index("import backtrader")


def test_007_sa_module_no_longer_loads_env_or_exposes_a_front_probe_or_store_route() -> None:
    """Importing the retained SA strategy cannot read .env or probe/construct CTP."""
    source = (CTP_ROOT / "ctp_sa_dual_ma_strategy.py").read_text(encoding="utf-8")

    assert "load_env" not in source
    assert "socket" not in source
    assert "resolve_server" not in source
    assert "CTPStore" not in source


@pytest.mark.parametrize("suite", ("simnow_penetration", "hongyuan_penetration"))
def test_each_certification_case_child_is_fenced_in_common_runtime_before_backtrader(
    suite: str,
) -> None:
    """All 66 child scripts share a pre-framework gate instead of a partial allow-list."""

    runtime = CTP_ROOT / "live_certification" / suite / "common" / "runtime.py"
    source = runtime.read_text(encoding="utf-8")

    assert "load_dotenv" not in source
    assert "def _is_direct_legacy_case_process()" in source
    assert "raise SystemExit(run_legacy_config_first_cli" in source
    assert source.index("raise SystemExit(run_legacy_config_first_cli") < source.index(
        "import backtrader as bt"
    )
    assert "def started_store" in source
    assert "raise legacy_direct_execution_error" in source


@pytest.mark.parametrize("suite", ("simnow_penetration", "hongyuan_penetration"))
def test_every_certification_case_imports_the_shared_gate_before_trading_dependencies(
    suite: str,
) -> None:
    """Cover all 66 direct child scripts without maintaining a fragile file allow-list."""

    cases_dir = CTP_ROOT / "live_certification" / suite / "cases"
    cases = tuple(path for path in sorted(cases_dir.glob("*.py")) if path.name != "__init__.py")
    assert len(cases) == 33

    for case in cases:
        tree = ast.parse(case.read_text(encoding="utf-8"), filename=str(case))
        runtime_import_line = None
        trading_import_lines = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                imported_modules = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_modules = (node.module or "",)
            else:
                continue

            if "common.runtime" in imported_modules:
                runtime_import_line = node.lineno
            if any(
                module.split(".")[0] in {"backtrader", "bt_api_py", "ctpbeebt"}
                for module in imported_modules
            ):
                trading_import_lines.append(node.lineno)

        assert runtime_import_line is not None, case
        assert all(runtime_import_line < line for line in trading_import_lines), case


@pytest.mark.parametrize("strategy_id, template, runner_module", RUNTIME_SPECS)
def test_registered_no_action_profiles_have_no_framework_provider_or_network_import(
    strategy_id: str, template: Path, runner_module: str
) -> None:
    """The configured migration report remains a real zero-I/O path in a fresh interpreter."""

    config = template.read_text(encoding="utf-8")
    program = r"""
import importlib.abc
import json
import socket
import sys
import tempfile
from pathlib import Path

class RejectTradingImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'backtrader', 'bt_api_py', 'ctpbeebt'}:
            raise AssertionError('no-action profile imported framework/provider')

def reject(*args, **kwargs):
    raise AssertionError('no-action profile attempted network I/O')

socket.getaddrinfo = reject
socket.create_connection = reject
socket.socket.connect = reject
socket.socket.connect_ex = reject
socket.socket.sendto = reject
sys.meta_path.insert(0, RejectTradingImports())

from backtrader_runtime import RegisteredRuntime, RuntimeRegistry, load_runtime_config, resolve_runtime_config
from backtrader_runtime.runner import dispatch_registered_runtime

runtime_dir = Path(sys.argv[1])
strategy_id = sys.argv[2]
runner_module = sys.argv[3]
config_text = sys.argv[4]
runtime_dir.mkdir(parents=True)
(runtime_dir / 'config.yaml').write_text(config_text, encoding='utf-8')
registry = RuntimeRegistry((RegisteredRuntime(
    runtime_dir=runtime_dir,
    strategy_id=strategy_id,
    allowed_presets=('replay',),
    allowed_parameter_keys=('scenario',),
    runner_module=runner_module,
),))
effective = resolve_runtime_config(load_runtime_config(runtime_dir, registry=registry), registry)
print(json.dumps(dispatch_registered_runtime(effective, registry), sort_keys=True))
"""
    # A subprocess-owned TemporaryDirectory avoids keeping a config.yaml in a
    # registered source runtime, which would invalidate the Git-ignore proof.
    import tempfile

    with tempfile.TemporaryDirectory(prefix="iteration41-legacy-no-action-") as directory:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(REPOSITORY_ROOT)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                program,
                str(Path(directory) / "runtime"),
                strategy_id,
                runner_module,
                config,
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["admission_status"] == "LOCAL_REPLAY_ONLY"
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}


def test_copied_007_direct_runner_is_not_trusted_even_with_a_v4_config(tmp_path: Path) -> None:
    """A copied old script cannot use a nearby config as a registry bypass."""

    copied = tmp_path / "copy" / "examples" / "007_ctp"
    copied_runner = copied / "ctp_mixbroker_examples" / "live" / "run.py"
    copied_runner.parent.mkdir(parents=True)
    shutil.copy2(CTP_DIRECT_RUNNER, copied_runner)
    copied_runtime = copied / "runtime"
    copied_runtime.mkdir()
    shutil.copy2(CTP_ROOT / "runtime" / "config.example.yaml", copied_runtime / "config.yaml")

    error = _error(_guarded_script_run(copied_runner))

    assert error["error_code"] == "PRESET_POLICY_VIOLATION"
    assert error["reason"] == "runtime_not_registered"


@pytest.mark.parametrize(
    "test_file",
    (
        LIVE_EXAMPLES_ROOT / "test_simnow_ctp.py",
        LIVE_EXAMPLES_ROOT / "test_simnow_trade_logger_certification.py",
    ),
)
def test_retired_simnow_pytest_modules_skip_instead_of_running_direct_cases(
    test_file: Path,
) -> None:
    """Manual pytest collection is deterministic and does not require bt_api_py or credentials."""

    source = test_file.read_text(encoding="utf-8")
    assert source.count("if __name__") == 1

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT)
    # The assertion is about the retired module's own import-time skip.  Do
    # not let an unrelated developer plugin or shared cache make this fresh
    # collection depend on the parent xdist environment.
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment.pop("PYTEST_ADDOPTS", None)

    result = subprocess.run(
        # Some developer environments load an incompatible pytest-asyncio
        # collector globally.  The assertion concerns the retired module's
        # own import-time fence, so disable that unrelated plugin in the fresh
        # process as well.
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:asyncio",
            "-p",
            "no:cacheprovider",
            str(test_file),
            "-q",
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=_FRESH_PYTEST_COLLECTION_TIMEOUT_SECONDS,
        check=False,
    )

    # A module-level skip leaves this one-file pytest process with no selected
    # tests.  Pytest uses exit status 5 for that condition; it is the expected
    # result for a retired direct test module rather than an execution failure.
    assert result.returncode == 5, result.stderr
    assert "skipped" in result.stdout.lower()
