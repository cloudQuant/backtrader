"""Root-only, fixed-path rebinding of OKX M01 V3 deployment metadata.

This unregistered helper accepts only the frozen public source map and review
identity held by its Root caller. It never loads credentials, contacts a
provider, or emits protected deployment bytes, paths, or hashes.
"""

from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import hashlib
import inspect
import os
from pathlib import Path
import re
import types
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
READER_RELATIVE = (
    "examples/000_live_certification/okx_penetration/" "_m01_readonly_monitor_v3/current_reader.py"
)
REVIEW_REF = "iteration41-okx-m01-source-owned-v3-review-r2"
OLD_REVIEW_REF = REVIEW_REF
ROOT_CU_PRIVATE_MODULE_NAME = "_root_public_custody_private"
CANONICAL_PRIVATE_MODULE_NAME = "backtrader_runtime.certification_roundtrip_private"
R2_SOURCE_MAP_SHA256 = "07f0eb60d60f37919c75cc3ec6833b41653fdbc9952c8478dbbc36ba0cda1ff3"
R2_SOURCE_MAP_SIZE = 2877
OLD_SOURCE_MAP_SHA256 = "db7b351656a0e26aac3778332ed7eb838a92a73605a5bb3604cb4b770c06ebe3"
CURRENT_REVIEW_SHA256 = "c09eb8be009567b70d50a063e042ef7d75af8ce8d2368fd568bdb4b82e38263b"
CURRENT_REVIEW_SIZE = 3820
CURRENT_REVIEW_TEST_SHA256 = "21d43a5e8d1c517c2ffaa147c96f58343fb188432d4fae47717a5b68b6ec040d"
CURRENT_REVIEW_TEST_SIZE = 9809
_PROFILE = "OKX_GLOBAL_DEMO_M01_CASE_V3"
_ADMISSION_SCHEMA = "iteration41.okx.m01.case-deployment.v3"
_SOURCE_MAP_SCHEMA = "iteration41.okx.m01.case-source-map.v3"
_CURRENT_REVIEWED_SOURCES = {
    READER_RELATIVE: (
        68215,
        "5a8fd479c999279d9efde625cac1938d794201f04e1beaa6f3663b267d7a7ebc",
    ),
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/entry.py": (
        5952,
        "e0613b66fa54d5ea155da263d1e901e8ada78adf7d83a7e1c8dc5430ea440d1e",
    ),
    "examples/000_live_certification/okx_penetration/cases/M01/run.py": (
        1992,
        "d498e32fcb573781a3eec25eff4c7ba98bfe2c8d4d94f9e5a9b078ab4074641e",
    ),
}
PRIVATE_RELATIVE = "backtrader_runtime/certification_roundtrip_private.py"
BACKUP_CHILD = "r3-20261009-preservation"
CURRENT_REVIEW_RELATIVE = (
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-okx-m01-root-helper-lifecycle-integration-r1-independent-review-r1-"
    "2026-10-09-oct7f/README.md"
)
CURRENT_REVIEW_TEST_RELATIVE = (
    "tests/unit/scripts/test_iteration41_okx_m01_reader_lifecycle_integration_r1.py"
)
BACKUP_NAMES = ("deployment.json", "source-map.json")
_DEPLOYMENT = Path("D:/temp/iteration41-okx-m01-v3-deployment")
_DEPLOYMENT_PATHS = {
    "deployment.json": _DEPLOYMENT / "deployment.json",
    "source-map.json": _DEPLOYMENT / "source-map.json",
}
_OLD_STATUS = "ADMITTED_SOURCE_PIN"
_MAX_ADMISSION = 64 * 1024
_MAX_SOURCE_MAP = 256 * 1024
_MAX_PUBLIC_SOURCE = 2 * 1024 * 1024
_READ_CHUNK = 64 * 1024
_OPERATION_SECONDS = 20.0
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_INVALID_HANDLE = C.c_void_p(-1).value
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_READ_CONTROL = 0x00020000
_READ_ATTRIBUTES = 0x00000080
_FILE_SHARE_READ = 0x00000001
_OPEN_EXISTING = 3
_CREATE_NEW = 1
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_FLAGS = _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT
_DIR_FLAGS = _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT
_STATE_KEYS = (
    "backup_created",
    "source_map_updated",
    "deployment_updated",
    "readback_verified",
    "handles_released",
)
_ERROR_CODES = frozenset(
    {
        "invalid_root_inputs",
        "review_identity_mismatch",
        "reader_binding_mismatch",
        "source_map_invalid",
        "source_pin_mismatch",
        "old_metadata_invalid",
        "protected_path_invalid",
        "backup_name_in_use",
        "protected_io_failed",
        "protected_write_uncertain",
        "protected_close_uncertain",
        "operation_deadline",
    }
)


class RebindError(ValueError):
    """Finite source-fake result; no OS text or protected value is retained."""

    def __init__(self, code: str, state: dict[str, bool] | None = None):
        self.code = code if code in _ERROR_CODES else "protected_io_failed"
        self.state = _state(state)
        super().__init__(self.code)


def _state(values: dict[str, bool] | None = None) -> dict[str, bool]:
    values = values or {}
    result = {key: values.get(key) is True for key in _STATE_KEYS}
    result["handles_released"] = values.get("handles_released", True) is True
    return result


def _fail(code: str, state: dict[str, bool] | None = None) -> None:
    raise RebindError(code, state) from None


def _read_public_source(path: Path) -> bytes:
    size = path.stat().st_size
    if size < 0 or size > _MAX_PUBLIC_SOURCE:
        raise ValueError("public_source_size")
    with path.open("rb") as stream:
        raw = stream.read(_MAX_PUBLIC_SOURCE + 1)
    if len(raw) != size or len(raw) > _MAX_PUBLIC_SOURCE:
        raise ValueError("public_source_size")
    return raw


def _code_index(module_code: types.CodeType) -> dict[str, list[types.CodeType]]:
    result: dict[str, list[types.CodeType]] = {}
    pending = [module_code]
    while pending:
        code = pending.pop()
        result.setdefault(code.co_name, []).append(code)
        pending.extend(value for value in code.co_consts if isinstance(value, types.CodeType))
    return result


def _reader_binding(reader: Any) -> None:
    try:
        expected = (ROOT / Path(READER_RELATIVE)).resolve(strict=True)
        if ROOT not in expected.parents:
            _fail("reader_binding_mismatch")
        module_file = reader.__file__
        if type(module_file) is not str or Path(module_file) != expected:
            _fail("reader_binding_mismatch")
        source = Path(module_file).resolve(strict=True)
        expected_size, expected_sha = _CURRENT_REVIEWED_SOURCES[READER_RELATIVE]
        if expected.stat().st_size != expected_size:
            _fail("reader_binding_mismatch")
        source_raw = _read_public_source(expected)
        if (
            len(source_raw) != expected_size
            or hashlib.sha256(source_raw).hexdigest() != expected_sha
        ):
            _fail("reader_binding_mismatch")
        expected_codes = _code_index(compile(source_raw, str(expected), "exec"))
        bound_functions = {
            "_require": reader._require,
            "_sha": reader._sha,
            "_canonical": reader._canonical,
            "_strict": reader._strict,
            "_validate_deployment_documents": reader._validate_deployment_documents,
        }
        valid = (
            reader.__name__ == "_m01_readonly_monitor_v3.current_reader"
            and source == expected
            and reader.SOURCE_REVIEW_REF == REVIEW_REF
            and reader.PROFILE == _PROFILE
            and reader.ADMISSION_SCHEMA == _ADMISSION_SCHEMA
            and reader.SOURCE_MAP_SCHEMA == _SOURCE_MAP_SCHEMA
            and reader.DEPLOYMENT_DIRECTORY == _DEPLOYMENT
            and reader.ADMISSION_FILE == _DEPLOYMENT_PATHS["deployment.json"]
            and reader.SOURCE_MAP_FILE == _DEPLOYMENT_PATHS["source-map.json"]
            and all(
                type(function) is types.FunctionType
                and function.__module__ == reader.__name__
                and function.__globals__ is reader.__dict__
                and len(expected_codes.get(name, ())) == 1
                and function.__code__ == expected_codes[name][0]
                and function.__defaults__ is None
                and (
                    type(function.__kwdefaults__) is dict
                    and function.__kwdefaults__ == {"invocation_source_map_sha256": None}
                    if name == "_validate_deployment_documents"
                    else function.__kwdefaults__ is None
                )
                for name, function in bound_functions.items()
            )
        )
    except Exception:
        _fail("reader_binding_mismatch")
    if not valid:
        _fail("reader_binding_mismatch")


def _root_inputs(
    reader: Any,
    held_source_map_raw: bytes,
    source_review_ref: str,
    held_current_review_raw: bytes,
    held_current_review_test_raw: bytes,
):
    if (
        type(held_source_map_raw) is not bytes
        or type(source_review_ref) is not str
        or type(held_current_review_raw) is not bytes
        or type(held_current_review_test_raw) is not bytes
    ):
        _fail("invalid_root_inputs")
    if (
        source_review_ref != REVIEW_REF
        or len(held_source_map_raw) != R2_SOURCE_MAP_SIZE
        or hashlib.sha256(held_source_map_raw).hexdigest() != R2_SOURCE_MAP_SHA256
        or len(held_current_review_raw) != CURRENT_REVIEW_SIZE
        or hashlib.sha256(held_current_review_raw).hexdigest() != CURRENT_REVIEW_SHA256
        or len(held_current_review_test_raw) != CURRENT_REVIEW_TEST_SIZE
        or hashlib.sha256(held_current_review_test_raw).hexdigest() != CURRENT_REVIEW_TEST_SHA256
    ):
        _fail("review_identity_mismatch")
    _reader_binding(reader)
    try:
        source_map = reader._strict(held_source_map_raw, _MAX_SOURCE_MAP)
        if (
            type(source_map) is not dict
            or set(source_map) != {"schema", "source_pins"}
            or source_map["schema"] != reader.SOURCE_MAP_SCHEMA
            or type(source_map["source_pins"]) is not dict
            or set(source_map["source_pins"]) != reader.SOURCE_MAP_RELATIVES
            or len(source_map["source_pins"]) != 19
            or reader._canonical(source_map) + b"\n" != held_source_map_raw
        ):
            _fail("source_map_invalid")
        pins = source_map["source_pins"]
        source_sizes = {}
        for relative, pin in pins.items():
            if type(relative) is not str or type(pin) is not str or not _HEX64.fullmatch(pin):
                _fail("source_map_invalid")
            candidate = ROOT / Path(relative)
            resolved = candidate.resolve(strict=True)
            if ROOT not in resolved.parents:
                _fail("source_map_invalid")
            try:
                raw = _read_public_source(resolved)
            except Exception:
                _fail("source_map_invalid")
            if hashlib.sha256(raw).hexdigest() != pin:
                _fail("source_pin_mismatch")
            source_sizes[relative] = len(raw)
        for relative, (size, digest) in _CURRENT_REVIEWED_SOURCES.items():
            if pins.get(relative) != digest or source_sizes.get(relative) != size:
                _fail("review_identity_mismatch")
        draft = {
            "schema": reader.ADMISSION_SCHEMA,
            "status": _OLD_STATUS,
            "profile": reader.PROFILE,
            "source_map_sha256": reader._sha(held_source_map_raw),
            "review_ref": REVIEW_REF,
        }
        reader._validate_deployment_documents(reader._canonical(draft) + b"\n", held_source_map_raw)
        return source_map
    except RebindError:
        raise
    except Exception:
        _fail("source_map_invalid")


def _private_binding(
    private_module: Any, source_map: dict[str, Any], expected_module_name: str
) -> None:
    try:
        expected = (ROOT / Path(PRIVATE_RELATIVE)).resolve(strict=True)
        if ROOT not in expected.parents:
            _fail("reader_binding_mismatch")
        module_file = private_module.__file__
        if type(module_file) is not str or Path(module_file) != expected:
            _fail("reader_binding_mismatch")
        source = Path(module_file).resolve(strict=True)
        if source != expected:
            _fail("reader_binding_mismatch")
        pin = source_map["source_pins"][PRIVATE_RELATIVE]
        actual = hashlib.sha256(_read_public_source(expected)).hexdigest()
        api_function = private_module._api
        artifact_directory = private_module.PrivateArtifactDirectory
        bound_functions = tuple(
            inspect.unwrap(function)
            for function in (
                api_function,
                private_module._ancestors,
                private_module.create_private_directory,
                artifact_directory.verify,
                artifact_directory.write_bytes,
            )
        )
        valid = (
            private_module.__name__ == expected_module_name
            and source == expected
            and actual == pin
            and all(
                callable(function)
                and getattr(getattr(function, "__code__", None), "co_filename", None)
                == str(expected)
                and getattr(function, "__globals__", None) is private_module.__dict__
                for function in bound_functions
            )
            and artifact_directory.__module__ == expected_module_name
        )
    except Exception:
        _fail("reader_binding_mismatch")
    if not valid:
        _fail("reader_binding_mismatch")


class _Win32Leaves:
    """Narrow Win32 adapter. File reads and updates stay on one held handle."""

    def __init__(self, private_module: Any):
        self.private = private_module
        self.api = private_module._api()
        self.kernel = self.api.kernel
        self._declare(
            "ReadFile", [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p], W.BOOL
        )
        self._declare(
            "SetFilePointerEx", [W.HANDLE, C.c_longlong, C.POINTER(C.c_longlong), W.DWORD], W.BOOL
        )
        self._declare("SetEndOfFile", [W.HANDLE], W.BOOL)

    def _declare(self, name: str, args: list[Any], result: Any) -> None:
        call = getattr(self.kernel, name)
        call.argtypes, call.restype = args, result
        setattr(self, name, call)

    @staticmethod
    def exists(path: Path) -> bool:
        return os.path.lexists(path)

    def current_sid(self) -> str:
        return self.api.current_sid()

    def open_directory(self, path: Path):
        handle = self.api.CreateFileW(
            str(path),
            _READ_CONTROL | _READ_ATTRIBUTES,
            3,
            None,
            _OPEN_EXISTING,
            _DIR_FLAGS,
            None,
        )
        if handle == _INVALID_HANDLE:
            _fail("protected_io_failed")
        return handle

    def open_existing_file(self, path: Path):
        handle = self.api.CreateFileW(
            str(path),
            _GENERIC_READ | _GENERIC_WRITE | _READ_CONTROL | _READ_ATTRIBUTES,
            _FILE_SHARE_READ,
            None,
            _OPEN_EXISTING,
            _FILE_FLAGS,
            None,
        )
        if handle == _INVALID_HANDLE:
            _fail("protected_io_failed")
        return handle

    def create_directory(self, path: Path, sid: str) -> None:
        with self.api.descriptor(sid, directory=True) as descriptor:
            if not self.api.CreateDirectoryW(str(path), C.byref(descriptor)):
                _fail("protected_io_failed")

    def create_new_file(self, path: Path, sid: str):
        with self.api.descriptor(sid, directory=False) as descriptor:
            handle = self.api.CreateFileW(
                str(path),
                _GENERIC_READ | _GENERIC_WRITE | _READ_CONTROL | _READ_ATTRIBUTES,
                0,
                C.byref(descriptor),
                _CREATE_NEW,
                _FILE_FLAGS,
                None,
            )
        if handle == _INVALID_HANDLE:
            _fail("protected_io_failed")
        return handle

    def info(self, handle, *, directory: bool):
        return self.api.info(handle, directory=directory)

    def verify_acl(self, handle, sid: str, *, directory: bool = False) -> None:
        self.api.verify_acl(handle, sid, directory=directory)

    def read_bounded(self, handle, limit: int) -> bytes:
        position = C.c_longlong()
        if not self.SetFilePointerEx(handle, 0, C.byref(position), 0):
            _fail("protected_io_failed")
        output = bytearray()
        while len(output) <= limit:
            size = min(_READ_CHUNK, limit + 1 - len(output))
            if size <= 0:
                break
            buffer = C.create_string_buffer(size)
            count = W.DWORD()
            if not self.ReadFile(handle, buffer, size, C.byref(count), None):
                _fail("protected_io_failed")
            if count.value == 0:
                break
            output.extend(buffer.raw[: count.value])
        if len(output) > limit:
            _fail("protected_io_failed")
        return bytes(output)

    def write_truncate_flush(self, handle, payload: bytes) -> None:
        position = C.c_longlong()
        if not self.SetFilePointerEx(handle, 0, C.byref(position), 0):
            _fail("protected_io_failed")
        offset = 0
        while offset < len(payload):
            chunk = payload[offset : offset + _READ_CHUNK]
            buffer = C.create_string_buffer(chunk)
            count = W.DWORD()
            if not self.api.WriteFile(
                handle, buffer, len(chunk), C.byref(count), None
            ) or count.value != len(chunk):
                _fail("protected_write_uncertain")
            offset += count.value
        if not self.SetEndOfFile(handle) or not self.api.FlushFileBuffers(handle):
            _fail("protected_write_uncertain")

    def close(self, handle) -> bool:
        return bool(self.api.CloseHandle(handle))


_ORPHANED_CONTEXTS: list[tuple[Any, tuple[Any, ...]]] = []


class _Lease:
    def __init__(self, io: Any, state: dict[str, bool]):
        self.io = io
        self.state = state
        self.handles: list[Any] = []
        self.retained = False

    def add(self, handle):
        self.handles.append(handle)
        self.state["handles_released"] = False
        return handle

    def retain(self) -> None:
        if not self.retained:
            _ORPHANED_CONTEXTS.append((self.io, tuple(self.handles)))
            self.retained = True
        self.state["handles_released"] = False

    def close_all(self) -> bool:
        while self.handles:
            handle = self.handles[-1]
            try:
                closed = self.io.close(handle)
            except Exception:
                closed = False
            if not closed:
                self.retain()
                return False
            self.handles.pop()
        self.state["handles_released"] = True
        return True


def _deadline_check(deadline: float, state: dict[str, bool]) -> None:
    import time

    if time.monotonic() >= deadline:
        _fail("operation_deadline", state)


def _identity(io: Any, handle, *, directory: bool, expected=None):
    identity = io.info(handle, directory=directory)
    if expected is not None and identity != expected:
        _fail("protected_path_invalid")
    return identity


def _read_checked(io: Any, handle, sid: str, limit: int, identity):
    if _identity(io, handle, directory=False, expected=identity) != identity:
        _fail("protected_path_invalid")
    io.verify_acl(handle, sid)
    raw = io.read_bounded(handle, limit)
    io.verify_acl(handle, sid)
    return raw


def _write_checked(
    io: Any, handle, sid: str, limit: int, identity, payload: bytes, state: dict[str, bool]
) -> None:
    io.verify_acl(handle, sid)
    if _identity(io, handle, directory=False, expected=identity) != identity:
        _fail("protected_path_invalid", state)
    io.write_truncate_flush(handle, payload)
    readback = _read_checked(io, handle, sid, limit, identity)
    if readback != payload:
        _fail("protected_write_uncertain", state)


def _old_documents(reader: Any, old_admission_raw: bytes, old_map_raw: bytes):
    try:
        if reader._sha(old_map_raw) != OLD_SOURCE_MAP_SHA256:
            _fail("old_metadata_invalid")
        old_admission = reader._strict(old_admission_raw, _MAX_ADMISSION)
        if (
            type(old_admission) is not dict
            or set(old_admission)
            != {"schema", "status", "profile", "source_map_sha256", "review_ref"}
            or old_admission["review_ref"] != OLD_REVIEW_REF
            or reader._canonical(old_admission) + b"\n" != old_admission_raw
        ):
            _fail("old_metadata_invalid")
        reader._validate_deployment_documents(old_admission_raw, old_map_raw)
        return old_admission
    except RebindError:
        raise
    except Exception:
        _fail("old_metadata_invalid")


def _backup_file(
    io: Any, lease: _Lease, backup_dir: Path, name: str, payload: bytes, limit: int, sid: str
) -> None:
    handle = lease.add(io.create_new_file(backup_dir / name, sid))
    identity = _identity(io, handle, directory=False)
    io.verify_acl(handle, sid)
    io.write_truncate_flush(handle, payload)
    try:
        readback = _read_checked(io, handle, sid, limit, identity)
    except Exception:
        _fail("protected_write_uncertain")
    if readback != payload:
        _fail("protected_write_uncertain")


def rebind_fixed_deployment(
    *,
    held_source_map_raw: bytes,
    source_review_ref: str,
    held_current_review_raw: bytes,
    held_current_review_test_raw: bytes,
    reader_module: Any,
    private_module: Any,
    io: Any = None,
) -> dict[str, bool | str]:
    """Preserve accepted R2 bytes, then bind the fixed deployment to current V3 pins.

    Root must hold the 19 public source leases, the exact current source-map
    bytes, the current integration review note, and its separately reviewed
    test source for the entire call. The older source-review reference remains
    the reader's fixed admission identity; it does not authorize this updated
    map by itself. Root must independently check `BACKUP_CHILD` is absent.
    `io` exists solely for faithful source-fake coverage; the Root invocation
    leaves it unset.
    """
    state = _state()
    source_fake = io is not None
    source_map = _root_inputs(
        reader_module,
        held_source_map_raw,
        source_review_ref,
        held_current_review_raw,
        held_current_review_test_raw,
    )
    expected_private_name = (
        CANONICAL_PRIVATE_MODULE_NAME if io is not None else ROOT_CU_PRIVATE_MODULE_NAME
    )
    _private_binding(private_module, source_map, expected_private_name)
    if io is None:
        try:
            io = _Win32Leaves(private_module)
        except RebindError:
            raise
        except Exception:
            _fail("protected_io_failed", state)
    elif getattr(io, "__class__", None).__name__ != "_FakeProtectedOS":
        _fail("invalid_root_inputs", state)

    mutation_attempted = False
    try:
        import time

        deadline = time.monotonic() + _OPERATION_SECONDS
        lease = _Lease(io, state)
        sid = io.current_sid()
        directories = tuple(reversed(_DEPLOYMENT.parents)) + (_DEPLOYMENT,)
        directory_ids: list[tuple[Any, Any, bool]] = []
        for index, directory in enumerate(directories):
            handle = lease.add(io.open_directory(directory))
            identity = _identity(io, handle, directory=True)
            owner_only = directory == _DEPLOYMENT
            if owner_only:
                io.verify_acl(handle, sid, directory=True)
            directory_ids.append((handle, identity, owner_only))
            if directory.name.lower() == ".git" or io.exists(directory / ".git"):
                _fail("protected_path_invalid", state)
            _deadline_check(deadline, state)

        admission_path = _DEPLOYMENT_PATHS["deployment.json"]
        map_path = _DEPLOYMENT_PATHS["source-map.json"]
        admission_handle = lease.add(io.open_existing_file(admission_path))
        admission_id = _identity(io, admission_handle, directory=False)
        map_handle = lease.add(io.open_existing_file(map_path))
        map_id = _identity(io, map_handle, directory=False)
        old_admission_raw = _read_checked(io, admission_handle, sid, _MAX_ADMISSION, admission_id)
        old_map_raw = _read_checked(io, map_handle, sid, _MAX_SOURCE_MAP, map_id)
        _old_documents(reader_module, old_admission_raw, old_map_raw)
        _deadline_check(deadline, state)

        backup_path = _DEPLOYMENT / BACKUP_CHILD
        if io.exists(backup_path):
            _fail("backup_name_in_use", state)
        io.create_directory(backup_path, sid)
        state["backup_created"] = True
        backup_handle = lease.add(io.open_directory(backup_path))
        backup_id = _identity(io, backup_handle, directory=True)
        io.verify_acl(backup_handle, sid, directory=True)
        directory_ids.append((backup_handle, backup_id, True))
        _backup_file(
            io,
            lease,
            backup_path,
            "deployment.json",
            old_admission_raw,
            _MAX_ADMISSION,
            sid,
        )
        _backup_file(
            io,
            lease,
            backup_path,
            "source-map.json",
            old_map_raw,
            _MAX_SOURCE_MAP,
            sid,
        )
        _deadline_check(deadline, state)

        source_map_doc = reader_module._strict(held_source_map_raw, _MAX_SOURCE_MAP)
        new_admission = {
            "schema": reader_module.ADMISSION_SCHEMA,
            "status": _OLD_STATUS,
            "profile": reader_module.PROFILE,
            "source_map_sha256": reader_module._sha(held_source_map_raw),
            "review_ref": REVIEW_REF,
        }
        new_admission_raw = reader_module._canonical(new_admission) + b"\n"
        reader_module._validate_deployment_documents(new_admission_raw, held_source_map_raw)

        mutation_attempted = True
        _write_checked(io, map_handle, sid, _MAX_SOURCE_MAP, map_id, held_source_map_raw, state)
        state["source_map_updated"] = True
        _deadline_check(deadline, state)
        _write_checked(
            io,
            admission_handle,
            sid,
            _MAX_ADMISSION,
            admission_id,
            new_admission_raw,
            state,
        )
        state["deployment_updated"] = True
        final_map_raw = _read_checked(io, map_handle, sid, _MAX_SOURCE_MAP, map_id)
        final_admission_raw = _read_checked(io, admission_handle, sid, _MAX_ADMISSION, admission_id)
        _admission, final_pins, final_sha = reader_module._validate_deployment_documents(
            final_admission_raw, final_map_raw
        )
        if (
            final_map_raw != held_source_map_raw
            or final_sha != new_admission["source_map_sha256"]
            or final_pins != source_map_doc["source_pins"]
        ):
            _fail("protected_write_uncertain", state)
        state["readback_verified"] = True

        for handle, identity, owner_only in directory_ids:
            if _identity(io, handle, directory=True, expected=identity) != identity:
                _fail("protected_path_invalid", state)
            if owner_only:
                io.verify_acl(handle, sid, directory=True)
        for handle, identity in ((admission_handle, admission_id), (map_handle, map_id)):
            if _identity(io, handle, directory=False, expected=identity) != identity:
                _fail("protected_path_invalid", state)
            io.verify_acl(handle, sid)
        _deadline_check(deadline, state)

        if not lease.close_all():
            _fail("protected_close_uncertain", state)
        state["handles_released"] = True
        return {"status": "SOURCE_FAKE_REBOUND" if source_fake else "REBOUND", **state}
    except RebindError as exc:
        active = locals().get("lease")
        if active is not None:
            if (
                mutation_attempted
                or state["source_map_updated"]
                or state["deployment_updated"]
                or exc.code == "protected_write_uncertain"
            ):
                active.retain()
            elif not active.retained:
                if not active.close_all():
                    exc = RebindError("protected_close_uncertain", state)
        raise RebindError(exc.code, state) from None
    except Exception:
        active = locals().get("lease")
        if active is not None:
            if mutation_attempted or state["source_map_updated"] or state["deployment_updated"]:
                active.retain()
            elif not active.retained and not active.close_all():
                _fail("protected_close_uncertain", state)
        _fail("protected_io_failed", state)
