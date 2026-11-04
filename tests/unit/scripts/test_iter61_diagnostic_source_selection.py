"""Offline source-selection contracts for diagnostic checkout comparisons."""

from pathlib import Path
import subprocess
import sys
from textwrap import dedent

import pytest

ROOT = Path(__file__).resolve().parents[3]
DIAGNOSTIC = ROOT / "scripts" / "diagnose_factor_research_pipeline.py"
BENCHMARK = ROOT / "scripts" / "benchmark_factor_examples.py"
DAILY = ROOT / "examples" / "backtest" / "027_alpha003_panel_acceptance" / "run_daily.py"


def _checkout(root, layout, source="class FactorStrategy: pass\n"):
    for package in ("backtrader", "backtrader/research", "backtrader/strategies"):
        directory = root / package
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "__init__.py").write_text("", encoding="utf-8")
    path = root / "backtrader" / layout / "factor_strategy.py"
    path.write_text(source, encoding="utf-8")
    return path


def _run(script, root, body):
    program = dedent("""\
        import importlib, runpy, sys
        from pathlib import Path
        script, root = Path(sys.argv[1]), Path(sys.argv[2])
        namespace = runpy.run_path(str(script))
        sys.path.insert(0, str(root))
        importlib.import_module('backtrader.research')
    """) + dedent(body)
    return subprocess.run(
        [sys.executable, "-I", "-c", program, str(script), str(root)],
        capture_output=True,
        text=True,
        timeout=20,
    )


@pytest.mark.parametrize("script", (DIAGNOSTIC, BENCHMARK))
@pytest.mark.parametrize("layout", ("research", "strategies"))
def test_selected_checkout_layout_and_source_fingerprint(tmp_path, script, layout):
    path = _checkout(tmp_path, layout)
    body = dedent("""\
        module = namespace['_strategy_module'](root)
        assert Path(module.__file__).resolve() == root / 'backtrader' / sys.argv[3] / 'factor_strategy.py'
    """).replace("sys.argv[3]", repr(layout))
    if script == DIAGNOSTIC:
        body += dedent("""\
        origins, hashes = {}, {'backtrader/research/factor_strategy.py': 'stale',
                              'backtrader/strategies/factor_strategy.py': 'stale'}
        namespace['_record_strategy_source'](root, module, origins, hashes)
        assert list(hashes) == [str(Path(module.__file__).relative_to(root))]
        assert hashes[next(iter(hashes))] == namespace['_sha256'](Path(module.__file__))
        stage = namespace['_load_stage_benchmark'](root, module)
        assert stage._factor_strategy() is module.FactorStrategy
        import types
        bt = sys.modules['backtrader']
        class ReachedAddStrategy(Exception): pass
        class Cerebro:
            def __init__(self, **kwargs): pass
            def addstrategy(self, cls, **kwargs):
                assert cls is module.FactorStrategy
                raise ReachedAddStrategy()
        bt.Cerebro = Cerebro
        align = types.ModuleType('backtrader.research.align')
        align.align_to_grid = lambda *args, **kwargs: None
        sink = types.ModuleType('backtrader.research.sink')
        sink.MemorySink = lambda: object()
        sys.modules[align.__name__] = align
        sys.modules[sink.__name__] = sink
        stage._research_spec = lambda *args: object()
        stage._factor_specs = lambda *args: {}
        stage._rss = lambda: 0
        try:
            stage._run_panel('025', {}, {'assets': []}, {}, {}, runnext=False,
                             write_csv=False, report=False, evaluate=False, resident={},
                             stage_states={'align': {}})
        except ReachedAddStrategy:
            pass
        else:
            raise AssertionError('panel runner did not use the selected strategy')
        """)
    result = _run(script, tmp_path, body)
    assert result.returncode == 0, result.stderr
    assert path.is_file()


def test_benchmark_default_strategy_is_the_current_class():
    from backtrader.strategies.factor_strategy import FactorStrategy
    from scripts.benchmark_factor_research import _factor_strategy

    assert _factor_strategy() is FactorStrategy


@pytest.mark.parametrize("script", (DIAGNOSTIC, BENCHMARK))
def test_internal_import_error_is_not_treated_as_layout_fallback(tmp_path, script):
    _checkout(tmp_path, "research", "raise ImportError('internal sentinel')\n")
    result = _run(script, tmp_path, "namespace['_strategy_module'](root)\n")
    assert result.returncode != 0
    assert "ImportError: internal sentinel" in result.stderr


@pytest.mark.parametrize("script", (DIAGNOSTIC, BENCHMARK))
def test_reexported_class_is_not_recorded_as_owning_source(tmp_path, script):
    _checkout(
        tmp_path,
        "research",
        "FactorStrategy = type('FactorStrategy', (), {'__module__': 'elsewhere'})\n",
    )
    result = _run(script, tmp_path, "namespace['_strategy_module'](root)\n")
    assert result.returncode != 0
    assert "FactorStrategy is not defined in selected source" in result.stderr


@pytest.mark.parametrize("script", (DIAGNOSTIC, BENCHMARK))
def test_ambiguous_and_foreign_sources_are_rejected(tmp_path, script):
    selected = tmp_path / "selected"
    _checkout(selected, "research")
    _checkout(selected, "strategies")
    result = _run(script, selected, "namespace['_strategy_module'](root)\n")
    assert result.returncode != 0
    assert "expected exactly one FactorStrategy source" in result.stderr
    foreign = tmp_path / "foreign"
    _checkout(foreign, "research")
    result = _run(
        script,
        foreign,
        """\
        root = root.parent / 'selected'
        namespace['_strategy_module'](root)
    """,
    )
    assert result.returncode != 0
    assert "outside selected root" in result.stderr


@pytest.mark.parametrize("script", (DIAGNOSTIC, BENCHMARK))
@pytest.mark.parametrize("layout", ("research", "strategies"))
def test_preloaded_source_selects_one_of_two_layouts(tmp_path, script, layout):
    _checkout(tmp_path, "research")
    _checkout(tmp_path, "strategies")
    result = _run(
        script,
        tmp_path,
        """\
        name = 'backtrader.%s.factor_strategy'
        loaded = importlib.import_module(name)
        assert namespace['_strategy_module'](root) is loaded
    """ % layout,
    )
    assert result.returncode == 0, result.stderr


def test_daily_strategy_source_checks_class_identity_and_selected_root(tmp_path, monkeypatch):
    import runpy
    from types import ModuleType

    helper = runpy.run_path(str(DAILY))["_factor_strategy_source_path"]
    source = _checkout(tmp_path, "strategies")
    name = "backtrader.strategies.factor_strategy"
    module = ModuleType(name)
    module.__file__ = str(source)
    module.FactorStrategy = type("FactorStrategy", (), {"__module__": name})
    monkeypatch.setitem(sys.modules, name, module)
    assert helper(tmp_path, module.FactorStrategy) == str(source.resolve())
    with pytest.raises(ImportError, match="does not match selected checkout"):
        helper(tmp_path / "other", module.FactorStrategy)
    with pytest.raises(ImportError, match="does not match selected checkout"):
        helper(tmp_path, type("FactorStrategy", (), {"__module__": name}))
