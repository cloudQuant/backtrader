"""Focused contracts for the finite logical journal-payload budget helper."""

import sqlite3
from contextvars import copy_context

import pytest

from backtrader.stores.execution_durable_capacity import (
    DEFAULT_MAX_DURABLE_BASE_BYTES,
    DEFAULT_MAX_DURABLE_BASE_RECORDS,
    DEFAULT_MAX_DURABLE_SETTLEMENT_BYTES,
    DEFAULT_MAX_DURABLE_SETTLEMENT_RECORDS,
    DurableCapacityCharge,
    DurableCapacityError,
    DurableCapacityLimits,
    DurableCapacityUsage,
    canonical_sql_row_bytes,
    charge_durable_capacity,
    durable_capacity_transaction,
    ensure_durable_capacity_usage_schema,
    read_durable_capacity_usage,
    track_durable_row_change,
)


def _memory_connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    return connection


def _seed_usage(connection, limits=None):
    connection.execute("BEGIN IMMEDIATE")
    ensure_durable_capacity_usage_schema(connection.cursor())
    if limits is not None:
        charge_durable_capacity(
            connection.cursor(),
            limits,
            DurableCapacityCharge(
                base_records=0,
                base_bytes=0,
                settlement_records=0,
                settlement_bytes=0,
            ),
        )
    connection.commit()


def test_limits_have_independent_finite_defaults_and_reject_non_integer_values():
    limits = DurableCapacityLimits()
    assert limits.max_durable_base_records == DEFAULT_MAX_DURABLE_BASE_RECORDS == 500_000
    assert limits.max_durable_base_bytes == DEFAULT_MAX_DURABLE_BASE_BYTES == 1_073_741_824
    assert (
        limits.max_durable_settlement_records == DEFAULT_MAX_DURABLE_SETTLEMENT_RECORDS == 100_000
    )
    assert (
        limits.max_durable_settlement_bytes == DEFAULT_MAX_DURABLE_SETTLEMENT_BYTES == 1_073_741_824
    )

    for field in (
        "max_durable_base_records",
        "max_durable_base_bytes",
        "max_durable_settlement_records",
        "max_durable_settlement_bytes",
    ):
        for value in (True, 0, -1, 1.5, 9_223_372_036_854_775_808):
            with pytest.raises(DurableCapacityError) as error:
                DurableCapacityLimits(**{field: value})
            assert error.value.code == "INVALID_DURABLE_CAPACITY_LIMITS"


def test_usage_schema_is_idempotent_and_contains_only_fixed_classes():
    connection = _memory_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.cursor()
        ensure_durable_capacity_usage_schema(cursor)
        ensure_durable_capacity_usage_schema(cursor)
        assert read_durable_capacity_usage(cursor) == DurableCapacityUsage(0, 0, 0, 0)
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO execution_durable_capacity_usage VALUES('OTHER',0,0)")
    finally:
        connection.close()


@pytest.mark.parametrize("damaged_state", ("empty", "missing", "duplicate"))
def test_ensure_rejects_existing_damaged_ledger_without_repair(damaged_state):
    connection = _memory_connection()
    try:
        cursor = connection.cursor()
        if damaged_state == "duplicate":
            cursor.execute(
                """CREATE TABLE execution_durable_capacity_usage (
                    capacity_class TEXT,
                    record_count INTEGER,
                    payload_bytes INTEGER
                )"""
            )
            cursor.executemany(
                "INSERT INTO execution_durable_capacity_usage VALUES(?,?,?)",
                (("BASE", 1, 2), ("BASE", 3, 4), ("SETTLEMENT", 5, 6)),
            )
            expected_code = "DURABLE_CAPACITY_USAGE_INVALID"
        else:
            connection.execute("BEGIN IMMEDIATE")
            ensure_durable_capacity_usage_schema(cursor)
            connection.commit()
            if damaged_state == "empty":
                cursor.execute("DELETE FROM execution_durable_capacity_usage")
                expected_code = "DURABLE_CAPACITY_USAGE_UNAVAILABLE"
            else:
                cursor.execute(
                    "DELETE FROM execution_durable_capacity_usage WHERE capacity_class='BASE'"
                )
                expected_code = "DURABLE_CAPACITY_USAGE_UNAVAILABLE"

        before = tuple(
            tuple(row)
            for row in cursor.execute(
                """SELECT capacity_class,record_count,payload_bytes
                   FROM execution_durable_capacity_usage ORDER BY rowid"""
            ).fetchall()
        )
        with pytest.raises(DurableCapacityError) as error:
            ensure_durable_capacity_usage_schema(cursor)
        after = tuple(
            tuple(row)
            for row in cursor.execute(
                """SELECT capacity_class,record_count,payload_bytes
                   FROM execution_durable_capacity_usage ORDER BY rowid"""
            ).fetchall()
        )
        assert error.value.code == expected_code
        assert after == before
    finally:
        connection.close()


def test_combined_charge_updates_each_class_once_and_persists_across_reopen(tmp_path):
    path = tmp_path / "durable-capacity.sqlite"
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    limits = DurableCapacityLimits(
        max_durable_base_records=4,
        max_durable_base_bytes=100,
        max_durable_settlement_records=3,
        max_durable_settlement_bytes=90,
    )
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.cursor()
        ensure_durable_capacity_usage_schema(cursor)
        charge = DurableCapacityCharge.combine(
            DurableCapacityCharge(base_records=1, base_bytes=11),
            DurableCapacityCharge(base_records=1, base_bytes=7),
            DurableCapacityCharge(settlement_records=1, settlement_bytes=13),
        )
        usage = charge_durable_capacity(cursor, limits, charge)
        assert usage.base_records == 2
        assert usage.base_bytes == 18
        assert usage.settlement_records == 1
        assert usage.settlement_bytes == 13
        connection.commit()
    finally:
        connection.close()

    reopened = sqlite3.connect(path)
    reopened.row_factory = sqlite3.Row
    try:
        assert read_durable_capacity_usage(reopened.cursor()).base_records == 2
        assert read_durable_capacity_usage(reopened.cursor()).settlement_records == 1
    finally:
        reopened.close()


@pytest.mark.parametrize(
    ("limits", "charge", "expected_code"),
    [
        (
            DurableCapacityLimits(max_durable_base_records=1),
            DurableCapacityCharge(base_records=2),
            "DURABLE_BASE_RECORDS_EXHAUSTED",
        ),
        (
            DurableCapacityLimits(max_durable_base_bytes=2),
            DurableCapacityCharge(base_bytes=3),
            "DURABLE_BASE_BYTES_EXHAUSTED",
        ),
        (
            DurableCapacityLimits(max_durable_settlement_records=1),
            DurableCapacityCharge(settlement_records=2),
            "DURABLE_SETTLEMENT_RECORDS_EXHAUSTED",
        ),
        (
            DurableCapacityLimits(max_durable_settlement_bytes=2),
            DurableCapacityCharge(settlement_bytes=3),
            "DURABLE_SETTLEMENT_BYTES_EXHAUSTED",
        ),
    ],
)
def test_each_budget_dimension_fails_closed_without_changing_usage(limits, charge, expected_code):
    connection = _memory_connection()
    try:
        _seed_usage(connection)
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.cursor()
        before = read_durable_capacity_usage(cursor)
        with pytest.raises(DurableCapacityError) as error:
            charge_durable_capacity(cursor, limits, charge)
        assert error.value.code == expected_code
        assert read_durable_capacity_usage(cursor) == before
        connection.rollback()
    finally:
        connection.close()


def test_combined_budget_rejection_does_not_partially_charge_other_class():
    connection = _memory_connection()
    limits = DurableCapacityLimits(
        max_durable_base_records=2,
        max_durable_base_bytes=100,
        max_durable_settlement_records=1,
        max_durable_settlement_bytes=100,
    )
    try:
        _seed_usage(connection)
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.cursor()
        charge_durable_capacity(
            cursor,
            limits,
            DurableCapacityCharge(settlement_records=1, settlement_bytes=5),
        )
        before = read_durable_capacity_usage(cursor)
        with pytest.raises(DurableCapacityError) as error:
            charge_durable_capacity(
                cursor,
                limits,
                DurableCapacityCharge(
                    base_records=1,
                    base_bytes=7,
                    settlement_records=1,
                    settlement_bytes=9,
                ),
            )
        assert error.value.code == "DURABLE_SETTLEMENT_RECORDS_EXHAUSTED"
        assert read_durable_capacity_usage(cursor) == before
        connection.rollback()
    finally:
        connection.close()


def test_charge_requires_an_active_transaction():
    connection = _memory_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        ensure_durable_capacity_usage_schema(connection.cursor())
        connection.commit()
        with pytest.raises(DurableCapacityError) as error:
            charge_durable_capacity(
                connection.cursor(),
                DurableCapacityLimits(),
                DurableCapacityCharge(base_records=1),
            )
        assert error.value.code == "DURABLE_CAPACITY_TRANSACTION_REQUIRED"
    finally:
        connection.close()


def test_settlement_charge_is_allowed_when_legacy_base_usage_exceeds_its_limit():
    connection = _memory_connection()
    limits = DurableCapacityLimits(
        max_durable_base_records=1,
        max_durable_base_bytes=100,
        max_durable_settlement_records=2,
        max_durable_settlement_bytes=100,
    )
    try:
        _seed_usage(connection)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """UPDATE execution_durable_capacity_usage SET record_count=2,payload_bytes=10
               WHERE capacity_class='BASE'"""
        )
        cursor = connection.cursor()
        usage = charge_durable_capacity(
            cursor,
            limits,
            DurableCapacityCharge(settlement_records=1, settlement_bytes=7),
        )
        assert usage.base_records == 2
        assert usage.base_bytes == 10
        assert usage.settlement_records == 1
        assert usage.settlement_bytes == 7

        with pytest.raises(DurableCapacityError) as error:
            charge_durable_capacity(
                cursor, limits, DurableCapacityCharge(base_records=1, base_bytes=1)
            )
        assert error.value.code == "DURABLE_BASE_RECORDS_EXHAUSTED"
        assert read_durable_capacity_usage(cursor) == usage
        connection.rollback()
    finally:
        connection.close()


def test_row_change_counts_insert_positive_growth_but_never_refunds_or_recharges_replay():
    original = {"amount": "1.00", "id": "fill-1"}
    larger = {"amount": "100000.00", "id": "fill-1"}
    insert = DurableCapacityCharge.for_row_change("SETTLEMENT", None, original)
    replay = DurableCapacityCharge.for_row_change("SETTLEMENT", original, original)
    growth = DurableCapacityCharge.for_row_change("SETTLEMENT", original, larger)
    shrink = DurableCapacityCharge.for_row_change("SETTLEMENT", larger, original)
    delete = DurableCapacityCharge.for_row_change("SETTLEMENT", original, None)

    assert insert.settlement_records == 1
    assert insert.settlement_bytes == len(canonical_sql_row_bytes(original))
    assert replay == DurableCapacityCharge()
    assert growth.settlement_records == 0
    assert growth.settlement_bytes > 0
    assert shrink == DurableCapacityCharge()
    assert delete == DurableCapacityCharge()


def test_row_serializer_is_stable_typed_and_rejects_non_finite_or_unknown_values():
    left = {"z": 1, "a": "x"}
    right = {"a": "x", "z": 1}
    assert canonical_sql_row_bytes(left) == canonical_sql_row_bytes(right)
    assert canonical_sql_row_bytes({"value": 1}) != canonical_sql_row_bytes({"value": "1"})
    assert canonical_sql_row_bytes({"value": 1}) != canonical_sql_row_bytes({"value": 1.0})
    assert canonical_sql_row_bytes({"value": 1.0}) != canonical_sql_row_bytes({"value": -0.0})

    for invalid in ({"value": float("nan")}, {"value": float("inf")}, {"value": object()}):
        with pytest.raises(DurableCapacityError) as error:
            canonical_sql_row_bytes(invalid)
        assert error.value.code == "DURABLE_ROW_VALUE_INVALID"


def test_row_serializer_accepts_sqlite_blob_and_rejects_duplicate_column_names():
    connection = _memory_connection()
    try:
        row = connection.execute("SELECT X'00FF' AS payload, 4 AS count").fetchone()
        encoded = canonical_sql_row_bytes(row)
        assert b"00ff" in encoded
        duplicate = connection.execute("SELECT 1 AS value, 2 AS value").fetchone()
        with pytest.raises(DurableCapacityError) as error:
            canonical_sql_row_bytes(duplicate)
        assert error.value.code == "DURABLE_ROW_VALUE_INVALID"
    finally:
        connection.close()


def test_two_connections_serialize_capacity_updates_and_prevent_overspend(tmp_path):
    path = tmp_path / "durable-capacity-lock.sqlite"
    first = sqlite3.connect(path, timeout=0)
    second = sqlite3.connect(path, timeout=0)
    first.row_factory = sqlite3.Row
    second.row_factory = sqlite3.Row
    limits = DurableCapacityLimits(max_durable_base_records=1)
    try:
        first.execute("BEGIN IMMEDIATE")
        ensure_durable_capacity_usage_schema(first.cursor())
        first.commit()

        first.execute("BEGIN IMMEDIATE")
        charge_durable_capacity(first.cursor(), limits, DurableCapacityCharge(base_records=1))
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            second.execute("BEGIN IMMEDIATE")
        first.commit()

        second.execute("BEGIN IMMEDIATE")
        with pytest.raises(DurableCapacityError) as error:
            charge_durable_capacity(second.cursor(), limits, DurableCapacityCharge(base_records=1))
        assert error.value.code == "DURABLE_BASE_RECORDS_EXHAUSTED"
        second.rollback()
    finally:
        first.close()
        second.close()


def test_copied_context_cannot_append_after_capacity_transaction_exits():
    connection = _memory_connection()
    limits = DurableCapacityLimits()
    connection.execute(
        "CREATE TABLE execution_decision_callbacks (receipt_id TEXT PRIMARY KEY, payload TEXT)"
    )
    connection.execute("BEGIN IMMEDIATE")
    cursor = connection.cursor()
    ensure_durable_capacity_usage_schema(cursor)
    try:
        with durable_capacity_transaction(cursor, limits):
            stale_context = copy_context()
            with track_durable_row_change(
                cursor, "execution_decision_callbacks", ("receipt-1",), "BASE"
            ):
                cursor.execute(
                    "INSERT INTO execution_decision_callbacks VALUES(?,?)",
                    ("receipt-1", "recorded while active"),
                )
        connection.commit()

        charged = read_durable_capacity_usage(cursor)
        assert charged.base_records == 1

        connection.execute("BEGIN IMMEDIATE")

        def stale_insert():
            with track_durable_row_change(
                cursor, "execution_decision_callbacks", ("receipt-2",), "BASE"
            ):
                cursor.execute(
                    "INSERT INTO execution_decision_callbacks VALUES(?,?)",
                    ("receipt-2", "must not commit"),
                )

        with pytest.raises(DurableCapacityError) as error:
            stale_context.run(stale_insert)
        assert error.value.code == "DURABLE_CAPACITY_TRANSACTION_REQUIRED"
        assert (
            connection.execute(
                "SELECT 1 FROM execution_decision_callbacks WHERE receipt_id='receipt-2'"
            ).fetchone()
            is None
        )
        assert read_durable_capacity_usage(cursor) == charged
        connection.rollback()

        def fresh_transaction():
            connection.execute("BEGIN IMMEDIATE")
            with durable_capacity_transaction(cursor, limits), track_durable_row_change(
                cursor, "execution_decision_callbacks", ("receipt-2",), "BASE"
            ):
                cursor.execute(
                    "INSERT INTO execution_decision_callbacks VALUES(?,?)",
                    ("receipt-2", "new active transaction"),
                )
            connection.commit()

        stale_context.run(fresh_transaction)
        usage_after_fresh_transaction = read_durable_capacity_usage(cursor)
        assert usage_after_fresh_transaction.base_records == 2
        assert (
            connection.execute(
                "SELECT 1 FROM execution_decision_callbacks WHERE receipt_id='receipt-2'"
            ).fetchone()
            is not None
        )
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()


def test_missing_usage_class_fails_closed():
    connection = _memory_connection()
    try:
        _seed_usage(connection)
        connection.execute(
            "DELETE FROM execution_durable_capacity_usage WHERE capacity_class='BASE'"
        )
        with pytest.raises(DurableCapacityError) as error:
            read_durable_capacity_usage(connection.cursor())
        assert error.value.code == "DURABLE_CAPACITY_USAGE_UNAVAILABLE"
    finally:
        connection.close()
