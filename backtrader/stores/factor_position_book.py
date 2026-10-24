"""Durable, journal-backed position attribution for factor strategies.

The selected route remains authoritative for Broker and provider position
facts.  This module records only fills that are already present in the
execution journal's immutable callback receipts, then projects those fills
back against the caller's Broker/CTP snapshot.  It deliberately has no
connection of its own: schema changes and fill projection use the journal's
SQLite cursor so a callback receipt and its position update can commit in one
transaction.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from types import MappingProxyType
from typing import Any, Mapping, Optional, Sequence, Tuple


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")
_DECIMAL_TEXT = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_DECIMAL_DIVISION_PRECISION = 256
_MAX_DECIMAL_DIGITS = 128
_MAX_DECIMAL_EXPONENT = 128
_MAX_POSITION_ACCUMULATOR_DIGITS = 1024
_MAX_POSITION_ACCUMULATOR_EXPONENT = 512
_POSITION_BOOK_SCHEMA_VERSION = 5
_UNKNOWN_EXCHANGE_KEY = ""


class FactorPositionBookError(RuntimeError):
    """A durable factor-position projection failed closed."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class FactorPositionApplyResult:
    """Result of projecting one immutable callback receipt."""

    status: str
    receipt_id: str
    execution_id: Optional[str] = None
    intent_id: Optional[str] = None
    blocker_code: Optional[str] = None


@dataclass(frozen=True)
class FactorPositionAttributionSnapshot:
    """Position-book attribution reconciled with the actual route snapshot."""

    status: str
    blocker_code: Optional[str]
    account_scope: str
    strategy_scope: str
    instrument: str
    exchange: str
    snapshot_id: str
    available_at: datetime
    signed_quantity: Optional[Decimal]
    attributed_signed_quantity: Optional[Decimal] = None
    owner_strategy_scope: Optional[str] = None
    owner_intent_id: Optional[str] = None
    position_side: Optional[str] = None
    average_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    held_eligible_bars: Optional[int] = None
    risk_policy_id: Optional[str] = None
    risk_policy: Optional[Mapping[str, Any]] = None
    opening_fee_total: Optional[Decimal] = None
    opening_fees_known: bool = False


def ensure_factor_position_book_schema(cursor: sqlite3.Cursor) -> None:
    """Create or migrate position tables on the execution journal cursor.

    Immutable fill/grid/issue evidence stays append-only.  The small mutable
    tables are the materialized current projection read by Strategy snapshots;
    their updates share the journal transaction with callbacks and decisions.
    """

    if not isinstance(cursor, sqlite3.Cursor):
        raise FactorPositionBookError("JOURNAL_CURSOR_REQUIRED")
    connection = cursor.connection
    owns_transaction = not connection.in_transaction
    try:
        if owns_transaction:
            cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS factor_position_book_meta (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                version INTEGER NOT NULL
            )"""
        )
        meta = cursor.execute(
            "SELECT version FROM factor_position_book_meta WHERE singleton=1"
        ).fetchone()
        if meta is not None and int(meta[0]) >= _POSITION_BOOK_SCHEMA_VERSION:
            if owns_transaction:
                connection.commit()
            return

        _create_position_history_schema(cursor)
        _migrate_nullable_fill_fields(cursor)
        _ensure_grid_time_index(cursor)
        _create_position_projection_schema(cursor)
        _create_position_history_guards(cursor)
        if meta is None:
            cursor.execute("INSERT INTO factor_position_book_meta(singleton, version) VALUES(1, 0)")
            meta_version = 0
        else:
            meta_version = int(meta[0])
        if meta_version < _POSITION_BOOK_SCHEMA_VERSION:
            _migrate_open_intent_fill_totals(cursor)
            if 0 < meta_version < _POSITION_BOOK_SCHEMA_VERSION:
                _invalidate_legacy_active_risk_facts(cursor)
            _seed_legacy_projection_as_unknown(cursor)
            cursor.execute(
                "UPDATE factor_position_book_meta SET version=? WHERE singleton=1",
                (_POSITION_BOOK_SCHEMA_VERSION,),
            )
        if owns_transaction:
            connection.commit()
    except sqlite3.Error as error:
        if owns_transaction and connection.in_transaction:
            connection.rollback()
        raise FactorPositionBookError("POSITION_BOOK_SCHEMA_FAILED") from error
    except Exception:
        if owns_transaction and connection.in_transaction:
            connection.rollback()
        raise


def _create_position_history_schema(cursor: sqlite3.Cursor) -> None:
    statements = (
        """CREATE TABLE IF NOT EXISTS factor_position_grid_history (
            account_scope TEXT NOT NULL,
            strategy_scope TEXT NOT NULL,
            cohort_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL CHECK(ordinal >= 1),
            batch_id TEXT NOT NULL,
            close_time TEXT NOT NULL,
            close_time_ns INTEGER NOT NULL,
            PRIMARY KEY(account_scope, strategy_scope, cohort_id, ordinal),
            UNIQUE(account_scope, strategy_scope, cohort_id, close_time)
        )""",
        """CREATE TABLE IF NOT EXISTS factor_position_openings (
            intent_id TEXT PRIMARY KEY REFERENCES execution_decision_intents(intent_id),
            account_scope TEXT NOT NULL,
            strategy_scope TEXT NOT NULL,
            instrument TEXT NOT NULL,
            exchange TEXT NOT NULL,
            position_side TEXT NOT NULL CHECK(position_side IN ('LONG','SHORT')),
            stop_price TEXT,
            risk_policy_id TEXT,
            risk_policy_json TEXT,
            cohort_id TEXT,
            batch_id TEXT,
            close_time TEXT,
            decision_grid_ordinal INTEGER CHECK(
                decision_grid_ordinal IS NULL OR decision_grid_ordinal >= 1
            ),
            created_at_ns INTEGER NOT NULL
        )""",
        _fill_table_ddl(),
        """CREATE TABLE IF NOT EXISTS factor_position_evidence_issues (
            receipt_id TEXT PRIMARY KEY REFERENCES execution_decision_callbacks(receipt_id),
            intent_id TEXT NOT NULL REFERENCES execution_decision_intents(intent_id),
            account_scope TEXT NOT NULL,
            instrument TEXT NOT NULL,
            exchange TEXT,
            blocker_code TEXT NOT NULL,
            evidence_sha256 TEXT NOT NULL,
            created_at_ns INTEGER NOT NULL
        )""",
    )
    # Do not use executescript: it commits an active journal transaction.
    for statement in statements:
        cursor.execute(statement)


def _fill_table_ddl(table_name: str = "factor_position_fills") -> str:
    if table_name not in ("factor_position_fills", "factor_position_fills_legacy"):
        raise FactorPositionBookError("INVALID_POSITION_FILL_TABLE")
    return """CREATE TABLE IF NOT EXISTS {table} (
        account_scope TEXT NOT NULL,
        instrument TEXT NOT NULL,
        exchange TEXT NOT NULL,
        execution_id TEXT NOT NULL,
        receipt_id TEXT NOT NULL REFERENCES execution_decision_callbacks(receipt_id),
        intent_id TEXT NOT NULL REFERENCES execution_decision_intents(intent_id),
        strategy_scope TEXT NOT NULL,
        position_effect TEXT NOT NULL CHECK(position_effect IN ('OPEN','CLOSE')),
        order_side TEXT NOT NULL CHECK(order_side IN ('BUY','SELL')),
        owner_intent_id TEXT,
        quantity TEXT NOT NULL,
        price TEXT NOT NULL,
        fee TEXT,
        filled_at_ns INTEGER CHECK(filled_at_ns IS NULL OR filled_at_ns > 0),
        payload_sha256 TEXT NOT NULL,
        PRIMARY KEY(account_scope, instrument, exchange, execution_id),
        UNIQUE(receipt_id)
    )""".format(
        table=table_name
    )


def _migrate_nullable_fill_fields(cursor: sqlite3.Cursor) -> None:
    columns = {
        row["name"]: row
        for row in cursor.execute("PRAGMA table_info(factor_position_fills)").fetchall()
    }
    if not columns:
        cursor.execute(_fill_table_ddl())
        return
    if not bool(columns["fee"]["notnull"]) and not bool(columns["filled_at_ns"]["notnull"]):
        return
    cursor.execute("DROP TRIGGER IF EXISTS factor_position_fill_no_update")
    cursor.execute("DROP TRIGGER IF EXISTS factor_position_fill_no_delete")
    cursor.execute("DROP INDEX IF EXISTS factor_position_fills_by_intent")
    cursor.execute("DROP INDEX IF EXISTS factor_position_fills_by_owner")
    cursor.execute("ALTER TABLE factor_position_fills RENAME TO factor_position_fills_legacy")
    cursor.execute(_fill_table_ddl())
    cursor.execute(
        """INSERT INTO factor_position_fills
           (account_scope,instrument,exchange,execution_id,receipt_id,intent_id,
            strategy_scope,position_effect,order_side,owner_intent_id,quantity,price,
            fee,filled_at_ns,payload_sha256)
           SELECT account_scope,instrument,exchange,execution_id,receipt_id,intent_id,
                  strategy_scope,position_effect,order_side,owner_intent_id,quantity,price,
                  fee,filled_at_ns,payload_sha256 FROM factor_position_fills_legacy"""
    )
    cursor.execute("DROP TABLE factor_position_fills_legacy")


def _ensure_grid_time_index(cursor: sqlite3.Cursor) -> None:
    columns = {
        row["name"] for row in cursor.execute("PRAGMA table_info(factor_position_grid_history)")
    }
    if "close_time_ns" not in columns:
        cursor.execute("ALTER TABLE factor_position_grid_history ADD COLUMN close_time_ns INTEGER")
    read_cursor = cursor.connection.cursor()
    rows = read_cursor.execute(
        "SELECT rowid, close_time FROM factor_position_grid_history WHERE close_time_ns IS NULL"
    )
    for row in rows:
        try:
            close_time_ns = _close_time_to_ns(row["close_time"])
        except (TypeError, ValueError, OverflowError):
            continue
        cursor.execute(
            "UPDATE factor_position_grid_history SET close_time_ns=? WHERE rowid=?",
            (close_time_ns, row["rowid"]),
        )
    read_cursor.close()
    cursor.execute(
        """CREATE INDEX IF NOT EXISTS factor_position_grid_by_time
           ON factor_position_grid_history
             (account_scope,strategy_scope,cohort_id,close_time_ns,ordinal)"""
    )
    cursor.execute(
        """CREATE INDEX IF NOT EXISTS factor_position_openings_by_position
           ON factor_position_openings(account_scope,instrument,exchange,intent_id)"""
    )
    cursor.execute(
        """CREATE INDEX IF NOT EXISTS factor_position_issues_by_created
           ON factor_position_evidence_issues
             (account_scope,instrument,exchange,created_at_ns,receipt_id)"""
    )
    cursor.execute(
        """CREATE INDEX IF NOT EXISTS factor_position_intents_by_owner
           ON execution_decision_intents(owner_intent_id,state)"""
    )
    cursor.execute(
        """CREATE INDEX IF NOT EXISTS factor_position_callbacks_by_time
           ON execution_decision_callbacks(receipt_id,created_at_ns)"""
    )


def _create_position_projection_schema(cursor: sqlite3.Cursor) -> None:
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS factor_position_current (
            account_scope TEXT NOT NULL,
            instrument TEXT NOT NULL,
            exchange TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('FLAT','ACTIVE','UNKNOWN')),
            blocker_code TEXT,
            epoch INTEGER NOT NULL DEFAULT 0 CHECK(epoch >= 0),
            owner_intent_id TEXT,
            strategy_scope TEXT,
            cohort_id TEXT,
            position_side TEXT CHECK(position_side IN ('LONG','SHORT') OR position_side IS NULL),
            open_quantity TEXT NOT NULL DEFAULT '0',
            close_quantity TEXT NOT NULL DEFAULT '0',
            open_notional TEXT NOT NULL DEFAULT '0',
            opening_fee_total TEXT NOT NULL DEFAULT '0',
            opening_fee_unknown_count INTEGER NOT NULL DEFAULT 0
                CHECK(opening_fee_unknown_count >= 0),
            first_fill_at_ns INTEGER,
            first_fill_grid_ordinal INTEGER,
            fill_time_complete INTEGER NOT NULL DEFAULT 1 CHECK(fill_time_complete IN (0,1)),
            fill_time_unknown_count INTEGER NOT NULL DEFAULT 0
                CHECK(fill_time_unknown_count >= 0),
            last_callback_at_ns INTEGER,
            flat_checkpoint_ns INTEGER,
            flat_reconciliation_id TEXT,
            updated_at_ns INTEGER NOT NULL,
            PRIMARY KEY(account_scope,instrument,exchange)
        )"""
    )
    cursor.execute(
        """CREATE INDEX IF NOT EXISTS factor_position_current_by_owner
           ON factor_position_current(owner_intent_id,state)"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS factor_position_active_issues (
            account_scope TEXT NOT NULL,
            instrument TEXT NOT NULL,
            exchange_key TEXT NOT NULL,
            receipt_id TEXT NOT NULL,
            blocker_code TEXT NOT NULL,
            created_at_ns INTEGER NOT NULL,
            PRIMARY KEY(account_scope,instrument,exchange_key)
        )"""
    )
    columns = {row["name"] for row in cursor.execute("PRAGMA table_info(factor_position_current)")}
    if "opening_fee_unknown_count" not in columns:
        cursor.execute(
            """ALTER TABLE factor_position_current ADD COLUMN opening_fee_unknown_count
               INTEGER NOT NULL DEFAULT 0 CHECK(opening_fee_unknown_count >= 0)"""
        )
    if "fill_time_unknown_count" not in columns:
        cursor.execute(
            """ALTER TABLE factor_position_current ADD COLUMN fill_time_unknown_count
               INTEGER NOT NULL DEFAULT 0 CHECK(fill_time_unknown_count >= 0)"""
        )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS factor_position_fill_attributes (
            account_scope TEXT NOT NULL,
            instrument TEXT NOT NULL,
            exchange TEXT NOT NULL,
            execution_id TEXT NOT NULL,
            intent_id TEXT NOT NULL,
            position_effect TEXT NOT NULL CHECK(position_effect IN ('OPEN','CLOSE')),
            position_epoch INTEGER CHECK(position_epoch IS NULL OR position_epoch >= 1),
            fee TEXT,
            filled_at_ns INTEGER CHECK(filled_at_ns IS NULL OR filled_at_ns > 0),
            last_receipt_id TEXT NOT NULL REFERENCES execution_decision_callbacks(receipt_id),
            payload_sha256 TEXT NOT NULL,
            PRIMARY KEY(account_scope,instrument,exchange,execution_id)
        )"""
    )
    cursor.execute(
        """CREATE INDEX IF NOT EXISTS factor_position_fill_attributes_by_receipt
           ON factor_position_fill_attributes(last_receipt_id)"""
    )
    attribute_columns = {
        row["name"] for row in cursor.execute("PRAGMA table_info(factor_position_fill_attributes)")
    }
    if "intent_id" not in attribute_columns:
        cursor.execute("ALTER TABLE factor_position_fill_attributes ADD COLUMN intent_id TEXT")
    if "position_effect" not in attribute_columns:
        cursor.execute(
            "ALTER TABLE factor_position_fill_attributes ADD COLUMN position_effect TEXT"
        )
    if "position_epoch" not in attribute_columns:
        # Existing evidence cannot be assigned to a current projection epoch
        # retrospectively. NULL deliberately disables cross-epoch enrichment.
        cursor.execute(
            "ALTER TABLE factor_position_fill_attributes ADD COLUMN position_epoch INTEGER"
        )
    cursor.execute("DROP INDEX IF EXISTS factor_position_fill_attributes_by_intent_time")
    cursor.execute(
        """CREATE INDEX IF NOT EXISTS factor_position_fill_attributes_by_intent_time
           ON factor_position_fill_attributes
             (account_scope,instrument,exchange,intent_id,position_effect,
              position_epoch,filled_at_ns,execution_id)"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS factor_position_open_intent_totals (
            intent_id TEXT PRIMARY KEY REFERENCES execution_decision_intents(intent_id),
            account_scope TEXT NOT NULL,
            strategy_scope TEXT NOT NULL,
            instrument TEXT NOT NULL,
            exchange TEXT NOT NULL,
            filled_quantity TEXT NOT NULL,
            quantity_complete INTEGER NOT NULL CHECK(quantity_complete IN (0,1)),
            blocker_code TEXT,
            updated_at_ns INTEGER NOT NULL
        )"""
    )


def _migrate_open_intent_fill_totals(cursor: sqlite3.Cursor) -> None:
    """Build bounded per-intent OPEN totals from append-only source fills.

    This one-time schema migration streams history in intent order and keeps
    only one intent accumulator in memory. The hot snapshot path reads the
    materialized totals/current projection and never scans fill history.
    """

    connection = cursor.connection
    read_cursor = connection.cursor()
    intent_cursor = connection.cursor()
    rows = read_cursor.execute(
        """SELECT f.intent_id,f.account_scope,f.strategy_scope,f.instrument,f.exchange,
                  f.quantity,c.created_at_ns
           FROM factor_position_fills AS f
           JOIN execution_decision_callbacks AS c ON c.receipt_id=f.receipt_id
           WHERE f.position_effect='OPEN'
           ORDER BY f.intent_id,f.execution_id"""
    )
    current_id = None
    binding = None
    total = Decimal(0)
    complete = True
    blocker = None
    updated_at_ns = 0

    def flush() -> None:
        if current_id is None or binding is None:
            return
        account_scope, strategy_scope, instrument, exchange = binding
        intent_row = intent_cursor.execute(
            "SELECT economic_payload_json FROM execution_decision_intents WHERE intent_id=?",
            (current_id,),
        ).fetchone()
        if intent_row is None:
            final_complete = False
            final_blocker = "OPEN_INTENT_FILL_TOTAL_UNAVAILABLE"
        else:
            try:
                economics = json.loads(intent_row["economic_payload_json"])
            except (TypeError, ValueError):
                economics = None
            requested = (
                _parse_decimal(economics.get("quantity"), positive=True)
                if isinstance(economics, Mapping)
                else None
            )
            final_complete = complete
            final_blocker = blocker
            if not final_complete and final_blocker is None:
                final_blocker = "OPEN_INTENT_FILL_TOTAL_UNAVAILABLE"
            elif final_complete and requested is None:
                final_blocker = "OPEN_INTENT_QUANTITY_UNAVAILABLE"
            elif final_complete and total > requested:
                final_blocker = "OPEN_INTENT_QUANTITY_EXCEEDED"
        cursor.execute(
            """INSERT INTO factor_position_open_intent_totals
               (intent_id,account_scope,strategy_scope,instrument,exchange,filled_quantity,
                quantity_complete,blocker_code,updated_at_ns)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(intent_id) DO UPDATE SET
                 account_scope=excluded.account_scope,strategy_scope=excluded.strategy_scope,
                 instrument=excluded.instrument,exchange=excluded.exchange,
                 filled_quantity=excluded.filled_quantity,
                 quantity_complete=excluded.quantity_complete,
                 blocker_code=excluded.blocker_code,updated_at_ns=excluded.updated_at_ns""",
            (
                current_id,
                account_scope,
                strategy_scope,
                instrument,
                exchange,
                _serialize_decimal(total),
                int(final_complete),
                final_blocker,
                updated_at_ns,
            ),
        )
        if final_blocker is not None:
            position = cursor.execute(
                """SELECT state FROM factor_position_current
                   WHERE account_scope=? AND instrument=? AND exchange=?
                     AND owner_intent_id=?""",
                (account_scope, instrument, exchange, current_id),
            ).fetchone()
            if position is not None and position["state"] == "ACTIVE":
                cursor.execute(
                    """UPDATE factor_position_current
                       SET state='UNKNOWN',blocker_code=?,updated_at_ns=?
                       WHERE account_scope=? AND instrument=? AND exchange=?
                         AND owner_intent_id=? AND state='ACTIVE'""",
                    (
                        final_blocker,
                        updated_at_ns,
                        account_scope,
                        instrument,
                        exchange,
                        current_id,
                    ),
                )

    for row in rows:
        row_binding = (
            row["account_scope"],
            row["strategy_scope"],
            row["instrument"],
            row["exchange"],
        )
        if current_id != row["intent_id"]:
            flush()
            current_id = row["intent_id"]
            binding = row_binding
            total = Decimal(0)
            complete = True
            blocker = None
            updated_at_ns = 0
        elif binding != row_binding:
            complete = False
            blocker = "OPEN_INTENT_FILL_TOTAL_CONFLICT"
        parsed = _parse_decimal(row["quantity"], positive=True)
        if parsed is None:
            complete = False
            blocker = blocker or "OPEN_INTENT_FILL_TOTAL_UNAVAILABLE"
        elif complete:
            try:
                total = _decimal_add(total, parsed)
            except FactorPositionBookError:
                complete = False
                blocker = "POSITION_DECIMAL_ACCUMULATOR_LIMIT"
        updated_at_ns = max(updated_at_ns, int(row["created_at_ns"]))
    flush()
    read_cursor.close()
    intent_cursor.close()


def _invalidate_legacy_active_risk_facts(cursor: sqlite3.Cursor) -> None:
    """Avoid asserting fee or held-age facts derived before epoch binding.

    Existing materialized owners and quantities remain available for their
    original authorized risk-reduction path. Fee completeness and the age
    anchor become unavailable until a fresh, provably bound epoch is opened.
    """

    cursor.execute(
        """UPDATE factor_position_current
           SET opening_fee_unknown_count=MAX(opening_fee_unknown_count,1),
               fill_time_complete=0,
               fill_time_unknown_count=MAX(fill_time_unknown_count,1),
               first_fill_at_ns=NULL,first_fill_grid_ordinal=NULL
           WHERE owner_intent_id IS NOT NULL AND state IN ('ACTIVE','UNKNOWN')"""
    )


def _create_position_history_guards(cursor: sqlite3.Cursor) -> None:
    statements = (
        "CREATE INDEX IF NOT EXISTS factor_position_fills_by_intent ON factor_position_fills(intent_id, position_effect, filled_at_ns)",
        "CREATE INDEX IF NOT EXISTS factor_position_fills_by_owner ON factor_position_fills(owner_intent_id, position_effect, filled_at_ns)",
        "CREATE INDEX IF NOT EXISTS factor_position_issues_by_position ON factor_position_evidence_issues(account_scope, instrument, exchange)",
        """CREATE TRIGGER IF NOT EXISTS factor_position_grid_no_update
            BEFORE UPDATE ON factor_position_grid_history
            BEGIN SELECT RAISE(ABORT, 'factor position grid history is append only'); END""",
        """CREATE TRIGGER IF NOT EXISTS factor_position_grid_no_delete
            BEFORE DELETE ON factor_position_grid_history
            BEGIN SELECT RAISE(ABORT, 'factor position grid history is append only'); END""",
        """CREATE TRIGGER IF NOT EXISTS factor_position_opening_no_update
            BEFORE UPDATE ON factor_position_openings
            BEGIN SELECT RAISE(ABORT, 'factor position openings are append only'); END""",
        """CREATE TRIGGER IF NOT EXISTS factor_position_opening_no_delete
            BEFORE DELETE ON factor_position_openings
            BEGIN SELECT RAISE(ABORT, 'factor position openings are append only'); END""",
        """CREATE TRIGGER IF NOT EXISTS factor_position_fill_no_update
            BEFORE UPDATE ON factor_position_fills
            BEGIN SELECT RAISE(ABORT, 'factor position fills are append only'); END""",
        """CREATE TRIGGER IF NOT EXISTS factor_position_fill_no_delete
            BEFORE DELETE ON factor_position_fills
            BEGIN SELECT RAISE(ABORT, 'factor position fills are append only'); END""",
        """CREATE TRIGGER IF NOT EXISTS factor_position_issue_no_update
            BEFORE UPDATE ON factor_position_evidence_issues
            BEGIN SELECT RAISE(ABORT, 'factor position evidence issues are append only'); END""",
        """CREATE TRIGGER IF NOT EXISTS factor_position_issue_no_delete
            BEFORE DELETE ON factor_position_evidence_issues
            BEGIN SELECT RAISE(ABORT, 'factor position evidence issues are append only'); END""",
    )
    for statement in statements:
        cursor.execute(statement)


def _seed_legacy_projection_as_unknown(cursor: sqlite3.Cursor) -> None:
    """Do not invent ownership while upgrading histories without projections."""

    keys = cursor.execute(
        """SELECT account_scope,instrument,exchange FROM factor_position_fills
           UNION SELECT account_scope,instrument,exchange FROM factor_position_openings
           UNION SELECT account_scope,instrument,exchange FROM factor_position_evidence_issues
             WHERE exchange IS NOT NULL"""
    )
    for row in keys.fetchall():
        cursor.execute(
            """INSERT OR IGNORE INTO factor_position_current
               (account_scope,instrument,exchange,state,blocker_code,epoch,updated_at_ns)
               VALUES(?,?,?,'UNKNOWN','POSITION_PROJECTION_REQUIRES_RECONCILIATION',0,0)""",
            (row["account_scope"], row["instrument"], row["exchange"]),
        )
    issue_keys = cursor.execute(
        """SELECT account_scope,instrument,exchange FROM factor_position_evidence_issues
           GROUP BY account_scope,instrument,exchange"""
    )
    for row in issue_keys.fetchall():
        exchange_key = row["exchange"] or _UNKNOWN_EXCHANGE_KEY
        issue = cursor.execute(
            """SELECT receipt_id,blocker_code,created_at_ns
               FROM factor_position_evidence_issues
               WHERE account_scope=? AND instrument=? AND exchange IS ?
               ORDER BY created_at_ns DESC,receipt_id DESC LIMIT 1""",
            (row["account_scope"], row["instrument"], row["exchange"]),
        ).fetchone()
        if issue is None:
            continue
        cursor.execute(
            """INSERT OR IGNORE INTO factor_position_active_issues
               (account_scope,instrument,exchange_key,receipt_id,blocker_code,created_at_ns)
               VALUES(?,?,?,?,?,?)""",
            (
                row["account_scope"],
                row["instrument"],
                exchange_key,
                issue["receipt_id"],
                issue["blocker_code"],
                issue["created_at_ns"],
            ),
        )


def record_factor_position_grid(
    cursor: sqlite3.Cursor,
    *,
    account_scope: str,
    strategy_scope: str,
    cohort_id: str,
    batch_id: str,
    close_time: str,
    ordinal: int,
) -> bool:
    """Append one newly committed eligible grid in the journal transaction.

    Returns ``False`` for an exact idempotent replay and rejects any identity
    or ordinal collision.  The caller invokes this only for complete,
    LIVE_READY grids whose decision cursor was advanced in the same
    transaction.
    """

    ensure_factor_position_book_schema(cursor)
    for name, value in (
        ("account_scope", account_scope),
        ("strategy_scope", strategy_scope),
        ("cohort_id", cohort_id),
        ("batch_id", batch_id),
    ):
        _require_identifier(value, "INVALID_" + name.upper())
    _require_close_time(close_time)
    close_time_ns = _close_time_to_ns(close_time)
    if type(ordinal) is not int or ordinal < 1:
        raise FactorPositionBookError("INVALID_GRID_ORDINAL")

    by_ordinal = cursor.execute(
        """SELECT batch_id, close_time FROM factor_position_grid_history
           WHERE account_scope=? AND strategy_scope=? AND cohort_id=? AND ordinal=?""",
        (account_scope, strategy_scope, cohort_id, ordinal),
    ).fetchone()
    if by_ordinal is not None:
        if by_ordinal["batch_id"] == batch_id and by_ordinal["close_time"] == close_time:
            return False
        raise FactorPositionBookError("GRID_ORDINAL_CONFLICT")
    by_time = cursor.execute(
        """SELECT ordinal, batch_id FROM factor_position_grid_history
           WHERE account_scope=? AND strategy_scope=? AND cohort_id=? AND close_time=?""",
        (account_scope, strategy_scope, cohort_id, close_time),
    ).fetchone()
    if by_time is not None:
        raise FactorPositionBookError("GRID_CLOSE_TIME_CONFLICT")
    latest = cursor.execute(
        """SELECT MAX(ordinal) FROM factor_position_grid_history
           WHERE account_scope=? AND strategy_scope=? AND cohort_id=?""",
        (account_scope, strategy_scope, cohort_id),
    ).fetchone()[0]
    if latest is not None and ordinal != int(latest) + 1:
        raise FactorPositionBookError("GRID_ORDINAL_NOT_CONTIGUOUS")
    if latest is None and ordinal != 1:
        raise FactorPositionBookError("GRID_HISTORY_MUST_START_AT_ONE")
    cursor.execute(
        """INSERT INTO factor_position_grid_history
           (account_scope, strategy_scope, cohort_id, ordinal, batch_id, close_time,
            close_time_ns)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (account_scope, strategy_scope, cohort_id, ordinal, batch_id, close_time, close_time_ns),
    )
    return True


def record_factor_position_flat_checkpoint(
    cursor: sqlite3.Cursor, *, intent_id: str, reconciliation_id: str
) -> None:
    """Apply one stored, terminal, authoritative-flat resolution atomically.

    This helper consumes only evidence already persisted by the execution
    journal. It does not accept a caller's claim that a position is flat. The
    journal calls it inside the same transaction that inserts a resolution.
    An old resolution replay cannot erase callbacks received after its
    checkpoint, and missing-exchange issues are never cleared by an exact
    exchange observation.
    """

    ensure_factor_position_book_schema(cursor)
    _require_identifier(intent_id, "INVALID_INTENT_ID")
    _require_identifier(reconciliation_id, "INVALID_RECONCILIATION_ID")
    row = cursor.execute(
        """SELECT r.*,i.state AS intent_state,i.dispatch_state,i.intent_key_json,
                  i.economic_payload_json,i.created_at_ns AS intent_created_at_ns,
                  d.business_key_json,q.state AS reconciliation_state,
                  q.terminal_state AS reconciliation_terminal_state,
                  q.terminal_event_id AS reconciliation_terminal_event_id,
                  q.position_snapshot_id AS reconciliation_snapshot_id,
                  q.position_flat AS reconciliation_position_flat,
                  q.reconciliation_id AS joined_reconciliation_id
           FROM execution_intent_resolutions AS r
           JOIN execution_decision_intents AS i ON i.intent_id=r.intent_id
           JOIN execution_decisions AS d ON d.decision_id=i.decision_id
           JOIN execution_intent_reconciliations AS q
             ON q.reconciliation_id=r.reconciliation_id AND q.intent_id=r.intent_id
           WHERE r.intent_id=? AND r.reconciliation_id=?""",
        (intent_id, reconciliation_id),
    ).fetchone()
    if row is None:
        raise FactorPositionBookError("POSITION_FLAT_CHECKPOINT_INVALID")
    try:
        key = json.loads(row["intent_key_json"])
        business = json.loads(row["business_key_json"])
        economics = json.loads(row["economic_payload_json"])
    except (TypeError, ValueError) as error:
        raise FactorPositionBookError("POSITION_FLAT_CHECKPOINT_INVALID") from error
    if not all(isinstance(value, Mapping) for value in (key, business, economics)):
        raise FactorPositionBookError("POSITION_FLAT_CHECKPOINT_INVALID")
    account_scope = row["account_scope"]
    instrument = row["instrument"]
    exchange = economics.get("exchange")
    terminal = row["terminal_state"]
    created_at_ns = row["created_at_ns"]
    if (
        row["intent_id"] != intent_id
        or row["reconciliation_id"] != reconciliation_id
        or row["joined_reconciliation_id"] != reconciliation_id
        or row["intent_state"] != "KNOWN"
        or row["dispatch_state"] not in ("KNOWN", "UNKNOWN")
        or row["reconciliation_state"] != "KNOWN"
        or terminal not in ("FILLED", "CANCELLED", "REJECTED")
        or row["reconciliation_terminal_state"] != terminal
        or row["reconciliation_terminal_event_id"] != row["terminal_event_id"]
        or row["reconciliation_snapshot_id"] != row["position_snapshot_id"]
        or row["position_flat"] is None
        or int(row["position_flat"]) != 1
        or row["reconciliation_position_flat"] is None
        or int(row["reconciliation_position_flat"]) != 1
        or business.get("account_scope") != account_scope
        or key.get("instrument") != instrument
        or not _is_identifier(account_scope)
        or not _is_identifier(instrument)
        or not _is_identifier(exchange)
        or type(created_at_ns) is not int
        or created_at_ns <= 0
    ):
        raise FactorPositionBookError("POSITION_FLAT_CHECKPOINT_INVALID")
    current = cursor.execute(
        """SELECT * FROM factor_position_current
           WHERE account_scope=? AND instrument=? AND exchange=?""",
        (account_scope, instrument, exchange),
    ).fetchone()
    if current is not None and current["flat_reconciliation_id"] == reconciliation_id:
        if current["flat_checkpoint_ns"] != created_at_ns:
            raise FactorPositionBookError("POSITION_FLAT_CHECKPOINT_CONFLICT")
        # A replay may occur after a later callback or a new risk epoch. The
        # checkpoint is already represented, so preserve the newer projection.
        return
    if current is not None:
        if (
            current["flat_checkpoint_ns"] is not None
            and int(current["flat_checkpoint_ns"]) > created_at_ns
        ):
            return
        # A late replay of an old terminal query must not flatten newer fill
        # evidence. The newer evidence remains available for an exact query.
        if (
            current["last_callback_at_ns"] is not None
            and int(current["last_callback_at_ns"]) > created_at_ns
        ):
            return
    active_issue = cursor.execute(
        """SELECT receipt_id,blocker_code,created_at_ns
           FROM factor_position_active_issues
           WHERE account_scope=? AND instrument=? AND exchange_key=?""",
        (account_scope, instrument, exchange),
    ).fetchone()
    if active_issue is not None and int(active_issue["created_at_ns"]) < created_at_ns:
        cursor.execute(
            """DELETE FROM factor_position_active_issues
               WHERE account_scope=? AND instrument=? AND exchange_key=?""",
            (account_scope, instrument, exchange),
        )
        active_issue = None
    next_epoch = 1 if current is None else int(current["epoch"]) + 1
    state = "UNKNOWN" if active_issue is not None else "FLAT"
    blocker = active_issue["blocker_code"] if active_issue is not None else None
    cursor.execute(
        """INSERT INTO factor_position_current
           (account_scope,instrument,exchange,state,blocker_code,epoch,
            owner_intent_id,strategy_scope,cohort_id,position_side,open_quantity,
            close_quantity,open_notional,opening_fee_total,opening_fee_unknown_count,
            first_fill_at_ns,first_fill_grid_ordinal,fill_time_complete,
            fill_time_unknown_count,last_callback_at_ns,flat_checkpoint_ns,
            flat_reconciliation_id,updated_at_ns)
           VALUES(?,?,?,?,?,?,NULL,NULL,NULL,NULL,'0','0','0','0',0,NULL,NULL,1,
                  0,NULL,?,?,?)
           ON CONFLICT(account_scope,instrument,exchange) DO UPDATE SET
             state=excluded.state,blocker_code=excluded.blocker_code,
             epoch=excluded.epoch,owner_intent_id=NULL,strategy_scope=NULL,
             cohort_id=NULL,position_side=NULL,open_quantity='0',close_quantity='0',
             open_notional='0',opening_fee_total='0',opening_fee_unknown_count=0,
             first_fill_at_ns=NULL,first_fill_grid_ordinal=NULL,fill_time_complete=1,
             fill_time_unknown_count=0,
             last_callback_at_ns=NULL,flat_checkpoint_ns=excluded.flat_checkpoint_ns,
             flat_reconciliation_id=excluded.flat_reconciliation_id,
             updated_at_ns=excluded.updated_at_ns""",
        (
            account_scope,
            instrument,
            exchange,
            state,
            blocker,
            next_epoch,
            created_at_ns,
            reconciliation_id,
            created_at_ns,
        ),
    )


def validate_factor_position_close_owner(
    cursor: sqlite3.Cursor,
    *,
    account_scope: str,
    strategy_scope: str,
    instrument: str,
    exchange: str,
    owner_intent_id: str,
) -> None:
    """Require a reconciled, positively owned residual before preparing CLOSE.

    This check is intended to run in ``ExecutionDecisionJournal``'s
    ``prepare_intent`` transaction.  It validates journaled fills and the
    prior order's terminal position reconciliation; it does not trust a
    Strategy-provided quantity and does not change the pending-order owner.
    """

    ensure_factor_position_book_schema(cursor)
    for name, value in (
        ("account_scope", account_scope),
        ("strategy_scope", strategy_scope),
        ("instrument", instrument),
        ("exchange", exchange),
        ("owner_intent_id", owner_intent_id),
    ):
        _require_identifier(value, "INVALID_" + name.upper())
    owner = cursor.execute(
        """SELECT i.*, d.business_key_json
           FROM execution_decision_intents AS i
           JOIN execution_decisions AS d ON d.decision_id=i.decision_id
           WHERE i.intent_id=?""",
        (owner_intent_id,),
    ).fetchone()
    if owner is None:
        raise FactorPositionBookError("CLOSE_OWNER_NOT_FOUND")
    try:
        key = json.loads(owner["intent_key_json"])
        business = json.loads(owner["business_key_json"])
    except (TypeError, ValueError) as error:
        raise FactorPositionBookError("CLOSE_OWNER_QUANTITY_UNKNOWN") from error
    if not isinstance(key, Mapping) or not isinstance(business, Mapping):
        raise FactorPositionBookError("CLOSE_OWNER_QUANTITY_UNKNOWN")
    if (
        business.get("account_scope") != account_scope
        or business.get("strategy_scope") != strategy_scope
        or key.get("instrument") != instrument
        or key.get("action") != "SUBMIT"
        or key.get("position_effect") != "OPEN"
        or key.get("side") not in ("BUY", "SELL")
    ):
        raise FactorPositionBookError("CLOSE_OWNER_SCOPE_MISMATCH")
    opening = cursor.execute(
        """SELECT * FROM factor_position_openings WHERE intent_id=?""", (owner_intent_id,)
    ).fetchone()
    if (
        opening is None
        or opening["account_scope"] != account_scope
        or opening["strategy_scope"] != strategy_scope
        or opening["instrument"] != instrument
        or opening["exchange"] != exchange
        or opening["position_side"] != ("LONG" if key["side"] == "BUY" else "SHORT")
    ):
        raise FactorPositionBookError("CLOSE_OWNER_QUANTITY_UNKNOWN")
    resolution = cursor.execute(
        """SELECT * FROM execution_intent_resolutions
           WHERE intent_id=? AND account_scope=? AND instrument=?""",
        (owner_intent_id, account_scope, instrument),
    ).fetchone()
    if (
        owner["state"] != "KNOWN"
        or owner["dispatch_state"] != "KNOWN"
        or resolution is None
        or resolution["terminal_state"] not in ("FILLED", "CANCELLED", "REJECTED")
        or resolution["position_flat"] is None
        or int(resolution["position_flat"]) != 0
    ):
        raise FactorPositionBookError("CLOSE_OWNER_NOT_RECONCILED")
    reconciliation = cursor.execute(
        """SELECT * FROM execution_intent_reconciliations
           WHERE reconciliation_id=? AND intent_id=?""",
        (resolution["reconciliation_id"], owner_intent_id),
    ).fetchone()
    if (
        reconciliation is None
        or reconciliation["state"] != "KNOWN"
        or reconciliation["terminal_state"] != resolution["terminal_state"]
        or reconciliation["terminal_event_id"] != resolution["terminal_event_id"]
        or reconciliation["position_snapshot_id"] != resolution["position_snapshot_id"]
        or reconciliation["position_flat"] is None
        or int(reconciliation["position_flat"]) != 0
    ):
        raise FactorPositionBookError("CLOSE_OWNER_NOT_RECONCILED")

    current = cursor.execute(
        """SELECT * FROM factor_position_current
           WHERE account_scope=? AND instrument=? AND exchange=?""",
        (account_scope, instrument, exchange),
    ).fetchone()
    if current is not None and current["state"] == "FLAT":
        raise FactorPositionBookError("CLOSE_OWNER_FLAT")
    if current is None:
        raise FactorPositionBookError("CLOSE_OWNER_QUANTITY_UNKNOWN")
    overfill_reduction = (
        current["state"] == "UNKNOWN" and current["blocker_code"] == "OPEN_INTENT_QUANTITY_EXCEEDED"
    )
    if current["state"] != "ACTIVE" and not overfill_reduction:
        raise FactorPositionBookError("CLOSE_OWNER_QUANTITY_UNKNOWN")
    if current["owner_intent_id"] != owner_intent_id:
        raise FactorPositionBookError("CLOSE_OWNER_SCOPE_MISMATCH")
    if overfill_reduction:
        total = cursor.execute(
            """SELECT * FROM factor_position_open_intent_totals WHERE intent_id=?""",
            (owner_intent_id,),
        ).fetchone()
        active_issue = cursor.execute(
            """SELECT blocker_code FROM factor_position_active_issues
               WHERE account_scope=? AND instrument=? AND exchange_key IN (?,?)""",
            (account_scope, instrument, exchange, _UNKNOWN_EXCHANGE_KEY),
        ).fetchall()
        if (
            total is None
            or not bool(total["quantity_complete"])
            or total["blocker_code"] != "OPEN_INTENT_QUANTITY_EXCEEDED"
            or tuple(
                total[name]
                for name in ("account_scope", "strategy_scope", "instrument", "exchange")
            )
            != (account_scope, strategy_scope, instrument, exchange)
            or any(
                issue["blocker_code"] != "OPEN_INTENT_QUANTITY_EXCEEDED" for issue in active_issue
            )
        ):
            raise FactorPositionBookError("CLOSE_OWNER_QUANTITY_UNKNOWN")
    open_quantity = _parse_accumulator_decimal(current["open_quantity"], nonnegative=True)
    close_quantity = _parse_accumulator_decimal(current["close_quantity"], nonnegative=True)
    if (
        open_quantity is None
        or close_quantity is None
        or current["strategy_scope"] != strategy_scope
        or current["position_side"] != opening["position_side"]
    ):
        raise FactorPositionBookError("CLOSE_OWNER_QUANTITY_UNKNOWN")
    if close_quantity > open_quantity:
        raise FactorPositionBookError("CLOSE_OWNER_QUANTITY_UNKNOWN")
    if open_quantity == close_quantity:
        raise FactorPositionBookError("CLOSE_OWNER_FLAT")

    candidates = cursor.execute(
        """SELECT i.intent_id, i.state, i.intent_key_json, i.economic_payload_json,
                  d.business_key_json
           FROM execution_decision_intents AS i
           JOIN execution_decisions AS d ON d.decision_id=i.decision_id
           WHERE i.owner_intent_id=?""",
        (owner_intent_id,),
    ).fetchall()
    for candidate in candidates:
        try:
            candidate_key = json.loads(candidate["intent_key_json"])
            candidate_economics = json.loads(candidate["economic_payload_json"])
            candidate_business = json.loads(candidate["business_key_json"])
        except (TypeError, ValueError):
            raise FactorPositionBookError("CLOSE_OWNER_QUANTITY_UNKNOWN") from None
        is_same_owner_close = (
            isinstance(candidate_key, Mapping)
            and isinstance(candidate_economics, Mapping)
            and isinstance(candidate_business, Mapping)
            and candidate_key.get("position_effect") == "CLOSE"
            and candidate_economics.get("owner_intent_id") == owner_intent_id
            and candidate_business.get("account_scope") == account_scope
            and candidate_business.get("strategy_scope") == strategy_scope
            and candidate_key.get("instrument") == instrument
            and candidate_economics.get("exchange") == exchange
        )
        if not is_same_owner_close:
            continue
        if candidate["state"] != "KNOWN":
            raise FactorPositionBookError("CLOSE_OWNER_ALREADY_PENDING")
        reserved = cursor.execute(
            """SELECT owner_intent_id FROM execution_instrument_owners
               WHERE account_scope=? AND instrument=?""",
            (account_scope, instrument),
        ).fetchone()
        if reserved is not None and reserved["owner_intent_id"] == candidate["intent_id"]:
            raise FactorPositionBookError("CLOSE_OWNER_ALREADY_PENDING")


def apply_factor_execution_fill(
    cursor: sqlite3.Cursor, *, receipt_id: str
) -> FactorPositionApplyResult:
    """Project a source execution fill already persisted as a callback receipt.

    The receipt, order identity, strategy scope, instrument, side, effect and
    immutable risk economics are read from the journal tables.  Caller-supplied
    identifiers cannot assign a fill to a Strategy.  ACK/status notifications
    are retained by the journal but do not become fills.
    """

    ensure_factor_position_book_schema(cursor)
    _require_identifier(receipt_id, "INVALID_CALLBACK_RECEIPT_ID")
    receipt = cursor.execute(
        "SELECT * FROM execution_decision_callbacks WHERE receipt_id=?", (receipt_id,)
    ).fetchone()
    if receipt is None:
        raise FactorPositionBookError("CALLBACK_RECEIPT_NOT_FOUND")
    prior_issue = cursor.execute(
        """SELECT blocker_code, evidence_sha256, intent_id
           FROM factor_position_evidence_issues WHERE receipt_id=?""",
        (receipt_id,),
    ).fetchone()
    if prior_issue is not None:
        expected_digest = hashlib.sha256(
            receipt["evidence_payload_json"].encode("utf-8")
        ).hexdigest()
        if (
            prior_issue["intent_id"] != receipt["intent_id"]
            or prior_issue["evidence_sha256"] != expected_digest
        ):
            raise FactorPositionBookError("POSITION_ISSUE_CONFLICT")
        return _blocked_apply(receipt_id, receipt["intent_id"], prior_issue["blocker_code"])
    try:
        evidence = json.loads(receipt["evidence_payload_json"])
    except (TypeError, ValueError) as error:
        raise FactorPositionBookError("CALLBACK_EVIDENCE_INVALID") from error
    intent = cursor.execute(
        """SELECT i.*, d.business_key_json
           FROM execution_decision_intents AS i
           JOIN execution_decisions AS d ON d.decision_id=i.decision_id
           WHERE i.intent_id=?""",
        (receipt["intent_id"],),
    ).fetchone()
    if intent is None:
        raise FactorPositionBookError("CALLBACK_INTENT_NOT_FOUND")
    try:
        intent_key = json.loads(intent["intent_key_json"])
        business_key = json.loads(intent["business_key_json"])
        economics = json.loads(intent["economic_payload_json"])
    except (TypeError, ValueError) as error:
        raise FactorPositionBookError("JOURNAL_INTENT_INVALID") from error
    if not all(isinstance(value, Mapping) for value in (intent_key, business_key, economics)):
        raise FactorPositionBookError("JOURNAL_INTENT_INVALID")
    if not isinstance(evidence, Mapping):
        account_scope = business_key.get("account_scope")
        instrument = intent_key.get("instrument")
        if not _is_identifier(account_scope) or not _is_identifier(instrument):
            raise FactorPositionBookError("JOURNAL_INTENT_INVALID")
        exchange = economics.get("exchange")
        if not _is_identifier(exchange):
            exchange = None
        return _record_position_issue(
            cursor,
            receipt,
            account_scope=account_scope,
            instrument=instrument,
            exchange=exchange,
            blocker_code="CALLBACK_EVIDENCE_INVALID",
        )
    if evidence.get("event_type") != "execution_fill":
        return FactorPositionApplyResult("NO_FILL", receipt_id, intent_id=receipt["intent_id"])

    execution_id = evidence.get("execution_id")
    if not _is_identifier(execution_id):
        execution_id = None
    account_scope = business_key.get("account_scope")
    strategy_scope = business_key.get("strategy_scope")
    instrument = intent_key.get("instrument")
    if not _is_identifier(account_scope) or not _is_identifier(instrument):
        raise FactorPositionBookError("JOURNAL_INTENT_INVALID")
    expected_exchange = economics.get("exchange")
    evidence_exchange = evidence.get("exchange")
    bound_exchange = expected_exchange if _is_identifier(expected_exchange) else None
    if bound_exchange is None and _is_identifier(evidence_exchange):
        bound_exchange = evidence_exchange
    if not _is_identifier(strategy_scope):
        return _record_position_issue(
            cursor,
            receipt,
            account_scope=account_scope,
            instrument=instrument,
            exchange=bound_exchange,
            blocker_code="INTENT_BINDING_INVALID",
            execution_id=execution_id,
        )
    if (
        intent_key.get("action") != "SUBMIT"
        or intent_key.get("position_effect") not in ("OPEN", "CLOSE")
        or intent_key.get("side") not in ("BUY", "SELL")
        or not _is_identifier(business_key.get("cohort_id"))
    ):
        return _record_position_issue(
            cursor,
            receipt,
            account_scope=account_scope,
            instrument=instrument,
            exchange=bound_exchange,
            blocker_code="INTENT_BINDING_INVALID",
            execution_id=execution_id,
        )
    if (
        not _is_identifier(expected_exchange)
        or not _is_identifier(evidence_exchange)
        or expected_exchange != evidence_exchange
    ):
        return _record_position_issue(
            cursor,
            receipt,
            account_scope=account_scope,
            instrument=instrument,
            exchange=bound_exchange,
            blocker_code="INTENT_EXCHANGE_MISMATCH",
            execution_id=execution_id,
        )

    abandoned = cursor.execute(
        """SELECT 1 FROM execution_intent_abandonments WHERE intent_id=?
           UNION ALL
           SELECT 1 FROM execution_slot_abandonments WHERE intent_id=? LIMIT 1""",
        (receipt["intent_id"], receipt["intent_id"]),
    ).fetchone()
    if abandoned is not None:
        return _record_position_issue(
            cursor,
            receipt,
            account_scope=account_scope,
            instrument=instrument,
            exchange=expected_exchange,
            blocker_code="FILL_INTENT_ABANDONED",
            execution_id=execution_id,
        )

    intent_state = intent["state"]
    dispatch_state = intent["dispatch_state"]
    dispatch_claimed = intent_state == "DISPATCHING" and dispatch_state is None
    dispatch_result_recorded = (
        intent_state in ("KNOWN", "UNKNOWN")
        and dispatch_state in ("KNOWN", "UNKNOWN")
        and (
            intent_state == dispatch_state
            or (
                intent_state == "KNOWN"
                and dispatch_state == "UNKNOWN"
                and cursor.execute(
                    """SELECT 1 FROM execution_intent_reconciliations
                       WHERE intent_id=? AND state='KNOWN' LIMIT 1""",
                    (receipt["intent_id"],),
                ).fetchone()
                is not None
            )
        )
    )
    if not (dispatch_claimed or dispatch_result_recorded):
        return _record_position_issue(
            cursor,
            receipt,
            account_scope=account_scope,
            instrument=instrument,
            exchange=expected_exchange,
            blocker_code="FILL_DISPATCH_NOT_CLAIMED",
            execution_id=execution_id,
        )

    quantity = _parse_decimal(evidence.get("quantity"), positive=True)
    price = _parse_decimal(evidence.get("price"), positive=True)
    fee = (
        None
        if evidence.get("fee") is None
        else _parse_decimal(evidence.get("fee"), nonnegative=True)
    )
    filled_at_ns = evidence.get("filled_at_ns")
    if quantity is None or price is None or (evidence.get("fee") is not None and fee is None):
        return _record_position_issue(
            cursor,
            receipt,
            account_scope=account_scope,
            instrument=instrument,
            exchange=bound_exchange,
            blocker_code="FILL_ECONOMICS_INVALID",
            execution_id=execution_id,
        )
    if filled_at_ns is not None and (type(filled_at_ns) is not int or filled_at_ns <= 0):
        return _record_position_issue(
            cursor,
            receipt,
            account_scope=account_scope,
            instrument=instrument,
            exchange=bound_exchange,
            blocker_code="FILL_TIME_INVALID",
            execution_id=execution_id,
        )
    exchange = expected_exchange
    if execution_id is None:
        return _record_position_issue(
            cursor,
            receipt,
            account_scope=account_scope,
            instrument=instrument,
            exchange=exchange,
            blocker_code="FILL_ID_UNAVAILABLE",
        )
    position_effect = intent_key["position_effect"]
    order_side = intent_key["side"]
    owner_intent_id = None
    stop_price = None
    risk_policy_id = None
    risk_policy_json = None
    cohort_id = business_key["cohort_id"]
    close_time = business_key.get("close_time")
    decision_grid_ordinal = None

    if position_effect == "OPEN":
        factor_stop = economics.get("factor_stop_price")
        legacy_stop = economics.get("stop_price")
        factor_stop_price = _parse_decimal(factor_stop, positive=True)
        legacy_stop_price = _parse_decimal(legacy_stop, positive=True)
        if factor_stop is not None and legacy_stop is not None:
            stop_price = (
                factor_stop_price
                if factor_stop_price is not None and factor_stop_price == legacy_stop_price
                else None
            )
        else:
            stop_price = factor_stop_price if factor_stop is not None else legacy_stop_price
        risk_policy_id = economics.get("risk_policy_id")
        risk_policy = economics.get("risk_policy")
        if (
            _is_identifier(risk_policy_id)
            and isinstance(risk_policy, Mapping)
            and bool(risk_policy)
        ):
            try:
                risk_policy_json = _canonical_json(risk_policy)
            except FactorPositionBookError:
                return _record_position_issue(
                    cursor,
                    receipt,
                    account_scope=account_scope,
                    instrument=instrument,
                    exchange=exchange,
                    blocker_code="POSITION_RISK_METADATA_INVALID",
                    execution_id=execution_id,
                )
        requested_ordinal = economics.get("entry_grid_ordinal")
        if requested_ordinal is not None and (
            type(requested_ordinal) is not int or requested_ordinal < 1
        ):
            return _record_position_issue(
                cursor,
                receipt,
                account_scope=account_scope,
                instrument=instrument,
                exchange=exchange,
                blocker_code="OPEN_GRID_BINDING_MISMATCH",
                execution_id=execution_id,
            )
        if requested_ordinal is not None:
            grid = cursor.execute(
                """SELECT ordinal,batch_id,close_time FROM factor_position_grid_history
                   WHERE account_scope=? AND strategy_scope=? AND cohort_id=? AND ordinal=?""",
                (account_scope, strategy_scope, cohort_id, requested_ordinal),
            ).fetchone()
            if grid is not None and grid["close_time"] != close_time:
                grid = None
            if grid is None:
                return _record_position_issue(
                    cursor,
                    receipt,
                    account_scope=account_scope,
                    instrument=instrument,
                    exchange=exchange,
                    blocker_code="OPEN_GRID_BINDING_MISMATCH",
                    execution_id=execution_id,
                )
        else:
            grid = cursor.execute(
                """SELECT ordinal,batch_id,close_time FROM factor_position_grid_history
                   WHERE account_scope=? AND strategy_scope=? AND cohort_id=? AND close_time=?""",
                (account_scope, strategy_scope, cohort_id, close_time),
            ).fetchone()
        if grid is not None:
            batch_id = economics.get("batch_id", economics.get("grid_batch_id"))
            if batch_id is not None and batch_id != grid["batch_id"]:
                return _record_position_issue(
                    cursor,
                    receipt,
                    account_scope=account_scope,
                    instrument=instrument,
                    exchange=exchange,
                    blocker_code="OPEN_GRID_BINDING_MISMATCH",
                    execution_id=execution_id,
                )
            decision_grid_ordinal = int(grid["ordinal"])
        else:
            batch_id = economics.get("batch_id", economics.get("grid_batch_id"))
        opening_values = (
            account_scope,
            strategy_scope,
            instrument,
            exchange,
            "LONG" if order_side == "BUY" else "SHORT",
            None if stop_price is None else str(stop_price),
            risk_policy_id if _is_identifier(risk_policy_id) else None,
            risk_policy_json,
            cohort_id,
            batch_id if _is_identifier(batch_id) else None,
            close_time if isinstance(close_time, str) else None,
            decision_grid_ordinal,
        )
        existing_open = cursor.execute(
            "SELECT * FROM factor_position_openings WHERE intent_id=?", (intent["intent_id"],)
        ).fetchone()
        if existing_open is None:
            cursor.execute(
                """INSERT INTO factor_position_openings
                   (intent_id, account_scope, strategy_scope, instrument, exchange,
                    position_side, stop_price, risk_policy_id, risk_policy_json,
                    cohort_id, batch_id, close_time, decision_grid_ordinal, created_at_ns)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (intent["intent_id"],) + opening_values + (int(intent["created_at_ns"]),),
            )
        elif _opening_values(existing_open) != opening_values:
            return _record_position_issue(
                cursor,
                receipt,
                account_scope=account_scope,
                instrument=instrument,
                exchange=exchange,
                blocker_code="OPENING_INTENT_ECONOMICS_CONFLICT",
                execution_id=execution_id,
            )
    else:
        owner_intent_id = economics.get("owner_intent_id")
        if not _is_identifier(owner_intent_id) or owner_intent_id != intent["owner_intent_id"]:
            return _record_position_issue(
                cursor,
                receipt,
                account_scope=account_scope,
                instrument=instrument,
                exchange=exchange,
                blocker_code="CLOSE_OWNER_SCOPE_MISMATCH",
                execution_id=execution_id,
            )
        opening = cursor.execute(
            """SELECT * FROM factor_position_openings WHERE intent_id=?""",
            (owner_intent_id,),
        ).fetchone()
        if (
            opening is None
            or opening["account_scope"] != account_scope
            or opening["strategy_scope"] != strategy_scope
            or opening["instrument"] != instrument
            or opening["exchange"] != exchange
            or opening["position_side"] != ("LONG" if order_side == "SELL" else "SHORT")
        ):
            return _record_position_issue(
                cursor,
                receipt,
                account_scope=account_scope,
                instrument=instrument,
                exchange=exchange,
                blocker_code="CLOSE_OWNER_SCOPE_MISMATCH",
                execution_id=execution_id,
            )

    normalized_quantity = _serialize_decimal(quantity)
    normalized_price = _serialize_decimal(price)
    normalized_fee = None if fee is None else _serialize_decimal(fee)
    fill_identity = {
        "account_scope": account_scope,
        "instrument": instrument,
        "exchange": exchange,
        "execution_id": execution_id,
        "intent_id": intent["intent_id"],
        "strategy_scope": strategy_scope,
        "position_effect": position_effect,
        "order_side": order_side,
        "owner_intent_id": owner_intent_id,
        "quantity": normalized_quantity,
        "price": normalized_price,
        "fee": normalized_fee,
        "filled_at_ns": filled_at_ns,
    }
    payload_digest = hashlib.sha256(_canonical_json(fill_identity).encode("utf-8")).hexdigest()
    fill_values = (
        account_scope,
        instrument,
        exchange,
        execution_id,
        receipt_id,
        intent["intent_id"],
        strategy_scope,
        position_effect,
        order_side,
        owner_intent_id,
        normalized_quantity,
        normalized_price,
        normalized_fee,
        filled_at_ns,
        payload_digest,
    )
    existing_fill = cursor.execute(
        """SELECT * FROM factor_position_fills
           WHERE account_scope=? AND instrument=? AND exchange=? AND execution_id=?""",
        (account_scope, instrument, exchange, execution_id),
    ).fetchone()
    if existing_fill is not None:
        if not _same_fill_binding(existing_fill, fill_values):
            return _record_position_issue(
                cursor,
                receipt,
                account_scope=account_scope,
                instrument=instrument,
                exchange=exchange,
                blocker_code="EXECUTION_ID_CONFLICT",
                execution_id=execution_id,
            )
        try:
            enrichment_blocker = _enrich_duplicate_fill(
                cursor,
                receipt,
                existing_fill,
                fee=normalized_fee,
                filled_at_ns=filled_at_ns,
                fill_identity=fill_identity,
            )
        except FactorPositionBookError as error:
            enrichment_blocker = error.code
        if enrichment_blocker is not None:
            return _record_position_issue(
                cursor,
                receipt,
                account_scope=account_scope,
                instrument=instrument,
                exchange=exchange,
                blocker_code=enrichment_blocker,
                execution_id=execution_id,
            )
        return FactorPositionApplyResult("DUPLICATE", receipt_id, execution_id, intent["intent_id"])
    receipt_fill = cursor.execute(
        "SELECT execution_id FROM factor_position_fills WHERE receipt_id=?", (receipt_id,)
    ).fetchone()
    if receipt_fill is not None:
        return _record_position_issue(
            cursor,
            receipt,
            account_scope=account_scope,
            instrument=instrument,
            exchange=exchange,
            blocker_code="CALLBACK_RECEIPT_FILL_CONFLICT",
            execution_id=execution_id,
        )
    if position_effect == "CLOSE":
        current = cursor.execute(
            """SELECT * FROM factor_position_current
               WHERE account_scope=? AND instrument=? AND exchange=?""",
            (account_scope, instrument, exchange),
        ).fetchone()
        if (
            current is None
            or current["state"] not in ("ACTIVE", "UNKNOWN")
            or current["owner_intent_id"] != owner_intent_id
            or current["strategy_scope"] != strategy_scope
        ):
            return _record_position_issue(
                cursor,
                receipt,
                account_scope=account_scope,
                instrument=instrument,
                exchange=exchange,
                blocker_code="CLOSE_OWNER_SCOPE_MISMATCH",
                execution_id=execution_id,
            )
        open_quantity = _parse_accumulator_decimal(current["open_quantity"], positive=True)
        close_quantity = _parse_accumulator_decimal(current["close_quantity"], nonnegative=True)
        if open_quantity is None or close_quantity is None or close_quantity > open_quantity:
            return _record_position_issue(
                cursor,
                receipt,
                account_scope=account_scope,
                instrument=instrument,
                exchange=exchange,
                blocker_code="CLOSE_OWNER_QUANTITY_UNKNOWN",
                execution_id=execution_id,
            )
        remaining = _decimal_add(open_quantity, -close_quantity)
        if quantity > remaining:
            return _record_position_issue(
                cursor,
                receipt,
                account_scope=account_scope,
                instrument=instrument,
                exchange=exchange,
                blocker_code="CLOSE_FILL_EXCEEDS_OWNED_QUANTITY",
                execution_id=execution_id,
            )
    cursor.execute(
        """INSERT INTO factor_position_fills
           (account_scope, instrument, exchange, execution_id, receipt_id, intent_id,
            strategy_scope, position_effect, order_side, owner_intent_id, quantity,
            price, fee, filled_at_ns, payload_sha256)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        fill_values,
    )
    cursor.execute(
        """INSERT INTO factor_position_fill_attributes
           (account_scope,instrument,exchange,execution_id,intent_id,position_effect,
            position_epoch,fee,filled_at_ns,last_receipt_id,payload_sha256)
           VALUES(?,?,?,?,?,?,NULL,?,?,?,?)""",
        (
            account_scope,
            instrument,
            exchange,
            execution_id,
            intent["intent_id"],
            position_effect,
            normalized_fee,
            filled_at_ns,
            receipt_id,
            payload_digest,
        ),
    )
    open_total_blocker = None
    if position_effect == "OPEN":
        open_total_blocker = _record_open_intent_fill_total(
            cursor,
            intent=intent,
            account_scope=account_scope,
            strategy_scope=strategy_scope,
            instrument=instrument,
            exchange=exchange,
            quantity=quantity,
            updated_at_ns=int(receipt["created_at_ns"]),
        )
    try:
        blocker = _project_new_fill(
            cursor,
            receipt=receipt,
            intent=intent,
            account_scope=account_scope,
            strategy_scope=strategy_scope,
            instrument=instrument,
            exchange=exchange,
            execution_id=execution_id,
            position_effect=position_effect,
            order_side=order_side,
            owner_intent_id=owner_intent_id,
            quantity=quantity,
            price=price,
            fee=fee,
            filled_at_ns=filled_at_ns,
            decision_grid_ordinal=decision_grid_ordinal,
            cohort_id=cohort_id,
        )
    except FactorPositionBookError as error:
        blocker = error.code
    if position_effect == "OPEN" and blocker is None:
        current = cursor.execute(
            """SELECT epoch FROM factor_position_current
               WHERE account_scope=? AND instrument=? AND exchange=?
                 AND owner_intent_id=? AND strategy_scope=?""",
            (account_scope, instrument, exchange, intent["intent_id"], strategy_scope),
        ).fetchone()
        if current is None:
            blocker = "POSITION_EPOCH_BINDING_UNAVAILABLE"
        else:
            cursor.execute(
                """UPDATE factor_position_fill_attributes SET position_epoch=?
                   WHERE account_scope=? AND instrument=? AND exchange=? AND execution_id=?""",
                (
                    int(current["epoch"]),
                    account_scope,
                    instrument,
                    exchange,
                    execution_id,
                ),
            )
    if blocker is not None:
        return _record_position_issue(
            cursor,
            receipt,
            account_scope=account_scope,
            instrument=instrument,
            exchange=exchange,
            blocker_code=blocker,
            execution_id=execution_id,
        )
    if open_total_blocker is not None:
        return _record_position_issue(
            cursor,
            receipt,
            account_scope=account_scope,
            instrument=instrument,
            exchange=exchange,
            blocker_code=open_total_blocker,
            execution_id=execution_id,
        )
    return FactorPositionApplyResult("APPLIED", receipt_id, execution_id, intent["intent_id"])


def _record_open_intent_fill_total(
    cursor: sqlite3.Cursor,
    *,
    intent: sqlite3.Row,
    account_scope: str,
    strategy_scope: str,
    instrument: str,
    exchange: str,
    quantity: Decimal,
    updated_at_ns: int,
) -> Optional[str]:
    """Persist the exact lifetime OPEN quantity for its immutable intent."""

    intent_id = intent["intent_id"]
    existing = cursor.execute(
        "SELECT * FROM factor_position_open_intent_totals WHERE intent_id=?", (intent_id,)
    ).fetchone()
    binding = (account_scope, strategy_scope, instrument, exchange)
    blocker = None
    complete = True
    total = Decimal(0)
    if existing is not None:
        existing_binding = tuple(
            existing[name] for name in ("account_scope", "strategy_scope", "instrument", "exchange")
        )
        total = _parse_accumulator_decimal(existing["filled_quantity"], nonnegative=True)
        complete = bool(existing["quantity_complete"]) and total is not None
        blocker = existing["blocker_code"]
        if existing_binding != binding:
            complete = False
            blocker = "OPEN_INTENT_FILL_TOTAL_CONFLICT"
        if total is None:
            total = Decimal(0)
            complete = False
            blocker = blocker or "OPEN_INTENT_FILL_TOTAL_UNAVAILABLE"
    if complete:
        try:
            total = _decimal_add(total, quantity)
        except FactorPositionBookError as error:
            complete = False
            blocker = error.code
    try:
        economics = json.loads(intent["economic_payload_json"])
    except (TypeError, ValueError):
        economics = None
    requested = (
        _parse_decimal(economics.get("quantity"), positive=True)
        if isinstance(economics, Mapping)
        else None
    )
    if blocker is None:
        if not complete:
            blocker = "OPEN_INTENT_FILL_TOTAL_UNAVAILABLE"
        elif requested is None:
            blocker = "OPEN_INTENT_QUANTITY_UNAVAILABLE"
        elif total > requested:
            blocker = "OPEN_INTENT_QUANTITY_EXCEEDED"
    cursor.execute(
        """INSERT INTO factor_position_open_intent_totals
           (intent_id,account_scope,strategy_scope,instrument,exchange,filled_quantity,
            quantity_complete,blocker_code,updated_at_ns)
           VALUES(?,?,?,?,?,?,?,?,?)
           ON CONFLICT(intent_id) DO UPDATE SET
             account_scope=excluded.account_scope,strategy_scope=excluded.strategy_scope,
             instrument=excluded.instrument,exchange=excluded.exchange,
             filled_quantity=excluded.filled_quantity,
             quantity_complete=excluded.quantity_complete,
             blocker_code=excluded.blocker_code,updated_at_ns=excluded.updated_at_ns""",
        (
            intent_id,
            account_scope,
            strategy_scope,
            instrument,
            exchange,
            _serialize_decimal(total),
            int(complete),
            blocker,
            updated_at_ns,
        ),
    )
    return blocker


def _same_fill_binding(existing: sqlite3.Row, values: Tuple[Any, ...]) -> bool:
    """Compare immutable execution identity while allowing missing enrichment."""

    names = (
        "account_scope",
        "instrument",
        "exchange",
        "execution_id",
        "intent_id",
        "strategy_scope",
        "position_effect",
        "order_side",
        "owner_intent_id",
        "quantity",
        "price",
    )
    indexes = (0, 1, 2, 3, 5, 6, 7, 8, 9, 10, 11)
    if any(existing[name] != values[index] for name, index in zip(names, indexes)):
        return False
    return existing["position_effect"] in ("OPEN", "CLOSE")


def _enrich_duplicate_fill(
    cursor: sqlite3.Cursor,
    receipt: sqlite3.Row,
    existing_fill: sqlite3.Row,
    *,
    fee: Optional[str],
    filled_at_ns: Optional[int],
    fill_identity: Mapping[str, Any],
) -> Optional[str]:
    """Record later known fee/time facts without rewriting immutable fill evidence."""

    identity = (
        existing_fill["account_scope"],
        existing_fill["instrument"],
        existing_fill["exchange"],
        existing_fill["execution_id"],
    )
    attributes = cursor.execute(
        """SELECT * FROM factor_position_fill_attributes
           WHERE account_scope=? AND instrument=? AND exchange=? AND execution_id=?""",
        identity,
    ).fetchone()
    if attributes is None:
        # Legacy histories are seeded UNKNOWN during migration.  Retain their
        # raw known attributes for audit, but never use that history to infer
        # ownership in the current projection.
        attributes = {
            "fee": existing_fill["fee"],
            "filled_at_ns": existing_fill["filled_at_ns"],
            "position_epoch": None,
        }
        cursor.execute(
            """INSERT INTO factor_position_fill_attributes
               (account_scope,instrument,exchange,execution_id,intent_id,position_effect,
                position_epoch,fee,filled_at_ns,last_receipt_id,payload_sha256)
               VALUES(?,?,?,?,?,?,NULL,?,?,?,?)""",
            identity
            + (
                existing_fill["intent_id"],
                existing_fill["position_effect"],
                existing_fill["fee"],
                existing_fill["filled_at_ns"],
                existing_fill["receipt_id"],
                existing_fill["payload_sha256"],
            ),
        )
    old_fee = attributes["fee"]
    old_time = attributes["filled_at_ns"]
    if fee is not None and old_fee is not None and fee != old_fee:
        return "EXECUTION_ID_CONFLICT"
    if filled_at_ns is not None and old_time is not None and filled_at_ns != int(old_time):
        return "EXECUTION_ID_CONFLICT"
    next_fee = old_fee if old_fee is not None else fee
    next_time = old_time if old_time is not None else filled_at_ns
    payload_digest = hashlib.sha256(_canonical_json(fill_identity).encode("utf-8")).hexdigest()
    changed = next_fee != old_fee or next_time != old_time
    if changed:
        cursor.execute(
            """UPDATE factor_position_fill_attributes
               SET fee=?,filled_at_ns=?,last_receipt_id=?,payload_sha256=?
               WHERE account_scope=? AND instrument=? AND exchange=? AND execution_id=?""",
            (next_fee, next_time, receipt["receipt_id"], payload_digest) + identity,
        )
    current = cursor.execute(
        """SELECT * FROM factor_position_current
           WHERE account_scope=? AND instrument=? AND exchange=?""",
        identity[:3],
    ).fetchone()
    if (
        current is None
        or current["state"] == "FLAT"
        or current["owner_intent_id"] != existing_fill["intent_id"]
        or existing_fill["position_effect"] != "OPEN"
        or attributes["position_epoch"] is None
        or int(attributes["position_epoch"]) != int(current["epoch"])
    ):
        return None
    fee_unknown = int(current["opening_fee_unknown_count"])
    fee_total = _parse_accumulator_decimal(current["opening_fee_total"], nonnegative=True)
    if fee_total is None:
        return "POSITION_PROJECTION_CORRUPT"
    if old_fee is None and fee is not None:
        if fee_unknown <= 0:
            return "POSITION_FEE_PROJECTION_CONFLICT"
        fee_unknown -= 1
        parsed_fee = _parse_decimal(fee, nonnegative=True)
        if parsed_fee is None:
            return "FILL_ECONOMICS_INVALID"
        fee_total = _decimal_add(fee_total, parsed_fee)
    time_unknown = int(current["fill_time_unknown_count"])
    if old_time is None and filled_at_ns is not None:
        if time_unknown <= 0:
            return "POSITION_FILL_TIME_PROJECTION_CONFLICT"
        time_unknown -= 1
    first_fill_at_ns = current["first_fill_at_ns"]
    first_fill_grid_ordinal = current["first_fill_grid_ordinal"]
    if time_unknown == 0:
        first = cursor.execute(
            """SELECT filled_at_ns FROM factor_position_fill_attributes
               WHERE account_scope=? AND instrument=? AND exchange=? AND intent_id=?
                 AND position_effect='OPEN' AND position_epoch=?
                 AND filled_at_ns IS NOT NULL
               ORDER BY filled_at_ns,execution_id LIMIT 1""",
            identity[:3] + (existing_fill["intent_id"], int(current["epoch"])),
        ).fetchone()
        if first is None:
            return "POSITION_FILL_TIME_PROJECTION_CONFLICT"
        first_fill_at_ns = int(first["filled_at_ns"])
        opening = cursor.execute(
            "SELECT * FROM factor_position_openings WHERE intent_id=?",
            (existing_fill["intent_id"],),
        ).fetchone()
        if opening is None:
            return "POSITION_OWNER_EVIDENCE_UNAVAILABLE"
        first_fill_grid_ordinal = _grid_anchor_for_fill(
            cursor,
            account_scope=existing_fill["account_scope"],
            strategy_scope=existing_fill["strategy_scope"],
            cohort_id=opening["cohort_id"],
            filled_at_ns=first_fill_at_ns,
            decision_grid_ordinal=opening["decision_grid_ordinal"],
        )
    elif filled_at_ns is not None and (
        first_fill_at_ns is None or filled_at_ns < int(first_fill_at_ns)
    ):
        first_fill_at_ns = filled_at_ns
        opening = cursor.execute(
            "SELECT * FROM factor_position_openings WHERE intent_id=?",
            (existing_fill["intent_id"],),
        ).fetchone()
        if opening is None:
            return "POSITION_OWNER_EVIDENCE_UNAVAILABLE"
        first_fill_grid_ordinal = _grid_anchor_for_fill(
            cursor,
            account_scope=existing_fill["account_scope"],
            strategy_scope=existing_fill["strategy_scope"],
            cohort_id=opening["cohort_id"],
            filled_at_ns=first_fill_at_ns,
            decision_grid_ordinal=opening["decision_grid_ordinal"],
        )
    previous_callback = current["last_callback_at_ns"]
    callback_at_ns = int(receipt["created_at_ns"])
    last_callback_at_ns = (
        callback_at_ns if previous_callback is None else max(int(previous_callback), callback_at_ns)
    )
    cursor.execute(
        """UPDATE factor_position_current
           SET opening_fee_total=?,opening_fee_unknown_count=?,
               fill_time_unknown_count=?,fill_time_complete=?,first_fill_at_ns=?,
               first_fill_grid_ordinal=?,last_callback_at_ns=?,updated_at_ns=?
           WHERE account_scope=? AND instrument=? AND exchange=?""",
        (
            _serialize_decimal(fee_total),
            fee_unknown,
            time_unknown,
            int(time_unknown == 0),
            first_fill_at_ns,
            first_fill_grid_ordinal,
            last_callback_at_ns,
            callback_at_ns,
        )
        + identity[:3],
    )
    return None


def _project_new_fill(
    cursor: sqlite3.Cursor,
    *,
    receipt: sqlite3.Row,
    intent: sqlite3.Row,
    account_scope: str,
    strategy_scope: str,
    instrument: str,
    exchange: str,
    execution_id: str,
    position_effect: str,
    order_side: str,
    owner_intent_id: Optional[str],
    quantity: Decimal,
    price: Decimal,
    fee: Optional[Decimal],
    filled_at_ns: Optional[int],
    decision_grid_ordinal: Optional[int],
    cohort_id: str,
) -> Optional[str]:
    """Update the one materialized position row after accepting a unique fill."""

    current = cursor.execute(
        """SELECT * FROM factor_position_current
           WHERE account_scope=? AND instrument=? AND exchange=?""",
        (account_scope, instrument, exchange),
    ).fetchone()
    callback_at_ns = int(receipt["created_at_ns"])
    if position_effect == "OPEN":
        opening = cursor.execute(
            "SELECT * FROM factor_position_openings WHERE intent_id=?",
            (intent["intent_id"],),
        ).fetchone()
        if (
            opening is None
            or opening["account_scope"] != account_scope
            or opening["strategy_scope"] != strategy_scope
            or opening["instrument"] != instrument
            or opening["exchange"] != exchange
            or opening["cohort_id"] != cohort_id
            or opening["position_side"] != ("LONG" if order_side == "BUY" else "SHORT")
        ):
            return "OPENING_INTENT_ECONOMICS_CONFLICT"
        active_issue = cursor.execute(
            """SELECT blocker_code FROM factor_position_active_issues
               WHERE account_scope=? AND instrument=? AND exchange_key IN (?,?) LIMIT 1""",
            (account_scope, instrument, exchange, _UNKNOWN_EXCHANGE_KEY),
        ).fetchone()
        if current is None:
            if active_issue is not None:
                return "POSITION_EVIDENCE_BLOCKED"
            epoch = 1
            state = "ACTIVE"
            blocker = None
            open_quantity = Decimal(0)
            close_quantity = Decimal(0)
            open_notional = Decimal(0)
            opening_fee_total = Decimal(0)
            opening_fee_unknown_count = 0
            first_fill_at_ns = None
            first_fill_grid_ordinal = None
            fill_time_unknown_count = 0
            last_callback_at_ns = None
        elif current["state"] == "FLAT":
            flat_at = current["flat_checkpoint_ns"]
            intent_started = int(intent["created_at_ns"])
            if flat_at is not None and max(intent_started, callback_at_ns) <= int(flat_at):
                return "FILL_PRECEDES_FLAT_CHECKPOINT"
            if active_issue is not None:
                return "POSITION_EVIDENCE_BLOCKED"
            epoch = int(current["epoch"]) + 1
            state = "ACTIVE"
            blocker = None
            open_quantity = Decimal(0)
            close_quantity = Decimal(0)
            open_notional = Decimal(0)
            opening_fee_total = Decimal(0)
            opening_fee_unknown_count = 0
            first_fill_at_ns = None
            first_fill_grid_ordinal = None
            fill_time_unknown_count = 0
            last_callback_at_ns = None
        else:
            if (
                current["owner_intent_id"] != intent["intent_id"]
                or current["strategy_scope"] != strategy_scope
                or current["position_side"] != opening["position_side"]
                or current["cohort_id"] != cohort_id
            ):
                return "POSITION_OWNER_AMBIGUOUS"
            try:
                open_quantity = _parse_accumulator_decimal(
                    current["open_quantity"], nonnegative=True
                )
                close_quantity = _parse_accumulator_decimal(
                    current["close_quantity"], nonnegative=True
                )
                open_notional = _parse_accumulator_decimal(
                    current["open_notional"], nonnegative=True
                )
                opening_fee_total = _parse_accumulator_decimal(
                    current["opening_fee_total"], nonnegative=True
                )
            except (TypeError, ValueError):
                return "POSITION_PROJECTION_CORRUPT"
            if any(
                value is None
                for value in (open_quantity, close_quantity, open_notional, opening_fee_total)
            ):
                return "POSITION_PROJECTION_CORRUPT"
            state = current["state"]
            blocker = current["blocker_code"]
            epoch = int(current["epoch"])
            opening_fee_unknown_count = int(current["opening_fee_unknown_count"])
            fill_time_unknown_count = int(current["fill_time_unknown_count"])
            first_fill_at_ns = current["first_fill_at_ns"]
            first_fill_grid_ordinal = current["first_fill_grid_ordinal"]
            last_callback_at_ns = current["last_callback_at_ns"]
        open_quantity = _decimal_add(open_quantity, quantity)
        open_notional = _decimal_add(open_notional, _decimal_multiply(quantity, price))
        if fee is None:
            opening_fee_unknown_count += 1
        else:
            opening_fee_total = _decimal_add(opening_fee_total, fee)
        if filled_at_ns is None:
            fill_time_unknown_count += 1
        else:
            if decision_grid_ordinal is not None and not _fill_follows_entry_grid(
                cursor,
                account_scope=account_scope,
                strategy_scope=strategy_scope,
                cohort_id=cohort_id,
                decision_grid_ordinal=decision_grid_ordinal,
                filled_at_ns=filled_at_ns,
            ):
                return "OPEN_FILL_PRECEDES_ENTRY_GRID"
            if first_fill_at_ns is None or filled_at_ns < int(first_fill_at_ns):
                first_fill_at_ns = filled_at_ns
                first_fill_grid_ordinal = _grid_anchor_for_fill(
                    cursor,
                    account_scope=account_scope,
                    strategy_scope=strategy_scope,
                    cohort_id=cohort_id,
                    filled_at_ns=filled_at_ns,
                    decision_grid_ordinal=decision_grid_ordinal,
                )
        if last_callback_at_ns is None:
            last_callback_at_ns = callback_at_ns
        else:
            last_callback_at_ns = max(int(last_callback_at_ns), callback_at_ns)
        cursor.execute(
            """INSERT INTO factor_position_current
               (account_scope,instrument,exchange,state,blocker_code,epoch,
                owner_intent_id,strategy_scope,cohort_id,position_side,open_quantity,
                close_quantity,open_notional,opening_fee_total,opening_fee_unknown_count,
                first_fill_at_ns,first_fill_grid_ordinal,fill_time_complete,
                fill_time_unknown_count,last_callback_at_ns,flat_checkpoint_ns,
                flat_reconciliation_id,updated_at_ns)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(account_scope,instrument,exchange) DO UPDATE SET
                 state=excluded.state,blocker_code=excluded.blocker_code,
                 epoch=excluded.epoch,owner_intent_id=excluded.owner_intent_id,
                 strategy_scope=excluded.strategy_scope,cohort_id=excluded.cohort_id,
                 position_side=excluded.position_side,open_quantity=excluded.open_quantity,
                 close_quantity=excluded.close_quantity,open_notional=excluded.open_notional,
                 opening_fee_total=excluded.opening_fee_total,
                 opening_fee_unknown_count=excluded.opening_fee_unknown_count,
                 first_fill_at_ns=excluded.first_fill_at_ns,
                 first_fill_grid_ordinal=excluded.first_fill_grid_ordinal,
                 fill_time_complete=excluded.fill_time_complete,
                 fill_time_unknown_count=excluded.fill_time_unknown_count,
                 last_callback_at_ns=excluded.last_callback_at_ns,
                 updated_at_ns=excluded.updated_at_ns""",
            (
                account_scope,
                instrument,
                exchange,
                state,
                blocker,
                epoch,
                intent["intent_id"],
                strategy_scope,
                cohort_id,
                opening["position_side"],
                _serialize_decimal(open_quantity),
                _serialize_decimal(close_quantity),
                _serialize_decimal(open_notional),
                _serialize_decimal(opening_fee_total),
                opening_fee_unknown_count,
                first_fill_at_ns,
                first_fill_grid_ordinal,
                int(fill_time_unknown_count == 0),
                fill_time_unknown_count,
                last_callback_at_ns,
                None if current is None else current["flat_checkpoint_ns"],
                None if current is None else current["flat_reconciliation_id"],
                callback_at_ns,
            ),
        )
        return None

    if current is None or current["state"] == "FLAT":
        return "CLOSE_OWNER_QUANTITY_UNKNOWN"
    if (
        current["owner_intent_id"] != owner_intent_id
        or current["strategy_scope"] != strategy_scope
        or current["position_side"] != ("LONG" if order_side == "SELL" else "SHORT")
    ):
        return "CLOSE_OWNER_SCOPE_MISMATCH"
    opened = _parse_accumulator_decimal(current["open_quantity"], positive=True)
    closed = _parse_accumulator_decimal(current["close_quantity"], nonnegative=True)
    if opened is None or closed is None:
        return "CLOSE_OWNER_QUANTITY_UNKNOWN"
    if _decimal_add(closed, quantity) > opened:
        return "CLOSE_FILL_EXCEEDS_OWNED_QUANTITY"
    next_callback = (
        callback_at_ns
        if current["last_callback_at_ns"] is None
        else max(int(current["last_callback_at_ns"]), callback_at_ns)
    )
    cursor.execute(
        """UPDATE factor_position_current
           SET close_quantity=?,last_callback_at_ns=?,updated_at_ns=?
           WHERE account_scope=? AND instrument=? AND exchange=?""",
        (
            _serialize_decimal(_decimal_add(closed, quantity)),
            next_callback,
            callback_at_ns,
            account_scope,
            instrument,
            exchange,
        ),
    )
    return None


def _fill_follows_entry_grid(
    cursor: sqlite3.Cursor,
    *,
    account_scope: str,
    strategy_scope: str,
    cohort_id: str,
    decision_grid_ordinal: int,
    filled_at_ns: int,
) -> bool:
    row = cursor.execute(
        """SELECT close_time_ns FROM factor_position_grid_history
           WHERE account_scope=? AND strategy_scope=? AND cohort_id=? AND ordinal=?""",
        (account_scope, strategy_scope, cohort_id, decision_grid_ordinal),
    ).fetchone()
    return row is not None and int(row["close_time_ns"]) <= filled_at_ns


def _grid_anchor_for_fill(
    cursor: sqlite3.Cursor,
    *,
    account_scope: str,
    strategy_scope: str,
    cohort_id: Optional[str],
    filled_at_ns: int,
    decision_grid_ordinal: Optional[int],
) -> Optional[int]:
    if not _is_identifier(cohort_id):
        return None
    row = cursor.execute(
        """SELECT ordinal FROM factor_position_grid_history
           WHERE account_scope=? AND strategy_scope=? AND cohort_id=?
             AND close_time_ns<=?
           ORDER BY close_time_ns DESC,ordinal DESC LIMIT 1""",
        (account_scope, strategy_scope, cohort_id, filled_at_ns),
    ).fetchone()
    by_time = None if row is None else int(row["ordinal"])
    if decision_grid_ordinal is None:
        return by_time
    if not _fill_follows_entry_grid(
        cursor,
        account_scope=account_scope,
        strategy_scope=strategy_scope,
        cohort_id=cohort_id,
        decision_grid_ordinal=decision_grid_ordinal,
        filled_at_ns=filled_at_ns,
    ):
        return None
    return max(decision_grid_ordinal, by_time or decision_grid_ordinal)


def _current_signed_quantity(current: sqlite3.Row) -> Decimal:
    opened = _parse_accumulator_decimal(current["open_quantity"], nonnegative=True)
    closed = _parse_accumulator_decimal(current["close_quantity"], nonnegative=True)
    if opened is None or closed is None or closed > opened:
        raise FactorPositionBookError("POSITION_PROJECTION_CORRUPT")
    residual = _decimal_add(opened, -closed)
    side = current["position_side"]
    if side == "LONG":
        return residual
    if side == "SHORT":
        return -residual
    if residual == 0:
        return Decimal(0)
    raise FactorPositionBookError("POSITION_PROJECTION_CORRUPT")


def _opening_matches_current(
    opening: sqlite3.Row,
    current: sqlite3.Row,
    *,
    account_scope: str,
    instrument: str,
    exchange: str,
) -> bool:
    return (
        opening["intent_id"] == current["owner_intent_id"]
        and opening["account_scope"] == account_scope
        and opening["instrument"] == instrument
        and opening["exchange"] == exchange
        and opening["strategy_scope"] == current["strategy_scope"]
        and opening["cohort_id"] == current["cohort_id"]
        and opening["position_side"] == current["position_side"]
    )


def _current_attribution(
    current: Optional[sqlite3.Row], opening: Optional[sqlite3.Row]
) -> Mapping[str, Any]:
    if current is None or opening is None:
        return {}
    open_quantity = _parse_accumulator_decimal(current["open_quantity"], positive=True)
    open_notional = _parse_accumulator_decimal(current["open_notional"], nonnegative=True)
    fee_total = _parse_accumulator_decimal(current["opening_fee_total"], nonnegative=True)
    average_price = (
        None
        if open_quantity is None or open_notional is None
        else _decimal_divide(open_notional, open_quantity)
    )
    try:
        attributed_signed_quantity = _current_signed_quantity(current)
    except FactorPositionBookError:
        attributed_signed_quantity = None
    stop_price = _parse_decimal(opening["stop_price"], positive=True)
    risk_policy_id = opening["risk_policy_id"]
    try:
        policy = json.loads(opening["risk_policy_json"])
    except (TypeError, ValueError):
        policy = None
    risk_policy = _freeze_mapping(policy) if isinstance(policy, dict) else None
    fee_known = int(current["opening_fee_unknown_count"]) == 0 and fee_total is not None
    return {
        "attributed_signed_quantity": attributed_signed_quantity,
        "owner_strategy_scope": opening["strategy_scope"],
        "owner_intent_id": opening["intent_id"],
        "position_side": opening["position_side"],
        "average_price": average_price,
        "stop_price": stop_price,
        "held_eligible_bars": None,
        "risk_policy_id": risk_policy_id,
        "risk_policy": risk_policy,
        "opening_fee_total": fee_total if fee_known else None,
        "opening_fees_known": fee_known,
    }


class FactorPositionBook:
    """Read-only projection facade bound to one execution journal instance."""

    def __init__(self, journal: Any) -> None:
        connection = getattr(journal, "_connection", None)
        read_lock = getattr(journal, "_read_lock", None)
        if connection is None or not callable(read_lock):
            raise FactorPositionBookError("EXECUTION_JOURNAL_REQUIRED")
        self._journal = journal

    def snapshot(
        self,
        *,
        account_scope: str,
        strategy_scope: str,
        instrument: str,
        exchange: str,
        broker_quantity: Any,
        long_quantity: Any,
        short_quantity: Any,
        snapshot_id: str,
        available_at: datetime,
    ) -> FactorPositionAttributionSnapshot:
        """Match journal-derived ownership/risk against actual Broker and CTP facts."""

        for name, value in (
            ("account_scope", account_scope),
            ("strategy_scope", strategy_scope),
            ("instrument", instrument),
            ("exchange", exchange),
            ("snapshot_id", snapshot_id),
        ):
            _require_identifier(value, "INVALID_" + name.upper())
        if not isinstance(available_at, datetime) or available_at.tzinfo is None:
            raise FactorPositionBookError("INVALID_POSITION_SNAPSHOT_TIME")
        if available_at.utcoffset() is None:
            raise FactorPositionBookError("INVALID_POSITION_SNAPSHOT_TIME")
        broker = _parse_decimal(broker_quantity, nonnegative=False)
        long_qty = _parse_decimal(long_quantity, nonnegative=True)
        short_qty = _parse_decimal(short_quantity, nonnegative=True)
        base = {
            "account_scope": account_scope,
            "strategy_scope": strategy_scope,
            "instrument": instrument,
            "exchange": exchange,
            "snapshot_id": snapshot_id,
            "available_at": available_at,
        }
        if broker is None or long_qty is None or short_qty is None:
            return _snapshot("UNKNOWN", "POSITION_QUANTITY_INVALID", base, None)
        ctp_blocker = None
        if long_qty != 0 and short_qty != 0:
            ctp_blocker = "OPPOSING_POSITION_SIDES_PRESENT"
        elif broker != _decimal_add(long_qty, -short_qty):
            ctp_blocker = "BROKER_CTP_POSITION_MISMATCH"

        try:
            snapshot_time_ns = _datetime_to_ns(available_at)
            with self._journal._read_lock():
                connection = self._journal._connection
                pending_owner = connection.execute(
                    """SELECT owner_intent_id FROM execution_instrument_owners
                       WHERE account_scope=? AND instrument=?""",
                    (account_scope, instrument),
                ).fetchone()
                current = connection.execute(
                    """SELECT * FROM factor_position_current
                       WHERE account_scope=? AND instrument=? AND exchange=?""",
                    (account_scope, instrument, exchange),
                ).fetchone()
                active_issue = connection.execute(
                    """SELECT blocker_code,created_at_ns FROM factor_position_active_issues
                       WHERE account_scope=? AND instrument=? AND exchange_key IN (?,?)
                       ORDER BY created_at_ns DESC,receipt_id DESC LIMIT 1""",
                    (account_scope, instrument, exchange, _UNKNOWN_EXCHANGE_KEY),
                ).fetchone()
                opening = None
                if current is not None and _is_identifier(current["owner_intent_id"]):
                    opening = connection.execute(
                        "SELECT * FROM factor_position_openings WHERE intent_id=?",
                        (current["owner_intent_id"],),
                    ).fetchone()
                grid_cursor = None
                if opening is not None and _is_identifier(opening["cohort_id"]):
                    grid_cursor = connection.execute(
                        """SELECT ordinal,close_time FROM execution_grid_cursors
                           WHERE account_scope=? AND strategy_scope=? AND cohort_id=?""",
                        (account_scope, opening["strategy_scope"], opening["cohort_id"]),
                    ).fetchone()
        except (sqlite3.Error, ValueError, OverflowError):
            if ctp_blocker is not None:
                return _snapshot("CTP_MISMATCH", ctp_blocker, base, broker)
            return _snapshot("UNKNOWN", "POSITION_BOOK_UNAVAILABLE", base, None)

        if current is not None and current["last_callback_at_ns"] is not None:
            if int(current["last_callback_at_ns"]) > snapshot_time_ns:
                return _snapshot(
                    "UNKNOWN",
                    "POSITION_CALLBACK_AFTER_SNAPSHOT",
                    base,
                    broker,
                    **_current_attribution(current, opening),
                )

        if grid_cursor is not None:
            try:
                cursor_time_ns = _close_time_to_ns(grid_cursor["close_time"])
            except (TypeError, ValueError, OverflowError):
                return _snapshot(
                    "UNKNOWN",
                    "POSITION_GRID_CURSOR_UNAVAILABLE",
                    base,
                    broker,
                    **_current_attribution(current, opening),
                )
            if cursor_time_ns > snapshot_time_ns:
                return _snapshot(
                    "UNKNOWN",
                    "POSITION_GRID_CURSOR_AHEAD_OF_SNAPSHOT",
                    base,
                    broker,
                    **_current_attribution(current, opening),
                )

        if ctp_blocker is not None:
            is_overfill_owner = bool(
                current is not None
                and opening is not None
                and current["state"] == "UNKNOWN"
                and current["blocker_code"] == "OPEN_INTENT_QUANTITY_EXCEEDED"
                and (
                    active_issue is None
                    or active_issue["blocker_code"] == "OPEN_INTENT_QUANTITY_EXCEEDED"
                )
                and current["strategy_scope"] == strategy_scope
                and _opening_matches_current(
                    opening,
                    current,
                    account_scope=account_scope,
                    instrument=instrument,
                    exchange=exchange,
                )
            )
            if is_overfill_owner:
                return _snapshot(
                    "UNKNOWN",
                    "OPEN_INTENT_QUANTITY_EXCEEDED",
                    base,
                    broker,
                    **_current_attribution(current, opening),
                )
            return _snapshot("CTP_MISMATCH", ctp_blocker, base, broker)

        if active_issue is not None:
            return _snapshot(
                "UNKNOWN",
                active_issue["blocker_code"],
                base,
                broker,
                **_current_attribution(current, opening),
            )
        pending_id = None if pending_owner is None else pending_owner["owner_intent_id"]
        same_pending_open = (
            current is not None
            and current["state"] in ("ACTIVE", "UNKNOWN")
            and pending_id is not None
            and current["owner_intent_id"] == pending_id
        )
        if pending_id is not None and not same_pending_open:
            return _snapshot(
                "UNKNOWN",
                "INSTRUMENT_ORDER_UNRESOLVED",
                base,
                broker,
                **_current_attribution(current, opening),
            )

        if current is None:
            if broker == 0:
                return _snapshot("FLAT", None, base, Decimal(0))
            return _snapshot("UNKNOWN", "POSITION_OWNERSHIP_UNPROVEN", base, broker)

        try:
            current_quantity = _current_signed_quantity(current)
        except FactorPositionBookError as error:
            return _snapshot(
                "UNKNOWN", error.code, base, broker, **_current_attribution(current, opening)
            )
        if current["state"] == "FLAT":
            if broker == 0:
                return _snapshot("FLAT", None, base, Decimal(0))
            return _snapshot(
                "BROKER_MISMATCH",
                "POSITION_BOOK_BROKER_MISMATCH",
                base,
                broker,
            )
        if opening is None or not _opening_matches_current(
            opening, current, account_scope=account_scope, instrument=instrument, exchange=exchange
        ):
            return _snapshot("UNKNOWN", "POSITION_OWNER_EVIDENCE_UNAVAILABLE", base, broker)
        attribution = _current_attribution(current, opening)
        if current_quantity == 0:
            return _snapshot(
                "UNKNOWN",
                current["blocker_code"] or "POSITION_ZERO_RESIDUAL_UNRECONCILED",
                base,
                broker,
                **attribution,
            )
        if current_quantity != broker:
            return _snapshot(
                "BROKER_MISMATCH",
                "POSITION_BOOK_BROKER_MISMATCH",
                base,
                broker,
            )
        if current["strategy_scope"] != strategy_scope:
            return _snapshot("FOREIGN_OWNER", "POSITION_OWNED_BY_OTHER_STRATEGY", base, broker)
        if current["state"] == "UNKNOWN":
            return _snapshot(
                "UNKNOWN",
                current["blocker_code"] or "POSITION_ATTRIBUTION_UNCERTAIN",
                base,
                broker,
                **attribution,
            )
        if current["state"] != "ACTIVE":
            return _snapshot("UNKNOWN", "POSITION_PROJECTION_STATE_INVALID", base, broker)
        if (
            current["first_fill_at_ns"] is not None
            and int(current["first_fill_at_ns"]) > snapshot_time_ns
        ):
            return _snapshot("UNKNOWN", "POSITION_FILL_AFTER_SNAPSHOT", base, broker, **attribution)

        if attribution["stop_price"] is None or attribution["risk_policy"] is None:
            return _snapshot(
                "RISK_METADATA_MISSING",
                "POSITION_RISK_METADATA_UNAVAILABLE",
                base,
                broker,
                **attribution,
            )
        if (
            not current["fill_time_complete"]
            or current["first_fill_at_ns"] is None
            or current["first_fill_grid_ordinal"] is None
        ):
            return _snapshot(
                "UNKNOWN",
                "POSITION_GRID_ANCHOR_UNAVAILABLE",
                base,
                broker,
                **attribution,
            )
        if grid_cursor is None:
            return _snapshot(
                "UNKNOWN",
                "POSITION_GRID_CURSOR_UNAVAILABLE",
                base,
                broker,
                **attribution,
            )
        cursor_ordinal = grid_cursor["ordinal"]
        anchor_ordinal = current["first_fill_grid_ordinal"]
        if (
            type(cursor_ordinal) is not int
            or type(anchor_ordinal) is not int
            or cursor_ordinal < anchor_ordinal
        ):
            return _snapshot(
                "UNKNOWN",
                "POSITION_GRID_CURSOR_UNAVAILABLE",
                base,
                broker,
                **attribution,
            )
        return _snapshot(
            "MATCHED",
            None,
            base,
            broker,
            held_eligible_bars=max(0, cursor_ordinal - anchor_ordinal),
            **{key: value for key, value in attribution.items() if key != "held_eligible_bars"},
        )


def _record_position_issue(
    cursor: sqlite3.Cursor,
    receipt: sqlite3.Row,
    *,
    account_scope: str,
    instrument: str,
    exchange: Optional[str],
    blocker_code: str,
    execution_id: Optional[str] = None,
) -> FactorPositionApplyResult:
    """Persist contradictory or incomplete fill evidence without adopting it."""

    if not _is_identifier(account_scope) or not _is_identifier(instrument):
        raise FactorPositionBookError("POSITION_ISSUE_SCOPE_UNAVAILABLE")
    if exchange is not None and not _is_identifier(exchange):
        exchange = None
    if not _is_identifier(blocker_code):
        raise FactorPositionBookError("INVALID_POSITION_ISSUE_CODE")
    evidence_text = receipt["evidence_payload_json"]
    digest = hashlib.sha256(evidence_text.encode("utf-8")).hexdigest()
    values = (
        receipt["receipt_id"],
        receipt["intent_id"],
        account_scope,
        instrument,
        exchange,
        blocker_code,
        digest,
        int(receipt["created_at_ns"]),
    )
    existing = cursor.execute(
        "SELECT * FROM factor_position_evidence_issues WHERE receipt_id=?",
        (receipt["receipt_id"],),
    ).fetchone()
    if existing is None:
        cursor.execute(
            """INSERT INTO factor_position_evidence_issues
               (receipt_id, intent_id, account_scope, instrument, exchange,
                blocker_code, evidence_sha256, created_at_ns)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            values,
        )
    elif (
        tuple(
            existing[name]
            for name in (
                "receipt_id",
                "intent_id",
                "account_scope",
                "instrument",
                "exchange",
                "blocker_code",
                "evidence_sha256",
                "created_at_ns",
            )
        )
        != values
    ):
        raise FactorPositionBookError("POSITION_ISSUE_CONFLICT")
    created_at_ns = int(receipt["created_at_ns"])
    exchange_key = exchange or _UNKNOWN_EXCHANGE_KEY
    current = None
    activate = True
    if exchange is not None:
        current = cursor.execute(
            """SELECT flat_checkpoint_ns FROM factor_position_current
               WHERE account_scope=? AND instrument=? AND exchange=?""",
            (account_scope, instrument, exchange),
        ).fetchone()
        if (
            current is not None
            and current["flat_checkpoint_ns"] is not None
            and created_at_ns < int(current["flat_checkpoint_ns"])
        ):
            # A delayed replay of an old issue cannot reopen a closed epoch.
            activate = False
    current_issue = None
    if activate:
        current_issue = cursor.execute(
            """SELECT created_at_ns FROM factor_position_active_issues
               WHERE account_scope=? AND instrument=? AND exchange_key=?""",
            (account_scope, instrument, exchange_key),
        ).fetchone()
    if activate and (current_issue is None or int(current_issue["created_at_ns"]) <= created_at_ns):
        cursor.execute(
            """INSERT INTO factor_position_active_issues
               (account_scope,instrument,exchange_key,receipt_id,blocker_code,created_at_ns)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(account_scope,instrument,exchange_key) DO UPDATE SET
                 receipt_id=excluded.receipt_id,blocker_code=excluded.blocker_code,
                 created_at_ns=excluded.created_at_ns""",
            (
                account_scope,
                instrument,
                exchange_key,
                receipt["receipt_id"],
                blocker_code,
                created_at_ns,
            ),
        )
    if exchange is not None and activate:
        if current is None:
            cursor.execute(
                """INSERT INTO factor_position_current
                   (account_scope,instrument,exchange,state,blocker_code,epoch,updated_at_ns)
                   VALUES(?,?,?,'UNKNOWN',?,0,?)""",
                (account_scope, instrument, exchange, blocker_code, created_at_ns),
            )
        elif current["flat_checkpoint_ns"] is None or created_at_ns >= int(
            current["flat_checkpoint_ns"]
        ):
            active = cursor.execute(
                """SELECT blocker_code FROM factor_position_active_issues
                   WHERE account_scope=? AND instrument=? AND exchange_key=?""",
                (account_scope, instrument, exchange_key),
            ).fetchone()
            cursor.execute(
                """UPDATE factor_position_current SET state='UNKNOWN',blocker_code=?,
                          updated_at_ns=?
                   WHERE account_scope=? AND instrument=? AND exchange=?""",
                (
                    blocker_code if active is None else active["blocker_code"],
                    created_at_ns,
                    account_scope,
                    instrument,
                    exchange,
                ),
            )
    return _blocked_apply(receipt["receipt_id"], receipt["intent_id"], blocker_code, execution_id)


def _blocked_apply(
    receipt_id: str,
    intent_id: str,
    code: str,
    execution_id: Optional[str] = None,
) -> FactorPositionApplyResult:
    return FactorPositionApplyResult("BLOCKED", receipt_id, execution_id, intent_id, code)


def _latest_confirmed_flat_checkpoint(
    rows: Sequence[sqlite3.Row],
    *,
    account_scope: str,
    instrument: str,
    exchange: str,
) -> Optional[int]:
    checkpoints = []
    for row in rows:
        if (
            row["account_scope"] != account_scope
            or row["instrument"] != instrument
            or int(row["position_flat"]) != 1
        ):
            raise FactorPositionBookError("POSITION_FLAT_CHECKPOINT_INVALID")
        try:
            economics = json.loads(row["economic_payload_json"])
        except (TypeError, ValueError) as error:
            raise FactorPositionBookError("POSITION_FLAT_CHECKPOINT_INVALID") from error
        if not isinstance(economics, Mapping) or not _is_identifier(economics.get("exchange")):
            raise FactorPositionBookError("POSITION_FLAT_CHECKPOINT_INVALID")
        if economics["exchange"] != exchange:
            continue
        if (
            row["intent_state"] != "KNOWN"
            or row["dispatch_state"] != "KNOWN"
            or row["reconciliation_state"] != "KNOWN"
            or row["reconciliation_terminal_state"] != row["terminal_state"]
            or row["reconciliation_terminal_event_id"] != row["terminal_event_id"]
            or row["reconciliation_snapshot_id"] != row["position_snapshot_id"]
            or row["reconciliation_position_flat"] is None
            or int(row["reconciliation_position_flat"]) != 1
        ):
            raise FactorPositionBookError("POSITION_FLAT_CHECKPOINT_INVALID")
        created_at_ns = row["created_at_ns"]
        if type(created_at_ns) is not int or created_at_ns <= 0:
            raise FactorPositionBookError("POSITION_FLAT_CHECKPOINT_INVALID")
        checkpoints.append(created_at_ns)
    return max(checkpoints) if checkpoints else None


def _snapshot(
    status: str,
    blocker_code: Optional[str],
    base: Mapping[str, Any],
    signed_quantity: Optional[Decimal],
    **values: Any,
) -> FactorPositionAttributionSnapshot:
    return FactorPositionAttributionSnapshot(
        status=status,
        blocker_code=blocker_code,
        signed_quantity=signed_quantity,
        **dict(base),
        **values,
    )


def _opening_values(row: sqlite3.Row) -> Tuple[Any, ...]:
    return tuple(
        row[name]
        for name in (
            "account_scope",
            "strategy_scope",
            "instrument",
            "exchange",
            "position_side",
            "stop_price",
            "risk_policy_id",
            "risk_policy_json",
            "cohort_id",
            "batch_id",
            "close_time",
            "decision_grid_ordinal",
        )
    )


def _fill_values(row: sqlite3.Row) -> Tuple[Any, ...]:
    return tuple(
        row[name]
        for name in (
            "account_scope",
            "instrument",
            "exchange",
            "execution_id",
            "receipt_id",
            "intent_id",
            "strategy_scope",
            "position_effect",
            "order_side",
            "owner_intent_id",
            "quantity",
            "price",
            "fee",
            "filled_at_ns",
            "payload_sha256",
        )
    )


def _fill_identity_values(row: sqlite3.Row) -> Tuple[Any, ...]:
    return tuple(
        row[name]
        for name in (
            "account_scope",
            "instrument",
            "exchange",
            "execution_id",
            "intent_id",
            "strategy_scope",
            "position_effect",
            "order_side",
            "owner_intent_id",
            "quantity",
            "price",
            "fee",
            "filled_at_ns",
            "payload_sha256",
        )
    )


def _fill_identity_values_from_values(values: Tuple[Any, ...]) -> Tuple[Any, ...]:
    # ``fill_values`` includes receipt_id after execution_id; the execution
    # identity deliberately excludes that field so a repeated provider trade
    # delivered under a later callback ID remains an idempotent replay.
    return values[:4] + values[5:]


def _parse_decimal(
    value: Any,
    *,
    positive: bool = False,
    nonnegative: Optional[bool] = None,
) -> Optional[Decimal]:
    if type(value) is bool or value is None:
        return None
    if isinstance(value, Decimal):
        result = value
    elif type(value) in (str, int):
        try:
            text = str(value)
        except (ValueError, OverflowError):
            return None
        if len(text) > 256:
            return None
        if not _DECIMAL_TEXT.fullmatch(text):
            return None
        try:
            result = Decimal(text)
        except InvalidOperation:
            return None
    else:
        return None
    if not result.is_finite():
        return None
    _sign, digits, exponent = result.as_tuple()
    normalized_digits = digits
    normalized_exponent = exponent
    while (
        len(normalized_digits) > _MAX_DECIMAL_DIGITS
        and normalized_digits
        and normalized_digits[-1] == 0
    ):
        normalized_digits = normalized_digits[:-1]
        normalized_exponent += 1
    if (
        len(normalized_digits) > _MAX_DECIMAL_DIGITS
        or abs(normalized_exponent) > _MAX_DECIMAL_EXPONENT
    ):
        return None
    if positive and result <= 0:
        return None
    if nonnegative is True and result < 0:
        return None
    if nonnegative is False and result < 0:
        # Signed position quantities are valid; this parameter explicitly
        # allows their negative direction.
        return result
    return result


def _parse_accumulator_decimal(
    value: Any,
    *,
    positive: bool = False,
    nonnegative: Optional[bool] = None,
) -> Optional[Decimal]:
    """Parse a persisted exact aggregate under its wider explicit bound."""

    if type(value) is bool or value is None:
        return None
    if isinstance(value, Decimal):
        result = value
    elif type(value) in (str, int):
        try:
            text = str(value)
        except (ValueError, OverflowError):
            return None
        max_text = _MAX_POSITION_ACCUMULATOR_DIGITS + _MAX_POSITION_ACCUMULATOR_EXPONENT + 32
        if len(text) > max_text or not _DECIMAL_TEXT.fullmatch(text):
            return None
        try:
            result = Decimal(text)
        except InvalidOperation:
            return None
    else:
        return None
    if not result.is_finite():
        return None
    _sign, digits, exponent = result.as_tuple()
    if (
        len(digits) > _MAX_POSITION_ACCUMULATOR_DIGITS
        or type(exponent) is not int
        or abs(exponent) > _MAX_POSITION_ACCUMULATOR_EXPONENT
    ):
        return None
    if positive and result <= 0:
        return None
    if nonnegative is True and result < 0:
        return None
    if nonnegative is False and result < 0:
        return result
    return result


def _serialize_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _decimal_add(left: Decimal, right: Decimal) -> Decimal:
    left_coefficient, left_exponent = _decimal_parts_for_accumulation(left)
    right_coefficient, right_exponent = _decimal_parts_for_accumulation(right)
    if left_coefficient == 0:
        return right
    if right_coefficient == 0:
        return left
    exponent = min(left_exponent, right_exponent)
    left_shift = left_exponent - exponent
    right_shift = right_exponent - exponent
    left_width = len(str(abs(left_coefficient))) + left_shift
    right_width = len(str(abs(right_coefficient))) + right_shift
    if max(left_width, right_width) > _MAX_POSITION_ACCUMULATOR_DIGITS:
        raise FactorPositionBookError("POSITION_DECIMAL_ACCUMULATOR_LIMIT")
    total = left_coefficient * (10**left_shift) + right_coefficient * (10**right_shift)
    return _decimal_from_accumulator_parts(total, exponent)


def _decimal_multiply(left: Decimal, right: Decimal) -> Decimal:
    left_coefficient, left_exponent = _decimal_parts_for_accumulation(left)
    right_coefficient, right_exponent = _decimal_parts_for_accumulation(right)
    exponent = left_exponent + right_exponent
    if abs(exponent) > _MAX_POSITION_ACCUMULATOR_EXPONENT:
        raise FactorPositionBookError("POSITION_DECIMAL_ACCUMULATOR_LIMIT")
    return _decimal_from_accumulator_parts(left_coefficient * right_coefficient, exponent)


def _decimal_divide(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = _DECIMAL_DIVISION_PRECISION
        return left / right


def _decimal_parts_for_accumulation(value: Decimal) -> Tuple[int, int]:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise FactorPositionBookError("POSITION_PROJECTION_CORRUPT")
    sign, digits, exponent = value.as_tuple()
    if (
        type(exponent) is not int
        or len(digits) > _MAX_POSITION_ACCUMULATOR_DIGITS
        or abs(exponent) > _MAX_POSITION_ACCUMULATOR_EXPONENT
    ):
        raise FactorPositionBookError("POSITION_DECIMAL_ACCUMULATOR_LIMIT")
    coefficient = int("".join(str(digit) for digit in digits) or "0")
    return (-coefficient if sign else coefficient), exponent


def _decimal_from_accumulator_parts(coefficient: int, exponent: int) -> Decimal:
    if abs(exponent) > _MAX_POSITION_ACCUMULATOR_EXPONENT:
        raise FactorPositionBookError("POSITION_DECIMAL_ACCUMULATOR_LIMIT")
    if coefficient == 0:
        return Decimal(0)
    digits_text = str(abs(coefficient))
    if len(digits_text) > _MAX_POSITION_ACCUMULATOR_DIGITS:
        raise FactorPositionBookError("POSITION_DECIMAL_ACCUMULATOR_LIMIT")
    digits = tuple(ord(character) - ord("0") for character in digits_text)
    return Decimal((1 if coefficient < 0 else 0, digits, exponent))


def _require_identifier(value: Any, code: str) -> None:
    if not _is_identifier(value):
        raise FactorPositionBookError(code)


def _is_identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(_IDENTIFIER.fullmatch(value))


def _require_close_time(value: Any) -> None:
    if not isinstance(value, str):
        raise FactorPositionBookError("INVALID_GRID_CLOSE_TIME")
    try:
        _close_time_to_ns(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise FactorPositionBookError("INVALID_GRID_CLOSE_TIME") from error


def _close_time_to_ns(value: str) -> int:
    if not isinstance(value, str):
        raise ValueError("close time must be text")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("close time must include timezone")
    parsed = parsed.astimezone(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = parsed - epoch
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


def _datetime_to_ns(value: datetime) -> int:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("snapshot time must be timezone-aware")
    normalized = value.astimezone(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = normalized - epoch
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise FactorPositionBookError("POSITION_METADATA_INVALID") from error


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})


def _freeze_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _freeze_mapping(value)
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    return value
