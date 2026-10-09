"""Fixed child handoff wrapper for the unregistered SimNow C01 V20 candidate.

This entrypoint is launched only by the fixed V11 Root driver.  It accepts no
public arguments or environment supplied channel.  The driver's literal
bootstrap installs one fresh private sentinel and one explicitly inherited
write handle on ``sys``; this module consumes both once, runs the exact V20
source closure, and emits a finite candidate projection on stdout.  The
RootSeal content frame travels only through the separately inherited binary
pipe.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.machinery
import io
import json
import os
from pathlib import Path
import re
import sys
from types import FunctionType, MappingProxyType, ModuleType
from typing import Any, Mapping, Optional, Sequence


_WRAPPER_PATH = "scripts/run_simnow_c01_native_td_read_v20_root_activation_r1.py"
_WRAPPER_MODULE_NAME = "scripts.run_simnow_c01_native_td_read_v20_root_activation_r1"
_FRONT_PATH = "backtrader_runtime/certification_simnow_c01_front_transport_v14.py"
_FRONT_MODULE_NAME = "backtrader_runtime.certification_simnow_c01_front_transport_v14"
_RUNNER_PATH = "examples/000_live_certification/simnow_penetration/cases/C01/run_v20.py"
_RUNNER_MODULE_NAME = "examples.000_live_certification.simnow_penetration.cases.C01.run_v20"
_ISSUER_PATH = "backtrader_runtime/certification_simnow_c01_native_td_read_v20.py"
_PREDECESSOR_PATH = "backtrader_runtime/certification_simnow_c01_native_td_read_v19.py"
_ROOT_PATH = "backtrader_runtime/certification_simnow_c01_root_v17.py"
_CUSTODY_PATH = "backtrader_runtime/certification_simnow_c01_root_custody_v17.py"
_HANDOFF_PATH = "backtrader_runtime/certification_simnow_c01_rootseal_custody_v1.py"
_VALIDATOR_PATH = "examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1.py"
_PROTOCOL_PATH = "backtrader_runtime/certification_simnow_c01_v3_protocol.py"
_WORKER_PATH = "backtrader_runtime/certification_simnow_c01_native_v4.py"
_SUPERVISOR_PATH = "backtrader_runtime/certification_simnow_c01_v4_supervisor.py"
_OWNER_PATH = "backtrader_runtime/certification_simnow_c01_v7_owner.py"
_HELPER_PATHS = {
    "private": "backtrader_runtime/certification_roundtrip_private.py",
    "r3_cli": "backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
    "selector": "scripts/ctp_000_paired_front_selector.py",
    "handoff": "scripts/ctp_000_front_handoff.py",
    "probe": "backtrader_runtime/ctp_front_pair_probe.py",
    "renderer": "scripts/ctp_000_render_config.py",
    "protocol": _PROTOCOL_PATH,
    "contract": "backtrader_runtime/certification_simnow_c01_v3_contract.py",
    "supervisor": _SUPERVISOR_PATH,
    "job_backend": "scripts/ctp_i13_i15_windows_job_backend.py",
    "watchdog": "scripts/ctp_i13_i15_outer_watchdog.py",
    "interpreter_binding": "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py",
}
_HELPER_MODULE_NAMES = {
    "private": "backtrader_runtime.certification_roundtrip_private",
    "r3_cli": "backtrader_runtime.certification_binance_roundtrip_r3_cli",
    "selector": "scripts.ctp_000_paired_front_selector",
    "handoff": "scripts.ctp_000_front_handoff",
    "probe": "backtrader_runtime.ctp_front_pair_probe",
    "renderer": "scripts.ctp_000_render_config",
    "protocol": "backtrader_runtime.certification_simnow_c01_v3_protocol",
    "contract": "backtrader_runtime.certification_simnow_c01_v3_contract",
    "supervisor": "backtrader_runtime.certification_simnow_c01_v4_supervisor",
    "job_backend": "scripts.ctp_i13_i15_windows_job_backend",
    "watchdog": "scripts.ctp_i13_i15_outer_watchdog",
    "interpreter_binding": "backtrader_runtime.certification_simnow_c01_interpreter_binding_v1",
}
_V20_PROFILE = "C01_NATIVE_TD_READ_V20"
_MAX_FRAME_BYTES = 18_087_964
_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_MAX_SMALL_SOURCE_BYTES = 256 * 1024
_SAFE_REASON = re.compile(r"[a-z0-9_:-]{1,96}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_BOOTSTRAP_ATTR = "_c01_v20_frame_channel_bootstrap"
_HANDLE_ATTR = "_c01_v20_frame_channel_handle"
_BOOTSTRAP_CONSUMED_ATTR = "_c01_v20_frame_channel_consumed"
_FRAME_CHANNEL_HANDLE_FACTORY = object()
_C01_V20_FRAME_CHANNEL_FACTORY = object()
_WRAPPER_CALL_FACTORY = object()

# Fixed public source pins.  V20 and this wrapper are pinned by the parent
# driver; the V20 transport pins its issuer; V17 rechecks every supplied byte
# against its own fixed accepted-source map.
_SOURCE_PINS = {
    _PREDECESSOR_PATH: "3de1024b233a0eee55fba7c30df69f04afa38746c9a0e88996e0db7df283fd40",
    _OWNER_PATH: "ee492f115c60ca14f770a055061014f30b7b9cc1cecdfd09cae17f75aabf55e9",
    _PROTOCOL_PATH: "c48b41272ae6378060b0b65188b56ef613f001b53d13db7aceaf13489d398160",
    _WORKER_PATH: "66666d2addc3bddbf0f13a9a30fab9fea83479d7cac7328879552e13baea5a66",
    _SUPERVISOR_PATH: "daf2cf99cbc5d977e27f59efb0f27087abdf3493c9d959d5c3d253744f869da1",
    _VALIDATOR_PATH: "4cbe8465c9b2854d2913de03d4e7a12f020debc8723d6c63539314d2ba7f424a",
    "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py": "a38d00ecfbc7a777edab4b9d090be49ef03a94e7c23340dfe95366bacfd05494",
    "backtrader_runtime/certification_simnow_c01_v3_contract.py": "19d8b13bda11e54a5ca037387b6abc884035ec02c05fb099f2398b99319d8fb0",
    "backtrader_runtime/certification_roundtrip_private.py": "b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd",
    "backtrader_runtime/certification_binance_roundtrip_r3_cli.py": "62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76",
    "backtrader_runtime/ctp_front_pair_probe.py": "d6f92c7d2f6df13480cebcee2c7f864ac305d34d4cda37d1a22c466932d2905f",
    "scripts/ctp_000_render_config.py": "34bf2a99872f43f0d915bafcb0284827a8ac0c4baf70a2ce5f1046888223eac9",
    "scripts/ctp_000_paired_front_selector.py": "08d4025684503ba89c286699ad0511793c536e09af58333963cbecb40ad49ebb",
    "scripts/ctp_000_front_handoff.py": "b08e70e723a5d31f18809129387455dfee3645e6ad9f2b516d7aa2789ffd19f7",
    "scripts/ctp_i13_i15_outer_watchdog.py": "31c945c77c7e147a296e66f4f1ec075e0a23f1a88b94fd339884268e79ca251c",
    "scripts/ctp_i13_i15_windows_job_backend.py": "2566dd55d1a96285473850b1e2c63174696347da56e07d69fb72aa3a6285e381",
}
_ROOT_STATIC_SOURCE_PINS = {
    _ROOT_PATH: "5fc2f7acd7ca0c2e107f846d637a6716c000b61d0b211ec9a2f21651025b7481",
    _CUSTODY_PATH: "8ea25c42a834085c54c87df9b24cb7a1876cf361cd6ca20323f4c5993a59816e",
    _HANDOFF_PATH: "653dd1227902bce3f0e27330833b672d07771f05f3f4d2b1b15e83c8f13e40e7",
    _ISSUER_PATH: "7118ed43cdc012181546f54f7b302ee51d3704860c5746807217c35087257f71",
    _FRONT_PATH: "aa281e122ae4c1e79022dd5b1a9fcbc0afd51f0282aa0e6587671b0d15f8b3a8",
    _RUNNER_PATH: "a2fed5ca72c61ab03795963f3d08f0575972d571fc4ddca7e7f1f79f9645926b",
}

_PROJECTION_KEYS = frozenset(
    {
        "case_id",
        "certification",
        "mode",
        "profile",
        "reason",
        "write_policy",
        "writes",
        "receipt_type",
        "receipt_verified",
        "source_closure_verified",
        "root_postverify_verified",
        "request_count",
        "query_callback_count",
        "snapshot_count",
        "write_invocation_count",
        "outer_job_empty",
        "stdout_eof",
        "stderr_eof",
        "stderr_empty",
        "job_handles_closed",
        "reader_threads_joined",
        "cleanup_verified",
    }
)
_PARENT_ONLY_KEYS = frozenset(
    {
        "outer_job_empty",
        "stdout_eof",
        "stderr_eof",
        "stderr_empty",
        "job_handles_closed",
        "reader_threads_joined",
        "cleanup_verified",
    }
)
_PARENT_DRIVER_MODULE_NAME = "_c01_v20_root_actual_driver"


class C01V20ChildActivationError(RuntimeError):
    """Safe fixed error raised when the child cannot complete a handoff."""

    def __init__(self, code: str = "child_root_handoff_blocked") -> None:
        if type(code) is not str or not _SAFE_REASON.fullmatch(code):
            code = "child_root_handoff_blocked"
        self.code = code
        super().__init__(code)


class C01V20FrameChannelReceipt:
    """One-use binding to the fixed inherited child-to-Root binary stream."""

    __slots__ = (
        "scope",
        "channel",
        "stream",
        "nonce",
        "used",
        "direction",
        "process_id",
        "_factory",
    )

    def __init__(
        self,
        scope: Any,
        stream: Any,
        *,
        _factory: Any = None,
    ) -> None:
        if _factory is not _C01_V20_FRAME_CHANNEL_FACTORY:
            raise C01V20ChildActivationError("frame_channel_factory_required")
        if (
            type(stream) is not io.FileIO
            or stream.closed
            or not stream.writable()
            or type(scope)
            is not getattr(getattr(scope, "root_module", None), "C01RootInvocationScope", None)
            or getattr(scope, "active", None) is not True
            or getattr(scope, "consumed", None) is not False
        ):
            raise C01V20ChildActivationError("frame_channel_binding_invalid")
        self.scope = scope
        self.channel = stream
        self.stream = stream
        self.nonce = object()
        self.used = False
        self.direction = "child_to_root"
        self.process_id = os.getpid()
        self._factory = _C01_V20_FRAME_CHANNEL_FACTORY

    def consume_root_frame_writer(self, scope: Any) -> io.FileIO:
        """Consume the stream once after Root has a staged, returned candidate."""

        if (
            self._factory is not _C01_V20_FRAME_CHANNEL_FACTORY
            or self.scope is not scope
            or self.channel is not self.stream
            or type(self.stream) is not io.FileIO
            or self.stream.closed
            or not self.stream.writable()
            or type(self.nonce) is not object
            or self.used is not False
            or self.direction != "child_to_root"
            or type(self.process_id) is not int
            or self.process_id <= 0
            or self.process_id != os.getpid()
            or getattr(scope, "active", None) is not True
            or getattr(scope, "consumed", None) is not False
            or getattr(scope, "issuer_returned", None) is not True
            or getattr(scope, "stage_count", None) != 1
            or getattr(scope, "root_content_stage", None) is None
            or getattr(scope, "pending", None) is None
            or getattr(scope, "root_content_seal", None) is None
        ):
            raise C01V20ChildActivationError("frame_channel_receipt_invalid")
        self.used = True
        return self.stream

    def __repr__(self) -> str:
        return "C01V20FrameChannelReceipt(<one-use child-to-Root stream>)"


class C01V20WrapperCallReceipt:
    """Parent-local binding of one candidate stdout frame to one supervised call."""

    __slots__ = (
        "projection_raw",
        "frame",
        "parent_process_receipt",
        "child_pid",
        "call_nonce",
        "parent_driver_module",
        "parent_driver_objects",
        "_factory",
    )

    def __init__(
        self,
        projection_raw: bytes,
        frame: Any,
        parent_process_receipt: Any,
        child_pid: int,
        call_nonce: object,
        parent_driver_module: ModuleType,
        parent_driver_objects: Mapping[str, Any],
        *,
        _factory: Any = None,
    ) -> None:
        if _factory is not _WRAPPER_CALL_FACTORY:
            raise ValueError("wrapper_call_receipt_factory_required")
        object.__setattr__(self, "projection_raw", projection_raw)
        object.__setattr__(self, "frame", frame)
        object.__setattr__(self, "parent_process_receipt", parent_process_receipt)
        object.__setattr__(self, "child_pid", child_pid)
        object.__setattr__(self, "call_nonce", call_nonce)
        object.__setattr__(self, "parent_driver_module", parent_driver_module)
        object.__setattr__(self, "parent_driver_objects", parent_driver_objects)
        object.__setattr__(self, "_factory", _WRAPPER_CALL_FACTORY)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("wrapper_call_receipt_immutable")

    def __repr__(self) -> str:
        return "C01V20WrapperCallReceipt(<candidate projection and parent call bound>)"


class _DiscardingTextSink(io.TextIOBase):
    """Drop incidental child text so stdout remains one candidate JSON frame."""

    def writable(self) -> bool:
        return True

    def write(self, value: str) -> int:
        if type(value) is not str:
            raise TypeError("text_required")
        return len(value)

    def flush(self) -> None:
        return None


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_public_source(
    root: Path,
    relative: str,
    *,
    maximum: int = _MAX_SOURCE_BYTES,
    expected_sha256: Optional[str] = None,
) -> bytes:
    path = root / Path(relative)
    try:
        info = path.lstat()
        attributes = getattr(info, "st_file_attributes", 0)
        if (
            path.is_symlink()
            or attributes & 0x400
            or not path.is_file()
            or not path.is_absolute()
            or info.st_size < 1
            or info.st_size > maximum
            or root.resolve(strict=True) not in path.resolve(strict=True).parents
        ):
            raise C01V20ChildActivationError("public_source_unavailable")
        with path.open("rb") as stream:
            raw = stream.read(maximum + 1)
    except C01V20ChildActivationError:
        raise
    except Exception:
        raise C01V20ChildActivationError("public_source_unavailable") from None
    if (
        type(raw) is not bytes
        or len(raw) != info.st_size
        or len(raw) > maximum
        or (expected_sha256 is not None and _sha256(raw) != expected_sha256)
    ):
        raise C01V20ChildActivationError("public_source_mismatch")
    return raw


def _load_module_from_bytes(
    root: Path,
    relative: str,
    module_name: str,
    raw: bytes,
    *,
    register_for_exec: bool = False,
) -> ModuleType:
    path = (root / Path(relative)).resolve(strict=True)
    module = ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = module_name.rpartition(".")[0]
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(module_name, loader=None)
    module.__c01_source_sha256__ = _sha256(raw)
    registered = False
    try:
        if register_for_exec:
            if module_name in sys.modules:
                raise C01V20ChildActivationError("source_module_already_loaded")
            sys.modules[module_name] = module
            registered = True
        exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    except C01V20ChildActivationError:
        raise
    except Exception:
        raise C01V20ChildActivationError("public_source_load_failed") from None
    finally:
        if registered and sys.modules.get(module_name) is module:
            sys.modules.pop(module_name, None)
    return module


def _load_wrapper_module(root: Path) -> tuple[ModuleType, bytes]:
    raw = _read_public_source(root, _WRAPPER_PATH, maximum=_MAX_SOURCE_BYTES)
    module = _load_module_from_bytes(root, _WRAPPER_PATH, _WRAPPER_MODULE_NAME, raw)
    required = (
        "C01V20FrameChannelReceipt",
        "create_c01_v20_wrapper_call_receipt",
        "validate_c01_v20_wrapper_call_receipt",
    )
    if any(name not in module.__dict__ for name in required):
        raise C01V20ChildActivationError("wrapper_source_invalid")
    return module, raw


def _captured_function(
    scope: Any, path: str, name: str, *, owner: Optional[ModuleType] = None
) -> FunctionType:
    module = scope.verified_source_modules[path]
    objects = scope.verified_source_objects[path]
    function = module.__dict__.get(name)
    if (
        type(function) is not FunctionType
        or (owner is not None and function.__globals__ is not owner.__dict__)
        or function.__globals__ is not module.__dict__
        or objects.get(name) is not function
        or objects.get(name + ".__code__") is not function.__code__
        or objects.get(name + ".__globals__") is not module.__dict__
    ):
        raise C01V20ChildActivationError("captured_source_function_invalid")
    return function


def _fixed_root_scope(
    *,
    root: Path,
    wrapper_module: ModuleType,
    wrapper_raw: bytes,
    front_module: ModuleType,
    front_raw: bytes,
    runner_module: ModuleType,
    runner_raw: bytes,
    bundle: Any,
    helpers_source: Mapping[str, bytes],
) -> Any:
    issuer = bundle.issuer
    owner = bundle.owner
    helpers = bundle.helpers
    bundle_type = front_module.__dict__.get("VerifiedC01V20SourceBundle")
    if (
        type(bundle) is not bundle_type
        or bundle_type is not type(bundle)
        or getattr(bundle, "_factory", None) is not front_module.__dict__.get("_BUNDLE_FACTORY")
        or getattr(bundle, "_active", None) is not True
        or type(getattr(bundle, "root", None)) is not type(root)
        or bundle.root != root.resolve(strict=True)
        or getattr(bundle, "issuer", None) is not issuer
        or getattr(bundle, "owner", None) is not owner
        or getattr(bundle, "helpers", None) is not helpers
        or type(issuer) is not ModuleType
        or type(owner) is not ModuleType
        or type(helpers) is not MappingProxyType
        or set(helpers) != set(_HELPER_PATHS) | {"owner_now_utc"}
        or helpers.get("owner_now_utc") is not owner.__dict__.get("_now_utc")
        or any(
            type(helpers.get(name)) is not ModuleType
            or helpers[name].__name__ != _HELPER_MODULE_NAMES[name]
            for name in _HELPER_PATHS
        )
    ):
        raise C01V20ChildActivationError("v20_source_bundle_invalid")

    issuer_source = issuer._read_fixed_source(root, _ISSUER_PATH, front_module._V20_SHA256)
    if _sha256(issuer_source) != issuer.__dict__.get("__c01_source_sha256__"):
        raise C01V20ChildActivationError("v20_source_bundle_invalid")
    owner_source = issuer._read_fixed_source(
        root, _OWNER_PATH, issuer.__dict__.get("_OWNER_SHA256", "")
    )
    predecessor_source = issuer._read_fixed_source(
        root, _PREDECESSOR_PATH, _SOURCE_PINS[_PREDECESSOR_PATH]
    )
    if type(helpers_source) is not dict or not set(_HELPER_PATHS.values()).issubset(helpers_source):
        raise C01V20ChildActivationError("v20_helper_sources_invalid")

    root_raw = _read_public_source(
        root, _ROOT_PATH, expected_sha256=_ROOT_STATIC_SOURCE_PINS.get(_ROOT_PATH)
    )
    custody_raw = _read_public_source(
        root, _CUSTODY_PATH, expected_sha256=_ROOT_STATIC_SOURCE_PINS.get(_CUSTODY_PATH)
    )
    handoff_raw = _read_public_source(
        root, _HANDOFF_PATH, expected_sha256=_ROOT_STATIC_SOURCE_PINS.get(_HANDOFF_PATH)
    )
    validator_raw = _read_public_source(
        root,
        _VALIDATOR_PATH,
        maximum=_MAX_SMALL_SOURCE_BYTES,
        expected_sha256=_SOURCE_PINS[_VALIDATOR_PATH],
    )
    worker_raw = _read_public_source(root, _WORKER_PATH, expected_sha256=_SOURCE_PINS[_WORKER_PATH])
    root_module = _load_module_from_bytes(
        root, _ROOT_PATH, "backtrader_runtime.certification_simnow_c01_root_v17", root_raw
    )
    custody_module = _load_module_from_bytes(
        root,
        _CUSTODY_PATH,
        "backtrader_runtime.certification_simnow_c01_root_custody_v17",
        custody_raw,
    )
    handoff_module = _load_module_from_bytes(
        root,
        _HANDOFF_PATH,
        "backtrader_runtime.certification_simnow_c01_rootseal_custody_v1",
        handoff_raw,
        register_for_exec=True,
    )
    validator_module = _load_module_from_bytes(
        root,
        _VALIDATOR_PATH,
        "common.c01_root_ledger_v1",
        validator_raw,
        register_for_exec=True,
    )
    worker_module = _load_module_from_bytes(
        root, _WORKER_PATH, "backtrader_runtime.certification_simnow_c01_native_v4", worker_raw
    )
    predecessor_module = _load_module_from_bytes(
        root,
        _PREDECESSOR_PATH,
        "backtrader_runtime.certification_simnow_c01_native_td_read_v19",
        predecessor_source,
        register_for_exec=True,
    )
    root_source_modules = {
        _ROOT_PATH: root_module,
        _CUSTODY_PATH: custody_module,
        _HANDOFF_PATH: handoff_module,
        _FRONT_PATH: front_module,
        _RUNNER_PATH: runner_module,
        _VALIDATOR_PATH: validator_module,
        _PROTOCOL_PATH: helpers["protocol"],
        _WORKER_PATH: worker_module,
        _ISSUER_PATH: issuer,
        _PREDECESSOR_PATH: predecessor_module,
        _SUPERVISOR_PATH: helpers["supervisor"],
        _OWNER_PATH: owner,
        _WRAPPER_PATH: wrapper_module,
        **{relative: helpers[name] for name, relative in _HELPER_PATHS.items()},
    }
    root_source_bytes = {
        _ROOT_PATH: root_raw,
        _CUSTODY_PATH: custody_raw,
        _HANDOFF_PATH: handoff_raw,
        _FRONT_PATH: front_raw,
        _RUNNER_PATH: runner_raw,
        _VALIDATOR_PATH: validator_raw,
        _PROTOCOL_PATH: helpers_source[_PROTOCOL_PATH],
        _WORKER_PATH: worker_raw,
        _ISSUER_PATH: issuer_source,
        _PREDECESSOR_PATH: predecessor_source,
        _SUPERVISOR_PATH: helpers_source[_SUPERVISOR_PATH],
        _OWNER_PATH: owner_source,
        _WRAPPER_PATH: wrapper_raw,
        **{relative: helpers_source[relative] for relative in _HELPER_PATHS.values()},
    }
    create_scope = root_module.__dict__.get("create_c01_root_invocation_scope")
    if (
        type(create_scope) is not FunctionType
        or create_scope.__globals__ is not root_module.__dict__
    ):
        raise C01V20ChildActivationError("root_scope_api_invalid")
    try:
        scope = create_scope(root_module, root_source_modules, root_source_bytes)
    except Exception as error:
        if (
            type(error).__name__ == "C01RootV17Error"
            and type(getattr(error, "code", None)) is str
            and _SAFE_REASON.fullmatch(error.code)
        ):
            raise C01V20ChildActivationError("root_scope_" + error.code) from None
        raise C01V20ChildActivationError("root_scope_create_failed") from None
    if (
        type(scope) is not root_module.__dict__.get("C01RootInvocationScope")
        or scope.root_module is not root_module
        or scope.root_custody_module is not custody_module
        or scope.active is not True
        or scope.consumed is not False
        or root_module.__dict__["verify_namespace_freshness_receipt"](
            scope, scope.namespace_freshness_receipt
        )
        is not True
    ):
        raise C01V20ChildActivationError("root_scope_postcheck_failed")
    return scope


def _consume_bootstrap_stream() -> io.FileIO:
    """Consume only the fixed bootstrap's private inherited write handle."""

    if os.name != "nt":
        raise C01V20ChildActivationError("windows_inherited_pipe_required")
    sentinel = getattr(sys, _BOOTSTRAP_ATTR, None)
    handle = getattr(sys, _HANDLE_ATTR, None)
    if (
        type(sentinel) is not object
        or type(handle) is not int
        or handle <= 0
        or getattr(sys, _BOOTSTRAP_CONSUMED_ATTR, False) is True
        or sys.argv != [str(Path("D:/source_code/backtrader") / Path(_WRAPPER_PATH))]
    ):
        raise C01V20ChildActivationError("fixed_child_bootstrap_required")
    try:
        delattr(sys, _BOOTSTRAP_ATTR)
        delattr(sys, _HANDLE_ATTR)
        setattr(sys, _BOOTSTRAP_CONSUMED_ATTR, sentinel)
    except Exception:
        raise C01V20ChildActivationError("fixed_child_bootstrap_required") from None
    try:
        import ctypes
        import msvcrt

        kernel = ctypes.windll.kernel32
        if kernel.GetFileType(ctypes.c_void_p(handle)) != 3:
            raise C01V20ChildActivationError("inherited_handle_not_pipe")
        for standard_id in (-10, -11, -12):
            standard_handle = kernel.GetStdHandle(standard_id)
            if int(ctypes.cast(standard_handle, ctypes.c_void_p).value or 0) == handle:
                raise C01V20ChildActivationError("inherited_handle_is_standard_stream")
        fd = msvcrt.open_osfhandle(handle, os.O_BINARY | os.O_WRONLY)
        stream = io.FileIO(fd, mode="wb", closefd=True)
    except C01V20ChildActivationError:
        raise
    except Exception:
        raise C01V20ChildActivationError("inherited_pipe_conversion_failed") from None
    if type(stream) is not io.FileIO or stream.closed or not stream.writable():
        try:
            stream.close()
        except Exception:
            pass
        raise C01V20ChildActivationError("inherited_pipe_conversion_failed")
    return stream


def _validate_content_summary(content: Any) -> dict[str, int]:
    values = {
        "request_count": getattr(content, "request_count", None),
        "query_callback_count": getattr(content, "query_callback_count", None),
        "snapshot_count": getattr(content, "snapshot_count", None),
        "write_invocation_count": getattr(content, "write_invocation_count", None),
    }
    if (
        type(values["request_count"]) is not int
        or values["request_count"] != 8
        or type(values["query_callback_count"]) is not int
        or not 6 <= values["query_callback_count"] <= 8
        or type(values["snapshot_count"]) is not int
        or values["snapshot_count"] != 2
        or type(values["write_invocation_count"]) is not int
        or values["write_invocation_count"] != 0
    ):
        raise C01V20ChildActivationError("candidate_content_summary_invalid")
    return values  # type: ignore[return-value]


def _child_projection(
    *,
    reason: str,
    receipt_verified: bool,
    source_closure_verified: bool,
    root_postverify_verified: bool,
    counts: Optional[Mapping[str, int]] = None,
) -> dict[str, Any]:
    values = dict(counts or {})
    return {
        "case_id": "C01",
        "certification": "BLOCKED",
        "mode": _V20_PROFILE,
        "profile": _V20_PROFILE,
        "reason": reason,
        "write_policy": "NO_WRITE",
        "writes": 0,
        "receipt_type": "C01RootContentCustodyReceipt" if receipt_verified else None,
        "receipt_verified": receipt_verified,
        "source_closure_verified": source_closure_verified,
        "root_postverify_verified": root_postverify_verified,
        "request_count": values.get("request_count", 0),
        "query_callback_count": values.get("query_callback_count", 0),
        "snapshot_count": values.get("snapshot_count", 0),
        "write_invocation_count": values.get("write_invocation_count", 0),
        "outer_job_empty": None,
        "stdout_eof": None,
        "stderr_eof": None,
        "stderr_empty": None,
        "job_handles_closed": None,
        "reader_threads_joined": None,
        "cleanup_verified": None,
    }


def _validate_candidate_projection(value: Any, *, require_success: bool) -> bool:
    if type(value) is not dict or set(value) != _PROJECTION_KEYS:
        return False
    if (
        value.get("case_id") != "C01"
        or value.get("certification") != "BLOCKED"
        or value.get("mode") != _V20_PROFILE
        or value.get("profile") != _V20_PROFILE
        or type(value.get("reason")) is not str
        or not _SAFE_REASON.fullmatch(value["reason"])
        or value.get("write_policy") != "NO_WRITE"
        or type(value.get("writes")) is not int
        or value.get("writes") != 0
        or type(value.get("receipt_verified")) is not bool
        or type(value.get("source_closure_verified")) is not bool
        or type(value.get("root_postverify_verified")) is not bool
        or any(value.get(key) is not None for key in _PARENT_ONLY_KEYS)
        or type(value.get("request_count")) is not int
        or type(value.get("query_callback_count")) is not int
        or type(value.get("snapshot_count")) is not int
        or type(value.get("write_invocation_count")) is not int
    ):
        return False
    if require_success:
        return (
            value.get("reason") == "candidate_root_handoff_written"
            and value.get("receipt_type") == "C01RootContentCustodyReceipt"
            and value.get("receipt_verified") is True
            and value.get("source_closure_verified") is True
            and value.get("root_postverify_verified") is True
            and value.get("request_count") == 8
            and 6 <= value.get("query_callback_count") <= 8
            and value.get("snapshot_count") == 2
            and value.get("write_invocation_count") == 0
        )
    if value.get("receipt_verified"):
        return value.get("receipt_type") == "C01RootContentCustodyReceipt"
    return value.get("receipt_type") is None


def _canonical_projection(raw: bytes) -> Optional[dict[str, Any]]:
    if type(raw) is not bytes or not raw or len(raw) > 64 * 1024:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
        canonical = json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except Exception:
        return None
    if canonical != raw:
        return None
    return value if type(value) is dict else None


def _validate_parent_driver_binding(
    parent_driver_module: Any,
    parent_driver_objects: Any,
) -> tuple[FunctionType, Any]:
    if (
        type(parent_driver_module) is not ModuleType
        or parent_driver_module.__name__ != _PARENT_DRIVER_MODULE_NAME
        or parent_driver_module.__dict__ is not vars(parent_driver_module)
        or type(parent_driver_objects) is not MappingProxyType
    ):
        raise ValueError("parent_driver_source_invalid")
    required = (
        "C01V20ParentProcessReceipt",
        "C01V20ParentProcessReceipt.__init__",
        "C01V20ParentProcessReceipt.__init__.__code__",
        "C01V20ParentProcessReceipt.__init__.__globals__",
        "create_c01_v20_parent_process_receipt",
        "create_c01_v20_parent_process_receipt.__code__",
        "create_c01_v20_parent_process_receipt.__globals__",
        "validate_c01_v20_parent_process_receipt",
        "validate_c01_v20_parent_process_receipt.__code__",
        "validate_c01_v20_parent_process_receipt.__globals__",
    )
    if any(key not in parent_driver_objects for key in required):
        raise ValueError("parent_driver_object_map_incomplete")
    receipt_type = parent_driver_objects["C01V20ParentProcessReceipt"]
    init = parent_driver_objects["C01V20ParentProcessReceipt.__init__"]
    creator = parent_driver_objects["create_c01_v20_parent_process_receipt"]
    validator = parent_driver_objects["validate_c01_v20_parent_process_receipt"]
    if (
        type(receipt_type) is not type
        or parent_driver_module.__dict__.get("C01V20ParentProcessReceipt") is not receipt_type
        or type(init) is not FunctionType
        or receipt_type.__dict__.get("__init__") is not init
        or init.__code__
        is not parent_driver_objects["C01V20ParentProcessReceipt.__init__.__code__"]
        or init.__globals__ is not parent_driver_module.__dict__
        or parent_driver_objects["C01V20ParentProcessReceipt.__init__.__globals__"]
        is not parent_driver_module.__dict__
        or type(creator) is not FunctionType
        or parent_driver_module.__dict__.get("create_c01_v20_parent_process_receipt") is not creator
        or creator.__code__
        is not parent_driver_objects["create_c01_v20_parent_process_receipt.__code__"]
        or creator.__globals__ is not parent_driver_module.__dict__
        or parent_driver_objects["create_c01_v20_parent_process_receipt.__globals__"]
        is not parent_driver_module.__dict__
        or type(validator) is not FunctionType
        or parent_driver_module.__dict__.get("validate_c01_v20_parent_process_receipt")
        is not validator
        or validator.__code__
        is not parent_driver_objects["validate_c01_v20_parent_process_receipt.__code__"]
        or validator.__globals__ is not parent_driver_module.__dict__
        or parent_driver_objects["validate_c01_v20_parent_process_receipt.__globals__"]
        is not parent_driver_module.__dict__
    ):
        raise ValueError("parent_driver_source_binding_invalid")
    return validator, receipt_type


def create_c01_v20_wrapper_call_receipt(
    projection_raw: bytes,
    frame: Any,
    parent_process_receipt: Any,
    *,
    parent_driver_module: ModuleType,
    parent_driver_objects: Mapping[str, Any],
) -> C01V20WrapperCallReceipt:
    """Bind one canonical candidate projection to the parent's typed call."""

    if type(projection_raw) is not bytes:
        raise ValueError("candidate_projection_invalid")
    projection = _canonical_projection(projection_raw)
    if projection is None or not _validate_candidate_projection(projection, require_success=True):
        raise ValueError("candidate_projection_invalid")
    validator, receipt_type = _validate_parent_driver_binding(
        parent_driver_module, parent_driver_objects
    )
    if (
        type(parent_process_receipt) is not receipt_type
        or type(getattr(parent_process_receipt, "child_pid", None)) is not int
        or parent_process_receipt.child_pid <= 0
        or type(getattr(parent_process_receipt, "call_nonce", None)) is not object
        or parent_process_receipt.stdout_raw is not projection_raw
        or parent_process_receipt.frame is not frame
        or validator(parent_process_receipt) is not True
    ):
        raise ValueError("parent_process_receipt_invalid")
    receipt = C01V20WrapperCallReceipt(
        projection_raw,
        frame,
        parent_process_receipt,
        parent_process_receipt.child_pid,
        parent_process_receipt.call_nonce,
        parent_driver_module,
        parent_driver_objects,
        _factory=_WRAPPER_CALL_FACTORY,
    )
    if validate_c01_v20_wrapper_call_receipt(receipt) is not True:
        raise ValueError("wrapper_call_receipt_postcheck_failed")
    return receipt


def validate_c01_v20_wrapper_call_receipt(receipt: Any) -> bool:
    """Revalidate candidate bytes, frame identity, source binding, and parent call."""

    try:
        if (
            type(receipt) is not C01V20WrapperCallReceipt
            or receipt._factory is not _WRAPPER_CALL_FACTORY
            or type(receipt.projection_raw) is not bytes
            or type(receipt.child_pid) is not int
            or receipt.child_pid <= 0
        ):
            return False
        projection = _canonical_projection(receipt.projection_raw)
        if projection is None or not _validate_candidate_projection(
            projection, require_success=True
        ):
            return False
        validator, receipt_type = _validate_parent_driver_binding(
            receipt.parent_driver_module, receipt.parent_driver_objects
        )
        process_receipt = receipt.parent_process_receipt
        return (
            type(process_receipt) is receipt_type
            and process_receipt.child_pid == receipt.child_pid
            and type(receipt.call_nonce) is object
            and process_receipt.call_nonce is receipt.call_nonce
            and process_receipt.stdout_raw is receipt.projection_raw
            and process_receipt.frame is receipt.frame
            and validator(process_receipt) is True
        )
    except Exception:
        return False


def _invoke_with_bootstrap_stream(
    stream: io.FileIO,
    wrapper_module: ModuleType,
    wrapper_raw: bytes,
) -> dict[str, Any]:
    """Run the child-local V20/RootSeal chain under the fixed source scope."""

    root = Path("D:/source_code/backtrader")
    if not root.is_absolute():
        raise C01V20ChildActivationError("repository_root_invalid")
    front_raw = _read_public_source(
        root, _FRONT_PATH, expected_sha256=_ROOT_STATIC_SOURCE_PINS[_FRONT_PATH]
    )
    front_module = _load_module_from_bytes(root, _FRONT_PATH, _FRONT_MODULE_NAME, front_raw)
    runner_raw = _read_public_source(
        root,
        _RUNNER_PATH,
        maximum=_MAX_SMALL_SOURCE_BYTES,
        expected_sha256=_ROOT_STATIC_SOURCE_PINS[_RUNNER_PATH],
    )
    runner_module = _load_module_from_bytes(root, _RUNNER_PATH, _RUNNER_MODULE_NAME, runner_raw)

    context_function = front_module.__dict__.get("verified_c01_v20_sources")
    if (
        type(context_function) is not FunctionType
        or context_function.__globals__ is not front_module.__dict__
        or _sha256(front_raw) != front_module.__dict__.get("__c01_source_sha256__")
    ):
        raise C01V20ChildActivationError("v20_front_source_invalid")
    try:
        bundle_context = context_function(root)
        bundle = bundle_context.__enter__()
    except Exception:
        raise C01V20ChildActivationError("v20_source_bundle_unavailable") from None
    scope = None
    try:
        issuer = bundle.issuer
        owner = bundle.owner
        helpers = bundle.helpers
        helper_sources = owner._read_source_bundle(root)
        scope = _fixed_root_scope(
            root=root,
            wrapper_module=wrapper_module,
            wrapper_raw=wrapper_raw,
            front_module=front_module,
            front_raw=front_raw,
            runner_module=runner_module,
            runner_raw=runner_raw,
            bundle=bundle,
            helpers_source=helper_sources,
        )
        channel_receipt = wrapper_module.C01V20FrameChannelReceipt(
            scope,
            stream,
            _factory=wrapper_module._C01_V20_FRAME_CHANNEL_FACTORY,
        )
        verify = scope.root_module.__dict__.get("verify_namespace_freshness_receipt")
        if verify(scope, scope.namespace_freshness_receipt) is not True:
            raise C01V20ChildActivationError("root_source_closure_unverified")
        invoke = _captured_function(scope, _RUNNER_PATH, "invoke_v20_issuer")
        issuer_result = invoke(issuer, scope, owner, helpers)
        if (
            type(issuer_result) is not issuer.__dict__.get("C01NativeTdReadV20Result")
            or getattr(issuer_result, "status", None) != "PASS"
            or getattr(issuer_result, "reason", None) != "read_only_candidate_complete"
            or scope.issuer_returned is not False
            or scope.stage_count != 1
            or scope.root_content_stage is None
        ):
            raise C01V20ChildActivationError("candidate_content_incomplete")
        stage = scope.root_content_stage
        issue_pending = _captured_function(scope, _ROOT_PATH, "issue_c01_candidate_pending_result")
        pending = issue_pending(scope, issuer_result)
        custody_module = scope.root_custody_module
        issue_custody = _captured_function(
            scope, _CUSTODY_PATH, "issue_c01_root_content_custody_receipt"
        )
        custody_receipt = issue_custody(scope, pending, stage, stage.candidate_refs[2])
        validate_custody = _captured_function(
            scope, _CUSTODY_PATH, "validate_c01_root_content_custody_receipt"
        )
        if validate_custody(custody_receipt, scope, pending, stage) is not True:
            raise C01V20ChildActivationError("child_custody_receipt_invalid")
        mint_seal = _captured_function(scope, _HANDOFF_PATH, "mint_c01_root_content_seal")
        seal = mint_seal(
            root_module=scope.root_module,
            custody_module=custody_module,
            stage=stage,
            pending=pending,
            custody_receipt=custody_receipt,
        )
        if (
            scope.root_content_seal is not seal
            or seal.stage is not stage
            or seal.custody_receipt is not custody_receipt
            or seal._used is not False
        ):
            raise C01V20ChildActivationError("child_rootseal_postcheck_failed")
        create_writer = _captured_function(
            scope, _ROOT_PATH, "create_c01_root_content_frame_writer"
        )
        writer = create_writer(scope, channel_receipt)
        write_frame = _captured_function(scope, _HANDOFF_PATH, "write_c01_root_content_frame")
        frame_bytes = seal._frame
        if type(frame_bytes) is not bytes or not 1 <= len(frame_bytes) <= _MAX_FRAME_BYTES:
            raise C01V20ChildActivationError("child_content_frame_size_invalid")
        write_frame(seal, writer)
        if (
            scope.content_frame_sent is not True
            or scope.consumed is not True
            or writer._used is not True
            or seal._used is not True
            or channel_receipt.used is not True
        ):
            raise C01V20ChildActivationError("child_content_frame_postcheck_failed")
        try:
            stream.flush()
            stream.close()
        except Exception:
            raise C01V20ChildActivationError("child_content_frame_close_failed") from None
        close_scope = _captured_function(scope, _ROOT_PATH, "close_c01_root_invocation_scope")
        close_scope(scope)
        if scope.active is not False:
            raise C01V20ChildActivationError("root_scope_close_unverified")
        verify_after = _captured_function(scope, _ROOT_PATH, "verify_namespace_freshness_receipt")
        if verify_after(scope, scope.namespace_freshness_receipt) is not True:
            raise C01V20ChildActivationError("root_postverify_unverified")
        counts = _validate_content_summary(stage.validated_content)
        projection = _child_projection(
            reason="candidate_root_handoff_written",
            receipt_verified=True,
            source_closure_verified=True,
            root_postverify_verified=True,
            counts=counts,
        )
    except BaseException as error:
        try:
            bundle_context.__exit__(type(error), error, error.__traceback__)
        except Exception:
            pass
        raise
    else:
        try:
            bundle_context.__exit__(None, None, None)
        except Exception:
            raise C01V20ChildActivationError("child_source_lease_close_failed") from None
    return projection


def invoke_c01_v20_activation() -> dict[str, Any]:
    """No-argument fixed child entry.  The caller cannot supply a channel."""

    stream = _consume_bootstrap_stream()
    try:
        root = Path("D:/source_code/backtrader")
        wrapper_module, wrapper_raw = _load_wrapper_module(root)
        sink = _DiscardingTextSink()
        with redirect_stdout(sink), redirect_stderr(sink):
            invoke = wrapper_module.__dict__.get("_invoke_with_bootstrap_stream")
            if (
                type(invoke) is not FunctionType
                or invoke.__globals__ is not wrapper_module.__dict__
            ):
                raise C01V20ChildActivationError("wrapper_source_binding_invalid")
            return invoke(stream, wrapper_module, wrapper_raw)
    except Exception:
        try:
            stream.close()
        except Exception:
            pass
        raise
    finally:
        if hasattr(sys, _BOOTSTRAP_CONSUMED_ATTR):
            try:
                delattr(sys, _BOOTSTRAP_CONSUMED_ATTR)
            except Exception:
                pass


def _emit_candidate_projection(projection: Mapping[str, Any]) -> None:
    if not _validate_candidate_projection(dict(projection), require_success=False):
        projection = _child_projection(
            reason="child_projection_invalid",
            receipt_verified=False,
            source_closure_verified=False,
            root_postverify_verified=False,
        )
    raw = json.dumps(
        dict(projection), ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        raise SystemExit(2)
    stream.write(raw)
    stream.flush()


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the fixed no-user-argument child route and emit one JSON frame."""

    expected_argv = [str(Path("D:/source_code/backtrader") / Path(_WRAPPER_PATH))]
    if argv is not None or sys.argv != expected_argv:
        _emit_candidate_projection(
            _child_projection(
                reason="fixed_child_bootstrap_required",
                receipt_verified=False,
                source_closure_verified=False,
                root_postverify_verified=False,
            )
        )
        return 2
    try:
        projection = invoke_c01_v20_activation()
        _emit_candidate_projection(projection)
        return 0
    except C01V20ChildActivationError:
        _emit_candidate_projection(
            _child_projection(
                reason="child_root_handoff_blocked",
                receipt_verified=False,
                source_closure_verified=False,
                root_postverify_verified=False,
            )
        )
        return 2
    except Exception:
        _emit_candidate_projection(
            _child_projection(
                reason="child_root_handoff_blocked",
                receipt_verified=False,
                source_closure_verified=False,
                root_postverify_verified=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "C01V20FrameChannelReceipt",
    "C01V20WrapperCallReceipt",
    "create_c01_v20_wrapper_call_receipt",
    "invoke_c01_v20_activation",
    "main",
    "validate_c01_v20_wrapper_call_receipt",
]
