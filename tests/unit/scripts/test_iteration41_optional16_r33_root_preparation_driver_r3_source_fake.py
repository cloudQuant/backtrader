"""Sourcefake contracts for the additive R3 Root preparation driver.

The composition case runs the default driver path and exact Call R3 source,
while replacing only the physical scope bootstrap and terminal R1 preparation
leaf. Its successful receipt is a sourcefake projection; it does not prove an
actual scope close, profiler proof, preparation, installer, worker, or
activation.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(r"D:\source_code\backtrader")
DRIVER_PATH = ROOT / "scripts/iteration41_optional16_r33_root_preparation_driver_r3.py"
DRIVER_SHA256 = "4185a4854c04f5d6adef4741be850d3736c62af749b2180008dc6992faf5ecbe"
CALL_PATH = ROOT / "scripts/iteration41_optional16_r33_root_preparation_call_r3.py"
CALL_SHA256 = "fe3a4548ff05bce6beb3b504b9dcbc71fa9a5e5e91be0f154882a9bb50c1b324"
PREPARATION_PATH = ROOT / "scripts/iteration41_optional16_r33_root_preparation_r1.py"
PREPARATION_SHA256 = "a626001a9f80bee26996a0fd3effb0e670c96ffd7a167ba154d23521eca64aa4"
V3_PATH = ROOT / "scripts/iteration41_root_held_source_scope_v3.py"
V3_SHA256 = "f3270495d3ddb046f8617d689510d4ae6ee700d639e0db769c518a15099a7677"
V4_PATH = ROOT / "scripts/iteration41_root_held_source_scope_v4.py"
V4_SHA256 = "138c86e21de773822eceac07034e113e0adb5ea5d9056fcc16cee10a75c0e830"
def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read(path: Path) -> bytes:
    raw = path.read_bytes()
    assert type(raw) is bytes and raw
    return raw


def _load_driver():
    raw = _read(DRIVER_PATH)
    assert _sha(raw) == DRIVER_SHA256
    spec = importlib.util.spec_from_file_location("optional16_root_preparation_driver_r3_test", DRIVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _successful_call_receipt(call_schema: str, scope_state: str = "CLOSED"):
    return {
        "schema": call_schema,
        "status": "PREPARATION_VERIFIED_NO_AUTHORITY",
        "reason_code": "held_source_preparation_complete",
        "evidence_level": "ROOT_HELD_PREPARATION_ONLY",
        "public_rows": 582,
        "full_union_rows": 620,
        "software_rows": 5,
        "held_rows": 625,
        "profiler_modules": 3,
        "boundary": "before_r5_worker_installer",
        "scope_state": scope_state,
        "authority": "NONE",
        "activation": "NOT_ENTERED",
        "control": "NOT_ENTERED",
        "child": "NOT_ENTERED",
        "diagnostic_phase": "result_check",
        "diagnostic_category": "none",
        "diagnostic_code": "preparation_complete",
    }


def _sourcefake_scope(v4, v3, v3_raw: bytes, v4_raw: bytes):
    """Create the exact V4 type with sourcefake OS leaves for this test only."""
    private = types.ModuleType("_driver_r3_fake_private")
    private._api = lambda: None
    private._Win32 = type("FakeWin32", (), {})
    private._path = Path
    cli = types.ModuleType("_driver_r3_fake_cli")
    cli._locked_readonly_file = lambda *_args, **_kwargs: None
    cli._locked_file_identity = lambda *_args, **_kwargs: None
    cli._read_bounded_handle = lambda *_args, **_kwargs: b""

    original = v3._bootstrap_fixed_helpers
    v3._bootstrap_fixed_helpers = lambda: (private, cli, b"", b"", object(), object())
    try:
        scope = v4.RootHeldScopeV4(enabled=True)
    finally:
        v3._bootstrap_fixed_helpers = original

    scope._sourcefake_enter(object(), v3._SOURCE_FAKE_TOKEN)
    raw_by_handle = {}
    identity_by_handle = {}
    for logical, path, raw in (("held-v3", V3_PATH, v3_raw), ("held-v4", V4_PATH, v4_raw)):
        key = v3._path_key(path)
        handle = ("scope-file", logical)
        identity = ("scope-id", logical)
        row = v3._HeldRow(key, logical, path, _sha(raw), 256 * 1024, "public")
        row.handle = handle
        row.identity = identity
        row.size = len(raw)
        scope._rows[key] = row
        scope._logical[logical.casefold()] = key
        scope._bytes[key] = raw
        raw_by_handle[handle] = raw
        identity_by_handle[handle] = identity

    def fake_identity(handle, *, directory=False, allow_hardlinks=False):
        assert directory is False and allow_hardlinks is False
        return identity_by_handle[handle]

    def fake_size(handle):
        return len(raw_by_handle[handle])

    def fake_seek(_handle):
        return None

    def fake_read(_api, handle, maximum):
        raw = raw_by_handle[handle]
        assert len(raw) <= maximum
        return raw

    scope._identity = fake_identity
    scope._file_size = fake_size
    scope._seek_start = fake_seek
    scope._bounded_reader = fake_read
    return scope


def test_request_defaults_closed_without_public_reads(monkeypatch):
    driver = _load_driver()
    monkeypatch.setattr(
        driver,
        "_read_public_source",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected read")),
    )

    result = driver.prepare_root_held_source_gate()

    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "preparation_request_required"
    assert result["scope_state"] == "NOT_OPENED"
    assert result["diagnostic_phase"] == "root_preflight"
    assert driver._ATTEMPT_STARTED is False
    assert driver._RETAINED_ATTEMPTS == []


def test_one_shot_rejection_preserves_retained_state(monkeypatch):
    driver = _load_driver()
    monkeypatch.setattr(driver, "_ATTEMPT_STARTED", True)
    scope = types.SimpleNamespace(state="RETAINED")
    monkeypatch.setattr(driver, "_RETAINED_ATTEMPTS", [(None, None, None, None, scope)])

    result = driver.prepare_root_held_source_gate(requested=True)

    assert result["status"] == "BLOCKED_RETAINED"
    assert result["reason_code"] == "one_shot_attempt_already_used"
    assert result["scope_state"] == "RETAINED"
    assert result["retry"] == "DO_NOT_RETRY_IN_THIS_PROCESS"
    assert driver._RETAINED_ATTEMPTS[-1][4] is scope


def test_fixed_payload_uses_pinned_public_sources_only():
    driver = _load_driver()
    payload_raw, loaded = driver._build_payload()

    assert type(payload_raw) is bytes
    assert 0 < len(payload_raw) <= driver.MAX_PAYLOAD_BYTES
    assert len(loaded) == 3
    r5, invoke, whole = loaded
    assert r5.__verified_source_sha256__ == driver.R5_SHA256
    assert invoke.__verified_source_sha256__ == driver.R27_INVOKE_SHA256
    assert whole.__verified_source_sha256__ == driver.R27_WHOLE_SHA256
    assert r5.ROOT_ACTUAL_ENABLED is False
    assert invoke.ROOT_ACTUAL_ENABLED is False
    assert whole.ROOT_ACTUAL_ENABLED is False
    assert whole.ROOT_NATIVE_ENABLED is False
    assert b"parent_deadline_monotonic" in payload_raw


def test_call_r2_receipt_schema_is_rejected():
    driver = _load_driver()
    receipt = _successful_call_receipt(
        "iteration41.optional16.r33.root-preparation-call.r2"
    )

    assert driver._verified_receipt(receipt, types.SimpleNamespace(state="CLOSED")) is False


def test_success_receipt_requires_exact_rows_and_diagnostic_fields():
    driver = _load_driver()
    receipt = _successful_call_receipt(driver.CALL_SCHEMA)
    assert driver._verified_receipt(receipt, types.SimpleNamespace(state="CLOSED")) is True
    assert driver._verified_receipt(receipt, types.SimpleNamespace(state="OPEN")) is False

    for field, value in (
        ("public_rows", 581),
        ("software_rows", 4),
        ("profiler_modules", 2),
        ("boundary", "worker_installer_entered"),
        ("authority", "ROOT"),
        ("child", "ENTERED"),
        ("diagnostic_phase", "raw/path"),
        ("diagnostic_category", "credential"),
        ("diagnostic_code", "private text"),
    ):
        changed = dict(receipt)
        changed[field] = value
        assert driver._verified_receipt(changed, types.SimpleNamespace(state="CLOSED")) is False

    extra = dict(receipt, raw_payload="forbidden")
    assert driver._verified_receipt(extra, types.SimpleNamespace(state="CLOSED")) is False


def test_finite_call_diagnostics_are_projected_and_unknowns_are_rejected():
    driver = _load_driver()
    projected = driver._diagnostic_from_receipt(
        {
            "diagnostic_phase": "module_binding",
            "diagnostic_category": "source_contract",
            "diagnostic_code": "module_binding_rejected",
            "detail": "private input must not be copied",
        }
    )
    assert projected == {
        "diagnostic_phase": "module_binding",
        "diagnostic_category": "source_contract",
        "diagnostic_code": "module_binding_rejected",
    }
    assert driver._diagnostic_from_receipt({"diagnostic_phase": "raw path"}) == {
        "diagnostic_phase": "root_call_adapter",
        "diagnostic_category": "unexpected",
        "diagnostic_code": "unexpected_exception",
    }


def _expand_scope_with_held_sources(scope, v3, sources):
    raw_by_handle = {}
    identity_by_handle = {}
    for row in tuple(scope._rows.values()):
        raw_by_handle[row.handle] = scope._bytes[row.key]
        identity_by_handle[row.handle] = row.identity

    for logical, path, digest, raw in sources:
        key = v3._path_key(path)
        row = v3._HeldRow(key, logical, path, digest, 256 * 1024, "public")
        row.handle = ("sourcefake-composition", logical)
        row.identity = ("sourcefake-identity", logical)
        row.size = len(raw)
        scope._rows[key] = row
        scope._logical[logical.casefold()] = key
        scope._bytes[key] = raw
        raw_by_handle[row.handle] = raw
        identity_by_handle[row.handle] = row.identity

    def fake_identity(handle, *, directory=False, allow_hardlinks=False):
        assert directory is False and allow_hardlinks is False
        return identity_by_handle[handle]

    def fake_size(handle):
        return len(raw_by_handle[handle])

    def fake_seek(_handle):
        return None

    def fake_read(_api, handle, maximum):
        raw = raw_by_handle[handle]
        assert len(raw) <= maximum
        return raw

    scope._identity = fake_identity
    scope._file_size = fake_size
    scope._seek_start = fake_seek
    scope._bounded_reader = fake_read


def test_default_driver_composes_with_exact_call_r3_and_sourcefake_leaves(monkeypatch):
    driver = _load_driver()
    payload_raw, loaded = driver._build_payload()
    if not driver._root_runtime_matches(loaded[1]):
        pytest.skip("fixed Root runtime is required for the default driver path")

    prep_raw = _read(PREPARATION_PATH)
    call_raw = _read(CALL_PATH)
    v3_raw = _read(V3_PATH)
    v4_raw = _read(V4_PATH)
    assert _sha(prep_raw) == PREPARATION_SHA256
    assert _sha(call_raw) == CALL_SHA256
    assert _sha(v3_raw) == V3_SHA256
    assert _sha(v4_raw) == V4_SHA256
    assert len(payload_raw) > 0

    monkeypatch.setattr(driver, "_ATTEMPT_STARTED", False)
    monkeypatch.setattr(driver, "_RETAINED_ATTEMPTS", [])
    monkeypatch.setattr(driver, "_OWNER_THREAD", None)
    original_load = driver._load_exact_public_module
    retained = {}
    helper_call_count = []

    def fake_scope_bootstrap(entry, v4):
        v3 = v4._V3_MODULE
        scope = _sourcefake_scope(v4, v3, v3_raw, v4_raw)
        # The sourcefake token creates this exact V4 type using fake file/API
        # leaves. The False flag only projects the production guard branch;
        # it does not turn the sourcefake scope into production custody.
        scope.test_only = False
        _expand_scope_with_held_sources(
            scope,
            v3,
            (
                ("held-preparation-r1", ROOT / driver.PREPARATION_REL, driver.PREPARATION_SHA256, prep_raw),
                ("held-call-r3", ROOT / driver.CALL_REL, driver.CALL_SHA256, call_raw),
            ),
        )
        retained["scope"] = scope
        retained["v3"] = v3
        return scope

    def fake_preparation_leaf(scope, _v4, _payload, *, requested=False):
        assert requested is True
        assert scope is retained["scope"]
        assert scope.state == "OPEN" and scope.test_only is False
        helper_call_count.append(scope)
        # This substitutes the terminal R1 preparation/close boundary. The
        # full map/profiler work and native postverify are intentionally not
        # claimed by this fixture.
        scope._state = "CLOSED"
        retained["v3"]._forget_scope(scope)
        return {
            "status": "PREPARATION_VERIFIED_NO_AUTHORITY",
            "scope_state": "CLOSED",
            "public_rows": 582,
            "full_union_rows": 620,
            "software_rows": 5,
            "held_rows": 625,
            "profiler_modules": 3,
            "boundary": "before_r5_worker_installer",
        }

    def load_with_sourcefake_leaves(relative, digest, raw, name):
        module = original_load(relative, digest, raw, name)
        if relative == driver.ENTRY_REL:
            module._bootstrap_scope = lambda v4, _payload: fake_scope_bootstrap(module, v4)
        elif relative == driver.CALL_REL:
            exact_prepare = module.prepare_root_source_verification
            assert exact_prepare.__globals__ is module.__dict__
            assert exact_prepare.__code__.co_filename == str(ROOT / driver.CALL_REL)
            helper_loader = module._load_pinned_preparation_helper

            def load_pinned_helper_with_terminal_fake(held_raw):
                helper = helper_loader(held_raw)
                assert helper.__verified_source_sha256__ == PREPARATION_SHA256
                actual_prepare = helper.prepare_root_source_verification
                assert actual_prepare.__globals__ is helper.__dict__
                assert actual_prepare.__code__.co_filename == str(PREPARATION_PATH)
                helper.prepare_root_source_verification = fake_preparation_leaf
                retained["call_module"] = module
                retained["call_prepare"] = exact_prepare
                retained["helper_module"] = helper
                retained["helper_prepare_source"] = actual_prepare
                return helper

            module._load_pinned_preparation_helper = load_pinned_helper_with_terminal_fake
        return module

    monkeypatch.setattr(driver, "_load_exact_public_module", load_with_sourcefake_leaves)
    result = driver.prepare_root_held_source_gate(requested=True)

    assert result["schema"] == driver.SCHEMA
    assert result["status"] == "PREPARATION_VERIFIED_NO_AUTHORITY"
    assert result["boundary"] == "before_r5_worker_installer"
    assert result["authority"] == "NONE"
    assert result["installer"] == result["worker"] == result["activation"] == "NOT_ENTERED"
    assert driver._ATTEMPT_STARTED is True
    assert driver._RETAINED_ATTEMPTS == []
    assert helper_call_count == [retained["scope"]]
    assert retained["scope"].state == "CLOSED"
    assert retained["scope"].test_only is False
    assert retained["scope"] not in retained["v3"]._RETAINED_SCOPES
    assert retained["call_module"].__verified_source_sha256__ == CALL_SHA256
    assert retained["call_prepare"].__globals__ is retained["call_module"].__dict__
    assert retained["call_prepare"].__code__.co_filename == str(CALL_PATH)
    assert retained["helper_module"].__verified_source_sha256__ == PREPARATION_SHA256
    assert retained["helper_prepare_source"].__globals__ is retained["helper_module"].__dict__
    assert retained["helper_prepare_source"].__code__.co_filename == str(PREPARATION_PATH)
