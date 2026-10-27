"""Focused integration tests for 028 history source/HWM persistence.

They use the real journal, coordinator, calendar and saved-history runner with
fixed source receipts; no provider API or order dispatch is involved.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import backtrader as bt

from backtrader.feeds.futures_main_contract import ProductKey
from backtrader.feeds.futures_sessions import (
    CommonMinuteGrid,
    PlannedCommonMinute,
    SessionSlotEvidence,
)
from backtrader.research.live_cohort import LiveCohortBatch, LiveCohortCalendar
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionKey,
    ExecutionSourceMemberReceipt,
    ExecutionSourceHighWaterRef,
    ExecutionSourceRestartMarker,
    ExecutionSourceReceipt,
)
from backtrader.stores.factor_execution import FactorExecutionCoordinator, FactorExecutionError
from backtrader.stores.registered_sim import RegisteredSimStore
from tests.integration import test_factor_decision_replay_economics as alpha003


_UTC = timezone.utc
_BASE = datetime(2026, 10, 24, 1, 0, tzinfo=_UTC)
_ACCOUNT = alpha003.ACCOUNT_SCOPE
_STRATEGY = alpha003.STRATEGY_SCOPE
_RUN = alpha003.RUN_ID
_CACHED_SOURCE_KIND = None
_CALENDAR_ID = "alpha003-calendar-v1"
_CALENDAR_VERSION = "rules-v1"
_COHORT_ID = "alpha003:alpha003-calendar-v1:1"
_MEMBER_COUNT = 87
_TAPE_FILE_ID = "alpha003-decision-tape-fixture-v1"
_HISTORY_COHORT_ID = "alpha003:alpha003-calendar-v1:1"
_CURRENT_COHORT_ID = "alpha003:alpha003-calendar-v1:2"
_HISTORY_TARGETS = tuple("DCE.P{:03d}".format(index) for index in range(_MEMBER_COUNT))
_HISTORY_PRODUCTS = tuple(
    ProductKey("DCE", "P{:03d}".format(index)) for index in range(_MEMBER_COUNT)
)
_HISTORY_INSTRUMENTS = {
    target: "instrument-{:03d}".format(index)
    for index, target in enumerate(_HISTORY_TARGETS)
}
_HISTORY_RUNNER = None


def _time(value: datetime) -> str:
    return value.astimezone(_UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _receipt(
    slot_index: int,
    *,
    source_role: str,
    readiness: str,
    predecessor=None,
) -> ExecutionSourceReceipt:
    close = _BASE + timedelta(minutes=slot_index)
    bucket_start = close - timedelta(minutes=1)
    available_at = close + timedelta(seconds=2)
    batch_id = "{}:{}:{}:{}:{}".format(
        _COHORT_ID, _CALENDAR_ID, 1, _CALENDAR_VERSION, slot_index
    )
    members = tuple(
        ExecutionSourceMemberReceipt(
            member_id="target-{:03d}".format(index),
            source_ref="ctp-live:target-{:03d}:instrument-{:03d}".format(index, index),
            source_role=source_role,
            connection_generation="{}-generation-1".format(source_role),
            feed_sequence=slot_index + 1,
            bar_id="bar-1-{:03d}-{:03d}".format(slot_index, index),
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
            event_source="ctp-history" if source_role == "history" else "ctp-live",
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
        slot_index=slot_index,
        slot_id="minute:{}".format(_time(close)),
        close_time=_time(close),
        batch_id=batch_id,
        readiness=readiness,
        tape_file_id=_TAPE_FILE_ID,
        tape_record_id="alpha003-record-{:04d}".format(slot_index + 1),
        tape_record_index=slot_index + 1,
        members=members,
        predecessor=predecessor,
    )


def _key(receipt: ExecutionSourceReceipt) -> ExecutionDecisionKey:
    return ExecutionDecisionKey(
        account_scope=_ACCOUNT,
        strategy_scope=_STRATEGY,
        logical_run_id=_RUN,
        cohort_id=receipt.cohort_id,
        close_time=receipt.close_time,
        decision_kind=receipt.source_kind,
    )


def _batch(receipt: ExecutionSourceReceipt) -> LiveCohortBatch:
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


def _coordinator(path):
    class NeverCalledProvider:
        def __init__(self, *args, **kwargs):
            del args, kwargs
            raise AssertionError("source-only history recording must not create a provider")

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
    return journal, coordinator


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


def _load_runner():
    global _HISTORY_RUNNER
    if _HISTORY_RUNNER is not None:
        return _HISTORY_RUNNER
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
            "i51_history_runner_source_test_module", runner_path
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
    _HISTORY_RUNNER = runner
    return runner


def _source_kind():
    global _CACHED_SOURCE_KIND
    if _CACHED_SOURCE_KIND is None:
        _CACHED_SOURCE_KIND = _load_runner()._live_source_lineage_kind_from_days(
            {"DCE": date(2026, 10, 24)}
        )
    return _CACHED_SOURCE_KIND


def _seal_tape_record(runner, row):
    sealed = dict(row)
    sealed["record_id"] = hashlib.sha256(
        runner._canonical_json_bytes(sealed).rstrip(b"\n")
    ).hexdigest()
    return sealed


def _history_grid(*, decision_at, omit_close=None, changed_session_close=None):
    day = date(2026, 10, 24)
    minutes = []
    for slot_index in range(12):
        close = _BASE + timedelta(minutes=slot_index)
        if omit_close is not None and close == omit_close:
            continue
        session_id = "changed-session" if close == changed_session_close else "regular"
        members = tuple(
            SessionSlotEvidence(
                product=product,
                trading_day=day,
                session_date=day,
                action_day=day,
                session_id=session_id,
            )
            for product in _HISTORY_PRODUCTS
        )
        minutes.append(PlannedCommonMinute(close_time=close, members=members))
    return CommonMinuteGrid(
        status="READY",
        decision_at=decision_at,
        target_products=_HISTORY_PRODUCTS,
        product_trading_days=tuple((product, (day,)) for product in _HISTORY_PRODUCTS),
        calendar_hashes=(("DCE", "d" * 64),),
        minutes=tuple(minutes),
    )


def _history_plan(grid):
    product_by_target = dict(zip(_HISTORY_TARGETS, _HISTORY_PRODUCTS))
    routes = {
        product: _HISTORY_INSTRUMENTS[target]
        for target, product in product_by_target.items()
    }
    return {
        "grid": grid,
        "targets": _HISTORY_TARGETS,
        "authorized_targets": _HISTORY_TARGETS,
        "routes": routes,
        "product_by_target": product_by_target,
        "selection_source": "bundle",
        "source_snapshot_id": "selection-snapshot-v1",
    }


def _restart_identity(runner, config, config_path, plan, *, epoch_id):
    config_at_epoch = dict(config)
    config_at_epoch["cohort"] = dict(config["cohort"], epoch_id=epoch_id)
    return runner._live_restart_identity(
        config_at_epoch,
        config_path,
        plan,
        factor_mode="native",
        direction=1,
        simnow_profile={"verified": None, "environment": None, "profile": None},
    )


def _history_config(tape_path, journal_path):
    return {
        "inputs": {"history_decision_tape": str(tape_path)},
        "selection": {"source": "bundle", "daily_bundles": False},
        "output": {
            "decision_tape_path": str(tape_path.parent / "new-decision-tape.jsonl"),
            "decision_tape_max_bytes": 5_000_000,
        },
        "live": {
            "account_scope": _ACCOUNT,
            "strategy_scope": _STRATEGY,
            "logical_run_id": _RUN,
            "journal_path": str(journal_path),
        },
        "risk": {
            "policy_id": "alpha003-history-fixture-v1",
            "max_hold_eligible_bars": 12,
            "preclose_grace_seconds": 60,
            "run_end_policy": "CLOSE_ALL",
            "quote_max_age_seconds": "5",
            "max_state_age_seconds": "30",
            "max_notional_per_position": "3000",
            "max_total_notional": "5000",
            "max_margin_per_position": "250",
            "max_total_margin": "500",
            "max_loss_per_position": "20",
            "max_total_loss": "40",
            "round_trip_fee_upper_bound_per_contract": "1",
            "stop_loss_ticks": 2,
            "max_order_intents_per_grid": 2,
            "max_order_intents_per_run": 20,
        },
        "factor": {"preheat_bars": 3},
        "cohort": {
            "calendar_id": _CALENDAR_ID,
            "calendar_version": _CALENDAR_VERSION,
            "epoch_id": 2,
            "timezone_id": "Asia/Shanghai",
            "clock_domain_id": "synthetic-ctp-clock",
            "session_semantics": "explicit-session-slots",
        },
    }


def _tape_member(slot_index, target_index, target):
    close = _BASE + timedelta(minutes=slot_index)
    bucket_start = close - timedelta(minutes=1)
    instrument = _HISTORY_INSTRUMENTS[target]
    return {
        "cohort_id": _HISTORY_COHORT_ID,
        "calendar_id": _CALENDAR_ID,
        "epoch_id": 1,
        "slot_index": slot_index,
        "slot_id": "minute:{}".format(close.isoformat()),
        "instrument": instrument,
        "source_ref": "ctp-live:{}:{}".format(target, instrument),
        "source_role": "live",
        "connection_generation": "old-generation-1",
        "feed_sequence": slot_index + 1,
        "bucket_start": _time(bucket_start),
        "close_time": _time(close),
        "available_at": _time(close),
        # DecisionTapeWriter stores the CTP wire day in canonical ISO form.
        "trading_day": "2026-10-24",
        "session_segment": "regular",
        "timezone_id": "Asia/Shanghai",
        "clock_domain_id": "synthetic-ctp-clock",
        "bar_id": "old-bar-{:03d}-{:03d}".format(slot_index, target_index),
        "complete": True,
        "quality": "GOOD",
        "present": True,
        "quality_flags": [],
        "missing_fields": [],
        "rules_hash": "b" * 64,
        "event_source": "ctp-live",
        "received_monotonic_ns": None,
        "raw_values": {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 10.0,
            "openinterest": 1.0,
        },
    }


def _history_tape_row(runner, slot_index, file_id):
    close = _BASE + timedelta(minutes=slot_index)
    batch_id = "{}:{}:{}:{}:{}".format(
        _HISTORY_COHORT_ID, _CALENDAR_ID, 1, _CALENDAR_VERSION, slot_index
    )
    row = {
        "schema": runner.DECISION_TAPE_SCHEMA,
        "record_type": "DECISION",
        "file_id": file_id,
        "record_index": slot_index + 1,
        "batch_id": batch_id,
        "cohort_id": _HISTORY_COHORT_ID,
        "calendar_id": _CALENDAR_ID,
        "calendar_version": _CALENDAR_VERSION,
        "epoch_id": 1,
        "slot_index": slot_index,
        "close_time": _time(close),
        "available_at": _time(close),
        "readiness": "LIVE_READY",
        "readiness_reasons": [],
        "calendar_fingerprint": "a" * 64,
        "slot_id": "minute:{}".format(close.isoformat()),
        "members": {
            target: _tape_member(slot_index, index, target)
            for index, target in enumerate(_HISTORY_TARGETS)
        },
        "factors": {"plan_id": "alpha003", "factors": []},
        "target_decision": {"status": "TARGETS_READY", "targets": []},
        "order_plan": {"status": "READY", "reason": None, "actions": []},
    }
    return _seal_tape_record(runner, row)


def _write_history_tape(runner, path, *, identity):
    file_id = "alpha003-history-tape-v1"
    header = {
        "schema": runner.DECISION_TAPE_SCHEMA,
        "record_type": "HEADER",
        "file_id": file_id,
        "mode": "live",
        "factor_mode": "native",
        "direction": 1,
        "targets": list(_HISTORY_TARGETS),
        "calendar_id": _CALENDAR_ID,
        "grid_sha256": None,
        "source_snapshot_id": "selection-snapshot-v1",
        "calendar_fingerprint": "a" * 64,
        "restart_identity": identity,
    }
    records = [_seal_tape_record(runner, header)]
    records.extend(
        _history_tape_row(runner, slot_index, file_id) for slot_index in range(5)
    )
    path.write_bytes(b"".join(runner._canonical_json_bytes(row) for row in records))
    return records, identity


def _receipt_from_tape_row(row, predecessor=None):
    member_rows = row["members"]
    members = tuple(
        ExecutionSourceMemberReceipt(
            member_id=target,
            source_ref=member_rows[target]["source_ref"],
            source_role=member_rows[target]["source_role"],
            connection_generation=member_rows[target]["connection_generation"],
            feed_sequence=member_rows[target]["feed_sequence"],
            bar_id=member_rows[target]["bar_id"],
            bucket_start=member_rows[target]["bucket_start"],
            close_time=member_rows[target]["close_time"],
            available_at=member_rows[target]["available_at"],
            # The source receipt binds the original CTP envelope day, which is
            # compact even though the persisted tape row is canonical ISO.
            trading_day=date.fromisoformat(member_rows[target]["trading_day"]).strftime(
                "%Y%m%d"
            ),
            session_segment=member_rows[target]["session_segment"],
            timezone_id=member_rows[target]["timezone_id"],
            clock_domain_id=member_rows[target]["clock_domain_id"],
            complete=member_rows[target]["complete"],
            quality=member_rows[target]["quality"],
            present=member_rows[target]["present"],
            missing_fields=tuple(member_rows[target]["missing_fields"]),
            quality_flags=tuple(member_rows[target]["quality_flags"]),
            event_source=member_rows[target]["event_source"],
            received_monotonic_ns=member_rows[target]["received_monotonic_ns"],
            rules_hash=member_rows[target]["rules_hash"],
        )
        for target in sorted(member_rows)
    )
    return ExecutionSourceReceipt(
        source_kind=_source_kind(),
        cohort_id=row["cohort_id"],
        calendar_id=row["calendar_id"],
        calendar_version=row["calendar_version"],
        calendar_fingerprint=row["calendar_fingerprint"],
        epoch_id=row["epoch_id"],
        slot_index=row["slot_index"],
        slot_id=row["slot_id"],
        close_time=row["close_time"],
        batch_id=row["batch_id"],
        readiness=row["readiness"],
        tape_file_id=row["file_id"],
        tape_record_id=row["record_id"],
        tape_record_index=row["record_index"],
        members=members,
        predecessor=predecessor,
    )


def _seed_history_journal(
    journal, coordinator, records, *, record_count=None, wrong_tail_ref=False
):
    rows = records[1:]
    if record_count is not None:
        rows = rows[:record_count]
    predecessor = None
    for index, row in enumerate(rows):
        receipt = _receipt_from_tape_row(row, predecessor=predecessor)
        if wrong_tail_ref and index == len(rows) - 1:
            receipt = replace(receipt, tape_record_id="not-the-tape-record-id")
        if coordinator is None:
            result = journal.record_grid_decision(
                _key(receipt),
                {},
                intent_keys=(),
                epoch_id=str(receipt.epoch_id),
                batch_id=receipt.batch_id,
                eligible=False,
                complete=False,
                live_ready=False,
                inputs_complete=False,
                source_receipt=receipt,
            )
        else:
            result = coordinator.record_source_receipt(
                key=_key(receipt), batch=_batch(receipt), source_receipt=receipt
            )
        assert result.source_anchor is not None
        assert result.source_anchor.intent_keys == ()
        head = journal.source_highwater(_ACCOUNT, _STRATEGY, _RUN, _source_kind())
        assert head is not None and head.receipt == receipt
        predecessor = head.reference
    return predecessor


def _loader_inputs(tmp_path, *, decision_at, omit_close=None, changed_session_close=None):
    runner = _load_runner()
    tape_path = tmp_path / "history.jsonl"
    old_grid = _history_grid(decision_at=_BASE - timedelta(hours=1))
    current_grid = _history_grid(
        decision_at=decision_at,
        omit_close=omit_close,
        changed_session_close=changed_session_close,
    )
    plan = _history_plan(current_grid)
    config = _history_config(tape_path, tmp_path / "journal.sqlite3")
    config_path = tmp_path / "config.yaml"
    old_identity = _restart_identity(
        runner, config, config_path, _history_plan(old_grid), epoch_id=1
    )
    restart_identity = _restart_identity(runner, config, config_path, plan, epoch_id=2)
    records, _old_identity = _write_history_tape(runner, tape_path, identity=old_identity)
    return runner, tape_path, records, old_grid, current_grid, plan, config, restart_identity


def _load_saved(runner, tape_path, plan, config, restart_identity, journal, *, now):
    return runner._load_saved_live_history(
        config,
        tape_path.parent / "config.yaml",
        plan,
        restart_identity=restart_identity,
        now=now,
        journal=journal,
        scopes={
            "account_scope": _ACCOUNT,
            "strategy_scope": _STRATEGY,
            "logical_run_id": _RUN,
        },
        source_kind=_source_kind(),
    )


def _seed_restarted_history_and_live(
    runner, journal, coordinator, saved, calendar, *, tape_file_id, gap_fingerprint
):
    previous = saved["source_highwater"].reference
    prior_members = saved["source_highwater"].receipt.members
    restarted_history = []
    for slot_index, slot in enumerate(calendar.slots[:3]):
        members = []
        for target_index, target in enumerate(_HISTORY_TARGETS):
            old_bar = saved["bars_by_target"][target][slot_index]
            old_member = prior_members[target_index]
            members.append(
                ExecutionSourceMemberReceipt(
                    member_id=target,
                    source_ref=old_member.source_ref,
                    source_role="history",
                    connection_generation=old_bar["connection_generation"],
                    feed_sequence=old_bar["bar_sequence"],
                    bar_id=old_bar["bar_id"],
                    bucket_start=_time(slot.bucket_start),
                    close_time=_time(slot.close_time),
                    available_at=_time(slot.close_time),
                    trading_day=slot.member_sessions[target].trading_day,
                    session_segment=slot.member_sessions[target].session_segment,
                    timezone_id="Asia/Shanghai",
                    clock_domain_id="synthetic-ctp-clock",
                    complete=True,
                    quality="GOOD",
                    present=True,
                    missing_fields=(),
                    quality_flags=tuple(old_bar["quality_flags"]),
                    event_source=old_bar["source"],
                    received_monotonic_ns=None,
                    rules_hash="b" * 64,
                )
            )
        receipt = ExecutionSourceReceipt(
            source_kind=_source_kind(),
            cohort_id=_CURRENT_COHORT_ID,
            calendar_id=_CALENDAR_ID,
            calendar_version=_CALENDAR_VERSION,
            calendar_fingerprint=calendar.fingerprint,
            epoch_id=2,
            slot_index=slot_index,
            slot_id=slot.slot_id,
            close_time=_time(slot.close_time),
            batch_id="{}:{}:{}:{}:{}".format(
                _CURRENT_COHORT_ID, _CALENDAR_ID, 2, _CALENDAR_VERSION, slot_index
            ),
            readiness="WARMUP",
            tape_file_id=tape_file_id,
            tape_record_id="{}-record-{:02d}".format(tape_file_id, slot_index + 1),
            tape_record_index=slot_index + 1,
            members=tuple(members),
            predecessor=previous,
            restart_marker=(
                ExecutionSourceRestartMarker(
                    prior_highwater=saved["source_highwater"].reference,
                    gap_fingerprint=gap_fingerprint,
                )
                if slot_index == 0
                else None
            ),
        )
        anchored = coordinator.record_source_receipt(
            key=_key(receipt), batch=_batch(receipt), source_receipt=receipt
        )
        assert anchored.source_anchor is not None
        assert anchored.source_anchor.economic_payload["_execution_source_anchor_only"] is True
        assert anchored.source_anchor.intent_keys == ()
        restarted_history.append(receipt)
        previous = journal.source_highwater(_ACCOUNT, _STRATEGY, _RUN, _source_kind()).reference

    live_slot = calendar.slots[3]
    live_members = tuple(
        ExecutionSourceMemberReceipt(
            member_id=target,
            source_ref="ctp-live:{}:{}".format(target, _HISTORY_INSTRUMENTS[target]),
            source_role="live",
            connection_generation="new-generation-1",
            feed_sequence=1,
            bar_id="new-live-{:03d}".format(index),
            bucket_start=_time(live_slot.bucket_start),
            close_time=_time(live_slot.close_time),
            available_at=_time(live_slot.close_time),
            trading_day=live_slot.member_sessions[target].trading_day,
            session_segment=live_slot.member_sessions[target].session_segment,
            timezone_id="Asia/Shanghai",
            clock_domain_id="synthetic-ctp-clock",
            complete=True,
            quality="GOOD",
            present=True,
            missing_fields=(),
            quality_flags=(),
            event_source="ctp-live",
            received_monotonic_ns=None,
            rules_hash="b" * 64,
        )
        for index, target in enumerate(_HISTORY_TARGETS)
    )
    live_receipt = ExecutionSourceReceipt(
        source_kind=_source_kind(),
        cohort_id=_CURRENT_COHORT_ID,
        calendar_id=_CALENDAR_ID,
        calendar_version=_CALENDAR_VERSION,
        calendar_fingerprint=calendar.fingerprint,
        epoch_id=2,
        slot_index=3,
        slot_id=live_slot.slot_id,
        close_time=_time(live_slot.close_time),
        batch_id="{}:{}:{}:{}:3".format(
            _CURRENT_COHORT_ID, _CALENDAR_ID, 2, _CALENDAR_VERSION
        ),
        readiness="LIVE_READY",
        tape_file_id=tape_file_id,
        tape_record_id="{}-record-04".format(tape_file_id),
        tape_record_index=4,
        members=live_members,
        predecessor=previous,
    )
    live_anchor = coordinator.record_source_receipt(
        key=_key(live_receipt), batch=_batch(live_receipt), source_receipt=live_receipt
    )
    assert live_anchor.source_anchor is not None
    assert live_anchor.source_anchor.intent_keys == ()
    return live_receipt, tuple(restarted_history), previous


def _expected_runner_error(runner, code, operation):
    try:
        operation()
    except runner.RunnerError as error:
        assert error.code == code
    else:
        raise AssertionError("expected RunnerError {}".format(code))


def test_tape_trading_day_keeps_ctp_and_persisted_date_boundaries_strict():
    runner = _load_runner()
    assert runner._tape_trading_day("20261024", "trading_day") == "2026-10-24"
    assert runner._tape_trading_day("2026-10-24", "trading_day") == "2026-10-24"
    assert runner._iso_date("2026-10-24", "saved history trading_day") == date(2026, 10, 24)
    _expected_runner_error(
        runner,
        "INPUT_DATE_INVALID",
        lambda: runner._iso_date("20261024", "saved history trading_day"),
    )
    _expected_runner_error(
        runner,
        "INPUT_DATE_INVALID",
        lambda: runner._iso_date("2026-02-30", "saved history trading_day"),
    )
    _expected_runner_error(
        runner,
        "INPUT_DATE_INVALID",
        lambda: runner._tape_trading_day("20260230", "trading_day"),
    )


def test_source_lineage_uses_only_sorted_full_exchange_day_map():
    runner = _load_runner()
    first_days = (
        SimpleNamespace(exchange_id="DCE", current_trading_day=date(2026, 10, 24)),
        SimpleNamespace(exchange_id="SHFE", current_trading_day=date(2026, 10, 24)),
    )
    same_days_different_routes_and_grid = tuple(reversed(first_days))
    first = {
        "manifest": SimpleNamespace(trading_days=first_days),
        "routes": {"DCE.P001": "p2601"},
        "grid": "first-grid",
    }
    same_day = {
        "manifest": SimpleNamespace(trading_days=same_days_different_routes_and_grid),
        "routes": {"DCE.P001": "p2605"},
        "grid": "changed-grid",
    }
    next_day = {
        "manifest": SimpleNamespace(
            trading_days=(
                SimpleNamespace(exchange_id="DCE", current_trading_day=date(2026, 10, 25)),
                SimpleNamespace(exchange_id="SHFE", current_trading_day=date(2026, 10, 25)),
            )
        ),
        "routes": first["routes"],
        "grid": first["grid"],
    }

    assert runner._live_source_lineage_kind(first) == runner._live_source_lineage_kind(
        same_day
    )
    assert runner._live_source_lineage_kind(first) != runner._live_source_lineage_kind(
        next_day
    )
    assert runner._live_source_lineage_kind(first).startswith(
        "ALPHA003_GRID:trading-day-map-v1:"
    )


def test_legacy_bare_source_highwater_is_explicitly_rejected(tmp_path):
    runner = _load_runner()
    journal, coordinator = _coordinator(tmp_path / "legacy-source-highwater.sqlite3")
    scopes = {
        "account_scope": _ACCOUNT,
        "strategy_scope": _STRATEGY,
        "logical_run_id": _RUN,
    }
    try:
        legacy = replace(
            _receipt(0, source_role="live", readiness="LIVE_READY"),
            source_kind="ALPHA003_GRID",
        )
        anchored = coordinator.record_source_receipt(
            key=_key(legacy), batch=_batch(legacy), source_receipt=legacy
        )
        assert anchored.source_anchor is not None
        before = journal.source_highwater(_ACCOUNT, _STRATEGY, _RUN, "ALPHA003_GRID")
        assert before is not None

        _expected_runner_error(
            runner,
            "LIVE_LEGACY_SOURCE_HIGHWATER_UNSUPPORTED",
            lambda: runner._reject_legacy_live_source_highwater(journal, scopes),
        )
        assert journal.source_highwater(_ACCOUNT, _STRATEGY, _RUN, "ALPHA003_GRID") == before
    finally:
        journal.close()


def test_source_only_hwm_replay_is_idempotent_and_cannot_upgrade_to_grid(tmp_path):
    journal, coordinator = _coordinator(tmp_path / "source-only-replay.sqlite3")
    try:
        first = _receipt(0, source_role="live", readiness="LIVE_READY")
        result = coordinator.record_source_receipt(
            key=_key(first), batch=_batch(first), source_receipt=first
        )
        assert result.source_anchor is not None
        assert result.source_anchor.economic_payload["_execution_source_anchor_only"] is True
        first_head = journal.source_highwater(_ACCOUNT, _STRATEGY, _RUN, _source_kind())
        assert first_head is not None and first_head.anchor_kind == "SOURCE_ONLY"

        replay = coordinator.record_source_receipt(
            key=_key(first), batch=_batch(first), source_receipt=first
        )
        assert replay.is_new_grid is False
        assert replay.source_anchor == result.source_anchor
        assert journal.source_highwater(_ACCOUNT, _STRATEGY, _RUN, _source_kind()) == first_head

        try:
            journal.record_grid_decision(
                _key(first),
                {"proposed_actions": ()},
                intent_keys=(),
                epoch_id=str(first.epoch_id),
                batch_id=first.batch_id,
                eligible=True,
                complete=True,
                live_ready=True,
                inputs_complete=True,
                source_receipt=first,
            )
        except Exception as error:
            assert getattr(error, "code", None) == "SOURCE_RECEIPT_ALREADY_ANCHORED"
        else:
            raise AssertionError("SOURCE_ONLY anchor upgraded to GRID")

        second = _receipt(
            1,
            source_role="live",
            readiness="LIVE_READY",
            predecessor=first_head.reference,
        )
        second_result = coordinator.record_source_receipt(
            key=_key(second), batch=_batch(second), source_receipt=second
        )
        assert second_result.source_anchor is not None
        second_head = journal.source_highwater(_ACCOUNT, _STRATEGY, _RUN, _source_kind())
        assert second_head is not None and second_head.receipt == second
        assert second.predecessor == first_head.reference
        assert second_head.reference == _expected_reference(second_head)
        assert journal.grid_cursor(_ACCOUNT, _STRATEGY, second.cohort_id) is None
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decision_intents"
        ).fetchone()[0] == 0
        assert coordinator.run_order_count() == 0
    finally:
        journal.close()


def test_source_receipt_rejects_each_coordinator_scope_drift_before_journal_write(tmp_path):
    journal, coordinator = _coordinator(tmp_path / "source-scope-drift.sqlite3")
    receipt = _receipt(0, source_role="history", readiness="WARMUP")
    original_key = _key(receipt)
    mismatches = (
        ("account_scope", "other-account"),
        ("strategy_scope", "other-strategy"),
        ("logical_run_id", "other-run"),
    )
    try:
        for field, value in mismatches:
            key = replace(original_key, **{field: value})
            try:
                coordinator.record_source_receipt(
                    key=key, batch=_batch(receipt), source_receipt=receipt
                )
            except FactorExecutionError as error:
                assert error.code == "DECISION_SCOPE_IDENTITY_MISMATCH"
            else:
                raise AssertionError("source receipt accepted mismatched {}".format(field))

            assert journal.source_highwater(_ACCOUNT, _STRATEGY, _RUN, _source_kind()) is None
            assert (
                journal.source_highwater(
                    key.account_scope,
                    key.strategy_scope,
                    key.logical_run_id,
                    _source_kind(),
                )
                is None
            )
            assert journal.grid_cursor(_ACCOUNT, _STRATEGY, receipt.cohort_id) is None
            assert journal.grid_cursor(
                key.account_scope, key.strategy_scope, receipt.cohort_id
            ) is None
            assert journal.decision_for_key(original_key) is None
            assert journal.decision_for_key(key) is None
            assert coordinator.run_order_count() == 0
    finally:
        journal.close()


def test_saved_history_gapless_and_restart_gap_continue_only_after_anchored_tail(tmp_path):
    runner, tape_path, records, old_grid, current_grid, plan, config, restart_identity = (
        _loader_inputs(tmp_path, decision_at=_BASE + timedelta(minutes=2))
    )
    assert runner._grid_semantics_sha256(old_grid) == runner._grid_semantics_sha256(current_grid)
    assert old_grid.decision_at != current_grid.decision_at
    assert all(minute.close_time.date() == _BASE.date() for minute in old_grid.minutes)
    old_plan = _history_plan(old_grid)
    assert tuple(minute.close_time for minute in old_grid.minutes) == tuple(
        minute.close_time for minute in current_grid.minutes
    )
    assert old_plan["targets"] == plan["targets"]
    assert old_plan["routes"] == plan["routes"]
    assert restart_identity["epoch_id"] == 2
    assert records[0]["restart_identity"]["epoch_id"] == 1
    assert records[1]["members"][_HISTORY_TARGETS[0]]["trading_day"] == "2026-10-24"
    assert _receipt_from_tape_row(records[1]).members[0].trading_day == "20261024"
    assert {
        key: value
        for key, value in records[0]["restart_identity"].items()
        if key != "epoch_id"
    } == {key: value for key, value in restart_identity.items() if key != "epoch_id"}
    journal, coordinator = _coordinator(tmp_path / "journal.sqlite3")
    try:
        _seed_history_journal(journal, coordinator, records)
        saved = _load_saved(
            runner,
            tape_path,
            plan,
            config,
            restart_identity,
            journal,
            now=_BASE + timedelta(minutes=6, seconds=30),
        )
        assert saved["record_count"] == 5 and saved["bar_count"] == 3
        assert saved["source_highwater"].reference == _expected_reference(
            journal.source_highwater(_ACCOUNT, _STRATEGY, _RUN, _source_kind())
        )
        assert saved["source_highwater"].receipt.tape_file_id == saved["source_file_id"]
        assert saved["source_highwater"].receipt.tape_record_id == records[-1]["record_id"]
        assert saved["source_highwater"].receipt.tape_record_index == 5
        assert saved["source_highwater"].receipt.calendar_fingerprint == records[-1][
            "calendar_fingerprint"
        ]
        assert tuple(
            item["bucket_end"] for item in saved["bars_by_target"][_HISTORY_TARGETS[0]]
        ) == tuple(_BASE + timedelta(minutes=index) for index in (2, 3, 4))
        assert tuple(
            item["bar_id"] for item in saved["bars_by_target"][_HISTORY_TARGETS[0]]
        ) == tuple("old-bar-{:03d}-000".format(index) for index in (2, 3, 4))
        assert len(saved["decision_anchors"]) == 3
        runner._verify_saved_history_decision_anchors(
            journal,
            {"account_scope": _ACCOUNT, "strategy_scope": _STRATEGY, "logical_run_id": _RUN},
            saved,
        )
        for anchor in saved["decision_anchors"]:
            key = ExecutionDecisionKey(
                account_scope=_ACCOUNT,
                strategy_scope=_STRATEGY,
                logical_run_id=_RUN,
                cohort_id=anchor["cohort_id"],
                close_time=_time(anchor["close_time"]),
                decision_kind=_source_kind(),
            )
            record = journal.decision_for_key(key)
            assert record is not None and record.intent_keys == ()
            assert record.economic_payload["_execution_source_anchor_only"] is True
            assert record.economic_payload["_execution_source_receipt"]["tape_record_id"] == anchor[
                "record_id"
            ]
            assert all(
                action.get("action") != "OPEN"
                for action in record.economic_payload.get("proposed_actions", ())
            )
        assert journal.grid_cursor(_ACCOUNT, _STRATEGY, _HISTORY_COHORT_ID) is None

        gap_startup = _BASE + timedelta(minutes=6, seconds=30)
        full_gap_calendar = runner._make_live_calendar(
            config,
            current_grid,
            begin_at=saved["first_bucket_start"],
            ctp_trading_days=True,
        )
        first_live = next(
            slot for slot in full_gap_calendar.slots if slot.bucket_start >= gap_startup
        )
        gap_calendar = LiveCohortCalendar.with_restart_gap(
            full_gap_calendar,
            startup_time_utc=gap_startup,
            journal_highwater=saved["calendar_highwater"],
            first_live_slot_id=first_live.slot_id,
        )
        gap = gap_calendar.restart_gap
        assert gap is not None
        assert gap.omitted_slot_count == 3
        assert gap.omitted_elapsed_slot_count == 2
        assert gap.omitted_partial_slot_id == "minute:{}".format(
            (_BASE + timedelta(minutes=7)).isoformat()
        )
        assert gap.first_live_slot_id == "minute:{}".format(
            (_BASE + timedelta(minutes=8)).isoformat()
        )
        assert tuple(slot.close_time for slot in gap_calendar.slots[:3]) == tuple(
            item["bucket_end"] for item in saved["bars_by_target"][_HISTORY_TARGETS[0]]
        )
        gap_live, gap_history, gap_history_head = _seed_restarted_history_and_live(
            runner,
            journal,
            coordinator,
            saved,
            gap_calendar,
            tape_file_id="alpha003-restarted-gap-tape-v1",
            gap_fingerprint=gap.fingerprint,
        )
        assert tuple(
            member.bar_id
            for receipt in gap_history
            for member in receipt.members
            if member.member_id == _HISTORY_TARGETS[0]
        ) == tuple(item["bar_id"] for item in saved["bars_by_target"][_HISTORY_TARGETS[0]])
        assert gap_history[0].predecessor == saved["source_highwater"].reference
        assert gap_history[0].restart_marker.prior_highwater == saved["source_highwater"].reference
        assert gap_history[0].restart_marker.gap_fingerprint == gap.fingerprint
        assert gap_history[0].calendar_fingerprint == gap_calendar.fingerprint
        assert gap_history[0].tape_file_id != saved["source_highwater"].receipt.tape_file_id
        gap_head = journal.source_highwater(_ACCOUNT, _STRATEGY, _RUN, _source_kind())
        assert gap_head is not None and gap_head.receipt == gap_live
        assert gap_live.predecessor is not None
        assert gap_live.predecessor == gap_history_head
        assert gap_live.restart_marker is None
        assert gap_live.calendar_fingerprint == gap_calendar.fingerprint
        assert gap_live.slot_index == gap.first_live_cohort_slot_index == 3
        assert gap_head.anchor_kind == "SOURCE_ONLY"
        assert coordinator.run_order_count() == 0

        # A fresh journal exercises the same planned slots with no elapsed or
        # partial omission: only the query's decision_at differs.
        gapless_path = tmp_path / "gapless-journal.sqlite3"
        journal.close()
        journal, coordinator = _coordinator(gapless_path)
        old_rows = records
        _seed_history_journal(journal, coordinator, old_rows)
        gapless_saved = _load_saved(
            runner,
            tape_path,
            plan,
            config,
            restart_identity,
            journal,
            now=_BASE + timedelta(minutes=4),
        )
        full_gapless_calendar = runner._make_live_calendar(
            config,
            current_grid,
            begin_at=gapless_saved["first_bucket_start"],
            ctp_trading_days=True,
        )
        gapless_startup = datetime.fromisoformat(
            gapless_saved["source_highwater"].receipt.close_time.replace("Z", "+00:00")
        )
        next_slot = next(
            slot for slot in full_gapless_calendar.slots if slot.bucket_start >= gapless_startup
        )
        highwater_position = next(
            index
            for index, slot in enumerate(full_gapless_calendar.slots)
            if slot.slot_id == gapless_saved["calendar_highwater"].slot_id
        )
        next_position = next(
            index
            for index, slot in enumerate(full_gapless_calendar.slots)
            if slot.slot_id == next_slot.slot_id
        )
        assert next_position == highwater_position + 1
        assert full_gapless_calendar.restart_gap is None
        assert tuple(slot.close_time for slot in full_gapless_calendar.slots[:3]) == tuple(
            item["bucket_end"] for item in gapless_saved["bars_by_target"][_HISTORY_TARGETS[0]]
        )
        gapless_live, gapless_history, gapless_history_head = _seed_restarted_history_and_live(
            runner,
            journal,
            coordinator,
            gapless_saved,
            full_gapless_calendar,
            tape_file_id="alpha003-restarted-gapless-tape-v1",
            gap_fingerprint=None,
        )
        assert tuple(
            member.bar_id
            for receipt in gapless_history
            for member in receipt.members
            if member.member_id == _HISTORY_TARGETS[0]
        ) == tuple(item["bar_id"] for item in gapless_saved["bars_by_target"][_HISTORY_TARGETS[0]])
        assert gapless_history[0].predecessor == gapless_saved["source_highwater"].reference
        assert gapless_history[0].restart_marker.prior_highwater == gapless_saved[
            "source_highwater"
        ].reference
        assert gapless_history[0].restart_marker.gap_fingerprint is None
        assert gapless_history[0].calendar_fingerprint == full_gapless_calendar.fingerprint
        gapless_head = journal.source_highwater(_ACCOUNT, _STRATEGY, _RUN, _source_kind())
        assert gapless_head is not None and gapless_head.receipt == gapless_live
        assert gapless_live.predecessor is not None
        assert gapless_live.predecessor == gapless_history_head
        assert gapless_live.slot_index == 3
        assert gapless_live.calendar_fingerprint == full_gapless_calendar.fingerprint
        assert gapless_head.anchor_kind == "SOURCE_ONLY"
        assert coordinator.run_order_count() == 0
    finally:
        journal.close()


def test_saved_history_rejects_missing_or_unanchored_source_highwater_before_engine_setup(tmp_path):
    runner, tape_path, records, _old_grid, _current_grid, plan, config, restart_identity = (
        _loader_inputs(tmp_path, decision_at=_BASE + timedelta(minutes=1))
    )
    # These failure paths run the real loader with only its journal dependency;
    # the Store/Broker/Cerebro composition is not constructed before rejection.
    empty_journal = ExecutionDecisionJournal(tmp_path / "empty-journal.sqlite3")
    try:
        _expected_runner_error(
            runner,
            "LIVE_HISTORY_SOURCE_HIGHWATER_MISSING",
            lambda: _load_saved(
                runner,
                tape_path,
                plan,
                config,
                restart_identity,
                empty_journal,
                now=_BASE + timedelta(minutes=4),
            ),
        )
    finally:
        empty_journal.close()

    partial_journal = ExecutionDecisionJournal(tmp_path / "partial-journal.sqlite3")
    try:
        _seed_history_journal(partial_journal, None, records, record_count=4)
        _expected_runner_error(
            runner,
            "LIVE_HISTORY_SOURCE_HIGHWATER_MISMATCH",
            lambda: _load_saved(
                runner,
                tape_path,
                plan,
                config,
                restart_identity,
                partial_journal,
                now=_BASE + timedelta(minutes=4),
            ),
        )
    finally:
        partial_journal.close()

    wrong_ref_journal = ExecutionDecisionJournal(tmp_path / "wrong-ref-journal.sqlite3")
    try:
        _seed_history_journal(
            wrong_ref_journal,
            None,
            records,
            wrong_tail_ref=True,
        )
        _expected_runner_error(
            runner,
            "LIVE_HISTORY_SOURCE_HIGHWATER_MISMATCH",
            lambda: _load_saved(
                runner,
                tape_path,
                plan,
                config,
                restart_identity,
                wrong_ref_journal,
                now=_BASE + timedelta(minutes=4),
            ),
        )
    finally:
        wrong_ref_journal.close()


def test_saved_history_rejects_same_calendar_old_slot_or_session_changes(tmp_path):
    runner, tape_path, records, _old_grid, _current_grid, plan, config, restart_identity = (
        _loader_inputs(tmp_path, decision_at=_BASE + timedelta(minutes=1))
    )
    for variant, grid in (
        (
            "missing-hwm-slot",
            _history_grid(
                decision_at=_BASE + timedelta(minutes=1),
                omit_close=_BASE + timedelta(minutes=4),
            ),
        ),
        (
            "changed-hwm-session",
            _history_grid(
                decision_at=_BASE + timedelta(minutes=1),
                changed_session_close=_BASE + timedelta(minutes=4),
            ),
        ),
    ):
        case_plan = _history_plan(grid)
        journal = ExecutionDecisionJournal(tmp_path / (variant + ".sqlite3"))
        try:
            _seed_history_journal(journal, None, records)
            expected_code = (
                "LIVE_HISTORY_OUTSIDE_CURRENT_GRID"
                if variant == "missing-hwm-slot"
                else "LIVE_HISTORY_MEMBER_INVALID"
            )
            _expected_runner_error(
                runner,
                expected_code,
                lambda: _load_saved(
                    runner,
                    tape_path,
                    case_plan,
                    config,
                    restart_identity,
                    journal,
                    now=_BASE + timedelta(minutes=4),
                ),
            )
        finally:
            journal.close()


def test_live_source_continuity_is_sticky_and_reports_no_rows_and_read_errors(tmp_path):
    runner = _load_runner()
    journal, coordinator = _coordinator(tmp_path / "continuity-journal.sqlite3")
    try:
        # This direct helper fixture deliberately exercises its documented
        # legacy-key default, so the persisted receipt must use that same key.
        receipt = replace(
            _receipt(0, source_role="live", readiness="LIVE_READY"),
            source_kind="ALPHA003_GRID",
        )
        anchored = coordinator.record_source_receipt(
            key=_key(receipt), batch=_batch(receipt), source_receipt=receipt
        )
        assert anchored.source_anchor is not None
        head = journal.source_highwater(
            _ACCOUNT, _STRATEGY, _RUN, receipt.source_kind
        )
        assert head is not None
        tape = type(
            "TapeProjection",
            (),
            {
                "file_id": receipt.tape_file_id,
                "calendar_fingerprint": receipt.calendar_fingerprint,
                "summary": lambda _self: {
                    "file_id": receipt.tape_file_id,
                    "record_count": 1,
                    "last_record_reference": {
                        "record_index": receipt.tape_record_index,
                        "record_id": receipt.tape_record_id,
                        "batch_id": receipt.batch_id,
                    },
                },
            },
        )()
        scopes = {
            "account_scope": _ACCOUNT,
            "strategy_scope": _STRATEGY,
            "logical_run_id": _RUN,
        }
        matched = runner._live_source_continuity_status(
            journal, scopes, tape, type("StrategyProjection", (), {})()
        )
        assert matched == {
            "status": "AVAILABLE",
            "available": True,
            "record_count": 1,
            "failure_count": 0,
            "first_error": None,
            "final_highwater_matches_tape": True,
        }

        prior_failure = type(
            "StrategyFailureProjection",
            (),
            {
                "source_continuity_failure_count": 1,
                "source_continuity_first_error": "SOURCE_RECEIPT_WRITE_FAILED",
            },
        )()
        sticky = runner._live_source_continuity_status(journal, scopes, tape, prior_failure)
        assert sticky["status"] == "UNAVAILABLE"
        assert sticky["available"] is False
        assert sticky["failure_count"] == 1
        assert sticky["first_error"] == "SOURCE_RECEIPT_WRITE_FAILED"
        assert sticky["final_highwater_matches_tape"] is True

        no_rows_tape = type(
            "EmptyTapeProjection",
            (),
            {
                "file_id": "unused-file",
                "calendar_fingerprint": "unused-fingerprint",
                "summary": lambda _self: {"record_count": 0, "last_record_reference": None},
            },
        )()
        no_rows = runner._live_source_continuity_status(None, scopes, no_rows_tape, None)
        assert no_rows["status"] == "NOT_APPLICABLE"
        assert no_rows["available"] is False
        assert no_rows["reason"] == "NO_ROWS"
        assert no_rows["failure_count"] == 0
        assert no_rows["first_error"] is None

        class ReadErrorJournal:
            closed = False

            def source_highwater(self, *_args):
                raise sqlite3.OperationalError("synthetic final read failure")

            def close(self):
                self.closed = True

        failed_read_journal = ReadErrorJournal()
        try:
            failed_read = runner._live_source_continuity_status(
                failed_read_journal, scopes, tape, None
            )
        finally:
            failed_read_journal.close()
        assert failed_read_journal.closed is True
        assert failed_read["status"] == "UNAVAILABLE"
        assert failed_read["failure_count"] == 1
        assert failed_read["first_error"] == "SOURCE_HIGHWATER_FINAL_READ_FAILED"
        assert failed_read["final_highwater_matches_tape"] is False
    finally:
        journal.close()
