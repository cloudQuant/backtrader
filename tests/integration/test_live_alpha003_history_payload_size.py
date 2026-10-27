"""Measure 87-target Alpha003 decision/source payloads for the live runner.

The execution evidence is synthetic and bounded; the journal, serializer,
source receipts, and Alpha003 shadow planner are production APIs. No provider
or order-dispatch operation is constructed.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Mapping
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import backtrader as bt

from backtrader.research.live_cohort import LiveCohortBatch
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
    ExecutionDecisionKey,
    ExecutionSourceHighWaterRef,
    ExecutionSourceMemberReceipt,
    ExecutionSourceReceipt,
    _canonical_json,
)
from backtrader.stores.factor_execution import FactorExecutionCoordinator
from backtrader.stores.factor_execution_facts import (
    FactorExecutionAccountFacts,
    FactorExecutionFacts,
    FactorExecutionQueryFact,
    FactorExecutionQuoteFacts,
)
from backtrader.stores.registered_sim import RegisteredSimStore
from tests.integration import test_factor_decision_replay_economics as alpha003


_UTC = timezone.utc
_BASE = datetime(2026, 10, 24, 1, 0, tzinfo=_UTC)
_ACCOUNT = alpha003.ACCOUNT_SCOPE
_STRATEGY = alpha003.STRATEGY_SCOPE
_RUN = alpha003.RUN_ID
_LEGACY_SOURCE_KIND = "ALPHA003_GRID"
_SOURCE_KIND_SUFFIX = ":trading-day-map-v1:"
_CALENDAR_ID = "alpha003-calendar-v1"
_CALENDAR_VERSION = "rules-v1"
_COHORT_ID = "alpha003:alpha003-calendar-v1:1"
_MEMBER_COUNT = 87
_TAPE_FILE_ID = "alpha003-decision-tape-size-fixture-v1"
_DEFAULT_CAP = 65_536
_BOUNDED_OVERRIDE_CAP = 131_072
# The prior bare-kind fixture was 109,223 bytes. The production lineage kind
# retains the 13-byte prefix and adds the 21-byte version suffix plus a
# fixed-width 64-character SHA-256 digest in the serialized receipt.
_EXPECTED_GRID_PAYLOAD_BYTES = (
    109_223 + len(_SOURCE_KIND_SUFFIX.encode("ascii")) + 64
)
_RUNNER = None
_SOURCE_KIND = None


def _load_runner():
    global _RUNNER
    if _RUNNER is not None:
        return _RUNNER
    example = (
        Path(__file__).resolve().parents[2]
        / "examples"
        / "unified"
        / "028_alpha003_simnow_minute"
    )
    entry_path = example / "entry_tier.py"
    entry_spec = importlib.util.spec_from_file_location("entry_tier", entry_path)
    assert entry_spec is not None and entry_spec.loader is not None
    entry_module = importlib.util.module_from_spec(entry_spec)
    prior_entry = sys.modules.get("entry_tier")
    sys.modules["entry_tier"] = entry_module
    try:
        entry_spec.loader.exec_module(entry_module)
        runner_path = example / "run.py"
        runner_spec = importlib.util.spec_from_file_location(
            "i51_history_payload_size_runner_source_test", runner_path
        )
        assert runner_spec is not None and runner_spec.loader is not None
        runner = importlib.util.module_from_spec(runner_spec)
        sys.modules[runner_spec.name] = runner
        runner_spec.loader.exec_module(runner)
    finally:
        if prior_entry is None:
            sys.modules.pop("entry_tier", None)
        else:
            sys.modules["entry_tier"] = prior_entry
    _RUNNER = runner
    return runner


def _source_kind():
    global _SOURCE_KIND
    if _SOURCE_KIND is None:
        _SOURCE_KIND = _load_runner()._live_source_lineage_kind_from_days(
            {"DCE": date(2026, 10, 24)}
        )
    assert _SOURCE_KIND.startswith(_LEGACY_SOURCE_KIND + _SOURCE_KIND_SUFFIX)
    assert len(_SOURCE_KIND) == len(_LEGACY_SOURCE_KIND + _SOURCE_KIND_SUFFIX) + 64
    return _SOURCE_KIND


def _time(value: datetime) -> str:
    return value.astimezone(_UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _receipt(*, source_role="live", readiness="LIVE_READY") -> ExecutionSourceReceipt:
    close = _BASE
    bucket_start = close - timedelta(minutes=1)
    available_at = close + timedelta(seconds=2)
    batch_id = "{}:{}:{}:{}:0".format(_COHORT_ID, _CALENDAR_ID, 1, _CALENDAR_VERSION)
    members = tuple(
        ExecutionSourceMemberReceipt(
            member_id="target-{:03d}".format(index),
            source_ref="ctp-live:target-{:03d}:instrument-{:03d}".format(index, index),
            source_role=source_role,
            connection_generation="{}-generation-1".format(source_role),
            feed_sequence=1,
            bar_id="bar-1-000-{:03d}".format(index),
            bucket_start=_time(bucket_start),
            close_time=_time(close),
            available_at=_time(available_at),
            trading_day="20261024",
            session_segment="regular",
            timezone_id="Asia/Shanghai",
            clock_domain_id="synthetic-ctp-clock",
            complete=True,
            quality="GOOD",
            present=True,
            event_source="ctp-live",
            rules_hash="b" * 64,
        )
        for index in range(_MEMBER_COUNT)
    )
    return ExecutionSourceReceipt(
        source_kind=_source_kind(),
        cohort_id=_COHORT_ID,
        calendar_id=_CALENDAR_ID,
        calendar_version=_CALENDAR_VERSION,
        calendar_fingerprint="a" * 64,
        epoch_id=1,
        slot_index=0,
        slot_id="minute:{}".format(_time(close)),
        close_time=_time(close),
        batch_id=batch_id,
        readiness=readiness,
        tape_file_id=_TAPE_FILE_ID,
        tape_record_id="alpha003-record-0001",
        tape_record_index=1,
        members=members,
    )


def _key(receipt):
    return ExecutionDecisionKey(
        account_scope=_ACCOUNT,
        strategy_scope=_STRATEGY,
        logical_run_id=_RUN,
        cohort_id=receipt.cohort_id,
        close_time=receipt.close_time,
        decision_kind=receipt.source_kind,
    )


def _batch(receipt):
    close = datetime.fromisoformat(receipt.close_time.replace("Z", "+00:00"))
    return LiveCohortBatch(
        batch_id=receipt.batch_id,
        cohort_id=receipt.cohort_id,
        calendar_id=receipt.calendar_id,
        calendar_version=receipt.calendar_version,
        epoch_id=receipt.epoch_id,
        slot_index=receipt.slot_index,
        close_time=close,
        available_at=close + timedelta(seconds=2),
    )


def _facts_87(receipt, close):
    snapshot_id = "alpha003-87-target-snapshot-v1"
    account_fingerprint = "c" * 64
    available_at = close + timedelta(seconds=4)
    account = FactorExecutionAccountFacts(
        account_scope=_ACCOUNT,
        snapshot_id=snapshot_id,
        available_at=available_at,
        route_permitted=True,
        available_margin=Decimal("1000000"),
        used_margin=Decimal("1000"),
        current_notional=Decimal("2500"),
        current_worst_case_loss=Decimal("250"),
        account_fingerprint=account_fingerprint,
        connection_generation=1,
        trading_day="20261024",
    )
    quotes = tuple(
        FactorExecutionQuoteFacts(
            instrument="instrument-{:03d}".format(index),
            exchange="DCE",
            source="ctp-query",
            source_ref="quote:{}:instrument-{:03d}".format(member.member_id, index),
            metadata_snapshot_id=snapshot_id,
            generation=1,
            sequence=index + 1,
            trading_day="20261024",
            event_time=close + timedelta(seconds=2),
            available_at=close + timedelta(seconds=3),
            bid=Decimal("100.0") + Decimal(index) / Decimal("100"),
            ask=Decimal("100.2") + Decimal(index) / Decimal("100"),
            bid_size=Decimal("10"),
            ask_size=Decimal("12"),
            tick_size=Decimal("0.2"),
            lower_limit=Decimal("80"),
            upper_limit=Decimal("120"),
            quality="GOOD",
        )
        for index, member in enumerate(receipt.members)
    )
    query_started = close + timedelta(seconds=1)
    query_completed = close + timedelta(seconds=3)
    base_queries = tuple(
        FactorExecutionQueryFact(
            family=family,
            request_type=family,
            request_id=index + 1,
            connection_generation=1,
            account_fingerprint=account_fingerprint,
            trading_day="20261024",
            started_at=query_started,
            completed_at=query_completed,
            source_owned=True,
            query_complete=True,
            scope_complete=True,
            row_count=_MEMBER_COUNT,
        )
        for index, family in enumerate(
            (
                "account_result",
                "orders_result",
                "trades_result",
                "instruments_result",
                "positions_result",
            )
        )
    )
    target_queries = tuple(
        FactorExecutionQueryFact(
            family="instrument_margin_rate_result",
            request_type="instrument_margin_rate_result",
            request_id=_MEMBER_COUNT + index + 1,
            connection_generation=1,
            account_fingerprint=account_fingerprint,
            trading_day="20261024",
            started_at=query_started,
            completed_at=query_completed,
            source_owned=True,
            query_complete=True,
            scope_complete=True,
            row_count=1,
            target_id=member.member_id,
        )
        for index, member in enumerate(receipt.members)
    )
    facts = FactorExecutionFacts(
        account_scope=_ACCOUNT,
        strategy_scope=_STRATEGY,
        snapshot_id=snapshot_id,
        available_at=available_at,
        account=account,
        positions=(),
        working_orders=(),
        terminal_orders=(),
        trade_observations=(),
        quotes=quotes,
        instruments=(),
        route_eligibilities=(),
        query_provenance=base_queries + target_queries,
        blockers=(),
        target_ids=tuple(member.member_id for member in receipt.members),
    )
    assert len(facts.quotes) == _MEMBER_COUNT
    assert len(facts.query_provenance) == _MEMBER_COUNT + 5
    return facts


def _grid_payload(receipt):
    close = datetime.fromisoformat(receipt.close_time.replace("Z", "+00:00"))
    target = alpha003._target_decision(
        mode="native",
        cohort_id=receipt.cohort_id,
        batch_id=receipt.batch_id,
        close=close,
        epoch=receipt.epoch_id,
    )
    planning = alpha003._planning_input(target, close=close)
    plan = alpha003._STRATEGY.plan_alpha003_orders(planning)
    assert plan.status == "READY" and len(plan.actions) == 2
    economics_owner = SimpleNamespace(_risk_policy=planning.risk_policy)
    economics_owner._risk_policy_payload = (
        lambda: alpha003._STRATEGY.Alpha003TargetStrategy._risk_policy_payload(
            economics_owner
        )
    )
    intent_keys, intent_economics = alpha003._STRATEGY.Alpha003TargetStrategy._order_intents(
        economics_owner,
        plan,
        SimpleNamespace(batch_id=receipt.batch_id),
    )
    assert len(intent_keys) == len(intent_economics) == 2
    facts = _facts_87(receipt, close)
    payload = {
        "plan_id": "alpha003",
        "factor_source_sha256": target.source_sha256,
        "snapshot_id": facts.snapshot_id,
        "execution_evidence": alpha003._STRATEGY._live_execution_evidence_payload(facts),
        "batch_id": receipt.batch_id,
        "epoch_id": receipt.epoch_id,
        "signal_batch_id": target.batch_id,
        "decision_tape_status": "DURABLE",
        "decision_tape_error": None,
        "intent_economics": intent_economics,
        "proposed_actions": tuple(
            alpha003._STRATEGY._planned_action_payload(action) for action in plan.actions
        ),
        "dispatch_suppressed": False,
        "plan_status": plan.status,
        "plan_reason": plan.reason,
        "decision_tape_file_id": receipt.tape_file_id,
        "decision_tape_record_id": receipt.tape_record_id,
        "decision_tape_record_index": receipt.tape_record_index,
        "decision_tape_batch_id": receipt.batch_id,
    }
    assert len(payload["execution_evidence"]["quotes"]) == _MEMBER_COUNT
    assert len(payload["execution_evidence"]["query_provenance"]) == _MEMBER_COUNT + 5
    assert len(intent_keys) <= planning.risk_policy.max_order_intents_per_grid == 2
    assert planning.risk_policy.max_order_intents_per_run == 20
    return payload, intent_keys


def _stored_payload_bytes(journal, decision_id):
    row = journal._connection.execute(
        """SELECT LENGTH(CAST(economic_payload_json AS BLOB))
           FROM execution_decisions WHERE decision_id=?""",
        (decision_id,),
    ).fetchone()
    assert row is not None and type(row[0]) is int
    return row[0]


def _canonical_bytes(payload):
    return len(_canonical_json(payload).encode("utf-8"))


def _thaw_json(value):
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw_json(item) for item in value]
    return value


def _expected_reference(head):
    receipt = head.receipt
    return ExecutionSourceHighWaterRef(
        account_scope=_ACCOUNT,
        strategy_scope=_STRATEGY,
        logical_run_id=_RUN,
        source_kind=receipt.source_kind,
        decision_id=head.decision_id,
        receipt_sha256=head.receipt_sha256,
        cohort_id=receipt.cohort_id,
        calendar_id=receipt.calendar_id,
        calendar_version=receipt.calendar_version,
        calendar_fingerprint=receipt.calendar_fingerprint,
        epoch_id=receipt.epoch_id,
        slot_index=receipt.slot_index,
        slot_id=receipt.slot_id,
        close_time=receipt.close_time,
        batch_id=receipt.batch_id,
        tape_file_id=receipt.tape_file_id,
        tape_record_id=receipt.tape_record_id,
        tape_record_index=receipt.tape_record_index,
    )


def _record_grid(journal, receipt, payload, intent_keys, *, expected_used):
    return journal.record_grid_decision(
        _key(receipt),
        payload,
        intent_keys=intent_keys,
        epoch_id=str(receipt.epoch_id),
        batch_id=receipt.batch_id,
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
        max_order_intents_per_run=20,
        expected_run_order_intents_used=expected_used,
        remaining_exit_intent_reserve=0,
        source_receipt=receipt,
    )


def test_87_member_alpha003_grid_payload_is_measured_before_write_and_reopen(tmp_path):
    receipt = _receipt()
    assert receipt.source_kind == _source_kind()
    assert _key(receipt).decision_kind == receipt.source_kind
    economics, intent_keys = _grid_payload(receipt)
    assert len(intent_keys) == 2
    expected_payload = dict(economics)
    expected_payload["_execution_source_receipt"] = asdict(receipt)
    expected_payload["_journal_run_order_reservation"] = {
        "max_order_intents_per_run": 20,
        "remaining_exit_intent_reserve": 0,
    }
    expected_payload = json.loads(_canonical_json(expected_payload))
    expected_bytes = _canonical_bytes(expected_payload)
    assert expected_bytes == _EXPECTED_GRID_PAYLOAD_BYTES, (
        "87-member canonical GRID payload bytes={}".format(expected_bytes)
    )
    assert 0 < expected_bytes <= _BOUNDED_OVERRIDE_CAP

    path = tmp_path / "alpha003-grid-size.sqlite3"
    journal = ExecutionDecisionJournal(path)
    default_cap = journal.max_payload_bytes
    assert default_cap == _DEFAULT_CAP
    used_cap = default_cap
    try:
        try:
            result = _record_grid(journal, receipt, economics, intent_keys, expected_used=0)
        except ExecutionDecisionJournalError as error:
            assert error.code == "JOURNAL_PAYLOAD_TOO_LARGE"
            assert expected_bytes > default_cap
            journal.close()
            used_cap = _BOUNDED_OVERRIDE_CAP
            journal = ExecutionDecisionJournal(path, max_payload_bytes=used_cap)
            result = _record_grid(journal, receipt, economics, intent_keys, expected_used=0)
        assert result.is_new_grid is True
        assert result.source_anchor == result.decision
        assert result.cursor is not None
        serialized_bytes = _stored_payload_bytes(journal, result.decision.decision_id)
        assert serialized_bytes == expected_bytes, (
            "stored GRID payload bytes={} canonical bytes={}".format(
                serialized_bytes, expected_bytes
            )
        )
        assert serialized_bytes <= used_cap
        if used_cap == default_cap:
            assert serialized_bytes <= _DEFAULT_CAP
        else:
            assert serialized_bytes > _DEFAULT_CAP
            assert used_cap == _BOUNDED_OVERRIDE_CAP
        saved = journal.decision_for_key(_key(receipt))
        assert saved is not None
        assert saved.economic_payload["snapshot_id"] == "alpha003-87-target-snapshot-v1"
        assert len(saved.economic_payload["execution_evidence"]["quotes"]) == _MEMBER_COUNT
        assert len(saved.economic_payload["execution_evidence"]["query_provenance"]) == 92
        assert saved.economic_payload["decision_tape_file_id"] == receipt.tape_file_id
        assert saved.economic_payload["decision_tape_record_id"] == receipt.tape_record_id
        assert saved.economic_payload["decision_tape_record_index"] == receipt.tape_record_index
        assert saved.economic_payload["decision_tape_batch_id"] == receipt.batch_id
        assert len(saved.economic_payload["proposed_actions"]) == 2
        assert saved.intent_keys == intent_keys
        assert journal.run_order_count(_ACCOUNT, _STRATEGY, _RUN) == 2
        head = journal.source_highwater(_ACCOUNT, _STRATEGY, _RUN, _source_kind())
        assert head is not None and head.anchor_kind == "GRID"
        assert head.receipt == receipt
        assert head.reference == _expected_reference(head)
        assert len(head.receipt.members) == _MEMBER_COUNT
    finally:
        journal.close()

    reopened = ExecutionDecisionJournal(path, max_payload_bytes=used_cap)
    try:
        persisted = reopened.decision_for_key(_key(receipt))
        assert persisted is not None
        assert _thaw_json(persisted.economic_payload) == _thaw_json(saved.economic_payload)
        assert _thaw_json(persisted.economic_payload) == _thaw_json(expected_payload)
        assert _stored_payload_bytes(reopened, persisted.decision_id) == expected_bytes
        assert _canonical_bytes(persisted.economic_payload) == expected_bytes
        recovered_head = reopened.source_highwater(
            _ACCOUNT, _STRATEGY, _RUN, _source_kind()
        )
        assert recovered_head == head
        assert recovered_head.receipt == receipt
        assert recovered_head.reference == head.reference
        replay = _record_grid(
            reopened, receipt, economics, intent_keys, expected_used=2
        )
        assert replay.is_new_grid is False
        assert replay.decision == persisted
        assert reopened.source_highwater(
            _ACCOUNT, _STRATEGY, _RUN, _source_kind()
        ) == head
    finally:
        reopened.close()


def test_87_member_source_only_payload_fits_default_cap_after_reopen(tmp_path):
    receipt = _receipt(source_role="history", readiness="WARMUP")
    path = tmp_path / "alpha003-source-only-size.sqlite3"

    class NeverCalledProvider:
        def __init__(self, *args, **kwargs):
            del args, kwargs
            raise AssertionError("source-only anchor must not create a provider")

    store = RegisteredSimStore(allow_writes=False, api_cls=NeverCalledProvider)
    broker = bt.brokers.BtApiBroker(
        store=store,
        cash=10_000,
        validation_enabled=False,
        cash_check_enabled=False,
    )
    journal = ExecutionDecisionJournal(path)
    coordinator = FactorExecutionCoordinator(
        broker,
        journal,
        account_scope=_ACCOUNT,
        strategy_scope=_STRATEGY,
        logical_run_id=_RUN,
        max_order_intents_per_grid=2,
        max_order_intents_per_run=20,
    )
    expected_payload = {
        "_execution_source_receipt": asdict(receipt),
        "_execution_source_anchor_only": True,
    }
    expected_payload = json.loads(
        json.dumps(
            expected_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    )
    expected_bytes = _canonical_bytes(expected_payload)
    assert 0 < expected_bytes <= _DEFAULT_CAP
    assert journal.max_payload_bytes == _DEFAULT_CAP
    try:
        result = coordinator.record_source_receipt(
            key=_key(receipt), batch=_batch(receipt), source_receipt=receipt
        )
        assert result.source_anchor is not None
        assert result.source_anchor.intent_keys == ()
        assert result.source_anchor.economic_payload["_execution_source_anchor_only"] is True
        assert len(result.source_anchor.economic_payload["_execution_source_receipt"]["members"]) == 87
        serialized_bytes = _stored_payload_bytes(journal, result.source_anchor.decision_id)
        assert serialized_bytes == expected_bytes <= journal.max_payload_bytes
        assert _canonical_bytes(result.source_anchor.economic_payload) == expected_bytes
        head = journal.source_highwater(_ACCOUNT, _STRATEGY, _RUN, _source_kind())
        assert head is not None and head.anchor_kind == "SOURCE_ONLY"
        assert head.receipt == receipt
        assert head.reference == _expected_reference(head)
    finally:
        journal.close()

    reopened = ExecutionDecisionJournal(path)
    try:
        saved = reopened.decision_for_key(_key(receipt))
        assert saved is not None
        assert _thaw_json(saved.economic_payload) == _thaw_json(expected_payload)
        assert _stored_payload_bytes(reopened, saved.decision_id) == expected_bytes
        assert _canonical_bytes(saved.economic_payload) == expected_bytes
        recovered_head = reopened.source_highwater(
            _ACCOUNT, _STRATEGY, _RUN, _source_kind()
        )
        assert recovered_head is not None and recovered_head.anchor_kind == "SOURCE_ONLY"
        assert recovered_head.receipt == receipt
        assert recovered_head.reference == _expected_reference(recovered_head)
    finally:
        reopened.close()
