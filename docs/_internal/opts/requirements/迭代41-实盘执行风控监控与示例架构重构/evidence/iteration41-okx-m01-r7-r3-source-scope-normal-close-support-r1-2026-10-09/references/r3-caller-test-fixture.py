"""Source-fake contract tests for the Root-owned M01 lifecycle caller."""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[3]
CALLER_PATH = ROOT / "scripts/iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r3.py"
R7_GATE_TEST_PATH = (
    ROOT / "tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r7.py"
)
CUV2_SOURCE_PATH = ROOT / (
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-cuv2-public-source-snapshot-r1-2026-10-08/cuv2-source.py"
)
CUV2_ORIGIN = Path("D:/temp/iteration41-root-public-custody-v2.py")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


caller = _load_module("_m01_r7_root_caller_r3_source_fake_test", CALLER_PATH)


def _source_module(name: str, path: Path, raw: bytes):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__spec__ = importlib.util.spec_from_file_location(name, path)
    exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    return module


def _load_cuv2_source_module(name: str):
    raw = CUV2_SOURCE_PATH.read_bytes()
    assert len(raw) == caller.CUV2_SOURCE_BYTES
    assert hashlib.sha256(raw).hexdigest() == caller.CUV2_SOURCE_SHA256
    module = types.ModuleType(name)
    module.__file__ = str(CUV2_ORIGIN)
    module.__package__ = ""
    module.__spec__ = importlib.util.spec_from_file_location(name, CUV2_ORIGIN)
    sys.modules[name] = module
    exec(compile(raw, str(CUV2_ORIGIN), "exec", dont_inherit=True), module.__dict__)
    return module, raw


@pytest.fixture
def pinned_source_modules(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("the exact pinned M01 module closure is Windows-only")
    r7_test_raw = R7_GATE_TEST_PATH.read_bytes()
    assert len(r7_test_raw) == caller.GATE_TEST_BYTES
    assert hashlib.sha256(r7_test_raw).hexdigest() == caller.GATE_TEST_SHA256
    patch_path = ROOT / "scripts/iteration41_okx_m01_root_helper_lifecycle_patch_r2.py"
    patch_raw = patch_path.read_bytes()
    assert len(patch_raw) == 13625
    assert hashlib.sha256(patch_raw).hexdigest() == (
        "c53833b20238cb82d491bf7972508a604e56c8ad3158cada7060f9910629a78e"
    )
    fake_test_path = (
        ROOT / "tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r2.py"
    )
    fake_test_raw = fake_test_path.read_bytes()
    assert len(fake_test_raw) == 20224
    assert hashlib.sha256(fake_test_raw).hexdigest() == (
        "d6df3de0af5695d6842c711597dddd998dc3f394144be89d720c851e1c600848"
    )
    gate_tests = _load_module("_m01_r7_gate_test_for_root_caller", R7_GATE_TEST_PATH)
    isolated_venue = tmp_path / "okx_penetration"
    for relative, (expected_size, expected_sha) in gate_tests._ISOLATED_INPUTS.items():
        source_path = gate_tests.VENUE / relative
        raw = source_path.read_bytes()
        assert len(raw) == expected_size
        assert gate_tests.hashlib.sha256(raw).hexdigest() == expected_sha
        destination = isolated_venue / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    _name, reader_relative, reader_sha, reader_size = caller.MODULE_SPECS["reader"]
    reader_source = gate_tests.VENUE / reader_relative.removeprefix(
        "examples/000_live_certification/okx_penetration/"
    )
    reader_raw = reader_source.read_bytes()
    assert len(reader_raw) == reader_size
    assert gate_tests.hashlib.sha256(reader_raw).hexdigest() == reader_sha
    reader_destination = isolated_venue / "_m01_readonly_monitor_v3/current_reader.py"
    reader_destination.parent.mkdir(parents=True, exist_ok=True)
    reader_destination.write_bytes(reader_raw)

    previous_modules = {
        name: module for name, module in sys.modules.items() if gate_tests._is_owned_module(name)
    }
    for name in tuple(sys.modules):
        if gate_tests._is_owned_module(name):
            del sys.modules[name]
    monkeypatch.syspath_prepend(str(isolated_venue))
    monkeypatch.setattr(gate_tests.gate, "VENUE", isolated_venue)
    importlib.invalidate_caches()
    try:
        reader = importlib.import_module("_m01_readonly_monitor_v3.current_reader")
        yield gate_tests, (reader, reader.job_supervisor, reader.worker)
    finally:
        for name in tuple(sys.modules):
            if gate_tests._is_owned_module(name):
                del sys.modules[name]
        sys.modules.update(previous_modules)


def test_source_literal_and_computed_caller_pins_are_checked():
    raw = CALLER_PATH.read_bytes()
    module = _load_module("_m01_r7_caller_literal_probe", CALLER_PATH)
    caller._verify_literal_module_globals(module, raw, frozenset({"_INVOCATION_STARTED"}))
    caller._verify_caller_computed_globals(module, ROOT)

    original = module.GATE_SHA256
    module.GATE_SHA256 = "0" * 64
    try:
        with pytest.raises(caller.CallerError) as raised:
            caller._verify_literal_module_globals(module, raw, frozenset({"_INVOCATION_STARTED"}))
    finally:
        module.GATE_SHA256 = original

    assert raised.value.code == "caller_literal_global_mismatch"


def test_current_source_index_binds_exact_26_rows():
    path = ROOT / caller.SOURCE_INDEX_RELATIVE
    raw = path.read_bytes()
    assert len(raw) == caller.SOURCE_INDEX_BYTES
    assert hashlib.sha256(raw).hexdigest() == caller.SOURCE_INDEX_SHA256
    source_index = json.loads(raw.decode("ascii"))
    assert source_index["runtime_source_count"] == 19
    assert source_index["archive_member_count"] == 26
    rows = caller._verify_source_index_rows(source_index)
    assert rows is source_index["rows"]
    assert len(rows) == 26

    forged = dict(source_index)
    forged["rows"] = [*rows, rows[0]]
    forged["archive_member_count"] = 27
    with pytest.raises(caller.CallerError) as raised:
        caller._verify_source_index_rows(forged)
    assert raised.value.code == "source_index_row_count_invalid"


def test_root_public_pin_set_is_exact_31_and_adds_only_declared_support_sources():
    index_raw = (ROOT / caller.SOURCE_INDEX_RELATIVE).read_bytes()
    assert len(index_raw) == caller.SOURCE_INDEX_BYTES
    assert hashlib.sha256(index_raw).hexdigest() == caller.SOURCE_INDEX_SHA256
    index = json.loads(index_raw.decode("ascii"))
    rows = caller._verify_source_index_rows(index)
    indexed_paths = {row["path"] for row in rows}
    assert len(indexed_paths) == caller.SOURCE_INDEX_ROW_COUNT
    assert caller.CUV2_SOURCE_RELATIVE not in indexed_paths

    expected = caller._expected_public_pin_paths(indexed_paths)
    assert len(expected) == caller.ROOT_PUBLIC_PIN_COUNT == 31
    assert expected - indexed_paths == {
        caller.SOURCE_MAP_RELATIVE,
        caller.SOURCE_INDEX_RELATIVE,
        caller.CUV2_SOURCE_RELATIVE,
        caller.CALLER_RELATIVE,
        caller.CALLER_TEST_RELATIVE,
    }


def test_cuv2_software_source_pin_must_match_bound_public_source():
    software_pins = {
        "C:/anaconda3/python.exe": "1" * 64,
        "C:/anaconda3/python311.dll": "2" * 64,
        caller.CUV2_SOFTWARE_ORIGIN: caller.CUV2_SOURCE_SHA256,
    }
    caller._verify_cuv2_software_pin(software_pins)

    software_pins[caller.CUV2_SOFTWARE_ORIGIN] = "3" * 64
    with pytest.raises(caller.CallerError) as raised:
        caller._verify_cuv2_software_pin(software_pins)
    assert raised.value.code == "cuv2_software_source_pin_mismatch"


def test_source_execution_guard_allows_only_safe_pinned_dataclass_replay_code():
    reader_relative = caller.MODULE_SPECS["reader"][1]
    reader_path = ROOT / reader_relative
    reader_raw = reader_path.read_bytes()
    audit, executed = caller._source_execution_guard({str(reader_path): reader_raw})
    replay_codes = caller._source_dataclass_replay_codes(reader_raw, str(reader_path))
    assert replay_codes

    replay_code = next(iter(replay_codes))
    audit("exec", (replay_code,))
    assert executed == set()

    full_module_code = compile(reader_raw, str(reader_path), "exec", dont_inherit=True)
    audit("exec", (full_module_code,))
    assert executed == {caller._norm(reader_path)}

    arbitrary_same_origin = compile("VALUE = 1\n", str(reader_path), "exec", dont_inherit=True)
    with pytest.raises(caller.CallerError) as raised:
        audit("exec", (arbitrary_same_origin,))
    assert raised.value.code == "pinned_source_code_object_mismatch"


def test_actual_cuv2_source_binds_and_runs_with_fake_file_api_leaves(monkeypatch):
    name = "_cuv2_actual_source_fake_probe"
    module, raw = _load_cuv2_source_module(name)
    try:
        (
            method,
            wrapped,
            method_snapshot,
            wrapped_snapshot,
            function_snapshots,
        ) = caller._bind_cuv2_method(module, CUV2_ORIGIN, raw, caller.ROOT)
        public_values = {"scripts/fake_public.py": b"fixed public source"}
        software_values = {
            key: ("synthetic software leaf:" + key).encode("ascii")
            for key in caller.SOFTWARE_PIN_KEYS
        }
        path_values = {
            caller._norm(caller.ROOT / relative): value for relative, value in public_values.items()
        }
        path_values.update({caller._norm(key): value for key, value in software_values.items()})
        public_pins = {
            relative: hashlib.sha256(value).hexdigest() for relative, value in public_values.items()
        }
        software_pins = {
            path: hashlib.sha256(value).hexdigest() for path, value in software_values.items()
        }
        fake_events = []

        @contextlib.contextmanager
        def fake_opened(path, **kwargs):
            fake_events.append("directory_open")
            yield object()

        @contextlib.contextmanager
        def fake_locked_readonly_file(path, _private, _api, **kwargs):
            key = caller._norm(path)
            handle = types.SimpleNamespace(key=key, identity=object())
            fake_events.append("file_lock")
            yield handle, handle.identity

        def fake_read_bounded_handle(_api, handle, _maximum):
            return path_values[handle.key]

        def fake_locked_file_identity(_api, handle, _private, **kwargs):
            return handle.identity

        fake_api = types.SimpleNamespace(opened=fake_opened)
        fake_private = types.SimpleNamespace(_api=lambda: fake_api)
        fake_cli = types.SimpleNamespace(
            _locked_readonly_file=fake_locked_readonly_file,
            _read_bounded_handle=fake_read_bounded_handle,
            _locked_file_identity=fake_locked_file_identity,
        )
        original_load = module.load

        def fake_load(_relative, _pin, name):
            return fake_private if name == "_root_public_custody_private" else fake_cli

        monkeypatch.setattr(module, "load", fake_load)

        def fake_path_read_bytes(path):
            return path_values[caller._norm(path)]

        monkeypatch.setattr(Path, "read_bytes", fake_path_read_bytes)
        scope = method(public_pins, software_pins)
        generator, globals_dict, held = caller._enter_cuv2_scope(scope, wrapped, module)
        assert globals_dict is module.__dict__
        assert generator.gi_frame.f_globals is module.__dict__
        assert type(held) is tuple and len(held) == 3
        assert held[0] is fake_private
        assert held[1] is fake_cli
        assert len(held[2]) == len(public_pins) + len(software_pins)
        assert fake_events
        monkeypatch.setattr(module, "load", original_load)

        state = {"scope_exit_attempted": False, "scope_exit_confirmed": False}
        result = {}
        caller._close_scope_if_clean(
            scope,
            generator,
            globals_dict,
            state,
            result,
            clean_facts=True,
        )
        assert result["scope_exit_confirmed"] is True
        assert generator.gi_frame is None
        assert caller._function_binding_unchanged(method, method_snapshot)
        assert caller._function_binding_unchanged(wrapped, wrapped_snapshot)
        assert caller._cuv2_function_bindings_unchanged(module, function_snapshots)
    finally:
        sys.modules.pop(name, None)


def test_cuv2_binder_rejects_same_origin_same_globals_changed_generator_code():
    name = "_cuv2_altered_actual_source_fake_probe"
    module, raw = _load_cuv2_source_module(name)
    try:
        altered = compile(
            "from contextlib import contextmanager\n"
            "@contextmanager\n"
            "def held_public_sources(public_pins, software_pins):\n"
            "    yield (public_pins, software_pins, {})\n",
            str(CUV2_ORIGIN),
            "exec",
            dont_inherit=True,
        )
        exec(altered, module.__dict__)
        with pytest.raises(caller.CallerError) as raised:
            caller._bind_cuv2_method(module, CUV2_ORIGIN, raw, caller.ROOT)
        assert raised.value.code in {
            "cuv2_method_binding_invalid",
            "source_function_binding_mismatch",
        }
    finally:
        sys.modules.pop(name, None)


def test_cuv2_binder_rejects_actual_generator_with_detached_globals():
    name = "_cuv2_detached_actual_source_fake_probe"
    module, raw = _load_cuv2_source_module(name)
    try:
        foreign_globals = {
            "__name__": name,
            "__builtins__": __builtins__,
            "contextmanager": contextlib.contextmanager,
        }
        exec(
            compile(
                "@contextmanager\n"
                "def held_public_sources(public_pins, software_pins):\n"
                "    yield (public_pins, software_pins, {})\n",
                str(CUV2_ORIGIN),
                "exec",
                dont_inherit=True,
            ),
            foreign_globals,
        )
        module.held_public_sources = foreign_globals["held_public_sources"]
        with pytest.raises(caller.CallerError):
            caller._bind_cuv2_method(module, CUV2_ORIGIN, raw, caller.ROOT)
    finally:
        sys.modules.pop(name, None)


def test_cuv2_binder_rejects_rebound_module_builtins():
    name = "_cuv2_rebound_builtins_source_fake_probe"
    module, raw = _load_cuv2_source_module(name)
    try:
        original = module.__dict__["__builtins__"]
        module.__dict__["__builtins__"] = {}
        with pytest.raises(caller.CallerError) as raised:
            caller._bind_cuv2_method(module, CUV2_ORIGIN, raw, caller.ROOT)
        assert raised.value.code == "cuv2_import_binding_invalid"
        module.__dict__["__builtins__"] = original
        caller._bind_cuv2_method(module, CUV2_ORIGIN, raw, caller.ROOT)
    finally:
        sys.modules.pop(name, None)


def test_cuv2_post_binding_check_detects_wrapper_closure_cell_replacement():
    name = "_cuv2_wrapper_closure_source_fake_probe"
    module, raw = _load_cuv2_source_module(name)
    try:
        (
            method,
            _wrapped,
            method_snapshot,
            _wrapped_snapshot,
            function_snapshots,
        ) = caller._bind_cuv2_method(module, CUV2_ORIGIN, raw, caller.ROOT)
        assert method.__closure__ is not None and len(method.__closure__) == 1
        cell = method.__closure__[0]
        original = cell.cell_contents
        replacement = types.FunctionType(original.__code__, original.__globals__, original.__name__)
        replacement.__module__ = original.__module__
        replacement.__qualname__ = original.__qualname__
        cell.cell_contents = replacement
        assert not caller._function_binding_unchanged(method, method_snapshot)
        assert not caller._cuv2_function_bindings_unchanged(module, function_snapshots)
        cell.cell_contents = original
        assert caller._function_binding_unchanged(method, method_snapshot)
        assert caller._cuv2_function_bindings_unchanged(module, function_snapshots)
    finally:
        sys.modules.pop(name, None)


def test_source_gate_snapshot_rejects_same_filename_function_with_foreign_globals(tmp_path):
    origin = tmp_path / "probe.py"
    raw = b"VALUE = 1\ndef read_value():\n    return VALUE\n"
    reference = _source_module("_probe_reference", origin, raw)
    module = types.ModuleType("_probe_actual")
    module.__file__ = str(origin)
    module.__package__ = ""
    module.__spec__ = importlib.util.spec_from_file_location(module.__name__, origin)
    module.VALUE = reference.VALUE
    module.read_value = types.FunctionType(reference.read_value.__code__, {"VALUE": 1})
    module.read_value.__module__ = module.__name__
    module.read_value.__qualname__ = "read_value"

    with pytest.raises(caller.CallerError) as raised:
        caller._gate_module_snapshot(module, raw, str(origin))

    assert raised.value.code == "source_function_binding_mismatch"


def test_gate_snapshot_detects_global_and_descriptor_drift(tmp_path):
    origin = tmp_path / "descriptor_probe.py"
    raw = (
        b"VALUE = 1\n"
        b"class Record:\n"
        b"    @property\n"
        b"    def value(self):\n"
        b"        return 1\n"
        b"    @classmethod\n"
        b"    def create(cls):\n"
        b"        return cls()\n"
        b"    def read(self):\n"
        b"        return VALUE\n"
    )
    module = _source_module("_descriptor_probe", origin, raw)
    snapshot = caller._gate_module_snapshot(module, raw, str(origin))
    assert caller._gate_snapshot_unchanged(snapshot)

    original_value = module.VALUE
    module.VALUE = 2
    assert not caller._gate_snapshot_unchanged(snapshot)
    module.VALUE = original_value

    original_property = vars(module.Record)["value"]
    module.Record.value = original_property.fget
    assert not caller._gate_snapshot_unchanged(snapshot)
    module.Record.value = original_property

    original_classmethod = vars(module.Record)["create"]
    module.Record.create = original_classmethod.__func__
    assert not caller._gate_snapshot_unchanged(snapshot)
    module.Record.create = original_classmethod
    assert caller._gate_snapshot_unchanged(snapshot)


def test_r7_gate_is_source_bound_from_held_gate_bytes():
    gate_path = ROOT / "scripts/iteration41_okx_m01_root_helper_lifecycle_gate_r7.py"
    source = gate_path.read_bytes()
    assert len(source) == caller.GATE_BYTES
    assert caller._sha(source) == caller.GATE_SHA256
    gate_module = _source_module("_m01_r7_gate_source_fake_probe", gate_path, source)
    snapshot = caller._bind_gate_module(gate_module, source, gate_path)
    assert caller._snapshots_unchanged(gate_module, (snapshot,))

    gate_module._MAX_HELPER_OUTPUT_BYTES += 1
    assert not caller._snapshots_unchanged(gate_module, (snapshot,))


def test_all_five_production_modules_bind_to_held_source_and_detect_transitive_drift(
    pinned_source_modules,
):
    gate_tests, (reader, supervisor, worker) = pinned_source_modules
    modules = {
        "reader": reader,
        "supervisor": supervisor,
        "worker": worker,
        "current_types": reader.current_types,
        "contract": supervisor.contract,
    }
    sources = {
        key: (Path(module.__file__).read_bytes(), Path(module.__file__))
        for key, module in modules.items()
    }
    snapshots = caller._bind_five_modules(gate_tests.gate, modules, sources)
    assert len(snapshots) == 5
    assert caller._snapshots_unchanged(gate_tests.gate, snapshots)

    original = worker.parse_credentials
    exec(
        compile(
            "def parse_credentials(packet):\n    return None\n",
            str(Path(worker.__file__).resolve()),
            "exec",
        ),
        worker.__dict__,
    )
    try:
        assert not caller._snapshots_unchanged(gate_tests.gate, snapshots)
        with pytest.raises(gate_tests.gate.GateError):
            caller._bind_five_modules(gate_tests.gate, modules, sources)
    finally:
        worker.parse_credentials = original

    assert caller._snapshots_unchanged(gate_tests.gate, snapshots)

    target_class = worker._WireReader
    original_property = vars(target_class)["partial_state_clear"]
    target_class.partial_state_clear = original_property.fget
    try:
        assert not caller._snapshots_unchanged(gate_tests.gate, snapshots)
        with pytest.raises(gate_tests.gate.GateError):
            caller._bind_five_modules(gate_tests.gate, modules, sources)
    finally:
        target_class.partial_state_clear = original_property

    assert caller._snapshots_unchanged(gate_tests.gate, snapshots)


def test_registry_preflight_and_identity_reject_nonempty_or_rebound_state():
    module = types.ModuleType("_registry_probe")
    module.registry = []
    original = caller._require_empty_registry(module, "registry")
    references = ((module, "registry", original),)
    assert caller._registries_unchanged(references)

    module.registry = []
    assert not caller._registries_unchanged(references)
    module.registry = original
    original.append(object())
    assert not caller._registries_unchanged(references)
    with pytest.raises(caller.CallerError) as raised:
        caller._require_empty_registry(module, "registry")
    assert raised.value.code == "retained_registry_not_fresh"


def test_module_global_snapshot_detects_in_place_mutable_changes():
    module = types.ModuleType("_global_snapshot_probe")
    module.settings = {"limit": 3}
    snapshot = caller._module_globals_snapshot(module)
    assert caller._module_globals_unchanged((snapshot,))
    module.settings["limit"] = 4
    assert not caller._module_globals_unchanged((snapshot,))


def _clean_raw_gate_result():
    raw = {
        "schema": "iteration41.okx.m01.root-helper-lifecycle-gate.v6",
        "status": "LOCAL_SYNTHETIC_CHILD",
        "phase": "complete",
        "error_category": None,
        "error_code": None,
        "job_count_after_cleanup_error": None,
        "source_bytes_held": 5,
        "win32_api": None,
        "native_failure_phase": None,
        "winerror": None,
        "reader_retained_context_count_after": 0,
        "reader_retained_context_count_captured_after": 0,
        "handle_close_failures": 0,
        "handle_close_calls": 8,
        "cleanup_wait_attempted": True,
        "cleanup_wait_succeeded": True,
        "wait_results": (True, True),
        "job_count_observations": (
            ("job_count_after_exit", 0),
            ("job_count_after_cleanup", 0),
        ),
        "unprojected_child_output": "never copied into the public projection",
    }
    raw.update(dict.fromkeys(caller.GATE_TRUE_FIELDS, True))
    raw.update(dict.fromkeys(caller.GATE_FALSE_FIELDS, False))
    return raw


def test_gate_projection_is_finite_and_requires_zero_job_eof_wait_and_closed_handles():
    raw = _clean_raw_gate_result()
    facts = caller._validate_gate_result(raw)
    assert caller._clean_gate_facts(facts)
    assert "unprojected_child_output" not in facts

    nonzero = _clean_raw_gate_result()
    nonzero["job_count_observations"] = (
        ("job_count_after_exit", 1),
        ("job_count_after_cleanup", 0),
    )
    assert not caller._clean_gate_facts(caller._validate_gate_result(nonzero))

    missing_cleanup_wait = _clean_raw_gate_result()
    missing_cleanup_wait["wait_results"] = (True,)
    missing_cleanup_wait["cleanup_wait_attempted"] = False
    missing_cleanup_wait["cleanup_wait_succeeded"] = False
    assert not caller._clean_gate_facts(caller._validate_gate_result(missing_cleanup_wait))

    missing_eof = _clean_raw_gate_result()
    missing_eof["stdout_eof"] = False
    assert not caller._clean_gate_facts(caller._validate_gate_result(missing_eof))


def test_cuv2_normal_close_is_only_attempted_for_clean_facts():
    calls = []

    @contextlib.contextmanager
    def fake_scope():
        yield {"public": b"synthetic"}
        calls.append("normal_exit")

    scope = fake_scope()
    scope.__enter__()
    state = {"scope_exit_attempted": False, "scope_exit_confirmed": False}
    result = {}
    generator = scope.gen
    globals_dict = generator.gi_frame.f_globals

    with pytest.raises(caller.CallerError) as raised:
        caller._close_scope_if_clean(
            scope, generator, globals_dict, state, result, clean_facts=False
        )
    assert raised.value.code == "gate_cleanup_not_certain"
    assert calls == []
    assert state["scope_exit_attempted"] is False

    caller._close_scope_if_clean(scope, generator, globals_dict, state, result, clean_facts=True)
    assert calls == ["normal_exit"]
    assert result["scope_exit_attempted"] is True
    assert result["scope_exit_confirmed"] is True
    assert result["scope_exit_state"] == "closed_verified"
    assert generator.gi_frame is None


def test_uncertain_scope_exit_remains_unconfirmed_and_references_are_retained():
    @contextlib.contextmanager
    def failing_scope():
        yield None
        raise RuntimeError("sourcefake exit error")

    scope = failing_scope()
    scope.__enter__()
    generator = scope.gen
    state = {"scope_exit_attempted": False, "scope_exit_confirmed": False, "scope": scope}
    result = {}
    with pytest.raises(RuntimeError):
        caller._close_scope_if_clean(
            scope,
            generator,
            generator.gi_frame.f_globals,
            state,
            result,
            clean_facts=True,
        )
    caller._set_scope_exit_state(state, result)
    assert result["scope_exit_attempted"] is True
    assert result["scope_exit_confirmed"] is False
    assert result["scope_exit_state"] == "unconfirmed"

    retained = object()
    before = len(caller._RETAINED_CONTEXTS)
    retained_state = {"gate": retained, "raw_source_bytes": {"public": b"p"}}
    caller._retain_state(retained_state, "a" * 64)
    caller._retain_state(retained_state, "a" * 64)
    try:
        assert retained_state["retained_python_references"] is True
        assert len(caller._RETAINED_CONTEXTS) == before + 1
        assert caller._RETAINED_CONTEXTS[-1][10] is retained
    finally:
        del caller._RETAINED_CONTEXTS[before:]


class _RuntimePinMismatchKernel:
    """Reuse the R7 fake kernel while serving only synthetic runtime bytes."""

    def __init__(self, supervisor, fake_leaves_module, path_values):
        self.base = fake_leaves_module._FakeKernel(supervisor)
        self.supervisor = supervisor
        self.fake_leaves_module = fake_leaves_module
        self.path_values = path_values
        self.runtime_handles = {}
        self.runtime_offsets = {}
        self.runtime_open_arguments = []
        self.create_process_calls = 0

    def __getattr__(self, name):
        if name.startswith("call_"):
            return getattr(self.base, name)
        if name in self.base.__dict__ or any(
            name in base.__dict__ for base in type(self.base).__mro__
        ):
            return getattr(self.base, name)
        if name not in self.base.functions:
            self.base.functions[name] = self.fake_leaves_module._FakeWinFunction(self, name)
        return self.base.functions[name]

    def _runtime_key(self, path):
        return caller._norm(path)

    def call_CreateFileW(self, path, access, share, security, creation, flags, template):
        assert access == self.supervisor._GENERIC_READ
        assert share == self.supervisor._FILE_SHARE_READ
        assert security is None
        assert creation == self.supervisor._OPEN_EXISTING
        assert flags == (
            self.supervisor._FILE_ATTRIBUTE_NORMAL | self.supervisor._FILE_FLAG_OPEN_REPARSE_POINT
        )
        assert template is None
        key = self._runtime_key(path)
        self.runtime_open_arguments.append((key, access, share, creation, flags))
        handle = self.base._new_handle()
        self.runtime_handles[handle] = (str(path), self.path_values[key])
        self.runtime_offsets[handle] = 0
        return handle

    def call_GetFileInformationByHandle(self, handle, info_pointer):
        assert int(handle) in self.runtime_handles
        info = ctypes.cast(
            info_pointer,
            ctypes.POINTER(self.supervisor._BY_HANDLE_FILE_INFORMATION),
        ).contents
        info.dwFileAttributes = self.supervisor._FILE_ATTRIBUTE_NORMAL
        info.dwVolumeSerialNumber = 7
        info.nFileSizeHigh = 0
        info.nFileSizeLow = len(self.runtime_handles[int(handle)][1])
        info.nNumberOfLinks = 1
        info.nFileIndexHigh = 0
        info.nFileIndexLow = int(handle)
        return True

    def call_GetFinalPathNameByHandleW(self, handle, buffer, capacity, _flags):
        assert int(handle) in self.runtime_handles
        final_path = self.runtime_handles[int(handle)][0]
        assert len(final_path) < capacity
        buffer.value = final_path
        return len(final_path)

    def call_GetFileSizeEx(self, handle, size_pointer):
        assert int(handle) in self.runtime_handles
        size = ctypes.cast(size_pointer, ctypes.POINTER(ctypes.c_longlong)).contents
        size.value = len(self.runtime_handles[int(handle)][1])
        return True

    def call_ReadFile(self, handle, buffer, capacity, received_pointer, overlapped):
        if int(handle) not in self.runtime_handles:
            return self.base.call_ReadFile(handle, buffer, capacity, received_pointer, overlapped)
        raw = self.runtime_handles[int(handle)][1]
        offset = self.runtime_offsets[int(handle)]
        chunk = raw[offset : offset + capacity]
        self.runtime_offsets[int(handle)] = offset + len(chunk)
        if chunk:
            ctypes.memmove(buffer, chunk, len(chunk))
        received = ctypes.cast(
            received_pointer,
            ctypes.POINTER(ctypes.wintypes.DWORD),
        ).contents
        received.value = len(chunk)
        return True

    def call_CreateProcessW(self, *args):
        self.create_process_calls += 1
        return self.base.call_CreateProcessW(*args)

    def call_CloseHandle(self, handle):
        if int(handle) in self.runtime_handles:
            self.runtime_handles.pop(int(handle))
            self.runtime_offsets.pop(int(handle), None)
        return self.base.call_CloseHandle(handle)


def test_zz_full_run_one_holds_31_public_and_3_software_bytes_then_fails_closed(
    tmp_path, monkeypatch, request
):
    if os.name != "nt":
        pytest.skip("the exact pinned M01 caller and Win32 fake leaves are Windows-only")

    caller_name = "_m01_r7_root_caller_r3_full_source_fake"
    actual_caller = _load_module(caller_name, CALLER_PATH)
    cu_name = "_cuv2_r7_root_caller_r3_full_source_fake"
    cu_module, cuv2_raw = _load_cuv2_source_module(cu_name)

    def cleanup_sourcefake_modules():
        actual_caller._RETAINED_CONTEXTS.clear()
        for module_name in tuple(sys.modules):
            if module_name.startswith(
                (
                    "_certification",
                    "_m01_readonly_monitor_v2",
                    "_m01_readonly_monitor_v3",
                    "_root_m01_r7_gate_",
                )
            ):
                sys.modules.pop(module_name, None)
        sys.modules.pop(cu_name, None)
        sys.modules.pop(caller_name, None)

    request.addfinalizer(cleanup_sourcefake_modules)
    index_raw = (ROOT / actual_caller.SOURCE_INDEX_RELATIVE).read_bytes()
    source_index = json.loads(index_raw.decode("ascii"))
    indexed_paths = {row["path"] for row in actual_caller._verify_source_index_rows(source_index)}
    public_paths = actual_caller._expected_public_pin_paths(indexed_paths)
    assert len(public_paths) == actual_caller.ROOT_PUBLIC_PIN_COUNT == 31

    public_values = {relative: (ROOT / relative).read_bytes() for relative in public_paths}
    public_pins = {
        relative: hashlib.sha256(raw).hexdigest() for relative, raw in public_values.items()
    }
    software_values = {
        "C:/anaconda3/python.exe": b"synthetic python executable bytes",
        "C:/anaconda3/python311.dll": b"synthetic python runtime dll bytes",
        actual_caller.CUV2_SOFTWARE_ORIGIN: cuv2_raw,
    }
    software_pins = {path: hashlib.sha256(raw).hexdigest() for path, raw in software_values.items()}
    software_pins[actual_caller.CUV2_SOFTWARE_ORIGIN] = actual_caller.CUV2_SOURCE_SHA256

    path_values = {
        actual_caller._norm(ROOT / relative): raw for relative, raw in public_values.items()
    }
    path_values.update({actual_caller._norm(path): raw for path, raw in software_values.items()})
    fake_private = types.SimpleNamespace()
    fake_cli = types.SimpleNamespace()
    fake_events = []

    @contextlib.contextmanager
    def fake_opened(path, **kwargs):
        fake_events.append("directory_scope")
        assert kwargs.get("directory") is True
        yield object()

    @contextlib.contextmanager
    def fake_locked_readonly_file(path, _private, _api, **kwargs):
        assert kwargs.get("allow_hardlinks") is True
        key = actual_caller._norm(path)
        handle = types.SimpleNamespace(key=key, identity=object())
        fake_events.append("file_scope")
        yield handle, handle.identity

    def fake_read_bounded_handle(_api, handle, _maximum):
        return path_values[handle.key]

    def fake_locked_file_identity(_api, handle, _private, **kwargs):
        assert kwargs.get("allow_hardlinks") is True
        return handle.identity

    fake_api = types.SimpleNamespace(opened=fake_opened)
    fake_private._api = lambda: fake_api
    fake_cli._locked_readonly_file = fake_locked_readonly_file
    fake_cli._read_bounded_handle = fake_read_bounded_handle
    fake_cli._locked_file_identity = fake_locked_file_identity
    original_enter = actual_caller._enter_cuv2_scope

    def enter_with_fake_cuv2_leaves(scope, wrapped, module):
        original_load = module.load

        def fake_load(_relative, _pin, name):
            return fake_private if name == "_root_public_custody_private" else fake_cli

        module.load = fake_load
        try:
            return original_enter(scope, wrapped, module)
        finally:
            module.load = original_load

    monkeypatch.setattr(actual_caller, "_enter_cuv2_scope", enter_with_fake_cuv2_leaves)

    original_validate = actual_caller._validate_output_directory
    output_directory = tmp_path / "r3-caller-observation"

    def route_output_to_temp(_path, _root):
        actual_caller._validate_output_directory = original_validate
        output_directory.mkdir()
        return output_directory

    monkeypatch.setattr(actual_caller, "_validate_output_directory", route_output_to_temp)

    original_read_bytes = Path.read_bytes

    def fake_public_read_bytes(path):
        key = actual_caller._norm(path)
        return path_values[key] if key in path_values else original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fake_public_read_bytes)
    original_resolve = Path.resolve
    fixed_runtime_keys = {
        actual_caller._norm("C:/anaconda3/python.exe"),
        actual_caller._norm("C:/anaconda3/python311.dll"),
    }

    def fake_runtime_resolve(path, *args, **kwargs):
        if actual_caller._norm(path) in fixed_runtime_keys:
            return Path(str(path))
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fake_runtime_resolve)

    fake_leaves_module = _load_module(
        "_m01_r7_root_caller_r3_fake_win32_leaves",
        ROOT / "tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r2.py",
    )
    kernels = []
    original_import_module = importlib.import_module

    def import_with_fake_kernel(name, package=None):
        module = original_import_module(name, package)
        if name == "_m01_readonly_monitor_v3.current_reader":
            kernel = _RuntimePinMismatchKernel(
                module.job_supervisor, fake_leaves_module, path_values
            )
            kernels.append(kernel)
            monkeypatch.setattr(
                module.job_supervisor.ctypes,
                "WinDLL",
                lambda *_args, **_kwargs: kernel,
                raising=False,
            )
            monkeypatch.setattr(
                module.job_supervisor.ctypes,
                "get_last_error",
                kernel.get_last_error,
                raising=False,
            )
        if name == "_certification.m01_private_monitor_v2":
            actual_caller.importlib.import_module = original_import_module
        return module

    monkeypatch.setattr(actual_caller.importlib, "import_module", import_with_fake_kernel)
    result = actual_caller.run_one(
        cu_module,
        cuv2_source_raw=cuv2_raw,
        public_pins=public_pins,
        software_pins=software_pins,
        root_nonce="a" * 32,
        output_dir=ROOT
        / actual_caller.EVIDENCE_ROOT.relative_to(ROOT)
        / actual_caller.ACTUAL_OUTPUT_NAME,
    )

    assert result["schema"] == "iteration41.okx.m01.r7_root_caller.v2"
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "caller_gate_binding_postcheck_failed", result
    assert result["gate_invocations"] == 1
    assert result["source_count"] == 34
    assert result["public_source_count"] == 31
    assert result["software_source_count"] == 3
    assert result["software_payload_bytes_returned_to_caller"] is True
    assert result["software_payload_bytes_retained_in_caller_state"] is True
    assert result["software_payload_bytes_sha256_rechecked_by_caller"] is True
    assert result["caller_opened_software_payload_paths"] is False
    assert result["caller_parsed_software_payloads"] is False
    assert result["software_pins_verified_by_cuv2"] is True
    assert result["scope_exit_attempted"] is False
    assert result["scope_exit_confirmed"] is False
    assert result["host_exit_permitted"] is False
    assert result["private_inputs_read"] is False
    assert result["account_provider_operations"] is False
    assert result["formal_m01_pass_count"] == 0
    assert result["gate_result"]["status"] == "LIFECYCLE_BLOCKED"
    assert result["gate_result"]["process_created"] is False
    assert result["retained_python_references"] is True
    assert fake_events
    assert len(kernels) == 1
    kernel = kernels[0]
    assert len(kernel.runtime_open_arguments) == 1
    assert kernel.create_process_calls == 0
    assert kernel.child_exit_code is None
    assert kernel.stdin_frame == b""
    assert len(actual_caller._RETAINED_CONTEXTS) == 1
    retained = actual_caller._RETAINED_CONTEXTS[0]
    assert type(retained[7]) is dict and len(retained[7]) == 34
    assert {actual_caller._norm(key): value for key, value in retained[7].items()} == path_values
