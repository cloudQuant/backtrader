"""Source contracts for optional factor-research dependencies."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_BLOCKER = dedent(
    """\
    import importlib.abc
    import sys

    class BlockOptionalImports(importlib.abc.MetaPathFinder):
        def __init__(self, *roots):
            self.roots = roots

        def find_spec(self, fullname, path=None, target=None):
            if any(fullname == root or fullname.startswith(root + ".") for root in self.roots):
                raise ModuleNotFoundError("blocked optional dependency: " + fullname)
            return None

    sys.meta_path.insert(0, BlockOptionalImports(*sys.argv[1:]))

    def has_module(root):
        return any(name == root or name.startswith(root + ".") for name in sys.modules)
    """
)


def _run_fresh_python(
    script: str, *blocked_roots: str, light_import: bool = False
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if light_import:
        environment["BACKTRADER_LIGHT_IMPORT"] = "1"
    else:
        environment.pop("BACKTRADER_LIGHT_IMPORT", None)
    return subprocess.run(
        [sys.executable, "-c", script, *blocked_roots],
        cwd=str(_REPOSITORY_ROOT),
        env=environment,
        capture_output=True,
        text=True,
        timeout=45,
    )


@pytest.mark.parametrize("light_import", (False, True), ids=("default", "light"))
@pytest.mark.parametrize(
    "blocked_roots",
    (("pandas",), ("fincore",), ("pandas", "fincore")),
    ids=("pandas", "fincore", "pandas-and-fincore"),
)
def test_research_and_alpha_registry_import_without_optional_dependencies(
    blocked_roots: tuple[str, ...], light_import: bool
) -> None:
    script = _BLOCKER + dedent(
        """\
        import backtrader.research as research
        import backtrader.research.alpha101 as alpha101

        assert research.FactorStrategy is not None
        assert len(alpha101.ALPHA_REGISTRY) == 101
        assert alpha101.get_alpha(1) is alpha101.ALPHA_REGISTRY[1]
        assert len(alpha101.list_alphas()) == 101
        assert not has_module("pandas")
        assert not has_module("fincore")
        """
    )

    result = _run_fresh_python(script, *blocked_roots, light_import=light_import)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("light_import", (False, True), ids=("default", "light"))
def test_research_constructors_report_missing_pandas_dependency(light_import: bool) -> None:
    script = _BLOCKER + dedent(
        """\
        from backtrader.errors import DependencyError
        from backtrader.research import FactorPanel, ResearchSpec

        def assert_dependency_unavailable(action):
            try:
                action()
            except DependencyError as exc:
                assert exc.code == "DEPENDENCY_UNAVAILABLE"
            else:
                raise AssertionError("expected a typed pandas dependency error")

        assert_dependency_unavailable(lambda: ResearchSpec(
            grid=None,
            start=None,
            end=None,
            targets=("AAA",),
            source_timezone="UTC",
            snapshot_id="fixture-v1",
            price_basis="synthetic close",
            calendar_id="fixture-calendar-v1",
            frequency="1session",
        ))
        assert_dependency_unavailable(lambda: FactorPanel(
            factors=None,
            grid=None,
            prices_open=None,
            prices_close=None,
        ))
        assert not has_module("pandas")
        """
    )

    result = _run_fresh_python(script, "pandas", light_import=light_import)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("light_import", (False, True), ids=("default", "light"))
def test_evaluation_and_report_report_missing_fincore_dependency(light_import: bool) -> None:
    script = _BLOCKER + dedent(
        """\
        import pandas as pd

        from backtrader.errors import DependencyError
        from backtrader.research import FactorPanel, evaluate_frames, write_factor_report

        times = pd.date_range("2025-01-01", periods=2, freq="D", tz="UTC", name="close_time")
        grid = pd.DataFrame(
            {"open_time": times - pd.Timedelta(hours=6)},
            index=times,
        )
        index = pd.MultiIndex.from_product([times, ("AAA",)], names=("time", "asset"))
        factors = pd.DataFrame({"alpha": [0.1, 0.2]}, index=index)
        prices = pd.DataFrame({"AAA": [10.0, 11.0]}, index=times)
        panel = FactorPanel(
            factors=factors,
            grid=grid,
            prices_open=prices,
            prices_close=prices,
            start=times[0],
            end=times[-1],
            target_order=("AAA",),
            factor_order=("alpha",),
            directions={"alpha": 1},
        )

        def assert_dependency_unavailable(action):
            try:
                action()
            except DependencyError as exc:
                assert exc.code == "DEPENDENCY_UNAVAILABLE"
            except Exception as exc:
                raise AssertionError(
                    "expected DependencyError, got " + type(exc).__name__
                ) from exc
            else:
                raise AssertionError("expected a typed fincore dependency error")

        assert_dependency_unavailable(lambda: evaluate_frames(panel, {}))
        assert_dependency_unavailable(
            lambda: write_factor_report(panel, "alpha", "unused-report.html")
        )
        assert not has_module("fincore")
        """
    )

    result = _run_fresh_python(script, "fincore", light_import=light_import)
    assert result.returncode == 0, result.stdout + result.stderr
