"""Narrow durable contracts for callback/query restart dispositions."""

from __future__ import annotations

import hashlib
import sqlite3

import pytest

from backtrader.stores import execution_decision_journal as journal_module
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
    ExecutionDecisionKey,
    ExecutionIntentKey,
    _callback_query_disposition_replay_matches,
)


def _prepared_intent(journal: ExecutionDecisionJournal) -> str:
    key = ExecutionDecisionKey(
        account_scope="sim-account",
        strategy_scope="alpha003-native",
        logical_run_id="run-callback-disposition",
        cohort_id="callback-disposition-cohort",
        close_time="2026-10-24T09:00:00Z",
        decision_kind="ALPHA003_GRID",
    )
    intent_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument="rb2701",
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    decision = journal.record_decision(
        key,
        {"mode": "native", "risk_policy_id": "a003-risk-v1"},
        intent_keys=(intent_key,),
    )
    intent = journal.prepare_intent(
        decision.decision_id,
        intent_key,
        {
            "exchange": "SHFE",
            "quantity": "1",
            "price": "3500",
            "factor_stop_price": "3450",
            "risk_policy_id": "a003-risk-v1",
            "risk_policy": {"stop_loss_ticks": 10},
        },
    )
    return intent.intent_id


def _callback_query_proof():
    family_ids = [
        ["account_result", 41],
        ["orders_result", 42],
        ["trades_result", 43],
        ["instruments_result", 44],
        ["positions_result", 45],
    ]
    return {
        "schema_version": 1,
        "disposition_code": "QUERY_MATCHED_BROKER_ACK_UNOBSERVED_AFTER_RESTART",
        "native_receipt_id": "native-receipt",
        "query_receipt_id": "query-receipt",
        "intent_id": "intent-1",
        "execution_id": "ctp:20261024:trade-1",
        "native_callback_id": "ctp-trade:abc",
        "native_evidence_sha256": "a" * 64,
        "query_callback_id": "query-trade:abc",
        "query_evidence_sha256": "b" * 64,
        "original_order": {
            "account_scope": "sim-account",
            "strategy_scope": "alpha003-native",
            "trading_day": "20261024",
            "instrument": "rb2701",
            "exchange": "SHFE",
            "order_ref": "7001",
            "front_id": 4,
            "session_id": 7,
            "order_sys_id": None,
        },
        "matched_order": {
            "front_id": 4,
            "session_id": 7,
            "order_ref": "7001",
            "instrument": "rb2701",
            "exchange": "SHFE",
            "order_sys_id": "sys-7001",
        },
        "trade": {
            "trade_id": "trade-1",
            "trade_date": "20261024",
            "trade_time": "09:00:01",
            "query_set_id": "query-set-1",
            "observation_id": "trade-observation-1",
            "snapshot_id": "snapshot-1",
            "request_id": 43,
            "account_fingerprint": "acct-fingerprint",
            "connection_generation": 1,
            "trading_day": "20261024",
            "side": "BUY",
            "position_effect": "OPEN",
            "order_sys_id": "sys-7001",
            "quantity": "1",
            "price": "3500",
            "fee": None,
            "filled_at_ns": 1792832401000000000,
        },
        "query_set": {
            "query_set_id": "query-set-1",
            "account_fingerprint": "acct-fingerprint",
            "connection_generation": 1,
            "trading_day": "20261024",
            "started_at_utc": "2026-10-24T01:00:00Z",
            "completed_at_utc": "2026-10-24T01:00:02Z",
            "available_at_utc": "2026-10-24T01:00:02Z",
            "family_request_ids": family_ids,
        },
    }


def test_process_marker_is_stable_for_same_process_and_uses_live_pid(monkeypatch):
    marker = journal_module._current_process_instance_id()
    assert marker.startswith("{}:".format(journal_module.os.getpid()))

    original_getpid = journal_module.os.getpid
    monkeypatch.setattr(journal_module.os, "getpid", lambda: original_getpid() + 1000)
    assert journal_module._current_process_instance_id() != marker


def test_v10_migration_keeps_legacy_callbacks_pending_and_origin_unknown(tmp_path):
    path = tmp_path / "callback-disposition-v10.sqlite3"
    journal = ExecutionDecisionJournal(path)
    intent_id = _prepared_intent(journal)
    native = journal.record_callback(
        intent_id,
        "native-legacy",
        {"event_type": "unresolved_trade_callback", "trade_id": "trade-1"},
    )
    query = journal.record_callback(
        intent_id,
        "query-legacy",
        {"event_type": "execution_fill", "execution_id": "ctp:20261024:trade-1"},
    )
    journal.close()

    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        for trigger in (
            "execution_callback_query_disposition_no_update",
            "execution_callback_query_disposition_no_delete",
            "execution_callback_delivery_state",
            "execution_callback_delivery_insert",
            "execution_callback_delivery_acknowledged",
            "execution_callback_delivery_disposition",
            "execution_callback_disposition_no_ack",
        ):
            connection.execute("DROP TRIGGER IF EXISTS {}".format(trigger))
        connection.execute("DROP INDEX IF EXISTS execution_callback_delivery_order")
        connection.execute("DROP INDEX IF EXISTS execution_callback_disposition_startup")
        connection.execute("DROP TABLE execution_callback_query_dispositions")
        connection.execute("DROP TABLE IF EXISTS execution_callback_delivery_queue")
        connection.execute(
            "ALTER TABLE execution_decision_callbacks DROP COLUMN process_instance_id"
        )
        connection.execute("ALTER TABLE execution_decision_callbacks DROP COLUMN delivery_pending")
        connection.execute("DROP TABLE IF EXISTS execution_durable_capacity_usage")
        connection.execute("DROP TABLE IF EXISTS execution_durable_capacity_limits")
        connection.execute("PRAGMA user_version=10")
        connection.commit()
    finally:
        connection.close()

    migrated = ExecutionDecisionJournal(path)
    try:
        assert migrated._connection.execute("PRAGMA user_version").fetchone()[0] == 12
        pending = migrated.pending_callbacks(limit=16)
        assert {item.receipt_id for item in pending} == {native.receipt_id, query.receipt_id}
        with migrated._transaction() as cursor, pytest.raises(
            ExecutionDecisionJournalError
        ) as error:
            migrated.record_callback_query_disposition(
                cursor,
                native_receipt_id=native.receipt_id,
                query_receipt_id=query.receipt_id,
                intent_id=intent_id,
                execution_id="ctp:20261024:trade-1",
                proof_payload={
                    "original_order": {},
                    "matched_order": {},
                    "trade": {},
                    "query_set": {},
                },
            )
        assert error.value.code == "CALLBACK_QUERY_RESTART_ORIGIN_UNKNOWN"
        assert {item.receipt_id for item in migrated.pending_callbacks(limit=16)} == {
            native.receipt_id,
            query.receipt_id,
        }
    finally:
        migrated.close()


@pytest.mark.parametrize("missing", ["delivery_pending", "disposition_table"])
def test_v11_missing_delivery_projection_fails_closed_before_schema_recreation(tmp_path, missing):
    path = tmp_path / "callback-disposition-v11-corrupt.sqlite3"
    journal = ExecutionDecisionJournal(path)
    journal.close()

    connection = sqlite3.connect(path)
    try:
        if missing == "delivery_pending":
            connection.execute("DROP TRIGGER IF EXISTS execution_callback_delivery_state")
            connection.execute("DROP INDEX IF EXISTS execution_callback_delivery_order")
            connection.execute("DROP INDEX IF EXISTS execution_callback_disposition_startup")
            connection.execute(
                "ALTER TABLE execution_decision_callbacks DROP COLUMN delivery_pending"
            )
        else:
            connection.execute(
                "DROP TRIGGER IF EXISTS execution_callback_query_disposition_no_update"
            )
            connection.execute(
                "DROP TRIGGER IF EXISTS execution_callback_query_disposition_no_delete"
            )
            connection.execute("DROP TRIGGER IF EXISTS execution_callback_disposition_no_ack")
            connection.execute("DROP TABLE execution_callback_query_dispositions")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ExecutionDecisionJournalError) as error:
        ExecutionDecisionJournal(path)
    assert error.value.code == "CALLBACK_DELIVERY_SCHEMA_CORRUPT"


def test_pending_projection_is_authoritative_and_corrupt_disposition_fails_closed(tmp_path):
    path = tmp_path / "callback-disposition-corrupt-proof.sqlite3"
    journal = ExecutionDecisionJournal(path)
    intent_id = _prepared_intent(journal)
    execution_id = "ctp:20261024:trade-1"
    digest = hashlib.sha256(execution_id.encode("utf-8")).hexdigest()
    native_callback_id = "ctp-trade:" + digest
    query_callback_id = "query-trade:" + digest
    native_evidence = {
        "event_type": "execution_fill",
        "evidence_kind": "native_trade_callback",
        "execution_id": execution_id,
    }
    query_evidence = {"event_type": "execution_fill", "execution_id": execution_id}
    native = journal.record_callback(intent_id, native_callback_id, native_evidence)
    query = journal.record_callback(intent_id, query_callback_id, query_evidence)
    assert {item.receipt_id for item in journal.pending_callbacks(limit=8)} == {
        native.receipt_id,
        query.receipt_id,
    }
    raw = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                """UPDATE execution_decision_callbacks SET delivery_pending=0
                   WHERE receipt_id=?""",
                (native.receipt_id,),
            )
        raw.rollback()
    finally:
        raw.close()
    assert {item.receipt_id for item in journal.pending_callbacks(limit=8)} == {
        native.receipt_id,
        query.receipt_id,
    }

    journal.acknowledge_callback(query.receipt_id)
    native_json = journal._payload_json(native_evidence)
    query_json = journal._payload_json(query_evidence)
    proof = {
        "disposition_code": "QUERY_MATCHED_BROKER_ACK_UNOBSERVED_AFTER_RESTART",
        "native_receipt_id": native.receipt_id,
        "query_receipt_id": query.receipt_id,
        "intent_id": intent_id,
        "execution_id": execution_id,
        "native_callback_id": native_callback_id,
        "query_callback_id": query_callback_id,
        "native_evidence_sha256": hashlib.sha256(native_json.encode("utf-8")).hexdigest(),
        "query_evidence_sha256": hashlib.sha256(query_json.encode("utf-8")).hexdigest(),
    }
    proof_json = journal._payload_json(proof)
    producer = journal._connection.execute(
        "SELECT process_instance_id FROM execution_decision_callbacks WHERE receipt_id=?",
        (native.receipt_id,),
    ).fetchone()[0]
    with journal._transaction() as cursor:
        cursor.execute(
            """INSERT INTO execution_callback_query_dispositions
               (native_receipt_id,query_receipt_id,intent_id,execution_id,
                disposition_code,query_process_instance_id,proof_payload_json,
                proof_sha256,created_at_ns)
               VALUES(?,?,?,?,?,?,?,?,1)""",
            (
                native.receipt_id,
                query.receipt_id,
                intent_id,
                execution_id,
                "QUERY_MATCHED_BROKER_ACK_UNOBSERVED_AFTER_RESTART",
                producer + ":other-process",
                proof_json,
                hashlib.sha256(proof_json.encode("utf-8")).hexdigest(),
            ),
        )
        cursor.execute(
            "UPDATE execution_decision_callbacks SET delivery_pending=0 WHERE receipt_id=?",
            (native.receipt_id,),
        )
    assert journal.pending_callbacks(limit=8) == ()
    with pytest.raises(ExecutionDecisionJournalError) as error:
        journal.callback_query_disposition(native.receipt_id)
    assert error.value.code == "CALLBACK_QUERY_DISPOSITION_CORRUPT"
    with pytest.raises(ExecutionDecisionJournalError) as error:
        ExecutionDecisionJournal(path)
    assert error.value.code == "CALLBACK_QUERY_DISPOSITION_CORRUPT"

    raw = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                """UPDATE execution_decision_callbacks SET delivery_pending=1
                   WHERE receipt_id=?""",
                (native.receipt_id,),
            )
        raw.rollback()
        raw.execute("DROP TRIGGER execution_callback_delivery_state")
        raw.execute(
            "UPDATE execution_decision_callbacks SET delivery_pending=1 WHERE receipt_id=?",
            (native.receipt_id,),
        )
        raw.commit()
    finally:
        raw.close()
    with pytest.raises(ExecutionDecisionJournalError) as error:
        journal.pending_callbacks(limit=8)
    assert error.value.code == "CALLBACK_DELIVERY_STATE_CORRUPT"

    raw = sqlite3.connect(path)
    try:
        raw.execute(
            "UPDATE execution_decision_callbacks SET delivery_pending=0 WHERE receipt_id=?",
            (native.receipt_id,),
        )
        raw.execute("DROP TRIGGER execution_callback_query_disposition_no_update")
        raw.execute(
            "UPDATE execution_callback_query_dispositions SET proof_payload_json='{}' "
            "WHERE native_receipt_id=?",
            (native.receipt_id,),
        )
        raw.commit()
    finally:
        raw.close()
    with pytest.raises(ExecutionDecisionJournalError) as error:
        journal.callback_query_disposition(native.receipt_id)
    assert error.value.code == "CALLBACK_QUERY_DISPOSITION_CORRUPT"
    journal.close()


def test_open_rejects_hidden_unacknowledged_callback_without_disposition(tmp_path):
    path = tmp_path / "callback-disposition-missing-proof.sqlite3"
    journal = ExecutionDecisionJournal(path)
    intent_id = _prepared_intent(journal)
    native = journal.record_callback(
        intent_id,
        "native-hidden-without-proof",
        {"event_type": "unresolved_trade_callback", "trade_id": "trade-1"},
    )
    journal.close()

    raw = sqlite3.connect(path)
    try:
        raw.execute("DROP TRIGGER execution_callback_delivery_state")
        raw.execute(
            "UPDATE execution_decision_callbacks SET delivery_pending=0 WHERE receipt_id=?",
            (native.receipt_id,),
        )
        raw.commit()
    finally:
        raw.close()

    with pytest.raises(ExecutionDecisionJournalError) as error:
        ExecutionDecisionJournal(path)
    assert error.value.code == "CALLBACK_DELIVERY_STATE_CORRUPT"


def test_replay_keeps_first_proof_when_fresh_query_ids_and_times_change():
    original = _callback_query_proof()
    candidate = _callback_query_proof()
    candidate["trade"].update(
        query_set_id="query-set-2",
        observation_id="trade-observation-2",
        snapshot_id="snapshot-2",
        request_id=103,
        connection_generation=2,
    )
    candidate["query_set"].update(
        query_set_id="query-set-2",
        connection_generation=2,
        started_at_utc="2026-10-24T01:01:00Z",
        completed_at_utc="2026-10-24T01:01:02Z",
        available_at_utc="2026-10-24T01:01:02Z",
        family_request_ids=[
            ["account_result", 101],
            ["orders_result", 102],
            ["trades_result", 103],
            ["instruments_result", 104],
            ["positions_result", 105],
        ],
    )
    candidate["trade"]["fee"] = "2.5"

    assert _callback_query_disposition_replay_matches(original, candidate)

    conflicting = _callback_query_proof()
    conflicting["trade"]["quantity"] = "1.1"
    assert not _callback_query_disposition_replay_matches(original, conflicting)

    conflicting_time = _callback_query_proof()
    conflicting_time["trade"]["filled_at_ns"] += 1
    assert not _callback_query_disposition_replay_matches(original, conflicting_time)
