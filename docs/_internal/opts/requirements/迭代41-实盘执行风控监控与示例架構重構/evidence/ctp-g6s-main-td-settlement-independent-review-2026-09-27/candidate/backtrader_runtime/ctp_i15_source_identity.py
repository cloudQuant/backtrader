"""Exact source-tree seal for the unregistered supervised I15 candidate.

Both I15 and I13 share a package-wide Python source inventory. Their digest
pin modules are excluded from that inventory to avoid a cross-candidate
self-hash cycle; both are still code-owned trust roots and require independent
review. The JSON manifests are data files and are not Python import sources.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional, Tuple, Union


I15_SOURCE_MANIFEST_RELATIVE_PATH = "backtrader_runtime/ctp_i15_source_manifest.json"
I15_SOURCE_MANIFEST_SCHEMA = "ctp_i15_source_manifest.v2"
I15_SOURCE_MANIFEST_ENV = "bt_i15_source_manifest_sha256"
I15_SOURCE_PACKAGE_RELATIVE_PATH = "backtrader_runtime"
I15_EXCLUDED_SOURCE_PIN_PATHS = (
    "backtrader_runtime/ctp_i13_source_identity_pin.py",
    "backtrader_runtime/ctp_i15_source_identity_pin.py",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class I15SourceIdentityError(ValueError):
    """A source manifest, runtime source, or import cache failed the seal."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class I15SourceIdentityBinding:
    """Exact manifest identity bound into the parent, metadata Job, and worker."""

    manifest_sha256: str
    source_count: int

    def __post_init__(self) -> None:
        if (
            type(self.manifest_sha256) is not str
            or not _SHA256_RE.fullmatch(self.manifest_sha256)
            or type(self.source_count) is not int
            or self.source_count <= 0
        ):
            raise ValueError("i15_source_binding_invalid")


def _safe_relative_source_path(value: object) -> Optional[PurePosixPath]:
    if type(value) is not str or not value or "\\" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path


def _is_reparse_or_symlink(value: os.stat_result) -> bool:
    return stat.S_ISLNK(value.st_mode) or bool(getattr(value, "st_file_attributes", 0) & 0x400)


def _lstat(path: Path, *, missing_reason: str) -> os.stat_result:
    try:
        return os.lstat(path)
    except OSError:
        raise I15SourceIdentityError(missing_reason) from None


def _read_regular_file(root: Path, relative: PurePosixPath) -> bytes:
    root_stat = _lstat(root, missing_reason="source_root_unavailable")
    if _is_reparse_or_symlink(root_stat) or not stat.S_ISDIR(root_stat.st_mode):
        raise I15SourceIdentityError("source_root_invalid")
    current = root
    for index, component in enumerate(relative.parts):
        current = current / component
        before = _lstat(current, missing_reason="source_file_unavailable")
        if _is_reparse_or_symlink(before):
            raise I15SourceIdentityError("source_path_reparse_point")
        final = index == len(relative.parts) - 1
        if final:
            if not stat.S_ISREG(before.st_mode):
                raise I15SourceIdentityError("source_file_not_regular")
            try:
                content = current.read_bytes()
                after = os.lstat(current)
            except OSError:
                raise I15SourceIdentityError("source_file_unavailable") from None
            if (
                _is_reparse_or_symlink(after)
                or not stat.S_ISREG(after.st_mode)
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                or len(content) != after.st_size
            ):
                raise I15SourceIdentityError("source_file_changed_during_read")
            return content
        if not stat.S_ISDIR(before.st_mode):
            raise I15SourceIdentityError("source_parent_not_directory")
    raise I15SourceIdentityError("source_file_unavailable")


def discover_i15_source_files(source_root: Union[Path, str]) -> Tuple[str, ...]:
    """Return every Python source importable from ``backtrader_runtime``.

    Every Python source file is inventoried exactly. Current-interpreter
    bytecode caches are accepted only when their executable code matches the
    corresponding source; supervised workers additionally bypass checkout
    caches and compile sealed source directly.
    """

    root = Path(source_root)
    if not root.is_absolute():
        raise I15SourceIdentityError("source_root_invalid")
    package_relative = _safe_relative_source_path(I15_SOURCE_PACKAGE_RELATIVE_PATH)
    assert package_relative is not None
    package_root = root.joinpath(*package_relative.parts)
    package_stat = _lstat(package_root, missing_reason="source_root_unavailable")
    if _is_reparse_or_symlink(package_stat) or not stat.S_ISDIR(package_stat.st_mode):
        raise I15SourceIdentityError("source_root_invalid")

    excluded = set(I15_EXCLUDED_SOURCE_PIN_PATHS)
    discovered = []
    pyc_paths = []
    stack = [(package_root, I15_SOURCE_PACKAGE_RELATIVE_PATH)]
    while stack:
        directory, relative_directory = stack.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError:
            raise I15SourceIdentityError("source_directory_unavailable") from None
        for entry in entries:
            relative = relative_directory + "/" + entry.name
            try:
                details = entry.stat(follow_symlinks=False)
            except OSError:
                raise I15SourceIdentityError("source_file_unavailable") from None
            if _is_reparse_or_symlink(details):
                raise I15SourceIdentityError("source_path_reparse_point")
            if stat.S_ISDIR(details.st_mode):
                stack.append((Path(entry.path), relative))
            elif stat.S_ISREG(details.st_mode):
                if entry.name.casefold().endswith((".pyd", ".so", ".dll", ".dylib", ".pyo")):
                    raise I15SourceIdentityError("source_native_module_invalid")
                if entry.name.endswith(".pyc"):
                    if "__pycache__" not in relative.split("/")[:-1]:
                        raise I15SourceIdentityError("source_pyc_cache_invalid")
                    pyc_paths.append(relative)
                if entry.name.endswith(".py") and relative not in excluded:
                    discovered.append(relative)
            else:
                raise I15SourceIdentityError("source_file_not_regular")
    if not discovered:
        raise I15SourceIdentityError("source_file_set_empty")
    _validate_current_bytecode_caches(root, package_root, discovered, pyc_paths)
    return tuple(sorted(discovered))


def _validate_current_bytecode_caches(
    root: Path, package_root: Path, source_paths: list[str], pyc_paths: list[str]
) -> None:
    """Require every bytecode file this interpreter could load to match source."""

    if not pyc_paths:
        return
    try:
        from .ctp_artifact_provenance import _validate_pyc_cache
    except Exception:
        raise I15SourceIdentityError("source_pyc_validator_unavailable") from None
    bytecode_sources = set(source_paths)
    for relative in I15_EXCLUDED_SOURCE_PIN_PATHS:
        path = root.joinpath(*PurePosixPath(relative).parts)
        try:
            details = os.lstat(path)
        except OSError:
            continue
        if _is_reparse_or_symlink(details) or not stat.S_ISREG(details.st_mode):
            raise I15SourceIdentityError("source_path_reparse_point")
        bytecode_sources.add(relative)
    for relative in pyc_paths:
        cache_path = root.joinpath(*PurePosixPath(relative).parts)
        try:
            content = _read_regular_file(root, PurePosixPath(relative))
        except I15SourceIdentityError:
            raise
        if content[:4] != importlib.util.MAGIC_NUMBER:
            # CPython ignores caches compiled for a different bytecode version.
            continue
        try:
            _validate_pyc_cache(cache_path, package_root, root, bytecode_sources)
        except Exception:
            raise I15SourceIdentityError("source_pyc_cache_invalid") from None


def verify_i15_source_identity(
    source_root: Union[Path, str], *, expected_manifest_sha256: object
) -> I15SourceIdentityBinding:
    """Verify exact package Python inventory, content hashes, and manifest pin."""

    if type(expected_manifest_sha256) is not str or not _SHA256_RE.fullmatch(
        expected_manifest_sha256
    ):
        raise I15SourceIdentityError("source_pin_unset")
    root = Path(source_root)
    if not root.is_absolute():
        raise I15SourceIdentityError("source_root_invalid")
    manifest_relative = _safe_relative_source_path(I15_SOURCE_MANIFEST_RELATIVE_PATH)
    assert manifest_relative is not None
    raw_manifest = _read_regular_file(root, manifest_relative)
    manifest_sha256 = hashlib.sha256(raw_manifest).hexdigest()
    if not hmac.compare_digest(manifest_sha256, expected_manifest_sha256):
        raise I15SourceIdentityError("source_manifest_digest_mismatch")
    try:
        manifest = json.loads(raw_manifest.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise I15SourceIdentityError("source_manifest_invalid") from None
    if type(manifest) is not dict or set(manifest) != {"files", "schema"}:
        raise I15SourceIdentityError("source_manifest_invalid")
    if manifest["schema"] != I15_SOURCE_MANIFEST_SCHEMA or type(manifest["files"]) is not list:
        raise I15SourceIdentityError("source_manifest_invalid")

    actual_paths = set(discover_i15_source_files(root))
    manifest_paths = set()
    for row in manifest["files"]:
        if type(row) is not dict or set(row) != {"path", "sha256"}:
            raise I15SourceIdentityError("source_manifest_invalid")
        relative = _safe_relative_source_path(row["path"])
        digest = row["sha256"]
        if (
            relative is None
            or type(digest) is not str
            or not _SHA256_RE.fullmatch(digest)
            or row["path"] in manifest_paths
        ):
            raise I15SourceIdentityError("source_manifest_invalid")
        if row["path"] not in actual_paths:
            raise I15SourceIdentityError("source_manifest_file_set_mismatch")
        manifest_paths.add(row["path"])
        content = _read_regular_file(root, relative)
        if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), digest):
            raise I15SourceIdentityError("source_file_digest_mismatch")
    if manifest_paths != actual_paths:
        raise I15SourceIdentityError("source_manifest_file_set_mismatch")
    return I15SourceIdentityBinding(manifest_sha256, len(manifest_paths))


def render_i15_source_verifier_bootstrap(
    *,
    source_root: Union[Path, str],
    expected_manifest_sha256: str,
    cache_prefix: Union[Path, str],
    site_packages_root: Union[Path, str],
) -> str:
    """Render a stdlib-only source verifier and source-only import guard.

    The returned code is executed before importing any ``backtrader_runtime``
    module in the metadata Job and worker. It hashes the full package inventory,
    validates the isolated pycache prefix, and compiles sealed source bytes
    directly on import so checkout bytecode is not executable in those jobs.
    """

    if not _SHA256_RE.fullmatch(expected_manifest_sha256):
        raise I15SourceIdentityError("source_pin_unset")
    root = Path(source_root)
    if not root.is_absolute():
        raise I15SourceIdentityError("source_root_invalid")
    cache_root = Path(cache_prefix)
    if not cache_root.is_absolute() or os.path.lexists(cache_root):
        raise I15SourceIdentityError("source_cache_prefix_invalid")
    site_root = Path(site_packages_root)
    if not site_root.is_absolute():
        raise I15SourceIdentityError("source_install_root_invalid")
    expected_files = discover_i15_source_files(root)
    return (
        "import hashlib, hmac, importlib.abc, importlib.util, json, os, pathlib, stat, sys\n"
        f"_I15_SOURCE_ROOT = pathlib.Path({os.fspath(root)!r})\n"
        f"_I15_SOURCE_CACHE_PREFIX = pathlib.Path({os.fspath(cache_root)!r})\n"
        f"_I15_FIXED_SITE_PACKAGES = pathlib.Path({os.fspath(site_root)!r})\n"
        f"_I15_SOURCE_EXPECTED = {expected_manifest_sha256!r}\n"
        f"_I15_SOURCE_MANIFEST_REL = {I15_SOURCE_MANIFEST_RELATIVE_PATH!r}\n"
        f"_I15_SOURCE_SCHEMA = {I15_SOURCE_MANIFEST_SCHEMA!r}\n"
        f"_I15_SOURCE_PACKAGE = {I15_SOURCE_PACKAGE_RELATIVE_PATH!r}\n"
        "_I15_SOURCE_PIN_MODULE = 'backtrader_runtime.ctp_i15_source_identity_pin'\n"
        f"_I15_SOURCE_EXCLUDED = {I15_EXCLUDED_SOURCE_PIN_PATHS!r}\n"
        f"_I15_SOURCE_FILES = {expected_files!r}\n"
        "_I15_SOURCE_FILE_HASHES = {}\n"
        "_I15_SOURCE_STARTUP_VALIDATED = False\n"
        "def _i15_source_bad_stat(item):\n"
        "    return stat.S_ISLNK(item.st_mode) or bool(getattr(item, 'st_file_attributes', 0) & 0x400)\n"
        "def _i15_startup_clean():\n"
        "    if sys.flags.isolated != 1 or sys.flags.no_site != 1 or not sys.dont_write_bytecode: return False\n"
        "    if 'sitecustomize' in sys.modules or 'usercustomize' in sys.modules: return False\n"
        "    for name in sys.modules:\n"
        "        if name == 'backtrader' or name.startswith('backtrader.') or name == 'backtrader_runtime' or name.startswith('backtrader_runtime.'): return False\n"
        "    return True\n"
        "def _i15_fixed_install_root_valid():\n"
        "    try:\n"
        "        if not _I15_FIXED_SITE_PACKAGES.is_absolute(): return False\n"
        "        current = pathlib.Path(_I15_FIXED_SITE_PACKAGES.anchor)\n"
        "        for part in _I15_FIXED_SITE_PACKAGES.parts[1:]:\n"
        "            current = current / part\n"
        "            item = os.lstat(current)\n"
        "            if _i15_source_bad_stat(item) or not stat.S_ISDIR(item.st_mode): return False\n"
        "        return True\n"
        "    except Exception:\n"
        "        return False\n"
        "def _i15_add_fixed_install_root():\n"
        "    if not _i15_fixed_install_root_valid(): return False\n"
        "    expected = os.path.normcase(os.path.abspath(_I15_FIXED_SITE_PACKAGES))\n"
        "    for item in sys.path:\n"
        "        if type(item) is str and os.path.normcase(os.path.abspath(item or os.getcwd())) == expected: return False\n"
        "    sys.path.append(str(_I15_FIXED_SITE_PACKAGES))\n"
        "    return sum(1 for item in sys.path if type(item) is str and os.path.normcase(os.path.abspath(item or os.getcwd())) == expected) == 1\n"
        "def _i15_bind_fixed_artifact_install_root():\n"
        "    if not _i15_fixed_install_root_valid(): return False\n"
        "    expected = os.path.normcase(os.path.abspath(_I15_FIXED_SITE_PACKAGES))\n"
        "    if sum(1 for item in sys.path if type(item) is str and os.path.normcase(os.path.abspath(item or os.getcwd())) == expected) != 1: return False\n"
        "    try:\n"
        "        import backtrader_runtime.ctp_artifact_provenance as provenance\n"
        "        import backtrader_runtime.capability_imports as capability_imports\n"
        "        if type(getattr(provenance, '__loader__', None)) is not _I15SealedSourceLoader: return False\n"
        "        if type(getattr(capability_imports, '__loader__', None)) is not _I15SealedSourceLoader: return False\n"
        "        def _fixed_roots():\n"
        "            if not _i15_fixed_install_root_valid(): raise RuntimeError('i15 install root changed')\n"
        "            if sum(1 for item in sys.path if type(item) is str and os.path.normcase(os.path.abspath(item or os.getcwd())) == expected) != 1: raise RuntimeError('i15 install root not bound')\n"
        "            return (_I15_FIXED_SITE_PACKAGES.resolve(strict=True),)\n"
        "        def _fixed_capability_roots():\n"
        "            if not _i15_fixed_install_root_valid(): raise RuntimeError('i15 install root changed')\n"
        "            if sum(1 for item in sys.path if type(item) is str and os.path.normcase(os.path.abspath(item or os.getcwd())) == expected) != 1: raise RuntimeError('i15 install root not bound')\n"
        "            return frozenset((_I15_FIXED_SITE_PACKAGES.resolve(strict=True),))\n"
        "        provenance._interpreter_install_roots = _fixed_roots\n"
        "        capability_imports._interpreter_install_roots = _fixed_capability_roots\n"
        "        return provenance._interpreter_install_roots() == (_I15_FIXED_SITE_PACKAGES.resolve(strict=True),) and capability_imports._interpreter_install_roots() == frozenset((_I15_FIXED_SITE_PACKAGES.resolve(strict=True),))\n"
        "    except Exception:\n"
        "        return False\n"
        "def _i15_source_read(relative):\n"
        "    current = _I15_SOURCE_ROOT\n"
        "    root_stat = os.lstat(current)\n"
        "    if _i15_source_bad_stat(root_stat) or not stat.S_ISDIR(root_stat.st_mode): return None\n"
        "    parts = pathlib.PurePosixPath(relative).parts\n"
        "    for index, component in enumerate(parts):\n"
        "        current = current / component\n"
        "        before = os.lstat(current)\n"
        "        if _i15_source_bad_stat(before): return None\n"
        "        if index < len(parts) - 1:\n"
        "            if not stat.S_ISDIR(before.st_mode): return None\n"
        "            continue\n"
        "        if not stat.S_ISREG(before.st_mode): return None\n"
        "        content = current.read_bytes()\n"
        "        after = os.lstat(current)\n"
        "        if _i15_source_bad_stat(after) or not stat.S_ISREG(after.st_mode): return None\n"
        "        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns): return None\n"
        "        if len(content) != after.st_size: return None\n"
        "        return content\n"
        "    return None\n"
        "def _i15_source_discover():\n"
        "    package_root = _I15_SOURCE_ROOT.joinpath(*pathlib.PurePosixPath(_I15_SOURCE_PACKAGE).parts)\n"
        "    package_stat = os.lstat(package_root)\n"
        "    if _i15_source_bad_stat(package_stat) or not stat.S_ISDIR(package_stat.st_mode): raise ValueError()\n"
        "    found = []\n"
        "    stack = [(package_root, _I15_SOURCE_PACKAGE)]\n"
        "    while stack:\n"
        "        directory, relative_directory = stack.pop()\n"
        "        with os.scandir(directory) as iterator: entries = sorted(iterator, key=lambda item: item.name)\n"
        "        for entry in entries:\n"
        "            relative = relative_directory + '/' + entry.name\n"
        "            details = entry.stat(follow_symlinks=False)\n"
        "            if _i15_source_bad_stat(details): raise ValueError()\n"
        "            if stat.S_ISDIR(details.st_mode): stack.append((pathlib.Path(entry.path), relative))\n"
        "            elif stat.S_ISREG(details.st_mode):\n"
        "                if entry.name.casefold().endswith(('.pyd', '.so', '.dll', '.dylib', '.pyo')): raise ValueError()\n"
        "                if entry.name.endswith('.pyc') and '__pycache__' not in relative.split('/')[:-1]: raise ValueError()\n"
        "                if entry.name.endswith('.py') and relative not in _I15_SOURCE_EXCLUDED: found.append(relative)\n"
        "            else: raise ValueError()\n"
        "    return tuple(sorted(found))\n"
        "def _verify_i15_source_identity():\n"
        "    global _I15_SOURCE_STARTUP_VALIDATED\n"
        "    _I15_SOURCE_FILE_HASHES.clear()\n"
        "    try:\n"
        "        if not _I15_SOURCE_STARTUP_VALIDATED and not _i15_startup_clean(): return False\n"
        "        if type(sys.pycache_prefix) is not str or os.path.normcase(os.path.abspath(sys.pycache_prefix)) != os.path.normcase(os.path.abspath(_I15_SOURCE_CACHE_PREFIX)) or os.path.lexists(_I15_SOURCE_CACHE_PREFIX): return False\n"
        "        if _i15_source_discover() != _I15_SOURCE_FILES: return False\n"
        "        raw = _i15_source_read(_I15_SOURCE_MANIFEST_REL)\n"
        "        if raw is None or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), _I15_SOURCE_EXPECTED): return False\n"
        "        manifest = json.loads(raw.decode('utf-8'))\n"
        "        if type(manifest) is not dict or set(manifest) != {'files', 'schema'}: return False\n"
        "        if manifest['schema'] != _I15_SOURCE_SCHEMA or type(manifest['files']) is not list: return False\n"
        "        seen = set()\n"
        "        for row in manifest['files']:\n"
        "            if type(row) is not dict or set(row) != {'path', 'sha256'}: return False\n"
        "            name, digest = row['path'], row['sha256']\n"
        "            if type(name) is not str or '\\\\' in name: return False\n"
        "            relative = pathlib.PurePosixPath(name)\n"
        "            if relative.is_absolute() or any(part in {'', '.', '..'} for part in relative.parts): return False\n"
        "            if type(digest) is not str or len(digest) != 64 or any(ch not in '0123456789abcdef' for ch in digest): return False\n"
        "            if name in seen or name not in _I15_SOURCE_FILES: return False\n"
        "            seen.add(name)\n"
        "            content = _i15_source_read(name)\n"
        "            if content is None or not hmac.compare_digest(hashlib.sha256(content).hexdigest(), digest): return False\n"
        "            _I15_SOURCE_FILE_HASHES[name] = digest\n"
        "        if seen != set(_I15_SOURCE_FILES): return False\n"
        "        _I15_SOURCE_STARTUP_VALIDATED = True\n"
        "        return True\n"
        "    except Exception:\n"
        "        _I15_SOURCE_FILE_HASHES.clear()\n"
        "        return False\n"
        "class _I15SealedSourceLoader(importlib.abc.Loader):\n"
        "    def __init__(self, fullname, relative, is_package): self.fullname, self.relative, self.is_package = fullname, relative, is_package\n"
        "    def create_module(self, spec): return None\n"
        "    def exec_module(self, module):\n"
        "        expected = _I15_SOURCE_FILE_HASHES.get(self.relative)\n"
        "        content = _i15_source_read(self.relative)\n"
        "        if expected is None or content is None or not hmac.compare_digest(hashlib.sha256(content).hexdigest(), expected): raise ImportError('i15 source identity changed')\n"
        "        filename = str(_I15_SOURCE_ROOT.joinpath(*pathlib.PurePosixPath(self.relative).parts))\n"
        "        module.__file__ = filename\n"
        "        module.__cached__ = None\n"
        "        module.__loader__ = self\n"
        "        if self.is_package: module.__path__ = [str(pathlib.Path(filename).parent)]\n"
        "        code = compile(content, filename, 'exec', dont_inherit=True)\n"
        "        exec(code, module.__dict__)\n"
        "class _I15SealedSourceFinder(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname == 'backtrader' or fullname.startswith('backtrader.'):\n"
        "            raise ModuleNotFoundError('unsealed backtrader import: ' + fullname)\n"
        "        if fullname != 'backtrader_runtime' and not fullname.startswith('backtrader_runtime.'): return None\n"
        "        stem = fullname.replace('.', '/')\n"
        "        package_relative = stem + '/__init__.py'\n"
        "        module_relative = stem + '.py'\n"
        "        if package_relative in _I15_SOURCE_FILE_HASHES:\n"
        "            relative, is_package = package_relative, True\n"
        "        elif module_relative in _I15_SOURCE_FILE_HASHES:\n"
        "            relative, is_package = module_relative, False\n"
        "        else: raise ModuleNotFoundError('unsealed backtrader_runtime import: ' + fullname)\n"
        "        loader = _I15SealedSourceLoader(fullname, relative, is_package)\n"
        "        return importlib.util.spec_from_loader(fullname, loader, is_package=is_package)\n"
        "def _install_i15_sealed_importer():\n"
        "    sys.meta_path.insert(0, _I15SealedSourceFinder())\n"
        "def _verify_i15_import_origins():\n"
        "    try:\n"
        "        if sys.flags.isolated != 1 or sys.flags.no_site != 1 or not sys.dont_write_bytecode: return False\n"
        "        if 'sitecustomize' in sys.modules or 'usercustomize' in sys.modules: return False\n"
        "        if not _i15_fixed_install_root_valid(): return False\n"
        "        _i15_expected_site_root = os.path.normcase(os.path.abspath(_I15_FIXED_SITE_PACKAGES))\n"
        "        if sum(1 for item in sys.path if type(item) is str and os.path.normcase(os.path.abspath(item or os.getcwd())) == _i15_expected_site_root) != 1: return False\n"
        "        provenance = sys.modules.get('backtrader_runtime.ctp_artifact_provenance')\n"
        "        capability_imports = sys.modules.get('backtrader_runtime.capability_imports')\n"
        "        if provenance is None or capability_imports is None: return False\n"
        "        if provenance._interpreter_install_roots() != (_I15_FIXED_SITE_PACKAGES.resolve(strict=True),): return False\n"
        "        if capability_imports._interpreter_install_roots() != frozenset((_I15_FIXED_SITE_PACKAGES.resolve(strict=True),)): return False\n"
        "        if os.path.lexists(_I15_SOURCE_CACHE_PREFIX): return False\n"
        "        for name, module in tuple(sys.modules.items()):\n"
        "            if name == 'backtrader' or name.startswith('backtrader.'): return False\n"
        "            if name != 'backtrader_runtime' and not name.startswith('backtrader_runtime.'): continue\n"
        "            if name == _I15_SOURCE_PIN_MODULE:\n"
        "                if getattr(module, '__file__', None) is not None or getattr(module, 'I15_REVIEWED_SOURCE_MANIFEST_SHA256', None) != _I15_SOURCE_EXPECTED: return False\n"
        "                continue\n"
        "            if type(getattr(module, '__loader__', None)) is not _I15SealedSourceLoader: return False\n"
        "            relative = pathlib.Path(module.__file__).relative_to(_I15_SOURCE_ROOT).as_posix()\n"
        "            if relative not in _I15_SOURCE_FILE_HASHES: return False\n"
        "            expected_path = _I15_SOURCE_ROOT.joinpath(*pathlib.PurePosixPath(relative).parts)\n"
        "            if os.path.normcase(os.path.abspath(module.__file__)) != os.path.normcase(os.path.abspath(expected_path)): return False\n"
        "            if getattr(module, '__cached__', None) is not None: return False\n"
        "            if relative.endswith('/__init__.py'):\n"
        "                expected_package = os.path.normcase(os.path.abspath(expected_path.parent))\n"
        "                paths = tuple(os.path.normcase(os.path.abspath(item)) for item in getattr(module, '__path__', ()))\n"
        "                if paths != (expected_package,): return False\n"
        "        return 'backtrader_runtime' in sys.modules\n"
        "    except Exception:\n"
        "        return False\n"
    )


__all__ = [
    "I15_EXCLUDED_SOURCE_PIN_PATHS",
    "I15_SOURCE_MANIFEST_ENV",
    "I15_SOURCE_MANIFEST_RELATIVE_PATH",
    "I15_SOURCE_MANIFEST_SCHEMA",
    "I15SourceIdentityBinding",
    "I15SourceIdentityError",
    "discover_i15_source_files",
    "render_i15_source_verifier_bootstrap",
    "verify_i15_source_identity",
]
