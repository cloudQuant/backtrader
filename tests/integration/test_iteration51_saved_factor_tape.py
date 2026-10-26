"""Synthetic, offline contracts for saved Iteration 51 Alpha003 tapes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

import scripts.validate_iteration51_saved_factor_tape as validator
from scripts.validate_iteration51_saved_factor_tape import (
    SavedTapeValidationError,
    _canonical_bytes,
    _run_factor_strategy,
    _runner_module,
    project_expected_plan,
    validate_saved_factor_tape,
)
import tests.integration.test_live_alpha003_parity as live_parity
from backtrader.research.live_cohort import (
    LiveCalendarSlot,
    LiveCohortCalendar,
)
from tests.integration.test_live_alpha003_parity import _minute_frames


_UTC = timezone.utc
_TARGETS = tuple("EX%d.P%d" % (index, index) for index in range(6))
_GRID_COUNT = 195
_PREHEAT = 30
_CLOCK_DOMAIN = "synthetic-ctp-clock"
_CALENDAR_ID = "synthetic-ctp-calendar"


@dataclass(frozen=True)
class _Product:
    exchange_id: str
    product_id: str


class _Grid:
    def __init__(self, row):
        self._row = row
        self.evidence_sha256 = None

    def to_dict(self):
        return self._row


class _Manifest:
    def __init__(self, row, digest):
        self._row = row
        self.manifest_sha256 = digest

    def to_dict(self):
        return self._row


def _plan_and_frames(
    *,
    clock_domain_id=_CLOCK_DOMAIN,
    calendar_id=_CALENDAR_ID,
    instrument_ids=None,
):
    base = _minute_frames(320)
    source_frames = tuple(base.values())
    closes = tuple(source_frames[0].index[:_GRID_COUNT].to_pydatetime())
    targets = _TARGETS
    products = tuple(
        _Product("EX%d" % index, "P%d" % index) for index in range(len(targets))
    )
    product_by_target = dict(zip(targets, products))
    target_by_product = {product: target for target, product in product_by_target.items()}
    routes = {
        product: (
            "SYNTH-%03d" % index
            if instrument_ids is None
            else instrument_ids[target]
        )
        for index, (target, product) in enumerate(zip(targets, products))
    }
    target_products = [
        {"exchange_id": product.exchange_id, "product_id": product.product_id}
        for product in products
    ]
    trading_day = closes[0].date().isoformat()
    product_trading_days = [
        {"product": product_row, "trading_days": [trading_day]}
        for product_row in target_products
    ]
    minutes = []
    for close_at in closes:
        members = []
        for product in products:
            members.append(
                {
                    "product": {
                        "exchange_id": product.exchange_id,
                        "product_id": product.product_id,
                    },
                    "trading_day": close_at.date().isoformat(),
                    "session_date": close_at.date().isoformat(),
                    "action_day": close_at.date().isoformat(),
                    "session_id": "regular",
                }
            )
        minutes.append({"close_time": close_at.isoformat(), "members": members})
    grid = _Grid(
        {
            "schema": "backtrader.futures_common_minute_grid.v1",
            "status": "READY",
            "decision_at": (closes[0] - timedelta(minutes=10)).isoformat(),
            "target_products": target_products,
            "product_trading_days": product_trading_days,
            "calendar_hashes": [
                {"exchange_id": product.exchange_id, "sha256": "%064x" % (index + 1)}
                for index, product in enumerate(products)
            ],
            "minutes": minutes,
        }
    )
    manifest_row = {
        "schema": "backtrader.futures_main_contract_manifest.v2",
        "status": "READY",
        "selection_id": "synthetic-selection",
    }
    manifest_digest = hashlib.sha256(_canonical_bytes(manifest_row).rstrip(b"\n")).hexdigest()
    plan = {
        "selection_source": "ctp_query_snapshot_equal_weight_v1",
        "selection_path": "ctp-query://synthetic-catalog|synthetic-quotes",
        "source_snapshot_id": "synthetic-catalog|synthetic-quotes",
        "manifest": _Manifest(manifest_row, manifest_digest),
        "targets": targets,
        "products": products,
        "routes": routes,
        "product_by_target": product_by_target,
        "target_by_product": target_by_product,
        "authorized_targets": targets,
        "grid": grid,
    }
    expected = project_expected_plan(
        plan,
        clock_domain_id=clock_domain_id,
        calendar_id=calendar_id,
    )
    frames = {
        target: frame.iloc[:_GRID_COUNT].copy(deep=True)
        for target, frame in zip(targets, source_frames)
    }
    return expected, plan, manifest_row, frames


def _hash_value(value):
    number = float(value)
    return {
        "finite": number == number and abs(number) != float("inf"),
        "value": number if number == number and abs(number) != float("inf") else None,
        "float64_hex": number.hex(),
    }


def _selection_evidence(expected, manifest_row):
    binding = {
        "schema": "backtrader.alpha003_epoch_selection_evidence.v1",
        "epoch_id": 1,
        "selection_source": expected["selection_source"],
        "selection_path": expected["selection_path"],
        "source_snapshot_id": expected["source_snapshot_id"],
        "manifest_sha256": expected["manifest_sha256"],
        "routes": {
            target: expected["routes"][target]["instrument_id"]
            for target in expected["targets"]
        },
        "authorized_targets": expected["authorized_targets"],
        "grid_semantics_sha256": expected["grid_semantics_sha256"],
    }
    binding_sha256 = hashlib.sha256(_canonical_bytes(binding).rstrip(b"\n")).hexdigest()
    return {**binding, "binding_sha256": binding_sha256, "manifest": manifest_row}


def _write_tape(path: Path, expected, manifest_row, frames, *, omit_index=None, tamper=None):
    runner = _runner_module()
    raw_by_target = {
        target: {field: [float(value) for value in frames[target][field].to_list()] for field in runner.OHLCV_FIELDS}
        for target in expected["targets"]
    }
    native = _run_factor_strategy(
        expected,
        raw_by_target,
        factor_mode="native",
        direction=1,
    )
    file_id = "synthetic-decision-tape-0001"
    header = {
        "schema": runner.DECISION_TAPE_SCHEMA,
        "record_type": "HEADER",
        "file_id": file_id,
        "created_at": datetime(2025, 1, 1, tzinfo=_UTC).isoformat(),
        "mode": "live",
        "factor_mode": "native",
        "direction": 1,
        "targets": expected["targets"],
        "calendar_id": expected["calendar_id"],
        "grid_sha256": expected["grid_sha256"],
        "source_snapshot_id": expected["source_snapshot_id"],
        "selection_evidence": _selection_evidence(expected, manifest_row),
    }
    header_id = hashlib.sha256(_canonical_bytes(header).rstrip(b"\n")).hexdigest()
    header["record_id"] = header_id
    selection_hash = header["selection_evidence"]["binding_sha256"]
    output_rows = [_canonical_bytes(header)]
    for index, minute in enumerate(expected["minutes"]):
        if index == omit_index:
            continue
        close_at = datetime.fromisoformat(minute["close_time"].replace("Z", "+00:00"))
        available_at = close_at + timedelta(milliseconds=100)
        batch_id = "batch-%03d" % index
        members = {}
        factor_values = {}
        for target_index, target in enumerate(expected["targets"]):
            plan_member = minute["members"][target]
            raw_values = {field: raw_by_target[target][field][index] for field in runner.OHLCV_FIELDS}
            members[target] = {
                "cohort_id": "alpha003:%s:1" % expected["calendar_id"],
                "calendar_id": expected["calendar_id"],
                "epoch_id": 1,
                "slot_index": index,
                "slot_id": "minute:%s" % close_at.isoformat(),
                "instrument": plan_member["instrument_id"],
                "source_ref": "synthetic-feed:%s" % target,
                "source_role": "live",
                "connection_generation": 1,
                "feed_sequence": index + 1,
                "bucket_start": plan_member["bucket_start"],
                "close_time": minute["close_time"],
                "available_at": (close_at + timedelta(milliseconds=50)).isoformat().replace("+00:00", "Z"),
                "trading_day": plan_member["trading_day"],
                "session_segment": plan_member["session_segment"],
                "timezone_id": "Asia/Shanghai",
                "clock_domain_id": expected["clock_domain_id"],
                "bar_id": "bar:%s:%03d" % (target, index),
                "complete": True,
                "quality": "GOOD",
                "present": True,
                "quality_flags": [],
                "event_source": "synthetic-ctp-callback",
                "received_monotonic_ns": 1_000_000_000 + index * 60_000_000_000 + target_index,
                "raw_values": raw_values,
            }
            value = native["values"][target][index]
            reason = native["reasons"][target][index]
            factor_values[target] = {
                "value": _hash_value(value),
                "status": "OUTPUT_AVAILABLE" if reason is None else "OUTPUT_UNAVAILABLE",
                "reason": reason,
                "present": True,
                "complete": True,
                "quality": "GOOD",
                "source_role": "live",
                "member_id": target,
                "source_ref": "synthetic-feed:%s" % target,
                "sequence": index + 1,
                "generation": 1,
            }
        if tamper is not None and index == tamper[0]:
            target = expected["targets"][0]
            stored = factor_values[target]["value"]
            changed = float(stored["value"]) + 0.125
            factor_values[target]["value"] = _hash_value(changed)
        row = {
            "schema": runner.DECISION_TAPE_SCHEMA,
            "record_type": "DECISION",
            "file_id": file_id,
            "record_index": index + 1 if omit_index is None or index < omit_index else index,
            "batch_id": batch_id,
            "cohort_id": "alpha003:%s:1" % expected["calendar_id"],
            "calendar_id": expected["calendar_id"],
            "calendar_version": "synthetic-v1",
            "epoch_id": 1,
            "slot_index": index,
            "close_time": minute["close_time"],
            "available_at": available_at.isoformat().replace("+00:00", "Z"),
            "readiness": "LIVE_READY" if index >= _PREHEAT - 1 else "WARMUP",
            "readiness_reasons": [] if index >= _PREHEAT - 1 else ["live_cutover_incomplete"],
            "members": members,
            "factors": {
                "plan_id": "synthetic-alpha003-plan",
                "factors": {
                    "alpha003": {
                        "mode": "native",
                        "panel_line": "factor",
                        "direction": 1,
                        "source_sha256": native["source_sha256"],
                        "values": factor_values,
                    }
                },
            },
            "target_decision": None,
            "order_plan": {
                "status": "NO_ACTION",
                "reason": "synthetic read-only source tape",
                "decision_batch_id": batch_id,
                "decision_available_at": available_at.isoformat().replace("+00:00", "Z"),
                "actions": [],
            },
            "selection_evidence_sha256": selection_hash,
            "header_record_id": header_id,
        }
        record_id = hashlib.sha256(_canonical_bytes(row).rstrip(b"\n")).hexdigest()
        row["record_id"] = record_id
        output_rows.append(_canonical_bytes(row))
    path.write_bytes(b"".join(output_rows))
    payload = path.read_bytes()
    return {
        "file_id": file_id,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "record_count": _GRID_COUNT,
    }


def _validate(path, expected, pins, *, mode, required_live_ready=100):
    return validate_saved_factor_tape(
        path,
        expected=expected,
        expected_file_id=pins["file_id"],
        expected_sha256=pins["sha256"],
        expected_bytes=pins["bytes"],
        expected_record_count=pins["record_count"],
        factor_mode=mode,
        direction=1,
        preheat_bars=_PREHEAT,
        required_live_ready=required_live_ready,
    )


def _rewrite_tape_pins(path, mutate):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    mutate(rows)
    encoded = []
    for row in rows:
        row.pop("record_id", None)
        row["record_id"] = hashlib.sha256(_canonical_bytes(row).rstrip(b"\n")).hexdigest()
        encoded.append(_canonical_bytes(row))
    path.write_bytes(b"".join(encoded))
    payload = path.read_bytes()
    return {
        "file_id": rows[0]["file_id"],
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "record_count": len(rows) - 1,
    }


def _live_calendar_with_target_members(calendar_builder, targets, grid):
    calendar, previous_member_ids = calendar_builder(targets, grid)
    slots = []
    for slot in calendar.slots:
        sessions = {
            target: slot.member_sessions[previous_member_ids[target]] for target in targets
        }
        slots.append(
            LiveCalendarSlot(
                slot_id=slot.slot_id,
                bucket_start=slot.bucket_start,
                close_time=slot.close_time,
                trading_day=slot.trading_day,
                session_segment=slot.session_segment,
                member_sessions=sessions,
            )
        )
    return (
        LiveCohortCalendar(
            calendar_id=calendar.calendar_id,
            version=calendar.version,
            epoch_id=calendar.epoch_id,
            frequency=calendar.frequency,
            frequency_seconds=calendar.frequency_seconds,
            timezone_id=calendar.timezone_id,
            clock_domain_id=calendar.clock_domain_id,
            session_semantics=calendar.session_semantics,
            slots=tuple(slots),
        ),
        {target: target for target in targets},
    )


def _write_live_snapshot_tape(path, expected, manifest_row, strategy, cohort, feeds):
    runner = _runner_module()
    selection_evidence = _selection_evidence(expected, manifest_row)
    writer = runner.DecisionTapeWriter(
        path,
        64 * 1024 * 1024,
        mode="live",
        factor_mode="native",
        direction=1,
        targets=tuple(expected["targets"]),
        calendar_id=expected["calendar_id"],
        grid_sha256=expected["grid_sha256"],
        source_snapshot_id=expected["source_snapshot_id"],
        selection_evidence=selection_evidence,
    )
    receipts = {
        target: cohort.complete_window_bars(
            feeds[target], runner.OHLCV_FIELDS, len(expected["minutes"])
        )
        for target in expected["targets"]
    }
    if any(len(window) != len(expected["minutes"]) for window in receipts.values()):
        raise AssertionError("live cohort did not retain the full complete receipt window")
    try:
        for index, snapshot in enumerate(strategy.snapshots):
            batch = SimpleNamespace(
                status="COMPLETE",
                batch_id=snapshot.batch_id,
                cohort_id=snapshot.cohort_id,
                calendar_id=snapshot.calendar_id,
                calendar_version=snapshot.calendar_version,
                epoch_id=snapshot.epoch_id,
                slot_index=index,
                close_time=snapshot.close_time,
                available_at=snapshot.available_at,
                members=MappingProxyType(
                    {target: receipts[target][index] for target in expected["targets"]}
                ),
            )
            writer.record_decision(batch, snapshot, None, None)
    finally:
        summary = writer.close()
    if not summary["closed"] or summary["record_count"] != len(expected["minutes"]):
        raise AssertionError("production DecisionTapeWriter did not close a complete live tape")
    return {
        "file_id": summary["file_id"],
        "sha256": summary["sha256"],
        "bytes": summary["bytes"],
        "record_count": summary["record_count"],
    }


def _live_bar_events_with_integer_generation(bar_events, frames, asset, *, arrival_delay=None):
    events = bar_events(frames, asset, arrival_delay=arrival_delay)
    return tuple(
        MappingProxyType({**event, "connection_generation": 1}) for event in events
    )


@pytest.mark.integration
def test_saved_factor_tape_recomputes_full_grid_with_native_and_build(tmp_path):
    expected, _plan, manifest_row, frames = _plan_and_frames()
    path = tmp_path / "synthetic-decision-tape.jsonl"
    pins = _write_tape(path, expected, manifest_row, frames)

    native = _validate(path, expected, pins, mode="native")
    build = _validate(path, expected, pins, mode="build")

    assert native["status"] == build["status"] == "PASS"
    assert native["grid_minute_count"] == build["grid_minute_count"] == _GRID_COUNT
    assert native["decision_record_count"] == build["decision_record_count"] == _GRID_COUNT
    assert native["value_comparisons"] == build["value_comparisons"] == _GRID_COUNT * len(_TARGETS)
    assert native["reason_comparisons"] == native["membership_comparisons"]
    assert build["reason_comparisons"] == build["membership_comparisons"]
    assert native["tape_sha256"] == build["tape_sha256"] == pins["sha256"]
    assert native["live_ready_rows"] >= 100 and build["live_ready_rows"] >= 100
    assert native["distinct_finite_witnesses"] >= 2
    assert build["distinct_finite_witnesses"] >= 2
    assert native["orders_submitted"] == build["orders_submitted"] == 0
    assert native["provider_calls"] == build["provider_calls"] == 0


@pytest.mark.integration
def test_saved_factor_tape_rejects_rehashed_factor_value_tamper(tmp_path):
    expected, _plan, manifest_row, frames = _plan_and_frames()
    path = tmp_path / "tampered-factor.jsonl"
    pins = _write_tape(path, expected, manifest_row, frames, tamper=(100, "alpha003"))

    with pytest.raises(SavedTapeValidationError) as raised:
        _validate(path, expected, pins, mode="native")

    assert raised.value.code == "TAPE_FACTOR_VALUE_MISMATCH"


@pytest.mark.integration
def test_saved_factor_tape_rejects_missing_planned_close(tmp_path):
    expected, _plan, manifest_row, frames = _plan_and_frames()
    path = tmp_path / "missing-minute.jsonl"
    pins = _write_tape(path, expected, manifest_row, frames, omit_index=87)

    with pytest.raises(SavedTapeValidationError) as raised:
        _validate(path, expected, pins, mode="native")

    assert raised.value.code == "TAPE_GRID_COVERAGE_MISMATCH"


@pytest.mark.integration
def test_saved_factor_tape_rejects_short_expected_grid(tmp_path):
    expected, _plan, manifest_row, frames = _plan_and_frames()
    path = tmp_path / "short-expected-grid.jsonl"
    pins = _write_tape(path, expected, manifest_row, frames)
    short_expected = dict(expected)
    short_expected["minutes"] = expected["minutes"][:-1]

    with pytest.raises(SavedTapeValidationError) as raised:
        _validate(path, short_expected, pins, mode="native")

    assert raised.value.code == "EXPECTED_PLAN_MINUTES_INVALID"


@pytest.mark.integration
def test_saved_factor_tape_rejects_change_during_validation(tmp_path, monkeypatch):
    expected, _plan, manifest_row, frames = _plan_and_frames()
    path = tmp_path / "changed-during-validation.jsonl"
    pins = _write_tape(path, expected, manifest_row, frames)
    runner = _runner_module()
    original = runner.iter_decision_tape

    def mutate_after_read(tape_path, *, max_bytes):
        yield from original(tape_path, max_bytes=max_bytes)
        tape_path.write_bytes(tape_path.read_bytes() + b"\n")

    monkeypatch.setattr(runner, "iter_decision_tape", mutate_after_read)
    with pytest.raises(SavedTapeValidationError) as raised:
        _validate(path, expected, pins, mode="native")

    assert raised.value.code == "TAPE_CHANGED_DURING_VALIDATION"


@pytest.mark.integration
def test_saved_factor_tape_accepts_live_ready_good_batch_with_legal_nan(tmp_path, monkeypatch):
    calendar_id = "alpha003-live-parity-v1"
    clock_domain_id = "alpha003-replay-clock-v1"
    expected, _plan, manifest_row, frames = _plan_and_frames(
        clock_domain_id=clock_domain_id,
        calendar_id=calendar_id,
        instrument_ids={target: target for target in _TARGETS},
    )
    constant_target = _TARGETS[0]
    for field in ("open", "high", "low", "close"):
        frames[constant_target][field] = 100.0

    calendar_builder = live_parity._calendar
    bar_events = live_parity._bar_events
    monkeypatch.setattr(
        live_parity,
        "_calendar",
        lambda targets, grid: _live_calendar_with_target_members(
            calendar_builder, targets, grid
        ),
    )
    monkeypatch.setattr(
        live_parity,
        "_bar_events",
        lambda source_frames, asset, *, arrival_delay=None: _live_bar_events_with_integer_generation(
            bar_events, source_frames, asset, arrival_delay=arrival_delay
        ),
    )
    strategy, cohort, feeds = live_parity._run_live(frames, mode="native")
    tail = strategy.snapshots[_PREHEAT - 1 :]
    assert len(tail) >= 100
    assert all(snapshot.readiness.value == "LIVE_READY" for snapshot in tail)
    assert any(
        not math.isfinite(float(snapshot.factors["alpha003"].values[constant_target].value))
        and snapshot.factors["alpha003"].values[constant_target].reason == "DOMAIN_ERROR"
        for snapshot in tail
    )

    path = tmp_path / "live-factor-snapshot-decision-tape.jsonl"
    pins = _write_live_snapshot_tape(path, expected, manifest_row, strategy, cohort, feeds)
    native = _validate(path, expected, pins, mode="native")
    build = _validate(path, expected, pins, mode="build")

    assert native["status"] == build["status"] == "PASS"
    assert native["source_factor_mode"] == build["source_factor_mode"] == "native"
    assert native["offline_factor_mode"] == "native"
    assert build["offline_factor_mode"] == "build"
    assert native["value_comparisons"] == build["value_comparisons"] == _GRID_COUNT * len(_TARGETS)
    assert native["reason_comparisons"] == build["reason_comparisons"] == _GRID_COUNT * len(_TARGETS)
    assert native["membership_comparisons"] == build["membership_comparisons"] == _GRID_COUNT * len(_TARGETS)
    assert native["live_ready_rows"] == build["live_ready_rows"] == len(tail)
    assert native["two_candidate_witness_rows"] >= 1
    assert build["two_candidate_witness_rows"] >= 1


@pytest.mark.integration
def test_saved_factor_tape_rejects_bad_member_quality(tmp_path):
    expected, _plan, manifest_row, frames = _plan_and_frames()
    path = tmp_path / "bad-member-quality.jsonl"
    _write_tape(path, expected, manifest_row, frames)

    def make_quality_bad(rows):
        rows[50]["members"][_TARGETS[0]]["quality"] = "STALE"

    pins = _rewrite_tape_pins(path, make_quality_bad)
    with pytest.raises(SavedTapeValidationError) as raised:
        _validate(path, expected, pins, mode="native")
    assert raised.value.code == "TAPE_MEMBER_PLAN_OR_QUALITY_MISMATCH"


@pytest.mark.integration
def test_saved_factor_tape_rejects_decreasing_member_receive_time(tmp_path):
    expected, _plan, manifest_row, frames = _plan_and_frames()
    path = tmp_path / "decreasing-member-receive-time.jsonl"
    _write_tape(path, expected, manifest_row, frames)

    def make_receive_time_decrease(rows):
        target = _TARGETS[0]
        previous = rows[40]["members"][target]["received_monotonic_ns"]
        rows[41]["members"][target]["received_monotonic_ns"] = previous - 1

    pins = _rewrite_tape_pins(path, make_receive_time_decrease)
    with pytest.raises(SavedTapeValidationError) as raised:
        _validate(path, expected, pins, mode="native")
    assert raised.value.code == "TAPE_MEMBER_RECEIPT_ORDER_INVALID"


@pytest.mark.integration
def test_saved_factor_tape_rejects_history_receipts_for_live_grid(tmp_path):
    expected, _plan, manifest_row, frames = _plan_and_frames()
    path = tmp_path / "history-receipts-on-live-grid.jsonl"
    _write_tape(path, expected, manifest_row, frames)

    def make_all_receipts_history(rows):
        for row in rows[1:]:
            points = row["factors"]["factors"]["alpha003"]["values"]
            for target in _TARGETS:
                row["members"][target]["source_role"] = "history"
                points[target]["source_role"] = "history"

    pins = _rewrite_tape_pins(path, make_all_receipts_history)
    with pytest.raises(SavedTapeValidationError) as raised:
        _validate(path, expected, pins, mode="native")
    assert raised.value.code == "TAPE_MEMBER_SOURCE_ROLE_INVALID"


@pytest.mark.integration
def test_saved_factor_tape_checks_hash_after_offline_calculation(tmp_path, monkeypatch):
    expected, _plan, manifest_row, frames = _plan_and_frames()
    path = tmp_path / "changed-during-offline-calculation.jsonl"
    pins = _write_tape(path, expected, manifest_row, frames)
    original = validator._run_factor_strategy

    def mutate_after_calculation(*args, **kwargs):
        result = original(*args, **kwargs)
        with path.open("ab") as handle:
            handle.write(b" ")
        return result

    monkeypatch.setattr(validator, "_run_factor_strategy", mutate_after_calculation)
    with pytest.raises(SavedTapeValidationError) as raised:
        _validate(path, expected, pins, mode="native")
    assert raised.value.code == "TAPE_CHANGED_DURING_VALIDATION"


@pytest.mark.integration
def test_saved_factor_tape_cli_bounds_plan_read_before_json_parse(
    tmp_path, monkeypatch, capsys
):
    expected_path = tmp_path / "over-budget-plan.json"
    with expected_path.open("wb") as handle:
        handle.truncate(validator.MAX_PLAN_BYTES + 1)

    def reject_json_parse(*args, **kwargs):
        raise AssertionError("over-budget expected plan reached JSON parsing")

    args = [
        "--tape",
        str(tmp_path / "not-opened.jsonl"),
        "--expected-plan-json",
        str(expected_path),
        "--file-id",
        "synthetic-file",
        "--sha256",
        "0" * 64,
        "--bytes",
        "1",
        "--record-count",
        str(_GRID_COUNT),
        "--factor-mode",
        "native",
        "--direction",
        "1",
        "--preheat-bars",
        str(_PREHEAT),
    ]
    with monkeypatch.context() as patch:
        patch.setattr(validator.json, "loads", reject_json_parse)
        code = validator.main(args)

    assert code == 1
    assert json.loads(capsys.readouterr().out) == {
        "code": "EXPECTED_PLAN_BYTE_BUDGET_EXCEEDED",
        "status": "FAIL",
    }


@pytest.mark.integration
def test_saved_factor_tape_cli_cannot_lower_live_ready_floor(tmp_path, capsys):
    expected, _plan, _manifest_row, _frames = _plan_and_frames()
    expected_path = tmp_path / "safe-expected-plan.json"
    expected_path.write_bytes(_canonical_bytes(expected))
    code = validator.main(
        [
            "--tape",
            str(tmp_path / "not-opened.jsonl"),
            "--expected-plan-json",
            str(expected_path),
            "--file-id",
            "synthetic-file",
            "--sha256",
            "0" * 64,
            "--bytes",
            "1",
            "--record-count",
            str(_GRID_COUNT),
            "--factor-mode",
            "native",
            "--direction",
            "1",
            "--preheat-bars",
            str(_PREHEAT),
            "--required-live-ready",
            "1",
        ]
    )
    assert code == 1
    assert json.loads(capsys.readouterr().out) == {
        "code": "LIVE_READY_REQUIREMENT_INVALID",
        "status": "FAIL",
    }
