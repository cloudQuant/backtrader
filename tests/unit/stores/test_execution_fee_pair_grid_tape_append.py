"""Synthetic contracts for the Journal's fail-closed GRID tape append intent."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace

import pytest

from backtrader.stores import execution_decision_journal as journal_module
from backtrader.stores import execution_journal_archive as archive_module
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
)
from tests.unit.stores import test_execution_fee_pair_candidate_journal as workflow_fixtures


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _intent(candidate, candidate_id):
    header_record_id = _digest("synthetic-header")
    record_index = candidate.expected_tape_record_index + 1
    row = {
        "schema": "backtrader.alpha003.decision_tape.v2",
        "record_type": "DECISION",
        "file_id": candidate.expected_tape_file_id,
        "record_index": record_index,
        "header_record_id": header_record_id,
        "fee_pair_workflow": {
            "candidate_id": candidate_id,
            "candidate_sha256": _digest(
                journal_module._canonical_json(journal_module._fee_pair_candidate_values(candidate))
            ),
        },
        "batch_id": candidate.batch_id,
        "cohort_id": candidate.key.cohort_id,
        "calendar_id": candidate.calendar_id,
        "calendar_version": candidate.calendar_version,
        "calendar_fingerprint": candidate.calendar_fingerprint,
        "epoch_id": candidate.epoch_id,
        "slot_index": candidate.slot_index,
        "slot_id": candidate.slot_id,
        "close_time": candidate.key.close_time,
        "readiness": candidate.readiness,
        "target_decision": {
            "cohort_id": candidate.key.cohort_id,
            "batch_id": candidate.batch_id,
            "close_time": candidate.key.close_time,
        },
    }
    row["record_id"] = _digest(journal_module._canonical_tape_record_json(row))
    record_json = journal_module._canonical_tape_record_json(row)
    return {
        "tape_file_id": candidate.expected_tape_file_id,
        "header_record_id": header_record_id,
        "record_index": record_index,
        "prefix_sha256": _digest("synthetic-prefix"),
        "record_json": record_json,
    }


def _report(intent, *, disposition="APPENDED", changed=None):
    row = json.loads(intent["record_json"])
    values = {
        "disposition": disposition,
        "observed_file_id": row["file_id"],
        "observed_header_record_id": row["header_record_id"],
        "observed_record_index": row["record_index"],
        "observed_prefix_sha256": intent["prefix_sha256"],
        "observed_record_id": row["record_id"],
        "observed_record_sha256": hashlib.sha256(
            (intent["record_json"] + "\n").encode("utf-8")
        ).hexdigest(),
    }
    if changed is not None:
        values[changed] = _digest("different-" + changed)
    return values


def _record_intent(journal, candidate_id, token, intent):
    return journal.reserve_fee_pair_grid_tape_append_intent(
        candidate_id,
        owner_token=token,
        **intent,
    )


def _claim(journal, candidate_id, token):
    return journal.claim_fee_pair_grid_tape_append(candidate_id, owner_token=token)


def _report_append(journal, candidate_id, token, report):
    return journal.report_fee_pair_grid_tape_append(
        candidate_id,
        owner_token=token,
        disposition=report["disposition"],
        observed_file_id=report["observed_file_id"],
        observed_header_record_id=report["observed_header_record_id"],
        observed_record_index=report["observed_record_index"],
        observed_prefix_sha256=report["observed_prefix_sha256"],
        observed_record_id=report["observed_record_id"],
        observed_record_sha256=report["observed_record_sha256"],
    )


def _tamper_tape_intent_record(connection, candidate_id, record_json):
    connection.execute("DROP TRIGGER execution_fee_pair_workflow_event_no_update")
    connection.execute(
        """UPDATE execution_fee_pair_workflow_events
           SET tape_record_json=?
           WHERE candidate_id=? AND event_sequence=4
             AND event_kind='GRID_TAPE_APPEND_INTENT'""",
        (record_json, candidate_id),
    )
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_EVENT_NO_UPDATE_TRIGGER_SQL)


def _prepared_workflow(journal, candidate, token):
    journal.register_fee_pair_required_scope(
        candidate.key.account_scope, candidate.key.strategy_scope
    )
    return workflow_fixtures._attach_fee_pair_receipt(journal, candidate, token)


def test_oversized_intent_is_rejected_before_json_parse(tmp_path, monkeypatch):
    limit = journal_module._MAX_FEE_PAIR_GRID_TAPE_RECORD_BYTES
    oversized_records = ("x" * limit, "\u0800" * (limit // 3 + 1))
    journal = ExecutionDecisionJournal(tmp_path / "grid-tape-append-oversized-input.sqlite3")
    try:
        candidate_id = _digest("oversized-input-candidate")
        token = "grid-tape-append-owner-" + "z" * 32
        for record_json in oversized_records:
            json_parse_attempts = []
            original_loads = json.loads

            def guarded_loads(
                value,
                *args,
                _record_json=record_json,
                _attempts=json_parse_attempts,
                _original_loads=original_loads,
                **kwargs,
            ):
                if type(value) is str and value == _record_json:
                    _attempts.append(True)
                    raise AssertionError("oversized tape intent reached JSON parsing")
                return _original_loads(value, *args, **kwargs)

            with monkeypatch.context() as patcher:
                patcher.setattr(journal_module.json, "loads", guarded_loads)
                with pytest.raises(
                    ExecutionDecisionJournalError,
                    match="FEE_PAIR_GRID_TAPE_INTENT_INVALID",
                ):
                    journal.reserve_fee_pair_grid_tape_append_intent(
                        candidate_id,
                        owner_token=token,
                        tape_file_id=_digest("oversized-input-file"),
                        header_record_id=_digest("oversized-input-header"),
                        record_index=1,
                        prefix_sha256=_digest("oversized-input-prefix"),
                        record_json=record_json,
                    )
            assert json_parse_attempts == []
    finally:
        journal.close()


def test_intent_claim_and_matching_report_are_idempotent_and_caller_only(tmp_path):
    candidate = workflow_fixtures._candidate(run_id="grid-tape-append-idempotent")
    token = "grid-tape-append-owner-" + "a" * 32
    journal = ExecutionDecisionJournal(tmp_path / "grid-tape-append-idempotent.sqlite3")
    try:
        candidate_id, _receipt = _prepared_workflow(journal, candidate, token)
        intent = _intent(candidate, candidate_id)

        first = _record_intent(journal, candidate_id, token, intent)
        second = _record_intent(journal, candidate_id, token, intent)
        assert first.tape_append_state == second.tape_append_state == "INTENT"
        reserved = journal._connection.execute(
            "SELECT reserved_records,reserved_bytes,state "
            "FROM execution_fee_pair_workflow_durable_reservations WHERE candidate_id=?",
            (candidate_id,),
        ).fetchone()
        assert tuple(reserved)[0] == 12
        assert tuple(reserved)[2] == "ACTIVE"

        claimed = _claim(journal, candidate_id, token)
        replayed_claim = _claim(journal, candidate_id, token)
        assert claimed.tape_append_state == replayed_claim.tape_append_state == "CLAIMED"
        assert (
            journal._connection.execute(
                "SELECT reserved_records FROM execution_fee_pair_workflow_durable_reservations "
                "WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()[0]
            == 11
        )
        assert (
            journal._connection.execute(
                "SELECT COUNT(*) FROM execution_fee_pair_workflow_events "
                "WHERE candidate_id=? AND event_kind='GRID_TAPE_APPEND_CLAIMED'",
                (candidate_id,),
            ).fetchone()[0]
            == 1
        )

        report = _report(intent)
        reported = _report_append(journal, candidate_id, token, report)
        replayed_report = _report_append(journal, candidate_id, token, report)
        assert reported.tape_append_state == replayed_report.tape_append_state == "REPORTED"
        assert reported.state == "RECEIPT_VERIFIED"
        assert reported.grid_settled_decision_id is None
        assert (
            journal._connection.execute(
                "SELECT reserved_records FROM execution_fee_pair_workflow_durable_reservations "
                "WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()[0]
            == 10
        )
        saved_report = json.loads(
            journal._connection.execute(
                "SELECT event_payload_json FROM execution_fee_pair_workflow_events "
                "WHERE candidate_id=? AND event_sequence=6",
                (candidate_id,),
            ).fetchone()[0]
        )
        assert saved_report["state"] == "GRID_TAPE_APPEND_REPORTED"
        assert saved_report["report"] == report
        # The Journal records only the caller's statement; it has no tape handle.
        assert "physical" not in saved_report

        source_only = journal.finalize_fee_pair_source_only_from_attached_receipt(
            candidate_id, owner_token=token
        )
        finalized = journal.fee_pair_workflow_candidate(candidate_id)
        assert source_only.is_noop
        assert finalized.state == "SOURCE_ONLY"
        assert finalized.tape_append_state == "REPORTED"
        assert finalized.grid_settled_decision_id is None
        reservation = journal._connection.execute(
            "SELECT reserved_records,reserved_bytes,state "
            "FROM execution_fee_pair_workflow_durable_reservations WHERE candidate_id=?",
            (candidate_id,),
        ).fetchone()
        assert tuple(reservation) == (0, 0, "CONSUMED")

        archive_path = tmp_path / "grid-tape-append-archive.sqlite3"
        archived_receipt = journal.archive_snapshot(archive_path)
        verified = archive_module.verify_execution_journal_archive(
            archive_path,
            expected_schema_version=23,
            expected_sha256=archived_receipt.sha256,
        )
        assert verified == archived_receipt
        with sqlite3.connect(archive_path) as archived:
            rows = tuple(
                tuple(row)
                for row in archived.execute(
                    "SELECT event_sequence,event_kind,tape_file_id,record_index,tape_record_json "
                    "FROM execution_fee_pair_workflow_events WHERE candidate_id=? "
                    "ORDER BY event_sequence",
                    (candidate_id,),
                )
            )
        assert tuple(row[0:2] for row in rows) == (
            (1, "RESERVED"),
            (2, "APPEND_CLAIMED"),
            (3, "RECEIPT_VERIFIED"),
            (4, "GRID_TAPE_APPEND_INTENT"),
            (5, "GRID_TAPE_APPEND_CLAIMED"),
            (6, "GRID_TAPE_APPEND_REPORTED"),
            (7, "SOURCE_ONLY"),
        )
        assert rows[3][2:4] == (intent["tape_file_id"], intent["record_index"])
        assert rows[3][4] == intent["record_json"]
    finally:
        journal.close()


def test_pending_and_conflicting_append_cannot_finalize_source_only(tmp_path):
    candidate = workflow_fixtures._candidate(run_id="grid-tape-append-fail-closed")
    token = "grid-tape-append-owner-" + "b" * 32
    journal = ExecutionDecisionJournal(tmp_path / "grid-tape-append-fail-closed.sqlite3")
    try:
        candidate_id, _receipt = _prepared_workflow(journal, candidate, token)
        intent = _intent(candidate, candidate_id)
        _record_intent(journal, candidate_id, token, intent)
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_GRID_TAPE_APPEND_UNRESOLVED"
        ):
            journal.finalize_fee_pair_source_only_from_attached_receipt(
                candidate_id, owner_token=token
            )

        _claim(journal, candidate_id, token)
        conflict = _report(intent, changed="observed_record_id")
        conflicted = _report_append(journal, candidate_id, token, conflict)
        assert conflicted.tape_append_state == "CONFLICT"
        assert (
            _report_append(journal, candidate_id, token, conflict).tape_append_state == "CONFLICT"
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_GRID_TAPE_APPEND_UNRESOLVED"
        ):
            journal.finalize_fee_pair_source_only_from_attached_receipt(
                candidate_id, owner_token=token
            )
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_GRID_TAPE_REPORT_CONFLICT"
        ):
            _report_append(journal, candidate_id, token, _report(intent))
        assert journal.fee_pair_workflow_candidate(candidate_id).state == "RECEIPT_VERIFIED"
        assert journal.fee_pair_workflow_candidate(candidate_id).grid_settled_decision_id is None
    finally:
        journal.close()


def test_reopened_pending_intent_is_recognized_but_process_change_cannot_take_over(
    tmp_path, monkeypatch
):
    path = tmp_path / "grid-tape-append-reopen.sqlite3"
    candidate = workflow_fixtures._candidate(run_id="grid-tape-append-reopen")
    token = "grid-tape-append-owner-" + "c" * 32
    journal = ExecutionDecisionJournal(path)
    candidate_id, _receipt = _prepared_workflow(journal, candidate, token)
    intent = _intent(candidate, candidate_id)
    _record_intent(journal, candidate_id, token, intent)
    journal.close()

    reopened = ExecutionDecisionJournal(path)
    try:
        assert reopened.fee_pair_workflow_candidate(candidate_id).tape_append_state == "INTENT"
        assert reopened.fee_pair_workflow_candidate(candidate_id).state == "RECEIPT_VERIFIED"
        monkeypatch.setattr(journal_module, "_PROCESS_INSTANCE_NONCE", "simulated-new-process")
        with pytest.raises(ExecutionDecisionJournalError, match="FEE_PAIR_WORKFLOW_OWNER_MISMATCH"):
            _claim(reopened, candidate_id, token)
        assert reopened.fee_pair_workflow_candidate(candidate_id).tape_append_state == "INTENT"
    finally:
        reopened.close()


def test_caller_report_never_authorizes_grid_settlement(tmp_path):
    case, candidate, quote_by_route = workflow_fixtures._fee_pair_settlement_fixture(
        "grid-tape-append-no-open"
    )
    token = "grid-tape-append-owner-" + "d" * 32
    journal = ExecutionDecisionJournal(tmp_path / "grid-tape-append-no-open.sqlite3")
    try:
        candidate_id, receipt = _prepared_workflow(journal, candidate, token)
        intent = _intent(candidate, candidate_id)
        _record_intent(journal, candidate_id, token, intent)
        _claim(journal, candidate_id, token)
        _report_append(journal, candidate_id, token, _report(intent))
        payload = workflow_fixtures._fee_pair_grid_economic_payload(
            candidate, case.facts, quote_by_route, receipt
        )
        kwargs = {
            "owner_token": token,
            "facts": case.facts,
            "current_account_session_id": candidate.account_session_id,
            "current_account_session_generation": candidate.account_session_generation,
            "max_query_age_seconds": 20.0,
            "max_quote_age_seconds": 10.0,
            "economic_payload": payload,
            "max_order_intents_per_run": 100,
            "expected_run_order_intents_used": 0,
            "remaining_exit_intent_reserve": 0,
        }
        before_usage = tuple(
            tuple(row)
            for row in journal._connection.execute(
                "SELECT capacity_class,record_count,payload_bytes "
                "FROM execution_durable_capacity_usage ORDER BY capacity_class"
            )
        )
        before_decision_count = journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decisions"
        ).fetchone()[0]
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_GRID_TAPE_PHYSICAL_VERIFICATION_REQUIRED",
        ):
            journal.settle_fee_pair_grid_decision(candidate_id, **kwargs)
        assert (
            journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0]
            == before_decision_count
        )
        assert (
            journal._connection.execute(
                "SELECT COUNT(*) FROM execution_fee_pair_workflow_grid_settlements "
                "WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()[0]
            == 0
        )
        after_usage = tuple(
            tuple(row)
            for row in journal._connection.execute(
                "SELECT capacity_class,record_count,payload_bytes "
                "FROM execution_durable_capacity_usage ORDER BY capacity_class"
            )
        )
        assert after_usage == before_usage
        assert journal.fee_pair_workflow_candidate(candidate_id).grid_settled_decision_id is None
    finally:
        journal.close()


def test_tape_position_and_numeric_identity_are_exact(tmp_path):
    token = "grid-tape-append-owner-" + "e" * 32
    journal = ExecutionDecisionJournal(tmp_path / "grid-tape-append-position.sqlite3")
    try:
        first = workflow_fixtures._candidate(run_id="grid-tape-position-first")
        first_id, _ = _prepared_workflow(journal, first, token)
        first_intent = _intent(first, first_id)
        _record_intent(journal, first_id, token, first_intent)

        second = workflow_fixtures._candidate(run_id="grid-tape-position-second")
        second = replace(
            second,
            key=replace(
                second.key,
                account_scope="pair-account-two",
                strategy_scope="pair-strategy-two",
            ),
        )
        second_id, _ = _prepared_workflow(journal, second, token)
        second_intent = _intent(second, second_id)
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_GRID_TAPE_POSITION_ALREADY_RESERVED",
        ):
            _record_intent(journal, second_id, token, second_intent)

        malformed = json.loads(second_intent["record_json"])
        malformed["slot_index"] = bool(second.slot_index)
        malformed.pop("record_id")
        malformed["record_id"] = _digest(journal_module._canonical_tape_record_json(malformed))
        second_intent["record_json"] = journal_module._canonical_tape_record_json(malformed)
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_GRID_TAPE_INTENT_INVALID"
        ):
            _record_intent(journal, second_id, token, second_intent)
    finally:
        journal.close()


@pytest.mark.parametrize("encoding", ("UTF-8", "UTF-16le"))
def test_v23_archive_roundtrip_bounds_legacy_tape_intent_rows(tmp_path, encoding):
    candidate = workflow_fixtures._candidate(run_id="grid-tape-archive-bounds")
    token = "grid-tape-append-owner-" + "f" * 32
    source_path = tmp_path / "grid-tape-archive-bounds-source.sqlite3"
    archive_path = tmp_path / "grid-tape-archive-bounds-snapshot.sqlite3"
    if encoding != "UTF-8":
        with sqlite3.connect(source_path) as bootstrap:
            bootstrap.execute("PRAGMA encoding='{}'".format(encoding))
            bootstrap.execute("CREATE TABLE encoding_seed (value TEXT)")
            bootstrap.execute("DROP TABLE encoding_seed")
    journal = ExecutionDecisionJournal(source_path)
    try:
        source_encoding = journal._connection.execute("PRAGMA encoding").fetchone()[0]
        assert source_encoding.upper() == encoding.upper()
        candidate_id, _receipt = _prepared_workflow(journal, candidate, token)
        intent = _intent(candidate, candidate_id)
        _record_intent(journal, candidate_id, token, intent)
        receipt = journal.archive_snapshot(archive_path)
        assert receipt.schema_version == 23
    finally:
        journal.close()

    verified = archive_module.verify_execution_journal_archive(
        archive_path, expected_schema_version=23
    )
    assert verified.schema_version == 23
    archived_journal = ExecutionDecisionJournal(archive_path)
    try:
        restored = archived_journal.fee_pair_workflow_candidate(candidate_id)
        assert restored is not None
        assert restored.tape_append_state == "INTENT"
    finally:
        archived_journal.close()

    oversized = "x" * journal_module._MAX_FEE_PAIR_GRID_TAPE_RECORD_BYTES
    with sqlite3.connect(archive_path) as archived:
        _tamper_tape_intent_record(archived, candidate_id, oversized)
        archived.commit()
        archived.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        archived.execute("PRAGMA journal_mode=DELETE")

    with pytest.raises(
        archive_module.ExecutionJournalArchiveError,
        match="ARCHIVE_FEE_PAIR_TAPE_RECORD_TOO_LARGE",
    ):
        archive_module.verify_execution_journal_archive(archive_path, expected_schema_version=23)


@pytest.mark.parametrize("encoding", ("UTF-8", "UTF-16le"))
def test_oversized_persisted_intent_is_rejected_before_event_fetch_or_json_parse(
    tmp_path, monkeypatch, encoding
):
    candidate = workflow_fixtures._candidate(run_id="grid-tape-corrupt-intent-bound")
    token = "grid-tape-append-owner-" + "g" * 32
    journal_path = tmp_path / "grid-tape-corrupt-intent-bound.sqlite3"
    if encoding.upper() != "UTF-8":
        with sqlite3.connect(journal_path) as bootstrap:
            bootstrap.execute("PRAGMA encoding='{}'".format(encoding))
            bootstrap.execute("CREATE TABLE encoding_seed (value TEXT)")
            bootstrap.execute("DROP TABLE encoding_seed")
    journal = ExecutionDecisionJournal(journal_path)
    try:
        assert (
            journal._connection.execute("PRAGMA encoding").fetchone()[0].upper() == encoding.upper()
        )
        candidate_id, _receipt = _prepared_workflow(journal, candidate, token)
        intent = _intent(candidate, candidate_id)
        _record_intent(journal, candidate_id, token, intent)
        limit = journal_module._MAX_FEE_PAIR_GRID_TAPE_RECORD_BYTES
        if encoding.upper() == "UTF-16LE":
            # U+0800 occupies two SQLite UTF-16 bytes but three UTF-8 bytes,
            # so this deliberately passes the old two-times storage prefilter.
            oversized = "\u0800" * (limit // 3 + 1)
            expected_storage_bytes = 2 * len(oversized)
            assert expected_storage_bytes <= 2 * (limit - 1)
        else:
            oversized = "x" * limit
            expected_storage_bytes = len(oversized)
        assert len(oversized.encode("utf-8")) + 1 > limit
        with journal._transaction() as cursor:
            _tamper_tape_intent_record(cursor.connection, candidate_id, oversized)
        stored_bytes = journal._connection.execute(
            """SELECT length(CAST(tape_record_json AS BLOB))
               FROM execution_fee_pair_workflow_events
               WHERE candidate_id=? AND event_sequence=4""",
            (candidate_id,),
        ).fetchone()[0]
        assert stored_bytes == expected_storage_bytes

        json_parse_attempts = []
        full_event_selects = []
        original_loads = json.loads

        def guarded_loads(value, *args, **kwargs):
            if type(value) is str and value == oversized:
                json_parse_attempts.append(True)
                raise AssertionError("oversized stored tape intent reached JSON parsing")
            return original_loads(value, *args, **kwargs)

        def trace_sql(statement):
            normalized = " ".join(statement.upper().split())
            if (
                normalized.startswith("SELECT * FROM EXECUTION_FEE_PAIR_WORKFLOW_EVENTS ")
                and "ORDER BY EVENT_SEQUENCE" in normalized
            ):
                full_event_selects.append(True)

        journal._connection.set_trace_callback(trace_sql)
        try:
            with monkeypatch.context() as patcher:
                patcher.setattr(journal_module.json, "loads", guarded_loads)
                with pytest.raises(
                    ExecutionDecisionJournalError,
                    match="FEE_PAIR_WORKFLOW_LEDGER_CORRUPT",
                ):
                    journal.fee_pair_workflow_candidate(candidate_id)
        finally:
            journal._connection.set_trace_callback(None)
        assert json_parse_attempts == []
        assert full_event_selects == []
    finally:
        journal.close()


def test_tape_intent_size_scan_accepts_exact_utf8_limit_across_multibyte_chunk(
    tmp_path,
):
    candidate = workflow_fixtures._candidate(run_id="grid-tape-exact-limit")
    token = "grid-tape-append-owner-" + "h" * 32
    journal = ExecutionDecisionJournal(tmp_path / "grid-tape-exact-limit.sqlite3")
    try:
        candidate_id, _receipt = _prepared_workflow(journal, candidate, token)
        intent = _intent(candidate, candidate_id)
        _record_intent(journal, candidate_id, token, intent)

        row = json.loads(intent["record_json"])
        row.pop("record_id")
        row["padding"] = ""
        row["record_id"] = "0" * 64
        base = journal_module._canonical_tape_record_json(row)
        marker = '"padding":""'
        marker_start = base.index(marker)
        padding_start = len(base[: marker_start + len('"padding":"')].encode("utf-8"))
        chunk_bytes = journal_module._FEE_PAIR_GRID_TAPE_SCAN_CHUNK_BYTES
        before_multibyte = chunk_bytes - 1 - padding_start
        limit = journal_module._MAX_FEE_PAIR_GRID_TAPE_RECORD_BYTES
        target_record_bytes = limit - 1
        added_bytes = target_record_bytes - len(base.encode("utf-8"))
        after_multibyte = added_bytes - before_multibyte - len("\u0800".encode("utf-8"))
        assert before_multibyte >= 0 and after_multibyte >= 0
        row["padding"] = "a" * before_multibyte + "\u0800" + "a" * after_multibyte
        unsigned = dict(row)
        unsigned.pop("record_id")
        row["record_id"] = _digest(journal_module._canonical_tape_record_json(unsigned))
        record_json = journal_module._canonical_tape_record_json(row)
        record_bytes = record_json.encode("utf-8")
        assert len(record_bytes) + 1 == limit
        assert record_bytes[chunk_bytes - 1 : chunk_bytes + 2] == "\u0800".encode("utf-8")

        with journal._transaction() as cursor:
            _tamper_tape_intent_record(cursor.connection, candidate_id, record_json)
            journal._precheck_fee_pair_grid_tape_intent_storage_bound(cursor, candidate_id)
    finally:
        journal.close()
