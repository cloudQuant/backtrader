from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

QA = Path(__file__).resolve().parents[1]
COPY = QA / "candidate-copy"
REPO = Path(r"D:\source_code\backtrader")
sys.path.insert(0, str(COPY / "tests"))
sys.path.insert(0, str(COPY))

import test_ctp_simnow_settlement_consumer as base
from ctp_simnow_settlement_consumer import (
    CtpSimNowSettlementConsumerRejected,
    consume_current_settlement_readiness,
)


@pytest.fixture
def expected_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(base.runtime_config, "_require_private_config_security", lambda *a, **k: None)
    return base.expected_scope.__wrapped__(tmp_path)


def test_missing_attestor_and_missing_filter_readback_are_fail_closed(expected_scope):
    with pytest.raises(CtpSimNowSettlementConsumerRejected) as caught:
        consume_current_settlement_readiness(expected_scope.native_readiness, expected_scope)
    assert caught.value.reason == "settlement_attestor_required"
    evidence = replace(base._valid_evidence(expected_scope), request_filter_readback=None)
    with pytest.raises(CtpSimNowSettlementConsumerRejected) as caught:
        consume_current_settlement_readiness(
            expected_scope.native_readiness, expected_scope, attestor=base._FakeAttestor(evidence)
        )
    assert caught.value.reason == "settlement_request_filter_readback_missing_or_mismatched"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("sdk_wheel_sha256", "0" * 64, "settlement_sdk_pin_mismatch"),
        ("sdk_source_manifest_sha256", "0" * 64, "settlement_sdk_pin_mismatch"),
        ("sdk_pin_sha256", "0" * 64, "settlement_sdk_pin_mismatch"),
        ("request_filter_readback", (), "settlement_request_filter_readback_missing_or_mismatched"),
        ("explicit_request_filters", ("BrokerID",), "settlement_request_filter_readback_missing_or_mismatched"),
        ("callback_source", "OnRspQrySettlementInfoConfirmAction", "settlement_callback_source_missing_or_mismatched"),
        ("query_source_seal_sha256", "", "settlement_attestation_digest_missing_or_invalid"),
        ("query_source_history_sha256", "", "settlement_attestation_digest_missing_or_invalid"),
        ("terminal_callback_history_sha256", "", "settlement_attestation_digest_missing_or_invalid"),
        ("selected_pair_sha256", "0" * 64, "settlement_selected_pair_or_account_mismatch"),
        ("current_account_fingerprint_sha256", "0" * 64, "settlement_selected_pair_or_account_mismatch"),
        ("query_trading_day", "20260925", "settlement_current_trading_day_or_generation_mismatch"),
        ("current_trading_day", "20260925", "settlement_current_trading_day_or_generation_mismatch"),
        ("query_connection_generation", 2, "settlement_current_trading_day_or_generation_mismatch"),
        ("current_connection_generation", 2, "settlement_current_trading_day_or_generation_mismatch"),
        ("confirm_date", "20260925", "settlement_confirmation_row_scope_mismatch"),
    ],
)
def test_requested_binding_tampering_rejects(expected_scope, field, value, reason):
    evidence = replace(base._valid_evidence(expected_scope), **{field: value})
    with pytest.raises(CtpSimNowSettlementConsumerRejected) as caught:
        consume_current_settlement_readiness(
            expected_scope.native_readiness, expected_scope, attestor=base._FakeAttestor(evidence)
        )
    assert caught.value.reason == reason


def test_confirmdate_without_row_tradingday_is_only_shape_success(expected_scope):
    evidence = replace(base._valid_evidence(expected_scope), row_trading_day=None)
    receipt = consume_current_settlement_readiness(
        expected_scope.native_readiness, expected_scope, attestor=base._FakeAttestor(evidence)
    )
    assert receipt.consumer_contract_satisfied is True
    assert receipt.provider_source_trusted is False
    assert receipt.execution_authorized is False


def test_boolean_generation_is_currently_accepted_for_generation_one(expected_scope):
    evidence = replace(
        base._valid_evidence(expected_scope),
        query_connection_generation=True,
        current_connection_generation=True,
    )
    receipt = consume_current_settlement_readiness(
        expected_scope.native_readiness, expected_scope, attestor=base._FakeAttestor(evidence)
    )
    assert receipt.consumer_contract_satisfied is True
    assert receipt.provider_source_trusted is False
    assert receipt.execution_authorized is False


def test_boolean_native_error_code_is_currently_accepted_as_zero(expected_scope):
    evidence = replace(base._valid_evidence(expected_scope), error_code=False, submit_code=False)
    receipt = consume_current_settlement_readiness(
        expected_scope.native_readiness, expected_scope, attestor=base._FakeAttestor(evidence)
    )
    assert receipt.consumer_contract_satisfied is True
    assert receipt.provider_source_trusted is False
    assert receipt.execution_authorized is False


def test_main_runtime_snapshots_do_not_wire_consumer_contract():
    main_files = [
        COPY / "input-snapshots/main/ctp_simnow_managed_runtime.py",
        COPY / "input-snapshots/main/ctp_simnow_native_readiness.py",
        COPY / "input-snapshots/main/ctp_simulation_query_evidence.py",
    ]
    for path in main_files:
        source = path.read_text(encoding="utf-8")
        assert "consume_current_settlement_readiness" not in source
        assert "ctp_simnow_settlement_consumer" not in source


