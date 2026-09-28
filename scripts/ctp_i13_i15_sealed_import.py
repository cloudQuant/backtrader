# ruff: noqa: E402
"""Offline source-only import primitives for the I13/I15 launcher review.

This module is deliberately not an operator entry point.  It does not read a
runtime config, inspect a marker, create a Job, contact a provider, or invoke a
candidate supervisor.  A future captured ``python -I -S -B -c`` bootstrap may
use these primitives only after an external trust descriptor has supplied the
manifest and interpreter pins.  The current I13/I15 pins are unset/zero, so
there is no production trust descriptor that can successfully seal this
checkout. This offline slice targets only the fixed CPython 3.11.5 interpreter;
it is not part of the repository's general Python 3.8+ runtime or CLI.

The finder owns the complete ``backtrader_runtime`` namespace.  It never lets
PathFinder retry an unlisted runtime name, explicitly rejects ``backtrader``
and non-stdlib imports, and compiles only the exact source bytes it hashes.
The standard-library roots passed by a caller must themselves come from an
independently pinned interpreter descriptor; merely passing ``sys.path`` is
not proof of that fact.

Only standard-library module objects captured by this bootstrap or exact source
and extension entries in the verified runtime closure are in the import
closure. New stdlib names fail closed unless the runtime seal supplies their
exact origin and kind; no general ``PathFinder`` fallback is permitted.

The Windows source lease below is integrated with this offline manifest sealer
and source loader. It opens every path component with ``OPEN_REPARSE_POINT``,
retains handles that deny write/delete sharing, and reopens paths to compare
volume/file IDs before reading. The returned seal owns the lease until explicit
close. The parent descriptor, PyYAML/SDK artifacts, fixed stdlib closure, and
actual Windows launch path still require independent pins and review.
"""

import sys


# Exact startup image for the pinned Windows CPython 3.11.5 build used by this
# offline slice.  A name allowlist (for example ``sys.stdlib_module_names``)
# alone is insufficient: an arbitrary preloaded ``sys.modules['json']`` would
# otherwise survive the helper imports below.  The external interpreter and
# stdlib still need an independently reviewed pin; this list cannot establish
# that trust root by itself.
_STARTUP_MODULE_NAMES = frozenset(
    {
        "__main__",
        "_abc",
        "_codecs",
        "_codecs_cn",
        "_frozen_importlib",
        "_frozen_importlib_external",
        "_imp",
        "_io",
        "_multibytecodec",
        "_signal",
        "_thread",
        "_warnings",
        "_weakref",
        "abc",
        "builtins",
        "codecs",
        "encodings",
        "encodings.aliases",
        "encodings.gbk",
        "encodings.utf_8",
        "io",
        "marshal",
        "nt",
        "sys",
        "time",
        "winreg",
        "zipimport",
    }
)
_BUILTIN_STARTUP_MODULES = frozenset(
    {
        "_abc",
        "_codecs",
        "_codecs_cn",
        "_imp",
        "_io",
        "_multibytecodec",
        "_signal",
        "_thread",
        "_warnings",
        "_weakref",
        "builtins",
        "marshal",
        "nt",
        "sys",
        "time",
        "winreg",
    }
)
_FROZEN_STARTUP_MODULES = frozenset(
    {"_frozen_importlib", "_frozen_importlib_external", "abc", "codecs", "io", "zipimport"}
)
_SOURCE_STARTUP_MODULES = frozenset(
    {"encodings", "encodings.aliases", "encodings.gbk", "encodings.utf_8"}
)
_MODULE_NAME_ALIASES = {
    "_collections_abc": "collections.abc",
    "_io": "io",
    "os.path": "ntpath",
}
_MODULE_SPEC_NAME_ALIASES = {
    "importlib._bootstrap": "_frozen_importlib",
    "importlib._bootstrap_external": "_frozen_importlib_external",
    "os.path": "ntpath",
}


def _startup_fail(reason):
    raise RuntimeError(reason)


def _default_filefinder_loader_details(external):
    categories = (
        (external.ExtensionFileLoader, external.EXTENSION_SUFFIXES),
        (external.SourceFileLoader, external.SOURCE_SUFFIXES),
        (external.SourcelessFileLoader, external.BYTECODE_SUFFIXES),
    )
    return tuple((suffix, loader) for loader, suffixes in categories for suffix in suffixes)


def _filefinder_is_default(finder, external, path):
    if type(finder) is not external.FileFinder or finder.path != path:
        return False
    expected = _default_filefinder_loader_details(external)
    actual = finder._loaders
    if type(actual) is not list or len(actual) != len(expected):
        return False
    if not all(
        type(item) is tuple
        and len(item) == 2
        and item[0] == expected[index][0]
        and item[1] is expected[index][1]
        for index, item in enumerate(actual)
    ):
        return False
    try:
        nt = sys.modules["nt"]
        details = nt.stat(path)
        names = nt.listdir(path)
    except (OSError, KeyError):
        return False
    cache = finder._path_cache
    if type(cache) is not set or any(type(name) is not str for name in cache):
        return False
    return finder._path_mtime == details.st_mtime and cache == set(names)


def _module_matches_startup_origin(name, module, *, external, frozen, stdlib_root):
    expected_module_name = _MODULE_NAME_ALIASES.get(name, name)
    if type(module) is not type(sys) or getattr(module, "__name__", None) != expected_module_name:
        return False
    if name == "__main__":
        return getattr(module, "__spec__", None) is None
    spec = getattr(module, "__spec__", None)
    if spec is None or getattr(spec, "name", None) != name:
        return False
    if name in _BUILTIN_STARTUP_MODULES:
        return (
            getattr(spec, "origin", None) == "built-in"
            and getattr(spec, "loader", None) is frozen.BuiltinImporter
            and getattr(module, "__loader__", None) is frozen.BuiltinImporter
        )
    if name in _FROZEN_STARTUP_MODULES:
        return (
            getattr(spec, "origin", None) == "frozen"
            and getattr(spec, "loader", None) is frozen.FrozenImporter
            and getattr(module, "__loader__", None) is frozen.FrozenImporter
        )
    if name not in _SOURCE_STARTUP_MODULES:
        return False
    relative = name.replace(".", "\\")
    source_name = "__init__.py" if name == "encodings" else relative + ".py"
    expected = (
        stdlib_root + "\\" + relative + "\\" + source_name
        if name == "encodings"
        else stdlib_root + "\\" + source_name
    )
    loader = getattr(spec, "loader", None)
    return (
        getattr(spec, "origin", None) == expected
        and getattr(module, "__file__", None) == expected
        and type(loader) is external.SourceFileLoader
        and getattr(loader, "name", None) == name
        and getattr(loader, "path", None) == expected
        and getattr(module, "__loader__", None) is loader
    )


def _check_initial_importer_cache(*, external, zipimport):
    cache = sys.path_importer_cache
    if type(cache) is not dict or len(sys.path) != 4:
        _startup_fail("bootstrap_importer_cache_invalid")
    encodings_path = sys.path[2] + "\\encodings"
    expected_keys = {sys.path[0], sys.path[1], sys.path[2], encodings_path}
    if set(cache) != expected_keys:
        _startup_fail("bootstrap_importer_cache_invalid")
    zip_path = sys.path[0]
    zip_importer = cache[zip_path]
    try:
        sys.modules["nt"].stat(zip_path)
    except OSError:
        if zip_importer is not None:
            _startup_fail("bootstrap_importer_cache_invalid")
    else:
        if (
            type(zip_importer) is not zipimport.zipimporter
            or getattr(zip_importer, "archive", None) != zip_path
            or getattr(zip_importer, "prefix", None) != ""
        ):
            _startup_fail("bootstrap_importer_cache_invalid")
    for path in expected_keys - {zip_path}:
        if not _filefinder_is_default(cache[path], external, path):
            _startup_fail("bootstrap_importer_cache_invalid")


def _check_initial_import_state():
    """Reject any process that differs from the pinned 3.11.5 startup image."""

    frozen = sys.modules.get("_frozen_importlib")
    external = sys.modules.get("_frozen_importlib_external")
    zipimport = sys.modules.get("zipimport")
    if frozen is None or external is None or zipimport is None:
        raise RuntimeError("bootstrap_import_state_invalid")

    if sys.platform != "win32" or sys.version_info[:3] != (3, 11, 5):
        _startup_fail("bootstrap_runtime_baseline_invalid")
    if type(sys.modules) is not dict or frozenset(sys.modules) != _STARTUP_MODULE_NAMES:
        _startup_fail("bootstrap_preloaded_module_set_invalid")
    for name, module in sys.modules.items():
        if not _module_matches_startup_origin(
            name,
            module,
            external=external,
            frozen=frozen,
            stdlib_root=sys.path[2],
        ):
            _startup_fail("bootstrap_preloaded_module_invalid")

    expected_meta_path = [frozen.BuiltinImporter, frozen.FrozenImporter, external.PathFinder]
    if sys.meta_path != expected_meta_path:
        raise RuntimeError("bootstrap_meta_path_invalid")

    prefix = sys.pycache_prefix
    prefix_absolute = type(prefix) is str and (
        (len(prefix) >= 3 and prefix[1] == ":" and prefix[2] in "\\/") or prefix.startswith("\\\\")
    )
    if (
        not sys.flags.isolated
        or not sys.flags.no_site
        or not sys.dont_write_bytecode
        or not prefix_absolute
    ):
        raise RuntimeError("bootstrap_interpreter_flags_invalid")
    try:
        sys.modules["nt"].stat(prefix)
    except OSError:
        pass
    else:
        _startup_fail("bootstrap_pycache_prefix_not_fresh")

    hooks = sys.path_hooks
    if len(hooks) == 2:
        hook = hooks[1]
        try:
            closure = tuple(cell.cell_contents for cell in hook.__closure__ or ())
        except (AttributeError, ValueError):
            closure = ()
        expected_loader_details = (
            (external.ExtensionFileLoader, list(external.EXTENSION_SUFFIXES)),
            (external.SourceFileLoader, list(external.SOURCE_SUFFIXES)),
            (external.SourcelessFileLoader, list(external.BYTECODE_SUFFIXES)),
        )
        hook_is_default = (
            len(closure) == 2
            and external is not None
            and closure[0] is external.FileFinder
            and type(closure[1]) is tuple
            and len(closure[1]) == len(expected_loader_details)
            and all(
                actual[0] is expected[0] and actual[1] == expected[1]
                for actual, expected in zip(closure[1], expected_loader_details)
            )
        )
    else:
        hook_is_default = False
    if (
        len(hooks) != 2
        or hooks[0] is not zipimport.zipimporter
        or getattr(hooks[1], "__module__", None) != "_frozen_importlib_external"
        or getattr(hooks[1], "__qualname__", None)
        != "FileFinder.path_hook.<locals>.path_hook_for_FileFinder"
        or not hook_is_default
    ):
        raise RuntimeError("bootstrap_path_hooks_invalid")

    _check_initial_importer_cache(external=external, zipimport=zipimport)

    blocked = ("backtrader", "backtrader_runtime", "sitecustomize", "usercustomize")
    for name in tuple(sys.modules):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in blocked):
            raise RuntimeError("bootstrap_preloaded_module_invalid")
        root = name.partition(".")[0]
        if (
            root != "__main__"
            and root not in sys.stdlib_module_names
            and root not in sys.builtin_module_names
        ):
            raise RuntimeError("bootstrap_preloaded_nonstdlib_module")


_check_initial_import_state()

# Preserve the validated interpreter-owned objects before importing any helper
# modules.  The snapshots let later public calls reject replacement modules or
# importer-cache objects even after this file has loaded its stdlib helpers.
_INITIAL_MODULE_OBJECTS = dict(sys.modules)
_INITIAL_IMPORTER_CACHE = dict(sys.path_importer_cache)

import hashlib
import hmac
import importlib.abc
import importlib.machinery  # noqa: F401 - preloaded for the sealed dependency helper
import importlib.util
import ast  # noqa: F401 - preloaded for the appended captured parent launcher
import base64  # noqa: F401 - used by the fixed child bootstrap payload
import csv  # noqa: F401 - preloaded for the sealed dependency helper
import ctypes
import json
import io  # noqa: F401 - preloaded for the sealed dependency helper
import ntpath  # noqa: F401 - preloaded for the appended captured parent launcher
import os
import re
import stat
import threading  # noqa: F401 - preloaded for the sealed dependency helper
import zlib  # noqa: F401 - used by the fixed child bootstrap payload
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Mapping, Optional, Sequence


_BOOTSTRAP_MODULE_OBJECTS = dict(sys.modules)
_BOOTSTRAP_IMPORTER_CACHE = dict(sys.path_importer_cache)
_BOOTSTRAP_META_PATH = tuple(sys.meta_path)
_BOOTSTRAP_PATH_HOOKS = tuple(sys.path_hooks)
_BOOTSTRAP_PATHS = tuple(sys.path)
_BOOTSTRAP_PYCACHE_PREFIX = sys.pycache_prefix


def _path_is_beneath(path: object, root: str) -> bool:
    if type(path) is not str:
        return False
    normalized_path = os.path.normcase(os.path.abspath(path))
    normalized_root = os.path.normcase(os.path.abspath(root)).rstrip("\\/")
    return normalized_path.startswith(normalized_root + os.sep)


def _path_is_root_or_beneath(path: object, root: str) -> bool:
    if type(path) is not str:
        return False
    normalized_path = os.path.normcase(os.path.abspath(path))
    normalized_root = os.path.normcase(os.path.abspath(root)).rstrip("\\/")
    return normalized_path == normalized_root or normalized_path.startswith(
        normalized_root + os.sep
    )


def _module_has_pinned_kind(name: str, module: object) -> bool:
    """Check a post-bootstrap module's kind and origin, without trusting its name."""

    expected_module_name = _MODULE_NAME_ALIASES.get(name, name)
    if type(module) is not type(sys) or getattr(module, "__name__", None) != expected_module_name:
        return False
    spec = getattr(module, "__spec__", None)
    expected_spec_name = _MODULE_SPEC_NAME_ALIASES.get(name, name)
    if spec is None or getattr(spec, "name", None) != expected_spec_name:
        return False
    frozen = sys.modules.get("_frozen_importlib")
    external = sys.modules.get("_frozen_importlib_external")
    origin = getattr(spec, "origin", None)
    loader = getattr(spec, "loader", None)
    if origin == "built-in":
        return loader is frozen.BuiltinImporter and getattr(module, "__loader__", None) is loader
    if origin == "frozen":
        return loader is frozen.FrozenImporter and getattr(module, "__loader__", None) is loader
    root = name.partition(".")[0]
    if root not in sys.stdlib_module_names and root not in sys.builtin_module_names:
        return False
    if type(loader) is external.SourceFileLoader:
        return (
            type(origin) is str
            and origin.endswith(".py")
            and _path_is_beneath(origin, sys.path[2])
            and getattr(module, "__file__", None) == origin
            and getattr(loader, "name", None) == expected_module_name
            and getattr(loader, "path", None) == origin
            and getattr(module, "__loader__", None) is loader
        )
    zipimport = sys.modules.get("zipimport")
    if zipimport is not None and type(loader) is zipimport.zipimporter:
        archive = getattr(loader, "archive", None)
        return (
            type(origin) is str
            and type(archive) is str
            and archive in _BOOTSTRAP_PATHS
            and origin.lower().endswith(".py")
            and _path_is_beneath(origin, archive)
            and getattr(module, "__file__", None) == origin
            and getattr(module, "__loader__", None) is loader
        )
    if type(loader) is external.ExtensionFileLoader:
        return (
            type(origin) is str
            and origin.lower().endswith(".pyd")
            and any(_path_is_beneath(origin, root_path) for root_path in sys.path[1:3])
            and getattr(module, "__file__", None) == origin
            and getattr(loader, "name", None) == expected_module_name
            and getattr(loader, "path", None) == origin
            and getattr(module, "__loader__", None) is loader
        )
    return False


def _is_bootstrap_typing_alias(name: str, module: object) -> bool:
    return (
        name in {"typing.io", "typing.re"}
        and _BOOTSTRAP_MODULE_OBJECTS.get(name) is module
        and isinstance(module, type)
        and type(module).__name__ == "_DeprecatedType"
        and type(module).__module__ == "typing"
        and getattr(module, "__module__", None) == "typing"
        and getattr(module, "__name__", None) == name
    )


def _check_post_bootstrap_state(seal=None, finder=None):
    """Reject object/cache swaps after helper import and before each load."""

    if type(sys.modules) is not dict or type(sys.path_importer_cache) is not dict:
        raise SealedImportError("bootstrap_import_state_invalid")
    if tuple(sys.path) != _BOOTSTRAP_PATHS:
        raise SealedImportError("sys_path_changed")
    if (
        not sys.flags.isolated
        or not sys.flags.no_site
        or not sys.dont_write_bytecode
        or type(sys.pycache_prefix) is not str
        or not os.path.isabs(sys.pycache_prefix)
        or sys.pycache_prefix != _BOOTSTRAP_PYCACHE_PREFIX
        or os.path.exists(sys.pycache_prefix)
    ):
        raise SealedImportError("bootstrap_interpreter_flags_invalid")
    for name, module in _BOOTSTRAP_MODULE_OBJECTS.items():
        if sys.modules.get(name) is not module:
            raise SealedImportError("bootstrap_module_replaced")
    dependency_modules = tuple(
        (name, module)
        for name, module in sys.modules.items()
        if name.partition(".")[0] in _SEALED_DEPENDENCY_TOP_LEVEL_ROOTS
    )
    dependency_finder = (
        getattr(finder, "_dependency_finder", None)
        if type(finder) is SealedSourceFinder
        else None
    )
    if dependency_modules:
        validator = getattr(dependency_finder, "validate_current", None)
        if not callable(validator):
            raise SealedImportError("bootstrap_dependency_module_invalid")
        try:
            validator()
        except BaseException:
            raise SealedImportError("bootstrap_dependency_seal_invalid") from None
    runtime_stdlib_names = tuple(
        name
        for name in sys.modules
        if type(finder) is SealedSourceFinder
        and name in finder._runtime_stdlib_entries
    )
    if runtime_stdlib_names:
        runtime_seal = finder._runtime_closure
        if runtime_seal is None or runtime_seal is not finder._runtime_closure_identity:
            raise SealedImportError("bootstrap_runtime_closure_invalid")
        validator = getattr(runtime_seal, "verify_current", None)
        if not callable(validator):
            raise SealedImportError("bootstrap_runtime_closure_invalid")
        try:
            validator()
        except BaseException:
            raise SealedImportError("bootstrap_runtime_closure_invalid") from None
    for name, module in sys.modules.items():
        if name == "__main__":
            if type(module) is not type(sys):
                raise SealedImportError("bootstrap_preloaded_module_invalid")
            continue
        if name == "backtrader" or name.startswith("backtrader."):
            raise SealedImportError("unsealed_backtrader_namespace")
        if name in {"sitecustomize", "usercustomize"}:
            raise SealedImportError("site_import_blocked")
        if name == "backtrader_runtime" or name.startswith("backtrader_runtime."):
            if seal is None or finder is None:
                raise SealedImportError("bootstrap_preloaded_module_invalid")
            if (
                type(finder) is not SealedSourceFinder
                or finder._seal is not seal
                or not finder._was_executed_or_in_progress(name, module)
            ):
                raise SealedImportError("bootstrap_runtime_module_invalid")
            module_spec = getattr(module, "__spec__", None)
            loader = getattr(module_spec, "loader", None)
            expected_relatives = {
                name.replace(".", "/") + "/__init__.py",
                name.replace(".", "/") + ".py",
            }
            if (
                type(loader) is not _SealedSourceLoader
                or loader._finder is not finder
                or loader._seal is not seal
                or loader._fullname != name
                or loader._relative not in expected_relatives
                or loader._relative not in seal.files
            ):
                raise SealedImportError("bootstrap_runtime_module_invalid")
            expected_origin = str(seal.source_root.joinpath(*PurePosixPath(loader._relative).parts))
            if getattr(module_spec, "origin", None) != expected_origin:
                raise SealedImportError("bootstrap_runtime_module_invalid")
            continue
        if name.partition(".")[0] in _SEALED_DEPENDENCY_TOP_LEVEL_ROOTS:
            owns_module = getattr(dependency_finder, "owns_module", None)
            if not callable(owns_module):
                raise SealedImportError("bootstrap_dependency_module_invalid")
            try:
                owned = owns_module(name, module)
            except BaseException:
                owned = False
            if owned is not True:
                raise SealedImportError("bootstrap_dependency_module_invalid")
            continue
        if type(finder) is SealedSourceFinder and finder._owns_runtime_stdlib_module(
            name, module
        ):
            continue
        if type(finder) is SealedSourceFinder and finder._owns_fixed_role_module(
            name, module
        ):
            continue
        if type(finder) is SealedSourceFinder and finder._owns_fixed_bootstrap_support(
            name, module
        ):
            continue
        if _is_bootstrap_typing_alias(name, module):
            continue
        if name in _BOOTSTRAP_MODULE_OBJECTS:
            if _BOOTSTRAP_MODULE_OBJECTS[name] is not module:
                raise SealedImportError("bootstrap_module_replaced")
            if any(module is initial for initial in _INITIAL_MODULE_OBJECTS.values()):
                continue
            if not _module_has_pinned_kind(name, module):
                raise SealedImportError("bootstrap_module_origin_invalid")
            continue
        raise SealedImportError("bootstrap_module_outside_snapshot")

    cache = sys.path_importer_cache
    external = sys.modules.get("_frozen_importlib_external")
    zipimport = sys.modules.get("zipimport")
    for key, original in _BOOTSTRAP_IMPORTER_CACHE.items():
        if key not in cache or cache[key] is not original:
            raise SealedImportError("importer_cache_replaced")
    for key, importer in cache.items():
        if type(key) is not str:
            raise SealedImportError("importer_cache_invalid")
        if importer is None:
            if key != _BOOTSTRAP_PATHS[0]:
                raise SealedImportError("importer_cache_invalid")
            continue
        if type(importer) is zipimport.zipimporter:
            if key != _BOOTSTRAP_PATHS[0] or getattr(importer, "archive", None) != key:
                raise SealedImportError("importer_cache_invalid")
            continue
        if not any(_path_is_root_or_beneath(key, root_path) for root_path in _BOOTSTRAP_PATHS[1:]):
            raise SealedImportError("importer_cache_outside_stdlib")
        if not _filefinder_is_default(importer, external, key):
            raise SealedImportError("importer_cache_invalid")

    if finder is None:
        if tuple(sys.meta_path) != _BOOTSTRAP_META_PATH:
            raise SealedImportError("meta_path_changed")
    elif tuple(sys.meta_path) != (finder,) + _BOOTSTRAP_META_PATH:
        raise SealedImportError("meta_path_changed")
    if tuple(sys.path_hooks) != _BOOTSTRAP_PATH_HOOKS:
        raise SealedImportError("path_hooks_changed")


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_SOURCE_BYTES = 16 * 1024 * 1024
_MAX_SOURCE_FILES = 4096
_REPARSE_POINT_ATTRIBUTE = 0x400
_FILE_ATTRIBUTE_DIRECTORY = 0x10
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_FILE_ATTRIBUTE_DEVICE = 0x40
_FILE_LIST_DIRECTORY = 0x00000001
_FILE_READ_ATTRIBUTES = 0x80
_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x1
_FILE_SHARE_WRITE = 0x2
_FILE_SHARE_DELETE = 0x4
_OPEN_EXISTING = 3
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
_FILE_ID_INFO_CLASS = 18
_FILE_ID_BOTH_DIRECTORY_INFO_CLASS = 10
_FILE_ID_BOTH_DIRECTORY_RESTART_INFO_CLASS = 11
_PIN_PATHS = MappingProxyType(
    {
        "i13": "backtrader_runtime/ctp_i13_source_identity_pin.py",
        "i15": "backtrader_runtime/ctp_i15_source_identity_pin.py",
    }
)
_FIXED_READONLY_WORKER_RELATIVE_PATH = "scripts/ctp_i13_i15_readonly_preflight_worker.py"
_FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH = (
    "scripts/ctp_i13_i15_readonly_preflight_bootstrap.py"
)
_FIXED_READONLY_REQUEST_COORDINATOR_RELATIVE_PATH = (
    "scripts/ctp_i13_i15_readonly_request_coordinator.py"
)
_FIXED_READONLY_RECEIPT_WRITER_RELATIVE_PATH = (
    "scripts/ctp_i13_i15_readonly_receipt_writer.py"
)
_FIXED_READONLY_TOKEN_BOOTSTRAP_RELATIVE_PATH = (
    "scripts/ctp_i13_i15_readonly_token_bootstrap.py"
)
# Service-role sources are fixed data, executed only from this sealed bootstrap.
# They never widen the `backtrader_runtime` import namespace.
_FIXED_READONLY_SERVICE_ROLE_RELATIVE_PATHS = frozenset(
    {
        _FIXED_READONLY_REQUEST_COORDINATOR_RELATIVE_PATH,
        _FIXED_READONLY_RECEIPT_WRITER_RELATIVE_PATH,
        _FIXED_READONLY_TOKEN_BOOTSTRAP_RELATIVE_PATH,
    }
)
_FIXED_READONLY_ROLE_MODULES = MappingProxyType(
    {
        "request_coordinator": (
            _FIXED_READONLY_REQUEST_COORDINATOR_RELATIVE_PATH,
            "_i13_fixed_readonly_request_coordinator",
            "ctp_i13_i15_readonly_request_coordinator_binding.v1",
            "main",
        ),
        "receipt_writer": (
            _FIXED_READONLY_RECEIPT_WRITER_RELATIVE_PATH,
            "_i13_fixed_readonly_receipt_writer",
            "ctp_i13_i15_readonly_receipt_writer_binding.v1",
            "main",
        ),
    }
)
_FIXED_READONLY_TOKEN_HELPER_MODULE = (
    _FIXED_READONLY_TOKEN_BOOTSTRAP_RELATIVE_PATH,
    "_i13_fixed_readonly_token_bootstrap",
    "ctp_i13_i15_readonly_token_bootstrap.v1",
)
_FIXED_BOOTSTRAP_SUPPORT_MODULES = MappingProxyType(
    {
        "scripts/ctp_i13_i15_outer_watchdog.py": "scripts.ctp_i13_i15_outer_watchdog",
        "scripts/ctp_i13_i15_worker_output_channel.py": "scripts.ctp_i13_i15_worker_output_channel",
        "scripts/ctp_i13_i15_windows_job_backend.py": "scripts.ctp_i13_i15_windows_job_backend",
    }
)
_FIXED_BOOTSTRAP_SUPPORT_PACKAGE_ORIGIN = "<fixed-i13-bootstrap-support-package>"
_FIXED_BOOTSTRAP_SUPPORT_REGISTRATION_TOKEN = object()
_FIXED_READONLY_DATA_RELATIVE_PATHS = frozenset(
    {
        _FIXED_READONLY_WORKER_RELATIVE_PATH,
        _FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH,
        *_FIXED_READONLY_SERVICE_ROLE_RELATIVE_PATHS,
    }
)
_FIXED_WORKER_DEPENDENCY_HELPER_RELATIVE_PATH = (
    "backtrader_runtime/ctp_i13_worker_dependency_seal.py"
)
_SEALED_DEPENDENCY_TOP_LEVEL_ROOTS = ("yaml", "bt_api_base", "bt_api_ctp")
_MAX_LEASE_PATHS = _MAX_SOURCE_FILES + len(_PIN_PATHS) + 1


@dataclass(frozen=True)
class CandidateSpec:
    manifest_path: str
    manifest_schema: object
    entrypoint: str
    pin_key: str


CANDIDATES = MappingProxyType(
    {
        "i13_md": CandidateSpec(
            "backtrader_runtime/ctp_i13_source_manifest.json",
            1,
            "backtrader_runtime.ctp_i13_md_oneshot_supervisor",
            "i13",
        ),
        "i15_td": CandidateSpec(
            "backtrader_runtime/ctp_i15_source_manifest.json",
            "ctp_i15_source_manifest.v2",
            "backtrader_runtime.ctp_i15_td_only_readonly",
            "i15",
        ),
    }
)


class SealedImportError(ValueError):
    """A redacted fail-closed source seal or import rejection."""


class WindowsSourceLeaseError(ValueError):
    """A Windows source lease or reopened-file identity check failed."""


_PENDING_WINDOWS_SOURCE_LEASES = []


def _remember_pending_windows_lease(lease) -> None:
    if not any(pending is lease for pending in _PENDING_WINDOWS_SOURCE_LEASES):
        _PENDING_WINDOWS_SOURCE_LEASES.append(lease)


def _forget_pending_windows_lease(lease) -> None:
    _PENDING_WINDOWS_SOURCE_LEASES[:] = [
        pending for pending in _PENDING_WINDOWS_SOURCE_LEASES if pending is not lease
    ]


class _FileAttributeTagInfo(ctypes.Structure):
    _fields_ = [("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD)]


class _FileIdInfo(ctypes.Structure):
    _fields_ = [("VolumeSerialNumber", ctypes.c_ulonglong), ("FileId", ctypes.c_ubyte * 16)]


class _FileIdBothDirectoryInfo(ctypes.Structure):
    """Fixed prefix of FILE_ID_BOTH_DIR_INFO; FileName is variable length."""

    _fields_ = [
        ("NextEntryOffset", wintypes.DWORD),
        ("FileIndex", wintypes.DWORD),
        ("CreationTime", ctypes.c_longlong),
        ("LastAccessTime", ctypes.c_longlong),
        ("LastWriteTime", ctypes.c_longlong),
        ("ChangeTime", ctypes.c_longlong),
        ("EndOfFile", ctypes.c_longlong),
        ("AllocationSize", ctypes.c_longlong),
        ("FileAttributes", wintypes.DWORD),
        ("FileNameLength", wintypes.DWORD),
        ("EaSize", wintypes.DWORD),
        ("ShortNameLength", ctypes.c_ubyte),
        ("ShortName", wintypes.WCHAR * 12),
        ("FileId", ctypes.c_longlong),
        ("FileName", wintypes.WCHAR * 1),
    ]


@dataclass(frozen=True)
class WindowsFileIdentity:
    volume_serial: int
    file_id: bytes


@dataclass(frozen=True)
class _WindowsLeaseEntry:
    path: str
    identity: WindowsFileIdentity
    is_directory: bool
    size: Optional[int]
    handle: object


class _WindowsLeaseApi:
    def __init__(self):
        if sys.platform != "win32":
            raise WindowsSourceLeaseError("windows_file_id_api_unavailable")
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except (AttributeError, OSError):
            raise WindowsSourceLeaseError("windows_file_id_api_unavailable") from None
        kernel32.CreateFileW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.GetFileInformationByHandleEx.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
        )
        kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
        kernel32.GetFileSizeEx.argtypes = (wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong))
        kernel32.GetFileSizeEx.restype = wintypes.BOOL
        kernel32.ReadFile.argtypes = (
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        )
        kernel32.ReadFile.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        self.kernel32 = kernel32

    @staticmethod
    def _invalid_handle(handle) -> bool:
        return handle is None or handle == wintypes.HANDLE(-1).value

    def open(self, path: str, *, is_directory: bool, lease: bool, read_data: bool = False):
        access = _FILE_READ_ATTRIBUTES
        if is_directory:
            access |= _FILE_LIST_DIRECTORY
        elif read_data:
            access |= _GENERIC_READ
        share = (
            _FILE_SHARE_READ if lease else _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE
        )
        flags = _FILE_FLAG_OPEN_REPARSE_POINT
        if is_directory:
            flags |= _FILE_FLAG_BACKUP_SEMANTICS
        handle = self.kernel32.CreateFileW(
            path,
            access,
            share,
            None,
            _OPEN_EXISTING,
            flags,
            None,
        )
        if self._invalid_handle(handle):
            raise WindowsSourceLeaseError("source_handle_open_failed")
        return handle

    def close(self, handle) -> None:
        if not self.kernel32.CloseHandle(handle):
            raise WindowsSourceLeaseError("source_handle_close_failed")

    def attributes(self, handle) -> int:
        details = _FileAttributeTagInfo()
        if not self.kernel32.GetFileInformationByHandleEx(
            handle,
            _FILE_ATTRIBUTE_TAG_INFO_CLASS,
            ctypes.byref(details),
            ctypes.sizeof(details),
        ):
            raise WindowsSourceLeaseError("source_attributes_unavailable")
        return details.FileAttributes

    def identity(self, handle) -> WindowsFileIdentity:
        details = _FileIdInfo()
        if not self.kernel32.GetFileInformationByHandleEx(
            handle,
            _FILE_ID_INFO_CLASS,
            ctypes.byref(details),
            ctypes.sizeof(details),
        ):
            raise WindowsSourceLeaseError("source_file_id_unavailable")
        return WindowsFileIdentity(
            volume_serial=int(details.VolumeSerialNumber),
            file_id=bytes(details.FileId),
        )

    def size(self, handle) -> int:
        value = ctypes.c_longlong()
        if not self.kernel32.GetFileSizeEx(handle, ctypes.byref(value)):
            raise WindowsSourceLeaseError("source_size_unavailable")
        if value.value < 0:
            raise WindowsSourceLeaseError("source_size_invalid")
        return int(value.value)

    def read(self, handle, size: int) -> bytes:
        result = bytearray()
        while len(result) < size:
            requested = min(64 * 1024, size - len(result))
            buffer = ctypes.create_string_buffer(requested)
            received = wintypes.DWORD()
            if not self.kernel32.ReadFile(
                handle,
                buffer,
                requested,
                ctypes.byref(received),
                None,
            ):
                raise WindowsSourceLeaseError("source_read_failed")
            if received.value == 0:
                break
            result.extend(buffer.raw[: received.value])
        return bytes(result)

    def list_directory(self, handle) -> tuple[str, ...]:
        """Enumerate names from the retained directory handle only."""

        attributes = self.attributes(handle)
        if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise WindowsSourceLeaseError("source_path_reparse_point")
        if not attributes & _FILE_ATTRIBUTE_DIRECTORY:
            raise WindowsSourceLeaseError("source_directory_not_leased")
        identity_before = self.identity(handle)
        buffer_size = 64 * 1024
        buffer = ctypes.create_string_buffer(buffer_size)
        names = []
        information_class = _FILE_ID_BOTH_DIRECTORY_RESTART_INFO_CLASS
        while True:
            succeeded = self.kernel32.GetFileInformationByHandleEx(
                handle,
                information_class,
                buffer,
                buffer_size,
            )
            information_class = _FILE_ID_BOTH_DIRECTORY_INFO_CLASS
            if not succeeded:
                error = ctypes.get_last_error()
                if error == 18:  # ERROR_NO_MORE_FILES
                    break
                raise WindowsSourceLeaseError("source_directory_read_failed")

            offset = 0
            while True:
                if offset < 0 or offset + ctypes.sizeof(_FileIdBothDirectoryInfo) > buffer_size:
                    raise WindowsSourceLeaseError("source_directory_buffer_invalid")
                row = _FileIdBothDirectoryInfo.from_buffer(buffer, offset)
                name_length = int(row.FileNameLength)
                name_offset = offset + _FileIdBothDirectoryInfo.FileName.offset
                if (
                    name_length <= 0
                    or name_length % 2
                    or name_offset + name_length > buffer_size
                    or row.FileAttributes & (_FILE_ATTRIBUTE_REPARSE_POINT | _FILE_ATTRIBUTE_DEVICE)
                ):
                    raise WindowsSourceLeaseError("source_directory_entry_invalid")
                raw_name = ctypes.string_at(ctypes.addressof(buffer) + name_offset, name_length)
                try:
                    name = raw_name.decode("utf-16-le", "strict")
                except UnicodeError:
                    raise WindowsSourceLeaseError("source_directory_entry_invalid") from None
                if (
                    not name
                    or "/" in name
                    or "\\" in name
                    or ":" in name
                    or "\x00" in name
                ):
                    raise WindowsSourceLeaseError("source_directory_entry_invalid")
                if name in {".", ".."}:
                    if not row.FileAttributes & _FILE_ATTRIBUTE_DIRECTORY:
                        raise WindowsSourceLeaseError("source_directory_entry_invalid")
                else:
                    names.append(name)
                    if len(names) > 100_000:
                        raise WindowsSourceLeaseError("source_directory_entry_limit")
                next_offset = int(row.NextEntryOffset)
                if next_offset == 0:
                    break
                if (
                    next_offset % 8
                    or next_offset < _FileIdBothDirectoryInfo.FileName.offset + name_length
                    or offset + next_offset + ctypes.sizeof(_FileIdBothDirectoryInfo) > buffer_size
                ):
                    raise WindowsSourceLeaseError("source_directory_buffer_invalid")
                offset += next_offset
        if self.identity(handle) != identity_before:
            raise WindowsSourceLeaseError("source_file_identity_mismatch")
        folded = [name.casefold() for name in names]
        if len(folded) != len(set(folded)):
            raise WindowsSourceLeaseError("source_directory_case_collision")
        return tuple(names)


def _canonical_windows_absolute_path(value: object) -> str:
    try:
        raw = os.fspath(value)
    except TypeError:
        raise WindowsSourceLeaseError("source_path_invalid") from None
    if type(raw) is not str or not raw or sys.platform != "win32":
        raise WindowsSourceLeaseError("source_path_invalid")
    raw = raw.replace("/", "\\")
    if (
        len(raw) < 3
        or not raw[0].isalpha()
        or raw[1:3] != ":\\"
        or raw.startswith("\\\\")
        or any(part in {".", ".."} for part in raw[3:].split("\\") if part)
        or ":" in raw[3:]
        or any(char in raw for char in '*?"<>|')
    ):
        raise WindowsSourceLeaseError("source_path_invalid")
    for component in raw[3:].split("\\"):
        if not component:
            continue
        stem = component.split(".", 1)[0].rstrip(" .").casefold()
        if (
            component.endswith((".", " "))
            or stem in {"con", "prn", "aux", "nul"}
            or (len(stem) == 4 and stem[:3] in {"com", "lpt"} and stem[3] in "123456789")
        ):
            raise WindowsSourceLeaseError("source_path_invalid")
    normalized = os.path.normpath(os.path.abspath(raw))
    if not os.path.isabs(normalized) or len(normalized) > 32767:
        raise WindowsSourceLeaseError("source_path_invalid")
    return normalized


def _windows_path_components(path: str, *, final_is_directory: bool):
    parts = PureWindowsPath(path).parts
    if not parts or not parts[0].endswith("\\"):
        raise WindowsSourceLeaseError("source_path_invalid")
    current = PureWindowsPath(parts[0])
    yield str(current), True
    for index, part in enumerate(parts[1:]):
        current = current / part
        last = index == len(parts) - 2
        yield str(current), final_is_directory if last else True


def _lease_relative_parts(relative: object) -> tuple[str, ...]:
    if type(relative) is not str or not relative or "\\" in relative:
        raise WindowsSourceLeaseError("source_relative_path_invalid")
    path = PurePosixPath(relative)
    if (
        path.is_absolute()
        or path.as_posix() != relative
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise WindowsSourceLeaseError("source_relative_path_invalid")
    return path.parts


class WindowsSourceLease:
    """Hold path handles and read only matching file IDs and source bytes.

    ``SealedSourceTree`` retains this lease and its loader reads exact verified
    bytes through it. Every path component is opened without following its
    final reparse point; retained handles use a read-only share mask. Windows
    still permits directory attribute handles, so this is not a general path
    immutability claim. A failed close poisons the lease and preserves the
    handle for explicit retry.
    """

    def __init__(self, root: str, api: _WindowsLeaseApi):
        self.root = root
        self._api = api
        self._entries = {}
        self._handles = []
        self._closed = False
        self._poisoned = False

    @classmethod
    def acquire(cls, source_root: object, relative_paths: Sequence[str]):
        if sys.platform != "win32" or sys.version_info[:3] != (3, 11, 5):
            raise WindowsSourceLeaseError("windows_file_id_api_unavailable")
        root = _canonical_windows_absolute_path(source_root)
        if type(relative_paths) not in (tuple, list) or not relative_paths:
            raise WindowsSourceLeaseError("source_lease_paths_invalid")
        if len(relative_paths) > _MAX_LEASE_PATHS:
            raise WindowsSourceLeaseError("source_lease_paths_invalid")
        relative_parts = [_lease_relative_parts(value) for value in relative_paths]
        target_keys = {
            os.path.normcase(os.path.normpath(str(PureWindowsPath(root).joinpath(*parts))))
            for parts in relative_parts
        }
        if len(target_keys) != len(relative_parts):
            raise WindowsSourceLeaseError("source_lease_paths_invalid")
        api = _WindowsLeaseApi()
        lease = cls(root, api)
        try:
            lease._retain_path(root, final_is_directory=True)
            for parts in relative_parts:
                target = str(PureWindowsPath(root).joinpath(*parts))
                lease._retain_path(target, final_is_directory=False)
            return lease
        except BaseException:
            try:
                lease.close()
            except WindowsSourceLeaseError:
                raise WindowsSourceLeaseError("source_lease_acquire_cleanup_failed") from None
            raise

    def _retain_path(self, path: str, *, final_is_directory: bool) -> None:
        for component, is_directory in _windows_path_components(
            path, final_is_directory=final_is_directory
        ):
            key = os.path.normcase(os.path.normpath(component))
            existing = self._entries.get(key)
            if existing is not None:
                if existing.is_directory != is_directory:
                    raise WindowsSourceLeaseError("source_path_kind_conflict")
                continue
            handle = self._api.open(
                component,
                is_directory=is_directory,
                lease=True,
                read_data=not is_directory,
            )
            self._handles.append(handle)
            attributes = self._api.attributes(handle)
            if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                raise WindowsSourceLeaseError("source_path_reparse_point")
            if bool(attributes & _FILE_ATTRIBUTE_DIRECTORY) != is_directory:
                raise WindowsSourceLeaseError("source_path_kind_invalid")
            identity = self._api.identity(handle)
            size = None if is_directory else self._api.size(handle)
            entry = _WindowsLeaseEntry(component, identity, is_directory, size, handle)
            self._entries[key] = entry

    def _close_tracked_handle(self, handle) -> None:
        if not any(current == handle for current in self._handles):
            return
        try:
            self._api.close(handle)
        except Exception:
            self._poisoned = True
            _remember_pending_windows_lease(self)
            raise WindowsSourceLeaseError("source_handle_close_failed") from None
        self._handles[:] = [current for current in self._handles if current != handle]

    def _open_verified_path(
        self, path: object, expected: _WindowsLeaseEntry, *, read_data: bool = False
    ):
        if self._closed or self._poisoned:
            raise WindowsSourceLeaseError("source_lease_poisoned")
        canonical = _canonical_windows_absolute_path(path)
        handle = self._api.open(
            canonical,
            is_directory=expected.is_directory,
            lease=False,
            read_data=read_data,
        )
        self._handles.append(handle)
        try:
            attributes = self._api.attributes(handle)
            if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                raise WindowsSourceLeaseError("source_path_reparse_point")
            if bool(attributes & _FILE_ATTRIBUTE_DIRECTORY) != expected.is_directory:
                raise WindowsSourceLeaseError("source_path_kind_invalid")
            if self._api.identity(handle) != expected.identity:
                raise WindowsSourceLeaseError("source_file_identity_mismatch")
            if read_data and not expected.is_directory and self._api.size(handle) != expected.size:
                raise WindowsSourceLeaseError("source_size_changed")
            return handle
        except BaseException:
            self._close_tracked_handle(handle)
            raise

    def read_source(self, relative: str, *, expected_sha256: str) -> bytes:
        if self._closed:
            raise WindowsSourceLeaseError("source_lease_closed")
        if self._poisoned:
            raise WindowsSourceLeaseError("source_lease_poisoned")
        expected = _sha256(expected_sha256, "source_digest_invalid")
        parts = _lease_relative_parts(relative)
        target = str(PureWindowsPath(self.root).joinpath(*parts))
        components = list(_windows_path_components(target, final_is_directory=False))
        reopened_file = None
        try:
            for component, is_directory in components:
                key = os.path.normcase(os.path.normpath(component))
                entry = self._entries.get(key)
                if entry is None or entry.is_directory != is_directory:
                    raise WindowsSourceLeaseError("source_path_not_leased")
                handle = self._open_verified_path(component, entry, read_data=not is_directory)
                if is_directory:
                    self._close_tracked_handle(handle)
                else:
                    reopened_file = (handle, entry)
            if reopened_file is None:
                raise WindowsSourceLeaseError("source_file_not_leased")
            handle, entry = reopened_file
            if entry.size is None or entry.size > _MAX_SOURCE_BYTES:
                raise WindowsSourceLeaseError("source_size_invalid")
            content = self._api.read(handle, entry.size)
            if (
                len(content) != entry.size
                or self._api.identity(handle) != entry.identity
                or self._api.size(handle) != entry.size
                or not hmac.compare_digest(hashlib.sha256(content).hexdigest(), expected)
            ):
                raise WindowsSourceLeaseError("source_content_changed")
            return content
        finally:
            if reopened_file is not None:
                self._close_tracked_handle(reopened_file[0])

    def list_directory(self, relative: str) -> tuple[str, ...]:
        """List one retained directory while checking its held file identity.

        This narrow API supports exact installed-dependency inventory checks.
        The directory and its ancestors are already held by the lease with a
        share mask that denies concurrent write/delete opens. Enumeration is
        performed through that retained handle, with the file ID compared
        before and after. Reparse entries are rejected. It accepts no absolute
        or caller-selected root path.
        """

        if self._closed:
            raise WindowsSourceLeaseError("source_lease_closed")
        if self._poisoned:
            raise WindowsSourceLeaseError("source_lease_poisoned")
        parts = _lease_relative_parts(relative)
        target = str(PureWindowsPath(self.root).joinpath(*parts))
        key = os.path.normcase(os.path.normpath(target))
        expected = self._entries.get(key)
        if expected is None or not expected.is_directory:
            raise WindowsSourceLeaseError("source_directory_not_leased")

        if self._api.identity(expected.handle) != expected.identity:
            raise WindowsSourceLeaseError("source_file_identity_mismatch")
        attributes = self._api.attributes(expected.handle)
        if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise WindowsSourceLeaseError("source_path_reparse_point")
        names = self._api.list_directory(expected.handle)
        if self._api.identity(expected.handle) != expected.identity:
            raise WindowsSourceLeaseError("source_file_identity_mismatch")
        folded = [name.casefold() for name in names]
        if len(folded) != len(set(folded)):
            raise WindowsSourceLeaseError("source_directory_case_collision")
        return tuple(names)

    def verify_current(self) -> None:
        """Reopen every retained file/directory and verify its identity/size."""

        if self._closed:
            raise WindowsSourceLeaseError("source_lease_closed")
        if self._poisoned:
            raise WindowsSourceLeaseError("source_lease_poisoned")
        for entry in tuple(self._entries.values()):
            handle = self._open_verified_path(
                entry.path,
                entry,
                read_data=not entry.is_directory,
            )
            self._close_tracked_handle(handle)

    def close(self) -> None:
        if self._closed:
            return
        remaining = []
        for handle in reversed(tuple(self._handles)):
            try:
                self._api.close(handle)
            except Exception:
                remaining.append(handle)
        self._handles[:] = list(reversed(remaining))
        if self._handles:
            self._poisoned = True
            _remember_pending_windows_lease(self)
            raise WindowsSourceLeaseError("source_lease_close_failed")
        self._closed = True
        self._poisoned = False
        _forget_pending_windows_lease(self)

    def __enter__(self):
        if self._closed:
            raise WindowsSourceLeaseError("source_lease_closed")
        if self._poisoned:
            raise WindowsSourceLeaseError("source_lease_poisoned")
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


def acquire_windows_source_lease(source_root: object, relative_paths: Sequence[str]):
    """Acquire a Windows deny-write/delete lease for exact relative paths."""

    if sys.platform != "win32" or sys.version_info[:3] != (3, 11, 5):
        raise WindowsSourceLeaseError("windows_file_id_api_unavailable")
    return WindowsSourceLease.acquire(source_root, relative_paths)


def retry_pending_windows_source_lease_cleanup() -> None:
    """Retry close for lease objects retained after a failed handle close."""

    if sys.platform != "win32" or sys.version_info[:3] != (3, 11, 5):
        raise WindowsSourceLeaseError("windows_file_id_api_unavailable")
    failed = False
    for lease in tuple(_PENDING_WINDOWS_SOURCE_LEASES):
        try:
            lease.close()
        except WindowsSourceLeaseError:
            failed = True
    if failed:
        raise WindowsSourceLeaseError("source_lease_cleanup_pending")


@dataclass(frozen=True)
class SealedSourceTree:
    candidate: str
    source_root: Path
    manifest_sha256: str
    files: Mapping[str, str]
    stdlib_paths: tuple[str, ...]
    source_lease: WindowsSourceLease

    @property
    def worker_sha256(self) -> str:
        """Return the pinned digest for the one fixed read-only worker source."""

        _require_source_lease(self)
        if self.candidate != "i13_md":
            raise SealedImportError("readonly_worker_source_unpinned")
        digest = self.files.get(_FIXED_READONLY_WORKER_RELATIVE_PATH)
        if digest is None:
            raise SealedImportError("readonly_worker_source_unpinned")
        return _sha256(digest, "readonly_worker_source_unpinned")

    def read_worker_source(self) -> bytes:
        """Read only the fixed worker bytes through the retained hash-bound lease."""

        digest = self.worker_sha256
        lease = _require_source_lease(self)
        try:
            return lease.read_source(
                _FIXED_READONLY_WORKER_RELATIVE_PATH,
                expected_sha256=digest,
            )
        except WindowsSourceLeaseError as error:
            raise SealedImportError("readonly_worker_source_unavailable") from error

    @property
    def bootstrap_sha256(self) -> str:
        """Return the pinned digest for the one fixed child bootstrap artifact."""

        _require_source_lease(self)
        if self.candidate != "i13_md":
            raise SealedImportError("readonly_bootstrap_source_unpinned")
        digest = self.files.get(_FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH)
        if digest is None:
            raise SealedImportError("readonly_bootstrap_source_unpinned")
        return _sha256(digest, "readonly_bootstrap_source_unpinned")

    def read_bootstrap_source(self) -> bytes:
        """Read the fixed child bootstrap through the retained hash-bound lease."""

        digest = self.bootstrap_sha256
        lease = _require_source_lease(self)
        try:
            return lease.read_source(
                _FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH,
                expected_sha256=digest,
            )
        except WindowsSourceLeaseError as error:
            raise SealedImportError("readonly_bootstrap_source_unavailable") from error

    def read_request_coordinator_source(self) -> bytes:
        """Read only the fixed service coordinator bytes through the source lease."""

        return self._read_fixed_readonly_source(
            _FIXED_READONLY_REQUEST_COORDINATOR_RELATIVE_PATH,
            "readonly_request_coordinator_source_unpinned",
            "readonly_request_coordinator_source_unavailable",
        )

    def read_receipt_writer_source(self) -> bytes:
        """Read only the fixed service receipt-writer bytes through the source lease."""

        return self._read_fixed_readonly_source(
            _FIXED_READONLY_RECEIPT_WRITER_RELATIVE_PATH,
            "readonly_receipt_writer_source_unpinned",
            "readonly_receipt_writer_source_unavailable",
        )

    def read_token_bootstrap_source(self) -> bytes:
        """Read only the fixed token-bootstrap bytes through the source lease."""

        return self._read_fixed_readonly_source(
            _FIXED_READONLY_TOKEN_BOOTSTRAP_RELATIVE_PATH,
            "readonly_token_bootstrap_source_unpinned",
            "readonly_token_bootstrap_source_unavailable",
        )

    def _read_fixed_readonly_source(
        self, relative_path: str, missing_reason: str, read_reason: str
    ) -> bytes:
        _require_source_lease(self)
        if self.candidate != "i13_md" or relative_path not in _FIXED_READONLY_SERVICE_ROLE_RELATIVE_PATHS:
            raise SealedImportError(missing_reason)
        digest = self.files.get(relative_path)
        if digest is None:
            raise SealedImportError(missing_reason)
        try:
            return self.source_lease.read_source(relative_path, expected_sha256=digest)
        except WindowsSourceLeaseError as error:
            raise SealedImportError(read_reason) from error

    def close(self) -> None:
        self.source_lease.close()

    def __enter__(self):
        _require_source_lease(self)
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


def _candidate_spec(candidate: object) -> CandidateSpec:
    if type(candidate) is not str or candidate not in CANDIDATES:
        raise SealedImportError("candidate_invalid")
    return CANDIDATES[candidate]


def _require_source_lease(seal: SealedSourceTree) -> WindowsSourceLease:
    if (
        type(seal) is not SealedSourceTree
        or sys.platform != "win32"
        or sys.version_info[:3] != (3, 11, 5)
    ):
        raise SealedImportError("windows_source_lease_required")
    lease = seal.source_lease
    if (
        type(lease) is not WindowsSourceLease
        or type(lease._api) is not _WindowsLeaseApi
        or lease._closed
        or lease._poisoned
        or type(lease._handles) is not list
        or not lease._handles
        or type(lease._entries) is not dict
        or type(seal.files) is not type(MappingProxyType({}))
    ):
        raise SealedImportError("source_lease_unavailable")
    try:
        root = _canonical_windows_absolute_path(seal.source_root)
        spec = _candidate_spec(seal.candidate)
        relative_paths = (spec.manifest_path,) + tuple(seal.files)
        for relative in relative_paths:
            parts = _lease_relative_parts(relative)
            path = str(PureWindowsPath(root).joinpath(*parts))
            key = os.path.normcase(os.path.normpath(path))
            entry = lease._entries.get(key)
            if entry is None or entry.is_directory or entry.size is None:
                raise SealedImportError("source_lease_unavailable")
    except (AttributeError, TypeError, WindowsSourceLeaseError):
        raise SealedImportError("source_lease_unavailable") from None
    if lease.root != root or seal.source_root != Path(root):
        raise SealedImportError("source_lease_root_mismatch")
    return lease


def _sha256(value: object, reason: str) -> str:
    if type(value) is not str or not _SHA256_RE.fullmatch(value) or value == "0" * 64:
        raise SealedImportError(reason)
    return value


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SealedImportError("manifest_duplicate_key")
        result[key] = value
    return result


def _safe_source_path(value: object) -> str:
    if type(value) is not str or not value or "\\" in value:
        raise SealedImportError("manifest_path_invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or path.suffix != ".py"
        or len(path.parts) < 2
        or path.parts[0] != "backtrader_runtime"
        or any(part in {"", ".", ".."} for part in path.parts)
        or value in _PIN_PATHS.values()
    ):
        raise SealedImportError("manifest_path_invalid")
    return value


def _safe_i13_manifest_path(value: object) -> str:
    """Accept runtime imports plus the exact fixed worker/bootstrap data paths."""

    if value in _FIXED_READONLY_DATA_RELATIVE_PATHS:
        return value
    return _safe_source_path(value)


def parse_candidate_manifest(
    candidate: object,
    raw: bytes,
    *,
    expected_manifest_sha256: object,
) -> Mapping[str, str]:
    """Parse and pin the existing candidate-specific manifest format.

    I13 uses schema 1 with a sorted ``source_files`` mapping. I15 uses its
    versioned schema with sorted ``files`` rows. Both encodings must be strict
    canonical JSON and contain only lower-case SHA-256 values.
    """

    spec = _candidate_spec(candidate)
    expected = _sha256(expected_manifest_sha256, "manifest_pin_unset")
    if type(raw) is not bytes or not raw or len(raw) > _MAX_MANIFEST_BYTES:
        raise SealedImportError("manifest_invalid")
    actual = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual, expected):
        raise SealedImportError("manifest_digest_mismatch")
    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except SealedImportError:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise SealedImportError("manifest_invalid") from None

    files = {}
    if candidate == "i13_md":
        if type(parsed) is not dict or set(parsed) != {"schema", "source_files"}:
            raise SealedImportError("manifest_invalid")
        if type(parsed["schema"]) is not int or parsed["schema"] != spec.manifest_schema:
            raise SealedImportError("manifest_invalid")
        rows = parsed["source_files"]
        if type(rows) is not dict or not 1 <= len(rows) <= _MAX_SOURCE_FILES:
            raise SealedImportError("manifest_invalid")
        if list(rows) != sorted(rows):
            raise SealedImportError("manifest_order_invalid")
        for path, digest in rows.items():
            files[_safe_i13_manifest_path(path)] = _sha256(digest, "manifest_invalid")
        if (
            _FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH in files
            and _FIXED_READONLY_WORKER_RELATIVE_PATH not in files
        ):
            raise SealedImportError("readonly_worker_source_unpinned")
        if (
            _FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH in files
            and _FIXED_WORKER_DEPENDENCY_HELPER_RELATIVE_PATH not in files
        ):
            raise SealedImportError("readonly_dependency_helper_unpinned")
        service_role_paths = files.keys() & _FIXED_READONLY_SERVICE_ROLE_RELATIVE_PATHS
        if service_role_paths and service_role_paths != _FIXED_READONLY_SERVICE_ROLE_RELATIVE_PATHS:
            raise SealedImportError("readonly_service_role_sources_incomplete")
        if service_role_paths and (
            _FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH not in files
            or _FIXED_READONLY_WORKER_RELATIVE_PATH not in files
            or _FIXED_WORKER_DEPENDENCY_HELPER_RELATIVE_PATH not in files
        ):
            raise SealedImportError("readonly_service_role_bootstrap_unpinned")
        canonical_value = {"schema": 1, "source_files": files}
    else:
        if type(parsed) is not dict or set(parsed) != {"files", "schema"}:
            raise SealedImportError("manifest_invalid")
        if parsed["schema"] != spec.manifest_schema:
            raise SealedImportError("manifest_invalid")
        rows = parsed["files"]
        if type(rows) is not list or not 1 <= len(rows) <= _MAX_SOURCE_FILES:
            raise SealedImportError("manifest_invalid")
        previous = None
        for row in rows:
            if type(row) is not dict or set(row) != {"path", "sha256"}:
                raise SealedImportError("manifest_invalid")
            path = _safe_source_path(row["path"])
            digest = _sha256(row["sha256"], "manifest_invalid")
            if path in files:
                raise SealedImportError("manifest_duplicate_path")
            if previous is not None and path <= previous:
                raise SealedImportError("manifest_order_invalid")
            previous = path
            files[path] = digest
        canonical_value = {
            "files": [{"path": path, "sha256": digest} for path, digest in files.items()],
            "schema": spec.manifest_schema,
        }

    if not files:
        raise SealedImportError("manifest_invalid")
    if "backtrader_runtime/__init__.py" not in files:
        raise SealedImportError("runtime_package_init_unpinned")
    if spec.entrypoint.replace(".", "/") + ".py" not in files:
        raise SealedImportError("candidate_entrypoint_unpinned")
    canonical = json.dumps(
        canonical_value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    if raw != canonical:
        raise SealedImportError("manifest_not_canonical")
    return MappingProxyType(files)


def _has_reparse_point(details: os.stat_result) -> bool:
    return stat.S_ISLNK(details.st_mode) or bool(
        getattr(details, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
    )


def _assert_path_components(path: Path, *, final_kind: Optional[str] = None) -> None:
    if not path.is_absolute():
        raise SealedImportError("path_not_absolute")
    anchor = Path(path.anchor)
    current = anchor
    relative = path.parts[1:] if path.anchor else path.parts
    for index, part in enumerate(relative):
        current = current / part
        try:
            details = os.lstat(current)
        except OSError:
            raise SealedImportError("path_component_unavailable") from None
        if _has_reparse_point(details):
            raise SealedImportError("path_reparse_point")
        if index < len(relative) - 1 and not stat.S_ISDIR(details.st_mode):
            raise SealedImportError("path_parent_not_directory")
    if final_kind == "directory" and not stat.S_ISDIR(os.lstat(path).st_mode):
        raise SealedImportError("path_not_directory")
    if final_kind == "file" and not stat.S_ISREG(os.lstat(path).st_mode):
        raise SealedImportError("path_not_regular_file")


def _checked_read(root: Path, relative: str) -> bytes:
    if relative in _PIN_PATHS.values():
        safe = relative
    else:
        safe = _safe_source_path(relative) if relative.endswith(".py") else relative
    if type(safe) is not str or "\\" in safe:
        raise SealedImportError("source_path_invalid")
    parts = PurePosixPath(safe).parts
    if PurePosixPath(safe).is_absolute() or any(part in {"", ".", ".."} for part in parts):
        raise SealedImportError("source_path_invalid")
    current = root
    try:
        root_stat = os.lstat(root)
    except OSError:
        raise SealedImportError("source_root_unavailable") from None
    if _has_reparse_point(root_stat) or not stat.S_ISDIR(root_stat.st_mode):
        raise SealedImportError("source_root_invalid")
    for index, component in enumerate(parts):
        current = current / component
        try:
            before = os.lstat(current)
        except OSError:
            raise SealedImportError("source_file_unavailable") from None
        if _has_reparse_point(before):
            raise SealedImportError("source_path_reparse_point")
        final = index == len(parts) - 1
        if not final:
            if not stat.S_ISDIR(before.st_mode):
                raise SealedImportError("source_parent_not_directory")
            continue
        if not stat.S_ISREG(before.st_mode):
            raise SealedImportError("source_not_regular_file")
        try:
            with open(current, "rb") as stream:
                content = stream.read(_MAX_SOURCE_BYTES + 1)
            after = os.lstat(current)
        except OSError:
            raise SealedImportError("source_file_unavailable") from None
        if (
            _has_reparse_point(after)
            or not stat.S_ISREG(after.st_mode)
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or len(content) != after.st_size
            or len(content) > _MAX_SOURCE_BYTES
        ):
            raise SealedImportError("source_changed_during_read")
        return content
    raise SealedImportError("source_file_unavailable")


def _pyc_source_for_relative(relative: str) -> Optional[str]:
    path = PurePosixPath(relative)
    parts = path.parts
    if "__pycache__" not in parts:
        return None
    index = parts.index("__pycache__")
    if index != len(parts) - 2 or index == 0:
        raise SealedImportError("pyc_cache_layout_invalid")
    name = parts[-1]
    match = re.fullmatch(r"(.+)\.([A-Za-z0-9_-]+)\.pyc", name)
    if match is None or match.group(2) in {"", "py"}:
        raise SealedImportError("pyc_cache_layout_invalid")
    source_parts = parts[:index] + (match.group(1) + ".py",)
    return PurePosixPath(*source_parts).as_posix()


def _scan_source_inventory(
    package_root: Path,
    manifest_path: str,
    *,
    include_readonly_worker: bool = False,
    include_readonly_bootstrap: bool = False,
    include_readonly_service_roles: bool = False,
) -> set[str]:
    python_files = set()
    pyc_sources = set()
    stack = [(package_root, "backtrader_runtime")]
    while stack:
        directory, relative_directory = stack.pop()
        directory_parts = PurePosixPath(relative_directory).parts
        if "__pycache__" in directory_parts and directory_parts[-1] != "__pycache__":
            raise SealedImportError("pyc_cache_layout_invalid")
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError:
            raise SealedImportError("source_directory_unavailable") from None
        for entry in entries:
            relative = relative_directory + "/" + entry.name
            try:
                details = entry.stat(follow_symlinks=False)
            except OSError:
                raise SealedImportError("source_entry_unavailable") from None
            if _has_reparse_point(details):
                raise SealedImportError("source_tree_reparse_point")
            if stat.S_ISDIR(details.st_mode):
                stack.append((Path(entry.path), relative))
                continue
            if not stat.S_ISREG(details.st_mode):
                raise SealedImportError("source_entry_not_regular")
            lowered = entry.name.casefold()
            if lowered.endswith((".pyd", ".so", ".dll", ".dylib", ".pyo")):
                raise SealedImportError("source_native_artifact_invalid")
            if lowered.endswith(".pyc"):
                source = _pyc_source_for_relative(relative)
                if source is None:
                    raise SealedImportError("pyc_cache_layout_invalid")
                pyc_sources.add(source)
                continue
            if entry.name.endswith(".py"):
                python_files.add(relative)
            elif lowered.endswith(".py"):
                raise SealedImportError("source_python_suffix_invalid")
            elif entry.name.lower().endswith(".json") and relative == manifest_path:
                continue
    if not pyc_sources.issubset(python_files):
        raise SealedImportError("pyc_cache_source_missing")
    if include_readonly_worker:
        worker_path = package_root.parent.joinpath(*_FIXED_READONLY_WORKER_RELATIVE_PATH.split("/"))
        _assert_path_components(worker_path, final_kind="file")
        python_files.add(_FIXED_READONLY_WORKER_RELATIVE_PATH)
    if include_readonly_bootstrap:
        bootstrap_path = package_root.parent.joinpath(
            *_FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH.split("/")
        )
        _assert_path_components(bootstrap_path, final_kind="file")
        python_files.add(_FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH)
    if include_readonly_service_roles:
        for relative in sorted(_FIXED_READONLY_SERVICE_ROLE_RELATIVE_PATHS):
            service_path = package_root.parent.joinpath(*relative.split("/"))
            _assert_path_components(service_path, final_kind="file")
            python_files.add(relative)
    return python_files


def validate_stdlib_roots(expected_stdlib_paths: Sequence[str]) -> tuple[str, ...]:
    if type(expected_stdlib_paths) not in (tuple, list) or not expected_stdlib_paths:
        raise SealedImportError("stdlib_roots_unset")
    normalized = []
    for value in expected_stdlib_paths:
        if type(value) is not str or not os.path.isabs(value):
            raise SealedImportError("stdlib_root_invalid")
        canonical = os.path.normcase(os.path.abspath(value))
        if any(piece in canonical.casefold() for piece in ("site-packages", "appdata")):
            raise SealedImportError("stdlib_root_invalid")
        if canonical in normalized:
            raise SealedImportError("stdlib_root_duplicate")
        if os.path.exists(value):
            _assert_path_components(Path(value))
        normalized.append(canonical)
    current = tuple(os.path.normcase(os.path.abspath(value)) for value in sys.path)
    if any(
        type(value) is not str
        or not value
        or os.path.normcase(os.path.abspath(value)) not in normalized
        for value in sys.path
    ):
        raise SealedImportError("sys_path_outside_stdlib_roots")
    if len(current) != len(normalized) or set(current) != set(normalized):
        raise SealedImportError("sys_path_stdlib_mismatch")
    return tuple(current)


def validate_fixed_venv_binding(
    *,
    venv_root: str,
    python_executable: str,
    python_sha256: str,
    python_version: str,
    venv_home: str,
    actual_executable: Optional[str] = None,
    actual_version: Optional[str] = None,
) -> None:
    """Validate the exact -S venv facts supplied by an external descriptor.

    This pure validation helper does not make its arguments trusted. The
    descriptor and its digest must be anchored outside the checkout.
    """

    for value in (venv_root, python_executable, venv_home):
        if type(value) is not str or not os.path.isabs(value):
            raise SealedImportError("venv_binding_invalid")
    expected_python_hash = _sha256(python_sha256, "venv_python_pin_invalid")
    if type(python_version) is not str or not re.fullmatch(r"3\.11\.5", python_version):
        raise SealedImportError("venv_version_pin_invalid")
    root = Path(venv_root)
    executable = Path(python_executable)
    home = Path(venv_home)
    if os.name == "nt":
        expected_executable = root / "Scripts" / "python.exe"
    else:
        expected_executable = root / "bin" / "python"

    def norm(value):
        return os.path.normcase(os.path.abspath(str(value)))

    if norm(executable) != norm(expected_executable):
        raise SealedImportError("venv_executable_path_mismatch")
    running_executable = actual_executable if actual_executable is not None else sys.executable
    if norm(running_executable) != norm(executable):
        raise SealedImportError("venv_running_executable_mismatch")
    running_version = (
        actual_version if actual_version is not None else ".".join(map(str, sys.version_info[:3]))
    )
    if running_version != python_version:
        raise SealedImportError("venv_running_version_mismatch")

    _assert_path_components(root, final_kind="directory")
    _assert_path_components(home, final_kind="directory")
    _assert_path_components(executable, final_kind="file")
    cfg_path = root / "pyvenv.cfg"
    _assert_path_components(cfg_path, final_kind="file")
    try:
        raw_cfg = cfg_path.read_bytes()
    except OSError:
        raise SealedImportError("venv_config_unavailable") from None
    if len(raw_cfg) > 16 * 1024:
        raise SealedImportError("venv_config_invalid")
    config = {}
    try:
        for line in raw_cfg.decode("utf-8").splitlines():
            if not line.strip():
                continue
            key, separator, value = line.partition("=")
            if not separator:
                raise SealedImportError("venv_config_invalid")
            key = key.strip().casefold()
            value = value.strip()
            if key in config:
                raise SealedImportError("venv_config_duplicate_key")
            config[key] = value
    except UnicodeError:
        raise SealedImportError("venv_config_invalid") from None
    if (
        config.get("include-system-site-packages", "").casefold() != "false"
        or norm(config.get("home", "")) != norm(home)
        or config.get("version") != python_version
    ):
        raise SealedImportError("venv_config_binding_mismatch")
    try:
        executable_bytes = executable.read_bytes()
    except OSError:
        raise SealedImportError("venv_python_unavailable") from None
    if not hmac.compare_digest(hashlib.sha256(executable_bytes).hexdigest(), expected_python_hash):
        raise SealedImportError("venv_python_digest_mismatch")


def seal_candidate_source_tree(
    candidate: object,
    source_root: str | Path,
    *,
    expected_manifest_sha256: object,
    expected_pin_sha256s: Mapping[str, str],
    stdlib_paths: Sequence[str],
) -> SealedSourceTree:
    """Seal source bytes with retained Windows file-ID handles and hashes.

    The external manifest digest is checked before acquiring the lease. The
    manifest and every listed/pinned source are then reopened through the lease
    and revalidated before the returned tree can be installed or imported.
    The caller owns the returned lease and must close the tree explicitly.
    """

    if sys.platform != "win32" or sys.version_info[:3] != (3, 11, 5):
        raise SealedImportError("windows_source_lease_required")
    spec = _candidate_spec(candidate)
    try:
        root = Path(_canonical_windows_absolute_path(source_root))
    except WindowsSourceLeaseError:
        raise SealedImportError("source_root_invalid") from None
    _assert_path_components(root, final_kind="directory")
    package_root = root / "backtrader_runtime"
    _assert_path_components(package_root, final_kind="directory")
    if type(expected_pin_sha256s) is not dict or set(expected_pin_sha256s) != set(_PIN_PATHS):
        raise SealedImportError("pin_source_descriptor_invalid")
    pins = {
        path: _sha256(expected_pin_sha256s[key], "pin_source_descriptor_invalid")
        for key, path in _PIN_PATHS.items()
    }
    expected_digest = _sha256(expected_manifest_sha256, "manifest_pin_unset")

    # This first read is only used to learn the exact candidate file list. Its
    # bytes must already match the external manifest pin, and the leased reread
    # below repeats that pin before any tree is returned.
    initial_manifest = _checked_read(root, spec.manifest_path)
    if not hmac.compare_digest(hashlib.sha256(initial_manifest).hexdigest(), expected_digest):
        raise SealedImportError("manifest_digest_mismatch")
    manifest_files = parse_candidate_manifest(
        candidate, initial_manifest, expected_manifest_sha256=expected_digest
    )
    all_files = dict(manifest_files)
    all_files.update(pins)
    if spec.entrypoint.replace(".", "/") + ".py" not in all_files:
        raise SealedImportError("candidate_entrypoint_unpinned")
    checked_stdlib_paths = validate_stdlib_roots(stdlib_paths)

    lease_paths = (spec.manifest_path,) + tuple(sorted(all_files))
    lease = acquire_windows_source_lease(root, lease_paths)
    try:
        leased_manifest = lease.read_source(spec.manifest_path, expected_sha256=expected_digest)
        if not hmac.compare_digest(leased_manifest, initial_manifest):
            raise SealedImportError("manifest_changed_before_lease")
        verified_manifest_files = parse_candidate_manifest(
            candidate, leased_manifest, expected_manifest_sha256=expected_digest
        )
        verified_files = dict(verified_manifest_files)
        verified_files.update(pins)
        if verified_files != all_files:
            raise SealedImportError("manifest_changed_before_lease")

        if _scan_source_inventory(
            package_root,
            spec.manifest_path,
            include_readonly_worker=(_FIXED_READONLY_WORKER_RELATIVE_PATH in all_files),
            include_readonly_bootstrap=(
                _FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH in all_files
            ),
            include_readonly_service_roles=bool(
                all_files.keys() & _FIXED_READONLY_SERVICE_ROLE_RELATIVE_PATHS
            ),
        ) != set(all_files):
            raise SealedImportError("source_inventory_mismatch")
        for relative, expected in all_files.items():
            lease.read_source(relative, expected_sha256=expected)

        return SealedSourceTree(
            candidate=candidate,
            source_root=Path(lease.root),
            manifest_sha256=expected_digest,
            files=MappingProxyType(all_files),
            stdlib_paths=checked_stdlib_paths,
            source_lease=lease,
        )
    except BaseException:
        try:
            lease.close()
        except WindowsSourceLeaseError:
            raise SealedImportError("source_lease_cleanup_failed") from None
        raise


class _SealedSourceLoader(importlib.abc.Loader):
    def __init__(
        self,
        seal: SealedSourceTree,
        finder: "SealedSourceFinder",
        fullname: str,
        relative: str,
        is_package: bool,
    ):
        self._seal = seal
        self._finder = finder
        self._fullname = fullname
        self._relative = relative
        self._is_package = is_package

    def create_module(self, spec):
        return None

    def is_package(self, fullname):
        return self._is_package

    def exec_module(self, module):
        self._finder._begin_module_execution(self, module)
        try:
            self._check_active()
            expected = self._seal.files.get(self._relative)
            if expected is None:
                raise SealedImportError("module_not_allowlisted")
            source = self._seal.source_lease.read_source(self._relative, expected_sha256=expected)
            if not hmac.compare_digest(hashlib.sha256(source).hexdigest(), expected):
                raise SealedImportError("source_digest_mismatch")
            origin = self._seal.source_root.joinpath(*PurePosixPath(self._relative).parts)
            code = compile(source, str(origin), "exec", dont_inherit=True)
            module.__file__ = str(origin)
            module.__cached__ = None
            if self._is_package:
                module.__path__ = [str(origin.parent)]
            exec(code, module.__dict__)
            self._finder._complete_module_execution(self, module)
        except BaseException:
            self._finder._abort_module_execution(self, module)
            raise

    def _check_active(self):
        _require_clean_after_install(self._seal, finder=self._finder)


class _SealedRuntimeStdlibLoader(importlib.abc.Loader):
    """Load one manifest-bound stdlib member through its runtime seal."""

    def __init__(self, runtime_seal, finder, entry):
        self._runtime_seal = runtime_seal
        self._finder = finder
        self._entry = entry
        self._fullname = entry.fullname
        self._spec = None
        self._extension_loader = (
            importlib.machinery.ExtensionFileLoader(self._fullname, entry.origin)
            if entry.kind == "extension"
            else None
        )

    def is_package(self, fullname):
        if fullname != self._fullname:
            raise ImportError("runtime_stdlib_name_mismatch")
        return self._entry.is_package

    def create_module(self, spec):
        if (
            spec is not self._spec
            or getattr(spec, "loader", None) is not self
            or getattr(spec, "origin", None) != self._entry.origin
            or self._runtime_seal is not self._finder._runtime_closure_identity
        ):
            raise ImportError("runtime_stdlib_spec_invalid")
        if self._entry.kind == "source":
            return None
        verified = self._runtime_seal.verify_stdlib_entry(self._fullname)
        if verified is not self._entry:
            raise ImportError("runtime_stdlib_entry_changed")
        return self._extension_loader.create_module(spec)

    def exec_module(self, module):
        self._finder._begin_runtime_stdlib_execution(self, module)
        try:
            _require_clean_after_install(self._finder._seal, finder=self._finder)
            verified = self._runtime_seal.verify_stdlib_entry(self._fullname)
            if verified is not self._entry:
                raise ImportError("runtime_stdlib_entry_changed")
            if self._entry.kind == "source":
                source = self._runtime_seal.read_stdlib_source(self._fullname)
                if (
                    type(source) is not bytes
                    or len(source) != self._entry.size
                    or not hmac.compare_digest(
                        hashlib.sha256(source).hexdigest(), self._entry.sha256
                    )
                ):
                    raise ImportError("runtime_stdlib_source_digest_mismatch")
                code = compile(source, self._entry.origin, "exec", dont_inherit=True)
                module.__file__ = self._entry.origin
                module.__cached__ = None
                if self._entry.is_package:
                    module.__path__ = [ntpath.dirname(self._entry.origin)]
                exec(code, module.__dict__)
            else:
                if self._extension_loader is None or self._entry.is_package:
                    raise ImportError("runtime_stdlib_extension_invalid")
                self._extension_loader.exec_module(module)
            self._finder._complete_runtime_stdlib_execution(self, module)
        except BaseException:
            self._finder._abort_runtime_stdlib_execution(self, module)
            raise


class SealedSourceFinder(importlib.abc.MetaPathFinder):
    """Own runtime imports and reject stdlib names outside the captured cache."""

    def __init__(self, seal: SealedSourceTree):
        self._seal = seal
        self._base_meta_path = tuple(sys.meta_path)
        self._base_path_hooks = tuple(sys.path_hooks)
        self._in_progress_modules = {}
        self._executed_modules = {}
        self._dependency_finder = None
        self._runtime_closure = None
        self._runtime_closure_identity = None
        self._runtime_stdlib_entries = {}
        self._runtime_stdlib_specs = {}
        self._runtime_stdlib_in_progress = {}
        self._runtime_stdlib_modules = {}
        self._fixed_role_modules = {}
        self._fixed_bootstrap_support_package = None
        self._fixed_bootstrap_support_modules = {}

    def attach_dependency_finder(self, dependency_finder) -> None:
        """Attach one fixed-root dependency finder without changing meta_path."""

        roots = getattr(dependency_finder, "top_level_roots", None)
        if (
            self._dependency_finder is not None
            or dependency_finder is None
            or type(roots) is not tuple
            or roots != _SEALED_DEPENDENCY_TOP_LEVEL_ROOTS
            or not callable(getattr(dependency_finder, "find_spec", None))
            or not callable(getattr(dependency_finder, "owns_module", None))
            or not callable(getattr(dependency_finder, "validate_current", None))
            or not sys.meta_path
            or sys.meta_path[0] is not self
        ):
            raise SealedImportError("dependency_finder_invalid")
        _require_clean_after_install(self._seal, finder=self)
        self._dependency_finder = dependency_finder

    def detach_dependency_finder(self, dependency_finder) -> None:
        """Detach only the exact dependency finder previously attached."""

        if self._dependency_finder is not dependency_finder:
            raise SealedImportError("dependency_finder_identity_mismatch")
        self._dependency_finder = None

    def attach_runtime_closure(self, runtime_seal) -> None:
        """Attach one exact runtime seal for late stdlib imports."""

        entries = getattr(runtime_seal, "stdlib_modules", None)
        methods = (
            "stdlib_entry",
            "read_stdlib_source",
            "verify_stdlib_entry",
            "verify_current",
        )
        if (
            self._runtime_closure is not None
            or runtime_seal is None
            or type(entries) is not tuple
            or not all(callable(getattr(runtime_seal, name, None)) for name in methods)
            or not sys.meta_path
            or sys.meta_path[0] is not self
        ):
            raise SealedImportError("runtime_closure_invalid")
        _require_clean_after_install(self._seal, finder=self)
        validator = runtime_seal.verify_current
        try:
            validator()
        except BaseException:
            raise SealedImportError("runtime_closure_invalid") from None

        entries_by_name = {}
        for entry in entries:
            fullname = getattr(entry, "fullname", None)
            origin = getattr(entry, "origin", None)
            kind = getattr(entry, "kind", None)
            is_package = getattr(entry, "is_package", None)
            digest = getattr(entry, "sha256", None)
            size = getattr(entry, "size", None)
            relative_path = getattr(entry, "relative_path", None)
            root_kind = getattr(entry, "root_kind", None)
            parts = fullname.split(".") if type(fullname) is str else ()
            if (
                not parts
                or any(not part.isidentifier() for part in parts)
                or parts[0] not in sys.stdlib_module_names
                or fullname in sys.builtin_module_names
                or type(origin) is not str
                or not os.path.isabs(origin)
                or not any(_path_is_root_or_beneath(origin, root) for root in self._seal.stdlib_paths)
                or kind not in {"source", "extension"}
                or type(is_package) is not bool
                or type(digest) is not str
                or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
                or type(size) is not int
                or size <= 0
                or type(relative_path) is not str
                or not relative_path
                or "\\" in relative_path
                or PurePosixPath(relative_path).is_absolute()
                or any(part in {"", ".", ".."} for part in PurePosixPath(relative_path).parts)
                or root_kind not in {"base", "venv"}
                or (kind == "source" and not origin.lower().endswith(".py"))
                or (kind == "extension" and (is_package or not origin.lower().endswith(".pyd")))
                or fullname in entries_by_name
            ):
                raise SealedImportError("runtime_stdlib_entry_invalid")
            try:
                if runtime_seal.stdlib_entry(fullname) is not entry:
                    raise SealedImportError("runtime_stdlib_entry_identity_mismatch")
                verified = runtime_seal.verify_stdlib_entry(fullname)
            except SealedImportError:
                raise
            except BaseException:
                raise SealedImportError("runtime_stdlib_entry_invalid") from None
            if verified is not entry:
                raise SealedImportError("runtime_stdlib_entry_identity_mismatch")
            entries_by_name[fullname] = entry

        # Hash-check source/extension files that were already imported by the
        # fixed bootstrap before the source finder was installed.
        for name, module in _BOOTSTRAP_MODULE_OBJECTS.items():
            if type(module) is not type(sys):
                continue
            module_spec = getattr(module, "__spec__", None)
            origin = getattr(module_spec, "origin", None)
            if type(origin) is not str or origin in {"built-in", "frozen"}:
                continue
            if not any(_path_is_root_or_beneath(origin, root) for root in self._seal.stdlib_paths):
                continue
            fullname = _MODULE_NAME_ALIASES.get(name, name)
            entry = entries_by_name.get(fullname)
            loader = getattr(module_spec, "loader", None)
            external = sys.modules.get("_frozen_importlib_external")
            expected_kind = (
                "source"
                if type(loader) is external.SourceFileLoader
                or type(loader) is sys.modules["zipimport"].zipimporter
                else "extension"
                if type(loader) is external.ExtensionFileLoader
                else None
            )
            if (
                entry is None
                or expected_kind != entry.kind
                or os.path.normcase(os.path.normpath(origin))
                != os.path.normcase(os.path.normpath(entry.origin))
            ):
                raise SealedImportError("runtime_bootstrap_stdlib_unpinned")
        self._runtime_stdlib_entries = entries_by_name
        self._runtime_closure = runtime_seal
        self._runtime_closure_identity = runtime_seal

    def detach_runtime_closure(self, runtime_seal) -> None:
        """Detach only the exact closure attached by this finder."""

        if self._runtime_closure is not runtime_seal:
            raise SealedImportError("runtime_closure_identity_mismatch")
        self._runtime_closure = None
        self._runtime_closure_identity = None

    def _begin_fixed_role_module(self, relative_path: str, module) -> None:
        """Temporarily register one verified data-only role during execution."""

        matches = [
            (name, spec)
            for name, spec in _FIXED_READONLY_ROLE_MODULES.items()
            if spec[0] == relative_path
        ]
        if relative_path == _FIXED_READONLY_TOKEN_HELPER_MODULE[0]:
            matches.append(("token_bootstrap", _FIXED_READONLY_TOKEN_HELPER_MODULE))
        if len(matches) != 1 or type(module) is not type(sys):
            raise SealedImportError("readonly_role_module_invalid")
        name, spec = matches[0]
        if name in self._fixed_role_modules or name in sys.modules:
            raise SealedImportError("readonly_role_module_already_active")
        module_spec = getattr(module, "__spec__", None)
        expected_origin = str(
            self._seal.source_root.joinpath(*PurePosixPath(relative_path).parts)
        )
        digest = self._seal.files.get(relative_path)
        if (
            type(digest) is not str
            or module.__name__ != spec[1]
            or module_spec is None
            or module_spec.name != spec[1]
            or module_spec.loader is not None
            or module_spec.origin != expected_origin
            or module.__file__ != expected_origin
            or module.__loader__ is not None
        ):
            raise SealedImportError("readonly_role_module_invalid")
        self._fixed_role_modules[name] = (module, module_spec, relative_path, digest)

    def _owns_fixed_role_module(self, fullname, module) -> bool:
        for _role, record in self._fixed_role_modules.items():
            expected_module, expected_spec, relative_path, digest = record
            if fullname != expected_module.__name__ or module is not expected_module:
                continue
            expected_origin = str(
                self._seal.source_root.joinpath(*PurePosixPath(relative_path).parts)
            )
            return (
                sys.modules.get(fullname) is module
                and getattr(module, "__spec__", None) is expected_spec
                and getattr(module, "__file__", None) == expected_origin
                and expected_spec.origin == expected_origin
                and self._seal.files.get(relative_path) == digest
            )
        return False

    def _begin_fixed_bootstrap_support_package(self, package, *, capability) -> None:
        """Register the one pathless package used by embedded support sources."""

        if (
            capability is not _FIXED_BOOTSTRAP_SUPPORT_REGISTRATION_TOKEN
            or type(self) is not SealedSourceFinder
            or self._seal.candidate != "i13_md"
            or self._fixed_bootstrap_support_package is not None
            or type(package) is not type(sys)
            or package.__name__ != "scripts"
            or "scripts" in sys.modules
            or any(name.startswith("scripts.") for name in sys.modules)
            or not sys.meta_path
            or sys.meta_path[0] is not self
        ):
            raise SealedImportError("bootstrap_support_package_invalid")
        _require_clean_after_install(self._seal, finder=self)
        package.__package__ = "scripts"
        package.__path__ = []
        package.__loader__ = None
        package.__file__ = None
        spec = importlib.machinery.ModuleSpec("scripts", None, is_package=True)
        spec.origin = _FIXED_BOOTSTRAP_SUPPORT_PACKAGE_ORIGIN
        spec.submodule_search_locations = []
        package.__spec__ = spec
        self._fixed_bootstrap_support_package = (package, spec)
        sys.modules["scripts"] = package

    def _load_fixed_bootstrap_support_module(
        self,
        relative_path: str,
        source: bytes,
        *,
        expected_sha256: str,
        capability,
    ):
        """Compile one exact embedded support module under the sealed scripts package."""

        fullname = _FIXED_BOOTSTRAP_SUPPORT_MODULES.get(relative_path)
        package_record = self._fixed_bootstrap_support_package
        if (
            capability is not _FIXED_BOOTSTRAP_SUPPORT_REGISTRATION_TOKEN
            or type(self) is not SealedSourceFinder
            or self._seal.candidate != "i13_md"
            or fullname is None
            or package_record is None
            or sys.modules.get("scripts") is not package_record[0]
            or getattr(package_record[0], "__spec__", None) is not package_record[1]
            or not sys.meta_path
            or sys.meta_path[0] is not self
            or fullname in sys.modules
            or fullname in self._fixed_bootstrap_support_modules
            or type(source) is not bytes
            or not source
            or type(expected_sha256) is not str
            or _SHA256_RE.fullmatch(expected_sha256) is None
        ):
            raise SealedImportError("bootstrap_support_module_binding_invalid")
        actual_sha256 = hashlib.sha256(source).hexdigest()
        if not hmac.compare_digest(actual_sha256, expected_sha256):
            raise SealedImportError("bootstrap_support_module_digest_mismatch")
        _require_clean_after_install(self._seal, finder=self)
        origin = str(self._seal.source_root.joinpath(*PurePosixPath(relative_path).parts))
        try:
            code = compile(source, origin, "exec", dont_inherit=True)
        except (SyntaxError, UnicodeError, ValueError):
            raise SealedImportError("bootstrap_support_module_invalid") from None
        module = type(sys)(fullname)
        spec = importlib.machinery.ModuleSpec(fullname, None, origin=origin)
        spec.cached = None
        module.__file__ = origin
        module.__cached__ = None
        module.__package__ = "scripts"
        module.__loader__ = None
        module.__spec__ = spec
        module.__embedded_source_sha256__ = actual_sha256
        self._fixed_bootstrap_support_modules[fullname] = (
            module,
            spec,
            relative_path,
            actual_sha256,
            False,
        )
        sys.modules[fullname] = module
        try:
            exec(code, module.__dict__)
            if sys.modules.get(fullname) is not module or module.__spec__ is not spec:
                raise SealedImportError("bootstrap_support_module_identity_mismatch")
            self._fixed_bootstrap_support_modules[fullname] = (
                module,
                spec,
                relative_path,
                actual_sha256,
                True,
            )
            _require_clean_after_install(self._seal, finder=self)
            return module
        except BaseException:
            if sys.modules.get(fullname) is module:
                del sys.modules[fullname]
            self._fixed_bootstrap_support_modules.pop(fullname, None)
            raise

    def _owns_fixed_bootstrap_support(self, fullname, module) -> bool:
        package_record = self._fixed_bootstrap_support_package
        if fullname == "scripts":
            if package_record is None or package_record[0] is not module:
                return False
            package, spec = package_record
            return (
                sys.modules.get("scripts") is package
                and type(package) is type(sys)
                and package.__name__ == "scripts"
                and package.__package__ == "scripts"
                and package.__path__ == []
                and package.__loader__ is None
                and package.__file__ is None
                and package.__spec__ is spec
                and spec.name == "scripts"
                and spec.loader is None
                and spec.origin == _FIXED_BOOTSTRAP_SUPPORT_PACKAGE_ORIGIN
                and spec.submodule_search_locations == []
            )
        record = self._fixed_bootstrap_support_modules.get(fullname)
        if record is None or record[0] is not module:
            return False
        expected_module, expected_spec, relative_path, digest, _complete = record
        expected_origin = str(
            self._seal.source_root.joinpath(*PurePosixPath(relative_path).parts)
        )
        return (
            fullname == _FIXED_BOOTSTRAP_SUPPORT_MODULES.get(relative_path)
            and sys.modules.get(fullname) is expected_module
            and type(module) is type(sys)
            and module.__name__ == fullname
            and module.__package__ == "scripts"
            and module.__file__ == expected_origin
            and module.__cached__ is None
            and module.__loader__ is None
            and module.__spec__ is expected_spec
            and expected_spec.name == fullname
            and expected_spec.loader is None
            and expected_spec.origin == expected_origin
            and expected_spec.cached is None
            and self._fixed_bootstrap_support_package is not None
            and sys.modules.get("scripts") is self._fixed_bootstrap_support_package[0]
            and module.__embedded_source_sha256__ == digest
            and bool(digest)
        )

    def _end_fixed_role_module(self, role: str, module) -> None:
        record = self._fixed_role_modules.get(role)
        if record is None or record[0] is not module:
            raise SealedImportError("readonly_role_module_identity_mismatch")
        fullname = record[1].name
        current = sys.modules.get(fullname)
        if current is not module:
            if fullname in sys.modules:
                del sys.modules[fullname]
            del self._fixed_role_modules[role]
            raise SealedImportError("readonly_role_module_identity_mismatch")
        del sys.modules[fullname]
        del self._fixed_role_modules[role]
        if module.__name__ != fullname or getattr(module, "__spec__", None) is not record[1]:
            raise SealedImportError("readonly_role_module_identity_mismatch")

    def _owns_runtime_stdlib_module(self, fullname, module) -> bool:
        entry = self._runtime_stdlib_entries.get(fullname)
        if entry is None:
            return False
        loader = self._runtime_stdlib_specs.get(fullname)
        in_progress = self._runtime_stdlib_in_progress.get(fullname) is module
        if loader is None:
            return False
        if not in_progress and self._runtime_stdlib_modules.get(fullname) is not module:
            return False
        spec = getattr(module, "__spec__", None)
        if (
            type(module) is not type(sys)
            or sys.modules.get(fullname) is not module
            or getattr(module, "__name__", None) != fullname
            or spec is not loader._spec
            or getattr(spec, "loader", None) is not loader
            or getattr(spec, "origin", None) != entry.origin
            or getattr(spec, "cached", None) is not None
            or getattr(module, "__loader__", None) is not loader
            or getattr(module, "__cached__", None) is not None
        ):
            return False
        module_file = getattr(module, "__file__", None)
        if module_file != entry.origin and not (in_progress and module_file is None):
            return False
        if entry.is_package:
            module_path = getattr(module, "__path__", None)
            if type(module_path) is not list or module_path != [ntpath.dirname(entry.origin)]:
                return False
        elif hasattr(module, "__path__"):
            return False
        return True

    def _begin_runtime_stdlib_execution(self, loader, module) -> None:
        fullname = loader._fullname
        if (
            self._runtime_closure is not loader._runtime_seal
            or self._runtime_closure_identity is not loader._runtime_seal
            or self._runtime_stdlib_specs.get(fullname) is not loader
            or sys.modules.get(fullname) is not module
            or fullname in self._runtime_stdlib_in_progress
            or not self._owns_runtime_stdlib_module_for_execution(loader, module)
        ):
            raise SealedImportError("runtime_stdlib_execution_state_invalid")
        self._runtime_stdlib_in_progress[fullname] = module

    def _owns_runtime_stdlib_module_for_execution(self, loader, module) -> bool:
        entry = self._runtime_stdlib_entries.get(loader._fullname)
        spec = getattr(module, "__spec__", None)
        return (
            entry is loader._entry
            and self._runtime_stdlib_specs.get(loader._fullname) is loader
            and type(module) is type(sys)
            and sys.modules.get(loader._fullname) is module
            and getattr(module, "__name__", None) == loader._fullname
            and spec is loader._spec
            and getattr(spec, "loader", None) is loader
            and getattr(spec, "origin", None) == entry.origin
            and getattr(spec, "cached", None) is None
            and getattr(module, "__loader__", None) is loader
            and (getattr(module, "__file__", None) in {None, entry.origin})
        )

    def _complete_runtime_stdlib_execution(self, loader, module) -> None:
        fullname = loader._fullname
        if (
            self._runtime_stdlib_in_progress.get(fullname) is not module
            or not self._owns_runtime_stdlib_module(loader._fullname, module)
        ):
            raise SealedImportError("runtime_stdlib_execution_state_invalid")
        del self._runtime_stdlib_in_progress[fullname]
        self._runtime_stdlib_modules[fullname] = module

    def _abort_runtime_stdlib_execution(self, loader, module) -> None:
        fullname = loader._fullname
        if self._runtime_stdlib_in_progress.get(fullname) is module:
            del self._runtime_stdlib_in_progress[fullname]

    def _loader_matches_module(self, loader, module, *, require_file: bool) -> bool:
        fullname = loader._fullname
        expected_relative = (
            fullname.replace(".", "/") + "/__init__.py"
            if loader._is_package
            else fullname.replace(".", "/") + ".py"
        )
        expected_origin = str(
            self._seal.source_root.joinpath(*PurePosixPath(expected_relative).parts)
        )
        module_spec = getattr(module, "__spec__", None)
        return (
            type(module) is type(sys)
            and getattr(module, "__name__", None) == fullname
            and getattr(module_spec, "name", None) == fullname
            and getattr(module_spec, "loader", None) is loader
            and getattr(module_spec, "origin", None) == expected_origin
            and getattr(module_spec, "cached", None) is None
            and getattr(module, "__loader__", None) is loader
            and (
                getattr(module, "__file__", None) == expected_origin
                if require_file
                else getattr(module, "__file__", None) in {None, expected_origin}
            )
            and loader._finder is self
            and loader._seal is self._seal
            and loader._relative == expected_relative
            and expected_relative in self._seal.files
        )

    def _was_executed_or_in_progress(self, fullname: str, module: object) -> bool:
        return (
            type(self._in_progress_modules) is dict
            and type(self._executed_modules) is dict
            and (
                self._in_progress_modules.get(fullname) is module
                or self._executed_modules.get(fullname) is module
            )
        )

    def _begin_module_execution(self, loader, module) -> None:
        fullname = loader._fullname
        if (
            type(self._in_progress_modules) is not dict
            or type(self._executed_modules) is not dict
            or sys.modules.get(fullname) is not module
            or not self._loader_matches_module(loader, module, require_file=False)
            or fullname in self._in_progress_modules
        ):
            raise SealedImportError("sealed_module_execution_state_invalid")
        previous = self._executed_modules.get(fullname)
        if previous is not None and previous is not module:
            raise SealedImportError("sealed_module_execution_state_invalid")
        self._executed_modules.pop(fullname, None)
        self._in_progress_modules[fullname] = module

    def _complete_module_execution(self, loader, module) -> None:
        fullname = loader._fullname
        if (
            self._in_progress_modules.get(fullname) is not module
            or sys.modules.get(fullname) is not module
            or not self._loader_matches_module(loader, module, require_file=True)
        ):
            raise SealedImportError("sealed_module_execution_state_invalid")
        del self._in_progress_modules[fullname]
        self._executed_modules[fullname] = module

    def _abort_module_execution(self, loader, module) -> None:
        fullname = loader._fullname
        if self._in_progress_modules.get(fullname) is module:
            del self._in_progress_modules[fullname]

    def find_spec(self, fullname, path=None, target=None):
        _require_clean_after_install(self._seal, finder=self)
        if fullname == "backtrader" or fullname.startswith("backtrader."):
            raise ModuleNotFoundError("unsealed_backtrader_namespace")
        if fullname == "site" or fullname in {"sitecustomize", "usercustomize"}:
            raise ModuleNotFoundError("site_import_blocked")
        if fullname == "backtrader_runtime" or fullname.startswith("backtrader_runtime."):
            if any(not part.isidentifier() for part in fullname.split(".")):
                raise ModuleNotFoundError("runtime_module_name_invalid")
            if fullname.endswith(".__init__"):
                raise ModuleNotFoundError("runtime_module_name_invalid")
            relative_base = fullname.replace(".", "/")
            package_relative = relative_base + "/__init__.py"
            module_relative = relative_base + ".py"
            if package_relative in self._seal.files:
                relative, is_package = package_relative, True
            elif module_relative in self._seal.files:
                relative, is_package = module_relative, False
            else:
                raise ModuleNotFoundError("runtime_module_not_allowlisted")
            loader = _SealedSourceLoader(self._seal, self, fullname, relative, is_package)
            spec = importlib.util.spec_from_loader(
                fullname,
                loader,
                origin=str(self._seal.source_root.joinpath(*PurePosixPath(relative).parts)),
                is_package=is_package,
            )
            if spec is None:
                raise SealedImportError("sealed_module_spec_unavailable")
            spec.cached = None
            if is_package:
                spec.submodule_search_locations = [
                    str(self._seal.source_root.joinpath(*PurePosixPath(relative).parts[:-1]))
                ]
            return spec

        root = fullname.partition(".")[0]
        if root in _SEALED_DEPENDENCY_TOP_LEVEL_ROOTS:
            dependency_finder = self._dependency_finder
            if dependency_finder is None:
                raise ModuleNotFoundError("sealed_dependency_finder_unavailable")
            validator = getattr(dependency_finder, "validate_current", None)
            delegate = getattr(dependency_finder, "find_spec", None)
            if not callable(validator) or not callable(delegate):
                raise ModuleNotFoundError("sealed_dependency_finder_invalid")
            try:
                validator()
                spec = delegate(fullname, path, target)
            except BaseException:
                raise ModuleNotFoundError("sealed_dependency_unavailable") from None
            if spec is None:
                raise ModuleNotFoundError("sealed_dependency_not_allowlisted")
            return spec
        if root not in sys.stdlib_module_names and root not in sys.builtin_module_names:
            raise ModuleNotFoundError("unsealed_external_module")
        runtime_seal = self._runtime_closure
        if runtime_seal is not None:
            if runtime_seal is not self._runtime_closure_identity:
                raise ModuleNotFoundError("runtime_closure_identity_mismatch")
            entry = self._runtime_stdlib_entries.get(fullname)
            if entry is not None:
                try:
                    verified = runtime_seal.verify_stdlib_entry(fullname)
                except BaseException:
                    raise ModuleNotFoundError("runtime_stdlib_unavailable") from None
                if verified is not entry:
                    raise ModuleNotFoundError("runtime_stdlib_entry_changed")
                loader = _SealedRuntimeStdlibLoader(runtime_seal, self, entry)
                spec = importlib.util.spec_from_loader(
                    fullname,
                    loader,
                    origin=entry.origin,
                    is_package=entry.is_package,
                )
                if spec is None:
                    raise SealedImportError("runtime_stdlib_spec_unavailable")
                spec.cached = None
                if entry.is_package:
                    spec.submodule_search_locations = [ntpath.dirname(entry.origin)]
                loader._spec = spec
                self._runtime_stdlib_specs[fullname] = loader
                return spec
        if (
            fullname not in _BOOTSTRAP_MODULE_OBJECTS
            or sys.modules.get(fullname) is not _BOOTSTRAP_MODULE_OBJECTS[fullname]
        ):
            raise ModuleNotFoundError("stdlib_module_outside_bootstrap_snapshot")
        raise ModuleNotFoundError("stdlib_module_not_preloaded")


def _require_clean_after_install(
    seal: SealedSourceTree, *, finder: Optional[SealedSourceFinder] = None
) -> None:
    _require_source_lease(seal)
    expected_paths = tuple(os.path.normcase(os.path.abspath(value)) for value in sys.path)
    if expected_paths != tuple(seal.stdlib_paths):
        raise SealedImportError("sys_path_changed")
    _check_post_bootstrap_state(seal=seal, finder=finder)
    if finder is not None and (not sys.meta_path or sys.meta_path[0] is not finder):
        raise SealedImportError("sealed_finder_not_first")


def validate_clean_bootstrap_import_state() -> None:
    """Require the captured stdlib bootstrap image before any source import."""

    _check_post_bootstrap_state()
    blocked = ("backtrader", "backtrader_runtime", "sitecustomize", "usercustomize")
    if any(
        name == prefix or name.startswith(prefix + ".")
        for name in sys.modules
        for prefix in blocked
    ):
        raise SealedImportError("bootstrap_preloaded_module_invalid")
    if tuple(sys.meta_path) != _BOOTSTRAP_META_PATH:
        raise SealedImportError("meta_path_changed")


def install_sealed_source_finder(seal: SealedSourceTree) -> SealedSourceFinder:
    """Install the strict finder as sys.meta_path[0] after a fresh-state check."""

    if not isinstance(seal, SealedSourceTree):
        raise SealedImportError("source_seal_invalid")
    _require_source_lease(seal)
    if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode:
        raise SealedImportError("isolated_startup_required")
    prefix = sys.pycache_prefix
    if type(prefix) is not str or not os.path.isabs(prefix) or os.path.exists(prefix):
        raise SealedImportError("pycache_prefix_not_fresh")
    try:
        validate_clean_bootstrap_import_state()
    except SealedImportError:
        raise
    except RuntimeError as error:
        raise SealedImportError(str(error)) from None
    blocked = ("backtrader", "backtrader_runtime", "sitecustomize", "usercustomize")
    if any(
        name == blocked_prefix or name.startswith(blocked_prefix + ".")
        for name in sys.modules
        for blocked_prefix in blocked
    ):
        raise SealedImportError("bootstrap_preloaded_module_invalid")
    if tuple(os.path.normcase(os.path.abspath(value)) for value in sys.path) != tuple(
        seal.stdlib_paths
    ):
        raise SealedImportError("sys_path_changed")
    finder = SealedSourceFinder(seal)
    sys.meta_path.insert(0, finder)
    if sys.meta_path[0] is not finder:
        raise SealedImportError("sealed_finder_install_failed")
    return finder


def import_sealed_candidate_module(seal: SealedSourceTree, finder: SealedSourceFinder):
    """Import only the fixed candidate entrypoint through its sealed loader.

    Callers must use this checked boundary rather than importing a candidate
    name directly: Python returns an existing ``sys.modules`` object without
    consulting ``sys.meta_path``.
    """

    if not isinstance(seal, SealedSourceTree) or not isinstance(finder, SealedSourceFinder):
        raise SealedImportError("source_seal_invalid")
    if finder._seal is not seal or finder not in sys.meta_path:
        raise SealedImportError("sealed_finder_invalid")
    _require_clean_after_install(seal, finder=finder)
    entrypoint = _candidate_spec(seal.candidate).entrypoint
    module = importlib.import_module(entrypoint)
    _require_clean_after_install(seal, finder=finder)
    module_spec = getattr(module, "__spec__", None)
    loader = getattr(module_spec, "loader", None)
    expected_relative = entrypoint.replace(".", "/") + ".py"
    if (
        sys.modules.get(entrypoint) is not module
        or type(loader) is not _SealedSourceLoader
        or loader._finder is not finder
        or loader._seal is not seal
        or loader._fullname != entrypoint
        or loader._relative != expected_relative
        or loader._is_package
        or getattr(module, "__cached__", None) is not None
        or getattr(module_spec, "cached", None) is not None
    ):
        raise SealedImportError("candidate_entrypoint_not_sealed")
    return module


def _open_fixed_readonly_role_module(
    seal: SealedSourceTree, finder: SealedSourceFinder, role: str
):
    """Compile one exact data-only role while the sealed finder is installed."""

    if (
        type(seal) is not SealedSourceTree
        or type(finder) is not SealedSourceFinder
        or seal.candidate != "i13_md"
        or finder._seal is not seal
        or not sys.meta_path
        or sys.meta_path[0] is not finder
    ):
        raise SealedImportError("readonly_role_dispatch_unavailable")
    if finder._dependency_finder is None:
        raise SealedImportError("readonly_role_dependency_closure_unavailable")
    if finder._runtime_closure is None:
        raise SealedImportError("readonly_role_runtime_closure_unavailable")
    if finder._runtime_closure_identity is not finder._runtime_closure:
        raise SealedImportError("readonly_role_runtime_closure_invalid")
    if role == "token_bootstrap":
        relative, module_name, _schema = _FIXED_READONLY_TOKEN_HELPER_MODULE
        if "request_coordinator" not in finder._fixed_role_modules:
            raise SealedImportError("readonly_token_helper_outside_coordinator")
    else:
        role_spec = _FIXED_READONLY_ROLE_MODULES.get(role)
        if role_spec is None:
            raise SealedImportError("readonly_role_not_fixed")
        relative, module_name, _schema, _entrypoint = role_spec
    if not _FIXED_READONLY_SERVICE_ROLE_RELATIVE_PATHS.issubset(seal.files):
        raise SealedImportError("readonly_service_role_sources_incomplete")
    required = {
        _FIXED_READONLY_WORKER_RELATIVE_PATH,
        _FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH,
        _FIXED_WORKER_DEPENDENCY_HELPER_RELATIVE_PATH,
    }
    if not required.issubset(seal.files):
        raise SealedImportError("readonly_service_role_bootstrap_unpinned")
    dependency_validator = getattr(finder._dependency_finder, "validate_current", None)
    runtime_validator = getattr(finder._runtime_closure, "verify_current", None)
    if (
        getattr(finder._dependency_finder, "top_level_roots", None)
        != _SEALED_DEPENDENCY_TOP_LEVEL_ROOTS
        or not all(
            callable(getattr(finder._dependency_finder, name, None))
            for name in ("find_spec", "owns_module", "validate_current")
        )
        or not all(
            callable(getattr(finder._runtime_closure, name, None))
            for name in (
                "stdlib_entry",
                "verify_stdlib_entry",
                "read_stdlib_source",
                "verify_current",
            )
        )
        or not callable(dependency_validator)
        or not callable(runtime_validator)
    ):
        raise SealedImportError("readonly_role_closure_unavailable")
    try:
        dependency_validator()
        runtime_validator()
    except BaseException:
        raise SealedImportError("readonly_role_closure_invalid") from None
    digest = _sha256(seal.files.get(relative), "readonly_role_source_unpinned")
    _require_clean_after_install(seal, finder=finder)
    try:
        source = seal.source_lease.read_source(relative, expected_sha256=digest)
    except WindowsSourceLeaseError as error:
        raise SealedImportError("readonly_role_source_unavailable") from error
    if type(source) is not bytes or not source:
        raise SealedImportError("readonly_role_source_invalid")
    try:
        code = compile(source, str(seal.source_root.joinpath(*PurePosixPath(relative).parts)), "exec", dont_inherit=True)
    except (SyntaxError, UnicodeError, ValueError):
        raise SealedImportError("readonly_role_source_invalid") from None
    if module_name in sys.modules:
        raise SealedImportError("readonly_role_module_already_active")
    module = type(sys)(module_name)
    origin = str(seal.source_root.joinpath(*PurePosixPath(relative).parts))
    module_spec = importlib.machinery.ModuleSpec(module_name, None, origin=origin)
    module.__file__ = origin
    module.__cached__ = None
    module.__package__ = ""
    module.__loader__ = None
    module.__spec__ = module_spec
    finder._begin_fixed_role_module(relative, module)
    sys.modules[module_name] = module
    try:
        exec(code, module.__dict__)
        if sys.modules.get(module_name) is not module or module.__spec__ is not module_spec:
            raise SealedImportError("readonly_role_module_identity_mismatch")
        _require_clean_after_install(seal, finder=finder)
        return module
    except BaseException:
        if module_name in sys.modules:
            del sys.modules[module_name]
        finder._fixed_role_modules.pop(role, None)
        raise


def run_fixed_readonly_service_role(
    seal: SealedSourceTree,
    finder: SealedSourceFinder,
    role: str,
    binding: object,
) -> int:
    """Reject role dispatch until the fixed bootstrap owns its runtime adapter.

    The role sources are data-only and are not invoked through caller-supplied
    runtime objects.  The fixed bootstrap must construct the narrow OS adapter
    itself before this boundary can be enabled.
    """

    if type(role) is not str or type(binding) is not dict:
        raise SealedImportError("readonly_role_binding_invalid")
    role_spec = _FIXED_READONLY_ROLE_MODULES.get(role)
    if role_spec is None or binding.get("schema") != role_spec[2]:
        raise SealedImportError("readonly_role_binding_invalid")
    raise SealedImportError("readonly_role_runtime_factory_unavailable")


def run_fixed_readonly_token_bootstrap(
    seal: SealedSourceTree,
    finder: SealedSourceFinder,
    raw: bytes,
    *,
    request_id: str,
    nonce: str,
    owner_sid: str,
):
    """Reject token application until a fixed coordinator adapter exists."""

    if (
        type(finder) is not SealedSourceFinder
        or "request_coordinator" not in finder._fixed_role_modules
    ):
        raise SealedImportError("readonly_token_helper_outside_coordinator")
    raise SealedImportError("readonly_token_runtime_adapter_unavailable")


__all__ = [
    "CANDIDATES",
    "SealedImportError",
    "SealedSourceFinder",
    "SealedSourceTree",
    "WindowsFileIdentity",
    "WindowsSourceLease",
    "WindowsSourceLeaseError",
    "acquire_windows_source_lease",
    "install_sealed_source_finder",
    "import_sealed_candidate_module",
    "parse_candidate_manifest",
    "seal_candidate_source_tree",
    "retry_pending_windows_source_lease_cleanup",
    "validate_fixed_venv_binding",
    "validate_clean_bootstrap_import_state",
    "validate_stdlib_roots",
]
