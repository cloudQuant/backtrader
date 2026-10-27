"""Journal and position-book integration contracts for durable payload limits."""

from __future__ import annotations

import hashlib
import sqlite3
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backtrader.stores import factor_position_book as position_book_module
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
    ExecutionDecisionKey,
    ExecutionIntentKey,
)
from backtrader.stores.execution_durable_capacity import (
    canonical_sql_row_bytes,
    read_durable_capacity_usage,
)
from backtrader.stores.factor_position_book import (
    FactorPositionBook,
    _ctp_trade_time_ns,
    _record_open_intent_fill_total,
    apply_factor_execution_fill,
)


_ACCOUNT = "capacity-account"
_STRATEGY = "capacity-strategy"
_COHORT = "capacity-cohort"
_INSTRUMENT = "rb2701"
_EXCHANGE = "SHFE"


def _usage(journal: ExecutionDecisionJournal):
    """Read the typed v12 ledger under the journal's ordinary read lock."""

    with journal._read_lock():
        cursor = journal._connection.cursor()
        try:
            return read_durable_capacity_usage(cursor)
        finally:
            cursor.close()


def _restore_v11_journal_schema(connection: sqlite3.Connection) -> None:
    """Remove schema added after v11 before modeling a historical database."""

    for table in (
        "execution_fee_pair_candidate_capacity_reservations",
        "execution_fee_pair_candidate_events",
        "execution_fee_pair_candidates",
        "execution_fee_pair_scope_events",
        "execution_fee_pair_required_scopes",
        "execution_source_highwaters",
        "execution_run_loss_guards",
        "execution_durable_capacity_usage",
        "execution_durable_capacity_limits",
    ):
        connection.execute("DROP TABLE IF EXISTS " + table)
    connection.execute("PRAGMA user_version=11")


def _key(
    logical_run_id: str,
    *,
    cohort_id: str = _COHORT,
    close_time: str = "2026-10-24T09:00:00Z",
    decision_kind: str = "capacity-test",
) -> ExecutionDecisionKey:
    return ExecutionDecisionKey(
        account_scope=_ACCOUNT,
        strategy_scope=_STRATEGY,
        logical_run_id=logical_run_id,
        cohort_id=cohort_id,
        close_time=close_time,
        decision_kind=decision_kind,
    )


def _open_intent(
    journal: ExecutionDecisionJournal,
    *,
    instrument: str = _INSTRUMENT,
    logical_run_id: str = "capacity-open",
    order_ref: str = "8001",
    grid: bool = False,
) -> str:
    intent_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument=instrument,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    key = _key(logical_run_id)
    if grid:
        decision = journal.record_grid_decision(
            key,
            {"signal": "open", "risk_policy_id": "capacity-risk-v1"},
            intent_keys=(intent_key,),
            epoch_id="epoch-capacity-1",
            batch_id="batch-capacity-1",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
        ).decision
    else:
        decision = journal.record_decision(
            key,
            {"signal": "open", "risk_policy_id": "capacity-risk-v1"},
            intent_keys=(intent_key,),
        )
    intent = journal.prepare_intent(
        decision.decision_id,
        intent_key,
        {
            "exchange": _EXCHANGE,
            "quantity": "1",
            "price": "100",
            "factor_stop_price": "95",
            "risk_policy_id": "capacity-risk-v1",
            "risk_policy": {"max_loss_per_position": "5"},
        },
        original_identity={
            "operation": "insert",
            "instrument_id": instrument,
            "exchange_id": _EXCHANGE,
            "trading_day": "20261024",
            "order_ref": order_ref,
        },
    )
    return intent.intent_id


def _fill_settlement_with_close_decisions(
    journal: ExecutionDecisionJournal, *, limit: int, payload_chars: int = 64
) -> None:
    """Use ordinary immutable CLOSE decisions to consume the shared reserve."""

    for ordinal in range(limit):
        intent_key = ExecutionIntentKey(
            action="SUBMIT",
            instrument="settlement-{:04d}".format(ordinal),
            side="SELL",
            position_effect="CLOSE",
            leg=0,
        )
        try:
            journal.record_decision(
                _key("settlement-fill-{:04d}".format(ordinal)),
                {"reason": "bounded-reserve-fill", "padding": "x" * payload_chars},
                intent_keys=(intent_key,),
            )
        except ExecutionDecisionJournalError as error:
            assert error.code == "DURABLE_SETTLEMENT_BYTES_EXHAUSTED"
            return
    raise AssertionError("settlement byte budget did not exhaust within the bounded loop")


def test_post_rpc_outcome_uses_settlement_and_preserves_dispatch_fence_when_full(tmp_path):
    journal = ExecutionDecisionJournal(
        tmp_path / "post-rpc-settlement.sqlite3",
        max_durable_settlement_records=1000,
        max_durable_settlement_bytes=16_384,
    )
    try:
        intent_id = _open_intent(journal)
        usage_before_claim = _usage(journal)
        assert (
            usage_before_claim.base_records
            < journal.durable_capacity_limits.max_durable_base_records
        )
        assert (
            usage_before_claim.settlement_bytes
            < journal.durable_capacity_limits.max_durable_settlement_bytes
        )
        assert journal.claim_dispatch(intent_id) is not None

        # This models a provider leaf that returned after the durable claim.
        def fake_native_submit(intent):
            native_requests.append({"intent_id": intent.intent_id, "request_id": "native-8001"})

        native_requests = []
        fake_native_submit(journal.intent(intent_id))
        assert len(native_requests) == 1

        _fill_settlement_with_close_decisions(journal, limit=1000)
        usage_before_result = _usage(journal)
        assert (
            usage_before_result.settlement_bytes
            < journal.durable_capacity_limits.max_durable_settlement_bytes
        )

        with pytest.raises(
            ExecutionDecisionJournalError,
            match="DURABLE_SETTLEMENT_BYTES_EXHAUSTED",
        ):
            journal.record_dispatch_result(
                intent_id,
                state="KNOWN",
                provider_identity={"native_receipt": "x" * 32_000},
                outcome_code="accepted",
            )

        assert _usage(journal) == usage_before_result
        intent = journal.intent(intent_id)
        assert intent.state == "DISPATCHING"
        assert intent.dispatch_state is None
        assert intent.provider_identity is None
        persisted = journal._connection.execute(
            """SELECT dispatch_result_json,outcome_code FROM execution_decision_intents
               WHERE intent_id=?""",
            (intent_id,),
        ).fetchone()
        assert persisted["dispatch_result_json"] is None
        assert persisted["outcome_code"] is None
        assert journal.claim_dispatch(intent_id) is None
        assert len(native_requests) == 1
        assert journal._failed_closed is False
    finally:
        journal.close()


def test_existing_claim_can_persist_provider_outcome_after_base_budget_is_full(tmp_path):
    journal = ExecutionDecisionJournal(
        tmp_path / "base-full-settlement.sqlite3",
        max_durable_base_records=12,
        max_durable_base_bytes=1_000_000,
        max_durable_settlement_records=32,
        max_durable_settlement_bytes=100_000,
    )
    try:
        intent_id = _open_intent(journal, logical_run_id="base-full-open")
        assert journal.claim_dispatch(intent_id) is not None

        for ordinal in range(32):
            usage = _usage(journal)
            if usage.base_records == journal.durable_capacity_limits.max_durable_base_records:
                break
            journal.record_decision(
                _key("base-fill-{:04d}".format(ordinal)),
                {"signal": "flat"},
            )
        usage = _usage(journal)
        assert usage.base_records == journal.durable_capacity_limits.max_durable_base_records

        result = journal.record_dispatch_result(
            intent_id,
            state="KNOWN",
            provider_identity={"order_ref": "8001"},
            outcome_code="accepted",
        )
        assert result.state == "KNOWN"
        assert _usage(journal).base_records == usage.base_records
        assert _usage(journal).settlement_bytes > usage.settlement_bytes
    finally:
        journal.close()


def test_shared_position_book_dated_trade_insert_charges_settlement_atomically(
    monkeypatch, tmp_path
):
    journal = ExecutionDecisionJournal(
        tmp_path / "position-book-settlement.sqlite3",
        max_durable_settlement_records=1000,
        max_durable_settlement_bytes=32_768,
    )
    try:
        intent_id = _open_intent(journal, logical_run_id="dated-book-open", grid=True)
        assert journal.claim_dispatch(intent_id) is not None
        journal.record_dispatch_result(
            intent_id,
            state="KNOWN",
            provider_identity={"order_ref": "8001", "order_sys_id": "native-8001"},
        )

        execution_id = "ctp:20261024:trade-capacity-1"
        trade_id = "trade-capacity-1"
        observation_id = "observation-capacity-1"
        # CTP trade time is UTC+08; the exact UTC fill follows the 09:00 UTC
        # grid close by one second.
        trade_time = "17:00:01"
        trade_time_ns = _ctp_trade_time_ns("20261024", trade_time)
        assert trade_time_ns is not None
        source_values = {
            "account_scope": _ACCOUNT,
            "strategy_scope": _STRATEGY,
            "instrument": _INSTRUMENT,
            "exchange": _EXCHANGE,
            "trade_id": trade_id,
            "execution_id": execution_id,
            "intent_id": intent_id,
            "receipt_id": "pending-receipt-id",
            "order_ref": "8001",
            "order_sys_id": "native-8001",
            "order_side": "BUY",
            "position_effect": "OPEN",
            "position_side": "LONG",
            "hedge_flag": "1",
            "offset_flag": "0",
            "quantity": Decimal("1"),
            "price": Decimal("100"),
            "trading_day": "20261024",
            "trade_date": "20261024",
            "trade_time": trade_time,
            "trade_time_ns": trade_time_ns,
            "observation_id": observation_id,
            "query_set_id": "query-set-capacity-1",
            "snapshot_id": "snapshot-capacity-1",
            "request_id": 17,
            "connection_generation": 1,
            "account_fingerprint": "capacity-fingerprint",
            "available_at_ns": trade_time_ns + 1_000_000_000,
        }
        callback_id = "query-trade:" + hashlib.sha256(execution_id.encode("utf-8")).hexdigest()
        evidence = {
            "event_type": "execution_fill",
            "execution_id": execution_id,
            "provider_trade_id": trade_id,
            "order_ref": "8001",
            "instrument_id": _INSTRUMENT,
            "exchange": _EXCHANGE,
            "quantity": "1",
            "price": "100",
            "fee": None,
            "filled_at_ns": trade_time_ns,
            "order_sys_id": "native-8001",
            "evidence_kind": "complete_trades_query_observation",
            "time_source": "CTP_TradeDate_TradeTime_UTC_PLUS_08",
            "query_observation_id": observation_id,
            "snapshot_id": "snapshot-capacity-1",
            "request_id": 17,
            "connection_generation": 1,
            "account_fingerprint": "capacity-fingerprint",
            "trading_day": "20261024",
            "account_scope": _ACCOUNT,
            "strategy_scope": _STRATEGY,
        }
        receipt = journal.record_callback(intent_id, callback_id, evidence)
        source_values["receipt_id"] = receipt.receipt_id
        with journal._transaction() as cursor:
            applied = apply_factor_execution_fill(cursor, receipt_id=receipt.receipt_id)
            assert applied.status == "APPLIED"
            journal.acknowledge_callback_in_transaction(cursor, receipt.receipt_id)

        observation = {"observation_id": observation_id}
        page_item = {
            "observation_id": observation_id,
            "status": "APPLIED",
            "intent_id": intent_id,
            "receipt_id": receipt.receipt_id,
            "execution_id": execution_id,
            "blocker_code": None,
        }
        monkeypatch.setattr(
            position_book_module,
            "_dated_trade_page_inputs",
            lambda facts, page, *, limit, offset: (
                (observation,),
                (page_item,),
                {
                    "query_set_id": "query-set-capacity-1",
                    "observation_count": 1,
                    "offset": 0,
                    "next_offset": None,
                    "truncated": False,
                },
            ),
        )
        monkeypatch.setattr(
            position_book_module,
            "_dated_trade_source_values",
            lambda facts, obs, item, *, query_set_id: (source_values, None),
        )

        _fill_settlement_with_close_decisions(journal, limit=1000, payload_chars=16)
        before = _usage(journal)
        assert (
            before.settlement_bytes < journal.durable_capacity_limits.max_durable_settlement_bytes
        )

        with pytest.raises(
            ExecutionDecisionJournalError,
            match="DURABLE_SETTLEMENT_BYTES_EXHAUSTED",
        ):
            FactorPositionBook(journal).reconcile_dated_trade_observations(
                SimpleNamespace(), reconciliation_page=SimpleNamespace(), limit=1
            )

        after = _usage(journal)
        assert after == before
        assert (
            journal._connection.execute(
                "SELECT 1 FROM factor_position_dated_trade_facts WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
            is None
        )
        assert journal._failed_closed is False
    finally:
        journal.close()


def test_open_intent_fill_total_insert_is_settlement_budgeted(tmp_path):
    journal = ExecutionDecisionJournal(
        tmp_path / "open-intent-total-capacity.sqlite3",
        max_durable_settlement_records=1,
    )
    try:
        first_intent_id = _open_intent(journal, logical_run_id="open-total-first")
        second_intent_id = _open_intent(
            journal,
            instrument="cu2701",
            logical_run_id="open-total-second",
            order_ref="8002",
        )
        before = _usage(journal)
        assert before.settlement_records == 0

        def record_total(intent_id, instrument):
            with journal._transaction() as cursor:
                intent = cursor.execute(
                    "SELECT * FROM execution_decision_intents WHERE intent_id=?", (intent_id,)
                ).fetchone()
                assert intent is not None
                _record_open_intent_fill_total(
                    cursor,
                    intent=intent,
                    account_scope=_ACCOUNT,
                    strategy_scope=_STRATEGY,
                    instrument=instrument,
                    exchange=_EXCHANGE,
                    quantity=Decimal("1"),
                    updated_at_ns=1,
                )

        record_total(first_intent_id, _INSTRUMENT)
        after_first = _usage(journal)
        assert after_first.settlement_records == 1

        with pytest.raises(
            ExecutionDecisionJournalError,
            match="DURABLE_SETTLEMENT_RECORDS_EXHAUSTED",
        ):
            record_total(second_intent_id, "cu2701")

        assert _usage(journal) == after_first
        assert (
            journal._connection.execute(
                "SELECT 1 FROM factor_position_open_intent_totals WHERE intent_id=?",
                (second_intent_id,),
            ).fetchone()
            is None
        )
        assert journal._failed_closed is False
    finally:
        journal.close()


def test_v12_migration_rejects_ambiguous_grid_history_classification(tmp_path):
    path = tmp_path / "ambiguous-grid-history.sqlite3"
    journal = ExecutionDecisionJournal(path)
    try:
        key = _key("grid-history-source")
        journal.record_grid_decision(
            key,
            {"signal": "flat"},
            epoch_id="epoch-1",
            batch_id="batch-1",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
        )
        # This is a distinct immutable decision with the same exact join
        # identity, so a history row cannot be assigned by class alone.
        journal.record_decision(
            _key("grid-history-ambiguous", decision_kind=key.decision_kind),
            {"signal": "flat"},
        )
    finally:
        journal.close()

    with sqlite3.connect(path) as connection:
        _restore_v11_journal_schema(connection)

    with pytest.raises(ExecutionDecisionJournalError) as error:
        ExecutionDecisionJournal(path)
    assert error.value.code == "DURABLE_CAPACITY_CLASSIFICATION_INVALID"
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 11
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='execution_durable_capacity_usage'"
            ).fetchone()
            is None
        )


def test_v12_migration_assigns_ambiguous_dispatching_owner_to_settlement(tmp_path):
    path = tmp_path / "dispatching-capacity-classification.sqlite3"
    journal = ExecutionDecisionJournal(path)
    limits = journal.durable_capacity_limits
    intent_id = _open_intent(journal, logical_run_id="dispatching-migration")
    assert journal.claim_dispatch(intent_id) is not None
    journal.close()

    with sqlite3.connect(path) as connection:
        _restore_v11_journal_schema(connection)

    migrated = ExecutionDecisionJournal(
        path,
        max_durable_base_records=limits.max_durable_base_records,
        max_durable_base_bytes=limits.max_durable_base_bytes,
        max_durable_settlement_records=limits.max_durable_settlement_records,
        max_durable_settlement_bytes=limits.max_durable_settlement_bytes,
    )
    try:
        usage = _usage(migrated)
        assert usage.base_records == 4  # decision, slot, owner reservation, native identity
        assert usage.settlement_records == 1  # ambiguous DISPATCHING intent state
        assert migrated.intent(intent_id).state == "DISPATCHING"
        assert migrated.claim_dispatch(intent_id) is None
    finally:
        migrated.close()


def test_v12_migration_assigns_mixed_run_budget_snapshot_to_base(tmp_path):
    path = tmp_path / "mixed-run-budget-classification.sqlite3"
    journal = ExecutionDecisionJournal(path)
    try:
        open_key = _key("mixed-capacity-run", close_time="2026-10-24T09:00:00Z")
        close_key = _key("mixed-capacity-run", close_time="2026-10-24T09:01:00Z")
        journal.record_decision(
            open_key,
            {"signal": "open"},
            intent_keys=(
                ExecutionIntentKey(
                    action="SUBMIT",
                    instrument="rb2701",
                    side="BUY",
                    position_effect="OPEN",
                    leg=0,
                ),
            ),
        )
        journal.record_decision(
            close_key,
            {"signal": "close"},
            intent_keys=(
                ExecutionIntentKey(
                    action="SUBMIT",
                    instrument="rb2701",
                    side="SELL",
                    position_effect="CLOSE",
                    leg=0,
                ),
            ),
        )
        journal._connection.execute(
            """INSERT INTO execution_run_order_budgets
               (account_scope,strategy_scope,logical_run_id,max_intents,intent_count,created_at_ns)
               VALUES(?,?,?,?,?,?)""",
            (_ACCOUNT, _STRATEGY, "mixed-capacity-run", 4, 2, 1),
        )
    finally:
        journal.close()

    with sqlite3.connect(path) as connection:
        _restore_v11_journal_schema(connection)

    migrated = ExecutionDecisionJournal(path)
    try:
        usage = _usage(migrated)
        # The current aggregate budget payload is assigned once by the
        # documented migration convention; this does not reconstruct its
        # pre-v12 per-operation growth history.
        assert usage.base_records == 3  # BASE decision, slot, and run budget
        assert usage.settlement_records == 2  # SETTLEMENT decision and slot
        assert migrated.run_order_count(_ACCOUNT, _STRATEGY, "mixed-capacity-run") == 2
    finally:
        migrated.close()


def test_v12_migration_classifies_prepared_rows_by_intent_operation(tmp_path):
    path = tmp_path / "mixed-decision-intent-capacity-classification.sqlite3"
    journal = ExecutionDecisionJournal(path)
    limits = journal.durable_capacity_limits
    open_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument="rb2701",
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    close_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument="cu2701",
        side="SELL",
        position_effect="CLOSE",
        leg=1,
    )
    prepared_open_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument="ag2701",
        side="BUY",
        position_effect="OPEN",
        leg=2,
    )
    try:
        decision = journal.record_decision(
            _key("mixed-intent-capacity"),
            {"signal": "mixed"},
            intent_keys=(open_key, close_key, prepared_open_key),
        )
        assert (
            journal._connection.execute(
                "SELECT capacity_class FROM execution_decisions WHERE decision_id=?",
                (decision.decision_id,),
            ).fetchone()[0]
            == "BASE"
        )

        intents = {}
        for key, order_ref in (
            (open_key, "8101"),
            (close_key, "8102"),
            (prepared_open_key, "8103"),
        ):
            prepared = journal.prepare_intent(
                decision.decision_id,
                key,
                {"exchange": _EXCHANGE, "quantity": "1", "price": "100"},
                original_identity={
                    "operation": "insert",
                    "instrument_id": key.instrument,
                    "exchange_id": _EXCHANGE,
                    "trading_day": "20261024",
                    "order_ref": order_ref,
                },
            )
            intents[key.instrument] = prepared.intent_id

        assert journal.claim_dispatch(intents[open_key.instrument]) is not None
        journal.record_dispatch_result(
            intents[open_key.instrument],
            state="KNOWN",
            provider_identity={"order_ref": "8101"},
            outcome_code="accepted",
        )
        assert journal.intent(intents[close_key.instrument]).state == "PREPARED"
        assert journal.intent(intents[prepared_open_key.instrument]).state == "PREPARED"
    finally:
        journal.close()

    with sqlite3.connect(path) as connection:
        _restore_v11_journal_schema(connection)

    migrated = ExecutionDecisionJournal(
        path,
        max_durable_base_records=limits.max_durable_base_records,
        max_durable_base_bytes=limits.max_durable_base_bytes,
        max_durable_settlement_records=limits.max_durable_settlement_records,
        max_durable_settlement_bytes=limits.max_durable_settlement_bytes,
    )
    try:
        usage = _usage(migrated)
        assert usage.base_records == 9  # decision/slots, PREPARED OPEN, owners and identities
        assert usage.settlement_records == 4  # both intent rows, CLOSE owner and identity

        # The OPEN intent row itself is conservatively counted as settlement
        # after its ACK, while its admission metadata remains BASE. The other
        # OPEN intent stays PREPARED and BASE. The CLOSE intent and its
        # preparation metadata are SETTLEMENT even though the shared parent is
        # BASE.
        expected_base_rows = (
            migrated._connection.execute(
                "SELECT * FROM execution_decisions WHERE decision_id=?",
                (decision.decision_id,),
            ).fetchone(),
            *migrated._connection.execute(
                "SELECT * FROM execution_decision_slots WHERE decision_id=?",
                (decision.decision_id,),
            ).fetchall(),
            *(
                migrated._connection.execute(
                    "SELECT * FROM execution_instrument_owners WHERE owner_intent_id=?",
                    (intents[instrument],),
                ).fetchone()
                for instrument in (open_key.instrument, prepared_open_key.instrument)
            ),
            *(
                migrated._connection.execute(
                    "SELECT * FROM execution_native_intent_identities WHERE intent_id=?",
                    (intents[instrument],),
                ).fetchone()
                for instrument in (open_key.instrument, prepared_open_key.instrument)
            ),
            migrated._connection.execute(
                "SELECT * FROM execution_decision_intents WHERE intent_id=?",
                (intents[prepared_open_key.instrument],),
            ).fetchone(),
        )
        expected_settlement_rows = (
            migrated._connection.execute(
                "SELECT * FROM execution_decision_intents WHERE intent_id=?",
                (intents[open_key.instrument],),
            ).fetchone(),
            migrated._connection.execute(
                "SELECT * FROM execution_decision_intents WHERE intent_id=?",
                (intents[close_key.instrument],),
            ).fetchone(),
            migrated._connection.execute(
                "SELECT * FROM execution_instrument_owners WHERE owner_intent_id=?",
                (intents[close_key.instrument],),
            ).fetchone(),
            migrated._connection.execute(
                "SELECT * FROM execution_native_intent_identities WHERE intent_id=?",
                (intents[close_key.instrument],),
            ).fetchone(),
        )
        assert all(row is not None for row in expected_base_rows + expected_settlement_rows)
        assert usage.base_bytes == sum(
            len(canonical_sql_row_bytes(row)) for row in expected_base_rows
        )
        assert usage.settlement_bytes == sum(
            len(canonical_sql_row_bytes(row)) for row in expected_settlement_rows
        )
    finally:
        migrated.close()


def test_rollback_failure_latches_journal_after_capacity_exhaustion():
    journal = ExecutionDecisionJournal(":memory:", max_durable_base_records=1)
    journal.record_decision(_key("base-first"), {"signal": "flat"})
    connection = journal._connection

    def deny_rollback(action, argument, _database, _source, _trigger):
        if action == sqlite3.SQLITE_TRANSACTION and argument == "ROLLBACK":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    connection.set_authorizer(deny_rollback)
    try:
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="DURABLE_BASE_RECORDS_EXHAUSTED",
        ):
            journal.record_decision(_key("base-overflow"), {"signal": "flat"})
        assert journal._failed_closed is True
        connection.set_authorizer(None)
        with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_FAILED_CLOSED"):
            journal.record_decision(_key("after-rollback-failure"), {"signal": "flat"})
    finally:
        connection.set_authorizer(None)
        journal.close()
