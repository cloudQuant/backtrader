"""Fake retained-tree tests for the fixed Windows worker runtime closure."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
import uuid
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module():
    name = "_i13_i15_runtime_closure_" + uuid.uuid4().hex
    path = REPO_ROOT / "scripts" / "ctp_i13_i15_runtime_closure.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


closure = _load_module()


def _minimal_pe(imports=(), delay_imports=()):
    """Build a tiny PE32+ test image with normal and/or delay import rows."""
    image = bytearray(0x600)
    image[:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, 0x80)
    image[0x80:0x84] = b"PE\0\0"
    coff = 0x84
    struct.pack_into("<HHIIIHH", image, coff, 0x8664, 1, 0, 0, 0, 240, 0)
    optional = coff + 20
    struct.pack_into("<H", image, optional, 0x20B)
    struct.pack_into("<Q", image, optional + 24, 0x140000000)
    struct.pack_into("<I", image, optional + 60, 0x200)
    struct.pack_into("<I", image, optional + 108, 16)
    section = optional + 240
    struct.pack_into("<IIII", image, section + 8, 0x400, 0x1000, 0x400, 0x200)
    if imports:
        descriptor_size = 20
        directory_size = (len(imports) + 1) * descriptor_size
        struct.pack_into("<II", image, optional + 112 + 8, 0x1000, directory_size)
        cursor = 0x200
        name_cursor = 0x280
        thunk_cursor = 0x380
        for index, name in enumerate(imports):
            encoded = name.encode("ascii") + b"\0"
            struct.pack_into(
                "<IIIII",
                image,
                cursor + index * descriptor_size,
                0x1100 + index * 8,
                0,
                0,
                0x1000 + (name_cursor - 0x200),
                0x1180 + index * 8,
            )
            image[name_cursor : name_cursor + len(encoded)] = encoded
            name_cursor += len(encoded)
            struct.pack_into("<Q", image, thunk_cursor + index * 8, 0)
    if delay_imports:
        descriptor_size = 32
        directory_size = (len(delay_imports) + 1) * descriptor_size
        struct.pack_into("<II", image, optional + 112 + 13 * 8, 0x1040, directory_size)
        cursor = 0x240
        name_cursor = 0x300
        for index, name in enumerate(delay_imports):
            encoded = name.encode("ascii") + b"\0"
            values = (1, 0x1000 + (name_cursor - 0x200), 0, 0, 0, 0, 0, 0)
            struct.pack_into("<8I", image, cursor + index * descriptor_size, *values)
            image[name_cursor : name_cursor + len(encoded)] = encoded
            name_cursor += len(encoded)
    return bytes(image)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


class _FakeLease:
    def __init__(self, files, directories, *, dependency_child=False, extra=None):
        self.files = dict(files)
        self.directories = tuple(directories)
        self.extra = extra or {}
        self.dependency_child = dependency_child
        self.closed = False
        self.events = []

    def read_file(self, relative_path, *, max_bytes):
        if self.closed or relative_path not in self.files:
            raise OSError("not retained")
        self.events.append(("read", relative_path))
        result = self.files[relative_path]
        if len(result) > max_bytes:
            raise OSError("too large")
        return result

    def list_directory(self, relative_directory):
        if self.closed:
            raise OSError("closed")
        self.events.append(("list", relative_directory))
        names = set(self.extra.get(relative_directory, ()))
        for directory in self.directories:
            parent, _, leaf = directory.rpartition("/")
            if parent == relative_directory:
                names.add(leaf)
        for path in self.files:
            parent, _, leaf = path.rpartition("/")
            if parent == relative_directory:
                names.add(leaf)
        if relative_directory == "Lib" and self.dependency_child:
            # The dependency seal owns this separately retained subtree.
            names.add("site-packages")
        return tuple(sorted(names))

    def verify_current(self):
        if self.closed:
            raise OSError("closed")
        self.events.append(("verify", None))

    def close(self):
        self.closed = True


class _FakeDependencySeal:
    manifest_sha256 = "a" * 64
    dependency_root = r"C:\pyvenv\Lib\site-packages"
    native_file_paths = ()
    dll_directories = ()

    def verify_current(self):
        return None

    def read_file(self, _relative_path):
        raise AssertionError("empty dependency fixture has no native files")


def _fixture(*, extra_base_directories=(), extra_base_files=None, imports=None):
    pe = _minimal_pe()
    source = {
        "Lib/asyncio/__init__.py": b"from . import base_events\n",
        "Lib/asyncio/base_events.py": b"class BaseEventLoop: pass\n",
        "Lib/encodings/__init__.py": b"# encodings\n",
        "Lib/logging/__init__.py": b"from . import handlers\n",
        "Lib/logging/handlers.py": b"class NullHandler: pass\n",
        "Lib/socket.py": b"from _socket import *\n",
        "DLLs/_ctypes.pyd": pe,
        "DLLs/_socket.pyd": pe,
        "DLLs/_ssl.pyd": pe,
        "python.exe": pe,
        "python311.dll": pe,
    }
    if extra_base_files:
        source.update(extra_base_files)
    pyvenv = b"home = C:\\pyhome\ninclude-system-site-packages = false\nversion = 3.11.5\n"
    venv = {
        "Scripts/python.exe": pe,
        "pyvenv.cfg": pyvenv,
    }
    base_dirs = {
        "DLLs",
        "Lib",
        "Lib/asyncio",
        "Lib/encodings",
        "Lib/logging",
        *extra_base_directories,
    }
    venv_dirs = {"Lib", "Scripts"}

    def file_rows(files):
        return [
            {"path": path, "sha256": _sha(raw), "size": len(raw)}
            for path, raw in sorted(files.items())
        ]

    native_rows = []
    all_pe = {"base": source, "venv": venv}
    for root_name, files in all_pe.items():
        for path, raw in files.items():
            if path.casefold().endswith((".exe", ".dll", ".pyd")):
                if imports and (root_name, path) in imports:
                    normal, delay = imports[(root_name, path)]
                else:
                    normal, delay = (), ()
                native_rows.append(
                    {"root": root_name, "path": path, "normal": list(normal), "delay": list(delay)}
                )
    native_rows.sort(key=lambda row: (row["root"], row["path"].casefold()))
    manifest = {
        "schema": "ctp_i13_i15_runtime_closure.v2",
        "python_version": "3.11.5",
        "architecture": "AMD64",
        "python": {
            "base_executable": "python.exe",
            "python_dll": "python311.dll",
            "venv_executable": "Scripts/python.exe",
            "pyvenv_cfg": "pyvenv.cfg",
            "venv_site_packages": "Lib/site-packages",
            "python311_zip": {"present": False, "path": None, "sha256": None},
            "pycache_prefix": {"relative_path": "disabled-bytecode-cache", "present": False},
            "pth_files": [],
        },
        "base": {
            "files": file_rows(source),
            "directories": sorted(base_dirs),
        },
        "venv": {
            "files": file_rows(venv),
            "directories": sorted(venv_dirs),
        },
        "dependency_manifest_sha256": _FakeDependencySeal.manifest_sha256,
        "native_imports": native_rows,
        "system32_dll_names": [],
    }
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    base_lease = _FakeLease(source, sorted(base_dirs))
    venv_lease = _FakeLease(venv, sorted(venv_dirs), dependency_child=True)
    retained = []

    def retain(root_kind, relative_files, relative_directories):
        assert tuple(relative_directories)[0] == ""
        lease = base_lease if root_kind == "base" else venv_lease
        assert set(relative_files) == set(lease.files)
        retained.append(lease)
        return lease

    descriptor = {
        "python_executable": r"C:\pyvenv\Scripts\python.exe",
        "python_sha256": _sha(venv["Scripts/python.exe"]),
        "python_version": "3.11.5",
        "python_architecture": "AMD64",
        "python_home": r"C:\pyhome",
        "venv_root": r"C:\pyvenv",
        "pyvenv_cfg_sha256": _sha(pyvenv),
        "stdlib_paths": [
            r"C:\pyhome\python311.zip",
            r"C:\pyhome\DLLs",
            r"C:\pyhome\Lib",
            r"C:\pyhome",
        ],
    }
    process = {
        "sys_executable": r"C:\pyvenv\Scripts\python.exe",
        "version_info": (3, 11, 5),
        "architecture": "AMD64",
        "sys_path": tuple(descriptor["stdlib_paths"]),
        "prefix": r"C:\pyhome",
        "base_prefix": r"C:\pyhome",
        "sys_pycache_prefix": r"C:\pyhome\disabled-bytecode-cache",
        "flags": {"isolated": 1, "no_site": 1, "dont_write_bytecode": 1},
    }
    return raw, descriptor, process, _FakeDependencySeal(), retain, retained, manifest


def _seal(fixture):
    raw, descriptor, process, dependency, retain, retained, _manifest = fixture
    seal = closure.seal_runtime_closure(
        raw,
        expected_manifest_sha256=_sha(raw),
        descriptor_facts=descriptor,
        process_facts=process,
        dependency_seal=dependency,
        retain_paths=retain,
    )
    return seal, retained


def test_runtime_seal_exposes_exact_stdlib_source_and_extension_entries():
    seal, retained = _seal(_fixture())
    base_events = retained[0].events
    last_base_listing = max(index for index, event in enumerate(base_events) if event[0] == "list")
    first_base_read = min(index for index, event in enumerate(base_events) if event[0] == "read")
    assert any(
        event[0] == "verify" for event in base_events[last_base_listing + 1 : first_base_read]
    )

    asyncio_entry = seal.stdlib_entry("asyncio")
    socket_entry = seal.stdlib_entry("socket")
    native_entry = seal.stdlib_entry("_socket")
    assert asyncio_entry is not None
    assert asyncio_entry.kind == "source" and asyncio_entry.is_package is True
    assert asyncio_entry.origin == r"C:\pyhome\Lib\asyncio\__init__.py"
    assert seal.read_stdlib_source("asyncio") == b"from . import base_events\n"
    assert socket_entry is not None and socket_entry.kind == "source"
    assert native_entry is not None and native_entry.kind == "extension"
    assert native_entry.origin == r"C:\pyhome\DLLs\_socket.pyd"
    assert seal.verify_stdlib_entry("_ssl") == seal.stdlib_entry("_ssl")
    assert seal.stdlib_entry("ambient_package") is None
    with pytest.raises(closure.RuntimeClosureError, match="runtime_stdlib_source_not_python"):
        seal.read_stdlib_source("_ctypes")
    seal.close()


def test_runtime_seal_rechecks_module_hash_through_retained_lease():
    seal, retained = _seal(_fixture())
    retained[0].files["DLLs/_socket.pyd"] = b"changed"
    with pytest.raises(closure.RuntimeClosureError, match="runtime_file_size_mismatch"):
        seal.verify_stdlib_entry("_socket")
    seal.close()


def test_pycache_prefix_must_match_derived_fixed_absent_leaf():
    fixture = _fixture()
    fixture[2]["sys_pycache_prefix"] = r"C:\Temp\cache"
    with pytest.raises(closure.RuntimeClosureError, match="runtime_process_binding_mismatch"):
        _seal(fixture)


def test_pycache_prefix_cannot_be_listed_or_present_in_root_manifest():
    raw, descriptor, process, dependency, retain, _retained, manifest = _fixture(
        extra_base_directories=("disabled-bytecode-cache",)
    )
    with pytest.raises(closure.RuntimeClosureError, match="runtime_pycache_prefix_present"):
        closure.seal_runtime_closure(
            raw,
            expected_manifest_sha256=_sha(raw),
            descriptor_facts=descriptor,
            process_facts=process,
            dependency_seal=dependency,
            retain_paths=retain,
        )


def test_pycache_prefix_absence_is_case_insensitive_in_manifest_and_retained_listing():
    fixture = _fixture(extra_base_directories=("Disabled-Bytecode-Cache",))
    with pytest.raises(closure.RuntimeClosureError, match="runtime_pycache_prefix_present"):
        _seal(fixture)

    fixture = _fixture()
    raw, descriptor, process, dependency, retain, _retained, _manifest = fixture
    base_files = tuple(row["path"] for row in _manifest["base"]["files"])
    base_dirs = ("", *_manifest["base"]["directories"])
    lease = retain("base", base_files, base_dirs)
    lease.extra[""] = ("Disabled-Bytecode-Cache",)
    with pytest.raises(closure.RuntimeClosureError, match="runtime_directory_inventory_mismatch"):
        closure.seal_runtime_closure(
            raw,
            expected_manifest_sha256=_sha(raw),
            descriptor_facts=descriptor,
            process_facts=process,
            dependency_seal=dependency,
            retain_paths=retain,
        )


def test_present_python311_zip_is_explicitly_rejected_as_unsupported():
    fixture = _fixture()
    raw, descriptor, process, dependency, retain, _retained, manifest = fixture
    manifest["base"]["files"].append({"path": "python311.zip", "sha256": _sha(b"zip"), "size": 3})
    manifest["base"]["files"].sort(key=lambda item: item["path"])
    manifest["python"]["python311_zip"] = {
        "present": True,
        "path": "python311.zip",
        "sha256": _sha(b"zip"),
    }
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(closure.RuntimeClosureError, match="runtime_python_zip_present_unsupported"):
        closure.seal_runtime_closure(
            raw,
            expected_manifest_sha256=_sha(raw),
            descriptor_facts=descriptor,
            process_facts=process,
            dependency_seal=dependency,
            retain_paths=retain,
        )


def test_pe_parser_captures_normal_import_names():
    assert closure._pe_imports(_minimal_pe(("KERNEL32.dll",))) == (("kernel32.dll",), ())


def test_pe_parser_captures_delay_import_names():
    assert closure._pe_imports(_minimal_pe(delay_imports=("USER32.dll",))) == (
        (),
        ("user32.dll",),
    )


def test_local_pe_cannot_shadow_manifest_system32_import():
    raw = _minimal_pe(("kernel32.dll",))
    with pytest.raises(closure.RuntimeClosureError, match="runtime_system32_import_shadowed"):
        closure._validate_import_graph(
            {
                ("base", "python311.dll"): (("kernel32.dll",), ()),
                ("base", "kernel32.dll"): ((), ()),
            },
            ("kernel32.dll",),
            {"base": {"python311.dll": raw, "kernel32.dll": _minimal_pe()}},
            _FakeDependencySeal(),
        )


def test_fixed_runtime_pin_is_zero_by_default_and_rejects_before_anchor_reads():
    with pytest.raises(closure.RuntimeClosureError, match="runtime_manifest_code_pin_invalid"):
        closure.seal_fixed_runtime_closure(object())


@pytest.mark.parametrize(
    "override",
    [
        {"process_facts": {}},
        {"dependency_seal": _FakeDependencySeal()},
    ],
)
def test_fixed_runtime_adapter_rejects_caller_fact_and_lease_overrides(override):
    with pytest.raises(TypeError):
        closure.seal_fixed_runtime_closure(object(), **override)
