"""Durability failures at the ordinary registered-sim dispatch boundary.

The test harness reuses the real Broker, Store wrapper, journal, coordinator,
and ordinary ``Strategy.buy/cancel`` methods.  Only the provider/native leaves
are fake; no SDK, account, or provider connection is created.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from backtrader.order import Order
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionKey,
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
    ExecutionIntentKey,
)
from backtrader.stores.factor_execution import FactorExecutionCoordinator
from tests.unit.stores import test_factor_execution as execution_helpers
from tests.unit.stores import test_factor_execution_facts as facts_helpers


_INSTRUMENT = execution_helpers._INSTRUMENT
_EXCHANGE = execution_helpers._EXCHANGE
_ACCOUNT_SCOPE = execution_helpers._ACCOUNT_SCOPE
_SCOPE = execution_helpers._SCOPE
_SDK_MD_FRONT = "tcp://182.254.243.31:30012"


def _durable_system(path, *, now, monkeypatch=None):
    if monkeypatch is None:
        system = execution_helpers._system(now=now)
    else:
        # The cancel path needs a Store-minted, source-owned order-identity
        # query receipt, which only the canonical SDK leaves can attest. The
        # shared helper keeps the production Store/Broker/journal path intact.
        system = execution_helpers._source_sdk_system(monkeypatch, now=now)
    (
        api,
        store,
        broker,
        memory_journal,
        _coordinator,
        target,
        data,
        strategy,
        _cerebro,
    ) = system[:9]
    memory_journal.close()
    broker.factor_execution_coordinator = None
    journal = ExecutionDecisionJournal(path)
    coordinator = FactorExecutionCoordinator(
        broker,
        journal,
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_SCOPE,
        logical_run_id="run-1",
        max_order_intents_per_grid=4,
        max_order_intents_per_run=100,
    )
    return api, store, broker, journal, coordinator, target, data, strategy


def _ready_facts(store, broker, target, *, now, md_front="tcp://127.0.0.1:1"):
    query = facts_helpers._refresh_all(store, target)
    store.registered_sim_configure_arm_templates(
        {
            (_INSTRUMENT, _EXCHANGE): {
                "md_front": md_front,
                "strategy_identity_sha256": "a" * 64,
                "execution_cycle_id": "cycle-1",
                "preflight_sha256": "b" * 64,
            }
        }
    )
    store.registered_sim_arm(
        instrument=_INSTRUMENT,
        exchange=_EXCHANGE,
        md_front=md_front,
        strategy_identity_sha256="a" * 64,
        execution_cycle_id="cycle-1",
        preflight_sha256="b" * 64,
    )
    assert facts_helpers._consume_quote(store) is not None
    facts = facts_helpers._project(store, broker, target, now, query_set=query.query_set)
    assert facts.open_risk_ready is True, facts.blockers
    return facts


def _opening_order(coordinator, strategy, data, facts, *, now):
    key = ExecutionIntentKey(
        action="SUBMIT",
        instrument=_INSTRUMENT,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    economics = {
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
        "batch_id": "batch-1",
        "price": "100",
    }
    with execution_helpers._live_scope(
        coordinator,
        strategy,
        facts,
        now=now,
        intent_key=key,
        economics=economics,
    ):
        order = strategy.buy(
            data=data,
            size=1,
            price=100,
            exectype=Order.Limit,
            instrument_id=_INSTRUMENT,
            exchange_id=_EXCHANGE,
            factor_position_effect="OPEN",
            factor_strategy_scope=_SCOPE,
            offset="open",
        )
    return order


def _install_trigger(path, sql):
    with sqlite3.connect(path) as connection:
        connection.execute(sql)


def test_decision_write_failure_prevents_strategy_submit(tmp_path):
    path = tmp_path / "decision-failure.sqlite3"
    now = datetime.now(timezone.utc)
    api, store, broker, journal, coordinator, target, data, strategy = _durable_system(
        path, now=now
    )
    try:
        facts = _ready_facts(store, broker, target, now=now)
        _install_trigger(
            path,
            """CREATE TRIGGER reject_grid_decision
               BEFORE INSERT ON execution_decisions
               BEGIN SELECT RAISE(ABORT, 'synthetic decision write failure'); END""",
        )

        with pytest.raises(ExecutionDecisionJournalError) as caught:
            _opening_order(coordinator, strategy, data, facts, now=now)

        assert caught.value.code == "JOURNAL_WRITE_FAILED"
        assert api.native_calls == []
        assert store.registered_sim_dispatch_history() == ()
        journal.close()
        recovered = ExecutionDecisionJournal(path)
        try:
            assert recovered.recoverable_intents(limit=8) == ()
            assert recovered.grid_cursor(_ACCOUNT_SCOPE, _SCOPE, "rb-cohort") is None
            assert recovered.decision_capacity_snapshot().base_record_count == 0
        finally:
            recovered.close()
    finally:
        journal.close()


def test_claim_write_failure_rolls_back_before_native_submit(tmp_path):
    path = tmp_path / "claim-failure.sqlite3"
    now = datetime.now(timezone.utc)
    api, store, broker, journal, coordinator, target, data, strategy = _durable_system(
        path, now=now
    )
    try:
        facts = _ready_facts(store, broker, target, now=now)
        _install_trigger(
            path,
            """CREATE TRIGGER reject_dispatch_claim
               BEFORE UPDATE OF state ON execution_decision_intents
               WHEN NEW.state = 'DISPATCHING'
               BEGIN SELECT RAISE(ABORT, 'synthetic claim write failure'); END""",
        )

        with pytest.raises(ExecutionDecisionJournalError):
            _opening_order(coordinator, strategy, data, facts, now=now)

        assert api.native_calls == []
        assert store.registered_sim_dispatch_history() == ()
        journal.close()
        recovered = ExecutionDecisionJournal(path)
        try:
            intents = recovered.recoverable_intents(limit=8)
            assert len(intents) == 1
            assert intents[0].key.action == "SUBMIT"
            assert intents[0].state == "PREPARED"
            assert intents[0].dispatch_state is None
            owner = recovered.active_instrument_owner(_ACCOUNT_SCOPE, _INSTRUMENT)
            assert owner is not None
            assert owner.intent_id == intents[0].intent_id
            assert owner.state == "PREPARED"
        finally:
            recovered.close()
    finally:
        journal.close()


def test_cancel_claim_write_failure_prevents_native_cancel(tmp_path, monkeypatch):
    path = tmp_path / "cancel-claim-failure.sqlite3"
    now = datetime.now(timezone.utc)
    api, store, broker, journal, coordinator, target, data, strategy = _durable_system(
        path, now=now, monkeypatch=monkeypatch
    )
    try:
        facts = _ready_facts(store, broker, target, now=now, md_front=_SDK_MD_FRONT)
        order = _opening_order(coordinator, strategy, data, facts, now=now)
        assert order is not None and order.alive()
        assert order.info["factor_dispatch_state"] == "KNOWN"
        assert len(api.native_calls) == 1

        provider_order = api._provider_orders[order.info["external_order_ref"]]
        active_order = {
            "OrderRef": order.info["external_order_ref"],
            "OrderSysID": "sys-501",
            "InstrumentID": provider_order["instrument_id"],
            "ExchangeID": provider_order["exchange_id"],
            "OrderStatus": "3",
            "Direction": "0",
            "CombOffsetFlag": "0",
            "VolumeTotalOriginal": str(provider_order["size"]),
            "VolumeTraded": "0",
            "VolumeTotal": str(provider_order["size"]),
            "FrontID": provider_order["front_id"],
            "SessionID": provider_order["session_id"],
            "TradingDay": facts_helpers._TRADING_DAY,
        }
        api.query_rows = facts_helpers._query_rows(orders=(active_order,))
        api._use_observed_query_clock = True
        query = facts_helpers._refresh_all(store, target)
        quote_received = datetime.now(timezone.utc)
        api.tick = facts_helpers._quote(
            event_time=query.query_set.completed_at_utc,
            received_at=quote_received,
            sequence=2,
        )
        assert facts_helpers._consume_quote(store) is not None
        cancel_facts = facts_helpers._project(
            store,
            broker,
            target,
            quote_received + timedelta(milliseconds=1),
            query_set=query.query_set,
        )
        assert cancel_facts.order_cancel_ready is True, cancel_facts.order_cancel_blockers

        cancel_key = ExecutionIntentKey(
            action="CANCEL",
            instrument=_INSTRUMENT,
            side="BUY",
            position_effect="OPEN",
            leg=0,
        )
        cancel_economics = {
            "instrument": _INSTRUMENT,
            "exchange": _EXCHANGE,
            "side": "BUY",
            "position_effect": "OPEN",
            "owner_intent_id": order.info["factor_intent_id"],
            "reason": "durability-failure cancel test",
        }
        _install_trigger(
            path,
            """CREATE TRIGGER reject_cancel_dispatch_claim
               BEFORE UPDATE OF state ON execution_decision_intents
               WHEN NEW.state = 'DISPATCHING'
               BEGIN SELECT RAISE(ABORT, 'synthetic cancel claim failure'); END""",
        )
        with pytest.raises(ExecutionDecisionJournalError), coordinator.risk_decision_scope(
            owner=strategy,
            key=ExecutionDecisionKey(
                account_scope=_ACCOUNT_SCOPE,
                strategy_scope=_SCOPE,
                logical_run_id="run-1",
                cohort_id=execution_helpers._COHORT,
                close_time=cancel_facts.available_at.isoformat().replace("+00:00", "Z"),
                decision_kind="ALPHA003_RISK_REDUCTION",
            ),
            economic_payload={"intent_economics": (cancel_economics,)},
            intent_keys=(cancel_key,),
            execution_facts=cancel_facts,
            inputs_complete=True,
            expected_run_order_intents_used=coordinator.run_order_count(),
            remaining_exit_intent_reserve=0,
        ):
            strategy.cancel(order)

        assert api.native_calls == [
            ("insert", _INSTRUMENT, _EXCHANGE, order.info["external_order_ref"], 101)
        ]
        assert order.alive()
        assert order.info.get("cancel_requested_remote", False) is False
        journal.close()
        recovered = ExecutionDecisionJournal(path)
        try:
            cancel_intents = tuple(
                item
                for item in recovered.recoverable_intents(limit=8)
                if item.key.action == "CANCEL"
            )
            assert len(cancel_intents) == 1
            assert cancel_intents[0].state == "PREPARED"
            assert cancel_intents[0].dispatch_state is None
            owner = recovered.active_instrument_owner(_ACCOUNT_SCOPE, _INSTRUMENT)
            assert owner is not None
            assert owner.intent_id == order.info["factor_intent_id"]
            assert owner.cancel_intent_id == cancel_intents[0].intent_id
        finally:
            recovered.close()
    finally:
        journal.close()


def test_native_ack_with_result_commit_failure_recovers_as_dispatching_no_retry(tmp_path):
    path = tmp_path / "result-commit-failure.sqlite3"
    now = datetime.now(timezone.utc)
    api, store, broker, journal, coordinator, target, data, strategy = _durable_system(
        path, now=now
    )
    try:
        facts = _ready_facts(store, broker, target, now=now)
        _install_trigger(
            path,
            """CREATE TRIGGER reject_dispatch_result
               BEFORE UPDATE OF state ON execution_decision_intents
               WHEN NEW.state IN ('KNOWN', 'UNKNOWN')
               BEGIN SELECT RAISE(ABORT, 'synthetic result commit failure'); END""",
        )

        order = _opening_order(coordinator, strategy, data, facts, now=now)

        assert len(api.native_calls) == 1
        assert api.native_calls[0][0] == "insert"
        assert order is not None and order.alive()
        assert order.info["factor_dispatch_state"] == "UNKNOWN"
        assert order.info["execution_unknown"] is True
        assert order.info["error_code"] == "dispatch_result_not_durable"
        evidence = store.registered_sim_dispatch_history()
        assert len(evidence) == 1 and evidence[0].status == "KNOWN"
        intent_id = order.info["factor_intent_id"]

        journal.close()
        recovered = ExecutionDecisionJournal(path)
        try:
            persisted = recovered.intent(intent_id)
            assert persisted is not None
            # The native ACK happened, but the result transaction did not
            # commit. DISPATCHING is therefore the truthful recovery state.
            assert persisted.state == "DISPATCHING"
            assert persisted.dispatch_state is None
            assert persisted.original_identity["order_ref"] == order.info["external_order_ref"]
            assert recovered.active_instrument_owner(_ACCOUNT_SCOPE, _INSTRUMENT).intent_id == (
                intent_id
            )
            assert recovered.claim_dispatch(intent_id) is None
        finally:
            recovered.close()

        # The recovery read/claim check cannot re-enter the Store, so the one
        # observed native request remains exactly one after restart semantics.
        assert len(api.native_calls) == 1
    finally:
        journal.close()


def test_request_then_exception_persists_unknown_and_is_not_reclaimable(tmp_path):
    path = tmp_path / "ambiguous-native-outcome.sqlite3"
    now = datetime.now(timezone.utc)
    api, store, broker, journal, coordinator, target, data, strategy = _durable_system(
        path, now=now
    )
    try:
        facts = _ready_facts(store, broker, target, now=now)
        native_insert = api.trader_client.submit_order_insert

        def _request_then_timeout(field, request_id, *, execution_capability):
            native_insert(field, request_id, execution_capability=execution_capability)
            raise TimeoutError("synthetic lost response after request")

        api.trader_client.submit_order_insert = _request_then_timeout
        order = _opening_order(coordinator, strategy, data, facts, now=now)

        assert len(api.native_calls) == 1
        assert api.native_calls[0][0] == "insert"
        assert order is not None and order.alive()
        assert order.info["execution_unknown"] is True
        assert order.info["factor_dispatch_state"] == "UNKNOWN"
        intent_id = order.info["factor_intent_id"]

        journal.close()
        recovered = ExecutionDecisionJournal(path)
        try:
            persisted = recovered.intent(intent_id)
            assert persisted is not None
            assert persisted.state == "UNKNOWN"
            assert persisted.dispatch_state == "UNKNOWN"
            assert persisted.outcome_code == "registered_sim_insert_unknown"
            assert recovered.active_instrument_owner(_ACCOUNT_SCOPE, _INSTRUMENT).intent_id == (
                intent_id
            )
            assert recovered.claim_dispatch(intent_id) is None
        finally:
            recovered.close()
        assert len(api.native_calls) == 1
    finally:
        journal.close()
