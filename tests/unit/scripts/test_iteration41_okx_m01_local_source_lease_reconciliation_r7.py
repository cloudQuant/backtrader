"""Production-loaded source-fake checks for M01 CUv2 lease reconciliation."""

from __future__ import annotations

import ast
import ctypes
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from contextlib import contextmanager
from types import FunctionType, ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"
CUV2_SNAPSHOT = EVIDENCE / "iteration41-cuv2-public-source-snapshot-r1-2026-10-08/cuv2-source.py"
OBSERVATION_PATH = (
    EVIDENCE / "iteration41-okx-m01-local-lifecycle-root-actual-r1-2026-10-09/observation.json"
)
RETAINED_PATH = (
    EVIDENCE / "iteration41-okx-m01-local-lifecycle-root-actual-r1-2026-10-09/retained-facts.json"
)
DRIVER_PATH = ROOT / "scripts/iteration41_okx_m01_local_source_lease_reconciliation_r7.py"
VENUE = ROOT / "examples/000_live_certification/okx_penetration"

_SPEC = importlib.util.spec_from_file_location(
    "_m01_source_lease_reconciliation_r7_test", DRIVER_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
reconciliation = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = reconciliation
_SPEC.loader.exec_module(reconciliation)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path_key(value) -> str:
    return reconciliation._path_key(value)


def _assignment_nodes(raw):
    tree = ast.parse(raw.decode("utf-8"))
    assignments = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
    return assignments


def _runner_text(node, assignments, seen=()):
    if isinstance(node, ast.Constant) and type(node.value) is str:
        return node.value
    if isinstance(node, ast.Name) and node.id in assignments and node.id not in seen:
        return _runner_text(assignments[node.id], assignments, (*seen, node.id))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _runner_text(node.left, assignments, seen) + _runner_text(
            node.right, assignments, seen
        )
    raise AssertionError("unsupported pinned runner string expression")


def _root_runner_maps(root_runner_raw):
    runner_rel = reconciliation.ROOT_RUNNER_RELATIVE
    runner_pin = reconciliation._PUBLIC_SOURCE_PINS[runner_rel]
    assert _sha(root_runner_raw) == runner_pin
    assignments = _assignment_nodes(root_runner_raw)

    support_node = assignments["SUPPORT"]
    assert isinstance(support_node, ast.Dict)
    support = {
        _runner_text(key, assignments): ast.literal_eval(value)
        for key, value in zip(support_node.keys, support_node.values)
    }
    assert len(support) == 6
    source_index_paths = [path for path in support if path.endswith("/source-index.json")]
    assert len(source_index_paths) == 1
    source_index_path = ROOT / source_index_paths[0]
    source_index_raw = _bounded_public_read(source_index_path, 10 * 1024 * 1024)
    assert _sha(source_index_raw) == support[source_index_paths[0]]
    source_index = json.loads(source_index_raw.decode("utf-8"))
    rows = source_index.get("rows")
    assert type(rows) is list and len(rows) == 20
    pins = {row["path"]: row["sha256"] for row in rows}
    pins.update(support)
    pins[runner_rel] = _sha(root_runner_raw)
    assert len(pins) == 27

    cu_node = assignments["CU"]
    assert (
        isinstance(cu_node, ast.Call)
        and isinstance(cu_node.func, ast.Name)
        and cu_node.func.id == "Path"
        and len(cu_node.args) == 1
        and not cu_node.keywords
    )
    cu_path_value = _runner_text(cu_node.args[0], assignments)
    cu_path = Path(cu_path_value)
    cu_sha = ast.literal_eval(assignments["CU_SHA"])
    assert cu_sha == reconciliation.CUV2_SOURCE_SHA256

    software_node = assignments["SOFTWARE"]
    assert isinstance(software_node, ast.Dict) and len(software_node.keys) == 3
    software = {}
    for index in (0, 1):
        software[ast.literal_eval(software_node.keys[index])] = ast.literal_eval(
            software_node.values[index]
        )
    cu_key_node = software_node.keys[2]
    assert (
        isinstance(cu_key_node, ast.Call)
        and isinstance(cu_key_node.func, ast.Name)
        and cu_key_node.func.id == "str"
        and len(cu_key_node.args) == 1
        and isinstance(cu_key_node.args[0], ast.Name)
        and cu_key_node.args[0].id == "CU"
        and not cu_key_node.keywords
        and isinstance(software_node.values[2], ast.Name)
        and software_node.values[2].id == "CU_SHA"
    )
    software[str(cu_path)] = cu_sha
    assert _path_key(str(cu_path)) == _path_key(reconciliation.CUV2_RUNTIME_ORIGIN)
    assert pins == reconciliation._PUBLIC_SOURCE_PINS
    assert software == reconciliation._SOFTWARE_SOURCE_PINS
    return pins, software, source_index_raw


def _production_gate_context(gate, reader, supervisor, projection):
    """Build the exact GateR1 context type for the pinned finite projection."""
    context = gate._Observation(reader, supervisor)
    context.phase = projection["phase"]
    context.failed_phase = projection["phase"]
    context.error_category = projection["error_category"]
    context.error_code = projection["error_code"]
    context.native_api = projection["win32_api"]
    context.native_winerror = projection["winerror"]
    context.created = projection["process_created"]
    context.assigned = projection["job_assigned_before_resume"]
    context.resumed = projection["resumed"]
    context.source_write_ok = projection["source_frame_write_succeeded"]
    context.stdin_closed = projection["stdin_close_succeeded"]
    context.wait_results = [
        projection["process_wait_succeeded"],
        projection["cleanup_wait_succeeded"],
        projection["process_reaped_after_cleanup"],
    ]
    context.process_exit_code_present = projection["process_exit_code_present"]
    context.process_exit_code_zero = projection["process_exit_code_zero"]
    context.job_counts = [1, 1, 1]
    context.stdout_eof = projection["stdout_eof"]
    context.stderr_eof = projection["stderr_eof"]
    context.stdout_done = projection["stdout_read_done"]
    context.stderr_done = projection["stderr_read_done"]
    context.stdout_error = projection["stdout_read_error"]
    context.stderr_error = projection["stderr_read_error"]
    context.stdout_overflow = projection["stdout_overflow"]
    context.stderr_overflow = projection["stderr_overflow"]
    context.output_matches = projection["stdout_matches_fixed"]
    context.stderr_empty = projection["stderr_empty"]
    context.thread_starts = {
        "stdout": projection["stdout_thread_started"],
        "stderr": projection["stderr_thread_started"],
    }
    context.thread_joins = {
        "stdout": projection["stdout_thread_joined"],
        "stderr": projection["stderr_thread_joined"],
    }
    context.terminate_requested = projection["termination_requested"]
    context.terminate_succeeded = projection["termination_succeeded"]
    context.close_calls = projection["handle_close_calls"]
    context.close_failures = projection["handle_close_failures"]
    context.open_handles.clear()
    context.sourcefake = projection["source_fake_only"]
    context.runtime_registry = supervisor._ORPHANED_RUNTIME_HANDLE_SETS
    context.runtime_registry_empty_before = projection["runtime_registry_empty_before"]
    context.runtime_registry_length_before = len(context.runtime_registry)
    context.raw_kernel = object()
    context.kernel_proxy = object()
    context.control_reference = object()
    context.kernel_reference = object()
    context.sibling_registry = context.runtime_registry
    context.thread_references[:] = [object(), object()]
    context.pipe_state_references[:] = [object(), object()]
    return context


class _FakeApi:
    def __init__(self, contents_by_path, software_bytes):
        self.contents_by_path = contents_by_path
        self.software_bytes = software_bytes
        self.handles = {}
        self.next_handle = 10_000
        self.private = None
        self.cuv2 = None
        self.original_path = None
        self.original_sha = None
        self.readback_path = None
        self.readback_installed = False
        self.closed_count = 0
        self.identity_calls = {}
        self.change_second_identity = False
        self.on_final_close = None
        self.events = []
        self.kernel = type(
            "FakeKernel",
            (),
            {"GetFileInformationByHandle": self._get_info, "ReadFile": self._read_file},
        )()

    @contextmanager
    def opened(self, path, *, directory, access):
        self.events.append(("directory_enter", _path_key(path), bool(directory)))
        try:
            yield object()
        finally:
            self.events.append(("directory_close", _path_key(path), bool(directory)))

    def CreateFileW(self, path, *_args):
        key = _path_key(path)
        if key not in self.contents_by_path:
            raise AssertionError("fake API was asked for an unpinned path")
        self.next_handle += 1
        handle = self.next_handle
        self.handles[handle] = {"path": path, "key": key, "raw": self.contents_by_path[key]}
        self.events.append(("file_open", key, handle))
        return handle

    def CloseHandle(self, handle):
        self.events.append(("file_close", self.handles[handle]["key"], handle))
        self.closed_count += 1
        if self.closed_count == len(self.handles):
            self._restore_readback_path()
            if self.on_final_close is not None:
                self.on_final_close()
        return True

    def _install_readback_path(self):
        if self.readback_installed:
            return
        api = self
        concrete_path = type(Path())

        class SourceReadbackPath(concrete_path):
            def read_bytes(self):
                key = _path_key(self)
                if key in api.software_bytes:
                    return api.software_bytes[key]
                return super().read_bytes()

        self.readback_path = SourceReadbackPath
        self.cuv2.Path = SourceReadbackPath

        original_sha = self.original_sha

        def source_fake_sha(raw):
            for path, value in self.software_bytes.items():
                if path != _path_key(reconciliation.CUV2_RUNTIME_ORIGIN) and raw is value:
                    return reconciliation._SOFTWARE_SOURCE_PINS[
                        next(
                            source
                            for source in reconciliation._SOFTWARE_SOURCE_PINS
                            if _path_key(source) == path
                        )
                    ]
            return original_sha(raw)

        self.cuv2.sha = source_fake_sha
        self.readback_installed = True

    def _restore_readback_path(self):
        if self.readback_installed:
            self.cuv2.Path = self.original_path
            self.cuv2.sha = self.original_sha
            self.readback_installed = False

    def _get_info(self, handle, pointer):
        state = self.handles[handle]
        count = self.identity_calls.get(handle, 0) + 1
        self.identity_calls[handle] = count
        self.events.append(("identity", state["key"], count))
        if len(self.handles) == len(self.contents_by_path) and count == 2:
            self._install_readback_path()
        info = ctypes.cast(pointer, ctypes.POINTER(self.private._FILE_INFO)).contents
        info.attributes = 0
        info.volume = 1
        info.links = 1
        info.index_high = 0
        info.index_low = handle + (1 if self.change_second_identity and count == 2 else 0)
        return 1

    def _read_file(self, handle, buffer, _size, count_pointer, _overlapped):
        raw = self.handles[handle]["raw"]
        if raw:
            ctypes.memmove(buffer, raw, len(raw))
        ctypes.cast(count_pointer, ctypes.POINTER(ctypes.c_ulong)).contents.value = len(raw)
        return 1


def _bounded_public_read(path: Path, maximum: int) -> bytes:
    size = path.stat().st_size
    if size < 0 or size > maximum:
        raise RuntimeError("fake_public_source_size_invalid")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) != size or len(raw) > maximum:
        raise RuntimeError("fake_public_source_read_invalid")
    return raw


def _load_modules(monkeypatch):
    if os.name != "nt":
        pytest.skip("the actual CUv2 source uses fixed Windows path identities")

    # Import the exact production reader/supervisor chain from the pinned paths.
    names = (
        "_m01_readonly_monitor_v3.current_reader",
        "_m01_readonly_monitor_v3",
        "_m01_readonly_monitor_v2.current_types",
        "_m01_readonly_monitor_v2.job_supervisor",
        "_m01_readonly_monitor_v2.worker",
        "_m01_readonly_monitor_v2",
        "_certification.m01_private_monitor_v2",
        "_certification",
    )
    for name in names:
        sys.modules.pop(name, None)
    monkeypatch.syspath_prepend(str(VENUE))

    snapshot_raw = _bounded_public_read(CUV2_SNAPSHOT, 10 * 1024 * 1024)
    assert len(snapshot_raw) == reconciliation.CUV2_SOURCE_BYTES
    assert _sha(snapshot_raw) == reconciliation.CUV2_SOURCE_SHA256
    cuv2 = ModuleType(reconciliation.CUV2_RUNTIME_MODULE_NAME)
    cuv2.__file__ = reconciliation.CUV2_RUNTIME_ORIGIN
    sys.modules[cuv2.__name__] = cuv2
    exec(compile(snapshot_raw, cuv2.__file__, "exec", dont_inherit=True), cuv2.__dict__)

    reader = importlib.import_module("_m01_readonly_monitor_v3.current_reader")
    supervisor = reader.job_supervisor
    worker = reader.worker

    runner_path = ROOT / reconciliation.ROOT_RUNNER_RELATIVE
    runner_raw = _bounded_public_read(runner_path, 2 * 1024 * 1024)
    public_pins, software_pins, source_index_raw = _root_runner_maps(runner_raw)
    public_raw_by_path = {}
    for relative, expected_sha in public_pins.items():
        path = ROOT / relative
        raw = _bounded_public_read(path, 64 * 1024 * 1024)
        assert _sha(raw) == expected_sha, relative
        public_raw_by_path[_path_key(path)] = raw

    # The original Root runner supplies the exact three software keys and
    # pins. Opaque executable/DLL contents stay synthetic; CUv2 uses its public
    # pinned snapshot bytes.
    software_bytes = {}
    for path in software_pins:
        key = _path_key(path)
        if key == _path_key(str(Path(reconciliation.CUV2_RUNTIME_ORIGIN))):
            software_bytes[key] = snapshot_raw
        elif key == _path_key("C:/anaconda3/python.exe"):
            software_bytes[key] = b"source-fake-python-exe"
        elif key == _path_key("C:/anaconda3/python311.dll"):
            software_bytes[key] = b"source-fake-python-dll"
        else:
            raise AssertionError("pinned Root runner declared an unexpected software key")
    assert software_pins.keys() == reconciliation._SOFTWARE_SOURCE_PINS.keys()
    for key, raw in software_bytes.items():
        if key == _path_key(reconciliation.CUV2_RUNTIME_ORIGIN):
            assert _sha(raw) == reconciliation.CUV2_SOURCE_SHA256
        else:
            assert raw not in public_raw_by_path.values()

    contents_by_path = {**public_raw_by_path, **software_bytes}
    pins_by_path = {
        _path_key(ROOT / relative): expected_sha for relative, expected_sha in public_pins.items()
    }
    pins_by_path.update(
        {_path_key(path): expected_sha for path, expected_sha in software_pins.items()}
    )
    assert set(contents_by_path) == set(pins_by_path)

    fake_api = _FakeApi(contents_by_path, software_bytes)
    fake_api.cuv2 = cuv2
    fake_api.original_path = cuv2.Path
    fake_api.original_sha = cuv2.sha
    original_load = cuv2.load
    original_sha = cuv2.sha
    custody_modules = {}
    original_cli_read = {}

    def source_fake_load(relative, pin, name):
        module = original_load(relative, pin, name)
        if name == "_root_public_custody_private":
            module._API = fake_api
            fake_api.private = module
        elif name == "_root_public_custody_cli":
            original_cli_read["function"] = module._read_bounded_handle

            def fake_read_bounded_handle(api, handle, maximum):
                raw = fake_api.handles[handle]["raw"]
                if len(raw) > maximum:
                    raise RuntimeError("source_fake_read_bound")
                return raw

            module._read_bounded_handle = fake_read_bounded_handle
            custody_modules[name] = module
        else:
            raise RuntimeError("source_fake_unexpected_module")
        return module

    def entry_sha(raw):
        for path, value in software_bytes.items():
            if path != _path_key(reconciliation.CUV2_RUNTIME_ORIGIN) and raw is value:
                return next(
                    digest for source, digest in software_pins.items() if _path_key(source) == path
                )
        return original_sha(raw)

    cuv2.load = source_fake_load
    cuv2.sha = entry_sha
    try:
        scope = cuv2.held_public_sources(public_pins, software_pins)
        scope_value = scope.__enter__()
    finally:
        cuv2.load = original_load
        cuv2.sha = original_sha
        if "_root_public_custody_cli" in custody_modules:
            custody_modules["_root_public_custody_cli"]._read_bounded_handle = original_cli_read[
                "function"
            ]
    cli = scope_value[1]
    private = scope_value[0]
    assert private._API is fake_api
    assert cli._locked_file_identity.__globals__ is cli.__dict__
    assert cli._read_bounded_handle.__globals__ is cli.__dict__

    gate_path = ROOT / reconciliation.GATE_RELATIVE
    gate_raw = contents_by_path[_path_key(gate_path)]
    gate = ModuleType("_root_m01_local_lifecycle_gate_oct9")
    gate.__file__ = str(gate_path.resolve())
    sys.modules[gate.__name__] = gate
    exec(compile(gate_raw, gate.__file__, "exec", dont_inherit=True), gate.__dict__)

    module_source_bytes = {
        "cuv2": contents_by_path[_path_key(reconciliation.CUV2_RUNTIME_ORIGIN)],
        "gate": contents_by_path[_path_key(gate_path)],
        "reader": contents_by_path[_path_key(ROOT / reconciliation.READER_RELATIVE)],
        "supervisor": contents_by_path[_path_key(ROOT / reconciliation.SUPERVISOR_RELATIVE)],
        "worker": contents_by_path[_path_key(ROOT / reconciliation.WORKER_RELATIVE)],
    }
    observation_raw = _bounded_public_read(OBSERVATION_PATH, 10 * 1024 * 1024)
    retained_raw = _bounded_public_read(RETAINED_PATH, 10 * 1024 * 1024)
    observation = json.loads(observation_raw.decode("utf-8"))
    gate_observation = observation["gate_result"]
    gate_context = _production_gate_context(gate, reader, supervisor, gate_observation)
    runtime_registry = supervisor._ORPHANED_RUNTIME_HANDLE_SETS
    entry = (
        gate_context,
        reader,
        supervisor,
        gate_context.raw_kernel,
        gate_context.kernel_proxy,
        gate_context.control_reference,
        tuple(gate_context.thread_references),
        tuple(gate_context.pipe_state_references),
        tuple(gate_context.open_handles),
        runtime_registry,
    )
    gate._ORPHANED_GATE_CONTEXTS.append(entry)
    return {
        "cuv2": cuv2,
        "gate": gate,
        "reader": reader,
        "supervisor": supervisor,
        "worker": worker,
        "private": scope_value[0],
        "cli": scope_value[1],
        "scope": scope,
        "scope_value": scope_value,
        "sources": module_source_bytes,
        "custody_modules": (scope_value[0], scope_value[1]),
        "observation": gate_observation,
        "context": gate_context,
        "registry": gate._ORPHANED_GATE_CONTEXTS,
        "evidence": (observation_raw, retained_raw),
        "pins": public_pins,
        "software_pins": software_pins,
        "root_runner_raw": runner_raw,
        "source_index_raw": source_index_raw,
        "fake_api": fake_api,
        "contents_by_path": contents_by_path,
    }


@pytest.fixture
def prepared(monkeypatch):
    state = _load_modules(monkeypatch)
    yield state
    for name in (
        "_root_m01_local_cuv2_oct9",
        "_root_m01_local_lifecycle_gate_oct9",
        "_root_public_custody_private",
        "_root_public_custody_cli",
        "_m01_readonly_monitor_v3.current_reader",
        "_m01_readonly_monitor_v3",
        "_m01_readonly_monitor_v2.current_types",
        "_m01_readonly_monitor_v2.job_supervisor",
        "_m01_readonly_monitor_v2.worker",
        "_m01_readonly_monitor_v2",
        "_certification.m01_private_monitor_v2",
        "_certification",
    ):
        sys.modules.pop(name, None)


def _reconcile(state):
    return reconciliation.reconcile_normal_cuv2_source_scope(
        cuv2_module=state["cuv2"],
        source_scope=state["scope"],
        source_scope_value=state["scope_value"],
        gate_module=state["gate"],
        gate_context=state["context"],
        gate_observation=state["observation"],
        gate_context_registry=state["registry"],
        reader_module=state["reader"],
        supervisor_module=state["supervisor"],
        worker_module=state["worker"],
        custody_modules=state["custody_modules"],
        module_source_bytes=state["sources"],
        failure_evidence=state["evidence"],
        root_tty_reference=object(),
    )


def _cell(value):
    return (lambda: value).__closure__[0]


def test_exact_root_runner_maps_pass_the_cuv2_scope_verifier(prepared):
    state = prepared
    generator, exit_method = reconciliation._verify_scope(
        state["scope"],
        state["cuv2"],
        state["scope_value"],
        state["sources"],
    )

    assert len(state["pins"]) == 27
    assert len(state["software_pins"]) == 3
    assert state["pins"] == reconciliation._PUBLIC_SOURCE_PINS
    assert state["software_pins"] == reconciliation._SOFTWARE_SOURCE_PINS
    assert _sha(state["root_runner_raw"]) == state["pins"][reconciliation.ROOT_RUNNER_RELATIVE]
    assert generator is state["scope"].gen
    assert exit_method.__self__ is state["scope"]
    frame = generator.gi_frame
    assert frame is not None and frame.f_globals is state["cuv2"].__dict__
    assert frame.f_locals["pins"] is state["pins"]
    assert frame.f_locals["software_pins"] is state["software_pins"]
    runtime_key = str(Path(reconciliation.CUV2_RUNTIME_ORIGIN))
    assert runtime_key in state["software_pins"]
    raw_runtime_keys = [
        key
        for key in state["scope_value"][2]
        if _path_key(key) == _path_key(reconciliation.CUV2_RUNTIME_ORIGIN)
    ]
    assert raw_runtime_keys == [runtime_key]
    assert exit_method(None, None, None) is False


def test_exact_cuv2_scope_exits_normally_and_keeps_gate_context(prepared):
    state = prepared
    api = state["fake_api"]

    receipt = _reconcile(state)

    assert receipt.facts["status"] == "CUV2_SOURCE_SCOPE_NORMAL_EXIT_RETURNED", receipt.facts
    assert receipt.facts["source_scope_exit_attempted"] is True
    assert receipt.facts["source_scope_exit_method_verified"] is True
    assert receipt.facts["normal_postverify_exit_returned"] is True
    assert receipt.facts["source_scope_generator_closed"] is True
    assert receipt.facts["source_lease_close_state"] == "closed_after_normal_postverify"
    assert receipt.facts["retained_python_references"] is True
    assert receipt.facts["gate_context_typed"] is True
    assert receipt.facts["gate_context_projection_matches"] is True
    assert receipt.facts["gate_context_identity_unchanged"] is True
    assert receipt.facts["gate_observation_unchanged"] is True
    assert receipt.facts["gate_context_registry_unchanged"] is True
    assert receipt.facts["runtime_handle_registry_unchanged"] is True
    assert receipt.facts["compiled_module_bindings_unchanged"] is True
    assert receipt.facts["held_source_byte_bindings_unchanged"] is True
    assert receipt.facts["held_scope_raw_byte_bindings_unchanged"] is True
    assert receipt.facts["public_failure_evidence_unchanged"] is True
    assert receipt.facts["root_tty_reference_held"] is True
    assert receipt.facts["retained_context"] is True
    assert receipt.retained.gate_context is state["context"]
    assert receipt.retained.gate_observation is state["observation"]
    assert receipt.retained.gate_context_entries[0][0] is state["context"]
    assert receipt.retained.gate_context is not receipt.retained.gate_observation
    assert receipt.retained.custody_modules == state["custody_modules"]
    assert receipt.retained.public_source_bytes["cuv2"] is state["sources"]["cuv2"]
    events = [item[0] for item in api.events]
    assert "identity" in events
    assert next(
        index for index, item in enumerate(api.events) if item[0] == "identity" and item[2] == 2
    ) < events.index("file_close")
    assert api.closed_count == 30
    assert api.readback_installed is False
    assert not {"authority", "account", "job_cleanup_confirmed"} & set(receipt.facts)


def test_failed_postverify_retains_all_refs_and_preserves_failure_facts(prepared):
    state = prepared
    state["fake_api"].change_second_identity = True

    receipt = _reconcile(state)

    assert receipt.facts["status"] == "SOURCE_SCOPE_POSTCHECK_UNCONFIRMED"
    assert receipt.facts["error_category"] == "scope_exit_exception"
    assert receipt.facts["error_code"] == "source_scope_exit_failed"
    assert receipt.facts["source_scope_exit_attempted"] is True
    assert receipt.facts["source_scope_exit_method_verified"] is True
    assert receipt.facts["normal_postverify_exit_returned"] is False
    assert receipt.facts["source_scope_generator_closed"] is True
    assert receipt.facts["source_lease_close_state"] == "close_uncertain_after_scope_exception"
    assert receipt.facts["retained_python_references"] is True
    assert receipt.facts["gate_observation_unchanged"] is True
    assert receipt.facts["gate_context_typed"] is True
    assert receipt.facts["gate_context_projection_matches"] is True
    assert receipt.facts["gate_context_identity_unchanged"] is True
    assert receipt.facts["gate_context_registry_unchanged"] is True
    assert receipt.facts["runtime_handle_registry_unchanged"] is True
    assert receipt.facts["compiled_module_bindings_unchanged"] is True
    assert receipt.facts["held_source_byte_bindings_unchanged"] is True
    assert receipt.facts["held_scope_raw_byte_bindings_unchanged"] is True
    assert receipt.facts["public_failure_evidence_unchanged"] is True
    assert receipt.facts["root_tty_reference_held"] is True
    assert receipt.retained.gate_observation is state["observation"]
    assert receipt.retained.gate_context is state["context"]
    assert receipt.retained.source_scope is state["scope"]
    assert not {"authority", "account", "job_cleanup_confirmed"} & set(receipt.facts)
    assert state["fake_api"].closed_count == 30
    assert state["fake_api"].readback_installed is False


def test_duplicate_attempt_does_not_exit_source_scope_twice(prepared):
    state = prepared

    first = _reconcile(state)
    second = _reconcile(state)

    assert first.facts["source_scope_exit_attempted"] is True
    assert second.facts["status"] == "SOURCE_SCOPE_ALREADY_ATTEMPTED"
    assert second.facts["source_scope_exit_attempted"] is False
    assert second.retained is first.retained
    assert reconciliation.retained_context_count() >= 1


def test_invalid_gate_context_holds_scope_without_attempting_exit(prepared):
    state = prepared
    state["registry"].clear()

    receipt = _reconcile(state)

    assert receipt.facts["status"] == "SOURCE_SCOPE_HELD_PREFLIGHT_REJECTED"
    assert receipt.facts["error_code"] == "gate_context_registry_mismatch"
    assert receipt.facts["source_scope_exit_attempted"] is False
    assert receipt.facts["source_scope_exit_method_verified"] is False
    assert receipt.retained.source_scope is state["scope"]


def test_registry_must_hold_typed_context_separately_from_projection(prepared):
    state = prepared
    entry = state["registry"][0]
    state["registry"][0] = (state["observation"], *entry[1:])

    receipt = _reconcile(state)

    assert receipt.facts["status"] == "SOURCE_SCOPE_HELD_PREFLIGHT_REJECTED"
    assert receipt.facts["error_code"] == "gate_context_entry_mismatch"
    assert receipt.facts["source_scope_exit_attempted"] is False
    assert receipt.retained.gate_context is state["context"]
    assert receipt.retained.gate_observation is state["observation"]


def test_projection_mismatch_holds_both_typed_context_and_original_dict(prepared):
    state = prepared
    mismatched_projection = dict(state["observation"])
    mismatched_projection["phase"] = "different_finite_phase"

    receipt = reconciliation.reconcile_normal_cuv2_source_scope(
        cuv2_module=state["cuv2"],
        source_scope=state["scope"],
        source_scope_value=state["scope_value"],
        gate_module=state["gate"],
        gate_context=state["context"],
        gate_observation=mismatched_projection,
        gate_context_registry=state["registry"],
        reader_module=state["reader"],
        supervisor_module=state["supervisor"],
        worker_module=state["worker"],
        custody_modules=state["custody_modules"],
        module_source_bytes=state["sources"],
        failure_evidence=state["evidence"],
        root_tty_reference=object(),
    )

    assert receipt.facts["status"] == "SOURCE_SCOPE_HELD_PREFLIGHT_REJECTED"
    assert receipt.facts["error_code"] == "gate_context_projection_mismatch"
    assert receipt.facts["source_scope_exit_attempted"] is False
    assert receipt.retained.gate_context is state["context"]
    assert receipt.retained.gate_observation is mismatched_projection


def test_detached_gate_result_function_is_rejected_before_projection(prepared):
    state = prepared
    called = []

    def detached_result(self):
        called.append(self)
        return state["observation"]

    state["gate"]._Observation.result = detached_result
    receipt = _reconcile(state)

    assert receipt.facts["status"] == "SOURCE_SCOPE_HELD_PREFLIGHT_REJECTED"
    assert receipt.facts["error_code"] == "module_source_function_binding_mismatch"
    assert receipt.facts["source_scope_exit_attempted"] is False
    assert called == []
    assert receipt.retained.gate_context is state["context"]


def test_gate_context_projection_mutation_during_close_is_reported_uncertain(prepared):
    state = prepared
    state["fake_api"].on_final_close = lambda: setattr(
        state["context"], "error_category", "changed_during_source_close"
    )

    receipt = _reconcile(state)

    assert receipt.facts["status"] == "SOURCE_SCOPE_POSTCHECK_UNCONFIRMED"
    assert receipt.facts["normal_postverify_exit_returned"] is True
    assert receipt.facts["source_scope_generator_closed"] is True
    assert receipt.facts["source_lease_close_state"] == "closed_after_normal_postverify"
    assert receipt.facts["gate_context_identity_unchanged"] is True
    assert receipt.facts["gate_context_projection_matches"] is False
    assert receipt.retained.gate_context is state["context"]
    assert receipt.retained.gate_observation is state["observation"]
    assert receipt.facts["retained_context"] is True


def test_mutated_exact_pin_map_holds_scope_without_attempting_exit(prepared):
    state = prepared
    state["scope"].gen.gi_frame.f_locals["pins"]["scripts/fake.py"] = "0" * 64

    receipt = _reconcile(state)

    assert receipt.facts["status"] == "SOURCE_SCOPE_HELD_PREFLIGHT_REJECTED"
    assert receipt.facts["error_code"] == "cuv2_scope_pin_maps_mismatch"
    assert receipt.facts["source_scope_exit_attempted"] is False
    assert receipt.facts["retained_context"] is True


def test_callable_proxy_with_pinned_attributes_is_rejected_before_exit(prepared):
    state = prepared
    original = state["cuv2"].check

    class CallableProxy:
        def __init__(self, wrapped):
            self.__code__ = wrapped.__code__
            self.__globals__ = wrapped.__globals__

        def __call__(self, *_args, **_kwargs):
            return None

    state["cuv2"].check = CallableProxy(original)
    receipt = _reconcile(state)

    assert receipt.facts["status"] == "SOURCE_SCOPE_HELD_PREFLIGHT_REJECTED"
    assert receipt.facts["error_code"] == "module_function_binding_mismatch"
    assert receipt.facts["source_scope_exit_attempted"] is False
    assert state["scope"].gen.gi_frame is not None


def test_worker_function_rebind_with_same_globals_is_rejected_before_exit(prepared):
    state = prepared
    worker = state["worker"]
    original = worker.parse_credentials
    exec(
        compile(
            "def parse_credentials(packet):\n    return packet\n",
            worker.__file__,
            "exec",
            dont_inherit=True,
        ),
        worker.__dict__,
        worker.__dict__,
    )
    try:
        receipt = _reconcile(state)
    finally:
        worker.parse_credentials = original

    assert receipt.facts["status"] == "SOURCE_SCOPE_HELD_PREFLIGHT_REJECTED"
    assert receipt.facts["error_code"] == "module_source_function_binding_mismatch"
    assert receipt.facts["source_scope_exit_attempted"] is False


def test_worker_property_replaced_with_its_getter_is_rejected_before_exit(prepared):
    state = prepared
    owner = state["worker"]._WireReader
    descriptor = vars(owner)["partial_state_clear"]
    assert type(descriptor) is property
    owner.partial_state_clear = descriptor.fget
    try:
        receipt = _reconcile(state)
    finally:
        owner.partial_state_clear = descriptor

    assert receipt.facts["status"] == "SOURCE_SCOPE_HELD_PREFLIGHT_REJECTED"
    assert receipt.facts["error_code"] == "module_source_descriptor_mismatch"
    assert receipt.facts["source_scope_exit_attempted"] is False
    assert state["scope"].gen.gi_frame is not None


def test_worker_classmethod_replaced_with_its_function_is_rejected_before_exit(prepared):
    state = prepared
    owner = state["worker"].OKXPrivateWebSocketTransport
    descriptor = vars(owner)["connect"]
    assert type(descriptor) is classmethod
    owner.connect = descriptor.__func__
    try:
        receipt = _reconcile(state)
    finally:
        owner.connect = descriptor

    assert receipt.facts["status"] == "SOURCE_SCOPE_HELD_PREFLIGHT_REJECTED"
    assert receipt.facts["error_code"] == "module_source_descriptor_mismatch"
    assert receipt.facts["source_scope_exit_attempted"] is False
    assert state["scope"].gen.gi_frame is not None


def test_cuv2_contextmanager_wrapper_replacement_is_rejected_before_exit(prepared):
    state = prepared
    module = state["cuv2"]
    original = module.held_public_sources
    exec(
        compile(
            "def held_public_sources(*args, **kwargs):\n    return None\n",
            module.__file__,
            "exec",
            dont_inherit=True,
        ),
        module.__dict__,
        module.__dict__,
    )
    replacement = module.held_public_sources
    replacement.__wrapped__ = original.__wrapped__
    try:
        receipt = _reconcile(state)
    finally:
        module.held_public_sources = original

    assert receipt.facts["status"] == "SOURCE_SCOPE_HELD_PREFLIGHT_REJECTED"
    assert receipt.facts["error_code"] == "module_contextmanager_wrapper_binding_mismatch"
    assert receipt.facts["source_scope_exit_attempted"] is False
    assert state["scope"].gen.gi_frame is not None


def test_cuv2_contextmanager_wrapper_requires_canonical_globals_and_closure(prepared):
    state = prepared
    module = state["cuv2"]
    original = module.held_public_sources
    generator = original.__wrapped__
    expected = reconciliation.contextlib.contextmanager(generator)
    foreign_generator = FunctionType(generator.__code__, generator.__globals__)
    replacement = FunctionType(
        expected.__code__,
        module.__dict__,
        name=expected.__name__,
        argdefs=expected.__defaults__,
        closure=(_cell(foreign_generator),),
    )
    replacement.__module__ = module.__name__
    replacement.__qualname__ = original.__qualname__
    replacement.__wrapped__ = generator
    module.held_public_sources = replacement
    try:
        receipt = _reconcile(state)
    finally:
        module.held_public_sources = original

    assert receipt.facts["status"] == "SOURCE_SCOPE_HELD_PREFLIGHT_REJECTED"
    assert receipt.facts["error_code"] == "module_contextmanager_wrapper_binding_mismatch"
    assert receipt.facts["source_scope_exit_attempted"] is False
    assert state["scope"].gen.gi_frame is not None


def test_contextmanager_wrapper_closure_mutation_during_exit_blocks_postcheck(prepared):
    state = prepared
    api = state["fake_api"]
    wrapper = state["cuv2"].held_public_sources
    generator = wrapper.__wrapped__
    foreign_generator = FunctionType(generator.__code__, generator.__globals__)
    wrapper_cell = wrapper.__closure__[0]
    original_close = api.CloseHandle

    def mutate_after_last_close(handle):
        result = original_close(handle)
        if api.closed_count == len(api.handles):
            wrapper_cell.cell_contents = foreign_generator
        return result

    api.CloseHandle = mutate_after_last_close

    receipt = _reconcile(state)

    assert receipt.facts["status"] == "SOURCE_SCOPE_POSTCHECK_UNCONFIRMED"
    assert receipt.facts["source_scope_exit_attempted"] is True
    assert receipt.facts["normal_postverify_exit_returned"] is True
    assert receipt.facts["source_scope_generator_closed"] is True
    assert receipt.facts["source_lease_close_state"] == "closed_after_normal_postverify"
    assert receipt.facts["compiled_module_bindings_unchanged"] is False
    assert receipt.facts["retained_python_references"] is True
    assert receipt.facts["root_tty_reference_held"] is True
    assert api.closed_count == len(api.handles)
