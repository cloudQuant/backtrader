from __future__ import annotations

from dataclasses import replace

import pytest

from backtrader_runtime.ctp_f14_external_admission import (
    CtpF14ActionAdmission,
    CtpF14ActionRequest,
    CtpF14AdmissionError,
    CtpF14ExternalAdmissionClaim,
    CtpF14SessionBinding,
    claim_f14_action,
)


_ACCOUNT = "a" * 64
_CONFIG = "b" * 64
_EFFECTIVE = "c" * 64
_REGISTRATION = "d" * 64
_ARTIFACTS = "e" * 64
_SESSION = "f" * 64
_ACTION = "1" * 64
_APPROVAL = "2" * 64
_TARGET = "3" * 64
_COVERAGE = ("account_funds", "open_orders", "positions", "trades")


def _request(
    *,
    environment: str = "simnow",
    mode: str = "simulation",
    preset: str = "sandbox",
    action_kind: str = "SUBMIT",
) -> CtpF14ActionRequest:
    return CtpF14ActionRequest(
        runtime_id="ctp_shared_runner",
        environment=environment,
        mode=mode,
        preset=preset,
        account_fingerprint_sha256=_ACCOUNT,
        config_digest=_CONFIG,
        effective_digest=_EFFECTIVE,
        registration_digest=_REGISTRATION,
        artifact_set_digest=_ARTIFACTS,
        session=CtpF14SessionBinding(
            session_id="session-7",
            trading_day="20260925",
            connection_generation=7,
            identity_digest=_SESSION,
        ),
        action_kind=action_kind,
        action_id="action-52",
        action_digest=_ACTION,
        approval_digest=_APPROVAL,
        target_digest=_TARGET if action_kind == "CANCEL" else None,
    )


def _claim(request: CtpF14ActionRequest, **changes: object) -> CtpF14ExternalAdmissionClaim:
    values: dict[str, object] = {
        "binding": request,
        "authority_id": "account-control-v1",
        "claim_id": "claim-104",
        "fence_id": "writer-fence-71",
        "fence_epoch": 41,
        "fence_scope_digest": request.scope_digest,
        "snapshot_id": "snapshot-903",
        "snapshot_version": "server-version-2204",
        "snapshot_digest": "4" * 64,
        "snapshot_coverage_digest": "5" * 64,
        "snapshot_account_fingerprint_sha256": request.account_fingerprint_sha256,
        "snapshot_fence_id": "writer-fence-71",
        "snapshot_fence_epoch": 41,
        "snapshot_coverage": _COVERAGE,
        "account_writer_exclusive": True,
        "snapshot_complete": True,
        "snapshot_consistent": True,
        "issued_at_utc": 1_790_000_000.0,
        "expires_at_utc": 1_790_000_030.0,
        "authority_receipt_digest": "6" * 64,
    }
    values.update(changes)
    return CtpF14ExternalAdmissionClaim(**values)  # type: ignore[arg-type]


class _FakeAuthority:
    def __init__(self, claim: CtpF14ExternalAdmissionClaim) -> None:
        self.claim = claim
        self.claim_requests: list[CtpF14ActionRequest] = []
        self.active_requests: list[CtpF14ActionRequest] = []
        self.active_claims: list[CtpF14ExternalAdmissionClaim] = []
        self.active_result: object = True
        self.fail_claim = False
        self.fail_active = False

    def claim_and_verify(self, request: CtpF14ActionRequest) -> CtpF14ExternalAdmissionClaim:
        self.claim_requests.append(request)
        if self.fail_claim:
            raise RuntimeError("private authority detail")
        return self.claim

    def assert_active(
        self,
        claim: CtpF14ExternalAdmissionClaim,
        *,
        request: CtpF14ActionRequest,
    ) -> bool:
        self.active_claims.append(claim)
        self.active_requests.append(request)
        if self.fail_active:
            raise RuntimeError("private authority detail")
        return self.active_result  # type: ignore[return-value]


def test_claim_is_requested_for_exact_action_and_rechecked_before_dispatch() -> None:
    request = _request(action_kind="CANCEL")
    claim = _claim(request)
    authority = _FakeAuthority(claim)

    admission = claim_f14_action(authority, request)

    assert type(admission) is CtpF14ActionAdmission
    assert authority.claim_requests == [request]
    assert admission.request_digest == request.request_digest
    assert admission.scope_digest == request.scope_digest
    admission.assert_active()
    assert authority.active_claims == [claim]
    assert authority.active_requests == [request]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"account_writer_exclusive": False},
        {"snapshot_complete": False},
        {"snapshot_consistent": False},
        {"snapshot_coverage": ("orders", "trades", "positions", "funds")},
        {"snapshot_account_fingerprint_sha256": "9" * 64},
        {"snapshot_fence_id": "other-fence"},
        {"snapshot_fence_epoch": 40},
    ],
)
def test_incomplete_or_mismatched_external_snapshot_fails_closed(kwargs: dict[str, object]) -> None:
    request = _request()
    authority = _FakeAuthority(_claim(request, **kwargs))

    with pytest.raises(CtpF14AdmissionError):
        claim_f14_action(authority, request)


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_fingerprint_sha256", "9" * 64),
        ("config_digest", "9" * 64),
        ("effective_digest", "9" * 64),
        ("registration_digest", "9" * 64),
        ("artifact_set_digest", "9" * 64),
        ("action_id", "action-53"),
        ("action_digest", "9" * 64),
        ("approval_digest", "9" * 64),
    ],
)
def test_claim_bound_to_different_account_config_artifact_or_action_is_rejected(
    field: str, value: str
) -> None:
    request = _request()
    mismatched_binding = replace(request, **{field: value})
    authority = _FakeAuthority(_claim(request, binding=mismatched_binding))

    with pytest.raises(CtpF14AdmissionError, match="scope mismatch"):
        claim_f14_action(authority, request)


def test_claim_bound_to_different_native_session_is_rejected() -> None:
    request = _request()
    changed_session = replace(request.session, connection_generation=8)
    authority = _FakeAuthority(_claim(request, binding=replace(request, session=changed_session)))

    with pytest.raises(CtpF14AdmissionError, match="scope mismatch"):
        claim_f14_action(authority, request)


@pytest.mark.parametrize(
    "environment,mode,preset",
    [
        ("simnow", "simulation", "sandbox"),
        ("production", "live", "managed_live_direct"),
    ],
)
def test_simnow_and_production_are_separate_exact_request_scopes(
    environment: str, mode: str, preset: str
) -> None:
    request = _request(environment=environment, mode=mode, preset=preset)
    authority = _FakeAuthority(_claim(request))

    claim_f14_action(authority, request)

    assert authority.claim_requests == [request]
    if environment == "production":
        simnow_request = _request()
        assert request.scope_digest != simnow_request.scope_digest


@pytest.mark.parametrize("active_result", [False, None, 1])
def test_non_true_external_recheck_blocks_dispatch(active_result: object) -> None:
    request = _request()
    authority = _FakeAuthority(_claim(request))
    admission = claim_f14_action(authority, request)
    authority.active_result = active_result

    with pytest.raises(CtpF14AdmissionError, match="no longer active"):
        admission.assert_active()


def test_authority_errors_are_redacted_and_fail_closed() -> None:
    request = _request()
    authority = _FakeAuthority(_claim(request))
    authority.fail_claim = True

    with pytest.raises(CtpF14AdmissionError, match="authority unavailable") as caught:
        claim_f14_action(authority, request)
    assert "private authority detail" not in str(caught.value)

    authority.fail_claim = False
    admission = claim_f14_action(authority, request)
    authority.fail_active = True
    with pytest.raises(CtpF14AdmissionError, match="recheck unavailable") as caught:
        admission.assert_active()
    assert "private authority detail" not in str(caught.value)


def test_caller_cannot_pass_a_claim_as_the_authority_or_construct_a_handle() -> None:
    request = _request()
    claim = _claim(request)

    with pytest.raises(CtpF14AdmissionError, match="authority required"):
        claim_f14_action(claim, request)  # type: ignore[arg-type]
    with pytest.raises(CtpF14AdmissionError, match="factory required"):
        CtpF14ActionAdmission(
            None, request, claim, _construction_key=object()  # type: ignore[arg-type]
        )


def test_seven_independent_query_kinds_do_not_satisfy_common_snapshot_contract() -> None:
    request = _request()
    authority = _FakeAuthority(
        _claim(
            request,
            snapshot_coverage=(
                "orders_query_1",
                "orders_query_2",
                "trades_query",
                "positions_query",
                "account_query",
                "rates_query",
                "instruments_query",
            ),
        )
    )

    with pytest.raises(CtpF14AdmissionError, match="snapshot coverage incomplete"):
        claim_f14_action(authority, request)
