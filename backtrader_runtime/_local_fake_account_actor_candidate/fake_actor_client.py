from __future__ import annotations

import json
import math
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .account_actor_port import (
    AccountActorGateError,
    ActorCommandContextV1,
    ActorCommandExpectationV2,
    ActorCommandReceiptV2,
    ActorCommandState,
    CtpAccountActorPort,
    CtpCancelIntentV2,
    CtpSubmitIntentV2,
    validate_actor_receipt,
)

_SCHEMA = "account-actor-wire.v1"
_MAX_RESPONSE_LINE_BYTES = 64 * 1024
_MAX_REQUEST_BYTES = 64 * 1024
_MAX_RESPONSE_QUEUE_LINES = 16
_MAX_RESPONSE_QUEUE_BYTES = 512 * 1024
_STDERR_TAIL_BYTES = 8 * 1024


class _BoundedResponseMailbox:
    """Bound both queued line count and aggregate payload bytes."""

    def __init__(self, max_lines: int, max_bytes: int) -> None:
        self._max_lines = max_lines
        self._max_bytes = max_bytes
        self._condition = threading.Condition()
        self._lines = deque()
        self._queued_bytes = 0
        self._terminal = None

    def publish_line(self, line: bytes) -> bool:
        with self._condition:
            if self._terminal is not None:
                return False
            if (
                len(self._lines) >= self._max_lines
                or self._queued_bytes + len(line) > self._max_bytes
            ):
                self._lines.clear()
                self._queued_bytes = 0
                self._terminal = "overflow"
                self._condition.notify_all()
                return False
            self._lines.append(line)
            self._queued_bytes += len(line)
            self._condition.notify()
            return True

    def finish(self, kind: str) -> None:
        with self._condition:
            if self._terminal is None:
                self._terminal = kind
            self._condition.notify_all()

    def get(self, timeout: float):
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                if self._terminal in ("overflow", "oversize", "read_error"):
                    return self._terminal, None
                if self._lines:
                    line = self._lines.popleft()
                    self._queued_bytes -= len(line)
                    return "line", line
                if self._terminal is not None:
                    return self._terminal, None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise queue.Empty
                self._condition.wait(remaining)


@dataclass(frozen=True)
class FakeWireReceiptDetails:
    """Extra local test metadata; not part of the production port receipt."""

    writer_epoch: int
    snapshot_version: int
    dispatch_id: int
    durable_command_digest: str
    fake_send_id: str
    provider_acknowledged: bool


class SubprocessFakeActorPort(CtpAccountActorPort):
    """stdio client to the child-process fake actor; deliberately no local fallback."""

    def __init__(
        self,
        database_path: str,
        response_timeout_seconds: float = 2.0,
        request_timeout_seconds: float = 2.0,
        response_queue_max_lines: int = _MAX_RESPONSE_QUEUE_LINES,
        response_queue_max_bytes: int = _MAX_RESPONSE_QUEUE_BYTES,
    ) -> None:
        if (
            type(response_timeout_seconds) not in (int, float)
            or not math.isfinite(response_timeout_seconds)
            or response_timeout_seconds <= 0
        ):
            raise ValueError("positive finite response timeout required")
        if (
            type(request_timeout_seconds) not in (int, float)
            or not math.isfinite(request_timeout_seconds)
            or request_timeout_seconds <= 0
        ):
            raise ValueError("positive finite request timeout required")
        if type(response_queue_max_lines) is not int or not 1 <= response_queue_max_lines <= 128:
            raise ValueError("response queue line bound out of range")
        if (
            type(response_queue_max_bytes) is not int
            or not 1 <= response_queue_max_bytes <= 4 * 1024 * 1024
        ):
            raise ValueError("response queue byte bound out of range")
        self._response_timeout_seconds = float(response_timeout_seconds)
        self._request_timeout_seconds = float(request_timeout_seconds)
        self._response_lines = _BoundedResponseMailbox(
            response_queue_max_lines,
            response_queue_max_bytes,
        )
        self._exchange_lock = threading.Lock()
        self._active_writer = None
        self._active_writer_done = None
        self._cleanup_uncertain = False
        self._stderr_lock = threading.Lock()
        self._stderr_bytes_drained = 0
        self._stderr_tail = bytearray()
        self._closed = False
        self._stdout_reader = None
        self._stderr_reader = None
        service_path = Path(__file__).resolve().with_name("fake_actor_service.py")
        self._process = subprocess.Popen(
            [sys.executable, "-B", str(service_path), database_path],
            cwd=str(service_path.parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            bufsize=0,
        )
        self._stdout_reader = threading.Thread(
            target=self._drain_stdout,
            name="fake-actor-stdout-reader",
            daemon=True,
        )
        self._stderr_reader = threading.Thread(
            target=self._drain_stderr,
            name="fake-actor-stderr-reader",
            daemon=True,
        )
        self._stdout_reader.start()
        self._stderr_reader.start()
        self._last_wire_receipt: Optional[FakeWireReceiptDetails] = None  # noqa: UP045 - retain Python 3.8 compatibility
        try:
            ready = self._read_response()
            if ready.get("kind") != "ready":
                raise AccountActorGateError("fake_actor_service_not_ready")
            self._stale_context = ActorCommandContextV1(**ready["stale_context"])
            self._current_context = ActorCommandContextV1(**ready["current_context"])
            self._snapshot_version = ready["snapshot_version"]
            if (
                type(self._snapshot_version) is not int
                or self._snapshot_version <= 0
                or self._current_context.actor_epoch <= self._stale_context.actor_epoch
            ):
                raise AccountActorGateError("fake_actor_service_context_invalid")
        except Exception:
            self.close()
            raise

    @property
    def test_stale_context(self) -> ActorCommandContextV1:
        return self._stale_context

    @property
    def test_current_context(self) -> ActorCommandContextV1:
        return self._current_context

    @property
    def test_snapshot_version(self) -> int:
        return self._snapshot_version

    @property
    def test_last_wire_receipt(self) -> Optional[FakeWireReceiptDetails]:  # noqa: UP045 - retain Python 3.8 compatibility
        return self._last_wire_receipt

    @property
    def test_stderr_bytes_drained(self) -> int:
        with self._stderr_lock:
            return self._stderr_bytes_drained

    @property
    def test_stderr_tail(self) -> bytes:
        with self._stderr_lock:
            return bytes(self._stderr_tail)

    def submit_order(self, intent: CtpSubmitIntentV2) -> ActorCommandReceiptV2:
        if type(intent) is not CtpSubmitIntentV2:
            raise AccountActorGateError("typed_actor_intent_required")
        try:
            intent.__post_init__()
        except (TypeError, ValueError):
            raise AccountActorGateError("actor_intent_invalid") from None
        wire_intent = {
            "intent_id": intent.intent_id,
            "instrument_id": intent.instrument_id,
            "exchange_id": intent.exchange_id,
            "side": intent.side,
            "offset": intent.offset,
            "hedge_flag": intent.hedge_flag,
            "quantity": intent.quantity,
            "limit_price": format(intent.limit_price, "f"),
            "context": intent.context.to_payload(),
            "command_digest": intent.command_digest,
        }
        response = self._exchange({"schema": _SCHEMA, "kind": "submit", "intent": wire_intent})
        if response.get("kind") == "rejected":
            reason = response.get("reason")
            mapped = {
                "intent_actor_epoch_mismatch": "actor_service_stale_epoch",
                "intent_session_binding_mismatch": "actor_service_stale_session",
            }.get(reason, "actor_service_rejected")
            raise AccountActorGateError(mapped)
        if response.get("kind") != "receipt":
            raise AccountActorGateError("actor_service_receipt_invalid")
        receipt_data = response.get("receipt")
        if type(receipt_data) is not dict:
            raise AccountActorGateError("actor_service_receipt_invalid")
        try:
            context = ActorCommandContextV1(**receipt_data["context"])
            receipt = ActorCommandReceiptV2(
                operation=receipt_data["operation"],
                command_id=receipt_data["command_id"],
                state=ActorCommandState[receipt_data["state"]],
                context=context,
                command_digest=receipt_data["command_digest"],
            )
            validated = validate_actor_receipt(
                receipt,
                expected=ActorCommandExpectationV2.from_intent(intent),
            )
            details = FakeWireReceiptDetails(
                writer_epoch=receipt_data["writer_epoch"],
                snapshot_version=receipt_data["snapshot_version"],
                dispatch_id=receipt_data["dispatch_id"],
                durable_command_digest=receipt_data["durable_command_digest"],
                fake_send_id=receipt_data["fake_send_id"],
                provider_acknowledged=receipt_data["provider_acknowledged"],
            )
            if (
                type(details.writer_epoch) is not int
                or details.writer_epoch != intent.context.actor_epoch
                or type(details.snapshot_version) is not int
                or details.snapshot_version != self._snapshot_version
                or type(details.dispatch_id) is not int
                or details.dispatch_id <= 0
                or type(details.durable_command_digest) is not str
                or len(details.durable_command_digest) != 64
                or type(details.fake_send_id) is not str
                or not details.fake_send_id
                or details.provider_acknowledged is not False
            ):
                raise ValueError("fake receipt details invalid")
        except (KeyError, TypeError, ValueError):
            raise AccountActorGateError("actor_service_receipt_binding_invalid") from None
        self._last_wire_receipt = details
        return validated

    def cancel_order(self, intent: CtpCancelIntentV2) -> ActorCommandReceiptV2:
        del intent
        raise AccountActorGateError("fake_wire_cancel_not_implemented")

    def test_inspect_fake_sink(self) -> dict:
        return self._exchange({"schema": _SCHEMA, "kind": "test_inspect_fake_sink"})

    def test_inspect_import_boundary(self) -> dict:
        return self._exchange({"schema": _SCHEMA, "kind": "test_import_boundary"})

    def test_crash_service(self) -> dict:
        return self._exchange({"schema": _SCHEMA, "kind": "test_abrupt_exit"})

    def test_stall_output(self) -> dict:
        return self._exchange({"schema": _SCHEMA, "kind": "test_stall_output"})

    def test_stderr_burst(self, byte_count: int) -> dict:
        if type(byte_count) is not int or not 65536 <= byte_count <= 4 * 1024 * 1024:
            raise ValueError("stderr burst byte count out of range")
        return self._exchange(
            {"schema": _SCHEMA, "kind": "test_stderr_burst", "byte_count": byte_count}
        )

    def test_response_queue_payload(self, byte_count: int) -> dict:
        if type(byte_count) is not int or not 1 <= byte_count <= 48 * 1024:
            raise ValueError("queue payload byte count out of range")
        return self._exchange(
            {"schema": _SCHEMA, "kind": "test_response_queue_payload", "byte_count": byte_count}
        )

    def _exchange(self, request: dict) -> dict:
        if not self._exchange_lock.acquire(
            timeout=self._request_timeout_seconds + self._response_timeout_seconds
        ):
            raise AccountActorGateError("actor_service_request_busy")
        try:
            return self._exchange_locked(request)
        finally:
            self._exchange_lock.release()

    def _exchange_locked(self, request: dict) -> dict:
        process = self._process
        if self._closed or process.poll() is not None or process.stdin is None:
            raise AccountActorGateError("actor_service_unavailable")
        try:
            request_bytes = (
                json.dumps(
                    request,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError, OverflowError):
            raise AccountActorGateError("actor_service_request_invalid") from None
        if len(request_bytes) > _MAX_REQUEST_BYTES:
            raise AccountActorGateError("actor_service_request_too_large")

        write_done = threading.Event()
        write_error = []

        def write_request() -> None:
            try:
                stream = process.stdin
                if stream is None:
                    raise BrokenPipeError
                remaining = memoryview(request_bytes)
                while remaining:
                    written = stream.write(remaining)
                    if written is None or written <= 0:
                        raise BrokenPipeError
                    remaining = remaining[written:]
                stream.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                write_error.append(exc)
            finally:
                write_done.set()

        writer = threading.Thread(
            target=write_request,
            name="fake-actor-request-writer",
            daemon=True,
        )
        self._active_writer = writer
        self._active_writer_done = write_done
        writer.start()
        if not write_done.wait(self._request_timeout_seconds):
            self.close()
            raise AccountActorGateError("actor_service_request_timeout")
        writer.join(timeout=0.05)
        self._active_writer = None
        self._active_writer_done = None
        if writer.is_alive():
            self.close()
            raise AccountActorGateError("actor_service_cleanup_uncertain")
        if write_error:
            self.close()
            raise AccountActorGateError("actor_service_unavailable") from None
        return self._read_response()

    def _read_response(self) -> dict:
        if self._closed:
            raise AccountActorGateError("actor_service_unavailable")
        try:
            kind, line = self._response_lines.get(timeout=self._response_timeout_seconds)
        except queue.Empty:
            self.close()
            raise AccountActorGateError("actor_service_response_timeout") from None
        if kind == "eof":
            self.close()
            raise AccountActorGateError("actor_service_unavailable")
        if kind == "overflow":
            self.close()
            raise AccountActorGateError("actor_service_response_queue_overflow")
        if kind == "oversize":
            self.close()
            raise AccountActorGateError("actor_service_wire_invalid")
        if kind == "read_error":
            self.close()
            raise AccountActorGateError("actor_service_unavailable")
        if kind != "line" or line is None:
            self.close()
            raise AccountActorGateError("actor_service_wire_invalid")
        try:
            response = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, TypeError, ValueError):
            self.close()
            raise AccountActorGateError("actor_service_wire_invalid") from None
        if type(response) is not dict or response.get("schema") != _SCHEMA:
            self.close()
            raise AccountActorGateError("actor_service_wire_invalid")
        return response

    def _drain_stdout(self) -> None:
        stream = self._process.stdout
        if stream is None:
            self._response_lines.finish("eof")
            return
        pending = bytearray()
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    if pending and not self._response_lines.publish_line(bytes(pending)):
                        return
                    self._response_lines.finish("eof")
                    return
                pending.extend(chunk)
                while True:
                    newline_at = pending.find(b"\n")
                    if newline_at < 0:
                        break
                    line_size = newline_at + 1
                    if line_size > _MAX_RESPONSE_LINE_BYTES:
                        self._response_lines.finish("oversize")
                        return
                    line = bytes(pending[:line_size])
                    del pending[:line_size]
                    if not self._response_lines.publish_line(line):
                        return
                if len(pending) > _MAX_RESPONSE_LINE_BYTES:
                    self._response_lines.finish("oversize")
                    return
        except (OSError, ValueError):
            self._response_lines.finish("read_error")

    def _drain_stderr(self) -> None:
        stream = self._process.stderr
        if stream is None:
            return
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    return
                with self._stderr_lock:
                    self._stderr_bytes_drained += len(chunk)
                    self._stderr_tail.extend(chunk)
                    if len(self._stderr_tail) > _STDERR_TAIL_BYTES:
                        del self._stderr_tail[:-_STDERR_TAIL_BYTES]
        except (OSError, ValueError):
            return

    def close(self) -> None:
        process = getattr(self, "_process", None)
        if process is None:
            return
        if self._closed:
            if self._cleanup_uncertain:
                raise AccountActorGateError("actor_service_cleanup_uncertain")
            return
        self._closed = True
        streams = (process.stdin, process.stdout, process.stderr)
        writer = self._active_writer
        writer_done = self._active_writer_done
        write_in_progress = (
            writer is not None
            and writer.is_alive()
            and writer_done is not None
            and not writer_done.is_set()
        )
        forced_termination = False
        cleanup_uncertain = False
        try:
            if process.stdin is not None and not write_in_progress:
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass
            if process.poll() is None:
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    forced_termination = True
                    try:
                        process.terminate()
                    except OSError:
                        cleanup_uncertain = True
                    try:
                        process.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        try:
                            process.kill()
                        except OSError:
                            cleanup_uncertain = True
                        try:
                            process.wait(timeout=0.5)
                        except subprocess.TimeoutExpired:
                            cleanup_uncertain = True
            if process.poll() is None:
                cleanup_uncertain = True
            # This fake client has no OS job/process-group supervisor. A forced
            # kill confirms neither descendant cleanup nor process-tree closure.
            if forced_termination:
                cleanup_uncertain = True
        except (OSError, subprocess.SubprocessError, ValueError, RuntimeError):
            cleanup_uncertain = True
        finally:
            # Close every pipe even when poll() reported an already-exited child
            # or a shutdown operation raised unexpectedly.
            for stream in streams:
                if stream is not None:
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        cleanup_uncertain = True
            for reader in (writer, self._stdout_reader, self._stderr_reader):
                if reader is not None and reader is not threading.current_thread():
                    try:
                        reader.join(timeout=0.5)
                    except RuntimeError:
                        cleanup_uncertain = True
                    else:
                        if reader.is_alive():
                            cleanup_uncertain = True
        self._cleanup_uncertain = cleanup_uncertain
        if cleanup_uncertain:
            raise AccountActorGateError("actor_service_cleanup_uncertain")
