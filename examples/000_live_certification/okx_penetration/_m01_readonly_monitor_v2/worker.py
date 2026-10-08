"""Isolated OKX Global Demo M01 private monitor v2 candidate.

The fixed transport is selected only through the source-owned issuer and its
protected deployment registration. This worker has no SDK dependency and no
order, cancel, REST, or reconnect operation.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import os
import queue
import re
import socket
import ssl
import struct
import sys
import threading
import time
from typing import Any, Callable, Mapping


PROFILE = "OKX_GLOBAL_DEMO_M01_PRIVATE_WS_MONITOR_V2"
PROTOCOL_VERSION = 1
CASE_STATUS = "CASE_NOT_ACCEPTED"
LIVE_TRANSPORT_ENABLEMENT = "ROOT_FIXED_ISSUER_ADMITTED"

DEMO_WSS_HOST = "wspap.okx.com"
PRIVATE_PATH = "/ws/v5/private"
BALANCE_POSITION_SUBSCRIPTION = {"channel": "balance_and_position"}
SUBSCRIPTION_ID = "okxM01BalancePositionV2"

MAX_LAUNCH_FRAME_BYTES = 128 * 1024
MAX_CONTROL_FRAME_BYTES = 16 * 1024
MAX_EVENT_BYTES = 256 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_EVENT_COUNT = 4096
MAX_CREDENTIAL_PACKET_BYTES = 16 * 1024
MAX_HANDSHAKE_BYTES = 16 * 1024
MAX_WEBSOCKET_MESSAGE_BYTES = MAX_EVENT_BYTES
MAX_CLOSE_TRAILING_BYTES = MAX_WEBSOCKET_MESSAGE_BYTES
MAX_RUN_SECONDS = 90.0
MAX_EVENT_TIMEOUT_MS = 90_000
MAX_QUIET_MS = 5_000
MAX_RECEIVE_POLL_SECONDS = 0.05
MAX_WEBSOCKET_FRAME_ASSEMBLY_SECONDS = 5.0
MAX_WEBSOCKET_FRAGMENT_ASSEMBLY_SECONDS = 10.0
MAX_WEBSOCKET_FRAGMENT_COUNT = 1024
MAX_CLOSE_SECONDS = 4.0

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_REQUEST_ID = re.compile(r"[A-Za-z0-9]{1,32}\Z")
_UID = re.compile(r"[0-9]{1,32}\Z")
_CONNECTION_COUNT = re.compile(r"[1-9][0-9]{0,9}\Z")
_SAFE_REASON = re.compile(r"[a-z0-9_]{1,64}\Z")
_FRAME_MAGIC = b"OKX-M01-PRIVATE-WS-PARENT-JOURNAL-V2\n"
_WS_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

_FRAME_EVENT = 1
_FRAME_READY = 2
_FRAME_QUIET_ACK = 3
_FRAME_DRAIN_ACK = 4
_FRAME_RECEIPT = 5
_FRAME_ERROR = 6
_FRAME_COMMAND = 10
_EVENT_HEADER = struct.Struct(">IQQI")


class CandidateError(ValueError):
    """A fixed non-sensitive failure category."""

    def __init__(self, code: str):
        if type(code) is not str or not _SAFE_REASON.fullmatch(code):
            code = "candidate_error"
        super().__init__(code)
        self.code = code


def _fail(code: str) -> None:
    raise CandidateError(code)


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> Any:
    _fail("nonfinite_json_number")


def strict_json(raw: bytes, *, limit: int) -> Any:
    if type(raw) is not bytes or len(raw) > limit:
        _fail("json_size")
    try:
        return json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
        )
    except CandidateError:
        raise
    except Exception:
        _fail("json_invalid")


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except Exception:
        _fail("canonical_json_invalid")


def _digest(value: Any, code: str) -> str:
    if type(value) is not str or not _HEX64.fullmatch(value):
        _fail(code)
    return value


def _keys(value: Any, expected: set[str], code: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != expected:
        _fail(code)
    return value


@dataclass(frozen=True, repr=False)
class LaunchRequest:
    run_nonce: str
    parent_pid: int
    worker_source_sha256: str
    account_scope_sha256: str = field(repr=False)
    credential_binding_sha256: str = field(repr=False)
    current_rest_read_receipt_sha256: str = field(repr=False)
    owner_invocation_sha256: str = field(repr=False)
    event_timeout_ms: int = MAX_EVENT_TIMEOUT_MS
    credential_packet: bytes = field(default=b"", repr=False)


@dataclass(frozen=True, repr=False)
class DemoCredentials:
    api_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    passphrase: str = field(repr=False)
    expected_rest_uid: str = field(repr=False)


def _validate_credential_text(value: Any) -> str:
    if (
        type(value) is not str
        or not 8 <= len(value) <= 256
        or not value.isascii()
        or any(ord(char) < 33 or ord(char) > 126 for char in value)
    ):
        _fail("credential_shape")
    return value


def encode_launch_frame(request: LaunchRequest) -> bytes:
    if type(request) is not LaunchRequest:
        _fail("launch_type")
    if type(request.run_nonce) is not str or not _NONCE.fullmatch(request.run_nonce):
        _fail("run_nonce")
    if type(request.parent_pid) is not int or request.parent_pid <= 0:
        _fail("parent_pid")
    if (
        type(request.event_timeout_ms) is not int
        or not 1 <= request.event_timeout_ms <= MAX_EVENT_TIMEOUT_MS
    ):
        _fail("event_timeout")
    packet = request.credential_packet
    if type(packet) is not bytes or len(packet) > MAX_CREDENTIAL_PACKET_BYTES:
        _fail("credential_packet_size")
    _digest(request.current_rest_read_receipt_sha256, "rest_receipt")
    _digest(request.owner_invocation_sha256, "owner_invocation")
    credentials = parse_credentials(packet)
    if (
        account_scope_sha256(credentials) != request.account_scope_sha256
        or credential_binding_sha256(credentials) != request.credential_binding_sha256
    ):
        _fail("credential_binding")
    value = {
        "account_scope_sha256": _digest(request.account_scope_sha256, "account_scope"),
        "credential_binding_sha256": _digest(
            request.credential_binding_sha256, "credential_binding"
        ),
        "credential_packet_b64": base64.b64encode(packet).decode("ascii"),
        "current_rest_read_receipt_sha256": request.current_rest_read_receipt_sha256,
        "event_timeout_ms": request.event_timeout_ms,
        "owner_invocation_sha256": request.owner_invocation_sha256,
        "parent_pid": request.parent_pid,
        "profile": PROFILE,
        "protocol_version": PROTOCOL_VERSION,
        "run_nonce": request.run_nonce,
        "worker_source_sha256": _digest(request.worker_source_sha256, "worker_source"),
    }
    raw = _canonical_json(value) + b"\n"
    if len(raw) > MAX_LAUNCH_FRAME_BYTES:
        _fail("launch_size")
    return raw


def parse_launch_frame(raw: bytes) -> LaunchRequest:
    if (
        type(raw) is not bytes
        or not raw.endswith(b"\n")
        or raw.count(b"\n") != 1
        or len(raw) > MAX_LAUNCH_FRAME_BYTES
    ):
        _fail("launch_termination")
    value = _keys(
        strict_json(raw[:-1], limit=MAX_LAUNCH_FRAME_BYTES - 1),
        {
            "account_scope_sha256",
            "credential_binding_sha256",
            "credential_packet_b64",
            "current_rest_read_receipt_sha256",
            "event_timeout_ms",
            "owner_invocation_sha256",
            "parent_pid",
            "profile",
            "protocol_version",
            "run_nonce",
            "worker_source_sha256",
        },
        "launch_fields",
    )
    if value["profile"] != PROFILE or value["protocol_version"] != PROTOCOL_VERSION:
        _fail("launch_version")
    if type(value["run_nonce"]) is not str or not _NONCE.fullmatch(value["run_nonce"]):
        _fail("run_nonce")
    if type(value["parent_pid"]) is not int or value["parent_pid"] <= 0:
        _fail("parent_pid")
    if (
        type(value["event_timeout_ms"]) is not int
        or not 1 <= value["event_timeout_ms"] <= MAX_EVENT_TIMEOUT_MS
    ):
        _fail("event_timeout")
    for field_name in (
        "worker_source_sha256",
        "account_scope_sha256",
        "credential_binding_sha256",
        "current_rest_read_receipt_sha256",
        "owner_invocation_sha256",
    ):
        _digest(value[field_name], field_name)
    encoded = value["credential_packet_b64"]
    if type(encoded) is not str or len(encoded) > ((MAX_CREDENTIAL_PACKET_BYTES + 2) // 3) * 4:
        _fail("credential_packet_size")
    try:
        packet = base64.b64decode(encoded.encode("ascii"), validate=True)
    except Exception:
        _fail("credential_packet_encoding")
    if len(packet) > MAX_CREDENTIAL_PACKET_BYTES:
        _fail("credential_packet_size")
    request = LaunchRequest(
        run_nonce=value["run_nonce"],
        parent_pid=value["parent_pid"],
        worker_source_sha256=value["worker_source_sha256"],
        account_scope_sha256=value["account_scope_sha256"],
        credential_binding_sha256=value["credential_binding_sha256"],
        current_rest_read_receipt_sha256=value["current_rest_read_receipt_sha256"],
        owner_invocation_sha256=value["owner_invocation_sha256"],
        event_timeout_ms=value["event_timeout_ms"],
        credential_packet=packet,
    )
    credentials = parse_credentials(packet)
    if (
        account_scope_sha256(credentials) != request.account_scope_sha256
        or credential_binding_sha256(credentials) != request.credential_binding_sha256
    ):
        _fail("credential_binding")
    return request


def parse_credentials(packet: bytes) -> DemoCredentials:
    value = _keys(
        strict_json(packet, limit=MAX_CREDENTIAL_PACKET_BYTES),
        {"api_key", "secret_key", "passphrase", "expected_rest_uid"},
        "credential_packet_fields",
    )
    if _canonical_json(value) != packet:
        _fail("credential_packet_not_canonical")
    expected_rest_uid = value["expected_rest_uid"]
    if type(expected_rest_uid) is not str or not _UID.fullmatch(expected_rest_uid):
        _fail("rest_uid_shape")
    return DemoCredentials(
        api_key=_validate_credential_text(value["api_key"]),
        secret_key=_validate_credential_text(value["secret_key"]),
        passphrase=_validate_credential_text(value["passphrase"]),
        expected_rest_uid=expected_rest_uid,
    )


def account_scope_sha256(credentials: DemoCredentials) -> str:
    """Return the owner-compatible digest without its public ``sha256:`` wrapper."""
    if type(credentials) is not DemoCredentials:
        _fail("credential_type")
    return hashlib.sha256(
        b"okx-global-demo-api-key-v1\0" + credentials.api_key.encode("ascii")
    ).hexdigest()


def credential_binding_sha256(credentials: DemoCredentials) -> str:
    """Return a private digest over the canonical credential tuple and scheme."""
    if type(credentials) is not DemoCredentials:
        _fail("credential_type")
    document = {
        "api_key": credentials.api_key,
        "passphrase": credentials.passphrase,
        "scheme": "okx.global.demo.credentials.v1",
        "secret_key": credentials.secret_key,
    }
    return hashlib.sha256(_canonical_json(document)).hexdigest()


def encode_frame(kind: int, payload: bytes) -> bytes:
    if type(kind) is not int or kind not in {
        _FRAME_EVENT,
        _FRAME_READY,
        _FRAME_QUIET_ACK,
        _FRAME_DRAIN_ACK,
        _FRAME_RECEIPT,
        _FRAME_ERROR,
        _FRAME_COMMAND,
    }:
        _fail("frame_kind")
    maximum = (
        MAX_EVENT_BYTES + _EVENT_HEADER.size if kind == _FRAME_EVENT else MAX_CONTROL_FRAME_BYTES
    )
    if type(payload) is not bytes or len(payload) > maximum:
        _fail("frame_size")
    return bytes((kind,)) + struct.pack(">I", len(payload)) + payload


def encode_control(kind: int, document: Mapping[str, Any]) -> bytes:
    return encode_frame(kind, _canonical_json(dict(document)) + b"\n")


def decode_event_payload(payload: bytes) -> tuple[int, int, int, bytes]:
    if type(payload) is not bytes or len(payload) < _EVENT_HEADER.size:
        _fail("event_frame_header")
    sequence, wall_ms, monotonic_ns, length = _EVENT_HEADER.unpack_from(payload)
    raw = payload[_EVENT_HEADER.size :]
    if (
        not 1 <= sequence <= MAX_EVENT_COUNT
        or length != len(raw)
        or not 0 < length <= MAX_EVENT_BYTES
    ):
        _fail("event_frame_length")
    try:
        raw.decode("utf-8", errors="strict")
    except Exception:
        _fail("event_utf8")
    return sequence, wall_ms, monotonic_ns, raw


def _event_payload(sequence: int, raw: bytes) -> bytes:
    return (
        _EVENT_HEADER.pack(sequence, int(time.time() * 1000), time.monotonic_ns(), len(raw)) + raw
    )


def _frame_json(emit: Callable[[int, bytes], None], kind: int, value: Mapping[str, Any]) -> None:
    emit(kind, _canonical_json(dict(value)) + b"\n")


def _read_exact(stream: Any, count: int) -> bytes:
    output = bytearray()
    while len(output) < count:
        chunk = stream.read(count - len(output))
        if not chunk:
            _fail("stdin_eof")
        output.extend(chunk)
    return bytes(output)


def _read_launch_line(stream: Any) -> bytes:
    output = bytearray()
    while len(output) <= MAX_LAUNCH_FRAME_BYTES:
        byte = stream.read(1)
        if not byte:
            _fail("launch_eof")
        output.extend(byte)
        if byte == b"\n":
            return bytes(output)
    _fail("launch_size")


def _read_control_frame(stream: Any) -> tuple[int, bytes]:
    header = _read_exact(stream, 5)
    kind = header[0]
    length = struct.unpack(">I", header[1:])[0]
    if kind != _FRAME_COMMAND or length > MAX_CONTROL_FRAME_BYTES:
        _fail("control_frame_header")
    return kind, _read_exact(stream, length)


def _mask_frame(opcode: int, payload: bytes) -> bytes:
    if type(payload) is not bytes or len(payload) > MAX_WEBSOCKET_MESSAGE_BYTES:
        _fail("client_frame_size")
    if opcode not in (1, 8, 10):
        _fail("client_frame_opcode")
    mask = os.urandom(4)
    first = 0x80 | opcode
    length = len(payload)
    if length <= 125:
        head = bytes((first, 0x80 | length))
    elif length <= 0xFFFF:
        head = bytes((first, 0x80 | 126)) + struct.pack(">H", length)
    else:
        head = bytes((first, 0x80 | 127)) + struct.pack(">Q", length)
    masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    return head + mask + masked


class _WireReader:
    """Strict RFC6455 reader with bounded partial-frame and fragment retention."""

    def __init__(self, stream: Any):
        self.stream = stream
        self.frame_bytes = bytearray()
        self.frame_deadline: float | None = None
        self.fragment_opcode: int | None = None
        self.fragments = bytearray()
        self.fragment_deadline: float | None = None
        self.fragment_count = 0
        self.closed_by_server = False

    def _frame_layout(self) -> tuple[bool, int, int, int] | None:
        raw = self.frame_bytes
        if not raw:
            return None
        first = raw[0]
        fin = bool(first & 0x80)
        rsv = first & 0x70
        opcode = first & 0x0F
        if rsv or opcode not in (0, 1, 2, 8, 9, 10):
            _fail("websocket_frame_flags")
        if len(raw) < 2:
            return None
        second = raw[1]
        if second & 0x80:
            _fail("websocket_frame_flags")
        marker = second & 0x7F
        if marker < 126:
            header_size = 2
            length = marker
        elif marker == 126:
            header_size = 4
            if len(raw) < header_size:
                return None
            length = struct.unpack(">H", raw[2:4])[0]
            if length < 126:
                _fail("websocket_noncanonical_length")
        else:
            header_size = 10
            if len(raw) < header_size:
                return None
            length = struct.unpack(">Q", raw[2:10])[0]
            if length <= 0xFFFF or length & (1 << 63):
                _fail("websocket_noncanonical_length")
        if length > MAX_WEBSOCKET_MESSAGE_BYTES:
            _fail("websocket_frame_size")
        if opcode >= 8 and (not fin or length > 125):
            _fail("websocket_control_frame")
        return fin, opcode, header_size, length

    def _next_frame_read_size(self, layout: tuple[bool, int, int, int] | None) -> int:
        size = len(self.frame_bytes)
        if not size:
            return 1
        if size == 1:
            return 1
        marker = self.frame_bytes[1] & 0x7F
        header_size = 2 if marker < 126 else (4 if marker == 126 else 10)
        if size < header_size:
            return header_size - size
        if layout is None:
            _fail("websocket_frame_state")
        _fin, _opcode, parsed_header_size, length = layout
        return parsed_header_size + length - size

    def _reset_frame(self) -> None:
        self.frame_bytes.clear()
        self.frame_deadline = None

    def _check_fragment_deadline(self) -> None:
        if self.fragment_opcode is not None:
            if self.fragment_deadline is None:
                _fail("websocket_fragment_state")
            if time.monotonic() >= self.fragment_deadline:
                _fail("fragment_assembly_timeout")

    def _begin_fragment(self, payload: bytes) -> None:
        if self.fragment_opcode is not None:
            _fail("websocket_nested_fragment")
        if type(payload) is not bytes or len(payload) > MAX_WEBSOCKET_MESSAGE_BYTES:
            _fail("websocket_message_size")
        self.fragment_opcode = 1
        self.fragments = bytearray(payload)
        self.fragment_deadline = time.monotonic() + MAX_WEBSOCKET_FRAGMENT_ASSEMBLY_SECONDS
        self.fragment_count = 1

    def _append_fragment(self, payload: bytes) -> None:
        self._check_fragment_deadline()
        if self.fragment_opcode != 1:
            _fail("websocket_unexpected_continuation")
        if self.fragment_count >= MAX_WEBSOCKET_FRAGMENT_COUNT:
            _fail("websocket_fragment_count")
        if len(self.fragments) + len(payload) > MAX_WEBSOCKET_MESSAGE_BYTES:
            _fail("websocket_message_size")
        self.fragment_count += 1
        self.fragments.extend(payload)

    def _finish_fragment(self) -> bytes:
        self._check_fragment_deadline()
        if self.fragment_opcode != 1:
            _fail("websocket_fragment_fin")
        raw = bytes(self.fragments)
        try:
            raw.decode("utf-8", errors="strict")
        except Exception:
            _fail("websocket_text_utf8")
        self.fragment_opcode = None
        self.fragments.clear()
        self.fragment_deadline = None
        self.fragment_count = 0
        return raw

    def _frame(self, deadline: float) -> tuple[bool, int, bytes] | None:
        while True:
            now = time.monotonic()
            if self.frame_bytes and self.frame_deadline is not None:
                if now >= self.frame_deadline:
                    _fail("partial_websocket_frame")
            if now >= deadline:
                return None
            layout = self._frame_layout()
            if layout is not None:
                fin, opcode, header_size, length = layout
                total_size = header_size + length
                if len(self.frame_bytes) == total_size:
                    payload = bytes(self.frame_bytes[header_size:])
                    if opcode == 8:
                        _validate_close_payload(payload)
                    self._reset_frame()
                    return fin, opcode, payload
                if len(self.frame_bytes) > total_size:
                    _fail("websocket_frame_state")
            else:
                fin = opcode = header_size = length = 0
            remaining = min(MAX_RECEIVE_POLL_SECONDS, deadline - now)
            if self.frame_bytes:
                if self.frame_deadline is None:
                    _fail("websocket_frame_state")
                remaining = min(remaining, self.frame_deadline - now)
            if remaining <= 0:
                return None
            self.stream.settimeout(remaining)
            read_size = self._next_frame_read_size(layout)
            if read_size <= 0 or read_size > MAX_WEBSOCKET_MESSAGE_BYTES + 10:
                _fail("websocket_frame_state")
            try:
                chunk = self.stream.recv(read_size)
            except (TimeoutError, socket.timeout):
                now = time.monotonic()
                if self.frame_bytes and self.frame_deadline is not None:
                    if now >= self.frame_deadline:
                        _fail("partial_websocket_frame")
                return None
            if not chunk:
                _fail("websocket_eof")
            if type(chunk) is not bytes or len(chunk) > read_size:
                _fail("websocket_recv_shape")
            if not self.frame_bytes:
                self.frame_deadline = time.monotonic() + MAX_WEBSOCKET_FRAME_ASSEMBLY_SECONDS
            self.frame_bytes.extend(chunk)

    @property
    def partial_state_clear(self) -> bool:
        return (
            not self.frame_bytes
            and self.fragment_opcode is None
            and not self.fragments
            and not self.closed_by_server
        )

    def next_text(self, deadline: float) -> bytes | None:
        while True:
            self._check_fragment_deadline()
            frame = self._frame(deadline)
            if frame is None:
                self._check_fragment_deadline()
                return None
            fin, opcode, payload = frame
            if opcode == 9:
                self.stream.sendall(_mask_frame(10, payload))
                continue
            if opcode == 10:
                continue
            if opcode == 8:
                self.closed_by_server = True
                _fail("websocket_closed")
            if opcode == 1:
                if self.fragment_opcode is not None:
                    _fail("websocket_nested_fragment")
                if not fin:
                    self._begin_fragment(payload)
                    continue
                try:
                    payload.decode("utf-8", errors="strict")
                except Exception:
                    _fail("websocket_text_utf8")
                return payload
            if opcode == 0:
                self._append_fragment(payload)
                if fin:
                    return self._finish_fragment()
            else:
                _fail("websocket_binary_message")


@dataclass(frozen=True)
class SocketCloseObservation:
    socket_closed: bool
    normal_websocket_close: bool
    trailing_raw_messages: tuple[bytes, ...]


def _validate_close_payload(payload: bytes) -> None:
    if not payload:
        return
    if len(payload) == 1:
        _fail("websocket_close_payload")
    code = struct.unpack(">H", payload[:2])[0]
    if (
        code not in {1000, 1001, 1002, 1003, 1007, 1008, 1009, 1010, 1011, 1012, 1013, 1014}
        and not 3000 <= code <= 4999
    ):
        _fail("websocket_close_code")
    try:
        payload[2:].decode("utf-8", errors="strict")
    except Exception:
        _fail("websocket_close_reason_utf8")


class OKXPrivateWebSocketTransport:
    """Small fixed-host TLS/WebSocket transport with no proxy or reconnect."""

    def __init__(self, stream: Any):
        self._stream = stream
        self._reader = _WireReader(stream)
        self._socket_closed = False

    @classmethod
    def connect(
        cls,
        *,
        deadline: float,
        socket_factory: Callable[..., Any] | None = None,
        tls_context_factory: Callable[[], Any] | None = None,
    ) -> "OKXPrivateWebSocketTransport":
        if LIVE_TRANSPORT_ENABLEMENT != "ROOT_FIXED_ISSUER_ADMITTED":
            _fail("live_transport_disabled")
        if time.monotonic() >= deadline:
            _fail("observer_deadline")
        factory = socket_factory or socket.create_connection
        context_factory = tls_context_factory or ssl.create_default_context
        raw_socket = factory((DEMO_WSS_HOST, 443), timeout=min(5.0, deadline - time.monotonic()))
        try:
            context = context_factory()
            tls = context.wrap_socket(raw_socket, server_hostname=DEMO_WSS_HOST)
            tls.settimeout(min(5.0, deadline - time.monotonic()))
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            request = (
                f"GET {PRIVATE_PATH} HTTP/1.1\r\n"
                f"Host: {DEMO_WSS_HOST}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode("ascii")
            tls.sendall(request)
            response = bytearray()
            while not response.endswith(b"\r\n\r\n"):
                if time.monotonic() >= deadline or len(response) >= MAX_HANDSHAKE_BYTES:
                    _fail("websocket_handshake_timeout")
                tls.settimeout(min(0.5, max(0.001, deadline - time.monotonic())))
                try:
                    chunk = tls.recv(1)
                except (TimeoutError, socket.timeout):
                    _fail("websocket_handshake_timeout")
                if not chunk:
                    _fail("websocket_handshake_eof")
                response.extend(chunk)
            lines = bytes(response[:-4]).split(b"\r\n")
            if not lines or lines[0] != b"HTTP/1.1 101 Switching Protocols":
                _fail("websocket_handshake_status")
            headers: dict[str, str] = {}
            for line in lines[1:]:
                if b":" not in line:
                    _fail("websocket_handshake_header")
                name_raw, value_raw = line.split(b":", 1)
                try:
                    name = name_raw.decode("ascii").strip().lower()
                    value = value_raw.decode("ascii").strip()
                except Exception:
                    _fail("websocket_handshake_header")
                if not name or name in headers:
                    _fail("websocket_handshake_duplicate_header")
                headers[name] = value
            expected_accept = base64.b64encode(
                hashlib.sha1(key.encode("ascii") + _WS_GUID).digest()
            ).decode("ascii")
            if (
                headers.get("upgrade", "").lower() != "websocket"
                or "upgrade"
                not in {part.strip().lower() for part in headers.get("connection", "").split(",")}
                or headers.get("sec-websocket-accept") != expected_accept
                or "sec-websocket-extensions" in headers
                or "sec-websocket-protocol" in headers
            ):
                _fail("websocket_handshake_validation")
            return cls(tls)
        except Exception:
            try:
                raw_socket.close()
            except Exception:
                pass
            raise

    @property
    def partial_state_clear(self) -> bool:
        return self._reader.partial_state_clear

    def send_text(self, raw: bytes) -> None:
        if type(raw) is not bytes or len(raw) > MAX_WEBSOCKET_MESSAGE_BYTES:
            _fail("websocket_client_message_size")
        raw.decode("utf-8", errors="strict")
        self._stream.sendall(_mask_frame(1, raw))

    def next_text(self, deadline: float) -> bytes | None:
        return self._reader.next_text(deadline)

    def close_normally(self, deadline: float) -> SocketCloseObservation:
        if self._socket_closed:
            return SocketCloseObservation(True, self._reader.closed_by_server, ())
        normal = False
        trailing: list[bytes] = []
        trailing_bytes = 0

        def retain_trailing(raw: bytes) -> None:
            nonlocal trailing_bytes
            if (
                type(raw) is not bytes
                or len(raw) > MAX_WEBSOCKET_MESSAGE_BYTES
                or trailing_bytes + len(raw) > MAX_CLOSE_TRAILING_BYTES
            ):
                _fail("websocket_close_tail_size")
            if len(trailing) + 1 > MAX_EVENT_COUNT:
                _fail("event_count")
            trailing.append(raw)
            trailing_bytes += len(raw)

        try:
            self._stream.sendall(_mask_frame(8, struct.pack(">H", 1000)))
            while time.monotonic() < deadline:
                self._reader._check_fragment_deadline()
                frame = self._reader._frame(deadline)
                if frame is None:
                    continue
                fin, opcode, payload = frame
                if opcode == 9:
                    self._stream.sendall(_mask_frame(10, payload))
                    continue
                if opcode == 10:
                    continue
                if opcode == 8 and fin and payload[:2] == struct.pack(">H", 1000):
                    if self._reader.fragment_opcode is not None:
                        _fail("fragment_incomplete_at_close")
                    normal = True
                    self._reader.closed_by_server = True
                    break
                if opcode == 1 and fin:
                    if self._reader.fragment_opcode is not None:
                        _fail("websocket_nested_fragment")
                    try:
                        payload.decode("utf-8", errors="strict")
                    except Exception:
                        _fail("websocket_text_utf8")
                    retain_trailing(payload)
                    if payload == b"ping":
                        self.send_text(b"pong")
                    continue
                if opcode == 0:
                    self._reader._append_fragment(payload)
                    if fin:
                        retain_trailing(self._reader._finish_fragment())
                    continue
                if opcode == 1 and not fin:
                    if self._reader.fragment_opcode is not None:
                        _fail("websocket_nested_fragment")
                    self._reader._begin_fragment(payload)
                    continue
                if opcode == 2:
                    _fail("websocket_binary_message")
                _fail("websocket_close_frame")
        except Exception:
            normal = False
        try:
            self._stream.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            self._stream.close()
            self._socket_closed = True
        except Exception:
            self._socket_closed = False
        return SocketCloseObservation(self._socket_closed, normal, tuple(trailing))


def websocket_login(credentials: DemoCredentials, timestamp: str) -> bytes:
    if not re.fullmatch(r"[0-9]{10}(?:\.[0-9]{1,3})?", timestamp):
        _fail("login_timestamp")
    prehash = (timestamp + "GET" + "/users/self/verify").encode("ascii")
    signature = base64.b64encode(
        hmac.new(credentials.secret_key.encode("ascii"), prehash, hashlib.sha256).digest()
    ).decode("ascii")
    return _canonical_json(
        {
            "op": "login",
            "args": [
                {
                    "apiKey": credentials.api_key,
                    "passphrase": credentials.passphrase,
                    "timestamp": timestamp,
                    "sign": signature,
                }
            ],
        }
    )


def _subscriptions() -> tuple[tuple[str, dict[str, str]], ...]:
    return ((SUBSCRIPTION_ID, BALANCE_POSITION_SUBSCRIPTION),)


def _validate_request_id(value: Any) -> str:
    if type(value) is not str or not _REQUEST_ID.fullmatch(value):
        _fail("request_id_shape")
    return value


def _validate_server_message(raw: bytes) -> dict[str, Any]:
    if raw == b"ping":
        return {"_heartbeat": "ping"}
    value = strict_json(raw, limit=MAX_EVENT_BYTES)
    if type(value) is not dict:
        _fail("server_message_object")
    return value


def _journal_event(raw: bytes, events: list[bytes], emit: Callable[[int, bytes], None]) -> int:
    if len(events) >= MAX_EVENT_COUNT:
        _fail("event_count")
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_EVENT_BYTES:
        _fail("event_size")
    try:
        raw.decode("utf-8", errors="strict")
    except Exception:
        _fail("event_utf8")
    events.append(raw)
    payload = _event_payload(len(events), raw)
    emit(_FRAME_EVENT, payload)
    return len(events)


def _event_id(run_nonce: str, sequence: int, raw: bytes) -> str:
    if type(run_nonce) is not str or not _NONCE.fullmatch(run_nonce):
        _fail("run_nonce")
    if type(sequence) is not int or not 1 <= sequence <= MAX_EVENT_COUNT:
        _fail("event_sequence")
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_EVENT_BYTES:
        _fail("event_size")
    digest = hashlib.sha256(
        b"okx.m01.event.v1\0"
        + run_nonce.encode("ascii")
        + sequence.to_bytes(8, "big")
        + hashlib.sha256(raw).digest()
    ).hexdigest()
    return "m01ev-" + digest


def _validate_uid(value: Any) -> str:
    if type(value) is not str or not _UID.fullmatch(value):
        _fail("private_uid_shape")
    return value


def _validate_data_message(value: dict[str, Any]) -> tuple[str, str]:
    if set(value) - {"arg", "data", "ts", "connId"} or not {"arg", "data"} <= set(value):
        _fail("private_data_fields")
    if type(value["arg"]) is not dict or type(value["data"]) is not list:
        _fail("private_data_shape")
    if set(value["arg"]) != {"channel", "uid"}:
        _fail("balance_position_subscription_scope")
    if value["arg"].get("channel") != "balance_and_position":
        _fail("unknown_private_channel")
    uid = _validate_uid(value["arg"]["uid"])
    if any(type(row) is not dict for row in value["data"]):
        _fail("balance_position_data_shape")
    return "balance_and_position", uid


def _validate_channel_connection_event(
    value: dict[str, Any], *, sent_channels: set[str], connection_id: str | None
) -> bool:
    event = value.get("event")
    if event == "channel-conn-count-error":
        _fail("channel_conn_count_error")
    if event != "channel-conn-count":
        return False
    if set(value) != {"event", "channel", "connCount", "connId"}:
        _fail("channel_conn_count_fields")
    channel = value["channel"]
    if type(channel) is not str or channel not in sent_channels:
        _fail("channel_conn_count_unsent")
    count = value["connCount"]
    if type(count) is not str or not _CONNECTION_COUNT.fullmatch(count):
        _fail("channel_conn_count_shape")
    if type(connection_id) is not str or value["connId"] != connection_id:
        _fail("connection_id_changed")
    return True


def _validate_private_observation(
    value: dict[str, Any],
    *,
    sent_channels: set[str],
    connection_id: str | None,
    account_uid: str | None,
    expected_rest_uid: str,
) -> str | None:
    if _validate_channel_connection_event(
        value, sent_channels=sent_channels, connection_id=connection_id
    ):
        return account_uid
    if "event" in value:
        _fail("unexpected_private_event")
    channel, uid = _validate_data_message(value)
    if channel not in sent_channels:
        _fail("private_channel_unsent")
    if uid != expected_rest_uid:
        _fail("rest_uid_mismatch")
    if account_uid is not None and uid != account_uid:
        _fail("account_uid_changed")
    return uid if account_uid is None else account_uid


def _validate_message_connection(value: dict[str, Any], connection_id: str | None) -> None:
    if "connId" in value:
        actual = value["connId"]
        if (
            type(actual) is not str
            or not 1 <= len(actual) <= 128
            or any(ord(char) < 33 or ord(char) > 126 for char in actual)
            or (connection_id is not None and actual != connection_id)
        ):
            _fail("connection_id_changed")


def _validate_login_ack(value: dict[str, Any], connection_id: str | None) -> str:
    if set(value) != {"event", "code", "msg", "connId"}:
        _fail("login_ack_fields")
    if value.get("event") != "login" or value.get("code") != "0" or value.get("msg") != "":
        _fail("login_ack_rejected")
    conn_id = value.get("connId")
    if type(conn_id) is not str or not 1 <= len(conn_id) <= 128:
        _fail("connection_id")
    if any(ord(char) < 33 or ord(char) > 126 for char in conn_id):
        _fail("connection_id")
    if connection_id is not None and connection_id != conn_id:
        _fail("connection_id_changed")
    return conn_id


def _validate_subscription_ack(
    value: dict[str, Any], *, request_id: str, expected_arg: Mapping[str, str], connection_id: str
) -> None:
    allowed = {"id", "event", "arg", "connId", "msg", "code"}
    if not {"id", "event", "arg", "connId"} <= set(value) or set(value) - allowed:
        _fail("subscription_ack_fields")
    if (
        _validate_request_id(value.get("id")) != _validate_request_id(request_id)
        or value.get("event") != "subscribe"
        or value.get("arg") != dict(expected_arg)
        or value.get("connId") != connection_id
        or value.get("msg", "") != ""
        or value.get("code", "0") != "0"
    ):
        _fail("subscription_ack_mismatch")


def _capture_and_parse(
    raw: bytes,
    *,
    events: list[bytes],
    emit: Callable[[int, bytes], None],
    expected_connection_id: str | None,
) -> tuple[dict[str, Any], str | None]:
    # Exact server bytes are sent to the private parent journal before JSON parse.
    _journal_event(raw, events, emit)
    value = _validate_server_message(raw)
    if "_heartbeat" in value:
        return value, expected_connection_id
    _validate_message_connection(value, expected_connection_id)
    return value, expected_connection_id


def _read_controls(
    stream: Any,
    commands: queue.Queue[dict[str, Any]],
    stopped: threading.Event,
    started: threading.Event | None = None,
) -> None:
    if started is not None:
        started.set()
    try:
        while not stopped.is_set():
            kind, payload = _read_control_frame(stream)
            value = strict_json(
                payload[:-1] if payload.endswith(b"\n") else payload, limit=MAX_CONTROL_FRAME_BYTES
            )
            if kind != _FRAME_COMMAND or type(value) is not dict:
                _fail("control_shape")
            try:
                commands.put_nowait(value)
            except queue.Full:
                _fail("control_queue_full")
    except Exception:
        if not stopped.is_set():
            commands.put({"command": "stdin_closed"})


def run_actor_with_transport(
    request: LaunchRequest,
    *,
    credentials: DemoCredentials,
    transport: OKXPrivateWebSocketTransport,
    emit: Callable[[int, bytes], None],
    commands: queue.Queue[dict[str, Any]],
    control_stream: Any | None = None,
    expected_parent_pid: int | None = None,
    absolute_deadline: float | None = None,
) -> int:
    """Real protocol actor with injected transport only for credential-free tests."""
    local_deadline = time.monotonic() + min(request.event_timeout_ms / 1000.0, MAX_RUN_SECONDS)
    deadline = (
        min(local_deadline, absolute_deadline) if absolute_deadline is not None else local_deadline
    )
    worker_pid = os.getpid()
    parent_pid = expected_parent_pid if expected_parent_pid is not None else os.getppid()
    events: list[bytes] = []
    sent_channels: set[str] = set()
    connection_id: str | None = None
    account_uid: str | None = None
    private_data_event_count = 0
    connection_event_sequence: int | None = None
    readiness_event_sequence: int | None = None
    connection_event_id = ""
    readiness_event_id = ""
    login_ok = False
    acked_ids: list[str] = []
    ready_sent = False
    reason = "observer_incomplete"
    close = SocketCloseObservation(False, False, ())
    control_thread: threading.Thread | None = None
    control_stopped = threading.Event()
    return_code = 2
    try:
        if type(request) is not LaunchRequest or type(credentials) is not DemoCredentials:
            _fail("actor_input_type")
        if request.parent_pid != parent_pid:
            _fail("parent_pid_binding")
        if credentials != parse_credentials(request.credential_packet):
            _fail("credential_packet_mismatch")
        if account_scope_sha256(credentials) != request.account_scope_sha256:
            _fail("account_scope_binding")
        if credential_binding_sha256(credentials) != request.credential_binding_sha256:
            _fail("credential_binding")
        timestamp = str(int(time.time()))
        transport.send_text(websocket_login(credentials, timestamp))
        while not login_ok:
            if time.monotonic() >= deadline:
                _fail("login_deadline")
            raw = transport.next_text(deadline)
            if raw is None:
                continue
            if raw == b"ping":
                _journal_event(raw, events, emit)
                transport.send_text(b"pong")
                continue
            value, _ = _capture_and_parse(
                raw, events=events, emit=emit, expected_connection_id=connection_id
            )
            if value.get("event") == "error":
                _fail("login_server_error")
            if value.get("event") != "login":
                _fail("login_ack_expected")
            connection_id = _validate_login_ack(value, connection_id)
            login_ok = True
            connection_event_sequence = len(events)
        for request_id, expected_arg in _subscriptions():
            _validate_request_id(request_id)
            sent_channels.add(expected_arg["channel"])
            command = _canonical_json(
                {"id": request_id, "op": "subscribe", "args": [dict(expected_arg)]}
            )
            transport.send_text(command)
            pending_subscription_id = request_id
            while request_id not in acked_ids:
                if time.monotonic() >= deadline:
                    _fail("subscription_deadline")
                raw = transport.next_text(deadline)
                if raw is None:
                    continue
                if raw == b"ping":
                    _journal_event(raw, events, emit)
                    transport.send_text(b"pong")
                    continue
                value, _ = _capture_and_parse(
                    raw, events=events, emit=emit, expected_connection_id=connection_id
                )
                if value.get("event") == "error":
                    _fail("subscription_server_error")
                if value.get("event") == "subscribe":
                    ack_id = _validate_request_id(value.get("id"))
                    expected_by_id = dict(_subscriptions())
                    if (
                        ack_id != pending_subscription_id
                        or ack_id not in expected_by_id
                        or ack_id in acked_ids
                    ):
                        _fail("unexpected_subscription_ack")
                    _validate_subscription_ack(
                        value,
                        request_id=pending_subscription_id,
                        expected_arg=expected_by_id[ack_id],
                        connection_id=connection_id,
                    )
                    acked_ids.append(ack_id)
                    continue
                account_uid = _validate_private_observation(
                    value,
                    sent_channels=sent_channels,
                    connection_id=connection_id,
                    account_uid=account_uid,
                    expected_rest_uid=credentials.expected_rest_uid,
                )
                if value.get("event") is None:
                    private_data_event_count += 1
        if len(acked_ids) != len(_subscriptions()) or len(set(acked_ids)) != len(acked_ids):
            _fail("subscriptions_incomplete")
        if connection_id is None or connection_event_sequence is None:
            _fail("connection_event_missing")
        if len(events) == 0:
            _fail("event_journal_empty")
        if not acked_ids:
            _fail("subscription_ack_missing")
        # The pending ACK has just been captured and validated.
        readiness_event_sequence = len(events)
        connection_event_id = _event_id(
            request.run_nonce, connection_event_sequence, events[connection_event_sequence - 1]
        )
        readiness_event_id = _event_id(
            request.run_nonce, readiness_event_sequence, events[readiness_event_sequence - 1]
        )
        ready = {
            "account_scope_sha256": request.account_scope_sha256,
            "credential_binding_sha256": request.credential_binding_sha256,
            "balance_position_payload_count": private_data_event_count,
            "balance_snapshot_observed": False,
            "connection_event_id": connection_event_id,
            "connection_id_sha256": hashlib.sha256(connection_id.encode("utf-8")).hexdigest(),
            "current_rest_read_receipt_sha256": request.current_rest_read_receipt_sha256,
            "parent_pid": request.parent_pid,
            "owner_invocation_sha256": request.owner_invocation_sha256,
            "profile": PROFILE,
            "protocol_version": PROTOCOL_VERSION,
            "run_nonce": request.run_nonce,
            "readiness_event_id": readiness_event_id,
            "subscription_ack_ids": list(acked_ids),
            "worker_pid": worker_pid,
            "worker_source_sha256": request.worker_source_sha256,
        }
        if control_stream is not None:
            control_started = threading.Event()
            control_thread = threading.Thread(
                target=_read_controls,
                args=(control_stream, commands, control_stopped, control_started),
                daemon=True,
                name="okx-m01-control-reader",
            )
            try:
                control_thread.start()
            except Exception:
                _fail("control_reader_start_failed")
            if not control_started.wait(timeout=1.0) or not control_thread.is_alive():
                _fail("control_reader_start_failed")
        _frame_json(emit, _FRAME_READY, ready)
        ready_sent = True
        reason = "ready_waiting_for_parent_close"
        quiet_request: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            if quiet_request is None:
                try:
                    command = commands.get_nowait()
                except queue.Empty:
                    command = None
            else:
                command = None
            if command is not None:
                if command.get("command") == "stdin_closed":
                    _fail("parent_control_eof")
                if command.get("run_nonce") != request.run_nonce:
                    _fail("control_nonce")
                command_name = command.get("command")
                if command_name == "quiet":
                    _keys(
                        command,
                        {"command", "command_id", "cursor", "duration_ms", "run_nonce"},
                        "quiet_command_fields",
                    )
                    command_id = command["command_id"]
                    cursor = command["cursor"]
                    duration_ms = command["duration_ms"]
                    if (
                        type(command_id) is not str
                        or not _NONCE.fullmatch(command_id)
                        or type(cursor) is not int
                        or type(duration_ms) is not int
                        or not 1 <= duration_ms <= MAX_QUIET_MS
                    ):
                        _fail("quiet_command_shape")
                    quiet_request = {
                        "command_id": command_id,
                        "cursor": cursor,
                        "deadline": time.monotonic() + duration_ms / 1000.0,
                        "started_ns": time.monotonic_ns(),
                        "valid": cursor == len(events),
                    }
                    if not quiet_request["valid"]:
                        _frame_json(
                            emit,
                            _FRAME_QUIET_ACK,
                            {
                                "command_id": command_id,
                                "cursor": len(events),
                                "partial_frame_clear": transport.partial_state_clear,
                                "quiet": False,
                                "run_nonce": request.run_nonce,
                            },
                        )
                        quiet_request = None
                elif command_name == "drain":
                    _keys(command, {"command", "command_id", "run_nonce"}, "drain_command_fields")
                    if type(command["command_id"]) is not str or not _NONCE.fullmatch(
                        command["command_id"]
                    ):
                        _fail("drain_command_id")
                    journal_digest = hashlib.sha256(encode_journal(events)).hexdigest()
                    _frame_json(
                        emit,
                        _FRAME_DRAIN_ACK,
                        {
                            "command_id": command["command_id"],
                            "cursor": len(events),
                            "event_journal_sha256": journal_digest,
                            "run_nonce": request.run_nonce,
                        },
                    )
                elif command_name == "close":
                    _keys(command, {"command", "command_id", "run_nonce"}, "close_command_fields")
                    reason = "normal_close_requested"
                    return_code = 2
                    break
                else:
                    _fail("control_command_unknown")
            if time.monotonic() >= deadline:
                _fail("observer_deadline")
            try:
                raw = transport.next_text(
                    min(deadline, time.monotonic() + MAX_RECEIVE_POLL_SECONDS)
                )
            except CandidateError:
                raise
            if raw is not None:
                if raw == b"ping":
                    _journal_event(raw, events, emit)
                    transport.send_text(b"pong")
                    continue
                _journal_event(raw, events, emit)
                if quiet_request is not None:
                    quiet_request["valid"] = False
                    _frame_json(
                        emit,
                        _FRAME_QUIET_ACK,
                        {
                            "command_id": quiet_request["command_id"],
                            "cursor": len(events),
                            "partial_frame_clear": transport.partial_state_clear,
                            "quiet": False,
                            "run_nonce": request.run_nonce,
                        },
                    )
                    quiet_request = None
                value = _validate_server_message(raw)
                _validate_message_connection(value, connection_id)
                account_uid = _validate_private_observation(
                    value,
                    sent_channels=sent_channels,
                    connection_id=connection_id,
                    account_uid=account_uid,
                    expected_rest_uid=credentials.expected_rest_uid,
                )
                if value.get("event") is None:
                    private_data_event_count += 1
            if quiet_request is not None and time.monotonic() >= quiet_request["deadline"]:
                partial_clear = transport.partial_state_clear
                quiet_value = bool(
                    quiet_request["valid"]
                    and partial_clear
                    and len(events) == quiet_request["cursor"]
                )
                if not partial_clear:
                    _fail("quiet_partial_frame")
                _frame_json(
                    emit,
                    _FRAME_QUIET_ACK,
                    {
                        "command_id": quiet_request["command_id"],
                        "cursor": len(events),
                        "partial_frame_clear": partial_clear,
                        "quiet": quiet_value,
                        "run_nonce": request.run_nonce,
                    },
                )
                quiet_request = None
        if reason != "normal_close_requested":
            _fail("observer_deadline")
    except CandidateError as error:
        reason = error.code
    except Exception:
        reason = "actor_failed"
    finally:
        control_stopped.set()
        close_deadline = time.monotonic() + MAX_CLOSE_SECONDS
        try:
            close = transport.close_normally(close_deadline)
        except Exception:
            close = SocketCloseObservation(False, False, ())
        for trailing in close.trailing_raw_messages:
            try:
                _journal_event(trailing, events, emit)
                trailing_value = _validate_server_message(trailing)
                if "_heartbeat" not in trailing_value:
                    _validate_message_connection(trailing_value, connection_id)
                    account_uid = _validate_private_observation(
                        trailing_value,
                        sent_channels=sent_channels,
                        connection_id=connection_id,
                        account_uid=account_uid,
                        expected_rest_uid=credentials.expected_rest_uid,
                    )
                    if trailing_value.get("event") is None:
                        private_data_event_count += 1
            except Exception:
                if reason == "normal_close_requested":
                    reason = "close_trailing_message_invalid"
        if control_thread is not None and control_thread.ident is not None:
            control_thread.join(
                timeout=min(MAX_CLOSE_SECONDS, max(0.0, close_deadline - time.monotonic()))
            )
        control_joined = (
            control_thread is None or control_thread.ident is None or not control_thread.is_alive()
        )
        if reason == "normal_close_requested" and not control_joined:
            reason = "control_thread_join_unconfirmed"
        normal = (
            reason == "normal_close_requested"
            and close.socket_closed
            and close.normal_websocket_close
            and control_joined
        )
        if normal:
            return_code = 0
        final = {
            "account_scope_sha256": request.account_scope_sha256,
            "credential_binding_sha256": request.credential_binding_sha256,
            "balance_position_payload_count": private_data_event_count,
            "balance_snapshot_observed": False,
            "connection_event_id": connection_event_id if connection_event_sequence else "",
            "connection_id_sha256": (
                hashlib.sha256(connection_id.encode("utf-8")).hexdigest()
                if connection_id is not None
                else ""
            ),
            "current_rest_read_receipt_sha256": request.current_rest_read_receipt_sha256,
            "event_count": len(events),
            "event_journal_sha256": hashlib.sha256(encode_journal(events)).hexdigest(),
            "login_acknowledged": login_ok,
            "normal_websocket_close": close.normal_websocket_close,
            "owner_invocation_sha256": request.owner_invocation_sha256,
            "parent_pid": request.parent_pid,
            "profile": PROFILE,
            "reason": reason,
            "run_nonce": request.run_nonce,
            "socket_closed": close.socket_closed,
            "status": CASE_STATUS,
            "subscription_ack_ids": list(acked_ids),
            "readiness_event_id": readiness_event_id if readiness_event_sequence else "",
            "worker_pid": worker_pid,
            "worker_source_sha256": request.worker_source_sha256,
            "ready_sent": ready_sent,
            "control_thread_joined": control_joined,
        }
        try:
            _frame_json(emit, _FRAME_RECEIPT, final)
        except Exception:
            return_code = 2
    return return_code


def encode_journal(events: list[bytes]) -> bytes:
    if type(events) is not list or len(events) > MAX_EVENT_COUNT:
        _fail("event_count")
    output = bytearray(_FRAME_MAGIC)
    chain = hashlib.sha256(_FRAME_MAGIC).digest()
    for raw in events:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_EVENT_BYTES:
            _fail("event_size")
        record = struct.pack(">I", len(raw)) + raw
        chain = hashlib.sha256(chain + record).digest()
        output.extend(record)
        output.extend(chain)
        if len(output) > MAX_OUTPUT_BYTES:
            _fail("journal_size")
    return bytes(output)


def _worker_source_sha256() -> str:
    value = globals().get("__okx_verified_worker_source_sha256__")
    if type(value) is not str or not _HEX64.fullmatch(value):
        _fail("worker_source_bootstrap")
    return value


def _stdio_emitter(stream: Any) -> Callable[[int, bytes], None]:
    lock = threading.Lock()
    total_bytes = 0

    def emit(kind: int, payload: bytes) -> None:
        nonlocal total_bytes
        frame = encode_frame(kind, payload)
        with lock:
            if total_bytes + len(frame) > MAX_OUTPUT_BYTES:
                _fail("stdout_limit")
            stream.write(frame)
            stream.flush()
            total_bytes += len(frame)

    return emit


def main_from_stdio() -> int:
    """Fixed isolated child entry. Credentials are accepted only on stdin."""
    output = sys.stdout.buffer
    emit = _stdio_emitter(output)
    try:
        raw = _read_launch_line(sys.stdin.buffer)
        request = parse_launch_frame(raw)
        if LIVE_TRANSPORT_ENABLEMENT != "ROOT_FIXED_ISSUER_ADMITTED":
            _frame_json(
                emit,
                _FRAME_ERROR,
                {
                    "profile": PROFILE,
                    "reason": "live_transport_disabled",
                    "run_nonce": request.run_nonce,
                    "status": CASE_STATUS,
                },
            )
            return 2
        source_hash = _worker_source_sha256()
        if request.worker_source_sha256 != source_hash or request.parent_pid != os.getppid():
            _fail("worker_parent_binding")
        credentials = parse_credentials(request.credential_packet)
        if account_scope_sha256(credentials) != request.account_scope_sha256:
            _fail("account_scope_binding")
        if credential_binding_sha256(credentials) != request.credential_binding_sha256:
            _fail("credential_binding")
        deadline = time.monotonic() + min(request.event_timeout_ms / 1000.0, MAX_RUN_SECONDS)
        transport = OKXPrivateWebSocketTransport.connect(deadline=deadline)
        commands: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=128)
        return run_actor_with_transport(
            request,
            credentials=credentials,
            transport=transport,
            emit=emit,
            commands=commands,
            control_stream=sys.stdin.buffer,
            absolute_deadline=deadline,
        )
    except CandidateError as error:
        try:
            _frame_json(
                emit,
                _FRAME_ERROR,
                {
                    "profile": PROFILE,
                    "reason": error.code,
                    "status": CASE_STATUS,
                },
            )
        except Exception:
            pass
        return 2
    except Exception:
        try:
            _frame_json(
                emit,
                _FRAME_ERROR,
                {"profile": PROFILE, "reason": "worker_failed", "status": CASE_STATUS},
            )
        except Exception:
            pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main_from_stdio())
