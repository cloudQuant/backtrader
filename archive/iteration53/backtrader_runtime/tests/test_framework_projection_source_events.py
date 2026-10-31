"""Local-only source-event receipts used by managed Broker projection."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from typing import Optional

import pytest

from backtrader_runtime.framework_projection import (
    FrameworkProjectionJournal,
    FrameworkProjectionRecoveryError,
)


_SCOPE = "scope.fixture.local"
_INCARNATION = "a" * 32
_SESSION = "session.fixture.1"
_FINGERPRINT = "b" * 64


def _event(
    sequence: int,
    *,
    intent_id: str = "intent.fixture",
    event_id: Optional[str] = None,
    quantity: str = "1",
    average: Optional[str] = "100",
    commission: Optional[str] = "0.05",
):
    return SimpleNamespace(
        sequence=sequence,
        event_id=event_id or "event." + str(sequence),
        intent_id=intent_id,
        scope_key=_SCOPE,
        event_type="provider_observation",
        state=SimpleNamespace(value="PARTIALLY_FILLED"),
        created_at_ns=sequence + 100,
        journal_incarnation_id=_INCARNATION,
        payload={
            "provider_order_id": "provider.fixture",
            "filled_quantity": quantity,
            "average_price": average,
            "cumulative_commission": commission,
            "reason_code": None,
            "source": "provider",
        },
    )


def _claim(journal: FrameworkProjectionJournal, event, session: str = _SESSION):
    return journal.claim_source_event(
        event=event,
        session_id=session,
        expected_scope_key=_SCOPE,
        canonical_fingerprint=_FINGERPRINT,
    )


def test_source_event_receipt_is_idempotent_and_restart_scoped(tmp_path) -> None:
    journal = FrameworkProjectionJournal(tmp_path)
    try:
        first = _event(1)
        claim = _claim(journal, first)
        assert claim is not None
        assert journal.validate_source_event(claim)
        journal.complete_source_event(claim)
        assert (
            journal.claim_source_event(
                event=first,
                session_id=_SESSION,
                expected_scope_key=_SCOPE,
                canonical_fingerprint=_FINGERPRINT,
            )
            is None
        )

        second = _event(2, quantity="2", average="110", commission="0.11")
        next_claim = _claim(journal, second)
        assert next_claim is not None
        journal.complete_source_event(next_claim)

        # A fresh framework session rebuilds its empty Broker from the same
        # immutable event stream; the existing session cannot replay old seq.
        restart_claim = _claim(journal, first, session="session.fixture.2")
        assert restart_claim is not None
        journal.complete_source_event(restart_claim)
        with pytest.raises(FrameworkProjectionRecoveryError, match="backwards"):
            _claim(journal, _event(1, event_id="different.event"))
    finally:
        journal.close()


def test_source_event_identity_payload_and_missing_fill_evidence_fail_closed(tmp_path) -> None:
    journal = FrameworkProjectionJournal(tmp_path)
    try:
        first = _event(1)
        claim = _claim(journal, first)
        assert claim is not None
        journal.complete_source_event(claim)

        changed = _event(1, event_id=first.event_id, average="101")
        with pytest.raises(FrameworkProjectionRecoveryError, match="reused"):
            _claim(journal, changed)

        with pytest.raises(FrameworkProjectionRecoveryError, match="lacks price"):
            _claim(
                journal,
                _event(2, quantity="2", average=None, commission="0.11"),
            )
        with pytest.raises(FrameworkProjectionRecoveryError, match="lacks price"):
            _claim(
                journal,
                _event(2, quantity="2", average="110", commission=None),
            )
    finally:
        journal.close()


def test_source_event_completion_rolls_back_without_advancing_high_water(tmp_path) -> None:
    journal = FrameworkProjectionJournal(tmp_path)
    try:
        claim = _claim(journal, _event(1))
        assert claim is not None
        invalid = replace(claim, claim_token="c" * 32)
        with pytest.raises(FrameworkProjectionRecoveryError, match="not active"):
            journal.complete_source_event(invalid)
        assert journal.validate_source_event(claim)
        journal.complete_source_event(claim)
        assert _claim(journal, _event(2)) is not None
    finally:
        journal.close()


def test_source_event_claim_race_has_one_winner_across_journal_handles(tmp_path) -> None:
    first = FrameworkProjectionJournal(tmp_path)
    second = FrameworkProjectionJournal(tmp_path)
    event = _event(1)
    try:

        def attempt(journal: FrameworkProjectionJournal):
            try:
                return _claim(journal, event)
            except FrameworkProjectionRecoveryError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, (first, second)))
        assert sum(result is not None for result in results) == 1
        winner = next(result for result in results if result is not None)
        assert first.validate_source_event(winner) or second.validate_source_event(winner)
    finally:
        first.close()
        second.close()


def test_source_stream_high_water_is_scope_global_across_intents(tmp_path) -> None:
    journal = FrameworkProjectionJournal(tmp_path)
    try:
        first = _claim(journal, _event(1, intent_id="intent.a"))
        assert first is not None
        journal.complete_source_event(first)
        later = _claim(journal, _event(3, intent_id="intent.b"))
        assert later is not None
        journal.complete_source_event(later)
        with pytest.raises(FrameworkProjectionRecoveryError, match="backwards"):
            _claim(journal, _event(2, intent_id="intent.a"))
    finally:
        journal.close()


def test_fenced_source_session_rejects_future_events(tmp_path) -> None:
    journal = FrameworkProjectionJournal(tmp_path)
    try:
        journal.fence_source_session(
            scope_key=_SCOPE,
            journal_incarnation_id=_INCARNATION,
            session_id=_SESSION,
            reason="fixture_failure",
        )
        with pytest.raises(FrameworkProjectionRecoveryError, match="fenced"):
            _claim(journal, _event(1))
    finally:
        journal.close()


def test_validate_source_event_rejects_a_receipt_after_session_fence(tmp_path) -> None:
    journal = FrameworkProjectionJournal(tmp_path)
    try:
        claim = _claim(journal, _event(1))
        assert claim is not None
        journal.fence_source_session(
            scope_key=_SCOPE,
            journal_incarnation_id=_INCARNATION,
            session_id=_SESSION,
            reason="fixture_failure",
        )
        assert journal.validate_source_event(claim) is False
    finally:
        journal.close()


def test_consumed_non_projection_event_persists_cursor_idempotently(tmp_path) -> None:
    journal = FrameworkProjectionJournal(tmp_path)
    lifecycle = SimpleNamespace(
        sequence=1,
        event_id="event.intent-recorded",
        intent_id="intent.a",
        scope_key=_SCOPE,
        event_type="intent_recorded",
        state="PENDING_ADMISSION",
        created_at_ns=101,
        journal_incarnation_id=_INCARNATION,
        payload={"payload_sha256": "c" * 64},
    )
    try:
        assert (
            journal.source_high_water(
                scope_key=_SCOPE,
                journal_incarnation_id=_INCARNATION,
                session_id=_SESSION,
            )
            == 0
        )
        assert (
            journal.advance_source_event(
                event=lifecycle,
                session_id=_SESSION,
                expected_scope_key=_SCOPE,
            )
            is True
        )
        assert (
            journal.advance_source_event(
                event=lifecycle,
                session_id=_SESSION,
                expected_scope_key=_SCOPE,
            )
            is False
        )
        assert (
            journal.source_high_water(
                scope_key=_SCOPE,
                journal_incarnation_id=_INCARNATION,
                session_id=_SESSION,
            )
            == 1
        )
        changed = SimpleNamespace(**{**vars(lifecycle), "payload": {"payload_sha256": "d" * 64}})
        with pytest.raises(FrameworkProjectionRecoveryError, match="reused"):
            journal.advance_source_event(
                event=changed,
                session_id=_SESSION,
                expected_scope_key=_SCOPE,
            )
    finally:
        journal.close()
