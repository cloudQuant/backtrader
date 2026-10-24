"""Source-fake contracts for durable strategy position attribution."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest

from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionKey,
    ExecutionIntentKey,
)
from backtrader.stores.factor_position_book import (
    FactorPositionBook,
    FactorPositionBookError,
    apply_factor_execution_fill,
    ensure_factor_position_book_schema,
    _decimal_add,
    validate_factor_position_close_owner,
)


_ACCOUNT = "sim-account"
_STRATEGY = "alpha003-native"
_INSTRUMENT = "rb2701"
_EXCHANGE = "SHFE"
_COHORT = "rb-cohort"
_AVAILABLE = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)


def _close_time(minute: int) -> str:
    return "2026-10-24T09:{:02d}:00Z".format(minute)


def _timestamp_ns(minute: int, second: int) -> int:
    value = datetime(2026, 10, 24, 9, minute, second, tzinfo=timezone.utc)
    return int(value.timestamp()) * 1_000_000_000


def _new_open(
    journal: ExecutionDecisionJournal,
    *,
    strategy_scope: str = _STRATEGY,
    logical_run_id: str = "run-1",
    cohort_id: str = _COHORT,
    batch_id: str = "batch-1",
    grid_minute: int = 0,
):
    key = ExecutionDecisionKey(
        account_scope=_ACCOUNT,
        strategy_scope=strategy_scope,
        logical_run_id=logical_run_id,
        cohort_id=cohort_id,
        close_time=_close_time(grid_minute),
        decision_kind="alpha003-rebalance",
    )
    intent_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument=_INSTRUMENT,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    grid = journal.record_grid_decision(
        key,
        {"batch_id": batch_id, "mode": "native", "risk_policy_id": "a003-risk-v1"},
        intent_keys=(intent_key,),
        epoch_id="epoch-1",
        batch_id=batch_id,
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
    )
    intent = journal.prepare_intent(
        grid.decision.decision_id,
        intent_key,
        {
            "exchange": _EXCHANGE,
            "factor_stop_price": "3450",
            "risk_policy_id": "a003-risk-v1",
            "risk_policy": {
                "max_loss_per_position": "20",
                "stop_loss_ticks": 10,
            },
            "batch_id": batch_id,
            "quantity": "1",
            "price": "3500",
        },
    )
    return key, intent


def _new_callback(
    journal: ExecutionDecisionJournal,
    intent_id: str,
    *,
    callback_id: str,
    execution_id: str,
    quantity: str,
    price: str,
    fee: Optional[str] = "1",
    filled_at_ns: Optional[int],
    exchange: str = _EXCHANGE,
    event_type: str = "execution_fill",
):
    if event_type == "execution_fill":
        journal.claim_dispatch(intent_id)
    receipt = journal.record_callback(
        intent_id,
        callback_id,
        {
            "event_type": event_type,
            "execution_id": execution_id,
            "quantity": quantity,
            "price": price,
            "fee": fee,
            "filled_at_ns": filled_at_ns,
            "exchange": exchange,
        },
    )
    with journal._transaction() as cursor:
        applied = apply_factor_execution_fill(cursor, receipt_id=receipt.receipt_id)
    return receipt, applied


def _record_grid(journal: ExecutionDecisionJournal, ordinal: int, minute: int) -> None:
    batch_id = "batch-{}".format(ordinal)
    key = ExecutionDecisionKey(
        account_scope=_ACCOUNT,
        strategy_scope=_STRATEGY,
        logical_run_id="position-grid-{}".format(ordinal),
        cohort_id=_COHORT,
        close_time=_close_time(minute),
        decision_kind="position-test-grid",
    )
    result = journal.record_grid_decision(
        key,
        {"batch_id": batch_id},
        epoch_id="epoch-1",
        batch_id=batch_id,
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
    )
    assert result.cursor.ordinal == ordinal


def _snapshot(
    journal: ExecutionDecisionJournal,
    *,
    strategy_scope: str = _STRATEGY,
    broker_quantity: str = "1",
    long_quantity: str = "1",
    short_quantity: str = "0",
):
    return FactorPositionBook(journal).snapshot(
        account_scope=_ACCOUNT,
        strategy_scope=strategy_scope,
        instrument=_INSTRUMENT,
        exchange=_EXCHANGE,
        broker_quantity=Decimal(broker_quantity),
        long_quantity=Decimal(long_quantity),
        short_quantity=Decimal(short_quantity),
        snapshot_id="broker-query-r1",
        available_at=_AVAILABLE,
    )


def _make_open_fill(journal, *, intent_id: str, execution_id: str = "trade-open-1"):
    return _new_callback(
        journal,
        intent_id,
        callback_id="callback-{}".format(execution_id),
        execution_id=execution_id,
        quantity="1",
        price="3500",
        fee="2.5",
        filled_at_ns=_timestamp_ns(0, 30),
    )


def _terminally_reconcile_open(journal, intent_id: str, *, position_flat: bool = False):
    journal.claim_dispatch(intent_id)
    journal.record_dispatch_result(
        intent_id, state="KNOWN", provider_identity={"order": "native-1"}
    )
    reconciliation = journal.record_reconciliation(
        intent_id,
        reconciliation_id="reconcile-{}".format(intent_id[:12]),
        query_id="query-{}".format(intent_id[:12]),
        state="KNOWN",
        provider_identity={"order": "native-1"},
        terminal_state="CANCELLED",
        terminal_event_id="terminal-{}".format(intent_id[:12]),
        position_snapshot_id="snapshot-{}".format(intent_id[:12]),
        position_flat=position_flat,
    )
    journal.release_instrument_owner(intent_id, reconciliation_id=reconciliation.reconciliation_id)


def test_open_fill_reconstructs_attribution_in_fresh_process(tmp_path):
    database = tmp_path / "positions.sqlite3"
    journal = ExecutionDecisionJournal(database)
    _key, intent = _new_open(journal)
    _make_open_fill(journal, intent_id=intent.intent_id)
    _record_grid(journal, 2, 1)
    local = _snapshot(journal)
    assert local.status == "MATCHED"
    assert local.owner_strategy_scope == _STRATEGY
    assert local.owner_intent_id == intent.intent_id
    assert local.position_side == "LONG"
    assert local.average_price == Decimal("3500")
    assert local.stop_price == Decimal("3450")
    assert local.held_eligible_bars == 1
    with pytest.raises(TypeError):
        local.risk_policy["stop_loss_ticks"] = 1
    journal.close()

    child = r"""
import json, sys
from datetime import datetime, timezone
from decimal import Decimal
from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal
from backtrader.stores.factor_position_book import FactorPositionBook
journal = ExecutionDecisionJournal(sys.argv[1])
snapshot = FactorPositionBook(journal).snapshot(
    account_scope='sim-account', strategy_scope='alpha003-native',
    instrument='rb2701', exchange='SHFE', broker_quantity=Decimal('1'),
    long_quantity=Decimal('1'), short_quantity=Decimal('0'),
    snapshot_id='restart-query',
    available_at=datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc),
)
print(json.dumps({'status': snapshot.status, 'owner': snapshot.owner_intent_id,
                  'held': snapshot.held_eligible_bars, 'stop': str(snapshot.stop_price)}))
journal.close()
"""
    completed = subprocess.run(
        [sys.executable, "-c", child, str(database)],
        cwd=str(Path.cwd()),
        check=True,
        capture_output=True,
        text=True,
    )
    recovered = json.loads(completed.stdout)
    assert recovered == {
        "status": "MATCHED",
        "owner": intent.intent_id,
        "held": 1,
        "stop": "3450",
    }


def test_snapshot_rejects_grid_history_ahead_of_available_time(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "positions.sqlite3")
    _key, intent = _new_open(journal)
    _make_open_fill(journal, intent_id=intent.intent_id)
    _record_grid(journal, 2, 1)

    snapshot = FactorPositionBook(journal).snapshot(
        account_scope=_ACCOUNT,
        strategy_scope=_STRATEGY,
        instrument=_INSTRUMENT,
        exchange=_EXCHANGE,
        broker_quantity=Decimal("1"),
        long_quantity=Decimal("1"),
        short_quantity=Decimal("0"),
        snapshot_id="earlier-query",
        available_at=datetime(2026, 10, 24, 9, 0, 45, tzinfo=timezone.utc),
    )

    assert snapshot.status == "UNKNOWN"
    assert snapshot.blocker_code == "POSITION_GRID_CURSOR_AHEAD_OF_SNAPSHOT"
    assert snapshot.held_eligible_bars is None
    flat_snapshot = FactorPositionBook(journal).snapshot(
        account_scope=_ACCOUNT,
        strategy_scope=_STRATEGY,
        instrument=_INSTRUMENT,
        exchange=_EXCHANGE,
        broker_quantity=Decimal("0"),
        long_quantity=Decimal("0"),
        short_quantity=Decimal("0"),
        snapshot_id="earlier-flat-query",
        available_at=datetime(2026, 10, 24, 9, 0, 45, tzinfo=timezone.utc),
    )
    assert flat_snapshot.status == "UNKNOWN"
    assert flat_snapshot.blocker_code == "POSITION_GRID_CURSOR_AHEAD_OF_SNAPSHOT"


def test_partial_fills_out_of_order_and_duplicate_trade_ids_count_once(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "positions.sqlite3")
    _key, intent = _new_open(journal)
    # The later source execution is delivered first; the earlier one follows.
    _new_callback(
        journal,
        intent.intent_id,
        callback_id="callback-later",
        execution_id="trade-later",
        quantity="0.125",
        price="3520",
        fee="0.125",
        filled_at_ns=_timestamp_ns(0, 45),
    )
    _new_callback(
        journal,
        intent.intent_id,
        callback_id="callback-earlier",
        execution_id="trade-earlier",
        quantity="0.375",
        price="3500",
        fee="0.375",
        filled_at_ns=_timestamp_ns(0, 35),
    )
    _record_grid(journal, 2, 1)
    # A provider replay can use a new callback ID while retaining the same
    # immutable trade ID and economics.
    _receipt, duplicate = _new_callback(
        journal,
        intent.intent_id,
        callback_id="callback-earlier-replay",
        execution_id="trade-earlier",
        quantity="0.3750",
        price="3500.0",
        fee="0.3750",
        filled_at_ns=_timestamp_ns(0, 35),
    )
    assert duplicate.status == "DUPLICATE"
    snapshot = _snapshot(
        journal,
        broker_quantity="0.5",
        long_quantity="0.5",
        short_quantity="0",
    )
    assert snapshot.status == "MATCHED"
    assert snapshot.signed_quantity == Decimal("0.5")
    assert snapshot.average_price == Decimal("3505")
    assert snapshot.held_eligible_bars == 1
    fees = sum(
        (
            Decimal(row[0])
            for row in journal._connection.execute(
                "SELECT fee FROM factor_position_fills ORDER BY execution_id"
            )
        ),
        Decimal(0),
    )
    assert fees == Decimal("0.5")
    journal.close()


def test_persisted_callback_replays_after_crash_without_double_projection(tmp_path):
    database = tmp_path / "positions.sqlite3"
    journal = ExecutionDecisionJournal(database)
    _key, intent = _new_open(journal)
    journal.claim_dispatch(intent.intent_id)
    receipt = journal.record_callback(
        intent.intent_id,
        "callback-before-crash",
        {
            "event_type": "execution_fill",
            "execution_id": "trade-crash-window",
            "quantity": "1",
            "price": "3500",
            "fee": "2",
            "filled_at_ns": _timestamp_ns(0, 20),
            "exchange": _EXCHANGE,
        },
    )
    journal.close()

    replay = ExecutionDecisionJournal(database)
    with replay._transaction() as cursor:
        first = apply_factor_execution_fill(cursor, receipt_id=receipt.receipt_id)
    with replay._transaction() as cursor:
        second = apply_factor_execution_fill(cursor, receipt_id=receipt.receipt_id)
    assert first.status == "APPLIED"
    assert second.status == "DUPLICATE"
    assert _snapshot(replay).signed_quantity == Decimal("1")
    replay.close()


@pytest.mark.parametrize(
    ("abandon", "expected_blocker"),
    ((False, "FILL_DISPATCH_NOT_CLAIMED"), (True, "FILL_INTENT_ABANDONED")),
)
def test_unclaimed_or_abandoned_fill_is_audited_without_position_projection(
    tmp_path, abandon, expected_blocker
):
    journal = ExecutionDecisionJournal(tmp_path / "unclaimed-fill.sqlite3")
    _key, intent = _new_open(journal)
    if abandon:
        journal.abandon_prepared_intent(intent.intent_id, reason_code="not_sent")
    receipt = journal.record_callback(
        intent.intent_id,
        "unclaimed-fill-callback",
        {
            "event_type": "execution_fill",
            "execution_id": "trade-never-claimed",
            "quantity": "1",
            "price": "3500",
            "fee": None,
            "filled_at_ns": _timestamp_ns(0, 20),
            "exchange": _EXCHANGE,
        },
    )
    with journal._transaction() as cursor:
        result = apply_factor_execution_fill(cursor, receipt_id=receipt.receipt_id)

    assert result.status == "BLOCKED"
    assert result.blocker_code == expected_blocker
    assert journal.callback_receipt(intent.intent_id, "unclaimed-fill-callback") is not None
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM factor_position_fills").fetchone()[0] == 0
    )
    current = journal._connection.execute(
        """SELECT state,blocker_code,owner_intent_id,open_quantity,close_quantity
           FROM factor_position_current WHERE account_scope=? AND instrument=? AND exchange=?""",
        (_ACCOUNT, _INSTRUMENT, _EXCHANGE),
    ).fetchone()
    assert current is not None
    assert current["state"] == "UNKNOWN"
    assert current["blocker_code"] == expected_blocker
    assert current["owner_intent_id"] is None
    assert Decimal(current["open_quantity"]) == Decimal("0")
    assert Decimal(current["close_quantity"]) == Decimal("0")
    assert (
        journal._connection.execute(
            "SELECT COUNT(*) FROM factor_position_evidence_issues WHERE receipt_id=?",
            (receipt.receipt_id,),
        ).fetchone()[0]
        == 1
    )
    assert journal.intent(intent.intent_id).state == "PREPARED"
    journal.close()


def test_unknown_fee_and_fill_time_can_be_enriched_without_rewriting_fill(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "positions.sqlite3")
    _key, intent = _new_open(journal)
    receipt, applied = _new_callback(
        journal,
        intent.intent_id,
        callback_id="trade-without-fee-or-clock",
        execution_id="trade-enriched-later",
        quantity="1",
        price="3500",
        fee=None,
        filled_at_ns=None,
    )
    assert applied.status == "APPLIED"
    unknown = _snapshot(journal)
    assert unknown.status == "UNKNOWN"
    assert unknown.blocker_code == "POSITION_GRID_ANCHOR_UNAVAILABLE"
    assert unknown.owner_intent_id == intent.intent_id
    assert unknown.stop_price == Decimal("3450")
    assert unknown.opening_fee_total is None
    assert unknown.opening_fees_known is False

    clock_receipt = journal.record_callback(
        intent.intent_id,
        "trade-clock-recovered-fee-still-unknown",
        {
            "event_type": "execution_fill",
            "execution_id": "trade-enriched-later",
            "quantity": "1",
            "price": "3500",
            "fee": None,
            "filled_at_ns": _timestamp_ns(0, 30),
            "exchange": _EXCHANGE,
        },
    )
    with journal._transaction() as cursor:
        clock_result = apply_factor_execution_fill(cursor, receipt_id=clock_receipt.receipt_id)
    assert clock_result.status == "DUPLICATE"
    fee_unknown_but_attributed = _snapshot(journal)
    assert fee_unknown_but_attributed.status == "MATCHED"
    assert fee_unknown_but_attributed.owner_intent_id == intent.intent_id
    assert fee_unknown_but_attributed.average_price == Decimal("3500")
    assert fee_unknown_but_attributed.stop_price == Decimal("3450")
    assert fee_unknown_but_attributed.held_eligible_bars == 0
    assert fee_unknown_but_attributed.opening_fee_total is None
    assert fee_unknown_but_attributed.opening_fees_known is False

    duplicate = journal.record_callback(
        intent.intent_id,
        "trade-fee-and-clock-recovered",
        {
            "event_type": "execution_fill",
            "execution_id": "trade-enriched-later",
            "quantity": "1",
            "price": "3500",
            "fee": "2.5",
            "filled_at_ns": _timestamp_ns(0, 30),
            "exchange": _EXCHANGE,
        },
    )
    with journal._transaction() as cursor:
        result = apply_factor_execution_fill(cursor, receipt_id=duplicate.receipt_id)
    assert result.status == "DUPLICATE"
    matched = _snapshot(journal)
    assert matched.status == "MATCHED"
    assert matched.opening_fees_known is True
    assert matched.opening_fee_total == Decimal("2.5")
    assert matched.held_eligible_bars == 0
    raw_fill = journal._connection.execute(
        """SELECT fee,filled_at_ns FROM factor_position_fills
           WHERE execution_id='trade-enriched-later'"""
    ).fetchone()
    assert raw_fill["fee"] is None
    assert raw_fill["filled_at_ns"] is None
    journal.close()


def test_old_epoch_fill_enrichment_cannot_change_new_epoch_risk_facts(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "positions.sqlite3")
    _key, intent = _new_open(journal)
    _old_receipt, old_applied = _new_callback(
        journal,
        intent.intent_id,
        callback_id="old-epoch-unknown-fill",
        execution_id="old-epoch-trade",
        quantity="1",
        price="3500",
        fee=None,
        filled_at_ns=None,
    )
    assert old_applied.status == "APPLIED"
    old_epoch = journal._connection.execute(
        """SELECT position_epoch FROM factor_position_fill_attributes
           WHERE execution_id='old-epoch-trade'"""
    ).fetchone()[0]
    assert old_epoch == 1

    _terminally_reconcile_open(journal, intent.intent_id, position_flat=True)
    _new_receipt, new_applied = _new_callback(
        journal,
        intent.intent_id,
        callback_id="new-epoch-unknown-fill",
        execution_id="new-epoch-trade",
        quantity="1",
        price="3510",
        fee=None,
        filled_at_ns=None,
    )
    assert new_applied.status == "BLOCKED"
    assert new_applied.blocker_code == "OPEN_INTENT_QUANTITY_EXCEEDED"
    current_before = journal._connection.execute(
        """SELECT epoch,opening_fee_unknown_count,fill_time_unknown_count,
                  first_fill_at_ns,first_fill_grid_ordinal,open_quantity
           FROM factor_position_current
           WHERE account_scope=? AND instrument=? AND exchange=?""",
        (_ACCOUNT, _INSTRUMENT, _EXCHANGE),
    ).fetchone()
    assert current_before["epoch"] == 3
    assert current_before["opening_fee_unknown_count"] == 1
    assert current_before["fill_time_unknown_count"] == 1
    assert current_before["first_fill_at_ns"] is None
    assert current_before["first_fill_grid_ordinal"] is None
    assert current_before["open_quantity"] == "1"

    old_enrichment = journal.record_callback(
        intent.intent_id,
        "old-epoch-fee-time-enrichment",
        {
            "event_type": "execution_fill",
            "execution_id": "old-epoch-trade",
            "quantity": "1",
            "price": "3500",
            "fee": "2.5",
            "filled_at_ns": _timestamp_ns(0, 30),
            "exchange": _EXCHANGE,
        },
    )
    with journal._transaction() as cursor:
        enriched = apply_factor_execution_fill(cursor, receipt_id=old_enrichment.receipt_id)
    assert enriched.status == "DUPLICATE"
    old_attributes = journal._connection.execute(
        """SELECT fee,filled_at_ns,position_epoch FROM factor_position_fill_attributes
           WHERE execution_id='old-epoch-trade'"""
    ).fetchone()
    assert old_attributes["fee"] == "2.5"
    assert old_attributes["filled_at_ns"] == _timestamp_ns(0, 30)
    assert old_attributes["position_epoch"] == old_epoch
    old_raw_fill = journal._connection.execute(
        """SELECT fee,filled_at_ns FROM factor_position_fills
           WHERE execution_id='old-epoch-trade'"""
    ).fetchone()
    assert tuple(old_raw_fill) == (None, None)
    current_after = journal._connection.execute(
        """SELECT epoch,opening_fee_unknown_count,fill_time_unknown_count,
                  first_fill_at_ns,first_fill_grid_ordinal,
                  open_quantity
           FROM factor_position_current
           WHERE account_scope=? AND instrument=? AND exchange=?""",
        (_ACCOUNT, _INSTRUMENT, _EXCHANGE),
    ).fetchone()
    assert tuple(current_after) == tuple(current_before)
    assert (
        journal._connection.execute(
            """SELECT opening_fee_total FROM factor_position_current
           WHERE account_scope=? AND instrument=? AND exchange=?""",
            (_ACCOUNT, _INSTRUMENT, _EXCHANGE),
        ).fetchone()[0]
        == "0"
    )
    assert current_after["epoch"] != old_epoch
    assert (
        journal._connection.execute(
            """SELECT position_epoch FROM factor_position_fill_attributes
           WHERE execution_id='new-epoch-trade'"""
        ).fetchone()[0]
        == current_after["epoch"]
    )
    snapshot = _snapshot(journal)
    assert snapshot.status == "UNKNOWN"
    assert snapshot.blocker_code == "OPEN_INTENT_QUANTITY_EXCEEDED"
    assert snapshot.owner_intent_id == intent.intent_id
    assert snapshot.average_price == Decimal("3510")
    assert snapshot.opening_fee_total is None
    assert snapshot.opening_fees_known is False
    assert snapshot.held_eligible_bars is None
    journal.close()


def test_open_overfill_keeps_observed_owned_quantity_and_blocks_new_risk(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "positions.sqlite3")
    _key, intent = _new_open(journal)
    _first_receipt, first = _new_callback(
        journal,
        intent.intent_id,
        callback_id="overfill-first-part",
        execution_id="overfill-trade-1",
        quantity="0.6",
        price="3500",
        fee="0.2",
        filled_at_ns=_timestamp_ns(0, 30),
    )
    assert first.status == "APPLIED", first.blocker_code
    first_projection = journal._connection.execute(
        """SELECT owner_intent_id,strategy_scope,cohort_id,position_side,state,blocker_code
           FROM factor_position_current WHERE account_scope=? AND instrument=? AND exchange=?""",
        (_ACCOUNT, _INSTRUMENT, _EXCHANGE),
    ).fetchone()
    assert tuple(first_projection) == (intent.intent_id, _STRATEGY, _COHORT, "LONG", "ACTIVE", None)
    _receipt, overfill = _new_callback(
        journal,
        intent.intent_id,
        callback_id="overfill-second-part",
        execution_id="overfill-trade-2",
        quantity="0.6",
        price="3510",
        fee="0.3",
        filled_at_ns=_timestamp_ns(0, 40),
    )
    assert overfill.status == "BLOCKED"
    assert overfill.blocker_code == "OPEN_INTENT_QUANTITY_EXCEEDED"
    _record_grid(journal, 2, 1)

    total_before = journal._connection.execute(
        "SELECT filled_quantity FROM factor_position_open_intent_totals WHERE intent_id=?",
        (intent.intent_id,),
    ).fetchone()[0]
    assert total_before == "1.2"
    snapshot = _snapshot(
        journal,
        broker_quantity="1.2",
        long_quantity="1.2",
        short_quantity="0",
    )
    assert snapshot.status == "UNKNOWN"
    assert snapshot.blocker_code == "OPEN_INTENT_QUANTITY_EXCEEDED"
    assert snapshot.signed_quantity == Decimal("1.2")
    assert snapshot.attributed_signed_quantity == Decimal("1.2")
    assert snapshot.owner_intent_id == intent.intent_id
    assert snapshot.average_price == Decimal("3505")
    assert snapshot.opening_fees_known is True
    assert snapshot.opening_fee_total == Decimal("0.5")

    broker_capped = _snapshot(
        journal,
        broker_quantity="1",
        long_quantity="1",
        short_quantity="0",
    )
    assert broker_capped.status == "UNKNOWN"
    assert broker_capped.blocker_code == "OPEN_INTENT_QUANTITY_EXCEEDED"
    assert broker_capped.signed_quantity == Decimal("1")
    assert broker_capped.attributed_signed_quantity == Decimal("1.2")
    assert broker_capped.owner_intent_id == intent.intent_id

    ctp_disagrees = _snapshot(
        journal,
        broker_quantity="1",
        long_quantity="1.2",
        short_quantity="0",
    )
    assert ctp_disagrees.status == "UNKNOWN"
    assert ctp_disagrees.blocker_code == "OPEN_INTENT_QUANTITY_EXCEEDED"
    assert ctp_disagrees.signed_quantity == Decimal("1")
    assert ctp_disagrees.attributed_signed_quantity == Decimal("1.2")

    _duplicate_receipt, duplicate = _new_callback(
        journal,
        intent.intent_id,
        callback_id="overfill-first-part-replay",
        execution_id="overfill-trade-1",
        quantity="0.6",
        price="3500",
        fee="0.2",
        filled_at_ns=_timestamp_ns(0, 30),
    )
    assert duplicate.status == "DUPLICATE"
    total_after = journal._connection.execute(
        "SELECT filled_quantity FROM factor_position_open_intent_totals WHERE intent_id=?",
        (intent.intent_id,),
    ).fetchone()[0]
    assert total_after == total_before
    assert (
        journal._connection.execute(
            "SELECT COUNT(*) FROM factor_position_fills WHERE intent_id=? AND position_effect='OPEN'",
            (intent.intent_id,),
        ).fetchone()[0]
        == 2
    )

    _terminally_reconcile_open(journal, intent.intent_id, position_flat=False)
    with journal._transaction() as cursor:
        validate_factor_position_close_owner(
            cursor,
            account_scope=_ACCOUNT,
            strategy_scope=_STRATEGY,
            instrument=_INSTRUMENT,
            exchange=_EXCHANGE,
            owner_intent_id=intent.intent_id,
        )
    journal.close()


def test_decimal_accumulator_preserves_full_input_exponent_span_and_rejects_overflow():
    exact = _decimal_add(Decimal("1e128"), Decimal("1e-128"))
    sign, digits, exponent = exact.as_tuple()
    assert sign == 0
    assert len(digits) == 257
    assert exponent == -128
    assert digits[0] == 1 and digits[-1] == 1
    too_wide = Decimal((0, (9,) * 1024, -256))
    with pytest.raises(FactorPositionBookError, match="POSITION_DECIMAL_ACCUMULATOR_LIMIT"):
        _decimal_add(too_wide, Decimal("1e-512"))


def test_v4_upgrade_preserves_fills_and_leaves_epoch_unproven(tmp_path):
    database = tmp_path / "positions.sqlite3"
    journal = ExecutionDecisionJournal(database)
    _key, intent = _new_open(journal)
    _make_open_fill(journal, intent_id=intent.intent_id)
    journal.close()

    connection = sqlite3.connect(database)
    connection.execute("DROP INDEX factor_position_fill_attributes_by_intent_time")
    connection.execute("ALTER TABLE factor_position_fill_attributes DROP COLUMN position_epoch")
    connection.execute("DROP TABLE factor_position_open_intent_totals")
    connection.execute("UPDATE factor_position_book_meta SET version=4 WHERE singleton=1")
    connection.commit()
    connection.close()

    migrated = ExecutionDecisionJournal(database)
    raw_fill = migrated._connection.execute(
        """SELECT quantity,price,fee,filled_at_ns FROM factor_position_fills
           WHERE execution_id='trade-open-1'"""
    ).fetchone()
    assert tuple(raw_fill) == ("1", "3500", "2.5", _timestamp_ns(0, 30))
    attributes = migrated._connection.execute(
        """SELECT position_epoch FROM factor_position_fill_attributes
           WHERE execution_id='trade-open-1'"""
    ).fetchone()
    assert attributes["position_epoch"] is None
    total = migrated._connection.execute(
        "SELECT filled_quantity,quantity_complete FROM factor_position_open_intent_totals WHERE intent_id=?",
        (intent.intent_id,),
    ).fetchone()
    assert tuple(total) == ("1", 1)
    current = migrated._connection.execute(
        """SELECT state,owner_intent_id,open_quantity,opening_fee_unknown_count,
                  fill_time_complete,fill_time_unknown_count,first_fill_at_ns
           FROM factor_position_current WHERE account_scope=? AND instrument=? AND exchange=?""",
        (_ACCOUNT, _INSTRUMENT, _EXCHANGE),
    ).fetchone()
    assert current["state"] == "ACTIVE"
    assert current["owner_intent_id"] == intent.intent_id
    assert current["open_quantity"] == "1"
    assert current["opening_fee_unknown_count"] == 1
    assert current["fill_time_complete"] == 0
    assert current["fill_time_unknown_count"] == 1
    assert current["first_fill_at_ns"] is None
    snapshot = _snapshot(migrated)
    assert snapshot.status == "UNKNOWN"
    assert snapshot.blocker_code == "POSITION_GRID_ANCHOR_UNAVAILABLE"
    assert snapshot.owner_intent_id == intent.intent_id
    assert snapshot.opening_fees_known is False
    migrated.close()


def test_extreme_observed_fees_remain_exact_and_known(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "positions.sqlite3")
    _key, intent = _new_open(journal)
    _first_receipt, first = _new_callback(
        journal,
        intent.intent_id,
        callback_id="large-fee",
        execution_id="large-fee-trade",
        quantity="0.5",
        price="3500",
        fee="1e128",
        filled_at_ns=_timestamp_ns(0, 30),
    )
    persisted_evidence = json.loads(
        journal._connection.execute(
            "SELECT evidence_payload_json FROM execution_decision_callbacks WHERE receipt_id=?",
            (_first_receipt.receipt_id,),
        ).fetchone()[0]
    )
    assert Decimal(persisted_evidence["fee"]) == Decimal("1e128")
    assert first.status == "APPLIED", first.blocker_code
    first_projection = journal._connection.execute(
        """SELECT owner_intent_id,strategy_scope,cohort_id,position_side,state,blocker_code
           FROM factor_position_current WHERE account_scope=? AND instrument=? AND exchange=?""",
        (_ACCOUNT, _INSTRUMENT, _EXCHANGE),
    ).fetchone()
    assert tuple(first_projection) == (intent.intent_id, _STRATEGY, _COHORT, "LONG", "ACTIVE", None)
    _new_callback(
        journal,
        intent.intent_id,
        callback_id="small-fee",
        execution_id="small-fee-trade",
        quantity="0.5",
        price="3500",
        fee="1e-128",
        filled_at_ns=_timestamp_ns(0, 40),
    )
    _record_grid(journal, 2, 1)
    snapshot = _snapshot(journal)
    assert snapshot.status == "MATCHED", snapshot.blocker_code
    assert snapshot.opening_fees_known is True
    assert snapshot.opening_fee_total is not None
    sign, digits, exponent = snapshot.opening_fee_total.as_tuple()
    assert sign == 0
    assert len(digits) == 257
    assert exponent == -128
    assert digits[0] == 1 and digits[-1] == 1
    journal.close()


def test_snapshot_reads_bounded_projection_after_history_growth(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "positions.sqlite3")
    _key, intent = _new_open(journal)
    _make_open_fill(journal, intent_id=intent.intent_id)
    base_time = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)
    count = 256
    for ordinal in range(2, count + 1):
        grid_time = base_time + timedelta(minutes=ordinal - 1)
        batch_id = "history-batch-{}".format(ordinal)
        key = ExecutionDecisionKey(
            account_scope=_ACCOUNT,
            strategy_scope=_STRATEGY,
            logical_run_id="history-run-{}".format(ordinal),
            cohort_id=_COHORT,
            close_time=grid_time.isoformat(timespec="seconds").replace("+00:00", "Z"),
            decision_kind="durable-noop",
        )
        journal.record_grid_decision(
            key,
            {"batch_id": batch_id},
            epoch_id="epoch-1",
            batch_id=batch_id,
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
        )
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM factor_position_fills").fetchone()[0] == 1
    )
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM factor_position_grid_history").fetchone()[
            0
        ]
        == count
    )

    statements = []
    journal._connection.set_trace_callback(statements.append)
    latest_time = base_time + timedelta(minutes=count)
    snapshot = FactorPositionBook(journal).snapshot(
        account_scope=_ACCOUNT,
        strategy_scope=_STRATEGY,
        instrument=_INSTRUMENT,
        exchange=_EXCHANGE,
        broker_quantity=Decimal("1"),
        long_quantity=Decimal("1"),
        short_quantity=Decimal("0"),
        snapshot_id="bounded-history-query",
        available_at=latest_time,
    )
    journal._connection.set_trace_callback(None)

    assert snapshot.status == "MATCHED"
    assert snapshot.held_eligible_bars == count - 1
    normalized = [statement.lower() for statement in statements]
    history_tables = (
        "factor_position_fills",
        "factor_position_evidence_issues",
        "factor_position_grid_history",
        "execution_intent_resolutions",
        "execution_intent_reconciliations",
    )
    assert not any(
        statement.lstrip().startswith("select")
        and any(table in statement for table in history_tables)
        for statement in normalized
    )
    assert len(statements) <= 8
    access_paths = (
        (
            "SELECT owner_intent_id FROM execution_instrument_owners "
            "WHERE account_scope=? AND instrument=?",
            (_ACCOUNT, _INSTRUMENT),
        ),
        (
            "SELECT * FROM factor_position_current "
            "WHERE account_scope=? AND instrument=? AND exchange=?",
            (_ACCOUNT, _INSTRUMENT, _EXCHANGE),
        ),
        (
            "SELECT blocker_code,created_at_ns FROM factor_position_active_issues "
            "WHERE account_scope=? AND instrument=? AND exchange_key IN (?,?) "
            "ORDER BY created_at_ns DESC,receipt_id DESC LIMIT 1",
            (_ACCOUNT, _INSTRUMENT, _EXCHANGE, ""),
        ),
        (
            "SELECT * FROM factor_position_openings WHERE intent_id=?",
            (intent.intent_id,),
        ),
        (
            "SELECT ordinal,close_time FROM execution_grid_cursors "
            "WHERE account_scope=? AND strategy_scope=? AND cohort_id=?",
            (_ACCOUNT, _STRATEGY, _COHORT),
        ),
    )
    for sql, parameters in access_paths:
        plan = journal._connection.execute("EXPLAIN QUERY PLAN " + sql, parameters).fetchall()
        assert plan
        assert all("SCAN" not in row[3].upper() for row in plan), plan
        assert any("SEARCH" in row[3].upper() for row in plan), plan
    journal.close()


def test_contradictory_execution_replay_is_durable_and_blocks_nonflat_snapshot(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "positions.sqlite3")
    _key, intent = _new_open(journal)
    _make_open_fill(journal, intent_id=intent.intent_id, execution_id="trade-conflict")
    receipt, conflict = _new_callback(
        journal,
        intent.intent_id,
        callback_id="callback-conflict",
        execution_id="trade-conflict",
        quantity="1",
        price="3510",
        fee="2.5",
        filled_at_ns=_timestamp_ns(0, 30),
    )
    assert conflict.status == "BLOCKED"
    assert conflict.blocker_code == "EXECUTION_ID_CONFLICT"
    with journal._transaction() as cursor:
        replay = apply_factor_execution_fill(cursor, receipt_id=receipt.receipt_id)
    assert replay.status == "BLOCKED"
    assert replay.blocker_code == "EXECUTION_ID_CONFLICT"
    assert (
        journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decision_callbacks WHERE receipt_id=?",
            (receipt.receipt_id,),
        ).fetchone()[0]
        == 1
    )
    assert (
        journal._connection.execute(
            "SELECT COUNT(*) FROM factor_position_evidence_issues WHERE receipt_id=?",
            (receipt.receipt_id,),
        ).fetchone()[0]
        == 1
    )
    blocked = _snapshot(journal)
    assert blocked.status == "UNKNOWN"
    assert blocked.blocker_code == "EXECUTION_ID_CONFLICT"
    assert blocked.owner_intent_id == intent.intent_id
    assert blocked.average_price == Decimal("3500")
    _terminally_reconcile_open(journal, intent.intent_id, position_flat=True)
    reconciled_flat = _snapshot(
        journal,
        broker_quantity="0",
        long_quantity="0",
        short_quantity="0",
    )
    assert reconciled_flat.status == "FLAT"
    assert reconciled_flat.owner_intent_id is None
    journal.close()


def test_reconciled_flat_starts_new_risk_epoch_after_old_evidence_issue(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "positions.sqlite3")
    _old_key, old_intent = _new_open(journal)
    _make_open_fill(journal, intent_id=old_intent.intent_id, execution_id="old-position-trade")
    bad_receipt = journal.record_callback(
        old_intent.intent_id,
        "conflicting-old-fill",
        {
            "event_type": "execution_fill",
            "execution_id": "old-position-trade",
            "quantity": "1",
            "price": "3510",
            "fee": "1",
            "filled_at_ns": _timestamp_ns(0, 30),
            "exchange": _EXCHANGE,
        },
    )
    with journal._transaction() as cursor:
        conflict = apply_factor_execution_fill(cursor, receipt_id=bad_receipt.receipt_id)
    assert conflict.status == "BLOCKED"
    assert conflict.blocker_code == "EXECUTION_ID_CONFLICT"
    _terminally_reconcile_open(journal, old_intent.intent_id, position_flat=True)
    assert (
        _snapshot(
            journal,
            broker_quantity="0",
            long_quantity="0",
            short_quantity="0",
        ).status
        == "FLAT"
    )

    _new_key, new_intent = _new_open(
        journal,
        logical_run_id="run-after-flat",
        cohort_id="rb-cohort-after-flat",
        batch_id="batch-after-flat",
        grid_minute=2,
    )
    journal.claim_dispatch(new_intent.intent_id)
    new_receipt = journal.record_callback(
        new_intent.intent_id,
        "new-position-fill",
        {
            "event_type": "execution_fill",
            "execution_id": "new-position-trade",
            "quantity": "1",
            "price": "3510",
            "fee": "1",
            "filled_at_ns": _timestamp_ns(2, 30),
            "exchange": _EXCHANGE,
        },
    )
    with journal._transaction() as cursor:
        applied = apply_factor_execution_fill(cursor, receipt_id=new_receipt.receipt_id)
    assert applied.status == "APPLIED"

    snapshot = _snapshot(journal)
    assert snapshot.status == "MATCHED"
    assert snapshot.owner_intent_id == new_intent.intent_id
    assert snapshot.average_price == Decimal("3510")
    journal.close()


def test_known_terminal_flat_query_releases_unknown_dispatch_projection(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "positions.sqlite3")
    _key, intent = _new_open(journal)
    _make_open_fill(journal, intent_id=intent.intent_id)
    journal.claim_dispatch(intent.intent_id)
    journal.record_dispatch_result(intent.intent_id, state="UNKNOWN")
    reconciliation = journal.record_reconciliation(
        intent.intent_id,
        reconciliation_id="known-terminal-after-unknown-dispatch",
        query_id="provider-query-after-unknown-dispatch",
        state="KNOWN",
        provider_identity={"order": "source-reconciled"},
        terminal_state="CANCELLED",
        terminal_event_id="terminal-event-after-unknown-dispatch",
        position_snapshot_id="flat-position-after-unknown-dispatch",
        position_flat=True,
    )
    journal.release_instrument_owner(
        intent.intent_id, reconciliation_id=reconciliation.reconciliation_id
    )
    recovered_intent = journal.intent(intent.intent_id)
    assert recovered_intent.dispatch_state == "UNKNOWN"
    flat = _snapshot(
        journal,
        broker_quantity="0",
        long_quantity="0",
        short_quantity="0",
    )
    assert flat.status == "FLAT"
    assert flat.owner_intent_id is None
    journal.close()


def test_callback_receipt_and_fill_projection_rollback_together(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "positions.sqlite3")
    _key, intent = _new_open(journal)
    journal.claim_dispatch(intent.intent_id)
    with journal._transaction() as cursor:
        ensure_factor_position_book_schema(cursor)
    evidence = {
        "event_type": "execution_fill",
        "execution_id": "trade-atomic",
        "quantity": "1",
        "price": "3500",
        "fee": "2",
        "filled_at_ns": _timestamp_ns(0, 20),
        "exchange": _EXCHANGE,
    }
    receipt_id = "receipt-atomic"
    with pytest.raises(
        RuntimeError, match="crash after projection"
    ), journal._transaction() as cursor:
        cursor.execute(
            """INSERT INTO execution_decision_callbacks
               (receipt_id,intent_id,callback_id,evidence_payload_json,acknowledged,created_at_ns)
               VALUES (?,?,?,?,0,1)""",
            (
                receipt_id,
                intent.intent_id,
                "callback-atomic",
                json.dumps(evidence, sort_keys=True, separators=(",", ":")),
            ),
        )
        result = apply_factor_execution_fill(cursor, receipt_id=receipt_id)
        assert result.status == "APPLIED"
        raise RuntimeError("crash after projection")
    assert (
        journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decision_callbacks WHERE receipt_id=?", (receipt_id,)
        ).fetchone()[0]
        == 0
    )
    assert (
        journal._connection.execute(
            "SELECT COUNT(*) FROM factor_position_fills WHERE execution_id='trade-atomic'"
        ).fetchone()[0]
        == 0
    )
    journal.close()


def test_cancel_ack_is_not_a_fill_but_late_fill_keeps_original_owner(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "positions.sqlite3")
    _key, intent = _new_open(journal)
    status, no_fill = _new_callback(
        journal,
        intent.intent_id,
        callback_id="cancel-confirmed",
        execution_id="",
        quantity="0",
        price="0",
        fee="0",
        filled_at_ns=_timestamp_ns(0, 40),
        event_type="order_status",
    )
    assert no_fill.status == "NO_FILL"
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM factor_position_fills").fetchone()[0] == 0
    )
    _terminally_reconcile_open(journal, intent.intent_id, position_flat=False)
    _receipt, late_fill = _make_open_fill(
        journal, intent_id=intent.intent_id, execution_id="late-after-cancel"
    )
    assert late_fill.status == "APPLIED"
    snapshot = _snapshot(journal)
    assert snapshot.status == "MATCHED"
    assert snapshot.owner_intent_id == intent.intent_id
    assert snapshot.signed_quantity == Decimal("1")
    journal.close()


def test_late_fill_after_flat_reconciliation_keeps_original_owner(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "positions.sqlite3")
    _key, intent = _new_open(journal)
    _terminally_reconcile_open(journal, intent.intent_id, position_flat=True)
    _record_grid(journal, 2, 1)

    receipt, applied = _new_callback(
        journal,
        intent.intent_id,
        callback_id="late-after-flat",
        execution_id="late-after-flat-trade",
        quantity="1",
        price="3505",
        fee="1.5",
        filled_at_ns=_timestamp_ns(2, 30),
    )
    assert applied.status == "APPLIED"
    assert receipt.receipt_id

    snapshot = _snapshot(journal)
    assert snapshot.status == "MATCHED"
    assert snapshot.owner_intent_id == intent.intent_id
    assert snapshot.stop_price == Decimal("3450")
    assert snapshot.held_eligible_bars == 0
    journal.close()


def test_close_fill_reduces_owned_lot_and_reconciled_flat_clears_risk(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "positions.sqlite3")
    _open_key, opening = _new_open(journal)
    _make_open_fill(journal, intent_id=opening.intent_id)
    _terminally_reconcile_open(journal, opening.intent_id, position_flat=False)

    with journal._transaction() as cursor:
        validate_factor_position_close_owner(
            cursor,
            account_scope=_ACCOUNT,
            strategy_scope=_STRATEGY,
            instrument=_INSTRUMENT,
            exchange=_EXCHANGE,
            owner_intent_id=opening.intent_id,
        )
    close_key = ExecutionDecisionKey(
        account_scope=_ACCOUNT,
        strategy_scope=_STRATEGY,
        logical_run_id="run-1",
        cohort_id=_COHORT,
        close_time=_close_time(2),
        decision_kind="alpha003-risk-close",
    )
    close_intent_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument=_INSTRUMENT,
        side="SELL",
        position_effect="CLOSE",
        leg=0,
    )
    close_decision = journal.record_decision(
        close_key, {"batch_id": "batch-2"}, intent_keys=(close_intent_key,)
    )
    close_intent = journal.prepare_intent(
        close_decision.decision_id,
        close_intent_key,
        {
            "exchange": _EXCHANGE,
            "owner_intent_id": opening.intent_id,
            "owner_position_effect": "OPEN",
            "owner_side": "BUY",
            "quantity": "1",
            "price": "3490",
        },
        owner_intent_id=opening.intent_id,
    )
    with pytest.raises(
        FactorPositionBookError, match="CLOSE_OWNER_ALREADY_PENDING"
    ), journal._transaction() as cursor:
        validate_factor_position_close_owner(
            cursor,
            account_scope=_ACCOUNT,
            strategy_scope=_STRATEGY,
            instrument=_INSTRUMENT,
            exchange=_EXCHANGE,
            owner_intent_id=opening.intent_id,
        )
    journal.claim_dispatch(close_intent.intent_id)
    close_receipt = journal.record_callback(
        close_intent.intent_id,
        "close-trade-callback",
        {
            "event_type": "execution_fill",
            "execution_id": "trade-close-1",
            "quantity": "1",
            "price": "3490",
            "fee": "1.25",
            "filled_at_ns": _timestamp_ns(2, 10),
            "exchange": _EXCHANGE,
        },
    )
    with journal._transaction() as cursor:
        applied = apply_factor_execution_fill(cursor, receipt_id=close_receipt.receipt_id)
    assert applied.status == "APPLIED"
    journal.record_dispatch_result(
        close_intent.intent_id,
        state="KNOWN",
        provider_identity={"order": "close-native-1"},
    )
    close_reconciliation = journal.record_reconciliation(
        close_intent.intent_id,
        reconciliation_id="close-reconcile-1",
        query_id="close-query-1",
        state="KNOWN",
        provider_identity={"order": "close-native-1"},
        terminal_state="FILLED",
        terminal_event_id="close-terminal-1",
        position_snapshot_id="flat-snapshot-1",
        position_flat=True,
    )
    journal.release_instrument_owner(
        close_intent.intent_id,
        reconciliation_id=close_reconciliation.reconciliation_id,
    )
    flat = _snapshot(
        journal,
        broker_quantity="0",
        long_quantity="0",
        short_quantity="0",
    )
    assert flat.status == "FLAT"
    assert flat.owner_intent_id is None
    assert flat.stop_price is None
    assert flat.held_eligible_bars is None
    with pytest.raises(
        FactorPositionBookError, match="CLOSE_OWNER_FLAT"
    ), journal._transaction() as cursor:
        validate_factor_position_close_owner(
            cursor,
            account_scope=_ACCOUNT,
            strategy_scope=_STRATEGY,
            instrument=_INSTRUMENT,
            exchange=_EXCHANGE,
            owner_intent_id=opening.intent_id,
        )

    # A fresh eligible grid can prepare the next opening after the flat
    # reconciliation released the previous pending-order owner.
    next_key = ExecutionDecisionKey(
        account_scope=_ACCOUNT,
        strategy_scope=_STRATEGY,
        logical_run_id="run-1",
        cohort_id=_COHORT,
        close_time=_close_time(3),
        decision_kind="alpha003-rebalance",
    )
    _record_grid(journal, 2, 3)
    next_key_open = ExecutionIntentKey(
        action="SUBMIT",
        instrument=_INSTRUMENT,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    next_decision = journal.record_decision(
        next_key, {"batch_id": "batch-3"}, intent_keys=(next_key_open,)
    )
    next_intent = journal.prepare_intent(
        next_decision.decision_id,
        next_key_open,
        {
            "exchange": _EXCHANGE,
            "factor_stop_price": "3440",
            "risk_policy_id": "a003-risk-v1",
            "risk_policy": {"max_loss_per_position": "20", "stop_loss_ticks": 10},
            "batch_id": "batch-3",
            "quantity": "1",
            "price": "3500",
        },
    )
    assert next_intent.owner_intent_id is None
    assert (
        _snapshot(
            journal,
            broker_quantity="0",
            long_quantity="0",
            short_quantity="0",
        ).status
        == "UNKNOWN"
    )  # new intent is prepared but not terminally resolved
    journal.close()


def test_external_foreign_and_mismatched_positions_never_gain_attribution(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "positions.sqlite3")
    _key, intent = _new_open(journal)
    _make_open_fill(journal, intent_id=intent.intent_id)
    foreign = _snapshot(journal, strategy_scope="other-strategy")
    assert foreign.status == "FOREIGN_OWNER"
    assert foreign.owner_intent_id is None
    assert foreign.stop_price is None

    mismatch = _snapshot(journal, broker_quantity="2", long_quantity="2")
    assert mismatch.status == "BROKER_MISMATCH"
    assert mismatch.owner_intent_id is None
    ctp_mismatch = _snapshot(journal, broker_quantity="1", long_quantity="0", short_quantity="1")
    assert ctp_mismatch.status == "CTP_MISMATCH"
    journal.close()

    external = ExecutionDecisionJournal(tmp_path / "external.sqlite3")
    _snapshot_key, _intent = _new_open(external)
    # No execution callback was applied; a route-reported nonzero holding is
    # never adopted from a pending or acknowledged order intent.
    unknown = _snapshot(external)
    assert unknown.status == "UNKNOWN"
    assert unknown.owner_intent_id is None
    assert unknown.blocker_code == "INSTRUMENT_ORDER_UNRESOLVED"
    external.close()


def test_close_owner_rejects_unknown_or_flat_residual(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "positions.sqlite3")
    _key, intent = _new_open(journal)
    with pytest.raises(
        FactorPositionBookError, match="CLOSE_OWNER_QUANTITY_UNKNOWN"
    ), journal._transaction() as cursor:
        validate_factor_position_close_owner(
            cursor,
            account_scope=_ACCOUNT,
            strategy_scope=_STRATEGY,
            instrument=_INSTRUMENT,
            exchange=_EXCHANGE,
            owner_intent_id=intent.intent_id,
        )
    journal.close()
