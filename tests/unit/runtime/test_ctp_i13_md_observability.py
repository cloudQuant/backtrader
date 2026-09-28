"""Offline fake-only contracts for I13 MD event projection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional

from backtrader_runtime.ctp_i13_md_observability import (
    I13AckTickOrder,
    I13AcknowledgementState,
    I13EventKind,
    I13MdEvent,
    I13NativeJoinState,
    I13PrimaryProbeReason,
    I13TickClassification,
    I13TickRejectCode,
    merge_i13_md_diagnostic_receipt,
    project_i13_md_observability,
)


def _event(
    kind: I13EventKind,
    tick: Optional[int] = None,
    code: Optional[I13TickRejectCode] = None,
    elapsed: Optional[int] = None,
) -> I13MdEvent:
    return I13MdEvent(
        kind=kind,
        tick_ordinal=tick,
        rejection_code=code,
        elapsed_ms=elapsed,
    )


def test_no_tick_is_reported_only_after_observation_window_closes() -> None:
    incomplete = project_i13_md_observability(())
    closed = project_i13_md_observability((_event(I13EventKind.OBSERVATION_WINDOW_CLOSED),))

    assert incomplete.tick_classification is I13TickClassification.UNKNOWN
    assert incomplete.acknowledgement_state is I13AcknowledgementState.UNKNOWN
    assert closed.tick_classification is I13TickClassification.NO_TICK_OBSERVED
    assert closed.acknowledgement_state is I13AcknowledgementState.NOT_OBSERVED_AT_WINDOW_CLOSE
    assert closed.primary_probe_reason is I13PrimaryProbeReason.MARKET_OBSERVATION_INCOMPLETE


def test_sdk_rejection_is_distinct_from_adapter_rejection_and_keeps_fixed_reason() -> None:
    result = project_i13_md_observability(
        (
            _event(I13EventKind.TICK_ARRIVED, 1),
            _event(
                I13EventKind.TICK_SDK_REJECTED,
                1,
                I13TickRejectCode.BEFORE_ACK,
            ),
            _event(I13EventKind.OBSERVATION_WINDOW_CLOSED),
        ),
        reported_primary_reason="market_probe_failed",
    )

    public = result.as_public_dict()
    assert result.tick_classification is I13TickClassification.SDK_REJECTED
    assert result.sdk_rejected_tick_count == 1
    assert result.adapter_rejected_tick_count == 0
    assert result.primary_probe_reason is I13PrimaryProbeReason.MARKET_PROBE_FAILED
    assert "BEFORE_ACK" not in repr(public)
    assert "front" not in repr(public)


def test_adapter_rejection_is_value_free_and_classifies_day_mismatch() -> None:
    result = project_i13_md_observability(
        (
            _event(I13EventKind.SUBSCRIPTION_ACKNOWLEDGED),
            _event(I13EventKind.TICK_ARRIVED, 1),
            _event(
                I13EventKind.TICK_ADAPTER_REJECTED,
                1,
                I13TickRejectCode.TRADING_DAY_MISMATCH,
            ),
            _event(I13EventKind.OBSERVATION_WINDOW_CLOSED),
        )
    )

    public_text = repr(result.as_public_dict())
    assert result.tick_classification is I13TickClassification.ADAPTER_REJECTED
    assert result.ack_tick_order is I13AckTickOrder.ACK_BEFORE_ALL_TICKS
    assert result.same_trading_day_observed is None
    assert "TRADING_DAY_MISMATCH" not in public_text
    assert "TradingDay" not in public_text


def test_same_day_confirmation_cannot_contradict_same_tick_rejection() -> None:
    contradictory_traces = (
        (
            _event(I13EventKind.TICK_ARRIVED, 1),
            _event(
                I13EventKind.TICK_ADAPTER_REJECTED,
                1,
                I13TickRejectCode.TRADING_DAY_MISMATCH,
            ),
            _event(I13EventKind.TICK_SAME_TRADING_DAY_CONFIRMED, 1),
        ),
        (
            _event(I13EventKind.TICK_ARRIVED, 1),
            _event(I13EventKind.TICK_SDK_REJECTED, 1, I13TickRejectCode.BEFORE_ACK),
            _event(I13EventKind.TICK_SAME_TRADING_DAY_CONFIRMED, 1),
        ),
    )
    separate_ordinals = project_i13_md_observability(
        (
            _event(I13EventKind.TICK_ARRIVED, 1),
            _event(
                I13EventKind.TICK_ADAPTER_REJECTED,
                1,
                I13TickRejectCode.TRADING_DAY_MISMATCH,
            ),
            _event(I13EventKind.TICK_ARRIVED, 2),
            _event(I13EventKind.TICK_SAME_TRADING_DAY_CONFIRMED, 2),
        )
    )

    for events in contradictory_traces:
        result = project_i13_md_observability(events)
        assert result.evidence_integrity.value == "invalid"
        assert result.same_trading_day_observed is None
    assert separate_ordinals.evidence_integrity.value == "valid"
    assert separate_ordinals.same_trading_day_observed is True


def test_ack_tick_reordering_is_explicit_for_both_callback_orders() -> None:
    tick_first = project_i13_md_observability(
        (
            _event(I13EventKind.TICK_ARRIVED, 1),
            _event(I13EventKind.TICK_SDK_REJECTED, 1, I13TickRejectCode.BEFORE_ACK),
            _event(I13EventKind.SUBSCRIPTION_ACKNOWLEDGED),
            _event(I13EventKind.OBSERVATION_WINDOW_CLOSED),
        )
    )
    ack_first = project_i13_md_observability(
        (
            _event(I13EventKind.SUBSCRIPTION_ACKNOWLEDGED),
            _event(I13EventKind.TICK_ARRIVED, 1),
            _event(I13EventKind.TICK_ACCEPTED, 1),
            _event(I13EventKind.TICK_SAME_TRADING_DAY_CONFIRMED, 1),
            _event(I13EventKind.OBSERVATION_WINDOW_CLOSED),
        )
    )

    assert tick_first.ack_tick_order is I13AckTickOrder.TICK_BEFORE_ACK
    assert tick_first.tick_classification is I13TickClassification.SDK_REJECTED
    assert ack_first.ack_tick_order is I13AckTickOrder.ACK_BEFORE_ALL_TICKS
    assert ack_first.tick_classification is I13TickClassification.TICK_ACCEPTED
    assert ack_first.same_trading_day_observed is True


def test_join_pending_does_not_replace_unknown_primary_probe_reason() -> None:
    result = project_i13_md_observability(
        (
            _event(I13EventKind.LOGIN_IDENTITY_UNVERIFIED),
            _event(I13EventKind.SUBSCRIPTION_ACKNOWLEDGED),
            _event(I13EventKind.NATIVE_JOIN_PENDING),
            _event(I13EventKind.OBSERVATION_WINDOW_CLOSED),
        ),
        reported_primary_reason="native_join_pending",
    )

    assert result.native_join_state is I13NativeJoinState.PENDING_OBSERVED
    assert result.primary_probe_reason is I13PrimaryProbeReason.UNKNOWN
    assert result.tick_classification is I13TickClassification.NO_TICK_OBSERVED
    assert result.acknowledgement_state is I13AcknowledgementState.ACKNOWLEDGED


def test_contradictory_tick_or_malformed_event_fails_closed_without_reflection() -> None:
    contradictory = project_i13_md_observability(
        (
            _event(I13EventKind.TICK_ARRIVED, 1),
            _event(I13EventKind.TICK_ACCEPTED, 1),
            _event(
                I13EventKind.TICK_ADAPTER_REJECTED,
                1,
                I13TickRejectCode.INVALID_VOLUME,
            ),
        )
    )
    malformed = project_i13_md_observability(("password-or-front-value",))

    assert contradictory.tick_classification is I13TickClassification.EVIDENCE_INCONSISTENT
    assert contradictory.evidence_integrity.value == "invalid"
    assert malformed.evidence_integrity.value == "invalid"
    assert "password-or-front-value" not in repr(malformed.as_public_dict())


class _SdkCode(str, Enum):
    ACCEPTED = "accepted"
    EQUAL = "equal"
    EXACT_MATCH = "exact_match"
    IDENTITY_UNVERIFIED = "identity_unverified"
    NONE = "none"
    NOT_OBSERVED = "not_observed"
    NONEMPTY_TERMINATED = "nonempty_terminated"
    VALID = "valid"
    ZERO = "zero"


@dataclass(frozen=True)
class MdLoginCallbackDiagnostic:
    callback_count: int
    disposition: _SdkCode
    request_id_relation: _SdkCode
    response_error_status: _SdkCode
    broker_id_shape: _SdkCode
    user_id_shape: _SdkCode
    trading_day_shape: _SdkCode
    native_broker_id_shape: _SdkCode
    native_user_id_shape: _SdkCode


@dataclass(frozen=True)
class MdOneShotDiagnosticReceipt:
    login_callback: MdLoginCallbackDiagnostic
    terminal: bool
    terminal_reason: Optional[str]
    subscription_submitted: bool
    subscription_response_error_status: _SdkCode
    subscription_acknowledged: bool
    first_tick_pending: bool
    first_tick_received: bool


def _sdk_receipt(
    *,
    callback_count: int = 0,
    disposition: _SdkCode = _SdkCode.NONE,
    terminal: bool = False,
    terminal_reason: Optional[str] = None,
    subscription_submitted: bool = False,
    subscription_status: _SdkCode = _SdkCode.NOT_OBSERVED,
    subscription_acknowledged: bool = False,
    first_tick_pending: bool = False,
    first_tick_received: bool = False,
) -> MdOneShotDiagnosticReceipt:
    callback = MdLoginCallbackDiagnostic(
        callback_count=callback_count,
        disposition=disposition,
        request_id_relation=(_SdkCode.EQUAL if callback_count else _SdkCode.NOT_OBSERVED),
        response_error_status=(_SdkCode.ZERO if callback_count else _SdkCode.NOT_OBSERVED),
        broker_id_shape=(_SdkCode.EXACT_MATCH if callback_count else _SdkCode.NOT_OBSERVED),
        user_id_shape=(_SdkCode.EXACT_MATCH if callback_count else _SdkCode.NOT_OBSERVED),
        trading_day_shape=(_SdkCode.VALID if callback_count else _SdkCode.NOT_OBSERVED),
        native_broker_id_shape=(
            _SdkCode.NONEMPTY_TERMINATED if callback_count else _SdkCode.NOT_OBSERVED
        ),
        native_user_id_shape=(
            _SdkCode.NONEMPTY_TERMINATED if callback_count else _SdkCode.NOT_OBSERVED
        ),
    )
    return MdOneShotDiagnosticReceipt(
        login_callback=callback,
        terminal=terminal,
        terminal_reason=terminal_reason,
        subscription_submitted=subscription_submitted,
        subscription_response_error_status=subscription_status,
        subscription_acknowledged=subscription_acknowledged,
        first_tick_pending=first_tick_pending,
        first_tick_received=first_tick_received,
    )


def test_receipt_pending_tick_and_missing_native_callback_stay_unknown_or_false() -> None:
    absent = merge_i13_md_diagnostic_receipt(None, ())
    pending = merge_i13_md_diagnostic_receipt(
        _sdk_receipt(
            callback_count=1,
            disposition=_SdkCode.IDENTITY_UNVERIFIED,
            subscription_submitted=True,
            first_tick_pending=True,
        ),
        (_event(I13EventKind.OBSERVATION_WINDOW_CLOSED),),
    )
    no_callback = merge_i13_md_diagnostic_receipt(
        _sdk_receipt(),
        (
            _event(I13EventKind.OBSERVATION_WINDOW_CLOSED),
            _event(I13EventKind.NATIVE_JOIN_PENDING),
        ),
    )

    assert absent.sdk_receipt.evidence_integrity.value == "valid"
    assert absent.sdk_receipt.first_tick_received is None
    assert pending.sdk_receipt.first_tick_pending is True
    assert pending.sdk_receipt.first_tick_received is False
    assert (
        pending.adapter_observability.tick_classification is I13TickClassification.NO_TICK_OBSERVED
    )
    assert no_callback.sdk_receipt.login_callback.callback_count == 0
    assert no_callback.sdk_receipt.first_tick_received is False
    assert (
        no_callback.adapter_observability.tick_classification
        is I13TickClassification.NO_TICK_OBSERVED
    )
    assert (
        no_callback.adapter_observability.native_join_state is I13NativeJoinState.PENDING_OBSERVED
    )


def test_missing_receipt_stays_unknown_while_explicit_no_tick_conflicts_with_arrival() -> None:
    adapter_tick = (
        _event(I13EventKind.TICK_ARRIVED, 1),
        _event(I13EventKind.TICK_ACCEPTED, 1),
    )
    missing_receipt = merge_i13_md_diagnostic_receipt(None, adapter_tick)
    explicit_no_tick = merge_i13_md_diagnostic_receipt(_sdk_receipt(), adapter_tick)

    assert missing_receipt.evidence_integrity.value == "valid"
    assert missing_receipt.sdk_receipt.first_tick_received is None
    assert (
        missing_receipt.adapter_observability.tick_classification
        is I13TickClassification.TICK_ACCEPTED
    )
    assert explicit_no_tick.evidence_integrity.value == "invalid"
    assert explicit_no_tick.sdk_receipt.first_tick_received is False


def test_sdk_tick_receipt_does_not_promote_adapter_rejection_or_trading_day() -> None:
    merged = merge_i13_md_diagnostic_receipt(
        _sdk_receipt(
            callback_count=1,
            disposition=_SdkCode.ACCEPTED,
            terminal=True,
            terminal_reason="diagnostic_complete",
            subscription_submitted=True,
            subscription_status=_SdkCode.ZERO,
            subscription_acknowledged=True,
            first_tick_received=True,
        ),
        (
            _event(I13EventKind.SUBSCRIPTION_ACKNOWLEDGED),
            _event(I13EventKind.TICK_ARRIVED, 1),
            _event(
                I13EventKind.TICK_ADAPTER_REJECTED,
                1,
                I13TickRejectCode.TRADING_DAY_MISMATCH,
            ),
            _event(I13EventKind.OBSERVATION_WINDOW_CLOSED),
        ),
    )

    assert merged.evidence_integrity.value == "valid"
    assert merged.sdk_receipt.first_tick_received is True
    assert (
        merged.adapter_observability.tick_classification is I13TickClassification.ADAPTER_REJECTED
    )
    assert merged.adapter_observability.same_trading_day_observed is None
    assert merged.adapter_observability.accepted_tick_count == 0


def test_join_pending_remains_separate_from_sdk_and_adapter_tick_facts() -> None:
    merged = merge_i13_md_diagnostic_receipt(
        _sdk_receipt(
            callback_count=1,
            disposition=_SdkCode.ACCEPTED,
            terminal=True,
            terminal_reason="diagnostic_complete",
            subscription_submitted=True,
            subscription_status=_SdkCode.ZERO,
            subscription_acknowledged=True,
            first_tick_received=True,
        ),
        (
            _event(I13EventKind.SUBSCRIPTION_ACKNOWLEDGED),
            _event(I13EventKind.TICK_ARRIVED, 1),
            _event(I13EventKind.TICK_ACCEPTED, 1),
            _event(I13EventKind.TICK_SAME_TRADING_DAY_CONFIRMED, 1),
            _event(I13EventKind.NATIVE_JOIN_PENDING),
        ),
    )

    assert merged.sdk_receipt.terminal_reason == "diagnostic_complete"
    assert merged.adapter_observability.tick_classification is I13TickClassification.TICK_ACCEPTED
    assert merged.adapter_observability.native_join_state is I13NativeJoinState.PENDING_OBSERVED
    assert "session_success" not in merged.as_public_dict()


def test_receipt_with_unknown_or_secret_bearing_fields_fails_closed() -> None:
    receipt = _sdk_receipt()
    object.__setattr__(receipt, "password", "private-password")
    merged = merge_i13_md_diagnostic_receipt(receipt, ())

    assert merged.sdk_receipt.evidence_integrity.value == "invalid"
    assert merged.evidence_integrity.value == "invalid"
    assert "private-password" not in repr(merged.as_public_dict())


def test_zero_login_callbacks_cannot_carry_callback_derived_shape_evidence() -> None:
    receipt = _sdk_receipt()
    contradictory_callback = replace(
        receipt.login_callback,
        broker_id_shape=_SdkCode.EXACT_MATCH,
    )
    contradictory_receipt = replace(receipt, login_callback=contradictory_callback)
    merged = merge_i13_md_diagnostic_receipt(contradictory_receipt, ())
    absent = merge_i13_md_diagnostic_receipt(None, ())
    explicit_no_tick = merge_i13_md_diagnostic_receipt(_sdk_receipt(), ())

    assert merged.evidence_integrity.value == "invalid"
    assert merged.sdk_receipt.login_callback is None
    assert absent.sdk_receipt.first_tick_received is None
    assert explicit_no_tick.sdk_receipt.first_tick_received is False
