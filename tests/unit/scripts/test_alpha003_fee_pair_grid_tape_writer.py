"""Synthetic production-writer contracts for the v20 GRID tape append seam."""

from __future__ import annotations

from dataclasses import fields, replace
import hashlib
import importlib.util
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest

from backtrader.stores import execution_decision_journal as journal_module
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
)
from tests.unit.stores import test_execution_fee_pair_candidate_journal as workflow_fixtures


RUNNER_PATH = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "unified"
    / "028_alpha003_simnow_minute"
    / "run.py"
)
EXAMPLE_PATH = str(RUNNER_PATH.parent)
if EXAMPLE_PATH not in sys.path:
    sys.path.insert(0, EXAMPLE_PATH)
RUNNER_SPEC = importlib.util.spec_from_file_location(
    "alpha003_fee_pair_grid_tape_writer_test_runner", RUNNER_PATH
)
assert RUNNER_SPEC is not None and RUNNER_SPEC.loader is not None
runner = importlib.util.module_from_spec(RUNNER_SPEC)
sys.modules[RUNNER_SPEC.name] = runner
RUNNER_SPEC.loader.exec_module(runner)
_DEFAULT_ORDER_PLAN = object()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _selection_inputs(candidate):
    routes = {"SIM-A": "rb2510", "SIM-B": "i2510"}
    authorized = ["SIM-A", "SIM-B"]
    manifest = {"fixture": "synthetic-public"}
    manifest_sha256 = hashlib.sha256(
        runner._canonical_json_bytes(manifest).rstrip(b"\n")
    ).hexdigest()
    binding = {
        "schema": "backtrader.alpha003_epoch_selection_evidence.v1",
        "epoch_id": candidate.epoch_id,
        "selection_source": "saved_bundle_legacy",
        "selection_path": "synthetic-public-fixture",
        "source_snapshot_id": None,
        "manifest_sha256": manifest_sha256,
        "routes": routes,
        "authorized_targets": authorized,
    }
    evidence = {
        **binding,
        "binding_sha256": hashlib.sha256(
            runner._canonical_json_bytes(binding).rstrip(b"\n")
        ).hexdigest(),
        "manifest": manifest,
    }
    identity = {
        "schema": "backtrader.alpha003.live_restart_identity.v1",
        "epoch_id": candidate.epoch_id,
        "mode": "live",
        "factor_mode": "native",
        "direction": 1,
        "scope_sha256": {
            name: _digest(value)
            for name, value in (
                ("account_scope", candidate.key.account_scope),
                ("strategy_scope", candidate.key.strategy_scope),
                ("logical_run_id", candidate.key.logical_run_id),
            )
        },
        "selection_source": "saved_bundle_legacy",
        "source_snapshot_id": None,
        "targets": ["SIM-A", "SIM-B"],
        "authorized_targets": authorized,
        "routes": routes,
        "calendar": {
            "calendar_id": candidate.calendar_id,
            "grid_sha256": _digest("synthetic-grid"),
        },
    }
    return identity, evidence


def _candidate_with_origin_partitions(candidate):
    source_members = []
    for member in candidate.source_members:
        partition = {
            "schema": runner.SOURCE_ORIGIN_PARTITION_SCHEMA,
            "cohort_id": candidate.key.cohort_id,
            "epoch_id": candidate.epoch_id,
            "member_id": member.member_id,
            "source_ref": member.source_ref,
            "source_role": member.source_role,
            "connection_generation": member.connection_generation,
        }
        source_members.append(
            replace(
                member,
                trading_day=runner._tape_trading_day(member.trading_day, "fixture"),
                origin_partition=partition,
            )
        )
    template = source_members[0]
    second_partition = {
        "schema": runner.SOURCE_ORIGIN_PARTITION_SCHEMA,
        "cohort_id": candidate.key.cohort_id,
        "epoch_id": candidate.epoch_id,
        "member_id": "SIM-B",
        "source_ref": "synthetic-ctp-b",
        "source_role": "live",
        "connection_generation": template.connection_generation,
    }
    second = replace(
        template,
        member_id="SIM-B",
        source_ref="synthetic-ctp-b",
        feed_sequence=2,
        bar_id="bar-2",
        origin_partition=second_partition,
    )
    return replace(
        candidate,
        source_members=(source_members[0], second),
    )


def _objects(candidate):
    member_rows = {}
    instrument_by_target = {"SIM-A": "rb2510", "SIM-B": "i2510"}
    for member in candidate.source_members:
        envelope_values = {
            field.name: getattr(member, field.name) for field in fields(member)
        }
        envelope_values.update(
            cohort_id=candidate.key.cohort_id,
            calendar_id=candidate.calendar_id,
            epoch_id=candidate.epoch_id,
            slot_index=candidate.slot_index,
            slot_id=candidate.slot_id,
            instrument=instrument_by_target[member.member_id],
        )
        envelope_values["raw_values"] = {
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 7.0,
            "openinterest": 0.0,
        }
        member_rows[member.member_id] = SimpleNamespace(
            envelope=SimpleNamespace(**envelope_values)
        )

    available_at = max(member.available_at for member in candidate.source_members)
    batch = SimpleNamespace(
        status="COMPLETE",
        members=member_rows,
        batch_id=candidate.batch_id,
        cohort_id=candidate.key.cohort_id,
        calendar_id=candidate.calendar_id,
        calendar_version=candidate.calendar_version,
        epoch_id=candidate.epoch_id,
        slot_index=candidate.slot_index,
        close_time=candidate.key.close_time,
        available_at=available_at,
    )
    factor_values = {
        member.member_id: SimpleNamespace(
            value=0.25 if member.member_id == "SIM-A" else -0.25,
            status="READY",
            reason=None,
            present=True,
            complete=True,
            quality="GOOD",
            source_role=member.source_role,
            member_id=member.member_id,
            source_ref=member.source_ref,
            sequence=member.feed_sequence,
            generation=member.connection_generation,
        )
        for member in candidate.source_members
    }
    factor = SimpleNamespace(
        mode="native",
        panel_line="alpha003",
        direction=1,
        source_sha256=candidate.factor_snapshot_sha256,
        values=factor_values,
    )
    snapshot = SimpleNamespace(
        batch_complete=True,
        batch_id=candidate.batch_id,
        close_time=candidate.key.close_time,
        readiness="LIVE_READY",
        readiness_reasons=(),
        plan_id="synthetic-plan",
        factors={"alpha003": factor},
    )
    target_rows = []
    for index, target in enumerate(candidate.target_ids):
        target_rows.append(
            SimpleNamespace(
                target_id=target,
                product_key=SimpleNamespace(
                    exchange_id="SHFE" if target == "SIM-A" else "DCE",
                    product_id=instrument_by_target[target],
                ),
                target_position=candidate.directions[index],
                raw_score=0.25 if target == "SIM-A" else -0.25,
                oriented_score=0.25,
            )
        )
    target_decision = SimpleNamespace(
        status="READY",
        reason=None,
        factor_name="alpha003",
        mode="native",
        execution_mode="simnow-live",
        direction=1,
        source_sha256=candidate.factor_snapshot_sha256,
        cohort_id=candidate.key.cohort_id,
        batch_id=candidate.batch_id,
        close_time=candidate.key.close_time,
        available_at=available_at,
        eligible_grid_index=candidate.slot_index,
        rebalance_every=1,
        authorized_targets=list(candidate.target_ids),
        eligible_targets=list(candidate.target_ids),
        targets=target_rows,
    )
    order_plan = SimpleNamespace(
        status="NO_ACTION",
        reason=None,
        decision_batch_id=candidate.batch_id,
        decision_available_at=available_at,
        actions=(),
    )
    return batch, snapshot, target_decision, order_plan


def _build_harness(tmp_path, run_id="grid-writer"):
    candidate = _candidate_with_origin_partitions(workflow_fixtures._candidate(run_id=run_id))
    identity, evidence = _selection_inputs(candidate)
    writer = runner.DecisionTapeWriter(
        tmp_path / (run_id + ".jsonl"),
        2 * 1024 * 1024,
        mode="live",
        factor_mode="native",
        direction=1,
        targets=("SIM-A", "SIM-B"),
        calendar_id=candidate.calendar_id,
        grid_sha256=identity["calendar"]["grid_sha256"],
        source_snapshot_id=None,
        restart_identity=identity,
        selection_evidence=evidence,
        calendar_fingerprint=candidate.calendar_fingerprint,
    )
    candidate = replace(candidate, expected_tape_file_id=writer.file_id)
    batch, snapshot, target_decision, order_plan = _objects(candidate)
    writer.record_decision(batch, snapshot, target_decision, order_plan)
    source_row = list(
        runner.iter_decision_tape(
            writer.path,
            max_bytes=writer.max_bytes,
            max_record_bytes=runner._FEE_PAIR_SOURCE_ONLY_MAX_RECORD_BYTES,
        )
    )[1]
    receipt = runner._fee_pair_source_receipt_from_tape_row(
        source_row, candidate, journal_module
    )

    journal = ExecutionDecisionJournal(tmp_path / (run_id + ".sqlite3"))
    journal.register_fee_pair_required_scope(
        candidate.key.account_scope, candidate.key.strategy_scope
    )
    owner_token = "writer-owner-" + run_id + "-" + "x" * 24
    reserved = journal.reserve_fee_pair_workflow_candidate(
        candidate, owner_token=owner_token, ttl_seconds=30.0
    )
    journal.record_fee_pair_workflow_append_claim(
        reserved.candidate_id, owner_token=owner_token
    )
    attached = journal.attach_verified_fee_pair_source_receipt(
        reserved.candidate_id, receipt, owner_token=owner_token
    )
    assert attached.state == "RECEIPT_VERIFIED"
    return SimpleNamespace(
        candidate=candidate,
        candidate_id=reserved.candidate_id,
        batch=batch,
        snapshot=snapshot,
        target_decision=target_decision,
        order_plan=order_plan,
        journal=journal,
        owner_token=owner_token,
        receipt=receipt,
        writer=writer,
    )


def _safe_close(harness):
    try:
        harness.writer.close()
    except Exception:
        pass
    harness.journal.close()


@pytest.fixture
def harness(tmp_path):
    value = _build_harness(tmp_path)
    try:
        yield value
    finally:
        _safe_close(value)


def _append(harness, *, order_plan=_DEFAULT_ORDER_PLAN):
    if order_plan is _DEFAULT_ORDER_PLAN:
        order_plan = harness.order_plan
    return harness.writer.record_fee_pair_grid_tape_append_observation(
        harness.candidate_id,
        harness.candidate,
        harness.batch,
        harness.snapshot,
        harness.target_decision,
        order_plan,
        harness.journal,
        owner_token=harness.owner_token,
    )


def _workflow_events(harness):
    return tuple(
        tuple(row)
        for row in harness.journal._connection.execute(
            "SELECT event_sequence,event_kind FROM execution_fee_pair_workflow_events "
            "WHERE candidate_id=? ORDER BY event_sequence",
            (harness.candidate_id,),
        )
    )


def _table_count(journal, table):
    return journal._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_grid_append_is_fsynced_read_back_idempotent_and_never_settles(harness):
    prefix_before = hashlib.sha256(harness.writer.path.read_bytes()).hexdigest()
    decisions_before = _table_count(harness.journal, "execution_decisions")
    intents_before = _table_count(harness.journal, "execution_decision_intents")

    observation = _append(harness)
    assert observation["evidence_level"] == "WRITER_LOCAL_FSYNC_AND_READBACK"
    assert observation["status"] == "APPENDED"
    assert observation["prefix_sha256"] == prefix_before
    assert observation["record_index"] == 2
    assert harness.candidate.expected_tape_record_index == 1
    assert observation["journal_tape_append_state"] == "REPORTED"
    assert observation["grid_settled"] is False
    assert observation["open_authorized"] is False

    rows = list(
        runner.iter_decision_tape(
            harness.writer.path,
            max_bytes=harness.writer.max_bytes,
            max_record_bytes=runner._FEE_PAIR_SOURCE_ONLY_MAX_RECORD_BYTES,
        )
    )
    assert len(rows) == 3
    assert rows[-1]["record_id"] == observation["record_id"]
    assert rows[-1]["record_index"] == observation["record_index"]
    assert rows[-1]["fee_pair_workflow"] == {
        "candidate_id": harness.candidate_id,
        "candidate_sha256": observation["candidate_sha256"],
    }
    assert rows[-1]["order_plan"] == {
        "status": "NO_ACTION",
        "reason": None,
        "decision_batch_id": harness.candidate.batch_id,
        "decision_available_at": harness.batch.available_at,
        "actions": [],
    }
    assert hashlib.sha256((harness.writer.path.read_bytes())).hexdigest() == (
        harness.writer.summary()["sha256"]
    )

    workflow = harness.journal.fee_pair_workflow_candidate(harness.candidate_id)
    assert workflow.state == "RECEIPT_VERIFIED"
    assert workflow.tape_append_state == "REPORTED"
    assert workflow.grid_settled_decision_id is None
    assert workflow.source_only_decision_id is None
    assert tuple(kind for _sequence, kind in _workflow_events(harness))[-3:] == (
        "GRID_TAPE_APPEND_INTENT",
        "GRID_TAPE_APPEND_CLAIMED",
        "GRID_TAPE_APPEND_REPORTED",
    )
    assert _table_count(harness.journal, "execution_decisions") == decisions_before
    assert _table_count(harness.journal, "execution_decision_intents") == intents_before

    # A repeated same-process callback verifies and returns the existing row;
    # it never writes a second row or repeats the Journal transition.
    bytes_after_first = harness.writer.path.read_bytes()
    events_after_first = _workflow_events(harness)
    repeated = _append(harness)
    assert repeated is observation
    assert harness.writer.path.read_bytes() == bytes_after_first
    assert _workflow_events(harness) == events_after_first
    assert harness.writer.summary()["record_count"] == 2


@pytest.mark.parametrize("conflict", ("tail", "identity"))
def test_prefix_tail_or_open_handle_identity_conflict_fails_before_intent(
    tmp_path, conflict
):
    harness = _build_harness(tmp_path, run_id="grid-writer-" + conflict)
    try:
        original_size = harness.writer.path.stat().st_size
        if conflict == "tail":
            with harness.writer.path.open("ab") as changed:
                changed.write(b"unauthorized-tail\n")
                changed.flush()
        else:
            twin_path = tmp_path / "same-bytes-different-file.jsonl"
            shutil.copyfile(harness.writer.path, twin_path)
            original_handle = harness.writer._handle
            harness.writer._handle = twin_path.open("r+b")
            original_handle.close()
            assert twin_path.stat().st_size == original_size

        with pytest.raises(runner.RunnerError):
            _append(harness)
        assert harness.writer.summary()["failed"] is True
        assert not any(
            kind == "GRID_TAPE_APPEND_INTENT"
            for _sequence, kind in _workflow_events(harness)
        )
        assert harness.writer.summary()["record_count"] == 1
    finally:
        _safe_close(harness)


@pytest.mark.parametrize("failure_point", ("fsync", "readback", "report"))
def test_post_intent_failures_leave_unresolved_and_do_not_settle(
    tmp_path, monkeypatch, failure_point
):
    harness = _build_harness(tmp_path, run_id="grid-writer-failure-" + failure_point)
    try:
        if failure_point == "fsync":
            original_fsync = runner.os.fsync
            calls = 0

            def fail_first_fsync(fd):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError("synthetic fsync failure")
                return original_fsync(fd)

            monkeypatch.setattr(runner.os, "fsync", fail_first_fsync)
            expected_error = "DECISION_TAPE_WRITE_FAILED"
        elif failure_point == "readback":
            def fail_readback(*_args, **_kwargs):
                raise runner.RunnerError("SYNTHETIC_READBACK_FAILURE")

            monkeypatch.setattr(
                harness.writer, "_verify_fee_pair_grid_append_row", fail_readback
            )
            expected_error = "SYNTHETIC_READBACK_FAILURE"
        else:
            def fail_report(*_args, **_kwargs):
                raise ExecutionDecisionJournalError("SYNTHETIC_REPORT_FAILURE")

            monkeypatch.setattr(
                harness.journal, "report_fee_pair_grid_tape_append", fail_report
            )
            expected_error = "SYNTHETIC_REPORT_FAILURE"

        with pytest.raises(Exception, match=expected_error):
            _append(harness)

        workflow = harness.journal.fee_pair_workflow_candidate(harness.candidate_id)
        assert workflow.state == "RECEIPT_VERIFIED"
        assert workflow.tape_append_state == "CLAIMED"
        assert workflow.grid_settled_decision_id is None
        assert harness.writer.summary()["failed"] is True
        assert not any(
            kind in {"GRID_TAPE_APPEND_REPORTED", "GRID_TAPE_APPEND_CONFLICT"}
            for _sequence, kind in _workflow_events(harness)
        )
        assert _table_count(harness.journal, "execution_decisions") == 0
        assert _table_count(harness.journal, "execution_decision_intents") == 0
        rows = list(
            runner.iter_decision_tape(
                harness.writer.path,
                max_bytes=harness.writer.max_bytes,
                max_record_bytes=runner._FEE_PAIR_SOURCE_ONLY_MAX_RECORD_BYTES,
            )
        )
        assert len(rows) == (2 if failure_point == "fsync" else 3)
    finally:
        _safe_close(harness)


def test_changed_repeat_is_a_conflict_without_a_second_physical_row(harness):
    first = _append(harness)
    before = harness.writer.path.read_bytes()
    events = _workflow_events(harness)
    changed_plan = SimpleNamespace(
        status="NO_ACTION",
        reason="synthetic-changed-request",
        decision_batch_id=harness.candidate.batch_id,
        decision_available_at=harness.batch.available_at,
        actions=(),
    )
    with pytest.raises(runner.RunnerError, match="FEE_PAIR_GRID_TAPE_APPEND_CONFLICT"):
        _append(harness, order_plan=changed_plan)
    assert harness.writer.path.read_bytes() == before
    assert _workflow_events(harness) == events
    assert harness.writer.summary()["record_count"] == 2
    workflow = harness.journal.fee_pair_workflow_candidate(harness.candidate_id)
    assert workflow.tape_append_state == "REPORTED"
    assert workflow.grid_settled_decision_id is None
    assert first["status"] == "APPENDED"
