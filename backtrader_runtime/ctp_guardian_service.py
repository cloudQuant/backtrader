"""Fixed-operation guardian request protocol (unregistered service core).

This module contains the bounded, pathless request protocol and its service
state machine. It does not create a Windows service or named pipe, authenticate
an operating-system peer, load CTP configuration, or grant provider/write
authority. A deployment must supply a trusted peer verifier, durable acceptance
recorder, fixed operation runner, and transport adapter that verifies both
OS identities over a protected endpoint. The runner must use an OS process
supervisor and return its separately observed Job evidence; this protocol does
not turn caller-constructed evidence into provider or process authority.

The module is intentionally not wired into the default CLI. On Windows, a
production port still needs a reviewed named-pipe ACL, client-token/SID
verification, service lifetime watchdog, and independent Win32 acceptance.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Optional


REQUEST_SCHEMA = "backtrader_ctp_readonly_guardian_request.v1"
RESPONSE_SCHEMA = "backtrader_ctp_readonly_guardian_response.v1"
FIXED_OPERATION = "ctp_readonly_preflight"
SERVICE_OPERATION_BUDGET_SECONDS = 300
MAX_REQUEST_BYTES = 1024
MAX_RESPONSE_BYTES = 2048

_REQUEST_ID = re.compile(r"\A[0-9a-f]{32}\Z")
_NS_PER_SECOND = 1_000_000_000
_OPERATION_REASON_CODES = frozenset(
    {
        "observation_complete",
        "observation_missing",
        "operation_unverified",
        "worker_failed",
        "sdk_session_failed",
        "sdk_session_close_unverified",
        "receipt_write_unverified",
        "job_cleanup_unverified",
        "deadline_expired",
    }
)
_RESPONSE_REASON_CODES = _OPERATION_REASON_CODES | frozenset(
    {
        "accepted_record_unverified",
        "client_identity_unverified",
        "client_timeout",
        "guardian_client_start_failed",
        "guardian_response_unavailable",
        "guardian_response_unverified",
        "guardian_service_unavailable",
        "guardian_transport_unverified",
        "job_empty_unverified",
        "native_close_unverified",
        "operation_not_observed",
        "operation_result_invalid",
        "operation_runner_failed",
        "operation_unverified",
        "protocol_encoding_failed",
        "readonly_observation_complete",
        "receipt_durability_unverified",
        "request_binding_invalid",
        "request_duplicate_key",
        "request_fields_invalid",
        "request_invalid",
        "request_not_canonical",
        "request_size_invalid",
        "response_binding_invalid",
        "response_fields_invalid",
        "response_invalid",
        "response_not_canonical",
        "response_size_invalid",
        "service_clock_invalid",
        "service_clock_unavailable",
        "service_deadline_exceeded",
    }
)


class GuardianServiceError(ValueError):
    """A malformed or untrusted guardian protocol value."""


@dataclass(frozen=True)
class OperationResult:
    """Value-free result returned by the service-owned fixed operation.

    The configured runner must derive these facts from its own validated
    read-only evidence. Job-empty, native close, and durable receipt evidence
    remain separate because none alone proves the requested observation.
    """

    operation_observed: bool
    job_empty_observed: Optional[bool]
    native_close_observed: Optional[bool]
    receipt_durable: Optional[bool]
    reason: str

    def __post_init__(self) -> None:
        if type(self.operation_observed) is not bool:
            raise GuardianServiceError("operation_result_invalid")
        for field_value in (
            self.job_empty_observed,
            self.native_close_observed,
            self.receipt_durable,
        ):
            if field_value is not None and type(field_value) is not bool:
                raise GuardianServiceError("operation_result_invalid")
        if type(self.reason) is not str or self.reason not in _OPERATION_REASON_CODES:
            raise GuardianServiceError("operation_result_invalid")


@dataclass(frozen=True)
class GuardianResult:
    """Redacted client-visible result; it never grants execution authority."""

    state: str
    reason: str
    request_id: Optional[str]
    service_t0_monotonic_ns: Optional[int]
    deadline_monotonic_ns: Optional[int]
    operation_observed: bool
    job_empty_observed: Optional[bool]
    native_close_observed: Optional[bool] = None
    receipt_durable: Optional[bool] = None


@dataclass(frozen=True)
class _Request:
    request_id: str


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GuardianServiceError("request_duplicate_key")
        result[key] = value
    return result


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        raise GuardianServiceError("protocol_encoding_failed") from None


def _decode_request(raw: bytes) -> _Request:
    if type(raw) is not bytes or not raw or len(raw) > MAX_REQUEST_BYTES:
        raise GuardianServiceError("request_size_invalid")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_reject_duplicate_pairs)
    except GuardianServiceError:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise GuardianServiceError("request_invalid") from None
    if type(value) is not dict or set(value) != {
        "schema",
        "operation",
        "request_id",
    }:
        raise GuardianServiceError("request_fields_invalid")
    request_id = value["request_id"]
    if (
        value["schema"] != REQUEST_SCHEMA
        or value["operation"] != FIXED_OPERATION
        or type(request_id) is not str
        or _REQUEST_ID.fullmatch(request_id) is None
    ):
        raise GuardianServiceError("request_binding_invalid")
    if _canonical_json(value) != raw:
        raise GuardianServiceError("request_not_canonical")
    return _Request(request_id=request_id)


def _encode_response(result: GuardianResult) -> bytes:
    if result.reason not in _RESPONSE_REASON_CODES:
        raise GuardianServiceError("response_reason_invalid")
    body = {
        "schema": RESPONSE_SCHEMA,
        "state": result.state,
        "reason": result.reason,
        "request_id": result.request_id,
        "service_t0_monotonic_ns": result.service_t0_monotonic_ns,
        "deadline_monotonic_ns": result.deadline_monotonic_ns,
        "operation_observed": result.operation_observed,
        "job_empty_observed": result.job_empty_observed,
        "native_close_observed": result.native_close_observed,
        "receipt_durable": result.receipt_durable,
    }
    encoded = _canonical_json(body)
    if len(encoded) > MAX_RESPONSE_BYTES:
        raise GuardianServiceError("response_size_invalid")
    return encoded


def _decode_response(raw: bytes, *, expected_request_id: str) -> GuardianResult:
    if type(raw) is not bytes or not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise GuardianServiceError("response_size_invalid")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_reject_duplicate_pairs)
    except GuardianServiceError:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise GuardianServiceError("response_invalid") from None
    expected = {
        "schema",
        "state",
        "reason",
        "request_id",
        "service_t0_monotonic_ns",
        "deadline_monotonic_ns",
        "operation_observed",
        "job_empty_observed",
        "native_close_observed",
        "receipt_durable",
    }
    if type(value) is not dict or set(value) != expected:
        raise GuardianServiceError("response_fields_invalid")
    t0_ns = value["service_t0_monotonic_ns"]
    deadline_ns = value["deadline_monotonic_ns"]
    job_empty = value["job_empty_observed"]
    native_close = value["native_close_observed"]
    receipt_durable = value["receipt_durable"]
    if (
        value["schema"] != RESPONSE_SCHEMA
        or value["state"] not in ("observed", "unknown")
        or type(value["reason"]) is not str
        or value["reason"] not in _RESPONSE_REASON_CODES
        or value["request_id"] != expected_request_id
        or (t0_ns is not None and (type(t0_ns) is not int or t0_ns < 0))
        or (deadline_ns is not None and (type(deadline_ns) is not int or deadline_ns <= 0))
        or (t0_ns is None) != (deadline_ns is None)
        or (t0_ns is not None and deadline_ns <= t0_ns)
        or type(value["operation_observed"]) is not bool
        or (job_empty is not None and type(job_empty) is not bool)
        or (native_close is not None and type(native_close) is not bool)
        or (receipt_durable is not None and type(receipt_durable) is not bool)
        or (
            value["state"] == "observed"
            and (
                value["operation_observed"] is not True
                or job_empty is not True
                or native_close is not True
                or receipt_durable is not True
                or t0_ns is None
                or value["reason"] != "readonly_observation_complete"
            )
        )
    ):
        raise GuardianServiceError("response_binding_invalid")
    if _canonical_json(value) != raw:
        raise GuardianServiceError("response_not_canonical")
    return GuardianResult(
        state=value["state"],
        reason=value["reason"],
        request_id=value["request_id"],
        service_t0_monotonic_ns=t0_ns,
        deadline_monotonic_ns=deadline_ns,
        operation_observed=value["operation_observed"],
        job_empty_observed=job_empty,
        native_close_observed=native_close,
        receipt_durable=receipt_durable,
    )


class GuardianService:
    """Handle one fixed request after a transport authenticates its peer.

    ``verify_peer`` must validate transport-bound operating-system identity,
    not a request field. It returns the literal ``True`` only for the pinned
    client identity. ``persist_accepted`` must return the literal ``True`` only
    after the server-stamped request identity, T0, and fixed deadline are
    durably committed. ``run_fixed_operation`` is service-owned and receives
    only the fixed operation name and that same absolute deadline.
    """

    def __init__(
        self,
        verify_peer: Callable[[object], bool],
        persist_accepted: Callable[..., bool],
        run_fixed_operation: Callable[..., OperationResult],
        *,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if (
            not callable(verify_peer)
            or not callable(persist_accepted)
            or not callable(run_fixed_operation)
        ):
            raise TypeError("guardian_service_bindings_required")
        if not callable(monotonic_ns):
            raise TypeError("guardian_clock_required")
        self._verify_peer = verify_peer
        self._persist_accepted = persist_accepted
        self._run_fixed_operation = run_fixed_operation
        self._monotonic_ns = monotonic_ns

    def handle(self, raw_request: bytes, peer_context: object) -> bytes:
        """Validate, authenticate, stamp T0, and run the single readonly route."""

        try:
            request = _decode_request(raw_request)
        except GuardianServiceError as error:
            return _encode_response(
                GuardianResult("unknown", str(error), None, None, None, False, None)
            )
        try:
            authenticated = self._verify_peer(peer_context)
        except BaseException:
            authenticated = False
        if authenticated is not True:
            return _encode_response(
                GuardianResult(
                    "unknown",
                    "client_identity_unverified",
                    request.request_id,
                    None,
                    None,
                    False,
                    None,
                )
            )

        # The service-owned clock starts only after request shape and transport
        # identity have both been checked. Clients cannot supply T0 or a path.
        try:
            t0_ns = self._monotonic_ns()
        except BaseException:
            return _encode_response(
                GuardianResult(
                    "unknown",
                    "service_clock_unavailable",
                    request.request_id,
                    None,
                    None,
                    False,
                    None,
                )
            )
        if type(t0_ns) is not int or t0_ns < 0:
            return _encode_response(
                GuardianResult(
                    "unknown", "service_clock_invalid", request.request_id, None, None, False, None
                )
            )
        deadline_ns = t0_ns + SERVICE_OPERATION_BUDGET_SECONDS * _NS_PER_SECOND
        try:
            accepted = self._persist_accepted(
                request.request_id,
                service_t0_monotonic_ns=t0_ns,
                deadline_monotonic_ns=deadline_ns,
            )
        except BaseException:
            accepted = False
        if accepted is not True:
            return _encode_response(
                GuardianResult(
                    "unknown",
                    "accepted_record_unverified",
                    request.request_id,
                    t0_ns,
                    deadline_ns,
                    False,
                    None,
                )
            )
        try:
            accepted_ns = self._monotonic_ns()
        except BaseException:
            accepted_ns = deadline_ns
        if type(accepted_ns) is not int or accepted_ns < t0_ns:
            return _encode_response(
                GuardianResult(
                    "unknown",
                    "service_clock_invalid",
                    request.request_id,
                    t0_ns,
                    deadline_ns,
                    False,
                    None,
                )
            )
        if accepted_ns >= deadline_ns:
            return _encode_response(
                GuardianResult(
                    "unknown",
                    "service_deadline_exceeded",
                    request.request_id,
                    t0_ns,
                    deadline_ns,
                    False,
                    None,
                )
            )
        operation_observed = False
        job_empty_observed: Optional[bool] = None
        native_close_observed: Optional[bool] = None
        receipt_durable: Optional[bool] = None
        reason = "operation_unverified"
        try:
            outcome = self._run_fixed_operation(FIXED_OPERATION, deadline_monotonic_ns=deadline_ns)
            if type(outcome) is not OperationResult:
                raise GuardianServiceError("operation_result_invalid")
            if outcome.reason not in _OPERATION_REASON_CODES:
                raise GuardianServiceError("operation_result_invalid")
            operation_observed = outcome.operation_observed
            job_empty_observed = outcome.job_empty_observed
            native_close_observed = outcome.native_close_observed
            receipt_durable = outcome.receipt_durable
            reason = outcome.reason
        except BaseException:
            reason = "operation_runner_failed"

        try:
            completed_ns = self._monotonic_ns()
        except BaseException:
            completed_ns = deadline_ns
        deadline_expired = (
            type(completed_ns) is not int or completed_ns < t0_ns or completed_ns >= deadline_ns
        )
        if deadline_expired:
            # A late worker result is diagnostic only; it cannot turn the
            # final service outcome into observed.
            return _encode_response(
                GuardianResult(
                    "unknown",
                    "service_deadline_exceeded",
                    request.request_id,
                    t0_ns,
                    deadline_ns,
                    False,
                    job_empty_observed,
                    native_close_observed,
                    receipt_durable,
                )
            )
        if job_empty_observed is not True:
            reason = "job_empty_unverified"
        elif native_close_observed is not True:
            reason = "native_close_unverified"
        elif receipt_durable is not True:
            reason = "receipt_durability_unverified"
        elif not operation_observed:
            reason = "operation_not_observed" if reason == "operation_unverified" else reason
        state = (
            "observed"
            if (
                operation_observed is True
                and job_empty_observed is True
                and native_close_observed is True
                and receipt_durable is True
            )
            else "unknown"
        )
        return _encode_response(
            GuardianResult(
                state,
                "readonly_observation_complete" if state == "observed" else reason,
                request.request_id,
                t0_ns,
                deadline_ns,
                operation_observed,
                job_empty_observed,
                native_close_observed,
                receipt_durable,
            )
        )


def _make_request() -> tuple[str, bytes]:
    request_id = uuid.uuid4().hex
    raw = _canonical_json(
        {
            "schema": REQUEST_SCHEMA,
            "operation": FIXED_OPERATION,
            "request_id": request_id,
        }
    )
    if len(raw) > MAX_REQUEST_BYTES:
        raise GuardianServiceError("request_size_invalid")
    return request_id, raw


def request_readonly_preflight(
    transport: Optional[object],
    *,
    client_timeout_seconds: float = 30.0,
) -> GuardianResult:
    """Send the fixed request and return UNKNOWN when service evidence is absent.

    ``transport`` is a deployment-owned object with ``exchange(bytes) ->
    bytes`` and ``verify_server_identity() -> True``. That verifier must bind
    the response channel to the pinned guardian service OS identity over a
    protected endpoint. An object that implements only ``exchange`` is
    rejected. The client wait timeout is independent of the server operation
    deadline. On timeout this function returns an immutable UNKNOWN result;
    a late transport response is discarded and cannot upgrade it. No concrete
    Windows transport is provided here, so this function is not a production
    connection path.
    """

    if (
        type(client_timeout_seconds) not in (int, float)
        or not math.isfinite(float(client_timeout_seconds))
        or client_timeout_seconds <= 0
        or client_timeout_seconds > SERVICE_OPERATION_BUDGET_SECONDS
    ):
        raise ValueError("guardian_client_timeout_out_of_range")
    request_id, raw_request = _make_request()
    if transport is None:
        return GuardianResult(
            "unknown", "guardian_service_unavailable", request_id, None, None, False, None
        )
    verify_server_identity = getattr(transport, "verify_server_identity", None)
    exchange_request = getattr(transport, "exchange", None)
    if not callable(verify_server_identity) or not callable(exchange_request):
        return GuardianResult(
            "unknown", "guardian_transport_unverified", request_id, None, None, False, None
        )

    completed = threading.Event()
    response_holder: list[object] = []

    def exchange() -> None:
        try:
            if verify_server_identity() is not True:
                response_holder.append("transport_unverified")
                return
            response_holder.append(exchange_request(raw_request))
        except BaseException:
            response_holder.append(None)
        finally:
            completed.set()

    try:
        worker = threading.Thread(target=exchange, name="ctp-guardian-request", daemon=True)
        worker.start()
    except BaseException:
        return GuardianResult(
            "unknown", "guardian_client_start_failed", request_id, None, None, False, None
        )
    if not completed.wait(float(client_timeout_seconds)):
        return GuardianResult("unknown", "client_timeout", request_id, None, None, False, None)
    if response_holder and response_holder[0] == "transport_unverified":
        return GuardianResult(
            "unknown", "guardian_transport_unverified", request_id, None, None, False, None
        )
    if not response_holder or type(response_holder[0]) is not bytes:
        return GuardianResult(
            "unknown", "guardian_response_unavailable", request_id, None, None, False, None
        )
    try:
        return _decode_response(response_holder[0], expected_request_id=request_id)
    except GuardianServiceError:
        return GuardianResult(
            "unknown", "guardian_response_unverified", request_id, None, None, False, None
        )


__all__ = [
    "FIXED_OPERATION",
    "GuardianResult",
    "GuardianService",
    "GuardianServiceError",
    "OperationResult",
    "SERVICE_OPERATION_BUDGET_SECONDS",
    "request_readonly_preflight",
]
