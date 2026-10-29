# -*- coding: utf-8 -*-
"""Helpers for modeling historical execution-journal schemas in tests.

Many journal tests take a *current* database and peel back the objects added
by later migrations so that a genuine upgrade path can be exercised. A real
historical database cannot already contain an object introduced by a newer
migration, so every downgrade helper must remove those objects first.

The v25 fee-pair amount lifecycle projection is a special case: its triggers
reference the v24 ``execution_fee_pair_amount_reservations`` table and the v17
workflow tables. Dropping a referenced table while the newer triggers still
exist makes SQLite raise ``no such table``, so the v25 triggers must be
removed before any older table is rebuilt or dropped.
"""

from __future__ import annotations

import sqlite3

V25_FEE_PAIR_AMOUNT_TABLES = (
    "execution_fee_pair_amount_active_holds",
    "execution_fee_pair_amount_lifecycle_events",
    "execution_fee_pair_amount_open_reservations",
)

V25_FEE_PAIR_AMOUNT_TRIGGERS = (
    "execution_fee_pair_amount_open_reservation_no_update",
    "execution_fee_pair_amount_open_reservation_no_delete",
    "execution_fee_pair_amount_open_reservation_exclusive",
    "execution_fee_pair_amount_reservation_exclusive",
    "execution_fee_pair_amount_lifecycle_event_no_update",
    "execution_fee_pair_amount_lifecycle_event_no_delete",
    "execution_fee_pair_amount_lifecycle_event_insert",
    "execution_fee_pair_amount_active_hold_no_update",
    "execution_fee_pair_amount_active_hold_insert",
    "execution_fee_pair_amount_active_hold_delete",
)

# Tables introduced by each schema version, newest first. Keep this in sync
# with the migration constants in ``backtrader.stores.execution_decision_journal``.
_VERSIONED_FEE_PAIR_TABLES = (
    (25, V25_FEE_PAIR_AMOUNT_TABLES),
    (24, ("execution_fee_pair_amount_reservations",)),
    (
        23,
        (
            "execution_fee_pair_legacy_unresolved_v23",
            "execution_fee_pair_grid_single_row_tape_intents",
        ),
    ),
    (
        22,
        (
            "execution_registered_sim_cancel_dispatch_tombstones",
            "execution_registered_sim_cancel_dispatch_claims",
        ),
    ),
    (21, ("execution_known_ctp_order_sysid_bindings",)),
    (19, ("execution_fee_pair_workflow_grid_settlements",)),
    (
        17,
        (
            "execution_fee_pair_workflow_decision_reservations",
            "execution_fee_pair_workflow_durable_reservations",
            "execution_fee_pair_workflow_events",
            "execution_fee_pair_workflows",
        ),
    ),
    (
        16,
        (
            "execution_fee_pair_candidate_capacity_reservations",
            "execution_fee_pair_candidate_events",
            "execution_fee_pair_candidates",
        ),
    ),
    (
        15,
        (
            "execution_fee_pair_scope_events",
            "execution_fee_pair_required_scopes",
        ),
    ),
)


def _existing_tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def drop_v25_fee_pair_amount_lifecycle_objects(connection: sqlite3.Connection) -> None:
    """Remove the v25 amount-hold projection from a historical-schema fixture.

    The fixtures are built by downgrading a current journal, so every object a
    later migration would create must be removed first. Otherwise the v25
    migration correctly refuses what looks like a partially migrated schema.
    """

    existing = _existing_tables(connection)
    for table in V25_FEE_PAIR_AMOUNT_TABLES:
        if table in existing and connection.execute(
            "SELECT COUNT(*) FROM {}".format(table)
        ).fetchone()[0]:
            raise AssertionError(
                "cannot downgrade a journal with v25 amount lifecycle rows"
            )
    # Drop every trigger before any referenced table (v24 amount reservations,
    # v17 workflows) is removed or rebuilt by the caller.
    for trigger in V25_FEE_PAIR_AMOUNT_TRIGGERS:
        connection.execute("DROP TRIGGER IF EXISTS {}".format(trigger))
    for table in V25_FEE_PAIR_AMOUNT_TABLES:
        connection.execute("DROP TABLE IF EXISTS {}".format(table))


def drop_empty_fee_pair_tables_from_version(
    connection: sqlite3.Connection, first_version: int
) -> None:
    """Drop only empty fee-pair tables added at or after ``first_version``."""

    tables = tuple(
        table
        for version, names in _VERSIONED_FEE_PAIR_TABLES
        if version >= first_version
        for table in names
    )
    existing = _existing_tables(connection)
    present = tuple(name for name in tables if name in existing)
    for name in present:
        if not name.isidentifier():
            raise AssertionError("unexpected schema table name")
        count = connection.execute('SELECT COUNT(*) FROM "{}"'.format(name)).fetchone()[0]
        if type(count) is not int or count != 0:
            raise AssertionError("cannot downgrade nonempty schema table: {}".format(name))
    if first_version <= 25:
        # The v25 triggers reference the v24 table, so remove them before the
        # loop below drops that table and trips SQLite's schema validation.
        for trigger in V25_FEE_PAIR_AMOUNT_TRIGGERS:
            connection.execute("DROP TRIGGER IF EXISTS {}".format(trigger))
    for name in present:
        connection.execute('DROP TABLE "{}"'.format(name))
