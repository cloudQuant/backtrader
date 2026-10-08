"""Pure source contract for the unregistered OKX M01 monitor candidate.

This module validates a narrowly scoped private WebSocket readiness exchange.
It does not issue a case result, establish provider acceptance, or claim that a
balance or position snapshot was observed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Iterable


PROFILE = "OKX_GLOBAL_DEMO_M01_PRIVATE_WS_MONITOR_V2"
PROTOCOL_VERSION = 1
CASE_ID = "M01"
CASE_STATUS = "CASE_NOT_ACCEPTED"
ELIGIBILITY_STATUS = "SOURCE_CANDIDATE_ONLY"
DEMO_WSS_HOST = "wspap.okx.com"
PRIVATE_PATH = "/ws/v5/private"
SUBSCRIPTION_ID = "okxM01BalancePositionV2"
SUBSCRIPTION = {"channel": "balance_and_position"}

MAX_LAUNCH_FRAME_BYTES = 32 * 1024
MAX_CREDENTIAL_PACKET_BYTES = 16 * 1024
MAX_EVENT_BYTES = 256 * 1024
MAX_EVENT_COUNT = 4096
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_CONNECTION_ID_CHARS = 128
JOURNAL_MAGIC = b"OKX-M01-PRIVATE-WS-PARENT-JOURNAL-V2\n"

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_UID = re.compile(r"[0-9]{1,32}\Z")
_SAFE_REASON = re.compile(r"[a-z0-9_]{1,64}\Z")


class CandidateError(ValueError):
    """Fixed, value-free failure category."""

    def __init__(self, code: str):
        if type(code) is not str or not _SAFE_REASON.fullmatch(code):
            code = "candidate_error"
        super().__init__(code)
        self.code = code


def fail(code: str) -> None:
    raise CandidateError(code)


def _reject_constant(_value: str) -> Any:
    fail("nonfinite_json_number")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail("duplicate_json_key")
        result[key] = value
    return result


def strict_json(raw: bytes, *, limit: int) -> Any:
    if type(raw) is not bytes or not 0 <= len(raw) <= limit:
        fail("json_size")
    try:
        return json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
        )
    except CandidateError:
        raise
    except Exception:
        fail("json_invalid")


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except Exception:
        fail("canonical_json_invalid")


def require_sha256(value: Any, code: str = "sha256_shape") -> str:
    if type(value) is not str or not _HEX64.fullmatch(value):
        fail(code)
    return value


def uid_sha256(uid: str) -> str:
    """Digest a provider UID without ever returning its raw value."""
    if type(uid) is not str or not _UID.fullmatch(uid):
        fail("private_uid_shape")
    return hashlib.sha256(uid.encode("ascii")).hexdigest()


@dataclass(frozen=True, repr=False)
class PrivateCredentials:
    api_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    passphrase: str = field(repr=False)


@dataclass(frozen=True, repr=False)
class LaunchRequest:
    run_nonce: str
    parent_pid: int
    worker_source_sha256: str
    account_scope_sha256: str = field(repr=False)
    credential_binding_sha256: str = field(repr=False)
    current_rest_read_receipt_sha256: str = field(repr=False)
    owner_invocation_sha256: str = field(repr=False)
    expected_rest_uid: str = field(repr=False)
    timeout_ms: int = 30_000
    credential_packet: bytes = field(default=b"", repr=False)


def _credential_text(value: Any) -> str:
    if (
        type(value) is not str
        or not 8 <= len(value) <= 256
        or not value.isascii()
        or any(ord(char) < 33 or ord(char) > 126 for char in value)
    ):
        fail("credential_shape")
    return value


def parse_credentials(packet: bytes) -> tuple[PrivateCredentials, str]:
    if type(packet) is not bytes or len(packet) > MAX_CREDENTIAL_PACKET_BYTES:
        fail("credential_packet_size")
    value = strict_json(packet, limit=MAX_CREDENTIAL_PACKET_BYTES)
    if type(value) is not dict or set(value) != {
        "api_key",
        "secret_key",
        "passphrase",
        "expected_rest_uid",
    }:
        fail("credential_packet_fields")
    if canonical_json(value) != packet:
        fail("credential_packet_not_canonical")
    credentials = PrivateCredentials(
        api_key=_credential_text(value["api_key"]),
        secret_key=_credential_text(value["secret_key"]),
        passphrase=_credential_text(value["passphrase"]),
    )
    expected_uid = value["expected_rest_uid"]
    if type(expected_uid) is not str or not _UID.fullmatch(expected_uid):
        fail("rest_uid_shape")
    return credentials, expected_uid


def account_scope_sha256(credentials: PrivateCredentials) -> str:
    if type(credentials) is not PrivateCredentials:
        fail("credential_type")
    return hashlib.sha256(
        b"okx-global-demo-api-key-v1\0" + credentials.api_key.encode("ascii")
    ).hexdigest()


def credential_binding_sha256(credentials: PrivateCredentials) -> str:
    if type(credentials) is not PrivateCredentials:
        fail("credential_type")
    return hashlib.sha256(
        canonical_json(
            {
                "api_key": credentials.api_key,
                "passphrase": credentials.passphrase,
                "scheme": "okx.global.demo.credentials.v1",
                "secret_key": credentials.secret_key,
            }
        )
    ).hexdigest()


def _validate_launch(request: LaunchRequest) -> None:
    if type(request) is not LaunchRequest:
        fail("launch_type")
    if type(request.run_nonce) is not str or not _NONCE.fullmatch(request.run_nonce):
        fail("run_nonce")
    if type(request.parent_pid) is not int or request.parent_pid <= 0:
        fail("parent_pid")
    if type(request.timeout_ms) is not int or not 1_000 <= request.timeout_ms <= 90_000:
        fail("timeout")
    for name in (
        "worker_source_sha256",
        "account_scope_sha256",
        "credential_binding_sha256",
        "current_rest_read_receipt_sha256",
        "owner_invocation_sha256",
    ):
        require_sha256(getattr(request, name), name)
    if type(request.expected_rest_uid) is not str or not _UID.fullmatch(request.expected_rest_uid):
        fail("rest_uid_shape")
    if type(request.credential_packet) is not bytes or len(request.credential_packet) > (
        MAX_CREDENTIAL_PACKET_BYTES
    ):
        fail("credential_packet_size")
    credentials, packet_uid = parse_credentials(request.credential_packet)
    if (
        packet_uid != request.expected_rest_uid
        or account_scope_sha256(credentials) != request.account_scope_sha256
        or credential_binding_sha256(credentials) != request.credential_binding_sha256
    ):
        fail("launch_credential_binding")


def encode_launch_frame(request: LaunchRequest) -> bytes:
    _validate_launch(request)
    credentials, packet_uid = parse_credentials(request.credential_packet)
    if (
        packet_uid != request.expected_rest_uid
        or account_scope_sha256(credentials) != request.account_scope_sha256
        or credential_binding_sha256(credentials) != request.credential_binding_sha256
    ):
        fail("launch_credential_binding")
    value = {
        "account_scope_sha256": request.account_scope_sha256,
        "credential_binding_sha256": request.credential_binding_sha256,
        "credential_packet": request.credential_packet.decode("utf-8", errors="strict"),
        "current_rest_read_receipt_sha256": request.current_rest_read_receipt_sha256,
        "owner_invocation_sha256": request.owner_invocation_sha256,
        "parent_pid": request.parent_pid,
        "profile": PROFILE,
        "protocol_version": PROTOCOL_VERSION,
        "run_nonce": request.run_nonce,
        "timeout_ms": request.timeout_ms,
        "worker_source_sha256": request.worker_source_sha256,
    }
    raw = canonical_json(value) + b"\n"
    if len(raw) > MAX_LAUNCH_FRAME_BYTES:
        fail("launch_size")
    return raw


def parse_launch_frame(raw: bytes) -> LaunchRequest:
    if (
        type(raw) is not bytes
        or not raw.endswith(b"\n")
        or raw.count(b"\n") != 1
        or len(raw) > MAX_LAUNCH_FRAME_BYTES
    ):
        fail("launch_termination")
    value = strict_json(raw[:-1], limit=MAX_LAUNCH_FRAME_BYTES - 1)
    expected = {
        "account_scope_sha256",
        "credential_binding_sha256",
        "credential_packet",
        "current_rest_read_receipt_sha256",
        "owner_invocation_sha256",
        "parent_pid",
        "profile",
        "protocol_version",
        "run_nonce",
        "timeout_ms",
        "worker_source_sha256",
    }
    if type(value) is not dict or set(value) != expected:
        fail("launch_fields")
    if value["profile"] != PROFILE or value["protocol_version"] != PROTOCOL_VERSION:
        fail("launch_version")
    packet = value["credential_packet"]
    if type(packet) is not str:
        fail("credential_packet_shape")
    try:
        packet_bytes = packet.encode("utf-8", errors="strict")
    except Exception:
        fail("credential_packet_encoding")
    credentials, expected_uid = parse_credentials(packet_bytes)
    request = LaunchRequest(
        run_nonce=value["run_nonce"],
        parent_pid=value["parent_pid"],
        worker_source_sha256=value["worker_source_sha256"],
        account_scope_sha256=value["account_scope_sha256"],
        credential_binding_sha256=value["credential_binding_sha256"],
        current_rest_read_receipt_sha256=value["current_rest_read_receipt_sha256"],
        owner_invocation_sha256=value["owner_invocation_sha256"],
        expected_rest_uid=expected_uid,
        timeout_ms=value["timeout_ms"],
        credential_packet=packet_bytes,
    )
    _validate_launch(request)
    if (
        account_scope_sha256(credentials) != request.account_scope_sha256
        or credential_binding_sha256(credentials) != request.credential_binding_sha256
    ):
        fail("credential_binding")
    return LaunchRequest(
        run_nonce=request.run_nonce,
        parent_pid=request.parent_pid,
        worker_source_sha256=request.worker_source_sha256,
        account_scope_sha256=request.account_scope_sha256,
        credential_binding_sha256=request.credential_binding_sha256,
        current_rest_read_receipt_sha256=request.current_rest_read_receipt_sha256,
        owner_invocation_sha256=request.owner_invocation_sha256,
        expected_rest_uid=expected_uid,
        timeout_ms=request.timeout_ms,
        credential_packet=packet_bytes,
    )


def validate_event_journal(
    events: Iterable[bytes], *, expected_rest_uid: str, run_nonce: str
) -> "EventJournalSummary":
    """Recompute M01 login/subscription/data protocol from exact journal bytes.

    Returns only a connection-ID digest, a channel/event digest, and the count
    of private data messages. No account UID or row data is returned.
    """
    if type(expected_rest_uid) is not str or not _UID.fullmatch(expected_rest_uid):
        fail("rest_uid_shape")
    expected_uid_digest = uid_sha256(expected_rest_uid)
    raw_events = tuple(events)
    if len(raw_events) > MAX_EVENT_COUNT:
        fail("event_count")
    if type(run_nonce) is not str or not _NONCE.fullmatch(run_nonce):
        fail("run_nonce")
    login_conn_id: str | None = None
    login_seen = False
    subscribe_sent = False
    subscribe_ack = False
    data_count = 0
    kinds: list[str] = []
    connection_sequence: int | None = None
    readiness_sequence: int | None = None
    for sequence, raw in enumerate(raw_events, start=1):
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_EVENT_BYTES:
            fail("event_size")
        if raw == b"ping":
            kinds.append("application_heartbeat_ping")
            continue
        value = strict_json(raw, limit=MAX_EVENT_BYTES)
        if type(value) is not dict:
            fail("private_event_object")
        event = value.get("event")
        if event == "login":
            if (
                login_seen
                or subscribe_sent
                or set(value) != {"event", "code", "msg", "connId"}
                or value.get("code") != "0"
                or value.get("msg") != ""
            ):
                fail("login_ack_invalid")
            conn_id = value.get("connId")
            if type(conn_id) is not str or not 1 <= len(conn_id) <= MAX_CONNECTION_ID_CHARS:
                fail("connection_id")
            if any(ord(c) < 33 or ord(c) > 126 for c in conn_id):
                fail("connection_id")
            login_conn_id = conn_id
            login_seen = True
            connection_sequence = sequence
            kinds.append("login_ack")
            # The fixed worker sends the only subscription immediately after
            # consuming a successful login ack.
            subscribe_sent = True
            continue
        if not login_seen or login_conn_id is None:
            fail("event_before_login")
        if event == "error" or event == "channel-conn-count-error":
            fail("provider_error_event")
        if event == "channel-conn-count":
            if set(value) != {"event", "channel", "connCount", "connId"}:
                fail("connection_count_fields")
            if (
                value.get("channel") != "balance_and_position"
                or type(value.get("connCount")) is not str
                or not re.fullmatch(r"[1-9][0-9]{0,9}", value["connCount"])
                or value.get("connId") != login_conn_id
            ):
                fail("connection_count_invalid")
            kinds.append("connection_count_info")
            continue
        if event == "subscribe":
            if subscribe_ack or not subscribe_sent:
                fail("subscription_ack_order")
            allowed = {"id", "event", "arg", "connId", "msg", "code"}
            if (
                set(value) - allowed
                or not {"id", "event", "arg", "connId"} <= set(value)
                or value.get("id") != SUBSCRIPTION_ID
                or value.get("arg") != SUBSCRIPTION
                or value.get("connId") != login_conn_id
                or value.get("msg", "") != ""
                or value.get("code", "0") != "0"
            ):
                fail("subscription_ack_invalid")
            subscribe_ack = True
            readiness_sequence = sequence
            kinds.append("subscription_ack")
            continue
        if event is not None:
            fail("unknown_event")
        if not subscribe_sent:
            fail("data_before_subscription")
        if set(value) - {"arg", "data", "ts", "connId"} or not {"arg", "data"} <= set(value):
            fail("private_data_fields")
        arg = value.get("arg")
        data = value.get("data")
        if (
            type(arg) is not dict
            or set(arg) != {"channel", "uid"}
            or arg.get("channel") != "balance_and_position"
            or type(data) is not list
            or any(type(row) is not dict for row in data)
        ):
            fail("private_data_shape")
        if uid_sha256(arg.get("uid")) != expected_uid_digest:
            fail("rest_uid_mismatch")
        if "connId" in value:
            conn_id = value["connId"]
            if type(conn_id) is not str or conn_id != login_conn_id:
                fail("connection_id_changed")
        data_count += 1
        kinds.append("balance_position_data")
    if not login_seen or not subscribe_ack or login_conn_id is None:
        fail("readiness_incomplete")
    if connection_sequence is None or readiness_sequence is None:
        fail("readiness_event_missing")
    return EventJournalSummary(
        connection_id_sha256=hashlib.sha256(login_conn_id.encode("utf-8")).hexdigest(),
        event_kinds_sha256=hashlib.sha256(canonical_json(kinds)).hexdigest(),
        private_data_event_count=data_count,
        connection_event_id=_event_id(
            run_nonce, connection_sequence, raw_events[connection_sequence - 1]
        ),
        readiness_event_id=_event_id(
            run_nonce, readiness_sequence, raw_events[readiness_sequence - 1]
        ),
    )


@dataclass(frozen=True)
class EventJournalSummary:
    connection_id_sha256: str
    event_kinds_sha256: str
    private_data_event_count: int
    connection_event_id: str
    readiness_event_id: str


def _event_id(run_nonce: str, sequence: int, raw: bytes) -> str:
    if type(run_nonce) is not str or not _NONCE.fullmatch(run_nonce):
        fail("run_nonce")
    digest = hashlib.sha256(
        b"okx.m01.event.v1\0"
        + run_nonce.encode("ascii")
        + sequence.to_bytes(8, "big")
        + hashlib.sha256(raw).digest()
    ).hexdigest()
    return "m01ev-" + digest


def encode_journal(events: Iterable[bytes]) -> bytes:
    raw_events = tuple(events)
    if len(raw_events) > MAX_EVENT_COUNT:
        fail("event_count")
    output = bytearray(JOURNAL_MAGIC)
    chain = hashlib.sha256(JOURNAL_MAGIC).digest()
    for raw in raw_events:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_EVENT_BYTES:
            fail("event_size")
        record = len(raw).to_bytes(4, "big") + raw
        chain = hashlib.sha256(chain + record).digest()
        output.extend(record)
        output.extend(chain)
        if len(output) > MAX_OUTPUT_BYTES:
            fail("journal_size")
    return bytes(output)


@dataclass(frozen=True, repr=False)
class PrivateEventRef:
    sequence: int
    received_utc_ms: int
    received_monotonic_ns: int
    raw_sha256: str
    raw_bytes: bytes = field(repr=False)


@dataclass(frozen=True, repr=False)
class WorkerReceipt:
    run_nonce: str
    parent_pid: int
    worker_pid: int
    worker_source_sha256: str
    account_scope_sha256: str = field(repr=False)
    credential_binding_sha256: str = field(repr=False)
    current_rest_read_receipt_sha256: str = field(repr=False)
    owner_invocation_sha256: str = field(repr=False)
    connection_id_sha256: str = field(default="", repr=False)
    connection_event_id: str = ""
    readiness_event_id: str = ""
    event_count: int = 0
    event_journal_sha256: str = ""
    login_acknowledged: bool = False
    subscription_ack_ids: tuple[str, ...] = ()
    private_data_event_count: int = 0
    balance_snapshot_observed: bool = False
    ready_sent: bool = False
    socket_closed: bool = False
    normal_websocket_close: bool = False
    control_thread_joined: bool = False
    reason: str = ""
    status: str = CASE_STATUS


@dataclass(frozen=True, repr=False)
class ProcessLifecycleReceipt:
    run_nonce: str
    parent_pid: int
    worker_pid: int | None
    worker_source_sha256: str | None
    containment: str
    assigned_before_resume: bool
    process_resumed: bool
    stdin_closed: bool
    stdout_eof: bool
    stderr_eof: bool
    process_exit_observed: bool
    process_exit_code: int | None
    job_active_count: int | None
    drain_threads_joined: bool
    handles_closed: bool
    handle_close_failed: bool
    runtime_files_held_through_exit: bool
    runtime_files_closed: bool
    timed_out: bool
    forced_termination: bool
    socket_closed: bool
    normal_websocket_close: bool
    worker_receipt_valid: bool


@dataclass(frozen=True)
class MonitorAssessment:
    status: str
    eligible_for_future_fixed_issuer: bool
    balance_position_payload_count: int
    balance_snapshot_observed: bool
    reasons: tuple[str, ...]


def assess_m01(
    *,
    launch: LaunchRequest,
    worker: WorkerReceipt,
    process: ProcessLifecycleReceipt,
    raw_events: Iterable[bytes],
    journal_sha256: str,
) -> MonitorAssessment:
    """Validate source-candidate evidence; never issue a certification PASS."""
    reasons: list[str] = []
    raw_event_tuple = tuple(raw_events)
    data_count = 0
    try:
        _validate_launch(launch)
        summary = validate_event_journal(
            raw_event_tuple,
            expected_rest_uid=launch.expected_rest_uid,
            run_nonce=launch.run_nonce,
        )
        data_count = summary.private_data_event_count
        if (
            worker.connection_id_sha256 != summary.connection_id_sha256
            or worker.connection_event_id != summary.connection_event_id
            or worker.readiness_event_id != summary.readiness_event_id
        ):
            reasons.append("event_receipt_mismatch")
    except CandidateError as exc:
        reasons.append(exc.code)
    if (
        type(worker.status) is not str
        or worker.status != CASE_STATUS
        or process.run_nonce != launch.run_nonce
    ):
        reasons.append("receipt_status_or_nonce")
    if (
        type(worker.parent_pid) is not int
        or type(process.parent_pid) is not int
        or type(worker.worker_pid) is not int
        or type(process.worker_pid) is not int
        or worker.run_nonce != launch.run_nonce
        or worker.worker_pid <= 0
        or process.worker_pid <= 0
        or worker.parent_pid != launch.parent_pid
        or process.parent_pid != launch.parent_pid
        or worker.worker_pid != process.worker_pid
        or worker.worker_source_sha256 != launch.worker_source_sha256
        or process.worker_source_sha256 != launch.worker_source_sha256
        or worker.account_scope_sha256 != launch.account_scope_sha256
        or worker.credential_binding_sha256 != launch.credential_binding_sha256
        or worker.current_rest_read_receipt_sha256 != launch.current_rest_read_receipt_sha256
        or worker.owner_invocation_sha256 != launch.owner_invocation_sha256
    ):
        reasons.append("receipt_binding")
    try:
        expected_journal_sha = hashlib.sha256(encode_journal(raw_event_tuple)).hexdigest()
        if (
            type(worker.event_count) is not int
            or worker.event_count != len(raw_event_tuple)
            or worker.event_journal_sha256 != require_sha256(journal_sha256)
            or expected_journal_sha != worker.event_journal_sha256
        ):
            reasons.append("journal_binding")
    except CandidateError as exc:
        reasons.append(exc.code)
    if (
        type(worker.login_acknowledged) is not bool
        or type(worker.ready_sent) is not bool
        or not worker.login_acknowledged
        or not worker.ready_sent
        or type(worker.reason) is not str
        or worker.reason != "normal_close_requested"
        or worker.balance_snapshot_observed is not False
        or type(worker.private_data_event_count) is not int
        or type(worker.socket_closed) is not bool
        or type(worker.normal_websocket_close) is not bool
        or type(worker.control_thread_joined) is not bool
        or not worker.socket_closed
        or not worker.normal_websocket_close
        or not worker.control_thread_joined
    ):
        reasons.append("readiness_missing")
    if worker.subscription_ack_ids != (SUBSCRIPTION_ID,):
        reasons.append("subscription_ack_missing")
    bool_fields = (
        process.assigned_before_resume,
        process.process_resumed,
        process.stdin_closed,
        process.stdout_eof,
        process.stderr_eof,
        process.process_exit_observed,
        process.drain_threads_joined,
        process.handles_closed,
        process.handle_close_failed,
        process.runtime_files_held_through_exit,
        process.runtime_files_closed,
        process.timed_out,
        process.forced_termination,
        process.socket_closed,
        process.normal_websocket_close,
        process.worker_receipt_valid,
    )
    lifecycle_valid = (
        all(type(value) is bool for value in bool_fields)
        and process.containment == "windows_job"
        and process.assigned_before_resume
        and process.process_resumed
        and process.stdin_closed
        and process.stdout_eof
        and process.stderr_eof
        and process.process_exit_observed
        and type(process.process_exit_code) is int
        and process.process_exit_code == 0
        and type(process.job_active_count) is int
        and process.job_active_count == 0
        and process.drain_threads_joined
        and process.handles_closed
        and not process.handle_close_failed
        and process.runtime_files_held_through_exit
        and process.runtime_files_closed
        and not process.timed_out
        and not process.forced_termination
        and process.socket_closed
        and process.normal_websocket_close
        and process.worker_receipt_valid
    )
    if not lifecycle_valid:
        reasons.append("process_lifecycle_incomplete")
    if worker.private_data_event_count != data_count:
        reasons.append("private_data_count_mismatch")
    return MonitorAssessment(
        status=CASE_STATUS,
        eligible_for_future_fixed_issuer=not reasons,
        balance_position_payload_count=data_count,
        balance_snapshot_observed=False,
        reasons=tuple(dict.fromkeys(reasons)),
    )
