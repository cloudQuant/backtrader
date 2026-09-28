"""Pinned source identity for the unregistered I13 diagnostic candidate.

The checked-in manifest covers the complete ``backtrader_runtime`` Python
inventory and may additionally pin fixed read-only worker/bootstrap/service
role files under ``scripts/`` as source data. These files are not part of the
runtime import namespace. A separate code-owned pin fixes the manifest bytes.
This module deliberately imports only the standard library and the pin
constant; it never reads runtime config or credentials and never imports an
SDK.
"""

from __future__ import annotations

import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import marshal
import os
import stat
import ctypes
import sys
import tempfile
from pathlib import Path, PurePosixPath
from types import CodeType
from typing import Mapping, Optional

from .ctp_i13_source_identity_pin import I13_SOURCE_MANIFEST_SHA256


_MANIFEST_RELATIVE_PATH = PurePosixPath("backtrader_runtime/ctp_i13_source_manifest.json")
_PIN_RELATIVE_PATH = PurePosixPath("backtrader_runtime/ctp_i13_source_identity_pin.py")
_I15_PIN_RELATIVE_PATH = PurePosixPath("backtrader_runtime/ctp_i15_source_identity_pin.py")
_FIXED_READONLY_WORKER_RELATIVE_PATH = PurePosixPath(
    "scripts/ctp_i13_i15_readonly_preflight_worker.py"
)
_FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH = PurePosixPath(
    "scripts/ctp_i13_i15_readonly_preflight_bootstrap.py"
)
_FIXED_READONLY_REQUEST_COORDINATOR_RELATIVE_PATH = PurePosixPath(
    "scripts/ctp_i13_i15_readonly_request_coordinator.py"
)
_FIXED_READONLY_RECEIPT_WRITER_RELATIVE_PATH = PurePosixPath(
    "scripts/ctp_i13_i15_readonly_receipt_writer.py"
)
_FIXED_READONLY_TOKEN_BOOTSTRAP_RELATIVE_PATH = PurePosixPath(
    "scripts/ctp_i13_i15_readonly_token_bootstrap.py"
)
_FIXED_READONLY_SERVICE_ROLE_RELATIVE_PATHS = frozenset(
    {
        _FIXED_READONLY_REQUEST_COORDINATOR_RELATIVE_PATH,
        _FIXED_READONLY_RECEIPT_WRITER_RELATIVE_PATH,
        _FIXED_READONLY_TOKEN_BOOTSTRAP_RELATIVE_PATH,
    }
)
_FIXED_WORKER_DEPENDENCY_HELPER_RELATIVE_PATH = PurePosixPath(
    "backtrader_runtime/ctp_i13_worker_dependency_seal.py"
)
_PIN_EXCLUSIONS = frozenset({_PIN_RELATIVE_PATH.as_posix(), _I15_PIN_RELATIVE_PATH.as_posix()})
_SHA256_LENGTH = 64
_GENERIC_READ = 0x80000000
_FILE_READ_ATTRIBUTES = 0x0080
_FILE_SHARE_READ = 0x00000001
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000


class I13SourceIdentityError(ValueError):
    """Redacted fail-closed I13 source identity rejection."""


class I13SourceLease:
    """Windows deny-write/delete handles held while both Jobs run."""

    def __init__(
        self,
        kernel32: object,
        handles: list[object],
        digest: str,
        cache_prefix: Optional[Path] = None,
    ) -> None:
        self._kernel32 = kernel32
        self._handles = handles
        self.manifest_sha256 = digest
        self.cache_prefix = cache_prefix
        self._import_guard: Optional[I13SourceImportGuard] = None

    def install_source_import_guard(self, source_root: Path | str) -> None:
        if self._import_guard is not None:
            raise I13SourceIdentityError("source_import_guard_already_installed")
        self._import_guard = install_i13_source_import_guard(source_root)

    def close(self) -> None:
        close_handle = getattr(self._kernel32, "CloseHandle", None)
        if not callable(close_handle):
            raise I13SourceIdentityError("source_lease_close_failed")
        remaining: list[object] = []
        close_failed = False
        for handle in reversed(self._handles):
            try:
                if not close_handle(handle):
                    remaining.append(handle)
                    close_failed = True
            except Exception:
                remaining.append(handle)
                close_failed = True
        self._handles = list(reversed(remaining))
        if close_failed:
            raise I13SourceIdentityError("source_lease_close_failed")
        if self._import_guard is not None:
            self._import_guard.close()
            self._import_guard = None
        if self.cache_prefix is not None:
            _require_empty_cache_prefix(self.cache_prefix)
            try:
                self.cache_prefix.rmdir()
            except OSError as exc:
                raise I13SourceIdentityError("source_cache_prefix_cleanup_failed") from exc
            self.cache_prefix = None


def _windows_open_read_lock(kernel32: object, path: Path, *, directory: bool) -> object:
    create_file = getattr(kernel32, "CreateFileW", None)
    if not callable(create_file):
        raise I13SourceIdentityError("source_lease_unavailable")
    access = _FILE_READ_ATTRIBUTES if directory else _GENERIC_READ
    flags = _FILE_FLAG_BACKUP_SEMANTICS if directory else _FILE_ATTRIBUTE_NORMAL
    try:
        handle = create_file(
            str(path),
            access,
            _FILE_SHARE_READ,
            None,
            _OPEN_EXISTING,
            flags,
            None,
        )
    except Exception as exc:
        raise I13SourceIdentityError("source_lease_unavailable") from exc
    if handle is None or handle == -1 or handle == ctypes.c_void_p(-1).value:
        raise I13SourceIdentityError("source_lease_unavailable")
    return handle


def acquire_i13_source_lease(
    source_root: Path | str,
    *,
    expected_manifest_sha256: Optional[str] = None,
    cache_prefix_parent: Optional[Path | str] = None,
) -> I13SourceLease:
    """Verify source and hold a fresh bytecode-prefix lease across both Jobs."""

    if os.name != "nt":
        raise I13SourceIdentityError("source_lease_windows_required")
    cache_prefix: Optional[Path] = None
    try:
        root = Path(os.path.abspath(Path(source_root)))
        # An initial check provides the exact code-owned paths to lock.  The
        # complete check is repeated after every file and parent directory is
        # held, closing the discovery-to-lock race.
        digest = verify_i13_source_identity(root, expected_manifest_sha256=expected_manifest_sha256)
        manifest_path = _checked_path(root, _MANIFEST_RELATIVE_PATH, directory=False)
        manifest_files = parse_i13_source_manifest(manifest_path.read_bytes())
        file_paths = [root / PurePosixPath(name) for name in manifest_files]
        file_paths.extend(
            (
                _checked_path(root, _MANIFEST_RELATIVE_PATH, directory=False),
                _checked_path(root, _PIN_RELATIVE_PATH, directory=False),
                _checked_path(root, _I15_PIN_RELATIVE_PATH, directory=False),
            )
        )
        cache_files = _verify_runtime_python_caches(root)
        file_paths.extend(sorted(cache_files, key=str))
        directories = _source_lease_directories(root, file_paths)
        directories.update(_runtime_python_cache_directories(root))
        if cache_prefix_parent is not None:
            cache_parent = _require_concrete_directory(Path(cache_prefix_parent))
            cache_prefix = Path(tempfile.mkdtemp(prefix="i13-pycache-", dir=str(cache_parent)))
            _require_empty_cache_prefix(cache_prefix)
            directories.add(cache_parent)
            directories.add(cache_prefix)
    except I13SourceIdentityError:
        _remove_empty_cache_prefix(cache_prefix)
        raise
    except (OSError, TypeError, ValueError) as exc:
        _remove_empty_cache_prefix(cache_prefix)
        raise I13SourceIdentityError("source_lease_unavailable") from exc

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except Exception as exc:
        _remove_empty_cache_prefix(cache_prefix)
        raise I13SourceIdentityError("source_lease_unavailable") from exc
    handles: list[object] = []
    try:
        # Hold parent directories first so a path component cannot be renamed
        # or replaced after its file handles have been acquired.
        for directory in sorted(directories, key=lambda item: (len(item.parts), str(item))):
            result = os.lstat(directory)
            if not stat.S_ISDIR(result.st_mode) or _is_reparse_point(result):
                raise I13SourceIdentityError("source_path_reparse_point")
            handles.append(_windows_open_read_lock(kernel32, directory, directory=True))
        for path in file_paths:
            _checked_path(root, PurePosixPath(path.relative_to(root).as_posix()), directory=False)
            handles.append(_windows_open_read_lock(kernel32, path, directory=False))
        digest = verify_i13_source_identity(root, expected_manifest_sha256=expected_manifest_sha256)
        locked_cache_files = _verify_runtime_python_caches(root)
        if not locked_cache_files.issubset(set(file_paths)):
            raise I13SourceIdentityError("source_bytecode_cache_changed")
        if cache_prefix is not None:
            _require_empty_cache_prefix(cache_prefix)
        return I13SourceLease(kernel32, handles, digest, cache_prefix)
    except Exception as exc:
        close_handle = getattr(kernel32, "CloseHandle", None)
        if callable(close_handle):
            for handle in reversed(handles):
                try:
                    close_handle(handle)
                except Exception:
                    pass
        if isinstance(exc, I13SourceIdentityError):
            _remove_empty_cache_prefix(cache_prefix)
            raise
        _remove_empty_cache_prefix(cache_prefix)
        raise I13SourceIdentityError("source_lease_unavailable") from exc


def _require_concrete_directory(path: Path) -> Path:
    """Require every absolute path component to be an ordinary directory."""

    try:
        absolute = Path(os.path.abspath(path))
        current = Path(absolute.anchor)
        for part in absolute.parts[1:]:
            current = current / part
            result = os.lstat(current)
            if not stat.S_ISDIR(result.st_mode) or _is_reparse_point(result):
                raise I13SourceIdentityError("source_cache_prefix_invalid")
        return absolute
    except I13SourceIdentityError:
        raise
    except OSError as exc:
        raise I13SourceIdentityError("source_cache_prefix_unavailable") from exc


def _require_empty_cache_prefix(path: Path) -> None:
    try:
        _require_concrete_directory(path)
        with os.scandir(path) as entries:
            if next(entries, None) is not None:
                raise I13SourceIdentityError("source_cache_prefix_not_empty")
    except I13SourceIdentityError:
        raise
    except OSError as exc:
        raise I13SourceIdentityError("source_cache_prefix_unavailable") from exc


def _remove_empty_cache_prefix(path: Optional[Path]) -> None:
    if path is None:
        return
    try:
        _require_empty_cache_prefix(path)
        path.rmdir()
    except (OSError, I13SourceIdentityError):
        # A non-empty or replaced directory is left intact for inspection.
        pass


class _I13SourceOnlyLoader(importlib.machinery.SourceFileLoader):
    """Compile sealed source directly and never consult a checkout pyc."""

    def get_code(self, fullname: str) -> CodeType:
        source = self.get_data(self.path)
        code = self.source_to_code(source, self.path)
        if not isinstance(code, CodeType):
            raise I13SourceIdentityError("runtime_loaded_code_unverifiable")
        return code


class _I13SourceOnlyFinder(importlib.abc.MetaPathFinder):
    def __init__(self, source_root: Path) -> None:
        self._source_root = Path(os.path.abspath(source_root))
        self._package_root = self._source_root / "backtrader_runtime"

    def find_spec(self, fullname: str, path: object = None, target: object = None) -> object:
        del path, target
        if fullname != "backtrader_runtime" and not fullname.startswith("backtrader_runtime."):
            return None
        suffix = fullname.removeprefix("backtrader_runtime").lstrip(".")
        parts = suffix.split(".") if suffix else []
        if any(not part.isidentifier() for part in parts):
            raise ModuleNotFoundError(fullname)
        package_path = self._package_root.joinpath(*parts, "__init__.py")
        module_path = (
            self._package_root.joinpath(*parts).with_suffix(".py") if parts else package_path
        )
        candidate = package_path if package_path.is_file() else module_path
        if not candidate.is_file():
            raise ModuleNotFoundError(fullname)
        relative = PurePosixPath(candidate.relative_to(self._source_root).as_posix())
        _checked_path(self._source_root, relative, directory=False)
        is_package = candidate == package_path
        loader = _I13SourceOnlyLoader(fullname, str(candidate))
        return importlib.util.spec_from_file_location(
            fullname,
            str(candidate),
            loader=loader,
            submodule_search_locations=[str(candidate.parent)] if is_package else None,
        )


class I13SourceImportGuard:
    """A removable parent-process guard that excludes runtime pyc imports."""

    def __init__(self, finder: _I13SourceOnlyFinder) -> None:
        self._finder = finder

    def close(self) -> None:
        try:
            sys.meta_path.remove(self._finder)
        except ValueError as exc:
            raise I13SourceIdentityError("source_import_guard_close_failed") from exc


def install_i13_source_import_guard(source_root: Path | str) -> I13SourceImportGuard:
    root = Path(os.path.abspath(Path(source_root)))
    finder = _I13SourceOnlyFinder(root)
    sys.meta_path.insert(0, finder)
    return I13SourceImportGuard(finder)


def _is_reparse_point(result: os.stat_result) -> bool:
    return stat.S_ISLNK(result.st_mode) or bool(getattr(result, "st_file_attributes", 0) & 0x400)


def _checked_path(root: Path, relative: PurePosixPath, *, directory: bool) -> Path:
    if (
        not isinstance(relative, PurePosixPath)
        or relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
        or "\\" in relative.as_posix()
    ):
        raise I13SourceIdentityError("source_path_invalid")
    target = root.joinpath(*relative.parts)
    current = root
    try:
        root_stat = os.lstat(root)
    except OSError as exc:
        raise I13SourceIdentityError("source_root_unavailable") from exc
    if not stat.S_ISDIR(root_stat.st_mode) or _is_reparse_point(root_stat):
        raise I13SourceIdentityError("source_root_invalid")
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            result = os.lstat(current)
        except OSError as exc:
            raise I13SourceIdentityError("source_file_unavailable") from exc
        if _is_reparse_point(result):
            raise I13SourceIdentityError("source_path_reparse_point")
        expected_directory = index < len(relative.parts) - 1 or directory
        if expected_directory and not stat.S_ISDIR(result.st_mode):
            raise I13SourceIdentityError("source_directory_invalid")
        if not expected_directory and not stat.S_ISREG(result.st_mode):
            raise I13SourceIdentityError("source_file_invalid")
    return target


def parse_i13_source_manifest(raw: bytes) -> Mapping[str, str]:
    """Parse a canonical, exact-path source hash manifest."""

    if type(raw) is not bytes or not raw or len(raw) > 128 * 1024:
        raise I13SourceIdentityError("source_manifest_invalid")

    def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise I13SourceIdentityError("source_manifest_duplicate_key")
            result[key] = value
        return result

    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_pairs)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise I13SourceIdentityError("source_manifest_invalid") from exc
    if type(parsed) is not dict or set(parsed) != {"schema", "source_files"}:
        raise I13SourceIdentityError("source_manifest_invalid")
    if type(parsed["schema"]) is not int or parsed["schema"] != 1:
        raise I13SourceIdentityError("source_manifest_invalid")
    files = parsed["source_files"]
    if type(files) is not dict or not 1 <= len(files) <= 256:
        raise I13SourceIdentityError("source_manifest_invalid")
    normalized: dict[str, str] = {}
    for name, digest in files.items():
        if (
            type(name) is not str
            or type(digest) is not str
            or len(digest) != _SHA256_LENGTH
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise I13SourceIdentityError("source_manifest_invalid")
        path = PurePosixPath(name)
        if (
            path.as_posix() != name
            or path.suffix != ".py"
            or (
                path.parts[0] != "backtrader_runtime"
                and path
                not in {
                    _FIXED_READONLY_WORKER_RELATIVE_PATH,
                    _FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH,
                    *_FIXED_READONLY_SERVICE_ROLE_RELATIVE_PATHS,
                }
            )
            or path in {_PIN_RELATIVE_PATH, _I15_PIN_RELATIVE_PATH}
            or path == _MANIFEST_RELATIVE_PATH
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise I13SourceIdentityError("source_manifest_path_invalid")
        normalized[name] = digest
    if list(files) != sorted(files):
        raise I13SourceIdentityError("source_manifest_order_invalid")
    return normalized


def _verify_i13_source_files(source_root: Path, files: Mapping[str, str]) -> None:
    for name, expected_sha256 in files.items():
        path = _checked_path(source_root, PurePosixPath(name), directory=False)
        try:
            actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise I13SourceIdentityError("source_file_unavailable") from exc
        if actual_sha256 != expected_sha256:
            raise I13SourceIdentityError("source_digest_mismatch")


def _runtime_python_inventory(source_root: Path) -> set[str]:
    package_root = source_root / "backtrader_runtime"
    actual_python_files: set[str] = set()
    try:
        for current_text, directory_names, file_names in os.walk(
            package_root, topdown=True, followlinks=False
        ):
            current = Path(current_text)
            kept_directories: list[str] = []
            for directory_name in directory_names:
                directory = current / directory_name
                directory_stat = os.lstat(directory)
                if _is_reparse_point(directory_stat) or not stat.S_ISDIR(directory_stat.st_mode):
                    raise I13SourceIdentityError("source_tree_reparse_point")
                kept_directories.append(directory_name)
            directory_names[:] = kept_directories
            for file_name in file_names:
                source_path = current / file_name
                source_stat = os.lstat(source_path)
                if _is_reparse_point(source_stat):
                    raise I13SourceIdentityError("source_tree_reparse_point")
                if file_name.endswith(".py"):
                    actual_python_files.add(source_path.relative_to(source_root).as_posix())
    except I13SourceIdentityError:
        raise
    except OSError as exc:
        raise I13SourceIdentityError("source_tree_unavailable") from exc
    return actual_python_files


def _source_lease_directories(source_root: Path, file_paths: list[Path]) -> set[Path]:
    """Return exact ancestor directories needed to retain source file handles."""

    root = Path(os.path.abspath(source_root))
    directories = {root, root.parent}
    for path in file_paths:
        try:
            absolute_path = Path(os.path.abspath(path))
            absolute_path.relative_to(root)
        except (TypeError, ValueError) as exc:
            raise I13SourceIdentityError("source_path_invalid") from exc
        parent = absolute_path.parent
        while parent == root or root in parent.parents:
            directories.add(parent)
            if parent == root:
                break
            parent = parent.parent
    return directories


def _require_i13_source_inventory(source_root: Path, expected_paths: set[str]) -> None:
    expected_runtime_paths = set(expected_paths)
    readonly_paths = {
        _FIXED_READONLY_WORKER_RELATIVE_PATH.as_posix(),
        _FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH.as_posix(),
        *(path.as_posix() for path in _FIXED_READONLY_SERVICE_ROLE_RELATIVE_PATHS),
    }
    pinned_readonly_paths = expected_runtime_paths & readonly_paths
    pinned_service_paths = expected_runtime_paths & {
        path.as_posix() for path in _FIXED_READONLY_SERVICE_ROLE_RELATIVE_PATHS
    }
    if (
        _FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH.as_posix() in pinned_readonly_paths
        and _FIXED_READONLY_WORKER_RELATIVE_PATH.as_posix() not in pinned_readonly_paths
    ):
        raise I13SourceIdentityError("source_manifest_worker_unpinned")
    if (
        _FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH.as_posix() in pinned_readonly_paths
        and _FIXED_WORKER_DEPENDENCY_HELPER_RELATIVE_PATH.as_posix() not in expected_runtime_paths
    ):
        raise I13SourceIdentityError("source_manifest_dependency_helper_unpinned")
    if pinned_service_paths and pinned_service_paths != {
        path.as_posix() for path in _FIXED_READONLY_SERVICE_ROLE_RELATIVE_PATHS
    }:
        raise I13SourceIdentityError("source_manifest_service_roles_incomplete")
    if pinned_service_paths and (
        _FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH.as_posix() not in pinned_readonly_paths
        or _FIXED_READONLY_WORKER_RELATIVE_PATH.as_posix() not in pinned_readonly_paths
        or _FIXED_WORKER_DEPENDENCY_HELPER_RELATIVE_PATH.as_posix()
        not in expected_runtime_paths
    ):
        raise I13SourceIdentityError("source_manifest_service_role_bootstrap_unpinned")
    for relative in pinned_readonly_paths:
        expected_runtime_paths.remove(relative)
        _checked_path(source_root, PurePosixPath(relative), directory=False)
    if _runtime_python_inventory(source_root) != expected_runtime_paths:
        raise I13SourceIdentityError("source_manifest_file_set_mismatch")


def _normalized_code(code: CodeType) -> CodeType:
    constants = tuple(
        _normalized_code(value) if isinstance(value, CodeType) else value
        for value in code.co_consts
    )
    return code.replace(co_filename="", co_consts=constants)


def _verify_runtime_python_caches(source_root: Path) -> set[Path]:
    """Inventory only source-associated caches; imports use a fresh empty prefix."""

    source_root = Path(os.path.abspath(source_root))
    package_root = source_root / "backtrader_runtime"
    source_paths = {
        package_root.joinpath(*PurePosixPath(name).parts[1:])
        for name in _runtime_python_inventory(source_root)
    }
    expected_cache_paths: set[Path] = set()
    cache_tag = sys.implementation.cache_tag
    if type(cache_tag) is not str or not cache_tag:
        raise I13SourceIdentityError("source_bytecode_cache_unverifiable")
    for source_path in source_paths:
        for optimization in (0, 1, 2):
            suffix = f".{cache_tag}"
            if optimization:
                suffix += f".opt-{optimization}"
            cache_path = source_path.parent / "__pycache__" / f"{source_path.stem}{suffix}.pyc"
            expected_cache_paths.add(cache_path)

    actual_caches: set[Path] = set()
    for current_text, directory_names, file_names in os.walk(
        package_root, topdown=True, followlinks=False
    ):
        current = Path(current_text)
        in_cache_dir = current.name == "__pycache__"
        if in_cache_dir and directory_names:
            raise I13SourceIdentityError("source_bytecode_cache_invalid")
        for directory_name in directory_names:
            directory = current / directory_name
            directory_stat = os.lstat(directory)
            if _is_reparse_point(directory_stat) or not stat.S_ISDIR(directory_stat.st_mode):
                raise I13SourceIdentityError("source_tree_reparse_point")
        for file_name in file_names:
            cache_path = current / file_name
            cache_stat = os.lstat(cache_path)
            if _is_reparse_point(cache_stat) or not stat.S_ISREG(cache_stat.st_mode):
                raise I13SourceIdentityError("source_bytecode_cache_invalid")
            if file_name.endswith((".pyd", ".pyo", ".so", ".dll")):
                raise I13SourceIdentityError("source_importable_artifact_present")
            if in_cache_dir and not file_name.endswith(".pyc"):
                raise I13SourceIdentityError("source_bytecode_cache_invalid")
            if not file_name.endswith(".pyc"):
                continue
            if not in_cache_dir:
                raise I13SourceIdentityError("source_bytecode_cache_unverifiable")
            actual_caches.add(cache_path)
    for cache_path in actual_caches:
        if cache_path in expected_cache_paths:
            continue
        # Other CPython minors' caches are not import candidates for this
        # interpreter. The exact source-only loader and fresh pycache prefix
        # prevent this process from executing any checkout cache.
        cache_name = cache_path.name
        source_stem = cache_name.split(".cpython-", 1)[0]
        version_suffix = cache_name[len(source_stem) :] if source_stem else ""
        source_path = cache_path.parent.parent / f"{source_stem}.py"
        if (
            source_path not in source_paths
            or not version_suffix.startswith(".cpython-")
            or not version_suffix.endswith(".pyc")
            or sys.implementation.cache_tag in version_suffix
        ):
            raise I13SourceIdentityError("source_bytecode_cache_unverifiable")
    return actual_caches


def _runtime_python_cache_directories(source_root: Path) -> set[Path]:
    package_root = source_root / "backtrader_runtime"
    result: set[Path] = set()
    try:
        for current_text, directory_names, _file_names in os.walk(
            package_root, topdown=True, followlinks=False
        ):
            current = Path(current_text)
            if current.name == "__pycache__":
                result.add(current)
                if directory_names:
                    raise I13SourceIdentityError("source_bytecode_cache_invalid")
            for directory_name in directory_names:
                directory = current / directory_name
                directory_stat = os.lstat(directory)
                if _is_reparse_point(directory_stat) or not stat.S_ISDIR(directory_stat.st_mode):
                    raise I13SourceIdentityError("source_tree_reparse_point")
    except I13SourceIdentityError:
        raise
    except OSError as exc:
        raise I13SourceIdentityError("source_tree_unavailable") from exc
    return result


def verify_i13_source_identity(
    source_root: Path | str,
    *,
    expected_manifest_sha256: Optional[str] = None,
) -> str:
    """Verify every code-owned source hash and return the pinned manifest digest.

    ``expected_manifest_sha256`` is supplied through a fixed parent-created
    environment for the two Jobs.  It must equal the independent code-owned
    pin and the exact manifest bytes must hash to that same value.
    """

    expected = I13_SOURCE_MANIFEST_SHA256
    if (
        type(expected) is not str
        or len(expected) != _SHA256_LENGTH
        or any(char not in "0123456789abcdef" for char in expected)
        or (expected_manifest_sha256 is not None and expected_manifest_sha256 != expected)
    ):
        raise I13SourceIdentityError("source_identity_pin_mismatch")
    try:
        root = Path(source_root)
        if not root.is_absolute():
            raise I13SourceIdentityError("source_root_invalid")
        root = Path(os.path.abspath(root))
        manifest_path = _checked_path(root, _MANIFEST_RELATIVE_PATH, directory=False)
        manifest_raw = manifest_path.read_bytes()
    except I13SourceIdentityError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise I13SourceIdentityError("source_manifest_unavailable") from exc
    actual_manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    if actual_manifest_sha256 != expected:
        raise I13SourceIdentityError("source_manifest_digest_mismatch")
    files = parse_i13_source_manifest(manifest_raw)
    _require_i13_source_inventory(root, set(files) | _PIN_EXCLUSIONS)
    for excluded in _PIN_EXCLUSIONS:
        _checked_path(root, PurePosixPath(excluded), directory=False)
    _verify_i13_source_files(root, files)
    _verify_runtime_python_caches(root)
    return actual_manifest_sha256


def verify_i13_runtime_import_origins(source_root: Path | str) -> None:
    """Require loaded runtime modules to come only from the sealed checkout."""

    try:
        root = Path(os.path.abspath(Path(source_root)))
        package_root = (root / "backtrader_runtime").resolve(strict=True)
        package = sys.modules.get("backtrader_runtime")
        package_file = getattr(package, "__file__", None)
        package_path = getattr(package, "__path__", None)
        expected_init = (package_root / "__init__.py").resolve(strict=True)
        if (
            package is None
            or type(package_file) is not str
            or Path(package_file).resolve(strict=True) != expected_init
            or package_path is None
            or tuple(Path(item).resolve(strict=True) for item in package_path) != (package_root,)
        ):
            raise I13SourceIdentityError("runtime_import_origin_mismatch")
        for name, module in tuple(sys.modules.items()):
            if name != "backtrader_runtime" and not name.startswith("backtrader_runtime."):
                continue
            module_file = getattr(module, "__file__", None)
            if type(module_file) is not str:
                raise I13SourceIdentityError("runtime_import_origin_mismatch")
            resolved = Path(module_file).resolve(strict=True)
            suffix = name.removeprefix("backtrader_runtime").lstrip(".").replace(".", os.sep)
            expected_module_file = package_root / (suffix + ".py") if suffix else expected_init
            expected_package_file = (
                package_root / suffix / "__init__.py" if suffix else expected_init
            )
            if (
                resolved.suffix != ".py"
                or package_root not in resolved.parents
                or resolved not in {expected_module_file, expected_package_file}
            ):
                raise I13SourceIdentityError("runtime_import_origin_mismatch")
            spec = getattr(module, "__spec__", None)
            loader = getattr(spec, "loader", None)
            if (
                not isinstance(loader, importlib.machinery.SourceFileLoader)
                or getattr(spec, "origin", None) is None
                or Path(spec.origin).resolve(strict=True) != resolved
            ):
                raise I13SourceIdentityError("runtime_import_origin_mismatch")
            try:
                source = resolved.read_bytes()
                loaded_code = loader.get_code(name)
                compiled_code = compile(
                    source,
                    str(resolved),
                    "exec",
                    dont_inherit=True,
                    optimize=sys.flags.optimize,
                )
            except Exception as exc:
                raise I13SourceIdentityError("runtime_loaded_code_unverifiable") from exc
            if not isinstance(loaded_code, CodeType) or marshal.dumps(
                _normalized_code(loaded_code)
            ) != marshal.dumps(_normalized_code(compiled_code)):
                raise I13SourceIdentityError("runtime_loaded_code_mismatch")
    except I13SourceIdentityError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise I13SourceIdentityError("runtime_import_origin_mismatch") from exc


__all__ = [
    "I13SourceLease",
    "I13SourceIdentityError",
    "acquire_i13_source_lease",
    "parse_i13_source_manifest",
    "verify_i13_runtime_import_origins",
    "verify_i13_source_identity",
]
