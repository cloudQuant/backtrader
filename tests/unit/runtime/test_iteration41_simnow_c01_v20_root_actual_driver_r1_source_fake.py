"""Pure source-fake tests for the V20 parent close-receipt contract."""

from __future__ import annotations

import importlib
import importlib.util
import hashlib
import io
import json
import ntpath
from pathlib import Path
import sys
from types import MappingProxyType, ModuleType

import pytest


_driver_path = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / ("iteration41_simnow_c01_v20_root_actual_driver_r1.py")
)
_driver_spec = importlib.util.spec_from_file_location("_c01_v20_root_actual_driver", _driver_path)
assert _driver_spec is not None and _driver_spec.loader is not None
driver = importlib.util.module_from_spec(_driver_spec)
sys.modules[_driver_spec.name] = driver
_driver_spec.loader.exec_module(driver)
_handoff_name = "backtrader_runtime.certification_simnow_c01_rootseal_custody_v1"
_handoff_path = (
    Path(__file__).resolve().parents[3]
    / "backtrader_runtime"
    / ("certification_simnow_c01_rootseal_custody_v1.py")
)
_handoff_raw = _handoff_path.read_bytes()
_handoff_spec = importlib.util.spec_from_file_location(_handoff_name, _handoff_path)
assert _handoff_spec is not None and _handoff_spec.loader is not None
handoff = importlib.util.module_from_spec(_handoff_spec)
sys.modules[_handoff_name] = handoff
try:
    _handoff_spec.loader.exec_module(handoff)
finally:
    if sys.modules.get(_handoff_name) is handoff:
        sys.modules.pop(_handoff_name, None)


def _frame():
    return handoff.RootContentFrame(b"fake-frame-bytes", handoff._FRAME_FACTORY)


def _blocked_projection():
    return {
        "case_id": "C01",
        "certification": "BLOCKED",
        "mode": "C01_NATIVE_TD_READ_V20",
        "profile": "C01_NATIVE_TD_READ_V20",
        "reason": "child_root_handoff_blocked",
        "write_policy": "NO_WRITE",
        "writes": 0,
        "receipt_type": None,
        "receipt_verified": False,
        "source_closure_verified": False,
        "root_postverify_verified": False,
        "request_count": 0,
        "query_callback_count": 0,
        "snapshot_count": 0,
        "write_invocation_count": 0,
        "outer_job_empty": None,
        "stdout_eof": None,
        "stderr_eof": None,
        "stderr_empty": None,
        "job_handles_closed": None,
        "reader_threads_joined": None,
        "cleanup_verified": None,
    }


def _candidate_projection():
    value = _blocked_projection()
    value.update(
        {
            "reason": "candidate_root_handoff_written",
            "receipt_type": "C01RootContentCustodyReceipt",
            "receipt_verified": True,
            "source_closure_verified": True,
            "root_postverify_verified": True,
            "request_count": 8,
            "query_callback_count": 6,
            "snapshot_count": 2,
        }
    )
    return value


def _process(**changes):
    values = {
        "frame": None,
        "handoff_module": handoff,
        "call_nonce": object(),
        "stdout_raw": json.dumps(
            _blocked_projection(), sort_keys=True, separators=(",", ":")
        ).encode("ascii"),
        "stderr_raw": b"",
        "child_pid": 42,
        "exit_code": 0,
        "launch_count": 1,
        "job_assigned_before_resume": True,
        "job_empty": True,
        "stdout_eof": True,
        "stderr_eof": True,
        "frame_eof": True,
        "job_handles_closed": True,
        "reader_threads_joined": True,
        "overflow_observed": False,
        "reader_failed": False,
        "forced_termination": False,
    }
    values.update(changes)
    if values["frame"] is not None and "stdout_raw" not in changes:
        values["stdout_raw"] = json.dumps(
            _candidate_projection(), sort_keys=True, separators=(",", ":")
        ).encode("ascii")
    return driver.create_c01_v20_parent_process_receipt(**values)


def _source_maps():
    source_bytes = b"public source bytes"
    source_pin = hashlib.sha256(source_bytes).hexdigest()
    module = ModuleType("fake.public_source")
    module.__file__ = "D:/fake/public_source.py"
    module.__c01_source_sha256__ = source_pin
    return {
        "public_source_pins": {"public_source.py": source_pin},
        "source_modules": MappingProxyType({"public_source.py": module}),
        "source_objects": MappingProxyType({"public_source.py": MappingProxyType({})}),
        "held_source_bytes": MappingProxyType({"public_source.py": source_bytes}),
    }


def _outer_lease(monkeypatch, *, close_raises=False):
    cuv2_raw = (
        b"from contextlib import contextmanager\n"
        b"@contextmanager\n"
        b"def held_public_sources(public, software):\n"
        b"    try:\n"
        b"        yield (PRIVATE, CLI, RAW_MAP)\n"
        b"    finally:\n"
        b"        CLOSES.append('closed')\n"
        b"        if CLOSE_RAISES:\n"
        b"            raise RuntimeError('private detail')\n"
    )
    cuv2_path = "D:/fake/iteration41-root-public-custody-v2.py"
    cuv2_sha = hashlib.sha256(cuv2_raw).hexdigest()
    monkeypatch.setattr(driver, "CUV2_SOURCE_PATH", cuv2_path)
    monkeypatch.setattr(driver, "CUV2_SOURCE_SHA256", cuv2_sha)
    monkeypatch.setattr(driver, "CUV2_SOURCE_BYTES", len(cuv2_raw))

    cuv2 = ModuleType("_fake_cuv2")
    cuv2.__file__ = cuv2_path
    cuv2.__c01_source_sha256__ = cuv2_sha
    private = ModuleType("_root_public_custody_private")
    cli = ModuleType("_root_public_custody_cli")
    cuv2.__dict__.update(
        PRIVATE=private,
        CLI=cli,
        RAW_MAP={},
        CLOSES=[],
        CLOSE_RAISES=close_raises,
    )
    exec(compile(cuv2_raw, cuv2_path, "exec", dont_inherit=True), cuv2.__dict__)

    public_payload = b"fake-public-source"
    public_bytes = {"fake/public_source.py": public_payload}
    public_pins = {path: hashlib.sha256(raw).hexdigest() for path, raw in public_bytes.items()}
    software_bytes = {
        cuv2_path: cuv2_raw,
        "C:/fake/python.exe": b"fake-python",
        "C:/fake/python311.dll": b"fake-python-dll",
    }
    software_pins = {path: hashlib.sha256(raw).hexdigest() for path, raw in software_bytes.items()}
    source_root = driver._source_root_for_driver()
    raw_map = {
        driver._absolute_public_path(source_root, relative): raw
        for relative, raw in public_bytes.items()
    }
    raw_map.update(
        {driver._normalize_absolute_path(path): raw for path, raw in software_bytes.items()}
    )
    cuv2.RAW_MAP.update(raw_map)

    public_module = ModuleType("fake.public_source")
    public_module.__file__ = driver._absolute_public_path(source_root, "fake/public_source.py")
    public_module.__c01_source_sha256__ = public_pins["fake/public_source.py"]
    modules = MappingProxyType({"fake/public_source.py": public_module})
    objects = MappingProxyType(
        {"fake/public_source.py": driver._capture_source_module_objects(public_module)}
    )
    public_bytes_map = MappingProxyType(dict(public_bytes))
    lease = driver.enter_c01_v20_outer_source_lease(
        cuv2_module=cuv2,
        cuv2_source_bytes=cuv2_raw,
        public_source_pins=public_pins,
        software_source_pins=software_pins,
    )
    driver.bind_c01_v20_outer_source_modules(
        lease,
        source_modules=modules,
        source_objects=objects,
        source_pins=public_pins,
        held_source_bytes=public_bytes_map,
    )
    return lease, cuv2, public_pins, software_pins


@pytest.fixture(autouse=True)
def _isolated_driver_keepalive(monkeypatch):
    monkeypatch.setattr(driver, "_OUTER_KEEPALIVE", [])
    monkeypatch.setattr(driver, "_PARENT_NATIVE_KEEPALIVE", [])


def test_parent_process_receipt_binds_one_clean_call_and_frame():
    receipt = _process(frame=_frame())
    assert driver.validate_c01_v20_parent_process_receipt(receipt) is True
    assert receipt.frame is not None
    assert receipt.launch_count == 1
    with pytest.raises(AttributeError):
        receipt.child_pid = 100


@pytest.mark.parametrize(
    "changes",
    [
        {"exit_code": True},
        {"launch_count": 2},
        {"job_assigned_before_resume": False},
        {"job_empty": False},
        {"stdout_eof": False},
        {"stderr_eof": False},
        {"frame_eof": False},
        {"stderr_raw": b"unexpected"},
        {"job_handles_closed": False},
        {"reader_threads_joined": False},
        {"overflow_observed": True},
        {"reader_failed": True},
    ],
)
def test_process_receipt_rejects_unclean_or_boolean_coercion(changes):
    with pytest.raises(driver.RootDriverError):
        _process(**changes)


def test_forced_cleanup_receipt_is_cleanup_only_and_cannot_formalize(monkeypatch):
    lease, _cuv2, _public, _software = _outer_lease(monkeypatch)
    process = _process(forced_termination=True)
    assert driver.validate_c01_v20_parent_process_receipt(process) is True
    outer_close = driver.create_c01_v20_outer_close_receipt(
        lease=lease, parent_process_receipt=process
    )
    with pytest.raises(driver.RootDriverError, match="formal_completion_outer_close_invalid"):
        driver.complete_c01_v20_formal_result(
            frame=None,
            parent_process_receipt=process,
            wrapper_call_receipt=None,
            outer_close_receipt=outer_close,
        )


def test_outer_close_receipt_is_derived_from_one_normal_cuv2_exit(monkeypatch):
    lease, cuv2, public, software = _outer_lease(monkeypatch)
    process = _process()
    receipt = driver.create_c01_v20_outer_close_receipt(lease=lease, parent_process_receipt=process)
    assert driver.validate_c01_v20_outer_close_receipt(receipt) is True
    assert receipt.observed_held_public_count == len(public)
    assert receipt.observed_held_software_count == len(software)
    assert receipt.observed_held_count == len(public) + len(software)
    assert cuv2.CLOSES == ["closed"]
    assert driver._OUTER_KEEPALIVE == []
    assert lease.state == "closed"
    with pytest.raises(driver.RootDriverError):
        driver.create_c01_v20_outer_close_receipt(lease=lease, parent_process_receipt=process)


def test_outer_close_failure_retains_the_original_source_tuple(monkeypatch):
    lease, cuv2, _public, _software = _outer_lease(monkeypatch, close_raises=True)
    with pytest.raises(driver.RootDriverError, match="outer_source_close_uncertain"):
        driver.create_c01_v20_outer_close_receipt(lease=lease, parent_process_receipt=_process())
    assert cuv2.CLOSES == ["closed"]
    assert lease.state == "uncertain"
    assert [lease.keepalive_ref] == driver._OUTER_KEEPALIVE
    with pytest.raises(driver.RootDriverError):
        driver.create_c01_v20_outer_close_receipt(lease=lease, parent_process_receipt=_process())


def test_formal_completion_requires_closed_typed_full_source_closure(monkeypatch):
    lease, _cuv2, _public, _software = _outer_lease(monkeypatch)
    process = _process()
    outer = driver.create_c01_v20_outer_close_receipt(lease=lease, parent_process_receipt=process)

    with pytest.raises(
        driver.RootDriverError,
        match="formal_completion_source_closure_incomplete",
    ):
        driver.complete_c01_v20_formal_result(
            frame=process.frame,
            parent_process_receipt=process,
            wrapper_call_receipt=object(),
            outer_close_receipt=outer,
        )


def test_outer_close_rejects_changed_cuv2_exit_method_before_call(monkeypatch):
    lease, cuv2, _public, _software = _outer_lease(monkeypatch)
    original = lease.manager_type.__dict__["__exit__"]
    try:
        lease.manager_type.__exit__ = lambda *_args: False
        with pytest.raises(driver.RootDriverError, match="outer_source_close_precondition_failed"):
            driver.create_c01_v20_outer_close_receipt(
                lease=lease, parent_process_receipt=_process()
            )
        assert cuv2.CLOSES == []
        assert [lease.keepalive_ref] == driver._OUTER_KEEPALIVE
    finally:
        lease.manager_type.__exit__ = original


def test_outer_close_rejects_instance_shadow_and_held_byte_mutation(monkeypatch):
    lease, cuv2, _public, _software = _outer_lease(monkeypatch)
    lease.manager.__dict__["__exit__"] = lambda *_args: False
    with pytest.raises(driver.RootDriverError):
        driver.create_c01_v20_outer_close_receipt(lease=lease, parent_process_receipt=_process())
    assert cuv2.CLOSES == []
    assert [lease.keepalive_ref] == driver._OUTER_KEEPALIVE

    # A separate lease demonstrates that mutation of CUv2's original yielded
    # map is caught by identity checks before invoking its close method.
    monkeypatch.setattr(driver, "_OUTER_KEEPALIVE", [])
    lease2, cuv2_2, _public2, _software2 = _outer_lease(monkeypatch)
    public_absolute = driver._absolute_public_path(lease2.source_root, "fake/public_source.py")
    lease2.held_tuple[2][public_absolute] = b"changed"
    with pytest.raises(driver.RootDriverError):
        driver.create_c01_v20_outer_close_receipt(lease=lease2, parent_process_receipt=_process())
    assert cuv2_2.CLOSES == []
    assert [lease2.keepalive_ref] == driver._OUTER_KEEPALIVE


def test_noncanonical_or_duplicate_public_projection_is_rejected():
    with pytest.raises(driver.RootDriverError):
        _process(stdout_raw=b'{"candidate":"BLOCKED", "candidate":"PASS"}')
    with pytest.raises(driver.RootDriverError):
        _process(stdout_raw=b'{ "candidate":"BLOCKED"}')
    with pytest.raises(driver.RootDriverError):
        _process(stdout_raw=b'{"candidate":"BLOCKED"}\n')


def test_driver_object_snapshot_checks_exact_function_globals_and_code():
    objects = driver.capture_c01_v20_driver_objects(driver)
    assert driver.validate_c01_v20_driver_source_objects(driver, objects) is True
    assert objects["validate_c01_v20_parent_process_receipt.__code__"] is (
        driver.validate_c01_v20_parent_process_receipt.__code__
    )
    assert objects["validate_c01_v20_parent_process_receipt.__globals__"] is driver.__dict__

    original = driver.validate_c01_v20_parent_process_receipt
    try:
        driver.validate_c01_v20_parent_process_receipt = lambda _receipt: True
        assert driver.validate_c01_v20_driver_source_objects(driver, objects) is False
    finally:
        driver.validate_c01_v20_parent_process_receipt = original


def _run_lease(monkeypatch):
    """Build a source-only CUv2 lease around the actual launcher source."""

    cuv2_raw = (
        b"from contextlib import contextmanager\n"
        b"@contextmanager\n"
        b"def held_public_sources(public, software):\n"
        b"    yield (PRIVATE, CLI, RAW_MAP)\n"
    )
    cuv2_path = "D:/fake/iteration41-root-public-custody-v2.py"
    cuv2_sha = hashlib.sha256(cuv2_raw).hexdigest()
    monkeypatch.setattr(driver, "CUV2_SOURCE_PATH", cuv2_path)
    monkeypatch.setattr(driver, "CUV2_SOURCE_SHA256", cuv2_sha)
    monkeypatch.setattr(driver, "CUV2_SOURCE_BYTES", len(cuv2_raw))
    monkeypatch.setattr(driver, "_PYTHON_EXE_SHA256", hashlib.sha256(b"fake-python").hexdigest())
    monkeypatch.setattr(
        driver, "_PYTHON_DLL_SHA256", hashlib.sha256(b"fake-python-dll").hexdigest()
    )

    cuv2 = ModuleType("_fake_cuv2_run")
    cuv2.__file__ = cuv2_path
    cuv2.__c01_source_sha256__ = cuv2_sha
    private = ModuleType("_root_public_custody_private")
    cli = ModuleType("_root_public_custody_cli")
    cuv2.__dict__.update(PRIVATE=private, CLI=cli, RAW_MAP={})
    exec(compile(cuv2_raw, cuv2_path, "exec", dont_inherit=True), cuv2.__dict__)

    root = driver._source_root_for_driver()
    public_sources = {
        driver._DRIVER_PATH: Path(driver.__file__).read_bytes(),
        driver._WRAPPER_PATH: (
            b"def create_c01_v20_wrapper_call_receipt(*args, **kwargs):\n"
            b"    raise AssertionError('blocked child must not mint wrapper receipt')\n"
            b"def validate_c01_v20_wrapper_call_receipt(receipt):\n"
            b"    return False\n"
        ),
        driver._HANDOFF_PATH: (
            b"_FRAME_FACTORY = object()\n"
            b"_MAX_FRAME_BYTES = 18087964\n"
            b"class RootContentFrame:\n"
            b"    def __init__(self, raw, factory):\n"
            b"        self._raw = raw\n"
            b"        self._factory = factory\n"
            b"def read_c01_root_content_frame(reader):\n"
            b"    raw = reader.read(18087965)\n"
            b"    if not raw or reader.read(1): raise ValueError('frame invalid')\n"
            b"    return RootContentFrame(raw, _FRAME_FACTORY)\n"
        ),
        driver._JOB_BACKEND_PATH: (
            b"def _load_kernel32(): return None\n"
            b"def _create_job(kernel): return 1\n"
            b"def _query_job_active_processes(kernel, job): return 0\n"
            b"def _as_handle(value): return int(value)\n"
        ),
    }
    public_pins = {path: hashlib.sha256(raw).hexdigest() for path, raw in public_sources.items()}

    wrapper = ModuleType("scripts.run_simnow_c01_native_td_read_v20_root_activation_r1")
    wrapper.__file__ = driver._absolute_public_path(root, driver._WRAPPER_PATH)
    wrapper.__c01_source_sha256__ = public_pins[driver._WRAPPER_PATH]
    exec(compile(public_sources[driver._WRAPPER_PATH], wrapper.__file__, "exec"), wrapper.__dict__)
    handoff = ModuleType("backtrader_runtime.certification_simnow_c01_rootseal_custody_v1")
    handoff.__file__ = driver._absolute_public_path(root, driver._HANDOFF_PATH)
    handoff.__c01_source_sha256__ = public_pins[driver._HANDOFF_PATH]
    exec(compile(public_sources[driver._HANDOFF_PATH], handoff.__file__, "exec"), handoff.__dict__)
    backend = ModuleType("scripts.ctp_i13_i15_windows_job_backend")
    backend.__file__ = driver._absolute_public_path(root, driver._JOB_BACKEND_PATH)
    backend.__c01_source_sha256__ = public_pins[driver._JOB_BACKEND_PATH]
    exec(
        compile(public_sources[driver._JOB_BACKEND_PATH], backend.__file__, "exec"),
        backend.__dict__,
    )
    monkeypatch.setattr(
        driver, "__c01_source_sha256__", public_pins[driver._DRIVER_PATH], raising=False
    )
    modules = {
        driver._DRIVER_PATH: driver,
        driver._WRAPPER_PATH: wrapper,
        driver._HANDOFF_PATH: handoff,
        driver._JOB_BACKEND_PATH: backend,
    }
    objects = {
        path: driver._capture_source_module_objects(module) for path, module in modules.items()
    }
    software_bytes = {
        cuv2_path: cuv2_raw,
        driver._PYTHON_EXE_PATH: b"fake-python",
        driver._PYTHON_DLL_PATH: b"fake-python-dll",
    }
    software_pins = {path: hashlib.sha256(raw).hexdigest() for path, raw in software_bytes.items()}
    raw_map = {
        driver._absolute_public_path(root, path): raw for path, raw in public_sources.items()
    }
    raw_map.update(
        {driver._normalize_absolute_path(path): raw for path, raw in software_bytes.items()}
    )
    cuv2.RAW_MAP.update(raw_map)
    lease = driver.enter_c01_v20_outer_source_lease(
        cuv2_module=cuv2,
        cuv2_source_bytes=cuv2_raw,
        public_source_pins=public_pins,
        software_source_pins=software_pins,
    )
    driver.bind_c01_v20_outer_source_modules(
        lease,
        source_modules=MappingProxyType(modules),
        source_objects=MappingProxyType(objects),
        source_pins=public_pins,
        held_source_bytes=MappingProxyType(public_sources),
    )
    return lease, wrapper, handoff, backend


class _FakeParentApi:
    """Deterministic native-call leaves for the fixed production launcher."""

    def __init__(
        self,
        driver_module,
        *,
        persistent_descendant=False,
        candidate=False,
        fail_pipe_at=None,
        create_process_failed=False,
        partial_pipe_failure=False,
        unobserved_job=False,
        fail_stream_at=None,
        create_process_exception=None,
        forced_cleanup_complete=False,
        process_wait_timeout=False,
        wait_exception=None,
        uncertain_fdclose_at=None,
        uncertain_fdconversion_at=None,
        query_exception=None,
        windows_directory_exception=None,
    ):
        self.driver = driver_module
        blocked = _blocked_projection()
        blocked["reason"] = "child_root_handoff_blocked"
        if candidate:
            blocked = _candidate_projection()
        self.outputs = {
            100: json.dumps(blocked, sort_keys=True, separators=(",", ":")).encode("ascii"),
            102: b"",
            104: b"candidate-frame-bytes" if candidate else b"",
        }
        self.next_handle = 100
        self.events = []
        self.persistent_descendant = persistent_descendant
        self.process_open = True
        self.thread_open = True
        self.job_open = True
        self.job_terminated = False
        self.child_call = None
        self.fail_pipe_at = fail_pipe_at
        self.create_process_failed = create_process_failed
        self.pipe_count = 0
        self.partial_pipe_failure = partial_pipe_failure
        self.unobserved_job = unobserved_job
        self.fail_stream_at = fail_stream_at
        self.create_process_exception = create_process_exception
        self.stream_count = 0
        self.forced_cleanup_complete = forced_cleanup_complete
        self.process_wait_timeout = process_wait_timeout
        self.process_wait_count = 0
        self.wait_exception = wait_exception
        self.uncertain_fdclose_at = uncertain_fdclose_at
        self.uncertain_fdconversion_at = uncertain_fdconversion_at
        self.query_exception = query_exception
        self.windows_directory_exception = windows_directory_exception

    def create_pipe(self, state):
        self.pipe_count += 1
        if self.fail_pipe_at == self.pipe_count:
            if self.partial_pipe_failure:
                read, write = self.next_handle, self.next_handle + 1
                self.next_handle += 2
                driver._track_owned_handle(state, read)
                driver._track_owned_handle(state, write)
                state["pipe_setup_uncertain"] = True
                self.events.append(("partial_pipe", read, write))
                raise RuntimeError("fake pipe call uncertain")
            raise driver._ParentLaunchError("parent_pipe_create_failed")
        read, write = self.next_handle, self.next_handle + 1
        self.next_handle += 2
        state.setdefault("pipes", []).append((read, write))
        driver._track_owned_handle(state, read)
        driver._track_owned_handle(state, write)
        self.events.append(("pipe", read, write))
        return read, write

    def open_null_input(self, state):
        self.events.append(("stdin", 90))
        driver._track_owned_handle(state, 90)
        return 90

    def open_read_stream(self, handle, state):
        self.stream_count += 1
        if self.uncertain_fdconversion_at == self.stream_count:
            state.setdefault("fd_conversion_uncertain_handles", set()).add(handle)
            raise driver._ParentLaunchError("parent_reader_handle_conversion_failed")
        stream = io.BytesIO(self.outputs[handle])
        if self.uncertain_fdclose_at == self.stream_count:
            state.setdefault("fd_owned_handles", set()).add(handle)
            state.setdefault("fd_close_uncertain_handles", set()).add(handle)
            state.setdefault("fd_by_handle", {})[handle] = 123
            state.setdefault("owned_handles", set()).discard(handle)
            raise driver._ParentLaunchError(
                "parent_reader_stream_cleanup_uncertain", uncertain=True
            )
        if self.fail_stream_at == self.stream_count:
            # Model open_osfhandle success followed by fdopen failure where
            # os.close(fd) succeeded. The raw HANDLE is closed through the fd.
            state.setdefault("fd_owned_handles", set()).add(handle)
            state.setdefault("fd_closed_handles", set()).add(handle)
            state.setdefault("stream_handles", set()).add(handle)
            state.setdefault("owned_handles", set()).discard(handle)
            state.setdefault("fd_owned_handles", set()).discard(handle)
            state.setdefault("fd_by_handle", {})[handle] = 123
            driver._record_handle_closed(state, handle)
            state.setdefault("fd_by_handle", {}).pop(handle, None)
            raise driver._ParentLaunchError("parent_reader_handle_conversion_failed")
        state.setdefault("fd_owned_handles", set()).add(handle)
        state.setdefault("stream_handle_by_id", {})[id(stream)] = handle
        state.setdefault("stream_handles", set()).add(handle)
        state.setdefault("owned_handles", set()).discard(handle)
        return stream

    def create_job(self):
        self.events.append(("create_job", 70))
        return 70

    def windows_directory(self):
        if self.windows_directory_exception is not None:
            raise self.windows_directory_exception
        return "C:\\Windows"

    def create_suspended_process(
        self, *, job, inherited_handles, stdio_handles, argv, cwd, env, state
    ):
        self.child_call = {
            "job": job,
            "inherited_handles": inherited_handles,
            "stdio_handles": stdio_handles,
            "argv": argv,
            "cwd": cwd,
            "env": dict(env),
        }
        self.events.append(("create_suspended", job, inherited_handles, stdio_handles))
        state["create_attempted"] = True
        state["process_create_call_count"] = 1
        if self.create_process_exception is not None:
            state["process_creation_uncertain"] = True
            state["attribute_list_open"] = True
            state["attribute_setup_uncertain"] = True
            state["process_info"] = object()
            raise self.create_process_exception
        state["process_creation_uncertain"] = False
        return self.driver._ParentProcessControls(
            job=job,
            process=71,
            thread=72,
            pid=73,
            tid=74,
            attribute_list=object(),
            attribute_storage=object(),
            job_array=object(),
            handle_array=object(),
            created=not self.create_process_failed,
        )

    def delete_attributes(self, controls, state):
        self.events.append(("delete_attributes",))
        driver._forget_attribute_state(state)
        return True

    def delete_attribute_state(self, state):
        self.events.append(("delete_attribute_state",))
        driver._forget_attribute_state(state)
        return True

    def query_job_active(self, job):
        self.events.append(("query_job", job, self.process_open))
        if self.query_exception is not None:
            raise self.query_exception
        if self.unobserved_job and not self.process_open:
            return None
        if self.persistent_descendant and not self.process_open:
            if self.job_terminated and self.forced_cleanup_complete:
                return 0
            return 1
        return 1 if self.process_open else 0

    def sleep(self, seconds):
        # Keep timeout regressions fast while allowing the monotonic deadline
        # to advance in the real parent helper.
        import time

        time.sleep(min(seconds, 0.001))

    def close_handle(self, handle):
        self.events.append(("close", handle))
        if handle == 71:
            self.process_open = False
        elif handle == 72:
            self.thread_open = False
        elif handle == 70:
            self.job_open = False
        return True

    def resume_thread(self, thread):
        self.events.append(("resume", thread))
        return True

    def wait_process(self, process, timeout_ms):
        self.events.append(("wait", process, timeout_ms))
        self.process_wait_count += 1
        if self.wait_exception is not None:
            raise self.wait_exception
        if self.process_wait_timeout and self.process_wait_count == 1:
            return "timeout"
        return "signaled"

    def get_exit_code(self, process):
        return 0 if self.outputs[104] else 2

    def terminate_job(self, job):
        self.events.append(("terminate_job", job))
        self.job_terminated = True
        return True


def test_fixed_launcher_uses_separate_frame_handle_and_closes_process_before_job_query(monkeypatch):
    lease, _wrapper, handoff, _backend = _run_lease(monkeypatch)
    api = _FakeParentApi(driver)
    receipt = driver._supervise_fixed_child(lease, api, object())
    assert driver.validate_c01_v20_parent_process_receipt(receipt) is True
    assert receipt.frame is None
    assert receipt.exit_code == 2
    assert receipt.launch_count == 1
    assert api.child_call["inherited_handles"] == (90, 101, 103, 105)
    assert api.child_call["stdio_handles"] == (90, 101, 103)
    assert api.child_call["argv"][:5] == ("C:/anaconda3/python.exe", "-I", "-S", "-B", "-c")
    assert "_c01_v20_frame_channel_handle=105" in api.child_call["argv"][5]
    assert "sys.flags.optimize != 0" in api.child_call["argv"][5]
    normalized_wrapper = ntpath.normpath(ntpath.join(driver._ROOT_DIRECTORY, driver._WRAPPER_PATH))
    assert normalized_wrapper == driver._CHILD_WRAPPER_PATH
    assert f"sys.argv=[{normalized_wrapper!r}]" in api.child_call["argv"][5]
    assert f"runpy.run_path({normalized_wrapper!r}" in api.child_call["argv"][5]
    assert api.child_call["cwd"] == "D:/source_code/backtrader"
    assert set(api.child_call["env"]) == {"SystemRoot", "WINDIR", "PATH", "TEMP", "TMP"}
    close_process = api.events.index(("close", 71))
    query_after_close = next(
        index
        for index, event in enumerate(api.events)
        if event[0] == "query_job" and index > close_process
    )
    assert query_after_close > close_process
    assert api.events.index(("resume", 72)) < api.events.index(("close", 72))
    assert api.job_open is False
    assert driver._PARENT_NATIVE_KEEPALIVE == []


def test_fixed_launcher_retains_job_and_source_when_descendant_keeps_job_active(monkeypatch):
    lease, _wrapper, _handoff, _backend = _run_lease(monkeypatch)
    ticks = [0.0]

    def advancing_clock():
        ticks[0] += 0.02
        return ticks[0]

    monkeypatch.setattr(driver.time, "monotonic", advancing_clock)
    api = _FakeParentApi(driver, persistent_descendant=True)
    with pytest.raises(driver.RootDriverError, match="parent_job_descendant_retained"):
        driver._supervise_fixed_child(lease, api, object())
    assert api.process_open is False
    assert api.job_open is True
    assert any(event[0] == "terminate_job" for event in api.events)
    assert not any(event == ("close", 70) for event in api.events)
    assert len(driver._PARENT_NATIVE_KEEPALIVE) == 1
    assert driver._PARENT_NATIVE_KEEPALIVE[0][0] is lease


def test_fixed_launcher_keeps_private_candidate_frame_on_separate_pipe(monkeypatch):
    lease, _wrapper, _handoff, _backend = _run_lease(monkeypatch)
    api = _FakeParentApi(driver, candidate=True)
    receipt = driver._supervise_fixed_child(lease, api, object())
    assert driver.validate_c01_v20_parent_process_receipt(receipt) is True
    assert receipt.exit_code == 0
    assert receipt.frame is not None
    assert receipt.frame._raw == b"candidate-frame-bytes"
    assert api.child_call["inherited_handles"][-1] == 105
    assert 105 not in api.child_call["stdio_handles"]
    assert all(handle not in api.child_call["inherited_handles"] for handle in (100, 102, 104))


def test_fixed_launcher_closes_partial_pipe_setup_before_child_creation(monkeypatch):
    lease, _wrapper, _handoff, _backend = _run_lease(monkeypatch)
    api = _FakeParentApi(driver, fail_pipe_at=2)
    with pytest.raises(driver.RootDriverError, match="parent_pipe_create_failed"):
        driver._supervise_fixed_child(lease, api, object())
    assert ("close", 100) in api.events
    assert ("close", 101) in api.events
    assert api.child_call is None
    assert driver._PARENT_NATIVE_KEEPALIVE == []


def test_fixed_launcher_cleans_empty_job_after_create_process_failure(monkeypatch):
    lease, _wrapper, _handoff, _backend = _run_lease(monkeypatch)
    api = _FakeParentApi(driver, create_process_failed=True)
    with pytest.raises(driver.RootDriverError, match="parent_process_create_failed"):
        driver._supervise_fixed_child(lease, api, object())
    assert api.process_open is False
    assert api.thread_open is False
    assert api.job_open is False
    assert ("close", 71) in api.events
    assert ("close", 72) in api.events
    assert ("close", 70) in api.events
    assert not any(event[0] == "resume" for event in api.events)
    assert driver._PARENT_NATIVE_KEEPALIVE == []


class _AttributeCleanupApi:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = 0

    def delete_attribute_state(self, state):
        self.calls += 1
        if self.fail:
            state["attribute_setup_uncertain"] = True
            return False
        driver._forget_attribute_state(state)
        return True


def test_attribute_list_state_is_cleared_only_after_confirmed_delete():
    state = {
        "controls": None,
        "pipes": [],
        "streams": [],
        "attribute_list": object(),
        "attribute_storage": object(),
        "job_array": object(),
        "handle_array": object(),
        "attribute_list_open": True,
        "attribute_setup_uncertain": False,
    }
    api = _AttributeCleanupApi()
    assert driver._cleanup_unstarted_native_call(api, state) is True
    assert api.calls == 1
    assert state["attribute_list_open"] is False
    assert state["attribute_setup_uncertain"] is False
    assert not any(
        key in state for key in ("attribute_list", "attribute_storage", "job_array", "handle_array")
    )


def test_failed_attribute_list_delete_keeps_all_storage_referenced():
    refs = {
        "attribute_list": object(),
        "attribute_storage": object(),
        "job_array": object(),
        "handle_array": object(),
    }
    state = {
        "controls": None,
        "pipes": [],
        "streams": [],
        **refs,
        "attribute_list_open": True,
        "attribute_setup_uncertain": False,
    }
    api = _AttributeCleanupApi(fail=True)
    assert driver._cleanup_unstarted_native_call(api, state) is False
    assert state["attribute_setup_uncertain"] is True
    assert all(state[key] is value for key, value in refs.items())


def test_partial_pipe_exception_retains_every_observed_handle(monkeypatch):
    lease, _wrapper, _handoff, _backend = _run_lease(monkeypatch)
    api = _FakeParentApi(driver, fail_pipe_at=2, partial_pipe_failure=True)
    with pytest.raises(RuntimeError, match="fake pipe call uncertain"):
        driver._supervise_fixed_child(lease, api, object())
    retained_lease, state = driver._PARENT_NATIVE_KEEPALIVE[0]
    assert retained_lease is lease
    assert state["pipe_setup_uncertain"] is True
    assert state["owned_handles"] == {100, 101, 102, 103}
    assert not any(event[0] == "close" for event in api.events)


def test_fdopen_failure_does_not_close_transferred_raw_handle_twice(monkeypatch):
    lease, _wrapper, _handoff, _backend = _run_lease(monkeypatch)
    api = _FakeParentApi(driver, fail_stream_at=2)
    with pytest.raises(driver.RootDriverError, match="parent_reader_handle_conversion_failed"):
        driver._supervise_fixed_child(lease, api, object())
    closed_values = [event[1] for event in api.events if event[0] == "close"]
    assert 102 not in closed_values
    assert driver._PARENT_NATIVE_KEEPALIVE == []


@pytest.mark.parametrize("failure_option", ["uncertain_fdclose_at", "uncertain_fdconversion_at"])
def test_uncertain_fd_ownership_is_retained_without_raw_handle_close(monkeypatch, failure_option):
    lease, _wrapper, _handoff, _backend = _run_lease(monkeypatch)
    api = _FakeParentApi(driver, **{failure_option: 2})
    with pytest.raises(driver.RootDriverError):
        driver._supervise_fixed_child(lease, api, object())
    retained_lease, state = driver._PARENT_NATIVE_KEEPALIVE[0]
    assert retained_lease is lease
    assert 102 not in [event[1] for event in api.events if event[0] == "close"]
    if failure_option == "uncertain_fdclose_at":
        assert 102 in state["fd_close_uncertain_handles"]
    else:
        assert 102 in state["fd_conversion_uncertain_handles"]


def test_unobserved_job_count_does_not_authorize_termination(monkeypatch):
    lease, _wrapper, _handoff, _backend = _run_lease(monkeypatch)
    api = _FakeParentApi(driver, unobserved_job=True)
    with pytest.raises(driver.RootDriverError, match="parent_job_zero_unobserved"):
        driver._supervise_fixed_child(lease, api, object())
    assert not any(event[0] == "terminate_job" for event in api.events)
    assert len(driver._PARENT_NATIVE_KEEPALIVE) == 1


def test_job_query_baseexception_is_preserved_with_native_state_retained(monkeypatch):
    lease, _wrapper, _handoff, _backend = _run_lease(monkeypatch)
    interruption = KeyboardInterrupt("fake job query interruption")
    api = _FakeParentApi(driver, query_exception=interruption)
    with pytest.raises(KeyboardInterrupt) as caught:
        driver._supervise_fixed_child(lease, api, object())
    assert caught.value is interruption
    retained_lease, state = driver._PARENT_NATIVE_KEEPALIVE[0]
    assert retained_lease is lease
    assert state["controls"] is not None
    assert state["job"] == 70
    assert not any(event[0] == "terminate_job" for event in api.events)


def test_cleanup_baseexception_does_not_mask_prelaunch_failure(monkeypatch):
    lease, _wrapper, _handoff, _backend = _run_lease(monkeypatch)
    primary = driver.RootDriverError("windows_directory_unavailable")
    cleanup_interruption = KeyboardInterrupt("fake cleanup interruption")
    api = _FakeParentApi(
        driver,
        windows_directory_exception=primary,
        query_exception=cleanup_interruption,
    )

    with pytest.raises(driver.RootDriverError) as caught:
        driver._supervise_fixed_child(lease, api, object())

    assert caught.value is primary
    assert caught.value.code == "windows_directory_unavailable"
    assert caught.value.__cause__ is cleanup_interruption
    assert len(driver._PARENT_NATIVE_KEEPALIVE) == 1
    retained_lease, state = driver._PARENT_NATIVE_KEEPALIVE[0]
    assert retained_lease is lease
    assert state["job"] == 70
    assert state["controls"] is None
    assert not any(event[0] == "terminate_job" for event in api.events)


def test_confirmed_forced_cleanup_closes_source_but_stays_blocked(monkeypatch):
    lease, _wrapper, _handoff, _backend = _run_lease(monkeypatch)
    api = _FakeParentApi(driver, process_wait_timeout=True, forced_cleanup_complete=True)
    process = driver._supervise_fixed_child(lease, api, object())
    assert process.forced_termination is True
    assert driver.validate_c01_v20_parent_process_receipt(process) is True
    outer_close = driver.create_c01_v20_outer_close_receipt(
        lease=lease, parent_process_receipt=process
    )
    result = driver._forced_cleanup_blocked_result(outer_close)
    assert result["certification"] == "BLOCKED"
    assert result["formal_c01_pass"] is False
    assert result["official_c01_pass_count"] == 0
    assert result["forced_cleanup"] is True
    assert result["outer_close_verified"] is True
    assert result["cleanup_verified"] is True
    assert driver._OUTER_KEEPALIVE == []
    assert driver._PARENT_NATIVE_KEEPALIVE == []


def test_wait_baseexception_retains_process_job_readers_and_source(monkeypatch):
    lease, _wrapper, _handoff, _backend = _run_lease(monkeypatch)
    interruption = KeyboardInterrupt("fake wait interruption")
    api = _FakeParentApi(driver, wait_exception=interruption)
    with pytest.raises(KeyboardInterrupt) as caught:
        driver._supervise_fixed_child(lease, api, object())
    assert caught.value is interruption
    retained_lease, state = driver._PARENT_NATIVE_KEEPALIVE[0]
    assert retained_lease is lease
    assert state["controls"].process == 71
    assert state["job"] == 70
    assert len(state["captures"]) == 3
    assert state["lease"] is lease
    assert not any(event == ("close", 70) for event in api.events)


def test_createprocess_exception_is_preserved_and_native_setup_retained(monkeypatch):
    lease, _wrapper, _handoff, _backend = _run_lease(monkeypatch)
    failure = RuntimeError("synthetic CreateProcessW exception")
    api = _FakeParentApi(driver, create_process_exception=failure)
    with pytest.raises(RuntimeError) as caught:
        driver._supervise_fixed_child(lease, api, object())
    assert caught.value is failure
    retained_lease, state = driver._PARENT_NATIVE_KEEPALIVE[0]
    assert retained_lease is lease
    assert state["process_creation_uncertain"] is True
    assert state["process_create_call_count"] == 1
    assert state["process_info"] is not None
    assert state["attribute_list_open"] is True
    assert state["attribute_setup_uncertain"] is True
    assert not any(event == ("delete_attributes",) for event in api.events)


def test_one_lease_cannot_launch_twice(monkeypatch):
    lease, _wrapper, _handoff, _backend = _run_lease(monkeypatch)
    first_api = _FakeParentApi(driver)
    driver._supervise_fixed_child(lease, first_api, object())
    second_api = _FakeParentApi(driver)
    with pytest.raises(driver.RootDriverError, match="parent_activation_already_consumed"):
        driver._supervise_fixed_child(lease, second_api, object())
    assert second_api.events == []


def test_retained_native_call_blocks_new_lease_before_api_creation(monkeypatch):
    lease, _wrapper, _handoff, _backend = _run_lease(monkeypatch)
    driver._PARENT_NATIVE_KEEPALIVE.append((object(), {"retained": True}))
    with pytest.raises(driver.RootDriverError, match="parent_activation_already_consumed"):
        driver.run_root_activation(lease)
    assert driver._PARENT_NATIVE_KEEPALIVE
