"""013_1/013_2 CTP pair arbitrage examples: strategy + yaml + run.py coverage.

The two examples are loaded with unique module names (spec_from_file_location)
so their identical ``strategy.py``/``run.py`` basenames never collide inside
one pytest process.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EX1 = REPO / "examples" / "013_1_midfreq_cross_arbitrage"
EX2 = REPO / "examples" / "013_2_highfreq_calendar_arbitrage"


def load_module(directory, filename, name):
    # Example runners import a top-level ``strategy`` module from their own
    # directory; clear any cached one so the two example families never
    # cross-contaminate inside a single pytest process.
    sys.modules.pop("strategy", None)
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location(name, directory / filename)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    finally:
        try:
            sys.path.remove(str(directory))
        except ValueError:
            pass
    return module


@pytest.fixture(scope="module")
def ex1():
    return load_module(EX1, "strategy.py", "ex013_1_strategy")


@pytest.fixture(scope="module")
def ex2():
    return load_module(EX2, "strategy.py", "ex013_2_strategy")


@pytest.fixture(scope="module")
def run1():
    return load_module(EX1, "run.py", "ex013_1_run")


@pytest.fixture(scope="module")
def run2():
    return load_module(EX2, "run.py", "ex013_2_run")


def test_each_example_has_the_three_required_files():
    for directory in (EX1, EX2):
        assert (directory / "strategy.py").is_file()
        assert (directory / "run.py").is_file()
        assert list(directory.glob("*.yaml")), f"missing yaml config in {directory}"


def test_strategies_subclass_backtrader_strategy_and_use_framework_indicator(ex1, ex2):
    import backtrader as bt
    import backtrader.indicators as btind

    for module in (ex1, ex2):
        strategy = module.PairArbitrageStrategy
        assert issubclass(strategy, bt.Strategy)
        assert strategy is not bt.Strategy
        assert btind.SpreadZScore  # framework indicator reused, not redefined
        assert "backtrader.indicators" in sys.modules
    assert ex1.PairArbitrageStrategy is not ex2.PairArbitrageStrategy


def _defaults_of(strategy_class):
    return dict(strategy_class.params._getpairs())


def test_midfreq_defaults_are_slower_than_highfreq(ex1, ex2):
    slow_map = _defaults_of(ex1.PairArbitrageStrategy)
    fast_map = _defaults_of(ex2.PairArbitrageStrategy)
    assert slow_map["confirmations"] > fast_map["confirmations"]
    assert slow_map["entry_z"] > fast_map["entry_z"]
    assert slow_map["max_holding_seconds"] > fast_map["max_holding_seconds"]


def test_runner_resolves_symbols_with_product_calendars(run1, run2):
    import datetime as dt

    today = dt.date(2026, 9, 6)
    # rb skips rb2610 (39 days to expiry) -> rb2701/rb2705.
    assert run2.resolve_symbols(today) == ["rb2701", "rb2705"]
    # m and rm pick their own nearest live contracts (DCE full / CZCE 3-digit).
    assert run1.resolve_symbols(today) == ["m2611", "RM611"]


def test_runner_close_offset_follows_exchange_rules(run1, run2):
    assert run2.close_offset("rb2701") == "close_today"
    assert run1.close_offset("m2611") == "close"
    assert run1.close_offset("RM611") == "close"


def _replay(run_module, scenario):
    report = run_module.run_replay(scenario)
    return report


@pytest.mark.parametrize("scenario", ["profitable", "loss", "no_edge"])
def test_example1_replay_scenarios(scenario, run1):
    report = _replay(run1, scenario)

    assert report["scenario"] == scenario
    assert all(size == 0 for size in report["positions"].values())
    if scenario == "profitable":
        assert report["pair_actions"] >= 1
        assert report["fees_paid"] > 0
    if scenario == "loss":
        assert report["halted"]
    if scenario == "no_edge":
        assert report["orders"] == []


@pytest.mark.parametrize("scenario", ["profitable", "loss", "no_edge"])
def test_example2_replay_scenarios(scenario, run2):
    report = _replay(run2, scenario)

    assert report["scenario"] == scenario
    assert all(size == 0 for size in report["positions"].values())
    if scenario == "profitable":
        assert report["pair_actions"] >= 1
    if scenario == "loss":
        assert report["halted"]
    if scenario == "no_edge":
        assert report["orders"] == []


def test_yaml_configs_match_strategy_defaults_and_runners(run1, run2):
    for run_module, directory in ((run1, EX1), (run2, EX2)):
        config = run_module.load_config(directory)
        params = config["strategy_params"]
        strategy_class = run_module.STRATEGY_CLASS
        defaults = _defaults_of(strategy_class)
        # Every yaml strategy_params key must be a real strategy parameter.
        assert set(params).issubset(set(defaults))
        assert config["symbols"] == ["auto"]
        assert config["simnow_env"] == "new_7x24"
