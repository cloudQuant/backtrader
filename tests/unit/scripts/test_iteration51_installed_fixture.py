"""Focused contracts for the external Iteration 51 installed-wheel CLI fixture."""

from __future__ import annotations

import ast
from dataclasses import replace
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from collections.abc import Mapping
from pathlib import Path
import sys
import threading
import time
import types
from types import ModuleType, SimpleNamespace
from typing import Optional

import pytest


_FIXTURE_PATH = Path(__file__).resolve().parents[3] / "scripts" / "iteration51_installed_fixture.py"
_ITERATION50_FIXTURE_PATH = _FIXTURE_PATH.with_name("iteration50_installed_fixture.py")
_FACTS_INTEGRATION_HELPER_PATH = (
    _FIXTURE_PATH.parents[1]
    / "tests"
    / "unit"
    / "stores"
    / "test_factor_execution_facts.py"
)


def _load_fixture() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "iteration51_installed_fixture_test", _FIXTURE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_iteration50_fixture() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "iteration50_installed_fixture_clock_test", _ITERATION50_FIXTURE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_factor_execution_facts_test_helpers() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "iteration51_factor_execution_facts_test_support",
        _FACTS_INTEGRATION_HELPER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FixedUTCClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def utc_now(self) -> datetime:
        return self._now


def _source_loaded_refresh_case(
    helper: ModuleType,
    runner: ModuleType,
    clock: _FixedUTCClock,
    *,
    bind_query_clock: bool,
):
    from backtrader.brokers.btapibroker import BtApiBroker
    from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal
    from backtrader.stores.factor_execution import FactorExecutionCoordinator
    from backtrader.stores.factor_execution_facts import FactorExecutionTarget
    from backtrader.stores.registered_sim import RegisteredSimStore, RegisteredSimWrapper

    instrument = "M2611"
    helper._TARGETS = (instrument,)

    class _SourceLoadedRegisteredSimApi(RegisteredSimWrapper, helper._ExecutionProviderLeaf):
        pass

    api = _SourceLoadedRegisteredSimApi(
        registered_sim_allow_writes=False,
        bars={instrument: ({},)},
        slot_count=1,
    )
    api.is_read_only_ready = True
    if bind_query_clock:
        api._query_utc_clock = clock
    store = RegisteredSimStore(api=api, allow_writes=False)
    # This source-loaded integration keeps the actual Store and Broker while
    # replacing only the provider leaves; no connect or account operation runs.
    store._connected = True
    broker = BtApiBroker(
        store=store,
        contract_metadata={
            instrument: {"instrument_id": instrument, "exchange_id": "DCE"}
        },
    )
    journal = ExecutionDecisionJournal(":memory:")
    coordinator = FactorExecutionCoordinator(
        broker,
        journal,
        account_scope=api._account_fingerprint,
        strategy_scope="fixture-strategy",
        logical_run_id="fixture-query-clock",
        max_order_intents_per_grid=4,
        max_order_intents_per_run=20,
    )
    target = FactorExecutionTarget(
        "DCE.M", instrument, "DCE", SimpleNamespace(_name=instrument)
    )
    loop = runner.QueryRefreshLoop(
        store,
        broker,
        (target,),
        execution_target_ids=(target.target_id,),
        coordinator=coordinator,
        account_scope=api._account_fingerprint,
        strategy_scope="fixture-strategy",
        clock=clock,
        quote_max_age=timedelta(seconds=60),
        max_query_age=timedelta(seconds=60),
        timeout=0.2,
        overall_timeout=2.0,
        interval=1.0,
        cerebro=SimpleNamespace(),
        shutdown_grace_seconds=1.0,
    )
    return api, store, journal, target, loop


def test_initial_query_refresh_uses_shared_synthetic_utc_and_real_monotonic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backtrader.stores.factor_execution_facts import _BASE_FAMILIES

    runner_path = (
        _FIXTURE_PATH.parents[1]
        / "examples"
        / "unified"
        / "028_alpha003_simnow_minute"
        / "run.py"
    )
    monkeypatch.syspath_prepend(str(runner_path.parent))
    runner_spec = importlib.util.spec_from_file_location(
        "alpha003_simnow_query_clock_source_test", runner_path
    )
    assert runner_spec is not None and runner_spec.loader is not None
    runner = importlib.util.module_from_spec(runner_spec)
    sys.modules[runner_spec.name] = runner
    runner_spec.loader.exec_module(runner)

    helper = _load_iteration50_fixture()
    clock = _FixedUTCClock(datetime.now(timezone.utc) - timedelta(seconds=1))
    host_api, host_store, host_journal, _host_target, host_loop = (
        _source_loaded_refresh_case(
            helper, runner, clock, bind_query_clock=False
        )
    )
    try:
        assert not hasattr(host_api, "_query_utc_clock")
        host_before = datetime.now(timezone.utc)
        monotonic_before = time.monotonic()
        default_result = host_api.query_account_result()
        monotonic_after = time.monotonic()
        host_after = datetime.now(timezone.utc)
        assert host_before <= default_result.started_at_utc
        assert default_result.started_at_utc <= default_result.completed_at_utc
        assert default_result.completed_at_utc <= host_after
        assert (
            monotonic_before
            <= default_result.query_source.started_monotonic
            <= default_result.query_source.completed_monotonic
            <= monotonic_after
        )

        receipt = host_loop.refresh_initial(wait_timeout=2.0)
        assert receipt is host_loop.last_receipt
        assert host_loop.last_error_code == "LIVE_QUERY_SET_UNAVAILABLE"
        assert host_loop.last_facts is None
        assert receipt.query_set is None
        assert set(host_store._ctp_query_results) == set(_BASE_FAMILIES) | {
            "instrument_margin_rate_result"
        }
        assert (
            host_store._ctp_query_results["account_result"]["completed_at_utc"]
            > clock.utc_now()
        )
    finally:
        host_journal.close()

    from backtrader.stores.factor_execution_facts import refresh_factor_execution_queries

    future_clock = _FixedUTCClock(datetime.now(timezone.utc) + timedelta(hours=1))
    future_api, future_store, future_journal, future_target, future_loop = (
        _source_loaded_refresh_case(
            helper, runner, future_clock, bind_query_clock=True
        )
    )
    try:
        assert future_api._query_utc_clock is future_clock is future_loop.clock
        default_monotonic_before = time.monotonic()
        default_receipt = refresh_factor_execution_queries(
            future_store, targets=(future_target,), overall_timeout=2.0
        )
        default_monotonic_after = time.monotonic()
        assert default_receipt.query_set is None
        assert default_receipt.deadline_reached is False
        assert default_receipt.completed_at < future_clock.utc_now()
        assert all(
            fact.completed_at is not None
            and fact.completed_at > default_receipt.completed_at
            for fact in default_receipt.query_provenance
        )
        assert all(
            default_monotonic_before
            <= result["source_started_monotonic"]
            <= result["source_completed_monotonic"]
            <= default_monotonic_after
            < result["source_expires_monotonic"]
            for result in future_store._ctp_query_results.values()
        )

        monotonic_before = time.monotonic()
        receipt = future_loop.refresh_initial(wait_timeout=2.0)
        monotonic_after = time.monotonic()
        assert receipt is future_loop.last_receipt
        assert future_loop.last_error_code is None
        assert future_loop.last_facts.snapshot_id
        assert future_loop.last_facts.query_set_id
        assert receipt.query_set is not None
        assert receipt.query_set.started_at_utc == future_clock.utc_now()
        assert receipt.query_set.completed_at_utc == future_clock.utc_now()
        assert len(future_api.native_calls) == 0
        assert set(future_store._ctp_query_results) == set(_BASE_FAMILIES) | {
            "instrument_margin_rate_result"
        }
        for result in future_store._ctp_query_results.values():
            assert result["started_at_utc"] == future_clock.utc_now()
            assert result["completed_at_utc"] == future_clock.utc_now()
            assert monotonic_before <= result["source_started_monotonic"]
            assert (
                result["source_started_monotonic"]
                <= result["source_completed_monotonic"]
                <= monotonic_after
            )
            assert result["source_expires_monotonic"] > monotonic_after
        assert all(
            fact.source_owned is True
            and fact.query_complete is True
            and fact.completed_at <= future_clock.utc_now()
            for fact in future_loop.last_facts.query_provenance
        )
    finally:
        future_journal.close()

    aligned_api, aligned_store, aligned_journal, target, aligned_loop = (
        _source_loaded_refresh_case(
            helper, runner, clock, bind_query_clock=True
        )
    )
    try:
        assert aligned_api._query_utc_clock is clock is aligned_loop.clock
        monotonic_before = time.monotonic()
        receipt = aligned_loop.refresh_initial(wait_timeout=2.0)
        monotonic_after = time.monotonic()

        assert receipt is aligned_loop.last_receipt
        assert aligned_loop.last_error_code is None
        assert aligned_loop.last_facts.snapshot_id
        assert aligned_loop.last_facts.query_set_id
        assert aligned_loop.last_facts.target_ids == (target.target_id,)
        assert len(aligned_api.native_calls) == 0
        assert set(aligned_store._ctp_query_results) == set(_BASE_FAMILIES) | {
            "instrument_margin_rate_result"
        }
        for facts in aligned_store._ctp_query_results.values():
            assert facts["started_at_utc"] == clock.utc_now()
            assert facts["completed_at_utc"] == clock.utc_now()
            assert (
                monotonic_before
                <= facts["source_started_monotonic"]
                <= facts["source_completed_monotonic"]
                <= monotonic_after
            )
            assert facts["source_expires_monotonic"] > monotonic_after
        assert all(
            fact.source_owned is True
            and fact.query_complete is True
            and fact.completed_at <= clock.utc_now()
            for fact in aligned_loop.last_facts.query_provenance
        )
    finally:
        aligned_journal.close()


def test_write_refresh_barrier_waits_on_the_real_query_refresh_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_path = (
        _FIXTURE_PATH.parents[1]
        / "examples"
        / "unified"
        / "028_alpha003_simnow_minute"
        / "run.py"
    )
    monkeypatch.syspath_prepend(str(runner_path.parent))
    runner_spec = importlib.util.spec_from_file_location(
        "alpha003_simnow_refresh_barrier_source_test", runner_path
    )
    assert runner_spec is not None and runner_spec.loader is not None
    runner = importlib.util.module_from_spec(runner_spec)
    sys.modules[runner_spec.name] = runner
    runner_spec.loader.exec_module(runner)

    fixture = _load_fixture()
    helper = _load_iteration50_fixture()
    clock = _FixedUTCClock(datetime.now(timezone.utc) - timedelta(seconds=1))
    api, _store, journal, _target, loop = _source_loaded_refresh_case(
        helper, runner, clock, bind_query_clock=True
    )
    child_tree = ast.parse(fixture._SYNTHETIC_LIVE_CHILD_CODE)
    barrier_node = next(
        node
        for node in child_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SyntheticQueryRefreshBarrier"
    )
    fake_state = {"synthetic_fill_count": 0, "synthetic_engine_fills": []}
    namespace = {
        "threading": threading,
        "_real_time": time,
        "datetime": datetime,
        "Mapping": Mapping,
        "Decimal": Decimal,
        "InvalidOperation": InvalidOperation,
        "fake_state": fake_state,
    }
    exec(
        compile(ast.Module(body=[barrier_node], type_ignores=[]), "<refresh-barrier>", "exec"),
        namespace,
    )
    barrier = namespace["SyntheticQueryRefreshBarrier"](
        enabled=True,
        max_order_intents_per_run=20,
        per_barrier_timeout=8.0,
    )
    loop_class = type(loop)
    original_refresh_once = loop_class.refresh_once
    assert barrier.install(loop_class) is True
    try:
        initial = loop.refresh_initial(wait_timeout=2.0)
        assert initial is loop.last_receipt
        assert loop.last_error_code is None
        assert initial.query_set is not None
        assert loop.last_facts.query_set_id == initial.query_set.query_set_id

        loop.interval = 0.05
        loop.start()
        with barrier._condition:
            assert barrier._condition.wait_for(
                lambda: barrier._started_generation >= 2
                and barrier._active_refreshes == 0,
                timeout=3.0,
            )
        gate_boundary = {}
        pending_fill = {
            "order_ref": "501",
            "trade_id": "iteration51-test-trade-501",
            "order_sys_id": "iteration51-test-sys-501",
            "instrument": "M2611",
            "exchange": "DCE",
            "side": "BUY",
            "quantity": 1,
            "price": "214",
        }

        def publish_fill() -> None:
            with barrier._condition:
                # deliver_synthetic_callback has drained all active refreshes
                # and left _callback_pending set, so no query can begin while
                # this exact pre-fill boundary is captured.
                assert barrier._active_refreshes == 0
                gate_boundary["generation"] = barrier._started_generation
                gate_boundary["request_id"] = api._request_id
                gate_boundary["query_set_id"] = barrier._last_query_set_id
                latest_receipt = loop.last_receipt
                latest_query_set = getattr(latest_receipt, "query_set", None)
                latest_facts = loop.last_facts
                gate_boundary["receipt_query_set_id"] = getattr(
                    latest_query_set, "query_set_id", None
                )
                gate_boundary["facts_query_set_id"] = getattr(
                    latest_facts, "query_set_id", None
                )
                gate_boundary["last_error_code"] = loop.last_error_code
                fake_state["synthetic_engine_fills"].append(pending_fill)
                fake_state["synthetic_fill_count"] += 1

        assert barrier.deliver_synthetic_callback(publish_fill) is True
        generation_before_fill = gate_boundary["generation"]
        request_id_before_fill = gate_boundary["request_id"]
        previous_query_set_id_before_fill = gate_boundary["query_set_id"]
        assert type(previous_query_set_id_before_fill) is str
        assert previous_query_set_id_before_fill
        assert previous_query_set_id_before_fill == gate_boundary["receipt_query_set_id"]
        assert previous_query_set_id_before_fill == gate_boundary["facts_query_set_id"]
        assert gate_boundary["last_error_code"] is None
        assert previous_query_set_id_before_fill != initial.query_set.query_set_id
        loop._refresh_wakeup.set()
        with barrier._condition:
            assert barrier._condition.wait_for(
                lambda: barrier._waiting_refreshes == 1,
                timeout=3.0,
            )
        assert barrier._engine_fill_pending == pending_fill
        assert barrier._started_generation == generation_before_fill
        assert api._request_id == request_id_before_fill

        requested_at = clock.utc_now()
        wrong_delivery = {
            **pending_fill,
            "order_ref": "502",
        }
        with pytest.raises(RuntimeError, match="does not match pending callback"):
            barrier.wait_for_complete_refresh(
                "fill",
                requested_at_utc=requested_at,
                engine_delivery=wrong_delivery,
                consumed_fill_ref="502",
            )
        assert barrier._engine_fill_pending == pending_fill
        assert api._request_id == request_id_before_fill

        engine_delivery = {
            **pending_fill,
            "broker_order_ref": 1,
            "broker_data_name": "DCE.M",
            "broker_data_instrument": "M2611",
            "broker_strategy_route": ["M2611", "DCE"],
            "broker_ctp_order_ref": "501",
            "broker_order_sys_id": "iteration51-test-sys-501",
            "broker_exchange_id": "DCE",
            "broker_status": "COMPLETED",
            "strategy_completed_event_count": 2,
            "executed_size": "1",
            "callback_price": "214",
            "executed_price": "214.0",
            "execution_bit_size": "1",
            "execution_bit_price": "214.00",
            "broker_position_size": "1",
            "expected_position_size": "1",
        }
        record = barrier.wait_for_complete_refresh(
            "fill",
            requested_at_utc=requested_at,
            engine_delivery=engine_delivery,
            consumed_fill_ref=pending_fill["order_ref"],
        )
        assert loop._thread.is_alive()
        assert loop._thread.ident != threading.get_ident()
        assert record["status"] == "PASS"
        assert record["refresh_generation"] == generation_before_fill + 1
        assert record["receipt_is_last_published"] is True
        assert record["query_set_is_receipt_bound"] is True
        assert record["facts_query_set_matches"] is True
        assert record["query_set_id"] == record["facts_query_set_id"]
        assert record["previous_query_set_id"] == previous_query_set_id_before_fill
        assert record["query_set_id"] != record["previous_query_set_id"]
        assert record["engine_delivery"] == engine_delivery
        assert api._request_id > request_id_before_fill
        assert datetime.fromisoformat(record["requested_at_utc"]) == requested_at
        assert datetime.fromisoformat(record["requested_at_utc"]) <= datetime.fromisoformat(
            record["query_set_started_at_utc"]
        ) <= datetime.fromisoformat(record["query_set_completed_at_utc"])
        assert barrier.receipt()["fill_barrier_count"] == 1
        assert api._query_utc_clock is loop.clock is clock
    finally:
        with barrier._condition:
            barrier._engine_fill_pending = None
            barrier._callback_pending = False
            barrier._condition.notify_all()
        if loop.started:
            loop.stop_and_join()
        barrier.restore()
        loop_class.refresh_once = original_refresh_once
        journal.close()


def test_blocked_optional_fee_query_leaves_live_core_projection_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_path = (
        _FIXTURE_PATH.parents[1]
        / "examples"
        / "unified"
        / "028_alpha003_simnow_minute"
        / "run.py"
    )
    monkeypatch.syspath_prepend(str(runner_path.parent))
    runner_spec = importlib.util.spec_from_file_location(
        "alpha003_simnow_fee_lock_source_test", runner_path
    )
    assert runner_spec is not None and runner_spec.loader is not None
    runner = importlib.util.module_from_spec(runner_spec)
    sys.modules[runner_spec.name] = runner
    runner_spec.loader.exec_module(runner)

    strategy_path = runner_path.with_name("alpha003_strategy.py")
    strategy_spec = importlib.util.spec_from_file_location(
        "alpha003_simnow_fee_lock_strategy_test", strategy_path
    )
    assert strategy_spec is not None and strategy_spec.loader is not None
    strategy_module = importlib.util.module_from_spec(strategy_spec)
    sys.modules[strategy_spec.name] = strategy_module
    strategy_spec.loader.exec_module(strategy_module)

    helper = _load_iteration50_fixture()
    clock = _FixedUTCClock(datetime.now(timezone.utc))
    _api, _store, journal, target, loop = _source_loaded_refresh_case(
        helper, runner, clock, bind_query_clock=True
    )
    entered = threading.Event()
    release = threading.Event()
    refresh = None
    try:
        initial = loop.refresh_initial(wait_timeout=2.0)
        assert initial is loop.last_receipt and initial.query_set is not None

        loop.commission_identity_by_target = {
            target.target_id: {"account_id": "fixture-account", "invest_unit_id": ""}
        }
        loop._commission_targets = (target,)
        loop._refresh_commission_sidecar = lambda: (entered.set(), release.wait(5.0))
        refresh = threading.Thread(target=loop.refresh_once)
        refresh.start()
        assert entered.wait(3.0)

        strategy = object.__new__(strategy_module.Alpha003TargetStrategy)
        strategy.broker = loop.broker
        strategy.p = SimpleNamespace(
            control_refresh_loop=loop,
            execution_enabled=True,
        )
        strategy._risk_policy = object()
        strategy._quote_max_age_seconds = Decimal("60")
        strategy._max_query_age_seconds = Decimal("60")
        strategy._target_ids = (target.target_id,)
        strategy._routes = {
            target.target_id: (target.instrument, target.exchange),
        }
        strategy._data_by_target = {target.target_id: target.data}
        strategy._authorized_targets = frozenset({target.target_id})
        strategy._account_scope = loop.account_scope
        strategy._strategy_scope = loop.strategy_scope
        strategy.last_execution_facts = None
        strategy._last_execution_facts_broker = None
        strategy._last_execution_facts_store = None
        strategy.last_execution_block_reason = None

        facts = strategy_module.Alpha003TargetStrategy._live_facts(
            strategy, clock.utc_now()
        )

        assert facts is not None, strategy.last_execution_block_reason
        assert strategy.last_execution_block_reason is None
        assert facts.snapshot_id is not None
        assert facts.query_set_id == loop.last_receipt.query_set.query_set_id
        assert {
            item.family
            for item in facts.query_provenance
            if item.family
            in {
                "account_result",
                "orders_result",
                "trades_result",
                "instruments_result",
                "positions_result",
            }
        } == {
            "account_result",
            "orders_result",
            "trades_result",
            "instruments_result",
            "positions_result",
        }
        assert loop._fact_snapshot_lock.locked() is False
    finally:
        release.set()
        if refresh is not None:
            refresh.join(timeout=3.0)
            assert not refresh.is_alive()
        journal.close()


def test_commission_refresh_prioritizes_live_pair_and_held_fees_within_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backtrader.stores.factor_execution_facts import FactorExecutionTarget

    runner_path = (
        _FIXTURE_PATH.parents[1]
        / "examples"
        / "unified"
        / "028_alpha003_simnow_minute"
        / "run.py"
    )
    monkeypatch.syspath_prepend(str(runner_path.parent))
    runner_spec = importlib.util.spec_from_file_location(
        "alpha003_simnow_fee_priority_source_test", runner_path
    )
    assert runner_spec is not None and runner_spec.loader is not None
    runner = importlib.util.module_from_spec(runner_spec)
    sys.modules[runner_spec.name] = runner
    runner_spec.loader.exec_module(runner)

    class VirtualTime:
        monotonic_now = 100.0

        @classmethod
        def monotonic(cls):
            return cls.monotonic_now

    class MutableClock:
        now = datetime(2026, 10, 27, 1, 0, tzinfo=timezone.utc)

        @classmethod
        def utc_now(cls):
            return cls.now

    monkeypatch.setattr(runner, "time", VirtualTime)
    target_ids = tuple("T{:03d}".format(index) for index in range(128))
    targets = tuple(
        FactorExecutionTarget(
            target_id,
            "M{}".format(index),
            "DCE",
            SimpleNamespace(_name="M{}".format(index)),
        )
        for index, target_id in enumerate(target_ids)
    )
    loop = runner.QueryRefreshLoop(
        SimpleNamespace(),
        None,
        targets,
        execution_target_ids=target_ids,
        commission_identity_by_target={
            target_id: {"account_id": "synthetic-account", "invest_unit_id": ""}
            for target_id in target_ids
        },
        commission_required_for_open=True,
        coordinator=None,
        account_scope="synthetic-scope",
        strategy_scope="synthetic-strategy",
        clock=MutableClock,
        quote_max_age=timedelta(seconds=60),
        max_query_age=timedelta(seconds=60),
        timeout=5.0,
        overall_timeout=20.0,
        interval=1.0,
        cerebro=None,
        shutdown_grace_seconds=1.0,
    )
    account = SimpleNamespace(
        account_fingerprint="synthetic-fingerprint",
        connection_generation=7,
        trading_day="20261027",
    )
    loop.last_facts = SimpleNamespace(account=account, positions=(), query_provenance=())

    def decision(pair, *, available_at=None, authorized=target_ids, batch="batch-1"):
        return SimpleNamespace(
            status="TARGETS_READY",
            execution_mode="LIVE",
            batch_id=batch,
            available_at=available_at or MutableClock.now,
            authorized_targets=authorized,
            targets=tuple(SimpleNamespace(target_id=value) for value in pair),
        )

    def record_complete_query(target_id):
        fact = SimpleNamespace(
            family="instrument_commission_rate_result",
            target_id=target_id,
            request_id=100 + target_ids.index(target_id),
            source_owned=True,
            query_complete=True,
            connection_generation=account.connection_generation,
            trading_day=account.trading_day,
            account_fingerprint=account.account_fingerprint,
            completed_at=MutableClock.now,
        )
        previous = tuple(loop.last_facts.query_provenance)
        previous = tuple(item for item in previous if item.target_id != target_id)
        loop.last_facts = SimpleNamespace(
            account=account,
            positions=loop.last_facts.positions,
            query_provenance=previous + (fact,),
        )

    loop.publish_commission_target_decision(decision(("T000", "T001")))
    assert loop._select_commission_target().target_id == "T000"
    record_complete_query("T000")

    # Simulate six serialized core queries and one bounded fee slot per cycle.
    cadence = 6 * 1.05 + 3.0
    MutableClock.now += timedelta(seconds=cadence)
    VirtualTime.monotonic_now += cadence
    assert loop._select_commission_target().target_id == "T001"
    record_complete_query("T001")

    # Many authorized but unselected targets remain in the pool. A held target
    # is serviced after both currently selected pair fees are fresh.
    loop.last_facts = SimpleNamespace(
        account=account,
        positions=(SimpleNamespace(target_id="T010", quantity=1),),
        query_provenance=loop.last_facts.query_provenance,
    )
    assert loop._select_commission_target().target_id == "T010"
    assert len(loop._commission_targets) == 128
    record_complete_query("T010")

    # After the 30s refresh horizon, the selected pair jumps ahead of the
    # round-robin tail and can be refreshed within two bounded fee slots.
    MutableClock.now += timedelta(seconds=31)
    VirtualTime.monotonic_now += 31
    loop.last_facts = SimpleNamespace(
        account=account,
        positions=(),
        query_provenance=loop.last_facts.query_provenance,
    )
    assert loop._select_commission_target().target_id == "T000"
    record_complete_query("T000")
    MutableClock.now += timedelta(seconds=cadence)
    VirtualTime.monotonic_now += cadence
    assert loop._select_commission_target().target_id == "T001"


def test_commission_priority_rejects_switched_or_expired_decision_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backtrader.stores.factor_execution_facts import FactorExecutionTarget

    runner_path = (
        _FIXTURE_PATH.parents[1]
        / "examples"
        / "unified"
        / "028_alpha003_simnow_minute"
        / "run.py"
    )
    monkeypatch.syspath_prepend(str(runner_path.parent))
    runner_spec = importlib.util.spec_from_file_location(
        "alpha003_simnow_fee_priority_stale_source_test", runner_path
    )
    assert runner_spec is not None and runner_spec.loader is not None
    runner = importlib.util.module_from_spec(runner_spec)
    sys.modules[runner_spec.name] = runner
    runner_spec.loader.exec_module(runner)

    class VirtualTime:
        monotonic_now = 50.0

        @classmethod
        def monotonic(cls):
            return cls.monotonic_now

    class MutableClock:
        now = datetime(2026, 10, 27, 1, 0, tzinfo=timezone.utc)

        @classmethod
        def utc_now(cls):
            return cls.now

    monkeypatch.setattr(runner, "time", VirtualTime)
    targets = tuple(
        FactorExecutionTarget(
            target_id,
            "M" + target_id,
            "DCE",
            SimpleNamespace(_name="M" + target_id),
        )
        for target_id in ("A", "B", "C", "D", "E")
    )
    target_ids = tuple(item.target_id for item in targets)
    loop = runner.QueryRefreshLoop(
        SimpleNamespace(),
        None,
        targets,
        execution_target_ids=target_ids,
        commission_identity_by_target={
            target_id: {"account_id": "synthetic-account", "invest_unit_id": ""}
            for target_id in target_ids
        },
        commission_required_for_open=True,
        coordinator=None,
        account_scope="synthetic-scope",
        strategy_scope="synthetic-strategy",
        clock=MutableClock,
        quote_max_age=timedelta(seconds=10),
        max_query_age=timedelta(seconds=60),
        timeout=5.0,
        overall_timeout=20.0,
        interval=1.0,
        cerebro=None,
        shutdown_grace_seconds=1.0,
    )
    loop.last_facts = SimpleNamespace(account=None, positions=(), query_provenance=())

    def decision(pair, available_at, authorized=target_ids, batch="batch"):
        return SimpleNamespace(
            status="TARGETS_READY",
            execution_mode="LIVE",
            batch_id=batch,
            available_at=available_at,
            authorized_targets=authorized,
            targets=tuple(SimpleNamespace(target_id=value) for value in pair),
        )

    loop.publish_commission_target_decision(
        decision(("A", "B"), MutableClock.now, authorized=target_ids[:2])
    )
    # A decision for a different execution grant must never seed priority.
    assert loop._commission_priority_target_ids() == ()

    loop.publish_commission_target_decision(decision(("A", "B"), MutableClock.now))
    assert loop._select_commission_target().target_id == "A"
    loop.publish_commission_target_decision(
        decision(("C", "D"), MutableClock.now, batch="next-grid")
    )
    assert loop._commission_priority_target_ids() == ("C", "D")
    assert loop._select_commission_target().target_id == "C"

    MutableClock.now += timedelta(seconds=11)
    VirtualTime.monotonic_now += 11
    loop._commission_index = 4
    assert loop._commission_priority_target_ids() == ()
    # Stale selection falls back to the full authorized pool; it does not keep
    # retrying the formerly selected C/D legs.
    assert loop._select_commission_target().target_id == "E"
    assert len(loop._commission_targets) == 5


@pytest.mark.parametrize("second_leg_mode", ("available", "missing", "timeout"))
def test_source_loaded_pair_fee_sidecar_requires_both_source_owned_target_rows(
    monkeypatch: pytest.MonkeyPatch,
    second_leg_mode: str,
) -> None:
    """Exercise sequential pair fees through the real Store and refresh loop."""

    runner_path = (
        _FIXTURE_PATH.parents[1]
        / "examples"
        / "unified"
        / "028_alpha003_simnow_minute"
        / "run.py"
    )
    monkeypatch.syspath_prepend(str(runner_path.parent))
    runner_spec = importlib.util.spec_from_file_location(
        "alpha003_simnow_pair_fee_refresh_source_test", runner_path
    )
    assert runner_spec is not None and runner_spec.loader is not None
    runner = importlib.util.module_from_spec(runner_spec)
    sys.modules[runner_spec.name] = runner
    runner_spec.loader.exec_module(runner)

    facts_fixture = _load_factor_execution_facts_test_helpers()
    now = datetime.now(timezone.utc)
    target_specs = (("A", "rb2510", "SHFE"), ("B", "i2510", "DCE"))
    account_row = {
        "Available": "100000",
        "CurrMargin": "0",
        "CloseProfit": "1000",
        "PositionProfit": "0",
        "Commission": "0",
        "CurrencyID": "CNY",
        "TradingDay": facts_fixture._TRADING_DAY,
        "BrokerID": "fake-broker",
        "AccountID": "configured-account",
        "InvestorID": "fake-investor",
    }
    api, store, broker, journal, coordinator, targets, _templates = (
        facts_fixture._multi_target_system_under_test(
            now=now,
            target_specs=target_specs,
            account=account_row,
        )
    )
    api._use_observed_query_clock = True
    api.query_rows["instrument_commission_rate_result"] = [
        facts_fixture._commission_row(instrument="rb2510", exchange="SHFE")
    ]
    if second_leg_mode != "missing":
        api.query_rows["instrument_commission_rate_result"].append(
            facts_fixture._commission_row(instrument="i2510", exchange="DCE")
        )
    if second_leg_mode == "timeout":
        query_commission = api.query_instrument_commission_rate_result

        def query_with_second_leg_timeout(
            *, timeout=5.0, deadline_monotonic, instrument_id, exchange_id
        ):
            if instrument_id == "i2510":
                raise TimeoutError("synthetic second-leg timeout")
            return query_commission(
                timeout=timeout,
                deadline_monotonic=deadline_monotonic,
                instrument_id=instrument_id,
                exchange_id=exchange_id,
            )

        monkeypatch.setattr(
            api, "query_instrument_commission_rate_result", query_with_second_leg_timeout
        )
    assert all(store.poll_tick(target.instrument) is not None for target in targets)

    class _SystemUTCClock:
        @staticmethod
        def utc_now() -> datetime:
            return datetime.now(timezone.utc)

    clock = _SystemUTCClock()
    loop = runner.QueryRefreshLoop(
        store,
        broker,
        targets,
        execution_target_ids=("A", "B"),
        commission_identity_by_target={
            target_id: {"account_id": "configured-account", "invest_unit_id": ""}
            for target_id in ("A", "B")
        },
        commission_required_for_open=True,
        coordinator=coordinator,
        account_scope="acct-scope",
        strategy_scope="alpha003",
        clock=clock,
        quote_max_age=timedelta(seconds=60),
        max_query_age=timedelta(seconds=30),
        timeout=1.0,
        overall_timeout=4.0,
        interval=0.01,
        cerebro=SimpleNamespace(),
        shutdown_grace_seconds=1.0,
    )
    try:
        initial = loop.refresh_initial(wait_timeout=2.0)
        assert initial is loop.last_receipt
        assert initial.query_set is not None

        decision_time = clock.utc_now()
        loop.publish_commission_target_decision(
            SimpleNamespace(
                status="TARGETS_READY",
                execution_mode="LIVE",
                batch_id="pair-fee-grid-1",
                available_at=decision_time,
                authorized_targets=("A", "B"),
                targets=(SimpleNamespace(target_id="A"), SimpleNamespace(target_id="B")),
            )
        )

        # The optional sidecar is one exact target per serialized refresh pass.
        loop.refresh_once()
        by_target = {item.target_id: item for item in loop.last_facts.instruments}
        assert by_target["A"].commission_fee_status == "AVAILABLE"
        assert by_target["B"].commission_fee_status != "AVAILABLE"
        assert loop._commission_query_is_fresh("A") is True
        assert loop._commission_query_is_fresh("B") is False

        loop.refresh_once()
        by_target = {item.target_id: item for item in loop.last_facts.instruments}
        assert by_target["A"].commission_fee_status == "AVAILABLE"
        expected_second_leg_status = {
            "available": "AVAILABLE",
            "missing": "RATE_UNAVAILABLE",
            "timeout": "QUERY_UNAVAILABLE",
        }[second_leg_mode]
        assert by_target["B"].commission_fee_status == expected_second_leg_status
        assert loop._commission_query_is_fresh("A") is True
        if second_leg_mode == "available":
            assert loop._commission_query_is_fresh("B") is True
        elif second_leg_mode == "timeout":
            assert loop._commission_query_is_fresh("B") is False
        else:
            # A complete empty response is fresh evidence of no qualifying fee row.
            assert loop._commission_query_is_fresh("B") is True
        sidecar_rows = tuple(
            item
            for item in loop.last_facts.query_provenance
            if item.family == "instrument_commission_rate_result"
        )
        assert {item.target_id for item in sidecar_rows} == {"A", "B"}
        if second_leg_mode == "timeout":
            second_leg_rows = tuple(item for item in sidecar_rows if item.target_id == "B")
            assert len(second_leg_rows) == 1
            assert second_leg_rows[0].query_complete is False
        complete_rows = tuple(item for item in sidecar_rows if item.query_complete is True)
        assert all(item.source_owned is True for item in complete_rows)
        assert all(
            item.connection_generation == loop.last_facts.account.connection_generation
            for item in complete_rows
        )
        assert all(item.trading_day == loop.last_facts.account.trading_day for item in complete_rows)
        assert all(
            item.account_fingerprint == loop.last_facts.account.account_fingerprint
            for item in complete_rows
        )

        if second_leg_mode == "available":
            old_generation = loop.last_facts.account.connection_generation
            api.trader_client._connection_generation = old_generation + 1
            loop.refresh_once()
            assert loop.last_facts.account.connection_generation == old_generation + 1
            assert loop._commission_query_is_fresh("A") is True
            assert loop._commission_query_is_fresh("B") is False
            by_target = {item.target_id: item for item in loop.last_facts.instruments}
            assert not (
                by_target["A"].commission_fee_status == "AVAILABLE"
                and by_target["B"].commission_fee_status == "AVAILABLE"
                and loop._commission_query_is_fresh("A")
                and loop._commission_query_is_fresh("B")
            )
    finally:
        journal.close()


def test_refresh_barrier_rejects_missing_or_future_query_sets_and_noquote_preclose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _load_fixture()
    helper = _load_iteration50_fixture()
    runner_path = (
        _FIXTURE_PATH.parents[1]
        / "examples"
        / "unified"
        / "028_alpha003_simnow_minute"
        / "run.py"
    )
    runner_spec = importlib.util.spec_from_file_location(
        "alpha003_simnow_refresh_barrier_negative_source_test", runner_path
    )
    monkeypatch.syspath_prepend(str(runner_path.parent))
    assert runner_spec is not None and runner_spec.loader is not None
    runner = importlib.util.module_from_spec(runner_spec)
    sys.modules[runner_spec.name] = runner
    runner_spec.loader.exec_module(runner)
    clock = _FixedUTCClock(datetime.now(timezone.utc) - timedelta(seconds=1))
    _api, _store, journal, _target, loop = _source_loaded_refresh_case(
        helper, runner, clock, bind_query_clock=True
    )
    child_tree = ast.parse(fixture._SYNTHETIC_LIVE_CHILD_CODE)
    barrier_node = next(
        node
        for node in child_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SyntheticQueryRefreshBarrier"
    )
    namespace = {"threading": threading, "_real_time": time, "datetime": datetime}
    exec(
        compile(ast.Module(body=[barrier_node], type_ignores=[]), "<refresh-barrier>", "exec"),
        namespace,
    )
    barrier = namespace["SyntheticQueryRefreshBarrier"](
        enabled=True,
        max_order_intents_per_run=20,
    )
    try:
        receipt = loop.refresh_initial(wait_timeout=2.0)
        assert receipt is not None and receipt.query_set is not None
        loop.last_receipt = replace(receipt, query_set=None)
        previous_query_set_id = "prior-query-set"
        missing = barrier._completed_refresh_record(
            loop,
            loop.last_receipt,
            None,
            requested_at_utc=clock.utc_now(),
            previous_query_set_id=previous_query_set_id,
        )
        assert missing["complete"] is False
        assert missing["failure_code"] == "PRODUCTION_QUERY_SET_UNAVAILABLE"

        loop.last_receipt = receipt
        older_than_request = barrier._completed_refresh_record(
            loop,
            receipt,
            None,
            requested_at_utc=receipt.query_set.completed_at_utc + timedelta(seconds=1),
            previous_query_set_id=previous_query_set_id,
        )
        assert older_than_request["complete"] is False
        assert older_than_request["failure_code"] == "QUERY_SET_BEFORE_BARRIER_REQUEST"

        reused_query_set = barrier._completed_refresh_record(
            loop,
            receipt,
            None,
            requested_at_utc=receipt.query_set.started_at_utc,
            previous_query_set_id=receipt.query_set.query_set_id,
        )
        assert reused_query_set["complete"] is False
        assert reused_query_set["failure_code"] == "QUERY_SET_NOT_NEW"

        clock._now = receipt.query_set.completed_at_utc - timedelta(seconds=1)
        future = barrier._completed_refresh_record(
            loop,
            receipt,
            None,
            requested_at_utc=receipt.query_set.started_at_utc,
            previous_query_set_id=previous_query_set_id,
        )
        assert future["complete"] is False
        assert future["failure_code"] == "QUERY_SET_TIME_INVALID"
    finally:
        journal.close()

    scheduler_class = next(
        node
        for node in child_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SyntheticVirtualScheduler"
    )
    quote_method = next(
        node
        for node in scheduler_class.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_next_authorized_quote_requirements"
    )
    quote_globals = {
        "datetime": datetime,
        "authorized_instruments": {"M2611", "A2611"},
        "synthetic_events": [],
    }
    exec(
        compile(ast.Module(body=[quote_method], type_ignores=[]), "<quote-requirements>", "exec"),
        quote_globals,
    )
    scheduler = SimpleNamespace(_event_index=0)
    query_at = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    quote_globals["synthetic_events"] = [
        (query_at, "M2611", 0, 0, None),
        (query_at + timedelta(seconds=1), "M2611", 0, 1, None),
    ]
    assert quote_globals["_next_authorized_quote_requirements"](
        scheduler, query_at
    ) is None
    quote_globals["synthetic_events"] = [
        (query_at + timedelta(seconds=1), "M2611", 0, 0, None),
        (query_at + timedelta(seconds=2), "A2611", 0, 0, None),
    ]
    requirements = quote_globals["_next_authorized_quote_requirements"](
        scheduler, query_at
    )
    assert requirements == {
        "M2611": query_at + timedelta(seconds=1),
        "A2611": query_at + timedelta(seconds=2),
    }


def _write_example(path: Path) -> dict[str, bytes]:
    path.mkdir(parents=True)
    payloads = {
        "run.py": b"public runner\n",
        "entry_tier.py": b"public tier helper\n",
        "alpha003_strategy.py": b"public strategy\n",
        "config.yaml": b"schema: backtrader.alpha003.simnow_runner.v1\nmode: dry\n",
    }
    for name, payload in payloads.items():
        (path / name).write_bytes(payload)
    return payloads


def _write_test_selector_source(
    path: Path,
    fixture: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    source = path / "sdk-source" / "ctp_env_selector.py"
    source.parent.mkdir(parents=True)
    payload = b"test-only pinned selector source bytes"
    source.write_bytes(payload)
    monkeypatch.setattr(fixture, "SDK_SELECTOR_SOURCE_SIZE_BYTES", len(payload))
    monkeypatch.setattr(fixture, "SDK_SELECTOR_SOURCE_SHA256", hashlib.sha256(payload).hexdigest())
    return source


def test_copy_public_example_pins_exact_four_files_and_separate_config(
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    workspace = tmp_path / "external"
    workspace.mkdir()
    source = workspace / "source"
    payloads = _write_example(source)
    offline_config = workspace / "research-fixture.yaml"
    offline_config.write_text("mode: research\n", encoding="utf-8")

    copied, config_path, pins = fixture.copy_public_example(
        source,
        workspace / "copy",
        offline_config=offline_config,
    )

    assert config_path == copied / "fixture-config.yaml"
    assert {path.name for path in copied.iterdir()} == set(fixture.PUBLIC_FILES) | {
        "fixture-config.yaml"
    }
    assert set(pins) == set(fixture.PUBLIC_FILES) | {"fixture-config.yaml"}
    for name, payload in payloads.items():
        assert (copied / name).read_bytes() == payload
        assert pins[name]["sha256"] == hashlib.sha256(payload).hexdigest()


def test_copy_public_example_rejects_incomplete_or_reused_destination(tmp_path: Path) -> None:
    fixture = _load_fixture()
    workspace = tmp_path / "external"
    workspace.mkdir()
    source = workspace / "source"
    source.mkdir()
    for name in fixture.PUBLIC_FILES[:-1]:
        (source / name).write_text("public\n", encoding="utf-8")
    with pytest.raises(fixture.InstalledFixtureError, match="missing or not regular"):
        fixture.copy_public_example(source, workspace / "copy")

    complete_source = workspace / "complete"
    _write_example(complete_source)
    existing = workspace / "existing"
    existing.mkdir()
    with pytest.raises(fixture.InstalledFixtureError, match="must not already exist"):
        fixture.copy_public_example(complete_source, existing)


def test_offline_paths_must_be_staged_and_confined_to_external_workspace(
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    workspace = tmp_path / "external"
    workspace.mkdir()
    example = workspace / "example"
    example.mkdir()
    config_path = example / "fixture-config.yaml"
    config_path.write_text("unused\n", encoding="utf-8")
    bundle = workspace / "bundle.json"
    bundle.write_text("{}\n", encoding="utf-8")
    minute = workspace / "minute.json"
    minute.write_text('{"bars": []}\n', encoding="utf-8")
    output = {
        "directory": "outputs",
        "evaluate_with_fincore": False,
        "decision_tape_path": None,
    }
    selection = {"bundle": "../bundle.json", "daily_bundles": []}
    inputs = {
        "minute_tape": "../minute.json",
        "execution_quotes": None,
        "instrument_metadata": None,
    }

    resolved = fixture._config_paths(
        {"mode": "research", "output": output, "selection": selection, "inputs": inputs},
        config_path,
        workspace,
        "research",
    )
    assert resolved["selection.bundle"] == str(bundle.resolve())
    assert resolved["inputs.minute_tape"] == str(minute.resolve())
    assert fixture._input_evidence(resolved)["inputs.minute_tape"] == {
        "path": str(minute.resolve()),
        "sha256": hashlib.sha256(minute.read_bytes()).hexdigest(),
        "size_bytes": minute.stat().st_size,
    }

    inputs["minute_tape"] = str(Path(tmp_path) / "outside-minute.json")
    with pytest.raises(fixture.InstalledFixtureError, match="inside the external workspace"):
        fixture._config_paths(
            {"mode": "research", "output": output, "selection": selection, "inputs": inputs},
            config_path,
            workspace,
            "research",
        )


def test_replay_config_requires_all_inputs_and_new_confined_outputs(tmp_path: Path) -> None:
    fixture = _load_fixture()
    workspace = tmp_path / "external"
    example = workspace / "example"
    fixtures = workspace / "inputs"
    example.mkdir(parents=True)
    fixtures.mkdir()
    config_path = example / "replay.yaml"
    config_path.write_text("unused\n", encoding="utf-8")
    paths = {}
    for name in ("bundle", "minute", "quotes", "metadata"):
        source = fixtures / (name + ".json")
        source.write_text("{}\n", encoding="utf-8")
        paths[name] = "../inputs/" + source.name
    config = {
        "mode": "replay",
        "selection": {"bundle": paths["bundle"], "daily_bundles": []},
        "inputs": {
            "minute_tape": paths["minute"],
            "execution_quotes": paths["quotes"],
            "instrument_metadata": paths["metadata"],
        },
        "output": {
            "directory": "../output",
            "decision_tape_path": "../decision.jsonl",
            "evaluate_with_fincore": False,
        },
    }

    resolved = fixture._config_paths(config, config_path, workspace, "replay")
    assert resolved["inputs.minute_tape"] == str((fixtures / "minute.json").resolve())
    assert resolved["output.decision_tape_path"] == str((workspace / "decision.jsonl").resolve())

    (workspace / "output").mkdir()
    with pytest.raises(fixture.InstalledFixtureError, match="output directory must be new"):
        fixture._config_paths(config, config_path, workspace, "replay")


def test_cli_case_uses_isolated_child_and_reused_installed_origin_verifier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    example = tmp_path / "copied-example"
    example.mkdir()
    (example / "run.py").write_text("# copied public runner\n", encoding="utf-8")
    config = example / "config.yaml"
    config.write_text("mode: dry\n", encoding="utf-8")
    wheel = tmp_path / "pinned.whl"
    wheel.write_bytes(b"wheel placeholder for command construction")
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    monkeypatch.setenv("PYTHONPATH", "checkout-shadow")
    monkeypatch.setenv("BT_SIMNOW_CONFIG_JSON", "must-not-reach-child")
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        child = {
            "exit_code": 0,
            "wheel_sha256": wheel_hash,
            "loaded_modules_verified": 17,
            "fresh_bytecode_cache": True,
        }
        stdout = json.dumps({"status": "DRY_VALIDATION_COMPLETE"}) + "\n"
        stdout += fixture._CHILD_MARKER + json.dumps(child) + "\n"
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(fixture.subprocess, "run", fake_run)
    result = fixture.run_cli_case(
        example_dir=example,
        config_path=config,
        wheel_path=wheel,
        wheel_sha256=wheel_hash,
        mode="dry",
        factor_mode="native",
    )

    assert result["status"] == "DRY_VALIDATION_COMPLETE"
    assert result["summary"] == {"status": "DRY_VALIDATION_COMPLETE"}
    assert observed["command"][1:3] == ["-I", "-c"]
    assert "iteration50_installed_fixture.py" in observed["command"][4]
    compile(observed["command"][3], "<iteration51-installed-child>", "exec")
    assert json.loads(observed["command"][-1]) == result["cli_argv"]
    assert "--allow-write" not in observed["command"]
    assert result["cli_argv"] == [
        str((example / "run.py").resolve()),
        "--config",
        str(config.resolve()),
        "--mode",
        "dry",
        "--factor-mode",
        "native",
    ]
    assert observed["kwargs"]["cwd"] == str(example.resolve())
    assert "PYTHONPATH" not in observed["kwargs"]["env"]
    assert "BT_SIMNOW_CONFIG_JSON" not in observed["kwargs"]["env"]
    assert observed["kwargs"]["timeout"] == 180.0


def test_cli_timeout_preserves_partial_output_and_unknown_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    example = tmp_path / "copied-example"
    example.mkdir()
    (example / "run.py").write_text("# copied public runner\n", encoding="utf-8")
    config = example / "config.yaml"
    config.write_text("mode: dry\n", encoding="utf-8")
    wheel = tmp_path / "pinned.whl"
    wheel.write_bytes(b"wheel placeholder for timeout command")
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    stdout = b"partial public CLI stdout\r\n"
    stderr = b"partial public CLI stderr\r\n"

    def timeout_run(*_args, **_kwargs):
        raise fixture.subprocess.TimeoutExpired(
            cmd=["public-cli"], timeout=2.0, output=stdout, stderr=stderr
        )

    monkeypatch.setattr(fixture.subprocess, "run", timeout_run)
    with pytest.raises(
        fixture.InstalledFixtureError,
        match="exit status is unknown",
    ):
        fixture.run_cli_case(
            example_dir=example,
            config_path=config,
            wheel_path=wheel,
            wheel_sha256=wheel_hash,
            mode="dry",
            factor_mode="native",
            timeout_seconds=2.0,
        )

    workspace = tmp_path
    stem = "iteration51-installed-cli-dry-native"
    stdout_path = workspace / (stem + ".stdout.bin")
    stderr_path = workspace / (stem + ".stderr.bin")
    exit_path = workspace / (stem + ".exit.txt")
    assert stdout_path.read_bytes() == stdout
    assert stderr_path.read_bytes() == stderr
    assert exit_path.read_bytes() == b"UNKNOWN_TIMEOUT\n"


def test_cli_fixture_rejects_live_and_write_options() -> None:
    fixture = _load_fixture()
    with pytest.raises(fixture.InstalledFixtureError, match="safe installed-fixture set"):
        fixture._child_command(
            verifier_path=_FIXTURE_PATH,
            wheel_path=_FIXTURE_PATH,
            wheel_sha256="0" * 64,
            example_dir=_FIXTURE_PATH.parent,
            config_path=_FIXTURE_PATH,
            mode="live",
            factor_mode="native",
        )


def test_synthetic_live_child_is_separate_from_the_offline_allowlist() -> None:
    fixture = _load_fixture()

    assert fixture.SAFE_MODES == ("dry", "research", "replay")
    assert fixture.SYNTHETIC_LIVE_CASES == (
        "read-only",
        "write",
        "write-denied",
        "tier-escalation",
    )
    assert len(fixture._SYNTHETIC_LIVE_CHILD_CODE) > 32767
    compile(fixture._SYNTHETIC_LIVE_CHILD_CODE, "<synthetic-live-child>", "exec")
    with pytest.raises(fixture.InstalledFixtureError, match="fixed local set"):
        fixture._synthetic_live_child_command(
            child_script_path=_FIXTURE_PATH,
            wheel_path=_FIXTURE_PATH,
            wheel_sha256="0" * 64,
            example_dir=_FIXTURE_PATH.parent,
            workspace=_FIXTURE_PATH.parent,
            selector_source_path=_FIXTURE_PATH,
            case="live",
            factor_mode="native",
        )


def test_write_scheduler_barriers_run_after_delivery_outside_scheduler_lock() -> None:
    fixture = _load_fixture()
    tree = ast.parse(
        fixture._SYNTHETIC_LIVE_CHILD_CODE,
        filename="iteration51-synthetic-live-child.py",
    )
    cap_assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "write_intent_cap"
            for target in node.targets
        )
    )
    for case, configured_cap, expected_cap in (("readonly", None, 20), ("write", 7, 7)):
        namespace = {
            "case": case,
            "config": {"risk": {"max_order_intents_per_run": configured_cap}},
            "write_risk": {"max_order_intents_per_run": 20},
        }
        exec(
            compile(ast.Module(body=[cap_assignment], type_ignores=[]), "<fixture-cap>", "exec"),
            namespace,
        )
        assert namespace["write_intent_cap"] == expected_cap
    scheduler = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SyntheticVirtualScheduler"
    )
    callback_at = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    callbacks = []
    fake_state = {"synthetic_fill_count": 0}
    lock_depth_observations = []
    wait_lock_depths = []
    wait_requested_at = []

    class TrackingLock:
        def __init__(self) -> None:
            self.depth = 0

        def __enter__(self):
            self.depth += 1
            return self

        def __exit__(self, _error_type, _error, _traceback):
            self.depth -= 1

    class RefreshBarrier:
        last_completed_at_utc = callback_at

        def deliver_synthetic_callback(self, callback) -> bool:
            lock_depth_observations.append(scheduler._lock.depth)
            assert scheduler._lock.depth == 0
            assert callbacks == []  # _deliver_through popped it before yielding.
            assert callback is fill_callback
            callback()
            return True

        def wait_for_complete_refresh(self, reason, *, requested_at_utc=None):
            wait_lock_depths.append(scheduler._lock.depth)
            wait_requested_at.append((reason, requested_at_utc))
            raise RefreshWaitObserved

    class RefreshWaitObserved(Exception):
        pass

    def fill_callback() -> None:
        assert scheduler._lock.depth == 0
        assert scheduler._now == callback_at
        assert callbacks == []
        fake_state["synthetic_fill_count"] += 1

    callbacks.append((callback_at, 1, fill_callback))
    namespace = {
        "datetime": datetime,
        "timedelta": timedelta,
        "timezone": timezone,
        "threading": SimpleNamespace(RLock=TrackingLock),
        "created_at": callback_at,
        "synthetic_events": [],
        "synthetic_callback_events": callbacks,
        "heapq": __import__("heapq"),
        "fake_state": fake_state,
        "refresh_barrier": RefreshBarrier(),
        "authorized_instruments": (),
        "_real_time": time,
    }
    exec(
        compile(ast.Module(body=[scheduler], type_ignores=[]), "<scheduler-behavior>", "exec"),
        namespace,
    )
    scheduler = namespace["SyntheticVirtualScheduler"]()
    scheduler._advance(0)

    assert lock_depth_observations == [0]
    assert fake_state["synthetic_fill_count"] == scheduler._observed_fill_count == 1
    assert scheduler._callback_delivery_count == 1
    assert scheduler._now == callback_at
    assert scheduler._advance_count == 0  # Return to the engine at the fill instant.
    assert callbacks == []

    preclose_at = callback_at + timedelta(seconds=5)
    scheduler._preclose_barrier_at = preclose_at
    with pytest.raises(RefreshWaitObserved):
        scheduler._advance(5)
    assert wait_lock_depths == [0]
    assert wait_requested_at == [("preclose", preclose_at)]
    assert scheduler._now == preclose_at

    # The example's session end is Asia/Shanghai-aware. The scheduler may
    # retain that local timestamp for event ordering, but its query clock must
    # expose the same instant in canonical UTC for the installed query leaf.
    local_preclose_at = (callback_at + timedelta(seconds=10)).astimezone(
        timezone(timedelta(hours=8))
    )
    scheduler._preclose_barrier_at = local_preclose_at
    scheduler._preclose_barrier_done = False
    with pytest.raises(RefreshWaitObserved):
        scheduler._advance(5)
    expected_utc = local_preclose_at.astimezone(timezone.utc)
    assert scheduler._now == local_preclose_at
    assert scheduler.utc_now() == expected_utc
    assert scheduler.utc_now().utcoffset() == timedelta(0)
    assert wait_lock_depths == [0, 0]
    assert wait_requested_at == [("preclose", preclose_at), ("preclose", expected_utc)]


def test_strategy_fill_delivery_binds_named_feed_to_instrument_route() -> None:
    fixture = _load_fixture()
    tree = ast.parse(fixture._SYNTHETIC_LIVE_CHILD_CODE)
    barrier_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SyntheticQueryRefreshBarrier"
    )
    namespace = {
        "threading": threading,
        "_real_time": time,
        "datetime": datetime,
        "Mapping": Mapping,
        "Decimal": Decimal,
        "InvalidOperation": InvalidOperation,
        "fake_state": {"synthetic_fill_count": 1},
        "_SYNTHETIC_TARGET_BY_INSTRUMENT": {
            "M2611": "DCE.M",
            "Y2611": "DCE.Y",
            "A2611": "DCE.A",
        },
        "_SYNTHETIC_ENGINE_DELIVERY_FAILURE_CODE_BY_MESSAGE": {
            "synthetic fill Broker data route does not match the target mapping": (
                "BROKER_DATA_ROUTE_MISMATCH"
            )
        },
        "_SYNTHETIC_ENGINE_DELIVERY_FAILURE_CODES": frozenset(
            {"BROKER_DATA_ROUTE_MISMATCH"}
        ),
    }
    exec(
        compile(ast.Module(body=[barrier_node], type_ignores=[]), "<delivery-route>", "exec"),
        namespace,
    )
    barrier = namespace["SyntheticQueryRefreshBarrier"](
        enabled=True,
        max_order_intents_per_run=20,
        per_barrier_timeout=8.0,
    )
    barrier._expected_broker_positions = {"M2611": 0}
    pending = {
        "order_ref": "501",
        "trade_id": "iteration51-test-trade-501",
        "order_sys_id": "iteration51-test-sys-501",
        "instrument": "M2611",
        "exchange": "DCE",
        "side": "BUY",
        "quantity": 1,
        "price": "214",
    }
    data = SimpleNamespace(_name="DCE.M", p=SimpleNamespace(dataname="M2611"))
    order = SimpleNamespace(
        info={
            "ctp_order_ref": "501",
            "registered_sim_ctp_order_sys_id": "iteration51-test-sys-501",
            "registered_sim_ctp_order_sys_id_conflict": False,
            "exchange_id": "DCE",
        },
        data=data,
        ref=17,
        getstatusname=lambda: "Completed",
        executed=SimpleNamespace(
            size=1,
            price=214,
            exbits=(SimpleNamespace(size=1, price=214),),
        ),
    )
    broker = SimpleNamespace(
        orders={17: order},
        getposition=lambda _data: SimpleNamespace(size=1),
    )
    strategy = SimpleNamespace(
        broker=broker,
        _routes={"DCE.M": ("M2611", "DCE")},
        order_events=[{"ref": 17, "status": "COMPLETED"}],
    )

    delivery = barrier._strategy_engine_fill_delivery(strategy, pending)

    assert delivery["broker_data_name"] == "DCE.M"
    assert delivery["broker_data_instrument"] == "M2611"
    assert delivery["broker_strategy_route"] == ["M2611", "DCE"]
    assert delivery["broker_position_size"] == "1"

    barrier._expected_broker_positions = {"M2611": 0}
    data.p.dataname = "A2611"
    with pytest.raises(RuntimeError, match="data route does not match the target mapping"):
        barrier._strategy_engine_fill_delivery(strategy, pending)
    data.p.dataname = "M2611"

    class Loop:
        def refresh_once(self):
            pass

    class Strategy:
        def __init__(self):
            self.broker = broker
            self._routes = {"DCE.M": ("A2611", "DCE")}
            self.order_events = [{"ref": 17, "status": "COMPLETED"}]

        def _notify(self):
            return None

    barrier._engine_fill_pending = dict(pending)
    assert barrier.install(Loop, Strategy) is True
    try:
        with pytest.raises(RuntimeError, match="data route does not match the target mapping"):
            Strategy()._notify()
        assert barrier.receipt()["engine_delivery_failure_codes"] == [
            "BROKER_DATA_ROUTE_MISMATCH"
        ]
    finally:
        barrier.restore()

    strategy._routes = {"DCE.M": ("A2611", "DCE")}
    assert barrier._expected_broker_positions == {"M2611": 0}


def test_sdk_selector_source_uses_the_fixed_public_pin_and_external_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    assert fixture.SDK_SELECTOR_SOURCE_COMMIT == "48b476ea90665791c7d2f86935720ce238931520"
    assert fixture.SDK_SELECTOR_SOURCE_SIZE_BYTES == 21403
    assert fixture.SDK_SELECTOR_SOURCE_SHA256 == (
        "ca8fa2b48293e7c5d79c1a0cfc20fd229879693290b99b56440b84c72cae12c3"
    )
    source = _write_test_selector_source(tmp_path, fixture, monkeypatch)

    evidence = fixture._pinned_sdk_selector_source(source)

    assert evidence == {
        "source_commit": fixture.SDK_SELECTOR_SOURCE_COMMIT,
        "source_path": fixture.SDK_SELECTOR_SOURCE_RELATIVE_PATH,
        "path": str(source.resolve()),
        "module": "bt_api_ctp.ctp_env_selector",
        "size_bytes": len(source.read_bytes()),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    with pytest.raises(fixture.InstalledFixtureError, match="outside the checkout"):
        fixture._pinned_sdk_selector_source(_FIXTURE_PATH)

    source.write_bytes(b"changed")
    with pytest.raises(fixture.InstalledFixtureError, match="fixed public size"):
        fixture._pinned_sdk_selector_source(source)
    source.write_bytes(b"x" * fixture.SDK_SELECTOR_SOURCE_SIZE_BYTES)
    with pytest.raises(fixture.InstalledFixtureError, match="fixed public pin"):
        fixture._pinned_sdk_selector_source(source)


def test_live_child_loads_pinned_selector_before_run_and_runner_uses_official_api() -> None:
    fixture = _load_fixture()
    child_source = fixture._SYNTHETIC_LIVE_CHILD_CODE
    assert "component.is_symlink()" in child_source
    assert "selector_path.relative_to(repository_root)" in child_source
    assert "len(selector_source_bytes) != SDK_SELECTOR_SOURCE_SIZE_BYTES" in child_source
    assert 'compile(selector_source_bytes, str(selector_path), "exec")' in child_source
    assert child_source.index(
        "sys.modules[SDK_SELECTOR_MODULE] = selector_module"
    ) < child_source.index("runpy.run_path(")
    mutable_bar_copy = "target: [dict(row) for row in target_rows]"
    assert "include_extra_fields=False" in child_source
    metadata_assignment = 'target_row["trading_day"] = trading_day.isoformat()'
    assert mutable_bar_copy in child_source
    assert child_source.index(mutable_bar_copy) < child_source.index(metadata_assignment)
    assert '"live_tick_provenance"' in child_source
    assert '"clock_domain_id": helper._CLOCK_DOMAIN' in child_source
    assert '"rules_hash": "a" * 64' in child_source
    assert '"session_segment": "regular"' in child_source
    assert "def _trace_live_cohort_exception(frame, event, arg):" in child_source
    assert '"backtrader.research.live_cohort"' in child_source
    assert '"live-cohort-exception-diagnostics.json"' in child_source
    for function_name in (
        "official_simnow_fronts",
        "official_simnow_profile_for_td_front",
        "verify_official_simnow_profile",
    ):
        assert function_name in child_source

    runner_path = (
        _FIXTURE_PATH.parents[1] / "examples" / "unified" / "028_alpha003_simnow_minute" / "run.py"
    )
    runner_source = runner_path.read_text(encoding="utf-8")
    assert "import bt_api_ctp.ctp_env_selector as selector" in runner_source
    assert "validate_official_simnow_store_profile(store_config, api_kwargs)" in runner_source
    assert "official_simnow_profile_for_td_front(td_front)" in runner_source


def test_synthetic_ctp_leaf_matches_registered_order_and_price_tick_contracts() -> None:
    fixture = _load_fixture()
    child_source = fixture._SYNTHETIC_LIVE_CHILD_CODE

    assert "def _synthetic_ctp_payload(fields):" in child_source
    assert "return types.SimpleNamespace(**fields)" in child_source
    assert "_synthetic_ctp_payload(payload)" in child_source
    assert child_source.count("_synthetic_ctp_payload(") == 3
    assert "self._req_id = 100" in child_source
    assert "self._query_utc_clock = virtual_scheduler" in child_source
    assert "wrapper_frame = leaf_frame.f_back" in child_source
    assert 'wrapper_frame.f_code.co_name != "connect"' in child_source
    assert '_emit_order_status("3", 0, quantity)' in child_source
    assert '_emit_order_status("0", quantity, 0)' in child_source
    assert "OrderStatus=ctp_status" in child_source
    assert 'fake_state["ctp_order_callback_count"] += 1' in child_source
    assert 'fake_state["ctp_trade_callback_count"] += 1' in child_source
    assert 'fake_state["synthetic_fill_count"] += 1' in child_source
    assert 'order_sys_id = "iteration51-sys-" + order_ref' in child_source
    assert "OrderSysID=order_sys_id" in child_source
    assert "price_tick = price_tick_by_target[target]" in child_source
    assert 'tick_units = (Decimal(str(price)) / price_tick).quantize(Decimal("1"))' in child_source
    assert "bid_price = last_price - price_tick" in child_source
    assert "ask_price = last_price + price_tick" in child_source
    assert '"BidPrice1": float(bid_price)' in child_source
    assert '"AskPrice1": float(ask_price)' in child_source
    assert (
        "tick_volume_base, tick_volume_remainder = divmod(bar_volume, len(values))" in child_source
    )
    assert "cumulative_volume += tick_volume" in child_source
    assert 'fake_state["ctp_order_callback_associations"].append({' in child_source
    assert 'fake_state["arm_scope_observations"].append({' in child_source
    assert 'fake_state["disarm_scope_observations"].append(' in child_source
    assert '"order_sys_id": order_sys_id' in child_source
    assert '"price": price' in child_source
    assert 'def _order_row(self, order_ref, *, status, filled, remaining):' in child_source
    assert 'def _trade_row(self, order_ref, trade_id, *, quantity, offset, when, fee):' in child_source
    assert 'row["OrderSysID"] = identity["order_sys_id"]' in child_source
    assert 'row["Price"] = str(identity["price"])' in child_source
    assert '"query_price_matches": query_price_matches' in child_source
    assert '"callback_price": str(trade_callback.Price)' in child_source
    assert 'query_trade_row["Price"] =' not in child_source
    assert 'fake_state["ctp_trade_callback_associations"].append({' in child_source

    child_tree = ast.parse(child_source, filename="iteration51-synthetic-live-child.py")
    owner_helper = next(
        node
        for node in child_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_wrapper_owner_from_sdk_constructor"
    )
    namespace = {
        "sys": sys,
        "fake_state": {
            "wrapper_mros": [],
            "wrapper_write_flags": [],
            "wrapper_api_instances": [],
        },
        "leaf_bindings": [],
    }
    exec(
        compile(ast.Module(body=[owner_helper], type_ignores=[]), "<pinned-helper>", "exec"),
        namespace,
    )

    class RegisteredSimWrapper:
        _registered_sim_allow_writes = False

    class CtpClientWrapper:
        def connect(self):
            def synthetic_sdk_leaf_constructor():
                namespace["leaf_bindings"].append(
                    namespace["_wrapper_owner_from_sdk_constructor"]()
                )

            synthetic_sdk_leaf_constructor()

    class SyntheticRegisteredClient(RegisteredSimWrapper, CtpClientWrapper):
        pass

    wrapper = SyntheticRegisteredClient()
    wrapper.connect()
    assert namespace["fake_state"]["wrapper_api_instances"] == [wrapper]
    assert namespace["leaf_bindings"] == [wrapper]
    assert namespace["fake_state"]["wrapper_mros"][0][:3] == [
        "SyntheticRegisteredClient",
        "RegisteredSimWrapper",
        "CtpClientWrapper",
    ]
    assert namespace["fake_state"]["wrapper_write_flags"] == [False]


def test_synthetic_ctp_payload_matches_attribute_backed_sdk_leaf_contract() -> None:
    fixture = _load_fixture()
    child_tree = ast.parse(
        fixture._SYNTHETIC_LIVE_CHILD_CODE,
        filename="iteration51-synthetic-live-child.py",
    )
    payload_helper = next(
        node
        for node in child_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_synthetic_ctp_payload"
    )
    namespace = {"types": types}
    exec(
        compile(
            ast.Module(body=[payload_helper], type_ignores=[]),
            "<synthetic-ctp-payload-helper>",
            "exec",
        ),
        namespace,
    )

    payload = namespace["_synthetic_ctp_payload"](
        {
            "InstrumentID": "M2601",
            "TradingDay": "20261026",
            "ActionDay": "20261025",
            "UpdateTime": "09:00:01",
            "UpdateMillisec": 0,
            "LastPrice": 230.0,
        }
    )

    assert not isinstance(payload, dict)
    assert payload.InstrumentID == "M2601"
    assert payload.TradingDay == "20261026"
    assert payload.ActionDay == "20261025"
    assert payload.UpdateTime == "09:00:01"
    assert payload.UpdateMillisec == 0
    assert payload.LastPrice == 230.0


def test_synthetic_authorization_scope_receipt_is_exact_and_disarmed() -> None:
    fixture = _load_fixture()
    read_only = {
        "arm_calls": 0,
        "disarm_calls": 0,
        "arm_scope_observations": [],
        "disarm_scope_observations": [],
        "synthetic_leaf_actions": [],
        "ctp_trader_leaf_instances": 1,
        "native_gate_after_close": [{"armed": False, "trading_ready": False}],
    }
    assert fixture._synthetic_authorization_scope_is_valid("read-only", read_only)
    assert not fixture._synthetic_authorization_scope_is_valid(
        "read-only",
        {
            **read_only,
            "arm_calls": 1,
            "arm_scope_observations": [
                {
                    "requested_instrument_id": "Y2611",
                    "authorized_instruments": ["Y2611"],
                }
            ],
        },
    )

    write = {
        "arm_calls": 2,
        "disarm_calls": 1,
        "synthetic_leaf_actions": [
            {
                "action": "arm", "generation": 1, "instrument": "M2611",
                "exchange": "DCE", "authorized_instruments": ["M2611"],
                "capability_issued": True, "armed_after": True,
            },
            {
                "action": "insert", "order_ref": "1", "exchange": "DCE",
                "instrument": "M2611", "generation": 1,
                "authorized_instruments": ["M2611"],
                "capability_matches_current": True, "authorization_valid": True,
            },
            {
                "action": "insert", "order_ref": "2", "exchange": "DCE",
                "instrument": "M2611", "generation": 1,
                "authorized_instruments": ["M2611"],
                "capability_matches_current": True, "authorization_valid": True,
            },
            {
                "action": "disarm", "generation": 1, "instrument": "M2611",
                "exchange": "DCE", "authorized_instruments": ["M2611"],
                "capability_matches_current": True,
                "reason": "registered_sim_instrument_switch", "armed_before": True,
                "armed_after": False, "proof_present_after": False,
            },
            {
                "action": "arm", "generation": 2, "instrument": "A2611",
                "exchange": "DCE", "authorized_instruments": ["A2611"],
                "capability_issued": True, "armed_after": True,
            },
            {
                "action": "insert", "order_ref": "3", "exchange": "DCE",
                "instrument": "A2611", "generation": 2,
                "authorized_instruments": ["A2611"],
                "capability_matches_current": True, "authorization_valid": True,
            },
            {
                "action": "sdk_stop_revoke", "generation": 2,
                "instrument": "A2611", "exchange": "DCE",
                "capability_matches_current": True,
                "revocation_source": "ctp_execution_gate_disconnected",
                "armed_before": True, "armed_after": False,
                "proof_present_after": False,
            },
        ],
        "arm_scope_observations": [
            {
                "generation": 1,
                "requested_instrument_id": "M2611",
                "authorized_instruments": ["M2611"],
            },
            {
                "generation": 2,
                "requested_instrument_id": "A2611",
                "authorized_instruments": ["A2611"],
            },
        ],
        "disarm_scope_observations": [
            {"generation": 1, "authorized_instruments": ["M2611"]}
        ],
        "ctp_trader_leaf_instances": 1,
        "native_gate_after_close": [
            {
                "managed": True,
                "armed": False,
                "instrument": None,
                "authorized_instruments": None,
                "proof_present": False,
                "revocation_reason": "ctp_execution_gate_disconnected",
                "trading_ready": False,
            }
        ],
    }
    assert fixture._synthetic_authorization_scope_is_valid("write", write)
    wrong_target = {
        **write,
        "synthetic_leaf_actions": [
            *write["synthetic_leaf_actions"][:2],
            {
                **write["synthetic_leaf_actions"][2],
                "instrument": "Y2611",
                "authorized_instruments": ["Y2611"],
            },
            *write["synthetic_leaf_actions"][3:],
        ],
    }
    assert not fixture._synthetic_authorization_scope_is_valid("write", wrong_target)
    unmatched_disarm = {
        **write,
        "synthetic_leaf_actions": [
            *write["synthetic_leaf_actions"][:3],
            {
                **write["synthetic_leaf_actions"][3],
                "generation": 2,
                "instrument": "A2611",
                "authorized_instruments": ["A2611"],
            },
            *write["synthetic_leaf_actions"][4:],
        ],
    }
    assert not fixture._synthetic_authorization_scope_is_valid("write", unmatched_disarm)
    missing_stop_revoke = {
        **write,
        "synthetic_leaf_actions": write["synthetic_leaf_actions"][:-1],
    }
    assert not fixture._synthetic_authorization_scope_is_valid("write", missing_stop_revoke)
    stale_capability = {
        **write,
        "synthetic_leaf_actions": [
            *write["synthetic_leaf_actions"][:1],
            {
                **write["synthetic_leaf_actions"][1],
                "capability_matches_current": False,
            },
            *write["synthetic_leaf_actions"][2:],
        ],
    }
    assert not fixture._synthetic_authorization_scope_is_valid("write", stale_capability)


def test_source_loaded_registered_sim_reuses_switches_and_stop_revokes_grants() -> None:
    from backtrader.stores.registered_sim import BtApiStoreError, RegisteredSimWrapper

    fixture = _load_fixture()
    helper = _load_iteration50_fixture()
    child_tree = ast.parse(fixture._SYNTHETIC_LIVE_CHILD_CODE)
    source_class = next(
        node
        for node in child_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SyntheticTraderClient"
    )
    selected_names = {
        "arm_execution_for_registered_sim",
        "disarm_execution_gate",
        "stop",
        "disconnect",
        "_synthetic_native_authorization",
    }
    methods = [
        node
        for node in source_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in selected_names
    ]
    assert {method.name for method in methods} == selected_names
    synthetic_class_module = ast.parse(
        "class SyntheticAuthorizationLeaf(_ExecutionProviderLeaf):\n    pass\n"
    )
    synthetic_class = synthetic_class_module.body[0]
    assert isinstance(synthetic_class, ast.ClassDef)
    synthetic_class.body = methods
    namespace = {
        "_ExecutionProviderLeaf": helper._ExecutionProviderLeaf,
        "fake_state": {
            "arm_calls": 0,
            "disarm_calls": 0,
            "arm_scope_observations": [],
            "disarm_scope_observations": [],
            "synthetic_leaf_actions": [],
            "trader_stop_calls": 0,
            "disconnect_calls": 0,
        },
    }
    code = compile(ast.fix_missing_locations(synthetic_class_module), "<source-loaded-r51-leaf>", "exec")
    exec(code, namespace)
    leaf_class = namespace["SyntheticAuthorizationLeaf"]
    client = leaf_class(bars={"M2611": ({},), "A2611": ({},)}, slot_count=1)
    client._synthetic_capability_generation = 0
    client._synthetic_active_grant = None
    client.is_read_only_ready = True
    client.connect()

    native_calls = []

    def submit_order_insert(field, request_id, *, execution_capability):
        client._synthetic_native_authorization(
            "insert", field, execution_capability
        )
        native_calls.append((field.InstrumentID, field.ExchangeID, field.OrderRef))
        return helper._ExecutionProviderLeaf.submit_order_insert(
            client, field, request_id, execution_capability=execution_capability
        )

    client.submit_order_insert = submit_order_insert
    api_class = type("SourceLoadedRegisteredSimApi", (RegisteredSimWrapper,), {})
    api = api_class(registered_sim_allow_writes=True)
    api.trader_client = client
    api.configure_registered_sim_arm_templates(
        {
            (instrument, "DCE"): {
                "md_front": "tcp://md:1",
                "strategy_identity_sha256": "a" * 64,
                "execution_cycle_id": "iteration51-source-test",
                "preflight_sha256": "b" * 64,
            }
            for instrument in ("M2611", "A2611")
        }
    )

    def order_field(instrument: str, order_ref: str, request_id: int) -> SimpleNamespace:
        return SimpleNamespace(
            InstrumentID=instrument,
            ExchangeID="DCE",
            OrderRef=order_ref,
            RequestID=request_id,
            LimitPrice=214.0 if instrument == "M2611" else 207.0,
            VolumeTotalOriginal=1,
            Direction="0",
            CombOffsetFlag="0",
        )

    expected = client.get_session_state()
    with api.registered_sim_expected_session_scope(expected):
        assert api._send_native_order_insert(order_field("M2611", "501", 1), 1) == 0
        assert api._send_native_order_insert(order_field("M2611", "502", 2), 2) == 0
        assert api._send_native_order_insert(order_field("A2611", "503", 3), 3) == 0
        with pytest.raises(
            BtApiStoreError,
            match="outbound leg has no exact registered-sim arm template",
        ):
            api._send_native_order_insert(order_field("Y2611", "504", 4), 4)

    events = namespace["fake_state"]["synthetic_leaf_actions"]
    assert [event["action"] for event in events] == [
        "arm", "insert", "insert", "disarm", "arm", "insert"
    ]
    assert [event.get("generation") for event in events] == [1, 1, 1, 1, 2, 2]
    assert native_calls == [
        ("M2611", "DCE", "501"),
        ("M2611", "DCE", "502"),
        ("A2611", "DCE", "503"),
    ]
    client.stop()
    assert client.get_execution_gate_state()["armed"] is False
    assert client.get_execution_gate_state()["proof_sha256"] is None
    assert namespace["fake_state"]["disconnect_calls"] == 1
    assert events[-1]["action"] == "sdk_stop_revoke"
    assert events[-1]["revocation_source"] == "ctp_execution_gate_disconnected"
    gate_state = client.get_execution_gate_state()
    child = {
        "arm_calls": namespace["fake_state"]["arm_calls"],
        "disarm_calls": namespace["fake_state"]["disarm_calls"],
        "arm_scope_observations": namespace["fake_state"]["arm_scope_observations"],
        "disarm_scope_observations": namespace["fake_state"]["disarm_scope_observations"],
        "synthetic_leaf_actions": events,
        "ctp_trader_leaf_instances": 1,
        "native_gate_after_close": [{
            "managed": gate_state.get("managed") is True,
            "armed": gate_state.get("armed") is True,
            "instrument": gate_state.get("instrument"),
            "authorized_instruments": gate_state.get("authorized_instruments"),
            "proof_present": gate_state.get("proof_sha256") is not None,
            "revocation_reason": gate_state.get("revocation_reason"),
            "trading_ready": bool(client.is_trading_ready),
        }],
    }
    assert fixture._synthetic_authorization_scope_is_valid("write", child)

    stale = order_field("Y2611", "505", 5)
    with pytest.raises(RuntimeError, match="outside the current exact grant"):
        client.submit_order_insert(
            stale, 5, execution_capability=api._registered_sim_capability
        )
    assert len(native_calls) == 3
    assert events[-1]["action"] == "insert"
    assert events[-1]["authorization_valid"] is False
    assert not fixture._synthetic_authorization_scope_is_valid("write", child)


def _synthetic_order_receipt(order_specs: tuple[tuple[str, str], ...]) -> dict[str, object]:
    actions = []
    arm_observations = []
    disarm_observations = []
    accepted_associations = []
    filled_associations = []
    trade_callbacks = []
    trade_queries = []
    engine_fills = []
    active_instrument = None
    active_generation = None
    generation = 0
    for order_ref, instrument in order_specs:
        if instrument != active_instrument:
            if active_instrument is not None:
                actions.append({
                    "action": "disarm",
                    "generation": active_generation,
                    "instrument": active_instrument,
                    "exchange": "DCE",
                    "authorized_instruments": [active_instrument],
                    "capability_matches_current": True,
                    "reason": "registered_sim_instrument_switch",
                    "armed_before": True,
                    "armed_after": False,
                    "proof_present_after": False,
                })
                disarm_observations.append({
                    "generation": active_generation,
                    "authorized_instruments": [active_instrument],
                })
            generation += 1
            active_instrument = instrument
            active_generation = generation
            actions.append({
                "action": "arm",
                "generation": generation,
                "instrument": instrument,
                "exchange": "DCE",
                "authorized_instruments": [instrument],
                "capability_issued": True,
                "armed_after": True,
            })
            arm_observations.append({
                "generation": generation,
                "requested_instrument_id": instrument,
                "authorized_instruments": [instrument],
            })
        order_sys_id = "iteration51-sys-" + order_ref
        trade_id = "iteration51-" + order_ref
        trade_price = "214" if instrument == "M2611" else "207"
        engine_fills.append(
            {
                "order_ref": order_ref,
                "trade_id": trade_id,
                "order_sys_id": order_sys_id,
                "instrument": instrument,
                "exchange": "DCE",
                "side": "BUY",
                "quantity": 1,
                "price": trade_price,
            }
        )
        actions.append({
            "action": "insert",
            "order_ref": order_ref,
            "instrument": instrument,
            "exchange": "DCE",
            "generation": generation,
            "authorized_instruments": [instrument],
            "capability_matches_current": True,
            "authorization_valid": True,
        })
        accepted_associations.append(
            {
                "order_ref": order_ref,
                "status": "3",
                "callback_order_sys_id": order_sys_id,
                "query_order_sys_id": order_sys_id,
                "query_order_sys_id_matches": True,
                "callback_owner_is_wrapper": True,
                "pending_order_present": False,
                "pending_order_ref_matches": False,
                "system_id_order_ref_matches": True,
                "system_id_uses_full_pending_order": False,
            }
        )
        filled_associations.append(
            {
                "order_ref": order_ref,
                "status": "0",
                "callback_order_sys_id": order_sys_id,
                "query_order_sys_id": order_sys_id,
                "query_order_sys_id_matches": True,
                "callback_owner_is_wrapper": True,
                "pending_order_present": True,
                "pending_order_ref_matches": True,
                "system_id_order_ref_matches": True,
                "system_id_uses_full_pending_order": True,
            }
        )
        trade_callbacks.append(
            {
                "trade_id": trade_id,
                "order_ref": order_ref,
                "order_sys_id": order_sys_id,
                "callback_price": trade_price,
            }
        )
        trade_queries.append(
            {
                "trade_id": trade_id,
                "order_ref": order_ref,
                "callback_order_sys_id": order_sys_id,
                "query_order_sys_id": order_sys_id,
                "query_order_sys_id_matches": True,
                "callback_price": trade_price,
                "query_price": trade_price,
                "query_price_matches": True,
            }
        )
    if active_instrument is not None:
        actions.append({
            "action": "sdk_stop_revoke",
            "generation": active_generation,
            "instrument": active_instrument,
            "exchange": "DCE",
            "capability_matches_current": True,
            "revocation_source": "ctp_execution_gate_disconnected",
            "armed_before": True,
            "armed_after": False,
            "proof_present_after": False,
        })
    return {
        "max_order_intents_per_run": 20,
        "synthetic_leaf_actions": actions,
        "arm_calls": generation,
        "disarm_calls": len(disarm_observations),
        "arm_scope_observations": arm_observations,
        "disarm_scope_observations": disarm_observations,
        "native_gate_after_close": (
            [{
                "managed": True,
                "armed": False,
                "instrument": None,
                "authorized_instruments": None,
                "proof_present": False,
                "revocation_reason": "ctp_execution_gate_disconnected",
                "trading_ready": False,
            }]
            if order_specs
            else []
        ),
        "synthetic_fill_count": len(order_specs),
        "synthetic_engine_fills": engine_fills,
        "ctp_order_callback_count": len(accepted_associations) + len(filled_associations),
        "ctp_order_callback_associations": accepted_associations + filled_associations,
        "ctp_trade_callback_count": len(trade_callbacks),
        "ctp_trade_callback_associations": trade_callbacks,
        "ctp_trade_query_associations": trade_queries,
    }


def _synthetic_live_summary(
    *,
    planned_slot_count: int,
    write_enabled: bool,
    order_specs: tuple[tuple[str, str], ...],
    selection_bundle_path: Path,
    profile_id: str,
) -> dict[str, object]:
    routes = {"DCE.M": "M2611", "DCE.Y": "Y2611", "DCE.A": "A2611"}
    file_id = "iteration51-test-decision-tape-v1"
    tape_bytes = planned_slot_count * 100
    tape_sha256 = hashlib.sha256(b"synthetic decision tape receipt").hexdigest()
    last_reference = {
        "batch_id": "iteration51-test-batch-" + str(planned_slot_count),
        "file_id": file_id,
        "record_id": hashlib.sha256(b"synthetic final record").hexdigest(),
        "record_index": planned_slot_count,
    }
    events = [
        {
            "ref": int(order_ref),
            "target": "DCE.M" if instrument == "M2611" else "DCE.A",
        }
        for order_ref, instrument in order_specs
    ]
    return {
        "status": "LIVE_RUN_COMPLETE",
        "epoch_id": 1,
        "mode": "live",
        "selection_source": "saved_bundle_legacy",
        "scheduler_clock": "host-utc-plus-monotonic",
        "write_mode": write_enabled,
        "cleanup_complete": True,
        "shutdown_status": "PASS",
        "routes": routes,
        "selection_evidence": {
            "schema": "backtrader.alpha003_epoch_selection_evidence.v1",
            "epoch_id": 1,
            "selection_path": str(selection_bundle_path.resolve()),
            "selection_source": "saved_bundle_legacy",
            "routes": routes,
            "authorized_targets": ["DCE.M", "DCE.A"],
        },
        "simnow_profile": {
            "verified": True,
            "environment": "simnow",
            "profile": profile_id,
        },
        "strategy_order_events": {
            "capacity": 128,
            "events": events,
            "reason": None,
            "retained_count": len(events),
            "status": "AVAILABLE",
            "truncated": False,
        },
        "decision_tape": {
            "path": str(selection_bundle_path.parent / "decision-tape.jsonl"),
            "record_count": planned_slot_count,
            "closed": True,
            "failed": False,
            "bytes": tape_bytes,
            "max_bytes": 5_000_000,
            "file_id": file_id,
            "sha256": tape_sha256,
            "last_record_reference": last_reference,
        },
        "decision_tape_readback": {
            "record_count": planned_slot_count,
            "actual_bytes": tape_bytes,
            "file_id": file_id,
            "last_record_reference": last_reference,
        },
        "resource_shutdown": [
            {
                "resource": "query_refresh",
                "status": "RETURNED",
                "started": True,
                "joined": True,
            },
            {
                "resource": "decision_tape",
                "status": "CLOSED",
                "record_count": planned_slot_count,
                "bytes": tape_bytes,
                "sha256": tape_sha256,
            },
            {
                "resource": "broker",
                "status": "PASS" if write_enabled else "OBSERVATION_ONLY",
                "store_shutdown_state": "PASS",
            },
            {
                "resource": "store",
                "status": "CLOSED_BY_BROKER",
                "shutdown_state": "PASS",
            },
            {"resource": "journal", "status": "CLOSED"},
        ],
    }


def test_synthetic_order_and_trade_query_ids_match_callback_ids_per_insert() -> None:
    fixture = _load_fixture()
    child = _synthetic_order_receipt((("12", "M2611"), ("13", "A2611")))
    assert fixture._synthetic_order_sys_id_provenance_is_valid(child)
    equivalent_query_price = json.loads(json.dumps(child))
    equivalent_query_price["ctp_trade_query_associations"][0]["query_price"] = "214.0"
    assert fixture._synthetic_order_sys_id_provenance_is_valid(equivalent_query_price)
    mismatched_query = json.loads(json.dumps(child))
    mismatched_query["ctp_trade_query_associations"][0]["query_order_sys_id"] = "wrong"
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(mismatched_query)
    mismatched_query_price = json.loads(json.dumps(child))
    mismatched_query_price["ctp_trade_query_associations"][0]["query_price"] = "215"
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(mismatched_query_price)
    mismatched_query_callback_price = json.loads(json.dumps(child))
    mismatched_query_callback_price["ctp_trade_query_associations"][0][
        "callback_price"
    ] = "215"
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(
        mismatched_query_callback_price
    )
    false_price_receipt = json.loads(json.dumps(child))
    false_price_receipt["ctp_trade_query_associations"][0]["query_price_matches"] = False
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(false_price_receipt)
    non_finite_callback_price = json.loads(json.dumps(child))
    non_finite_callback_price["ctp_trade_callback_associations"][0][
        "callback_price"
    ] = "NaN"
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(non_finite_callback_price)
    missing_callback = json.loads(json.dumps(child))
    missing_callback["ctp_order_callback_associations"].pop(1)
    missing_callback["ctp_order_callback_count"] -= 1
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(missing_callback)
    duplicate_callback = json.loads(json.dumps(child))
    duplicate_callback["ctp_order_callback_associations"].append(
        dict(duplicate_callback["ctp_order_callback_associations"][0])
    )
    duplicate_callback["ctp_order_callback_count"] += 1
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(duplicate_callback)
    duplicate_ref = json.loads(json.dumps(child))
    duplicate_ref["synthetic_leaf_actions"].append(
        dict(duplicate_ref["synthetic_leaf_actions"][0])
    )
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(duplicate_ref)
    duplicate_trade = json.loads(json.dumps(child))
    duplicate_trade["ctp_trade_callback_associations"].append(
        dict(duplicate_trade["ctp_trade_callback_associations"][0])
    )
    duplicate_trade["ctp_trade_query_associations"].append(
        dict(duplicate_trade["ctp_trade_query_associations"][0])
    )
    duplicate_trade["ctp_trade_callback_count"] += 1
    duplicate_trade["synthetic_fill_count"] += 1
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(duplicate_trade)
    missing_trade = json.loads(json.dumps(child))
    missing_trade["ctp_trade_callback_associations"].pop()
    missing_trade["ctp_trade_query_associations"].pop()
    missing_trade["ctp_trade_callback_count"] -= 1
    missing_trade["synthetic_fill_count"] -= 1
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(missing_trade)
    wrong_ref = json.loads(json.dumps(child))
    wrong_ref["ctp_order_callback_associations"][1]["order_ref"] = "uninserted"
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(wrong_ref)
    orphan_trade = json.loads(json.dumps(child))
    for rows in (
        orphan_trade["ctp_trade_callback_associations"],
        orphan_trade["ctp_trade_query_associations"],
    ):
        rows[0]["order_ref"] = "uninserted"
        rows[0]["trade_id"] = "iteration51-uninserted"
        if "order_sys_id" in rows[0]:
            rows[0]["order_sys_id"] = "iteration51-sys-uninserted"
        else:
            rows[0]["callback_order_sys_id"] = "iteration51-sys-uninserted"
            rows[0]["query_order_sys_id"] = "iteration51-sys-uninserted"
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(orphan_trade)
    orphan_callback = {**child, "synthetic_leaf_actions": []}
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(orphan_callback)
    reduced_limit = {**child, "max_order_intents_per_run": 1}
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(reduced_limit)
    over_limit = _synthetic_order_receipt(
        tuple((str(index), "M2611") for index in range(1, 22))
    )
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(over_limit)


def test_source_backed_trade_reconciliation_rejects_query_price_conflict() -> None:
    support = _load_factor_execution_facts_test_helpers()
    _facts, live_inputs = support._build_source_backed_dated_close_facts(
        native_callback_mode="acknowledged"
    )
    journal = live_inputs["journal"]
    try:
        api = live_inputs["api"]
        coordinator = live_inputs["coordinator"]
        target = live_inputs["target"]
        native_receipt = live_inputs["native_receipt"]
        query_row = api.query_rows["trades_result"][0]
        assert str(query_row["Price"]) == str(native_receipt.evidence_payload["price"])
        assert live_inputs["trade_page"].items[0].blocker_code is None

        # The real RegisteredSim Store, Broker, journal and coordinator have
        # accepted this exact-price callback/query pair. A one-tick query
        # mutation must remain a hard native callback conflict.
        api.query_rows["trades_result"] = [{**query_row, "Price": "101"}]
        refresh, projection_now, _consumed = support._refresh_complete_facts_after_callback(
            api,
            live_inputs["store"],
            target,
            sequence=10,
            trading_day=support._TRADING_DAY,
        )
        facts = support._project(
            live_inputs["store"],
            live_inputs["broker"],
            target,
            projection_now,
            query_set=refresh.query_set,
        )
        trade_page = coordinator.reconcile_trade_observations(
            facts,
            refresh_receipt=refresh,
            limit=128,
        )

        assert trade_page.observation_count == 1
        assert trade_page.items[0].status == "BLOCKED"
        assert trade_page.items[0].blocker_code == "NATIVE_TRADE_CALLBACK_QUERY_CONFLICT"
        assert journal.callback_query_disposition(native_receipt.receipt_id) is None
    finally:
        journal.close()


def test_synthetic_live_summary_binds_direct_run_query_and_tape_receipts(
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    selection_bundle = tmp_path / "case" / "selection-bundle.json"
    selection_bundle.parent.mkdir()
    selection_bundle.write_text("{}\n", encoding="utf-8")
    summary = _synthetic_live_summary(
        planned_slot_count=64,
        write_enabled=False,
        order_specs=(),
        selection_bundle_path=selection_bundle,
        profile_id=fixture.SDK_SELECTOR_PROFILE,
    )
    child = {
        "planned_slot_count": 64,
        "query_families": list(fixture._SYNTHETIC_QUERY_FAMILIES),
        "subscriptions": ["A2611", "M2611", "Y2611"],
        "runner_summary_scheduler_clock_labels": [
            {"path": "summary", "value": "host-utc-plus-monotonic"}
        ],
        "runner_summary_scheduler_clock_label_meaning": (
            "production summary default identifier; not the injected runtime clock"
        ),
        **_synthetic_order_receipt(()),
        "synthetic_refresh_barrier": {
            "enabled": False,
            "barrier_count": 0,
            "fill_barrier_count": 0,
            "preclose_barrier_count": 0,
            "records": [],
            "engine_delivery_failure_codes": [],
        },
        "query_refresh_barrier_binding": None,
        "strategy_notify_barrier_binding": None,
        "strategy_notify_class_origin": None,
        "strategy_notify_barrier_origin": None,
        "strategy_notify_barrier_delegates_original": False,
    }
    check = fixture._synthetic_live_summary_failure_checks
    check_args = {
        "planned_slot_count": 64,
        "expected_writes": False,
        "expected_selection_path": selection_bundle,
    }
    assert check(summary, child, **check_args) == []

    wrapped = json.loads(json.dumps(summary))
    wrapped["epochs"] = [dict(summary)]
    assert "summary.direct_live_run_shape" in check(wrapped, child, **check_args)

    missing_query = dict(child)
    missing_query["query_families"] = list(fixture._SYNTHETIC_QUERY_FAMILIES[:-1])
    assert "child.query_families" in check(summary, missing_query, **check_args)

    missing_barrier = dict(child)
    missing_barrier.pop("synthetic_refresh_barrier")
    assert "child.query_refresh_barriers" in check(
        summary, missing_barrier, **check_args
    )

    wrong_writer_count = json.loads(json.dumps(summary))
    wrong_writer_count["decision_tape"]["record_count"] = 63
    wrong_writer_count["decision_tape_readback"]["record_count"] = 63
    assert "summary.decision_tape_counts" in check(
        wrong_writer_count, child, **check_args
    )

    wrong_readback_reference = json.loads(json.dumps(summary))
    wrong_readback_reference["decision_tape_readback"]["last_record_reference"][
        "record_index"
    ] = 63
    assert "summary.decision_tape_readback" in check(
        wrong_readback_reference, child, **check_args
    )

    wrong_write_shutdown = json.loads(json.dumps(summary))
    wrong_write_shutdown["resource_shutdown"][2]["status"] = "OBSERVATION_ONLY"
    assert "summary.resource_shutdown" in check(
        wrong_write_shutdown,
        child,
        planned_slot_count=64,
        expected_writes=True,
        expected_selection_path=selection_bundle,
    )


def _synthetic_refresh_barrier_receipt(
    *,
    order_specs: tuple[tuple[str, str], ...],
    run_cap: int = 20,
    wait_seconds: float = 0.25,
) -> dict[str, object]:
    origin = str(
        (_FIXTURE_PATH.parents[1] / "examples" / "unified" / "028_alpha003_simnow_minute" / "run.py").resolve()
    )
    fill_count = len(order_specs)
    strategy_origin = str(
        (_FIXTURE_PATH.parents[1] / "examples" / "unified" / "028_alpha003_simnow_minute" / "alpha003_strategy.py").resolve()
    )
    strategy_notify_origin = str(
        (_FIXTURE_PATH.parents[1] / "backtrader" / "strategy.py").resolve()
    )
    records = []
    positions = {}
    for index in range(fill_count + 1):
        query_set_id = "iteration51-query-set-{}".format(index + 2)
        is_fill = index < fill_count
        delivery = None
        if is_fill:
            order_ref, instrument = order_specs[index]
            trade_id = "iteration51-" + order_ref
            order_sys_id = "iteration51-sys-" + order_ref
            side = "BUY"
            quantity = 1
            price = "214" if instrument == "M2611" else "207"
            position = positions.get(instrument, 0) + quantity
            positions[instrument] = position
            delivery = {
                "order_ref": order_ref,
                "trade_id": trade_id,
                "order_sys_id": order_sys_id,
                "instrument": instrument,
                "exchange": "DCE",
                "side": side,
                "quantity": quantity,
                "broker_order_ref": index + 1,
                "broker_data_name": {"M2611": "DCE.M", "A2611": "DCE.A"}[instrument],
                "broker_data_instrument": instrument,
                "broker_strategy_route": [instrument, "DCE"],
                "broker_ctp_order_ref": order_ref,
                "broker_order_sys_id": order_sys_id,
                "broker_exchange_id": "DCE",
                "broker_status": "COMPLETED",
                # Backtrader may issue duplicate COMPLETED status notifications;
                # the receipt binds the actual completed order, not a single call.
                "strategy_completed_event_count": 2 if index == 0 else 1,
                "executed_size": str(quantity),
                "callback_price": price,
                "executed_price": price,
                "execution_bit_size": str(quantity),
                "execution_bit_price": price,
                "broker_position_size": str(position),
                "expected_position_size": str(position),
            }
        records.append(
            {
                "reason": "fill" if is_fill else "preclose",
                "refresh_generation": index + 2,
                "status": "PASS",
                "failure_code": None,
                "receipt_is_last_published": True,
                "query_set_is_receipt_bound": True,
                "facts_query_set_matches": True,
                "query_set_id": query_set_id,
                "facts_query_set_id": query_set_id,
                "previous_query_set_id": "iteration51-query-set-{}".format(index + 1),
                "requested_at_utc": "2026-10-25T11:59:59+00:00",
                "query_set_started_at_utc": "2026-10-25T12:00:00+00:00",
                "query_set_completed_at_utc": "2026-10-25T12:00:00+00:00",
                "wait_seconds": round(wait_seconds, 6),
                "engine_delivery": delivery,
            }
        )
    barrier = {
        "enabled": True,
        "max_order_intents_per_run": run_cap,
        "max_barrier_count": run_cap + 1,
        "per_barrier_timeout_seconds": 8.0,
        "max_total_wait_seconds": 8.0 * (run_cap + 1),
        "barrier_count": len(records),
        "fill_barrier_count": fill_count,
        "preclose_barrier_count": 1,
        "engine_delivery_failure_codes": [],
        "total_wait_seconds": round(wait_seconds * len(records), 6),
        "records": records,
    }
    return {
        "synthetic_refresh_barrier": barrier,
        "synthetic_fill_count": fill_count,
        "query_refresh_barrier_binding": "copied run.py QueryRefreshLoop.refresh_once",
        "query_refresh_barrier_origin": origin,
        "query_refresh_barrier_delegates_original": True,
        "strategy_notify_barrier_binding": (
            "copied Alpha003TargetStrategy hook after inherited backtrader.strategy.Strategy._notify"
        ),
        "strategy_notify_class_origin": strategy_origin,
        "strategy_notify_barrier_origin": strategy_notify_origin,
        "strategy_notify_barrier_delegates_original": True,
        "runner_clock_patch_origin": origin,
    }


def test_write_summary_requires_new_complete_refresh_per_fill_and_calendar_preclose(
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    selection_bundle = tmp_path / "case" / "selection-bundle.json"
    selection_bundle.parent.mkdir()
    selection_bundle.write_text("{}\n", encoding="utf-8")
    summary = _synthetic_live_summary(
        planned_slot_count=64,
        write_enabled=True,
        order_specs=(("12", "M2611"),),
        selection_bundle_path=selection_bundle,
        profile_id=fixture.SDK_SELECTOR_PROFILE,
    )
    child = {
        "planned_slot_count": 64,
        "query_families": list(fixture._SYNTHETIC_QUERY_FAMILIES),
        "subscriptions": ["A2611", "M2611", "Y2611"],
        "runner_summary_scheduler_clock_labels": [
            {"path": "summary", "value": "host-utc-plus-monotonic"}
        ],
        "runner_summary_scheduler_clock_label_meaning": (
            "production summary default identifier; not the injected runtime clock"
        ),
        "max_order_intents_per_run": 20,
        **_synthetic_order_receipt((("12", "M2611"),)),
        **_synthetic_refresh_barrier_receipt(order_specs=(("12", "M2611"),)),
    }
    args = {
        "planned_slot_count": 64,
        "expected_writes": True,
        "expected_selection_path": selection_bundle,
    }
    check = fixture._synthetic_live_summary_failure_checks
    assert check(summary, child, **args) == []

    full_risk_specs = tuple(
        (str(index + 1), "M2611" if index % 2 == 0 else "A2611")
        for index in range(20)
    )
    full_risk_budget = {
        **_synthetic_order_receipt(full_risk_specs),
        "max_order_intents_per_run": 20,
        **_synthetic_refresh_barrier_receipt(
            order_specs=full_risk_specs, wait_seconds=0.1234567
        ),
    }
    assert fixture._synthetic_refresh_barrier_is_valid(
        full_risk_budget, expected_writes=True
    )

    missing_preclose = json.loads(json.dumps(child))
    missing_preclose["synthetic_refresh_barrier"]["records"].pop()
    missing_preclose["synthetic_refresh_barrier"]["barrier_count"] -= 1
    missing_preclose["synthetic_refresh_barrier"]["preclose_barrier_count"] = 0
    assert "child.query_refresh_barriers" in check(
        summary, missing_preclose, **args
    )

    stale_facts = json.loads(json.dumps(child))
    stale_facts["synthetic_refresh_barrier"]["records"][0][
        "facts_query_set_id"
    ] = "prior-query-set"
    assert "child.query_refresh_barriers" in check(summary, stale_facts, **args)

    stale_query_set = json.loads(json.dumps(child))
    stale_query_set["synthetic_refresh_barrier"]["records"][0][
        "requested_at_utc"
    ] = "2026-10-25T12:00:01+00:00"
    assert "child.query_refresh_barriers" in check(summary, stale_query_set, **args)

    reused_query_set = json.loads(json.dumps(child))
    reused_query_set["synthetic_refresh_barrier"]["records"][0][
        "previous_query_set_id"
    ] = reused_query_set["synthetic_refresh_barrier"]["records"][0]["query_set_id"]
    assert "child.query_refresh_barriers" in check(summary, reused_query_set, **args)

    duplicate_generation = json.loads(json.dumps(child))
    duplicate_generation["synthetic_refresh_barrier"]["records"][1][
        "refresh_generation"
    ] = duplicate_generation["synthetic_refresh_barrier"]["records"][0][
        "refresh_generation"
    ]
    assert "child.query_refresh_barriers" in check(
        summary, duplicate_generation, **args
    )

    over_budget = json.loads(json.dumps(child))
    over_budget["synthetic_refresh_barrier"]["total_wait_seconds"] = 169.0
    assert "child.query_refresh_barriers" in check(summary, over_budget, **args)

    missing_delivery = json.loads(json.dumps(child))
    missing_delivery["synthetic_refresh_barrier"]["records"][0].pop("engine_delivery")
    assert "child.query_refresh_barriers" in check(summary, missing_delivery, **args)

    wrong_fill_ref = json.loads(json.dumps(child))
    wrong_fill_ref["synthetic_refresh_barrier"]["records"][0]["engine_delivery"][
        "order_ref"
    ] = "13"
    assert "child.query_refresh_barriers" in check(summary, wrong_fill_ref, **args)

    wrong_broker_route = json.loads(json.dumps(child))
    wrong_broker_route["synthetic_refresh_barrier"]["records"][0][
        "engine_delivery"
    ]["broker_data_name"] = "M2611"
    assert "child.query_refresh_barriers" in check(
        summary, wrong_broker_route, **args
    )

    wrong_callback_trade = json.loads(json.dumps(child))
    wrong_callback_trade["ctp_trade_callback_associations"][0]["trade_id"] = (
        "iteration51-uninserted"
    )
    assert "child.query_refresh_barriers" in check(
        summary, wrong_callback_trade, **args
    )

    missing_execution_bit = json.loads(json.dumps(child))
    missing_execution_bit["synthetic_refresh_barrier"]["records"][0][
        "engine_delivery"
    ].pop("execution_bit_size")
    assert "child.query_refresh_barriers" in check(
        summary, missing_execution_bit, **args
    )

    wrong_consumed_position = json.loads(json.dumps(child))
    wrong_consumed_position["synthetic_refresh_barrier"]["records"][0][
        "engine_delivery"
    ]["broker_position_size"] = "0"
    assert "child.query_refresh_barriers" in check(
        summary, wrong_consumed_position, **args
    )


def test_main_reports_only_allowlisted_synthetic_check_ids(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = _load_fixture()
    wheel = tmp_path / "pinned.whl"
    wheel.write_bytes(b"wheel placeholder")
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    selector_source = _write_test_selector_source(tmp_path, fixture, monkeypatch)
    workspace = tmp_path / "external-workspace"

    def fake_copy(_source, destination, offline_config=None):
        destination.mkdir(parents=True)
        config_path = destination / "fixture-config.yaml"
        config_path.write_text("public fixture\n", encoding="utf-8")
        return destination, config_path, {}

    def fail_matrix(**_kwargs):
        raise fixture.InstalledFixtureError(
            "do not expose this arbitrary error detail",
            safe_check_ids=("child.query_families", "private/path"),
        )

    monkeypatch.setattr(fixture, "copy_public_example", fake_copy)
    monkeypatch.setattr(fixture, "run_synthetic_live_matrix", fail_matrix)
    exit_code = fixture.main(
        [
            "--wheel",
            str(wheel),
            "--wheel-sha256",
            wheel_hash,
            "--workspace",
            str(workspace),
            "--example-source",
            str(tmp_path),
            "--sdk-selector-source",
            str(selector_source),
            "--synthetic-live",
            "--factor-mode",
            "native",
        ]
    )
    diagnostic = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert diagnostic == {
        "status": "BLOCKED",
        "error_type": "InstalledFixtureError",
        "failed_checks": ["child.query_families"],
    }


@pytest.mark.parametrize(
    (
        "case",
        "exit_code",
        "status",
        "error_code",
        "write_enabled",
        "planned_slot_count",
        "expected_evidence_level",
    ),
    (
        (
            "read-only",
            0,
            "LIVE_RUN_COMPLETE",
            None,
            False,
            64,
            "INSTALLED_BT_WHEEL_PUBLIC_SDK_SOURCE_FIXTURE",
        ),
        (
            "write",
            0,
            "LIVE_RUN_COMPLETE",
            None,
            True,
            64,
            "INSTALLED_BT_WHEEL_PUBLIC_SDK_SOURCE_FIXTURE",
        ),
        (
            "write-denied",
            2,
            "BLOCKED",
            "LIVE_WRITE_GRANT_MISSING_IN_CONFIG",
            False,
            64,
            "INSTALLED_BT_WHEEL_PUBLIC_SDK_SOURCE_FIXTURE",
        ),
        (
            "tier-escalation",
            2,
            "BLOCKED",
            "ENTRY_TIER_ESCALATION_DENIED",
            False,
            64,
            "INSTALLED_BT_WHEEL_PUBLIC_SDK_SOURCE_FIXTURE",
        ),
        (
            "read-only",
            0,
            "LIVE_RUN_COMPLETE",
            None,
            False,
            32,
            "SYNTHETIC_DIAGNOSTIC_ONLY",
        ),
    ),
)
def test_synthetic_live_case_runs_isolated_command_and_checks_finite_outcome(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    case: str,
    exit_code: int,
    status: str,
    error_code: Optional[str],
    write_enabled: bool,
    planned_slot_count: int,
    expected_evidence_level: str,
) -> None:
    fixture = _load_fixture()
    example = tmp_path / "copied-example"
    example.mkdir()
    (example / "run.py").write_text("# copied public runner\n", encoding="utf-8")
    (example / "alpha003_strategy.py").write_text(
        "# copied public strategy\n", encoding="utf-8"
    )
    (example / "config.yaml").write_text("schema: public-template\n", encoding="utf-8")
    workspace = tmp_path / "external-workspace"
    workspace.mkdir()
    live_case_dir = workspace / "iteration51-live-case-test"
    live_case_dir.mkdir()
    live_config = live_case_dir / "runner.yaml"
    live_config.write_text("synthetic test config\n", encoding="utf-8")
    selection_bundle_path = live_case_dir / "selection-bundle.json"
    selection_bundle_path.write_text("{}\n", encoding="utf-8")
    diagnostic_path = live_case_dir / "live-cohort-exception-diagnostics.json"
    diagnostic_document = {
        "schema": "backtrader.iteration51.synthetic_live_cohort_diagnostics.v1",
        "capture": "installed live_cohort exception events during copied public CLI run",
        "captured_exception_count": 0,
        "exceptions": [],
        "runner_summary": None,
    }
    diagnostic_bytes = json.dumps(
        diagnostic_document, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    diagnostic_path.write_bytes(diagnostic_bytes)
    wheel = tmp_path / "pinned.whl"
    wheel.write_bytes(b"wheel placeholder for synthetic live command")
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    selector_source_path = _write_test_selector_source(tmp_path, fixture, monkeypatch)
    selector_source = fixture._pinned_sdk_selector_source(selector_source_path)
    cli_argv = [
        str((example / "run.py").resolve()),
        "--config",
        str(live_config.resolve()),
        "--mode",
        "live",
        "--factor-mode",
        "native",
    ]
    if case in {"write", "write-denied"}:
        cli_argv.append("--allow-write")
    order_specs = (("1", "M2611"), ("2", "A2611")) if case == "write" else ()
    order_receipt = _synthetic_order_receipt(order_specs)
    if error_code is None and write_enabled:
        barrier_receipt = _synthetic_refresh_barrier_receipt(
            order_specs=order_specs
        )
        barrier_receipt["query_refresh_barrier_origin"] = str(
            (example / "run.py").resolve()
        )
        barrier_receipt["strategy_notify_barrier_origin"] = str(
            (_FIXTURE_PATH.parents[1] / "backtrader" / "strategy.py").resolve()
        )
        barrier_receipt["strategy_notify_class_origin"] = str(
            (example / "alpha003_strategy.py").resolve()
        )
        barrier_receipt["max_order_intents_per_run"] = 20
    elif error_code is None:
        barrier_receipt = {
            "synthetic_refresh_barrier": {
                "enabled": False,
                "barrier_count": 0,
                "fill_barrier_count": 0,
                "preclose_barrier_count": 0,
                "engine_delivery_failure_codes": [],
                "records": [],
            },
            "query_refresh_barrier_binding": None,
            "strategy_notify_barrier_binding": None,
            "strategy_notify_class_origin": None,
            "strategy_notify_barrier_origin": None,
            "strategy_notify_barrier_delegates_original": False,
        }
    else:
        barrier_receipt = {}
    if error_code is None:
        summary = _synthetic_live_summary(
            planned_slot_count=planned_slot_count,
            write_enabled=write_enabled,
            order_specs=order_specs,
            selection_bundle_path=selection_bundle_path,
            profile_id=fixture.SDK_SELECTOR_PROFILE,
        )
        instances = 1
        flags = [write_enabled]
    else:
        summary = {"status": status, "code": error_code}
        instances = 0
        flags = []
    child = {
        "case": case,
        "exit_code": exit_code,
        "cli_argv": cli_argv,
        "wheel_sha256": wheel_hash,
        "loaded_modules_verified": 12,
        "fresh_bytecode_cache": True,
        "ctp_wrapper_factory_unchanged": True,
        "ctp_wrapper_mro_verified": bool(instances),
        "ctp_trader_leaf_instances": instances,
        "ctp_md_leaf_instances": instances,
        "ctp_trader_leaf_wrapper_matches_registered_instance": bool(instances),
        "ctp_md_leaf_wrapper_matches_registered_instance": bool(instances),
        "ctp_wrapper_mros": (
            [["RegisteredSimClient", "RegisteredSimWrapper", "CtpClientWrapper", "object"]]
            if instances
            else []
        ),
        "store_write_flags": flags,
        "network_attempts": 0,
        **order_receipt,
        **barrier_receipt,
        "selection_bundle_sha256": "a" * 64,
        "sdk_selector_source": {
            **selector_source,
            "module_origin": selector_source["path"],
            "profile_id": fixture.SDK_SELECTOR_PROFILE,
            "official_fronts_lookup": True,
            "td_front_profile_lookup": True,
            "official_profile_verification": True,
        },
        "sdk_selector_profile_id": fixture.SDK_SELECTOR_PROFILE,
        "sdk_selector_profile_verified": True,
        "synthetic_only": True,
        "virtual_scheduler": True,
        "virtual_scheduler_monotonic_is_real": True,
        "virtual_scheduler_advance_count": 1 if error_code is None else 0,
        "virtual_scheduler_delivered_ticks": 1 if error_code is None else 0,
        "virtual_scheduler_callback_delivery_count": len(order_specs),
        "virtual_scheduler_pending_callbacks": 0,
        "virtual_scheduler_late_callback_schedule_count": 0,
        "virtual_scheduler_final_utc": "2026-10-25T00:01:00+00:00",
        "runner_clock_patch_binding": "run.__globals__['RunnerWallClock']",
        "runner_clock_patch_target_is_function_globals": True,
        "runner_clock_patch_origin": str((example / "run.py").resolve()),
        "clock_origins": {
            "runner_wall_clock_binding": "copied run.py run.__globals__['RunnerWallClock']",
            "ctp_receive_wall_clock": (
                "backtrader.stores.btapistore.time.time -> synthetic virtual UTC"
            ),
            "monotonic_clock": "host time.monotonic_ns forwarded without virtualization",
            "scheduler_shared_state": (
                "RunnerWallClock and CTP leaves share one child-local instance"
            ),
        },
        "runner_clock_constructor_calls": 1 if error_code is None else 0,
        "runner_clock_shared_with_virtual_scheduler": error_code is None,
        "store_environment_shape_valid": True,
        "store_environment_api_kwargs_keys": ["fixture_marker", "live_tick_provenance"],
        "store_live_tick_provenance": {
            "clock_domain_id": "iteration50-installed-fixture-v1",
            "rules_hash": "a" * 64,
            "session_segment": "regular",
        },
        "live_cohort_exception_diagnostics": {
            "path": str(diagnostic_path),
            "size_bytes": len(diagnostic_bytes),
            "sha256": hashlib.sha256(diagnostic_bytes).hexdigest(),
            "captured_exception_count": 0,
        },
        "planned_slot_count": planned_slot_count,
        "query_families": fixture._SYNTHETIC_QUERY_FAMILIES
        if error_code is None
        else [],
        "subscriptions": ["A2611", "M2611", "Y2611"] if error_code is None else [],
        "runner_summary_scheduler_clock_labels": (
            [{"path": "summary", "value": "host-utc-plus-monotonic"}]
            if error_code is None
            else []
        ),
        "runner_summary_scheduler_clock_label_meaning": (
            "production summary default identifier; not the injected runtime clock"
        ),
        "synthetic_leaf_close_receipt": {
            "trader_client_count": instances,
            "md_client_count": instances,
            "trader_stop_calls": instances,
            "trader_disconnect_calls": instances,
            "md_stop_calls": instances,
            "trader_connected_after_close": [False] if instances else [],
            "trader_ready_after_close": [False] if instances else [],
            "md_started_after_close": [False] if instances else [],
            "wrappers_connected_after_close": [False] if instances else [],
        },
        "native_gate_after_close": (
            order_receipt["native_gate_after_close"]
            if order_specs
            else ([{
                "managed": False,
                "armed": False,
                "instrument": None,
                "authorized_instruments": [],
                "proof_present": True,
                "revocation_reason": None,
                "trading_ready": False,
            }] if instances else [])
        ),
        "authorized_products": ["DCE.M", "DCE.A"],
    }
    child["raw_cli_summary_sha256"] = hashlib.sha256(
        json.dumps(summary).encode("utf-8")
    ).hexdigest()
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        stdout = json.dumps(summary) + "\n"
        stdout += fixture._LIVE_CHILD_MARKER + json.dumps(child) + "\n"
        observed["stdout"] = stdout.encode("utf-8")
        observed["stderr"] = b""
        return SimpleNamespace(returncode=exit_code, stdout=observed["stdout"], stderr=b"")

    monkeypatch.setenv("PYTHONPATH", "checkout-shadow")
    monkeypatch.setenv("BT_SIMNOW_CONFIG_JSON", "ambient-must-not-reach-child")
    monkeypatch.setattr(fixture.subprocess, "run", fake_run)
    result = fixture.run_synthetic_live_case(
        example_dir=example,
        workspace=workspace,
        wheel_path=wheel,
        wheel_sha256=wheel_hash,
        selector_source_path=selector_source_path,
        case=case,
        planned_slot_count=planned_slot_count,
    )

    assert result["case"] == case
    assert result["status"] == status
    assert result["evidence_level"] == expected_evidence_level
    assert result["planned_slot_count"] == planned_slot_count
    assert result["formal_64_slot_acceptance"] is (planned_slot_count == 64)
    assert result["acceptance_status"] == (
        "SYNTHETIC_64_SLOT_CASE_ACCEPTED"
        if planned_slot_count == 64
        else "SYNTHETIC_DIAGNOSTIC_ONLY"
    )
    assert result["sdk_selector_source"] == selector_source
    assert observed["command"][1] == "-I"
    child_script = Path(observed["command"][2])
    assert child_script.parent == workspace.resolve()
    assert child_script.name == "iteration51-synthetic-live-child-native-" + case + ".py"
    assert "iteration50_installed_fixture.py" in observed["command"][3]
    child_source = child_script.read_bytes()
    assert child_source == fixture._SYNTHETIC_LIVE_CHILD_CODE.encode("utf-8")
    compile(child_source, str(child_script), "exec")
    assert len(fixture.subprocess.list2cmdline(observed["command"])) < 32767
    assert result["child_launcher"] == {
        "path": str(child_script),
        "size_bytes": len(child_source),
        "sha256": hashlib.sha256(child_source).hexdigest(),
    }
    child_output = result["child_process_output"]
    assert Path(child_output["stdout_path"]).read_bytes() == observed["stdout"]
    assert Path(child_output["stderr_path"]).read_bytes() == observed["stderr"]
    assert Path(child_output["exit_path"]).read_text(encoding="ascii") == f"{exit_code}\n"
    assert child_output["exit_code"] == exit_code
    assert child_output["exit_status"] == "returned"
    assert child_output["stdout_sha256"] == hashlib.sha256(observed["stdout"]).hexdigest()
    assert child_output["stderr_sha256"] == hashlib.sha256(observed["stderr"]).hexdigest()
    assert observed["command"][-4] == str(selector_source_path.resolve())
    assert observed["command"][-3:] == [case, "native", str(planned_slot_count)]
    assert observed["kwargs"]["cwd"] == str(example.resolve())
    assert "PYTHONPATH" not in observed["kwargs"]["env"]
    assert "BT_SIMNOW_CONFIG_JSON" not in observed["kwargs"]["env"]
    assert observed["kwargs"]["timeout"] == 300.0


def test_synthetic_live_child_output_is_preserved_before_parse_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    example = tmp_path / "copied-example"
    example.mkdir()
    (example / "run.py").write_text("# copied public runner\n", encoding="utf-8")
    (example / "config.yaml").write_text("schema: public-template\n", encoding="utf-8")
    workspace = tmp_path / "external-workspace"
    workspace.mkdir()
    wheel = tmp_path / "pinned.whl"
    wheel.write_bytes(b"wheel placeholder for synthetic live command")
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    selector_source_path = _write_test_selector_source(tmp_path, fixture, monkeypatch)
    stdout = b"child traceback bytes\r\n"
    stderr = b"raw child stderr\r\n"
    monkeypatch.setattr(
        fixture.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=9, stdout=stdout, stderr=stderr),
    )

    with pytest.raises(fixture.InstalledFixtureError, match="did not emit a JSON result"):
        fixture.run_synthetic_live_case(
            example_dir=example,
            workspace=workspace,
            wheel_path=wheel,
            wheel_sha256=wheel_hash,
            selector_source_path=selector_source_path,
            case="read-only",
        )

    stem = "iteration51-synthetic-live-child-native-read-only"
    assert (workspace / (stem + ".stdout.bin")).read_bytes() == stdout
    assert (workspace / (stem + ".stderr.bin")).read_bytes() == stderr
    assert (workspace / (stem + ".exit.txt")).read_text(encoding="ascii") == "9\n"


def test_synthetic_live_timeout_preserves_partial_output_and_unknown_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    example = tmp_path / "copied-example"
    example.mkdir()
    (example / "run.py").write_text("# copied public runner\n", encoding="utf-8")
    (example / "config.yaml").write_text("schema: public-template\n", encoding="utf-8")
    workspace = tmp_path / "external-workspace"
    workspace.mkdir()
    wheel = tmp_path / "pinned.whl"
    wheel.write_bytes(b"wheel placeholder for synthetic live command")
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    selector_source_path = _write_test_selector_source(tmp_path, fixture, monkeypatch)
    stdout = b"partial child stdout before timeout\r\n"
    stderr = b"partial child stderr before timeout\r\n"

    def timeout_run(*_args, **_kwargs):
        raise fixture.subprocess.TimeoutExpired(
            cmd=["synthetic-child"],
            timeout=3.0,
            output=stdout,
            stderr=stderr,
        )

    monkeypatch.setattr(fixture.subprocess, "run", timeout_run)
    with pytest.raises(
        fixture.InstalledFixtureError,
        match="exit status is unknown",
    ):
        fixture.run_synthetic_live_case(
            example_dir=example,
            workspace=workspace,
            wheel_path=wheel,
            wheel_sha256=wheel_hash,
            selector_source_path=selector_source_path,
            case="read-only",
        )

    stem = "iteration51-synthetic-live-child-native-read-only"
    assert (workspace / (stem + ".stdout.bin")).read_bytes() == stdout
    assert (workspace / (stem + ".stderr.bin")).read_bytes() == stderr
    assert (workspace / (stem + ".exit.txt")).read_text(encoding="ascii") == ("UNKNOWN_TIMEOUT\n")


def test_synthetic_live_matrix_requires_fixed_64_slot_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _load_fixture()
    calls = []

    def accepted_case(**kwargs):
        calls.append(kwargs)
        return {
            "case": kwargs["case"],
            "planned_slot_count": kwargs["planned_slot_count"],
            "formal_64_slot_acceptance": kwargs["planned_slot_count"] == 64,
            "acceptance_status": "SYNTHETIC_64_SLOT_CASE_ACCEPTED",
        }

    monkeypatch.setattr(fixture, "run_synthetic_live_case", accepted_case)
    results = fixture.run_synthetic_live_matrix(
        example_dir=Path("example"),
        workspace=Path("workspace"),
        wheel_path=Path("wheel.whl"),
        wheel_sha256="a" * 64,
        selector_source_path=Path("selector.py"),
    )
    assert [call["case"] for call in calls] == list(fixture.SYNTHETIC_LIVE_CASES)
    assert all(call["planned_slot_count"] == 64 for call in calls)
    assert all(result["formal_64_slot_acceptance"] is True for result in results)

    def diagnostic_case(**kwargs):
        return {
            "case": kwargs["case"],
            "planned_slot_count": 32,
            "formal_64_slot_acceptance": False,
            "acceptance_status": "SYNTHETIC_DIAGNOSTIC_ONLY",
        }

    monkeypatch.setattr(fixture, "run_synthetic_live_case", diagnostic_case)
    with pytest.raises(fixture.InstalledFixtureError, match="fixed 64-slot gate"):
        fixture.run_synthetic_live_matrix(
            example_dir=Path("example"),
            workspace=Path("workspace"),
            wheel_path=Path("wheel.whl"),
            wheel_sha256="a" * 64,
            selector_source_path=Path("selector.py"),
        )
