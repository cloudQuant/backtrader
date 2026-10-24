"""Spawned crash-boundary checks for durable factor execution.

Each source worker is a test-owned spawned process. It calls ``os._exit`` only
after a selected SQLite/API boundary, so Python cleanup cannot hide whether
the last durable state survived. Recovery workers use the real journal,
coordinator, Store and Broker with the existing fake SDK leaves. A DISPATCHING
row is retained as DISPATCHING; this file does not manufacture UNKNOWN or
claim that positive reconciliation for that state exists.
"""

from __future__ import annotations

import json
import multiprocessing
import os
from datetime import datetime, timedelta, timezone

import pytest

from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal
from backtrader.stores.factor_execution import FactorExecutionDecisionScope
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
}

_INCOMPLETE_DISPATCHING_RECOVERY = (
    "INCOMPLETE_POSITIVE_RECOVERY_UNSUPPORTED:DISPATCHING_REMAINS_UNRESOLVED"
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
                    _INCOMPLETE_DISPATCHING_RECOVERY
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
        assert recovered["recovery_state"] == _INCOMPLETE_DISPATCHING_RECOVERY


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


def test_module_declares_dispatching_positive_recovery_incomplete_without_state_rewrite():
    """Make the supported boundary explicit for operators and future tests."""

    assert _INCOMPLETE_DISPATCHING_RECOVERY == (
        "INCOMPLETE_POSITIVE_RECOVERY_UNSUPPORTED:DISPATCHING_REMAINS_UNRESOLVED"
    )
