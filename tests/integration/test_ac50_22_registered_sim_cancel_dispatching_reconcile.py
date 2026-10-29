"""Fresh-process recovery for a CTP cancel lost after native dispatch.

These cases keep the production journal, Store, Broker, coordinator, query
projection, and Alpha003 refresh loop in the test. The only provider leaves
are the established public fake CTP client fixtures.
"""

from __future__ import annotations

import importlib.util
import json
import multiprocessing
import os
import sys
import time
import traceback
from contextlib import contextmanager
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from backtrader.order import Order
from backtrader.research.live import LiveFactorReadiness, LiveFactorSnapshot
from backtrader.research.live_cohort import LiveCohortBatch
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionKey,
    ExecutionIntentKey,
)
from tests.integration import test_factor_execution_crash_boundaries as crash_helpers
from tests.integration import test_factor_execution_unknown_recovery as recovery
from tests.unit.stores import test_factor_execution_facts as facts_helpers


_EXIT_CODE = crash_helpers._EXIT_CODES["cancel_dispatching_crash"]
_CTP_TIMEZONE = timezone(timedelta(hours=8))
_RUNNER_PATH = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "unified"
    / "028_alpha003_simnow_minute"
    / "run.py"
)


def _load_runner():
    example_directory = str(_RUNNER_PATH.parent)
    if example_directory not in sys.path:
        sys.path.insert(0, example_directory)
    spec = importlib.util.spec_from_file_location("alpha003_simnow_runner_ac50_22", _RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_RUNNER = _load_runner()


def _refresh_loop(api, store, broker, journal, coordinator, target, cerebro):
    return _RUNNER.QueryRefreshLoop(
        store,
        broker,
        (target,),
        coordinator=coordinator,
        account_scope=recovery._ACCOUNT_SCOPE,
        strategy_scope=recovery._STRATEGY_SCOPE,
        clock=_RUNNER.RunnerWallClock(),
        quote_max_age=timedelta(seconds=60),
        max_query_age=timedelta(seconds=60),
        timeout=3.0,
        overall_timeout=5.0,
        interval=1.0,
        cerebro=cerebro,
        shutdown_grace_seconds=1.0,
    )


def _track_recovery_leases(coordinator):
    entered = []
    original = coordinator.terminal_recovery_scope

    @contextmanager
    def tracked(*, timeout_seconds=5.0):
        with original(timeout_seconds=timeout_seconds) as started_at:
            entered.append(started_at)
            yield started_at

    coordinator.terminal_recovery_scope = tracked
    return entered


def _fresh_terminal_row(checkpoint):
    identity = checkpoint["original_identity"]
    return recovery._terminal_row(
        identity["order_ref"],
        front_id=identity["front_id"],
        session_id=identity["session_id"],
        trading_day=identity["trading_day"],
    )


def _spawn_exit(context, *, target, args, expected_code):
    process = context.Process(target=target, args=args)
    process.start()
    process.join(timeout=60)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        raise AssertionError("test-owned cancel crash worker exceeded its bound")
    assert process.exitcode == expected_code
    return process.pid


def _spawn_result(context, *, target, args):
    result_queue = context.Queue()
    process = context.Process(target=target, args=(*args, result_queue))
    process.start()
    process.join(timeout=60)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        result_queue.close()
        result_queue.join_thread()
        raise AssertionError("test-owned recovery worker exceeded its bound")
    assert process.exitcode == 0
    result = result_queue.get(timeout=5)
    result_queue.close()
    result_queue.join_thread()
    if result["status"] != "OK":
        raise AssertionError("spawned worker failed: {}".format(json.dumps(result, sort_keys=True)))
    result["pid"] = process.pid
    return result


def _seed_current_quote(api, store, broker, target, *, generation, sequence):
    # This creates a current query/quote projection without arming writes.
    recovery._refresh_five_family_facts(
        api,
        store,
        broker,
        target,
        generation=generation,
        sequence=sequence,
    )


def _dispatching_cancel_candidate_page(journal):
    return journal.dispatching_cancel_store_absence_candidates(
        recovery._ACCOUNT_SCOPE,
        limit=128,
    )


def _dispatch_result_json_is_null(journal, intent_id):
    row = journal._connection.execute(
        "SELECT dispatch_result_json FROM execution_decision_intents WHERE intent_id=?",
        (intent_id,),
    ).fetchone()
    assert row is not None
    return row[0] is None


def _capture_real_store_absence_check(store, outcomes):
    """Wrap the production absence assertion and preserve its bounded result."""

    original = store.registered_sim_assert_original_order_absent

    def captured(*, original_identity, expected_session):
        observation = {
            "original_identity": dict(original_identity),
            "expected_session": dict(expected_session),
        }
        try:
            result = original(
                original_identity=original_identity,
                expected_session=expected_session,
            )
        except Exception as error:
            observation.update(
                status="ERROR",
                error_type=type(error).__name__,
                error=str(error)[:240],
            )
            outcomes.append(observation)
            raise
        observation.update(status="OK", result=result)
        outcomes.append(observation)
        return result

    store.registered_sim_assert_original_order_absent = captured
    return captured


def _initialize_fake_sdk_pending_order_maps(api):
    """Mirror the connected fake SDK's explicitly observed empty local maps."""

    for name in ("_pending_orders", "_pending_orders_by_sys_id"):
        value = getattr(api, name, None)
        if value is None:
            setattr(api, name, {})
            value = getattr(api, name)
        assert isinstance(value, dict), name


def _ctp_trade_time_after(after):
    """Return a real whole-second CTP-local timestamp after the required event."""

    if after.tzinfo is None or after.utcoffset() is None:
        raise AssertionError("the decision/query timestamp must be timezone-aware")
    earliest_utc = max(after.astimezone(timezone.utc), datetime.now(timezone.utc))
    target_ctp = earliest_utc.astimezone(_CTP_TIMEZONE).replace(microsecond=0)
    target_ctp += timedelta(seconds=1)
    target_utc = target_ctp.astimezone(timezone.utc)
    while True:
        remaining = (target_utc - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            return target_ctp
        time.sleep(min(remaining, 0.05))


def _persist_unrelated_dispatching_intent(
    journal, coordinator, *, generation=3, front_id=6, session_id=9
):
    """Seed another route's durable claim to exercise the normal recovery gate."""

    instrument = "AC50-22-UNRELATED"
    exchange = "DCE"
    batch_id = "ac50-22-unrelated-dispatching-trigger"
    intent_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument=instrument,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    economics = {
        "instrument": instrument,
        "exchange": exchange,
        "side": "BUY",
        "position_effect": "OPEN",
        "quantity": "1",
        "limit_price": "100",
        "offset": "open",
        "factor_stop_price": "95",
        "risk_policy_id": "ac50-22-unrelated-risk-v1",
        "risk_policy": {"stop_loss_ticks": 5, "max_loss_per_position": "25"},
        "entry_grid_ordinal": 1,
        "batch_id": batch_id,
        "price": "100",
    }
    close_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    decision = journal.record_grid_decision(
        ExecutionDecisionKey(
            account_scope=recovery._ACCOUNT_SCOPE,
            strategy_scope=recovery._STRATEGY_SCOPE,
            logical_run_id="run-1",
            cohort_id="ac50-22-unrelated-cohort",
            close_time=close_time,
            decision_kind="ALPHA003_GRID",
        ),
        {"intent_economics": (economics,)},
        intent_keys=(intent_key,),
        epoch_id="1",
        batch_id=batch_id,
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
        max_order_intents_per_run=100,
        expected_run_order_intents_used=coordinator.run_order_count(),
        remaining_exit_intent_reserve=0,
    )
    assert decision.decision is not None and decision.is_new_grid is True
    identity = {
        "backtrader_order_ref": 90000,
        "order_ref": "90000",
        "instrument_id": instrument,
        "exchange_id": exchange,
        "account_fingerprint": facts_helpers._ACCOUNT,
        "connection_generation": generation,
        "trading_day": recovery._TRADING_DAY,
        "front_id": front_id,
        "session_id": session_id,
        "operation": "insert",
    }
    intent = journal.prepare_intent(
        decision.decision.decision_id,
        intent_key,
        {"intent_economics": economics},
        original_identity=identity,
    )
    claim = journal.claim_dispatch(intent.intent_id)
    assert claim is not None and claim.intent.state == "DISPATCHING"
    return intent


def _spawned_cancel_cas_then_local_order_conflict(journal_path, checkpoint, result_queue):
    now = datetime.now(timezone.utc)
    monkeypatch = pytest.MonkeyPatch()
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        target,
        _data,
        _strategy,
        cerebro,
    ) = recovery._durable_system(journal_path, now=now, monkeypatch=monkeypatch)
    stage = "current_session_query"
    observed_position_projections = []
    try:
        _initialize_fake_sdk_pending_order_maps(api)
        crash_helpers._bind_sdk_session_identity(
            api, generation=2, front_id=5, session_id=8
        )
        api._connected = True
        terminal_row = _fresh_terminal_row(checkpoint)
        api.query_rows["orders_result"] = [terminal_row]
        _seed_current_quote(api, store, broker, target, generation=2, sequence=30)

        absence_calls = []
        absence_errors = []
        absence_outcomes = []
        original_absence = _capture_real_store_absence_check(store, absence_outcomes)

        def collide_with_the_real_store_check(*, original_identity, expected_session):
            absence_calls.append(dict(original_identity))
            # Model a conflicting local reference in this fresh process, then
            # let the real Store assertion reject it.
            api._order_state[checkpoint["order_ref"]] = "active"
            try:
                return original_absence(
                    original_identity=original_identity,
                    expected_session=expected_session,
                )
            except Exception as error:
                absence_errors.append(str(error))
                raise

        store.registered_sim_assert_original_order_absent = collide_with_the_real_store_check
        leases = _track_recovery_leases(coordinator)
        original_terminal_reconcile = coordinator.reconcile_terminal_order_observations
        noncausal_blocker_active = [False]
        noncausal_blocker_projections = []

        def capture_terminal_positions(facts, *args, **kwargs):
            observed_position_projections.append(
                tuple(
                    {
                        "instrument": position.instrument,
                        "exchange": position.exchange,
                        "quantity": (None if position.quantity is None else str(position.quantity)),
                        "broker_quantity": (
                            None
                            if position.broker_quantity is None
                            else str(position.broker_quantity)
                        ),
                        "long_quantity": (
                            None if position.long_quantity is None else str(position.long_quantity)
                        ),
                        "short_quantity": (
                            None
                            if position.short_quantity is None
                            else str(position.short_quantity)
                        ),
                        "attributed_signed_quantity": (
                            None
                            if position.attributed_signed_quantity is None
                            else str(position.attributed_signed_quantity)
                        ),
                        "position_book_status": position.position_book_status,
                        "position_book_blocker_code": position.position_book_blocker_code,
                        "owner_intent_id": position.owner_intent_id,
                        "owner_strategy_scope": position.owner_strategy_scope,
                    }
                    for position in facts.positions
                )
            )
            if noncausal_blocker_active[0]:
                positions = []
                matched_route_count = 0
                for position in facts.positions:
                    if (
                        position.instrument == recovery._INSTRUMENT
                        and position.exchange == recovery._EXCHANGE
                    ):
                        matched_route_count += 1
                        assert position.quantity == Decimal("0")
                        assert position.broker_quantity == Decimal("0")
                        assert position.position_book_status == "UNKNOWN"
                        assert position.position_book_blocker_code == (
                            "INSTRUMENT_ORDER_UNRESOLVED"
                        )
                        position = replace(
                            position,
                            position_book_blocker_code="POSITION_GRID_ANCHOR_UNAVAILABLE",
                        )
                        noncausal_blocker_projections.append(
                            {
                                "instrument": position.instrument,
                                "exchange": position.exchange,
                                "quantity": str(position.quantity),
                                "broker_quantity": str(position.broker_quantity),
                                "position_book_status": position.position_book_status,
                                "position_book_blocker_code": (position.position_book_blocker_code),
                            }
                        )
                    positions.append(position)
                assert matched_route_count == 1
                facts = replace(facts, positions=tuple(positions))
            return original_terminal_reconcile(facts, *args, **kwargs)

        coordinator.reconcile_terminal_order_observations = capture_terminal_positions
        loop = _refresh_loop(api, store, broker, journal, coordinator, target, cerebro)
        parent_id = checkpoint["submit_intent_id"]
        cancel_id = checkpoint["cancel_intent_id"]
        noncausal_blocker_active[0] = True
        stage = "noncausal_unknown_book_blocker_rejected"
        try:
            loop.refresh_once()
        except _RUNNER.RunnerError:
            pass
        else:
            raise AssertionError("CANCEL recovery accepted a non-causal UNKNOWN Book blocker")
        finally:
            noncausal_blocker_active[0] = False

        assert noncausal_blocker_projections == [
            {
                "instrument": recovery._INSTRUMENT,
                "exchange": recovery._EXCHANGE,
                "quantity": "0",
                "broker_quantity": "0",
                "position_book_status": "UNKNOWN",
                "position_book_blocker_code": "POSITION_GRID_ANCHOR_UNAVAILABLE",
            }
        ]
        assert any(
            item[0] == "terminal_orders"
            and item[3] == "CANCEL_DISPATCHING_POSITION_BOOK_FLAT_MISMATCH"
            for item in loop.last_reconciliation_blockers
        )
        assert loop.last_receipt is None and loop.last_facts is None
        assert absence_calls == []
        assert journal.intent(parent_id).state == "KNOWN"
        assert journal.intent(cancel_id).state == "DISPATCHING"
        assert journal.instrument_resolution(parent_id) is None
        assert len(leases) == 1

        stage = "terminal_reconciliation_after_cas"
        try:
            loop.refresh_once()
        except _RUNNER.RunnerError:
            pass
        else:
            raise AssertionError("Store-conflicted dispatching CANCEL published facts")

        parent = journal.intent(parent_id)
        cancel = journal.intent(cancel_id)
        resolution = journal.instrument_resolution(parent_id)
        assert parent is not None and cancel is not None and resolution is not None
        parent_proof = journal.reconciliation(resolution.reconciliation_id)
        assert parent_proof is not None
        assert parent_proof.original_identity == parent.original_identity
        marker = parent_proof.provider_identity
        cancel_proof = journal.reconciliation(marker["cancel_reconciliation_id"])
        assert cancel_proof is not None
        assert cancel_proof.original_identity == cancel.original_identity
        cancel_marker = cancel_proof.provider_identity
        assert marker["cancel_recovery_kind"] == "dispatching_cancel"
        assert marker["parent_intent_id"] == parent_id
        assert marker["cancel_intent_id"] == cancel_id
        assert marker["parent_reconciliation_id"] == parent_proof.reconciliation_id
        assert marker["cancel_reconciliation_id"] == cancel_proof.reconciliation_id
        assert marker["observation_id"] == parent_proof.query_id == cancel_proof.query_id
        assert marker["query_set_id"] and marker["snapshot_id"]
        assert cancel_marker["evidence_kind"] == (
            "complete_orders_query_cancel_dispatching_terminal"
        )
        assert cancel_marker["parent_reconciliation_id"] == parent_proof.reconciliation_id
        assert cancel_marker["cancel_reconciliation_id"] == cancel_proof.reconciliation_id
        assert marker["order_ref"] == checkpoint["order_ref"]
        assert marker["order_sys_id"] == "sys-{}".format(checkpoint["order_ref"])
        assert marker["original_connection_generation"] == 1
        assert marker["original_front_id"] == 4
        assert marker["original_session_id"] == 7
        assert marker["original_order_ref"] == checkpoint["order_ref"]
        assert marker["front_id"] == 4
        assert marker["session_id"] == 7
        assert marker["connection_generation"] == 2
        assert marker["account_fingerprint"] == facts_helpers._ACCOUNT
        assert marker["trading_day"] == recovery._TRADING_DAY
        assert marker["instrument"] == recovery._INSTRUMENT
        assert marker["exchange"] == recovery._EXCHANGE
        assert marker["current_session"] == {
            "account_fingerprint": facts_helpers._ACCOUNT,
            "connection_generation": 2,
            "trading_day": recovery._TRADING_DAY,
            "front_id": 5,
            "session_id": 8,
            "read_only_ready": True,
        }
        assert marker["original_order_sys_id"] == checkpoint["original_identity"].get(
            "order_sys_id"
        )
        assert marker["terminal_status"] == "5"
        assert marker["terminal_state"] == "CANCELED"
        assert marker["volume_total_original"] == "1"
        assert marker["volume_traded"] == "0"
        assert marker["volume_total"] == "1"
        assert cancel.state == "KNOWN"
        assert cancel.dispatch_state is None
        assert cancel.provider_identity is None
        assert cancel.outcome_code is None
        assert _dispatch_result_json_is_null(journal, cancel_id)
        assert (
            journal.active_instrument_owner(recovery._ACCOUNT_SCOPE, recovery._INSTRUMENT) is None
        )
        candidate_page = _dispatching_cancel_candidate_page(journal)
        assert candidate_page.truncated is False
        assert len(candidate_page.items) == 1
        assert candidate_page.items[0].parent_intent_id == parent_id
        assert candidate_page.items[0].cancel_intent_id == cancel_id
        assert absence_calls == [dict(parent.original_identity)]
        assert len(absence_errors) == 1
        assert "LOCAL_ORDER_REFERENCE_PRESENT" in absence_errors[0], absence_errors[0]
        assert len(absence_outcomes) == 1
        assert absence_outcomes[0]["status"] == "ERROR"
        assert "LOCAL_ORDER_REFERENCE_PRESENT" in absence_outcomes[0]["error"]
        assert not tuple(
            item
            for item in journal.reconciliations(parent_id, limit=128)
            if item.outcome_code == "LOCAL_STORE_ABSENCE"
        )
        assert len(leases) == 2
        assert loop.last_receipt is None and loop.last_facts is None
        assert loop.last_error_code == "LIVE_CANCEL_DISPATCHING_STORE_ABSENCE_PENDING"
        assert broker.orders == {}
        assert api.native_calls == []

        # This fresh process has no in-memory retry hint. The subsequent test
        # process proves the durable selector is enough to keep the runner
        # under the terminal-recovery lease when a query omits the old order.
        result_queue.put(
            {
                "status": "OK",
                "pid": os.getpid(),
                "parent_intent_id": parent_id,
                "cancel_intent_id": cancel_id,
                "parent_reconciliation_id": parent_proof.reconciliation_id,
                "cancel_reconciliation_id": cancel_proof.reconciliation_id,
                "candidate_count": len(candidate_page.items),
                "lease_count": len(leases),
                "absence_calls": len(absence_calls),
                "publication_blocked": loop.last_receipt is None and loop.last_facts is None,
                "blocker": loop.last_error_code,
            }
        )
    except BaseException as error:
        parent_state = journal.intent(checkpoint["submit_intent_id"])
        cancel_state = journal.intent(checkpoint["cancel_intent_id"])
        resolution_state = journal.instrument_resolution(checkpoint["submit_intent_id"])
        loop_diagnostics = {}
        if "loop" in locals():
            loop_diagnostics = {
                "last_error_code": loop.last_error_code,
                "last_reconciliation_blockers": tuple(loop.last_reconciliation_blockers),
                "receipt_published": loop.last_receipt is not None,
                "facts_published": loop.last_facts is not None,
            }
        result_queue.put(
            {
                "status": "ERROR",
                "stage": stage,
                "error_type": type(error).__name__,
                "error_code": getattr(error, "code", None),
                "error_message": str(error)[:240],
                "error_traceback": traceback.format_exc(limit=8)[-2400:],
                "parent_state": parent_state.state if parent_state is not None else None,
                "cancel_state": cancel_state.state if cancel_state is not None else None,
                "resolution_exists": resolution_state is not None,
                "absence_call_count": len(absence_calls) if "absence_calls" in locals() else None,
                "lease_count": len(leases) if "leases" in locals() else None,
                "loop_diagnostics": loop_diagnostics,
                "position_projections": observed_position_projections,
            }
        )
    finally:
        journal.close()


def _spawned_pending_marker_blocks_then_acknowledges(
    journal_path, checkpoint, expected_cas_ids, result_queue
):
    now = datetime.now(timezone.utc)
    monkeypatch = pytest.MonkeyPatch()
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
    ) = recovery._durable_system(journal_path, now=now, monkeypatch=monkeypatch)
    stage = "fresh_pid_durable_pending_marker"
    try:
        _initialize_fake_sdk_pending_order_maps(api)
        crash_helpers._bind_sdk_session_identity(
            api, generation=3, front_id=6, session_id=9
        )
        api._connected = True
        api.query_rows["orders_result"] = []
        _seed_current_quote(api, store, broker, target, generation=3, sequence=31)
        absence_calls = []
        absence_outcomes = []
        original_absence = _capture_real_store_absence_check(store, absence_outcomes)

        def observe_real_store_check(*, original_identity, expected_session):
            try:
                result = original_absence(
                    original_identity=original_identity,
                    expected_session=expected_session,
                )
            except Exception as error:
                absence_calls.append(
                    (dict(original_identity), dict(expected_session), str(error)[:240])
                )
                raise
            absence_calls.append((dict(original_identity), dict(expected_session), result))
            return result

        store.registered_sim_assert_original_order_absent = observe_real_store_check
        leases = _track_recovery_leases(coordinator)
        loop = _refresh_loop(api, store, broker, journal, coordinator, target, cerebro)
        try:
            loop.refresh_once()
        except _RUNNER.RunnerError:
            pass
        else:
            raise AssertionError("pending marker without a terminal row published facts")
        assert loop.last_error_code == "LIVE_CANCEL_DISPATCHING_STORE_ABSENCE_PENDING"
        assert loop.last_receipt is None and loop.last_facts is None
        assert len(leases) == 1
        assert absence_calls == []
        pending = _dispatching_cancel_candidate_page(journal)
        assert not pending.truncated and len(pending.items) == 1

        # A second complete source query in this same fresh PID supplies the
        # exact old terminal row and current session 3/6/9.
        terminal_row = _fresh_terminal_row(checkpoint)
        api.query_rows["orders_result"] = [terminal_row]
        stage = "terminal_query_store_absence_ack"
        receipt = loop.refresh_once()
        assert receipt is loop.last_receipt
        assert loop.last_facts is not None
        assert receipt.query_set is not None
        assert len(leases) == 2
        assert len(absence_calls) == 1
        assert absence_calls[0][0] == dict(
            journal.intent(checkpoint["submit_intent_id"]).original_identity
        )
        assert absence_calls[0][1] == {
            "account_fingerprint": facts_helpers._ACCOUNT,
            "connection_generation": 3,
            "trading_day": recovery._TRADING_DAY,
            "front_id": 6,
            "session_id": 9,
            "read_only_ready": True,
        }
        assert absence_calls[0][2] == "ALREADY_ABSENT"
        assert absence_outcomes == [
            {
                "original_identity": absence_calls[0][0],
                "expected_session": absence_calls[0][1],
                "status": "OK",
                "result": "ALREADY_ABSENT",
            }
        ]

        parent_id = checkpoint["submit_intent_id"]
        cancel_id = checkpoint["cancel_intent_id"]
        parent = journal.intent(parent_id)
        cancel = journal.intent(cancel_id)
        resolution = journal.instrument_resolution(parent_id)
        assert parent is not None and cancel is not None and resolution is not None
        parent_cas_id, cancel_cas_id = expected_cas_ids
        parent_proof = journal.reconciliation(parent_cas_id)
        cancel_proof = journal.reconciliation(cancel_cas_id)
        assert parent_proof is not None and cancel_proof is not None
        acknowledgements = tuple(
            item
            for item in journal.reconciliations(parent_id, limit=128)
            if item.outcome_code == "LOCAL_STORE_ABSENCE"
        )
        assert len(acknowledgements) == 1
        ack = acknowledgements[0]
        evidence = ack.provider_identity
        current = evidence["current_session"]
        assert ack.state == "KNOWN"
        assert ack.query_id == evidence["acknowledgement_query_id"]
        assert ack.query_id != parent_proof.query_id
        assert ack.reconciliation_id not in {parent_cas_id, cancel_cas_id}
        assert ack.terminal_state is None and ack.position_snapshot_id is None
        assert ack.original_identity == parent.original_identity
        assert evidence["evidence_kind"] == "LOCAL_STORE_ABSENCE"
        assert evidence["cancel_recovery_kind"] == "dispatching_cancel_store_absence_ack"
        assert evidence["store_assertion"] == "ALREADY_ABSENT"
        assert evidence["parent_intent_id"] == parent_id
        assert evidence["cancel_intent_id"] == cancel_id
        assert evidence["parent_reconciliation_id"] == parent_cas_id
        assert evidence["cancel_reconciliation_id"] == cancel_cas_id
        assert evidence["cas_parent_reconciliation_id"] == parent_cas_id
        assert evidence["cas_cancel_reconciliation_id"] == cancel_cas_id
        assert evidence["acknowledgement_query_id"] == ack.query_id
        assert evidence["query_observation_id"] == loop.last_facts.terminal_orders[0].observation_id
        assert evidence["query_set_id"] == receipt.query_set.query_set_id
        assert evidence["snapshot_id"] == loop.last_facts.snapshot_id
        assert evidence["original_order_ref"] == parent.original_identity["order_ref"]
        assert evidence["instrument"] == recovery._INSTRUMENT
        assert evidence["exchange"] == recovery._EXCHANGE
        assert current == {
            "account_fingerprint": facts_helpers._ACCOUNT,
            "connection_generation": 3,
            "trading_day": recovery._TRADING_DAY,
            "front_id": 6,
            "session_id": 9,
            "read_only_ready": True,
        }
        assert cancel.state == "KNOWN"
        assert cancel.dispatch_state is None
        assert cancel.provider_identity is None
        assert cancel.outcome_code is None
        assert _dispatch_result_json_is_null(journal, cancel_id)
        assert journal.instrument_resolution(parent_id) == resolution
        assert not _dispatching_cancel_candidate_page(journal).items
        assert not broker.orders
        assert api.native_calls == []

        # A separately unresolved durable DISPATCHING claim admits a later
        # strict recovery refresh. Keep the old terminal row visible so the
        # coordinator must take its exact-ack replay path without repeating
        # the local Store absence assertion.
        unrelated_intent = _persist_unrelated_dispatching_intent(journal, coordinator)
        api.query_rows["orders_result"] = [terminal_row]
        stage = "post_ack_unrelated_refresh"
        try:
            unrelated_receipt = loop.refresh_once()
        except _RUNNER.RunnerError:
            unrelated_receipt = None
        assert unrelated_receipt is not None and unrelated_receipt is loop.last_receipt
        assert loop.last_facts is not None
        assert loop.last_error_code is None
        assert len(leases) == 3
        assert len(absence_calls) == 1
        assert not _dispatching_cancel_candidate_page(journal).items
        assert journal.intent(unrelated_intent.intent_id).state == "DISPATCHING"
        assert (
            len(
                tuple(
                    item
                    for item in journal.reconciliations(parent_id, limit=128)
                    if item.outcome_code == "LOCAL_STORE_ABSENCE"
                )
            )
            == 1
        )
        assert journal.reconciliation(ack.reconciliation_id) == ack

        result_queue.put(
            {
                "status": "OK",
                "pid": os.getpid(),
                "lease_count": len(leases),
                "absence_calls": len(absence_calls),
                "unrelated_intent_id": unrelated_intent.intent_id,
                "ack_reconciliation_id": ack.reconciliation_id,
                "parent_reconciliation_id": parent_cas_id,
                "cancel_reconciliation_id": cancel_cas_id,
                "ack_query_set_id": evidence["query_set_id"],
                "post_ack_refresh_entered_lease": len(leases) == 3,
                "post_ack_refresh_returned": unrelated_receipt is not None,
                "post_ack_error_code": loop.last_error_code,
                "store_absence_outcomes": absence_outcomes,
                "child_result_fields_null": cancel.dispatch_state is None
                and cancel.provider_identity is None
                and cancel.outcome_code is None
                and _dispatch_result_json_is_null(journal, cancel_id),
            }
        )
    except BaseException as error:
        absence_state = {}
        try:
            parent_id = checkpoint["submit_intent_id"]
            acknowledgements = tuple(
                item
                for item in journal.reconciliations(parent_id, limit=128)
                if item.outcome_code == "LOCAL_STORE_ABSENCE"
            )
            pending = _dispatching_cancel_candidate_page(journal)
            absence_state = {
                "store_connected": store._connected is True,
                "wrapper_connected": getattr(store._api, "_connected", None) is True,
                "absence_calls": absence_calls if "absence_calls" in locals() else None,
                "absence_outcomes": (absence_outcomes if "absence_outcomes" in locals() else None),
                "absence_ack_count": len(acknowledgements),
                "pending_candidate_count": len(pending.items),
                "pending_candidate_truncated": pending.truncated,
                "acknowledgement_rows": tuple(
                    {
                        "reconciliation_id": item.reconciliation_id,
                        "state": item.state,
                        "outcome_code": item.outcome_code,
                    }
                    for item in acknowledgements
                ),
            }
        except Exception as diagnostic_error:
            absence_state = {
                "diagnostic_error": "{}: {}".format(
                    type(diagnostic_error).__name__, str(diagnostic_error)[:160]
                )
            }
        result_queue.put(
            {
                "status": "ERROR",
                "stage": stage,
                "error_type": type(error).__name__,
                "error_code": getattr(error, "code", None),
                "error_message": str(error)[:240],
                "error_traceback": traceback.format_exc(limit=8)[-1800:],
                "absence_state": absence_state,
                "loop_diagnostics": (
                    {
                        "last_error_code": loop.last_error_code,
                        "last_reconciliation_blockers": tuple(loop.last_reconciliation_blockers),
                        "receipt_published": loop.last_receipt is not None,
                        "facts_published": loop.last_facts is not None,
                    }
                    if "loop" in locals()
                    else None
                ),
            }
        )
    finally:
        journal.close()


def test_fresh_process_cancel_dispatching_recovery_requires_store_absence_ack(tmp_path):
    """A terminal CANCEL query is durable before local absence is acknowledged."""

    journal_path = tmp_path / "cancel-dispatching-absence-ack.sqlite3"
    checkpoint_path = tmp_path / "cancel-dispatching-absence-ack.json"
    context = multiprocessing.get_context("spawn")
    pid1 = _spawn_exit(
        context,
        target=crash_helpers._spawned_cancel_dispatching_crash_worker,
        args=(str(journal_path), str(checkpoint_path)),
        expected_code=_EXIT_CODE,
    )
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["boundary"] == "cancel_dispatching"
    assert checkpoint["native_call_count"] == 2
    assert checkpoint["native_return_code_before_crash"] == 0

    pid2 = _spawn_result(
        context,
        target=_spawned_cancel_cas_then_local_order_conflict,
        args=(str(journal_path), checkpoint),
    )
    assert pid2["pid"] != pid1
    assert pid2["candidate_count"] == 1
    assert pid2["lease_count"] == 2
    assert pid2["absence_calls"] == 1
    assert pid2["publication_blocked"] is True
    assert pid2["blocker"] == "LIVE_CANCEL_DISPATCHING_STORE_ABSENCE_PENDING"

    pid3 = _spawn_result(
        context,
        target=_spawned_pending_marker_blocks_then_acknowledges,
        args=(
            str(journal_path),
            checkpoint,
            (pid2["parent_reconciliation_id"], pid2["cancel_reconciliation_id"]),
        ),
    )
    assert pid3["pid"] not in {pid1, pid2["pid"]}
    assert pid3["lease_count"] == 3
    assert pid3["absence_calls"] == 1
    assert pid3["parent_reconciliation_id"] == pid2["parent_reconciliation_id"]
    assert pid3["cancel_reconciliation_id"] == pid2["cancel_reconciliation_id"]
    assert pid3["post_ack_refresh_entered_lease"] is True
    assert pid3["post_ack_refresh_returned"] is True
    assert pid3["post_ack_error_code"] is None
    assert pid3["child_result_fields_null"] is True


def _trade_row(trade_id, order_ref, order_sys_id, *, when, quantity, offset_flag):
    signed_quantity = Decimal(str(quantity))
    signed_quantity = signed_quantity if offset_flag == "0" else -signed_quantity
    return facts_helpers._query_trade_for_fill(
        trade_id=trade_id,
        order_ref=str(order_ref),
        order_sys_id=order_sys_id,
        filled_at=when,
        quantity=signed_quantity,
        price="100",
        offset_flag=offset_flag,
    )


def _order_row(
    order_ref,
    *,
    status,
    side,
    effect,
    original,
    traded,
    remaining,
    front_id=4,
    session_id=7,
    offset_flag=None,
):
    if offset_flag is None:
        offset_flag = "0" if effect == "OPEN" else "1"
    return {
        "OrderRef": str(order_ref),
        "OrderSysID": "sys-{}".format(order_ref),
        "InstrumentID": recovery._INSTRUMENT,
        "ExchangeID": recovery._EXCHANGE,
        "OrderStatus": status,
        "Direction": "0" if side == "BUY" else "1",
        "CombOffsetFlag": offset_flag,
        "FrontID": front_id,
        "SessionID": session_id,
        "TradingDay": recovery._TRADING_DAY,
        "VolumeTotalOriginal": str(original),
        "VolumeTraded": str(traded),
        "VolumeTotal": str(remaining),
    }


def _sized_open_scope(coordinator, strategy, facts, *, quantity, batch_id):
    close_time = facts.available_at - timedelta(milliseconds=2)
    batch = LiveCohortBatch(
        batch_id=batch_id,
        cohort_id="rb-cohort",
        calendar_id="simnow-common-minutes-v1",
        calendar_version="v1",
        epoch_id=1,
        slot_index=0,
        close_time=close_time,
        available_at=close_time + timedelta(milliseconds=1),
    )
    snapshot = LiveFactorSnapshot(
        plan_id="alpha003-cancel-dispatching-test",
        cohort_id=batch.cohort_id,
        calendar_id=batch.calendar_id,
        calendar_version=batch.calendar_version,
        frequency="1min",
        epoch_id=batch.epoch_id,
        batch_id=batch.batch_id,
        close_time=batch.close_time,
        available_at=batch.available_at,
        batch_complete=True,
        readiness=LiveFactorReadiness.LIVE_READY,
        readiness_reasons=(),
        factors={},
    )
    intent_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument=recovery._INSTRUMENT,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    economics = {
        "instrument": recovery._INSTRUMENT,
        "exchange": recovery._EXCHANGE,
        "side": "BUY",
        "position_effect": "OPEN",
        "quantity": str(quantity),
        "limit_price": "100",
        "offset": "open",
        "factor_stop_price": "95",
        "risk_policy_id": "a003-risk-v1",
        "risk_policy": {"stop_loss_ticks": 5, "max_loss_per_position": "25"},
        "entry_grid_ordinal": 1,
        "batch_id": batch_id,
        "price": "100",
    }
    key = ExecutionDecisionKey(
        account_scope=recovery._ACCOUNT_SCOPE,
        strategy_scope=recovery._STRATEGY_SCOPE,
        logical_run_id="run-1",
        cohort_id=batch.cohort_id,
        close_time=close_time.isoformat().replace("+00:00", "Z"),
        decision_kind="ALPHA003_GRID",
    )
    return coordinator.decision_scope(
        owner=strategy,
        key=key,
        economic_payload={"intent_economics": (economics,)},
        intent_keys=(intent_key,),
        batch=batch,
        snapshot=snapshot,
        execution_facts=facts,
        inputs_complete=True,
        expected_run_order_intents_used=coordinator.run_order_count(),
        remaining_exit_intent_reserve=0,
    )


def _close_order_scope(
    coordinator,
    strategy,
    facts,
    *,
    quantity,
    owner_intent_id,
    batch_id,
    offset,
):
    close_time = facts.available_at
    intent_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument=recovery._INSTRUMENT,
        side="SELL",
        position_effect="CLOSE",
        leg=0,
    )
    economics = {
        "instrument": recovery._INSTRUMENT,
        "exchange": recovery._EXCHANGE,
        "side": "SELL",
        "position_effect": "CLOSE",
        "quantity": str(quantity),
        "limit_price": "100",
        "offset": offset,
        "owner_intent_id": owner_intent_id,
        "owner_position_effect": "OPEN",
        "owner_side": "BUY",
        "entry_grid_ordinal": 1,
        "batch_id": batch_id,
    }
    key = ExecutionDecisionKey(
        account_scope=recovery._ACCOUNT_SCOPE,
        strategy_scope=recovery._STRATEGY_SCOPE,
        logical_run_id="run-1",
        cohort_id="rb-cohort",
        close_time=close_time.isoformat().replace("+00:00", "Z"),
        decision_kind="ALPHA003_RISK_REDUCTION",
    )
    return coordinator.risk_decision_scope(
        owner=strategy,
        key=key,
        economic_payload={"intent_economics": (economics,)},
        intent_keys=(intent_key,),
        batch=None,
        execution_facts=facts,
        inputs_complete=True,
        expected_run_order_intents_used=coordinator.run_order_count(),
        remaining_exit_intent_reserve=0,
    )


def _drain_provider_callbacks(cerebro, strategy):
    cerebro._brokernotify()
    strategy._notify()


def _capture_submitted_order_offsets(api):
    """Observe order offset at the existing fake provider submission boundary."""

    observed = []
    provider_submit = api.submit_order

    def capture(payload):
        result = provider_submit(payload)
        observed.append(
            (
                str(payload["order_ref"]),
                str(payload.get("offset") or "open").lower(),
            )
        )
        return result

    api.submit_order = capture
    return observed


def _assert_submitted_order_offsets_match_native_refs(api, observed, expected):
    assert observed == expected
    insert_calls = tuple(call for call in api.native_calls if call[0] == "insert")
    assert tuple(str(call[3]) for call in insert_calls) == tuple(ref for ref, _ in expected)
    assert all(call[1:3] == (recovery._INSTRUMENT, recovery._EXCHANGE) for call in insert_calls)


def _assign_fake_provider_order_sys_id(api, order_ref):
    identity = api._provider_orders[str(order_ref)]
    native_sys_id = "sys-{}".format(order_ref)
    if identity["order_sys_id"] not in (None, native_sys_id):
        raise AssertionError("fake provider order was assigned a conflicting native ID")
    identity["order_sys_id"] = native_sys_id
    return native_sys_id


def _emit_order_callback_with_native_sys_id(
    api, cerebro, strategy, broker, order_ref, *, order, status, filled, remaining
):
    """Deliver the fake CTP order payload through the production callback path."""

    identity = api._provider_orders[str(order_ref)]
    native_sys_id = _assign_fake_provider_order_sys_id(api, order_ref)
    offset_flag = {
        "open": "0",
        "close": "1",
        "close_today": "3",
        "close_yesterday": "4",
    }.get(identity["offset"])
    assert offset_flag is not None, identity
    update = {
        "kind": "order",
        "order_ref": str(order_ref),
        "data_name": identity["instrument_id"],
        "instrument": identity["instrument_id"],
        "exchange_id": identity["exchange_id"],
        "front_id": identity["front_id"],
        "session_id": identity["session_id"],
        "status": status,
        "side": identity["side"],
        "offset": identity["offset"],
        "price": 100.0,
        "size": identity["size"],
        "filled": filled,
        "remaining": remaining,
        "details": {
            "OrderRef": str(order_ref),
            "OrderSysID": native_sys_id,
            "InstrumentID": identity["instrument_id"],
            "ExchangeID": identity["exchange_id"],
            "FrontID": identity["front_id"],
            "SessionID": identity["session_id"],
            "OrderStatus": status,
            "Direction": "0" if identity["side"] == "buy" else "1",
            "CombOffsetFlag": offset_flag,
            "LimitPrice": "100",
            "VolumeTotalOriginal": str(identity["size"]),
            "VolumeTraded": str(filled),
            "VolumeTotal": str(remaining),
        },
    }
    api._order_updates.append(update)
    _drain_provider_callbacks(cerebro, strategy)
    assert order.info.get("ctp_order_ref") == str(order_ref)
    assert order.info.get("registered_sim_ctp_order_sys_id") == native_sys_id
    assert order.info.get("registered_sim_ctp_order_sys_id_source") == "ctp_order_callback"

    matching_orders = tuple(
        item
        for item in broker.execution_order_snapshot()
        if item.external_order_ref == str(order_ref)
    )
    if status == "completed":
        # Completed orders are intentionally omitted from the alive-only
        # execution snapshot. Their original Broker order carries the callback
        # lineage and terminal status for this assertion. A full trade may
        # already have retired the lookup mapping, so this terminal callback
        # must not be relied on to establish the native ID.
        assert order.status == order.Completed
        assert not order.alive()
        assert matching_orders == ()
        return native_sys_id

    assert status in {"accepted", "partial"}
    if status == "accepted":
        assert order.status == order.Accepted
    else:
        assert order.status == order.Partial
    assert order.alive()
    assert len(matching_orders) == 1, matching_orders
    local_order = matching_orders[0]
    assert local_order.instrument_id == identity["instrument_id"]
    assert local_order.exchange_id == identity["exchange_id"]
    assert local_order.side == identity["side"].upper()
    assert local_order.position_effect == ("OPEN" if identity["offset"] == "open" else "CLOSE")
    assert local_order.remaining_quantity == Decimal(str(remaining))
    assert local_order.order_sys_id == native_sys_id, local_order
    assert local_order.front_id == identity["front_id"]
    assert local_order.session_id == identity["session_id"]
    return native_sys_id


def _emit_provider_close_today_trade_callback(api, order_ref, *, trade_id, quantity, when):
    """Queue one faithful close-today CTP trade event on the fake SDK leaf."""

    identity = api._provider_orders[str(order_ref)]
    assert identity["offset"] == "close_today", identity
    assert identity["side"] == "sell", identity
    native_sys_id = _assign_fake_provider_order_sys_id(api, order_ref)
    details = {
        "OrderRef": str(order_ref),
        "OrderSysID": native_sys_id,
        "TradeID": trade_id,
        "InstrumentID": identity["instrument_id"],
        "ExchangeID": identity["exchange_id"],
        "Direction": "1",
        "OffsetFlag": "3",
        "Volume": str(quantity),
        "Price": "100",
        "TradingDay": facts_helpers._TRADING_DAY,
        "TradeTime": when.strftime("%H:%M:%S"),
        "TradeDate": when.strftime("%Y%m%d"),
    }
    api._order_updates.append(
        {
            "kind": "trade",
            "trade_id": trade_id,
            "order_ref": str(order_ref),
            "data_name": identity["instrument_id"],
            "instrument": identity["instrument_id"],
            "exchange_id": identity["exchange_id"],
            "side": identity["side"],
            "offset": "close_today",
            "price": 100.0,
            "size": quantity,
            "timestamp": when.isoformat(),
            "details": details,
        }
    )


def _assert_provider_trade_callback(
    api,
    *,
    order_ref,
    trade_id,
    order_sys_id,
    side,
    offset,
    offset_flag,
    quantity,
    fee,
    when,
):
    callback = api._order_updates[-1]
    details = callback["details"]
    expected_direction = "0" if side == "BUY" else "1"
    assert callback["kind"] == "trade"
    assert callback["trade_id"] == trade_id
    assert callback["order_ref"] == str(order_ref)
    assert callback["data_name"] == callback["instrument"] == recovery._INSTRUMENT
    assert callback["exchange_id"] == recovery._EXCHANGE
    assert callback["side"] == side.lower()
    assert callback["offset"] == offset
    assert callback["timestamp"] == when.isoformat()
    assert Decimal(str(callback["size"])) == Decimal(str(quantity))
    assert callback["price"] == 100.0
    assert callback["fee"] == fee
    assert details["OrderRef"] == str(order_ref)
    assert details["OrderSysID"] == order_sys_id
    assert details["TradeID"] == trade_id
    assert details["InstrumentID"] == recovery._INSTRUMENT
    assert details["ExchangeID"] == recovery._EXCHANGE
    assert details["Direction"] == expected_direction
    assert details["OffsetFlag"] == offset_flag
    assert Decimal(details["Volume"]) == Decimal(str(quantity))
    assert Decimal(details["Price"]) == Decimal("100")
    assert details["TradingDay"] == recovery._TRADING_DAY
    assert details["TradeDate"] == when.strftime("%Y%m%d")
    assert details["TradeTime"] == when.strftime("%H:%M:%S")
    assert details["Fee"] == fee


def _assert_query_trade_row(
    row,
    *,
    order_ref,
    trade_id,
    order_sys_id,
    side,
    offset_flag,
    quantity,
    when,
):
    ctp_time = when.astimezone(_CTP_TIMEZONE)
    assert row["TradeID"] == trade_id
    assert row["OrderRef"] == str(order_ref)
    assert row["OrderSysID"] == order_sys_id
    assert row["InstrumentID"] == recovery._INSTRUMENT
    assert row["ExchangeID"] == recovery._EXCHANGE
    assert row["Direction"] == ("0" if side == "BUY" else "1")
    assert row["OffsetFlag"] == offset_flag
    assert Decimal(row["Volume"]) == Decimal(str(quantity))
    assert Decimal(row["Price"]) == Decimal("100")
    assert row["TradeDate"] == ctp_time.strftime("%Y%m%d")
    assert row["TradeTime"] == ctp_time.strftime("%H:%M:%S.%f")
    assert row["TradingDay"] == recovery._TRADING_DAY


def _add_fee_to_last_trade_callback(api, fee):
    callback = api._order_updates[-1]
    assert callback["kind"] == "trade"
    callback["fee"] = fee
    callback["details"]["Fee"] = fee


def _set_query_rows(api, *, orders, trades, positions):
    api.query_rows = facts_helpers._query_rows(
        orders=tuple(orders),
        trades=tuple(trades),
        positions=tuple(positions),
    )


def _book_snapshot(coordinator, facts, broker, data):
    position = facts.positions[0]
    return coordinator.position_book.snapshot(
        account_scope=recovery._ACCOUNT_SCOPE,
        strategy_scope=recovery._STRATEGY_SCOPE,
        instrument=recovery._INSTRUMENT,
        exchange=recovery._EXCHANGE,
        broker_quantity=broker.execution_position_snapshot(data).quantity,
        long_quantity=position.long_quantity,
        short_quantity=position.short_quantity,
        snapshot_id=facts.snapshot_id,
        available_at=facts.available_at,
    )


def _risk_reduction_projection(facts):
    """Keep a finite, source-backed diagnostic for a rejected CLOSE fixture."""

    return {
        "risk_reduction_ready": facts.risk_reduction_ready,
        "blockers": facts.blockers,
        "aggregate_write_blockers": facts.aggregate_write_blockers,
        "risk_reduction_blockers": facts.risk_reduction_blockers,
        "snapshot_id": facts.snapshot_id,
        "query_set_id": facts.query_set_id,
        "available_at": facts.available_at,
        "query_provenance": tuple(
            (
                item.family,
                item.target_id,
                item.request_id,
                item.query_complete,
                item.scope_complete,
                item.started_at,
                item.completed_at,
            )
            for item in facts.query_provenance
        ),
        "positions": tuple(
            {
                "target_id": item.target_id,
                "quantity": item.quantity,
                "broker_quantity": item.broker_quantity,
                "attributed_signed_quantity": item.attributed_signed_quantity,
                "owner_strategy_scope": item.owner_strategy_scope,
                "owner_intent_id": item.owner_intent_id,
                "position_book_status": item.position_book_status,
                "position_book_blocker_code": item.position_book_blocker_code,
                "dated_inventory_rows": tuple(
                    (row.position_date, row.position, row.source_row_id, row.blockers)
                    for row in item.dated_inventory_rows
                ),
            }
            for item in facts.positions
        ),
        "quotes": tuple(
            (
                item.instrument,
                item.quality,
                item.event_time,
                item.available_at,
                item.generation,
                item.sequence,
            )
            for item in facts.quotes
        ),
        "instruments": tuple(
            (
                item.target_id,
                item.trading_permitted,
                item.multiplier,
                item.tick_size,
                item.lower_limit,
                item.upper_limit,
            )
            for item in facts.instruments
        ),
        "route_eligibilities": tuple(
            (
                item.target_id,
                item.eligible,
                item.reason_codes,
                item.connection_generation,
                item.trading_day,
            )
            for item in facts.route_eligibilities
        ),
        "dated_close_legs": tuple(
            (
                item.target_id,
                item.position_date,
                item.ready,
                item.blockers,
                item.provider_quantity,
                item.owned_quantity,
                item.available_quantity,
                item.owner_strategy_scope,
                item.owner_intent_id,
                item.source_row_ids,
                item.opening_execution_ids,
            )
            for item in facts.dated_close_legs
        ),
    }


def _cancel_admission_projection(api, broker, facts, order_ref):
    """Capture bounded public projections before the real cancel admission gate."""

    from backtrader.stores.factor_execution_facts import (
        _exact_owned_cancel_join_covers_book_blocker,
    )

    def record_fields(value):
        if value is None:
            return None
        return {item.name: getattr(value, item.name) for item in fields(value)}

    local_orders = tuple(broker.execution_order_snapshot())
    matching_local_orders = tuple(
        item for item in local_orders if item.external_order_ref == str(order_ref)
    )
    order_rows = tuple(api.query_rows.get("orders_result", ()))
    active_statuses = {"1", "2", "3", "a"}
    matching_ctp_rows = tuple(
        {
            name: row.get(name)
            for name in (
                "OrderRef",
                "OrderSysID",
                "InstrumentID",
                "ExchangeID",
                "OrderStatus",
                "Direction",
                "CombOffsetFlag",
                "FrontID",
                "SessionID",
                "TradingDay",
                "VolumeTotalOriginal",
                "VolumeTraded",
                "VolumeTotal",
            )
        }
        for row in order_rows
        if str(row.get("OrderRef")) == str(order_ref)
        and str(row.get("OrderStatus", "")).strip().lower() in active_statuses
    )

    def bounded_records(values, *, limit=16):
        values = tuple(values)
        return {
            "items": tuple(record_fields(item) for item in values[:limit]),
            "count": len(values),
            "truncated": len(values) > limit,
        }

    blockers = tuple(facts.blockers)
    aggregate_blockers = tuple(facts.aggregate_write_blockers)
    cancel_blockers = tuple(facts.order_cancel_blockers)
    return {
        "order_ref": str(order_ref),
        "snapshot_id": facts.snapshot_id,
        "query_set_id": facts.query_set_id,
        "available_at": facts.available_at,
        "order_cancel_ready": facts.order_cancel_ready,
        "order_cancel_blockers": cancel_blockers[:128],
        "order_cancel_blockers_truncated": len(cancel_blockers) > 128,
        "aggregate_write_blockers": aggregate_blockers[:128],
        "aggregate_write_blockers_truncated": len(aggregate_blockers) > 128,
        "blockers": blockers[:128],
        "blockers_truncated": len(blockers) > 128,
        "exact_owned_cancel_join_covers_book_blocker": (
            _exact_owned_cancel_join_covers_book_blocker(facts)
        ),
        "working_orders": bounded_records(facts.working_orders),
        "positions": tuple(
            {
                name: getattr(position, name)
                for name in (
                    "target_id",
                    "instrument",
                    "exchange",
                    "quantity",
                    "broker_quantity",
                    "attributed_signed_quantity",
                    "owner_strategy_scope",
                    "owner_intent_id",
                    "position_book_status",
                    "position_book_blocker_code",
                    "snapshot_id",
                    "available_at",
                    "long_quantity",
                    "short_quantity",
                    "opening_fee_total",
                    "opening_fees_known",
                )
            }
            for position in tuple(facts.positions)[:16]
        ),
        "positions_count": len(facts.positions),
        "positions_truncated": len(facts.positions) > 16,
        "route_eligibilities": bounded_records(facts.route_eligibilities),
        "account": record_fields(facts.account),
        "query_provenance": bounded_records(facts.query_provenance, limit=16),
        "broker_order_snapshot": bounded_records(local_orders),
        "matching_broker_orders": bounded_records(matching_local_orders),
        "matching_ctp_active_rows": matching_ctp_rows[:16],
        "matching_ctp_active_rows_truncated": len(matching_ctp_rows) > 16,
    }


def _project_risk_facts_after_completed_query(
    api,
    store,
    broker,
    target,
    query_set,
    *,
    generation,
    sequence,
):
    """Consume a post-query quote and reproject the same completed query set."""

    completed_at = query_set.completed_at_utc
    event_time = _utc_now_not_before(completed_at)
    received_at = _utc_now_not_before(event_time)
    api.tick = facts_helpers._quote(
        event_time=event_time,
        received_at=received_at,
        generation=generation,
        sequence=sequence,
        trading_day=recovery._TRADING_DAY,
    )
    consumed = facts_helpers._consume_quote(store)
    assert consumed is not None
    projection_now = _utc_now_not_before(received_at)
    assert completed_at <= event_time <= received_at <= projection_now
    assert consumed.received_wall_time <= projection_now.timestamp()
    return facts_helpers.project_factor_execution_facts(
        store,
        broker,
        targets=(target,),
        account_scope=recovery._ACCOUNT_SCOPE,
        strategy_scope=recovery._STRATEGY_SCOPE,
        now=projection_now,
        quote_max_age=timedelta(seconds=60),
        max_query_age=timedelta(seconds=60),
        query_set=query_set,
    )


def _utc_now_not_before(target):
    """Wait briefly for the real UTC clock to reach an observed event time."""

    deadline = time.monotonic() + 1.0
    while True:
        observed = datetime.now(timezone.utc)
        if observed >= target:
            return observed
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError("UTC wall clock did not reach the observed query time")
        time.sleep(min(0.001, remaining))


def _spawned_partial_close_cancel_crash(journal_path, checkpoint_path):
    now = datetime.now(timezone.utc)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        recovery,
        "_arm_template",
        crash_helpers._canonical_sdk_arm_template,
    )
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
    ) = recovery._durable_system(journal_path, now=now, bars=3, monkeypatch=monkeypatch)
    submitted_offsets = _capture_submitted_order_offsets(api)
    try:
        facts = recovery._initial_open_facts(api, store, broker, target, now=now)
        # This worker reports fills after its initial complete snapshot. Keep
        # subsequent fake query receipt times tied to their actual calls so
        # those source rows are not projected as future trades.
        api._use_observed_query_clock = True
        open_scope = _sized_open_scope(
            coordinator,
            strategy,
            facts,
            quantity=2,
            batch_id="ac50-22-open-two-before-partial-close",
        )
        with open_scope:
            open_order = strategy.buy(
                data=data,
                size=2,
                price=100,
                exectype=Order.Limit,
                instrument_id=recovery._INSTRUMENT,
                exchange_id=recovery._EXCHANGE,
                factor_position_effect="OPEN",
                factor_strategy_scope=recovery._STRATEGY_SCOPE,
                offset="open",
            )
        open_intent_id = open_order.info["factor_intent_id"]
        open_ref = open_order.info["external_order_ref"]
        _assert_submitted_order_offsets_match_native_refs(
            api,
            submitted_offsets,
            [(str(open_ref), "open")],
        )
        open_sys_id = _assign_fake_provider_order_sys_id(api, open_ref)
        assert (
            _emit_order_callback_with_native_sys_id(
                api,
                cerebro,
                strategy,
                broker,
                open_ref,
                order=open_order,
                status="accepted",
                filled=0,
                remaining=2,
            )
            == open_sys_id
        )
        # The provider fill occurs after the OPEN decision grid was recorded.
        # CTP TradeDate may be the next calendar date while TradingDay remains
        # the prior session's fixed fixture day.
        open_time = _ctp_trade_time_after(facts.available_at)
        api.emit_provider_trade_callback(
            open_ref,
            trade_id="ac50-22-open-fill",
            quantity=2,
            offset="open",
            when=open_time,
        )
        _add_fee_to_last_trade_callback(api, "0.12")
        _assert_provider_trade_callback(
            api,
            order_ref=open_ref,
            trade_id="ac50-22-open-fill",
            order_sys_id=open_sys_id,
            side="BUY",
            offset="open",
            offset_flag="0",
            quantity=2,
            fee="0.12",
            when=open_time,
        )
        assert (
            _emit_order_callback_with_native_sys_id(
                api,
                cerebro,
                strategy,
                broker,
                open_ref,
                order=open_order,
                status="completed",
                filled=2,
                remaining=0,
            )
            == open_sys_id
        )
        assert broker.execution_position_snapshot(data).quantity == Decimal("2")
        open_trade = _trade_row(
            "ac50-22-open-fill",
            open_ref,
            open_sys_id,
            when=open_time,
            quantity=2,
            offset_flag="0",
        )
        _assert_query_trade_row(
            open_trade,
            order_ref=open_ref,
            trade_id="ac50-22-open-fill",
            order_sys_id=open_sys_id,
            side="BUY",
            offset_flag="0",
            quantity=2,
            when=open_time,
        )
        open_order_row = _order_row(
            open_ref,
            status="0",
            side="BUY",
            effect="OPEN",
            original=2,
            traded=2,
            remaining=0,
        )
        assert open_trade["OrderSysID"] == open_order_row["OrderSysID"] == open_sys_id
        assert open_trade["OffsetFlag"] == open_order_row["CombOffsetFlag"] == "0"
        _set_query_rows(
            api,
            orders=(open_order_row,),
            trades=(open_trade,),
            positions=(facts_helpers._dated_position_row("2"),),
        )
        loop = _refresh_loop(api, store, broker, journal, coordinator, target, cerebro)
        assert loop.refresh_once() is loop.last_receipt
        assert loop.last_facts is not None
        open_book = _book_snapshot(coordinator, loop.last_facts, broker, data)
        assert open_book.status == "MATCHED", open_book
        assert open_book.owner_intent_id == open_intent_id
        assert open_book.signed_quantity == Decimal("2")
        assert open_book.opening_fee_total == Decimal("0.12")
        assert open_book.opening_fees_known is True

        close_facts = _project_risk_facts_after_completed_query(
            api,
            store,
            broker,
            target,
            loop.last_receipt.query_set,
            generation=1,
            sequence=2,
        )
        assert close_facts.risk_reduction_ready is True, _risk_reduction_projection(close_facts)
        close_book = _book_snapshot(coordinator, close_facts, broker, data)
        assert close_book.status == "MATCHED", close_book
        assert close_book.owner_intent_id == open_intent_id
        assert close_book.signed_quantity == Decimal("2")
        assert close_book.opening_fee_total == Decimal("0.12")
        assert close_book.opening_fees_known is True

        close_scope = _close_order_scope(
            coordinator,
            strategy,
            close_facts,
            quantity=2,
            owner_intent_id=open_intent_id,
            batch_id="ac50-22-partial-close-owner-open",
            offset="close_today",
        )
        with close_scope:
            close_order = strategy.sell(
                data=data,
                size=2,
                price=100,
                exectype=Order.Limit,
                instrument_id=recovery._INSTRUMENT,
                exchange_id=recovery._EXCHANGE,
                factor_position_effect="CLOSE",
                factor_strategy_scope=recovery._STRATEGY_SCOPE,
                factor_owner_side="BUY",
                factor_owner_position_effect="OPEN",
                offset="close_today",
            )
        close_intent_id = close_order.info["factor_intent_id"]
        close_ref = close_order.info["external_order_ref"]
        _assert_submitted_order_offsets_match_native_refs(
            api,
            submitted_offsets,
            [(str(open_ref), "open"), (str(close_ref), "close_today")],
        )
        assert api._provider_orders[str(close_ref)]["offset"] == "close_today"
        close_sys_id = _assign_fake_provider_order_sys_id(api, close_ref)
        assert (
            _emit_order_callback_with_native_sys_id(
                api,
                cerebro,
                strategy,
                broker,
                close_ref,
                order=close_order,
                status="accepted",
                filled=0,
                remaining=2,
            )
            == close_sys_id
        )
        close_time = _ctp_trade_time_after(loop.last_facts.available_at)
        _emit_provider_close_today_trade_callback(
            api,
            close_ref,
            trade_id="ac50-22-partial-close-fill",
            quantity=1,
            when=close_time,
        )
        _add_fee_to_last_trade_callback(api, "0.25")
        _assert_provider_trade_callback(
            api,
            order_ref=close_ref,
            trade_id="ac50-22-partial-close-fill",
            order_sys_id=close_sys_id,
            side="SELL",
            offset="close_today",
            offset_flag="3",
            quantity=1,
            fee="0.25",
            when=close_time,
        )
        assert (
            _emit_order_callback_with_native_sys_id(
                api,
                cerebro,
                strategy,
                broker,
                close_ref,
                order=close_order,
                status="partial",
                filled=1,
                remaining=1,
            )
            == close_sys_id
        )
        assert broker.execution_position_snapshot(data).quantity == Decimal("1")
        close_trade = _trade_row(
            "ac50-22-partial-close-fill",
            close_ref,
            close_sys_id,
            when=close_time,
            quantity=1,
            offset_flag="3",
        )
        _assert_query_trade_row(
            close_trade,
            order_ref=close_ref,
            trade_id="ac50-22-partial-close-fill",
            order_sys_id=close_sys_id,
            side="SELL",
            offset_flag="3",
            quantity=1,
            when=close_time,
        )
        active_close_row = _order_row(
            close_ref,
            status="1",
            side="SELL",
            effect="CLOSE",
            original=2,
            traded=1,
            remaining=1,
            offset_flag="3",
        )
        assert active_close_row["OrderSysID"] == close_sys_id
        assert active_close_row["CombOffsetFlag"] == "3"
        assert close_trade["OffsetFlag"] == "3"
        _set_query_rows(
            api,
            orders=(open_order_row, active_close_row),
            trades=(open_trade, close_trade),
            positions=(facts_helpers._dated_position_row("1"),),
        )
        assert loop.refresh_once() is loop.last_receipt
        assert loop.last_facts is not None
        remaining_book = _book_snapshot(coordinator, loop.last_facts, broker, data)
        # The partial CLOSE remains live until the following cancel. Its
        # instrument reservation intentionally keeps the Book unresolved,
        # while the exact OPEN lot attribution and remaining economics remain
        # visible for the terminal cancel reconciliation.
        assert remaining_book.status == "UNKNOWN", remaining_book
        assert remaining_book.blocker_code == "INSTRUMENT_ORDER_UNRESOLVED"
        assert remaining_book.owner_intent_id == open_intent_id
        assert remaining_book.owner_strategy_scope == recovery._STRATEGY_SCOPE
        assert remaining_book.signed_quantity == Decimal("1")
        assert remaining_book.attributed_signed_quantity == Decimal("1")
        assert remaining_book.opening_fee_total == Decimal("0.12")
        assert remaining_book.opening_fees_known is True

        cancel_key = ExecutionIntentKey(
            action="CANCEL",
            instrument=recovery._INSTRUMENT,
            side="SELL",
            position_effect="CLOSE",
            leg=0,
        )
        cancel_economics = {
            "instrument": recovery._INSTRUMENT,
            "exchange": recovery._EXCHANGE,
            "side": "SELL",
            "position_effect": "CLOSE",
            "offset": "close_today",
            "owner_intent_id": close_intent_id,
            "reason": "AC50-22 partial CLOSE survives cancel-dispatch crash",
        }
        cancel_scope = coordinator.risk_decision_scope(
            owner=strategy,
            key=ExecutionDecisionKey(
                account_scope=recovery._ACCOUNT_SCOPE,
                strategy_scope=recovery._STRATEGY_SCOPE,
                logical_run_id="run-1",
                cohort_id="rb-cohort",
                close_time=loop.last_facts.available_at.isoformat().replace("+00:00", "Z"),
                decision_kind="ALPHA003_RISK_REDUCTION",
            ),
            economic_payload={"intent_economics": (cancel_economics,)},
            intent_keys=(cancel_key,),
            batch=None,
            execution_facts=loop.last_facts,
            inputs_complete=True,
            expected_run_order_intents_used=coordinator.run_order_count(),
            remaining_exit_intent_reserve=0,
        )
        def crash_after_native_cancel(field, request_id):
            del field, request_id
            active_owner = journal.active_instrument_owner(
                recovery._ACCOUNT_SCOPE,
                recovery._INSTRUMENT,
            )
            assert active_owner is not None
            cancel_intent_id = active_owner.cancel_intent_id
            cancel_intent = journal.intent(cancel_intent_id)
            assert cancel_intent is not None
            assert cancel_intent.state == "DISPATCHING"
            assert cancel_intent.dispatch_state is None
            crash_helpers._write_checkpoint(
                checkpoint_path,
                {
                    "boundary": "cancel_dispatching_partial_close",
                    "pid": os.getpid(),
                    "submit_intent_id": close_intent_id,
                    "cancel_intent_id": cancel_intent_id,
                    "open_intent_id": open_intent_id,
                    "order_ref": close_ref,
                    "open_order_ref": open_ref,
                    "original_identity": dict(journal.intent(close_intent_id).original_identity),
                    "cancel_original_identity": dict(cancel_intent.original_identity),
                    "open_trade_id": "ac50-22-open-fill",
                    "close_trade_id": "ac50-22-partial-close-fill",
                    # The fake native leaf always accepts; this records the
                    # last provider return code before the process exits.
                    "native_return_code_before_crash": 0,
                    "native_call_count": len(api.native_calls),
                    "open_time": open_time.isoformat(),
                    "close_time": close_time.isoformat(),
                },
            )
            os._exit(_EXIT_CODE)

        native_api = api.trader_client._api
        assert native_api.order_action_hook is None
        native_api.order_action_hook = crash_after_native_cancel
        assert loop.last_facts is not None
        cancel_diagnostic = _cancel_admission_projection(
            api,
            broker,
            loop.last_facts,
            close_ref,
        )
        assert (
            loop.last_facts.order_cancel_ready is True
        ), "AC50_22_CANCEL_ADMISSION_FACTS_NOT_READY " + json.dumps(
            cancel_diagnostic, sort_keys=True, default=str, separators=(",", ":")
        )
        _assert_submitted_order_offsets_match_native_refs(
            api,
            submitted_offsets,
            [(str(open_ref), "open"), (str(close_ref), "close_today")],
        )
        with cancel_scope:
            strategy.cancel(close_order)
        raise AssertionError("the actual partial-close cancel did not crash after dispatch")
    finally:
        journal.close()


def _spawned_recover_partial_close_and_close_remaining(journal_path, checkpoint, result_queue):
    now = datetime.now(timezone.utc)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        recovery,
        "_arm_template",
        crash_helpers._canonical_sdk_arm_template,
    )
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
    ) = recovery._durable_system(journal_path, now=now, bars=3, monkeypatch=monkeypatch)
    submitted_offsets = _capture_submitted_order_offsets(api)
    stage = "fresh_session_terminal_query"
    absence_calls = []
    try:
        _initialize_fake_sdk_pending_order_maps(api)
        crash_helpers._bind_sdk_session_identity(
            api, generation=2, front_id=5, session_id=8
        )
        api._connected = True
        api._use_observed_query_clock = True
        open_ref = checkpoint["open_order_ref"]
        close_ref = checkpoint["order_ref"]
        open_time = datetime.fromisoformat(checkpoint["open_time"])
        close_time = datetime.fromisoformat(checkpoint["close_time"])
        open_trade = _trade_row(
            checkpoint["open_trade_id"],
            open_ref,
            "sys-{}".format(open_ref),
            when=open_time,
            quantity=2,
            offset_flag="0",
        )
        close_trade = _trade_row(
            checkpoint["close_trade_id"],
            close_ref,
            "sys-{}".format(close_ref),
            when=close_time,
            quantity=1,
            offset_flag="3",
        )
        open_terminal = _order_row(
            open_ref,
            status="0",
            side="BUY",
            effect="OPEN",
            original=2,
            traded=2,
            remaining=0,
        )
        close_terminal = _order_row(
            close_ref,
            status="5",
            side="SELL",
            effect="CLOSE",
            original=2,
            traded=1,
            remaining=1,
            offset_flag="3",
        )
        assert open_trade["OrderSysID"] == open_terminal["OrderSysID"]
        assert open_trade["OffsetFlag"] == open_terminal["CombOffsetFlag"] == "0"
        _assert_query_trade_row(
            open_trade,
            order_ref=open_ref,
            trade_id=checkpoint["open_trade_id"],
            order_sys_id="sys-{}".format(open_ref),
            side="BUY",
            offset_flag="0",
            quantity=2,
            when=open_time,
        )
        assert close_trade["OrderSysID"] == close_terminal["OrderSysID"]
        assert close_trade["OffsetFlag"] == close_terminal["CombOffsetFlag"] == "3"
        _assert_query_trade_row(
            close_trade,
            order_ref=close_ref,
            trade_id=checkpoint["close_trade_id"],
            order_sys_id="sys-{}".format(close_ref),
            side="SELL",
            offset_flag="3",
            quantity=1,
            when=close_time,
        )
        _set_query_rows(
            api,
            orders=(open_terminal, close_terminal),
            trades=(open_trade, close_trade),
            positions=(facts_helpers._dated_position_row("1"),),
        )
        # A fresh Broker is seeded from this complete current account snapshot;
        # no historical Backtrader Order is rebuilt.
        broker.positions[recovery._INSTRUMENT].update(1, 100.0)
        _seed_current_quote(api, store, broker, target, generation=2, sequence=40)
        absence_outcomes = []
        absence = _capture_real_store_absence_check(store, absence_outcomes)

        def refuse_first_absence_then_check_store(*, original_identity, expected_session):
            if not absence_calls:
                # Cause a real local Store refusal only after the durable CAS.
                api._order_state[close_ref] = "active"
            try:
                result = absence(
                    original_identity=original_identity,
                    expected_session=expected_session,
                )
            except Exception as error:
                absence_calls.append(
                    (
                        dict(original_identity),
                        dict(expected_session),
                        str(error),
                    )
                )
                raise
            absence_calls.append((dict(original_identity), dict(expected_session), result))
            return result

        store.registered_sim_assert_original_order_absent = refuse_first_absence_then_check_store
        leases = _track_recovery_leases(coordinator)
        loop = _refresh_loop(api, store, broker, journal, coordinator, target, cerebro)
        original_terminal_reconcile = coordinator.reconcile_terminal_order_observations
        retry_query_projections = []
        retry_query_facts = []

        def capture_retry_query(facts, *args, **kwargs):
            retry_query_facts.append(facts)
            retry_query_projections.append(
                {
                    "query_set_id": facts.query_set_id,
                    "snapshot_id": facts.snapshot_id,
                    "trade_rows": tuple(
                        (
                            row.trade_id,
                            row.request_id,
                            row.observation_id,
                            str(row.volume),
                            str(row.price),
                            row.trade_date,
                            row.trade_time,
                        )
                        for row in facts.trade_observations
                    ),
                }
            )
            return original_terminal_reconcile(facts, *args, **kwargs)

        coordinator.reconcile_terminal_order_observations = capture_retry_query

        def reject_wrong_open_book_owner(facts, **kwargs):
            positions = tuple(
                replace(position, owner_intent_id="ac50-22-wrong-open-owner")
                if position.instrument == recovery._INSTRUMENT
                and position.exchange == recovery._EXCHANGE
                else position
                for position in facts.positions
            )
            assert positions != facts.positions
            return original_terminal_reconcile(replace(facts, positions=positions), **kwargs)

        coordinator.reconcile_terminal_order_observations = reject_wrong_open_book_owner
        stage = "wrong_open_book_owner_rejected"
        try:
            loop.refresh_once()
        except _RUNNER.RunnerError:
            pass
        else:
            raise AssertionError("CLOSE recovery accepted a mismatched OPEN Book owner")
        finally:
            coordinator.reconcile_terminal_order_observations = capture_retry_query
        assert any(
            item[0] == "terminal_orders"
            and item[3] == "CANCEL_DISPATCHING_POSITION_BOOK_OWNER_MISMATCH"
            for item in loop.last_reconciliation_blockers
        )
        assert loop.last_receipt is None and loop.last_facts is None
        assert absence_calls == []
        assert journal.instrument_resolution(checkpoint["submit_intent_id"]) is None
        assert journal.intent(checkpoint["cancel_intent_id"]).state == "DISPATCHING"

        stage = "partial_close_store_absence_refused_after_cas"
        try:
            loop.refresh_once()
        except _RUNNER.RunnerError:
            pass
        else:
            raise AssertionError("local Store conflict did not block the post-CAS publication")
        assert loop.last_error_code == "LIVE_CANCEL_DISPATCHING_STORE_ABSENCE_PENDING"
        assert loop.last_receipt is None and loop.last_facts is None
        assert len(leases) == 2
        assert len(absence_calls) == 1
        assert "LOCAL_ORDER_REFERENCE_PRESENT" in absence_calls[0][2]
        assert absence_outcomes == [
            {
                "original_identity": absence_calls[0][0],
                "expected_session": absence_calls[0][1],
                "status": "ERROR",
                "error_type": "BtApiStoreError",
                "error": absence_calls[0][2],
            }
        ]
        assert api._order_state[close_ref] == "active"
        api._order_state.pop(close_ref)

        close_intent_id = checkpoint["submit_intent_id"]
        cancel_intent_id = checkpoint["cancel_intent_id"]
        open_intent_id = checkpoint["open_intent_id"]
        close_intent_after_refusal = journal.intent(close_intent_id)
        cancel_intent_after_refusal = journal.intent(cancel_intent_id)
        resolution_after_refusal = journal.instrument_resolution(close_intent_id)
        assert close_intent_after_refusal is not None
        assert cancel_intent_after_refusal is not None
        assert resolution_after_refusal is not None
        assert cancel_intent_after_refusal.state == "KNOWN"
        assert cancel_intent_after_refusal.dispatch_state is None
        assert cancel_intent_after_refusal.provider_identity is None
        assert cancel_intent_after_refusal.outcome_code is None
        assert _dispatch_result_json_is_null(journal, cancel_intent_id)
        parent_cas_after_refusal = journal.reconciliation(
            resolution_after_refusal.reconciliation_id
        )
        assert parent_cas_after_refusal is not None
        cancel_cas_id_after_refusal = parent_cas_after_refusal.provider_identity[
            "cancel_reconciliation_id"
        ]
        cancel_cas_after_refusal = journal.reconciliation(cancel_cas_id_after_refusal)
        assert cancel_cas_after_refusal is not None
        assert len(retry_query_facts) == 1
        first_query = retry_query_projections[0]
        first_facts = retry_query_facts[0]
        assert len(first_query["trade_rows"]) == 2
        first_close_trade_projection = next(
            row for row in first_query["trade_rows"] if row[0] == close_trade["TradeID"]
        )
        first_close_fill_id = facts_helpers._execution_id_from_trade_row(close_trade)
        first_close_fill = journal._connection.execute(
            """SELECT intent_id,position_effect,quantity,fee
               FROM factor_position_fills WHERE execution_id=?""",
            (first_close_fill_id,),
        ).fetchone()
        assert first_close_fill is not None
        assert first_close_fill["intent_id"] == close_intent_id
        assert first_close_fill["position_effect"] == "CLOSE"
        assert Decimal(first_close_fill["quantity"]) == Decimal("1")
        assert Decimal(first_close_fill["fee"]) == Decimal("0.25")
        assert (
            journal._connection.execute(
                "SELECT COUNT(*) FROM factor_position_fills WHERE execution_id=?",
                (first_close_fill_id,),
            ).fetchone()[0]
            == 1
        )
        pending_after_refusal = _dispatching_cancel_candidate_page(journal)
        assert not pending_after_refusal.truncated
        assert len(pending_after_refusal.items) == 1
        assert pending_after_refusal.items[0].parent_intent_id == close_intent_id
        assert pending_after_refusal.items[0].cancel_intent_id == cancel_intent_id
        first_refused_book = _book_snapshot(coordinator, first_facts, broker, data)
        assert first_refused_book.status == "MATCHED", first_refused_book
        assert first_refused_book.owner_intent_id == open_intent_id
        assert first_refused_book.signed_quantity == Decimal("1")
        assert first_refused_book.opening_fee_total == Decimal("0.12")
        assert api.native_calls == []
        assert (
            len(
                tuple(
                    item
                    for item in journal.reconciliations(close_intent_id, limit=128)
                    if item.outcome_code == "LOCAL_STORE_ABSENCE"
                )
            )
            == 0
        )

        # A new complete query changes query-local request/observation IDs,
        # while the same durable partial fill and OPEN Book owner survive.
        stage = "partial_close_terminal_retry_with_fresh_query"
        receipt = loop.refresh_once()
        assert receipt is loop.last_receipt
        assert loop.last_facts is not None
        assert len(leases) == 3
        assert len(absence_calls) == 2
        assert absence_calls[1][2] == "ALREADY_ABSENT"
        assert absence_outcomes[1]["status"] == "OK"
        assert absence_outcomes[1]["result"] == "ALREADY_ABSENT"
        assert len(retry_query_facts) == 2
        second_query = retry_query_projections[1]
        assert second_query["query_set_id"] != first_query["query_set_id"]
        assert second_query["snapshot_id"] != first_query["snapshot_id"]
        second_close_trade_projection = next(
            row for row in second_query["trade_rows"] if row[0] == close_trade["TradeID"]
        )
        assert second_close_trade_projection[1] != first_close_trade_projection[1]
        assert second_close_trade_projection[2] != first_close_trade_projection[2]
        assert second_close_trade_projection[3:] == first_close_trade_projection[3:]
        assert loop.last_facts.positions[0].broker_quantity == Decimal("1")
        assert loop.last_facts.positions[0].long_quantity == Decimal("1")
        old_order_rebuilt = bool(broker.orders)
        assert old_order_rebuilt is False
        assert api.native_calls == []

        close_intent = journal.intent(close_intent_id)
        cancel_intent = journal.intent(cancel_intent_id)
        resolution = journal.instrument_resolution(close_intent_id)
        assert close_intent is not None and cancel_intent is not None and resolution is not None
        assert close_intent.key.position_effect == "CLOSE"
        assert cancel_intent.state == "KNOWN"
        assert cancel_intent.dispatch_state is None
        assert cancel_intent.provider_identity is None
        assert cancel_intent.outcome_code is None
        assert _dispatch_result_json_is_null(journal, cancel_intent_id)
        absence_ack_rows = tuple(
            item
            for item in journal.reconciliations(close_intent_id, limit=128)
            if item.outcome_code == "LOCAL_STORE_ABSENCE"
        )
        assert len(absence_ack_rows) == 1
        absence_ack = absence_ack_rows[0]
        assert resolution.position_flat is False
        assert (
            journal.active_instrument_owner(recovery._ACCOUNT_SCOPE, recovery._INSTRUMENT) is None
        )
        recovered_book = _book_snapshot(coordinator, loop.last_facts, broker, data)
        assert recovered_book.status == "MATCHED", recovered_book
        assert recovered_book.owner_intent_id == open_intent_id
        assert recovered_book.signed_quantity == Decimal("1")
        assert recovered_book.opening_fee_total == Decimal("0.12")
        assert recovered_book.opening_fees_known is True
        close_fill_id = facts_helpers._execution_id_from_trade_row(close_trade)
        close_fill = journal._connection.execute(
            """SELECT intent_id,position_effect,quantity,fee
               FROM factor_position_fills WHERE execution_id=?""",
            (close_fill_id,),
        ).fetchone()
        assert close_fill is not None
        assert close_fill["intent_id"] == close_intent_id
        assert close_fill["position_effect"] == "CLOSE"
        assert Decimal(close_fill["quantity"]) == Decimal("1")
        assert Decimal(close_fill["fee"]) == Decimal("0.25")
        assert (
            journal._connection.execute(
                "SELECT COUNT(*) FROM factor_position_fills WHERE execution_id=?",
                (close_fill_id,),
            ).fetchone()[0]
            == 1
        )
        assert resolution_after_refusal == resolution
        assert parent_cas_after_refusal == journal.reconciliation(resolution.reconciliation_id)
        assert cancel_cas_after_refusal == journal.reconciliation(
            absence_ack.provider_identity["cancel_reconciliation_id"]
        )
        assert not _dispatching_cancel_candidate_page(journal).items

        # The recovered remaining Book quantity still authorizes a distinct
        # owned CLOSE; it consumes the OPEN lot rather than creating exposure.
        store.registered_sim_configure_arm_templates(
            {
                (recovery._INSTRUMENT, recovery._EXCHANGE): recovery._arm_template(),
            }
        )
        store.registered_sim_arm(
            instrument=recovery._INSTRUMENT,
            exchange=recovery._EXCHANGE,
            **recovery._arm_template(),
        )
        remaining_facts = _project_risk_facts_after_completed_query(
            api,
            store,
            broker,
            target,
            loop.last_receipt.query_set,
            generation=2,
            sequence=41,
        )
        assert remaining_facts.risk_reduction_ready is True, _risk_reduction_projection(
            remaining_facts
        )
        remaining_book_before_close = _book_snapshot(
            coordinator,
            remaining_facts,
            broker,
            data,
        )
        assert remaining_book_before_close.status == "MATCHED", remaining_book_before_close
        assert remaining_book_before_close.owner_intent_id == open_intent_id
        assert remaining_book_before_close.signed_quantity == Decimal("1")
        assert remaining_book_before_close.opening_fee_total == Decimal("0.12")
        assert remaining_book_before_close.opening_fees_known is True
        api._next_order_reference = 900
        remaining_scope = _close_order_scope(
            coordinator,
            strategy,
            remaining_facts,
            quantity=1,
            owner_intent_id=open_intent_id,
            batch_id="ac50-22-close-recovered-remainder",
            offset="close_today",
        )
        stage = "later_owned_close"
        with remaining_scope:
            remaining_order = strategy.sell(
                data=data,
                size=1,
                price=100,
                exectype=Order.Limit,
                instrument_id=recovery._INSTRUMENT,
                exchange_id=recovery._EXCHANGE,
                factor_position_effect="CLOSE",
                factor_strategy_scope=recovery._STRATEGY_SCOPE,
                factor_owner_side="BUY",
                factor_owner_position_effect="OPEN",
                offset="close_today",
            )
        remaining_intent_id = remaining_order.info["factor_intent_id"]
        remaining_ref = remaining_order.info["external_order_ref"]
        assert remaining_intent_id != close_intent_id
        assert remaining_ref != close_ref
        assert all(
            item.info.get("external_order_ref") != str(close_ref) for item in broker.orders.values()
        )
        _assert_submitted_order_offsets_match_native_refs(
            api,
            submitted_offsets,
            [(str(remaining_ref), "close_today")],
        )
        remaining_sys_id = _assign_fake_provider_order_sys_id(api, remaining_ref)
        assert (
            _emit_order_callback_with_native_sys_id(
                api,
                cerebro,
                strategy,
                broker,
                remaining_ref,
                order=remaining_order,
                status="accepted",
                filled=0,
                remaining=1,
            )
            == remaining_sys_id
        )
        # This fill follows its own later CLOSE decision and precedes the
        # final complete query; do not reuse the earlier PID1 timestamp.
        remaining_time = _ctp_trade_time_after(loop.last_facts.available_at)
        _emit_provider_close_today_trade_callback(
            api,
            remaining_ref,
            trade_id="ac50-22-recovered-remainder-close",
            quantity=1,
            when=remaining_time,
        )
        _add_fee_to_last_trade_callback(api, "0.03")
        _assert_provider_trade_callback(
            api,
            order_ref=remaining_ref,
            trade_id="ac50-22-recovered-remainder-close",
            order_sys_id=remaining_sys_id,
            side="SELL",
            offset="close_today",
            offset_flag="3",
            quantity=1,
            fee="0.03",
            when=remaining_time,
        )
        assert (
            _emit_order_callback_with_native_sys_id(
                api,
                cerebro,
                strategy,
                broker,
                remaining_ref,
                order=remaining_order,
                status="completed",
                filled=1,
                remaining=0,
            )
            == remaining_sys_id
        )
        assert broker.execution_position_snapshot(data).quantity == Decimal("0")
        remaining_trade = _trade_row(
            "ac50-22-recovered-remainder-close",
            remaining_ref,
            remaining_sys_id,
            when=remaining_time,
            quantity=1,
            offset_flag="3",
        )
        remaining_terminal = _order_row(
            remaining_ref,
            status="0",
            side="SELL",
            effect="CLOSE",
            original=1,
            traded=1,
            remaining=0,
            front_id=5,
            session_id=8,
            offset_flag="3",
        )
        assert remaining_trade["OrderSysID"] == remaining_terminal["OrderSysID"] == remaining_sys_id
        assert remaining_trade["OffsetFlag"] == remaining_terminal["CombOffsetFlag"] == "3"
        _assert_query_trade_row(
            remaining_trade,
            order_ref=remaining_ref,
            trade_id="ac50-22-recovered-remainder-close",
            order_sys_id=remaining_sys_id,
            side="SELL",
            offset_flag="3",
            quantity=1,
            when=remaining_time,
        )
        _assert_submitted_order_offsets_match_native_refs(
            api,
            submitted_offsets,
            [(str(remaining_ref), "close_today")],
        )
        _set_query_rows(
            api,
            orders=(open_terminal, close_terminal, remaining_terminal),
            trades=(open_trade, close_trade, remaining_trade),
            positions=(),
        )
        unrelated_intent = _persist_unrelated_dispatching_intent(
            journal,
            coordinator,
            generation=2,
            front_id=5,
            session_id=8,
        )
        assert journal.intent(unrelated_intent.intent_id).state == "DISPATCHING"
        stage = "final_owned_close_reconciliation"
        final_receipt = loop.refresh_once()
        assert final_receipt is not None and final_receipt is loop.last_receipt
        assert loop.last_facts is not None
        assert loop.last_error_code is None
        assert len(leases) == 4
        assert len(absence_calls) == 2
        assert journal.reconciliation(absence_ack.reconciliation_id) == absence_ack
        assert not _dispatching_cancel_candidate_page(journal).items
        assert journal.intent(remaining_intent_id).state == "KNOWN"
        final_book = _book_snapshot(coordinator, loop.last_facts, broker, data)
        assert final_book.status == "FLAT"
        assert final_book.signed_quantity == Decimal("0")
        assert (
            journal.active_instrument_owner(recovery._ACCOUNT_SCOPE, recovery._INSTRUMENT) is None
        )
        assert api.native_calls == [
            ("insert", recovery._INSTRUMENT, recovery._EXCHANGE, remaining_ref, 101)
        ]
        open_fill_id = facts_helpers._execution_id_from_trade_row(open_trade)
        close_fill_id = facts_helpers._execution_id_from_trade_row(close_trade)
        remaining_fill_id = facts_helpers._execution_id_from_trade_row(remaining_trade)
        final_fills = journal._connection.execute(
            """SELECT execution_id,intent_id,position_effect,quantity,fee
               FROM factor_position_fills
               WHERE account_scope=? AND instrument=? AND exchange=?
               ORDER BY execution_id""",
            (recovery._ACCOUNT_SCOPE, recovery._INSTRUMENT, recovery._EXCHANGE),
        ).fetchall()
        assert len(final_fills) == 3
        assert {row["execution_id"] for row in final_fills} == {
            open_fill_id,
            close_fill_id,
            remaining_fill_id,
        }
        fills_by_execution = {row["execution_id"]: row for row in final_fills}
        assert fills_by_execution[open_fill_id]["intent_id"] == open_intent_id
        assert fills_by_execution[open_fill_id]["position_effect"] == "OPEN"
        assert Decimal(fills_by_execution[open_fill_id]["quantity"]) == Decimal("2")
        assert Decimal(fills_by_execution[open_fill_id]["fee"]) == Decimal("0.12")
        assert fills_by_execution[close_fill_id]["intent_id"] == close_intent_id
        assert fills_by_execution[close_fill_id]["position_effect"] == "CLOSE"
        assert Decimal(fills_by_execution[close_fill_id]["quantity"]) == Decimal("1")
        assert Decimal(fills_by_execution[close_fill_id]["fee"]) == Decimal("0.25")
        assert fills_by_execution[remaining_fill_id]["intent_id"] == remaining_intent_id
        assert fills_by_execution[remaining_fill_id]["position_effect"] == "CLOSE"
        assert Decimal(fills_by_execution[remaining_fill_id]["quantity"]) == Decimal("1")
        assert Decimal(fills_by_execution[remaining_fill_id]["fee"]) == Decimal("0.03")
        assert sum((Decimal(row["fee"]) for row in final_fills), Decimal("0")) == Decimal("0.40")
        result_queue.put(
            {
                "status": "OK",
                "pid": os.getpid(),
                "original_pid": checkpoint["pid"],
                "owner_intent_id": open_intent_id,
                "partial_close_intent_id": close_intent_id,
                "remaining_close_intent_id": remaining_intent_id,
                "recovered_quantity": str(recovered_book.signed_quantity),
                "recovered_close_fee": close_fill["fee"],
                "final_fill_count": len(final_fills),
                "final_total_fee": str(
                    sum((Decimal(row["fee"]) for row in final_fills), Decimal("0"))
                ),
                "recovered_book_owner_preserved": recovered_book.owner_intent_id == open_intent_id,
                "final_position_status": final_book.status,
                "absence_calls": len(absence_calls),
                "lease_count": len(leases),
                "post_cas_absence_refusal_retried": (
                    len(absence_calls) == 2
                    and "LOCAL_ORDER_REFERENCE_PRESENT" in absence_calls[0][2]
                    and absence_calls[1][2] == "ALREADY_ABSENT"
                ),
                "fresh_query_request_changed": (
                    len(retry_query_projections) >= 2
                    and second_close_trade_projection[1] != first_close_trade_projection[1]
                ),
                "wrong_open_owner_rejected": True,
                "old_order_rebuilt": old_order_rebuilt,
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
                "error_traceback": traceback.format_exc(limit=8)[-2400:],
            }
        )
    finally:
        journal.close()


def test_partial_close_fill_survives_cancel_dispatch_crash_and_remains_owned(tmp_path):
    """Recovery keeps the OPEN Book owner and exact partial-close economics."""

    journal_path = tmp_path / "partial-close-cancel-crash.sqlite3"
    checkpoint_path = tmp_path / "partial-close-cancel-crash.json"
    context = multiprocessing.get_context("spawn")
    pid1 = _spawn_exit(
        context,
        target=_spawned_partial_close_cancel_crash,
        args=(str(journal_path), str(checkpoint_path)),
        expected_code=_EXIT_CODE,
    )
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["pid"] == pid1
    assert checkpoint["boundary"] == "cancel_dispatching_partial_close"
    assert checkpoint["native_return_code_before_crash"] == 0
    assert checkpoint["native_call_count"] == 3
    assert checkpoint["original_identity"]["connection_generation"] == 1
    assert checkpoint["original_identity"]["front_id"] == 4
    assert checkpoint["original_identity"]["session_id"] == 7

    recovered = _spawn_result(
        context,
        target=_spawned_recover_partial_close_and_close_remaining,
        args=(str(journal_path), checkpoint),
    )
    assert recovered["pid"] != pid1
    assert recovered["original_pid"] == pid1
    assert recovered["recovered_quantity"] == "1"
    assert recovered["recovered_close_fee"] == "0.25"
    assert recovered["final_fill_count"] == 3
    assert recovered["final_total_fee"] == "0.40"
    assert recovered["recovered_book_owner_preserved"] is True
    assert recovered["final_position_status"] == "FLAT"
    assert recovered["absence_calls"] == 2
    assert recovered["lease_count"] == 4
    assert recovered["post_cas_absence_refusal_retried"] is True
    assert recovered["fresh_query_request_changed"] is True
    assert recovered["wrong_open_owner_rejected"] is True
    assert recovered["old_order_rebuilt"] is False
