"""Cursor-aware fake coverage for the additive V19 admission lease."""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[3]
_V17_BASELINE_SUPPORT_PINS = (
    (
        "backtrader_runtime/certification_simnow_c01_native_td_read_v17.py",
        189499,
        "fa202e00da45fced059b6409e17c2ea9d41b0f8e0f1666f56491735a7f39b795",
    ),
    (
        "scripts/run_simnow_c01_native_td_read_v17_root_activation_r1.py",
        70858,
        "1c1b2a09c39d680b3c5cf2687dc2514a57c2faa71d8e9191cdf1444f106d650c",
    ),
    (
        "examples/000_live_certification/simnow_penetration/cases/C01/run_v17.py",
        9129,
        "9d34964cae9eb4b6a7435cb77a641dab6fb4c08a38eb4ac4e357a81c007cbd9d",
    ),
)


class _FakeFunction:
    def __init__(self, callback):
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


class _CursorHandle:
    def __init__(self, path: Path, *, directory: bool):
        self.path = Path(path)
        self.directory = directory
        self.position = 0
        self.closed = False
        self.protected = True


class _CursorApi:
    """Synthetic OS leaves; bounded reads still use the pinned production helper."""

    def __init__(self):
        self.private = None
        self.handles = []
        self.read_calls = []
        self.seek_calls = []
        self.acl_calls = []
        self.fail_seek_path = None
        self.kernel = type("Kernel", (), {})()
        self.kernel.ReadFile = _FakeFunction(self._read_file)
        self.kernel.SetFilePointerEx = _FakeFunction(self._set_file_pointer)
        self.kernel.GetFileInformationByHandle = _FakeFunction(self._file_information)
        self.CreateFileW = _FakeFunction(self._create_file)
        self.CloseHandle = _FakeFunction(self._close_handle)

    def _new_handle(self, path, *, directory):
        handle = _CursorHandle(Path(path), directory=directory)
        self.handles.append(handle)
        return handle

    def _create_file(self, path, *_args):
        path = Path(path)
        if not path.is_file():
            return self.private._INVALID_HANDLE
        return self._new_handle(path, directory=False)

    @contextmanager
    def opened(self, path, *, directory, access=None):
        del access
        path = Path(path)
        if not directory or not path.is_dir():
            raise OSError("synthetic directory open rejected")
        handle = self._new_handle(path, directory=True)
        try:
            yield handle
        finally:
            self._close_handle(handle)

    def current_sid(self):
        return "S-1-5-21-SOURCE-FAKE"

    def verify_acl(self, handle, sid, *, directory=False):
        assert sid == self.current_sid()
        assert not handle.closed
        assert handle.directory is directory
        assert handle.protected is True
        self.acl_calls.append((handle.path, directory))

    def _close_handle(self, handle):
        handle.closed = True
        return 1

    def _file_information(self, handle, output):
        info = ctypes.cast(output, ctypes.POINTER(self.private._FILE_INFO))[0]
        stat = handle.path.stat()
        inode = int(stat.st_ino)
        info.attributes = 0
        info.volume = int(stat.st_dev) & 0xFFFFFFFF
        info.links = int(stat.st_nlink)
        info.index_low = inode & 0xFFFFFFFF
        info.index_high = (inode >> 32) & 0xFFFFFFFF
        return 1

    def _read_file(self, handle, buffer, maximum, bytes_read, _overlapped):
        raw = handle.path.read_bytes()
        start = handle.position
        chunk = raw[start : start + maximum]
        if chunk:
            ctypes.memmove(buffer, chunk, len(chunk))
        count = ctypes.cast(bytes_read, ctypes.POINTER(self.private.W.DWORD))
        count[0] = self.private.W.DWORD(len(chunk))
        handle.position += len(chunk)
        self.read_calls.append((handle.path, start, len(chunk)))
        return 1

    def _set_file_pointer(self, handle, distance, new_position, move_method):
        self.seek_calls.append(handle.path)
        if handle.path == self.fail_seek_path:
            return 0
        if int(distance.value) != 0 or move_method != 0 or handle.closed:
            return 0
        handle.position = 0
        pointer = ctypes.cast(new_position, ctypes.POINTER(ctypes.c_longlong))
        pointer[0] = 0
        return 1


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _SyntheticDirectory:
    def __init__(self, path: Path):
        self.path = Path(path)

    def write_bytes(self, name: str, value: bytes):
        (self.path / name).write_bytes(value)


def _setup_lease(*, version: int, tmp_path: Path, monkeypatch, fail_seek_path=None):
    if version == 17:
        for relative, expected_size, expected_sha256 in _V17_BASELINE_SUPPORT_PINS:
            support_bytes = (ROOT / Path(relative)).read_bytes()
            assert len(support_bytes) == expected_size
            assert hashlib.sha256(support_bytes).hexdigest() == expected_sha256
    version_text = f"v{version}"
    issuer_path = ROOT / "backtrader_runtime" / f"certification_simnow_c01_native_td_read_{version_text}.py"
    root_path = ROOT / "scripts" / f"run_simnow_c01_native_td_read_{version_text}_root_activation_r1.py"
    runner_path = (
        ROOT
        / "examples"
        / "000_live_certification"
        / "simnow_penetration"
        / "cases"
        / "C01"
        / f"run_{version_text}.py"
    )
    issuer = _load_module(f"_v{version}_lease_issuer_{id(tmp_path)}", issuer_path)
    root_entry = _load_module(f"_v{version}_lease_root_{id(tmp_path)}", root_path)
    issuer_digest = hashlib.sha256(issuer_path.read_bytes()).hexdigest()
    issuer.__c01_source_sha256__ = issuer_digest
    required = issuer._required_admission_bindings(
        issuer_source_sha256=issuer_digest,
        case_runner_source_sha256=hashlib.sha256(runner_path.read_bytes()).hexdigest(),
    )

    user_profile = tmp_path / "synthetic-user-profile"
    local_app_data = user_profile / "AppData" / "Local"
    admission_id = "b" * 32
    collection_dir = (
        local_app_data / issuer._ADMISSION_ROOT_NAME / issuer._ADMISSION_COLLECTION_NAME
    )
    admission_dir = collection_dir / admission_id
    admission_dir.mkdir(parents=True)
    raw_admission = root_entry._build_admission_document(
        admission_id=admission_id,
        required_bindings=required,
        configured_pair_count=8,
        config_sha256=hashlib.sha256(b"synthetic config").hexdigest(),
        account_scope_sha256=hashlib.sha256(b"synthetic account").hexdigest(),
        credential_binding_sha256=hashlib.sha256(b"synthetic credential").hexdigest(),
        now=issuer.datetime.now(issuer.timezone.utc),
    )
    admission_path = admission_dir / "admission.json"
    admission_path.write_bytes(raw_admission)

    api = _CursorApi()
    api.fail_seek_path = Path(fail_seek_path) if fail_seek_path is not None else None
    original_load = issuer._load_admission_helpers

    def load_synthetic_leaves(root):
        private, r3_cli = original_load(root)
        api.private = private
        private._api = lambda: api

        def create_private_directory(path):
            path = Path(path)
            path.mkdir()
            return _SyntheticDirectory(path)

        private.create_private_directory = create_private_directory
        r3_cli._known_local_app_data = lambda: str(local_app_data)
        return private, r3_cli

    monkeypatch.setattr(issuer, "_load_admission_helpers", load_synthetic_leaves)
    monkeypatch.setenv("USERPROFILE", str(user_profile))
    return issuer, api, admission_path, admission_dir, collection_dir


def _replace_last_byte(path: Path):
    raw = path.read_bytes()
    assert raw
    replacement = b" " if raw[-1:] != b" " else b"!"
    path.write_bytes(raw[:-1] + replacement)


def test_v19_issuer_front_root_runner_and_manifest_pins_agree():
    issuer_path = ROOT / "backtrader_runtime" / "certification_simnow_c01_native_td_read_v19.py"
    manifest_path = (
        ROOT / "backtrader_runtime" / "certification_simnow_c01_native_td_read_v19.sources.json"
    )
    schema_path = (
        ROOT
        / "backtrader_runtime"
        / "certification_simnow_c01_native_td_read_v19.admission.schema.json"
    )
    front_path = ROOT / "backtrader_runtime" / "certification_simnow_c01_front_transport_v13.py"
    root_path = ROOT / "scripts" / "run_simnow_c01_native_td_read_v19_root_activation_r1.py"
    runner_path = (
        ROOT
        / "examples"
        / "000_live_certification"
        / "simnow_penetration"
        / "cases"
        / "C01"
        / "run_v19.py"
    )
    issuer_sha = hashlib.sha256(issuer_path.read_bytes()).hexdigest()
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    schema_sha = hashlib.sha256(schema_path.read_bytes()).hexdigest()
    front_sha = hashlib.sha256(front_path.read_bytes()).hexdigest()
    runner_sha = hashlib.sha256(runner_path.read_bytes()).hexdigest()
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))

    assert manifest["profile_id"] == "C01_NATIVE_TD_READ_V19"
    assert manifest["schema"] == "simnow.c01.native_td_read_v19.source_manifest.v1"
    assert manifest["admission_bound_files"] == [
        "backtrader_runtime/certification_simnow_c01_native_td_read_v19.py",
        "examples/000_live_certification/simnow_penetration/cases/C01/run_v19.py",
    ]
    assert manifest["source_files"][schema_path.relative_to(ROOT).as_posix()] == schema_sha
    for relative, expected_sha in manifest["source_files"].items():
        assert hashlib.sha256((ROOT / Path(relative)).read_bytes()).hexdigest() == expected_sha

    issuer = _load_module("_v19_chain_issuer_source_fake", issuer_path)
    front = _load_module("_v19_chain_front_source_fake", front_path)
    root_entry = _load_module("_v19_chain_root_source_fake", root_path)
    runner_text = runner_path.read_text(encoding="utf-8")
    root_text = root_path.read_text(encoding="utf-8")
    assert issuer.PROFILE_ID == "C01_NATIVE_TD_READ_V19"
    assert issuer._SOURCE_MANIFEST_SHA256 == manifest_sha
    assert issuer._ADMISSION_SCHEMA_SHA256 == schema_sha
    assert front._V19_SHA256 == issuer_sha
    assert root_entry._V19_SHA256 == issuer_sha
    assert root_entry._V19_MANIFEST_SHA256 == manifest_sha
    assert root_entry._V19_SCHEMA_SHA256 == schema_sha
    assert root_entry._FRONT_TRANSPORT_RELATIVE.endswith("front_transport_v13.py")
    assert root_entry._FRONT_TRANSPORT_SHA256 == front_sha
    assert root_entry._CASE_RUNNER_SHA256 == runner_sha
    assert "verified_c01_v19_sources" in root_text
    assert "VerifiedC01V19SourceBundle" in root_text
    assert f'ISSUER_SHA256 = "{issuer_sha}"' in runner_text


def test_v17_eof_regression_and_v19_three_handle_rewind(tmp_path, monkeypatch):
    old_root = tmp_path / "old-v17"
    old_root.mkdir()
    old_issuer, old_api, old_admission, _, _ = _setup_lease(
        version=17, tmp_path=old_root, monkeypatch=monkeypatch
    )
    with pytest.raises(old_issuer._IssuerError) as old_error:
        with old_issuer._profile_admission_lease(ROOT, old_issuer):
            pass
    assert old_error.value.args == ("admission_source_changed",)
    old_reads = [call for call in old_api.read_calls if call[0] == old_admission]
    assert [call[1] for call in old_reads] == [0, len(old_admission.read_bytes())]
    assert old_api.seek_calls == []

    new_root = tmp_path / "new-v19"
    new_root.mkdir()
    issuer, api, admission_path, admission_dir, collection_dir = _setup_lease(
        version=19, tmp_path=new_root, monkeypatch=monkeypatch
    )
    with issuer._profile_admission_lease(ROOT, issuer) as admitted:
        assert type(admitted) is issuer._C01V19Admission
        assert admitted.configured_front_pair_count == 8
        paths = {
            admission_path,
            admission_dir / "consumed" / "consumed.json",
            collection_dir / issuer._ADMISSION_CLAIM_NAME / "claim.json",
        }
        assert all(path.is_file() for path in paths)

    for path in paths:
        reads = [call for call in api.read_calls if call[0] == path]
        assert len(reads) == 2
        assert [call[1] for call in reads] == [0, 0]
        assert [call[2] for call in reads] == [path.stat().st_size, path.stat().st_size]
        assert api.seek_calls.count(path) == 1
        assert sum(1 for item in api.acl_calls if item == (path, False)) == 2
    assert all(handle.closed for handle in api.handles)


@pytest.mark.parametrize("target", ["admission", "marker", "claim"])
def test_v19_seek_failure_fails_closed_without_reread(tmp_path, monkeypatch, target):
    issuer, api, admission_path, admission_dir, collection_dir = _setup_lease(
        version=19, tmp_path=tmp_path, monkeypatch=monkeypatch
    )
    target_paths = {
        "admission": admission_path,
        "marker": admission_dir / "consumed" / "consumed.json",
        "claim": collection_dir / issuer._ADMISSION_CLAIM_NAME / "claim.json",
    }
    api.fail_seek_path = target_paths[target]
    with pytest.raises(issuer._IssuerError) as error:
        with issuer._profile_admission_lease(ROOT, issuer):
            pass
    expected = {
        "admission": "admission_source_changed",
        "marker": "admission_consumed_marker_changed",
        "claim": "admission_claim_marker_changed",
    }[target]
    assert error.value.args == (expected,)
    assert target_paths[target] in api.seek_calls
    target_reads = [call for call in api.read_calls if call[0] == target_paths[target]]
    assert len(target_reads) == 1
    assert target_reads[0][1] == 0
    assert all(handle.closed for handle in api.handles)


@pytest.mark.parametrize("target", ["admission", "marker", "claim"])
def test_v19_changed_content_fails_exact_same_handle_revalidation(
    tmp_path, monkeypatch, target
):
    issuer, api, admission_path, admission_dir, collection_dir = _setup_lease(
        version=19, tmp_path=tmp_path, monkeypatch=monkeypatch
    )
    target_paths = {
        "admission": admission_path,
        "marker": admission_dir / "consumed" / "consumed.json",
        "claim": collection_dir / issuer._ADMISSION_CLAIM_NAME / "claim.json",
    }
    with pytest.raises(issuer._IssuerError) as error:
        with issuer._profile_admission_lease(ROOT, issuer):
            _replace_last_byte(target_paths[target])
    expected = {
        "admission": "admission_source_changed",
        "marker": "admission_consumed_marker_changed",
        "claim": "admission_claim_marker_changed",
    }[target]
    assert error.value.args == (expected,)
    reads = [call for call in api.read_calls if call[0] == target_paths[target]]
    assert len(reads) == 2
    assert [call[1] for call in reads] == [0, 0]
    assert target_paths[target] in api.seek_calls
    assert all(handle.closed for handle in api.handles)
