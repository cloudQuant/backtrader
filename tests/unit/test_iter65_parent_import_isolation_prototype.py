"""Cold-import isolation for two existing synthetic parent/delegate paths.

This runs source-tree tests with local SQLite, synthetic identities, fake
admission and a synthetic provider in a fresh subprocess.  It does not prove
an independent Execution service starts, cover every branch, validate a real
account or Gateway authorization, or exercise an installed distribution.
"""

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_existing_parent_paths_without_risk_or_ctp_native_client(tmp_path):
    workspace = Path(__file__).resolve().parents[3]
    assert workspace.name == "wt-iter65"
    sdk_root = workspace / "bt_api_py"
    test_file = sdk_root / "bt_api/bt_api_execution/tests/test_parent_authority_iter63.py"
    assert test_file.is_file()
    child_script = textwrap.dedent(
        """
        import importlib.abc
        from pathlib import Path
        import sys

        workspace = Path(sys.argv[1]).resolve()
        test_file = Path(sys.argv[2]).resolve()
        base_temp = Path(sys.argv[3]).resolve()
        blocked = ("bt_api_risk", "bt_api_ctp.ctp.client")

        def forbidden(name):
            return any(name == prefix or name.startswith(prefix + ".") for prefix in blocked)

        assert not [name for name in sys.modules if forbidden(name)]

        class BlockOptionalImports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if forbidden(fullname):
                    raise ModuleNotFoundError("synthetic import guard: " + fullname)
                return None

        guard = BlockOptionalImports()
        for name in blocked:
            try:
                guard.find_spec(name)
            except ModuleNotFoundError:
                pass
            else:
                raise AssertionError("optional-import guard did not reject " + name)
        sys.meta_path.insert(0, guard)

        import pytest

        selectors = [
            str(test_file) + "::test_execution_to_registry_gateway_parent_journal",
            str(test_file) + "::test_sdk_delegate_uses_execution_journal_and_never_resends",
        ]
        result = pytest.main(["-q", "-p", "no:cacheprovider", "--basetemp", str(base_temp), *selectors])
        assert result == 0, "synthetic source-tree tests failed: " + str(result)

        required = (
            "bt_api_execution.parent_authority", "bt_api_execution.gateway_delegate_host",
            "bt_api_py.gateway_delegate_service_client", "bt_api_gateway.direct_parent_authority",
        )
        assert all(name in sys.modules for name in required)
        assert not [name for name in sys.modules if forbidden(name)]
        escaped = {}
        for name, module in tuple(sys.modules.items()):
            if name == "bt_api" or name.startswith(("bt_api.", "bt_api_")):
                paths = []
                if getattr(module, "__file__", None):
                    paths.append(module.__file__)
                paths.extend(getattr(module, "__path__", ()))
                for path in paths:
                    if not Path(path).resolve().is_relative_to(workspace):
                        escaped[name] = str(path)
        assert not escaped, escaped
        print("ISOLATED_PARENT_PATHS_OK")
        """
    )
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", child_script, str(workspace), str(test_file), str(tmp_path / "child")],
        cwd=sdk_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    assert "2 passed" in completed.stdout
    assert "ISOLATED_PARENT_PATHS_OK" in completed.stdout
