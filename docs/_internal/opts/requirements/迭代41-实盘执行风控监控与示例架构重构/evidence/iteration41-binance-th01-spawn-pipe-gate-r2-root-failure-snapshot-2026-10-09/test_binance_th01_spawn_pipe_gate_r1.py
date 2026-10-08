"""Source-fake checks for the TH01 cold-source spawn gate.

This suite calls the pinned production worker body inline with fake HTTP and
Pipe leaves only. It does not spawn a process, create an OS pipe, read private
inputs, or call a provider. Root owns the separate real spawn/Pipe gate.
"""

from __future__ import annotations

import hashlib
import importlib.util
import multiprocessing
from pathlib import Path
import pickle
import socket
import subprocess
import sys
import time
from types import FunctionType, ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
GATE_PATH = ROOT / "scripts" / "iteration41_binance_th01_spawn_pipe_gate_r1.py"


def _load_gate_module() -> ModuleType:
    name = "_iteration41_binance_th01_spawn_pipe_gate_r1_sourcefake"
    spec = importlib.util.spec_from_file_location(name, GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_gate_module()


class _FakePipe:
    def __init__(self) -> None:
        self.frames = []
        self.closed = False

    def send(self, frame) -> None:
        assert not self.closed
        assert not self.frames
        self.frames.append(frame)

    def close(self) -> None:
        self.closed = True


def _load_owner_through_current_launcher():
    raw = gate._gate_read_pinned_launcher()
    assert hashlib.sha256(raw).hexdigest() == gate.GATE_LAUNCHER_SHA256
    name = "_iteration41_th01_worker_sourcefake"
    module = ModuleType(name)
    module.__file__ = str(gate.GATE_LAUNCHER_PATH)
    module.__package__ = ""
    sys.modules[name] = module
    namespace = module.__dict__
    exec(compile(raw, str(gate.GATE_LAUNCHER_PATH), "exec", dont_inherit=True), namespace)
    candidate = namespace["_CANDIDATE_MODULE"]
    assert len(candidate.source_preflight(namespace["ROOT"])) == 3
    candidate._verify_candidate_source_binding()
    worker = namespace["_root_fixed_signed_get_worker"]
    assert worker.__module__ == namespace["__name__"]
    assert Path(worker.__code__.co_filename).resolve() == namespace["OWNER_PATH"].resolve()
    return namespace


def test_pinned_launcher_cold_loads_owner_candidate_and_public_dependencies():
    originals = gate._gate_install_synthetic_transport()
    try:
        namespace = _load_owner_through_current_launcher()
    finally:
        gate._gate_restore_transport(originals)

    assert namespace["__th01_verified_owner_source_sha256__"] == namespace["OWNER_SHA256"]
    assert namespace["_CANDIDATE_MODULE"].__th01_verified_candidate_source_sha256__ == (
        namespace["CANDIDATE_SHA256"]
    )
    assert "backtrader_runtime" not in sys.modules
    assert "certification_roundtrip_private" not in sys.modules


def test_spawn_child_bootstrap_registers_exact_owner_namespace(monkeypatch):
    originals = gate._gate_install_synthetic_transport()
    source_guards = gate._gate_install_source_guards()
    child = ModuleType("__mp_main__")
    child.__file__ = str(GATE_PATH)
    child.__package__ = ""
    monkeypatch.setitem(sys.modules, "__mp_main__", child)
    guards_active_during_bootstrap = False
    try:
        qa = gate._gate_bootstrap_current_sources(child.__dict__)
        guards_active_during_bootstrap = (
            source_guards["meta_finder"] in sys.meta_path
            and child.__dict__["_CANDIDATE_MODULE"].__th01_verified_candidate_source_sha256__
            == child.__dict__["CANDIDATE_SHA256"]
        )
    finally:
        gate._gate_restore_source_guards(source_guards)
        gate._gate_restore_transport(originals)

    worker = child.__dict__["_root_fixed_signed_get_worker"]
    loaded_child = sys.modules["__mp_main__"]
    assert qa == {"launcher_source_qa": False, "child_source_qa": True}
    assert worker.__module__ == "__mp_main__"
    assert worker.__globals__ is loaded_child.__dict__
    assert pickle.loads(pickle.dumps(worker)) is worker
    assert loaded_child.__dict__["__th01_verified_owner_source_sha256__"] == (
        loaded_child.__dict__["OWNER_SHA256"]
    )
    assert loaded_child.__dict__["_CANDIDATE_MODULE"].__th01_verified_candidate_source_sha256__ == (
        loaded_child.__dict__["CANDIDATE_SHA256"]
    )
    assert guards_active_during_bootstrap is True
    assert source_guards["meta_finder"] not in sys.meta_path


def test_production_worker_body_uses_one_fixed_synthetic_https_read():
    before = len(gate._GateFakeHTTPSConnection.instances)
    originals = gate._gate_install_synthetic_transport()
    network_guard_installed = False
    try:
        namespace = _load_owner_through_current_launcher()
        network_guard_installed = socket.create_connection is gate._gate_deny_network
        pipe = _FakePipe()
        now_ms = int(time.time() * 1000)
        query = {"startTime": now_ms - 5000, "endTime": now_ms - 1000, "limit": 1000}
        namespace["_root_fixed_signed_get_worker"](
            pipe,
            "all_orders_in_window",
            query,
            gate.GATE_SYNTHETIC_KEY,
            gate.GATE_SYNTHETIC_SECRET,
            now_ms - 60_000,
            time.monotonic() + 7.0,
        )
    finally:
        gate._gate_restore_transport(originals)

    assert pipe.closed is True
    assert len(pipe.frames) == 1
    status, body, complete, reason, actual_query, started_ms, completed_ms = pipe.frames[0]
    assert (status, body, complete, reason) == (200, b"[]", True, None)
    assert set(actual_query) == {"startTime", "endTime", "limit", "recvWindow", "timestamp"}
    assert started_ms <= actual_query["timestamp"] <= completed_ms
    assert "signature" not in actual_query
    assert network_guard_installed is True
    created = gate._GateFakeHTTPSConnection.instances[before:]
    assert len(created) == 1
    assert created[0]._request_seen is True and created[0].closed is True
    assert created[0]._response is not None and created[0]._response.body == b"[]"


def test_synthetic_transport_denies_dns_and_direct_socket_connects():
    originals = gate._gate_install_synthetic_transport()
    try:
        with pytest.raises(gate._GateBlocked):
            socket.getaddrinfo("example.invalid", 443)
        with pytest.raises(gate._GateBlocked):
            socket.socket.connect(None, ("example.invalid", 443))
        with pytest.raises(gate._GateBlocked):
            socket.socket.connect_ex(None, ("example.invalid", 443))
        with pytest.raises(gate._GateBlocked):
            socket.create_connection(("example.invalid", 443), timeout=0.1)
    finally:
        gate._gate_restore_transport(originals)


def test_child_spawn_flags_keep_isolated_s_but_omit_interactive_i():
    import multiprocessing.util

    actual = multiprocessing.util._args_from_interpreter_flags
    fake_sys = SimpleNamespace(
        flags=SimpleNamespace(
            debug=0,
            inspect=1,
            interactive=1,
            dont_write_bytecode=1,
            no_site=1,
            verbose=0,
            bytes_warning=0,
            quiet=0,
            isolated=1,
            ignore_environment=1,
            no_user_site=1,
            safe_path=1,
            dev_mode=False,
        ),
        warnoptions=[],
        _xoptions={},
    )
    synthetic_globals = dict(actual.__globals__)
    synthetic_globals["sys"] = fake_sys
    synthetic_globals["_optim_args_from_interpreter_flags"] = lambda: []
    simulated = FunctionType(actual.__code__, synthetic_globals)()

    assert gate._gate_child_spawn_flags_safe() is True
    assert actual.__module__ == "subprocess"
    assert Path(actual.__code__.co_filename).name.lower() == "subprocess.py"
    assert simulated == ["-B", "-S", "-I"]
    assert "-i" not in simulated


def test_gate_source_is_fixed_and_cannot_invoke_root_account_factory():
    source = GATE_PATH.read_text(encoding="utf-8")
    assert "--root-local-synthetic-worker-gate" in source
    assert "_run_root_fixed_signed_get" in source
    assert "create_root_read_candidate" not in source
    assert "protected_env" not in source
    assert "_private_helper(" not in source
    assert 'GATE_SYNTHETIC_KEY = "PUBLIC_SYNTHETIC_KEY"' in source
    assert '"formal_case_pass": False' in source


def test_source_guards_allow_public_sources_and_block_private_native_and_launch_surfaces():
    import builtins

    originals = gate._gate_install_source_guards()
    try:
        with builtins.open(GATE_PATH, "rb") as stream:
            assert stream.read(16)
        with pytest.raises(PermissionError):
            builtins.open(ROOT / ".env", "rb")
        with pytest.raises(PermissionError):
            gate.io.open(ROOT / "private-captures" / "sample.json", "rb")
        if callable(originals["io_open_code"]):
            with pytest.raises(PermissionError):
                gate.io.open_code(ROOT / ".env")
        with pytest.raises(PermissionError):
            gate.os.open(ROOT / "secrets.yaml", gate.os.O_RDONLY)
        with pytest.raises(ImportError):
            originals["meta_finder"].find_spec("ctypes")
        with pytest.raises(ImportError):
            originals["meta_finder"].find_spec("backtrader_runtime")
        with pytest.raises(PermissionError):
            gate.sqlite3.connect(":memory:")
        with pytest.raises(PermissionError):
            subprocess.Popen(["this-command-is-never-run"])
        with pytest.raises(PermissionError):
            multiprocessing.Process(target=lambda: None)
        # This module-level alias is bound at import time and bypasses a later
        # monkeypatch of BaseContext.Pipe unless it is denied explicitly.
        with pytest.raises(PermissionError):
            multiprocessing.Pipe(duplex=False)
        with pytest.raises(PermissionError):
            multiprocessing.get_context("spawn")
        with pytest.raises(PermissionError):
            multiprocessing.context.SpawnContext().Pipe(duplex=False)
        with pytest.raises(PermissionError):
            multiprocessing.context.SpawnContext().Process(target=lambda: None)
        with pytest.raises(PermissionError):
            multiprocessing.connection.Pipe(duplex=False)
        with pytest.raises(PermissionError):
            multiprocessing.process.BaseProcess.start(object())
        with pytest.raises(PermissionError):
            gate.os.system("this-command-is-never-run")
    finally:
        gate._gate_restore_source_guards(originals)

    assert multiprocessing.Pipe is originals["multiprocessing_pipe"]


def test_spawn_capability_accepts_only_the_fixed_target_and_arguments(monkeypatch):
    class Endpoint:
        pass

    class FakeProcess:
        pass

    class FakeContext:
        def __init__(self):
            self.pipe_calls = 0
            self.process_calls = []

        def Pipe(self, *, duplex):
            self.pipe_calls += 1
            return Endpoint(), Endpoint()

        def Process(self, **kwargs):
            self.process_calls.append(kwargs)
            return FakeProcess()

    endpoint_refs = []
    process_refs = []
    context = FakeContext()
    target = object()
    query = {"startTime": 100, "endTime": 200, "limit": 1000}
    monkeypatch.setattr(gate, "_root_fixed_signed_get_worker", target, raising=False)
    monkeypatch.setattr(gate, "_GATE_EXPECTED_QUERY", query, raising=False)
    monkeypatch.setattr(gate, "_GATE_EXPECTED_HISTORY_START_MS", 50, raising=False)
    monkeypatch.setattr(gate, "_GATE_ACTIVE_ENDPOINTS", endpoint_refs)
    monkeypatch.setattr(gate, "_GATE_ACTIVE_PROCESSES", process_refs)
    old_capability = gate._GATE_SYNTHETIC_CAPABILITY[0]
    gate._GATE_SYNTHETIC_CAPABILITY[0] = True
    try:
        observed = gate._GateObservedSpawnContext(context, endpoint_refs, process_refs)

        parent, child = observed.Pipe(duplex=False)
        assert (parent, child) == tuple(endpoint_refs)
        deadline = time.monotonic() + 6.0
        process = observed.Process(
            target=target,
            args=(
                child,
                "all_orders_in_window",
                query,
                gate.GATE_SYNTHETIC_KEY,
                gate.GATE_SYNTHETIC_SECRET,
                50,
                deadline,
            ),
            name="th01-fixed-signed-read",
            daemon=True,
        )
        assert isinstance(process, gate._GateObservedSpawnProcess)
        assert len(context.process_calls) == 1
        with pytest.raises(PermissionError):
            observed.Pipe(duplex=True)
        with pytest.raises(PermissionError):
            observed.Process(target=object(), args=(), name="other", daemon=True)
    finally:
        gate._GATE_SYNTHETIC_CAPABILITY[0] = old_capability


def test_public_multiprocessing_context_routes_only_through_fake_leaves():
    class Endpoint:
        pass

    class FakeProcess:
        pass

    originals = gate._gate_install_source_guards()
    endpoint_refs = []
    process_refs = []
    old_endpoints = gate._GATE_ACTIVE_ENDPOINTS
    old_processes = gate._GATE_ACTIVE_PROCESSES
    old_target = getattr(gate, "_root_fixed_signed_get_worker", None)
    old_query = gate._GATE_EXPECTED_QUERY
    old_history = gate._GATE_EXPECTED_HISTORY_START_MS
    old_capability = gate._GATE_SYNTHETIC_CAPABILITY[0]
    original_base_context_pipe = originals["base_context_pipe"]
    original_spawn_factory = originals["spawn_context_process"]
    gate._GATE_ACTIVE_ENDPOINTS = endpoint_refs
    gate._GATE_ACTIVE_PROCESSES = process_refs
    target = object()
    query = {"startTime": 100, "endTime": 200, "limit": 1000}
    gate._root_fixed_signed_get_worker = target
    gate._GATE_EXPECTED_QUERY = query
    gate._GATE_EXPECTED_HISTORY_START_MS = 50
    gate._GATE_SYNTHETIC_CAPABILITY[0] = True
    originals["base_context_pipe"] = lambda context, duplex=True: (Endpoint(), Endpoint())
    originals["spawn_context_process"] = lambda **kwargs: FakeProcess()
    try:
        observed = multiprocessing.get_context("spawn")
        parent, child = observed.Pipe(duplex=False)
        process = observed.Process(
            target=target,
            args=(
                child,
                "all_orders_in_window",
                query,
                gate.GATE_SYNTHETIC_KEY,
                gate.GATE_SYNTHETIC_SECRET,
                50,
                time.monotonic() + 6.0,
            ),
            name="th01-fixed-signed-read",
            daemon=True,
        )
        assert isinstance(process, gate._GateObservedSpawnProcess)
        assert len(endpoint_refs) == 2 and endpoint_refs == [parent, child]
        assert process_refs == [process]
    finally:
        gate._GATE_SYNTHETIC_CAPABILITY[0] = old_capability
        gate._GATE_ACTIVE_ENDPOINTS = old_endpoints
        gate._GATE_ACTIVE_PROCESSES = old_processes
        gate._GATE_EXPECTED_QUERY = old_query
        gate._GATE_EXPECTED_HISTORY_START_MS = old_history
        if old_target is None:
            gate.__dict__.pop("_root_fixed_signed_get_worker", None)
        else:
            gate._root_fixed_signed_get_worker = old_target
        originals["base_context_pipe"] = original_base_context_pipe
        originals["spawn_context_process"] = original_spawn_factory
        gate._gate_restore_source_guards(originals)


def test_uncertain_worker_cleanup_retains_owner_and_forbids_host_exit():
    class Endpoint:
        closed = False

    owner = {"_ACTIVE_ROOT_FIXED_WORKERS": [object()]}
    old_owner_refs = list(gate.GATE_RETAINED_OWNER_NAMESPACES)
    old_resource_refs = list(gate.GATE_RETAINED_GATE_RESOURCES)
    old_keep = gate._GATE_KEEP_HOST_OPEN
    try:
        assert gate._gate_retain_owner_if_uncertain(owner, [Endpoint()], []) is True
        assert any(value is owner for value in gate.GATE_RETAINED_OWNER_NAMESPACES)
        assert gate._gate_exit_permitted() is False
        assert gate._GATE_KEEP_HOST_OPEN is True
    finally:
        gate.GATE_RETAINED_OWNER_NAMESPACES[:] = old_owner_refs
        gate.GATE_RETAINED_GATE_RESOURCES[:] = old_resource_refs
        gate._GATE_KEEP_HOST_OPEN = old_keep


def test_root_callable_refuses_before_worker_setup_without_interactive_tty(monkeypatch):
    monkeypatch.setattr(gate, "_GATE_ATTEMPTED", False)
    monkeypatch.setattr(gate, "_gate_root_tty_ready", lambda: False)
    result = gate._root_local_synthetic_worker_gate()
    assert result["status"] == "BLOCKED_SYNTHETIC_GATE"
    assert result["first_failure"] == "root_tty_required"
    assert result["provider_call"] is False
    assert gate._GATE_ACTIVE_ENDPOINTS is None
    assert gate._GATE_ACTIVE_PROCESSES is None
    assert gate._gate_exit_permitted() is True


def test_post_call_source_recheck_detects_a_changed_candidate_reader():
    namespace = _load_owner_through_current_launcher()
    good = gate._gate_post_call_source_pins(namespace)
    assert all(good.values())
    original_reader = namespace["_read_pinned_public_source"]

    def changed_candidate_reader(path, expected_sha256, maximum):
        raw = original_reader(path, expected_sha256, maximum)
        if path == namespace["CANDIDATE_PATH"]:
            return raw + b"tampered"
        return raw

    namespace["_read_pinned_public_source"] = changed_candidate_reader
    bad = gate._gate_post_call_source_pins(namespace)
    assert bad["launcher"] is True
    assert bad["owner"] is True
    assert bad["candidate"] is False
    assert bad["candidate_dependencies"] is True
