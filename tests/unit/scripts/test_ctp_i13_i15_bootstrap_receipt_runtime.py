"""Source-only tests for the fixed receipt-writer runtime factory."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import ntpath
import os
import sys
import types
from pathlib import Path, PureWindowsPath

import pytest


ROOT = Path(__file__).resolve().parents[3]
REQUEST_ID = "a" * 32
NONCE = "d" * 32
RECEIPT_ROOT = r"C:\ProgramData\Backtrader\Iteration41\ctp-readonly-guardian\receipts"
FIXED_ROOT = r"C:\ProgramData\Backtrader\Iteration41\ctp-readonly-guardian"
DESCRIPTOR_PATH = FIXED_ROOT + r"\deployment.json"
DESCRIPTOR_RAW = b"fixed reviewed descriptor bytes"
_SHA_NAMES = (
    "descriptor_sha256",
    "source_manifest_sha256",
    "runtime_manifest_sha256",
    "dependency_manifest_sha256",
    "python_sha256",
    "i13_pin_sha256",
    "i15_pin_sha256",
    "bootstrap_sha256",
    "worker_sha256",
    "coordinator_sha256",
    "receipt_writer_sha256",
    "token_bootstrap_sha256",
)


def _load_script_module(module_name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


_builder = _load_script_module(
    "_i13_bootstrap_receipt_runtime_builder",
    ROOT / "scripts" / "ctp_i13_source_manifest_candidate.py",
)
_receipt_writer = _load_script_module(
    "_i13_bootstrap_receipt_runtime_role",
    ROOT / "scripts" / "ctp_i13_i15_readonly_receipt_writer.py",
)


def _runtime_helper_namespace(*, now: int = 100):
    source = _builder._bootstrap_runner_source().decode("ascii")
    events = []
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_readonly_bootstrap_run_receipt_writer"
    )

    class FakeTime:
        value = now

        @classmethod
        def monotonic_ns(cls):
            return cls.value

    class FakeProtectedPaths:
        def __init__(self, _trusted_sids):
            self.paths = set()
            self.files = {}
            self.create_calls = []
            self.close_calls = 0
            self.create_error = None
            self.corrupt_readback = False
            self.on_create = None

        def add_paths(self, paths, **_kwargs):
            for path in paths:
                canonical = ntpath.normcase(ntpath.normpath(path))
                if canonical not in {
                    ntpath.normcase(RECEIPT_ROOT),
                    ntpath.normcase(ntpath.join(RECEIPT_ROOT, REQUEST_ID + ".json")),
                    ntpath.normcase(DESCRIPTOR_PATH),
                }:
                    raise AssertionError("runtime attempted a non-fixed path")
                self.paths.add(canonical)

        def verify_current(self):
            return None

        def create_new_receipt(self, directory_path, request_id, raw):
            events.append("create_new")
            self.create_calls.append((directory_path, request_id, raw))
            if self.create_error is not None:
                raise self.create_error
            target = ntpath.join(directory_path, request_id + ".json")
            key = ntpath.normcase(ntpath.normpath(target))
            if key in self.files:
                raise OSError("already exists")
            self.files[key] = raw
            if self.on_create is not None:
                self.on_create()
            return target

        def read_file(self, path, *, max_bytes):
            key = ntpath.normcase(ntpath.normpath(path))
            if key == ntpath.normcase(DESCRIPTOR_PATH):
                return DESCRIPTOR_RAW
            if key not in self.paths or key not in self.files:
                raise AssertionError("readback was not opened through the fixed lease")
            raw = self.files[key]
            if len(raw) > max_bytes:
                raise AssertionError("readback cap bypass")
            return b"corrupt" if self.corrupt_readback else raw

        def close(self):
            events.append("source_lease_close")
            self.close_calls += 1

    class FakeSourceLease:
        def __init__(self):
            self.verify_calls = 0
            self.close_calls = 0

        def verify_current(self):
            self.verify_calls += 1

        def close(self):
            self.close_calls += 1

    class FakeSourceSeal:
        candidate = "i13_md"
        manifest_sha256 = "2" * 64
        source_root = Path("D:/sealed-source")

        def __init__(self, files):
            self.files = files
            self.source_lease = FakeSourceLease()

        def close(self):
            events.append("source_seal_close")
            self.source_lease.close()

    class FakeDependencySeal:
        manifest_sha256 = "4" * 64
        verify_calls = 0

        def verify_current(self):
            self.verify_calls += 1

        def close(self):
            events.append("dependency_seal_close")
            self.close_calls = getattr(self, "close_calls", 0) + 1

    class FakeRuntimeSeal:
        manifest_sha256 = "3" * 64
        verify_calls = 0

        def verify_current(self):
            self.verify_calls += 1

        def close(self):
            events.append("runtime_seal_close")
            self.close_calls = getattr(self, "close_calls", 0) + 1

    class FakeFinder:
        def __init__(self, seal, runtime_seal, dependency_seal, channel_module):
            self._seal = seal
            self._runtime_closure = runtime_seal
            self._dependency_finder = dependency_seal
            self._channel_module = channel_module
            self.end_calls = []

        def _owns_fixed_bootstrap_support(self, fullname, module):
            return (
                fullname == "scripts.ctp_i13_i15_worker_output_channel"
                and module is self._channel_module
            )

        def _end_fixed_role_module(self, role, module):
            self.end_calls.append((role, module))

        def detach_runtime_closure(self, seal):
            if self._runtime_closure is not seal:
                raise AssertionError("runtime closure detach mismatch")
            self._runtime_closure = None

        def detach_dependency_finder(self, finder):
            if self._dependency_finder is not finder:
                raise AssertionError("dependency finder detach mismatch")
            self._dependency_finder = None

    class FakeReceiptPaths(FakeProtectedPaths):
        instance = None

        def __init__(self, trusted_sids):
            super().__init__(trusted_sids)
            FakeReceiptPaths.instance = self

    files = {
        "scripts/ctp_i13_i15_readonly_preflight_bootstrap.py": "8" * 64,
        "scripts/ctp_i13_i15_readonly_preflight_worker.py": "9" * 64,
        "scripts/ctp_i13_i15_readonly_request_coordinator.py": "a" * 64,
        "scripts/ctp_i13_i15_readonly_receipt_writer.py": "b" * 64,
        "scripts/ctp_i13_i15_readonly_token_bootstrap.py": "c" * 64,
    }
    source_seal = FakeSourceSeal(files)
    dependency_seal = FakeDependencySeal()
    runtime_seal = FakeRuntimeSeal()
    channel_module = types.ModuleType("scripts.ctp_i13_i15_worker_output_channel")
    channel_module.frames = []

    def _write_bounded_frame(raw, *, nonce, expected_server_pid, deadline_monotonic_ns):
        if (
            type(raw) is not bytes
            or len(raw) < 5
            or int.from_bytes(raw[:4], "big", signed=False) != len(raw) - 4
        ):
            raise ValueError("channel_frame_prefix_invalid")
        channel_module.frames.append(
            (raw, nonce, expected_server_pid, deadline_monotonic_ns)
        )

    channel_module._write_bounded_frame = _write_bounded_frame
    finder = FakeFinder(source_seal, runtime_seal, dependency_seal, channel_module)
    parent_facts = types.SimpleNamespace(
        candidates={
            "i13_md": {"pin_sha256": "5" * 64},
            "i15_td": {"pin_sha256": "6" * 64},
        }
    )
    descriptor = types.SimpleNamespace(
        descriptor_sha256=hashlib.sha256(DESCRIPTOR_RAW).hexdigest(),
        python_sha256="7" * 64,
        service_sid="S-1-5-80-100",
    )
    anchor_ns = {
        "_program_data_path": lambda: r"C:\ProgramData",
        "FIXED_PROGRAMDATA_RELATIVE": PureWindowsPath(
            r"Backtrader\Iteration41\ctp-readonly-guardian"
        ),
        "FIXED_RECEIPT_DIRECTORY": "receipts",
        "FIXED_DESCRIPTOR_NAME": "deployment.json",
        "FIXED_DEPENDENCY_MANIFEST_NAME": "dependencies.json",
        "FIXED_RUNTIME_MANIFEST_NAME": "runtime.json",
        "_SYSTEM_SID": "S-1-5-18",
        "_ADMINISTRATORS_SID": "S-1-5-32-544",
        "_MAX_DESCRIPTOR_BYTES": 64 * 1024,
        "_ProtectedWindowsPaths": FakeReceiptPaths,
    }

    def _fixed_paths(program_data):
        fixed = ntpath.join(
            program_data, *anchor_ns["FIXED_PROGRAMDATA_RELATIVE"].parts
        )
        return (
            fixed,
            ntpath.join(fixed, "deployment.json"),
            ntpath.join(fixed, "auth.key"),
            ntpath.join(fixed, "dependencies.json"),
            ntpath.join(fixed, "runtime.json"),
            ntpath.join(fixed, "receipts"),
        )

    anchor_ns["_fixed_paths"] = _fixed_paths
    anchor_paths = FakeProtectedPaths(frozenset({"S-1-5-18", "S-1-5-32-544"}))
    anchor_paths.add_paths((DESCRIPTOR_PATH,))
    anchor_paths.files[ntpath.normcase(DESCRIPTOR_PATH)] = DESCRIPTOR_RAW
    deployment = {
        "descriptor_sha256": descriptor.descriptor_sha256,
        "source_manifest_sha256": source_seal.manifest_sha256,
        "runtime_manifest_sha256": runtime_seal.manifest_sha256,
        "dependency_manifest_sha256": dependency_seal.manifest_sha256,
        "python_sha256": descriptor.python_sha256,
        "i13_pin_sha256": parent_facts.candidates["i13_md"]["pin_sha256"],
        "i15_pin_sha256": parent_facts.candidates["i15_td"]["pin_sha256"],
        "bootstrap_sha256": files[
            "scripts/ctp_i13_i15_readonly_preflight_bootstrap.py"
        ],
        "worker_sha256": files["scripts/ctp_i13_i15_readonly_preflight_worker.py"],
        "coordinator_sha256": files[
            "scripts/ctp_i13_i15_readonly_request_coordinator.py"
        ],
        "receipt_writer_sha256": files[
            "scripts/ctp_i13_i15_readonly_receipt_writer.py"
        ],
        "token_bootstrap_sha256": files[
            "scripts/ctp_i13_i15_readonly_token_bootstrap.py"
        ],
    }
    summary = {
        "schema": "ctp_i13_i15_readonly_worker_summary.v1",
        "identity": {
            "account_scope": "redacted",
            "provider": "ctp",
            "environment": "simnow",
            "trading_day": "20260927",
            "connection_generation": 1,
        },
        "query_digests": [
            [name, "e" * 64]
            for name in (
                "account",
                "commission_rates",
                "instruments",
                "margin_rates",
                "orders",
                "positions",
                "trades",
            )
        ],
        "snapshot_sha256": "f" * 64,
    }
    clean_job = {
        "process_created": True,
        "job_assignment_observed": True,
        "launcher_resumed": True,
        "launcher_exit_observed": True,
        "launcher_exit_code": 0,
        "job_termination_requested": False,
        "job_termination_call_succeeded": None,
        "job_empty_observed": True,
        "containment": "verified",
        "controls_retained": False,
    }
    raw_binding = {
        "schema": _receipt_writer.RECEIPT_BINDING_SCHEMA,
        "request_id": REQUEST_ID,
        "deadline_monotonic_ns": 1000,
        "deployment": deployment,
        "work_result": {
            "schema": _receipt_writer.COORDINATOR_OUTPUT_SCHEMA,
            "request_id": REQUEST_ID,
            "state": "observed",
            "reason": "completed",
            "worker_observation": summary,
            "worker_facts": dict(clean_job),
        },
        "coordinator_job": dict(clean_job),
        "receipt_output_channel": {"nonce": NONCE, "server_pid": 4321},
    }
    normalized_binding = {
        "_readonly_role": "receipt_writer",
        "_readonly_role_binding": raw_binding,
        "_deployment": deployment,
        "request_id": REQUEST_ID,
        "deadline_monotonic_ns": 1000,
    }
    namespace = {
        "SealedSourceFinder": FakeFinder,
        "_open_fixed_readonly_role_module": lambda *_args: _receipt_writer,
        "_require_clean_after_install": lambda *_args, **_kwargs: None,
        "_readonly_bootstrap_digest": lambda value: (
            type(value) is str
            and len(value) == 64
            and value != "0" * 64
            and all(char in "0123456789abcdef" for char in value)
        ),
        "hashlib": __import__("hashlib"),
        "ntpath": ntpath,
        "sys": sys,
        "time": FakeTime,
    }
    exec(
        compile(
            ast.Module(body=[function], type_ignores=[]),
            "<receipt-writer-runtime-test>",
            "exec",
        ),
        namespace,
    )
    return types.SimpleNamespace(
        run=namespace["_readonly_bootstrap_run_receipt_writer"],
        time=FakeTime,
        anchor_ns=anchor_ns,
        descriptor=descriptor,
        parent_facts=parent_facts,
        source_seal=source_seal,
        finder=finder,
        dependency_seal=dependency_seal,
        runtime_seal=runtime_seal,
        anchor_paths=anchor_paths,
        support_modules={
            "scripts/ctp_i13_i15_worker_output_channel.py": channel_module
        },
        binding=normalized_binding,
        raw_binding=raw_binding,
        role_module=_receipt_writer,
        channel_module=channel_module,
        receipt_paths=lambda: FakeReceiptPaths.instance,
        fixed_paths=FakeReceiptPaths,
        namespace=namespace,
        files=files,
        deployment=deployment,
        clean_job=clean_job,
        events=events,
    )


def _run(harness, monkeypatch, *, raw_binding=None, role_module=None):
    module_name = "scripts.ctp_i13_i15_worker_output_channel"
    monkeypatch.setitem(sys.modules, module_name, harness.channel_module)
    harness.namespace["_open_fixed_readonly_role_module"] = lambda *_args: (
        role_module or harness.role_module
    )
    return harness.run(
        harness.binding,
        raw_binding=harness.raw_binding if raw_binding is None else raw_binding,
        anchor_ns=harness.anchor_ns,
        descriptor=harness.descriptor,
        parent_facts=harness.parent_facts,
        source_seal=harness.source_seal,
        source_finder=harness.finder,
        dependency_seal=harness.dependency_seal,
        runtime_seal=harness.runtime_seal,
        anchor_paths=harness.anchor_paths,
        support_modules=harness.support_modules,
    )


def _parse_outer_binding(monkeypatch, raw_binding):
    raw_text = json.dumps(raw_binding, sort_keys=True, separators=(",", ":"))
    env = {
        "PATH": r"C:\Python311",
        "SYSTEMROOT": r"C:\Windows",
        "WINDIR": r"C:\Windows",
        "BT_I13_READONLY_BOOTSTRAP_BINDING": raw_text,
    }
    monkeypatch.setattr(os, "environ", env)
    source = _builder._bootstrap_runner_source().decode("ascii")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_readonly_bootstrap_binding"
    )

    def pairs_no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def valid_digest(value):
        return (
            type(value) is str
            and len(value) == 64
            and value != "0" * 64
            and all(char in "0123456789abcdef" for char in value)
        )

    namespace = {
        "_READONLY_BOOTSTRAP_BINDING_ENV": "BT_I13_READONLY_BOOTSTRAP_BINDING",
        "_READONLY_BOOTSTRAP_BINDING_SCHEMA": (
            "ctp_i13_i15_readonly_preflight_bootstrap_binding.v3"
        ),
        "_readonly_bootstrap_pairs": pairs_no_duplicates,
        "_readonly_bootstrap_digest": valid_digest,
        "os": os,
        "json": json,
        "time": types.SimpleNamespace(monotonic_ns=lambda: 100),
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<binding-test>", "exec"), namespace)
    return namespace["_readonly_bootstrap_binding"]()


def test_outer_cleanup_accepts_factory_detach_but_rejects_replacement():
    source = _builder._bootstrap_runner_source().decode("ascii")
    tree = ast.parse(source)
    names = {
        "_readonly_bootstrap_detach_runtime_closure",
        "_readonly_bootstrap_detach_dependency_finder",
    }
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert {node.name for node in functions} == names

    class FakeFinder:
        def __init__(self):
            self._runtime_closure = None
            self._dependency_finder = None
            self.detached = []

        def detach_runtime_closure(self, seal):
            assert self._runtime_closure is seal
            self.detached.append(("runtime", seal))
            self._runtime_closure = None

        def detach_dependency_finder(self, finder):
            assert self._dependency_finder is finder
            self.detached.append(("dependency", finder))
            self._dependency_finder = None

    namespace = {"ValueError": ValueError}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<cleanup-test>", "exec"), namespace)
    detach_runtime = namespace["_readonly_bootstrap_detach_runtime_closure"]
    detach_dependency = namespace["_readonly_bootstrap_detach_dependency_finder"]

    finder = FakeFinder()
    expected_runtime = object()
    expected_dependency = object()
    finder._runtime_closure = expected_runtime
    finder._dependency_finder = expected_dependency
    detach_runtime(finder, expected_runtime)
    detach_dependency(finder, expected_dependency)
    # The outer finally can safely see the leases already detached by the writer role.
    detach_runtime(finder, expected_runtime)
    detach_dependency(finder, expected_dependency)
    assert finder.detached == [
        ("runtime", expected_runtime),
        ("dependency", expected_dependency),
    ]

    finder._runtime_closure = object()
    with pytest.raises(ValueError, match="runtime_closure_replaced"):
        detach_runtime(finder, expected_runtime)
    finder._dependency_finder = object()
    with pytest.raises(ValueError, match="dependency_finder_replaced"):
        detach_dependency(finder, expected_dependency)


def test_fixed_receipt_writer_uses_only_derived_create_new_target_and_reads_back(
    monkeypatch,
):
    harness = _runtime_helper_namespace()
    result = _run(harness, monkeypatch)

    paths = harness.receipt_paths()
    assert result == 0
    assert len(paths.create_calls) == 1
    directory, request_id, raw = paths.create_calls[0]
    assert directory == RECEIPT_ROOT
    assert request_id == REQUEST_ID
    assert paths.files[ntpath.normcase(ntpath.join(RECEIPT_ROOT, REQUEST_ID + ".json"))] == raw
    assert ntpath.normcase(ntpath.join(RECEIPT_ROOT, REQUEST_ID + ".json")) in paths.paths
    assert len(harness.channel_module.frames) == 1
    frame, nonce, server_pid, deadline = harness.channel_module.frames[0]
    assert (nonce, server_pid, deadline) == (NONCE, 4321, 1000)
    output = _receipt_writer.parse_receipt_writer_frame(
        frame[4:], expected_request_id=REQUEST_ID, expected_nonce=NONCE
    )
    assert output["state"] == "observed"
    assert output["receipt_created"] is True
    assert output["receipt_sha256"] == hashlib.sha256(raw).hexdigest()
    assert harness.events.index("runtime_seal_close") < harness.events.index("create_new")
    assert harness.events.index("dependency_seal_close") < harness.events.index("create_new")
    assert harness.events.index("source_lease_close") < harness.events.index("create_new")
    assert harness.events.index("source_seal_close") < harness.events.index("create_new")
    assert paths.close_calls == 1
    assert harness.finder.end_calls == [("receipt_writer", harness.role_module)]


def test_receipt_writer_rejects_caller_path_and_duplicate_create(monkeypatch):
    harness = _runtime_helper_namespace()
    forged = dict(harness.raw_binding, receipt_path=r"C:\caller\chosen.json")
    with pytest.raises(ValueError, match="binding_fields"):
        _parse_outer_binding(monkeypatch, forged)
    with pytest.raises(_receipt_writer.ReceiptWriterError, match="receipt_binding_fields_invalid"):
        _run(harness, monkeypatch, raw_binding=forged)
    assert harness.receipt_paths() is None

    normalized, process_env = _parse_outer_binding(monkeypatch, harness.raw_binding)
    assert normalized["_readonly_role"] == "receipt_writer"
    assert normalized["_readonly_role_binding"] == harness.raw_binding
    assert normalized["_deployment"] == harness.deployment
    assert process_env["path"] == r"C:\Python311"

    harness = _runtime_helper_namespace()
    real_role = harness.role_module

    class ReentryRole:
        parse_receipt_writer_binding = staticmethod(real_role.parse_receipt_writer_binding)
        encode_receipt_writer_frame = staticmethod(real_role.encode_receipt_writer_frame)

        @staticmethod
        def main(raw, api):
            result = real_role.main(raw, api)
            with pytest.raises(ValueError, match="receipt_write_binding_invalid"):
                api.persist_fixed_receipt(REQUEST_ID, b"second write")
            return result

    assert _run(harness, monkeypatch, role_module=ReentryRole) == 0
    paths = harness.receipt_paths()
    assert len(paths.create_calls) == 1
    assert len(harness.channel_module.frames) == 1


def test_receipt_writer_deadline_after_create_sends_no_output(monkeypatch):
    harness = _runtime_helper_namespace()
    paths_factory = harness.anchor_ns["_ProtectedWindowsPaths"]
    original_init = paths_factory.__init__

    def _init_and_expire_after_create(self, trusted_sids):
        original_init(self, trusted_sids)
        self.on_create = lambda: setattr(harness.time, "value", 1000)

    monkeypatch.setattr(paths_factory, "__init__", _init_and_expire_after_create)
    assert _run(harness, monkeypatch) == 2
    paths = harness.receipt_paths()
    assert len(paths.create_calls) == 1
    assert harness.channel_module.frames == []
    assert paths.close_calls == 1


def test_receipt_writer_create_exception_is_unknown_and_baseexception_cleans_up(
    monkeypatch,
):
    harness = _runtime_helper_namespace()
    paths_factory = harness.anchor_ns["_ProtectedWindowsPaths"]
    original_init = paths_factory.__init__

    def _init_with_create_error(self, trusted_sids):
        original_init(self, trusted_sids)
        self.create_error = OSError("synthetic create failure")

    monkeypatch.setattr(paths_factory, "__init__", _init_with_create_error)
    assert _run(harness, monkeypatch) == 2
    paths = harness.receipt_paths()
    assert len(paths.create_calls) == 1
    assert len(harness.channel_module.frames) == 1
    output = _receipt_writer.parse_receipt_writer_frame(
        harness.channel_module.frames[0][0][4:],
        expected_request_id=REQUEST_ID,
        expected_nonce=NONCE,
    )
    assert output["state"] == "unknown"
    assert output["receipt_created"] is False
    assert output["receipt_sha256"] is None

    harness = _runtime_helper_namespace()

    class FatalWrite(BaseException):
        pass

    paths_factory = harness.anchor_ns["_ProtectedWindowsPaths"]
    original_init = paths_factory.__init__

    def _init_with_baseexception(self, trusted_sids):
        original_init(self, trusted_sids)
        self.create_error = FatalWrite("synthetic fatal write failure")

    monkeypatch.setattr(paths_factory, "__init__", _init_with_baseexception)
    with pytest.raises(FatalWrite):
        _run(harness, monkeypatch)
    assert harness.receipt_paths().close_calls == 1
    assert harness.finder.end_calls == [("receipt_writer", harness.role_module)]


def test_receipt_writer_execution_lease_close_failure_persists_only_unknown(
    monkeypatch,
):
    harness = _runtime_helper_namespace()
    harness.runtime_seal.close = lambda: (_ for _ in ()).throw(OSError("close failure"))

    assert _run(harness, monkeypatch) == 2
    paths = harness.receipt_paths()
    assert len(paths.create_calls) == 1
    raw = paths.create_calls[0][2]
    receipt = json.loads(raw.decode("ascii"))
    assert receipt["state"] == "unknown"
    assert receipt["reason"] == "deployment_execution_lease_close_failed"
    assert len(harness.channel_module.frames) == 1
    output = _receipt_writer.parse_receipt_writer_frame(
        harness.channel_module.frames[0][0][4:],
        expected_request_id=REQUEST_ID,
        expected_nonce=NONCE,
    )
    assert output["state"] == "unknown"
    assert output["receipt_created"] is True
