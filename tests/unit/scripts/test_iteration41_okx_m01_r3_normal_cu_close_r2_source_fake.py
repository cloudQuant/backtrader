"""Faithful public source fakes for the additive OKX M01 R3 close helper."""

from __future__ import annotations

import ast
import contextlib
import hashlib
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / ".codex-tmp" / "okx_m01_r3_normal_cu_close_helper_r2_20261009.py"
HELPER_SIZE = 19399
HELPER_SHA256 = "01a51406d2b54abb116b70e93111e741beaa8f3ada54f15e3b5c67c684c59072"
CALLER = ROOT / ".codex-tmp" / "okx_m01_protected_rebind_r3_root_actual_candidate_20261009.py"
CALLER_SIZE = 55093
CALLER_SHA256 = "f80890de30021dc9751a439a247c0549afca7303fb13f8f8bb27019e6c193fd6"


def _read_pinned(path: Path, size: int, digest: str) -> bytes:
    info = path.lstat()
    assert info.st_size == size
    assert info.st_size <= 2 * 1024 * 1024
    with path.open("rb") as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    assert len(raw) == size
    assert hashlib.sha256(raw).hexdigest() == digest
    return raw


def _load_helper():
    raw = _read_pinned(HELPER, HELPER_SIZE, HELPER_SHA256)
    namespace = {"__name__": "_m01_cu_close_r2_source_fake", "__file__": str(HELPER)}
    exec(compile(raw, str(HELPER), "exec", dont_inherit=True), namespace)
    return namespace


def _load_caller_prefix():
    raw = _read_pinned(CALLER, CALLER_SIZE, CALLER_SHA256)
    tree = ast.parse(raw.decode("utf-8", errors="strict"), filename=str(CALLER))
    prefix = []
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "ROOT_RESULT"
            and isinstance(node.value, ast.Constant)
            and node.value.value is None
        ):
            break
        prefix.append(node)
    else:
        raise AssertionError("pinned caller has no actual-run boundary")
    module = ast.Module(body=prefix, type_ignores=tree.type_ignores)
    namespace = {
        "__name__": "_okx_m01_r3_root_caller_prefix_fake",
        "__file__": str(CALLER),
        "__package__": "",
    }
    exec(compile(module, str(CALLER), "exec", dont_inherit=True), namespace)
    return raw, namespace


def _make_module(monkeypatch, name: str):
    module = types.ModuleType(name)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _make_full_close_fixture(tmp_path, monkeypatch):
    helper = _load_helper()
    caller_raw, caller = _load_caller_prefix()

    # The close helper's source binding path is redirected only within this
    # synthetic test so no external CU source or binary is opened or read.
    cu_path = tmp_path / "synthetic-root-public-custody.py"
    cu_raw = (
        "from contextlib import contextmanager\n"
        "@contextmanager\n"
        "def held_public_sources(*args, **kwargs):\n"
        "    try:\n"
        "        yield _private, _cli, _raw\n"
        "    finally:\n"
        "        _events.append('normal_postyield')\n"
    ).encode("utf-8")
    cu_path.write_bytes(cu_raw)
    helper["CU_PATH"] = cu_path

    module_map = {
        name: _make_module(monkeypatch, name) for name in helper["MODULE_NAMES"]
    }
    v2 = module_map["_m01_readonly_monitor_v2"]
    current_types = module_map["_m01_readonly_monitor_v2.current_types"]
    worker = module_map["_m01_readonly_monitor_v2.worker"]
    certification = module_map["_certification"]
    contract = module_map["_certification.m01_private_monitor_v2"]
    supervisor = module_map["_m01_readonly_monitor_v2.job_supervisor"]
    v3 = module_map["_m01_readonly_monitor_v3"]
    reader = module_map["_m01_readonly_monitor_v3.current_reader"]
    metadata_helper = module_map["_root_okx_m01_metadata_helper_r2"]
    private = module_map["_root_public_custody_private"]
    cli = module_map["_root_public_custody_cli"]

    v2.current_types = current_types
    v2.worker = worker
    v2.job_supervisor = supervisor
    certification.m01_private_monitor_v2 = contract
    supervisor.worker = worker
    supervisor.current_types = current_types
    supervisor.contract = contract
    v3.current_reader = reader
    reader.current_types = current_types
    reader.worker = worker
    reader.job_supervisor = supervisor

    empty_registries = (
        (metadata_helper, "_ORPHANED_CONTEXTS", []),
        (reader, "_ADMISSIONS", {}),
        (reader, "_CONSUMED_ADMISSIONS", set()),
        (reader, "_ORPHANED_SOURCE_ADMISSIONS", []),
        (reader, "_CURRENT_READ_EVIDENCE", {}),
        (reader, "_ROOT_HELPER_RETAINED_CONTEXTS", []),
        (supervisor, "_ORPHANED_RUNTIME_HANDLE_SETS", []),
        (current_types, "_ISSUED", {}),
        (current_types, "_CONSUMED", set()),
    )
    for module, name, value in empty_registries:
        setattr(module, name, value)

    api_type = type("SyntheticPrivateApi", (), {})
    private._Win32 = api_type
    private._API = api_type()

    raw_map = {str(CALLER): caller_raw}
    events = []
    cu = types.ModuleType(helper["CU_NAME"])
    cu.__file__ = str(cu_path)
    cu.__package__ = ""
    cu.__cached__ = None
    cu.__dict__.update(_private=private, _cli=cli, _raw=raw_map, _events=events)
    exec(compile(cu_raw, str(cu_path), "exec", dont_inherit=True), cu.__dict__)
    monkeypatch.setitem(sys.modules, helper["CU_NAME"], cu)
    cu_binding = caller["bind_module"](
        cu, cu_raw, cu_path, helper["CU_NAME"]
    )
    caller["verify_binding"](cu_binding)
    scope = cu.held_public_sources({}, {})
    held = scope.__enter__()
    assert held == (private, cli, raw_map)
    assert type(scope) is contextlib._GeneratorContextManager
    assert type(scope.gen) is types.GeneratorType
    assert scope.gen.gi_frame is not None
    assert scope.gen.gi_frame.f_globals is cu.__dict__

    state = caller["ROOT_STATE"]
    state.update(
        scope=scope,
        held=held,
        cu=cu,
        private=private,
        raw=raw_map,
        cli_module=cli,
        reader=reader,
        helper=metadata_helper,
        modules=tuple(module_map[name] for name in helper["MODULE_NAMES"]),
        bindings=(cu_binding,),
        admission=None,
        admission_private_binding=None,
        registries=(),
        bindings_complete=False,
        registry_snapshot_complete=False,
    )
    result = caller["_initial_result"]()
    result.update(
        reason="root_source_binding_failed",
        public_pin_count=33,
        software_pin_count=3,
        source_map_sha256_matches=True,
        cu_source_code_globals_verified=True,
    )
    caller["ROOT_RESULT"] = result
    return helper, caller, state, result, scope, events, module_map, empty_registries


def _mutate_nested_string(code):
    constants = list(code.co_consts)
    for index, value in enumerate(constants):
        if type(value) is types.CodeType:
            changed = _mutate_nested_string(value)
            if changed is not None:
                constants[index] = changed
                return code.replace(co_consts=tuple(constants))
    for index, value in enumerate(constants):
        if type(value) is str:
            constants[index] = value + "_tampered"
            return code.replace(co_consts=tuple(constants))
    return None


def test_full_close_uses_actual_caller_prefix_bindings_and_preserves_original_state(
    tmp_path, monkeypatch
):
    helper, caller, state, result, scope, events, module_map, registries = (
        _make_full_close_fixture(tmp_path, monkeypatch)
    )
    state_before = dict(state)
    result_before = dict(result)
    registry_before = tuple(
        (module, name, value, id(value), type(value)) for module, name, value in registries
    )
    module_links_before = tuple(
        (name, sys.modules[name]) for name in helper["MODULE_NAMES"]
    )
    report = helper["close_original_scope"](caller)

    assert report["status"] == "CU_SCOPE_NORMAL_CLOSE_CONFIRMED"
    assert report["phase"] == "complete"
    assert report["normal_close_called"] is True
    assert report["normal_close_confirmed"] is True
    assert report["uncertainty_references_retained"] is False
    assert report["host_exit_permitted"] is False
    assert report["metadata_helper_invoked"] is False
    assert report["metadata_rebound"] is False
    assert report["fresh_source_admission_released"] is False
    assert report["credentials_read"] is report["provider_call"] is report["account_call"] is False
    assert report["formal_m01_pass_count"] == 0
    assert events == ["normal_postyield"]
    assert scope.gen.gi_frame is None
    assert caller["inspect"].getgeneratorstate(scope.gen) == caller["inspect"].GEN_CLOSED
    assert helper["_ATTEMPTED"] == [scope]
    assert helper["_RETAINED"] == []
    assert state.keys() == state_before.keys()
    assert all(state[key] is value for key, value in state_before.items())
    assert caller["ROOT_RESULT"] is result
    assert result == result_before
    assert (
        tuple((module, name, value, id(value), type(value)) for module, name, value in registries)
        == registry_before
    )
    assert all(
        type(value) is expected_type and len(value) == 0
        for _, _, value, _, expected_type in registry_before
    )
    assert all(sys.modules[name] is module for name, module in module_links_before)
    assert (
        module_map["_m01_readonly_monitor_v2"].worker
        is module_map["_m01_readonly_monitor_v2.worker"]
    )

    second = helper["close_original_scope"](caller)
    assert second["status"] == "BLOCKED"
    assert second["normal_close_called"] is False
    assert helper["_ATTEMPTED"] == [scope]
    assert events == ["normal_postyield"]


@pytest.mark.parametrize("tamper", ("filename", "qualname", "nested_constant"))
def test_run_code_tampering_blocks_before_close(tmp_path, monkeypatch, tamper):
    helper, caller, state, _result, scope, events, _modules, _registries = (
        _make_full_close_fixture(tmp_path, monkeypatch)
    )
    original = caller["run"]
    code = original.__code__
    if tamper == "filename":
        original.__code__ = code.replace(co_filename=code.co_filename + ".tampered")
    elif tamper == "qualname":
        original.__code__ = code.replace(co_qualname=code.co_qualname + ".tampered")
    else:
        changed = _mutate_nested_string(code)
        assert changed is not None
        original.__code__ = changed

    report = helper["close_original_scope"](caller)

    assert report["status"] == "BLOCKED"
    assert report["phase"] == "root_binding"
    assert report["normal_close_called"] is False
    assert report["host_exit_permitted"] is False
    assert scope.gen.gi_frame is not None
    assert caller["inspect"].getgeneratorstate(scope.gen) == caller["inspect"].GEN_SUSPENDED
    assert events == []
    assert helper["_ATTEMPTED"] == []
    assert helper["_RETAINED"]
    assert state["scope"] is scope


