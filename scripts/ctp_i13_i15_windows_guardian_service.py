"""One-shot, inert-only Windows AF_PIPE guardian service candidate.

An external supervisor starts this process before any request owner. The
service accepts one mutually authenticated local named-pipe request, admits
only a fixed bounded sleep worker, owns that worker's Job, writes one fixed
receipt, and attempts a response after cleanup. Requests contain no command,
executable, working directory, or output path. This module does not install a
Windows Service, establish a production pipe ACL, access trading configuration,
or import an SDK.
"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import math
import ntpath
import os
from pathlib import Path
import re
import stat
import threading
import time
import uuid
from ctypes import wintypes
from dataclasses import dataclass
from types import MappingProxyType, SimpleNamespace
from typing import Callable, Optional

from scripts.ctp_i13_i15_outer_watchdog import FixedOuterCommand, run_outer_watchdog
from scripts.ctp_i13_i15_windows_guardian import _result_payload, _write_receipt
from scripts.ctp_i13_i15_windows_job_backend import WindowsJobBackend


REQUEST_SCHEMA = "ctp_i13_i15_inert_guardian_request.v1"
RESPONSE_SCHEMA = "ctp_i13_i15_inert_guardian_service_response.v1"
READONLY_REQUEST_SCHEMA = "ctp_i13_i15_readonly_preflight_request.v1"
READONLY_OS_REQUEST_SCHEMA = "ctp_i13_i15_readonly_preflight_os_request.v1"
READONLY_OS_RESPONSE_SCHEMA = "ctp_i13_i15_readonly_preflight_os_response.v2"
READONLY_WORKER_SCHEMA = "ctp_i13_i15_readonly_preflight_worker_output.v1"
READONLY_DEPLOYMENT_SCHEMA = "ctp_i13_i15_readonly_preflight_deployment.v1"
READONLY_SERVICE_RECEIPT_SCHEMA = "ctp_i13_i15_readonly_preflight_service_receipt.v1"
READONLY_BOOTSTRAP_BINDING_SCHEMA = "ctp_i13_i15_readonly_preflight_bootstrap_binding.v2"
READONLY_BOOTSTRAP_BINDING_ENV = "BT_I13_READONLY_BOOTSTRAP_BINDING"
READONLY_MAX_OUTPUT_BYTES = 16 * 1024
_READONLY_OS_RESPONSE_MAX_BYTES = READONLY_MAX_OUTPUT_BYTES + 4096
_PIPE_RE = re.compile(r"\\\\\.\\pipe\\backtrader-ctp-i13-i15-[0-9a-f]{32}\Z")
_REQUEST_ID_RE = re.compile(r"[0-9a-f]{32}\Z")
_READONLY_TRADING_DAY_RE = re.compile(r"[0-9]{8}\Z")
_READONLY_INSTRUMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_READONLY_EXCHANGE_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{0,15}\Z")
_READONLY_RUNTIME_ID = "example.013_3.sa_midfreq_simnow.ctp_private"
_READONLY_STRATEGY_ID = "example.013_3.sa_midfreq_simnow"
_MAX_MESSAGE_BYTES = 4096
_MAX_CHILD_SECONDS = 300.0
_MAX_TOTAL_SECONDS = 310.0
_REPARSE_POINT = 0x400
_TOKEN_QUERY = 0x0008
_TOKEN_DUPLICATE = 0x0002
_TOKEN_ASSIGN_PRIMARY = 0x0001
_TOKEN_ADJUST_SESSIONID = 0x0100
_TOKEN_USER = 1
_TOKEN_GROUPS = 2
_SECURITY_IMPERSONATION = 2
_TOKEN_PRIMARY = 1
_PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
_ERROR_BROKEN_PIPE = 109
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_FLAG_OVERLAPPED = 0x40000000
_HANDLE_FLAG_INHERIT = 0x00000001
_FIXED_READONLY_WORKER_RELATIVE_PATH = "scripts/ctp_i13_i15_readonly_preflight_worker.py"
_FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH = "scripts/ctp_i13_i15_readonly_preflight_bootstrap.py"
_TOKEN_CONTROL_PIPE_PREFIX = r"\\.\pipe\Backtrader-I13-Readonly-Token-v1-"
_READONLY_ACCEPT_TIMEOUT_SECONDS = 600.0
_READONLY_REQUEST_RECEIVE_SECONDS = 15.0
_READONLY_CLEANUP_RESERVE_SECONDS = 10.0
FIXED_SERVICE_NAME = "BacktraderCtpReadonlyGuardian"
FIXED_READONLY_SERVICE_NAME = FIXED_SERVICE_NAME
_UNRELEASED_WINDOWS_HANDLE_OWNERS: list[object] = []
_SERVICE_SID_RE = re.compile(r"S-1-5-80-(?:[0-9]+-){4}[0-9]+\Z")
_SE_GROUP_ENABLED = 0x00000004
_SE_GROUP_USE_FOR_DENY_ONLY = 0x00000010
_READONLY_PIPE_CLIENT_ACCESS = 0x00120183
_FILE_READ_DATA = 0x00000001
_FILE_WRITE_DATA = 0x00000002
_FILE_APPEND_DATA = 0x00000004
_FILE_READ_ATTRIBUTES = 0x00000080
_FILE_WRITE_ATTRIBUTES = 0x00000100
_READ_CONTROL = 0x00020000
_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x00001000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
_FILE_BEGIN = 0
_SC_MANAGER_CONNECT = 0x00000001
_SERVICE_QUERY_STATUS = 0x00000004
_SC_STATUS_PROCESS_INFO = 0
_SERVICE_RUNNING = 4
_SERVICE_WIN32_OWN_PROCESS = 0x00000010
_WAIT_TIMEOUT = 258
_ERROR_IO_PENDING = 997
_ERROR_PIPE_CONNECTED = 535
_ERROR_MORE_DATA = 234
_WAIT_OBJECT_0 = 0


def _native_handle_value(value: object) -> int:
    """Normalize ctypes handles from real WinDLLs and explicit test doubles."""

    if type(value) is int:
        return value
    raw = getattr(value, "value", None)
    if type(raw) is int:
        return raw
    return 0


def _retain_failed_windows_cleanup(owner: object) -> None:
    """Keep failed native-handle custodians alive until this one-shot exits."""

    if not any(existing is owner for existing in _UNRELEASED_WINDOWS_HANDLE_OWNERS):
        _UNRELEASED_WINDOWS_HANDLE_OWNERS.append(owner)


@dataclass
class _NativeHandleCustody:
    """Retryable owner for a raw handle when a higher-level setup fails."""

    handle: int
    kernel32: object

    def close(self) -> bool:
        if self.handle <= 0:
            return True
        try:
            closed = bool(self.kernel32.CloseHandle(wintypes.HANDLE(self.handle)))
        except BaseException:
            closed = False
        if closed:
            self.handle = 0
        return closed


def _windows_system_root() -> str:
    """Read the OS system directory without copying service environment values."""

    if os.name != "nt":
        raise GuardianServiceError("windows_required")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_windows_directory = kernel32.GetWindowsDirectoryW
    get_windows_directory.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    get_windows_directory.restype = wintypes.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    length = int(get_windows_directory(buffer, len(buffer)))
    if length <= 0 or length >= len(buffer):
        raise GuardianServiceError("windows_system_root_unavailable")
    return str(Path(buffer.value))


def _fixed_readonly_worker_command(
    anchor: object, *, deadline_monotonic: float
) -> FixedOuterCommand:
    """Build the fixed bootstrap command from a retained trust anchor.

    The worker source itself is never copied into ``-c`` or a caller-selected
    path.  A separately pinned bootstrap independently establishes the sealed
    source/dependency importers in the child process.  Until that complete
    contract exists, this helper fails closed.
    """

    required = (
        "source_root",
        "source_manifest_sha256",
        "descriptor_sha256",
        "python_executable",
        "python_sha256",
        "i13_pin_sha256",
        "i15_pin_sha256",
        "worker_sha256",
        "worker_dependency_manifest_sha256",
        "runtime_manifest_sha256",
        "dependency_root",
        "dependency_seal",
        "pycache_prefix",
        "bootstrap_relative_path",
        "bootstrap_sha256",
        "read_bootstrap_source",
        "verify_current",
    )
    if any(not hasattr(anchor, name) for name in required):
        raise GuardianServiceError("readonly_bootstrap_binding_invalid")
    source_root = getattr(anchor, "source_root")
    source_manifest_sha256 = getattr(anchor, "source_manifest_sha256")
    descriptor_sha256 = getattr(anchor, "descriptor_sha256")
    python_executable = getattr(anchor, "python_executable")
    python_sha256 = getattr(anchor, "python_sha256")
    i13_pin_sha256 = getattr(anchor, "i13_pin_sha256")
    i15_pin_sha256 = getattr(anchor, "i15_pin_sha256")
    worker_sha256 = getattr(anchor, "worker_sha256")
    dependency_manifest_sha256 = getattr(anchor, "worker_dependency_manifest_sha256")
    runtime_manifest_sha256 = getattr(anchor, "runtime_manifest_sha256")
    dependency_root = getattr(anchor, "dependency_root")
    dependency_seal = getattr(anchor, "dependency_seal")
    pycache_prefix = getattr(anchor, "pycache_prefix")
    bootstrap_relative_path = getattr(anchor, "bootstrap_relative_path")
    bootstrap_sha256 = getattr(anchor, "bootstrap_sha256")
    source_reader = getattr(anchor, "read_bootstrap_source")
    verify_current = getattr(anchor, "verify_current")
    if not callable(verify_current):
        raise GuardianServiceError("readonly_bootstrap_binding_invalid")
    if (
        type(source_root) is not str
        or not Path(source_root).is_absolute()
        or type(python_executable) is not str
        or not Path(python_executable).is_absolute()
        or type(python_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", python_sha256) is None
        or not _is_lower_sha256(source_manifest_sha256)
        or not _is_lower_sha256(descriptor_sha256)
        or not _is_lower_sha256(i13_pin_sha256)
        or not _is_lower_sha256(i15_pin_sha256)
        or type(worker_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", worker_sha256) is None
        or not _is_lower_sha256(dependency_manifest_sha256)
        or not _is_lower_sha256(runtime_manifest_sha256)
        or type(dependency_root) is not str
        or not Path(dependency_root).is_absolute()
        or type(pycache_prefix) is not str
        or not ntpath.isabs(pycache_prefix)
        or "\0" in pycache_prefix
        or dependency_seal is None
        or getattr(dependency_seal, "manifest_sha256", None) != dependency_manifest_sha256
        or getattr(dependency_seal, "dependency_root", None) != dependency_root
        or getattr(dependency_seal, "verify_current", None) is None
        or not callable(getattr(dependency_seal, "verify_current", None))
        or bootstrap_relative_path != _FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH
        or not _is_lower_sha256(bootstrap_sha256)
        or not callable(source_reader)
        or not callable(getattr(dependency_seal, "close", None))
        or type(deadline_monotonic) not in (int, float)
        or not math.isfinite(float(deadline_monotonic))
        or float(deadline_monotonic) <= 0.0
    ):
        raise GuardianServiceError("readonly_bootstrap_binding_invalid")
    try:
        verify_current()
        bootstrap_source = source_reader()
    except BaseException:
        raise GuardianServiceError("readonly_bootstrap_source_unavailable") from None
    if (
        type(bootstrap_source) is not bytes
        or not bootstrap_source
        or len(bootstrap_source) > 256 * 1024
    ):
        raise GuardianServiceError("readonly_bootstrap_source_size_invalid")
    if not hmac.compare_digest(hashlib.sha256(bootstrap_source).hexdigest(), bootstrap_sha256):
        raise GuardianServiceError("readonly_bootstrap_source_digest_invalid")
    deadline_ns = math.floor(float(deadline_monotonic) * 1_000_000_000)
    if type(deadline_ns) is not int or deadline_ns <= 0:
        raise GuardianServiceError("readonly_bootstrap_deadline_invalid")
    binding = {
        "schema": READONLY_BOOTSTRAP_BINDING_SCHEMA,
        "deployment_descriptor_sha256": descriptor_sha256,
        "source_manifest_sha256": source_manifest_sha256,
        "i13_pin_sha256": i13_pin_sha256,
        "i15_pin_sha256": i15_pin_sha256,
        "bootstrap_sha256": bootstrap_sha256,
        "worker_sha256": worker_sha256,
        "dependency_manifest_sha256": dependency_manifest_sha256,
        "runtime_manifest_sha256": runtime_manifest_sha256,
        "python_sha256": python_sha256,
        "deadline_monotonic_ns": deadline_ns,
    }
    binding_bytes = json.dumps(
        binding, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if len(binding_bytes) > 2048:
        raise GuardianServiceError("readonly_bootstrap_binding_too_large")
    executable = Path(python_executable)
    system_root = _windows_system_root()
    bootstrap_path = Path(source_root).joinpath(*bootstrap_relative_path.split("/"))
    command = FixedOuterCommand(
        [
            str(executable),
            "-I",
            "-S",
            "-B",
            "-X",
            "pycache_prefix={}".format(pycache_prefix),
            str(bootstrap_path),
        ],
        source_root,
        {
            "PATH": str(executable.parent),
            "SYSTEMROOT": system_root,
            "WINDIR": system_root,
            READONLY_BOOTSTRAP_BINDING_ENV: binding_bytes.decode("ascii"),
        },
    )
    return command


_READONLY_WORKER_OBSERVATION_FIELDS = frozenset(
    {
        "credentials_resolved",
        "provider_connected",
        "account_identity_verified",
        "preflight_authorized",
        "execution_authorized",
        "external_writes_authorized",
        "order_submission_authorized",
        "cancellation_authorized",
        "settlement_authorized",
        "arming_authorized",
        "external_write_requests",
        "market_data_trading_writes",
        "read_only_observation",
        "market_data_observation",
    }
)
_READONLY_ACCOUNT_FACT_FIELDS = frozenset(
    {
        "account_acceptance_established",
        "account_scope",
        "approval_required",
        "arming_authorized",
        "cancellation_authorized",
        "connection_generation",
        "effective_config_digest",
        "environment",
        "exchange_id",
        "execution_authorized",
        "external_write_requests",
        "external_writes_authorized",
        "hedge_flag",
        "instrument_id",
        "native_certificate_provenance",
        "native_certificate_sha256",
        "order_submission_authorized",
        "provider",
        "provider_preflight_started",
        "query_snapshot",
        "read_only_route_admitted",
        "registration_digest",
        "runtime_id",
        "sdk_profile",
        "session_connected",
        "settlement_authorized",
        "strategy_id",
        "trading_day",
    }
)
_READONLY_MARKET_FACT_FIELDS = frozenset(
    {
        "client_stop_returned",
        "connection_generation",
        "account_probe_lock_scope",
        "account_scope_bound",
        "exchange_id",
        "first_tick_observed",
        "instrument_id",
        "market_login_ready",
        "market_path_ready",
        "md_front_sha256",
        "native_join_pending",
        "order_submission_authorized",
        "probe_session_closed",
        "subscription_acknowledged",
        "settlement_writes",
        "tick_binding",
        "tick_observation_count",
        "trading_writes",
    }
)
_READONLY_TICK_BINDING_FIELDS = frozenset(
    {"account_bound", "connection_generation", "exchange_id", "instrument_id", "md_front_sha256"}
)
_READONLY_QUERY_SNAPSHOT_FIELDS = frozenset({"identity", "query_digests", "snapshot_sha256"})
_READONLY_SESSION_IDENTITY_FIELDS = frozenset(
    {"account_scope", "connection_generation", "environment", "provider", "trading_day"}
)
_READONLY_QUERY_NAMES = frozenset(
    {"account", "positions", "orders", "trades", "instruments", "margin_rates", "commission_rates"}
)
_READONLY_RATE_SCOPE_NAMES = ("commission_rates", "margin_rates")
_READONLY_RATE_SCOPE_VALUES = frozenset({"exact", "unverified"})


def _is_lower_sha256(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _readonly_query_snapshot_is_valid(value: object) -> bool:
    if type(value) is not dict:
        return False
    fields = set(value)
    required = set(_READONLY_QUERY_SNAPSHOT_FIELDS)
    optional = {"native_certificate_sha256", "rate_exchange_scopes"}
    if not required.issubset(fields) or not fields.issubset(required | optional):
        return False
    if not _is_lower_sha256(value.get("snapshot_sha256")):
        return False
    identity = value.get("identity")
    if type(identity) is not dict or set(identity) != _READONLY_SESSION_IDENTITY_FIELDS:
        return False
    if (
        identity.get("account_scope") != "redacted"
        or identity.get("provider") != "ctp"
        or type(identity.get("environment")) is not str
        or re.fullmatch(r"simnow(?:_set[1-9][0-9]*)?", identity["environment"]) is None
        or type(identity.get("trading_day")) is not str
        or _READONLY_TRADING_DAY_RE.fullmatch(identity["trading_day"]) is None
        or type(identity.get("connection_generation")) is not int
        or identity["connection_generation"] <= 0
    ):
        return False
    digests = value.get("query_digests")
    if type(digests) is not list or len(digests) != len(_READONLY_QUERY_NAMES):
        return False
    parsed = []
    for pair in digests:
        if (
            type(pair) is not list
            or len(pair) != 2
            or type(pair[0]) is not str
            or pair[0] not in _READONLY_QUERY_NAMES
            or not _is_lower_sha256(pair[1])
        ):
            return False
        parsed.append(pair[0])
    if parsed != sorted(_READONLY_QUERY_NAMES) or len(set(parsed)) != len(parsed):
        return False
    certificate = value.get("native_certificate_sha256")
    if "native_certificate_sha256" in fields and not _is_lower_sha256(certificate):
        return False
    scopes = value.get("rate_exchange_scopes")
    if "rate_exchange_scopes" in fields:
        if "native_certificate_sha256" not in fields or type(scopes) is not list:
            return False
        if len(scopes) != len(_READONLY_RATE_SCOPE_NAMES):
            return False
        names = []
        for pair in scopes:
            if (
                type(pair) is not list
                or len(pair) != 2
                or type(pair[0]) is not str
                or pair[0] not in _READONLY_RATE_SCOPE_NAMES
                or type(pair[1]) is not str
                or pair[1] not in _READONLY_RATE_SCOPE_VALUES
            ):
                return False
            names.append(pair[0])
        if names != list(_READONLY_RATE_SCOPE_NAMES):
            return False
    elif "native_certificate_sha256" in fields:
        return False
    canonical_facts = {
        "identity": identity,
        "query_digests": digests,
    }
    if "native_certificate_sha256" in fields:
        canonical_facts["native_certificate_sha256"] = certificate
    if "rate_exchange_scopes" in fields:
        canonical_facts["rate_exchange_scopes"] = scopes
    canonical = json.dumps(
        canonical_facts,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    expected = hashlib.sha256(canonical).hexdigest()
    return hmac.compare_digest(value["snapshot_sha256"], expected)


def _decode_readonly_worker_output(raw: bytes) -> dict[str, object]:
    """Accept only the worker's fixed redacted, zero-write projection."""

    if type(raw) is not bytes or not raw or len(raw) > READONLY_MAX_OUTPUT_BYTES:
        raise GuardianServiceError("worker_output_size_invalid")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_duplicate_rejecting_pairs)
    except GuardianServiceError:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise GuardianServiceError("worker_output_invalid") from None
    if type(value) is not dict or set(value) != {"schema", "observation"}:
        raise GuardianServiceError("worker_output_fields_invalid")
    if value["schema"] != READONLY_WORKER_SCHEMA:
        raise GuardianServiceError("worker_output_schema_invalid")
    observation = value["observation"]
    if type(observation) is not dict or set(observation) != _READONLY_WORKER_OBSERVATION_FIELDS:
        raise GuardianServiceError("worker_observation_fields_invalid")
    boolean_fields = (
        "credentials_resolved",
        "provider_connected",
        "account_identity_verified",
        "preflight_authorized",
        "execution_authorized",
        "external_writes_authorized",
        "order_submission_authorized",
        "cancellation_authorized",
        "settlement_authorized",
        "arming_authorized",
    )
    if any(type(observation[key]) is not bool for key in boolean_fields):
        raise GuardianServiceError("worker_observation_authority_invalid")
    if (
        observation["credentials_resolved"] is not True
        or any(observation[key] is not False for key in boolean_fields[1:])
        or type(observation["external_write_requests"]) is not int
        or observation["external_write_requests"] != 0
        or type(observation["market_data_trading_writes"]) is not int
        or observation["market_data_trading_writes"] != 0
        or type(observation["read_only_observation"]) is not dict
        or type(observation["market_data_observation"]) is not dict
    ):
        raise GuardianServiceError("worker_observation_authority_invalid")
    account = observation["read_only_observation"]
    market = observation["market_data_observation"]
    if (
        set(account) != _READONLY_ACCOUNT_FACT_FIELDS
        or set(market) != _READONLY_MARKET_FACT_FIELDS
        or account["account_scope"] != "redacted"
        or account["account_acceptance_established"] is not False
        or account["approval_required"] is not False
        or account["read_only_route_admitted"] is not True
        or account["session_connected"] is not True
        or account["provider_preflight_started"] is not True
        or type(account["external_write_requests"]) is not int
        or account["external_write_requests"] != 0
        or any(
            account[key] is not False
            for key in (
                "arming_authorized",
                "cancellation_authorized",
                "execution_authorized",
                "external_writes_authorized",
                "order_submission_authorized",
                "settlement_authorized",
            )
        )
        or not _readonly_query_snapshot_is_valid(account["query_snapshot"])
        or type(account["connection_generation"]) is not int
        or account["connection_generation"]
        != account["query_snapshot"]["identity"]["connection_generation"]
        or account["provider"] != "ctp"
        or account["environment"] != account["query_snapshot"]["identity"]["environment"]
        or account["environment"] != "simnow"
        or account["sdk_profile"] != "config_front_pair"
        or account["trading_day"] != account["query_snapshot"]["identity"]["trading_day"]
        or not _is_lower_sha256(account["effective_config_digest"])
        or not _is_lower_sha256(account["registration_digest"])
        or account["native_certificate_sha256"]
        != account["query_snapshot"].get("native_certificate_sha256")
        or account["native_certificate_provenance"]
        != (
            "UNVERIFIED_DIGEST_ONLY"
            if account["native_certificate_sha256"] is not None
            else "LOCAL_ONLY"
        )
        or account["runtime_id"] != _READONLY_RUNTIME_ID
        or account["strategy_id"] != _READONLY_STRATEGY_ID
        or type(account["instrument_id"]) is not str
        or _READONLY_INSTRUMENT_RE.fullmatch(account["instrument_id"]) is None
        or type(account["exchange_id"]) is not str
        or _READONLY_EXCHANGE_RE.fullmatch(account["exchange_id"]) is None
        or type(account["hedge_flag"]) is not str
        or account["hedge_flag"] not in ("1", "2", "3")
        or account["instrument_id"] != market.get("instrument_id")
        or account["exchange_id"] != market.get("exchange_id")
        or type(market["account_scope_bound"]) is not bool
        or market["account_scope_bound"] is not True
        or market["market_login_ready"] is not True
        or market["subscription_acknowledged"] is not True
        or market["first_tick_observed"] is not True
        or market["market_path_ready"] is not True
        or type(market["client_stop_returned"]) is not bool
        or market["client_stop_returned"] is not True
        or type(market["native_join_pending"]) is not bool
        or market["native_join_pending"] is not False
        or market["probe_session_closed"] is not True
        or market["order_submission_authorized"] is not False
        or type(market["trading_writes"]) is not int
        or market["trading_writes"] != 0
        or type(market["settlement_writes"]) is not int
        or market["settlement_writes"] != 0
        or type(market["tick_binding"]) is not dict
        or set(market["tick_binding"]) != _READONLY_TICK_BINDING_FIELDS
        or market["tick_binding"].get("account_bound") is not True
        or type(market["connection_generation"]) is not int
        or market["connection_generation"] != account["connection_generation"]
        or type(market["tick_observation_count"]) is not int
        or market["tick_observation_count"] < 1
        or type(market["tick_binding"].get("connection_generation")) is not int
        or market["tick_binding"]["connection_generation"] != market["connection_generation"]
        or market["tick_binding"].get("instrument_id") != market["instrument_id"]
        or market["tick_binding"].get("exchange_id") != market["exchange_id"]
        or market["tick_binding"].get("md_front_sha256") != market["md_front_sha256"]
        or not _is_lower_sha256(market["md_front_sha256"])
        or not _is_lower_sha256(market["tick_binding"].get("md_front_sha256"))
        or market["account_probe_lock_scope"] != "cooperating_probe_invocations_only"
    ):
        raise GuardianServiceError("worker_observation_facts_invalid")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    if canonical != raw:
        raise GuardianServiceError("worker_output_not_canonical")
    return observation


class GuardianServiceError(ValueError):
    """Redacted service admission or IPC error."""


class GuardianServiceThreadFatalError(BaseException):
    """The service process must stop after identity cleanup fails."""


def _fail_stop_service_process_after_revert_failure() -> None:
    """Exit the service process without running Python handlers or thread reuse.

    A failed ``RevertToSelf`` leaves the request thread's token context
    uncertain.  Returning it to a service dispatcher could run later work as
    the client.  Process termination closes the token/thread handles in the
    kernel and lets the existing Job containment collect descendants.
    """

    if os.name == "nt":
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            get_current_process = kernel32.GetCurrentProcess
            get_current_process.argtypes = []
            get_current_process.restype = wintypes.HANDLE
            terminate_process = kernel32.TerminateProcess
            terminate_process.argtypes = [wintypes.HANDLE, wintypes.UINT]
            terminate_process.restype = wintypes.BOOL
            terminate_process(get_current_process(), 70)
        except BaseException:
            pass
    # TerminateProcess should not return after success.  This fallback also
    # makes failure or a wrapper that returns fail-stop rather than resuming
    # Python finally blocks under an uncertain thread token.
    os._exit(70)


def _revert_pipe_impersonation_or_fail_stop(advapi32: object) -> None:
    """Restore the service token or terminate before any caller can continue."""

    try:
        revert = advapi32.RevertToSelf
        revert.argtypes = []
        revert.restype = wintypes.BOOL
        reverted = bool(revert())
    except BaseException:
        reverted = False
    if not reverted:
        _fail_stop_service_process_after_revert_failure()
        # The production fail-stop never returns. Keep test/fault-injected
        # return paths non-catchable by ordinary GuardianServiceError handlers.
        raise GuardianServiceThreadFatalError("pipe_client_revert_failed")


@dataclass(frozen=True)
class PipeResponse:
    state: str
    reason: str
    response_bytes: Optional[bytes]


def _is_reparse(details: os.stat_result) -> bool:
    return stat.S_ISLNK(details.st_mode) or bool(
        getattr(details, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _validate_directory(path: Path, reason: str) -> None:
    if not path.is_absolute():
        raise GuardianServiceError(reason)
    current = Path(path.anchor)
    parts = path.parts[1:]
    for index, part in enumerate(parts):
        current = current / part
        try:
            details = os.lstat(current)
        except OSError:
            raise GuardianServiceError(reason) from None
        if _is_reparse(details) or (index < len(parts) - 1 and not stat.S_ISDIR(details.st_mode)):
            raise GuardianServiceError(reason)
    if not path.is_dir():
        raise GuardianServiceError(reason)


def _validate_pipe_address(address: object) -> str:
    if type(address) is not str or _PIPE_RE.fullmatch(address) is None:
        raise GuardianServiceError("service_pipe_address_invalid")
    return address


def _validate_key(auth_key: object) -> bytes:
    if type(auth_key) is not bytes or len(auth_key) != 32:
        raise GuardianServiceError("service_auth_key_invalid")
    return auth_key


def _duplicate_rejecting_pairs(pairs):
    values = {}
    for key, value in pairs:
        if key in values:
            raise GuardianServiceError("request_duplicate_key")
        values[key] = value
    return values


def _decode_request(raw: bytes, *, now: float) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > _MAX_MESSAGE_BYTES:
        raise GuardianServiceError("request_size_invalid")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_duplicate_rejecting_pairs)
    except GuardianServiceError:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise GuardianServiceError("request_invalid") from None
    expected_fields = {
        "schema",
        "operation",
        "request_id",
        "child_seconds",
        "stop_deadline_monotonic",
        "deadline_monotonic",
    }
    if type(value) is not dict or set(value) != expected_fields:
        raise GuardianServiceError("request_fields_invalid")
    if value["schema"] != REQUEST_SCHEMA or value["operation"] != "sleep_probe":
        raise GuardianServiceError("request_operation_invalid")
    request_id = value["request_id"]
    if type(request_id) is not str or _REQUEST_ID_RE.fullmatch(request_id) is None:
        raise GuardianServiceError("request_id_invalid")
    child_seconds = value["child_seconds"]
    stop_deadline = value["stop_deadline_monotonic"]
    deadline = value["deadline_monotonic"]
    if (
        type(child_seconds) not in (int, float)
        or not math.isfinite(float(child_seconds))
        or not 0.0 < float(child_seconds) <= _MAX_CHILD_SECONDS
        or type(stop_deadline) not in (int, float)
        or not math.isfinite(float(stop_deadline))
        or type(deadline) not in (int, float)
        or not math.isfinite(float(deadline))
        or not now < float(stop_deadline) <= float(deadline)
        or float(deadline) - now > _MAX_TOTAL_SECONDS
    ):
        raise GuardianServiceError("request_deadline_or_duration_invalid")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    if raw != canonical:
        raise GuardianServiceError("request_not_canonical")
    return value


def _decode_readonly_preflight_request(raw: bytes, *, now: float) -> dict[str, object]:
    """Decode the fixed operation's pathless, argument-free wire request."""

    if type(raw) is not bytes or not raw or len(raw) > _MAX_MESSAGE_BYTES:
        raise GuardianServiceError("request_size_invalid")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_duplicate_rejecting_pairs)
    except GuardianServiceError:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise GuardianServiceError("request_invalid") from None
    expected_fields = {"schema", "operation", "request_id", "deadline_monotonic"}
    if type(value) is not dict or set(value) != expected_fields:
        raise GuardianServiceError("readonly_request_fields_invalid")
    if value["schema"] != READONLY_REQUEST_SCHEMA or value["operation"] != "ctp_readonly_preflight":
        raise GuardianServiceError("readonly_request_operation_invalid")
    request_id = value["request_id"]
    deadline = value["deadline_monotonic"]
    if type(request_id) is not str or _REQUEST_ID_RE.fullmatch(request_id) is None:
        raise GuardianServiceError("request_id_invalid")
    if (
        type(deadline) not in (int, float)
        or not math.isfinite(float(deadline))
        or not float(now) < float(deadline) <= float(now) + _MAX_TOTAL_SECONDS
    ):
        raise GuardianServiceError("request_deadline_or_duration_invalid")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    if raw != canonical:
        raise GuardianServiceError("request_not_canonical")
    return value


def _decode_readonly_os_request(raw: bytes, *, now_monotonic_ns: int) -> dict[str, object]:
    """Validate the pathless OS-token request and its single absolute deadline."""

    if type(raw) is not bytes or not raw or len(raw) > _MAX_MESSAGE_BYTES:
        raise GuardianServiceError("request_size_invalid")
    if type(now_monotonic_ns) is not int or now_monotonic_ns < 0:
        raise GuardianServiceError("request_clock_invalid")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_duplicate_rejecting_pairs)
    except GuardianServiceError:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise GuardianServiceError("request_invalid") from None
    if type(value) is not dict or set(value) != {
        "schema",
        "operation",
        "request_id",
        "deadline_monotonic_ns",
    }:
        raise GuardianServiceError("readonly_request_fields_invalid")
    if (
        value["schema"] != READONLY_OS_REQUEST_SCHEMA
        or value["operation"] != "ctp_readonly_preflight"
    ):
        raise GuardianServiceError("readonly_request_operation_invalid")
    request_id = value["request_id"]
    deadline_ns = value["deadline_monotonic_ns"]
    if type(request_id) is not str or _REQUEST_ID_RE.fullmatch(request_id) is None:
        raise GuardianServiceError("request_id_invalid")
    if (
        type(deadline_ns) is not int
        or deadline_ns <= now_monotonic_ns
        or deadline_ns - now_monotonic_ns > int(_MAX_TOTAL_SECONDS * 1_000_000_000)
    ):
        raise GuardianServiceError("request_deadline_or_duration_invalid")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    if raw != canonical:
        raise GuardianServiceError("request_not_canonical")
    return value


def _decode_readonly_os_response(raw: bytes, *, request_id: str) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > _MAX_MESSAGE_BYTES:
        raise GuardianServiceError("readonly_response_size_invalid")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_duplicate_rejecting_pairs)
    except GuardianServiceError:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise GuardianServiceError("readonly_response_invalid") from None
    if type(value) is not dict or set(value) != {
        "schema",
        "request_id",
        "state",
        "reason",
        "receipt_sha256",
        "coordinator_job",
        "receipt_writer_job",
    }:
        raise GuardianServiceError("readonly_response_fields_invalid")
    if (
        value["schema"] != READONLY_OS_RESPONSE_SCHEMA
        or value["request_id"] != request_id
        or type(value["state"]) is not str
        or value["state"] not in {"observed", "unknown"}
        or type(value["reason"]) is not str
        or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value["reason"]) is None
        or (value["receipt_sha256"] is not None and not _is_lower_sha256(value["receipt_sha256"]))
        or (value["state"] == "observed" and value["receipt_sha256"] is None)
        or not _valid_readonly_job_facts(value["coordinator_job"], allow_unknown=True)
        or not _valid_readonly_job_facts(value["receipt_writer_job"], allow_unknown=True)
        or (
            value["state"] == "observed"
            and (
                not _job_facts_are_clean_success(value["coordinator_job"])
                or not _job_facts_are_clean_success(value["receipt_writer_job"])
            )
        )
    ):
        raise GuardianServiceError("readonly_response_facts_invalid")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    if raw != canonical:
        raise GuardianServiceError("readonly_response_not_canonical")
    return value


_READONLY_JOB_FACT_FIELDS = frozenset(
    {
        "process_created",
        "job_assignment_observed",
        "launcher_resumed",
        "launcher_exit_observed",
        "launcher_exit_code",
        "job_termination_requested",
        "job_termination_call_succeeded",
        "job_empty_observed",
        "containment",
        "controls_retained",
    }
)


def _valid_readonly_job_facts(value: object, *, allow_unknown: bool = False) -> bool:
    if type(value) is not dict or set(value) != _READONLY_JOB_FACT_FIELDS:
        return False
    bool_fields = (
        "process_created",
        "job_assignment_observed",
        "launcher_resumed",
        "launcher_exit_observed",
        "job_termination_requested",
        "job_empty_observed",
        "controls_retained",
    )
    if any(
        type(value[name]) is not bool and not (allow_unknown and value[name] is None)
        for name in bool_fields
    ):
        return False
    termination_result = value["job_termination_call_succeeded"]
    if termination_result is not None and type(termination_result) is not bool:
        return False
    exit_code = value["launcher_exit_code"]
    if exit_code is not None and type(exit_code) is not int:
        return False
    if (
        value["launcher_exit_observed"] is not None
        and value["launcher_exit_observed"] != (exit_code is not None)
    ):
        return False
    if type(value["containment"]) is not str or value["containment"] not in {
        "verified",
        "unknown",
        "not_started",
    }:
        return False
    if value["job_assignment_observed"] is True and value["process_created"] is not True:
        return False
    if value["launcher_resumed"] is True and value["job_assignment_observed"] is not True:
        return False
    if value["job_empty_observed"] is True and value["launcher_exit_observed"] is not True:
        return False
    if value["job_termination_requested"] is True and termination_result is None:
        return False
    if value["process_created"] is False and any(
        value[name] is True
        for name in (
            "job_assignment_observed",
            "launcher_resumed",
            "launcher_exit_observed",
            "job_termination_requested",
            "job_empty_observed",
        )
    ):
        return False
    return True


def _job_facts_are_clean_success(value: object) -> bool:
    return _valid_readonly_job_facts(value) and (
        value["process_created"] is True
        and value["job_assignment_observed"] is True
        and value["launcher_resumed"] is True
        and value["launcher_exit_observed"] is True
        and value["launcher_exit_code"] == 0
        and value["job_termination_requested"] is False
        and value["job_empty_observed"] is True
        and value["containment"] == "verified"
        and value["controls_retained"] is False
    )


def _job_cleanup_proven_facts(value: object) -> bool:
    """Require exit, empty Job and released controls; exit code may be nonzero."""

    return _valid_readonly_job_facts(value) and (
        value["process_created"] is True
        and value["job_assignment_observed"] is True
        and value["launcher_exit_observed"] is True
        and type(value["launcher_exit_code"]) is int
        and value["job_empty_observed"] is True
        and value["containment"] == "verified"
        and value["controls_retained"] is False
    )


def _server_pid_from_pipe(handle: int) -> int:
    if os.name != "nt":
        raise GuardianServiceError("windows_required")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = kernel32.GetNamedPipeServerProcessId
    function.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    function.restype = wintypes.BOOL
    pid = wintypes.ULONG()
    if not function(wintypes.HANDLE(handle), ctypes.byref(pid)):
        raise GuardianServiceError("service_pipe_server_identity_unavailable")
    return int(pid.value)


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]


class _TOKEN_USER_VALUE(ctypes.Structure):
    _fields_ = [("User", _SID_AND_ATTRIBUTES)]


class _TOKEN_GROUPS_ONE(ctypes.Structure):
    _fields_ = [("GroupCount", wintypes.DWORD), ("Groups", _SID_AND_ATTRIBUTES * 1)]


class _SERVICE_STATUS_PROCESS(ctypes.Structure):
    _fields_ = [
        ("dwServiceType", wintypes.DWORD),
        ("dwCurrentState", wintypes.DWORD),
        ("dwControlsAccepted", wintypes.DWORD),
        ("dwWin32ExitCode", wintypes.DWORD),
        ("dwServiceSpecificExitCode", wintypes.DWORD),
        ("dwCheckPoint", wintypes.DWORD),
        ("dwWaitHint", wintypes.DWORD),
        ("dwProcessId", wintypes.DWORD),
        ("dwServiceFlags", wintypes.DWORD),
    ]


class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


def _token_user_sid(token_handle: int) -> str:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    get_token_information = advapi32.GetTokenInformation
    get_token_information.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    get_token_information.restype = wintypes.BOOL
    required = wintypes.DWORD()
    get_token_information(
        wintypes.HANDLE(token_handle), _TOKEN_USER, None, 0, ctypes.byref(required)
    )
    if not required.value:
        raise GuardianServiceError("pipe_token_user_unavailable")
    buffer = ctypes.create_string_buffer(required.value)
    if not get_token_information(
        wintypes.HANDLE(token_handle),
        _TOKEN_USER,
        ctypes.cast(buffer, wintypes.LPVOID),
        required.value,
        ctypes.byref(required),
    ):
        raise GuardianServiceError("pipe_token_user_unavailable")
    user = ctypes.cast(buffer, ctypes.POINTER(_TOKEN_USER_VALUE)).contents
    if not user.User.Sid:
        raise GuardianServiceError("pipe_token_user_unavailable")

    sid_text = wintypes.LPWSTR()
    convert_sid = advapi32.ConvertSidToStringSidW
    convert_sid.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
    convert_sid.restype = wintypes.BOOL
    if not convert_sid(user.User.Sid, ctypes.byref(sid_text)):
        raise GuardianServiceError("pipe_token_user_unavailable")
    try:
        return str(sid_text.value)
    finally:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        local_free = kernel32.LocalFree
        local_free.argtypes = [wintypes.HLOCAL]
        local_free.restype = wintypes.HLOCAL
        local_free(wintypes.HLOCAL(ctypes.cast(sid_text, wintypes.HLOCAL).value))


def _validate_fixed_service_sid(service_name: object, service_sid: object) -> str:
    """Accept only the canonical service SID for the one code-owned SCM name."""

    if (
        service_name != FIXED_READONLY_SERVICE_NAME
        or type(service_sid) is not str
        or _SERVICE_SID_RE.fullmatch(service_sid) is None
    ):
        raise GuardianServiceError("service_sid_binding_invalid")
    components = service_sid.split("-")[4:]
    if len(components) != 5 or any(str(int(part)) != part for part in components):
        raise GuardianServiceError("service_sid_binding_invalid")
    if any(not 0 <= int(part) <= 0xFFFFFFFF for part in components):
        raise GuardianServiceError("service_sid_binding_invalid")
    return service_sid


def _bind_service_sid(service_sid: object) -> str:
    """Match descriptor/binding data to the SID derived from the fixed SCM name."""

    derived = _service_sid_from_name(FIXED_READONLY_SERVICE_NAME)
    _validate_fixed_service_sid(FIXED_READONLY_SERVICE_NAME, service_sid)
    if not hmac.compare_digest(derived, service_sid):
        raise GuardianServiceError("service_sid_binding_mismatch")
    return derived


def _service_sid_from_name(service_name: str = FIXED_READONLY_SERVICE_NAME) -> str:
    """Resolve the fixed SCM name to its OS-issued NT SERVICE SID."""

    if os.name != "nt":
        raise GuardianServiceError("windows_required")
    if service_name != FIXED_READONLY_SERVICE_NAME:
        raise GuardianServiceError("service_name_not_fixed")
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    lookup = advapi32.LookupAccountNameW
    lookup.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    lookup.restype = wintypes.BOOL
    account_name = "NT SERVICE\\" + FIXED_READONLY_SERVICE_NAME
    sid_size = wintypes.DWORD()
    domain_size = wintypes.DWORD()
    sid_use = wintypes.DWORD()
    lookup(
        None,
        account_name,
        None,
        ctypes.byref(sid_size),
        None,
        ctypes.byref(domain_size),
        ctypes.byref(sid_use),
    )
    if not sid_size.value or ctypes.get_last_error() != 122:
        raise GuardianServiceError("service_sid_lookup_failed")
    sid_buffer = ctypes.create_string_buffer(sid_size.value)
    domain_buffer = ctypes.create_unicode_buffer(max(1, int(domain_size.value)))
    if not lookup(
        None,
        account_name,
        ctypes.cast(sid_buffer, wintypes.LPVOID),
        ctypes.byref(sid_size),
        domain_buffer,
        ctypes.byref(domain_size),
        ctypes.byref(sid_use),
    ):
        raise GuardianServiceError("service_sid_lookup_failed")
    sid_text = wintypes.LPWSTR()
    convert_sid = advapi32.ConvertSidToStringSidW
    convert_sid.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
    convert_sid.restype = wintypes.BOOL
    if not convert_sid(ctypes.cast(sid_buffer, wintypes.LPVOID), ctypes.byref(sid_text)):
        raise GuardianServiceError("service_sid_lookup_failed")
    try:
        return _validate_fixed_service_sid(service_name, str(sid_text.value))
    finally:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        local_free = kernel32.LocalFree
        local_free.argtypes = [wintypes.HLOCAL]
        local_free.restype = wintypes.HLOCAL
        if local_free(wintypes.HLOCAL(ctypes.cast(sid_text, wintypes.HLOCAL).value)):
            raise GuardianServiceError("service_sid_string_cleanup_failed")


def _token_group_sid_attributes(token_handle: int) -> tuple[tuple[str, int], ...]:
    """Read token groups without treating a service SID as TokenUser."""

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    get_token_information = advapi32.GetTokenInformation
    get_token_information.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    get_token_information.restype = wintypes.BOOL
    required = wintypes.DWORD()
    get_token_information(
        wintypes.HANDLE(token_handle), _TOKEN_GROUPS, None, 0, ctypes.byref(required)
    )
    if not required.value or required.value > 1024 * 1024:
        raise GuardianServiceError("service_token_groups_unavailable")
    buffer = ctypes.create_string_buffer(required.value)
    if not get_token_information(
        wintypes.HANDLE(token_handle),
        _TOKEN_GROUPS,
        ctypes.cast(buffer, wintypes.LPVOID),
        required.value,
        ctypes.byref(required),
    ):
        raise GuardianServiceError("service_token_groups_unavailable")
    base = ctypes.addressof(buffer)
    header = ctypes.cast(base, ctypes.POINTER(_TOKEN_GROUPS_ONE)).contents
    group_count = int(header.GroupCount)
    groups_offset = _TOKEN_GROUPS_ONE.Groups.offset
    available_count = (int(required.value) - groups_offset) // ctypes.sizeof(_SID_AND_ATTRIBUTES)
    if group_count < 0 or group_count > available_count:
        raise GuardianServiceError("service_token_groups_invalid")
    groups = ctypes.cast(
        base + groups_offset, ctypes.POINTER(_SID_AND_ATTRIBUTES * max(1, group_count))
    ).contents
    results = []
    for index in range(group_count):
        group = groups[index]
        if not group.Sid:
            raise GuardianServiceError("service_token_groups_invalid")
        sid_text = wintypes.LPWSTR()
        convert_sid = advapi32.ConvertSidToStringSidW
        convert_sid.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
        convert_sid.restype = wintypes.BOOL
        if not convert_sid(group.Sid, ctypes.byref(sid_text)):
            raise GuardianServiceError("service_token_groups_invalid")
        try:
            results.append((str(sid_text.value), int(group.Attributes)))
        finally:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            local_free = kernel32.LocalFree
            local_free.argtypes = [wintypes.HLOCAL]
            local_free.restype = wintypes.HLOCAL
            if local_free(wintypes.HLOCAL(ctypes.cast(sid_text, wintypes.HLOCAL).value)):
                raise GuardianServiceError("service_sid_string_cleanup_failed")
    return tuple(results)


def _has_enabled_service_sid(group_facts: object, *, service_name: str, service_sid: str) -> bool:
    """Require the derived service SID to be enabled and not deny-only."""

    _validate_fixed_service_sid(service_name, service_sid)
    if type(group_facts) not in (tuple, list):
        raise GuardianServiceError("service_token_groups_invalid")
    matches = []
    for fact in group_facts:
        if (
            type(fact) not in (tuple, list)
            or len(fact) != 2
            or type(fact[0]) is not str
            or type(fact[1]) is not int
            or fact[1] < 0
        ):
            raise GuardianServiceError("service_token_groups_invalid")
        if hmac.compare_digest(fact[0], service_sid):
            matches.append(fact[1])
    return (
        len(matches) == 1
        and bool(matches[0] & _SE_GROUP_ENABLED)
        and not bool(matches[0] & _SE_GROUP_USE_FOR_DENY_ONLY)
    )


def _validate_fixed_scm_status(
    *, service_name: str, service_type: int, current_state: int, process_id: int, expected_pid: int
) -> None:
    """Reject shared-process services and any non-running or mismatched PID."""

    if (
        service_name != FIXED_READONLY_SERVICE_NAME
        or type(service_type) is not int
        or type(current_state) is not int
        or type(process_id) is not int
        or type(expected_pid) is not int
        or service_type != _SERVICE_WIN32_OWN_PROCESS
        or current_state != _SERVICE_RUNNING
        or process_id <= 0
        or process_id != expected_pid
    ):
        raise GuardianServiceError("service_scm_identity_mismatch")


def _query_fixed_scm_status() -> tuple[int, int, int]:
    """Query the code-owned service name; no caller may select an SCM entry."""

    if os.name != "nt":
        raise GuardianServiceError("windows_required")
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    open_scm = advapi32.OpenSCManagerW
    open_scm.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    open_scm.restype = wintypes.HANDLE
    open_service = advapi32.OpenServiceW
    open_service.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
    open_service.restype = wintypes.HANDLE
    query_status = advapi32.QueryServiceStatusEx
    query_status.argtypes = [
        wintypes.HANDLE,
        wintypes.INT,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    query_status.restype = wintypes.BOOL
    manager = open_scm(None, None, _SC_MANAGER_CONNECT)
    if not manager:
        raise GuardianServiceError("service_scm_unavailable")
    service = None
    try:
        service = open_service(manager, FIXED_READONLY_SERVICE_NAME, _SERVICE_QUERY_STATUS)
        if not service:
            raise GuardianServiceError("service_scm_unavailable")
        status = _SERVICE_STATUS_PROCESS()
        needed = wintypes.DWORD()
        if not query_status(
            service,
            _SC_STATUS_PROCESS_INFO,
            ctypes.byref(status),
            ctypes.sizeof(status),
            ctypes.byref(needed),
        ):
            raise GuardianServiceError("service_scm_status_unavailable")
        return int(status.dwServiceType), int(status.dwCurrentState), int(status.dwProcessId)
    finally:
        close_service = advapi32.CloseServiceHandle
        close_service.argtypes = [wintypes.HANDLE]
        close_service.restype = wintypes.BOOL
        close_failed = False
        if service:
            try:
                close_failed = not bool(close_service(service))
            except BaseException:
                close_failed = True
        try:
            manager_closed = bool(close_service(manager))
        except BaseException:
            manager_closed = False
        if close_failed or not manager_closed:
            raise GuardianServiceError("service_scm_handle_close_failed")


def _process_creation_filetime(process_handle: int) -> int:
    if os.name != "nt":
        raise GuardianServiceError("windows_required")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_times = kernel32.GetProcessTimes
    get_times.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    get_times.restype = wintypes.BOOL
    creation, exit_time, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
    if not get_times(
        wintypes.HANDLE(process_handle),
        ctypes.byref(creation),
        ctypes.byref(exit_time),
        ctypes.byref(kernel_time),
        ctypes.byref(user_time),
    ):
        raise GuardianServiceError("service_process_creation_time_unavailable")
    return (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)


def _process_id_from_handle(process_handle: int) -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_pid = kernel32.GetProcessId
    get_pid.argtypes = [wintypes.HANDLE]
    get_pid.restype = wintypes.DWORD
    pid = int(get_pid(wintypes.HANDLE(process_handle)))
    if pid <= 0:
        raise GuardianServiceError("service_process_id_unavailable")
    return pid


def _process_is_live(process_handle: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    wait = kernel32.WaitForSingleObject
    wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait.restype = wintypes.DWORD
    return int(wait(wintypes.HANDLE(process_handle), 0)) == _WAIT_TIMEOUT


def _process_image_path(process_handle: int) -> str:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    query = kernel32.QueryFullProcessImageNameW
    query.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    query.restype = wintypes.BOOL
    buffer = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(buffer))
    if not query(wintypes.HANDLE(process_handle), 0, buffer, ctypes.byref(size)):
        raise GuardianServiceError("service_process_image_unavailable")
    return str(buffer.value)


def _canonical_image_path(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or not ntpath.isabs(value)
        or "/" in value
        or ntpath.normpath(value) != value
        or any(part in {".", ".."} for part in value.split("\\"))
    ):
        raise GuardianServiceError("service_python_binding_invalid")
    return value


def _normalized_final_image_path(value: str) -> str:
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return ntpath.normcase(ntpath.normpath(value))


@dataclass
class _RetainedPinnedExecutable:
    """Retain a read-only executable handle and verify its pinned bytes/identity."""

    path: str
    sha256: str
    handle: Optional[int]
    file_identity: tuple[int, ...]
    _kernel32: object

    @classmethod
    def open(cls, path: str, sha256: str) -> "_RetainedPinnedExecutable":
        if os.name != "nt":
            raise GuardianServiceError("windows_required")
        canonical = _canonical_image_path(path)
        if type(sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
            raise GuardianServiceError("service_python_binding_invalid")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(_SECURITY_ATTRIBUTES),
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create_file.restype = wintypes.HANDLE
        handle = create_file(
            canonical,
            _GENERIC_READ,
            _FILE_SHARE_READ,
            None,
            _OPEN_EXISTING,
            _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_SEQUENTIAL_SCAN,
            None,
        )
        value = _native_handle_value(handle)
        if value == 0 or value == ctypes.c_void_p(-1).value:
            raise GuardianServiceError("service_python_handle_unavailable")
        retained = cls(canonical, sha256, value, (), kernel32)
        try:
            retained.file_identity = retained._query_file_identity()
            actual_path = retained._query_final_path()
            if _normalized_final_image_path(actual_path) != ntpath.normcase(canonical):
                raise GuardianServiceError("service_python_file_identity_mismatch")
            actual_digest = retained._hash_open_file()
            if not hmac.compare_digest(actual_digest, sha256):
                raise GuardianServiceError("service_python_digest_mismatch")
            if retained._query_file_identity() != retained.file_identity:
                raise GuardianServiceError("service_python_file_changed")
            return retained
        except BaseException:
            if not retained.close():
                raise GuardianServiceError("service_python_handle_cleanup_unconfirmed") from None
            raise

    def _query_file_identity(self) -> tuple[int, ...]:
        get_info = self._kernel32.GetFileInformationByHandle
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION)]
        get_info.restype = wintypes.BOOL
        info = _BY_HANDLE_FILE_INFORMATION()
        if not get_info(wintypes.HANDLE(self.handle), ctypes.byref(info)):
            raise GuardianServiceError("service_python_file_identity_unavailable")
        attributes = int(info.dwFileAttributes)
        if attributes == _INVALID_FILE_ATTRIBUTES or attributes & (
            _FILE_ATTRIBUTE_DIRECTORY | _FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise GuardianServiceError("service_python_file_type_invalid")
        size = (int(info.nFileSizeHigh) << 32) | int(info.nFileSizeLow)
        if not 0 < size <= 256 * 1024 * 1024:
            raise GuardianServiceError("service_python_file_size_invalid")
        return (
            int(info.dwVolumeSerialNumber),
            int(info.nFileIndexHigh),
            int(info.nFileIndexLow),
            size,
            int(info.ftCreationTime.dwHighDateTime),
            int(info.ftCreationTime.dwLowDateTime),
            int(info.ftLastWriteTime.dwHighDateTime),
            int(info.ftLastWriteTime.dwLowDateTime),
        )

    def _query_final_path(self) -> str:
        get_path = self._kernel32.GetFinalPathNameByHandleW
        get_path.argtypes = [
            wintypes.HANDLE,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        get_path.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        length = int(get_path(wintypes.HANDLE(self.handle), buffer, len(buffer), 0))
        if length <= 0 or length >= len(buffer):
            raise GuardianServiceError("service_python_final_path_unavailable")
        return str(buffer.value)

    def _hash_open_file(self) -> str:
        set_pointer = self._kernel32.SetFilePointerEx
        set_pointer.argtypes = [
            wintypes.HANDLE,
            ctypes.c_longlong,
            ctypes.POINTER(ctypes.c_longlong),
            wintypes.DWORD,
        ]
        set_pointer.restype = wintypes.BOOL
        new_position = ctypes.c_longlong()
        if not set_pointer(
            wintypes.HANDLE(self.handle), 0, ctypes.byref(new_position), _FILE_BEGIN
        ):
            raise GuardianServiceError("service_python_read_failed")
        total = self.file_identity[3]
        digest = hashlib.sha256()
        remaining = total
        read_file = self._kernel32.ReadFile
        read_file.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        read_file.restype = wintypes.BOOL
        while remaining:
            requested = min(64 * 1024, remaining)
            buffer = ctypes.create_string_buffer(requested)
            received = wintypes.DWORD()
            if (
                not read_file(
                    wintypes.HANDLE(self.handle),
                    buffer,
                    requested,
                    ctypes.byref(received),
                    None,
                )
                or int(received.value) != requested
            ):
                raise GuardianServiceError("service_python_read_failed")
            digest.update(buffer.raw[:requested])
            remaining -= requested
        return digest.hexdigest()

    def verify_current(self) -> None:
        if self.handle is None:
            raise GuardianServiceError("service_python_handle_closed")
        if self._query_file_identity() != self.file_identity or _normalized_final_image_path(
            self._query_final_path()
        ) != ntpath.normcase(self.path):
            raise GuardianServiceError("service_python_file_identity_changed")

    def close(self) -> bool:
        if self.handle is None:
            return True
        try:
            closed = bool(self._kernel32.CloseHandle(wintypes.HANDLE(self.handle)))
        except BaseException:
            closed = False
        if closed:
            self.handle = None
        else:
            _retain_failed_windows_cleanup(self)
        return closed


def _process_has_service_sid(process_handle: int, service_sid: str) -> bool:
    _validate_fixed_service_sid(FIXED_READONLY_SERVICE_NAME, service_sid)
    if os.name != "nt":
        raise GuardianServiceError("windows_required")
    kernel32, advapi32 = _pipe_token_apis()
    open_token = advapi32.OpenProcessToken
    open_token.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    open_token.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not open_token(wintypes.HANDLE(process_handle), _TOKEN_QUERY, ctypes.byref(token)):
        raise GuardianServiceError("service_process_token_unavailable")
    try:
        facts = _token_group_sid_attributes(int(token.value))
        return _has_enabled_service_sid(
            facts, service_name=FIXED_READONLY_SERVICE_NAME, service_sid=service_sid
        )
    finally:
        try:
            if not kernel32.CloseHandle(token):
                raise GuardianServiceError("service_process_token_close_failed")
        except BaseException as error:
            if isinstance(error, GuardianServiceError):
                raise
            raise GuardianServiceError("service_process_token_close_failed") from None


def _verify_current_fixed_service_identity(service_sid: object) -> str:
    """Require this process to be the running own-process fixed Windows service."""

    expected_sid = _bind_service_sid(service_sid)
    if os.name != "nt":
        raise GuardianServiceError("windows_required")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.argtypes = []
    get_current_process.restype = wintypes.HANDLE
    if not _process_has_service_sid(_native_handle_value(get_current_process()), expected_sid):
        raise GuardianServiceError("service_enabled_sid_unavailable")
    current_pid = int(os.getpid())
    service_type, current_state, process_id = _query_fixed_scm_status()
    _validate_fixed_scm_status(
        service_name=FIXED_READONLY_SERVICE_NAME,
        service_type=service_type,
        current_state=current_state,
        process_id=process_id,
        expected_pid=current_pid,
    )
    return expected_sid


@dataclass
class _RetainedReadonlyServerProcess:
    """PID-reuse-resistant identity binding retained across one pipe exchange."""

    handle: int
    pid: int
    creation_filetime: int
    service_sid: str
    python_executable: str
    executable_lease: _RetainedPinnedExecutable
    _kernel32: object
    _closed: bool = False

    @classmethod
    def from_pipe(
        cls,
        pipe_handle: int,
        *,
        service_sid: str,
        python_executable: str,
        python_sha256: str,
    ) -> "_RetainedReadonlyServerProcess":
        if os.name != "nt":
            raise GuardianServiceError("windows_required")
        _bind_service_sid(service_sid)
        executable_lease = _RetainedPinnedExecutable.open(python_executable, python_sha256)
        try:
            pid_before = _server_pid_from_pipe(pipe_handle)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            open_process = kernel32.OpenProcess
            open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            open_process.restype = wintypes.HANDLE
            process = open_process(
                _PROCESS_QUERY_LIMITED_INFORMATION | 0x00100000, False, pid_before
            )
            value = _native_handle_value(process)
        except BaseException:
            if not executable_lease.close():
                raise GuardianServiceError("service_python_handle_cleanup_unconfirmed") from None
            raise
        if value == 0 or value == ctypes.c_void_p(-1).value:
            if not executable_lease.close():
                raise GuardianServiceError("service_python_handle_cleanup_unconfirmed")
            raise GuardianServiceError("service_process_handle_unavailable")
        binding = cls.__new__(cls)
        binding.handle = value
        binding.pid = pid_before
        binding.creation_filetime = 0
        binding.service_sid = service_sid
        binding.python_executable = executable_lease.path
        binding.executable_lease = executable_lease
        binding._kernel32 = kernel32
        binding._closed = False
        try:
            binding.verify(pipe_handle)
            binding.creation_filetime = _process_creation_filetime(value)
            binding.verify(pipe_handle)
            return binding
        except BaseException:
            if not binding.close():
                raise GuardianServiceError("service_process_identity_cleanup_unconfirmed") from None
            raise

    def verify(self, pipe_handle: int) -> None:
        if self._closed:
            raise GuardianServiceError("service_process_handle_closed")
        self.executable_lease.verify_current()
        pipe_pid_before = _server_pid_from_pipe(pipe_handle)
        if pipe_pid_before != self.pid or _process_id_from_handle(self.handle) != self.pid:
            raise GuardianServiceError("service_process_identity_mismatch")
        if not _process_is_live(self.handle):
            raise GuardianServiceError("service_process_not_running")
        if not _process_has_service_sid(self.handle, self.service_sid):
            raise GuardianServiceError("service_process_service_sid_missing")
        if _normalized_final_image_path(_process_image_path(self.handle)) != ntpath.normcase(
            self.python_executable
        ):
            raise GuardianServiceError("service_process_image_mismatch")
        service_type, current_state, process_id = _query_fixed_scm_status()
        _validate_fixed_scm_status(
            service_name=FIXED_READONLY_SERVICE_NAME,
            service_type=service_type,
            current_state=current_state,
            process_id=process_id,
            expected_pid=self.pid,
        )
        creation_now = _process_creation_filetime(self.handle)
        if self.creation_filetime and creation_now != self.creation_filetime:
            raise GuardianServiceError("service_process_creation_identity_changed")
        if (
            _server_pid_from_pipe(pipe_handle) != pipe_pid_before
            or _process_id_from_handle(self.handle) != self.pid
            or not _process_is_live(self.handle)
        ):
            raise GuardianServiceError("service_process_identity_changed")

    def close(self) -> bool:
        if self._closed:
            return True
        try:
            closed = bool(self._kernel32.CloseHandle(wintypes.HANDLE(self.handle)))
        except BaseException:
            closed = False
        if closed:
            self.handle = 0
        executable_closed = self.executable_lease.close()
        self._closed = self.handle == 0 and executable_closed
        if not self._closed:
            _retain_failed_windows_cleanup(self)
        return self._closed


def _current_user_sid() -> str:
    if os.name != "nt":
        raise GuardianServiceError("windows_required")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.argtypes = []
    get_current_process.restype = wintypes.HANDLE
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    open_process_token = advapi32.OpenProcessToken
    open_process_token.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    open_process_token.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not open_process_token(get_current_process(), _TOKEN_QUERY, ctypes.byref(token)):
        raise GuardianServiceError("service_token_unavailable")
    try:
        return _token_user_sid(int(token.value))
    finally:
        if token.value and not kernel32.CloseHandle(token):
            raise GuardianServiceError("service_token_close_failed")


def _client_pid_from_pipe(handle: int) -> int:
    if os.name != "nt":
        raise GuardianServiceError("windows_required")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = kernel32.GetNamedPipeClientProcessId
    function.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    function.restype = wintypes.BOOL
    pid = wintypes.ULONG()
    if not function(wintypes.HANDLE(handle), ctypes.byref(pid)) or not pid.value:
        raise GuardianServiceError("pipe_client_pid_unavailable")
    return int(pid.value)


def _impersonated_pipe_client_sid(handle: int) -> str:
    """Read the identity attached to the actual pipe client message."""

    if os.name != "nt":
        raise GuardianServiceError("windows_required")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    impersonate = advapi32.ImpersonateNamedPipeClient
    impersonate.argtypes = [wintypes.HANDLE]
    impersonate.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    impersonation_attempted = False
    try:
        # Include the native call itself in the cleanup scope: an exception
        # raised by the wrapper may follow a successful OS side effect.
        impersonation_attempted = True
        if not impersonate(wintypes.HANDLE(handle)):
            raise GuardianServiceError("pipe_client_impersonation_failed")
        get_current_thread = kernel32.GetCurrentThread
        get_current_thread.argtypes = []
        get_current_thread.restype = wintypes.HANDLE
        open_thread_token = advapi32.OpenThreadToken
        open_thread_token.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.BOOL,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        open_thread_token.restype = wintypes.BOOL
        if not open_thread_token(get_current_thread(), _TOKEN_QUERY, True, ctypes.byref(token)):
            raise GuardianServiceError("pipe_client_token_unavailable")
        return _token_user_sid(int(token.value))
    finally:
        token_close_failed = False
        if token:
            try:
                closed = bool(kernel32.CloseHandle(token))
            except BaseException:
                closed = False
            token_close_failed = not closed
        if impersonation_attempted:
            _revert_pipe_impersonation_or_fail_stop(advapi32)
        if token_close_failed:
            raise GuardianServiceError("pipe_client_token_close_failed")


def _pipe_token_apis():
    """Load the native token APIs used only after an authenticated request read."""

    if os.name != "nt":
        raise GuardianServiceError("windows_required")
    return (
        ctypes.WinDLL("kernel32", use_last_error=True),
        ctypes.WinDLL("advapi32", use_last_error=True),
    )


@dataclass
class _AuthenticatedPipeClientToken:
    """Borrowable primary token captured from one authenticated pipe message."""

    handle: int
    client_sid: str
    client_pid: int
    _kernel32: object
    _closed: bool = False

    def close(self) -> bool:
        if self._closed:
            return True
        try:
            closed = bool(self._kernel32.CloseHandle(wintypes.HANDLE(self.handle)))
        except BaseException:
            return False
        if closed:
            self._closed = True
        return closed


def _authenticated_pipe_client_primary_token(
    handle: int,
    *,
    expected_client_sid: str,
    include_session_adjustment: bool = False,
) -> _AuthenticatedPipeClientToken:
    """Duplicate the actual message sender's token as a primary token.

    The connected pipe PID is sampled before and after the request-token capture.
    The worker backend receives only this server-created handle; no request
    field can select a token, account, path, or command.
    """

    if not _valid_sid_text(expected_client_sid) or type(include_session_adjustment) is not bool:
        raise GuardianServiceError("pipe_client_binding_invalid")
    pid_before = _client_pid_from_pipe(handle)
    kernel32, advapi32 = _pipe_token_apis()
    impersonate = advapi32.ImpersonateNamedPipeClient
    impersonate.argtypes = [wintypes.HANDLE]
    impersonate.restype = wintypes.BOOL
    get_current_thread = kernel32.GetCurrentThread
    get_current_thread.argtypes = []
    get_current_thread.restype = wintypes.HANDLE
    open_thread_token = advapi32.OpenThreadToken
    open_thread_token.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.BOOL,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    open_thread_token.restype = wintypes.BOOL
    duplicate_token = advapi32.DuplicateTokenEx
    duplicate_token.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.INT,
        wintypes.INT,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    duplicate_token.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    source_token = wintypes.HANDLE()
    primary_token = wintypes.HANDLE()
    # Revert even when the API raises after changing the thread token.  A
    # native call can have side effects before a Python wrapper surfaces a
    # BaseException, so the attempt itself is the cleanup boundary.
    impersonation_attempted = False
    failure: Optional[BaseException] = None
    client_sid: Optional[str] = None
    try:
        impersonation_attempted = True
        if not impersonate(wintypes.HANDLE(handle)):
            raise GuardianServiceError("pipe_client_impersonation_failed")
        if not open_thread_token(
            get_current_thread(),
            _TOKEN_QUERY | _TOKEN_DUPLICATE,
            True,
            ctypes.byref(source_token),
        ):
            raise GuardianServiceError("pipe_client_token_unavailable")
        if not source_token.value:
            raise GuardianServiceError("pipe_client_token_unavailable")
        client_sid = _token_user_sid(int(source_token.value))
        if not hmac.compare_digest(client_sid, expected_client_sid):
            raise GuardianServiceError("pipe_client_identity_mismatch")
        # The coordinator uses this token only for readback, the fixed
        # SessionId=0 adjustment, and CreateProcessAsUserW.  It never duplicates
        # the token again, so do not grant TOKEN_DUPLICATE to the child.
        desired_access = _TOKEN_QUERY | _TOKEN_ASSIGN_PRIMARY
        if include_session_adjustment:
            desired_access |= _TOKEN_ADJUST_SESSIONID
        if not duplicate_token(
            source_token,
            desired_access,
            None,
            _SECURITY_IMPERSONATION,
            _TOKEN_PRIMARY,
            ctypes.byref(primary_token),
        ):
            raise GuardianServiceError("pipe_client_primary_token_unavailable")
        if not primary_token.value:
            raise GuardianServiceError("pipe_client_primary_token_unavailable")
    except BaseException as error:
        failure = error
    finally:
        if impersonation_attempted:
            _revert_pipe_impersonation_or_fail_stop(advapi32)
        if source_token.value:
            try:
                closed = bool(close_handle(source_token))
            except BaseException:
                closed = False
            if not closed and failure is None:
                failure = GuardianServiceError("pipe_client_token_close_failed")

    if failure is not None:
        primary_close_failed = False
        if primary_token.value:
            try:
                primary_close_failed = not bool(close_handle(primary_token))
            except BaseException:
                primary_close_failed = True
        if isinstance(failure, GuardianServiceThreadFatalError):
            # Reversion failure takes precedence: the service process must
            # terminate even if this additional token-handle close failed.
            raise failure
        if primary_close_failed:
            raise GuardianServiceError("pipe_client_primary_token_close_failed") from None
        if isinstance(failure, GuardianServiceError):
            raise failure
        if isinstance(failure, Exception):
            raise GuardianServiceError("pipe_client_token_capture_failed") from None
        raise failure

    try:
        pid_after = _client_pid_from_pipe(handle)
        primary_sid = _token_user_sid(int(primary_token.value))
    except BaseException:
        primary_sid = None
        pid_after = None
    if (
        pid_after != pid_before
        or primary_sid is None
        or client_sid is None
        or not hmac.compare_digest(primary_sid, expected_client_sid)
    ):
        primary_close_failed = False
        try:
            primary_close_failed = not bool(close_handle(primary_token))
        except BaseException:
            primary_close_failed = True
        if primary_close_failed:
            raise GuardianServiceError("pipe_client_primary_token_close_failed")
        raise GuardianServiceError("pipe_client_token_binding_changed")
    return _AuthenticatedPipeClientToken(int(primary_token.value), client_sid, pid_before, kernel32)


def _valid_sid_text(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"S-1-(?:[0-9]+-){1,14}[0-9]+", value) is not None


class _BoundedWorkerOutput:
    """Nonblocking, cap+1 reader owned by the service thread."""

    def __init__(self, read_handle: int, *, max_bytes: int = READONLY_MAX_OUTPUT_BYTES):
        if type(read_handle) is not int or read_handle <= 0:
            raise GuardianServiceError("worker_output_handle_invalid")
        if type(max_bytes) is not int or max_bytes <= 0:
            raise GuardianServiceError("worker_output_limit_invalid")
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._handle = read_handle
        self._max_bytes = max_bytes
        self._buffer = bytearray()
        self._eof = False
        self._failure: Optional[str] = None

    def poll_abort_reason(self) -> Optional[str]:
        """Drain only currently available bytes; never wait for worker output."""

        if self._failure is not None:
            return self._failure
        if self._eof:
            return None
        kernel32 = self._kernel32
        peek = kernel32.PeekNamedPipe
        peek.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.LPVOID,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        peek.restype = wintypes.BOOL
        available = wintypes.DWORD()
        if not peek(wintypes.HANDLE(self._handle), None, 0, None, ctypes.byref(available), None):
            if int(ctypes.get_last_error()) == _ERROR_BROKEN_PIPE:
                self._eof = True
                return None
            self._failure = "worker_output_poll_failed"
            return self._failure
        count = int(available.value)
        if count <= 0:
            return None
        remaining = self._max_bytes + 1 - len(self._buffer)
        if remaining <= 0:
            self._failure = "worker_output_limit_exceeded"
            return self._failure
        read_size = min(count, remaining)
        native_buffer = ctypes.create_string_buffer(read_size)
        read = kernel32.ReadFile
        read.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        read.restype = wintypes.BOOL
        received = wintypes.DWORD()
        if not read(
            wintypes.HANDLE(self._handle),
            native_buffer,
            read_size,
            ctypes.byref(received),
            None,
        ):
            self._failure = "worker_output_read_failed"
            return self._failure
        actual = int(received.value)
        if actual > read_size:
            self._failure = "worker_output_read_invalid"
            return self._failure
        self._buffer.extend(native_buffer.raw[:actual])
        if len(self._buffer) > self._max_bytes:
            self._failure = "worker_output_limit_exceeded"
            return self._failure
        return None

    def read_after_job_empty(
        self,
        *,
        deadline_monotonic: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> bytes:
        """Read the final bounded bytes only after independent Job-empty proof."""

        if not callable(monotonic) or not math.isfinite(float(deadline_monotonic)):
            raise GuardianServiceError("worker_output_deadline_invalid")
        while not self._eof:
            if float(monotonic()) >= float(deadline_monotonic):
                raise GuardianServiceError("worker_output_deadline_exceeded")
            reason = self.poll_abort_reason()
            if reason is not None:
                raise GuardianServiceError(reason)
            if not self._eof:
                time.sleep(min(0.001, max(0.0, float(deadline_monotonic) - float(monotonic()))))
        return bytes(self._buffer)

    def close(self) -> bool:
        if self._handle is None:
            return True
        handle = self._handle
        try:
            close = self._kernel32.CloseHandle
            close.argtypes = [wintypes.HANDLE]
            close.restype = wintypes.BOOL
            closed = bool(close(wintypes.HANDLE(handle)))
        except BaseException:
            return False
        if closed:
            self._handle = None
        return closed


def _create_worker_stdio_handles(*, service_sid: str) -> tuple[int, int, int]:
    """Create service-owned output/NUL handles; only these enter HANDLE_LIST."""

    if os.name != "nt":
        raise GuardianServiceError("windows_required")
    if not _valid_sid_text(service_sid):
        raise GuardianServiceError("pipe_identity_binding_invalid")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    read_handle = wintypes.HANDLE()
    write_handle = wintypes.HANDLE()
    null_handle = wintypes.HANDLE()
    security_descriptor = None
    try:
        attributes, security_descriptor = _create_pipe_security_attributes(
            service_sid=service_sid, client_sid=service_sid
        )
        attributes.bInheritHandle = True
        create_pipe = kernel32.CreatePipe
        create_pipe.argtypes = [
            ctypes.POINTER(wintypes.HANDLE),
            ctypes.POINTER(wintypes.HANDLE),
            ctypes.POINTER(_SECURITY_ATTRIBUTES),
            wintypes.DWORD,
        ]
        create_pipe.restype = wintypes.BOOL
        if not create_pipe(
            ctypes.byref(read_handle), ctypes.byref(write_handle), ctypes.byref(attributes), 0
        ):
            raise GuardianServiceError("worker_output_pipe_create_failed")
        local_free = kernel32.LocalFree
        local_free.argtypes = [wintypes.HLOCAL]
        local_free.restype = wintypes.HLOCAL
        if local_free(wintypes.HLOCAL(security_descriptor.value)):
            raise GuardianServiceError("worker_pipe_descriptor_release_failed")
        security_descriptor = None
        set_handle_information = kernel32.SetHandleInformation
        set_handle_information.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
        set_handle_information.restype = wintypes.BOOL
        if not set_handle_information(read_handle, _HANDLE_FLAG_INHERIT, 0):
            raise GuardianServiceError("worker_output_read_handle_protect_failed")
        # A valid inert stdin and isolated stderr prevent input from blocking on
        # the output pipe or diagnostics from corrupting its canonical JSON.
        attributes, security_descriptor = _create_pipe_security_attributes(
            service_sid=service_sid, client_sid=service_sid
        )
        attributes.bInheritHandle = True
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(_SECURITY_ATTRIBUTES),
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create_file.restype = wintypes.HANDLE
        null_handle = create_file(
            "NUL",
            _GENERIC_READ | _GENERIC_WRITE,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            ctypes.byref(attributes),
            _OPEN_EXISTING,
            _FILE_ATTRIBUTE_NORMAL,
            None,
        )
        local_free = kernel32.LocalFree
        local_free.argtypes = [wintypes.HLOCAL]
        local_free.restype = wintypes.HLOCAL
        if local_free(wintypes.HLOCAL(security_descriptor.value)):
            raise GuardianServiceError("worker_null_descriptor_release_failed")
        security_descriptor = None
        null_value = _native_handle_value(null_handle)
        if null_value == 0 or null_value == ctypes.c_void_p(-1).value:
            raise GuardianServiceError("worker_null_stdio_unavailable")
    except BaseException:
        cleanup_failed = False
        for handle in (read_handle, write_handle, null_handle):
            if handle:
                try:
                    if not kernel32.CloseHandle(handle):
                        cleanup_failed = True
                except BaseException:
                    cleanup_failed = True
        if security_descriptor:
            try:
                local_free = kernel32.LocalFree
                local_free.argtypes = [wintypes.HLOCAL]
                local_free.restype = wintypes.HLOCAL
                if local_free(wintypes.HLOCAL(security_descriptor.value)):
                    cleanup_failed = True
            except BaseException:
                cleanup_failed = True
        if cleanup_failed:
            raise GuardianServiceError("worker_stdio_cleanup_unconfirmed") from None
        raise
    return (
        int(read_handle.value),
        int(write_handle.value),
        _native_handle_value(null_handle),
    )


def _create_pipe_security_attributes(*, service_sid: str, client_sid: str):
    """Build a protected DACL for the bound service and client identities."""

    if not _valid_sid_text(service_sid) or not _valid_sid_text(client_sid):
        raise GuardianServiceError("pipe_identity_binding_invalid")
    trustees = [service_sid]
    if client_sid != service_sid:
        trustees.append(client_sid)
    sddl = "D:P" + "".join("(A;;GA;;;{})".format(sid) for sid in trustees)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    convert_sddl = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert_sddl.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.DWORD),
    ]
    convert_sddl.restype = wintypes.BOOL
    security_descriptor = wintypes.LPVOID()
    if not convert_sddl(sddl, 1, ctypes.byref(security_descriptor), None):
        raise GuardianServiceError("pipe_security_descriptor_unavailable")
    attributes = _SECURITY_ATTRIBUTES(
        ctypes.sizeof(_SECURITY_ATTRIBUTES), security_descriptor, False
    )
    return attributes, security_descriptor


def _readonly_pipe_client_access_mask() -> int:
    """Return specific client rights without FILE_CREATE_PIPE_INSTANCE."""

    rights = (
        _FILE_READ_DATA
        | _FILE_WRITE_DATA
        | _FILE_READ_ATTRIBUTES
        | _FILE_WRITE_ATTRIBUTES
        | _READ_CONTROL
        | _SYNCHRONIZE
    )
    if rights != _READONLY_PIPE_CLIENT_ACCESS or rights & _FILE_APPEND_DATA:
        raise GuardianServiceError("readonly_pipe_access_policy_invalid")
    return rights


def _readonly_pipe_sddl(*, service_sid: str, client_sid: str) -> str:
    """Create the one allowed OS-token endpoint DACL, excluding client pipe creation."""

    _bind_service_sid(service_sid)
    if not _valid_sid_text(client_sid) or hmac.compare_digest(service_sid, client_sid):
        raise GuardianServiceError("readonly_pipe_identity_binding_invalid")
    client_mask = _readonly_pipe_client_access_mask()
    return "D:P(A;;GA;;;{})(A;;0x{:08X};;;{})".format(service_sid, client_mask, client_sid)


def _create_readonly_pipe_security_attributes(*, service_sid: str, client_sid: str):
    """Create a service-only create-instance ACL for the OS-token endpoint."""

    sddl = _readonly_pipe_sddl(service_sid=service_sid, client_sid=client_sid)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    convert_sddl = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert_sddl.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.DWORD),
    ]
    convert_sddl.restype = wintypes.BOOL
    security_descriptor = wintypes.LPVOID()
    if not convert_sddl(sddl, 1, ctypes.byref(security_descriptor), None):
        raise GuardianServiceError("readonly_pipe_security_descriptor_unavailable")
    attributes = _SECURITY_ATTRIBUTES(
        ctypes.sizeof(_SECURITY_ATTRIBUTES), security_descriptor, False
    )
    return attributes, security_descriptor


def _open_readonly_pipe_client_handle(address: str, *, timeout_ms: int = 1000) -> int:
    """Open a fixed endpoint using explicit data rights, never GENERIC_WRITE."""

    if os.name != "nt":
        raise GuardianServiceError("windows_required")
    address = _validate_pipe_address(address)
    if type(timeout_ms) is not int or not 0 < timeout_ms <= 600_000:
        raise GuardianServiceError("readonly_pipe_connect_timeout_invalid")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    wait_named_pipe = kernel32.WaitNamedPipeW
    wait_named_pipe.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    wait_named_pipe.restype = wintypes.BOOL
    if not wait_named_pipe(address, timeout_ms):
        raise GuardianServiceError("readonly_pipe_unavailable")
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_SECURITY_ATTRIBUTES),
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        address,
        _readonly_pipe_client_access_mask(),
        0,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_OVERLAPPED,
        None,
    )
    value = _native_handle_value(handle)
    if value == 0 or value == ctypes.c_void_p(-1).value:
        raise GuardianServiceError("readonly_pipe_open_failed")
    set_mode = kernel32.SetNamedPipeHandleState
    set_mode.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    set_mode.restype = wintypes.BOOL
    mode = wintypes.DWORD(0x00000002)  # PIPE_READMODE_MESSAGE
    if not set_mode(wintypes.HANDLE(value), ctypes.byref(mode), None, None):
        try:
            closed = bool(kernel32.CloseHandle(wintypes.HANDLE(value)))
        except BaseException:
            closed = False
        if not closed:
            _retain_failed_windows_cleanup(_NativeHandleCustody(value, kernel32))
            raise GuardianServiceError("readonly_pipe_mode_and_handle_cleanup_unconfirmed")
        raise GuardianServiceError("readonly_pipe_mode_unavailable")
    return value


def _create_readonly_pipe_server_handle(address: str, *, service_sid: str, client_sid: str) -> int:
    """Create the one first-instance, local-only, overlapped readonly endpoint."""

    if os.name != "nt":
        raise GuardianServiceError("windows_required")
    address = _validate_pipe_address(address)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_pipe = kernel32.CreateNamedPipeW
    create_pipe.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_SECURITY_ATTRIBUTES),
    ]
    create_pipe.restype = wintypes.HANDLE
    # CreateNamedPipe captures the descriptor during this call; retain both the
    # ctypes SECURITY_ATTRIBUTES and LocalAlloc descriptor until it returns.
    attributes, security_descriptor = _create_readonly_pipe_security_attributes(
        service_sid=service_sid, client_sid=client_sid
    )
    value = 0
    try:
        open_mode = 0x00000003 | 0x40000000 | 0x00080000
        pipe_mode = 0x00000004 | 0x00000002 | _PIPE_REJECT_REMOTE_CLIENTS
        handle = create_pipe(
            address,
            open_mode,
            pipe_mode,
            1,
            _READONLY_OS_RESPONSE_MAX_BYTES,
            _MAX_MESSAGE_BYTES,
            0,
            ctypes.byref(attributes),
        )
        value = _native_handle_value(handle)
        if value == 0 or value == ctypes.c_void_p(-1).value:
            value = 0
            raise GuardianServiceError("readonly_pipe_create_failed")
        return value
    finally:
        local_free = kernel32.LocalFree
        local_free.argtypes = [wintypes.HLOCAL]
        local_free.restype = wintypes.HLOCAL
        if local_free(wintypes.HLOCAL(security_descriptor.value)):
            if value:
                custody = _NativeHandleCustody(value, kernel32)
                if not custody.close():
                    _retain_failed_windows_cleanup(custody)
                    raise GuardianServiceError(
                        "readonly_pipe_descriptor_and_handle_cleanup_unconfirmed"
                    )
            raise GuardianServiceError("readonly_pipe_descriptor_release_failed")


def _create_service_only_token_pipe(service_sid: str, nonce: str) -> tuple[int, str]:
    """Create one fixed service-only message pipe for an owner-token frame."""

    if os.name != "nt" or not _valid_sid_text(service_sid):
        raise GuardianServiceError("token_pipe_binding_invalid")
    _bind_service_sid(service_sid)
    if type(nonce) is not str or _REQUEST_ID_RE.fullmatch(nonce) is None:
        raise GuardianServiceError("token_pipe_binding_invalid")
    address = _TOKEN_CONTROL_PIPE_PREFIX + nonce
    sddl = "D:P(A;;GA;;;SY)(A;;GA;;;{})".format(service_sid)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    convert = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.DWORD),
    ]
    convert.restype = wintypes.BOOL
    descriptor = wintypes.LPVOID()
    if not convert(sddl, 1, ctypes.byref(descriptor), None):
        raise GuardianServiceError("token_pipe_security_unavailable")
    attributes = _SECURITY_ATTRIBUTES(ctypes.sizeof(_SECURITY_ATTRIBUTES), descriptor, False)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_pipe = kernel32.CreateNamedPipeW
    create_pipe.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_SECURITY_ATTRIBUTES),
    ]
    create_pipe.restype = wintypes.HANDLE
    handle_value = 0
    try:
        # First instance + overlapped, message-mode, reject remote clients.
        handle = create_pipe(
            address,
            0x00000003 | _FILE_FLAG_OVERLAPPED | 0x00080000,
            0x00000004 | 0x00000002 | _PIPE_REJECT_REMOTE_CLIENTS,
            1,
            _TOKEN_BOOTSTRAP_FRAME_MAX,
            _TOKEN_BOOTSTRAP_FRAME_MAX,
            0,
            ctypes.byref(attributes),
        )
        handle_value = _native_handle_value(handle)
        if handle_value == 0 or handle_value == ctypes.c_void_p(-1).value:
            handle_value = 0
            raise GuardianServiceError("token_pipe_create_failed")
    finally:
        local_free = kernel32.LocalFree
        local_free.argtypes = [wintypes.HLOCAL]
        local_free.restype = wintypes.HLOCAL
        if local_free(wintypes.HLOCAL(descriptor.value)):
            if handle_value and not _close_readonly_native_handle(handle_value):
                raise GuardianServiceError("token_pipe_descriptor_cleanup_unconfirmed")
            raise GuardianServiceError("token_pipe_descriptor_release_failed")
    return handle_value, address


class _OwnerTokenControlServer:
    """One-shot server that duplicates the authenticated owner token into a suspended coordinator."""

    def __init__(
        self,
        *,
        service_sid: str,
        expected_owner_sid: str,
        owner_token: _AuthenticatedPipeClientToken,
        request_id: str,
        deadline_monotonic_ns: int,
    ) -> None:
        if (
            type(request_id) is not str
            or _REQUEST_ID_RE.fullmatch(request_id) is None
            or type(deadline_monotonic_ns) is not int
            or deadline_monotonic_ns <= 0
            or type(owner_token) is not _AuthenticatedPipeClientToken
            or owner_token._closed
            or owner_token.client_sid != expected_owner_sid
        ):
            raise GuardianServiceError("token_pipe_binding_invalid")
        _bind_service_sid(service_sid)
        try:
            from scripts.ctp_i13_i15_readonly_token_bootstrap import (
                WindowsTokenSessionApi,
                _read_token_facts,
            )
        except ImportError:
            raise GuardianServiceError("token_bootstrap_unavailable") from None
        token_facts = WindowsTokenSessionApi().query_token_facts(owner_token.handle)
        owner_sid, authentication_id, source_session_id, stable_digest = _read_token_facts(
            token_facts
        )
        if owner_sid != expected_owner_sid:
            raise GuardianServiceError("token_pipe_owner_binding_mismatch")
        nonce = uuid.uuid4().hex
        pipe_handle, address = _create_service_only_token_pipe(service_sid, nonce)
        self.service_sid = service_sid
        self.owner_sid = expected_owner_sid
        self.owner_token = owner_token
        self.request_id = request_id
        self.nonce = nonce
        self.server_pid = int(os.getpid())
        self.address = address
        self.pipe_handle: Optional[int] = pipe_handle
        self.deadline_monotonic_ns = deadline_monotonic_ns
        self.authentication_id = authentication_id
        self.source_session_id = source_session_id
        self.token_facts_sha256 = stable_digest
        self.coordinator_pid: Optional[int] = None
        self.coordinator_handle: Optional[int] = None  # borrowed from the Job backend
        self.coordinator_creation_filetime: Optional[int] = None
        self.remote_token_handle: Optional[int] = None
        self._sent = False

    @property
    def binding(self) -> MappingProxyType:
        return MappingProxyType({"nonce": self.nonce, "server_pid": self.server_pid})

    def bind_suspended_coordinator(self, pid: int, process_handle: int) -> bool:
        """Duplicate the token only after the backend proved in-Job suspension."""

        if (
            self.coordinator_pid is not None
            or type(pid) is not int
            or pid <= 0
            or type(process_handle) is not int
            or process_handle <= 0
            or _process_id_from_handle(process_handle) != pid
            or not _process_is_live(process_handle)
        ):
            return False
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_current = kernel32.GetCurrentProcess
        get_current.argtypes = []
        get_current.restype = wintypes.HANDLE
        duplicate = kernel32.DuplicateHandle
        duplicate.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        duplicate.restype = wintypes.BOOL
        remote = wintypes.HANDLE()
        if not duplicate(
            get_current(),
            wintypes.HANDLE(self.owner_token.handle),
            wintypes.HANDLE(process_handle),
            ctypes.byref(remote),
            0,
            False,
            0x00000002,  # DUPLICATE_SAME_ACCESS; no inheritance.
        ):
            return False
        remote_value = _native_handle_value(remote)
        if remote_value <= 0:
            return False
        creation = _process_creation_filetime(process_handle)
        if _process_id_from_handle(process_handle) != pid or not _process_is_live(process_handle):
            self._close_remote_token(process_handle, remote_value)
            return False
        self.coordinator_pid = pid
        self.coordinator_handle = process_handle
        self.coordinator_creation_filetime = creation
        self.remote_token_handle = remote_value
        return True

    @staticmethod
    def _close_remote_token(process_handle: int, remote_token_handle: int) -> bool:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_current = kernel32.GetCurrentProcess
        get_current.argtypes = []
        get_current.restype = wintypes.HANDLE
        duplicate = kernel32.DuplicateHandle
        duplicate.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        duplicate.restype = wintypes.BOOL
        local = wintypes.HANDLE()
        return bool(
            duplicate(
                wintypes.HANDLE(process_handle),
                wintypes.HANDLE(remote_token_handle),
                get_current(),
                ctypes.byref(local),
                0,
                False,
                0x00000003,  # DUPLICATE_CLOSE_SOURCE | DUPLICATE_SAME_ACCESS.
            )
        )

    def send_after_resume(self) -> Optional[str]:
        """Connect once and send the exact token frame within the request deadline."""

        if (
            self._sent
            or self.pipe_handle is None
            or self.coordinator_pid is None
            or self.coordinator_handle is None
            or self.coordinator_creation_filetime is None
            or self.remote_token_handle is None
        ):
            return "token_pipe_binding_incomplete"
        now_ns = time.monotonic_ns()
        if now_ns >= self.deadline_monotonic_ns:
            return "token_pipe_deadline_exceeded"
        deadline = float(self.deadline_monotonic_ns) / 1_000_000_000.0
        result: Optional[str] = None
        try:
            _connect_readonly_pipe_server(self.pipe_handle, deadline_monotonic=deadline)
            if (
                _client_pid_from_pipe(self.pipe_handle) != self.coordinator_pid
                or _process_id_from_handle(self.coordinator_handle) != self.coordinator_pid
                or _process_creation_filetime(self.coordinator_handle)
                != self.coordinator_creation_filetime
                or not _process_is_live(self.coordinator_handle)
            ):
                result = "token_pipe_peer_binding_changed"
            else:
                value = {
                    "schema": "ctp_i13_i15_readonly_token_bootstrap.v1",
                    "request_id": self.request_id,
                    "nonce": self.nonce,
                    "remote_primary_token_handle": self.remote_token_handle,
                    "owner_sid": self.owner_sid,
                    "authentication_id": {
                        "high": self.authentication_id[0],
                        "low": self.authentication_id[1],
                    },
                    "source_session_id": self.source_session_id,
                    "token_facts_sha256": self.token_facts_sha256,
                }
                try:
                    from scripts.ctp_i13_i15_readonly_token_bootstrap import (
                        encode_token_bootstrap_frame,
                    )
                except ImportError:
                    result = "token_bootstrap_unavailable"
                else:
                    body = encode_token_bootstrap_frame(value)
                    framed = len(body).to_bytes(4, "big") + body
                    if time.monotonic_ns() >= self.deadline_monotonic_ns:
                        result = "token_pipe_deadline_exceeded"
                    else:
                        _write_readonly_pipe_message(
                            self.pipe_handle,
                            framed,
                            max_bytes=_TOKEN_BOOTSTRAP_FRAME_MAX + 4,
                            deadline_monotonic=deadline,
                        )
                        if (
                            _client_pid_from_pipe(self.pipe_handle) != self.coordinator_pid
                            or _process_id_from_handle(self.coordinator_handle)
                            != self.coordinator_pid
                            or _process_creation_filetime(self.coordinator_handle)
                            != self.coordinator_creation_filetime
                            or not _process_is_live(self.coordinator_handle)
                        ):
                            result = "token_pipe_peer_binding_changed"
                        elif not _wait_token_pipe_message_consumed(
                            self.pipe_handle, self.deadline_monotonic_ns
                        ):
                            result = "token_pipe_client_read_unconfirmed"
                        else:
                            self._sent = True
        except BaseException:
            result = "token_pipe_send_failed"
        finally:
            pipe_handle = self.pipe_handle
            close_failed = pipe_handle is not None and not _close_readonly_native_handle(
                pipe_handle
            )
            if pipe_handle is not None and not close_failed:
                self.pipe_handle = None
        if close_failed:
            return "token_pipe_close_unconfirmed"
        return result

    def close(self) -> bool:
        """Retryably close the one-shot control endpoint.

        The duplicated owner token belongs to the coordinator process.  That
        process is contained by Job1; if its exit cannot be confirmed, its
        handle remains covered by the unresolved Job rather than being closed
        through a possibly stale PID.
        """

        handle = self.pipe_handle
        if handle is None:
            return True
        if not _close_readonly_native_handle(handle):
            return False
        self.pipe_handle = None
        return True


_TOKEN_BOOTSTRAP_FRAME_MAX = 4096


def _wait_token_pipe_message_consumed(pipe_handle: int, deadline_monotonic_ns: int) -> bool:
    """Wait boundedly until the coordinator has read the complete frame.

    The server closes only after the client-side PID check can run while the
    pipe remains connected; close then supplies EOF to the reader.
    """

    if type(pipe_handle) is not int or pipe_handle <= 0:
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    peek = kernel32.PeekNamedPipe
    peek.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    peek.restype = wintypes.BOOL
    while time.monotonic_ns() < deadline_monotonic_ns:
        available = wintypes.DWORD()
        if not peek(
            wintypes.HANDLE(pipe_handle),
            None,
            0,
            None,
            ctypes.byref(available),
            None,
        ):
            return False
        if available.value == 0:
            return True
        time.sleep(0.001)
    return False


def _wait_for_overlapped_io(
    overlapped: object,
    *,
    deadline_monotonic: float,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Wait for one overlapped pipe operation without extending its deadline."""

    try:
        import _winapi
    except ImportError:
        raise GuardianServiceError("readonly_pipe_overlapped_unavailable") from None
    try:
        remaining = float(deadline_monotonic) - float(monotonic())
    except BaseException:
        remaining = 0.0
    if remaining <= 0.0:
        try:
            overlapped.cancel()
        except BaseException:
            pass
        raise GuardianServiceError("readonly_pipe_io_deadline_exceeded")
    timeout_ms = max(1, min(600_000, math.ceil(remaining * 1000.0)))
    try:
        result = _winapi.WaitForMultipleObjects([overlapped.event], False, timeout_ms)
    except BaseException:
        try:
            overlapped.cancel()
        except BaseException:
            pass
        raise GuardianServiceError("readonly_pipe_io_wait_failed") from None
    if result == _winapi.WAIT_TIMEOUT:
        try:
            overlapped.cancel()
        except BaseException:
            pass
        raise GuardianServiceError("readonly_pipe_io_deadline_exceeded")
    if result != _WAIT_OBJECT_0:
        try:
            overlapped.cancel()
        except BaseException:
            pass
        raise GuardianServiceError("readonly_pipe_io_wait_failed")


def _read_readonly_pipe_message(
    handle: int,
    *,
    max_bytes: int,
    deadline_monotonic: float,
    monotonic: Callable[[], float] = time.monotonic,
) -> bytes:
    """Read exactly one bounded message-mode pipe record with a finite wait."""

    if type(handle) is not int or handle <= 0 or type(max_bytes) is not int or max_bytes <= 0:
        raise GuardianServiceError("readonly_pipe_read_binding_invalid")
    try:
        import _winapi

        overlapped, error_code = _winapi.ReadFile(handle, max_bytes + 1, overlapped=True)
    except OSError as error:
        if getattr(error, "winerror", None) == _ERROR_BROKEN_PIPE:
            raise GuardianServiceError("readonly_pipe_peer_disconnected") from None
        raise GuardianServiceError("readonly_pipe_read_failed") from None
    except BaseException:
        raise GuardianServiceError("readonly_pipe_read_failed") from None
    if error_code == _ERROR_IO_PENDING:
        _wait_for_overlapped_io(
            overlapped, deadline_monotonic=deadline_monotonic, monotonic=monotonic
        )
    try:
        count, final_error = overlapped.GetOverlappedResult(True)
    except OSError as error:
        if getattr(error, "winerror", None) == _ERROR_MORE_DATA:
            raise GuardianServiceError("readonly_pipe_message_too_large") from None
        if getattr(error, "winerror", None) == _ERROR_BROKEN_PIPE:
            raise GuardianServiceError("readonly_pipe_peer_disconnected") from None
        raise GuardianServiceError("readonly_pipe_read_failed") from None
    except BaseException:
        raise GuardianServiceError("readonly_pipe_read_failed") from None
    if final_error == _ERROR_MORE_DATA or type(count) is not int or count <= 0 or count > max_bytes:
        raise GuardianServiceError("readonly_pipe_message_too_large")
    try:
        raw = bytes(overlapped.getbuffer())[:count]
    except BaseException:
        raise GuardianServiceError("readonly_pipe_read_failed") from None
    if len(raw) != count:
        raise GuardianServiceError("readonly_pipe_read_failed")
    return raw


def _write_readonly_pipe_message(
    handle: int,
    raw: bytes,
    *,
    max_bytes: int,
    deadline_monotonic: float,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Write one bounded message-mode pipe record with a finite wait."""

    if (
        type(handle) is not int
        or handle <= 0
        or type(raw) is not bytes
        or not raw
        or type(max_bytes) is not int
        or len(raw) > max_bytes
    ):
        raise GuardianServiceError("readonly_pipe_write_binding_invalid")
    try:
        import _winapi

        overlapped, error_code = _winapi.WriteFile(handle, raw, overlapped=True)
    except BaseException:
        raise GuardianServiceError("readonly_pipe_write_failed") from None
    if error_code == _ERROR_IO_PENDING:
        _wait_for_overlapped_io(
            overlapped, deadline_monotonic=deadline_monotonic, monotonic=monotonic
        )
    try:
        count, final_error = overlapped.GetOverlappedResult(True)
    except BaseException:
        raise GuardianServiceError("readonly_pipe_write_failed") from None
    if final_error or count != len(raw):
        raise GuardianServiceError("readonly_pipe_write_failed")


def _connect_readonly_pipe_server(
    handle: int,
    *,
    deadline_monotonic: float,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Accept one local client on the already-created first pipe instance."""

    if type(handle) is not int or handle <= 0:
        raise GuardianServiceError("readonly_pipe_server_handle_invalid")
    try:
        import _winapi

        overlapped = _winapi.ConnectNamedPipe(handle, overlapped=True)
    except OSError as error:
        if getattr(error, "winerror", None) == _ERROR_PIPE_CONNECTED:
            return
        raise GuardianServiceError("readonly_pipe_accept_failed") from None
    except BaseException:
        raise GuardianServiceError("readonly_pipe_accept_failed") from None
    _wait_for_overlapped_io(overlapped, deadline_monotonic=deadline_monotonic, monotonic=monotonic)
    try:
        _count, error_code = overlapped.GetOverlappedResult(True)
    except BaseException:
        raise GuardianServiceError("readonly_pipe_accept_failed") from None
    if error_code:
        raise GuardianServiceError("readonly_pipe_accept_failed")


def _close_readonly_native_handle(handle: Optional[int]) -> bool:
    """Close an owned handle, retaining custody when Windows will not close it."""

    if handle is None or handle <= 0:
        return True
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        close = kernel32.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        closed = bool(close(wintypes.HANDLE(handle)))
    except BaseException:
        closed = False
        kernel32 = None
    if closed:
        return True
    if kernel32 is not None:
        _retain_failed_windows_cleanup(_NativeHandleCustody(handle, kernel32))
    return False


class _RestrictedPipeListener:
    """One-shot AF_PIPE listener with explicit service/client SID entries."""

    def __init__(
        self, address: str, auth_key: bytes, *, expected_client_sid: Optional[str] = None
    ) -> None:
        import _winapi
        from multiprocessing import connection as mp_connection

        self._winapi = _winapi
        self._connection_module = mp_connection
        self._address = address
        self._auth_key = auth_key
        self._service_sid = _current_user_sid()
        self._expected_client_sid = (
            self._service_sid if expected_client_sid is None else expected_client_sid
        )
        if not _valid_sid_text(self._expected_client_sid):
            raise GuardianServiceError("pipe_client_binding_invalid")
        self._handle_queue = [self._new_handle(first=True)]
        self._closed = False

    def _new_handle(self, *, first: bool) -> int:
        winapi = self._winapi
        flags = winapi.PIPE_ACCESS_DUPLEX | winapi.FILE_FLAG_OVERLAPPED
        if first:
            flags |= winapi.FILE_FLAG_FIRST_PIPE_INSTANCE
        attributes, security_descriptor = _create_pipe_security_attributes(
            service_sid=self._service_sid,
            client_sid=self._expected_client_sid,
        )
        try:
            return int(
                winapi.CreateNamedPipe(
                    self._address,
                    flags,
                    winapi.PIPE_TYPE_MESSAGE
                    | winapi.PIPE_READMODE_MESSAGE
                    | winapi.PIPE_WAIT
                    | _PIPE_REJECT_REMOTE_CLIENTS,
                    2,
                    self._connection_module.BUFSIZE,
                    self._connection_module.BUFSIZE,
                    winapi.NMPWAIT_WAIT_FOREVER,
                    ctypes.addressof(attributes),
                )
            )
        finally:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            local_free = kernel32.LocalFree
            local_free.argtypes = [wintypes.HLOCAL]
            local_free.restype = wintypes.HLOCAL
            local_free(wintypes.HLOCAL(security_descriptor.value))

    def accept(self):
        winapi = self._winapi
        self._handle_queue.append(self._new_handle(first=False))
        handle = self._handle_queue.pop(0)
        try:
            try:
                overlapped = winapi.ConnectNamedPipe(handle, overlapped=True)
            except OSError as error:
                if error.winerror != winapi.ERROR_NO_DATA:
                    raise
            else:
                try:
                    winapi.WaitForMultipleObjects([overlapped.event], False, 0xFFFFFFFF)
                except BaseException:
                    overlapped.cancel()
                    handle_to_close = handle
                    handle = None
                    winapi.CloseHandle(handle_to_close)
                    raise
                _, error_code = overlapped.GetOverlappedResult(True)
                if error_code:
                    raise OSError(error_code, "named pipe connect failed")

            connection = self._connection_module.PipeConnection(handle)
            handle = None
            try:
                client_pid = _client_pid_from_pipe(connection.fileno())
                self._connection_module.deliver_challenge(connection, self._auth_key)
                client_sid = _impersonated_pipe_client_sid(connection.fileno())
                if not hmac.compare_digest(client_sid, self._expected_client_sid):
                    raise GuardianServiceError("pipe_client_identity_mismatch")
                if _client_pid_from_pipe(connection.fileno()) != client_pid:
                    raise GuardianServiceError("pipe_client_pid_changed")
                self._connection_module.answer_challenge(connection, self._auth_key)
                return connection
            except BaseException:
                connection.close()
                raise
        except BaseException:
            if handle is not None:
                winapi.CloseHandle(handle)
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for handle in self._handle_queue:
            self._winapi.CloseHandle(handle)
        self._handle_queue.clear()


def request_over_pipe(
    *,
    address: str,
    expected_service_pid: int,
    auth_key: bytes,
    request_bytes: bytes,
    deadline_monotonic: float,
    monotonic: Callable[[], float] = time.monotonic,
    before_send: Optional[Callable[[], None]] = None,
) -> PipeResponse:
    """Exchange one request with a prestarted service, bounding the caller wait.

    CPython's AF_PIPE read/write calls use infinite overlapped waits. They run
    in a daemon I/O thread; the request owner waits only through its absolute
    deadline. A late thread may still finish an exchange, but the service
    independently rejects requests whose absolute deadline has expired.
    ``before_send`` is a test seam for owner-death coverage only.
    """

    address = _validate_pipe_address(address)
    auth_key = _validate_key(auth_key)
    if type(expected_service_pid) is not int or expected_service_pid <= 0:
        raise GuardianServiceError("service_pid_invalid")
    if (
        type(request_bytes) is not bytes
        or not request_bytes
        or len(request_bytes) > _MAX_MESSAGE_BYTES
    ):
        raise GuardianServiceError("request_size_invalid")
    if not callable(monotonic) or not math.isfinite(float(deadline_monotonic)):
        raise GuardianServiceError("request_deadline_invalid")
    remaining = float(deadline_monotonic) - float(monotonic())
    if remaining <= 0.0:
        return PipeResponse("unknown", "ipc_deadline_expired_before_connect", None)

    finished = threading.Event()
    outcome: dict[str, object] = {}

    def exchange() -> None:
        connection = None
        try:
            if os.name != "nt":
                raise GuardianServiceError("windows_required")
            from multiprocessing import connection as mp_connection

            connection = mp_connection.PipeClient(address)
            server_pid = _server_pid_from_pipe(connection.fileno())
            if server_pid != expected_service_pid:
                raise GuardianServiceError("service_pipe_server_pid_mismatch")
            mp_connection.answer_challenge(connection, auth_key)
            mp_connection.deliver_challenge(connection, auth_key)
            if before_send is not None:
                before_send()
            connection.send_bytes(request_bytes)
            outcome["response"] = connection.recv_bytes(maxlength=_MAX_MESSAGE_BYTES)
        except BaseException as error:
            reason = getattr(error, "reason", None)
            if type(reason) is not str or not reason.isascii() or not reason.isidentifier():
                reason = "ipc_exchange_failed"
            outcome["reason"] = reason
        finally:
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass
            finished.set()

    io_thread = threading.Thread(target=exchange, name="ctp-inert-guardian-ipc", daemon=True)
    try:
        io_thread.start()
    except BaseException:
        return PipeResponse("unknown", "ipc_thread_start_failed", None)
    if not finished.wait(remaining):
        return PipeResponse("unknown", "ipc_deadline_exceeded", None)
    if float(monotonic()) >= float(deadline_monotonic):
        return PipeResponse("unknown", "ipc_deadline_exceeded", None)
    if "response" not in outcome:
        return PipeResponse("unknown", str(outcome.get("reason", "ipc_exchange_failed")), None)
    return PipeResponse("response", "response_received", outcome["response"])


def _receipt_payload(result: object, request_id: str) -> dict[str, object]:
    payload = _result_payload(result)
    payload.update(
        {
            "service_schema": RESPONSE_SCHEMA,
            "request_id": request_id,
            "service_pid": os.getpid(),
        }
    )
    return payload


def serve_one_inert_request(
    *,
    address: str,
    auth_key: bytes,
    python_executable: str,
    python_sha256: str,
    receipt_root: str,
    expected_client_sid: Optional[str] = None,
    ready: Optional[Callable[[str, int], None]] = None,
    before_response: Optional[Callable[[], None]] = None,
    accept_timeout_seconds: float = 120.0,
    monotonic: Callable[[], float] = time.monotonic,
    backend_factory: Callable[[], object] = WindowsJobBackend,
) -> str:
    """Serve one fixed sleep request; the caller must have prestarted us."""

    if os.name != "nt":
        raise GuardianServiceError("windows_required")
    address = _validate_pipe_address(address)
    auth_key = _validate_key(auth_key)
    if (
        type(accept_timeout_seconds) not in (int, float)
        or not math.isfinite(float(accept_timeout_seconds))
        or not 0.0 < float(accept_timeout_seconds) <= 600.0
    ):
        raise GuardianServiceError("service_accept_timeout_invalid")
    receipt_directory = Path(receipt_root)
    _validate_directory(receipt_directory, "receipt_root_invalid")
    receipt_path = receipt_directory / "guardian-receipt.json"
    if os.path.lexists(receipt_path):
        raise GuardianServiceError("guardian_receipt_already_exists")
    executable = Path(python_executable)
    if not executable.is_absolute() or not re.fullmatch(r"[0-9a-f]{64}", python_sha256):
        raise GuardianServiceError("service_python_binding_invalid")
    try:
        executable_raw = executable.read_bytes()
    except OSError:
        raise GuardianServiceError("service_python_unavailable") from None
    if not hmac.compare_digest(hashlib.sha256(executable_raw).hexdigest(), python_sha256):
        raise GuardianServiceError("service_python_digest_mismatch")

    listener = _RestrictedPipeListener(address, auth_key, expected_client_sid=expected_client_sid)
    accepted = threading.Event()
    accept_outcome: dict[str, object] = {}

    def accept_once() -> None:
        try:
            accept_outcome["connection"] = listener.accept()
        except BaseException as error:
            accept_outcome["error"] = error
        finally:
            accepted.set()

    accept_thread = threading.Thread(
        target=accept_once, name="ctp-inert-guardian-accept", daemon=True
    )
    accept_thread.start()
    if ready is not None:
        ready(address, os.getpid())
    if not accepted.wait(float(accept_timeout_seconds)):
        listener.close()
        return "service_accept_deadline_exceeded"
    connection = accept_outcome.get("connection")
    if connection is None:
        listener.close()
        return "service_accept_failed"
    listener.close()
    try:
        try:
            raw_request = connection.recv_bytes(maxlength=_MAX_MESSAGE_BYTES)
        except (EOFError, OSError):
            return "request_incomplete_or_owner_disconnected"
        try:
            request_sid = _impersonated_pipe_client_sid(connection.fileno())
        except GuardianServiceError as error:
            return str(error)
        if not hmac.compare_digest(request_sid, listener._expected_client_sid):
            return "service_request_identity_mismatch"
        request = _decode_request(raw_request, now=float(monotonic()))
        request_id = str(request["request_id"])
        child_seconds = float(request["child_seconds"])
        stop_deadline = float(request["stop_deadline_monotonic"])
        deadline = float(request["deadline_monotonic"])
        child_source = "import time; time.sleep({})".format(repr(child_seconds))
        system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        command = FixedOuterCommand(
            [
                str(executable),
                "-I",
                "-S",
                "-B",
                "-c",
                child_source,
            ],
            str(receipt_directory),
            {
                "PATH": str(executable.parent),
                "SYSTEMROOT": system_root,
                "WINDIR": os.environ.get("WINDIR", system_root),
            },
        )
        result = run_outer_watchdog(
            command,
            backend=backend_factory(),
            stop_deadline_monotonic=stop_deadline,
            deadline_monotonic=deadline,
            monotonic=monotonic,
        )
        payload = _receipt_payload(result, request_id)
        _write_receipt(receipt_path, payload)
        response = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
        if before_response is not None:
            before_response()
        try:
            connection.send_bytes(response)
        except (BrokenPipeError, EOFError, OSError):
            return "owner_disconnected_after_cleanup"
        return result.state
    except GuardianServiceError as error:
        return str(error)
    finally:
        try:
            connection.close()
        except OSError:
            pass


def _load_fixed_deployment_anchor() -> object:
    """Load only the code-owned protected deployment anchor."""

    try:
        from scripts.ctp_i13_i15_guardian_deployment_anchor import (
            load_fixed_deployment_anchor,
        )
    except ImportError:
        raise GuardianServiceError("deployment_anchor_unavailable") from None
    try:
        return load_fixed_deployment_anchor()
    except BaseException as error:
        reason = error.args[0] if getattr(error, "args", ()) else None
        if type(reason) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", reason) is None:
            reason = "deployment_anchor_unavailable"
        raise GuardianServiceError(reason) from None


def _exact_anchor_text(anchor: object, name: str, *, sha256: bool = False) -> str:
    value = getattr(anchor, name, None)
    if type(value) is not str or not value:
        raise GuardianServiceError("readonly_deployment_binding_invalid")
    if sha256 and not _is_lower_sha256(value):
        raise GuardianServiceError("readonly_deployment_binding_invalid")
    return value


def _readonly_outer_facts(result: object) -> dict[str, object]:
    evidence = getattr(result, "evidence", None)
    if evidence is None:
        raise GuardianServiceError("readonly_outer_facts_unavailable")
    facts = {
        "process_created": getattr(evidence, "process_created", None),
        "job_assignment_observed": getattr(evidence, "job_assignment_observed", None),
        "launcher_resumed": getattr(evidence, "launcher_resumed", None),
        "launcher_exit_observed": getattr(evidence, "launcher_exit_observed", None),
        "launcher_exit_code": getattr(evidence, "launcher_exit_code", None),
        "job_termination_requested": getattr(evidence, "job_termination_requested", None),
        "job_termination_call_succeeded": getattr(evidence, "job_termination_call_succeeded", None),
        "job_empty_observed": getattr(evidence, "job_empty_observed", None),
        "containment": getattr(evidence, "containment", None),
        "controls_retained": getattr(evidence, "controls_retained", None),
    }
    if any(
        value is not None and type(value) is not bool
        for key, value in facts.items()
        if key != "launcher_exit_code" and key != "containment"
    ):
        raise GuardianServiceError("readonly_outer_facts_invalid")
    if facts["launcher_exit_code"] is not None and type(facts["launcher_exit_code"]) is not int:
        raise GuardianServiceError("readonly_outer_facts_invalid")
    if type(facts["containment"]) is not str or facts["containment"] not in {
        "verified",
        "unknown",
        "not_started",
    }:
        raise GuardianServiceError("readonly_outer_facts_invalid")
    return facts


def _readonly_outer_result_is_complete(result: object) -> bool:
    if getattr(result, "state", None) != "exited":
        return False
    try:
        facts = _readonly_outer_facts(result)
    except GuardianServiceError:
        return False
    return (
        getattr(result, "reason", None) == "launcher_exited_job_empty"
        and facts["process_created"] is True
        and facts["job_assignment_observed"] is True
        and facts["launcher_resumed"] is True
        and facts["launcher_exit_observed"] is True
        and facts["launcher_exit_code"] == 0
        and facts["job_termination_requested"] is False
        and facts["job_empty_observed"] is True
        and facts["containment"] == "verified"
        and facts["controls_retained"] is False
    )


def _readonly_service_receipt(
    *,
    request_id: str,
    state: str,
    reason: str,
    outer_result: object,
    worker_observation: Optional[dict[str, object]],
) -> bytes:
    if type(request_id) is not str or _REQUEST_ID_RE.fullmatch(request_id) is None:
        raise GuardianServiceError("request_id_invalid")
    if state not in {"observed", "unknown"}:
        raise GuardianServiceError("readonly_service_state_invalid")
    if type(reason) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", reason) is None:
        raise GuardianServiceError("readonly_service_reason_invalid")
    if worker_observation is not None and type(worker_observation) is not dict:
        raise GuardianServiceError("readonly_worker_observation_invalid")
    payload = {
        "schema": READONLY_SERVICE_RECEIPT_SCHEMA,
        "operation": "ctp_readonly_preflight",
        "request_id": request_id,
        "state": state,
        "reason": reason,
        "service_pid": int(os.getpid()),
        "outer": _readonly_outer_facts(outer_result),
        "worker_observation": worker_observation,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    if len(raw) > 64 * 1024:
        raise GuardianServiceError("readonly_service_receipt_too_large")
    return raw


def _not_started_outer_result() -> object:
    return SimpleNamespace(
        state="not_started",
        reason="not_started",
        evidence=SimpleNamespace(
            process_created=False,
            job_assignment_observed=False,
            launcher_resumed=False,
            launcher_exit_observed=False,
            launcher_exit_code=None,
            job_termination_requested=False,
            job_termination_call_succeeded=None,
            job_empty_observed=None,
            containment="not_started",
            controls_retained=None,
        ),
    )


def _readonly_not_started_worker_facts() -> dict[str, object]:
    return {
        "process_created": False,
        "job_assignment_observed": False,
        "launcher_resumed": False,
        "launcher_exit_observed": False,
        "launcher_exit_code": None,
        "job_termination_requested": False,
        "job_termination_call_succeeded": None,
        "job_empty_observed": False,
        "containment": "not_started",
        "controls_retained": False,
    }


def _readonly_deployment_digest_map(anchor: object) -> dict[str, str]:
    """Return only the exact fixed role digests held by the protected anchor."""

    source_names = {
        "descriptor_sha256": "descriptor_sha256",
        "source_manifest_sha256": "source_manifest_sha256",
        "runtime_manifest_sha256": "runtime_manifest_sha256",
        "dependency_manifest_sha256": "worker_dependency_manifest_sha256",
        "python_sha256": "python_sha256",
        "i13_pin_sha256": "i13_pin_sha256",
        "i15_pin_sha256": "i15_pin_sha256",
        "bootstrap_sha256": "bootstrap_sha256",
        "worker_sha256": "worker_sha256",
        "coordinator_sha256": "request_coordinator_sha256",
        "receipt_writer_sha256": "receipt_writer_sha256",
        "token_bootstrap_sha256": "token_bootstrap_sha256",
    }
    values = {}
    for target, source in source_names.items():
        value = getattr(anchor, source, None)
        if not _is_lower_sha256(value) or value == "0" * 64:
            raise GuardianServiceError("readonly_deployment_binding_invalid")
        values[target] = value
    return values


def _fixed_readonly_service_role_command(
    anchor: object, binding_value: object, *, deadline_monotonic: float
) -> FixedOuterCommand:
    """Build one of the two code-owned service role commands.

    The role is selected only by its fixed schema.  Its binding is generated
    inside this module from the authenticated request and retained anchor; no
    caller argv, path, executable, environment, or callback reaches the child.
    """

    if type(binding_value) is not dict:
        raise GuardianServiceError("readonly_role_binding_invalid")
    schema = binding_value.get("schema")
    try:
        if schema == "ctp_i13_i15_readonly_request_coordinator_binding.v1":
            from scripts.ctp_i13_i15_readonly_request_coordinator import (
                parse_coordinator_binding,
            )

            parsed = parse_coordinator_binding(binding_value)
            normalized = {
                "schema": schema,
                "request_id": parsed.request_id,
                "deadline_monotonic_ns": parsed.deadline_monotonic_ns,
                "deployment": dict(parsed.deployment),
                "identities": {
                    "service_sid": parsed.service_sid,
                    "owner_sid": parsed.owner_sid,
                },
                "supervisor_output_channel": dict(parsed.supervisor_output_channel),
                "token_control_channel": dict(parsed.token_control_channel),
            }
        elif schema == "ctp_i13_i15_readonly_receipt_writer_binding.v1":
            from scripts.ctp_i13_i15_readonly_receipt_writer import (
                parse_receipt_writer_binding,
            )

            parsed = parse_receipt_writer_binding(binding_value)
            normalized = {
                "schema": schema,
                "request_id": parsed.request_id,
                "deadline_monotonic_ns": parsed.deadline_monotonic_ns,
                "deployment": dict(parsed.deployment),
                "work_result": dict(parsed.work_result),
                "coordinator_job": dict(parsed.coordinator_job),
                "receipt_output_channel": dict(parsed.receipt_output_channel),
            }
        else:
            raise GuardianServiceError("readonly_role_schema_invalid")
    except GuardianServiceError:
        raise
    except BaseException:
        raise GuardianServiceError("readonly_role_binding_invalid") from None

    required = (
        "source_root",
        "source_manifest_sha256",
        "descriptor_sha256",
        "python_executable",
        "python_sha256",
        "i13_pin_sha256",
        "i15_pin_sha256",
        "worker_sha256",
        "worker_dependency_manifest_sha256",
        "runtime_manifest_sha256",
        "dependency_root",
        "dependency_seal",
        "pycache_prefix",
        "bootstrap_relative_path",
        "bootstrap_sha256",
        "read_bootstrap_source",
        "verify_current",
        "verify_dependencies_current",
    )
    if any(not hasattr(anchor, name) for name in required):
        raise GuardianServiceError("readonly_bootstrap_binding_invalid")
    source_root = getattr(anchor, "source_root")
    executable = getattr(anchor, "python_executable")
    pycache_prefix = getattr(anchor, "pycache_prefix")
    bootstrap_relative_path = getattr(anchor, "bootstrap_relative_path")
    bootstrap_sha256 = getattr(anchor, "bootstrap_sha256")
    bootstrap_reader = getattr(anchor, "read_bootstrap_source")
    verify_current = getattr(anchor, "verify_current")
    verify_dependencies = getattr(anchor, "verify_dependencies_current")
    dependency_seal = getattr(anchor, "dependency_seal", None)
    dependency_root = getattr(anchor, "dependency_root", None)
    if (
        type(source_root) is not str
        or not Path(source_root).is_absolute()
        or type(executable) is not str
        or not Path(executable).is_absolute()
        or type(pycache_prefix) is not str
        or not ntpath.isabs(pycache_prefix)
        or "\0" in pycache_prefix
        or bootstrap_relative_path != _FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH
        or not _is_lower_sha256(bootstrap_sha256)
        or not callable(bootstrap_reader)
        or not callable(verify_current)
        or not callable(verify_dependencies)
        or dependency_seal is None
        or getattr(dependency_seal, "verify_current", None) is None
        or not callable(getattr(dependency_seal, "verify_current", None))
        or getattr(dependency_seal, "dependency_root", None) != dependency_root
        or getattr(dependency_seal, "manifest_sha256", None)
        != getattr(anchor, "worker_dependency_manifest_sha256", None)
    ):
        raise GuardianServiceError("readonly_bootstrap_binding_invalid")
    try:
        deadline_ns = math.floor(float(deadline_monotonic) * 1_000_000_000)
    except (TypeError, ValueError, OverflowError):
        raise GuardianServiceError("readonly_bootstrap_deadline_invalid") from None
    if (
        type(deadline_monotonic) not in (int, float)
        or not math.isfinite(float(deadline_monotonic))
        or deadline_ns <= 0
        or normalized["deadline_monotonic_ns"] != deadline_ns
    ):
        raise GuardianServiceError("readonly_bootstrap_deadline_invalid")
    deployment = _readonly_deployment_digest_map(anchor)
    if normalized.get("deployment") != deployment:
        raise GuardianServiceError("readonly_deployment_binding_mismatch")
    if schema == "ctp_i13_i15_readonly_request_coordinator_binding.v1":
        identities = normalized.get("identities")
        if (
            type(identities) is not dict
            or identities.get("service_sid") != getattr(anchor, "service_sid", None)
            or identities.get("owner_sid") != getattr(anchor, "client_sid", None)
        ):
            raise GuardianServiceError("readonly_request_identity_mismatch")

    normalized = _plain_json_value(normalized)
    if type(normalized) is not dict:
        raise GuardianServiceError("readonly_role_binding_invalid")

    try:
        verify_current()
        verify_dependencies()
        dependency_seal.verify_current()
        bootstrap_raw = bootstrap_reader()
    except BaseException:
        raise GuardianServiceError("readonly_bootstrap_source_unavailable") from None
    if (
        type(bootstrap_raw) is not bytes
        or not bootstrap_raw
        or len(bootstrap_raw) > 256 * 1024
        or not hmac.compare_digest(hashlib.sha256(bootstrap_raw).hexdigest(), bootstrap_sha256)
    ):
        raise GuardianServiceError("readonly_bootstrap_source_invalid")
    try:
        binding_raw = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        raise GuardianServiceError("readonly_role_binding_invalid") from None
    if not binding_raw or len(binding_raw) > _MAX_MESSAGE_BYTES:
        raise GuardianServiceError("readonly_role_binding_too_large")
    system_root = _windows_system_root()
    bootstrap_path = Path(source_root).joinpath(*bootstrap_relative_path.split("/"))
    return FixedOuterCommand(
        [
            executable,
            "-I",
            "-S",
            "-B",
            "-X",
            "pycache_prefix={}".format(pycache_prefix),
            str(bootstrap_path),
        ],
        source_root,
        {
            "PATH": str(Path(executable).parent),
            "SYSTEMROOT": system_root,
            "WINDIR": system_root,
            READONLY_BOOTSTRAP_BINDING_ENV: binding_raw.decode("ascii"),
        },
    )


def _readonly_job_empty_evidence(result: object) -> bool:
    """Check cleanup evidence independently of child exit status."""

    try:
        facts = _readonly_outer_facts(result)
    except GuardianServiceError:
        return False
    return (
        getattr(result, "state", None) == "exited"
        and getattr(result, "reason", None) == "launcher_exited_job_empty"
        and _job_cleanup_proven_facts(facts)
        and facts["launcher_resumed"] is True
        and facts["job_termination_requested"] is False
    )


def _run_fixed_service_role_stage(
    *,
    channel: object,
    command: FixedOuterCommand,
    backend: object,
    request_id: str,
    deadline_monotonic: float,
    stop_deadline_monotonic: Optional[float],
    after_resume: Optional[Callable[[], Optional[str]]] = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[object, Optional[bytes], Optional[str]]:
    """Run one fixed service-token role and read its frame after Job-empty."""

    try:
        from scripts.ctp_i13_i15_worker_output_channel import run_child_with_output_channel
    except ImportError:
        raise GuardianServiceError("readonly_stage_supervisor_unavailable") from None
    result = run_child_with_output_channel(
        channel,
        command,
        backend=backend,
        request_id=request_id,
        deadline_monotonic=deadline_monotonic,
        stop_deadline_monotonic=stop_deadline_monotonic,
        after_resume=after_resume,
    )
    if not _readonly_job_empty_evidence(result):
        return result, None, "job_cleanup_unverified"
    try:
        frame = channel.read_frame_after_job_empty(
            request_id=request_id,
            outer_result=result,
            deadline_monotonic=deadline_monotonic,
            monotonic=monotonic,
        )
    except BaseException as error:
        return result, None, _stage_error_reason(error, "stage_output_unverified")
    return result, frame, None


@dataclass(frozen=True)
class _ReadonlyTwoStageOutcome:
    state: str
    reason: str
    receipt_sha256: Optional[str]
    coordinator_job: dict[str, object]
    receipt_writer_job: dict[str, object]


def _plain_json_value(value: object) -> object:
    """Copy validated immutable role outputs into plain JSON containers."""

    from collections.abc import Mapping

    if isinstance(value, Mapping):
        return {key: _plain_json_value(item) for key, item in value.items()}
    if type(value) in (tuple, list):
        return [_plain_json_value(item) for item in value]
    return value


def _unknown_coordinator_result(request_id: str, reason: str) -> dict[str, object]:
    from scripts.ctp_i13_i15_readonly_request_coordinator import (
        COORDINATOR_OUTPUT_SCHEMA,
        parse_coordinator_output,
    )

    allowed = {
        "deadline_expired",
        "deployment_binding_mismatch",
        "owner_token_invalid",
        "owner_token_session_failed",
        "worker_output_invalid",
        "worker_launch_failed",
        "worker_cleanup_unverified",
        "worker_source_invalid",
        "worker_failed",
        "supervisor_channel_failed",
    }
    if reason not in allowed:
        reason = "worker_failed"
    parsed = parse_coordinator_output(
        {
            "schema": COORDINATOR_OUTPUT_SCHEMA,
            "request_id": request_id,
            "state": "unknown",
            "reason": reason,
            "worker_observation": None,
            "worker_facts": _readonly_not_started_worker_facts(),
        },
        expected_request_id=request_id,
    )
    plain = _plain_json_value(parsed)
    if type(plain) is not dict:
        raise GuardianServiceError("coordinator_output_invalid")
    return plain


def _stage_error_reason(error: BaseException, fallback: str) -> str:
    candidate = error.args[0] if getattr(error, "args", ()) else None
    if type(candidate) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", candidate):
        return candidate
    return fallback


def _run_readonly_two_stage_request(
    anchor: object,
    *,
    request_id: str,
    deadline_monotonic_ns: int,
    owner_token: _AuthenticatedPipeClientToken,
    monotonic: Callable[[], float] = time.monotonic,
    backend_factory: Callable[..., object] = WindowsJobBackend,
) -> _ReadonlyTwoStageOutcome:
    """Run coordinator+worker in Job1, then fixed receipt writer in Job2.

    No receipt or observed response is produced from the service process.  The
    receipt writer starts only after Job1's process exit, Job-empty and control
    release are independently observed by the outer watchdog.  Both stages
    receive the same absolute monotonic deadline.
    """

    from scripts.ctp_i13_i15_readonly_receipt_writer import (
        RECEIPT_BINDING_SCHEMA,
        parse_receipt_writer_frame,
        parse_receipt_writer_output,
    )
    from scripts.ctp_i13_i15_readonly_request_coordinator import (
        COORDINATOR_BINDING_SCHEMA,
        parse_coordinator_frame,
        parse_coordinator_output,
    )
    from scripts.ctp_i13_i15_worker_output_channel import (
        create_service_stage_output_channel,
    )

    not_started = _readonly_not_started_worker_facts()
    coordinator_job = dict(not_started)
    writer_job = dict(not_started)
    receipt_sha256 = None
    state = "unknown"
    reason = "coordinator_not_started"
    service_sid = _exact_anchor_text(anchor, "service_sid")
    owner_sid = _exact_anchor_text(anchor, "client_sid")
    if (
        type(request_id) is not str
        or _REQUEST_ID_RE.fullmatch(request_id) is None
        or type(deadline_monotonic_ns) is not int
        or deadline_monotonic_ns <= 0
        or not callable(monotonic)
        or not callable(backend_factory)
        or owner_token._closed
        or owner_token.client_sid != owner_sid
    ):
        return _ReadonlyTwoStageOutcome(
            state, "readonly_stage_binding_invalid", None, coordinator_job, writer_job
        )
    deadline = float(deadline_monotonic_ns) / 1_000_000_000.0
    if float(monotonic()) >= deadline:
        return _ReadonlyTwoStageOutcome(
            state, "readonly_deadline_exceeded", None, coordinator_job, writer_job
        )

    coordinator_channel = None
    token_server = None
    writer_channel = None
    try:
        coordinator_channel = create_service_stage_output_channel(service_sid=service_sid)
        token_server = _OwnerTokenControlServer(
            service_sid=service_sid,
            expected_owner_sid=owner_sid,
            owner_token=owner_token,
            request_id=request_id,
            deadline_monotonic_ns=deadline_monotonic_ns,
        )
        coordinator_binding = {
            "schema": COORDINATOR_BINDING_SCHEMA,
            "request_id": request_id,
            "deadline_monotonic_ns": deadline_monotonic_ns,
            "deployment": _readonly_deployment_digest_map(anchor),
            "identities": {"service_sid": service_sid, "owner_sid": owner_sid},
            "supervisor_output_channel": dict(coordinator_channel.bootstrap_binding),
            "token_control_channel": dict(token_server.binding),
        }
        coordinator_command = _fixed_readonly_service_role_command(
            anchor, coordinator_binding, deadline_monotonic=deadline
        )

        def bind_coordinator(pid: int, process_handle: int) -> bool:
            if not coordinator_channel.bind_suspended_worker(pid, process_handle):
                return False
            if not token_server.bind_suspended_coordinator(pid, process_handle):
                return False
            # The one-shot DuplicateHandle target now owns the remote token
            # value.  Never resume the coordinator if the source handle cannot
            # be positively closed.
            return owner_token.close() is True

        coordinator_backend = backend_factory(
            no_inherited_handles=True,
            process_created_callback=bind_coordinator,
        )
        worker_stop_deadline = deadline - _READONLY_CLEANUP_RESERVE_SECONDS
        if float(monotonic()) >= worker_stop_deadline:
            raise GuardianServiceError("readonly_cleanup_budget_exhausted")
        coordinator_result = None
        coordinator_output = None
        coordinator_frame = None
        coordinator_frame_error = None
        try:
            (
                coordinator_result,
                coordinator_frame,
                coordinator_frame_error,
            ) = _run_fixed_service_role_stage(
                channel=coordinator_channel,
                command=coordinator_command,
                backend=coordinator_backend,
                request_id=request_id,
                deadline_monotonic=deadline,
                stop_deadline_monotonic=worker_stop_deadline,
                after_resume=token_server.send_after_resume,
                monotonic=monotonic,
            )
        except BaseException as stage_error:
            reason = _stage_error_reason(stage_error, "coordinator_stage_failed")
        if coordinator_result is not None:
            coordinator_job = _readonly_outer_facts(coordinator_result)
            if not _readonly_job_empty_evidence(coordinator_result):
                return _ReadonlyTwoStageOutcome(
                    "unknown",
                    "coordinator_cleanup_unverified",
                    None,
                    coordinator_job,
                    writer_job,
                )
            if (
                getattr(coordinator_result, "state", None) == "exited"
                and getattr(coordinator_result, "reason", None) == "launcher_exited_job_empty"
            ):
                if coordinator_frame is not None:
                    try:
                        parsed_coordinator = parse_coordinator_frame(
                            coordinator_frame,
                            expected_request_id=request_id,
                            expected_nonce=str(coordinator_channel.bootstrap_binding["nonce"]),
                        )
                        coordinator_output = _plain_json_value(parsed_coordinator)
                    except BaseException as frame_error:
                        reason = _stage_error_reason(frame_error, "supervisor_channel_failed")
                else:
                    reason = coordinator_frame_error or "supervisor_channel_failed"
            else:
                reason = "deadline_expired"
        if coordinator_output is None:
            coordinator_output = _unknown_coordinator_result(
                request_id,
                reason if reason in {
                    "deadline_expired",
                    "deployment_binding_mismatch",
                    "owner_token_invalid",
                    "owner_token_session_failed",
                    "worker_output_invalid",
                    "worker_launch_failed",
                    "worker_cleanup_unverified",
                    "worker_source_invalid",
                    "worker_failed",
                    "supervisor_channel_failed",
                } else "supervisor_channel_failed",
            )
        if (
            coordinator_output["state"] == "observed"
            and coordinator_job["launcher_exit_code"] != 0
        ):
            coordinator_output = _unknown_coordinator_result(request_id, "worker_failed")
        coordinator_output = _plain_json_value(
            parse_coordinator_output(
                coordinator_output, expected_request_id=request_id
            )
        )

        if not _job_cleanup_proven_facts(coordinator_job):
            return _ReadonlyTwoStageOutcome(
                "unknown",
                "coordinator_cleanup_unverified",
                None,
                coordinator_job,
                writer_job,
            )

        if float(monotonic()) >= deadline:
            return _ReadonlyTwoStageOutcome(
                "unknown",
                "readonly_deadline_exceeded",
                None,
                coordinator_job,
                writer_job,
            )

        # Job2 is deliberately not prepared, created, or resumed until Job1 is
        # proven empty and its controls have been released.
        writer_channel = create_service_stage_output_channel(service_sid=service_sid)
        writer_binding = {
            "schema": RECEIPT_BINDING_SCHEMA,
            "request_id": request_id,
            "deadline_monotonic_ns": deadline_monotonic_ns,
            "deployment": _readonly_deployment_digest_map(anchor),
            "work_result": coordinator_output,
            "coordinator_job": coordinator_job,
            "receipt_output_channel": dict(writer_channel.bootstrap_binding),
        }
        writer_command = _fixed_readonly_service_role_command(
            anchor, writer_binding, deadline_monotonic=deadline
        )

        def bind_writer(pid: int, process_handle: int) -> bool:
            return writer_channel.bind_suspended_worker(pid, process_handle) is True

        writer_backend = backend_factory(
            no_inherited_handles=True,
            process_created_callback=bind_writer,
        )
        writer_result = None
        writer_output = None
        try:
            writer_result, writer_frame, writer_frame_error = _run_fixed_service_role_stage(
                channel=writer_channel,
                command=writer_command,
                backend=writer_backend,
                request_id=request_id,
                deadline_monotonic=deadline,
                stop_deadline_monotonic=deadline,
                monotonic=monotonic,
            )
            writer_job = _readonly_outer_facts(writer_result)
            if writer_frame is None:
                reason = writer_frame_error or "receipt_writer_output_unverified"
            else:
                writer_output = parse_receipt_writer_frame(
                    writer_frame,
                    expected_request_id=request_id,
                    expected_nonce=str(writer_channel.bootstrap_binding["nonce"]),
                )
        except BaseException as writer_error:
            reason = _stage_error_reason(writer_error, "receipt_writer_stage_failed")
            if writer_result is not None:
                writer_job = _readonly_outer_facts(writer_result)
        if writer_result is None or not _readonly_job_empty_evidence(writer_result):
            return _ReadonlyTwoStageOutcome(
                "unknown",
                "receipt_writer_cleanup_unverified",
                None,
                coordinator_job,
                writer_job,
            )
        if writer_output is None:
            return _ReadonlyTwoStageOutcome(
                "unknown",
                reason,
                None,
                coordinator_job,
                writer_job,
            )
        writer_output = parse_receipt_writer_output(
            dict(writer_output), expected_request_id=request_id
        )
        receipt_sha256 = writer_output["receipt_sha256"]
        if writer_output["state"] == "observed":
            if (
                writer_result.state != "exited"
                or writer_result.reason != "launcher_exited_job_empty"
                or writer_job["launcher_exit_code"] != 0
                or writer_output["receipt_created"] is not True
            ):
                return _ReadonlyTwoStageOutcome(
                    "unknown",
                    "receipt_writer_success_unproven",
                    None,
                    coordinator_job,
                    writer_job,
                )
            state = "observed"
            reason = "readonly_observation_complete"
        else:
            state = "unknown"
            reason = str(writer_output["reason"])
        if float(monotonic()) >= deadline:
            return _ReadonlyTwoStageOutcome(
                "unknown",
                "readonly_deadline_exceeded",
                receipt_sha256,
                coordinator_job,
                writer_job,
            )
        return _ReadonlyTwoStageOutcome(
            state, reason, receipt_sha256, coordinator_job, writer_job
        )
    except BaseException as stage_error:
        return _ReadonlyTwoStageOutcome(
            "unknown",
            _stage_error_reason(stage_error, "readonly_two_stage_failed"),
            None,
            coordinator_job,
            writer_job,
        )
    finally:
        close_failed = False
        if writer_channel is not None:
            try:
                if writer_channel.close() is not True:
                    close_failed = True
            except BaseException:
                close_failed = True
        if coordinator_channel is not None:
            try:
                if coordinator_channel.close() is not True:
                    close_failed = True
            except BaseException:
                close_failed = True
        if token_server is not None:
            try:
                if token_server.close() is not True:
                    close_failed = True
            except BaseException:
                close_failed = True
        try:
            if owner_token.close() is not True:
                close_failed = True
        except BaseException:
            close_failed = True
        # Cleanup uncertainty can never be converted back into success or a
        # normal return. Keep this as an exception so every early return above
        # is overridden if any source token/channel handle remains unconfirmed.
        if close_failed:
            raise GuardianServiceError("readonly_two_stage_cleanup_unconfirmed")


def _serve_one_readonly_os_request(
    anchor: object,
    *,
    accept_timeout_seconds: float = _READONLY_ACCEPT_TIMEOUT_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    backend_factory: Callable[..., object] = WindowsJobBackend,
) -> str:
    """Serve one authenticated request through two independently witnessed Jobs.

    Job1 contains the service-token coordinator and its owner-token worker.
    Job2 contains only the service-token receipt writer and starts after Job1
    exit, Job-empty and control release have been independently observed. The
    service never performs receipt creation or execution-lease close itself.
    Synchronous anchor/Win32 setup in this service process is still outside an
    independent host watchdog, so this path does not establish a whole-command
    hard deadline.
    """

    if os.name != "nt":
        raise GuardianServiceError("windows_required")
    if (
        type(accept_timeout_seconds) not in (int, float)
        or not math.isfinite(float(accept_timeout_seconds))
        or not 0.0 < float(accept_timeout_seconds) <= _READONLY_ACCEPT_TIMEOUT_SECONDS
        or not callable(monotonic)
        or not callable(monotonic_ns)
        or not callable(backend_factory)
    ):
        raise GuardianServiceError("readonly_service_binding_invalid")

    service_sid = _exact_anchor_text(anchor, "service_sid")
    client_sid = _exact_anchor_text(anchor, "client_sid")
    address = _validate_pipe_address(getattr(anchor, "pipe_address", None))
    _bind_service_sid(service_sid)
    verify_anchor = getattr(anchor, "verify_current", None)
    verify_dependencies = getattr(anchor, "verify_dependencies_current", None)
    close_receipt_lease = getattr(anchor, "close_receipt_lease", None)
    if not all(callable(value) for value in (verify_anchor, verify_dependencies)):
        raise GuardianServiceError("readonly_deployment_binding_invalid")

    # These fixed trust checks occur before the request has established its
    # deadline. Their synchronous Win32/filesystem calls are a known boundary;
    # they are not presented as hard-bounded by the inner Job watchdog.
    verify_anchor()
    verify_dependencies()
    _verify_current_fixed_service_identity(service_sid)

    accept_deadline = float(monotonic()) + float(accept_timeout_seconds)
    pipe_handle: Optional[int] = None
    client_token: Optional[_AuthenticatedPipeClientToken] = None
    request_id: Optional[str] = None
    deadline = accept_deadline
    outcome = _ReadonlyTwoStageOutcome(
        "unknown",
        "readonly_request_unverified",
        None,
        _readonly_not_started_worker_facts(),
        _readonly_not_started_worker_facts(),
    )
    response_sent = False
    fatal_revert = False

    try:
        pipe_handle = _create_readonly_pipe_server_handle(
            address, service_sid=service_sid, client_sid=client_sid
        )
        _connect_readonly_pipe_server(
            pipe_handle, deadline_monotonic=accept_deadline, monotonic=monotonic
        )
        receive_deadline = min(
            accept_deadline, float(monotonic()) + _READONLY_REQUEST_RECEIVE_SECONDS
        )
        request_raw = _read_readonly_pipe_message(
            pipe_handle,
            max_bytes=_MAX_MESSAGE_BYTES,
            deadline_monotonic=receive_deadline,
            monotonic=monotonic,
        )
        client_token = _authenticated_pipe_client_primary_token(
            pipe_handle, expected_client_sid=client_sid
        )
        if client_token.client_pid != _client_pid_from_pipe(pipe_handle):
            raise GuardianServiceError("pipe_client_pid_changed")
        request = _decode_readonly_os_request(
            request_raw, now_monotonic_ns=monotonic_ns()
        )
        request_id = str(request["request_id"])
        deadline_ns = int(request["deadline_monotonic_ns"])
        deadline = float(deadline_ns) / 1_000_000_000.0
        if float(monotonic()) >= deadline:
            raise GuardianServiceError("request_deadline_expired_before_coordinator")
        outcome = _run_readonly_two_stage_request(
            anchor,
            request_id=request_id,
            deadline_monotonic_ns=deadline_ns,
            owner_token=client_token,
            monotonic=monotonic,
            backend_factory=backend_factory,
        )
        client_token = None  # The two-stage owner either closed or retained it.

    except GuardianServiceThreadFatalError:
        # Do not run receipt, anchor, response, or dispatcher work while this
        # thread's impersonation context is uncertain.
        fatal_revert = True
        _fail_stop_service_process_after_revert_failure()
        raise
    except BaseException as error:
        error_reason = error.args[0] if getattr(error, "args", ()) else None
        reason = (
            error_reason
            if type(error_reason) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error_reason)
            else "readonly_service_failed"
        )
        outcome = _ReadonlyTwoStageOutcome(
            "unknown",
            reason,
            None,
            _readonly_not_started_worker_facts(),
            _readonly_not_started_worker_facts(),
        )
    finally:
        cleanup_failed = False
        if not fatal_revert and client_token is not None:
            try:
                if client_token.close() is not True:
                    cleanup_failed = True
            except BaseException:
                cleanup_failed = True
        if not fatal_revert and cleanup_failed:
            outcome = _ReadonlyTwoStageOutcome(
                "unknown",
                "readonly_service_handle_cleanup_unconfirmed",
                None,
                outcome.coordinator_job,
                outcome.receipt_writer_job,
            )

    if request_id is None:
        if pipe_handle is not None:
            if not _close_readonly_native_handle(pipe_handle):
                return "readonly_pipe_close_unconfirmed"
        return "request_rejected_before_identity"

    # Closing the service's retained receipt-directory lease is not allowed to
    # upgrade a failed result. This call is synchronous and remains part of the
    # stated whole-command deadline limitation.
    if callable(close_receipt_lease):
        try:
            close_result = close_receipt_lease()
            if close_result is False:
                raise GuardianServiceError("receipt_lease_close_unconfirmed")
        except BaseException:
            outcome = _ReadonlyTwoStageOutcome(
                "unknown",
                "receipt_lease_close_unconfirmed",
                None,
                outcome.coordinator_job,
                outcome.receipt_writer_job,
            )

    state = outcome.state
    reason = outcome.reason
    receipt_sha256 = outcome.receipt_sha256
    if state == "observed" and (
        not _job_facts_are_clean_success(outcome.coordinator_job)
        or not _job_facts_are_clean_success(outcome.receipt_writer_job)
        or receipt_sha256 is None
    ):
        state = "unknown"
        reason = "readonly_two_job_success_unproven"
        receipt_sha256 = None
    if float(monotonic()) >= deadline:
        state = "unknown"
        reason = "readonly_deadline_exceeded"
        receipt_sha256 = None
    response = {
        "schema": READONLY_OS_RESPONSE_SCHEMA,
        "request_id": request_id,
        "state": state,
        "reason": reason,
        "receipt_sha256": receipt_sha256,
        "coordinator_job": outcome.coordinator_job,
        "receipt_writer_job": outcome.receipt_writer_job,
    }
    try:
        response_raw = json.dumps(
            response, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        return "readonly_response_invalid"
    if len(response_raw) > _READONLY_OS_RESPONSE_MAX_BYTES:
        return "readonly_response_too_large"
    try:
        if pipe_handle is not None and float(monotonic()) < deadline:
            _write_readonly_pipe_message(
                pipe_handle,
                response_raw,
                max_bytes=_READONLY_OS_RESPONSE_MAX_BYTES,
                deadline_monotonic=deadline,
                monotonic=monotonic,
            )
            response_sent = True
    except BaseException:
        return "owner_disconnected_after_service_cleanup"
    finally:
        if pipe_handle is not None and not _close_readonly_native_handle(pipe_handle):
            # The response is immutable once written. The host must regard the
            # service outcome as uncertain even if the owner saw the bytes.
            state = "unknown"
            reason = "readonly_pipe_close_unconfirmed"
    return state if response_sent else "readonly_deadline_or_response_unavailable"


def serve_fixed_readonly_preflight_request() -> str:
    """Load the fixed protected anchor and serve exactly one readonly request.

    This function accepts no command-line, environment-selected, or caller
    supplied service identity, pipe, receipt path, configuration path, token,
    worker command, or timeout.
    """

    if os.name != "nt":
        raise GuardianServiceError("windows_required")
    anchor = _load_fixed_deployment_anchor()
    try:
        return _serve_one_readonly_os_request(anchor, backend_factory=WindowsJobBackend)
    finally:
        close = getattr(anchor, "close", None)
        if callable(close):
            close()


def request_fixed_readonly_preflight(
    *, hard_deadline_seconds: int = 300, ipc_timeout_seconds: int = 30
) -> PipeResponse:
    """Issue only the fixed readonly operation through the OS-token endpoint.

    ``hard_deadline_seconds`` is sent as the service's absolute operation
    deadline. ``ipc_timeout_seconds`` only bounds this caller's wait and may be
    shorter. An IPC timeout returns ``ipc_deadline_exceeded``; it does not prove
    the service worker's Job was empty or stopped. The service's watchdog and
    receipt provide that independent evidence.
    """

    if os.name != "nt":
        return PipeResponse("unknown", "windows_required", None)
    if (
        type(hard_deadline_seconds) is not int
        or not 15 <= hard_deadline_seconds <= 300
        or type(ipc_timeout_seconds) is not int
        or not 1 <= ipc_timeout_seconds <= hard_deadline_seconds
    ):
        raise GuardianServiceError("readonly_request_timeout_invalid")
    started_ns = time.monotonic_ns()
    deadline_ns = started_ns + hard_deadline_seconds * 1_000_000_000
    deadline = float(deadline_ns) / 1_000_000_000.0
    ipc_deadline = time.monotonic() + float(ipc_timeout_seconds)
    request_id = uuid.uuid4().hex
    request_raw = json.dumps(
        {
            "schema": READONLY_OS_REQUEST_SCHEMA,
            "operation": "ctp_readonly_preflight",
            "request_id": request_id,
            "deadline_monotonic_ns": deadline_ns,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    finished = threading.Event()
    outcome: dict[str, object] = {}

    def exchange() -> None:
        binding = None
        server_process = None
        pipe_handle: Optional[int] = None
        failure = "readonly_ipc_failed"
        response_bytes = None
        try:
            try:
                from scripts.ctp_i13_i15_guardian_deployment_anchor import (
                    load_fixed_guardian_client_binding,
                )
            except ImportError:
                raise GuardianServiceError("guardian_client_binding_unavailable") from None
            binding = load_fixed_guardian_client_binding()
            if (
                getattr(binding, "service_name", None) != FIXED_READONLY_SERVICE_NAME
                or not callable(getattr(binding, "verify_current", None))
                or not callable(getattr(binding, "close", None))
            ):
                raise GuardianServiceError("guardian_client_binding_invalid")
            service_sid = _bind_service_sid(getattr(binding, "service_sid", None))
            client_sid = _exact_anchor_text(binding, "client_sid")
            if not hmac.compare_digest(_current_user_sid(), client_sid):
                raise GuardianServiceError("guardian_client_user_mismatch")
            address = _validate_pipe_address(getattr(binding, "pipe_address", None))
            python_executable = _exact_anchor_text(binding, "python_executable")
            python_sha256 = _exact_anchor_text(binding, "python_sha256", sha256=True)
            if not _is_lower_sha256(getattr(binding, "descriptor_sha256", None)):
                raise GuardianServiceError("guardian_client_binding_invalid")
            binding.verify_current()
            if time.monotonic() >= deadline:
                raise GuardianServiceError("ipc_deadline_exceeded")
            connect_timeout_ms = max(
                1, min(600_000, math.ceil((deadline - time.monotonic()) * 1000))
            )
            pipe_handle = _open_readonly_pipe_client_handle(address, timeout_ms=connect_timeout_ms)
            server_process = _RetainedReadonlyServerProcess.from_pipe(
                pipe_handle,
                service_sid=service_sid,
                python_executable=python_executable,
                python_sha256=python_sha256,
            )
            server_process.verify(pipe_handle)
            _write_readonly_pipe_message(
                pipe_handle,
                request_raw,
                max_bytes=_MAX_MESSAGE_BYTES,
                deadline_monotonic=deadline,
            )
            response_bytes = _read_readonly_pipe_message(
                pipe_handle,
                max_bytes=_READONLY_OS_RESPONSE_MAX_BYTES,
                deadline_monotonic=deadline,
            )
            server_process.verify(pipe_handle)
            binding.verify_current()
            _decode_readonly_os_response(response_bytes, request_id=request_id)
            if time.monotonic() >= deadline:
                raise GuardianServiceError("ipc_deadline_exceeded")
            outcome["response"] = response_bytes
        except BaseException as error:
            error_reason = error.args[0] if getattr(error, "args", ()) else None
            failure = (
                error_reason
                if type(error_reason) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error_reason)
                else "readonly_ipc_failed"
            )
            outcome["reason"] = failure
        finally:
            cleanup_failed = False
            if server_process is not None:
                if not server_process.close():
                    cleanup_failed = True
            if pipe_handle is not None and not _close_readonly_native_handle(pipe_handle):
                cleanup_failed = True
            if binding is not None:
                try:
                    binding.close()
                except BaseException:
                    cleanup_failed = True
            if cleanup_failed:
                outcome.pop("response", None)
                outcome["reason"] = "readonly_client_cleanup_unconfirmed"
            finished.set()

    try:
        thread = threading.Thread(target=exchange, name="ctp-readonly-guardian-ipc", daemon=True)
        thread.start()
    except BaseException:
        return PipeResponse("unknown", "ipc_thread_start_failed", None)
    remaining = max(0.0, ipc_deadline - time.monotonic())
    if not finished.wait(remaining):
        return PipeResponse("unknown", "ipc_deadline_exceeded", None)
    if time.monotonic() >= ipc_deadline:
        return PipeResponse("unknown", "ipc_deadline_exceeded", None)
    response = outcome.get("response")
    if type(response) is bytes:
        return PipeResponse("response", "response_received", response)
    return PipeResponse("unknown", str(outcome.get("reason", "readonly_ipc_failed")), None)


__all__ = [
    "GuardianServiceError",
    "PipeResponse",
    "REQUEST_SCHEMA",
    "RESPONSE_SCHEMA",
    "READONLY_OS_REQUEST_SCHEMA",
    "READONLY_OS_RESPONSE_SCHEMA",
    "request_fixed_readonly_preflight",
    "request_over_pipe",
    "serve_fixed_readonly_preflight_request",
    "serve_one_inert_request",
]
