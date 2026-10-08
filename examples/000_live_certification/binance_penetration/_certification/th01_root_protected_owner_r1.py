"""Root-only protected storage primitives for the Binance TH01 owner.

The module accepts no directory, path, writer, verifier, or callback from its
caller.  A Root-owned invocation derives one new directory from the current
user's LOCALAPPDATA and binds fixed evidence, SQLite, and TradeLogger paths to
the pinned private-artifact helper.  This remains an unregistered candidate
until its source and local-storage gate have been independently accepted.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import base64
import hashlib
import hmac
import http.client
import importlib
import json
import multiprocessing
from multiprocessing.connection import wait as wait_for_connections
import os
from pathlib import Path
import re
import sqlite3
import socket
import ssl
import sys
import time
from types import MappingProxyType
from typing import Any, Iterator, Mapping
from urllib.parse import urlencode
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[4]
PRIVATE_HELPER_SHA256 = "b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd"
ROOT_READONLY_PATH = (
    ROOT
    / "examples"
    / "000_live_certification"
    / "binance_penetration"
    / "_certification"
    / "th01_root_readonly.py"
)
ROOT_READONLY_SHA256 = "2b5e055aff27a07c3d28b6499a45ebf1c7546e7a8f0710ea60feb68d2561ca0f"
ACCOUNT_COLLECTOR_PATH = (
    ROOT
    / "examples"
    / "000_live_certification"
    / "binance_penetration"
    / "_certification"
    / "th01_account_window_collector_r1.py"
)
ACCOUNT_COLLECTOR_SHA256 = "af33e9870725f67a35dcbb92c01c191e8cb88bfc4a7a9938eb6409bf8b4b7cd9"
DEMO_PROBE_PATH = (
    ROOT
    / "examples"
    / "000_live_certification"
    / "binance_penetration"
    / "_certification"
    / "th01_demo_availability_probe_r1.py"
)
DEMO_PROBE_SHA256 = "8b249e3d484e4d02f973db71df428690dc24615bd685ae127781f2b94c66c70e"
MONITOR_DATABASE_NAME = "th01_monitor_outbox.sqlite"
TRADELOGGER_NAME = "monitor.log"
MAX_EVIDENCE_BYTES = 8 * 1024 * 1024
FIXED_ENDPOINT = "https://demo-fapi.binance.com"
FIXED_HOST = "demo-fapi.binance.com"
FIXED_REQUEST_TIMEOUT_SECONDS = 8.0
FIXED_RECV_WINDOW_MS = 5000
FIXED_PAGE_LIMIT = 1000
MAX_ACCOUNT_WINDOW_MS = 72 * 60 * 60 * 1000
MAX_FIXED_REQUESTS = 64
MAX_FIXED_ROWS = 5000
MAX_FIXED_BODY_BYTES = 64 * 1024 * 1024
MAX_FIXED_CAPTURE_MS = 120_000
MAX_FIXED_PAGE_BYTES = 2 * 1024 * 1024
FIXED_RESOURCE_PATHS = {
    "account_configuration": "/fapi/v1/accountConfig",
    "account_v2": "/fapi/v2/account",
    "standard_open_orders": "/fapi/v1/openOrders",
    "algo_open_orders": "/fapi/v1/openAlgoOrders",
    "all_orders_in_window": "/fapi/v1/allOrders",
    "user_trades_in_window": "/fapi/v1/userTrades",
    "income_in_window": "/fapi/v1/income",
}
_PROBE_FAILURE_STAGES = frozenset({
    "account_configuration",
    "account_v2",
    "standard_open_orders",
    "algo_open_orders",
    "all_orders_in_window",
    "user_trades_in_window",
    "income_in_window",
    "probe_validation",
})
_PROBE_FAILURE_CODE_CATEGORIES = MappingProxyType({
    "fixed_get_body_budget_reached": "capture_limit",
    "fixed_get_capture_budget_reached": "capture_limit",
    "fixed_get_page_row_limit_reached": "capture_limit",
    "fixed_get_request_budget_reached": "capture_limit",
    "fixed_get_row_budget_reached": "capture_limit",
    "fixed_get_full_page_cursor_missing": "pagination_incomplete",
    "fixed_get_page_cursor_replay": "pagination_incomplete",
    "fixed_get_pagination_budget_reached": "pagination_incomplete",
    "fixed_get_pagination_not_advancing": "pagination_incomplete",
    "fixed_get_provider_response_unproven": "provider_response_unproven",
    "fixed_get_response_incomplete": "provider_response_unproven",
    "fixed_get_transport_unavailable": "provider_response_unproven",
    "fixed_get_worker_cleanup_uncertain": "provider_response_unproven",
    "fixed_get_worker_close_uncertain": "provider_response_unproven",
    "fixed_get_worker_failed": "provider_response_unproven",
    "account_v2_nested_shape_invalid": "provider_schema_invalid",
    "account_v2_response_shape_invalid": "provider_schema_invalid",
    "provider_body_limit_or_empty": "provider_payload_invalid",
    "provider_duplicate_json_key": "provider_payload_invalid",
    "provider_json_invalid": "provider_payload_invalid",
    "provider_nonfinite_json": "provider_payload_invalid",
    "provider_response_root_shape_invalid": "provider_payload_invalid",
    "fixed_get_current_scope_invalid": "fixed_route_contract_rejected",
    "fixed_get_history_scope_invalid": "fixed_route_contract_rejected",
    "fixed_get_query_rejected": "fixed_route_contract_rejected",
    "fixed_get_resource_rejected": "fixed_route_contract_rejected",
    "fixed_get_route_rejected": "fixed_route_contract_rejected",
    "fixed_get_scope_invalid": "fixed_route_contract_rejected",
    "fixed_get_symbol_rejected": "fixed_route_contract_rejected",
    "fixed_get_symbol_required": "fixed_route_contract_rejected",
    "fixed_get_window_rejected": "fixed_route_contract_rejected",
})
_PROBE_FAILURE_CATEGORIES = frozenset(_PROBE_FAILURE_CODE_CATEGORIES.values()) | {
    "probe_blocked",
    "unexpected_failure",
}

_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_RECORD_KIND = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_ROOT_TH01_PROTECTED_WRITER_SEAL = object()
_ROOT_TH01_WAL_GUARD_SEAL = object()
_ROOT_TH01_LOG_GUARD_SEAL = object()
_ROOT_TH01_ACCOUNT_WINDOW_AUTH_SEAL = object()
_ROOT_TH01_DEMO_AVAILABILITY_RECEIPT_SEAL = object()
_ROOT_TH01_ACCOUNT_WINDOW_PAGE_SEAL = object()
_ROOT_TH01_ACCOUNT_WINDOW_READER_SEAL = object()
_ROOT_TH01_PROBE_FACTS_SEAL = object()
_ROOT_TH01_CREDENTIAL_CONTEXT_SEAL = object()
_ACTIVE_ROOT_ACCOUNT_AUTH: list[Any] = []
_ACTIVE_ROOT_FIXED_WORKERS: list[Any] = []
_ACTIVE_ROOT_PROBE_RECEIPTS: list[Any] = []


class RootTH01ProtectedOwnerBlocked(ValueError):
    """A fixed, non-sensitive failure code for the Root storage owner."""

    def __init__(self, code: str):
        if type(code) is not str or re.fullmatch(r"[a-z0-9_]{1,64}", code) is None:
            code = "th01_protected_owner_blocked"
        super().__init__(code)
        self.code = code


def _fail(code: str) -> None:
    raise RootTH01ProtectedOwnerBlocked(code)


def _private_helper() -> Any:
    try:
        root_readonly = _pinned_root_readonly_module()
        bootstrap_name = "backtrader_runtime.certification_roundtrip_r3_bootstrap"
        module_name = "backtrader_runtime.certification_roundtrip_private"
        source_key = "certification_roundtrip_private"
        bootstrap = sys.modules.get(bootstrap_name)
        bootstrap_spec = getattr(bootstrap, "__spec__", None)
        bootstrap_loader = getattr(bootstrap_spec, "loader", None)
        if (
            bootstrap is None
            or bootstrap_spec is None
            or type(bootstrap_loader) is not root_readonly._VerifiedBytesLoader
            or getattr(bootstrap_loader, "path", None)
            != root_readonly.R3_BOOTSTRAP_PATH
            or getattr(bootstrap, "__loader__", None) is not bootstrap_loader
            or getattr(bootstrap, "__file__", None)
            != "<roundtrip-r3-source:certification_roundtrip_r3_bootstrap>"
            or getattr(bootstrap, "__cached__", None) is not None
        ):
            _fail("private_artifact_helper_bootstrap_binding_invalid")
        raw_bootstrap = getattr(bootstrap_loader, "raw", None)
        if (
            type(raw_bootstrap) is not bytes
            or hashlib.sha256(raw_bootstrap).hexdigest()
            != root_readonly.R3_BOOTSTRAP_SHA256
        ):
            _fail("private_artifact_helper_bootstrap_binding_invalid")
        try:
            sources, source_digest = bootstrap.current_sources()
            finder = bootstrap._current_finder()
            source_root = bootstrap.current_source_root()
        except Exception:
            _fail("private_artifact_helper_source_closure_invalid")
        raw_helper = sources.get(source_key)
        if (
            type(finder) is not bootstrap.Finder
            or source_root != root_readonly.R3_BOOTSTRAP_PATH.parent
            or source_digest != root_readonly.R3_SOURCE_CLOSURE_SHA256
            or type(raw_helper) is not bytes
            or raw_helper != finder.sources.get(source_key)
            or raw_bootstrap != sources.get("certification_roundtrip_r3_bootstrap")
        ):
            _fail("private_artifact_helper_source_closure_invalid")
        if hashlib.sha256(raw_helper).hexdigest() != PRIVATE_HELPER_SHA256:
            _fail("private_artifact_helper_pin_mismatch")
        module = sys.modules.get(module_name)
        if module is None:
            module = importlib.import_module(module_name)
        if (
            module.__spec__ is None
            or module.__spec__.loader is not finder
            or module.__loader__ is not finder
            or module.__file__ != "<roundtrip-r3-source:certification_roundtrip_private>"
            or getattr(module, "__cached__", None) is not None
        ):
            _fail("private_artifact_helper_origin_mismatch")
        source_origin = "<roundtrip-r3-source:certification_roundtrip_private>"
        source_functions = (
            module._path,
            module.create_private_directory,
            module._Win32.__init__,
            module._Win32.current_sid,
            module._Win32.descriptor.__wrapped__,
            module._Win32.info,
            module._Win32.opened.__wrapped__,
            module._Win32.verify_acl,
            module.PrivateArtifactDirectory.verify,
            module.PrivateArtifactDirectory.prepare_child,
            module.PrivateArtifactDirectory.write_json,
            module.PrivateArtifactDirectory.write_bytes,
            module.PrivateArtifactDirectory.verify_sqlite_scope,
            module.PrivateArtifactDirectory._verified.__wrapped__,
        )
        if (
            module.PrivateArtifactDirectory.__module__ != module_name
            or any(
                getattr(function, "__globals__", None) is not module.__dict__
                or getattr(getattr(function, "__code__", None), "co_filename", None)
                != source_origin
                for function in source_functions
            )
        ):
            _fail("private_artifact_helper_origin_mismatch")
        try:
            confirmed_sources, confirmed_digest = bootstrap.current_sources()
            confirmed_finder = bootstrap._current_finder()
            confirmed_root = bootstrap.current_source_root()
        except Exception:
            _fail("private_artifact_helper_source_closure_invalid")
        if (
            confirmed_finder is not finder
            or confirmed_digest != source_digest
            or confirmed_sources.get(source_key) != raw_helper
            or confirmed_root != source_root
        ):
            _fail("private_artifact_helper_source_closure_invalid")
    except RootTH01ProtectedOwnerBlocked:
        raise
    except Exception:
        _fail("private_artifact_helper_unavailable")
    if not callable(getattr(module, "create_private_directory", None)):
        _fail("private_artifact_helper_api_missing")
    return module


def _require_writer(value: object) -> "RootTH01ProtectedWriterV1":
    if (
        type(value) is not RootTH01ProtectedWriterV1
        or value._seal is not _ROOT_TH01_PROTECTED_WRITER_SEAL
        or type(value._directory) is not _private_helper().PrivateArtifactDirectory
        or _HEX32.fullmatch(value.invocation_id) is None
        or value._directory.path.name != "bt-iteration41-th01-" + value.invocation_id
        or value.database_path != value._directory.path / MONITOR_DATABASE_NAME
        or value.monitor_log_path != value._directory.path / TRADELOGGER_NAME
    ):
        _fail("root_protected_writer_required")
    return value


@dataclass(frozen=True, repr=False)
class RootTH01ProtectedWriterV1:
    """Exact invocation-bound writer; callers cannot choose artifact paths."""

    invocation_id: str
    _directory: Any = field(repr=False, compare=False)
    database_path: Path = field(repr=False, compare=False)
    monitor_log_path: Path = field(repr=False, compare=False)
    _next_sequence: list[int] = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return "RootTH01ProtectedWriterV1(<Root-protected>)"

    @property
    def directory_path(self) -> Path:
        _require_writer(self)
        return self._directory.path

    def write_private_record(self, kind: str, document: dict[str, Any]) -> str:
        _require_writer(self)
        if (
            type(kind) is not str
            or _RECORD_KIND.fullmatch(kind) is None
            or type(document) is not dict
        ):
            _fail("private_record_shape_invalid")
        try:
            payload = json.dumps(
                document,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        except Exception:
            _fail("private_record_json_invalid")
        if len(payload) > MAX_EVIDENCE_BYTES:
            _fail("private_record_size_limit")
        self._next_sequence[0] += 1
        sequence = self._next_sequence[0]
        reference = uuid4().hex
        name = "th01-{}-{:04d}-{}.json".format(self.invocation_id, sequence, reference)
        envelope = {
            "schema": "iteration41.binance.th01.root-protected-owner.v1",
            "invocation_ref": self.invocation_id,
            "sequence": sequence,
            "record_ref": reference,
            "kind": kind,
            "document": json.loads(payload.decode("utf-8")),
        }
        try:
            # The helper returns a content digest.  It is deliberately ignored;
            # no digest of account/provider evidence enters a public receipt.
            self._directory.write_json(name, envelope)
        except Exception:
            _fail("private_record_write_failed")
        return reference

    def prepare_monitor_database(self) -> Path:
        """Validate the fixed database destination before the SDK creates it."""
        _require_writer(self)
        try:
            self._directory.verify()
            self._directory.prepare_child(MONITOR_DATABASE_NAME)
        except Exception:
            _fail("monitor_database_destination_invalid")
        return self.database_path

    def verify_monitor_database(self, *, require_wal: bool = False) -> tuple[str, ...]:
        _require_writer(self)
        if type(require_wal) is not bool:
            _fail("sqlite_scope_check_invalid")
        try:
            present = self._directory.verify_sqlite_scope(
                MONITOR_DATABASE_NAME, require_wal=require_wal
            )
        except Exception:
            _fail("monitor_database_scope_invalid")
        return tuple(present)

    def open_wal_guard(self) -> "RootTH01WALGuardV1":
        _require_writer(self)
        try:
            self._directory.verify_sqlite_scope(MONITOR_DATABASE_NAME)
            connection = sqlite3.connect(
                str(self.database_path), timeout=5.0, isolation_level=None
            )
            mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()
            sync = connection.execute("PRAGMA synchronous = FULL").fetchone()
            if mode is None or str(mode[0]).casefold() != "wal":
                connection.close()
                _fail("monitor_wal_mode_unavailable")
            if sync is None or int(sync[0]) != 2:
                connection.close()
                _fail("monitor_sqlite_sync_unverified")
            connection.execute("PRAGMA query_only = ON")
            query_only = connection.execute("PRAGMA query_only").fetchone()
            if query_only is None or int(query_only[0]) != 1:
                connection.close()
                _fail("monitor_wal_guard_not_readonly")
            connection.execute("SELECT 1").fetchone()
            self._directory.verify_sqlite_scope(
                MONITOR_DATABASE_NAME, require_wal=True
            )
        except RootTH01ProtectedOwnerBlocked:
            raise
        except Exception:
            _fail("monitor_wal_guard_open_failed")
        return RootTH01WALGuardV1(
            invocation_id=self.invocation_id,
            writer=self,
            connection=connection,
            _seal=_ROOT_TH01_WAL_GUARD_SEAL,
        )

    def close_wal_guard_after_worker_join(self, guard: object) -> tuple[str, ...]:
        _require_writer(self)
        if (
            type(guard) is not RootTH01WALGuardV1
            or guard._seal is not _ROOT_TH01_WAL_GUARD_SEAL
            or guard.writer is not self
            or guard.invocation_id != self.invocation_id
            or guard._closed
        ):
            _fail("root_wal_guard_binding_invalid")
        try:
            guard.connection.close()
            guard._closed = True
            # Once the child has joined, the database must still be a bound
            # regular file; every sidecar that remains is checked by the
            # pinned helper.  WAL/SHM may have been removed by normal SQLite
            # close/checkpoint behavior.
            present = self._directory.verify_sqlite_scope(MONITOR_DATABASE_NAME)
        except Exception:
            _fail("monitor_wal_guard_close_unverified")
        return tuple(present)

    def create_monitor_log(self) -> Path:
        """Create the exact empty TradeLogger JSON sink before observer start."""
        _require_writer(self)
        try:
            self._directory.write_bytes(TRADELOGGER_NAME, b"")
            self.verify_monitor_log()
        except Exception:
            _fail("monitor_log_destination_invalid")
        return self.monitor_log_path

    def verify_monitor_log(self) -> None:
        _require_writer(self)
        helper = _private_helper()
        try:
            # Bind the open handle and inherited owner ACL to the exact empty
            # directory created by this Root writer.  Use the pinned helper's
            # existing no-reparse, regular-file and hardlink checks.
            with self._directory._verified() as (api, sid):
                path = helper._path(self.monitor_log_path)
                with api.opened(path, directory=False) as handle:
                    api.verify_acl(handle, sid, inherited=False)
        except Exception:
            _fail("monitor_log_scope_invalid")

    @contextmanager
    def hold_monitor_log_identity(self) -> Iterator[tuple[Path, tuple[int, int]]]:
        _require_writer(self)
        helper = _private_helper()
        try:
            with self._directory._verified() as (api, sid):
                path = helper._path(self.monitor_log_path)
                with api.opened(path, directory=False) as handle:
                    api.verify_acl(handle, sid, inherited=False)
                    identity = api.info(handle, directory=False)
                    if (
                        type(identity) is not tuple
                        or len(identity) != 2
                        or any(type(part) is not int or part < 0 for part in identity)
                    ):
                        _fail("monitor_log_identity_invalid")
                    yield self.monitor_log_path, identity
                    api.verify_acl(handle, sid, inherited=False)
        except RootTH01ProtectedOwnerBlocked:
            raise
        except Exception:
            _fail("monitor_log_identity_lost")


@dataclass(repr=False)
class RootTH01WALGuardV1:
    invocation_id: str
    writer: RootTH01ProtectedWriterV1 = field(repr=False)
    connection: sqlite3.Connection = field(repr=False)
    _seal: object = field(repr=False)
    _closed: bool = field(default=False, repr=False)

    def __repr__(self) -> str:
        return "RootTH01WALGuardV1(<Root-owned-open-connection>)"


def create_root_protected_writer(invocation_id: str) -> RootTH01ProtectedWriterV1:
    """Create one protected directory using only a Root-generated invocation."""
    if type(invocation_id) is not str or _HEX32.fullmatch(invocation_id) is None:
        _fail("root_invocation_ref_invalid")
    helper = _private_helper()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if type(local_app_data) is not str or not local_app_data:
        _fail("root_local_app_data_unavailable")
    try:
        base = helper._path(Path(local_app_data))
        if not base.is_dir():
            _fail("root_local_app_data_unavailable")
        directory = helper.create_private_directory(
            base / ("bt-iteration41-th01-" + invocation_id)
        )
        writer = RootTH01ProtectedWriterV1(
            invocation_id=invocation_id,
            _directory=directory,
            database_path=directory.path / MONITOR_DATABASE_NAME,
            monitor_log_path=directory.path / TRADELOGGER_NAME,
            _next_sequence=[0],
            _seal=_ROOT_TH01_PROTECTED_WRITER_SEAL,
        )
        _require_writer(writer)
        writer.create_monitor_log()
        writer._directory.verify()
    except RootTH01ProtectedOwnerBlocked:
        raise
    except Exception:
        _fail("root_protected_writer_creation_failed")
    return writer


@dataclass(frozen=True, repr=False)
class _RootTH01AccountWindowPageV1:
    """One invocation-bound signed GET response; body remains private."""

    resource: str
    request_ref: str
    response_ref: str
    request_cursor: int | str | None
    next_cursor: int | str | None
    page_index: int
    requested_start_ms: int
    requested_end_ms: int
    request_started_at_ms: int
    response_completed_at_ms: int
    http_status: int
    transport_complete: bool
    row_limit: int
    row_count: int
    has_more: bool
    terminal_proof: str
    truncated: bool
    provider_watermark_ms: int | None
    rows: tuple[dict[str, Any], ...] = field(repr=False)
    response_body: bytes = field(repr=False)
    _private_record_ref: str = field(repr=False)
    _invocation_id: str = field(repr=False)
    _evidence_window_id: str = field(repr=False)
    _account_binding_ref: str = field(repr=False)
    _seal: object = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return "_RootTH01AccountWindowPageV1(<provider-response-private>)"


@dataclass(frozen=True, repr=False)
class _RootTH01AccountWindowAuthV1:
    """Capability created only by Root's protected bounded credential reader."""

    invocation_id: str
    evidence_window_id: str
    _account_binding_ref: str = field(repr=False)
    history_start_ms: int
    _reader: "FixedAccountWindowGetV1" = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return "_RootTH01AccountWindowAuthV1(<Root-protected>)"


@dataclass(frozen=True, repr=False)
class _RootTH01CredentialContextV1:
    """Credential authority acquired before Root imports its private writer."""

    source_digest: str = field(repr=False)
    _account_binding_ref: str = field(repr=False)
    _api_key: str = field(repr=False)
    _secret: str = field(repr=False)
    _seal: object = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return "_RootTH01CredentialContextV1(<Root-protected>)"


@dataclass(frozen=True, repr=False)
class _RootTH01DemoAvailabilityReceiptV1:
    """Short-lived Root receipt for a fixed Demo read profile."""

    invocation_id: str
    evidence_window_id: str
    _account_binding_ref: str = field(repr=False)
    endpoint: str
    profile_id: str
    collector_sha256: str
    probe_packet_sha256: str
    issued_at_ms: int = field(repr=False)
    expires_at_ms: int = field(repr=False)
    history_start_ms: int = field(repr=False)
    coverage_claims: tuple[tuple[str, bool], ...]
    request_budget: int = field(repr=False)
    row_budget: int = field(repr=False)
    body_budget_bytes: int = field(repr=False)
    capture_budget_ms: int = field(repr=False)
    _private_record_refs: tuple[str, ...] = field(repr=False)
    _seal: object = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return "_RootTH01DemoAvailabilityReceiptV1(<Root-issued-redacted>)"


@dataclass(frozen=True, repr=False)
class RootTH01DemoProbePublicV1:
    """Safe shape-probe projection; excludes account rows and provider bodies."""

    result: str
    readiness: Any = field(repr=False)
    route_results: tuple[tuple[str, bool], ...]
    account_configuration_schema: bool
    account_v2_schema: bool
    pagination_exhaustion: bool
    no_silent_truncation: bool
    all_symbol_routes_requested_without_symbol: tuple[str, ...]
    source_sha256: str
    first_failure: tuple[str, str] | None = None
    transport_diagnostic: _RootTH01TransportDiagnosticV1 | None = field(
        default=None, repr=False
    )

    def __repr__(self) -> str:
        return "RootTH01DemoProbePublicV1(<safe-readiness-only>)"

    def public_document(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "snapshot_ready": bool(self.readiness.snapshot_ready),
            "unresolved_predicates": list(self.readiness.unresolved_predicates),
            "readiness_codes": list(self.readiness.readiness_codes),
            "predicate_results": [list(item) for item in self.readiness.predicate_results],
            "external_or_informational_results": [
                list(item) for item in self.readiness.external_or_informational_results
            ],
            "route_results": [list(item) for item in self.route_results],
            "account_configuration_schema": self.account_configuration_schema,
            "account_v2_schema": self.account_v2_schema,
            "pagination_exhaustion": self.pagination_exhaustion,
            "no_silent_truncation": self.no_silent_truncation,
            "all_symbol_routes_requested_without_symbol": list(
                self.all_symbol_routes_requested_without_symbol
            ),
            "first_failure": (
                None
                if self.first_failure is None
                else {"stage": self.first_failure[0], "category": self.first_failure[1]}
            ),
            "transport_diagnostic": _fixed_get_transport_diagnostic_document(
                self.transport_diagnostic
            ),
            "source_sha256": self.source_sha256,
        }


@dataclass(frozen=True, repr=False)
class RootTH01DemoProbeOutcomeV1:
    """Internal Root result retaining its sealed reader for the same invocation."""

    auth: _RootTH01AccountWindowAuthV1 = field(repr=False)
    availability_receipt: _RootTH01DemoAvailabilityReceiptV1 = field(repr=False)
    public: RootTH01DemoProbePublicV1

    def __repr__(self) -> str:
        return "RootTH01DemoProbeOutcomeV1(<Root-owned-capability-redacted>)"


@dataclass(frozen=True, repr=False)
class _RootTH01ProbeFactsV1:
    """Sealed observations derived only from pages returned by this reader."""

    invocation_id: str
    evidence_window_id: str
    _account_binding_ref: str = field(repr=False)
    route_results: tuple[tuple[str, bool], ...]
    account_configuration_schema: bool
    account_v2_schema: bool
    pagination_exhaustion: bool
    no_silent_truncation: bool
    pages: tuple[_RootTH01AccountWindowPageV1, ...] = field(repr=False)
    _seal: object = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return "_RootTH01ProbeFactsV1(<Root-derived-observations>)"


@dataclass(frozen=True, repr=False)
class _RootTH01GetOutcomeV1:
    status: int | None
    body: bytes = field(repr=False)
    complete: bool
    reason: str | None
    actual_query: tuple[tuple[str, str], ...] = field(repr=False)
    started_at_ms: int
    completed_at_ms: int
    worker_exit_code: int
    pipe_eof: bool
    forced_shutdown: bool

    def __repr__(self) -> str:
        return "_RootTH01GetOutcomeV1(<provider-response-private>)"


_ROOT_FIXED_GET_DIAGNOSTIC_SEAL = object()
_FIXED_GET_WORKER_REASON_CATEGORIES = MappingProxyType({
    "fixed_get_deadline": "deadline",
    "fixed_get_http_rejected": "http_rejected",
    "fixed_get_query_rejected": "route_rejected",
    "fixed_get_resource_rejected": "route_rejected",
    "fixed_get_route_rejected": "route_rejected",
    "fixed_get_cursor_rejected": "route_rejected",
    "fixed_get_window_rejected": "route_rejected",
    "fixed_get_worker_input_invalid": "worker_input_invalid",
    "fixed_get_transport_unavailable": "transport_unavailable",
    "fixed_get_response_encoding": "response_encoding",
    "fixed_get_response_framing": "response_framing",
    "fixed_get_response_size": "response_size",
    "fixed_get_response_incomplete": "response_incomplete",
    "fixed_get_tls_failed": "tls_failure",
    "fixed_get_transport_failed": "transport_failure",
})
_FIXED_GET_NO_QUERY_FAILURE_REASONS = frozenset({
    "fixed_get_deadline",
    "fixed_get_query_rejected",
    "fixed_get_resource_rejected",
    "fixed_get_route_rejected",
    "fixed_get_cursor_rejected",
    "fixed_get_window_rejected",
    "fixed_get_worker_input_invalid",
    "fixed_get_transport_unavailable",
    "fixed_get_tls_failed",
    "fixed_get_transport_failed",
})
_FIXED_GET_WORKER_REASON_VALUES = frozenset(
    _FIXED_GET_WORKER_REASON_CATEGORIES.values()
) | {"none", "other"}
_FIXED_GET_HTTP_RESPONSE_VALUES = frozenset({
    "none", "expected_200", "client_rejected", "server_error", "other"
})
_FIXED_GET_COMPLETION_VALUES = frozenset({"unobserved", "complete", "incomplete"})
_FIXED_GET_FRAME_VALUES = frozenset({
    "unobserved", "received", "valid", "invalid", "multiple"
})
_FIXED_GET_PIPE_VALUES = frozenset({
    "unobserved", "no_frame", "read_error", "frame_received", "eof",
    "eof_unverified", "multiple_frames",
})
_FIXED_GET_CLEANUP_VALUES = frozenset({
    "unobserved", "clean", "forced", "nonzero_exit", "unjoined", "close_uncertain"
})


@dataclass(frozen=True, repr=False)
class _RootTH01TransportDiagnosticV1:
    """Closed safe summary of the one fixed GET worker and its response."""

    worker_reason_category: str
    http_response_category: str
    response_completion: str
    frame_status: str
    pipe_status: str
    cleanup_status: str
    _seal: object = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return "_RootTH01TransportDiagnosticV1(<closed-enum-summary>)"


def _fixed_get_http_response_category(status: Any) -> str:
    if status is None:
        return "none"
    if type(status) is not int:
        return "other"
    if status == 200:
        return "expected_200"
    if 400 <= status < 500:
        return "client_rejected"
    if 500 <= status < 600:
        return "server_error"
    return "other"


def _fixed_get_transport_diagnostic(
    *, reason: Any = None, status: Any = None, complete: Any = None,
    frame: str = "unobserved", pipe: str = "unobserved",
    cleanup: str = "unobserved",
) -> _RootTH01TransportDiagnosticV1:
    worker_reason = (
        "none" if reason is None
        else _FIXED_GET_WORKER_REASON_CATEGORIES.get(reason, "other")
        if type(reason) is str
        else "other"
    )
    if worker_reason not in _FIXED_GET_WORKER_REASON_VALUES:
        worker_reason = "other"
    completion = (
        "complete" if complete is True
        else "incomplete" if complete is False
        else "unobserved"
    )
    return _RootTH01TransportDiagnosticV1(
        worker_reason_category=worker_reason,
        http_response_category=_fixed_get_http_response_category(status),
        response_completion=completion,
        frame_status=frame if frame in _FIXED_GET_FRAME_VALUES else "unobserved",
        pipe_status=pipe if pipe in _FIXED_GET_PIPE_VALUES else "unobserved",
        cleanup_status=cleanup if cleanup in _FIXED_GET_CLEANUP_VALUES else "unobserved",
        _seal=_ROOT_FIXED_GET_DIAGNOSTIC_SEAL,
    )


def _fixed_get_outcome_diagnostic(
    outcome: _RootTH01GetOutcomeV1,
) -> _RootTH01TransportDiagnosticV1:
    if type(outcome) is not _RootTH01GetOutcomeV1:
        return _fixed_get_transport_diagnostic()
    cleanup = (
        "forced" if outcome.forced_shutdown
        else "clean" if outcome.worker_exit_code == 0
        else "nonzero_exit" if type(outcome.worker_exit_code) is int
        else "unobserved"
    )
    return _fixed_get_transport_diagnostic(
        reason=outcome.reason,
        status=outcome.status,
        complete=outcome.complete,
        frame="valid",
        pipe="eof" if outcome.pipe_eof else "eof_unverified",
        cleanup=cleanup,
    )


def _fixed_get_diagnostic_with_cleanup(
    diagnostic: Any, cleanup: str
) -> _RootTH01TransportDiagnosticV1:
    safe = _fixed_get_transport_diagnostic_document(diagnostic)
    if safe is not None:
        safe["cleanup_status"] = (
            cleanup if type(cleanup) is str and cleanup in _FIXED_GET_CLEANUP_VALUES
            else "unobserved"
        )
        return _RootTH01TransportDiagnosticV1(
            worker_reason_category=safe["worker_reason_category"],
            http_response_category=safe["http_response_category"],
            response_completion=safe["response_completion"],
            frame_status=safe["frame_status"],
            pipe_status=safe["pipe_status"],
            cleanup_status=safe["cleanup_status"],
            _seal=_ROOT_FIXED_GET_DIAGNOSTIC_SEAL,
        )
    return _fixed_get_transport_diagnostic(cleanup=cleanup)


def _fixed_get_transport_diagnostic_document(diagnostic: Any) -> dict[str, str] | None:
    if (
        type(diagnostic) is not _RootTH01TransportDiagnosticV1
        or diagnostic._seal is not _ROOT_FIXED_GET_DIAGNOSTIC_SEAL
    ):
        return None

    def value(raw: Any, allowed: frozenset[str], fallback: str) -> str:
        return raw if type(raw) is str and raw in allowed else fallback

    return {
        "worker_reason_category": value(
            diagnostic.worker_reason_category, _FIXED_GET_WORKER_REASON_VALUES, "other"
        ),
        "http_response_category": value(
            diagnostic.http_response_category, _FIXED_GET_HTTP_RESPONSE_VALUES, "other"
        ),
        "response_completion": value(
            diagnostic.response_completion, _FIXED_GET_COMPLETION_VALUES, "unobserved"
        ),
        "frame_status": value(diagnostic.frame_status, _FIXED_GET_FRAME_VALUES, "unobserved"),
        "pipe_status": value(diagnostic.pipe_status, _FIXED_GET_PIPE_VALUES, "unobserved"),
        "cleanup_status": value(
            diagnostic.cleanup_status, _FIXED_GET_CLEANUP_VALUES, "unobserved"
        ),
    }


class RootTH01AccountWindowBlocked(ValueError):
    """A fixed, non-sensitive failure code for the TH01 signed read profile."""

    def __init__(
        self, code: str, *, transport_diagnostic: _RootTH01TransportDiagnosticV1 | None = None
    ):
        if type(code) is not str or re.fullmatch(r"[a-z0-9_]{1,64}", code) is None:
            code = "account_window_blocked"
        self.code = code
        self._transport_diagnostic = (
            transport_diagnostic
            if type(transport_diagnostic) is _RootTH01TransportDiagnosticV1
            and transport_diagnostic._seal is _ROOT_FIXED_GET_DIAGNOSTIC_SEAL
            else None
        )
        super().__init__(code)


def _account_window_fail(
    code: str,
    *,
    transport_diagnostic: _RootTH01TransportDiagnosticV1 | None = None,
) -> None:
    raise RootTH01AccountWindowBlocked(code, transport_diagnostic=transport_diagnostic)


def _safe_probe_failure(stage: str, exc: BaseException) -> tuple[str, str]:
    """Project a local probe failure to closed public stage/category labels."""
    safe_stage = stage if type(stage) is str and stage in _PROBE_FAILURE_STAGES else "probe_validation"
    if type(exc) is RootTH01AccountWindowBlocked:
        code = exc.code if type(exc.code) is str else ""
        category = _PROBE_FAILURE_CODE_CATEGORIES.get(code, "probe_blocked")
    else:
        category = "unexpected_failure"
    if category not in _PROBE_FAILURE_CATEGORIES:
        category = "probe_blocked"
    return safe_stage, category


def _safe_probe_transport_diagnostic(
    exc: BaseException,
) -> _RootTH01TransportDiagnosticV1 | None:
    if type(exc) is not RootTH01AccountWindowBlocked:
        return None
    diagnostic = getattr(exc, "_transport_diagnostic", None)
    if _fixed_get_transport_diagnostic_document(diagnostic) is None:
        return None
    return diagnostic


def _fixed_request_deadline(capture_deadline: float, now_monotonic: float) -> float:
    if (
        type(capture_deadline) not in (int, float)
        or type(now_monotonic) not in (int, float)
        or capture_deadline <= now_monotonic
        or now_monotonic <= 0
    ):
        _account_window_fail("fixed_get_capture_budget_reached")
    deadline = min(capture_deadline, now_monotonic + FIXED_REQUEST_TIMEOUT_SECONDS)
    if not now_monotonic < deadline <= capture_deadline:
        _account_window_fail("fixed_get_capture_budget_reached")
    return float(deadline)


def _preflight_response_budget(
    current_body_bytes: int,
    body_size_bytes: int,
    current_rows: int,
    response_rows: int,
) -> None:
    values = (current_body_bytes, body_size_bytes, current_rows, response_rows)
    if any(type(value) is not int or value < 0 for value in values):
        _account_window_fail("fixed_get_budget_shape_invalid")
    if current_body_bytes + body_size_bytes > MAX_FIXED_BODY_BYTES:
        _account_window_fail("fixed_get_body_budget_reached")
    if current_rows + response_rows > MAX_FIXED_ROWS:
        _account_window_fail("fixed_get_row_budget_reached")


def _strict_provider_json(body: bytes) -> Any:
    if type(body) is not bytes or not body or len(body) >= MAX_FIXED_PAGE_BYTES:
        _account_window_fail("provider_body_limit_or_empty")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in items:
            if key in output:
                _account_window_fail("provider_duplicate_json_key")
            output[key] = value
        return output

    def nonfinite(_value: str) -> Any:
        _account_window_fail("provider_nonfinite_json")

    try:
        return json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=nonfinite,
        )
    except RootTH01AccountWindowBlocked:
        raise
    except Exception:
        _account_window_fail("provider_json_invalid")


def _fixed_request_path(resource: str, query: Mapping[str, Any], history_start_ms: int,
                        now_ms: int) -> tuple[str, dict[str, Any], bool]:
    if type(resource) is not str or resource not in FIXED_RESOURCE_PATHS:
        _account_window_fail("fixed_get_resource_rejected")
    if not isinstance(query, Mapping) or any(type(key) is not str for key in query):
        _account_window_fail("fixed_get_query_rejected")
    values = dict(query)
    current_keys = {
        "account_configuration": set(),
        "account_v2": set(),
        "standard_open_orders": set(),
        "algo_open_orders": set(),
    }
    history = resource not in current_keys
    if not history:
        if set(values) != current_keys[resource]:
            _account_window_fail("fixed_get_query_rejected")
        return FIXED_RESOURCE_PATHS[resource], values, False
    if resource == "all_orders_in_window":
        base = {"startTime", "endTime", "limit"}
        if set(values) not in (base, base | {"orderId"}):
            _account_window_fail("fixed_get_query_rejected")
        cursor_name = "orderId"
    elif resource == "user_trades_in_window":
        bounded_time_query = {"symbol", "startTime", "endTime", "limit"}
        id_cursor_query = {"symbol", "fromId", "limit"}
        if set(values) not in (bounded_time_query, id_cursor_query):
            _account_window_fail("fixed_get_query_rejected")
        symbol = values.get("symbol")
        if type(symbol) is not str or re.fullmatch(r"[A-Z0-9_]{1,32}", symbol) is None:
            _account_window_fail("fixed_get_query_rejected")
        cursor_name = "fromId"
    else:
        base = {"startTime", "endTime", "limit", "page"}
        if set(values) != base:
            _account_window_fail("fixed_get_query_rejected")
        cursor_name = "page"
        if type(values.get("page")) is not int or not 1 <= values["page"] <= MAX_FIXED_REQUESTS:
            _account_window_fail("fixed_get_query_rejected")
    id_cursor_page = resource == "user_trades_in_window" and "fromId" in values
    start, end = values.get("startTime"), values.get("endTime")
    if (
        (not id_cursor_page and (
            type(start) is not int
            or type(end) is not int
            or not history_start_ms <= start <= end < now_ms
            or end - start >= MAX_ACCOUNT_WINDOW_MS
        ))
        or type(values.get("limit")) is not int
        or values.get("limit") != FIXED_PAGE_LIMIT
    ):
        _account_window_fail("fixed_get_window_rejected")
    if cursor_name in values and (
        type(values[cursor_name]) is not int
        or values[cursor_name] <= 0
        or values[cursor_name] >= 2**63
    ):
        _account_window_fail("fixed_get_cursor_rejected")
    return FIXED_RESOURCE_PATHS[resource], values, True


def _root_fixed_signed_get_worker(pipe: Any, resource: str, query: dict[str, Any],
                                  api_key: str, secret: str, history_start_ms: int,
                                  deadline_monotonic: float) -> None:
    """Isolated fixed-origin GET worker. Signed material never leaves this process."""
    connection = None
    status: int | None = None
    raw = bytearray()
    complete = False
    reason: str | None = None
    actual_query: dict[str, Any] = {}
    started_ms = int(time.time() * 1000)
    completed_ms = started_ms
    try:
        path, planned, _history = _fixed_request_path(
            resource, query, history_start_ms, int(time.time() * 1000)
        )
        if (
            type(api_key) is not str
            or not api_key
            or type(secret) is not str
            or not secret
            or type(deadline_monotonic) not in (float, int)
            or not 0 < deadline_monotonic - time.monotonic()
            <= FIXED_REQUEST_TIMEOUT_SECONDS
        ):
            _account_window_fail("fixed_get_worker_input_invalid")
        deadline = float(deadline_monotonic)
        connection = http.client.HTTPSConnection(
            FIXED_HOST,
            timeout=max(0.001, deadline - time.monotonic()),
            context=ssl.create_default_context(),
        )
        connection.auto_open = 0
        connection.connect()
        if connection.sock is None:
            _account_window_fail("fixed_get_transport_unavailable")
        connection.sock.settimeout(max(0.001, deadline - time.monotonic()))
        actual_query = dict(planned)
        actual_query["recvWindow"] = FIXED_RECV_WINDOW_MS
        actual_query["timestamp"] = int(time.time() * 1000)
        encoded = urlencode(sorted(actual_query.items()))
        signature = hmac.new(
            secret.encode("ascii"), encoded.encode("ascii"), hashlib.sha256
        ).hexdigest()
        if time.monotonic() >= deadline:
            _account_window_fail("fixed_get_deadline")
        if connection.sock is not None:
            connection.sock.settimeout(deadline - time.monotonic())
        connection.request(
            "GET",
            path + "?" + encoded + "&signature=" + signature,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "X-MBX-APIKEY": api_key,
            },
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _account_window_fail("fixed_get_deadline")
        if connection.sock is not None:
            connection.sock.settimeout(remaining)
        response = connection.getresponse()
        status = response.status
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            _account_window_fail("fixed_get_response_encoding")
        if response.getheader("Transfer-Encoding") is not None:
            _account_window_fail("fixed_get_response_framing")
        length = response.getheader("Content-Length")
        if length is None or not length.isdigit() or int(length) >= MAX_FIXED_PAGE_BYTES:
            _account_window_fail("fixed_get_response_size")
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _account_window_fail("fixed_get_deadline")
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            part = response.read1(min(16384, MAX_FIXED_PAGE_BYTES - len(raw)))
            if not part:
                break
            raw.extend(part)
            if len(raw) >= MAX_FIXED_PAGE_BYTES:
                _account_window_fail("fixed_get_response_size")
        if len(raw) != int(length):
            _account_window_fail("fixed_get_response_incomplete")
        complete = True
        if status != 200:
            reason = "fixed_get_http_rejected"
    except RootTH01AccountWindowBlocked as exc:
        reason = exc.code
    except (socket.timeout, TimeoutError):
        reason = "fixed_get_deadline"
    except ssl.SSLError:
        reason = "fixed_get_tls_failed"
    except BaseException:
        reason = "fixed_get_transport_failed"
    finally:
        completed_ms = int(time.time() * 1000)
        try:
            pipe.send((status, bytes(raw), complete, reason, actual_query, started_ms, completed_ms))
        except BaseException:
            pass
        try:
            if connection is not None:
                connection.close()
        except BaseException:
            pass
        try:
            pipe.close()
        except BaseException:
            pass


def _stop_root_fixed_worker(
    worker: Any,
    *,
    force: bool,
    transport_diagnostic: _RootTH01TransportDiagnosticV1 | None = None,
) -> tuple[int, bool]:
    if worker.is_alive() and force:
        try:
            worker.terminate()
        except Exception:
            pass
    try:
        worker.join(timeout=1.0)
    except Exception:
        pass
    if worker.is_alive():
        if worker not in _ACTIVE_ROOT_FIXED_WORKERS:
            _ACTIVE_ROOT_FIXED_WORKERS.append(worker)
        _account_window_fail(
            "fixed_get_worker_cleanup_uncertain",
            transport_diagnostic=_fixed_get_diagnostic_with_cleanup(
                transport_diagnostic, "unjoined"
            ),
        )
    exit_code = worker.exitcode
    try:
        worker.close()
    except Exception:
        if worker not in _ACTIVE_ROOT_FIXED_WORKERS:
            _ACTIVE_ROOT_FIXED_WORKERS.append(worker)
        _account_window_fail(
            "fixed_get_worker_close_uncertain",
            transport_diagnostic=_fixed_get_diagnostic_with_cleanup(
                transport_diagnostic, "close_uncertain"
            ),
        )
    if worker in _ACTIVE_ROOT_FIXED_WORKERS:
        _ACTIVE_ROOT_FIXED_WORKERS.remove(worker)
    return (int(exit_code) if type(exit_code) is int else -1), bool(force)


def _run_root_fixed_signed_get(resource: str, query: dict[str, Any], api_key: str,
                               secret: str, history_start_ms: int,
                               deadline_monotonic: float) -> _RootTH01GetOutcomeV1:
    path, planned, _history = _fixed_request_path(
        resource, query, history_start_ms, int(time.time() * 1000)
    )
    if path != FIXED_RESOURCE_PATHS[resource] or any(
        forbidden in path for forbidden in ("/fapi/v1/order", "/listenKey", "/trade/asyn")
    ):
        _account_window_fail("fixed_get_route_rejected")
    if type(deadline_monotonic) not in (float, int):
        _account_window_fail("fixed_get_deadline")
    before_spawn = time.monotonic()
    remaining_seconds = float(deadline_monotonic) - before_spawn
    if not 0 < remaining_seconds <= FIXED_REQUEST_TIMEOUT_SECONDS:
        _account_window_fail("fixed_get_deadline")
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    worker = context.Process(
        target=_root_fixed_signed_get_worker,
        args=(child, resource, planned, api_key, secret, history_start_ms,
              float(deadline_monotonic)),
        name="th01-fixed-signed-read",
        daemon=True,
    )
    started_ms = int(time.time() * 1000)
    _ACTIVE_ROOT_FIXED_WORKERS.append(worker)
    worker_started = False
    frame_state = "unobserved"
    pipe_state = "unobserved"
    cleanup_state = "unobserved"

    def current_diagnostic() -> _RootTH01TransportDiagnosticV1:
        return _fixed_get_transport_diagnostic(
            frame=frame_state, pipe=pipe_state, cleanup=cleanup_state
        )

    try:
        worker.start()
        worker_started = True
        child.close()
        remaining_after_start = deadline_monotonic - time.monotonic()
        if remaining_after_start <= 0 or not parent.poll(remaining_after_start + 0.25):
            pipe_state = "no_frame"
            exit_code, forced = _stop_root_fixed_worker(
                worker, force=True, transport_diagnostic=current_diagnostic()
            )
            cleanup_state = (
                "forced" if forced
                else "clean" if exit_code == 0
                else "nonzero_exit" if type(exit_code) is int
                else "unobserved"
            )
            _account_window_fail("fixed_get_deadline", transport_diagnostic=current_diagnostic())
        try:
            frame = parent.recv()
        except (EOFError, OSError):
            pipe_state = "read_error"
            _account_window_fail(
                "fixed_get_response_pipe_invalid", transport_diagnostic=current_diagnostic()
            )
        frame_state = "received"
        pipe_state = "frame_received"
        exit_code, forced = _stop_root_fixed_worker(
            worker, force=False, transport_diagnostic=current_diagnostic()
        )
        cleanup_state = (
            "forced" if forced
            else "clean" if exit_code == 0
            else "nonzero_exit" if type(exit_code) is int
            else "unobserved"
        )
        # On Windows, Connection.poll() uses PeekNamedPipe and can raise
        # BrokenPipeError after the peer closes an exhausted one-way pipe.
        # multiprocessing.connection.wait() treats that state as readable;
        # the following recv() must still prove EOF and reject any extra frame.
        if parent not in wait_for_connections([parent], timeout=0.1):
            pipe_state = "eof_unverified"
            _account_window_fail(
                "fixed_get_response_pipe_uncertain",
                transport_diagnostic=current_diagnostic(),
            )
        try:
            parent.recv()
            frame_state = "multiple"
            pipe_state = "multiple_frames"
            _account_window_fail(
                "fixed_get_multiple_frames", transport_diagnostic=current_diagnostic()
            )
        except EOFError:
            pipe_state = "eof"
        if exit_code != 0 or forced:
            _account_window_fail(
                "fixed_get_worker_cleanup_uncertain",
                transport_diagnostic=current_diagnostic(),
            )
        if type(frame) is not tuple or len(frame) != 7:
            frame_state = "invalid"
            _account_window_fail(
                "fixed_get_frame_invalid", transport_diagnostic=current_diagnostic()
            )
        status, body, complete, reason, actual_query, worker_started_ms, completed_ms = frame
        signed_query_valid = (
            type(actual_query) is dict
            and set(actual_query) == set(planned) | {"recvWindow", "timestamp"}
            and actual_query.get("recvWindow") == FIXED_RECV_WINDOW_MS
            and type(actual_query.get("timestamp")) is int
            and type(worker_started_ms) is int
            and type(completed_ms) is int
            and worker_started_ms <= actual_query["timestamp"] <= completed_ms
        )
        pre_request_failure_valid = (
            type(actual_query) is dict
            and not actual_query
            and status is None
            and body == b""
            and complete is False
            and type(reason) is str
            and reason in _FIXED_GET_NO_QUERY_FAILURE_REASONS
        )
        if (
            (status is not None and type(status) is not int)
            or type(body) is not bytes
            or len(body) >= MAX_FIXED_PAGE_BYTES
            or type(complete) is not bool
            or (reason is not None and type(reason) is not str)
            or type(actual_query) is not dict
            or type(worker_started_ms) is not int
            or type(completed_ms) is not int
            or not 0 < worker_started_ms <= completed_ms
            or completed_ms < started_ms - 5000
            or not (signed_query_valid or pre_request_failure_valid)
        ):
            frame_state = "invalid"
            _account_window_fail(
                "fixed_get_frame_invalid",
                transport_diagnostic=_fixed_get_transport_diagnostic(
                    reason=reason,
                    status=status,
                    complete=complete,
                    frame=frame_state,
                    pipe=pipe_state,
                    cleanup=cleanup_state,
                ),
            )
        frame_state = "valid"
        return _RootTH01GetOutcomeV1(
            status=status,
            body=body,
            complete=complete,
            reason=reason,
            actual_query=tuple(sorted((key, str(value)) for key, value in actual_query.items())),
            started_at_ms=worker_started_ms,
            completed_at_ms=completed_ms,
            worker_exit_code=exit_code,
            pipe_eof=True,
            forced_shutdown=forced,
        )
    except RootTH01AccountWindowBlocked as exc:
        if worker_started and worker in _ACTIVE_ROOT_FIXED_WORKERS:
            try:
                if worker.is_alive():
                    _stop_root_fixed_worker(
                        worker,
                        force=True,
                        transport_diagnostic=exc._transport_diagnostic,
                    )
            except Exception:
                # Keep an uncertain child in the active list; do not replace
                # the original fixed, non-sensitive failure with cleanup noise.
                pass
        raise
    except Exception:
        if worker_started and worker in _ACTIVE_ROOT_FIXED_WORKERS:
            try:
                if worker.is_alive():
                    _stop_root_fixed_worker(
                        worker,
                        force=True,
                        transport_diagnostic=current_diagnostic(),
                    )
            except Exception:
                # The active-list reference keeps uncertain cleanup fail-closed.
                pass
        _account_window_fail(
            "fixed_get_worker_failed", transport_diagnostic=current_diagnostic()
        )
    finally:
        try:
            parent.close()
        except Exception:
            pass
        try:
            child.close()
        except Exception:
            pass
        if not worker_started:
            try:
                worker.close()
            except Exception:
                pass
            if worker in _ACTIVE_ROOT_FIXED_WORKERS:
                _ACTIVE_ROOT_FIXED_WORKERS.remove(worker)
        elif worker in _ACTIVE_ROOT_FIXED_WORKERS:
            try:
                _stop_root_fixed_worker(
                    worker,
                    force=worker.is_alive(),
                    transport_diagnostic=current_diagnostic(),
                )
            except Exception:
                # The active list intentionally retains a process that could
                # not be joined/closed, so a later call remains fail-closed.
                pass


def _root_account_source_module(module_name: str, expected_path: Path) -> Any:
    try:
        module = importlib.import_module(f"{__package__}.{module_name}")
        loaded = Path(module.__file__).resolve()
        expected = expected_path.resolve()
        if loaded != expected:
            _account_window_fail("source_origin_mismatch")
        info = expected.lstat()
        if expected.is_symlink() or not expected.is_file() or info.st_size > 2_000_000:
            _account_window_fail("source_shape_invalid")
    except RootTH01AccountWindowBlocked:
        raise
    except Exception:
        _account_window_fail("source_unavailable")
    return module


def _pinned_root_readonly_module():
    root_readonly = _root_account_source_module("th01_root_readonly", ROOT_READONLY_PATH)
    spec = getattr(root_readonly, "__spec__", None)
    if (
        getattr(root_readonly, "__loader__", None) is not None
        or spec is None
        or spec.loader is not None
        or getattr(root_readonly, "__cached__", None) is not None
    ):
        _account_window_fail("root_readonly_source_loader_unpinned")
    if hashlib.sha256(ROOT_READONLY_PATH.read_bytes()).hexdigest() != ROOT_READONLY_SHA256:
        _account_window_fail("root_readonly_source_pin_mismatch")
    return root_readonly


def verify_root_readonly_source_binding_for_source_qa() -> bool:
    """Run the production owner-to-reader source-pin check without credentials."""
    _pinned_root_readonly_module()
    return True


def _root_th01_credential_context(env_file: str | Path) -> _RootTH01CredentialContextV1:
    """Invoke the pinned R3 bounded reader before importing Root's writer."""
    env_path = Path(env_file)
    if env_path.resolve() != (ROOT / ".env").resolve():
        _account_window_fail("root_env_path_not_fixed")
    root_readonly = _pinned_root_readonly_module()
    factory = getattr(root_readonly, "_root_runtime_authority", None)
    if not callable(factory):
        _account_window_fail("root_bounded_reader_unavailable")
    try:
        source_digest, account_ref, api_key, secret = factory(env_path)
    except Exception:
        _account_window_fail("root_bounded_reader_failed")
    if (
        type(source_digest) is not str
        or re.fullmatch(r"[0-9a-f]{64}", source_digest) is None
        or type(account_ref) is not str
        or re.fullmatch(r"[0-9a-f]{64}", account_ref) is None
        or type(api_key) is not str
        or not api_key
        or type(secret) is not str
        or not secret
    ):
        _account_window_fail("root_bounded_reader_shape_invalid")
    return _RootTH01CredentialContextV1(
        source_digest=source_digest,
        _account_binding_ref=account_ref,
        _api_key=api_key,
        _secret=secret,
        _seal=_ROOT_TH01_CREDENTIAL_CONTEXT_SEAL,
    )


def _make_root_account_window_auth(credential_context: object, writer: object,
                                   invocation_id: str, evidence_window_id: str,
                                   history_start_ms: int) -> _RootTH01AccountWindowAuthV1:
    checked_writer = _require_writer(writer)
    if (
        type(credential_context) is not _RootTH01CredentialContextV1
        or credential_context._seal is not _ROOT_TH01_CREDENTIAL_CONTEXT_SEAL
        or type(credential_context.source_digest) is not str
        or re.fullmatch(r"[0-9a-f]{64}", credential_context.source_digest) is None
        or type(credential_context._account_binding_ref) is not str
        or re.fullmatch(r"[0-9a-f]{64}", credential_context._account_binding_ref) is None
        or type(credential_context._api_key) is not str
        or not credential_context._api_key
        or type(credential_context._secret) is not str
        or not credential_context._secret
        or checked_writer.invocation_id != invocation_id
        or type(invocation_id) is not str
        or _HEX32.fullmatch(invocation_id) is None
        or type(evidence_window_id) is not str
        or evidence_window_id != "th01-window:" + invocation_id
        or type(history_start_ms) is not int
        or history_start_ms <= 0
    ):
        _account_window_fail("root_account_window_binding_invalid")
    now_ms = int(time.time() * 1000)
    if history_start_ms >= now_ms or now_ms - history_start_ms > MAX_ACCOUNT_WINDOW_MS:
        _account_window_fail("root_history_window_invalid")
    reader = FixedAccountWindowGetV1(
        invocation_id=invocation_id,
        evidence_window_id=evidence_window_id,
        _account_binding_ref=credential_context._account_binding_ref,
        _api_key=credential_context._api_key,
        _secret=credential_context._secret,
        history_start_ms=history_start_ms,
        writer=checked_writer,
        _request_count=[0],
        _row_count=[0],
        _response_bytes=[0],
        _first_request_ms=[None],
        _last_response_ms=[None],
        _capture_deadline_monotonic=[None],
        _page_progress={},
        _private_record_refs=[],
        _seal=_ROOT_TH01_ACCOUNT_WINDOW_READER_SEAL,
    )
    auth = _RootTH01AccountWindowAuthV1(
        invocation_id=invocation_id,
        evidence_window_id=evidence_window_id,
        _account_binding_ref=credential_context._account_binding_ref,
        history_start_ms=history_start_ms,
        _reader=reader,
        _seal=_ROOT_TH01_ACCOUNT_WINDOW_AUTH_SEAL,
    )
    _ACTIVE_ROOT_ACCOUNT_AUTH.append(auth)
    return auth


def _root_parse_page_rows(body: bytes) -> tuple[dict[str, Any], ...]:
    parsed = _strict_provider_json(body)
    if type(parsed) is dict:
        return (parsed,)
    if type(parsed) is list and all(type(item) is dict for item in parsed):
        return tuple(parsed)
    _account_window_fail("provider_response_root_shape_invalid")


def _reader_progress(reader: "FixedAccountWindowGetV1", resource: str,
                     symbol: str | None, start_ms: int, end_ms: int,
                     cursor: int | str | None) -> tuple[tuple[Any, ...], int]:
    key = (resource, symbol, start_ms, end_ms)
    previous = reader._page_progress.get(key)
    if previous is None:
        if cursor is not None:
            _account_window_fail("fixed_get_initial_cursor_invalid")
        return key, 0
    expected_cursor, next_index, terminal = previous
    if terminal or cursor != expected_cursor:
        _account_window_fail("fixed_get_page_cursor_replay")
    return key, next_index


@dataclass(repr=False)
class FixedAccountWindowGetV1:
    """Sealed seven-method direct HTTPS reader; every route is a fixed GET."""

    invocation_id: str
    evidence_window_id: str
    _account_binding_ref: str = field(repr=False)
    _api_key: str = field(repr=False)
    _secret: str = field(repr=False)
    history_start_ms: int
    writer: RootTH01ProtectedWriterV1 = field(repr=False)
    _request_count: list[int] = field(repr=False)
    _row_count: list[int] = field(repr=False)
    _response_bytes: list[int] = field(repr=False)
    _first_request_ms: list[int | None] = field(repr=False)
    _last_response_ms: list[int | None] = field(repr=False)
    _capture_deadline_monotonic: list[float | None] = field(repr=False)
    _page_progress: dict[tuple[Any, ...], tuple[Any, int, bool]] = field(repr=False)
    _private_record_refs: list[str] = field(repr=False)
    _seal: object = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return "FixedAccountWindowGetV1(<Root-sealed-fixed-GET>)"

    def _require(self) -> None:
        if (
            self._seal is not _ROOT_TH01_ACCOUNT_WINDOW_READER_SEAL
            or type(self.writer) is not RootTH01ProtectedWriterV1
            or self.writer._seal is not _ROOT_TH01_PROTECTED_WRITER_SEAL
            or self.writer.invocation_id != self.invocation_id
            or self.evidence_window_id != "th01-window:" + self.invocation_id
            or _HEX32.fullmatch(self.invocation_id) is None
        ):
            _account_window_fail("fixed_reader_capability_invalid")
        _require_writer(self.writer)
        if _ACTIVE_ROOT_FIXED_WORKERS:
            _account_window_fail("fixed_get_prior_worker_unclosed")

    def _get(self, resource: str, query: dict[str, Any], *, start_ms: int,
             end_ms: int, cursor: int | str | None, symbol: str | None,
             current: bool) -> _RootTH01AccountWindowPageV1:
        self._require()
        now_ms = int(time.time() * 1000)
        path, planned, history = _fixed_request_path(
            resource, query, self.history_start_ms, now_ms
        )
        if current == history:
            _account_window_fail("fixed_get_scope_invalid")
        if current and (start_ms != 0 or end_ms != 0 or cursor is not None or symbol is not None):
            _account_window_fail("fixed_get_current_scope_invalid")
        if history:
            if resource == "user_trades_in_window" and "fromId" in planned:
                # Binance forbids fromId with startTime/endTime. Keep the
                # original evidence window in the typed page metadata, while
                # the fixed query uses only the ID cursor. The collector still
                # checks every returned row against the case cutoff and blocks
                # if this cursor-only page crosses it.
                if (
                    type(start_ms) is not int
                    or type(end_ms) is not int
                    or not self.history_start_ms <= start_ms <= end_ms < now_ms
                    or planned.get("fromId") != cursor
                    or planned.get("symbol") != symbol
                ):
                    _account_window_fail("fixed_get_history_scope_invalid")
            elif (
                start_ms != planned["startTime"]
                or end_ms != planned["endTime"]
                or not self.history_start_ms <= start_ms <= end_ms < now_ms
            ):
                _account_window_fail("fixed_get_history_scope_invalid")
        page_key, page_index = _reader_progress(
            self, resource, symbol, start_ms, end_ms, cursor
        ) if history else ((resource, symbol, start_ms, end_ms, uuid4().hex), 0)
        if self._request_count[0] >= MAX_FIXED_REQUESTS:
            _account_window_fail("fixed_get_request_budget_reached")
        request_ref, response_ref = str(uuid4()), str(uuid4())
        if request_ref == response_ref:
            _account_window_fail("fixed_get_reference_collision")
        if self._capture_deadline_monotonic[0] is None:
            self._capture_deadline_monotonic[0] = time.monotonic() + (
                MAX_FIXED_CAPTURE_MS / 1000.0
            )
        request_deadline = _fixed_request_deadline(
            self._capture_deadline_monotonic[0], time.monotonic()
        )
        outcome = _run_root_fixed_signed_get(
            resource,
            planned,
            self._api_key,
            self._secret,
            self.history_start_ms,
            request_deadline,
        )
        self._request_count[0] += 1
        if self._first_request_ms[0] is None:
            self._first_request_ms[0] = outcome.started_at_ms
        self._last_response_ms[0] = outcome.completed_at_ms
        if (
            outcome.completed_at_ms - self._first_request_ms[0] >= MAX_FIXED_CAPTURE_MS
        ):
            _account_window_fail("fixed_get_capture_budget_reached")
        _preflight_response_budget(
            self._response_bytes[0], len(outcome.body), self._row_count[0], 0
        )
        rows: tuple[dict[str, Any], ...] = ()
        effective_rows = 0
        row_limit = FIXED_PAGE_LIMIT if history else MAX_FIXED_ROWS
        if (
            outcome.status == 200
            and outcome.complete is True
            and outcome.reason is None
            and outcome.worker_exit_code == 0
            and outcome.pipe_eof is True
            and outcome.forced_shutdown is False
        ):
            rows = _root_parse_page_rows(outcome.body)
            effective_rows = len(rows)
            if len(rows) > row_limit:
                _account_window_fail("fixed_get_page_row_limit_reached")
            if resource == "account_v2":
                if len(rows) != 1:
                    _account_window_fail("account_v2_response_shape_invalid")
                row = rows[0]
                for key in ("assets", "positions"):
                    nested = row.get(key)
                    if type(nested) is not list or any(
                        type(item) is not dict for item in nested
                    ):
                        _account_window_fail("account_v2_nested_shape_invalid")
                    effective_rows += len(nested)
            _preflight_response_budget(
                self._response_bytes[0],
                len(outcome.body),
                self._row_count[0],
                effective_rows,
            )
        try:
            actual_query = dict(outcome.actual_query)
            private_ref = self.writer.write_private_record(
                "account_window_page",
                {
                    "schema": "iteration41.binance.th01.account-window-page.private.v1",
                    "invocation_ref": self.invocation_id,
                    "evidence_window_ref": self.evidence_window_id,
                    "request_ref": request_ref,
                    "response_ref": response_ref,
                    "resource": resource,
                    "method": "GET",
                    "endpoint": FIXED_ENDPOINT,
                    "path": path,
                    "unsigned_query": actual_query,
                    "request_started_at_ms": outcome.started_at_ms,
                    "response_completed_at_ms": outcome.completed_at_ms,
                    "http_status": outcome.status,
                    "transport_complete": outcome.complete,
                    "failure_code": outcome.reason,
                    "response_body_b64": base64.b64encode(outcome.body).decode("ascii"),
                },
            )
        except RootTH01ProtectedOwnerBlocked:
            raise
        except Exception:
            _account_window_fail("account_window_private_capture_failed")
        self._private_record_refs.append(private_ref)
        self._response_bytes[0] += len(outcome.body)
        if (
            outcome.status != 200
            or not outcome.complete
            or outcome.reason is not None
            or outcome.worker_exit_code != 0
            or not outcome.pipe_eof
            or outcome.forced_shutdown
        ):
            _account_window_fail(
                "fixed_get_provider_response_unproven",
                transport_diagnostic=_fixed_get_outcome_diagnostic(outcome),
            )
        self._row_count[0] += effective_rows
        next_cursor: int | str | None = None
        has_more = False
        if history and len(rows) == FIXED_PAGE_LIMIT:
            has_more = True
            if resource == "all_orders_in_window":
                ids = [item.get("orderId") for item in rows]
            elif resource == "user_trades_in_window":
                ids = [item.get("id") for item in rows]
            else:
                ids = []
            if resource in {"all_orders_in_window", "user_trades_in_window"}:
                if any(type(item) is not int or item <= 0 for item in ids):
                    _account_window_fail("fixed_get_full_page_cursor_missing")
                next_cursor = max(ids) + 1
            else:
                next_cursor = int(planned["page"]) + 1
            terminal_proof = "unknown"
        elif history:
            terminal_proof = "short_page"
        else:
            terminal_proof = "single_response"
        if history:
            self._page_progress[page_key] = (next_cursor, page_index + 1, not has_more)
        page = _RootTH01AccountWindowPageV1(
            resource=resource,
            request_ref=request_ref,
            response_ref=response_ref,
            request_cursor=cursor,
            next_cursor=next_cursor,
            page_index=page_index,
            requested_start_ms=start_ms,
            requested_end_ms=end_ms,
            request_started_at_ms=outcome.started_at_ms,
            response_completed_at_ms=outcome.completed_at_ms,
            http_status=outcome.status,
            transport_complete=outcome.complete,
            row_limit=row_limit,
            row_count=len(rows),
            has_more=has_more,
            terminal_proof=terminal_proof,
            truncated=False,
            provider_watermark_ms=None,
            rows=rows,
            response_body=outcome.body,
            _private_record_ref=private_ref,
            _invocation_id=self.invocation_id,
            _evidence_window_id=self.evidence_window_id,
            _account_binding_ref=self._account_binding_ref,
            _seal=_ROOT_TH01_ACCOUNT_WINDOW_PAGE_SEAL,
        )
        return page

    def account_configuration(self) -> _RootTH01AccountWindowPageV1:
        return self._get(
            "account_configuration", {}, start_ms=0, end_ms=0, cursor=None,
            symbol=None, current=True
        )

    def account_v2(self) -> _RootTH01AccountWindowPageV1:
        return self._get(
            "account_v2", {}, start_ms=0, end_ms=0, cursor=None, symbol=None,
            current=True
        )

    def open_orders(self) -> _RootTH01AccountWindowPageV1:
        return self._get(
            "standard_open_orders", {}, start_ms=0, end_ms=0, cursor=None,
            symbol=None, current=True
        )

    def open_algo_orders(self) -> _RootTH01AccountWindowPageV1:
        return self._get(
            "algo_open_orders", {}, start_ms=0, end_ms=0, cursor=None,
            symbol=None, current=True
        )

    def all_orders(self, start_ms: int, end_ms: int,
                   cursor: int | str | None) -> _RootTH01AccountWindowPageV1:
        query: dict[str, Any] = {
            "startTime": start_ms, "endTime": end_ms, "limit": FIXED_PAGE_LIMIT
        }
        if cursor is not None:
            query["orderId"] = cursor
        return self._get(
            "all_orders_in_window", query, start_ms=start_ms, end_ms=end_ms,
            cursor=cursor, symbol=None, current=False
        )

    def user_trades(self, symbol: str, start_ms: int, end_ms: int,
                    cursor: int | str | None) -> _RootTH01AccountWindowPageV1:
        if type(symbol) is not str or re.fullmatch(r"[A-Z0-9_]{1,32}", symbol) is None:
            _account_window_fail("fixed_get_symbol_rejected")
        if cursor is None:
            query: dict[str, Any] = {
                "symbol": symbol,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": FIXED_PAGE_LIMIT,
            }
        else:
            query = {"symbol": symbol, "fromId": cursor, "limit": FIXED_PAGE_LIMIT}
        return self._get(
            "user_trades_in_window", query, start_ms=start_ms, end_ms=end_ms,
            cursor=cursor, symbol=symbol, current=False
        )

    def income(self, start_ms: int, end_ms: int,
               cursor: int | str | None) -> _RootTH01AccountWindowPageV1:
        page_number = 1 if cursor is None else cursor
        query: dict[str, Any] = {
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": FIXED_PAGE_LIMIT,
            "page": page_number,
        }
        return self._get(
            "income_in_window", query, start_ms=start_ms, end_ms=end_ms,
            cursor=cursor, symbol=None, current=False
        )


def _root_probe_collector_and_packet() -> tuple[Any, Any, str, str]:
    collector_path = ACCOUNT_COLLECTOR_PATH
    probe_path = DEMO_PROBE_PATH
    for path, expected_sha256 in (
        (collector_path, ACCOUNT_COLLECTOR_SHA256),
        (probe_path, DEMO_PROBE_SHA256),
    ):
        try:
            info = path.lstat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except Exception:
            _account_window_fail("root_probe_source_unavailable")
        if path.is_symlink() or not path.is_file() or info.st_size > 2_000_000:
            _account_window_fail("root_probe_source_shape_invalid")
        if digest != expected_sha256:
            _account_window_fail("root_probe_source_pin_mismatch")
    collector = _root_account_source_module("th01_account_window_collector_r1", collector_path)
    probe = _root_account_source_module("th01_demo_availability_probe_r1", probe_path)
    collector_sha = hashlib.sha256(collector_path.read_bytes()).hexdigest()
    probe_sha = hashlib.sha256(probe_path.read_bytes()).hexdigest()
    if (
        collector_sha != ACCOUNT_COLLECTOR_SHA256
        or probe_sha != DEMO_PROBE_SHA256
        or collector_sha != collector.collector_source_sha256()
        or probe_sha != probe.probe_packet_sha256()
    ):
        _account_window_fail("root_probe_source_changed")
    return collector, probe, collector_sha, probe_sha


def _drain_probe_history(reader: FixedAccountWindowGetV1, resource: str,
                         start_ms: int, end_ms: int,
                         symbol: str | None = None) -> tuple[_RootTH01AccountWindowPageV1, ...]:
    pages: list[_RootTH01AccountWindowPageV1] = []
    cursor: int | str | None = None
    seen: set[int | str] = set()
    for _index in range(MAX_FIXED_REQUESTS):
        if resource == "all_orders_in_window":
            page = reader.all_orders(start_ms, end_ms, cursor)
        elif resource == "user_trades_in_window":
            if symbol is None:
                _account_window_fail("fixed_get_symbol_required")
            page = reader.user_trades(symbol, start_ms, end_ms, cursor)
        elif resource == "income_in_window":
            page = reader.income(start_ms, end_ms, cursor)
        else:
            _account_window_fail("fixed_get_history_resource_rejected")
        pages.append(page)
        if not page.has_more:
            return tuple(pages)
        next_cursor = page.next_cursor
        if next_cursor is None or next_cursor in seen or next_cursor == cursor:
            _account_window_fail("fixed_get_pagination_not_advancing")
        seen.add(next_cursor)
        cursor = next_cursor
    _account_window_fail("fixed_get_pagination_budget_reached")


def _root_probe_schema_ok(page: _RootTH01AccountWindowPageV1, kind: str) -> bool:
    if page._seal is not _ROOT_TH01_ACCOUNT_WINDOW_PAGE_SEAL or not page.rows:
        return False
    row = page.rows[0]
    if kind == "configuration":
        return all(type(row.get(name)) is bool for name in
                   ("canTrade", "dualSidePosition", "multiAssetsMargin"))
    if kind == "account_v2":
        assets, positions = row.get("assets"), row.get("positions")
        return (
            type(assets) is list
            and type(positions) is list
            and all(type(item) is dict and type(item.get("asset")) is str
                    and type(item.get("walletBalance")) is str for item in assets)
            and all(type(item) is dict and type(item.get("symbol")) is str
                    and type(item.get("positionSide")) is str
                    and type(item.get("positionAmt")) is str for item in positions)
        )
    return False


def _mint_demo_availability_receipt(
    auth: _RootTH01AccountWindowAuthV1,
    probe: Any,
    collector_sha256: str,
    probe_sha256: str,
    history_start_ms: int,
    facts: _RootTH01ProbeFactsV1,
) -> _RootTH01DemoAvailabilityReceiptV1:
    if (
        type(facts) is not _RootTH01ProbeFactsV1
        or facts._seal is not _ROOT_TH01_PROBE_FACTS_SEAL
        or facts.invocation_id != auth.invocation_id
        or facts.evidence_window_id != auth.evidence_window_id
        or facts._account_binding_ref != auth._account_binding_ref
        or any(
            type(page) is not _RootTH01AccountWindowPageV1
            or page._seal is not _ROOT_TH01_ACCOUNT_WINDOW_PAGE_SEAL
            or page._invocation_id != auth.invocation_id
            or page._evidence_window_id != auth.evidence_window_id
            or page._account_binding_ref != auth._account_binding_ref
            for page in facts.pages
        )
    ):
        _account_window_fail("root_probe_facts_invalid")
    route_results = dict(facts.route_results)
    if set(route_results) != set(FIXED_RESOURCE_PATHS) or any(
        type(value) is not bool for value in route_results.values()
    ):
        _account_window_fail("root_probe_route_facts_invalid")
    every_route = all(route_results.values())
    claims_by_name = {
        "demo_endpoint": every_route
        and facts.account_configuration_schema
        and facts.account_v2_schema,
        "account_configuration_schema": facts.account_configuration_schema,
        "account_v2_schema": facts.account_v2_schema,
        # The fixed implementation sends no symbol for the account-wide
        # endpoints. Public Binance API contracts define the scope; this GET
        # probe establishes that the configured Demo account accepts the
        # route shape. Each later account_full window still validates all
        # returned rows and per-symbol history before making a snapshot.
        "open_orders_all_symbols": route_results["standard_open_orders"],
        "algo_orders_all_symbols": route_results["algo_open_orders"],
        "all_orders_window_all_symbols": route_results["all_orders_in_window"]
        and facts.pagination_exhaustion,
        # A single BTCUSDT route probe establishes only that this configured
        # Demo account accepted the symbol-specific query. It cannot establish
        # the account's complete symbol universe; the case collector must
        # derive and cover that universe from its own complete account window.
        "user_trades_universe_closed": False,
        "income_window_all_symbols": route_results["income_in_window"]
        and facts.pagination_exhaustion,
        "pagination_exhaustion": facts.pagination_exhaustion,
        "no_silent_truncation": facts.no_silent_truncation,
        # Binance exposes no provider-authored watermark on these endpoints.
        # This field is optional informational context and is never synthesized.
        "provider_watermark_finality": False,
    }
    names = tuple(probe.REQUIRED_COVERAGE_CLAIMS)
    if set(claims_by_name) != set(names):
        _account_window_fail("root_coverage_claims_invalid")
    now_ms = int(time.time() * 1000)
    reader = auth._reader
    receipt = _RootTH01DemoAvailabilityReceiptV1(
        invocation_id=auth.invocation_id,
        evidence_window_id=auth.evidence_window_id,
        _account_binding_ref=auth._account_binding_ref,
        endpoint=probe.ENDPOINT,
        profile_id=probe.PROFILE_ID,
        collector_sha256=collector_sha256,
        probe_packet_sha256=probe_sha256,
        issued_at_ms=now_ms,
        expires_at_ms=now_ms + MAX_FIXED_CAPTURE_MS,
        history_start_ms=history_start_ms,
        coverage_claims=tuple((name, claims_by_name[name]) for name in names),
        request_budget=MAX_FIXED_REQUESTS - reader._request_count[0],
        row_budget=MAX_FIXED_ROWS - reader._row_count[0],
        body_budget_bytes=MAX_FIXED_BODY_BYTES - reader._response_bytes[0],
        capture_budget_ms=MAX_FIXED_CAPTURE_MS,
        _private_record_refs=tuple(reader._private_record_refs),
        _seal=_ROOT_TH01_DEMO_AVAILABILITY_RECEIPT_SEAL,
    )
    _ACTIVE_ROOT_PROBE_RECEIPTS.append(receipt)
    return receipt


def _run_root_demo_shape_probe(
    auth: _RootTH01AccountWindowAuthV1,
    *,
    availability_start_ms: int,
    availability_cutoff_ms: int,
) -> RootTH01DemoProbeOutcomeV1:
    """Run bounded fixed GET shapes; all response bytes go only to Root storage."""
    if (
        type(auth) is not _RootTH01AccountWindowAuthV1
        or auth._seal is not _ROOT_TH01_ACCOUNT_WINDOW_AUTH_SEAL
        or auth._reader._seal is not _ROOT_TH01_ACCOUNT_WINDOW_READER_SEAL
        or availability_start_ms != auth.history_start_ms
        or type(availability_cutoff_ms) is not int
        or availability_cutoff_ms <= availability_start_ms
        or availability_cutoff_ms > int(time.time() * 1000)
    ):
        _account_window_fail("root_probe_auth_or_window_invalid")
    _collector, probe, collector_sha, probe_sha = _root_probe_collector_and_packet()
    reader = auth._reader
    route_results: dict[str, bool] = {name: False for name in FIXED_RESOURCE_PATHS}
    config_ok = account_v2_ok = pagination_ok = transport_ok = False
    pages: list[_RootTH01AccountWindowPageV1] = []
    order_pages: tuple[_RootTH01AccountWindowPageV1, ...] = ()
    trade_pages: tuple[_RootTH01AccountWindowPageV1, ...] = ()
    income_pages: tuple[_RootTH01AccountWindowPageV1, ...] = ()
    first_failure: tuple[str, str] | None = None
    transport_diagnostic: _RootTH01TransportDiagnosticV1 | None = None
    all_symbol_routes = (
        "standard_open_orders", "algo_open_orders", "all_orders_in_window", "income_in_window"
    )
    try:
        active_stage = "account_configuration"
        account_config = reader.account_configuration()
        pages.append(account_config)
        route_results["account_configuration"] = True
        active_stage = "account_v2"
        account = reader.account_v2()
        pages.append(account)
        route_results["account_v2"] = True
        active_stage = "standard_open_orders"
        open_orders = reader.open_orders()
        pages.append(open_orders)
        route_results["standard_open_orders"] = True
        active_stage = "algo_open_orders"
        open_algo = reader.open_algo_orders()
        pages.append(open_algo)
        route_results["algo_open_orders"] = True
        active_stage = "all_orders_in_window"
        order_pages = _drain_probe_history(
            reader, "all_orders_in_window", availability_start_ms, availability_cutoff_ms - 1
        )
        pages.extend(order_pages)
        route_results["all_orders_in_window"] = True
        # The probe confirms one fixed symbol query shape only. It does not
        # treat that sample as account coverage. A saturated bounded page is
        # reported as incomplete instead of silently issuing an unbounded
        # cursor-only read for a shape check.
        active_stage = "user_trades_in_window"
        trade_sample = reader.user_trades(
            "BTCUSDT", availability_start_ms, availability_cutoff_ms - 1, None
        )
        trade_pages = (trade_sample,)
        pages.append(trade_sample)
        route_results["user_trades_in_window"] = True
        active_stage = "income_in_window"
        income_pages = _drain_probe_history(
            reader, "income_in_window", availability_start_ms, availability_cutoff_ms - 1
        )
        pages.extend(income_pages)
        route_results["income_in_window"] = True
        active_stage = "probe_validation"
        config_ok = _root_probe_schema_ok(account_config, "configuration")
        account_v2_ok = _root_probe_schema_ok(account, "account_v2")
        pagination_ok = all(
            page.terminal_proof in {"short_page", "single_response"}
            and page.has_more is False
            and page.next_cursor is None
            for page in order_pages + trade_pages + income_pages
        )
        transport_ok = all(
            page.http_status == 200 and page.transport_complete is True and page.truncated is False
            for page in pages
        )
    except RootTH01AccountWindowBlocked as exc:
        # Partial response bytes remain protected; only already completed
        # route observations are retained in the safe predicate projection.
        first_failure = _safe_probe_failure(active_stage, exc)
        transport_diagnostic = _safe_probe_transport_diagnostic(exc)
        config_ok = account_v2_ok = pagination_ok = transport_ok = False
    except Exception as exc:
        first_failure = _safe_probe_failure(active_stage, exc)
        config_ok = account_v2_ok = pagination_ok = transport_ok = False
    facts = _RootTH01ProbeFactsV1(
        invocation_id=auth.invocation_id,
        evidence_window_id=auth.evidence_window_id,
        _account_binding_ref=auth._account_binding_ref,
        route_results=tuple((name, route_results[name]) for name in FIXED_RESOURCE_PATHS),
        account_configuration_schema=config_ok,
        account_v2_schema=account_v2_ok,
        pagination_exhaustion=pagination_ok,
        no_silent_truncation=transport_ok and pagination_ok,
        pages=tuple(pages),
        _seal=_ROOT_TH01_PROBE_FACTS_SEAL,
    )
    receipt = _mint_demo_availability_receipt(
        auth, probe, collector_sha, probe_sha, auth.history_start_ms, facts
    )
    try:
        readiness = probe.validate_root_availability_receipt(
            auth,
            receipt,
            collector_sha256=collector_sha,
            history_start_ms=auth.history_start_ms,
            now_ms=int(time.time() * 1000),
        )
        if type(readiness) is not probe.ProbeReadinessV1 or not readiness.snapshot_ready:
            _account_window_fail("probe_readiness_projection_invalid")
        result = "READY_FOR_ACCOUNT_SNAPSHOT"
    except probe.ProbeReceiptBlocked as exc:
        readiness = exc.readiness
        if (
            type(readiness) is not probe.ProbeReadinessV1
            or readiness.snapshot_ready is not False
        ):
            _account_window_fail("probe_readiness_projection_invalid")
        result = "BLOCKED_ACCOUNT_SNAPSHOT"
    public = RootTH01DemoProbePublicV1(
        result=result,
        readiness=readiness,
        route_results=tuple((name, route_results[name]) for name in FIXED_RESOURCE_PATHS),
        account_configuration_schema=config_ok,
        account_v2_schema=account_v2_ok,
        pagination_exhaustion=pagination_ok,
        no_silent_truncation=transport_ok and pagination_ok,
        all_symbol_routes_requested_without_symbol=all_symbol_routes,
        source_sha256=probe_sha,
        first_failure=first_failure,
        transport_diagnostic=transport_diagnostic,
    )
    return RootTH01DemoProbeOutcomeV1(auth, receipt, public)


def run_root_th01_demo_shape_probe() -> RootTH01DemoProbeOutcomeV1:
    """Root-only entry for an authorized, zero-write 71-hour Demo shape probe.

    The function has no endpoint, method, symbol, key, credential-dict, writer,
    or transport input. It reads only ``ROOT/.env`` through the pinned Root
    bounded reader; account responses are written to the exact protected
    invocation directory, and callers receive a redacted typed outcome.
    """
    now_ms = int(time.time() * 1000)
    history_start_ms = now_ms - (71 * 60 * 60 * 1000)
    invocation_id = uuid4().hex
    evidence_window_id = "th01-window:" + invocation_id
    # R3 refuses to bootstrap if backtrader_runtime is already loaded. Obtain
    # its bounded credential capability before the protected writer imports
    # that package; no provider request is made during this authority step.
    credential_context = _root_th01_credential_context(ROOT / ".env")
    writer = create_root_protected_writer(invocation_id)
    auth = _make_root_account_window_auth(
        credential_context, writer, invocation_id, evidence_window_id, history_start_ms
    )
    del credential_context
    private_ref = writer.write_private_record(
        "account_window_probe_start",
        {
            "schema": "iteration41.binance.th01.account-window-probe-start.private.v1",
            "invocation_ref": invocation_id,
            "evidence_window_ref": evidence_window_id,
            "history_start_ms": history_start_ms,
            "history_window_ms": now_ms - history_start_ms,
            "source_profile": "binance.th01.account-window.fixed-get.r1",
            "source_kind": "ROOT_PROTECTED_SIGNED_REST_READ",
        },
    )
    auth._reader._private_record_refs.append(private_ref)
    return _run_root_demo_shape_probe(
        auth, availability_start_ms=history_start_ms, availability_cutoff_ms=now_ms
    )


__all__ = [
    "RootTH01ProtectedOwnerBlocked",
    "RootTH01ProtectedWriterV1",
    "RootTH01WALGuardV1",
    "RootTH01AccountWindowBlocked",
    "_RootTH01AccountWindowAuthV1",
    "_RootTH01AccountWindowPageV1",
    "_RootTH01DemoAvailabilityReceiptV1",
    "FixedAccountWindowGetV1",
    "RootTH01DemoProbePublicV1",
    "RootTH01DemoProbeOutcomeV1",
    "create_root_protected_writer",
    "run_root_th01_demo_shape_probe",
    "verify_root_readonly_source_binding_for_source_qa",
]
