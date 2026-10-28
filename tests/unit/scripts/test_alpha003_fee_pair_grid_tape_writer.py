"""Synthetic production-writer contracts for the v20 GRID tape append seam."""

from __future__ import annotations

from dataclasses import fields, replace
import hashlib
import importlib.util
from pathlib import Path
import shutil
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from backtrader.stores import execution_decision_journal as journal_module
from backtrader.stores import execution_journal_archive as archive_module
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
)
from backtrader.stores.execution_durable_capacity import DurableCapacityLimits
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
    if candidate.target_routes is not None:
        routes = {route.target_id: route.instrument for route in candidate.target_routes}
    else:
        routes = {"SIM-A": "rb2510", "SIM-B": "i2510"}
    authorized = list(candidate.target_ids)
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
        "targets": list(candidate.target_ids),
        "authorized_targets": authorized,
        "routes": routes,
        "calendar": {
            "calendar_id": candidate.calendar_id,
            "grid_sha256": _digest("synthetic-grid"),
        },
    }
    return identity, evidence


def _candidate_with_origin_partitions(candidate):
    targets = tuple(candidate.target_ids)
    if len(targets) != 2 or len(candidate.source_members) not in (1, 2):
        raise AssertionError("the pair writer fixture requires exactly two source targets")
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
    if len(source_members) == 2:
        second = source_members[1]
    else:
        template = source_members[0]
        second_id = targets[1]
        second_source_ref = "synthetic-ctp-{}".format(second_id.lower())
        second_partition = {
            "schema": runner.SOURCE_ORIGIN_PARTITION_SCHEMA,
            "cohort_id": candidate.key.cohort_id,
            "epoch_id": candidate.epoch_id,
            "member_id": second_id,
            "source_ref": second_source_ref,
            "source_role": "live",
            "connection_generation": template.connection_generation,
        }
        second = replace(
            template,
            member_id=second_id,
            source_ref=second_source_ref,
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
    if candidate.target_routes is not None:
        instrument_by_target = {
            route.target_id: route.instrument for route in candidate.target_routes
        }
        exchange_by_target = {
            route.target_id: route.exchange for route in candidate.target_routes
        }
    else:
        instrument_by_target = {"SIM-A": "rb2510", "SIM-B": "i2510"}
        exchange_by_target = {"SIM-A": "SHFE", "SIM-B": "DCE"}
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
            value=0.25 * candidate.directions[candidate.target_ids.index(member.member_id)],
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
                    exchange_id=exchange_by_target[target],
                    product_id=instrument_by_target[target],
                ),
                target_position=candidate.directions[index],
                raw_score=0.25 * candidate.directions[index],
                oriented_score=0.25 * candidate.directions[index],
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


def _build_single_row_harness(tmp_path, run_id="grid-writer-v23"):
    case, candidate, quote_by_route = workflow_fixtures._fee_pair_settlement_fixture(run_id)
    candidate = _candidate_with_origin_partitions(candidate)
    identity, evidence = _selection_inputs(candidate)
    writer = runner.DecisionTapeWriter(
        tmp_path / (run_id + ".jsonl"),
        2 * 1024 * 1024,
        mode="live",
        factor_mode="native",
        direction=1,
        targets=tuple(candidate.target_ids),
        calendar_id=candidate.calendar_id,
        grid_sha256=identity["calendar"]["grid_sha256"],
        source_snapshot_id=None,
        restart_identity=identity,
        selection_evidence=evidence,
        calendar_fingerprint=candidate.calendar_fingerprint,
        cross_process_generation_lease=True,
    )
    candidate = replace(
        candidate,
        expected_tape_file_id=writer.file_id,
        expected_tape_record_index=writer._record_count + 1,
    )
    batch, snapshot, target_decision, _empty_plan = _objects(candidate)
    target_decision.status = "TARGETS_READY"
    receipt = journal_module._fee_pair_receipt_from_candidate(candidate, "0" * 64)
    payload = dict(
        workflow_fixtures._fee_pair_grid_economic_payload(
            candidate, case.facts, quote_by_route, receipt
        )
    )
    payload["decision_tape_record_id"] = None
    payload["proposed_actions"] = [
        {**action, "decision_available_at": batch.available_at}
        for action in payload["proposed_actions"]
    ]
    planned_actions = []
    for action in payload["proposed_actions"]:
        planned_actions.append(
            SimpleNamespace(
                action=action["action"],
                target_id=action["target_id"],
                instrument=action["instrument"],
                side=action["side"],
                position_effect=action["position_effect"],
                quantity=action["quantity"],
                limit_price=action["limit_price"],
                offset="OPEN",
                reason="synthetic-ready-pair",
                planned_stop_price=action["planned_stop_price"],
                exchange=action["exchange"],
                decision_available_at=action["decision_available_at"],
                entry_grid_ordinal=action["entry_grid_ordinal"],
            )
        )
    order_plan = SimpleNamespace(
        status="READY",
        reason=None,
        decision_batch_id=candidate.batch_id,
        decision_available_at=batch.available_at,
        actions=tuple(planned_actions),
    )
    journal = ExecutionDecisionJournal(
        tmp_path / (run_id + ".sqlite3"),
        max_payload_bytes=runner._LIVE_DECISION_JOURNAL_MAX_PAYLOAD_BYTES,
    )
    journal.register_fee_pair_required_scope(
        candidate.key.account_scope, candidate.key.strategy_scope
    )
    owner_token = "writer-v23-owner-" + run_id + "-" + "x" * 24
    return SimpleNamespace(
        candidate=candidate,
        batch=batch,
        snapshot=snapshot,
        target_decision=target_decision,
        order_plan=order_plan,
        journal=journal,
        owner_token=owner_token,
        writer=writer,
        facts=case.facts,
        economic_payload=payload,
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


def _settle_single_row(harness, *, economic_payload=None):
    return harness.writer.settle_fee_pair_grid_single_row(
        harness.candidate,
        harness.batch,
        harness.snapshot,
        harness.target_decision,
        harness.order_plan,
        harness.journal,
        owner_token=harness.owner_token,
        facts=harness.facts,
        economic_payload=(
            harness.economic_payload if economic_payload is None else economic_payload
        ),
        current_account_session_id=harness.candidate.account_session_id,
        current_account_session_generation=harness.candidate.account_session_generation,
        max_query_age_seconds=20.0,
        max_quote_age_seconds=10.0,
        max_order_intents_per_run=100,
        expected_run_order_intents_used=0,
        remaining_exit_intent_reserve=0,
    )


@pytest.fixture
def single_row_harness(tmp_path):
    value = _build_single_row_harness(tmp_path)
    try:
        yield value
    finally:
        _safe_close(value)


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


def test_v23_writer_appends_one_row_and_settles_the_same_physical_receipt(
    single_row_harness,
):
    harness = single_row_harness
    append_calls = []
    original_append = harness.writer._append

    def counted_append(raw, *, count_record):
        append_calls.append((raw, count_record))
        return original_append(raw, count_record=count_record)

    harness.writer._append = counted_append
    result = _settle_single_row(harness)

    assert len(append_calls) == 1
    assert append_calls[0][1] is True
    assert result["schema"] == "backtrader.alpha003.single_row_grid_settlement.v1"
    assert result["evidence_level"] == (
        "WRITER_LEASED_PHYSICAL_READBACK_AND_JOURNAL_SETTLEMENT"
    )
    assert result["is_new_grid"] is True
    assert result["open_dispatch_authorized"] is False
    assert result["source_receipt"].tape_file_id == harness.writer.file_id
    assert result["source_receipt"].tape_record_id == result["tape_reference"]["record_id"]
    assert result["source_receipt"].tape_record_index == 1

    rows = list(
        runner.iter_decision_tape(
            harness.writer.path,
            max_bytes=harness.writer.max_bytes,
            max_record_bytes=runner._FEE_PAIR_SOURCE_ONLY_MAX_RECORD_BYTES,
        )
    )
    assert len(rows) == 2  # header plus exactly one complete LIVE_READY GRID row
    tape_row = rows[1]
    assert tape_row["record_index"] == 1
    assert tape_row["readiness"] == "LIVE_READY"
    assert tape_row["target_decision"]["status"] == "TARGETS_READY"
    assert tape_row["order_plan"]["status"] == "READY"
    assert len(tape_row["order_plan"]["actions"]) == 2
    for target, member in tape_row["members"].items():
        source = next(
            item for item in harness.candidate.source_members if item.member_id == target
        )
        assert member["raw_values"] == {
            "close": 101.0,
            "high": 102.0,
            "low": 99.0,
            "open": 100.0,
            "openinterest": 0.0,
            "volume": 7.0,
        }
        assert member["source_role"] == source.source_role
        assert member["origin_partition"] == dict(source.origin_partition)
    assert harness.writer.summary()["record_count"] == 1
    assert harness.writer.summary()["sha256"] == hashlib.sha256(
        harness.writer.path.read_bytes()
    ).hexdigest()

    workflow = harness.journal.fee_pair_workflow_candidate(result["candidate_id"])
    assert workflow.state == "RECEIPT_VERIFIED"
    assert workflow.grid_settled_decision_id == result["decision"].decision_id
    assert workflow.source_only_decision_id is None
    assert harness.journal._connection.execute(
        "SELECT COUNT(*) FROM execution_fee_pair_grid_single_row_tape_intents"
    ).fetchone()[0] == 1
    stored_intent = harness.journal._connection.execute(
        """SELECT record_json,record_id,tape_file_id,record_index
           FROM execution_fee_pair_grid_single_row_tape_intents WHERE candidate_id=?""",
        (result["candidate_id"],),
    ).fetchone()
    assert stored_intent["record_json"] == runner._canonical_json_bytes(dict(tape_row)).decode(
        "utf-8"
    ).rstrip("\n")
    assert stored_intent["record_id"] == tape_row["record_id"]
    assert stored_intent["tape_file_id"] == harness.writer.file_id
    assert stored_intent["record_index"] == 1

    highwater = harness.journal.source_highwater(
        harness.candidate.key.account_scope,
        harness.candidate.key.strategy_scope,
        harness.candidate.key.logical_run_id,
        harness.candidate.source_kind,
    )
    assert highwater.anchor_kind == "GRID"
    assert highwater.receipt == result["source_receipt"]
    assert harness.journal.grid_cursor(
        harness.candidate.key.account_scope,
        harness.candidate.key.strategy_scope,
        harness.candidate.key.cohort_id,
    ).ordinal == 1
    assert _table_count(harness.journal, "execution_decisions") == 1
    assert _table_count(harness.journal, "execution_source_highwaters") == 1
    assert _table_count(harness.journal, "execution_fee_pair_workflow_grid_settlements") == 1
    assert _table_count(harness.journal, "execution_decision_intents") == 0

    with pytest.raises(
        ExecutionDecisionJournalError,
        match="FEE_PAIR_OPEN_RISK_RESERVATION_REQUIRED",
    ):
        harness.journal.prepare_intent(
            result["decision"].decision_id,
            result["decision"].intent_keys[0],
            result["decision"].economic_payload["intent_economics"][0],
        )
    assert _table_count(harness.journal, "execution_decision_intents") == 0


@pytest.mark.parametrize("changed_component", ("leg_action", "leg_economics"))
def test_v23_settlement_rejects_economics_different_from_the_tape_row(
    tmp_path, monkeypatch, changed_component
):
    harness = _build_single_row_harness(
        tmp_path, run_id="grid-writer-v23-bind-" + changed_component
    )
    try:
        original_settle = harness.journal.settle_fee_pair_grid_decision

        def settle_changed_plan(*args, **kwargs):
            changed = dict(kwargs["economic_payload"])
            if changed_component == "leg_action":
                actions = [dict(item) for item in changed["proposed_actions"]]
                actions[0]["quantity"] += 1
                changed["proposed_actions"] = actions
            else:
                economics = [dict(item) for item in changed["intent_economics"]]
                economics[1]["quantity"] += 1
                changed["intent_economics"] = economics
            kwargs["economic_payload"] = changed
            return original_settle(*args, **kwargs)

        monkeypatch.setattr(harness.journal, "settle_fee_pair_grid_decision", settle_changed_plan)
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_SINGLE_ROW_TAPE_PLAN_BINDING_INVALID",
        ):
            _settle_single_row(harness)
        assert harness.writer.summary()["failed"] is True
        rows = list(
            runner.iter_decision_tape(
                harness.writer.path,
                max_bytes=harness.writer.max_bytes,
                max_record_bytes=runner._FEE_PAIR_SOURCE_ONLY_MAX_RECORD_BYTES,
            )
        )
        assert len(rows) == 2
        workflow = harness.journal.fee_pair_workflow_candidate(
            _table_count(harness.journal, "execution_fee_pair_workflows")
            and harness.journal._connection.execute(
                "SELECT candidate_id FROM execution_fee_pair_workflows"
            ).fetchone()[0]
        )
        assert workflow.state == "APPEND_CLAIMED"
        assert workflow.grid_settled_decision_id is None
        assert harness.journal.source_highwater(
            harness.candidate.key.account_scope,
            harness.candidate.key.strategy_scope,
            harness.candidate.key.logical_run_id,
            harness.candidate.source_kind,
        ) is None
        for table in (
            "execution_decisions",
            "execution_source_highwaters",
            "execution_grid_cursors",
            "execution_grid_highwaters",
            "execution_fee_pair_workflow_grid_settlements",
            "execution_decision_intents",
        ):
            assert _table_count(harness.journal, table) == 0
    finally:
        _safe_close(harness)


@pytest.mark.parametrize("failure_point", ("append", "readback"))
def test_v23_post_claim_failure_keeps_grid_unresolved_and_no_highwater(
    tmp_path, monkeypatch, failure_point
):
    harness = _build_single_row_harness(
        tmp_path, run_id="grid-writer-v23-failure-" + failure_point
    )
    try:
        if failure_point == "append":
            def fail_append(_raw, *, count_record):
                assert count_record is True
                raise OSError("synthetic single-row append failure")

            monkeypatch.setattr(harness.writer, "_append", fail_append)
            expected = "synthetic single-row append failure"
        else:
            def fail_readback(**_kwargs):
                raise ExecutionDecisionJournalError("SYNTHETIC_V23_READBACK_FAILURE")

            monkeypatch.setattr(
                harness.journal,
                "_verify_fee_pair_grid_single_row_tape_readback_in_transaction",
                fail_readback,
            )
            expected = "SYNTHETIC_V23_READBACK_FAILURE"
        with pytest.raises(Exception, match=expected):
            _settle_single_row(harness)

        assert harness.writer.summary()["failed"] is True
        rows = list(
            runner.iter_decision_tape(
                harness.writer.path,
                max_bytes=harness.writer.max_bytes,
                max_record_bytes=runner._FEE_PAIR_SOURCE_ONLY_MAX_RECORD_BYTES,
            )
        )
        assert len(rows) == (1 if failure_point == "append" else 2)
        candidate_id = harness.journal._connection.execute(
            "SELECT candidate_id FROM execution_fee_pair_workflows"
        ).fetchone()[0]
        workflow = harness.journal.fee_pair_workflow_candidate(candidate_id)
        assert workflow.state == "APPEND_CLAIMED"
        assert workflow.grid_settled_decision_id is None
        assert harness.journal.source_highwater(
            harness.candidate.key.account_scope,
            harness.candidate.key.strategy_scope,
            harness.candidate.key.logical_run_id,
            harness.candidate.source_kind,
        ) is None
        for table in (
            "execution_decisions",
            "execution_source_highwaters",
            "execution_grid_cursors",
            "execution_grid_highwaters",
            "execution_fee_pair_workflow_grid_settlements",
        ):
            assert _table_count(harness.journal, table) == 0
    finally:
        _safe_close(harness)


def test_v23_claim_capacity_reserves_intent_before_any_physical_append(
    tmp_path, monkeypatch
):
    harness = _build_single_row_harness(tmp_path, run_id="grid-writer-v23-capacity")
    try:
        original_claim = harness.journal.record_fee_pair_grid_single_row_append_claim

        def cap_at_existing_reservation(*args, **kwargs):
            base = harness.journal._connection.execute(
                """SELECT record_count FROM execution_durable_capacity_usage
                   WHERE capacity_class='BASE'"""
            ).fetchone()[0]
            workflow_reserved = harness.journal._connection.execute(
                """SELECT COALESCE(SUM(reserved_records),0)
                   FROM execution_fee_pair_workflow_durable_reservations
                   WHERE state='ACTIVE'"""
            ).fetchone()[0]
            candidate_reserved = harness.journal._connection.execute(
                """SELECT COALESCE(SUM(reserved_records),0)
                   FROM execution_fee_pair_candidate_capacity_reservations
                   WHERE state='RESERVED'"""
            ).fetchone()[0]
            current_bytes = harness.journal._connection.execute(
                """SELECT payload_bytes FROM execution_durable_capacity_usage
                   WHERE capacity_class='BASE'"""
            ).fetchone()[0]
            workflow_bytes = harness.journal._connection.execute(
                """SELECT COALESCE(SUM(reserved_bytes),0)
                   FROM execution_fee_pair_workflow_durable_reservations
                   WHERE state='ACTIVE'"""
            ).fetchone()[0]
            candidate_bytes = harness.journal._connection.execute(
                """SELECT COALESCE(SUM(reserved_bytes),0)
                   FROM execution_fee_pair_candidate_capacity_reservations
                   WHERE state='RESERVED'"""
            ).fetchone()[0]
            harness.journal.durable_capacity_limits = DurableCapacityLimits(
                max_durable_base_records=base + workflow_reserved + candidate_reserved,
                max_durable_base_bytes=current_bytes + workflow_bytes + candidate_bytes,
                max_durable_settlement_records=100_000,
                max_durable_settlement_bytes=1_073_741_824,
            )
            return original_claim(*args, **kwargs)

        monkeypatch.setattr(
            harness.journal,
            "record_fee_pair_grid_single_row_append_claim",
            cap_at_existing_reservation,
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="DURABLE_BASE_RECORDS_EXHAUSTED"
        ):
            _settle_single_row(harness)
        assert harness.writer.summary()["failed"] is True
        assert harness.writer.summary()["record_count"] == 0
        rows = list(
            runner.iter_decision_tape(
                harness.writer.path,
                max_bytes=harness.writer.max_bytes,
                max_record_bytes=runner._FEE_PAIR_SOURCE_ONLY_MAX_RECORD_BYTES,
            )
        )
        assert len(rows) == 1
        workflow = harness.journal._connection.execute(
            """SELECT state,grid_decision_id FROM execution_fee_pair_workflows"""
        ).fetchone()
        assert tuple(workflow) == ("RESERVED", None)
        assert _table_count(harness.journal, "execution_fee_pair_grid_single_row_tape_intents") == 0
        assert _table_count(harness.journal, "execution_decisions") == 0
        assert _table_count(harness.journal, "execution_source_highwaters") == 0
    finally:
        _safe_close(harness)


def test_v23_archive_rejects_an_oversized_single_row_tape_intent(
    tmp_path, single_row_harness
):
    harness = single_row_harness
    settled = _settle_single_row(harness)
    archive_path = tmp_path / "grid-writer-v23-archive.sqlite3"
    archived = harness.journal.archive_snapshot(archive_path)
    assert archived.schema_version == 23

    oversized = "x" * journal_module._MAX_FEE_PAIR_GRID_TAPE_RECORD_BYTES
    with sqlite3.connect(archive_path) as connection:
        connection.execute(
            "DROP TRIGGER execution_fee_pair_grid_single_row_tape_intent_no_update"
        )
        connection.execute(
            """UPDATE execution_fee_pair_grid_single_row_tape_intents
               SET record_json=? WHERE candidate_id=?""",
            (oversized, settled["candidate_id"]),
        )

    with pytest.raises(
        archive_module.ExecutionJournalArchiveError,
        match="ARCHIVE_FEE_PAIR_TAPE_RECORD_TOO_LARGE",
    ):
        archive_module.verify_execution_journal_archive(
            archive_path, expected_schema_version=23
        )
