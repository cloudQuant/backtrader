"""Sourcefake checks for the R2 Root preparation call adapter.

The positive loader case executes the pinned public V4 module, including its
own nested V3 loader. It never opens a physical source scope or reads external
software/cache payloads.
"""

from __future__ import annotations

import hashlib
import ctypes
import importlib.machinery
import ntpath
import os
from contextlib import contextmanager
from pathlib import Path
import sys
import types

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
CALL_PATH = REPO_ROOT / "scripts/iteration41_optional16_r33_root_preparation_call_r2.py"
V3_PATH = REPO_ROOT / "scripts/iteration41_root_held_source_scope_v3.py"
V4_PATH = REPO_ROOT / "scripts/iteration41_root_held_source_scope_v4.py"
V3_SHA256 = "f3270495d3ddb046f8617d689510d4ae6ee700d639e0db769c518a15099a7677"
V4_SHA256 = "138c86e21de773822eceac07034e113e0adb5ea5d9056fcc16cee10a75c0e830"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_public(path: Path) -> bytes:
    raw = path.read_bytes()
    assert type(raw) is bytes and raw
    return raw


def _load_module(name: str, path: Path, raw: bytes, digest: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__loader__ = None
    module.__cached__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(path))
    module.__verified_source_sha256__ = digest
    exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__, module.__dict__)
    return module


def _load_call() -> types.ModuleType:
    raw = _read_public(CALL_PATH)
    return _load_module(
        "iteration41_optional16_r33_root_preparation_call_r2_test",
        CALL_PATH,
        raw,
        _sha(raw),
    )


def _production_loaded_v4(call: types.ModuleType) -> tuple[bytes, bytes, types.ModuleType, types.ModuleType]:
    v3_raw = _read_public(V3_PATH)
    v4_raw = _read_public(V4_PATH)
    assert _sha(v3_raw) == V3_SHA256
    assert _sha(v4_raw) == V4_SHA256
    # This runs the pinned V4 top-level loader. V4 itself loads V3 from the
    # exact public file and leaves V3.__cached__ absent, as the production
    # loader does.
    missing = object()
    prior = sys.modules.pop(call.V3_MODULE_NAME, missing)
    try:
        v4 = call._make_module(call.V4_MODULE_NAME, call.V4_REL, v4_raw, call.V4_SHA256)
        v3 = v4._V3_MODULE
    finally:
        sys.modules.pop(call.V3_MODULE_NAME, None)
        if prior is not missing:
            sys.modules[call.V3_MODULE_NAME] = prior
    assert type(v3) is types.ModuleType
    assert v3.__file__ == str(V3_PATH)
    assert "__cached__" not in v3.__dict__
    return v3_raw, v4_raw, v3, v4


def _append_retained_scope(v3: types.ModuleType, scope: object) -> None:
    v3._RETAINED_SCOPES.append(scope)


def _remove_retained_scope(v3: types.ModuleType, scope: object) -> None:
    v3._RETAINED_SCOPES[:] = [item for item in v3._RETAINED_SCOPES if item is not scope]


def _path_key(path: object) -> str:
    return ntpath.normcase(ntpath.normpath(os.fspath(path)))


class _FakeFunction:
    def __init__(self, callback):
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


class _FakeKernel:
    def __init__(self, owner):
        self.owner = owner
        self.GetFileInformationByHandle = _FakeFunction(self._file_info)
        self.ReadFile = _FakeFunction(self._read_file)
        self.SetFilePointerEx = _FakeFunction(self._seek)

    def _file_info(self, handle, pointer):
        record = self.owner.handles.get(handle)
        if record is None:
            return 0
        info = ctypes.cast(pointer, ctypes.POINTER(self.owner.file_info_type)).contents
        info.attributes = 0x10 if record["directory"] else 0
        info.links = 1
        info.volume = 71
        info.index_high = 0
        info.index_low = record["identity"]
        size = 0 if record["directory"] else len(self.owner.files[record["key"]])
        info.size_high = size >> 32
        info.size_low = size & 0xFFFFFFFF
        return 1

    def _seek(self, handle, _distance, pointer, method):
        record = self.owner.handles.get(handle)
        if record is None or method != 0:
            return 0
        record["offset"] = 0
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_longlong)).contents.value = 0
        return 1

    def _read_file(self, handle, buffer, requested, pointer, _overlapped):
        record = self.owner.handles.get(handle)
        if record is None or record["directory"]:
            return 0
        raw = self.owner.files[record["key"]][record["offset"] : record["offset"] + requested]
        if raw:
            buffer[: len(raw)] = raw
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32)).contents.value = len(raw)
        record["offset"] += len(raw)
        self.owner.read_count += 1
        return 1


class _FakeAPI:
    def __init__(self, files):
        self.files = {_path_key(path): raw for path, raw in files.items()}
        self.handles = {}
        self.next_handle = 10
        self.file_info_type = None
        self.invalid_handle = None
        self.read_count = 0
        self.kernel = _FakeKernel(self)

    def _new_handle(self, key, *, directory):
        handle = self.next_handle
        self.next_handle += 1
        self.handles[handle] = {
            "key": key,
            "directory": directory,
            "offset": 0,
            "identity": handle,
        }
        return handle

    def CreateFileW(self, path, access, share, _security, _disposition, flags, _template):
        key = _path_key(path)
        if access != (0x80000000 | 0x20000 | 0x80) or share != 1 or flags != 0x02200000:
            return self.invalid_handle
        if key not in self.files:
            return self.invalid_handle
        return self._new_handle(key, directory=False)

    def CloseHandle(self, handle):
        return int(self.handles.pop(handle, None) is not None)

    @contextmanager
    def opened(self, path, *, directory, access=0x20080):
        if directory is not True or access != 0x80:
            raise AssertionError("sourcefake_directory_open_contract_changed")
        handle = self._new_handle(_path_key(path), directory=True)
        try:
            yield handle
        finally:
            if not self.CloseHandle(handle):
                raise AssertionError("sourcefake_directory_close_failed")

    def info(self, handle, *, directory):
        record = self.handles.get(handle)
        if record is None or record["directory"] is not directory:
            raise AssertionError("sourcefake_directory_identity_invalid")
        return (71, record["identity"])


def _sourcefake_v4_scope(v4, v3_raw: bytes, v4_raw: bytes):
    bindings = (
        {
            "logical_origin": "sourcefake-root-v3",
            "physical_path": str(V3_PATH),
            "sha256": V3_SHA256,
            "max_bytes": 256 * 1024,
            "category": "public",
        },
        {
            "logical_origin": "sourcefake-root-v4",
            "physical_path": str(V4_PATH),
            "sha256": V4_SHA256,
            "max_bytes": 256 * 1024,
            "category": "public",
        },
    )
    scope = v4.RootHeldScopeV4(bindings, enabled=True)
    api = _FakeAPI({V3_PATH: v3_raw, V4_PATH: v4_raw})
    api.file_info_type = scope.private._FILE_INFO
    api.invalid_handle = scope.private._INVALID_HANDLE
    scope._sourcefake_enter(api, v4._V3_MODULE._SOURCE_FAKE_TOKEN)
    return scope, api


def test_nested_pinned_v3_loader_allows_only_absent_or_none_cache_slot():
    call = _load_call()
    missing = object()
    prior_alias = sys.modules.get(call.V3_MODULE_NAME, missing)
    v3_raw, v4_raw, v3, v4 = _production_loaded_v4(call)

    reference_v3, reference_v4 = call.bind_v4_module_to_held_source(
        v4, {"v3": v3_raw, "v4": v4_raw}
    )
    assert reference_v3.__dict__["__cached__"] is None
    assert reference_v4.__dict__["__cached__"] is None
    assert v4._V3_MODULE is v3
    assert sys.modules.get(call.V3_MODULE_NAME, missing) is prior_alias

    v3.__cached__ = None
    call.bind_v4_module_to_held_source(v4, {"v3": v3_raw, "v4": v4_raw})
    v3.__cached__ = "unexpected-cache-slot"
    with pytest.raises(call.RootPreparationCallError, match="module_source_metadata_mismatch"):
        call.bind_v4_module_to_held_source(v4, {"v3": v3_raw, "v4": v4_raw})


def test_missing_cache_slot_is_not_allowed_for_the_pinned_v4_module():
    call = _load_call()
    v3_raw, v4_raw, _v3, v4 = _production_loaded_v4(call)
    del v4.__cached__

    with pytest.raises(call.RootPreparationCallError, match="module_source_metadata_mismatch"):
        call.bind_v4_module_to_held_source(v4, {"v3": v3_raw, "v4": v4_raw})


def test_nested_v3_code_and_globals_remain_bound_after_cache_slot_fix():
    call = _load_call()
    v3_raw, v4_raw, v3, v4 = _production_loaded_v4(call)
    v3.ROOT_HELD_SCOPE_V3_SCHEMA = "changed"

    with pytest.raises(call.RootPreparationCallError, match="module_global_value_mismatch"):
        call.bind_v4_module_to_held_source(v4, {"v3": v3_raw, "v4": v4_raw})


def test_module_binding_failure_has_finite_phase_projection_and_no_error_text():
    call = _load_call()
    v3_raw, v4_raw, _v3, v4 = _production_loaded_v4(call)
    changed_v3 = bytearray(v3_raw)
    changed_v3[-1] ^= 1

    result = call.prepare_root_source_verification(
        object(), v4, b"{}", {"v3": bytes(changed_v3), "v4": v4_raw}, b"x", requested=True
    )

    assert result["status"] == "BLOCKED_RETAINED"
    assert result["reason_code"] == "source_binding_or_preparation_failed"
    assert result["diagnostic_phase"] == "module_binding"
    assert result["diagnostic_category"] == "source_contract"
    assert result["diagnostic_code"] == "module_binding_rejected"
    assert set(result) == {
        "schema", "status", "reason_code", "evidence_level", "scope_state", "authority",
        "activation", "control", "child", "diagnostic_phase", "diagnostic_category",
        "diagnostic_code",
    }


def test_scope_reread_failure_is_distinct_and_finite():
    call = _load_call()
    v3_raw, v4_raw, v3, v4 = _production_loaded_v4(call)
    scope, api = _sourcefake_v4_scope(v4, v3_raw, v4_raw)
    try:
        assert scope.read_held(V3_PATH, V3_SHA256, 256 * 1024) == v3_raw
        assert scope.read_held(V4_PATH, V4_SHA256, 256 * 1024) == v4_raw
        assert api.read_count >= 4
        call.bind_v4_module_to_held_source(
            v4, {"v3": v3_raw, "v4": v4_raw}, scope=scope
        )
        result = call.prepare_root_source_verification(
            scope, v4, b"{}", {"v3": v3_raw, "v4": v4_raw}, b"x", requested=True
        )
    finally:
        assert scope.release(0, True) is True
        _remove_retained_scope(v3, scope)

    assert result["diagnostic_phase"] == "scope_reread"
    assert result["diagnostic_category"] == "source_contract"
    assert result["diagnostic_code"] == "scope_reread_rejected"
    assert result["reason_code"] == "source_binding_or_preparation_failed"
    assert scope.state == "CLOSED"
    assert api.handles == {}
    assert "scope" not in result


def test_unexpected_module_binding_error_is_stage_only_and_never_serialized():
    call = _load_call()
    v3_raw = _read_public(V3_PATH)
    v4_raw = _read_public(V4_PATH)
    result = call.prepare_root_source_verification(
        object(), object(), b"{}", {"v3": v3_raw, "v4": v4_raw}, b"x", requested=True
    )

    assert result["diagnostic_phase"] == "module_binding"
    assert result["diagnostic_category"] == "unexpected"
    assert result["diagnostic_code"] == "unexpected_exception"
    assert set(result) == {
        "schema", "status", "reason_code", "evidence_level", "scope_state", "authority",
        "activation", "control", "child", "diagnostic_phase", "diagnostic_category",
        "diagnostic_code",
    }
    assert all("object" not in str(value) for value in result.values())


def test_default_call_remains_closed_without_touching_arguments():
    call = _load_call()

    class NoTouch:
        def __getattribute__(self, _name):
            raise AssertionError("closed_call_touched_argument")

    result = call.prepare_root_source_verification(NoTouch(), NoTouch(), NoTouch(), NoTouch(), NoTouch())
    assert result["schema"] == call.SCHEMA
    assert result["status"] == "BLOCKED"
    assert result["diagnostic_phase"] == "input_shape"
    assert result["diagnostic_category"] == "source_contract"
    assert result["diagnostic_code"] == "input_rejected"


def test_failure_projection_values_are_closed_enumerations():
    call = _load_call()
    assert call._failure_projection("raw/path", "credential", "private text") == {
        "diagnostic_phase": "result_check",
        "diagnostic_category": "unexpected",
        "diagnostic_code": "unexpected_exception",
    }
