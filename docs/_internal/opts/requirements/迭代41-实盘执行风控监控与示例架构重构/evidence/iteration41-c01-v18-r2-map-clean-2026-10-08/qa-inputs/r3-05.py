"""Current-invocation owner for the unregistered SimNow C01 read-only candidate.

This module has no import-time filesystem, network, SDK, or provider behavior.
The public owner entry is permanently ``BLOCKED``. The fixed V3 issuer compiles
this module's exact pinned helpers inside its own current invocation; saved
worker frames and snapshots are never accepted as inputs.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.machinery
import json
import os
from pathlib import Path
import re
import struct
import sys
import threading
import time
from types import MappingProxyType, ModuleType
from typing import Any, Iterator, Mapping


MAX_OWNER_SECONDS = 90.0
MAX_CLEANUP_SECONDS = 5.0
MAX_ENV_BYTES = 64 * 1024
MAX_TREE_ENTRIES = 4096
MAX_TREE_DEPTH = 16
_SAFE_REASON = re.compile(r"[a-z0-9_:-]{1,96}\Z")
_PROGRESS_FILE_RE = re.compile(r"progress-([0-9]{3})\.json\Z")
_MAX_PROGRESS_FILES = 128
# Fixed local software identifier for CTP UserProductInfo, not an account
# credential, AppID/AuthCode substitute, or provider-approved identity.
_PRODUCT_INFO = "bt-i41c01"

# These are review identifiers for the exact source bytes this owner compiles.
# They are not a deployment trust root; the owner stays unregistered and has no
# PASS route until an external protected admission binds this new source too.
_SOURCE_PINS = MappingProxyType(
    {
        "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py": (
            "a38d00ecfbc7a777edab4b9d090be49ef03a94e7c23340dfe95366bacfd05494"
        ),
        "backtrader_runtime/certification_simnow_c01_native_v2.py": (
            "9a24ef954a4e192ae2879e657613ff5ca7b1cdf5d7ee116d9e28fbef9d70ce91"
        ),
        "backtrader_runtime/certification_simnow_c01_dependencies_v1.json": (
            "7cb851df481066ee7622aea0bdd87863d6e04d3372fb520e7685a241411f2324"
        ),
        "backtrader_runtime/certification_simnow_c01_v2_protocol.py": (
            "fa1028021a903fdc5602caf1e7375c6f4eb76e46ffbb819ea057b97ef048fc88"
        ),
        "backtrader_runtime/certification_simnow_c01_v2_contract.py": (
            "3892af9a87ab424ceea896f9ebcbc1608515ead5e9d5c89a21ea823ff32de20c"
        ),
        "backtrader_runtime/certification_simnow_c01_v2_supervisor.py": (
            "4975fbdf8fbe8c7174a92f9f26069b65bbfac0021666fb6bcb6577819a340555"
        ),
        "backtrader_runtime/certification_roundtrip_private.py": (
            "b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd"
        ),
        "backtrader_runtime/certification_binance_roundtrip_r3_cli.py": (
            "62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76"
        ),
        "backtrader_runtime/ctp_front_pair_probe.py": (
            "d6f92c7d2f6df13480cebcee2c7f864ac305d34d4cda37d1a22c466932d2905f"
        ),
        "scripts/ctp_000_render_config.py": (
            "34bf2a99872f43f0d915bafcb0284827a8ac0c4baf70a2ce5f1046888223eac9"
        ),
        "scripts/ctp_000_paired_front_selector.py": (
            "08d4025684503ba89c286699ad0511793c536e09af58333963cbecb40ad49ebb"
        ),
        "scripts/ctp_000_front_handoff.py": (
            "b08e70e723a5d31f18809129387455dfee3645e6ad9f2b516d7aa2789ffd19f7"
        ),
        "scripts/ctp_i13_i15_outer_watchdog.py": (
            "31c945c77c7e147a296e66f4f1ec075e0a23f1a88b94fd339884268e79ca251c"
        ),
        "scripts/ctp_i13_i15_windows_job_backend.py": (
            "2566dd55d1a96285473850b1e2c63174696347da56e07d69fb72aa3a6285e381"
        ),
    }
)

_MODULE_PATHS = MappingProxyType(
    {
        "backtrader_runtime.certification_simnow_c01_interpreter_binding_v1": (
            "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py"
        ),
        "backtrader_runtime.certification_simnow_c01_v2_protocol": (
            "backtrader_runtime/certification_simnow_c01_v2_protocol.py"
        ),
        "backtrader_runtime.certification_simnow_c01_v2_contract": (
            "backtrader_runtime/certification_simnow_c01_v2_contract.py"
        ),
        "backtrader_runtime.certification_simnow_c01_v2_supervisor": (
            "backtrader_runtime/certification_simnow_c01_v2_supervisor.py"
        ),
        "backtrader_runtime.certification_roundtrip_private": (
            "backtrader_runtime/certification_roundtrip_private.py"
        ),
        "backtrader_runtime.certification_binance_roundtrip_r3_cli": (
            "backtrader_runtime/certification_binance_roundtrip_r3_cli.py"
        ),
        "backtrader_runtime.ctp_front_pair_probe": "backtrader_runtime/ctp_front_pair_probe.py",
        "scripts.ctp_000_render_config": "scripts/ctp_000_render_config.py",
        "scripts.ctp_000_paired_front_selector": "scripts/ctp_000_paired_front_selector.py",
        "scripts.ctp_000_front_handoff": "scripts/ctp_000_front_handoff.py",
        "scripts.ctp_i13_i15_outer_watchdog": "scripts/ctp_i13_i15_outer_watchdog.py",
        "scripts.ctp_i13_i15_windows_job_backend": "scripts/ctp_i13_i15_windows_job_backend.py",
    }
)

_ENV_NAMES = frozenset(
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
_CREDENTIAL_LIMITS = MappingProxyType(
    {
        "broker_id": 10,
        "user_id": 15,
        "password": 40,
        "app_id": 32,
        "auth_code": 16,
        "product_info": 10,
    }
)

_BUNDLE_LOCK = threading.Lock()
_MISSING = object()


class _OwnerError(ValueError):
    """Fixed local failure category, with no paths or credential text."""


@dataclass(frozen=True, repr=False)
class _Credentials:
    broker_id: str
    user_id: str
    password: str
    app_id: str
    auth_code: str
    product_info: str
    md_front: str
    td_front: str

    def __repr__(self) -> str:
        return "_Credentials(<redacted>)"


@dataclass(frozen=True, repr=False)
class _PrivateRun:
    root: Any
    native_flow: Any
    evidence: Any

    def __repr__(self) -> str:
        return "_PrivateRun(<owner-only paths redacted>)"


@dataclass(frozen=True, repr=False)
class C01CurrentOwnerResult:
    """Value-free public observation; a current local result is always blocked."""

    status: str
    reason: str
    worker_process_complete: bool

    def __post_init__(self) -> None:
        if self.status != "BLOCKED" or not _SAFE_REASON.fullmatch(self.reason):
            raise ValueError("c01_owner_result_must_be_blocked")

    def __repr__(self) -> str:
        return "C01CurrentOwnerResult(status='BLOCKED', reason={!r}, worker_process_complete={})".format(
            self.reason, self.worker_process_complete
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "BLOCKED",
            "reason": self.reason,
            "worker_process_complete": self.worker_process_complete,
        }


def _blocked(reason: str, *, worker_process_complete: bool = False) -> C01CurrentOwnerResult:
    safe = (
        reason if type(reason) is str and _SAFE_REASON.fullmatch(reason) else "owner_internal_error"
    )
    return C01CurrentOwnerResult("BLOCKED", safe, worker_process_complete)


def _repo_root() -> Path:
    try:
        path = Path(__file__).resolve(strict=True).parents[1]
    except Exception:
        raise _OwnerError("owner_source_unavailable") from None
    if not path.is_absolute() or not path.is_dir():
        raise _OwnerError("owner_source_unavailable")
    return path


def _source_is_regular(path: Path) -> bool:
    try:
        info = path.lstat()
        attributes = getattr(info, "st_file_attributes", 0)
        return (
            path.is_absolute()
            and not path.is_symlink()
            and not attributes & 0x400
            and path.is_file()
        )
    except OSError:
        return False


def _read_source_bundle(root: Path) -> dict[str, bytes]:
    if set(_SOURCE_PINS.values()) == {""}:
        raise _OwnerError("source_pin_missing")
    bundle: dict[str, bytes] = {}
    for relative, expected in _SOURCE_PINS.items():
        if not expected:
            continue
        path = root / Path(relative)
        if not _source_is_regular(path):
            raise _OwnerError("source_bundle_unavailable")
        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                raise _OwnerError("source_bundle_size_invalid")
            with path.open("rb") as stream:
                raw = stream.read(8 * 1024 * 1024 + 1)
        except _OwnerError:
            raise
        except Exception:
            raise _OwnerError("source_bundle_unavailable") from None
        if len(raw) > 8 * 1024 * 1024:
            raise _OwnerError("source_bundle_size_invalid")
        if hashlib.sha256(raw).hexdigest() != expected:
            raise _OwnerError("source_bundle_pin_mismatch")
        bundle[relative] = raw
    if set(bundle) != {path for path, pin in _SOURCE_PINS.items() if pin}:
        raise _OwnerError("source_bundle_incomplete")
    return bundle


def _expected_package_path(root: Path, package_name: str) -> Path:
    return root / Path(*package_name.split("."))


def _ensure_package(
    root: Path,
    name: str,
    *,
    saved_modules: dict[str, Any],
    saved_attributes: dict[tuple[str, str], Any],
) -> ModuleType:
    expected = _expected_package_path(root, name).resolve(strict=True)
    module = sys.modules.get(name)
    if module is None:
        module = ModuleType(name)
        module.__package__ = name
        module.__path__ = [str(expected)]  # type: ignore[attr-defined]
        module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
        saved_modules.setdefault(name, _MISSING)
        sys.modules[name] = module
        return module
    paths = getattr(module, "__path__", None)
    if paths is None:
        raise _OwnerError("module_package_binding_mismatch")
    try:
        observed = tuple(Path(value).resolve(strict=True) for value in paths)
    except Exception:
        raise _OwnerError("module_package_binding_mismatch") from None
    if observed != (expected,):
        raise _OwnerError("module_package_binding_mismatch")
    return module


@contextmanager
def _verified_helper_bundle() -> Iterator[Mapping[str, Any]]:
    """Compile helper modules from the exact pinned bytes, then restore imports."""

    if not _BUNDLE_LOCK.acquire(blocking=False):
        raise _OwnerError("owner_already_running")
    saved_modules: dict[str, Any] = {}
    saved_attributes: dict[tuple[str, str], Any] = {}
    try:
        root = _repo_root()
        bundle = _read_source_bundle(root)
        runtime = _ensure_package(
            root,
            "backtrader_runtime",
            saved_modules=saved_modules,
            saved_attributes=saved_attributes,
        )
        scripts = _ensure_package(
            root,
            "scripts",
            saved_modules=saved_modules,
            saved_attributes=saved_attributes,
        )
        del runtime, scripts
        modules: dict[str, ModuleType] = {}
        for name, relative in _MODULE_PATHS.items():
            raw = bundle.get(relative)
            if type(raw) is not bytes:
                raise _OwnerError("source_bundle_incomplete")
            prior = sys.modules.get(name, _MISSING)
            saved_modules.setdefault(name, prior)
            parent_name, _, child_name = name.rpartition(".")
            parent = sys.modules.get(parent_name)
            if not isinstance(parent, ModuleType):
                raise _OwnerError("module_package_binding_mismatch")
            attr_key = (parent_name, child_name)
            saved_attributes.setdefault(attr_key, getattr(parent, child_name, _MISSING))
            module = ModuleType(name)
            module.__file__ = str(root / Path(relative))
            module.__package__ = parent_name
            module.__loader__ = None
            module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None)
            sys.modules[name] = module
            setattr(parent, child_name, module)
            try:
                code = compile(raw, module.__file__, "exec", dont_inherit=True)
                exec(code, module.__dict__, module.__dict__)
            except Exception:
                raise _OwnerError("source_bundle_compile_failed") from None
            modules[name] = module
        aliases = {
            "interpreter_binding": modules[
                "backtrader_runtime.certification_simnow_c01_interpreter_binding_v1"
            ],
            "protocol": modules["backtrader_runtime.certification_simnow_c01_v2_protocol"],
            "contract": modules["backtrader_runtime.certification_simnow_c01_v2_contract"],
            "supervisor": modules["backtrader_runtime.certification_simnow_c01_v2_supervisor"],
            "private": modules["backtrader_runtime.certification_roundtrip_private"],
            "r3_cli": modules["backtrader_runtime.certification_binance_roundtrip_r3_cli"],
            "probe": modules["backtrader_runtime.ctp_front_pair_probe"],
            "renderer": modules["scripts.ctp_000_render_config"],
            "selector": modules["scripts.ctp_000_paired_front_selector"],
            "handoff": modules["scripts.ctp_000_front_handoff"],
            "job_backend": modules["scripts.ctp_i13_i15_windows_job_backend"],
            "watchdog": modules["scripts.ctp_i13_i15_outer_watchdog"],
        }
        yield MappingProxyType(aliases)
    finally:
        for (parent_name, child_name), value in reversed(tuple(saved_attributes.items())):
            parent = sys.modules.get(parent_name)
            if isinstance(parent, ModuleType):
                if value is _MISSING:
                    try:
                        delattr(parent, child_name)
                    except AttributeError:
                        pass
                else:
                    setattr(parent, child_name, value)
        for name, value in reversed(tuple(saved_modules.items())):
            if value is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value
        _BUNDLE_LOCK.release()


def _validate_text(value: Any, maximum: int) -> str:
    if type(value) is not str or not value:
        raise _OwnerError("credential_value_invalid")
    try:
        raw = value.encode("ascii")
    except UnicodeError:
        raise _OwnerError("credential_value_invalid") from None
    if len(raw) > maximum or any(byte < 0x20 or byte == 0x7F for byte in raw):
        raise _OwnerError("credential_value_invalid")
    return value


def _credentials_from_env_values(values: Mapping[str, Any]) -> _Credentials:
    if not isinstance(values, Mapping) or set(values) != set(_ENV_NAMES):
        raise _OwnerError("explicit_env_fields_invalid")
    credentials = _Credentials(
        broker_id=_validate_text(values["CTP_BROKER_ID"], 10),
        user_id=_validate_text(values["SIMNOW_USER_ID"], 15),
        password=_validate_text(values["SIMNOW_PASSWORD"], 40),
        app_id=_validate_text(values["CTP_APP_ID"], 32),
        auth_code=_validate_text(values["CTP_AUTH_CODE"], 16),
        product_info=_PRODUCT_INFO,
        md_front=_validate_text(values["CTP_MD_FRONT"], 128),
        td_front=_validate_text(values["CTP_TD_FRONT"], 128),
    )
    return credentials


@contextmanager
def _credential_lease(helpers: Mapping[str, Any], repo_root: Path) -> Iterator[_Credentials]:
    """Read the explicit ignored root .env under a retained read-only handle."""

    private = helpers["private"]
    r3_cli = helpers["r3_cli"]
    renderer = helpers["renderer"]
    env_path = repo_root / ".env"
    api = private._api()
    try:
        with ExitStack() as stack:
            stack.enter_context(r3_cli._require_ignored_env(env_path, private))
            stack.enter_context(r3_cli._credential_ancestor_locks(env_path, private))
            handle, _identity = stack.enter_context(
                r3_cli._locked_readonly_file(env_path, private, api)
            )
            raw = r3_cli._read_bounded_handle(api, handle, MAX_ENV_BYTES)
            values = renderer._parse_env_file(raw, _ENV_NAMES)
            credentials = _credentials_from_env_values(values)
            yield credentials
    except _OwnerError:
        raise
    except Exception:
        raise _OwnerError("explicit_ignored_env_unavailable") from None


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _select_pair_binding(
    helpers: Mapping[str, Any], credentials: _Credentials, *, deadline: float
) -> Any:
    if time.monotonic() >= deadline:
        raise _OwnerError("owner_deadline_exceeded")
    selector = helpers["selector"]
    handoff_module = helpers["handoff"]
    protocol = helpers["protocol"]
    document = {
        "schema": selector.SCHEMA,
        "venue": "simnow",
        "scope": "transport_only",
        "strategy_id": selector.STRATEGY,
        "front_pairs": [{"md_front": credentials.md_front, "td_front": credentials.td_front}],
    }
    try:
        projection = json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("ascii")
        selector.parse_document(projection)
        handoff = handoff_module.create_current_handoff(projection, confirm_transport_only=True)
        selected = handoff.consume(projection)
    except Exception:
        raise _OwnerError("fresh_pair_selection_unavailable") from None
    selection_type = getattr(handoff_module, "SelectedFrontPair", None)
    if (
        type(selected) is not selection_type
        or selected.config_index != 0
        or selected.md_front != credentials.md_front
        or selected.td_front != credentials.td_front
        or type(selected.degraded_candidate) is not bool
        or selected.execution_authority != "NONE"
        or selected.public_projection_sha256 != hashlib.sha256(projection).hexdigest()
        or time.monotonic() >= deadline
    ):
        raise _OwnerError("fresh_pair_binding_invalid")
    try:
        binding = protocol.C01PairBinding(
            selected_index=selected.config_index,
            selection_sha256=selected.observation_sha256,
            md_front_sha256=hashlib.sha256(selected.md_front.encode("utf-8")).hexdigest(),
            td_front_sha256=hashlib.sha256(selected.td_front.encode("utf-8")).hexdigest(),
            td_front=selected.td_front,
            selected_at_utc=_now_utc(),
        )
        if type(binding) is not protocol.C01PairBinding:
            raise ValueError("pair_binding_type_invalid")
        return binding
    except Exception:
        raise _OwnerError("fresh_pair_binding_invalid") from None


def _directory_entries(path: Path) -> tuple[Path, ...]:
    try:
        entries = tuple(path.iterdir())
        if len(entries) > MAX_TREE_ENTRIES:
            raise _OwnerError("private_tree_entry_limit")
        for entry in entries:
            info = entry.lstat()
            if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                raise _OwnerError("private_tree_reparse_rejected")
        return entries
    except _OwnerError:
        raise
    except Exception:
        raise _OwnerError("private_tree_unavailable") from None


@contextmanager
def _private_run(helpers: Mapping[str, Any]) -> Iterator[_PrivateRun]:
    """Create and retain a new owner-only root plus exactly two empty children."""

    private = helpers["private"]
    stack = ExitStack()

    def close_preserving_exception() -> None:
        try:
            stack.close()
        except BaseException:
            pass

    try:
        local_app_data = Path(helpers["r3_cli"]._known_local_app_data())
        root_path = private._path(local_app_data / ("simnow-c01-" + os.urandom(16).hex()))
        stack.enter_context(private._ancestors(root_path))
        root = private.create_private_directory(root_path)
        native_flow = private.create_private_directory(root_path / "native-flow")
        evidence = private.create_private_directory(root_path / "evidence")
        root.verify()
        native_flow.verify()
        evidence.verify()
        api = private._api()
        sid = api.current_sid()
        for artifact_dir in (root, native_flow, evidence):
            handle = stack.enter_context(api.opened(artifact_dir.path, directory=True))
            api.verify_acl(handle, sid, directory=True)
            if api.info(handle, directory=True) != (artifact_dir.device, artifact_dir.inode):
                raise _OwnerError("private_directory_identity_changed")
        if {item.name for item in _directory_entries(root.path)} != {
            "native-flow",
            "evidence",
        }:
            raise _OwnerError("private_run_root_not_fresh")
        if _directory_entries(native_flow.path) or _directory_entries(evidence.path):
            raise _OwnerError("private_run_children_not_empty")
    except _OwnerError:
        close_preserving_exception()
        raise
    except Exception:
        close_preserving_exception()
        raise _OwnerError("private_run_directory_unavailable") from None
    except BaseException:
        close_preserving_exception()
        raise

    try:
        yield _PrivateRun(root, native_flow, evidence)
    except BaseException:
        close_preserving_exception()
        raise

    try:
        root.verify()
        native_flow.verify()
        evidence.verify()
    except _OwnerError:
        close_preserving_exception()
        raise
    except Exception:
        close_preserving_exception()
        raise _OwnerError("private_run_directory_unavailable") from None
    except BaseException:
        close_preserving_exception()
        raise
    try:
        stack.close()
    except Exception:
        raise _OwnerError("private_run_directory_unavailable") from None


def _private_input_packet(
    helpers: Mapping[str, Any], credentials: _Credentials, paths: _PrivateRun
) -> tuple[bytes, str, str]:
    protocol = helpers["protocol"]
    try:
        account_digest = protocol.compute_account_scope_sha256(
            credentials.broker_id, credentials.user_id
        )
        credential_digest = protocol.compute_credential_binding_sha256(
            credentials.broker_id,
            credentials.user_id,
            credentials.password,
            credentials.app_id,
            credentials.auth_code,
            credentials.product_info,
        )
        private_input = protocol.C01PrivateInput(
            broker_id=credentials.broker_id,
            user_id=credentials.user_id,
            password=credentials.password,
            app_id=credentials.app_id,
            auth_code=credentials.auth_code,
            product_info=credentials.product_info,
            native_flow_directory=str(paths.native_flow.path),
            evidence_directory=str(paths.evidence.path),
        )
        packet = protocol.encode_private_input_packet(private_input)
    except Exception:
        raise _OwnerError("private_worker_packet_invalid") from None
    return packet, account_digest, credential_digest


def _worker_process_complete(helpers: Mapping[str, Any], supervisor_result: Any) -> bool:
    try:
        if type(supervisor_result) is not helpers["supervisor"].C01SupervisorResult:
            return False
        lifecycle = supervisor_result.process_lifecycle
        if supervisor_result.reason == "candidate_transport_complete":
            if type(supervisor_result.worker_receipt) is not helpers["protocol"].C01WorkerReceipt:
                return False
        elif supervisor_result.reason in {
            "diagnostic_profile_only",
            "diagnostic_intent_stream_invalid",
        }:
            if supervisor_result.worker_receipt is not None:
                return False
        else:
            return False
        return (
            type(lifecycle) is helpers["protocol"].C01ProcessLifecycleReceipt
            and supervisor_result.status == "BLOCKED"
            and lifecycle.status == "BLOCKED"
            and lifecycle.containment == "windows_job"
            and lifecycle.assigned_before_resume is True
            and lifecycle.stdin_fully_sent is True
            and lifecycle.stdout_eof is True
            and lifecycle.stderr_eof is True
            and lifecycle.process_exit_observed is True
            and lifecycle.process_exit_code == 0
            and lifecycle.job_active_count == 0
            and lifecycle.handles_closed is True
            and lifecycle.timed_out is False
            and lifecycle.forced_kill is False
            and type(lifecycle.worker_pid) is int
            and lifecycle.worker_pid > 0
            and type(lifecycle.worker_source_sha256) is str
        )
    except Exception:
        return False


def _worker_receipt_matches(
    helpers: Mapping[str, Any],
    supervisor_result: Any,
    pair_binding: Any,
    account_digest: str,
    credential_digest: str,
) -> bool:
    try:
        receipt = supervisor_result.worker_receipt
        lifecycle = supervisor_result.process_lifecycle
        return (
            type(receipt) is helpers["protocol"].C01WorkerReceipt
            and receipt.run_nonce == lifecycle.run_nonce
            and receipt.parent_pid == os.getpid()
            and receipt.parent_pid == lifecycle.parent_pid
            and receipt.worker_pid == lifecycle.worker_pid
            and receipt.worker_source_sha256
            == _SOURCE_PINS["backtrader_runtime/certification_simnow_c01_native_v2.py"]
            and lifecycle.worker_source_sha256 == receipt.worker_source_sha256
            and receipt.pair_binding == pair_binding.to_receipt_ref()
            and receipt.account_scope_sha256 == account_digest
            and receipt.credential_binding_sha256 == credential_digest
        )
    except Exception:
        return False


def _verify_tree(
    helpers: Mapping[str, Any], paths: _PrivateRun, *, expected_snapshots: bool
) -> None:
    private = helpers["private"]
    api = private._api()
    sid = api.current_sid()
    count = 0

    def walk(directory: Path, *, depth: int, inherited: bool) -> None:
        nonlocal count
        if depth > MAX_TREE_DEPTH:
            raise _OwnerError("private_tree_depth_limit")
        entries = _directory_entries(directory)
        for path in entries:
            count += 1
            if count > MAX_TREE_ENTRIES:
                raise _OwnerError("private_tree_entry_limit")
            is_directory = path.is_dir()
            try:
                with api.opened(path, directory=is_directory) as handle:
                    api.verify_acl(
                        handle,
                        sid,
                        directory=is_directory,
                        inherited=inherited if not is_directory else inherited,
                    )
            except _OwnerError:
                raise
            except Exception:
                raise _OwnerError("private_tree_acl_or_identity_invalid") from None
            if is_directory:
                walk(path, depth=depth + 1, inherited=True)

    try:
        paths.root.verify()
        paths.native_flow.verify()
        paths.evidence.verify()
        if {item.name for item in _directory_entries(paths.root.path)} != {
            "native-flow",
            "evidence",
        }:
            raise _OwnerError("private_run_root_changed")
        evidence_entries = _directory_entries(paths.evidence.path)
        evidence_names = {item.name for item in evidence_entries}
        progress_entries = [
            item for item in evidence_entries if _PROGRESS_FILE_RE.fullmatch(item.name)
        ]
        if (
            any(
                item.name != "snapshots" and item not in progress_entries
                for item in evidence_entries
            )
            or len(progress_entries) > _MAX_PROGRESS_FILES
            or not progress_entries
            or "snapshots" not in evidence_names
        ):
            raise _OwnerError("private_evidence_shape_invalid")
        progress_sequences = [
            int(_PROGRESS_FILE_RE.fullmatch(item.name).group(1)) for item in progress_entries
        ]
        if sorted(progress_sequences) != list(range(1, len(progress_entries) + 1)):
            raise _OwnerError("private_progress_sequence_invalid")
        snapshot_dir = paths.evidence.path / "snapshots"
        if not snapshot_dir.is_dir() or snapshot_dir.is_symlink():
            raise _OwnerError("private_snapshot_directory_invalid")
        with api.opened(snapshot_dir, directory=True) as handle:
            api.verify_acl(handle, sid, directory=True)
        if expected_snapshots and {item.name for item in _directory_entries(snapshot_dir)} != {
            "baseline.json",
            "final.json",
        }:
            raise _OwnerError("private_snapshot_shape_invalid")
        if not expected_snapshots and _directory_entries(paths.evidence.path):
            raise _OwnerError("private_evidence_unexpected")
        walk(paths.native_flow.path, depth=0, inherited=True)
        walk(paths.evidence.path, depth=0, inherited=True)
    except _OwnerError:
        raise
    except Exception:
        raise _OwnerError("private_tree_verification_failed") from None


def _read_snapshot_artifacts(helpers: Mapping[str, Any], paths: _PrivateRun) -> dict[str, bytes]:
    private = helpers["private"]
    r3_cli = helpers["r3_cli"]
    protocol = helpers["protocol"]
    api = private._api()
    sid = api.current_sid()
    artifacts: dict[str, bytes] = {}
    try:
        for name in ("baseline", "final"):
            relative = "snapshots/{}.json".format(name)
            path = paths.evidence.path / relative.replace("/", os.sep)
            with r3_cli._locked_readonly_file(path, private, api) as (handle, _identity):
                api.verify_acl(handle, sid, directory=False)
                payload = r3_cli._read_bounded_handle(
                    api, handle, protocol.MAX_PRIVATE_SNAPSHOT_BYTES
                )
            if not payload or len(payload) > protocol.MAX_PRIVATE_SNAPSHOT_BYTES:
                raise _OwnerError("private_snapshot_size_invalid")
            artifacts[relative] = payload
    except _OwnerError:
        raise
    except Exception:
        raise _OwnerError("private_snapshot_read_failed") from None
    if set(artifacts) != {"snapshots/baseline.json", "snapshots/final.json"}:
        raise _OwnerError("private_snapshot_shape_invalid")
    return artifacts


def _validation_acceptable(helpers: Mapping[str, Any], validation: Any) -> bool:
    try:
        return (
            type(validation) is helpers["protocol"].C01CandidateValidation
            and type(validation.status) is str
            and validation.status == "BLOCKED"
            and type(validation.eligible_for_protected_admission) is bool
        )
    except Exception:
        return False


def _run_supervised_candidate(
    helpers: Mapping[str, Any],
    credentials: _Credentials,
    paths: _PrivateRun,
    pair_binding: Any,
    *,
    deadline: float,
) -> tuple[bool, str]:
    contract = helpers["contract"]
    supervisor = helpers["supervisor"]
    if type(pair_binding) is not helpers["protocol"].C01PairBinding:
        return False, "fresh_pair_binding_invalid"
    packet, account_digest, credential_digest = _private_input_packet(helpers, credentials, paths)
    remaining = deadline - time.monotonic()
    if remaining < 0.01:
        return False, "owner_deadline_exceeded"
    worker_path = _repo_root() / "backtrader_runtime" / "certification_simnow_c01_native_v2.py"
    source_root = worker_path.parent
    try:
        result = supervisor.run_fixed_c01_worker(
            worker_path=worker_path,
            source_root=source_root,
            expected_worker_source_sha256=_SOURCE_PINS[
                "backtrader_runtime/certification_simnow_c01_native_v2.py"
            ],
            pair_binding=pair_binding,
            account_scope_sha256=account_digest,
            credential_binding_sha256=credential_digest,
            credential_packet=packet,
            timeout_seconds=min(MAX_OWNER_SECONDS, remaining),
            cleanup_seconds=MAX_CLEANUP_SECONDS,
        )
    except Exception:
        return False, "worker_supervisor_failed"
    if not _worker_process_complete(helpers, result):
        if getattr(getattr(result, "process_lifecycle", None), "timed_out", False):
            return False, "native_close_unknown"
        return False, "worker_process_incomplete"
    if time.monotonic() >= deadline:
        return True, "owner_deadline_exceeded"
    if not _worker_receipt_matches(
        helpers, result, pair_binding, account_digest, credential_digest
    ):
        return True, "worker_receipt_misbinding"
    try:
        _verify_tree(helpers, paths, expected_snapshots=True)
        artifacts = _read_snapshot_artifacts(helpers, paths)
    except _OwnerError as error:
        return True, error.args[0] if error.args else "private_evidence_unavailable"
    except Exception:
        return True, "private_evidence_unavailable"
    if time.monotonic() >= deadline:
        return True, "owner_deadline_exceeded"
    try:
        validation = contract.validate_c01_candidate(
            result.worker_receipt,
            result.process_lifecycle,
            expected_pair_binding=pair_binding,
            expected_worker_source_sha256=_SOURCE_PINS[
                "backtrader_runtime/certification_simnow_c01_native_v2.py"
            ],
            expected_account_scope_sha256=account_digest,
            expected_credential_binding_sha256=credential_digest,
            private_snapshot_artifacts=artifacts,
            expected_broker_id=credentials.broker_id,
            expected_user_id=credentials.user_id,
        )
    except Exception:
        return True, "candidate_contract_failed"
    if not _validation_acceptable(helpers, validation):
        return True, "candidate_contract_unexpected"
    if time.monotonic() >= deadline:
        return True, "owner_deadline_exceeded"
    if validation.eligible_for_protected_admission is True:
        return True, "protected_admission_required"
    return True, "candidate_validation_ineligible"


def _windows_consumer_supported() -> bool:
    return (
        os.name == "nt"
        and sys.platform == "win32"
        and sys.implementation.name == "cpython"
        and sys.version_info[:3] == (3, 11, 5)
        and struct.calcsize("P") == 8
    )


def run_current_c01_owner() -> C01CurrentOwnerResult:
    """Run one current local C01 read-only candidate; never return PASS.

    This takes no caller-supplied credentials, pair, source pin, receipt,
    artifacts, or eligibility capsule. The only credential source is the
    explicitly ignored checkout-root ``.env`` held read-only through worker
    cleanup. The child receives credentials solely over inherited stdin.
    """

    if not _windows_consumer_supported():
        return _blocked("windows_cpython311_x64_required")
    deadline = time.monotonic() + MAX_OWNER_SECONDS
    try:
        with _verified_helper_bundle() as helpers:
            if not helpers["interpreter_binding"].verify_current_runtime():
                return _blocked("approved_interpreter_binding_required")
            repo_root = _repo_root()
            if time.monotonic() >= deadline:
                raise _OwnerError("owner_deadline_exceeded")
            with ExitStack() as stack:
                credentials = stack.enter_context(_credential_lease(helpers, repo_root))
                paths = stack.enter_context(_private_run(helpers))
                pair_binding = _select_pair_binding(helpers, credentials, deadline=deadline)
                worker_complete, reason = _run_supervised_candidate(
                    helpers,
                    credentials,
                    paths,
                    pair_binding,
                    deadline=deadline,
                )
                return _blocked(reason, worker_process_complete=worker_complete)
    except _OwnerError as error:
        reason = error.args[0] if error.args else "owner_internal_error"
        return _blocked(reason)
    except Exception:
        return _blocked("owner_internal_error")


__all__ = ["C01CurrentOwnerResult", "run_current_c01_owner"]
