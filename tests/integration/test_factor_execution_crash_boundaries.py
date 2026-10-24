"""Spawned crash-boundary checks for durable factor execution.

Each source worker is a test-owned spawned process. It calls ``os._exit`` only
after a selected SQLite/API boundary, so Python cleanup cannot hide whether
the last durable state survived. Recovery workers use the real journal,
coordinator, Store and Broker with the existing fake SDK leaves. A DISPATCHING
row with no complete terminal query remains unresolved. The positive SUBMIT
no-fill recovery below uses a new complete query after the original
dispatcher has exited; this file does not manufacture UNKNOWN.
"""

from __future__ import annotations

import json
import multiprocessing
import os
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

import pytest

from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionKey,
    ExecutionIntentKey,
)
from backtrader.stores.factor_execution import (
    FactorExecutionDecisionScope,
    FactorExecutionError,
)
from tests.integration import test_factor_execution_unknown_recovery as recovery_helpers
from tests.unit.stores import test_factor_execution_facts as facts_helpers


_EXIT_CODES = {
    "decision_commit": 71,
    "prepared_commit": 72,
    "claim_commit": 73,
    "native_request_no_response": 74,
    "native_ack_before_result": 75,
    "dispatch_result_commit": 76,
    "callback_before_receipt": 81,
    "callback_after_projection": 82,
    "callback_after_broker_apply": 83,
    "callback_after_ack": 84,
    "live_dispatching_submit_crash": 85,
    "cancel_dispatching_crash": 86,
}

_INCOMPLETE_DISPATCHING_WITHOUT_TERMINAL_PROOF = (
    "INCOMPLETE_RECOVERY_WITHOUT_TERMINAL_PROOF:DISPATCHING_REMAINS_UNRESOLVED"
)
_INCOMPLETE_CALLBACK_RECOVERY = (
    "INCOMPLETE_CALLBACK_RECOVERY:EXACT_NATIVE_RECEIPT_REQUIRES_SUPPORTED_RECONCILIATION"
)


def _write_checkpoint(path, payload):
    """Persist a small synthetic boundary receipt before the intentional exit."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    with open(path, "xb") as output:
        output.write(encoded)
        output.flush()
        os.fsync(output.fileno())


def _crash(path, boundary, payload):
    _write_checkpoint(path, {"boundary": boundary, **payload})
    os._exit(_EXIT_CODES[boundary])


def _submit_in_scope(scope, owner, data):
    with scope:
        return owner.buy(
            data=data,
            size=1,
            price=100,
            exectype=recovery_helpers.Order.Limit,
            instrument_id=recovery_helpers._INSTRUMENT,
            exchange_id=recovery_helpers._EXCHANGE,
            factor_position_effect="OPEN",
            factor_strategy_scope=recovery_helpers._STRATEGY_SCOPE,
            offset="open",
        )


def _source_dispatch_crash_worker(journal_path, checkpoint_path, boundary):
    """Run the ordinary Strategy/Broker route and exit at one durable point."""

    now = datetime.now(timezone.utc)
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        target,
        data,
        owner,
        _cerebro,
    ) = recovery_helpers._durable_system(journal_path, now=now)
    facts = recovery_helpers._initial_open_facts(api, store, broker, target, now=now)
    close_time = facts.available_at - timedelta(milliseconds=2)
    batch_id = "crash-boundary-" + boundary
    scope, _intent_key, _economics = recovery_helpers._decision_scope(
        coordinator,
        owner,
        facts,
        close_time=close_time,
        batch_id=batch_id,
    )
    grid_identity = {
        "close_time": scope.key.close_time,
        "batch_id": batch_id,
        "cohort_id": scope.key.cohort_id,
        "native_calls_at_worker_start": len(api.native_calls),
    }

    if boundary == "decision_commit":
        original = journal.record_grid_decision

        def commit_then_crash(*args, **kwargs):
            original(*args, **kwargs)
            assert api.native_calls == []
            _crash(
                checkpoint_path,
                boundary,
                grid_identity,
            )

        journal.record_grid_decision = commit_then_crash
    elif boundary == "prepared_commit":
        original = journal.prepare_intent

        def prepare_then_crash(*args, **kwargs):
            original(*args, **kwargs)
            assert api.native_calls == []
            _crash(
                checkpoint_path,
                boundary,
                grid_identity,
            )

        journal.prepare_intent = prepare_then_crash
    elif boundary == "claim_commit":
        original = journal.claim_dispatch

        def claim_then_crash(intent_id):
            result = original(intent_id)
            assert result is not None
            assert api.native_calls == []
            _crash(
                checkpoint_path,
                boundary,
                grid_identity,
            )

        journal.claim_dispatch = claim_then_crash
    elif boundary == "native_request_no_response":

        def request_then_crash(field, request_id, *, execution_capability):
            assert execution_capability is not None
            _crash(
                checkpoint_path,
                boundary,
                {
                    **grid_identity,
                    "native_request_count": 1,
                    "native_response_observed": False,
                    "request_id": request_id,
                    "instrument_id": field.InstrumentID,
                    "exchange_id": field.ExchangeID,
                    "order_ref": field.OrderRef,
                },
            )

        api.trader_client.submit_order_insert = request_then_crash
    elif boundary == "native_ack_before_result":
        native_insert = api.trader_client.submit_order_insert

        def acknowledge_and_return(field, request_id, *, execution_capability):
            result = native_insert(
                field,
                request_id,
                execution_capability=execution_capability,
            )
            _write_checkpoint(
                checkpoint_path,
                {
                    "boundary": boundary,
                    **grid_identity,
                    "native_request_count": 1,
                    "native_response_observed": True,
                    "native_return_code": result,
                    "request_id": request_id,
                    "instrument_id": field.InstrumentID,
                    "exchange_id": field.ExchangeID,
                    "order_ref": field.OrderRef,
                },
            )
            return result

        api.trader_client.submit_order_insert = acknowledge_and_return

        def crash_before_result(_scope, _order, _attempt, *, response=None, error=None):
            del response, error
            os._exit(_EXIT_CODES[boundary])

        FactorExecutionDecisionScope.complete_order = crash_before_result
    elif boundary == "dispatch_result_commit":
        original = journal.record_dispatch_result

        def result_then_crash(*args, **kwargs):
            intent = original(*args, **kwargs)
            _crash(
                checkpoint_path,
                boundary,
                {
                    **grid_identity,
                    "dispatch_result_state": intent.state,
                    "native_return_code": (intent.provider_identity or {}).get(
                        "native_return_code"
                    ),
                },
            )

        journal.record_dispatch_result = result_then_crash
    else:
        raise AssertionError("unknown dispatch crash boundary")

    _submit_in_scope(scope, owner, data)
    raise AssertionError("selected crash boundary was not reached")


def _read_intent_rows(journal):
    return tuple(journal.execution_intent_snapshot(limit=16).items)


def _child_reopen_and_replay_decision(journal_path, checkpoint, result_queue):
    """Reopen a crash image, replay only its immutable decision, and never send."""

    now = datetime.now(timezone.utc)
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        target,
        _data,
        _owner,
        _cerebro,
    ) = recovery_helpers._durable_system(journal_path, now=now)
    try:
        cursor_before = journal.grid_cursor(
            recovery_helpers._ACCOUNT_SCOPE,
            recovery_helpers._STRATEGY_SCOPE,
            checkpoint["cohort_id"],
        )
        assert cursor_before is not None
        assert cursor_before.batch_id == checkpoint["batch_id"]
        assert cursor_before.close_time == checkpoint["close_time"]
        decision = journal.decision(cursor_before.decision_id)
        assert decision is not None

        # Re-recording the exact immutable old grid is the public journal
        # replay path. It must return is_new_grid=False and leave the cursor.
        replay_economics = dict(decision.economic_payload)
        replay_economics.pop("_journal_run_order_reservation", None)
        replay = journal.record_grid_decision(
            decision.key,
            replay_economics,
            intent_keys=decision.intent_keys,
            epoch_id=cursor_before.epoch_id,
            batch_id=cursor_before.batch_id,
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
            max_order_intents_per_run=coordinator.max_order_intents_per_run,
            expected_run_order_intents_used=coordinator.run_order_count(),
            remaining_exit_intent_reserve=0,
        )
        assert replay.is_new_grid is False
        assert replay.decision.decision_id == decision.decision_id
        assert replay.decision.economic_payload == decision.economic_payload
        assert replay.decision.intent_keys == decision.intent_keys

        rows = _read_intent_rows(journal)
        if checkpoint["boundary"] == "decision_commit":
            assert rows == ()
            owner = None
            intent = None
        else:
            assert len(rows) == 1
            intent = rows[0]
            owner = journal.active_instrument_owner(
                recovery_helpers._ACCOUNT_SCOPE,
                recovery_helpers._INSTRUMENT,
            )
            assert owner is not None and owner.intent_id == intent.intent_id
            assert owner.state == intent.state

        # The fresh Store has no old in-memory API request history and this
        # replay worker never calls Strategy.buy/sell or a native leaf.
        assert api.native_calls == []
        result_queue.put(
            {
                "status": "OK",
                "decision_replayed": True,
                "is_new_grid": replay.is_new_grid,
                "intent_state": None if intent is None else intent.state,
                "dispatch_state": None if intent is None else intent.dispatch_state,
                "original_order_ref": (
                    None if intent is None else intent.original_identity.get("order_ref")
                ),
                "owner_retained": owner is not None,
                "native_calls": len(api.native_calls),
                "old_order_rebuilt": bool(broker.orders),
                "recovery_state": (
                    _INCOMPLETE_DISPATCHING_WITHOUT_TERMINAL_PROOF
                    if intent is not None and intent.state == "DISPATCHING"
                    else "NO_DISPATCHING_POSITIVE_RECOVERY_REQUIRED"
                ),
            }
        )
    except BaseException as error:
        result_queue.put(
            {
                "status": "ERROR",
                "error_type": type(error).__name__,
                "error_code": getattr(error, "code", None),
                "error_message": str(error)[:240],
            }
        )
    finally:
        journal.close()


def _spawn_exit(context, *, target, args, expected_code, timeout=45):
    process = context.Process(target=target, args=args)
    process.start()
    process.join(timeout=timeout)
    if process.is_alive():
        # This terminates only the fresh child created by this test.
        process.terminate()
        process.join(timeout=5)
        pytest.fail("test-owned spawned crash worker exceeded its bound")
    assert process.exitcode == expected_code


def _spawn_result(context, *, target, args, timeout=45):
    result_queue = context.Queue()
    process = context.Process(target=target, args=(*args, result_queue))
    process.start()
    process.join(timeout=timeout)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        result_queue.close()
        result_queue.join_thread()
        pytest.fail("test-owned spawned recovery worker exceeded its bound")
    assert process.exitcode == 0
    result = result_queue.get(timeout=3)
    result_queue.close()
    result_queue.join_thread()
    assert result["status"] == "OK", result
    return result


@pytest.mark.parametrize(
    "boundary,expected_state,expected_dispatch_state",
    (
        ("decision_commit", None, None),
        ("prepared_commit", "PREPARED", None),
        ("claim_commit", "DISPATCHING", None),
        ("native_request_no_response", "DISPATCHING", None),
        ("native_ack_before_result", "DISPATCHING", None),
        ("dispatch_result_commit", "KNOWN", "KNOWN"),
    ),
    ids=("decision", "prepared-ref", "claimed-ref", "rpc-no-response", "sdk-ack", "known"),
)
def test_spawned_dispatch_crash_preserves_grid_identity_and_never_replays_native(
    tmp_path,
    boundary,
    expected_state,
    expected_dispatch_state,
):
    """A restart keeps the old decision/OrderRef and never redispatches it."""

    journal_path = tmp_path / (boundary + ".sqlite3")
    checkpoint_path = tmp_path / (boundary + ".json")
    context = multiprocessing.get_context("spawn")
    _spawn_exit(
        context,
        target=_source_dispatch_crash_worker,
        args=(str(journal_path), str(checkpoint_path), boundary),
        expected_code=_EXIT_CODES[boundary],
    )

    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["boundary"] == boundary
    assert checkpoint["native_calls_at_worker_start"] == 0
    journal = ExecutionDecisionJournal(journal_path)
    try:
        cursor = journal.grid_cursor(
            recovery_helpers._ACCOUNT_SCOPE,
            recovery_helpers._STRATEGY_SCOPE,
            checkpoint["cohort_id"],
        )
        assert cursor is not None and cursor.batch_id == checkpoint["batch_id"]
        decision = journal.decision(cursor.decision_id)
        assert decision is not None
        assert decision.key.close_time == checkpoint["close_time"]
        assert decision.economic_payload["intent_economics"][0]["instrument"] == (
            recovery_helpers._INSTRUMENT
        )
        assert decision.intent_keys[0].action == "SUBMIT"
        assert decision.intent_keys[0].instrument == recovery_helpers._INSTRUMENT
        assert cursor.close_time == checkpoint["close_time"]

        intent_id = None
        original_order_ref = None
        if expected_state is None:
            assert _read_intent_rows(journal) == ()
            assert (
                journal.active_instrument_owner(
                    recovery_helpers._ACCOUNT_SCOPE,
                    recovery_helpers._INSTRUMENT,
                )
                is None
            )
        else:
            rows = _read_intent_rows(journal)
            assert len(rows) == 1
            intent = rows[0]
            intent_id = intent.intent_id
            assert intent.state == expected_state
            assert intent.dispatch_state == expected_dispatch_state
            original_order_ref = intent.original_identity["order_ref"]
            assert original_order_ref.isdecimal() and int(original_order_ref) > 0
            assert intent.original_identity["trading_day"] == recovery_helpers._TRADING_DAY
            assert intent.original_identity["instrument_id"] == recovery_helpers._INSTRUMENT
            assert intent.original_identity["exchange_id"] == recovery_helpers._EXCHANGE
            assert intent.economic_payload == decision.economic_payload["intent_economics"][0]
            owner = journal.active_instrument_owner(
                recovery_helpers._ACCOUNT_SCOPE,
                recovery_helpers._INSTRUMENT,
            )
            assert owner is not None and owner.intent_id == intent_id
            assert owner.state == expected_state
            if expected_state in ("DISPATCHING", "KNOWN"):
                assert journal.claim_dispatch(intent_id) is None
        if boundary == "native_request_no_response":
            assert checkpoint["native_request_count"] == 1
            assert checkpoint["native_response_observed"] is False
            assert checkpoint["order_ref"] == intent.original_identity["order_ref"]
        elif boundary in ("native_ack_before_result", "dispatch_result_commit"):
            if boundary == "native_ack_before_result":
                assert checkpoint["native_request_count"] == 1
                assert checkpoint["native_response_observed"] is True
                assert checkpoint["native_return_code"] == 0
            else:
                assert checkpoint["dispatch_result_state"] == "KNOWN"
                assert checkpoint["native_return_code"] == 0
    finally:
        journal.close()

    recovered = _spawn_result(
        context,
        target=_child_reopen_and_replay_decision,
        args=(str(journal_path), checkpoint),
    )
    assert recovered["decision_replayed"] is True
    assert recovered["is_new_grid"] is False
    assert recovered["native_calls"] == 0
    assert recovered["old_order_rebuilt"] is False
    assert recovered["intent_state"] == expected_state
    assert recovered["dispatch_state"] == expected_dispatch_state
    assert recovered["original_order_ref"] == original_order_ref
    assert recovered["owner_retained"] is (expected_state is not None)
    if expected_state == "DISPATCHING":
        # This is a safety characterization, not positive recovery acceptance.
        assert recovered["recovery_state"] == _INCOMPLETE_DISPATCHING_WITHOUT_TERMINAL_PROOF


def _callback_rows(journal, intent_id):
    with journal._read_lock():
        rows = journal._connection.execute(
            """SELECT receipt_id, callback_id, acknowledged, evidence_payload_json
               FROM execution_decision_callbacks WHERE intent_id=?
               ORDER BY created_at_ns, receipt_id""",
            (intent_id,),
        ).fetchall()
    return tuple(
        {
            "receipt_id": row["receipt_id"],
            "callback_id": row["callback_id"],
            "acknowledged": bool(row["acknowledged"]),
            "evidence": json.loads(row["evidence_payload_json"]),
        }
        for row in rows
    )


def _callback_process_instance_id(journal, receipt_id):
    with journal._read_lock():
        row = journal._connection.execute(
            "SELECT process_instance_id FROM execution_decision_callbacks WHERE receipt_id=?",
            (receipt_id,),
        ).fetchone()
    assert row is not None and isinstance(row["process_instance_id"], str)
    return row["process_instance_id"]


def _source_callback_crash_worker(journal_path, checkpoint_path, boundary):
    """Submit one fake order, then crash at a selected Broker callback step."""

    # Keep the test's wall-clock fixture inside the fake provider's fixed
    # trading day so the projected fill follows its decision grid.
    now = datetime(2026, 10, 24, 1, 0, 10, tzinfo=timezone.utc)
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        target,
        data,
        owner,
        _cerebro,
    ) = recovery_helpers._durable_system(journal_path, now=now)
    facts = recovery_helpers._initial_open_facts(api, store, broker, target, now=now)
    close_time = facts.available_at - timedelta(milliseconds=2)
    batch_id = "crash-boundary-callback"
    scope, _intent_key, _economics = recovery_helpers._decision_scope(
        coordinator,
        owner,
        facts,
        close_time=close_time,
        batch_id=batch_id,
    )
    order = _submit_in_scope(scope, owner, data)
    assert order is not None and order.info["factor_dispatch_state"] == "KNOWN"
    intent_id = order.info["factor_intent_id"]
    intent = journal.intent(intent_id)
    assert intent is not None and intent.dispatch_state == "KNOWN"
    order_ref = intent.original_identity["order_ref"]
    trade_time = (now + timedelta(seconds=5)).astimezone(timezone(timedelta(hours=8)))
    api.emit_provider_trade_callback(
        order_ref,
        trade_id="crash-boundary-trade-1",
        quantity=1,
        offset="open",
        when=trade_time,
        omit_trade_date=False,
    )

    common = {
        "decision_id": intent.decision_id,
        "intent_id": intent_id,
        "order_ref": order_ref,
        "trading_day": intent.original_identity["trading_day"],
        "instrument_id": intent.original_identity["instrument_id"],
        "exchange_id": intent.original_identity["exchange_id"],
        "native_requests_before_callback": len(api.native_calls),
        "source_callback_receipt": None,
        "trade_id": "crash-boundary-trade-1",
        "trade_date": trade_time.strftime("%Y%m%d"),
        "trade_time": trade_time.strftime("%H:%M:%S"),
    }
    if boundary == "callback_before_receipt":

        def crash_before_record(_update, _order):
            _crash(
                checkpoint_path,
                boundary,
                {
                    **common,
                    "callback_rows_before_recovery": _callback_rows(journal, intent_id),
                },
            )

        coordinator.record_trade_callback = crash_before_record
    elif boundary == "callback_after_projection":
        original = journal.record_callback_projected

        def project_then_crash(*args, **kwargs):
            receipt, projection = original(*args, **kwargs)
            callback_rows = _callback_rows(journal, intent_id)
            assert len(callback_rows) == 1
            assert callback_rows[0]["receipt_id"] == receipt.receipt_id
            assert callback_rows[0]["callback_id"] == receipt.callback_id
            _crash(
                checkpoint_path,
                boundary,
                {
                    **common,
                    "source_callback_receipt": callback_rows[0],
                    "source_process_instance_id": _callback_process_instance_id(
                        journal, receipt.receipt_id
                    ),
                    "callback_rows_before_recovery": callback_rows,
                    "receipt_id": receipt.receipt_id,
                    "receipt_acknowledged": receipt.acknowledged,
                    "projection_status": getattr(projection, "status", None),
                    "broker_position_before_apply": broker.getposition(data).size,
                    "order_executed_before_apply": order.executed.size,
                },
            )

        journal.record_callback_projected = project_then_crash
    elif boundary in ("callback_after_broker_apply", "callback_after_ack"):
        original = journal.acknowledge_callback

        def crash_at_ack(receipt_id):
            callback_rows = _callback_rows(journal, intent_id)
            assert len(callback_rows) == 1
            assert callback_rows[0]["receipt_id"] == receipt_id
            if boundary == "callback_after_ack":
                original(receipt_id)
                callback_rows = _callback_rows(journal, intent_id)
            _crash(
                checkpoint_path,
                boundary,
                {
                    **common,
                    "source_callback_receipt": callback_rows[0],
                    "callback_rows_before_recovery": callback_rows,
                    "receipt_id": receipt_id,
                    "ack_returned": boundary == "callback_after_ack",
                    "broker_position_before_ack": broker.getposition(data).size,
                    "order_executed_before_ack": order.executed.size,
                },
            )

        journal.acknowledge_callback = crash_at_ack
    else:
        raise AssertionError("unknown callback crash boundary")

    broker._drain_store_updates()
    raise AssertionError("selected callback crash boundary was not reached")


def _trade_query_row(checkpoint):
    return {
        "TradeID": checkpoint["trade_id"],
        "OrderRef": checkpoint["order_ref"],
        "OrderSysID": "",
        "InstrumentID": checkpoint["instrument_id"],
        "ExchangeID": checkpoint["exchange_id"],
        "Direction": "0",
        "OffsetFlag": "0",
        "HedgeFlag": "1",
        "Volume": "1",
        "Price": "100",
        "TradeDate": checkpoint["trade_date"],
        "TradeTime": checkpoint["trade_time"],
        "TradingDay": checkpoint["trading_day"],
    }


def _child_reconcile_trade_after_callback_crash(journal_path, checkpoint, result_queue):
    """Read a fresh complete query and project its trade without old Orders."""

    now = datetime.now(timezone.utc)
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        target,
        _data,
        _owner,
        _cerebro,
    ) = recovery_helpers._durable_system(journal_path, now=now)
    try:
        order_row = {
            "OrderRef": checkpoint["order_ref"],
            "OrderSysID": "",
            "InstrumentID": checkpoint["instrument_id"],
            "ExchangeID": checkpoint["exchange_id"],
            "OrderStatus": "0",
            "Direction": "0",
            "CombOffsetFlag": "0",
            "VolumeTotalOriginal": "1",
            "VolumeTraded": "1",
            "VolumeTotal": "0",
            "FrontID": 4,
            "SessionID": 7,
            "TradingDay": checkpoint["trading_day"],
        }
        position_row = facts_helpers._dated_position_row(
            "1",
            position_date="TODAY",
            side="LONG",
            trading_day=checkpoint["trading_day"],
        )
        api.query_rows = facts_helpers._query_rows(
            positions=(position_row,),
            orders=(order_row,),
            trades=(_trade_query_row(checkpoint),),
        )
        recovery_helpers._bind_current_session_identity(
            api,
            generation=2,
            front_id=5,
            session_id=8,
        )
        receipt, facts = recovery_helpers._refresh_five_family_facts(
            api,
            store,
            broker,
            target,
            generation=2,
            sequence=22,
        )
        assert receipt.query_set.connection_generation == 2
        assert not broker.orders, "recovery must not rebuild a historical Backtrader Order"

        callback_rows_before_recovery = _callback_rows(journal, checkpoint["intent_id"])
        with journal._read_lock():
            fill_count_before_recovery = int(
                journal._connection.execute(
                    "SELECT COUNT(*) FROM factor_position_fills WHERE intent_id=?",
                    (checkpoint["intent_id"],),
                ).fetchone()[0]
            )

        page = coordinator.reconcile_trade_observations(facts, limit=16)
        assert page.truncated is False
        assert page.observation_count == 1
        item = page.items[0]
        callback_rows_after_first_reconcile = _callback_rows(journal, checkpoint["intent_id"])
        with journal._read_lock():
            fill_count_after_first_reconcile = int(
                journal._connection.execute(
                    "SELECT COUNT(*) FROM factor_position_fills WHERE intent_id=?",
                    (checkpoint["intent_id"],),
                ).fetchone()[0]
            )

        # Replaying the same immutable query is the idempotency check. A
        # projected fill stays singular; an exact native callback conflict
        # remains a blocker until production supports joining that receipt.
        repeated_page = coordinator.reconcile_trade_observations(facts, limit=16)
        assert repeated_page.truncated is False
        assert repeated_page.observation_count == 1
        repeated_item = repeated_page.items[0]
        callback_rows_after_replay = _callback_rows(journal, checkpoint["intent_id"])
        with journal._read_lock():
            fill_count = int(
                journal._connection.execute(
                    "SELECT COUNT(*) FROM factor_position_fills WHERE intent_id=?",
                    (checkpoint["intent_id"],),
                ).fetchone()[0]
            )
        pending = journal.pending_callbacks(limit=16)
        pending_ids = tuple(
            row.callback_id for row in pending if row.intent_id == checkpoint["intent_id"]
        )
        if item.status in ("APPLIED", "DUPLICATE") and fill_count == 1:
            assert repeated_item.status in ("APPLIED", "DUPLICATE")
            recovery_state = (
                "QUERY_PROJECTION_RECOVERED_WITHOUT_ORDER_REBUILD"
                if not pending_ids
                else _INCOMPLETE_CALLBACK_RECOVERY
            )
        elif (
            item.status == "BLOCKED"
            and item.blocker_code == "NATIVE_TRADE_CALLBACK_QUERY_CONFLICT"
            and fill_count == 1
        ):
            assert repeated_item.status == "BLOCKED"
            assert repeated_item.blocker_code == "NATIVE_TRADE_CALLBACK_QUERY_CONFLICT"
            recovery_state = _INCOMPLETE_CALLBACK_RECOVERY
        else:
            raise AssertionError(
                "callback recovery produced an unclassified state: {!r}, fills={}, pending={}".format(
                    item, fill_count, pending_ids
                )
            )

        with journal._read_lock():
            fill_count_after_replay = int(
                journal._connection.execute(
                    "SELECT COUNT(*) FROM factor_position_fills WHERE intent_id=?",
                    (checkpoint["intent_id"],),
                ).fetchone()[0]
            )
        result_queue.put(
            {
                "status": "OK",
                "item_status": item.status,
                "blocker_code": item.blocker_code,
                "repeated_item_status": repeated_item.status,
                "repeated_blocker_code": repeated_item.blocker_code,
                "fill_count": fill_count,
                "fill_count_before_recovery": fill_count_before_recovery,
                "fill_count_after_first_reconcile": fill_count_after_first_reconcile,
                "fill_count_after_replay": fill_count_after_replay,
                "callback_rows_before_recovery": callback_rows_before_recovery,
                "callback_rows_after_first_reconcile": callback_rows_after_first_reconcile,
                "callback_rows_after_replay": callback_rows_after_replay,
                "pending_native_callback_ids": pending_ids,
                "fresh_broker_orders": len(broker.orders),
                "owner_retained": journal.active_instrument_owner(
                    recovery_helpers._ACCOUNT_SCOPE,
                    checkpoint["instrument_id"],
                )
                is not None,
                "recovery_state": recovery_state,
            }
        )
    except BaseException as error:
        result_queue.put(
            {
                "status": "ERROR",
                "error_type": type(error).__name__,
                "error_code": getattr(error, "code", None),
                "error_message": str(error)[:240],
            }
        )
    finally:
        journal.close()


@pytest.mark.parametrize(
    "boundary,expected_callback_count,expected_pending,expected_broker_size",
    (
        ("callback_before_receipt", 0, 0, None),
        ("callback_after_projection", 1, 1, 0),
        ("callback_after_broker_apply", 1, 1, 1),
        ("callback_after_ack", 1, 0, 1),
    ),
    ids=("before-receipt", "after-projection", "broker-applied-before-ack", "after-ack"),
)
def test_spawned_callback_crash_keeps_projection_idempotent_and_marks_recovery_limit(
    tmp_path,
    boundary,
    expected_callback_count,
    expected_pending,
    expected_broker_size,
):
    """Recover query facts after a crash without rebuilding a historical Order."""

    journal_path = tmp_path / (boundary + ".sqlite3")
    checkpoint_path = tmp_path / (boundary + ".json")
    context = multiprocessing.get_context("spawn")
    _spawn_exit(
        context,
        target=_source_callback_crash_worker,
        args=(str(journal_path), str(checkpoint_path), boundary),
        expected_code=_EXIT_CODES[boundary],
    )
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["boundary"] == boundary
    assert checkpoint["native_requests_before_callback"] == 1

    journal = ExecutionDecisionJournal(journal_path)
    try:
        intent = journal.intent(checkpoint["intent_id"])
        assert intent is not None
        assert intent.state == "KNOWN" and intent.dispatch_state == "KNOWN"
        assert intent.original_identity["order_ref"] == checkpoint["order_ref"]
        assert intent.original_identity["trading_day"] == checkpoint["trading_day"]
        assert intent.original_identity["instrument_id"] == checkpoint["instrument_id"]
        assert intent.original_identity["exchange_id"] == checkpoint["exchange_id"]
        rows = _callback_rows(journal, intent.intent_id)
        assert len(rows) == expected_callback_count
        assert rows == tuple(checkpoint["callback_rows_before_recovery"])
        assert sum(not row["acknowledged"] for row in rows) == expected_pending
        fill_count = int(
            journal._connection.execute(
                "SELECT COUNT(*) FROM factor_position_fills WHERE intent_id=?",
                (intent.intent_id,),
            ).fetchone()[0]
        )
        if boundary == "callback_before_receipt":
            assert fill_count == 0
        else:
            assert fill_count == 1
        if boundary in ("callback_after_projection", "callback_after_broker_apply"):
            assert rows[0]["evidence"]["event_type"] == "execution_fill"
            assert rows[0]["acknowledged"] is False
        if boundary == "callback_after_projection":
            assert checkpoint["projection_status"] == "APPLIED"
            assert checkpoint["broker_position_before_apply"] == 0
            assert checkpoint["order_executed_before_apply"] == 0
        if boundary in ("callback_after_broker_apply", "callback_after_ack"):
            assert checkpoint["broker_position_before_ack"] == expected_broker_size
            assert checkpoint["order_executed_before_ack"] == expected_broker_size
        if boundary == "callback_after_ack":
            assert checkpoint["ack_returned"] is True
            assert rows[0]["acknowledged"] is True
    finally:
        journal.close()

    recovered = _spawn_result(
        context,
        target=_child_reconcile_trade_after_callback_crash,
        args=(str(journal_path), checkpoint),
    )
    assert recovered["fill_count"] == 1
    assert recovered["callback_rows_before_recovery"] == tuple(
        checkpoint["callback_rows_before_recovery"]
    )
    assert recovered["fill_count_before_recovery"] == expected_callback_count
    assert recovered["fill_count_after_first_reconcile"] == 1
    assert recovered["fill_count_after_replay"] == 1
    after_first = recovered["callback_rows_after_first_reconcile"]
    after_replay = recovered["callback_rows_after_replay"]
    assert after_replay == after_first, "replaying one query must not add a duplicate receipt"
    assert len({row["receipt_id"] for row in after_replay}) == len(after_replay)
    source_receipt = checkpoint["source_callback_receipt"]
    if expected_callback_count == 0:
        assert source_receipt is None
        assert recovered["callback_rows_before_recovery"] == ()
        assert len(after_first) == 1
        query_row = after_first[0]
        assert query_row["callback_id"].startswith("query-trade:")
        assert query_row["evidence"].get("query_observation_id")
        assert query_row["evidence"].get("evidence_kind") != "native_trade_callback"
    else:
        assert source_receipt is not None
        assert source_receipt["callback_id"].startswith("ctp-trade:")
        assert source_receipt["evidence"].get("evidence_kind") == "native_trade_callback"
        original_matches = [
            row
            for row in recovered["callback_rows_before_recovery"]
            if row["receipt_id"] == source_receipt["receipt_id"]
        ]
        assert original_matches == [source_receipt]
        after_first_matches = [
            row for row in after_first if row["receipt_id"] == source_receipt["receipt_id"]
        ]
        after_replay_matches = [
            row for row in after_replay if row["receipt_id"] == source_receipt["receipt_id"]
        ]
        assert after_first_matches == [source_receipt]
        assert after_replay_matches == [source_receipt]
        query_rows = [row for row in after_first if row["callback_id"].startswith("query-trade:")]
        assert len(query_rows) == 1
        assert query_rows[0]["evidence"].get("evidence_kind") != "native_trade_callback"
    assert recovered["fresh_broker_orders"] == 0
    assert recovered["owner_retained"] is True
    if boundary == "callback_before_receipt":
        assert recovered["item_status"] == "APPLIED"
        assert recovered["recovery_state"] == "QUERY_PROJECTION_RECOVERED_WITHOUT_ORDER_REBUILD"
    elif recovered["blocker_code"] == "NATIVE_TRADE_CALLBACK_QUERY_CONFLICT":
        # A valid-date native callback has already created the exact native
        # receipt. Current query reconciliation does not join that receipt to
        # the complete-query observation, so it leaves the owner unresolved.
        assert recovered["item_status"] == "BLOCKED"
        assert recovered["recovery_state"] == _INCOMPLETE_CALLBACK_RECOVERY
    elif expected_pending:
        # A crash before Broker ACK retains the exact durable native receipt.
        # Query projection cannot acknowledge that original callback on this
        # recovery path, so the owner remains held with an explicit blocker.
        assert recovered["item_status"] in ("APPLIED", "DUPLICATE")
        assert recovered["pending_native_callback_ids"] == (source_receipt["callback_id"],)
        assert recovered["recovery_state"] == _INCOMPLETE_CALLBACK_RECOVERY
    else:
        # An already-acknowledged native callback plus the exact query replay
        # keeps one fill and does not manufacture another callback receipt.
        assert recovered["item_status"] in ("APPLIED", "DUPLICATE")
        assert recovered["pending_native_callback_ids"] == ()
        assert recovered["recovery_state"] == "QUERY_PROJECTION_RECOVERED_WITHOUT_ORDER_REBUILD"


def _callback_fill_count(journal, intent_id):
    with journal._read_lock():
        return int(
            journal._connection.execute(
                "SELECT COUNT(*) FROM factor_position_fills WHERE intent_id=?",
                (intent_id,),
            ).fetchone()[0]
        )


def _callback_proof_json(value):
    """Canonicalize frozen journal proof values for a spawned-process receipt."""

    return json.dumps(_callback_proof_value(value), sort_keys=True, separators=(",", ":"))


def _callback_proof_value(value):
    if isinstance(value, Mapping):
        return {key: _callback_proof_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_callback_proof_value(item) for item in value]
    return value


def _callback_query_rows(api, checkpoint, *, trade_price="100"):
    order_row = {
        "OrderRef": checkpoint["order_ref"],
        "OrderSysID": "",
        "InstrumentID": checkpoint["instrument_id"],
        "ExchangeID": checkpoint["exchange_id"],
        "OrderStatus": "0",
        "Direction": "0",
        "CombOffsetFlag": "0",
        "VolumeTotalOriginal": "1",
        "VolumeTraded": "1",
        "VolumeTotal": "0",
        "FrontID": 4,
        "SessionID": 7,
        "TradingDay": checkpoint["trading_day"],
    }
    position_row = facts_helpers._dated_position_row(
        "1",
        position_date="TODAY",
        side="LONG",
        trading_day=checkpoint["trading_day"],
    )
    trade_row = _trade_query_row(checkpoint)
    trade_row["Price"] = trade_price
    api.query_rows = facts_helpers._query_rows(
        positions=(position_row,),
        orders=(order_row,),
        trades=(trade_row,),
    )
    recovery_helpers._bind_current_session_identity(
        api,
        generation=2,
        front_id=5,
        session_id=8,
    )


def _spawned_reconcile_native_callback_query_disposition(
    journal_path, checkpoint, proof_case, result_queue
):
    """Match one persisted native fill to a genuinely completed source query."""

    now = datetime.now(timezone.utc)
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        target,
        _data,
        _owner,
        _cerebro,
    ) = recovery_helpers._durable_system(journal_path, now=now)
    stage = "setup_query"
    try:
        _callback_query_rows(
            api,
            checkpoint,
            trade_price="101" if proof_case == "mismatch" else "100",
        )
        native = journal.callback_receipt(
            checkpoint["intent_id"], checkpoint["source_callback_receipt"]["callback_id"]
        )
        assert native is not None and native.acknowledged is False
        assert dict(native.evidence_payload) == checkpoint["source_callback_receipt"]["evidence"]
        assert not broker.orders, "recovery must not rebuild the original Backtrader Order"

        stage = "fresh_five_family_query"
        complete_receipt, facts = recovery_helpers._refresh_five_family_facts(
            api,
            store,
            broker,
            target,
            generation=2,
            sequence=22,
        )
        receipt = complete_receipt
        if proof_case == "incomplete":
            # This is a real second refresh, bounded before its fifth core
            # family. Keep the complete facts separate so the test proves that
            # a later incomplete receipt cannot stand in for their source set.
            receipt, _partial_facts = recovery_helpers._refresh_five_family_facts(
                api,
                store,
                broker,
                target,
                generation=2,
                sequence=23,
                max_queries=4,
            )
            assert receipt.query_set is None
            assert receipt.pending_families or receipt.blockers
        else:
            assert receipt.query_set is not None
            assert receipt.blockers == ()
            assert receipt.pending_families == ()
            assert receipt.requested_families == recovery_helpers._CORE_FAMILIES
            assert receipt.attempted_families == recovery_helpers._CORE_FAMILIES

        assert complete_receipt.query_set is not None
        assert complete_receipt.query_set.connection_generation == 2
        assert len(facts.trade_observations) == 1
        assert facts.trade_observations[0].trade_id == checkpoint["trade_id"]
        assert facts.trade_observations[0].order_ref == checkpoint["order_ref"]
        before_rows = _callback_rows(journal, checkpoint["intent_id"])
        assert before_rows == (checkpoint["source_callback_receipt"],)
        pending_before = journal.pending_callbacks(limit=16)
        assert tuple(
            row.receipt_id for row in pending_before if row.intent_id == checkpoint["intent_id"]
        ) == (native.receipt_id,), "fresh reopen must retain the original delivery receipt"
        fill_count_before = _callback_fill_count(journal, checkpoint["intent_id"])

        stage = "query_reconciliation"
        page = coordinator.reconcile_trade_observations(
            facts,
            limit=16,
            refresh_receipt=receipt,
        )
        assert page.truncated is False
        assert page.observation_count == 1
        item = page.items[0]
        rows_after_first = _callback_rows(journal, checkpoint["intent_id"])
        native_after_first = journal.callback_receipt(
            checkpoint["intent_id"], checkpoint["source_callback_receipt"]["callback_id"]
        )
        assert native_after_first is not None
        assert native_after_first.acknowledged is False
        assert (
            dict(native_after_first.evidence_payload)
            == checkpoint["source_callback_receipt"]["evidence"]
        )
        disposition = journal.callback_query_disposition(native.receipt_id)

        stage = "query_replay"
        replay = coordinator.reconcile_trade_observations(
            facts,
            limit=16,
            refresh_receipt=receipt,
        )
        assert replay.truncated is False
        assert replay.observation_count == 1
        replay_item = replay.items[0]
        rows_after_replay = _callback_rows(journal, checkpoint["intent_id"])
        fill_count_after = _callback_fill_count(journal, checkpoint["intent_id"])
        pending_receipts = journal.pending_callbacks(limit=16)
        pending_ids = tuple(
            row.receipt_id for row in pending_receipts if row.intent_id == checkpoint["intent_id"]
        )
        owner = journal.active_instrument_owner(
            recovery_helpers._ACCOUNT_SCOPE,
            checkpoint["instrument_id"],
        )
        assert not broker.orders
        assert api.native_calls == []
        assert owner is not None, "query disposition does not release the position owner"

        if proof_case == "match":
            assert item.status in ("APPLIED", "DUPLICATE"), item
            assert item.blocker_code is None
            assert replay_item.status in ("APPLIED", "DUPLICATE"), replay_item
            assert replay_item.blocker_code is None
            assert disposition is not None
            assert disposition.disposition_code == (
                "QUERY_MATCHED_BROKER_ACK_UNOBSERVED_AFTER_RESTART"
            )
            assert disposition.native_receipt_id == native.receipt_id
            assert disposition.intent_id == checkpoint["intent_id"]
            assert disposition.execution_id == item.execution_id
            assert disposition.query_process_instance_id
            query_pid = disposition.query_process_instance_id.split(":", 1)[0]
            assert query_pid.isdecimal() and int(query_pid) != checkpoint["source_process_id"]
            assert disposition.query_process_instance_id != checkpoint["source_process_instance_id"]
            assert len(disposition.proof_sha256) == 64
            proof = disposition.proof_payload
            assert proof["original_order"] == {
                "account_scope": recovery_helpers._ACCOUNT_SCOPE,
                "strategy_scope": recovery_helpers._STRATEGY_SCOPE,
                "trading_day": checkpoint["trading_day"],
                "instrument": checkpoint["instrument_id"],
                "exchange": checkpoint["exchange_id"],
                "order_ref": checkpoint["order_ref"],
                "front_id": 4,
                "session_id": 7,
                "order_sys_id": None,
            }
            assert proof["matched_order"] == {
                "front_id": 4,
                "session_id": 7,
                "order_ref": checkpoint["order_ref"],
                "instrument": checkpoint["instrument_id"],
                "exchange": checkpoint["exchange_id"],
                "order_sys_id": None,
            }
            assert proof["trade"]["trade_id"] == checkpoint["trade_id"]
            assert proof["trade"]["trade_date"] == checkpoint["trade_date"]
            assert proof["trade"]["trade_time"] == checkpoint["trade_time"]
            assert proof["trade"]["quantity"] == "1"
            assert proof["trade"]["price"] == "100"
            assert proof["trade"]["request_id"] > 0
            assert proof["trade"]["connection_generation"] == 2
            assert proof["query_set"]["connection_generation"] == 2
            assert proof["query_set"]["trading_day"] == checkpoint["trading_day"]
            assert tuple(tuple(row) for row in proof["query_set"]["family_request_ids"]) == tuple(
                complete_receipt.query_set.query_ids
            )
            query_rows = [row for row in rows_after_first if row["receipt_id"] != native.receipt_id]
            assert len(query_rows) == 1
            assert query_rows[0]["callback_id"].startswith("query-trade:")
            assert query_rows[0]["acknowledged"] is True
            assert disposition.query_receipt_id == query_rows[0]["receipt_id"]
            assert rows_after_replay == rows_after_first
            assert fill_count_before == 1 and fill_count_after == 1
            assert native.receipt_id not in pending_ids
            repeated_disposition = journal.callback_query_disposition(native.receipt_id)
            assert repeated_disposition == disposition
            outcome = "QUERY_MATCHED_NATIVE_CALLBACK_WITHOUT_ACK_OR_ORDER_REBUILD"
        elif proof_case == "incomplete":
            assert item.status in ("APPLIED", "DUPLICATE"), item
            assert item.blocker_code == "CALLBACK_QUERY_REFRESH_RECEIPT_INCOMPLETE"
            assert replay_item.status in ("APPLIED", "DUPLICATE"), replay_item
            assert replay_item.blocker_code == item.blocker_code
            assert disposition is None
            assert fill_count_before == 1 and fill_count_after == 1
            assert rows_after_replay == rows_after_first
            assert native.receipt_id in pending_ids
            outcome = "INCOMPLETE_QUERY_RECEIPT_LEFT_NATIVE_CALLBACK_PENDING"
        else:
            assert proof_case == "mismatch"
            assert item.status == "BLOCKED", item
            assert item.blocker_code == "NATIVE_TRADE_CALLBACK_QUERY_CONFLICT"
            assert replay_item.status == "BLOCKED", replay_item
            assert replay_item.blocker_code == item.blocker_code
            assert disposition is None
            assert fill_count_before == 1 and fill_count_after == 1
            assert rows_after_replay == rows_after_first == before_rows
            assert native.receipt_id in pending_ids
            outcome = "MISMATCHED_TRADE_LEFT_NATIVE_CALLBACK_PENDING"

        result_queue.put(
            {
                "status": "OK",
                "outcome": outcome,
                "proof_case": proof_case,
                "item_status": item.status,
                "blocker_code": item.blocker_code,
                "replay_status": replay_item.status,
                "fill_count_before": fill_count_before,
                "fill_count_after": fill_count_after,
                "native_receipt_id": native.receipt_id,
                "native_acknowledged": native_after_first.acknowledged,
                "native_evidence_unchanged": dict(native_after_first.evidence_payload)
                == checkpoint["source_callback_receipt"]["evidence"],
                "native_pending": native.receipt_id in pending_ids,
                "disposition_code": None if disposition is None else disposition.disposition_code,
                "disposition_query_receipt_id": (
                    None if disposition is None else disposition.query_receipt_id
                ),
                "disposition_query_process_instance_id": (
                    None if disposition is None else disposition.query_process_instance_id
                ),
                "disposition_proof_json": (
                    None if disposition is None else _callback_proof_json(disposition.proof_payload)
                ),
                "disposition_proof_sha256": (
                    None if disposition is None else disposition.proof_sha256
                ),
                "fresh_broker_orders": len(broker.orders),
                "native_calls": len(api.native_calls),
                "owner_retained": owner is not None,
            }
        )
    except BaseException as error:
        result_queue.put(
            {
                "status": "ERROR",
                "stage": stage,
                "error_type": type(error).__name__,
                "error_code": getattr(error, "code", None),
                "error_message": str(error)[:240],
            }
        )
    finally:
        journal.close()


@pytest.mark.parametrize("proof_case", ("match", "incomplete", "mismatch"))
def test_spawned_callback_before_ack_uses_exact_query_disposition_only_after_restart(
    tmp_path, proof_case
):
    """A matching full query can retire delivery without ACK or duplicate fill."""

    journal_path = tmp_path / ("callback-query-disposition-" + proof_case + ".sqlite3")
    checkpoint_path = tmp_path / ("callback-query-disposition-" + proof_case + ".json")
    context = multiprocessing.get_context("spawn")
    source = context.Process(
        target=_source_callback_crash_worker,
        args=(str(journal_path), str(checkpoint_path), "callback_after_projection"),
        name="factor-execution-native-callback-crash",
    )
    source.start()
    source_pid = source.pid
    source.join(timeout=45)
    if source.is_alive():
        source.terminate()
        source.join(timeout=5)
        pytest.fail("test-owned native callback crash worker exceeded its bound")
    assert source.exitcode == _EXIT_CODES["callback_after_projection"]
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["source_process_id"] = source_pid
    assert type(source_pid) is int and source_pid != os.getpid()
    assert checkpoint["source_callback_receipt"] is not None
    assert checkpoint["source_callback_receipt"]["acknowledged"] is False
    assert checkpoint["receipt_acknowledged"] is False
    assert checkpoint["projection_status"] == "APPLIED"
    assert checkpoint["broker_position_before_apply"] == 0
    assert checkpoint["order_executed_before_apply"] == 0

    recovered = _spawn_result(
        context,
        target=_spawned_reconcile_native_callback_query_disposition,
        args=(str(journal_path), checkpoint, proof_case),
    )
    assert recovered["proof_case"] == proof_case
    assert recovered["native_acknowledged"] is False
    assert recovered["native_evidence_unchanged"] is True
    assert recovered["fill_count_before"] == 1
    assert recovered["fill_count_after"] == 1
    assert recovered["fresh_broker_orders"] == 0
    assert recovered["native_calls"] == 0
    assert recovered["owner_retained"] is True
    if proof_case == "match":
        assert recovered["outcome"] == "QUERY_MATCHED_NATIVE_CALLBACK_WITHOUT_ACK_OR_ORDER_REBUILD"
        assert recovered["native_pending"] is False
        assert recovered["disposition_code"] == (
            "QUERY_MATCHED_BROKER_ACK_UNOBSERVED_AFTER_RESTART"
        )
        assert recovered["blocker_code"] is None

        # Opening the database after the recovery worker has exited exercises
        # startup validation of a valid persisted proof. This third process
        # scope reads the exact immutable proof, source callback row and fill
        # checkpoint without rebuilding an Order or invoking native methods.
        reopened = ExecutionDecisionJournal(journal_path)
        try:
            native = reopened.callback_receipt(
                checkpoint["intent_id"], checkpoint["source_callback_receipt"]["callback_id"]
            )
            assert native is not None
            assert native.receipt_id == recovered["native_receipt_id"]
            assert native.acknowledged is False
            assert (
                dict(native.evidence_payload) == checkpoint["source_callback_receipt"]["evidence"]
            )

            disposition = reopened.callback_query_disposition(native.receipt_id)
            assert disposition is not None
            assert disposition.disposition_code == recovered["disposition_code"]
            assert disposition.query_receipt_id == recovered["disposition_query_receipt_id"]
            assert (
                disposition.query_process_instance_id
                == recovered["disposition_query_process_instance_id"]
            )
            assert (
                _callback_proof_json(disposition.proof_payload)
                == recovered["disposition_proof_json"]
            )
            assert disposition.proof_sha256 == recovered["disposition_proof_sha256"]

            persisted_rows = _callback_rows(reopened, checkpoint["intent_id"])
            assert persisted_rows[0] == checkpoint["source_callback_receipt"]
            query_rows = [row for row in persisted_rows if row["receipt_id"] != native.receipt_id]
            assert len(query_rows) == 1
            assert query_rows[0]["receipt_id"] == disposition.query_receipt_id
            assert query_rows[0]["acknowledged"] is True
            pending_ids = tuple(row.receipt_id for row in reopened.pending_callbacks(limit=16))
            assert native.receipt_id not in pending_ids
            assert _callback_fill_count(reopened, checkpoint["intent_id"]) == 1
        finally:
            reopened.close()
    elif proof_case == "incomplete":
        assert recovered["outcome"] == "INCOMPLETE_QUERY_RECEIPT_LEFT_NATIVE_CALLBACK_PENDING"
        assert recovered["native_pending"] is True
        assert recovered["disposition_code"] is None
        assert recovered["blocker_code"] == "CALLBACK_QUERY_REFRESH_RECEIPT_INCOMPLETE"
    else:
        assert recovered["outcome"] == "MISMATCHED_TRADE_LEFT_NATIVE_CALLBACK_PENDING"
        assert recovered["native_pending"] is True
        assert recovered["disposition_code"] is None
        assert recovered["blocker_code"] == "NATIVE_TRADE_CALLBACK_QUERY_CONFLICT"


def test_reopened_journal_in_same_process_cannot_claim_callback_restart_disposition(tmp_path):
    """Reopening SQLite in the producer process does not prove a process restart."""

    journal_path = tmp_path / "callback-query-same-process.sqlite3"
    fixed_now = datetime(2026, 10, 24, 1, 0, 10, tzinfo=timezone.utc)
    (
        api,
        _store,
        broker,
        journal,
        coordinator,
        target,
        data,
        owner,
        _cerebro,
    ) = recovery_helpers._durable_system(journal_path, now=fixed_now)
    checkpoint = None
    try:
        initial_facts = recovery_helpers._initial_open_facts(
            api, _store, broker, target, now=fixed_now
        )
        scope, _intent_key, _economics = recovery_helpers._decision_scope(
            coordinator,
            owner,
            initial_facts,
            close_time=initial_facts.available_at - timedelta(milliseconds=2),
            batch_id="callback-same-process-source",
        )
        order = _submit_in_scope(scope, owner, data)
        assert order is not None and order.info["factor_dispatch_state"] == "KNOWN"
        intent = journal.intent(order.info["factor_intent_id"])
        assert intent is not None and intent.dispatch_state == "KNOWN"
        order_ref = intent.original_identity["order_ref"]
        trade_time = (fixed_now + timedelta(seconds=5)).astimezone(timezone(timedelta(hours=8)))
        api.emit_provider_trade_callback(
            order_ref,
            trade_id="callback-same-process-trade",
            quantity=1,
            offset="open",
            when=trade_time,
            omit_trade_date=False,
        )

        def interrupt_before_ack(_receipt_id):
            raise RuntimeError("test leaves the durable callback unacknowledged")

        journal.acknowledge_callback = interrupt_before_ack
        broker._drain_store_updates()
        rows = _callback_rows(journal, intent.intent_id)
        assert len(rows) == 1
        callback_id = rows[0]["callback_id"]
        assert rows[0]["acknowledged"] is False
        assert broker.getposition(data).size == 1
        assert order.executed.size == 1
        checkpoint = {
            "intent_id": intent.intent_id,
            "order_ref": order_ref,
            "trading_day": intent.original_identity["trading_day"],
            "instrument_id": intent.original_identity["instrument_id"],
            "exchange_id": intent.original_identity["exchange_id"],
            "trade_id": "callback-same-process-trade",
            "trade_date": trade_time.strftime("%Y%m%d"),
            "trade_time": trade_time.strftime("%H:%M:%S"),
            "source_callback_receipt": rows[0],
            "source_process_instance_id": _callback_process_instance_id(
                journal, rows[0]["receipt_id"]
            ),
            "source_process_id": os.getpid(),
        }
    finally:
        journal.close()

    # _durable_system creates a fresh Store/Broker and reopens this database,
    # while the process-instance marker remains shared with the producer.
    now = datetime.now(timezone.utc)
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        target,
        _data,
        _owner,
        _cerebro,
    ) = recovery_helpers._durable_system(journal_path, now=now)
    try:
        _callback_query_rows(api, checkpoint)
        receipt, facts = recovery_helpers._refresh_five_family_facts(
            api,
            store,
            broker,
            target,
            generation=2,
            sequence=22,
        )
        assert receipt.blockers == () and receipt.pending_families == ()
        assert receipt.query_set is not None
        native = journal.callback_receipt(checkpoint["intent_id"], callback_id)
        assert native is not None and native.acknowledged is False
        assert (
            _callback_process_instance_id(journal, native.receipt_id)
            == checkpoint["source_process_instance_id"]
        )
        assert dict(native.evidence_payload) == checkpoint["source_callback_receipt"]["evidence"]
        pending_before = journal.pending_callbacks(limit=16)
        assert native.receipt_id in tuple(row.receipt_id for row in pending_before)
        page = coordinator.reconcile_trade_observations(
            facts,
            limit=16,
            refresh_receipt=receipt,
        )
        assert page.observation_count == 1 and page.truncated is False
        item = page.items[0]
        native_after = journal.callback_receipt(checkpoint["intent_id"], callback_id)
        assert native_after is not None and native_after.acknowledged is False
        assert (
            dict(native_after.evidence_payload) == checkpoint["source_callback_receipt"]["evidence"]
        )
        assert item.status in ("APPLIED", "DUPLICATE"), item
        assert item.blocker_code == "CALLBACK_QUERY_RESTART_NOT_PROVEN"
        assert journal.callback_query_disposition(native.receipt_id) is None
        pending = journal.pending_callbacks(limit=16)
        assert native.receipt_id in tuple(row.receipt_id for row in pending)
        assert _callback_fill_count(journal, checkpoint["intent_id"]) == 1
        assert not broker.orders
        assert api.native_calls == []
    finally:
        journal.close()


def test_dispatching_without_terminal_query_stays_unresolved_on_grid_replay():
    """Old-grid replay alone never resolves a claimed native dispatch."""

    assert _INCOMPLETE_DISPATCHING_WITHOUT_TERMINAL_PROOF == (
        "INCOMPLETE_RECOVERY_WITHOUT_TERMINAL_PROOF:DISPATCHING_REMAINS_UNRESOLVED"
    )


def _spawned_submit_live_until_crash_worker(
    journal_path, checkpoint_path, request_entered, crash_now
):
    """Hold the real dispatch gate across a submitted fake native request."""

    now = datetime.now(timezone.utc)
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        target,
        data,
        owner,
        _cerebro,
    ) = recovery_helpers._durable_system(journal_path, now=now)
    try:
        facts = recovery_helpers._initial_open_facts(api, store, broker, target, now=now)
        scope, _intent_key, _economics = recovery_helpers._decision_scope(
            coordinator,
            owner,
            facts,
            close_time=facts.available_at - timedelta(milliseconds=2),
            batch_id="dispatching-live-gate-submit",
        )
        native_insert = api.trader_client.submit_order_insert

        def request_then_hold(field, request_id, *, execution_capability):
            native_code = native_insert(
                field,
                request_id,
                execution_capability=execution_capability,
            )
            order_ref = str(field.OrderRef)
            intent = journal.intent_by_native_order_ref(
                account_scope=recovery_helpers._ACCOUNT_SCOPE,
                strategy_scope=recovery_helpers._STRATEGY_SCOPE,
                trading_day=recovery_helpers._TRADING_DAY,
                instrument=recovery_helpers._INSTRUMENT,
                exchange=recovery_helpers._EXCHANGE,
                order_ref=order_ref,
            )
            assert intent is not None and intent.state == "DISPATCHING"
            assert intent.dispatch_state is None
            _write_checkpoint(
                checkpoint_path,
                {
                    "boundary": "live_dispatching_submit",
                    "intent_id": intent.intent_id,
                    "native_request_id": request_id,
                    "native_return_code_before_crash": native_code,
                    "original_identity": dict(intent.original_identity),
                    "native_call_count": len(api.native_calls),
                },
            )
            request_entered.set()
            if not crash_now.wait(20):
                os._exit(94)
            # Exit before the Store returns and before complete_order can
            # persist a KNOWN/UNKNOWN dispatch result.
            os._exit(_EXIT_CODES["live_dispatching_submit_crash"])

        api.trader_client.submit_order_insert = request_then_hold
        _submit_in_scope(scope, owner, data)
        raise AssertionError("the controlled native request returned normally")
    finally:
        journal.close()


def _refresh_and_reconcile_inside_terminal_scope(
    api,
    store,
    broker,
    target,
    coordinator,
    *,
    generation,
    sequence,
    stale_snapshot=None,
):
    """Keep the durable dispatch gate across source reads and retirement."""

    with coordinator.terminal_recovery_scope(timeout_seconds=5.0) as scope_started_at:
        stale_page = None
        if stale_snapshot is not None:
            stale_receipt, stale_facts = stale_snapshot
            stale_page = coordinator.reconcile_terminal_order_observations(
                stale_facts,
                refresh_receipt=stale_receipt,
                limit=128,
            )
        receipt, facts = recovery_helpers._refresh_five_family_facts(
            api,
            store,
            broker,
            target,
            generation=generation,
            sequence=sequence,
        )
        page = coordinator.reconcile_terminal_order_observations(
            facts,
            refresh_receipt=receipt,
            limit=128,
        )
    return receipt, facts, page, scope_started_at, stale_page


def _spawned_recover_submit_dispatching_no_fill(journal_path, terminal_row, result_queue):
    """Recover only from a new complete query after the original process died."""

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
    ) = recovery_helpers._durable_system(journal_path, now=now)
    stage = "fresh_terminal_query"
    reconciliation_item = None
    try:
        recovery_helpers._bind_current_session_identity(api, generation=2, front_id=5, session_id=8)
        api.query_rows["orders_result"] = [terminal_row]
        stale_receipt, stale_facts = recovery_helpers._refresh_five_family_facts(
            api,
            store,
            broker,
            target,
            generation=2,
            sequence=8,
        )
        assert stale_receipt.query_set is not None
        assert stale_receipt.query_set.started_at_utc < datetime.now(timezone.utc)
        outside_scope = coordinator.reconcile_terminal_order_observations(
            stale_facts,
            refresh_receipt=stale_receipt,
            limit=128,
        )
        assert len(outside_scope.items) == 1
        assert outside_scope.items[0].status == "BLOCKED"
        assert outside_scope.items[0].blocker_code == "DISPATCHING_RECOVERY_SCOPE_REQUIRED"
        dispatch_owner = journal.active_instrument_owner(
            recovery_helpers._ACCOUNT_SCOPE,
            recovery_helpers._INSTRUMENT,
        )
        assert dispatch_owner is not None
        still_dispatching = journal.intent(dispatch_owner.intent_id)
        assert still_dispatching is not None and still_dispatching.state == "DISPATCHING"

        (
            receipt,
            facts,
            page,
            scope_started_at,
            stale_page,
        ) = _refresh_and_reconcile_inside_terminal_scope(
            api,
            store,
            broker,
            target,
            coordinator,
            generation=2,
            sequence=9,
            stale_snapshot=(stale_receipt, stale_facts),
        )
        assert receipt.query_set is not None
        assert receipt.blockers == ()
        assert receipt.pending_families == ()
        assert receipt.query_set.connection_generation == 2
        assert receipt.query_set.trading_day == recovery_helpers._TRADING_DAY
        assert receipt.query_set.started_at_utc >= scope_started_at
        assert stale_receipt.query_set.started_at_utc < scope_started_at
        assert stale_page is not None and len(stale_page.items) == 1
        assert stale_page.items[0].status == "BLOCKED"
        assert stale_page.items[0].blocker_code == "DISPATCHING_RECOVERY_QUERY_PREDATES_SCOPE"
        assert facts.trade_observations == ()
        assert len(facts.terminal_orders) == 1
        assert facts.terminal_orders[0].order_ref == terminal_row["OrderRef"]
        assert facts.terminal_orders[0].volume_traded == 0
        assert facts.positions[0].broker_quantity == 0
        assert facts.positions[0].long_quantity == 0
        assert facts.positions[0].short_quantity == 0
        assert not broker.orders, "fresh-process recovery must not rebuild the old Order"
        assert api.native_calls == []

        assert len(page.items) == 1
        item = page.items[0]
        reconciliation_item = item
        assert item.status == "RESOLVED", item
        intent = journal.intent(item.intent_id)
        assert intent is not None
        assert intent.state == "KNOWN"
        # Reconciliation proves terminal no-fill; it is not a fabricated
        # native dispatch response and must preserve the absent dispatch data.
        assert intent.dispatch_state is None
        assert intent.provider_identity is None
        assert intent.outcome_code is None
        assert dict(intent.original_identity)["order_ref"] == terminal_row["OrderRef"]
        resolution = journal.instrument_resolution(intent.intent_id)
        assert resolution is not None
        assert resolution.reconciliation_id == item.reconciliation_id
        assert resolution.position_flat is True
        assert (
            journal.active_instrument_owner(
                recovery_helpers._ACCOUNT_SCOPE,
                recovery_helpers._INSTRUMENT,
            )
            is None
        )
        assert not broker.orders
        assert api.native_calls == []

        # A later grid is admitted only after a fresh generation-2 quote/query
        # preflight and the normal route-arm path. Its OrderRef must be new.
        stage = "fresh_grid_preflight"
        store.registered_sim_configure_arm_templates(
            {
                (recovery_helpers._INSTRUMENT, recovery_helpers._EXCHANGE): (
                    recovery_helpers._arm_template()
                )
            }
        )
        store.registered_sim_arm(
            instrument=recovery_helpers._INSTRUMENT,
            exchange=recovery_helpers._EXCHANGE,
            **recovery_helpers._arm_template(),
        )
        api._next_order_reference = 900
        next_receipt, next_facts = recovery_helpers._refresh_five_family_facts(
            api,
            store,
            broker,
            target,
            generation=2,
            sequence=10,
            include_margin=True,
        )
        assert next_receipt.query_set is not None
        assert next_receipt.query_set.connection_generation == 2
        assert next_facts.open_risk_ready is True, next_facts.blockers
        assert not broker.orders
        assert api.native_calls == []

        stage = "new_grid_submit"
        new_order = recovery_helpers._submit_open(
            coordinator,
            strategy,
            data,
            next_facts,
            close_time=next_facts.available_at - timedelta(milliseconds=2),
            batch_id="dispatching-no-fill-recovered-new-grid",
        )
        assert new_order is not None
        new_intent = journal.intent(new_order.info["factor_intent_id"])
        assert new_intent is not None and new_intent.dispatch_state == "KNOWN"
        assert new_intent.original_identity["order_ref"] != terminal_row["OrderRef"]
        assert len(api.native_calls) == 1
        assert api.native_calls[0][0] == "insert"
        assert api.native_calls[0][3] == new_intent.original_identity["order_ref"]
        assert len(broker.orders) == 1
        assert broker.orders[new_order.ref] is new_order

        result_queue.put(
            {
                "status": "OK",
                "old_intent_id": intent.intent_id,
                "old_order_ref": intent.original_identity["order_ref"],
                "old_dispatch_fields_null": (
                    intent.dispatch_state is None
                    and intent.provider_identity is None
                    and intent.outcome_code is None
                ),
                "resolution_flat": resolution.position_flat,
                "owner_released_before_new_grid": True,
                "old_order_rebuilt": False,
                "new_intent_id": new_intent.intent_id,
                "new_order_ref": new_intent.original_identity["order_ref"],
                "native_calls": tuple(api.native_calls),
            }
        )
    except BaseException as error:
        result_queue.put(
            {
                "status": "ERROR",
                "stage": stage,
                "error_type": type(error).__name__,
                "error_code": getattr(error, "code", None),
                "reconciliation_status": (
                    None if reconciliation_item is None else reconciliation_item.status
                ),
                "reconciliation_blocker_code": (
                    None if reconciliation_item is None else reconciliation_item.blocker_code
                ),
                "error_message": str(error)[:240],
            }
        )
    finally:
        journal.close()


def test_spawned_live_dispatch_gate_then_fresh_process_no_fill_recovery_and_new_grid(tmp_path):
    """A live dispatch blocks CAS; post-crash proof resolves without replaying its ref."""

    path = tmp_path / "dispatching-submit-positive-recovery.sqlite3"
    checkpoint_path = tmp_path / "dispatching-submit-crash.json"
    context = multiprocessing.get_context("spawn")
    request_entered = context.Event()
    crash_now = context.Event()
    dispatcher = context.Process(
        target=_spawned_submit_live_until_crash_worker,
        args=(str(path), str(checkpoint_path), request_entered, crash_now),
        name="factor-execution-live-dispatch-crash",
    )
    dispatcher.start()
    recovery_journal = None
    query_journal = None
    try:
        assert request_entered.wait(15), "the native leaf did not reach its barrier"
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        assert checkpoint["boundary"] == "live_dispatching_submit"
        assert checkpoint["native_call_count"] == 1
        identity = checkpoint["original_identity"]
        old_order_ref = identity["order_ref"]
        assert old_order_ref.isdecimal() and int(old_order_ref) > 0

        recovery_journal = ExecutionDecisionJournal(path)
        persisted = recovery_journal.intent(checkpoint["intent_id"])
        assert persisted is not None
        assert persisted.state == "DISPATCHING"
        assert persisted.dispatch_state is None
        assert persisted.provider_identity is None
        assert persisted.outcome_code is None
        assert dict(persisted.original_identity) == identity
        owner = recovery_journal.active_instrument_owner(
            recovery_helpers._ACCOUNT_SCOPE,
            recovery_helpers._INSTRUMENT,
        )
        assert owner is not None and owner.intent_id == persisted.intent_id
        assert owner.state == "DISPATCHING"

        # A complete-looking terminal row cannot race a dispatcher that still
        # owns the shared Journal gate.
        now = datetime.now(timezone.utc)
        (
            api,
            store,
            broker,
            query_journal,
            coordinator,
            target,
            _data,
            _strategy,
            _cerebro,
        ) = recovery_helpers._durable_system(path, now=now)
        recovery_helpers._bind_current_session_identity(api, generation=2, front_id=5, session_id=8)
        terminal_row = recovery_helpers._terminal_row(
            old_order_ref,
            front_id=identity["front_id"],
            session_id=identity["session_id"],
            trading_day=identity["trading_day"],
        )
        api.query_rows["orders_result"] = [terminal_row]
        with pytest.raises(FactorExecutionError) as busy, coordinator.terminal_recovery_scope(
            timeout_seconds=0.25
        ):
            recovery_helpers._refresh_five_family_facts(
                api,
                store,
                broker,
                target,
                generation=2,
                sequence=9,
            )
        assert busy.value.code == "DISPATCH_SERIALIZATION_BUSY"
        assert api.query_calls == [], "the durable gate must be acquired before any query"
        still_pending = recovery_journal.intent(persisted.intent_id)
        assert still_pending is not None and still_pending.state == "DISPATCHING"
        assert still_pending.dispatch_state is None
        assert recovery_journal.instrument_resolution(persisted.intent_id) is None
        assert recovery_journal.reconciliations(persisted.intent_id, limit=8) == ()
        still_owned = recovery_journal.active_instrument_owner(
            recovery_helpers._ACCOUNT_SCOPE,
            recovery_helpers._INSTRUMENT,
        )
        assert still_owned is not None and still_owned.intent_id == persisted.intent_id
        assert api.native_calls == []
        query_journal.close()
        query_journal = None
    finally:
        crash_now.set()
        dispatcher.join(timeout=15)
        if dispatcher.is_alive():
            dispatcher.terminate()
            dispatcher.join(timeout=5)
        if query_journal is not None:
            query_journal.close()
        if recovery_journal is not None:
            recovery_journal.close()
    assert dispatcher.exitcode == _EXIT_CODES["live_dispatching_submit_crash"]

    terminal_row = recovery_helpers._terminal_row(
        old_order_ref,
        front_id=identity["front_id"],
        session_id=identity["session_id"],
        trading_day=identity["trading_day"],
    )
    recovered = _spawn_result(
        context,
        target=_spawned_recover_submit_dispatching_no_fill,
        args=(str(path), terminal_row),
    )
    assert recovered["old_intent_id"] == checkpoint["intent_id"]
    assert recovered["old_order_ref"] == old_order_ref
    assert recovered["old_dispatch_fields_null"] is True
    assert recovered["resolution_flat"] is True
    assert recovered["owner_released_before_new_grid"] is True
    assert recovered["old_order_rebuilt"] is False
    assert recovered["new_intent_id"] != checkpoint["intent_id"]
    assert recovered["new_order_ref"] != old_order_ref
    assert recovered["native_calls"] == (
        (
            "insert",
            recovery_helpers._INSTRUMENT,
            recovery_helpers._EXCHANGE,
            recovered["new_order_ref"],
            101,
        ),
    )


def _spawned_cancel_dispatching_crash_worker(journal_path, checkpoint_path):
    """Create a real known submit, then die inside its claimed native cancel."""

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
    ) = recovery_helpers._durable_system(journal_path, now=now)
    try:
        facts = recovery_helpers._initial_open_facts(api, store, broker, target, now=now)
        order = recovery_helpers._submit_open(
            coordinator,
            strategy,
            data,
            facts,
            close_time=facts.available_at - timedelta(milliseconds=2),
            batch_id="cancel-dispatching-parent-submit",
        )
        assert order is not None and order.status == recovery_helpers.Order.Accepted
        submit_intent_id = order.info["factor_intent_id"]
        order_ref = order.info["external_order_ref"]
        active_row = {
            **recovery_helpers._terminal_row(order_ref),
            "OrderSysID": "",
            "OrderStatus": "3",
            "Direction": "0",
        }
        api.query_rows["orders_result"] = [active_row]
        _active_receipt, active_facts = recovery_helpers._refresh_five_family_facts(
            api,
            store,
            broker,
            target,
            generation=1,
            sequence=20,
        )
        assert active_facts.order_cancel_ready is True, active_facts.order_cancel_blockers

        cancel_key = ExecutionDecisionKey(
            account_scope=recovery_helpers._ACCOUNT_SCOPE,
            strategy_scope=recovery_helpers._STRATEGY_SCOPE,
            logical_run_id="run-1",
            cohort_id="rb-cohort",
            close_time=active_facts.available_at.isoformat().replace("+00:00", "Z"),
            decision_kind="ALPHA003_RISK_REDUCTION",
        )
        cancel_intent_key = ExecutionIntentKey(
            action="CANCEL",
            instrument=recovery_helpers._INSTRUMENT,
            side="BUY",
            position_effect="OPEN",
            leg=0,
        )
        cancel_economics = {
            "instrument": recovery_helpers._INSTRUMENT,
            "exchange": recovery_helpers._EXCHANGE,
            "side": "BUY",
            "position_effect": "OPEN",
            "owner_intent_id": submit_intent_id,
            "reason": "cancel DISPATCHING must not use submit no-fill recovery",
        }
        cancel_scope = coordinator.risk_decision_scope(
            owner=strategy,
            key=cancel_key,
            economic_payload={"intent_economics": (cancel_economics,)},
            intent_keys=(cancel_intent_key,),
            batch=None,
            execution_facts=active_facts,
            inputs_complete=True,
            expected_run_order_intents_used=coordinator.run_order_count(),
            remaining_exit_intent_reserve=0,
        )
        native_cancel = api.trader_client.submit_order_action

        def cancel_then_crash(field, request_id, *, execution_capability):
            native_code = native_cancel(
                field,
                request_id,
                execution_capability=execution_capability,
            )
            active_owner = journal.active_instrument_owner(
                recovery_helpers._ACCOUNT_SCOPE,
                recovery_helpers._INSTRUMENT,
            )
            assert active_owner is not None and active_owner.cancel_intent_id is not None
            cancel_intent = journal.intent(active_owner.cancel_intent_id)
            assert cancel_intent is not None and cancel_intent.state == "DISPATCHING"
            assert cancel_intent.dispatch_state is None
            _write_checkpoint(
                checkpoint_path,
                {
                    "boundary": "cancel_dispatching",
                    "submit_intent_id": submit_intent_id,
                    "cancel_intent_id": cancel_intent.intent_id,
                    "order_ref": order_ref,
                    "original_identity": dict(journal.intent(submit_intent_id).original_identity),
                    "cancel_original_identity": dict(cancel_intent.original_identity),
                    "native_return_code_before_crash": native_code,
                    "native_call_count": len(api.native_calls),
                },
            )
            os._exit(_EXIT_CODES["cancel_dispatching_crash"])

        api.trader_client.submit_order_action = cancel_then_crash
        with cancel_scope:
            strategy.cancel(order)
        raise AssertionError("the controlled native cancel returned normally")
    finally:
        journal.close()


def _spawned_check_cancel_dispatching_stays_blocked(journal_path, terminal_row, result_queue):
    now = datetime.now(timezone.utc)
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        target,
        _data,
        _strategy,
        _cerebro,
    ) = recovery_helpers._durable_system(journal_path, now=now)
    stage = "fresh_cancel_terminal_query"
    try:
        recovery_helpers._bind_current_session_identity(api, generation=2, front_id=5, session_id=8)
        api.query_rows["orders_result"] = [terminal_row]
        (
            receipt,
            facts,
            page,
            scope_started_at,
            _stale_page,
        ) = _refresh_and_reconcile_inside_terminal_scope(
            api,
            store,
            broker,
            target,
            coordinator,
            generation=2,
            sequence=21,
        )
        assert receipt.query_set is not None and receipt.blockers == ()
        assert receipt.query_set.started_at_utc >= scope_started_at
        assert facts.trade_observations == ()
        assert len(facts.terminal_orders) == 1
        assert not broker.orders
        assert not api.native_calls
        checkpoint_owner = journal.active_instrument_owner(
            recovery_helpers._ACCOUNT_SCOPE,
            recovery_helpers._INSTRUMENT,
        )
        assert checkpoint_owner is not None and checkpoint_owner.cancel_intent_id is not None
        cancel_intent_id = checkpoint_owner.cancel_intent_id

        assert len(page.items) == 1
        item = page.items[0]
        assert item.status == "BLOCKED", item
        submit_intent = journal.intent(checkpoint_owner.intent_id)
        cancel_intent = journal.intent(cancel_intent_id)
        assert submit_intent is not None and submit_intent.dispatch_state == "KNOWN"
        assert cancel_intent is not None
        assert cancel_intent.key.action == "CANCEL"
        assert cancel_intent.state == "DISPATCHING"
        assert cancel_intent.dispatch_state is None
        assert cancel_intent.provider_identity is None
        assert cancel_intent.outcome_code is None
        owner_after = journal.active_instrument_owner(
            recovery_helpers._ACCOUNT_SCOPE,
            recovery_helpers._INSTRUMENT,
        )
        assert owner_after is not None
        assert owner_after.intent_id == submit_intent.intent_id
        assert owner_after.cancel_intent_id == cancel_intent.intent_id
        assert journal.instrument_resolution(submit_intent.intent_id) is None
        assert not broker.orders
        assert not api.native_calls
        result_queue.put(
            {
                "status": "OK",
                "item_status": item.status,
                "blocker_code": item.blocker_code,
                "submit_intent_id": submit_intent.intent_id,
                "cancel_intent_id": cancel_intent.intent_id,
                "owner_retained": owner_after.cancel_intent_id == cancel_intent.intent_id,
                "resolution_absent": journal.instrument_resolution(submit_intent.intent_id) is None,
                "native_calls": len(api.native_calls),
                "old_orders_rebuilt": bool(broker.orders),
            }
        )
    except BaseException as error:
        result_queue.put(
            {
                "status": "ERROR",
                "stage": stage,
                "error_type": type(error).__name__,
                "error_code": getattr(error, "code", None),
                "error_message": str(error)[:240],
            }
        )
    finally:
        journal.close()


def test_spawned_cancel_dispatching_is_not_resolved_by_submit_terminal_query(tmp_path):
    """A cancel with no durable result keeps the original submit owner held."""

    path = tmp_path / "cancel-dispatching-remains-blocked.sqlite3"
    checkpoint_path = tmp_path / "cancel-dispatching-crash.json"
    context = multiprocessing.get_context("spawn")
    child = context.Process(
        target=_spawned_cancel_dispatching_crash_worker,
        args=(str(path), str(checkpoint_path)),
        name="factor-execution-cancel-dispatch-crash",
    )
    child.start()
    child.join(timeout=45)
    if child.is_alive():
        child.terminate()
        child.join(timeout=5)
        pytest.fail("test-owned cancel DISPATCHING worker exceeded its bound")
    assert child.exitcode == _EXIT_CODES["cancel_dispatching_crash"]
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["boundary"] == "cancel_dispatching"
    assert checkpoint["native_call_count"] == 2  # original insert + one cancel
    assert checkpoint["native_return_code_before_crash"] == 0
    original = checkpoint["original_identity"]
    assert checkpoint["order_ref"] == original["order_ref"]

    terminal_row = recovery_helpers._terminal_row(
        original["order_ref"],
        front_id=original["front_id"],
        session_id=original["session_id"],
        trading_day=original["trading_day"],
    )
    recovered = _spawn_result(
        context,
        target=_spawned_check_cancel_dispatching_stays_blocked,
        args=(str(path), terminal_row),
    )
    assert recovered["item_status"] == "BLOCKED"
    assert recovered["submit_intent_id"] == checkpoint["submit_intent_id"]
    assert recovered["cancel_intent_id"] == checkpoint["cancel_intent_id"]
    assert recovered["owner_retained"] is True
    assert recovered["resolution_absent"] is True
    assert recovered["native_calls"] == 0
    assert recovered["old_orders_rebuilt"] is False
