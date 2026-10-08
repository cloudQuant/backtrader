"""Source-owned fresh C01 UID reader for the fixed M01 V3 route.

This module owns the C01 invocation and its evidence path. It never accepts a
CaptureBundle, receipt DTO, UID, credential packet, subprocess callback, or
provider object from its caller. The only proof it can mint follows a fresh,
fixed, source-pinned C01 root-helper run and independent replay of its private
capture archives. No raw UID, credential, response body, or helper output is
written to the M01 audit directory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import ctypes
from ctypes import wintypes
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import types
from typing import Any, Mapping

from _m01_readonly_monitor_v2 import current_types, job_supervisor, worker


ROOT = Path("D:/source_code/backtrader")
VENUE = ROOT / "examples/000_live_certification/okx_penetration"
ENV_FILE = ROOT / ".env"
ROOT_HELPER = Path("D:/temp/iteration41-okx-c01-root-r13.py")
ROOT_HELPER_SHA256 = "8af889953e9136d8c2c709e6c02aa533dcb6f50bccfd4123b96a347f3fc24550"
PYTHON_EXE = Path(r"C:\anaconda3\python.exe")
PYTHON_DLL = Path(r"C:\anaconda3\python311.dll")
PYTHON_EXE_SHA256 = "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642"
PYTHON_DLL_SHA256 = "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00"
REGISTRY_RELATIVE = "_certification/c01_reviewed_sources.json"
REGISTRY_SHA256 = "e8ef0d44a5f456d696d9c03369b43ddf90a2308bd4acffbd93a3ea613165f562"
BOOTSTRAP_RELATIVE = "_certification/c01_runtime_bootstrap.py"
BOOTSTRAP_SHA256 = "a68d2293c14914cbe7ee8d085dfdc93219a1d3929c392cd561a76a18eec4dc8b"
CASE_RUN_RELATIVE = "cases/C01/run.py"
CASE_RUN_SHA256 = "7829c3f50cebfd1708db2b25339f08bd3edf80303df92b9707dd4b0c913c0955"
PRIVATE_HELPER_RELATIVE = "backtrader_runtime/certification_roundtrip_private.py"
PRIVATE_HELPER_SHA256 = "b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd"
REGISTRY_FILES = {
    "_certification/c01_live_entry.py": "f6ead5932114f0e7729874d83903741f68b492f9383dbef101f5131bc3c959c0",
    "_certification/c01_runtime_bootstrap.py": BOOTSTRAP_SHA256,
    "_certification/c01_signed_rest_v2.py": "68ae91c09a0573477a63e39be71ab2f36cf34d589d21e8ac24c0c0afa813486b",
    "c01_capture.py": "86c437a164a6e628db0479c6f6acb7716d56642f7f1a5b2f5f6abfc9f6ac56f4",
    "c01_http_connect_candidate.py": "b398b5b4426ff212f3a986311b5d3343db3c454b3bb981e25226e94e30923aee",
    "c01_http_framing_candidate.py": "2e2ad7a745c56b26194850291633b0113077080e2c2f58d550f30075c361528b",
    "direct_observation.py": "2d9b5a63d8e6dda1ca46d468cc82aa164909e855c496fc8cd3535ffff5c28ca7",
    "direct_preflight.py": "9bb7abd64253be38cee5eacd7a87b167c735a9b2e54ec6eefeb1c45131b540b0",
}
MAX_ENV_BYTES = 65_536
MAX_ROOT_HELPER_SECONDS = 360.0
MAX_HELPER_OUTPUT_BYTES = 32 * 1024
MAX_C01_ARCHIVE_BYTES = 96 * 1024 * 1024
MAX_C01_BODY_BYTES = 2 * 1024 * 1024
MAX_UID_PROOF_AGE_MS = 30_000
_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x00000001
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_RUN_NAME = re.compile(
    r"iteration41-okx-c01-(?P<role>caller|live)-r13-"
    r"(?P<stamp>[0-9]{8}T[0-9]{6}Z)-(?P<nonce>[0-9a-f]{8})\Z"
)
_UID = re.compile(r"[0-9]{1,32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_ADMISSION_CAPABILITY = object()
_ADMISSIONS: dict[int, "SourceAdmission"] = {}
_CONSUMED_ADMISSIONS: set[int] = set()
_ADMISSION_LOCK = threading.RLock()
_ORPHANED_SOURCE_ADMISSIONS: list[Any] = []
_CURRENT_READ_EVIDENCE: dict[int, tuple[Any, Any]] = {}
_CURRENT_READ_LOCK = threading.RLock()
_CURRENT_READ_CAPABILITY = object()
DEPLOYMENT_DIRECTORY = Path("D:/temp/iteration41-okx-m01-v3-deployment")
ADMISSION_FILE = DEPLOYMENT_DIRECTORY / "deployment.json"
SOURCE_MAP_FILE = DEPLOYMENT_DIRECTORY / "source-map.json"
PROFILE = "OKX_GLOBAL_DEMO_M01_CASE_V3"
SOURCE_REVIEW_REF = "iteration41-okx-m01-source-owned-v3-review-r2"
ADMISSION_SCHEMA = "iteration41.okx.m01.case-deployment.v3"
SOURCE_MAP_SCHEMA = "iteration41.okx.m01.case-source-map.v3"
SOURCE_MAP_RELATIVES = frozenset(
    {
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/__init__.py",
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/current_reader.py",
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/issuer.py",
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/entry.py",
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/__init__.py",
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/current_types.py",
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/job_supervisor.py",
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/worker.py",
        "examples/000_live_certification/okx_penetration/_certification/m01_private_monitor_v2.py",
        "examples/000_live_certification/okx_penetration/_certification/__init__.py",
        "examples/000_live_certification/okx_penetration/_certification/models.py",
        "examples/000_live_certification/okx_penetration/_certification/cases.py",
        "examples/000_live_certification/okx_penetration/_certification/config.py",
        "examples/000_live_certification/okx_penetration/_certification/evidence.py",
        "examples/000_live_certification/okx_penetration/_certification/fixed_owner_routes.py",
        "examples/000_live_certification/okx_penetration/_certification/runner.py",
        "examples/000_live_certification/okx_penetration/cases/M01/M01_strategy.py",
        "examples/000_live_certification/okx_penetration/cases/M01/run.py",
        "backtrader_runtime/certification_roundtrip_private.py",
    }
)


class CurrentReaderError(ValueError):
    """Fixed value-free source reader rejection."""

    def __init__(self, code: str):
        if type(code) is not str or not re.fullmatch(r"[a-z0-9_]{1,64}", code):
            code = "c01_current_read_rejected"
        super().__init__(code)
        self.code = code


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise CurrentReaderError(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("ascii")
    except Exception:
        _require(False, "canonical_json_invalid")
        raise AssertionError from None


def _strict(raw: bytes, limit: int) -> Any:
    _require(type(raw) is bytes and 0 <= len(raw) <= limit, "json_size")

    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate_json_key")
            result[key] = value
        return result

    def constant(_value):
        _require(False, "json_constant")

    try:
        return json.loads(
            raw.decode("utf-8", errors="strict"), object_pairs_hook=pairs, parse_constant=constant
        )
    except CurrentReaderError:
        raise
    except Exception:
        _require(False, "json_invalid")


@dataclass
class _HeldFile:
    path: Path
    handle: int
    raw: bytes = field(repr=False)
    sha256: str
    file_id: str


@dataclass
class _HeldDirectory:
    path: Path
    handle: int
    file_id: str


class _SourceLeaseSet:
    """Exact file handles kept open with FILE_SHARE_READ only."""

    def __init__(self, kernel32: Any, private_api: Any, files: list[Any]):
        self.kernel32, self.private_api = kernel32, private_api
        self.files = files
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        remaining = []
        for item in reversed(tuple(self.files)):
            try:
                if not self.kernel32.CloseHandle(item.handle):
                    remaining.append(item)
            except Exception:
                remaining.append(item)
        self.files = list(reversed(remaining))
        if self.files:
            # Keep leaked handles alive; never claim a clean release.
            job_supervisor._ORPHANED_RUNTIME_HANDLE_SETS.append(
                (self.kernel32, tuple(item.handle for item in self.files))
            )
            raise CurrentReaderError("source_lease_close_uncertain")
        self._closed = True


@dataclass(frozen=True, repr=False, eq=False)
class SourceAdmission:
    """One-use process-local token for a protected V3 source/deployment set."""

    source_map_sha256: str
    private_module: Any = field(repr=False)
    leases: _SourceLeaseSet = field(repr=False)
    _seal: object = field(repr=False, compare=False)

    def __reduce__(self):
        raise TypeError("m01_v3_source_admission_not_serializable")

    def __reduce_ex__(self, _protocol):
        raise TypeError("m01_v3_source_admission_not_serializable")


@dataclass(frozen=True, repr=False, eq=False)
class VerifiedAccountConfigurationRead:
    """One exact signed GET retained from the source-owned C01 proof."""

    invocation: Any = field(repr=False)
    capture_id: str
    request_sha256: str
    response_sha256: str
    request_started_ms: int
    response_received_ms: int
    source_id_sha256: str
    _seal: object = field(repr=False, compare=False)

    def __reduce__(self):
        raise TypeError("m01_v3_rest_capture_not_serializable")

    def __reduce_ex__(self, _protocol):
        raise TypeError("m01_v3_rest_capture_not_serializable")


def verified_account_configuration_read(
    proof: current_types.CurrentReadProof,
    invocation: current_types.M01Invocation,
) -> VerifiedAccountConfigurationRead:
    """Read only the same-call C01 capture selected by the proof factory."""
    if (
        type(proof) is not current_types.CurrentReadProof
        or type(invocation) is not current_types.M01Invocation
    ):
        raise CurrentReaderError("c01_capture_proof_binding")
    with current_types._LOCK:
        if (
            proof.invocation is not invocation
            or current_types._ISSUED.get(id(proof)) is not proof
            or id(proof) not in current_types._CONSUMED
            or proof.source_map_sha256 != invocation.source_map_sha256
        ):
            raise CurrentReaderError("c01_capture_proof_binding")
    with _CURRENT_READ_LOCK:
        stored = _CURRENT_READ_EVIDENCE.get(id(proof))
        if (
            type(stored) is not tuple
            or len(stored) != 2
            or stored[0] is not proof
            or type(stored[1]) is not VerifiedAccountConfigurationRead
            or stored[1]._seal is not _CURRENT_READ_CAPABILITY
        ):
            raise CurrentReaderError("c01_capture_not_factory_issued")
        return stored[1]


def release_current_read_proof(proof: current_types.CurrentReadProof) -> None:
    """Release the proof only after caller has completed replay and audit."""
    if type(proof) is not current_types.CurrentReadProof:
        raise CurrentReaderError("c01_capture_proof_type")
    current_types.release_current_read_proof(proof)
    with _CURRENT_READ_LOCK:
        _CURRENT_READ_EVIDENCE.pop(id(proof), None)


def admit_source() -> SourceAdmission:
    """Verify and hold the exact protected V3 registration before credentials."""
    source_map_raw, private_module, files = _verify_source_admission(None)
    lease_set = None
    try:
        lease_set = _SourceLeaseSet(job_supervisor._winapi(), private_module._api(), files)
        token = SourceAdmission(
            source_map_sha256=_sha(source_map_raw),
            private_module=private_module,
            leases=lease_set,
            _seal=_ADMISSION_CAPABILITY,
        )
        with _ADMISSION_LOCK:
            _ADMISSIONS[id(token)] = token
        return token
    except BaseException:
        if lease_set is None:
            lease_set = _SourceLeaseSet(job_supervisor._winapi(), private_module._api(), files)
        try:
            lease_set.close()
        except BaseException:
            _ORPHANED_SOURCE_ADMISSIONS.append(lease_set)
        raise


def consume_admission(token: SourceAdmission) -> tuple[str, Any, _SourceLeaseSet]:
    if type(token) is not SourceAdmission:
        raise CurrentReaderError("source_admission_type")
    with _ADMISSION_LOCK:
        if (
            token._seal is not _ADMISSION_CAPABILITY
            or _ADMISSIONS.get(id(token)) is not token
            or id(token) in _CONSUMED_ADMISSIONS
        ):
            raise CurrentReaderError("source_admission_invalid")
        _CONSUMED_ADMISSIONS.add(id(token))
    return token.source_map_sha256, token.private_module, token.leases


def release_admission(token: SourceAdmission) -> None:
    if type(token) is not SourceAdmission:
        raise CurrentReaderError("source_admission_type")
    with _ADMISSION_LOCK:
        if token._seal is not _ADMISSION_CAPABILITY or _ADMISSIONS.get(id(token)) is not token:
            raise CurrentReaderError("source_admission_invalid")
    token.leases.close()
    with _ADMISSION_LOCK:
        _ADMISSIONS.pop(id(token), None)
        _CONSUMED_ADMISSIONS.discard(id(token))


def _file_digest_on_handle(kernel32: Any, handle: int, maximum: int) -> bytes:
    size = ctypes.c_longlong()
    if not kernel32.GetFileSizeEx(handle, ctypes.byref(size)) or not 0 <= size.value <= maximum:
        raise CurrentReaderError("source_file_size")
    output = bytearray()
    while len(output) <= maximum:
        buffer = ctypes.create_string_buffer(min(64 * 1024, maximum + 1 - len(output)))
        received = wintypes.DWORD()
        if not kernel32.ReadFile(handle, buffer, len(buffer), ctypes.byref(received), None):
            raise CurrentReaderError("source_file_read")
        if received.value == 0:
            break
        output.extend(buffer.raw[: received.value])
    _require(len(output) <= maximum and len(output) == size.value, "source_file_changed")
    return bytes(output)


def _hold_file(
    kernel32: Any,
    private_api: Any,
    path: Path,
    *,
    maximum: int,
    expected_sha256: str | None,
    private_acl: bool = False,
) -> _HeldFile:
    _require(path.is_absolute() and path.resolve(strict=True) == path, "source_path_identity")
    raw_handle = kernel32.CreateFileW(
        str(path),
        _GENERIC_READ,
        _FILE_SHARE_READ,
        None,
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if raw_handle in (None, 0, _INVALID_HANDLE):
        raise CurrentReaderError("source_file_lease_unavailable")
    handle = int(raw_handle)
    try:
        info = job_supervisor._BY_HANDLE_FILE_INFORMATION()
        _require(
            bool(kernel32.GetFileInformationByHandle(handle, ctypes.byref(info))),
            "source_file_identity",
        )
        _require(
            not (info.dwFileAttributes & job_supervisor._FILE_ATTRIBUTE_REPARSE_POINT),
            "source_reparse",
        )
        _require(info.nNumberOfLinks == 1, "source_hardlink")
        path_buffer = ctypes.create_unicode_buffer(32768)
        path_length = kernel32.GetFinalPathNameByHandleW(handle, path_buffer, len(path_buffer), 0)
        _require(0 < path_length < len(path_buffer), "source_final_path")
        _require(
            job_supervisor._canonical_win32_path(path_buffer.value)
            == job_supervisor._canonical_win32_path(str(path)),
            "source_final_path_mismatch",
        )
        if private_acl:
            sid = private_api.current_sid()
            private_api.verify_acl(handle, sid, directory=False)
        raw = _file_digest_on_handle(kernel32, handle, maximum)
        digest = _sha(raw)
        if expected_sha256 is not None:
            _require(digest == expected_sha256, "source_pin_mismatch")
        file_id = (
            (int(info.dwVolumeSerialNumber) << 64)
            | (int(info.nFileIndexHigh) << 32)
            | int(info.nFileIndexLow)
        )
        _require(file_id > 0, "source_file_id")
        return _HeldFile(path, handle, raw, digest, f"{file_id:032x}")
    except BaseException:
        kernel32.CloseHandle(handle)
        raise


def _load_source_module(name: str, path: Path, raw: bytes) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__cached__ = None
    sys.modules[name] = module
    try:
        exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _open_private_file(path: Path, private_module: Any, maximum: int) -> tuple[bytes, str]:
    """Bounded private read with exact ACL, single-link, and held identity checks."""
    api = private_module._api()
    if os.name != "nt":
        raise CurrentReaderError("windows_private_reader_required")
    path = private_module._path(path)
    parent_context = None
    parent = None
    kernel32 = job_supervisor._winapi()
    handle = kernel32.CreateFileW(
        str(path),
        _GENERIC_READ | private_module._READ_CONTROL | private_module._READ_ATTRIBUTES,
        _FILE_SHARE_READ,
        None,
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle in (None, 0, _INVALID_HANDLE):
        raise CurrentReaderError("private_file_unavailable")
    handle = int(handle)
    try:
        with private_module._ancestors(path):
            parent_context = api.opened(path.parent, directory=True)
            parent = parent_context.__enter__()
            parent_before = api.info(parent, directory=True)
            sid = api.current_sid()
            api.verify_acl(parent, sid, directory=True)
            before = api.info(handle, directory=False)
            api.verify_acl(handle, sid)
            path_buffer = ctypes.create_unicode_buffer(32768)
            path_length = kernel32.GetFinalPathNameByHandleW(
                handle, path_buffer, len(path_buffer), 0
            )
            _require(0 < path_length < len(path_buffer), "private_file_final_path")
            _require(
                job_supervisor._canonical_win32_path(path_buffer.value)
                == job_supervisor._canonical_win32_path(str(path)),
                "private_file_final_path_mismatch",
            )
            raw = _file_digest_on_handle(kernel32, handle, maximum)
            after = api.info(handle, directory=False)
            parent_after = api.info(parent, directory=True)
            _require(
                before == after and parent_before == parent_after, "private_file_identity_changed"
            )
            return raw, f"{before[0]:08x}{before[1]:016x}"
    finally:
        try:
            if parent_context is not None:
                parent_context.__exit__(None, None, None)
        finally:
            if not kernel32.CloseHandle(handle):
                raise CurrentReaderError("private_file_close_uncertain")


def _hold_private_directory(path: Path, private_module: Any) -> _HeldDirectory:
    """Hold the deployment directory against rename/delete and verify owner DACL."""
    if os.name != "nt":
        raise CurrentReaderError("windows_private_reader_required")
    path = private_module._path(path)
    api = private_module._api()
    kernel32 = job_supervisor._winapi()
    handle = api.CreateFileW(
        str(path),
        private_module._READ_ATTRIBUTES | private_module._READ_CONTROL,
        _FILE_SHARE_READ,
        None,
        3,
        0x02200000,
        None,
    )
    if handle in (None, 0, _INVALID_HANDLE):
        raise CurrentReaderError("deployment_directory_unavailable")
    handle = int(handle)
    try:
        identity = api.info(handle, directory=True)
        api.verify_acl(handle, api.current_sid(), directory=True)
        path_buffer = ctypes.create_unicode_buffer(32768)
        path_length = kernel32.GetFinalPathNameByHandleW(handle, path_buffer, len(path_buffer), 0)
        _require(0 < path_length < len(path_buffer), "deployment_directory_final_path")
        _require(
            job_supervisor._canonical_win32_path(path_buffer.value)
            == job_supervisor._canonical_win32_path(str(path)),
            "deployment_directory_path_mismatch",
        )
        volume, index = identity
        return _HeldDirectory(path, handle, f"{volume:08x}{index:016x}")
    except BaseException:
        if not api.CloseHandle(handle):
            job_supervisor._ORPHANED_RUNTIME_HANDLE_SETS.append((api, (handle,)))
        raise


def _open_private_json(path: Path, private_module: Any, maximum: int) -> tuple[bytes, Any, str]:
    raw, file_id = _open_private_file(path, private_module, maximum)
    return raw, _strict(raw, maximum), file_id


def _path_under_temp(value: Any, prefix: str) -> Path:
    _require(type(value) is str and len(value) <= 512, "root_path_shape")
    path = Path(value)
    _require(path.is_absolute() and path.parent == Path("D:/temp"), "root_path_scope")
    _require(path.name.startswith(prefix) and _RUN_NAME.fullmatch(path.name), "root_path_nonce")
    _require(path.resolve(strict=True) == path, "root_path_identity")
    return path


def _validate_root_summary(
    stdout: bytes, stderr: bytes, exit_code: int | None, *, started_ms: int, finished_ms: int
) -> dict[str, Any]:
    _require(type(exit_code) is int and exit_code == 0, "root_helper_exit")
    _require(type(stderr) is bytes and not stderr, "root_helper_stderr")
    _require(
        type(stdout) is bytes and 0 < len(stdout) <= MAX_HELPER_OUTPUT_BYTES, "root_helper_output"
    )
    _require(stdout.endswith(b"\n") and stdout.count(b"\n") == 1, "root_helper_output_framing")
    value = _strict(stdout[:-1], MAX_HELPER_OUTPUT_BYTES)
    expected = {
        "caller_directory",
        "evidence_directory",
        "exit_code",
        "elapsed_ms",
        "stdout_json",
        "status",
        "operation",
        "orders",
        "cancels",
    }
    _require(
        type(value) is dict
        and set(value) == expected
        and json.dumps(value, allow_nan=False).encode("utf-8") + b"\n" == stdout,
        "root_helper_fields",
    )
    _require(
        type(value["status"]) is str
        and value["status"] == "PASS"
        and value["operation"] == "C01_SIGNED_REST_V2_READ_ONLY",
        "root_helper_status",
    )
    _require(
        type(value["exit_code"]) is int
        and value["exit_code"] == 0
        and value["stdout_json"] is True
        and type(value["orders"]) is int
        and value["orders"] == 0
        and type(value["cancels"]) is int
        and value["cancels"] == 0,
        "root_helper_result",
    )
    _require(
        type(value["elapsed_ms"]) is int
        and 0 <= value["elapsed_ms"] <= MAX_ROOT_HELPER_SECONDS * 1000,
        "root_helper_elapsed",
    )
    _require(finished_ms >= started_ms, "root_helper_time")
    caller = _path_under_temp(value["caller_directory"], "iteration41-okx-c01-caller-r13-")
    evidence = _path_under_temp(value["evidence_directory"], "iteration41-okx-c01-live-r13-")
    _require(caller != evidence, "root_paths_reused")
    caller_match = _RUN_NAME.fullmatch(caller.name)
    evidence_match = _RUN_NAME.fullmatch(evidence.name)
    _require(
        caller_match is not None
        and evidence_match is not None
        and caller_match.group("role") == "caller"
        and evidence_match.group("role") == "live"
        and caller_match.group("stamp") == evidence_match.group("stamp")
        and caller_match.group("nonce") == evidence_match.group("nonce"),
        "root_path_run_binding",
    )
    return {
        "caller": caller,
        "evidence": evidence,
        "summary_sha256": _sha(stdout),
        "elapsed_ms": value["elapsed_ms"],
        "started_at_utc": caller_match.group("stamp"),
    }


def _validate_uid_body(raw_body: str) -> str:
    _require(type(raw_body) is str, "account_body_type")
    body = raw_body.encode("utf-8", errors="strict")
    _require(len(body) <= MAX_C01_BODY_BYTES, "account_body_size")
    value = _strict(body, MAX_C01_BODY_BYTES)
    _require(type(value) is dict and value.get("code") == "0", "account_body_code")
    rows = value.get("data")
    _require(type(rows) is list and len(rows) == 1 and type(rows[0]) is dict, "account_body_rows")
    uid = rows[0].get("uid")
    _require(type(uid) is str and _UID.fullmatch(uid) is not None, "account_uid_shape")
    return uid


def _account_ref(credentials: Mapping[str, str], uid: str) -> str:
    identity = json.dumps(
        [
            "okx-demo-account-key-v1",
            "global",
            "https://openapi.okx.com",
            credentials["OKX_DEMO_API_KEY"],
            uid,
        ],
        separators=(",", ":"),
    ).encode("ascii")
    return hmac.new(
        credentials["OKX_DEMO_SECRET"].encode("ascii"), identity, hashlib.sha256
    ).hexdigest()


def _source_file_map(registry: dict[str, Any]) -> dict[str, str]:
    _require(
        type(registry) is dict
        and set(registry) == {"files", "review_ref", "schema", "status", "venue"},
        "registry_fields",
    )
    _require(
        registry["schema"] == 1 and registry["status"] == "REVIEWED" and registry["venue"] == "okx",
        "registry_not_reviewed",
    )
    _require(registry["files"] == REGISTRY_FILES, "registry_file_map_changed")
    return dict(REGISTRY_FILES)


def _validate_deployment_documents(
    admission_raw: bytes,
    source_map_raw: bytes,
    *,
    invocation_source_map_sha256: str | None = None,
) -> tuple[dict[str, Any], dict[str, str], str]:
    """Validate the fixed deployment decision and exact V3 member set."""
    admission = _strict(admission_raw, 64 * 1024)
    source_map = _strict(source_map_raw, 256 * 1024)
    _require(
        type(admission) is dict
        and set(admission) == {"schema", "status", "profile", "source_map_sha256", "review_ref"},
        "admission_fields",
    )
    _require(admission["schema"] == ADMISSION_SCHEMA, "admission_schema")
    _require(admission["status"] == "ADMITTED_SOURCE_PIN", "candidate_unregistered")
    _require(admission["profile"] == PROFILE, "admission_profile")
    _require(
        admission["review_ref"] == SOURCE_REVIEW_REF,
        "admission_review_ref",
    )
    _require(_canonical(admission) + b"\n" == admission_raw, "admission_canonical")
    _require(
        type(source_map) is dict and set(source_map) == {"schema", "source_pins"},
        "source_map_fields",
    )
    _require(source_map["schema"] == SOURCE_MAP_SCHEMA, "source_map_schema")
    _require(
        type(source_map["source_pins"]) is dict
        and set(source_map["source_pins"]) == SOURCE_MAP_RELATIVES,
        "source_map_members",
    )
    _require(_canonical(source_map) + b"\n" == source_map_raw, "source_map_canonical")
    for relative, pin in source_map["source_pins"].items():
        _require(
            type(relative) is str and type(pin) is str and _HEX64.fullmatch(pin) is not None,
            "source_map_entry",
        )
        candidate = Path(relative)
        _require(
            not candidate.is_absolute()
            and ".." not in candidate.parts
            and ":" not in relative
            and "\\" not in relative,
            "source_map_path",
        )
    map_sha = _sha(source_map_raw)
    _require(admission["source_map_sha256"] == map_sha, "admission_source_map_binding")
    if invocation_source_map_sha256 is not None:
        _require(map_sha == invocation_source_map_sha256, "invocation_source_map_binding")
    return admission, dict(source_map["source_pins"]), map_sha


def _verify_source_admission(
    invocation: current_types.M01Invocation | None,
) -> tuple[bytes, Any, list[Any]]:
    """Verify exact root deployment registration and hold its source closure."""
    _require(
        worker.LIVE_TRANSPORT_ENABLEMENT == "ROOT_FIXED_ISSUER_ADMITTED", "candidate_unregistered"
    )
    private_path = ROOT / PRIVATE_HELPER_RELATIVE
    kernel = job_supervisor._winapi()
    helper_lease = _hold_file(
        kernel, None, private_path, maximum=2 * 1024 * 1024, expected_sha256=PRIVATE_HELPER_SHA256
    )
    leases: list[Any] = [helper_lease]
    private_module = None
    try:
        private_module = _load_source_module(
            "_okx_m01_v3_admission_private", private_path, helper_lease.raw
        )
        private_api = private_module._api()
        deployment_directory = _hold_private_directory(DEPLOYMENT_DIRECTORY, private_module)
        leases.append(deployment_directory)
        admission_lease = _hold_file(
            kernel,
            private_api,
            ADMISSION_FILE,
            maximum=64 * 1024,
            expected_sha256=None,
            private_acl=True,
        )
        leases.append(admission_lease)
        map_lease = _hold_file(
            kernel,
            private_api,
            SOURCE_MAP_FILE,
            maximum=256 * 1024,
            expected_sha256=None,
            private_acl=True,
        )
        leases.append(map_lease)
        _admission, source_pins, _map_sha = _validate_deployment_documents(
            admission_lease.raw,
            map_lease.raw,
            invocation_source_map_sha256=(
                invocation.source_map_sha256 if invocation is not None else None
            ),
        )
        for relative, pin in source_pins.items():
            path = ROOT / relative
            file_lease = _hold_file(
                kernel, private_api, path, maximum=2 * 1024 * 1024, expected_sha256=pin
            )
            _require(file_lease.raw, "source_map_empty_file")
            leases.append(file_lease)
        return map_lease.raw, private_module, leases
    except BaseException:
        failed = []
        for item in reversed(leases):
            try:
                if not kernel.CloseHandle(item.handle):
                    failed.append(item.handle)
            except Exception:
                failed.append(item.handle)
        if failed:
            job_supervisor._ORPHANED_RUNTIME_HANDLE_SETS.append((kernel, tuple(failed)))
        raise


def deployment_source_map_digest() -> str:
    """Return the hash of the admitted protected map after pinning its closure."""
    raw, private_module, leases = _verify_source_admission(None)
    try:
        return _sha(raw)
    finally:
        _SourceLeaseSet(job_supervisor._winapi(), private_module._api(), leases).close()


class C01CurrentReadFactory:
    """Create one exact fresh C01 run and mint its same-call private UID proof."""

    def acquire(self, invocation: current_types.M01Invocation) -> current_types.CurrentReadProof:
        if type(invocation) is not current_types.M01Invocation:
            raise CurrentReaderError("invocation_type")
        _require(os.name == "nt", "windows_required")
        lease_files: list[Any] = []
        private_module = None
        output_directory = None
        try:
            _source_map_raw, private_module, admission_leases = _verify_source_admission(invocation)
            lease_files.extend(admission_leases)
            kernel = job_supervisor._winapi()
            private_api = private_module._api()

            def hold(relative: str, pin: str, maximum: int = 2 * 1024 * 1024) -> bytes:
                item = _hold_file(
                    kernel,
                    private_api,
                    VENUE / relative,
                    maximum=maximum,
                    expected_sha256=pin,
                )
                lease_files.append(item)
                return item.raw

            registry_raw = hold(REGISTRY_RELATIVE, REGISTRY_SHA256, 64 * 1024)
            registry = _strict(registry_raw, 64 * 1024)
            pins = _source_file_map(registry)
            source_bytes: dict[str, bytes] = {}
            for relative, pin in pins.items():
                source_bytes[relative] = hold(relative, pin)
            hold(CASE_RUN_RELATIVE, CASE_RUN_SHA256)
            bootstrap_raw = hold(BOOTSTRAP_RELATIVE, BOOTSTRAP_SHA256)
            root_helper_file = _hold_file(
                kernel,
                private_api,
                ROOT_HELPER,
                maximum=64 * 1024,
                expected_sha256=ROOT_HELPER_SHA256,
            )
            lease_files.append(root_helper_file)
            # The env is held deny-write/delete and read only in this invocation.
            env_file = _hold_file(
                kernel,
                private_api,
                ENV_FILE,
                maximum=MAX_ENV_BYTES,
                expected_sha256=None,
                private_acl=True,
            )
            lease_files.append(env_file)
            private_module._path(ENV_FILE)
            direct_preflight = _load_source_module(
                f"_okx_m01_v3_preflight_{invocation.nonce}",
                VENUE / "direct_preflight.py",
                source_bytes["direct_preflight.py"],
            )
            credentials = direct_preflight._credentials(ENV_FILE)
            _require(
                type(credentials) is dict
                and set(credentials) == set(direct_preflight.CREDENTIAL_NAMES),
                "credential_names",
            )
            c01_bootstrap = _load_source_module(
                f"_okx_m01_v3_c01_bootstrap_{invocation.nonce}",
                VENUE / BOOTSTRAP_RELATIVE,
                bootstrap_raw,
            )
            environment = c01_bootstrap.clean_environment()
            _require(
                type(environment) is dict
                and all(type(k) is type(v) is str for k, v in environment.items()),
                "clean_environment",
            )
            environment_names = {key.lower() for key in environment}
            forbidden = {
                "pythonpath",
                "pythonhome",
                "sslkeylogfile",
                "ssl_cert_file",
                "ssl_cert_dir",
                "requests_ca_bundle",
                "curl_ca_bundle",
                "https_proxy",
                "http_proxy",
                "all_proxy",
                "okx_demo_api_key",
                "okx_demo_secret",
                "okx_demo_passphrase",
            }
            _require(not (environment_names & forbidden), "ambient_environment_present")
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            run_path = Path(
                f"D:/temp/iteration41-okx-m01-current-read-v3-{stamp}-{invocation.nonce}"
            )
            output_directory = private_module.create_private_directory(run_path)
            output_directory.write_json(
                "invocation.json",
                {
                    "schema": "iteration41.okx.m01.current-read-invocation.v3",
                    "nonce": invocation.nonce,
                    "parent_pid": invocation.parent_pid,
                    "started_ms": invocation.started_ms,
                    "c01_registry_sha256": REGISTRY_SHA256,
                    "c01_root_helper_sha256": ROOT_HELPER_SHA256,
                    "env_snapshot_sha256": env_file.sha256,
                    "env_file_id": env_file.file_id,
                    "source_file_count": len(source_bytes),
                    "case_runner_sha256": CASE_RUN_SHA256,
                },
            )
            helper_started_ms = time.time_ns() // 1_000_000
            helper_started = time.monotonic()
            wrapper = _root_helper_wrapper(root_helper_file.raw)
            stdout, stderr, exit_code, helper_pid, job_facts = _run_pinned_root_helper(
                wrapper, environment, timeout_seconds=MAX_ROOT_HELPER_SECONDS
            )
            helper_finished_ms = time.time_ns() // 1_000_000
            helper_elapsed_ms = int((time.monotonic() - helper_started) * 1000)
            summary = _validate_root_summary(
                stdout,
                stderr,
                exit_code,
                started_ms=helper_started_ms,
                finished_ms=helper_finished_ms,
            )
            _require(
                job_facts["pid"] == helper_pid and job_facts["assigned_before_resume"],
                "root_job_binding",
            )
            _require(
                job_facts["active_count_after_exit"] == 0 and job_facts["normal_exit"],
                "root_job_cleanup",
            )
            proof_facts = _verify_root_c01_artifacts(
                summary=summary,
                private_module=private_module,
                source_bytes=source_bytes,
                registry=registry,
                credentials=credentials,
                helper_pid=helper_pid,
                helper_started_ms=helper_started_ms,
                helper_finished_ms=helper_finished_ms,
                helper_elapsed_ms=helper_elapsed_ms,
                summary_elapsed_ms=summary["elapsed_ms"],
                env_file=env_file,
            )
            capture_facts = proof_facts["latest_account_configuration_capture"]
            _require(
                type(capture_facts) is dict
                and set(capture_facts)
                == {
                    "capture_id",
                    "request_sha256",
                    "response_sha256",
                    "request_started_ms",
                    "response_received_ms",
                    "source_id_sha256",
                }
                and type(capture_facts["capture_id"]) is str
                and 1 <= len(capture_facts["capture_id"]) <= 128
                and type(capture_facts["request_sha256"]) is str
                and _HEX64.fullmatch(capture_facts["request_sha256"])
                and type(capture_facts["response_sha256"]) is str
                and _HEX64.fullmatch(capture_facts["response_sha256"])
                and type(capture_facts["request_started_ms"]) is int
                and type(capture_facts["response_received_ms"]) is int
                and invocation.started_ms
                <= capture_facts["request_started_ms"]
                <= capture_facts["response_received_ms"]
                <= proof_facts["last_capture_finished_ms"]
                and type(capture_facts["source_id_sha256"]) is str
                and _HEX64.fullmatch(capture_facts["source_id_sha256"]),
                "c01_case_operation_capture",
            )
            completed_ms = time.time_ns() // 1_000_000
            _require(
                completed_ms - proof_facts["last_capture_finished_ms"] <= MAX_UID_PROOF_AGE_MS,
                "fresh_uid_stale",
            )
            credential_packet = _canonical(
                {
                    "api_key": credentials["OKX_DEMO_API_KEY"],
                    "expected_rest_uid": proof_facts["uid"],
                    "passphrase": credentials["OKX_DEMO_PASSPHRASE"],
                    "secret_key": credentials["OKX_DEMO_SECRET"],
                }
            )
            parsed_credentials = worker.parse_credentials(credential_packet)
            account_scope = worker.account_scope_sha256(parsed_credentials)
            credential_binding = worker.credential_binding_sha256(parsed_credentials)
            receipt_sha = _sha(
                _canonical(
                    {
                        "schema": "iteration41.okx.m01.c01-current-read-proof.v2",
                        "invocation_nonce": invocation.nonce,
                        "m01_parent_pid": invocation.parent_pid,
                        "source_map_sha256": invocation.source_map_sha256,
                        "c01_registry_sha256": REGISTRY_SHA256,
                        "c01_root_helper_sha256": ROOT_HELPER_SHA256,
                        "c01_root_helper_pid": helper_pid,
                        "c01_root_job_active_count_after_exit": job_facts[
                            "active_count_after_exit"
                        ],
                        "c01_root_job_assigned_before_resume": True,
                        "c01_root_helper_exit_code": exit_code,
                        "c01_root_helper_stdout_sha256": _sha(stdout),
                        "c01_root_helper_stderr_sha256": _sha(stderr),
                        "c01_report_sha256": proof_facts["report_sha256"],
                        "c01_archive_sha256": list(proof_facts["archive_sha256s"]),
                        "m01_operation_capture_id": capture_facts["capture_id"],
                        "m01_operation_request_sha256": capture_facts["request_sha256"],
                        "m01_operation_response_sha256": capture_facts["response_sha256"],
                        "c01_child_pids": list(proof_facts["child_pids"]),
                        "c01_child_nonces": list(proof_facts["child_nonces"]),
                        "c01_uid_sha256": _sha(proof_facts["uid"].encode("ascii")),
                        "account_scope_sha256": account_scope,
                        "credential_binding_sha256": credential_binding,
                        "env_snapshot_sha256": env_file.sha256,
                        "env_file_id": env_file.file_id,
                        "freshness_completed_ms": completed_ms,
                    }
                )
            )
            output_directory.write_json(
                "current-read-proof.json",
                {
                    "schema": "iteration41.okx.m01.c01-current-read-audit.v2",
                    "run_nonce": invocation.nonce,
                    "source_map_sha256": invocation.source_map_sha256,
                    "c01_registry_sha256": REGISTRY_SHA256,
                    "c01_root_helper_sha256": ROOT_HELPER_SHA256,
                    "c01_root_helper_pid": helper_pid,
                    "c01_root_helper_job_active_count_after_exit": job_facts[
                        "active_count_after_exit"
                    ],
                    "c01_report_sha256": proof_facts["report_sha256"],
                    "c01_archive_sha256": list(proof_facts["archive_sha256s"]),
                    "m01_operation_capture_id": capture_facts["capture_id"],
                    "m01_operation_request_sha256": capture_facts["request_sha256"],
                    "m01_operation_response_sha256": capture_facts["response_sha256"],
                    "c01_child_pids": list(proof_facts["child_pids"]),
                    "c01_child_nonces": list(proof_facts["child_nonces"]),
                    "account_scope_sha256": account_scope,
                    "credential_binding_sha256": credential_binding,
                    "uid_sha256": _sha(proof_facts["uid"].encode("ascii")),
                    "provider_requests": proof_facts["request_count"],
                    "provider_order_or_cancel_attempts": 0,
                    "case_passes_added": 0,
                    "status": "FRESH_CURRENT_UID_VERIFIED",
                },
            )
            lease_set = _SourceLeaseSet(kernel, private_api, lease_files)
            lease_files = []
            proof = current_types.mint_current_read_proof(
                invocation=invocation,
                receipt_sha256=receipt_sha,
                account_scope_sha256=account_scope,
                credential_binding_sha256=credential_binding,
                expected_rest_uid=proof_facts["uid"],
                completed_ms=completed_ms,
                credential_packet=credential_packet,
                lease_set=lease_set,
                audit_directory=output_directory,
            )
            read_evidence = VerifiedAccountConfigurationRead(
                invocation=invocation,
                capture_id=capture_facts["capture_id"],
                request_sha256=capture_facts["request_sha256"],
                response_sha256=capture_facts["response_sha256"],
                request_started_ms=capture_facts["request_started_ms"],
                response_received_ms=capture_facts["response_received_ms"],
                source_id_sha256=capture_facts["source_id_sha256"],
                _seal=_CURRENT_READ_CAPABILITY,
            )
            try:
                with _CURRENT_READ_LOCK:
                    _CURRENT_READ_EVIDENCE[id(proof)] = (proof, read_evidence)
            except BaseException:
                current_types.release_current_read_proof(proof)
                raise
            return proof
        except CurrentReaderError:
            raise
        except Exception:
            raise CurrentReaderError("c01_current_read_failed") from None
        finally:
            if lease_files:
                _SourceLeaseSet(
                    kernel, private_module._api() if private_module else None, lease_files
                ).close()


def _root_helper_wrapper(root_helper_bytes: bytes) -> bytes:
    _require(
        type(root_helper_bytes) is bytes and 0 < len(root_helper_bytes) <= 64 * 1024,
        "root_helper_size",
    )
    _require(
        root_helper_bytes.decode("utf-8", errors="strict").startswith(
            "from datetime import datetime, timezone\n"
        ),
        "root_helper_source_shape",
    )
    # The V2 supervisor loader injects the verified payload digest into the
    # execution namespace. The exact pinned helper bytes remain unchanged.
    return (
        b"def _worker_source_sha256():\n"
        b" return __okx_verified_worker_source_sha256__\n" + root_helper_bytes
    )


_ROOT_HELPER_RETAINED_CONTEXTS: list[tuple[Any, ...]] = []

def _wait_for_job_zero(kernel: Any, job: int, *, timeout_seconds: float) -> bool:
    """Poll a held Job until its active process count is zero or time expires."""
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while True:
        try:
            active = job_supervisor._active_count(kernel, job)
        except Exception:
            raise CurrentReaderError("root_helper_job_count_unavailable") from None
        if type(active) is not int:
            raise CurrentReaderError("root_helper_job_count_invalid")
        if active == 0:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.025, remaining))


def _run_pinned_root_helper(
    wrapper: bytes, environment: Mapping[str, str], *, timeout_seconds: float
) -> tuple[bytes, bytes, int | None, int, dict[str, Any]]:
    """Run exact helper bytes and retain uncertain process/Job ownership."""
    _require(type(timeout_seconds) in (int, float) and 1 <= timeout_seconds <= 360, "root_timeout")
    _require(
        type(wrapper) is bytes and 0 < len(wrapper) <= worker.MAX_LAUNCH_FRAME_BYTES,
        "root_wrapper_size",
    )
    setup_deadline = time.monotonic() + 20.0
    deadline = time.monotonic() + float(timeout_seconds)
    kernel = job_supervisor._winapi()
    control = None
    states = [job_supervisor._new_pipe_state(), job_supervisor._new_pipe_state()]
    threads = []
    result = None
    primary_error = None
    cleanup_complete = False

    try:
        control = job_supervisor._create_suspended(
            kernel,
            environment,
            worker_source_sha256=_sha(wrapper),
            worker_source_size=len(wrapper),
            deadline=setup_deadline,
        )
        for name, state, limit in (
            ("stdout", states[0], MAX_HELPER_OUTPUT_BYTES),
            ("stderr", states[1], MAX_HELPER_OUTPUT_BYTES),
        ):
            thread = threading.Thread(
                target=job_supervisor._drain,
                args=(kernel, control[name], state, limit),
                daemon=True,
                name=f"okx-m01-c01-{name}-drain",
            )
            thread.start()
            threads.append(thread)
        job_supervisor._assign_control_to_job(kernel, control, setup_deadline)
        job_supervisor._resume_control(kernel, control, setup_deadline)
        if not job_supervisor._close_handle(kernel, control["handles"], control["thread"]):
            raise CurrentReaderError("root_helper_thread_handle_close")
        control["thread"] = 0
        frame = len(wrapper).to_bytes(4, "big") + wrapper
        if not job_supervisor._write_all(kernel, control["stdin"], frame, setup_deadline):
            raise CurrentReaderError("root_helper_source_write")
        if not job_supervisor._close_handle(kernel, control["handles"], control["stdin"]):
            raise CurrentReaderError("root_helper_stdin_close")
        control["stdin"] = 0

        remaining = max(0, int((deadline - time.monotonic()) * 1000))
        exited = job_supervisor._wait_process(kernel, control["process"], remaining)
        if not exited:
            raise CurrentReaderError("root_helper_timeout")
        control["process_reaped"] = True
        exit_code = job_supervisor._process_exit_code(kernel, control["process"])
        if exit_code is None:
            raise CurrentReaderError("root_helper_exit_code_unavailable")

        # Windows Job accounting can retain the root process while its parent
        # process handle remains open. Release that reference before querying.
        if not job_supervisor._close_handle(kernel, control["handles"], control["process"]):
            raise CurrentReaderError("root_helper_process_handle_close")
        control["process"] = 0

        job_zero = _wait_for_job_zero(kernel, control["job"], timeout_seconds=2.0)
        control["job_zero_confirmed"] = job_zero
        if not job_zero:
            raise CurrentReaderError("root_helper_descendant_active")

        for thread in threads:
            thread.join(timeout=5.0)
        _require(all(not thread.is_alive() for thread in threads), "root_helper_pipe_join")
        for state in states:
            _require(
                state["eof"] and state["done"] and not state["error"] and not state["overflow"],
                "root_helper_pipe_incomplete",
            )
        stdout, stderr = bytes(states[0]["raw"]), bytes(states[1]["raw"])
        control["root_helper_normal_exit"] = True
        result = (
            stdout,
            stderr,
            exit_code,
            int(control["pid"]),
            {
                "pid": int(control["pid"]),
                "assigned_before_resume": bool(control.get("assigned")),
                "active_count_after_exit": 0,
                "normal_exit": exit_code == 0 and exited,
            },
        )
    except BaseException as exc:
        primary_error = exc
        if control is not None:
            try:
                control["termination_succeeded"] = bool(
                    job_supervisor._terminate_control(kernel, control, 0xEE5A)
                )
            except Exception:
                control["termination_succeeded"] = False

            process = control.get("process")
            process_reaped = bool(control.get("process_reaped"))
            if process and not process_reaped:
                try:
                    process_reaped = job_supervisor._wait_process(kernel, process, 5000)
                except Exception:
                    process_reaped = False
                control["process_reaped"] = process_reaped
            if process and process_reaped:
                try:
                    if job_supervisor._close_handle(kernel, control["handles"], process):
                        control["process"] = 0
                except Exception:
                    pass

            if control.get("process_reaped") and not control.get("process"):
                try:
                    control["job_zero_confirmed"] = _wait_for_job_zero(
                        kernel, control["job"], timeout_seconds=5.0
                    )
                except Exception:
                    control["job_zero_confirmed"] = False
            for thread in threads:
                try:
                    thread.join(timeout=5.0)
                except Exception:
                    pass
    finally:
        if control is None:
            cleanup_complete = True
        else:
            process = control.get("process")
            process_reaped = bool(control.get("process_reaped"))
            if process and not process_reaped:
                try:
                    process_reaped = job_supervisor._wait_process(kernel, process, 0)
                except Exception:
                    process_reaped = False
                control["process_reaped"] = process_reaped
            if process and process_reaped:
                try:
                    if job_supervisor._close_handle(kernel, control["handles"], process):
                        control["process"] = 0
                except Exception:
                    pass

            threads_joined = all(not thread.is_alive() for thread in threads)
            pipes_complete = all(
                state["eof"] and state["done"] and not state["error"] and not state["overflow"]
                for state in states
            )
            retain_context = (
                not control.get("process_reaped")
                or bool(control.get("process"))
                or not control.get("job_zero_confirmed")
                or not threads_joined
                or not pipes_complete
            )
            if not retain_context:
                handles = control.get("handles")
                if type(handles) is not set:
                    retain_context = True
                else:
                    job_value = control.get("job")
                    try:
                        ordered_handles = sorted(
                            tuple(handles),
                            key=lambda handle: (handle == job_value, int(handle)),
                        )
                    except Exception:
                        ordered_handles = []
                        retain_context = True
                    for handle in ordered_handles:
                        try:
                            closed = job_supervisor._close_handle(kernel, handles, handle)
                        except Exception:
                            closed = False
                        if not closed:
                            retain_context = True
                            break
            if retain_context:
                _ROOT_HELPER_RETAINED_CONTEXTS.append(
                    (kernel, control, tuple(threads), tuple(states))
                )
            else:
                cleanup_complete = not control.get("handles")

    if primary_error is not None:
        if isinstance(primary_error, CurrentReaderError):
            raise primary_error
        raise CurrentReaderError("root_helper_lifecycle_failed") from None
    if not cleanup_complete:
        raise CurrentReaderError("root_helper_cleanup_unconfirmed")
    if result is None:
        raise CurrentReaderError("root_helper_lifecycle_failed")
    return result




def _verify_root_c01_artifacts(
    *,
    summary: dict[str, Any],
    private_module: Any,
    source_bytes: dict[str, bytes],
    registry: dict[str, Any],
    credentials: Mapping[str, str],
    helper_pid: int,
    helper_started_ms: int,
    helper_finished_ms: int,
    helper_elapsed_ms: int,
    summary_elapsed_ms: int,
    env_file: _HeldFile,
) -> dict[str, Any]:
    caller, evidence = summary["caller"], summary["evidence"]
    run_raw, run_doc, report_id = _open_private_json(
        evidence / "run.json", private_module, MAX_C01_ARCHIVE_BYTES
    )
    invocation_raw, invocation_doc, _ = _open_private_json(
        caller / "parent-invocation.json", private_module, 64 * 1024
    )
    config_raw, config, _ = _open_private_json(caller / "config.json", private_module, 64 * 1024)
    _require(
        type(invocation_doc) is dict
        and set(invocation_doc)
        == {
            "source_registry_sha256",
            "started_at_utc",
            "exit_code",
            "elapsed_ms",
            "stdout",
            "stderr",
        },
        "parent_invocation_fields",
    )
    _require(
        invocation_doc["source_registry_sha256"] == REGISTRY_SHA256
        and type(invocation_doc["exit_code"]) is int
        and invocation_doc["exit_code"] == 0
        and type(invocation_doc["elapsed_ms"]) is int
        and 0 <= invocation_doc["elapsed_ms"] <= MAX_ROOT_HELPER_SECONDS * 1000
        and type(invocation_doc["stderr"]) is str
        and invocation_doc["stderr"] == "",
        "parent_invocation_result",
    )
    _require(
        invocation_doc["started_at_utc"] == summary["started_at_utc"]
        and invocation_doc["elapsed_ms"] == summary_elapsed_ms
        and helper_elapsed_ms >= summary_elapsed_ms
        and helper_elapsed_ms - summary_elapsed_ms <= 10_000,
        "parent_invocation_time_binding",
    )
    _require(
        type(invocation_doc["stdout"]) is str
        and len(invocation_doc["stdout"].encode("utf-8")) <= MAX_HELPER_OUTPUT_BYTES
        and _strict(invocation_doc["stdout"].encode("utf-8"), MAX_HELPER_OUTPUT_BYTES) == run_doc,
        "parent_report_binding",
    )
    _require(
        type(config) is dict
        and set(config)
        == {
            "schema_version",
            "auth_profile",
            "case_id",
            "access",
            "venue",
            "environment",
            "region",
            "endpoint",
            "instrument_scope",
            "history_start_ms",
            "history_end_ms",
            "credential_env_file",
            "network_profile",
            "proxy_env_ref",
        }
        and type(config.get("schema_version")) is int
        and config["schema_version"] == 3
        and config.get("auth_profile") == "C01_SIGNED_REST_V2"
        and config.get("case_id") == "C01",
        "c01_config_profile",
    )
    _require(
        config.get("venue") == "okx"
        and config.get("environment") == "demo"
        and config.get("region") == "global"
        and config.get("endpoint") == "https://openapi.okx.com"
        and config.get("access") == "READ",
        "c01_config_scope",
    )
    _require(
        config.get("instrument_scope") == ["BTC-USDT-SWAP"]
        and config.get("network_profile") == "DIRECT"
        and config.get("proxy_env_ref") is None,
        "c01_config_binding",
    )
    _require(
        type(config["history_start_ms"]) is int
        and type(config["history_end_ms"]) is int
        and config["history_end_ms"] - config["history_start_ms"] == 60_000
        and helper_started_ms <= config["history_end_ms"] + 5_000
        and helper_finished_ms >= config["history_end_ms"]
        and helper_finished_ms - config["history_end_ms"] <= MAX_ROOT_HELPER_SECONDS * 1000 + 5_000,
        "c01_config_window",
    )
    _require(
        Path(config.get("credential_env_file", "")).resolve(strict=True) == ENV_FILE,
        "c01_env_reference",
    )
    _require(_sha(env_file.raw) == env_file.sha256, "env_snapshot_changed")
    _require(
        type(run_doc) is dict
        and run_doc.get("status") == "PASS"
        and run_doc.get("case_id") == "C01"
        and type(run_doc.get("strict_cases_passed")) is int
        and run_doc.get("strict_cases_passed") == 1
        and run_doc.get("auth_profile") == "C01_SIGNED_REST_V2",
        "c01_report_status",
    )
    _require(run_doc.get("source_registry_sha256") == REGISTRY_SHA256, "c01_report_registry")
    _require(
        run_doc.get("network_binding") == {"network_profile": "DIRECT", "proxy_env_ref": None},
        "c01_report_network",
    )
    children, receipts = run_doc.get("owned_children"), run_doc.get("observations")
    _require(
        type(children) is list and type(receipts) is list and len(children) == len(receipts) == 2,
        "c01_child_count",
    )
    _require(
        len({child.get("pid") for child in children}) == 2
        and len({child.get("nonce") for child in children}) == 2,
        "c01_child_identity",
    )
    # Load the exact pure contract from the held registry source, never an
    # importable checkout module or caller-supplied dataclass instance.
    contract_path = VENUE / "_certification/c01_signed_rest_v2.py"
    contract_raw = source_bytes["_certification/c01_signed_rest_v2.py"]
    contract = _load_source_module(
        f"_okx_m01_v3_c01_contract_{helper_pid}", contract_path, contract_raw
    )
    uids: list[str] = []
    bundles = []
    account_configuration_captures = []
    archive_hashes: list[str] = []
    child_pids, child_nonces = [], []
    request_count = 0
    last_finished_ms = 0
    for child, receipt in zip(children, receipts):
        _require(type(child) is dict and type(receipt) is dict, "c01_child_receipt_shape")
        _require(
            child.get("cleanup") == "COMPLETE"
            and type(child.get("exit_code")) is int
            and child.get("exit_code") == 0
            and child.get("receipt_verified") is True
            and child.get("termination_requested") is False
            and child.get("failure_code") is None,
            "c01_child_cleanup",
        )
        _require(
            child.get("pid") == receipt.get("pid") and child.get("nonce") == receipt.get("nonce"),
            "c01_child_receipt_binding",
        )
        pid, nonce = child.get("pid"), child.get("nonce")
        _require(
            type(pid) is int
            and pid > 0
            and type(nonce) is str
            and re.fullmatch(r"[0-9a-f]{32}", nonce),
            "c01_child_identity_shape",
        )
        child_pids.append(pid)
        child_nonces.append(nonce)
        archive_raw, archive, _ = _open_private_json(
            evidence / ("observation-" + nonce) / "archive.json",
            private_module,
            MAX_C01_ARCHIVE_BYTES,
        )
        archive_hash = _sha(archive_raw)
        _require(archive_hash == receipt.get("archive_sha256"), "c01_archive_hash")
        _require(
            archive.get("status") == "CAPTURE_COMPLETE_ONLY"
            and archive.get("source_kind") == "DIRECT_HTTPS_LOCAL_CAPTURE",
            "c01_archive_status",
        )
        scope = archive.get("scope")
        _require(
            type(scope) is dict
            and scope.get("contract") == "C01_SIGNED_REST_V2"
            and scope.get("venue") == "okx"
            and scope.get("environment") == "demo"
            and scope.get("region") == "global"
            and scope.get("endpoint") == "https://openapi.okx.com"
            and scope.get("instrument_scope") == ["BTC-USDT-SWAP"],
            "c01_archive_scope",
        )
        _require(
            archive.get("network_binding") == {"network_profile": "DIRECT", "proxy_env_ref": None},
            "c01_archive_network",
        )
        captures = archive.get("captures")
        _require(type(captures) is list and 1 <= len(captures) <= 64, "c01_capture_count")
        config_uid_values = []
        for capture in captures:
            _require(
                type(capture) is dict
                and capture.get("method") == "GET"
                and capture.get("http_status") == 200
                and capture.get("response_complete") is True
                and capture.get("raw_truncated") is False
                and capture.get("response_reason") == "complete"
                and capture.get("framing_classification") in {"CONTENT_LENGTH", "CHUNKED"},
                "c01_capture_transport",
            )
            raw_body = capture.get("raw_body_utf8")
            _require(
                type(raw_body) is str
                and _sha(raw_body.encode("utf-8")) == capture.get("raw_sha256"),
                "c01_raw_body_hash",
            )
            if capture.get("resource") == "account_configuration":
                config_uid_values.append(_validate_uid_body(raw_body))
        _require(
            len(config_uid_values) == 2 and len(set(config_uid_values)) == 1,
            "c01_capture_uid_count",
        )
        uids.append(config_uid_values[0])
        last_finished_ms = max(last_finished_ms, receipt.get("finished_ms", 0))
        request_count += len(captures)
        archive_hashes.append(archive_hash)
        value = {
            name: archive[name]
            for name in (
                "scope",
                "source_id",
                "source_kind",
                "collector_sha256",
                "capture_started_at_ms",
                "capture_deadline_ms",
                "captures",
            )
        }
        for capture in value["captures"]:
            capture.pop("raw_base64", None)
            for name in (
                "response_complete",
                "response_reason",
                "declared_length",
                "raw_truncated",
                "framing_classification",
            ):
                capture.pop(name, None)
        bundle = contract.bundle_from_document(value)
        validation = contract.validate_capture(bundle, now_ms=time.time_ns() // 1_000_000)
        _require(validation.validation_status == "CAPTURE_COMPLETE_ONLY", "c01_contract_incomplete")
        _require(
            type(receipt.get("started_ms")) is int
            and type(receipt.get("finished_ms")) is int
            and receipt["started_ms"] <= bundle.capture_started_at_ms <= receipt["finished_ms"],
            "c01_capture_time",
        )
        _require(
            helper_started_ms
            <= receipt["started_ms"]
            <= receipt["finished_ms"]
            <= helper_finished_ms,
            "c01_outer_time",
        )
        bundles.append(bundle)
        account_configuration_captures.extend(
            capture for capture in bundle.captures if capture.resource == "account_configuration"
        )
    _require(len(uids) == 2 and uids[0] == uids[1], "c01_uid_changed")
    uid = uids[0]
    _require(
        _account_ref(credentials, uid)
        == bundles[0].scope.account_ref
        == bundles[1].scope.account_ref,
        "c01_account_credential_binding",
    )
    compared = contract.compare_captures(*bundles, now_ms=time.time_ns() // 1_000_000)
    _require(compared.get("comparison_status") == "STABLE_FACTS_MATCH", "c01_stable_compare")
    _require(last_finished_ms > 0 and helper_finished_ms >= last_finished_ms, "c01_finish_time")
    _require(helper_finished_ms - last_finished_ms <= 30_000, "c01_uid_source_stale")
    _require(len(account_configuration_captures) == 4, "c01_case_operation_capture_count")
    selected_capture = next(
        capture
        for capture in reversed(bundles[-1].captures)
        if capture.resource == "account_configuration"
    )
    _require(
        type(selected_capture.capture_id) is str
        and 1 <= len(selected_capture.capture_id) <= 128
        and type(selected_capture.source_id) is str
        and 1 <= len(selected_capture.source_id) <= 128
        and type(selected_capture.request_sha256) is str
        and _HEX64.fullmatch(selected_capture.request_sha256) is not None
        and type(selected_capture.raw_sha256) is str
        and _HEX64.fullmatch(selected_capture.raw_sha256) is not None
        and type(selected_capture.request_started_at_ms) is int
        and type(selected_capture.response_received_at_ms) is int
        and selected_capture.request_started_at_ms <= selected_capture.response_received_at_ms,
        "c01_case_operation_capture_shape",
    )
    return {
        "uid": uid,
        "report_sha256": _sha(run_raw),
        "archive_sha256s": tuple(archive_hashes),
        "child_pids": tuple(child_pids),
        "child_nonces": tuple(child_nonces),
        "request_count": request_count,
        "last_capture_finished_ms": last_finished_ms,
        "private_run_json_file_id": report_id,
        "latest_account_configuration_capture": {
            "capture_id": selected_capture.capture_id,
            "request_sha256": selected_capture.request_sha256,
            "response_sha256": selected_capture.raw_sha256,
            "request_started_ms": selected_capture.request_started_at_ms,
            "response_received_ms": selected_capture.response_received_at_ms,
            "source_id_sha256": _sha(selected_capture.source_id.encode("utf-8")),
        },
    }
