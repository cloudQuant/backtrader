"""Root-only bounded USDⓈ-M account-window candidate collector.

This module intentionally separates permission to perform fixed reads from
proof that the returned rows form a complete account snapshot.  It contains
no trading route.  The Root driver exact-loads the already-reviewed fixed GET
transport as ``__main__`` so Windows ``spawn`` re-executes the same pinned
driver before resolving the worker target.

The ordinary tests exercise only source and fake response seams.  The live
entry point is not registered with the certification CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import stat
from types import ModuleType
from typing import Any, Mapping
from uuid import uuid4
from decimal import Decimal, InvalidOperation


ROOT = Path(__file__).resolve().parents[4]
VENUE_ROOT = ROOT / "examples" / "000_live_certification" / "binance_penetration"
OWNER_PATH = VENUE_ROOT / "_certification" / "th01_root_protected_owner_r1.py"
DRIVER_PATH = ROOT / "scripts" / "iteration41_binance_th01_account_window_candidate_r2.py"
CAPTURE_CANDIDATE_PATH = VENUE_ROOT / "_certification" / "th01_account_window_candidate_r2.py"
CLI_PATH = ROOT / "backtrader_runtime" / "certification_binance_roundtrip_r3_cli.py"
PRIVATE_HELPER_PATH = ROOT / "backtrader_runtime" / "certification_roundtrip_private.py"

# These are the already-reviewed fixed transport and protected helper bytes.
# The R3 39-member package bootstrap is deliberately not part of this route.
OWNER_SHA256 = "290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f"
CLI_SHA256 = "62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76"
PRIVATE_HELPER_SHA256 = "b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd"

ENDPOINT = "https://demo-fapi.binance.com"
FIXED_HOST = "demo-fapi.binance.com"
RECV_WINDOW_MS = 5000
PAGE_LIMIT = 1000
MAX_WINDOW_MS = 71 * 60 * 60 * 1000
MAX_AGE_MS = 89 * 24 * 60 * 60 * 1000
MAX_REQUESTS = 64
MAX_ROWS = 5000
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BODY_BYTES = 64 * 1024 * 1024
MAX_CAPTURE_MS = 120_000
REQUEST_TIMEOUT_SECONDS = 8.0

ROUTE_PATHS = {
    "account_configuration": "/fapi/v1/accountConfig",
    "account_v2": "/fapi/v2/account",
    "standard_open_orders": "/fapi/v1/openOrders",
    "algo_open_orders": "/fapi/v1/openAlgoOrders",
    "all_orders_in_window": "/fapi/v1/allOrders",
    "user_trades_in_window": "/fapi/v1/userTrades",
    "income_in_window": "/fapi/v1/income",
}
CURRENT_ROUTES = (
    "account_configuration",
    "account_v2",
    "standard_open_orders",
    "algo_open_orders",
)
HISTORY_ROUTES = (
    "all_orders_in_window",
    "user_trades_in_window",
    "income_in_window",
)

_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_SYMBOL = re.compile(r"[A-Z0-9_]{1,32}\Z")
_RESOURCE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_PRIVATE_CAPTURE_SEAL = object()
_READ_AUTH_SEAL = object()
_READ_SESSION_SEAL = object()


class AccountWindowBlocked(ValueError):
    """Fixed public failure code; never includes provider or OS text."""

    def __init__(self, code: str, public_projection: Mapping[str, Any] | None = None):
        if type(code) is not str or re.fullmatch(r"[a-z0-9_]{1,64}", code) is None:
            code = "account_window_blocked"
        self.code = code
        self.public_projection = public_projection
        super().__init__(code)


def _block(code: str) -> None:
    raise AccountWindowBlocked(code)


def _check_source_ancestors(lexical: Path) -> None:
    relative = lexical.relative_to(ROOT)
    if not relative.parts:
        _block("source_path_outside_root")
    directories = list(reversed(ROOT.parents)) + [ROOT]
    current = ROOT
    for part in relative.parts[:-1]:
        current = current / part
        directories.append(current)
    for directory in directories:
        directory_info = directory.lstat()
        if (
            stat.S_ISLNK(directory_info.st_mode)
            or not stat.S_ISDIR(directory_info.st_mode)
            or getattr(directory_info, "st_file_attributes", 0) & 0x400
        ):
            _block("source_ancestor_shape_invalid")


def _bounded_source(path: Path, expected_sha256: str, maximum: int) -> bytes:
    """Check path shape before reading a bounded, exact public source file."""
    try:
        lexical = Path(os.path.abspath(str(path)))
        _check_source_ancestors(lexical)
    except AccountWindowBlocked:
        raise
    except Exception:
        _block("source_ancestor_unavailable")
    try:
        info = lexical.lstat()
    except Exception:
        _block("source_unavailable")
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & 0x400
        or getattr(info, "st_nlink", 1) != 1
        or info.st_size <= 0
        or info.st_size > maximum
    ):
        _block("source_shape_invalid")
    descriptor = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        descriptor = os.open(str(lexical), flags)
        opened = os.fstat(descriptor)
        identity = (
            info.st_dev,
            info.st_ino,
            info.st_size,
            getattr(info, "st_mtime_ns", None),
            getattr(info, "st_ctime_ns", None),
        )
        opened_identity = (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            getattr(opened, "st_mtime_ns", None),
            getattr(opened, "st_ctime_ns", None),
        )
        if identity != opened_identity or getattr(opened, "st_nlink", 1) != 1:
            _block("source_changed_before_read")
        buffer = bytearray()
        while len(buffer) <= maximum:
            part = os.read(descriptor, min(65536, maximum + 1 - len(buffer)))
            if not part:
                break
            buffer.extend(part)
        raw = bytes(buffer)
        after_handle = os.fstat(descriptor)
        after_path = lexical.lstat()
        after_identity = (
            after_handle.st_dev,
            after_handle.st_ino,
            after_handle.st_size,
            getattr(after_handle, "st_mtime_ns", None),
            getattr(after_handle, "st_ctime_ns", None),
        )
        path_identity = (
            after_path.st_dev,
            after_path.st_ino,
            after_path.st_size,
            getattr(after_path, "st_mtime_ns", None),
            getattr(after_path, "st_ctime_ns", None),
        )
        if (
            after_identity != identity
            or path_identity != identity
            or stat.S_ISLNK(after_path.st_mode)
            or getattr(after_path, "st_file_attributes", 0) & 0x400
            or getattr(after_path, "st_nlink", 1) != 1
        ):
            _block("source_changed_during_read")
        _check_source_ancestors(lexical)
    except AccountWindowBlocked:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except Exception:
                pass
        raise
    except Exception:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except Exception:
                pass
        _block("source_unavailable")
    try:
        os.close(descriptor)
    except Exception:
        _block("source_close_failed")
    if len(raw) != info.st_size or len(raw) > maximum or hashlib.sha256(raw).hexdigest() != expected_sha256:
        _block("source_pin_mismatch")
    return raw


def source_preflight(root: Path = ROOT) -> dict[str, str]:
    """Verify every public source dependency before credentials or storage."""
    try:
        checked_root = root.resolve(strict=True)
    except Exception:
        _block("source_root_unavailable")
    if checked_root != ROOT.resolve():
        _block("source_root_mismatch")
    rows = (
        (OWNER_PATH, OWNER_SHA256, 250_000),
        (CLI_PATH, CLI_SHA256, 100_000),
        (PRIVATE_HELPER_PATH, PRIVATE_HELPER_SHA256, 64_000),
    )
    hashes: dict[str, str] = {}
    for path, expected, maximum in rows:
        raw = _bounded_source(path, expected, maximum)
        hashes[path.relative_to(ROOT).as_posix()] = hashlib.sha256(raw).hexdigest()
    return hashes


def _verify_candidate_source_binding() -> str:
    module = sys.modules.get(__name__)
    if (
        module is None
        or module.__dict__ is not globals()
        or Path(getattr(module, "__file__", "")).resolve() != CAPTURE_CANDIDATE_PATH.resolve()
    ):
        _block("candidate_source_binding_invalid")
    expected = getattr(module, "__th01_verified_candidate_source_sha256__", None)
    if type(expected) is not str or _HEX64.fullmatch(expected) is None:
        _block("candidate_source_binding_invalid")
    raw = _bounded_source(CAPTURE_CANDIDATE_PATH, expected, 100_000)
    return hashlib.sha256(raw).hexdigest()


def _verify_postflight_sources(
    initial_candidate_sha256: str,
    initial_source_hashes: Mapping[str, str],
) -> None:
    if (
        _verify_candidate_source_binding() != initial_candidate_sha256
        or source_preflight() != dict(initial_source_hashes)
    ):
        _block("source_pin_mismatch")


def _compile_verified_module(name: str, path: Path, raw: bytes) -> ModuleType:
    if (
        type(name) is not str
        or not re.fullmatch(r"_iteration41_th01_(?:protected_cli|private_helper)_r2_[0-9a-f]{32}", name)
        or name in sys.modules
        or type(raw) is not bytes
        or not raw
    ):
        _block("source_module_input_invalid")
    module = ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__dict__["__th01_source_sha256__"] = hashlib.sha256(raw).hexdigest()
    sys.modules[name] = module
    try:
        code = compile(raw, str(path), "exec", dont_inherit=True)
        exec(code, module.__dict__)
    except Exception:
        if sys.modules.get(name) is module:
            sys.modules.pop(name, None)
        _block("source_module_load_failed")
    return module


@dataclass(frozen=True, repr=False)
class VerifiedReadSourcesV1:
    """Exact source modules used by the Root-owned read path."""

    owner: ModuleType = field(repr=False)
    cli: ModuleType = field(repr=False)
    private: ModuleType = field(repr=False)
    source_hashes: Mapping[str, str] = field(repr=False)
    _seal: object = field(repr=False)

    def __repr__(self) -> str:
        return "VerifiedReadSourcesV1(<fixed public sources>)"


def _verify_owner_namespace(owner: object) -> ModuleType:
    if not isinstance(owner, ModuleType):
        _block("owner_transport_unavailable")
    if (
        owner is not sys.modules.get("__main__")
        or getattr(owner, "__name__", None) != "__main__"
        or type(getattr(owner, "__file__", None)) is not str
        or Path(owner.__file__).resolve() != DRIVER_PATH.resolve()
        or getattr(owner, "__th01_verified_owner_source_sha256__", None) != OWNER_SHA256
        or getattr(owner, "__th01_verified_owner_source_path__", None) != str(OWNER_PATH)
        or getattr(owner, "ROOT", None) != ROOT
    ):
        _block("owner_transport_source_binding_invalid")
    worker = getattr(owner, "_root_fixed_signed_get_worker", None)
    parent = getattr(owner, "_run_root_fixed_signed_get", None)
    if (
        not callable(worker)
        or not callable(parent)
        or getattr(worker, "__module__", None) != "__main__"
        or getattr(worker, "__code__", None) is None
        or Path(worker.__code__.co_filename).resolve() != OWNER_PATH.resolve()
        or getattr(parent, "__code__", None) is None
        or Path(parent.__code__.co_filename).resolve() != OWNER_PATH.resolve()
    ):
        _block("owner_transport_source_binding_invalid")
    return owner


def load_verified_read_sources(owner_namespace: object, root: Path = ROOT) -> VerifiedReadSourcesV1:
    """Cold-load only the tracked credential reader and protected helper.

    `owner_namespace` must be the exact byte-compiled owner transport installed
    by the root driver into ``__main__``. No package initializer or pyc import
    is used for the two helper modules.
    """
    hashes = source_preflight(root)
    owner = _verify_owner_namespace(owner_namespace)
    cli_raw = _bounded_source(CLI_PATH, CLI_SHA256, 100_000)
    private_raw = _bounded_source(PRIVATE_HELPER_PATH, PRIVATE_HELPER_SHA256, 64_000)
    module_token = uuid4().hex
    cli = _compile_verified_module(
        "_iteration41_th01_protected_cli_r2_" + module_token, CLI_PATH, cli_raw
    )
    private = _compile_verified_module(
        "_iteration41_th01_private_helper_r2_" + uuid4().hex,
        PRIVATE_HELPER_PATH,
        private_raw,
    )
    if not callable(getattr(cli, "protected_env", None)):
        _block("protected_reader_unavailable")
    if not callable(getattr(private, "create_private_directory", None)):
        _block("protected_writer_unavailable")
    return VerifiedReadSourcesV1(
        owner=owner,
        cli=cli,
        private=private,
        source_hashes=hashes,
        _seal=_READ_AUTH_SEAL,
    )


def _account_binding_ref(credentials: object) -> str:
    """Match the existing R3 demo-account pseudonym; keep it private in memory."""
    if type(credentials) is not dict or set(credentials) != {"api_key", "secret"}:
        _block("protected_reader_credential_shape")
    api_key = credentials.get("api_key")
    secret = credentials.get("secret")
    if (
        type(api_key) is not str
        or not api_key.isascii()
        or not 16 <= len(api_key) <= 256
        or type(secret) is not str
        or not secret.isascii()
        or not 16 <= len(secret) <= 256
    ):
        _block("protected_reader_credential_shape")
    key_ref = hashlib.sha256(b"binance-demo-api-key-v1\0" + api_key.encode("ascii")).hexdigest()
    payload = json.dumps(
        {"venue": "binance", "environment": "demo", "product": "USDM", "account_ref": key_ref},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, repr=False)
class ProtectedCaptureWriterV1:
    """Root-created private page archive; only opaque references escape."""

    invocation_id: str
    directory: Any = field(repr=False)
    _sequence: list[int] = field(repr=False)
    _private_module: ModuleType = field(repr=False)
    _seal: object = field(repr=False)

    def __repr__(self) -> str:
        return "ProtectedCaptureWriterV1(<Root-private-directory>)"

    def append(self, document: dict[str, Any]) -> str:
        if (
            self._seal is not _PRIVATE_CAPTURE_SEAL
            or type(document) is not dict
            or type(self._sequence) is not list
            or len(self._sequence) != 1
            or type(self._sequence[0]) is not int
        ):
            _block("protected_capture_writer_binding_invalid")
        private_type = getattr(self._private_module, "PrivateArtifactDirectory", None)
        if private_type is None or type(self.directory) is not private_type:
            _block("protected_capture_writer_binding_invalid")
        sequence = self._sequence[0]
        self._sequence[0] += 1
        name = "page-" + format(sequence, "06d") + "-" + uuid4().hex + ".json"
        try:
            ref = self.directory.write_json(name, document)
            self.directory.verify()
        except Exception:
            _block("protected_capture_write_failed")
        # `write_json` returns a content digest. It is intentionally discarded
        # because the contents include provider account data.
        if type(ref) is not str or _HEX64.fullmatch(ref) is None:
            _block("protected_capture_write_unverified")
        return uuid4().hex


@dataclass(frozen=True, repr=False)
class RootFixedGetAuthorizationV1:
    """Root-issued seven-GET authorization, with no completeness claims."""

    invocation_id: str
    evidence_window_id: str
    history_start_ms: int
    phase_cutoff_ms: int
    account_binding_ref: str = field(repr=False)
    _credential_box: list[str] = field(repr=False)
    _writer: ProtectedCaptureWriterV1 = field(repr=False)
    _sources: VerifiedReadSourcesV1 = field(repr=False)
    _started_monotonic: float = field(repr=False)
    _request_count: list[int] = field(repr=False)
    _row_count: list[int] = field(repr=False)
    _body_bytes: list[int] = field(repr=False)
    _route_entries: dict[str, int] = field(repr=False)
    _route_completed: dict[str, int] = field(repr=False)
    _active_stage: list[str] = field(repr=False)
    _seal: object = field(repr=False)

    def __repr__(self) -> str:
        return "RootFixedGetAuthorizationV1(<read-only scope; no coverage claims>)"


@dataclass(frozen=True, repr=False)
class CandidatePageV1:
    resource: str
    request_ref: str
    response_ref: str
    rows: tuple[dict[str, Any], ...] = field(repr=False)
    response_body: bytes = field(repr=False)
    request_started_at_ms: int
    response_completed_at_ms: int
    row_count: int
    page_limit: int
    query: Mapping[str, Any] = field(repr=False)
    _invocation_id: str = field(repr=False)
    _evidence_window_id: str = field(repr=False)
    _account_binding_ref: str = field(repr=False)
    _seal: object = field(repr=False)

    def __repr__(self) -> str:
        return "CandidatePageV1(<private provider page>)"


class FixedGetReaderV1:
    """Instance-local capability for seven fixed GET resources only."""

    __slots__ = ("_auth", "_seal")

    def __init__(self, auth: RootFixedGetAuthorizationV1, seal: object):
        if type(auth) is not RootFixedGetAuthorizationV1 or seal is not _READ_SESSION_SEAL:
            _block("fixed_get_auth_binding_invalid")
        self._auth = auth
        self._seal = seal

    def __repr__(self) -> str:
        return "FixedGetReaderV1(<seven fixed GET routes>)"

    @property
    def _account_binding_ref(self) -> str:
        if self._seal is not _READ_SESSION_SEAL or self._auth._seal is not _READ_AUTH_SEAL:
            _block("fixed_get_auth_binding_invalid")
        return self._auth.account_binding_ref

    def current(self, resource: str) -> CandidatePageV1:
        if resource not in CURRENT_ROUTES:
            _block("fixed_get_current_resource_rejected")
        self._auth._active_stage[0] = resource
        return self._read(resource, {})

    def all_orders(self, start_ms: int, end_ms: int) -> CandidatePageV1:
        self._auth._active_stage[0] = "all_orders_in_window"
        return self._read(
            "all_orders_in_window",
            {"startTime": start_ms, "endTime": end_ms, "limit": PAGE_LIMIT},
        )

    def income(self, start_ms: int, end_ms: int, page: int) -> CandidatePageV1:
        self._auth._active_stage[0] = "income_in_window"
        return self._read(
            "income_in_window",
            {"startTime": start_ms, "endTime": end_ms, "limit": PAGE_LIMIT, "page": page},
        )

    def user_trades(
        self,
        symbol: str,
        start_ms: int,
        end_ms: int,
        from_id: int | None = None,
    ) -> CandidatePageV1:
        self._auth._active_stage[0] = "user_trades_in_window"
        if type(symbol) is not str or _SYMBOL.fullmatch(symbol) is None:
            _block("fixed_get_symbol_rejected")
        if from_id is None:
            query = {"symbol": symbol, "startTime": start_ms, "endTime": end_ms, "limit": PAGE_LIMIT}
        else:
            if type(from_id) is not int or from_id <= 0:
                _block("fixed_get_cursor_rejected")
            query = {"symbol": symbol, "fromId": from_id, "limit": PAGE_LIMIT}
        return self._read("user_trades_in_window", query)

    def _read(self, resource: str, query: dict[str, Any]) -> CandidatePageV1:
        auth = self._auth
        if (
            self._seal is not _READ_SESSION_SEAL
            or auth._seal is not _READ_AUTH_SEAL
            or resource not in ROUTE_PATHS
            or type(query) is not dict
        ):
            _block("fixed_get_auth_binding_invalid")
        if any(str(key).lower() in {"origclientorderid", "signature", "apikey", "secret"} for key in query):
            _block("fixed_get_query_forbidden")
        now_monotonic = time.monotonic()
        elapsed_ms = int((now_monotonic - auth._started_monotonic) * 1000)
        remaining_ms = MAX_CAPTURE_MS - elapsed_ms
        if remaining_ms <= 0:
            _block("fixed_get_capture_budget_reached")
        if auth._request_count[0] >= MAX_REQUESTS:
            _block("fixed_get_request_budget_reached")
        deadline = now_monotonic + min(REQUEST_TIMEOUT_SECONDS, remaining_ms / 1000.0)
        path, planned, is_history = auth._sources.owner._fixed_request_path(
            resource, query, auth.history_start_ms - 1, int(time.time() * 1000)
        )
        if path != ROUTE_PATHS[resource]:
            _block("fixed_get_route_rejected")
        if not is_history and query:
            _block("fixed_get_current_query_rejected")
        auth._route_entries[resource] = auth._route_entries.get(resource, 0) + 1
        request_ref, response_ref = uuid4().hex, uuid4().hex
        auth._request_count[0] += 1
        api_key, secret = auth._credential_box
        try:
            outcome = auth._sources.owner._run_root_fixed_signed_get(
                resource,
                dict(planned),
                api_key,
                secret,
                auth.history_start_ms - 1,
                deadline,
            )
        except Exception:
            _block("fixed_get_transport_unproven")
        body = getattr(outcome, "body", None)
        status = getattr(outcome, "status", None)
        complete = getattr(outcome, "complete", None)
        if (
            type(body) is not bytes
            or len(body) > MAX_PAGE_BYTES
            or type(status) is not int
            or status != 200
            or complete is not True
            or getattr(outcome, "reason", None) is not None
            or getattr(outcome, "worker_exit_code", None) != 0
            or getattr(outcome, "pipe_eof", None) is not True
            or getattr(outcome, "forced_shutdown", None) is not False
        ):
            # Never exceed the per-page private archive ceiling while recording
            # a rejected transport response. The fixed failure metadata remains
            # useful; an oversized provider body is not persisted.
            body_bytes = body if type(body) is bytes and len(body) <= MAX_PAGE_BYTES else b""
            self._write_private_page(
                resource, query, request_ref, response_ref, outcome, body_bytes
            )
            _block("fixed_get_provider_response_unproven")
        next_body_bytes = auth._body_bytes[0] + len(body)
        if next_body_bytes > MAX_TOTAL_BODY_BYTES:
            _block("fixed_get_body_budget_reached")
        started = getattr(outcome, "started_at_ms", None)
        completed = getattr(outcome, "completed_at_ms", None)
        if (
            type(started) is not int
            or type(completed) is not int
            or started <= 0
            or completed < started
            or completed > int(time.time() * 1000) + 5000
        ):
            _block("fixed_get_timestamp_invalid")
        try:
            rows = _rows_for_resource(resource, body)
            nested_rows = _nested_row_count(resource, rows)
        except AccountWindowBlocked:
            # Preserve a bounded malformed provider response privately so a
            # Root reviewer can diagnose it without a public body or digest.
            self._write_private_page(resource, query, request_ref, response_ref, outcome, body)
            raise
        next_row_count = auth._row_count[0] + nested_rows
        if next_row_count > MAX_ROWS:
            _block("fixed_get_row_budget_reached")
        self._write_private_page(resource, query, request_ref, response_ref, outcome, body)
        auth._body_bytes[0] = next_body_bytes
        auth._row_count[0] = next_row_count
        auth._route_completed[resource] = auth._route_completed.get(resource, 0) + 1
        return CandidatePageV1(
            resource=resource,
            request_ref=request_ref,
            response_ref=response_ref,
            rows=rows,
            response_body=body,
            request_started_at_ms=started,
            response_completed_at_ms=completed,
            row_count=nested_rows,
            page_limit=PAGE_LIMIT if is_history else 0,
            query=dict(query),
            _invocation_id=auth.invocation_id,
            _evidence_window_id=auth.evidence_window_id,
            _account_binding_ref=auth.account_binding_ref,
            _seal=_READ_SESSION_SEAL,
        )

    def _write_private_page(
        self,
        resource: str,
        query: Mapping[str, Any],
        request_ref: str,
        response_ref: str,
        outcome: Any,
        body: bytes,
    ) -> None:
        auth = self._auth
        if auth._seal is not _READ_AUTH_SEAL:
            _block("fixed_get_auth_binding_invalid")
        try:
            document = {
                "schema": "iteration41.binance.th01.account-window-page.private.r2",
                "invocation_ref": auth.invocation_id,
                "evidence_window_ref": auth.evidence_window_id,
                "account_binding_ref": auth.account_binding_ref,
                "owner_source_sha256": OWNER_SHA256,
                "protected_reader_source_sha256": CLI_SHA256,
                "private_writer_source_sha256": PRIVATE_HELPER_SHA256,
                "fixed_transport_source_sha256": OWNER_SHA256,
            "source_preflight_sha256": auth._sources.source_hashes,
                "request_ref": request_ref,
                "response_ref": response_ref,
                "resource": resource,
                "method": "GET",
                "endpoint": ENDPOINT,
                "path": ROUTE_PATHS[resource],
                "unsigned_query": dict(query),
                "request_started_at_ms": getattr(outcome, "started_at_ms", None),
                "response_completed_at_ms": getattr(outcome, "completed_at_ms", None),
                "http_status": getattr(outcome, "status", None),
                "transport_complete": getattr(outcome, "complete", None),
                "worker_exit_code": getattr(outcome, "worker_exit_code", None),
                "pipe_eof": getattr(outcome, "pipe_eof", None),
                "forced_shutdown": getattr(outcome, "forced_shutdown", None),
                "response_body_b64": base64.b64encode(body).decode("ascii"),
            }
            auth._writer.append(document)
        except AccountWindowBlocked:
            raise
        except Exception:
            _block("protected_capture_write_failed")


@dataclass(frozen=True, repr=False)
class CandidateAssessmentV1:
    """Private account-window candidate; never a runner `StateSnapshot`."""

    invocation_ref: str
    evidence_window_ref: str
    history_start_ms: int
    phase_cutoff_ms: int
    pages: Mapping[str, tuple[CandidatePageV1, ...]] = field(repr=False)
    candidate_symbols: tuple[str, ...] = field(repr=False)
    all_orders_rows: tuple[dict[str, Any], ...] = field(repr=False)
    income_rows: tuple[dict[str, Any], ...] = field(repr=False)
    user_trade_rows: Mapping[str, tuple[dict[str, Any], ...]] = field(repr=False)
    all_orders_time_partition_scan_completed: bool
    income_short_page_terminal_observed: bool
    candidate_symbol_user_trades_short_page_terminal_observed: bool
    user_trades_universe_closed: bool
    provider_watermark_finality: bool
    _account_binding_ref: str = field(repr=False)
    _seal: object = field(repr=False)

    def __repr__(self) -> str:
        return "CandidateAssessmentV1(<bounded private account-window candidate>)"

    def public_document(self) -> dict[str, Any]:
        if self._seal is not _READ_SESSION_SEAL:
            _block("candidate_assessment_binding_invalid")
        observed = {
            name: bool(self.pages.get(name))
            for name in (*CURRENT_ROUTES, "all_orders_in_window", "income_in_window")
        }
        observed["user_trades_in_window"] = any(
            name.startswith("user_trades_in_window:") and bool(items)
            for name, items in self.pages.items()
        )
        return {
            "schema": "iteration41.binance.th01.account-window-candidate-public.r2",
            "status": "CANDIDATE_ONLY",
            "invocation_ref": self.invocation_ref,
            "evidence_window_ref": self.evidence_window_ref,
            "completed_route_observations": observed,
            "route_page_completion_counts": {
                resource: (
                    sum(len(items) for name, items in self.pages.items() if name.startswith(resource + ":"))
                    if resource == "user_trades_in_window"
                    else len(self.pages.get(resource, ()))
                )
                for resource in (*CURRENT_ROUTES, *HISTORY_ROUTES)
            },
            "all_orders_time_partition_scan_completed": self.all_orders_time_partition_scan_completed,
            "income_short_page_terminal_observed": self.income_short_page_terminal_observed,
            "candidate_symbol_user_trades_short_page_terminal_observed": (
                self.candidate_symbol_user_trades_short_page_terminal_observed
            ),
            "user_trades_universe_closed": self.user_trades_universe_closed,
            "provider_watermark_finality": self.provider_watermark_finality,
            "account_full_snapshot_issued": False,
            "formal_case_pass": False,
            "unresolved": [
                "trade_universe: use a provider-backed account-wide bounded trade source; known-symbol queries are candidates only",
                "three_phase_state: reuse one invocation-bound protected read session for three fresh, unchanged account_full snapshots",
                "monitor: join the actual strategy-attached TradeLogger event to the separately spawned read-only monitor service summary",
            ],
        }


def _strict_json(body: bytes) -> Any:
    if type(body) is not bytes or not body or len(body) > MAX_PAGE_BYTES:
        _block("provider_body_invalid")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                _block("provider_duplicate_json_key")
            result[key] = value
        return result

    def nonfinite(_value: str) -> Any:
        _block("provider_nonfinite_json")

    try:
        return json.loads(body.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
    except AccountWindowBlocked:
        raise
    except Exception:
        _block("provider_json_invalid")


def _rows_for_resource(resource: str, body: bytes) -> tuple[dict[str, Any], ...]:
    value = _strict_json(body)
    if resource in {"account_configuration", "account_v2"}:
        if type(value) is not dict:
            _block("provider_account_shape_invalid")
        return (value,)
    if type(value) is not list or any(type(row) is not dict for row in value):
        _block("provider_rows_shape_invalid")
    return tuple(value)


def _nested_row_count(resource: str, rows: tuple[dict[str, Any], ...]) -> int:
    count = len(rows)
    if resource == "account_v2":
        if len(rows) != 1:
            _block("provider_account_shape_invalid")
        assets, positions = rows[0].get("assets"), rows[0].get("positions")
        if type(assets) is not list or type(positions) is not list:
            _block("provider_account_shape_invalid")
        if any(type(row) is not dict for row in (*assets, *positions)):
            _block("provider_account_shape_invalid")
        count += len(assets) + len(positions)
    return count


def _decimal_text(value: object, *, nonnegative: bool = False, positive: bool = False) -> Decimal:
    if type(value) is not str or len(value) > 96 or re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value) is None:
        _block("provider_decimal_shape_invalid")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        _block("provider_decimal_shape_invalid")
    if not parsed.is_finite() or (nonnegative and parsed < 0) or (positive and parsed <= 0):
        _block("provider_decimal_range_invalid")
    return parsed


def _positive_integer(value: object) -> int:
    if type(value) is not int or value <= 0 or value >= 2**63:
        _block("provider_integer_shape_invalid")
    return value


def _validate_current_pages(pages: Mapping[str, tuple[CandidatePageV1, ...]]) -> None:
    for resource in CURRENT_ROUTES:
        items = pages.get(resource)
        if type(items) is not tuple or len(items) != 1:
            _block("current_route_not_complete")
        page = items[0]
        if page._seal is not _READ_SESSION_SEAL or page.resource != resource:
            _block("current_route_page_binding_invalid")
        if resource == "account_configuration":
            row = page.rows[0]
            if any(type(row.get(key)) is not bool for key in ("canTrade", "dualSidePosition", "multiAssetsMargin")):
                _block("account_configuration_schema_invalid")
        elif resource == "account_v2":
            row = page.rows[0]
            assets, positions = row.get("assets"), row.get("positions")
            if type(assets) is not list or type(positions) is not list:
                _block("account_v2_schema_invalid")
            asset_names: set[str] = set()
            for item in assets:
                asset = item.get("asset")
                if type(asset) is not str or re.fullmatch(r"[A-Z0-9]{2,24}", asset) is None or asset in asset_names:
                    _block("account_v2_schema_invalid")
                _decimal_text(item.get("walletBalance"))
                asset_names.add(asset)
            position_names: set[tuple[str, str]] = set()
            for item in positions:
                symbol, side = item.get("symbol"), item.get("positionSide")
                if (
                    type(symbol) is not str
                    or _SYMBOL.fullmatch(symbol) is None
                    or type(side) is not str
                    or side not in {"BOTH", "LONG", "SHORT"}
                ):
                    _block("account_v2_schema_invalid")
                if (symbol, side) in position_names:
                    _block("account_v2_schema_invalid")
                amount = _decimal_text(item.get("positionAmt"))
                if (side == "LONG" and amount < 0) or (side == "SHORT" and amount > 0):
                    _block("account_v2_schema_invalid")
                position_names.add((symbol, side))
        elif resource in {"standard_open_orders", "algo_open_orders"}:
            seen: set[tuple[str, int]] = set()
            for row in page.rows:
                symbol = row.get("symbol")
                if type(symbol) is not str or _SYMBOL.fullmatch(symbol) is None:
                    _block("open_order_schema_invalid")
                key_id = "orderId" if resource == "standard_open_orders" else "algoId"
                order_id = _positive_integer(row.get(key_id))
                if (symbol, order_id) in seen:
                    _block("open_order_schema_invalid")
                seen.add((symbol, order_id))
                side = row.get("side")
                if type(side) is not str or side not in {"BUY", "SELL"}:
                    _block("open_order_schema_invalid")
                if resource == "standard_open_orders":
                    status = row.get("status")
                    if type(status) is not str or status not in {"NEW", "PARTIALLY_FILLED"}:
                        _block("open_order_schema_invalid")
                    _decimal_text(row.get("price"), nonnegative=True)
                    requested = _decimal_text(row.get("origQty"), positive=True)
                    filled = _decimal_text(row.get("executedQty"), nonnegative=True)
                    if filled >= requested:
                        _block("open_order_schema_invalid")
                    if type(row.get("clientOrderId")) is not str or not row["clientOrderId"]:
                        _block("open_order_schema_invalid")
                    if type(row.get("reduceOnly")) is not bool:
                        _block("open_order_schema_invalid")
                    if type(row.get("timeInForce")) is not str or not row["timeInForce"]:
                        _block("open_order_schema_invalid")
                else:
                    status = row.get("algoStatus")
                    if type(status) is not str or status not in {"NEW", "PARTIALLY_FILLED"}:
                        _block("open_order_schema_invalid")
                    if row.get("closePosition") is not False:
                        _block("unsupported_algo_shape")
                    _decimal_text(row.get("price"), nonnegative=True)
                    requested = _decimal_text(row.get("quantity"), positive=True)
                    filled = _decimal_text(row.get("executedQty"), nonnegative=True)
                    if filled >= requested:
                        _block("open_order_schema_invalid")
                    if type(row.get("clientAlgoId")) is not str or not row["clientAlgoId"]:
                        _block("open_order_schema_invalid")
                    if type(row.get("reduceOnly")) is not bool:
                        _block("open_order_schema_invalid")
                    if type(row.get("timeInForce")) is not str or not row["timeInForce"]:
                        _block("open_order_schema_invalid")


def _read_all_orders_bisected(
    reader: Any,
    start_ms: int,
    cutoff_ms: int,
) -> tuple[tuple[CandidatePageV1, ...], tuple[dict[str, Any], ...]]:
    target_end = cutoff_ms - 1
    pages: list[CandidatePageV1] = []
    selected: dict[tuple[str, int], dict[str, Any]] = {}
    stack: list[tuple[int, int, int]] = [(start_ms, target_end, 0)]
    while stack:
        if len(pages) >= MAX_REQUESTS:
            _block("all_orders_page_budget_exceeded")
        lo, hi, depth = stack.pop()
        if depth > 32 or lo > hi:
            _block("all_orders_bisection_invalid")
        # Padding by one millisecond on both sides covers either inclusive or
        # exclusive provider bounds while the private row-time check preserves
        # the requested half-open evidence window.
        page = reader.all_orders(lo - 1, hi + 1)
        if type(page) is not CandidatePageV1 or page._seal is not _READ_SESSION_SEAL:
            _block("all_orders_page_binding_invalid")
        pages.append(page)
        if page.resource != "all_orders_in_window" or len(page.rows) > PAGE_LIMIT:
            _block("all_orders_page_shape_invalid")
        for row in page.rows:
            when = row.get("time")
            if type(when) is not int or not lo - 1 <= when <= hi + 1:
                _block("all_orders_row_time_invalid")
            if (
                type(row.get("symbol")) is not str
                or _SYMBOL.fullmatch(row["symbol"]) is None
                or type(row.get("orderId")) is not int
                or row["orderId"] <= 0
                or type(row.get("status")) is not str
                or type(row.get("side")) is not str
                or type(row.get("type")) is not str
                or type(row.get("origQty")) is not str
                or type(row.get("executedQty")) is not str
            ):
                _block("all_orders_row_shape_invalid")
            _decimal_text(row.get("origQty"), nonnegative=True)
            _decimal_text(row.get("executedQty"), nonnegative=True)
        if len(page.rows) == PAGE_LIMIT:
            if lo == hi:
                _block("all_orders_one_ms_saturated")
            mid = (lo + hi) // 2
            if mid >= hi:
                _block("all_orders_bisection_stalled")
            # Stack is LIFO; append right first to collect left before right.
            stack.append((mid + 1, hi, depth + 1))
            stack.append((lo, mid, depth + 1))
            continue
        for row in page.rows:
            when = row.get("time")
            if not start_ms <= when < cutoff_ms:
                continue
            symbol, order_id = row.get("symbol"), row.get("orderId")
            if type(symbol) is not str or _SYMBOL.fullmatch(symbol) is None or type(order_id) is not int or order_id <= 0:
                _block("all_orders_identity_invalid")
            key = (symbol, order_id)
            previous = selected.get(key)
            if previous is not None and previous != row:
                _block("all_orders_conflicting_duplicate")
            selected[key] = row
    return tuple(pages), tuple(selected[key] for key in sorted(selected))


def _read_income_pages(reader: Any, start_ms: int, cutoff_ms: int) -> tuple[tuple[CandidatePageV1, ...], tuple[dict[str, Any], ...]]:
    pages: list[CandidatePageV1] = []
    selected: dict[tuple[str, int, str, int], dict[str, Any]] = {}
    page_number = 1
    while page_number <= MAX_REQUESTS:
        page = reader.income(start_ms, cutoff_ms - 1, page_number)
        if type(page) is not CandidatePageV1 or page._seal is not _READ_SESSION_SEAL:
            _block("income_page_binding_invalid")
        pages.append(page)
        if page.resource != "income_in_window" or len(page.rows) > PAGE_LIMIT:
            _block("income_page_shape_invalid")
        for row in page.rows:
            when = row.get("time")
            if type(when) is not int or not start_ms <= when < cutoff_ms:
                _block("income_row_outside_window")
            kind, entry_id, asset = row.get("incomeType"), row.get("tranId"), row.get("asset")
            if type(kind) is not str or not kind or type(entry_id) is not int or entry_id <= 0 or type(asset) is not str or not asset:
                _block("income_identity_invalid")
            _decimal_text(row.get("income"))
            symbol = row.get("symbol")
            if symbol not in (None, "") and (type(symbol) is not str or _SYMBOL.fullmatch(symbol) is None):
                _block("income_symbol_invalid")
            key = (kind, entry_id, asset, when)
            previous = selected.get(key)
            if previous is not None and previous != row:
                _block("income_conflicting_duplicate")
            selected[key] = row
        if len(page.rows) < PAGE_LIMIT:
            return tuple(pages), tuple(selected[key] for key in sorted(selected))
        page_number += 1
    _block("income_page_budget_exceeded")


def _read_user_trade_pages(
    reader: Any,
    symbol: str,
    start_ms: int,
    cutoff_ms: int,
) -> tuple[tuple[CandidatePageV1, ...], tuple[dict[str, Any], ...]]:
    pages: list[CandidatePageV1] = []
    selected: dict[tuple[str, int], dict[str, Any]] = {}
    cursor: int | None = None
    prior_id = 0
    for _ in range(MAX_REQUESTS):
        if cursor is None:
            # One millisecond padding handles endpoint boundary convention;
            # padding rows are retained only in private source pages.
            page = reader.user_trades(symbol, start_ms - 1, cutoff_ms, None)
        else:
            # Binance forbids mixing fromId with either time bound.
            page = reader.user_trades(symbol, 0, 0, cursor)
        if type(page) is not CandidatePageV1 or page._seal is not _READ_SESSION_SEAL:
            _block("user_trades_page_binding_invalid")
        pages.append(page)
        if page.resource != "user_trades_in_window" or len(page.rows) > PAGE_LIMIT:
            _block("user_trades_page_shape_invalid")
        page_ids: list[int] = []
        page_seen: set[int] = set()
        for row in page.rows:
            if row.get("symbol") != symbol:
                _block("user_trades_symbol_mismatch")
            trade_id, when = row.get("id"), row.get("time")
            if type(trade_id) is not int or trade_id <= 0 or type(when) is not int or trade_id in page_seen:
                _block("user_trades_order_invalid")
            if trade_id <= prior_id:
                if cursor is not None and trade_id < cursor:
                    _block("user_trades_cursor_regressed")
                _block("user_trades_order_invalid")
            page_seen.add(trade_id)
            prior_id = trade_id
            if when < start_ms - 1 or when > cutoff_ms:
                _block("user_trades_row_outside_window")
            if type(row.get("orderId")) is not int or row["orderId"] <= 0:
                _block("user_trades_order_invalid")
            side, position_side = row.get("side"), row.get("positionSide")
            if (
                type(side) is not str
                or side not in {"BUY", "SELL"}
                or type(position_side) is not str
                or position_side not in {"BOTH", "LONG", "SHORT"}
            ):
                _block("user_trades_schema_invalid")
            _decimal_text(row.get("qty"), positive=True)
            _decimal_text(row.get("price"), positive=True)
            _decimal_text(row.get("commission"), nonnegative=True)
            _decimal_text(row.get("realizedPnl"))
            if type(row.get("commissionAsset")) is not str or not row["commissionAsset"]:
                _block("user_trades_schema_invalid")
            page_ids.append(trade_id)
            if start_ms <= when < cutoff_ms:
                key = (symbol, trade_id)
                previous = selected.get(key)
                if previous is not None and previous != row:
                    _block("user_trades_conflicting_duplicate")
                selected[key] = row
        if len(page.rows) < PAGE_LIMIT:
            return tuple(pages), tuple(selected[key] for key in sorted(selected))
        if not page_ids:
            _block("user_trades_cursor_missing")
        next_cursor = max(page_ids) + 1
        if next_cursor <= (cursor or 0) or next_cursor >= 2**63:
            _block("user_trades_cursor_stalled")
        cursor = next_cursor
    _block("user_trades_page_budget_exceeded")


def collect_account_window_candidate(
    reader: Any,
    *,
    invocation_ref: str,
    evidence_window_ref: str,
    history_start_ms: int,
    phase_cutoff_ms: int,
) -> CandidateAssessmentV1:
    """Collect one fixed-route candidate; no coverage claim is minted here."""
    if (
        type(invocation_ref) is not str
        or _HEX32.fullmatch(invocation_ref) is None
        or type(evidence_window_ref) is not str
        or evidence_window_ref != "th01-window:" + invocation_ref
        or type(history_start_ms) is not int
        or type(phase_cutoff_ms) is not int
        or not 0 < history_start_ms < phase_cutoff_ms
        or phase_cutoff_ms - history_start_ms > MAX_WINDOW_MS
        or phase_cutoff_ms - history_start_ms > MAX_AGE_MS
    ):
        _block("account_window_binding_invalid")
    pages: dict[str, tuple[CandidatePageV1, ...]] = {}
    for resource in CURRENT_ROUTES:
        pages[resource] = (reader.current(resource),)
    _validate_current_pages(pages)
    all_order_pages, all_order_rows = _read_all_orders_bisected(reader, history_start_ms, phase_cutoff_ms)
    pages["all_orders_in_window"] = all_order_pages
    income_pages, income_rows = _read_income_pages(reader, history_start_ms, phase_cutoff_ms)
    pages["income_in_window"] = income_pages
    account = pages["account_v2"][0].rows[0]
    symbols: set[str] = set()
    for row in account["positions"]:
        symbol, amount = row.get("symbol"), row.get("positionAmt")
        if type(symbol) is not str or _SYMBOL.fullmatch(symbol) is None or type(amount) is not str:
            _block("account_position_symbol_invalid")
        active = _decimal_text(amount) != 0
        if active:
            symbols.add(symbol)
    for resource in ("standard_open_orders", "algo_open_orders"):
        for row in pages[resource][0].rows:
            symbol = row.get("symbol")
            if type(symbol) is not str or _SYMBOL.fullmatch(symbol) is None:
                _block("open_order_symbol_invalid")
            symbols.add(symbol)
    for row in all_order_rows:
        symbols.add(row["symbol"])
    for row in income_rows:
        symbol = row.get("symbol")
        if type(symbol) is str and symbol:
            if _SYMBOL.fullmatch(symbol) is None:
                _block("income_symbol_invalid")
            symbols.add(symbol)
    trades: dict[str, tuple[dict[str, Any], ...]] = {}
    for symbol in sorted(symbols):
        trade_pages, trade_rows = _read_user_trade_pages(
            reader, symbol, history_start_ms, phase_cutoff_ms
        )
        pages["user_trades_in_window:" + symbol] = trade_pages
        trades[symbol] = trade_rows
    account_binding_ref = getattr(reader, "_account_binding_ref", None)
    if type(account_binding_ref) is not str or _HEX64.fullmatch(account_binding_ref) is None:
        _block("account_window_reader_binding_invalid")
    seen_refs: set[str] = set()
    for name, page_group in pages.items():
        expected_resource = name.split(":", 1)[0]
        for page in page_group:
            if (
                type(page) is not CandidatePageV1
                or page._seal is not _READ_SESSION_SEAL
                or page.resource != expected_resource
                or page._invocation_id != invocation_ref
                or page._evidence_window_id != evidence_window_ref
                or page._account_binding_ref != account_binding_ref
                or type(page.request_ref) is not str
                or _HEX32.fullmatch(page.request_ref) is None
                or type(page.response_ref) is not str
                or _HEX32.fullmatch(page.response_ref) is None
                or page.request_ref == page.response_ref
                or page.request_ref in seen_refs
                or page.response_ref in seen_refs
            ):
                _block("account_window_page_binding_invalid")
            parsed_rows = _rows_for_resource(page.resource, page.response_body)
            if parsed_rows != page.rows:
                _block("account_window_page_body_binding_invalid")
            seen_refs.update((page.request_ref, page.response_ref))
    return CandidateAssessmentV1(
        invocation_ref=invocation_ref,
        evidence_window_ref=evidence_window_ref,
        history_start_ms=history_start_ms,
        phase_cutoff_ms=phase_cutoff_ms,
        pages=pages,
        candidate_symbols=tuple(sorted(symbols)),
        all_orders_rows=all_order_rows,
        income_rows=income_rows,
        user_trade_rows=trades,
        all_orders_time_partition_scan_completed=True,
        income_short_page_terminal_observed=True,
        candidate_symbol_user_trades_short_page_terminal_observed=True,
        user_trades_universe_closed=False,
        # Binance account V2's updateTime is explicitly reserved/ignored.
        provider_watermark_finality=False,
        _account_binding_ref=account_binding_ref,
        _seal=_READ_SESSION_SEAL,
    )


_PUBLIC_FAILURE_CATEGORIES = {
    "source_preflight": frozenset({
        "source_root_unavailable", "source_root_mismatch", "source_ancestor_unavailable",
        "source_ancestor_shape_invalid", "source_unavailable", "source_shape_invalid",
        "source_changed_before_read", "source_changed_during_read", "source_close_failed",
        "source_pin_mismatch", "source_module_input_invalid", "source_module_load_failed",
        "owner_transport_unavailable", "owner_transport_source_binding_invalid",
        "candidate_source_binding_invalid",
    }),
    "window_validation": frozenset({"root_window_invalid", "account_window_binding_invalid"}),
    "protected_credential_read": frozenset({"protected_reader_failed", "protected_reader_credential_shape"}),
    "protected_evidence_write": frozenset({
        "root_local_app_data_unavailable", "protected_writer_unavailable",
        "protected_writer_binding_invalid", "protected_capture_write_failed",
        "protected_capture_write_unverified",
    }),
    "fixed_get_transport_or_response": frozenset({
        "fixed_get_auth_binding_invalid", "fixed_get_query_forbidden", "fixed_get_capture_budget_reached",
        "fixed_get_request_budget_reached", "fixed_get_route_rejected", "fixed_get_transport_unproven",
        "fixed_get_provider_response_unproven", "fixed_get_body_budget_reached",
        "fixed_get_timestamp_invalid", "fixed_get_row_budget_reached",
    }),
    "provider_response_shape": frozenset({
        "provider_body_invalid", "provider_duplicate_json_key", "provider_nonfinite_json",
        "provider_json_invalid", "provider_account_shape_invalid", "provider_rows_shape_invalid",
        "provider_decimal_shape_invalid", "provider_decimal_range_invalid",
        "provider_integer_shape_invalid", "account_configuration_schema_invalid",
        "account_v2_schema_invalid", "open_order_schema_invalid", "unsupported_algo_shape",
        "all_orders_row_time_invalid", "all_orders_row_shape_invalid", "income_row_outside_window",
        "income_identity_invalid", "income_symbol_invalid", "user_trades_row_outside_window",
        "user_trades_order_invalid", "user_trades_schema_invalid", "user_trades_time_regressed",
    }),
    "all_orders_window_scan": frozenset({
        "all_orders_bisection_invalid", "all_orders_page_binding_invalid", "all_orders_page_shape_invalid",
        "all_orders_one_ms_saturated", "all_orders_bisection_stalled", "all_orders_identity_invalid",
        "all_orders_conflicting_duplicate", "all_orders_page_budget_exceeded",
    }),
    "income_window_scan": frozenset({
        "income_page_binding_invalid", "income_page_shape_invalid", "income_conflicting_duplicate",
        "income_page_budget_exceeded",
    }),
    "user_trades_candidate_scan": frozenset({
        "user_trades_page_binding_invalid", "user_trades_page_shape_invalid", "user_trades_symbol_mismatch",
        "user_trades_cursor_missing", "user_trades_cursor_stalled", "user_trades_conflicting_duplicate",
        "user_trades_cursor_regressed", "user_trades_page_budget_exceeded", "fixed_get_symbol_rejected",
        "fixed_get_cursor_rejected",
    }),
}


def _public_failure_stage(code: str, auth: RootFixedGetAuthorizationV1 | None) -> tuple[str, str]:
    for stage, codes in _PUBLIC_FAILURE_CATEGORIES.items():
        if code in codes:
            if stage in {"fixed_get_transport_or_response", "provider_response_shape"} and auth is not None:
                active = auth._active_stage[0]
                if active in {*CURRENT_ROUTES, *HISTORY_ROUTES}:
                    return active, stage
            if stage == "all_orders_window_scan":
                return "all_orders_in_window", stage
            if stage == "income_window_scan":
                return "income_in_window", stage
            if stage == "user_trades_candidate_scan":
                return "user_trades_in_window", stage
            return stage, stage
    return (auth._active_stage[0] if auth is not None else "root_preflight", "unexpected_failure")


def _blocked_public_projection(
    code: str,
    auth: RootFixedGetAuthorizationV1 | None,
    *,
    account_read_started: bool,
) -> dict[str, Any]:
    stage, category = _public_failure_stage(code, auth)
    return {
        "schema": "iteration41.binance.th01.account-window-candidate-public.r2",
        "status": "BLOCKED_ACCOUNT_SNAPSHOT",
        "first_failure": {"stage": stage, "category": category},
        "account_read_started": bool(account_read_started),
        "completed_route_observations": {
            resource: bool(auth and auth._route_completed.get(resource, 0))
            for resource in (*CURRENT_ROUTES, *HISTORY_ROUTES)
        },
        "route_page_completion_counts": {
            resource: auth._route_completed.get(resource, 0) if auth else 0
            for resource in (*CURRENT_ROUTES, *HISTORY_ROUTES)
        },
        "user_trades_completed_page_count": sum(
            count for resource, count in (auth._route_completed.items() if auth else ())
            if resource == "user_trades_in_window"
        ),
        "account_full_snapshot_issued": False,
        "formal_case_pass": False,
        "false_completion_means_request_absent": False,
    }


def account_full_attestation(candidate: CandidateAssessmentV1, coverage: object) -> object:
    """Fail closed until a separate provider-bound coverage issuer is reviewed.

    This collector produces a bounded candidate only. Caller booleans, local
    symbol unions and opaque references are not account-full evidence, so this
    round deliberately has no coverage object that can be minted here.
    """
    if type(candidate) is not CandidateAssessmentV1 or candidate._seal is not _READ_SESSION_SEAL:
        _block("candidate_assessment_binding_invalid")
    _block("account_full_attestation_unproven")


def create_root_read_candidate(
    *,
    history_start_ms: int,
    phase_cutoff_ms: int,
) -> CandidateAssessmentV1:
    """Root entry: preflight, protected credential read, private writer, GETs.

    Caller must be the pinned `scripts` driver. No credential, path, HTTP
    callback, or writer is accepted as a parameter. This function was not run
    during source implementation or QA.
    """
    account_read_started = False
    auth: RootFixedGetAuthorizationV1 | None = None
    credentials: dict[str, Any] | None = None
    owner_namespace = sys.modules.get("__main__")
    try:
        candidate_source_sha256 = _verify_candidate_source_binding()
        sources = load_verified_read_sources(owner_namespace)
    except AccountWindowBlocked as exc:
        exc.public_projection = _blocked_public_projection(exc.code, None, account_read_started=False)
        raise
    try:
        if not (getattr(owner_namespace, "__name__", None) == "__main__"):
            _block("root_driver_required")
        if os.name != "nt":
            _block("windows_root_required")
        now_ms = int(time.time() * 1000)
        if (
            type(history_start_ms) is not int
            or type(phase_cutoff_ms) is not int
            or not 0 < history_start_ms < phase_cutoff_ms
            or phase_cutoff_ms > now_ms - 2000
            or now_ms - phase_cutoff_ms > 120_000
            or phase_cutoff_ms - history_start_ms > MAX_WINDOW_MS
            or now_ms - history_start_ms > MAX_AGE_MS
        ):
            _block("root_window_invalid")
    except AccountWindowBlocked as exc:
        exc.public_projection = _blocked_public_projection(exc.code, None, account_read_started=False)
        raise
    # The only credential read is the unchanged tracked, bounded Windows
    # helper. It also checks ignored .env provenance under locked handles.
    env_path = ROOT / ".env"
    try:
        credentials, _unused = sources.cli.protected_env(env_path, None, sources.private)
    except Exception as exc:
        blocked = AccountWindowBlocked("protected_reader_failed")
        blocked.public_projection = _blocked_public_projection(
            blocked.code, None, account_read_started=False
        )
        raise blocked from None
    try:
        account_ref = _account_binding_ref(credentials)
        api_key, secret = credentials["api_key"], credentials["secret"]
        invocation = uuid4().hex
        evidence_window = "th01-window:" + invocation
        local_app_data = os.environ.get("LOCALAPPDATA")
        if type(local_app_data) is not str or not local_app_data:
            _block("root_local_app_data_unavailable")
        directory = sources.private.create_private_directory(
            Path(local_app_data) / ("bt-iteration41-th01-window-" + invocation)
        )
        if type(directory) is not getattr(sources.private, "PrivateArtifactDirectory", None):
            _block("protected_writer_unavailable")
        directory.verify()
        writer = ProtectedCaptureWriterV1(
            invocation_id=invocation,
            directory=directory,
            _sequence=[0],
            _private_module=sources.private,
            _seal=_PRIVATE_CAPTURE_SEAL,
        )
        auth = RootFixedGetAuthorizationV1(
            invocation_id=invocation,
            evidence_window_id=evidence_window,
            history_start_ms=history_start_ms,
            phase_cutoff_ms=phase_cutoff_ms,
            account_binding_ref=account_ref,
            _credential_box=[api_key, secret],
            _writer=writer,
            _sources=sources,
            _started_monotonic=time.monotonic(),
            _request_count=[0],
            _row_count=[0],
            _body_bytes=[0],
            _route_entries={},
            _route_completed={},
            _active_stage=["root_preflight"],
            _seal=_READ_AUTH_SEAL,
        )
        reader = FixedGetReaderV1(auth, _READ_SESSION_SEAL)
        account_read_started = True
        candidate = collect_account_window_candidate(
            reader,
            invocation_ref=invocation,
            evidence_window_ref=evidence_window,
            history_start_ms=history_start_ms,
            phase_cutoff_ms=phase_cutoff_ms,
        )
        _verify_postflight_sources(candidate_source_sha256, sources.source_hashes)
        return candidate
    except AccountWindowBlocked as exc:
        exc.public_projection = _blocked_public_projection(
            exc.code, auth, account_read_started=account_read_started
        )
        raise
    except Exception:
        blocked = AccountWindowBlocked("account_window_blocked")
        blocked.public_projection = _blocked_public_projection(
            blocked.code, auth, account_read_started=account_read_started
        )
        raise blocked from None
    finally:
        # Keep provider credentials out of retained Root session objects.
        _clear_root_credentials(auth, credentials)
        api_key = ""
        secret = ""


def _clear_root_credentials(
    auth: RootFixedGetAuthorizationV1 | None,
    credentials: dict[str, Any] | None,
) -> None:
    if type(auth) is RootFixedGetAuthorizationV1 and type(auth._credential_box) is list:
        for index in range(len(auth._credential_box)):
            auth._credential_box[index] = ""
    if type(credentials) is dict:
        credentials.clear()


__all__ = [
    "AccountWindowBlocked",
    "CandidateAssessmentV1",
    "CandidatePageV1",
    "FixedGetReaderV1",
    "RootFixedGetAuthorizationV1",
    "account_full_attestation",
    "collect_account_window_candidate",
    "create_root_read_candidate",
    "load_verified_read_sources",
    "source_preflight",
]
