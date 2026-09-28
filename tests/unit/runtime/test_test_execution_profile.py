"""Offline, fail-closed contract tests for a future sandbox test profile."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import backtrader_runtime.test_execution_profile as test_execution_profile
from backtrader_runtime.test_execution_profile import (
    MAX_TEST_EXECUTION_PROFILE_BYTES,
    TEST_EXECUTION_PROFILE_PRECHECKED,
    TEST_EXECUTION_PROFILE_SCHEMA_VERSION,
    TestExecutionPreflightContext as _TestExecutionPreflightContext,
    TestExecutionProfileError as _TestExecutionProfileError,
    canonical_test_execution_profile,
    parse_test_execution_profile,
    test_execution_profile_sha256 as _test_execution_profile_sha256,
    validate_test_execution_profile,
)


NOW = 1_700_000_100.0


@pytest.fixture(autouse=True)
def profile_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise public validation with a fixed actual-clock lookup."""

    monkeypatch.setattr(test_execution_profile.time, "time", lambda: NOW)


class _AcceptingOfflineVerifier:
    """A test-only verifier with no credential, account, or provider access."""

    def __init__(self) -> None:
        self.calls = 0

    def verify(self, profile, canonical_payload: bytes) -> bool:
        self.calls += 1
        assert canonical_payload == canonical_test_execution_profile(profile)
        return True


class _MutatingOfflineVerifier:
    """A hostile verifier used to ensure a profile cannot be changed in place."""

    def verify(self, profile, canonical_payload: bytes) -> bool:
        del canonical_payload
        object.__setattr__(profile, "max_external_writes", 99)
        return True


class _StatefulMapping(dict):
    """A mapping whose iteration must not run at the parsing boundary."""

    def __init__(self) -> None:
        super().__init__()
        self.iterated = False

    def __iter__(self):
        self.iterated = True
        raise AssertionError("the parser must not execute mapping subclasses")


def _wire() -> dict:
    return {
        "account_fingerprint_sha256": "a" * 64,
        "allowed_instruments": ["IF2406", "rb2610"],
        "approval_receipt_digest": "e" * 64,
        "artifact_sha256": "b" * 64,
        "capability_receipt_digest": "c" * 64,
        "cleanup_required": True,
        "created_at": NOW - 10.0,
        "effective_config_digest": "d" * 64,
        "environment": "sandbox",
        "expires_at": NOW + 60.0,
        "max_external_writes": 2,
        "max_quantity": "3.000",
        "profile_id": "iteration41.ctp.simnow-test-1",
        "provider": "ctp",
        "reconciliation_required": True,
        "schema_version": TEST_EXECUTION_PROFILE_SCHEMA_VERSION,
        "valid_from": NOW - 5.0,
    }


def _context(**changes) -> _TestExecutionPreflightContext:
    values = {
        "provider": "ctp",
        "environment": "sandbox",
        "account_fingerprint_sha256": "a" * 64,
        "approval_receipt_digest": "e" * 64,
        "effective_config_digest": "d" * 64,
        "artifact_sha256": "b" * 64,
        "capability_receipt_digest": "c" * 64,
        "instrument": "IF2406",
        "quantity": "2.5",
        "requested_external_writes": 1,
        "cleanup_ready": True,
        "reconciliation_ready": True,
    }
    values.update(changes)
    return _TestExecutionPreflightContext(**values)


def test_matching_profile_only_returns_a_non_authoritative_offline_observation() -> None:
    wire = _wire()
    verifier = _AcceptingOfflineVerifier()

    observation = validate_test_execution_profile(wire, context=_context(), verifier=verifier)

    assert verifier.calls == 1
    assert observation.status == TEST_EXECUTION_PROFILE_PRECHECKED
    assert observation.profile_binding_valid is True
    assert observation.profile_verifier_accepted is True
    assert observation.preflight_authorized is False
    assert observation.execution_authorized is False
    assert observation.provider_preflight_started is False
    assert observation.provider_connected is False
    assert observation.external_writes_started is False
    assert observation.approval_receipt_digest == wire["approval_receipt_digest"]
    assert observation.valid_until == NOW + 60.0
    public = observation.as_public_dict()
    assert "account_fingerprint_sha256" not in public
    assert wire["account_fingerprint_sha256"] not in json.dumps(public)
    profile = parse_test_execution_profile(wire)
    assert wire["account_fingerprint_sha256"] not in repr(profile)
    with pytest.raises(ValueError, match="cannot grant authority"):
        replace(observation, execution_authorized=True)
    with pytest.raises(TypeError, match="not an admission decision"):
        bool(observation)


def test_default_verifier_rejects_every_profile_before_any_provider_activity() -> None:
    with pytest.raises(_TestExecutionProfileError) as caught:
        validate_test_execution_profile(_wire(), context=_context())

    assert caught.value.reason == "profile_untrusted"


def test_caller_cannot_revive_profile_with_historical_time() -> None:
    verifier = _AcceptingOfflineVerifier()

    with pytest.raises(TypeError, match="unexpected keyword argument 'now'"):
        validate_test_execution_profile(
            _wire(),
            context=_context(),
            verifier=verifier,
            now=NOW - 1_000.0,  # type: ignore[call-arg]
        )

    assert verifier.calls == 0


def test_profile_canonicalization_normalizes_instrument_order_and_quantity() -> None:
    first_wire = _wire()
    second_wire = _wire()
    second_wire["allowed_instruments"] = list(reversed(first_wire["allowed_instruments"]))
    second_wire["max_quantity"] = "3"

    first = parse_test_execution_profile(first_wire)
    second = parse_test_execution_profile(second_wire)

    assert first.allowed_instruments == ("IF2406", "rb2610")
    assert first.max_quantity == "3"
    assert canonical_test_execution_profile(first) == canonical_test_execution_profile(second)
    assert _test_execution_profile_sha256(first) == _test_execution_profile_sha256(second)
    assert TEST_EXECUTION_PROFILE_SCHEMA_VERSION == "bt-test-execution-profile/v2"


@pytest.mark.parametrize(
    "mutate,reason",
    (
        (
            lambda wire: wire.update({"environment": "production"}),
            "production_environment_forbidden",
        ),
        (lambda wire: wire.update({"environment": "development"}), "environment_not_sandbox"),
        (lambda wire: wire.update({"approval_receipt_digest": "invalid"}), "invalid_digest"),
        (lambda wire: wire.update({"valid_from": NOW + 1.0}), "profile_not_yet_valid"),
        (lambda wire: wire.update({"expires_at": NOW}), "profile_expired"),
        (lambda wire: wire.update({"cleanup_required": False}), "required_safety_control_missing"),
        (
            lambda wire: wire.update({"reconciliation_required": False}),
            "required_safety_control_missing",
        ),
        (
            lambda wire: wire.update({"schema_version": "bt-test-execution-profile/v1"}),
            "unsupported_schema",
        ),
        (lambda wire: wire.update({"unexpected": "field"}), "invalid_wire"),
    ),
)
def test_malformed_or_non_sandbox_profiles_fail_before_the_verifier(mutate, reason: str) -> None:
    wire = _wire()
    mutate(wire)
    verifier = _AcceptingOfflineVerifier()

    with pytest.raises(_TestExecutionProfileError) as caught:
        validate_test_execution_profile(wire, context=_context(), verifier=verifier)

    assert caught.value.reason == reason
    assert verifier.calls == 0


@pytest.mark.parametrize(
    "context_change,reason",
    (
        ({"provider": "other"}, "provider_mismatch"),
        ({"environment": "simnow"}, "environment_mismatch"),
        ({"account_fingerprint_sha256": "e" * 64}, "account_fingerprint_mismatch"),
        ({"effective_config_digest": "e" * 64}, "effective_config_digest_mismatch"),
        ({"artifact_sha256": "e" * 64}, "artifact_mismatch"),
        ({"capability_receipt_digest": "e" * 64}, "capability_receipt_digest_mismatch"),
        ({"approval_receipt_digest": "f" * 64}, "approval_receipt_digest_mismatch"),
        ({"instrument": "cu2406"}, "instrument_not_allowed"),
        ({"quantity": "3.1"}, "quantity_limit_exceeded"),
        ({"requested_external_writes": 3}, "external_write_limit_exceeded"),
        ({"cleanup_ready": False}, "cleanup_not_ready"),
        ({"reconciliation_ready": False}, "reconciliation_not_ready"),
    ),
)
def test_context_must_remain_exactly_bound_and_within_profile_limits(
    context_change, reason: str
) -> None:
    verifier = _AcceptingOfflineVerifier()

    with pytest.raises(_TestExecutionProfileError) as caught:
        validate_test_execution_profile(
            _wire(), context=_context(**context_change), verifier=verifier
        )

    assert caught.value.reason == reason
    assert verifier.calls == 0


def test_profile_parser_rejects_missing_and_duplicate_wire_fields() -> None:
    missing = _wire()
    del missing["max_quantity"]

    with pytest.raises(_TestExecutionProfileError) as caught:
        parse_test_execution_profile(missing)

    assert caught.value.reason == "invalid_wire"
    encoded = json.dumps(_wire(), sort_keys=True)
    duplicate = encoded[:-1] + ',"profile_id":"duplicate"}'
    with pytest.raises(_TestExecutionProfileError) as caught:
        parse_test_execution_profile(duplicate)

    assert caught.value.reason == "invalid_json"


def test_profile_wire_requires_a_preissued_approval_receipt_digest() -> None:
    missing = _wire()
    del missing["approval_receipt_digest"]

    with pytest.raises(_TestExecutionProfileError) as caught:
        parse_test_execution_profile(missing)

    assert caught.value.reason == "invalid_wire"

    with pytest.raises(_TestExecutionProfileError) as caught:
        _context(approval_receipt_digest=None)

    assert caught.value.reason == "invalid_digest"


def test_profile_parser_rejects_stateful_mappings_without_running_them() -> None:
    mapping = _StatefulMapping()

    with pytest.raises(_TestExecutionProfileError) as caught:
        parse_test_execution_profile(mapping)

    assert caught.value.reason == "invalid_wire"
    assert mapping.iterated is False


@pytest.mark.parametrize(
    "serialized,reason",
    (
        ("[" * 2_000 + "]" * 2_000, "invalid_json"),
        (b"{" + b" " * MAX_TEST_EXECUTION_PROFILE_BYTES + b"}", "profile_too_large"),
    ),
    ids=("deeply_nested_json", "oversized_bytes"),
)
def test_profile_parser_rejects_nested_or_oversized_serialized_wires(
    serialized, reason: str
) -> None:
    with pytest.raises(_TestExecutionProfileError) as caught:
        parse_test_execution_profile(serialized)

    assert caught.value.reason == reason


def test_profile_parser_rejects_deep_json_even_with_raised_recursion_limit() -> None:
    original_limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(max(original_limit, 10_000))
        with pytest.raises(_TestExecutionProfileError) as caught:
            parse_test_execution_profile("[" * 2_000 + "]" * 2_000)
    finally:
        sys.setrecursionlimit(original_limit)
    assert caught.value.reason == "invalid_json"


def test_verifier_cannot_mutate_the_canonical_profile_it_claims_to_trust() -> None:
    with pytest.raises(_TestExecutionProfileError) as caught:
        validate_test_execution_profile(
            _wire(), context=_context(), verifier=_MutatingOfflineVerifier()
        )

    assert caught.value.reason == "profile_mutated_by_verifier"


def test_validation_rechecks_expiry_after_the_verifier_returns(monkeypatch) -> None:
    clock_values = iter((NOW, NOW + 60.0))
    monkeypatch.setattr(test_execution_profile.time, "time", lambda: next(clock_values))
    verifier = _AcceptingOfflineVerifier()

    with pytest.raises(_TestExecutionProfileError) as caught:
        validate_test_execution_profile(_wire(), context=_context(), verifier=verifier)

    assert caught.value.reason == "profile_expired"
    assert verifier.calls == 1


def test_profile_module_imports_no_framework_or_provider_sdk() -> None:
    script = (
        "import sys; import backtrader_runtime.test_execution_profile; "
        "blocked = ('backtrader', 'bt_api', 'bt_api_py', 'backtrader_agent', "
        "'backtrader_skills', 'backtrader_mcp'); "
        "assert not any(name == item or name.startswith(item + '.') "
        "for item in blocked for name in sys.modules)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(Path(__file__).resolve().parents[3]),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_context_does_not_accept_production_environment() -> None:
    values = dict(_context().__dict__)
    values["environment"] = "production"

    with pytest.raises(_TestExecutionProfileError) as caught:
        _TestExecutionPreflightContext(**copy.deepcopy(values))

    assert caught.value.reason == "production_environment_forbidden"
