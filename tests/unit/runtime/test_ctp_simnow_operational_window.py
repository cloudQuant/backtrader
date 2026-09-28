from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from backtrader_runtime.ctp_f14_external_admission import (
    CtpF14ActionRequest,
    CtpF14AdmissionError,
    CtpF14ExternalAdmissionClaim,
    CtpF14SessionBinding,
    claim_f14_action,
)
from backtrader_runtime.ctp_simnow_operational_window import (
    CtpSimNowOperationalActionRequest,
    CtpSimNowOperationalRiskLimits,
    CtpSimNowOperationalWindowError,
    CtpSimNowOperationalWindowPermit,
    CtpSimNowOperationalWindowScope,
    CtpSimNowQueryKind,
    CtpSimNowQueryRequest,
    CtpSimNowSingleQueryObservation,
    require_active_simnow_operational_window_permit,
    require_simnow_operational_window_permit,
    require_simnow_single_query_observation,
)


_ACCOUNT = "a" * 64
_CONFIG = "b" * 64
_EFFECTIVE = "c" * 64
_REGISTRATION = "d" * 64
_ARTIFACTS = "e" * 64
_SESSION = "f" * 64
_FILTERS = "1" * 64
_ACTION = "2" * 64
_APPROVAL = "3" * 64
_TARGET = "4" * 64


def _scope(**changes: object) -> CtpSimNowOperationalWindowScope:
    values: dict[str, object] = {
        "window_id": "simnow-window-7",
        "runtime_id": "iteration41.ctp.simnow-test",
        "environment": "simnow",
        "mode": "simulation",
        "preset": "sandbox",
        "account_fingerprint_sha256": _ACCOUNT,
        "config_digest": _CONFIG,
        "effective_digest": _EFFECTIVE,
        "registration_digest": _REGISTRATION,
        "artifact_set_digest": _ARTIFACTS,
        "session_id": "session-7",
        "trading_day": "20260925",
        "connection_generation": 7,
        "session_identity_digest": _SESSION,
        "selected_front_pair": ("tcp://127.0.0.1:11001", "tcp://127.0.0.1:12001"),
        "instrument_id": "rb2701",
        "exchange_id": "SHFE",
        "hedge_flag": "1",
        "risk_limits": CtpSimNowOperationalRiskLimits(
            max_order_quantity=1,
            max_gross_position_quantity=1,
            max_live_test_orders=1,
            max_order_notional=Decimal("5000"),
        ),
    }
    values.update(changes)
    return CtpSimNowOperationalWindowScope(**values)  # type: ignore[arg-type]


def _action(
    *,
    scope: CtpSimNowOperationalWindowScope | None = None,
    action_kind: str = "SUBMIT",
    **changes: object,
) -> CtpSimNowOperationalActionRequest:
    values: dict[str, object] = {
        "scope": scope or _scope(),
        "action_kind": action_kind,
        "action_id": "action-52",
        "action_digest": _ACTION,
        "approval_digest": _APPROVAL,
        "requested_quantity": 1 if action_kind == "SUBMIT" else None,
        "requested_notional": Decimal("3450") if action_kind == "SUBMIT" else None,
        "target_digest": _TARGET if action_kind == "CANCEL" else None,
        "target_remaining_quantity": 1 if action_kind == "CANCEL" else None,
    }
    values.update(changes)
    return CtpSimNowOperationalActionRequest(**values)  # type: ignore[arg-type]


def _permit(
    request: CtpSimNowOperationalActionRequest, **changes: object
) -> CtpSimNowOperationalWindowPermit:
    values: dict[str, object] = {
        "binding": request,
        "permit_id": "permit-100",
        "review_authority_id": "fake-reviewer",
        "review_digest": "5" * 64,
        "revocation_epoch": 3,
        "issued_at_utc": 1_790_000_000.0,
        "expires_at_utc": 1_790_000_030.0,
    }
    values.update(changes)
    return CtpSimNowOperationalWindowPermit(**values)  # type: ignore[arg-type]


class _FakeReviewer:
    def __init__(self, permit: object) -> None:
        self.permit = permit
        self.active_result: object = True
        self.fail_issue = False
        self.fail_check = False
        self.requests: list[CtpSimNowOperationalActionRequest] = []
        self.checked: list[CtpSimNowOperationalWindowPermit] = []

    def issue_action_review(self, request: CtpSimNowOperationalActionRequest) -> object:
        self.requests.append(request)
        if self.fail_issue:
            raise RuntimeError("untrusted reviewer detail")
        return self.permit

    def assert_action_review_current(
        self,
        permit: CtpSimNowOperationalWindowPermit,
        *,
        request: CtpSimNowOperationalActionRequest,
    ) -> object:
        assert permit.binding == request
        self.checked.append(permit)
        if self.fail_check:
            raise RuntimeError("untrusted reviewer detail")
        return self.active_result


class _FakeQueryVerifier:
    def __init__(self) -> None:
        self.result: object = True
        self.requests: list[CtpSimNowQueryRequest] = []
        self.observations: list[CtpSimNowSingleQueryObservation] = []

    def verify_single_query(
        self,
        observation: CtpSimNowSingleQueryObservation,
        *,
        expected_request: CtpSimNowQueryRequest,
    ) -> object:
        self.observations.append(observation)
        self.requests.append(expected_request)
        return self.result


def _query_request(**changes: object) -> CtpSimNowQueryRequest:
    values: dict[str, object] = {
        "scope": _scope(),
        "query_id": "query-11",
        "query_kind": CtpSimNowQueryKind.OPEN_ORDERS,
        "request_id": 11,
        "filters_digest": _FILTERS,
    }
    values.update(changes)
    return CtpSimNowQueryRequest(**values)  # type: ignore[arg-type]


def _observation(
    request: CtpSimNowQueryRequest, **changes: object
) -> CtpSimNowSingleQueryObservation:
    values: dict[str, object] = {
        "binding": request,
        "b_is_last": True,
        "response_error_code": 0,
        "callback_count": 1,
        "late_callback_count": 0,
        "record_count": 0,
        "records_digest": "6" * 64,
        "source_evidence_digest": "7" * 64,
        "started_at_utc": 1_790_000_000.0,
        "terminal_at_utc": 1_790_000_001.0,
    }
    values.update(changes)
    return CtpSimNowSingleQueryObservation(**values)  # type: ignore[arg-type]


def test_simnow_action_permit_is_exact_and_explicitly_non_authorizing() -> None:
    request = _action(action_kind="CANCEL")
    permit = _permit(request)
    reviewer = _FakeReviewer(permit)

    returned = require_simnow_operational_window_permit(reviewer, request, now_utc=1_790_000_001.0)

    assert returned is permit
    assert reviewer.requests == [request]
    assert reviewer.checked == [permit]
    assert permit.request_digest == request.request_digest
    assert permit.scope_digest == request.scope.scope_digest
    assert permit.permit_digest == _permit(request).permit_digest
    assert permit.account_writer_exclusive is False
    assert permit.common_snapshot_verified is False
    assert permit.cryptographic_signature_verified is False
    assert permit.write_authorized is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("environment", "production"),
        ("mode", "live"),
        ("preset", "managed_live_direct"),
        ("account_fingerprint_sha256", "9" * 64),
        ("config_digest", "9" * 64),
        ("effective_digest", "9" * 64),
        ("registration_digest", "9" * 64),
        ("artifact_set_digest", "9" * 64),
        ("session_id", "session-other"),
        ("trading_day", "20260926"),
        ("connection_generation", 8),
        ("session_identity_digest", "9" * 64),
        ("selected_front_pair", ("tcp://127.0.0.1:11002", "tcp://127.0.0.1:12002")),
    ],
)
def test_scope_rejects_mode_account_config_artifact_session_day_or_pair_changes(
    field: str, value: object
) -> None:
    if field in ("environment", "mode", "preset"):
        values = {
            "window_id": "simnow-window-7",
            "runtime_id": "iteration41.ctp.simnow-test",
            "environment": "simnow",
            "mode": "simulation",
            "preset": "sandbox",
            "account_fingerprint_sha256": _ACCOUNT,
            "config_digest": _CONFIG,
            "effective_digest": _EFFECTIVE,
            "registration_digest": _REGISTRATION,
            "artifact_set_digest": _ARTIFACTS,
            "session_id": "session-7",
            "trading_day": "20260925",
            "connection_generation": 7,
            "session_identity_digest": _SESSION,
            "selected_front_pair": ("tcp://127.0.0.1:11001", "tcp://127.0.0.1:12001"),
            "instrument_id": "rb2701",
            "exchange_id": "SHFE",
            "hedge_flag": "1",
            "risk_limits": CtpSimNowOperationalRiskLimits(1, 1, 1, Decimal("5000")),
        }
        values[field] = value
        with pytest.raises(CtpSimNowOperationalWindowError):
            CtpSimNowOperationalWindowScope(**values)  # type: ignore[arg-type]
        return

    changed_scope = _scope(**{field: value})
    original = _action()
    changed_request = replace(original, scope=changed_scope)
    reviewer = _FakeReviewer(_permit(original))
    with pytest.raises(CtpSimNowOperationalWindowError, match="scope mismatch"):
        require_simnow_operational_window_permit(reviewer, changed_request, now_utc=1_790_000_001.0)


@pytest.mark.parametrize(
    "action_kind,changes",
    [
        ("SUBMIT", {"requested_quantity": 2}),
        ("SUBMIT", {"requested_notional": Decimal("5000.01")}),
        ("SUBMIT", {"target_digest": _TARGET}),
        ("CANCEL", {"target_digest": None}),
        ("CANCEL", {"target_remaining_quantity": 2}),
        ("CANCEL", {"requested_quantity": 1}),
    ],
)
def test_action_request_enforces_risk_ceiling_and_exact_cancel_target(
    action_kind: str, changes: dict[str, object]
) -> None:
    with pytest.raises(CtpSimNowOperationalWindowError):
        _action(action_kind=action_kind, **changes)


def test_risk_limits_are_single_order_one_lot_and_positive() -> None:
    with pytest.raises(CtpSimNowOperationalWindowError):
        CtpSimNowOperationalRiskLimits(2, 1, 1, Decimal("5000"))
    with pytest.raises(CtpSimNowOperationalWindowError):
        CtpSimNowOperationalRiskLimits(1, 1, 2, Decimal("5000"))
    with pytest.raises(CtpSimNowOperationalWindowError):
        CtpSimNowOperationalRiskLimits(1, 1, 1, Decimal("NaN"))


@pytest.mark.parametrize(
    "now",
    [1_789_999_999.0, 1_790_000_030.0],
)
def test_action_permit_expiry_is_enforced(now: float) -> None:
    request = _action()
    reviewer = _FakeReviewer(_permit(request))
    with pytest.raises(CtpSimNowOperationalWindowError, match="expired"):
        require_simnow_operational_window_permit(reviewer, request, now_utc=now)


def test_action_permit_cannot_outlive_short_action_ttl() -> None:
    with pytest.raises(CtpSimNowOperationalWindowError, match="expiry invalid"):
        _permit(_action(), expires_at_utc=1_790_000_061.0)


def test_permit_digest_binds_window_expiry_and_revocation_epoch() -> None:
    request = _action()
    original = _permit(request)

    assert replace(original, revocation_epoch=4).permit_digest != original.permit_digest
    assert replace(original, expires_at_utc=1_790_000_029.0).permit_digest != original.permit_digest


@pytest.mark.parametrize("active", [False, None, 1])
def test_revocation_or_nonliteral_active_result_fails_closed(active: object) -> None:
    request = _action()
    reviewer = _FakeReviewer(_permit(request))
    reviewer.active_result = active
    with pytest.raises(CtpSimNowOperationalWindowError, match="revoked"):
        require_simnow_operational_window_permit(reviewer, request, now_utc=1_790_000_001.0)


def test_permit_rechecks_expiry_and_revocation_for_exact_action() -> None:
    request = _action(action_kind="CANCEL")
    permit = _permit(request)
    reviewer = _FakeReviewer(permit)
    require_active_simnow_operational_window_permit(
        reviewer, permit, request, now_utc=1_790_000_002.0
    )

    reviewer.active_result = False
    with pytest.raises(CtpSimNowOperationalWindowError, match="revoked"):
        require_active_simnow_operational_window_permit(
            reviewer, permit, request, now_utc=1_790_000_003.0
        )
    with pytest.raises(CtpSimNowOperationalWindowError, match="scope mismatch"):
        require_active_simnow_operational_window_permit(
            reviewer, permit, replace(request, target_digest="8" * 64), now_utc=1_790_000_003.0
        )


def test_revocation_verifier_errors_are_redacted() -> None:
    request = _action()
    reviewer = _FakeReviewer(_permit(request))
    reviewer.fail_check = True
    with pytest.raises(
        CtpSimNowOperationalWindowError, match="revocation check unavailable"
    ) as caught:
        require_simnow_operational_window_permit(reviewer, request, now_utc=1_790_000_001.0)
    assert "untrusted reviewer detail" not in str(caught.value)


def test_reviewer_failures_are_redacted_and_wrong_contracts_reject() -> None:
    request = _action()
    reviewer = _FakeReviewer(_permit(request))
    reviewer.fail_issue = True
    with pytest.raises(CtpSimNowOperationalWindowError, match="review unavailable") as caught:
        require_simnow_operational_window_permit(reviewer, request, now_utc=1_790_000_001.0)
    assert "untrusted reviewer detail" not in str(caught.value)

    strict_request = CtpF14ActionRequest(
        runtime_id="runtime",
        environment="simnow",
        mode="simulation",
        preset="sandbox",
        account_fingerprint_sha256=_ACCOUNT,
        config_digest=_CONFIG,
        effective_digest=_EFFECTIVE,
        registration_digest=_REGISTRATION,
        artifact_set_digest=_ARTIFACTS,
        session=CtpF14SessionBinding("session-7", "20260925", 7, _SESSION),
        action_kind="SUBMIT",
        action_id="action-52",
        action_digest=_ACTION,
        approval_digest=_APPROVAL,
    )
    strict_claim = object.__new__(CtpF14ExternalAdmissionClaim)
    reviewer = _FakeReviewer(strict_claim)
    with pytest.raises(CtpSimNowOperationalWindowError, match="scope mismatch"):
        require_simnow_operational_window_permit(reviewer, request, now_utc=1_790_000_001.0)
    with pytest.raises(CtpF14AdmissionError, match="authority required"):
        claim_f14_action(strict_claim, strict_request)  # type: ignore[arg-type]
    with pytest.raises(CtpF14AdmissionError, match="authority required"):
        claim_f14_action(_permit(request), strict_request)  # type: ignore[arg-type]


def test_one_terminal_query_observation_is_accepted_without_snapshot_claim() -> None:
    request = _query_request()
    observation = _observation(request)
    verifier = _FakeQueryVerifier()

    require_simnow_single_query_observation(verifier, observation, expected_request=request)

    assert verifier.requests == [request]
    assert verifier.observations == [observation]
    assert observation.account_writer_exclusive is False
    assert observation.common_snapshot_verified is False
    assert observation.account_coverage_verified is False


@pytest.mark.parametrize(
    "changes",
    [
        {"b_is_last": False},
        {"response_error_code": 7},
        {"callback_count": 0},
        {"late_callback_count": 1},
    ],
)
def test_single_query_requires_one_clean_terminal_stream(changes: dict[str, object]) -> None:
    request = _query_request()
    observation = _observation(request, **changes)
    with pytest.raises(CtpSimNowOperationalWindowError, match="terminal evidence incomplete"):
        require_simnow_single_query_observation(
            _FakeQueryVerifier(), observation, expected_request=request
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("query_kind", CtpSimNowQueryKind.TRADES),
        ("request_id", 12),
        ("filters_digest", "8" * 64),
    ],
)
def test_single_query_observation_is_bound_to_exact_query_request(
    field: str, value: object
) -> None:
    expected = _query_request()
    other = replace(expected, **{field: value})
    with pytest.raises(CtpSimNowOperationalWindowError, match="scope mismatch"):
        require_simnow_single_query_observation(
            _FakeQueryVerifier(), _observation(expected), expected_request=other
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_fingerprint_sha256", "8" * 64),
        ("artifact_set_digest", "8" * 64),
        ("trading_day", "20260926"),
        ("connection_generation", 8),
        ("selected_front_pair", ("tcp://127.0.0.1:11002", "tcp://127.0.0.1:12002")),
    ],
)
def test_single_query_observation_is_bound_to_exact_account_session_and_fronts(
    field: str, value: object
) -> None:
    source_request = _query_request()
    changed_scope = _scope(**{field: value})
    changed_request = replace(source_request, scope=changed_scope)
    with pytest.raises(CtpSimNowOperationalWindowError, match="scope mismatch"):
        require_simnow_single_query_observation(
            _FakeQueryVerifier(),
            _observation(source_request),
            expected_request=changed_request,
        )


@pytest.mark.parametrize("result", [False, None, 1])
def test_unverified_single_query_source_is_rejected(result: object) -> None:
    request = _query_request()
    verifier = _FakeQueryVerifier()
    verifier.result = result
    with pytest.raises(CtpSimNowOperationalWindowError, match="source unverified"):
        require_simnow_single_query_observation(
            verifier, _observation(request), expected_request=request
        )


def test_single_query_verifier_errors_are_redacted() -> None:
    request = _query_request()

    class _FailingVerifier:
        def verify_single_query(self, observation: object, *, expected_request: object) -> bool:
            raise RuntimeError("untrusted verifier detail")

    with pytest.raises(
        CtpSimNowOperationalWindowError, match="source verification unavailable"
    ) as caught:
        require_simnow_single_query_observation(
            _FailingVerifier(),
            _observation(request),
            expected_request=request,  # type: ignore[arg-type]
        )
    assert "untrusted verifier detail" not in str(caught.value)


def test_several_single_streams_do_not_form_a_common_snapshot_contract() -> None:
    first = _query_request(
        query_id="query-1", query_kind=CtpSimNowQueryKind.ACCOUNT_FUNDS, request_id=1
    )
    second = _query_request(
        query_id="query-2", query_kind=CtpSimNowQueryKind.OPEN_ORDERS, request_id=2
    )
    verifier = _FakeQueryVerifier()

    require_simnow_single_query_observation(verifier, _observation(first), expected_request=first)
    require_simnow_single_query_observation(verifier, _observation(second), expected_request=second)

    assert _observation(first).common_snapshot_verified is False
    assert _observation(second).account_writer_exclusive is False
    with pytest.raises(CtpSimNowOperationalWindowError, match="scope mismatch"):
        require_simnow_single_query_observation(
            verifier,
            (_observation(first), _observation(second)),  # type: ignore[arg-type]
            expected_request=first,
        )
