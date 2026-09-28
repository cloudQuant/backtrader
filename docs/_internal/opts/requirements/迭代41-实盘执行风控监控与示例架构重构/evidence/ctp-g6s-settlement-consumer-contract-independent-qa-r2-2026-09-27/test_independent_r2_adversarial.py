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
sys.path.insert(0, str(REPO))

import test_ctp_simnow_settlement_consumer as base
from ctp_simnow_settlement_consumer import (
    CtpSimNowSettlementConsumerRejected,
    consume_current_settlement_readiness,
)


@pytest.fixture
def expected_scope(tmp_path, monkeypatch):
    # The selected runtime fixture writes only synthetic tmp_path config.
    monkeypatch.setattr(base.runtime_config, "_require_private_config_security", lambda *a, **k: None)
    return base.expected_scope.__wrapped__(tmp_path)


class _CountingAttestor:
    def __init__(self, evidence):
        self.evidence = evidence
        self.calls = 0
        self.write_calls = 0

    def attest_current_settlement(self, _expected):
        self.calls += 1
        return self.evidence


def _reject(expected_scope, evidence, reason):
    attestor = _CountingAttestor(evidence)
    with pytest.raises(CtpSimNowSettlementConsumerRejected) as caught:
        consume_current_settlement_readiness(
            expected_scope.native_readiness, expected_scope, attestor=attestor
        )
    assert caught.value.reason == reason
    assert attestor.calls == 1
    assert attestor.write_calls == 0


@pytest.mark.parametrize("field", ["query_connection_generation", "current_connection_generation"])
@pytest.mark.parametrize("value", [True, False, 1.0, 0, -1])
def test_generation_requires_exact_positive_builtin_int(expected_scope, field, value):
    evidence = replace(base._valid_evidence(expected_scope), **{field: value})
    _reject(expected_scope, evidence, "settlement_current_trading_day_or_generation_mismatch")


@pytest.mark.parametrize("field", ["error_code", "submit_code"])
@pytest.mark.parametrize("value", [False, True, 0.0, 1])
def test_optional_native_codes_accept_only_none_or_exact_int_zero(expected_scope, field, value):
    evidence = replace(base._valid_evidence(expected_scope), **{field: value})
    _reject(expected_scope, evidence, "settlement_query_not_terminal")


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("request_id", True, "settlement_query_not_terminal"),
        ("late_callback_count", False, "settlement_query_not_terminal"),
        ("record_count", True, "settlement_confirmation_row_scope_mismatch"),
        ("terminal_callback_records_sha256", "", "settlement_attestation_digest_missing_or_invalid"),
        ("row_broker_id_sha256", "f" * 64, "settlement_confirmation_row_scope_mismatch"),
        ("row_investor_id_sha256", "f" * 64, "settlement_confirmation_row_scope_mismatch"),
        ("row_trading_day", "20260925", "settlement_confirmation_row_scope_mismatch"),
    ],
)
def test_other_strict_types_and_lineage_fields_reject(expected_scope, field, value, reason):
    evidence = replace(base._valid_evidence(expected_scope), **{field: value})
    _reject(expected_scope, evidence, reason)


def test_r1_counterexamples_reject_before_any_fake_write(expected_scope):
    for field, value in (
        ("query_connection_generation", True),
        ("current_connection_generation", True),
        ("error_code", False),
        ("submit_code", False),
    ):
        _reject(
            expected_scope,
            replace(base._valid_evidence(expected_scope), **{field: value}),
            "settlement_query_not_terminal"
            if field in ("error_code", "submit_code")
            else "settlement_current_trading_day_or_generation_mismatch",
        )


def test_mutable_attestor_property_is_retrieved_twice_but_cannot_authorize(expected_scope):
    evidence = base._valid_evidence(expected_scope)

    class _ChangingAttestor:
        def __init__(self):
            self.getter_calls = 0
            self.write_calls = 0

        @property
        def attest_current_settlement(self):
            self.getter_calls += 1
            if self.getter_calls == 1:
                return lambda _scope: None
            return lambda _scope: evidence

    attestor = _ChangingAttestor()
    receipt = consume_current_settlement_readiness(
        expected_scope.native_readiness, expected_scope, attestor=attestor
    )
    assert attestor.getter_calls == 2
    assert attestor.write_calls == 0
    assert receipt.consumer_contract_satisfied is True
    assert receipt.provider_source_trusted is False
    assert receipt.execution_authorized is False


def test_valid_confirmdate_only_attestation_remains_non_authorizing(expected_scope):
    evidence = base._valid_evidence(expected_scope)
    assert evidence.row_trading_day is None
    receipt = consume_current_settlement_readiness(
        expected_scope.native_readiness,
        expected_scope,
        attestor=_CountingAttestor(evidence),
    )
    assert receipt.consumer_contract_satisfied is True
    assert receipt.provider_source_trusted is False
    assert receipt.execution_authorized is False


def test_main_runtime_snapshots_do_not_reference_candidate_consumer():
    for name in (
        "ctp_simnow_managed_runtime.py",
        "ctp_simnow_native_readiness.py",
        "ctp_simulation_query_evidence.py",
    ):
        source = (COPY / "input-snapshots/main" / name).read_text(encoding="utf-8")
        assert "consume_current_settlement_readiness" not in source
        assert "ctp_simnow_settlement_consumer" not in source

@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("complete", 1),
        ("is_last_seen", 1),
        ("timed_out", 0),
        ("unsupported", 0),
    ],
)
def test_boolean_status_fields_do_not_accept_integer_aliases(expected_scope, field, value):
    evidence = replace(base._valid_evidence(expected_scope), **{field: value})
    _reject(expected_scope, evidence, "settlement_query_not_terminal")


def test_emitted_receipt_is_non_authorizing_but_receipt_dto_is_not_a_trust_token(expected_scope):
    from ctp_simnow_settlement_consumer import CtpSimNowSettlementConsumerReceipt

    emitted = consume_current_settlement_readiness(
        expected_scope.native_readiness,
        expected_scope,
        attestor=_CountingAttestor(base._valid_evidence(expected_scope)),
    )
    assert emitted.consumer_contract_satisfied is True
    assert emitted.provider_source_trusted is False
    assert emitted.execution_authorized is False
    # The public dataclass can be constructed by any caller; downstream code must
    # consume the validated function result in a trusted integration, not rely on
    # nominal DTO identity alone.
    caller_forgery = CtpSimNowSettlementConsumerReceipt(
        selected_pair_sha256=emitted.selected_pair_sha256,
        account_fingerprint_sha256=emitted.account_fingerprint_sha256,
        trading_day=emitted.trading_day,
        connection_generation=emitted.connection_generation,
        sdk_pin_sha256=emitted.sdk_pin_sha256,
        settlement_evidence_sha256=emitted.settlement_evidence_sha256,
        consumer_contract_satisfied=True,
        provider_source_trusted=True,
        execution_authorized=True,
    )
    assert caller_forgery.provider_source_trusted is True
    assert caller_forgery.execution_authorized is True
