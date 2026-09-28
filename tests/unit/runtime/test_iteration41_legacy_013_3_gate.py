"""Fresh-process checks for the retired 013_3 direct SimNow launcher.

The retained module is still imported by historical fixture tests, so this
coverage exercises only ``python run.py``.  Each process blocks framework,
provider, and socket access; the observed JSON rejection must therefore come
from the Iteration 41 configuration fence itself.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Iterable


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPOSITORY_ROOT / "examples" / "013_3_sa_midfreq_simnow" / "run.py"


def _guarded_script_run(
    path: Path,
    *,
    package_root: Path,
    arguments: Iterable[str] = (),
) -> subprocess.CompletedProcess:
    """Run a legacy script while refusing any framework/provider or socket use."""

    program = r"""
import importlib.abc
import runpy
import socket
import sys

def reject(*args, **kwargs):
    raise AssertionError("legacy 013_3 gate attempted network I/O")

class RejectTradingImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"backtrader", "bt_api_py", "ctpbeebt"}:
            raise AssertionError("legacy 013_3 gate imported framework/provider before rejection")

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


def _canonical_clone_without_config(tmp_path: Path) -> tuple[Path, Path]:
    """Clone only the early gate and its local configuration package."""

    clone_root = tmp_path / "canonical-clone"
    shutil.copytree(REPOSITORY_ROOT / "backtrader_runtime", clone_root / "backtrader_runtime")
    cloned_script = clone_root / SCRIPT.relative_to(REPOSITORY_ROOT)
    cloned_script.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT, cloned_script)
    runtime_dir = cloned_script.parent / "runtime"
    runtime_dir.mkdir()
    shutil.copy2(
        SCRIPT.parent / "runtime" / "config.example.yaml", runtime_dir / "config.example.yaml"
    )
    return clone_root, cloned_script


def _unregistered_copy_with_config(tmp_path: Path) -> Path:
    """A valid nearby config cannot create a route outside the reviewed registry."""

    copied_root = tmp_path / "unregistered-copy"
    copied_script = copied_root / SCRIPT.relative_to(REPOSITORY_ROOT)
    copied_script.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT, copied_script)
    runtime_dir = copied_script.parent / "runtime"
    runtime_dir.mkdir()
    shutil.copy2(SCRIPT.parent / "runtime" / "config.example.yaml", runtime_dir / "config.yaml")
    return copied_script


def test_direct_013_3_requires_config_before_framework_provider_or_network(tmp_path: Path) -> None:
    clone_root, cloned_script = _canonical_clone_without_config(tmp_path)

    error = _error(_guarded_script_run(cloned_script, package_root=clone_root))

    assert error["error_code"] == "CONFIG_REQUIRED"
    assert error["reason"] == "missing_config"


def test_direct_013_3_rejects_every_legacy_argument_before_framework_or_network() -> None:
    error = _error(
        _guarded_script_run(SCRIPT, package_root=REPOSITORY_ROOT, arguments=("--mode", "simnow"))
    )

    assert error["error_code"] == "PRESET_POLICY_VIOLATION"
    assert error["reason"] == "legacy_cli_arguments_not_supported"


def test_unregistered_013_3_copy_is_rejected_before_framework_or_network(tmp_path: Path) -> None:
    copied_script = _unregistered_copy_with_config(tmp_path)

    error = _error(_guarded_script_run(copied_script, package_root=REPOSITORY_ROOT))

    assert error["error_code"] == "PRESET_POLICY_VIOLATION"
    assert error["reason"] == "runtime_not_registered"


def test_013_3_direct_gate_precedes_framework_import_and_legacy_parser() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    gate = source.index('if __name__ == "__main__":')

    assert "run_legacy_config_first_cli" in source
    assert gate < source.index("import backtrader as bt")
    assert gate < source.index("def build_parser()")
