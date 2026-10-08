"""Whole-module source-fake tests for the repaired M01 helper lifecycle gate."""

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import time
from types import FunctionType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
VENUE = ROOT / "examples/000_live_certification/okx_penetration"
GATE_PATH = ROOT / "scripts/iteration41_okx_m01_root_helper_lifecycle_gate_r7.py"
PATCH_PATH = ROOT / "scripts/iteration41_okx_m01_root_helper_lifecycle_patch_r2.py"
GATE_R2_TEST_PATH = (
    ROOT / "tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r2.py"
)

_GATE_SPEC = importlib.util.spec_from_file_location("_m01_root_helper_gate_r7_test", GATE_PATH)
assert _GATE_SPEC is not None and _GATE_SPEC.loader is not None
gate = importlib.util.module_from_spec(_GATE_SPEC)
_GATE_SPEC.loader.exec_module(gate)

_PATCH_SPEC = importlib.util.spec_from_file_location(
    "_m01_root_helper_patch_r2_for_r7_test", PATCH_PATH
)
assert _PATCH_SPEC is not None and _PATCH_SPEC.loader is not None
patch_r2 = importlib.util.module_from_spec(_PATCH_SPEC)
_PATCH_SPEC.loader.exec_module(patch_r2)

_FAKE_SPEC = importlib.util.spec_from_file_location(
    "_m01_root_helper_r2_fake_leaves", GATE_R2_TEST_PATH
)
assert _FAKE_SPEC is not None and _FAKE_SPEC.loader is not None
fake_leaves = importlib.util.module_from_spec(_FAKE_SPEC)
_FAKE_SPEC.loader.exec_module(fake_leaves)


_ISOLATED_INPUTS = {
    "_certification/__init__.py": (
        66,
        "a55f2a221bc45d1b840c15ca9ec8e5f46579e011728ec9e7c3b0748eacc7f7dc",
    ),
    "_certification/m01_private_monitor_v2.py": (
        25108,
        "1c319502dcec4da91a7166ad1a532e4610319ca837ac93f2391f21fda87ae1db",
    ),
    "_m01_readonly_monitor_v2/__init__.py": (
        56,
        "d7cbd961ed06466f6bd2388d44a5951f92b0bb9f61d930cc9d26ec21be8d1a5c",
    ),
    "_m01_readonly_monitor_v2/current_types.py": (
        7364,
        "cd896051b0580195baa569989622c18fec594afc3772e7ea4af9e4cf226778ea",
    ),
    "_m01_readonly_monitor_v2/job_supervisor.py": (
        71188,
        "188b929b4e74b6e16a54d21093b6d52a7471849b161b2777945561e6d8d62e82",
    ),
    "_m01_readonly_monitor_v2/worker.py": (
        60000,
        "aea9651c571d4bbd93592ccbd06c630a2a73df8286e9425a357433d598ca4f41",
    ),
    "_m01_readonly_monitor_v3/__init__.py": (
        50,
        "ae66c18bb4d289dd2e09e9ac637af8a6ef017f4f6cc5edec4a23ee23d7e560e6",
    ),
}
_MODULE_PREFIXES = (
    "_certification",
    "_m01_readonly_monitor_v2",
    "_m01_readonly_monitor_v3",
)


def _is_owned_module(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in _MODULE_PREFIXES)


class _VirtualClock:
    def __init__(self):
        self.offset = 0.0
        self.base = time.monotonic()

    def monotonic(self):
        return self.base + self.offset

    def sleep(self, seconds):
        self.offset += max(0.0, float(seconds))


@pytest.fixture
def patched_source_modules(tmp_path, monkeypatch):
    """Load the transformed reader module and exact source closure in isolation."""
    if os.name != "nt":
        pytest.skip("the source-bound M01 lifecycle gate is Windows-only")

    isolated_venue = tmp_path / "okx_penetration"
    for relative, (expected_size, expected_sha) in _ISOLATED_INPUTS.items():
        source_path = VENUE / relative
        raw = source_path.read_bytes()
        assert len(raw) == expected_size
        assert hashlib.sha256(raw).hexdigest() == expected_sha
        destination = isolated_venue / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)

    original_reader = (VENUE / "_m01_readonly_monitor_v3/current_reader.py").read_bytes()
    assert hashlib.sha256(original_reader).hexdigest() == patch_r2.CURRENT_READER_SHA256
    successor = patch_r2.transform_current_reader_source(original_reader)
    assert len(successor) == 68215
    assert hashlib.sha256(successor).hexdigest() == gate.READER_SHA256
    reader_path = isolated_venue / "_m01_readonly_monitor_v3/current_reader.py"
    reader_path.write_bytes(successor)

    previous_modules = {
        name: module for name, module in sys.modules.items() if _is_owned_module(name)
    }
    for name in tuple(sys.modules):
        if _is_owned_module(name):
            del sys.modules[name]
    monkeypatch.syspath_prepend(str(isolated_venue))
    monkeypatch.setattr(gate, "VENUE", isolated_venue)
    importlib.invalidate_caches()
    try:
        reader = importlib.import_module("_m01_readonly_monitor_v3.current_reader")
        supervisor = reader.job_supervisor
        worker = reader.worker
        yield reader, supervisor, worker
    finally:
        for name in tuple(sys.modules):
            if _is_owned_module(name):
                del sys.modules[name]
        sys.modules.update(previous_modules)


@pytest.fixture
def fake_win32(patched_source_modules, monkeypatch):
    _reader, supervisor, _worker = patched_source_modules
    kernel = fake_leaves._FakeKernel(supervisor)
    monkeypatch.setattr(supervisor.ctypes, "WinDLL", lambda *_a, **_k: kernel, raising=False)
    monkeypatch.setattr(supervisor.ctypes, "get_last_error", kernel.get_last_error, raising=False)
    monkeypatch.setattr(
        supervisor, "_hold_runtime_files", lambda _kernel, _deadline: {"runtime_handles": set()}
    )
    return kernel


def _use_virtual_reader_clock(reader, monkeypatch):
    monkeypatch.setattr(reader, "time", _VirtualClock())


def test_gate_runs_exact_transformed_reader_module_through_v2_fake_leaves(
    patched_source_modules, fake_win32, monkeypatch
):
    reader, supervisor, worker = patched_source_modules
    _use_virtual_reader_clock(reader, monkeypatch)

    result = gate.run_fixed_synthetic_probe(reader, supervisor, worker)

    assert result["schema"] == "iteration41.okx.m01.root-helper-lifecycle-gate.v6"
    assert result["status"] == "SOURCE_FAKE_ONLY"
    assert result["phase"] == "complete"
    assert result["reader_source_pinned"] is True
    assert result["supervisor_source_pinned"] is True
    assert result["worker_source_pinned"] is True
    assert result["source_functions_restored"] is True
    assert result["process_created"] is True
    assert result["job_assigned_before_resume"] is True
    assert result["resumed"] is True
    assert result["process_wait_succeeded"] is True
    assert result["process_exit_code_zero"] is True
    assert result["job_zero_after_exit"] is True
    assert result["job_zero_after_cleanup"] is True
    assert result["cleanup_confirmed"] is True
    assert result["stdout_eof"] is True
    assert result["stderr_eof"] is True
    assert result["stdout_matches_fixed"] is True
    assert result["stderr_empty"] is True
    assert result["all_observed_handles_closed"] is True
    assert result["handle_close_failures"] == 0
    assert result["reader_retained_contexts_empty_before"] is True
    assert result["reader_retained_contexts_empty_after"] is True
    assert result["reader_retained_registry_identity_unchanged"] is True
    assert result["reader_retained_context_count_after"] == 0
    assert result["retained_context"] is False
    assert result["production_acceptance"] is False
    assert fake_win32.process_handle_closed is True
    assert fake_win32.job_close_preceding_sample == (True, True, 0)
    assert fake_win32.stdout_bytes == gate.SYNTHETIC_OUTPUT
    assert fake_win32.child_exit_code == 0
    assert fake_win32.stdin_frame[4:].startswith(b"def _worker_source_sha256():\n")


def test_source_root_reference_is_closed_before_zero_count_check(
    patched_source_modules, monkeypatch
):
    reader, supervisor, worker = patched_source_modules
    kernel = fake_leaves._FakeKernel(supervisor, root_process_reference=True)
    monkeypatch.setattr(supervisor.ctypes, "WinDLL", lambda *_a, **_k: kernel, raising=False)
    monkeypatch.setattr(supervisor.ctypes, "get_last_error", kernel.get_last_error, raising=False)
    monkeypatch.setattr(
        supervisor, "_hold_runtime_files", lambda _kernel, _deadline: {"runtime_handles": set()}
    )
    _use_virtual_reader_clock(reader, monkeypatch)

    result = gate.run_fixed_synthetic_probe(reader, supervisor, worker)

    assert result["status"] == "SOURCE_FAKE_ONLY"
    assert result["job_zero_after_exit"] is True
    assert result["reader_retained_contexts_empty_after"] is True
    assert kernel.process_handle_closed is True
    after_exit_samples = [sample for sample in kernel.job_count_samples if sample[0]]
    assert after_exit_samples
    assert all(sample[1:] == (True, 0) for sample in after_exit_samples)
    assert kernel.job_close_preceding_sample == (True, True, 0)
    assert kernel.terminated is False


def test_true_descendant_is_terminated_then_zero_checked_before_job_close(
    patched_source_modules, monkeypatch
):
    reader, supervisor, worker = patched_source_modules
    kernel = fake_leaves._FakeKernel(
        supervisor,
        descendant_after_root_close=True,
        clear_descendant_on_terminate=True,
    )
    monkeypatch.setattr(supervisor.ctypes, "WinDLL", lambda *_a, **_k: kernel, raising=False)
    monkeypatch.setattr(supervisor.ctypes, "get_last_error", kernel.get_last_error, raising=False)
    monkeypatch.setattr(
        supervisor, "_hold_runtime_files", lambda _kernel, _deadline: {"runtime_handles": set()}
    )
    _use_virtual_reader_clock(reader, monkeypatch)

    result = gate.run_fixed_synthetic_probe(reader, supervisor, worker)

    assert result["status"] == "LIFECYCLE_BLOCKED"
    assert result["reader_exception_code"] == "root_helper_descendant_active"
    assert result["termination_requested"] is True
    assert result["termination_succeeded"] is True
    assert result["job_nonzero_after_exit"] is True
    assert any(
        phase == "job_count_after_exit" and count == 1
        for phase, count in result["job_count_observations"]
    )
    assert any(
        phase == "job_count_after_cleanup" and count == 0
        for phase, count in result["job_count_observations"]
    )
    assert result["job_zero_after_cleanup"] is True
    assert result["cleanup_confirmed"] is True
    assert result["reader_retained_contexts_empty_after"] is True
    assert kernel.process_handle_closed is True
    assert kernel.terminated is True
    assert kernel.job_close_preceding_sample == (True, True, 0)


def test_persistent_descendant_retains_reader_job_and_gate_context(
    patched_source_modules, monkeypatch
):
    reader, supervisor, worker = patched_source_modules
    kernel = fake_leaves._FakeKernel(
        supervisor,
        descendant_after_root_close=True,
        clear_descendant_on_terminate=False,
    )
    monkeypatch.setattr(supervisor.ctypes, "WinDLL", lambda *_a, **_k: kernel, raising=False)
    monkeypatch.setattr(supervisor.ctypes, "get_last_error", kernel.get_last_error, raising=False)
    monkeypatch.setattr(
        supervisor, "_hold_runtime_files", lambda _kernel, _deadline: {"runtime_handles": set()}
    )
    _use_virtual_reader_clock(reader, monkeypatch)

    result = gate.run_fixed_synthetic_probe(reader, supervisor, worker)

    assert result["status"] == "LIFECYCLE_BLOCKED"
    assert result["reader_exception_code"] == "root_helper_descendant_active"
    assert result["termination_succeeded"] is True
    assert result["job_nonzero_after_exit"] is True
    assert result["job_count_after_cleanup_observed"] is True
    assert result["job_nonzero_after_cleanup"] is True
    assert result["cleanup_confirmed"] is False
    assert result["reader_retained_contexts_empty_after"] is False
    assert result["reader_retained_context_count_after"] == 1
    assert result["retained_context"] is True
    assert kernel.job_handle not in kernel.closed_handles
    assert kernel.job_close_preceding_sample is None


def test_cleanup_close_failure_keeps_primary_reader_error_and_source_context(
    patched_source_modules, monkeypatch
):
    reader, supervisor, worker = patched_source_modules
    kernel = fake_leaves._FakeKernel(
        supervisor,
        fail_job_close=True,
        descendant_after_root_close=True,
        clear_descendant_on_terminate=True,
    )
    monkeypatch.setattr(supervisor.ctypes, "WinDLL", lambda *_a, **_k: kernel, raising=False)
    monkeypatch.setattr(supervisor.ctypes, "get_last_error", kernel.get_last_error, raising=False)
    monkeypatch.setattr(
        supervisor, "_hold_runtime_files", lambda _kernel, _deadline: {"runtime_handles": set()}
    )
    _use_virtual_reader_clock(reader, monkeypatch)

    result = gate.run_fixed_synthetic_probe(reader, supervisor, worker)

    assert result["status"] == "LIFECYCLE_BLOCKED"
    assert result["error_code"] == "root_helper_descendant_active"
    assert result["reader_exception_code"] == "root_helper_descendant_active"
    assert result["win32_api"] == "CloseHandle"
    assert result["winerror"] == 5
    assert result["job_zero_after_cleanup"] is True
    assert result["cleanup_confirmed"] is False
    assert result["reader_retained_context_count_after"] == 1
    assert result["retained_context"] is True
    assert kernel.job_handle not in kernel.closed_handles
    assert kernel.job_close_preceding_sample == (True, True, 0)


def test_gate_rejects_detached_same_filename_successor_function(
    patched_source_modules, monkeypatch
):
    reader, supervisor, worker = patched_source_modules
    namespace = {}
    exec(
        compile(
            "def _run_pinned_root_helper(*args, **kwargs):\n    return None\n",
            str(Path(reader.__file__).resolve()),
            "exec",
        ),
        namespace,
        namespace,
    )
    monkeypatch.setattr(reader, "_run_pinned_root_helper", namespace["_run_pinned_root_helper"])

    with pytest.raises(gate.GateError) as raised:
        gate._bind_sources(reader, supervisor, worker)

    assert raised.value.code == "reader_global_binding_mismatch"


def test_gate_rejects_same_filename_reader_code_in_module_globals(patched_source_modules):
    reader, supervisor, worker = patched_source_modules
    original = reader._run_pinned_root_helper
    exec(
        compile(
            "def _run_pinned_root_helper(*args, **kwargs):\n    return None\n",
            str(Path(reader.__file__).resolve()),
            "exec",
        ),
        reader.__dict__,
        reader.__dict__,
    )
    try:
        with pytest.raises(gate.GateError) as raised:
            gate._bind_sources(reader, supervisor, worker)
    finally:
        reader._run_pinned_root_helper = original

    assert raised.value.code == "module_function_binding_mismatch"


def test_gate_rejects_callable_proxy_with_pinned_function_attributes(patched_source_modules):
    reader, supervisor, worker = patched_source_modules
    original = reader._run_pinned_root_helper

    class FunctionProxy:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def __call__(self, *_args, **_kwargs):
            return None

    reader._run_pinned_root_helper = FunctionProxy(original)
    try:
        with pytest.raises(gate.GateError) as raised:
            gate._bind_sources(reader, supervisor, worker)
    finally:
        reader._run_pinned_root_helper = original

    assert raised.value.code == "module_function_binding_mismatch"


def test_gate_rejects_same_filename_supervisor_code_in_module_globals(
    patched_source_modules,
):
    reader, supervisor, worker = patched_source_modules
    original = supervisor._write_all
    exec(
        compile(
            "def _write_all(*args, **kwargs):\n    return True\n",
            str(Path(supervisor.__file__).resolve()),
            "exec",
        ),
        supervisor.__dict__,
        supervisor.__dict__,
    )
    try:
        with pytest.raises(gate.GateError) as raised:
            gate._bind_sources(reader, supervisor, worker)
    finally:
        supervisor._write_all = original

    assert raised.value.code == "module_function_binding_mismatch"


@pytest.mark.parametrize(
    "name",
    ("_hold_and_verify_runtime_file", "_canonical_win32_path"),
)
def test_gate_rejects_same_globals_supervisor_transitive_helper_replacement(
    patched_source_modules, name
):
    reader, supervisor, worker = patched_source_modules
    original = getattr(supervisor, name)
    replacement = f"def {name}(*args, **kwargs):\n    return None\n"
    exec(
        compile(replacement, str(Path(supervisor.__file__).resolve()), "exec"), supervisor.__dict__
    )
    try:
        with pytest.raises(gate.GateError) as raised:
            gate._bind_sources(reader, supervisor, worker)
    finally:
        setattr(supervisor, name, original)

    assert raised.value.code == "module_function_binding_mismatch"


def test_gate_rejects_same_globals_worker_protocol_function_replacement(patched_source_modules):
    reader, supervisor, worker = patched_source_modules
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
        with pytest.raises(gate.GateError) as raised:
            gate._bind_sources(reader, supervisor, worker)
    finally:
        worker.parse_credentials = original

    assert raised.value.code == "module_function_binding_mismatch"


def test_gate_rejects_same_globals_worker_class_method_replacement(patched_source_modules):
    reader, supervisor, worker = patched_source_modules
    original = worker.OKXPrivateWebSocketTransport
    exec(
        compile(
            "class OKXPrivateWebSocketTransport:\n"
            "    def connect(self, *args, **kwargs):\n"
            "        return None\n",
            str(Path(worker.__file__).resolve()),
            "exec",
        ),
        worker.__dict__,
    )
    try:
        with pytest.raises(gate.GateError) as raised:
            gate._bind_sources(reader, supervisor, worker)
    finally:
        worker.OKXPrivateWebSocketTransport = original

    assert raised.value.code == "module_class_descriptor_kind_mismatch"


def test_gate_rejects_property_replaced_by_its_source_getter(patched_source_modules):
    reader, supervisor, worker = patched_source_modules
    target_class = worker._WireReader
    original = vars(target_class)["partial_state_clear"]
    target_class.partial_state_clear = original.fget
    try:
        with pytest.raises(gate.GateError) as raised:
            gate._bind_sources(reader, supervisor, worker)
    finally:
        target_class.partial_state_clear = original

    assert raised.value.code == "module_class_descriptor_kind_mismatch"


def test_gate_rejects_property_with_undeclared_foreign_setter(patched_source_modules):
    reader, supervisor, worker = patched_source_modules
    target_class = worker._WireReader
    original = vars(target_class)["partial_state_clear"]
    foreign_setter = FunctionType(original.fget.__code__, {"__name__": "foreign.worker"})
    foreign_setter.__module__ = "foreign.worker"
    foreign_setter.__qualname__ = original.fget.__qualname__
    target_class.partial_state_clear = property(original.fget, foreign_setter)
    try:
        with pytest.raises(gate.GateError) as raised:
            gate._bind_sources(reader, supervisor, worker)
    finally:
        target_class.partial_state_clear = original

    assert raised.value.code == "module_class_descriptor_accessor_mismatch"


def test_gate_rejects_classmethod_replaced_by_its_source_function(patched_source_modules):
    reader, supervisor, worker = patched_source_modules
    target_class = worker.OKXPrivateWebSocketTransport
    original = vars(target_class)["connect"]
    target_class.connect = original.__func__
    try:
        with pytest.raises(gate.GateError) as raised:
            gate._bind_sources(reader, supervisor, worker)
    finally:
        target_class.connect = original

    assert raised.value.code == "module_class_descriptor_kind_mismatch"


def test_gate_rejects_source_code_method_rebound_to_foreign_globals(patched_source_modules):
    reader, supervisor, worker = patched_source_modules
    target_class = worker.OKXPrivateWebSocketTransport
    original_descriptor = vars(target_class)["connect"]
    method = original_descriptor.__func__
    replacement = FunctionType(method.__code__, {"__name__": "foreign.worker"})
    replacement.__qualname__ = method.__qualname__
    target_class.connect = classmethod(replacement)
    try:
        with pytest.raises(gate.GateError) as raised:
            gate._bind_sources(reader, supervisor, worker)
    finally:
        target_class.connect = original_descriptor

    assert raised.value.code == "module_function_binding_mismatch"


def test_gate_rejects_fabricated_dataclass_generated_method(patched_source_modules):
    reader, supervisor, worker = patched_source_modules
    launch_class = worker.LaunchRequest
    original = vars(launch_class)["__init__"]
    module_code = compile(
        "def fabricated(self, *args, **kwargs):\n    return None\n",
        "<string>",
        "exec",
    )
    method_code = next(value for value in module_code.co_consts if hasattr(value, "co_code"))
    replacement = FunctionType(method_code, worker.__dict__)
    replacement.__qualname__ = "LaunchRequest.__init__"
    launch_class.__init__ = replacement
    try:
        with pytest.raises(gate.GateError) as raised:
            gate._bind_sources(reader, supervisor, worker)
    finally:
        launch_class.__init__ = original

    assert raised.value.code == "module_generated_method_unexpected"


def test_gate_rejects_dataclass_default_changed_before_reference_binding(patched_source_modules):
    reader, supervisor, worker = patched_source_modules
    original = worker.MAX_EVENT_TIMEOUT_MS
    original_defaults = worker.LaunchRequest.__init__.__defaults__
    worker.MAX_EVENT_TIMEOUT_MS = original + 1
    try:
        source = Path(worker.__file__).read_bytes()
        tree = ast.parse(source)
        node = next(
            item
            for item in tree.body
            if isinstance(item, ast.ClassDef) and item.name == "LaunchRequest"
        )
        reference = gate._dataclass_reference_class(
            node, worker, Path(worker.__file__).resolve(strict=True), tree
        )
        worker.LaunchRequest.__init__.__defaults__ = reference.__init__.__defaults__
        with pytest.raises(gate.GateError) as raised:
            gate._bind_sources(reader, supervisor, worker)
    finally:
        worker.MAX_EVENT_TIMEOUT_MS = original
        worker.LaunchRequest.__init__.__defaults__ = original_defaults

    assert raised.value.code == "module_literal_binding_mismatch"


def test_wrong_module_origin_is_rejected_before_opening_its_file(
    patched_source_modules, tmp_path, monkeypatch
):
    _reader, _supervisor, _worker = patched_source_modules
    outside = tmp_path / "must_not_read.py"
    outside.write_bytes(b"public test sentinel\n")
    module = SimpleNamespace(
        __name__="_m01_readonly_monitor_v3.current_reader",
        __file__=str(outside),
    )
    original_open = Path.open
    forbidden_reads = []

    def guarded_open(path, *args, **kwargs):
        if os.path.normcase(os.path.abspath(str(path))) == os.path.normcase(str(outside)):
            forbidden_reads.append(True)
            raise AssertionError("wrong-origin path was opened")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    with pytest.raises(gate.GateError) as raised:
        gate._module_source(
            module,
            "_m01_readonly_monitor_v3.current_reader",
            gate.READER_RELATIVE,
            gate.READER_SHA256,
        )

    assert raised.value.code == "source_module_origin_mismatch"
    assert forbidden_reads == []


def test_nonempty_reader_registry_fails_before_helper_and_retains_verified_sources(
    patched_source_modules, fake_win32
):
    reader, supervisor, worker = patched_source_modules
    registry = reader._ROOT_HELPER_RETAINED_CONTEXTS
    registry.append(None)

    result = gate.run_fixed_synthetic_probe(reader, supervisor, worker)

    assert result["status"] == "LIFECYCLE_BLOCKED"
    assert result["phase"] == "source_binding"
    assert result["error_code"] == "reader_retained_context_not_fresh"
    assert result["source_bytes_held"] == 5
    assert result["reader_retained_contexts_empty_before"] is False
    assert result["reader_retained_registry_identity_unchanged"] is True
    assert result["reader_retained_context_count_after"] == 1
    assert result["process_created"] is False
    assert result["retained_context"] is True
    assert fake_win32.child_exit_code is None
    assert fake_win32.stdin_frame == b""


def test_invalid_type_reader_registry_fails_closed_and_retains_verified_sources(
    patched_source_modules, fake_win32
):
    reader, supervisor, worker = patched_source_modules
    reader._ROOT_HELPER_RETAINED_CONTEXTS = None

    result = gate.run_fixed_synthetic_probe(reader, supervisor, worker)

    assert result["status"] == "LIFECYCLE_BLOCKED"
    assert result["phase"] == "source_binding"
    assert result["error_code"] == "reader_retained_context_not_fresh"
    assert result["source_bytes_held"] == 5
    assert result["reader_retained_contexts_empty_before"] is False
    assert result["reader_retained_contexts_empty_after"] is False
    assert result["reader_retained_registry_identity_unchanged"] is False
    assert result["reader_retained_context_count_after"] is None
    assert result["process_created"] is False
    assert result["retained_context"] is True
    assert fake_win32.child_exit_code is None
    assert fake_win32.stdin_frame == b""


def test_live_reader_registry_rebind_blocks_and_retains_original_module_context(
    patched_source_modules, monkeypatch
):
    reader, supervisor, worker = patched_source_modules
    kernel = fake_leaves._FakeKernel(supervisor)
    monkeypatch.setattr(supervisor.ctypes, "WinDLL", lambda *_a, **_k: kernel, raising=False)
    monkeypatch.setattr(supervisor.ctypes, "get_last_error", kernel.get_last_error, raising=False)
    monkeypatch.setattr(
        supervisor, "_hold_runtime_files", lambda _kernel, _deadline: {"runtime_handles": set()}
    )
    original_read = kernel.call_ReadFile

    def rebind_reader_registry(*args):
        reader.__dict__["_ROOT_HELPER_RETAINED_CONTEXTS"] = []
        return original_read(*args)

    monkeypatch.setattr(kernel, "call_ReadFile", rebind_reader_registry)
    _use_virtual_reader_clock(reader, monkeypatch)

    result = gate.run_fixed_synthetic_probe(reader, supervisor, worker)

    assert result["status"] == "LIFECYCLE_BLOCKED"
    assert result["error_code"] == "module_binding_changed_after_call"
    assert result["source_bytes_held"] == 5
    assert result["reader_retained_contexts_empty_before"] is True
    assert result["reader_retained_registry_identity_unchanged"] is False
    assert result["reader_retained_context_count_captured_after"] == 0
    assert result["reader_retained_context_count_after"] == 0
    assert result["reader_retained_contexts_empty_after"] is False
    assert result["module_bindings_unchanged_after"] is False
    assert result["retained_context"] is True
    assert result["process_exit_code_zero"] is True
    assert result["all_observed_handles_closed"] is True
