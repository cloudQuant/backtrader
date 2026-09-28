"""Synthetic-only projection tests for partial I8 shutdown evidence."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backtrader_runtime import ctp_i8_oneshot_md_readonly as adapter
from backtrader_runtime.ctp_sdk_market_readonly import CtpSdkMarketReadOnlyError
from tests.unit.runtime import test_ctp_i8_oneshot_md_diagnostic as fake_support


class _Credentials:
    values = {
        "broker_id": fake_support.BROKER_ID,
        "user_id": fake_support.USER_ID,
        "password": fake_support.PASSWORD,
    }

    def require_credential(self, name: str) -> str:
        return self.values[name]


def _add_login_id_shapes(client_type: type[Any]) -> None:
    original_property = client_type.login_callback_diagnostic

    def _diagnostic(client: Any) -> Any:
        value = original_property.fget(client)
        return SimpleNamespace(
            callback_count=value.callback_count,
            disposition=value.disposition,
            request_id_relation=value.request_id_relation,
            response_error_status=value.response_error_status,
            broker_id_shape=SimpleNamespace(value="empty"),
            user_id_shape=SimpleNamespace(value="empty"),
            trading_day_shape=value.trading_day_shape,
            native_broker_id_shape=value.native_broker_id_shape,
            native_user_id_shape=value.native_user_id_shape,
        )

    client_type.login_callback_diagnostic = property(_diagnostic)


def _probe(client_type: type[Any], receipt_type: type[Any]) -> adapter.CtpI8OneShotMdObservation:
    return adapter.probe_i8_oneshot_md_readonly(
        admission=fake_support._i8_admission(),
        credential_source=_Credentials(),
        client_type=client_type,
        stop_receipt_type=receipt_type,
        expected_diagnostic_instrument=fake_support.INSTRUMENT,
        timeout_seconds=0.5,
    )


def test_i8_success_carries_complete_value_free_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter, "_AccountLease", fake_support._FakeLease)
    client_type, receipt_type = fake_support._fake_i8_sdk_types()
    _add_login_id_shapes(client_type)

    observation = _probe(client_type, receipt_type)

    evidence = observation.diagnostic_evidence
    assert type(evidence) is adapter.CtpI8OneShotMdDiagnosticEvidence
    assert evidence.evidence_level == "complete"
    assert evidence.close_state == "stop_returned"
    assert evidence.primary_error is None
    assert evidence.login_callback_count == "one"
    assert evidence.login_callback_disposition == "identity_unverified"
    assert evidence.login_request_id_relation == "zero"
    assert evidence.login_response_error_status == "zero"
    assert evidence.login_broker_id_shape == evidence.login_user_id_shape == "empty"
    assert evidence.login_trading_day_shape == "valid"
    assert evidence.native_broker_id_shape == evidence.native_user_id_shape == "empty"
    assert evidence.identity_unverified is True
    assert evidence.subscription_acknowledged is True
    assert evidence.matching_tick_observed is True
    assert evidence.same_trading_day_observed is True
    assert evidence.client_stop_returned is True
    assert evidence.native_join_pending is False
    assert fake_support.PASSWORD not in repr(evidence)
    assert fake_support.BROKER_ID not in repr(evidence)
    assert fake_support.USER_ID not in repr(evidence)
    assert fake_support.MD_FRONT not in repr(evidence)


def test_i8_uncertain_native_join_raises_with_partial_progress_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter, "_AccountLease", fake_support._FakeLease)
    monkeypatch.setattr(
        adapter,
        "_close_client",
        lambda *_args, **_kwargs: ("native_join_pending", True, False),
    )
    client_type, receipt_type = fake_support._fake_i8_sdk_types()
    _add_login_id_shapes(client_type)

    with pytest.raises(CtpSdkMarketReadOnlyError) as caught:
        _probe(client_type, receipt_type)

    error = caught.value
    evidence = error.i8_diagnostic_evidence
    assert type(evidence) is adapter.CtpI8OneShotMdDiagnosticEvidence
    assert evidence.evidence_level == "partial"
    assert evidence.close_state == "native_join_pending"
    assert evidence.primary_error is None
    assert evidence.login_callback_count == "one"
    assert evidence.login_callback_disposition == "identity_unverified"
    assert evidence.login_request_id_relation == "zero"
    assert evidence.login_response_error_status == "zero"
    assert evidence.login_broker_id_shape == evidence.login_user_id_shape == "empty"
    assert evidence.login_trading_day_shape == "valid"
    assert evidence.native_broker_id_shape == evidence.native_user_id_shape == "empty"
    assert evidence.identity_unverified is True
    assert evidence.subscription_acknowledged is True
    assert evidence.matching_tick_observed is True
    assert evidence.same_trading_day_observed is True
    assert evidence.client_stop_returned is True
    assert evidence.native_join_pending is True
    assert error.reason == "market_client_stop_failed"
    assert fake_support.PASSWORD not in repr(evidence)
    assert fake_support.BROKER_ID not in repr(evidence)
    assert fake_support.USER_ID not in repr(evidence)
    assert fake_support.MD_FRONT not in repr(evidence)
    assert fake_support.PASSWORD not in str(error)


def test_i8_unobserved_ack_and_tick_stay_nullable_on_partial_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter, "_AccountLease", fake_support._FakeLease)
    monkeypatch.setattr(
        adapter,
        "_close_client",
        lambda *_args, **_kwargs: ("native_join_pending", True, False),
    )
    client_type, receipt_type = fake_support._fake_i8_sdk_types()
    _add_login_id_shapes(client_type)
    client_type.subscribe = lambda _self, _instrument: -1

    with pytest.raises(CtpSdkMarketReadOnlyError) as caught:
        _probe(client_type, receipt_type)

    error = caught.value
    evidence = error.i8_diagnostic_evidence
    assert evidence.evidence_level == "partial"
    assert evidence.primary_error == "market_subscription_rejected"
    assert evidence.login_callback_count == "one"
    assert evidence.login_callback_disposition == "identity_unverified"
    assert evidence.identity_unverified is True
    assert evidence.subscription_acknowledged is None
    assert evidence.matching_tick_observed is None
    assert evidence.same_trading_day_observed is None
    assert evidence.client_stop_returned is True
    assert evidence.native_join_pending is True


def test_i8_probe_error_with_clean_shutdown_preserves_sanitized_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter, "_AccountLease", fake_support._FakeLease)
    monkeypatch.setattr(
        adapter,
        "_close_client",
        lambda *_args, **_kwargs: ("stop_returned", True, True),
    )
    client_type, receipt_type = fake_support._fake_i8_sdk_types()
    _add_login_id_shapes(client_type)
    client_type.subscribe = lambda _self, _instrument: -1

    with pytest.raises(CtpSdkMarketReadOnlyError) as caught:
        _probe(client_type, receipt_type)

    error = caught.value
    assert error.reason == "market_subscription_rejected"
    assert error.primary_reason == "market_subscription_rejected"
    assert error.close_state == "stop_returned"
    assert error.i8_diagnostic_evidence.primary_error == "market_subscription_rejected"


def test_i8_unknown_primary_error_is_redacted_even_when_join_is_uncertain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter, "_AccountLease", fake_support._FakeLease)
    monkeypatch.setattr(
        adapter,
        "_close_client",
        lambda *_args, **_kwargs: ("native_join_pending", True, False),
    )
    client_type, receipt_type = fake_support._fake_i8_sdk_types()
    _add_login_id_shapes(client_type)

    def _raise_sensitive_reason(_self: Any, _instrument: str) -> int:
        raise CtpSdkMarketReadOnlyError(fake_support.PASSWORD)

    client_type.subscribe = _raise_sensitive_reason

    with pytest.raises(CtpSdkMarketReadOnlyError) as caught:
        _probe(client_type, receipt_type)

    error = caught.value
    evidence = error.i8_diagnostic_evidence
    assert error.reason == "market_client_stop_failed"
    assert error.primary_reason == "unavailable"
    assert evidence.primary_error == "unavailable"
    assert evidence.close_state == "native_join_pending"
    assert fake_support.PASSWORD not in str(error)
    assert fake_support.PASSWORD not in repr(error)
    assert fake_support.PASSWORD not in repr(evidence)
