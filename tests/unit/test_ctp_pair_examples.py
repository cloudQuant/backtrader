"""013_1/013_2 CTP pair arbitrage examples: strategy + yaml + run.py coverage.

The two examples are loaded with unique module names (spec_from_file_location)
so their identical ``strategy.py``/``run.py`` basenames never collide inside
one pytest process.
"""

import copy
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

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


@pytest.mark.parametrize("runner_fixture", ("run1", "run2"))
def test_final_pair_report_requires_frozen_trade_logger_extension(request, runner_fixture):
    """A pair runner must never export a live Observer snapshot as final evidence."""
    runner = request.getfixturevalue(runner_fixture)
    generic = {
        "finalized": True,
        "run_id": "generic-run",
        "extensions": {"pair_arbitrage": {"halted": False, "positions": {}}},
    }
    strategy = SimpleNamespace(
        stats=SimpleNamespace(trade_logger=SimpleNamespace(final_report=lambda: generic))
    )

    result = runner._final_pair_report(strategy)
    assert result["halted"] is False
    assert result["trade_logger"] == generic

    generic["finalized"] = False
    with pytest.raises(RuntimeError, match="not finalized"):
        runner._final_pair_report(strategy)

    generic.update(finalized=True, extensions={})
    with pytest.raises(RuntimeError, match="missing the pair_arbitrage extension"):
        runner._final_pair_report(strategy)

    generic["extensions"] = {"pair_arbitrage": {"halted": False, "positions": {}}}
    strategy._trade_logger_context_failed_since_success = True
    with pytest.raises(RuntimeError, match="stale after a publish failure"):
        runner._final_pair_report(strategy)


@pytest.mark.parametrize("runner_fixture", ("run1", "run2"))
def test_pair_extension_is_visible_in_a_live_trade_logger_snapshot(
    request, monkeypatch, runner_fixture
):
    """The strategy extension is observable before TradeLogger freezes it."""
    import backtrader as bt

    runner = request.getfixturevalue(runner_fixture)
    snapshots = []
    original_attach = runner._attach_trade_logger

    def attach_with_probe(cerebro, output_directory):
        original_attach(cerebro, output_directory)

        class SnapshotProbe(bt.Analyzer):
            def next(self):
                snapshots.append(copy.deepcopy(self.strategy.stats.trade_logger.snapshot()))

        cerebro.addanalyzer(SnapshotProbe, _name="trade_logger_snapshot_probe")

    monkeypatch.setattr(runner, "_attach_trade_logger", attach_with_probe)
    runner.run_replay("no_edge")

    live_extensions = [
        item.get("extensions", {}).get("pair_arbitrage", {})
        for item in snapshots
        if item.get("finalized") is False
    ]
    assert live_extensions
    assert any(item.get("ticks_seen", 0) > 0 for item in live_extensions)


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


@pytest.mark.parametrize("runner_fixture", ("run1", "run2"))
@pytest.mark.parametrize("scenario", ("profitable", "loss", "no_edge"))
def test_pair_replay_business_summary_is_stable_without_runtime_telemetry(
    request, runner_fixture, scenario
):
    runner = request.getfixturevalue(runner_fixture)

    first = runner.run_replay(scenario)
    second = runner.run_replay(scenario)

    assert first["trade_logger"]["finalized"] is True
    assert first["business_summary"] == second["business_summary"]
    assert first["business_summary_hash"] == second["business_summary_hash"]
    assert "trade_logger" not in first["business_summary"]


@pytest.mark.parametrize("runner_fixture", ("run1", "run2"))
def test_pair_business_summary_hash_excludes_trade_logger_runtime_data(request, runner_fixture):
    runner = request.getfixturevalue(runner_fixture)
    report = {
        "scenario": "no_edge",
        "positions": {"leg": 0.0},
        "execution_state": {"pending_order_ref": 5},
        "orders": [{"ref": 5, "symbol": "leg", "status": "Completed"}],
        "results": [{"action": "open", "order_refs": [5]}],
        "trade_logger": {
            "run_id": "observer-1",
            "generated_at": "2026-09-10T00:00:00+00:00",
            "event_counts": {"ticks": 1},
        },
    }

    expected = runner.business_summary_hash(report)
    changed = copy.deepcopy(report)
    changed["trade_logger"] = {
        "run_id": "observer-2",
        "generated_at": "2026-09-10T00:02:00+00:00",
        "event_counts": {"ticks": 999},
    }
    changed["business_summary_hash"] = expected
    changed["execution_state"] = {"pending_order_ref": 10}
    changed["orders"] = [{"ref": 10, "symbol": "leg", "status": "Completed"}]
    changed["results"] = [{"action": "open", "order_refs": [10]}]

    assert runner.business_summary_hash(changed) == expected
    changed["positions"] = {"leg": 1.0}
    assert runner.business_summary_hash(changed) != expected


class _GetterForbiddenBroker:
    def __init__(self):
        self.calls = {"cached": 0, "getvalue": 0, "getposition": 0}

    def get_cached_report_state(self):
        self.calls["cached"] += 1
        return {
            "value": 125.0,
            "positions": {
                "first": SimpleNamespace(size=2.0),
                "second": SimpleNamespace(size=-2.0),
            },
        }

    def getvalue(self):
        self.calls["getvalue"] += 1
        raise AssertionError("report context must not call getvalue")

    def getposition(self, _data):
        self.calls["getposition"] += 1
        raise AssertionError("report context must not call getposition")


@pytest.mark.parametrize("strategy_fixture", ("ex1", "ex2"))
def test_pair_report_context_uses_cached_state_only(request, strategy_fixture):
    strategy_class = request.getfixturevalue(strategy_fixture).PairArbitrageStrategy
    broker = _GetterForbiddenBroker()
    first = SimpleNamespace(_name="first")
    second = SimpleNamespace(_name="second")
    holder = SimpleNamespace(
        broker=broker,
        datas=(first, second),
        initial_value=100.0,
        ticks_seen=4,
        orders={},
        results=[],
        open_attempts=0,
        halted=False,
        halt_reason="",
        current_pair=None,
        pending_order=None,
        active_pair=None,
        stage=None,
    )
    holder._finite_float = strategy_class._finite_float
    holder._cached_position_size = strategy_class._cached_position_size
    holder._cached_broker_report_state = strategy_class._cached_broker_report_state.__get__(holder)
    holder._cached_positions = strategy_class._cached_positions.__get__(holder)
    holder._report_execution_state = strategy_class._report_execution_state.__get__(holder)

    context = strategy_class._report_context(holder)

    assert context["portfolio_value"] == 125.0
    assert context["net_pnl"] == 25.0
    assert context["positions"] == {"first": 2.0, "second": -2.0}
    assert broker.calls == {"cached": 1, "getvalue": 0, "getposition": 0}


@pytest.mark.parametrize(
    ("strategy_fixture", "ticks_seen", "expected_updates"),
    (("ex1", 1, 1), ("ex2", 1, 0), ("ex2", 128, 1)),
)
def test_pair_context_publication_is_rate_bounded(
    request, strategy_fixture, ticks_seen, expected_updates
):
    strategy_class = request.getfixturevalue(strategy_fixture).PairArbitrageStrategy
    updates = []
    holder = SimpleNamespace(
        trade_logger_tick_interval=strategy_class.trade_logger_tick_interval,
        ticks_seen=ticks_seen,
        _trade_logger_context_revision=0,
        _trade_logger_last_attempted_revision=0,
        _trade_logger_last_attempted_tick=0,
        _trade_logger_context_dirty=False,
        _trade_logger_context_failed_since_success=False,
        _trade_logger_context_last_error=None,
        stats=SimpleNamespace(
            trade_logger=SimpleNamespace(
                update_report_context=lambda context, namespace: updates.append(
                    (context, namespace)
                )
                or True
            )
        ),
        _report_context=lambda: {"ticks_seen": ticks_seen},
    )

    assert strategy_class._publish_trade_logger_context(holder) is True
    assert len(updates) == expected_updates


def test_highfreq_pair_publish_failure_is_rate_bounded_and_final_report_is_rejected(
    run2, monkeypatch
):
    """A failed HFT publication must not make every tick serialize context."""
    import backtrader as bt

    original_update = bt.observers.TradeLogger.update_report_context
    calls = []

    def accept_once_then_raise(observer, mapping, namespace="strategy"):
        calls.append(namespace)
        if len(calls) == 1:
            return original_update(observer, mapping, namespace=namespace)
        raise RuntimeError("injected publication failure")

    monkeypatch.setattr(bt.observers.TradeLogger, "update_report_context", accept_once_then_raise)
    with pytest.raises(RuntimeError, match="stale after a publish failure"):
        run2.run_replay("no_edge")

    # The replay has 120 ticks, below the 128-tick cadence.  The failed
    # startup-state publication and forced final attempt are still allowed;
    # a per-tick retry would have produced hundreds of calls.
    assert 2 <= len(calls) < 10
