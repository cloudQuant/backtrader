"""Pure policy tests for the fixed I13/I15 guardian deployment anchor."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


_MODULE_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "ctp_i13_i15_guardian_deployment_anchor.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "ctp_i13_i15_guardian_deployment_anchor_test_module", _MODULE_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
anchor = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = anchor
_SPEC.loader.exec_module(anchor)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _descriptor_value(**overrides):
    parent = b'{"schema":"parent-test-v1"}'
    dependency_manifest = b'{"schema":"worker-dependencies.v1"}'
    value = {
        "schema": anchor.DEPLOYMENT_SCHEMA,
        "operation": anchor.DEPLOYMENT_OPERATION,
        "source_root": r"C:\sealed\candidate",
        "source_manifest_sha256": _sha(b"i13 manifest"),
        "python": {
            "executable": r"C:\sealed\venv\Scripts\python.exe",
            "sha256": _sha(b"python"),
            "version": "3.11.5",
            "architecture": "AMD64",
        },
        "service_sid": "S-1-5-18",
        "client_sid": "S-1-5-21-1-2-3-1001",
        "worker_sha256": _sha(b"fixed worker"),
        "worker_dependency_manifest_sha256": _sha(dependency_manifest),
        "runtime_manifest_sha256": _sha(b'{"schema":"runtime-closure.v1"}'),
        "pipe_address": r"\\.\pipe\backtrader-ctp-i13-i15-" + "a" * 32,
        "auth_key_sha256": _sha(b"k" * 32),
        "parent_trust_descriptor_b64": base64.b64encode(parent).decode("ascii"),
        "parent_trust_descriptor_sha256": _sha(parent),
    }
    value.update(overrides)
    return value


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def _parse(value=None):
    descriptor_value = _descriptor_value() if value is None else value
    raw = _canonical(descriptor_value)
    return anchor._parse_deployment_descriptor(
        raw,
        expected_sha256=_sha(raw),
        expected_worker_dependency_sha256=_sha(b'{"schema":"worker-dependencies.v1"}'),
        expected_runtime_manifest_sha256=_sha(b'{"schema":"runtime-closure.v1"}'),
    )


def test_fixed_descriptor_parses_exact_code_owned_fields_only():
    parsed = _parse()

    assert parsed.source_root == r"C:\sealed\candidate"
    assert parsed.source_manifest_sha256 == _sha(b"i13 manifest")
    assert parsed.python_executable.endswith(r"Scripts\python.exe")
    assert parsed.worker_sha256 == _sha(b"fixed worker")
    assert parsed.worker_dependency_manifest_sha256 == _sha(b'{"schema":"worker-dependencies.v1"}')
    assert parsed.runtime_manifest_sha256 == _sha(b'{"schema":"runtime-closure.v1"}')
    assert anchor.DEPLOYMENT_SCHEMA == "ctp_i13_i15_guardian_deployment.v2"
    assert parsed.auth_key_sha256 == _sha(b"k" * 32)
    assert parsed.parent_trust_raw == b'{"schema":"parent-test-v1"}'
    assert anchor.FIXED_RECEIPT_SCOPE == "ctp_i13_i15.readonly_preflight.v1"
    assert anchor.WORKER_RELATIVE_PATH == "scripts/ctp_i13_i15_readonly_preflight_worker.py"
    assert anchor.BOOTSTRAP_RELATIVE_PATH == "scripts/ctp_i13_i15_readonly_preflight_bootstrap.py"


@pytest.mark.parametrize(
    "update",
    [
        {"operation": "arbitrary"},
        {"source_root": r"C:\other\..\tree"},
        {"worker_sha256": "0" * 64},
        {"worker_dependency_manifest_sha256": "0" * 64},
        {"runtime_manifest_sha256": "0" * 64},
        {"auth_key_sha256": "0" * 64},
        {"service_sid": "not-a-sid"},
        {"client_sid": "S-1-5-21-not-numeric"},
        {"pipe_address": r"\\.\pipe\caller-selected"},
        {"receipt_root": r"C:\caller\receipts"},
        {"worker_path": "scripts/caller.py"},
        {"auth_key_path": r"C:\caller\key.bin"},
    ],
)
def test_descriptor_rejects_nonfixed_or_unpinned_fields(update):
    value = _descriptor_value(**update)
    raw = _canonical(value)
    with pytest.raises(anchor.DeploymentAnchorError):
        anchor._parse_deployment_descriptor(raw, expected_sha256=_sha(raw))


def test_descriptor_rejects_tampering_noncanonical_bytes_and_parent_digest_mismatch():
    raw = _canonical(_descriptor_value())
    tampered = raw.replace(b"sealed", b"seald!")
    with pytest.raises(anchor.DeploymentAnchorError, match="digest_mismatch"):
        anchor._parse_deployment_descriptor(tampered, expected_sha256=_sha(raw))

    duplicate = raw[:-1] + b',"operation":"ctp_readonly_preflight"}'
    with pytest.raises(anchor.DeploymentAnchorError, match="duplicate_key"):
        anchor._parse_deployment_descriptor(duplicate, expected_sha256=_sha(duplicate))

    value = _descriptor_value(parent_trust_descriptor_sha256=_sha(b"different parent"))
    bad_parent = _canonical(value)
    with pytest.raises(
        anchor.DeploymentAnchorError, match="parent_trust_descriptor_digest_mismatch"
    ):
        anchor._parse_deployment_descriptor(bad_parent, expected_sha256=_sha(bad_parent))

    noncanonical = json.dumps(_descriptor_value(), sort_keys=False).encode("ascii")
    with pytest.raises(anchor.DeploymentAnchorError, match="not_canonical"):
        anchor._parse_deployment_descriptor(
            noncanonical,
            expected_sha256=_sha(noncanonical),
            expected_worker_dependency_sha256=_sha(b'{"schema":"worker-dependencies.v1"}'),
            expected_runtime_manifest_sha256=_sha(b'{"schema":"runtime-closure.v1"}'),
        )


def test_unset_production_pin_rejects_before_known_folder_or_file_access(monkeypatch):
    assert anchor.GUARDIAN_DEPLOYMENT_DESCRIPTOR_SHA256 == "0" * 64
    called = []

    def unexpected_known_folder():
        called.append(True)
        raise AssertionError("unset pin must reject before filesystem discovery")

    monkeypatch.setattr(anchor, "_program_data_path", unexpected_known_folder)
    with pytest.raises(anchor.DeploymentAnchorError, match="deployment_anchor_pin_unset"):
        anchor.load_fixed_deployment_anchor()
    assert called == []
    raw = _canonical(_descriptor_value())
    with pytest.raises(anchor.DeploymentAnchorError, match="worker_dependency_closure_pin_unset"):
        anchor._parse_deployment_descriptor(raw, expected_sha256=_sha(raw))


def test_missing_dependency_manifest_pin_rejects_before_known_folder_or_file_access(monkeypatch):
    monkeypatch.setattr(anchor, "GUARDIAN_DEPLOYMENT_DESCRIPTOR_SHA256", _sha(b"descriptor pin"))
    monkeypatch.setattr(anchor, "WORKER_DEPENDENCY_MANIFEST_SHA256", "0" * 64)
    called = []
    monkeypatch.setattr(anchor, "_program_data_path", lambda: called.append(True))
    with pytest.raises(anchor.DeploymentAnchorError, match="worker_dependency_closure_pin_unset"):
        anchor.load_fixed_deployment_anchor()
    assert called == []


def test_unset_runtime_manifest_pin_rejects_before_known_folder_or_file_access(monkeypatch):
    monkeypatch.setattr(anchor, "GUARDIAN_DEPLOYMENT_DESCRIPTOR_SHA256", _sha(b"descriptor pin"))
    monkeypatch.setattr(anchor, "WORKER_DEPENDENCY_MANIFEST_SHA256", _sha(b"dependency pin"))
    monkeypatch.setattr(anchor, "RUNTIME_MANIFEST_SHA256", "0" * 64)
    called = []
    monkeypatch.setattr(anchor, "_program_data_path", lambda: called.append(True))

    with pytest.raises(anchor.DeploymentAnchorError, match="runtime_manifest_pin_unset"):
        anchor.load_fixed_guardian_client_binding()
    with pytest.raises(anchor.DeploymentAnchorError, match="runtime_manifest_pin_unset"):
        anchor.load_fixed_deployment_anchor()

    assert called == []


def test_v1_descriptor_and_fixed_runtime_path_are_not_accepted_as_v2():
    value = _descriptor_value(schema="ctp_i13_i15_guardian_deployment.v1")
    raw = _canonical(value)
    with pytest.raises(anchor.DeploymentAnchorError, match="deployment_operation_binding_invalid"):
        anchor._parse_deployment_descriptor(
            raw,
            expected_sha256=_sha(raw),
            expected_worker_dependency_sha256=value["worker_dependency_manifest_sha256"],
            expected_runtime_manifest_sha256=value["runtime_manifest_sha256"],
        )

    paths = anchor._fixed_paths(r"C:\ProgramData")
    assert paths[4] == (r"C:\ProgramData\Backtrader\Iteration41\ctp-readonly-guardian\runtime.json")
    assert paths[5] == (r"C:\ProgramData\Backtrader\Iteration41\ctp-readonly-guardian\receipts")


def _runtime_anchor_for_test():
    value = object.__new__(anchor.GuardianDeploymentAnchor)
    fields = {
        "_closed": False,
        "_execution_close_attempted": False,
        "runtime_manifest_sha256": _sha(b'{"schema":"runtime-closure.v1"}'),
        "runtime_base_root": r"C:\Python311",
        "runtime_venv_root": r"C:\sealed\venv",
        "pyvenv_cfg_sha256": _sha(b"home = C:\\Python311\n"),
        "stdlib_paths": (r"C:\Python311\Lib", r"C:\Python311\DLLs"),
        "python_executable": r"C:\sealed\venv\Scripts\python.exe",
        "python_sha256": _sha(b"python"),
        "python_version": "3.11.5",
        "python_architecture": "AMD64",
        "_acl_trusted_sids": frozenset({"S-1-5-18", "S-1-5-32-544"}),
    }
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def test_runtime_descriptor_facts_are_exact_verified_readonly_parent_facts():
    value = _runtime_anchor_for_test()

    facts = value.runtime_descriptor_facts

    assert dict(facts) == {
        "python_executable": value.python_executable,
        "python_sha256": value.python_sha256,
        "python_version": "3.11.5",
        "python_architecture": "AMD64",
        "python_home": value.runtime_base_root,
        "venv_root": value.runtime_venv_root,
        "pyvenv_cfg_sha256": value.pyvenv_cfg_sha256,
        "stdlib_paths": value.stdlib_paths,
    }
    with pytest.raises(TypeError):
        facts["python_home"] = r"C:\attacker"


def test_pycache_prefix_is_derived_only_from_verified_runtime_home():
    value = _runtime_anchor_for_test()

    assert value.pycache_prefix == r"C:\Python311\disabled-bytecode-cache"
    assert anchor.FIXED_PYCACHE_PREFIX_NAME == "disabled-bytecode-cache"
    object.__setattr__(value, "_execution_close_attempted", True)
    with pytest.raises(anchor.DeploymentAnchorError, match="deployment_anchor_closed"):
        _ = value.pycache_prefix


def test_runtime_manifest_reads_fixed_retained_path_and_checks_digest():
    value = _runtime_anchor_for_test()
    raw = b'{"schema":"runtime-closure.v1"}'
    object.__setattr__(value, "runtime_manifest_sha256", _sha(raw))
    object.__setattr__(
        value,
        "_runtime_manifest_path",
        r"C:\ProgramData\Backtrader\Iteration41\ctp-readonly-guardian\runtime.json",
    )

    class FakeProgramDataPaths:
        def __init__(self):
            self.calls = []

        def read_file(self, path, *, max_bytes):
            self.calls.append((path, max_bytes))
            return raw

    paths = FakeProgramDataPaths()
    object.__setattr__(value, "_programdata_paths", paths)

    assert value.read_runtime_manifest() == raw
    assert paths.calls == [(value._runtime_manifest_path, 4 * 1024 * 1024)]

    object.__setattr__(value, "runtime_manifest_sha256", _sha(b"different manifest"))
    with pytest.raises(anchor.DeploymentAnchorError, match="runtime_manifest_digest_mismatch"):
        value.read_runtime_manifest()


def test_runtime_path_retention_is_limited_to_fixed_roots_and_relative_manifest_paths(monkeypatch):
    value = _runtime_anchor_for_test()
    created = []

    class FakeProtectedPaths:
        def __init__(self, trusted_sids):
            self.trusted_sids = trusted_sids
            self.added = []
            self.closed = False
            created.append(self)

        def add_paths(self, paths, **kwargs):
            self.added.append((tuple(paths), kwargs))

        def list_directory(self, path):
            return ("python.exe",)

        def read_file(self, path, *, max_bytes):
            return b"pinned"

        def verify_current(self):
            return None

        def close(self):
            self.closed = True

    monkeypatch.setattr(anchor, "_ProtectedWindowsPaths", FakeProtectedPaths)
    retained = value.retain_runtime_paths(
        "base",
        ("python.exe", "python311.dll"),
        ("Lib", "DLLs"),
    )

    assert retained.list_directory("") == ("python.exe",)
    assert created[0].trusted_sids == value._acl_trusted_sids
    assert created[0].added[0][0] == (value.runtime_base_root,)
    assert created[0].added[0][1]["listable_directory_paths"] == frozenset(
        {value.runtime_base_root}
    )
    assert created[0].added[1][0] == (r"C:\Python311\DLLs",)
    assert created[0].added[2][0] == (r"C:\Python311\Lib",)
    assert created[0].added[3][0] == (r"C:\Python311\python.exe",)
    assert created[0].added[4][0] == (r"C:\Python311\python311.dll",)

    retained.close()
    assert created[0].closed
    with pytest.raises(anchor.DeploymentAnchorError, match="runtime_root_kind_invalid"):
        value.retain_runtime_paths("dependencies", (), ())
    with pytest.raises(anchor.DeploymentAnchorError, match="dependency_relative_path_invalid"):
        value.retain_runtime_paths("venv", ("../outside.dll",), ())
    assert len(created) == 1


def test_client_binding_loader_rejects_unset_pin_before_known_folder_or_key_access(monkeypatch):
    assert anchor.GUARDIAN_DEPLOYMENT_DESCRIPTOR_SHA256 == "0" * 64
    called = []
    monkeypatch.setattr(anchor, "_program_data_path", lambda: called.append("programdata"))
    monkeypatch.setattr(
        anchor,
        "_ProtectedWindowsPaths",
        lambda *args, **kwargs: called.append("protected_paths"),
    )

    with pytest.raises(anchor.DeploymentAnchorError, match="deployment_anchor_pin_unset"):
        anchor.load_fixed_guardian_client_binding()

    assert called == []


def test_fixed_service_sid_shape_and_descriptor_binding_are_strict():
    service_sid = "S-1-5-80-111-222-333-444-555"
    assert anchor._canonical_service_sid(service_sid) == service_sid
    assert anchor._assert_fixed_service_sid(service_sid, service_sid) == service_sid

    for invalid in (
        "S-1-5-18",
        "S-1-5-80-1-2-3-4",
        "S-1-5-80-1-2-3-4-4294967296",
        "S-1-5-80-1-2-3-4-5-extra",
    ):
        with pytest.raises(anchor.DeploymentAnchorError, match="guardian_service_sid_invalid"):
            anchor._canonical_service_sid(invalid)

    with pytest.raises(anchor.DeploymentAnchorError, match="guardian_service_identity_mismatch"):
        anchor._assert_fixed_service_sid(service_sid, "S-1-5-80-111-222-333-444-556")


class _FakeClientDescriptorLease:
    def __init__(self, raw):
        self.raw = raw
        self.events = []
        self.closed = False

    def verify_current(self):
        self.events.append("verify")
        if self.closed:
            raise anchor.DeploymentAnchorError("fake_lease_closed")

    def read_file(self, path, *, max_bytes):
        self.events.append(("read", path, max_bytes))
        if self.closed:
            raise anchor.DeploymentAnchorError("fake_lease_closed")
        return self.raw

    def close(self):
        self.events.append("close")
        self.closed = True


def _make_client_binding(monkeypatch, *, client_sid="S-1-5-21-10-20-30-1001"):
    service_sid = "S-1-5-80-111-222-333-444-555"
    value = _descriptor_value(service_sid=service_sid, client_sid=client_sid)
    raw = _canonical(value)
    parsed = anchor._parse_deployment_descriptor(
        raw,
        expected_sha256=_sha(raw),
        expected_worker_dependency_sha256=_sha(b'{"schema":"worker-dependencies.v1"}'),
        expected_runtime_manifest_sha256=_sha(b'{"schema":"runtime-closure.v1"}'),
    )
    paths = _FakeClientDescriptorLease(raw)
    monkeypatch.setattr(anchor, "_lookup_fixed_service_sid", lambda: service_sid)
    binding = anchor._client_binding_from_descriptor(
        parsed,
        descriptor_path=r"C:\ProgramData\Backtrader\Iteration41\ctp-readonly-guardian\deployment.json",
        descriptor_paths=paths,
        service_sid=service_sid,
        worker_dependency_manifest_sha256=parsed.worker_dependency_manifest_sha256,
    )
    return binding, paths, value


def test_client_binding_is_readonly_descriptor_view_and_never_contains_key(monkeypatch):
    binding, paths, value = _make_client_binding(monkeypatch)

    binding.verify_current()

    assert binding.service_name == "BacktraderCtpReadonlyGuardian"
    assert binding.service_sid == value["service_sid"]
    assert binding.client_sid == value["client_sid"]
    assert binding.pipe_address == value["pipe_address"]
    assert binding.python_executable == value["python"]["executable"]
    assert binding.python_sha256 == value["python"]["sha256"]
    assert binding.descriptor_sha256 == _sha(_canonical(value))
    assert binding.runtime_manifest_sha256 == value["runtime_manifest_sha256"]
    assert paths.events == ["verify", ("read", binding._descriptor_path, 64 * 1024), "verify"]
    assert not hasattr(binding, "auth_key")
    assert "k" * 32 not in repr(binding)
    assert "authkey.bin" not in repr(binding)

    binding.close()
    assert paths.closed
    assert paths.events[-1] == "close"
    with pytest.raises(anchor.DeploymentAnchorError, match="guardian_client_binding_closed"):
        binding.verify_current()


def test_client_binding_rejects_changed_descriptor_without_reading_authkey(monkeypatch):
    binding, paths, value = _make_client_binding(monkeypatch)
    changed = dict(value)
    changed["pipe_address"] = r"\\.\pipe\backtrader-ctp-i13-i15-" + "b" * 32
    paths.raw = _canonical(changed)

    with pytest.raises(anchor.DeploymentAnchorError, match="deployment_descriptor_digest_mismatch"):
        binding.verify_current()

    assert all(not (isinstance(item, tuple) and "authkey" in str(item)) for item in paths.events)


@pytest.mark.parametrize(
    "client_sid",
    ["S-1-1-0", "S-1-5-11", "S-1-5-18", "S-1-5-32-544", "S-1-5-80-111-222-333-444-555"],
)
def test_client_binding_rejects_broad_or_service_identity(monkeypatch, client_sid):
    service_sid = "S-1-5-80-111-222-333-444-555"
    value = _descriptor_value(service_sid=service_sid, client_sid=client_sid)
    raw = _canonical(value)
    parsed = anchor._parse_deployment_descriptor(
        raw,
        expected_sha256=_sha(raw),
        expected_worker_dependency_sha256=_sha(b'{"schema":"worker-dependencies.v1"}'),
        expected_runtime_manifest_sha256=_sha(b'{"schema":"runtime-closure.v1"}'),
    )
    monkeypatch.setattr(anchor, "_lookup_fixed_service_sid", lambda: service_sid)

    with pytest.raises(anchor.DeploymentAnchorError, match="guardian_client_sid_invalid"):
        anchor._client_binding_from_descriptor(
            parsed,
            descriptor_path=r"C:\ProgramData\deployment.json",
            descriptor_paths=_FakeClientDescriptorLease(raw),
            service_sid=service_sid,
            worker_dependency_manifest_sha256=parsed.worker_dependency_manifest_sha256,
        )


def _directory_entry(name, *, attributes=0x80):
    encoded_name = name.encode("utf-16-le")
    name_offset = anchor._FileIdBothDirectoryInfo.FileName.offset
    raw = bytearray(
        max(ctypes.sizeof(anchor._FileIdBothDirectoryInfo), name_offset + len(encoded_name))
    )
    raw[0:4] = (0).to_bytes(4, "little")
    raw[56:60] = attributes.to_bytes(4, "little")
    raw[60:64] = len(encoded_name).to_bytes(4, "little")
    raw[name_offset : name_offset + len(encoded_name)] = encoded_name
    return bytes(raw)


class _FakeWindowsFunction:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


class _FakeDirectoryKernel:
    def __init__(self, records):
        self.records = list(records)
        self.calls = []
        self.GetFileInformationByHandleEx = _FakeWindowsFunction(self._query)

    def _query(self, handle, information_class, buffer, buffer_size):
        self.calls.append((handle.value, information_class, buffer_size))
        if not self.records:
            ctypes.set_last_error(anchor._ERROR_NO_MORE_FILES)
            return 0
        record = self.records.pop(0)
        ctypes.memmove(ctypes.addressof(buffer), record, len(record))
        return 1


def _fake_protected_directory(records):
    paths = object.__new__(anchor._ProtectedWindowsPaths)
    path = r"C:\sealed\venv\Lib\site-packages\package"
    entry = anchor._ProtectedEntry(
        path=path,
        handle=123,
        identity=(7, 9),
        is_directory=True,
        trusted_sids=frozenset({"S-1-5-18", "S-1-5-32-544"}),
        allowed_read_sids=None,
        share_write=False,
        can_list_directory=True,
    )
    paths._entries = {paths._key(path): entry}
    paths._closed = False
    paths._poisoned = False
    paths._kernel32 = _FakeDirectoryKernel(records)
    paths._trusted_sids = entry.trusted_sids
    paths._validate_calls = 0
    paths._file_info_calls = 0

    def validate_acl(handle, **kwargs):
        paths._validate_calls += 1

    def file_info(handle):
        paths._file_info_calls += 1
        return type(
            "Info",
            (),
            {
                "dwVolumeSerialNumber": 7,
                "nFileIndexHigh": 0,
                "nFileIndexLow": 9,
                "dwFileAttributes": 0x10,
                "nFileSizeHigh": 0,
                "nFileSizeLow": 0,
            },
        )()

    paths._validate_handle_acl = validate_acl
    paths._file_information = file_info
    return paths, path


def test_retained_directory_enumerates_sorted_names_through_same_handle(monkeypatch):
    paths, path = _fake_protected_directory(
        [_directory_entry("zeta.py"), _directory_entry("Alpha"), _directory_entry("module.pyc")]
    )
    monkeypatch.setattr(anchor.ctypes, "get_last_error", lambda: anchor._ERROR_NO_MORE_FILES)

    names = paths.list_directory(path)

    assert names == ("Alpha", "module.pyc", "zeta.py")
    assert [call[0] for call in paths._kernel32.calls] == [123, 123, 123, 123]
    assert [call[1] for call in paths._kernel32.calls] == [
        anchor._FILE_ID_BOTH_DIRECTORY_RESTART_INFO,
        anchor._FILE_ID_BOTH_DIRECTORY_INFO,
        anchor._FILE_ID_BOTH_DIRECTORY_INFO,
        anchor._FILE_ID_BOTH_DIRECTORY_INFO,
    ]
    assert paths._validate_calls == 2
    assert paths._file_info_calls == 2


def test_retained_directory_rejects_identity_change_after_enumeration(monkeypatch):
    paths, path = _fake_protected_directory([_directory_entry("module.py")])
    original = paths._file_information
    calls = []

    def changed_after_first_check(handle):
        info = original(handle)
        calls.append(True)
        if len(calls) > 1:
            info.nFileIndexLow = 10
        return info

    paths._file_information = changed_after_first_check
    monkeypatch.setattr(anchor.ctypes, "get_last_error", lambda: anchor._ERROR_NO_MORE_FILES)

    with pytest.raises(anchor.DeploymentAnchorError, match="protected_path_identity_changed"):
        paths.list_directory(path)

    assert len(calls) == 2


@pytest.mark.parametrize(
    "record,reason",
    [
        (_directory_entry("module.pyc", attributes=0x400), "dependency_directory_entry_invalid"),
        (_directory_entry("nested\\name"), "dependency_directory_entry_invalid"),
        (b"short", "dependency_directory_buffer_invalid"),
    ],
)
def test_directory_buffer_rejects_reparse_invalid_name_and_truncation(record, reason):
    with pytest.raises(anchor.DeploymentAnchorError, match=reason):
        anchor._parse_file_id_both_directory_buffer(record)


def test_directory_buffer_skips_dot_entries_only_when_directory():
    assert anchor._parse_file_id_both_directory_buffer(_directory_entry(".", attributes=0x10)) == ()
    assert (
        anchor._parse_file_id_both_directory_buffer(_directory_entry("..", attributes=0x10)) == ()
    )
    with pytest.raises(anchor.DeploymentAnchorError, match="dependency_directory_entry_invalid"):
        anchor._parse_file_id_both_directory_buffer(_directory_entry(".", attributes=0x80))


@pytest.mark.skipif(os.name != "nt", reason="GetFileInformationByHandleEx is Windows-only")
def test_windows_temp_directory_enumeration_skips_os_dot_entries(tmp_path, monkeypatch):
    directory = tmp_path / "retained-list-directory-smoke"
    directory.mkdir()
    (directory / "alpha.txt").write_text("x", encoding="ascii")
    (directory / "subdir").mkdir()

    path = str(directory)
    paths = anchor._ProtectedWindowsPaths(frozenset({"S-1-5-18", "S-1-5-32-544"}))
    # This mechanics smoke checks the actual retained-handle enumeration path.
    # ACL policy is tested separately; no filesystem ACLs are changed here.
    monkeypatch.setattr(paths, "_validate_handle_acl", lambda *args, **kwargs: None)
    try:
        paths.add_paths(
            (path,),
            directory_paths=frozenset({path}),
            listable_directory_paths=frozenset({path}),
        )
        names = paths.list_directory(path)
    finally:
        paths.close()

    assert names == ("alpha.txt", "subdir")


@pytest.mark.skipif(os.name != "nt", reason="retained Windows directory handles are required")
def test_windows_runtime_cache_prefix_absence_and_unexpected_presence_are_visible(
    tmp_path, monkeypatch
):
    runtime_home = tmp_path / "runtime-home"
    runtime_home.mkdir()
    value = _runtime_anchor_for_test()
    object.__setattr__(value, "runtime_base_root", str(runtime_home))
    expected = str(runtime_home / "disabled-bytecode-cache")
    assert value.pycache_prefix == expected

    # This test exercises file-sharing/identity mechanics only. ACL policy is
    # independently tested and no filesystem ACLs are changed here.
    monkeypatch.setattr(
        anchor._ProtectedWindowsPaths,
        "_validate_handle_acl",
        lambda *args, **kwargs: None,
    )
    retained = value.retain_runtime_paths("base", (), ())
    try:
        assert retained.list_directory("") == ()
        # The temp directory's ACL is deliberately not modified, so this
        # untrusted test writer can create the leaf. The retained enumeration
        # must expose it for the pinned runtime manifest to reject.
        Path(expected).mkdir()
        assert retained.list_directory("") == ("disabled-bytecode-cache",)
    finally:
        retained.close()


def test_retained_directory_rejects_case_collision_and_unleased_directory(monkeypatch):
    paths, path = _fake_protected_directory(
        [_directory_entry("package.pyd"), _directory_entry("PACKAGE.PYD")]
    )
    monkeypatch.setattr(anchor.ctypes, "get_last_error", lambda: anchor._ERROR_NO_MORE_FILES)
    with pytest.raises(anchor.DeploymentAnchorError, match="dependency_directory_case_collision"):
        paths.list_directory(path)

    with pytest.raises(anchor.DeploymentAnchorError, match="not_leased_for_listing"):
        paths.list_directory(r"C:\sealed\venv\Lib\site-packages\other")


def test_dependency_path_wrapper_maps_empty_relative_directory_to_fixed_root():
    class FakePaths:
        def __init__(self):
            self.listed = []

        def list_directory(self, path):
            self.listed.append(path)
            return ("PyYAML",)

    paths = FakePaths()
    retained = anchor._RetainedDependencyPaths(r"C:\sealed\venv\Lib\site-packages", paths)

    assert retained.list_directory("") == ("PyYAML",)
    assert retained.list_directory("yaml") == ("PyYAML",)
    assert paths.listed == [
        r"C:\sealed\venv\Lib\site-packages",
        r"C:\sealed\venv\Lib\site-packages\yaml",
    ]
    with pytest.raises(anchor.DeploymentAnchorError, match="dependency_relative_path_invalid"):
        retained.list_directory("../outside")


def test_listable_directory_path_must_be_an_explicit_retained_directory():
    paths = object.__new__(anchor._ProtectedWindowsPaths)
    paths._closed = False
    paths._poisoned = False
    paths._entries = {}

    with pytest.raises(
        anchor.DeploymentAnchorError, match="protected_path_listable_target_not_directory"
    ):
        paths.add_paths(
            (r"D:\venv\Lib\site-packages\package.pyd",),
            listable_directory_paths=frozenset({r"D:\venv\Lib\site-packages\package.pyd"}),
        )


def test_retained_paths_preserve_list_access_for_nested_explicit_directories():
    paths = object.__new__(anchor._ProtectedWindowsPaths)
    paths._closed = False
    paths._poisoned = False
    paths._entries = {}
    paths._trusted_sids = frozenset({"S-1-5-18", "S-1-5-32-544"})
    seen = {}

    def record_open(path, **kwargs):
        seen[paths._key(path)] = (path, kwargs)
        paths._entries[paths._key(path)] = type(
            "Entry", (), {"can_list_directory": kwargs.get("can_list_directory", False)}
        )()

    paths._open_one = record_open
    parent = r"D:\venv\Lib\site-packages\package"
    child = parent + r"\native"
    paths.add_paths(
        (parent, child),
        directory_paths=frozenset({parent, child}),
        listable_directory_paths=frozenset({parent, child}),
    )

    assert seen[paths._key(parent)][1]["can_list_directory"] is True
    assert seen[paths._key(child)][1]["can_list_directory"] is True


def test_acl_policy_allows_read_only_untrusted_aces_but_trusted_write_aces():
    anchor._validate_acl_facts(
        owner_sid="S-1-5-18",
        trusted_sids=frozenset({"S-1-5-18", "S-1-5-32-544"}),
        aces=(
            (0, 0, 0x00120089, "S-1-5-21-9-8-7-1002"),  # read-only to unrelated SID
            (0, 0, 0x000F01FF, "S-1-5-18"),  # protected SYSTEM owner
            (1, 0, 0xFFFFFFFF, "S-1-1-0"),  # deny does not grant rights
        ),
    )


def test_service_write_is_scoped_to_receipt_directory_and_client_stays_read_only():
    service_sid = "S-1-5-21-100-200-300-400"
    client_sid = "S-1-5-21-100-200-300-401"
    anchor._validate_acl_facts(
        owner_sid="S-1-5-18",
        trusted_sids=frozenset({"S-1-5-18", "S-1-5-32-544", service_sid}),
        aces=((0, 0, 0x40000000, service_sid),),
    )
    with pytest.raises(anchor.DeploymentAnchorError, match="write_access"):
        anchor._validate_acl_facts(
            owner_sid="S-1-5-18",
            trusted_sids=frozenset({"S-1-5-18", "S-1-5-32-544"}),
            aces=((0, 0, 0x40000000, service_sid),),
        )
    with pytest.raises(anchor.DeploymentAnchorError, match="write_access"):
        anchor._validate_acl_facts(
            owner_sid="S-1-5-18",
            trusted_sids=frozenset({"S-1-5-18", "S-1-5-32-544", service_sid}),
            aces=((0, 0, 0x40000000, client_sid),),
        )


def test_auth_key_acl_allows_only_service_os_principals_to_read_key_bytes():
    service_sid = "S-1-5-21-100-200-300-400"
    client_sid = "S-1-5-21-100-200-300-401"
    allowed_readers = frozenset({"S-1-5-18", "S-1-5-32-544", service_sid})
    writers = frozenset({"S-1-5-18", "S-1-5-32-544"})

    # The service can read the key, but its receipt-only write privilege does
    # not extend to the key path. READ_CONTROL is metadata, not key bytes.
    anchor._validate_acl_facts(
        owner_sid="S-1-5-18",
        trusted_sids=writers,
        allowed_read_sids=allowed_readers,
        aces=(
            (0, 0, 0x80000000, service_sid),  # GENERIC_READ
            (0, 0, 0x00020000, "S-1-1-0"),  # READ_CONTROL only
            (0, 0, 0x000F01FF, "S-1-5-18"),
        ),
    )

    for principal, mask, reason in (
        (client_sid, 0x80000000, "untrusted_read_access"),  # GENERIC_READ
        ("S-1-1-0", 0x80000000, "untrusted_read_access"),  # Everyone
        ("S-1-5-11", 0x80000000, "untrusted_read_access"),  # Authenticated Users
        ("S-1-5-11", 0x00000001, "untrusted_read_access"),  # Authenticated Users FILE_READ_DATA
        (client_sid, 0x00000001, "untrusted_read_access"),  # FILE_READ_DATA
        (client_sid, 0x00000008, "untrusted_read_access"),  # FILE_READ_EA
        ("S-1-1-0", 0x10000000, "untrusted_write_access"),  # GENERIC_ALL
    ):
        with pytest.raises(anchor.DeploymentAnchorError, match=reason):
            anchor._validate_acl_facts(
                owner_sid="S-1-5-18",
                trusted_sids=writers,
                allowed_read_sids=allowed_readers,
                aces=((0, 0, mask, principal),),
            )

    with pytest.raises(anchor.DeploymentAnchorError, match="untrusted_write_access"):
        anchor._validate_acl_facts(
            owner_sid="S-1-5-18",
            trusted_sids=writers,
            allowed_read_sids=allowed_readers,
            aces=((0, 0, 0x40000000, service_sid),),  # GENERIC_WRITE
        )

    # The production loader maps only authkey.bin to the restricted reader
    # set; worker/source and descriptor paths retain ordinary read access.
    policy = anchor._auth_key_read_policy(
        r"C:\ProgramData\guardian\authkey.bin", service_sid, client_sid
    )
    assert policy == {
        r"C:\ProgramData\guardian\authkey.bin": allowed_readers,
    }
    for invalid_service_sid, same_client_sid in (
        ("S-1-1-0", client_sid),  # a broad principal cannot become the service reader
        ("S-1-5-11", client_sid),
        (service_sid, service_sid),  # config/client identity cannot inherit key access
    ):
        with pytest.raises(anchor.DeploymentAnchorError, match="deployment_service_sid_invalid"):
            anchor._auth_key_read_policy(
                r"C:\ProgramData\guardian\authkey.bin",
                invalid_service_sid,
                same_client_sid,
            )
    anchor._validate_acl_facts(
        owner_sid="S-1-5-18",
        trusted_sids=writers,
        aces=((0, 0, 0x80000000, client_sid),),  # source/descriptor may be client-readable
    )
    with pytest.raises(anchor.DeploymentAnchorError, match="write_access"):
        anchor._validate_acl_facts(
            owner_sid="S-1-5-18",
            trusted_sids=frozenset({"S-1-5-18", "S-1-5-32-544", service_sid}),
            aces=((0, 0, 0x40000000, client_sid),),
        )


@pytest.mark.parametrize(
    "request_id", ["", "A" * 32, "0" * 31, "0" * 32 + ".json", "../" + "a" * 32]
)
def test_receipt_name_rejects_noncanonical_request_id_before_filesystem_access(request_id):
    paths = object.__new__(anchor._ProtectedWindowsPaths)
    paths._closed = False
    paths._poisoned = False
    paths._entries = {}
    with pytest.raises(anchor.DeploymentAnchorError, match="receipt_request_id_invalid"):
        paths.create_new_receipt(r"C:\protected\receipts", request_id, b"receipt")
    assert paths._entries == {}


def test_receipt_requires_exact_retained_writable_directory_and_nonempty_bounded_bytes():
    paths = object.__new__(anchor._ProtectedWindowsPaths)
    paths._closed = False
    paths._poisoned = False
    paths._entries = {}
    with pytest.raises(anchor.DeploymentAnchorError, match="receipt_content_invalid"):
        paths.create_new_receipt(r"C:\protected\receipts", "a" * 32, b"")
    with pytest.raises(anchor.DeploymentAnchorError, match="receipt_directory_not_writable_lease"):
        paths.create_new_receipt(r"C:\protected\receipts", "a" * 32, b"receipt")


class _FakeLease:
    def __init__(self, name, events, *, fail=False):
        self.name = name
        self.events = events
        self.fail = fail

    def close(self):
        self.events.append(self.name)
        if self.fail:
            raise OSError("fake close failure")


class _FakeReceiptLease(_FakeLease):
    def create_new_receipt(self, directory, request_id, raw):
        self.events.append(("receipt", directory, request_id, raw))
        return str(Path(directory) / (request_id + ".json"))


class _FakeSourceLease:
    def __init__(self, source, events):
        self.source = source
        self.events = events

    def read_source(self, relative_path, *, expected_sha256):
        self.events.append(("source", relative_path, expected_sha256))
        raw = self.source[relative_path]
        if _sha(raw) != expected_sha256:
            raise OSError("digest mismatch")
        return raw


class _FakeSourceSeal:
    def __init__(self, source, events):
        self.files = {path: _sha(raw) for path, raw in source.items()}
        self.source_lease = _FakeSourceLease(source, events)


def _fake_lifecycle_anchor(*, fail_dependency_close=False):
    events = []
    value = object.__new__(anchor.GuardianDeploymentAnchor)
    fields = {
        "_closed": False,
        "_execution_close_attempted": False,
        "_execution_close_failed": False,
        "_receipt_closed": False,
        "_runtime_closure_seal": _FakeLease("runtime", events),
        "_dependency_seal": _FakeLease("dependency", events, fail=fail_dependency_close),
        "_source_seal": _FakeLease("source", events),
        "_source_paths": _FakeLease("source_acl", events),
        "_programdata_paths": _FakeLease("programdata", events),
        "_receipt_paths": _FakeReceiptLease("receipt_lease", events),
        "receipt_root": r"C:\ProgramData\Backtrader\Iteration41\ctp-readonly-guardian\receipts",
    }
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value, events


def _fake_role_source_anchor(source):
    events = []
    value = object.__new__(anchor.GuardianDeploymentAnchor)
    object.__setattr__(value, "_closed", False)
    object.__setattr__(value, "_execution_close_attempted", False)
    object.__setattr__(value, "_source_seal", _FakeSourceSeal(source, events))
    return value, events


def test_fixed_role_sources_are_read_only_from_exact_retained_manifest_entries():
    source = {
        anchor.REQUEST_COORDINATOR_RELATIVE_PATH: b"coordinator source",
        anchor.RECEIPT_WRITER_RELATIVE_PATH: b"receipt writer source",
        anchor.TOKEN_BOOTSTRAP_RELATIVE_PATH: b"token bootstrap source",
    }
    value, events = _fake_role_source_anchor(source)

    assert value.request_coordinator_sha256 == _sha(source[anchor.REQUEST_COORDINATOR_RELATIVE_PATH])
    assert value.read_request_coordinator_source() == source[anchor.REQUEST_COORDINATOR_RELATIVE_PATH]
    assert value.receipt_writer_sha256 == _sha(source[anchor.RECEIPT_WRITER_RELATIVE_PATH])
    assert value.read_receipt_writer_source() == source[anchor.RECEIPT_WRITER_RELATIVE_PATH]
    assert value.token_bootstrap_sha256 == _sha(source[anchor.TOKEN_BOOTSTRAP_RELATIVE_PATH])
    assert value.read_token_bootstrap_source() == source[anchor.TOKEN_BOOTSTRAP_RELATIVE_PATH]
    assert [event[1] for event in events] == [
        anchor.REQUEST_COORDINATOR_RELATIVE_PATH,
        anchor.RECEIPT_WRITER_RELATIVE_PATH,
        anchor.TOKEN_BOOTSTRAP_RELATIVE_PATH,
    ]


def test_fixed_role_source_reader_rejects_unknown_paths_and_post_close_reads():
    source = {anchor.REQUEST_COORDINATOR_RELATIVE_PATH: b"coordinator source"}
    value, events = _fake_role_source_anchor(source)

    with pytest.raises(anchor.DeploymentAnchorError, match="readonly_role_source_not_fixed"):
        value._read_fixed_role_source("scripts/attacker.py")
    assert events == []

    object.__setattr__(value, "_closed", True)
    with pytest.raises(anchor.DeploymentAnchorError, match="deployment_anchor_closed"):
        value.read_request_coordinator_source()
    assert events == []


def test_receipt_requires_execution_lease_close_attempt_and_keeps_output_lease_separate():
    value, events = _fake_lifecycle_anchor()
    with pytest.raises(anchor.DeploymentAnchorError, match="execution_leases_not_closed"):
        value.create_receipt("a" * 32, b"receipt")

    value.close_execution_leases()
    assert events == ["runtime", "dependency", "source", "source_acl", "programdata"]
    target = value.create_receipt("a" * 32, b"receipt")
    assert target.endswith("a" * 32 + ".json")
    assert events[-1] == ("receipt", value.receipt_root, "a" * 32, b"receipt")

    value.close_receipt_lease()
    assert events[-1] == "receipt_lease"


def test_receipt_can_persist_unknown_after_execution_lease_close_failure():
    value, events = _fake_lifecycle_anchor(fail_dependency_close=True)
    with pytest.raises(
        anchor.DeploymentAnchorError, match="deployment_anchor_execution_close_failed"
    ):
        value.close_execution_leases()
    assert value._execution_close_attempted is True
    assert value._execution_close_failed is True

    value.create_receipt("b" * 32, b'{"outcome":"UNKNOWN"}')
    assert events[-1] == (
        "receipt",
        value.receipt_root,
        "b" * 32,
        b'{"outcome":"UNKNOWN"}',
    )


@pytest.mark.parametrize(
    "owner,aces,reason",
    [
        ("S-1-5-21-9-8-7-1002", ((0, 0, 0x1, "S-1-5-18"),), "owner"),
        ("S-1-5-18", ((0, 0, 0x2, "S-1-5-21-9-8-7-1002"),), "write_access"),
        ("S-1-5-18", ((0, 0, 0x4, "S-1-5-21-9-8-7-1002"),), "write_access"),
        ("S-1-5-18", ((0, 0, 0x40, "S-1-5-21-9-8-7-1002"),), "write_access"),
        ("S-1-5-18", ((0, 0, 0x10000, "S-1-5-21-9-8-7-1002"),), "write_access"),
        ("S-1-5-18", ((0, 0, 0x40000, "S-1-5-21-9-8-7-1002"),), "write_access"),
        ("S-1-5-18", ((0, 0, 0x80000, "S-1-5-21-9-8-7-1002"),), "write_access"),
        ("S-1-5-18", ((0, 0, 0x40000000, "S-1-5-21-9-8-7-1002"),), "write_access"),
        ("S-1-5-18", ((0, 0, 0x40000000, "S-1-5-21-1-2-3-1001"),), "write_access"),
        ("S-1-5-18", ((0, 0, 0x40, "S-1-5-21-1-2-3-1001"),), "write_access"),
        ("S-1-5-18", ((0, 0, 0x40000, "S-1-5-21-1-2-3-1001"),), "write_access"),
        ("S-1-5-18", ((0, 0, 0x80000, "S-1-5-21-1-2-3-1001"),), "write_access"),
        ("S-1-5-18", ((5, 0, 0x1, "S-1-5-18"),), "unknown_ace"),
        ("S-1-5-18", ((0, 0x100, 0x1, "S-1-5-18"),), "unknown_ace"),
    ],
)
def test_acl_policy_rejects_untrusted_owner_write_delete_and_unknown_aces(owner, aces, reason):
    with pytest.raises(anchor.DeploymentAnchorError, match=reason):
        anchor._validate_acl_facts(
            owner_sid=owner,
            aces=aces,
            trusted_sids=frozenset({"S-1-5-18", "S-1-5-32-544"}),
        )
