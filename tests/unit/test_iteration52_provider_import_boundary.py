"""Iteration 52 boundary: importing the framework must not load a provider SDK.

``BtApiStore`` binds ``bt_api_*`` lazily so the package stays importable without
the optional SDK.  Nothing pinned that property for the store/broker modules
themselves; these checks do, each in a fresh interpreter.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_PROBE = """
import json
import sys
import {module}
print(json.dumps(sorted(name for name in sys.modules if name.startswith("bt_api"))))
"""


def _imported_sdk_modules(module: str) -> list[str]:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(module=module)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, f"{module}: {result.stderr}"
    return json.loads(result.stdout)


def test_framework_imports_do_not_load_provider_sdk():
    for module in (
        "backtrader",
        "backtrader.stores",
        "backtrader.stores.btapistore",
        "backtrader.brokers.btapibroker",
        "backtrader.stores.managed_execution",
    ):
        assert _imported_sdk_modules(module) == [], module
