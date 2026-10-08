"""Fixed read-only SimNow C01 TD worker candidate.

This module is a child-process entrypoint only.  Importing it does not import
the CTP SDK, read configuration, access credentials, or contact a provider.
The executable path verifies the exact installed SDK source/RECORD/native
bytes before importing that SDK.  Its only native request plan is
authenticate, login, then orders/positions/funds twice.  A valid receipt is
still only local evidence; the parent contract always remains BLOCKED. The
isolated worker denies Python-level process-start audit events before SDK
imports; that hook does not mediate native or direct operating-system calls.
"""

from __future__ import annotations

import base64
import csv
import ctypes
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import sys
import sysconfig
import threading
import time
import types
import unicodedata
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple


MAX_PRIVATE_PACKET_BYTES = 128 * 1024
MAX_PRIVATE_SNAPSHOT_BYTES = 8 * 1024 * 1024
MAX_PRIVATE_PROGRESS_RECORDS = 128
MAX_PRIVATE_PROGRESS_RECORD_BYTES = 4096
MAX_PRIVATE_PROGRESS_TOTAL_BYTES = 512 * 1024
MAX_STAGE_INTENT_RECORDS = 128
MAX_STAGE_INTENT_FRAME_BYTES = 1024
MAX_STAGE_INTENT_TOTAL_BYTES = 128 * 1024
STAGE_INTENT_MAGIC = b"C01INTENT\x01"
STAGE_INTENT_PROTOCOL = "simnow.c01.stage-intent.v1"
MAX_WORKER_FRAME_BYTES = 1024 * 1024
MAX_CALLBACKS = 10000
RSP_INFO_ABSENT = "RSP_INFO_ABSENT"
RSP_INFO_ERROR_ID_PRESENT = "RSP_INFO_ERROR_ID_PRESENT"
MAX_DEPENDENCY_RECORD_BYTES = 4 * 1024 * 1024
MAX_DEPENDENCY_PAYLOAD_BYTES = 64 * 1024 * 1024
MAX_DEPENDENCY_TREE_ENTRIES = 8192
MAX_CERTIFI_CA_RESOURCE_BYTES = 2 * 1024 * 1024
CERTIFI_RESOURCE_PACKAGE = "certifi"
CERTIFI_RESOURCE_NAME = "cacert.pem"
CERTIFI_RESOURCE_RELATIVE_PATH = "certifi/cacert.pem"
MAX_POSITION_TEXT_CHARS = 128
MAX_POSITION_DECIMAL_INPUT_CHARS = 128
MAX_POSITION_DECIMAL_DIGITS = 64
MAX_POSITION_DECIMAL_SCALE = 18
MAX_POSITION_DECIMAL_ABS_EXCLUSIVE = "1e30"
EXPECTED_PROTOCOL_SOURCE_SHA256 = "c48b41272ae6378060b0b65188b56ef613f001b53d13db7aceaf13489d398160"
EXPECTED_INTERPRETER_BINDING_SOURCE_SHA256 = (
    "a38d00ecfbc7a777edab4b9d090be49ef03a94e7c23340dfe95366bacfd05494"
)
DEPENDENCY_MANIFEST_FILENAME = "certification_simnow_c01_dependencies_v1.json"
EXPECTED_DEPENDENCY_MANIFEST_SHA256 = (
    "7cb851df481066ee7622aea0bdd87863d6e04d3372fb520e7685a241411f2324"
)
DEPENDENCY_MANIFEST_SCHEMA = "iteration41.simnow-c01-pure-python-dependency-manifest.v1"
QUERY_TIMEOUT_SECONDS = 5.0
LOGIN_TIMEOUT_SECONDS = 25.0
STOP_TIMEOUT_SECONDS = 30.0
_PROCESS_START_AUDIT_EVENTS = frozenset(
    {
        "os.exec",
        "os.fork",
        "os.forkpty",
        "os.posix_spawn",
        "os.spawn",
        "os.startfile",
        "os.startfile/2",
        "os.system",
        "subprocess.Popen",
    }
)
_PROCESS_START_AUDIT_PROBE = "simnow.c01.process_start_audit_probe"
_PROCESS_START_AUDIT_DENIAL = "simnow_c01_process_start_denied"

SDK_DISTRIBUTIONS = {
    "bt_api_ctp": {
        "dist_info": "bt_api_ctp-2.0.3+iteration41.i2.dist-info",
        "record_sha256": "4953ef5cb13468a300693fd3c37b7eb59c4afd0727e3d6dbcf8a15de5abebe08",
        "package": "bt_api_ctp",
        "python_files": 78,
    },
    "bt_api_py": {
        "dist_info": "bt_api_py-0.15.5.dist-info",
        "record_sha256": "b58b927aa474acb8bebf118cbce0309629aa438e3f56f6e6792c113a492e85a4",
        "package": "bt_api_py",
        "python_files": 139,
    },
    "bt_api_base": {
        "dist_info": "bt_api_base-0.15.5.dist-info",
        "record_sha256": "47994f991fee3266e62fb368fe167dc1f188eceecfddac6ccc06dad2604e9762",
        "package": "bt_api_base",
        "python_files": 105,
    },
}
_DEPENDENCY_PACKAGE_ROOTS = {
    "requests": ("requests",),
    "urllib3": ("urllib3",),
    "idna": ("idna",),
    "certifi": ("certifi",),
    "charset_normalizer": ("charset_normalizer",),
    "PyYAML": ("yaml", "_yaml"),
    "python-dotenv": ("dotenv",),
}
_DEPENDENCY_EXCLUDED_RECORD_PATHS = {
    "requests": (),
    "urllib3": (),
    "idna": (),
    "certifi": (),
    "charset_normalizer": ("../../Scripts/normalizer.exe",),
    "PyYAML": (),
    "python-dotenv": ("../../Scripts/dotenv.exe",),
}
_DEPENDENCY_IMPORT_ALIASES = {
    "requests.packages.urllib3": "urllib3",
    "requests.packages.idna": "idna",
    "requests.packages.charset_normalizer": "charset_normalizer",
    # requests.compat aliases the selected detector as both names.
    "requests.packages.chardet": "charset_normalizer",
}
SIX_SOURCE_RELATIVE_PATH = "urllib3/packages/six.py"
SIX_SOURCE_SHA256 = "6fd2ccd30057bfb13b4ab6c28c09b8c3037e86b1fe88dc6fd7c2e058d30c28fa"
_SIX_VIRTUAL_ROUTES = {}
_SIX_CANONICAL_PRODUCER = "urllib3.packages.six"
for _six_route_prefix in (
    "urllib3.packages.six",
    "requests.packages.urllib3.packages.six",
):
    _SIX_VIRTUAL_ROUTES.update(
        {
            _six_route_prefix
            + ".moves": (
                _SIX_CANONICAL_PRODUCER,
                _SIX_CANONICAL_PRODUCER + ".moves",
                "six_moves_namespace",
                "six.moves",
            ),
            _six_route_prefix
            + ".moves.http_client": (
                _SIX_CANONICAL_PRODUCER,
                _SIX_CANONICAL_PRODUCER + ".moves.http_client",
                "six_moved_module",
                "http.client",
            ),
            _six_route_prefix
            + ".moves.queue": (
                _SIX_CANONICAL_PRODUCER,
                _SIX_CANONICAL_PRODUCER + ".moves.queue",
                "six_moved_module",
                "queue",
            ),
            _six_route_prefix
            + ".moves.urllib": (
                _SIX_CANONICAL_PRODUCER,
                _SIX_CANONICAL_PRODUCER + ".moves.urllib",
                "six_urllib_namespace",
                "six.moves.urllib",
            ),
            _six_route_prefix
            + ".moves.urllib.parse": (
                _SIX_CANONICAL_PRODUCER,
                _SIX_CANONICAL_PRODUCER + ".moves.urllib.parse",
                "six_urllib_parse_module",
                "six.moves.urllib_parse",
            ),
        }
    )
del _six_route_prefix
_SIX_STDLIB_TARGET_PATHS = {
    "http.client": "http/client.py",
    "queue": "queue.py",
}
_SIX_STDLIB_PACKAGE_PATHS = {
    "http": "http/__init__.py",
}
SIX_VIRTUAL_METADATA_ROUTES = {
    name: {
        "producer_module": producer,
        "known_module_name": known_name,
        "virtual_kind": virtual_kind,
        "virtual_target": target,
        "target_origin_kind": (
            "interpreter_stdlib_moved_target"
            if virtual_kind == "six_moved_module"
            else "six_pinned_source_virtual_module"
        ),
    }
    for name, (producer, known_name, virtual_kind, target) in _SIX_VIRTUAL_ROUTES.items()
}
_FORBIDDEN_DEPENDENCY_SUFFIXES = frozenset({".exe", ".com", ".bat", ".cmd", ".scr"})
_OPTIONAL_NATIVE_DEPENDENCY_SUFFIXES = frozenset({".pyd", ".dll", ".so", ".dylib"})
PINNED_NATIVE_FILES = {
    "bt_api_ctp/ctp/_ctp.cp311-win_amd64.pyd": (
        "468eaf9b623f684959922e3d1a2970f7f5ea71c73b7495cd533732f39672ef47",
        11889152,
    ),
    "bt_api_ctp/ctp/thosttraderapi_se.dll": (
        "d79cc036fc90733a30cee8e8e30bdea17b346333c69413f33d44ebc7a96b1fad",
        3428864,
    ),
    "bt_api_ctp/ctp/thostmduserapi_se.dll": (
        "72a833786836ce6e6026bc0c19a06bd3c1b0279cb1ea9df0297b1c2916cad98b",
        3044352,
    ),
}
_CREDENTIAL_LIMITS = {
    # CTP char[N] capacities, excluding the required terminal NUL.
    "broker_id": 10,
    "user_id": 15,
    "password": 40,
    "app_id": 32,
    "auth_code": 16,
    "product_info": 10,
}
_REQUEST_PLAN = (
    ("authenticate", None, None, "ReqAuthenticate"),
    ("login", None, None, "ReqUserLogin"),
    ("query", "baseline", "orders", "ReqQryOrder"),
    ("query", "baseline", "positions", "ReqQryInvestorPosition"),
    ("query", "baseline", "funds", "ReqQryTradingAccount"),
    ("query", "final", "orders", "ReqQryOrder"),
    ("query", "final", "positions", "ReqQryInvestorPosition"),
    ("query", "final", "funds", "ReqQryTradingAccount"),
)
_CALLBACKS = {
    "ReqQryOrder": ("orders", "OnRspQryOrder"),
    "ReqQryInvestorPosition": ("positions", "OnRspQryInvestorPosition"),
    "ReqQryTradingAccount": ("funds", "OnRspQryTradingAccount"),
}
_OPEN_ORDER_STATUSES = frozenset({"1", "3", "a", "b", "c"})
_CLOSED_ORDER_STATUSES = frozenset({"0", "2", "4", "5"})
_KNOWN_ORDER_STATUSES = _OPEN_ORDER_STATUSES | _CLOSED_ORDER_STATUSES
_POSITION_SCHEMA = "simnow.c01.ctp-gross-position-buckets.v2"
_POSITION_DIMENSIONS = (
    "ExchangeID",
    "InstrumentID",
    "PosiDirection",
    "HedgeFlag",
    "PositionDate",
)
_POSITION_DECIMAL_MEASURES = (
    "YdPosition",
    "Position",
    "LongFrozen",
    "ShortFrozen",
    "LongFrozenAmount",
    "ShortFrozenAmount",
    "OpenVolume",
    "CloseVolume",
    "OpenAmount",
    "CloseAmount",
    "PositionCost",
    "PreMargin",
    "UseMargin",
    "FrozenMargin",
    "FrozenCash",
    "FrozenCommission",
    "CashIn",
    "Commission",
    "CloseProfit",
    "PositionProfit",
    "PreSettlementPrice",
    "SettlementPrice",
    "SettlementID",
    "OpenCost",
    "ExchangeMargin",
    "CombPosition",
    "CombLongFrozen",
    "CombShortFrozen",
    "CloseProfitByDate",
    "CloseProfitByTrade",
    "TodayPosition",
    "MarginRateByMoney",
    "MarginRateByVolume",
    "StrikeFrozen",
    "StrikeFrozenAmount",
    "AbandonFrozen",
    "YdStrikeFrozen",
    "PositionCostOffset",
    "TasPosition",
    "TasPositionCost",
)
_POSITION_INTEGER_QUANTITIES = frozenset(
    {
        "YdPosition",
        "Position",
        "LongFrozen",
        "ShortFrozen",
        "SettlementID",
        "OpenVolume",
        "CloseVolume",
        "CombPosition",
        "CombLongFrozen",
        "CombShortFrozen",
        "TodayPosition",
        "StrikeFrozen",
        "AbandonFrozen",
        "YdStrikeFrozen",
        "TasPosition",
    }
)
_POSITION_TEXT_MEASURES = (
    "TradingDay",
    "InvestUnitID",
    "reserve1",
)
_POSITION_EXCHANGES = frozenset({"CFFEX", "CZCE", "DCE", "GFEX", "INE", "SHFE"})
_ACCOUNT_SCHEMA = "simnow.c01.ctp-trading-account-economics.v3"
_ACCOUNT_DIMENSIONS = ("BrokerID", "AccountID", "CurrencyID", "BizType", "TradingDay")
_ACCOUNT_DECIMAL_MEASURES = (
    "PreMortgage",
    "PreCredit",
    "PreDeposit",
    "PreBalance",
    "PreMargin",
    "InterestBase",
    "Interest",
    "Deposit",
    "Withdraw",
    "FrozenMargin",
    "FrozenCash",
    "FrozenCommission",
    "CurrMargin",
    "CashIn",
    "Commission",
    "CloseProfit",
    "PositionProfit",
    "Balance",
    "Available",
    "WithdrawQuota",
    "Reserve",
    "Credit",
    "Mortgage",
    "ExchangeMargin",
    "DeliveryMargin",
    "ExchangeDeliveryMargin",
    "ReserveBalance",
    "PreFundMortgageIn",
    "PreFundMortgageOut",
    "FundMortgageIn",
    "FundMortgageOut",
    "FundMortgageAvailable",
    "MortgageableFund",
    "SpecProductMargin",
    "SpecProductFrozenMargin",
    "SpecProductCommission",
    "SpecProductFrozenCommission",
    "SpecProductPositionProfit",
    "SpecProductCloseProfit",
    "SpecProductPositionProfitByAlg",
    "SpecProductExchangeMargin",
    "FrozenSwap",
    "RemainSwap",
)
_ACCOUNT_INTEGER_MEASURES = frozenset({"SettlementID"})
_ACCOUNT_NONNEGATIVE_MEASURES = frozenset(
    {
        "SettlementID",
        "FrozenMargin",
        "FrozenCash",
        "FrozenCommission",
        "SpecProductFrozenMargin",
        "SpecProductFrozenCommission",
        "FrozenSwap",
    }
)
_ACCOUNT_DIAGNOSTIC_SOURCES = {
    "cash": "Available",
    "available_funds": "Available",
    "equity": "Balance",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FRONT_RE = re.compile(r"^tcp://(?:\d{1,3}\.){3}\d{1,3}:\d{1,5}$")
_PROGRESS_PROTOCOL = "simnow.c01.native-progress.v1"
_PROGRESS_EVENTS = frozenset({"begin", "end", "failed", "callback_first", "callback_terminal"})
_PROGRESS_STAGE_REQUEST = {
    "ReqAuthenticate": "authenticate_request",
    "ReqUserLogin": "login_request",
    ("baseline", "orders"): "baseline_orders_request",
    ("baseline", "positions"): "baseline_positions_request",
    ("baseline", "funds"): "baseline_funds_request",
    ("final", "orders"): "final_orders_request",
    ("final", "positions"): "final_positions_request",
    ("final", "funds"): "final_funds_request",
}
_PROGRESS_STAGE_CALLBACK = {
    "authenticate": "authenticate_callback",
    "login": "login_callback",
    ("baseline", "orders"): "baseline_orders_callback",
    ("baseline", "positions"): "baseline_positions_callback",
    ("baseline", "funds"): "baseline_funds_callback",
    ("final", "orders"): "final_orders_callback",
    ("final", "positions"): "final_positions_callback",
    ("final", "funds"): "final_funds_callback",
}
_PROGRESS_STAGES = frozenset(
    {
        "worker",
        "private_paths",
        "sdk_install_verify",
        "sdk_import",
        "client_construct",
        "client_start",
        "client_start_native_module_check",
        "client_no_join_start_policy",
        "client_start_generation_reserve",
        "client_start_identity_validate",
        "client_start_identity_compare",
        "client_start_flow_prepare",
        "native_create_trader_api",
        "native_register_spi_attach",
        "native_subscribe_private_topic",
        "native_subscribe_public_topic",
        "native_register_front",
        "native_api_init",
        "native_register_spi_detach",
        "native_release",
        "login_wait",
        "snapshot_directory",
        "baseline_orders_read",
        "baseline_positions_read",
        "baseline_funds_read",
        "final_orders_read",
        "final_positions_read",
        "final_funds_read",
        "baseline_snapshot_write",
        "final_snapshot_write",
        "native_stop",
        "worker_receipt",
    }
    | set(_PROGRESS_STAGE_REQUEST.values())
    | set(_PROGRESS_STAGE_CALLBACK.values())
)


class NativeAdapterError(ValueError):
    """A fixed, value-free fail-closed worker error."""


def _deny_process_start_audit_event(event: Any) -> None:
    """Deny Python process-start audit events without inspecting their args."""
    if type(event) is str and event in _PROCESS_START_AUDIT_EVENTS:
        raise PermissionError(_PROCESS_START_AUDIT_DENIAL)


def _install_process_start_audit_guard() -> None:
    """Install and verify the worker-local Python process-start guard.

    This is called only by the hash-verified isolated worker entrypoint. It is
    not installed when this module is imported by tests or the parent process.
    """
    probe_seen = False

    def audit_guard(event: str, args: Tuple[Any, ...]) -> None:
        nonlocal probe_seen
        if event == _PROCESS_START_AUDIT_PROBE:
            probe_seen = True
            return
        _deny_process_start_audit_event(event)

    try:
        sys.addaudithook(audit_guard)
        # CPython can decline an added hook when an earlier hook raises
        # RuntimeError. A private probe proves this hook actually runs.
        sys.audit(_PROCESS_START_AUDIT_PROBE)
    except BaseException:
        raise NativeAdapterError("process_start_audit_install_failed") from None
    if not probe_seen:
        raise NativeAdapterError("process_start_audit_unavailable")


class _VerifiedSdkPayloads(dict):
    """Verified importable sources/data plus separately denied native payloads."""

    def __init__(self):
        super().__init__()
        self.optional_native_payloads: Dict[Path, str] = {}
        self.dependency_manifest_sha256: Optional[str] = None


class _CandidateAbort(Exception):
    """Internal control flow.  It must never be written to a worker frame."""


class _NullTextIO:
    """Discard SDK text output without retaining potentially private strings."""

    encoding = "utf-8"

    def write(self, value: str) -> int:
        return len(value)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _strict_object(pairs: list) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NativeAdapterError("duplicate_private_input_key")
        result[key] = value
    return result


def _strict_dependency_object(pairs: list) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NativeAdapterError("dependency_manifest_invalid")
        result[key] = value
    return result


def _ensure_no_reparse_path(path: Path, *, boundary: Path, error_code: str) -> Path:
    """Require an existing absolute path and each component to be non-reparse."""

    if not path.is_absolute() or not boundary.is_absolute():
        raise NativeAdapterError(error_code)
    try:
        absolute = Path(os.path.abspath(path))
        root = Path(os.path.abspath(boundary))
        relative = absolute.relative_to(root)
        current = root
        for item in (
            current,
            *(root / Path(*relative.parts[:index]) for index in range(1, len(relative.parts) + 1)),
        ):
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise NativeAdapterError(error_code)
        resolved = absolute.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
        return resolved
    except NativeAdapterError:
        raise
    except (OSError, ValueError):
        raise NativeAdapterError(error_code) from None


def _load_dependency_manifest() -> Tuple[Dict[str, Any], str]:
    """Load the fixed, hash-pinned manifest without importlib or cached code."""

    worker_path = Path(__file__)
    try:
        if not worker_path.is_absolute():
            raise NativeAdapterError("dependency_manifest_path_invalid")
        manifest_path = worker_path.with_name(DEPENDENCY_MANIFEST_FILENAME)
        manifest_path = _ensure_no_reparse_path(
            manifest_path,
            boundary=Path(manifest_path.anchor),
            error_code="dependency_manifest_path_invalid",
        )
        if not manifest_path.is_file() or manifest_path.stat().st_size > 64 * 1024:
            raise NativeAdapterError("dependency_manifest_unavailable")
        manifest_bytes = manifest_path.read_bytes()
    except NativeAdapterError:
        raise
    except OSError:
        raise NativeAdapterError("dependency_manifest_unavailable") from None
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_sha256 != EXPECTED_DEPENDENCY_MANIFEST_SHA256:
        raise NativeAdapterError("dependency_manifest_hash_mismatch")
    try:
        manifest = json.loads(
            manifest_bytes.decode("utf-8"), object_pairs_hook=_strict_dependency_object
        )
    except NativeAdapterError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise NativeAdapterError("dependency_manifest_invalid") from None
    expected_top = {
        "distributions",
        "import_policy",
        "native_dependency_imports",
        "schema",
    }
    if (
        type(manifest) is not dict
        or set(manifest) != expected_top
        or manifest.get("schema") != DEPENDENCY_MANIFEST_SCHEMA
        or manifest.get("import_policy") != "COMPILE_VERIFIED_SOURCE_ONLY"
        or manifest.get("native_dependency_imports") != "DENIED"
        or type(manifest.get("distributions")) is not list
    ):
        raise NativeAdapterError("dependency_manifest_invalid")

    expected_distributions = set(_DEPENDENCY_PACKAGE_ROOTS)
    seen_distributions = set()
    expected_spec_keys = {
        "dist_info",
        "distribution",
        "excluded_console_record_paths",
        "package_roots",
        "python_files",
        "record_sha256",
    }
    for spec in manifest["distributions"]:
        if type(spec) is not dict or set(spec) != expected_spec_keys:
            raise NativeAdapterError("dependency_manifest_invalid")
        distribution = spec.get("distribution")
        if type(distribution) is not str or distribution not in expected_distributions:
            raise NativeAdapterError("dependency_manifest_invalid")
        if distribution in seen_distributions:
            raise NativeAdapterError("dependency_manifest_invalid")
        seen_distributions.add(distribution)
        roots = spec.get("package_roots")
        if type(roots) is not list or tuple(roots) != _DEPENDENCY_PACKAGE_ROOTS[distribution]:
            raise NativeAdapterError("dependency_manifest_invalid")
        expected_excluded = _DEPENDENCY_EXCLUDED_RECORD_PATHS[distribution]
        excluded = spec.get("excluded_console_record_paths")
        if type(excluded) is not list or tuple(excluded) != expected_excluded:
            raise NativeAdapterError("dependency_manifest_invalid")
        dist_info = spec.get("dist_info")
        if (
            type(dist_info) is not str
            or re.fullmatch(r"[A-Za-z0-9_.+-]+\.dist-info", dist_info) is None
        ):
            raise NativeAdapterError("dependency_manifest_invalid")
        record_sha = spec.get("record_sha256")
        if type(record_sha) is not str or _SHA256_RE.fullmatch(record_sha) is None:
            raise NativeAdapterError("dependency_manifest_invalid")
        python_files = spec.get("python_files")
        if (
            type(python_files) is not dict
            or set(python_files) != set(roots)
            or any(type(count) is not int or count <= 0 for count in python_files.values())
        ):
            raise NativeAdapterError("dependency_manifest_invalid")
    if seen_distributions != expected_distributions:
        raise NativeAdapterError("dependency_manifest_invalid")
    return manifest, manifest_sha256


def _native_text_exact(value: Any) -> str:
    """Decode a native char field exactly, without trimming edge spaces."""

    if isinstance(value, bytes):
        try:
            value = value.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            raise NativeAdapterError("native_request_field_unavailable") from None
    if (
        type(value) is not str
        or len(value) > MAX_POSITION_TEXT_CHARS
        or any(unicodedata.category(char) == "Cc" for char in value)
    ):
        raise NativeAdapterError("native_request_field_unavailable")
    return value


def _validate_native_request_fields(
    method: str, native_field: Any, credentials: Optional[Mapping[str, str]]
) -> None:
    """Bind every allowed request struct to the private configured account."""

    if native_field is None or credentials is None:
        raise NativeAdapterError("native_request_field_unavailable")
    if method == "ReqAuthenticate":
        expected_fields = {
            "BrokerID": credentials["broker_id"],
            "UserID": credentials["user_id"],
            "AppID": credentials["app_id"],
            "AuthCode": credentials["auth_code"],
        }
    elif method == "ReqUserLogin":
        expected_fields = {
            "BrokerID": credentials["broker_id"],
            "UserID": credentials["user_id"],
            "Password": credentials["password"],
        }
    elif method in {"ReqQryOrder", "ReqQryInvestorPosition", "ReqQryTradingAccount"}:
        expected_fields = {
            "BrokerID": credentials["broker_id"],
            "InvestorID": credentials["user_id"],
        }
    else:
        raise NativeAdapterError("native_request_allowlist_violation")

    for name, expected in expected_fields.items():
        try:
            value = (
                native_field[name]
                if isinstance(native_field, Mapping)
                else getattr(native_field, name)
            )
        except Exception:
            raise NativeAdapterError("native_request_field_unavailable") from None
        try:
            actual = _native_text_exact(value)
        except NativeAdapterError:
            raise NativeAdapterError("native_request_field_unavailable") from None
        reason = (
            "native_query_scope_mismatch"
            if method.startswith("ReqQry")
            else "native_credential_field_mismatch"
        )
        if actual != expected:
            raise NativeAdapterError(reason)

    if method in {"ReqAuthenticate", "ReqUserLogin"}:
        try:
            if isinstance(native_field, dict):
                native_field["UserProductInfo"] = credentials["product_info"]
            else:
                native_field.UserProductInfo = credentials["product_info"]
        except Exception:
            raise NativeAdapterError("native_credential_field_unavailable") from None


def _decode_private_input(protocol: Any, launch: Any) -> Dict[str, Any]:
    packet = launch.credential_packet
    if type(packet) is not bytes or not packet or len(packet) > MAX_PRIVATE_PACKET_BYTES:
        raise NativeAdapterError("private_input_packet_invalid")
    private_input = protocol.parse_private_input_packet(packet)
    field_names = (
        "broker_id",
        "user_id",
        "password",
        "app_id",
        "auth_code",
        "product_info",
        "native_flow_directory",
        "evidence_directory",
    )
    try:
        values = {name: getattr(private_input, name) for name in field_names}
    except Exception:
        raise NativeAdapterError("private_input_shape_invalid") from None
    if set(values) != set(field_names):
        raise NativeAdapterError("private_input_shape_invalid")
    for name, max_bytes in _CREDENTIAL_LIMITS.items():
        value = values.get(name)
        if type(value) is not str or not value or not value.isascii():
            raise NativeAdapterError("private_input_credential_invalid")
        if len(value.encode("utf-8")) > max_bytes or any(
            unicodedata.category(char) == "Cc" for char in value
        ):
            raise NativeAdapterError("private_input_credential_invalid")
    for name in ("native_flow_directory", "evidence_directory"):
        value = values.get(name)
        if type(value) is not str or not value or len(value) > 32767:
            raise NativeAdapterError("private_input_path_invalid")
        if any(unicodedata.category(char) == "Cc" for char in value):
            raise NativeAdapterError("private_input_path_invalid")
    account_digest = protocol.compute_account_scope_sha256(values["broker_id"], values["user_id"])
    credential_digest = protocol.compute_credential_binding_sha256(
        values["broker_id"],
        values["user_id"],
        values["password"],
        values["app_id"],
        values["auth_code"],
        values["product_info"],
    )
    if account_digest != launch.account_scope_sha256:
        raise NativeAdapterError("account_scope_digest_mismatch")
    if credential_digest != launch.credential_binding_sha256:
        raise NativeAdapterError("credential_binding_digest_mismatch")
    return values


def _validate_td_front(launch: Any, protocol: Any) -> str:
    pair = launch.pair_binding
    value = getattr(pair, "td_front", None)
    if type(value) is not str or len(value) > 64 or not value.isascii():
        raise NativeAdapterError("td_front_invalid")
    match = _FRONT_RE.fullmatch(value)
    if match is None or hashlib.sha256(value.encode("utf-8")).hexdigest() != pair.td_front_sha256:
        raise NativeAdapterError("td_front_binding_mismatch")
    address, port = value[6:].rsplit(":", 1)
    octets = address.split(".")
    if any(
        not octet.isdigit() or int(octet) > 255 or (len(octet) > 1 and octet[0] == "0")
        for octet in octets
    ):
        raise NativeAdapterError("td_front_invalid")
    if not 1 <= int(port) <= 65535 or str(int(port)) != port:
        raise NativeAdapterError("td_front_invalid")
    return value


def _load_protocol_from_worker_path() -> Any:
    path = Path(__file__).resolve(strict=True).with_name("certification_simnow_c01_v3_protocol.py")
    if not path.is_file() or path.is_symlink():
        raise NativeAdapterError("protocol_source_unavailable")
    try:
        source = path.read_bytes()
    except OSError:
        raise NativeAdapterError("protocol_source_unavailable") from None
    if hashlib.sha256(source).hexdigest() != EXPECTED_PROTOCOL_SOURCE_SHA256:
        raise NativeAdapterError("protocol_source_hash_mismatch")

    # Compile the verified bytes directly. Importlib's file loader may accept
    # a timestamp-valid adjacent pyc, so it is not used for this trust root.
    name = "_simnow_c01_native_protocol"
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    # Dataclasses resolve their defining module through sys.modules while
    # decorators run.  Register only this fixed, repository-owned protocol
    # source before execution; no SDK package is imported here.
    sys.modules[name] = module
    try:
        code = compile(source, str(path), "exec", dont_inherit=True)
        exec(code, module.__dict__)
    except Exception:
        sys.modules.pop(name, None)
        raise NativeAdapterError("protocol_source_unavailable") from None
    return module


def _load_interpreter_binding_from_worker_path() -> Any:
    path = (
        Path(__file__)
        .resolve(strict=True)
        .with_name("certification_simnow_c01_interpreter_binding_v1.py")
    )
    if not path.is_file() or path.is_symlink():
        raise NativeAdapterError("interpreter_binding_source_unavailable")
    try:
        source = path.read_bytes()
    except OSError:
        raise NativeAdapterError("interpreter_binding_source_unavailable") from None
    if hashlib.sha256(source).hexdigest() != EXPECTED_INTERPRETER_BINDING_SOURCE_SHA256:
        raise NativeAdapterError("interpreter_binding_source_hash_mismatch")
    name = "_simnow_c01_interpreter_binding"
    if name in sys.modules:
        raise NativeAdapterError("interpreter_binding_already_loaded")
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__c01_interpreter_binding_sha256__ = EXPECTED_INTERPRETER_BINDING_SOURCE_SHA256
    sys.modules[name] = module
    try:
        code = compile(source, str(path), "exec", dont_inherit=True)
        exec(code, module.__dict__)
    except Exception:
        sys.modules.pop(name, None)
        raise NativeAdapterError("interpreter_binding_source_unavailable") from None
    return module


def _relative_record_path(site_packages: Path, raw: str) -> Path:
    rel = PurePosixPath(raw)
    if rel.is_absolute() or not rel.parts or any(part in {"", ".", ".."} for part in rel.parts):
        raise NativeAdapterError("sdk_record_path_invalid")
    target = site_packages.joinpath(*rel.parts)
    try:
        target.resolve(strict=True).relative_to(site_packages)
    except (OSError, ValueError):
        raise NativeAdapterError("sdk_record_path_invalid") from None
    return target


def _canonical_unhashed_pyc_source(package_root: Path, pyc_path: Path) -> Optional[Path]:
    """Map only CPython 3.11's canonical source-cache path back to its source."""

    try:
        relative = pyc_path.relative_to(package_root)
    except ValueError:
        return None
    if len(relative.parts) < 2 or relative.parts[-2] != "__pycache__":
        return None
    suffix = ".cpython-311.pyc"
    if not relative.name.endswith(suffix):
        return None
    source_stem = relative.name[: -len(suffix)]
    if not source_stem:
        return None
    return package_root.joinpath(*relative.parts[:-2], source_stem + ".py")


def _verify_distribution(site_packages: Path, name: str) -> Dict[Path, str]:
    spec = SDK_DISTRIBUTIONS[name]
    record = site_packages / spec["dist_info"] / "RECORD"
    try:
        record_bytes = record.read_bytes()
    except OSError:
        raise NativeAdapterError("sdk_record_missing") from None
    if hashlib.sha256(record_bytes).hexdigest() != spec["record_sha256"]:
        raise NativeAdapterError("sdk_record_hash_mismatch")
    try:
        text = record_bytes.decode("utf-8")
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (UnicodeDecodeError, csv.Error):
        raise NativeAdapterError("sdk_record_invalid") from None
    package_root = site_packages / spec["package"]
    seen = set()
    row_by_path = {}
    for row in rows:
        if len(row) != 3 or not row[0] or row[0] in seen:
            raise NativeAdapterError("sdk_record_invalid")
        seen.add(row[0])
        row_by_path[row[0]] = row

    verified: Dict[Path, str] = {}
    for row in rows:
        path = _relative_record_path(site_packages, row[0])
        if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
            raise NativeAdapterError("sdk_record_path_invalid")
        if path == record:
            if row[1] or row[2]:
                raise NativeAdapterError("sdk_record_invalid")
            continue
        if not row[1]:
            pyc_source = _canonical_unhashed_pyc_source(package_root, path)
            if row[2] or pyc_source is None or not path.is_file():
                raise NativeAdapterError("sdk_record_hash_missing")
            try:
                source_record_path = pyc_source.relative_to(site_packages).as_posix()
            except ValueError:
                raise NativeAdapterError("sdk_record_path_invalid") from None
            source_row = row_by_path.get(source_record_path)
            if source_row is None or not source_row[1]:
                raise NativeAdapterError("sdk_record_hash_missing")
            continue
        try:
            data = path.read_bytes()
        except OSError:
            raise NativeAdapterError("sdk_record_file_missing") from None
        if row[2] and (not row[2].isdigit() or int(row[2]) != len(data)):
            raise NativeAdapterError("sdk_record_size_mismatch")
        if row[1]:
            algorithm, separator, encoded = row[1].partition("=")
            if algorithm != "sha256" or not separator:
                raise NativeAdapterError("sdk_record_hash_algorithm_invalid")
            actual = (
                base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode("ascii").rstrip("=")
            )
            if actual != encoded:
                raise NativeAdapterError("sdk_record_file_hash_mismatch")
            verified[path] = hashlib.sha256(data).hexdigest()
    try:
        source_files = [p for p in package_root.rglob("*.py") if p.is_file()]
    except OSError:
        raise NativeAdapterError("sdk_source_tree_unavailable") from None
    if len(source_files) != spec["python_files"]:
        raise NativeAdapterError("sdk_source_file_count_mismatch")
    for path in source_files:
        if path.is_symlink() or path not in verified:
            raise NativeAdapterError("sdk_source_not_recorded")
    return verified


def _dependency_record_target(site_packages: Path, raw: str) -> Path:
    if type(raw) is not str or not raw or "\\" in raw or any(ord(char) < 32 for char in raw):
        raise NativeAdapterError("dependency_record_path_invalid")
    relative = PurePosixPath(raw)
    if (
        relative.is_absolute()
        or not relative.parts
        or relative.as_posix() != raw
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise NativeAdapterError("dependency_record_path_invalid")
    path = site_packages.joinpath(*relative.parts)
    return _ensure_no_reparse_path(
        path,
        boundary=site_packages,
        error_code="dependency_record_path_invalid",
    )


def _verify_dependency_payload(path: Path, row: list) -> str:
    row_hash, row_size = row[1], row[2]
    if type(row_hash) is not str or not row_hash:
        raise NativeAdapterError("dependency_record_hash_missing")
    if type(row_size) is not str or len(row_size) > 12 or re.fullmatch(r"[0-9]+", row_size) is None:
        raise NativeAdapterError("dependency_record_size_mismatch")
    size = int(row_size)
    if size > MAX_DEPENDENCY_PAYLOAD_BYTES:
        raise NativeAdapterError("dependency_record_size_mismatch")
    try:
        if path.stat().st_size != size:
            raise NativeAdapterError("dependency_record_size_mismatch")
        data = path.read_bytes()
    except OSError:
        raise NativeAdapterError("dependency_record_file_missing") from None
    if size != len(data):
        raise NativeAdapterError("dependency_record_size_mismatch")
    algorithm, separator, encoded = row_hash.partition("=")
    if algorithm != "sha256" or not separator or not encoded:
        raise NativeAdapterError("dependency_record_hash_algorithm_invalid")
    actual = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode("ascii").rstrip("=")
    if actual != encoded:
        raise NativeAdapterError("dependency_record_file_hash_mismatch")
    return hashlib.sha256(data).hexdigest()


def _dependency_root_for_record_path(raw: str, roots: Tuple[str, ...]) -> Optional[str]:
    for root in roots:
        if raw.startswith(root + "/"):
            return root
    return None


def _verify_dependency_distribution(
    site_packages: Path, spec: Mapping[str, Any]
) -> Tuple[Dict[Path, str], Dict[Path, str]]:
    """Verify one fixed pure-Python dependency without exposing its dist-info."""

    roots = tuple(spec["package_roots"])
    dist_info = spec["dist_info"]
    excluded = set(spec["excluded_console_record_paths"])
    site_packages = _ensure_no_reparse_path(
        site_packages,
        boundary=Path(site_packages.anchor),
        error_code="dependency_record_path_invalid",
    )
    try:
        record_path = _dependency_record_target(site_packages, dist_info + "/RECORD")
        if not record_path.is_file():
            raise NativeAdapterError("dependency_record_missing")
        if record_path.stat().st_size > MAX_DEPENDENCY_RECORD_BYTES:
            raise NativeAdapterError("dependency_record_invalid")
        record_bytes = record_path.read_bytes()
    except NativeAdapterError:
        raise
    except OSError:
        raise NativeAdapterError("dependency_record_missing") from None
    if hashlib.sha256(record_bytes).hexdigest() != spec["record_sha256"]:
        raise NativeAdapterError("dependency_record_hash_mismatch")
    try:
        rows = list(csv.reader(io.StringIO(record_bytes.decode("utf-8"), newline=""), strict=True))
    except (UnicodeDecodeError, csv.Error):
        raise NativeAdapterError("dependency_record_invalid") from None
    row_by_path: Dict[str, list] = {}
    for row in rows:
        if len(row) != 3 or not row[0] or row[0] in row_by_path:
            raise NativeAdapterError("dependency_record_invalid")
        row_by_path[row[0]] = row
    if row_by_path.get(dist_info + "/RECORD") != [dist_info + "/RECORD", "", ""]:
        raise NativeAdapterError("dependency_record_invalid")

    package_rows: Dict[str, list] = {}
    excluded_seen = set()
    for raw, row in row_by_path.items():
        if raw == dist_info + "/RECORD":
            continue
        if raw in excluded:
            excluded_seen.add(raw)
            continue
        root_name = _dependency_root_for_record_path(raw, roots)
        if root_name is not None:
            if PurePosixPath(raw).suffix.lower() in _FORBIDDEN_DEPENDENCY_SUFFIXES:
                raise NativeAdapterError("dependency_native_payload_rejected")
            path = _dependency_record_target(site_packages, raw)
            if not path.is_file():
                raise NativeAdapterError("dependency_record_file_missing")
            if "__pycache__" in PurePosixPath(raw).parts:
                package_root = site_packages / root_name
                pyc_source = _canonical_unhashed_pyc_source(package_root, path)
                source_row = (
                    row_by_path.get(pyc_source.relative_to(site_packages).as_posix())
                    if pyc_source is not None
                    else None
                )
                if pyc_source is None or row[1] or row[2] or not source_row or not source_row[1]:
                    raise NativeAdapterError("dependency_record_hash_missing")
                continue
            if not stat.S_ISREG(path.lstat().st_mode):
                raise NativeAdapterError("dependency_record_path_invalid")
            _verify_dependency_payload(path, row)
            package_rows[raw] = row
            continue
        if raw.startswith(dist_info + "/"):
            path = _dependency_record_target(site_packages, raw)
            if not path.is_file() or not stat.S_ISREG(path.lstat().st_mode):
                raise NativeAdapterError("dependency_record_path_invalid")
            _verify_dependency_payload(path, row)
            continue
        raise NativeAdapterError("dependency_record_unapproved_path")
    if excluded_seen != excluded:
        raise NativeAdapterError("dependency_record_exclusion_mismatch")

    verified: Dict[Path, str] = {}
    optional_native: Dict[Path, str] = {}
    rows_by_root: Dict[str, set] = {root: set() for root in roots}
    for raw, row in package_rows.items():
        root_name = _dependency_root_for_record_path(raw, roots)
        if root_name is None:
            raise NativeAdapterError("dependency_record_unapproved_path")
        path = _dependency_record_target(site_packages, raw)
        digest = _verify_dependency_payload(path, row)
        if path.suffix.lower() in _OPTIONAL_NATIVE_DEPENDENCY_SUFFIXES:
            optional_native[path] = digest
        else:
            verified[path] = digest
        rows_by_root[root_name].add(raw)

    counts = spec["python_files"]
    for root_name in roots:
        package_root = site_packages / root_name
        _ensure_no_reparse_path(
            package_root,
            boundary=site_packages,
            error_code="dependency_record_path_invalid",
        )
        if not package_root.is_dir():
            raise NativeAdapterError("dependency_source_tree_unavailable")
        observed_payload = set()
        source_count = 0
        try:
            descendants = package_root.rglob("*")
        except OSError:
            raise NativeAdapterError("dependency_source_tree_unavailable") from None
        entry_count = 0
        for path in descendants:
            entry_count += 1
            if entry_count > MAX_DEPENDENCY_TREE_ENTRIES:
                raise NativeAdapterError("dependency_source_tree_unavailable")
            _ensure_no_reparse_path(
                path,
                boundary=site_packages,
                error_code="dependency_record_path_invalid",
            )
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode):
                raise NativeAdapterError("dependency_record_path_invalid")
            relative_parts = path.relative_to(package_root).parts
            if "__pycache__" in relative_parts:
                pyc_source = _canonical_unhashed_pyc_source(package_root, path)
                cache_raw = path.relative_to(site_packages).as_posix()
                source_raw = (
                    pyc_source.relative_to(site_packages).as_posix()
                    if pyc_source is not None
                    else None
                )
                cache_row = row_by_path.get(cache_raw)
                source_row = row_by_path.get(source_raw) if source_raw is not None else None
                if (
                    pyc_source is None
                    or cache_row is None
                    or cache_row[1]
                    or cache_row[2]
                    or not source_row
                    or not source_row[1]
                ):
                    raise NativeAdapterError("dependency_record_hash_missing")
                continue
            if path.suffix.lower() in _FORBIDDEN_DEPENDENCY_SUFFIXES:
                raise NativeAdapterError("dependency_native_payload_rejected")
            relative = path.relative_to(site_packages).as_posix()
            observed_payload.add(relative)
            if path.suffix == ".py":
                source_count += 1
        if observed_payload != rows_by_root[root_name]:
            raise NativeAdapterError("dependency_source_not_recorded")
        if source_count != counts[root_name]:
            raise NativeAdapterError("dependency_source_file_count_mismatch")
        for raw in rows_by_root[root_name]:
            path = site_packages.joinpath(*PurePosixPath(raw).parts)
            if raw.endswith(".py") and path not in verified:
                raise NativeAdapterError("dependency_source_not_recorded")
            if (
                path.suffix.lower() in _OPTIONAL_NATIVE_DEPENDENCY_SUFFIXES
                and path not in optional_native
            ):
                raise NativeAdapterError("dependency_native_payload_rejected")
    return verified, optional_native


def _verify_sdk_install(binding: Any = None) -> Tuple[Path, Dict[Path, str]]:
    _verify_pinned_cpython_abi()
    binding = binding or _load_interpreter_binding_from_worker_path()
    if getattr(binding, "BINDING_ID", None) != "simnow.c01.interpreter-binding.v1":
        raise NativeAdapterError("interpreter_binding_type_invalid")
    if binding.verify_current_runtime() is not True:
        raise NativeAdapterError("interpreter_binding_runtime_mismatch")
    try:
        site_candidate = Path(binding.SDK_SITE_PACKAGES)
        if not site_candidate.is_absolute():
            raise NativeAdapterError("sdk_site_packages_missing")
        site_packages = _ensure_no_reparse_path(
            site_candidate,
            boundary=Path(site_candidate.anchor),
            error_code="sdk_site_packages_missing",
        )
        if not site_packages.is_dir():
            raise NativeAdapterError("sdk_site_packages_missing")
    except OSError:
        raise NativeAdapterError("sdk_site_packages_missing") from None
    verified = _VerifiedSdkPayloads()
    for name in SDK_DISTRIBUTIONS:
        verified.update(_verify_distribution(site_packages, name))
    dependency_manifest, manifest_sha256 = _load_dependency_manifest()
    verified.dependency_manifest_sha256 = manifest_sha256
    for spec in dependency_manifest["distributions"]:
        dependency_sources, optional_native = _verify_dependency_distribution(site_packages, spec)
        verified.update(dependency_sources)
        verified.optional_native_payloads.update(optional_native)
    for relative, (expected_hash, expected_size) in PINNED_NATIVE_FILES.items():
        path = site_packages.joinpath(*PurePosixPath(relative).parts)
        try:
            data = path.read_bytes()
        except OSError:
            raise NativeAdapterError("pinned_ctp_native_missing") from None
        if len(data) != expected_size or hashlib.sha256(data).hexdigest() != expected_hash:
            raise NativeAdapterError("pinned_ctp_native_hash_mismatch")
        if path.suffix in {".pyd", ".dll"} and path not in verified:
            raise NativeAdapterError("pinned_ctp_native_not_recorded")
    return site_packages, verified


def _check_pinned_cpython_abi(
    *,
    os_name: str,
    platform_name: str,
    implementation_name: str,
    version: Tuple[int, int, int],
    primary_extension_suffix: Optional[str],
    pointer_bits: int,
) -> None:
    if (
        os_name != "nt"
        or platform_name != "win32"
        or implementation_name != "cpython"
        or version != (3, 11, 5)
        or primary_extension_suffix != ".cp311-win_amd64.pyd"
        or pointer_bits != 64
    ):
        raise NativeAdapterError("pinned_cpython_runtime_required")


def _verify_pinned_cpython_abi() -> None:
    suffixes = importlib.machinery.EXTENSION_SUFFIXES
    primary_suffix = suffixes[0] if suffixes else None
    _check_pinned_cpython_abi(
        os_name=os.name,
        platform_name=sys.platform,
        implementation_name=sys.implementation.name,
        version=tuple(sys.version_info[:3]),
        primary_extension_suffix=primary_suffix,
        pointer_bits=struct.calcsize("P") * 8,
    )


class _VerifiedCertifiTraversable:
    """Expose only the verified certifi CA bundle through resources.files()."""

    def __init__(self, reader: "_VerifiedCertifiResourceReader", resource: bool = False):
        self._reader = reader
        self._resource = resource

    @property
    def name(self) -> str:
        return CERTIFI_RESOURCE_NAME if self._resource else CERTIFI_RESOURCE_PACKAGE

    def iterdir(self) -> Iterable["_VerifiedCertifiTraversable"]:
        if self._resource:
            raise NotADirectoryError("verified certifi resource is not a directory")
        yield _VerifiedCertifiTraversable(self._reader, resource=True)

    def is_dir(self) -> bool:
        return not self._resource

    def is_file(self) -> bool:
        return self._resource

    def read_bytes(self) -> bytes:
        with self.open("rb") as stream:
            return stream.read()

    def read_text(self, encoding: Optional[str] = None) -> str:
        with self.open("r", encoding=encoding or "utf-8") as stream:
            return stream.read()

    def joinpath(self, *descendants: Any) -> "_VerifiedCertifiTraversable":
        if self._resource:
            raise FileNotFoundError("verified certifi resource path is unavailable")
        if (
            len(descendants) == 1
            and type(descendants[0]) is str
            and descendants[0] == CERTIFI_RESOURCE_NAME
        ):
            return _VerifiedCertifiTraversable(self._reader, resource=True)
        raise FileNotFoundError("unapproved certifi resource path")

    def open(self, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if not self._resource:
            raise IsADirectoryError("verified certifi package root is not a file")
        if args or set(kwargs) - {"encoding", "errors", "newline"}:
            raise ValueError("unsupported certifi resource open options")
        data = self._reader.read_verified_resource()
        if mode == "rb":
            if kwargs:
                raise ValueError("binary certifi resource open takes no text options")
            return io.BytesIO(data)
        if mode != "r":
            raise ValueError("verified certifi resource is read-only")
        return io.TextIOWrapper(
            io.BytesIO(data),
            encoding=kwargs.get("encoding") or "utf-8",
            errors=kwargs.get("errors") or "strict",
            newline=kwargs.get("newline"),
        )


class _VerifiedCertifiResourceReader(importlib.abc.TraversableResources):
    """Provide one hash-checked resource and no installed filesystem fallback."""

    def __init__(self, boundary: Path, resource_path: Path, expected_sha256: str):
        self.boundary = boundary
        self.resource_path_value = resource_path
        self.expected_sha256 = expected_sha256

    def files(self) -> _VerifiedCertifiTraversable:
        return _VerifiedCertifiTraversable(self)

    def read_verified_resource(self) -> bytes:
        expected_path = self.boundary / CERTIFI_RESOURCE_RELATIVE_PATH
        if self.resource_path_value != expected_path:
            raise FileNotFoundError("verified certifi resource unavailable")
        try:
            safe_path = _ensure_no_reparse_path(
                self.resource_path_value,
                boundary=self.boundary,
                error_code="certifi_resource_path_invalid",
            )
            info = safe_path.stat()
            if not stat.S_ISREG(info.st_mode):
                raise FileNotFoundError("verified certifi resource unavailable")
            if info.st_size < 0 or info.st_size > MAX_CERTIFI_CA_RESOURCE_BYTES:
                raise FileNotFoundError("verified certifi resource unavailable")
            with safe_path.open("rb") as resource_stream:
                data = resource_stream.read(MAX_CERTIFI_CA_RESOURCE_BYTES + 1)
            if len(data) != info.st_size or len(data) > MAX_CERTIFI_CA_RESOURCE_BYTES:
                raise FileNotFoundError("verified certifi resource unavailable")
            safe_after_read = _ensure_no_reparse_path(
                self.resource_path_value,
                boundary=self.boundary,
                error_code="certifi_resource_path_invalid",
            )
        except NativeAdapterError:
            raise FileNotFoundError("verified certifi resource unavailable") from None
        except OSError:
            raise FileNotFoundError("verified certifi resource unavailable") from None
        if safe_after_read != safe_path:
            raise FileNotFoundError("verified certifi resource unavailable")
        if hashlib.sha256(data).hexdigest() != self.expected_sha256:
            raise FileNotFoundError("verified certifi resource unavailable")
        return data


class _VerifiedSdkSourceLoader(importlib.abc.Loader):
    """Execute verified source bytes directly; never consume installed pyc."""

    def __init__(
        self,
        fullname: str,
        path: Path,
        expected_sha256: str,
        is_package: bool,
        boundary: Optional[Path] = None,
        verified_resources: Optional[Mapping[str, Tuple[Path, str]]] = None,
    ):
        self.fullname = fullname
        self.path = path
        self.expected_sha256 = expected_sha256
        self.is_package = is_package
        self.boundary = boundary
        self.verified_resources = dict(verified_resources or {})

    def create_module(self, spec: Any) -> None:
        return None

    def get_resource_reader(self, fullname: str) -> Optional[Any]:
        if fullname != self.fullname or not self.is_package:
            return None
        if fullname != CERTIFI_RESOURCE_PACKAGE:
            return None
        if set(self.verified_resources) != {CERTIFI_RESOURCE_NAME} or self.boundary is None:
            raise FileNotFoundError("verified certifi resource unavailable")
        resource_path, expected_sha256 = self.verified_resources[CERTIFI_RESOURCE_NAME]
        if (
            type(expected_sha256) is not str
            or _SHA256_RE.fullmatch(expected_sha256) is None
            or resource_path != self.boundary / CERTIFI_RESOURCE_RELATIVE_PATH
        ):
            raise FileNotFoundError("verified certifi resource unavailable")
        return _VerifiedCertifiResourceReader(self.boundary, resource_path, expected_sha256)

    def exec_module(self, module: Any) -> None:
        try:
            source_path = (
                _ensure_no_reparse_path(
                    self.path,
                    boundary=self.boundary,
                    error_code="verified_source_path_changed",
                )
                if self.boundary is not None
                else self.path
            )
            source = source_path.read_bytes()
        except OSError:
            raise ImportError("pinned SDK source unavailable") from None
        except NativeAdapterError:
            raise ImportError("pinned source path changed after verification") from None
        if hashlib.sha256(source).hexdigest() != self.expected_sha256:
            raise ImportError("pinned SDK source changed after verification") from None
        code = compile(source, str(source_path), "exec", dont_inherit=True)
        exec(code, module.__dict__)


class _VerifiedSdkExtensionLoader(importlib.abc.Loader):
    """Load only the one hash-pinned CTP extension after rechecking its bytes."""

    def __init__(self, fullname: str, path: Path, expected_sha256: str):
        self.path = path
        self.expected_sha256 = expected_sha256
        self.delegate = importlib.machinery.ExtensionFileLoader(fullname, str(path))

    def _verify_bytes(self) -> None:
        try:
            data = self.path.read_bytes()
        except OSError:
            raise ImportError("pinned CTP extension unavailable") from None
        if hashlib.sha256(data).hexdigest() != self.expected_sha256:
            raise ImportError("pinned CTP extension changed after verification") from None

    def create_module(self, spec: Any) -> Any:
        self._verify_bytes()
        return self.delegate.create_module(spec)

    def exec_module(self, module: Any) -> None:
        self._verify_bytes()
        self.delegate.exec_module(module)


class _VerifiedSdkFinder(importlib.abc.MetaPathFinder):
    def __init__(self, site_packages: Path, verified: Mapping[Path, str]):
        self.sdk_roots = {
            name: site_packages / SDK_DISTRIBUTIONS[name]["package"] for name in SDK_DISTRIBUTIONS
        }
        self.dependency_manifest, self.dependency_manifest_sha256 = _load_dependency_manifest()
        self.dependency_roots: Dict[str, Path] = {}
        for spec in self.dependency_manifest["distributions"]:
            for root_name in spec["package_roots"]:
                if root_name in self.sdk_roots or root_name in self.dependency_roots:
                    raise NativeAdapterError("dependency_manifest_invalid")
                self.dependency_roots[root_name] = site_packages / root_name
        self.roots = {**self.sdk_roots, **self.dependency_roots}
        self.verified = verified
        self.site_packages = site_packages

    def _route_name(self, fullname: str) -> str:
        for alias, target in _DEPENDENCY_IMPORT_ALIASES.items():
            if fullname == alias or fullname.startswith(alias + "."):
                return target + fullname[len(alias) :]
        return fullname

    def _interpreter_stdlib_path(self, target: str) -> Path:
        relative = _SIX_STDLIB_TARGET_PATHS.get(target) or _SIX_STDLIB_PACKAGE_PATHS.get(target)
        if relative is None:
            raise ImportError("unapproved six stdlib target")
        try:
            boundary = Path(sysconfig.get_path("stdlib")).resolve(strict=True)
            path = boundary.joinpath(*PurePosixPath(relative).parts)
            resolved = _ensure_no_reparse_path(
                path, boundary=boundary, error_code="six_stdlib_path_invalid"
            )
        except (NativeAdapterError, OSError, ValueError):
            raise ImportError("interpreter stdlib target unavailable") from None
        try:
            resolved.relative_to(self.site_packages.resolve(strict=True))
        except ValueError:
            pass
        else:
            raise ImportError("interpreter stdlib target overlaps dependency install")
        return resolved

    def _verify_interpreter_stdlib_source(self, target: str, expected_path: Path) -> None:
        """Verify the fixed stdlib source used by a six MovedModule."""
        for raw in sys.path:
            if not raw:
                raise ImportError("interpreter stdlib path is unsafe")
            try:
                candidate = Path(raw).resolve(strict=False)
                candidate.relative_to(self.site_packages.resolve(strict=True))
            except ValueError:
                continue
            except OSError:
                raise ImportError("interpreter stdlib path is unsafe") from None
            raise ImportError("interpreter stdlib path includes dependency install")

        stdlib_root = Path(sysconfig.get_path("stdlib")).resolve(strict=True)
        if "." in target:
            parent_name = target.rpartition(".")[0]
            parent_path = self._interpreter_stdlib_path(parent_name)
            parent_spec = importlib.machinery.PathFinder.find_spec(parent_name, [str(stdlib_root)])
            if (
                parent_spec is None
                or parent_spec.origin is None
                or Path(parent_spec.origin).resolve(strict=True) != parent_path
                or type(parent_spec.loader) is not importlib.machinery.SourceFileLoader
            ):
                raise ImportError("interpreter stdlib parent origin changed")
            spec = importlib.machinery.PathFinder.find_spec(target, [str(parent_path.parent)])
        else:
            spec = importlib.machinery.PathFinder.find_spec(target, [str(stdlib_root)])
        if (
            spec is None
            or spec.origin is None
            or Path(spec.origin).resolve(strict=True) != expected_path
            or type(spec.loader) is not importlib.machinery.SourceFileLoader
        ):
            raise ImportError("interpreter stdlib module origin changed")

    def _six_importer_context(
        self, fullname: str
    ) -> Tuple[Any, Any, Any, Tuple[str, str, str, str]]:
        route = _SIX_VIRTUAL_ROUTES.get(fullname)
        if route is None:
            raise ImportError("unapproved six virtual route")
        producer, known_name, virtual_kind, virtual_target = route
        if fullname != known_name:
            expected_alias = known_name.replace(
                "urllib3.packages.six",
                "requests.packages.urllib3.packages.six",
                1,
            )
            if (
                fullname != expected_alias
                or sys.modules.get(fullname) is None
                or sys.modules.get(fullname) is not sys.modules.get(known_name)
            ):
                raise ImportError("requests six alias identity changed")
        source_path = self.site_packages.joinpath(*PurePosixPath(SIX_SOURCE_RELATIVE_PATH).parts)
        try:
            source_path = _ensure_no_reparse_path(
                source_path,
                boundary=self.site_packages,
                error_code="six_source_path_invalid",
            )
            expected = self.verified.get(source_path)
            source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
        except (NativeAdapterError, OSError):
            raise ImportError("pinned six source unavailable") from None
        if expected != SIX_SOURCE_SHA256 or source_sha != SIX_SOURCE_SHA256:
            raise ImportError("pinned six source changed")
        module = sys.modules.get(producer)
        if module is None:
            raise ModuleNotFoundError("verified six producer missing", name=producer)
        try:
            module_path = Path(module.__file__).resolve(strict=True)
            module_spec = module.__spec__
            loader = module_spec.loader
            module_origin = Path(module_spec.origin).resolve(strict=True)
            loader_boundary = (
                Path(loader.boundary).resolve(strict=True)
                if type(loader) is _VerifiedSdkSourceLoader and loader.boundary is not None
                else None
            )
            site_boundary = self.site_packages.resolve(strict=True)
        except (AttributeError, OSError, TypeError, ValueError):
            raise ImportError("verified six producer origin unavailable") from None
        if (
            module_path != source_path
            or module_spec.name != producer
            or module_origin != source_path
            or type(loader) is not _VerifiedSdkSourceLoader
            or module.__loader__ is not loader
            or loader.path != source_path
            or loader.expected_sha256 != SIX_SOURCE_SHA256
            or loader_boundary != site_boundary
        ):
            raise ImportError("verified six producer origin changed")
        importer_type = module.__dict__.get("_SixMetaPathImporter")
        importer = module.__dict__.get("_importer")
        if (
            not isinstance(importer_type, type)
            or importer_type.__module__ != producer
            or importer_type.__name__ != "_SixMetaPathImporter"
            or type(importer) is not importer_type
            or importer.name != producer
            or type(importer.known_modules) is not dict
            or sum(candidate is importer for candidate in sys.meta_path) != 1
        ):
            raise ImportError("verified six importer is not source-authenticated")
        if not known_name.startswith(producer + "."):
            raise ImportError("six virtual name is outside its producer")
        lookup_name = known_name[len(producer) + 1 :]
        try:
            # The pinned six implementation prefixes importer.name inside
            # _get_module, so the argument is the relative suffix while the
            # public spec and known_modules keys remain fully qualified.
            entry = importer._get_module(lookup_name)
        except (AttributeError, ImportError, KeyError):
            raise ImportError("six virtual name is not declared by pinned source") from None
        if importer.known_modules.get(known_name) is not entry:
            raise ImportError("six virtual mapping changed")
        if virtual_kind == "six_moves_namespace":
            moved_type = module.__dict__.get("_MovedItems")
            if (
                type(entry) is not moved_type
                or entry.__name__ != known_name
                or type(getattr(entry, "__path__", None)) is not list
                or entry.__path__ != []
            ):
                raise ImportError("six moves namespace changed")
        elif virtual_kind == "six_moved_module":
            moved_type = module.__dict__.get("MovedModule")
            moved_attributes = module.__dict__.get("_moved_attributes")
            if (
                type(entry) is not moved_type
                or entry.mod != virtual_target
                or type(moved_attributes) is not list
                or sum(attribute is entry for attribute in moved_attributes) != 1
            ):
                raise ImportError("six moved module mapping changed")
        elif virtual_kind == "six_urllib_namespace":
            urllib_type = module.__dict__.get("Module_six_moves_urllib")
            parse_entry = importer._get_module("moves.urllib_parse")
            canonical_parse_name = producer + ".moves.urllib_parse"
            alias_parse_name = producer + ".moves.urllib.parse"
            if (
                type(entry) is not urllib_type
                or entry.__name__ != known_name
                or type(getattr(entry, "__path__", None)) is not list
                or entry.__path__ != []
                or urllib_type.__dict__.get("parse") is not parse_entry
                or importer.known_modules.get(canonical_parse_name) is not parse_entry
                or importer.known_modules.get(alias_parse_name) is not parse_entry
            ):
                raise ImportError("six urllib namespace mapping changed")
        elif virtual_kind == "six_urllib_parse_module":
            parse_type = module.__dict__.get("Module_six_moves_urllib_parse")
            canonical_parse_name = producer + ".moves.urllib_parse"
            alias_parse_name = producer + ".moves.urllib.parse"
            if (
                type(entry) is not parse_type
                or entry.__name__ != canonical_parse_name
                or importer.known_modules.get(canonical_parse_name) is not entry
                or importer.known_modules.get(alias_parse_name) is not entry
            ):
                raise ImportError("six urllib parse alias changed")
        else:
            raise ImportError("unrecognized six virtual module kind")
        return module, importer, entry, route

    def _six_virtual_spec(self, fullname: str, target: Any) -> Any:
        _module, importer, _entry, route = self._six_importer_context(fullname)
        _producer, known_name, _virtual_kind, _virtual_target = route
        spec = importer.find_spec(known_name, None, target)
        if spec is None or spec.name != fullname or spec.loader is not importer:
            raise ImportError("six virtual module spec changed")
        return spec

    def _six_virtual_metadata_fact(self, fullname: str) -> Dict[str, Any]:
        module, importer, entry, route = self._six_importer_context(fullname)
        producer, known_name, virtual_kind, virtual_target = route
        loaded = sys.modules.get(fullname)
        if loaded is None:
            raise NativeAdapterError("six_virtual_module_missing")
        if virtual_kind in {
            "six_moves_namespace",
            "six_urllib_namespace",
            "six_urllib_parse_module",
        }:
            if loaded is not entry or loaded.__loader__ is not importer:
                raise NativeAdapterError("six_virtual_source_module_changed")
            if virtual_kind in {"six_moves_namespace", "six_urllib_namespace"}:
                if loaded.__name__ != known_name:
                    raise NativeAdapterError("six_virtual_namespace_changed")
            elif loaded.__name__ != producer + ".moves.urllib_parse":
                raise NativeAdapterError("six_virtual_parse_module_changed")
            origin_kind = "six_pinned_source_virtual_module"
        elif virtual_kind == "six_moved_module":
            target_path = self._interpreter_stdlib_path(virtual_target)
            self._verify_interpreter_stdlib_source(virtual_target, target_path)
            target_module = sys.modules.get(virtual_target)
            try:
                target_module_path = Path(target_module.__file__).resolve(strict=True)
                target_spec = target_module.__spec__
                target_loader = target_module.__loader__
                target_loader_path = Path(target_loader.path).resolve(strict=True)
            except (AttributeError, OSError, TypeError, ValueError):
                raise NativeAdapterError("six_virtual_moved_module_origin_missing") from None
            if (
                loaded is not target_module
                or target_module_path != target_path
                or target_spec.name != known_name
                or target_spec.loader is not importer
                or type(target_loader) is not importlib.machinery.SourceFileLoader
                or target_loader.name != virtual_target
                or target_loader_path != target_path
            ):
                raise NativeAdapterError("six_virtual_moved_module_changed")
            origin_kind = "interpreter_stdlib_moved_target"
        else:
            raise NativeAdapterError("six_virtual_module_kind_invalid")
        return {
            "name": fullname,
            "source_kind": "source_derived_virtual",
            "producer_module": producer,
            "producer_sha256": SIX_SOURCE_SHA256,
            "producer_matches_pin": True,
            "importer_type": "_SixMetaPathImporter",
            "importer_registered": importer in sys.meta_path,
            "known_module_name": known_name,
            "known_module_present": importer.known_modules.get(known_name) is entry,
            "virtual_kind": virtual_kind,
            "virtual_target": virtual_target,
            "target_origin_kind": origin_kind,
            "target_origin_verified": True,
        }

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        if fullname == "_ctp":
            raise ImportError("unverified absolute CTP extension blocked")
        if fullname in _SIX_VIRTUAL_ROUTES:
            return self._six_virtual_spec(fullname, target)
        routed_name = self._route_name(fullname)
        top, dot, tail = routed_name.partition(".")
        root = self.roots.get(top)
        if root is None:
            return None
        parts = tail.split(".") if dot and tail else []
        base = root.joinpath(*parts)
        init_file = base / "__init__.py"
        module_file = base.with_suffix(".py") if parts else None
        if init_file.is_file():
            source_path = init_file
            is_package = True
            locations = [str(base)]
        elif module_file is not None and module_file.is_file():
            source_path = module_file
            is_package = False
            locations = None
        else:
            native_name = "bt_api_ctp.ctp._ctp"
            native_relative = "bt_api_ctp/ctp/_ctp.cp311-win_amd64.pyd"
            if fullname == native_name:
                native_path = self.roots["bt_api_ctp"].joinpath(
                    *PurePosixPath(native_relative).parts[1:]
                )
                expected = PINNED_NATIVE_FILES[native_relative][0]
                if (
                    not native_path.is_file()
                    or native_path.is_symlink()
                    or self.verified.get(native_path) != expected
                ):
                    raise ImportError("pinned CTP extension is not recorded")
                loader = _VerifiedSdkExtensionLoader(fullname, native_path, expected)
                return importlib.util.spec_from_file_location(
                    fullname,
                    native_path,
                    loader=loader,
                )
            if top in self.dependency_roots:
                raise ModuleNotFoundError(
                    "unresolved or unpinned dependency module blocked", name=fullname
                )
            raise ModuleNotFoundError("unresolved or unpinned SDK module blocked", name=fullname)
        expected = self.verified.get(source_path)
        if expected is None:
            if top in self.dependency_roots:
                raise ModuleNotFoundError(
                    "dependency source is not in the pinned RECORD", name=fullname
                )
            raise ImportError("SDK source is not in the pinned RECORD")
        verified_resources: Dict[str, Tuple[Path, str]] = {}
        if fullname == CERTIFI_RESOURCE_PACKAGE and is_package:
            resource_path = self.site_packages / CERTIFI_RESOURCE_RELATIVE_PATH
            try:
                resource_path = _ensure_no_reparse_path(
                    resource_path,
                    boundary=self.site_packages,
                    error_code="certifi_resource_path_invalid",
                )
            except NativeAdapterError:
                resource_path = self.site_packages / CERTIFI_RESOURCE_RELATIVE_PATH
            expected_resource_sha256 = self.verified.get(resource_path)
            if expected_resource_sha256 is not None:
                verified_resources[CERTIFI_RESOURCE_NAME] = (
                    resource_path,
                    expected_resource_sha256,
                )
        loader = _VerifiedSdkSourceLoader(
            fullname,
            source_path,
            expected,
            is_package,
            boundary=self.site_packages,
            verified_resources=verified_resources,
        )
        return importlib.util.spec_from_file_location(
            fullname,
            source_path,
            loader=loader,
            submodule_search_locations=locations,
        )


def _require_isolated_sdk_import_path(site_packages: Path) -> None:
    if not getattr(sys.flags, "isolated", 0) or not getattr(sys.flags, "no_site", 0):
        raise NativeAdapterError("pinned_sdk_isolation_required")
    site_root = site_packages.resolve(strict=True)
    for raw in sys.path:
        if not raw:
            raise NativeAdapterError("pinned_sdk_import_path_unsafe")
        try:
            candidate = Path(raw).resolve(strict=False)
            candidate.relative_to(site_root)
        except ValueError:
            continue
        except OSError:
            raise NativeAdapterError("pinned_sdk_import_path_unsafe") from None
        raise NativeAdapterError("pinned_sdk_import_path_unsafe")


def _check_path_chain(path: Path, *, reject_repository: Path) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise NativeAdapterError("private_path_invalid")
    try:
        for part in (path, *path.parents):
            if not part.exists():
                continue
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise NativeAdapterError("private_reparse_path_rejected")
            if part.name == ".git" or (part / ".git").exists():
                raise NativeAdapterError("private_repository_path_rejected")
        resolved = path.resolve(strict=True)
        resolved.relative_to(reject_repository)
    except ValueError:
        # A path inside the source repository is rejected, not resolved through.
        if _is_within(path.resolve(strict=True), reject_repository):
            raise NativeAdapterError("private_repository_path_rejected") from None
        return path.resolve(strict=True)
    except NativeAdapterError:
        raise
    except OSError:
        raise NativeAdapterError("private_path_unavailable") from None
    raise NativeAdapterError("private_repository_path_rejected")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class _Win32PrivateDirectory:
    """Minimal stdlib Win32 owner-only ACL and exclusive snapshot writer."""

    def __init__(self):
        if os.name != "nt":
            raise NativeAdapterError("windows_private_acl_required")
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self.kernel32.GetCurrentProcess.argtypes = []
        self.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL
        self.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self.kernel32.LocalFree.restype = ctypes.c_void_p
        self.kernel32.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetFileAttributesW.restype = wintypes.DWORD
        self.kernel32.CreateDirectoryW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p]
        self.kernel32.CreateDirectoryW.restype = wintypes.BOOL
        self.kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self.kernel32.CreateFileW.restype = wintypes.HANDLE
        self.kernel32.WriteFile.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        self.kernel32.WriteFile.restype = wintypes.BOOL
        self.kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
        self.kernel32.FlushFileBuffers.restype = wintypes.BOOL
        self.advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        self.advapi32.OpenProcessToken.restype = wintypes.BOOL
        self.advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.advapi32.GetTokenInformation.restype = wintypes.BOOL
        self.advapi32.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.LPWSTR),
        ]
        self.advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
        self.advapi32.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.advapi32.EqualSid.restype = wintypes.BOOL
        self.advapi32.GetSecurityDescriptorDacl.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.BOOL),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.BOOL),
        ]
        self.advapi32.GetSecurityDescriptorDacl.restype = wintypes.BOOL
        self.advapi32.GetSecurityDescriptorControl.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.WORD),
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.advapi32.GetSecurityDescriptorControl.restype = wintypes.BOOL
        self.advapi32.GetAclInformation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self.advapi32.GetAclInformation.restype = wintypes.BOOL
        self.advapi32.GetAce.argtypes = [
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.advapi32.GetAce.restype = wintypes.BOOL
        self._owner_sid_buffer, self.owner_sid = self._current_owner_sid()
        self.owner_sid_text = self._sid_text(self.owner_sid)

    def _current_owner_sid(self) -> Tuple[Any, Any]:
        token = wintypes.HANDLE()
        if not self.advapi32.OpenProcessToken(
            self.kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)
        ):
            raise NativeAdapterError("owner_token_unavailable")
        try:
            size = wintypes.DWORD()
            self.advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            if not size.value:
                raise NativeAdapterError("owner_token_unavailable")
            buffer = ctypes.create_string_buffer(size.value)
            if not self.advapi32.GetTokenInformation(
                token, 1, buffer, size.value, ctypes.byref(size)
            ):
                raise NativeAdapterError("owner_token_unavailable")
            sid_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p)).contents.value
            if not sid_pointer:
                raise NativeAdapterError("owner_token_unavailable")
            return buffer, ctypes.c_void_p(sid_pointer)
        finally:
            self.kernel32.CloseHandle(token)

    def _sid_text(self, sid: Any) -> str:
        text_pointer = wintypes.LPWSTR()
        if not self.advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text_pointer)):
            raise NativeAdapterError("owner_sid_unavailable")
        try:
            return str(text_pointer.value)
        finally:
            self.kernel32.LocalFree(text_pointer)

    def _security_descriptor(self, path: Path) -> Tuple[Any, Any, Any]:
        owner = ctypes.c_void_p()
        group = ctypes.c_void_p()
        dacl = ctypes.c_void_p()
        sacl = ctypes.c_void_p()
        descriptor = ctypes.c_void_p()
        get_named = self.advapi32.GetNamedSecurityInfoW
        get_named.argtypes = [
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        get_named.restype = wintypes.DWORD
        result = get_named(
            str(path),
            1,
            0x00000001 | 0x00000004,
            ctypes.byref(owner),
            ctypes.byref(group),
            ctypes.byref(dacl),
            ctypes.byref(sacl),
            ctypes.byref(descriptor),
        )
        if result != 0 or not descriptor.value:
            raise NativeAdapterError("owner_acl_unverified")
        return owner, dacl, descriptor

    def _verify_acl(self, path: Path, *, directory: bool) -> None:
        owner, dacl, descriptor = self._security_descriptor(path)
        try:
            if not owner.value or not self.advapi32.EqualSid(owner, self.owner_sid):
                raise NativeAdapterError("owner_acl_unverified")
            present, defaulted = wintypes.BOOL(), wintypes.BOOL()
            acl_pointer = ctypes.c_void_p()
            if not self.advapi32.GetSecurityDescriptorDacl(
                descriptor,
                ctypes.byref(present),
                ctypes.byref(acl_pointer),
                ctypes.byref(defaulted),
            ):
                raise NativeAdapterError("owner_acl_unverified")
            if not present.value or not acl_pointer.value:
                raise NativeAdapterError("owner_acl_unverified")
            control, revision = wintypes.WORD(), wintypes.DWORD()
            if not self.advapi32.GetSecurityDescriptorControl(
                descriptor, ctypes.byref(control), ctypes.byref(revision)
            ) or not (control.value & 0x1000):
                raise NativeAdapterError("owner_acl_unverified")

            class _ACL_SIZE(ctypes.Structure):
                _fields_ = [
                    ("AceCount", wintypes.DWORD),
                    ("AclBytesInUse", wintypes.DWORD),
                    ("AclBytesFree", wintypes.DWORD),
                ]

            info = _ACL_SIZE()
            if (
                not self.advapi32.GetAclInformation(
                    acl_pointer, ctypes.byref(info), ctypes.sizeof(info), 2
                )
                or info.AceCount != 1
            ):
                raise NativeAdapterError("owner_acl_unverified")
            ace = ctypes.c_void_p()
            if not self.advapi32.GetAce(acl_pointer, 0, ctypes.byref(ace)):
                raise NativeAdapterError("owner_acl_unverified")
            header = ctypes.cast(ace, ctypes.POINTER(ctypes.c_ubyte * 4)).contents
            expected_flags = 0x03 if directory else 0x00  # OI|CI only on a directory.
            if header[0] != 0 or header[1] != expected_flags:
                raise NativeAdapterError("owner_acl_unverified")
            mask = ctypes.cast(ace.value + 4, ctypes.POINTER(wintypes.DWORD)).contents.value
            sid_pointer = ctypes.c_void_p(ace.value + 8)
            if mask != 0x001F01FF or not self.advapi32.EqualSid(sid_pointer, self.owner_sid):
                raise NativeAdapterError("owner_acl_unverified")
        finally:
            self.kernel32.LocalFree(descriptor)

    def _attributes(self, path: Path) -> int:
        value = self.kernel32.GetFileAttributesW(str(path))
        if value == 0xFFFFFFFF:
            raise NativeAdapterError("private_path_unavailable")
        if value & 0x400:
            raise NativeAdapterError("private_reparse_path_rejected")
        return int(value)

    def verify_directory(self, path: Path) -> None:
        if not path.is_dir():
            raise NativeAdapterError("private_directory_unavailable")
        self._attributes(path)
        self._verify_acl(path, directory=True)

    def _descriptor_for(self, *, directory: bool) -> Tuple[Any, wintypes.LPWSTR]:
        descriptor = ctypes.c_void_p()
        flags = "OICI" if directory else ""
        sddl = f"O:{self.owner_sid_text}D:P(A;{flags};FA;;;{self.owner_sid_text})"
        convert = self.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
        convert.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
        ]
        convert.restype = wintypes.BOOL
        if not convert(sddl, 1, ctypes.byref(descriptor), None):
            raise NativeAdapterError("owner_acl_create_failed")
        return descriptor, sddl

    def create_child_directory(self, path: Path) -> None:
        descriptor, _ = self._descriptor_for(directory=True)

        class _SECURITY_ATTRIBUTES(ctypes.Structure):
            _fields_ = [
                ("nLength", wintypes.DWORD),
                ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL),
            ]

        try:
            attributes = _SECURITY_ATTRIBUTES(
                ctypes.sizeof(_SECURITY_ATTRIBUTES), descriptor, False
            )
            if not self.kernel32.CreateDirectoryW(str(path), ctypes.byref(attributes)):
                raise NativeAdapterError("snapshot_directory_create_failed")
        finally:
            self.kernel32.LocalFree(descriptor)
        self.verify_directory(path)

    def write_json_new(self, path: Path, payload: bytes) -> str:
        if len(payload) > MAX_PRIVATE_SNAPSHOT_BYTES or not payload.endswith(b"\n"):
            raise NativeAdapterError("snapshot_size_invalid")
        descriptor, _ = self._descriptor_for(directory=False)

        class _SECURITY_ATTRIBUTES(ctypes.Structure):
            _fields_ = [
                ("nLength", wintypes.DWORD),
                ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL),
            ]

        handle = wintypes.HANDLE()
        try:
            attributes = _SECURITY_ATTRIBUTES(
                ctypes.sizeof(_SECURITY_ATTRIBUTES), descriptor, False
            )
            handle = self.kernel32.CreateFileW(
                str(path),
                0x40000000 | 0x00020000,
                0,
                ctypes.byref(attributes),
                1,  # CREATE_NEW, never replace a prior artifact.
                0x80 | 0x00200000,  # NORMAL | OPEN_REPARSE_POINT.
                None,
            )
            if handle == ctypes.c_void_p(-1).value or not handle:
                raise NativeAdapterError("snapshot_create_failed")
        finally:
            self.kernel32.LocalFree(descriptor)
        try:
            self._verify_acl(path, directory=False)
            offset = 0
            while offset < len(payload):
                block = payload[offset : offset + 65536]
                written = wintypes.DWORD()
                buffer = ctypes.create_string_buffer(block)
                if not self.kernel32.WriteFile(
                    handle, buffer, len(block), ctypes.byref(written), None
                ) or written.value != len(block):
                    raise NativeAdapterError("snapshot_write_failed")
                offset += written.value
            if not self.kernel32.FlushFileBuffers(handle):
                raise NativeAdapterError("snapshot_flush_failed")
        finally:
            self.kernel32.CloseHandle(handle)
        return hashlib.sha256(payload).hexdigest()


class _C01StageIntentWriter:
    """Emit bounded, source-bound local stage intents on a diagnostic pipe."""

    def __init__(self, descriptor: int, launch: Any, worker_source_sha256: str) -> None:
        if type(descriptor) is not int or descriptor < 0:
            raise NativeAdapterError("stage_intent_descriptor_invalid")
        if type(worker_source_sha256) is not str or not _SHA256_RE.fullmatch(worker_source_sha256):
            raise NativeAdapterError("stage_intent_source_binding_invalid")
        pair_binding_ref = launch.pair_binding.to_receipt_ref().to_dict()
        if type(pair_binding_ref) is not dict or set(pair_binding_ref) != {
            "selected_index",
            "selection_sha256",
            "md_front_sha256",
            "td_front_sha256",
            "selected_at_utc",
        }:
            raise NativeAdapterError("stage_intent_pair_binding_invalid")
        if (
            type(pair_binding_ref["selected_index"]) is not int
            or pair_binding_ref["selected_index"] < 0
            or any(
                type(pair_binding_ref[name]) is not str
                or not _SHA256_RE.fullmatch(pair_binding_ref[name])
                for name in ("selection_sha256", "md_front_sha256", "td_front_sha256")
            )
            or type(pair_binding_ref["selected_at_utc"]) is not str
            or not pair_binding_ref["selected_at_utc"]
            or len(pair_binding_ref["selected_at_utc"]) > 64
            or any(
                unicodedata.category(char) == "Cc" for char in pair_binding_ref["selected_at_utc"]
            )
        ):
            raise NativeAdapterError("stage_intent_pair_binding_invalid")
        if (
            type(launch.run_nonce) is not str
            or not re.fullmatch(r"[0-9a-f]{32}", launch.run_nonce)
            or type(launch.parent_pid) is not int
            or launch.parent_pid < 1
        ):
            raise NativeAdapterError("stage_intent_run_binding_invalid")
        self._descriptor = descriptor
        self._run_nonce = launch.run_nonce
        self._parent_pid = launch.parent_pid
        self._worker_pid = os.getpid()
        self._worker_source_sha256 = worker_source_sha256
        self._pair_binding_ref = dict(pair_binding_ref)
        self._sequence = 0
        self._total_bytes = len(STAGE_INTENT_MAGIC)
        self._header_sent = False
        self._failed = False
        self._lock = threading.Lock()

    def emit(self, stage: str, event: str) -> None:
        with self._lock:
            if self._failed:
                raise NativeAdapterError("stage_intent_write_failed")
            if stage not in _PROGRESS_STAGES or event not in _PROGRESS_EVENTS:
                self._failed = True
                raise NativeAdapterError("stage_intent_value_invalid")
            if self._sequence >= MAX_STAGE_INTENT_RECORDS:
                self._failed = True
                raise NativeAdapterError("stage_intent_record_limit_exceeded")
            document = {
                "protocol": STAGE_INTENT_PROTOCOL,
                "version": 1,
                "case_id": "C01",
                "sequence": self._sequence + 1,
                "stage": stage,
                "event": event,
                "run_nonce": self._run_nonce,
                "parent_pid": self._parent_pid,
                "worker_pid": self._worker_pid,
                "worker_source_sha256": self._worker_source_sha256,
                "pair_binding_ref": self._pair_binding_ref,
            }
            try:
                payload = json.dumps(
                    document,
                    ensure_ascii=True,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("ascii")
            except Exception:
                self._failed = True
                raise NativeAdapterError("stage_intent_encoding_failed") from None
            frame = struct.pack(">H", len(payload)) + payload
            if len(frame) > MAX_STAGE_INTENT_FRAME_BYTES:
                self._failed = True
                raise NativeAdapterError("stage_intent_frame_limit_exceeded")
            wire = (STAGE_INTENT_MAGIC if not self._header_sent else b"") + frame
            if self._total_bytes + len(frame) > MAX_STAGE_INTENT_TOTAL_BYTES:
                self._failed = True
                raise NativeAdapterError("stage_intent_total_limit_exceeded")
            try:
                offset = 0
                while offset < len(wire):
                    written = os.write(self._descriptor, wire[offset:])
                    if written <= 0:
                        raise OSError("stage intent pipe write returned no bytes")
                    offset += written
            except Exception:
                self._failed = True
                raise NativeAdapterError("stage_intent_write_failed") from None
            self._header_sent = True
            self._sequence += 1
            self._total_bytes += len(frame)


class _C01ProgressRecorder:
    """Durably record fixed local worker stages under the private evidence ACL."""

    def __init__(
        self,
        private_acl: Any,
        evidence_dir: Path,
        launch: Any,
        worker_source_sha256: str,
        stage_intent_writer: Optional[_C01StageIntentWriter] = None,
    ) -> None:
        if type(worker_source_sha256) is not str or not _SHA256_RE.fullmatch(worker_source_sha256):
            raise NativeAdapterError("progress_worker_source_binding_invalid")
        pair_binding = launch.pair_binding.to_receipt_ref().to_dict()
        if type(pair_binding) is not dict or set(pair_binding) != {
            "selected_index",
            "selection_sha256",
            "md_front_sha256",
            "td_front_sha256",
            "selected_at_utc",
        }:
            raise NativeAdapterError("progress_pair_binding_invalid")
        if (
            type(pair_binding["selected_index"]) is not int
            or pair_binding["selected_index"] < 0
            or any(
                type(pair_binding[name]) is not str or not _SHA256_RE.fullmatch(pair_binding[name])
                for name in ("selection_sha256", "md_front_sha256", "td_front_sha256")
            )
            or type(pair_binding["selected_at_utc"]) is not str
            or not pair_binding["selected_at_utc"]
            or len(pair_binding["selected_at_utc"]) > 64
            or any(unicodedata.category(char) == "Cc" for char in pair_binding["selected_at_utc"])
        ):
            raise NativeAdapterError("progress_pair_binding_invalid")
        if (
            type(launch.run_nonce) is not str
            or not re.fullmatch(r"[0-9a-f]{32}", launch.run_nonce)
            or type(launch.parent_pid) is not int
            or launch.parent_pid < 1
            or type(launch.account_scope_sha256) is not str
            or not _SHA256_RE.fullmatch(launch.account_scope_sha256)
            or type(launch.credential_binding_sha256) is not str
            or not _SHA256_RE.fullmatch(launch.credential_binding_sha256)
        ):
            raise NativeAdapterError("progress_run_binding_invalid")
        self._private_acl = private_acl
        self._evidence_dir = evidence_dir
        self._run_nonce = launch.run_nonce
        self._parent_pid = launch.parent_pid
        self._worker_pid = os.getpid()
        self._worker_source_sha256 = worker_source_sha256
        self._pair_binding = pair_binding
        self._account_scope_sha256 = launch.account_scope_sha256
        self._credential_binding_sha256 = launch.credential_binding_sha256
        self._sequence = 0
        self._total_bytes = 0
        self._previous_sha256 = "0" * 64
        self._failed = False
        self._lock = threading.RLock()
        if (
            stage_intent_writer is not None
            and type(stage_intent_writer) is not _C01StageIntentWriter
        ):
            raise NativeAdapterError("stage_intent_writer_invalid")
        self._stage_intent_writer = stage_intent_writer

    @property
    def record_count(self) -> int:
        return self._sequence

    @property
    def failed(self) -> bool:
        return self._failed

    def record(self, stage: str, event: str) -> str:
        with self._lock:
            if self._failed:
                raise NativeAdapterError("progress_record_write_failed")
            if stage not in _PROGRESS_STAGES or event not in _PROGRESS_EVENTS:
                raise NativeAdapterError("progress_stage_invalid")
            if (
                self._sequence >= MAX_PRIVATE_PROGRESS_RECORDS
                or self._total_bytes >= MAX_PRIVATE_PROGRESS_TOTAL_BYTES
            ):
                self._failed = True
                raise NativeAdapterError("progress_record_limit_exceeded")
            sequence = self._sequence + 1
            if self._stage_intent_writer is not None:
                try:
                    self._stage_intent_writer.emit(stage, event)
                except Exception:
                    self._failed = True
                    raise NativeAdapterError("progress_intent_write_failed") from None
            document = {
                "protocol": _PROGRESS_PROTOCOL,
                "version": 1,
                "case_id": "C01",
                "sequence": sequence,
                "stage": stage,
                "event": event,
                "run_nonce": self._run_nonce,
                "parent_pid": self._parent_pid,
                "worker_pid": self._worker_pid,
                "worker_source_sha256": self._worker_source_sha256,
                "account_scope_sha256": self._account_scope_sha256,
                "credential_binding_sha256": self._credential_binding_sha256,
                "pair_binding": self._pair_binding,
                "recorded_at_utc": _utc_now(),
                "recorded_monotonic_ns": time.monotonic_ns(),
                "previous_record_sha256": self._previous_sha256,
            }
            try:
                payload = (
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
                self._failed = True
                raise NativeAdapterError("progress_record_encoding_failed") from None
            if (
                len(payload) > MAX_PRIVATE_PROGRESS_RECORD_BYTES
                or self._total_bytes + len(payload) > MAX_PRIVATE_PROGRESS_TOTAL_BYTES
            ):
                self._failed = True
                raise NativeAdapterError("progress_record_limit_exceeded")
            path = self._evidence_dir / ("progress-{:03d}.json".format(sequence))
            try:
                self._private_acl.verify_directory(self._evidence_dir)
                digest = self._private_acl.write_json_new(path, payload)
                expected = hashlib.sha256(payload).hexdigest()
                if digest != expected:
                    raise NativeAdapterError("progress_record_digest_mismatch")
            except Exception:
                self._failed = True
                raise NativeAdapterError("progress_record_write_failed") from None
            self._sequence = sequence
            self._total_bytes += len(payload)
            self._previous_sha256 = expected
            return expected


class C01NativeCapture:
    """Bounded adapter-local call/callback timeline with no credential fields."""

    def __init__(self, account_scope_sha256: str, credential_binding_sha256: str):
        self.account_scope_sha256 = account_scope_sha256
        self.credential_binding_sha256 = credential_binding_sha256
        self.instance_id = os.urandom(16).hex()
        self.client_generation = 1
        self.arrival_generation: Optional[int] = None
        self.requests: list = []
        self.callbacks: list = []
        self.private_callback_rows: list = []
        self.requests_by_id: Dict[int, Dict[str, Any]] = {}
        self.query_callbacks: Dict[int, list] = {}
        self._next_request_generation = 0
        self._next_sequence = 0
        self._phase: Optional[str] = None
        self._lock = threading.RLock()
        self._client: Any = None
        self._snapshotter: Optional[Callable[[Any], Dict[str, Any]]] = None
        self._progress_recorder: Optional[_C01ProgressRecorder] = None
        self._start_precheck_thread_id: Optional[int] = None
        self._progress_callback_first: set = set()
        self._failure: Optional[str] = None
        self._login_trading_day: Optional[str] = None
        self.write_counters = {"ReqOrderInsert": 0, "ReqOrderAction": 0}

    def bind_client(self, client: Any) -> None:
        self._client = client

    def bind_snapshotter(self, snapshotter: Callable[[Any], Dict[str, Any]]) -> None:
        self._snapshotter = snapshotter

    def bind_progress_recorder(self, recorder: _C01ProgressRecorder) -> None:
        self._progress_recorder = recorder

    def progress_event(self, stage: str, event: str, *, required: bool = True) -> bool:
        if self._progress_recorder is None:
            return True
        try:
            self._progress_recorder.record(stage, event)
            return True
        except Exception:
            self._failure = "progress_record_write_failed"
            if required:
                raise _CandidateAbort() from None
            return False

    def set_phase(self, phase: str) -> None:
        if phase not in ("baseline", "final"):
            raise NativeAdapterError("query_phase_invalid")
        self._phase = phase

    def _sequence(self) -> int:
        self._next_sequence += 1
        return self._next_sequence

    def _client_facts(self) -> Tuple[int, int]:
        if self._client is None:
            raise NativeAdapterError("sdk_client_unbound")
        api_generation = int(getattr(self._client, "_native_api_generation", 0) or 0)
        arrival_generation = int(getattr(self._client, "_connection_generation", 0) or 0)
        if api_generation < 1 or arrival_generation < 1:
            raise NativeAdapterError("sdk_client_generation_invalid")
        if self.arrival_generation is None:
            self.arrival_generation = arrival_generation
        elif self.arrival_generation != arrival_generation:
            self._failure = "connection_generation_changed"
        self.client_generation = api_generation
        return api_generation, arrival_generation

    def native_request(
        self,
        method: str,
        request_id_value: Any,
        invoke: Callable[[], Any],
        *,
        native_field: Any = None,
        credentials: Optional[Mapping[str, str]] = None,
    ) -> Any:
        with self._lock:
            expected_index = len(self.requests)
            if expected_index >= len(_REQUEST_PLAN) or method != _REQUEST_PLAN[expected_index][3]:
                if method == "ReqOrderInsert" or method == "ReqOrderAction":
                    self.write_counters[method] += 1
                self._failure = "native_request_allowlist_violation"
                raise _CandidateAbort()
            kind, phase, family, _ = _REQUEST_PLAN[expected_index]
            if kind == "query" and self._phase != phase:
                self._failure = "native_query_phase_mismatch"
                raise _CandidateAbort()
            request_id = _as_native_int(request_id_value)
            if request_id is None or request_id < 1 or request_id in self.requests_by_id:
                self._failure = "native_request_id_invalid"
                raise _CandidateAbort()
            client_generation, _ = self._client_facts()
            self._next_request_generation += 1
            request_generation = self._next_request_generation
            issued_at_utc = _utc_now()
            issued_monotonic_ns = time.monotonic_ns()
            local_sequence = self._sequence()
            try:
                _validate_native_request_fields(method, native_field, credentials)
            except NativeAdapterError as exc:
                self._failure = str(exc)
                raise _CandidateAbort() from None
            request = {
                "kind": kind,
                "phase": phase,
                "family": family,
                "method": method,
                "request_id": request_id,
                "request_generation": request_generation,
                "local_sequence": local_sequence,
                "issued_at_utc": issued_at_utc,
                "issued_monotonic_ns": issued_monotonic_ns,
                "return_code": None,
                "sdk_query_result": None,
                "receipt_origin": "local_native_invocation",
                "account_scope_sha256": self.account_scope_sha256,
                "credential_binding_sha256": self.credential_binding_sha256,
            }
            stage_key = method if kind in {"authenticate", "login"} else (phase, family)
            progress_stage = _PROGRESS_STAGE_REQUEST.get(stage_key)
            if progress_stage is None:
                self._failure = "progress_stage_invalid"
                raise _CandidateAbort()
            self.progress_event(progress_stage, "begin")
            self.requests.append(request)
            self.requests_by_id[request_id] = request
            try:
                result = invoke()
            except Exception:
                self._failure = "native_request_invocation_failed"
                raise _CandidateAbort() from None
            if type(result) is not int:
                self._failure = "native_request_return_type_invalid"
                raise _CandidateAbort()
            request["return_code"] = result
            self.progress_event(progress_stage, "end")
            return result

    def response_callback(
        self,
        callback_name: str,
        request_id_value: Any,
        error_info: Any,
        is_last_value: Any,
        row: Any,
        *,
        login_field: bool = False,
    ) -> Dict[str, Any]:
        request_id = _as_native_int(request_id_value)
        try:
            rsp_info_present, error_id = _native_error_facts(error_info)
        except NativeAdapterError as exc:
            self._failure = str(exc)
            raise _CandidateAbort() from None
        error_semantics = RSP_INFO_ERROR_ID_PRESENT if rsp_info_present else RSP_INFO_ABSENT
        is_last = _native_bool(is_last_value)
        if request_id is None or request_id < 1 or is_last is None:
            self._failure = "native_response_metadata_invalid"
            raise _CandidateAbort()
        with self._lock:
            request = self.requests_by_id.get(request_id)
            if request is None:
                self._failure = "native_response_request_unbound"
                raise _CandidateAbort()
            client_generation, arrival_generation = self._client_facts()
            if callback_name == "OnRspAuthenticate":
                kind, phase, family = "authenticate", None, None
            elif callback_name == "OnRspUserLogin":
                kind, phase, family = "login", None, None
            else:
                family, expected_name = next(
                    (
                        (family, name)
                        for family, name in _CALLBACKS.values()
                        if name == callback_name
                    ),
                    (None, None),
                )
                if family is None or callback_name != expected_name or request["family"] != family:
                    self._failure = "native_query_callback_unbound"
                    raise _CandidateAbort()
                kind, phase = "query", request["phase"]
            if (kind, phase, family) != (request["kind"], request["phase"], request["family"]):
                self._failure = "native_response_scope_mismatch"
                raise _CandidateAbort()
            if kind in {"authenticate", "login"} and (
                rsp_info_present is not True or type(error_id) is not int or error_id != 0
            ):
                self._failure = "auth_login_error_info_unverified"
                raise _CandidateAbort()
            callback_stage_key = kind if kind in {"authenticate", "login"} else (phase, family)
            callback_stage = _PROGRESS_STAGE_CALLBACK.get(callback_stage_key)
            if callback_stage is None:
                self._failure = "progress_stage_invalid"
                raise _CandidateAbort()
            request_generation = request["request_generation"]
            if request_generation not in self._progress_callback_first:
                self.progress_event(callback_stage, "callback_first")
                self._progress_callback_first.add(request_generation)
            row_snapshot = None
            if kind == "query" and row is not None:
                if self._snapshotter is None:
                    self._failure = "native_row_snapshotter_missing"
                    raise _CandidateAbort()
                try:
                    row_snapshot = _json_safe(self._snapshotter(row))
                except Exception:
                    self._failure = "native_row_snapshot_failed"
                    raise _CandidateAbort() from None
                if family in {"orders", "positions"}:
                    expected = getattr(self, "_credentials", {})
                    try:
                        broker = _exact_position_text(row_snapshot, "BrokerID")
                        investor = _exact_position_text(row_snapshot, "InvestorID")
                    except NativeAdapterError:
                        self._failure = "query_row_account_identity_unavailable"
                        raise _CandidateAbort() from None
                    if broker != expected.get("broker_id"):
                        self._failure = "query_row_broker_mismatch"
                    if investor != expected.get("user_id"):
                        self._failure = "query_row_investor_mismatch"
                elif family == "funds":
                    expected = getattr(self, "_credentials", {})
                    try:
                        broker = _exact_position_text(row_snapshot, "BrokerID")
                        account = _exact_position_text(row_snapshot, "AccountID")
                    except NativeAdapterError:
                        self._failure = "query_row_account_identity_unavailable"
                        raise _CandidateAbort() from None
                    if broker != expected.get("broker_id"):
                        self._failure = "query_row_broker_mismatch"
                    if account != expected.get("user_id"):
                        self._failure = "query_row_account_mismatch"
            if login_field:
                broker = _native_text(row, "BrokerID")
                investor = _native_text(row, "UserID")
                expected = getattr(self, "_credentials", {})
                if broker != expected.get("broker_id") or investor != expected.get("user_id"):
                    self._failure = "login_identity_mismatch"
                front_id = _as_native_int(_native_field(row, "FrontID"))
                session_raw = _native_field(row, "SessionID")
                session_id = str(session_raw) if session_raw is not None else ""
                trading_day = _native_text(row, "TradingDay")
                if is_last is True:
                    self._login_trading_day = trading_day
            else:
                front_id = None
                session_id = None
                trading_day = None
            callback = {
                "kind": kind,
                "phase": phase,
                "family": family,
                "callback_name": callback_name,
                "request_id": request_id,
                "error_id": error_id,
                "rsp_info_present": rsp_info_present,
                "error_semantics": error_semantics,
                "is_last": is_last,
                "request_generation": request["request_generation"],
                "client_instance_id": self.instance_id,
                "client_generation": client_generation,
                "arrival_generation": arrival_generation,
                "local_sequence": self._sequence(),
                "arrived_at_utc": _utc_now(),
                "arrived_monotonic_ns": time.monotonic_ns(),
                "row_present": row is not None if kind == "query" else None,
                "front_id": front_id,
                "session_id": session_id,
                "trading_day": trading_day,
                "account_scope_sha256": self.account_scope_sha256,
                "credential_binding_sha256": self.credential_binding_sha256,
            }
            if kind in {"authenticate", "login"}:
                private_row = None
                capture_error = None
                if row is not None:
                    if self._snapshotter is None:
                        capture_error = "native_callback_snapshotter_missing"
                    else:
                        try:
                            private_row = _json_safe(self._snapshotter(row))
                        except Exception:
                            capture_error = "native_callback_snapshot_failed"
                if len(self.private_callback_rows) >= MAX_CALLBACKS:
                    self._failure = "native_callback_limit_exceeded"
                    raise _CandidateAbort()
                self.private_callback_rows.append(
                    {
                        "callback_name": callback_name,
                        "request_id": request_id,
                        "request_generation": request["request_generation"],
                        "local_sequence": callback["local_sequence"],
                        "row_present": row is not None,
                        "row": private_row,
                        "capture_error": capture_error,
                    }
                )
            if len(self.callbacks) >= MAX_CALLBACKS:
                self._failure = "native_callback_limit_exceeded"
                raise _CandidateAbort()
            self.callbacks.append(callback)
            if kind == "query":
                query_callback = {
                    "callback_name": callback_name,
                    "request_id": request_id,
                    "error_id": error_id,
                    "rsp_info_present": rsp_info_present,
                    "error_semantics": error_semantics,
                    "is_last": is_last,
                    "request_generation": request["request_generation"],
                    "local_sequence": callback["local_sequence"],
                    "arrived_at_utc": callback["arrived_at_utc"],
                    "arrived_monotonic_ns": callback["arrived_monotonic_ns"],
                    "row_present": row is not None,
                    "row": row_snapshot,
                }
                self.query_callbacks.setdefault(request_id, []).append(query_callback)
            if is_last is True:
                self.progress_event(callback_stage, "callback_terminal")
            return callback

    def activity_callback(self, callback_name: str) -> Dict[str, Any]:
        kind = {"OnRtnOrder": "order_activity", "OnRtnTrade": "trade_activity"}.get(callback_name)
        if kind is None:
            self._failure = "native_activity_callback_invalid"
            raise _CandidateAbort()
        with self._lock:
            client_generation, arrival_generation = self._client_facts()
            callback = {
                "kind": kind,
                "phase": None,
                "family": None,
                "callback_name": callback_name,
                "request_id": None,
                "error_id": None,
                "rsp_info_present": None,
                "error_semantics": None,
                "is_last": None,
                "request_generation": None,
                "client_instance_id": self.instance_id,
                "client_generation": client_generation,
                "arrival_generation": arrival_generation,
                "local_sequence": self._sequence(),
                "arrived_at_utc": _utc_now(),
                "arrived_monotonic_ns": time.monotonic_ns(),
                "row_present": None,
                "front_id": None,
                "session_id": None,
                "trading_day": None,
                "account_scope_sha256": self.account_scope_sha256,
                "credential_binding_sha256": self.credential_binding_sha256,
            }
            if len(self.callbacks) >= MAX_CALLBACKS:
                self._failure = "native_callback_limit_exceeded"
                raise _CandidateAbort()
            self.callbacks.append(callback)
            return callback

    def login_facts(self) -> Tuple[int, str, str]:
        matches = [
            item for item in self.callbacks if item["kind"] == "login" and item["is_last"] is True
        ]
        if len(matches) != 1:
            raise NativeAdapterError("login_terminal_callback_invalid")
        item = matches[0]
        if (
            item["rsp_info_present"] is not True
            or type(item["error_id"]) is not int
            or item["error_id"] != 0
            or item["error_semantics"] != RSP_INFO_ERROR_ID_PRESENT
        ):
            raise NativeAdapterError("login_error_id_unverified")
        return item["front_id"], item["session_id"], item["trading_day"]


def _as_native_int(value: Any, *, allow_none: bool = False) -> Optional[int]:
    if value is None and allow_none:
        return None
    if type(value) is int:
        return value
    try:
        converted = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(value, bool) or str(converted) != str(value):
        return None
    return converted


def _native_bool(value: Any) -> Optional[bool]:
    return value if type(value) is bool else None


def _native_error_facts(rsp_info: Any) -> Tuple[bool, Optional[int]]:
    if rsp_info is None:
        return False, None
    try:
        value = getattr(rsp_info, "ErrorID")
    except Exception:
        raise NativeAdapterError("native_response_error_info_invalid") from None
    if type(value) is not int or value < 0:
        raise NativeAdapterError("native_response_error_id_malformed")
    return True, value


def _native_field(source: Any, name: str) -> Any:
    try:
        return getattr(source, name) if source is not None else None
    except Exception:
        return None


def _native_text(source: Any, name: str) -> str:
    value = _native_field(source, name)
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return ""
    return str(value)


def _json_safe(value: Any) -> Any:
    if value is None or type(value) in (bool, int, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict")
    if type(value) is float:
        if not math.isfinite(value):
            raise NativeAdapterError("non_finite_native_row")
        return value
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise NativeAdapterError("native_row_key_invalid")
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    raise NativeAdapterError("native_row_value_unsupported")


def _field_decimal(row: Mapping[str, Any], field: str) -> str:
    if field not in row or row[field] is None:
        raise NativeAdapterError("native_projection_field_missing")
    return _decimal_text(row[field])


def _ctp_code(value: Any) -> str:
    if value is None:
        return ""
    try:
        return _native_text_exact(value)
    except NativeAdapterError:
        raise NativeAdapterError("native_order_text_invalid") from None


def _exact_nonnegative_integer(value: Any) -> int:
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            raise NativeAdapterError("native_order_quantity_invalid") from None
    if type(value) is int:
        parsed = value
    elif (
        type(value) is str
        and 1 <= len(value) <= MAX_POSITION_DECIMAL_INPUT_CHARS
        and value
        and (value == "0" or value[0] in "123456789")
    ):
        if not value.isascii() or not value.isdecimal():
            raise NativeAdapterError("native_order_quantity_invalid")
        try:
            parsed = int(value)
        except (ValueError, OverflowError):
            raise NativeAdapterError("native_order_quantity_invalid") from None
        if str(parsed) != value:
            raise NativeAdapterError("native_order_quantity_invalid")
    else:
        raise NativeAdapterError("native_order_quantity_invalid")
    if parsed < 0:
        raise NativeAdapterError("native_order_quantity_invalid")
    return parsed


def _order_status_and_remaining(row: Mapping[str, Any]) -> Tuple[str, int]:
    status = _ctp_code(row.get("OrderStatus"))
    if status not in _KNOWN_ORDER_STATUSES:
        raise NativeAdapterError("native_order_status_unknown")
    total = _exact_nonnegative_integer(row.get("VolumeTotalOriginal"))
    traded = _exact_nonnegative_integer(row.get("VolumeTraded"))
    if total >= 10**30 or traded >= 10**30 or traded > total:
        raise NativeAdapterError("native_order_quantity_invalid")
    return status, total - traded


def _order_exact_text(row: Mapping[str, Any], field: str, *, allow_empty: bool = False) -> str:
    if field not in row or row[field] is None:
        raise NativeAdapterError("native_order_field_missing")
    try:
        value = _native_text_exact(row[field])
    except NativeAdapterError:
        raise NativeAdapterError("native_order_text_invalid") from None
    if not allow_empty and not value:
        raise NativeAdapterError("native_order_text_invalid")
    return value


def _order_bounded_integer(value: Any) -> int:
    try:
        parsed = _exact_nonnegative_integer(value)
    except NativeAdapterError:
        raise NativeAdapterError("native_order_integer_invalid") from None
    if parsed >= 10**30:
        raise NativeAdapterError("native_order_integer_invalid")
    return parsed


def _order_identity(
    row: Mapping[str, Any],
    protocol: Any,
    *,
    expected_broker_id: str,
    expected_user_id: str,
    trading_day: str,
) -> Dict[str, Any]:
    identity: Dict[str, Any] = {}
    allow_empty = {"ExchangeID", "OrderSysID", "OrderRef"}
    for field in protocol.ORDER_IDENTITY_TEXT_FIELDS:
        value = _order_exact_text(row, field, allow_empty=field in allow_empty)
        if field == "BrokerID" and value != expected_broker_id:
            raise NativeAdapterError("query_row_broker_mismatch")
        if field == "InvestorID" and value != expected_user_id:
            raise NativeAdapterError("query_row_investor_mismatch")
        if field == "TradingDay" and value != trading_day:
            raise NativeAdapterError("order_trading_day_mismatch")
        identity[field] = value
    for field in protocol.ORDER_IDENTITY_INTEGER_FIELDS:
        identity[field] = _order_bounded_integer(row.get(field))
    if not (
        (identity["ExchangeID"] and identity["OrderSysID"])
        or (identity["OrderRef"] and identity["FrontID"] > 0 and identity["SessionID"] > 0)
    ):
        raise NativeAdapterError("open_order_identity_unavailable")
    return identity


def project_order_economics(
    rows: Iterable[Mapping[str, Any]],
    protocol: Any,
    *,
    expected_broker_id: str,
    expected_user_id: str,
    trading_day: str,
) -> Dict[str, Any]:
    order_rows = []
    identity_tokens = set()
    for row in rows:
        status, remaining = _order_status_and_remaining(row)
        if status in _CLOSED_ORDER_STATUSES or remaining <= 0:
            continue
        identity = _order_identity(
            row,
            protocol,
            expected_broker_id=expected_broker_id,
            expected_user_id=expected_user_id,
            trading_day=trading_day,
        )
        measures: Dict[str, Any] = {}
        for field in protocol.ORDER_DECIMAL_MEASURES:
            if field not in row or row[field] is None:
                raise NativeAdapterError("native_order_field_missing")
            measures[field] = _decimal_text(row[field])
        for field in protocol.ORDER_INTEGER_MEASURES:
            measures[field] = _order_bounded_integer(row.get(field))
        for field in protocol.ORDER_TEXT_MEASURES:
            value = _order_exact_text(row, field)
            if field == "OrderStatus" and value not in _OPEN_ORDER_STATUSES:
                raise NativeAdapterError("native_order_status_unknown")
            measures[field] = value
        if measures["VolumeTotalOriginal"] != _order_bounded_integer(
            row.get("VolumeTotalOriginal")
        ) or measures["VolumeTraded"] != _order_bounded_integer(row.get("VolumeTraded")):
            raise NativeAdapterError("native_order_quantity_invalid")
        identity_token = protocol.canonical_json_bytes(identity)
        if identity_token in identity_tokens:
            raise NativeAdapterError("native_order_identity_duplicated")
        identity_tokens.add(identity_token)
        order_rows.append({"identity": identity, "measures": measures})
    order_rows.sort(key=protocol.canonical_json_bytes)
    return {"schema": protocol.ORDER_ECONOMICS_SCHEMA, "rows": order_rows}


def project_open_order_refs(rows: Iterable[Mapping[str, Any]]) -> list:
    refs = []
    seen = set()
    for row in rows:
        status, remaining = _order_status_and_remaining(row)
        if status in _CLOSED_ORDER_STATUSES or remaining <= 0:
            continue
        exchange_id = _ctp_code(row.get("ExchangeID"))
        order_sys_id = _ctp_code(row.get("OrderSysID"))
        if exchange_id and order_sys_id:
            ref = {
                "kind": "ctp_order_sys_id",
                "exchange_id": exchange_id,
                "order_sys_id": order_sys_id,
            }
        else:
            order_ref = _ctp_code(row.get("OrderRef"))
            front_id = _order_bounded_integer(row.get("FrontID"))
            session_id = _order_bounded_integer(row.get("SessionID"))
            if not order_ref or front_id <= 0 or session_id <= 0:
                raise NativeAdapterError("open_order_identity_unavailable")
            ref = {
                "kind": "ctp_front_session_order_ref",
                "front_id": front_id,
                "session_id": session_id,
                "order_ref": order_ref,
            }
        token = json.dumps(ref, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        if token in seen:
            raise NativeAdapterError("native_order_identity_duplicated")
        seen.add(token)
        refs.append((token, ref))
    return [ref for _, ref in sorted(refs)]


def _exact_position_text(row: Mapping[str, Any], field: str, *, allow_empty: bool = False) -> str:
    if field not in row:
        raise NativeAdapterError("position_field_missing")
    value = row[field]
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            raise NativeAdapterError("position_text_invalid") from None
    if (
        type(value) is not str
        or len(value) > MAX_POSITION_TEXT_CHARS
        or (not allow_empty and not value)
    ):
        raise NativeAdapterError("position_text_invalid")
    if value != value.strip() or any(unicodedata.category(char) == "Cc" for char in value):
        raise NativeAdapterError("position_text_invalid")
    return value


def _project_biz_type(row: Mapping[str, Any]) -> Dict[str, str]:
    """Keep an all-NUL CTP BizType explicitly unknown in the funds projection."""
    if "BizType" not in row:
        raise NativeAdapterError("account_economic_field_missing")
    value = row["BizType"]
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            raise NativeAdapterError("position_text_invalid") from None
    if type(value) is not str or len(value) > MAX_POSITION_TEXT_CHARS or not value:
        raise NativeAdapterError("position_text_invalid")
    if all(char == "\x00" for char in value):
        return {"state": "unknown", "reason": "nul_only"}
    if value != value.strip() or any(unicodedata.category(char) == "Cc" for char in value):
        raise NativeAdapterError("position_text_invalid")
    return {"state": "observed", "value": value}


def _decimal_text(value: Any, *, nonnegative: bool = False, integer: bool = False) -> str:
    from decimal import Decimal, InvalidOperation, localcontext

    if type(value) not in (int, float, str, Decimal):
        raise NativeAdapterError("position_decimal_type_invalid")
    if isinstance(value, bool):
        raise NativeAdapterError("position_decimal_type_invalid")
    try:
        input_text = str(value)
    except Exception:
        raise NativeAdapterError("position_decimal_invalid") from None
    if len(input_text) > MAX_POSITION_DECIMAL_INPUT_CHARS:
        raise NativeAdapterError("position_decimal_invalid")
    try:
        number = Decimal(input_text)
    except (InvalidOperation, ValueError, TypeError):
        raise NativeAdapterError("position_decimal_invalid") from None
    if not number.is_finite() or (nonnegative and number < 0):
        raise NativeAdapterError("position_decimal_invalid")
    if integer:
        with localcontext() as context:
            context.prec = 100
            if number != number.to_integral_value():
                raise NativeAdapterError("position_integer_quantity_invalid")
    if number == 0:
        return "0"
    sign, digits, exponent = number.as_tuple()
    normalized_digits = list(digits)
    while normalized_digits and normalized_digits[-1] == 0:
        normalized_digits.pop()
        exponent += 1
    if (
        len(normalized_digits) > MAX_POSITION_DECIMAL_DIGITS
        or max(0, -exponent) > MAX_POSITION_DECIMAL_SCALE
        or number.copy_abs() >= Decimal(MAX_POSITION_DECIMAL_ABS_EXCLUSIVE)
    ):
        # CTP commonly uses DBL_MAX as an unreported-value sentinel.  The
        # magnitude cap rejects it, along with unsupported numeric outliers.
        raise NativeAdapterError("position_decimal_out_of_bounds")
    canonical = Decimal((sign, tuple(normalized_digits), exponent))
    rendered = format(canonical, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _position_measure_row(
    row: Mapping[str, Any], *, expected_broker_id: str, expected_user_id: str, trading_day: str
) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for field, expected in (("BrokerID", expected_broker_id), ("InvestorID", expected_user_id)):
        if _exact_position_text(row, field) != expected:
            raise NativeAdapterError("query_row_account_mismatch")

    for field in _POSITION_DECIMAL_MEASURES:
        if field not in row:
            raise NativeAdapterError("position_measure_missing")
        integer = field in _POSITION_INTEGER_QUANTITIES
        nonnegative = field in _POSITION_INTEGER_QUANTITIES or field in {
            "LongFrozenAmount",
            "ShortFrozenAmount",
            "FrozenMargin",
            "FrozenCash",
            "FrozenCommission",
            "StrikeFrozenAmount",
        }
        result[field] = _decimal_text(row[field], nonnegative=nonnegative, integer=integer)

    for field in _POSITION_TEXT_MEASURES:
        text = _exact_position_text(row, field, allow_empty=field in {"InvestUnitID", "reserve1"})
        if field == "TradingDay" and text != trading_day:
            raise NativeAdapterError("position_trading_day_mismatch")
        result[field] = text
    return result


def project_gross_positions(
    rows: Iterable[Mapping[str, Any]],
    *,
    expected_broker_id: str,
    expected_user_id: str,
    trading_day: str,
) -> Dict[str, Any]:
    """Preserve CTP gross position dimensions and all detached economics.

    No long/short netting occurs.  Rows with equal dimensions are grouped for
    quantity totals while every normalized source row is retained, so changes
    in frozen, valuation, PnL, cost, margin, or auxiliary quantity fields stay
    visible to the baseline/final digest.
    """

    from decimal import Decimal, localcontext

    grouped: Dict[Tuple[str, str, str, str, str], Dict[str, Any]] = {}
    try:
        parsed_day = datetime.strptime(trading_day, "%Y%m%d")
    except (TypeError, ValueError):
        raise NativeAdapterError("position_session_trading_day_invalid") from None
    if parsed_day.strftime("%Y%m%d") != trading_day:
        raise NativeAdapterError("position_session_trading_day_invalid")
    for row in rows:
        values = {field: _exact_position_text(row, field) for field in _POSITION_DIMENSIONS}
        exchange = values["ExchangeID"]
        direction = values["PosiDirection"]
        hedge = values["HedgeFlag"]
        position_date = values["PositionDate"]
        if exchange not in _POSITION_EXCHANGES:
            raise NativeAdapterError("position_exchange_unknown")
        if direction not in {"1", "2", "3"}:
            raise NativeAdapterError("position_direction_unknown")
        if hedge not in {"1", "2", "3"}:
            raise NativeAdapterError("position_hedge_unknown")
        if position_date not in {"1", "2"}:
            raise NativeAdapterError("position_date_unknown")
        instrument = values["InstrumentID"]
        if not instrument:
            raise NativeAdapterError("position_instrument_missing")
        row_measures = _position_measure_row(
            row,
            expected_broker_id=expected_broker_id,
            expected_user_id=expected_user_id,
            trading_day=trading_day,
        )
        quantity = Decimal(row_measures["Position"])
        key = (exchange, instrument, direction, hedge, position_date)
        bucket = grouped.setdefault(
            key,
            {
                "exchange_id": exchange,
                "instrument_id": instrument,
                "position_direction": direction,
                "hedge_flag": hedge,
                "position_date": position_date,
                "quantity_decimal": Decimal(0),
                "rows": [],
            },
        )
        with localcontext() as context:
            context.prec = 100
            bucket["quantity_decimal"] += quantity
        bucket["rows"].append(row_measures)

    buckets = []
    for key in sorted(grouped):
        bucket = grouped[key]
        bucket["rows"].sort(
            key=lambda value: json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            )
        )
        buckets.append(
            {
                "exchange_id": bucket["exchange_id"],
                "instrument_id": bucket["instrument_id"],
                "position_direction": bucket["position_direction"],
                "hedge_flag": bucket["hedge_flag"],
                "position_date": bucket["position_date"],
                "quantity": _decimal_text(bucket["quantity_decimal"], nonnegative=True),
                "rows": bucket["rows"],
            }
        )
    return {
        "schema": _POSITION_SCHEMA,
        "dimensions": list(_POSITION_DIMENSIONS),
        "buckets": buckets,
    }


def project_funds(
    row: Mapping[str, Any],
    *,
    expected_broker_id: str,
    expected_account_id: str,
    trading_day: str,
) -> Dict[str, Any]:
    """Normalize every economic field in the pinned TradingAccountField.

    Cash/equity names are explicitly derived aliases for existing C01
    consumers; baseline/final equality uses the full dimensions/measures map.
    """

    dimensions = {
        field: (
            _project_biz_type(row)
            if field == "BizType"
            else _exact_position_text(row, field)
        )
        for field in _ACCOUNT_DIMENSIONS
    }
    if dimensions["BrokerID"] != expected_broker_id:
        raise NativeAdapterError("query_row_broker_mismatch")
    if dimensions["AccountID"] != expected_account_id:
        raise NativeAdapterError("query_row_account_mismatch")
    if dimensions["TradingDay"] != trading_day:
        raise NativeAdapterError("account_trading_day_mismatch")

    measures: Dict[str, str] = {}
    for field in _ACCOUNT_DECIMAL_MEASURES:
        if field not in row:
            raise NativeAdapterError("account_economic_field_missing")
        measures[field] = _decimal_text(
            row[field],
            nonnegative=field in _ACCOUNT_NONNEGATIVE_MEASURES,
        )
    if "SettlementID" not in row:
        raise NativeAdapterError("account_economic_field_missing")
    measures["SettlementID"] = _decimal_text(row["SettlementID"], nonnegative=True, integer=True)
    diagnostics = {alias: measures[source] for alias, source in _ACCOUNT_DIAGNOSTIC_SOURCES.items()}
    return {
        "schema": _ACCOUNT_SCHEMA,
        "dimensions": dimensions,
        "measures": measures,
        "diagnostic_field_sources": dict(_ACCOUNT_DIAGNOSTIC_SOURCES),
        "diagnostics": diagnostics,
    }


def _private_snapshot(
    protocol: Any,
    capture: C01NativeCapture,
    phase: str,
    front_id: int,
    session_id: str,
    trading_day: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    request_by_family = {}
    snapshot_queries = {}
    rows_by_family = {}
    for family in ("orders", "positions", "funds"):
        method = {
            "orders": "ReqQryOrder",
            "positions": "ReqQryInvestorPosition",
            "funds": "ReqQryTradingAccount",
        }[family]
        request = next(
            item
            for item in reversed(capture.requests)
            if item["kind"] == "query" and item["phase"] == phase and item["family"] == family
        )
        callbacks = capture.query_callbacks.get(request["request_id"], [])
        if not callbacks or callbacks[-1]["is_last"] is not True:
            raise NativeAdapterError("query_terminal_callback_missing")
        if any(not _query_callback_has_no_error(item) for item in callbacks):
            raise NativeAdapterError("query_error_id_unverified")
        snapshot_query = {
            "request": {
                "method": method,
                "request_id": request["request_id"],
                "request_generation": request["request_generation"],
                "local_sequence": request["local_sequence"],
                "issued_at_utc": request["issued_at_utc"],
                "issued_monotonic_ns": request["issued_monotonic_ns"],
                "return_code": request["return_code"],
                "sdk_query_result": request["sdk_query_result"],
            },
            "callbacks": callbacks,
        }
        snapshot_queries[family] = snapshot_query
        rows_by_family[family] = [item["row"] for item in callbacks if item["row_present"] is True]
        request_by_family[family] = request
    if len(rows_by_family["funds"]) != 1:
        raise NativeAdapterError("account_snapshot_row_count_invalid")
    expected = getattr(capture, "_credentials", {})
    for row in rows_by_family["orders"]:
        if _order_exact_text(row, "BrokerID") != expected.get("broker_id"):
            raise NativeAdapterError("query_row_broker_mismatch")
        if _order_exact_text(row, "InvestorID") != expected.get("user_id"):
            raise NativeAdapterError("query_row_investor_mismatch")
        if _order_exact_text(row, "TradingDay") != trading_day:
            raise NativeAdapterError("order_trading_day_mismatch")
    order_refs = project_open_order_refs(rows_by_family["orders"])
    order_economics = project_order_economics(
        rows_by_family["orders"],
        protocol,
        expected_broker_id=expected.get("broker_id", ""),
        expected_user_id=expected.get("user_id", ""),
        trading_day=trading_day,
    )
    positions = project_gross_positions(
        rows_by_family["positions"],
        expected_broker_id=expected.get("broker_id", ""),
        expected_user_id=expected.get("user_id", ""),
        trading_day=trading_day,
    )
    funds = project_funds(
        rows_by_family["funds"][0],
        expected_broker_id=expected.get("broker_id", ""),
        expected_account_id=expected.get("user_id", ""),
        trading_day=trading_day,
    )
    client = {
        "instance_id": capture.instance_id,
        "client_generation": capture.client_generation,
        "arrival_generation": capture.arrival_generation,
    }
    document = {
        "protocol": protocol.PROTOCOL_NAME,
        "version": protocol.PROTOCOL_VERSION,
        "case_id": "C01",
        "phase": phase,
        "account_scope_sha256": capture.account_scope_sha256,
        "credential_binding_sha256": capture.credential_binding_sha256,
        "client": client,
        "scope": {
            "front_id": front_id,
            "session_id": session_id,
            "trading_day": trading_day,
        },
        "queries": snapshot_queries,
        "projections": {
            "open_order_refs": order_refs,
            "order_economics": order_economics,
            "positions": positions,
            "funds": funds,
        },
    }
    artifact_bytes = protocol.encode_private_snapshot_artifact(document)
    if len(artifact_bytes) > MAX_PRIVATE_SNAPSHOT_BYTES:
        raise NativeAdapterError("snapshot_size_invalid")
    artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
    summary = {
        "phase": phase,
        "artifact_ref": f"snapshots/{phase}.json",
        "artifact_sha256": artifact_sha256,
        "client_instance_id": capture.instance_id,
        "client_generation": capture.client_generation,
        "arrival_generation": capture.arrival_generation,
        "session_id": session_id,
        "trading_day": trading_day,
        "queries": {
            family: {
                "request_id": request_by_family[family]["request_id"],
                "callback_count": len(snapshot_queries[family]["callbacks"]),
                "row_count": len(rows_by_family[family]),
                "first_sequence": snapshot_queries[family]["callbacks"][0]["local_sequence"],
                "terminal_sequence": snapshot_queries[family]["callbacks"][-1]["local_sequence"],
            }
            for family in ("orders", "positions", "funds")
        },
        "open_order_refs_sha256": protocol.canonical_value_sha256(order_refs),
        "order_economics_sha256": protocol.canonical_value_sha256(order_economics),
        "positions_sha256": protocol.canonical_value_sha256(positions),
        "funds_sha256": protocol.canonical_value_sha256(funds),
        "account_scope_sha256": capture.account_scope_sha256,
        "credential_binding_sha256": capture.credential_binding_sha256,
    }
    return document, {"bytes": artifact_bytes, "summary": summary}


_NATIVE_LIFECYCLE_METHOD_STAGES = (
    ("CreateFtdcTraderApi", "native_create_trader_api", "staticmethod"),
    ("RegisterSpi", "native_register_spi_attach", "instance"),
    ("SubscribePrivateTopic", "native_subscribe_private_topic", "instance"),
    ("SubscribePublicTopic", "native_subscribe_public_topic", "instance"),
    ("RegisterFront", "native_register_front", "instance"),
    ("Init", "native_api_init", "instance"),
    ("Release", "native_release", "instance"),
)


def _instrument_native_lifecycle_calls(api_class: Any, capture: C01NativeCapture) -> None:
    """Add fixed progress spans around the reviewed native lifecycle methods.

    Method descriptors are checked before any replacement.  Wrappers pass
    arguments through unchanged and return the original result.  A begin record
    is mandatory before entering native code; failed/end records are written
    only after the corresponding call has returned or raised.
    """

    if not isinstance(api_class, type) or capture is None:
        raise NativeAdapterError("native_lifecycle_instrumentation_invalid")
    namespace = vars(api_class)
    originals: Dict[str, Any] = {}
    for method_name, _stage, descriptor_kind in _NATIVE_LIFECYCLE_METHOD_STAGES:
        descriptor = namespace.get(method_name)
        if descriptor_kind == "staticmethod":
            if type(descriptor) is not staticmethod:
                raise NativeAdapterError("native_lifecycle_descriptor_invalid")
            original = descriptor.__func__
        else:
            original = descriptor
        if type(original) is not types.FunctionType:
            raise NativeAdapterError("native_lifecycle_descriptor_invalid")
        originals[method_name] = original

    def invoke_with_progress(
        stage: str, invoke: Callable[[], Any], *, best_effort: bool = False
    ) -> Any:
        # Startup entry requires durable attribution before entering native
        # code. Cleanup calls must still run if journaling has already failed;
        # C01NativeCapture latches that failure and receipt construction blocks.
        required = not best_effort
        capture.progress_event(stage, "begin", required=required)
        try:
            result = invoke()
        except BaseException:
            # Preserve the native exception object and traceback.  Diagnostic
            # failure must not replace the original SDK exception.
            try:
                capture.progress_event(stage, "failed", required=False)
            except BaseException:
                pass
            raise
        # This is intentionally outside the native-call try block.  If the
        # end journal write fails, the original native call did return.
        capture.progress_event(stage, "end", required=required)
        return result

    for method_name, stage, descriptor_kind in _NATIVE_LIFECYCLE_METHOD_STAGES:
        original = originals[method_name]
        if descriptor_kind == "staticmethod":

            def make_static_wrapper(native_method: Callable[..., Any], progress_stage: str):
                def wrapped(*args: Any, **kwargs: Any) -> Any:
                    return invoke_with_progress(
                        progress_stage, lambda: native_method(*args, **kwargs)
                    )

                return wrapped

            setattr(api_class, method_name, staticmethod(make_static_wrapper(original, stage)))
            continue

        if method_name == "RegisterSpi":

            def make_register_spi_wrapper(native_method: Callable[..., Any]):
                def wrapped(api: Any, *args: Any, **kwargs: Any) -> Any:
                    # The pinned SDK uses RegisterSpi(None) for detach.  Only
                    # this exact argument shape gets the detach stage; payload
                    # objects are never inspected, stringified, or retained.
                    is_detach = (len(args) == 1 and args[0] is None and not kwargs) or (
                        not args and set(kwargs) == {"pSpi"} and kwargs["pSpi"] is None
                    )
                    progress_stage = (
                        "native_register_spi_detach" if is_detach else "native_register_spi_attach"
                    )
                    return invoke_with_progress(
                        progress_stage,
                        lambda: native_method(api, *args, **kwargs),
                        best_effort=is_detach,
                    )

                return wrapped

            setattr(api_class, method_name, make_register_spi_wrapper(original))
            continue

        def make_instance_wrapper(native_method: Callable[..., Any], progress_stage: str):
            def wrapped(api: Any, *args: Any, **kwargs: Any) -> Any:
                return invoke_with_progress(
                    progress_stage,
                    lambda: native_method(api, *args, **kwargs),
                    best_effort=progress_stage == "native_release",
                )

            return wrapped

        setattr(api_class, method_name, make_instance_wrapper(original, stage))


_START_PRECHECK_CALLS = (
    ("module", "_check_native_module", "client_start_native_module_check"),
    ("method", "_reserve_start_generation", "client_start_generation_reserve"),
    ("method", "_require_bound_identity_locked", "client_start_identity_validate"),
    ("method", "_bound_identity_is_current", "client_start_identity_compare"),
    ("module", "_flow_dir", "client_start_flow_prepare"),
)


def _instrument_start_precheck_calls(client_module: Any, capture: C01NativeCapture) -> None:
    """Journal only the five fixed Python callables that precede TD API creation."""

    if type(client_module) is not types.ModuleType or type(capture) is not C01NativeCapture:
        raise NativeAdapterError("start_precheck_instrumentation_invalid")
    client_class = getattr(client_module, "TraderClient", None)
    if not isinstance(client_class, type):
        raise NativeAdapterError("start_precheck_descriptor_invalid")

    def wrap(original: Callable[..., Any], stage: str) -> Callable[..., Any]:
        if type(original) is not types.FunctionType:
            raise NativeAdapterError("start_precheck_descriptor_invalid")

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if capture._start_precheck_thread_id != threading.get_ident():
                return original(*args, **kwargs)
            capture.progress_event(stage, "begin")
            try:
                result = original(*args, **kwargs)
            except BaseException:
                try:
                    capture.progress_event(stage, "failed", required=False)
                except BaseException:
                    pass
                raise
            capture.progress_event(stage, "end")
            return result

        wrapped.__name__ = original.__name__
        wrapped.__qualname__ = original.__qualname__
        wrapped.__doc__ = original.__doc__
        return wrapped

    replacements = []
    for owner_kind, name, stage in _START_PRECHECK_CALLS:
        if owner_kind == "module":
            owner = client_module
            original = vars(client_module).get(name)
        else:
            owner = client_class
            original = vars(client_class).get(name)
        if type(original) is not types.FunctionType:
            raise NativeAdapterError("start_precheck_descriptor_invalid")
        replacements.append((owner, name, wrap(original, stage)))
    for owner, name, replacement in replacements:
        setattr(owner, name, replacement)


def _readonly_client_class(client_class: Any, capture: C01NativeCapture) -> type:
    """Create this profile's no-Join client variant without fabricating receipts."""

    if not isinstance(client_class, type) or type(capture) is not C01NativeCapture:
        raise NativeAdapterError("readonly_client_class_invalid")
    original = getattr(client_class, "_start_join_observer", None)
    if type(original) is not types.FunctionType:
        raise NativeAdapterError("readonly_join_observer_descriptor_invalid")

    def suppress_join_observer(self: Any, api: Any) -> bool:
        capture.progress_event("client_no_join_start_policy", "begin")
        if (
            api is not getattr(self, "_native_api", None)
            or getattr(self, "_native_init_started", None) is not True
            or getattr(self, "_thread", None) is not None
            or getattr(self, "_join_active", None) is not True
        ):
            capture.progress_event("client_no_join_start_policy", "failed", required=False)
            raise NativeAdapterError("readonly_no_join_state_invalid")
        # TraderClient.start(block=False) marks Join active immediately before
        # Init, then calls this hook instead of invoking Join. Clear only that
        # SDK bookkeeping flag after proving no observer exists; stop() then
        # follows the SDK's existing no-Join detach-and-Release branch.
        self._join_active = False
        self._c01_no_join_api = api
        capture.progress_event("client_no_join_start_policy", "end")
        return False

    return type(
        "C01ReadOnlyTraderClientV2",
        (client_class,),
        {"_start_join_observer": suppress_join_observer},
    )


def _readonly_client_start_valid(client: Any) -> bool:
    api = getattr(client, "_native_api", None)
    return (
        api is not None
        and getattr(client, "_c01_no_join_api", None) is api
        and getattr(client, "_native_init_started", None) is True
        and getattr(client, "_join_active", None) is False
        and getattr(client, "_thread", None) is None
    )


def _instrument_readonly_join_deny(api_class: Any, capture: C01NativeCapture) -> None:
    """Make any native Join call fail closed in this isolated profile child."""

    if not isinstance(api_class, type) or type(capture) is not C01NativeCapture:
        raise NativeAdapterError("readonly_join_guard_invalid")
    original = getattr(api_class, "Join", None)
    if not callable(original):
        raise NativeAdapterError("readonly_join_method_unavailable")

    def denied_join(_api: Any, *_args: Any, **_kwargs: Any) -> Any:
        capture._failure = "readonly_native_join_forbidden"
        raise _CandidateAbort()

    setattr(api_class, "Join", denied_join)


def _sdk_client_and_capture(
    site_packages: Path,
    verified_sources: Mapping[Path, str],
    credentials: Mapping[str, str],
    td_front: str,
    capture: C01NativeCapture,
) -> Tuple[Any, Any, Any]:
    # Only now, after credential digests, front binding, paths and SDK RECORD
    # bytes have been checked, does the worker import a native SDK package.
    # The fixed -I -S process has no ambient site-packages path.  The verified
    # finder serves the three pinned Python distributions; the CTP extension
    # is resolved under the verified bt_api_ctp.ctp package path.  Do not add
    # all of site-packages to sys.path, which would expose unrelated wheels.
    _require_isolated_sdk_import_path(site_packages)
    capture.progress_event("sdk_import", "begin")
    sys.meta_path.insert(0, _VerifiedSdkFinder(site_packages, verified_sources))
    ctp_dir_handle = os.add_dll_directory(str(site_packages / "bt_api_ctp" / "ctp"))
    capture._ctp_dir_handle = ctp_dir_handle
    try:
        from bt_api_ctp.ctp import client as client_module
        from bt_api_ctp.ctp.ctp_trader_api import CThostFtdcTraderApi
        from bt_api_ctp.ctp._ctp_base import is_ctp_native_loaded
    except Exception:
        ctp_dir_handle.close()
        raise NativeAdapterError("pinned_sdk_import_failed") from None
    if is_ctp_native_loaded() is not True:
        ctp_dir_handle.close()
        raise NativeAdapterError("pinned_native_extension_unavailable")
    extension_path = Path(sys.modules["bt_api_ctp.ctp._ctp"].__file__).resolve(strict=True)
    expected_native = site_packages / "bt_api_ctp" / "ctp" / "_ctp.cp311-win_amd64.pyd"
    if extension_path != expected_native:
        ctp_dir_handle.close()
        raise NativeAdapterError("pinned_native_extension_origin_mismatch")
    capture.progress_event("sdk_import", "end")

    capture._credentials = credentials
    capture.bind_snapshotter(client_module._snapshot_ctp_field)
    original_flow_dir = client_module._flow_dir
    flow_directory = Path(credentials["native_flow_directory"]).resolve(strict=True)

    def fixed_flow_dir(_prefix: str) -> str:
        # Replace the SDK's default shared %TEMP% flow location with the
        # parent-created, owner-only, single-run directory.
        return str(flow_directory) + os.sep

    client_module._flow_dir = fixed_flow_dir
    _instrument_start_precheck_calls(client_module, capture)
    ctp_base = getattr(client_module, "_ctp_base", None)
    original_public_login = getattr(ctp_base, "_submit_public_trader_user_login", None)
    if (
        getattr(client_module, "_CTP_RUNTIME_SOURCE", None) != "vendored_bt_api_py"
        or not callable(original_public_login)
        or not callable(getattr(client_module, "_is_vendored_native_trader_api", None))
    ):
        client_module._flow_dir = original_flow_dir
        ctp_dir_handle.close()
        raise NativeAdapterError("pinned_login_submit_route_unavailable")

    def record_public_login(api: Any, field: Any, request_id: Any) -> Any:
        if not isinstance(api, CThostFtdcTraderApi):
            capture._failure = "native_login_api_type_invalid"
            raise _CandidateAbort()
        return capture.native_request(
            "ReqUserLogin",
            request_id,
            lambda: original_public_login(api, field, request_id),
            native_field=field,
            credentials=credentials,
        )

    # The pinned vendored login path calls this Python ABI guard, which in
    # turn returns the actual integer from the native CTP wrapper.  Capture at
    # this boundary, and also instrument the public Python ReqUserLogin method
    # for the reviewed fallback route.  Only one route is used for any call.
    ctp_base._submit_public_trader_user_login = record_public_login
    instrumented: list = []
    for name in dir(CThostFtdcTraderApi):
        if not name.startswith("Req"):
            continue
        original = getattr(CThostFtdcTraderApi, name)
        if not callable(original):
            continue
        if name in {
            "ReqAuthenticate",
            "ReqUserLogin",
            "ReqQryOrder",
            "ReqQryInvestorPosition",
            "ReqQryTradingAccount",
        }:

            def make_allowed(
                method_name: str, native_method: Callable[..., Any]
            ) -> Callable[..., Any]:
                def wrapped(api: Any, field: Any, request_id: Any) -> Any:
                    return capture.native_request(
                        method_name,
                        request_id,
                        lambda: native_method(api, field, request_id),
                        native_field=field,
                        credentials=credentials,
                    )

                return wrapped

            setattr(CThostFtdcTraderApi, name, make_allowed(name, original))
        else:

            def make_denied(
                method_name: str, native_method: Callable[..., Any]
            ) -> Callable[..., Any]:
                def wrapped(api: Any, *args: Any, **kwargs: Any) -> Any:
                    if method_name in {"ReqOrderInsert", "ReqOrderAction"}:
                        capture.write_counters[method_name] += 1
                    capture._failure = "native_request_allowlist_violation"
                    raise _CandidateAbort()

                return wrapped

            setattr(CThostFtdcTraderApi, name, make_denied(name, original))
        instrumented.append(name)
    required_methods = {
        "ReqAuthenticate",
        "ReqUserLogin",
        "ReqQryOrder",
        "ReqQryInvestorPosition",
        "ReqQryTradingAccount",
    }
    if not required_methods.issubset(instrumented):
        client_module._flow_dir = original_flow_dir
        ctp_base._submit_public_trader_user_login = original_public_login
        ctp_dir_handle.close()
        raise NativeAdapterError("required_native_methods_missing")

    _instrument_native_lifecycle_calls(CThostFtdcTraderApi, capture)
    _instrument_readonly_join_deny(CThostFtdcTraderApi, capture)

    original_spi = client_module._TraderSpi

    class _CaptureTraderSpi(original_spi):
        def OnRspAuthenticate(self, field: Any, info: Any, request_id: Any, is_last: Any) -> Any:
            capture.response_callback("OnRspAuthenticate", request_id, info, is_last, field)
            return super().OnRspAuthenticate(field, info, request_id, is_last)

        def OnRspUserLogin(self, field: Any, info: Any, request_id: Any, is_last: Any) -> Any:
            capture.response_callback(
                "OnRspUserLogin", request_id, info, is_last, field, login_field=True
            )
            return super().OnRspUserLogin(field, info, request_id, is_last)

        def OnRspQryOrder(self, row: Any, info: Any, request_id: Any, is_last: Any) -> Any:
            capture.response_callback("OnRspQryOrder", request_id, info, is_last, row)
            return super().OnRspQryOrder(row, info, request_id, is_last)

        def OnRspQryInvestorPosition(
            self, row: Any, info: Any, request_id: Any, is_last: Any
        ) -> Any:
            capture.response_callback("OnRspQryInvestorPosition", request_id, info, is_last, row)
            return super().OnRspQryInvestorPosition(row, info, request_id, is_last)

        def OnRspQryTradingAccount(self, row: Any, info: Any, request_id: Any, is_last: Any) -> Any:
            capture.response_callback("OnRspQryTradingAccount", request_id, info, is_last, row)
            return super().OnRspQryTradingAccount(row, info, request_id, is_last)

        def OnRtnOrder(self, row: Any) -> Any:
            capture.activity_callback("OnRtnOrder")
            # Deliberately do not retain private push payloads in the SDK queue.
            return None

        def OnRtnTrade(self, row: Any) -> Any:
            capture.activity_callback("OnRtnTrade")
            return None

    client_module._TraderSpi = _CaptureTraderSpi
    readonly_client_class = _readonly_client_class(client_module.TraderClient, capture)
    capture.progress_event("client_construct", "begin")
    client = readonly_client_class(
        td_front,
        credentials["broker_id"],
        credentials["user_id"],
        credentials["password"],
        app_id=credentials["app_id"],
        auth_code=credentials["auth_code"],
        auto_settlement_confirm=False,
    )
    capture.bind_client(client)
    capture._client = client
    capture.progress_event("client_construct", "end")
    # Keep all monkeypatches in the isolated worker module lifetime; no global
    # process except this fixed child can import or construct the pinned client.
    return client, client_module, ctp_dir_handle


def _validate_private_directories(
    credentials: Mapping[str, str],
    *,
    repository_root: Path,
    private_acl: _Win32PrivateDirectory,
) -> Tuple[Path, Path, Path]:
    evidence = _check_path_chain(
        Path(credentials["evidence_directory"]), reject_repository=repository_root
    )
    native_flow = _check_path_chain(
        Path(credentials["native_flow_directory"]), reject_repository=repository_root
    )
    if (
        evidence.parent != native_flow.parent
        or evidence.name != "evidence"
        or native_flow.name != "native-flow"
    ):
        raise NativeAdapterError("private_directory_root_mismatch")
    run_root = _check_path_chain(evidence.parent, reject_repository=repository_root)
    if run_root.drive.startswith("\\\\"):
        raise NativeAdapterError("private_directory_not_local")
    try:
        children = tuple(run_root.iterdir())
    except OSError:
        raise NativeAdapterError("private_run_root_unavailable") from None
    if len(children) != 2 or {child.name for child in children} != {"evidence", "native-flow"}:
        raise NativeAdapterError("private_run_root_not_fresh")
    private_acl.verify_directory(run_root)
    private_acl.verify_directory(evidence)
    private_acl.verify_directory(native_flow)
    for path, reason in (
        (evidence, "evidence_directory_not_fresh"),
        (native_flow, "native_flow_directory_not_fresh"),
    ):
        try:
            if any(path.iterdir()):
                raise NativeAdapterError(reason)
        except OSError:
            raise NativeAdapterError("private_directory_unavailable") from None
    snapshot_dir = evidence / "snapshots"
    return evidence, native_flow, snapshot_dir


def _query_callback_has_no_error(callback: Mapping[str, Any]) -> bool:
    present = callback.get("rsp_info_present")
    error_id = callback.get("error_id")
    semantic = callback.get("error_semantics")
    if present is True:
        return type(error_id) is int and error_id == 0 and semantic == RSP_INFO_ERROR_ID_PRESENT
    return present is False and error_id is None and semantic == RSP_INFO_ABSENT


def _query_result_summary(
    family: str,
    result: Any,
    request_id: int,
    arrival_generation: int,
    request_return_code: int,
    *,
    protocol: Any,
    query_module: Any,
    client: Any,
    expected_broker_id: str,
    expected_user_id: str,
    expected_trading_day: str,
    callback_rows: list,
) -> Dict[str, Any]:
    result_type = type(result)
    if result_type.__module__ != "bt_api_ctp.query" or result_type.__name__ != "QueryResult":
        raise NativeAdapterError("native_query_result_type_unverified")
    expected_request_type = {"orders": "orders", "positions": "positions", "funds": "account"}[
        family
    ]
    request_type = getattr(result, "request_type", None)
    result_request_id = getattr(result, "request_id", None)
    result_generation = getattr(result, "connection_generation", None)
    complete = getattr(result, "complete", None)
    is_last_seen = getattr(result, "is_last_seen", None)
    timed_out = getattr(result, "timed_out", None)
    unsupported = getattr(result, "unsupported", None)
    error_code = getattr(result, "error_code", "sdk_query_error_code_missing")
    submit_code = getattr(result, "submit_code", None)
    records = getattr(result, "records", None)
    late_callback_count = getattr(result, "late_callback_count", None)
    account_fingerprint = getattr(result, "account_fingerprint", None)
    started_at_utc = getattr(result, "started_at_utc", None)
    completed_at_utc = getattr(result, "completed_at_utc", None)
    error_message = getattr(result, "error_message", None)
    evidence_complete = getattr(result, "evidence_complete", None)
    source = getattr(result, "query_source", None)
    if (
        request_type != expected_request_type
        or type(result_request_id) is not int
        or result_request_id != request_id
        or type(result_generation) is not int
        or result_generation != arrival_generation
        or complete is not True
        or is_last_seen is not True
        or timed_out is not False
        or unsupported is not False
        or error_code is not None
        or type(submit_code) is not int
        or submit_code != 0
        or type(request_return_code) is not int
        or request_return_code != 0
        or type(records) is not tuple
        or type(late_callback_count) is not int
        or late_callback_count != 0
        or type(account_fingerprint) is not str
        or not account_fingerprint
        or len(account_fingerprint) > 256
        or any(ord(char) < 32 or ord(char) == 127 for char in account_fingerprint)
        or type(started_at_utc) is not datetime
        or type(completed_at_utc) is not datetime
        or started_at_utc.tzinfo is None
        or completed_at_utc.tzinfo is None
        or started_at_utc.utcoffset() != timezone.utc.utcoffset(started_at_utc)
        or completed_at_utc.utcoffset() != timezone.utc.utcoffset(completed_at_utc)
        or completed_at_utc < started_at_utc
        or error_message != ""
        or evidence_complete is not True
    ):
        raise NativeAdapterError("native_query_incomplete")
    if (
        type(query_module) is not types.ModuleType
        or query_module.__name__ != "bt_api_ctp.query"
        or type(source).__module__ != "bt_api_ctp.query"
        or type(source).__name__ != "_QuerySource"
        or getattr(source, "_seal", None) is not getattr(query_module, "_QUERY_SOURCE_SEAL", None)
        or getattr(source, "issuer", None) is not getattr(client, "_query_evidence_issuer", None)
    ):
        raise NativeAdapterError("native_query_provenance_unverified")

    source_request_type = getattr(source, "request_type", None)
    source_request_id = getattr(source, "request_id", None)
    source_account_fingerprint = getattr(source, "account_fingerprint", None)
    source_generation = getattr(source, "connection_generation", None)
    source_trading_day = getattr(source, "trading_day", None)
    source_broker_id = getattr(source, "broker_id", None)
    source_investor_id = getattr(source, "investor_id", None)
    source_filters = getattr(source, "request_filters", None)
    source_explicit_filters = getattr(source, "explicit_request_filters", None)
    source_started_at = getattr(source, "started_at_utc", None)
    source_completed_at = getattr(source, "completed_at_utc", None)
    source_started_monotonic = getattr(source, "started_monotonic", None)
    source_completed_monotonic = getattr(source, "completed_monotonic", None)
    source_clock_domain = getattr(source, "clock_domain_id", None)
    source_records_sha256 = getattr(source, "records_sha256", None)
    source_trusted_expires_at = getattr(source, "trusted_expires_at_utc", None)
    source_trusted_expires_monotonic = getattr(source, "trusted_expires_monotonic", None)
    expected_filter_names = (
        ("BrokerID", "ExchangeID", "InstrumentID", "InvestorID", "OrderSysID")
        if family == "orders"
        else ("BrokerID", "InvestorID")
    )
    source_filters_valid = type(source_filters) is tuple and all(
        type(item) is tuple and len(item) == 2 and type(item[0]) is str and type(item[1]) is str
        for item in source_filters
    )
    source_filter_map = dict(source_filters) if source_filters_valid else {}
    if (
        source_request_type != expected_request_type
        or type(source_request_id) is not int
        or source_request_id != request_id
        or source_account_fingerprint != account_fingerprint
        or type(source_generation) is not int
        or source_generation != arrival_generation
        or source_trading_day != expected_trading_day
        or source_broker_id != expected_broker_id
        or source_investor_id != expected_user_id
        or not source_filters_valid
        or tuple(name for name, _ in source_filters) != expected_filter_names
        or source_filter_map.get("BrokerID") != expected_broker_id
        or source_filter_map.get("InvestorID") != expected_user_id
        or any(
            source_filter_map.get(name) != ""
            for name in ("ExchangeID", "InstrumentID", "OrderSysID")
            if name in source_filter_map
        )
        or type(source_explicit_filters) is not tuple
        or source_explicit_filters != ()
        or source_started_at != started_at_utc
        or source_completed_at != completed_at_utc
        or type(source_started_monotonic) is not float
        or type(source_completed_monotonic) is not float
        or not math.isfinite(source_started_monotonic)
        or not math.isfinite(source_completed_monotonic)
        or source_started_monotonic <= 0
        or source_started_monotonic >= source_completed_monotonic
        or source_clock_domain != "python.time.monotonic"
        or type(source_records_sha256) is not str
        or not _SHA256_RE.fullmatch(source_records_sha256)
        or type(source_trusted_expires_at) is not datetime
        or type(source_trusted_expires_monotonic) is not float
        or source_trusted_expires_at
        != completed_at_utc + timedelta(seconds=protocol.SDK_QUERY_EVIDENCE_MAX_TTL_SECONDS)
        or source_trusted_expires_monotonic
        != source_completed_monotonic + protocol.SDK_QUERY_EVIDENCE_MAX_TTL_SECONDS
    ):
        raise NativeAdapterError("native_query_provenance_binding_invalid")

    try:
        detached_records = [_json_safe(record) for record in records]
        record_digest = protocol.canonical_sdk_query_records_sha256(detached_records)
        callback_records_digest = protocol.canonical_sdk_query_records_sha256(callback_rows)
    except Exception:
        raise NativeAdapterError("native_query_records_unverifiable") from None
    if detached_records != callback_rows or record_digest != source_records_sha256:
        raise NativeAdapterError("native_query_records_callback_mismatch")

    result_started_at = started_at_utc.isoformat()
    result_completed_at = completed_at_utc.isoformat()
    trusted_expires_at = source_trusted_expires_at.isoformat()
    source_summary = {
        "source_type": "bt_api_ctp.query._QuerySource",
        "seal_valid": True,
        "issuer_is_client_query_lane": True,
        "request_type": source_request_type,
        "request_id": source_request_id,
        "account_fingerprint": source_account_fingerprint,
        "connection_generation": source_generation,
        "trading_day": source_trading_day,
        "broker_id": source_broker_id,
        "investor_id": source_investor_id,
        "request_filters": [[name, value] for name, value in source_filters],
        "explicit_request_filters": list(source_explicit_filters),
        "started_at_utc": source_started_at.isoformat(),
        "completed_at_utc": source_completed_at.isoformat(),
        "started_monotonic_hex": source_started_monotonic.hex(),
        "completed_monotonic_hex": source_completed_monotonic.hex(),
        "clock_domain_id": source_clock_domain,
        "records_sha256": source_records_sha256,
        "trusted_expires_at_utc": trusted_expires_at,
        "trusted_expires_monotonic_hex": source_trusted_expires_monotonic.hex(),
    }
    return {
        "result_type": "bt_api_ctp.query.QueryResult",
        "request_type": request_type,
        "request_id": result_request_id,
        "connection_generation": result_generation,
        "complete": True,
        "evidence_complete": True,
        "is_last_seen": True,
        "timed_out": False,
        "unsupported": False,
        "error_code": None,
        "account_fingerprint": account_fingerprint,
        "started_at_utc": result_started_at,
        "completed_at_utc": result_completed_at,
        "error_message": "",
        "submit_code": submit_code,
        "record_count": len(records),
        "late_callback_count": late_callback_count,
        "error_semantics": protocol.SDK_QUERY_NULL_ERROR_CODE_NO_FAILURE,
        "records_sha256": record_digest,
        "callback_records_sha256": callback_records_digest,
        "query_source": source_summary,
    }


def _query_phase(client: Any, capture: C01NativeCapture, phase: str, protocol: Any) -> None:
    capture.set_phase(phase)
    query_methods = (
        ("orders", client.query_orders_result),
        ("positions", client.query_positions_result),
        ("funds", client.query_account_result),
    )
    for family, method in query_methods:
        stage = "{}_{}_read".format(phase, family)
        capture.progress_event(stage, "begin")
        result = method(timeout=QUERY_TIMEOUT_SECONDS)
        capture.progress_event(stage, "end")
        request_id = _as_native_int(getattr(result, "request_id", None))
        if request_id is None or request_id not in capture.requests_by_id:
            raise NativeAdapterError("native_query_request_missing")
        request = capture.requests_by_id[request_id]
        if request["return_code"] != 0:
            raise NativeAdapterError("native_query_return_code_unverified")
        callbacks = capture.query_callbacks.get(request_id, [])
        if not callbacks or callbacks[-1]["is_last"] is not True:
            raise NativeAdapterError("native_query_terminal_callback_missing")
        if any(not _query_callback_has_no_error(item) for item in callbacks):
            raise NativeAdapterError("native_query_error_id_unverified")
        callback_rows = [item["row"] for item in callbacks if item["row_present"] is True]
        query_module = sys.modules.get("bt_api_ctp.query")
        request["sdk_query_result"] = _query_result_summary(
            family,
            result,
            request_id,
            capture.arrival_generation,
            request["return_code"],
            protocol=protocol,
            query_module=query_module,
            client=client,
            expected_broker_id=capture._credentials["broker_id"],
            expected_user_id=capture._credentials["user_id"],
            expected_trading_day=capture._login_trading_day,
            callback_rows=callback_rows,
        )


def _stop_client_with_progress(
    client: Any, capture: Optional[C01NativeCapture]
) -> Tuple[Any, Optional[str]]:
    """Attempt native stop even when a progress write already failed."""

    if client is None:
        return None, None
    if capture is not None:
        capture.progress_event("native_stop", "begin", required=False)
    try:
        native_close = client.stop_and_wait(timeout=STOP_TIMEOUT_SECONDS)
    except Exception:
        if capture is not None:
            capture.progress_event("native_stop", "failed", required=False)
        return None, "native_stop_and_wait_failed"
    if capture is not None:
        capture.progress_event("native_stop", "end", required=False)
    return native_close, None


def _build_worker_receipt(
    protocol: Any,
    launch: Any,
    credentials: Mapping[str, str],
    capture: C01NativeCapture,
    client: Any,
    snapshots: list,
    native_close: Any,
) -> Dict[str, Any]:
    front_id, session_id, trading_day = capture.login_facts()
    if len(capture.requests) != len(_REQUEST_PLAN):
        raise NativeAdapterError("native_request_plan_incomplete")
    if any(request["return_code"] != 0 for request in capture.requests):
        raise NativeAdapterError("native_request_return_code_unverified")
    if capture._failure is not None:
        raise NativeAdapterError("native_capture_incomplete")
    if getattr(native_close, "complete", False) is not True:
        raise NativeAdapterError("native_close_incomplete")
    if (
        type(native_close).__module__ != "bt_api_ctp.ctp.client"
        or type(native_close).__name__ != "CtpNativeStopReceipt"
        or native_close.join_required is not False
        or native_close.join_completed is not True
        or native_close.native_released is not True
        or native_close.thread_alive is not False
        or native_close.timed_out is not False
        or getattr(client, "_native_api", None) is not None
        or getattr(client, "_thread", None) is not None
        or getattr(client, "_join_active", None) is not False
        or getattr(client, "_native_init_started", None) is not False
        or getattr(client, "_last_stop_join_required", None) is not False
        or getattr(client, "_last_stop_native_released", None) is not True
        or getattr(client, "_c01_no_join_api", None)
        is not getattr(client, "_last_stopped_native_api", None)
    ):
        raise NativeAdapterError("native_no_join_release_unverified")
    if len(snapshots) != 2:
        raise NativeAdapterError("native_snapshots_incomplete")
    pair_ref = launch.pair_binding.to_receipt_ref().to_dict()
    callbacks = sorted(capture.callbacks, key=lambda item: item["local_sequence"])
    payload = {
        "protocol": protocol.PROTOCOL_NAME,
        "message_type": protocol.WORKER_MESSAGE,
        "version": protocol.PROTOCOL_VERSION,
        "case_id": "C01",
        "run_nonce": launch.run_nonce,
        "parent_pid": launch.parent_pid,
        "worker_pid": os.getpid(),
        "worker_source_sha256": getattr(
            sys.modules.get("__main__"), "__c01_verified_worker_source_sha256__", None
        ),
        "pair_binding": pair_ref,
        "account_scope_sha256": launch.account_scope_sha256,
        "credential_binding_sha256": launch.credential_binding_sha256,
        "client": {
            "instance_id": capture.instance_id,
            "client_generation": capture.client_generation,
            "arrival_generation": capture.arrival_generation,
        },
        "requests": capture.requests,
        "callbacks": callbacks,
        "snapshots": [snapshot["summary"] for snapshot in snapshots],
        "write_counters": dict(capture.write_counters),
        "native_close": {
            "receipt_type": "CtpNativeStopReceipt",
            "lifecycle_mode": "NO_JOIN_RELEASE_RETURNED",
            "join_required": native_close.join_required,
            "join_completed": native_close.join_completed,
            "native_released": native_close.native_released,
            "thread_alive": native_close.thread_alive,
            "timed_out": native_close.timed_out,
        },
        "terminal_state": "normal",
    }
    expected_worker_sha = getattr(
        sys.modules.get("__main__"), "__c01_verified_worker_source_sha256__", None
    )
    if type(expected_worker_sha) is not str or not _SHA256_RE.fullmatch(expected_worker_sha):
        raise NativeAdapterError("verified_worker_source_hash_missing")
    payload["worker_source_sha256"] = expected_worker_sha
    return payload


def _failure_code(exc: Exception, capture: Optional[C01NativeCapture]) -> str:
    candidate = getattr(capture, "_failure", None) if capture is not None else None
    if not isinstance(candidate, str) or not re.fullmatch(r"[a-z0-9_]{1,64}", candidate):
        candidate = str(exc) if isinstance(exc, NativeAdapterError) else "worker_failure"
    if not re.fullmatch(r"[a-z0-9_]{1,64}", candidate):
        return "worker_failure"
    return candidate


def _failure_diagnostic_bytes(
    *,
    failure_code: str,
    launch: Any,
    capture: Optional[C01NativeCapture],
    native_close: Any,
    native_close_error_code: Optional[str],
    client_module: Any,
    snapshots: list,
) -> bytes:
    receipt_type = getattr(client_module, "CtpNativeStopReceipt", None)
    close_facts = None
    if native_close is not None and receipt_type is not None and type(native_close) is receipt_type:
        close_facts = {
            "receipt_type": "CtpNativeStopReceipt",
            "join_required": native_close.join_required,
            "join_completed": native_close.join_completed,
            "native_released": native_close.native_released,
            "thread_alive": native_close.thread_alive,
            "timed_out": native_close.timed_out,
        }

    query_facts = []
    if capture is not None:
        for request_id in sorted(capture.query_callbacks):
            request = capture.requests_by_id.get(request_id)
            query_facts.append(
                {
                    "request_id": request_id,
                    "phase": request.get("phase") if request is not None else None,
                    "family": request.get("family") if request is not None else None,
                    "callbacks": capture.query_callbacks[request_id],
                }
            )
    payload = {
        "protocol": "iteration41.simnow-c01-private-failure.v1",
        "case_id": "C01",
        "failure_code": failure_code,
        "worker_source_sha256": _load_worker_hash(),
        "run_nonce": getattr(launch, "run_nonce", None),
        "parent_pid": getattr(launch, "parent_pid", None),
        "worker_pid": os.getpid(),
        "pair_binding": (
            launch.pair_binding.to_receipt_ref().to_dict() if launch is not None else None
        ),
        "account_scope_sha256": getattr(launch, "account_scope_sha256", None),
        "credential_binding_sha256": getattr(launch, "credential_binding_sha256", None),
        "client": (
            {
                "instance_id": capture.instance_id,
                "client_generation": capture.client_generation,
                "arrival_generation": capture.arrival_generation,
            }
            if capture is not None
            else None
        ),
        "requests": capture.requests if capture is not None else [],
        "callbacks": capture.callbacks if capture is not None else [],
        "private_auth_login_callback_rows": (
            capture.private_callback_rows if capture is not None else []
        ),
        "query_callbacks": query_facts,
        "snapshots": [item["summary"] for item in snapshots if isinstance(item, dict)],
        "write_counters": dict(capture.write_counters) if capture is not None else None,
        "native_close": close_facts,
        "native_close_error_code": native_close_error_code,
    }
    try:
        encoded = (
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
    except Exception:
        raise NativeAdapterError("failure_diagnostic_encoding_failed") from None
    if len(encoded) > MAX_PRIVATE_SNAPSHOT_BYTES:
        raise NativeAdapterError("failure_diagnostic_size_invalid")
    return encoded


def _persist_failure_diagnostic(
    *,
    private_acl: Any,
    evidence_dir: Path,
    failure_code: str,
    launch: Any,
    capture: Optional[C01NativeCapture],
    native_close: Any,
    native_close_error_code: Optional[str],
    client_module: Any,
    snapshots: list,
) -> str:
    private_acl.verify_directory(evidence_dir)
    diagnostic = _failure_diagnostic_bytes(
        failure_code=failure_code,
        launch=launch,
        capture=capture,
        native_close=native_close,
        native_close_error_code=native_close_error_code,
        client_module=client_module,
        snapshots=snapshots,
    )
    return private_acl.write_json_new(evidence_dir / "failure.json", diagnostic)


def run_from_streams(
    stdin: Any,
    stdout: Any,
    *,
    protocol: Any = None,
    stage_intent_fd: Optional[int] = None,
) -> int:
    """Read one framed parent packet and write one receipt only on full proof."""
    if stage_intent_fd is not None and (type(stage_intent_fd) is not int or stage_intent_fd < 0):
        return 2
    protocol = protocol or _load_protocol_from_worker_path()
    interpreter_binding = _load_interpreter_binding_from_worker_path()
    if interpreter_binding.verify_current_runtime() is not True:
        return 2
    packet = stdin.read(protocol.MAX_LAUNCH_FRAME_BYTES + 1)
    if type(packet) is not bytes or len(packet) > protocol.MAX_LAUNCH_FRAME_BYTES:
        return 2
    launch = None
    credentials = None
    private_acl = None
    evidence_dir = None
    capture = None
    progress_recorder = None
    client = None
    client_module = None
    native_close = None
    native_close_error_code = None
    snapshots = []
    stage_intent_writer = None
    try:
        launch = protocol.parse_launch_frame(packet)
        credentials = _decode_private_input(protocol, launch)
        td_front = _validate_td_front(launch, protocol)
        worker_source_sha256 = _load_worker_hash()
        if worker_source_sha256 != launch.expected_worker_source_sha256:
            return 2
        if stage_intent_fd is not None:
            stage_intent_writer = _C01StageIntentWriter(
                stage_intent_fd, launch, worker_source_sha256
            )
        private_acl = _Win32PrivateDirectory()
        repository_root = Path(__file__).resolve(strict=True).parents[1]
        evidence_dir, native_flow_dir, snapshot_dir = _validate_private_directories(
            credentials,
            repository_root=repository_root,
            private_acl=private_acl,
        )
        progress_recorder = _C01ProgressRecorder(
            private_acl,
            evidence_dir,
            launch,
            worker_source_sha256,
            stage_intent_writer,
        )
        progress_recorder.record("worker", "begin")
        progress_recorder.record("private_paths", "end")
        progress_recorder.record("sdk_install_verify", "begin")
        site_packages, verified_sources = _verify_sdk_install(interpreter_binding)
        progress_recorder.record("sdk_install_verify", "end")
        capture = C01NativeCapture(launch.account_scope_sha256, launch.credential_binding_sha256)
        capture._credentials = credentials
        capture.bind_progress_recorder(progress_recorder)
        client = None
        client_module = None
        ctp_dir_handle = None
        native_close = None
        try:
            client, client_module, ctp_dir_handle = _sdk_client_and_capture(
                site_packages,
                verified_sources,
                credentials,
                td_front,
                capture,
            )
            # Parent supplied both paths in one owner-only private run root;
            # replace the SDK's shared TEMP flow directory before start.
            if Path(client_module._flow_dir("unused")).resolve(strict=True) != native_flow_dir:
                raise NativeAdapterError("native_flow_path_binding_mismatch")
            capture.progress_event("snapshot_directory", "begin")
            private_acl.create_child_directory(snapshot_dir)
            capture.progress_event("snapshot_directory", "end")
            capture._start_precheck_thread_id = threading.get_ident()
            try:
                capture.progress_event("client_start", "begin")
                client.start(block=False)
                if not _readonly_client_start_valid(client):
                    raise NativeAdapterError("readonly_no_join_start_unverified")
                capture.progress_event("client_start", "end")
            finally:
                capture._start_precheck_thread_id = None
            capture.progress_event("login_wait", "begin")
            login_ready = client.wait_ready(timeout=LOGIN_TIMEOUT_SECONDS)
            capture.progress_event("login_wait", "end")
            if login_ready is not True:
                raise NativeAdapterError("native_login_not_ready")
            # Authentication and login require an explicit native ErrorID 0.
            if len([c for c in capture.callbacks if c["kind"] == "authenticate"]) != 1:
                raise NativeAdapterError("authentication_callback_count_invalid")
            auth = next(c for c in capture.callbacks if c["kind"] == "authenticate")
            if (
                auth["rsp_info_present"] is not True
                or type(auth["error_id"]) is not int
                or auth["error_id"] != 0
                or auth["is_last"] is not True
            ):
                raise NativeAdapterError("authentication_error_id_unverified")
            front_id, session_id, trading_day = capture.login_facts()
            if (
                int(client._front_id) != front_id
                or str(client._session_id) != session_id
                or str(client._trading_day) != trading_day
            ):
                raise NativeAdapterError("sdk_login_scope_mismatch")
            _query_phase(client, capture, "baseline", protocol)
            capture.progress_event("baseline_snapshot_write", "begin")
            baseline_doc, baseline_artifact = _private_snapshot(
                protocol, capture, "baseline", front_id, session_id, trading_day
            )
            baseline_sha = private_acl.write_json_new(
                snapshot_dir / "baseline.json", baseline_artifact["bytes"]
            )
            if baseline_sha != baseline_artifact["summary"]["artifact_sha256"]:
                raise NativeAdapterError("baseline_artifact_hash_mismatch")
            snapshots.append(baseline_artifact)
            capture.progress_event("baseline_snapshot_write", "end")
            _query_phase(client, capture, "final", protocol)
            capture.progress_event("final_snapshot_write", "begin")
            final_doc, final_artifact = _private_snapshot(
                protocol, capture, "final", front_id, session_id, trading_day
            )
            final_sha = private_acl.write_json_new(
                snapshot_dir / "final.json", final_artifact["bytes"]
            )
            if final_sha != final_artifact["summary"]["artifact_sha256"]:
                raise NativeAdapterError("final_artifact_hash_mismatch")
            snapshots.append(final_artifact)
            capture.progress_event("final_snapshot_write", "end")
        finally:
            if client is None and capture is not None:
                client = getattr(capture, "_client", None)
            if client is not None:
                native_close, native_close_error_code = _stop_client_with_progress(client, capture)
            if ctp_dir_handle is None and capture is not None:
                ctp_dir_handle = getattr(capture, "_ctp_dir_handle", None)
            if ctp_dir_handle is not None:
                try:
                    ctp_dir_handle.close()
                except Exception:
                    pass
        if native_close is None:
            raise NativeAdapterError("native_close_unavailable")
        capture.progress_event("worker_receipt", "begin")
        receipt = _build_worker_receipt(
            protocol,
            launch,
            credentials,
            capture,
            client,
            snapshots,
            native_close,
        )
        # The parent protocol encoder rechecks the exact typed shape. No local
        # status or PASS field is emitted by this worker.
        frame = protocol.encode_worker_frame(receipt)
        if len(frame) > MAX_WORKER_FRAME_BYTES:
            raise NativeAdapterError("worker_frame_size_invalid")
        capture.progress_event("worker_receipt", "end")
        stdout.write(frame)
        stdout.flush()
        return 0
    except Exception as exc:
        # Never surface SDK exceptions, paths, private data, or raw provider
        # error text on stdout/stderr. Preserve bounded raw callback facts only
        # under the already verified owner-only evidence directory.
        if private_acl is not None and evidence_dir is not None:
            try:
                _persist_failure_diagnostic(
                    private_acl=private_acl,
                    evidence_dir=evidence_dir,
                    failure_code=_failure_code(exc, capture),
                    launch=launch,
                    capture=capture,
                    native_close=native_close,
                    native_close_error_code=native_close_error_code,
                    client_module=client_module,
                    snapshots=snapshots,
                )
            except Exception:
                pass
        return 2


def _load_worker_hash() -> str:
    value = getattr(sys.modules.get("__main__"), "__c01_verified_worker_source_sha256__", None)
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        raise NativeAdapterError("verified_worker_source_hash_missing")
    return value


def main_from_stdin() -> int:
    """In-memory supervisor entrypoint: one request in, one receipt or exit."""
    main_module = sys.modules.get("__main__")
    if getattr(main_module, "__c01_verified_worker_source_sha256__", None) is None:
        return 2
    stage_intents_enabled = getattr(main_module, "__c01_progress_intents_enabled__", False)
    if type(stage_intents_enabled) is not bool:
        return 2
    try:
        # Keep this child-local: the source hash marker is set only by the
        # fixed supervisor bootstrap after its Job assignment. Install before
        # any SDK/dependency import or client factory work can begin.
        _install_process_start_audit_guard()
    except BaseException:
        return 2
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    stdout_buffer = getattr(original_stdout, "buffer", None)
    stdin_buffer = getattr(sys.stdin, "buffer", None)
    if stdout_buffer is None or stdin_buffer is None:
        return 2
    saved_descriptors = []
    null_descriptor = None
    stage_intent_fd = None
    output_buffer = io.BytesIO()
    result = 2
    try:
        original_stdout.flush()
        original_stderr.flush()
        if stage_intents_enabled:
            # Keep one duplicate of the parent's bounded stderr pipe for fixed
            # diagnostic frames while fd 2 itself is redirected to null.
            stage_intent_fd = os.dup(original_stderr.fileno())
            os.set_inheritable(stage_intent_fd, False)
        null_descriptor = os.open(os.devnull, os.O_WRONLY)
        for stream in (original_stdout, original_stderr):
            descriptor = stream.fileno()
            saved = os.dup(descriptor)
            saved_descriptors.append((descriptor, saved))
            os.dup2(null_descriptor, descriptor)
        sys.stdout = _NullTextIO()
        sys.stderr = _NullTextIO()
        # `-B` prevents writes, the verified source loader avoids SDK pyc, and
        # OS-level redirection also discards any native C stdout/stderr bytes.
        # Hold the sole receipt in memory until native shutdown has completed.
        result = run_from_streams(
            stdin_buffer,
            output_buffer,
            stage_intent_fd=stage_intent_fd,
        )
    except Exception:
        result = 2
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        for descriptor, saved in reversed(saved_descriptors):
            try:
                os.dup2(saved, descriptor)
            except Exception:
                result = 2
            try:
                os.close(saved)
            except OSError:
                result = 2
        if stage_intent_fd is not None:
            try:
                os.close(stage_intent_fd)
            except OSError:
                result = 2
        if null_descriptor is not None:
            try:
                os.close(null_descriptor)
            except OSError:
                result = 2
    if result != 0:
        return result
    frame = output_buffer.getvalue()
    if not frame or len(frame) > MAX_WORKER_FRAME_BYTES:
        return 2
    try:
        stdout_buffer.write(frame)
        stdout_buffer.flush()
        return 0
    except Exception:
        return 2


if __name__ == "__main__":
    raise SystemExit(main_from_stdin())
