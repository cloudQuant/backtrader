"""Fake-only tests for the pre-import I13/I15 parent launcher gate."""

from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
import os
import platform
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


_MODULE_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "ctp_i13_i15_parent_launcher.py"
)
_SPEC = importlib.util.spec_from_file_location("i13_i15_parent_launcher_test_module", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
launcher = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = launcher
_SPEC.loader.exec_module(launcher)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _manifest(candidate: str) -> bytes:
    _, _, entrypoint = launcher._CANDIDATE_LAYOUT[candidate]
    paths = sorted(
        {
            "backtrader_runtime/__init__.py": _sha(b"package\n"),
            "backtrader_runtime/inventory.py": _sha(b"inventory\n"),
            entrypoint: _sha(b"entrypoint\n"),
        }
    )
    if candidate == "i13_md":
        value = {"schema": 1, "source_files": {path: _sha(path.encode()) for path in paths}}
    else:
        value = {
            "files": [{"path": path, "sha256": _sha(path.encode())} for path in paths],
            "schema": "ctp_i15_source_manifest.v2",
        }
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _pin_source(candidate: str, manifest: bytes) -> bytes:
    name = launcher._CODE_OWNED_PIN_NAMES[candidate]
    return f'{name} = "{_sha(manifest)}"\n'.encode()


def _trusted(raw: bytes, *, digest: str | None = None):
    return launcher.ExternallyPinnedDescriptor(
        raw_bytes=raw,
        sha256=_sha(raw) if digest is None else digest,
        external_anchor_id="fake-fixture-only",
    )


def _guardian_descriptor(receipt_root: Path):
    repo_root = _MODULE_PATH.resolve().parents[1]
    receipt_root.mkdir(parents=True, exist_ok=True)
    files = {
        relative: _sha((repo_root / Path(*relative.split("/"))).read_bytes())
        for relative in launcher._INERT_GUARDIAN_FILES
    }
    auth_key = b"k" * 32
    assert len(auth_key) == 32
    pipe_token = _sha(str(receipt_root.resolve()).encode("utf-8"))[:32]
    python_executable = str(Path(sys.executable).resolve())
    value = {
        "schema": launcher._INERT_GUARDIAN_SCHEMA,
        "source_root": str(repo_root),
        "receipt_root": str(receipt_root.resolve()),
        "pipe_address": rf"\\.\pipe\backtrader-ctp-i13-i15-{pipe_token}",
        "service_authkey_sha256": _sha(auth_key),
        "python": {
            "executable": python_executable,
            "sha256": _sha(Path(python_executable).read_bytes()),
            "version": platform.python_version(),
            "architecture": platform.machine(),
        },
        "parent_launcher_sha256": _sha(_MODULE_PATH.read_bytes()),
        "files": files,
    }
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return value, raw, _MODULE_PATH.read_bytes(), python_executable, auth_key


def _fixture(tmp_path: Path, candidate: str = "i13_md"):
    source_root = tmp_path / "source"
    package = source_root / "backtrader_runtime"
    registration = (
        source_root / "examples" / "013_3_sa_midfreq_simnow" / "runtime-ctp-private"
    )
    package.mkdir(parents=True)
    registration.mkdir(parents=True)
    launcher_bytes = b"externally captured fake launcher bytes"
    manifest = _manifest(candidate)
    manifest_relative, _, _ = launcher._CANDIDATE_LAYOUT[candidate]
    (source_root / manifest_relative).write_bytes(manifest)

    venv_root = tmp_path / "venv"
    scripts = venv_root / "Scripts"
    scripts.mkdir(parents=True)
    executable = scripts / "python.exe"
    executable.write_bytes(b"pinned fake interpreter")
    home = tmp_path / "base-python"
    home.mkdir()
    cfg = f"home = {home}\ninclude-system-site-packages = false\nversion = 3.11.5\n".encode()
    (venv_root / "pyvenv.cfg").write_bytes(cfg)

    descriptor = {
        "schema": launcher.SCHEMA,
        "launcher": {"sha256": _sha(launcher_bytes), "version": "reviewed-test-1"},
        "source": {
            "root": str(source_root),
            "runtime_package": "backtrader_runtime",
            "private_registration": "examples/013_3_sa_midfreq_simnow/runtime-ctp-private",
            "strategy_id": "example.013_3.sa_midfreq_simnow",
            "runtime_id": "example.013_3.sa_midfreq_simnow.ctp_private",
            "candidates": {},
        },
        "python": {
            "version": "3.11.5",
            "architecture": "AMD64",
            "venv_root": str(venv_root),
            "executable": str(executable),
            "executable_sha256": _sha(executable.read_bytes()),
            "home": str(home),
            "pyvenv_cfg_sha256": _sha(cfg),
            # Kept outside pytest's per-user AppData fixture root because the
            # descriptor intentionally forbids user-writable stdlib locations.
            "stdlib_paths": ["C:\\PinnedPython\\Lib"],
        },
    }
    for name in ("i13_md", "i15_td"):
        manifest_path, pin_rel, _ = launcher._CANDIDATE_LAYOUT[name]
        manifest_bytes = manifest if name == candidate else _manifest(name)
        pin = _pin_source(name, manifest_bytes)
        if name != candidate:
            (source_root / manifest_path).write_bytes(manifest_bytes)
        (source_root / pin_rel).write_bytes(pin)
        descriptor["source"]["candidates"][name] = {
            "manifest_path": manifest_path,
            "manifest_sha256": _sha(manifest_bytes),
            "pin_path": pin_rel,
            "pin_sha256": _sha(pin),
        }
    raw = json.dumps(descriptor, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return descriptor, raw, launcher_bytes, executable


def _preflight(raw, launcher_bytes, executable, candidate="i13_md"):
    return launcher.preflight_parent_launch(
        _trusted(raw),
        candidate=candidate,
        captured_launcher_bytes=launcher_bytes,
        actual_executable=str(executable),
        actual_version="3.11.5",
        actual_architecture="AMD64",
        actual_sys_path=["C:\\PinnedPython\\Lib"],
    )


def _prepare(raw, launcher_bytes, executable, sealed_importer, metadata_job_setup):
    return launcher.prepare_candidate_import_and_job_setup(
        _trusted(raw),
        candidate="i13_md",
        captured_launcher_bytes=launcher_bytes,
        actual_executable=str(executable),
        actual_version="3.11.5",
        actual_architecture="AMD64",
        actual_sys_path=["C:\\PinnedPython\\Lib"],
        sealed_importer=sealed_importer,
        metadata_job_setup=metadata_job_setup,
    )


class _FakeSeal:
    def __init__(self, candidate, manifest_sha256, source_root, stdlib_paths, events):
        self.candidate = candidate
        self.manifest_sha256 = manifest_sha256
        self.source_root = Path(source_root)
        self.stdlib_paths = tuple(stdlib_paths)
        self.events = events
        self.closed = False

    def close(self):
        self.events.append("seal-close")
        self.closed = True


class _FakeSealedImporter:
    def __init__(self, events, *, failure=None):
        self.events = events
        self.failure = failure
        self.seal = None
        self.finder = object()
        self.module = object()

    def validate_clean_bootstrap_import_state(self):
        self.events.append("clean-bootstrap")
        if self.failure == "clean":
            raise launcher.ParentLaunchError("bootstrap_import_state_invalid")

    def seal_candidate_source_tree(
        self, candidate, source_root, *, expected_manifest_sha256, expected_pin_sha256s, stdlib_paths
    ):
        self.events.append("source-seal")
        assert set(expected_pin_sha256s) == {"i13", "i15"}
        self.seal = _FakeSeal(
            candidate, expected_manifest_sha256, source_root, stdlib_paths, self.events
        )
        return self.seal

    def install_sealed_source_finder(self, seal):
        self.events.append("finder-install")
        assert seal is self.seal
        if self.failure == "install":
            raise launcher.ParentLaunchError("sealed_finder_install_failed")
        return self.finder

    def import_sealed_candidate_module(self, seal, finder):
        self.events.append("sealed-import")
        assert seal is self.seal and finder is self.finder
        if self.failure == "import":
            raise launcher.ParentLaunchError("candidate_import_failed")
        return self.module


@pytest.mark.parametrize("candidate", ["i13_md", "i15_td"])
def test_preflight_binds_external_descriptor_interpreter_and_source_before_runtime_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, candidate: str
) -> None:
    _, raw, launcher_bytes, executable = _fixture(tmp_path, candidate)
    runtime_modules_before = {
        name
        for name in sys.modules
        if name == "backtrader_runtime" or name.startswith("backtrader_runtime.")
    }
    original_import = builtins.__import__

    def reject_runtime_import(name, *args, **kwargs):
        if name == "backtrader_runtime" or name.startswith("backtrader_runtime."):
            raise AssertionError("runtime import crossed preflight boundary")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_runtime_import)
    plan = _preflight(raw, launcher_bytes, executable, candidate)
    assert plan.candidate == candidate
    assert plan.entrypoint == launcher._CANDIDATE_LAYOUT[candidate][2]
    assert Path(plan.manifest_path).is_file()
    assert Path(plan.pin_path).is_file()
    runtime_modules_after = {
        name
        for name in sys.modules
        if name == "backtrader_runtime" or name.startswith("backtrader_runtime.")
    }
    assert runtime_modules_after == runtime_modules_before


def test_required_external_descriptor_drives_clean_import_then_job_setup(tmp_path: Path) -> None:
    _, raw, launcher_bytes, executable = _fixture(tmp_path)
    events = []
    importer = _FakeSealedImporter(events)

    def setup_job(plan, module):
        events.append("metadata-job-setup")
        assert plan.candidate == "i13_md"
        assert module is importer.module
        return "fake-job-handle"

    prepared = _prepare(raw, launcher_bytes, executable, importer, setup_job)
    assert events == [
        "clean-bootstrap",
        "source-seal",
        "finder-install",
        "sealed-import",
        "metadata-job-setup",
    ]
    assert prepared.metadata_job_setup_result == "fake-job-handle"
    assert not importer.seal.closed
    prepared.close()
    assert importer.seal.closed


@pytest.mark.skipif(os.name != "nt", reason="the inert guardian descriptor binds Windows paths")
def test_inert_guardian_request_uses_pinned_service_and_fixed_protocol(tmp_path: Path) -> None:
    _, raw, launcher_bytes, executable, auth_key = _guardian_descriptor(
        tmp_path / "accepted-output"
    )
    observed = {}
    request_id = "0123456789abcdef0123456789abcdef"
    fake_response = {
        "schema": "ctp_i13_i15_inert_guardian_receipt.v1",
        "state": "timed_out",
        "reason": "outer_worker_deadline_exceeded",
        "process_created": True,
        "job_assignment_observed": True,
        "launcher_resumed": True,
        "launcher_exit_observed": True,
        "job_termination_requested": True,
        "job_termination_call_succeeded": True,
        "job_empty_observed": True,
        "containment": "verified",
        "controls_retained": False,
        "service_schema": "ctp_i13_i15_inert_guardian_service_response.v1",
        "request_id": request_id,
        "service_pid": 4321,
    }

    def ipc_requester(**kwargs):
        observed.update(kwargs)
        return SimpleNamespace(
            state="response",
            reason="response_received",
            response_bytes=json.dumps(
                fake_response, sort_keys=True, separators=(",", ":")
            ).encode("ascii"),
        )

    now = time.monotonic()
    result = launcher.request_inert_guardian(
        _trusted(raw),
        captured_launcher_bytes=launcher_bytes,
        actual_executable=executable,
        actual_version=platform.python_version(),
        actual_architecture=platform.machine(),
        child_seconds=30,
        stop_deadline_monotonic=now + 10,
        deadline_monotonic=now + 12,
        service_pid=4321,
        service_auth_key=auth_key,
        request_id=request_id,
        ipc_requester=ipc_requester,
        monotonic=time.monotonic,
    )

    request = json.loads(observed["request_bytes"])
    assert set(request) == {
        "schema",
        "operation",
        "request_id",
        "child_seconds",
        "stop_deadline_monotonic",
        "deadline_monotonic",
    }
    assert request["schema"] == "ctp_i13_i15_inert_guardian_request.v1"
    assert request["operation"] == "sleep_probe"
    assert request["request_id"] == request_id
    assert observed["address"].startswith(r"\\.\pipe\backtrader-ctp-i13-i15-")
    assert observed["expected_service_pid"] == 4321
    assert observed["auth_key"] == auth_key
    assert result.state == "timed_out"
    assert result.response["job_empty_observed"] is True
    assert result.descriptor_sha256 == _sha(raw)


@pytest.mark.skipif(os.name != "nt", reason="the inert guardian descriptor binds Windows paths")
def test_inert_guardian_source_mismatch_rejects_before_ipc(tmp_path: Path) -> None:
    descriptor, _, launcher_bytes, executable, auth_key = _guardian_descriptor(tmp_path / "output")
    descriptor["files"][launcher._INERT_GUARDIAN_FILES[-1]] = _sha(b"wrong guardian bytes")
    raw = json.dumps(descriptor, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    calls = []

    with pytest.raises(launcher.ParentLaunchError, match="guardian_source_digest_mismatch"):
        launcher.request_inert_guardian(
            _trusted(raw),
            captured_launcher_bytes=launcher_bytes,
            actual_executable=executable,
            actual_version=platform.python_version(),
            actual_architecture=platform.machine(),
            child_seconds=3,
            stop_deadline_monotonic=time.monotonic() + 10,
            deadline_monotonic=time.monotonic() + 12,
            service_pid=4321,
            service_auth_key=auth_key,
            request_id="0123456789abcdef0123456789abcdef",
            ipc_requester=lambda **kwargs: calls.append(kwargs),
            monotonic=time.monotonic,
        )
    assert calls == []


@pytest.mark.skipif(os.name != "nt", reason="guardian descriptor binds Windows paths")
def test_legacy_sleep_guardian_descriptor_set_remains_accepted(tmp_path: Path) -> None:
    descriptor, _raw, _launcher_bytes, _executable, _auth_key = _guardian_descriptor(
        tmp_path / "legacy-output"
    )
    descriptor["files"].pop(launcher._READONLY_PREFLIGHT_WORKER)
    raw = json.dumps(descriptor, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

    plan = launcher.parse_inert_guardian_descriptor(_trusted(raw))

    assert set(plan.files) == set(launcher._LEGACY_INERT_GUARDIAN_FILES)


@pytest.mark.skipif(os.name != "nt", reason="guardian descriptor binds Windows paths")
def test_readonly_guardian_descriptor_requires_the_exact_fixed_bundle(tmp_path: Path) -> None:
    descriptor, _raw, _launcher_bytes, _executable, _auth_key = _guardian_descriptor(
        tmp_path / "readonly-output"
    )
    descriptor["files"] = {
        relative: _sha(relative.encode("ascii"))
        for relative in launcher._READONLY_GUARDIAN_FILES
    }
    raw = json.dumps(descriptor, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    plan = launcher.parse_inert_guardian_descriptor(_trusted(raw))
    assert set(plan.files) == set(launcher._READONLY_GUARDIAN_FILES)

    descriptor["files"]["scripts/other_bootstrap.py"] = _sha(b"arbitrary")
    raw = json.dumps(descriptor, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    with pytest.raises(launcher.ParentLaunchError, match="guardian_source_set_invalid"):
        launcher.parse_inert_guardian_descriptor(_trusted(raw))


@pytest.mark.skipif(os.name != "nt", reason="the inert guardian descriptor binds Windows paths")
def test_inert_guardian_rejects_key_not_bound_by_external_descriptor(tmp_path: Path) -> None:
    _, raw, launcher_bytes, executable, _ = _guardian_descriptor(tmp_path / "output")
    calls = []
    with pytest.raises(launcher.ParentLaunchError, match="guardian_service_authkey_mismatch"):
        launcher.request_inert_guardian(
            _trusted(raw),
            captured_launcher_bytes=launcher_bytes,
            actual_executable=executable,
            actual_version=platform.python_version(),
            actual_architecture=platform.machine(),
            child_seconds=3,
            stop_deadline_monotonic=time.monotonic() + 10,
            deadline_monotonic=time.monotonic() + 12,
            service_pid=4321,
            service_auth_key=b"x" * 32,
            request_id="0123456789abcdef0123456789abcdef",
            ipc_requester=lambda **kwargs: calls.append(kwargs),
            monotonic=time.monotonic,
        )
    assert calls == []


@pytest.mark.parametrize("changed_binding", ["source_root", "stdlib_paths"])
def test_sealed_source_binding_mismatch_closes_seal_before_job_setup(
    tmp_path: Path, changed_binding: str
) -> None:
    _, raw, launcher_bytes, executable = _fixture(tmp_path)
    events = []
    importer = _FakeSealedImporter(events)
    original_seal_source = importer.seal_candidate_source_tree

    def mismatched_seal_source(*args, **kwargs):
        seal = original_seal_source(*args, **kwargs)
        if changed_binding == "source_root":
            seal.source_root = seal.source_root.parent
        else:
            seal.stdlib_paths = ("C:\\DifferentPython\\Lib",)
        return seal

    importer.seal_candidate_source_tree = mismatched_seal_source
    job_calls = []

    with pytest.raises(launcher.ParentLaunchError, match="sealed_importer_binding_mismatch"):
        _prepare(raw, launcher_bytes, executable, importer, lambda *_: job_calls.append("job"))

    assert importer.seal.closed
    assert "finder-install" not in events
    assert job_calls == []


@pytest.mark.parametrize("cleanup_failure", ["missing", "raises"])
def test_sealed_source_binding_mismatch_reports_cleanup_failure(
    tmp_path: Path, cleanup_failure: str
) -> None:
    _, raw, launcher_bytes, executable = _fixture(tmp_path)
    events = []
    importer = _FakeSealedImporter(events)
    original_seal_source = importer.seal_candidate_source_tree

    def mismatched_seal_source(*args, **kwargs):
        seal = original_seal_source(*args, **kwargs)
        seal.source_root = seal.source_root.parent
        if cleanup_failure == "missing":
            seal.close = None
        else:
            def fail_close():
                events.append("seal-close-failed")
                raise OSError("fake close failure")

            seal.close = fail_close
        return seal

    importer.seal_candidate_source_tree = mismatched_seal_source
    job_calls = []

    with pytest.raises(launcher.ParentLaunchError, match="source_seal_cleanup_failed"):
        _prepare(raw, launcher_bytes, executable, importer, lambda *_: job_calls.append("job"))

    assert "finder-install" not in events
    assert job_calls == []
    assert ("seal-close-failed" in events) is (cleanup_failure == "raises")


@pytest.mark.parametrize(
    ("failure", "expected_events"),
    [
        ("clean", ["clean-bootstrap"]),
        ("install", ["clean-bootstrap", "source-seal", "finder-install", "seal-close"]),
        (
            "import",
            ["clean-bootstrap", "source-seal", "finder-install", "sealed-import", "seal-close"],
        ),
    ],
)
def test_bootstrap_or_sealed_import_failure_precedes_any_job_setup(
    tmp_path: Path, failure: str, expected_events: list[str]
) -> None:
    _, raw, launcher_bytes, executable = _fixture(tmp_path)
    events = []
    importer = _FakeSealedImporter(events, failure=failure)
    job_calls = []
    with pytest.raises(launcher.ParentLaunchError):
        _prepare(raw, launcher_bytes, executable, importer, lambda *_: job_calls.append("job"))
    assert events == expected_events
    assert job_calls == []


def test_metadata_job_setup_failure_closes_source_and_returns_no_later_stage(tmp_path: Path) -> None:
    _, raw, launcher_bytes, executable = _fixture(tmp_path)
    events = []
    importer = _FakeSealedImporter(events)

    def fail_job_setup(_plan, _module):
        events.append("metadata-job-setup")
        raise launcher.ParentLaunchError("metadata_job_setup_failed")

    with pytest.raises(launcher.ParentLaunchError, match="metadata_job_setup_failed"):
        _prepare(raw, launcher_bytes, executable, importer, fail_job_setup)
    assert events == [
        "clean-bootstrap",
        "source-seal",
        "finder-install",
        "sealed-import",
        "metadata-job-setup",
        "seal-close",
    ]
    assert importer.seal.closed


def test_parent_import_gate_requires_typed_descriptor_before_clean_check(tmp_path: Path) -> None:
    _, raw, launcher_bytes, executable = _fixture(tmp_path)
    events = []
    importer = _FakeSealedImporter(events)
    with pytest.raises(launcher.ParentLaunchError, match="trusted_descriptor_required"):
        launcher.prepare_candidate_import_and_job_setup(
            raw,
            candidate="i13_md",
            captured_launcher_bytes=launcher_bytes,
            actual_executable=str(executable),
            actual_version="3.11.5",
            actual_architecture="AMD64",
            actual_sys_path=["C:\\PinnedPython\\Lib"],
            sealed_importer=importer,
            metadata_job_setup=lambda *_: None,
        )
    assert events == []


def test_descriptor_digest_is_an_external_required_input(tmp_path: Path) -> None:
    _, raw, _, _ = _fixture(tmp_path)
    with pytest.raises(launcher.ParentLaunchError, match="descriptor_digest_mismatch"):
        launcher.parse_trust_descriptor(_trusted(raw, digest="a" * 64))


def test_descriptor_duplicate_keys_and_noncanonical_json_reject(tmp_path: Path) -> None:
    _, raw, _, _ = _fixture(tmp_path)
    duplicate = raw[:-1] + b',"schema":"shadow"}'
    with pytest.raises(launcher.ParentLaunchError, match="descriptor_duplicate_key"):
        launcher.parse_trust_descriptor(_trusted(duplicate))

    noncanonical = json.dumps(json.loads(raw), indent=2).encode()
    with pytest.raises(launcher.ParentLaunchError, match="descriptor_not_canonical"):
        launcher.parse_trust_descriptor(
            _trusted(noncanonical)
        )


def test_unset_candidate_pins_and_unknown_fields_reject(tmp_path: Path) -> None:
    descriptor, _, _, _ = _fixture(tmp_path)
    descriptor["source"]["candidates"]["i13_md"]["manifest_sha256"] = "0" * 64
    raw = json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(launcher.ParentLaunchError, match="candidate_manifest_pin_invalid"):
        launcher.parse_trust_descriptor(_trusted(raw))

    descriptor, _, _, _ = _fixture(tmp_path / "second")
    descriptor["unexpected"] = True
    raw = json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(launcher.ParentLaunchError, match="descriptor_fields_invalid"):
        launcher.parse_trust_descriptor(_trusted(raw))


def test_fixed_python_binding_rejects_before_source_or_runtime_use(tmp_path: Path) -> None:
    _, raw, launcher_bytes, executable = _fixture(tmp_path)
    with pytest.raises(launcher.ParentLaunchError, match="running_python_binding_mismatch"):
        launcher.preflight_parent_launch(
            _trusted(raw),
            candidate="i13_md",
            captured_launcher_bytes=launcher_bytes,
            actual_executable=str(executable.parent / "other-python.exe"),
            actual_version="3.11.5",
            actual_architecture="AMD64",
            actual_sys_path=["C:\\PinnedPython\\Lib"],
        )


def test_unpinned_import_path_and_launcher_bytes_reject(tmp_path: Path) -> None:
    _, raw, launcher_bytes, executable = _fixture(tmp_path)
    with pytest.raises(launcher.ParentLaunchError, match="running_sys_path_mismatch"):
        launcher.preflight_parent_launch(
            _trusted(raw),
            candidate="i13_md",
            captured_launcher_bytes=launcher_bytes,
            actual_executable=str(executable),
            actual_version="3.11.5",
            actual_architecture="AMD64",
            actual_sys_path=["C:\\PinnedPython\\Lib", "C:\\checkout"],
        )
    with pytest.raises(launcher.ParentLaunchError, match="launcher_digest_mismatch"):
        _preflight(raw, b"different launcher", executable)


def test_preflight_rejects_bad_venv_home_and_manifest_before_returning_plan(tmp_path: Path) -> None:
    descriptor, _, launcher_bytes, executable = _fixture(tmp_path)
    cfg_path = Path(descriptor["python"]["venv_root"]) / "pyvenv.cfg"
    cfg_path.write_bytes(cfg_path.read_bytes().replace(b"false", b"true"))
    descriptor["python"]["pyvenv_cfg_sha256"] = _sha(cfg_path.read_bytes())
    raw = json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(launcher.ParentLaunchError, match="pyvenv_cfg_binding_invalid"):
        _preflight(raw, launcher_bytes, executable)

    descriptor, _, launcher_bytes, executable = _fixture(tmp_path / "manifest")
    manifest_path = Path(descriptor["source"]["root"]) / descriptor["source"]["candidates"]["i13_md"]["manifest_path"]
    manifest_path.write_bytes(b"{}")
    descriptor["source"]["candidates"]["i13_md"]["manifest_sha256"] = _sha(b"{}")
    raw = json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(launcher.ParentLaunchError, match="manifest_invalid"):
        _preflight(raw, launcher_bytes, executable)


@pytest.mark.parametrize(
    ("candidate", "pin_source"),
    [
        ("i13_md", b'I13_SOURCE_MANIFEST_SHA256 = "' + b"0" * 64 + b'"\n'),
        ("i15_td", b"I15_REVIEWED_SOURCE_MANIFEST_SHA256 = None\n"),
    ],
)
def test_unset_code_owned_source_pin_rejects_even_with_fake_external_descriptor(
    tmp_path: Path, candidate: str, pin_source: bytes
) -> None:
    descriptor, _, launcher_bytes, executable = _fixture(tmp_path, candidate)
    pin_relative = launcher._CANDIDATE_LAYOUT[candidate][1]
    pin_path = Path(descriptor["source"]["root"]).joinpath(*pin_relative.split("/"))
    pin_path.write_bytes(pin_source)
    descriptor["source"]["candidates"][candidate]["pin_sha256"] = _sha(pin_source)
    raw = json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(launcher.ParentLaunchError, match="candidate_source_pin_unset"):
        _preflight(raw, launcher_bytes, executable, candidate)


def test_local_gap_detector_reports_missing_manifest_unset_pin_and_no_trust_claim(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "checkout"
    package = source_root / "backtrader_runtime"
    package.mkdir(parents=True)
    (package / "ctp_i13_source_identity_pin.py").write_text(
        'I13_SOURCE_MANIFEST_SHA256 = "' + "0" * 64 + '"\n', encoding="utf-8"
    )
    (package / "ctp_i15_source_identity_pin.py").write_text(
        "I15_REVIEWED_SOURCE_MANIFEST_SHA256 = None\n", encoding="utf-8"
    )
    gaps = launcher.inspect_local_source_pin_gaps(source_root)
    assert gaps["i13_md"] == (
        "manifest_missing",
        "candidate_source_pin_unset",
        "external_review_receipt_required",
    )
    assert gaps["i15_td"] == (
        "manifest_missing",
        "candidate_source_pin_unset",
        "external_review_receipt_required",
    )


def test_local_gap_detector_rejects_a_nonmatching_self_asserted_pin(tmp_path: Path) -> None:
    source_root = tmp_path / "checkout"
    package = source_root / "backtrader_runtime"
    package.mkdir(parents=True)
    manifest = _manifest("i13_md")
    (package / "ctp_i13_source_manifest.json").write_bytes(manifest)
    (package / "ctp_i13_source_identity_pin.py").write_text(
        'I13_SOURCE_MANIFEST_SHA256 = "' + "f" * 64 + '"\n', encoding="utf-8"
    )
    (package / "ctp_i15_source_identity_pin.py").write_text(
        "I15_REVIEWED_SOURCE_MANIFEST_SHA256 = None\n", encoding="utf-8"
    )
    gaps = launcher.inspect_local_source_pin_gaps(source_root)
    assert gaps["i13_md"] == (
        "candidate_source_pin_manifest_mismatch",
        "external_review_receipt_required",
    )


def test_i13_manifest_allows_only_fixed_readonly_worker_and_bootstrap_sources():
    rows = {
        "backtrader_runtime/__init__.py": _sha(b"package"),
        "backtrader_runtime/inventory.py": _sha(b"inventory"),
        launcher._CANDIDATE_LAYOUT["i13_md"][2]: _sha(b"entrypoint"),
        launcher._READONLY_WORKER_DEPENDENCY_HELPER: _sha(b"dependency helper"),
        launcher._READONLY_PREFLIGHT_WORKER: _sha(b"fixed inert fixture bytes"),
        launcher._READONLY_PREFLIGHT_BOOTSTRAP: _sha(b"fixed bootstrap fixture bytes"),
    }
    raw = json.dumps(
        {"schema": 1, "source_files": rows},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")

    parsed = launcher._parse_candidate_manifest("i13_md", raw, _sha(raw))
    assert parsed[launcher._READONLY_PREFLIGHT_WORKER] == rows[
        launcher._READONLY_PREFLIGHT_WORKER
    ]
    assert parsed[launcher._READONLY_PREFLIGHT_BOOTSTRAP] == rows[
        launcher._READONLY_PREFLIGHT_BOOTSTRAP
    ]

    # The prior worker/bootstrap closure remains valid for compatibility.
    # The three service roles form one optional, all-or-none closure.
    rows.update(
        {
            path: _sha(path.encode("ascii"))
            for path in launcher._READONLY_SERVICE_ROLE_FILES
        }
    )
    role_raw = json.dumps(
        {"schema": 1, "source_files": rows},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    role_parsed = launcher._parse_candidate_manifest("i13_md", role_raw, _sha(role_raw))
    assert launcher._READONLY_SERVICE_ROLE_FILES.issubset(role_parsed)

    for missing in launcher._READONLY_SERVICE_ROLE_FILES:
        incomplete_rows = dict(rows)
        incomplete_rows.pop(missing)
        incomplete_raw = json.dumps(
            {"schema": 1, "source_files": incomplete_rows},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        with pytest.raises(launcher.ParentLaunchError, match="readonly_service_roles_incomplete"):
            launcher._parse_candidate_manifest("i13_md", incomplete_raw, _sha(incomplete_raw))

    rows.pop(launcher._READONLY_PREFLIGHT_WORKER)
    rows.pop(launcher._READONLY_PREFLIGHT_BOOTSTRAP)
    rows.pop(launcher._READONLY_WORKER_DEPENDENCY_HELPER)
    rows = {path: digest for path, digest in rows.items() if path not in launcher._READONLY_SERVICE_ROLE_FILES}
    rows["scripts/other_worker.py"] = _sha(b"not fixed")
    arbitrary = json.dumps(
        {"schema": 1, "source_files": rows},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    with pytest.raises(launcher.ParentLaunchError, match="manifest_path_invalid"):
        launcher._parse_candidate_manifest("i13_md", arbitrary, _sha(arbitrary))


@pytest.mark.parametrize(
    "extra_path", [launcher._READONLY_PREFLIGHT_WORKER, launcher._READONLY_PREFLIGHT_BOOTSTRAP]
)
def test_i15_manifest_cannot_add_i13_readonly_sources(extra_path):
    _, _, entrypoint = launcher._CANDIDATE_LAYOUT["i15_td"]
    rows = [
        {"path": "backtrader_runtime/__init__.py", "sha256": _sha(b"package")},
        {"path": "backtrader_runtime/inventory.py", "sha256": _sha(b"inventory")},
        {"path": entrypoint, "sha256": _sha(b"entrypoint")},
        {"path": extra_path, "sha256": _sha(b"fixed readonly source")},
    ]
    rows.sort(key=lambda row: row["path"])
    raw = json.dumps(
        {"files": rows, "schema": "ctp_i15_source_manifest.v2"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    with pytest.raises(launcher.ParentLaunchError, match="manifest_path_invalid"):
        launcher._parse_candidate_manifest("i15_td", raw, _sha(raw))


def test_current_checkout_has_no_trusted_source_candidate_pin() -> None:
    source_root = _MODULE_PATH.resolve().parents[1]
    gaps = launcher.inspect_local_source_pin_gaps(source_root)
    assert gaps["i13_md"] == (
        "manifest_missing",
        "candidate_source_pin_unset",
        "external_review_receipt_required",
    )
    assert gaps["i15_td"] == (
        "manifest_missing",
        "candidate_source_pin_unset",
        "external_review_receipt_required",
    )
