"""Fail-closed artifact-first binding for the settlement evidence SDK.

This candidate deliberately has no production artifact pin.  Its pure
validation helpers are exercised with synthetic distributions; the runtime
entrypoint refuses before importing bt_api_ctp until an independently
reviewed wheel/RECORD/native-extension pin is added in code.
"""

from __future__ import annotations

import base64
import builtins
import csv
import hashlib
import hmac
import importlib
import importlib._bootstrap_external
import importlib.abc
import importlib.machinery
import io
import os
import re
import stat
import sys
import zipimport
from collections.abc import Mapping
from dataclasses import dataclass, field
from email.parser import Parser
from types import ModuleType
from typing import Optional

from backtrader_runtime.ctp_windows_artifact_custody import (
    WindowsArtifactCustody,
    WindowsArtifactCustodyError,
)

_DIST_NAME = "bt_api_ctp"
_EVIDENCE_MODULE = "bt_api_ctp.containers.ctp.ctp_native_query_certificate"
_LOWER_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_ORIGINAL_IMPORT = builtins.__import__
_TRUSTED_IMPORTLIB_MODULE = importlib
_TRUSTED_MACHINERY_MODULE = importlib.machinery
_TRUSTED_IMPORTLIB_UTIL_MODULE = importlib.util
_TRUSTED_MODULE_SPEC = importlib.machinery.ModuleSpec
_TRUSTED_MODULE_FROM_SPEC = importlib.util.module_from_spec
_TRUSTED_BUILTIN_IMPORTER = importlib.machinery.BuiltinImporter
_TRUSTED_FROZEN_IMPORTER = importlib.machinery.FrozenImporter
_TRUSTED_PATH_FINDER = importlib.machinery.PathFinder
_TRUSTED_BUILTIN_FIND_SPEC = vars(_TRUSTED_BUILTIN_IMPORTER).get("find_spec")
_TRUSTED_FROZEN_FIND_SPEC = vars(_TRUSTED_FROZEN_IMPORTER).get("find_spec")
_TRUSTED_PATH_FIND_SPEC = vars(_TRUSTED_PATH_FINDER).get("find_spec")
_TRUSTED_EXTENSION_FILE_LOADER = importlib.machinery.ExtensionFileLoader
_TRUSTED_EXTENSION_CREATE_MODULE = vars(_TRUSTED_EXTENSION_FILE_LOADER).get(
    "create_module"
)
_TRUSTED_EXTENSION_EXEC_MODULE = vars(_TRUSTED_EXTENSION_FILE_LOADER).get("exec_module")


def _assert_trusted_importlib_runtime() -> None:
    """Reject same-process replacement of the import machinery used by the gate."""

    machinery = _TRUSTED_MACHINERY_MODULE
    loader = _TRUSTED_EXTENSION_FILE_LOADER
    if (
        importlib is not _TRUSTED_IMPORTLIB_MODULE
        or sys.modules.get("importlib") is not _TRUSTED_IMPORTLIB_MODULE
        or getattr(_TRUSTED_IMPORTLIB_MODULE, "machinery", None) is not machinery
        or sys.modules.get("importlib.machinery") is not machinery
        or getattr(_TRUSTED_IMPORTLIB_MODULE, "util", None)
        is not _TRUSTED_IMPORTLIB_UTIL_MODULE
        or sys.modules.get("importlib.util") is not _TRUSTED_IMPORTLIB_UTIL_MODULE
        or getattr(machinery, "ModuleSpec", None) is not _TRUSTED_MODULE_SPEC
        or getattr(_TRUSTED_IMPORTLIB_UTIL_MODULE, "module_from_spec", None)
        is not _TRUSTED_MODULE_FROM_SPEC
        or getattr(machinery, "BuiltinImporter", None) is not _TRUSTED_BUILTIN_IMPORTER
        or getattr(machinery, "FrozenImporter", None) is not _TRUSTED_FROZEN_IMPORTER
        or getattr(machinery, "PathFinder", None) is not _TRUSTED_PATH_FINDER
        or vars(_TRUSTED_BUILTIN_IMPORTER).get("find_spec")
        is not _TRUSTED_BUILTIN_FIND_SPEC
        or vars(_TRUSTED_FROZEN_IMPORTER).get("find_spec")
        is not _TRUSTED_FROZEN_FIND_SPEC
        or vars(_TRUSTED_PATH_FINDER).get("find_spec") is not _TRUSTED_PATH_FIND_SPEC
        or getattr(machinery, "ExtensionFileLoader", None) is not loader
        or vars(loader).get("create_module") is not _TRUSTED_EXTENSION_CREATE_MODULE
        or vars(loader).get("exec_module") is not _TRUSTED_EXTENSION_EXEC_MODULE
    ):
        _fail("sdk_artifact_importlib_machinery_changed")


class CtpSdkArtifactBindingError(RuntimeError):
    """The installed SDK artifact cannot be bound to an approved identity."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class CtpSdkArtifactPolicy:
    """Code-owned exact installed-distribution expectations.

    ``record_sha256`` pins the complete installed RECORD inventory. ``files``
    independently pins relevant source and platform extension bytes. The
    policy is not accepted from a public function argument.
    """

    distribution_name: str
    version: str
    record_sha256: str
    source_manifest_sha256: str
    files: Mapping[str, str]
    module_files: Mapping[str, str]
    extension_paths: tuple[str, ...]


@dataclass(frozen=True)
class VerifiedCtpSdkArtifact:
    distribution_root: str
    package_root: str
    dist_info_root: str
    version: str
    record_sha256: str
    source_manifest_sha256: str
    file_sha256: tuple[tuple[str, str], ...]
    module_origins: tuple[tuple[str, str], ...]
    extension_paths: tuple[str, ...]
    custody: WindowsArtifactCustody | None = field(
        default=None, repr=False, compare=False
    )


# A candidate may set this only after an installed wheel, complete RECORD,
# source files, native extension, and external release identity are reviewed.
# Never replace None with a candidate/source-tree hash as a production pin.
_CODE_OWNED_ARTIFACT_POLICY: Optional[CtpSdkArtifactPolicy] = None  # noqa: UP045
_CODE_OWNED_VERIFIER_CACHE: Optional["_CodeOwnedSettlementEvidenceVerifier"] = None  # noqa: UP045, UP037
_CODE_OWNED_IMPORTER: Optional["_PinnedSdkImporter"] = None  # noqa: UP045, UP037


def _fail(reason: str) -> None:
    raise CtpSdkArtifactBindingError(reason)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _norm_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _absolute(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _is_within(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((_absolute(path), _absolute(root))) == _absolute(root)
    except (OSError, ValueError):
        return False


def _reject_link_components(path: str, root: str) -> None:
    """Reject symlink components; deployment ACL/reparse checks remain external."""

    absolute_root = os.path.abspath(root)
    absolute_path = os.path.abspath(path)
    if not _is_within(absolute_path, absolute_root):
        _fail("sdk_artifact_path_escape")
    relative = os.path.relpath(absolute_path, absolute_root)
    current = absolute_root
    for part in relative.split(os.sep):
        current = os.path.join(current, part)
        try:
            mode = os.lstat(current).st_mode
        except OSError:
            _fail("sdk_artifact_file_missing")
        if stat.S_ISLNK(mode):
            _fail("sdk_artifact_reparse_or_symlink")


def _read_regular_file(
    path: str, root: str, custody: WindowsArtifactCustody | None = None
) -> bytes:
    _reject_link_components(path, root)
    if custody is not None:
        relative = os.path.relpath(path, root).replace(os.sep, "/")
        try:
            return custody.read(relative)
        except WindowsArtifactCustodyError:
            _fail("sdk_artifact_retained_file_read_failed")
    try:
        info = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            _fail("sdk_artifact_not_regular_file")
        with open(path, "rb") as stream:
            data = stream.read()
    except CtpSdkArtifactBindingError:
        raise
    except OSError:
        _fail("sdk_artifact_file_unavailable")
    return data


def _parse_metadata(raw: bytes) -> tuple[str, str]:
    try:
        message = Parser().parsestr(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        _fail("sdk_artifact_metadata_invalid")
    names = message.get_all("Name", [])
    versions = message.get_all("Version", [])
    if len(names) != 1 or len(versions) != 1:
        _fail("sdk_artifact_metadata_identity_invalid")
    return names[0], versions[0]


def _decode_record_hash(value: str) -> str:
    if not value.startswith("sha256="):
        _fail("sdk_artifact_record_hash_algorithm_invalid")
    encoded = value[7:]
    try:
        digest = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (ValueError, TypeError):
        _fail("sdk_artifact_record_hash_invalid")
    if len(digest) != 32:
        _fail("sdk_artifact_record_hash_invalid")
    return digest.hex()


def _safe_record_relative(relative: str) -> str:
    if (
        type(relative) is not str
        or not relative
        or "\\" in relative
        or "\x00" in relative
        or relative.startswith("/")
        or any(part in ("", ".", "..") for part in relative.split("/"))
    ):
        _fail("sdk_artifact_record_path_invalid")
    return relative


def _package_inventory(package_root: str, distribution_root: str) -> set[str]:
    inventory: set[str] = set()
    for current, dirs, files in os.walk(package_root, topdown=True, followlinks=False):
        for name in list(dirs):
            path = os.path.join(current, name)
            if os.path.islink(path):
                _fail("sdk_artifact_reparse_or_symlink")
            if name == "__pycache__":
                _fail("sdk_artifact_bytecode_cache_present")
        for name in files:
            path = os.path.join(current, name)
            if name.lower().endswith(".pyc") or os.path.islink(path):
                _fail("sdk_artifact_unsealed_package_file")
            if not os.path.isfile(path):
                _fail("sdk_artifact_not_regular_file")
            rel = os.path.relpath(path, distribution_root).replace(os.sep, "/")
            inventory.add(rel)
    return inventory


def _verify_distribution_tree(
    *,
    distribution_root: str,
    package_root: str,
    dist_info_root: str,
    policy: CtpSdkArtifactPolicy,
    custody: WindowsArtifactCustody | None = None,
) -> tuple[tuple[str, str], ...]:
    root = _absolute(distribution_root)
    package = _absolute(package_root)
    dist_info = _absolute(dist_info_root)
    if not _is_within(package, root) or not _is_within(dist_info, root):
        _fail("sdk_artifact_root_mismatch")
    expected_dist_info = (
        _norm_name(policy.distribution_name + "-" + policy.version) + ".dist-info"
    )
    if (
        _norm_name(os.path.basename(dist_info)[:-10]) + ".dist-info"
        != expected_dist_info
    ):
        _fail("sdk_artifact_dist_info_name_mismatch")
    metadata_raw = _read_regular_file(
        os.path.join(dist_info, "METADATA"), root, custody
    )
    metadata_name, metadata_version = _parse_metadata(metadata_raw)
    if (
        _norm_name(metadata_name) != _norm_name(policy.distribution_name)
        or metadata_version != policy.version
    ):
        _fail("sdk_artifact_distribution_identity_mismatch")

    record_path = os.path.join(dist_info, "RECORD")
    record_raw = _read_regular_file(record_path, root, custody)
    if (
        type(policy.record_sha256) is not str
        or not _LOWER_HEX64_RE.fullmatch(policy.record_sha256)
        or not hmac.compare_digest(_sha256(record_raw), policy.record_sha256)
    ):
        _fail("sdk_artifact_record_digest_mismatch")
    try:
        rows = list(csv.reader(io.StringIO(record_raw.decode("utf-8"), newline="")))
    except (UnicodeError, csv.Error):
        _fail("sdk_artifact_record_invalid")
    if not rows or any(len(row) != 3 for row in rows):
        _fail("sdk_artifact_record_invalid")
    entries: dict[str, tuple[str, int]] = {}
    for relative, record_hash, record_size in rows:
        relative = _safe_record_relative(relative)
        if relative in entries:
            _fail("sdk_artifact_record_duplicate_path")
        if relative == os.path.relpath(record_path, root).replace(os.sep, "/"):
            if record_hash or record_size:
                _fail("sdk_artifact_record_self_hash_invalid")
            entries[relative] = ("", -1)
            continue
        if not record_size.isdigit():
            _fail("sdk_artifact_record_size_invalid")
        digest = _decode_record_hash(record_hash)
        path = os.path.join(root, *relative.split("/"))
        raw = _read_regular_file(path, root, custody)
        if len(raw) != int(record_size) or _sha256(raw) != digest:
            _fail("sdk_artifact_record_file_mismatch")
        entries[relative] = (digest, len(raw))

    expected = dict(policy.files)
    if not expected or any(
        type(path) is not str
        or _safe_record_relative(path) != path
        or type(digest) is not str
        or not _LOWER_HEX64_RE.fullmatch(digest)
        for path, digest in expected.items()
    ):
        _fail("sdk_artifact_policy_invalid")
    for relative, expected_digest in expected.items():
        row = entries.get(relative)
        if row is None or row[0] != expected_digest:
            _fail("sdk_artifact_pinned_file_mismatch")
    package_prefix = os.path.relpath(package, root).replace(os.sep, "/") + "/"
    record_package_files = {
        path
        for path in entries
        if path.startswith(package_prefix) and path != package_prefix
    }
    if _package_inventory(package, root) != record_package_files:
        _fail("sdk_artifact_package_inventory_mismatch")
    if not policy.extension_paths or any(
        path not in expected
        or not path.startswith(package_prefix)
        or not path.lower().endswith((".pyd", ".so", ".dylib"))
        or not any(
            path.lower().endswith(suffix.lower())
            for suffix in importlib.machinery.EXTENSION_SUFFIXES
        )
        for path in policy.extension_paths
    ):
        _fail("sdk_artifact_native_extension_unpinned")
    if not policy.module_files:
        _fail("sdk_artifact_module_map_missing")
    for fullname, relative in policy.module_files.items():
        if type(fullname) is not str or not (
            fullname == _DIST_NAME or fullname.startswith(_DIST_NAME + ".")
        ):
            _fail("sdk_artifact_module_map_invalid")
        if (
            relative not in expected
            or not relative.startswith(package_prefix)
            or not relative.endswith(".py")
        ):
            _fail("sdk_artifact_module_source_unpinned")
    if policy.module_files.get(_DIST_NAME) != package_prefix + "__init__.py":
        _fail("sdk_artifact_package_initializer_unpinned")
    return tuple(sorted((path, digest) for path, digest in expected.items()))


def _acquire_windows_artifact_custody(
    *, distribution_root: str, dist_info_root: str, policy: CtpSdkArtifactPolicy
) -> WindowsArtifactCustody:
    """Lock every RECORD member before the final validation/import pass.

    The initial RECORD read is untrusted discovery. Its digest is checked
    against the code-owned policy before any listed path is used, then the
    record itself is retained first. Every referenced member is acquired from
    the same distribution root with share-read-only handles and checked again
    through those handles by ``_verify_distribution_tree``.
    """

    if os.name != "nt":
        _fail("sdk_artifact_windows_custody_required")
    root = _absolute(distribution_root)
    record_path = os.path.join(_absolute(dist_info_root), "RECORD")
    record_relative = os.path.relpath(record_path, root).replace(os.sep, "/")
    _safe_record_relative(record_relative)
    if not _LOWER_HEX64_RE.fullmatch(policy.record_sha256):
        _fail("sdk_artifact_record_digest_mismatch")
    preliminary = _read_regular_file(record_path, root)
    if not hmac.compare_digest(_sha256(preliminary), policy.record_sha256):
        _fail("sdk_artifact_record_digest_mismatch")
    try:
        rows = list(csv.reader(io.StringIO(preliminary.decode("utf-8"), newline="")))
    except (UnicodeError, csv.Error):
        _fail("sdk_artifact_record_invalid")
    if not rows or any(len(row) != 3 for row in rows):
        _fail("sdk_artifact_record_invalid")
    members: dict[str, str] = {}
    saw_record = False
    for relative, record_hash, record_size in rows:
        relative = _safe_record_relative(relative)
        if relative in members:
            _fail("sdk_artifact_record_duplicate_path")
        if relative == record_relative:
            if record_hash or record_size:
                _fail("sdk_artifact_record_self_hash_invalid")
            members[relative] = policy.record_sha256
            saw_record = True
            continue
        if not record_size.isdigit():
            _fail("sdk_artifact_record_size_invalid")
        members[relative] = _decode_record_hash(record_hash)
    if not saw_record:
        _fail("sdk_artifact_record_self_hash_invalid")
    for relative, digest in policy.files.items():
        if members.get(relative) != digest:
            _fail("sdk_artifact_pinned_file_mismatch")

    # First retain RECORD alone so a concurrent writer cannot change the
    # member list while the remaining file handles are being acquired.
    record_custody = WindowsArtifactCustody.acquire(
        root,
        (record_relative,),
        expected_sha256={record_relative: policy.record_sha256},
    )
    try:
        locked_record = record_custody.read(record_relative)
        if not hmac.compare_digest(_sha256(locked_record), policy.record_sha256):
            _fail("sdk_artifact_record_digest_mismatch")
        if locked_record != preliminary:
            _fail("sdk_artifact_record_changed_during_lock")
        custody = WindowsArtifactCustody.acquire(
            root,
            tuple(members),
            expected_sha256=members,
        )
        custody.verify_current()
        if custody.read(record_relative) != locked_record:
            custody.close()
            _fail("sdk_artifact_record_changed_during_lock")
        return custody
    finally:
        record_custody.close()


def _discover_and_verify(policy: CtpSdkArtifactPolicy) -> VerifiedCtpSdkArtifact:
    if sys.dont_write_bytecode is not True:
        _fail("sdk_artifact_requires_no_bytecode")
    _require_standard_import_chain()
    if any(
        name == _DIST_NAME or name.startswith(_DIST_NAME + ".") for name in sys.modules
    ):
        _fail("sdk_artifact_check_after_import")
    search_roots = _verified_search_roots()
    packages: list[tuple[str, str]] = []
    dist_infos: list[tuple[str, str]] = []
    for root in search_roots:
        package = os.path.join(root, _DIST_NAME)
        if os.path.isdir(package):
            packages.append((root, _absolute(package)))
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for name in names:
            lower = name.lower()
            if lower.endswith(".dist-info") and _norm_name(name[:-10]).startswith(
                _norm_name(policy.distribution_name) + "-"
            ):
                dist_infos.append((root, _absolute(os.path.join(root, name))))
    if len(packages) != 1 or len(dist_infos) != 1:
        _fail("sdk_artifact_installation_not_unique")
    package_root = packages[0][1]
    if packages[0][0] != dist_infos[0][0]:
        _fail("sdk_artifact_distribution_root_mismatch")
    distribution_root = packages[0][0]
    source_hashes = _verify_distribution_tree(
        distribution_root=distribution_root,
        package_root=package_root,
        dist_info_root=dist_infos[0][1],
        policy=policy,
    )
    if (
        type(policy.source_manifest_sha256) is not str
        or not _LOWER_HEX64_RE.fullmatch(policy.source_manifest_sha256)
        or not policy.module_files
    ):
        _fail("sdk_artifact_source_manifest_unpinned")
    try:
        custody = _acquire_windows_artifact_custody(
            distribution_root=distribution_root,
            dist_info_root=dist_infos[0][1],
            policy=policy,
        )
    except WindowsArtifactCustodyError:
        _fail("sdk_artifact_custody_acquire_failed")
    try:
        locked_hashes = _verify_distribution_tree(
            distribution_root=distribution_root,
            package_root=package_root,
            dist_info_root=dist_infos[0][1],
            policy=policy,
            custody=custody,
        )
        if locked_hashes != source_hashes:
            _fail("sdk_artifact_inventory_changed_during_lock")
        return VerifiedCtpSdkArtifact(
            distribution_root=distribution_root,
            package_root=package_root,
            dist_info_root=dist_infos[0][1],
            version=policy.version,
            record_sha256=policy.record_sha256,
            source_manifest_sha256=policy.source_manifest_sha256,
            file_sha256=source_hashes,
            module_origins=tuple(
                sorted(
                    (
                        name,
                        _absolute(
                            os.path.join(distribution_root, *relative.split("/"))
                        ),
                    )
                    for name, relative in policy.module_files.items()
                )
            ),
            extension_paths=tuple(
                _absolute(os.path.join(distribution_root, *relative.split("/")))
                for relative in policy.extension_paths
            ),
            custody=custody,
        )
    except BaseException:
        custody.close()
        raise


class _RetainedSourceLoader(importlib.abc.Loader):
    """Compile one exact Python source module from a retained file handle."""

    def __init__(
        self,
        importer: _PinnedSdkImporter,
        fullname: str,
        relative_path: str,
        origin: str,
        expected_sha256: str,
        is_package: bool,
    ) -> None:
        self.name = fullname
        self.path = origin
        self._importer = importer
        self._relative_path = relative_path
        self._expected_sha256 = expected_sha256
        self._is_package = is_package

    def create_module(self, _spec: object) -> None:
        return None

    def exec_module(self, module: ModuleType) -> None:
        self._importer.begin_loader_exec(module, self.name, self)
        self._importer.assert_context()
        custody = self._importer.artifact.custody
        if custody is None:
            _fail("sdk_artifact_windows_custody_required")
        try:
            raw = custody.read(self._relative_path)
        except WindowsArtifactCustodyError:
            _fail("sdk_artifact_retained_source_unavailable")
        if not hmac.compare_digest(_sha256(raw), self._expected_sha256):
            _fail("sdk_artifact_retained_source_hash_mismatch")
        module.__file__ = self.path
        module.__cached__ = None
        if self._is_package:
            module.__path__ = [os.path.dirname(self.path)]
        builtins_map = dict(vars(builtins))
        builtins_map["__import__"] = self._importer.guarded_import
        module.__dict__["__builtins__"] = builtins_map
        code = compile(raw, self.path, "exec", dont_inherit=True)
        # The code object comes only from source bytes re-read from the retained,
        # hash-verified installation handle above; never from caller text.
        exec(code, module.__dict__)  # noqa: S102
        self._importer.assert_context()
        self._importer.finish_loader_exec(module, self.name, self)


class _PinnedExtensionLoader(importlib.abc.Loader):
    """Delegate one extension load only after its path is handle-pinned."""

    def __init__(
        self, importer: _PinnedSdkImporter, fullname: str, origin: str
    ) -> None:
        importer.assert_context()
        self.name = fullname
        self.path = origin
        self._importer = importer
        self._delegate = _TRUSTED_EXTENSION_FILE_LOADER(fullname, origin)

    def create_module(self, spec: object) -> ModuleType | None:
        self._importer.assert_context()
        self._importer.verify_extension_path(self.name, self.path)
        self._importer.assert_trusted_extension_delegate(
            self._delegate, self.name, self.path
        )
        return _TRUSTED_EXTENSION_CREATE_MODULE(self._delegate, spec)

    def exec_module(self, module: ModuleType) -> None:
        self._importer.begin_loader_exec(module, self.name, self)
        self._importer.verify_extension_path(self.name, self.path)
        # The digest read itself may run in the presence of a same-process
        # mutation hook; revalidate machinery immediately before entering the
        # platform loader and invoke the code-owned method descriptor directly.
        self._importer.assert_trusted_extension_delegate(
            self._delegate, self.name, self.path
        )
        _TRUSTED_EXTENSION_EXEC_MODULE(self._delegate, module)
        self._importer.assert_context()
        self._importer.finish_loader_exec(module, self.name, self)


class _PinnedSdkImporter(importlib.abc.MetaPathFinder):
    """Load only code-pinned SDK modules and reject all package fallbacks."""

    def __init__(self, artifact: VerifiedCtpSdkArtifact) -> None:
        if artifact.custody is None:
            _fail("sdk_artifact_windows_custody_required")
        self.artifact = artifact
        self._source_modules: dict[str, tuple[str, str, str, bool]] = {}
        hashes = dict(artifact.file_sha256)
        for fullname, origin in artifact.module_origins:
            relative = os.path.relpath(origin, artifact.distribution_root).replace(
                os.sep, "/"
            )
            digest = hashes.get(relative)
            if digest is None:
                _fail("sdk_artifact_module_source_unpinned")
            self._source_modules[fullname] = (
                relative,
                origin,
                digest,
                relative.endswith("/__init__.py"),
            )
        self._loaded: dict[str, ModuleType] = {}
        self._pending: dict[str, ModuleType] = {}
        self._loaders: dict[str, object] = {}
        self._specs: dict[str, object] = {}
        self._original_path: object = None
        self._original_meta_path: object = None
        self._original_path_hooks: object = None
        self._original_importer_cache: object = None
        self._path_entries: tuple[object, ...] = ()
        self._path_tuple: tuple[object, ...] = ()
        self._hooks_tuple: tuple[object, ...] = ()
        self._meta_tuple: tuple[object, ...] = ()
        self._cache_snapshot: tuple[tuple[object, object], ...] = ()
        self._installed = False

    def install(self) -> None:
        if self._installed:
            _fail("sdk_artifact_importer_already_installed")
        _require_standard_import_chain()
        _verified_search_roots()
        if any(
            name == _DIST_NAME or name.startswith(_DIST_NAME + ".")
            for name in sys.modules
        ):
            _fail("sdk_artifact_check_after_import")
        self._original_path = sys.path
        self._original_meta_path = sys.meta_path
        self._original_path_hooks = sys.path_hooks
        self._original_importer_cache = sys.path_importer_cache
        self._path_entries = tuple(sys.path)
        self._path_tuple = tuple(sys.path)
        self._hooks_tuple = tuple(sys.path_hooks)
        self._cache_snapshot = tuple(sys.path_importer_cache.items())
        self._meta_tuple = (
            importlib.machinery.BuiltinImporter,
            importlib.machinery.FrozenImporter,
            self,
            importlib.machinery.PathFinder,
        )
        # Immutable sequences prevent accidental in-place changes during the
        # import phase. Every custom source loader rechecks object identity and
        # contents before and after executing pinned bytes.
        sys.path = self._path_tuple
        sys.path_hooks = self._hooks_tuple
        sys.meta_path = self._meta_tuple
        self._installed = True
        self.assert_context()

    def assert_context(self) -> None:
        if not self._installed:
            _fail("sdk_artifact_importer_not_installed")
        _assert_trusted_importlib_runtime()
        if (
            sys.path is not self._path_tuple
            or tuple(sys.path) != self._path_entries
            or sys.path_hooks is not self._hooks_tuple
            or tuple(sys.path_hooks) != self._hooks_tuple
            or sys.meta_path is not self._meta_tuple
            or tuple(sys.meta_path) != self._meta_tuple
            or sys.path_importer_cache is not self._original_importer_cache
        ):
            _fail("sdk_artifact_import_environment_changed")
        current_cache = tuple(sys.path_importer_cache.items())
        if len(current_cache) != len(self._cache_snapshot):
            _fail("sdk_artifact_importer_cache_changed")
        old_cache = {key: value for key, value in self._cache_snapshot}
        if any(
            key not in old_cache or old_cache[key] is not value
            for key, value in current_cache
        ):
            _fail("sdk_artifact_importer_cache_changed")
        for name, module in tuple(sys.modules.items()):
            if name == _DIST_NAME or name.startswith(_DIST_NAME + "."):
                expected = self._loaded.get(name) or self._pending.get(name)
                if expected is not module:
                    _fail("sdk_artifact_sys_modules_spoof")

    def assert_trusted_extension_delegate(
        self, delegate: object, fullname: str, origin: str
    ) -> None:
        _assert_trusted_importlib_runtime()
        if (
            type(delegate) is not _TRUSTED_EXTENSION_FILE_LOADER
            or getattr(delegate, "name", None) != fullname
            or _absolute(getattr(delegate, "path", "")) != _absolute(origin)
        ):
            _fail("sdk_artifact_native_loader_identity_mismatch")

    def find_spec(
        self, fullname: str, path: object = None, target: object = None
    ) -> object:
        if fullname == _DIST_NAME or fullname.startswith(_DIST_NAME + "."):
            self.assert_context()
            if (
                fullname not in self._source_modules
                and fullname != "bt_api_ctp.ctp._ctp"
            ):
                _fail("sdk_artifact_unpinned_module_import")
            return self._spec_for(fullname)
        return None

    def _spec_for(self, fullname: str) -> object:
        if fullname in self._source_modules:
            relative, origin, digest, is_package = self._source_modules[fullname]
            loader = _RetainedSourceLoader(
                self, fullname, relative, origin, digest, is_package
            )
            self._loaders[fullname] = loader
            spec = _TRUSTED_MODULE_SPEC(
                fullname,
                loader,
                origin=origin,
                is_package=is_package,
            )
        elif fullname == "bt_api_ctp.ctp._ctp":
            matches = [
                path
                for path in self.artifact.extension_paths
                if os.path.basename(path).lower().startswith("_ctp")
            ]
            if len(matches) != 1:
                _fail("sdk_artifact_native_extension_unpinned")
            origin = matches[0]
            loader = _PinnedExtensionLoader(self, fullname, origin)
            self._loaders[fullname] = loader
            spec = _TRUSTED_MODULE_SPEC(fullname, loader, origin=origin)
        else:
            _fail("sdk_artifact_unpinned_module_import")
        self._specs[fullname] = spec
        return spec

    def verify_extension_path(self, fullname: str, origin: str) -> None:
        if (
            fullname != "bt_api_ctp.ctp._ctp"
            or _absolute(origin) not in self.artifact.extension_paths
        ):
            _fail("sdk_artifact_native_module_unpinned")
        custody = self.artifact.custody
        if custody is None:
            _fail("sdk_artifact_windows_custody_required")
        relative = os.path.relpath(origin, self.artifact.distribution_root).replace(
            os.sep, "/"
        )
        expected = dict(self.artifact.file_sha256).get(relative)
        if expected is None:
            _fail("sdk_artifact_native_module_unpinned")
        try:
            raw = custody.read(relative, max_bytes=128 * 1024 * 1024)
        except WindowsArtifactCustodyError:
            _fail("sdk_artifact_native_module_unavailable")
        if not hmac.compare_digest(_sha256(raw), expected):
            _fail("sdk_artifact_native_module_hash_mismatch")

    def begin_loader_exec(
        self, module: ModuleType, fullname: str, loader: object
    ) -> None:
        if fullname not in self._source_modules and fullname != "bt_api_ctp.ctp._ctp":
            _fail("sdk_artifact_unpinned_module_import")
        if sys.modules.get(fullname) is not module:
            _fail("sdk_artifact_sys_modules_spoof")
        if fullname in self._loaded or fullname in self._pending:
            _fail("sdk_artifact_module_reentry")
        if self._loaders.get(fullname) is not loader:
            _fail("sdk_artifact_loaded_module_loader_mismatch")
        spec = self._specs.get(fullname)
        if (
            spec is None
            or getattr(module, "__spec__", None) is not spec
            or getattr(spec, "loader", None) is not loader
            or getattr(spec, "name", None) != fullname
        ):
            _fail("sdk_artifact_loaded_module_origin_mismatch")
        if fullname == "bt_api_ctp.ctp._ctp":
            origin = getattr(spec, "origin", None)
            if (
                type(origin) is not str
                or _absolute(origin) not in self.artifact.extension_paths
                or _absolute(getattr(module, "__file__", "")) != _absolute(origin)
            ):
                _fail("sdk_artifact_native_module_origin_mismatch")
        self._pending[fullname] = module
        try:
            self.assert_context()
        except BaseException:
            self._pending.pop(fullname, None)
            raise

    def finish_loader_exec(
        self, module: ModuleType, fullname: str, loader: object
    ) -> None:
        if (
            self._pending.get(fullname) is not module
            or self._loaders.get(fullname) is not loader
        ):
            _fail("sdk_artifact_module_execution_state_invalid")
        self._pending.pop(fullname, None)
        self._loaded[fullname] = module

    def import_module(self, fullname: str) -> ModuleType:
        self.assert_context()
        if fullname not in self._source_modules and fullname != "bt_api_ctp.ctp._ctp":
            _fail("sdk_artifact_unpinned_module_import")
        existing = sys.modules.get(fullname)
        if existing is not None:
            if self._loaded.get(fullname) is existing:
                return existing
            _fail("sdk_artifact_sys_modules_spoof")
        parent_name, separator, _child = fullname.rpartition(".")
        if separator:
            if parent_name not in self._source_modules:
                _fail("sdk_artifact_parent_package_unpinned")
            self.import_module(parent_name)
        spec = self._spec_for(fullname)
        module = _TRUSTED_MODULE_FROM_SPEC(spec)
        sys.modules[fullname] = module
        try:
            loader = spec.loader
            self._loaders[fullname] = loader
            loader.exec_module(module)
            if sys.modules.get(fullname) is not module:
                _fail("sdk_artifact_sys_modules_spoof")
            if module.__spec__ is not spec or module.__spec__.loader is not loader:
                _fail("sdk_artifact_loaded_module_origin_mismatch")
            return module
        except BaseException:
            sys.modules.pop(fullname, None)
            raise

    def guarded_import(
        self,
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: object = (),
        level: int = 0,
    ) -> object:
        self.assert_context()
        if level:
            package = (globals or {}).get("__package__")
            if type(package) is not str:
                _fail("sdk_artifact_relative_import_invalid")
            absolute_name = importlib.util.resolve_name("." * level + name, package)
        else:
            absolute_name = name
        if absolute_name == _DIST_NAME or absolute_name.startswith(_DIST_NAME + "."):
            module = self.import_module(absolute_name)
            if fromlist:
                for item in fromlist:
                    if type(item) is not str or item == "*" or hasattr(module, item):
                        continue
                    child = absolute_name + "." + item
                    if child in self._source_modules or child == "bt_api_ctp.ctp._ctp":
                        self.import_module(child)
                self.assert_context()
                return module
            self.assert_context()
            return self.import_module(_DIST_NAME)
        result = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
        self.assert_context()
        return result

    def verify_module(
        self, module: object, fullname: str, expected_origin: str
    ) -> None:
        if sys.modules.get(fullname) is not self._loaded.get(fullname):
            _fail("sdk_artifact_module_identity_changed")
        spec = getattr(module, "__spec__", None)
        loader = self._loaders.get(fullname)
        if (
            spec is None
            or getattr(spec, "name", None) != fullname
            or spec.loader is not loader
            or type(getattr(spec, "origin", None)) is not str
            or _absolute(spec.origin) != _absolute(expected_origin)
            or _absolute(getattr(module, "__file__", "")) != _absolute(expected_origin)
        ):
            _fail("sdk_artifact_loaded_module_origin_mismatch")
        relative = os.path.relpath(
            expected_origin, self.artifact.distribution_root
        ).replace(os.sep, "/")
        expected_hash = dict(self.artifact.file_sha256).get(relative)
        if expected_hash is None or self.artifact.custody is None:
            _fail("sdk_artifact_loaded_module_not_in_verified_inventory")
        if not hmac.compare_digest(
            _sha256(self.artifact.custody.read(relative)), expected_hash
        ):
            _fail("sdk_artifact_loaded_module_hash_mismatch")

    def close_after_failure(self) -> None:
        for fullname in tuple(self._loaded):
            sys.modules.pop(fullname, None)
        if self._installed and sys.meta_path is self._meta_tuple:
            sys.meta_path = self._original_meta_path
        if self._installed and sys.path is self._path_tuple:
            sys.path = self._original_path
        if self._installed and sys.path_hooks is self._hooks_tuple:
            sys.path_hooks = self._original_path_hooks
        self._installed = False


def _verify_loaded_module(
    module: object, fullname: str, expected_origin: str, expected_sha256: str
) -> None:
    spec = getattr(module, "__spec__", None)
    origin = getattr(spec, "origin", None)
    module_file = getattr(module, "__file__", None)
    if (
        getattr(spec, "name", None) != fullname
        or type(origin) is not str
        or type(module_file) is not str
        or _absolute(origin) != _absolute(expected_origin)
        or _absolute(module_file) != _absolute(expected_origin)
        or getattr(spec, "has_location", False) is not True
        or type(getattr(spec, "loader", None))
        is not importlib.machinery.SourceFileLoader
        or getattr(spec.loader, "name", None) != fullname
        or _absolute(getattr(spec.loader, "path", "")) != _absolute(expected_origin)
    ):
        _fail("sdk_artifact_loaded_module_origin_mismatch")
    try:
        with open(expected_origin, "rb") as stream:
            digest = _sha256(stream.read())
    except OSError:
        _fail("sdk_artifact_loaded_module_unavailable")
    if not hmac.compare_digest(digest, expected_sha256):
        _fail("sdk_artifact_loaded_module_hash_mismatch")


def _require_standard_import_chain() -> None:
    expected = (
        _TRUSTED_BUILTIN_IMPORTER,
        _TRUSTED_FROZEN_IMPORTER,
        _TRUSTED_PATH_FINDER,
    )
    _assert_trusted_importlib_runtime()
    if len(sys.meta_path) != len(expected) or any(
        actual is not trusted for actual, trusted in zip(sys.meta_path, expected)
    ):
        _fail("sdk_artifact_import_chain_modified")


def _verified_search_roots() -> list[str]:
    """Reject path entries/hooks that can hide another importable install."""

    if len(sys.path_hooks) != 2 or sys.path_hooks[0] is not zipimport.zipimporter:
        _fail("sdk_artifact_path_hooks_modified")
    standard_hook = importlib._bootstrap_external.FileFinder.path_hook(
        *importlib._bootstrap_external._get_supported_file_loaders()
    )
    actual_hook = sys.path_hooks[1]
    if getattr(actual_hook, "__code__", None) is not standard_hook.__code__ or tuple(
        cell.cell_contents for cell in (actual_hook.__closure__ or ())
    ) != tuple(cell.cell_contents for cell in (standard_hook.__closure__ or ())):
        _fail("sdk_artifact_path_hooks_modified")

    roots: list[str] = []
    for entry in sys.path:
        if type(entry) is not str or not entry or "\x00" in entry:
            _fail("sdk_artifact_path_entry_invalid")
        candidate = _absolute(entry)
        try:
            exists = os.path.exists(candidate)
            is_directory = os.path.isdir(candidate)
        except OSError:
            _fail("sdk_artifact_path_entry_unavailable")
        if exists and not is_directory:
            _fail("sdk_artifact_non_directory_import_path")
        cached = sys.path_importer_cache.get(entry)
        if cached is not None and type(cached) is not importlib.machinery.FileFinder:
            _fail("sdk_artifact_cached_importer_modified")
        if is_directory and candidate not in roots:
            roots.append(candidate)
    return roots


def _verify_loaded_native_extension(
    artifact: VerifiedCtpSdkArtifact,
    importer: _PinnedSdkImporter | None = None,
) -> None:
    _assert_trusted_importlib_runtime()
    fullname = "bt_api_ctp.ctp._ctp"
    module = sys.modules.get(fullname)
    if module is None:
        return
    spec = getattr(module, "__spec__", None)
    origin = getattr(spec, "origin", None)
    module_file = getattr(module, "__file__", None)
    if (
        type(origin) is not str
        or type(module_file) is not str
        or (
            importer is None
            and type(getattr(spec, "loader", None))
            is not _TRUSTED_EXTENSION_FILE_LOADER
        )
        or getattr(spec.loader, "name", None) != fullname
        or _absolute(getattr(spec.loader, "path", "")) != _absolute(origin)
        or _absolute(module_file) != _absolute(origin)
        or _absolute(origin) not in artifact.extension_paths
    ):
        _fail("sdk_artifact_native_module_origin_mismatch")
    relative = os.path.relpath(origin, artifact.distribution_root).replace(os.sep, "/")
    expected_hash = dict(artifact.file_sha256).get(relative)
    if expected_hash is None:
        _fail("sdk_artifact_native_module_unpinned")
    try:
        if artifact.custody is not None:
            actual_hash = _sha256(
                artifact.custody.read(relative, max_bytes=128 * 1024 * 1024)
            )
        elif importer is None:
            # Retain this private passive checker for synthetic inert-module
            # tests. Production verifier always supplies the custody importer.
            with open(origin, "rb") as stream:
                actual_hash = _sha256(stream.read())
        else:
            _fail("sdk_artifact_windows_custody_required")
    except (OSError, WindowsArtifactCustodyError):
        _fail("sdk_artifact_native_module_unavailable")
    if importer is not None and spec.loader is not importer._loaders.get(fullname):
        _fail("sdk_artifact_native_module_loader_mismatch")
    if not hmac.compare_digest(actual_hash, expected_hash):
        _fail("sdk_artifact_native_module_hash_mismatch")


class _CodeOwnedSettlementEvidenceVerifier:
    """Verifier composed only after the no-argument artifact gate succeeds."""

    def __init__(
        self,
        artifact: VerifiedCtpSdkArtifact,
        certificate_module: ModuleType,
        importer: _PinnedSdkImporter,
    ) -> None:
        self.source_manifest_sha256 = artifact.source_manifest_sha256
        self.evidence_type = certificate_module.CtpSettlementConfirmationEvidence
        self._builder_type = certificate_module.CtpSettlementConfirmationEvidenceBuilder
        self._certificate_module = certificate_module
        self._artifact = artifact
        self._importer = importer
        self._file_hashes = dict(artifact.file_sha256)
        self._policy = _CODE_OWNED_ARTIFACT_POLICY
        self._module_objects: dict[str, object] = {}

    def bind_modules(self) -> None:
        for fullname, _origin in self._artifact.module_origins:
            module = sys.modules.get(fullname)
            if module is None:
                _fail("sdk_artifact_required_module_missing")
            self._module_objects[fullname] = module

    def assert_current(self) -> None:
        if self._policy is None:
            _fail("sdk_artifact_release_pin_unavailable")
        self._importer.assert_context()
        if self._artifact.custody is None:
            _fail("sdk_artifact_windows_custody_required")
        try:
            self._artifact.custody.verify_current()
        except WindowsArtifactCustodyError:
            _fail("sdk_artifact_custody_changed")
        if (
            _verify_distribution_tree(
                distribution_root=self._artifact.distribution_root,
                package_root=self._artifact.package_root,
                dist_info_root=self._artifact.dist_info_root,
                policy=self._policy,
                custody=self._artifact.custody,
            )
            != self._artifact.file_sha256
        ):
            _fail("sdk_artifact_inventory_changed")
        for fullname, origin in self._artifact.module_origins:
            module = sys.modules.get(fullname)
            if module is None or module is not self._module_objects.get(fullname):
                _fail("sdk_artifact_module_identity_changed")
            relative = os.path.relpath(
                origin, self._artifact.distribution_root
            ).replace(os.sep, "/")
            expected_hash = self._file_hashes.get(relative)
            if expected_hash is None:
                _fail("sdk_artifact_loaded_module_not_in_verified_inventory")
            self._importer.verify_module(module, fullname, origin)
        _verify_loaded_native_extension(self._artifact, self._importer)

    def verify_current(self, trader_client: object, result: object) -> object:
        self.assert_current()
        if (
            self._certificate_module.CtpSettlementConfirmationEvidence
            is not self.evidence_type
        ):
            _fail("sdk_artifact_evidence_type_identity_changed")
        builder = self._builder_type(trader_client)
        return builder.build(result)


def _load_code_owned_settlement_verifier() -> _CodeOwnedSettlementEvidenceVerifier:
    """Verify the pinned distribution before importing the SDK evidence module."""

    global _CODE_OWNED_VERIFIER_CACHE, _CODE_OWNED_IMPORTER
    if _CODE_OWNED_VERIFIER_CACHE is not None:
        _CODE_OWNED_VERIFIER_CACHE.assert_current()
        return _CODE_OWNED_VERIFIER_CACHE
    policy = _CODE_OWNED_ARTIFACT_POLICY
    if policy is None:
        _fail("sdk_artifact_release_pin_unavailable")
    artifact = _discover_and_verify(policy)
    importer = _PinnedSdkImporter(artifact)
    try:
        importer.install()
        certificate_module = importer.import_module(_EVIDENCE_MODULE)
        for fullname, expected_origin in artifact.module_origins:
            module = importer.import_module(fullname)
            importer.verify_module(module, fullname, expected_origin)
        _verify_loaded_native_extension(artifact, importer)
        if (
            getattr(certificate_module, "CtpSettlementConfirmationEvidence", None)
            is None
            or getattr(
                certificate_module, "CtpSettlementConfirmationEvidenceBuilder", None
            )
            is None
            or sys.modules.get(_EVIDENCE_MODULE) is not certificate_module
        ):
            _fail("sdk_artifact_evidence_type_unavailable")
        verifier = _CodeOwnedSettlementEvidenceVerifier(
            artifact, certificate_module, importer
        )
        verifier.bind_modules()
        verifier.assert_current()
    except BaseException:
        importer.close_after_failure()
        if artifact.custody is not None:
            artifact.custody.close()
        raise
    _CODE_OWNED_VERIFIER_CACHE = verifier
    _CODE_OWNED_IMPORTER = importer
    return verifier


def _get_preclient_code_owned_verifier() -> _CodeOwnedSettlementEvidenceVerifier:
    verifier = _CODE_OWNED_VERIFIER_CACHE
    if verifier is None:
        _fail("sdk_artifact_preclient_gate_required")
    verifier.assert_current()
    return verifier


def _require_exact_evidence_type(evidence: object, expected_type: object) -> None:
    if expected_type is None or type(evidence) is not expected_type:
        _fail("sdk_artifact_evidence_type_identity_mismatch")


def _validate_synthetic_distribution_for_tests(
    *,
    distribution_root: str,
    package_root: str,
    dist_info_root: str,
    policy: CtpSdkArtifactPolicy,
) -> tuple[tuple[str, str], ...]:
    """Private filesystem-only seam used by fake install tests; never a route."""

    return _verify_distribution_tree(
        distribution_root=distribution_root,
        package_root=package_root,
        dist_info_root=dist_info_root,
        policy=policy,
    )


def _discover_synthetic_distribution_for_tests(
    policy: CtpSdkArtifactPolicy,
) -> VerifiedCtpSdkArtifact:
    """Private test seam to assert duplicate-install rejection without imports."""

    return _discover_and_verify(policy)
