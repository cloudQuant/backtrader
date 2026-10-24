"""Source-backed AC50-21 recovery for an ambiguous native CTP cancel.

The Store, Broker, coordinator, journal, and typed query pipeline are the real
production components. Only the provider and native SDK leaves are synthetic.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone

import pytest

from backtrader.order import Order
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionKey,
    ExecutionIntentKey,
)
from tests.integration import test_factor_execution_unknown_recovery as recovery
from tests.unit.stores import test_factor_execution_facts as facts_helpers


class _FailOnceOrderUpdateQueue(deque):
    def __init__(self, values=()):
        super().__init__(values)
        self.fail_next_append = False

    def append(self, value):
        if self.fail_next_append:
            self.fail_next_append = False
            raise OSError("synthetic terminal update queue failure")
        super().append(value)


def _submit_open_for_side(coordinator, owner, data, facts, *, side, close_time, batch_id):
    close_time = close_time.astimezone(timezone.utc)
    available_at = close_time + timedelta(milliseconds=1)
    batch = recovery.LiveCohortBatch(
        batch_id=batch_id,
        cohort_id="rb-cohort",
        calendar_id="simnow-common-minutes-v1",
        calendar_version="v1",
        epoch_id=1,
        slot_index=0,
        close_time=close_time,
        available_at=available_at,
    )
    snapshot = recovery.LiveFactorSnapshot(
        plan_id="alpha003-unknown-cancel-test",
        cohort_id=batch.cohort_id,
        calendar_id=batch.calendar_id,
        calendar_version=batch.calendar_version,
        frequency="1min",
        epoch_id=batch.epoch_id,
        batch_id=batch.batch_id,
        close_time=close_time,
        available_at=available_at,
        batch_complete=True,
        readiness=recovery.LiveFactorReadiness.LIVE_READY,
        readiness_reasons=(),
        factors={},
    )
    decision_key = ExecutionDecisionKey(
        account_scope=recovery._ACCOUNT_SCOPE,
        strategy_scope=recovery._STRATEGY_SCOPE,
        logical_run_id="run-1",
        cohort_id=batch.cohort_id,
        close_time=close_time.isoformat().replace("+00:00", "Z"),
        decision_kind="ALPHA003_GRID",
    )
    intent_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument=recovery._INSTRUMENT,
        side=side,
        position_effect="OPEN",
        leg=0,
    )
    economics = {
        "instrument": recovery._INSTRUMENT,
        "exchange": recovery._EXCHANGE,
        "side": side,
        "position_effect": "OPEN",
        "quantity": "1",
        "limit_price": "100",
        "offset": "open",
        "factor_stop_price": "95" if side == "BUY" else "105",
        "risk_policy_id": "a003-risk-v1",
        "risk_policy": {"stop_loss_ticks": 5, "max_loss_per_position": "25"},
        "entry_grid_ordinal": 1,
        "batch_id": batch_id,
        "price": "100",
    }
    scope = coordinator.decision_scope(
        owner=owner,
        key=decision_key,
        economic_payload={"intent_economics": (economics,)},
        intent_keys=(intent_key,),
        batch=batch,
        snapshot=snapshot,
        execution_facts=facts,
        inputs_complete=True,
        expected_run_order_intents_used=coordinator.run_order_count(),
        remaining_exit_intent_reserve=0,
    )
    submit = owner.buy if side == "BUY" else owner.sell
    with scope:
        return submit(
            data=data,
            size=1,
            price=100,
            exectype=Order.Limit,
            instrument_id=recovery._INSTRUMENT,
            exchange_id=recovery._EXCHANGE,
            factor_position_effect="OPEN",
            factor_strategy_scope=recovery._STRATEGY_SCOPE,
            offset="open",
        )


@pytest.mark.parametrize(
    ("side", "ctp_direction"),
    (("BUY", "0"), ("SELL", "1")),
    ids=("buy", "sell"),
)
def test_ambiguous_native_cancel_resolves_only_from_fresh_original_order_query(
    tmp_path, side, ctp_direction
):
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
        cerebro,
    ) = recovery._durable_system(tmp_path / "cancel-unknown.sqlite3", now=now)
    try:
        initial_facts = recovery._initial_open_facts(api, store, broker, target, now=now)
        order = _submit_open_for_side(
            coordinator,
            strategy,
            data,
            initial_facts,
            side=side,
            close_time=initial_facts.available_at - timedelta(milliseconds=2),
            batch_id="ac50-21-open-before-unknown-cancel-{}".format(side.lower()),
        )
        assert order is not None and order.status == Order.Accepted
        assert order.isbuy() is (side == "BUY")
        submit_intent_id = order.info["factor_intent_id"]
        submit_intent = journal.intent(submit_intent_id)
        assert submit_intent is not None
        assert submit_intent.state == submit_intent.dispatch_state == "KNOWN"

        original_order_ref = order.info["external_order_ref"]
        api.query_rows = facts_helpers._query_rows(
            orders=(
                {
                    "OrderRef": original_order_ref,
                    "InstrumentID": recovery._INSTRUMENT,
                    "ExchangeID": recovery._EXCHANGE,
                    "OrderStatus": "3",  # CTP no-trade-queueing / still working
                    "Direction": ctp_direction,
                    "CombOffsetFlag": "0",
                    "VolumeTotalOriginal": "1",
                    "VolumeTraded": "0",
                    "VolumeTotal": "1",
                    "FrontID": 4,
                    "SessionID": 7,
                },
            )
        )
        active_receipt, active_facts = recovery._refresh_five_family_facts(
            api, store, broker, target, generation=1, sequence=20
        )
        assert active_receipt.query_set is not None
        assert active_facts.order_cancel_ready is True, active_facts.order_cancel_blockers
        assert len(active_facts.working_orders) == 1
        assert active_facts.working_orders[0].order_ref == original_order_ref
        assert active_facts.working_orders[0].owner_intent_id == submit_intent_id

        cancel_key = ExecutionDecisionKey(
            account_scope=recovery._ACCOUNT_SCOPE,
            strategy_scope=recovery._STRATEGY_SCOPE,
            logical_run_id="run-1",
            cohort_id="rb-cohort",
            close_time=active_facts.available_at.isoformat().replace("+00:00", "Z"),
            decision_kind="ALPHA003_RISK_REDUCTION",
        )
        cancel_intent_key = ExecutionIntentKey(
            action="CANCEL",
            instrument=recovery._INSTRUMENT,
            side=side,
            position_effect="OPEN",
            leg=0,
        )
        cancel_economics = {
            "instrument": recovery._INSTRUMENT,
            "exchange": recovery._EXCHANGE,
            "side": side,
            "position_effect": "OPEN",
            "owner_intent_id": submit_intent_id,
            "reason": "AC50-21 ambiguous native cancel recovery",
        }

        native_cancel = api.trader_client.submit_order_action

        def cancel_reaches_native_then_loses_reply(field, request_id, *, execution_capability):
            native_cancel(field, request_id, execution_capability=execution_capability)
            raise TimeoutError("synthetic native cancel response lost")

        api.trader_client.submit_order_action = cancel_reaches_native_then_loses_reply
        with coordinator.risk_decision_scope(
            owner=strategy,
            key=cancel_key,
            economic_payload={"intent_economics": (cancel_economics,)},
            intent_keys=(cancel_intent_key,),
            batch=None,
            execution_facts=active_facts,
            inputs_complete=True,
            expected_run_order_intents_used=coordinator.run_order_count(),
            remaining_exit_intent_reserve=0,
        ) as cancel_decision:
            strategy.cancel(order)

        cancel_intent_id = order.info["factor_cancel_intent_id"]
        cancel_intent = journal.intent(cancel_intent_id)
        owner_after_cancel = journal.active_instrument_owner(
            recovery._ACCOUNT_SCOPE, recovery._INSTRUMENT
        )
        unknown_dispatches = tuple(
            item
            for item in store.registered_sim_dispatch_history()
            if item.operation == "cancel" and item.order_ref == original_order_ref
        )
        assert cancel_decision.decision_id is not None
        assert cancel_intent is not None
        assert cancel_intent.key.action == "CANCEL"
        assert cancel_intent.state == cancel_intent.dispatch_state == "UNKNOWN"
        assert owner_after_cancel is not None
        assert owner_after_cancel.intent_id == submit_intent_id
        assert owner_after_cancel.cancel_intent_id == cancel_intent_id
        assert len(unknown_dispatches) == 1
        assert unknown_dispatches[0].status == "UNKNOWN"
        assert store.registered_sim_status()["frozen"] is True
        assert api.registered_sim_execution_facts()["unknown_ids"] == [original_order_ref]
        assert order.alive()
        assert order.status != Order.Rejected
        assert order.info.get("cancel_rejected_local") is not True
        assert api.native_calls == [
            ("insert", recovery._INSTRUMENT, recovery._EXCHANGE, original_order_ref, 101),
            ("cancel", recovery._INSTRUMENT, recovery._EXCHANGE, original_order_ref, 102),
        ]

        # This is a new complete typed query set. Its sole terminal row names
        # the original native OrderRef; it cannot create or imply a replacement.
        api.query_rows = facts_helpers._query_rows(
            orders=(
                {
                    **recovery._terminal_row(original_order_ref),
                    "Direction": ctp_direction,
                },
            )
        )
        receipt, terminal_facts = recovery._refresh_five_family_facts(
            api, store, broker, target, generation=1, sequence=21
        )
        assert receipt.query_set is not None
        assert receipt.blockers == ()
        assert receipt.pending_families == ()
        assert receipt.query_set.query_set_id != active_receipt.query_set.query_set_id
        assert (
            tuple(family for family, _request_id in receipt.query_set.query_ids)
            == recovery._CORE_FAMILIES
        )
        assert len(terminal_facts.terminal_orders) == 1
        terminal = terminal_facts.terminal_orders[0]
        assert terminal.order_ref == original_order_ref
        assert terminal.terminal_state == "CANCELED"
        assert terminal.front_id == 4 and terminal.session_id == 7
        assert terminal.volume_traded == 0
        assert terminal.volume_total_original == 1
        assert terminal.volume_total == 1

        order_update_queue = _FailOnceOrderUpdateQueue(api._order_updates)
        assert not order_update_queue
        order_update_queue.fail_next_append = True
        api._order_updates = order_update_queue
        failed_retirement_page = coordinator.reconcile_terminal_order_observations(
            terminal_facts,
            refresh_receipt=receipt,
            limit=128,
        )
        failed_retirement = (
            failed_retirement_page.items[0] if len(failed_retirement_page.items) == 1 else None
        )
        assert failed_retirement is not None
        assert failed_retirement.status == "BLOCKED"
        assert failed_retirement.blocker_code == "UNKNOWN_STORE_RETIREMENT_NOT_APPLIED"
        assert store.registered_sim_status()["frozen"] is True
        assert api.registered_sim_execution_facts()["unknown_ids"] == [original_order_ref]
        assert not api._order_updates

        # A new complete query that changes the terminal volume tuple cannot
        # overwrite the durable no-fill proof or retire the UNKNOWN latch.
        changed_terminal_row = {
            **recovery._terminal_row(original_order_ref),
            "Direction": ctp_direction,
            "VolumeTraded": "1",
            "VolumeTotal": "0",
        }
        api.query_rows = facts_helpers._query_rows(orders=(changed_terminal_row,))
        changed_receipt, changed_facts = recovery._refresh_five_family_facts(
            api, store, broker, target, generation=1, sequence=22
        )
        assert changed_receipt.query_set is not None
        assert changed_receipt.blockers == ()
        assert changed_receipt.pending_families == ()
        assert len(changed_facts.terminal_orders) == 1
        changed_page = coordinator.reconcile_terminal_order_observations(
            changed_facts,
            refresh_receipt=changed_receipt,
            limit=128,
        )
        changed_item = changed_page.items[0] if len(changed_page.items) == 1 else None
        assert changed_item is not None
        assert changed_item.status == "BLOCKED"
        assert changed_item.blocker_code == "UNKNOWN_CANCEL_TERMINAL_VOLUME_CONFLICT"
        assert store.registered_sim_status()["frozen"] is True
        assert api.registered_sim_execution_facts()["unknown_ids"] == [original_order_ref]
        assert not api._order_updates

        # The same immutable no-fill volume tuple on a later full query safely
        # retries queue retirement after the transient enqueue failure.
        api.query_rows = facts_helpers._query_rows(
            orders=(
                {
                    **recovery._terminal_row(original_order_ref),
                    "Direction": ctp_direction,
                },
            )
        )
        receipt, terminal_facts = recovery._refresh_five_family_facts(
            api, store, broker, target, generation=1, sequence=23
        )
        assert receipt.query_set is not None
        assert receipt.blockers == ()
        assert receipt.pending_families == ()
        assert receipt.query_set.query_set_id != changed_receipt.query_set.query_set_id
        page = coordinator.reconcile_terminal_order_observations(
            terminal_facts,
            refresh_receipt=receipt,
            limit=128,
        )
        item = page.items[0] if len(page.items) == 1 else None
        assert item is not None and item.status == "RESOLVED"
        assert len(api._order_updates) == 1

        # Replaying the same immutable query proof before the engine drains
        # the queued Store event must not enqueue a second terminal callback.
        replay = coordinator.reconcile_terminal_order_observations(
            terminal_facts,
            refresh_receipt=receipt,
            limit=128,
        )
        assert all(replayed.status != "BLOCKED" for replayed in replay.items)
        assert len(api._order_updates) == 1

        delivered_order_notifications = []
        strategy.notify_order = lambda notified_order: delivered_order_notifications.append(
            (
                notified_order.ref,
                notified_order.getstatusname(),
                notified_order.info.get("factor_intent_id"),
            )
        )
        # This is the ordinary Cerebro broker-notification stage: it calls
        # broker.next(), transfers queued notifications to Strategy, and then
        # Strategy delivers them through its normal notify_order callback.
        cerebro._brokernotify()
        strategy._notify()

        after_owner = journal.active_instrument_owner(recovery._ACCOUNT_SCOPE, recovery._INSTRUMENT)
        current_cancel_intent = journal.intent(cancel_intent_id)
        current_wrapper_facts = api.registered_sim_execution_facts()
        current_store_status = store.registered_sim_status()
        diagnostic = {
            "terminal_item": (
                None if item is None else (item.status, item.blocker_code, item.intent_id)
            ),
            "query_set": (
                receipt.query_set.query_set_id,
                receipt.query_set.connection_generation,
                receipt.query_set.trading_day,
                receipt.query_set.query_ids,
            ),
            "terminal_row": (
                terminal.order_ref,
                terminal.terminal_state,
                terminal.front_id,
                terminal.session_id,
                terminal.volume_total_original,
                terminal.volume_traded,
                terminal.volume_total,
            ),
            "cancel_intent": (
                current_cancel_intent.key.action,
                current_cancel_intent.state,
                current_cancel_intent.dispatch_state,
                current_cancel_intent.provider_identity.get("operation"),
                current_cancel_intent.provider_identity.get("status"),
            ),
            "owner": (
                None
                if after_owner is None
                else (after_owner.intent_id, after_owner.cancel_intent_id, after_owner.state)
            ),
            "store": (current_store_status.get("frozen"), current_store_status.get("reason")),
            "wrapper": (
                current_wrapper_facts.get("frozen"),
                current_wrapper_facts.get("unknown_ids"),
                current_wrapper_facts.get("dispatching_order_ids"),
            ),
            "broker_working_orders": tuple(
                (
                    row.order_ref,
                    row.state,
                    row.execution_unknown,
                    row.cancel_pending,
                    row.owner_intent_id,
                )
                for row in terminal_facts.working_orders
            ),
            "broker_order": (
                order.getstatusname(),
                order.alive(),
                order.info.get("cancel_execution_unknown"),
                order.info.get("cancel_intent_active"),
            ),
            "native_calls": tuple(api.native_calls),
            "delivered_order_notifications": tuple(delivered_order_notifications),
            "failed_retirement": (
                failed_retirement.status,
                failed_retirement.blocker_code,
            ),
            "changed_terminal": (changed_item.status, changed_item.blocker_code),
        }
        assert item is not None and item.status == "RESOLVED", diagnostic
        assert item.intent_id == submit_intent_id
        assert after_owner is None, diagnostic
        assert store.registered_sim_status()["frozen"] is False, diagnostic
        assert api.registered_sim_execution_facts()["unknown_ids"] == [], diagnostic
        assert not order.alive(), diagnostic
        assert order.status == Order.Canceled, diagnostic
        assert order.info.get("cancel_execution_unknown") is False, diagnostic
        canceled_notifications = tuple(
            event
            for event in delivered_order_notifications
            if event[0] == order.ref and event[1] == "Canceled"
        )
        assert canceled_notifications == ((order.ref, "Canceled", submit_intent_id),), diagnostic
        assert api.native_calls == [
            ("insert", recovery._INSTRUMENT, recovery._EXCHANGE, original_order_ref, 101),
            ("cancel", recovery._INSTRUMENT, recovery._EXCHANGE, original_order_ref, 102),
        ], "recovery must neither create a new OrderRef nor resend the native CANCEL"
        resolved_cancel_intent = journal.intent(cancel_intent_id)
        assert resolved_cancel_intent is not None
        assert resolved_cancel_intent.state != "UNKNOWN"
        assert resolved_cancel_intent.dispatch_state == "UNKNOWN"
    finally:
        journal.close()
