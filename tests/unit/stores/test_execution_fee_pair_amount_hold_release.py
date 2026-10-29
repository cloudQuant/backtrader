"""Synthetic v24/v25 amount-hold compatibility contracts.

These checks use the existing source-backed fee-pair fixtures and a temporary
SQLite journal.  They do not exercise a provider or any account data.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import importlib

import pytest

from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
    ExecutionFeePairOpenContext,
)
from backtrader.stores.factor_execution_facts import (
    FactorExecutionFactsSourceError,
    fee_pair_facts_open_source_scope,
    fee_pair_facts_release_source_scope,
)
from tests.unit.scripts import test_alpha003_fee_pair_grid_tape_writer as tape_fixtures
from tests.unit.stores import test_execution_fee_pair_candidate_journal as workflow_fixtures
from tests.unit.stores import test_factor_execution_facts_source_binding as source_fixtures


def _build_next_single_row_harness(
    tmp_path, monkeypatch, journal, run_id, *, entry_ordinal=1
):
    facts_fixtures = importlib.import_module("tests.unit.stores.test_factor_execution_facts")
    original_system = facts_fixtures._multi_target_system_under_test
    original_pair_fixture = workflow_fixtures._fee_pair_settlement_fixture
    cases = []

    def with_cny_account(**kwargs):
        account = dict(kwargs.get("account") or {})
        account["CurrencyID"] = "CNY"
        account.setdefault("TradingDay", facts_fixtures._TRADING_DAY)
        # Currency is only projected from a qualified single account row that
        # also carries the three PnL inputs.
        account.setdefault("CloseProfit", "0")
        account.setdefault("PositionProfit", "0")
        account.setdefault("Commission", "0")
        kwargs["account"] = account
        return original_system(**kwargs)

    def later_pair_fixture(candidate_run_id, **kwargs):
        kwargs.setdefault(
            "close_time",
            (
                datetime.now(timezone.utc).replace(second=0, microsecond=0)
                - timedelta(minutes=1)
            ).isoformat(timespec="seconds").replace("+00:00", "Z"),
        )
        case, candidate, quotes = original_pair_fixture(candidate_run_id, **kwargs)
        cases.append(case)
        return case, candidate, quotes

    # The separate writer gets a later grid but uses the same Journal head.
    with monkeypatch.context() as patch:
        patch.setattr(facts_fixtures, "_multi_target_system_under_test", with_cny_account)
        patch.setattr(
            workflow_fixtures, "_fee_pair_settlement_fixture", later_pair_fixture
        )
        patch.setattr(tape_fixtures, "ExecutionDecisionJournal", lambda *a, **k: journal)
        harness = tape_fixtures._build_single_row_harness(tmp_path, run_id=run_id)
    # The second candidate is the next grid on the same account/strategy/cohort
    # cursor, so its planner projection carries the caller-specified ordinal
    # rather than the fixture's standalone ordinal 1.
    for action in harness.economic_payload.get("proposed_actions", ()):
        action["entry_grid_ordinal"] = entry_ordinal
    for intent in harness.economic_payload.get("intent_economics", ()):
        intent["entry_grid_ordinal"] = entry_ordinal
    for action in harness.order_plan.actions:
        action.entry_grid_ordinal = entry_ordinal
    return harness, cases[0]


def _settle_single_row_with_open_hold(harness, source_lease):
    assert tuple(
        action.get("target_id") for action in harness.economic_payload["proposed_actions"]
    ) == tuple(route.target_id for route in harness.candidate.target_routes)
    return harness.writer.settle_fee_pair_grid_single_row(
        harness.candidate,
        harness.batch,
        harness.snapshot,
        harness.target_decision,
        harness.order_plan,
        harness.journal,
        owner_token=harness.owner_token,
        facts=harness.facts,
        economic_payload=harness.economic_payload,
        current_account_session_id=harness.candidate.account_session_id,
        current_account_session_generation=harness.candidate.account_session_generation,
        max_query_age_seconds=20.0,
        max_quote_age_seconds=10.0,
        max_order_intents_per_run=100,
        expected_run_order_intents_used=0,
        remaining_exit_intent_reserve=0,
        reserve_for_open=True,
        source_lease=source_lease,
    )


def _source_scope_kwargs(facts):
    marker = facts._source_projection
    return {
        "now": marker.projected_at,
        "max_query_age": marker.max_query_age,
    }


def _restore_source_projection(harness, facts):
    """Keep the source-issued facts and bind plan evidence to that object."""

    harness.facts = facts
    harness.economic_payload = {
        **harness.economic_payload,
        "execution_evidence": ExecutionDecisionJournal._fee_pair_execution_evidence_payload(
            facts
        ),
    }


def _settled_public_economics(decision):
    payload = dict(decision.economic_payload)
    for field in (
        tape_fixtures.journal_module._SOURCE_RECEIPT_PAYLOAD_FIELD,
        tape_fixtures.journal_module._FEE_PAIR_WORKFLOW_PAYLOAD_FIELD,
        tape_fixtures.journal_module._FEE_PAIR_SETTLEMENT_PAYLOAD_FIELD,
        tape_fixtures.journal_module._RUN_ORDER_RESERVATION_FIELD,
    ):
        payload.pop(field, None)
    return payload


def test_v24_legacy_hold_cannot_authorize_v25_pair_open(tmp_path, monkeypatch):
    harness = tape_fixtures._build_single_row_harness(
        tmp_path, run_id="amount-hold-v24-legacy-open-fence"
    )
    source_harness = None
    source_case = None
    reopened = None
    try:
        tape_fixtures._attach_amount_projection(harness)
        settled = tape_fixtures._settle_single_row(harness)
        legacy = harness.journal.reserve_fee_pair_grid_amounts(
            settled["candidate_id"],
            owner_token=harness.owner_token,
            facts=harness.facts,
        )

        assert legacy["status"] == "ACTIVE"
        assert harness.journal.fee_pair_grid_amount_reservation(
            settled["candidate_id"]
        )["lifecycle_state"] == "LEGACY_HELD"
        source_fixtures._install_fake_canonical_session_lock(monkeypatch)
        source_harness, source_case = _build_next_single_row_harness(
            tmp_path,
            monkeypatch,
            harness.journal,
            "amount-hold-v24-legacy-release-source",
        )
        with fee_pair_facts_release_source_scope(
            source_case.store,
            source_case.broker,
            source_case.facts,
            targets=source_case.targets[:2],
            **_source_scope_kwargs(source_case.facts),
        ) as release_lease:
            with pytest.raises(
                ExecutionDecisionJournalError,
                match="FEE_PAIR_LEGACY_AMOUNT_HOLD_NOT_RELEASE_AUTHORIZED",
            ):
                harness.journal.release_fee_pair_grid_amount_hold_for_flat(
                    settled["candidate_id"],
                    facts=source_case.facts,
                    source_lease=release_lease,
                )
        assert harness.journal.fee_pair_grid_amount_reservation(
            settled["candidate_id"]
        )["lifecycle_state"] == "LEGACY_HELD"
        context = ExecutionFeePairOpenContext(
            facts=harness.facts,
            account_session_id=harness.candidate.account_session_id,
            account_session_generation=harness.candidate.account_session_generation,
            owner_token=harness.owner_token,
            max_query_age_seconds=20.0,
            max_quote_age_seconds=10.0,
            candidate_id=settled["candidate_id"],
            reservation_sha256=legacy["reservation_sha256"],
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_OPEN_CONTEXT_MISMATCH"
        ):
            harness.journal.fee_pair_open_grid_admission(
                harness.candidate.key,
                _settled_public_economics(settled["decision"]),
                settled["decision"].intent_keys,
                context=context,
            )

        assert harness.journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_amount_open_reservations"
        ).fetchone()[0] == 0
        assert harness.journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decision_intents"
        ).fetchone()[0] == 0
        assert harness.journal.fee_pair_grid_amount_reservation(
            settled["candidate_id"]
        )["lifecycle_state"] == "LEGACY_HELD"

        journal_path = harness.journal.path
        harness.writer.close()
        harness.journal.close()
        reopened = ExecutionDecisionJournal(
            journal_path,
            max_payload_bytes=tape_fixtures.runner._LIVE_DECISION_JOURNAL_MAX_PAYLOAD_BYTES,
        )
        assert reopened.fee_pair_grid_amount_reservation(
            settled["candidate_id"]
        )["lifecycle_state"] == "LEGACY_HELD"
        assert reopened._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_amount_open_reservations"
        ).fetchone()[0] == 0
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_OPEN_CONTEXT_MISMATCH"
        ):
            reopened.fee_pair_open_grid_admission(
                harness.candidate.key,
                _settled_public_economics(settled["decision"]),
                settled["decision"].intent_keys,
                context=context,
            )
    finally:
        if reopened is not None:
            reopened.close()
        if source_harness is not None:
            try:
                source_harness.writer.close()
            except Exception:
                pass
        if source_case is not None:
            source_case.journal.close()
        try:
            tape_fixtures._safe_close(harness)
        except Exception:
            pass


def test_hand_built_fresh_flat_projection_has_no_release_source_authority():
    case, _candidate, _quotes = workflow_fixtures._fee_pair_settlement_fixture(
        "amount-hold-forged-flat-facts"
    )
    try:
        forged = replace(
            case.facts,
            account=replace(
                case.facts.account,
                current_notional=Decimal(0),
                current_worst_case_loss=Decimal(0),
            ),
            positions=tuple(
                replace(
                    position,
                    quantity=Decimal(0),
                    broker_quantity=Decimal(0),
                    long_quantity=Decimal(0),
                    short_quantity=Decimal(0),
                    attributed_signed_quantity=Decimal(0),
                    owner_strategy_scope=None,
                    owner_intent_id=None,
                    dated_inventory_rows=(),
                    position_book_status="FLAT",
                    position_book_blocker_code=None,
                )
                for position in case.facts.positions
            ),
            working_orders=(),
            execution_intents=(),
            blockers=(),
        )
        with pytest.raises(
            FactorExecutionFactsSourceError,
            match="factor_execution_facts_source_unissued",
        ):
            with fee_pair_facts_release_source_scope(
                case.store,
                case.broker,
                forged,
                now=datetime.now(timezone.utc),
                targets=case.targets[:2],
                max_query_age=timedelta(seconds=10),
            ):
                pytest.fail("hand-built facts unexpectedly entered the release scope")
    finally:
        case.journal.close()


def test_v24_account_head_rejects_next_v25_reservation_without_failing_journal(
    tmp_path, monkeypatch
):
    first = tape_fixtures._build_single_row_harness(
        tmp_path, run_id="amount-hold-v24-account-head"
    )
    second = None
    second_case = None
    try:
        tape_fixtures._attach_amount_projection(first)
        first_settlement = tape_fixtures._settle_single_row(first)
        legacy = first.journal.reserve_fee_pair_grid_amounts(
            first_settlement["candidate_id"],
            owner_token=first.owner_token,
            facts=first.facts,
        )

        source_fixtures._install_fake_canonical_session_lock(monkeypatch)
        second, second_case = _build_next_single_row_harness(
            tmp_path,
            monkeypatch,
            first.journal,
            "amount-hold-v25-next-candidate",
            entry_ordinal=2,
        )
        tape_fixtures._attach_amount_projection(second)
        # Keep the original Store-issued projection for the source lease; the
        # planner helper above builds economics from equal CNY values but uses
        # dataclasses.replace, which intentionally drops source authority.
        _restore_source_projection(second, second_case.facts)
        with fee_pair_facts_open_source_scope(
            second_case.store,
            second_case.broker,
            second.facts,
            targets=second_case.targets[:2],
            quote_max_age=second.facts._source_projection.quote_max_age,
            **_source_scope_kwargs(second.facts),
        ) as source_lease:
            with pytest.raises(
                ExecutionDecisionJournalError,
                match=(
                    "FEE_PAIR_ACCOUNT_AMOUNT_HOLD_ACTIVE|"
                    "FEE_PAIR_AMOUNT_RESERVATION_ALREADY_ACTIVE|"
                    "FEE_PAIR_LEGACY_AMOUNT_HOLD_ACTIVE"
                ),
            ):
                _settle_single_row_with_open_hold(second, source_lease)

        assert first.journal._failed_closed is False
        assert first.journal.fee_pair_grid_amount_reservation(
            first_settlement["candidate_id"]
        )["reservation_sha256"] == legacy["reservation_sha256"]
        second_candidate_row = first.journal._connection.execute(
            "SELECT candidate_id FROM execution_fee_pair_workflows WHERE logical_run_id=?",
            (second.candidate.key.logical_run_id,),
        ).fetchone()
        assert second_candidate_row is not None
        second_workflow = first.journal.fee_pair_workflow_candidate(
            second_candidate_row[0]
        )
        assert second_workflow is not None
        assert second_workflow.grid_settled_decision_id is None
        active = first.journal._connection.execute(
            "SELECT candidate_id FROM execution_fee_pair_amount_active_holds "
            "WHERE account_scope=?",
            (second.candidate.key.account_scope,),
        ).fetchone()
        assert active[0] == first_settlement["candidate_id"]
        assert first.journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_amount_open_reservations"
        ).fetchone()[0] == 0
        assert first.journal.decision_for_key(second.candidate.key) is None
    finally:
        if second is not None:
            try:
                second.writer.close()
            except Exception:
                pass
        tape_fixtures._safe_close(first)
        if second_case is not None:
            second_case.journal.close()


def test_unreconciled_v25_pair_cannot_release_amount_hold(tmp_path, monkeypatch):
    journal_path = tmp_path / "unreconciled-v25.sqlite3"
    journal = ExecutionDecisionJournal(
        journal_path,
        max_payload_bytes=tape_fixtures.runner._LIVE_DECISION_JOURNAL_MAX_PAYLOAD_BYTES,
    )
    source_fixtures._install_fake_canonical_session_lock(monkeypatch)
    harness, case = _build_next_single_row_harness(
        tmp_path, monkeypatch, journal, "amount-hold-v25-unreconciled"
    )
    source_facts = case.facts
    try:
        tape_fixtures._attach_amount_projection(harness)
        # Preserve the exact facts object issued by the synthetic Store.
        _restore_source_projection(harness, source_facts)
        with fee_pair_facts_open_source_scope(
            case.store,
            case.broker,
            source_facts,
            targets=case.targets[:2],
            quote_max_age=source_facts._source_projection.quote_max_age,
            **_source_scope_kwargs(source_facts),
        ) as open_lease:
            settled = _settle_single_row_with_open_hold(harness, open_lease)

        candidate_id = settled["candidate_id"]
        assert settled["amount_reservation"]["lifecycle_state"] == "ACTIVE"
        assert journal.fee_pair_grid_amount_reservation(candidate_id)[
            "lifecycle_state"
        ] == "ACTIVE"

        with fee_pair_facts_release_source_scope(
            case.store,
            case.broker,
            source_facts,
            targets=case.targets[:2],
            **_source_scope_kwargs(source_facts),
        ) as release_lease:
            with pytest.raises(
                ExecutionDecisionJournalError,
                match="FEE_PAIR_AMOUNT_RELEASE_NOT_RECONCILED",
            ):
                journal.release_fee_pair_grid_amount_hold_for_flat(
                    candidate_id,
                    facts=source_facts,
                    source_lease=release_lease,
                )

        assert journal._failed_closed is False
        assert journal.fee_pair_grid_amount_reservation(candidate_id)[
            "lifecycle_state"
        ] == "ACTIVE"
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_amount_lifecycle_events "
            "WHERE candidate_id=? AND event_sequence=2 AND event_kind='RELEASED'",
            (candidate_id,),
        ).fetchone()[0] == 0
        assert journal.fee_pair_active_amount_reservation(
            settled["decision"].key.account_scope
        )["candidate_id"] == candidate_id
    finally:
        try:
            harness.writer.close()
        except Exception:
            pass
        journal.close()
        case.journal.close()


