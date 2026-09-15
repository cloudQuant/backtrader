"""Pure-local tests for the V2 CTP bundle authorization builder."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import importlib
import sys
from datetime import datetime, timezone

import pytest

from backtrader.stores.btapistore import (
    _CTP_EXECUTION_ARM_BUNDLE_FIELDS,
    _CTP_EXECUTION_AUTHORIZATION_BUNDLE_FIELDS,
)
from examples.ctp_options_simnow_authorization import (
    AuthorizationBuildError,
    build_bundle_authorization,
)


SECRET = "local-test-secret-that-is-at-least-32-bytes"
ACCOUNT = "acct_0123456789abcdef"
PROFILE = "simnow_demo"
NOW = datetime.now(timezone.utc)


def _query_results(names, prefix):
    return {
        name: {"complete": True, "request_id": f"{prefix}-{index}"}
        for index, name in enumerate(names, 1)
    }


def _stage(*, instrument_id="", exchange_id="DCE", prefix="a"):
    return {
        "schema_version": "backtrader.ctp.preflight.v1",
        "instrument_id": instrument_id,
        "exchange_id": exchange_id,
        "account_fingerprint": ACCOUNT,
        "trading_day": "20260911",
        "connection_generation": 7,
        "snapshot_sha256": prefix * 64,
        "evidence_complete": True,
        "read_only_safe": True,
        "write_request_free": True,
        "evidence_errors": [],
        "session_after": {"environment_profile": PROFILE},
        "query_results": _query_results(
            ("account", "positions", "orders", "trades", "instruments")
            + (("margin_rate", "commission_rate") if instrument_id else ()),
            prefix,
        ),
    }


def _bundle(*, legs=None, primary="DCE.m2701", prefix="d"):
    legs = legs or [
        {"exchange_id": "DCE", "instrument_id": "m2701", "is_primary": True, "evidence_complete": True},
        {"exchange_id": "DCE", "instrument_id": "m2701-C-3400", "is_primary": False, "evidence_complete": True},
        {"exchange_id": "DCE", "instrument_id": "m2701-P-3400", "is_primary": False, "evidence_complete": True},
    ]
    return {
        "schema_version": "backtrader.ctp.bundle-preflight.v2",
        "snapshot_sha256": prefix * 64,
        "account_fingerprint": ACCOUNT,
        "trading_day": "20260911",
        "connection_generation": 7,
        "evidence_complete": True,
        "read_only_safe": True,
        "write_request_free": True,
        "flat": True,
        "evidence_errors": [],
        "session_after": {"environment_profile": PROFILE},
        "legs": legs,
        "primary_leg": {"exchange_id": "DCE", "instrument_id": primary.split(".", 1)[1]},
    }


def _kwargs(**changes):
    values = {
        "stage_a": _stage(prefix="a"),
        "stage_b": _stage(instrument_id="m2701", prefix="b"),
        "bundle_preflight": _bundle(),
        "runtime_identity": {
            "account_fingerprint": ACCOUNT,
            "trading_day": "20260911",
            "connection_generation": 7,
            "environment_profile": PROFILE,
        },
        "strategy_id": "iter24-ctp-bundle:engineering_smoke",
        "strategy_identity_sha256": "1" * 64,
        "authorization_key_id": "local-test-key",
        "authorization_secret": SECRET,
        "issued_at_utc": NOW,
        "expires_at_utc": NOW.replace(year=2099),
        "receipt_sha256": "2" * 64,
        "native_sha256": "3" * 64,
        "ctp_package_sha256": "4" * 64,
        "source_hashes_sha256": "5" * 64,
        "dependency_hashes_sha256": "6" * 64,
        "evidence_hashes_sha256": "7" * 64,
        "runtime_executable_sha256": "8" * 64,
        "gate_statuses": {"G1": "PASS", "G2": "PASS", "G3": "PASS"},
    }
    values.update(changes)
    return values


def test_success_shape_signature_and_secret_redaction():
    artifacts = build_bundle_authorization(**_kwargs())
    assert set(artifacts.arming_proof) == _CTP_EXECUTION_ARM_BUNDLE_FIELDS
    assert set(artifacts.grant) == _CTP_EXECUTION_AUTHORIZATION_BUNDLE_FIELDS
    unsigned = {key: value for key, value in artifacts.grant.items() if key != "signature_hmac_sha256"}
    expected = hmac.new(SECRET.encode(), json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(), hashlib.sha256).hexdigest()
    assert artifacts.grant["signature_hmac_sha256"] == expected
    assert artifacts.summary["status"] == "BUILT_NOT_ARMED"
    assert ACCOUNT not in repr(artifacts.summary)
    assert SECRET not in repr(artifacts)


@pytest.mark.parametrize(
    "change",
    [
        {"authorization_secret": "short"},
        {"gate_statuses": {"G1": "PASS", "G2": "FAIL", "G3": "PASS"}},
        {"strategy_identity_sha256": "not-a-hash"},
        {"runtime_executable_sha256": "Z" * 64},
        {"expires_at_utc": NOW},
    ],
)
def test_invalid_secret_gate_hash_or_expiry_rejects(change):
    with pytest.raises(AuthorizationBuildError):
        build_bundle_authorization(**_kwargs(**change))


@pytest.mark.parametrize("field", ["account_fingerprint", "trading_day", "connection_generation", "environment_profile"])
def test_identity_or_profile_mismatch_rejects(field):
    runtime = _kwargs()["runtime_identity"].copy()
    runtime[field] = "other" if field != "connection_generation" else 8
    with pytest.raises(AuthorizationBuildError):
        build_bundle_authorization(**_kwargs(runtime_identity=runtime))


def test_scope_order_duplicate_and_gate_tamper_reject():
    legs = _bundle()["legs"]
    with pytest.raises(AuthorizationBuildError):
        build_bundle_authorization(**_kwargs(bundle_preflight=_bundle(legs=list(reversed(legs)))))
    duplicate = copy.deepcopy(legs)
    duplicate[-1]["instrument_id"] = duplicate[-2]["instrument_id"]
    with pytest.raises(AuthorizationBuildError):
        build_bundle_authorization(**_kwargs(bundle_preflight=_bundle(legs=duplicate)))
    with pytest.raises(AuthorizationBuildError):
        build_bundle_authorization(**_kwargs(stage_b=_stage(instrument_id="m2702", prefix="b")))


def test_builder_output_is_accepted_by_existing_fake_store_contract():
    fixture = importlib.import_module("tests.unit.stores.test_btapistore_iteration22")
    client = fixture.BundleQueryClient()
    store = fixture.make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
        execution_config={
            "market_data_only": True,
            "strategy_id": "iter24-ctp-bundle:engineering_smoke",
            "strategy_identity_sha256": "1" * 64,
        },
        execution_authorization_key_id="local-test-key",
        execution_authorization_secret=SECRET,
    )
    stage_a = store.get_ctp_preflight_snapshot(timeout=0)
    stage_b = store.get_ctp_preflight_snapshot("DCE.m2701", timeout=0)
    bundle = store.get_ctp_bundle_preflight_snapshot(fixture._dce_bundle_legs(), timeout=0)
    session = bundle["session_after"]
    artifacts = build_bundle_authorization(
        **_kwargs(
            stage_a=stage_a,
            stage_b=stage_b,
            bundle_preflight=bundle,
            runtime_identity={
                "account_fingerprint": bundle["account_fingerprint"],
                "trading_day": bundle["trading_day"],
                "connection_generation": bundle["connection_generation"],
                "environment_profile": session["environment_profile"],
            },
            strategy_identity_sha256="1" * 64,
            runtime_executable_sha256=hashlib.sha256(open(sys.executable, "rb").read()).hexdigest(),
        )
    )
    configured = store.configure_ctp_execution_authorization(artifacts.grant)
    assert configured["configured"] is True
    assert configured["market_data_only"] is True
