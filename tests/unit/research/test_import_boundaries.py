"""Fresh-process checks for the optional research and TA-Lib import boundary."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _run_isolated(script: str, *, light_import: bool = False) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if light_import:
        environment["BACKTRADER_LIGHT_IMPORT"] = "1"
    else:
        environment.pop("BACKTRADER_LIGHT_IMPORT", None)
    return subprocess.run(
        [sys.executable, "-I", "-c", script, str(_REPOSITORY_ROOT)],
        cwd=str(_REPOSITORY_ROOT),
        env=environment,
        capture_output=True,
        text=True,
        timeout=45,
    )


def test_default_root_and_research_import_do_not_request_optional_runtime_or_network():
    script = dedent(
        """\
        import importlib.abc
        import sys

        sys.path.insert(0, sys.argv[1])
        blocked_roots = (
            "pandas",
            "fincore",
            "bt_api_py",
            "bt_api_base",
            "bt_api_ctp",
            "bt_api_execution",
        )
        import_attempts = []

        class OptionalImportBlocker(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if any(
                    fullname == root or fullname.startswith(root + ".")
                    for root in blocked_roots
                ):
                    import_attempts.append(fullname)
                    raise ModuleNotFoundError("blocked optional runtime: " + fullname)
                return None

        network_attempts = []
        def deny_network(event, args):
            if event in {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname"}:
                network_attempts.append(event)
                raise PermissionError("network access is outside package import")

        sys.meta_path.insert(0, OptionalImportBlocker())
        sys.addaudithook(deny_network)

        import backtrader as bt

        assert "talib" in dir(bt)
        assert set(bt.__all__) == {
            name for name in vars(bt) if not name.startswith("_")
        } | {"talib"}

        import backtrader.research as research
        import backtrader.research.alpha101 as alpha101

        assert bt.Cerebro is not None
        assert research.FactorStrategy is not None
        assert len(alpha101.ALPHA_REGISTRY) == 101
        assert alpha101.get_alpha(1) is alpha101.ALPHA_REGISTRY[1]
        assert import_attempts == [], import_attempts
        assert network_attempts == [], network_attempts
        assert not any(
            name == root or name.startswith(root + ".")
            for name in sys.modules
            for root in blocked_roots
        )
        assert "backtrader.talib" not in sys.modules
        """
    )

    result = _run_isolated(script)
    assert result.returncode == 0, result.stdout + result.stderr


def test_explicit_talib_import_hits_dependency_boundary_deterministically():
    script = dedent(
        """\
        import importlib.abc
        import importlib.util
        import sys

        sys.path.insert(0, sys.argv[1])
        pandas_attempts = []

        class FakeTalibLoader(importlib.abc.Loader):
            def exec_module(self, module):
                import pandas

        class OptionalDependencyBoundary(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "talib":
                    return importlib.util.spec_from_loader(fullname, FakeTalibLoader())
                if fullname == "pandas" or fullname.startswith("pandas."):
                    pandas_attempts.append(fullname)
                    raise ModuleNotFoundError("blocked optional dependency: " + fullname)
                return None

        sys.meta_path.insert(0, OptionalDependencyBoundary())
        import backtrader as bt

        assert "backtrader.talib" not in sys.modules
        from backtrader import talib

        assert talib is bt.talib
        assert talib.__name__ == "backtrader.talib"
        assert pandas_attempts == ["pandas"]
        assert "pandas" not in sys.modules
        """
    )

    result = _run_isolated(script)
    assert result.returncode == 0, result.stdout + result.stderr


def test_explicit_talib_import_works_when_optional_talib_is_absent():
    script = dedent(
        """\
        import importlib.abc
        import sys

        sys.path.insert(0, sys.argv[1])
        talib_attempts = []
        pandas_attempts = []

        class MissingTalibBoundary(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "talib":
                    talib_attempts.append(fullname)
                    raise ModuleNotFoundError("TA-Lib is not installed")
                if fullname == "pandas" or fullname.startswith("pandas."):
                    pandas_attempts.append(fullname)
                return None

        sys.meta_path.insert(0, MissingTalibBoundary())
        import backtrader as bt

        assert "backtrader.talib" not in sys.modules
        from backtrader import talib

        assert talib is bt.talib
        assert talib.__name__ == "backtrader.talib"
        assert talib_attempts == ["talib"]
        assert pandas_attempts == []
        assert "pandas" not in sys.modules
        """
    )

    result = _run_isolated(script)
    assert result.returncode == 0, result.stdout + result.stderr


def test_default_star_import_resolves_talib_only_when_requested():
    script = dedent(
        """\
        import importlib.abc
        import sys

        sys.path.insert(0, sys.argv[1])

        class MissingTalibBoundary(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "talib":
                    raise ModuleNotFoundError("TA-Lib is not installed")
                return None

        sys.meta_path.insert(0, MissingTalibBoundary())
        import backtrader as bt

        assert "backtrader.talib" not in sys.modules
        assert "talib" in bt.__all__
        namespace = {}
        exec("from backtrader import *", namespace)

        assert namespace["talib"] is bt.talib
        assert namespace["talib"].__name__ == "backtrader.talib"
        assert "backtrader.talib" in sys.modules
        """
    )

    result = _run_isolated(script)
    assert result.returncode == 0, result.stdout + result.stderr


def test_light_star_import_keeps_talib_out_of_the_light_export_surface():
    script = dedent(
        """\
        import sys

        sys.path.insert(0, sys.argv[1])
        import backtrader

        assert "__all__" not in vars(backtrader)
        namespace = {}
        exec("from backtrader import *", namespace)

        assert "talib" not in namespace
        assert "backtrader.talib" not in sys.modules
        """
    )

    result = _run_isolated(script, light_import=True)
    assert result.returncode == 0, result.stdout + result.stderr
