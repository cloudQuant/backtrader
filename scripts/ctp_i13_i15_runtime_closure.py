"""Strict, offline validation for the fixed CPython 3.11.5 worker closure.

This parser is not a deployment authority.  Its manifest digest must come
from the protected guardian descriptor, and its path reads must be provided
by retained-handle leases rooted at the verified Python home and venv.  It
checks the exact interpreter facts, file and directory inventories, Python
path, and static PE normal/delay import graph.  It does not prove the absence
of dynamic ``LoadLibrary`` behavior or replace Windows code-integrity policy.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import ntpath
import os
import sys
import threading
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional


RUNTIME_MANIFEST_SHA256 = "0" * 64
_SCHEMA = "ctp_i13_i15_runtime_closure.v2"
_PYTHON_VERSION = "3.11.5"
_PYTHON_ARCHITECTURE = "AMD64"
_MAX_MANIFEST_BYTES = 32 * 1024 * 1024
_MAX_FILES = 100_000
_MAX_FILE_BYTES = 256 * 1024 * 1024
_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
_MAX_NATIVE_BYTES = 1024 * 1024 * 1024
_MAX_PE_IMPORTS = 4096
_MAX_DLL_NAME_BYTES = 260
_ZERO_SHA256 = "0" * 64
_SHA256_CHARS = frozenset("0123456789abcdef")
_DEPENDENCY_SUBTREE = "Lib/site-packages"
_PE_SUFFIXES = (".exe", ".dll", ".pyd")


class RuntimeClosureError(ValueError):
    """A redacted fail-closed runtime closure rejection."""


@dataclass(frozen=True)
class _File:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class _Root:
    kind: str
    path: str
    files: Mapping[str, _File]
    directories: tuple[str, ...]
    lease: object


@dataclass(frozen=True)
class RuntimeStdlibEntry:
    """One exact source or extension module in the sealed stdlib search path."""

    fullname: str
    origin: str
    kind: str
    is_package: bool
    root_kind: str
    relative_path: str
    sha256: str
    size: int


def _fail(code: str):
    raise RuntimeClosureError(code)


def _is_sha256(value: object, *, nonzero: bool = True) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in _SHA256_CHARS for character in value)
        and (not nonzero or value != _ZERO_SHA256)
    )


def _expect_keys(value: object, keys: set[str], code: str) -> None:
    if not isinstance(value, Mapping) or set(value) != keys:
        _fail(code)


def _pairs_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if type(key) is not str or key in result:
            _fail("runtime_manifest_duplicate_or_invalid_key")
        result[key] = value
    return result


def _safe_relative(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or "\\" in value
        or ":" in value
        or value.startswith("/")
        or value.endswith("/")
        or any(ord(character) < 0x20 for character in value)
    ):
        _fail("runtime_manifest_path_invalid")
    parts = value.split("/")
    reserved = {"con", "prn", "aux", "nul"} | {
        f"{prefix}{index}" for prefix in ("com", "lpt") for index in range(1, 10)
    }
    if any(
        part in {"", ".", ".."}
        or part.endswith((".", " "))
        or any(character in part for character in '<>"|?*')
        or part.split(".", 1)[0].casefold() in reserved
        for part in parts
    ):
        _fail("runtime_manifest_path_invalid")
    if ntpath.isabs(value):
        _fail("runtime_manifest_path_invalid")
    return value


def _canonical_absolute(value: object, code: str) -> str:
    if type(value) is not str or not ntpath.isabs(value):
        _fail(code)
    normalized = ntpath.normpath(value)
    drive, tail = ntpath.splitdrive(normalized)
    if not drive or not tail.startswith("\\") or normalized != value:
        _fail(code)
    return normalized


def _path_key(value: str) -> str:
    return ntpath.normcase(ntpath.normpath(value))


def _path_is_beneath(path: str, root: str) -> bool:
    try:
        return ntpath.commonpath((ntpath.normcase(path), ntpath.normcase(root))) == ntpath.normcase(
            root
        )
    except (TypeError, ValueError):
        return False


def _decode_manifest(raw: object, expected_sha256: object) -> tuple[dict, str]:
    if not _is_sha256(expected_sha256):
        _fail("runtime_manifest_pin_unset_or_invalid")
    if type(raw) is not bytes or not raw or len(raw) > _MAX_MANIFEST_BYTES:
        _fail("runtime_manifest_size_invalid")
    actual = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual, expected_sha256):
        _fail("runtime_manifest_digest_mismatch")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs_no_duplicates)
    except RuntimeClosureError:
        raise
    except (UnicodeError, TypeError, ValueError):
        _fail("runtime_manifest_invalid")
    if type(value) is not dict:
        _fail("runtime_manifest_invalid")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    if raw != canonical:
        _fail("runtime_manifest_not_canonical")
    return value, actual


def _parse_root(kind: str, raw: object, *, dependency_subtree: Optional[str]) -> tuple[dict, dict]:
    _expect_keys(raw, {"files", "directories"}, "runtime_manifest_root_invalid")
    raw_files = raw["files"]
    raw_directories = raw["directories"]
    if type(raw_files) is not list or not raw_files or len(raw_files) > _MAX_FILES:
        _fail("runtime_manifest_files_invalid")
    files = {}
    total_size = 0
    for item in raw_files:
        _expect_keys(item, {"path", "sha256", "size"}, "runtime_manifest_file_invalid")
        path = _safe_relative(item["path"])
        if path in files or not _is_sha256(item["sha256"]):
            _fail("runtime_manifest_file_invalid")
        size = item["size"]
        if type(size) is not int or not 0 <= size <= _MAX_FILE_BYTES:
            _fail("runtime_manifest_file_size_invalid")
        if path.casefold().endswith((".pth", "._pth")):
            _fail("runtime_unpinned_pth_forbidden")
        if dependency_subtree and (
            path == dependency_subtree or path.startswith(dependency_subtree + "/")
        ):
            _fail("runtime_dependency_subtree_duplicated")
        total_size += size
        if total_size > _MAX_TOTAL_BYTES:
            _fail("runtime_manifest_total_size_invalid")
        files[path] = _File(path, item["sha256"], size)
    if tuple(files) != tuple(sorted(files)):
        _fail("runtime_manifest_files_not_sorted")
    folded_files = [path.casefold() for path in files]
    if len(folded_files) != len(set(folded_files)):
        _fail("runtime_manifest_case_collision")

    if type(raw_directories) is not list or len(raw_directories) > _MAX_FILES:
        _fail("runtime_manifest_directories_invalid")
    directories = tuple(_safe_relative(path) for path in raw_directories)
    if directories != tuple(sorted(set(directories))):
        _fail("runtime_manifest_directories_not_sorted")
    folded_dirs = [path.casefold() for path in directories]
    if len(folded_dirs) != len(set(folded_dirs)):
        _fail("runtime_manifest_case_collision")

    expected_dirs = set(directories)
    for directory in directories:
        parents = directory.split("/")[:-1]
        for index in range(1, len(parents) + 1):
            parent = "/".join(parents[:index])
            if dependency_subtree and (
                parent == dependency_subtree or parent.startswith(dependency_subtree + "/")
            ):
                continue
            if parent not in expected_dirs:
                _fail("runtime_manifest_directory_inventory_mismatch")
    for path in files:
        parents = path.split("/")[:-1]
        for index in range(1, len(parents) + 1):
            parent = "/".join(parents[:index])
            if dependency_subtree and (
                parent == dependency_subtree or parent.startswith(dependency_subtree + "/")
            ):
                continue
            if parent not in expected_dirs:
                _fail("runtime_manifest_directory_inventory_mismatch")
    if dependency_subtree:
        parent = dependency_subtree.rpartition("/")[0]
        if parent:
            if parent not in expected_dirs:
                _fail("runtime_manifest_directory_inventory_mismatch")
        if dependency_subtree in expected_dirs or any(
            path.startswith(dependency_subtree + "/") for path in expected_dirs
        ):
            _fail("runtime_dependency_subtree_duplicated")
    if set(files) & expected_dirs:
        _fail("runtime_manifest_path_kind_collision")
    all_folded = [path.casefold() for path in set(files) | expected_dirs]
    if len(all_folded) != len(set(all_folded)):
        _fail("runtime_manifest_case_collision")
    return files, {"directories": directories, "dependency_subtree": dependency_subtree}


def _parse_descriptor_facts(value: object) -> dict:
    keys = {
        "python_executable",
        "python_sha256",
        "python_version",
        "python_architecture",
        "python_home",
        "venv_root",
        "pyvenv_cfg_sha256",
        "stdlib_paths",
    }
    _expect_keys(value, keys, "runtime_descriptor_facts_invalid")
    executable = _canonical_absolute(
        value["python_executable"], "runtime_python_executable_invalid"
    )
    python_home = _canonical_absolute(value["python_home"], "runtime_python_home_invalid")
    venv_root = _canonical_absolute(value["venv_root"], "runtime_venv_root_invalid")
    if (
        ntpath.normcase(executable)
        != ntpath.normcase(ntpath.join(venv_root, "Scripts", "python.exe"))
        or value["python_version"] != _PYTHON_VERSION
        or value["python_architecture"] != _PYTHON_ARCHITECTURE
        or not _is_sha256(value["python_sha256"])
        or not _is_sha256(value["pyvenv_cfg_sha256"])
    ):
        _fail("runtime_descriptor_binding_invalid")
    raw_paths = value["stdlib_paths"]
    if type(raw_paths) not in (list, tuple) or not raw_paths:
        _fail("runtime_descriptor_sys_path_invalid")
    paths = tuple(
        _canonical_absolute(path, "runtime_descriptor_sys_path_invalid") for path in raw_paths
    )
    keys_path = tuple(_path_key(path) for path in paths)
    if len(keys_path) != len(set(keys_path)):
        _fail("runtime_descriptor_sys_path_invalid")
    if any("site-packages" in path.casefold() or "appdata" in path.casefold() for path in paths):
        _fail("runtime_descriptor_sys_path_invalid")
    expected_paths = (
        ntpath.join(python_home, "python311.zip"),
        ntpath.join(python_home, "DLLs"),
        ntpath.join(python_home, "Lib"),
        python_home,
    )
    if tuple(_path_key(path) for path in paths) != tuple(
        _path_key(path) for path in expected_paths
    ):
        _fail("runtime_descriptor_sys_path_invalid")
    return {
        "python_executable": executable,
        "python_sha256": value["python_sha256"],
        "python_version": value["python_version"],
        "python_architecture": value["python_architecture"],
        "python_home": python_home,
        "venv_root": venv_root,
        "pyvenv_cfg_sha256": value["pyvenv_cfg_sha256"],
        "stdlib_paths": paths,
    }


def capture_runtime_process_facts() -> dict:
    """Return the exact current process facts checked by the runtime sealer."""
    flags = sys.flags
    architecture = "AMD64" if sys.platform == "win32" and sys.maxsize > 2**32 else "unknown"
    return {
        "sys_executable": sys.executable,
        "version_info": tuple(sys.version_info[:3]),
        "architecture": architecture,
        "sys_path": tuple(sys.path),
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "sys_pycache_prefix": sys.pycache_prefix,
        "flags": {
            "isolated": flags.isolated,
            "no_site": flags.no_site,
            "dont_write_bytecode": flags.dont_write_bytecode,
        },
    }


def _validate_process_facts(value: object, descriptor: dict) -> None:
    keys = {
        "sys_executable",
        "version_info",
        "architecture",
        "sys_path",
        "prefix",
        "base_prefix",
        "sys_pycache_prefix",
        "flags",
    }
    _expect_keys(value, keys, "runtime_process_facts_invalid")
    if (
        type(value["version_info"]) not in (tuple, list)
        or any(type(part) is not int for part in value["version_info"])
        or tuple(value["version_info"]) != (3, 11, 5)
        or value["architecture"] != _PYTHON_ARCHITECTURE
        or _path_key(
            _canonical_absolute(value["sys_executable"], "runtime_process_executable_invalid")
        )
        != _path_key(descriptor["python_executable"])
        or _path_key(_canonical_absolute(value["prefix"], "runtime_process_prefix_invalid"))
        != _path_key(descriptor["python_home"])
        or _path_key(_canonical_absolute(value["base_prefix"], "runtime_process_prefix_invalid"))
        != _path_key(descriptor["python_home"])
        or _path_key(
            _canonical_absolute(
                value["sys_pycache_prefix"], "runtime_process_pycache_prefix_invalid"
            )
        )
        != _path_key(ntpath.join(descriptor["python_home"], "disabled-bytecode-cache"))
    ):
        _fail("runtime_process_binding_mismatch")
    raw_path = value["sys_path"]
    if type(raw_path) not in (tuple, list):
        _fail("runtime_process_sys_path_invalid")
    actual = tuple(
        _canonical_absolute(path, "runtime_process_sys_path_invalid") for path in raw_path
    )
    if tuple(_path_key(path) for path in actual) != tuple(
        _path_key(path) for path in descriptor["stdlib_paths"]
    ):
        _fail("runtime_process_sys_path_mismatch")
    flags = value["flags"]
    _expect_keys(
        flags,
        {"isolated", "no_site", "dont_write_bytecode"},
        "runtime_process_flags_invalid",
    )
    if any(type(flags[name]) is not int or flags[name] != 1 for name in flags):
        _fail("runtime_process_flags_invalid")


def _directory_inventory(lease, files: Mapping[str, _File], directories, skip_subtree=None):
    if not callable(getattr(lease, "list_directory", None)):
        _fail("runtime_directory_enumerator_unavailable")
    expected = {"": set()}
    expected.update({path: set() for path in directories})
    if skip_subtree:
        expected[skip_subtree.rpartition("/")[0]].add(skip_subtree.rpartition("/")[2])
    for path in directories:
        parent, _slash, leaf = path.rpartition("/")
        if not leaf or parent not in expected:
            _fail("runtime_directory_inventory_invalid")
        expected[parent].add(leaf)
    for path in files:
        parent, _slash, leaf = path.rpartition("/")
        if not leaf or parent not in expected:
            _fail("runtime_directory_inventory_invalid")
        expected[parent].add(leaf)
    for directory, expected_names in expected.items():
        try:
            actual = lease.list_directory(directory)
        except Exception:
            _fail("runtime_directory_read_failed")
        if type(actual) not in (tuple, list) or any(type(name) is not str for name in actual):
            _fail("runtime_directory_listing_invalid")
        if tuple(sorted(actual, key=str.casefold)) != tuple(
            sorted(expected_names, key=str.casefold)
        ):
            _fail("runtime_directory_inventory_mismatch")
        folded = [name.casefold() for name in actual]
        if len(folded) != len(set(folded)):
            _fail("runtime_directory_case_collision")
        if any(name in {".", ".."} or "/" in name or "\\" in name for name in actual):
            _fail("runtime_directory_listing_invalid")
    try:
        lease.verify_current()
    except Exception:
        _fail("runtime_directory_revalidation_failed")


def _read_verified(lease, item: _File) -> bytes:
    try:
        raw = lease.read_file(item.path, max_bytes=max(1, item.size))
    except Exception:
        _fail("runtime_file_read_failed")
    if type(raw) is not bytes or len(raw) != item.size:
        _fail("runtime_file_size_mismatch")
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), item.sha256):
        _fail("runtime_file_digest_mismatch")
    return raw


def _u16(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(data):
        _fail("runtime_pe_truncated")
    return int.from_bytes(data[offset : offset + 2], "little")


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        _fail("runtime_pe_truncated")
    return int.from_bytes(data[offset : offset + 4], "little")


def _u64(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 8 > len(data):
        _fail("runtime_pe_truncated")
    return int.from_bytes(data[offset : offset + 8], "little")


def _read_c_string(data: bytes, offset: int) -> bytes:
    if offset < 0 or offset >= len(data):
        _fail("runtime_pe_string_invalid")
    end_limit = min(len(data), offset + _MAX_DLL_NAME_BYTES + 1)
    end = data.find(b"\0", offset, end_limit)
    if end < 0:
        _fail("runtime_pe_string_invalid")
    value = data[offset:end]
    if not value:
        _fail("runtime_pe_string_invalid")
    return value


def _pe_imports(data: bytes) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if type(data) is not bytes or len(data) < 256 or data[:2] != b"MZ":
        _fail("runtime_pe_image_invalid")
    pe_offset = _u32(data, 0x3C)
    if pe_offset < 64 or data[pe_offset : pe_offset + 4] != b"PE\0\0":
        _fail("runtime_pe_image_invalid")
    coff = pe_offset + 4
    if _u16(data, coff) != 0x8664:
        _fail("runtime_pe_architecture_unsupported")
    section_count = _u16(data, coff + 2)
    optional_size = _u16(data, coff + 16)
    if section_count < 1 or section_count > 96:
        _fail("runtime_pe_section_count_invalid")
    optional = coff + 20
    if optional + optional_size > len(data) or _u16(data, optional) != 0x20B:
        _fail("runtime_pe_optional_header_invalid")
    size_of_headers = _u32(data, optional + 60)
    image_base = _u64(data, optional + 24)
    directory_count = _u32(data, optional + 108)
    if optional_size < 112 or directory_count < 14:
        _fail("runtime_pe_directories_invalid")
    directory_table = optional + 112
    if directory_table + 14 * 8 > optional + optional_size:
        _fail("runtime_pe_directories_invalid")
    section_table = optional + optional_size
    if section_table + section_count * 40 > len(data):
        _fail("runtime_pe_sections_invalid")
    sections = []
    for index in range(section_count):
        offset = section_table + index * 40
        virtual_size = _u32(data, offset + 8)
        virtual_address = _u32(data, offset + 12)
        raw_size = _u32(data, offset + 16)
        raw_pointer = _u32(data, offset + 20)
        if raw_pointer + raw_size > len(data):
            _fail("runtime_pe_sections_invalid")
        sections.append((virtual_address, max(virtual_size, raw_size), raw_pointer, raw_size))

    def rva_offset(rva: int, size: int = 1) -> int:
        if rva < 0 or size < 0:
            _fail("runtime_pe_rva_invalid")
        if rva < size_of_headers:
            if rva + size > min(size_of_headers, len(data)):
                _fail("runtime_pe_rva_invalid")
            return rva
        candidates = []
        for va, virtual_size, raw_ptr, raw_size in sections:
            if va <= rva < va + virtual_size:
                delta = rva - va
                if delta + size <= raw_size:
                    candidates.append(raw_ptr + delta)
        if len(candidates) != 1:
            _fail("runtime_pe_rva_invalid")
        return candidates[0]

    def directory(index: int) -> tuple[int, int]:
        offset = directory_table + index * 8
        return _u32(data, offset), _u32(data, offset + 4)

    def imported_names(rva: int, size: int, *, delayed: bool) -> tuple[str, ...]:
        descriptor_size = 32 if delayed else 20
        if (rva == 0) != (size == 0) or size > _MAX_PE_IMPORTS * descriptor_size:
            _fail("runtime_pe_import_directory_invalid")
        if not rva:
            return ()
        if size < descriptor_size or size % descriptor_size:
            _fail("runtime_pe_import_directory_invalid")
        names = []
        terminated = False
        for index in range(size // descriptor_size):
            offset = rva_offset(rva + index * descriptor_size, descriptor_size)
            values = tuple(_u32(data, offset + field * 4) for field in range(descriptor_size // 4))
            if not any(values):
                terminated = True
                remaining_size = size - index * descriptor_size
                remaining_offset = rva_offset(rva + index * descriptor_size, remaining_size)
                if any(data[remaining_offset : remaining_offset + remaining_size]):
                    _fail("runtime_pe_import_directory_invalid")
                break
            name_rva = values[1] if delayed else values[3]
            if delayed and values[0] & ~1:
                _fail("runtime_pe_import_directory_invalid")
            if delayed and not (values[0] & 1):
                absolute_name = name_rva
                if absolute_name < image_base:
                    _fail("runtime_pe_import_directory_invalid")
                name_rva = absolute_name - image_base
            if not name_rva:
                _fail("runtime_pe_import_directory_invalid")
            name_offset = rva_offset(name_rva)
            try:
                name = _read_c_string(data, name_offset).decode("ascii").casefold()
            except (UnicodeError, ValueError):
                _fail("runtime_pe_import_name_invalid")
            if (
                not name.endswith(".dll")
                or "/" in name
                or "\\" in name
                or ":" in name
                or name in names
            ):
                _fail("runtime_pe_import_name_invalid")
            names.append(name)
        if not terminated:
            _fail("runtime_pe_import_directory_unterminated")
        return tuple(sorted(names))

    normal_rva, normal_size = directory(1)
    delay_rva, delay_size = directory(13)
    return (
        imported_names(normal_rva, normal_size, delayed=False),
        imported_names(delay_rva, delay_size, delayed=True),
    )


def _parse_native_rows(
    raw: object,
) -> dict[tuple[str, str], tuple[tuple[str, ...], tuple[str, ...]]]:
    if type(raw) is not list or len(raw) > _MAX_FILES:
        _fail("runtime_native_imports_invalid")
    result = {}
    ordering = []
    for item in raw:
        _expect_keys(item, {"root", "path", "normal", "delay"}, "runtime_native_import_invalid")
        root = item["root"]
        if root not in {"base", "venv", "dependencies"}:
            _fail("runtime_native_import_invalid")
        path = _safe_relative(item["path"])
        names = []
        for key in ("normal", "delay"):
            value = item[key]
            if type(value) is not list or len(value) > _MAX_PE_IMPORTS:
                _fail("runtime_native_import_invalid")
            parsed = []
            for name in value:
                if (
                    type(name) is not str
                    or not name
                    or len(name) > _MAX_DLL_NAME_BYTES
                    or name != name.casefold()
                    or not name.endswith(".dll")
                    or "/" in name
                    or "\\" in name
                    or ":" in name
                ):
                    _fail("runtime_native_import_invalid")
                parsed.append(name)
            if parsed != sorted(set(parsed)):
                _fail("runtime_native_import_not_sorted")
            names.append(tuple(parsed))
        identity = (root, path)
        if identity in result:
            _fail("runtime_native_import_duplicate")
        result[identity] = (names[0], names[1])
        ordering.append(identity)
    if ordering != sorted(ordering, key=lambda item: (item[0], item[1].casefold())):
        _fail("runtime_native_imports_not_sorted")
    return result


def _directory_import_name(relative: str) -> str:
    return relative.rsplit("/", 1)[-1].casefold()


def _parse_pyvenv_cfg(raw: bytes, expected_home: str) -> None:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        _fail("runtime_pyvenv_cfg_invalid")
    values = {}
    for line in text.splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or key not in {"home", "include-system-site-packages", "version"}:
            _fail("runtime_pyvenv_cfg_invalid")
        if key in values:
            _fail("runtime_pyvenv_cfg_duplicate")
        values[key] = value
    if set(values) != {"home", "include-system-site-packages", "version"}:
        _fail("runtime_pyvenv_cfg_invalid")
    home = _canonical_absolute(values["home"], "runtime_pyvenv_cfg_invalid")
    if (
        _path_key(home) != _path_key(expected_home)
        or values["include-system-site-packages"].casefold() != "false"
        or values["version"] != _PYTHON_VERSION
    ):
        _fail("runtime_pyvenv_cfg_binding_mismatch")


def _parse_manifest(value: dict, descriptor: dict, dependency_seal: object):
    top_keys = {
        "schema",
        "python_version",
        "architecture",
        "python",
        "base",
        "venv",
        "dependency_manifest_sha256",
        "native_imports",
        "system32_dll_names",
    }
    _expect_keys(value, top_keys, "runtime_manifest_fields_invalid")
    if value["schema"] != _SCHEMA or value["python_version"] != _PYTHON_VERSION:
        _fail("runtime_manifest_baseline_invalid")
    if value["architecture"] != _PYTHON_ARCHITECTURE:
        _fail("runtime_manifest_architecture_invalid")
    if not _is_sha256(value["dependency_manifest_sha256"]):
        _fail("runtime_dependency_manifest_pin_invalid")
    if dependency_seal is None:
        _fail("runtime_dependency_seal_missing")
    dep_digest = getattr(dependency_seal, "manifest_sha256", None)
    if not _is_sha256(dep_digest) or not hmac.compare_digest(
        dep_digest, value["dependency_manifest_sha256"]
    ):
        _fail("runtime_dependency_manifest_mismatch")
    if (
        not callable(getattr(dependency_seal, "verify_current", None))
        or not callable(getattr(dependency_seal, "read_file", None))
        or type(getattr(dependency_seal, "native_file_paths", None)) is not tuple
    ):
        _fail("runtime_dependency_seal_invalid")
    dependency_root = _canonical_absolute(
        getattr(dependency_seal, "dependency_root", None), "runtime_dependency_root_invalid"
    )
    expected_dependency_root = ntpath.join(descriptor["venv_root"], "Lib", "site-packages")
    if _path_key(dependency_root) != _path_key(expected_dependency_root):
        _fail("runtime_dependency_root_mismatch")

    python = value["python"]
    _expect_keys(
        python,
        {
            "base_executable",
            "python_dll",
            "venv_executable",
            "pyvenv_cfg",
            "venv_site_packages",
            "python311_zip",
            "pycache_prefix",
            "pth_files",
        },
        "runtime_manifest_python_invalid",
    )
    roles = {
        name: _safe_relative(python[name])
        for name in (
            "base_executable",
            "python_dll",
            "venv_executable",
            "pyvenv_cfg",
            "venv_site_packages",
        )
    }
    if roles != {
        "base_executable": "python.exe",
        "python_dll": "python311.dll",
        "venv_executable": "Scripts/python.exe",
        "pyvenv_cfg": "pyvenv.cfg",
        "venv_site_packages": _DEPENDENCY_SUBTREE,
    }:
        _fail("runtime_manifest_python_roles_invalid")
    if type(python["pth_files"]) is not list or python["pth_files"]:
        _fail("runtime_unpinned_pth_forbidden")
    zip_value = python["python311_zip"]
    _expect_keys(zip_value, {"present", "path", "sha256"}, "runtime_python_zip_invalid")
    if type(zip_value["present"]) is not bool:
        _fail("runtime_python_zip_invalid")
    if zip_value["present"]:
        if zip_value["path"] != "python311.zip" or not _is_sha256(zip_value["sha256"]):
            _fail("runtime_python_zip_invalid")
    elif zip_value["path"] is not None or zip_value["sha256"] is not None:
        _fail("runtime_python_zip_invalid")
    pycache_prefix = python["pycache_prefix"]
    _expect_keys(
        pycache_prefix,
        {"relative_path", "present"},
        "runtime_pycache_prefix_invalid",
    )
    if pycache_prefix != {"relative_path": "disabled-bytecode-cache", "present": False}:
        _fail("runtime_pycache_prefix_invalid")

    base_files, base_meta = _parse_root("base", value["base"], dependency_subtree=None)
    venv_files, venv_meta = _parse_root(
        "venv", value["venv"], dependency_subtree=_DEPENDENCY_SUBTREE
    )
    base_roles = {
        roles["base_executable"],
        roles["python_dll"],
    }
    if not base_roles <= base_files.keys():
        _fail("runtime_base_roles_missing")
    venv_roles = {roles["venv_executable"], roles["pyvenv_cfg"]}
    if not venv_roles <= venv_files.keys():
        _fail("runtime_venv_roles_missing")
    if base_files[roles["base_executable"]].path.casefold() != "python.exe":
        _fail("runtime_base_executable_invalid")
    if not hmac.compare_digest(
        venv_files[roles["venv_executable"]].sha256, descriptor["python_sha256"]
    ):
        _fail("runtime_python_executable_digest_mismatch")
    if not hmac.compare_digest(
        venv_files[roles["pyvenv_cfg"]].sha256, descriptor["pyvenv_cfg_sha256"]
    ):
        _fail("runtime_pyvenv_cfg_digest_mismatch")
    if zip_value["present"]:
        entry = base_files.get(zip_value["path"])
        if entry is None or not hmac.compare_digest(entry.sha256, zip_value["sha256"]):
            _fail("runtime_python_zip_digest_mismatch")
    elif any(path.casefold() == "python311.zip" for path in base_files):
        _fail("runtime_python_zip_absence_mismatch")
    if zip_value["present"]:
        _fail("runtime_python_zip_present_unsupported")
    if any(
        path.casefold() == "disabled-bytecode-cache"
        or path.casefold().startswith("disabled-bytecode-cache/")
        for path in set(base_files) | set(base_meta["directories"])
    ):
        _fail("runtime_pycache_prefix_present")

    system32 = value["system32_dll_names"]
    if type(system32) is not list:
        _fail("runtime_system32_imports_invalid")
    if any(
        type(name) is not str
        or name != name.casefold()
        or not name.endswith(".dll")
        or "/" in name
        or "\\" in name
        or ":" in name
        for name in system32
    ):
        _fail("runtime_system32_imports_invalid")
    if system32 != sorted(set(system32)):
        _fail("runtime_system32_imports_not_sorted")
    native = _parse_native_rows(value["native_imports"])
    return (
        roles,
        base_files,
        base_meta,
        venv_files,
        venv_meta,
        tuple(system32),
        native,
    )


class RuntimeClosureSeal:
    """Retained, revalidatable fixed interpreter/dependency closure."""

    __slots__ = (
        "_manifest_sha256",
        "_dependency_seal",
        "_roots",
        "_dll_directories",
        "_dll_handles",
        "_stdlib_modules",
        "_lock",
        "_closed",
    )

    def __init__(self, manifest_sha256, dependency_seal, roots, dll_directories, stdlib_modules):
        self._manifest_sha256 = manifest_sha256
        self._dependency_seal = dependency_seal
        self._roots = tuple(roots)
        self._dll_directories = tuple(dll_directories)
        self._dll_handles = []
        self._stdlib_modules = stdlib_modules
        self._lock = threading.RLock()
        self._closed = False

    @property
    def manifest_sha256(self):
        return self._manifest_sha256

    @property
    def dll_directories(self):
        return self._dll_directories

    @property
    def stdlib_modules(self):
        """Immutable manifest-bound source and native module entries."""
        return tuple(self._stdlib_modules.values())

    def stdlib_entry(self, fullname: str) -> Optional[RuntimeStdlibEntry]:
        if type(fullname) is not str or any(
            not part.isidentifier() for part in fullname.split(".")
        ):
            _fail("runtime_stdlib_module_name_invalid")
        return self._stdlib_modules.get(fullname)

    def verify_stdlib_entry(self, fullname: str) -> RuntimeStdlibEntry:
        """Re-read and hash one exact retained stdlib source or extension."""
        with self._lock:
            if self._closed:
                _fail("runtime_closure_seal_closed")
            entry = self.stdlib_entry(fullname)
            if entry is None:
                _fail("runtime_stdlib_module_not_allowlisted")
            self.verify_current()
            root = next((item for item in self._roots if item.kind == entry.root_kind), None)
            if root is None:
                _fail("runtime_stdlib_module_root_invalid")
            item = root.files.get(entry.relative_path)
            if item is None:
                _fail("runtime_stdlib_module_file_unlisted")
            raw = _read_verified(root.lease, item)
            if len(raw) != entry.size or not hmac.compare_digest(
                hashlib.sha256(raw).hexdigest(), entry.sha256
            ):
                _fail("runtime_stdlib_module_digest_mismatch")
            return entry

    def read_stdlib_source(self, fullname: str) -> bytes:
        """Return exact verified Python source bytes; never read .pyc."""
        with self._lock:
            entry = self.verify_stdlib_entry(fullname)
            if entry.kind != "source":
                _fail("runtime_stdlib_source_not_python")
            root = next(item for item in self._roots if item.kind == entry.root_kind)
            return _read_verified(root.lease, root.files[entry.relative_path])

    def register_dll_search_directories(self) -> tuple[str, ...]:
        """Register only manifest-derived DLL roots; keep cookies until close."""
        with self._lock:
            if self._closed:
                _fail("runtime_closure_seal_closed")
            self.verify_current()
            if self._dll_handles:
                return self._dll_directories
            add_directory = getattr(os, "add_dll_directory", None)
            if os.name != "nt" or not callable(add_directory):
                _fail("runtime_dll_directory_api_unavailable")
            opened = []
            try:
                for directory in self._dll_directories:
                    opened.append(add_directory(directory))
            except Exception:
                for handle in reversed(opened):
                    try:
                        handle.close()
                    except Exception:
                        pass
                _fail("runtime_dll_directory_register_failed")
            self._dll_handles = opened
            return self._dll_directories

    def verify_current(self) -> None:
        with self._lock:
            if self._closed:
                _fail("runtime_closure_seal_closed")
            try:
                self._dependency_seal.verify_current()
                for root in self._roots:
                    root.lease.verify_current()
                    _directory_inventory(
                        root.lease,
                        root.files,
                        root.directories,
                        _DEPENDENCY_SUBTREE if root.kind == "venv" else None,
                    )
            except RuntimeClosureError:
                raise
            except Exception:
                _fail("runtime_closure_identity_changed")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            errors = []
            while self._dll_handles:
                handle = self._dll_handles[-1]
                try:
                    handle.close()
                except Exception:
                    errors.append("runtime_dll_directory_close_failed")
                    break
                self._dll_handles.pop()
            if errors:
                _fail(errors[0])
            remaining = list(self._roots)
            for root in reversed(self._roots):
                try:
                    root.lease.close()
                except Exception:
                    errors.append("runtime_closure_lease_close_failed")
                else:
                    remaining.remove(root)
            self._roots = tuple(remaining)
            if errors:
                _fail(errors[0])
            self._closed = True

    def __enter__(self):
        self.verify_current()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def __repr__(self) -> str:
        return "<runtime-closure-seal>"


def _read_root_files(lease, entries):
    total = 0
    native_bytes = {}
    for path, entry in entries.items():
        raw = _read_verified(lease, entry)
        total += len(raw)
        if total > _MAX_TOTAL_BYTES:
            _fail("runtime_manifest_total_size_invalid")
        if path.casefold().endswith(_PE_SUFFIXES):
            native_bytes[path] = raw
    return native_bytes


def _module_name(relative: str, suffix: str) -> Optional[tuple[str, bool]]:
    path = relative[: -len(suffix)]
    parts = path.split("/")
    if parts[-1] == "__init__":
        parts.pop()
        is_package = True
    else:
        is_package = False
    if not parts or any(not part.isidentifier() for part in parts):
        return None
    return ".".join(parts), is_package


def _stdlib_filesystem_modules(descriptor, base_root: _Root) -> dict[str, RuntimeStdlibEntry]:
    modules = {}
    home = descriptor["python_home"]
    zip_path = ntpath.join(home, "python311.zip")
    for search_path in descriptor["stdlib_paths"]:
        if _path_key(search_path) == _path_key(zip_path):
            continue
        if not _path_is_beneath(search_path, home):
            _fail("runtime_stdlib_path_outside_base")
        relative_root = ntpath.relpath(search_path, home)
        prefix = "" if relative_root == "." else _safe_relative(relative_root.replace("\\", "/"))
        if prefix and prefix not in base_root.directories:
            _fail("runtime_stdlib_path_not_manifest_directory")
        if prefix not in {"", "DLLs", "Lib"}:
            _fail("runtime_stdlib_path_not_supported")
        prefix_slash = prefix + "/" if prefix else ""
        for relative, item in base_root.files.items():
            if not relative.startswith(prefix_slash):
                continue
            module_relative = relative[len(prefix_slash) :]
            if not prefix and "/" in module_relative:
                continue
            if prefix == "Lib" and (
                module_relative == "site-packages" or module_relative.startswith("site-packages/")
            ):
                continue
            suffix = None
            kind = None
            if module_relative.casefold().endswith(".py"):
                suffix, kind = ".py", "source"
            else:
                for extension_suffix in (
                    ".cp311-win_amd64.pyd",
                    ".abi3.pyd",
                    ".pyd",
                ):
                    if module_relative.casefold().endswith(extension_suffix):
                        suffix, kind = extension_suffix, "extension"
                        break
            if suffix is None:
                continue
            module = _module_name(module_relative, suffix)
            if module is None:
                continue
            fullname, is_package = module
            entry = RuntimeStdlibEntry(
                fullname=fullname,
                origin=ntpath.join(home, relative.replace("/", "\\")),
                kind=kind,
                is_package=is_package,
                root_kind="base",
                relative_path=relative,
                sha256=item.sha256,
                size=item.size,
            )
            if fullname in modules:
                _fail("runtime_stdlib_module_ambiguous")
            modules[fullname] = entry
    return modules


def _build_stdlib_index(descriptor, base_root, zip_bytes):
    modules = _stdlib_filesystem_modules(descriptor, base_root)
    if zip_bytes:
        _fail("runtime_python_zip_present_unsupported")
    for fullname in modules:
        parts = fullname.split(".")
        for index in range(1, len(parts)):
            parent = modules.get(".".join(parts[:index]))
            if parent is None or not parent.is_package:
                _fail("runtime_stdlib_package_parent_missing")
    return MappingProxyType(dict(sorted(modules.items())))


def _validate_import_graph(manifest_native, system_names, root_native_bytes, dependency_seal):
    pe_bytes = {}
    for root_kind, files in root_native_bytes.items():
        for path, raw in files.items():
            pe_bytes[(root_kind, path)] = raw
    dependency_paths = dependency_seal.native_file_paths
    if tuple(sorted(dependency_paths)) != dependency_paths or len(set(dependency_paths)) != len(
        dependency_paths
    ):
        _fail("runtime_dependency_native_inventory_invalid")
    dependency_total = 0
    for path in dependency_paths:
        checked = _safe_relative(path)
        if not checked.casefold().endswith((".pyd", ".dll")):
            _fail("runtime_dependency_native_inventory_invalid")
        try:
            raw = dependency_seal.read_file(checked)
        except Exception:
            _fail("runtime_dependency_native_read_failed")
        if type(raw) is not bytes:
            _fail("runtime_dependency_native_read_failed")
        dependency_total += len(raw)
        if dependency_total > _MAX_NATIVE_BYTES:
            _fail("runtime_native_bytes_limit")
        pe_bytes[("dependencies", checked)] = raw

    if len(pe_bytes) > _MAX_FILES:
        _fail("runtime_native_file_count_invalid")
    actual = {}
    for identity, raw in pe_bytes.items():
        normal, delay = _pe_imports(raw)
        actual[identity] = (normal, delay)
    if set(actual) != set(manifest_native):
        _fail("runtime_native_import_inventory_mismatch")
    for identity, names in actual.items():
        if names != manifest_native[identity]:
            _fail("runtime_native_import_mismatch")

    system = set(system_names)
    seen_system = set()
    by_basename = {}
    for (root_kind, path), _raw in pe_bytes.items():
        if not path.casefold().endswith(".exe"):
            by_basename.setdefault(_directory_import_name(path), []).append((root_kind, path))
    for names in actual.values():
        for name in names[0] + names[1]:
            if name in system:
                if by_basename.get(name):
                    _fail("runtime_system32_import_shadowed")
                seen_system.add(name)
                continue
            matches = by_basename.get(name, ())
            if len(matches) != 1:
                _fail("runtime_native_import_unresolved_or_ambiguous")
    if seen_system != system:
        _fail("runtime_system32_import_inventory_mismatch")


def seal_runtime_closure(
    manifest_raw: bytes,
    *,
    expected_manifest_sha256: str,
    descriptor_facts: Mapping,
    process_facts: Mapping,
    dependency_seal: object,
    retain_paths,
) -> RuntimeClosureSeal:
    """Validate a pinned manifest using only descriptor-derived retained roots.

    ``retain_paths`` is a fixed adapter with signature
    ``(root_kind, relative_files, relative_directories)``.  It must return a
    retained lease that validates file/directory kind and identity, supports
    exact relative ``read_file``, ``list_directory`` and ``verify_current``.
    The caller must supply already protected manifest bytes, descriptor facts,
    live process facts and the already verified dependency seal.
    """
    manifest, digest = _decode_manifest(manifest_raw, expected_manifest_sha256)
    descriptor = _parse_descriptor_facts(descriptor_facts)
    _validate_process_facts(process_facts, descriptor)
    parsed = _parse_manifest(manifest, descriptor, dependency_seal)
    roles, base_files, base_meta, venv_files, venv_meta, system32, native = parsed
    if not callable(retain_paths):
        _fail("runtime_retainer_unavailable")
    retained = []
    try:
        for kind, root_path, files, metadata in (
            ("base", descriptor["python_home"], base_files, base_meta),
            ("venv", descriptor["venv_root"], venv_files, venv_meta),
        ):
            directories = metadata["directories"]
            requested_dirs = ("",) + directories
            lease = retain_paths(kind, tuple(files), requested_dirs)
            if (
                lease is None
                or not callable(getattr(lease, "read_file", None))
                or not callable(getattr(lease, "list_directory", None))
                or not callable(getattr(lease, "verify_current", None))
                or not callable(getattr(lease, "close", None))
            ):
                _fail("runtime_retainer_invalid")
            root = _Root(kind, root_path, files, directories, lease)
            retained.append(root)
            lease.verify_current()
            _directory_inventory(
                lease,
                files,
                directories,
                _DEPENDENCY_SUBTREE if kind == "venv" else None,
            )

        roots_by_kind = {root.kind: root for root in retained}
        venv_native_bytes = _read_root_files(
            roots_by_kind["venv"].lease, roots_by_kind["venv"].files
        )
        cfg = _read_verified(
            roots_by_kind["venv"].lease,
            roots_by_kind["venv"].files[roles["pyvenv_cfg"]],
        )
        _parse_pyvenv_cfg(cfg, descriptor["python_home"])
        base_native_bytes = _read_root_files(
            roots_by_kind["base"].lease, roots_by_kind["base"].files
        )
        dependency_seal.verify_current()
        _validate_import_graph(
            native,
            system32,
            {"base": base_native_bytes, "venv": venv_native_bytes},
            dependency_seal,
        )
        directories = set()
        for root in retained:
            for path in root.files:
                if path.casefold().endswith(_PE_SUFFIXES):
                    parent = path.rpartition("/")[0]
                    directories.add(
                        ntpath.join(root.path, parent.replace("/", "\\")) if parent else root.path
                    )
        directories.update(getattr(dependency_seal, "dll_directories", ()))
        normalized_dirs = tuple(sorted({_path_key(path): path for path in directories}.values()))
        stdlib_modules = _build_stdlib_index(descriptor, roots_by_kind["base"], b"")
        for root in retained:
            root.lease.verify_current()
        dependency_seal.verify_current()
        return RuntimeClosureSeal(
            digest,
            dependency_seal,
            tuple(retained),
            normalized_dirs,
            stdlib_modules,
        )
    except BaseException:
        for root in reversed(retained):
            try:
                root.lease.close()
            except Exception:
                pass
        raise


def seal_fixed_runtime_closure(
    anchor: object,
) -> RuntimeClosureSeal:
    """Seal from the fixed anchor and facts captured inside this process.

    The caller cannot replace live process facts or the dependency lease.  This
    adapter is the production boundary; the lower-level parser remains a
    validator used by the code-owned child bootstrap.
    """
    code_pin = RUNTIME_MANIFEST_SHA256
    if not _is_sha256(code_pin):
        _fail("runtime_manifest_code_pin_invalid")
    if code_pin == _ZERO_SHA256:
        _fail("runtime_manifest_pin_unset_or_invalid")
    digest = getattr(anchor, "runtime_manifest_sha256", None)
    if not _is_sha256(digest):
        _fail("runtime_manifest_pin_unset_or_invalid")
    if not hmac.compare_digest(code_pin, digest):
        _fail("runtime_manifest_code_pin_mismatch")
    reader = getattr(anchor, "read_runtime_manifest", None)
    retain = getattr(anchor, "retain_runtime_paths", None)
    descriptor = getattr(anchor, "runtime_descriptor_facts", None)
    if not callable(reader) or not callable(retain) or not isinstance(descriptor, Mapping):
        _fail("runtime_anchor_contract_invalid")
    if _path_key(
        _canonical_absolute(
            getattr(anchor, "runtime_base_root", None), "runtime_anchor_root_invalid"
        )
    ) != _path_key(descriptor.get("python_home", "")) or _path_key(
        _canonical_absolute(
            getattr(anchor, "runtime_venv_root", None), "runtime_anchor_root_invalid"
        )
    ) != _path_key(descriptor.get("venv_root", "")):
        _fail("runtime_anchor_root_mismatch")
    dependency_seal = getattr(anchor, "dependency_seal", None)
    try:
        raw = reader()
    except Exception:
        _fail("runtime_manifest_read_failed")
    facts = capture_runtime_process_facts()
    return seal_runtime_closure(
        raw,
        expected_manifest_sha256=digest,
        descriptor_facts=descriptor,
        process_facts=facts,
        dependency_seal=dependency_seal,
        retain_paths=retain,
    )
