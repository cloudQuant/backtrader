"""Synthetic contracts for Alpha003 source-receipt trading-day normalization."""

from __future__ import annotations

import hashlib
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


_STRATEGY_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "unified"
    / "028_alpha003_simnow_minute"
    / "alpha003_strategy.py"
)
_STRATEGY_MODULE_NAME = "_alpha003_source_receipt_trading_day_test_strategy"
_STRATEGY_SPEC = importlib.util.spec_from_file_location(_STRATEGY_MODULE_NAME, _STRATEGY_SOURCE)
if _STRATEGY_SPEC is None or _STRATEGY_SPEC.loader is None:
    raise RuntimeError("Alpha003 strategy source is unavailable")
STRATEGY = importlib.util.module_from_spec(_STRATEGY_SPEC)
sys.modules[_STRATEGY_MODULE_NAME] = STRATEGY
_STRATEGY_SPEC.loader.exec_module(STRATEGY)

UTC = timezone.utc
TARGETS = ("EX1.PROD1", "EX2.PROD2")


def _synthetic_source_receipt_inputs(raw_trading_day, batch_id="synthetic-source-batch"):
    close_time = datetime(2026, 10, 29, 10, 1, tzinfo=UTC)
    slot_id = "minute:" + close_time.isoformat()
    members = {}
    envelopes = []
    for index, member_id in enumerate(TARGETS, start=1):
        envelope = SimpleNamespace(
            source_ref="synthetic-source-" + str(index),
            source_role="live",
            connection_generation=1,
            feed_sequence=index,
            bar_id="synthetic-bar-" + str(index),
            bucket_start=close_time - timedelta(minutes=1),
            close_time=close_time,
            available_at=close_time,
            trading_day=raw_trading_day,
            session_segment="regular",
            timezone_id="UTC",
            clock_domain_id="synthetic-clock",
            complete=True,
            quality="GOOD",
            present=True,
            missing_fields=(),
            quality_flags=(),
            event_source="synthetic-test",
            received_monotonic_ns=1_000 + index,
            rules_hash=None,
            origin_partition=None,
            slot_id=slot_id,
        )
        envelopes.append(envelope)
        members[member_id] = SimpleNamespace(envelope=envelope)
    fingerprint = hashlib.sha256(b"synthetic-calendar").hexdigest()
    strategy = SimpleNamespace(
        _source_receipt_batch_id=None,
        _source_receipt_tape_reference=None,
        _source_receipt_cache=None,
        _target_ids=TARGETS,
        _source_kind="synthetic-ctp-factor-source",
        _source_predecessor=None,
        _source_restart_marker=None,
        p=SimpleNamespace(cohort=SimpleNamespace(calendar_fingerprint=fingerprint)),
    )
    batch = SimpleNamespace(
        batch_id=batch_id,
        cohort_id="synthetic-cohort",
        calendar_id="synthetic-calendar",
        calendar_version="synthetic-calendar-v1",
        epoch_id=1,
        slot_index=0,
        close_time=close_time,
        members=members,
    )
    snapshot = SimpleNamespace(readiness="WARMUP")
    tape_reference = {
        "file_id": "synthetic-file",
        "record_id": "synthetic-record",
        "record_index": 1,
        "batch_id": batch_id,
    }
    return strategy, batch, snapshot, tape_reference, tuple(envelopes)


def _build_synthetic_source_receipt(raw_trading_day, batch_id="synthetic-source-batch"):
    strategy, batch, snapshot, tape_reference, envelopes = _synthetic_source_receipt_inputs(
        raw_trading_day, batch_id
    )
    receipt = STRATEGY.Alpha003TargetStrategy._source_receipt(
        strategy, batch, snapshot, tape_reference
    )
    return receipt, envelopes, strategy


def test_alpha003_source_receipt_canonicalizes_compact_and_iso_days():
    compact_receipt, compact_envelopes, _ = _build_synthetic_source_receipt("20261029")
    iso_receipt, iso_envelopes, _ = _build_synthetic_source_receipt(
        "2026-10-29", batch_id="synthetic-iso-batch"
    )

    assert compact_receipt.members == iso_receipt.members
    assert tuple(member.trading_day for member in compact_receipt.members) == (
        "2026-10-29",
        "2026-10-29",
    )
    assert tuple(envelope.trading_day for envelope in compact_envelopes) == (
        "20261029",
        "20261029",
    )
    assert tuple(envelope.trading_day for envelope in iso_envelopes) == (
        "2026-10-29",
        "2026-10-29",
    )


@pytest.mark.parametrize(
    "invalid_day",
    (
        None,
        "20260230",
        "2026-02-30",
        "2026-2-03",
        "2026102",
        "2026-10-29T00:00:00",
    ),
)
def test_alpha003_source_receipt_rejects_invalid_trading_days(invalid_day):
    strategy, batch, snapshot, tape_reference, envelopes = _synthetic_source_receipt_inputs(
        invalid_day, batch_id="synthetic-invalid-day-batch"
    )

    with pytest.raises(ValueError, match="source receipt trading_day is invalid"):
        STRATEGY.Alpha003TargetStrategy._source_receipt(
            strategy, batch, snapshot, tape_reference
        )

    assert strategy._source_receipt_batch_id is None
    assert all(envelope.trading_day is invalid_day for envelope in envelopes)
