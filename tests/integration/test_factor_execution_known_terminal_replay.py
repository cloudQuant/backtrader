"""Read-only replay of an already resolved dispatching no-fill order.

The dispatcher and replay workers are separate spawned processes. Production
Journal, Coordinator, Store and Broker remain in place; only the registered
SimNow API leaves are synthetic.
"""

from __future__ import annotations

import json
import multiprocessing

from tests.integration import test_factor_execution_crash_boundaries as crash_helpers
from tests.integration import test_factor_execution_unknown_recovery as recovery_helpers


def _spawned_replay_known_no_fill_terminal(journal_path, terminal_row, result_queue):
    """Replay the exact terminal row without recovery scope or durable writes."""

    from datetime import datetime, timezone

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
    stage = "refresh_exact_terminal_row"
    try:
        recovery_helpers._bind_current_session_identity(api, generation=2, front_id=5, session_id=8)
        api.query_rows["orders_result"] = [terminal_row]
        receipt, facts = recovery_helpers._refresh_five_family_facts(
            api,
            store,
            broker,
            target,
            generation=2,
            sequence=11,
        )
        matches = journal.intent_by_native_order_ref(
            account_scope=recovery_helpers._ACCOUNT_SCOPE,
            strategy_scope=recovery_helpers._STRATEGY_SCOPE,
            trading_day=terminal_row["TradingDay"],
            instrument=terminal_row["InstrumentID"],
            exchange=terminal_row["ExchangeID"],
            order_ref=terminal_row["OrderRef"],
        )
        assert matches is not None
        intent_id = matches.intent_id
        resolution_before = journal.instrument_resolution(intent_id)
        reconciliations_before = journal.reconciliations(intent_id, limit=8)
        assert resolution_before is not None
        assert len(reconciliations_before) == 1

        stage = "exact_terminal_replay"
        page = coordinator.reconcile_terminal_order_observations(
            facts,
            refresh_receipt=receipt,
            limit=128,
        )
        assert len(page.items) == 1
        replay = page.items[0]
        assert replay.status == "RESOLVED", replay
        assert replay.intent_id == intent_id
        assert replay.reconciliation_id == resolution_before.reconciliation_id
        assert journal.reconciliations(intent_id, limit=8) == reconciliations_before
        assert journal.instrument_resolution(intent_id) == resolution_before
        assert not broker.orders, "a read-only replay must not rebuild the historical Order"
        assert api.native_calls == [], "a terminal replay must not resend the original request"

        # A later source row that changes the persisted terminal status is a
        # conflict. It must neither rewrite the first reconciliation nor issue
        # a retirement/native request.
        stage = "conflicting_terminal_replay"
        conflicting_row = dict(terminal_row)
        conflicting_row["OrderStatus"] = "4"  # CTP NO_TRADE_NOT_QUEUEING
        api.query_rows["orders_result"] = [conflicting_row]
        conflicting_receipt, conflicting_facts = recovery_helpers._refresh_five_family_facts(
            api,
            store,
            broker,
            target,
            generation=2,
            sequence=12,
        )
        conflict_page = coordinator.reconcile_terminal_order_observations(
            conflicting_facts,
            refresh_receipt=conflicting_receipt,
            limit=128,
        )
        assert len(conflict_page.items) == 1
        conflict = conflict_page.items[0]
        assert conflict.status == "BLOCKED"
        assert conflict.blocker_code == "DISPATCHING_NO_FILL_REPLAY_CONFLICT"
        assert conflict.reconciliation_id == resolution_before.reconciliation_id
        assert journal.reconciliations(intent_id, limit=8) == reconciliations_before
        assert journal.instrument_resolution(intent_id) == resolution_before
        assert api.native_calls == []
        result_queue.put(
            {
                "status": "OK",
                "intent_id": intent_id,
                "reconciliation_id": resolution_before.reconciliation_id,
                "exact_replay": replay.status,
                "conflict_replay": conflict.blocker_code,
                "reconciliation_count": len(reconciliations_before),
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


def test_spawned_known_no_fill_replay_is_read_only_and_status_bound(tmp_path):
    path = tmp_path / "known-no-fill-terminal-replay.sqlite3"
    checkpoint_path = tmp_path / "known-no-fill-terminal-crash.json"
    context = multiprocessing.get_context("spawn")
    request_entered = context.Event()
    crash_now = context.Event()
    dispatcher = context.Process(
        target=crash_helpers._spawned_submit_live_until_crash_worker,
        args=(str(path), str(checkpoint_path), request_entered, crash_now),
        name="factor-execution-known-no-fill-crash",
    )
    dispatcher.start()
    try:
        assert request_entered.wait(15), "the native submit did not reach its crash boundary"
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        assert checkpoint["boundary"] == "live_dispatching_submit"
        assert checkpoint["native_call_count"] == 1
    finally:
        crash_now.set()
        dispatcher.join(timeout=15)
        if dispatcher.is_alive():
            dispatcher.terminate()
            dispatcher.join(timeout=5)
    assert dispatcher.exitcode == crash_helpers._EXIT_CODES["live_dispatching_submit_crash"]

    identity = checkpoint["original_identity"]
    terminal_row = recovery_helpers._terminal_row(
        identity["order_ref"],
        front_id=identity["front_id"],
        session_id=identity["session_id"],
        trading_day=identity["trading_day"],
    )
    # First spawned process performs the supported fresh-proof retirement and
    # opens a distinct later grid. The second process only replays the original
    # terminal row, which no longer owns the instrument lock.
    recovered = crash_helpers._spawn_result(
        context,
        target=crash_helpers._spawned_recover_submit_dispatching_no_fill,
        args=(str(path), terminal_row),
    )
    assert recovered["old_intent_id"] == checkpoint["intent_id"]
    assert recovered["owner_released_before_new_grid"] is True

    replayed = crash_helpers._spawn_result(
        context,
        target=_spawned_replay_known_no_fill_terminal,
        args=(str(path), terminal_row),
    )
    assert replayed["intent_id"] == checkpoint["intent_id"]
    assert replayed["reconciliation_id"]
    assert replayed["exact_replay"] == "RESOLVED"
    assert replayed["conflict_replay"] == "DISPATCHING_NO_FILL_REPLAY_CONFLICT"
    assert replayed["reconciliation_count"] == 1
