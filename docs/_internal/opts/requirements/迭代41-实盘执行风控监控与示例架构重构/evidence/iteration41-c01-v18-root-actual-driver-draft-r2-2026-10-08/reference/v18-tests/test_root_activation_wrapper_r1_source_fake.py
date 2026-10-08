"""Fake-only outer Root activation checks for the C01 V18 wrapper.

These tests use temporary artifacts and fake Windows/private ports. They do
not establish native, account, provider, or formal SimNow acceptance.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import time
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
WRAPPER_PATH = ROOT / "scripts" / "run_simnow_c01_native_td_read_v18_root_activation_r1.py"
ENTRY_PATH = ROOT / "backtrader_runtime" / "certification_simnow_c01_root_entry_v18.py"
CERTIFICATION_PATH = (
    ROOT
    / "examples"
    / "000_live_certification"
    / "simnow_penetration"
    / "common"
    / "certification.py"
)
ENTRY_INTEGRATION_TEST_PATH = (
    ROOT / "tests" / "unit" / "runtime" / "test_certification_simnow_c01_root_entry_v18_source_fake.py"
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def wrapper():
    module = _load_module("_c01_v18_root_activation_source_fake", WRAPPER_PATH)
    yield module
    sys.modules.pop(module.__name__, None)


def _case_result_payload() -> dict[str, object]:
    cert = _load_module("_c01_v18_root_activation_certification_fake", CERTIFICATION_PATH)
    scenario = cert.get_certification_scenario("C01")
    required = list(scenario.required_events)
    fields = list(scenario.evidence_fields)
    sentinel = "PRIVATE_VALUE_MUST_NOT_LEAVE_THE_PROTECTED_RECEIPT"
    details = {
        "certification_evidence": {
            "front_id": 1,
            "session_id": sentinel,
            "trading_day": sentinel,
        },
        "root_admission": {
            "receipt_type": "C01RootPhysicalPostverifyProof",
            "request_count": 8,
            "query_callback_count": 6,
            "snapshot_count": 2,
            "write_invocation_count": 0,
            "biz_type_state": "observed",
        },
    }
    audit = {
        "event_type": "certification_case_result",
        "case_id": "C01",
        "status": "PASS",
        "missing_required_events": [],
        "missing_evidence_fields": [],
    }
    return {
        "case_id": "C01",
        "case_name": scenario.name,
        "status": "PASS",
        "scenario_id": "AUTH-01",
        "scenario_name": scenario.name,
        "category": scenario.category,
        "trace_id": sentinel,
        "started_at": "2026-10-08T00:00:00+00:00",
        "finished_at": "2026-10-08T00:00:01+00:00",
        "duration_seconds": 1.0,
        "simnow_env": "simulation",
        "required_events": required,
        "evidence_fields": fields,
        "pass_conditions": list(scenario.pass_conditions),
        "optional": scenario.optional,
        "observed_events": required,
        "missing_required_events": [],
        "required_events_present": True,
        "missing_evidence_fields": [],
        "evidence_fields_present": True,
        "evidence": [],
        "failure_reason": "",
        "next_action": "",
        "details": details,
        "audit_events": [audit],
    }


def _raw_case_result(wrapper, payload: dict[str, object]) -> bytes:
    return wrapper._canonical_json(payload)


def _fake_private_writer_modules(wrapper, tmp_path: Path):
    private = ModuleType("_c01_v18_root_receipt_private_writer")
    private.__file__ = str(ROOT / Path(wrapper._PRIVATE_HELPER_RELATIVE))
    private.__c01_source_sha256__ = wrapper._PRIVATE_HELPER_SHA256
    cli = ModuleType("_c01_v18_root_receipt_cli_writer")
    cli.__file__ = str(ROOT / Path(wrapper._R3_CLI_HELPER_RELATIVE))
    cli.__c01_source_sha256__ = wrapper._R3_CLI_HELPER_SHA256
    cli._known_local_app_data = lambda: str(tmp_path)

    class FakeApi:
        def current_sid(self):
            return "S-1-TEST"

        @contextmanager
        def opened(self, path, *, directory, access=None):
            yield Path(path)

        def info(self, path, *, directory):
            stat = Path(path).stat()
            return stat.st_dev, stat.st_ino

        def verify_acl(self, _handle, _sid, *, directory=False, inherited=False):
            assert inherited is False

    api = FakeApi()
    private._api = lambda: api
    private._path = lambda path: Path(path)

    @contextmanager
    def ancestors(_path, deadline=None):
        yield

    private._ancestors = ancestors

    class FakePrivateArtifactDirectory:
        def __init__(self, path, device, inode):
            self.path = Path(path)
            self.device = device
            self.inode = inode

        def write_bytes(self, name, payload):
            target = self.path / name
            if target.exists():
                raise ValueError("already_exists")
            target.write_bytes(payload)
            return _sha256(payload)

        def verify(self):
            current = self.path.stat()
            if (current.st_dev, current.st_ino) != (self.device, self.inode):
                raise ValueError("identity_changed")

    private.PrivateArtifactDirectory = FakePrivateArtifactDirectory
    return private, cli, api


def _fake_reader_ports(wrapper, tmp_path: Path, admission_id: str, artifact_directory, private, cli, api):
    @contextmanager
    def open_directory(_api, path):
        yield Path(path)

    @contextmanager
    def ancestor_locks(_path, _private, _api):
        yield

    @contextmanager
    def locked_readonly_file(path, _private, _api):
        yield Path(path), (Path(path).stat().st_dev, Path(path).stat().st_ino)

    cli._locked_readonly_file = locked_readonly_file

    def read_bounded_handle(_api, handle, maximum):
        raw = Path(handle).read_bytes()
        if len(raw) > maximum:
            raise ValueError("size_limit")
        return raw

    cli._read_bounded_handle = read_bounded_handle
    parent = artifact_directory.path.parent
    return SimpleNamespace(
        _admission_directory=artifact_directory,
        _admission_id=admission_id,
        _admission_collection_path=parent,
        _api=api,
        helpers={"private": private, "r3_cli": cli},
        issuer=SimpleNamespace(
            _admission_directory_ancestor_locks=ancestor_locks,
            _open_admission_directory=open_directory,
        ),
    )


def test_wrapper_binds_all_entry_source_rows_and_own_entry_row(wrapper):
    entry_raw = ENTRY_PATH.read_bytes()
    public, software = wrapper._entry_source_maps(entry_raw)
    public_rows, software_rows, complete = wrapper._verify_entry_public_closure(ROOT, entry_raw)

    assert len(public) == 27
    assert len(public_rows) == 27
    assert software == wrapper._EXPECTED_SOFTWARE_PINS
    assert software_rows == wrapper._EXPECTED_SOFTWARE_PINS
    assert len(complete) == 28
    assert complete[wrapper._ROOT_ENTRY_RELATIVE] == _sha256(entry_raw)
    assert complete[wrapper._ROOT_ENTRY_RELATIVE] == wrapper._ROOT_ENTRY_SHA256
    assert public[wrapper._PRIVATE_HELPER_RELATIVE] == wrapper._PRIVATE_HELPER_SHA256
    assert public[wrapper._R3_CLI_HELPER_RELATIVE] == wrapper._R3_CLI_HELPER_SHA256


def test_private_receipt_validation_returns_only_finite_counts(wrapper):
    payload = _case_result_payload()
    raw = _raw_case_result(wrapper, payload)
    projection = wrapper._validate_root_case_receipt(raw)
    text = json.dumps(projection, sort_keys=True)

    assert projection == {
        "request_count": 8,
        "query_callback_count": 6,
        "snapshot_count": 2,
        "write_invocation_count": 0,
    }
    assert "PRIVATE_VALUE_MUST_NOT_LEAVE_THE_PROTECTED_RECEIPT" not in text


def test_child_stdout_accepts_only_the_private_storage_marker(wrapper):
    marker = {
        "case_id": "C01",
        "receipt_type": "C01RootCaseResultReceipt",
        "receipt_stored": True,
        "write_policy": "NO_WRITE",
        "writes": 0,
    }
    raw = wrapper._canonical_json(marker)
    assert wrapper._validate_root_child_frame(raw, exit_code=0) == marker

    private_receipt = _raw_case_result(wrapper, _case_result_payload())
    with pytest.raises(wrapper.RootActivationError):
        wrapper._validate_root_child_frame(private_receipt, exit_code=0)


def test_main_dispatches_exact_child_argv_and_emits_only_storage_marker(
    wrapper, monkeypatch
):
    marker = {
        "case_id": "C01",
        "receipt_type": "C01RootCaseResultReceipt",
        "receipt_stored": True,
        "write_policy": "NO_WRITE",
        "writes": 0,
    }
    called = {}
    output = io.StringIO()
    monkeypatch.setattr(wrapper.sys, "stdout", output)

    def fake_child(**kwargs):
        called["kwargs"] = kwargs
        return wrapper._ActivationOutput(value=marker, exit_code=0)

    monkeypatch.setattr(wrapper, "_run_root_entry_child", fake_child)
    source_sha = _sha256(WRAPPER_PATH.read_bytes())
    argv = [
        "--root-child-v18",
        "--expected-wrapper-sha256",
        source_sha,
        "--expected-entry-sha256",
        wrapper._ROOT_ENTRY_SHA256,
        "--root-case-receipt-admission-id",
        "c" * 32,
    ]

    exit_code = wrapper.main(argv)

    assert exit_code == 0
    assert called["kwargs"] == {
        "wrapper_sha256": source_sha,
        "entry_sha256": wrapper._ROOT_ENTRY_SHA256,
        "admission_id": "c" * 32,
    }
    assert json.loads(output.getvalue()) == marker
    assert "PRIVATE_VALUE_MUST_NOT_LEAVE" not in output.getvalue()


def test_production_wires_full_source_tuple_and_exact_constructor_pins(wrapper, monkeypatch):
    own_source = WRAPPER_PATH.read_bytes()
    expected_sha = _sha256(own_source)
    fake_bundle = object()
    source_policy = dict(wrapper._EXPECTED_SOURCE_POLICY)
    runner_source = b"fixed runner bytes"
    source_values = (
        fake_bundle,
        source_policy,
        runner_source,
        b"entry bytes",
        {"source": "pins"},
        {"software": "pins"},
        {"complete": "pins"},
    )

    @contextmanager
    def source_context(_root):
        yield source_values

    calls = {}

    class FakePorts:
        def __init__(self, root, bundle, runner, *, wrapper_sha256, entry_sha256):
            calls["constructor"] = (root, bundle, runner, wrapper_sha256, entry_sha256)

    expected_output = wrapper._ActivationOutput(value={"test": "only"}, exit_code=2)
    monkeypatch.setattr(wrapper, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        wrapper,
        "sys",
        SimpleNamespace(
            flags=SimpleNamespace(isolated=1, no_site=1),
            dont_write_bytecode=True,
            version_info=(3, 11, 5),
        ),
    )
    monkeypatch.setattr(wrapper, "struct", SimpleNamespace(calcsize=lambda _value: 8))
    monkeypatch.setattr(wrapper, "_read_own_source", lambda: own_source)
    monkeypatch.setattr(wrapper, "_verified_v18_sources", source_context)
    monkeypatch.setattr(wrapper, "_ProductionPorts", FakePorts)

    def fake_core(ports, *, wrapper_sha256):
        calls["core"] = (ports, wrapper_sha256)
        return expected_output

    monkeypatch.setattr(wrapper, "_run_core", fake_core)

    output = wrapper._run_production(expected_sha)

    assert output is expected_output, (output.value["reason"], tuple(calls))
    assert calls["constructor"] == (
        wrapper.REPO_ROOT,
        fake_bundle,
        runner_source,
        expected_sha,
        wrapper._ROOT_ENTRY_SHA256,
    )
    assert calls["core"][1] == expected_sha


def test_protected_receipt_write_and_parent_read_return_only_counts(wrapper, tmp_path):
    private, cli, api = _fake_private_writer_modules(wrapper, tmp_path)
    admission_id = "a" * 32
    artifact_path = (
        tmp_path
        / wrapper._ADMISSION_ROOT_NAME
        / wrapper._ADMISSION_COLLECTION_NAME
        / admission_id
    )
    artifact_path.mkdir(parents=True)
    (artifact_path / "admission.json").write_bytes(b"private-admission")
    consumed = artifact_path / "consumed"
    consumed.mkdir()
    (consumed / "consumed.json").write_bytes(b"private-consumed-marker")

    payload = _case_result_payload()
    raw = _raw_case_result(wrapper, payload)
    wrapper._store_private_root_case_receipt(
        root=ROOT,
        admission_id=admission_id,
        payload=raw,
        private_module=private,
        cli_module=cli,
    )
    assert (artifact_path / wrapper._ROOT_CASE_RECEIPT_NAME).read_bytes() == raw

    identity = artifact_path.stat()
    directory = private.PrivateArtifactDirectory(
        artifact_path, identity.st_dev, identity.st_ino
    )
    ports = _fake_reader_ports(
        wrapper, tmp_path, admission_id, directory, private, cli, api
    )
    projection = wrapper._ProductionPorts._read_private_root_case_receipt(ports)
    assert projection == {
        "request_count": 8,
        "query_callback_count": 6,
        "snapshot_count": 2,
        "write_invocation_count": 0,
    }

    ports._admission_directory = SimpleNamespace(
        path=artifact_path,
        device=identity.st_dev + 1,
        inode=identity.st_ino,
    )
    with pytest.raises(wrapper.RootActivationError):
        wrapper._ProductionPorts._read_private_root_case_receipt(ports)


@contextmanager
def _noop_context(*values):
    yield values


def _valid_lifecycle(wrapper, *, exit_code=0):
    return {
        "assignment_before_resume": True,
        "job_active_zero": True,
        "normal_exit_code": exit_code,
        "stdout_eof": True,
        "stderr_eof": True,
        "stderr_empty": True,
        "handles_closed": True,
        "reader_threads_joined": True,
        "forced_termination": False,
    }


class _FakeRootPorts:
    def __init__(self, wrapper, *, clean=True, corrupt_result=False):
        self.wrapper = wrapper
        self.clean = clean
        self.corrupt_result = corrupt_result
        self.events: list[str] = []
        self.config_active = False
        self.credentials_active = False

    def source_policy(self):
        return dict(self.wrapper._EXPECTED_SOURCE_POLICY)

    def verify_runtime_binding(self):
        self.events.append("runtime_verified")

    def require_clean_ambient_names(self):
        self.events.append("ambient_names_verified")

    @contextmanager
    def activation_namespace_lease(self):
        self.events.append("namespace_open")
        try:
            yield
        finally:
            self.events.append("namespace_close")

    @contextmanager
    def config_lease(self):
        self.config_active = True
        pair = {"md_front": "public-md", "td_front": "public-td"}
        try:
            yield ([pair], "b" * 64, lambda: self.events.append("config_revalidated"))
        finally:
            self.config_active = False
            self.events.append("config_close")

    def select_current_pair(self, pairs, *, deadline):
        return SimpleNamespace(selected_index=0)

    def pair_projection(self, pairs):
        return b"fake-complete-pair-projection"

    def selected_pair_from_binding(self, pairs, binding, *, projection_sha256):
        return pairs[binding.selected_index]

    def claim_root_activation(self, wrapper_sha256):
        self.events.append("root_claimed")

    @contextmanager
    def credential_lease(self, pairs, binding, projection):
        self.credentials_active = True
        try:
            yield SimpleNamespace()
        finally:
            self.credentials_active = False
            self.events.append("credentials_close")

    def credential_digests(self, credentials):
        return "c" * 64, "d" * 64

    def new_admission_id(self):
        return "a" * 32

    def required_bindings(self, source_policy):
        return {name: "e" * 64 for name in self.wrapper._REQUIRED_BINDING_NAMES}

    def now_utc(self):
        return datetime.now(timezone.utc)

    def write_admission(self, admission_id, payload, wrapper_sha256):
        self.events.append("admission_written")

    def run_fixed_cli(self, *, deadline, cleanup_seconds):
        assert not self.config_active
        assert not self.credentials_active
        assert "namespace_close" in self.events
        self.events.append("outer_job_finished")
        lifecycle = _valid_lifecycle(self.wrapper, exit_code=0 if self.clean else 2)
        if not self.clean:
            lifecycle["job_active_zero"] = False
        result = self.wrapper._root_pass_projection(6, _valid_lifecycle(self.wrapper))
        if self.corrupt_result:
            result["root_postverify_verified"] = False
        return result, lifecycle


def test_core_returns_pass_only_after_leases_close_and_outer_job_is_clean(wrapper):
    ports = _FakeRootPorts(wrapper)
    output = wrapper._run_core(ports, wrapper_sha256="f" * 64)

    assert output.exit_code == 0, output.value["reason"]
    assert wrapper._valid_root_public_result(output.value)
    assert ports.events.index("credentials_close") < ports.events.index("outer_job_finished")
    assert ports.events.index("config_close") < ports.events.index("outer_job_finished")
    assert ports.events.index("namespace_close") < ports.events.index("outer_job_finished")


@pytest.mark.parametrize("case", ["unclean_job", "unverified_postverify"])
def test_core_denies_pass_when_outer_cleanup_or_proof_is_missing(wrapper, case):
    ports = _FakeRootPorts(
        wrapper,
        clean=case != "unclean_job",
        corrupt_result=case == "unverified_postverify",
    )
    output = wrapper._run_core(ports, wrapper_sha256="f" * 64)

    assert output.exit_code == 2
    assert output.value["certification"] == "BLOCKED"
    assert output.value["writes"] == 0


def test_fake_job_session_requires_zero_active_job_and_drains_child_pipes(wrapper):
    marker = {
        "case_id": "C01",
        "receipt_type": "C01RootCaseResultReceipt",
        "receipt_stored": True,
        "write_policy": "NO_WRITE",
        "writes": 0,
    }

    class FakeSession:
        job_assignment_observed = True

        def __init__(self, *, exit_after_termination=False):
            self.terminated = False
            self.exit_after_termination = exit_after_termination
            self.released = False

        def resume_launcher(self):
            return True

        def poll_launcher_exit_code(self):
            if self.terminated:
                return 2
            return 0 if not self.exit_after_termination else None

        def poll_job_empty(self):
            if self.terminated:
                return True
            return not self.exit_after_termination

        def release_controls(self):
            self.released = True
            return True

        def terminate_job(self):
            self.terminated = True

    def run_fake(*, unclean):
        session = FakeSession(exit_after_termination=unclean)

        class FakeBackend:
            def __init__(self, **_handles):
                pass

            def create_suspended_in_job(self, _command, *, deadline_monotonic):
                return session

        descriptors = []
        for _ in range(3):
            descriptors.extend(os.pipe())

        def open_streams():
            return (101, 102, 103), list(descriptors), (
                io.BytesIO(wrapper._canonical_json(marker)),
                io.BytesIO(b""),
            )

        backend_module = SimpleNamespace(WindowsJobBackend=FakeBackend)
        return session, open_streams, backend_module

    session, open_streams, backend_module = run_fake(unclean=False)
    raw, child, lifecycle = wrapper._run_v18_job(
        backend_module=backend_module,
        command=SimpleNamespace(argv=("fake",), cwd="fake", env={}),
        deadline=time.monotonic() + 2.0,
        open_streams=open_streams,
        process_id=lambda _session: 123,
    )
    assert wrapper._validate_root_child_frame(raw, exit_code=0) == child
    assert child == marker
    assert wrapper._valid_lifecycle(lifecycle)
    assert session.released is True
    assert session.terminated is False

    session, open_streams, backend_module = run_fake(unclean=True)
    with pytest.raises(wrapper.RootActivationError) as error:
        wrapper._run_v18_job(
            backend_module=backend_module,
            command=SimpleNamespace(argv=("fake",), cwd="fake", env={}),
            deadline=time.monotonic() + 0.05,
            open_streams=open_streams,
            process_id=lambda _session: 123,
        )
    assert error.value.reason == "cli_deadline_exceeded"
    assert session.terminated is True
    assert session.released is True


def test_wrapper_child_executes_real_v18_entry_then_stores_opaque_receipt(
    wrapper, monkeypatch, tmp_path
):
    integration = _load_module(
        "_c01_v18_root_activation_entry_integration_fixture", ENTRY_INTEGRATION_TEST_PATH
    )
    with integration._integrated_entry() as harness:
        private, cli, _api = _fake_private_writer_modules(wrapper, tmp_path)
        admission_id = "b" * 32
        artifact_path = (
            tmp_path
            / wrapper._ADMISSION_ROOT_NAME
            / wrapper._ADMISSION_COLLECTION_NAME
            / admission_id
        )
        artifact_path.mkdir(parents=True)
        (artifact_path / "admission.json").write_bytes(b"private-admission")
        consumed = artifact_path / "consumed"
        consumed.mkdir()
        (consumed / "consumed.json").write_bytes(b"private-consumed-marker")
        modules = {
            wrapper._FRONT_MODULE_NAME: harness["front"],
            wrapper._ROOT_BRIDGE_MODULE_NAME: harness["root_bridge"],
            wrapper._PROJECTION_MODULE_NAME: harness["projection"],
            wrapper._CERTIFICATION_MODULE_NAME: harness["certification"],
            wrapper._CUSTODY_MODULE_NAME: harness["custody"],
            "backtrader_runtime.certification_simnow_c01_root_entry_v18": harness["entry"],
            private.__name__: private,
            cli.__name__: cli,
        }
        monkeypatch.setattr(wrapper, "_load_root_entry_modules", lambda *_args: (modules, ()))
        raw = WRAPPER_PATH.read_bytes()
        output = wrapper._run_root_entry_child(
            wrapper_sha256=_sha256(raw),
            entry_sha256=wrapper._ROOT_ENTRY_SHA256,
            admission_id=admission_id,
        )
        state = harness["state"]

    assert output.exit_code == 0, output.value["reason"]
    assert output.value == {
        "case_id": "C01",
        "receipt_type": "C01RootCaseResultReceipt",
        "receipt_stored": True,
        "write_policy": "NO_WRITE",
        "writes": 0,
    }
    assert state["stage_calls"] == 1
    assert state["custody_hook_calls"] == 1
    assert state["events"] == [
        "lease_open",
        "issuer_enter",
        "candidate_stage",
        "issuer_exitstack_closed",
        "issuer_return",
        "postverify",
        "lease_close",
    ]
    raw_receipt = (artifact_path / wrapper._ROOT_CASE_RECEIPT_NAME).read_bytes()
    stored_receipt = json.loads(raw_receipt.decode("utf-8"))
    assert stored_receipt["case_id"] == "C01"
    assert stored_receipt["status"] == "PASS"
    assert stored_receipt["details"]["certification_evidence"]
    public_text = json.dumps(output.value, sort_keys=True)
    assert "front_id" not in public_text
    assert "session_id" not in public_text
    assert "trading_day" not in public_text

