"""P0 regression coverage for the retired 014 CTP/SimNow entrypoints.

Every direct process below blocks framework/provider imports and socket
operations.  The tests therefore prove that schema-v4/registry handling runs
before a historical runner can reach its retained local journal, coordinator,
or CTP write path.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Iterable

import pytest

from backtrader_runtime import RuntimeConfigError


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LOWFREQ_ROOT = REPOSITORY_ROOT / "examples" / "014_1_ctp_options_lowfreq"
MIDFREQ_ROOT = REPOSITORY_ROOT / "examples" / "014_2_ctp_options_midfreq"
DIRECT_SCRIPTS = (
    LOWFREQ_ROOT / "run.py",
    LOWFREQ_ROOT / "simnow_launcher.py",
    MIDFREQ_ROOT / "run.py",
    MIDFREQ_ROOT / "simnow_launcher.py",
)
LAUNCHER_MODULES = (
    "examples.014_1_ctp_options_lowfreq.simnow_launcher",
    "examples.014_2_ctp_options_midfreq.simnow_launcher",
)


def _guarded_script_run(
    path: Path,
    *,
    package_root: Path,
    arguments: Iterable[str] = (),
) -> subprocess.CompletedProcess:
    """Run one historical script while rejecting framework/provider and socket use."""

    program = r"""
import importlib.abc
import runpy
import socket
import sys

def reject(*args, **kwargs):
    raise AssertionError("legacy 014 gate attempted network I/O")

class RejectTradingImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"backtrader", "bt_api_py", "ctpbeebt"}:
            raise AssertionError("legacy 014 gate imported framework/provider before rejection")

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
    environment["PYTHONPATH"] = str(package_root)
    for name in (
        "BT_RUNTIME_MODE",
        "BT_RUNTIME_PRESET",
        "BACKTRADER_RUNTIME_MODE",
        "BACKTRADER_RUNTIME_PRESET",
    ):
        environment.pop(name, None)
    return subprocess.run(
        [sys.executable, "-c", program, str(path), *arguments],
        cwd=package_root,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _error(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 2, result.stderr
    return json.loads(result.stderr)


def _canonical_clone_without_config(tmp_path: Path, script: Path) -> tuple[Path, Path]:
    """Make a self-contained registered source mirror with no config.yaml.

    The cloned configuration package binds its inventory to this clone, so
    this asserts ``CONFIG_REQUIRED`` without depending on a developer's
    ignored source-tree config.yaml.
    """

    clone_root = tmp_path / "canonical-clone"
    shutil.copytree(REPOSITORY_ROOT / "backtrader_runtime", clone_root / "backtrader_runtime")
    cloned_script = clone_root / script.relative_to(REPOSITORY_ROOT)
    cloned_script.parent.mkdir(parents=True)
    shutil.copy2(script, cloned_script)
    runtime_dir = cloned_script.parent / "runtime"
    runtime_dir.mkdir()
    shutil.copy2(
        script.parent / "runtime" / "config.example.yaml", runtime_dir / "config.example.yaml"
    )
    return clone_root, cloned_script


def _unregistered_copy_with_config(tmp_path: Path, script: Path) -> Path:
    """Copy a script beside a valid v4 config without copying its registry binding."""

    copied_root = tmp_path / "unregistered-copy"
    copied_script = copied_root / script.relative_to(REPOSITORY_ROOT)
    copied_script.parent.mkdir(parents=True)
    shutil.copy2(script, copied_script)
    runtime_dir = copied_script.parent / "runtime"
    runtime_dir.mkdir()
    shutil.copy2(script.parent / "runtime" / "config.example.yaml", runtime_dir / "config.yaml")
    return copied_script


@pytest.mark.parametrize("script", DIRECT_SCRIPTS)
def test_direct_014_entrypoints_require_config_before_framework_or_network(
    tmp_path: Path, script: Path
) -> None:
    """No config produces CONFIG_REQUIRED before legacy code can import a client."""

    clone_root, cloned_script = _canonical_clone_without_config(tmp_path, script)
    error = _error(_guarded_script_run(cloned_script, package_root=clone_root))

    assert error["error_code"] == "CONFIG_REQUIRED"
    assert error["reason"] == "missing_config"


@pytest.mark.parametrize("script", DIRECT_SCRIPTS)
def test_legacy_014_cli_arguments_are_rejected_before_framework_or_network(script: Path) -> None:
    """Old mode/config/live switches cannot revive a replay or CTP entrypoint."""

    error = _error(
        _guarded_script_run(script, package_root=REPOSITORY_ROOT, arguments=("--mode", "live"))
    )

    assert error["error_code"] == "PRESET_POLICY_VIOLATION"
    assert error["reason"] == "legacy_cli_arguments_not_supported"


@pytest.mark.parametrize("script", DIRECT_SCRIPTS)
def test_unregistered_014_copy_is_rejected_before_framework_or_network(
    tmp_path: Path, script: Path
) -> None:
    """A nearby valid config cannot turn a copied historical script into a route."""

    copied_script = _unregistered_copy_with_config(tmp_path, script)
    error = _error(_guarded_script_run(copied_script, package_root=REPOSITORY_ROOT))

    assert error["error_code"] == "PRESET_POLICY_VIOLATION"
    assert error["reason"] == "runtime_not_registered"


@pytest.mark.parametrize("script", DIRECT_SCRIPTS)
def test_every_014_direct_script_has_a_pre_framework_config_first_fence(script: Path) -> None:
    """Prevent a future import reordering from bypassing the process gate."""

    source = script.read_text(encoding="utf-8")
    gate = source.index('if __name__ == "__main__":\n    raise SystemExit(_run_config_first_cli())')
    framework_import = source.index("import backtrader")

    assert "run_legacy_config_first_cli" in source
    assert gate < framework_import


@pytest.mark.parametrize("module_name", LAUNCHER_MODULES)
def test_programmatic_legacy_ctp_writer_names_are_deterministically_blocked(
    module_name: str,
) -> None:
    """The retained launcher cannot be revived through either public or private names."""

    launcher = importlib.import_module(module_name)
    for entrypoint in (launcher.run_live, launcher._legacy_run_live, launcher._legacy_main):
        with pytest.raises(RuntimeConfigError) as failure:
            entrypoint({}) if entrypoint is not launcher._legacy_main else entrypoint()
        assert failure.value.code == "PRESET_POLICY_VIOLATION"
        assert failure.value.reason == "legacy_direct_execution_not_supported"
