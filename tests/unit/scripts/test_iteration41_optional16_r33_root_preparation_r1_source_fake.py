"""Source-only checks for the bounded Optional16 Root preparation adapter.

This suite reads only the fixed public helper, Entry R2, and V4 source files.
It never reads or fabricates profiler cache bytes and never runs the V4/R29
proof. A passing result establishes the exact source boundary and the closed
test-scope guard only; Root must later run the prepared helper on its real
same-thread held V4 scope to establish profiler proof results.
"""

from __future__ import annotations

import hashlib
import importlib.machinery
from pathlib import Path
import sys
import types

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
HELPER_PATH = REPO_ROOT / "scripts/iteration41_optional16_r33_root_preparation_r1.py"
ENTRY_PATH = REPO_ROOT / "scripts/iteration41_optional16_r33_root_held_entry_r2.py"
V4_PATH = REPO_ROOT / "scripts/iteration41_root_held_source_scope_v4.py"
ENTRY_SHA256 = "80295025d0145893f4f63745182042812284434e4e7e5b4388b89d82623c2ead"
V4_SHA256 = "138c86e21de773822eceac07034e113e0adb5ea5d9056fcc16cee10a75c0e830"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_public(path: Path) -> bytes:
    raw = path.read_bytes()
    assert type(raw) is bytes and raw
    return raw


def _load_module(name: str, path: Path, raw: bytes) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__loader__ = None
    module.__cached__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(path))
    module.__verified_source_sha256__ = _sha(raw)
    exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__, module.__dict__)
    return module


def _load_helper() -> types.ModuleType:
    raw = _read_public(HELPER_PATH)
    return _load_module("iteration41_optional16_r33_preparation_test", HELPER_PATH, raw)


def _recursive_code_names(code: types.CodeType) -> set[str]:
    result = set(code.co_names)
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            result.update(_recursive_code_names(value))
    return result


def test_exact_entry_prefix_contains_r29_and_r5_steps_then_stops_before_installer():
    helper = _load_helper()
    entry_raw = _read_public(ENTRY_PATH)
    assert _sha(entry_raw) == ENTRY_SHA256
    entry = helper._load_entry_module(entry_raw)
    prefix = helper._compile_preinstaller_prefix(entry, entry_raw)

    names = _recursive_code_names(prefix.__code__)
    assert {
        "verify_profiler_module_cache",
        "derive_pinned_r19_active_map",
        "build_full_hold_map",
        "_transform_deferred_scope",
        "_transform_r28_worker_installer",
    } <= names
    assert "install_full_hold_adaptation" not in names
    assert "_r2_main" not in names
    assert "_start" not in names
    assert prefix.__code__.co_filename == str(ENTRY_PATH)
    assert prefix.__code__.co_name == "_prepare_before_worker_installer"


def test_entry_source_mutation_is_rejected_before_prefix_compilation():
    helper = _load_helper()
    entry_raw = bytearray(_read_public(ENTRY_PATH))
    entry_raw[-1] ^= 1
    with pytest.raises(helper.PreparationError, match="entry_source_pin_mismatch"):
        helper._load_entry_module(bytes(entry_raw))


def test_default_call_is_closed_without_touching_a_scope():
    helper = _load_helper()

    class NoTouch:
        def __getattribute__(self, _name):
            raise AssertionError("closed_preparation_touched_scope")

    result = helper.prepare_root_source_verification(NoTouch(), object(), b"not-read")
    assert result == {
        "schema": helper.SCHEMA,
        "status": "BLOCKED",
        "reason_code": "preparation_request_required",
        "evidence_level": "NONE",
    }


def test_real_v4_type_sourcefake_scope_is_rejected_before_any_source_read(monkeypatch):
    helper = _load_helper()
    v4_raw = _read_public(V4_PATH)
    assert _sha(v4_raw) == V4_SHA256
    v4 = _load_module("_iteration41_optional16_r33_entry_v4", V4_PATH, v4_raw)

    private = types.ModuleType("_preparation_test_private")
    private._api = lambda: None
    private._Win32 = type("FakeWin32", (), {})
    cli = types.ModuleType("_preparation_test_cli")
    cli._locked_readonly_file = lambda *_args, **_kwargs: None
    cli._locked_file_identity = lambda *_args, **_kwargs: None
    cli._read_bounded_handle = lambda *_args, **_kwargs: b""
    monkeypatch.setattr(
        v4._V3_MODULE,
        "_bootstrap_fixed_helpers",
        lambda: (private, cli, b"", b"", object(), object()),
    )

    scope = v4.RootHeldScopeV4(enabled=True)
    scope._sourcefake_enter(object(), v4._V3_MODULE._SOURCE_FAKE_TOKEN)
    assert type(scope) is v4.RootHeldScopeV4
    assert scope.test_only is True
    assert scope.state == "OPEN"

    result = helper.prepare_root_source_verification(scope, v4, b"{}", requested=True)
    assert result == {
        "schema": helper.SCHEMA,
        "status": "BLOCKED",
        "reason_code": "production_scope_required",
        "evidence_level": "NONE",
    }
    assert scope.state == "OPEN"
    assert scope.manifest() == {}
    assert scope.release(0, True) is True

