"""Offline tests for the exact isolated-worker dependency closure."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import io
import json
import sys
import types
import uuid
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
_MISSING_MODULE = object()


def _load_module():
    name = "_i13_worker_dependency_seal_" + uuid.uuid4().hex
    path = REPO_ROOT / "backtrader_runtime" / "ctp_i13_worker_dependency_seal.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return name, module


MODULE_NAME, seal_module = _load_module()

_DIST = {
    "PyYAML": (
        "6.0.1",
        "pyyaml-6.0.1-cp311-cp311-win_amd64.whl",
        "pyyaml-6.0.1.dist-info",
        "yaml",
        "cp311-cp311-win_amd64",
    ),
    "bt_api_base": (
        "0.15.4",
        "bt_api_base-0.15.4-py3-none-any.whl",
        "bt_api_base-0.15.4.dist-info",
        "bt_api_base",
        "py3-none-any",
    ),
    "bt_api_ctp": (
        "2.0.4+iteration41.i9",
        "bt_api_ctp-2.0.4+iteration41.i9-cp311-cp311-win_amd64.whl",
        "bt_api_ctp-2.0.4+iteration41.i9.dist-info",
        "bt_api_ctp",
        "cp311-cp311-win_amd64",
    ),
}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _wheel_record_digest(raw):
    encoded = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=")
    return "sha256=" + encoded.decode("ascii")


def _fixture():
    content = {
        "yaml/__init__.py": b"VALUE = 'yaml'\n",
        "yaml/_yaml.cp311-win_amd64.pyd": b"fake yaml extension; never load\n",
        "_yaml/__init__.py": b"legacy PyYAML shim; inventory only\n",
        "bt_api_base/__init__.py": b"VALUE = 'base'\n",
        "bt_api_ctp/__init__.py": b"VALUE = 'ctp'\n",
        "bt_api_ctp/ctp/__init__.py": b"VALUE = 'native package'\n",
        "bt_api_ctp/ctp/_ctp.cp311-win_amd64.pyd": b"fake native image; never load\n",
        "bt_api_ctp/ctp/thosttraderapi_se.dll": b"fake native library; never load\n",
    }
    distributions = []
    for index, (name, facts) in enumerate(_DIST.items(), start=1):
        version, wheel, dist_info, import_root, tag = facts
        files = {
            path: raw
            for path, raw in content.items()
            if path == import_root + "/__init__.py" or path.startswith(import_root + "/")
        }
        if name == "PyYAML":
            files.update(
                {path: raw for path, raw in content.items() if path == "_yaml/__init__.py"}
            )
        if name == "bt_api_ctp":
            files = {path: raw for path, raw in content.items() if path.startswith("bt_api_ctp/")}
        metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n".encode()
        wheel_metadata = (
            "Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: "
            + ("true" if tag == "py3-none-any" else "false")
            + f"\nTag: {tag}\n"
        ).encode()
        wheel_sha = str(index) * 64
        url_wheel = wheel.replace("+", "%2B")
        direct_url = _canonical(
            {
                "archive_info": {
                    "hash": "sha256=" + wheel_sha,
                    "hashes": {"sha256": wheel_sha},
                },
                "url": "file:///D:/wheelhouse/" + url_wheel,
            }
        )
        info_files = {
            dist_info + "/METADATA": metadata,
            dist_info + "/WHEEL": wheel_metadata,
            dist_info + "/direct_url.json": direct_url,
            dist_info + "/INSTALLER": b"pip\n",
        }
        files.update(info_files)
        rows = []
        for path, raw in sorted(files.items()):
            rows.append((path, _wheel_record_digest(raw), str(len(raw))))
        record_path = dist_info + "/RECORD"
        rows.append((record_path, "", ""))
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerows(sorted(rows))
        content.update(files)
        content[record_path] = output.getvalue().encode()
        distributions.append(
            {
                "name": name,
                "version": version,
                "wheel": wheel,
                "wheel_sha256": wheel_sha,
                "dist_info": dist_info,
                "record": record_path,
                "metadata": dist_info + "/METADATA",
                "wheel_metadata": dist_info + "/WHEEL",
                "direct_url": dist_info + "/direct_url.json",
            }
        )

    file_rows = []
    for path, raw in sorted(content.items()):
        suffix = path.rsplit(".", 1)[-1].lower()
        if path == "_yaml/__init__.py" or path.startswith(("yaml/", "bt_api_base/", "bt_api_ctp/")):
            kind = (
                "source" if suffix == "py" else "extension" if suffix in {"pyd", "dll"} else "data"
            )
        else:
            kind = "metadata"
        file_rows.append(
            {
                "path": path,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
                "kind": kind,
            }
        )
    directories = set()
    for path in content:
        parts = path.split("/")[:-1]
        directories.update("/".join(parts[:index]) for index in range(1, len(parts) + 1))
    manifest = {
        "schema": seal_module.MANIFEST_SCHEMA,
        "python": {"implementation": "CPython", "version": "3.11.5", "platform": "win_amd64"},
        "distributions": distributions,
        "files": file_rows,
        "directories": sorted(directories),
        "dll_directories": ["bt_api_ctp/ctp", "yaml"],
    }
    raw_manifest = _canonical(manifest)
    return raw_manifest, hashlib.sha256(raw_manifest).hexdigest(), manifest, content


class _Lease:
    def __init__(self, content, directories=None):
        self.content = dict(content)
        self.extra = {}
        self.closed = 0
        self.verify_count = 0
        self.directories = directories

    def read_file(self, path, *, max_bytes):
        raw = self.content.get(path)
        if raw is None or len(raw) > max_bytes:
            raise OSError("not retained")
        return raw

    def list_directory(self, path):
        children = set()
        prefix = path + "/" if path else ""
        for item in (*self.content, *self.extra):
            if item.startswith(prefix):
                tail = item[len(prefix) :]
                children.add(tail.split("/", 1)[0])
        return tuple(sorted(children))

    def verify_current(self):
        if self.closed:
            raise OSError("closed")
        self.verify_count += 1

    def close(self):
        self.closed += 1


def _seal_fixture(*, content=None, manifest_raw=None, expected=None, lease=None):
    raw, digest, _manifest, default_content = _fixture()
    raw = raw if manifest_raw is None else manifest_raw
    digest = digest if expected is None else expected
    lease = _Lease(default_content if content is None else content) if lease is None else lease
    calls = []

    def retain(files, directories):
        calls.append((files, directories))
        return lease

    seal = seal_module.seal_worker_dependencies(
        raw,
        expected_manifest_sha256=digest,
        python_executable=r"C:\worker\venv\Scripts\python.exe",
        retain_paths=retain,
    )
    return seal, lease, calls, digest, raw


def test_default_unset_manifest_pin_rejects_before_manifest_read_or_retention():
    calls = []
    with pytest.raises(seal_module.DependencySealError, match="pin_unset"):
        seal_module.read_fixed_worker_dependency_manifest(
            lambda: calls.append("read") or b"{}", expected_sha256="0" * 64
        )
    assert calls == []


def test_canonical_manifest_verifies_records_and_exposes_only_fixed_dependency_roots():
    seal, lease, calls, digest, _raw = _seal_fixture()
    assert seal.dependency_root == r"C:\worker\venv\Lib\site-packages"
    assert seal.manifest_sha256 == digest
    assert seal.dll_directories == (
        r"C:\worker\venv\Lib\site-packages\bt_api_ctp\ctp",
        r"C:\worker\venv\Lib\site-packages\yaml",
    )
    assert calls and lease.verify_count == 1
    assert tuple(seal_module.TOP_LEVEL_ROOTS) == ("yaml", "bt_api_base", "bt_api_ctp")
    assert "_yaml/__init__.py" in seal._files
    assert seal.native_file_paths == (
        "bt_api_ctp/ctp/_ctp.cp311-win_amd64.pyd",
        "bt_api_ctp/ctp/thosttraderapi_se.dll",
        "yaml/_yaml.cp311-win_amd64.pyd",
    )
    assert seal.read_file("bt_api_ctp/ctp/_ctp.cp311-win_amd64.pyd").startswith(
        b"fake native image"
    )
    with pytest.raises(seal_module.DependencySealError, match="native_file_unlisted"):
        seal.read_file("bt_api_ctp/__init__.py")
    seal.verify_current()
    assert lease.verify_count == 3
    seal.close()
    seal.close()
    assert lease.closed == 1


@pytest.mark.parametrize(
    "mutation,expected_error",
    [
        ("digest", "digest_mismatch"),
        ("noncanonical", "not_canonical"),
        ("duplicate", "duplicate_key"),
        ("extra_manifest_path", "unapproved_namespace"),
        ("pycache", "bytecode_forbidden"),
        ("bad_python", "python_mismatch"),
        ("bad_wheel_hash", "wheel_digest_mismatch"),
    ],
)
def test_manifest_rejects_untrusted_or_unlisted_inputs(mutation, expected_error):
    raw, digest, manifest, content = _fixture()
    lease = _Lease(content)
    if mutation == "digest":
        digest = "f" * 64
    elif mutation == "noncanonical":
        raw = json.dumps(manifest, indent=2).encode()
        digest = hashlib.sha256(raw).hexdigest()
    elif mutation == "duplicate":
        raw = raw[:-1] + b',"schema":"again"}'
        digest = hashlib.sha256(raw).hexdigest()
    elif mutation == "extra_manifest_path":
        manifest["files"].append(
            {"path": "requests/__init__.py", "sha256": "a" * 64, "size": 1, "kind": "source"}
        )
        raw = _canonical(manifest)
        digest = hashlib.sha256(raw).hexdigest()
    elif mutation == "pycache":
        lease.extra["bt_api_ctp/__pycache__/rogue.pyc"] = b"x"
    elif mutation == "bad_python":
        manifest["python"]["version"] = "3.12.0"
        raw = _canonical(manifest)
        digest = hashlib.sha256(raw).hexdigest()
    elif mutation == "bad_wheel_hash":
        next(item for item in manifest["distributions"] if item["name"] == "bt_api_ctp")[
            "wheel_sha256"
        ] = ("f" * 64)
        raw = _canonical(manifest)
        digest = hashlib.sha256(raw).hexdigest()
    with pytest.raises(seal_module.DependencySealError, match=expected_error):
        seal_module.seal_worker_dependencies(
            raw,
            expected_manifest_sha256=digest,
            python_executable=r"C:\worker\venv\Scripts\python.exe",
            retain_paths=lambda _files, _dirs: lease,
        )


def test_directory_inventory_rejects_unlisted_file_even_if_manifest_is_valid():
    seal, lease, _calls, _digest, _raw = _seal_fixture()
    lease.extra["yaml/rogue.py"] = b"MALICIOUS = True\n"
    with pytest.raises(seal_module.DependencySealError, match="directory_inventory_mismatch"):
        seal.verify_current()


@pytest.mark.parametrize(
    "change,expected_error",
    [
        ("missing", "dependency_directory_inventory_mismatch"),
        ("altered", "dependency_file_digest_mismatch"),
    ],
)
def test_retained_package_files_must_match_manifest_bytes(change, expected_error):
    raw, digest, _manifest, content = _fixture()
    path = "bt_api_base/__init__.py"
    if change == "missing":
        del content[path]
    else:
        content[path] = b"X" + content[path][1:]
    lease = _Lease(content)
    with pytest.raises(seal_module.DependencySealError, match=expected_error):
        seal_module.seal_worker_dependencies(
            raw,
            expected_manifest_sha256=digest,
            python_executable=r"C:\worker\venv\Scripts\python.exe",
            retain_paths=lambda _files, _dirs: lease,
        )
    assert lease.closed == 1


def test_source_finder_reads_only_retained_verified_sources_and_never_adds_paths():
    seal, _lease, _calls, _digest, _raw = _seal_fixture()
    finder = seal_module.WorkerDependencyFinder(seal)
    before = tuple(sys.path)
    spec = finder.find_spec("yaml")
    module = importlib.util.module_from_spec(spec)
    previous_yaml = sys.modules.get("yaml", _MISSING_MODULE)
    sys.modules["yaml"] = module
    try:
        spec.loader.exec_module(module)
        assert module.VALUE == "yaml"
        assert finder.owns_module("yaml", module)
        with pytest.raises(ModuleNotFoundError, match="not_allowlisted"):
            finder.find_spec("yaml.attacker")
        assert finder.find_spec("urllib3") is None
        assert tuple(sys.path) == before
    finally:
        if previous_yaml is _MISSING_MODULE:
            sys.modules.pop("yaml", None)
        else:
            sys.modules["yaml"] = previous_yaml
        seal.close()


def test_native_extension_spec_is_manifest_bound_but_test_does_not_load_it():
    seal, _lease, _calls, _digest, _raw = _seal_fixture()
    finder = seal_module.WorkerDependencyFinder(seal)
    native_names = ("bt_api_ctp.ctp._ctp", "yaml._yaml")
    previous_modules = {
        name: sys.modules.get(name, _MISSING_MODULE) for name in native_names
    }
    for name in native_names:
        sys.modules.pop(name, None)
    try:
        # Establish an empty pre-state so this checks that spec discovery does
        # not import either native extension even when earlier tests used YAML.
        assert all(name not in sys.modules for name in native_names)
        spec = finder.find_spec("bt_api_ctp.ctp._ctp")
        assert (
            type(spec.loader)
            is __import__("importlib.machinery", fromlist=["ExtensionFileLoader"])
            .ExtensionFileLoader
        )
        assert spec.origin.endswith(r"bt_api_ctp\ctp\_ctp.cp311-win_amd64.pyd")
        assert all(name not in sys.modules for name in native_names)
        yaml_spec = finder.find_spec("yaml._yaml")
        assert yaml_spec.origin.endswith(r"yaml\_yaml.cp311-win_amd64.pyd")
        assert all(name not in sys.modules for name in native_names)
        # PyYAML's compatibility shim is covered by its wheel RECORD but is not
        # one of the code-owned import roots delegated by this finder.
        assert finder.find_spec("_yaml") is None
        assert finder.owns_module("bt_api_ctp.ctp._ctp", types.SimpleNamespace()) is False
    finally:
        for name, previous in previous_modules.items():
            if previous is _MISSING_MODULE:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        seal.close()

    assert all(
        sys.modules.get(name, _MISSING_MODULE) is previous
        for name, previous in previous_modules.items()
    )


def test_installed_finder_delegates_without_reordering_meta_path_and_close_is_retryable(
    monkeypatch,
):
    seal, lease, _calls, _digest, _raw = _seal_fixture()

    class _SourceFinder:
        def __init__(self):
            self.delegated = None
            self.detach_fail = True

        def attach_dependency_finder(self, finder):
            assert self.delegated is None
            self.delegated = finder

        def detach_dependency_finder(self, finder):
            if self.detach_fail:
                raise RuntimeError("temporary")
            assert self.delegated is finder
            self.delegated = None

    class _DllHandle:
        closed = 0

        def close(self):
            self.closed += 1

    source = _SourceFinder()
    original_meta_path = sys.meta_path
    dll_handles = []
    try:
        sys.meta_path = [source]

        def add_dll_directory(path):
            handle = _DllHandle()
            dll_handles.append((path, handle))
            return handle

        monkeypatch.setattr(seal_module.os, "add_dll_directory", add_dll_directory, raising=False)
        finder = seal_module.install_worker_dependency_finder(seal)
        assert source.delegated is finder
        assert sys.meta_path == [source]
        with pytest.raises(seal_module.DependencySealError, match="finder_close_failed"):
            seal.close()
        source.detach_fail = False
        seal.close()
        seal.close()
        assert source.delegated is None
        assert lease.closed == 1
        assert len(dll_handles) == 2
        assert all(handle.closed == 1 for _path, handle in dll_handles)
    finally:
        sys.meta_path = original_meta_path


def test_read_fixed_manifest_uses_no_path_argument_and_checks_protected_bytes():
    raw, digest, _manifest, _content = _fixture()
    calls = []
    assert (
        seal_module.read_fixed_worker_dependency_manifest(
            lambda: calls.append(1) or raw, expected_sha256=digest
        )
        == raw
    )
    assert calls == [1]
    with pytest.raises(seal_module.DependencySealError, match="digest_mismatch"):
        seal_module.read_fixed_worker_dependency_manifest(lambda: raw, expected_sha256="f" * 64)


def test_fixed_anchor_adapter_rejects_unset_pin_before_path_retention():
    calls = []

    class _Anchor:
        worker_dependency_manifest_sha256 = "0" * 64
        dependency_root = r"C:\worker\venv\Lib\site-packages"
        python_executable = r"C:\worker\venv\Scripts\python.exe"

        def read_worker_dependency_manifest(self):
            calls.append("read")
            return b"{}"

        def retain_dependency_paths(self, _files, _directories):
            calls.append("retain")

    with pytest.raises(seal_module.DependencySealError, match="pin_unset"):
        seal_module.seal_fixed_worker_dependencies(_Anchor())
    assert calls == []


def test_fixed_anchor_adapter_uses_only_its_manifest_root_and_retained_path_api():
    raw, digest, _manifest, content = _fixture()
    lease = _Lease(content)
    calls = []

    class _Anchor:
        worker_dependency_manifest_sha256 = digest
        dependency_root = r"C:\worker\venv\Lib\site-packages"
        python_executable = r"C:\worker\venv\Scripts\python.exe"

        def read_worker_dependency_manifest(self):
            calls.append("read-fixed-manifest")
            return raw

        def retain_dependency_paths(self, files, directories):
            calls.append((files, directories))
            return lease

    seal = seal_module.seal_fixed_worker_dependencies(_Anchor())
    assert calls[0] == "read-fixed-manifest"
    assert calls[1][0] == tuple(sorted(content))
    assert calls[1][1] == ("", *tuple(_fixture()[2]["directories"]))
    assert seal.manifest_sha256 == digest
    seal.close()
    assert lease.closed == 1
