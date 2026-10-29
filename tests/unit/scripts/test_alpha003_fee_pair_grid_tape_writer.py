"""Synthetic production-writer contracts for the v20 GRID tape append seam."""

from __future__ import annotations

from dataclasses import fields, replace
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import hashlib
import importlib.util
from pathlib import Path
import shutil
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from backtrader.stores import execution_decision_journal as journal_module
from backtrader.stores import execution_journal_archive as archive_module
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
)
from backtrader.stores.execution_durable_capacity import DurableCapacityLimits
from tests.unit.stores import test_execution_fee_pair_candidate_journal as workflow_fixtures


RUNNER_PATH = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "unified"
    / "028_alpha003_simnow_minute"
    / "run.py"
)
EXAMPLE_PATH = str(RUNNER_PATH.parent)
if EXAMPLE_PATH not in sys.path:
    sys.path.insert(0, EXAMPLE_PATH)
RUNNER_SPEC = importlib.util.spec_from_file_location(
    "alpha003_fee_pair_grid_tape_writer_test_runner", RUNNER_PATH
)
assert RUNNER_SPEC is not None and RUNNER_SPEC.loader is not None
runner = importlib.util.module_from_spec(RUNNER_SPEC)
sys.modules[RUNNER_SPEC.name] = runner
RUNNER_SPEC.loader.exec_module(runner)
_DEFAULT_ORDER_PLAN = object()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _drop_v25_amount_lifecycle_objects(connection: sqlite3.Connection) -> None:
    """Restore the pre-v25 amount schema from a current journal fixture."""

    for trigger in (
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
    ):
        connection.execute("DROP TRIGGER IF EXISTS {}".format(trigger))
    connection.execute("DROP TABLE IF EXISTS execution_fee_pair_amount_active_holds")
    connection.execute("DROP TABLE IF EXISTS execution_fee_pair_amount_lifecycle_events")
    connection.execute("DROP TABLE IF EXISTS execution_fee_pair_amount_open_reservations")


def _selection_inputs(candidate):
    if candidate.target_routes is not None:
        routes = {route.target_id: route.instrument for route in candidate.target_routes}
    else:
        routes = {"SIM-A": "rb2510", "SIM-B": "i2510"}
    authorized = list(candidate.target_ids)
    manifest = {"fixture": "synthetic-public"}
    manifest_sha256 = hashlib.sha256(
        runner._canonical_json_bytes(manifest).rstrip(b"\n")
    ).hexdigest()
    binding = {
        "schema": "backtrader.alpha003_epoch_selection_evidence.v1",
        "epoch_id": candidate.epoch_id,
        "selection_source": "saved_bundle_legacy",
        "selection_path": "synthetic-public-fixture",
        "source_snapshot_id": None,
        "manifest_sha256": manifest_sha256,
        "routes": routes,
        "authorized_targets": authorized,
    }
    evidence = {
        **binding,
        "binding_sha256": hashlib.sha256(
            runner._canonical_json_bytes(binding).rstrip(b"\n")
        ).hexdigest(),
        "manifest": manifest,
    }
    identity = {
        "schema": "backtrader.alpha003.live_restart_identity.v1",
        "epoch_id": candidate.epoch_id,
        "mode": "live",
        "factor_mode": "native",
        "direction": 1,
        "scope_sha256": {
            name: _digest(value)
            for name, value in (
                ("account_scope", candidate.key.account_scope),
                ("strategy_scope", candidate.key.strategy_scope),
                ("logical_run_id", candidate.key.logical_run_id),
            )
        },
        "selection_source": "saved_bundle_legacy",
        "source_snapshot_id": None,
        "targets": list(candidate.target_ids),
        "authorized_targets": authorized,
        "routes": routes,
        "calendar": {
            "calendar_id": candidate.calendar_id,
            "grid_sha256": _digest("synthetic-grid"),
        },
    }
    return identity, evidence


def _candidate_with_origin_partitions(candidate):
    targets = tuple(candidate.target_ids)
    if len(targets) != 2 or len(candidate.source_members) not in (1, 2):
        raise AssertionError("the pair writer fixture requires exactly two source targets")
    source_members = []
    for member in candidate.source_members:
        partition = {
            "schema": runner.SOURCE_ORIGIN_PARTITION_SCHEMA,
            "cohort_id": candidate.key.cohort_id,
            "epoch_id": candidate.epoch_id,
            "member_id": member.member_id,
            "source_ref": member.source_ref,
            "source_role": member.source_role,
            "connection_generation": member.connection_generation,
        }
        source_members.append(
            replace(
                member,
                trading_day=runner._tape_trading_day(member.trading_day, "fixture"),
                origin_partition=partition,
            )
        )
    if len(source_members) == 2:
        second = source_members[1]
    else:
        template = source_members[0]
        second_id = targets[1]
        second_source_ref = "synthetic-ctp-{}".format(second_id.lower())
        second_partition = {
            "schema": runner.SOURCE_ORIGIN_PARTITION_SCHEMA,
            "cohort_id": candidate.key.cohort_id,
            "epoch_id": candidate.epoch_id,
            "member_id": second_id,
            "source_ref": second_source_ref,
            "source_role": "live",
            "connection_generation": template.connection_generation,
        }
        second = replace(
            template,
            member_id=second_id,
            source_ref=second_source_ref,
            feed_sequence=2,
            bar_id="bar-2",
            origin_partition=second_partition,
        )
    return replace(
        candidate,
        source_members=(source_members[0], second),
    )


def _objects(candidate):
    member_rows = {}
    if candidate.target_routes is not None:
        instrument_by_target = {
            route.target_id: route.instrument for route in candidate.target_routes
        }
        exchange_by_target = {
            route.target_id: route.exchange for route in candidate.target_routes
        }
    else:
        instrument_by_target = {"SIM-A": "rb2510", "SIM-B": "i2510"}
        exchange_by_target = {"SIM-A": "SHFE", "SIM-B": "DCE"}
    for member in candidate.source_members:
        envelope_values = {
            field.name: getattr(member, field.name) for field in fields(member)
        }
        envelope_values.update(
            cohort_id=candidate.key.cohort_id,
            calendar_id=candidate.calendar_id,
            epoch_id=candidate.epoch_id,
            slot_index=candidate.slot_index,
            slot_id=candidate.slot_id,
            instrument=instrument_by_target[member.member_id],
        )
        envelope_values["raw_values"] = {
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 7.0,
            "openinterest": 0.0,
        }
        member_rows[member.member_id] = SimpleNamespace(
            envelope=SimpleNamespace(**envelope_values)
        )

    available_at = max(member.available_at for member in candidate.source_members)
    batch = SimpleNamespace(
        status="COMPLETE",
        members=member_rows,
        batch_id=candidate.batch_id,
        cohort_id=candidate.key.cohort_id,
        calendar_id=candidate.calendar_id,
        calendar_version=candidate.calendar_version,
        epoch_id=candidate.epoch_id,
        slot_index=candidate.slot_index,
        close_time=candidate.key.close_time,
        available_at=available_at,
    )
    factor_values = {
        member.member_id: SimpleNamespace(
            value=0.25 * candidate.directions[candidate.target_ids.index(member.member_id)],
            status="READY",
            reason=None,
            present=True,
            complete=True,
            quality="GOOD",
            source_role=member.source_role,
            member_id=member.member_id,
            source_ref=member.source_ref,
            sequence=member.feed_sequence,
            generation=member.connection_generation,
        )
        for member in candidate.source_members
    }
    factor = SimpleNamespace(
        mode="native",
        panel_line="alpha003",
        direction=1,
        source_sha256=candidate.factor_snapshot_sha256,
        values=factor_values,
    )
    snapshot = SimpleNamespace(
        batch_complete=True,
        batch_id=candidate.batch_id,
        close_time=candidate.key.close_time,
        readiness="LIVE_READY",
        readiness_reasons=(),
        plan_id="synthetic-plan",
        factors={"alpha003": factor},
    )
    target_rows = []
    for index, target in enumerate(candidate.target_ids):
        target_rows.append(
            SimpleNamespace(
                target_id=target,
                product_key=SimpleNamespace(
                    exchange_id=exchange_by_target[target],
                    product_id=instrument_by_target[target],
                ),
                target_position=candidate.directions[index],
                raw_score=0.25 * candidate.directions[index],
                oriented_score=0.25 * candidate.directions[index],
            )
        )
    target_decision = SimpleNamespace(
        status="READY",
        reason=None,
        factor_name="alpha003",
        mode="native",
        execution_mode="simnow-live",
        direction=1,
        source_sha256=candidate.factor_snapshot_sha256,
        cohort_id=candidate.key.cohort_id,
        batch_id=candidate.batch_id,
        close_time=candidate.key.close_time,
        available_at=available_at,
        eligible_grid_index=candidate.slot_index,
        rebalance_every=1,
        authorized_targets=list(candidate.target_ids),
        eligible_targets=list(candidate.target_ids),
        targets=target_rows,
    )
    order_plan = SimpleNamespace(
        status="NO_ACTION",
        reason=None,
        decision_batch_id=candidate.batch_id,
        decision_available_at=available_at,
        actions=(),
    )
    return batch, snapshot, target_decision, order_plan


def _build_harness(tmp_path, run_id="grid-writer"):
    candidate = _candidate_with_origin_partitions(workflow_fixtures._candidate(run_id=run_id))
    identity, evidence = _selection_inputs(candidate)
    writer = runner.DecisionTapeWriter(
        tmp_path / (run_id + ".jsonl"),
        2 * 1024 * 1024,
        mode="live",
        factor_mode="native",
        direction=1,
        targets=("SIM-A", "SIM-B"),
        calendar_id=candidate.calendar_id,
        grid_sha256=identity["calendar"]["grid_sha256"],
        source_snapshot_id=None,
        restart_identity=identity,
        selection_evidence=evidence,
        calendar_fingerprint=candidate.calendar_fingerprint,
    )
    candidate = replace(candidate, expected_tape_file_id=writer.file_id)
    batch, snapshot, target_decision, order_plan = _objects(candidate)
    writer.record_decision(batch, snapshot, target_decision, order_plan)
    source_row = list(
        runner.iter_decision_tape(
            writer.path,
            max_bytes=writer.max_bytes,
            max_record_bytes=runner._FEE_PAIR_SOURCE_ONLY_MAX_RECORD_BYTES,
        )
    )[1]
    receipt = runner._fee_pair_source_receipt_from_tape_row(
        source_row, candidate, journal_module
    )

    journal = ExecutionDecisionJournal(tmp_path / (run_id + ".sqlite3"))
    journal.register_fee_pair_required_scope(
        candidate.key.account_scope, candidate.key.strategy_scope
    )
    owner_token = "writer-owner-" + run_id + "-" + "x" * 24
    reserved = journal.reserve_fee_pair_workflow_candidate(
        candidate, owner_token=owner_token, ttl_seconds=30.0
    )
    journal.record_fee_pair_workflow_append_claim(
        reserved.candidate_id, owner_token=owner_token
    )
    attached = journal.attach_verified_fee_pair_source_receipt(
        reserved.candidate_id, receipt, owner_token=owner_token
    )
    assert attached.state == "RECEIPT_VERIFIED"
    return SimpleNamespace(
        candidate=candidate,
        candidate_id=reserved.candidate_id,
        batch=batch,
        snapshot=snapshot,
        target_decision=target_decision,
        order_plan=order_plan,
        journal=journal,
        owner_token=owner_token,
        receipt=receipt,
        writer=writer,
    )


def _build_single_row_harness(tmp_path, run_id="grid-writer-v23", journal_encoding=None):
    case, candidate, quote_by_route = workflow_fixtures._fee_pair_settlement_fixture(run_id)
    candidate = _candidate_with_origin_partitions(candidate)
    identity, evidence = _selection_inputs(candidate)
    writer = runner.DecisionTapeWriter(
        tmp_path / (run_id + ".jsonl"),
        2 * 1024 * 1024,
        mode="live",
        factor_mode="native",
        direction=1,
        targets=tuple(candidate.target_ids),
        calendar_id=candidate.calendar_id,
        grid_sha256=identity["calendar"]["grid_sha256"],
        source_snapshot_id=None,
        restart_identity=identity,
        selection_evidence=evidence,
        calendar_fingerprint=candidate.calendar_fingerprint,
        cross_process_generation_lease=True,
    )
    candidate = replace(
        candidate,
        expected_tape_file_id=writer.file_id,
        expected_tape_record_index=writer._record_count + 1,
    )
    batch, snapshot, target_decision, _empty_plan = _objects(candidate)
    target_decision.status = "TARGETS_READY"
    receipt = journal_module._fee_pair_receipt_from_candidate(candidate, "0" * 64)
    payload = dict(
        workflow_fixtures._fee_pair_grid_economic_payload(
            candidate, case.facts, quote_by_route, receipt
        )
    )
    payload["decision_tape_record_id"] = None
    payload["proposed_actions"] = [
        {**action, "decision_available_at": batch.available_at}
        for action in payload["proposed_actions"]
    ]
    planned_actions = []
    for action in payload["proposed_actions"]:
        planned_actions.append(
            SimpleNamespace(
                action=action["action"],
                target_id=action["target_id"],
                instrument=action["instrument"],
                side=action["side"],
                position_effect=action["position_effect"],
                quantity=action["quantity"],
                limit_price=action["limit_price"],
                offset="OPEN",
                reason="synthetic-ready-pair",
                planned_stop_price=action["planned_stop_price"],
                exchange=action["exchange"],
                decision_available_at=action["decision_available_at"],
                entry_grid_ordinal=action["entry_grid_ordinal"],
            )
        )
    order_plan = SimpleNamespace(
        status="READY",
        reason=None,
        decision_batch_id=candidate.batch_id,
        decision_available_at=batch.available_at,
        actions=tuple(planned_actions),
    )
    journal_path = tmp_path / (run_id + ".sqlite3")
    if journal_encoding is not None:
        with sqlite3.connect(journal_path) as bootstrap:
            bootstrap.execute("PRAGMA encoding='{}'".format(journal_encoding))
    journal = ExecutionDecisionJournal(
        journal_path,
        max_payload_bytes=runner._LIVE_DECISION_JOURNAL_MAX_PAYLOAD_BYTES,
    )
    journal.register_fee_pair_required_scope(
        candidate.key.account_scope, candidate.key.strategy_scope
    )
    owner_token = "writer-v23-owner-" + run_id + "-" + "x" * 24
    return SimpleNamespace(
        candidate=candidate,
        batch=batch,
        snapshot=snapshot,
        target_decision=target_decision,
        order_plan=order_plan,
        journal=journal,
        owner_token=owner_token,
        writer=writer,
        facts=case.facts,
        economic_payload=payload,
    )


def _safe_close(harness):
    try:
        harness.writer.close()
    except Exception:
        pass
    harness.journal.close()


@pytest.fixture
def harness(tmp_path):
    value = _build_harness(tmp_path)
    try:
        yield value
    finally:
        _safe_close(value)


def _append(harness, *, order_plan=_DEFAULT_ORDER_PLAN):
    if order_plan is _DEFAULT_ORDER_PLAN:
        order_plan = harness.order_plan
    return harness.writer.record_fee_pair_grid_tape_append_observation(
        harness.candidate_id,
        harness.candidate,
        harness.batch,
        harness.snapshot,
        harness.target_decision,
        order_plan,
        harness.journal,
        owner_token=harness.owner_token,
    )


def _settle_single_row(harness, *, economic_payload=None):
    return harness.writer.settle_fee_pair_grid_single_row(
        harness.candidate,
        harness.batch,
        harness.snapshot,
        harness.target_decision,
        harness.order_plan,
        harness.journal,
        owner_token=harness.owner_token,
        facts=harness.facts,
        economic_payload=(
            harness.economic_payload if economic_payload is None else economic_payload
        ),
        current_account_session_id=harness.candidate.account_session_id,
        current_account_session_generation=harness.candidate.account_session_generation,
        max_query_age_seconds=20.0,
        max_quote_age_seconds=10.0,
        max_order_intents_per_run=100,
        expected_run_order_intents_used=0,
        remaining_exit_intent_reserve=0,
    )


def _attach_amount_projection(
    harness, *, currency="CNY", policy_overrides=None, account_overrides=None
):
    """Bind a real Alpha003 planner-shaped amount projection to this GRID."""

    import alpha003_strategy as alpha003

    policy = {
        "risk_policy_id": "synthetic-risk-policy-v1",
        "max_hold_eligible_bars": 12,
        "preclose_grace_seconds": 0,
        "run_end_policy": "CLOSE_ALL",
        "quote_max_age_seconds": "10",
        "max_state_age_seconds": "20",
        "max_notional_per_position": "100000",
        "max_total_notional": "200000",
        "max_margin_per_position": "20000",
        "max_total_margin": "40000",
        "max_loss_per_position": "500",
        "max_total_loss": "1000",
        "stop_loss_ticks": 1,
        "max_order_intents_per_grid": 2,
        "max_order_intents_per_run": 100,
        "round_trip_fee_upper_bound_per_contract": None,
    }
    if policy_overrides:
        policy.update(policy_overrides)
    facts = harness.facts
    account = replace(facts.account, currency=currency, **(account_overrides or {}))
    facts = replace(facts, account=account)
    harness.facts = facts
    latest_evidence = [facts.available_at, account.available_at]
    latest_evidence.extend(
        value
        for quote in facts.quotes
        for value in (quote.event_time, quote.available_at)
        if value is not None
    )
    latest_evidence.extend(
        query.completed_at
        for query in facts.query_provenance
        if query.family == "instrument_commission_rate_result"
        and query.completed_at is not None
    )
    decision_at = max(latest_evidence) + timedelta(milliseconds=1)
    decision_at_text = alpha003._time_key(decision_at)

    instrument_by_target = {item.target_id: item for item in facts.instruments}
    quote_by_route = {(item.instrument, item.exchange): item for item in facts.quotes}
    risk_legs = []
    total_notional = Decimal(0)
    total_margin = Decimal(0)
    total_loss = Decimal(0)
    for route, direction in zip(harness.candidate.target_routes, harness.candidate.directions):
        side = "BUY" if direction > 0 else "SELL"
        instrument = instrument_by_target[route.target_id]
        quote = quote_by_route[(route.instrument, route.exchange)]
        multiplier = instrument.risk_multiplier_upper or instrument.multiplier
        margin = instrument.long_margin_per_hand if side == "BUY" else instrument.short_margin_per_hand
        risk_tick = instrument.risk_tick_size_upper or quote.risk_tick_size_upper
        fee = instrument.round_trip_fee_upper_bound_per_contract
        risk_price = max(quote.risk_bid_upper, quote.risk_ask_upper)
        notional = alpha003._risk_ceiling_product(risk_price, multiplier)
        stop_distance = alpha003._risk_ceiling_product(quote.tick_size, policy["stop_loss_ticks"])
        stop_loss_distance = alpha003._risk_ceiling_product(risk_tick, policy["stop_loss_ticks"])
        stop_loss = alpha003._risk_ceiling_product(stop_loss_distance, multiplier)
        worst_case_loss = alpha003._risk_ceiling_sum(stop_loss, fee)
        entry = quote.ask if side == "BUY" else quote.bid
        stop_price = alpha003._risk_stop_price(entry, stop_distance, side)
        leg = alpha003.Alpha003OpenRiskLegCandidate(
            target_id=route.target_id,
            instrument=route.instrument,
            exchange=route.exchange,
            side=side,
            quantity=1,
            entry_price=entry,
            stop_price=stop_price,
            multiplier=multiplier,
            margin=margin,
            notional=notional,
            stop_loss=stop_loss,
            round_trip_fee_upper_bound=fee,
            worst_case_loss=worst_case_loss,
            commission_fee_required=instrument.commission_fee_required,
            commission_fee_status=instrument.commission_fee_status,
            instrument_snapshot_id=instrument.snapshot_id,
            quote_source_ref=quote.source_ref,
            quote_metadata_snapshot_id=quote.metadata_snapshot_id,
            quote_generation=quote.generation,
            quote_sequence=quote.sequence,
            quote_event_time=quote.event_time,
            quote_available_at=quote.available_at,
            quote_bid=quote.bid,
            quote_ask=quote.ask,
            quote_bid_size=quote.bid_size,
            quote_ask_size=quote.ask_size,
        )
        risk_legs.append(leg)
        total_notional = alpha003._risk_ceiling_sum(total_notional, notional)
        total_margin = alpha003._risk_ceiling_sum(total_margin, margin)
        total_loss = alpha003._risk_ceiling_sum(total_loss, worst_case_loss)

    held_fee = Decimal(0)
    candidate_risk = alpha003.Alpha003OpenRiskCandidate(
        schema="backtrader.alpha003.open_risk_candidate.v1",
        evidence_source="REGISTERED_SIM",
        strategy_scope=harness.candidate.key.strategy_scope,
        batch_id=harness.candidate.batch_id,
        risk_policy_id=policy["risk_policy_id"],
        account_scope=harness.candidate.key.account_scope,
        account_snapshot_id=account.snapshot_id,
        query_set_id=facts.query_set_id,
        account_fingerprint=harness.candidate.account_fingerprint,
        connection_generation=harness.candidate.connection_generation,
        trading_day=harness.candidate.trading_day,
        source_snapshot_id=facts.snapshot_id,
        eligible_grid_ordinal=1,
        account_available_at=account.available_at,
        risk_evidence_available_at=facts.available_at,
        available_margin=account.available_margin,
        used_margin=account.used_margin,
        current_notional=account.current_notional,
        current_worst_case_loss=account.current_worst_case_loss,
        held_fee_reserve=held_fee,
        required_margin=total_margin,
        added_notional=total_notional,
        added_loss=total_loss,
        projected_total_margin=alpha003._risk_ceiling_sum(account.used_margin, total_margin),
        projected_total_notional=alpha003._risk_ceiling_sum(
            account.current_notional, total_notional
        ),
        projected_total_worst_case_loss=alpha003._risk_ceiling_sum(
            account.current_worst_case_loss, held_fee, total_loss
        ),
        max_total_margin=Decimal(policy["max_total_margin"]),
        max_total_notional=Decimal(policy["max_total_notional"]),
        max_total_loss=Decimal(policy["max_total_loss"]),
        legs=tuple(risk_legs),
    )
    risk_payload = dict(alpha003._open_risk_candidate_payload(candidate_risk))
    economics = []
    for existing, leg in zip(harness.economic_payload["intent_economics"], risk_legs):
        row = dict(existing)
        row.update(
            target_id=leg.target_id,
            risk_policy_id=policy["risk_policy_id"],
            risk_policy=policy,
            open_risk_candidate=dict(alpha003._open_risk_leg_candidate_payload(leg)),
        )
        economics.append(row)
    actions = []
    planned_actions = []
    for existing, action in zip(
        harness.economic_payload["proposed_actions"], harness.order_plan.actions
    ):
        row = dict(existing)
        row["decision_available_at"] = decision_at_text
        actions.append(row)
        planned_actions.append(
            replace(action, decision_available_at=decision_at)
            if hasattr(action, "__dataclass_fields__")
            else SimpleNamespace(**{**vars(action), "decision_available_at": decision_at})
        )
    harness.order_plan.actions = tuple(planned_actions)
    harness.order_plan.decision_available_at = decision_at
    harness.economic_payload = {
        **harness.economic_payload,
        "execution_evidence": ExecutionDecisionJournal._fee_pair_execution_evidence_payload(
            facts
        ),
        "open_risk_candidate": risk_payload,
        "intent_economics": economics,
        "proposed_actions": actions,
    }
    return harness


def test_v24_strategy_and_journal_bind_account_currency_in_decision_evidence(
    single_row_harness,
):
    import alpha003_strategy as alpha003

    for currency in ("CNY", "USD", None):
        facts = replace(
            single_row_harness.facts,
            account=replace(single_row_harness.facts.account, currency=currency),
        )
        strategy_evidence = alpha003._live_execution_evidence_payload(facts)
        journal_evidence = ExecutionDecisionJournal._fee_pair_execution_evidence_payload(
            facts
        )
        assert dict(strategy_evidence) == dict(journal_evidence)
        assert strategy_evidence["account_currency"] == currency


@pytest.fixture
def single_row_harness(tmp_path):
    value = _build_single_row_harness(tmp_path)
    try:
        yield value
    finally:
        _safe_close(value)


def _workflow_events(harness):
    return tuple(
        tuple(row)
        for row in harness.journal._connection.execute(
            "SELECT event_sequence,event_kind FROM execution_fee_pair_workflow_events "
            "WHERE candidate_id=? ORDER BY event_sequence",
            (harness.candidate_id,),
        )
    )


def _table_count(journal, table):
    return journal._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_grid_append_is_fsynced_read_back_idempotent_and_never_settles(harness):
    prefix_before = hashlib.sha256(harness.writer.path.read_bytes()).hexdigest()
    decisions_before = _table_count(harness.journal, "execution_decisions")
    intents_before = _table_count(harness.journal, "execution_decision_intents")

    observation = _append(harness)
    assert observation["evidence_level"] == "WRITER_LOCAL_FSYNC_AND_READBACK"
    assert observation["status"] == "APPENDED"
    assert observation["prefix_sha256"] == prefix_before
    assert observation["record_index"] == 2
    assert harness.candidate.expected_tape_record_index == 1
    assert observation["journal_tape_append_state"] == "REPORTED"
    assert observation["grid_settled"] is False
    assert observation["open_authorized"] is False

    rows = list(
        runner.iter_decision_tape(
            harness.writer.path,
            max_bytes=harness.writer.max_bytes,
            max_record_bytes=runner._FEE_PAIR_SOURCE_ONLY_MAX_RECORD_BYTES,
        )
    )
    assert len(rows) == 3
    assert rows[-1]["record_id"] == observation["record_id"]
    assert rows[-1]["record_index"] == observation["record_index"]
    assert rows[-1]["fee_pair_workflow"] == {
        "candidate_id": harness.candidate_id,
        "candidate_sha256": observation["candidate_sha256"],
    }
    assert rows[-1]["order_plan"] == {
        "status": "NO_ACTION",
        "reason": None,
        "decision_batch_id": harness.candidate.batch_id,
        "decision_available_at": harness.batch.available_at,
        "actions": [],
    }
    assert hashlib.sha256((harness.writer.path.read_bytes())).hexdigest() == (
        harness.writer.summary()["sha256"]
    )

    workflow = harness.journal.fee_pair_workflow_candidate(harness.candidate_id)
    assert workflow.state == "RECEIPT_VERIFIED"
    assert workflow.tape_append_state == "REPORTED"
    assert workflow.grid_settled_decision_id is None
    assert workflow.source_only_decision_id is None
    assert tuple(kind for _sequence, kind in _workflow_events(harness))[-3:] == (
        "GRID_TAPE_APPEND_INTENT",
        "GRID_TAPE_APPEND_CLAIMED",
        "GRID_TAPE_APPEND_REPORTED",
    )
    assert _table_count(harness.journal, "execution_decisions") == decisions_before
    assert _table_count(harness.journal, "execution_decision_intents") == intents_before

    # A repeated same-process callback verifies and returns the existing row;
    # it never writes a second row or repeats the Journal transition.
    bytes_after_first = harness.writer.path.read_bytes()
    events_after_first = _workflow_events(harness)
    repeated = _append(harness)
    assert repeated is observation
    assert harness.writer.path.read_bytes() == bytes_after_first
    assert _workflow_events(harness) == events_after_first
    assert harness.writer.summary()["record_count"] == 2


@pytest.mark.parametrize("conflict", ("tail", "identity"))
def test_prefix_tail_or_open_handle_identity_conflict_fails_before_intent(
    tmp_path, conflict
):
    harness = _build_harness(tmp_path, run_id="grid-writer-" + conflict)
    try:
        original_size = harness.writer.path.stat().st_size
        if conflict == "tail":
            with harness.writer.path.open("ab") as changed:
                changed.write(b"unauthorized-tail\n")
                changed.flush()
        else:
            twin_path = tmp_path / "same-bytes-different-file.jsonl"
            shutil.copyfile(harness.writer.path, twin_path)
            original_handle = harness.writer._handle
            harness.writer._handle = twin_path.open("r+b")
            original_handle.close()
            assert twin_path.stat().st_size == original_size

        with pytest.raises(runner.RunnerError):
            _append(harness)
        assert harness.writer.summary()["failed"] is True
        assert not any(
            kind == "GRID_TAPE_APPEND_INTENT"
            for _sequence, kind in _workflow_events(harness)
        )
        assert harness.writer.summary()["record_count"] == 1
    finally:
        _safe_close(harness)


@pytest.mark.parametrize("failure_point", ("fsync", "readback", "report"))
def test_post_intent_failures_leave_unresolved_and_do_not_settle(
    tmp_path, monkeypatch, failure_point
):
    harness = _build_harness(tmp_path, run_id="grid-writer-failure-" + failure_point)
    try:
        if failure_point == "fsync":
            original_fsync = runner.os.fsync
            calls = 0

            def fail_first_fsync(fd):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError("synthetic fsync failure")
                return original_fsync(fd)

            monkeypatch.setattr(runner.os, "fsync", fail_first_fsync)
            expected_error = "DECISION_TAPE_WRITE_FAILED"
        elif failure_point == "readback":
            def fail_readback(*_args, **_kwargs):
                raise runner.RunnerError("SYNTHETIC_READBACK_FAILURE")

            monkeypatch.setattr(
                harness.writer, "_verify_fee_pair_grid_append_row", fail_readback
            )
            expected_error = "SYNTHETIC_READBACK_FAILURE"
        else:
            def fail_report(*_args, **_kwargs):
                raise ExecutionDecisionJournalError("SYNTHETIC_REPORT_FAILURE")

            monkeypatch.setattr(
                harness.journal, "report_fee_pair_grid_tape_append", fail_report
            )
            expected_error = "SYNTHETIC_REPORT_FAILURE"

        with pytest.raises(Exception, match=expected_error):
            _append(harness)

        workflow = harness.journal.fee_pair_workflow_candidate(harness.candidate_id)
        assert workflow.state == "RECEIPT_VERIFIED"
        assert workflow.tape_append_state == "CLAIMED"
        assert workflow.grid_settled_decision_id is None
        assert harness.writer.summary()["failed"] is True
        assert not any(
            kind in {"GRID_TAPE_APPEND_REPORTED", "GRID_TAPE_APPEND_CONFLICT"}
            for _sequence, kind in _workflow_events(harness)
        )
        assert _table_count(harness.journal, "execution_decisions") == 0
        assert _table_count(harness.journal, "execution_decision_intents") == 0
        rows = list(
            runner.iter_decision_tape(
                harness.writer.path,
                max_bytes=harness.writer.max_bytes,
                max_record_bytes=runner._FEE_PAIR_SOURCE_ONLY_MAX_RECORD_BYTES,
            )
        )
        assert len(rows) == (2 if failure_point == "fsync" else 3)
    finally:
        _safe_close(harness)


def test_changed_repeat_is_a_conflict_without_a_second_physical_row(harness):
    first = _append(harness)
    before = harness.writer.path.read_bytes()
    events = _workflow_events(harness)
    changed_plan = SimpleNamespace(
        status="NO_ACTION",
        reason="synthetic-changed-request",
        decision_batch_id=harness.candidate.batch_id,
        decision_available_at=harness.batch.available_at,
        actions=(),
    )
    with pytest.raises(runner.RunnerError, match="FEE_PAIR_GRID_TAPE_APPEND_CONFLICT"):
        _append(harness, order_plan=changed_plan)
    assert harness.writer.path.read_bytes() == before
    assert _workflow_events(harness) == events
    assert harness.writer.summary()["record_count"] == 2
    workflow = harness.journal.fee_pair_workflow_candidate(harness.candidate_id)
    assert workflow.tape_append_state == "REPORTED"
    assert workflow.grid_settled_decision_id is None
    assert first["status"] == "APPENDED"


def test_v23_writer_appends_one_row_and_settles_the_same_physical_receipt(
    single_row_harness,
):
    harness = single_row_harness
    append_calls = []
    original_append = harness.writer._append

    def counted_append(raw, *, count_record):
        append_calls.append((raw, count_record))
        return original_append(raw, count_record=count_record)

    harness.writer._append = counted_append
    result = _settle_single_row(harness)

    assert len(append_calls) == 1
    assert append_calls[0][1] is True
    assert result["schema"] == "backtrader.alpha003.single_row_grid_settlement.v1"
    assert result["evidence_level"] == (
        "WRITER_LEASED_PHYSICAL_READBACK_AND_JOURNAL_SETTLEMENT"
    )
    assert result["is_new_grid"] is True
    assert result["open_dispatch_authorized"] is False
    assert result["source_receipt"].tape_file_id == harness.writer.file_id
    assert result["source_receipt"].tape_record_id == result["tape_reference"]["record_id"]
    assert result["source_receipt"].tape_record_index == 1

    rows = list(
        runner.iter_decision_tape(
            harness.writer.path,
            max_bytes=harness.writer.max_bytes,
            max_record_bytes=runner._FEE_PAIR_SOURCE_ONLY_MAX_RECORD_BYTES,
        )
    )
    assert len(rows) == 2  # header plus exactly one complete LIVE_READY GRID row
    tape_row = rows[1]
    assert tape_row["record_index"] == 1
    assert tape_row["readiness"] == "LIVE_READY"
    assert tape_row["target_decision"]["status"] == "TARGETS_READY"
    assert tape_row["order_plan"]["status"] == "READY"
    assert len(tape_row["order_plan"]["actions"]) == 2
    for target, member in tape_row["members"].items():
        source = next(
            item for item in harness.candidate.source_members if item.member_id == target
        )
        assert member["raw_values"] == {
            "close": 101.0,
            "high": 102.0,
            "low": 99.0,
            "open": 100.0,
            "openinterest": 0.0,
            "volume": 7.0,
        }
        assert member["source_role"] == source.source_role
        assert member["origin_partition"] == dict(source.origin_partition)
    assert harness.writer.summary()["record_count"] == 1
    assert harness.writer.summary()["sha256"] == hashlib.sha256(
        harness.writer.path.read_bytes()
    ).hexdigest()

    workflow = harness.journal.fee_pair_workflow_candidate(result["candidate_id"])
    assert workflow.state == "RECEIPT_VERIFIED"
    assert workflow.grid_settled_decision_id == result["decision"].decision_id
    assert workflow.source_only_decision_id is None
    assert harness.journal._connection.execute(
        "SELECT COUNT(*) FROM execution_fee_pair_grid_single_row_tape_intents"
    ).fetchone()[0] == 1
    stored_intent = harness.journal._connection.execute(
        """SELECT record_json,record_id,tape_file_id,record_index
           FROM execution_fee_pair_grid_single_row_tape_intents WHERE candidate_id=?""",
        (result["candidate_id"],),
    ).fetchone()
    assert stored_intent["record_json"] == runner._canonical_json_bytes(dict(tape_row)).decode(
        "utf-8"
    ).rstrip("\n")
    assert stored_intent["record_id"] == tape_row["record_id"]
    assert stored_intent["tape_file_id"] == harness.writer.file_id
    assert stored_intent["record_index"] == 1

    highwater = harness.journal.source_highwater(
        harness.candidate.key.account_scope,
        harness.candidate.key.strategy_scope,
        harness.candidate.key.logical_run_id,
        harness.candidate.source_kind,
    )
    assert highwater.anchor_kind == "GRID"
    assert highwater.receipt == result["source_receipt"]
    assert harness.journal.grid_cursor(
        harness.candidate.key.account_scope,
        harness.candidate.key.strategy_scope,
        harness.candidate.key.cohort_id,
    ).ordinal == 1
    assert _table_count(harness.journal, "execution_decisions") == 1
    assert _table_count(harness.journal, "execution_source_highwaters") == 1
    assert _table_count(harness.journal, "execution_fee_pair_workflow_grid_settlements") == 1
    assert _table_count(harness.journal, "execution_decision_intents") == 0

    with pytest.raises(
        ExecutionDecisionJournalError,
        match="FEE_PAIR_OPEN_RISK_RESERVATION_REQUIRED",
    ):
        harness.journal.prepare_intent(
            result["decision"].decision_id,
            result["decision"].intent_keys[0],
            result["decision"].economic_payload["intent_economics"][0],
        )
    assert _table_count(harness.journal, "execution_decision_intents") == 0


def test_v24_amount_reservation_is_atomic_retained_and_does_not_open_the_fence(
    single_row_harness,
):
    harness = _attach_amount_projection(single_row_harness)
    settled = _settle_single_row(harness)
    capacity_before = tuple(
        harness.journal._connection.execute(
            "SELECT record_count,payload_bytes FROM execution_durable_capacity_usage "
            "WHERE capacity_class='BASE'"
        ).fetchone()
    )
    reservation = harness.journal.reserve_fee_pair_grid_amounts(
        settled["candidate_id"], owner_token=harness.owner_token, facts=harness.facts
    )

    assert reservation["status"] == "ACTIVE"
    assert reservation["evidence_level"] == "STRUCTURE_ONLY_STORE_PROJECTION"
    assert reservation["currency"] == "CNY"
    assert len(reservation["reserved_legs"]) == 2
    assert all(int(leg["quantity"]) == 1 for leg in reservation["reserved_legs"])
    assert Decimal(reservation["reserved_notional"]) <= Decimal("200000")
    assert Decimal(reservation["reserved_margin"]) <= Decimal("40000")
    assert Decimal(reservation["reserved_stop_loss_and_fees"]) <= Decimal("1000")
    assert _table_count(harness.journal, "execution_fee_pair_amount_reservations") == 1
    saved_row = harness.journal._connection.execute(
        "SELECT * FROM execution_fee_pair_amount_reservations WHERE candidate_id=?",
        (settled["candidate_id"],),
    ).fetchone()
    capacity_after = tuple(
        harness.journal._connection.execute(
            "SELECT record_count,payload_bytes FROM execution_durable_capacity_usage "
            "WHERE capacity_class='BASE'"
        ).fetchone()
    )
    legacy_event_row = harness.journal._connection.execute(
        "SELECT * FROM execution_fee_pair_amount_lifecycle_events "
        "WHERE candidate_id=? AND event_sequence=1",
        (settled["candidate_id"],),
    ).fetchone()
    active_hold_row = harness.journal._connection.execute(
        "SELECT * FROM execution_fee_pair_amount_active_holds WHERE candidate_id=?",
        (settled["candidate_id"],),
    ).fetchone()
    assert legacy_event_row is not None
    assert active_hold_row is not None
    assert capacity_after == (
        capacity_before[0] + 3,
        capacity_before[1]
        + sum(
            len(journal_module.canonical_sql_row_bytes(row))
            for row in (saved_row, legacy_event_row, active_hold_row)
        ),
    )
    assert harness.journal.reserve_fee_pair_grid_amounts(
        settled["candidate_id"], owner_token=harness.owner_token, facts=harness.facts
    ) == reservation
    assert tuple(
        harness.journal._connection.execute(
            "SELECT record_count,payload_bytes FROM execution_durable_capacity_usage "
            "WHERE capacity_class='BASE'"
        ).fetchone()
    ) == capacity_after
    with pytest.raises(sqlite3.IntegrityError, match="FEE_PAIR_AMOUNT_RESERVATION_IMMUTABLE"):
        harness.journal._connection.execute(
            "UPDATE execution_fee_pair_amount_reservations SET reservation_json='{}' "
            "WHERE candidate_id=?",
            (settled["candidate_id"],),
        )
    with pytest.raises(sqlite3.IntegrityError, match="FEE_PAIR_AMOUNT_RESERVATION_IMMUTABLE"):
        harness.journal._connection.execute(
            "DELETE FROM execution_fee_pair_amount_reservations WHERE candidate_id=?",
            (settled["candidate_id"],),
        )
    stored_reservation = harness.journal.fee_pair_grid_amount_reservation(
        settled["candidate_id"]
    )
    assert all(stored_reservation[name] == value for name, value in reservation.items())
    assert stored_reservation["lifecycle_state"] == "LEGACY_HELD"
    with pytest.raises(
        ExecutionDecisionJournalError, match="FEE_PAIR_AMOUNT_HOLD_ACTIVE"
    ):
        harness.journal.prepare_intent(
            settled["decision"].decision_id,
            settled["decision"].intent_keys[0],
            settled["decision"].economic_payload["intent_economics"][0],
        )
    assert _table_count(harness.journal, "execution_decision_intents") == 0

    journal_path = harness.journal.path
    harness.writer.close()
    harness.journal.close()
    reopened = ExecutionDecisionJournal(
        journal_path,
        max_payload_bytes=runner._LIVE_DECISION_JOURNAL_MAX_PAYLOAD_BYTES,
    )
    try:
        reopened_reservation = reopened.fee_pair_grid_amount_reservation(
            settled["candidate_id"]
        )
        assert all(
            reopened_reservation[name] == value for name, value in reservation.items()
        )
        assert reopened_reservation["lifecycle_state"] == "LEGACY_HELD"
        assert _table_count(reopened, "execution_fee_pair_amount_reservations") == 1
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_AMOUNT_HOLD_ACTIVE"
        ):
            reopened.prepare_intent(
                settled["decision"].decision_id,
                settled["decision"].intent_keys[0],
                settled["decision"].economic_payload["intent_economics"][0],
            )
    finally:
        reopened.close()
        harness.writer = SimpleNamespace(close=lambda: None)
        harness.journal = SimpleNamespace(close=lambda: None)


def test_v24_database_reopen_migrates_legacy_reservation_to_fail_closed_hold(
    single_row_harness,
):
    harness = _attach_amount_projection(single_row_harness)
    settled = _settle_single_row(harness)
    reservation = harness.journal.reserve_fee_pair_grid_amounts(
        settled["candidate_id"], owner_token=harness.owner_token, facts=harness.facts
    )
    journal_path = harness.journal.path
    harness.writer.close()
    harness.journal.close()

    # Reconstruct the v24 on-disk shape from a current journal: the immutable
    # reservation row and its original capacity charge remain, while only the
    # v25 lifecycle projection and its two capacity charges are removed.
    with sqlite3.connect(journal_path) as connection:
        connection.row_factory = sqlite3.Row
        event = connection.execute(
            "SELECT * FROM execution_fee_pair_amount_lifecycle_events "
            "WHERE candidate_id=? AND event_sequence=1",
            (settled["candidate_id"],),
        ).fetchone()
        active = connection.execute(
            "SELECT * FROM execution_fee_pair_amount_active_holds WHERE candidate_id=?",
            (settled["candidate_id"],),
        ).fetchone()
        assert event is not None
        assert active is not None
        removed_payload_bytes = sum(
            len(journal_module.canonical_sql_row_bytes(row)) for row in (event, active)
        )
        for trigger in (
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
        ):
            connection.execute("DROP TRIGGER {}".format(trigger))
        connection.execute("DROP TABLE execution_fee_pair_amount_active_holds")
        connection.execute("DROP TABLE execution_fee_pair_amount_lifecycle_events")
        connection.execute("DROP TABLE execution_fee_pair_amount_open_reservations")
        connection.execute(
            "UPDATE execution_durable_capacity_usage "
            "SET record_count=record_count-2,payload_bytes=payload_bytes-? "
            "WHERE capacity_class='BASE'",
            (removed_payload_bytes,),
        )
        connection.execute("PRAGMA user_version=24")

    reopened = ExecutionDecisionJournal(
        journal_path,
        max_payload_bytes=runner._LIVE_DECISION_JOURNAL_MAX_PAYLOAD_BYTES,
    )
    try:
        assert reopened._connection.execute("PRAGMA user_version").fetchone()[0] == 25
        migrated = reopened.fee_pair_grid_amount_reservation(settled["candidate_id"])
        assert migrated["reservation_sha256"] == reservation["reservation_sha256"]
        assert migrated["lifecycle_state"] == "LEGACY_HELD"
        assert _table_count(reopened, "execution_fee_pair_amount_active_holds") == 1
        with pytest.raises(ExecutionDecisionJournalError, match="FEE_PAIR_AMOUNT_HOLD_ACTIVE"):
            reopened.prepare_intent(
                settled["decision"].decision_id,
                settled["decision"].intent_keys[0],
                settled["decision"].economic_payload["intent_economics"][0],
            )
    finally:
        reopened.close()
        harness.writer = SimpleNamespace(close=lambda: None)
        harness.journal = SimpleNamespace(close=lambda: None)


@pytest.mark.parametrize("extra_exposure", ("third_target_position", "third_target_open_order"))
def test_v24_amount_reservation_rejects_unpriced_extra_exposure_without_capacity_change(
    tmp_path, extra_exposure
):
    harness = _build_single_row_harness(
        tmp_path, run_id="grid-writer-v24-exposure-" + extra_exposure
    )
    try:
        facts = harness.facts
        if extra_exposure == "third_target_position":
            # Make C part of the complete execution target scope. The GRID
            # candidate still selects only A/B, and its planner-shaped risk
            # payload deliberately continues to report held_fee_reserve=0.
            facts = replace(facts, execution_target_ids=facts._full_target_ids)
            target_position = next(
                item for item in facts.positions if item.target_id == "C"
            )
            target_position = replace(
                target_position,
                quantity=Decimal("1"),
                broker_quantity=Decimal("1"),
                long_quantity=Decimal("1"),
                short_quantity=Decimal("0"),
                attributed_signed_quantity=Decimal("1"),
                owner_strategy_scope=facts.strategy_scope,
                owner_intent_id="third-target-open-intent",
                average_price=Decimal("100"),
                stop_price=Decimal("99"),
                held_eligible_bars=1,
                opening_fee_total=Decimal("0"),
                opening_fees_known=True,
                position_book_status="MATCHED",
            )
            facts = replace(
                facts,
                positions=tuple(
                    target_position if item.target_id == "C" else item
                    for item in facts.positions
                ),
            )
        else:
            from backtrader.stores.factor_execution_facts import (
                FactorExecutionWorkingOrderFacts,
            )

            open_order = FactorExecutionWorkingOrderFacts(
                target_id="C",
                instrument="j2510",
                exchange="DCE",
                order_ref="third-target-open-order",
                state="ACCEPTED",
                side="BUY",
                position_effect="OPEN",
                remaining_quantity=Decimal("1"),
                owner_strategy_scope=facts.strategy_scope,
                owner_intent_id="third-target-open-intent",
                execution_unknown=False,
                cancel_pending=False,
                broker_order_ref=44,
                order_sys_id="third-target-open-sysid",
            )
            facts = replace(
                facts,
                execution_target_ids=facts._full_target_ids,
                working_orders=(open_order,),
            )

        harness.facts = facts
        _attach_amount_projection(harness)
        assert harness.economic_payload["open_risk_candidate"]["held_fee_reserve"] == "0"
        settled = _settle_single_row(harness)
        exposure = settled["decision"].economic_payload["execution_evidence"][
            "portfolio_exposure"
        ]
        if extra_exposure == "third_target_position":
            target = next(item for item in exposure["positions"] if item["target_id"] == "C")
            assert target["quantity"] == target["long_quantity"] == "1"
        else:
            assert exposure["working_orders"][0]["position_effect"] == "OPEN"

        capacity_before = tuple(
            harness.journal._connection.execute(
                "SELECT record_count,payload_bytes FROM execution_durable_capacity_usage "
                "WHERE capacity_class='BASE'"
            ).fetchone()
        )
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_AMOUNT_EXPOSURE_UNPROVEN",
        ):
            harness.journal.reserve_fee_pair_grid_amounts(
                settled["candidate_id"],
                owner_token=harness.owner_token,
                facts=harness.facts,
            )
        assert _table_count(harness.journal, "execution_fee_pair_amount_reservations") == 0
        assert tuple(
            harness.journal._connection.execute(
                "SELECT record_count,payload_bytes FROM execution_durable_capacity_usage "
                "WHERE capacity_class='BASE'"
            ).fetchone()
        ) == capacity_before
        highwater = harness.journal.source_highwater(
            harness.candidate.key.account_scope,
            harness.candidate.key.strategy_scope,
            harness.candidate.key.logical_run_id,
            harness.candidate.source_kind,
        )
        assert highwater.anchor_kind == "GRID"
        assert highwater.decision_id == settled["decision"].decision_id
    finally:
        _safe_close(harness)


def test_v24_amount_reservation_rejects_incomplete_position_query_without_mutation(
    tmp_path,
):
    harness = _build_single_row_harness(
        tmp_path, run_id="grid-writer-v24-exposure-incomplete-query"
    )
    try:
        _attach_amount_projection(harness)
        settled = _settle_single_row(harness)
        incomplete = replace(
            harness.facts,
            query_provenance=tuple(
                query
                for query in harness.facts.query_provenance
                if query.family != "positions_result"
            ),
        )
        capacity_before = tuple(
            harness.journal._connection.execute(
                "SELECT record_count,payload_bytes FROM execution_durable_capacity_usage "
                "WHERE capacity_class='BASE'"
            ).fetchone()
        )
        with pytest.raises(ExecutionDecisionJournalError):
            harness.journal.reserve_fee_pair_grid_amounts(
                settled["candidate_id"],
                owner_token=harness.owner_token,
                facts=incomplete,
            )
        assert _table_count(harness.journal, "execution_fee_pair_amount_reservations") == 0
        assert tuple(
            harness.journal._connection.execute(
                "SELECT record_count,payload_bytes FROM execution_durable_capacity_usage "
                "WHERE capacity_class='BASE'"
            ).fetchone()
        ) == capacity_before
        highwater = harness.journal.source_highwater(
            harness.candidate.key.account_scope,
            harness.candidate.key.strategy_scope,
            harness.candidate.key.logical_run_id,
            harness.candidate.source_kind,
        )
        assert highwater.anchor_kind == "GRID"
        assert highwater.decision_id == settled["decision"].decision_id
    finally:
        _safe_close(harness)


@pytest.mark.parametrize("currency", ("USD", None))
def test_v24_amount_reservation_rejects_missing_or_non_cny_currency(
    tmp_path, currency
):
    harness = _build_single_row_harness(
        tmp_path, run_id="grid-writer-v24-currency-" + str(currency)
    )
    try:
        _attach_amount_projection(harness, currency=currency)
        settled = _settle_single_row(harness)
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_AMOUNT_CURRENCY_UNAVAILABLE"
        ):
            harness.journal.reserve_fee_pair_grid_amounts(
                settled["candidate_id"],
                owner_token=harness.owner_token,
                facts=harness.facts,
            )
        assert _table_count(harness.journal, "execution_fee_pair_amount_reservations") == 0
        assert harness.journal.fee_pair_grid_amount_reservation(settled["candidate_id"]) is None
        assert harness.journal.source_highwater(
            harness.candidate.key.account_scope,
            harness.candidate.key.strategy_scope,
            harness.candidate.key.logical_run_id,
            harness.candidate.source_kind,
        ).anchor_kind == "GRID"
    finally:
        _safe_close(harness)


def test_v24_amount_reservation_rejects_currency_changed_after_grid_settlement(
    tmp_path,
):
    harness = _build_single_row_harness(tmp_path, run_id="grid-writer-v24-currency-swap")
    try:
        _attach_amount_projection(harness, currency="USD")
        settled = _settle_single_row(harness)
        cny_facts = replace(
            harness.facts,
            account=replace(harness.facts.account, currency="CNY"),
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_FACTS_SNAPSHOT_MISMATCH"
        ):
            harness.journal.reserve_fee_pair_grid_amounts(
                settled["candidate_id"],
                owner_token=harness.owner_token,
                facts=cny_facts,
            )
        assert _table_count(harness.journal, "execution_fee_pair_amount_reservations") == 0
    finally:
        _safe_close(harness)


def test_v24_amount_reservation_rejects_legacy_settlement_without_currency_binding(
    tmp_path, monkeypatch
):
    original_evidence = ExecutionDecisionJournal._fee_pair_execution_evidence_payload

    def legacy_evidence(facts):
        result = dict(original_evidence(facts))
        result.pop("account_currency", None)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(
            ExecutionDecisionJournal,
            "_fee_pair_execution_evidence_payload",
            staticmethod(legacy_evidence),
        )
        harness = _build_single_row_harness(
            tmp_path, run_id="grid-writer-v24-legacy-currency"
        )
        try:
            _attach_amount_projection(harness, currency="CNY")
            settled = _settle_single_row(harness)
        finally:
            # Retain the Journal row for the negative check below; close only
            # the writer whose physical append has already completed.
            harness.writer.close()
    try:
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_FACTS_SNAPSHOT_MISMATCH"
        ):
            harness.journal.reserve_fee_pair_grid_amounts(
                settled["candidate_id"],
                owner_token=harness.owner_token,
                facts=harness.facts,
            )
        assert _table_count(harness.journal, "execution_fee_pair_amount_reservations") == 0
    finally:
        harness.journal.close()


@pytest.mark.parametrize(
    "failure_case,expected_code",
    (
        ("per_leg_policy", "FEE_PAIR_AMOUNT_RESERVATION_INVALID"),
        ("available_margin", "FEE_PAIR_AMOUNT_RESERVATION_INVALID"),
    ),
)
def test_v24_amount_reservation_rejects_limits_without_consuming_capacity(
    tmp_path, failure_case, expected_code
):
    harness = _build_single_row_harness(
        tmp_path, run_id="grid-writer-v24-limit-" + failure_case
    )
    try:
        if failure_case == "per_leg_policy":
            _attach_amount_projection(
                harness, policy_overrides={"max_margin_per_position": "1"}
            )
        else:
            _attach_amount_projection(
                harness,
                account_overrides={"available_margin": Decimal("1")},
            )
        settled = _settle_single_row(harness)
        durable_before = tuple(
            harness.journal._connection.execute(
                "SELECT record_count,payload_bytes FROM execution_durable_capacity_usage "
                "WHERE capacity_class='BASE'"
            ).fetchone()
        )
        with pytest.raises(ExecutionDecisionJournalError, match=expected_code):
            harness.journal.reserve_fee_pair_grid_amounts(
                settled["candidate_id"],
                owner_token=harness.owner_token,
                facts=harness.facts,
            )
        assert _table_count(harness.journal, "execution_fee_pair_amount_reservations") == 0
        assert tuple(
            harness.journal._connection.execute(
                "SELECT record_count,payload_bytes FROM execution_durable_capacity_usage "
                "WHERE capacity_class='BASE'"
            ).fetchone()
        ) == durable_before
        assert harness.journal.source_highwater(
            harness.candidate.key.account_scope,
            harness.candidate.key.strategy_scope,
            harness.candidate.key.logical_run_id,
            harness.candidate.source_kind,
        ).anchor_kind == "GRID"
    finally:
        _safe_close(harness)


def test_v24_amount_reservation_capacity_failure_rolls_back_atomically(
    tmp_path,
):
    harness = _build_single_row_harness(tmp_path, run_id="grid-writer-v24-capacity")
    try:
        _attach_amount_projection(harness)
        settled = _settle_single_row(harness)
        usage = harness.journal._connection.execute(
            "SELECT record_count,payload_bytes FROM execution_durable_capacity_usage "
            "WHERE capacity_class='BASE'"
        ).fetchone()
        harness.journal.durable_capacity_limits = DurableCapacityLimits(
            max_durable_base_records=usage["record_count"],
            max_durable_base_bytes=usage["payload_bytes"],
            max_durable_settlement_records=100_000,
            max_durable_settlement_bytes=1_073_741_824,
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="DURABLE_BASE_RECORDS_EXHAUSTED"
        ):
            harness.journal.reserve_fee_pair_grid_amounts(
                settled["candidate_id"],
                owner_token=harness.owner_token,
                facts=harness.facts,
            )
        assert _table_count(harness.journal, "execution_fee_pair_amount_reservations") == 0
        assert tuple(
            harness.journal._connection.execute(
                "SELECT record_count,payload_bytes FROM execution_durable_capacity_usage "
                "WHERE capacity_class='BASE'"
            ).fetchone()
        ) == tuple(usage)
        assert harness.journal.fee_pair_grid_amount_reservation(settled["candidate_id"]) is None
    finally:
        _safe_close(harness)


def test_v24_amount_reservation_is_idempotent_across_concurrent_journal_connections(
    tmp_path,
):
    harness = _build_single_row_harness(tmp_path, run_id="grid-writer-v24-concurrent")
    second_journal = None
    try:
        _attach_amount_projection(harness)
        settled = _settle_single_row(harness)
        second_journal = ExecutionDecisionJournal(
            harness.journal.path,
            max_payload_bytes=runner._LIVE_DECISION_JOURNAL_MAX_PAYLOAD_BYTES,
        )

        def reserve(journal):
            return journal.reserve_fee_pair_grid_amounts(
                settled["candidate_id"],
                owner_token=harness.owner_token,
                facts=harness.facts,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (executor.submit(reserve, harness.journal), executor.submit(reserve, second_journal))
            results = tuple(future.result(timeout=10) for future in futures)
        assert results[0] == results[1]
        assert _table_count(harness.journal, "execution_fee_pair_amount_reservations") == 1
    finally:
        if second_journal is not None:
            second_journal.close()
        _safe_close(harness)


def test_v24_migration_adds_amount_reservation_without_rewriting_v23_workflow(
    tmp_path,
):
    harness = _build_single_row_harness(tmp_path, run_id="grid-writer-v24-migration")
    settled = _settle_single_row(harness)
    journal_path = harness.journal.path
    candidate_id = settled["candidate_id"]
    harness.writer.close()
    harness.journal.close()
    try:
        with sqlite3.connect(journal_path) as connection:
            # The fixture starts at the current schema; reconstruct the v23
            # shape, including removal of the v25 projection whose triggers
            # reference the v24 amount table.
            _drop_v25_amount_lifecycle_objects(connection)
            connection.execute("DROP TRIGGER execution_fee_pair_amount_reservation_no_update")
            connection.execute("DROP TRIGGER execution_fee_pair_amount_reservation_no_delete")
            connection.execute("DROP TABLE execution_fee_pair_amount_reservations")
            connection.execute("PRAGMA user_version=23")
        reopened = ExecutionDecisionJournal(
            journal_path,
            max_payload_bytes=runner._LIVE_DECISION_JOURNAL_MAX_PAYLOAD_BYTES,
        )
        try:
            assert reopened._connection.execute("PRAGMA user_version").fetchone()[0] == 25
            assert reopened.fee_pair_workflow_candidate(candidate_id).state == "RECEIPT_VERIFIED"
            assert _table_count(reopened, "execution_fee_pair_amount_reservations") == 0
        finally:
            reopened.close()
    finally:
        harness.writer = SimpleNamespace(close=lambda: None)
        harness.journal = SimpleNamespace(close=lambda: None)


@pytest.mark.parametrize("changed_component", ("leg_action", "leg_economics"))
def test_v23_settlement_rejects_economics_different_from_the_tape_row(
    tmp_path, monkeypatch, changed_component
):
    harness = _build_single_row_harness(
        tmp_path, run_id="grid-writer-v23-bind-" + changed_component
    )
    try:
        original_settle = harness.journal.settle_fee_pair_grid_decision

        def settle_changed_plan(*args, **kwargs):
            changed = dict(kwargs["economic_payload"])
            if changed_component == "leg_action":
                actions = [dict(item) for item in changed["proposed_actions"]]
                actions[0]["quantity"] += 1
                changed["proposed_actions"] = actions
            else:
                economics = [dict(item) for item in changed["intent_economics"]]
                economics[1]["quantity"] += 1
                changed["intent_economics"] = economics
            kwargs["economic_payload"] = changed
            return original_settle(*args, **kwargs)

        monkeypatch.setattr(harness.journal, "settle_fee_pair_grid_decision", settle_changed_plan)
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_SINGLE_ROW_TAPE_PLAN_BINDING_INVALID",
        ):
            _settle_single_row(harness)
        assert harness.writer.summary()["failed"] is True
        rows = list(
            runner.iter_decision_tape(
                harness.writer.path,
                max_bytes=harness.writer.max_bytes,
                max_record_bytes=runner._FEE_PAIR_SOURCE_ONLY_MAX_RECORD_BYTES,
            )
        )
        assert len(rows) == 2
        workflow = harness.journal.fee_pair_workflow_candidate(
            _table_count(harness.journal, "execution_fee_pair_workflows")
            and harness.journal._connection.execute(
                "SELECT candidate_id FROM execution_fee_pair_workflows"
            ).fetchone()[0]
        )
        assert workflow.state == "APPEND_CLAIMED"
        assert workflow.grid_settled_decision_id is None
        assert harness.journal.source_highwater(
            harness.candidate.key.account_scope,
            harness.candidate.key.strategy_scope,
            harness.candidate.key.logical_run_id,
            harness.candidate.source_kind,
        ) is None
        for table in (
            "execution_decisions",
            "execution_source_highwaters",
            "execution_grid_cursors",
            "execution_grid_highwaters",
            "execution_fee_pair_workflow_grid_settlements",
            "execution_decision_intents",
        ):
            assert _table_count(harness.journal, table) == 0
    finally:
        _safe_close(harness)


@pytest.mark.parametrize("failure_point", ("append", "readback"))
def test_v23_post_claim_failure_keeps_grid_unresolved_and_no_highwater(
    tmp_path, monkeypatch, failure_point
):
    harness = _build_single_row_harness(
        tmp_path, run_id="grid-writer-v23-failure-" + failure_point
    )
    try:
        if failure_point == "append":
            def fail_append(_raw, *, count_record):
                assert count_record is True
                raise OSError("synthetic single-row append failure")

            monkeypatch.setattr(harness.writer, "_append", fail_append)
            expected = "synthetic single-row append failure"
        else:
            def fail_readback(**_kwargs):
                raise ExecutionDecisionJournalError("SYNTHETIC_V23_READBACK_FAILURE")

            monkeypatch.setattr(
                harness.journal,
                "_verify_fee_pair_grid_single_row_tape_readback_in_transaction",
                fail_readback,
            )
            expected = "SYNTHETIC_V23_READBACK_FAILURE"
        with pytest.raises(Exception, match=expected):
            _settle_single_row(harness)

        assert harness.writer.summary()["failed"] is True
        rows = list(
            runner.iter_decision_tape(
                harness.writer.path,
                max_bytes=harness.writer.max_bytes,
                max_record_bytes=runner._FEE_PAIR_SOURCE_ONLY_MAX_RECORD_BYTES,
            )
        )
        assert len(rows) == (1 if failure_point == "append" else 2)
        candidate_id = harness.journal._connection.execute(
            "SELECT candidate_id FROM execution_fee_pair_workflows"
        ).fetchone()[0]
        workflow = harness.journal.fee_pair_workflow_candidate(candidate_id)
        assert workflow.state == "APPEND_CLAIMED"
        assert workflow.grid_settled_decision_id is None
        assert harness.journal.source_highwater(
            harness.candidate.key.account_scope,
            harness.candidate.key.strategy_scope,
            harness.candidate.key.logical_run_id,
            harness.candidate.source_kind,
        ) is None
        for table in (
            "execution_decisions",
            "execution_source_highwaters",
            "execution_grid_cursors",
            "execution_grid_highwaters",
            "execution_fee_pair_workflow_grid_settlements",
        ):
            assert _table_count(harness.journal, table) == 0
    finally:
        _safe_close(harness)


def test_v23_claim_capacity_reserves_intent_before_any_physical_append(
    tmp_path, monkeypatch
):
    harness = _build_single_row_harness(tmp_path, run_id="grid-writer-v23-capacity")
    try:
        original_claim = harness.journal.record_fee_pair_grid_single_row_append_claim

        def cap_at_existing_reservation(*args, **kwargs):
            base = harness.journal._connection.execute(
                """SELECT record_count FROM execution_durable_capacity_usage
                   WHERE capacity_class='BASE'"""
            ).fetchone()[0]
            workflow_reserved = harness.journal._connection.execute(
                """SELECT COALESCE(SUM(reserved_records),0)
                   FROM execution_fee_pair_workflow_durable_reservations
                   WHERE state='ACTIVE'"""
            ).fetchone()[0]
            candidate_reserved = harness.journal._connection.execute(
                """SELECT COALESCE(SUM(reserved_records),0)
                   FROM execution_fee_pair_candidate_capacity_reservations
                   WHERE state='RESERVED'"""
            ).fetchone()[0]
            current_bytes = harness.journal._connection.execute(
                """SELECT payload_bytes FROM execution_durable_capacity_usage
                   WHERE capacity_class='BASE'"""
            ).fetchone()[0]
            workflow_bytes = harness.journal._connection.execute(
                """SELECT COALESCE(SUM(reserved_bytes),0)
                   FROM execution_fee_pair_workflow_durable_reservations
                   WHERE state='ACTIVE'"""
            ).fetchone()[0]
            candidate_bytes = harness.journal._connection.execute(
                """SELECT COALESCE(SUM(reserved_bytes),0)
                   FROM execution_fee_pair_candidate_capacity_reservations
                   WHERE state='RESERVED'"""
            ).fetchone()[0]
            harness.journal.durable_capacity_limits = DurableCapacityLimits(
                max_durable_base_records=base + workflow_reserved + candidate_reserved,
                max_durable_base_bytes=current_bytes + workflow_bytes + candidate_bytes,
                max_durable_settlement_records=100_000,
                max_durable_settlement_bytes=1_073_741_824,
            )
            return original_claim(*args, **kwargs)

        monkeypatch.setattr(
            harness.journal,
            "record_fee_pair_grid_single_row_append_claim",
            cap_at_existing_reservation,
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="DURABLE_BASE_RECORDS_EXHAUSTED"
        ):
            _settle_single_row(harness)
        assert harness.writer.summary()["failed"] is True
        assert harness.writer.summary()["record_count"] == 0
        rows = list(
            runner.iter_decision_tape(
                harness.writer.path,
                max_bytes=harness.writer.max_bytes,
                max_record_bytes=runner._FEE_PAIR_SOURCE_ONLY_MAX_RECORD_BYTES,
            )
        )
        assert len(rows) == 1
        workflow = harness.journal._connection.execute(
            """SELECT state,grid_decision_id FROM execution_fee_pair_workflows"""
        ).fetchone()
        assert tuple(workflow) == ("RESERVED", None)
        assert _table_count(harness.journal, "execution_fee_pair_grid_single_row_tape_intents") == 0
        assert _table_count(harness.journal, "execution_decisions") == 0
        assert _table_count(harness.journal, "execution_source_highwaters") == 0
    finally:
        _safe_close(harness)


def test_v23_archive_rejects_an_oversized_single_row_tape_intent(
    tmp_path, single_row_harness
):
    harness = single_row_harness
    settled = _settle_single_row(harness)
    archive_path = tmp_path / "grid-writer-v23-archive.sqlite3"
    archived = harness.journal.archive_snapshot(archive_path)
    assert archived.schema_version == 25

    oversized = "x" * journal_module._MAX_FEE_PAIR_GRID_TAPE_RECORD_BYTES
    with sqlite3.connect(archive_path) as connection:
        connection.execute(
            "DROP TRIGGER execution_fee_pair_grid_single_row_tape_intent_no_update"
        )
        connection.execute(
            """UPDATE execution_fee_pair_grid_single_row_tape_intents
               SET record_json=? WHERE candidate_id=?""",
            (oversized, settled["candidate_id"]),
        )

    with pytest.raises(
        archive_module.ExecutionJournalArchiveError,
        match="ARCHIVE_FEE_PAIR_TAPE_RECORD_TOO_LARGE",
    ):
        archive_module.verify_execution_journal_archive(
            archive_path, expected_schema_version=25
        )


@pytest.mark.parametrize("encoding", ("UTF-8", "UTF-16le"))
def test_v24_archive_rejects_an_oversized_amount_reservation(tmp_path, encoding):
    harness = _build_single_row_harness(
        tmp_path,
        run_id="grid-writer-v24-archive-" + encoding.replace("-", ""),
        journal_encoding=encoding,
    )
    try:
        _attach_amount_projection(harness)
        settled = _settle_single_row(harness)
        harness.journal.reserve_fee_pair_grid_amounts(
            settled["candidate_id"],
            owner_token=harness.owner_token,
            facts=harness.facts,
        )
        archive_path = tmp_path / "grid-writer-v24-archive-copy.sqlite3"
        archived = harness.journal.archive_snapshot(archive_path)
        assert archived.schema_version == 25
        assert archived.table_row_counts["execution_fee_pair_amount_reservations"] == 1

        oversized = "x" * (journal_module._MAX_FEE_PAIR_AMOUNT_RESERVATION_BYTES + 1)
        with sqlite3.connect(archive_path) as connection:
            connection.execute(
                "DROP TRIGGER execution_fee_pair_amount_reservation_no_update"
            )
            connection.execute(
                "UPDATE execution_fee_pair_amount_reservations SET reservation_json=? "
                "WHERE candidate_id=?",
                (oversized, settled["candidate_id"]),
            )

        with pytest.raises(
            archive_module.ExecutionJournalArchiveError,
            match="ARCHIVE_FEE_PAIR_AMOUNT_RESERVATION_TOO_LARGE",
        ):
            archive_module.verify_execution_journal_archive(
                archive_path, expected_schema_version=25
            )
    finally:
        _safe_close(harness)


def test_single_row_grid_tape_projects_mapping_order_plan_exactly(harness):
    """The settlement adapter accepts its explicit serialized plan mapping."""

    action_fields = (
        "action",
        "target_id",
        "instrument",
        "side",
        "position_effect",
        "quantity",
        "limit_price",
        "offset",
        "reason",
        "planned_stop_price",
        "exchange",
        "decision_available_at",
        "entry_grid_ordinal",
    )
    plan = harness.order_plan
    mapped_plan = {
        "status": plan.status,
        "reason": plan.reason,
        "decision_batch_id": plan.decision_batch_id,
        "decision_available_at": plan.decision_available_at,
        "actions": [
            {name: getattr(action, name) for name in action_fields}
            for action in plan.actions
        ],
    }
    common = {
        "file_id": harness.writer.file_id,
        "index": harness.writer._record_count + 1,
        "targets": harness.writer.targets,
        "calendar_fingerprint": harness.writer.calendar_fingerprint,
    }
    object_row = runner._decision_tape_record(
        harness.batch,
        harness.snapshot,
        harness.target_decision,
        plan,
        **common,
    )
    mapping_row = runner._decision_tape_record(
        harness.batch,
        harness.snapshot,
        harness.target_decision,
        mapped_plan,
        **common,
    )

    assert mapping_row["order_plan"] == object_row["order_plan"]
