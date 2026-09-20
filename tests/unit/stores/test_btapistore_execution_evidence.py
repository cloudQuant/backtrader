"""Execution-summary evidence rules for managed and non-managed SDK sessions."""

import pytest

from backtrader.stores.btapistore import BtApiStore


CRYPTO_VENUE = "OKX___SWAP"
CTP_VENUE = "CTP___SIMNOW"


class CryptoSdk:
    exchange_kwargs = {CRYPTO_VENUE: {"environment": "demo"}}
    credential_fingerprint = "a" * 64
    account_id = f"okx-credential-{credential_fingerprint}"

    def poll_event(self, timeout=None):
        return None

    def get_execution_identity(self, venue):
        return {
            "provider": "OKX",
            "environment": "demo",
            "account_id": self.account_id,
            "credential_fingerprint": self.credential_fingerprint,
            "account_authority": "credential_fingerprint",
            "exchange_name": venue,
            "strategy_id": "test-strategy",
            "fencing_epoch": 1,
        }


class CtpSdk(CryptoSdk):
    exchange_kwargs = {CTP_VENUE: {"environment": "simnow"}}
    account_id = "acct_0123456789abcdef"

    def get_execution_identity(self, venue):
        return {
            "provider": "CTP",
            "environment": "simnow",
            "account_id": self.account_id,
            "account_alias": self.account_id,
            "account_authority": "account_fingerprint",
            "exchange_name": venue,
            "strategy_id": "test-strategy",
            "fencing_epoch": 1,
        }


def make_store(api, venue):
    store = BtApiStore(
        provider="btapi",
        api=api,
        config={
            "exchange_kwargs": api.exchange_kwargs,
            "symbol_routes": {"TEST": venue},
            "execution_config": {"market_data_only": False},
        },
    )
    # Exercise the evidence function with a live-generation identity binding,
    # without starting a transport or performing any network operation.
    store._command_generation = 1
    store._stream_generation = 1
    return store


def summary(**overrides):
    result = {
        "generation": 1,
        "session_generation": 1,
        "fencing_epoch": 1,
        "evidence_complete": True,
        "evidence_errors": [],
        "trading_blocked": False,
    }
    result.update(overrides)
    return result


def test_crypto_non_arm_managed_execution_summary_does_not_require_arm_fields():
    store = make_store(CryptoSdk(), CRYPTO_VENUE)
    raw = summary(arm_managed=False, armed=False, market_data_only=False)

    normalized, identities, errors = store._sdk_execution_evidence(raw)

    assert errors == []
    assert normalized["evidence_complete"] is True
    assert normalized["armed"] is False
    assert normalized["market_data_only"] is False
    assert normalized["identity_binding_sha256"]
    assert set(identities) == {CRYPTO_VENUE}


def test_crypto_non_arm_managed_summary_must_still_prove_writable_mode():
    store = make_store(CryptoSdk(), CRYPTO_VENUE)
    raw = summary(arm_managed=False, armed=False, market_data_only=True)

    normalized, _identities, errors = store._sdk_execution_evidence(raw)

    assert "execution_arm_market_data_only" in errors
    assert normalized["evidence_complete"] is False
    assert normalized["trading_blocked"] is True
    assert store._sdk_execution_config["market_data_only"] is True


def test_ctp_arm_managed_summary_requires_all_arm_evidence():
    store = make_store(CtpSdk(), CTP_VENUE)
    raw = summary(
        arm_managed=True,
        armed=True,
        market_data_only=False,
        arm_revoked=False,
    )

    normalized, _identities, errors = store._sdk_execution_evidence(raw)

    assert errors == []
    assert normalized["evidence_complete"] is True


@pytest.mark.parametrize(
    ("change", "expected_error"),
    [
        ({"armed": False}, "execution_arm_not_armed"),
        ({"market_data_only": True}, "execution_arm_market_data_only"),
        ({"arm_revoked": True}, "execution_arm_revoked"),
    ],
)
def test_ctp_arm_managed_summary_rejects_missing_or_contradictory_evidence(
    change, expected_error
):
    store = make_store(CtpSdk(), CTP_VENUE)
    raw = summary(
        arm_managed=True,
        armed=True,
        market_data_only=False,
        arm_revoked=False,
    )
    raw.update(change)

    normalized, _identities, errors = store._sdk_execution_evidence(raw)

    assert expected_error in errors
    assert normalized["evidence_complete"] is False
    assert normalized["trading_blocked"] is True


@pytest.mark.parametrize("arm_managed", [None, False])
def test_ctp_summary_without_explicit_managed_arm_fails_closed(arm_managed):
    store = make_store(CtpSdk(), CTP_VENUE)
    raw = summary(
        arm_managed=arm_managed,
        armed=True,
        market_data_only=False,
        arm_revoked=False,
    )

    normalized, _identities, errors = store._sdk_execution_evidence(raw)

    assert "execution_arm_management_unproven" in errors
    assert normalized["evidence_complete"] is False
    assert normalized["trading_blocked"] is True


def test_ctp_summary_missing_managed_arm_marker_fails_closed():
    store = make_store(CtpSdk(), CTP_VENUE)
    raw = summary(armed=True, market_data_only=False, arm_revoked=False)

    normalized, _identities, errors = store._sdk_execution_evidence(raw)

    assert "execution_arm_management_unproven" in errors
    assert normalized["evidence_complete"] is False
    assert normalized["trading_blocked"] is True
