"""Independent fake-only adversarial settlement evidence cases."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import test_ctp_simnow_td_trading_readiness as base
from backtrader_runtime import config as runtime_config
import backtrader_runtime.ctp_native_shutdown as ctp_native_shutdown_module
from backtrader_runtime.ctp_simnow_td_trading_readiness import (
    CtpSimNowTdTradingReadinessError,
    verify_ctp_simnow_td_trading_readiness,
)


@pytest.fixture(autouse=True)
def _allow_synthetic_private_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_config, "_require_private_config_security", lambda *a, **k: None)
    monkeypatch.setattr(
        ctp_native_shutdown_module,
        "_native_stop_receipt_type",
        lambda: base._FakeNativeStopReceipt,
    )


class _MissingFieldVerifier(base._FakeSettlementEvidenceVerifier):
    def __init__(self, field: str) -> None:
        super().__init__()
        self.field = field

    def verify_current(self, client: Any, result: Any):
        evidence = super().verify_current(client, result)
        evidence._public.pop(self.field, None)
        return evidence


def _assert_rejected_no_write(client: Any, reason: str) -> None:
    assert client.write_method_calls == 0
    assert client.counts["settlement_confirm"] == 0
    assert client.counts["order_insert"] == 0
    assert client.counts["order_action"] == 0
    assert reason


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("request_filters_sha256", "managed_simnow_td_settlement_evidence_shape_invalid"),
        (
            "terminal_callback_history_sha256",
            "managed_simnow_td_settlement_evidence_shape_invalid",
        ),
        ("connection_generation", "managed_simnow_td_settlement_evidence_shape_invalid"),
        ("evidence_sha256", "managed_simnow_td_settlement_evidence_verification_failed"),
    ],
)
def test_missing_filter_history_generation_or_sdk_digest_rejects_before_any_write(
    tmp_path, field: str, reason: str
) -> None:
    client, selection, config, prior = base._inputs(tmp_path)
    with pytest.raises(CtpSimNowTdTradingReadinessError) as raised:
        verify_ctp_simnow_td_trading_readiness(
            client,
            selection,
            config,
            native_readiness=prior,
            settlement_evidence_verifier=_MissingFieldVerifier(field),
            failure_cleanup=lambda: None,
        )
    assert raised.value.reason == reason
    _assert_rejected_no_write(client, reason)


def test_missing_sdk_source_manifest_digest_rejects_before_settlement_query(tmp_path) -> None:
    client, selection, config, prior = base._inputs(tmp_path)
    verifier = SimpleNamespace(source_manifest_sha256=None, verify_current=lambda *_: None)
    with pytest.raises(CtpSimNowTdTradingReadinessError) as raised:
        verify_ctp_simnow_td_trading_readiness(
            client,
            selection,
            config,
            native_readiness=prior,
            settlement_evidence_verifier=verifier,
            failure_cleanup=lambda: None,
        )
    assert raised.value.reason == "managed_simnow_td_settlement_evidence_source_mismatch"
    assert client.verify_calls == []
    _assert_rejected_no_write(client, raised.value.reason)


def test_sdk_public_seal_failure_is_delegated_to_injected_verifier_contract(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, selection, config, prior = base._inputs(tmp_path)

    def reject_unsealed_publication(self):
        raise ValueError("fake SDK seal check rejected")

    monkeypatch.setattr(
        base.CtpSettlementConfirmationEvidence,
        "as_public_dict",
        reject_unsealed_publication,
    )
    verifier = base._FakeSettlementEvidenceVerifier()
    with pytest.raises(CtpSimNowTdTradingReadinessError) as raised:
        verify_ctp_simnow_td_trading_readiness(
            client,
            selection,
            config,
            native_readiness=prior,
            settlement_evidence_verifier=verifier,
            failure_cleanup=lambda: None,
        )
    assert raised.value.reason == "managed_simnow_td_settlement_evidence_verification_failed"
    assert verifier.calls == 1
    _assert_rejected_no_write(client, raised.value.reason)


def test_confirm_date_only_correct_looking_row_with_wrong_day_rejects_before_verifier(
    tmp_path,
) -> None:
    client, selection, config, prior = base._inputs(tmp_path)
    client.record.records = (
        {"BrokerID": base.BROKER_ID, "InvestorID": base.USER_ID, "ConfirmDate": "20260923"},
    )
    verifier = base._FakeSettlementEvidenceVerifier()
    with pytest.raises(CtpSimNowTdTradingReadinessError) as raised:
        verify_ctp_simnow_td_trading_readiness(
            client,
            selection,
            config,
            native_readiness=prior,
            settlement_evidence_verifier=verifier,
            failure_cleanup=lambda: None,
        )
    assert raised.value.reason == "managed_simnow_td_settlement_record_identity_mismatch"
    assert client.verify_calls == [5.0]
    assert verifier.calls == 0
    _assert_rejected_no_write(client, raised.value.reason)
