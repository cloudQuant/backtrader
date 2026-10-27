"""Compose the 028 decision tape's byte limit with Alpha003's open-order gate."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tracemalloc
from types import MappingProxyType, SimpleNamespace

import pytest

from backtrader.research.live import LiveFactorOutput, LiveFactorOutputStatus
from backtrader.research.live_cohort import BarEnvelope, LiveDeliveryReceipt
from tests.integration import test_alpha003_decision_mode_replay as decision_mode
from tests.integration import test_factor_decision_replay_economics as economics


_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLE = _ROOT / "examples" / "unified" / "028_alpha003_simnow_minute"
_RUNNER_PATH = _EXAMPLE / "run.py"
if str(_EXAMPLE) not in sys.path:
    sys.path.insert(0, str(_EXAMPLE))
_RUNNER_SPEC = importlib.util.spec_from_file_location(
    "alpha003_decision_tape_capacity_runner", _RUNNER_PATH
)
assert _RUNNER_SPEC is not None and _RUNNER_SPEC.loader is not None
_RUNNER = importlib.util.module_from_spec(_RUNNER_SPEC)
sys.modules[_RUNNER_SPEC.name] = _RUNNER
_RUNNER_SPEC.loader.exec_module(_RUNNER)

_STRATEGY = economics._STRATEGY
_TARGETS = economics.TARGETS


def _complete_batch_snapshot(target_decision):
    batch, snapshot = economics._batch_and_snapshot(target_decision)
    receipts = {}
    values = {}
    for sequence, target in enumerate(_TARGETS, start=1):
        item = next(row for row in target_decision.targets if row.target_id == target)
        feed = object()
        source_ref = "capacity-source-" + target
        envelope = BarEnvelope(
            cohort_id=batch.cohort_id,
            calendar_id=batch.calendar_id,
            epoch_id=batch.epoch_id,
            slot_index=batch.slot_index,
            slot_id="slot-{:04d}".format(batch.slot_index),
            member_id=target,
            feed_ref=feed,
            instrument=economics.ROUTES[target][0],
            source_ref=source_ref,
            source_role="live",
            connection_generation=1,
            origin_partition=MappingProxyType(
                {
                    "schema": _RUNNER.SOURCE_ORIGIN_PARTITION_SCHEMA,
                    "cohort_id": batch.cohort_id,
                    "epoch_id": batch.epoch_id,
                    "member_id": target,
                    "source_ref": source_ref,
                    "source_role": "live",
                    "connection_generation": 1,
                }
            ),
            feed_sequence=sequence,
            bucket_start=batch.close_time - timedelta(minutes=1),
            close_time=batch.close_time,
            available_at=batch.available_at,
            trading_day="20261024",
            session_segment="day",
            timezone_id="Asia/Shanghai",
            clock_domain_id="capacity-clock",
            bar_id="capacity-bar-{}".format(target),
            complete=True,
            quality="GOOD",
            present=True,
            raw_values={
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 10.0,
                "openinterest": 0.0,
            },
            event_source="local_fixture",
            received_monotonic_ns=1000 + sequence,
        )
        receipts[target] = LiveDeliveryReceipt(
            cohort_id=batch.cohort_id,
            calendar_id=batch.calendar_id,
            epoch_id=batch.epoch_id,
            batch_id=batch.batch_id,
            slot_index=batch.slot_index,
            member_id=target,
            feed_ref=feed,
            source_ref=source_ref,
            envelope=envelope,
            feed_sequence=sequence,
            close_time=batch.close_time,
            available_at=batch.available_at,
            source_role="live",
            complete=True,
            quality="GOOD",
            present=True,
            raw_values=envelope.raw_values,
            line_values=envelope.raw_values,
        )
        values[target] = LiveFactorOutput(
            value=float(item.oriented_score),
            status=LiveFactorOutputStatus.OUTPUT_AVAILABLE,
            reason=None,
            present=True,
            complete=True,
            quality="GOOD",
            source_role="live",
            member_id=target,
            source_ref=source_ref,
            sequence=sequence,
            generation=1,
        )

    batch = replace(batch, members=receipts)
    factor = replace(
        snapshot.factors["alpha003"],
        values=MappingProxyType(values),
    )
    snapshot = replace(snapshot, factors=MappingProxyType({"alpha003": factor}))
    return batch, snapshot


def _mixed_plan(target_decision):
    action_type = _STRATEGY.Alpha003OrderAction
    open_action = action_type(
        action="SUBMIT",
        target_id="rb",
        instrument="rb2610",
        side="BUY",
        position_effect="OPEN",
        quantity=1,
        limit_price=economics.Decimal("100.1"),
        offset="open",
        reason="ALPHA003_TARGET",
        planned_stop_price=economics.Decimal("99.0"),
        exchange="SHFE",
        decision_available_at=target_decision.available_at,
        entry_grid_ordinal=5,
    )
    cancel_action = replace(
        open_action,
        action="CANCEL",
        reason="RUN_END_CANCEL_PENDING_OPEN",
        order_ref="remote-open-1",
        owner_intent_id="owner-open-1",
        broker_order_ref=1,
    )
    close_action = action_type(
        action="SUBMIT",
        target_id="i",
        instrument="i2610",
        side="SELL",
        position_effect="CLOSE",
        quantity=1,
        limit_price=economics.Decimal("99.9"),
        offset="close",
        reason="RISK_REDUCTION",
        owner_intent_id="owner-close-1",
        exchange="DCE",
        decision_available_at=target_decision.available_at,
    )
    return _STRATEGY.Alpha003OrderPlan(
        status="READY",
        reason=None,
        actions=(open_action, cancel_action, close_action),
        decision_batch_id=target_decision.batch_id,
        decision_available_at=target_decision.available_at,
        account_snapshot_id="capacity-account-snapshot",
    )


def _writer(path, *, max_bytes, calendar_id):
    return _RUNNER.DecisionTapeWriter(
        path,
        max_bytes,
        mode="live",
        factor_mode="native",
        direction=1,
        targets=_TARGETS,
        calendar_id=calendar_id,
        grid_sha256="a" * 64,
        source_snapshot_id="capacity-source-snapshot",
    )


@pytest.mark.integration
def test_actual_decision_tape_append_overflow_suppresses_open_dispatch(tmp_path):
    """A row-budget overflow preserves the valid prefix and blocks new exposure."""
    first_decision = economics._target_decision(
        mode="native", batch_id="batch-one", close=economics.CLOSE
    )
    second_decision = economics._target_decision(
        mode="native",
        batch_id="batch-two",
        close=economics.CLOSE + timedelta(minutes=1),
    )
    first_batch, first_snapshot = _complete_batch_snapshot(first_decision)
    second_batch, second_snapshot = _complete_batch_snapshot(second_decision)
    first_plan = _mixed_plan(first_decision)
    second_plan = replace(
        first_plan,
        decision_batch_id=second_decision.batch_id,
        decision_available_at=second_decision.available_at,
    )

    sizing_writer = _writer(
        tmp_path / "sizing.jsonl",
        max_bytes=1_000_000,
        calendar_id=first_batch.calendar_id,
    )
    assert (
        sizing_writer.record_decision(first_batch, first_snapshot, first_decision, first_plan)
        is True
    )
    prefix_bytes = sizing_writer.summary()["bytes"]
    assert sizing_writer.close()["failed"] is False

    tape_path = tmp_path / "decisions.jsonl"
    writer = _writer(tape_path, max_bytes=prefix_bytes, calendar_id=first_batch.calendar_id)
    assert writer.record_decision(first_batch, first_snapshot, first_decision, first_plan) is True
    assert writer.summary()["bytes"] == prefix_bytes
    accepted_prefix = tape_path.read_bytes()
    accepted_reference = writer.last_record_reference

    captured_overflow_codes = []
    actual_record_decision = writer.record_decision

    def capture_overflow(*args):
        try:
            return actual_record_decision(*args)
        except _RUNNER.RunnerError as error:
            captured_overflow_codes.append(error.code)
            raise

    # Observe the concrete writer error while leaving its implementation and
    # Strategy's error handling untouched.
    writer.record_decision = capture_overflow
    owner = object.__new__(_STRATEGY.Alpha003TargetStrategy)
    broker, journal, coordinator = decision_mode._new_journal_context()
    dispatch_attempts = []
    order_attempts = []
    owner.p = SimpleNamespace(
        decision_tape=writer,
        execution_enabled=True,
        cohort=SimpleNamespace(
            cohort_id=second_batch.cohort_id,
            current_batch=lambda: second_batch,
        ),
    )
    owner.broker = broker
    owner._last_decision_tape_batch_id = None
    owner._last_decision_tape_reference = None
    owner._last_decision_tape_error = None
    owner._coordinator = coordinator
    owner._account_scope = economics.ACCOUNT_SCOPE
    owner._strategy_scope = economics.STRATEGY_SCOPE
    owner._logical_run_id = coordinator.logical_run_id
    owner._source_kind = "ALPHA003_GRID"
    owner._last_signal_target = second_decision
    owner.last_execution_block_reason = None
    owner.live_factors = SimpleNamespace(snapshot=lambda: second_snapshot)
    owner._data_by_target = {target: object() for target in _TARGETS}
    owner._orders_by_broker_ref = {}
    owner._risk_policy = economics._risk_policy()
    owner.buy = lambda **kwargs: order_attempts.append(("BUY", kwargs))
    owner.sell = lambda **kwargs: order_attempts.append(("SELL", kwargs))
    owner.cancel = lambda order: order_attempts.append(("CANCEL", order))
    owner._find_order_object = lambda _action: object()
    actual_dispatch = _STRATEGY.Alpha003TargetStrategy._dispatch_live_actions

    def capture_dispatch(actions, batch):
        dispatch_attempts.extend(actions)
        return actual_dispatch(owner, actions, batch)

    owner._dispatch_live_actions = capture_dispatch

    try:
        durable, reference, tape_error = _STRATEGY.Alpha003TargetStrategy._record_decision_tape(
            owner, second_batch, second_snapshot, second_decision, second_plan
        )
        assert durable is False
        assert reference is None
        assert tape_error == "DECISION_TAPE_WRITE_FAILED"
        assert captured_overflow_codes == ["DECISION_TAPE_BYTE_BUDGET_EXCEEDED"]
        assert writer.summary()["failed"] is True
        assert writer.summary()["bytes"] == len(accepted_prefix) == prefix_bytes
        assert writer.summary()["record_count"] == 1
        assert writer.last_record_reference == accepted_reference
        assert tape_path.read_bytes() == accepted_prefix

        gated_plan = _STRATEGY.Alpha003TargetStrategy._gate_open_actions(
            second_plan, tape_durable=durable
        )
        assert gated_plan.status == "READY"
        assert gated_plan.reason == "OPEN_SUPPRESSED_DECISION_TAPE"
        assert gated_plan.actions == (second_plan.actions[1], second_plan.actions[2])
        assert not any(
            action.action == "SUBMIT" and action.position_effect == "OPEN"
            for action in gated_plan.actions
        )

        _STRATEGY.Alpha003TargetStrategy._live_grid_decision(
            owner,
            second_batch,
            second_snapshot,
            None,
            gated_plan,
            decision_tape_reference=reference,
            tape_error=tape_error,
            proposed_plan=second_plan,
        )
        assert dispatch_attempts == []
        assert order_attempts == []
        cursor = coordinator.grid_cursor(second_batch.cohort_id)
        assert cursor is not None
        saved = journal.decision(cursor.decision_id)
        assert saved is not None and saved.is_noop is True
        assert saved.intent_keys == ()
        assert saved.economic_payload["decision_tape_status"] == "FAILED"
        assert saved.economic_payload["decision_tape_error"] == tape_error
        assert saved.economic_payload["dispatch_suppressed"] is True
        assert coordinator.run_order_count() == 0

        with pytest.raises(_RUNNER.RunnerError) as close_error:
            writer.close()
        assert close_error.value.code == "DECISION_TAPE_CLOSE_FAILED"
        assert writer.summary()["closed"] is True
        assert writer.summary()["failed"] is True
        assert tape_path.read_bytes() == accepted_prefix
    finally:
        if not writer.summary()["closed"]:
            try:
                writer.close()
            except _RUNNER.RunnerError:
                pass
        journal.close()


@pytest.mark.integration
def test_fee_pair_source_only_reader_streams_long_tape_with_bounded_memory(tmp_path):
    """The source-only verifier retains a header and tail, not the whole tape."""
    target_decision = economics._target_decision(mode="native", batch_id="long-tape")
    batch, snapshot = _complete_batch_snapshot(target_decision)
    tape_path = tmp_path / "long-source-only-prefix.jsonl"
    writer = _writer(
        tape_path,
        max_bytes=64 * 1024 * 1024,
        calendar_id=batch.calendar_id,
    )
    assert writer.record_decision(batch, snapshot, target_decision, None) is True
    writer.close()

    header_raw, sample_raw = tape_path.read_bytes().splitlines(keepends=True)
    sample = json.loads(sample_raw.decode("utf-8"))
    sample.pop("record_id")
    row_bytes = len(sample_raw)
    row_count = max(4096, (16 * 1024 * 1024 // row_bytes) + 1)
    with tape_path.open("wb") as handle:
        handle.write(header_raw)
        for index in range(1, row_count + 1):
            row = dict(sample)
            row["record_index"] = index
            row["record_id"] = hashlib.sha256(
                _RUNNER._canonical_json_bytes(row).rstrip(b"\n")
            ).hexdigest()
            handle.write(_RUNNER._canonical_json_bytes(row))
    tape_size = tape_path.stat().st_size
    assert tape_size > 16 * 1024 * 1024

    tracemalloc.start()
    try:
        summary = writer._stream_fee_pair_tape(None)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert summary["row_count"] == row_count + 1
    assert summary["last"]["record_index"] == row_count
    assert summary["raw_sha256"] == hashlib.sha256(tape_path.read_bytes()).hexdigest()
    assert peak < 4 * 1024 * 1024


@pytest.mark.integration
def test_strict_decision_reader_rejects_record_cap_plus_one_before_json_parse(
    tmp_path, monkeypatch
):
    target_decision = economics._target_decision(mode="native", batch_id="line-cap")
    batch, _snapshot = _complete_batch_snapshot(target_decision)
    tape_path = tmp_path / "oversized-record.jsonl"
    writer = _writer(tape_path, max_bytes=16 * 1024 * 1024, calendar_id=batch.calendar_id)
    writer.close()
    header_raw = tape_path.read_bytes()
    record_cap = _RUNNER._FEE_PAIR_SOURCE_ONLY_MAX_RECORD_BYTES
    tape_path.write_bytes(header_raw + b"{" + b" " * (record_cap - 1) + b"\n")

    original_open = Path.open
    read_sizes = []

    class _TrackingHandle:
        def __init__(self, handle):
            self._handle = handle

        def __enter__(self):
            self._handle.__enter__()
            return self

        def __exit__(self, *args):
            return self._handle.__exit__(*args)

        def readline(self, size=-1):
            read_sizes.append(size)
            return self._handle.readline(size)

        def __getattr__(self, name):
            return getattr(self._handle, name)

    def tracking_open(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        return _TrackingHandle(handle) if path == tape_path else handle

    original_loads = json.loads
    parsed_rows = []

    def tracking_loads(value, *args, **kwargs):
        parsed_rows.append(value)
        return original_loads(value, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracking_open)
    monkeypatch.setattr(_RUNNER.json, "loads", tracking_loads)
    with pytest.raises(_RUNNER.RunnerError) as rejected:
        tuple(
            _RUNNER.iter_decision_tape(
                tape_path,
                max_bytes=16 * 1024 * 1024,
                max_record_bytes=record_cap,
            )
        )

    assert rejected.value.code == "DECISION_TAPE_RECORD_BYTE_LIMIT_EXCEEDED"
    assert read_sizes == [record_cap + 1, record_cap + 1]
    assert len(parsed_rows) == 1
