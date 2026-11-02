"""Origin-pinned imports for reviewed external capability packages.

The Iteration 41 runner owns its entrypoint selection, so a configuration file
must not also get to choose where optional SDK code comes from.  This module
keeps that rule at the Python import boundary: a reviewed registration lists
the exact top-level ``bt_api_*`` modules it may use, and each import is
resolved only from the process's non-CWD deployment search roots captured
before the runner starts.

This is deliberately a source-origin fence, not a wheel-signature verifier.
Production deployment still needs an isolated environment plus independently
verified wheel/lock hashes.  The fence prevents a same-name package placed in
the current working directory from winning normal Python import precedence and
rejects a cached package whose origin differs from the captured deployment
root.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import os
import stat
import sys
import sysconfig
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Generator, Iterable, Optional, Sequence, Tuple

from .errors import PRESET_POLICY_VIOLATION, RuntimeConfigError


# Keep the standard finder selected before reviewed runner code can execute.
# A runner may not replace ``PathFinder.find_spec`` later and turn a child
# namespace import into an ambient/custom finder result.
_PATH_FINDER_FIND_SPEC = importlib.machinery.PathFinder.find_spec


def _capability_error(reason: str, message: str) -> RuntimeConfigError:
    return RuntimeConfigError(
        PRESET_POLICY_VIOLATION,
        message,
        field_path="runtime.capabilities",
        reason=reason,
    )


def _is_link_or_reparse(stat_result: os.stat_result) -> bool:
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(stat_result, "st_file_attributes", 0)
    return stat.S_ISLNK(stat_result.st_mode) or bool(attributes & reparse_point)


@dataclass(frozen=True)
class _PathIdentity:
    """A leaf identity retained while a reviewed runner is active."""

    device: int
    inode: int
    mode: int

    @classmethod
    def directory(cls, path: Path) -> "_PathIdentity":
        try:
            result = os.lstat(str(path))
        except OSError:
            raise _capability_error(
                "capability_origin_mismatch",
                "a reviewed capability package directory cannot be inspected",
            ) from None
        if _is_link_or_reparse(result) or not stat.S_ISDIR(result.st_mode):
            raise _capability_error(
                "capability_origin_mismatch",
                "a reviewed capability package directory is not concrete",
            )
        return cls(result.st_dev, result.st_ino, result.st_mode)

    @classmethod
    def regular_file(cls, path: Path) -> "_PathIdentity":
        try:
            result = os.lstat(str(path))
        except OSError:
            raise _capability_error(
                "capability_origin_mismatch",
                "a reviewed capability package initializer cannot be inspected",
            ) from None
        if _is_link_or_reparse(result) or not stat.S_ISREG(result.st_mode):
            raise _capability_error(
                "capability_origin_mismatch",
                "a reviewed capability package initializer is not a regular file",
            )
        return cls(result.st_dev, result.st_ino, result.st_mode)

    def matches_directory(self, path: Path) -> bool:
        try:
            result = os.lstat(str(path))
        except OSError:
            return False
        return (
            not _is_link_or_reparse(result)
            and stat.S_ISDIR(result.st_mode)
            and (result.st_dev, result.st_ino, result.st_mode)
            == (self.device, self.inode, self.mode)
        )

    def matches_regular_file(self, path: Path) -> bool:
        try:
            result = os.lstat(str(path))
        except OSError:
            return False
        return (
            not _is_link_or_reparse(result)
            and stat.S_ISREG(result.st_mode)
            and (result.st_dev, result.st_ino, result.st_mode)
            == (self.device, self.inode, self.mode)
        )


def _absolute_path(path: object) -> Path:
    try:
        return Path(os.path.normcase(os.path.normpath(os.path.abspath(str(path)))))
    except (OSError, RuntimeError, TypeError, ValueError):
        raise _capability_error(
            "capability_origin_mismatch", "a capability import path is not usable"
        ) from None


def _physical_path(path: object) -> Path:
    """Normalise intermediate links before comparing import locations."""

    try:
        return Path(
            os.path.normcase(os.path.normpath(os.path.realpath(os.path.abspath(str(path)))))
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        raise _capability_error(
            "capability_origin_mismatch", "a capability import path is not usable"
        ) from None


def _path_is_within(path: object, root: Path) -> bool:
    try:
        candidate = str(_physical_path(path))
        trusted_root = str(_physical_path(root))
        return os.path.commonpath((candidate, trusted_root)) == trusted_root
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _concrete_directory(path: Path) -> Optional[Path]:
    """Return one usable import root without following links or CWD aliases."""

    try:
        result = os.lstat(str(path))
    except OSError:
        return None
    if _is_link_or_reparse(result) or not stat.S_ISDIR(result.st_mode):
        return None
    return path


def _interpreter_install_roots() -> frozenset[Path]:
    """Return the exact stdlib-reported package roots for this interpreter.

    A clean virtual environment is often deliberately created under the
    consumer's temporary working directory.  Its ``site-packages`` directory
    must remain an admissible deployment root; treating every descendant of
    CWD as a shadow would otherwise reject the isolated wheel consumer before
    a reviewed capability package can be loaded.  This exception is deliberately
    narrow: only the interpreter's own exact ``purelib``/``platlib`` roots are
    accepted, never arbitrary CWD children supplied through ``PYTHONPATH``.
    """

    try:
        paths = sysconfig.get_paths()
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return frozenset()
    roots = []
    for key in ("purelib", "platlib"):
        raw_path = paths.get(key)
        if isinstance(raw_path, (str, os.PathLike)) and str(raw_path):
            roots.append(_absolute_path(raw_path))
    return frozenset(roots)


def _concrete_interpreter_install_roots() -> Tuple[Path, ...]:
    """Return only concrete exact ``purelib``/``platlib`` roots for this interpreter.

    This deliberately does not inspect ``sys.path``.  The ordinary capability
    fence preserves its reviewed deployment-root behavior, including absolute
    non-CWD paths.  The stricter future private-account boundary instead needs
    the current interpreter's two installation roots and nothing else.
    """

    roots = []
    seen = set()
    for root in _interpreter_install_roots():
        concrete = _concrete_directory(root)
        if concrete is None:
            continue
        key = os.path.normcase(str(concrete))
        if key in seen:
            continue
        seen.add(key)
        roots.append(concrete)
    return tuple(sorted(roots, key=lambda root: os.path.normcase(str(root))))


def _captured_non_cwd_search_roots(source_root: Path) -> Tuple[Path, ...]:
    """Snapshot import roots that cannot be supplied by the current directory.

    Normal Python import resolution puts ``cwd`` before ``PYTHONPATH`` and
    installed packages.  A reviewed runtime captures the latter once, before
    source execution, and never consults a path added by the runner later.
    Absolute roots explicitly configured by a deployment remain possible;
    their release provenance is a separate wheel/environment acceptance gate.
    """

    cwd = _absolute_path(os.getcwd())
    interpreter_install_roots = _interpreter_install_roots()
    candidates: list[Path] = []
    seen = set()

    # The fixed Backtrader source root is itself a reviewed source location.
    # It normally contains no SDK packages, but including it permits an
    # explicitly packaged deployment tree without consulting CWD.
    raw_paths: Iterable[object] = (source_root,) + tuple(sys.path)
    for raw_path in raw_paths:
        if not isinstance(raw_path, (str, os.PathLike)) or not str(raw_path):
            # Empty sys.path entries mean CWD and are intentionally excluded.
            continue
        candidate = _absolute_path(raw_path)
        if _path_is_within(candidate, cwd) and candidate not in interpreter_install_roots:
            continue
        concrete = _concrete_directory(candidate)
        if concrete is None:
            continue
        key = os.path.normcase(str(concrete))
        if key in seen:
            continue
        seen.add(key)
        candidates.append(concrete)
    return tuple(candidates)


@dataclass(frozen=True)
class _CapabilityOrigin:
    """One top-level package resolved from a captured deployment root."""

    module_name: str
    search_root: Path
    package_directory: Path
    initializer: Path
    package_identity: _PathIdentity
    initializer_identity: _PathIdentity

    def assert_current(self) -> None:
        if not self.package_identity.matches_directory(self.package_directory):
            raise _capability_error(
                "capability_origin_mismatch",
                "a reviewed capability package directory changed during runner startup",
            )
        if not self.initializer_identity.matches_regular_file(self.initializer):
            raise _capability_error(
                "capability_origin_mismatch",
                "a reviewed capability package initializer changed during runner startup",
            )


class _CapabilityOriginResolver:
    """Resolve only code-owned capability module names from captured roots."""

    def __init__(self, modules: Sequence[str], source_root: Path) -> None:
        self.modules = frozenset(modules)
        self._initial_cwd = _absolute_path(os.getcwd())
        self.search_roots = _captured_non_cwd_search_roots(source_root)
        # PEP 660 editable installations can expose a package solely through
        # a meta-path finder.  Keep the pre-run finder objects so a runner
        # cannot add a new finder after this context starts, and never call
        # PathFinder here: it would consult the live CWD/sys.path again.
        self._deployment_meta_finders = tuple(
            finder for finder in sys.meta_path if finder is not importlib.machinery.PathFinder
        )
        self._origins: Dict[str, _CapabilityOrigin] = {}

    def origin_for(self, module_name: str) -> _CapabilityOrigin:
        origin = self._origins.get(module_name)
        if origin is not None:
            origin.assert_current()
            return origin

        for search_root in self.search_roots:
            try:
                specification = _PATH_FINDER_FIND_SPEC(module_name, (str(search_root),))
            except (ImportError, OSError, ValueError):
                continue
            if specification is None:
                continue
            origin = self._origin_from_specification(module_name, search_root, specification)
            self._origins[module_name] = origin
            return origin

        origin = self._origin_from_deployment_meta_finder(module_name)
        if origin is not None:
            self._origins[module_name] = origin
            return origin
        raise _capability_error(
            "capability_origin_unavailable",
            "a reviewed capability package is unavailable from the captured deployment roots",
        )

    def _origin_from_deployment_meta_finder(self, module_name: str) -> Optional[_CapabilityOrigin]:
        """Resolve a concrete editable-package root without using CWD.

        ``PathFinder`` above already searched the captured deployment roots.
        The remaining pre-existing finders cover editable package mappings.
        A result is accepted only after it is reduced to a regular package
        directory outside CWD and then re-resolved with ``PathFinder`` from
        that directory's parent.  Thus a finder cannot hand a runner an
        opaque loader or a CWD package.
        """

        current_cwd = _absolute_path(os.getcwd())
        for finder in self._deployment_meta_finders:
            find_spec = getattr(finder, "find_spec", None)
            if not callable(find_spec):
                continue
            try:
                specification = find_spec(module_name, None, None)
            except (ImportError, OSError, TypeError, ValueError):
                continue
            if specification is None:
                continue
            locations = getattr(specification, "submodule_search_locations", None)
            if locations is None:
                continue
            package_locations = tuple(locations)
            if len(package_locations) != 1:
                raise _capability_error(
                    "capability_origin_mismatch",
                    "a reviewed capability package must not be a namespace package",
                )
            package_directory = _absolute_path(package_locations[0])
            search_root = package_directory.parent
            if (
                _path_is_within(package_directory, self._initial_cwd)
                or _path_is_within(package_directory, current_cwd)
                or _concrete_directory(search_root) is None
            ):
                raise _capability_error(
                    "capability_origin_mismatch",
                    "a reviewed capability package must not resolve from the current directory",
                )
            try:
                concrete_specification = _PATH_FINDER_FIND_SPEC(module_name, (str(search_root),))
            except (ImportError, OSError, ValueError):
                concrete_specification = None
            if concrete_specification is None:
                raise _capability_error(
                    "capability_origin_unavailable",
                    "a reviewed editable capability package has no concrete deployment root",
                )
            return self._origin_from_specification(module_name, search_root, concrete_specification)
        return None

    @staticmethod
    def _origin_from_specification(
        module_name: str,
        search_root: Path,
        specification: object,
    ) -> _CapabilityOrigin:
        locations = getattr(specification, "submodule_search_locations", None)
        origin = getattr(specification, "origin", None)
        if not isinstance(origin, str) or not origin or locations is None:
            raise _capability_error(
                "capability_origin_mismatch",
                "a reviewed capability package must have one concrete package origin",
            )
        package_locations = tuple(locations)
        if len(package_locations) != 1:
            raise _capability_error(
                "capability_origin_mismatch",
                "a reviewed capability package must not be a namespace package",
            )
        package_directory = _absolute_path(package_locations[0])
        initializer = _absolute_path(origin)
        if (
            not _path_is_within(package_directory, search_root)
            or not _path_is_within(initializer, package_directory)
            or initializer.name != "__init__.py"
        ):
            raise _capability_error(
                "capability_origin_mismatch",
                "a reviewed capability package does not resolve inside its captured root",
            )
        return _CapabilityOrigin(
            module_name=module_name,
            search_root=search_root,
            package_directory=package_directory,
            initializer=initializer,
            package_identity=_PathIdentity.directory(package_directory),
            initializer_identity=_PathIdentity.regular_file(initializer),
        )

    def assert_module_origin(self, module_name: str, module: object) -> None:
        origin = self.origin_for(module_name)
        module_file = getattr(module, "__file__", None)
        module_path = getattr(module, "__path__", None)
        locations = []
        if isinstance(module_file, str) and module_file:
            locations.append(module_file)
        if module_path is not None:
            try:
                locations.extend(module_path)
            except TypeError:
                locations = []
        if not locations or any(
            not _path_is_within(location, origin.package_directory) for location in locations
        ):
            raise _capability_error(
                "capability_origin_mismatch",
                "a cached capability package is outside the captured deployment root",
            )

    def assert_cached_origins(self) -> None:
        for name, module in tuple(sys.modules.items()):
            if not isinstance(name, str):
                continue
            top_level = name.split(".", 1)[0]
            if not top_level.startswith("bt_api_"):
                continue
            # ``import`` returns an already cached module before consulting
            # meta-path finders.  Therefore a preloaded, unregistered SDK
            # package would otherwise bypass ``_CapabilityImportFinder`` and
            # let a reviewed runner expand its capability surface through an
            # ambient/CWD import.  Reject it before runner source is loaded.
            if top_level not in self.modules:
                raise _capability_error(
                    "capability_module_not_registered",
                    "a reviewed runtime started with an unregistered external capability package",
                )
            if module is None:
                raise _capability_error(
                    "capability_origin_mismatch",
                    "a reviewed capability package is partially initialized before runner startup",
                )
            self.assert_module_origin(top_level, module)

    def assert_top_level_loaded(self, module_name: str) -> None:
        module = sys.modules.get(module_name)
        if module is None:
            raise _capability_error(
                "capability_origin_mismatch",
                "a reviewed capability package is not available after import selection",
            )
        self.assert_module_origin(module_name, module)

    def trusted_submodule_spec(self, fullname: str, top_level: str) -> object:
        """Resolve one capability child through its already-pinned package path.

        A top-level package's ``__path__`` is not enough by itself: a custom
        meta finder may ignore that path and hand importlib an ambient child
        module.  Resolve the child with ``PathFinder`` here, before any later
        finder can run, and reject namespace/link/non-concrete results before
        their loaders execute.
        """

        origin = self.origin_for(top_level)
        origin.assert_current()
        parent_name, separator, _ = fullname.rpartition(".")
        if not separator:
            raise _capability_error(
                "capability_origin_mismatch",
                "a reviewed capability submodule name is invalid",
            )
        parent = sys.modules.get(parent_name)
        if parent is None:
            raise _capability_error(
                "capability_origin_mismatch",
                "a reviewed capability submodule has no trusted parent package",
            )
        parent_paths = getattr(parent, "__path__", None)
        try:
            search_paths = tuple(parent_paths)
        except TypeError:
            search_paths = ()
        if not search_paths or any(
            not _path_is_within(path, origin.package_directory)
            or _concrete_directory(_absolute_path(path)) is None
            for path in search_paths
        ):
            raise _capability_error(
                "capability_origin_mismatch",
                "a reviewed capability submodule parent is outside its captured package root",
            )
        try:
            specification = _PATH_FINDER_FIND_SPEC(fullname, search_paths)
        except (ImportError, OSError, ValueError):
            specification = None
        if specification is None:
            raise _capability_error(
                "capability_origin_unavailable",
                "a reviewed capability submodule is unavailable from its captured package root",
            )
        self._assert_submodule_specification(fullname, origin, specification)
        return specification

    @staticmethod
    def _assert_submodule_specification(
        fullname: str, top_level_origin: _CapabilityOrigin, specification: object
    ) -> None:
        """Reject a child spec which can execute outside the pinned package.

        ``trusted_submodule_spec`` obtains this value directly from
        :class:`~importlib.machinery.PathFinder`; accepting a namespace child
        therefore does not hand control back to ambient meta-path finders. A
        namespace child has no executable origin, but is safe to admit when
        it has exactly one concrete directory beneath the already-pinned
        top-level package. This narrow case is needed by SDK packages which
        intentionally omit ``__init__.py`` from data-only grouping folders.
        """

        if not isinstance(specification, importlib.machinery.ModuleSpec):
            raise _capability_error(
                "capability_origin_mismatch",
                "a reviewed capability submodule has an invalid import specification",
            )
        if getattr(specification, "name", None) != fullname:
            raise _capability_error(
                "capability_origin_mismatch",
                "a reviewed capability submodule has an unexpected import name",
            )
        origin = getattr(specification, "origin", None)
        locations = getattr(specification, "submodule_search_locations", None)
        if origin is None:
            # Only a standard no-code namespace package can have no origin.
            # A loader, a missing package path, or a forged spec must not be
            # treated as a benign namespace merely because it has no file.
            if getattr(specification, "loader", None) is not None or locations is None:
                raise _capability_error(
                    "capability_origin_mismatch",
                    "a reviewed capability namespace submodule is not a no-code package",
                )
            if isinstance(locations, (str, bytes)):
                raise _capability_error(
                    "capability_origin_mismatch",
                    "a reviewed capability namespace submodule has an invalid package path",
                )
            try:
                package_locations = tuple(locations)
            except TypeError:
                raise _capability_error(
                    "capability_origin_mismatch",
                    "a reviewed capability namespace submodule has an invalid package path",
                ) from None
            if len(package_locations) != 1:
                raise _capability_error(
                    "capability_origin_mismatch",
                    "a reviewed capability namespace submodule must have one concrete path",
                )
            package_directory = _absolute_path(package_locations[0])
            if not _path_is_within(package_directory, top_level_origin.package_directory):
                raise _capability_error(
                    "capability_origin_mismatch",
                    "a reviewed capability namespace submodule resolves outside its captured package root",
                )
            # lstat keeps a directory link/reparse point from being accepted
            # even where its resolved destination would fall below the same
            # reviewed package root.
            _PathIdentity.directory(package_directory)
            return
        if not isinstance(origin, str) or not origin:
            raise _capability_error(
                "capability_origin_mismatch",
                "a reviewed capability submodule lacks a concrete file origin",
            )
        initializer = _absolute_path(origin)
        if not _path_is_within(initializer, top_level_origin.package_directory):
            raise _capability_error(
                "capability_origin_mismatch",
                "a reviewed capability submodule resolves outside its captured package root",
            )
        _PathIdentity.regular_file(initializer)
        if locations is None:
            return
        package_locations = tuple(locations)
        if len(package_locations) != 1:
            raise _capability_error(
                "capability_origin_mismatch",
                "a reviewed capability submodule must not be a namespace package",
            )
        package_directory = _absolute_path(package_locations[0])
        if (
            not _path_is_within(package_directory, top_level_origin.package_directory)
            or _concrete_directory(package_directory) is None
            or initializer.name != "__init__.py"
            or not _path_is_within(initializer, package_directory)
        ):
            raise _capability_error(
                "capability_origin_mismatch",
                "a reviewed capability submodule package is not concrete",
            )


class _InstalledCapabilityOriginResolver(_CapabilityOriginResolver):
    """Resolve registered capabilities only from this interpreter's install roots.

    It intentionally has no source-root, ``sys.path``, or editable meta-finder
    fallback.  This is an origin fence only: it does not claim wheel hashes,
    signatures, release provenance, or isolation from trusted in-process code.
    """

    def __init__(self, modules: Sequence[str]) -> None:
        self.modules = frozenset(modules)
        self._initial_cwd = _absolute_path(os.getcwd())
        self.search_roots = _concrete_interpreter_install_roots()
        self._origins: Dict[str, _CapabilityOrigin] = {}

    def _origin_from_deployment_meta_finder(self, module_name: str) -> Optional[_CapabilityOrigin]:
        """Never permit editable/meta-path resolution in the strict boundary."""

        del module_name
        return None


class _CapabilityImportFinder:
    """A one-run meta finder that bypasses CWD for reviewed SDK packages."""

    def __init__(self, resolver: _CapabilityOriginResolver) -> None:
        self._resolver = resolver

    def find_spec(
        self,
        fullname: str,
        path: Optional[Sequence[str]] = None,
        target: object = None,
    ) -> object:
        del path, target
        top_level = fullname.split(".", 1)[0]
        if not top_level.startswith("bt_api_"):
            return None
        if top_level not in self._resolver.modules:
            raise _capability_error(
                "capability_module_not_registered",
                "the reviewed runtime did not register this external capability package",
            )
        if fullname == top_level:
            origin = self._resolver.origin_for(top_level)
            origin.assert_current()
            try:
                specification = _PATH_FINDER_FIND_SPEC(top_level, (str(origin.search_root),))
            except (ImportError, OSError, ValueError):
                specification = None
            if specification is None:
                raise _capability_error(
                    "capability_origin_unavailable",
                    "a reviewed capability package disappeared during runner startup",
                )
            # ``origin_for`` has already rejected namespace, link, and
            # cross-root results.  Revalidate before handing the loader back
            # to importlib so a changed package is rejected before execution.
            self._resolver._origin_from_specification(top_level, origin.search_root, specification)
            return specification
        self._resolver.assert_top_level_loaded(top_level)
        return self._resolver.trusted_submodule_spec(fullname, top_level)


def _installed_capability_module_names(capability_modules: Sequence[str]) -> Tuple[str, ...]:
    """Reject non-top-level or duplicate names before strict origin resolution."""

    if isinstance(capability_modules, (str, bytes)):
        raise _capability_error(
            "capability_module_not_registered",
            "installed capability imports require an exact sequence of top-level packages",
        )
    try:
        modules = tuple(capability_modules)
    except TypeError:
        raise _capability_error(
            "capability_module_not_registered",
            "installed capability imports require an exact sequence of top-level packages",
        ) from None
    if any(
        type(module_name) is not str or not module_name.startswith("bt_api_") or "." in module_name
        for module_name in modules
    ):
        raise _capability_error(
            "capability_module_not_registered",
            "installed capability imports require registered top-level bt_api packages",
        )
    if len(set(modules)) != len(modules):
        raise _capability_error(
            "capability_module_not_registered",
            "installed capability imports must not contain duplicate package names",
        )
    return modules


@contextmanager
def trusted_capability_import_context(
    source_root: Optional[Path], capability_modules: Sequence[str]
) -> Generator[None, None, None]:
    """Pin reviewed SDK imports for one shipped runner execution.

    Test-only registries with no inventory source root retain the existing
    runner-file loader behavior.  A shipped runner with an empty allow-list
    instead means that *no* external ``bt_api_*`` package is approved: its
    cached and newly requested capability imports still fail closed.
    """

    modules = tuple(capability_modules)
    if source_root is None:
        yield
        return
    resolver = _CapabilityOriginResolver(modules, source_root)
    resolver.assert_cached_origins()
    finder = _CapabilityImportFinder(resolver)
    sys.meta_path.insert(0, finder)
    try:
        yield
    except Exception:
        raise
    else:
        # Catch a package whose cached paths were altered by code that ran
        # under the reviewed runner before its report becomes public.
        resolver.assert_cached_origins()
    finally:
        try:
            sys.meta_path.remove(finder)
        except ValueError:
            pass


def first_unavailable_trusted_capability_module(
    source_root: Path,
    capability_modules: Sequence[str],
    required_modules: Sequence[str],
) -> Optional[str]:
    """Return the first absent, declared package without importing its code.

    This is a narrow preflight for reviewed routes that must fail before their
    runner starts.  It uses the same non-CWD origin resolver as the later
    import fence, so an ambient package cannot satisfy the check.  Resolving a
    package specification does not execute its initializer or import provider
    code.
    """

    modules = _installed_capability_module_names(capability_modules)
    required = _installed_capability_module_names(required_modules)
    if any(module_name not in modules for module_name in required):
        raise _capability_error(
            "capability_module_not_registered",
            "a required capability package is absent from the reviewed import allow-list",
        )

    resolver = _CapabilityOriginResolver(modules, source_root)
    resolver.assert_cached_origins()
    for module_name in required:
        try:
            resolver.origin_for(module_name)
        except RuntimeConfigError as error:
            if error.reason == "capability_origin_unavailable":
                return module_name
            raise
    return None


@contextmanager
def trusted_installed_capability_import_context(
    capability_modules: Sequence[str],
) -> Generator[None, None, None]:
    """Pin registered SDK imports to this interpreter's exact install roots.

    Unlike :func:`trusted_capability_import_context`, this strict context does
    not admit a source root, absolute ``PYTHONPATH`` entry, or editable
    meta-path mapping.  Each registered package is resolved before code under
    the context can run, and cached top-level/submodule locations must remain
    below that exact pinned installed package directory.

    This rejects origin substitution; it does not verify a wheel signature,
    release provenance, dependency lock, or arbitrary trusted in-process
    Python code.
    """

    modules = _installed_capability_module_names(capability_modules)
    resolver = _InstalledCapabilityOriginResolver(modules)
    # Resolve each name eagerly.  If an absolute PYTHONPATH/cache package is
    # the only available copy, fail before a future credential-backed factory
    # can run.  The resolver intentionally has no editable/meta-finder path.
    for module_name in modules:
        resolver.origin_for(module_name)
    resolver.assert_cached_origins()
    finder = _CapabilityImportFinder(resolver)
    sys.meta_path.insert(0, finder)
    try:
        yield
    except Exception:
        raise
    else:
        resolver.assert_cached_origins()
    finally:
        try:
            sys.meta_path.remove(finder)
        except ValueError:
            pass


__all__ = [
    "first_unavailable_trusted_capability_module",
    "trusted_capability_import_context",
    "trusted_installed_capability_import_context",
]
