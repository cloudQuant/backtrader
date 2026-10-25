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
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from types import MappingProxyType
from typing import Any, Mapping, Optional, Sequence, Tuple

from .execution_durable_capacity import track_durable_row_change


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")
_DECIMAL_TEXT = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_DECIMAL_DIVISION_PRECISION = 256
_MAX_DECIMAL_DIGITS = 128
_MAX_DECIMAL_EXPONENT = 128
_MAX_POSITION_ACCUMULATOR_DIGITS = 1024
_MAX_POSITION_ACCUMULATOR_EXPONENT = 512
_POSITION_BOOK_SCHEMA_VERSION = 6
_POSITION_BOOK_FILL_TOTALS_VERSION = 5
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


@dataclass(frozen=True)
class FactorDatedTradeReconciliationItem:
    """Result for binding one complete-query CTP trade row to a journal fill."""

    observation_id: str
    status: str
    intent_id: Optional[str] = None
    receipt_id: Optional[str] = None
    execution_id: Optional[str] = None
    blocker_code: Optional[str] = None


@dataclass(frozen=True)
class FactorDatedTradeReconciliationPage:
    """Bounded, immutable result of the dated-trade metadata append pass."""

    items: Tuple[FactorDatedTradeReconciliationItem, ...]
    observation_count: int
    offset: int
    next_offset: Optional[int]
    truncated: bool


@dataclass(frozen=True)
class FactorDatedPositionLot:
    """One journal OPEN fill and its deterministic dated CLOSE allocation.

    CTP identifies the CLOSE offset and date bucket, not the exact OPEN fill
    consumed. ``close_execution_ids`` therefore records a FIFO accounting
    allocation among eligible owned fills, not provider-specified lot linkage.
    """

    execution_id: str
    intent_id: str
    owner_intent_id: str
    strategy_scope: str
    trading_day: str
    position_side: str
    hedge_flag: str
    opened_quantity: Decimal
    closed_quantity: Decimal
    remaining_quantity: Decimal
    open_observation_id: str
    open_snapshot_id: str
    open_query_set_id: str
    close_execution_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class FactorDatedPositionBucket:
    """Fill-derived ownership compared with one current CTP date bucket."""

    position_side: str
    hedge_flag: str
    position_date: str
    trading_day: str
    provider_quantity: Decimal
    owned_quantity: Decimal
    available_quantity: Optional[Decimal]
    owner_strategy_scope: Optional[str]
    owner_intent_id: Optional[str]
    source_row_ids: Tuple[str, ...]
    opening_execution_ids: Tuple[str, ...]
    close_execution_ids: Tuple[str, ...]
    lots: Tuple[FactorDatedPositionLot, ...]
    ready: bool
    blockers: Tuple[str, ...] = ()


@dataclass(frozen=True)
class FactorDatedPositionProof:
    """Read-only, query-bound proof of current owned TODAY/HISTORY buckets."""

    status: str
    blocker_code: Optional[str]
    account_scope: str
    strategy_scope: str
    target_id: str
    instrument: str
    exchange: str
    query_set_id: Optional[str]
    account_fingerprint: Optional[str]
    connection_generation: Optional[int]
    trading_day: Optional[str]
    snapshot_id: Optional[str]
    available_at: Optional[datetime]
    source_row_ids: Tuple[str, ...]
    buckets: Tuple[FactorDatedPositionBucket, ...]
    ready: bool
    blockers: Tuple[str, ...] = ()


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
        _create_dated_trade_schema(cursor)
        _ensure_grid_time_index(cursor)
        _create_position_projection_schema(cursor)
        _create_position_history_guards(cursor)
        if meta is None:
            cursor.execute("INSERT INTO factor_position_book_meta(singleton, version) VALUES(1, 0)")
            meta_version = 0
        else:
            meta_version = int(meta[0])
        if meta_version < _POSITION_BOOK_SCHEMA_VERSION:
            if meta_version < _POSITION_BOOK_FILL_TOTALS_VERSION:
                _migrate_open_intent_fill_totals(cursor)
            if 0 < meta_version < _POSITION_BOOK_FILL_TOTALS_VERSION:
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


def _create_dated_trade_schema(cursor: sqlite3.Cursor) -> None:
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS factor_position_dated_trade_facts (
            account_scope TEXT NOT NULL,
            instrument TEXT NOT NULL,
            exchange TEXT NOT NULL,
            execution_id TEXT NOT NULL,
            receipt_id TEXT NOT NULL REFERENCES execution_decision_callbacks(receipt_id),
            intent_id TEXT NOT NULL REFERENCES execution_decision_intents(intent_id),
            owner_intent_id TEXT NOT NULL,
            strategy_scope TEXT NOT NULL,
            position_effect TEXT NOT NULL CHECK(position_effect IN ('OPEN','CLOSE')),
            order_side TEXT NOT NULL CHECK(order_side IN ('BUY','SELL')),
            position_side TEXT NOT NULL CHECK(position_side IN ('LONG','SHORT')),
            hedge_flag TEXT NOT NULL CHECK(hedge_flag IN ('1','2','3','5')),
            offset_flag TEXT NOT NULL CHECK(offset_flag IN ('0','1','2','3','4','5','6')),
            quantity TEXT NOT NULL,
            price TEXT NOT NULL,
            trading_day TEXT NOT NULL CHECK(length(trading_day)=8),
            trade_date TEXT NOT NULL CHECK(length(trade_date)=8),
            trade_time TEXT NOT NULL,
            trade_time_ns INTEGER NOT NULL CHECK(trade_time_ns > 0),
            order_ref TEXT NOT NULL,
            order_sys_id TEXT,
            observation_id TEXT NOT NULL,
            query_set_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            request_id INTEGER NOT NULL CHECK(request_id > 0),
            connection_generation INTEGER NOT NULL CHECK(connection_generation > 0),
            account_fingerprint TEXT NOT NULL,
            available_at_ns INTEGER NOT NULL CHECK(available_at_ns > 0),
            payload_sha256 TEXT NOT NULL,
            PRIMARY KEY(account_scope,instrument,exchange,execution_id),
            FOREIGN KEY(account_scope,instrument,exchange,execution_id)
                REFERENCES factor_position_fills(account_scope,instrument,exchange,execution_id)
        )"""
    )


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
        """SELECT rowid,account_scope,strategy_scope,cohort_id,ordinal,close_time
           FROM factor_position_grid_history WHERE close_time_ns IS NULL"""
    )
    for row in rows:
        try:
            close_time_ns = _close_time_to_ns(row["close_time"])
        except (TypeError, ValueError, OverflowError):
            continue
        key = (row["account_scope"], row["strategy_scope"], row["cohort_id"], row["ordinal"])
        with track_durable_row_change(cursor, "factor_position_grid_history", key, "SETTLEMENT"):
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
        with track_durable_row_change(
            cursor, "factor_position_open_intent_totals", (current_id,), "SETTLEMENT"
        ):
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
                position_key = (account_scope, instrument, exchange)
                with track_durable_row_change(
                    cursor, "factor_position_current", position_key, "SETTLEMENT"
                ):
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

    rows = cursor.execute(
        """SELECT account_scope,instrument,exchange FROM factor_position_current
           WHERE owner_intent_id IS NOT NULL AND state IN ('ACTIVE','UNKNOWN')"""
    ).fetchall()
    for row in rows:
        key = (row["account_scope"], row["instrument"], row["exchange"])
        with track_durable_row_change(cursor, "factor_position_current", key, "SETTLEMENT"):
            cursor.execute(
                """UPDATE factor_position_current
                   SET opening_fee_unknown_count=MAX(opening_fee_unknown_count,1),
                       fill_time_complete=0,
                       fill_time_unknown_count=MAX(fill_time_unknown_count,1),
                       first_fill_at_ns=NULL,first_fill_grid_ordinal=NULL
                   WHERE account_scope=? AND instrument=? AND exchange=?
                     AND owner_intent_id IS NOT NULL AND state IN ('ACTIVE','UNKNOWN')""",
                key,
            )


def _create_position_history_guards(cursor: sqlite3.Cursor) -> None:
    statements = (
        "CREATE INDEX IF NOT EXISTS factor_position_fills_by_intent ON factor_position_fills(intent_id, position_effect, filled_at_ns)",
        "CREATE INDEX IF NOT EXISTS factor_position_fills_by_owner ON factor_position_fills(owner_intent_id, position_effect, filled_at_ns)",
        "CREATE INDEX IF NOT EXISTS factor_position_issues_by_position ON factor_position_evidence_issues(account_scope, instrument, exchange)",
        """CREATE INDEX IF NOT EXISTS factor_position_dated_trades_by_owner
           ON factor_position_dated_trade_facts
             (account_scope,instrument,exchange,owner_intent_id,position_effect,
              trading_day,trade_time_ns,execution_id)""",
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
        """CREATE TRIGGER IF NOT EXISTS factor_position_dated_trade_no_update
            BEFORE UPDATE ON factor_position_dated_trade_facts
            BEGIN SELECT RAISE(ABORT, 'factor dated trade facts are append only'); END""",
        """CREATE TRIGGER IF NOT EXISTS factor_position_dated_trade_no_delete
            BEFORE DELETE ON factor_position_dated_trade_facts
            BEGIN SELECT RAISE(ABORT, 'factor dated trade facts are append only'); END""",
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
        position_key = (row["account_scope"], row["instrument"], row["exchange"])
        with track_durable_row_change(
            cursor, "factor_position_current", position_key, "SETTLEMENT"
        ):
            cursor.execute(
                """INSERT OR IGNORE INTO factor_position_current
                   (account_scope,instrument,exchange,state,blocker_code,epoch,updated_at_ns)
                   VALUES(?,?,?,'UNKNOWN','POSITION_PROJECTION_REQUIRES_RECONCILIATION',0,0)""",
                position_key,
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
        issue_key = (row["account_scope"], row["instrument"], exchange_key)
        with track_durable_row_change(
            cursor, "factor_position_active_issues", issue_key, "SETTLEMENT"
        ):
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
    capacity_class: str = "BASE",
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
    with track_durable_row_change(
        cursor,
        "factor_position_grid_history",
        (account_scope, strategy_scope, cohort_id, ordinal),
        capacity_class,
    ):
        cursor.execute(
            """INSERT INTO factor_position_grid_history
               (account_scope, strategy_scope, cohort_id, ordinal, batch_id, close_time,
                close_time_ns)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                account_scope,
                strategy_scope,
                cohort_id,
                ordinal,
                batch_id,
                close_time,
                close_time_ns,
            ),
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
                  i.original_identity_json,i.provider_identity_json AS intent_provider_identity_json,
                  i.outcome_code AS intent_outcome_code,
                  i.dispatch_result_json AS intent_dispatch_result_json,
                  d.business_key_json,q.state AS reconciliation_state,
                  q.outcome_code AS reconciliation_outcome_code,
                  q.provider_identity_json AS reconciliation_provider_identity_json,
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
        original_identity = json.loads(row["original_identity_json"])
        provider_identity = json.loads(row["reconciliation_provider_identity_json"])
    except (TypeError, ValueError) as error:
        raise FactorPositionBookError("POSITION_FLAT_CHECKPOINT_INVALID") from error
    if not all(
        isinstance(value, Mapping)
        for value in (key, business, economics, original_identity, provider_identity)
    ):
        raise FactorPositionBookError("POSITION_FLAT_CHECKPOINT_INVALID")
    account_scope = row["account_scope"]
    instrument = row["instrument"]
    exchange = economics.get("exchange")
    terminal = row["terminal_state"]
    created_at_ns = row["created_at_ns"]
    no_fill_terminal = {
        "5": ("CANCELED", "CANCELLED"),
        "4": ("NO_TRADE_NOT_QUEUEING", "REJECTED"),
    }.get(provider_identity.get("terminal_status"))
    volume_total_original = _parse_decimal(
        provider_identity.get("volume_total_original"), positive=True
    )
    volume_traded = _parse_decimal(provider_identity.get("volume_traded"), nonnegative=True)
    volume_total = _parse_decimal(provider_identity.get("volume_total"), nonnegative=True)
    requested_quantity = _parse_decimal(economics.get("quantity"), positive=True)
    expected_query_families = (
        "account_result",
        "orders_result",
        "trades_result",
        "instruments_result",
        "positions_result",
    )
    query_family_ids = provider_identity.get("query_family_request_ids")
    query_families_valid = bool(
        isinstance(query_family_ids, (tuple, list))
        and len(query_family_ids) == len(expected_query_families)
        and all(
            isinstance(item, (tuple, list))
            and len(item) == 2
            and item[0] == expected_query_families[index]
            and type(item[1]) is int
            and item[1] > 0
            for index, item in enumerate(query_family_ids)
        )
        and len({item[1] for item in query_family_ids}) == len(expected_query_families)
        and dict(query_family_ids).get("orders_result")
        == provider_identity.get("orders_request_id")
    )
    dispatching_crash_no_fill = bool(
        row["dispatch_state"] is None
        and row["intent_state"] == "KNOWN"
        and row["intent_provider_identity_json"] is None
        and row["intent_outcome_code"] is None
        and row["intent_dispatch_result_json"] is None
        and row["reconciliation_outcome_code"]
        == "complete_orders_query_dispatching_no_fill_terminal"
        and provider_identity.get("evidence_kind")
        == "complete_orders_query_dispatching_no_fill_terminal"
        and key.get("action") == "SUBMIT"
        and key.get("position_effect") == "OPEN"
        and original_identity.get("operation") == "insert"
        and original_identity.get("instrument_id") == instrument
        and original_identity.get("exchange_id") == exchange
        and original_identity.get("order_ref") == provider_identity.get("order_ref")
        and original_identity.get("account_fingerprint")
        == provider_identity.get("original_account_fingerprint")
        and original_identity.get("trading_day") == provider_identity.get("original_trading_day")
        and original_identity.get("front_id") == provider_identity.get("original_front_id")
        and original_identity.get("session_id") == provider_identity.get("original_session_id")
        and original_identity.get("connection_generation")
        == provider_identity.get("original_connection_generation")
        and provider_identity.get("intent_id") == intent_id
        and provider_identity.get("instrument") == instrument
        and provider_identity.get("exchange") == exchange
        and provider_identity.get("account_scope") == business.get("account_scope")
        and provider_identity.get("strategy_scope") == business.get("strategy_scope")
        and provider_identity.get("account_fingerprint")
        == original_identity.get("account_fingerprint")
        and provider_identity.get("trading_day") == original_identity.get("trading_day")
        and provider_identity.get("original_trading_day") == original_identity.get("trading_day")
        and type(provider_identity.get("connection_generation")) is int
        and provider_identity.get("connection_generation") > 0
        and type(provider_identity.get("matching_trade_count")) is int
        and provider_identity.get("matching_trade_count") == 0
        and query_families_valid
        and _is_identifier(provider_identity.get("query_set_id"))
        and _is_identifier(provider_identity.get("snapshot_id"))
        and type(provider_identity.get("orders_request_id")) is int
        and provider_identity.get("orders_request_id") > 0
        and provider_identity.get("position_flat") is True
        and provider_identity.get("position_snapshot_id") == row["position_snapshot_id"]
        and provider_identity.get("terminal_event_id") == row["terminal_event_id"]
        and provider_identity.get("observation_id") == row["terminal_event_id"]
        and no_fill_terminal is not None
        and no_fill_terminal[0] == provider_identity.get("terminal_state")
        and no_fill_terminal[1] == terminal
        and volume_total_original is not None
        and volume_total_original == volume_total_original.to_integral_value()
        and volume_traded == 0
        and volume_total == volume_total_original
        and requested_quantity == volume_total_original
        and provider_identity.get("broker_quantity") == "0"
        and provider_identity.get("ctp_long_quantity") == "0"
        and provider_identity.get("ctp_short_quantity") == "0"
        and (
            original_identity.get("order_sys_id") is None
            or original_identity.get("order_sys_id") == provider_identity.get("order_sys_id")
        )
    )
    if (
        row["intent_id"] != intent_id
        or row["reconciliation_id"] != reconciliation_id
        or row["joined_reconciliation_id"] != reconciliation_id
        or row["intent_state"] != "KNOWN"
        or (row["dispatch_state"] not in ("KNOWN", "UNKNOWN") and not dispatching_crash_no_fill)
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
        with track_durable_row_change(
            cursor,
            "factor_position_active_issues",
            (account_scope, instrument, exchange),
            "SETTLEMENT",
        ):
            cursor.execute(
                """DELETE FROM factor_position_active_issues
                   WHERE account_scope=? AND instrument=? AND exchange_key=?""",
                (account_scope, instrument, exchange),
            )
        active_issue = None
    next_epoch = 1 if current is None else int(current["epoch"]) + 1
    state = "UNKNOWN" if active_issue is not None else "FLAT"
    blocker = active_issue["blocker_code"] if active_issue is not None else None
    with track_durable_row_change(
        cursor, "factor_position_current", (account_scope, instrument, exchange), "SETTLEMENT"
    ):
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
            with track_durable_row_change(
                cursor, "factor_position_openings", (intent["intent_id"],), "SETTLEMENT"
            ):
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
    fill_key = (account_scope, instrument, exchange, execution_id)
    with track_durable_row_change(cursor, "factor_position_fills", fill_key, "SETTLEMENT"):
        cursor.execute(
            """INSERT INTO factor_position_fills
               (account_scope, instrument, exchange, execution_id, receipt_id, intent_id,
                strategy_scope, position_effect, order_side, owner_intent_id, quantity,
                price, fee, filled_at_ns, payload_sha256)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            fill_values,
        )
    with track_durable_row_change(
        cursor, "factor_position_fill_attributes", fill_key, "SETTLEMENT"
    ):
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
            with track_durable_row_change(
                cursor, "factor_position_fill_attributes", fill_key, "SETTLEMENT"
            ):
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
    with track_durable_row_change(
        cursor, "factor_position_open_intent_totals", (intent_id,), "SETTLEMENT"
    ):
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
        with track_durable_row_change(
            cursor, "factor_position_fill_attributes", identity, "SETTLEMENT"
        ):
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
        with track_durable_row_change(
            cursor, "factor_position_fill_attributes", identity, "SETTLEMENT"
        ):
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
    with track_durable_row_change(cursor, "factor_position_current", identity[:3], "SETTLEMENT"):
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
        with track_durable_row_change(
            cursor, "factor_position_current", (account_scope, instrument, exchange), "SETTLEMENT"
        ):
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
    with track_durable_row_change(
        cursor, "factor_position_current", (account_scope, instrument, exchange), "SETTLEMENT"
    ):
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

    def reconcile_dated_trade_observations(
        self,
        facts: Any,
        *,
        reconciliation_page: Any,
        limit: int = 512,
        offset: int = 0,
    ) -> FactorDatedTradeReconciliationPage:
        """Append exact CTP date/hedge/offset facts for already-owned fills.

        This is a runner-refresh operation, not a Strategy projection. The
        caller first reconciles the same immutable facts through
        ``FactorExecutionCoordinator.reconcile_trade_observations`` and passes
        its complete bounded page. Only APPLIED/DUPLICATE rows that exactly
        match a durable fill and its query callback are stored. A repeated
        trade ID is idempotent only when all execution economics and dated
        ownership fields are unchanged.
        """

        observations, page_items, page_shape = _dated_trade_page_inputs(
            facts,
            reconciliation_page,
            limit=limit,
            offset=offset,
        )
        prepared = []
        result_items = []
        preflight_blocked = False
        for observation, page_item in zip(observations, page_items):
            observation_id = _exact_identifier_value(_field_value(observation, "observation_id"))
            if observation_id is None:
                raise FactorPositionBookError("DATED_TRADE_OBSERVATION_ID_INVALID")
            status = _exact_identifier_value(_field_value(page_item, "status"))
            intent_id = _exact_identifier_value(_field_value(page_item, "intent_id"))
            receipt_id = _exact_identifier_value(_field_value(page_item, "receipt_id"))
            execution_id = _exact_identifier_value(_field_value(page_item, "execution_id"))
            blocker = _exact_identifier_value(_field_value(page_item, "blocker_code"))
            if status not in ("APPLIED", "DUPLICATE"):
                result_items.append(
                    FactorDatedTradeReconciliationItem(
                        observation_id,
                        status or "BLOCKED",
                        intent_id,
                        receipt_id,
                        execution_id,
                        blocker or "TRADE_NOT_OWNED_BY_POSITION_BOOK",
                    )
                )
                continue
            if intent_id is None or receipt_id is None or execution_id is None:
                preflight_blocked = True
                result_items.append(
                    FactorDatedTradeReconciliationItem(
                        observation_id,
                        "BLOCKED",
                        intent_id,
                        receipt_id,
                        execution_id,
                        "TRADE_RECONCILIATION_IDENTITY_INCOMPLETE",
                    )
                )
                continue
            source_values, error_code = _dated_trade_source_values(
                facts,
                observation,
                page_item,
                query_set_id=page_shape["query_set_id"],
            )
            if error_code is not None:
                preflight_blocked = True
                result_items.append(
                    FactorDatedTradeReconciliationItem(
                        observation_id,
                        "BLOCKED",
                        intent_id,
                        receipt_id,
                        execution_id,
                        error_code,
                    )
                )
                continue
            prepared.append(
                (
                    observation_id,
                    intent_id,
                    receipt_id,
                    execution_id,
                    source_values,
                )
            )
            result_items.append(
                FactorDatedTradeReconciliationItem(
                    observation_id,
                    "APPLIED",
                    intent_id,
                    receipt_id,
                    execution_id,
                )
            )

        by_observation = {item.observation_id: item for item in result_items}
        with self._journal._transaction() as cursor:
            ensure_factor_position_book_schema(cursor)
            inserts = []
            batch_blocked = preflight_blocked
            for observation_id, intent_id, receipt_id, execution_id, values in prepared:
                fill = cursor.execute(
                    """SELECT * FROM factor_position_fills
                       WHERE account_scope=? AND instrument=? AND exchange=? AND execution_id=?""",
                    (
                        values["account_scope"],
                        values["instrument"],
                        values["exchange"],
                        execution_id,
                    ),
                ).fetchone()
                callback = cursor.execute(
                    "SELECT * FROM execution_decision_callbacks WHERE receipt_id=?",
                    (receipt_id,),
                ).fetchone()
                existing = cursor.execute(
                    """SELECT * FROM factor_position_dated_trade_facts
                       WHERE account_scope=? AND instrument=? AND exchange=? AND execution_id=?""",
                    (
                        values["account_scope"],
                        values["instrument"],
                        values["exchange"],
                        execution_id,
                    ),
                ).fetchone()
                insert_values = _dated_trade_insert_values(
                    values,
                    execution_id=execution_id,
                    receipt_id=receipt_id,
                    intent_id=intent_id,
                    owner_intent_id=fill["intent_id"]
                    if fill["position_effect"] == "OPEN"
                    else fill["owner_intent_id"],
                    strategy_scope=fill["strategy_scope"],
                    position_effect=fill["position_effect"],
                    order_side=fill["order_side"],
                )
                if existing is not None:
                    # A later complete query can report the same native fill
                    # with a new request/snapshot/observation identity. Keep
                    # the first immutable source receipt and compare only the
                    # stable execution identity before treating that query row
                    # as a duplicate.
                    if not _dated_trade_row_digest_matches(existing):
                        batch_blocked = True
                        by_observation[observation_id] = FactorDatedTradeReconciliationItem(
                            observation_id,
                            "BLOCKED",
                            intent_id,
                            receipt_id,
                            execution_id,
                            "DATED_TRADE_IDENTITY_CONFLICT",
                        )
                        continue
                    if _dated_trade_stable_values(
                        existing
                    ) != _dated_trade_stable_values_from_insert(insert_values):
                        batch_blocked = True
                        by_observation[observation_id] = FactorDatedTradeReconciliationItem(
                            observation_id,
                            "BLOCKED",
                            intent_id,
                            receipt_id,
                            execution_id,
                            "DATED_TRADE_IDENTITY_CONFLICT",
                        )
                        continue
                    original_callback_values = dict(existing)
                    original_callback_values["trade_id"] = values["trade_id"]
                    original_callback_values["quantity"] = _parse_decimal(
                        existing["quantity"], positive=True
                    )
                    original_callback_values["price"] = _parse_decimal(
                        existing["price"], positive=True
                    )
                    blocker = _dated_trade_journal_binding_error(
                        cursor,
                        fill,
                        callback,
                        original_callback_values,
                        journal=self._journal,
                        intent_id=intent_id,
                        receipt_id=receipt_id,
                        execution_id=execution_id,
                    )
                    if blocker is not None:
                        batch_blocked = True
                        by_observation[observation_id] = FactorDatedTradeReconciliationItem(
                            observation_id,
                            "BLOCKED",
                            intent_id,
                            receipt_id,
                            execution_id,
                            blocker,
                        )
                    else:
                        by_observation[observation_id] = FactorDatedTradeReconciliationItem(
                            observation_id,
                            "DUPLICATE",
                            intent_id,
                            receipt_id,
                            execution_id,
                        )
                    continue
                blocker = _dated_trade_journal_binding_error(
                    cursor,
                    fill,
                    callback,
                    values,
                    journal=self._journal,
                    intent_id=intent_id,
                    receipt_id=receipt_id,
                    execution_id=execution_id,
                )
                if blocker is not None:
                    batch_blocked = True
                    by_observation[observation_id] = FactorDatedTradeReconciliationItem(
                        observation_id,
                        "BLOCKED",
                        intent_id,
                        receipt_id,
                        execution_id,
                        blocker,
                    )
                    continue
                inserts.append((observation_id, insert_values))

            if batch_blocked:
                for observation_id, _insert_values in inserts:
                    item = by_observation[observation_id]
                    by_observation[observation_id] = FactorDatedTradeReconciliationItem(
                        observation_id,
                        "BLOCKED",
                        item.intent_id,
                        item.receipt_id,
                        item.execution_id,
                        "DATED_TRADE_BATCH_PREFLIGHT_FAILED",
                    )
                inserts = []
            for _observation_id, insert_values in inserts:
                columns = tuple(insert_values)
                dated_key = (
                    insert_values["account_scope"],
                    insert_values["instrument"],
                    insert_values["exchange"],
                    insert_values["execution_id"],
                )
                with track_durable_row_change(
                    cursor, "factor_position_dated_trade_facts", dated_key, "SETTLEMENT"
                ):
                    cursor.execute(
                        "INSERT INTO factor_position_dated_trade_facts ({}) VALUES ({})".format(
                            ",".join(columns), ",".join("?" for _ in columns)
                        ),
                        tuple(insert_values[name] for name in columns),
                    )

        return FactorDatedTradeReconciliationPage(
            items=tuple(by_observation[item.observation_id] for item in result_items),
            observation_count=page_shape["observation_count"],
            offset=page_shape["offset"],
            next_offset=page_shape["next_offset"],
            truncated=page_shape["truncated"],
        )

    def dated_snapshot(self, facts: Any, *, target_id: str) -> FactorDatedPositionProof:
        """Read the exact owned dated lots against current immutable CTP buckets."""

        try:
            context = _dated_position_context(facts, target_id=target_id)
        except FactorPositionBookError as error:
            return _empty_dated_proof(
                facts,
                target_id=target_id,
                blocker_code=error.code,
            )
        account_scope = context["account_scope"]
        strategy_scope = context["strategy_scope"]
        instrument = context["instrument"]
        exchange = context["exchange"]
        try:
            with self._journal._read_lock():
                connection = self._journal._connection
                current = connection.execute(
                    """SELECT * FROM factor_position_current
                       WHERE account_scope=? AND instrument=? AND exchange=?""",
                    (account_scope, instrument, exchange),
                ).fetchone()
                if current is None or current["state"] != "ACTIVE":
                    return _empty_dated_proof(
                        facts,
                        target_id=target_id,
                        blocker_code="DATED_POSITION_OWNER_UNAVAILABLE",
                        context=context,
                    )
                owner_intent_id = _exact_identifier_value(current["owner_intent_id"])
                if (
                    owner_intent_id is None
                    or current["strategy_scope"] != strategy_scope
                    or current["position_side"] not in ("LONG", "SHORT")
                ):
                    return _empty_dated_proof(
                        facts,
                        target_id=target_id,
                        blocker_code="DATED_POSITION_OWNER_MISMATCH",
                        context=context,
                    )
                fact_owner_intent_id = _exact_identifier_value(context["position"].owner_intent_id)
                if (
                    fact_owner_intent_id != owner_intent_id
                    or context["position_side"] != current["position_side"]
                ):
                    return _empty_dated_proof(
                        facts,
                        target_id=target_id,
                        blocker_code="DATED_POSITION_OWNER_MISMATCH",
                        context=context,
                    )
                active_issue = connection.execute(
                    """SELECT blocker_code FROM factor_position_active_issues
                       WHERE account_scope=? AND instrument=? AND exchange_key IN (?,?) LIMIT 1""",
                    (account_scope, instrument, exchange, _UNKNOWN_EXCHANGE_KEY),
                ).fetchone()
                if active_issue is not None:
                    return _empty_dated_proof(
                        facts,
                        target_id=target_id,
                        blocker_code=active_issue["blocker_code"],
                        context=context,
                    )
                fill_rows = connection.execute(
                    """SELECT f.*, d.* FROM factor_position_fills AS f
                       LEFT JOIN factor_position_dated_trade_facts AS d
                         ON d.account_scope=f.account_scope AND d.instrument=f.instrument
                        AND d.exchange=f.exchange AND d.execution_id=f.execution_id
                       WHERE f.account_scope=? AND f.instrument=? AND f.exchange=?
                         AND ((f.position_effect='OPEN' AND f.intent_id=?)
                           OR (f.position_effect='CLOSE' AND f.owner_intent_id=?))
                       ORDER BY f.filled_at_ns,f.execution_id""",
                    (account_scope, instrument, exchange, owner_intent_id, owner_intent_id),
                ).fetchall()
                fill_rows = tuple(_joined_dated_fill_row(row) for row in fill_rows)
                for row in fill_rows:
                    blocker = _dated_persisted_trade_journal_binding_error(
                        connection,
                        self._journal,
                        row,
                    )
                    if blocker is not None:
                        return _empty_dated_proof(
                            facts,
                            target_id=target_id,
                            blocker_code=blocker,
                            context=context,
                        )
        except (sqlite3.Error, ValueError, TypeError, FactorPositionBookError):
            return _empty_dated_proof(
                facts,
                target_id=target_id,
                blocker_code="DATED_POSITION_BOOK_UNAVAILABLE",
                context=context,
            )

        position_query_time_ns = _safe_datetime_ns(context["positions_query"].completed_at)
        if position_query_time_ns is None or any(
            type(row.get("trade_time_ns")) is not int
            or row["trade_time_ns"] > position_query_time_ns
            for row in fill_rows
        ):
            return _empty_dated_proof(
                facts,
                target_id=target_id,
                blocker_code="DATED_FILL_AFTER_POSITION_QUERY",
                context=context,
            )

        try:
            lot_state = _derive_dated_owner_lots(
                fill_rows,
                owner_intent_id=owner_intent_id,
                strategy_scope=strategy_scope,
                current_account_fingerprint=context["account_fingerprint"],
                position_side=current["position_side"],
                current_trading_day=context["trading_day"],
                expected_quantity=_decimal_add(
                    _parse_accumulator_decimal(current["open_quantity"], nonnegative=True),
                    -_parse_accumulator_decimal(current["close_quantity"], nonnegative=True),
                ),
            )
        except FactorPositionBookError as error:
            return _empty_dated_proof(
                facts,
                target_id=target_id,
                blocker_code=error.code,
                context=context,
            )
        buckets, bucket_blockers = _match_dated_inventory_buckets(context, lot_state)
        if bucket_blockers:
            return FactorDatedPositionProof(
                status="UNKNOWN",
                blocker_code=bucket_blockers[0],
                source_row_ids=context["source_row_ids"],
                buckets=buckets,
                ready=False,
                blockers=tuple(bucket_blockers),
                **context["proof_fields"],
            )
        return FactorDatedPositionProof(
            status="MATCHED",
            blocker_code=None,
            source_row_ids=context["source_row_ids"],
            buckets=buckets,
            ready=True,
            blockers=(),
            **context["proof_fields"],
        )

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
        with track_durable_row_change(
            cursor, "factor_position_evidence_issues", (receipt["receipt_id"],), "SETTLEMENT"
        ):
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
        with track_durable_row_change(
            cursor,
            "factor_position_active_issues",
            (account_scope, instrument, exchange_key),
            "SETTLEMENT",
        ):
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
            with track_durable_row_change(
                cursor,
                "factor_position_current",
                (account_scope, instrument, exchange),
                "SETTLEMENT",
            ):
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
            with track_durable_row_change(
                cursor,
                "factor_position_current",
                (account_scope, instrument, exchange),
                "SETTLEMENT",
            ):
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


_DATED_QUERY_FAMILIES = (
    "account_result",
    "orders_result",
    "trades_result",
    "instruments_result",
    "positions_result",
)
_DATED_REQUEST_TYPES = {
    "account_result": "account",
    "orders_result": "orders",
    "trades_result": "trades",
    "instruments_result": "instruments",
    "positions_result": "positions",
}
_DATED_HEDGE_FLAGS = frozenset(("1", "2", "3", "5"))
_DATED_OFFSET_FLAGS = frozenset(("0", "1", "2", "3", "4", "5", "6"))
_DATED_INVENTORY_REQUIRED_FIELDS = frozenset(
    (
        "InstrumentID",
        "ExchangeID",
        "PosiDirection",
        "HedgeFlag",
        "PositionDate",
        "TradingDay",
        "Position",
        "TodayPosition",
        "YdPosition",
        "LongFrozen",
        "ShortFrozen",
        "CombLongFrozen",
        "CombShortFrozen",
        "StrikeFrozen",
        "AbandonFrozen",
        "LongFrozenAmount",
        "ShortFrozenAmount",
        "FrozenMargin",
        "FrozenCash",
        "FrozenCommission",
        "StrikeFrozenAmount",
        "YdStrikeFrozen",
    )
)
_DATED_STABLE_TRADE_COLUMNS = (
    "account_scope",
    "instrument",
    "exchange",
    "execution_id",
    "receipt_id",
    "intent_id",
    "owner_intent_id",
    "strategy_scope",
    "position_effect",
    "order_side",
    "position_side",
    "hedge_flag",
    "offset_flag",
    "quantity",
    "price",
    "trading_day",
    "trade_date",
    "trade_time",
    "trade_time_ns",
    "order_ref",
    "order_sys_id",
)
_POSITION_FILL_COLUMNS = (
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
_DATED_TRADE_COLUMNS = (
    "account_scope",
    "instrument",
    "exchange",
    "execution_id",
    "receipt_id",
    "intent_id",
    "owner_intent_id",
    "strategy_scope",
    "position_effect",
    "order_side",
    "position_side",
    "hedge_flag",
    "offset_flag",
    "quantity",
    "price",
    "trading_day",
    "trade_date",
    "trade_time",
    "trade_time_ns",
    "order_ref",
    "order_sys_id",
    "observation_id",
    "query_set_id",
    "snapshot_id",
    "request_id",
    "connection_generation",
    "account_fingerprint",
    "available_at_ns",
    "payload_sha256",
)
_DATED_FILL_MATCH_COLUMNS = (
    "account_scope",
    "instrument",
    "exchange",
    "execution_id",
    "intent_id",
    "strategy_scope",
    "position_effect",
    "order_side",
)


def _field_value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _exact_identifier_value(value: Any) -> Optional[str]:
    if type(value) is str and _is_identifier(value):
        return value
    return None


def _valid_yyyymmdd(value: Any) -> bool:
    if type(value) is not str or re.fullmatch(r"\d{8}", value) is None:
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def _aware_utc_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _same_aware_datetime(left: Any, right: Any) -> bool:
    left_ns = _safe_datetime_ns(left)
    right_ns = _safe_datetime_ns(right)
    return left_ns is not None and left_ns == right_ns


def _safe_datetime_ns(value: Any) -> Optional[int]:
    try:
        return _datetime_to_ns(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _validated_dated_query_context(facts: Any) -> Mapping[str, Any]:
    """Validate one complete immutable query set without using wall-clock time."""

    from .factor_execution_facts import (
        FactorExecutionAccountFacts,
        FactorExecutionFacts,
        FactorExecutionQueryFact,
    )

    if type(facts) is not FactorExecutionFacts:
        raise FactorPositionBookError("EXECUTION_FACTS_REQUIRED")
    if (
        not _is_identifier(facts.account_scope)
        or not _is_identifier(facts.strategy_scope)
        or not _is_identifier(facts.snapshot_id)
        or not _is_identifier(facts.query_set_id)
        or type(facts.query_provenance) is not tuple
        or type(facts.positions) is not tuple
        or type(facts.trade_observations) is not tuple
    ):
        raise FactorPositionBookError("DATED_FACTS_IDENTITY_INCOMPLETE")
    available_at = _aware_utc_datetime(facts.available_at)
    account = facts.account
    if (
        available_at is None
        or type(account) is not FactorExecutionAccountFacts
        or account is None
        or account.account_scope != facts.account_scope
        or account.snapshot_id != facts.snapshot_id
        or not _same_aware_datetime(account.available_at, facts.available_at)
    ):
        raise FactorPositionBookError("DATED_FACTS_ACCOUNT_BINDING_INVALID")

    base = {}
    for query in facts.query_provenance:
        if type(query) is not FactorExecutionQueryFact:
            continue
        if query.target_id is None and query.family in _DATED_QUERY_FAMILIES:
            if query.family in base:
                raise FactorPositionBookError("DATED_QUERY_PROVENANCE_AMBIGUOUS")
            base[query.family] = query
    if set(base) != set(_DATED_QUERY_FAMILIES):
        raise FactorPositionBookError("DATED_QUERY_SET_INCOMPLETE")
    ordered = tuple(base[family] for family in _DATED_QUERY_FAMILIES)
    if any(
        query.request_type != _DATED_REQUEST_TYPES[family]
        or type(query.request_id) is not int
        or query.request_id <= 0
        or type(query.connection_generation) is not int
        or query.connection_generation <= 0
        or not _is_identifier(query.account_fingerprint)
        or not _valid_yyyymmdd(query.trading_day)
        or _aware_utc_datetime(query.started_at) is None
        or _aware_utc_datetime(query.completed_at) is None
        or query.started_at > query.completed_at
        or query.source_owned is not True
        or query.query_complete is not True
        or query.scope_complete is not True
        or type(query.row_count) is not int
        or query.row_count < 0
        for family, query in zip(_DATED_QUERY_FAMILIES, ordered)
    ):
        raise FactorPositionBookError("DATED_QUERY_PROVENANCE_INVALID")
    if (
        len({query.request_id for query in ordered}) != len(ordered)
        or len({query.connection_generation for query in ordered}) != 1
        or len({query.account_fingerprint for query in ordered}) != 1
        or len({query.trading_day for query in ordered}) != 1
    ):
        raise FactorPositionBookError("DATED_QUERY_SET_IDENTITY_MISMATCH")
    started_at = min(query.started_at for query in ordered)
    completed_at = max(query.completed_at for query in ordered)
    generation = ordered[0].connection_generation
    fingerprint = ordered[0].account_fingerprint
    trading_day = ordered[0].trading_day
    query_ids = tuple(
        (family, query.request_id) for family, query in zip(_DATED_QUERY_FAMILIES, ordered)
    )
    query_set_payload = json.dumps(
        (
            "factor-execution-query-set-v1",
            fingerprint,
            generation,
            trading_day,
            started_at.isoformat(),
            completed_at.isoformat(),
            query_ids,
        ),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    expected_query_set_id = "ctp.query-set:" + hashlib.sha256(query_set_payload).hexdigest()
    if (
        expected_query_set_id != facts.query_set_id
        or not _same_aware_datetime(available_at, completed_at)
        or account.account_fingerprint != fingerprint
        or account.connection_generation != generation
        or account.trading_day != trading_day
    ):
        raise FactorPositionBookError("DATED_QUERY_SET_IDENTITY_MISMATCH")
    trades_query = base["trades_result"]
    positions_query = base["positions_result"]
    if trades_query.row_count != len(facts.trade_observations):
        raise FactorPositionBookError("DATED_TRADE_SOURCE_ROWS_INCOMPLETE")
    return {
        "account_scope": facts.account_scope,
        "strategy_scope": facts.strategy_scope,
        "snapshot_id": facts.snapshot_id,
        "available_at": available_at,
        "query_set_id": facts.query_set_id,
        "account_fingerprint": fingerprint,
        "connection_generation": generation,
        "trading_day": trading_day,
        "queries": base,
        "trades_query": trades_query,
        "positions_query": positions_query,
    }


def _dated_trade_page_inputs(
    facts: Any,
    page: Any,
    *,
    limit: int,
    offset: int,
) -> Tuple[Tuple[Any, ...], Tuple[Any, ...], Mapping[str, Any]]:
    from .factor_execution import (
        ExecutionTradeReconciliationItem,
        ExecutionTradeReconciliationPage,
    )
    from .factor_execution_facts import FactorExecutionTradeObservationFacts

    context = _validated_dated_query_context(facts)
    if type(limit) is not int or not 1 <= limit <= 512:
        raise FactorPositionBookError("DATED_TRADE_PAGE_LIMIT_INVALID")
    if type(offset) is not int or offset < 0:
        raise FactorPositionBookError("DATED_TRADE_PAGE_OFFSET_INVALID")
    if type(page) is not ExecutionTradeReconciliationPage or type(page.items) is not tuple:
        raise FactorPositionBookError("DATED_TRADE_RECONCILIATION_PAGE_INVALID")
    observations = facts.trade_observations
    if any(type(row) is not FactorExecutionTradeObservationFacts for row in observations):
        raise FactorPositionBookError("DATED_TRADE_OBSERVATIONS_INVALID")
    if (
        type(page.observation_count) is not int
        or page.observation_count != len(observations)
        or page.offset != offset
        or type(page.offset) is not int
        or type(page.truncated) is not bool
    ):
        raise FactorPositionBookError("DATED_TRADE_RECONCILIATION_PAGE_INCOMPLETE")
    end = min(len(observations), offset + limit)
    expected = observations[offset:end]
    is_truncated = end < len(observations)
    expected_next = end if is_truncated else None
    if (
        offset > len(observations)
        or len(page.items) != len(expected)
        or page.truncated is not is_truncated
        or page.next_offset != expected_next
    ):
        raise FactorPositionBookError("DATED_TRADE_RECONCILIATION_PAGE_INCOMPLETE")
    expected_ids = tuple(row.observation_id for row in expected)
    actual_ids = tuple(_field_value(item, "observation_id") for item in page.items)
    if actual_ids != expected_ids or len(set(actual_ids)) != len(actual_ids):
        raise FactorPositionBookError("DATED_TRADE_RECONCILIATION_PAGE_IDENTITY_MISMATCH")
    if any(type(item) is not ExecutionTradeReconciliationItem for item in page.items):
        raise FactorPositionBookError("DATED_TRADE_RECONCILIATION_PAGE_INVALID")
    return (
        expected,
        page.items,
        {
            **context,
            "observation_count": page.observation_count,
            "offset": page.offset,
            "next_offset": page.next_offset,
            "truncated": page.truncated,
        },
    )


def _dated_trade_source_values(
    facts: Any,
    observation: Any,
    page_item: Any,
    *,
    query_set_id: str,
) -> Tuple[Optional[Mapping[str, Any]], Optional[str]]:
    try:
        context = _validated_dated_query_context(facts)
    except FactorPositionBookError as error:
        return None, error.code
    query = context["trades_query"]
    trade_id = _exact_identifier_value(observation.trade_id)
    order_ref = _exact_identifier_value(observation.order_ref)
    order_sys_id = (
        None
        if observation.order_sys_id is None
        else _exact_identifier_value(observation.order_sys_id)
    )
    instrument = _exact_identifier_value(observation.instrument)
    exchange = _exact_identifier_value(observation.exchange)
    direction = observation.direction
    order_side = observation.side
    offset_flag = observation.offset_flag
    hedge_flag = observation.hedge_flag
    position_effect = observation.position_effect
    quantity = _parse_decimal(observation.volume, positive=True)
    price = _parse_decimal(observation.price, positive=True)
    trade_date = observation.trade_date
    trade_time = observation.trade_time
    trade_time_ns = _ctp_trade_time_ns(trade_date, trade_time)
    observed_time_ns = _safe_datetime_ns(observation.trade_time_utc)
    available_ns = _safe_datetime_ns(query.completed_at)
    observation_id = _exact_identifier_value(observation.observation_id)
    expected_observation_id = _dated_trade_observation_identifier(observation)
    expected_execution_id = (
        "ctp:{}:{}".format(trade_date, trade_id)
        if _valid_yyyymmdd(trade_date) and trade_id is not None
        else None
    )
    execution_id = _exact_identifier_value(_field_value(page_item, "execution_id"))
    intent_id = _exact_identifier_value(_field_value(page_item, "intent_id"))
    receipt_id = _exact_identifier_value(_field_value(page_item, "receipt_id"))
    if (
        observation.evidence_kind != "complete_trades_query_observation"
        or observation.snapshot_id != facts.snapshot_id
        or observation.request_id != query.request_id
        or observation.connection_generation != query.connection_generation
        or observation.account_fingerprint != query.account_fingerprint
        or type(observation.request_id) is not int
        or observation.trading_day != query.trading_day
        or not _same_aware_datetime(observation.available_at, query.completed_at)
        or not _valid_yyyymmdd(observation.trading_day)
        or observation.trading_day != context["trading_day"]
        or not _valid_yyyymmdd(trade_date)
        or trade_time_ns is None
        or observed_time_ns is None
        or trade_time_ns != observed_time_ns
        or available_ns is None
        or trade_time_ns > available_ns
        or observation_id is None
        or observation_id != expected_observation_id
        or trade_id is None
        or order_ref is None
        or (observation.order_sys_id is not None and order_sys_id is None)
        or instrument is None
        or exchange is None
        or direction not in ("0", "1")
        or order_side not in ("BUY", "SELL")
        or order_side != ("BUY" if direction == "0" else "SELL")
        or offset_flag not in _DATED_OFFSET_FLAGS
        or observation.offset != offset_flag
        or hedge_flag not in _DATED_HEDGE_FLAGS
        or position_effect != ("OPEN" if offset_flag == "0" else "CLOSE")
        or type(observation.volume) is not Decimal
        or quantity is None
        or type(observation.price) is not Decimal
        or price is None
        or expected_execution_id is None
        or execution_id != expected_execution_id
        or intent_id is None
        or receipt_id is None
        or not _is_identifier(query_set_id)
    ):
        return None, "DATED_TRADE_SOURCE_IDENTITY_INVALID"
    return {
        "account_scope": facts.account_scope,
        "strategy_scope": facts.strategy_scope,
        "instrument": instrument,
        "exchange": exchange,
        "trade_id": trade_id,
        "execution_id": execution_id,
        "intent_id": intent_id,
        "receipt_id": receipt_id,
        "order_ref": order_ref,
        "order_sys_id": order_sys_id,
        "order_side": order_side,
        "position_effect": position_effect,
        "position_side": _trade_position_side(order_side, position_effect),
        "hedge_flag": hedge_flag,
        "offset_flag": offset_flag,
        "quantity": quantity,
        "price": price,
        "trading_day": observation.trading_day,
        "trade_date": trade_date,
        "trade_time": trade_time,
        "trade_time_ns": trade_time_ns,
        "observation_id": observation_id,
        "query_set_id": query_set_id,
        "snapshot_id": observation.snapshot_id,
        "request_id": observation.request_id,
        "connection_generation": observation.connection_generation,
        "account_fingerprint": observation.account_fingerprint,
        "available_at_ns": available_ns,
    }, None


def _dated_trade_observation_identifier(observation: Any) -> Optional[str]:
    """Recompute the facts-layer row ID so dated metadata cannot be rebound."""

    text_fields = (
        observation.trading_day,
        observation.trading_day,
        observation.trade_id,
        observation.order_ref,
        observation.instrument,
        observation.exchange,
        observation.direction,
        observation.offset_flag,
        observation.hedge_flag,
        observation.trade_date,
        observation.trade_time,
    )
    if (
        type(observation.connection_generation) is not int
        or type(observation.request_id) is not int
        or type(observation.volume) is not Decimal
        or type(observation.price) is not Decimal
        or any(type(value) is not str for value in text_fields)
        or (observation.order_sys_id is not None and type(observation.order_sys_id) is not str)
    ):
        return None
    try:
        payload = json.dumps(
            (
                "ctp-trades-query-observation-v1",
                observation.connection_generation,
                observation.trading_day,
                observation.request_id,
                observation.trading_day,
                observation.trade_id,
                observation.order_ref,
                observation.order_sys_id,
                observation.instrument,
                observation.exchange,
                observation.direction,
                observation.offset_flag,
                observation.hedge_flag,
                str(observation.volume),
                str(observation.price),
                observation.trade_date,
                observation.trade_time,
            ),
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError):
        return None
    return "trades-query-row:" + hashlib.sha256(payload).hexdigest()


def _trade_position_side(order_side: str, position_effect: str) -> str:
    if position_effect == "OPEN":
        return "LONG" if order_side == "BUY" else "SHORT"
    return "LONG" if order_side == "SELL" else "SHORT"


def _ctp_trade_time_ns(trade_date: Any, trade_time: Any) -> Optional[int]:
    if (
        not _valid_yyyymmdd(trade_date)
        or type(trade_time) is not str
        or re.fullmatch(r"\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?", trade_time) is None
    ):
        return None
    try:
        pattern = "%Y%m%d %H:%M:%S.%f" if "." in trade_time else "%Y%m%d %H:%M:%S"
        local = datetime.strptime(trade_date + " " + trade_time, pattern).replace(
            tzinfo=timezone(timedelta(hours=8))
        )
        # CTP TradeDate/TradeTime are local exchange time (UTC+08), including
        # night sessions whose TradingDay may be a later calendar date.
        return _datetime_to_ns(local.astimezone(timezone.utc))
    except (TypeError, ValueError, OverflowError):
        return None


def _dated_trade_insert_values(
    source: Mapping[str, Any],
    *,
    execution_id: str,
    receipt_id: str,
    intent_id: str,
    owner_intent_id: Optional[str],
    strategy_scope: str,
    position_effect: str,
    order_side: str,
) -> Mapping[str, Any]:
    if not _is_identifier(owner_intent_id):
        raise FactorPositionBookError("DATED_TRADE_OWNER_ID_INVALID")
    values = {
        "account_scope": source["account_scope"],
        "instrument": source["instrument"],
        "exchange": source["exchange"],
        "execution_id": execution_id,
        "receipt_id": receipt_id,
        "intent_id": intent_id,
        "owner_intent_id": owner_intent_id,
        "strategy_scope": strategy_scope,
        "position_effect": position_effect,
        "order_side": order_side,
        "position_side": source["position_side"],
        "hedge_flag": source["hedge_flag"],
        "offset_flag": source["offset_flag"],
        "quantity": _serialize_decimal(source["quantity"]),
        "price": _serialize_decimal(source["price"]),
        "trading_day": source["trading_day"],
        "trade_date": source["trade_date"],
        "trade_time": source["trade_time"],
        "trade_time_ns": source["trade_time_ns"],
        "order_ref": source["order_ref"],
        "order_sys_id": source["order_sys_id"],
        "observation_id": source["observation_id"],
        "query_set_id": source["query_set_id"],
        "snapshot_id": source["snapshot_id"],
        "request_id": source["request_id"],
        "connection_generation": source["connection_generation"],
        "account_fingerprint": source["account_fingerprint"],
        "available_at_ns": source["available_at_ns"],
    }
    digest = hashlib.sha256(_canonical_json(values).encode("utf-8")).hexdigest()
    values["payload_sha256"] = digest
    return values


def _dated_trade_stable_values(row: Mapping[str, Any]) -> Tuple[Any, ...]:
    return tuple(row[name] for name in _DATED_STABLE_TRADE_COLUMNS)


def _dated_trade_stable_values_from_insert(values: Mapping[str, Any]) -> Tuple[Any, ...]:
    return tuple(values[name] for name in _DATED_STABLE_TRADE_COLUMNS)


def _joined_dated_fill_row(row: sqlite3.Row) -> Mapping[str, Any]:
    values = tuple(row)
    expected_count = len(_POSITION_FILL_COLUMNS) + len(_DATED_TRADE_COLUMNS)
    if len(values) != expected_count:
        raise FactorPositionBookError("DATED_TRADE_JOIN_SHAPE_INVALID")
    fill = dict(zip(_POSITION_FILL_COLUMNS, values[: len(_POSITION_FILL_COLUMNS)]))
    dated = dict(zip(_DATED_TRADE_COLUMNS, values[len(_POSITION_FILL_COLUMNS) :]))
    joined = dict(dated)
    joined.update({"_fill_" + name: fill[name] for name in _POSITION_FILL_COLUMNS})
    return joined


def _dated_trade_row_digest_matches(row: Mapping[str, Any]) -> bool:
    try:
        values = {key: row[key] for key in _DATED_TRADE_COLUMNS if key != "payload_sha256"}
        digest = hashlib.sha256(_canonical_json(values).encode("utf-8")).hexdigest()
    except (KeyError, TypeError, ValueError, FactorPositionBookError):
        return False
    return digest == row["payload_sha256"]


def _dated_trade_journal_binding_error(
    cursor: sqlite3.Cursor,
    fill: Any,
    callback: Any,
    values: Mapping[str, Any],
    *,
    journal: Any,
    intent_id: str,
    receipt_id: str,
    execution_id: str,
) -> Optional[str]:
    if fill is None or callback is None:
        return "DATED_TRADE_JOURNAL_FILL_NOT_FOUND"
    intent = cursor.execute(
        """SELECT i.*, s.decision_id AS slot_decision_id,
                  s.intent_key_json AS slot_intent_key_json,
                  d.business_key_json
           FROM execution_decision_intents AS i
           JOIN execution_decision_slots AS s ON s.intent_id=i.intent_id
           JOIN execution_decisions AS d ON d.decision_id=i.decision_id
           WHERE i.intent_id=?""",
        (intent_id,),
    ).fetchone()
    if intent is None:
        return "DATED_TRADE_INTENT_NOT_FOUND"
    if (
        cursor.execute(
            """SELECT 1 FROM execution_intent_abandonments WHERE intent_id=?
           UNION ALL
           SELECT 1 FROM execution_slot_abandonments WHERE intent_id=? LIMIT 1""",
            (intent_id, intent_id),
        ).fetchone()
        is not None
    ):
        return "DATED_TRADE_INTENT_ABANDONED"
    state = intent["state"]
    dispatch_state = intent["dispatch_state"]
    dispatch_claimed = state == "DISPATCHING" and dispatch_state is None
    dispatch_result_recorded = (
        state in ("KNOWN", "UNKNOWN")
        and dispatch_state in ("KNOWN", "UNKNOWN")
        and (
            state == dispatch_state
            or (
                state == "KNOWN"
                and dispatch_state == "UNKNOWN"
                and cursor.execute(
                    """SELECT 1 FROM execution_intent_reconciliations
                       WHERE intent_id=? AND state='KNOWN' LIMIT 1""",
                    (intent_id,),
                ).fetchone()
                is not None
            )
        )
    )
    if not (dispatch_claimed or dispatch_result_recorded):
        return "DATED_TRADE_DISPATCH_NOT_CLAIMED"
    try:
        intent_key = json.loads(intent["intent_key_json"])
        slot_intent_key = json.loads(intent["slot_intent_key_json"])
        business_key = json.loads(intent["business_key_json"])
        economics = json.loads(intent["economic_payload_json"])
        original_identity = json.loads(intent["original_identity_json"])
    except (TypeError, ValueError):
        return "DATED_TRADE_INTENT_PAYLOAD_INVALID"
    if (
        not isinstance(intent_key, Mapping)
        or not isinstance(slot_intent_key, Mapping)
        or intent_key != slot_intent_key
        or not isinstance(business_key, Mapping)
        or not isinstance(economics, Mapping)
        or not isinstance(original_identity, Mapping)
        or intent["slot_decision_id"] != intent["decision_id"]
        or intent_key.get("action") != "SUBMIT"
        or intent_key.get("instrument") != values["instrument"]
        or intent_key.get("position_effect") != values["position_effect"]
        or intent_key.get("side") != values["order_side"]
        or business_key.get("account_scope") != values["account_scope"]
        or business_key.get("strategy_scope") != values["strategy_scope"]
        or economics.get("exchange") != values["exchange"]
        or (
            values["position_effect"] == "CLOSE"
            and (
                intent["owner_intent_id"] != fill["owner_intent_id"]
                or economics.get("owner_intent_id") != fill["owner_intent_id"]
            )
        )
    ):
        return "DATED_TRADE_INTENT_BINDING_MISMATCH"
    native = cursor.execute(
        """SELECT account_scope,strategy_scope,trading_day,instrument,exchange,order_ref
           FROM execution_native_intent_identities WHERE intent_id=?""",
        (intent_id,),
    ).fetchone()
    if (
        native is None
        or native["account_scope"] != values["account_scope"]
        or native["strategy_scope"] != values["strategy_scope"]
        or native["trading_day"] != values["trading_day"]
        or native["instrument"] != values["instrument"]
        or native["exchange"] != values["exchange"]
        or native["order_ref"] != values["order_ref"]
        or original_identity.get("operation") != "insert"
        or original_identity.get("trading_day") != values["trading_day"]
        or original_identity.get("instrument_id") != values["instrument"]
        or original_identity.get("exchange_id") != values["exchange"]
        or original_identity.get("order_ref") != values["order_ref"]
    ):
        return "DATED_TRADE_NATIVE_IDENTITY_MISMATCH"
    if (
        fill["account_scope"] != values["account_scope"]
        or fill["instrument"] != values["instrument"]
        or fill["exchange"] != values["exchange"]
        or fill["execution_id"] != execution_id
        or fill["intent_id"] != intent_id
        or fill["strategy_scope"] != values["strategy_scope"]
        or fill["position_effect"] != values["position_effect"]
        or fill["order_side"] != values["order_side"]
        or _parse_decimal(fill["quantity"], positive=True) != values["quantity"]
        or _parse_decimal(fill["price"], positive=True) != values["price"]
        or type(fill["filled_at_ns"]) is not int
        or fill["filled_at_ns"] != values["trade_time_ns"]
        or callback["receipt_id"] != receipt_id
        or callback["intent_id"] != intent_id
        or callback["callback_id"]
        != "query-trade:" + hashlib.sha256(execution_id.encode("utf-8")).hexdigest()
        or type(callback["acknowledged"]) is not int
        or callback["acknowledged"] != 1
    ):
        return "DATED_TRADE_JOURNAL_FILL_MISMATCH"
    owner_intent_id = (
        fill["intent_id"] if fill["position_effect"] == "OPEN" else fill["owner_intent_id"]
    )
    if not _is_identifier(owner_intent_id):
        return "DATED_TRADE_OWNER_BINDING_INVALID"
    try:
        evidence = json.loads(callback["evidence_payload_json"])
    except (TypeError, ValueError):
        return "DATED_TRADE_CALLBACK_EVIDENCE_INVALID"
    expected_evidence = {
        "event_type": "execution_fill",
        "execution_id": execution_id,
        "provider_trade_id": values["trade_id"],
        "order_ref": values["order_ref"],
        "instrument_id": values["instrument"],
        "exchange": values["exchange"],
        "filled_at_ns": values["trade_time_ns"],
        "evidence_kind": "complete_trades_query_observation",
        "time_source": "CTP_TradeDate_TradeTime_UTC_PLUS_08",
        "query_observation_id": values["observation_id"],
        "snapshot_id": values["snapshot_id"],
        "request_id": values["request_id"],
        "connection_generation": values["connection_generation"],
        "account_fingerprint": values["account_fingerprint"],
        "trading_day": values["trading_day"],
        "account_scope": values["account_scope"],
        "strategy_scope": values["strategy_scope"],
    }
    if not isinstance(evidence, Mapping) or any(
        evidence.get(name) != expected for name, expected in expected_evidence.items()
    ):
        return "DATED_TRADE_CALLBACK_SOURCE_BINDING_MISMATCH"
    if (
        _parse_decimal(evidence.get("quantity"), positive=True) != values["quantity"]
        or _parse_decimal(evidence.get("price"), positive=True) != values["price"]
        or evidence.get("order_sys_id") != values["order_sys_id"]
    ):
        return "DATED_TRADE_CALLBACK_ECONOMICS_MISMATCH"
    if fill["receipt_id"] != receipt_id:
        return _dated_trade_native_receipt_binding_error(
            cursor,
            journal,
            fill,
            values,
            query_evidence=evidence,
            intent_id=intent_id,
            query_receipt_id=receipt_id,
            execution_id=execution_id,
        )
    return None


def _dated_persisted_trade_journal_binding_error(
    connection: sqlite3.Connection,
    journal: Any,
    row: Mapping[str, Any],
) -> Optional[str]:
    """Revalidate both receipt origins before reconstructing a dated lot.

    A query observation remains the dated fact's source receipt, while the
    immutable position fill may retain its earlier native callback receipt.
    Reuse the same evidence and ACK/disposition checks as insertion so the
    dated-row reader never relies on receipt IDs being equal.
    """

    execution_id = row.get("execution_id")
    trade_date = row.get("trade_date")
    if (
        type(execution_id) is not str
        or not _valid_yyyymmdd(trade_date)
        or not execution_id.startswith("ctp:" + trade_date + ":")
    ):
        return "DATED_TRADE_JOURNAL_FILL_MISMATCH"
    trade_id = execution_id[len("ctp:" + trade_date + ":") :]
    if not _is_identifier(trade_id):
        return "DATED_TRADE_JOURNAL_FILL_MISMATCH"
    receipt_id = row.get("receipt_id")
    intent_id = row.get("intent_id")
    if not _is_identifier(receipt_id) or not _is_identifier(intent_id):
        return "DATED_TRADE_JOURNAL_FILL_MISMATCH"

    cursor = connection.cursor()
    try:
        callback = cursor.execute(
            """SELECT * FROM execution_decision_callbacks
               WHERE receipt_id=? AND intent_id=?""",
            (receipt_id, intent_id),
        ).fetchone()
        if callback is None:
            return "DATED_TRADE_JOURNAL_FILL_NOT_FOUND"
        fill = {name: row.get("_fill_" + name) for name in _POSITION_FILL_COLUMNS}
        quantity = _parse_accumulator_decimal(row.get("quantity"), positive=True)
        price = _parse_accumulator_decimal(row.get("price"), positive=True)
        if quantity is None or price is None:
            return "DATED_TRADE_METADATA_INVALID"
        values = {
            "account_scope": row.get("account_scope"),
            "strategy_scope": row.get("strategy_scope"),
            "instrument": row.get("instrument"),
            "exchange": row.get("exchange"),
            "trade_id": trade_id,
            "execution_id": execution_id,
            "intent_id": intent_id,
            "receipt_id": receipt_id,
            "order_ref": row.get("order_ref"),
            "order_sys_id": row.get("order_sys_id"),
            "position_effect": row.get("position_effect"),
            "order_side": row.get("order_side"),
            "quantity": quantity,
            "price": price,
            "trading_day": row.get("trading_day"),
            "trade_time_ns": row.get("trade_time_ns"),
            "observation_id": row.get("observation_id"),
            "query_set_id": row.get("query_set_id"),
            "snapshot_id": row.get("snapshot_id"),
            "request_id": row.get("request_id"),
            "connection_generation": row.get("connection_generation"),
            "account_fingerprint": row.get("account_fingerprint"),
        }
        return _dated_trade_journal_binding_error(
            cursor,
            fill,
            callback,
            values,
            journal=journal,
            intent_id=intent_id,
            receipt_id=receipt_id,
            execution_id=execution_id,
        )
    except (sqlite3.Error, TypeError, ValueError, FactorPositionBookError):
        return "DATED_TRADE_JOURNAL_BINDING_UNAVAILABLE"
    finally:
        cursor.close()


def _dated_trade_native_receipt_binding_error(
    cursor: sqlite3.Cursor,
    journal: Any,
    fill: Any,
    values: Mapping[str, Any],
    *,
    query_evidence: Mapping[str, Any],
    intent_id: str,
    query_receipt_id: str,
    execution_id: str,
) -> Optional[str]:
    """Bind a native-origin fill to the separately ACKed query receipt.

    A native callback remains the immutable origin of its fill. The complete
    query is independently checked by the caller; this helper verifies the
    exact native callback and either its ordinary ACK or the journal's durable
    cross-process query disposition proof.
    """

    native_callback_id = "ctp-trade:" + hashlib.sha256(execution_id.encode("utf-8")).hexdigest()
    try:
        native_receipt = journal.callback_receipt(intent_id, native_callback_id)
    except Exception:
        return "DATED_TRADE_NATIVE_RECEIPT_UNAVAILABLE"
    if (
        native_receipt is None
        or native_receipt.receipt_id != fill["receipt_id"]
        or native_receipt.intent_id != intent_id
        or native_receipt.callback_id != native_callback_id
    ):
        return "DATED_TRADE_NATIVE_RECEIPT_MISMATCH"

    native_row = cursor.execute(
        """SELECT callback_id,acknowledged,delivery_pending
           FROM execution_decision_callbacks WHERE receipt_id=? AND intent_id=?""",
        (fill["receipt_id"], intent_id),
    ).fetchone()
    if (
        native_row is None
        or native_row["callback_id"] != native_callback_id
        or type(native_row["acknowledged"]) is not int
        or type(native_row["delivery_pending"]) is not int
    ):
        return "DATED_TRADE_NATIVE_RECEIPT_MISMATCH"

    if native_receipt.acknowledged:
        if native_row["acknowledged"] != 1 or native_row["delivery_pending"] != 0:
            return "DATED_TRADE_NATIVE_ACK_STATE_MISMATCH"
    else:
        if native_row["acknowledged"] != 0 or native_row["delivery_pending"] != 0:
            return "DATED_TRADE_NATIVE_ACK_STATE_MISMATCH"
        try:
            disposition = journal.callback_query_disposition(fill["receipt_id"])
        except Exception:
            return "DATED_TRADE_NATIVE_QUERY_DISPOSITION_INVALID"
        if (
            disposition is None
            or disposition.native_receipt_id != fill["receipt_id"]
            or disposition.query_receipt_id != query_receipt_id
            or disposition.intent_id != intent_id
            or disposition.execution_id != execution_id
            or disposition.disposition_code != "QUERY_MATCHED_BROKER_ACK_UNOBSERVED_AFTER_RESTART"
        ):
            return "DATED_TRADE_NATIVE_QUERY_DISPOSITION_REQUIRED"

    native_evidence = native_receipt.evidence_payload
    expected_native_evidence = {
        "event_type": "execution_fill",
        "execution_id": execution_id,
        "provider_trade_id": values["trade_id"],
        "order_ref": values["order_ref"],
        "instrument_id": values["instrument"],
        "exchange": values["exchange"],
        "filled_at_ns": values["trade_time_ns"],
        "time_source": "CTP_TradeDate_TradeTime_UTC_PLUS_08",
        "evidence_kind": "native_trade_callback",
    }
    if not isinstance(native_evidence, Mapping) or any(
        native_evidence.get(name) != expected for name, expected in expected_native_evidence.items()
    ):
        return "DATED_TRADE_NATIVE_EVIDENCE_MISMATCH"
    native_order_sys_id = native_evidence.get("order_sys_id")
    if (
        native_order_sys_id is not None
        and values["order_sys_id"] is not None
        and native_order_sys_id != values["order_sys_id"]
    ):
        return "DATED_TRADE_NATIVE_EVIDENCE_MISMATCH"
    if (
        _parse_decimal(native_evidence.get("quantity"), positive=True) != values["quantity"]
        or _parse_decimal(native_evidence.get("price"), positive=True) != values["price"]
        or _parse_decimal(fill["quantity"], positive=True) != values["quantity"]
        or _parse_decimal(fill["price"], positive=True) != values["price"]
        or type(native_evidence.get("filled_at_ns")) is not int
        or native_evidence.get("filled_at_ns") != fill["filled_at_ns"]
    ):
        return "DATED_TRADE_NATIVE_ECONOMICS_MISMATCH"

    native_fee = native_evidence.get("fee")
    query_fee = query_evidence.get("fee")
    if native_fee is not None:
        native_fee = _parse_decimal(native_fee, nonnegative=True)
        stored_fee = _parse_decimal(fill["fee"], nonnegative=True)
        if native_fee is None or stored_fee != native_fee:
            return "DATED_TRADE_NATIVE_ECONOMICS_MISMATCH"
    if native_evidence.get("fee") is not None and query_fee is not None:
        parsed_query_fee = _parse_decimal(query_fee, nonnegative=True)
        if parsed_query_fee is None or parsed_query_fee != native_fee:
            return "DATED_TRADE_NATIVE_ECONOMICS_MISMATCH"
    return None


def _dated_position_context(facts: Any, *, target_id: str) -> Mapping[str, Any]:
    from .factor_execution_facts import FactorExecutionPositionFacts

    query_context = _validated_dated_query_context(facts)
    if not _is_identifier(target_id):
        raise FactorPositionBookError("DATED_TARGET_ID_INVALID")
    if any(type(row) is not FactorExecutionPositionFacts for row in facts.positions):
        raise FactorPositionBookError("DATED_POSITION_FACTS_INVALID")
    matches = tuple(row for row in facts.positions if row.target_id == target_id)
    if len(matches) != 1:
        raise FactorPositionBookError("DATED_POSITION_TARGET_AMBIGUOUS")
    position = matches[0]
    if (
        not _is_identifier(position.instrument)
        or not _is_identifier(position.exchange)
        or position.snapshot_id != facts.snapshot_id
        or not _same_aware_datetime(position.available_at, facts.available_at)
        or type(position.dated_inventory_rows) is not tuple
    ):
        raise FactorPositionBookError("DATED_POSITION_TARGET_BINDING_INVALID")
    if (
        type(position.quantity) is not Decimal
        or type(position.broker_quantity) is not Decimal
        or type(position.long_quantity) is not Decimal
        or type(position.short_quantity) is not Decimal
        or _parse_decimal(position.quantity) is None
        or _parse_decimal(position.broker_quantity) is None
        or _parse_decimal(position.long_quantity, nonnegative=True) is None
        or _parse_decimal(position.short_quantity, nonnegative=True) is None
    ):
        raise FactorPositionBookError("DATED_POSITION_AGGREGATE_UNAVAILABLE")
    quantity = _parse_decimal(position.quantity)
    broker_quantity = _parse_decimal(position.broker_quantity)
    long_quantity = _parse_decimal(position.long_quantity, nonnegative=True)
    short_quantity = _parse_decimal(position.short_quantity, nonnegative=True)
    if (
        quantity != broker_quantity
        or quantity != _decimal_add(long_quantity, -short_quantity)
        or (long_quantity != 0 and short_quantity != 0)
    ):
        raise FactorPositionBookError("DATED_BROKER_CTP_AGGREGATE_MISMATCH")
    owner_intent_id = _exact_identifier_value(position.owner_intent_id)
    if quantity != 0 and (
        position.owner_strategy_scope != facts.strategy_scope or owner_intent_id is None
    ):
        raise FactorPositionBookError("DATED_POSITION_OWNER_UNAVAILABLE")
    if quantity == 0:
        raise FactorPositionBookError("DATED_POSITION_FLAT")
    rows = position.dated_inventory_rows
    if not rows:
        raise FactorPositionBookError("DATED_INVENTORY_ROWS_UNAVAILABLE")
    from .factor_execution_facts import FactorExecutionDatedInventoryRow

    if any(type(row) is not FactorExecutionDatedInventoryRow for row in rows):
        raise FactorPositionBookError("DATED_INVENTORY_ROWS_INVALID")
    return {
        **query_context,
        "target_id": target_id,
        "instrument": position.instrument,
        "exchange": position.exchange,
        "position": position,
        "owner_intent_id": owner_intent_id,
        "position_side": "LONG" if quantity > 0 else "SHORT",
        "signed_quantity": quantity,
        "long_quantity": long_quantity,
        "short_quantity": short_quantity,
        "rows": rows,
        "source_row_ids": tuple(
            row.source_row_id for row in rows if _is_identifier(row.source_row_id)
        ),
        "proof_fields": {
            "account_scope": query_context["account_scope"],
            "strategy_scope": query_context["strategy_scope"],
            "target_id": target_id,
            "instrument": position.instrument,
            "exchange": position.exchange,
            "query_set_id": query_context["query_set_id"],
            "account_fingerprint": query_context["account_fingerprint"],
            "connection_generation": query_context["connection_generation"],
            "trading_day": query_context["trading_day"],
            "snapshot_id": query_context["snapshot_id"],
            "available_at": query_context["available_at"],
        },
    }


def _empty_dated_proof(
    facts: Any,
    *,
    target_id: str,
    blocker_code: str,
    context: Optional[Mapping[str, Any]] = None,
) -> FactorDatedPositionProof:
    if context is not None:
        fields = context["proof_fields"]
        source_ids = context.get("source_row_ids", ())
    else:
        fields = {
            "account_scope": _exact_identifier_value(_field_value(facts, "account_scope"))
            or "unknown",
            "strategy_scope": _exact_identifier_value(_field_value(facts, "strategy_scope"))
            or "unknown",
            "target_id": _exact_identifier_value(target_id) or "unknown",
            "instrument": "unknown",
            "exchange": "unknown",
            "query_set_id": None,
            "account_fingerprint": None,
            "connection_generation": None,
            "trading_day": None,
            "snapshot_id": None,
            "available_at": None,
        }
        source_ids = ()
    return FactorDatedPositionProof(
        status="UNKNOWN",
        blocker_code=blocker_code,
        source_row_ids=tuple(source_ids),
        buckets=(),
        ready=False,
        blockers=(blocker_code,),
        **fields,
    )


def _derive_dated_owner_lots(
    fill_rows: Sequence[Any],
    *,
    owner_intent_id: str,
    strategy_scope: str,
    current_account_fingerprint: str,
    position_side: str,
    current_trading_day: str,
    expected_quantity: Decimal,
) -> Mapping[str, Any]:
    """Reconstruct owned date buckets without binding them to a session generation.

    The account fingerprint must still match the current complete query. A
    connection generation may change across restart for the same account, so
    per-fill generations are provenance only and are deliberately not compared.
    """

    if not _is_identifier(current_account_fingerprint):
        raise FactorPositionBookError("DATED_POSITION_ACCOUNT_FINGERPRINT_INVALID")
    if (
        not _valid_yyyymmdd(current_trading_day)
        or position_side not in ("LONG", "SHORT")
        or not isinstance(expected_quantity, Decimal)
        or not expected_quantity.is_finite()
        or expected_quantity <= 0
    ):
        raise FactorPositionBookError("DATED_POSITION_EXPECTED_QUANTITY_INVALID")
    opens = []
    closes = []
    seen_execution_ids = set()
    seen_trade_times = set()
    for row in fill_rows:
        execution_id = _exact_identifier_value(row["execution_id"])
        if execution_id is None or execution_id in seen_execution_ids:
            raise FactorPositionBookError("DATED_POSITION_EXECUTION_ID_AMBIGUOUS")
        seen_execution_ids.add(execution_id)
        if row["trade_time_ns"] in seen_trade_times:
            raise FactorPositionBookError("DATED_TRADE_TIME_AMBIGUOUS")
        seen_trade_times.add(row["trade_time_ns"])
        if row["strategy_scope"] != strategy_scope:
            raise FactorPositionBookError("DATED_POSITION_STRATEGY_SCOPE_MISMATCH")
        if not _dated_trade_row_digest_matches(row):
            raise FactorPositionBookError("DATED_TRADE_METADATA_DIGEST_INVALID")
        if row["account_fingerprint"] != current_account_fingerprint:
            raise FactorPositionBookError("DATED_POSITION_ACCOUNT_FINGERPRINT_MISMATCH")
        quantity = _parse_accumulator_decimal(row["quantity"], positive=True)
        price = _parse_accumulator_decimal(row["price"], positive=True)
        trading_day = row["trading_day"]
        trade_date = row["trade_date"]
        trade_time_ns = row["trade_time_ns"]
        hedge_flag = row["hedge_flag"]
        offset_flag = row["offset_flag"]
        effect = row["position_effect"]
        order_side = row["order_side"]
        if (
            quantity is None
            or price is None
            or any(row.get("_fill_" + name) != row[name] for name in _DATED_FILL_MATCH_COLUMNS)
            or _parse_accumulator_decimal(row.get("_fill_quantity"), positive=True) != quantity
            or _parse_accumulator_decimal(row.get("_fill_price"), positive=True) != price
            or row.get("_fill_filled_at_ns") != trade_time_ns
            or (effect == "OPEN" and row.get("_fill_owner_intent_id") is not None)
            or (effect == "CLOSE" and row.get("_fill_owner_intent_id") != row["owner_intent_id"])
            or row["position_side"] != _trade_position_side(order_side, effect)
            or not _valid_yyyymmdd(trading_day)
            or not _valid_yyyymmdd(trade_date)
            or type(trade_time_ns) is not int
            or trade_time_ns <= 0
            or not _is_identifier(row["intent_id"])
            or not _is_identifier(row["owner_intent_id"])
            or not _is_identifier(row["receipt_id"])
            or hedge_flag not in _DATED_HEDGE_FLAGS
            or offset_flag not in _DATED_OFFSET_FLAGS
            or order_side not in ("BUY", "SELL")
            or effect not in ("OPEN", "CLOSE")
            or (effect == "OPEN") != (offset_flag == "0")
        ):
            raise FactorPositionBookError("DATED_TRADE_METADATA_INVALID")
        if row["position_effect"] == "OPEN":
            if row["intent_id"] != owner_intent_id or row["owner_intent_id"] != owner_intent_id:
                raise FactorPositionBookError("DATED_OPEN_OWNER_MISMATCH")
            side = _trade_position_side(order_side, effect)
            if side != position_side:
                raise FactorPositionBookError("DATED_OPEN_POSITION_SIDE_MISMATCH")
            if trading_day > current_trading_day:
                raise FactorPositionBookError("DATED_OPEN_TRADING_DAY_IN_FUTURE")
            opens.append(
                {
                    "execution_id": row["execution_id"],
                    "intent_id": row["intent_id"],
                    "owner_intent_id": owner_intent_id,
                    "strategy_scope": strategy_scope,
                    "trading_day": trading_day,
                    "position_side": side,
                    "hedge_flag": hedge_flag,
                    "quantity": quantity,
                    "time_ns": trade_time_ns,
                    "observation_id": row["observation_id"],
                    "snapshot_id": row["snapshot_id"],
                    "query_set_id": row["query_set_id"],
                    "close_quantity": Decimal(0),
                    "close_execution_ids": [],
                }
            )
        else:
            if row["owner_intent_id"] != owner_intent_id:
                raise FactorPositionBookError("DATED_CLOSE_OWNER_MISMATCH")
            if _trade_position_side(order_side, effect) != position_side:
                raise FactorPositionBookError("DATED_CLOSE_POSITION_SIDE_MISMATCH")
            if offset_flag not in ("3", "4"):
                raise FactorPositionBookError("DATED_CLOSE_OFFSET_AMBIGUOUS")
            closes.append(
                {
                    "execution_id": row["execution_id"],
                    "trading_day": trading_day,
                    "hedge_flag": hedge_flag,
                    "quantity": quantity,
                    "time_ns": trade_time_ns,
                    "offset_flag": offset_flag,
                }
            )
    if not opens:
        raise FactorPositionBookError("DATED_OPEN_FILL_HISTORY_MISSING")
    opens.sort(key=lambda item: (item["time_ns"], item["execution_id"]))
    closes.sort(key=lambda item: (item["time_ns"], item["execution_id"]))
    for close in closes:
        remaining_to_allocate = close["quantity"]
        for opened in opens:
            if opened["time_ns"] > close["time_ns"]:
                continue
            if opened["hedge_flag"] != close["hedge_flag"]:
                continue
            eligible = (
                opened["trading_day"] == close["trading_day"]
                if close["offset_flag"] == "3"
                else opened["trading_day"] < close["trading_day"]
            )
            if not eligible:
                continue
            available = _decimal_add(opened["quantity"], -opened["close_quantity"])
            if available <= 0:
                continue
            allocation = min(available, remaining_to_allocate)
            opened["close_quantity"] = _decimal_add(opened["close_quantity"], allocation)
            opened["close_execution_ids"].append(close["execution_id"])
            remaining_to_allocate = _decimal_add(remaining_to_allocate, -allocation)
            if remaining_to_allocate == 0:
                break
        if remaining_to_allocate != 0:
            raise FactorPositionBookError("DATED_CLOSE_EXCEEDS_ELIGIBLE_OPEN_LOTS")

    lots = []
    grouped = {}
    aggregate = Decimal(0)
    for opened in opens:
        remaining = _decimal_add(opened["quantity"], -opened["close_quantity"])
        if remaining < 0:
            raise FactorPositionBookError("DATED_LOT_NEGATIVE_REMAINDER")
        position_date = "TODAY" if opened["trading_day"] == current_trading_day else "HISTORY"
        lot = FactorDatedPositionLot(
            execution_id=opened["execution_id"],
            intent_id=opened["intent_id"],
            owner_intent_id=opened["owner_intent_id"],
            strategy_scope=opened["strategy_scope"],
            trading_day=opened["trading_day"],
            position_side=opened["position_side"],
            hedge_flag=opened["hedge_flag"],
            opened_quantity=opened["quantity"],
            closed_quantity=opened["close_quantity"],
            remaining_quantity=remaining,
            open_observation_id=opened["observation_id"],
            open_snapshot_id=opened["snapshot_id"],
            open_query_set_id=opened["query_set_id"],
            close_execution_ids=tuple(opened["close_execution_ids"]),
        )
        lots.append(lot)
        aggregate = _decimal_add(aggregate, remaining)
        key = (opened["position_side"], opened["hedge_flag"], position_date, current_trading_day)
        group = grouped.setdefault(
            key,
            {"quantity": Decimal(0), "lots": [], "open_ids": [], "close_ids": []},
        )
        group["quantity"] = _decimal_add(group["quantity"], remaining)
        group["lots"].append(lot)
        group["open_ids"].append(opened["execution_id"])
        group["close_ids"].extend(opened["close_execution_ids"])
    if aggregate != expected_quantity:
        raise FactorPositionBookError("DATED_OWNER_FILL_TOTAL_MISMATCH")
    return {
        "lots": tuple(lots),
        "groups": grouped,
        "quantity": aggregate,
        "owner_intent_id": owner_intent_id,
        "strategy_scope": strategy_scope,
        "position_side": position_side,
    }


def _match_dated_inventory_buckets(
    context: Mapping[str, Any], lot_state: Mapping[str, Any]
) -> Tuple[Tuple[FactorDatedPositionBucket, ...], Tuple[str, ...]]:
    from .factor_execution_facts import FactorExecutionDatedInventoryRow

    rows = context["rows"]
    query = context["positions_query"]
    groups = lot_state["groups"]
    inventory = {}
    blockers = []
    row_ids = set()
    observed_total = {"LONG": Decimal(0), "SHORT": Decimal(0)}
    for row in rows:
        if type(row) is not FactorExecutionDatedInventoryRow:
            blockers.append("DATED_INVENTORY_ROW_TYPE_INVALID")
            continue
        source_id = _exact_identifier_value(row.source_row_id)
        if source_id is None or source_id in row_ids:
            blockers.append("DATED_INVENTORY_ROW_ID_DUPLICATE_OR_MISSING")
            continue
        row_ids.add(source_id)
        if row.blockers:
            blockers.extend("DATED_INVENTORY_ROW_BLOCKED:{}".format(code) for code in row.blockers)
        expected_source_prefix = "positions-query-row:{}:".format(query.request_id)
        suffix = (
            source_id[len(expected_source_prefix) :]
            if source_id.startswith(expected_source_prefix)
            else ""
        )
        if not suffix.isdigit() or (len(suffix) > 1 and suffix.startswith("0")):
            blockers.append("DATED_INVENTORY_SOURCE_ROW_BINDING_INVALID")
        if (
            row.instrument != context["instrument"]
            or row.exchange != context["exchange"]
            or row.query_set_id != context["query_set_id"]
            or row.snapshot_id != context["snapshot_id"]
            or row.request_id != query.request_id
            or row.connection_generation != context["connection_generation"]
            or row.account_fingerprint != context["account_fingerprint"]
            or not _same_aware_datetime(row.available_at, query.completed_at)
            or row.trading_day != context["trading_day"]
        ):
            blockers.append("DATED_INVENTORY_ROW_PROVENANCE_MISMATCH")
        if (
            type(row.observed_fields) is not tuple
            or any(type(name) is not str for name in row.observed_fields)
            or len(set(row.observed_fields)) != len(row.observed_fields)
            or not _DATED_INVENTORY_REQUIRED_FIELDS.issubset(set(row.observed_fields))
        ):
            blockers.append("DATED_INVENTORY_ROW_FIELDS_INCOMPLETE")
        numeric_fields = (
            "position",
            "today_position",
            "yd_position",
            "long_frozen",
            "short_frozen",
            "comb_long_frozen",
            "comb_short_frozen",
            "strike_frozen",
            "abandon_frozen",
            "long_frozen_amount",
            "short_frozen_amount",
            "frozen_margin",
            "frozen_cash",
            "frozen_commission",
            "strike_frozen_amount",
            "yd_strike_frozen",
        )
        numeric_invalid = any(
            type(getattr(row, name)) is not Decimal
            or _parse_decimal(getattr(row, name), nonnegative=True) is None
            for name in numeric_fields
        )
        if numeric_invalid:
            blockers.append("DATED_INVENTORY_NUMERIC_FIELD_INVALID")
        elif any(getattr(row, name) != 0 for name in numeric_fields[3:]):
            blockers.append("DATED_INVENTORY_FREEZE_PRESENT")
        if (
            row.position_side not in ("LONG", "SHORT")
            or row.hedge_flag not in _DATED_HEDGE_FLAGS
            or row.position_date_code not in ("1", "2")
            or row.position_date != ("TODAY" if row.position_date_code == "1" else "HISTORY")
            or not _valid_yyyymmdd(row.trading_day)
            or numeric_invalid
        ):
            blockers.append("DATED_INVENTORY_ROW_VALUES_INVALID")
            continue
        if row.position_date == "TODAY" and row.today_position != row.position:
            blockers.append("DATED_TODAY_POSITION_CONTRADICTION")
        if row.position_date == "HISTORY" and row.today_position != 0:
            blockers.append("DATED_HISTORY_TODAY_POSITION_CONTRADICTION")
        key = (row.position_side, row.hedge_flag, row.position_date, row.trading_day)
        if key in inventory:
            blockers.append("DATED_INVENTORY_BUCKET_DUPLICATE")
            continue
        inventory[key] = row
        observed_total[row.position_side] = _decimal_add(
            observed_total[row.position_side], row.position
        )
    if (
        observed_total["LONG"] != context["long_quantity"]
        or observed_total["SHORT"] != context["short_quantity"]
    ):
        blockers.append("DATED_INVENTORY_SIDE_TOTAL_MISMATCH")

    expected_keys = {key for key, group in groups.items() if group["quantity"] > 0}
    observed_keys = set(inventory)
    missing_keys = expected_keys - observed_keys
    unmatched_nonzero_keys = {
        key for key, row in inventory.items() if row.position > 0 and key not in expected_keys
    }
    if missing_keys or unmatched_nonzero_keys:
        blockers.append("DATED_INVENTORY_OWNER_BUCKET_SET_MISMATCH")
    bucket_items = []
    all_keys = sorted(expected_keys)
    for key in all_keys:
        side, hedge, position_date, trading_day = key
        row = inventory.get(key)
        group = groups.get(key)
        provider_quantity = Decimal(0) if row is None else row.position
        owned_quantity = Decimal(0) if group is None else group["quantity"]
        local_blockers = list(blockers)
        if row is None:
            local_blockers.append("DATED_INVENTORY_BUCKET_MISSING")
        if row is not None and group is not None and provider_quantity != owned_quantity:
            local_blockers.append("DATED_PROVIDER_OWNER_QUANTITY_MISMATCH")
        global_mismatch = bool(blockers)
        ready = not local_blockers and not global_mismatch and owned_quantity > 0
        lot_values = () if group is None else tuple(group["lots"])
        source_ids = () if row is None else (row.source_row_id,)
        bucket_items.append(
            FactorDatedPositionBucket(
                position_side=side,
                hedge_flag=hedge,
                position_date=position_date,
                trading_day=trading_day,
                provider_quantity=provider_quantity,
                owned_quantity=owned_quantity,
                available_quantity=owned_quantity if ready and owned_quantity > 0 else None,
                owner_strategy_scope=lot_state["strategy_scope"] if group else None,
                owner_intent_id=lot_state["owner_intent_id"] if group else None,
                source_row_ids=source_ids,
                opening_execution_ids=() if group is None else tuple(group["open_ids"]),
                close_execution_ids=() if group is None else tuple(group["close_ids"]),
                lots=lot_values,
                ready=ready,
                blockers=tuple(sorted(set(local_blockers))),
            )
        )
        blockers.extend(local_blockers)
    return tuple(bucket_items), tuple(sorted(set(blockers)))
