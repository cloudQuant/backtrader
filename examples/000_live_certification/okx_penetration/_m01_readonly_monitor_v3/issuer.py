"""Fixed OKX M01 V3 current-account case issuer.

The route owns its C01 fresh-read factory, invocation token, one WebSocket Job,
private event journal, drain, close, case predicate, audit and formal result.
It returns a case PASS only from a fresh same-invocation C01 proof and normally
closed owned monitor Job after exact M01 case validation.
"""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from . import current_reader
from _m01_readonly_monitor_v2 import current_types, job_supervisor, worker
from _certification import m01_private_monitor_v2 as contract


PROFILE = "OKX_GLOBAL_DEMO_M01_CASE_V3"
CASE_ID = "M01"
CASE_STATUS = "CASE_NOT_ACCEPTED"
MAX_JOURNAL_BYTES = worker.MAX_OUTPUT_BYTES
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_ORPHANED_JOURNAL_WRITERS: list[Any] = []
_ORPHANED_CASE_CUSTODY: list[Any] = []
_CASE_SEAL = object()
_SEALED_OUTCOMES: dict[int, Any] = {}
_OUTCOME_LOCK = __import__("threading").RLock()
_SAFE_REASON = re.compile(r"[a-z0-9_]{1,64}\Z")


class IssuerError(ValueError):
    """Fixed public-safe failure codes only."""

    def __init__(self, code: str):
        if type(code) is not str or not worker._SAFE_REASON.fullmatch(code):
            code = "m01_v2_issuer_blocked"
        super().__init__(code)
        self.code = code


class _PrivateJournalWriter:
    """Append-only, bounded private event journal with owner-only creation."""

    def __init__(self, directory: Any, private_api: Any):
        self.directory = directory
        self.api = private_api
        self.path = directory.prepare_child("m01-private-events-v3.bin")
        self.parts: list[bytes] = []
        self.total = 0
        self.failed = False
        self.handle = None
        sid = private_api.current_sid()
        with private_api.descriptor(sid, directory=False) as attributes:
            handle = private_api.CreateFileW(
                str(self.path),
                0x40000000 | 0x00020000 | 0x00000080,
                0,
                ctypes.byref(attributes),
                1,
                0x80200000,
                None,
            )
        if handle == _INVALID_HANDLE:
            raise IssuerError("private_journal_create_failed")
        self.handle = int(handle)
        try:
            self.identity = private_api.info(self.handle, directory=False)
            private_api.verify_acl(self.handle, sid)
        except BaseException:
            self.close()
            raise IssuerError("private_journal_identity_failed") from None

    def write_bytes(self, payload: bytes) -> None:
        try:
            if type(payload) is not bytes or self.total + len(payload) > MAX_JOURNAL_BYTES:
                raise IssuerError("private_journal_bound")
            self.directory.verify()
            sid = self.api.current_sid()
            self.api.verify_acl(self.handle, sid)
            if self.api.info(self.handle, directory=False) != self.identity:
                raise IssuerError("private_journal_identity_changed")
            offset = 0
            while offset < len(payload):
                chunk = payload[offset : offset + 64 * 1024]
                count = wintypes.DWORD()
                buffer = ctypes.create_string_buffer(chunk)
                if not self.api.WriteFile(
                    self.handle, buffer, len(chunk), ctypes.byref(count), None
                ):
                    raise IssuerError("private_journal_write_failed")
                if not 0 < count.value <= len(chunk):
                    raise IssuerError("private_journal_short_write")
                offset += count.value
            if not self.api.FlushFileBuffers(self.handle):
                raise IssuerError("private_journal_flush_failed")
            self.total += len(payload)
            self.parts.append(payload)
        except BaseException:
            self.failed = True
            raise

    def close(self) -> None:
        if self.handle is None:
            return
        handle = self.handle
        self.handle = None
        try:
            if not self.api.CloseHandle(handle):
                self.handle = handle
                raise IssuerError("private_journal_close_uncertain")
        except BaseException:
            self.failed = True
            raise


def _read_private_journal(path: Path, private_api: Any, maximum: int) -> bytes:
    kernel = job_supervisor._winapi()
    handle = kernel.CreateFileW(
        str(path),
        0x80000000 | 0x00020000 | 0x00000080,
        0x00000001,
        None,
        3,
        0x00200080,
        None,
    )
    if handle in (None, 0, _INVALID_HANDLE):
        raise IssuerError("private_journal_read_unavailable")
    handle = int(handle)
    try:
        before = private_api.info(handle, directory=False)
        private_api.verify_acl(handle, private_api.current_sid())
        output = bytearray()
        while len(output) <= maximum:
            size = min(64 * 1024, maximum + 1 - len(output))
            buffer = ctypes.create_string_buffer(size)
            received = wintypes.DWORD()
            if not kernel.ReadFile(handle, buffer, size, ctypes.byref(received), None):
                raise IssuerError("private_journal_read_failed")
            if not received.value:
                break
            output.extend(buffer.raw[: received.value])
        after = private_api.info(handle, directory=False)
        if before != after or len(output) > maximum:
            raise IssuerError("private_journal_read_identity")
        return bytes(output)
    finally:
        if not kernel.CloseHandle(handle):
            raise IssuerError("private_journal_read_close_uncertain")


def _close_ok(receipt: Any) -> bool:
    if (
        type(receipt) is not job_supervisor.ObserverCloseReceipt
        or type(receipt.worker_receipt) is not job_supervisor.ObserverWorkerReceipt
        or receipt.status != worker.CASE_STATUS
        or receipt.worker_receipt.status != worker.CASE_STATUS
    ):
        return False
    required_true = (
        "job_assigned_before_resume",
        "process_resumed",
        "stdin_closed",
        "stdout_eof",
        "stderr_eof",
        "process_exit_observed",
        "drain_threads_joined",
        "handles_closed",
        "socket_closed",
        "normal_websocket_close",
        "control_thread_joined",
        "worker_receipt_valid",
        "runtime_files_held_through_exit",
        "runtime_files_closed",
    )
    if any(getattr(receipt, name, False) is not True for name in required_true):
        return False
    return (
        receipt.containment == "windows_job"
        and receipt.process_exit_code == 0
        and receipt.job_active_count == 0
        and receipt.forced_termination is False
        and receipt.timed_out is False
        and receipt.handle_close_failed is False
    )


def _contract_receipts(
    proof: current_types.CurrentReadProof,
    request: worker.LaunchRequest,
    context: Any,
    ready: Any,
    close: Any,
    events: tuple[bytes, ...],
) -> tuple[Any, Any, Any]:
    child = close.worker_receipt
    if child is None:
        raise IssuerError("worker_receipt_missing")
    c_launch = contract.LaunchRequest(
        run_nonce=request.run_nonce,
        parent_pid=request.parent_pid,
        worker_source_sha256=request.worker_source_sha256,
        account_scope_sha256=request.account_scope_sha256,
        credential_binding_sha256=request.credential_binding_sha256,
        current_rest_read_receipt_sha256=request.current_rest_read_receipt_sha256,
        owner_invocation_sha256=request.owner_invocation_sha256,
        expected_rest_uid=proof.expected_rest_uid,
        timeout_ms=request.event_timeout_ms,
        credential_packet=request.credential_packet,
    )
    c_worker = contract.WorkerReceipt(
        run_nonce=child.run_nonce,
        parent_pid=child.parent_pid,
        worker_pid=child.worker_pid,
        worker_source_sha256=child.worker_source_sha256,
        account_scope_sha256=child.account_scope_sha256,
        credential_binding_sha256=child.credential_binding_sha256,
        current_rest_read_receipt_sha256=child.current_rest_read_receipt_sha256,
        owner_invocation_sha256=child.owner_invocation_sha256,
        connection_id_sha256=child.connection_id_sha256,
        connection_event_id=child.connection_event_id,
        readiness_event_id=child.readiness_event_id,
        event_count=child.event_count,
        event_journal_sha256=child.event_journal_sha256,
        login_acknowledged=child.login_acknowledged,
        subscription_ack_ids=child.subscription_ack_ids,
        private_data_event_count=child.balance_position_payload_count,
        balance_snapshot_observed=child.balance_snapshot_observed,
        ready_sent=child.ready_sent,
        socket_closed=child.socket_closed,
        normal_websocket_close=child.normal_websocket_close,
        control_thread_joined=child.control_thread_joined,
        reason=child.reason,
        status=child.status,
    )
    c_process = contract.ProcessLifecycleReceipt(
        run_nonce=close.run_nonce,
        parent_pid=close.parent_pid,
        worker_pid=close.worker_pid,
        worker_source_sha256=close.worker_source_sha256,
        containment=close.containment,
        assigned_before_resume=close.job_assigned_before_resume,
        process_resumed=close.process_resumed,
        stdin_closed=close.stdin_closed,
        stdout_eof=close.stdout_eof,
        stderr_eof=close.stderr_eof,
        process_exit_observed=close.process_exit_observed,
        process_exit_code=close.process_exit_code,
        job_active_count=close.job_active_count,
        drain_threads_joined=close.drain_threads_joined,
        handles_closed=close.handles_closed,
        handle_close_failed=close.handle_close_failed,
        runtime_files_held_through_exit=close.runtime_files_held_through_exit,
        runtime_files_closed=close.runtime_files_closed,
        timed_out=close.timed_out,
        forced_termination=close.forced_termination,
        socket_closed=close.socket_closed,
        normal_websocket_close=close.normal_websocket_close,
        worker_receipt_valid=close.worker_receipt_valid,
    )
    # The exact ready object is checked against the current context before this
    # conversion; it is not deserialized from private files or caller JSON.
    if ready.run_nonce != context.run_nonce:
        raise IssuerError("ready_nonce_mismatch")
    return c_launch, c_worker, c_process


@dataclass(frozen=True, repr=False, eq=False)
class _SealedM01Outcome:
    result: Any
    invocation_sha256: str
    audit_sha256: str
    _seal: object

    def __reduce__(self):
        raise TypeError("m01_v3_outcome_not_serializable")

    def __reduce_ex__(self, _protocol):
        raise TypeError("m01_v3_outcome_not_serializable")


def _iso_ms(value: int) -> str:
    if type(value) is not int or value < 0:
        raise IssuerError("case_time_invalid")
    return (
        datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _safe_reason(error: BaseException, fallback: str) -> str:
    value = getattr(error, "code", None) or getattr(error, "reason", None)
    return value if type(value) is str and _SAFE_REASON.fullmatch(value) else fallback


def _retain_orphan(*items: Any) -> None:
    if len(_ORPHANED_CASE_CUSTODY) >= 8:
        raise IssuerError("orphan_custody_capacity")
    _ORPHANED_CASE_CUSTODY.append(tuple(items))


def _close_leases(lease_set: Any) -> None:
    error = None
    for _ in range(3):
        try:
            lease_set.close()
            return
        except BaseException as exc:
            error = exc
    raise IssuerError("source_lease_close_uncertain") from error


def _source_facts(proof: Any) -> str:
    packet = worker.strict_json(proof._credential_packet, limit=worker.MAX_CREDENTIAL_PACKET_BYTES)
    if type(packet) is not dict or set(packet) != {
        "api_key",
        "expected_rest_uid",
        "passphrase",
        "secret_key",
    }:
        raise IssuerError("credential_proof_shape")
    if packet["expected_rest_uid"] != proof.expected_rest_uid:
        raise IssuerError("credential_uid_mismatch")
    credential_map = {
        "OKX_DEMO_API_KEY": packet["api_key"],
        "OKX_DEMO_SECRET": packet["secret_key"],
    }
    account_ref = current_reader._account_ref(credential_map, proof.expected_rest_uid)
    if type(account_ref) is not str or not re.fullmatch(r"[0-9a-f]{64}", account_ref):
        raise IssuerError("account_ref_invalid")
    return account_ref


def _load_case_contract() -> tuple[Any, Any, Any, Any, Any]:
    models = importlib.import_module("_certification.models")
    cases = importlib.import_module("_certification.cases")
    strategy = importlib.import_module("M01_strategy")
    runner = importlib.import_module("_certification.runner")
    expected_origins = (
        (models, current_reader.VENUE / "_certification" / "models.py"),
        (cases, current_reader.VENUE / "_certification" / "cases.py"),
        (strategy, current_reader.VENUE / "cases" / "M01" / "M01_strategy.py"),
        (runner, current_reader.VENUE / "_certification" / "runner.py"),
    )
    if any(
        type(getattr(module, "__file__", None)) is not str
        or Path(module.__file__).resolve() != expected.resolve()
        for module, expected in expected_origins
    ):
        raise IssuerError("m01_case_module_origin_mismatch")
    spec = cases.CASES.get(CASE_ID)
    if (
        spec is None
        or spec != strategy.CASE_SPEC
        or strategy.CASE_ID != CASE_ID
        or tuple(strategy.PROOF_FIELDS)
        != (
            "connection_session_id",
            "readiness_session_id",
            "connection_event_id",
            "readiness_event_id",
        )
        or spec.action != "inspect_monitor_connect"
        or spec.event != "monitor_ready"
        or spec.risk is not models.Risk.READ
        or spec.required != ("source_session_id", "evidence_window_id")
        or spec.optional != ()
    ):
        raise IssuerError("m01_case_contract_changed")
    return models, cases, strategy, runner, spec


def _event_index(context: Any, run_nonce: str, expected_id: str) -> tuple[int, Any]:
    matches = []
    previous_ms = 0
    previous_mono = 0
    for expected_sequence, event in enumerate(context._events, start=1):
        if type(event) is not job_supervisor.PrivateEvent:
            raise IssuerError("parent_event_type")
        if type(event.sequence) is not int or event.sequence != expected_sequence:
            raise IssuerError("parent_event_sequence")
        if (
            type(event.received_utc_ms) is not int
            or type(event.received_monotonic_ns) is not int
            or event.received_utc_ms < previous_ms
            or event.received_monotonic_ns <= previous_mono
            or hashlib.sha256(event.raw_bytes).hexdigest() != event.raw_sha256
        ):
            raise IssuerError("parent_event_time_or_digest")
        previous_ms = event.received_utc_ms
        previous_mono = event.received_monotonic_ns
        event_id = contract._event_id(run_nonce, event.sequence, event.raw_bytes)
        if event_id == expected_id:
            matches.append((event.sequence, event))
    if len(matches) != 1:
        raise IssuerError("case_event_id_missing_or_reused")
    return matches[0]


def _validate_case_proof(
    *,
    proof: Any,
    invocation: Any,
    request: Any,
    context: Any,
    ready: Any,
    quiet: Any,
    drain: Any,
    close: Any,
    summary: Any,
    raw_events: tuple[bytes, ...],
    account_capture: Any,
    case_completed_ms: int,
) -> tuple[Any, Any, Any, str, str, str]:
    models, _cases, _strategy, runner, spec = _load_case_contract()
    if (
        type(context) is not job_supervisor.ObserverContext
        or type(request) is not worker.LaunchRequest
        or type(ready) is not job_supervisor.ObserverReady
        or type(quiet) is not job_supervisor.QuietWindow
        or type(drain) is not job_supervisor.ObservationDrain
        or type(close) is not job_supervisor.ObserverCloseReceipt
        or type(proof) is not current_types.CurrentReadProof
        or context.request is not request
        or context._ready is not ready
        or context._closed is not True
        or context._worker_receipt is not close.worker_receipt
        or proof.invocation is not invocation
        or proof.source_map_sha256 != invocation.source_map_sha256
        or current_types._ISSUED.get(id(proof)) is not proof
        or id(proof) not in current_types._CONSUMED
        or type(account_capture) is not current_reader.VerifiedAccountConfigurationRead
        or account_capture.invocation is not invocation
        or current_reader.verified_account_configuration_read(proof, invocation)
        is not account_capture
        or type(raw_events) is not tuple
        or raw_events != tuple(item.raw_bytes for item in context._events)
        or tuple(context._raw_events) != raw_events
        or type(case_completed_ms) is not int
        or case_completed_ms < proof.completed_ms
        or not invocation.started_ms
        <= account_capture.request_started_ms
        <= account_capture.response_received_ms
        <= proof.completed_ms
        or account_capture.response_received_ms > case_completed_ms
        or type(account_capture.capture_id) is not str
        or not 1 <= len(account_capture.capture_id) <= 128
        or any(
            type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in (
                account_capture.request_sha256,
                account_capture.response_sha256,
                account_capture.source_id_sha256,
            )
        )
    ):
        raise IssuerError("m01_invocation_proof_binding")
    expected_journal_sha256 = hashlib.sha256(worker.encode_journal(list(raw_events))).hexdigest()
    if (
        request.parent_pid != invocation.parent_pid
        or request.run_nonce != context.run_nonce
        or request.current_rest_read_receipt_sha256 != proof.receipt_sha256
        or request.account_scope_sha256 != proof.account_scope_sha256
        or request.credential_binding_sha256 != proof.credential_binding_sha256
        or request.owner_invocation_sha256 != proof.owner_invocation_sha256
        or ready.parent_pid != invocation.parent_pid
        or ready.worker_pid != context._control.get("pid")
        or ready.worker_source_sha256 != request.worker_source_sha256
        or ready.current_rest_read_receipt_sha256 != proof.receipt_sha256
        or ready.account_scope_sha256 != proof.account_scope_sha256
        or ready.credential_binding_sha256 != proof.credential_binding_sha256
        or ready.owner_invocation_sha256 != proof.owner_invocation_sha256
        or ready.subscription_ack_ids != (worker.SUBSCRIPTION_ID,)
        or ready.balance_snapshot_observed is not False
        or quiet.run_nonce != context.run_nonce
        or quiet.quiet is not True
        or quiet.partial_frame_clear is not True
        or type(quiet.command_id) is not str
        or re.fullmatch(r"[0-9a-f]{32}", quiet.command_id) is None
        or type(quiet.cursor_before) is not int
        or quiet.cursor_before != len(raw_events)
        or quiet.cursor_after != len(raw_events)
        or type(quiet.started_monotonic_ns) is not int
        or type(quiet.ended_monotonic_ns) is not int
        or quiet.ended_monotonic_ns - quiet.started_monotonic_ns < worker.MAX_QUIET_MS * 1_000_000
        or drain.run_nonce != context.run_nonce
        or type(drain.cursor) is not int
        or drain.cursor != len(raw_events)
        or type(drain.event_count) is not int
        or drain.event_count != len(raw_events)
        or drain.events != tuple(context._events)
        or drain.latest_event_sha256 != context._events[-1].raw_sha256
        or drain.event_journal_sha256 != expected_journal_sha256
        or not _close_ok(close)
        or close.run_nonce != request.run_nonce
        or close.parent_pid != invocation.parent_pid
        or close.worker_pid != context._control.get("pid")
    ):
        raise IssuerError("m01_current_owner_lifecycle")
    if len(raw_events) != close.worker_receipt.event_count:
        raise IssuerError("m01_event_count")
    protocol = contract.validate_event_journal(
        raw_events, expected_rest_uid=proof.expected_rest_uid, run_nonce=request.run_nonce
    )
    if type(summary) is not contract.EventJournalSummary or summary != protocol:
        raise IssuerError("m01_protocol_summary_binding")
    journal_sha = expected_journal_sha256
    c_launch, c_worker, c_process = _contract_receipts(
        proof, request, context, ready, close, raw_events
    )
    assessment = contract.assess_m01(
        launch=c_launch,
        worker=c_worker,
        process=c_process,
        raw_events=raw_events,
        journal_sha256=journal_sha,
    )
    if (
        assessment.status != CASE_STATUS
        or not assessment.eligible_for_future_fixed_issuer
        or assessment.balance_snapshot_observed is not False
        or assessment.balance_position_payload_count != c_worker.private_data_event_count
        or protocol.private_data_event_count != c_worker.private_data_event_count
        or protocol.connection_id_sha256 != ready.connection_id_sha256
        or protocol.connection_event_id != ready.connection_event_id
        or protocol.readiness_event_id != ready.readiness_event_id
        or ready.connection_event_id == ready.readiness_event_id
    ):
        raise IssuerError("m01_monitor_contract_incomplete")

    connection_sequence, connection_event = _event_index(
        context, request.run_nonce, protocol.connection_event_id
    )
    readiness_sequence, readiness_event = _event_index(
        context, request.run_nonce, protocol.readiness_event_id
    )
    if connection_sequence >= readiness_sequence:
        raise IssuerError("m01_ready_before_connection")
    if not (
        proof.completed_ms
        <= connection_event.received_utc_ms
        < readiness_event.received_utc_ms
        <= case_completed_ms
    ):
        raise IssuerError("m01_event_outside_invocation")
    login = worker.strict_json(connection_event.raw_bytes, limit=worker.MAX_EVENT_BYTES)
    subscribe = worker.strict_json(readiness_event.raw_bytes, limit=worker.MAX_EVENT_BYTES)
    session_id = login.get("connId") if type(login) is dict else None
    if (
        type(session_id) is not str
        or not 1 <= len(session_id) <= contract.MAX_CONNECTION_ID_CHARS
        or any(ord(char) < 33 or ord(char) > 126 for char in session_id)
        or subscribe.get("connId") != session_id
        or subscribe.get("id") != worker.SUBSCRIPTION_ID
        or subscribe.get("arg") != worker.BALANCE_POSITION_SUBSCRIPTION
    ):
        raise IssuerError("m01_ws_session_or_ready_value")
    account_ref = _source_facts(proof)
    now = _iso_ms(case_completed_ms)
    event_time = _iso_ms(readiness_event.received_utc_ms)
    window_start = _iso_ms(invocation.started_ms)
    window_id = f"m01-v3-{invocation.nonce}"
    correlation_id = f"m01-{invocation.nonce}-correlation"
    client_id = f"m01-{invocation.nonce}-client"
    operation_id = f"m01-{invocation.nonce}-read"
    capture_request_id = account_capture.capture_id
    capture_response_id = account_capture.response_sha256
    capture_started = _iso_ms(account_capture.request_started_ms)
    capture_received = _iso_ms(account_capture.response_received_ms)
    source = "provider:okx"
    ws_instance = "okx-global-demo-private-ws"
    c01_instance = "okx-c01-fresh-current-read"
    attestation = models.Attestation(
        contract_version=2,
        binding=models.Binding("okx", "demo", "demo", account_ref),
        provider_attestation_id=f"m01-v3-{hashlib.sha256((proof.receipt_sha256 + request.run_nonce).encode()).hexdigest()}",
        provider_session_id=session_id,
        channels=(
            models.Channel(c01_instance, "account_configuration_get", "command_response"),
            models.Channel(ws_instance, "monitor_ready", "independent_event"),
            models.Channel(c01_instance, "signed_account_queries", "query"),
            models.Channel(c01_instance, "stable_account_capture", "state_snapshot"),
        ),
        source=source,
        observed_at=now,
        payload={
            "provider_venue": "okx",
            "provider_environment_kind": "demo",
            "provider_account_id": account_ref,
            "provider_environment_id": "okx-global-demo",
            "close_semantics": "local_transport_only",
        },
    )
    action_plan = models.ActionPlan(
        operations=(
            models.PlannedOperation(
                operation_id=operation_id,
                phase="execute",
                kind="read",
                client_order_id=None,
                target_order_id=None,
                symbol=None,
                side=None,
                quantity=Decimal(0),
                price=Decimal(0),
                order_type=None,
                position_id=None,
                reduce_only=False,
                instrument_spec_id=None,
            ),
        ),
        order_count=0,
        total_quantity=__import__("decimal").Decimal(0),
        total_notional=__import__("decimal").Decimal(0),
        notional_currency="USDT",
    )
    action = models.Action(
        case_id=CASE_ID,
        name=spec.action,
        risk=spec.risk,
        binding=attestation.binding,
        params={"source_session_id": session_id, "evidence_window_id": window_id},
        correlation_id=correlation_id,
        client_id=client_id,
        attested_session_id=session_id,
        evidence_window_id=window_id,
        plan=action_plan,
    )
    operation = models.OperationEvidence(
        operation_id=operation_id,
        phase="execute",
        kind="read",
        accepted=True,
        provider_request_id=capture_request_id,
        provider_order_id=None,
        client_order_id=None,
        target_order_id=None,
        symbol=None,
        side=None,
        quantity=Decimal(0),
        price=Decimal(0),
        order_type=None,
        position_id=None,
        reduce_only=False,
        instrument_spec_id=None,
        source_instance=c01_instance,
        source_channel="account_configuration_get",
        occurred_at=capture_started,
        observed_at=capture_received,
    )
    receipt = models.Receipt(
        action=spec.action,
        correlation_id=correlation_id,
        client_id=client_id,
        accepted=True,
        binding=attestation.binding,
        source=source,
        source_instance=c01_instance,
        source_channel="account_configuration_get",
        occurred_at=capture_started,
        observed_at=capture_received,
        provider_response_id=capture_response_id,
        operations=(operation,),
        created_order_ids=(),
        payload={"current_rest_read_receipt_sha256": proof.receipt_sha256},
    )
    observation = models.Observation(
        kind=spec.event,
        correlation_id=correlation_id,
        client_id=client_id,
        binding=attestation.binding,
        source=source,
        source_instance=ws_instance,
        source_channel="monitor_ready",
        occurred_at=event_time,
        observed_at=event_time,
        evidence_window_id=window_id,
        provider_event_id=protocol.readiness_event_id,
        operation_ids=(operation_id,),
        provider_order_ids=(),
        payload={
            "source_session_id": session_id,
            "evidence_window_id": window_id,
            "connection_session_id": session_id,
            "readiness_session_id": session_id,
            "connection_event_id": protocol.connection_event_id,
            "readiness_event_id": protocol.readiness_event_id,
            "provider_request_ids": [capture_request_id],
            "provider_response_id": capture_response_id,
            "window_start": window_start,
            "window_end": now,
            "connection_id_sha256": protocol.connection_id_sha256,
            "readiness_raw_sha256": readiness_event.raw_sha256,
        },
    )
    config = SimpleNamespace(venue="okx", environment=SimpleNamespace(name="demo", kind="demo"))
    runner._attest(config, account_ref, attestation)
    dispatch = datetime.fromtimestamp(invocation.started_ms / 1000, tz=timezone.utc)
    created = runner._validate_receipt(action, receipt, attestation, dispatch)
    runner._observe(action, receipt, attestation, [observation], created, dispatch)
    return models, action, receipt, observation, account_ref, session_id


def _mint_outcome(result: Any, invocation: Any, audit_sha256: str) -> _SealedM01Outcome:
    token = _SealedM01Outcome(
        result=result,
        invocation_sha256=current_types.invocation_digest(invocation),
        audit_sha256=audit_sha256,
        _seal=_CASE_SEAL,
    )
    with _OUTCOME_LOCK:
        _SEALED_OUTCOMES[id(token)] = token
    return token


def _consume_outcome(token: _SealedM01Outcome) -> Any:
    with _OUTCOME_LOCK:
        if (
            type(token) is not _SealedM01Outcome
            or token._seal is not _CASE_SEAL
            or _SEALED_OUTCOMES.get(id(token)) is not token
            or token.result.status.value != "PASS"
            or not re.fullmatch(r"[0-9a-f]{64}", token.invocation_sha256)
            or not re.fullmatch(r"[0-9a-f]{64}", token.audit_sha256)
        ):
            raise IssuerError("m01_outcome_seal_invalid")
        _SEALED_OUTCOMES.pop(id(token), None)
    return token.result


def _discard_outcome(token: _SealedM01Outcome | None) -> None:
    if token is None:
        return
    with _OUTCOME_LOCK:
        if _SEALED_OUTCOMES.get(id(token)) is token:
            _SEALED_OUTCOMES.pop(id(token), None)


def _release_proof(proof: Any) -> None:
    if proof is None:
        return
    _close_leases(proof._lease_set)
    current_reader.release_current_read_proof(proof)


def _write_failure_audit(proof: Any, invocation: Any, reason: str) -> None:
    if proof is None:
        return
    try:
        proof._audit_directory.write_json(
            f"m01-v3-blocked-{invocation.nonce}.json",
            {
                "schema": "iteration41.okx.m01.case-audit.v3",
                "case_id": CASE_ID,
                "status": "BLOCKED",
                "reason": reason if _SAFE_REASON.fullmatch(reason) else "m01_case_blocked",
                "run_nonce": invocation.nonce,
                "source_map_sha256": invocation.source_map_sha256,
                "case_passes_added": 0,
            },
        )
    except Exception:
        pass


def run_m01_case_v3(admission: current_reader.SourceAdmission) -> Any:
    """Run the one exact M01 route and return a formal sealed CaseResult."""
    models = None
    proof = None
    writer = None
    context = None
    ready = quiet = drain = close = None
    admission_owned = True
    actor_start_attempted = False
    actor_closed = False
    reason = "m01_case_blocked"
    invocation = None
    request = None
    private_api = None
    private_module = None
    try:
        admission_sha, private_module, admission_leases = current_reader.consume_admission(
            admission
        )
        if (
            type(admission_sha) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", admission_sha)
            or len(_ORPHANED_CASE_CUSTODY) >= 8
            or worker.LIVE_TRANSPORT_ENABLEMENT != "ROOT_FIXED_ISSUER_ADMITTED"
            or os.name != "nt"
        ):
            raise IssuerError("candidate_unregistered")
        invocation = current_types.new_invocation(
            parent_pid=os.getpid(),
            started_ms=time.time_ns() // 1_000_000,
            source_map_sha256=admission_sha,
        )
        proof = current_reader.C01CurrentReadFactory().acquire(invocation)
        private_api = proof._lease_set.private_api
        writer = _PrivateJournalWriter(proof._audit_directory, private_api)
        actor_start_attempted = True
        context = job_supervisor.start_m01_monitor(
            current_read_proof=proof,
            invocation=invocation,
            journal_writer=writer,
            timeout_seconds=75.0,
            cleanup_seconds=5.0,
        )
        request = context.request
        ready = context.wait_ready(time.monotonic() + 30.0)
        if (
            ready.parent_pid != invocation.parent_pid
            or ready.worker_pid != context._control.get("pid")
            or ready.worker_source_sha256 != request.worker_source_sha256
            or ready.account_scope_sha256 != proof.account_scope_sha256
            or ready.credential_binding_sha256 != proof.credential_binding_sha256
            or ready.current_rest_read_receipt_sha256 != proof.receipt_sha256
            or ready.owner_invocation_sha256 != proof.owner_invocation_sha256
            or ready.subscription_ack_ids != (worker.SUBSCRIPTION_ID,)
            or ready.balance_snapshot_observed is not False
        ):
            raise IssuerError("ready_binding")
        quiet = context.assert_quiet(
            len(context.events_since(0)),
            worker.MAX_QUIET_MS,
            min(
                context.deadline_monotonic,
                time.monotonic() + worker.MAX_QUIET_MS / 1000.0 + 2.0,
            ),
        )
        if (
            quiet.run_nonce != context.run_nonce
            or quiet.quiet is not True
            or quiet.partial_frame_clear is not True
            or quiet.cursor_before != quiet.cursor_after
        ):
            raise IssuerError("quiet_window_unverified")
        drain = context.drain(min(context.deadline_monotonic, time.monotonic() + 6.0))
        if drain.run_nonce != context.run_nonce or drain.cursor != drain.event_count:
            raise IssuerError("drain_binding")
        models, _cases, _strategy, _runner, _spec = _load_case_contract()
        reason = "normal_close_required"
    except current_reader.CurrentReaderError as error:
        reason = error.code
    except (
        IssuerError,
        job_supervisor.ObserverError,
        worker.CandidateError,
        TimeoutError,
    ) as error:
        reason = _safe_reason(error, "m01_observation_blocked")
    except BaseException:
        reason = "m01_observation_blocked"

    if context is not None:
        try:
            close = context.close(time.monotonic() + 5.0)
            actor_closed = _close_ok(close)
            if not actor_closed:
                reason = "observer_close_uncertain"
        except BaseException:
            reason = "observer_close_uncertain"
            actor_closed = False
    elif actor_start_attempted:
        # A failed start has no typed close receipt; retain the proof and all
        # source custody rather than assuming its Job is gone.
        actor_closed = False
        reason = "observer_start_cleanup_uncertain"

    if not actor_closed and actor_start_attempted:
        if writer is not None:
            _ORPHANED_JOURNAL_WRITERS.append(writer)
        _write_failure_audit(proof, invocation, reason)
        try:
            _retain_orphan(admission, proof, context, writer, reason)
            admission_owned = False
        except IssuerError:
            pass
        models = models or importlib.import_module("_certification.models")
        return models.CaseResult(CASE_ID, models.Status.BLOCKED, reason)

    if writer is not None:
        try:
            writer.close()
        except BaseException:
            reason = "private_journal_close_uncertain"
            _ORPHANED_JOURNAL_WRITERS.append(writer)

    if proof is None:
        if reason == "m01_case_blocked":
            reason = "current_read_proof_missing"
        if admission_owned:
            try:
                current_reader.release_admission(admission)
                admission_owned = False
            except BaseException:
                reason = "source_lease_close_uncertain"
                _ORPHANED_CASE_CUSTODY.append(
                    ("admission-release", admission, proof, context, writer)
                )
        models = models or importlib.import_module("_certification.models")
        return models.CaseResult(CASE_ID, models.Status.BLOCKED, reason)

    sealed = None
    try:
        if proof is None or invocation is None:
            raise IssuerError("current_read_proof_missing")
        if writer is None or writer.handle is not None or writer.failed:
            raise IssuerError("private_journal_incomplete")
        disk = _read_private_journal(writer.path, private_api, MAX_JOURNAL_BYTES)
        expected_disk = b"".join(writer.parts)
        if disk != expected_disk or not disk.startswith(job_supervisor._PARENT_JOURNAL_MAGIC):
            raise IssuerError("private_journal_digest")
        raw_events = tuple(item.raw_bytes for item in context._events)
        if request.run_nonce != context.run_nonce:
            raise IssuerError("launch_request_binding")
        summary = contract.validate_event_journal(
            raw_events,
            expected_rest_uid=proof.expected_rest_uid,
            run_nonce=request.run_nonce,
        )
        journal_sha = hashlib.sha256(worker.encode_journal(list(raw_events))).hexdigest()
        account_capture = current_reader.verified_account_configuration_read(proof, invocation)
        case_completed_ms = time.time_ns() // 1_000_000
        models, action, receipt, observation, account_ref, session_id = _validate_case_proof(
            proof=proof,
            invocation=invocation,
            request=request,
            context=context,
            ready=ready,
            quiet=quiet,
            drain=drain,
            close=close,
            summary=summary,
            raw_events=raw_events,
            account_capture=account_capture,
            case_completed_ms=case_completed_ms,
        )
        if (
            case_completed_ms - proof.completed_ms
            > current_reader.MAX_UID_PROOF_AGE_MS + worker.MAX_RUN_SECONDS * 1000
        ):
            raise IssuerError("m01_case_window_expired")
        current_reader._require(
            current_reader._sha(expected_disk) == current_reader._sha(disk),
            "private_journal_digest",
        )
        audit = {
            "schema": "iteration41.okx.m01.case-audit.v3",
            "profile": PROFILE,
            "case_id": CASE_ID,
            "pre_release_status": "PASS_SEALED_PENDING_CLEAN_RELEASE",
            "reason": "case_predicate_satisfied",
            "run_nonce": invocation.nonce,
            "parent_pid": invocation.parent_pid,
            "source_map_sha256": invocation.source_map_sha256,
            "current_rest_read_receipt_sha256": proof.receipt_sha256,
            "account_scope_sha256": proof.account_scope_sha256,
            "credential_binding_sha256": proof.credential_binding_sha256,
            "uid_sha256": hashlib.sha256(proof.expected_rest_uid.encode("ascii")).hexdigest(),
            "case_account_ref_sha256": hashlib.sha256(account_ref.encode("ascii")).hexdigest(),
            "worker_source_sha256": request.worker_source_sha256,
            "worker_pid": close.worker_pid,
            "worker_receipt_sha256": close.worker_receipt.event_journal_sha256,
            "journal_sha256": journal_sha,
            "private_journal_sha256": hashlib.sha256(disk).hexdigest(),
            "event_count": len(raw_events),
            "connection_session_sha256": hashlib.sha256(session_id.encode("utf-8")).hexdigest(),
            "connection_event_id": observation.payload["connection_event_id"],
            "readiness_event_id": observation.payload["readiness_event_id"],
            "readiness_event_sha256": observation.payload["readiness_raw_sha256"],
            "evidence_window_id": action.evidence_window_id,
            "receipt_count": 1,
            "observation_count": 1,
            "quiet_verified": True,
            "drain_verified": True,
            "normal_job_close_verified": True,
            "orders": 0,
            "cancels": 0,
            "reconnects": 0,
            "balance_snapshot_observed": False,
            "case_passes_added": 0,
            "release_state": "pending_after_durable_seal",
        }
        audit_sha = hashlib.sha256(
            json.dumps(audit, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
                "ascii"
            )
        ).hexdigest()
        result = models.CaseResult(
            case_id=CASE_ID,
            status=models.Status.PASS,
            reason="case_predicate_satisfied",
            receipt_count=1,
            observation_count=1,
        )
        proof._audit_directory.verify()
        audit_name = f"m01-v3-case-seal-{invocation.nonce}.json"
        proof._audit_directory.write_json(audit_name, audit)
        _audit_raw, audit_readback, _audit_file_id = current_reader._open_private_json(
            proof._audit_directory.path / audit_name,
            private_module,
            maximum=64 * 1024,
        )
        audit_readback_sha = hashlib.sha256(
            json.dumps(
                audit_readback,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("ascii")
        ).hexdigest()
        if audit_readback != audit or audit_readback_sha != audit_sha:
            raise IssuerError("private_case_audit_readback")
        sealed = _mint_outcome(result, invocation, audit_sha)
    except BaseException as error:
        reason = _safe_reason(error, "m01_private_replay_blocked")
        _write_failure_audit(proof, invocation, reason)

    release_error = False
    if proof is not None:
        try:
            _release_proof(proof)
        except BaseException:
            release_error = True
            reason = "source_lease_close_uncertain"
            _ORPHANED_CASE_CUSTODY.append(("proof-release", proof, admission, context, writer))
    if admission_owned:
        try:
            current_reader.release_admission(admission)
            admission_owned = False
        except BaseException:
            release_error = True
            reason = "source_lease_close_uncertain"
            _ORPHANED_CASE_CUSTODY.append(("admission-release", admission, proof, context, writer))

    if release_error:
        _discard_outcome(sealed)
        _write_failure_audit(proof, invocation, reason)
        models = models or importlib.import_module("_certification.models")
        return models.CaseResult(CASE_ID, models.Status.BLOCKED, reason)
    if sealed is not None:
        return _consume_outcome(sealed)
    models = models or importlib.import_module("_certification.models")
    return models.CaseResult(CASE_ID, models.Status.BLOCKED, reason)
