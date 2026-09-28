"""Exact installed-dependency closure for the isolated I13/I15 worker.

This module is a source-only primitive. It never discovers dependencies from
``sys.path``, reads environment variables, invokes pip, loads an extension, or
chooses a deployment path. The manifest bytes and expected digest come from a
protected deployment descriptor; the parent adapter obtains file bytes and
retains Windows handles only through the fixed deployment anchor.

Manifest schema ``ctp_i13_i15_worker_dependencies.v1`` is canonical UTF-8 JSON
with the exact keys ``schema``, ``python``, ``distributions``, ``files``,
``directories`` and ``dll_directories``. It describes exactly three approved
distributions and the complete file/directory inventory beneath their import
roots and dist-info roots. Installed RECORD, metadata, WHEEL and direct_url
claims are cross-checked. ``__pycache__``, bytecode, path files and unlisted
entries are rejected. The manifest is not useful until its nonzero SHA-256 is
bound by the protected anchor.

The worker finder delegates only ``yaml``, ``bt_api_base`` and ``bt_api_ctp``.
It does not change ``sys.path`` or ``sys.meta_path``; installation attaches it
to the already-first sealed source finder and registers only manifest-listed
DLL directories. Source imports use bytes read through retained handles.
Native extension specs are exposed for the explicitly listed ``.pyd`` only;
tests never execute/load one.

This seal covers installed package roots only. It does not seal the Python
executable, ``python311.dll``, the standard library, or system runtime DLLs;
those interpreter/bootstrap dependencies require their own pins and review.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import importlib.abc
import importlib.machinery
import importlib.util
import io
import json
import ntpath
import os
import re
import sys
import threading
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping, Optional


MANIFEST_SCHEMA = "ctp_i13_i15_worker_dependencies.v1"
TOP_LEVEL_ROOTS = ("yaml", "bt_api_base", "bt_api_ctp")
# The PyYAML Windows wheel carries this legacy compatibility shim in its
# RECORD.  It is retained for exact distribution closure but deliberately is
# not a worker import root; imports are delegated only for TOP_LEVEL_ROOTS.
_PY_YAML_AUXILIARY_FILES = frozenset({"_yaml/__init__.py"})
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_FILE_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_BYTES = 512 * 1024 * 1024
_MAX_FILES = 100_000
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_ZERO_SHA256 = "0" * 64


class DependencySealError(ValueError):
    """Redacted fail-closed dependency-closure error."""


_DISTRIBUTIONS = {
    "PyYAML": {
        "version": "6.0.1",
        "wheel": "pyyaml-6.0.1-cp311-cp311-win_amd64.whl",
        "dist_info": "pyyaml-6.0.1.dist-info",
        "import_root": "yaml",
        "tag": "cp311-cp311-win_amd64",
    },
    "bt_api_base": {
        "version": "0.15.4",
        "wheel": "bt_api_base-0.15.4-py3-none-any.whl",
        "dist_info": "bt_api_base-0.15.4.dist-info",
        "import_root": "bt_api_base",
        "tag": "py3-none-any",
    },
    "bt_api_ctp": {
        "version": "2.0.4+iteration41.i9",
        "wheel": "bt_api_ctp-2.0.4+iteration41.i9-cp311-cp311-win_amd64.whl",
        "dist_info": "bt_api_ctp-2.0.4+iteration41.i9.dist-info",
        "import_root": "bt_api_ctp",
        "tag": "cp311-cp311-win_amd64",
    },
}


@dataclass(frozen=True)
class _FileEntry:
    path: str
    sha256: str
    size: int
    kind: str
    distribution: str


@dataclass(frozen=True)
class _Distribution:
    name: str
    version: str
    wheel: str
    wheel_sha256: str
    dist_info: str
    record: str
    metadata: str
    wheel_metadata: str
    direct_url: str
    import_root: str


def _fail(code: str):
    raise DependencySealError(code)


def _is_sha256(value: object, *, nonzero: bool = True) -> bool:
    return (
        type(value) is str
        and _SHA256_RE.fullmatch(value) is not None
        and (not nonzero or value != _ZERO_SHA256)
    )


def _pairs_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("dependency_manifest_duplicate_key")
        result[key] = value
    return result


def _safe_relative(value: object) -> str:
    if type(value) is not str or not value or len(value) > 512:
        _fail("dependency_manifest_path_invalid")
    if "\\" in value or ":" in value or value.startswith("/"):
        _fail("dependency_manifest_path_invalid")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        _fail("dependency_manifest_path_invalid")
    if any(part.casefold() == "__pycache__" for part in parts):
        _fail("dependency_manifest_bytecode_forbidden")
    if parts[-1].casefold().endswith((".pyc", ".pyo", ".pth")):
        _fail("dependency_manifest_executable_path_forbidden")
    return value


def _decode_canonical_manifest(raw: object, expected_sha256: object) -> Mapping[str, object]:
    if not _is_sha256(expected_sha256):
        _fail("dependency_manifest_pin_unset")
    if type(raw) is not bytes or not raw or len(raw) > _MAX_MANIFEST_BYTES:
        _fail("dependency_manifest_size_invalid")
    actual = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual, expected_sha256):
        _fail("dependency_manifest_digest_mismatch")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs_no_duplicates)
    except DependencySealError:
        raise
    except (UnicodeError, TypeError, ValueError):
        _fail("dependency_manifest_invalid")
    if type(value) is not dict:
        _fail("dependency_manifest_invalid")
    try:
        canonical = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        _fail("dependency_manifest_invalid")
    if canonical != raw:
        _fail("dependency_manifest_not_canonical")
    return value


def read_fixed_worker_dependency_manifest(
    read_protected_manifest: Callable[[], bytes], *, expected_sha256: str
) -> bytes:
    """Read through a fixed no-argument protected-handle callback and verify its pin."""

    if not callable(read_protected_manifest) or not _is_sha256(expected_sha256):
        _fail("dependency_manifest_pin_unset")
    try:
        raw = read_protected_manifest()
    except Exception:
        _fail("dependency_manifest_read_failed")
    if type(raw) is not bytes or not raw or len(raw) > _MAX_MANIFEST_BYTES:
        _fail("dependency_manifest_size_invalid")
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_sha256):
        _fail("dependency_manifest_digest_mismatch")
    return raw


def _expected_keys(value: Mapping[str, object], expected: set[str], code: str) -> None:
    if set(value) != expected:
        _fail(code)


def _distribution_for_path(path: str) -> tuple[str, str]:
    first = path.split("/", 1)[0]
    if path in _PY_YAML_AUXILIARY_FILES:
        return "PyYAML", _DISTRIBUTIONS["PyYAML"]["import_root"]
    for name, facts in _DISTRIBUTIONS.items():
        if first in {facts["import_root"], facts["dist_info"]}:
            return name, facts["import_root"]
    _fail("dependency_manifest_unapproved_namespace")


def _parse_manifest(value: Mapping[str, object]):
    _expected_keys(
        value,
        {"schema", "python", "distributions", "files", "directories", "dll_directories"},
        "dependency_manifest_schema_invalid",
    )
    if value["schema"] != MANIFEST_SCHEMA:
        _fail("dependency_manifest_schema_invalid")
    python = value["python"]
    if type(python) is not dict:
        _fail("dependency_manifest_python_invalid")
    _expected_keys(
        python, {"implementation", "version", "platform"}, "dependency_manifest_python_invalid"
    )
    if python != {"implementation": "CPython", "version": "3.11.5", "platform": "win_amd64"}:
        _fail("dependency_manifest_python_mismatch")

    raw_distributions = value["distributions"]
    if type(raw_distributions) is not list or len(raw_distributions) != len(_DISTRIBUTIONS):
        _fail("dependency_manifest_distributions_invalid")
    distributions = {}
    for item in raw_distributions:
        if type(item) is not dict:
            _fail("dependency_manifest_distribution_invalid")
        _expected_keys(
            item,
            {
                "name",
                "version",
                "wheel",
                "wheel_sha256",
                "dist_info",
                "record",
                "metadata",
                "wheel_metadata",
                "direct_url",
            },
            "dependency_manifest_distribution_invalid",
        )
        name = item["name"]
        facts = _DISTRIBUTIONS.get(name) if type(name) is str else None
        if facts is None or name in distributions:
            _fail("dependency_manifest_distribution_unapproved")
        if (
            item["version"] != facts["version"]
            or item["wheel"] != facts["wheel"]
            or item["dist_info"] != facts["dist_info"]
            or not _is_sha256(item["wheel_sha256"])
        ):
            _fail("dependency_manifest_distribution_mismatch")
        dist_info = _safe_relative(item["dist_info"])
        for slot, expected_name in (
            ("record", "RECORD"),
            ("metadata", "METADATA"),
            ("wheel_metadata", "WHEEL"),
            ("direct_url", "direct_url.json"),
        ):
            candidate = _safe_relative(item[slot])
            if candidate != dist_info + "/" + expected_name:
                _fail("dependency_manifest_dist_info_path_invalid")
        distributions[name] = _Distribution(
            name=name,
            version=facts["version"],
            wheel=facts["wheel"],
            wheel_sha256=item["wheel_sha256"],
            dist_info=dist_info,
            record=item["record"],
            metadata=item["metadata"],
            wheel_metadata=item["wheel_metadata"],
            direct_url=item["direct_url"],
            import_root=facts["import_root"],
        )
    if set(distributions) != set(_DISTRIBUTIONS):
        _fail("dependency_manifest_distributions_invalid")
    if [item["name"] for item in raw_distributions] != sorted(_DISTRIBUTIONS):
        _fail("dependency_manifest_distributions_not_sorted")

    raw_files = value["files"]
    if type(raw_files) is not list or not raw_files or len(raw_files) > _MAX_FILES:
        _fail("dependency_manifest_files_invalid")
    files = {}
    files_by_distribution = {name: set() for name in distributions}
    total_size = 0
    for item in raw_files:
        if type(item) is not dict:
            _fail("dependency_manifest_file_invalid")
        _expected_keys(item, {"path", "sha256", "size", "kind"}, "dependency_manifest_file_invalid")
        path = _safe_relative(item["path"])
        if path in files or not _is_sha256(item["sha256"]):
            _fail("dependency_manifest_file_invalid")
        size = item["size"]
        if type(size) is not int or not 0 <= size <= _MAX_FILE_BYTES:
            _fail("dependency_manifest_file_size_invalid")
        total_size += size
        if total_size > _MAX_TOTAL_BYTES:
            _fail("dependency_manifest_total_size_invalid")
        kind = item["kind"]
        if type(kind) is not str or kind not in {"source", "extension", "data", "metadata"}:
            _fail("dependency_manifest_file_kind_invalid")
        distribution, import_root = _distribution_for_path(path)
        if path in _PY_YAML_AUXILIARY_FILES:
            if kind != "source":
                _fail("dependency_manifest_file_kind_invalid")
        elif path.startswith(import_root + "/"):
            suffix = path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
            allowed_kind = (
                "source"
                if suffix in {"py", "pyi"}
                else "extension"
                if suffix in {"pyd", "dll"}
                else "data"
            )
            if kind != allowed_kind:
                _fail("dependency_manifest_file_kind_invalid")
        else:
            if path not in {
                distributions[distribution].record,
                distributions[distribution].metadata,
                distributions[distribution].wheel_metadata,
                distributions[distribution].direct_url,
            } and not path.startswith(distributions[distribution].dist_info + "/"):
                _fail("dependency_manifest_dist_info_path_invalid")
            if kind != "metadata":
                _fail("dependency_manifest_file_kind_invalid")
        entry = _FileEntry(path, item["sha256"], size, kind, distribution)
        files[path] = entry
        files_by_distribution[distribution].add(path)
    if tuple(files) != tuple(sorted(files)):
        _fail("dependency_manifest_files_not_sorted")
    if len({path.casefold() for path in files}) != len(files):
        _fail("dependency_manifest_case_collision")
    for item in distributions.values():
        if not {item.record, item.metadata, item.wheel_metadata, item.direct_url} <= files.keys():
            _fail("dependency_manifest_dist_info_incomplete")

    raw_directories = value["directories"]
    if type(raw_directories) is not list:
        _fail("dependency_manifest_directories_invalid")
    directories = tuple(_safe_relative(path) for path in raw_directories)
    if directories != tuple(sorted(set(directories))):
        _fail("dependency_manifest_directories_not_sorted")
    if len({path.casefold() for path in directories}) != len(directories):
        _fail("dependency_manifest_case_collision")
    expected_directories = set()
    for path in files:
        parts = path.split("/")[:-1]
        for index in range(1, len(parts) + 1):
            expected_directories.add("/".join(parts[:index]))
    if set(directories) != expected_directories:
        _fail("dependency_manifest_directory_inventory_mismatch")

    raw_dll_dirs = value["dll_directories"]
    if type(raw_dll_dirs) is not list:
        _fail("dependency_manifest_dll_directories_invalid")
    dll_dirs = tuple(_safe_relative(path) for path in raw_dll_dirs)
    if dll_dirs != tuple(sorted(set(dll_dirs))) or not dll_dirs:
        _fail("dependency_manifest_dll_directories_invalid")
    if any(
        path not in directories
        or not any(path == root or path.startswith(root + "/") for root in TOP_LEVEL_ROOTS)
        for path in dll_dirs
    ):
        _fail("dependency_manifest_dll_directories_unapproved")
    native_dirs = {
        entry.path.rpartition("/")[0] for entry in files.values() if entry.kind == "extension"
    }
    if not native_dirs or set(dll_dirs) != native_dirs:
        _fail("dependency_manifest_dll_directory_empty")
    for name, dist in distributions.items():
        owned = files_by_distribution[name]
        if not {dist.record, dist.metadata, dist.wheel_metadata, dist.direct_url} <= owned:
            _fail("dependency_manifest_dist_info_incomplete")
    return distributions, files, directories, dll_dirs, files_by_distribution


def _read_entry(lease, entry: _FileEntry) -> bytes:
    try:
        raw = lease.read_file(entry.path, max_bytes=max(1, entry.size))
    except Exception:
        _fail("dependency_file_read_failed")
    if type(raw) is not bytes or len(raw) != entry.size:
        _fail("dependency_file_size_mismatch")
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), entry.sha256):
        _fail("dependency_file_digest_mismatch")
    return raw


def _header_value(text: str, name: str) -> Optional[str]:
    matches = [
        line.partition(":")[2].strip()
        for line in text.splitlines()
        if line.partition(":")[0] == name
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _record_digest(raw: bytes, code: str) -> str:
    if not raw.startswith(b"sha256="):
        _fail(code)
    encoded = raw[7:]
    try:
        decoded = base64.urlsafe_b64decode(encoded + b"=" * ((4 - len(encoded) % 4) % 4))
    except (ValueError, TypeError):
        _fail(code)
    if len(decoded) != 32:
        _fail(code)
    return decoded.hex()


def _validate_distribution_files(lease, distributions, files, files_by_distribution) -> None:
    cache = {}
    for path, entry in files.items():
        cache[path] = _read_entry(lease, entry)
    for name, dist in distributions.items():
        metadata = cache[dist.metadata].decode("utf-8", errors="strict")
        wheel = cache[dist.wheel_metadata].decode("utf-8", errors="strict")
        metadata_name = _header_value(metadata, "Name")
        metadata_version = _header_value(metadata, "Version")
        if (
            metadata_name is None
            or metadata_name.casefold() != name.casefold()
            or metadata_version != dist.version
        ):
            _fail("dependency_distribution_metadata_mismatch")
        tags = [
            line.partition(":")[2].strip() for line in wheel.splitlines() if line.startswith("Tag:")
        ]
        if tags != [_DISTRIBUTIONS[name]["tag"]] or _header_value(wheel, "Wheel-Version") != "1.0":
            _fail("dependency_distribution_wheel_mismatch")
        try:
            direct_url = json.loads(
                cache[dist.direct_url].decode("utf-8"), object_pairs_hook=_pairs_no_duplicates
            )
        except DependencySealError:
            raise
        except (UnicodeError, TypeError, ValueError):
            _fail("dependency_distribution_direct_url_invalid")
        if type(direct_url) is not dict or set(direct_url) != {"archive_info", "url"}:
            _fail("dependency_distribution_direct_url_invalid")
        archive = direct_url["archive_info"]
        if type(archive) is not dict or set(archive) - {"hash", "hashes"}:
            _fail("dependency_distribution_direct_url_invalid")
        hashes = archive.get("hashes")
        if hashes is not None and (
            type(hashes) is not dict
            or set(hashes) != {"sha256"}
            or hashes.get("sha256") != dist.wheel_sha256
        ):
            _fail("dependency_distribution_wheel_digest_mismatch")
        legacy_hash = archive.get("hash")
        if legacy_hash is not None and legacy_hash != "sha256=" + dist.wheel_sha256:
            _fail("dependency_distribution_wheel_digest_mismatch")
        if hashes is None and legacy_hash is None:
            _fail("dependency_distribution_wheel_digest_missing")
        url = direct_url["url"]
        if type(url) is not str or not url.startswith("file:///"):
            _fail("dependency_distribution_direct_url_invalid")
        basename = url.replace("\\", "/").rsplit("/", 1)[-1]
        # Wheel filenames use ``+`` for local versions; pip percent-encodes it
        # in direct_url.json. Accept only that one expected escape, not a
        # general URL-decoding surface.
        basename = basename.replace("%2B", "+").replace("%2b", "+")
        if "%" in basename:
            _fail("dependency_distribution_wheel_name_mismatch")
        if basename != dist.wheel:
            _fail("dependency_distribution_wheel_name_mismatch")

        try:
            text = cache[dist.record].decode("utf-8")
            rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
        except (UnicodeError, csv.Error, ValueError):
            _fail("dependency_distribution_record_invalid")
        seen = set()
        for row in rows:
            if len(row) != 3:
                _fail("dependency_distribution_record_invalid")
            relative, digest, size = row
            relative = _safe_relative(relative)
            record_path = relative
            if record_path not in files_by_distribution[name] or record_path in seen:
                _fail("dependency_distribution_record_invalid")
            seen.add(record_path)
            if record_path == dist.record:
                if digest or size:
                    _fail("dependency_distribution_record_self_invalid")
                continue
            if not digest or not size:
                _fail("dependency_distribution_record_incomplete")
            entry = files.get(record_path)
            if entry is None:
                _fail("dependency_distribution_record_unlisted_file")
            if (
                _record_digest(
                    digest.encode("ascii"), "dependency_distribution_record_digest_invalid"
                )
                != entry.sha256
            ):
                _fail("dependency_distribution_record_digest_mismatch")
            if size != str(entry.size):
                _fail("dependency_distribution_record_size_mismatch")
        if seen != files_by_distribution[name]:
            _fail("dependency_distribution_record_inventory_mismatch")
    return cache


def _python_site_packages(python_executable: object) -> str:
    if type(python_executable) is not str or not ntpath.isabs(python_executable):
        _fail("dependency_python_path_invalid")
    normalized = ntpath.normpath(python_executable)
    if normalized != python_executable or ntpath.basename(normalized).casefold() != "python.exe":
        _fail("dependency_python_path_invalid")
    venv = ntpath.dirname(ntpath.dirname(normalized))
    if not venv or venv.endswith(":"):
        _fail("dependency_python_path_invalid")
    return ntpath.join(venv, "Lib", "site-packages")


class WorkerDependencySeal:
    """Retain and revalidate the exact installed dependency closure."""

    __slots__ = (
        "_dependency_root",
        "_manifest_sha256",
        "_dll_directories",
        "_lease",
        "_files",
        "_directories",
        "_dll_relative",
        "_finder",
        "_lock",
        "_closed",
    )

    def __init__(self, dependency_root, manifest_sha256, dll_relative, lease, files, directories):
        self._dependency_root = dependency_root
        self._manifest_sha256 = manifest_sha256
        self._lease = lease
        self._files = files
        self._directories = directories
        self._dll_relative = dll_relative
        self._dll_directories = tuple(
            ntpath.join(dependency_root, path.replace("/", "\\")) for path in dll_relative
        )
        self._finder = None
        self._lock = threading.RLock()
        self._closed = False

    @property
    def dependency_root(self):
        return self._dependency_root

    @property
    def manifest_sha256(self):
        return self._manifest_sha256

    @property
    def dll_directories(self):
        return self._dll_directories

    @property
    def native_file_paths(self):
        """Exact package PE files eligible for runtime import-closure inspection."""
        return tuple(
            path
            for path, entry in self._files.items()
            if entry.kind == "extension" and path.casefold().endswith((".pyd", ".dll"))
        )

    def read_file(self, relative_path):
        """Read one exact, retained PE member after its digest is rechecked."""
        with self._lock:
            if self._closed:
                _fail("dependency_seal_closed")
            if type(relative_path) is not str or relative_path not in self.native_file_paths:
                _fail("dependency_native_file_unlisted")
            self.verify_current()
            entry = self._files[relative_path]
            return _read_entry(self._lease, entry)

    def verify_current(self) -> None:
        with self._lock:
            if self._closed:
                _fail("dependency_seal_closed")
            try:
                self._lease.verify_current()
            except Exception:
                _fail("dependency_lease_changed")
            _verify_directory_inventory(self._lease, self._files, self._directories)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            errors = []
            finder = self._finder
            if finder is not None:
                try:
                    finder.close()
                except Exception:
                    errors.append("dependency_finder_close_failed")
                else:
                    self._finder = None
            if self._finder is None:
                try:
                    self._lease.close()
                except Exception:
                    errors.append("dependency_lease_close_failed")
                else:
                    self._closed = True
            if errors:
                _fail(errors[0])

    def __enter__(self):
        self.verify_current()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def __repr__(self) -> str:
        return "<worker-dependency-seal>"


def _verify_directory_inventory(lease, files, directories) -> None:
    if not callable(getattr(lease, "list_directory", None)):
        _fail("dependency_directory_enumerator_unavailable")
    expected_children = {path: set() for path in directories}
    for path in directories:
        if not path:
            continue
        parent = path.rpartition("/")[0]
        if parent in expected_children:
            expected_children[parent].add(path.rpartition("/")[2])
    for path in files:
        parent = path.rpartition("/")[0]
        leaf = path.rpartition("/")[2]
        if not leaf or parent not in expected_children:
            _fail("dependency_directory_inventory_mismatch")
        expected_children[parent].add(leaf)
    for directory in directories:
        try:
            actual = lease.list_directory(directory)
        except Exception:
            _fail("dependency_directory_read_failed")
        if type(actual) not in (tuple, list) or any(type(name) is not str for name in actual):
            _fail("dependency_directory_listing_invalid")
        if any(
            name.casefold() == "__pycache__" or name.casefold().endswith((".pyc", ".pyo", ".pth"))
            for name in actual
        ):
            _fail("dependency_bytecode_forbidden")
        if tuple(sorted(actual, key=str.casefold)) != tuple(
            sorted(expected_children[directory], key=str.casefold)
        ):
            _fail("dependency_directory_inventory_mismatch")
        folded = [name.casefold() for name in actual]
        if len(folded) != len(set(folded)):
            _fail("dependency_directory_case_collision")


class _WorkerSourceLoader(importlib.abc.Loader):
    def __init__(self, seal, finder, fullname, relative, is_package):
        self._seal = seal
        self._finder = finder
        self._fullname = fullname
        self._relative = relative
        self._is_package = is_package

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        self._finder._begin(self, module)
        try:
            entry = self._seal._files[self._relative]
            source = _read_entry(self._seal._lease, entry)
            origin = ntpath.join(self._seal.dependency_root, self._relative.replace("/", "\\"))
            code = compile(source, origin, "exec", dont_inherit=True)
            module.__file__ = origin
            module.__cached__ = None
            if self._is_package:
                module.__path__ = [ntpath.dirname(origin)]
            exec(code, module.__dict__)
            self._finder._complete(self, module)
        except BaseException:
            self._finder._abort(self, module)
            raise


class WorkerDependencyFinder(importlib.abc.MetaPathFinder):
    """Finder for the exact pinned dependency namespaces only."""

    top_level_roots = TOP_LEVEL_ROOTS

    def __init__(self, seal: WorkerDependencySeal):
        self._seal = seal
        self._issued_specs = {}
        self._executing = {}
        self._executed = {}
        self._dll_handles = []
        self._attached = None
        self._closed = False
        self._lock = threading.RLock()

    def find_spec(self, fullname, path=None, target=None):
        root = fullname.partition(".")[0]
        if root not in TOP_LEVEL_ROOTS:
            return None
        if any(not part.isidentifier() for part in fullname.split(".")):
            raise ModuleNotFoundError("dependency_module_name_invalid")
        self.validate_current()
        base = fullname.replace(".", "/")
        candidates = []
        for suffix in (".py",) + tuple(importlib.machinery.EXTENSION_SUFFIXES):
            candidates.append((base + "/__init__" + suffix, True))
        for suffix in (".py",) + tuple(importlib.machinery.EXTENSION_SUFFIXES):
            candidates.append((base + suffix, False))
        matches = [
            (relative, package) for relative, package in candidates if relative in self._seal._files
        ]
        if len(matches) != 1:
            raise ModuleNotFoundError("dependency_module_not_allowlisted")
        relative, is_package = matches[0]
        entry = self._seal._files[relative]
        origin = ntpath.join(self._seal.dependency_root, relative.replace("/", "\\"))
        if entry.kind == "extension":
            loader = importlib.machinery.ExtensionFileLoader(fullname, origin)
        elif entry.kind == "source":
            loader = _WorkerSourceLoader(self._seal, self, fullname, relative, is_package)
        else:
            raise ModuleNotFoundError("dependency_module_kind_invalid")
        spec = importlib.util.spec_from_loader(
            fullname, loader, origin=origin, is_package=is_package
        )
        if spec is None:
            _fail("dependency_module_spec_unavailable")
        spec.cached = None
        if is_package:
            spec.submodule_search_locations = [ntpath.dirname(origin)]
        with self._lock:
            self._issued_specs[fullname] = spec
        return spec

    def _begin(self, loader, module):
        with self._lock:
            fullname = loader._fullname
            if (
                sys.modules.get(fullname) is not module
                or self._issued_specs.get(fullname) is not module.__spec__
                or fullname in self._executing
            ):
                _fail("dependency_module_execution_invalid")
            self._executing[fullname] = module

    def _complete(self, loader, module):
        with self._lock:
            fullname = loader._fullname
            if self._executing.get(fullname) is not module or not self.owns_module(
                fullname, module
            ):
                _fail("dependency_module_execution_invalid")
            del self._executing[fullname]
            self._executed[fullname] = module

    def _abort(self, loader, module):
        with self._lock:
            if self._executing.get(loader._fullname) is module:
                del self._executing[loader._fullname]
                self._issued_specs.pop(loader._fullname, None)

    def owns_module(self, fullname, module) -> bool:
        with self._lock:
            spec = getattr(module, "__spec__", None)
            if (
                type(fullname) is not str
                or fullname.partition(".")[0] not in TOP_LEVEL_ROOTS
                or sys.modules.get(fullname) is not module
                or self._issued_specs.get(fullname) is not spec
                or getattr(spec, "name", None) != fullname
                or getattr(module, "__name__", None) != fullname
                or getattr(module, "__file__", None) != getattr(spec, "origin", None)
                or getattr(module, "__loader__", None) is not getattr(spec, "loader", None)
                or getattr(spec, "cached", None) is not None
            ):
                return False
            origin = getattr(spec, "origin", None)
            if type(origin) is not str or not _path_is_beneath(origin, self._seal.dependency_root):
                return False
            relative = ntpath.relpath(origin, self._seal.dependency_root).replace("\\", "/")
            entry = self._seal._files.get(relative)
            if entry is None or entry.kind not in {"source", "extension"}:
                return False
            expected_loader = getattr(spec, "loader", None)
            locations = getattr(spec, "submodule_search_locations", None)
            is_package = relative.rsplit("/", 1)[-1].startswith("__init__.")
            expected_directory = ntpath.dirname(origin)
            if is_package:
                if (
                    type(locations) is not list
                    or locations != [expected_directory]
                    or getattr(module, "__path__", None) != [expected_directory]
                ):
                    return False
            elif locations is not None:
                return False
            if isinstance(expected_loader, _WorkerSourceLoader):
                if (
                    expected_loader._finder is not self
                    or expected_loader._seal is not self._seal
                    or expected_loader._fullname != fullname
                    or expected_loader._relative != relative
                ):
                    return False
            elif type(expected_loader) is not importlib.machinery.ExtensionFileLoader:
                return False
            if isinstance(expected_loader, _WorkerSourceLoader):
                return (
                    self._executing.get(fullname) is module
                    or self._executed.get(fullname) is module
                )
            return type(expected_loader) is importlib.machinery.ExtensionFileLoader

    def validate_current(self) -> None:
        if self._closed:
            _fail("dependency_finder_closed")
        self._seal.verify_current()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            errors = []
            if self._attached is not None:
                try:
                    self._attached.detach_dependency_finder(self)
                except Exception:
                    errors.append("dependency_finder_detach_failed")
                else:
                    self._attached = None
            remaining = []
            for handle in reversed(self._dll_handles):
                try:
                    handle.close()
                except Exception:
                    remaining.append(handle)
                    errors.append("dependency_dll_directory_close_failed")
            self._dll_handles[:] = list(reversed(remaining))
            if not errors:
                self._closed = True
            if errors:
                _fail(errors[0])


def _path_is_beneath(path: str, root: str) -> bool:
    try:
        return ntpath.commonpath((ntpath.normcase(path), ntpath.normcase(root))) == ntpath.normcase(
            root
        )
    except (TypeError, ValueError):
        return False


def _parse_and_retain(raw, expected_sha256, python_executable, retain_paths):
    value = _decode_canonical_manifest(raw, expected_sha256)
    distributions, files, directories, dll_dirs, files_by_distribution = _parse_manifest(value)
    if len(files) + len(directories) > _MAX_FILES:
        _fail("dependency_manifest_path_count_invalid")
    root = _python_site_packages(python_executable)
    if not callable(retain_paths):
        _fail("dependency_retainer_unavailable")
    try:
        retained_directories = ("",) + directories
        lease = retain_paths(tuple(files), retained_directories)
    except Exception:
        _fail("dependency_paths_retain_failed")
    if (
        lease is None
        or not callable(getattr(lease, "read_file", None))
        or not callable(getattr(lease, "verify_current", None))
        or not callable(getattr(lease, "close", None))
        or not callable(getattr(lease, "list_directory", None))
    ):
        try:
            if lease is not None and callable(getattr(lease, "close", None)):
                lease.close()
        except Exception:
            pass
        _fail("dependency_retainer_invalid")
    try:
        lease.verify_current()
        _verify_directory_inventory(lease, files, retained_directories)
        _validate_distribution_files(lease, distributions, files, files_by_distribution)
    except BaseException:
        try:
            lease.close()
        except Exception:
            pass
        raise
    return WorkerDependencySeal(
        root,
        expected_sha256,
        dll_dirs,
        lease,
        MappingProxyType(dict(files)),
        retained_directories,
    )


def seal_worker_dependencies(
    manifest_raw: bytes,
    *,
    expected_manifest_sha256: str,
    python_executable: str,
    retain_paths: Callable[[tuple[str, ...], tuple[str, ...]], object],
) -> WorkerDependencySeal:
    """Seal the exact dependency manifest beneath the pinned interpreter venv."""

    return _parse_and_retain(
        manifest_raw, expected_manifest_sha256, python_executable, retain_paths
    )


def seal_fixed_worker_dependencies(anchor) -> WorkerDependencySeal:
    """Parent adapter for the fixed, already-open deployment anchor."""

    if anchor is None:
        _fail("dependency_anchor_unavailable")
    try:
        expected = anchor.worker_dependency_manifest_sha256
    except Exception:
        _fail("dependency_anchor_contract_invalid")
    if not _is_sha256(expected):
        _fail("dependency_manifest_pin_unset")
    try:
        root = anchor.dependency_root
        raw = anchor.read_worker_dependency_manifest()
        retain = anchor.retain_dependency_paths
        python_executable = anchor.python_executable
    except Exception:
        _fail("dependency_anchor_contract_invalid")
    if type(root) is not str or not ntpath.isabs(root):
        _fail("dependency_root_invalid")
    derived = _python_site_packages(python_executable)
    if ntpath.normcase(root) != ntpath.normcase(derived):
        _fail("dependency_root_mismatch")
    return seal_worker_dependencies(
        raw,
        expected_manifest_sha256=expected,
        python_executable=python_executable,
        retain_paths=retain,
    )


def install_worker_dependency_finder(seal: WorkerDependencySeal) -> WorkerDependencyFinder:
    """Attach dependency imports to the first sealed finder; never edit sys.path."""

    if not isinstance(seal, WorkerDependencySeal):
        _fail("dependency_seal_invalid")
    if seal._finder is not None:
        _fail("dependency_finder_already_installed")
    seal.verify_current()
    if not sys.meta_path:
        _fail("sealed_source_finder_unavailable")
    source_finder = sys.meta_path[0]
    attach = getattr(source_finder, "attach_dependency_finder", None)
    if not callable(attach):
        _fail("sealed_source_finder_unavailable")
    finder = WorkerDependencyFinder(seal)
    add_dll_directory = getattr(os, "add_dll_directory", None)
    try:
        for directory in seal.dll_directories:
            if not callable(add_dll_directory):
                _fail("dependency_dll_directory_api_unavailable")
            finder._dll_handles.append(add_dll_directory(directory))
        attach(finder)
        finder._attached = source_finder
        seal._finder = finder
        seal.verify_current()
        return finder
    except BaseException:
        try:
            finder.close()
        except Exception:
            pass
        raise


__all__ = [
    "DependencySealError",
    "MANIFEST_SCHEMA",
    "TOP_LEVEL_ROOTS",
    "WorkerDependencyFinder",
    "WorkerDependencySeal",
    "install_worker_dependency_finder",
    "read_fixed_worker_dependency_manifest",
    "seal_fixed_worker_dependencies",
    "seal_worker_dependencies",
]
