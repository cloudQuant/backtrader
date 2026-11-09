"""Synthetic pending-host persistence for trade-date enrichment."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from bt_api_py.gateway_execution_stream_client import (
    GatewayExecutionReadContext,
    GatewayExecutionStreamClientResult,
)

from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.unit.live_state.test_gateway_execution_checkpoint import make_event, page, ready
from tests.unit.live_state.test_gateway_pending import inputs


def result(binding, consumer, events, after=0):
    return GatewayExecutionStreamClientResult(
        "OBSERVED",
        page=page(binding, consumer, events),
        request_context=GatewayExecutionReadContext(
            binding, consumer, after, None if after == 0 else "e" * 64, 256
        ),
    )


def dated(event, seq, *, date="20261107", metadata=True, fact="f" * 64, **changes):
    observation = replace(
        event.observation,
        schema_version=2,
        trade_date=date,
        trade_metadata_only=metadata,
        **changes,
    )
    return replace(event, sequence=seq, fact_digest=fact, observation=observation)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def test_legacy_receipt_enrichment_reopen_and_notification_preserved(state, ready):
    current, binding, consumer = ready
    legacy = make_event(current)
    first = result(binding, consumer, [legacy])
    first_page_bytes = canonical(first.page.to_mapping())
    saved = current.ingest_execution_result(first, expected_revision=0)
    raw = json.loads(Path(state.pending.path).read_bytes())
    receipt = raw["gateway"]["execution"]["receipts"][0]
    assert receipt["digest"] == hashlib.sha256(first_page_bytes).hexdigest()
    # Frozen v1 page digest: the v2 observation must not rewrite old receipts.
    assert receipt["digest"] == "1928e982fc5e1389e32b8d489e844fcfae08fe9b80bf01b2f501b0d7748a1078"
    assert "trade_date" not in first.page.events[0].observation.to_mapping()
    pending = current.commit_execution_notification_batch(
        3, {"schema_version": 1, "state": {"fills": 1}},
        [{"notification_id": "1" * 64, "kind": "trade", "object_key": "order",
          "payload": {"quantity": 1}}],
        expected_revision=saved.revision, expected_applied_sequence=0,
    )
    batch = current.load_execution_notification_batch()
    updated = dated(legacy, 6)
    second = result(binding, consumer, [updated], after=3)
    saved = current.ingest_execution_result(second, expected_revision=pending.revision)
    assert (saved.stored_sequence, saved.applied_sequence, saved.acknowledged_sequence) == (6, 3, 0)
    assert current.load_execution_notification_batch() == batch
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    assert reopened.load_execution_checkpoint() == saved
    assert reopened.read_execution_events(after_sequence=0) == (legacy, updated)
    after = json.loads(Path(state.pending.path).read_bytes())
    assert after["gateway"]["execution"]["receipts"][0] == receipt
    assert canonical(after["gateway"]["execution"]["events"][0]) == canonical(
        first.page.to_mapping()["events"][0]
    )
    assert reopened.ingest_execution_result(first, expected_revision=0) == saved
    assert reopened.ingest_execution_result(second, expected_revision=pending.revision) == saved
    repeat = dated(legacy, 8, fact="9" * 64)
    saved = reopened.ingest_execution_result(result(binding, consumer, [repeat], after=6),
                                             expected_revision=saved.revision)
    assert saved.stored_sequence == 8 and saved.applied_sequence == 3
    assert reopened.load_execution_notification_batch() == batch


@pytest.mark.parametrize(
    ("case", "error"),
    [("no_original", "WITHOUT_ORIGINAL"), ("wrong_trade", "WITHOUT_ORIGINAL"),
     ("wrong_economics", "TRADE_CONFLICT"), ("normal_enrichment", "EFFECT_MISMATCH"),
     ("conflicting_date", "DATE_CONFLICT"), ("wrong_request", "ORPHAN"),
     ("wrong_reservation", "BINDING_MISMATCH")],
)
def test_invalid_metadata_is_atomic(state, ready, case, error):
    current, binding, consumer = ready
    original = make_event(current)
    checkpoint = current.load_execution_checkpoint()
    if case != "no_original":
        checkpoint = current.ingest_execution_result(result(binding, consumer, [original]),
                                                     expected_revision=0)
    if case == "conflicting_date":
        event = dated(original, 6)
        checkpoint = current.ingest_execution_result(result(binding, consumer, [event], after=3),
                                                     expected_revision=checkpoint.revision)
    event = dated(original, checkpoint.stored_sequence + 3, fact="8" * 64)
    if case == "wrong_trade":
        event = dated(original, event.sequence, fact="8" * 64, trade_key_digest="2" * 64)
    elif case == "wrong_economics":
        event = dated(original, event.sequence, fact="8" * 64, trade_price="13")
    elif case == "normal_enrichment":
        event = dated(original, event.sequence, fact="8" * 64, metadata=False)
    elif case == "conflicting_date":
        event = dated(original, event.sequence, fact="8" * 64, date="20261108")
    elif case == "wrong_request":
        event = replace(event, request_key="missing")
    elif case == "wrong_reservation":
        event = replace(event, reservation_id="wrong")
    before = Path(state.pending.path).read_bytes()
    with pytest.raises(ValueError, match=error):
        current.ingest_execution_result(
            result(binding, consumer, [event], after=checkpoint.stored_sequence),
            expected_revision=checkpoint.revision,
        )
    assert Path(state.pending.path).read_bytes() == before
    assert current.load_execution_checkpoint() == checkpoint


def test_known_date_and_undated_normal_duplicates_preserve_known_date(state, ready):
    current, binding, consumer = ready
    original = dated(make_event(current), 3, metadata=False)
    saved = current.ingest_execution_result(result(binding, consumer, [original]), expected_revision=0)
    for seq, date, fact in [(6, None, "1" * 64), (8, "20261107", "2" * 64)]:
        event = dated(original, seq, date=date, metadata=False, fact=fact)
        saved = current.ingest_execution_result(result(binding, consumer, [event], after=saved.stored_sequence),
                                                expected_revision=saved.revision)
    assert GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding).load_execution_checkpoint() == saved
