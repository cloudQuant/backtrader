import multiprocessing
import os
import sqlite3
import time

import pytest

from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
    ExecutionDecisionKey,
    ExecutionIntentKey,
)


def _hold_gate_in_child(database_path, entered, release):
    journal = ExecutionDecisionJournal(database_path)
    with journal.dispatch_serialization_gate(timeout_seconds=5.0) as lease:
        assert lease.cross_process is True
        entered.set()
        if not release.wait(8.0):
            os._exit(91)
    journal.close()


def _crash_inside_gate_in_child(database_path, entered):
    journal = ExecutionDecisionJournal(database_path)
    with journal.dispatch_serialization_gate(timeout_seconds=5.0) as lease:
        assert lease.cross_process is True
        entered.set()
        os._exit(73)


def _claim_intent_then_wait_for_crash(database_path, decision_id, claimed, release):
    journal = ExecutionDecisionJournal(database_path)
    intent_key = ExecutionIntentKey(
        action="SUBMIT", instrument="SIM-IF-1", side="BUY", position_effect="OPEN", leg=0
    )
    with journal.dispatch_serialization_gate(timeout_seconds=5.0) as lease:
        assert lease.cross_process is True
        intent = journal.prepare_intent(
            decision_id,
            intent_key,
            {"quantity": "1", "price": "100", "exchange": "CFFEX"},
            original_identity={"backtrader_order_ref": 501},
        )
        assert journal.claim_dispatch(intent.intent_id) is not None
        claimed.set()
        if not release.wait(8.0):
            os._exit(92)
        # Simulate a hard process death after claim persistence and before a
        # provider result can be stored.
        os._exit(74)


def test_dispatch_gate_is_shared_by_independent_journal_connections(tmp_path):
    path = tmp_path / "shared-dispatch.sqlite3"
    first = ExecutionDecisionJournal(path)
    second = ExecutionDecisionJournal(path)
    gate_path = first.dispatch_serialization_path

    with first.dispatch_serialization_gate(timeout_seconds=1.0) as lease:
        assert lease.cross_process is True
        assert gate_path == path.resolve().with_name(path.name + ".dispatch-gate.sqlite3")
        assert gate_path.is_file()
        with pytest.raises(
            ExecutionDecisionJournalError, match="DISPATCH_SERIALIZATION_BUSY"
        ), second.dispatch_serialization_gate(timeout_seconds=0.05):
            pytest.fail("a second journal connection entered an occupied gate")

    with second.dispatch_serialization_gate(timeout_seconds=1.0) as lease:
        assert lease.cross_process is True
    first.close()
    second.close()


def test_dispatch_gate_excludes_a_different_process_until_release(tmp_path):
    path = tmp_path / "cross-process-dispatch.sqlite3"
    parent_journal = ExecutionDecisionJournal(path)
    context = multiprocessing.get_context("spawn")
    entered = context.Event()
    release = context.Event()
    child = context.Process(target=_hold_gate_in_child, args=(str(path), entered, release))
    child.start()
    try:
        assert entered.wait(8.0)
        with pytest.raises(
            ExecutionDecisionJournalError, match="DISPATCH_SERIALIZATION_BUSY"
        ), parent_journal.dispatch_serialization_gate(timeout_seconds=0.1):
            pytest.fail("the parent entered while the child owned the gate")
    finally:
        release.set()
        child.join(8.0)
        if child.is_alive():
            child.terminate()
            child.join(2.0)
    assert child.exitcode == 0

    with parent_journal.dispatch_serialization_gate(timeout_seconds=1.0) as lease:
        assert lease.cross_process is True
    parent_journal.close()


def test_process_death_releases_sqlite_dispatch_gate(tmp_path):
    path = tmp_path / "crashed-dispatch.sqlite3"
    journal = ExecutionDecisionJournal(path)
    context = multiprocessing.get_context("spawn")
    entered = context.Event()
    child = context.Process(target=_crash_inside_gate_in_child, args=(str(path), entered))
    child.start()
    assert entered.wait(8.0)
    child.join(8.0)
    if child.is_alive():
        child.terminate()
        child.join(2.0)
    assert child.exitcode == 73

    # OS process termination releases the file lock without a stale-PID
    # cleanup path or manual recovery declaration.
    with journal.dispatch_serialization_gate(timeout_seconds=1.0) as lease:
        assert lease.cross_process is True
    journal.close()


def test_claim_and_recovery_share_gate_across_process_crash_boundary(tmp_path):
    path = tmp_path / "dispatching-recovery-gate.sqlite3"
    setup = ExecutionDecisionJournal(path)
    intent_key = ExecutionIntentKey(
        action="SUBMIT", instrument="SIM-IF-1", side="BUY", position_effect="OPEN", leg=0
    )
    decision = setup.record_decision(
        ExecutionDecisionKey(
            account_scope="account-a",
            strategy_scope="strategy-a",
            logical_run_id="run-a",
            cohort_id="cohort-a",
            close_time="2026-10-24T10:00:00Z",
            decision_kind="bar",
        ),
        {"signal": "cross-up"},
        intent_keys=(intent_key,),
    )
    setup.close()

    context = multiprocessing.get_context("spawn")
    claimed = context.Event()
    release = context.Event()
    child = context.Process(
        target=_claim_intent_then_wait_for_crash,
        args=(str(path), decision.decision_id, claimed, release),
    )
    child.start()
    recovery = None
    try:
        assert claimed.wait(8.0)
        recovery = ExecutionDecisionJournal(path)
        with pytest.raises(ExecutionDecisionJournalError, match="DISPATCH_SERIALIZATION_BUSY"):
            recovery.dispatch_serialization_gate(timeout_seconds=0.1, recovery=True).__enter__()
    finally:
        release.set()
        child.join(8.0)
        if child.is_alive():
            child.terminate()
            child.join(2.0)

    assert child.exitcode == 74
    assert recovery is not None
    with recovery.dispatch_serialization_gate(timeout_seconds=1.0, recovery=True) as lease:
        assert lease.cross_process is True
        rows = recovery.execution_intent_snapshot(account_scope="account-a", limit=8)
        assert len(rows.items) == 1
        intent = rows.items[0]
        assert intent.state == "DISPATCHING"
        assert intent.dispatch_state is None
        assert intent.provider_identity is None
        assert intent.outcome_code is None
        assert recovery.claim_dispatch(intent.intent_id) is None
    recovery.close()


def test_memory_journal_gate_is_local_and_recovery_is_rejected():
    journal = ExecutionDecisionJournal(":memory:")
    assert journal.dispatch_serialization_path is None
    with journal.dispatch_serialization_gate(timeout_seconds=0.1) as lease:
        assert lease.cross_process is False
    with pytest.raises(
        ExecutionDecisionJournalError,
        match="DISPATCH_RECOVERY_REQUIRES_DURABLE_JOURNAL",
    ), journal.dispatch_serialization_gate(timeout_seconds=0.1, recovery=True):
        pytest.fail("an in-memory journal cannot authorize crash recovery")
    journal.close()


def test_memory_journal_dispatch_gate_rejects_nested_scope_within_deadline():
    journal = ExecutionDecisionJournal(":memory:")
    with journal.dispatch_serialization_gate(timeout_seconds=0.5) as lease:
        assert lease.cross_process is False
        started = time.monotonic()
        with pytest.raises(
            ExecutionDecisionJournalError, match="DISPATCH_SERIALIZATION_BUSY"
        ), journal.dispatch_serialization_gate(timeout_seconds=0.05):
            pytest.fail("a nested dispatch scope entered the same in-memory journal")
        elapsed = time.monotonic() - started
        assert 0.04 <= elapsed < 0.5

    # The failed nested acquisition must leave the outer scope usable and
    # release its mutex normally.
    with journal.dispatch_serialization_gate(timeout_seconds=0.1) as lease:
        assert lease.cross_process is False
    journal.close()


@pytest.mark.parametrize("timeout", [True, 0, -0.1, float("inf"), float("nan"), 60.1])
def test_dispatch_gate_rejects_invalid_or_unbounded_timeout(tmp_path, timeout):
    journal = ExecutionDecisionJournal(tmp_path / "bad-timeout.sqlite3")
    with pytest.raises(ExecutionDecisionJournalError, match="INVALID_DISPATCH_GATE_TIMEOUT"):
        journal.dispatch_serialization_gate(timeout_seconds=timeout).__enter__()
    journal.close()


def test_dispatch_gate_fails_closed_for_symlinked_sidecar(tmp_path):
    path = tmp_path / "symlinked-journal.sqlite3"
    journal = ExecutionDecisionJournal(path)
    sidecar = journal.dispatch_serialization_path
    target = tmp_path / "other-lock.sqlite3"
    with sqlite3.connect(target) as connection:
        connection.execute("CREATE TABLE marker (value INTEGER)")
    try:
        sidecar.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this platform")
    with pytest.raises(ExecutionDecisionJournalError, match="DISPATCH_GATE_PATH_UNSAFE"):
        journal.dispatch_serialization_gate(timeout_seconds=0.1).__enter__()
    journal.close()
