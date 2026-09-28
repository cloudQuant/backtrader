"""Offline-only consumer contract tests. No SDK, native library, provider or network."""
from __future__ import annotations

import hashlib
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

CANDIDATE = Path(__file__).resolve().parents[1]
REPO = Path(r"D:\source_code\backtrader")
TEST_FIXTURES = REPO / "tests" / "unit" / "runtime"
sys.path.insert(0, str(CANDIDATE))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TEST_FIXTURES))

import backtrader_runtime.config as runtime_config
from backtrader_runtime.ctp_simnow_managed_runtime import CtpSimNowNativeReadiness
from test_ctp_simnow_native_readiness import _selection

from ctp_simnow_settlement_consumer import (
    CtpSimNowSettlementConsumerRejected,
    CtpSimNowSettlementExpectedScope,
    CtpSimNowSettlementQueryAttestation,
    SDK_DISTRIBUTION,
    SDK_SOURCE_MANIFEST_SHA256,
    SDK_VERSION,
    SDK_WHEEL_SHA256,
    _identifier_sha256,
    _sdk_pin_sha256,
    consume_current_settlement_readiness,
)

BROKER = "9999"
INVESTOR = "offline-native-test"
TRADING_DAY = "20260924"


@pytest.fixture(autouse=True)
def _allow_synthetic_private_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_config, "_require_private_config_security", lambda *a, **k: None)


@pytest.fixture
def expected_scope(tmp_path: Path) -> CtpSimNowSettlementExpectedScope:
    selection = _selection(tmp_path)
    readiness = CtpSimNowNativeReadiness(
        config_digest=selection.config_digest,
        registration_digest=selection.execution_registration.digest,
        account_fingerprint_sha256=selection.execution_registration.account_fingerprint_sha256,
        md_front=selection.execution_registration.md_front,
        td_front=selection.execution_registration.td_front,
        td_ready=True,
        md_ready=True,
    )
    return CtpSimNowSettlementExpectedScope(
        selection=selection,
        native_readiness=readiness,
        broker_id=BROKER,
        investor_id=INVESTOR,
        trading_day=TRADING_DAY,
        connection_generation=1,
    )


class _FakeAttestor:
    def __init__(self, evidence: Any) -> None:
        self.evidence = evidence
        self.calls = 0
        self.write_calls = 0

    def attest_current_settlement(self, _expected: CtpSimNowSettlementExpectedScope):
        self.calls += 1
        return self.evidence


def _valid_evidence(expected: CtpSimNowSettlementExpectedScope) -> CtpSimNowSettlementQueryAttestation:
    return CtpSimNowSettlementQueryAttestation(
        sdk_distribution=SDK_DISTRIBUTION,
        sdk_version=SDK_VERSION,
        sdk_wheel_sha256=SDK_WHEEL_SHA256,
        sdk_source_manifest_sha256=SDK_SOURCE_MANIFEST_SHA256,
        sdk_pin_sha256=_sdk_pin_sha256(),
        selected_pair_sha256=expected.selected_pair_sha256,
        account_fingerprint_sha256=expected.selection.execution_registration.account_fingerprint_sha256,
        request_type="settlement_confirmation",
        request_id=41,
        complete=True,
        is_last_seen=True,
        timed_out=False,
        unsupported=False,
        error_code=0,
        submit_code=0,
        late_callback_count=0,
        request_intent_filters=(("BrokerID", BROKER), ("InvestorID", INVESTOR)),
        request_filter_readback=(("BrokerID", BROKER), ("InvestorID", INVESTOR)),
        explicit_request_filters=(),
        query_source_seal_sha256="a" * 64,
        query_source_history_sha256="b" * 64,
        callback_source="OnRspQrySettlementInfoConfirm",
        terminal_callback_records_sha256="c" * 64,
        terminal_callback_history_sha256="d" * 64,
        query_trading_day=expected.trading_day,
        query_connection_generation=expected.connection_generation,
        current_trading_day=expected.trading_day,
        current_connection_generation=expected.connection_generation,
        current_account_fingerprint_sha256=expected.selection.execution_registration.account_fingerprint_sha256,
        record_count=1,
        row_broker_id_sha256=_identifier_sha256(BROKER),
        row_investor_id_sha256=_identifier_sha256(INVESTOR),
        confirm_date=expected.trading_day,
        # Native CThostFtdcSettlementInfoConfirmField has ConfirmDate, not TradingDay.
        row_trading_day=None,
        evidence_sha256="e" * 64,
    )


def test_missing_attestor_rejects_by_default_before_any_provider_call(expected_scope):
    with pytest.raises(CtpSimNowSettlementConsumerRejected) as rejected:
        consume_current_settlement_readiness(expected_scope.native_readiness, expected_scope)
    assert rejected.value.reason == "settlement_attestor_required"


def test_confirm_date_only_row_is_accepted_as_shape_but_never_authorizes_execution(expected_scope):
    attestor = _FakeAttestor(_valid_evidence(expected_scope))
    receipt = consume_current_settlement_readiness(
        expected_scope.native_readiness, expected_scope, attestor=attestor
    )
    assert receipt.consumer_contract_satisfied is True
    assert receipt.provider_source_trusted is False
    assert receipt.execution_authorized is False
    assert receipt.trading_day == TRADING_DAY
    assert attestor.calls == 1
    assert attestor.write_calls == 0


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("sdk_wheel_sha256", "f" * 64, "settlement_sdk_pin_mismatch"),
        ("sdk_source_manifest_sha256", "f" * 64, "settlement_sdk_pin_mismatch"),
        ("sdk_pin_sha256", "f" * 64, "settlement_sdk_pin_mismatch"),
        ("query_source_seal_sha256", "", "settlement_attestation_digest_missing_or_invalid"),
        ("query_source_history_sha256", "", "settlement_attestation_digest_missing_or_invalid"),
        ("terminal_callback_history_sha256", "", "settlement_attestation_digest_missing_or_invalid"),
        ("callback_source", "", "settlement_callback_source_missing_or_mismatched"),
        ("callback_source", "OnRspQrySettlementInfoConfirmAction", "settlement_callback_source_missing_or_mismatched"),
        ("request_intent_filters", (), "settlement_request_filter_readback_missing_or_mismatched"),
        ("request_filter_readback", (), "settlement_request_filter_readback_missing_or_mismatched"),
        ("request_filter_readback", (("BrokerID", BROKER),), "settlement_request_filter_readback_missing_or_mismatched"),
        ("request_filter_readback", (("BrokerID", BROKER), ("InvestorID", INVESTOR), ("InstrumentID", "rb2701")), "settlement_request_filter_readback_missing_or_mismatched"),
        ("explicit_request_filters", ("BrokerID",), "settlement_request_filter_readback_missing_or_mismatched"),
        ("query_trading_day", "20260925", "settlement_current_trading_day_or_generation_mismatch"),
        ("current_trading_day", "20260925", "settlement_current_trading_day_or_generation_mismatch"),
        ("query_connection_generation", 2, "settlement_current_trading_day_or_generation_mismatch"),
        ("current_connection_generation", 2, "settlement_current_trading_day_or_generation_mismatch"),
        ("query_connection_generation", True, "settlement_current_trading_day_or_generation_mismatch"),
        ("current_connection_generation", True, "settlement_current_trading_day_or_generation_mismatch"),
        ("error_code", False, "settlement_query_not_terminal"),
        ("submit_code", False, "settlement_query_not_terminal"),
        ("selected_pair_sha256", "f" * 64, "settlement_selected_pair_or_account_mismatch"),
        ("current_account_fingerprint_sha256", "f" * 64, "settlement_selected_pair_or_account_mismatch"),
        ("confirm_date", "20260925", "settlement_confirmation_row_scope_mismatch"),
        ("row_trading_day", "20260925", "settlement_confirmation_row_scope_mismatch"),
        ("record_count", 2, "settlement_confirmation_row_scope_mismatch"),
        ("request_type", "orders", "settlement_query_not_terminal"),
        ("complete", False, "settlement_query_not_terminal"),
        ("is_last_seen", False, "settlement_query_not_terminal"),
        ("timed_out", True, "settlement_query_not_terminal"),
        ("unsupported", True, "settlement_query_not_terminal"),
        ("late_callback_count", 1, "settlement_query_not_terminal"),
    ],
)
def test_missing_or_mismatched_attestation_binding_rejects_before_write(
    expected_scope, field, value, reason
):
    evidence = replace(_valid_evidence(expected_scope), **{field: value})
    attestor = _FakeAttestor(evidence)
    with pytest.raises(CtpSimNowSettlementConsumerRejected) as rejected:
        consume_current_settlement_readiness(
            expected_scope.native_readiness, expected_scope, attestor=attestor
        )
    assert rejected.value.reason == reason
    assert attestor.calls == 1
    assert attestor.write_calls == 0


def test_correct_looking_confirmation_row_without_filters_source_seal_or_history_rejects(expected_scope):
    # The visible ConfirmDate/account row values look right. The missing native
    # request readback and provenance digests still make the result unusable.
    evidence = replace(
        _valid_evidence(expected_scope),
        request_filter_readback=(),
        query_source_seal_sha256="",
        query_source_history_sha256="",
        terminal_callback_history_sha256="",
    )
    attestor = _FakeAttestor(evidence)
    with pytest.raises(CtpSimNowSettlementConsumerRejected) as rejected:
        consume_current_settlement_readiness(
            expected_scope.native_readiness, expected_scope, attestor=attestor
        )
    assert rejected.value.reason == "settlement_attestation_digest_missing_or_invalid"
    assert attestor.write_calls == 0


def test_selected_official_pair_is_not_replaced_by_another_pair(expected_scope):
    evidence = replace(_valid_evidence(expected_scope), selected_pair_sha256="f" * 64)
    with pytest.raises(CtpSimNowSettlementConsumerRejected) as rejected:
        consume_current_settlement_readiness(
            expected_scope.native_readiness,
            expected_scope,
            attestor=_FakeAttestor(evidence),
        )
    assert rejected.value.reason == "settlement_selected_pair_or_account_mismatch"


def test_native_readiness_must_match_exact_selected_pair(expected_scope):
    tampered = replace(expected_scope.native_readiness, td_front="tcp://127.0.0.1:12002")
    with pytest.raises(CtpSimNowSettlementConsumerRejected) as rejected:
        consume_current_settlement_readiness(
            tampered, expected_scope, attestor=_FakeAttestor(_valid_evidence(expected_scope))
        )
    assert rejected.value.reason == "settlement_native_readiness_scope_mismatch"


def test_fake_positive_does_not_load_ctp_or_native_modules():
    # Import is performed in a child process by the harness; the unit itself
    # checks this module never reaches through to bt_api_ctp/_ctp.
    forbidden = [name for name in sys.modules if name == "bt_api_ctp" or name.startswith("bt_api_ctp.") or name == "_ctp" or name.endswith("._ctp")]
    assert forbidden == []




def test_attestor_must_return_exact_typed_contract(expected_scope):
    attestor = _FakeAttestor({"confirm_date": expected_scope.trading_day})
    with pytest.raises(CtpSimNowSettlementConsumerRejected) as rejected:
        consume_current_settlement_readiness(
            expected_scope.native_readiness, expected_scope, attestor=attestor
        )
    assert rejected.value.reason == "settlement_attestation_type_invalid"
    assert attestor.write_calls == 0
