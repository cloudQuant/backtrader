"""Registered-Sim Alpha003 fee-pair OPEN dispatch source-fake integration.

These cases keep the production Strategy, decision-tape writer, Journal,
Coordinator, Broker and Store in the path. Only the native SDK leaves are
synthetic; the fixture denies private config/environment reads and networking.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal
from tests.integration import test_alpha003_fee_pair_registered_sim_source_only as guarded_fixture
from tests.integration import test_alpha003_registered_sim_order_chain as chain_fixture


_ACCOUNT_SCOPE = "alpha003-factor-chain-account"


def _run_open_probe(tmp_path, monkeypatch, **fixture_kwargs):
    outcome, audit = guarded_fixture._run_guarded_chain_fixture(
        tmp_path,
        monkeypatch,
        _fee_pair_open_probe=True,
        # The strict live quote contract requires every consumed quote to be
        # at/after the risk snapshot it is evaluated against. The causal quote
        # barrier delivers the current bar's tick before the Strategy projects
        # facts, keeping the source lease admissible.
        _causal_quote_barrier=True,
        **fixture_kwargs,
    )
    assert outcome["evidence_level"] == "SOURCE_FAKE_REGISTERED_SIM_FEE_PAIR_OPEN_PROBE"
    assert outcome["cleanup_complete"] is True
    assert outcome["decision_tape"]["closed"] is True
    assert outcome["decision_tape"]["failed"] is False
    assert audit["private_input_denials"] == 0
    assert audit["network_denials"] == 0
    assert audit["synthetic_root_opens"] > 0
    return outcome


def _read_tape_rows(outcome):
    tape = outcome["decision_tape"]
    return tuple(
        chain_fixture.RUNNER.iter_decision_tape(
            Path(tape["path"]), max_bytes=tape["max_bytes"]
        )
    )


def _journal_snapshot(outcome):
    journal = ExecutionDecisionJournal(outcome["journal_path"])
    try:
        candidates = tuple(
            row["candidate_id"]
            for row in journal._connection.execute(
                "SELECT candidate_id FROM execution_fee_pair_workflows ORDER BY created_at_ns"
            ).fetchall()
        )
        workflows = tuple(
            journal.fee_pair_workflow_candidate(candidate_id)
            for candidate_id in candidates
        )
        active = journal.fee_pair_active_amount_reservation(_ACCOUNT_SCOPE)
        intents = tuple(
            {
                "intent_id": row["intent_id"],
                "decision_id": row["decision_id"],
                "key": json.loads(row["intent_key_json"]),
                "state": row["state"],
                "dispatch_state": row["dispatch_state"],
                "outcome_code": row["outcome_code"],
            }
            for row in journal._connection.execute(
                "SELECT intent_id,decision_id,intent_key_json,state,dispatch_state,outcome_code "
                "FROM execution_decision_intents ORDER BY created_at_ns,intent_id"
            ).fetchall()
        )
        return journal, candidates, workflows, active, intents
    except BaseException:
        journal.close()
        raise


def _row_summary(row):
    decision = row.get("target_decision")
    if not isinstance(decision, dict):
        decision_summary = decision
    else:
        decision_summary = {
            "status": decision.get("status"),
            "reason": decision.get("reason"),
            "targets": tuple(
                (item.get("target_id"), item.get("target_position"))
                for item in decision.get("targets", ())
                if isinstance(item, dict)
            ),
        }
    plan = row.get("order_plan")
    if isinstance(plan, dict):
        plan = {
            "status": plan.get("status"),
            "reason": plan.get("reason"),
            "actions": tuple(
                (
                    item.get("action"),
                    item.get("target_id"),
                    item.get("position_effect"),
                    item.get("reason"),
                )
                for item in plan.get("actions", ())
                if isinstance(item, dict)
            ),
        }
    return {
        "record_type": row.get("record_type"),
        "readiness": row.get("readiness"),
        "batch_id": row.get("batch_id"),
        "decision": decision_summary,
        "order_plan": plan,
        "fee_pair_workflow": row.get("fee_pair_workflow"),
    }


@pytest.mark.integration
def test_registered_sim_fee_pair_settles_and_dispatches_both_open_legs(
    tmp_path, monkeypatch
):
    """A real Strategy GRID settlement admits two real Store submit calls."""
    outcome = _run_open_probe(tmp_path, monkeypatch)
    tape_rows = _read_tape_rows(outcome)
    grid_rows = tuple(
        row
        for row in tape_rows
        if row.get("record_type") == "DECISION"
        and isinstance(row.get("fee_pair_workflow"), dict)
        and row["fee_pair_workflow"].get("candidate_id")
    )
    assert grid_rows, "the Strategy must produce a physically written fee-pair GRID row"

    journal, candidate_ids, workflows, active, intents = _journal_snapshot(outcome)
    try:
        settled = tuple(
            workflow
            for workflow in workflows
            if workflow is not None and workflow.grid_settled_decision_id is not None
        )
        assert settled, (
            "the Journal must link the source tape row to a settled GRID decision; "
            f"workflows={workflows!r}, rows={tuple(_row_summary(row) for row in tape_rows)!r}, "
            f"native={outcome['native_calls']!r}, submits={outcome['store_submit_count']}, "
            f"settlement_probes={outcome['settlement_probes'][:8]!r}"
        )
        assert len(settled) == 1
        workflow = settled[0]
        assert workflow.candidate_id in candidate_ids
        assert workflow.state == "RECEIPT_VERIFIED"
        assert active is not None
        assert active["candidate_id"] == workflow.candidate_id
        assert active["status"] == "ACTIVE"

        decision = journal.decision(workflow.grid_settled_decision_id)
        assert decision is not None
        assert len(decision.intent_keys) == 2
        assert tuple(key.action for key in decision.intent_keys) == ("SUBMIT", "SUBMIT")
        assert tuple(key.position_effect for key in decision.intent_keys) == ("OPEN", "OPEN")
        pair_intents = tuple(
            intent for intent in intents if intent["decision_id"] == decision.decision_id
        )
        assert len(pair_intents) == 2
        assert all(
            intent["key"]["position_effect"] == "OPEN"
            and intent["state"] == "KNOWN"
            and intent["dispatch_state"] == "KNOWN"
            for intent in pair_intents
        ), pair_intents
        assert outcome["store_submit_count"] == 2
        native_inserts = tuple(call for call in outcome["native_calls"] if call[0] == "insert")
        assert len(native_inserts) == 2
        assert len({call[1] for call in native_inserts}) == 2
        assert outcome["unknown_native_calls"] == ()
    finally:
        journal.close()


@pytest.mark.integration
def test_registered_sim_missing_commission_row_blocks_open_before_dispatch(
    tmp_path, monkeypatch
):
    """An absent queried commission projection cannot create an OPEN hold."""
    outcome = _run_open_probe(
        tmp_path,
        monkeypatch,
        _fee_pair_missing_commission_target_index=0,
    )
    assert outcome["commission_query_calls"]
    assert outcome["store_submit_count"] == 0
    assert not tuple(call for call in outcome["native_calls"] if call[0] == "insert")
    assert outcome["unknown_native_calls"] == ()

    journal, _candidate_ids, workflows, active, intents = _journal_snapshot(outcome)
    try:
        assert active is None
        assert not any(
            key.get("position_effect") == "OPEN"
            for intent in intents
            for key in (intent["key"],)
        ), intents
        assert not any(
            workflow is not None and workflow.grid_settled_decision_id is not None
            for workflow in workflows
        ), workflows
    finally:
        journal.close()


@pytest.mark.integration
def test_registered_sim_unknown_first_open_keeps_hold_and_never_dispatches_second_leg(
    tmp_path, monkeypatch
):
    """A native timeout is recorded UNKNOWN and preserves the pair hold."""
    outcome = _run_open_probe(
        tmp_path,
        monkeypatch,
        _fee_pair_first_insert_unknown=True,
    )
    assert len(outcome["unknown_native_calls"]) == 1
    assert outcome["store_submit_count"] == 1
    assert len(tuple(call for call in outcome["native_calls"] if call[0] == "insert")) == 1

    journal, candidate_ids, workflows, active, intents = _journal_snapshot(outcome)
    try:
        settled = tuple(
            workflow
            for workflow in workflows
            if workflow is not None and workflow.grid_settled_decision_id is not None
        )
        assert len(settled) == 1
        workflow = settled[0]
        assert workflow.candidate_id in candidate_ids
        assert active is not None
        assert active["candidate_id"] == workflow.candidate_id
        assert active["status"] == "ACTIVE"
        decision = journal.decision(workflow.grid_settled_decision_id)
        assert decision is not None and len(decision.intent_keys) == 2
        attempted = tuple(
            intent for intent in intents if intent["decision_id"] == decision.decision_id
        )
        assert len(attempted) == 1, "the second leg must not even be prepared after UNKNOWN"
        assert attempted[0]["key"]["position_effect"] == "OPEN"
        # A terminal-no-fill reconciliation may settle the intent row as KNOWN
        # while its dispatch_state remains UNKNOWN; the durable dispatch
        # identity is the UNKNOWN marker itself.
        assert attempted[0]["state"] in {"UNKNOWN", "KNOWN"}
        assert attempted[0]["dispatch_state"] == "UNKNOWN"
        assert attempted[0]["outcome_code"]
    finally:
        journal.close()
