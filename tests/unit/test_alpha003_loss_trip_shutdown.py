"""Source-fake regressions for the Alpha003 run-loss shutdown handoff.

The provider/query leaves come from the public no-I/O execution-facts fixture.
All Journal state uses SQLite ``:memory:``; these tests never load the example
profile or use a live provider, account, network connection, or order route.
"""

from __future__ import annotations

import builtins
import importlib.util
import io
import os
import socket
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_STRATEGY_PATH = (
    _ROOT / "examples" / "unified" / "028_alpha003_simnow_minute" / "alpha003_strategy.py"
)
_FACTS_FIXTURE_PATH = _ROOT / "tests" / "unit" / "stores" / "test_factor_execution_facts.py"
_RUNNER_PATH = _ROOT / "examples" / "unified" / "028_alpha003_simnow_minute" / "run.py"


@pytest.fixture
def sourcefake_io_guards(monkeypatch):
    """Fail if this source-fake test opens protected config or connects out."""

    audit = {"protected_reads": [], "network_attempts": []}
    original_builtin_open = builtins.open
    original_io_open = io.open
    original_os_open = os.open

    def check_path(path, operation):
        try:
            name = Path(os.fsdecode(os.fspath(path))).name.lower()
        except (OSError, TypeError, ValueError):
            return
        if name in {"config.yaml", "config.yml", ".env"} or name.startswith(".env."):
            audit["protected_reads"].append((operation, name))
            raise AssertionError("source-fake loss-exit test blocked protected input access")

    def guarded_builtin_open(file, *args, **kwargs):
        check_path(file, "builtins.open")
        return original_builtin_open(file, *args, **kwargs)

    def guarded_io_open(file, *args, **kwargs):
        check_path(file, "io.open")
        return original_io_open(file, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        check_path(path, "os.open")
        return original_os_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_builtin_open)
    monkeypatch.setattr(io, "open", guarded_io_open)
    monkeypatch.setattr(os, "open", guarded_os_open)

    def deny_network(operation):
        def denied(*_args, **_kwargs):
            audit["network_attempts"].append(operation)
            raise AssertionError("source-fake loss-exit test blocked network access")

        return denied

    monkeypatch.setattr(socket.socket, "connect", deny_network("socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", deny_network("socket.connect_ex"))
    monkeypatch.setattr(socket, "create_connection", deny_network("socket.create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", deny_network("socket.getaddrinfo"))
    yield audit
    assert audit == {"protected_reads": [], "network_attempts": []}


def _load_public_source(module_name: str, path: Path):
    module = sys.modules.get(module_name)
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("public source fixture is unavailable: " + path.name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_modules():
    strategy = _load_public_source("_alpha003_loss_trip_shutdown_strategy", _STRATEGY_PATH)
    facts_fixture = _load_public_source(
        "_alpha003_loss_trip_shutdown_facts_fixture", _FACTS_FIXTURE_PATH
    )
    example_dir = str(_RUNNER_PATH.parent)
    added_path = example_dir not in sys.path
    if added_path:
        sys.path.insert(0, example_dir)
    try:
        runner = _load_public_source("_alpha003_loss_trip_shutdown_runner", _RUNNER_PATH)
    finally:
        if added_path:
            sys.path.remove(example_dir)
    return strategy, facts_fixture, runner


def _account_row(close_profit=None):
    row = {
        "Available": "100000",
        "CurrMargin": "0",
        "PositionProfit": "0",
        "Commission": "0",
        "CurrencyID": "CNY",
        "TradingDay": "20261024",
    }
    if close_profit is not None:
        row["CloseProfit"] = close_profit
    return row


def _fresh_source_facts(facts_fixture, live, *, close_profit):
    """Refresh full fake rows and consume a quote after that exact query set."""

    api = live["api"]
    api.query_rows["account_result"] = [_account_row(close_profit)]
    api._use_observed_query_clock = True
    receipt = facts_fixture._refresh_all(live["store"], live["target"])

    # Risk-reduction evidence must pair the complete query set with a fresh,
    # current Store-consumed quote. The fixture's initial tick predates these
    # repeated query snapshots, so reuse would correctly fail the production
    # consumed_quote_unavailable gate.
    sequence = live["quote_sequence"] + 1
    query_completed_at = receipt.query_set.completed_at_utc
    received_at = max(datetime.now(timezone.utc), query_completed_at)
    api.tick = facts_fixture._quote(
        event_time=query_completed_at,
        received_at=received_at,
        sequence=sequence,
    )
    consumed = facts_fixture._consume_quote(live["store"])
    assert consumed is not None
    assert consumed.timestamp >= query_completed_at.timestamp()
    assert consumed.received_wall_time >= query_completed_at.timestamp()
    assert consumed.received_wall_time <= datetime.now(timezone.utc).timestamp()
    live["quote_sequence"] = sequence

    now = datetime.now(timezone.utc)
    facts = facts_fixture._project(
        live["store"], live["broker"], live["target"], now, query_set=receipt.query_set
    )
    assert facts.risk_reduction_ready is True, facts.risk_reduction_blockers
    assert facts.quotes[0].quality == "GOOD", facts.quotes[0]
    return receipt, now, facts


def _ready_signal(strategy, now):
    signal = strategy.Alpha003SignalTarget(
        target_id="rb",
        product_key=("SHFE", "rb"),
        target_position=-1,
        raw_score=1.0,
        oriented_score=1.0,
    )
    return strategy.Alpha003TargetDecision(
        status="TARGETS_READY",
        reason=None,
        factor_name="alpha003",
        mode="native",
        execution_mode="LIVE",
        direction=1,
        source_sha256="a" * 64,
        cohort_id="loss-exit-cohort",
        batch_id="loss-exit-batch",
        close_time=now - timedelta(seconds=2),
        available_at=now - timedelta(seconds=1),
        eligible_grid_index=1,
        rebalance_every=1,
        authorized_targets=("rb",),
        eligible_targets=("rb",),
        targets=(signal,),
    )


def _new_strategy(strategy_module, runner, live, receipt, facts, now):
    refresh_loop = object.__new__(runner.QueryRefreshLoop)
    refresh_loop.last_receipt = receipt
    risk_policy = strategy_module.Alpha003RiskPolicy(
        risk_policy_id="alpha003-loss-exit-test-v1",
        max_hold_eligible_bars=12,
        preclose_grace_seconds=60,
        run_end_policy="CLOSE_ALL",
        quote_max_age_seconds=Decimal("5"),
        max_state_age_seconds=Decimal("30"),
        max_notional_per_position=Decimal("2000"),
        max_total_notional=Decimal("3000"),
        max_margin_per_position=Decimal("250"),
        max_total_margin=Decimal("500"),
        max_loss_per_position=Decimal("20"),
        max_total_loss=Decimal("40"),
        stop_loss_ticks=2,
        max_order_intents_per_grid=2,
        max_order_intents_per_run=20,
        round_trip_fee_upper_bound_per_contract=Decimal("1"),
    )

    strategy = object.__new__(strategy_module.Alpha003TargetStrategy)
    strategy.p = SimpleNamespace(
        execution_enabled=True,
        replay_mode=False,
        control_refresh_loop=refresh_loop,
        cohort=SimpleNamespace(cohort_id="loss-exit-cohort"),
        live_ready_callback=None,
        live_capacity_callback=None,
        live_next_callback=None,
    )
    strategy._coordinator = live["coordinator"]
    strategy._account_scope = live["coordinator"].account_scope
    strategy._strategy_scope = live["coordinator"].strategy_scope
    strategy._logical_run_id = live["coordinator"].logical_run_id
    strategy._source_kind = "ALPHA003_GRID"
    strategy._loss_guard_net_loss_threshold = Decimal("1000")
    strategy._loss_guard_max_observation_age_seconds = 30
    strategy._risk_policy = risk_policy
    strategy._target_ids = (live["target"].target_id,)
    strategy._routes = {
        live["target"].target_id: (live["target"].instrument, live["target"].exchange)
    }
    strategy._authorized_targets = frozenset(strategy._target_ids)
    strategy._data_by_target = {live["target"].target_id: live["target"].data}
    strategy._orders_by_broker_ref = {}
    strategy._live_facts = lambda _now: facts
    strategy._last_signal_target = _ready_signal(strategy_module, now)
    strategy._live_shadow_order_count = 0
    strategy._shutdown_requested = Event()
    strategy._shutdown_ready_state = False
    strategy._shutdown_blocker_state = None
    strategy._shutdown_post_join_confirmed_state = False
    strategy._shutdown_post_join_blocker_state = "SHUTDOWN_POST_JOIN_CONFIRMATION_PENDING"
    strategy._shutdown_engine_stop_requested = False
    strategy._control_refresh_stopped = False
    strategy._last_shutdown_facts_id = None
    strategy.last_execution_block_reason = None
    strategy.last_order_plan = None
    return strategy, refresh_loop


def _build_flat_case(facts_fixture, *, journal_path=":memory:"):
    now = datetime.now(timezone.utc)
    rows = facts_fixture._query_rows(account=_account_row("1000"))
    api, store, broker, journal, coordinator, target = facts_fixture._system_under_test(
        now=now, rows=rows, journal_path=journal_path
    )
    live = {
        "api": api,
        "store": store,
        "broker": broker,
        "journal": journal,
        "coordinator": coordinator,
        "target": target,
        "quote_sequence": 0,
    }
    facts_fixture._arm(store)
    _receipt, _now, facts = _fresh_source_facts(
        facts_fixture, live, close_profit="1000"
    )
    # This fixture is intentionally a fake CTP/query/tick provider plus the
    # real Store, Broker, Coordinator and Journal projection.
    assert type(live["api"]).__name__ == "_FakeRegisteredSimWrapper"
    if str(journal_path) == ":memory:":
        assert live["journal"].path == ":memory:"
    else:
        assert Path(live["journal"].path) == Path(journal_path).resolve()
    return facts, live


def _seed_trip(strategy_module, facts_fixture, runner, live):
    baseline_receipt, baseline_now, baseline_facts = _fresh_source_facts(
        facts_fixture, live, close_profit="1000"
    )
    baseline_strategy, _baseline_loop = _new_strategy(
        strategy_module, runner, live, baseline_receipt, baseline_facts, baseline_now
    )
    context, blocker = baseline_strategy._refresh_run_loss_guard(
        baseline_facts, baseline_now
    )
    assert blocker is None
    assert context is not None

    loss_receipt, loss_now, loss_facts = _fresh_source_facts(
        facts_fixture, live, close_profit="0"
    )
    baseline_strategy.p.control_refresh_loop.last_receipt = loss_receipt
    trip_context, trip_blocker = baseline_strategy._refresh_run_loss_guard(
        loss_facts, loss_now
    )
    assert trip_context == context
    assert trip_blocker is None
    snapshot = live["journal"].run_loss_guard(
        live["coordinator"].account_scope,
        live["coordinator"].strategy_scope,
        live["coordinator"].logical_run_id,
    )
    assert snapshot is not None and snapshot.tripped is True
    return context, loss_receipt, loss_now, loss_facts


def _run_live_and_capture(
    strategy_module, strategy, facts, now, *, ordinal=None, session_close=None
):
    observed = []
    original_risk_decision = strategy_module.Alpha003TargetStrategy._live_risk_decision

    def record_risk_plan(batch, current_facts, plan, *, planning=None):
        observed.append((batch, current_facts, plan, planning))
        # Preserve the production shutdown-state update and real risk path.
        # The flat fixture produces no CLOSE/CANCEL action, so this cannot
        # dispatch an order.
        return original_risk_decision(
            strategy, batch, current_facts, plan, planning=planning
        )

    # Keep the real planner and _run_live orchestration.  Capture at the final
    # risk-decision boundary; the flat fake facts contain no dispatchable exit.
    strategy._live_risk_decision = record_risk_plan
    strategy._live_facts = lambda _now: facts
    strategy_module.Alpha003TargetStrategy._run_live(
        strategy,
        None,
        None,
        now,
        ordinal,
        session_close,
        False,
        is_new_batch=False,
    )
    assert len(observed) == 1
    return observed[0]


def test_fresh_loss_trip_requests_same_cycle_run_end_and_keeps_open_disabled(
    sourcefake_io_guards,
):
    strategy_module, facts_fixture, runner = _load_modules()
    _initial_facts, live = _build_flat_case(facts_fixture)
    try:
        baseline_receipt, baseline_now, baseline_facts = _fresh_source_facts(
            facts_fixture, live, close_profit="1000"
        )
        strategy, refresh_loop = _new_strategy(
            strategy_module, runner, live, baseline_receipt, baseline_facts, baseline_now
        )
        context, blocker = strategy._refresh_run_loss_guard(baseline_facts, baseline_now)
        assert blocker is None and context is not None

        loss_receipt, loss_now, loss_facts = _fresh_source_facts(
            facts_fixture, live, close_profit="0"
        )
        refresh_loop.last_receipt = loss_receipt
        _batch, observed_facts, plan, planning = _run_live_and_capture(
            strategy_module, strategy, loss_facts, loss_now
        )

        snapshot = live["journal"].run_loss_guard(
            strategy._account_scope, strategy._strategy_scope, strategy._logical_run_id
        )
        assert snapshot is not None and snapshot.tripped is True
        assert strategy.shutdown_requested is True
        assert planning.run_end is True
        assert planning.target_decision is None
        assert observed_facts is loss_facts
        assert plan.status == "NO_ACTION", (plan.status, plan.reason)
        assert plan.reason == "NO_FRESH_TARGET"
        assert plan.actions == ()
        assert not any(
            action.action == "SUBMIT" and action.position_effect == "OPEN"
            for action in plan.actions
        ), plan.actions
        # The fake source facts prove flatness. This is only pre-join
        # readiness; post-join confirmation remains a separate lifecycle step.
        assert strategy.shutdown_ready is True
        assert strategy.shutdown_blocker is None
        assert strategy.shutdown_post_join_confirmed is False

        from backtrader.stores.execution_decision_journal import (
            ExecutionDecisionKey,
            ExecutionDecisionJournalError,
            ExecutionIntentKey,
        )

        decision_key = ExecutionDecisionKey(
            account_scope=strategy._account_scope,
            strategy_scope=strategy._strategy_scope,
            logical_run_id=strategy._logical_run_id,
            cohort_id="loss-exit-open-after-trip",
            close_time=loss_now.isoformat().replace("+00:00", "Z"),
            decision_kind=strategy._source_kind,
        )
        open_key = ExecutionIntentKey(
            action="SUBMIT",
            instrument=live["target"].instrument,
            side="BUY",
            position_effect="OPEN",
            leg=0,
        )
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="RUN_TOTAL_NET_LOSS_LIMIT_REACHED",
        ):
            live["journal"].record_decision(
                decision_key,
                {"source": "loss-trip-sourcefake"},
                intent_keys=(open_key,),
                loss_guard_context=context,
            )
    finally:
        live["journal"].close()


def test_new_strategy_recovers_trip_from_same_open_journal(sourcefake_io_guards):
    strategy_module, facts_fixture, runner = _load_modules()
    _initial_facts, live = _build_flat_case(facts_fixture)
    try:
        _context, loss_receipt, loss_now, loss_facts = _seed_trip(
            strategy_module, facts_fixture, runner, live
        )
        restarted, _loop = _new_strategy(
            strategy_module, runner, live, loss_receipt, loss_facts, loss_now
        )
        assert restarted.shutdown_requested is False

        _batch, _facts, plan, planning = _run_live_and_capture(
            strategy_module, restarted, loss_facts, loss_now
        )

        assert restarted.shutdown_requested is True
        assert planning.run_end is True
        assert planning.target_decision is None
        assert plan.actions == ()
        assert restarted.shutdown_ready is True
        assert restarted.shutdown_blocker is None
    finally:
        live["journal"].close()


def test_closed_and_reopened_journal_restores_trip_into_same_cycle_run_end(
    sourcefake_io_guards, tmp_path
):
    strategy_module, facts_fixture, runner = _load_modules()
    journal_path = tmp_path / "alpha003-run-loss-guard.sqlite3"
    _initial_facts, live = _build_flat_case(
        facts_fixture, journal_path=journal_path
    )
    try:
        _context, loss_receipt, loss_now, loss_facts = _seed_trip(
            strategy_module, facts_fixture, runner, live
        )
        before_close = live["journal"].run_loss_guard(
            live["coordinator"].account_scope,
            live["coordinator"].strategy_scope,
            live["coordinator"].logical_run_id,
        )
        assert before_close is not None and before_close.tripped is True
        live["journal"].close()

        from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal

        reopened_journal = ExecutionDecisionJournal(journal_path)
        live["journal"] = reopened_journal
        live["coordinator"].journal = reopened_journal
        after_reopen = reopened_journal.run_loss_guard(
            live["coordinator"].account_scope,
            live["coordinator"].strategy_scope,
            live["coordinator"].logical_run_id,
        )
        assert after_reopen == before_close

        restarted, _loop = _new_strategy(
            strategy_module, runner, live, loss_receipt, loss_facts, loss_now
        )
        _batch, _facts, plan, planning = _run_live_and_capture(
            strategy_module, restarted, loss_facts, loss_now
        )

        assert restarted.shutdown_requested is True
        assert planning.run_end is True
        assert planning.target_decision is None
        assert plan.actions == ()
        assert restarted.shutdown_ready is True
        assert restarted.shutdown_blocker is None
        assert restarted.shutdown_post_join_confirmed is False
    finally:
        live["journal"].close()


def test_persisted_trip_with_missing_facts_requests_shutdown_but_stays_blocked(
    sourcefake_io_guards,
):
    strategy_module, facts_fixture, runner = _load_modules()
    _initial_facts, live = _build_flat_case(facts_fixture)
    try:
        _context, receipt, now, _loss_facts = _seed_trip(
            strategy_module, facts_fixture, runner, live
        )
        strategy, _loop = _new_strategy(
            strategy_module, runner, live, receipt, None, now
        )
        strategy._live_facts = lambda _now: None

        strategy_module.Alpha003TargetStrategy._run_live(
            strategy,
            None,
            None,
            now,
            None,
            None,
            False,
            is_new_batch=False,
        )

        assert strategy.shutdown_requested is True
        assert strategy.last_order_plan.status == "BLOCKED"
        assert strategy.last_order_plan.reason == "EXECUTION_FACTS_UNAVAILABLE"
        assert strategy.shutdown_ready is False
        assert strategy.shutdown_blocker == "SHUTDOWN_FACTS_UNAVAILABLE"
        assert strategy.shutdown_post_join_confirmed is False
    finally:
        live["journal"].close()


def test_journal_read_error_with_missing_facts_does_not_escape_or_report_ready(
    sourcefake_io_guards, monkeypatch
):
    strategy_module, facts_fixture, runner = _load_modules()
    _initial_facts, live = _build_flat_case(facts_fixture)
    try:
        _context, receipt, now, _loss_facts = _seed_trip(
            strategy_module, facts_fixture, runner, live
        )
        strategy, _loop = _new_strategy(
            strategy_module, runner, live, receipt, None, now
        )
        strategy._live_facts = lambda _now: None

        from backtrader.stores.execution_decision_journal import (
            ExecutionDecisionJournalError,
        )

        def unavailable_run_loss_guard(*_args, **_kwargs):
            raise ExecutionDecisionJournalError("JOURNAL_READ_UNAVAILABLE")

        monkeypatch.setattr(live["journal"], "run_loss_guard", unavailable_run_loss_guard)

        # Journal state is indeterminate, so _run_live must fail closed rather
        # than allowing this read exception to escape or declaring shutdown
        # readiness from absent execution facts.
        strategy_module.Alpha003TargetStrategy._run_live(
            strategy,
            None,
            None,
            now,
            None,
            None,
            False,
            is_new_batch=False,
        )

        assert strategy.last_order_plan.status == "BLOCKED"
        assert strategy.shutdown_ready is False
        assert strategy.shutdown_post_join_confirmed is False
        assert strategy.last_execution_block_reason is not None
    finally:
        live["journal"].close()


def test_journal_read_failure_blocks_source_backed_open_candidate(
    sourcefake_io_guards, monkeypatch
):
    strategy_module, facts_fixture, runner = _load_modules()
    _initial_facts, live = _build_flat_case(facts_fixture)
    try:
        receipt, now, facts = _fresh_source_facts(
            facts_fixture, live, close_profit="1000"
        )
        assert facts.open_risk_ready is True, facts.open_risk_blockers
        strategy, _loop = _new_strategy(
            strategy_module, runner, live, receipt, facts, now
        )
        strategy._risk_policy = replace(
            strategy._risk_policy,
            max_loss_per_position=Decimal("100"),
            max_total_loss=Decimal("300"),
        )

        from backtrader.stores.execution_decision_journal import (
            ExecutionDecisionJournalError,
        )

        def unavailable_run_loss_guard(*_args, **_kwargs):
            raise ExecutionDecisionJournalError("JOURNAL_READ_FAILED")

        monkeypatch.setattr(live["journal"], "run_loss_guard", unavailable_run_loss_guard)

        _batch, observed_facts, candidate_plan, planning = _run_live_and_capture(
            strategy_module,
            strategy,
            facts,
            now,
            ordinal=1,
            session_close=now + timedelta(hours=1),
        )
        assert observed_facts is facts
        assert strategy.last_execution_block_reason == "JOURNAL_READ_FAILED"
        assert candidate_plan.status == "READY", (
            candidate_plan.status,
            candidate_plan.reason,
            facts.open_risk_blockers,
        )
        assert any(
            action.action == "SUBMIT" and action.position_effect == "OPEN"
            for action in candidate_plan.actions
        ), candidate_plan.actions

        signal = strategy._last_signal_target
        batch = SimpleNamespace(
            status="COMPLETE",
            batch_id=signal.batch_id,
            cohort_id=signal.cohort_id,
            calendar_id="loss-exit-calendar-v1",
            epoch_id=1,
            close_time=signal.close_time,
            available_at=signal.available_at,
        )
        snapshot = SimpleNamespace(
            readiness="LIVE_READY",
            batch_complete=True,
            batch_id=batch.batch_id,
            cohort_id=batch.cohort_id,
            calendar_id=batch.calendar_id,
            epoch_id=batch.epoch_id,
            close_time=batch.close_time,
            factors={
                "alpha003": SimpleNamespace(source_sha256=signal.source_sha256)
            },
        )
        strategy.p.cohort = SimpleNamespace(
            cohort_id=batch.cohort_id,
            current_batch=lambda: batch,
        )
        strategy.live_factors = SimpleNamespace(snapshot=lambda: snapshot)
        dispatched = []
        strategy._dispatch_live_actions = lambda actions, _batch: dispatched.append(actions)

        from backtrader.stores.execution_decision_journal import ExecutionDecisionKey

        decision_key = ExecutionDecisionKey(
            account_scope=strategy._account_scope,
            strategy_scope=strategy._strategy_scope,
            logical_run_id=strategy._logical_run_id,
            cohort_id=batch.cohort_id,
            close_time=strategy_module._time_key(batch.close_time),
            decision_kind=strategy._source_kind,
        )
        assert live["journal"].decision_for_key(decision_key) is None

        recorded = strategy._live_grid_decision(
            batch,
            snapshot,
            facts,
            candidate_plan,
            planning=planning,
            proposed_plan=candidate_plan,
            loss_guard_context=None,
            loss_guard_blocker=strategy.last_execution_block_reason,
        )

        assert recorded is False
        assert strategy.last_execution_block_reason == "JOURNAL_READ_FAILED"
        assert strategy.last_order_plan.status == "BLOCKED"
        assert strategy.last_order_plan.actions == ()
        assert not any(
            action.action == "SUBMIT" and action.position_effect == "OPEN"
            for action in strategy.last_order_plan.actions
        )
        assert dispatched == []
        assert live["journal"].decision_for_key(decision_key) is None
    finally:
        live["journal"].close()


def test_repeated_shutdown_request_preserves_successful_post_join_confirmation(
    sourcefake_io_guards,
):
    strategy_module, facts_fixture, runner = _load_modules()
    _initial_facts, live = _build_flat_case(facts_fixture)
    try:
        receipt, now, facts = _fresh_source_facts(
            facts_fixture, live, close_profit="1000"
        )
        strategy, _loop = _new_strategy(
            strategy_module, runner, live, receipt, facts, now
        )
        strategy._clock_now = lambda: now
        joins = []
        strategy.p.control_refresh_loop = SimpleNamespace(
            stop_and_join=lambda: joins.append("joined")
        )

        strategy.request_shutdown()
        strategy._stop_control_refresh_loop()
        strategy._confirm_shutdown_post_join()

        assert joins == ["joined"]
        assert strategy.shutdown_ready is True
        assert strategy.shutdown_post_join_confirmed is True
        assert strategy.shutdown_post_join_blocker is None
        confirmed_facts_id = strategy._last_shutdown_facts_id

        strategy.request_shutdown()

        assert strategy.shutdown_requested is True
        assert strategy.shutdown_ready is True
        assert strategy.shutdown_post_join_confirmed is True
        assert strategy.shutdown_post_join_blocker is None
        assert strategy._last_shutdown_facts_id == confirmed_facts_id
    finally:
        live["journal"].close()


def test_persisted_trip_with_source_backed_stale_facts_stays_blocked_not_flat(
    sourcefake_io_guards,
):
    strategy_module, facts_fixture, runner = _load_modules()
    _initial_facts, live = _build_flat_case(facts_fixture)
    try:
        _context, _trip_receipt, trip_now, _trip_facts = _seed_trip(
            strategy_module, facts_fixture, runner, live
        )

        # Return provider query timestamps from a full minute ago. The Store,
        # Broker and facts projector remain real; only the fake CTP query clock
        # is stale. The existing quote must not make old account/order facts
        # current.
        live["api"]._use_observed_query_clock = False
        live["api"].query_time = trip_now - timedelta(seconds=60)
        stale_receipt = facts_fixture._refresh_all(live["store"], live["target"])
        stale_now = datetime.now(timezone.utc)
        stale_facts = facts_fixture._project(
            live["store"],
            live["broker"],
            live["target"],
            stale_now,
            query_set=stale_receipt.query_set,
        )

        assert stale_receipt.query_set.completed_at_utc <= stale_now - timedelta(seconds=30)
        assert stale_facts.read_only_reconciliation_ready is False
        assert stale_facts.read_only_reconciliation_blockers
        assert any(
            item.completed_at is not None
            and stale_now - item.completed_at >= timedelta(seconds=30)
            for item in stale_receipt.query_provenance
        )

        strategy, _loop = _new_strategy(
            strategy_module,
            runner,
            live,
            stale_receipt,
            stale_facts,
            stale_now,
        )
        _batch, observed_facts, plan, planning = _run_live_and_capture(
            strategy_module, strategy, stale_facts, stale_now
        )

        persisted = live["journal"].run_loss_guard(
            strategy._account_scope,
            strategy._strategy_scope,
            strategy._logical_run_id,
        )
        assert persisted is not None and persisted.tripped is True
        assert observed_facts is stale_facts
        assert strategy.shutdown_requested is True
        assert planning.run_end is True
        assert planning.target_decision is None
        assert plan.status == "BLOCKED"
        assert plan.actions == ()
        assert strategy.shutdown_ready is False
        assert strategy.shutdown_blocker.startswith(
            "SHUTDOWN_RECONCILIATION_BLOCKED:"
        )
        assert strategy.shutdown_post_join_confirmed is False
    finally:
        live["journal"].close()


def test_persisted_trip_with_unbound_facts_stays_blocked_not_flat(sourcefake_io_guards):
    strategy_module, facts_fixture, runner = _load_modules()
    _initial_facts, live = _build_flat_case(facts_fixture)
    try:
        _context, loss_receipt, loss_now, loss_facts = _seed_trip(
            strategy_module, facts_fixture, runner, live
        )
        blocked_facts = replace(loss_facts, available_at=None)
        assert blocked_facts.read_only_reconciliation_ready is False
        restarted, _loop = _new_strategy(
            strategy_module, runner, live, loss_receipt, blocked_facts, loss_now
        )

        _batch, _facts, plan, planning = _run_live_and_capture(
            strategy_module, restarted, blocked_facts, loss_now
        )

        assert restarted.shutdown_requested is True
        assert planning.run_end is True
        assert planning.target_decision is None
        assert plan.status == "BLOCKED"
        assert plan.actions == ()
        assert restarted.shutdown_ready is False
        assert restarted.shutdown_blocker.startswith("SHUTDOWN_RECONCILIATION_BLOCKED:")
        assert restarted.shutdown_post_join_confirmed is False
    finally:
        live["journal"].close()


def test_loss_guard_validation_blocker_alone_does_not_request_shutdown(
    sourcefake_io_guards,
):
    strategy_module, facts_fixture, runner = _load_modules()
    _initial_facts, live = _build_flat_case(facts_fixture)
    try:
        receipt, now, facts = _fresh_source_facts(
            facts_fixture, live, close_profit=None
        )
        # Missing account PnL makes the guard fail closed for OPEN but does not
        # prove a loss trip and therefore must not initiate an exit.
        strategy, _loop = _new_strategy(
            strategy_module, runner, live, receipt, facts, now
        )
        # The first complete but unqualified row must not establish a baseline.
        strategy.p.control_refresh_loop.last_receipt = receipt
        strategy._live_facts = lambda _now: facts
        result = strategy._refresh_run_loss_guard(facts, now)
        assert result[0] is None
        assert result[1] is not None
        _batch, _facts, _plan, planning = _run_live_and_capture(
            strategy_module, strategy, facts, now
        )
        assert strategy.shutdown_requested is False
        assert planning.run_end is False
        assert live["journal"].run_loss_guard(
            strategy._account_scope, strategy._strategy_scope, strategy._logical_run_id
        ) is None
    finally:
        live["journal"].close()
