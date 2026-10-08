"""Local Windows Job supervisor for the unregistered SimNow C01 worker.

This candidate only transports a bounded request to one source-pinned worker
and reports parent-observed process facts. It has no CLI registration, no
provider admission, and no path that reports certification PASS.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Optional, Tuple, Union

from .certification_simnow_c01_v3_protocol import (
    MAX_LAUNCH_FRAME_BYTES,
    MAX_WORKER_FRAME_BYTES,
    C01LaunchRequest,
    C01PairBinding,
    C01PairBindingRef,
    C01ProcessLifecycleReceipt,
    C01WorkerReceipt,
    encode_launch_frame,
    parse_worker_frame,
)
from . import certification_simnow_c01_interpreter_binding_v1 as interpreter_binding


MAX_WORKER_SOURCE_BYTES = 2 * 1024 * 1024
MAX_STDERR_BYTES = 64 * 1024
MAX_DIAGNOSTIC_STDERR_BYTES = 131072
MAX_DIAGNOSTIC_INTENT_RECORDS = 128
MAX_DIAGNOSTIC_INTENT_FRAME_BYTES = 1024
MAX_RUNTIME_SECONDS = 90.0
MAX_CLEANUP_SECONDS = 5.0
_POLL_INTERVAL_SECONDS = 0.01
MAX_NONZERO_EXIT_JOB_DRAIN_GRACE_SECONDS = 0.5
_HEX_SHA256 = frozenset("0123456789abcdef")
_DIAGNOSTIC_INTENT_MAGIC = b"C01INTENT\x01"
_DIAGNOSTIC_INTENT_PROTOCOL = "simnow.c01.stage-intent.v1"
_DIAGNOSTIC_INTENT_VERSION = 1
_DIAGNOSTIC_INTENT_STAGES = frozenset(
    {
        "worker",
        "private_paths",
        "sdk_install_verify",
        "sdk_import",
        "client_construct",
        "client_start",
        "client_no_join_start_policy",
        "native_create_trader_api",
        "native_register_spi_attach",
        "native_subscribe_private_topic",
        "native_subscribe_public_topic",
        "native_register_front",
        "native_api_init",
        "native_register_spi_detach",
        "native_release",
        "login_wait",
        "snapshot_directory",
        "baseline_orders_read",
        "baseline_positions_read",
        "baseline_funds_read",
        "final_orders_read",
        "final_positions_read",
        "final_funds_read",
        "baseline_snapshot_write",
        "final_snapshot_write",
        "native_stop",
        "worker_receipt",
        "authenticate_request",
        "login_request",
        "baseline_orders_request",
        "baseline_positions_request",
        "baseline_funds_request",
        "final_orders_request",
        "final_positions_request",
        "final_funds_request",
        "authenticate_callback",
        "login_callback",
        "baseline_orders_callback",
        "baseline_positions_callback",
        "baseline_funds_callback",
        "final_orders_callback",
        "final_positions_callback",
        "final_funds_callback",
        "client_start_native_module_check",
        "client_start_generation_reserve",
        "client_start_identity_validate",
        "client_start_identity_compare",
        "client_start_flow_prepare",
    }
)
_DIAGNOSTIC_INTENT_EVENTS = frozenset(
    {"begin", "end", "failed", "callback_first", "callback_terminal"}
)
_DIAGNOSTIC_INTENT_ERRORS = frozenset(
    {
        "intent_stream_missing",
        "intent_magic_invalid",
        "intent_stream_limit_exceeded",
        "intent_frame_length_truncated",
        "intent_frame_length_invalid",
        "intent_frame_too_large",
        "intent_frame_truncated",
        "intent_record_limit_exceeded",
        "intent_frame_invalid",
        "intent_frame_noncanonical",
        "intent_sequence_invalid",
        "intent_stage_invalid",
        "intent_event_invalid",
        "intent_frame_misbinding",
        "intent_stream_read_failed",
    }
)
_DIAGNOSTIC_INTENT_KEYS = frozenset(
    {
        "protocol",
        "version",
        "case_id",
        "sequence",
        "stage",
        "event",
        "run_nonce",
        "parent_pid",
        "worker_pid",
        "worker_source_sha256",
        "pair_binding_ref",
    }
)


@dataclass(frozen=True, repr=False)
class C01StageIntent:
    """One parsed local stage observation; it has no receipt or eligibility role."""

    sequence: int
    stage: str
    event: str
    run_nonce: str = field(repr=False)
    parent_pid: int = field(repr=False)
    worker_pid: int = field(repr=False)
    worker_source_sha256: str = field(repr=False)
    pair_binding_ref: C01PairBindingRef = field(repr=False)

    def __repr__(self) -> str:
        return "C01StageIntent(<local diagnostic stage redacted>)"


@dataclass(frozen=True)
class C01SupervisorResult:
    """Value-free supervisor outcome; the candidate is always BLOCKED."""

    status: str
    reason: str
    worker_receipt: Optional[C01WorkerReceipt]
    process_lifecycle: C01ProcessLifecycleReceipt
    diagnostic_intents: Tuple[C01StageIntent, ...] = ()
    diagnostic_intents_error: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status != "BLOCKED" or self.process_lifecycle.status != "BLOCKED":
            raise ValueError("c01_supervisor_status_must_be_blocked")
        if (
            type(self.diagnostic_intents) is not tuple
            or len(self.diagnostic_intents) > MAX_DIAGNOSTIC_INTENT_RECORDS
            or any(type(item) is not C01StageIntent for item in self.diagnostic_intents)
        ):
            raise ValueError("c01_diagnostic_intents_invalid")
        if (
            self.diagnostic_intents_error is not None
            and self.diagnostic_intents_error not in _DIAGNOSTIC_INTENT_ERRORS
        ):
            raise ValueError("c01_diagnostic_intent_error_invalid")
        if self.reason == "diagnostic_profile_only" and (
            self.worker_receipt is not None or self.diagnostic_intents_error is not None
        ):
            raise ValueError("c01_diagnostic_result_invalid")
        if self.reason == "diagnostic_intent_stream_invalid" and (
            self.worker_receipt is not None or self.diagnostic_intents_error is None
        ):
            raise ValueError("c01_diagnostic_result_invalid")


@dataclass
class _Capture:
    limit: int
    retain: bool
    data: bytearray
    eof: bool = False
    overflow: bool = False
    failed: bool = False
    total_bytes: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def drain(self, stream: BinaryIO) -> None:
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    with self.lock:
                        self.eof = True
                    return
                with self.lock:
                    self.total_bytes += len(chunk)
                    if self.total_bytes > self.limit:
                        self.overflow = True
                    if self.retain and len(self.data) < self.limit:
                        self.data.extend(chunk[: self.limit - len(self.data)])
        except Exception:
            with self.lock:
                self.failed = True
        finally:
            try:
                stream.close()
            except Exception:
                with self.lock:
                    self.failed = True

    def snapshot(self) -> Tuple[bytes, bool, bool, bool, int]:
        with self.lock:
            return (
                bytes(self.data),
                self.eof,
                self.overflow,
                self.failed,
                self.total_bytes,
            )


@dataclass
class _StdioPipes:
    stdin_parent: BinaryIO
    stdout_parent: BinaryIO
    stderr_parent: BinaryIO
    child_fds: Tuple[int, ...]
    child_handles: Tuple[int, int, int]
    child_handles_closed: bool = False
    parent_handles_closed: bool = False

    @property
    def handles_closed(self) -> bool:
        return self.child_handles_closed and self.parent_handles_closed

    def close_child_ends(self) -> bool:
        succeeded = True
        remaining = []
        for fd in self.child_fds:
            try:
                os.close(fd)
            except OSError:
                succeeded = False
                remaining.append(fd)
        self.child_fds = tuple(remaining)
        self.child_handles_closed = succeeded and not remaining
        return succeeded

    def close_parent_ends(self) -> bool:
        succeeded = True
        for stream_name in ("stdin_parent", "stdout_parent", "stderr_parent"):
            stream = getattr(self, stream_name)
            if stream is None:
                continue
            try:
                stream.close()
            except Exception:
                succeeded = False
            setattr(self, stream_name, None)
        self.parent_handles_closed = succeeded
        return succeeded


@dataclass
class _InputWrite:
    stream: BinaryIO
    payload: bytes
    done: threading.Event
    succeeded: bool = False

    def run(self) -> None:
        try:
            view = memoryview(self.payload)
            offset = 0
            while offset < len(view):
                count = self.stream.write(view[offset:])
                if type(count) is not int or count <= 0:
                    return
                offset += count
            self.stream.flush()
            self.succeeded = True
        except Exception:
            self.succeeded = False
        finally:
            try:
                self.stream.close()
            except Exception:
                self.succeeded = False
            self.done.set()


def _blocked_before_start(
    *,
    nonce: str,
    parent_pid: int,
    reason: str,
    containment: str = "not_started",
    handles_closed: bool = True,
    timed_out: bool = False,
) -> C01SupervisorResult:
    lifecycle = C01ProcessLifecycleReceipt(
        run_nonce=nonce,
        parent_pid=parent_pid,
        worker_pid=None,
        worker_source_sha256=None,
        assigned_before_resume=False,
        stdin_fully_sent=False,
        stdout_eof=False,
        stderr_eof=False,
        process_exit_observed=False,
        process_exit_code=None,
        job_active_count=None,
        handles_closed=handles_closed,
        timed_out=timed_out,
        forced_kill=False,
        containment=containment,
        reason=reason,
        status="BLOCKED",
    )
    return C01SupervisorResult("BLOCKED", reason, None, lifecycle)


def _valid_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in _HEX_SHA256 for character in value)
    )


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _canonical_intent_record(record: dict[str, Any]) -> bytes:
    return json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _parse_diagnostic_intents(
    raw: bytes,
    *,
    request: C01LaunchRequest,
    worker_pid: Optional[int],
    worker_sha256: str,
    total_bytes: int,
    eof: bool,
    read_failed: bool,
) -> Tuple[Tuple[C01StageIntent, ...], Optional[str]]:
    """Parse a bounded diagnostic prefix; it can never create a receipt."""

    intents: list[C01StageIntent] = []
    stream_overflow = False

    def fail(code: str) -> Tuple[Tuple[C01StageIntent, ...], str]:
        return tuple(intents), "intent_stream_limit_exceeded" if stream_overflow else code

    if type(raw) is not bytes or type(total_bytes) is not int or total_bytes < len(raw):
        return fail("intent_stream_read_failed")
    if total_bytes > MAX_DIAGNOSTIC_STDERR_BYTES or len(raw) > MAX_DIAGNOSTIC_STDERR_BYTES:
        stream_overflow = True
        raw = raw[:MAX_DIAGNOSTIC_STDERR_BYTES]
    else:
        stream_overflow = False
    if not raw:
        return fail(
            "intent_stream_read_failed" if read_failed or not eof else "intent_stream_missing"
        )
    if not raw.startswith(_DIAGNOSTIC_INTENT_MAGIC):
        return fail("intent_magic_invalid")

    expected_pair = request.pair_binding.to_receipt_ref().to_dict()
    offset = len(_DIAGNOSTIC_INTENT_MAGIC)
    while offset < len(raw):
        remaining = len(raw) - offset
        if remaining < 2:
            return fail(
                "intent_stream_limit_exceeded"
                if stream_overflow
                else "intent_frame_length_truncated"
            )
        payload_size = int.from_bytes(raw[offset : offset + 2], "big")
        frame_size = 2 + payload_size
        if payload_size <= 0:
            return fail("intent_frame_length_invalid")
        if frame_size > MAX_DIAGNOSTIC_INTENT_FRAME_BYTES:
            return fail("intent_frame_too_large")
        if remaining < frame_size:
            return fail(
                "intent_stream_limit_exceeded" if stream_overflow else "intent_frame_truncated"
            )
        if len(intents) >= MAX_DIAGNOSTIC_INTENT_RECORDS:
            return fail("intent_record_limit_exceeded")
        payload = raw[offset + 2 : offset + frame_size]
        try:
            record = json.loads(
                payload.decode("ascii"),
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("json_constant")),
            )
        except Exception:
            return fail("intent_frame_invalid")
        if type(record) is not dict or frozenset(record) != _DIAGNOSTIC_INTENT_KEYS:
            return fail("intent_frame_invalid")
        try:
            if _canonical_intent_record(record) != payload:
                return fail("intent_frame_noncanonical")
        except Exception:
            return fail("intent_frame_invalid")
        if type(record["sequence"]) is not int or record["sequence"] != len(intents) + 1:
            return fail("intent_sequence_invalid")
        if type(record["stage"]) is not str or record["stage"] not in _DIAGNOSTIC_INTENT_STAGES:
            return fail("intent_stage_invalid")
        if type(record["event"]) is not str or record["event"] not in _DIAGNOSTIC_INTENT_EVENTS:
            return fail("intent_event_invalid")
        pair_ref = record["pair_binding_ref"]
        if (
            record["protocol"] != _DIAGNOSTIC_INTENT_PROTOCOL
            or type(record["version"]) is not int
            or record["version"] != _DIAGNOSTIC_INTENT_VERSION
            or record["case_id"] != "C01"
            or type(record["run_nonce"]) is not str
            or record["run_nonce"] != request.run_nonce
            or type(record["parent_pid"]) is not int
            or record["parent_pid"] != request.parent_pid
            or type(record["worker_pid"]) is not int
            or worker_pid is None
            or record["worker_pid"] != worker_pid
            or type(record["worker_source_sha256"]) is not str
            or record["worker_source_sha256"] != worker_sha256
            or type(pair_ref) is not dict
            or frozenset(pair_ref) != frozenset(expected_pair)
            or type(pair_ref.get("selected_index")) is not int
            or any(
                type(pair_ref.get(key)) is not str
                for key in (
                    "selection_sha256",
                    "md_front_sha256",
                    "td_front_sha256",
                    "selected_at_utc",
                )
            )
            or pair_ref != expected_pair
        ):
            return fail("intent_frame_misbinding")
        intents.append(
            C01StageIntent(
                sequence=record["sequence"],
                stage=record["stage"],
                event=record["event"],
                run_nonce=record["run_nonce"],
                parent_pid=record["parent_pid"],
                worker_pid=record["worker_pid"],
                worker_source_sha256=record["worker_source_sha256"],
                pair_binding_ref=request.pair_binding.to_receipt_ref(),
            )
        )
        offset += frame_size

    if stream_overflow:
        return fail("intent_stream_limit_exceeded")
    if read_failed or not eof:
        return fail("intent_stream_read_failed")
    return tuple(intents), None


def _resolve_worker(worker_path: object, source_root: object) -> Tuple[Path, Path]:
    if not isinstance(worker_path, (str, os.PathLike)) or not isinstance(
        source_root, (str, os.PathLike)
    ):
        raise ValueError("worker_path_invalid")
    raw_worker = Path(worker_path)
    raw_root = Path(source_root)
    if not raw_worker.is_absolute() or not raw_root.is_absolute():
        raise ValueError("worker_paths_must_be_absolute")
    if raw_worker.is_symlink():
        raise ValueError("worker_path_symlink_rejected")
    root = raw_root.resolve(strict=True)
    worker = raw_worker.resolve(strict=True)
    if not root.is_dir() or not worker.is_file():
        raise ValueError("worker_source_missing")
    try:
        worker.relative_to(root)
    except ValueError:
        raise ValueError("worker_path_outside_source_root") from None
    if worker.stat().st_size > MAX_WORKER_SOURCE_BYTES:
        raise ValueError("worker_source_too_large")
    return worker, root


def _read_pinned_source(worker: Path, expected_sha256: str) -> bytes:
    with worker.open("rb") as stream:
        source = stream.read(MAX_WORKER_SOURCE_BYTES + 1)
    if len(source) > MAX_WORKER_SOURCE_BYTES:
        raise ValueError("worker_source_too_large")
    if hashlib.sha256(source).hexdigest() != expected_sha256:
        raise ValueError("worker_source_hash_mismatch")
    return source


def _bootstrap_code(
    worker_path: Path, expected_sha256: str, *, diagnostic_intents: bool = False
) -> str:
    """Hash and execute the same worker bytes from memory after Job resume."""

    if type(diagnostic_intents) is not bool:
        raise ValueError("diagnostic_profile_invalid")
    path_literal = repr(str(worker_path))
    digest_literal = repr(expected_sha256)
    diagnostic_literal = "True" if diagnostic_intents else "False"
    size_limit = MAX_WORKER_SOURCE_BYTES
    return (
        "import hashlib as _h\n"
        "import sys as _s\n"
        "import types as _t\n"
        "_p = " + path_literal + "\n"
        "_expected = " + digest_literal + "\n"
        "with open(_p, 'rb') as _f:\n"
        "    _source = _f.read(" + str(size_limit + 1) + ")\n"
        "if len(_source) > "
        + str(size_limit)
        + " or _h.sha256(_source).hexdigest() != _expected:\n"
        "    raise SystemExit(73)\n"
        "_m = _t.ModuleType('__main__')\n"
        "_m.__file__ = _p\n"
        "_m.__package__ = None\n"
        "_m.__loader__ = None\n"
        "_m.__spec__ = None\n"
        "_m.__cached__ = None\n"
        "_m.__c01_verified_worker_source_sha256__ = _expected\n"
        "_m.__c01_progress_intents_enabled__ = " + diagnostic_literal + "\n"
        "_s.modules['__main__'] = _m\n"
        "_g = _m.__dict__\n"
        "exec(compile(_source, _p, 'exec'), _g, _g)\n"
    )


def _minimal_environment() -> dict[str, str]:
    values = {key.upper(): value for key, value in os.environ.items()}
    system_root = values.get("SYSTEMROOT")
    windows_dir = values.get("WINDIR")
    if not system_root or not windows_dir:
        raise ValueError("windows_environment_unavailable")
    return {"SYSTEMROOT": system_root, "WINDIR": windows_dir}


def _create_stdio_pipes() -> _StdioPipes:
    if os.name != "nt":
        raise OSError("windows_required")
    import msvcrt

    owned_fds: set[int] = set()
    parent_streams: list[BinaryIO] = []
    try:
        stdin_read, stdin_write = os.pipe()
        owned_fds.update((stdin_read, stdin_write))
        stdout_read, stdout_write = os.pipe()
        owned_fds.update((stdout_read, stdout_write))
        stderr_read, stderr_write = os.pipe()
        owned_fds.update((stderr_read, stderr_write))

        child_fds = (stdin_read, stdout_write, stderr_write)
        parent_fds = (stdin_write, stdout_read, stderr_read)
        child_handles = tuple(msvcrt.get_osfhandle(fd) for fd in child_fds)
        for fd in child_fds:
            os.set_handle_inheritable(msvcrt.get_osfhandle(fd), True)
        for fd in parent_fds:
            os.set_handle_inheritable(msvcrt.get_osfhandle(fd), False)

        stdin_parent = os.fdopen(stdin_write, "wb", buffering=0)
        parent_streams.append(stdin_parent)
        owned_fds.discard(stdin_write)
        stdout_parent = os.fdopen(stdout_read, "rb", buffering=0)
        parent_streams.append(stdout_parent)
        owned_fds.discard(stdout_read)
        stderr_parent = os.fdopen(stderr_read, "rb", buffering=0)
        parent_streams.append(stderr_parent)
        owned_fds.discard(stderr_read)
        return _StdioPipes(
            stdin_parent=stdin_parent,
            stdout_parent=stdout_parent,
            stderr_parent=stderr_parent,
            child_fds=child_fds,
            child_handles=child_handles,
        )
    except Exception:
        for stream in parent_streams:
            try:
                stream.close()
            except Exception:
                pass
        for fd in owned_fds:
            try:
                os.close(fd)
            except OSError:
                pass
        raise


def _backend_for_handles(handles: Tuple[int, int, int]) -> Any:
    from scripts.ctp_i13_i15_windows_job_backend import WindowsJobBackend

    return WindowsJobBackend(
        inherited_stdin_handle=handles[0],
        inherited_stdout_handle=handles[1],
        inherited_stderr_handle=handles[2],
    )


def _worker_pid(session: Any) -> Optional[int]:
    process_handle = getattr(session, "_process_handle", None)
    kernel32 = getattr(session, "_kernel32", None)
    getter = getattr(kernel32, "GetProcessId", None)
    if process_handle is None or getter is None:
        return None
    try:
        getter.argtypes = [wintypes.HANDLE]
        getter.restype = wintypes.DWORD
        value = int(getter(process_handle))
    except Exception:
        return None
    return value if value > 0 else None


def _verified_interpreter_path() -> Optional[Path]:
    try:
        if interpreter_binding.verify_current_runtime() is not True:
            return None
        path = Path(interpreter_binding.CPYTHON_EXECUTABLE)
        if not path.is_absolute() or not path.is_file():
            return None
        return path
    except Exception:
        return None


def _job_active_count(session: Any) -> Optional[int]:
    job_handle = getattr(session, "_job_handle", None)
    kernel32 = getattr(session, "_kernel32", None)
    if job_handle is None or kernel32 is None:
        return None
    try:
        from scripts.ctp_i13_i15_windows_job_backend import _query_job_active_processes

        return _query_job_active_processes(kernel32, job_handle)
    except Exception:
        return None


def _process_exit_code(session: Any) -> Tuple[bool, Optional[int]]:
    try:
        value = session.poll_launcher_exit_code()
    except Exception:
        return False, None
    return value is not None, value


def _start_capture(capture: _Capture, stream: BinaryIO, name: str) -> threading.Thread:
    thread = threading.Thread(target=capture.drain, args=(stream,), name=name, daemon=True)
    thread.start()
    return thread


def _lifecycle(
    *,
    nonce: str,
    parent_pid: int,
    worker_pid: Optional[int],
    worker_sha256: Optional[str],
    assigned: bool,
    stdin_sent: bool,
    stdout_eof: bool,
    stderr_eof: bool,
    process_exit_observed: bool,
    process_exit_code: Optional[int],
    job_active_count: Optional[int],
    handles_closed: bool,
    timed_out: bool,
    forced_kill: bool,
    containment: str,
    reason: str,
) -> C01ProcessLifecycleReceipt:
    return C01ProcessLifecycleReceipt(
        run_nonce=nonce,
        parent_pid=parent_pid,
        worker_pid=worker_pid,
        worker_source_sha256=worker_sha256,
        assigned_before_resume=assigned,
        stdin_fully_sent=stdin_sent,
        stdout_eof=stdout_eof,
        stderr_eof=stderr_eof,
        process_exit_observed=process_exit_observed,
        process_exit_code=process_exit_code,
        job_active_count=job_active_count,
        handles_closed=handles_closed,
        timed_out=timed_out,
        forced_kill=forced_kill,
        containment=containment,
        reason=reason,
        status="BLOCKED",
    )


def _safe_release(backend: Any, session: Any) -> bool:
    try:
        released = session.release_controls() is True
    except Exception:
        released = False
    if not released:
        try:
            backend.retain_controls(session)
        except Exception:
            pass
    return released


def _worker_frame_matches(
    receipt: C01WorkerReceipt,
    *,
    request: C01LaunchRequest,
    worker_pid: int,
    worker_sha256: str,
) -> bool:
    try:
        expected_pair = request.pair_binding.to_receipt_ref()
        return (
            receipt.run_nonce == request.run_nonce
            and receipt.parent_pid == request.parent_pid
            and receipt.worker_pid == worker_pid
            and receipt.worker_source_sha256 == worker_sha256
            # The launch request may contain the private raw TD endpoint. The
            # worker receipt is deliberately hash-only.
            and receipt.pair_binding == expected_pair
            and receipt.account_scope_sha256 == request.account_scope_sha256
            and receipt.credential_binding_sha256 == request.credential_binding_sha256
        )
    except Exception:
        return False


def run_fixed_c01_worker(
    *,
    worker_path: Union[str, os.PathLike],
    source_root: Union[str, os.PathLike],
    expected_worker_source_sha256: str,
    pair_binding: C01PairBinding,
    account_scope_sha256: str,
    credential_binding_sha256: str,
    credential_packet: bytes,
    timeout_seconds: float = MAX_RUNTIME_SECONDS,
    cleanup_seconds: float = MAX_CLEANUP_SECONDS,
    diagnostic_intents: bool = False,
) -> C01SupervisorResult:
    """Run one exact C01 worker under a bounded Windows Job.

    The request, including opaque credential bytes, is encoded as one bounded
    JSON line and written only to the child's inherited stdin. The child is
    created suspended in a private non-admin Job with kill-on-close and is not
    resumed until Job assignment and the worker source digest are observed.
    This function reports process evidence only; its public result is always
    ``BLOCKED``.
    """

    nonce = secrets.token_hex(16)
    parent_pid = os.getpid()
    if type(diagnostic_intents) is not bool:
        return _blocked_before_start(
            nonce=nonce,
            parent_pid=parent_pid,
            reason="diagnostic_profile_invalid",
        )
    if (
        type(timeout_seconds) not in (int, float)
        or not math.isfinite(float(timeout_seconds))
        or not 0.01 <= float(timeout_seconds) <= MAX_RUNTIME_SECONDS
    ):
        return _blocked_before_start(
            nonce=nonce,
            parent_pid=parent_pid,
            reason="runtime_bound_invalid",
        )
    if (
        type(cleanup_seconds) not in (int, float)
        or not math.isfinite(float(cleanup_seconds))
        or not 0.01 <= float(cleanup_seconds) <= MAX_CLEANUP_SECONDS
    ):
        return _blocked_before_start(
            nonce=nonce,
            parent_pid=parent_pid,
            reason="cleanup_bound_invalid",
        )
    deadline = time.monotonic() + float(timeout_seconds)
    if not _valid_sha256(expected_worker_source_sha256):
        return _blocked_before_start(
            nonce=nonce,
            parent_pid=parent_pid,
            reason="worker_pin_invalid",
        )
    if not _valid_sha256(account_scope_sha256) or not _valid_sha256(credential_binding_sha256):
        return _blocked_before_start(
            nonce=nonce,
            parent_pid=parent_pid,
            reason="account_binding_invalid",
        )
    if os.name != "nt":
        return _blocked_before_start(
            nonce=nonce,
            parent_pid=parent_pid,
            reason="windows_required",
            containment="unavailable",
        )
    interpreter = _verified_interpreter_path()
    if interpreter is None:
        return _blocked_before_start(
            nonce=nonce,
            parent_pid=parent_pid,
            reason="approved_interpreter_binding_required",
            containment="unavailable",
            timed_out=time.monotonic() >= deadline,
        )

    try:
        worker, root = _resolve_worker(worker_path, source_root)
        source = _read_pinned_source(worker, expected_worker_source_sha256)
    except Exception as error:
        reason = str(error) if type(error) is ValueError else "worker_source_unavailable"
        if (
            not reason
            or len(reason) > 96
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_:-" for character in reason
            )
        ):
            reason = "worker_source_unavailable"
        return _blocked_before_start(
            nonce=nonce,
            parent_pid=parent_pid,
            reason=reason,
            timed_out=time.monotonic() >= deadline,
        )
    # Retain only the digest after the preflight read; source is reread by the
    # child bootstrap and the exact bytes it hashes are the bytes it executes.
    del source
    try:
        environment = _minimal_environment()
        request = C01LaunchRequest(
            run_nonce=nonce,
            parent_pid=parent_pid,
            expected_worker_source_sha256=expected_worker_source_sha256,
            pair_binding=pair_binding,
            account_scope_sha256=account_scope_sha256,
            credential_binding_sha256=credential_binding_sha256,
            credential_packet=credential_packet,
        )
        launch_frame = encode_launch_frame(request)
        if len(launch_frame) > MAX_LAUNCH_FRAME_BYTES:
            raise ValueError("launch_frame_too_large")
    except Exception:
        return _blocked_before_start(
            nonce=nonce,
            parent_pid=parent_pid,
            reason="launch_packet_invalid",
            timed_out=time.monotonic() >= deadline,
        )

    pipes: Optional[_StdioPipes] = None
    try:
        bootstrap = _bootstrap_code(
            worker,
            expected_worker_source_sha256,
            diagnostic_intents=diagnostic_intents,
        )
        if len(bootstrap) > 8192:
            raise ValueError("worker_bootstrap_too_large")
        pipes = _create_stdio_pipes()
        backend = _backend_for_handles(pipes.child_handles)
    except Exception:
        handles_closed = True
        if pipes is not None:
            pipes.close_child_ends()
            pipes.close_parent_ends()
            handles_closed = pipes.handles_closed
        return _blocked_before_start(
            nonce=nonce,
            parent_pid=parent_pid,
            reason="worker_setup_failed",
            containment="unavailable",
            handles_closed=handles_closed,
            timed_out=time.monotonic() >= deadline,
        )
    if time.monotonic() >= deadline:
        pipes.close_child_ends()
        pipes.close_parent_ends()
        return _blocked_before_start(
            nonce=nonce,
            parent_pid=parent_pid,
            reason="runtime_deadline_exceeded",
            containment="not_started",
            handles_closed=pipes.handles_closed,
            timed_out=True,
        )
    command = type(
        "_FixedWorkerCommand",
        (),
        {
            "argv": (
                str(interpreter),
                "-I",
                "-S",
                "-B",
                "-c",
                bootstrap,
            ),
            "cwd": str(root),
            "env": environment,
        },
    )()
    session: Any = None
    stdout_capture = _Capture(MAX_WORKER_FRAME_BYTES, True, bytearray())
    stderr_capture = _Capture(
        MAX_DIAGNOSTIC_STDERR_BYTES if diagnostic_intents else MAX_STDERR_BYTES,
        diagnostic_intents,
        bytearray(),
    )
    stdout_thread: Optional[threading.Thread] = None
    stderr_thread: Optional[threading.Thread] = None
    writer = _InputWrite(pipes.stdin_parent, launch_frame, threading.Event())
    writer_thread: Optional[threading.Thread] = None
    assigned = False
    process_created = False
    worker_pid: Optional[int] = None
    worker_sha256: Optional[str] = expected_worker_source_sha256
    source_recheck_observed = False
    process_exit_observed = False
    process_exit_code: Optional[int] = None
    job_active_count: Optional[int] = None
    stdout_eof = False
    stderr_eof = False
    stdin_sent = False
    timed_out = False
    forced_kill = False
    termination_requested = False
    resumed = False
    reason = "worker_setup_failed"
    handles_closed = False
    released = False
    parse_receipt: Optional[C01WorkerReceipt] = None
    diagnostic_records: Tuple[C01StageIntent, ...] = ()
    diagnostic_error: Optional[str] = None
    process_error = False

    try:
        try:
            session = backend.create_suspended_in_job(command, deadline_monotonic=deadline)
            process_created = bool(getattr(session, "process_created", False))
        except Exception:
            reason = "worker_job_create_failed"
            return _blocked_before_start(
                nonce=nonce,
                parent_pid=parent_pid,
                reason=reason,
                containment="windows_job",
                handles_closed=False,
            )

        if not pipes.close_child_ends():
            reason = "worker_pipe_setup_failed"
            process_error = True
        assigned = process_created and getattr(session, "job_assignment_observed", None) is True
        worker_pid = _worker_pid(session) if assigned else None
        try:
            # Recheck while the process remains suspended. The child bootstrap
            # performs the same check again and executes those same bytes.
            _read_pinned_source(worker, expected_worker_source_sha256)
            source_recheck_observed = True
        except Exception:
            reason = "worker_source_changed_before_resume"
            process_error = True
        if not process_created:
            reason = "worker_process_creation_unobserved"
            process_error = True
        elif not assigned:
            reason = "job_assignment_unobserved"
            process_error = True
        if assigned and worker_pid is None:
            reason = "worker_pid_unavailable"
            process_error = True
        if time.monotonic() >= deadline:
            timed_out = True
            reason = "native_close_unknown"
            process_error = True

        stdout_thread = _start_capture(stdout_capture, pipes.stdout_parent, "c01-stdout-drain")
        stderr_thread = _start_capture(stderr_capture, pipes.stderr_parent, "c01-stderr-drain")
        if not process_error:
            try:
                assigned = session.job_assignment_observed is True
                resumed = assigned and session.resume_launcher() is True
            except Exception:
                resumed = False
            if not resumed:
                reason = "worker_resume_failed"
                process_error = True
        else:
            resumed = False

        if not resumed:
            # An unassigned or unresumed process must never reach worker code.
            # If assignment is unknown, request both Job termination and
            # direct termination of the still-suspended launcher process.
            termination_requested = True
            try:
                job_result = session.terminate_job()
            except Exception:
                job_result = None
            process_result = None
            if not assigned:
                try:
                    process_result = session.terminate_launcher_process()
                except Exception:
                    process_result = None
            forced_kill = job_result is True or process_result is True

        if resumed:
            writer_thread = threading.Thread(
                target=writer.run, name="c01-stdin-writer", daemon=True
            )
            writer_thread.start()
            reason = "worker_running"
            while True:
                (
                    _stdout,
                    stdout_eof,
                    stdout_overflow,
                    stdout_failed,
                    _stdout_total,
                ) = stdout_capture.snapshot()
                (
                    _stderr,
                    stderr_eof,
                    stderr_overflow,
                    stderr_failed,
                    _stderr_total,
                ) = stderr_capture.snapshot()
                process_exit_observed, process_exit_code = _process_exit_code(session)
                job_active_count = _job_active_count(session)
                if stdout_overflow or stderr_overflow:
                    reason = "worker_output_limit_exceeded"
                    process_error = True
                    termination_requested = True
                    break
                if stdout_failed or stderr_failed:
                    reason = "worker_output_read_failed"
                    process_error = True
                    termination_requested = True
                    break
                if writer.done.is_set() and not writer.succeeded:
                    reason = "worker_stdin_write_failed"
                    process_error = True
                    termination_requested = True
                    break
                if job_active_count is None:
                    reason = "worker_job_accounting_unknown"
                    process_error = True
                    termination_requested = True
                    break
                if (
                    process_exit_observed
                    and process_exit_code == 0
                    and job_active_count == 0
                    and stdout_eof
                    and stderr_eof
                    and writer.done.is_set()
                ):
                    reason = "process_complete"
                    break
                if process_exit_observed and process_exit_code != 0:
                    reason = "worker_exit_nonzero"
                    process_error = True
                    termination_requested = job_active_count != 0
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    reason = "native_close_unknown"
                    process_error = True
                    termination_requested = True
                    break
                time.sleep(min(_POLL_INTERVAL_SECONDS, max(0.0, deadline - time.monotonic())))

        stdin_sent = writer.done.is_set() and writer.succeeded
        cleanup_deadline = min(
            time.monotonic() + float(cleanup_seconds),
            deadline + float(cleanup_seconds),
        )
        if (
            termination_requested
            and session is not None
            and resumed
            and reason == "worker_exit_nonzero"
            and process_exit_observed
            and type(process_exit_code) is int
            and process_exit_code != 0
            and type(job_active_count) is int
            and job_active_count > 0
        ):
            # Give a recently exited worker a short, bounded chance for Job
            # accounting and pipe drains to settle before terminating children.
            # This window is carved from the existing cleanup deadline and
            # reserves at least half of its remaining time for forced cleanup.
            now = time.monotonic()
            remaining_cleanup = max(0.0, cleanup_deadline - now)
            grace_seconds = min(
                MAX_NONZERO_EXIT_JOB_DRAIN_GRACE_SECONDS,
                remaining_cleanup / 2.0,
            )
            grace_deadline = min(cleanup_deadline, now + grace_seconds)
            while time.monotonic() < grace_deadline:
                process_exit_observed, process_exit_code = _process_exit_code(session)
                job_active_count = _job_active_count(session)
                (
                    _stdout,
                    stdout_eof,
                    _stdout_overflow,
                    _stdout_failed,
                    _stdout_total,
                ) = stdout_capture.snapshot()
                (
                    _stderr,
                    stderr_eof,
                    _stderr_overflow,
                    _stderr_failed,
                    _stderr_total,
                ) = stderr_capture.snapshot()
                stdin_sent = writer.done.is_set() and writer.succeeded
                if (
                    process_exit_observed
                    and type(process_exit_code) is int
                    and process_exit_code != 0
                    and type(job_active_count) is int
                    and job_active_count == 0
                    and stdout_eof
                    and not _stdout_overflow
                    and not _stdout_failed
                    and stderr_eof
                    and not _stderr_overflow
                    and not _stderr_failed
                    and writer.done.is_set()
                ):
                    termination_requested = False
                    break
                time.sleep(
                    min(_POLL_INTERVAL_SECONDS, max(0.0, grace_deadline - time.monotonic()))
                )
        if termination_requested and session is not None and resumed:
            try:
                forced_kill = session.terminate_job() is True
            except Exception:
                forced_kill = False
        while session is not None:
            process_exit_observed, process_exit_code = _process_exit_code(session)
            job_active_count = _job_active_count(session)
            (
                _stdout,
                stdout_eof,
                _stdout_overflow,
                _stdout_failed,
                _stdout_total,
            ) = stdout_capture.snapshot()
            (
                _stderr,
                stderr_eof,
                _stderr_overflow,
                _stderr_failed,
                _stderr_total,
            ) = stderr_capture.snapshot()
            stdin_sent = writer.done.is_set() and writer.succeeded
            if (
                process_exit_observed
                and job_active_count == 0
                and stdout_eof
                and stderr_eof
                and (writer.done.is_set() or not resumed)
            ):
                released = _safe_release(backend, session)
                handles_closed = released
                break
            if time.monotonic() >= cleanup_deadline:
                reason = "native_close_unknown"
                process_error = True
                break
            time.sleep(min(_POLL_INTERVAL_SECONDS, max(0.0, cleanup_deadline - time.monotonic())))

        if writer_thread is not None:
            writer_thread.join(timeout=max(0.0, cleanup_deadline - time.monotonic()))
        if stdout_thread is not None:
            stdout_thread.join(timeout=max(0.0, cleanup_deadline - time.monotonic()))
        if stderr_thread is not None:
            stderr_thread.join(timeout=max(0.0, cleanup_deadline - time.monotonic()))
        stdin_sent = writer.done.is_set() and writer.succeeded
        (
            _stdout,
            stdout_eof,
            stdout_overflow,
            stdout_failed,
            _stdout_total,
        ) = stdout_capture.snapshot()
        (
            _stderr,
            stderr_eof,
            stderr_overflow,
            stderr_failed,
            _stderr_total,
        ) = stderr_capture.snapshot()
        if not released and session is not None:
            # Preserve the Job and process controls when the child tree has not
            # been conclusively drained. The backend's process custodian owns
            # this unresolved session until explicit resolution or host exit.
            try:
                backend.retain_controls(session)
            except Exception:
                pass
        pipes.close_parent_ends()
        handles_closed = released and pipes.handles_closed
        if not handles_closed:
            reason = "native_close_unknown"
            process_error = True

        (
            stderr_raw,
            stderr_eof,
            _stderr_overflow,
            stderr_failed,
            stderr_total,
        ) = stderr_capture.snapshot()
        if diagnostic_intents:
            diagnostic_records, diagnostic_error = _parse_diagnostic_intents(
                stderr_raw,
                request=request,
                worker_pid=worker_pid,
                worker_sha256=expected_worker_source_sha256,
                total_bytes=stderr_total,
                eof=stderr_eof,
                read_failed=stderr_failed,
            )
        elif stderr_total > 0 and not process_error:
            reason = "worker_stderr_unexpected"
            process_error = True

        if not process_error and not timed_out and process_exit_code == 0:
            raw, _, _, _, _ = stdout_capture.snapshot()
            try:
                parse_receipt = parse_worker_frame(raw)
            except Exception:
                reason = "worker_frame_invalid"
                process_error = True
            else:
                if worker_pid is None or not _worker_frame_matches(
                    parse_receipt,
                    request=request,
                    worker_pid=worker_pid,
                    worker_sha256=expected_worker_source_sha256,
                ):
                    parse_receipt = None
                    reason = "worker_frame_misbinding"
                    process_error = True
                elif not stdin_sent:
                    parse_receipt = None
                    reason = "worker_stdin_incomplete"
                    process_error = True
                elif diagnostic_intents and diagnostic_error is not None:
                    parse_receipt = None
                    reason = "diagnostic_intent_stream_invalid"
                    process_error = True
                elif diagnostic_intents:
                    # Diagnostic mode validates transport but cannot issue a receipt.
                    parse_receipt = None
                    reason = "diagnostic_profile_only"
                else:
                    reason = "candidate_transport_complete"
        elif timed_out:
            reason = "native_close_unknown"
        elif reason == "worker_running":
            reason = "worker_incomplete"

        lifecycle_reason = (
            "native_close_unknown"
            if not handles_closed or timed_out
            else ("process_complete" if reason == "candidate_transport_complete" else reason)
        )
        lifecycle = _lifecycle(
            nonce=nonce,
            parent_pid=parent_pid,
            worker_pid=worker_pid,
            worker_sha256=worker_sha256 if process_created and source_recheck_observed else None,
            assigned=assigned,
            stdin_sent=stdin_sent,
            stdout_eof=stdout_eof,
            stderr_eof=stderr_eof,
            process_exit_observed=process_exit_observed,
            process_exit_code=process_exit_code,
            job_active_count=job_active_count,
            handles_closed=handles_closed,
            timed_out=timed_out,
            forced_kill=forced_kill,
            containment="windows_job",
            reason=lifecycle_reason,
        )
        return C01SupervisorResult(
            status="BLOCKED",
            reason=reason,
            worker_receipt=parse_receipt,
            process_lifecycle=lifecycle,
            diagnostic_intents=diagnostic_records,
            diagnostic_intents_error=diagnostic_error,
        )
    except Exception:
        # A failure in supervisor bookkeeping must still try to stop the
        # contained process and drain its pipes. Do not return a child receipt
        # from this path, and retain Job controls if any parent observation is
        # still unknown.
        reason = "supervisor_internal_error"
        process_error = True
        timed_out = timed_out or time.monotonic() >= deadline
        cleanup_deadline = min(
            time.monotonic() + float(cleanup_seconds),
            deadline + float(cleanup_seconds),
        )
        pipes.close_child_ends()
        if session is not None:
            if stdout_thread is None:
                try:
                    stdout_thread = _start_capture(
                        stdout_capture, pipes.stdout_parent, "c01-stdout-emergency-drain"
                    )
                except Exception:
                    pass
            if stderr_thread is None:
                try:
                    stderr_thread = _start_capture(
                        stderr_capture, pipes.stderr_parent, "c01-stderr-emergency-drain"
                    )
                except Exception:
                    pass
            if not released:
                try:
                    termination_requested = True
                    forced_kill = session.terminate_job() is True
                except Exception:
                    forced_kill = False
                if not assigned or not resumed:
                    try:
                        direct_termination = session.terminate_launcher_process() is True
                    except Exception:
                        direct_termination = False
                    forced_kill = forced_kill or direct_termination
            while not released and time.monotonic() < cleanup_deadline:
                process_exit_observed, process_exit_code = _process_exit_code(session)
                job_active_count = _job_active_count(session)
                _, stdout_eof, _, _, _ = stdout_capture.snapshot()
                _, stderr_eof, _, _, _ = stderr_capture.snapshot()
                stdin_finished = writer.done.is_set() or writer_thread is None or not resumed
                if (
                    process_exit_observed
                    and job_active_count == 0
                    and stdout_eof
                    and stderr_eof
                    and stdin_finished
                ):
                    released = _safe_release(backend, session)
                    break
                time.sleep(
                    min(_POLL_INTERVAL_SECONDS, max(0.0, cleanup_deadline - time.monotonic()))
                )
            if writer_thread is not None:
                writer_thread.join(timeout=max(0.0, cleanup_deadline - time.monotonic()))
            if stdout_thread is not None:
                stdout_thread.join(timeout=max(0.0, cleanup_deadline - time.monotonic()))
            if stderr_thread is not None:
                stderr_thread.join(timeout=max(0.0, cleanup_deadline - time.monotonic()))
            process_exit_observed, process_exit_code = _process_exit_code(session)
            job_active_count = _job_active_count(session)
            _, stdout_eof, _, _, _ = stdout_capture.snapshot()
            _, stderr_eof, _, _, _ = stderr_capture.snapshot()
            if not released:
                try:
                    backend.retain_controls(session)
                except Exception:
                    pass
        pipes.close_parent_ends()
        if diagnostic_intents:
            (
                stderr_raw,
                stderr_eof,
                _stderr_overflow,
                stderr_failed,
                stderr_total,
            ) = stderr_capture.snapshot()
            try:
                diagnostic_records, diagnostic_error = _parse_diagnostic_intents(
                    stderr_raw,
                    request=request,
                    worker_pid=worker_pid,
                    worker_sha256=expected_worker_source_sha256,
                    total_bytes=stderr_total,
                    eof=stderr_eof,
                    read_failed=stderr_failed,
                )
            except Exception:
                diagnostic_records = ()
                diagnostic_error = "intent_stream_read_failed"
        handles_closed = released and pipes.handles_closed
        lifecycle = _lifecycle(
            nonce=nonce,
            parent_pid=parent_pid,
            worker_pid=worker_pid,
            worker_sha256=worker_sha256 if process_created and source_recheck_observed else None,
            assigned=assigned,
            stdin_sent=writer.done.is_set() and writer.succeeded,
            stdout_eof=stdout_eof,
            stderr_eof=stderr_eof,
            process_exit_observed=process_exit_observed,
            process_exit_code=process_exit_code,
            job_active_count=job_active_count,
            handles_closed=handles_closed,
            timed_out=timed_out,
            forced_kill=forced_kill,
            containment="windows_job",
            reason=(
                "supervisor_internal_error"
                if handles_closed and not timed_out
                else "native_close_unknown"
            ),
        )
        return C01SupervisorResult(
            status="BLOCKED",
            reason=(
                "supervisor_internal_error"
                if handles_closed and not timed_out
                else "native_close_unknown"
            ),
            worker_receipt=None,
            process_lifecycle=lifecycle,
            diagnostic_intents=diagnostic_records,
            diagnostic_intents_error=diagnostic_error,
        )
    finally:
        if pipes.child_fds:
            pipes.close_child_ends()
        if not getattr(pipes, "parent_handles_closed", False):
            pipes.close_parent_ends()


__all__ = [
    "C01SupervisorResult",
    "C01StageIntent",
    "run_fixed_c01_worker",
]
