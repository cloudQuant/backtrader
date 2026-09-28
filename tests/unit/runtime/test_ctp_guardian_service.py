"""Contract tests for the offline, fixed-operation guardian service core."""

from __future__ import annotations

import json
import threading

import pytest

from backtrader_runtime.ctp_guardian_service import (
    FIXED_OPERATION,
    GuardianService,
    GuardianServiceError,
    OperationResult,
    SERVICE_OPERATION_BUDGET_SECONDS,
    _make_request,
    _decode_response,
    request_readonly_preflight,
)


def _service(
    *,
    result=None,
    clock_values=(1_000, 1_100, 1_200),
    events=None,
    persist=True,
    verify=True,
):
    times = iter(clock_values)
    if result is None:
        result = OperationResult(True, True, True, True, "observation_complete")

    def clock():
        if events is not None:
            events.append("clock")
        return next(times)

    def verify_peer(peer):
        if events is not None:
            events.append(("verify", peer))
        return verify

    def persist_accepted(request_id, *, service_t0_monotonic_ns, deadline_monotonic_ns):
        if events is not None:
            events.append(("persist", request_id, service_t0_monotonic_ns, deadline_monotonic_ns))
        return persist

    def run_fixed_operation(operation, *, deadline_monotonic_ns):
        if events is not None:
            events.append(("run", operation, deadline_monotonic_ns))
        return result

    service = GuardianService(
        verify_peer,
        persist_accepted,
        run_fixed_operation,
        monotonic_ns=clock,
    )
    return service


def _response(service, *, peer="verified-local-client"):
    _request_id, raw = _make_request()
    return _decode_response(service.handle(raw, peer), expected_request_id=_request_id)


def test_request_contains_only_fixed_operation_and_request_identity():
    request_id, raw = _make_request()
    request = json.loads(raw)

    assert set(request) == {"schema", "operation", "request_id"}
    assert request["operation"] == FIXED_OPERATION
    assert request["request_id"] == request_id
    assert not any("path" in key or "argv" in key or "env" in key for key in request)
    assert SERVICE_OPERATION_BUDGET_SECONDS == 300


def test_operation_reason_is_a_fixed_code_not_arbitrary_text():
    with pytest.raises(GuardianServiceError, match="operation_result_invalid"):
        OperationResult(True, True, True, True, "account123")


@pytest.mark.parametrize("timeout", [True, 0, -1, float("nan"), 301])
def test_client_wait_timeout_is_bounded_locally(timeout):
    with pytest.raises(ValueError, match="guardian_client_timeout_out_of_range"):
        request_readonly_preflight(None, client_timeout_seconds=timeout)


def test_request_with_extra_path_or_duplicate_field_is_rejected_before_dispatch():
    events = []
    service = _service(events=events)
    request_id, raw = _make_request()
    request = json.loads(raw)
    request["receipt_path"] = "C:/private/receipt.json"
    request["budget_seconds"] = 1
    response = json.loads(service.handle(json.dumps(request).encode("ascii"), object()))

    assert response["state"] == "unknown"
    assert response["reason"] == "request_fields_invalid"
    assert response["request_id"] is None
    assert events == []

    duplicated = (
        b'{"schema":"backtrader_ctp_readonly_guardian_request.v1",'
        b'"operation":"ctp_readonly_preflight","request_id":"'
        + request_id.encode("ascii")
        + b'","request_id":"'
        + request_id.encode("ascii")
        + b'"}'
    )
    duplicate_response = json.loads(service.handle(duplicated, object()))
    assert duplicate_response["reason"] == "request_duplicate_key"
    assert events == []


def test_identity_validation_precedes_t0_and_failed_identity_never_records_or_runs():
    events = []
    service = _service(events=events, verify=False)
    result = _response(service)

    assert result.state == "unknown"
    assert result.reason == "client_identity_unverified"
    assert result.service_t0_monotonic_ns is None
    assert events == [("verify", "verified-local-client")]


def test_t0_deadline_acceptance_and_runner_order_are_fixed():
    events = []
    service = _service(events=events, clock_values=(100, 200, 300))
    result = _response(service)

    assert result.state == "observed"
    assert result.service_t0_monotonic_ns == 100
    expected_deadline = 100 + SERVICE_OPERATION_BUDGET_SECONDS * 1_000_000_000
    assert result.deadline_monotonic_ns == expected_deadline
    assert events[0] == ("verify", "verified-local-client")
    assert events[1] == "clock"
    assert events[2][0] == "persist"
    assert events[2][2:] == (100, expected_deadline)
    assert events[3] == "clock"
    assert events[4] == ("run", FIXED_OPERATION, expected_deadline)
    assert events[5] == "clock"


def test_unconfirmed_durable_acceptance_fails_closed_before_runner():
    events = []
    service = _service(events=events, persist=False)
    result = _response(service)

    assert result.state == "unknown"
    assert result.reason == "accepted_record_unverified"
    assert result.operation_observed is False
    assert not any(event[0] == "run" for event in events if isinstance(event, tuple))


def test_acceptance_that_finishes_at_deadline_does_not_dispatch():
    events = []
    deadline = SERVICE_OPERATION_BUDGET_SECONDS * 1_000_000_000
    service = _service(events=events, clock_values=(0, deadline, deadline + 1))
    result = _response(service)

    assert result.state == "unknown"
    assert result.reason == "service_deadline_exceeded"
    assert result.deadline_monotonic_ns == deadline
    assert not any(event[0] == "run" for event in events if isinstance(event, tuple))


@pytest.mark.parametrize(
    "operation_result, expected_state, expected_reason, expected_job_empty",
    [
        (
            OperationResult(True, None, True, True, "observation_complete"),
            "unknown",
            "job_empty_unverified",
            None,
        ),
        (
            OperationResult(True, False, True, True, "observation_complete"),
            "unknown",
            "job_empty_unverified",
            False,
        ),
        (
            OperationResult(False, True, True, True, "observation_missing"),
            "unknown",
            "observation_missing",
            True,
        ),
        (
            OperationResult(True, True, True, True, "observation_complete"),
            "observed",
            "readonly_observation_complete",
            True,
        ),
    ],
)
def test_operation_observation_and_job_empty_are_distinct_evidence(
    operation_result, expected_state, expected_reason, expected_job_empty
):
    result = _response(_service(result=operation_result))

    assert result.state == expected_state
    assert result.reason == expected_reason
    assert result.job_empty_observed is expected_job_empty
    if expected_state == "observed":
        assert result.native_close_observed is True
        assert result.receipt_durable is True


@pytest.mark.parametrize(
    "operation_result, expected_reason",
    [
        (
            OperationResult(True, True, None, True, "observation_complete"),
            "native_close_unverified",
        ),
        (
            OperationResult(True, True, True, None, "observation_complete"),
            "receipt_durability_unverified",
        ),
    ],
)
def test_observation_requires_native_close_and_durable_receipt(operation_result, expected_reason):
    result = _response(_service(result=operation_result))

    assert result.state == "unknown"
    assert result.reason == expected_reason


def test_late_runner_result_remains_unknown_even_if_it_reports_success():
    deadline = SERVICE_OPERATION_BUDGET_SECONDS * 1_000_000_000
    service = _service(
        result=OperationResult(True, True, True, True, "observation_complete"),
        clock_values=(0, 1, deadline),
    )
    result = _response(service)

    assert result.state == "unknown"
    assert result.reason == "service_deadline_exceeded"
    assert result.operation_observed is False
    assert result.job_empty_observed is True
    assert result.native_close_observed is True
    assert result.receipt_durable is True


def test_client_timeout_returns_immutable_unknown_and_discards_late_response():
    release = threading.Event()
    finished = threading.Event()
    service = _service()

    class DelayedTransport:
        def verify_server_identity(self):
            return True

        def exchange(self, raw_request):
            release.wait(2.0)
            response = service.handle(raw_request, "verified-local-client")
            finished.set()
            return response

    result = request_readonly_preflight(DelayedTransport(), client_timeout_seconds=0.01)
    assert result.state == "unknown"
    assert result.reason == "client_timeout"
    assert result.service_t0_monotonic_ns is None

    release.set()
    assert finished.wait(1.0)
    assert result.state == "unknown"
    assert result.reason == "client_timeout"


def test_missing_service_and_missing_transport_fail_closed():
    result = request_readonly_preflight(None)

    assert result.state == "unknown"
    assert result.reason == "guardian_service_unavailable"
    assert result.operation_observed is False
    assert result.job_empty_observed is None


def test_transport_without_server_identity_binding_fails_closed_before_exchange():
    class UnboundTransport:
        called = False

        def exchange(self, raw_request):
            self.called = True
            return b"{}"

    transport = UnboundTransport()
    result = request_readonly_preflight(transport, client_timeout_seconds=1.0)

    assert result.state == "unknown"
    assert result.reason == "guardian_transport_unverified"
    assert transport.called is False


def test_mismatched_or_invalid_service_response_is_unknown():
    class InvalidTransport:
        def verify_server_identity(self):
            return True

        def exchange(self, raw_request):
            return json.dumps(
                {
                    "schema": "backtrader_ctp_readonly_guardian_response.v1",
                    "state": "observed",
                    "reason": "readonly_observation_complete",
                    "request_id": "0" * 32,
                    "service_t0_monotonic_ns": 1,
                    "deadline_monotonic_ns": 2,
                    "operation_observed": True,
                    "job_empty_observed": True,
                    "native_close_observed": True,
                    "receipt_durable": True,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")

    result = request_readonly_preflight(InvalidTransport(), client_timeout_seconds=1.0)

    assert result.state == "unknown"
    assert result.reason == "guardian_response_unverified"
    assert result.service_t0_monotonic_ns is None


def test_observed_response_requires_both_operation_and_job_evidence():
    request_id, _raw = _make_request()
    invalid = {
        "schema": "backtrader_ctp_readonly_guardian_response.v1",
        "state": "observed",
        "reason": "readonly_observation_complete",
        "request_id": request_id,
        "service_t0_monotonic_ns": 1,
        "deadline_monotonic_ns": 2,
        "operation_observed": True,
        "job_empty_observed": None,
        "native_close_observed": True,
        "receipt_durable": None,
    }

    with pytest.raises(GuardianServiceError, match="response_binding_invalid"):
        _decode_response(
            json.dumps(invalid, sort_keys=True, separators=(",", ":")).encode("ascii"),
            expected_request_id=request_id,
        )


def test_observed_response_requires_the_fixed_completion_reason():
    request_id, _raw = _make_request()
    invalid = {
        "schema": "backtrader_ctp_readonly_guardian_response.v1",
        "state": "observed",
        "reason": "observation_complete",
        "request_id": request_id,
        "service_t0_monotonic_ns": 1,
        "deadline_monotonic_ns": 2,
        "operation_observed": True,
        "job_empty_observed": True,
        "native_close_observed": True,
        "receipt_durable": True,
    }

    with pytest.raises(GuardianServiceError, match="response_binding_invalid"):
        _decode_response(
            json.dumps(invalid, sort_keys=True, separators=(",", ":")).encode("ascii"),
            expected_request_id=request_id,
        )
