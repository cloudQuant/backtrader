"""Prepare an in-process, public-only V20 Root precheck handle.

This helper never enters CUv2, reads software payloads, inspects environment
values, creates a process/pipe/Job, calls Windows APIs, or invokes either
credential-free gate or C01 activation.  It verifies the frozen public R3
source map and compiles the exact pinned driver bytes once, returning the
module/object snapshot for a Root-owned caller to retain in the same process.

The result is a source-precheck handle, not a gate receipt or C01 authority.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
from types import FunctionType, MappingProxyType, ModuleType
from typing import Any


SCHEMA = "iteration41-simnow-c01-v20-root-public-precheck-v2"
REPOSITORY_ROOT = Path(r"D:\source_code\backtrader")
PIN_MANIFEST_RELATIVE = (
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/"
    "evidence/iteration41-simnow-c01-v20-credential-free-job-channel-r3-2026-10-09/"
    "runtime-source-pins.json"
)
PIN_MANIFEST_SHA256 = "e3e6940ba4799b6e783ef4227a07dd43d628ba74b96e5e958a6c7ffec3a6e387"
PIN_MANIFEST_BYTES = 9069
MAX_PUBLIC_SOURCE_BYTES = 2 * 1024 * 1024
DRIVER_RELATIVE = "scripts/iteration41_simnow_c01_v20_root_actual_driver_r3.py"
DRIVER_MODULE_NAME = "_c01_v20_root_actual_driver"
DRIVER_SHA256 = "4f05194dea1a029a0950dba69e3644ce5e518253aa0d8a727687d707fed0b963"
DRIVER_BYTES = 158926
WRAPPER_RELATIVE = "scripts/run_simnow_c01_native_td_read_v20_root_activation_r2.py"
WRAPPER_SHA256 = "6323c537f852838cdd40f1f92482eb9fd9c57a994cd296074b6e18246badeadd"
EXPECTED_PUBLIC_ROWS = 26
EXPECTED_CHILD_ROWS = 23
EXPECTED_PARENT_MODULE_ROWS = 26
EXPECTED_SOFTWARE_ROWS = 3
EXPECTED_ENVIRONMENT_KEYS = frozenset(
    {"SystemRoot", "WINDIR", "PATH", "TEMP", "TMP", "USERPROFILE"}
)
_GATE_STATE_KEYS = frozenset({"used", "receipt"})
_HOST_STATE_KEYS = frozenset({"used", "lease", "call_nonce", "gate_receipt"})
_PRECHECK_FACTORY = object()


class PublicPrecheckError(ValueError):
    """A fixed-source precheck failure; never includes source or path values."""

    def __init__(self, code: str) -> None:
        safe = code if type(code) is str and code.isascii() else "public_precheck_blocked"
        super().__init__(safe)
        self.code = safe


class PreparedRootPrecheck:
    """Same-process source material and a finite, redacted summary."""

    __slots__ = (
        "driver_module",
        "driver_objects",
        "public_source_pins",
        "public_source_bytes",
        "software_source_pins",
        "_summary",
    )

    def __init__(
        self,
        *,
        driver_module: ModuleType,
        driver_objects: MappingProxyType,
        public_source_pins: MappingProxyType,
        public_source_bytes: MappingProxyType,
        software_source_pins: MappingProxyType,
        summary: dict[str, Any],
        _factory: Any = None,
    ) -> None:
        if _factory is not _PRECHECK_FACTORY:
            raise PublicPrecheckError("precheck_factory_required")
        object.__setattr__(self, "driver_module", driver_module)
        object.__setattr__(self, "driver_objects", driver_objects)
        object.__setattr__(self, "public_source_pins", public_source_pins)
        object.__setattr__(self, "public_source_bytes", public_source_bytes)
        object.__setattr__(self, "software_source_pins", software_source_pins)
        object.__setattr__(self, "_summary", MappingProxyType(summary))

    def __setattr__(self, _name: str, _value: Any) -> None:
        raise AttributeError("PreparedRootPrecheck is immutable")

    def public_summary(self) -> dict[str, Any]:
        """Return only finite public pins and booleans; source bytes stay in memory."""

        value = dict(self._summary)
        value["public_source_rows"] = [dict(row) for row in self._summary["public_source_rows"]]
        value["environment_keys"] = list(self._summary["environment_keys"])
        return value

    def __repr__(self) -> str:
        return "PreparedRootPrecheck(<26 public sources; module and bytes redacted>)"


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _read_public_file(root: Path, relative: str, byte_limit: int) -> bytes:
    pure = PurePosixPath(relative)
    if (
        type(relative) is not str
        or not relative
        or pure.is_absolute()
        or ".." in pure.parts
        or pure.as_posix() != relative
        or "\\" in relative
    ):
        raise PublicPrecheckError("public_source_path_invalid")
    if type(byte_limit) is not int or byte_limit <= 0 or byte_limit > MAX_PUBLIC_SOURCE_BYTES:
        raise PublicPrecheckError("public_source_size_limit_invalid")
    root_resolved = root.resolve(strict=True)
    candidate = root_resolved.joinpath(*pure.parts).resolve(strict=True)
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        raise PublicPrecheckError("public_source_path_escape") from None
    if not candidate.is_file():
        raise PublicPrecheckError("public_source_missing")
    try:
        with candidate.open("rb") as stream:
            raw = stream.read(byte_limit + 1)
    except OSError:
        raise PublicPrecheckError("public_source_read_failed") from None
    if type(raw) is not bytes:
        raise PublicPrecheckError("public_source_read_failed")
    if len(raw) > byte_limit:
        raise PublicPrecheckError("public_source_exceeds_size_limit")
    return raw


def _read_manifest(root: Path) -> tuple[dict[str, Any], bytes]:
    raw = _read_public_file(root, PIN_MANIFEST_RELATIVE, PIN_MANIFEST_BYTES)
    if len(raw) != PIN_MANIFEST_BYTES:
        raise PublicPrecheckError("source_manifest_size_mismatch")
    if hashlib.sha256(raw).hexdigest() != PIN_MANIFEST_SHA256:
        raise PublicPrecheckError("source_manifest_pin_mismatch")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=lambda _item: (_ for _ in ()).throw(ValueError("invalid_constant")),
        )
    except Exception:
        raise PublicPrecheckError("source_manifest_invalid") from None
    if type(value) is not dict:
        raise PublicPrecheckError("source_manifest_invalid")
    return value, raw


def _validated_rows(manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    public_rows = manifest.get("public_source_rows")
    software_rows = manifest.get("software_source_rows")
    if (
        type(manifest.get("child_frame_source_count")) is not int
        or manifest["child_frame_source_count"] != EXPECTED_CHILD_ROWS
        or type(manifest.get("parent_module_source_count")) is not int
        or manifest["parent_module_source_count"] != EXPECTED_PARENT_MODULE_ROWS
        or type(public_rows) is not list
        or len(public_rows) != EXPECTED_PUBLIC_ROWS
        or type(software_rows) is not list
        or len(software_rows) != EXPECTED_SOFTWARE_ROWS
    ):
        raise PublicPrecheckError("source_manifest_counts_invalid")
    clean_public: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in public_rows:
        if type(row) is not dict:
            raise PublicPrecheckError("source_manifest_row_invalid")
        path = row.get("path")
        digest = row.get("sha256")
        byte_count = row.get("bytes")
        if (
            type(path) is not str
            or type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or type(byte_count) is not int
            or byte_count <= 0
            or byte_count > MAX_PUBLIC_SOURCE_BYTES
            or path in seen
        ):
            raise PublicPrecheckError("source_manifest_row_invalid")
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != path:
            raise PublicPrecheckError("source_manifest_row_invalid")
        seen.add(path)
        clean_public.append({"path": path, "bytes": byte_count, "sha256": digest})

    by_path = {row["path"]: row["sha256"] for row in clean_public}
    if (
        by_path.get(DRIVER_RELATIVE) != DRIVER_SHA256
        or by_path.get(WRAPPER_RELATIVE) != WRAPPER_SHA256
        or next(row for row in clean_public if row["path"] == DRIVER_RELATIVE)["bytes"]
        != DRIVER_BYTES
    ):
        raise PublicPrecheckError("driver_or_wrapper_pin_invalid")
    software_pins: dict[str, str] = {}
    for row in software_rows:
        if type(row) is not dict:
            raise PublicPrecheckError("software_pin_metadata_invalid")
        path, digest = row.get("path"), row.get("sha256")
        if (
            type(path) is not str
            or type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or path in software_pins
        ):
            raise PublicPrecheckError("software_pin_metadata_invalid")
        software_pins[path] = digest
    if set(by_path) & set(software_pins):
        raise PublicPrecheckError("source_pin_overlap")
    return clean_public, software_pins


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    if len(matches) != 1 or not isinstance(matches[0], ast.FunctionDef):
        raise PublicPrecheckError("environment_source_shape_invalid")
    return matches[0]


def _fixed_environment_keys(driver_tree: ast.Module) -> frozenset[str]:
    function = _function(driver_tree, "_fixed_environment")
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "values" for target in node.targets
        ):
            if not isinstance(node.value, ast.Dict):
                break
            keys: set[str] = set()
            for key in node.value.keys:
                if not isinstance(key, ast.Constant) or type(key.value) is not str:
                    raise PublicPrecheckError("environment_source_shape_invalid")
                keys.add(key.value)
            return frozenset(keys)
    raise PublicPrecheckError("environment_source_shape_invalid")


def _wrapper_environment_keys(wrapper_tree: ast.Module) -> frozenset[str]:
    matches: list[ast.expr] = []
    for node in wrapper_tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_CREDENTIAL_FREE_ENV_KEYS"
            for target in node.targets
        ):
            matches.append(node.value)
    if len(matches) != 1 or not isinstance(matches[0], ast.Call):
        raise PublicPrecheckError("environment_source_shape_invalid")
    call = matches[0]
    if not isinstance(call.func, ast.Name) or call.func.id != "frozenset" or len(call.args) != 1:
        raise PublicPrecheckError("environment_source_shape_invalid")
    try:
        literal = ast.literal_eval(call.args[0])
    except Exception:
        raise PublicPrecheckError("environment_source_shape_invalid") from None
    if type(literal) is not set or any(type(item) is not str for item in literal):
        raise PublicPrecheckError("environment_source_shape_invalid")
    return frozenset(literal)


def _validate_environment_source(driver_raw: bytes, wrapper_raw: bytes) -> frozenset[str]:
    try:
        driver_tree = ast.parse(driver_raw, filename=DRIVER_RELATIVE)
        wrapper_tree = ast.parse(wrapper_raw, filename=WRAPPER_RELATIVE)
    except SyntaxError:
        raise PublicPrecheckError("environment_source_syntax_invalid") from None
    driver_keys = _fixed_environment_keys(driver_tree)
    wrapper_keys = _wrapper_environment_keys(wrapper_tree)
    if driver_keys != EXPECTED_ENVIRONMENT_KEYS or wrapper_keys != EXPECTED_ENVIRONMENT_KEYS:
        raise PublicPrecheckError("environment_allowlist_source_mismatch")

    gate = _function(wrapper_tree, "_run_credential_free_gate")
    names = {node.id for node in ast.walk(gate) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(gate) if isinstance(node, ast.Attribute)}
    calls = {
        node.func.id
        for node in ast.walk(gate)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    if (
        "os" not in names
        or "environ" not in attributes
        or "items" not in attributes
        or "_known_folder_profile_path" not in calls
        or "_consume_bootstrap_stream" not in calls
        or any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(gate))
    ):
        raise PublicPrecheckError("credential_free_gate_source_contract_invalid")
    return driver_keys


def _load_exact_driver(root: Path, raw: bytes) -> tuple[ModuleType, MappingProxyType]:
    if (
        type(raw) is not bytes
        or len(raw) != DRIVER_BYTES
        or hashlib.sha256(raw).hexdigest() != DRIVER_SHA256
    ):
        raise PublicPrecheckError("driver_source_pin_mismatch")
    driver_path = root.joinpath(*PurePosixPath(DRIVER_RELATIVE).parts).resolve(strict=True)
    try:
        spec = importlib.util.spec_from_file_location(DRIVER_MODULE_NAME, str(driver_path))
        if spec is None:
            raise PublicPrecheckError("driver_spec_unavailable")
        module = importlib.util.module_from_spec(spec)
        module.__dict__["__c01_source_sha256__"] = DRIVER_SHA256
        code = compile(raw, str(driver_path), "exec", dont_inherit=True)
        exec(code, module.__dict__)
    except PublicPrecheckError:
        raise
    except Exception:
        raise PublicPrecheckError("driver_compile_load_failed") from None

    capture = module.__dict__.get("capture_c01_v20_driver_objects")
    validate = module.__dict__.get("validate_c01_v20_driver_source_objects")
    required_functions = (
        "run_root_credential_free_job_channel_gate",
        "run_root_activation",
        "_fixed_environment",
        "_validate_fixed_environment",
    )
    if (
        type(module) is not ModuleType
        or module.__name__ != DRIVER_MODULE_NAME
        or module.__dict__.get("__file__") != str(driver_path)
        or module.__dict__.get("__spec__") is not spec
        or type(capture) is not FunctionType
        or type(validate) is not FunctionType
        or capture.__globals__ is not module.__dict__
        or validate.__globals__ is not module.__dict__
        or any(
            type(module.__dict__.get(name)) is not FunctionType
            or module.__dict__[name].__globals__ is not module.__dict__
            or module.__dict__[name].__code__.co_filename != str(driver_path)
            for name in required_functions
        )
    ):
        raise PublicPrecheckError("driver_module_binding_invalid")
    try:
        objects = capture(module)
    except Exception:
        raise PublicPrecheckError("driver_object_capture_failed") from None
    if type(objects) is not MappingProxyType or validate(module, objects) is not True:
        raise PublicPrecheckError("driver_object_binding_invalid")

    if not _latches_pristine(module):
        raise PublicPrecheckError("driver_latches_not_pristine")
    return module, objects


def _latches_pristine(module: ModuleType, *, expected_keepalive: Any = None) -> bool:
    try:
        outer_keepalive = module.__dict__.get("_OUTER_KEEPALIVE")
        if not _gate_host_states_pristine(module) or type(outer_keepalive) is not list:
            return False
        if expected_keepalive is None:
            return not outer_keepalive
        return len(outer_keepalive) == 1 and outer_keepalive[0] is expected_keepalive
    except Exception:
        return False


def _gate_host_states_pristine(module: ModuleType) -> bool:
    try:
        gate_state = module.__dict__.get("_CREDENTIAL_FREE_GATE_STATE")
        host_state = module.__dict__.get("_HOST_ACTIVATION_STATE")
        parent_keepalive = module.__dict__.get("_PARENT_NATIVE_KEEPALIVE")
        return (
            type(gate_state) is dict
            and set(gate_state) == _GATE_STATE_KEYS
            and gate_state.get("used") is False
            and gate_state.get("receipt") is None
            and type(host_state) is dict
            and set(host_state) == _HOST_STATE_KEYS
            and host_state.get("used") is False
            and host_state.get("lease") is None
            and host_state.get("call_nonce") is None
            and host_state.get("gate_receipt") is None
            and type(parent_keepalive) is list
            and not parent_keepalive
        )
    except Exception:
        return False


def validate_prepared_root_precheck(value: Any) -> bool:
    """Recheck the same-process module, object map, public bytes, and empty latches."""

    try:
        if (
            type(value) is not PreparedRootPrecheck
            or type(value.driver_module) is not ModuleType
            or type(value.driver_objects) is not MappingProxyType
            or type(value.public_source_pins) is not MappingProxyType
            or type(value.public_source_bytes) is not MappingProxyType
            or type(value.software_source_pins) is not MappingProxyType
            or len(value.public_source_pins) != EXPECTED_PUBLIC_ROWS
            or set(value.public_source_pins) != set(value.public_source_bytes)
            or len(value.software_source_pins) != EXPECTED_SOFTWARE_ROWS
            or type(value.driver_module.__dict__.get("__c01_source_sha256__")) is not str
            or value.driver_module.__dict__["__c01_source_sha256__"] != DRIVER_SHA256
        ):
            return False
        module = value.driver_module
        driver_path = REPOSITORY_ROOT.joinpath(*PurePosixPath(DRIVER_RELATIVE).parts).resolve(
            strict=True
        )
        raw_driver = value.public_source_bytes.get(DRIVER_RELATIVE)
        wrapper_raw = value.public_source_bytes.get(WRAPPER_RELATIVE)
        if (
            type(raw_driver) is not bytes
            or type(wrapper_raw) is not bytes
            or hashlib.sha256(raw_driver).hexdigest() != DRIVER_SHA256
            or len(raw_driver) != DRIVER_BYTES
            or hashlib.sha256(wrapper_raw).hexdigest() != WRAPPER_SHA256
            or module.__name__ != DRIVER_MODULE_NAME
            or module.__dict__.get("__file__") != str(driver_path)
            or module.__dict__.get("__spec__") is None
            or module.__dict__["__spec__"].origin != str(driver_path)
            or module.__dict__.get("__c01_source_sha256__") != DRIVER_SHA256
            or not _validate_environment_source(raw_driver, wrapper_raw)
        ):
            return False
        for relative, digest in value.public_source_pins.items():
            raw = value.public_source_bytes.get(relative)
            if (
                type(relative) is not str
                or type(digest) is not str
                or type(raw) is not bytes
                or hashlib.sha256(raw).hexdigest() != digest
            ):
                return False
        capture = module.__dict__.get("capture_c01_v20_driver_objects")
        validate = module.__dict__.get("validate_c01_v20_driver_source_objects")
        if (
            type(capture) is not FunctionType
            or capture.__globals__ is not module.__dict__
            or validate(module, value.driver_objects) is not True
        ):
            return False
        return _latches_pristine(module)
    except Exception:
        return False


def validate_precheck_against_entered_lease(value: Any, lease: Any) -> bool:
    """Bind the preloaded exact driver to a caller-owned entered CUv2 lease.

    The caller must create and enter the CUv2 lease through the pinned driver
    API. This check performs no additional file reads and does not close or
    otherwise operate the lease.
    """

    try:
        if type(value) is not PreparedRootPrecheck or not _precheck_handle_valid(value):
            return False
        module = value.driver_module
        lease_type = module.__dict__.get("C01V20OuterSourceLease")
        lease_check = module.__dict__.get("_outer_lease_current")
        if (
            type(lease_type) is not type
            or type(lease) is not lease_type
            or type(lease_check) is not FunctionType
            or lease_check.__globals__ is not module.__dict__
            or lease_check(lease, require_entered=True) is not True
            or lease.source_modules.get(DRIVER_RELATIVE) is not module
            or lease.source_objects.get(DRIVER_RELATIVE) is not value.driver_objects
            or dict(lease.public_source_pins) != dict(value.public_source_pins)
            or dict(lease.software_source_pins) != dict(value.software_source_pins)
            or lease.source_pins is not lease.public_source_pins
            or set(lease.held_source_bytes) != set(value.public_source_bytes)
            or any(
                lease.held_source_bytes[path] != value.public_source_bytes[path]
                for path in value.public_source_bytes
            )
            or lease.keepalive_container_ref is not module.__dict__.get("_OUTER_KEEPALIVE")
            or type(lease.keepalive_ref) is not tuple
            or not _latches_pristine(module, expected_keepalive=lease.keepalive_ref)
        ):
            return False
        return True
    except Exception:
        return False


def _precheck_handle_valid(value: PreparedRootPrecheck) -> bool:
    """Validate source identities while allowing exactly this entered lease."""

    try:
        module = value.driver_module
        if (
            type(module) is not ModuleType
            or module.__name__ != DRIVER_MODULE_NAME
            or type(value.driver_objects) is not MappingProxyType
            or type(value.public_source_pins) is not MappingProxyType
            or type(value.public_source_bytes) is not MappingProxyType
            or type(value.software_source_pins) is not MappingProxyType
            or len(value.public_source_pins) != EXPECTED_PUBLIC_ROWS
            or set(value.public_source_pins) != set(value.public_source_bytes)
            or len(value.software_source_pins) != EXPECTED_SOFTWARE_ROWS
            or type(module.__dict__.get("__c01_source_sha256__")) is not str
            or module.__dict__["__c01_source_sha256__"] != DRIVER_SHA256
        ):
            return False
        driver_path = REPOSITORY_ROOT.joinpath(*PurePosixPath(DRIVER_RELATIVE).parts).resolve(
            strict=True
        )
        if (
            module.__dict__.get("__file__") != str(driver_path)
            or module.__dict__.get("__spec__") is None
            or module.__dict__["__spec__"].origin != str(driver_path)
        ):
            return False
        wrapper_raw = value.public_source_bytes.get(WRAPPER_RELATIVE)
        driver_raw = value.public_source_bytes.get(DRIVER_RELATIVE)
        if (
            type(wrapper_raw) is not bytes
            or type(driver_raw) is not bytes
            or not _validate_environment_source(driver_raw, wrapper_raw)
        ):
            return False
        for path, digest in value.public_source_pins.items():
            raw = value.public_source_bytes.get(path)
            if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != digest:
                return False
        for path, digest in value.software_source_pins.items():
            if (
                type(path) is not str
                or type(digest) is not str
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
                or path in value.public_source_pins
            ):
                return False
        validate = module.__dict__.get("validate_c01_v20_driver_source_objects")
        if type(validate) is not FunctionType or validate(module, value.driver_objects) is not True:
            return False
        return (
            _gate_host_states_pristine(module)
            and type(module.__dict__.get("_OUTER_KEEPALIVE")) is list
        )
    except Exception:
        return False


def prepare_root_public_precheck() -> PreparedRootPrecheck:
    """Verify public R3 sources and prepare the exact driver object in-process.

    This function does not inspect environment values or touch the three
    software payload paths.  Returned bytes are public source bytes only.
    """

    root = REPOSITORY_ROOT
    if not root.is_absolute() or not root.is_dir():
        raise PublicPrecheckError("repository_root_unavailable")
    manifest, _manifest_raw = _read_manifest(root)
    rows, software_pins = _validated_rows(manifest)
    public_bytes: dict[str, bytes] = {}
    for row in rows:
        raw = _read_public_file(root, row["path"], row["bytes"])
        if len(raw) != row["bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise PublicPrecheckError("public_source_pin_mismatch")
        public_bytes[row["path"]] = raw
    if set(public_bytes) != {row["path"] for row in rows}:
        raise PublicPrecheckError("public_source_map_incomplete")
    env_keys = _validate_environment_source(
        public_bytes[DRIVER_RELATIVE], public_bytes[WRAPPER_RELATIVE]
    )
    module, objects = _load_exact_driver(root, public_bytes[DRIVER_RELATIVE])
    row_summary = [
        {"path": row["path"], "bytes": row["bytes"], "sha256": row["sha256"]} for row in rows
    ]
    summary: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "PUBLIC_SOURCE_PREFLIGHT_VERIFIED",
        "runtime_source_manifest_sha256": PIN_MANIFEST_SHA256,
        "driver_module_name": DRIVER_MODULE_NAME,
        "driver_sha256": DRIVER_SHA256,
        "wrapper_sha256": WRAPPER_SHA256,
        "driver_module_binding_verified": True,
        "driver_object_snapshot_verified": True,
        "credential_free_gate_latch_pristine": True,
        "host_activation_latch_pristine": True,
        "fixed_environment_contract_source_verified": True,
        "environment_values_read": False,
        "credential_values_read": False,
        "public_source_count": len(rows),
        "child_frame_source_count": EXPECTED_CHILD_ROWS,
        "parent_module_source_count": EXPECTED_PARENT_MODULE_ROWS,
        "software_source_count": len(software_pins),
        "software_payloads_read": False,
        "cuv2_entered": False,
        "private_inputs_read": False,
        "windows_api_called": False,
        "child_process_created": False,
        "provider_called": False,
        "credential_free_gate_invoked": False,
        "activation_invoked": False,
        "formal_c01_pass": False,
        "official_c01_pass_count": 0,
        "environment_keys": sorted(env_keys),
        "public_source_rows": row_summary,
    }
    return PreparedRootPrecheck(
        driver_module=module,
        driver_objects=objects,
        public_source_pins=MappingProxyType({row["path"]: row["sha256"] for row in rows}),
        public_source_bytes=MappingProxyType(public_bytes),
        software_source_pins=MappingProxyType(dict(software_pins)),
        summary=summary,
        _factory=_PRECHECK_FACTORY,
    )


def main() -> int:
    try:
        result = prepare_root_public_precheck()
    except PublicPrecheckError as exc:
        print(
            json.dumps({"schema": SCHEMA, "status": "BLOCKED", "reason": exc.code}, sort_keys=True)
        )
        return 2
    print(
        json.dumps(
            result.public_summary(), ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
