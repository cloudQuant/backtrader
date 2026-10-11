"""013_1/013_2 CTP pair arbitrage examples: strategy + yaml + run.py coverage.

The two examples are loaded with unique module names (spec_from_file_location)
so their identically-named strategy/runner modules never collide inside one
pytest process.  The standard entry (``run.py``) delegates to
``legacy_runner.py``, so the replay-facing fixtures load the legacy engine.
"""

import copy
import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
EX1 = REPO / "examples" / "unified" / "013_1_midfreq_cross_arbitrage"
EX2 = REPO / "examples" / "unified" / "013_2_highfreq_calendar_arbitrage"

# Both examples now use their descriptive four-file strategy names and a
# legacy_runner module; the standard run.py delegates to the legacy engine.
STRATEGY_FILES = {EX1: "pair_arbitrage_strategy.py", EX2: "calendar_arbitrage_strategy.py"}
LEGACY_RUNNERS = {EX1: "legacy_runner.py", EX2: "legacy_runner.py"}


def load_module(directory, filename, name):
    """Load one example module from ``directory`` under a caller-chosen name."""
    # Example runners import a top-level strategy module from their own
    # directory; clear any cached one so the two example families never
    # cross-contaminate inside a single pytest process.
    for module_name in ("strategy", "pair_arbitrage_strategy", "calendar_arbitrage_strategy"):
        sys.modules.pop(module_name, None)
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
    """Return example 013_1's strategy module (module-scoped fixture)."""
    return load_module(EX1, STRATEGY_FILES[EX1], "ex013_1_strategy")


@pytest.fixture(scope="module")
def ex2():
    """Return example 013_2's strategy module (module-scoped fixture)."""
    return load_module(EX2, STRATEGY_FILES[EX2], "ex013_2_strategy")


@pytest.fixture(scope="module")
def run1():
    """Return example 013_1's legacy engine module (module-scoped fixture)."""
    return load_module(EX1, LEGACY_RUNNERS[EX1], "ex013_1_run")


@pytest.fixture(scope="module")
def run2():
    """Return example 013_2's legacy engine module (module-scoped fixture)."""
    return load_module(EX2, LEGACY_RUNNERS[EX2], "ex013_2_run")


def test_each_example_has_the_required_files():
    for directory in (EX1, EX2):
        assert (directory / STRATEGY_FILES[directory]).is_file()
        assert (directory / "run.py").is_file()
        assert (directory / LEGACY_RUNNERS[directory]).is_file()
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
    """Return a strategy class's declared parameters as a plain mapping."""
    return dict(strategy_class.params._getpairs())


def test_midfreq_defaults_are_slower_than_highfreq(ex1, ex2):
    slow_map = _defaults_of(ex1.PairArbitrageStrategy)
    fast_map = _defaults_of(ex2.PairArbitrageStrategy)
    assert slow_map["confirmations"] > fast_map["confirmations"]
    assert slow_map["entry_z"] > fast_map["entry_z"]
    assert slow_map["max_holding_seconds"] > fast_map["max_holding_seconds"]


@pytest.mark.parametrize("strategy_fixture", ("ex1", "ex2"))
def test_pair_now_avoids_platform_timestamp_conversion(request, monkeypatch, strategy_fixture):
    """Pair timing must not depend on platform ``datetime.timestamp()`` support."""

    module = request.getfixturevalue(strategy_fixture)

    class TimestampUnsafeDatetime(dt.datetime):
        def timestamp(self):
            raise OSError(22, "Invalid argument")

    bar_datetime = TimestampUnsafeDatetime(1969, 12, 31, 23, 59, 59)
    monkeypatch.setattr(module.bt, "num2date", lambda _value: bar_datetime)
    strategy = module.PairArbitrageStrategy
    holder = SimpleNamespace(data0=SimpleNamespace(datetime=[1.0]))

    assert strategy._now(holder) == -1.0


def test_runner_resolves_symbols_with_product_calendars(run1, run2):
    import datetime as dt

    today = dt.date(2026, 9, 6)
    # rb skips rb2610 (39 days to expiry) -> rb2701/rb2705.
    assert run2.resolve_symbols(today) == ["rb2701", "rb2705"]
    # m and rm pick their own nearest live contracts (DCE full / CZCE 3-digit).
    assert run1.resolve_symbols(today) == ["m2611", "RM611"]
    # CZCE RM lists no December contract: once Nov falls inside the expiry
    # guard, resolution rolls to the January contract and never invents RM612
    # (which no front serves; the 2026-10-10 rehearsal blocked on exactly that).
    later = dt.date(2026, 10, 10)
    assert run1.resolve_symbols(later) == ["m2612", "RM701"]


def test_pair_limit_refuses_without_an_executable_book(ex1):
    """A missing one-level book refuses pricing instead of faking a close."""
    strategy_class = ex1.PairArbitrageStrategy
    holder = SimpleNamespace(
        _quotes={}, p=SimpleNamespace(slippage_ticks=2.0, tick_size=1.0)
    )
    assert strategy_class._limit(holder, "m2612", "buy") is None
    holder._quotes["m2612"] = (100.0, 101.0)
    assert strategy_class._limit(holder, "m2612", "buy") == 103.0
    assert strategy_class._limit(holder, "m2612", "sell") == 98.0


def test_pair_engineering_trigger_requires_an_active_window(ex1):
    import time as _time

    strategy_class = ex1.PairArbitrageStrategy
    holder = SimpleNamespace(_engineering_trigger_fired=False)
    now = _time.time()
    holder.p = SimpleNamespace(
        engineering_trigger={
            "side": "long",
            "not_before_epoch": now - 5.0,
            "not_after_epoch": now + 5.0,
        }
    )
    assert strategy_class._engineering_trigger_side(holder) == "long"
    holder.p.engineering_trigger = {
        "side": "short",
        "not_before_epoch": now + 60.0,
        "not_after_epoch": now + 120.0,
    }
    assert strategy_class._engineering_trigger_side(holder) is None
    holder.p.engineering_trigger = {
        "side": "north",
        "not_before_epoch": now - 5.0,
        "not_after_epoch": now + 5.0,
    }
    assert strategy_class._engineering_trigger_side(holder) is None
    holder.p.engineering_trigger = {
        "side": "long",
        "not_before_epoch": now - 5.0,
        "not_after_epoch": now + 5.0,
    }
    holder._engineering_trigger_fired = True
    assert strategy_class._engineering_trigger_side(holder) is None


@pytest.mark.parametrize("fixture_name", ("ex1", "ex2"))
def test_pair_pending_drill_suppresses_natural_opens(request, fixture_name):
    """A pending drill trigger makes the bounded drill the only open path.

    Regression: a live rehearsal showed an immature natural z-signal consuming
    the single drill attempt before its trigger window opened, after which the
    drill could never fire (max_pairs=1).
    """

    module = request.getfixturevalue(fixture_name)
    strategy_class = module.PairArbitrageStrategy
    holder = SimpleNamespace(_engineering_trigger_fired=False)
    holder.p = SimpleNamespace(engineering_trigger={"side": "long"})
    assert strategy_class._natural_open_suppressed(holder) is True
    holder._engineering_trigger_fired = True
    assert strategy_class._natural_open_suppressed(holder) is False
    holder.p.engineering_trigger = None
    holder._engineering_trigger_fired = False
    assert strategy_class._natural_open_suppressed(holder) is False


@pytest.mark.parametrize("strategy_fixture", ("ex1", "ex2"))
def test_pair_drill_run_suppresses_natural_then_fires_in_window(
    request, strategy_fixture
):
    """A qualifying natural signal cannot open before the drill window; the
    drill itself fires on the first evaluation once the window opens."""

    import time as _time

    strategy_class = request.getfixturevalue(strategy_fixture).PairArbitrageStrategy
    now = _time.time()
    calls = []

    class _Broker:
        def getvalue(self):
            return 1000.0

    holder = SimpleNamespace(
        broker=_Broker(),
        initial_value=100.0,
        open_attempts=0,
        _engineering_trigger_fired=False,
        _direction=None,
        _confirmations=0,
        _last_evaluation=0.0,
        symbols=("first", "second"),
    )
    holder.p = SimpleNamespace(
        max_pairs=1,
        min_interval=0.0,
        entry_z=1.5,
        confirmations=1,
        max_loss=50.0,
        order_lots=1,
        engineering_trigger={
            "side": "long",
            "not_before_epoch": now + 3600.0,
            "not_after_epoch": now + 7200.0,
        },
    )
    holder._zscore = lambda: 9.9
    holder._mark_trade_logger_context_dirty = lambda: None
    holder.current_pair = None

    def _record_begin_legs(legs, action):
        calls.append((legs, action))
        holder.current_pair = {"legs": legs, "action": action, "reason": None}

    holder._begin_legs = _record_begin_legs
    holder._engineering_trigger_side = lambda: strategy_class._engineering_trigger_side(holder)
    holder._natural_open_suppressed = lambda: strategy_class._natural_open_suppressed(holder)

    strategy_class._try_open(holder, now)
    assert holder.open_attempts == 0
    assert calls == []

    holder.p.engineering_trigger = {
        "side": "long",
        "not_before_epoch": now - 5.0,
        "not_after_epoch": now + 300.0,
    }
    strategy_class._try_open(holder, now)
    assert holder._engineering_trigger_fired is True
    assert holder.open_attempts == 1
    assert calls and calls[0][1] == "open"
    legs = calls[0][0]
    assert legs[0]["symbol"] == "second" and legs[0]["side"] == "sell"
    assert legs[1]["symbol"] == "first" and legs[1]["side"] == "buy"
    assert legs[0]["lots"] == 1 and legs[1]["lots"] == 1


def test_runner_close_offset_follows_exchange_rules(run1, run2):
    assert run2.close_offset("rb2701") == "close_today"
    assert run1.close_offset("m2611") == "close"
    assert run1.close_offset("RM611") == "close"
    # The standard entries derive the offset from the real exchange metadata
    # instead of the product-prefix heuristic.
    assert run1.close_offset_for_exchange("DCE") == "close"
    assert run1.close_offset_for_exchange("CZCE") == "close"
    assert run2.close_offset_for_exchange("SHFE") == "close_today"
    assert run1.close_offset_for_exchange("SHFE") == "close_today"
    assert run1.close_offset_for_exchange("INE") == "close_today"


def _replay(run_module, scenario):
    """Run one replay scenario through ``run_module`` and return its report."""
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
        _engineering_trigger_fired=False,
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


@pytest.mark.parametrize(
    ("fixture_name", "directory"), (("ex1", EX1), ("ex2", EX2))
)
def test_pair_live_entries_bind_gfd_for_the_direct_ctp_lane(
    request, fixture_name, directory
):
    """CTP first-version orders require GFD; IOC is the replay-only default.

    Regression: the drill orders were rejected pre-native with
    ``unsupported_time_in_force`` ("CTP first-version orders require GFD;
    received IOC") on the direct registered-sim lane.
    """

    strategy_class = request.getfixturevalue(fixture_name).PairArbitrageStrategy
    assert _defaults_of(strategy_class)["time_in_force"] == "IOC"
    strategy_source = (directory / STRATEGY_FILES[directory]).read_text(encoding="utf-8")
    assert "time_in_force=str(self.p.time_in_force)" in strategy_source
    run_source = (directory / "run.py").read_text(encoding="utf-8")
    assert 'params["time_in_force"] = "GFD"' in run_source


def _dual_side_submit_harness(strategy_class):
    """Minimal strategy harness that exercises the real ``_submit`` kwargs."""
    strategy = object.__new__(strategy_class)
    strategy.p = SimpleNamespace(broker_position_mode="dual_side", time_in_force="GFD")
    strategy.close_offsets = {"leg": "close"}
    strategy._limit = lambda symbol, side: 100.0
    strategy._now = lambda: 0.0
    strategy._mark_trade_logger_context_dirty = lambda: None
    strategy.getdatabyname = lambda symbol: object()
    calls = []

    def _capture(name):
        def _submit(**kwargs):
            calls.append((name, kwargs))
            return SimpleNamespace(ref=len(calls))

        return _submit

    strategy.buy = _capture("buy")
    strategy.sell = _capture("sell")
    return strategy, calls


@pytest.mark.parametrize("strategy_fixture", ("ex1", "ex2"))
def test_pair_dual_side_legs_declare_the_position_each_order_touches(
    request, strategy_fixture
):
    """Opening names the created side; closing names the reduced side.

    Regression: the live rehearsal filled both entry legs and the exchange
    then rejected the close leg with "Invalid dual-side order combination"
    because the opening mapping was reused (sell -> short) with a close
    offset.  A sell that closes a long must declare position_side=long.
    """

    module = request.getfixturevalue(strategy_fixture)
    strategy, calls = _dual_side_submit_harness(module.PairArbitrageStrategy)

    def _cycle(action, first_side, second_side):
        strategy.current_pair = {"action": action, "order_refs": [], "last_submit": 0.0}
        strategy._submit("leg", first_side, 1)
        strategy._submit("leg", second_side, 1)

    _cycle("open", "buy", "sell")
    _cycle("close", "sell", "buy")

    assert [(name, kwargs["position_side"], kwargs["offset"]) for name, kwargs in calls] == [
        ("buy", "long", "open"),
        ("sell", "short", "open"),
        ("sell", "long", "close"),
        ("buy", "short", "close"),
    ]
