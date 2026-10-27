"""Persistent run loss guard contracts for the execution decision journal."""

import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import (
    Clamped,
    Decimal,
    Inexact,
    Overflow,
    Rounded,
    Underflow,
    localcontext,
)

import pytest

import backtrader.stores.execution_decision_journal as journal_module
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
    ExecutionDecisionKey,
    ExecutionIntentKey,
    ExecutionRunLossGuardContext,
)
from backtrader.stores.execution_durable_capacity import (
    canonical_sql_row_bytes,
    read_durable_capacity_usage,
)


def _asof(seconds_ago=2):
    value = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _asof_at(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _context():
    return ExecutionRunLossGuardContext(
        account_scope="test-account",
        strategy_scope="alpha003",
        logical_run_id="run-loss-guard-test",
        trading_day="20261027",
        currency="CNY",
        pnl_basis="validated_total_net_after_fees_v1",
    )


def _decision_key(
    ordinal, decision_kind="ALPHA003_GRID", logical_run_id="run-loss-guard-test"
):
    return ExecutionDecisionKey(
        account_scope="test-account",
        strategy_scope="alpha003",
        logical_run_id=logical_run_id,
        cohort_id="cohort-{}".format(ordinal),
        close_time="2026-10-27T00:00:{:02d}Z".format(ordinal),
        decision_kind=decision_kind,
    )


def _open(instrument, leg=0):
    return ExecutionIntentKey(
        action="SUBMIT",
        instrument=instrument,
        side="BUY",
        position_effect="OPEN",
        leg=leg,
    )


def _enable(journal, context=None, *, baseline_asof=None, ttl=600):
    context = _context() if context is None else context
    baseline_asof = _asof(5) if baseline_asof is None else baseline_asof
    snapshot = journal.enable_run_loss_guard(
        context,
        baseline_observation_id="baseline-1",
        baseline_asof=baseline_asof,
        baseline_total_net_pnl=Decimal("10000.00"),
        net_loss_threshold=Decimal("1000"),
        max_observation_age_seconds=ttl,
    )
    return context, baseline_asof, snapshot


def _trip(journal, context):
    return journal.record_run_loss_observation(
        context,
        observation_id="pnl-1",
        asof=_asof(1),
        total_net_pnl=Decimal("9000"),
    )


def _usage(journal):
    with journal._read_lock():
        cursor = journal._connection.cursor()
        try:
            return read_durable_capacity_usage(cursor)
        finally:
            cursor.close()


def _guard_row(journal, context):
    with journal._read_lock():
        return journal._connection.execute(
            """SELECT * FROM execution_run_loss_guards
               WHERE account_scope=? AND strategy_scope=? AND logical_run_id=?""",
            (context.account_scope, context.strategy_scope, context.logical_run_id),
        ).fetchone()


def test_disabled_policy_keeps_existing_open_decision_prepare_and_dispatch(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "disabled.sqlite3")
    try:
        intent_key = _open("IF2601")
        decision = journal.record_decision(
            _decision_key(1), {}, intent_keys=(intent_key,)
        )
        prepared = journal.prepare_intent(decision.decision_id, intent_key, {})
        claim = journal.claim_dispatch(prepared.intent_id)

        assert claim is not None
        assert claim.intent.state == "DISPATCHING"
        assert journal.run_loss_guard(
            "test-account", "alpha003", "run-loss-guard-test"
        ) is None
    finally:
        journal.close()


def test_explicit_loss_guard_context_requires_policy_at_each_open_boundary(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "missing-policy.sqlite3")
    context = _context()
    try:
        with pytest.raises(
            ExecutionDecisionJournalError, match="RUN_LOSS_GUARD_NOT_CONFIGURED"
        ):
            journal.record_decision(
                _decision_key(1),
                {},
                intent_keys=(_open("IF2602"),),
                loss_guard_context=context,
            )

        prepare_key = _open("IF2603")
        prepare_decision = journal.record_decision(
            _decision_key(2), {}, intent_keys=(prepare_key,)
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="RUN_LOSS_GUARD_NOT_CONFIGURED"
        ):
            journal.prepare_intent(
                prepare_decision.decision_id,
                prepare_key,
                {},
                loss_guard_context=context,
            )

        claim_key = _open("IF2604")
        claim_decision = journal.record_decision(
            _decision_key(3), {}, intent_keys=(claim_key,)
        )
        claim_prepared = journal.prepare_intent(claim_decision.decision_id, claim_key, {})
        with pytest.raises(
            ExecutionDecisionJournalError, match="RUN_LOSS_GUARD_NOT_CONFIGURED"
        ):
            journal.claim_dispatch(claim_prepared.intent_id, loss_guard_context=context)

        legacy_key = _open("IF2605")
        legacy_decision = journal.record_decision(
            _decision_key(4), {}, intent_keys=(legacy_key,)
        )
        legacy_prepared = journal.prepare_intent(
            legacy_decision.decision_id, legacy_key, {}
        )
        assert journal.claim_dispatch(legacy_prepared.intent_id) is not None
        assert journal.run_loss_guard(
            context.account_scope, context.strategy_scope, context.logical_run_id
        ) is None
    finally:
        journal.close()


def test_trip_latches_across_reopen_and_only_latest_observation_replays(tmp_path):
    database = tmp_path / "trip.sqlite3"
    journal = ExecutionDecisionJournal(database)
    context, baseline_asof, initial = _enable(journal)
    tripped = _trip(journal, context)
    assert not initial.tripped
    assert tripped.tripped
    assert tripped.total_net_loss_from_baseline == Decimal("1000")

    replay = journal.record_run_loss_observation(
        context,
        observation_id="pnl-1",
        asof=tripped.latest_asof,
        total_net_pnl=Decimal("9000.00"),
    )
    assert replay == tripped
    with pytest.raises(ExecutionDecisionJournalError, match="RUN_LOSS_OBSERVATION_CONFLICT"):
        journal.record_run_loss_observation(
            context,
            observation_id="pnl-1",
            asof=tripped.latest_asof,
            total_net_pnl=Decimal("9001"),
        )
    with pytest.raises(
        ExecutionDecisionJournalError, match="RUN_LOSS_OBSERVATION_NOT_MONOTONE"
    ):
        journal.record_run_loss_observation(
            context,
            observation_id="baseline-1",
            asof=baseline_asof,
            total_net_pnl=Decimal("10000"),
        )

    journal.close()
    reopened = ExecutionDecisionJournal(database)
    try:
        persisted = reopened.run_loss_guard(
            "test-account", "alpha003", "run-loss-guard-test"
        )
        assert persisted is not None and persisted.tripped
        same_policy = reopened.enable_run_loss_guard(
            context,
            baseline_observation_id="baseline-1",
            baseline_asof=baseline_asof,
            baseline_total_net_pnl=Decimal("10000"),
            net_loss_threshold=Decimal("1000.00"),
            max_observation_age_seconds=600,
        )
        assert same_policy.tripped
        with pytest.raises(
            ExecutionDecisionJournalError, match="RUN_TOTAL_NET_LOSS_LIMIT_REACHED"
        ):
            reopened.record_decision(
                _decision_key(2),
                {},
                intent_keys=(_open("IF2602"),),
                loss_guard_context=context,
            )
        assert reopened.run_loss_guard(
            "test-account", "alpha003", "run-loss-guard-test"
        ).tripped

        risk_key = _decision_key(3, "RISK_REDUCTION")
        close = ExecutionIntentKey("SUBMIT", "IF2601", "SELL", "CLOSE", 0)
        cancel = ExecutionIntentKey("CANCEL", "IF2603", "BUY", "OPEN", 1)
        risk = reopened.record_risk_decision(
            risk_key,
            {"reason": "independent-risk-reduction"},
            intent_keys=(close, cancel),
            max_order_intents_per_run=8,
            expected_run_order_intents_used=0,
            remaining_exit_intent_reserve=0,
        )
        assert risk.decision is not None
    finally:
        reopened.close()


def test_loss_guard_checks_decision_prepare_dispatch_and_preserves_unknown(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "stages.sqlite3")
    try:
        context, _baseline_asof, _initial = _enable(journal)
        prepare_key = _open("IF2604")
        prepare_decision = journal.record_decision(
            _decision_key(1), {}, intent_keys=(prepare_key,), loss_guard_context=context
        )
        dispatch_key = _open("IF2605")
        dispatch_decision = journal.record_decision(
            _decision_key(2), {}, intent_keys=(dispatch_key,), loss_guard_context=context
        )
        dispatch_prepared = journal.prepare_intent(
            dispatch_decision.decision_id, dispatch_key, {}, loss_guard_context=context
        )
        unknown_key = _open("IF2606")
        unknown_decision = journal.record_decision(
            _decision_key(3), {}, intent_keys=(unknown_key,), loss_guard_context=context
        )
        unknown_prepared = journal.prepare_intent(
            unknown_decision.decision_id, unknown_key, {}, loss_guard_context=context
        )
        assert journal.claim_dispatch(
            unknown_prepared.intent_id, loss_guard_context=context
        ) is not None
        unknown = journal.record_dispatch_result(
            unknown_prepared.intent_id, state="UNKNOWN", outcome_code="response-ambiguous"
        )

        assert _trip(journal, context).tripped
        with pytest.raises(
            ExecutionDecisionJournalError, match="RUN_TOTAL_NET_LOSS_LIMIT_REACHED"
        ):
            journal.record_grid_decision(
                _decision_key(4),
                {},
                intent_keys=(_open("IF2607"),),
                epoch_id="epoch-4",
                batch_id="batch-4",
                eligible=True,
                complete=True,
                live_ready=True,
                inputs_complete=True,
                loss_guard_context=context,
            )
        with pytest.raises(
            ExecutionDecisionJournalError, match="RUN_TOTAL_NET_LOSS_LIMIT_REACHED"
        ):
            journal.prepare_intent(
                prepare_decision.decision_id,
                prepare_key,
                {},
                loss_guard_context=context,
            )
        with pytest.raises(
            ExecutionDecisionJournalError, match="RUN_TOTAL_NET_LOSS_LIMIT_REACHED"
        ):
            journal.claim_dispatch(
                dispatch_prepared.intent_id, loss_guard_context=context
            )
        assert journal.intent(dispatch_prepared.intent_id).state == "PREPARED"

        # UNKNOWN is neither reset nor claimed again; recovery keeps its ID.
        assert journal.claim_dispatch(unknown_prepared.intent_id) is None
        current_unknown = journal.intent(unknown_prepared.intent_id)
        assert current_unknown.state == "UNKNOWN"
        assert current_unknown.intent_id == unknown.intent_id
    finally:
        journal.close()


def test_context_and_clock_freshness_are_required_at_each_boundary(tmp_path, monkeypatch):
    journal = ExecutionDecisionJournal(tmp_path / "freshness.sqlite3")
    try:
        context, _baseline_asof, _initial = _enable(journal, ttl=30)
        prepared_key = _open("IF2608")
        prepared_decision = journal.record_decision(
            _decision_key(1), {}, intent_keys=(prepared_key,), loss_guard_context=context
        )
        prepared = journal.prepare_intent(
            prepared_decision.decision_id, prepared_key, {}, loss_guard_context=context
        )
        not_prepared_key = _open("IF2611")
        not_prepared_decision = journal.record_decision(
            _decision_key(4),
            {},
            intent_keys=(not_prepared_key,),
            loss_guard_context=context,
        )
        wrong_context = ExecutionRunLossGuardContext(
            account_scope=context.account_scope,
            strategy_scope=context.strategy_scope,
            logical_run_id=context.logical_run_id,
            trading_day=context.trading_day,
            currency=context.currency,
            pnl_basis="different_basis",
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="RUN_LOSS_GUARD_CONTEXT_MISMATCH"
        ):
            journal.record_decision(
                _decision_key(2),
                {},
                intent_keys=(_open("IF2608"),),
                loss_guard_context=wrong_context,
            )
        mismatched_run_key = ExecutionDecisionKey(
            account_scope=context.account_scope,
            strategy_scope=context.strategy_scope,
            logical_run_id="different-run",
            cohort_id="other-cohort",
            close_time="2026-10-27T00:00:02Z",
            decision_kind="ALPHA003_GRID",
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="RUN_LOSS_GUARD_CONTEXT_MISMATCH"
        ):
            journal.record_decision(
                mismatched_run_key,
                {},
                intent_keys=(_open("IF2610"),),
                loss_guard_context=context,
            )

        real_datetime = journal_module.datetime

        class AdvancedClockDateTime(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return real_datetime.now(tz) + timedelta(seconds=31)

        monkeypatch.setattr(journal_module, "datetime", AdvancedClockDateTime)
        with pytest.raises(ExecutionDecisionJournalError, match="RUN_LOSS_OBSERVATION_STALE"):
            journal.record_run_loss_observation(
                context,
                observation_id="stale-pnl",
                asof=_asof(1),
                total_net_pnl=Decimal("9999"),
            )
        with pytest.raises(ExecutionDecisionJournalError, match="RUN_LOSS_OBSERVATION_STALE"):
            journal.record_decision(
                _decision_key(3),
                {},
                intent_keys=(_open("IF2609"),),
                loss_guard_context=context,
            )
        with pytest.raises(ExecutionDecisionJournalError, match="RUN_LOSS_OBSERVATION_STALE"):
            journal.prepare_intent(
                not_prepared_decision.decision_id,
                not_prepared_key,
                {},
                loss_guard_context=context,
            )
        # Exact prepared readback is recovery, not a new OPEN admission.
        assert (
            journal.prepare_intent(
                prepared_decision.decision_id,
                prepared_key,
                {},
                loss_guard_context=context,
            )
            == prepared
        )
        with pytest.raises(ExecutionDecisionJournalError, match="RUN_LOSS_OBSERVATION_STALE"):
            journal.claim_dispatch(prepared.intent_id, loss_guard_context=context)
        assert journal.intent(prepared.intent_id).state == "PREPARED"
    finally:
        journal.close()


def test_fractional_asof_order_is_compared_as_instants(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "fractional-asof.sqlite3")
    try:
        context = _context()
        baseline_time = (datetime.now(timezone.utc) - timedelta(seconds=5)).replace(
            microsecond=0
        )
        latest_time = baseline_time + timedelta(milliseconds=123)
        baseline_asof = baseline_time.isoformat(timespec="seconds").replace("+00:00", "Z")
        latest_asof = latest_time.isoformat(timespec="microseconds").replace("+00:00", "Z")
        journal.enable_run_loss_guard(
            context,
            baseline_observation_id="baseline-1",
            baseline_asof=baseline_asof,
            baseline_total_net_pnl=Decimal("10000"),
            net_loss_threshold=Decimal("1000"),
            max_observation_age_seconds=30,
        )

        saved = journal.record_run_loss_observation(
            context,
            observation_id="fractional-1",
            asof=latest_asof,
            total_net_pnl=Decimal("9999"),
        )
        reloaded = journal.run_loss_guard(
            context.account_scope, context.strategy_scope, context.logical_run_id
        )
        assert saved.latest_asof == latest_asof
        assert reloaded == saved
    finally:
        journal.close()


@pytest.mark.parametrize(
    "field,value,expected",
    (
        ("baseline_total_net_pnl", 10000.0, "INVALID_RUN_LOSS_PNL"),
        ("baseline_total_net_pnl", Decimal("NaN"), "INVALID_RUN_LOSS_PNL"),
        ("net_loss_threshold", Decimal("Infinity"), "INVALID_RUN_LOSS_THRESHOLD"),
        ("max_observation_age_seconds", True, "INVALID_RUN_LOSS_TTL"),
    ),
)
def test_policy_requires_exact_finite_decimal_and_integer_inputs(
    tmp_path, field, value, expected
):
    journal = ExecutionDecisionJournal(tmp_path / "types.sqlite3")
    try:
        context = _context()
        kwargs = {
            "baseline_observation_id": "baseline-1",
            "baseline_asof": _asof(1),
            "baseline_total_net_pnl": Decimal("10000"),
            "net_loss_threshold": Decimal("1000"),
            "max_observation_age_seconds": 600,
        }
        kwargs[field] = value
        with pytest.raises(ExecutionDecisionJournalError, match=expected):
            journal.enable_run_loss_guard(context, **kwargs)
        kwargs = {
            "baseline_observation_id": "baseline-1",
            "baseline_asof": _asof(1),
            "baseline_total_net_pnl": Decimal("10000"),
            "net_loss_threshold": Decimal("1000"),
            "max_observation_age_seconds": 600,
        }
        valid_context, _baseline_asof, _snapshot = _enable(
            journal, baseline_asof=kwargs["baseline_asof"]
        )
        with pytest.raises(ExecutionDecisionJournalError, match="INVALID_RUN_LOSS_PNL"):
            journal.record_run_loss_observation(
                valid_context,
                observation_id="invalid-pnl",
                asof=_asof(0),
                total_net_pnl=9999.0,
            )
    finally:
        journal.close()


def test_first_enable_rejects_prior_open_but_allows_noop_close_and_cancel(tmp_path):
    context = _context()
    prior_open = ExecutionDecisionJournal(tmp_path / "late-open.sqlite3")
    try:
        prior_open.record_decision(
            _decision_key(1), {}, intent_keys=(_open("IF2710"),)
        )
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="RUN_LOSS_GUARD_LATE_ENABLE_AFTER_OPEN",
        ):
            _enable(prior_open, context)
        assert prior_open.run_loss_guard(
            context.account_scope, context.strategy_scope, context.logical_run_id
        ) is None
    finally:
        prior_open.close()

    history_only = ExecutionDecisionJournal(tmp_path / "late-non-open.sqlite3")
    try:
        history_only.record_decision(_decision_key(1), {})
        history_only.record_decision(
            _decision_key(2),
            {},
            intent_keys=(
                ExecutionIntentKey("SUBMIT", "IF2711", "SELL", "CLOSE", 0),
                ExecutionIntentKey("CANCEL", "IF2712", "BUY", "OPEN", 1),
            ),
        )
        _baseline_context, baseline_asof, _initial = _enable(history_only, context)
        # Exact policy re-open is not a new baseline or an admission scan.
        assert (
            _enable(history_only, context, baseline_asof=baseline_asof)[2]
            .baseline_observation_id
            == "baseline-1"
        )
    finally:
        history_only.close()


def test_first_enable_scan_fails_closed_at_fixed_row_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(journal_module, "_MAX_RUN_LOSS_ENABLE_SCAN_ROWS", 2)
    journal = ExecutionDecisionJournal(tmp_path / "scan-limit.sqlite3")
    try:
        for ordinal in range(1, 4):
            journal.record_decision(_decision_key(ordinal), {})
        with pytest.raises(
            ExecutionDecisionJournalError, match="RUN_LOSS_GUARD_ENABLE_SCAN_LIMIT"
        ):
            _enable(journal)
        assert journal.run_loss_guard(
            "test-account", "alpha003", "run-loss-guard-test"
        ) is None
    finally:
        journal.close()


def test_schema_v12_upgrade_preserves_usage_and_loss_row_is_settlement(tmp_path):
    path = tmp_path / "schema-v12-upgrade.sqlite3"
    context = _context()
    journal = ExecutionDecisionJournal(path)
    base_key = _decision_key(1)
    settlement_key = _decision_key(2)
    close_key = ExecutionIntentKey("SUBMIT", "IF2720", "SELL", "CLOSE", 0)
    journal.record_decision(base_key, {"legacy": "base"})
    journal.record_decision(
        settlement_key, {"legacy": "settlement"}, intent_keys=(close_key,)
    )
    before = _usage(journal)
    journal.close()

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE execution_run_loss_guards")
        connection.execute("DROP TABLE execution_source_highwaters")
        connection.execute("PRAGMA user_version=12")

    migrated = ExecutionDecisionJournal(path)
    try:
        assert migrated._connection.execute("PRAGMA user_version").fetchone()[0] == 14
        assert _usage(migrated) == before
        assert migrated.record_decision(base_key, {"legacy": "base"}).key == base_key
        assert migrated.record_decision(
            settlement_key, {"legacy": "settlement"}, intent_keys=(close_key,)
        ).key == settlement_key

        _enable(migrated, context)
        after_enable = _usage(migrated)
        row = _guard_row(migrated, context)
        assert row is not None
        assert after_enable.base_records == before.base_records
        assert after_enable.settlement_records == before.settlement_records + 1
        assert after_enable.settlement_bytes == before.settlement_bytes + len(
            canonical_sql_row_bytes(row)
        )
        assert migrated._connection.execute(
            "SELECT COUNT(*) FROM execution_run_loss_guards"
        ).fetchone()[0] == 1

        for observation_id, age, pnl in (
            ("observation-1", 3, Decimal("9999")),
            ("observation-2", 1, Decimal("9000")),
        ):
            before_usage = _usage(migrated)
            before_bytes = len(canonical_sql_row_bytes(_guard_row(migrated, context)))
            migrated.record_run_loss_observation(
                context,
                observation_id=observation_id,
                asof=_asof(age),
                total_net_pnl=pnl,
            )
            updated_row = _guard_row(migrated, context)
            updated_bytes = len(canonical_sql_row_bytes(updated_row))
            after_usage = _usage(migrated)
            assert after_usage.base_records == before_usage.base_records
            assert after_usage.settlement_records == before_usage.settlement_records
            assert after_usage.settlement_bytes == before_usage.settlement_bytes + max(
                0, updated_bytes - before_bytes
            )
            assert migrated._connection.execute(
                "SELECT COUNT(*) FROM execution_run_loss_guards"
            ).fetchone()[0] == 1
    finally:
        migrated.close()


@pytest.mark.parametrize("missing_schema", ("callback", "disposition"))
def test_corrupt_v12_callback_delivery_schema_is_rejected(tmp_path, missing_schema):
    path = tmp_path / "corrupt-v12-{}-schema.sqlite3".format(missing_schema)
    journal = ExecutionDecisionJournal(path)
    journal.close()

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE execution_callback_query_dispositions")
        connection.execute("DROP TABLE execution_decision_callbacks")
        callback_process_column = (
            "" if missing_schema == "callback" else ", process_instance_id TEXT"
        )
        disposition_proof_column = (
            "" if missing_schema == "disposition" else ", proof_sha256 TEXT NOT NULL"
        )
        connection.execute(
            """CREATE TABLE execution_decision_callbacks (
                receipt_id TEXT PRIMARY KEY,
                intent_id TEXT NOT NULL,
                callback_id TEXT NOT NULL,
                evidence_payload_json TEXT NOT NULL,
                acknowledged INTEGER NOT NULL CHECK(acknowledged IN (0,1)),
                created_at_ns INTEGER NOT NULL{callback_process_column},
                delivery_pending INTEGER NOT NULL DEFAULT 1
                    CHECK(delivery_pending IN (0,1)),
                UNIQUE(intent_id, callback_id)
            )""".format(callback_process_column=callback_process_column)
        )
        connection.execute(
            """CREATE TABLE execution_callback_query_dispositions (
                native_receipt_id TEXT PRIMARY KEY,
                query_receipt_id TEXT NOT NULL UNIQUE,
                intent_id TEXT NOT NULL,
                execution_id TEXT NOT NULL,
                disposition_code TEXT NOT NULL,
                query_process_instance_id TEXT NOT NULL,
                proof_payload_json TEXT NOT NULL{disposition_proof_column},
                created_at_ns INTEGER NOT NULL
            )""".format(disposition_proof_column=disposition_proof_column)
        )
        connection.execute("PRAGMA user_version=12")

    with pytest.raises(
        ExecutionDecisionJournalError, match="CALLBACK_DELIVERY_SCHEMA_CORRUPT"
    ):
        ExecutionDecisionJournal(path)


@pytest.mark.parametrize(
    "loss,pnl,expected_trip",
    (
        (Decimal("999.99"), Decimal("9000.01"), False),
        (Decimal("1000"), Decimal("9000"), True),
        (Decimal("1000.01"), Decimal("8999.99"), True),
    ),
)
def test_loss_threshold_uses_exact_decimal_boundary(tmp_path, loss, pnl, expected_trip):
    journal = ExecutionDecisionJournal(tmp_path / ("threshold-{}.sqlite3".format(loss)))
    try:
        context = _context()
        baseline_asof = _asof(5)
        journal.enable_run_loss_guard(
            context,
            baseline_observation_id="baseline-1",
            baseline_asof=baseline_asof,
            baseline_total_net_pnl=Decimal("10000.00"),
            net_loss_threshold=Decimal("1000"),
            max_observation_age_seconds=600,
        )
        snapshot = journal.record_run_loss_observation(
            context,
            observation_id="threshold-observation",
            asof=_asof(1),
            total_net_pnl=pnl,
        )
        assert snapshot.total_net_loss_from_baseline == loss
        assert snapshot.tripped is expected_trip
    finally:
        journal.close()


def test_exact_loss_subtraction_ignores_narrow_ambient_decimal_context(tmp_path):
    expected_extreme = Decimal((0, (1,) + (0,) * 1999 + (1,), -1000))
    journal = ExecutionDecisionJournal(tmp_path / "narrow-decimal-context.sqlite3")
    try:
        context = _context()
        journal.enable_run_loss_guard(
            context,
            baseline_observation_id="baseline-1",
            baseline_asof=_asof(5),
            baseline_total_net_pnl=Decimal("10000.00"),
            net_loss_threshold=Decimal("1000"),
            max_observation_age_seconds=600,
        )
        with localcontext() as ambient:
            ambient.prec = 3
            ambient.Emax = 2
            ambient.Emin = -2
            ambient.clamp = 1
            for signal in (Clamped, Inexact, Overflow, Rounded, Underflow):
                ambient.traps[signal] = True
            assert journal_module._exact_run_loss_difference(
                Decimal("10000.00"), Decimal("8999.99")
            ) == Decimal("1000.01")
            assert journal_module._exact_run_loss_difference(
                Decimal("1e1000"), Decimal("-1e-1000")
            ) == expected_extreme
            snapshot = journal.record_run_loss_observation(
                context,
                observation_id="threshold-observation",
                asof=_asof(1),
                total_net_pnl=Decimal("8999.99"),
            )
            assert snapshot.total_net_loss_from_baseline == Decimal("1000.01")
            assert snapshot.tripped is True
    finally:
        journal.close()


def test_close_and_cancel_prepare_and_claim_remain_available_after_trip(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "risk-after-trip.sqlite3")
    try:
        context, _baseline_asof, _initial = _enable(journal)
        open_key = _open("IF2730")
        open_decision = journal.record_decision(
            _decision_key(1), {}, intent_keys=(open_key,), loss_guard_context=context
        )
        opened = journal.prepare_intent(
            open_decision.decision_id, open_key, {}, loss_guard_context=context
        )
        assert journal.claim_dispatch(opened.intent_id, loss_guard_context=context) is not None
        journal.record_dispatch_result(
            opened.intent_id, state="KNOWN", provider_identity={"order": "open-1"}
        )
        assert _trip(journal, context).tripped

        close_key = ExecutionIntentKey("SUBMIT", "IF2731", "SELL", "CLOSE", 0)
        cancel_key = ExecutionIntentKey("CANCEL", "IF2730", "BUY", "OPEN", 1)
        risk = journal.record_risk_decision(
            _decision_key(2, "RISK_REDUCTION"),
            {"reason": "bounded-close-and-cancel"},
            intent_keys=(close_key, cancel_key),
            max_order_intents_per_run=8,
            expected_run_order_intents_used=0,
            remaining_exit_intent_reserve=0,
        )
        close = journal.prepare_intent(risk.decision.decision_id, close_key, {})
        assert journal.claim_dispatch(close.intent_id) is not None
        journal.record_dispatch_result(close.intent_id, state="KNOWN", provider_identity={})

        cancel = journal.prepare_intent(
            risk.decision.decision_id,
            cancel_key,
            {},
            owner_intent_id=opened.intent_id,
        )
        assert journal.claim_dispatch(cancel.intent_id) is not None
        assert journal.intent(close.intent_id).state == "KNOWN"
        assert journal.intent(cancel.intent_id).state == "DISPATCHING"
    finally:
        journal.close()


def test_exact_existing_decision_and_prepare_replay_after_trip_but_new_admission_fails(
    tmp_path,
):
    journal = ExecutionDecisionJournal(tmp_path / "readback-after-trip.sqlite3")
    try:
        context, _baseline_asof, _initial = _enable(journal)
        existing_key = _open("IF2740")
        existing_decision = journal.record_decision(
            _decision_key(1), {}, intent_keys=(existing_key,), loss_guard_context=context
        )
        existing_prepared = journal.prepare_intent(
            existing_decision.decision_id, existing_key, {}, loss_guard_context=context
        )
        unprepared_key = _open("IF2741")
        unprepared_decision = journal.record_decision(
            _decision_key(2), {}, intent_keys=(unprepared_key,), loss_guard_context=context
        )
        assert _trip(journal, context).tripped

        assert journal.record_decision(
            existing_decision.key,
            {},
            intent_keys=(existing_key,),
            loss_guard_context=context,
        ) == existing_decision
        assert journal.prepare_intent(
            existing_decision.decision_id,
            existing_key,
            {},
            loss_guard_context=context,
        ) == existing_prepared
        with pytest.raises(
            ExecutionDecisionJournalError, match="RUN_TOTAL_NET_LOSS_LIMIT_REACHED"
        ):
            journal.record_decision(
                _decision_key(3),
                {},
                intent_keys=(_open("IF2742"),),
                loss_guard_context=context,
            )
        with pytest.raises(
            ExecutionDecisionJournalError, match="RUN_TOTAL_NET_LOSS_LIMIT_REACHED"
        ):
            journal.prepare_intent(
                unprepared_decision.decision_id,
                unprepared_key,
                {},
                loss_guard_context=context,
            )
    finally:
        journal.close()


@pytest.mark.parametrize("already_tripped", (False, True))
def test_restart_observation_refreshes_stale_guard_without_clearing_trip(
    tmp_path, monkeypatch, already_tripped
):
    path = tmp_path / "restart-{}.sqlite3".format(already_tripped)
    journal = ExecutionDecisionJournal(path)
    context = _context()
    if already_tripped:
        context = ExecutionRunLossGuardContext(
            account_scope=context.account_scope,
            strategy_scope=context.strategy_scope,
            logical_run_id="run-loss-guard-tripped-restart",
            trading_day=context.trading_day,
            currency=context.currency,
            pnl_basis=context.pnl_basis,
        )
    _enable(journal, context, ttl=30)
    if already_tripped:
        _trip(journal, context)
    journal.close()

    reopened = ExecutionDecisionJournal(path)
    try:
        real_datetime = journal_module.datetime

        class AdvancedClockDateTime(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return real_datetime.now(tz) + timedelta(seconds=31)

        monkeypatch.setattr(journal_module, "datetime", AdvancedClockDateTime)
        fresh_key = _open("IF2750")
        with pytest.raises(
            ExecutionDecisionJournalError, match="RUN_LOSS_OBSERVATION_STALE"
        ):
            reopened.record_decision(
                _decision_key(1, logical_run_id=context.logical_run_id),
                {},
                intent_keys=(fresh_key,),
                loss_guard_context=context,
            )

        refreshed = reopened.record_run_loss_observation(
            context,
            observation_id="restart-refresh",
            asof=_asof_at(real_datetime.now(timezone.utc) + timedelta(seconds=29)),
            total_net_pnl=Decimal("9999"),
        )
        assert refreshed.tripped is already_tripped
        if already_tripped:
            with pytest.raises(
                ExecutionDecisionJournalError, match="RUN_TOTAL_NET_LOSS_LIMIT_REACHED"
            ):
                reopened.record_decision(
                    _decision_key(1, logical_run_id=context.logical_run_id),
                    {},
                    intent_keys=(fresh_key,),
                    loss_guard_context=context,
                )
        else:
            assert reopened.record_decision(
                _decision_key(1, logical_run_id=context.logical_run_id),
                {},
                intent_keys=(fresh_key,),
                loss_guard_context=context,
            ).intent_keys == (fresh_key,)
    finally:
        reopened.close()


def test_other_journal_connection_committed_trip_blocks_prepared_open_claim(tmp_path):
    path = tmp_path / "two-connections.sqlite3"
    first = ExecutionDecisionJournal(path)
    second = ExecutionDecisionJournal(path)
    try:
        context, _baseline_asof, _initial = _enable(first)
        key = _open("IF2760")
        decision = first.record_decision(
            _decision_key(1), {}, intent_keys=(key,), loss_guard_context=context
        )
        prepared = first.prepare_intent(
            decision.decision_id, key, {}, loss_guard_context=context
        )
        assert _trip(second, context).tripped
        with pytest.raises(
            ExecutionDecisionJournalError, match="RUN_TOTAL_NET_LOSS_LIMIT_REACHED"
        ):
            first.claim_dispatch(prepared.intent_id, loss_guard_context=context)
        assert first.intent(prepared.intent_id).state == "PREPARED"
    finally:
        first.close()
        second.close()


def test_schema_v13_loss_guard_table_without_composite_primary_key_is_rejected(tmp_path):
    path = tmp_path / "corrupt-v13-primary-key.sqlite3"
    original = ExecutionDecisionJournal(path)
    original.close()

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE execution_run_loss_guards")
        connection.execute(
            """CREATE TABLE execution_run_loss_guards (
                account_scope TEXT NOT NULL,
                strategy_scope TEXT NOT NULL,
                logical_run_id TEXT NOT NULL,
                trading_day TEXT NOT NULL,
                currency TEXT NOT NULL,
                pnl_basis TEXT NOT NULL,
                baseline_observation_id TEXT NOT NULL,
                baseline_asof TEXT NOT NULL,
                baseline_total_net_pnl TEXT NOT NULL,
                net_loss_threshold TEXT NOT NULL,
                max_observation_age_seconds INTEGER NOT NULL,
                latest_observation_id TEXT NOT NULL,
                latest_asof TEXT NOT NULL,
                latest_total_net_pnl TEXT NOT NULL,
                tripped INTEGER NOT NULL,
                trip_observation_id TEXT,
                trip_asof TEXT,
                trip_loss TEXT,
                created_at_ns INTEGER NOT NULL,
                updated_at_ns INTEGER NOT NULL
            )"""
        )
        connection.execute("PRAGMA user_version=13")

    with pytest.raises(
        ExecutionDecisionJournalError, match="RUN_LOSS_GUARD_SCHEMA_CORRUPT"
    ):
        ExecutionDecisionJournal(path)
