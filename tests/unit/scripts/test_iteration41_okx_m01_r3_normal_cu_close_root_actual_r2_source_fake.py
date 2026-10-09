"""Source-fake boundaries for the Root-only OKX R3 normal-close wrapper."""

from __future__ import annotations

import ast
import contextlib
import hashlib
import json
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[3]
CALLER_PATH = ROOT / ".codex-tmp/okx_m01_protected_rebind_r3_root_actual_candidate_20261009.py"
CALLER_PIN = (55093, "f80890de30021dc9751a439a247c0549afca7303fb13f8f8bb27019e6c193fd6")
WRAPPER_PATH = ROOT / ".codex-tmp/okx_m01_r3_normal_cu_close_root_actual_r2_20261009.py"
WRAPPER_PIN = (36419, "e314606fce79a5c536749c16d8cc2b446a5fc01db72cea9a154b4a08d8058d3e")
HELPER_PATH = ROOT / ".codex-tmp/okx_m01_r3_normal_cu_close_helper_r2_20261009.py"
HELPER_PIN = (19399, "01a51406d2b54abb116b70e93111e741beaa8f3ada54f15e3b5c67c684c59072")


def _read_pinned(path: Path, size: int | None = None, digest: str | None = None) -> bytes:
    info = path.lstat()
    assert info.st_size <= 2 * 1024 * 1024
    raw = path.read_bytes()
    assert len(raw) == info.st_size
    if size is not None:
        assert len(raw) == size
    if digest is not None:
        assert hashlib.sha256(raw).hexdigest() == digest
    return raw


def _load_wrapper(monkeypatch):
    raw = _read_pinned(WRAPPER_PATH, *WRAPPER_PIN)
    module = types.ModuleType("_okx_m01_r3_normal_cu_close_root_actual_r2_20261009")
    module.__file__ = str(WRAPPER_PATH)
    module.__package__ = ""
    module.__cached__ = None
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(raw, str(WRAPPER_PATH), "exec", dont_inherit=True), module.__dict__)
    return module, raw, hashlib.sha256(raw).hexdigest()


def _load_caller_prefix():
    raw = _read_pinned(CALLER_PATH, *CALLER_PIN)
    tree = ast.parse(raw.decode("utf-8", errors="strict"), filename=str(CALLER_PATH))
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
        raise AssertionError("pinned caller has no original-run boundary")
    namespace = {
        "__name__": "_okx_m01_r3_root_caller_prefix_fake",
        "__file__": str(CALLER_PATH),
        "__package__": "",
    }
    exec(compile(ast.Module(body=prefix, type_ignores=tree.type_ignores), str(CALLER_PATH), "exec", dont_inherit=True), namespace)
    return raw, namespace


def _public_pins(wrapper, caller_raw):
    map_raw = _read_pinned(ROOT / wrapper.MAP_RELATIVE, wrapper.MAP_SIZE, wrapper.MAP_SHA256)
    source_pins = json.loads(map_raw.decode("utf-8", errors="strict"))["source_pins"]
    pins = dict(source_pins)
    pins.update({path: value[1] for path, value in wrapper.SUPPORT_PINS.items()})
    caller_relative = CALLER_PATH.relative_to(ROOT).as_posix()
    pins[caller_relative] = hashlib.sha256(caller_raw).hexdigest()
    assert len(pins) == 33
    return pins


def _make_fixture(tmp_path, monkeypatch):
    wrapper, wrapper_raw, wrapper_sha = _load_wrapper(monkeypatch)
    helper_raw = _read_pinned(HELPER_PATH, *HELPER_PIN)
    caller_raw, caller = _load_caller_prefix()
    pins = _public_pins(wrapper, caller_raw)
    public_raw = {}
    for relative, digest in pins.items():
        value = _read_pinned(ROOT / Path(relative))
        assert hashlib.sha256(value).hexdigest() == digest
        public_raw[str(ROOT / Path(relative))] = value

    cu_path = tmp_path / "synthetic-root-public-custody-v2.py"
    cu_raw = (
        "from contextlib import contextmanager\n"
        "@contextmanager\n"
        "def held_public_sources(pins, software):\n"
        "    tag, raw = _scope_maps.pop(0)\n"
        "    _scope_requests.append((dict(pins), software))\n"
        "    _events.append(tag + ':enter')\n"
        "    try:\n"
        "        yield _private, _cli, raw\n"
        "    finally:\n"
        "        _events.append(tag + ':normal_postyield')\n"
    ).encode("utf-8")
    cu_path.write_bytes(cu_raw)
    cu_sha = hashlib.sha256(cu_raw).hexdigest()
    # The real CU path remains a source pin. Redirect only Path.resolve for
    # that exact public path so the fake never stats or reads the external CU.
    software = caller["SOFTWARE"]
    external_cu_path = str(wrapper.CU_PATH).replace("/", "\\").lower()
    path_type = type(wrapper.CU_PATH)
    original_resolve = path_type.resolve

    def resolve_without_external_cu(path, strict=False):
        if str(path).replace("/", "\\").lower() == external_cu_path:
            return cu_path
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(path_type, "resolve", resolve_without_external_cu)
    caller["SOFTWARE"] = software
    assert caller["ROOT"] == wrapper.ROOT
    assert caller["MAP_RELATIVE"] == wrapper.MAP_RELATIVE
    assert caller["MAP_SHA256"] == wrapper.MAP_SHA256
    assert caller["MAP_SIZE"] == wrapper.MAP_SIZE
    assert caller["SUPPORT_PINS"] == wrapper.SUPPORT_PINS
    assert caller["SOURCE_MAP_EXPECTED_PATHS"] == wrapper.SOURCE_PATHS

    module_map = {
        name: types.ModuleType(name) for name in (
            "_m01_readonly_monitor_v2",
            "_m01_readonly_monitor_v2.current_types",
            "_m01_readonly_monitor_v2.worker",
            "_certification",
            "_certification.m01_private_monitor_v2",
            "_m01_readonly_monitor_v2.job_supervisor",
            "_m01_readonly_monitor_v3",
            "_m01_readonly_monitor_v3.current_reader",
            "_root_okx_m01_metadata_helper_r2",
            "_root_public_custody_private",
            "_root_public_custody_cli",
        )
    }
    for name, module in module_map.items():
        monkeypatch.setitem(sys.modules, name, module)
    v2 = module_map["_m01_readonly_monitor_v2"]
    current_types = module_map["_m01_readonly_monitor_v2.current_types"]
    worker = module_map["_m01_readonly_monitor_v2.worker"]
    certification = module_map["_certification"]
    contract = module_map["_certification.m01_private_monitor_v2"]
    supervisor = module_map["_m01_readonly_monitor_v2.job_supervisor"]
    v3 = module_map["_m01_readonly_monitor_v3"]
    reader = module_map["_m01_readonly_monitor_v3.current_reader"]
    metadata = module_map["_root_okx_m01_metadata_helper_r2"]
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
    registries = (
        (metadata, "_ORPHANED_CONTEXTS", []),
        (reader, "_ADMISSIONS", {}),
        (reader, "_CONSUMED_ADMISSIONS", set()),
        (reader, "_ORPHANED_SOURCE_ADMISSIONS", []),
        (reader, "_CURRENT_READ_EVIDENCE", {}),
        (reader, "_ROOT_HELPER_RETAINED_CONTEXTS", []),
        (supervisor, "_ORPHANED_RUNTIME_HANDLE_SETS", []),
        (current_types, "_ISSUED", {}),
        (current_types, "_CONSUMED", set()),
    )
    for module, name, value in registries:
        setattr(module, name, value)
    api_type = type("SyntheticPrivateApi", (), {})
    private._Win32 = api_type
    private._API = api_type()

    software_keys = {str(Path(path)) for path in software}
    original_raw = dict(public_raw)
    for key in software_keys:
        original_raw[key] = b"synthetic-software-pin-bytes"
    review_raw = dict(original_raw)
    review_raw[str(ROOT / Path(wrapper.HELPER_RELATIVE))] = helper_raw
    review_raw[str(ROOT / Path(wrapper.WRAPPER_RELATIVE))] = wrapper_raw

    cu = types.ModuleType(wrapper.CU_NAME)
    cu.__file__ = str(cu_path)
    cu.__package__ = ""
    cu.__cached__ = None
    events = []
    requests = []
    cu.__dict__.update(
        _private=private,
        _cli=cli,
        _scope_maps=[("original", original_raw), ("review", review_raw)],
        _scope_requests=requests,
        _events=events,
    )
    exec(compile(cu_raw, str(cu_path), "exec", dont_inherit=True), cu.__dict__)
    monkeypatch.setitem(sys.modules, wrapper.CU_NAME, cu)
    original_scope = cu.held_public_sources({}, software)
    original_held = original_scope.__enter__()
    cu_binding = caller["bind_module"](cu, cu_raw, cu_path, wrapper.CU_NAME)
    caller["verify_binding"](cu_binding)
    state = caller["ROOT_STATE"]
    state.update(
        scope=original_scope,
        held=original_held,
        cu=cu,
        private=private,
        raw=original_raw,
        cli_module=cli,
        reader=reader,
        helper=metadata,
        modules=tuple(module_map[name] for name in module_map),
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
    return (
        wrapper,
        wrapper_raw,
        wrapper_sha,
        caller,
        state,
        result,
        original_scope,
        events,
        requests,
        review_raw,
        module_map,
        registries,
    )


def test_root_wrapper_closes_only_the_original_scope_once_and_preserves_result(tmp_path, monkeypatch):
    (
        wrapper, wrapper_raw, wrapper_sha, caller, state, result, original_scope,
        events, requests, review_raw, module_map, registries,
    ) = _make_fixture(tmp_path, monkeypatch)
    original_state = wrapper._state_snapshot(state)
    original_result = wrapper._result_snapshot(result)
    original_raw = tuple((key, id(value)) for key, value in state["raw"].items())
    original_modules = tuple((name, module) for name, module in module_map.items())
    original_registries = tuple(
        (module, name, value, id(value), type(value)) for module, name, value in registries
    )
    report = wrapper.invoke(caller, wrapper, wrapper_raw, len(wrapper_raw), wrapper_sha)

    assert report["status"] == "ROOT_REVIEWED_NORMAL_CLOSE_RETURNED", report
    assert report["phase"] == "complete"
    assert report["normal_close_invocation_count"] == 1
    assert report["original_scope_normal_close_confirmed"] is True
    assert report["review_scope_normal_close_confirmed"] is True, report
    assert report["original_result_unchanged"] is True
    assert report["original_maps_and_state_preserved"] is True
    assert report["host_exit_permitted"] is False
    assert report["metadata_or_admission_call"] is False
    assert report["provider_call"] is report["account_call"] is False
    assert report["formal_m01_pass_count"] == 0
    assert original_scope.gen.gi_frame is None
    assert events == ["original:enter", "review:enter", "original:normal_postyield", "review:normal_postyield"]
    assert len(requests) == 2
    assert len(requests[1][0]) == 35
    assert requests[1][1] is caller["SOFTWARE"]
    assert len(review_raw) == 38
    assert wrapper._state_snapshot(state) == original_state
    assert wrapper._result_snapshot(result) == original_result
    assert tuple((key, id(value)) for key, value in state["raw"].items()) == original_raw
    assert tuple((name, sys.modules[name]) for name, _ in original_modules) == original_modules
    assert tuple(
        (module, name, getattr(module, name), id(getattr(module, name)), type(getattr(module, name)))
        for module, name, _, _, _ in original_registries
    ) == original_registries
    assert all(type(value) is expected_type and len(value) == 0 for _, _, value, _, expected_type in original_registries)
    assert wrapper.HELPER_NAME not in sys.modules

    second = wrapper.invoke(caller, wrapper, wrapper_raw, len(wrapper_raw), wrapper_sha)
    assert second["status"] == "BLOCKED"
    assert second["normal_close_invocation_count"] == 0
    assert events.count("original:normal_postyield") == 1


@pytest.mark.parametrize("tamper", ("filename", "nested_constant"))
def test_root_wrapper_blocks_tampered_original_caller_before_close(tmp_path, monkeypatch, tamper):
    (
        wrapper, wrapper_raw, wrapper_sha, caller, _state, _result, original_scope,
        events, _requests, _review_raw, _module_map, _registries,
    ) = _make_fixture(tmp_path, monkeypatch)
    original = caller["run"]
    code = original.__code__
    if tamper == "filename":
        original.__code__ = code.replace(co_filename=code.co_filename + ".tampered")
    else:
        constants = list(code.co_consts)
        for index, value in enumerate(constants):
            if type(value) is str:
                constants[index] = value + "_tampered"
                break
        else:
            raise AssertionError("caller run has no direct string constant")
        original.__code__ = code.replace(co_consts=tuple(constants))

    report = wrapper.invoke(caller, wrapper, wrapper_raw, len(wrapper_raw), wrapper_sha)

    assert report["status"] == "BLOCKED"
    assert report["normal_close_invocation_count"] == 0
    assert report["original_scope_normal_close_confirmed"] is False
    assert report["review_scope_normal_close_confirmed"] is True, report
    assert original_scope.gen.gi_frame is not None
    assert events == ["original:enter", "review:enter", "review:normal_postyield"]
    assert wrapper.HELPER_NAME not in sys.modules
