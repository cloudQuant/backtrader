"""Route-neutral durable decision and intent journal contracts."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier, Event, RLock

import pytest

from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
    ExecutionDecisionKey,
    ExecutionIntentKey,
)
from backtrader.stores.factor_position_book import apply_factor_execution_fill


def _drop_v12_durable_capacity_tables(connection: sqlite3.Connection) -> None:
    """Restore a pre-v12 schema before exercising an older migration path."""

    connection.execute("DROP TABLE IF EXISTS execution_durable_capacity_usage")
    connection.execute("DROP TABLE IF EXISTS execution_durable_capacity_limits")
    connection.execute("DROP TABLE IF EXISTS execution_run_loss_guards")


def _decision_key(
    run_id: str = "run-a", *, close_time: str = "2026-10-20T10:00:00Z", kind: str = "bar"
) -> ExecutionDecisionKey:
    return ExecutionDecisionKey(
        account_scope="account-a",
        strategy_scope="strategy-a",
        logical_run_id=run_id,
        cohort_id="cohort-1",
        close_time=close_time,
        decision_kind=kind,
    )


def _grid_key(
    *,
    account_scope="account-a",
    strategy_scope="strategy-a",
    run_id="run-a",
    cohort_id="cohort-a",
    close_time="2026-10-20T10:00:00Z",
    kind="bar",
):
    return ExecutionDecisionKey(
        account_scope=account_scope,
        strategy_scope=strategy_scope,
        logical_run_id=run_id,
        cohort_id=cohort_id,
        close_time=close_time,
        decision_kind=kind,
    )


def _record_grid_noop(journal, key, *, epoch_id, batch_id, economics=None):
    return journal.record_grid_decision(
        key,
        {"signal": "flat"} if economics is None else economics,
        epoch_id=epoch_id,
        batch_id=batch_id,
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
    )


def _intent_key(
    instrument: str = "SIM-IF-1",
    *,
    action: str = "SUBMIT",
    leg: int = 0,
    side: str = "BUY",
    effect: str = "OPEN",
) -> ExecutionIntentKey:
    return ExecutionIntentKey(
        action=action,
        instrument=instrument,
        side=side,
        position_effect=effect,
        leg=leg,
    )


def _decision_payload(**changes):
    payload = {"signal": "cross-up", "confidence": 0.75}
    payload.update(changes)
    return payload


def _order_payload(**changes):
    payload = {
        "quantity": Decimal("2.000"),
        "price": Decimal("4012.50"),
        "order_type": "LIMIT",
        "time_in_force": "DAY",
    }
    payload.update(changes)
    return payload


def _native_order_identity(order_ref, *, instrument="SIM-IF-1"):
    return {
        "backtrader_order_ref": 41,
        "order_ref": str(order_ref),
        "instrument_id": instrument,
        "exchange_id": "CFFEX",
        "trading_day": "20261024",
        "operation": "insert",
    }


def _prepare(journal, *, key=None, intent_key=None, original_identity=None):
    decision = journal.record_decision(
        key or _decision_key(),
        _decision_payload(),
        intent_keys=(intent_key or _intent_key(),),
    )
    intent = journal.prepare_intent(
        decision.decision_id,
        intent_key or _intent_key(),
        _order_payload(),
        original_identity=original_identity or {"backtrader_order_ref": 41},
    )
    return decision, intent


def _record_terminal_reconciliation(
    journal,
    intent,
    *,
    reconciliation_id,
    query_id,
    terminal_state="FILLED",
    event_id="provider-event-1",
    snapshot_id="position-snapshot-1",
    position_flat=False,
    provider_order_id="provider-order-1",
):
    return journal.record_reconciliation(
        intent.intent_id,
        reconciliation_id=reconciliation_id,
        query_id=query_id,
        state="KNOWN",
        provider_identity={"order_id": provider_order_id},
        outcome_code=terminal_state.lower(),
        terminal_state=terminal_state,
        terminal_event_id=event_id,
        position_snapshot_id=snapshot_id,
        position_flat=position_flat,
    )


def test_noop_and_canonical_economics_are_durable_and_immutable(tmp_path):
    path = tmp_path / "decisions.sqlite3"
    journal = ExecutionDecisionJournal(path)
    key = _decision_key()
    first = journal.record_decision(
        key,
        {
            "quantity": Decimal("1.000"),
            "price": 123.0,
            "tags": {"z": 1, "a": 2},
            "path": ["strategy", {"phase": "close"}],
        },
    )
    assert first.is_noop is True
    assert first.intent_keys == ()
    assert first.economic_payload == {
        "quantity": "1",
        "price": "123",
        "tags": {"a": 2, "z": 1},
        "path": ("strategy", {"phase": "close"}),
    }
    with pytest.raises(TypeError):
        first.economic_payload["quantity"] = "99"
    with pytest.raises(TypeError):
        first.economic_payload["tags"]["a"] = 99
    with pytest.raises(TypeError):
        first.economic_payload["path"][1]["phase"] = "changed"
    replay = journal.record_decision(
        key,
        {
            "tags": {"a": 2, "z": 1},
            "price": "123.00",
            "quantity": "1.0",
            "path": ["strategy", {"phase": "close"}],
        },
    )
    assert replay.decision_id == first.decision_id
    with pytest.raises(ExecutionDecisionJournalError, match="DECISION_CONFLICT"):
        journal.record_decision(
            key,
            {"quantity": "1.01", "price": "123", "tags": {"a": 2, "z": 1}},
        )
    with pytest.raises(ExecutionDecisionJournalError, match="INVALID_JOURNAL_PAYLOAD"):
        journal.record_decision(_decision_key("bool-quantity"), {"quantity": True})
    journal.close()

    reopened = ExecutionDecisionJournal(path)
    restored = reopened.decision(first.decision_id)
    assert restored is not None
    assert restored.is_noop is True
    assert restored.economic_payload["quantity"] == "1"
    reopened.close()

    invalid = ExecutionDecisionJournal(tmp_path / "invalid-economic.sqlite3")
    decision = invalid.record_decision(_decision_key("invalid-economic"), _decision_payload())
    with pytest.raises(ExecutionDecisionJournalError, match="INVALID_JOURNAL_PAYLOAD"):
        invalid.prepare_intent(
            decision.decision_id,
            _intent_key(),
            _order_payload(price=False),
        )
    invalid.close()


def test_decision_for_key_reads_after_reopen_without_mutating_journal(tmp_path):
    path = tmp_path / "decision-for-key.sqlite3"
    journal = ExecutionDecisionJournal(path)
    key = _grid_key()
    grid = _record_grid_noop(
        journal,
        key,
        epoch_id="epoch-a",
        batch_id="batch-a",
    )
    assert grid.decision is not None
    assert grid.cursor is not None
    expected = grid.decision
    journal.close()

    reopened = ExecutionDecisionJournal(path)
    cursor_before = reopened.grid_cursor(
        key.account_scope, key.strategy_scope, key.cohort_id
    )
    capacity_before = reopened.decision_capacity_snapshot()
    changes_before = reopened._connection.total_changes

    assert reopened.decision_for_key(key) == expected
    equivalent_time_key = _grid_key(close_time="2026-10-20T18:00:00+08:00")
    assert reopened.decision_for_key(equivalent_time_key) == expected
    for missing_key in (
        _grid_key(account_scope="account-other"),
        _grid_key(strategy_scope="strategy-other"),
        _grid_key(close_time="2026-10-20T10:00:01Z"),
        _grid_key(kind="tick"),
        _grid_key(run_id="run-other"),
    ):
        assert reopened.decision_for_key(missing_key) is None

    with pytest.raises(ExecutionDecisionJournalError, match="INVALID_DECISION_KEY"):
        reopened.decision_for_key(None)

    assert reopened.grid_cursor(key.account_scope, key.strategy_scope, key.cohort_id) == (
        cursor_before
    )
    capacity_after = reopened.decision_capacity_snapshot()
    assert (
        capacity_after.base_record_count,
        capacity_after.base_payload_bytes,
        capacity_after.settlement_record_count,
        capacity_after.settlement_payload_bytes,
    ) == (
        capacity_before.base_record_count,
        capacity_before.base_payload_bytes,
        capacity_before.settlement_record_count,
        capacity_before.settlement_payload_bytes,
    )
    assert reopened._connection.total_changes == changes_before
    reopened.close()


def test_equivalent_close_times_normalize_to_one_business_key(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "time.sqlite3")
    utc_key = _decision_key(close_time="2026-10-20T10:00:00Z")
    offset_key = _decision_key(close_time="2026-10-20T18:00:00+08:00")
    assert utc_key.close_time == offset_key.close_time == "2026-10-20T10:00:00Z"
    first = journal.record_decision(utc_key, {"signal": "flat"})
    replay = journal.record_decision(offset_key, {"signal": "flat"})
    assert first.decision_id == replay.decision_id
    with pytest.raises(ExecutionDecisionJournalError, match="INVALID_DECISION_CLOSE_TIME"):
        _decision_key(close_time="2026-10-20T10:00:00")
    with pytest.raises(ExecutionDecisionJournalError, match="INVALID_DECISION_CLOSE_TIME"):
        _decision_key(close_time="2026-10-20T10:00:00.1234567Z")
    with pytest.raises(ExecutionDecisionJournalError, match="INVALID_DECISION_CLOSE_TIME"):
        _decision_key(close_time="2026-10-20T10:00:00-00:00")
    journal.close()


def test_finite_decision_high_water_allows_replay_and_reserved_settlement(tmp_path):
    path = tmp_path / "finite-capacity.sqlite3"
    limits = {
        "max_decision_records": 1,
        "settlement_decision_reserve_records": 2,
        "max_decision_bytes": 10000,
        "settlement_decision_reserve_bytes": 10000,
    }
    journal = ExecutionDecisionJournal(path, **limits)
    base = _decision_key("capacity-base")
    first = journal.record_decision(base, {"signal": "flat"})
    capacity_before_replay = journal.decision_capacity_snapshot()

    # Exact replay is idempotent and does not consume another capacity slot.
    replay = journal.record_decision(base, {"signal": "flat"})
    assert replay.decision_id == first.decision_id
    replay_capacity = journal.decision_capacity_snapshot()
    assert replay_capacity.base_record_count == capacity_before_replay.base_record_count
    assert replay_capacity.base_payload_bytes == capacity_before_replay.base_payload_bytes
    with pytest.raises(ExecutionDecisionJournalError, match="DECISION_CAPACITY_HIGH_WATER"):
        journal.record_decision(_decision_key("capacity-base-2"), {"signal": "flat"})

    close_key = _intent_key(effect="CLOSE")
    close = journal.record_decision(
        _decision_key("capacity-close"),
        {"signal": "reduce"},
        intent_keys=(close_key,),
    )
    assert close.intent_keys == (close_key,)
    cancel_key = _intent_key(action="CANCEL", instrument="SIM-IF-2")
    cancel = journal.record_decision(
        _decision_key("capacity-cancel"),
        {"signal": "cancel"},
        intent_keys=(cancel_key,),
    )
    assert cancel.intent_keys == (cancel_key,)
    with pytest.raises(ExecutionDecisionJournalError, match="SETTLEMENT_CAPACITY_EXHAUSTED"):
        journal.record_decision(
            _decision_key("capacity-settlement-3"),
            {"signal": "cancel"},
            intent_keys=(_intent_key(action="CANCEL", instrument="SIM-IF-3"),),
        )
    journal.close()

    reopened = ExecutionDecisionJournal(path, **limits)
    assert reopened.decision(first.decision_id) is not None
    assert reopened.decision(close.decision_id) is not None
    assert reopened.decision(cancel.decision_id) is not None
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_CAPACITY_CONFIG_MISMATCH"):
        ExecutionDecisionJournal(path, **{**limits, "max_decision_records": 2})
    # Capacity rejection is not a SQLite failure; exact settlement replay survives.
    assert (
        reopened.record_decision(
            _decision_key("capacity-cancel"),
            {"signal": "cancel"},
            intent_keys=(cancel_key,),
        ).decision_id
        == cancel.decision_id
    )
    usage = reopened.decision_capacity_snapshot()
    assert usage.base_record_count == usage.base_record_limit == 1
    assert usage.settlement_record_count == usage.settlement_record_limit == 2
    assert usage.base_payload_bytes > 0
    assert usage.settlement_payload_bytes > 0
    assert usage.physical_bytes >= usage.database_bytes
    reopened.close()


def test_capacity_usage_migration_backfills_exact_bytes_once(tmp_path):
    path = tmp_path / "capacity-v8-migration.sqlite3"
    journal = ExecutionDecisionJournal(path)
    journal.record_decision(_decision_key("capacity-migration-base"), {"symbol": "螺纹"})
    journal.record_decision(
        _decision_key("capacity-migration-settlement"),
        {"signal": "reduce"},
        intent_keys=(_intent_key(action="SUBMIT", effect="CLOSE"),),
    )
    journal.close()

    with sqlite3.connect(path) as connection:
        history = connection.execute(
            """SELECT capacity_class,business_key_json,economic_payload_json,intent_keys_json
               FROM execution_decisions"""
        ).fetchall()
        expected = {"BASE": [0, 0], "SETTLEMENT": [0, 0]}
        for capacity_class, business_key, economics, intent_keys in history:
            expected[capacity_class][0] += 1
            expected[capacity_class][1] += sum(
                len(value.encode("utf-8")) for value in (business_key, economics, intent_keys)
            )
        connection.execute("DROP TABLE execution_decision_capacity_usage")
        _drop_v12_durable_capacity_tables(connection)
        connection.execute("PRAGMA user_version = 8")

    migrated = ExecutionDecisionJournal(path)
    assert migrated._connection.execute("PRAGMA user_version").fetchone()[0] == 13
    usage = migrated._connection.execute(
        """SELECT capacity_class,record_count,payload_bytes
           FROM execution_decision_capacity_usage ORDER BY capacity_class"""
    ).fetchall()
    assert {
        row["capacity_class"]: (row["record_count"], row["payload_bytes"]) for row in usage
    } == {capacity_class: tuple(values) for capacity_class, values in expected.items()}
    snapshot = migrated.decision_capacity_snapshot()
    assert snapshot.base_record_count == expected["BASE"][0]
    assert snapshot.base_payload_bytes == expected["BASE"][1]
    assert snapshot.settlement_record_count == expected["SETTLEMENT"][0]
    assert snapshot.settlement_payload_bytes == expected["SETTLEMENT"][1]
    with migrated._transaction() as cursor:
        cursor.execute(
            """CREATE TRIGGER capacity_backfill_runs_once
               BEFORE DELETE ON execution_decision_capacity_usage
               BEGIN SELECT RAISE(ABORT,'migration repeated'); END"""
        )
    migrated.close()

    reopened = ExecutionDecisionJournal(path)
    assert reopened.decision_capacity_snapshot().base_record_count == expected["BASE"][0]
    assert (
        reopened.decision_capacity_snapshot().settlement_record_count == expected["SETTLEMENT"][0]
    )
    reopened.close()


def test_capacity_usage_concurrent_v8_openers_backfill_once(tmp_path, monkeypatch):
    path = tmp_path / "capacity-v8-concurrent-migration.sqlite3"
    journal = ExecutionDecisionJournal(path)
    journal.record_decision(_decision_key("capacity-concurrent-migration"), {"signal": "flat"})
    capacity_limits = journal.durable_capacity_limits
    journal.close()

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE execution_decision_capacity_usage")
        _drop_v12_durable_capacity_tables(connection)
        connection.execute("PRAGMA user_version = 8")

    def schema_instance(connection):
        instance = object.__new__(ExecutionDecisionJournal)
        instance._connection = connection
        instance._lock = RLock()
        instance._closed = False
        instance._failed_closed = False
        instance.max_decision_records = 100000
        instance.settlement_decision_reserve_records = 4096
        instance.max_decision_bytes = 536870912
        instance.settlement_decision_reserve_bytes = 67108864
        instance.durable_capacity_limits = capacity_limits
        return instance

    connections = [
        sqlite3.connect(path, isolation_level=None, check_same_thread=False) for _ in range(2)
    ]
    for connection in connections:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA foreign_keys = ON")
    first, second = (schema_instance(connection) for connection in connections)

    second_pre_migration = Event()
    allow_second = Event()
    paused = False

    def pause_second_before_ddl(statement):
        nonlocal paused
        normalized = " ".join(statement.upper().split())
        if not paused and normalized.startswith("CREATE TABLE IF NOT EXISTS EXECUTION_DECISIONS"):
            paused = True
            second_pre_migration.set()
            allow_second.wait(10)

    second._connection.set_trace_callback(pause_second_before_ddl)
    original_backfill = ExecutionDecisionJournal._backfill_decision_capacity_usage
    backfill_calls = []

    def count_backfill(cursor):
        backfill_calls.append("called")
        return original_backfill(cursor)

    monkeypatch.setattr(
        ExecutionDecisionJournal,
        "_backfill_decision_capacity_usage",
        staticmethod(count_backfill),
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            second_future = pool.submit(second._create_schema)
            assert second_pre_migration.wait(10)
            first_future = pool.submit(first._create_schema)
            first_future.result(timeout=10)
            allow_second.set()
            second_future.result(timeout=10)
    finally:
        allow_second.set()
        for connection in connections:
            connection.close()

    assert len(backfill_calls) == 1
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 13
        usage = connection.execute(
            """SELECT capacity_class,record_count
               FROM execution_decision_capacity_usage ORDER BY capacity_class"""
        ).fetchall()
    assert usage == [("BASE", 1), ("SETTLEMENT", 0)]


def test_capacity_usage_update_rolls_back_with_decision(tmp_path):
    path = tmp_path / "capacity-rollback.sqlite3"
    journal = ExecutionDecisionJournal(path)
    baseline = journal.decision_capacity_snapshot()
    journal.close()
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_capacity_usage_update
               BEFORE UPDATE ON execution_decision_capacity_usage
               BEGIN SELECT RAISE(ABORT,'synthetic capacity failure'); END"""
        )

    failing = ExecutionDecisionJournal(path)
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_WRITE_FAILED"):
        failing.record_decision(_decision_key("capacity-rollback"), {"signal": "flat"})
    failing.close()

    recovered = ExecutionDecisionJournal(path)
    usage = recovered.decision_capacity_snapshot()
    assert usage.base_record_count == baseline.base_record_count == 0
    assert usage.base_payload_bytes == baseline.base_payload_bytes == 0
    assert usage.settlement_record_count == baseline.settlement_record_count == 0
    assert usage.settlement_payload_bytes == baseline.settlement_payload_bytes == 0
    assert (
        recovered._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 0
    )
    recovered.close()


def test_noop_capacity_queries_are_bounded_and_indexed(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "capacity-bounded-queries.sqlite3")
    statements = []
    journal._connection.set_trace_callback(statements.append)
    journal.record_decision(_decision_key("capacity-bounded-noop"), {"signal": "flat"})
    snapshot = journal.decision_capacity_snapshot()
    journal._connection.set_trace_callback(None)

    traced = [" ".join(statement.upper().split()) for statement in statements]
    assert any(
        "SELECT RECORD_COUNT,PAYLOAD_BYTES FROM EXECUTION_DECISION_CAPACITY_USAGE" in statement
        for statement in traced
    )
    assert any("UPDATE EXECUTION_DECISION_CAPACITY_USAGE" in statement for statement in traced)
    assert not any("EXECUTION_DECISION_SLOTS" in statement for statement in traced)
    assert not any(
        ("COUNT(*)" in statement or "SUM(" in statement) and "EXECUTION_DECISIONS" in statement
        for statement in traced
    )
    assert snapshot.base_record_count == 1
    assert snapshot.settlement_record_count == 0

    plan = journal._connection.execute(
        """EXPLAIN QUERY PLAN SELECT record_count,payload_bytes
           FROM execution_decision_capacity_usage WHERE capacity_class=?""",
        ("BASE",),
    ).fetchall()
    details = " ".join(row["detail"].upper() for row in plan)
    assert "SEARCH EXECUTION_DECISION_CAPACITY_USAGE" in details
    assert "CAPACITY_CLASS=?" in details
    assert "SCAN EXECUTION_DECISION_CAPACITY_USAGE" not in details
    journal.close()


def test_capacity_usage_updates_are_serialized_across_connections(tmp_path):
    path = tmp_path / "capacity-connections.sqlite3"
    first = ExecutionDecisionJournal(path, max_decision_records=100)
    second = ExecutionDecisionJournal(path, max_decision_records=100)

    def record(journal, ordinal):
        return journal.record_decision(
            _decision_key("capacity-connection-{}".format(ordinal)),
            {"ordinal": ordinal, "signal": "flat"},
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(record, first if ordinal % 2 == 0 else second, ordinal)
            for ordinal in range(40)
        ]
        records = [future.result(timeout=30) for future in futures]
    assert len({record.decision_id for record in records}) == 40
    for journal in (first, second):
        usage = journal.decision_capacity_snapshot()
        assert usage.base_record_count == 40
        assert usage.settlement_record_count == 0
    first.close()
    second.close()


def test_decision_byte_high_water_is_transactional_and_replay_free(tmp_path):
    journal = ExecutionDecisionJournal(
        tmp_path / "decision-bytes.sqlite3",
        max_decision_records=10,
        settlement_decision_reserve_records=2,
        max_decision_bytes=1024,
        settlement_decision_reserve_bytes=1024,
    )
    key = _decision_key("decision-byte-a")
    first = journal.record_decision(key, {"note": "x" * 400})
    assert journal.record_decision(key, {"note": "x" * 400}).decision_id == first.decision_id
    with pytest.raises(ExecutionDecisionJournalError, match="DECISION_CAPACITY_HIGH_WATER"):
        journal.record_decision(_decision_key("decision-byte-b"), {"note": "y" * 400})
    assert journal.decision(first.decision_id) is not None
    usage = journal.decision_capacity_snapshot()
    assert usage.base_record_count == 1
    assert usage.base_payload_bytes <= usage.base_payload_byte_limit == 1024
    journal.close()


def test_schema_v1_migration_preserves_original_dispatch_outcome(tmp_path):
    path = tmp_path / "schema-v1.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE execution_decision_intents (
                   intent_id TEXT PRIMARY KEY,
                   decision_id TEXT NOT NULL,
                   intent_key_json TEXT NOT NULL,
                   economic_payload_json TEXT NOT NULL,
                   original_identity_json TEXT NOT NULL,
                   owner_intent_id TEXT,
                   state TEXT NOT NULL,
                   provider_identity_json TEXT,
                   outcome_code TEXT,
                   dispatch_result_json TEXT,
                   created_at_ns INTEGER NOT NULL,
                   updated_at_ns INTEGER NOT NULL
               )"""
        )
        connection.execute(
            """INSERT INTO execution_decision_intents VALUES
               ('intent-v1', 'decision-v1',
                    '{"action":"SUBMIT","instrument":"SIM-IF-1","leg":0,"position_effect":"OPEN","side":"BUY"}',
                '{"quantity":"1"}', '{"order_ref":9}', NULL, 'UNKNOWN', '{}',
                'connection_lost', '{"outcome_code":"connection_lost","provider_identity":{}}', 1, 2)"""
        )
        connection.execute("PRAGMA user_version = 1")

    journal = ExecutionDecisionJournal(path)
    intent = journal.intent("intent-v1")
    assert intent is not None
    assert intent.state == "UNKNOWN"
    assert intent.dispatch_state == "UNKNOWN"
    assert intent.outcome_code == "connection_lost"
    assert journal._connection.execute("PRAGMA user_version").fetchone()[0] == 13
    journal.close()


def test_schema_v2_migrates_grid_and_run_budget_tables(tmp_path):
    path = tmp_path / "schema-v2.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE execution_decision_intents (
                   intent_id TEXT PRIMARY KEY,
                   decision_id TEXT NOT NULL,
                   intent_key_json TEXT NOT NULL,
                   economic_payload_json TEXT NOT NULL,
                   original_identity_json TEXT NOT NULL,
                   owner_intent_id TEXT,
                   state TEXT NOT NULL,
                   dispatch_state TEXT,
                   provider_identity_json TEXT,
                   outcome_code TEXT,
                   dispatch_result_json TEXT,
                   created_at_ns INTEGER NOT NULL,
                   updated_at_ns INTEGER NOT NULL
               )"""
        )
        connection.execute("PRAGMA user_version = 2")

    journal = ExecutionDecisionJournal(path)
    assert journal._connection.execute("PRAGMA user_version").fetchone()[0] == 13
    names = {
        row["name"]
        for row in journal._connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert "execution_grid_cursors" in names
    assert "execution_run_order_budgets" in names
    journal.close()


def test_schema_v7_startup_backfills_native_ref_without_rewriting_dispatch(tmp_path):
    path = tmp_path / "schema-v7-native-index.sqlite3"
    journal = ExecutionDecisionJournal(path)
    decision = journal.record_decision(
        _decision_key("native-v7"),
        _decision_payload(),
        intent_keys=(_intent_key(),),
    )
    intent = journal.prepare_intent(
        decision.decision_id,
        _intent_key(),
        _order_payload(),
        original_identity=_native_order_identity("417"),
    )
    journal.claim_dispatch(intent.intent_id)
    unknown = journal.record_dispatch_result(
        intent.intent_id,
        state="UNKNOWN",
        provider_identity={"front_id": 13, "session_id": 7},
        outcome_code="connection_lost",
    )
    journal.close()

    with sqlite3.connect(path) as connection:
        original_rows = connection.execute(
            """SELECT original_identity_json, state, dispatch_state,
                      provider_identity_json, outcome_code, dispatch_result_json
               FROM execution_decision_intents WHERE intent_id=?""",
            (intent.intent_id,),
        ).fetchone()
        connection.execute(
            "DELETE FROM execution_native_intent_identities WHERE intent_id=?",
            (intent.intent_id,),
        )
        _drop_v12_durable_capacity_tables(connection)
        connection.execute("PRAGMA user_version = 7")

    recovered = ExecutionDecisionJournal(path)
    indexed = recovered.intent_by_native_order_ref(
        account_scope="account-a",
        strategy_scope="strategy-a",
        trading_day="20261024",
        instrument="SIM-IF-1",
        exchange="CFFEX",
        order_ref="417",
    )
    assert indexed == unknown
    assert recovered.intent(intent.intent_id) == unknown
    assert recovered._connection.execute("PRAGMA user_version").fetchone()[0] == 13
    recovered.close()

    with sqlite3.connect(path) as connection:
        recovered_rows = connection.execute(
            """SELECT original_identity_json, state, dispatch_state,
                      provider_identity_json, outcome_code, dispatch_result_json
               FROM execution_decision_intents WHERE intent_id=?""",
            (intent.intent_id,),
        ).fetchone()
        assert recovered_rows == original_rows
        assert connection.execute(
            "SELECT intent_id FROM execution_native_intent_identities"
        ).fetchall() == [(intent.intent_id,)]


def test_legacy_order_ref_without_ctp_identity_stays_unindexed(tmp_path):
    path = tmp_path / "legacy-order-ref.sqlite3"
    journal = ExecutionDecisionJournal(path)
    _, intent = _prepare(journal, original_identity={"order_ref": 9})
    journal.close()

    with sqlite3.connect(path) as connection:
        _drop_v12_durable_capacity_tables(connection)
        connection.execute("PRAGMA user_version = 7")

    recovered = ExecutionDecisionJournal(path)
    assert recovered.intent(intent.intent_id) is not None
    assert (
        recovered.intent_by_native_order_ref(
            account_scope="account-a",
            strategy_scope="strategy-a",
            trading_day="20261024",
            instrument="SIM-IF-1",
            exchange="CFFEX",
            order_ref="9",
        )
        is None
    )
    assert (
        recovered._connection.execute(
            "SELECT COUNT(*) FROM execution_native_intent_identities"
        ).fetchone()[0]
        == 0
    )
    recovered.close()


def test_native_order_ref_collision_rolls_back_second_intent(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "native-ref-collision.sqlite3")
    first_key = _intent_key("SIM-IF-1")
    first_decision = journal.record_decision(
        _decision_key("native-collision-a"),
        _decision_payload(),
        intent_keys=(first_key,),
    )
    first = journal.prepare_intent(
        first_decision.decision_id,
        first_key,
        _order_payload(),
        original_identity=_native_order_identity("9001"),
    )
    second_key = _intent_key("SIM-IF-2")
    second_decision = journal.record_decision(
        _decision_key("native-collision-b"),
        _decision_payload(),
        intent_keys=(second_key,),
    )

    with pytest.raises(ExecutionDecisionJournalError, match="NATIVE_ORDER_IDENTITY_CONFLICT"):
        journal.prepare_intent(
            second_decision.decision_id,
            second_key,
            _order_payload(),
            original_identity=_native_order_identity("9001", instrument="SIM-IF-2"),
        )

    assert (
        journal.intent_by_native_order_ref(
            account_scope="account-a",
            strategy_scope="strategy-a",
            trading_day="20261024",
            instrument="SIM-IF-1",
            exchange="CFFEX",
            order_ref="9001",
        ).intent_id
        == first.intent_id
    )
    assert (
        journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decision_intents WHERE decision_id=?",
            (second_decision.decision_id,),
        ).fetchone()[0]
        == 0
    )
    assert journal.active_instrument_owner("account-a", "SIM-IF-2") is None
    journal.close()


def test_v7_native_ref_collision_aborts_backfill_without_mutating_intents(tmp_path):
    path = tmp_path / "schema-v7-native-collision.sqlite3"
    journal = ExecutionDecisionJournal(path)
    first_key = _intent_key("SIM-IF-1")
    first_decision = journal.record_decision(
        _decision_key("native-migration-collision-a"),
        _decision_payload(),
        intent_keys=(first_key,),
    )
    first = journal.prepare_intent(
        first_decision.decision_id,
        first_key,
        _order_payload(),
        original_identity=_native_order_identity("9101"),
    )
    second_key = _intent_key("SIM-IF-2")
    second_decision = journal.record_decision(
        _decision_key("native-migration-collision-b"),
        _decision_payload(),
        intent_keys=(second_key,),
    )
    second = journal.prepare_intent(
        second_decision.decision_id,
        second_key,
        _order_payload(),
        original_identity=_native_order_identity("9102", instrument="SIM-IF-2"),
    )
    journal.claim_dispatch(first.intent_id)
    journal.record_dispatch_result(first.intent_id, state="UNKNOWN", outcome_code="connection_lost")
    journal.claim_dispatch(second.intent_id)
    journal.record_dispatch_result(
        second.intent_id, state="UNKNOWN", outcome_code="connection_lost"
    )
    journal.close()

    with sqlite3.connect(path) as connection:
        second_row = connection.execute(
            "SELECT original_identity_json FROM execution_decision_intents WHERE intent_id=?",
            (second.intent_id,),
        ).fetchone()
        second_identity = json.loads(second_row[0])
        second_identity["order_ref"] = "9101"
        connection.execute(
            "UPDATE execution_decision_intents SET original_identity_json=? WHERE intent_id=?",
            (json.dumps(second_identity, sort_keys=True, separators=(",", ":")), second.intent_id),
        )
        connection.execute("DELETE FROM execution_native_intent_identities")
        _drop_v12_durable_capacity_tables(connection)
        connection.execute("PRAGMA user_version = 7")
        raw_conflict = connection.execute(
            """SELECT intent_id, original_identity_json, state, dispatch_state,
                      outcome_code, dispatch_result_json
               FROM execution_decision_intents ORDER BY intent_id"""
        ).fetchall()

    with pytest.raises(ExecutionDecisionJournalError, match="NATIVE_ORDER_IDENTITY_CONFLICT"):
        ExecutionDecisionJournal(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 7
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM execution_native_intent_identities"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                """SELECT intent_id, original_identity_json, state, dispatch_state,
                      outcome_code, dispatch_result_json
               FROM execution_decision_intents ORDER BY intent_id"""
            ).fetchall()
            == raw_conflict
        )


def test_multileg_partial_dispatch_is_sequential_and_unknown_never_retries(tmp_path):
    path = tmp_path / "multi.sqlite3"
    journal = ExecutionDecisionJournal(path, max_pending_intents=4)
    keys = (
        _intent_key("SIM-IF-1", leg=0),
        _intent_key("SIM-IF-2", leg=1, side="SELL", effect="CLOSE"),
    )
    decision = journal.record_decision(_decision_key(), _decision_payload(), intent_keys=keys)
    first = journal.prepare_intent(
        decision.decision_id,
        keys[0],
        _order_payload(),
        original_identity={"backtrader_order_ref": 10, "client_order_id": "bt-10"},
    )
    first_claim = journal.claim_dispatch(first.intent_id)
    assert first_claim is not None
    assert first_claim.intent.state == "DISPATCHING"
    second = journal.prepare_intent(
        decision.decision_id,
        keys[1],
        _order_payload(quantity="1"),
        original_identity={"backtrader_order_ref": 11, "client_order_id": "bt-11"},
    )
    with pytest.raises(ExecutionDecisionJournalError, match="PRIOR_INTENT_NOT_KNOWN"):
        journal.claim_dispatch(second.intent_id)

    claim = first_claim
    assert claim.intent.original_identity["client_order_id"] == "bt-10"
    with pytest.raises(TypeError):
        claim.intent.original_identity["client_order_id"] = "changed"
    assert journal.claim_dispatch(first.intent_id) is None
    unknown = journal.record_dispatch_result(
        first.intent_id, state="UNKNOWN", outcome_code="connection_lost"
    )
    assert unknown.state == "UNKNOWN"
    assert journal.claim_dispatch(first.intent_id) is None
    with pytest.raises(ExecutionDecisionJournalError, match="PRIOR_INTENT_NOT_KNOWN"):
        journal.claim_dispatch(second.intent_id)
    journal.close()

    recovered = ExecutionDecisionJournal(path)
    recovered_first = recovered.intent(first.intent_id)
    assert recovered_first is not None
    assert recovered_first.state == "UNKNOWN"
    assert recovered_first.original_identity == {
        "backtrader_order_ref": 10,
        "client_order_id": "bt-10",
    }
    assert recovered.claim_dispatch(first.intent_id) is None
    recovered.close()


def test_same_instrument_close_open_reversal_is_two_decisions(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "reversal.sqlite3")
    reversal = (
        _intent_key("SIM-IF-1", leg=0, side="SELL", effect="CLOSE"),
        _intent_key("SIM-IF-1", leg=1, side="BUY", effect="OPEN"),
    )
    with pytest.raises(ExecutionDecisionJournalError, match="DUPLICATE_INSTRUMENT_INTENT"):
        journal.record_decision(_decision_key(), _decision_payload(), intent_keys=reversal)
    journal.close()


@pytest.mark.parametrize("final_state", ["DISPATCHING", "UNKNOWN"])
def test_fresh_process_recovery_never_reclaims_original_dispatch(tmp_path, final_state):
    path = tmp_path / (final_state.lower() + ".sqlite3")
    journal = ExecutionDecisionJournal(path)
    _, intent = _prepare(
        journal,
        original_identity={"backtrader_order_ref": 77, "provider_client_id": "client-77"},
    )
    assert journal.claim_dispatch(intent.intent_id) is not None
    if final_state == "UNKNOWN":
        journal.record_dispatch_result(intent.intent_id, state="UNKNOWN")
    journal.close()

    child = r"""
import json, sys
from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal
journal = ExecutionDecisionJournal(sys.argv[1])
intent = journal.intent(sys.argv[2])
claim = journal.claim_dispatch(sys.argv[2])
assert intent is not None
print(json.dumps({"state": intent.state, "identity": dict(intent.original_identity),
                  "claimed": claim is not None}, sort_keys=True))
journal.close()
"""
    completed = subprocess.run(
        [sys.executable, "-c", child, str(path), intent.intent_id],
        cwd=os.getcwd(),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    report = json.loads(completed.stdout)
    assert report == {
        "state": final_state,
        "identity": {"backtrader_order_ref": 77, "provider_client_id": "client-77"},
        "claimed": False,
    }


def test_cross_run_owner_survives_known_ack_until_terminal_position_reconcile(tmp_path):
    path = tmp_path / "owners.sqlite3"
    journal = ExecutionDecisionJournal(path)
    open_key = _intent_key("SIM-IF-1", leg=0, side="BUY", effect="OPEN")
    first_decision, opening = _prepare(
        journal,
        key=_decision_key("run-open"),
        intent_key=open_key,
        original_identity={"backtrader_order_ref": 101, "client_order_id": "open-101"},
    )
    assert journal.claim_dispatch(opening.intent_id) is not None
    known = journal.record_dispatch_result(
        opening.intent_id,
        state="KNOWN",
        provider_identity={"order_id": "sim-5001"},
        outcome_code="accepted",
    )
    assert known.state == "KNOWN"
    owner = journal.active_instrument_owner("account-a", "SIM-IF-1")
    assert owner is not None and owner.intent_id == opening.intent_id

    close_key = _intent_key("SIM-IF-1", leg=0, side="SELL", effect="CLOSE")
    next_decision = journal.record_decision(
        _decision_key("run-close"),
        _decision_payload(direction="close"),
        intent_keys=(close_key,),
    )
    with pytest.raises(ExecutionDecisionJournalError, match="INSTRUMENT_OWNER_ACTIVE"):
        journal.prepare_intent(next_decision.decision_id, close_key, _order_payload())

    with pytest.raises(ExecutionDecisionJournalError, match="INTENT_NOT_RECONCILED_TERMINAL"):
        journal.release_instrument_owner(
            opening.intent_id,
            reconciliation_id="recon-1",
        )
    open_reconciliation = _record_terminal_reconciliation(
        journal,
        opening,
        reconciliation_id="recon-1",
        query_id="query-open-1",
        event_id="sim-event-5001-filled",
        snapshot_id="position-after-open-1",
        position_flat=False,
        provider_order_id="sim-5001",
    )
    resolution = journal.release_instrument_owner(
        opening.intent_id,
        reconciliation_id=open_reconciliation.reconciliation_id,
    )
    assert resolution.position_flat is False
    assert journal.active_instrument_owner("account-a", "SIM-IF-1") is None

    close_intent = journal.prepare_intent(
        next_decision.decision_id,
        close_key,
        _order_payload(quantity="2", price="4010"),
        original_identity={"backtrader_order_ref": 102, "client_order_id": "close-102"},
    )
    assert close_intent.state == "PREPARED"
    assert close_intent.owner_intent_id is None
    assert journal.claim_dispatch(close_intent.intent_id) is not None
    close_known = journal.record_dispatch_result(
        close_intent.intent_id,
        state="KNOWN",
        provider_identity={"order_id": "sim-5002"},
        outcome_code="accepted",
    )
    assert close_known.state == "KNOWN"
    close_reconciliation = _record_terminal_reconciliation(
        journal,
        close_intent,
        reconciliation_id="recon-2",
        query_id="query-close-1",
        event_id="sim-event-5002-filled",
        snapshot_id="position-after-close-1",
        position_flat=True,
        provider_order_id="sim-5002",
    )
    close_resolution = journal.release_instrument_owner(
        close_intent.intent_id,
        reconciliation_id=close_reconciliation.reconciliation_id,
    )
    assert close_resolution.position_flat is True
    assert journal.active_instrument_owner("account-a", "SIM-IF-1") is None
    journal.close()


def test_unknown_owner_blocks_same_instrument_in_a_new_logical_run(tmp_path):
    path = tmp_path / "unknown-owner.sqlite3"
    journal = ExecutionDecisionJournal(path)
    _, original = _prepare(journal)
    journal.claim_dispatch(original.intent_id)
    journal.record_dispatch_result(original.intent_id, state="UNKNOWN")
    journal.close()

    recovered = ExecutionDecisionJournal(path)
    owner = recovered.active_instrument_owner("account-a", "SIM-IF-1")
    assert owner is not None
    assert owner.intent_id == original.intent_id
    assert owner.state == "UNKNOWN"
    recovered_intent = recovered.intent(original.intent_id)
    assert recovered_intent.dispatch_state == "UNKNOWN"
    assert recovered_intent.provider_identity == {}
    next_key = _intent_key("SIM-IF-1", side="SELL", effect="CLOSE")
    next_decision = recovered.record_decision(
        _decision_key("run-next"), _decision_payload(), intent_keys=(next_key,)
    )
    with pytest.raises(ExecutionDecisionJournalError, match="INSTRUMENT_OWNER_ACTIVE"):
        recovered.prepare_intent(next_decision.decision_id, next_key, _order_payload())
    recovered.close()


def test_dispatching_crash_recovery_rejects_unproven_terminal_and_keeps_owner(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "dispatching-no-fill.sqlite3")
    _decision, intent = _prepare(
        journal,
        original_identity={
            "backtrader_order_ref": 41,
            "order_ref": "501",
            "instrument_id": "SIM-IF-1",
            "exchange_id": "CFFEX",
            "trading_day": "20261024",
            "operation": "insert",
        },
    )
    assert journal.claim_dispatch(intent.intent_id) is not None

    with pytest.raises(
        ExecutionDecisionJournalError,
        match="DISPATCHING_NO_FILL_EVIDENCE_MISMATCH",
    ):
        journal.record_dispatching_no_fill_terminal(
            intent.intent_id,
            reconciliation_id="crash-recovery-unproven",
            query_id="orders-query-unproven",
            provider_identity={},
            terminal_state="CANCELLED",
            terminal_event_id="orders-query-unproven",
            position_snapshot_id="positions-snapshot-unproven",
            expected_original_identity=intent.original_identity,
        )

    current = journal.intent(intent.intent_id)
    owner = journal.active_instrument_owner("account-a", intent.key.instrument)
    assert current is not None
    assert current.state == "DISPATCHING"
    assert current.dispatch_state is None
    assert current.provider_identity is None
    assert current.outcome_code is None
    assert owner is not None and owner.intent_id == intent.intent_id
    with pytest.raises(
        ExecutionDecisionJournalError,
        match="INTENT_NOT_RECONCILED_TERMINAL",
    ):
        journal.release_instrument_owner(
            intent.intent_id,
            reconciliation_id="crash-recovery-unproven",
        )
    journal.close()


def test_unknown_query_resolution_is_append_only_and_allows_close_after_fill(tmp_path):
    path = tmp_path / "resolve-unknown.sqlite3"
    journal = ExecutionDecisionJournal(path)
    _, opening = _prepare(
        journal,
        original_identity={"backtrader_order_ref": 81, "client_order_id": "client-81"},
    )
    assert journal.claim_dispatch(opening.intent_id) is not None
    original_unknown = journal.record_dispatch_result(
        opening.intent_id,
        state="UNKNOWN",
        outcome_code="connection_lost_after_send",
    )
    journal.close()

    recovered = ExecutionDecisionJournal(path)
    unknown_query = recovered.record_reconciliation(
        opening.intent_id,
        reconciliation_id="recon-query-unknown",
        query_id="provider-query-1",
        state="UNKNOWN",
        outcome_code="order_not_visible_yet",
    )
    replay_unknown = recovered.record_reconciliation(
        opening.intent_id,
        reconciliation_id="recon-query-unknown",
        query_id="provider-query-1",
        state="UNKNOWN",
        outcome_code="order_not_visible_yet",
    )
    assert replay_unknown == unknown_query
    assert recovered.intent(opening.intent_id).state == "UNKNOWN"
    assert recovered.intent(opening.intent_id).dispatch_state == "UNKNOWN"
    assert recovered.claim_dispatch(opening.intent_id) is None
    with pytest.raises(ExecutionDecisionJournalError, match="INTENT_NOT_RECONCILED_TERMINAL"):
        recovered.release_instrument_owner(
            opening.intent_id, reconciliation_id=unknown_query.reconciliation_id
        )
    with pytest.raises(ExecutionDecisionJournalError, match="RECONCILIATION_CONFLICT"):
        recovered.record_reconciliation(
            opening.intent_id,
            reconciliation_id="recon-query-unknown",
            query_id="provider-query-1",
            state="KNOWN",
            provider_identity={"order_id": "sim-810"},
        )
    with pytest.raises(ExecutionDecisionJournalError, match="RECONCILIATION_QUERY_CONFLICT"):
        recovered.record_reconciliation(
            opening.intent_id,
            reconciliation_id="different-receipt-same-query",
            query_id="provider-query-1",
            state="UNKNOWN",
            outcome_code="order_not_visible_yet",
        )

    filled = _record_terminal_reconciliation(
        recovered,
        opening,
        reconciliation_id="recon-query-filled",
        query_id="provider-query-2",
        event_id="sim-event-810-filled",
        snapshot_id="position-after-open-810",
        position_flat=False,
        provider_order_id="sim-810",
    )
    assert filled.original_identity == {
        "backtrader_order_ref": 81,
        "client_order_id": "client-81",
    }
    with pytest.raises(TypeError):
        filled.original_identity["client_order_id"] = "mutated"
    resolved_intent = recovered.intent(opening.intent_id)
    assert resolved_intent.state == "KNOWN"
    assert resolved_intent.dispatch_state == "UNKNOWN"
    assert resolved_intent.provider_identity == {}
    assert resolved_intent.outcome_code == "connection_lost_after_send"
    assert recovered.claim_dispatch(opening.intent_id) is None
    assert (
        recovered.record_reconciliation(
            opening.intent_id,
            reconciliation_id="recon-query-filled",
            query_id="provider-query-2",
            state="KNOWN",
            provider_identity={"order_id": "sim-810"},
            outcome_code="filled",
            terminal_state="FILLED",
            terminal_event_id="sim-event-810-filled",
            position_snapshot_id="position-after-open-810",
            position_flat=False,
        )
        == filled
    )
    with pytest.raises(ExecutionDecisionJournalError, match="RECONCILIATION_CONFLICT"):
        recovered.record_reconciliation(
            opening.intent_id,
            reconciliation_id="recon-query-filled",
            query_id="provider-query-2",
            state="KNOWN",
            provider_identity={"order_id": "sim-810"},
            outcome_code="filled",
            terminal_state="FILLED",
            terminal_event_id="different-event",
            position_snapshot_id="position-after-open-810",
            position_flat=False,
        )
    with pytest.raises(ExecutionDecisionJournalError, match="INTENT_NOT_RECONCILED_TERMINAL"):
        recovered.release_instrument_owner(
            opening.intent_id, reconciliation_id=unknown_query.reconciliation_id
        )
    resolution = recovered.release_instrument_owner(
        opening.intent_id, reconciliation_id=filled.reconciliation_id
    )
    assert resolution.position_flat is False
    assert resolution.terminal_event_id == "sim-event-810-filled"
    assert recovered.active_instrument_owner("account-a", "SIM-IF-1") is None

    close_key = _intent_key("SIM-IF-1", side="SELL", effect="CLOSE")
    close_decision = recovered.record_decision(
        _decision_key("run-close-after-recovery"),
        _decision_payload(direction="close"),
        intent_keys=(close_key,),
    )
    close_intent = recovered.prepare_intent(
        close_decision.decision_id,
        close_key,
        _order_payload(quantity="2", price="4000"),
        original_identity={"backtrader_order_ref": 82, "client_order_id": "client-82"},
    )
    assert recovered.claim_dispatch(close_intent.intent_id) is not None
    recovered.record_dispatch_result(
        close_intent.intent_id,
        state="KNOWN",
        provider_identity={"order_id": "sim-811"},
        outcome_code="accepted",
    )
    close_reconciliation = _record_terminal_reconciliation(
        recovered,
        close_intent,
        reconciliation_id="recon-close-flat",
        query_id="provider-query-3",
        event_id="sim-event-811-filled",
        snapshot_id="position-after-close-811",
        position_flat=True,
        provider_order_id="sim-811",
    )
    assert (
        recovered.release_instrument_owner(
            close_intent.intent_id,
            reconciliation_id=close_reconciliation.reconciliation_id,
        ).position_flat
        is True
    )
    assert original_unknown.dispatch_state == "UNKNOWN"
    recovered.close()


def test_cancel_is_bound_to_active_owner_and_does_not_replace_it(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "cancel.sqlite3")
    _, submit = _prepare(journal)
    journal.claim_dispatch(submit.intent_id)
    journal.record_dispatch_result(
        submit.intent_id, state="KNOWN", provider_identity={"order_id": "sim-10"}
    )

    cancel_key = _intent_key("SIM-IF-1", action="CANCEL", leg=0)
    cancel_decision = journal.record_decision(
        _decision_key(kind="cancel"),
        {"target_backtrader_order_ref": 41},
        intent_keys=(cancel_key,),
    )
    with pytest.raises(ExecutionDecisionJournalError, match="CANCEL_OWNER_MISMATCH"):
        journal.prepare_intent(
            cancel_decision.decision_id,
            cancel_key,
            {"provider_order_id": "sim-10"},
            owner_intent_id="wrong-owner",
        )
    cancel = journal.prepare_intent(
        cancel_decision.decision_id,
        cancel_key,
        {"provider_order_id": "sim-10"},
        original_identity={"backtrader_order_ref": 41, "provider_order_id": "sim-10"},
        owner_intent_id=submit.intent_id,
    )
    assert cancel.owner_intent_id == submit.intent_id
    assert journal.claim_dispatch(cancel.intent_id) is not None
    assert journal.active_instrument_owner("account-a", "SIM-IF-1").intent_id == submit.intent_id
    journal.close()


def test_callbacks_are_deduplicated_bounded_and_acknowledged_after_delivery(tmp_path):
    path = tmp_path / "callbacks.sqlite3"
    journal = ExecutionDecisionJournal(path, max_pending_callbacks=1)
    _, intent = _prepare(journal)
    evidence = {"event_id": "fill-1", "state": "PARTIALLY_FILLED", "filled_quantity": "1.00"}
    receipt = journal.record_callback(intent.intent_id, "provider-event-1", evidence)
    replay = journal.record_callback(
        intent.intent_id,
        "provider-event-1",
        {
            "filled_quantity": Decimal("1.000"),
            "state": "PARTIALLY_FILLED",
            "event_id": "fill-1",
        },
    )
    assert replay.receipt_id == receipt.receipt_id
    assert len(journal.pending_callbacks(limit=1)) == 1
    with pytest.raises(ExecutionDecisionJournalError, match="CALLBACK_CONFLICT"):
        journal.record_callback(
            intent.intent_id,
            "provider-event-1",
            {"event_id": "fill-1", "state": "FILLED", "filled_quantity": "2"},
        )
    with pytest.raises(ExecutionDecisionJournalError, match="PENDING_CALLBACK_LIMIT"):
        journal.record_callback(intent.intent_id, "provider-event-2", {"state": "FILLED"})
    journal.close()

    # A crash after caller delivery but before acknowledgment replays the same
    # durable identity; the caller can deduplicate before acknowledging it.
    reopened = ExecutionDecisionJournal(path, max_pending_callbacks=1)
    pending = reopened.pending_callbacks(limit=1)
    assert len(pending) == 1
    assert pending[0].receipt_id == receipt.receipt_id
    redelivery = reopened.record_callback(intent.intent_id, "provider-event-1", evidence)
    assert redelivery.receipt_id == receipt.receipt_id
    assert redelivery.acknowledged is False
    reopened.acknowledge_callback(receipt.receipt_id)
    assert reopened.pending_callbacks(limit=1) == ()
    acknowledged_replay = reopened.record_callback(intent.intent_id, "provider-event-1", evidence)
    assert acknowledged_replay.acknowledged is True
    assert reopened.pending_callbacks(limit=1) == ()
    with pytest.raises(TypeError):
        acknowledged_replay.evidence_payload["state"] = "MUTATED"
    assert not hasattr(reopened, "fills")
    assert not hasattr(reopened, "balances")
    reopened.close()


def test_projected_callback_roundtrip_replay_and_exact_key_blocking(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "projected-callback.sqlite3")
    intent_key = _intent_key("SIM-IF-1", effect="OPEN")
    decision = journal.record_decision(
        _decision_key("projected-callback"),
        _decision_payload(),
        intent_keys=(intent_key,),
    )
    intent = journal.prepare_intent(
        decision.decision_id,
        intent_key,
        {
            "quantity": "1",
            "price": "100",
            "exchange": "CFFEX",
            "factor_stop_price": "90",
            "risk_policy_id": "risk-v1",
            "risk_policy": {"max_loss_per_position": "10"},
        },
    )
    callback_id = "trade-event-1"
    evidence = {
        "event_type": "execution_fill",
        "execution_id": "trade-1",
        "quantity": "1",
        "price": "100",
        "fee": None,
        "filled_at_ns": 1_798_192_800_000_000_000,
        "exchange": "CFFEX",
    }
    claim = journal.claim_dispatch(intent.intent_id)
    assert claim is not None
    assert claim.intent.state == "DISPATCHING"

    def project(cursor, receipt_id):
        return apply_factor_execution_fill(cursor, receipt_id=receipt_id)

    before_receipt = journal.callback_projection_status(intent.intent_id, callback_id, evidence)
    assert before_receipt.status == "UNRECONCILED"
    first, first_projection = journal.record_callback_projected(
        intent.intent_id, callback_id, evidence, project=project
    )
    assert first.is_new is True
    assert first_projection.status == "APPLIED"
    assert journal.callback_projection_status(intent.intent_id, callback_id, evidence).status == (
        "APPLIED"
    )

    replay, replay_projection = journal.record_callback_projected(
        intent.intent_id, callback_id, evidence, project=project
    )
    assert replay.receipt_id == first.receipt_id
    assert replay.is_new is False
    assert replay_projection.status == "DUPLICATE"
    assert journal.callback_projection_status(intent.intent_id, callback_id, evidence).status == (
        "APPLIED"
    )

    wrong_callback = journal.callback_projection_status(
        intent.intent_id, "different-trade-event", evidence
    )
    assert wrong_callback.status == "UNRECONCILED"
    mismatched_evidence = dict(evidence, quantity="2")
    wrong_payload = journal.callback_projection_status(
        intent.intent_id, callback_id, mismatched_evidence
    )
    assert wrong_payload.status == "BLOCKED"
    assert wrong_payload.blocker_code == "CALLBACK_EVIDENCE_CONFLICT"
    with pytest.raises(ExecutionDecisionJournalError, match="CALLBACK_CONFLICT"):
        journal.record_callback_projected(
            intent.intent_id, callback_id, mismatched_evidence, project=project
        )
    persisted = journal.callback_receipt(intent.intent_id, callback_id)
    assert persisted is not None
    assert persisted.receipt_id == first.receipt_id
    assert persisted.evidence_payload == first.evidence_payload
    with pytest.raises(ExecutionDecisionJournalError, match="INTENT_NOT_PREPARED"):
        journal.record_callback_projected("missing-intent", callback_id, evidence, project=project)
    journal.close()


def test_pending_intent_limit_and_sqlite_write_failure_fail_closed(tmp_path):
    path = tmp_path / "failure.sqlite3"
    journal = ExecutionDecisionJournal(path, max_pending_intents=1)
    _, first = _prepare(journal)
    with pytest.raises(ExecutionDecisionJournalError, match="PENDING_INTENT_LIMIT"):
        journal.record_decision(
            _decision_key("run-b"),
            _decision_payload(),
            intent_keys=(_intent_key("SIM-IF-2"),),
        )

    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_dispatch_claim
               BEFORE UPDATE OF state ON execution_decision_intents
               BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END"""
        )
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_WRITE_FAILED"):
        journal.claim_dispatch(first.intent_id)
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_FAILED_CLOSED"):
        journal.claim_dispatch(first.intent_id)
    journal.close()

    reopened = ExecutionDecisionJournal(path, max_pending_intents=1)
    persisted = reopened.intent(first.intent_id)
    assert persisted is not None
    assert persisted.state == "PREPARED"
    assert persisted.dispatch_state is None
    reopened.close()


def test_partial_write_failures_roll_back_and_latch_the_instance(tmp_path):
    decision_path = tmp_path / "decision-rollback.sqlite3"
    decision_journal = ExecutionDecisionJournal(decision_path)
    with sqlite3.connect(decision_path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_decision_slot
               BEFORE INSERT ON execution_decision_slots
               BEGIN SELECT RAISE(ABORT, 'synthetic slot write failure'); END"""
        )
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_WRITE_FAILED"):
        decision_journal.record_decision(
            _decision_key("rollback-decision"),
            _decision_payload(),
            intent_keys=(_intent_key(),),
        )
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_FAILED_CLOSED"):
        decision_journal.record_decision(_decision_key("after-failure"), _decision_payload())
    decision_journal.close()
    with sqlite3.connect(decision_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM execution_decision_slots").fetchone()[0] == 0
        )

    intent_path = tmp_path / "intent-rollback.sqlite3"
    intent_journal = ExecutionDecisionJournal(intent_path)
    decision = intent_journal.record_decision(
        _decision_key("rollback-intent"),
        _decision_payload(),
        intent_keys=(_intent_key(),),
    )
    with sqlite3.connect(intent_path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_intent_insert
               BEFORE INSERT ON execution_decision_intents
               BEGIN SELECT RAISE(ABORT, 'synthetic intent write failure'); END"""
        )
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_WRITE_FAILED"):
        intent_journal.prepare_intent(decision.decision_id, _intent_key(), _order_payload())
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_FAILED_CLOSED"):
        intent_journal.prepare_intent(decision.decision_id, _intent_key(), _order_payload())
    intent_journal.close()

    reopened = ExecutionDecisionJournal(intent_path)
    assert reopened.decision(decision.decision_id) is not None
    with sqlite3.connect(intent_path) as connection:
        intent_id = connection.execute(
            "SELECT intent_id FROM execution_decision_slots WHERE decision_id = ?",
            (decision.decision_id,),
        ).fetchone()[0]
    assert reopened.intent(intent_id) is None
    assert reopened.active_instrument_owner("account-a", "SIM-IF-1") is None
    with sqlite3.connect(intent_path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM execution_instrument_owners WHERE owner_intent_id IS NOT NULL"
            ).fetchone()[0]
            == 0
        )
    reopened.close()


def test_prepared_intent_can_be_abandoned_without_dispatch(tmp_path):
    path = tmp_path / "abandon.sqlite3"
    journal = ExecutionDecisionJournal(path, max_pending_intents=1)
    _, stale = _prepare(journal)
    owner = journal.active_instrument_owner("account-a", "SIM-IF-1")
    assert owner is not None and owner.intent_id == stale.intent_id

    abandonment = journal.abandon_prepared_intent(
        stale.intent_id, reason_code="quote_expired_before_dispatch"
    )
    assert abandonment == journal.abandon_prepared_intent(
        stale.intent_id, reason_code="quote_expired_before_dispatch"
    )
    assert journal.active_instrument_owner("account-a", "SIM-IF-1") is None
    assert journal.recoverable_intents(limit=1) == ()
    assert journal.execution_intent_snapshot(limit=1).items == ()
    assert journal.intent(stale.intent_id) == stale
    assert abandonment.intent_id == stale.intent_id
    with pytest.raises(ExecutionDecisionJournalError, match="INTENT_ABANDONED"):
        journal.claim_dispatch(stale.intent_id)
    with pytest.raises(ExecutionDecisionJournalError, match="INTENT_ABANDONMENT_CONFLICT"):
        journal.abandon_prepared_intent(stale.intent_id, reason_code="different_reason")

    next_key = _intent_key("SIM-IF-1", side="BUY", effect="OPEN")
    decision = journal.record_decision(
        _decision_key("run-after-abandon"), _decision_payload(), intent_keys=(next_key,)
    )
    next_intent = journal.prepare_intent(decision.decision_id, next_key, _order_payload())
    assert next_intent.state == "PREPARED"
    assert journal.claim_dispatch(next_intent.intent_id) is not None
    with pytest.raises(ExecutionDecisionJournalError, match="INTENT_NOT_ABANDONABLE"):
        journal.abandon_prepared_intent(next_intent.intent_id, reason_code="claimed_cannot_abandon")
    journal.close()


def test_two_journal_connections_cannot_claim_the_same_intent_twice(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    first_journal = ExecutionDecisionJournal(path)
    _, intent = _prepare(first_journal)
    second_journal = ExecutionDecisionJournal(path)
    first_claim = first_journal.claim_dispatch(intent.intent_id)
    second_claim = second_journal.claim_dispatch(intent.intent_id)
    assert first_claim is not None
    assert second_claim is None
    first_journal.close()
    second_journal.close()


def test_two_subprocesses_racing_for_one_dispatch_have_one_winner(tmp_path):
    path = tmp_path / "subprocess-race.sqlite3"
    journal = ExecutionDecisionJournal(path)
    _, intent = _prepare(journal)
    journal.close()

    gate = tmp_path / "race-start"
    ready_paths = (tmp_path / "worker-1-ready", tmp_path / "worker-2-ready")
    worker = r"""
import json, pathlib, sys, time
from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal
database, intent_id, ready_path, start_path = sys.argv[1:]
pathlib.Path(ready_path).write_text("ready", encoding="ascii")
deadline = time.monotonic() + 20
while not pathlib.Path(start_path).exists():
    if time.monotonic() >= deadline:
        raise SystemExit("start barrier timed out")
    time.sleep(0.005)
journal = ExecutionDecisionJournal(database)
claim = journal.claim_dispatch(intent_id)
print(json.dumps({"claimed": claim is not None}))
journal.close()
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", worker, str(path), intent.intent_id, str(ready), str(gate)],
            cwd=os.getcwd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for ready in ready_paths
    ]
    try:
        deadline = time.monotonic() + 20
        while not all(ready.exists() for ready in ready_paths):
            if time.monotonic() >= deadline:
                raise AssertionError("subprocess workers did not reach the start barrier")
            if any(process.poll() is not None for process in processes):
                raise AssertionError("a subprocess worker exited before the start barrier")
            time.sleep(0.005)
        gate.touch()
        results = [process.communicate(timeout=30) for process in processes]
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    assert all(process.returncode == 0 for process in processes), results
    claims = [json.loads(stdout)["claimed"] for stdout, _stderr in results]
    assert sum(claims) == 1
    assert all(stderr == "" for _stdout, stderr in results)


def test_eligible_grid_decision_and_cursor_commit_atomically_including_noop(tmp_path):
    path = tmp_path / "grid.sqlite3"
    journal = ExecutionDecisionJournal(path)
    key = _decision_key(close_time="2026-10-20T10:00:00Z")
    first = journal.record_grid_decision(
        key,
        {"signal": "flat", "quantity": "0"},
        epoch_id="epoch-a",
        batch_id="batch-a",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
    )
    assert first.eligible is True
    assert first.is_new_grid is True
    assert first.decision is not None and first.decision.is_noop is True
    assert first.cursor is not None
    assert first.cursor.ordinal == 1
    assert first.cursor.decision_id == first.decision.decision_id

    replay = journal.record_grid_decision(
        _decision_key(close_time="2026-10-20T18:00:00+08:00"),
        {"quantity": Decimal("0.0"), "signal": "flat"},
        epoch_id="epoch-a",
        batch_id="batch-a",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
    )
    assert replay.decision == first.decision
    assert replay.cursor == first.cursor
    assert replay.is_new_grid is False

    ineligible = journal.record_grid_decision(
        _decision_key(run_id="run-b", close_time="2026-10-20T10:01:00Z"),
        {"signal": "must-not-be-written"},
        epoch_id="epoch-a",
        batch_id="batch-gap",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=False,
    )
    assert ineligible.eligible is False
    assert ineligible.decision is None
    assert ineligible.cursor == first.cursor
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 1
    )

    # A later eligible grid advances once even when logical-run and epoch
    # identities change; neither identity resets consumed grid progress.
    next_grid = journal.record_grid_decision(
        _decision_key(run_id="run-b", close_time="2026-10-20T10:01:00Z"),
        {"signal": "flat"},
        epoch_id="epoch-b",
        batch_id="batch-b",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
    )
    assert next_grid.is_new_grid is True
    assert next_grid.cursor is not None and next_grid.cursor.ordinal == 2
    assert journal.grid_cursor("account-a", "strategy-a", "cohort-1") == next_grid.cursor

    with pytest.raises(ExecutionDecisionJournalError, match="GRID_CURSOR_STALE_OR_CONFLICT"):
        journal.record_grid_decision(
            _decision_key(run_id="run-c", close_time="2026-10-20T10:00:00Z"),
            {"signal": "cross-up"},
            epoch_id="epoch-c",
            batch_id="mode-changed-same-old-grid",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
        )
    assert journal.grid_cursor("account-a", "strategy-a", "cohort-1") == next_grid.cursor
    journal.close()


def test_grid_highwater_blocks_same_close_across_028_epochs_but_allows_later_and_other_scope(
    tmp_path,
):
    journal = ExecutionDecisionJournal(tmp_path / "alpha003-grid-highwater.sqlite3")
    close_time = "2026-10-24T10:00:00Z"
    epoch_a = "epoch-live-1"
    epoch_b = "epoch-live-2"
    cohort_a = f"alpha003:20261024:{epoch_a}"
    cohort_b = f"alpha003:20261024:{epoch_b}"

    first_key = _grid_key(cohort_id=cohort_a, close_time=close_time)
    first_economics = {"signal": "flat", "mode": "native", "config": "cfg-a"}
    first = _record_grid_noop(
        journal,
        first_key,
        epoch_id=epoch_a,
        batch_id="batch-1",
        economics=first_economics,
    )
    assert first.is_new_grid is True

    # Epoch/config/run changes do not make an already-consumed close new.
    second_epoch_same_close = _grid_key(
        run_id="run-b",
        cohort_id=cohort_b,
        close_time="2026-10-24T18:00:00+08:00",
    )
    with pytest.raises(ExecutionDecisionJournalError, match="GRID_CURSOR_STALE_OR_CONFLICT"):
        _record_grid_noop(
            journal,
            second_epoch_same_close,
            epoch_id=epoch_b,
            batch_id="batch-replay",
            economics={"signal": "flat", "mode": "build", "config": "cfg-b"},
        )
    assert journal.grid_cursor("account-a", "strategy-a", cohort_b) is None
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 1
    )

    # The same exact historical decision remains a no-dispatch replay after
    # its own cohort cursor has advanced.
    same_cohort_later = _grid_key(
        run_id="run-b",
        cohort_id=cohort_a,
        close_time="2026-10-24T10:00:30Z",
    )
    advanced_a = _record_grid_noop(
        journal,
        same_cohort_later,
        epoch_id=epoch_a,
        batch_id="batch-2",
    )
    assert advanced_a.is_new_grid is True
    replay = _record_grid_noop(
        journal,
        first_key,
        epoch_id=epoch_a,
        batch_id="batch-1",
        economics=first_economics,
    )
    assert replay.decision == first.decision
    assert replay.is_new_grid is False
    assert replay.cursor == advanced_a.cursor

    # Compare instants, not their normalized strings: a positive microsecond
    # timestamp sorts textually before the second-level timestamp ending in Z.
    fractional_later = _grid_key(
        run_id="run-c",
        cohort_id=cohort_b,
        close_time="2026-10-24T10:00:30.000001Z",
    )
    assert (
        _record_grid_noop(
            journal, fractional_later, epoch_id=epoch_b, batch_id="batch-fractional"
        ).is_new_grid
        is True
    )

    # A later eligible grid under a new epoch is allowed, while a genuinely
    # independent strategy scope has its own highwater at the earlier close.
    later_b = _grid_key(
        run_id="run-c",
        cohort_id=cohort_b,
        close_time="2026-10-24T10:01:00Z",
    )
    assert (
        _record_grid_noop(journal, later_b, epoch_id=epoch_b, batch_id="batch-3").is_new_grid
        is True
    )
    other_strategy = _grid_key(
        strategy_scope="strategy-b",
        cohort_id=cohort_b,
        close_time=close_time,
    )
    assert (
        _record_grid_noop(
            journal, other_strategy, epoch_id=epoch_b, batch_id="other-strategy"
        ).is_new_grid
        is True
    )
    journal.close()


def test_grid_highwater_migration_backfills_maximum_from_v9_cohort_cursors(tmp_path):
    path = tmp_path / "grid-highwater-v9-migration.sqlite3"
    journal = ExecutionDecisionJournal(path)
    epoch_a = "epoch-live-1"
    epoch_b = "epoch-live-2"
    first = _grid_key(
        cohort_id=f"alpha003:20261024:{epoch_a}",
        close_time="2026-10-24T10:00:00Z",
    )
    later = _grid_key(
        run_id="run-b",
        cohort_id=f"alpha003:20261024:{epoch_b}",
        close_time="2026-10-24T10:01:00Z",
    )
    _record_grid_noop(journal, first, epoch_id=epoch_a, batch_id="batch-1")
    _record_grid_noop(journal, later, epoch_id=epoch_b, batch_id="batch-2")
    journal.close()

    # Recreate the v9 layout: per-cohort cursors exist, the new materialized
    # stream highwater does not.
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE execution_grid_highwaters")
        _drop_v12_durable_capacity_tables(connection)
        connection.execute("PRAGMA user_version = 9")

    migrated = ExecutionDecisionJournal(path)
    assert migrated._connection.execute("PRAGMA user_version").fetchone()[0] == 13
    highwater = migrated._connection.execute(
        """SELECT close_time,cohort_id,decision_id FROM execution_grid_highwaters
           WHERE account_scope='account-a' AND strategy_scope='strategy-a'"""
    ).fetchone()
    assert highwater["close_time"] == "2026-10-24T10:01:00Z"
    assert highwater["cohort_id"] == later.cohort_id

    stale = _grid_key(
        run_id="run-c",
        cohort_id="alpha003:20261024:epoch-live-3",
        close_time="2026-10-24T10:00:30Z",
    )
    with pytest.raises(ExecutionDecisionJournalError, match="GRID_CURSOR_STALE_OR_CONFLICT"):
        _record_grid_noop(migrated, stale, epoch_id="epoch-live-3", batch_id="batch-3")
    next_grid = _grid_key(
        run_id="run-c",
        cohort_id="alpha003:20261024:epoch-live-3",
        close_time="2026-10-24T10:02:00Z",
    )
    assert (
        _record_grid_noop(
            migrated, next_grid, epoch_id="epoch-live-3", batch_id="batch-4"
        ).is_new_grid
        is True
    )
    migrated.close()


def test_grid_highwater_migration_rejects_noncanonical_legacy_cursor_time(tmp_path):
    path = tmp_path / "grid-highwater-invalid-v9-migration.sqlite3"
    journal = ExecutionDecisionJournal(path)
    epoch_a = "epoch-live-1"
    epoch_b = "epoch-live-2"
    _record_grid_noop(
        journal,
        _grid_key(
            cohort_id=f"alpha003:20261024:{epoch_a}",
            close_time="2026-10-24T10:00:00Z",
        ),
        epoch_id=epoch_a,
        batch_id="batch-1",
    )
    second = _grid_key(
        run_id="run-b",
        cohort_id=f"alpha003:20261024:{epoch_b}",
        close_time="2026-10-24T10:01:00Z",
    )
    _record_grid_noop(journal, second, epoch_id=epoch_b, batch_id="batch-2")
    journal.close()

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE execution_grid_highwaters")
        connection.execute(
            """UPDATE execution_grid_cursors SET close_time='2026-10-24T10:01:00+00:00'
               WHERE cohort_id=?""",
            (second.cohort_id,),
        )
        _drop_v12_durable_capacity_tables(connection)
        connection.execute("PRAGMA user_version = 9")

    with pytest.raises(ExecutionDecisionJournalError, match="INVALID_STORED_GRID_CLOSE_TIME"):
        ExecutionDecisionJournal(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 9
        assert connection.execute("SELECT COUNT(*) FROM execution_grid_cursors").fetchone()[0] == 2
        assert (
            connection.execute("SELECT COUNT(*) FROM execution_grid_highwaters").fetchone()[0] == 0
        )


def test_grid_highwater_and_decision_roll_back_together_on_sqlite_failure(tmp_path):
    path = tmp_path / "grid-highwater-rollback.sqlite3"
    journal = ExecutionDecisionJournal(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_grid_highwater
               BEFORE INSERT ON execution_grid_highwaters
               BEGIN SELECT RAISE(ABORT, 'synthetic highwater failure'); END"""
        )

    key = _grid_key(cohort_id="alpha003:20261024:epoch-live-1")
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_WRITE_FAILED"):
        _record_grid_noop(journal, key, epoch_id="epoch-live-1", batch_id="batch-1")
    assert journal._failed_closed is True
    journal.close()

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM execution_grid_cursors").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM execution_grid_highwaters").fetchone()[0] == 0
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM factor_position_grid_history").fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT SUM(record_count) FROM execution_decision_capacity_usage"
            ).fetchone()[0]
            == 0
        )
        connection.execute("DROP TRIGGER reject_grid_highwater")

    reopened = ExecutionDecisionJournal(path)
    assert (
        _record_grid_noop(reopened, key, epoch_id="epoch-live-1", batch_id="batch-1").is_new_grid
        is True
    )
    reopened.close()


def test_grid_decision_cursor_is_recovered_and_replay_does_not_redispatch(tmp_path):
    path = tmp_path / "grid-recovery.sqlite3"
    journal = ExecutionDecisionJournal(path)
    key = _decision_key(close_time="2026-10-20T10:00:00Z")
    result = journal.record_grid_decision(
        key,
        {"signal": "flat"},
        epoch_id="epoch-a",
        batch_id="batch-a",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
    )
    journal.close()

    child = r"""
import json, sys
from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal, ExecutionDecisionKey
journal = ExecutionDecisionJournal(sys.argv[1])
key = ExecutionDecisionKey("account-a", "strategy-a", "run-a", "cohort-1", "2026-10-20T10:00:00Z", "bar")
saved = journal.grid_cursor("account-a", "strategy-a", "cohort-1")
replay = journal.record_grid_decision(key, {"signal":"flat"}, epoch_id="epoch-a", batch_id="batch-a", eligible=True, complete=True, live_ready=True, inputs_complete=True)
assert replay.is_new_grid is False
assert replay.decision is not None and replay.decision.is_noop
assert replay.cursor == saved
print(json.dumps({"ordinal":saved.ordinal, "decision_id":saved.decision_id, "new":replay.is_new_grid}, sort_keys=True))
journal.close()
"""
    completed = subprocess.run(
        [sys.executable, "-c", child, str(path)],
        cwd=os.getcwd(),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert json.loads(completed.stdout) == {
        "ordinal": 1,
        "decision_id": result.decision.decision_id,
        "new": False,
    }


def test_grid_decision_and_cursor_roll_back_together_on_sqlite_failure(tmp_path):
    path = tmp_path / "grid-rollback.sqlite3"
    journal = ExecutionDecisionJournal(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_grid_cursor
               BEFORE INSERT ON execution_grid_cursors
               BEGIN SELECT RAISE(ABORT, 'synthetic cursor failure'); END"""
        )
    key = _decision_key(run_id="rollback-grid")
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_WRITE_FAILED"):
        journal.record_grid_decision(
            key,
            {"signal": "cross-up"},
            intent_keys=(_intent_key(),),
            epoch_id="epoch-a",
            batch_id="batch-a",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
        )
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_FAILED_CLOSED"):
        journal.record_grid_decision(
            key,
            {"signal": "cross-up"},
            intent_keys=(_intent_key(),),
            epoch_id="epoch-a",
            batch_id="batch-a",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
        )
    journal.close()

    reopened = ExecutionDecisionJournal(path)
    assert (
        reopened._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 0
    )
    assert reopened.grid_cursor("account-a", "strategy-a", "cohort-1") is None
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM execution_decision_slots").fetchone()[0] == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM execution_grid_cursors").fetchone()[0] == 0
    reopened.close()


def test_grid_order_budget_counts_submits_and_cancels_once_per_logical_run(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "grid-budget.sqlite3")
    first_key = _decision_key(run_id="budget-run", close_time="2026-10-20T10:00:00Z")
    first = journal.record_grid_decision(
        first_key,
        {"signal": "cancel-then-close"},
        intent_keys=(_intent_key("SIM-IF-1", action="CANCEL", leg=0),),
        epoch_id="epoch-a",
        batch_id="batch-a",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
        max_order_intents_per_run=2,
        expected_run_order_intents_used=0,
        remaining_exit_intent_reserve=1,
    )
    assert first.is_new_grid is True
    assert journal.run_order_count("account-a", "strategy-a", "budget-run") == 1

    replay = journal.record_grid_decision(
        first_key,
        {"signal": "cancel-then-close"},
        intent_keys=(_intent_key("SIM-IF-1", action="CANCEL", leg=0),),
        epoch_id="epoch-a",
        batch_id="batch-a",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
        max_order_intents_per_run=2,
    )
    assert replay.is_new_grid is False
    assert journal.run_order_count("account-a", "strategy-a", "budget-run") == 1
    with pytest.raises(ExecutionDecisionJournalError, match="RUN_ORDER_BUDGET_CONFLICT"):
        journal.record_grid_decision(
            first_key,
            {"signal": "cancel-then-close"},
            intent_keys=(_intent_key("SIM-IF-1", action="CANCEL", leg=0),),
            epoch_id="epoch-a",
            batch_id="batch-a",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
            max_order_intents_per_run=3,
        )

    with pytest.raises(ExecutionDecisionJournalError, match="DECISION_CONFLICT"):
        journal.record_grid_decision(
            first_key,
            {"signal": "cancel-then-close"},
            intent_keys=(_intent_key("SIM-IF-1", action="CANCEL", leg=0),),
            epoch_id="epoch-a",
            batch_id="batch-a",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
            max_order_intents_per_run=2,
            expected_run_order_intents_used=1,
            remaining_exit_intent_reserve=0,
        )
    assert journal.run_order_count("account-a", "strategy-a", "budget-run") == 1
    assert journal.grid_cursor("account-a", "strategy-a", "cohort-1") == first.cursor

    with pytest.raises(ExecutionDecisionJournalError, match="RUN_ORDER_BUDGET_STALE"):
        journal.record_grid_decision(
            _decision_key(run_id="budget-run", close_time="2026-10-20T10:01:00Z"),
            {"signal": "submit"},
            intent_keys=(_intent_key("SIM-IF-2", leg=0),),
            epoch_id="epoch-a",
            batch_id="batch-b",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
            max_order_intents_per_run=2,
            expected_run_order_intents_used=0,
            remaining_exit_intent_reserve=1,
        )
    assert journal.run_order_count("account-a", "strategy-a", "budget-run") == 1
    assert journal.grid_cursor("account-a", "strategy-a", "cohort-1") == first.cursor
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 1
    )

    with pytest.raises(ExecutionDecisionJournalError, match="RUN_ORDER_BUDGET_EXCEEDED"):
        journal.record_grid_decision(
            _decision_key(run_id="budget-run", close_time="2026-10-20T10:01:00Z"),
            {"signal": "submit"},
            intent_keys=(_intent_key("SIM-IF-2", leg=0),),
            epoch_id="epoch-a",
            batch_id="batch-b",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
            max_order_intents_per_run=2,
            expected_run_order_intents_used=1,
            remaining_exit_intent_reserve=1,
        )
    assert journal.run_order_count("account-a", "strategy-a", "budget-run") == 1
    assert journal.grid_cursor("account-a", "strategy-a", "cohort-1") == first.cursor
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 1
    )

    second = journal.record_grid_decision(
        _decision_key(run_id="budget-run", close_time="2026-10-20T10:01:00Z"),
        {"signal": "submit"},
        intent_keys=(_intent_key("SIM-IF-2", leg=0),),
        epoch_id="epoch-a",
        batch_id="batch-b",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
        max_order_intents_per_run=2,
        expected_run_order_intents_used=1,
        remaining_exit_intent_reserve=0,
    )
    assert second.is_new_grid is True
    assert second.cursor.ordinal == 2
    assert journal.run_order_count("account-a", "strategy-a", "budget-run") == 2
    journal.close()


def test_budgeted_decisions_require_reserved_evidence_and_reject_payload_collision(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "budget-evidence.sqlite3")
    key = _decision_key(run_id="budget-evidence")
    common = {
        "epoch_id": "epoch-a",
        "batch_id": "batch-a",
        "eligible": True,
        "complete": True,
        "live_ready": True,
        "inputs_complete": True,
        "max_order_intents_per_run": 0,
    }
    with pytest.raises(
        ExecutionDecisionJournalError, match="RUN_ORDER_BUDGET_RESERVATION_REQUIRED"
    ):
        journal.record_grid_decision(key, {"signal": "flat"}, **common)
    assert journal.grid_cursor("account-a", "strategy-a", "cohort-1") is None
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 0
    )
    assert journal.run_order_count("account-a", "strategy-a", "budget-evidence") == 0

    with pytest.raises(ExecutionDecisionJournalError, match="INVALID_RUN_ORDER_BUDGET_RESERVATION"):
        journal.record_grid_decision(
            key,
            {"signal": "flat"},
            **common,
            expected_run_order_intents_used=0,
        )
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 0
    )

    with pytest.raises(ExecutionDecisionJournalError, match="RUN_ORDER_BUDGET_EVIDENCE_RESERVED"):
        journal.record_grid_decision(
            key,
            {"signal": "flat", "_journal_run_order_reservation": {"fake": True}},
            **common,
            expected_run_order_intents_used=0,
            remaining_exit_intent_reserve=0,
        )
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 0
    )

    noop = journal.record_grid_decision(
        key,
        {"signal": "flat"},
        **common,
        expected_run_order_intents_used=0,
        remaining_exit_intent_reserve=0,
    )
    assert noop.is_new_grid is True
    assert noop.decision.economic_payload["_journal_run_order_reservation"] == {
        "max_order_intents_per_run": 0,
        "remaining_exit_intent_reserve": 0,
    }
    journal.close()


def test_risk_decision_uses_atomic_run_budget_and_reserve(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "risk-budget.sqlite3")
    opening = journal.record_grid_decision(
        _decision_key(run_id="risk-budget"),
        {"signal": "open"},
        intent_keys=(_intent_key("SIM-IF-1", leg=0, effect="OPEN"),),
        epoch_id="epoch-a",
        batch_id="batch-a",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
        max_order_intents_per_run=3,
        expected_run_order_intents_used=0,
        remaining_exit_intent_reserve=2,
    )
    assert opening.is_new_grid is True
    assert journal.run_order_count("account-a", "strategy-a", "risk-budget") == 1

    missing_reservation_key = _decision_key(
        run_id="risk-budget", close_time="2026-10-20T10:00:30Z", kind="risk"
    )
    before = journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0]
    with pytest.raises(
        ExecutionDecisionJournalError, match="RUN_ORDER_BUDGET_RESERVATION_REQUIRED"
    ):
        journal.record_risk_decision(
            missing_reservation_key,
            {"signal": "reduce"},
            intent_keys=(_intent_key("SIM-IF-1", side="SELL", effect="CLOSE"),),
            max_order_intents_per_run=3,
        )
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0]
        == before
    )
    assert journal.run_order_count("account-a", "strategy-a", "risk-budget") == 1

    close_key = _decision_key(run_id="risk-budget", close_time="2026-10-20T10:01:00Z", kind="risk")
    close_intents = (_intent_key("SIM-IF-1", action="SUBMIT", side="SELL", effect="CLOSE"),)
    close = journal.record_risk_decision(
        close_key,
        {"signal": "reduce"},
        intent_keys=close_intents,
        max_order_intents_per_run=3,
        expected_run_order_intents_used=1,
        remaining_exit_intent_reserve=1,
    )
    assert close.is_new_grid is True
    assert journal.run_order_count("account-a", "strategy-a", "risk-budget") == 2

    replay = journal.record_risk_decision(
        close_key,
        {"signal": "reduce"},
        intent_keys=close_intents,
        max_order_intents_per_run=3,
        expected_run_order_intents_used=0,
        remaining_exit_intent_reserve=1,
    )
    assert replay.is_new_grid is False
    assert journal.run_order_count("account-a", "strategy-a", "risk-budget") == 2

    with pytest.raises(ExecutionDecisionJournalError, match="DECISION_CONFLICT"):
        journal.record_risk_decision(
            close_key,
            {"signal": "reduce"},
            intent_keys=close_intents,
            max_order_intents_per_run=3,
            expected_run_order_intents_used=2,
            remaining_exit_intent_reserve=0,
        )

    next_risk_key = _decision_key(
        run_id="risk-budget", close_time="2026-10-20T10:02:00Z", kind="risk"
    )
    before = journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0]
    with pytest.raises(ExecutionDecisionJournalError, match="RUN_ORDER_BUDGET_STALE"):
        journal.record_risk_decision(
            next_risk_key,
            {"signal": "reduce-again"},
            intent_keys=close_intents,
            max_order_intents_per_run=3,
            expected_run_order_intents_used=1,
            remaining_exit_intent_reserve=0,
        )
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0]
        == before
    )

    with pytest.raises(ExecutionDecisionJournalError, match="RUN_ORDER_BUDGET_EXCEEDED"):
        journal.record_risk_decision(
            next_risk_key,
            {"signal": "reduce-again"},
            intent_keys=close_intents,
            max_order_intents_per_run=3,
            expected_run_order_intents_used=2,
            remaining_exit_intent_reserve=1,
        )
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0]
        == before
    )
    assert journal.run_order_count("account-a", "strategy-a", "risk-budget") == 2
    journal.close()


def test_run_order_budget_compare_and_swap_serializes_two_connections(tmp_path):
    path = tmp_path / "budget-concurrent.sqlite3"
    journals = (ExecutionDecisionJournal(path), ExecutionDecisionJournal(path))
    start = Barrier(2)

    def admit(index):
        start.wait(timeout=5)
        key = _grid_key(
            run_id="shared-run",
            cohort_id=f"cohort-{index}",
            close_time=f"2026-10-20T10:00:0{index}Z",
            kind="risk",
        )
        try:
            result = journals[index].record_risk_decision(
                key,
                {"signal": f"candidate-{index}"},
                intent_keys=(_intent_key(f"SIM-IF-{index + 1}", action="CANCEL"),),
                max_order_intents_per_run=2,
                expected_run_order_intents_used=0,
                remaining_exit_intent_reserve=1,
            )
            return "admitted" if result.is_new_grid else "replayed"
        except ExecutionDecisionJournalError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(admit, index) for index in range(2)]
        outcomes = [future.result(timeout=10) for future in futures]

    assert outcomes.count("admitted") == 1
    assert outcomes.count("RUN_ORDER_BUDGET_STALE") == 1
    assert journals[0].run_order_count("account-a", "strategy-a", "shared-run") == 1
    assert (
        journals[0]._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0]
        == 1
    )
    assert (
        journals[0]._connection.execute("SELECT COUNT(*) FROM execution_grid_cursors").fetchone()[0]
        == 0
    )
    for journal in journals:
        journal.close()


def test_run_order_budget_restart_respects_saved_usage_and_replays_without_charge(tmp_path):
    path = tmp_path / "budget-restart.sqlite3"
    journal = ExecutionDecisionJournal(path)
    first = journal.record_grid_decision(
        _decision_key(run_id="restart-budget"),
        {"signal": "open"},
        intent_keys=(_intent_key("SIM-IF-1"),),
        epoch_id="epoch-a",
        batch_id="batch-a",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
        max_order_intents_per_run=2,
        expected_run_order_intents_used=0,
        remaining_exit_intent_reserve=1,
    )
    assert first.is_new_grid is True
    journal.close()

    child = r"""
import json, sys
from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal, ExecutionDecisionJournalError, ExecutionDecisionKey, ExecutionIntentKey
journal = ExecutionDecisionJournal(sys.argv[1])
first = journal.grid_cursor("account-a", "strategy-a", "cohort-1")
key = ExecutionDecisionKey("account-a", "strategy-a", "restart-budget", "cohort-1", "2026-10-20T10:01:00Z", "bar")
intent = ExecutionIntentKey("SUBMIT", "SIM-IF-2", "BUY", "OPEN", 0)
try:
    journal.record_grid_decision(key, {"signal":"open-again"}, intent_keys=(intent,), epoch_id="epoch-a", batch_id="batch-b", eligible=True, complete=True, live_ready=True, inputs_complete=True, max_order_intents_per_run=2, expected_run_order_intents_used=1, remaining_exit_intent_reserve=1)
except ExecutionDecisionJournalError as error:
    assert error.code == "RUN_ORDER_BUDGET_EXCEEDED"
else:
    raise AssertionError("reserved exit slot was consumed")
assert journal.run_order_count("account-a", "strategy-a", "restart-budget") == 1
assert journal.grid_cursor("account-a", "strategy-a", "cohort-1") == first
assert journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 1
risk_key = ExecutionDecisionKey("account-a", "strategy-a", "restart-budget", "cohort-1", "2026-10-20T10:02:00Z", "risk")
close = ExecutionIntentKey("SUBMIT", "SIM-IF-1", "SELL", "CLOSE", 0)
saved = journal.record_risk_decision(risk_key, {"signal":"reduce"}, intent_keys=(close,), max_order_intents_per_run=2, expected_run_order_intents_used=1, remaining_exit_intent_reserve=0)
replay = journal.record_risk_decision(risk_key, {"signal":"reduce"}, intent_keys=(close,), max_order_intents_per_run=2, expected_run_order_intents_used=0, remaining_exit_intent_reserve=0)
assert saved.is_new_grid and not replay.is_new_grid
assert journal.run_order_count("account-a", "strategy-a", "restart-budget") == 2
print(json.dumps({"cursor_ordinal": first.ordinal, "risk_replayed": not replay.is_new_grid, "used": journal.run_order_count("account-a", "strategy-a", "restart-budget")}, sort_keys=True))
journal.close()
"""
    completed = subprocess.run(
        [sys.executable, "-c", child, str(path)],
        cwd=os.getcwd(),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert json.loads(completed.stdout) == {
        "cursor_ordinal": 1,
        "risk_replayed": True,
        "used": 2,
    }


def test_run_order_budget_sql_failure_rolls_back_decision_cursor_and_usage(tmp_path):
    path = tmp_path / "budget-rollback.sqlite3"
    journal = ExecutionDecisionJournal(path)
    first = journal.record_grid_decision(
        _decision_key(run_id="rollback-budget"),
        {"signal": "first"},
        intent_keys=(_intent_key("SIM-IF-1"),),
        epoch_id="epoch-a",
        batch_id="batch-a",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
        max_order_intents_per_run=2,
        expected_run_order_intents_used=0,
        remaining_exit_intent_reserve=0,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_budget_increment
               BEFORE UPDATE OF intent_count ON execution_run_order_budgets
               BEGIN SELECT RAISE(ABORT, 'synthetic budget failure'); END"""
        )
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_WRITE_FAILED"):
        journal.record_grid_decision(
            _decision_key(run_id="rollback-budget", close_time="2026-10-20T10:01:00Z"),
            {"signal": "second"},
            intent_keys=(_intent_key("SIM-IF-2"),),
            epoch_id="epoch-a",
            batch_id="batch-b",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
            max_order_intents_per_run=2,
            expected_run_order_intents_used=1,
            remaining_exit_intent_reserve=0,
        )
    journal.close()
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER reject_budget_increment")

    recovered = ExecutionDecisionJournal(path)
    assert recovered.run_order_count("account-a", "strategy-a", "rollback-budget") == 1
    assert recovered.grid_cursor("account-a", "strategy-a", "cohort-1") == first.cursor
    assert (
        recovered._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 1
    )
    recovered.close()
