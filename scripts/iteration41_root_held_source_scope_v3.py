"""Root-held physical source scope V3 (unregistered, closed by default).

The scope bootstraps only the two fixed public Windows helper modules from
bounded, hash-pinned source bytes. A production scope then requires the
helpers' concrete Win32 API type and holds caller-declared source files and
their ancestor directories through the same handles. Declarations are
physical custody inputs; this helper does not make their digests, counts, or
contents provider or account authority.

This is not a runtime registry entry, isolation boundary, ACL/owner proof, or
provider capability. Caller-declared public/software source rows may name an
exact D:\\temp physical path; the caller must close that path and digest in its
own source manifest. Private, credential, capture, SDK, native, WinAPI,
process, and provider paths are rejected before any handle open.
"""

from __future__ import annotations

import contextlib
from contextlib import ExitStack
import builtins
import dis
import hashlib
import ctypes
import ntpath
import os
from pathlib import Path
import re
import sys
import threading
import types


ROOT = Path(__file__).resolve().parents[1]
_PATH_IMPL_TYPE = type(ROOT)
ROOT_HELD_SCOPE_V3_SCHEMA = "iteration41.root-held-source-scope.v3"
ROOT_HELD_SCOPE_V3_ENABLED = False

PRIVATE_SOURCE_REL = Path("backtrader_runtime/certification_roundtrip_private.py")
PRIVATE_SOURCE_SHA256 = "b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd"
CLI_SOURCE_REL = Path("backtrader_runtime/certification_binance_roundtrip_r3_cli.py")
CLI_SOURCE_SHA256 = "62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76"

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MAX_PRIVATE_SOURCE_BYTES = 64 * 1024
_MAX_CLI_SOURCE_BYTES = 128 * 1024
_MAX_ROWS = 8192
_MAX_TOTAL_BYTES = 1024 * 1024 * 1024
_MAX_DEFAULT_ROW_BYTES = 64 * 1024 * 1024
_MAX_WHEEL_BYTES = 32 * 1024 * 1024
_MAX_PYC_BYTES = 16 * 1024 * 1024
_MAX_NATIVE_BYTES = 128 * 1024 * 1024
_OPAQUE_SUFFIXES = frozenset({".dll", ".exe", ".pyd", ".whl", ".pyc"})
_CREDENTIAL_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".p7b", ".kdbx"})
_CREDENTIAL_NAMES = frozenset(
    {
        ".env",
        "config.yaml",
        "secrets.yaml",
        "credentials.json",
        "credentials.yaml",
        "credential.json",
        "credential.yaml",
        "config.yml",
        "private-config.yaml",
        "private-config.yml",
        "auth.json",
        "authorization.json",
        "account.json",
        "account-scope.json",
        "approval.json",
        "approval-capsule.json",
        "capsule.json",
        "receipt.json",
        "token.json",
    }
)
_SENSITIVE_DIRECTORY_NAMES = frozenset(
    {
        ".aws",
        ".azure",
        ".ssh",
        ".git",
        "capture",
        "captures",
        "private",
        "private_captures",
        "credentials",
        "secrets",
        "authority",
        "authorities",
        "approvals",
        "capsules",
        "receipts",
    }
)
_AUTHORITY_TOKENS = frozenset(
    {
        "authority", "authorization", "approval", "capsule", "receipt", "credential",
        "secret", "account", "token",
    }
)
_AUTHORITY_DATA_SUFFIXES = frozenset({".json", ".jsonl", ".yaml", ".yml", ".ini", ".conf"})
_MISSING = object()
_RETAINED_SCOPES: list[object] = []


class RootHeldSourceError(RuntimeError):
    """Fixed safe errors; no path, OS text, or artifact bytes are included."""


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise RootHeldSourceError(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _bounded_public_source(path: Path, maximum: int, expected_sha256: str) -> bytes:
    """Read only one fixed, public helper source with a strict byte ceiling."""
    expected_path = (ROOT / path).resolve(strict=True)
    _need(expected_path == ROOT / path, "helper_source_path_changed")
    try:
        with expected_path.open("rb") as stream:
            raw = stream.read(maximum + 1)
    except BaseException:
        raise RootHeldSourceError("helper_source_unavailable") from None
    _need(type(raw) is bytes and len(raw) <= maximum, "helper_source_size_invalid")
    _need(_sha(raw) == expected_sha256, "helper_source_pin_mismatch")
    return raw


def _function_code_fingerprint(code: types.CodeType) -> bytes:
    def constant(value: object) -> object:
        if type(value) is types.CodeType:
            return ("code", shape(value))
        if type(value) is tuple:
            return ("tuple", tuple(constant(item) for item in value))
        if type(value) is frozenset:
            return ("frozenset", tuple(sorted((constant(item) for item in value), key=repr)))
        if type(value) in (str, bytes, int, bool, float, type(None)):
            return (type(value).__name__, value.hex() if type(value) is bytes else repr(value))
        if value is Ellipsis:
            return ("ellipsis",)
        raise RootHeldSourceError("helper_code_constant_unsupported")

    def shape(value: types.CodeType) -> tuple[object, ...]:
        return (
            value.co_argcount,
            value.co_posonlyargcount,
            value.co_kwonlyargcount,
            value.co_nlocals,
            value.co_stacksize,
            value.co_flags,
            value.co_code.hex(),
            tuple(constant(item) for item in value.co_consts),
            value.co_names,
            value.co_varnames,
            value.co_filename,
            value.co_name,
            value.co_qualname,
            value.co_firstlineno,
            value.co_linetable.hex(),
            value.co_exceptiontable.hex(),
            value.co_freevars,
            value.co_cellvars,
        )

    try:
        return hashlib.sha256(repr(shape(code)).encode("utf-8", "strict")).digest()
    except RootHeldSourceError:
        raise
    except BaseException:
        raise RootHeldSourceError("helper_code_fingerprint_failed") from None


def _same_literal(actual: object, expected: object) -> bool:
    if type(actual) is not type(expected):
        return False
    if type(expected) in (str, bytes, int, bool, float, type(None)):
        return actual == expected
    if type(expected) is tuple:
        return len(actual) == len(expected) and all(
            _same_literal(left, right) for left, right in zip(actual, expected)
        )
    if type(expected) is dict:
        return (
            type(actual) is dict
            and set(actual) == set(expected)
            and all(_same_literal(actual[key], expected[key]) for key in expected)
        )
    if isinstance(expected, re.Pattern):
        return (
            isinstance(actual, re.Pattern)
            and actual.pattern == expected.pattern
            and actual.flags == expected.flags
        )
    return actual is expected


def _assert_function(
    actual: object,
    expected_function: types.FunctionType,
    owner: types.ModuleType,
) -> types.FunctionType:
    _need(type(actual) is types.FunctionType, "helper_function_type_invalid")
    function = actual
    _need(
        function.__globals__ is owner.__dict__,
        "helper_function_globals_owner_invalid:" + expected_function.__qualname__,
    )
    _need(
        _function_code_fingerprint(function.__code__)
        == _function_code_fingerprint(expected_function.__code__),
        "helper_function_code_mismatch:" + expected_function.__qualname__,
    )
    _need(function.__name__ == expected_function.__name__, "helper_function_name_mismatch")
    _need(
        function.__qualname__ == expected_function.__qualname__,
        "helper_function_qualname_mismatch",
    )
    _need(
        _same_literal(function.__defaults__, expected_function.__defaults__),
        "helper_function_defaults_mismatch",
    )
    _need(
        _same_literal(function.__kwdefaults__, expected_function.__kwdefaults__),
        "helper_function_kwdefaults_mismatch",
    )
    _need(function.__closure__ is None, "helper_function_closure_mismatch")
    return function


def _same_module_value(actual: object, expected: object, actual_module: types.ModuleType) -> bool:
    if type(expected) is types.FunctionType:
        if (
            type(actual) is not types.FunctionType
            or actual.__globals__ is not actual_module.__dict__
        ):
            return False
        return (
            _function_code_fingerprint(actual.__code__)
            == _function_code_fingerprint(expected.__code__)
            and actual.__defaults__ == expected.__defaults__
            and actual.__kwdefaults__ == expected.__kwdefaults__
            and actual.__closure__ is None
        )
    if isinstance(expected, type) and expected.__module__ != "builtins":
        return (
            isinstance(actual, type)
            and actual.__module__ == expected.__module__
            and actual.__qualname__ == expected.__qualname__
            and actual.__bases__ == expected.__bases__
            and getattr(actual, "_fields_", None) == getattr(expected, "_fields_", None)
        )
    return _same_literal(actual, expected)


def _verify_function_globals(
    function: types.FunctionType,
    reference: types.FunctionType,
    owner: types.ModuleType,
    reference_owner: types.ModuleType,
    visited: set[str],
) -> None:
    qualname = reference.__qualname__
    reference_wrapped = getattr(reference, "__wrapped__", None)
    actual_wrapped = getattr(function, "__wrapped__", None)
    if type(reference_wrapped) is types.FunctionType:
        wrapper_key = qualname + "#contextmanager"
        if wrapper_key in visited:
            return
        visited.add(wrapper_key)
        _need(type(function) is types.FunctionType, "helper_contextmanager_type_invalid")
        generated = contextlib.contextmanager(reference_wrapped)
        _need(
            function.__globals__ is contextlib.__dict__
            and _function_code_fingerprint(function.__code__)
            == _function_code_fingerprint(generated.__code__)
            and function.__name__ == generated.__name__
            and function.__qualname__ == generated.__qualname__
            and function.__module__ == generated.__module__
            and _same_literal(function.__defaults__, generated.__defaults__)
            and _same_literal(function.__kwdefaults__, generated.__kwdefaults__)
            and type(actual_wrapped) is types.FunctionType
            and function.__closure__ is not None
            and len(function.__closure__) == len(generated.__closure__ or ())
            and all(
                actual_cell.cell_contents is actual_wrapped
                and reference_cell.cell_contents is reference_wrapped
                for actual_cell, reference_cell in zip(
                    function.__closure__ or (), generated.__closure__ or ()
                )
            ),
            "helper_contextmanager_wrapper_invalid",
        )
        _verify_function_globals(
            actual_wrapped,
            reference_wrapped,
            owner,
            reference_owner,
            visited,
        )
        return
    if qualname in visited:
        return
    visited.add(qualname)
    _assert_function(function, reference, owner)
    _need(
        function.__annotations__ == reference.__annotations__,
        "helper_function_annotations_mismatch",
    )
    for instruction in dis.get_instructions(reference.__code__):
        if instruction.opname not in {"LOAD_GLOBAL", "LOAD_NAME"}:
            continue
        name = instruction.argval
        if name in reference_owner.__dict__:
            expected = reference_owner.__dict__[name]
            actual = owner.__dict__.get(name, _MISSING)
            if name == "_API" and (actual is None or type(actual) is owner.__dict__.get("_Win32")):
                continue
            _need(
                _same_module_value(actual, expected, owner),
                "helper_global_dependency_mismatch",
            )
            if type(expected) is types.FunctionType:
                _verify_function_globals(
                    actual,
                    expected,
                    owner,
                    reference_owner,
                    visited,
                )
        else:
            _need(
                owner.__dict__.get("__builtins__") is builtins.__dict__
                and name in builtins.__dict__,
                "helper_builtin_dependency_mismatch",
            )


def _verify_helper_module(
    module: object,
    relative_path: Path,
    source_hash: str,
    source_limit: int,
    expected_name: str,
    required_functions: tuple[str, ...],
) -> tuple[types.ModuleType, types.ModuleType]:
    _need(type(module) is types.ModuleType, "helper_module_type_invalid")
    expected_path = ROOT / relative_path
    try:
        actual_path = Path(module.__file__).resolve(strict=True)
        spec_origin = Path(module.__spec__.origin).resolve(strict=True)
    except BaseException:
        raise RootHeldSourceError("helper_module_origin_invalid") from None
    _need(
        module.__name__ == expected_name
        and actual_path == expected_path
        and spec_origin == expected_path
        and module.__dict__.get("__builtins__") is builtins.__dict__,
        "helper_module_origin_invalid",
    )
    raw = _bounded_public_source(relative_path, source_limit, source_hash)
    reference = types.ModuleType(expected_name)
    reference.__file__ = str(expected_path)
    reference.__package__ = expected_name.rpartition(".")[0]
    reference.__spec__ = types.SimpleNamespace(origin=str(expected_path))
    try:
        exec(compile(raw, str(expected_path), "exec", dont_inherit=True), reference.__dict__)
    except BaseException:
        raise RootHeldSourceError("helper_reference_load_failed") from None
    for qualname in required_functions:
        expected = reference
        actual = module
        parts = qualname.split(".")
        for part in parts[:-1]:
            expected = getattr(expected, part, _MISSING)
            actual = getattr(actual, part, _MISSING)
        reference_function = getattr(expected, parts[-1], _MISSING)
        actual_function = getattr(actual, parts[-1], _MISSING)
        _need(type(reference_function) is types.FunctionType, "helper_source_function_missing")
        _verify_function_globals(
            actual_function,
            reference_function,
            module,
            reference,
            set(),
        )
    return module, reference


def _verify_public_helpers(
    private_module: object, cli_module: object
) -> tuple[types.ModuleType, types.ModuleType, types.ModuleType, types.ModuleType]:
    private, private_reference = _verify_helper_module(
        private_module,
        PRIVATE_SOURCE_REL,
        PRIVATE_SOURCE_SHA256,
        _MAX_PRIVATE_SOURCE_BYTES,
        "backtrader_runtime.certification_roundtrip_private",
        (
            "_fail",
            "_path",
            "_Win32.__init__",
            "_Win32.info",
            "_Win32.opened",
            "_Win32.verify_acl",
            "_api",
        ),
    )
    cli, cli_reference = _verify_helper_module(
        cli_module,
        CLI_SOURCE_REL,
        CLI_SOURCE_SHA256,
        _MAX_CLI_SOURCE_BYTES,
        "backtrader_runtime.certification_binance_roundtrip_r3_cli",
        ("_require", "_locked_file_identity", "_locked_readonly_file", "_read_bounded_handle"),
    )
    _need(
        isinstance(private.__dict__.get("_FILE_INFO"), type)
        and isinstance(private.__dict__.get("_Win32"), type)
        and type(cli.__dict__.get("_locked_readonly_file")) is types.FunctionType,
        "helper_source_types_invalid",
    )
    return private, cli, private_reference, cli_reference


def _verify_bound_helpers(private, cli, private_reference, cli_reference):
    for owner, reference_owner, names in (
        (
            private,
            private_reference,
            (
                "_fail",
                "_path",
                "_Win32.__init__",
                "_Win32.info",
                "_Win32.opened",
                "_Win32.verify_acl",
                "_api",
            ),
        ),
        (
            cli,
            cli_reference,
            ("_require", "_locked_file_identity", "_locked_readonly_file", "_read_bounded_handle"),
        ),
    ):
        for qualname in names:
            actual = owner
            expected = reference_owner
            parts = qualname.split(".")
            for part in parts[:-1]:
                actual = getattr(actual, part, _MISSING)
                expected = getattr(expected, part, _MISSING)
            function = getattr(actual, parts[-1], _MISSING)
            reference = getattr(expected, parts[-1], _MISSING)
            _verify_function_globals(function, reference, owner, reference_owner, set())


def _is_opaque(path: Path) -> bool:
    return path.suffix.lower() in _OPAQUE_SUFFIXES


def _row_limit(path: Path) -> int:
    suffix = path.suffix.lower()
    if suffix in {".dll", ".pyd"}:
        return _MAX_NATIVE_BYTES
    if suffix == ".whl":
        return _MAX_WHEEL_BYTES
    if suffix == ".pyc":
        return _MAX_PYC_BYTES
    return _MAX_DEFAULT_ROW_BYTES


def _path_policy(path: Path, category: str) -> bool:
    parts = tuple(part.casefold() for part in path.parts)
    name = path.name.casefold()
    _need(
        name not in _CREDENTIAL_NAMES and not name.startswith(".env."),
        "credential_path_rejected",
    )
    _need(path.suffix.casefold() not in _CREDENTIAL_SUFFIXES, "credential_path_rejected")
    _need(not any(part in _SENSITIVE_DIRECTORY_NAMES for part in parts), "credential_path_rejected")
    suffix = path.suffix.casefold()
    stem_tokens = set(re.split(r"[._\-\s]+", path.stem.casefold()))
    _need(
        not (suffix in _AUTHORITY_DATA_SUFFIXES and stem_tokens.intersection(_AUTHORITY_TOKENS)),
        "authority_artifact_path_rejected",
    )
    is_temp_path = any(part in {"temp", "tmp"} for part in parts)
    _need(
        not is_temp_path or category in {"public", "software"},
        "restricted_source_path_rejected",
    )
    _need(".." not in path.parts, "source_path_traversal_rejected")
    return _is_opaque(path)


def _canonical_path(path: Path) -> str:
    return ntpath.normcase(ntpath.normpath(str(path))).replace("/", "\\")


def _path_key(path: Path) -> str:
    return _canonical_path(path).casefold()


class _HeldRow:
    __slots__ = (
        "key", "logical_origin", "path", "digest", "maximum", "category",
        "opaque", "handle", "identity", "size",
    )

    def __init__(self, key, logical_origin, path, digest, maximum, category):
        self.key = key
        self.logical_origin = logical_origin
        self.path = path
        self.digest = digest
        self.maximum = maximum
        self.category = category
        # Software metadata and runtime images are hash-only custody rows.
        # Public source rows are readable only when their suffix is non-opaque.
        self.opaque = category == "software" or _is_opaque(path)
        self.handle = None
        self.identity = None
        self.size = None


def _normalize_bindings(bindings: object, private: types.ModuleType):
    _need(type(bindings) in (list, tuple), "source_binding_rows_invalid")
    _need(len(bindings) <= _MAX_ROWS, "source_binding_rows_limit")
    result = []
    seen_logical: set[str] = set()
    seen_paths: set[str] = set()
    required_keys = {"logical_origin", "physical_path", "sha256", "max_bytes", "category"}
    for item in bindings:
        _need(type(item) is dict and set(item) == required_keys, "source_binding_row_shape_invalid")
        logical = item["logical_origin"]
        _need(
            type(logical) is str and 0 < len(logical) <= 4096
            and not any(ord(char) < 32 for char in logical),
            "source_logical_origin_invalid",
        )
        logical_key = logical.casefold()
        _need(logical_key not in seen_logical, "source_logical_origin_duplicate")
        seen_logical.add(logical_key)
        raw_path = item["physical_path"]
        _need(
            type(raw_path) is str or type(raw_path) is _PATH_IMPL_TYPE,
            "source_path_type_invalid",
        )
        category = item["category"]
        _need(
            type(category) is str and category in {"public", "software", "support"},
            "source_category_invalid",
        )
        try:
            path = private._path(Path(raw_path))
        except BaseException:
            raise RootHeldSourceError("source_path_invalid") from None
        if any(part.casefold() in {"temp", "tmp"} for part in path.parts):
            _need(path.is_absolute(), "source_path_not_absolute")
        key = _path_key(path)
        _need(key not in seen_paths, "source_path_alias_rejected")
        seen_paths.add(key)
        opaque = _path_policy(path, category)
        digest = item["sha256"]
        if category == "software" and digest is None:
            pass  # Runtime software hashes are measured from the held handle.
        else:
            _need(
                type(digest) is str and _HASH.fullmatch(digest) is not None,
                "source_digest_invalid",
            )
        maximum = item["max_bytes"]
        _need(
            type(maximum) is int and 0 < maximum <= _row_limit(path),
            "source_row_limit_invalid",
        )
        result.append(_HeldRow(key, logical, path, digest, maximum, category))
    return tuple(sorted(result, key=lambda row: row.key))


def _retain_scope(scope):
    if not any(item is scope for item in _RETAINED_SCOPES):
        _RETAINED_SCOPES.append(scope)


def _forget_scope(scope):
    _RETAINED_SCOPES[:] = [item for item in _RETAINED_SCOPES if item is not scope]


def _bootstrap_fixed_helpers():
    """Cold-check both public helper files before executing either one."""
    private_raw = _bounded_public_source(
        PRIVATE_SOURCE_REL, _MAX_PRIVATE_SOURCE_BYTES, PRIVATE_SOURCE_SHA256
    )
    cli_raw = _bounded_public_source(CLI_SOURCE_REL, _MAX_CLI_SOURCE_BYTES, CLI_SOURCE_SHA256)
    private_path = ROOT / PRIVATE_SOURCE_REL
    cli_path = ROOT / CLI_SOURCE_REL
    package_name = "backtrader_runtime"
    private_name = "backtrader_runtime.certification_roundtrip_private"
    cli_name = "backtrader_runtime.certification_binance_roundtrip_r3_cli"
    old_package = sys.modules.get(package_name, _MISSING)
    old_private = sys.modules.get(private_name, _MISSING)
    old_cli = sys.modules.get(cli_name, _MISSING)
    package = types.ModuleType(package_name)
    package.__path__ = [str(ROOT / "backtrader_runtime")]
    package.__package__ = package_name
    package.__spec__ = types.SimpleNamespace(
        origin=None, submodule_search_locations=package.__path__
    )
    private = types.ModuleType(private_name)
    private.__file__ = str(private_path)
    private.__package__ = package_name
    private.__spec__ = types.SimpleNamespace(origin=str(private_path))
    cli = types.ModuleType(cli_name)
    cli.__file__ = str(cli_path)
    cli.__package__ = package_name
    cli.__spec__ = types.SimpleNamespace(origin=str(cli_path))
    verified = None
    try:
        sys.modules[package_name] = package
        sys.modules[private_name] = private
        exec(compile(private_raw, str(private_path), "exec", dont_inherit=True), private.__dict__)
        package.certification_roundtrip_private = private
        sys.modules[cli_name] = cli
        exec(compile(cli_raw, str(cli_path), "exec", dont_inherit=True), cli.__dict__)
        verified = _verify_public_helpers(private, cli)
    except BaseException:
        raise RootHeldSourceError("helper_source_bootstrap_failed") from None
    finally:
        for name, prior in (
            (cli_name, old_cli),
            (private_name, old_private),
            (package_name, old_package),
        ):
            if prior is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior
    _need(type(verified) is tuple and len(verified) == 4, "helper_source_verification_missing")
    _need(private.__dict__.get("_API") is None, "source_helper_api_already_initialized")
    return private, cli, private_raw, cli_raw, verified[2], verified[3]


_SOURCE_FAKE_TOKEN = object()


class RootHeldScopeV3:
    """One-owner physical source scope over exact caller-resolved bindings."""

    def __init__(self, bindings=(), *, enabled: bool = ROOT_HELD_SCOPE_V3_ENABLED):
        _need(type(enabled) is bool and enabled is True, "root_held_scope_activation_unset")
        (
            private,
            cli,
            private_raw,
            cli_raw,
            private_reference,
            cli_reference,
        ) = _bootstrap_fixed_helpers()
        self.schema = ROOT_HELD_SCOPE_V3_SCHEMA
        self.test_only = False
        self._private = private
        self._cli = cli
        self._private_raw = private_raw
        self._cli_raw = cli_raw
        self._private_reference = private_reference
        self._cli_reference = cli_reference
        self._private_factory = private._api
        self._win32_type = private._Win32
        self._locked_file = cli._locked_readonly_file
        self._locked_identity = cli._locked_file_identity
        self._bounded_reader = cli._read_bounded_handle
        self._initial_rows = _normalize_bindings(bindings, private)
        self._api = None
        self._stack = None
        self._state = "NEW"
        self._owner = None
        self._rows: dict[str, _HeldRow] = {}
        self._logical: dict[str, str] = {}
        self._directories: dict[str, tuple[Path, object, tuple[int, int]]] = {}
        self._bytes: dict[str, bytes] = {}
        self._postverified = False
        self._failure = None

    @property
    def state(self):
        return self._state

    @property
    def private(self):
        return self._private

    @property
    def cli(self):
        return self._cli

    @property
    def raw_held(self):
        self._require_owner_open()
        return self._bytes

    def __iter__(self):
        self._require_owner_open()
        return iter((self._private, self._cli, self._bytes))

    def _require_owner_open(self):
        _need(self._state in {"OPEN", "POSTVERIFIED", "RETAINED"}, "source_scope_not_open")
        _need(self._owner == threading.get_ident(), "source_scope_owner_mismatch")

    def _assert_helper_objects(self):
        _need(
            self._private._api is self._private_factory
            and self._private._Win32 is self._win32_type
            and self._cli._locked_readonly_file is self._locked_file
            and self._cli._locked_file_identity is self._locked_identity
            and self._cli._read_bounded_handle is self._bounded_reader,
            "helper_object_identity_changed",
        )

    def __enter__(self):
        _need(self._state == "NEW" and self.test_only is False, "source_scope_reuse_rejected")
        _need(self._private.__dict__.get("_API") is None, "source_helper_api_already_initialized")
        self._owner = threading.get_ident()
        stack = ExitStack()
        stack.__enter__()
        self._stack = stack
        self._state = "OPENING"
        _retain_scope(self)
        try:
            _verify_bound_helpers(
                self._private, self._cli, self._private_reference, self._cli_reference
            )
            self._assert_helper_objects()
            api = self._private._api()
            _need(type(api) is self._win32_type, "source_api_type_invalid")
            self._api = api
            self._state = "OPEN"
            if self._initial_rows:
                self._hold_rows(self._initial_rows)
            return self
        except RootHeldSourceError:
            self._state = "RETAINED"
            self._failure = "source_scope_open_failed"
            raise
        except BaseException:
            self._state = "RETAINED"
            self._failure = "source_scope_open_failed"
            raise RootHeldSourceError("source_scope_open_failed") from None

    def _sourcefake_enter(self, api, token):
        """Test-only bottom-leaf seam. Production entry never accepts operations."""
        _need(token is _SOURCE_FAKE_TOKEN, "sourcefake_token_invalid")
        _need(self._state == "NEW", "source_scope_reuse_rejected")
        self._owner = threading.get_ident()
        self.test_only = True
        self._api = api
        stack = ExitStack()
        stack.__enter__()
        self._stack = stack
        self._state = "OPEN"
        _retain_scope(self)
        if self._initial_rows:
            self._hold_rows(self._initial_rows)
        return self

    def _file_info(self, handle):
        info = self._private._FILE_INFO()
        try:
            ok = self._api.kernel.GetFileInformationByHandle(handle, ctypes.byref(info))
        except BaseException:
            raise RootHeldSourceError("source_handle_info_failed") from None
        _need(bool(ok), "source_handle_info_failed")
        return info

    def _file_size(self, handle):
        info = self._file_info(handle)
        _need(
            not info.attributes & 0x400 and not info.attributes & 0x10,
            "source_handle_type_invalid",
        )
        return (int(info.size_high) << 32) | int(info.size_low)

    def _identity(self, handle, *, directory=False, allow_hardlinks=False):
        if directory:
            return self._api.info(handle, directory=True)
        try:
            return self._locked_identity(
                self._api, handle, self._private, allow_hardlinks=allow_hardlinks
            )
        except BaseException:
            raise RootHeldSourceError("source_handle_identity_invalid") from None

    def _ensure_directories(self, paths):
        requested = {}
        for path in paths:
            for ancestor in path.parents:
                key = _path_key(ancestor)
                if key not in self._directories:
                    requested[key] = ancestor
        for key in sorted(requested, key=lambda value: (len(Path(value).parts), value)):
            path = requested[key]
            try:
                manager = self._api.opened(path, directory=True, access=0x80)
                handle = self._stack.enter_context(manager)
                identity = self._identity(handle, directory=True)
            except BaseException:
                raise RootHeldSourceError("source_ancestor_hold_failed") from None
            _need(
                type(identity) is tuple and len(identity) == 2
                and all(type(value) is int and value >= 0 for value in identity),
                "source_ancestor_identity_invalid",
            )
            self._directories[key] = (path, handle, identity)

    def _read_row_handle(self, row, maximum):
        allow_hardlinks = row.category == "software"
        try:
            identity = self._identity(row.handle, allow_hardlinks=allow_hardlinks)
            size = self._file_size(row.handle)
            _need(identity == row.identity, "source_handle_identity_changed")
            _need(size == row.size and size <= maximum, "source_handle_size_changed")
            self._seek_start(row.handle)
            raw = self._bounded_reader(self._api, row.handle, maximum)
        except RootHeldSourceError:
            raise
        except BaseException:
            raise RootHeldSourceError("source_handle_read_failed") from None
        _need(type(raw) is bytes and len(raw) == row.size, "source_handle_size_changed")
        _need(_sha(raw) == row.digest, "source_handle_digest_mismatch")
        _need(
            self._identity(row.handle, allow_hardlinks=allow_hardlinks) == row.identity
            and self._file_size(row.handle) == row.size,
            "source_handle_identity_changed",
        )
        return raw

    def _seek_start(self, handle):
        try:
            seek = self._api.kernel.SetFilePointerEx
            seek.argtypes = [
                ctypes.c_void_p,
                ctypes.c_longlong,
                ctypes.POINTER(ctypes.c_longlong),
                ctypes.c_uint32,
            ]
            seek.restype = ctypes.c_int
            position = ctypes.c_longlong()
            ok = seek(handle, ctypes.c_longlong(0), ctypes.byref(position), 0)
        except BaseException:
            raise RootHeldSourceError("source_handle_seek_failed") from None
        _need(bool(ok) and position.value == 0, "source_handle_seek_failed")

    def resolve_and_hold(self, bindings):
        self._require_owner_open()
        _need(self._state == "OPEN", "source_scope_not_extendable")
        _need(self._postverified is False, "source_scope_already_postverified")
        _need(self.test_only is False or self._api is not None, "sourcefake_api_missing")
        new_rows = _normalize_bindings(bindings, self._private)
        return self._hold_rows(new_rows)

    def _hold_rows(self, new_rows):
        self._require_owner_open()
        _need(self._state == "OPEN", "source_scope_not_extendable")
        _need(self._postverified is False, "source_scope_already_postverified")
        for row in new_rows:
            prior = self._rows.get(row.key)
            if prior is not None:
                _need(
                    prior.logical_origin == row.logical_origin
                    and (
                        row.digest is None and prior.category == "software"
                        or prior.digest == row.digest
                    )
                    and prior.maximum == row.maximum
                    and prior.category == row.category,
                    "source_binding_conflict",
                )
                continue
            _need(
                row.logical_origin.casefold() not in self._logical,
                "source_logical_origin_duplicate",
            )
        pending = [row for row in new_rows if row.key not in self._rows]
        _need(len(self._rows) + len(pending) <= _MAX_ROWS, "source_binding_rows_limit")
        self._ensure_directories([row.path for row in pending])
        total = sum(row.size or 0 for row in self._rows.values())
        for row in pending:
            allow_hardlinks = row.category == "software"
            try:
                manager = self._locked_file(
                    row.path, self._private, self._api, allow_hardlinks=allow_hardlinks
                )
                row.handle, row.identity = self._stack.enter_context(manager)
                size = self._file_size(row.handle)
                _need(size <= row.maximum, "source_row_size_limit")
                total += size
                _need(total <= _MAX_TOTAL_BYTES, "source_total_size_limit")
                row.size = size
                if row.digest is None:
                    self._seek_start(row.handle)
                    measured = self._bounded_reader(self._api, row.handle, row.maximum)
                    _need(
                        type(measured) is bytes and len(measured) == size,
                        "source_handle_size_changed",
                    )
                    row.digest = _sha(measured)
                    _need(
                        self._identity(row.handle, allow_hardlinks=True) == row.identity
                        and self._file_size(row.handle) == size,
                        "source_handle_identity_changed",
                    )
                    if not row.opaque:
                        self._bytes[row.key] = measured
                else:
                    raw = self._read_row_handle(row, row.maximum)
                    if not row.opaque:
                        self._bytes[row.key] = raw
                self._rows[row.key] = row
                self._logical[row.logical_origin.casefold()] = row.key
                self._postverified = False
            except RootHeldSourceError:
                self._state = "RETAINED"
                self._failure = "source_binding_hold_failed"
                raise
            except BaseException:
                self._state = "RETAINED"
                self._failure = "source_binding_hold_failed"
                raise RootHeldSourceError("source_binding_hold_failed") from None
        ordered_bytes = sorted(self._bytes.items())
        self._bytes.clear()
        self._bytes.update(ordered_bytes)
        return self

    def _find_row(self, path):
        _need(type(path) is str or type(path) is _PATH_IMPL_TYPE, "source_read_path_type_invalid")
        try:
            normalized = self._private._path(Path(path))
        except BaseException:
            raise RootHeldSourceError("source_read_path_invalid") from None
        key = _path_key(normalized)
        row = self._rows.get(key)
        _need(row is not None, "source_read_row_unknown")
        return row

    def read_held(self, path, digest, max_bytes):
        """Reread bounded non-opaque bytes from the exact still-held handle."""
        self._require_owner_open()
        row = self._find_row(path)
        _need(type(digest) is str and digest == row.digest, "source_read_digest_mismatch")
        _need(type(max_bytes) is int and 0 < max_bytes <= row.maximum, "source_read_limit_invalid")
        _need(not row.opaque, "opaque_source_bytes_unavailable")
        raw = self._read_row_handle(row, max_bytes)
        self._bytes[row.key] = raw
        return raw

    def read_logical(self, logical_origin, max_bytes=None):
        self._require_owner_open()
        _need(type(logical_origin) is str, "source_logical_origin_invalid")
        key = self._logical.get(logical_origin.casefold())
        _need(key is not None, "source_logical_origin_unknown")
        row = self._rows[key]
        maximum = row.maximum if max_bytes is None else max_bytes
        return self.read_held(row.path, row.digest, maximum)

    def verify_pin(self, path, digest):
        """Verify any held row, including opaque payloads, from its same handle."""
        self._require_owner_open()
        row = self._find_row(path)
        _need(type(digest) is str and digest == row.digest, "source_read_digest_mismatch")
        raw = self._read_row_handle(row, row.maximum)
        if not row.opaque:
            self._bytes[row.key] = raw
        return True

    def physical_for(self, logical_origin):
        self._require_owner_open()
        _need(type(logical_origin) is str, "source_logical_origin_invalid")
        key = self._logical.get(logical_origin.casefold())
        _need(key is not None, "source_logical_origin_unknown")
        return _canonical_path(self._rows[key].path)

    def logical_bindings(self):
        self._require_owner_open()
        return {
            self._rows[key].logical_origin: {
                "physical_path": _canonical_path(self._rows[key].path),
                "sha256": self._rows[key].digest,
                "max_bytes": self._rows[key].maximum,
                "category": self._rows[key].category,
            }
            for key in sorted(self._rows)
        }

    def _category_map(self, category):
        self._require_owner_open()
        return {
            _canonical_path(self._rows[key].path): self._rows[key].digest
            for key in sorted(self._rows)
            if self._rows[key].category == category
        }

    @property
    def public_map(self):
        return self._category_map("public")

    @property
    def software_map(self):
        return self._category_map("software")

    @property
    def support_map(self):
        return self._category_map("support")

    def manifest(self):
        self._require_owner_open()
        return {
            _canonical_path(row.path): row.digest
            for row in sorted(self._rows.values(), key=lambda item: item.key)
        }

    def _verify_directory_handles(self):
        for path, handle, identity in self._directories.values():
            try:
                actual = self._identity(handle, directory=True)
            except BaseException:
                raise RootHeldSourceError("source_ancestor_postverify_failed") from None
            _need(actual == identity, "source_ancestor_identity_changed")

    def postverify(self):
        self._require_owner_open()
        self._verify_directory_handles()
        for row in tuple(self._rows.values()):
            self.verify_pin(row.path, row.digest)
        self._verify_directory_handles()
        self._postverified = True
        self._state = "POSTVERIFIED"
        return True

    def release(self, code, result):
        """Close only after an exact code-0 clean result and same-handle reread."""
        self._require_owner_open()
        if (
            type(code) is not int or code != 0
            or type(result) is not bool or result is not True
            or self._failure is not None or self._state == "RETAINED"
        ):
            self._state = "RETAINED"
            _retain_scope(self)
            return False
        try:
            self.postverify()
        except RootHeldSourceError:
            self._state = "RETAINED"
            self._failure = "source_scope_postverify_failed"
            _retain_scope(self)
            return False
        try:
            self._stack.close()
        except BaseException:
            self._state = "RETAINED"
            self._failure = "source_scope_close_failed"
            _retain_scope(self)
            return False
        self._state = "CLOSED"
        _forget_scope(self)
        return True

    def __exit__(self, exc_type, exc, traceback):
        self._require_owner_open()
        already_retained = self._state == "RETAINED"
        try:
            self.postverify()
            if already_retained:
                self._state = "RETAINED"
        except RootHeldSourceError as error:
            self._state = "RETAINED"
            self._failure = error.args[0] if error.args else "source_scope_postverify_failed"
            _retain_scope(self)
            if exc_type is None:
                raise
        except BaseException:
            self._state = "RETAINED"
            self._failure = "source_scope_postverify_failed"
            _retain_scope(self)
            if exc_type is None:
                raise RootHeldSourceError("source_scope_postverify_failed") from None
        return False
