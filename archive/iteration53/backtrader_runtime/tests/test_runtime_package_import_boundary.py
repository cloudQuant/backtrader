"""Fresh-process import boundaries for the Iteration 41 public package."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_package_import_leaves_dispatch_module_unloaded_until_explicitly_requested() -> None:
    """An offline CLI import must not first load the runtime dispatcher."""

    program = """
import sys
import backtrader_runtime
import backtrader_runtime.cli
assert 'backtrader_runtime.runner' not in sys.modules
from backtrader_runtime import dispatch_registered_runtime
assert callable(dispatch_registered_runtime)
assert 'backtrader_runtime.runner' in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_default_store_contract_definitions_import_without_managed_sdk() -> None:
    """Evaluate the always-imported DTO module on every core CI interpreter.

    Loading this stdlib-only file directly keeps the minimal Python 3.8 lane
    independent of optional framework integrations while exercising dataclass
    construction (which an AST-only syntax check cannot verify).
    """

    program = """
import importlib.util
import sys
from pathlib import Path
path = Path('backtrader/stores/managed_execution.py').resolve()
spec = importlib.util.spec_from_file_location('bt_store_contract_compat', path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert module.CtpManagedDispatchBinding.__dataclass_params__.frozen
assert not any(name == 'bt_api_py' or name.startswith('bt_api_') for name in sys.modules)
if sys.version_info >= (3, 10):
    assert 'command_id' in module.CtpManagedDispatchBinding.__slots__
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
