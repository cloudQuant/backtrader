"""Current-invocation local issuer for the SimNow C01 V3 TD read profile.

Importing this module is inert. The fixed operation accepts no caller
credentials, endpoints, receipts, artifacts, or eligibility claims. It uses
only the fixed case profile to begin one bounded local read-only invocation.
Every eligible result is recomputed from the current worker, Job, and private
artifact evidence under this profile's source-pinned closure.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import importlib.machinery
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from types import MappingProxyType, ModuleType
from typing import Any, List, Mapping, Sequence, Tuple


PROFILE_ID = "C01_NATIVE_TD_READ_V3"
CASE_ID = "C01"
MAX_RUN_SECONDS = 90.0
MAX_CLEANUP_SECONDS = 5.0
MAX_PAIR_SELECTION_SECONDS = 30.0
MAX_POST_RUN_VALIDATION_SECONDS = 5.0
MAX_PROFILE_SECONDS = 150.0
MAX_PROJECTION_BYTES = 8192
MAX_CONFIG_BYTES = 256 * 1024
MAX_PRIVATE_AUDIT_BYTES = 4 * 1024 * 1024
MAX_WORKER_PROGRESS_RECORDS = 128
MAX_WORKER_PROGRESS_RECORD_BYTES = 4096
MAX_WORKER_PROGRESS_TOTAL_BYTES = 512 * 1024
_DIAGNOSTIC_INTENTS_ONLY = False
# Local source pins are reviewed identifiers, not an external signing root.
# The exact worker source, SDK RECORDs, and native payload are then checked by
# the frozen worker before it imports any SDK/native module.
_OWNER_SHA256 = "745c468247751068f5dd50d21ce988c61394c218a77350e78d9d26b6c1d54d2a"
_CASE_CONTRACT_SHA256 = "33d60824f780784f0c391a8212816c6167dd7485dec5b9fc0b461b28e6b4adca"
_CASE_STRATEGY_SHA256 = "c88501fda1ce83cebb334b58566776bee5154a5cfea1c5cc22d717a2e09d3f17"
_ENVREF_TEMPLATE_SHA256 = "debc71d75b4e04c4e64c38750cdfa2101dc69585ef7898a290c721d882f51db2"
_WORKER_SHA256 = "9a24ef954a4e192ae2879e657613ff5ca7b1cdf5d7ee116d9e28fbef9d70ce91"
_PROTOCOL_SHA256 = "fa1028021a903fdc5602caf1e7375c6f4eb76e46ffbb819ea057b97ef048fc88"
_CONTRACT_SHA256 = "3892af9a87ab424ceea896f9ebcbc1608515ead5e9d5c89a21ea823ff32de20c"
_SUPERVISOR_SHA256 = "4975fbdf8fbe8c7174a92f9f26069b65bbfac0021666fb6bcb6577819a340555"
_DEPENDENCY_MANIFEST_SHA256 = "7cb851df481066ee7622aea0bdd87863d6e04d3372fb520e7685a241411f2324"
_PRIVATE_HELPER_SHA256 = "b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd"
_R3_CLI_HELPER_SHA256 = "62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76"
_SOURCE_MANIFEST_PATH = "backtrader_runtime/certification_simnow_c01_native_td_read_v3.sources.json"
_SOURCE_MANIFEST_SHA256 = "7da8735cea74f4eafbd43fe0ed94d08232f8f20b9814cad0d682281c89eb116a"
_ADMISSION_SCHEMA_PATH = (
    "backtrader_runtime/certification_simnow_c01_native_td_read_v3.admission.schema.json"
)
_ADMISSION_SCHEMA_SHA256 = "3b3a3c4d9ef2895a6fef4167a32e528b100579b74a373f70576460b26e0c2f14"
_INTERPRETER_BINDING_SHA256 = "a38d00ecfbc7a777edab4b9d090be49ef03a94e7c23340dfe95366bacfd05494"
_INTERPRETER_BINDING_PATH = "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py"
_INTERPRETER_BINDING_MODULE_NAME = "_c01_pinned_interpreter_binding"
_CONFIG_RELATIVE = "examples/000_live_certification/simnow_penetration/config.yaml"
_CASE_RUNNER_RELATIVE = "examples/000_live_certification/simnow_penetration/cases/C01/run_v3.py"
_ADMISSION_BOUND_SOURCE_PATHS = (
    "backtrader_runtime/certification_simnow_c01_native_td_read_v3.py",
    _CASE_RUNNER_RELATIVE,
)
_ADMISSION_ROOT_NAME = "simnow-c01-native-td-read-v3"
_ADMISSION_COLLECTION_NAME = "admissions"
_ADMISSION_CLAIM_NAME = "claimed"
_ADMISSION_SCHEMA = "simnow.c01.native_td_read_v3.admission.v1"
_CONSUMED_SCHEMA = "simnow.c01.native_td_read_v3.consumed.v1"
_CLAIM_SCHEMA = "simnow.c01.native_td_read_v3.claim.v1"
_ADMISSION_MAX_BYTES = 16 * 1024
_ADMISSION_MAX_ENTRIES = 128
_ADMISSION_MAX_TTL_SECONDS = 600
_ADMISSION_DIRECTORY_ACCESS = 0x80020080  # GENERIC_READ | READ_CONTROL | FILE_READ_ATTRIBUTES
_ADMISSION_ID_RE = re.compile(r"[0-9a-f]{32}\Z")
_ADMISSION_TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
_ENV_NAMES = frozenset(
    {
        "SIMNOW_USER_ID",
        "SIMNOW_PASSWORD",
        "CTP_BROKER_ID",
        "CTP_APP_ID",
        "CTP_AUTH_CODE",
    }
)
_AMBIENT_SECRET_AND_FRONT_NAMES = frozenset(
    {
        "SIMNOW_USER_ID",
        "SIMNOW_PASSWORD",
        "CTP_BROKER_ID",
        "CTP_APP_ID",
        "CTP_AUTH_CODE",
        "CTP_MD_FRONT",
        "CTP_TD_FRONT",
    }
)
_FIELD_ENV_NAMES = {
    "broker_id": "CTP_BROKER_ID",
    "user_id": "SIMNOW_USER_ID",
    "password": "SIMNOW_PASSWORD",
    "app_id": "CTP_APP_ID",
    "auth_code": "CTP_AUTH_CODE",
}
_ENV_VALUE_MAX_BYTES = {
    "broker_id": 10,
    "user_id": 15,
    "password": 40,
    "app_id": 32,
    "auth_code": 16,
}
_SAFE_REASON = re.compile(r"[a-z0-9_:-]{1,96}\Z")
_FRESH_PAIR_HANDOFF_FAILURES = MappingProxyType(
    {
        "no_current_transport_candidate": "fresh_pair_no_transport_candidate",
        "current_transport_observation_unavailable": "fresh_pair_probe_unavailable",
        "current_transport_observation_invalid": "fresh_pair_probe_invalid",
        "current_transport_observation_expired": "fresh_pair_probe_invalid",
        "current_transport_pair_binding_invalid": "fresh_pair_handoff_rejected",
        "transport_handoff_expired": "fresh_pair_handoff_rejected",
        "transport_handoff_custody_mismatch": "fresh_pair_handoff_rejected",
        "transport_handoff_projection_mismatch": "fresh_pair_handoff_rejected",
        "transport_handoff_already_consumed": "fresh_pair_handoff_rejected",
        "transport_handoff_clock_invalid": "fresh_pair_handoff_rejected",
    }
)
_FRESH_PAIR_SELECTION_SOURCE = "scripts.ctp_000_front_handoff.SelectedFrontPair"
_RESULT_FACTORY = object()
_OWNER_MODULE_NAME = "backtrader_runtime._c01_native_td_read_v3_owner"
_ISSUER_LOCK = threading.Lock()
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_PROFILE_CONTRACT = {
    "profile_id": PROFILE_ID,
    "case_id": CASE_ID,
    "scope": "td_auth_login_account_read_only",
    "requests": [
        "authenticate",
        "login",
        "baseline_orders",
        "baseline_positions",
        "baseline_funds",
        "final_orders",
        "final_positions",
        "final_funds",
    ],
    "native_stop_required": True,
    "native_join_required": False,
    "native_lifecycle_mode": "NO_JOIN_RELEASE_RETURNED",
    "md_sdk_session": False,
    "front_transport_probe_candidates": 5,
    "order_insert_requests": 0,
    "order_cancel_requests": 0,
    "diagnostic_intents_only": _DIAGNOSTIC_INTENTS_ONLY,
    "case_receipt_authority": "none",
}
PROFILE_CONTRACT_SHA256 = hashlib.sha256(
    json.dumps(
        _PROFILE_CONTRACT,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
).hexdigest()


def _verify_source_manifest(root: Path, owner: ModuleType) -> None:
    raw = _read_fixed_source(root, _SOURCE_MANIFEST_PATH, _SOURCE_MANIFEST_SHA256)
    try:
        manifest = json.loads(raw.decode("ascii"), object_pairs_hook=_strict_object)
    except Exception:
        raise _IssuerError("source_manifest_invalid") from None
    if type(manifest) is not dict or set(manifest) != {
        "schema",
        "profile_id",
        "source_files",
        "admission_bound_files",
    }:
        raise _IssuerError("source_manifest_invalid")
    expected_files = dict(owner._SOURCE_PINS)
    expected_files.update(
        {
            "backtrader_runtime/certification_simnow_c01_v3_owner.py": _OWNER_SHA256,
            "examples/000_live_certification/simnow_penetration/case_contracts/C01.yaml": (
                _CASE_CONTRACT_SHA256
            ),
            "examples/000_live_certification/simnow_penetration/cases/C01/C01_strategy.py": (
                _CASE_STRATEGY_SHA256
            ),
            "examples/000_live_certification/simnow_penetration/config.private.yaml.template": (
                _ENVREF_TEMPLATE_SHA256
            ),
            _ADMISSION_SCHEMA_PATH: _ADMISSION_SCHEMA_SHA256,
        }
    )
    if (
        manifest.get("schema") != "simnow.c01.native_td_read_v3.source_manifest.v1"
        or manifest.get("profile_id") != PROFILE_ID
        or type(manifest.get("source_files")) is not dict
        or manifest["source_files"] != expected_files
        or manifest.get("admission_bound_files") != list(_ADMISSION_BOUND_SOURCE_PATHS)
    ):
        raise _IssuerError("source_manifest_mismatch")


class _IssuerError(ValueError):
    """Fixed local failure categories only; never carries private values."""


@dataclass(frozen=True, init=False)
class C01NativeTdReadV3Result:
    status: str
    reason: str
    profile: str = PROFILE_ID
    case_id: str = CASE_ID
    writes: int = 0

    def __init__(
        self,
        status: str,
        reason: str,
        profile: str = PROFILE_ID,
        case_id: str = CASE_ID,
        writes: int = 0,
        *,
        _factory: Any = None,
    ) -> None:
        if _factory is not _RESULT_FACTORY:
            raise ValueError("c01_native_td_result_factory_required")
        if (
            status not in {"PASS", "BLOCKED"}
            or profile != PROFILE_ID
            or case_id != CASE_ID
            or writes != 0
            or type(reason) is not str
            or not _SAFE_REASON.fullmatch(reason)
        ):
            raise ValueError("c01_native_td_result_invalid")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "profile", profile)
        object.__setattr__(self, "case_id", case_id)
        object.__setattr__(self, "writes", writes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": CASE_ID,
            "certification": self.status,
            "mode": PROFILE_ID,
            "profile": PROFILE_ID,
            "reason": self.reason,
            "write_policy": "NO_WRITE",
            "writes": 0,
        }


def _blocked(reason: str) -> C01NativeTdReadV3Result:
    safe_reason = (
        reason
        if type(reason) is str and _SAFE_REASON.fullmatch(reason)
        else "issuer_internal_error"
    )
    return C01NativeTdReadV3Result("BLOCKED", safe_reason, _factory=_RESULT_FACTORY)


def _repo_root() -> Path:
    try:
        root = Path(__file__).resolve(strict=True).parents[1]
    except Exception:
        raise _IssuerError("issuer_source_unavailable") from None
    if not root.is_absolute() or not root.is_dir():
        raise _IssuerError("issuer_source_unavailable")
    return root


def _read_fixed_source(root: Path, relative: str, expected_sha256: str) -> bytes:
    path = root / Path(relative)
    try:
        info = path.lstat()
        attributes = getattr(info, "st_file_attributes", 0)
        if path.is_symlink() or attributes & 0x400 or not path.is_file():
            raise _IssuerError("pinned_source_not_regular")
        if info.st_size > 8 * 1024 * 1024:
            raise _IssuerError("pinned_source_size_invalid")
        with path.open("rb") as stream:
            raw = stream.read(8 * 1024 * 1024 + 1)
    except _IssuerError:
        raise
    except Exception:
        raise _IssuerError("pinned_source_unavailable") from None
    if len(raw) > 8 * 1024 * 1024:
        raise _IssuerError("pinned_source_size_invalid")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise _IssuerError("pinned_source_digest_mismatch")
    return raw


def _verify_public_profile_sources(root: Path) -> None:
    _read_fixed_source(root, _INTERPRETER_BINDING_PATH, _INTERPRETER_BINDING_SHA256)
    _read_fixed_source(
        root,
        "examples/000_live_certification/simnow_penetration/case_contracts/C01.yaml",
        _CASE_CONTRACT_SHA256,
    )
    _read_fixed_source(
        root,
        "examples/000_live_certification/simnow_penetration/cases/C01/C01_strategy.py",
        _CASE_STRATEGY_SHA256,
    )
    _read_fixed_source(
        root,
        "examples/000_live_certification/simnow_penetration/config.private.yaml.template",
        _ENVREF_TEMPLATE_SHA256,
    )
    _read_fixed_source(root, _ADMISSION_SCHEMA_PATH, _ADMISSION_SCHEMA_SHA256)


def _load_frozen_owner(root: Path) -> ModuleType:
    raw = _read_fixed_source(
        root,
        "backtrader_runtime/certification_simnow_c01_v3_owner.py",
        _OWNER_SHA256,
    )
    name = _OWNER_MODULE_NAME
    if name in sys.modules:
        raise _IssuerError("owner_module_already_loaded")
    module = ModuleType(name)
    module.__file__ = str(root / "backtrader_runtime" / "certification_simnow_c01_v3_owner.py")
    module.__package__ = "backtrader_runtime"
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None)
    sys.modules[name] = module
    try:
        exec(compile(raw, module.__file__, "exec", dont_inherit=True), module.__dict__)
    except Exception:
        sys.modules.pop(name, None)
        raise _IssuerError("owner_source_compile_failed") from None
    return module


def _consumer_matches() -> bool:
    module = None
    try:
        root = _repo_root()
        raw = _read_fixed_source(root, _INTERPRETER_BINDING_PATH, _INTERPRETER_BINDING_SHA256)
        if _INTERPRETER_BINDING_MODULE_NAME in sys.modules:
            return False
        module = ModuleType(_INTERPRETER_BINDING_MODULE_NAME)
        module.__file__ = str(root / Path(_INTERPRETER_BINDING_PATH))
        module.__package__ = ""
        sys.modules[_INTERPRETER_BINDING_MODULE_NAME] = module
        exec(compile(raw, module.__file__, "exec", dont_inherit=True), module.__dict__)
        return module.verify_current_runtime() is True
    except Exception:
        return False
    finally:
        if module is not None and sys.modules.get(_INTERPRETER_BINDING_MODULE_NAME) is module:
            sys.modules.pop(_INTERPRETER_BINDING_MODULE_NAME, None)


def _strict_object(pairs: List[Tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _IssuerError("private_config_duplicate_key")
        result[key] = value
    return result


def _strict_source_object(pairs: List[Tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _IssuerError("admission_duplicate_key")
        result[key] = value
    return result


@dataclass(frozen=True, repr=False)
class _C01V3Admission:
    admission_id: str
    not_before_utc: datetime
    expires_at_utc: datetime
    bindings: Mapping[str, str]
    admission_sha256: str = ""
    claim_sha256: str = ""
    consumed_sha256: str = ""

    def __repr__(self) -> str:
        return "_C01V3Admission(<private one-shot registration>)"

    def active(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        return self.not_before_utc <= current <= self.expires_at_utc


def _required_admission_bindings(
    *, issuer_source_sha256: str, case_runner_source_sha256: str
) -> dict[str, str]:
    return {
        "case_runner_source_sha256": case_runner_source_sha256,
        "issuer_source_sha256": issuer_source_sha256,
        "source_manifest_sha256": _SOURCE_MANIFEST_SHA256,
        "profile_contract_sha256": PROFILE_CONTRACT_SHA256,
        "owner_source_sha256": _OWNER_SHA256,
        "worker_source_sha256": _WORKER_SHA256,
        "protocol_source_sha256": _PROTOCOL_SHA256,
        "contract_source_sha256": _CONTRACT_SHA256,
        "supervisor_source_sha256": _SUPERVISOR_SHA256,
        "sdk_dependency_manifest_sha256": _DEPENDENCY_MANIFEST_SHA256,
        "interpreter_binding_source_sha256": _INTERPRETER_BINDING_SHA256,
        "case_contract_sha256": _CASE_CONTRACT_SHA256,
        "case_strategy_sha256": _CASE_STRATEGY_SHA256,
        "envref_template_sha256": _ENVREF_TEMPLATE_SHA256,
    }


def _parse_profile_admission(
    raw: bytes,
    *,
    expected_bindings: Mapping[str, str],
    now: datetime | None = None,
) -> _C01V3Admission:
    if type(raw) is not bytes or not 0 < len(raw) <= _ADMISSION_MAX_BYTES:
        raise _IssuerError("admission_size_invalid")
    try:
        value = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=_strict_source_object,
            parse_constant=lambda _item: (_ for _ in ()).throw(
                _IssuerError("admission_nonfinite_number")
            ),
        )
    except _IssuerError:
        raise
    except Exception:
        raise _IssuerError("admission_invalid") from None
    try:
        canonical = (
            json.dumps(
                value,
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("ascii")
    except Exception:
        raise _IssuerError("admission_invalid") from None
    if canonical != raw:
        raise _IssuerError("admission_not_canonical")
    scope = {
        "role": "READ_ONLY_NATIVE_TD_NO_JOIN",
        "case_id": CASE_ID,
        "environment": "simulation",
        "operation_scope": "TD_AUTH_LOGIN_ORDERS_POSITIONS_FUNDS_BASELINE_FINAL",
        "front_transport_probe": True,
        "max_front_pair_candidates": 5,
        "md_sdk_session": False,
        "market_data_subscribe": False,
        "native_join": False,
        "order_insert": False,
        "order_cancel": False,
        "max_order_insert_requests": 0,
        "max_order_cancel_requests": 0,
    }
    if type(value) is not dict or set(value) != {
        "schema",
        "profile_id",
        "case_id",
        "admission_id",
        "status",
        "not_before_utc",
        "expires_at_utc",
        "scope",
        "bindings",
    }:
        raise _IssuerError("admission_schema_invalid")
    if (
        value["schema"] != _ADMISSION_SCHEMA
        or value["profile_id"] != PROFILE_ID
        or value["case_id"] != CASE_ID
        or type(value["admission_id"]) is not str
        or not _ADMISSION_ID_RE.fullmatch(value["admission_id"])
        or value["status"] != "ACTIVE"
        or type(value["scope"]) is not dict
        or set(value["scope"]) != set(scope)
        or any(
            type(value["scope"].get(key)) is not type(expected)
            or value["scope"].get(key) != expected
            for key, expected in scope.items()
        )
        or type(value["bindings"]) is not dict
        or any(
            type(digest) is not str or not _SHA256_RE.fullmatch(digest)
            for digest in value["bindings"].values()
        )
    ):
        raise _IssuerError("admission_binding_mismatch")
    dynamic_bindings = {
        "config_source_sha256",
        "account_scope_sha256",
        "credential_binding_sha256",
    }
    if set(value["bindings"]) != set(expected_bindings) | dynamic_bindings or any(
        value["bindings"].get(key) != expected for key, expected in expected_bindings.items()
    ):
        raise _IssuerError("admission_binding_mismatch")
    if (
        type(value["not_before_utc"]) is not str
        or not _ADMISSION_TIME_RE.fullmatch(value["not_before_utc"])
        or type(value["expires_at_utc"]) is not str
        or not _ADMISSION_TIME_RE.fullmatch(value["expires_at_utc"])
    ):
        raise _IssuerError("admission_time_invalid")
    try:
        not_before = datetime.strptime(value["not_before_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        expires_at = datetime.strptime(value["expires_at_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except Exception:
        raise _IssuerError("admission_time_invalid") from None
    current = now or datetime.now(timezone.utc)
    ttl = (expires_at - not_before).total_seconds()
    if ttl <= 0 or ttl > _ADMISSION_MAX_TTL_SECONDS:
        raise _IssuerError("admission_ttl_invalid")
    if current < not_before:
        raise _IssuerError("admission_not_yet_valid")
    if current > expires_at:
        raise _IssuerError("admission_expired")
    return _C01V3Admission(
        admission_id=value["admission_id"],
        not_before_utc=not_before,
        expires_at_utc=expires_at,
        bindings=MappingProxyType(dict(value["bindings"])),
        admission_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _load_admission_helpers(root: Path) -> tuple[ModuleType, ModuleType]:
    private_raw = _read_fixed_source(
        root,
        "backtrader_runtime/certification_roundtrip_private.py",
        _PRIVATE_HELPER_SHA256,
    )
    cli_raw = _read_fixed_source(
        root,
        "backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
        _R3_CLI_HELPER_SHA256,
    )
    modules = []
    for name, relative, raw in (
        (
            "_c01_v2_admission_private_helper",
            "backtrader_runtime/certification_roundtrip_private.py",
            private_raw,
        ),
        (
            "_c01_v2_admission_r3_cli_helper",
            "backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
            cli_raw,
        ),
    ):
        module = ModuleType(name)
        module.__file__ = str(root / Path(relative))
        module.__package__ = ""
        if name in sys.modules:
            raise _IssuerError("admission_helper_already_loaded")
        sys.modules[name] = module
        try:
            exec(compile(raw, module.__file__, "exec", dont_inherit=True), module.__dict__)
        except Exception:
            if sys.modules.get(name) is module:
                sys.modules.pop(name, None)
            raise _IssuerError("admission_helper_compile_failed") from None
        if sys.modules.get(name) is module:
            sys.modules.pop(name, None)
        modules.append(module)
    return modules[0], modules[1]


def _held_source_digest(
    path: Path,
    *,
    private: ModuleType,
    r3_cli: ModuleType,
    retained: ExitStack,
) -> str:
    api = private._api()
    try:
        retained.enter_context(r3_cli._credential_ancestor_locks(path, private))
        handle, _identity = retained.enter_context(r3_cli._locked_readonly_file(path, private, api))
        raw = r3_cli._read_bounded_handle(api, handle, 2 * 1024 * 1024)
    except Exception:
        raise _IssuerError("admission_source_lease_failed") from None
    return hashlib.sha256(raw).hexdigest()


def _bounded_namespace_children(path: Path, *, maximum: int, reason: str) -> tuple[Path, ...]:
    children = []
    try:
        for child in path.iterdir():
            if len(children) >= maximum:
                raise _IssuerError(reason)
            children.append(child)
    except _IssuerError:
        raise
    except Exception:
        raise _IssuerError(reason) from None
    return tuple(children)


@contextmanager
def _admission_directory_ancestor_locks(path: Path, private: ModuleType, api: Any):
    """Hold directory ancestors with read access and deny-delete sharing.

    The shared credential helper intentionally opens ancestors for metadata
    only. The V3 admission namespace needs a stronger held handle: GENERIC_READ
    is requested and the pinned private API keeps its fixed share mask at
    FILE_SHARE_READ | FILE_SHARE_WRITE (without FILE_SHARE_DELETE). Keep this
    route-owned so the shared helper's other callers are unchanged.
    """

    path = private._path(Path(path))
    with ExitStack() as stack:
        for ancestor in reversed(path.parents):
            stack.enter_context(
                api.opened(
                    ancestor,
                    directory=True,
                    access=_ADMISSION_DIRECTORY_ACCESS,
                )
            )
        yield


def _open_admission_directory(api: Any, path: Path):
    return api.opened(
        path,
        directory=True,
        access=_ADMISSION_DIRECTORY_ACCESS,
    )


def _consumed_document(admission: _C01V3Admission, issuer_source_sha256: str) -> bytes:
    payload = {
        "schema": _CONSUMED_SCHEMA,
        "profile_id": PROFILE_ID,
        "case_id": CASE_ID,
        "admission_id": admission.admission_id,
        "issuer_source_sha256": issuer_source_sha256,
        "source_manifest_sha256": _SOURCE_MANIFEST_SHA256,
        "consumed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return json.dumps(
        payload, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def _claim_document(admission: _C01V3Admission, issuer_source_sha256: str) -> bytes:
    payload = {
        "schema": _CLAIM_SCHEMA,
        "profile_id": PROFILE_ID,
        "case_id": CASE_ID,
        "admission_id": admission.admission_id,
        "issuer_source_sha256": issuer_source_sha256,
        "source_manifest_sha256": _SOURCE_MANIFEST_SHA256,
        "claimed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return json.dumps(
        payload, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


@contextmanager
def _profile_admission_lease(root: Path, issuer_module: ModuleType):
    """Consume one current root-created registration before profile inputs load.

    Only the two fixed private-path helpers are compiled to read/lock the
    protected registration. The issuer, case runner, profile manifest, SDK,
    worker and interpreter binding must all match that registration before a
    durable CREATE_NEW consumed namespace is made.
    """

    private, r3_cli = _load_admission_helpers(root)
    modules = (private, r3_cli)
    if any(module.__name__ in sys.modules for module in modules):
        raise _IssuerError("admission_helper_already_loaded")
    for module in modules:
        sys.modules[module.__name__] = module
    source_stack = ExitStack()
    try:
        api = private._api()
        local_app_data = Path(r3_cli._known_local_app_data()).resolve(strict=True)
        user_profile_text = os.environ.get("USERPROFILE")
        if type(user_profile_text) is not str or not user_profile_text:
            raise _IssuerError("admission_user_profile_unavailable")
        user_profile = private._path(Path(user_profile_text))
        user_profile_resolved = user_profile.resolve(strict=True)
        if (
            not user_profile.is_absolute()
            or not user_profile.is_dir()
            or os.path.normcase(str(local_app_data.parents[1]))
            != os.path.normcase(str(user_profile_resolved))
        ):
            raise _IssuerError("admission_known_folder_mismatch")

        expected_issuer_path = private._path(
            root / "backtrader_runtime" / "certification_simnow_c01_native_td_read_v3.py"
        )
        issuer_path = private._path(Path(issuer_module.__file__).resolve(strict=True))
        if os.path.normcase(str(issuer_path)) != os.path.normcase(str(expected_issuer_path)):
            raise _IssuerError("admission_issuer_path_mismatch")
        expected_issuer = issuer_module.__dict__.get("__c01_source_sha256__", "")
        issuer_digest = _held_source_digest(
            issuer_path,
            private=private,
            r3_cli=r3_cli,
            retained=source_stack,
        )
        if (
            type(expected_issuer) is not str
            or not _SHA256_RE.fullmatch(expected_issuer)
            or issuer_digest != expected_issuer
        ):
            raise _IssuerError("admission_issuer_source_mismatch")
        runner_path = private._path(root / Path(_CASE_RUNNER_RELATIVE))
        runner_digest = _held_source_digest(
            runner_path,
            private=private,
            r3_cli=r3_cli,
            retained=source_stack,
        )
        expected_bindings = _required_admission_bindings(
            issuer_source_sha256=issuer_digest,
            case_runner_source_sha256=runner_digest,
        )

        root_dir = private._path(local_app_data / _ADMISSION_ROOT_NAME)
        collection_dir = private._path(root_dir / _ADMISSION_COLLECTION_NAME)
        sid = api.current_sid()
        with ExitStack() as stack:
            stack.enter_context(_admission_directory_ancestor_locks(collection_dir, private, api))
            root_handle = stack.enter_context(_open_admission_directory(api, root_dir))
            api.verify_acl(root_handle, sid, directory=True)
            collection_handle = stack.enter_context(_open_admission_directory(api, collection_dir))
            api.verify_acl(collection_handle, sid, directory=True)
            entries = _bounded_namespace_children(
                collection_dir,
                maximum=_ADMISSION_MAX_ENTRIES,
                reason="admission_namespace_limit",
            )
            if any(entry.name == _ADMISSION_CLAIM_NAME for entry in entries):
                raise _IssuerError("admission_profile_already_consumed")
            pending = []
            for entry in entries:
                if not _ADMISSION_ID_RE.fullmatch(entry.name):
                    raise _IssuerError("admission_namespace_invalid")
                entry = private._path(entry)
                directory_handle = stack.enter_context(_open_admission_directory(api, entry))
                api.verify_acl(directory_handle, sid, directory=True)
                contents = _bounded_namespace_children(
                    entry,
                    maximum=2,
                    reason="admission_namespace_invalid",
                )
                content_names = {item.name for item in contents}
                if content_names == {"admission.json"}:
                    pending.append((entry, directory_handle))
                elif content_names == {"admission.json", "consumed"}:
                    consumed = private._path(entry / "consumed")
                    consumed_handle = stack.enter_context(_open_admission_directory(api, consumed))
                    api.verify_acl(consumed_handle, sid, directory=True)
                    if {
                        item.name
                        for item in _bounded_namespace_children(
                            consumed,
                            maximum=1,
                            reason="admission_consumed_marker_invalid",
                        )
                    } != {"consumed.json"}:
                        raise _IssuerError("admission_consumed_marker_invalid")
                    marker_path = private._path(consumed / "consumed.json")
                    marker_handle, _marker_identity = stack.enter_context(
                        r3_cli._locked_readonly_file(marker_path, private, api)
                    )
                    api.verify_acl(marker_handle, sid, directory=False)
                    marker_raw = r3_cli._read_bounded_handle(api, marker_handle, 4096)
                    try:
                        marker = json.loads(
                            marker_raw.decode("ascii"),
                            object_pairs_hook=_strict_source_object,
                        )
                    except Exception:
                        raise _IssuerError("admission_consumed_marker_invalid") from None
                    if (
                        type(marker) is not dict
                        or set(marker)
                        != {
                            "schema",
                            "profile_id",
                            "case_id",
                            "admission_id",
                            "issuer_source_sha256",
                            "source_manifest_sha256",
                            "consumed_at_utc",
                        }
                        or marker["schema"] != _CONSUMED_SCHEMA
                        or marker["profile_id"] != PROFILE_ID
                        or marker["case_id"] != CASE_ID
                        or marker["admission_id"] != entry.name
                        or marker["issuer_source_sha256"] != expected_issuer
                        or marker["source_manifest_sha256"] != _SOURCE_MANIFEST_SHA256
                        or type(marker["consumed_at_utc"]) is not str
                        or not _ADMISSION_TIME_RE.fullmatch(marker["consumed_at_utc"])
                    ):
                        raise _IssuerError("admission_consumed_marker_invalid")
                else:
                    raise _IssuerError("admission_namespace_invalid")
            if len(pending) != 1:
                raise _IssuerError(
                    "admission_unavailable" if not pending else "admission_ambiguous"
                )
            admission_dir, _admission_dir_handle = pending[0]
            admission_path = private._path(admission_dir / "admission.json")
            admission_context = r3_cli._locked_readonly_file(admission_path, private, api)
            admission_handle, _admission_identity = stack.enter_context(admission_context)
            api.verify_acl(admission_handle, sid, directory=False)
            raw_admission = r3_cli._read_bounded_handle(api, admission_handle, _ADMISSION_MAX_BYTES)
            admission = _parse_profile_admission(
                raw_admission,
                expected_bindings=expected_bindings,
            )
            if admission.admission_id != admission_dir.name:
                raise _IssuerError("admission_namespace_binding_mismatch")

            # A fixed CREATE_NEW profile claim prevents simultaneous use of
            # two separately prepared registration folders. It is persistent:
            # any failure after claiming requires a new source generation.
            claim_dir = private.create_private_directory(collection_dir / _ADMISSION_CLAIM_NAME)
            claim_path = private._path(claim_dir.path)
            claim_handle = stack.enter_context(_open_admission_directory(api, claim_path))
            api.verify_acl(claim_handle, sid, directory=True)
            claim_bytes = _claim_document(admission, issuer_digest)
            claim_dir.write_bytes("claim.json", claim_bytes)
            claim_file = private._path(claim_path / "claim.json")
            claim_file_handle, _claim_identity = stack.enter_context(
                r3_cli._locked_readonly_file(claim_file, private, api)
            )
            api.verify_acl(claim_file_handle, sid, directory=False)
            if r3_cli._read_bounded_handle(api, claim_file_handle, 4096) != claim_bytes:
                raise _IssuerError("admission_claim_marker_invalid")

            consumed_dir = private.create_private_directory(admission_dir / "consumed")
            consumed_path = private._path(consumed_dir.path)
            consumed_handle = stack.enter_context(_open_admission_directory(api, consumed_path))
            api.verify_acl(consumed_handle, sid, directory=True)
            marker_bytes = _consumed_document(admission, issuer_digest)
            consumed_dir.write_bytes("consumed.json", marker_bytes)
            marker_path = private._path(consumed_path / "consumed.json")
            marker_handle, _identity = stack.enter_context(
                r3_cli._locked_readonly_file(marker_path, private, api)
            )
            api.verify_acl(marker_handle, sid, directory=False)
            if r3_cli._read_bounded_handle(api, marker_handle, 4096) != marker_bytes:
                raise _IssuerError("admission_consumed_marker_invalid")
            admission = _C01V3Admission(
                admission_id=admission.admission_id,
                not_before_utc=admission.not_before_utc,
                expires_at_utc=admission.expires_at_utc,
                bindings=admission.bindings,
                admission_sha256=admission.admission_sha256,
                claim_sha256=hashlib.sha256(claim_bytes).hexdigest(),
                consumed_sha256=hashlib.sha256(marker_bytes).hexdigest(),
            )
            yield admission

            if not admission.active():
                raise _IssuerError("admission_expired_during_run")
            if (
                r3_cli._read_bounded_handle(api, admission_handle, _ADMISSION_MAX_BYTES)
                != raw_admission
            ):
                raise _IssuerError("admission_source_changed")
            if r3_cli._read_bounded_handle(api, marker_handle, 4096) != marker_bytes:
                raise _IssuerError("admission_consumed_marker_changed")
            if r3_cli._read_bounded_handle(api, claim_file_handle, 4096) != claim_bytes:
                raise _IssuerError("admission_claim_marker_changed")
            if {
                item.name
                for item in _bounded_namespace_children(
                    admission_dir,
                    maximum=2,
                    reason="admission_namespace_changed",
                )
            } != {
                "admission.json",
                "consumed",
            } or {
                item.name
                for item in _bounded_namespace_children(
                    consumed_path,
                    maximum=1,
                    reason="admission_namespace_changed",
                )
            } != {
                "consumed.json"
            }:
                raise _IssuerError("admission_namespace_changed")
            if {
                item.name
                for item in _bounded_namespace_children(
                    claim_path,
                    maximum=1,
                    reason="admission_claim_namespace_changed",
                )
            } != {"claim.json"}:
                raise _IssuerError("admission_claim_namespace_changed")
    except _IssuerError:
        raise
    except Exception:
        raise _IssuerError("admission_lease_failed") from None
    finally:
        close_failed = False
        try:
            source_stack.close()
        except Exception:
            close_failed = True
        for module in modules:
            if sys.modules.get(module.__name__) is module:
                sys.modules.pop(module.__name__, None)
        if close_failed:
            raise _IssuerError("admission_source_handle_close_failed") from None


def _parse_private_config(raw: bytes, selector: Any) -> Tuple[dict[str, str], ...]:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_CONFIG_BYTES:
        raise _IssuerError("private_config_size_invalid")
    try:
        text = raw.decode("ascii")
        value = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=lambda _item: (_ for _ in ()).throw(
                _IssuerError("private_config_nonfinite_number")
            ),
        )
    except _IssuerError:
        raise
    except Exception:
        raise _IssuerError("private_config_invalid") from None
    if type(value) is not dict or set(value) != {
        "config_schema_version",
        "strategy",
        "runtime",
        "parameters",
        "secrets_ref",
        "ctp",
    }:
        raise _IssuerError("private_config_schema_invalid")
    if (
        type(value["config_schema_version"]) is not int
        or value["config_schema_version"] != 4
        or value["strategy"] != {"id": "example.000_live_certification.simnow_penetration"}
        or value["runtime"] != {"mode": "simulation", "preset": "sandbox"}
        or value["parameters"] != {}
        or value["secrets_ref"] != "config_yaml"
    ):
        raise _IssuerError("private_config_scope_invalid")
    try:
        canonical = (
            json.dumps(
                value,
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("ascii")
    except Exception:
        raise _IssuerError("private_config_not_canonical") from None
    if canonical != raw:
        raise _IssuerError("private_config_not_canonical")
    ctp = value["ctp"]
    if type(ctp) is not dict or set(ctp) != {
        "front_pairs",
        "instrument_id",
        "exchange_id",
        "hedge_flag",
        "broker_id",
        "user_id",
        "password",
        "app_id",
        "auth_code",
    }:
        raise _IssuerError("private_config_ctp_shape_invalid")
    pairs = ctp["front_pairs"]
    if type(pairs) is not list or len(pairs) != 5:
        raise _IssuerError("configured_front_pair_count_invalid")
    normalized: List[dict[str, str]] = []
    for pair in pairs:
        if (
            type(pair) is not dict
            or set(pair) != {"md_front", "td_front"}
            or type(pair.get("md_front")) is not str
            or type(pair.get("td_front")) is not str
            or not pair["md_front"].isascii()
            or not pair["td_front"].isascii()
        ):
            raise _IssuerError("configured_front_pair_invalid")
        normalized.append({"md_front": pair["md_front"], "td_front": pair["td_front"]})
    try:
        selector.validate_document(
            {
                "schema": selector.SCHEMA,
                "venue": "simnow",
                "scope": "transport_only",
                "strategy_id": selector.STRATEGY,
                "front_pairs": normalized,
            }
        )
    except Exception:
        raise _IssuerError("configured_front_pair_invalid") from None
    return tuple(normalized)


def _require_clean_ambient_secrets() -> None:
    """Require the root's UNSET launcher before any private config/env reads."""

    if any(name in os.environ for name in _AMBIENT_SECRET_AND_FRONT_NAMES):
        raise _IssuerError("ambient_secret_environment_present")


def _require_ignored_untracked_config(root: Path, helpers: Mapping[str, Any]) -> None:
    private = helpers["private"]
    r3_cli = helpers["r3_cli"]
    try:
        git = r3_cli._git_executable(private)
        relative = _CONFIG_RELATIVE.replace("/", os.sep)
        environment = {
            key: os.environ[key]
            for key in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP")
            if key in os.environ
        }
        environment.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_COUNT="2",
            GIT_CONFIG_KEY_0="core.fsmonitor",
            GIT_CONFIG_VALUE_0="false",
            GIT_CONFIG_KEY_1="core.excludesFile",
            GIT_CONFIG_VALUE_1=os.devnull,
            GIT_OPTIONAL_LOCKS="0",
            GIT_TERMINAL_PROMPT="0",
        )
        common = {
            "cwd": str(root),
            "env": environment,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "timeout": 10,
            "check": False,
        }
        ignored = subprocess.run(
            [str(git), "-C", str(root), "check-ignore", "--quiet", "--", relative],
            **common,
        )
        tracked = subprocess.run(
            [
                str(git),
                "-C",
                str(root),
                "ls-files",
                "--error-unmatch",
                "--",
                relative,
            ],
            **common,
        )
    except Exception:
        raise _IssuerError("private_config_ignore_check_failed") from None
    if ignored.returncode != 0 or tracked.returncode != 1:
        raise _IssuerError("private_config_not_ignored_untracked")


def _private_pair_config_lease(root: Path, helpers: Mapping[str, Any]) -> Any:
    """Retain read-only identity/ACL custody of the ignored suite config."""

    from contextlib import contextmanager

    @contextmanager
    def lease():
        private = helpers["private"]
        r3_cli = helpers["r3_cli"]
        path = root / Path(_CONFIG_RELATIVE)
        _require_ignored_untracked_config(root, helpers)
        stack = ExitStack()

        def close_preserving_exception() -> None:
            try:
                stack.close()
            except BaseException:
                pass

        try:
            info = path.lstat()
            if (
                path.is_symlink()
                or getattr(info, "st_file_attributes", 0) & 0x400
                or not path.is_file()
                or not path.is_absolute()
            ):
                raise _IssuerError("private_config_file_invalid")
            api = private._api()
            sid = api.current_sid()
            stack.enter_context(r3_cli._credential_ancestor_locks(path, private))
            handle, identity = stack.enter_context(r3_cli._locked_readonly_file(path, private, api))
            api.verify_acl(handle, sid, directory=False)
            raw = r3_cli._read_bounded_handle(api, handle, MAX_CONFIG_BYTES)
            front_pairs = _parse_private_config(raw, helpers["selector"])
            config_digest = hashlib.sha256(raw).hexdigest()

            def verify_current() -> None:
                api.verify_acl(handle, sid, directory=False)
                with r3_cli._locked_readonly_file(path, private, api) as (
                    other,
                    other_identity,
                ):
                    if other_identity != identity:
                        raise _IssuerError("private_config_identity_changed")
                    api.verify_acl(other, sid, directory=False)
                    current = r3_cli._read_bounded_handle(api, other, MAX_CONFIG_BYTES)
                if hashlib.sha256(current).hexdigest() != config_digest:
                    raise _IssuerError("private_config_changed_during_run")
                if _parse_private_config(current, helpers["selector"]) != front_pairs:
                    raise _IssuerError("private_config_pair_set_changed")

        except _IssuerError:
            close_preserving_exception()
            raise
        except Exception:
            close_preserving_exception()
            raise _IssuerError("private_config_unavailable") from None
        except BaseException:
            close_preserving_exception()
            raise

        try:
            yield front_pairs, config_digest, verify_current
        except BaseException:
            close_preserving_exception()
            raise

        try:
            verify_current()
        except _IssuerError:
            close_preserving_exception()
            raise
        except Exception:
            close_preserving_exception()
            raise _IssuerError("private_config_unavailable") from None
        except BaseException:
            close_preserving_exception()
            raise
        try:
            stack.close()
        except Exception:
            raise _IssuerError("private_config_unavailable") from None

    return lease()


def _credential_lease(
    owner: ModuleType,
    root: Path,
    helpers: Mapping[str, Any],
    front_pairs: Sequence[Mapping[str, str]],
) -> Any:
    """Resolve only the five config-first EnvRefs under retained .env custody."""

    from contextlib import contextmanager

    @contextmanager
    def lease():
        private = helpers["private"]
        r3_cli = helpers["r3_cli"]
        renderer = helpers["renderer"]
        env_path = root / ".env"
        api = private._api()
        stack = ExitStack()

        def close_preserving_exception() -> None:
            try:
                stack.close()
            except BaseException:
                pass

        try:
            stack.enter_context(r3_cli._require_ignored_env(env_path, private))
            stack.enter_context(r3_cli._credential_ancestor_locks(env_path, private))
            handle, _identity = stack.enter_context(
                r3_cli._locked_readonly_file(env_path, private, api)
            )
            api.verify_acl(handle, api.current_sid(), directory=False)
            raw = r3_cli._read_bounded_handle(api, handle, renderer.MAX_ENV_FILE_BYTES)
            values = renderer._parse_env_file(raw, _ENV_NAMES)
            fields = {}
            for field, name in _FIELD_ENV_NAMES.items():
                value = owner._validate_text(values[name], _ENV_VALUE_MAX_BYTES[field])
                fields[field] = value
            first_pair = front_pairs[0]
            credentials = owner._Credentials(
                broker_id=fields["broker_id"],
                user_id=fields["user_id"],
                password=fields["password"],
                app_id=fields["app_id"],
                auth_code=fields["auth_code"],
                product_info=owner._PRODUCT_INFO,
                md_front=first_pair["md_front"],
                td_front=first_pair["td_front"],
            )
        except _IssuerError:
            close_preserving_exception()
            raise
        except Exception:
            close_preserving_exception()
            raise _IssuerError("explicit_credential_source_unavailable") from None
        except BaseException:
            close_preserving_exception()
            raise

        try:
            yield credentials
        except BaseException:
            close_preserving_exception()
            raise

        try:
            api.verify_acl(handle, api.current_sid(), directory=False)
        except _IssuerError:
            close_preserving_exception()
            raise
        except Exception:
            close_preserving_exception()
            raise _IssuerError("explicit_credential_source_unavailable") from None
        except BaseException:
            close_preserving_exception()
            raise
        try:
            stack.close()
        except Exception:
            raise _IssuerError("explicit_credential_source_unavailable") from None

    return lease()


def _pair_projection(helpers: Mapping[str, Any], front_pairs: Sequence[Mapping[str, str]]) -> bytes:
    selector = helpers["selector"]
    if type(front_pairs) not in (tuple, list) or not 1 <= len(front_pairs) <= 8:
        raise _IssuerError("configured_front_pair_count_invalid")
    normalized = []
    for pair in front_pairs:
        if (
            not isinstance(pair, Mapping)
            or set(pair) != {"md_front", "td_front"}
            or type(pair.get("md_front")) is not str
            or type(pair.get("td_front")) is not str
        ):
            raise _IssuerError("configured_front_pair_invalid")
        normalized.append({"md_front": pair["md_front"], "td_front": pair["td_front"]})
    document = {
        "schema": selector.SCHEMA,
        "venue": "simnow",
        "scope": "transport_only",
        "strategy_id": selector.STRATEGY,
        "front_pairs": normalized,
    }
    try:
        raw = json.dumps(
            document,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        if not 0 < len(raw) <= MAX_PROJECTION_BYTES:
            raise ValueError("size")
        selector.parse_document(raw)
    except Exception:
        raise _IssuerError("configured_front_projection_invalid") from None
    return raw


def _fresh_pair_selection_value(
    degraded_candidate: Any, observation_binding_sha256: Any
) -> dict[str, Any]:
    if (
        type(degraded_candidate) is not bool
        or type(observation_binding_sha256) is not str
        or not _SHA256_RE.fullmatch(observation_binding_sha256)
    ):
        raise _IssuerError("fresh_pair_binding_invalid")
    return {
        "source": _FRESH_PAIR_SELECTION_SOURCE,
        "degraded_candidate": degraded_candidate,
        "observation_binding_sha256": observation_binding_sha256,
    }


def _validate_fresh_pair_selection(
    value: Any, *, expected_selection_sha256: Any = None
) -> dict[str, Any] | None:
    if value is None:
        return None
    if (
        type(value) is not dict
        or set(value) != {"source", "degraded_candidate", "observation_binding_sha256"}
        or value.get("source") != _FRESH_PAIR_SELECTION_SOURCE
        or type(value.get("degraded_candidate")) is not bool
        or type(value.get("observation_binding_sha256")) is not str
        or not _SHA256_RE.fullmatch(value["observation_binding_sha256"])
    ):
        raise _IssuerError("fresh_pair_binding_invalid")
    if expected_selection_sha256 is not None and (
        type(expected_selection_sha256) is not str
        or not _SHA256_RE.fullmatch(expected_selection_sha256)
        or value["observation_binding_sha256"] != expected_selection_sha256
    ):
        raise _IssuerError("fresh_pair_binding_invalid")
    return {
        "source": _FRESH_PAIR_SELECTION_SOURCE,
        "degraded_candidate": value["degraded_candidate"],
        "observation_binding_sha256": value["observation_binding_sha256"],
    }


def _select_current_pair(
    helpers: Mapping[str, Any],
    front_pairs: Sequence[Mapping[str, str]],
    *,
    deadline: float,
    audit_sink: dict[str, Any] | None = None,
    connector: Any = None,
    probe_clock: Any = None,
) -> Any:
    if time.monotonic() >= deadline:
        raise _IssuerError("issuer_deadline_exceeded")
    if audit_sink is not None and (
        type(audit_sink) is not dict or "fresh_pair_selection" in audit_sink
    ):
        raise _IssuerError("fresh_pair_binding_invalid")
    handoff_module = helpers["handoff"]
    protocol = helpers["protocol"]
    projection = _pair_projection(helpers, front_pairs)
    try:
        handoff = handoff_module.create_current_handoff(
            projection,
            confirm_transport_only=True,
            connector=connector,
            probe_clock=probe_clock,
        )
        selected = handoff.consume(projection)
    except Exception as error:
        handoff_error_type = getattr(handoff_module, "FrontHandoffError", None)
        code = None
        if type(error) is handoff_error_type:
            args = error.args
            if type(args) is tuple and len(args) == 1 and type(args[0]) is str:
                code = args[0]
        reason = _FRESH_PAIR_HANDOFF_FAILURES.get(code, "fresh_pair_local_failure")
        raise _IssuerError(reason) from None
    selection_type = getattr(handoff_module, "SelectedFrontPair", None)
    if (
        type(selected) is not selection_type
        or type(selected.config_index) is not int
        or not 0 <= selected.config_index < len(front_pairs)
        or selected.execution_authority != "NONE"
        or type(selected.degraded_candidate) is not bool
        or selected.public_projection_sha256 != hashlib.sha256(projection).hexdigest()
        or (selected.md_front, selected.td_front)
        != (
            front_pairs[selected.config_index]["md_front"],
            front_pairs[selected.config_index]["td_front"],
        )
        or time.monotonic() >= deadline
    ):
        raise _IssuerError("fresh_pair_binding_invalid")
    try:
        binding = protocol.C01PairBinding(
            selected_index=selected.config_index,
            selection_sha256=selected.observation_sha256,
            md_front_sha256=hashlib.sha256(selected.md_front.encode("utf-8")).hexdigest(),
            td_front_sha256=hashlib.sha256(selected.td_front.encode("utf-8")).hexdigest(),
            td_front=selected.td_front,
            selected_at_utc=helpers["owner_now_utc"](),
        )
    except Exception:
        raise _IssuerError("fresh_pair_binding_invalid") from None
    if (
        type(binding) is not protocol.C01PairBinding
        or binding.selection_sha256 != selected.observation_sha256
    ):
        raise _IssuerError("fresh_pair_binding_invalid")
    if audit_sink is not None:
        audit_sink["fresh_pair_selection"] = _validate_fresh_pair_selection(
            _fresh_pair_selection_value(selected.degraded_candidate, selected.observation_sha256),
            expected_selection_sha256=binding.selection_sha256,
        )
    return binding


def _validation_issues_pass(contract: Any, protocol: Any, validation: Any) -> bool:
    return (
        type(validation) is protocol.C01CandidateValidation
        and validation.status == "BLOCKED"
        and validation.eligible_for_protected_admission is True
        and validation.reasons == (contract._PROTECTED_ADMISSION_REQUIRED,)
        and validation.checked_request_count == 8
        and validation.checked_query_callback_count >= 6
        and validation.checked_snapshot_count == 2
    )


def _canonical_digest(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


_WORKER_PROGRESS_STAGE_EVENTS = {
    "worker": frozenset({"begin"}),
    "private_paths": frozenset({"end"}),
    "sdk_install_verify": frozenset({"begin", "end"}),
    "sdk_import": frozenset({"begin", "end"}),
    "client_construct": frozenset({"begin", "end"}),
    "client_start": frozenset({"begin", "end"}),
    "client_no_join_start_policy": frozenset({"begin", "end", "failed"}),
    "client_start_native_module_check": frozenset({"begin", "end", "failed"}),
    "client_start_generation_reserve": frozenset({"begin", "end", "failed"}),
    "client_start_identity_validate": frozenset({"begin", "end", "failed"}),
    "client_start_identity_compare": frozenset({"begin", "end", "failed"}),
    "client_start_flow_prepare": frozenset({"begin", "end", "failed"}),
    "native_create_trader_api": frozenset({"begin", "end", "failed"}),
    "native_register_spi_attach": frozenset({"begin", "end", "failed"}),
    "native_subscribe_private_topic": frozenset({"begin", "end", "failed"}),
    "native_subscribe_public_topic": frozenset({"begin", "end", "failed"}),
    "native_register_front": frozenset({"begin", "end", "failed"}),
    "native_api_init": frozenset({"begin", "end", "failed"}),
    "native_register_spi_detach": frozenset({"begin", "end", "failed"}),
    "native_release": frozenset({"begin", "end", "failed"}),
    "login_wait": frozenset({"begin", "end"}),
    "snapshot_directory": frozenset({"begin", "end"}),
    "authenticate_request": frozenset({"begin", "end"}),
    "login_request": frozenset({"begin", "end"}),
    "authenticate_callback": frozenset({"callback_first", "callback_terminal"}),
    "login_callback": frozenset({"callback_first", "callback_terminal"}),
    "baseline_orders_request": frozenset({"begin", "end"}),
    "baseline_positions_request": frozenset({"begin", "end"}),
    "baseline_funds_request": frozenset({"begin", "end"}),
    "final_orders_request": frozenset({"begin", "end"}),
    "final_positions_request": frozenset({"begin", "end"}),
    "final_funds_request": frozenset({"begin", "end"}),
    "baseline_orders_callback": frozenset({"callback_first", "callback_terminal"}),
    "baseline_positions_callback": frozenset({"callback_first", "callback_terminal"}),
    "baseline_funds_callback": frozenset({"callback_first", "callback_terminal"}),
    "final_orders_callback": frozenset({"callback_first", "callback_terminal"}),
    "final_positions_callback": frozenset({"callback_first", "callback_terminal"}),
    "final_funds_callback": frozenset({"callback_first", "callback_terminal"}),
    "baseline_orders_read": frozenset({"begin", "end"}),
    "baseline_positions_read": frozenset({"begin", "end"}),
    "baseline_funds_read": frozenset({"begin", "end"}),
    "final_orders_read": frozenset({"begin", "end"}),
    "final_positions_read": frozenset({"begin", "end"}),
    "final_funds_read": frozenset({"begin", "end"}),
    "baseline_snapshot_write": frozenset({"begin", "end"}),
    "final_snapshot_write": frozenset({"begin", "end"}),
    "native_stop": frozenset({"begin", "end", "failed"}),
    "worker_receipt": frozenset({"begin", "end"}),
}
_WORKER_PROGRESS_KEYS = frozenset(
    {
        "protocol",
        "version",
        "case_id",
        "sequence",
        "stage",
        "event",
        "run_nonce",
        "parent_pid",
        "worker_pid",
        "worker_source_sha256",
        "account_scope_sha256",
        "credential_binding_sha256",
        "pair_binding",
        "recorded_at_utc",
        "recorded_monotonic_ns",
        "previous_record_sha256",
    }
)
_WORKER_PROGRESS_FILENAME_RE = re.compile(r"progress-([0-9]{3})\.json\Z")
_WORKER_PROGRESS_UTC_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z"
)


def _progress_summary(
    payloads: Mapping[str, bytes],
    *,
    run_nonce: Any,
    parent_pid: Any,
    worker_pid: Any,
    worker_source_sha256: Any,
    pair_binding: Any,
    account_scope_sha256: Any,
    credential_binding_sha256: Any,
) -> dict[str, Any]:
    """Verify a bounded local progress prefix and return only safe stage facts."""

    safe_records: list[dict[str, Any]] = []

    def result(status: str) -> dict[str, Any]:
        last = safe_records[-1] if safe_records else None
        return {
            "schema": "simnow.c01.native-progress-summary.v1",
            "status": status,
            "record_count": len(safe_records),
            "records": safe_records,
            "last_stage": last["stage"] if last else None,
            "last_event": last["event"] if last else None,
            "last_recorded_at_utc": last["recorded_at_utc"] if last else None,
            "last_recorded_monotonic_ns": last["recorded_monotonic_ns"] if last else None,
            "worker_pid": last["worker_pid"] if last else worker_pid,
        }

    if type(payloads) is not dict or not payloads:
        return result("missing")
    if (
        len(payloads) > MAX_WORKER_PROGRESS_RECORDS
        or type(run_nonce) is not str
        or not re.fullmatch(r"[0-9a-f]{32}", run_nonce)
        or type(parent_pid) is not int
        or parent_pid < 1
        or type(worker_pid) is not int
        or worker_pid < 1
        or type(worker_source_sha256) is not str
        or not _SHA256_RE.fullmatch(worker_source_sha256)
        or type(account_scope_sha256) is not str
        or not _SHA256_RE.fullmatch(account_scope_sha256)
        or type(credential_binding_sha256) is not str
        or not _SHA256_RE.fullmatch(credential_binding_sha256)
        or type(pair_binding) is not dict
    ):
        return result("invalid")
    filenames = sorted(payloads)
    expected_names = [
        "progress-{:03d}.json".format(index) for index in range(1, len(filenames) + 1)
    ]
    if filenames != expected_names:
        return result("invalid")
    total_bytes = 0
    previous_sha256 = "0" * 64
    seen_events: dict[str, set[str]] = {}
    complete_marker = False
    for index, filename in enumerate(filenames, start=1):
        raw = payloads[filename]
        if type(raw) is not bytes:
            return result("invalid")
        total_bytes += len(raw)
        if (
            len(raw) > MAX_WORKER_PROGRESS_RECORD_BYTES
            or total_bytes > MAX_WORKER_PROGRESS_TOTAL_BYTES
            or not raw.endswith(b"\n")
            or complete_marker
        ):
            return result("invalid")
        try:
            document = json.loads(raw.decode("ascii"))
            canonical = (
                json.dumps(
                    document,
                    ensure_ascii=True,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("ascii")
                + b"\n"
            )
        except Exception:
            return result("invalid")
        if type(document) is not dict or set(document) != _WORKER_PROGRESS_KEYS or raw != canonical:
            return result("invalid")
        stage = document.get("stage")
        event = document.get("event")
        if (
            document.get("protocol") != "simnow.c01.native-progress.v1"
            or type(document.get("version")) is not int
            or document["version"] != 1
            or document.get("case_id") != "C01"
            or type(document.get("sequence")) is not int
            or document["sequence"] != index
            or type(stage) is not str
            or stage not in _WORKER_PROGRESS_STAGE_EVENTS
            or type(event) is not str
            or event not in _WORKER_PROGRESS_STAGE_EVENTS[stage]
            or document.get("run_nonce") != run_nonce
            or type(document.get("parent_pid")) is not int
            or document["parent_pid"] != parent_pid
            or type(document.get("worker_pid")) is not int
            or document["worker_pid"] != worker_pid
            or document.get("worker_source_sha256") != worker_source_sha256
            or document.get("account_scope_sha256") != account_scope_sha256
            or document.get("credential_binding_sha256") != credential_binding_sha256
            or document.get("pair_binding") != pair_binding
            or type(document.get("recorded_at_utc")) is not str
            or not _WORKER_PROGRESS_UTC_RE.fullmatch(document["recorded_at_utc"])
            or type(document.get("recorded_monotonic_ns")) is not int
            or document["recorded_monotonic_ns"] < 1
            or document.get("previous_record_sha256") != previous_sha256
        ):
            return result("invalid")
        stage_seen = seen_events.setdefault(stage, set())
        if event in stage_seen:
            return result("invalid")
        if event == "end" and stage not in {"private_paths"} and "begin" not in stage_seen:
            return result("invalid")
        if event == "failed" and "begin" not in stage_seen:
            return result("invalid")
        if event == "callback_terminal" and "callback_first" not in stage_seen:
            return result("invalid")
        stage_seen.add(event)
        safe_records.append(
            {
                "sequence": index,
                "stage": stage,
                "event": event,
                "recorded_at_utc": document["recorded_at_utc"],
                "recorded_monotonic_ns": document["recorded_monotonic_ns"],
                "worker_pid": document["worker_pid"],
            }
        )
        previous_sha256 = hashlib.sha256(raw).hexdigest()
        complete_marker = stage == "worker_receipt" and event == "end"
    return result("verified")


def _empty_progress_summary(status: str, worker_pid: Any = None) -> dict[str, Any]:
    if status not in {"missing", "invalid", "unavailable"}:
        status = "unavailable"
    return {
        "schema": "simnow.c01.native-progress-summary.v1",
        "status": status,
        "record_count": 0,
        "records": [],
        "last_stage": None,
        "last_event": None,
        "last_recorded_at_utc": None,
        "last_recorded_monotonic_ns": None,
        "worker_pid": worker_pid if type(worker_pid) is int and worker_pid > 0 else None,
    }


_WORKER_PROGRESS_SUMMARY_KEYS = frozenset(
    {
        "schema",
        "status",
        "record_count",
        "records",
        "last_stage",
        "last_event",
        "last_recorded_at_utc",
        "last_recorded_monotonic_ns",
        "worker_pid",
    }
)
_WORKER_PROGRESS_RECORD_SUMMARY_KEYS = frozenset(
    {"sequence", "stage", "event", "recorded_at_utc", "recorded_monotonic_ns", "worker_pid"}
)


def _safe_progress_summary(value: Any) -> dict[str, Any]:
    """Keep only the public-safe fixed progress summary fields for the audit."""

    if type(value) is not dict or set(value) != _WORKER_PROGRESS_SUMMARY_KEYS:
        return _empty_progress_summary("unavailable")
    status = value.get("status")
    records = value.get("records")
    if (
        value.get("schema") != "simnow.c01.native-progress-summary.v1"
        or status not in {"missing", "invalid", "unavailable", "verified"}
        or type(value.get("record_count")) is not int
        or not 0 <= value["record_count"] <= MAX_WORKER_PROGRESS_RECORDS
        or type(records) is not list
        or len(records) != value["record_count"]
    ):
        return _empty_progress_summary("unavailable")
    safe_records = []
    for index, item in enumerate(records, start=1):
        if (
            type(item) is not dict
            or set(item) != _WORKER_PROGRESS_RECORD_SUMMARY_KEYS
            or type(item.get("sequence")) is not int
            or item["sequence"] != index
            or type(item.get("stage")) is not str
            or item["stage"] not in _WORKER_PROGRESS_STAGE_EVENTS
            or type(item.get("event")) is not str
            or item["event"] not in _WORKER_PROGRESS_STAGE_EVENTS[item["stage"]]
            or type(item.get("recorded_at_utc")) is not str
            or not _WORKER_PROGRESS_UTC_RE.fullmatch(item["recorded_at_utc"])
            or type(item.get("recorded_monotonic_ns")) is not int
            or item["recorded_monotonic_ns"] < 1
            or type(item.get("worker_pid")) is not int
            or item["worker_pid"] < 1
        ):
            return _empty_progress_summary("unavailable")
        safe_records.append(dict(item))
    last = safe_records[-1] if safe_records else None
    expected_last = {
        "last_stage": last["stage"] if last else None,
        "last_event": last["event"] if last else None,
        "last_recorded_at_utc": last["recorded_at_utc"] if last else None,
        "last_recorded_monotonic_ns": last["recorded_monotonic_ns"] if last else None,
        "worker_pid": last["worker_pid"] if last else value.get("worker_pid"),
    }
    if any(value.get(key) != expected for key, expected in expected_last.items()):
        return _empty_progress_summary("unavailable")
    if status == "verified" and not safe_records:
        return _empty_progress_summary("unavailable")
    if status in {"missing", "unavailable"} and safe_records:
        return _empty_progress_summary("unavailable")
    return {
        "schema": "simnow.c01.native-progress-summary.v1",
        "status": status,
        "record_count": len(safe_records),
        "records": safe_records,
        **expected_last,
    }


def _read_worker_progress(
    owner: ModuleType,
    helpers: Mapping[str, Any],
    paths: Any,
    process: Any,
    pair_binding: Any,
    account_scope_sha256: str,
    credential_binding_sha256: str,
) -> dict[str, Any]:
    """Read and verify only fixed progress files from the current private run."""

    unavailable = _empty_progress_summary("unavailable")
    try:
        if type(process) is not helpers["supervisor"].C01SupervisorResult:
            return unavailable
        lifecycle = process.process_lifecycle
        if type(lifecycle) is not helpers["protocol"].C01ProcessLifecycleReceipt:
            return unavailable
        evidence = paths.evidence.path
        entries = owner._directory_entries(evidence)
        progress_paths = []
        for entry in entries:
            if entry.name == "snapshots" or entry.name == "failure.json":
                continue
            if not _WORKER_PROGRESS_FILENAME_RE.fullmatch(entry.name) or entry.is_dir():
                return _empty_progress_summary("invalid", getattr(lifecycle, "worker_pid", None))
            progress_paths.append(entry)
        if len(progress_paths) > MAX_WORKER_PROGRESS_RECORDS:
            return _empty_progress_summary("invalid", getattr(lifecycle, "worker_pid", None))
        private = helpers["private"]
        r3_cli = helpers["r3_cli"]
        api = private._api()
        sid = api.current_sid()
        payloads: dict[str, bytes] = {}
        total_bytes = 0
        for path in progress_paths:
            with r3_cli._locked_readonly_file(path, private, api) as (handle, _identity):
                api.verify_acl(handle, sid, directory=False)
                raw = r3_cli._read_bounded_handle(api, handle, MAX_WORKER_PROGRESS_RECORD_BYTES)
            total_bytes += len(raw)
            if total_bytes > MAX_WORKER_PROGRESS_TOTAL_BYTES:
                return unavailable
            payloads[path.name] = raw
        pair_ref = pair_binding.to_receipt_ref().to_dict()
        return _progress_summary(
            payloads,
            run_nonce=lifecycle.run_nonce,
            parent_pid=lifecycle.parent_pid,
            worker_pid=lifecycle.worker_pid,
            worker_source_sha256=_WORKER_SHA256,
            pair_binding=pair_ref,
            account_scope_sha256=account_scope_sha256,
            credential_binding_sha256=credential_binding_sha256,
        )
    except Exception:
        return unavailable


def _diagnostic_stage_intents_document(
    helpers: Mapping[str, Any], process: Any, pair_binding: Any
) -> dict[str, Any] | None:
    """Validate and retain the supervisor's typed, local-only stage prefix."""

    supervisor = helpers["supervisor"]
    protocol = helpers["protocol"]
    if type(process) is not supervisor.C01SupervisorResult:
        raise _IssuerError("diagnostic_intent_result_invalid")
    lifecycle = process.process_lifecycle
    if type(lifecycle) is not protocol.C01ProcessLifecycleReceipt:
        raise _IssuerError("diagnostic_intent_lifecycle_invalid")
    if process.reason == "candidate_transport_complete":
        if process.diagnostic_intents or process.diagnostic_intents_error is not None:
            raise _IssuerError("diagnostic_intent_unexpected")
        return None
    if type(pair_binding) is not protocol.C01PairBinding:
        raise _IssuerError("diagnostic_intent_pair_binding_invalid")
    pair_ref = pair_binding.to_receipt_ref()
    if type(pair_ref) is not protocol.C01PairBindingRef:
        raise _IssuerError("diagnostic_intent_pair_binding_invalid")
    expected_pair_ref = pair_ref.to_dict()
    intents = process.diagnostic_intents
    error = process.diagnostic_intents_error
    if (
        type(intents) is not tuple
        or len(intents) > supervisor.MAX_DIAGNOSTIC_INTENT_RECORDS
        or (error is not None and error not in supervisor._DIAGNOSTIC_INTENT_ERRORS)
    ):
        raise _IssuerError("diagnostic_intent_shape_invalid")

    records = []
    for sequence, intent in enumerate(intents, start=1):
        if (
            type(intent) is not supervisor.C01StageIntent
            or type(intent.sequence) is not int
            or intent.sequence != sequence
            or type(intent.stage) is not str
            or intent.stage not in supervisor._DIAGNOSTIC_INTENT_STAGES
            or type(intent.event) is not str
            or intent.event not in supervisor._DIAGNOSTIC_INTENT_EVENTS
            or type(intent.run_nonce) is not str
            or not re.fullmatch(r"[0-9a-f]{32}", intent.run_nonce)
            or intent.run_nonce != lifecycle.run_nonce
            or type(intent.parent_pid) is not int
            or intent.parent_pid != lifecycle.parent_pid
            or type(intent.worker_pid) is not int
            or intent.worker_pid != lifecycle.worker_pid
            or type(intent.worker_source_sha256) is not str
            or intent.worker_source_sha256 != _WORKER_SHA256
            or type(intent.pair_binding_ref) is not protocol.C01PairBindingRef
            or intent.pair_binding_ref.to_dict() != expected_pair_ref
        ):
            raise _IssuerError("diagnostic_intent_binding_invalid")
        records.append(
            {
                "protocol": supervisor._DIAGNOSTIC_INTENT_PROTOCOL,
                "version": supervisor._DIAGNOSTIC_INTENT_VERSION,
                "case_id": CASE_ID,
                "sequence": sequence,
                "stage": intent.stage,
                "event": intent.event,
                "run_nonce": intent.run_nonce,
                "parent_pid": intent.parent_pid,
                "worker_pid": intent.worker_pid,
                "worker_source_sha256": intent.worker_source_sha256,
                "pair_binding_ref": expected_pair_ref,
            }
        )
    if process.reason == "diagnostic_profile_only" and (error is not None or not records):
        raise _IssuerError("diagnostic_intent_result_invalid")
    if process.reason == "diagnostic_intent_stream_invalid" and error is None:
        raise _IssuerError("diagnostic_intent_result_invalid")
    return {
        "schema": "simnow.c01.stage-intent-trace.v1",
        "status": "complete"
        if error is None and records
        else ("invalid_stream" if error else "missing"),
        "error": error,
        "record_count": len(records),
        "records": records,
    }


def _audit_document(
    owner: ModuleType,
    helpers: Mapping[str, Any],
    paths: Any,
    *,
    status: str,
    reason: str,
    config_sha256: str = "",
    projection_sha256: str = "",
    selected_index: Any = None,
    account_scope_sha256: str = "",
    credential_binding_sha256: str = "",
    process: Any = None,
    artifacts: Mapping[str, bytes] | None = None,
    validation: Any = None,
    worker_progress: Mapping[str, Any] | None = None,
    fresh_pair_selection: Mapping[str, Any] | None = None,
    pair_binding: Any = None,
    admission: _C01V3Admission | None = None,
) -> dict[str, Any]:
    if type(status) is not str or status not in {"BLOCKED", "CANDIDATE_EVIDENCE_COMPLETE"}:
        raise _IssuerError("issuer_audit_status_invalid")
    owner_pins = dict(owner._SOURCE_PINS)
    selection_value = _validate_fresh_pair_selection(fresh_pair_selection)
    if process is not None and selection_value is None:
        raise _IssuerError("issuer_audit_fresh_pair_selection_missing")
    if pair_binding is not None:
        protocol = helpers["protocol"]
        if (
            type(pair_binding) is not protocol.C01PairBinding
            or selection_value is None
            or pair_binding.selection_sha256 != selection_value["observation_binding_sha256"]
            or (selected_index is not None and pair_binding.selected_index != selected_index)
        ):
            raise _IssuerError("issuer_audit_pair_binding_invalid")
    result: dict[str, Any] = {
        "schema": "simnow.c01.native_td_read_v3.issuer_audit.v1",
        "profile": PROFILE_ID,
        "case_id": CASE_ID,
        "profile_contract_sha256": PROFILE_CONTRACT_SHA256,
        "profile_status": status,
        "reason": reason if _SAFE_REASON.fullmatch(reason) else "issuer_internal_error",
        "private_run_root": str(paths.root.path),
        "consumer_executable": str(Path(sys.executable).resolve()),
        "entry_source_sha256": globals().get("__c01_source_sha256__", ""),
        "source_bindings": {
            "source_manifest_sha256": _SOURCE_MANIFEST_SHA256,
            "owner_sha256": _OWNER_SHA256,
            "worker_sha256": _WORKER_SHA256,
            "case_contract_sha256": _CASE_CONTRACT_SHA256,
            "case_strategy_sha256": _CASE_STRATEGY_SHA256,
            "envref_template_sha256": _ENVREF_TEMPLATE_SHA256,
            "pinned_sources": owner_pins,
        },
        "config_sha256": config_sha256,
        "public_projection_sha256": projection_sha256,
        "selected_index": selected_index,
        "account_scope_sha256": account_scope_sha256,
        "credential_binding_sha256": credential_binding_sha256,
        "write_counters": {"ReqOrderInsert": 0, "ReqOrderAction": 0},
        "diagnostic_stage_intents": None,
    }
    if admission is not None:
        if (
            type(admission) is not _C01V3Admission
            or not _SHA256_RE.fullmatch(admission.admission_sha256)
            or not _SHA256_RE.fullmatch(admission.claim_sha256)
            or not _SHA256_RE.fullmatch(admission.consumed_sha256)
        ):
            raise _IssuerError("issuer_audit_admission_invalid")
        result["protected_admission"] = {
            "schema": _ADMISSION_SCHEMA,
            "profile_id": PROFILE_ID,
            "case_id": CASE_ID,
            "admission_id": admission.admission_id,
            "admission_sha256": admission.admission_sha256,
            "claim_sha256": admission.claim_sha256,
            "consumed_sha256": admission.consumed_sha256,
            "bindings_sha256": _canonical_digest(dict(admission.bindings)),
            "source_manifest_sha256": _SOURCE_MANIFEST_SHA256,
        }
    if process is not None:
        protocol = helpers["protocol"]
        supervisor = helpers["supervisor"]
        if type(process) is not supervisor.C01SupervisorResult:
            raise _IssuerError("issuer_audit_supervisor_type_invalid")
        worker_receipt = process.worker_receipt
        lifecycle = process.process_lifecycle
        if type(lifecycle) is not protocol.C01ProcessLifecycleReceipt:
            raise _IssuerError("issuer_audit_lifecycle_type_invalid")
        result["diagnostic_stage_intents"] = _diagnostic_stage_intents_document(
            helpers, process, pair_binding
        )
        lifecycle_value = asdict(lifecycle)
        if type(worker_receipt) is protocol.C01WorkerReceipt:
            try:
                worker_frame = protocol.encode_worker_frame(worker_receipt.to_dict())
                worker_value = protocol.parse_worker_frame(worker_frame).to_dict()
            except Exception:
                raise _IssuerError("issuer_audit_worker_receipt_invalid") from None
            pair_value = worker_value.get("pair_binding")
            if (
                selection_value is None
                or type(pair_value) is not dict
                or pair_value.get("selection_sha256")
                != selection_value["observation_binding_sha256"]
            ):
                raise _IssuerError("issuer_audit_fresh_pair_binding_mismatch")
            worker_digest = _canonical_digest(worker_value)
        elif worker_receipt is None and status == "BLOCKED":
            worker_value = None
            worker_digest = None
        else:
            raise _IssuerError("issuer_audit_worker_receipt_type_invalid")
        result["worker_receipt"] = {
            "type": "C01WorkerReceipt",
            "sha256": worker_digest,
            "value": worker_value,
        }
        result["supervisor_result"] = {
            "type": "C01SupervisorResult",
            "status": process.status,
            "reason": process.reason,
        }
        result["process_lifecycle"] = {
            "type": "C01ProcessLifecycleReceipt",
            "sha256": _canonical_digest(lifecycle_value),
            "value": lifecycle_value,
            "job_active_count": lifecycle.job_active_count,
            "process_exit_code": lifecycle.process_exit_code,
            "stdout_eof": lifecycle.stdout_eof,
            "stderr_eof": lifecycle.stderr_eof,
            "handles_closed": lifecycle.handles_closed,
        }
    if artifacts is not None:
        result["snapshots"] = {
            name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(artifacts.items())
        }
    if worker_progress is not None:
        result["worker_progress"] = _safe_progress_summary(worker_progress)
    if selection_value is not None:
        result["fresh_pair_selection"] = selection_value
    if validation is not None:
        validation_value = {
            "eligible_for_protected_admission": validation.eligible_for_protected_admission,
            "status": validation.status,
            "reasons": list(validation.reasons),
            "checked_request_count": validation.checked_request_count,
            "checked_query_callback_count": validation.checked_query_callback_count,
            "checked_snapshot_count": validation.checked_snapshot_count,
        }
        result["validation"] = {
            "type": "C01CandidateValidation",
            "sha256": _canonical_digest(validation_value),
            **validation_value,
        }
    return result


def _persist_private_audit(
    paths: Any, helpers: Mapping[str, Any], document: Mapping[str, Any]
) -> str:
    try:
        encoded = json.dumps(
            document,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        if len(encoded) > MAX_PRIVATE_AUDIT_BYTES:
            raise _IssuerError("issuer_audit_size_invalid")
        digest = paths.root.write_json("issuer-audit.json", dict(document))
        audit_path = paths.root.path / "issuer-audit.json"
        private = helpers["private"]
        r3_cli = helpers["r3_cli"]
        api = private._api()
        sid = api.current_sid()
        with r3_cli._locked_readonly_file(audit_path, private, api) as (handle, _identity):
            api.verify_acl(handle, sid, directory=False)
            raw = r3_cli._read_bounded_handle(api, handle, MAX_PRIVATE_AUDIT_BYTES)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise _IssuerError("issuer_audit_digest_mismatch")
        paths.root.verify()
        return digest
    except _IssuerError:
        raise
    except Exception:
        raise _IssuerError("issuer_audit_persist_failed") from None


def _run_candidate(
    owner: ModuleType,
    helpers: Mapping[str, Any],
    *,
    deadline: float,
    admission: _C01V3Admission,
) -> str:
    protocol = helpers["protocol"]
    supervisor = helpers["supervisor"]
    contract = helpers["contract"]
    root = owner._repo_root()
    private_paths = None
    audit_state: dict[str, Any] = {
        "status": "BLOCKED",
        "reason": "candidate_incomplete",
    }
    try:
        if type(admission) is not _C01V3Admission or not admission.active():
            raise _IssuerError("admission_expired_during_run")
        with ExitStack() as stack:
            front_pairs, config_digest, verify_config = stack.enter_context(
                _private_pair_config_lease(root, helpers)
            )
            if config_digest != admission.bindings.get("config_source_sha256"):
                raise _IssuerError("admission_config_binding_mismatch")
            if not admission.active():
                raise _IssuerError("admission_expired_during_run")
            credentials = stack.enter_context(_credential_lease(owner, root, helpers, front_pairs))
            private_paths = stack.enter_context(owner._private_run(helpers))
            audit_state["config_sha256"] = config_digest
            audit_state["private_run_root"] = str(private_paths.root.path)
            verify_config()
            required_after_selection = (
                MAX_RUN_SECONDS + MAX_CLEANUP_SECONDS + MAX_POST_RUN_VALIDATION_SECONDS
            )
            if deadline - time.monotonic() < required_after_selection:
                raise _IssuerError("issuer_deadline_reserve_unavailable")
            selection_deadline = min(
                time.monotonic() + MAX_PAIR_SELECTION_SECONDS,
                deadline - required_after_selection,
            )
            pair_binding = _select_current_pair(
                helpers,
                front_pairs,
                deadline=selection_deadline,
                audit_sink=audit_state,
            )
            projection = _pair_projection(helpers, front_pairs)
            audit_state.update(
                projection_sha256=hashlib.sha256(projection).hexdigest(),
                selected_index=pair_binding.selected_index,
                pair_binding=pair_binding,
            )
            verify_config()
            if deadline - time.monotonic() < required_after_selection:
                raise _IssuerError("issuer_deadline_reserve_unavailable")
            packet, account_digest, credential_digest = owner._private_input_packet(
                helpers, credentials, private_paths
            )
            if account_digest != admission.bindings.get(
                "account_scope_sha256"
            ) or credential_digest != admission.bindings.get("credential_binding_sha256"):
                raise _IssuerError("admission_account_binding_mismatch")
            audit_state.update(
                account_scope_sha256=account_digest,
                credential_binding_sha256=credential_digest,
            )
            if deadline - time.monotonic() < required_after_selection:
                raise _IssuerError("issuer_deadline_exceeded")
            if not admission.active():
                raise _IssuerError("admission_expired_during_run")
            _validate_fresh_pair_selection(
                audit_state.get("fresh_pair_selection"),
                expected_selection_sha256=pair_binding.selection_sha256,
            )
            worker_path = root / "backtrader_runtime" / "certification_simnow_c01_native_v2.py"
            try:
                process = supervisor.run_fixed_c01_worker(
                    worker_path=worker_path,
                    source_root=worker_path.parent,
                    expected_worker_source_sha256=_WORKER_SHA256,
                    pair_binding=pair_binding,
                    account_scope_sha256=account_digest,
                    credential_binding_sha256=credential_digest,
                    credential_packet=packet,
                    timeout_seconds=MAX_RUN_SECONDS,
                    cleanup_seconds=MAX_CLEANUP_SECONDS,
                    diagnostic_intents=_DIAGNOSTIC_INTENTS_ONLY,
                )
            except Exception:
                raise _IssuerError("worker_supervisor_failed") from None
            audit_state["process"] = process
            if type(process) is supervisor.C01SupervisorResult:
                audit_state["worker_progress"] = _read_worker_progress(
                    owner,
                    helpers,
                    private_paths,
                    process,
                    pair_binding,
                    account_digest,
                    credential_digest,
                )
            else:
                audit_state["worker_progress"] = _empty_progress_summary("unavailable")
            if type(process) is not supervisor.C01SupervisorResult:
                raise _IssuerError("worker_process_incomplete")
            if not admission.active():
                raise _IssuerError("admission_expired_during_run")
            if not owner._worker_process_complete(helpers, process):
                lifecycle = getattr(process, "process_lifecycle", None)
                if getattr(lifecycle, "timed_out", False):
                    raise _IssuerError("native_close_unknown")
                raise _IssuerError("worker_process_incomplete")
            if process.reason == "diagnostic_profile_only":
                raise _IssuerError("diagnostic_profile_only")
            if process.reason == "diagnostic_intent_stream_invalid":
                raise _IssuerError("diagnostic_intent_stream_invalid")
            progress = audit_state["worker_progress"]
            if (
                progress.get("status") != "verified"
                or progress.get("last_stage") != "worker_receipt"
                or progress.get("last_event") != "end"
            ):
                raise _IssuerError("worker_progress_invalid")
            if time.monotonic() >= deadline:
                raise _IssuerError("issuer_deadline_exceeded")
            if not owner._worker_receipt_matches(
                helpers, process, pair_binding, account_digest, credential_digest
            ):
                raise _IssuerError("worker_receipt_misbinding")
            verify_config()
            owner._verify_tree(helpers, private_paths, expected_snapshots=True)
            artifacts = owner._read_snapshot_artifacts(helpers, private_paths)
            audit_state["artifacts"] = artifacts
            if deadline - time.monotonic() < 0:
                raise _IssuerError("issuer_deadline_exceeded")
            try:
                decision = contract.validate_c01_candidate(
                    process.worker_receipt,
                    process.process_lifecycle,
                    expected_pair_binding=pair_binding,
                    expected_worker_source_sha256=_WORKER_SHA256,
                    expected_account_scope_sha256=account_digest,
                    expected_credential_binding_sha256=credential_digest,
                    private_snapshot_artifacts=artifacts,
                    expected_broker_id=credentials.broker_id,
                    expected_user_id=credentials.user_id,
                )
            except Exception:
                raise _IssuerError("candidate_contract_failed") from None
            audit_state["validation"] = decision
            if deadline - time.monotonic() < 0:
                raise _IssuerError("issuer_deadline_exceeded")
            if not _validation_issues_pass(contract, protocol, decision):
                raise _IssuerError("candidate_contract_ineligible")
            if not admission.active():
                raise _IssuerError("admission_expired_during_run")
        audit_state.update(
            status="CANDIDATE_EVIDENCE_COMPLETE", reason="read_only_candidate_complete"
        )
    except _IssuerError as error:
        audit_state.update(
            status="BLOCKED",
            reason=error.args[0] if error.args else "candidate_incomplete",
        )
        if private_paths is not None:
            try:
                _persist_private_audit(
                    private_paths,
                    helpers,
                    _audit_document(
                        owner,
                        helpers,
                        private_paths,
                        status=audit_state["status"],
                        reason=audit_state["reason"],
                        config_sha256=audit_state.get("config_sha256", ""),
                        projection_sha256=audit_state.get("projection_sha256", ""),
                        selected_index=audit_state.get("selected_index"),
                        account_scope_sha256=audit_state.get("account_scope_sha256", ""),
                        credential_binding_sha256=audit_state.get("credential_binding_sha256", ""),
                        process=audit_state.get("process"),
                        artifacts=audit_state.get("artifacts"),
                        validation=audit_state.get("validation"),
                        worker_progress=audit_state.get("worker_progress"),
                        fresh_pair_selection=audit_state.get("fresh_pair_selection"),
                        pair_binding=audit_state.get("pair_binding"),
                        admission=admission,
                    ),
                )
            except Exception:
                pass
        raise
    except Exception:
        audit_state.update(status="BLOCKED", reason="candidate_internal_error")
        if private_paths is not None:
            try:
                _persist_private_audit(
                    private_paths,
                    helpers,
                    _audit_document(
                        owner,
                        helpers,
                        private_paths,
                        status="BLOCKED",
                        reason="candidate_internal_error",
                        config_sha256=audit_state.get("config_sha256", ""),
                        projection_sha256=audit_state.get("projection_sha256", ""),
                        selected_index=audit_state.get("selected_index"),
                        account_scope_sha256=audit_state.get("account_scope_sha256", ""),
                        credential_binding_sha256=audit_state.get("credential_binding_sha256", ""),
                        process=audit_state.get("process"),
                        artifacts=audit_state.get("artifacts"),
                        validation=audit_state.get("validation"),
                        worker_progress=audit_state.get("worker_progress"),
                        fresh_pair_selection=audit_state.get("fresh_pair_selection"),
                        pair_binding=audit_state.get("pair_binding"),
                        admission=admission,
                    ),
                )
            except Exception:
                pass
        raise _IssuerError("candidate_internal_error") from None

    if private_paths is None:
        raise _IssuerError("private_run_root_missing")
    try:
        _persist_private_audit(
            private_paths,
            helpers,
            _audit_document(
                owner,
                helpers,
                private_paths,
                status="CANDIDATE_EVIDENCE_COMPLETE",
                reason="read_only_candidate_complete",
                config_sha256=audit_state["config_sha256"],
                projection_sha256=audit_state["projection_sha256"],
                selected_index=audit_state["selected_index"],
                account_scope_sha256=audit_state["account_scope_sha256"],
                credential_binding_sha256=audit_state["credential_binding_sha256"],
                process=audit_state["process"],
                artifacts=audit_state["artifacts"],
                validation=audit_state["validation"],
                worker_progress=audit_state.get("worker_progress"),
                fresh_pair_selection=audit_state.get("fresh_pair_selection"),
                pair_binding=audit_state.get("pair_binding"),
                admission=admission,
            ),
        )
    except _IssuerError:
        raise _IssuerError("issuer_audit_persist_failed") from None
    return "read_only_candidate_complete"


def run_c01_native_td_read_v3() -> C01NativeTdReadV3Result:
    """Run the explicit C01 native TD read profile in this current process.

    No inputs are accepted from a caller.  Every successful decision is based
    on a fresh pinned worker invocation, parent-observed Windows Job facts,
    owner-only current artifacts, and frozen contract recomputation.
    """

    if not _ISSUER_LOCK.acquire(blocking=False):
        return _blocked("issuer_already_running")
    owner = None
    started = time.monotonic()
    deadline = started + MAX_PROFILE_SECONDS
    try:
        if not _SHA256_RE.fullmatch(globals().get("__c01_source_sha256__", "")):
            return _blocked("fixed_source_bootstrap_required")
        root = _repo_root()
        issuer_module = sys.modules.get(__name__)
        if issuer_module is None or issuer_module.__dict__ is not globals():
            raise _IssuerError("fixed_source_bootstrap_required")
        with _profile_admission_lease(root, issuer_module) as admission:
            # The one-shot registration is durable before environment,
            # interpreter, profile, worker, SDK, config, or credential reads.
            _require_clean_ambient_secrets()
            if not admission.active():
                raise _IssuerError("admission_expired_during_run")
            if not _consumer_matches():
                raise _IssuerError("approved_cpython311_consumer_required")
            _verify_public_profile_sources(root)
            owner = _load_frozen_owner(root)
            _verify_source_manifest(root, owner)
            with owner._verified_helper_bundle() as helpers:
                helpers = dict(helpers)
                helpers["owner_now_utc"] = owner._now_utc
                if time.monotonic() >= deadline:
                    raise _IssuerError("issuer_deadline_exceeded")
                reason = _run_candidate(
                    owner,
                    helpers,
                    deadline=deadline,
                    admission=admission,
                )
                if reason != "read_only_candidate_complete":
                    raise _IssuerError("candidate_contract_ineligible")
                if not admission.active():
                    raise _IssuerError("admission_expired_during_run")
        return C01NativeTdReadV3Result(
            "PASS", "read_only_candidate_complete", _factory=_RESULT_FACTORY
        )
    except _IssuerError as error:
        return _blocked(error.args[0] if error.args else "issuer_blocked")
    except Exception:
        return _blocked("issuer_internal_error")
    finally:
        if owner is not None and sys.modules.get(_OWNER_MODULE_NAME) is owner:
            sys.modules.pop(_OWNER_MODULE_NAME, None)
        _ISSUER_LOCK.release()


__all__ = [
    "CASE_ID",
    "PROFILE_CONTRACT_SHA256",
    "PROFILE_ID",
    "C01NativeTdReadV3Result",
    "run_c01_native_td_read_v3",
]
