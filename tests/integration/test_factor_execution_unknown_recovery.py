"""Durable, query-proof-bound recovery of an ambiguous native order.

The production Store, Broker, Coordinator, journal and ordinary Cerebro
notification path remain in the test. Only the CTP/query/native leaves are
fake. The spawned-process case opens the same SQLite journal under a fresh
Store and connection generation; it never rebuilds a historical Backtrader
Order.
"""

from __future__ import annotations

import multiprocessing
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import backtrader as bt
import pytest

from backtrader.order import Order
from backtrader.research.live import LiveFactorReadiness, LiveFactorSnapshot
from backtrader.research.live_cohort import LiveCohortBatch
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionKey,
    ExecutionIntentKey,
)
from backtrader.stores.factor_execution import FactorExecutionCoordinator, FactorExecutionError
from backtrader.stores import factor_execution_facts as facts_module
from backtrader.stores.factor_execution_facts import refresh_factor_execution_queries
from tests.unit.stores import test_factor_execution as execution_helpers
from tests.unit.stores import test_factor_execution_facts as facts_helpers


_INSTRUMENT = execution_helpers._INSTRUMENT
_EXCHANGE = execution_helpers._EXCHANGE
_ACCOUNT_SCOPE = execution_helpers._ACCOUNT_SCOPE
_STRATEGY_SCOPE = execution_helpers._SCOPE
_TRADING_DAY = facts_helpers._TRADING_DAY
_CORE_FAMILIES = (
    "account_result",
    "orders_result",
    "trades_result",
    "instruments_result",
    "positions_result",
)


def _durable_system(path, *, now, bars=1, bar_advance_gate=None):
    (
        api,
        store,
        broker,
        memory_journal,
        _memory_coordinator,
        target,
        data,
        strategy,
        cerebro,
    ) = execution_helpers._system(
        now=now,
        bars=bars,
        bar_advance_gate=bar_advance_gate,
    )
    _bind_current_session_identity(api, generation=1)
    memory_journal.close()
    broker.factor_execution_coordinator = None
    journal = ExecutionDecisionJournal(path)
    coordinator = FactorExecutionCoordinator(
        broker,
        journal,
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_STRATEGY_SCOPE,
        logical_run_id="run-1",
        max_order_intents_per_grid=4,
        max_order_intents_per_run=100,
    )
    return api, store, broker, journal, coordinator, target, data, strategy, cerebro


def _bind_current_session_identity(api, *, generation, front_id=4, session_id=7):
    """Give the fake provider a complete current CTP session identity."""
    client = api.trader_client
    client._connection_generation = generation
    client._gate_state["connection_generation"] = generation
    client._front_id = front_id
    client._session_id = session_id
    original_arm = client.arm_execution_for_registered_sim
    client._fake_active_capability = None

    def arm_execution_for_registered_sim(*args, **kwargs):
        result = original_arm(*args, **kwargs)
        client._fake_active_capability = result[0]
        return result

    def disarm_execution_gate(capability, reason):
        if capability is not client._fake_active_capability:
            raise AssertionError("fake SDK disarm must name the active capability")
        client._fake_active_capability = None
        state = dict(client._gate_state)
        state.update(
            managed=False,
            armed=False,
            instrument=None,
            authorized_instruments=[],
            revocation_reason=reason,
        )
        client._gate_state = state
        return {"revoked": True}

    client.arm_execution_for_registered_sim = arm_execution_for_registered_sim
    client.disarm_execution_gate = disarm_execution_gate
    original_get_session_state = client.get_session_state

    def get_session_state():
        state = dict(original_get_session_state())
        native_counts = {
            "settlement_confirm": 0,
            "order_insert": sum(call[0] == "insert" for call in api.native_calls),
            "order_action": sum(call[0] == "cancel" for call in api.native_calls),
        }
        state.update(
            front_id=front_id,
            session_id=session_id,
            ready=True,
            read_only_ready=True,
            auto_settlement_confirm=False,
            request_counts=native_counts,
        )
        return state

    client.get_session_state = get_session_state


def _arm_template():
    return {
        "md_front": "tcp://127.0.0.1:1",
        "strategy_identity_sha256": "a" * 64,
        "execution_cycle_id": "cycle-unknown-recovery",
        "preflight_sha256": "b" * 64,
    }


def _configure_templates_and_arm(store):
    template = _arm_template()
    store.registered_sim_configure_arm_templates({(_INSTRUMENT, _EXCHANGE): template})
    store.registered_sim_arm(instrument=_INSTRUMENT, exchange=_EXCHANGE, **template)


def _initial_open_facts(api, store, broker, target, *, now):
    query = facts_helpers._refresh_all(store, target)
    _configure_templates_and_arm(store)
    assert facts_helpers._consume_quote(store) is not None
    facts = facts_helpers._project(store, broker, target, now, query_set=query.query_set)
    assert facts.open_risk_ready is True, facts.blockers
    return facts


def _decision_scope(coordinator, owner, facts, *, close_time, batch_id):
    close_time = close_time.astimezone(timezone.utc)
    available_at = close_time + timedelta(milliseconds=1)
    batch = LiveCohortBatch(
        batch_id=batch_id,
        cohort_id="rb-cohort",
        calendar_id="simnow-common-minutes-v1",
        calendar_version="v1",
        epoch_id=1,
        slot_index=0,
        close_time=close_time,
        available_at=available_at,
    )
    snapshot = LiveFactorSnapshot(
        plan_id="alpha003-unknown-recovery-test",
        cohort_id=batch.cohort_id,
        calendar_id=batch.calendar_id,
        calendar_version=batch.calendar_version,
        frequency="1min",
        epoch_id=batch.epoch_id,
        batch_id=batch.batch_id,
        close_time=close_time,
        available_at=available_at,
        batch_complete=True,
        readiness=LiveFactorReadiness.LIVE_READY,
        readiness_reasons=(),
        factors={},
    )
    key = ExecutionDecisionKey(
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_STRATEGY_SCOPE,
        logical_run_id="run-1",
        cohort_id=batch.cohort_id,
        close_time=close_time.isoformat().replace("+00:00", "Z"),
        decision_kind="ALPHA003_GRID",
    )
    intent_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument=_INSTRUMENT,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    batch_economics = {
        "instrument": _INSTRUMENT,
        "exchange": _EXCHANGE,
        "side": "BUY",
        "position_effect": "OPEN",
        "quantity": "1",
        "limit_price": "100",
        "factor_stop_price": "95",
        "risk_policy_id": "a003-risk-v1",
        "risk_policy": {"stop_loss_ticks": 5, "max_loss_per_position": "25"},
        "entry_grid_ordinal": 1,
        "batch_id": batch_id,
        "price": "100",
    }
    scope = coordinator.decision_scope(
        owner=owner,
        key=key,
        economic_payload={"intent_economics": (batch_economics,)},
        intent_keys=(intent_key,),
        batch=batch,
        snapshot=snapshot,
        execution_facts=facts,
        inputs_complete=True,
        expected_run_order_intents_used=coordinator.run_order_count(),
        remaining_exit_intent_reserve=0,
    )
    return scope, intent_key, batch_economics


def _submit_open(coordinator, owner, data, facts, *, close_time, batch_id):
    scope, _intent_key, _economics = _decision_scope(
        coordinator, owner, facts, close_time=close_time, batch_id=batch_id
    )
    with scope:
        return owner.buy(
            data=data,
            size=1,
            price=100,
            exectype=Order.Limit,
            instrument_id=_INSTRUMENT,
            exchange_id=_EXCHANGE,
            factor_position_effect="OPEN",
            factor_strategy_scope=_STRATEGY_SCOPE,
            offset="open",
        )


def _install_request_then_timeout(api):
    native_insert = api.trader_client.submit_order_insert

    def request_then_timeout(field, request_id, *, execution_capability):
        # The fake native leaf observes the request, then loses its response.
        # That ambiguous post-dispatch outcome must remain UNKNOWN.
        native_insert(field, request_id, execution_capability=execution_capability)
        raise TimeoutError("synthetic lost native response")

    api.trader_client.submit_order_insert = request_then_timeout
    return native_insert


def _terminal_row(order_ref, *, front_id=4, session_id=7, trading_day=_TRADING_DAY):
    return {
        "OrderRef": str(order_ref),
        "OrderSysID": "sys-{}".format(order_ref),
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": _EXCHANGE,
        "OrderStatus": "5",  # CTP CANCELED; explicit zero-fill volumes below
        "Direction": "0",
        "CombOffsetFlag": "0",
        "FrontID": front_id,
        "SessionID": session_id,
        "TradingDay": trading_day,
        "VolumeTotalOriginal": "1",
        "VolumeTraded": "0",
        "VolumeTotal": "1",
    }


def _refresh_five_family_facts(
    api,
    store,
    broker,
    target,
    *,
    generation=1,
    sequence=2,
    include_margin=False,
    stale_query=False,
    receipt_clock_advance_ms=None,
    monkeypatch=None,
    max_queries=None,
):
    api._use_observed_query_clock = True

    def refresh():
        return refresh_factor_execution_queries(
            store,
            targets=(target,),
            overall_timeout=4.0,
            include_core=True,
            margin_target_ids=(target.target_id,) if include_margin else (),
            max_queries=max_queries,
        )

    if receipt_clock_advance_ms is None:
        receipt = refresh()
    else:
        if monkeypatch is None:
            raise AssertionError("receipt clock control requires pytest monkeypatch")
        base_datetime = facts_module.datetime

        class _ReceiptClockMeta(type(base_datetime)):
            def __instancecheck__(cls, instance):
                return isinstance(instance, base_datetime)

        class _ReceiptClock(base_datetime, metaclass=_ReceiptClockMeta):
            calls = 0

            @classmethod
            def now(cls, tz=None):
                cls.calls += 1
                observed = base_datetime.now(tz)
                if cls.calls == 2:
                    return observed + timedelta(milliseconds=receipt_clock_advance_ms)
                return observed

        with monkeypatch.context() as scoped:
            scoped.setattr(facts_module, "datetime", _ReceiptClock)
            receipt = refresh()
    if max_queries is None and not include_margin:
        assert receipt.blockers == ()
        assert receipt.pending_families == ()
        assert receipt.requested_families == _CORE_FAMILIES
        assert receipt.attempted_families == _CORE_FAMILIES
        assert receipt.query_set is not None
        assert tuple(family for family, _ in receipt.query_set.query_ids) == _CORE_FAMILIES

    completed = (
        receipt.query_set.completed_at_utc
        if receipt.query_set is not None
        else datetime.now(timezone.utc)
    )
    if receipt.query_set is not None and not stale_query:
        assert receipt.completed_at >= completed
        if receipt_clock_advance_ms is not None:
            assert receipt.completed_at > completed
    received = max(datetime.now(timezone.utc), completed, receipt.completed_at) + timedelta(
        milliseconds=2
    )
    api.tick = facts_helpers._quote(
        event_time=received if stale_query else completed,
        received_at=received,
        generation=generation,
        sequence=sequence,
        trading_day=_TRADING_DAY,
    )
    assert facts_helpers._consume_quote(store) is not None
    projection_now = max(datetime.now(timezone.utc), received)
    if stale_query:
        # Project the same current query set at a later caller decision time.
        # Store correctly refuses to replace a current cache with older rows.
        projection_now += timedelta(seconds=11)
    facts = facts_helpers._project(
        store,
        broker,
        target,
        projection_now,
        query_set=receipt.query_set,
    )
    return receipt, facts


def _assert_still_unknown(journal, store, api, intent_id):
    intent = journal.intent(intent_id)
    assert intent is not None
    assert intent.state == "UNKNOWN"
    assert intent.dispatch_state == "UNKNOWN"
    owner = journal.active_instrument_owner(_ACCOUNT_SCOPE, _INSTRUMENT)
    assert owner is not None and owner.intent_id == intent_id
    assert store.registered_sim_status()["frozen"] is True
    assert api.registered_sim_execution_facts()["frozen"] is True
    assert len(api.native_calls) == 1


def _retirement_status_probe(
    store,
    journal,
    capture,
    *,
    expected_generation,
    expected_front_id,
    expected_session_id,
    capture_inputs=None,
):
    """Observe the one narrow retirement call without replacing its behavior."""
    retire = store.registered_sim_retire_unknown

    def checked_retirement(
        intent_id,
        reconciliation_id,
        *,
        original_identity,
        expected_session,
        terminal_event,
    ):
        intent = journal.intent(intent_id)
        resolution = journal.instrument_resolution(intent_id)
        assert intent is not None and intent.state == "KNOWN"
        assert intent.dispatch_state == "UNKNOWN"
        assert dict(original_identity) == dict(intent.original_identity)
        assert resolution is not None
        assert resolution.reconciliation_id == reconciliation_id
        assert resolution.position_flat is True
        assert journal.active_instrument_owner(_ACCOUNT_SCOPE, _INSTRUMENT) is None
        assert expected_session == {
            "account_fingerprint": facts_helpers._ACCOUNT,
            "connection_generation": expected_generation,
            "trading_day": _TRADING_DAY,
            "front_id": expected_front_id,
            "session_id": expected_session_id,
        }
        if terminal_event is not None:
            assert terminal_event["kind"] == "order"
            assert terminal_event["status"] == "canceled"
            assert terminal_event["terminal_confirmed"] is True
            assert terminal_event["execution_unknown"] is False
            assert terminal_event["filled"] == 0
            assert terminal_event["remaining"] == terminal_event["size"]
            assert terminal_event["details"]["OrderStatus"] in ("5", "CANCELED")
            assert terminal_event["details"]["FrontID"] == original_identity["front_id"]
            assert terminal_event["details"]["SessionID"] == original_identity["session_id"]
        if capture_inputs is not None:
            capture_inputs.append(
                {
                    "original_identity": dict(original_identity),
                    "expected_session": dict(expected_session),
                    "terminal_event": dict(terminal_event) if terminal_event is not None else None,
                }
            )
        capture.append(
            retire(
                intent_id,
                reconciliation_id,
                original_identity=original_identity,
                expected_session=expected_session,
                terminal_event=terminal_event,
            )
        )
        return capture[-1]

    store.registered_sim_retire_unknown = checked_retirement


class _UnknownRecoveryStrategy(bt.Strategy):
    params = (("command", None), ("state", None))

    def __init__(self):
        self._bar_index = 0

    def next(self):
        self.p.command(self, self._bar_index)
        self._bar_index += 1

    def notify_order(self, order):
        self.p.state["notifications"].append(
            (
                order.ref,
                order.getstatusname(),
                order.info.get("factor_intent_id"),
                threading.get_ident(),
            )
        )
        if order.getstatusname() == "Canceled":
            self.p.state["terminal_callback"].set()


def _child_reconcile_reopened_journal(journal_path, terminal_row, result_queue):
    """Spawn target: recover one old UNKNOWN under the fresh current session."""
    now = datetime.now(timezone.utc)
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        target,
        data,
        strategy,
        _cerebro,
    ) = _durable_system(
        journal_path,
        now=now,
        bars=1,
    )
    api.query_rows["orders_result"] = [terminal_row]
    _bind_current_session_identity(api, generation=2, front_id=5, session_id=8)
    stage = "session_and_initial_refresh"
    try:
        # The exact same account/day and original order lineage survive a
        # reconnect, while a newly completed source receipt belongs to gen 2.
        api.trader_client._gate_state["armed"] = False
        assert not broker.orders
        historical_orders_rebuilt = bool(broker.orders)

        receipt, facts = _refresh_five_family_facts(
            api,
            store,
            broker,
            target,
            generation=2,
            sequence=9,
        )
        captured_retirement = []
        captured_retirement_inputs = []
        _retirement_status_probe(
            store,
            journal,
            captured_retirement,
            expected_generation=2,
            expected_front_id=5,
            expected_session_id=8,
            capture_inputs=captured_retirement_inputs,
        )
        stage = "terminal_reconciliation"
        page = coordinator.reconcile_terminal_order_observations(
            facts,
            refresh_receipt=receipt,
            limit=128,
        )
        assert len(page.items) == 1
        item = page.items[0]
        assert item.status == "RESOLVED", item
        intent = journal.intent(item.intent_id)
        resolution = journal.instrument_resolution(item.intent_id)
        assert intent is not None and intent.state == "KNOWN"
        assert intent.dispatch_state == "UNKNOWN"
        assert resolution is not None and resolution.position_flat is True
        assert resolution.reconciliation_id == item.reconciliation_id
        assert journal.active_instrument_owner(_ACCOUNT_SCOPE, _INSTRUMENT) is None
        assert len(captured_retirement) == 1
        retirement = captured_retirement[0]
        assert len(captured_retirement_inputs) == 1
        assert captured_retirement_inputs[0]["original_identity"] == dict(intent.original_identity)
        assert not broker.orders, "fresh-process recovery must not rebuild a historical BT Order"
        owner_released_after_recovery = (
            journal.active_instrument_owner(_ACCOUNT_SCOPE, _INSTRUMENT) is None
        )

        # The child has no historical BT Order to reconstruct. It can still
        # admit a later grid through the normal decision-scope and Broker
        # path after a new complete current-generation observation.
        stage = "later_grid_refresh"
        store.registered_sim_configure_arm_templates({(_INSTRUMENT, _EXCHANGE): _arm_template()})
        api._next_order_reference = 900
        later_receipt, later_facts = _refresh_five_family_facts(
            api,
            store,
            broker,
            target,
            generation=2,
            sequence=10,
            include_margin=True,
        )
        assert later_receipt.query_set.connection_generation == 2
        assert later_facts.open_risk_ready is True, later_facts.blockers
        assert not broker.orders
        stage = "later_grid_submit"
        new_order = _submit_open(
            coordinator,
            strategy,
            data,
            later_facts,
            close_time=later_facts.available_at - timedelta(milliseconds=2),
            batch_id="unknown-recovered-fresh-process-grid",
        )
        assert new_order is not None
        new_intent_id = new_order.info["factor_intent_id"]
        new_intent = journal.intent(new_intent_id)
        assert new_intent is not None and new_intent.state == "KNOWN"
        assert new_intent.dispatch_state == "KNOWN"
        assert new_intent_id != item.intent_id
        assert len(api.native_calls) == 1
        assert api.native_calls[0][0] == "insert"
        assert len(broker.orders) == 1

        result_queue.put(
            {
                "status": "OK",
                "item_status": item.status,
                "reconciliation_id_present": bool(item.reconciliation_id),
                "retirement_status": retirement.status,
                "retirement_disarmed": retirement.disarmed,
                "historical_orders_rebuilt": historical_orders_rebuilt,
                "current_generation": receipt.query_set.connection_generation,
                "current_front_id": api.trader_client.get_session_state()["front_id"],
                "current_session_id": api.trader_client.get_session_state()["session_id"],
                "dispatch_state_preserved": intent.dispatch_state == "UNKNOWN",
                "owner_released": owner_released_after_recovery,
                "new_grid_intent_id": new_intent_id,
                "new_grid_dispatch_state": new_intent.dispatch_state,
                "new_grid_order_ref": new_order.info["external_order_ref"],
                "new_grid_native_calls": len(api.native_calls),
            }
        )
    except BaseException as error:
        result_queue.put(
            {
                "status": "ERROR",
                "error_stage": stage,
                "error_type": type(error).__name__,
                "error_code": getattr(error, "code", None),
                "error_message": str(error)[:240],
            }
        )
    finally:
        journal.close()


def test_unknown_timeout_recovers_through_cerebro_callback_and_later_grid(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    gate = execution_helpers._BarAdvanceGate()
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        target,
        data,
        _manual_strategy,
        cerebro,
    ) = _durable_system(
        tmp_path / "same-engine-unknown.sqlite3",
        now=now,
        bars=5,
        bar_advance_gate=gate,
    )
    initial_facts = _initial_open_facts(api, store, broker, target, now=now)
    native_insert = _install_request_then_timeout(api)
    state = {
        "initial_sent": threading.Event(),
        "bar1_warmup": threading.Event(),
        "bar2_after_callback": threading.Event(),
        "bar3_warmup": threading.Event(),
        "new_grid_sent": threading.Event(),
        "terminal_callback": threading.Event(),
        "order": None,
        "new_order": None,
        "notifications": [],
        "engine_thread_id": None,
        "error": None,
        "retirement": [],
        "retirement_inputs": [],
        "new_grid_facts": None,
    }
    initial_intent_id = None

    def command(owner, bar_index):
        if bar_index == 0:
            state["engine_thread_id"] = threading.get_ident()
            state["order"] = _submit_open(
                coordinator,
                owner,
                owner.data0,
                initial_facts,
                close_time=initial_facts.available_at - timedelta(milliseconds=2),
                batch_id="unknown-before-timeout",
            )
            api.trader_client.submit_order_insert = native_insert
            state["initial_sent"].set()
        elif bar_index == 1:
            state["bar1_warmup"].set()
        elif bar_index == 2:
            state["bar2_after_callback"].set()
        elif bar_index == 3:
            state["bar3_warmup"].set()
        elif bar_index == 4:
            facts = state["new_grid_facts"]
            state["new_order"] = _submit_open(
                coordinator,
                owner,
                owner.data0,
                facts,
                close_time=facts.available_at - timedelta(milliseconds=2),
                batch_id="unknown-recovered-later-grid",
            )
            state["new_grid_sent"].set()

    def run_engine():
        try:
            cerebro.addstrategy(_UnknownRecoveryStrategy, command=command, state=state)
            state["result"] = cerebro.run(runonce=False, preload=False)
        except BaseException as error:
            state["error"] = error
            for event_name, value in state.items():
                if isinstance(value, threading.Event):
                    value.set()

    engine = threading.Thread(target=run_engine, name="unknown-recovery-cerebro")
    engine.start()
    try:
        assert state["initial_sent"].wait(10), state["error"]
        order = state["order"]
        assert order is not None and order.info["execution_unknown"] is True
        assert order.info["factor_dispatch_state"] == "UNKNOWN"
        initial_intent_id = order.info["factor_intent_id"]
        assert len(api.native_calls) == 1
        assert api.native_calls[0][0] == "insert"
        intent_before = journal.intent(initial_intent_id)
        assert intent_before is not None
        assert intent_before.state == intent_before.dispatch_state == "UNKNOWN"

        # Old-grid callbacks/warmup do not resend the ambiguous request.
        gate.allow_through(1)
        assert state["bar1_warmup"].wait(10), state["error"]
        assert len(api.native_calls) == 1

        api.query_rows["orders_result"] = [_terminal_row(order.info["external_order_ref"])]
        receipt, terminal_facts = _refresh_five_family_facts(
            api,
            store,
            broker,
            target,
            generation=1,
            sequence=2,
            receipt_clock_advance_ms=10,
            monkeypatch=monkeypatch,
        )
        assert receipt.query_set.account_fingerprint == terminal_facts.account.account_fingerprint
        assert receipt.query_set.connection_generation == 1
        assert receipt.query_set.trading_day == _TRADING_DAY
        assert tuple(family for family, _request_id in receipt.query_set.query_ids) == (
            _CORE_FAMILIES
        )
        current_core_provenance = tuple(
            item for item in terminal_facts.query_provenance if item.family in _CORE_FAMILIES
        )
        assert tuple(item.family for item in current_core_provenance) == _CORE_FAMILIES
        query_ids = dict(receipt.query_set.query_ids)
        assert len(current_core_provenance) == len(_CORE_FAMILIES)
        assert all(
            item.source_owned is True
            and item.query_complete is True
            and item.scope_complete is True
            and item.connection_generation == 1
            and item.account_fingerprint == facts_helpers._ACCOUNT
            and item.trading_day == _TRADING_DAY
            and item.request_id == query_ids[item.family]
            for item in current_core_provenance
        )
        # The exact local Backtrader order is still alive until the recovery
        # terminal event reaches Broker.next/Cerebro. It must be identified as
        # this intent's sole UNKNOWN row, not treated as an unrelated order.
        same_route_working = [
            row
            for row in terminal_facts.working_orders
            if row.instrument == _INSTRUMENT and row.exchange == _EXCHANGE
        ]
        assert len(same_route_working) == 1
        unknown_working = same_route_working[0]
        assert unknown_working.order_ref == order.info["external_order_ref"]
        assert unknown_working.owner_intent_id == initial_intent_id
        assert unknown_working.owner_strategy_scope == _STRATEGY_SCOPE
        assert unknown_working.execution_unknown is True
        assert unknown_working.broker_order_ref == order.ref
        assert unknown_working.front_id == 4
        assert unknown_working.session_id == 7
        assert terminal_facts.trade_observations == ()
        assert terminal_facts.positions[0].broker_quantity == Decimal("0")
        assert terminal_facts.positions[0].long_quantity == Decimal("0")
        assert terminal_facts.positions[0].short_quantity == Decimal("0")
        assert terminal_facts.terminal_orders[0].terminal_state == "CANCELED"
        assert terminal_facts.terminal_orders[0].front_id == 4
        assert terminal_facts.terminal_orders[0].session_id == 7
        assert terminal_facts.terminal_orders[0].volume_traded == Decimal("0")
        assert terminal_facts.terminal_orders[0].volume_total_original == Decimal("1")
        assert terminal_facts.terminal_orders[0].volume_total == Decimal("1")

        _retirement_status_probe(
            store,
            journal,
            state["retirement"],
            expected_generation=1,
            expected_front_id=4,
            expected_session_id=7,
            capture_inputs=state["retirement_inputs"],
        )
        page = coordinator.reconcile_terminal_order_observations(
            terminal_facts,
            refresh_receipt=receipt,
            limit=128,
        )
        assert len(page.items) == 1
        recovered = page.items[0]
        assert recovered.status == "RESOLVED", recovered
        assert recovered.intent_id == initial_intent_id
        assert recovered.reconciliation_id
        intent_after = journal.intent(initial_intent_id)
        resolution = journal.instrument_resolution(initial_intent_id)
        assert intent_after is not None and intent_after.state == "KNOWN"
        assert intent_after.dispatch_state == "UNKNOWN"
        assert resolution is not None and resolution.position_flat is True
        assert resolution.reconciliation_id == recovered.reconciliation_id
        assert journal.active_instrument_owner(_ACCOUNT_SCOPE, _INSTRUMENT) is None
        assert len(state["retirement"]) == 1
        assert len(state["retirement_inputs"]) == 1
        assert state["retirement_inputs"][0]["terminal_event"] is not None
        assert state["retirement_inputs"][0]["original_identity"] == dict(
            intent_before.original_identity
        )
        assert state["retirement"][0].status == "QUEUED"
        assert state["retirement"][0].disarmed is True
        assert store.registered_sim_status()["frozen"] is False
        assert store.registered_sim_status()["armed"] is False
        assert api.registered_sim_execution_facts()["unknown_ids"] == []
        assert len(api.native_calls) == 1
        assert len(api._order_updates) == 1
        assert (
            order.alive()
        ), "durable proof retires the latch; only the normal callback ends BT Order"

        # Replaying the same durable proof before the queued callback drains
        # must be idempotent. A duplicate event would produce a second notify.
        replay = coordinator.reconcile_terminal_order_observations(
            terminal_facts,
            refresh_receipt=receipt,
            limit=128,
        )
        assert all(item.status != "BLOCKED" for item in replay.items)
        assert len(state["retirement"]) == 2
        assert state["retirement"][1].status == "ALREADY_ABSENT"
        assert state["retirement"][1].reconciliation_id == recovered.reconciliation_id
        assert len(state["retirement_inputs"]) == 2
        assert len(api._order_updates) == 1, "replay must not enqueue a duplicate callback"

        # Recovery itself queues the exact zero-fill terminal update. The
        # ordinary Store poll, Broker.next and Cerebro notification must
        # update this original in-memory Order on the engine thread.
        gate.allow_through(2)
        assert state["bar2_after_callback"].wait(10), state["error"]
        assert state["terminal_callback"].wait(10), state["notifications"]
        assert order.status == Order.Canceled
        assert order.alive() is False
        terminal_notifications = [item for item in state["notifications"] if item[1] == "Canceled"]
        assert len(terminal_notifications) == 1
        assert terminal_notifications[0][0] == order.ref
        assert terminal_notifications[0][2] == initial_intent_id
        assert terminal_notifications[0][3] == state["engine_thread_id"]
        assert len(api.native_calls) == 1

        # A warmup bar after retirement and terminal callback still dispatches
        # nothing. Only a later, distinct grid may re-arm through the normal
        # decision-scope / ensure-arm / Broker submit sequence.
        gate.allow_through(3)
        assert state["bar3_warmup"].wait(10), state["error"]
        assert len(api.native_calls) == 1

        # The durable UNKNOWN proof retires the exact Store freeze. Broker's
        # separate CTP exposure barrier still requires its ordinary pair of
        # complete, distinct flat query snapshots before a new opening order.
        def execution_summary():
            projection = api.registered_sim_execution_facts()
            return {
                "unknown_ids": list(projection["unknown_ids"]),
                "active_orders": len(projection["active_order_ids"]),
                "unmatched_trade_count": 0,
            }

        api.get_execution_summary = execution_summary
        first_reconcile = broker.reconcile_ctp_execution(timeout=0)
        assert first_reconcile["complete"] is False
        assert first_reconcile["consecutive_complete_rounds"] == 1
        second_reconcile = broker.reconcile_ctp_execution(timeout=0)
        assert second_reconcile["complete"] is True, second_reconcile
        assert second_reconcile["consecutive_complete_rounds"] == 2

        api.use_live_query_clock = True
        new_receipt = facts_helpers._refresh_all(store, target)
        new_completed = new_receipt.query_set.completed_at_utc
        new_received = max(datetime.now(timezone.utc), new_completed) + timedelta(milliseconds=2)
        api.tick = facts_helpers._quote(
            event_time=new_completed,
            received_at=new_received,
            generation=1,
            sequence=3,
            trading_day=_TRADING_DAY,
        )
        assert facts_helpers._consume_quote(store) is not None
        new_grid_now = max(datetime.now(timezone.utc), new_received) + timedelta(milliseconds=2)
        new_grid_facts = facts_helpers._project(
            store,
            broker,
            target,
            new_grid_now,
            query_set=new_receipt.query_set,
        )
        assert new_grid_facts.open_risk_ready is True, new_grid_facts.blockers
        state["new_grid_facts"] = new_grid_facts
        gate.allow_through(4)
        assert state["new_grid_sent"].wait(10), state["error"]
        assert state["new_order"] is not None
        assert state["new_order"].info["factor_dispatch_state"] == "KNOWN", dict(
            state["new_order"].info
        )
        assert state["new_order"].info["factor_intent_id"] != initial_intent_id
        assert len(api.native_calls) == 2
        assert api.native_calls[1][0] == "insert"
        assert api.native_calls[1][3] != api.native_calls[0][3]
        assert journal.intent(initial_intent_id).dispatch_state == "UNKNOWN"
    finally:
        gate.allow_through(100)
        engine.join(timeout=15)
        journal.close()
    assert not engine.is_alive()
    assert state["error"] is None


def test_reopened_journal_resolves_unknown_on_fresh_generation_without_order_rebuild(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "fresh-process-unknown.sqlite3"
    api, store, broker, journal, coordinator, target, data, strategy, _cerebro = _durable_system(
        path,
        now=now,
    )
    try:
        initial_facts = _initial_open_facts(api, store, broker, target, now=now)
        native_insert = _install_request_then_timeout(api)
        order = _submit_open(
            coordinator,
            strategy,
            data,
            initial_facts,
            close_time=initial_facts.available_at - timedelta(milliseconds=2),
            batch_id="unknown-before-process-restart",
        )
        api.trader_client.submit_order_insert = native_insert
        assert order.info["execution_unknown"] is True
        assert len(api.native_calls) == 1
        intent_id = order.info["factor_intent_id"]
        persisted = journal.intent(intent_id)
        assert persisted is not None and persisted.state == "UNKNOWN"
        identity = persisted.original_identity
        assert identity["account_fingerprint"] == facts_helpers._ACCOUNT
        assert identity["connection_generation"] == 1
        assert identity["trading_day"] == _TRADING_DAY
        assert identity["instrument_id"] == _INSTRUMENT
        assert identity["exchange_id"] == _EXCHANGE
        assert identity["order_ref"] == order.info["external_order_ref"]
        assert identity["front_id"] == 4
        assert identity["session_id"] == 7
        assert identity["operation"] == "insert"
        assert identity["backtrader_order_ref"] == order.ref
        terminal = _terminal_row(
            identity["order_ref"],
            front_id=identity["front_id"],
            session_id=identity["session_id"],
            trading_day=identity["trading_day"],
        )
        original_generation = identity["connection_generation"]
        journal.close()

        context = multiprocessing.get_context("spawn")
        result_queue = context.Queue()
        child = context.Process(
            target=_child_reconcile_reopened_journal,
            args=(str(path), terminal, result_queue),
            name="factor-execution-unknown-recovery",
        )
        child.start()
        child.join(timeout=45)
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)
            pytest.fail("fresh-process unknown recovery did not finish within its bound")
        assert child.exitcode == 0
        child_result = result_queue.get(timeout=3)
        result_queue.close()
        result_queue.join_thread()
        assert child_result["status"] == "OK", child_result
        assert child_result["item_status"] == "RESOLVED"
        assert child_result["reconciliation_id_present"] is True
        assert child_result["retirement_status"] == "ALREADY_ABSENT"
        assert child_result["retirement_disarmed"] is True
        assert child_result["historical_orders_rebuilt"] is False
        assert child_result["current_generation"] == 2
        assert child_result["current_front_id"] == 5
        assert child_result["current_session_id"] == 8
        assert original_generation == 1
        assert child_result["dispatch_state_preserved"] is True
        assert child_result["owner_released"] is True
        assert child_result["new_grid_intent_id"] != intent_id
        assert child_result["new_grid_order_ref"] != identity["order_ref"]
        assert child_result["new_grid_dispatch_state"] == "KNOWN"
        assert child_result["new_grid_native_calls"] == 1

        # Independently reopen in the parent and inspect durable final state.
        recovered_journal = ExecutionDecisionJournal(path)
        try:
            recovered_intent = recovered_journal.intent(intent_id)
            resolution = recovered_journal.instrument_resolution(intent_id)
            assert recovered_intent is not None
            assert recovered_intent.state == "KNOWN"
            assert recovered_intent.dispatch_state == "UNKNOWN"
            assert resolution is not None and resolution.position_flat is True
            new_intent = recovered_journal.intent(child_result["new_grid_intent_id"])
            assert new_intent is not None and new_intent.dispatch_state == "KNOWN"
            active_owner = recovered_journal.active_instrument_owner(_ACCOUNT_SCOPE, _INSTRUMENT)
            assert active_owner is not None
            assert active_owner.intent_id == child_result["new_grid_intent_id"]
            assert len(api.native_calls) == 1
        finally:
            recovered_journal.close()
    finally:
        journal.close()


@pytest.mark.parametrize(
    "case",
    (
        "lineage_mismatch",
        "stale_snapshot",
        "incomplete_five_family",
        "other_working_order",
        "malformed_trade",
        "duplicate_trade",
        "malformed_active_order",
        "duplicate_active_order",
    ),
)
def test_unproven_terminal_recovery_keeps_unknown_frozen(tmp_path, case):
    now = datetime.now(timezone.utc)
    path = tmp_path / "blocked-{}.sqlite3".format(case)
    api, store, broker, journal, coordinator, target, data, strategy, _cerebro = _durable_system(
        path,
        now=now,
    )
    try:
        initial_facts = _initial_open_facts(api, store, broker, target, now=now)
        native_insert = _install_request_then_timeout(api)
        order = _submit_open(
            coordinator,
            strategy,
            data,
            initial_facts,
            close_time=initial_facts.available_at - timedelta(milliseconds=2),
            batch_id="unknown-negative-{}".format(case),
        )
        api.trader_client.submit_order_insert = native_insert
        intent_id = order.info["factor_intent_id"]
        original_identity = journal.intent(intent_id).original_identity

        terminal = _terminal_row(order.info["external_order_ref"])
        expected_blocker_prefix = None
        if case == "lineage_mismatch":
            terminal["SessionID"] += 1
        elif case == "other_working_order":
            active = dict(
                terminal,
                OrderRef="987654321",
                OrderSysID="different-working-order",
                OrderStatus="3",
                VolumeTotalOriginal="2",
                VolumeTraded="0",
                VolumeTotal="2",
            )
            api.query_rows["orders_result"] = [terminal, active]
        elif case == "malformed_trade":
            api.query_rows["trades_result"] = [
                {
                    "TradeID": "malformed-trade",
                    "TradingDay": _TRADING_DAY,
                    "OrderRef": terminal["OrderRef"],
                    "InstrumentID": _INSTRUMENT,
                    "ExchangeID": _EXCHANGE,
                }
            ]
            expected_blocker_prefix = "remote_trade_fields_unobserved:"
        elif case == "duplicate_trade":
            trade = {
                "TradeID": "duplicate-trade",
                "OrderRef": terminal["OrderRef"],
                "OrderSysID": "",
                "InstrumentID": _INSTRUMENT,
                "ExchangeID": _EXCHANGE,
                "Direction": "0",
                "OffsetFlag": "0",
                "HedgeFlag": "1",
                "Volume": "1",
                "Price": "100",
                # The prior Shanghai calendar day guarantees this historical
                # row precedes the current query completion at any time on
                # the pinned trading day.
                "TradeDate": "20261023",
                "TradeTime": "00:00:00",
                "TradingDay": _TRADING_DAY,
            }
            api.query_rows["trades_result"] = [trade, dict(trade)]
            expected_blocker_prefix = "remote_trade_id_duplicate:"
        elif case == "malformed_active_order":
            malformed_active = {
                "OrderRef": "987654321",
                "OrderSysID": "malformed-active-order",
                "InstrumentID": _INSTRUMENT,
                "ExchangeID": _EXCHANGE,
                "OrderStatus": "3",
                # Deliberately absent TradingDay: the source row cannot prove
                # the full active-order set for this query.
            }
            api.query_rows["orders_result"] = [terminal, malformed_active]
            expected_blocker_prefix = "remote_order_trading_day_unobserved_or_mismatch"
        elif case == "duplicate_active_order":
            active = {
                "OrderRef": "987654321",
                "OrderSysID": "duplicate-active-order",
                "InstrumentID": _INSTRUMENT,
                "ExchangeID": _EXCHANGE,
                "OrderStatus": "3",
                "TradingDay": _TRADING_DAY,
            }
            api.query_rows["orders_result"] = [terminal, active, dict(active)]
            expected_blocker_prefix = "remote_order_identity_duplicate:"
        else:
            api.query_rows["orders_result"] = [terminal]

        if case not in {"other_working_order", "malformed_active_order", "duplicate_active_order"}:
            api.query_rows["orders_result"] = [terminal]
        receipt, facts = _refresh_five_family_facts(
            api,
            store,
            broker,
            target,
            generation=1,
            sequence=6,
            stale_query=(case == "stale_snapshot"),
        )
        if case == "stale_snapshot":
            assert any(
                blocker.startswith("query_snapshot_invalid_or_stale:") for blocker in facts.blockers
            )
        if expected_blocker_prefix is not None:
            assert any(
                blocker.startswith(expected_blocker_prefix) for blocker in facts.blockers
            ), facts.blockers
            assert facts.terminal_orders, "the valid terminal row must remain independently visible"
        if case in {"malformed_trade", "duplicate_trade"}:
            assert facts.trade_observations == ()
        if case in {"malformed_active_order", "duplicate_active_order"}:
            assert all(
                row.order_ref != "987654321" for row in facts.working_orders
            ), "unusable raw active-order rows must not be represented as complete working facts"
        if case == "incomplete_five_family":
            # The otherwise-valid facts cannot be paired with a later receipt
            # missing its fifth core family; the coordinator must reject the
            # exact refresh receipt instead of silently reusing cached rows.
            incomplete = refresh_factor_execution_queries(
                store,
                targets=(target,),
                overall_timeout=4.0,
                include_core=True,
                margin_target_ids=(),
                max_queries=4,
            )
            assert incomplete.query_set is None
            receipt = incomplete

        try:
            page = coordinator.reconcile_terminal_order_observations(
                facts,
                refresh_receipt=receipt,
                limit=128,
            )
        except FactorExecutionError:
            page = None
        if page is not None:
            assert all(item.status != "RESOLVED" for item in page.items)
        _assert_still_unknown(journal, store, api, intent_id)
        assert journal.intent(intent_id).original_identity == original_identity
        assert store.registered_sim_status()["armed"] is False
    finally:
        journal.close()
