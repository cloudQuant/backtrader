"""Content-only validation for a same-call C01 worker receipt and snapshots.

This module deliberately uses only the Python standard library. It validates
the shape and internal joins in a V3 C01 worker receipt plus the two held
snapshot byte strings. It does not authenticate source code, a provider, an
account, custody, or a caller. A successful return is not a C01 certification
result and carries no authority.

The private commitment fields are intended only for a future Root custody
consumer that already established the exact source lease and invocation
scope. They must never be serialized or copied to public evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import ModuleType
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


SCHEMA = "iteration41.simnow.c01.root-ledger-content.v1"
AUTHORITY = "NONE"
CONTENT_STATUS = "CONTENT_VALIDATED_ONLY"
PROTOCOL_NAME = "backtrader.simnow.c01.v2"
PROTOCOL_VERSION = 2
WORKER_MESSAGE = "worker_receipt"
PRIVATE_SNAPSHOT_PROTOCOL = "backtrader.simnow.c01.v2"
PRIVATE_SNAPSHOT_VERSION = 2
MAX_PRIVATE_SNAPSHOT_BYTES = 8 * 1024 * 1024
MAX_WORKER_FRAME_BYTES = 1024 * 1024
MAX_CALLBACKS = 10_000
SDK_QUERY_RESULT_TYPE = "bt_api_ctp.query.QueryResult"
SDK_QUERY_ERROR_SEMANTICS = "SDK_QUERY_NULL_ERROR_CODE_NO_FAILURE"
RSP_INFO_ERROR_ID_PRESENT = "RSP_INFO_ERROR_ID_PRESENT"
QUERY_EVIDENCE_TTL_SECONDS = 35.0

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
_UTC_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(?:Z|\+00:00)$")
_TRADING_DAY_RE = re.compile(r"^\d{8}$")
_HEX_FLOAT_RE = re.compile(r"^0x[0-9a-f]+(?:\.[0-9a-f]*)?p[+-][0-9]+$")

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
_QUERY_CALLBACKS = {
    "orders": ("ReqQryOrder", "OnRspQryOrder"),
    "positions": ("ReqQryInvestorPosition", "OnRspQryInvestorPosition"),
    "funds": ("ReqQryTradingAccount", "OnRspQryTradingAccount"),
}
_WORKER_KEYS = frozenset(
    {
        "protocol",
        "message_type",
        "version",
        "case_id",
        "run_nonce",
        "parent_pid",
        "worker_pid",
        "worker_source_sha256",
        "pair_binding",
        "account_scope_sha256",
        "credential_binding_sha256",
        "client",
        "requests",
        "callbacks",
        "snapshots",
        "write_counters",
        "native_close",
        "terminal_state",
    }
)
_REQUEST_KEYS = frozenset(
    {
        "kind",
        "phase",
        "family",
        "method",
        "request_id",
        "request_generation",
        "local_sequence",
        "issued_at_utc",
        "issued_monotonic_ns",
        "return_code",
        "sdk_query_result",
        "receipt_origin",
        "account_scope_sha256",
        "credential_binding_sha256",
    }
)
_CALLBACK_KEYS = frozenset(
    {
        "kind",
        "phase",
        "family",
        "callback_name",
        "request_id",
        "error_id",
        "rsp_info_present",
        "error_semantics",
        "is_last",
        "request_generation",
        "client_instance_id",
        "client_generation",
        "arrival_generation",
        "local_sequence",
        "arrived_at_utc",
        "arrived_monotonic_ns",
        "row_present",
        "front_id",
        "session_id",
        "trading_day",
        "account_scope_sha256",
        "credential_binding_sha256",
    }
)
_QUERY_RESULT_KEYS = frozenset(
    {
        "result_type",
        "request_type",
        "request_id",
        "connection_generation",
        "complete",
        "evidence_complete",
        "is_last_seen",
        "timed_out",
        "unsupported",
        "error_code",
        "account_fingerprint",
        "started_at_utc",
        "completed_at_utc",
        "error_message",
        "submit_code",
        "record_count",
        "late_callback_count",
        "error_semantics",
        "records_sha256",
        "callback_records_sha256",
        "query_source",
    }
)
_QUERY_SOURCE_KEYS = frozenset(
    {
        "source_type",
        "seal_valid",
        "issuer_is_client_query_lane",
        "request_type",
        "request_id",
        "account_fingerprint",
        "connection_generation",
        "trading_day",
        "broker_id",
        "investor_id",
        "request_filters",
        "explicit_request_filters",
        "started_at_utc",
        "completed_at_utc",
        "started_monotonic_hex",
        "completed_monotonic_hex",
        "clock_domain_id",
        "records_sha256",
        "trusted_expires_at_utc",
        "trusted_expires_monotonic_hex",
    }
)
_SNAPSHOT_SUMMARY_KEYS = frozenset(
    {
        "phase",
        "artifact_ref",
        "artifact_sha256",
        "client_instance_id",
        "client_generation",
        "arrival_generation",
        "session_id",
        "trading_day",
        "queries",
        "open_order_refs_sha256",
        "order_economics_sha256",
        "positions_sha256",
        "funds_sha256",
        "account_scope_sha256",
        "credential_binding_sha256",
    }
)
_SNAPSHOT_QUERY_SUMMARY_KEYS = frozenset(
    {"request_id", "callback_count", "row_count", "first_sequence", "terminal_sequence"}
)
_SNAPSHOT_KEYS = frozenset(
    {
        "protocol",
        "version",
        "case_id",
        "phase",
        "account_scope_sha256",
        "credential_binding_sha256",
        "client",
        "scope",
        "queries",
        "projections",
    }
)
_SNAPSHOT_CLIENT_KEYS = frozenset({"instance_id", "client_generation", "arrival_generation"})
_SNAPSHOT_SCOPE_KEYS = frozenset({"front_id", "session_id", "trading_day"})
_SNAPSHOT_QUERY_KEYS = frozenset({"request", "callbacks"})
_ARTIFACT_REQUEST_KEYS = frozenset(
    {
        "method",
        "request_id",
        "request_generation",
        "local_sequence",
        "issued_at_utc",
        "issued_monotonic_ns",
        "return_code",
        "sdk_query_result",
    }
)
_ARTIFACT_CALLBACK_KEYS = frozenset(
    {
        "callback_name",
        "request_id",
        "error_id",
        "rsp_info_present",
        "error_semantics",
        "is_last",
        "request_generation",
        "local_sequence",
        "arrived_at_utc",
        "arrived_monotonic_ns",
        "row_present",
        "row",
    }
)
_PROJECTION_KEYS = frozenset({"open_order_refs", "order_economics", "positions", "funds"})
_SUMMARY_PROJECTION_DIGESTS = (
    ("open_order_refs", "open_order_refs_sha256"),
    ("order_economics", "order_economics_sha256"),
    ("positions", "positions_sha256"),
    ("funds", "funds_sha256"),
)


class C01LedgerContentError(ValueError):
    """A fixed, non-sensitive content-validation failure code."""

    def __init__(self, code: str):
        if type(code) is not str or not re.fullmatch(r"[a-z0-9_]{1,80}", code):
            code = "content_invalid"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class C01RequestFact:
    kind: str
    phase: Optional[str]
    family: Optional[str]
    method: str
    request_id: int
    request_generation: int
    local_sequence: int
    issued_at_utc: str
    issued_monotonic_ns: int
    return_code: int
    client_instance_id: str
    client_generation: int
    arrival_generation: int
    _private_request_sha256: str = field(repr=False)

    def __repr__(self) -> str:
        return "C01RequestFact(<local fields; private commitment redacted>)"


@dataclass(frozen=True, repr=False)
class C01CallbackFact:
    kind: str
    phase: Optional[str]
    family: Optional[str]
    callback_name: str
    request_id: int
    request_generation: int
    error_id: int
    rsp_info_present: bool
    is_last: bool
    local_sequence: int
    arrived_at_utc: str
    arrived_monotonic_ns: int
    row_present: Optional[bool]
    front_id: Optional[int]
    session_id: Optional[str]
    trading_day: Optional[str]

    def __repr__(self) -> str:
        return "C01CallbackFact(<native/local fields; private identity redacted>)"


@dataclass(frozen=True, repr=False)
class C01QueryReceiptContent:
    phase: str
    family: str
    method: str
    request_id: int
    request_generation: int
    client_instance_id: str
    client_generation: int
    arrival_generation: int
    request_local_sequence: int
    request_issued_at_utc: str
    request_issued_monotonic_ns: int
    send_return_code: int
    callback_count: int
    row_count: int
    first_callback_local_sequence: int
    terminal_callback_local_sequence: int
    terminal_arrived_at_utc: str
    terminal_arrived_monotonic_ns: int
    terminal_error_id: int
    terminal_is_last: bool
    sdk_complete: bool
    sdk_evidence_complete: bool
    sdk_is_last_seen: bool
    sdk_timed_out: bool
    sdk_unsupported: bool
    sdk_late_callback_count: int
    _private_query_sha256: str = field(repr=False)

    def __repr__(self) -> str:
        return "C01QueryReceiptContent(<fixed query facts; private commitment redacted>)"


@dataclass(frozen=True, repr=False)
class C01SnapshotQueryFact:
    family: str
    request_id: int
    callback_count: int
    row_count: int
    first_callback_local_sequence: int
    terminal_callback_local_sequence: int

    def __repr__(self) -> str:
        return "C01SnapshotQueryFact(<private query join redacted>)"


@dataclass(frozen=True, repr=False)
class C01SnapshotFact:
    phase: str
    artifact_ref: str
    artifact_size_bytes: int
    client_instance_id: str
    client_generation: int
    arrival_generation: int
    front_id: int
    session_id: str
    trading_day: str
    queries: Tuple[C01SnapshotQueryFact, ...]
    _artifact_sha256: str = field(repr=False)
    _projection_sha256: Tuple[Tuple[str, str], ...] = field(repr=False)

    def __repr__(self) -> str:
        return "C01SnapshotFact(<private snapshot identity and commitments redacted>)"


@dataclass(frozen=True, repr=False)
class C01ValidatedContent:
    """Immutable content facts; this type never represents trust or PASS."""

    requests: Tuple[C01RequestFact, ...]
    callbacks: Tuple[C01CallbackFact, ...]
    query_receipts: Tuple[C01QueryReceiptContent, ...]
    request_count: int
    auth_login_callback_count: int
    query_request_count: int
    query_callback_count: int
    snapshot_count: int
    _snapshot_facts: Tuple[C01SnapshotFact, ...] = field(repr=False)
    activity_callback_count: int
    write_invocation_count: int
    native_close_complete: bool
    native_released: bool
    native_thread_alive: bool
    native_timed_out: bool
    provider_source_sequence: int
    authority: str
    status: str
    certification_pass: bool
    source_authenticity_verified: bool
    _content_commitment_sha256: str = field(repr=False)
    _baseline_artifact_sha256: str = field(repr=False)
    _final_artifact_sha256: str = field(repr=False)

    def __repr__(self) -> str:
        return (
            "C01ValidatedContent(<content only; 8 requests, 2 auth/login callbacks, "
            "6 query requests, private commitments redacted>)"
        )

    def safe_summary(self) -> Dict[str, Any]:
        """Return fixed counters and non-authority flags only."""

        return {
            "schema": SCHEMA,
            "status": self.status,
            "authority": self.authority,
            "certification_pass": self.certification_pass,
            "source_authenticity_verified": self.source_authenticity_verified,
            "provider_source_sequence": self.provider_source_sequence,
            "request_count": self.request_count,
            "auth_login_callback_count": self.auth_login_callback_count,
            "query_request_count": self.query_request_count,
            "query_callback_count": self.query_callback_count,
            "snapshot_count": self.snapshot_count,
            "activity_callback_count": self.activity_callback_count,
            "write_invocation_count": self.write_invocation_count,
            "native_close_complete": self.native_close_complete,
            "native_released": self.native_released,
            "native_thread_alive": self.native_thread_alive,
            "native_timed_out": self.native_timed_out,
        }


def validate_c01_ledger_content_v1(
    worker: Dict[str, Any],
    private_artifacts: Dict[str, bytes],
    *,
    protocol_module: ModuleType,
    worker_module: ModuleType,
    expected_worker_source_sha256: str,
    expected_protocol_source_sha256: str,
    expected_worker_module_source_sha256: str,
    expected_pair_binding: Dict[str, Any],
    expected_account_scope_sha256: str,
    expected_credential_binding_sha256: str,
) -> C01ValidatedContent:
    """Validate one fixed V3 worker payload and its held baseline/final bytes.

    ``worker`` is the actual typed receipt's ``to_dict()`` projection;
    ``private_artifacts`` is the exact in-memory mapping held by the caller.
    This function never opens paths and does not verify who supplied either
    argument. The caller must keep source pin, Root scope, and physical custody
    checks separate.
    """

    try:
        return _validate(
            worker,
            private_artifacts,
            protocol_module=protocol_module,
            worker_module=worker_module,
            expected_worker_source_sha256=expected_worker_source_sha256,
            expected_protocol_source_sha256=expected_protocol_source_sha256,
            expected_worker_module_source_sha256=expected_worker_module_source_sha256,
            expected_pair_binding=expected_pair_binding,
            expected_account_scope_sha256=expected_account_scope_sha256,
            expected_credential_binding_sha256=expected_credential_binding_sha256,
        )
    except C01LedgerContentError:
        raise
    except Exception:
        raise C01LedgerContentError("content_invalid") from None


def _validate(
    worker: Dict[str, Any],
    private_artifacts: Dict[str, bytes],
    *,
    protocol_module: ModuleType,
    worker_module: ModuleType,
    expected_worker_source_sha256: str,
    expected_protocol_source_sha256: str,
    expected_worker_module_source_sha256: str,
    expected_pair_binding: Dict[str, Any],
    expected_account_scope_sha256: str,
    expected_credential_binding_sha256: str,
) -> C01ValidatedContent:
    _validate_source_modules(protocol_module, worker_module)
    worker_input = _exact_dict(worker, "worker_invalid")
    artifacts = _exact_dict(private_artifacts, "artifacts_invalid")
    pair_binding_input = _exact_dict(expected_pair_binding, "pair_binding_invalid")
    _json_value(pair_binding_input, "pair_binding_invalid")
    worker_canonical = _canonical_json_bytes(worker_input, "worker_shape_invalid")
    if len(worker_canonical) + 1 > MAX_WORKER_FRAME_BYTES:
        _fail("worker_shape_invalid")
    try:
        worker_frame = protocol_module.encode_worker_frame(worker_input)
        worker_receipt = protocol_module.parse_worker_frame(worker_frame)
        if type(worker_receipt) is not protocol_module.C01WorkerReceipt:
            _fail("worker_protocol_invalid")
        worker_dict = worker_receipt.to_dict()
    except C01LedgerContentError:
        raise
    except Exception:
        _fail("worker_protocol_invalid")
    pair_binding = json.loads(
        _canonical_json_bytes(pair_binding_input, "pair_binding_invalid").decode("utf-8")
    )
    _sha256(expected_worker_source_sha256, "expected_worker_source_invalid")
    _sha256(expected_protocol_source_sha256, "expected_protocol_source_invalid")
    _sha256(expected_worker_module_source_sha256, "expected_worker_module_source_invalid")
    _sha256(expected_account_scope_sha256, "expected_account_scope_invalid")
    _sha256(expected_credential_binding_sha256, "expected_credential_binding_invalid")
    if set(artifacts) != {"snapshots/baseline.json", "snapshots/final.json"}:
        _fail("artifacts_invalid")
    baseline_bytes = artifacts["snapshots/baseline.json"]
    final_bytes = artifacts["snapshots/final.json"]
    if type(baseline_bytes) is not bytes or type(final_bytes) is not bytes:
        _fail("artifacts_invalid")

    _require_keys(worker_dict, _WORKER_KEYS, "worker_shape_invalid")
    _json_value(worker_dict, "worker_shape_invalid")
    if (
        worker_dict["protocol"] != PROTOCOL_NAME
        or worker_dict["message_type"] != WORKER_MESSAGE
        or type(worker_dict["version"]) is not int
        or worker_dict["version"] != PROTOCOL_VERSION
        or worker_dict["case_id"] != "C01"
        or worker_dict["terminal_state"] != "normal"
    ):
        _fail("worker_identity_invalid")
    if type(worker_dict["run_nonce"]) is not str or not _HEX32_RE.fullmatch(
        worker_dict["run_nonce"]
    ):
        _fail("worker_identity_invalid")
    parent_pid = _positive_int(worker_dict["parent_pid"], "worker_identity_invalid")
    worker_pid = _positive_int(worker_dict["worker_pid"], "worker_identity_invalid")
    if parent_pid == worker_pid:
        _fail("worker_identity_invalid")
    if worker_dict["worker_source_sha256"] != expected_worker_source_sha256:
        _fail("worker_source_binding_invalid")
    _validate_pair_ref(pair_binding)
    if _canonical_json_bytes(
        worker_dict["pair_binding"], "worker_pair_binding_invalid"
    ) != _canonical_json_bytes(pair_binding, "pair_binding_invalid"):
        _fail("worker_pair_binding_invalid")
    if worker_dict["account_scope_sha256"] != expected_account_scope_sha256:
        _fail("worker_account_binding_invalid")
    if worker_dict["credential_binding_sha256"] != expected_credential_binding_sha256:
        _fail("worker_credential_binding_invalid")

    client = _exact_dict(worker_dict["client"], "client_invalid")
    _require_keys(
        client, {"instance_id", "client_generation", "arrival_generation"}, "client_invalid"
    )
    client_id = _nonempty_string(client["instance_id"], "client_invalid", maximum=128)
    if not _HEX32_RE.fullmatch(client_id):
        _fail("client_invalid")
    client_generation = _positive_int(client["client_generation"], "client_invalid")
    arrival_generation = _positive_int(client["arrival_generation"], "client_invalid")
    requests_raw = worker_dict["requests"]
    if type(requests_raw) is not list or len(requests_raw) != len(_REQUEST_PLAN):
        _fail("request_plan_invalid")
    requests_by_key: Dict[Tuple[str, Optional[str], Optional[str]], Dict[str, Any]] = {}
    requests_by_id: Dict[int, Dict[str, Any]] = {}
    request_facts: List[C01RequestFact] = []
    query_identities_by_key: Dict[
        Tuple[str, Optional[str], Optional[str]], Tuple[str, str, str, str]
    ] = {}
    seen_request_ids: Set[int] = set()
    seen_request_generations: Set[int] = set()
    previous_request_sequence = 0
    for index, (row_value, expected) in enumerate(zip(requests_raw, _REQUEST_PLAN)):
        row = _exact_dict(row_value, "request_invalid")
        _require_keys(row, _REQUEST_KEYS, "request_shape_invalid")
        kind, phase, family, method = expected
        key = (kind, phase, family)
        if (
            row.get("kind") != kind
            or row.get("phase") != phase
            or row.get("family") != family
            or row.get("method") != method
        ):
            _fail("request_plan_invalid")
        request_id = _positive_int(row["request_id"], "request_identity_invalid")
        generation = _positive_int(row["request_generation"], "request_identity_invalid")
        sequence = _positive_int(row["local_sequence"], "request_sequence_invalid")
        if (
            request_id in seen_request_ids
            or generation in seen_request_generations
            or generation != index + 1
            or sequence <= previous_request_sequence
        ):
            _fail("request_identity_invalid")
        issued_at = _nonempty_string(row["issued_at_utc"], "request_time_invalid", maximum=40)
        _utc_ns(issued_at, "request_time_invalid")
        issued_monotonic_ns = _positive_int(row["issued_monotonic_ns"], "request_time_invalid")
        if type(row["return_code"]) is not int or row["return_code"] != 0:
            _fail("request_return_code_invalid")
        # This fixed string is a schema label from the pinned producer. It is
        # checked as content only and never authenticates the producer.
        if row["receipt_origin"] != "local_native_invocation":
            _fail("request_origin_invalid")
        if (
            row["account_scope_sha256"] != expected_account_scope_sha256
            or row["credential_binding_sha256"] != expected_credential_binding_sha256
        ):
            _fail("request_scope_binding_invalid")
        query_result = row["sdk_query_result"]
        query_identity = None
        if kind == "query":
            query_identity = _validate_sdk_query_result(
                query_result,
                family=family,
                request_id=request_id,
                arrival_generation=arrival_generation,
            )
        elif query_result is not None:
            _fail("request_query_result_invalid")
        copied_row = dict(row)
        requests_by_key[key] = copied_row
        requests_by_id[request_id] = copied_row
        seen_request_ids.add(request_id)
        seen_request_generations.add(generation)
        previous_request_sequence = sequence
        request_digest = _sha256_bytes(_canonical_json_bytes(row, "request_digest_invalid"))
        request_facts.append(
            C01RequestFact(
                kind=kind,
                phase=phase,
                family=family,
                method=method,
                request_id=request_id,
                request_generation=generation,
                local_sequence=sequence,
                issued_at_utc=issued_at,
                issued_monotonic_ns=issued_monotonic_ns,
                return_code=0,
                client_instance_id=client_id,
                client_generation=client_generation,
                arrival_generation=arrival_generation,
                _private_request_sha256=request_digest,
            )
        )
        if query_identity is not None:
            # The six private query identities are compared after the native
            # login callback is established below. Do not return them.
            query_identities_by_key[key] = query_identity

    callbacks_raw = worker_dict["callbacks"]
    if type(callbacks_raw) is not list or not 8 <= len(callbacks_raw) <= MAX_CALLBACKS:
        _fail("callback_list_invalid")
    callbacks_by_key: Dict[Tuple[str, Optional[str], Optional[str]], List[Dict[str, Any]]] = {}
    callback_facts: List[C01CallbackFact] = []
    callback_counts = {"authenticate": 0, "login": 0}
    callback_event_by_sequence: Dict[int, Tuple[int, int]] = {}
    previous_callback_sequence = 0
    for value in callbacks_raw:
        callback = _exact_dict(value, "callback_invalid")
        _require_keys(callback, _CALLBACK_KEYS, "callback_shape_invalid")
        kind = callback.get("kind")
        phase = callback.get("phase")
        family = callback.get("family")
        key = (kind, phase, family)
        request = requests_by_key.get(key)
        if request is None or kind not in {"authenticate", "login", "query"}:
            _fail("callback_request_join_invalid")
        request_id = _positive_int(callback["request_id"], "callback_identity_invalid")
        generation = _positive_int(callback["request_generation"], "callback_identity_invalid")
        sequence = _positive_int(callback["local_sequence"], "callback_sequence_invalid")
        if (
            request_id not in requests_by_id
            or request_id != request["request_id"]
            or generation != request["request_generation"]
            or _positive_int(callback["client_generation"], "callback_client_invalid")
            != client_generation
            or _positive_int(callback["arrival_generation"], "callback_client_invalid")
            != arrival_generation
            or callback["client_instance_id"] != client_id
            or callback["account_scope_sha256"] != expected_account_scope_sha256
            or callback["credential_binding_sha256"] != expected_credential_binding_sha256
            or sequence <= request["local_sequence"]
            or sequence <= previous_callback_sequence
        ):
            _fail("callback_request_join_invalid")
        arrived_at = _nonempty_string(
            callback["arrived_at_utc"], "callback_time_invalid", maximum=40
        )
        arrived_utc_ns = _utc_ns(arrived_at, "callback_time_invalid")
        arrived_monotonic_ns = _positive_int(
            callback["arrived_monotonic_ns"], "callback_time_invalid"
        )
        if (
            arrived_utc_ns < _utc_ns(request["issued_at_utc"], "request_time_invalid")
            or arrived_monotonic_ns < request["issued_monotonic_ns"]
        ):
            _fail("callback_clock_precedes_request")
        if callback["rsp_info_present"] is not True:
            _fail("callback_error_facts_invalid")
        if type(callback["error_id"]) is not int or callback["error_id"] != 0:
            _fail("callback_error_facts_invalid")
        if callback["error_semantics"] != RSP_INFO_ERROR_ID_PRESENT:
            _fail("callback_error_facts_invalid")
        if type(callback["is_last"]) is not bool:
            _fail("callback_terminal_invalid")
        if kind in {"authenticate", "login"}:
            callback_counts[kind] += 1
            expected_name = "OnRspAuthenticate" if kind == "authenticate" else "OnRspUserLogin"
            if (
                callback["callback_name"] != expected_name
                or callback["is_last"] is not True
                or callback["row_present"] is not None
            ):
                _fail("auth_login_callback_invalid")
            if kind == "authenticate":
                if any(
                    callback[field] is not None
                    for field in ("front_id", "session_id", "trading_day")
                ):
                    _fail("login_identity_origin_invalid")
            else:
                _positive_int(callback["front_id"], "login_identity_invalid")
                _nonempty_string(callback["session_id"], "login_identity_invalid", maximum=64)
                if not callback["session_id"].isdigit():
                    _fail("login_identity_invalid")
                trading_day = _nonempty_string(
                    callback["trading_day"], "login_identity_invalid", maximum=8
                )
                if not _TRADING_DAY_RE.fullmatch(trading_day):
                    _fail("login_identity_invalid")
        else:
            if (
                family not in _QUERY_CALLBACKS
                or callback["callback_name"] != _QUERY_CALLBACKS[family][1]
                or type(callback["row_present"]) is not bool
                or any(
                    callback[field] is not None
                    for field in ("front_id", "session_id", "trading_day")
                )
            ):
                _fail("query_callback_invalid")
            callbacks_by_key.setdefault(key, []).append(dict(callback))
        callback_event_by_sequence[sequence] = (
            arrived_utc_ns,
            arrived_monotonic_ns,
        )
        callback_facts.append(
            C01CallbackFact(
                kind=kind,
                phase=phase,
                family=family,
                callback_name=callback["callback_name"],
                request_id=request_id,
                request_generation=generation,
                error_id=0,
                rsp_info_present=True,
                is_last=callback["is_last"],
                local_sequence=sequence,
                arrived_at_utc=arrived_at,
                arrived_monotonic_ns=arrived_monotonic_ns,
                row_present=callback["row_present"],
                front_id=callback["front_id"],
                session_id=callback["session_id"],
                trading_day=callback["trading_day"],
            )
        )
        previous_callback_sequence = sequence
    if callback_counts != {"authenticate": 1, "login": 1}:
        _fail("auth_login_callback_count_invalid")

    # Sequence values are local SDK arrival/request sequence values. They are
    # checked globally for uniqueness and monotonic clock consistency, but
    # they are never mapped to a provider-issued source_sequence.
    combined_events: Dict[int, Tuple[int, int]] = {}
    for request in requests_raw:
        sequence = request["local_sequence"]
        combined_events[sequence] = (
            _utc_ns(request["issued_at_utc"], "request_time_invalid"),
            request["issued_monotonic_ns"],
        )
    for callback in callbacks_raw:
        sequence = callback["local_sequence"]
        if sequence in combined_events:
            _fail("local_sequence_duplicate")
        combined_events[sequence] = callback_event_by_sequence[sequence]
    if len(combined_events) != len(requests_raw) + len(callbacks_raw):
        _fail("local_sequence_duplicate")
    previous_utc_ns = -1
    previous_monotonic_ns = -1
    for sequence in sorted(combined_events):
        utc_ns, monotonic_ns = combined_events[sequence]
        if utc_ns < previous_utc_ns or monotonic_ns < previous_monotonic_ns:
            _fail("local_clock_order_invalid")
        previous_utc_ns = utc_ns
        previous_monotonic_ns = monotonic_ns

    login = next(item for item in callback_facts if item.kind == "login")
    auth = next(item for item in callback_facts if item.kind == "authenticate")
    if auth.local_sequence >= login.local_sequence or _utc_ns(
        auth.arrived_at_utc, "callback_time_invalid"
    ) >= _utc_ns(login.arrived_at_utc, "callback_time_invalid"):
        _fail("auth_login_order_invalid")

    for phase in ("baseline", "final"):
        for family in ("orders", "positions", "funds"):
            group = callbacks_by_key.get(("query", phase, family), [])
            if not group:
                _fail("query_callback_group_missing")
            if any(
                callback["is_last"] is not (index == len(group) - 1)
                for index, callback in enumerate(group)
            ):
                _fail("query_callback_terminal_order_invalid")
            if any(
                group[index]["local_sequence"] >= group[index + 1]["local_sequence"]
                for index in range(len(group) - 1)
            ):
                _fail("query_callback_sequence_invalid")

    if len(callbacks_by_key) != 6 or set(callbacks_by_key) != {
        ("query", phase, family)
        for phase in ("baseline", "final")
        for family in ("orders", "positions", "funds")
    }:
        _fail("query_callback_group_invalid")

    # The producer performs each request synchronously through its terminal
    # callback group before issuing the next item in the fixed plan. Bind that
    # serial same-call ordering explicitly, not just each callback to a request.
    for index, expected in enumerate(_REQUEST_PLAN):
        request = requests_by_key[expected[:3]]
        group = (
            [
                callback
                for callback in callback_facts
                if (callback.kind, callback.phase, callback.family) == expected[:3]
            ]
            if expected[0] == "query"
            else [callback for callback in callback_facts if callback.kind == expected[0]]
        )
        if not group or (expected[0] in {"authenticate", "login"} and len(group) != 1):
            _fail("request_callback_order_invalid")
        last_sequence = group[-1].local_sequence
        if last_sequence <= request["local_sequence"]:
            _fail("request_callback_order_invalid")
        if index + 1 < len(_REQUEST_PLAN):
            next_request = requests_by_key[_REQUEST_PLAN[index + 1][:3]]
            if last_sequence >= next_request["local_sequence"]:
                _fail("request_callback_order_invalid")

    write_counters = _exact_dict(worker_dict["write_counters"], "write_counters_invalid")
    if set(write_counters) != {"ReqOrderInsert", "ReqOrderAction"} or any(
        type(value) is not int or value != 0 for value in write_counters.values()
    ):
        _fail("write_activity_present")
    native_close = _exact_dict(worker_dict["native_close"], "native_close_invalid")
    _require_keys(
        native_close,
        {
            "receipt_type",
            "lifecycle_mode",
            "join_required",
            "join_completed",
            "native_released",
            "thread_alive",
            "timed_out",
        },
        "native_close_invalid",
    )
    if (
        native_close["receipt_type"] != "CtpNativeStopReceipt"
        or native_close["lifecycle_mode"] != "NO_JOIN_RELEASE_RETURNED"
        or type(native_close["join_required"]) is not bool
        or native_close["join_required"] is not False
        or type(native_close["join_completed"]) is not bool
        or native_close["join_completed"] is not True
        or type(native_close["native_released"]) is not bool
        or native_close["native_released"] is not True
        or type(native_close["thread_alive"]) is not bool
        or native_close["thread_alive"] is not False
        or type(native_close["timed_out"]) is not bool
        or native_close["timed_out"] is not False
    ):
        _fail("native_close_invalid")

    query_identity_rows = list(query_identities_by_key.values())
    if len(query_identity_rows) != 6:
        _fail("query_account_scope_inconsistent")
    identity_tuples = [(broker, investor, day) for broker, investor, day, _ in query_identity_rows]
    fingerprints = [fingerprint for _, _, _, fingerprint in query_identity_rows]
    if len(set(identity_tuples)) != 1 or len(set(fingerprints)) != 1:
        _fail("query_account_scope_inconsistent")
    expected_broker_id, expected_investor_id, query_trading_day = identity_tuples[0]
    if query_trading_day != login.trading_day:
        _fail("query_login_day_mismatch")

    summary_list = worker_dict["snapshots"]
    if type(summary_list) is not list or len(summary_list) != 2:
        _fail("snapshot_summary_invalid")
    parsed_snapshots: Dict[str, Dict[str, Any]] = {}
    artifact_digests: Dict[str, str] = {}
    snapshot_facts: List[C01SnapshotFact] = []
    for phase, artifact_ref, raw, summary_value in (
        ("baseline", "snapshots/baseline.json", baseline_bytes, summary_list[0]),
        ("final", "snapshots/final.json", final_bytes, summary_list[1]),
    ):
        summary = _exact_dict(summary_value, "snapshot_summary_invalid")
        _require_keys(summary, _SNAPSHOT_SUMMARY_KEYS, "snapshot_summary_invalid")
        _sha256(summary["artifact_sha256"], "snapshot_summary_invalid")
        raw_digest = _sha256_bytes(raw)
        if (
            summary["phase"] != phase
            or summary["artifact_ref"] != artifact_ref
            or summary["artifact_sha256"] != raw_digest
            or summary["account_scope_sha256"] != expected_account_scope_sha256
            or summary["credential_binding_sha256"] != expected_credential_binding_sha256
            or summary["client_instance_id"] != client_id
            or _positive_int(summary["client_generation"], "snapshot_summary_invalid")
            != client_generation
            or _positive_int(summary["arrival_generation"], "snapshot_summary_invalid")
            != arrival_generation
            or _nonempty_string(summary["session_id"], "snapshot_summary_invalid", maximum=64)
            != login.session_id
            or _trading_day(summary["trading_day"], "snapshot_summary_invalid") != login.trading_day
        ):
            _fail("snapshot_summary_binding_invalid")
        _validate_snapshot_summary_queries(summary["queries"])
        document = _parse_snapshot(raw, phase, protocol_module=protocol_module)
        _validate_snapshot(
            document,
            phase=phase,
            protocol_module=protocol_module,
            worker_module=worker_module,
            expected_account_scope_sha256=expected_account_scope_sha256,
            expected_credential_binding_sha256=expected_credential_binding_sha256,
            expected_broker_id=expected_broker_id,
            expected_investor_id=expected_investor_id,
            worker_client=client,
            login=login,
            summary=summary,
            requests_by_key=requests_by_key,
            callbacks_by_key=callbacks_by_key,
        )
        parsed_snapshots[phase] = document
        artifact_digests[phase] = raw_digest
        snapshot_client = document["client"]
        snapshot_scope = document["scope"]
        summary_queries = summary["queries"]
        snapshot_query_facts = []
        for family in ("orders", "positions", "funds"):
            detail = summary_queries[family]
            artifact_callbacks = document["queries"][family]["callbacks"]
            rows = sum(1 for item in artifact_callbacks if item["row_present"] is True)
            snapshot_query_facts.append(
                C01SnapshotQueryFact(
                    family=family,
                    request_id=_positive_int(
                        detail["request_id"], "snapshot_summary_query_invalid"
                    ),
                    callback_count=_positive_int(
                        detail["callback_count"], "snapshot_summary_query_invalid"
                    ),
                    row_count=_nonnegative_int(
                        detail["row_count"], "snapshot_summary_query_invalid"
                    ),
                    first_callback_local_sequence=_positive_int(
                        detail["first_sequence"], "snapshot_summary_query_invalid"
                    ),
                    terminal_callback_local_sequence=_positive_int(
                        detail["terminal_sequence"], "snapshot_summary_query_invalid"
                    ),
                )
            )
            if rows != detail["row_count"]:
                _fail("snapshot_summary_query_binding_invalid")
        projection_digests = tuple(
            (projection, summary[digest_key])
            for projection, digest_key in _SUMMARY_PROJECTION_DIGESTS
        )
        snapshot_facts.append(
            C01SnapshotFact(
                phase=phase,
                artifact_ref=artifact_ref,
                artifact_size_bytes=len(raw),
                client_instance_id=snapshot_client["instance_id"],
                client_generation=snapshot_client["client_generation"],
                arrival_generation=snapshot_client["arrival_generation"],
                front_id=document["scope"]["front_id"],
                session_id=snapshot_scope["session_id"],
                trading_day=snapshot_scope["trading_day"],
                queries=tuple(snapshot_query_facts),
                _artifact_sha256=raw_digest,
                _projection_sha256=projection_digests,
            )
        )
    baseline_doc = parsed_snapshots["baseline"]
    final_doc = parsed_snapshots["final"]
    if (
        _canonical_json_bytes(baseline_doc["scope"], "snapshot_scope_invalid")
        != _canonical_json_bytes(final_doc["scope"], "snapshot_scope_invalid")
        or _canonical_json_bytes(baseline_doc["client"], "snapshot_client_invalid")
        != _canonical_json_bytes(final_doc["client"], "snapshot_client_invalid")
        or _canonical_json_bytes(baseline_doc["projections"], "snapshot_projection_invalid")
        != _canonical_json_bytes(final_doc["projections"], "snapshot_projection_invalid")
    ):
        _fail("baseline_final_reconciliation_invalid")

    query_receipts: List[C01QueryReceiptContent] = []
    for phase in ("baseline", "final"):
        snapshot = parsed_snapshots[phase]
        for family in ("orders", "positions", "funds"):
            key = ("query", phase, family)
            request = requests_by_key[key]
            group = callbacks_by_key[key]
            artifact_query = snapshot["queries"][family]
            sdk_result = request["sdk_query_result"]
            terminal = group[-1]
            query_commitment = _sha256_bytes(
                b"iteration41.simnow.c01.query-content.v1\x00"
                + _canonical_json_bytes(
                    {
                        "request": request,
                        "callbacks": group,
                        "artifact_query": artifact_query,
                        "artifact_sha256": artifact_digests[phase],
                    },
                    "query_commitment_invalid",
                )
            )
            query_receipts.append(
                C01QueryReceiptContent(
                    phase=phase,
                    family=family,
                    method=request["method"],
                    request_id=request["request_id"],
                    request_generation=request["request_generation"],
                    client_instance_id=client_id,
                    client_generation=client_generation,
                    arrival_generation=arrival_generation,
                    request_local_sequence=request["local_sequence"],
                    request_issued_at_utc=request["issued_at_utc"],
                    request_issued_monotonic_ns=request["issued_monotonic_ns"],
                    send_return_code=request["return_code"],
                    callback_count=len(group),
                    row_count=sdk_result["record_count"],
                    first_callback_local_sequence=group[0]["local_sequence"],
                    terminal_callback_local_sequence=terminal["local_sequence"],
                    terminal_arrived_at_utc=terminal["arrived_at_utc"],
                    terminal_arrived_monotonic_ns=terminal["arrived_monotonic_ns"],
                    terminal_error_id=terminal["error_id"],
                    terminal_is_last=terminal["is_last"],
                    sdk_complete=sdk_result["complete"],
                    sdk_evidence_complete=sdk_result["evidence_complete"],
                    sdk_is_last_seen=sdk_result["is_last_seen"],
                    sdk_timed_out=sdk_result["timed_out"],
                    sdk_unsupported=sdk_result["unsupported"],
                    sdk_late_callback_count=sdk_result["late_callback_count"],
                    _private_query_sha256=query_commitment,
                )
            )

    request_tuple = tuple(request_facts)
    callback_tuple = tuple(callback_facts)
    query_tuple = tuple(query_receipts)
    private_content = worker_canonical
    private_content += len(baseline_bytes).to_bytes(8, "big") + baseline_bytes
    private_content += len(final_bytes).to_bytes(8, "big") + final_bytes
    private_content += bytes.fromhex(expected_worker_source_sha256)
    private_content += bytes.fromhex(expected_protocol_source_sha256)
    private_content += bytes.fromhex(expected_worker_module_source_sha256)
    private_content += bytes.fromhex(expected_account_scope_sha256)
    private_content += bytes.fromhex(expected_credential_binding_sha256)
    content_commitment = _sha256_bytes(
        b"iteration41.simnow.c01.content-only.v1\x00" + private_content
    )
    return C01ValidatedContent(
        requests=request_tuple,
        callbacks=callback_tuple,
        query_receipts=query_tuple,
        request_count=8,
        auth_login_callback_count=2,
        query_request_count=6,
        query_callback_count=sum(len(group) for group in callbacks_by_key.values()),
        snapshot_count=2,
        _snapshot_facts=tuple(snapshot_facts),
        activity_callback_count=0,
        write_invocation_count=0,
        native_close_complete=True,
        native_released=True,
        native_thread_alive=False,
        native_timed_out=False,
        provider_source_sequence=0,
        authority=AUTHORITY,
        status=CONTENT_STATUS,
        certification_pass=False,
        source_authenticity_verified=False,
        _content_commitment_sha256=content_commitment,
        _baseline_artifact_sha256=artifact_digests["baseline"],
        _final_artifact_sha256=artifact_digests["final"],
    )


def _validate_source_modules(protocol_module: ModuleType, worker_module: ModuleType) -> None:
    """Require the fixed first-party parser/projector module interfaces.

    This is only an interface check. The Root caller must independently bind
    each module's exact source/function bytes and object identity to its held
    source lease before using this content result.
    """

    if type(protocol_module) is not ModuleType or type(worker_module) is not ModuleType:
        _fail("source_module_invalid")
    if (
        type(getattr(protocol_module, "__name__", None)) is not str
        or type(getattr(worker_module, "__name__", None)) is not str
    ):
        _fail("source_module_invalid")
    protocol_functions = (
        "encode_worker_frame",
        "parse_worker_frame",
        "parse_private_snapshot_artifact",
        "canonical_value_sha256",
    )
    worker_functions = (
        "project_order_economics",
        "project_open_order_refs",
        "project_gross_positions",
        "project_funds",
    )
    for module, names in (
        (protocol_module, protocol_functions),
        (worker_module, worker_functions),
    ):
        for name in names:
            function = getattr(module, name, None)
            if (
                type(function).__name__ != "function"
                or getattr(function, "__module__", None) != module.__name__
            ):
                _fail("source_module_invalid")
    receipt_type = getattr(protocol_module, "C01WorkerReceipt", None)
    if (
        type(receipt_type).__name__ != "type"
        or getattr(receipt_type, "__module__", None) != protocol_module.__name__
    ):
        _fail("source_module_invalid")
    snapshot_type = getattr(protocol_module, "C01PrivateSnapshot", None)
    if (
        type(snapshot_type).__name__ != "type"
        or getattr(snapshot_type, "__module__", None) != protocol_module.__name__
    ):
        _fail("source_module_invalid")


def _validate_snapshot(
    document: Dict[str, Any],
    *,
    phase: str,
    protocol_module: ModuleType,
    worker_module: ModuleType,
    expected_account_scope_sha256: str,
    expected_credential_binding_sha256: str,
    expected_broker_id: str,
    expected_investor_id: str,
    worker_client: Dict[str, Any],
    login: C01CallbackFact,
    summary: Dict[str, Any],
    requests_by_key: Dict[Tuple[str, Optional[str], Optional[str]], Dict[str, Any]],
    callbacks_by_key: Dict[Tuple[str, Optional[str], Optional[str]], List[Dict[str, Any]]],
) -> None:
    _require_keys(document, _SNAPSHOT_KEYS, "snapshot_shape_invalid")
    if (
        document["protocol"] != PRIVATE_SNAPSHOT_PROTOCOL
        or type(document["version"]) is not int
        or document["version"] != PRIVATE_SNAPSHOT_VERSION
        or document["case_id"] != "C01"
        or document["phase"] != phase
        or document["account_scope_sha256"] != expected_account_scope_sha256
        or document["credential_binding_sha256"] != expected_credential_binding_sha256
    ):
        _fail("snapshot_identity_invalid")
    client = _exact_dict(document["client"], "snapshot_client_invalid")
    _require_keys(client, _SNAPSHOT_CLIENT_KEYS, "snapshot_client_invalid")
    _nonempty_string(client["instance_id"], "snapshot_client_invalid", maximum=128)
    _positive_int(client["client_generation"], "snapshot_client_invalid")
    _positive_int(client["arrival_generation"], "snapshot_client_invalid")
    if _canonical_json_bytes(client, "snapshot_client_invalid") != _canonical_json_bytes(
        worker_client, "snapshot_client_invalid"
    ):
        _fail("snapshot_client_binding_invalid")
    scope = _exact_dict(document["scope"], "snapshot_scope_invalid")
    _require_keys(scope, _SNAPSHOT_SCOPE_KEYS, "snapshot_scope_invalid")
    front_id = _positive_int(scope["front_id"], "snapshot_scope_invalid")
    session_id = _nonempty_string(scope["session_id"], "snapshot_scope_invalid", maximum=64)
    trading_day = _trading_day(scope["trading_day"], "snapshot_scope_invalid")
    if (front_id, session_id, trading_day) != (
        login.front_id,
        login.session_id,
        login.trading_day,
    ):
        _fail("login_snapshot_scope_mismatch")

    queries = _exact_dict(document["queries"], "snapshot_queries_invalid")
    if set(queries) != {"orders", "positions", "funds"}:
        _fail("snapshot_queries_invalid")
    for family in ("orders", "positions", "funds"):
        key = ("query", phase, family)
        query = _exact_dict(queries[family], "snapshot_query_invalid")
        _require_keys(query, _SNAPSHOT_QUERY_KEYS, "snapshot_query_invalid")
        request = requests_by_key[key]
        group = callbacks_by_key[key]
        artifact_request = _exact_dict(query["request"], "snapshot_request_invalid")
        _require_keys(artifact_request, _ARTIFACT_REQUEST_KEYS, "snapshot_request_invalid")
        expected_request = {
            name: request[name]
            for name in (
                "method",
                "request_id",
                "request_generation",
                "local_sequence",
                "issued_at_utc",
                "issued_monotonic_ns",
                "return_code",
                "sdk_query_result",
            )
        }
        if _canonical_json_bytes(
            artifact_request, "snapshot_request_invalid"
        ) != _canonical_json_bytes(expected_request, "snapshot_request_invalid"):
            _fail("snapshot_request_binding_invalid")

        artifact_callbacks = query["callbacks"]
        if type(artifact_callbacks) is not list or len(artifact_callbacks) != len(group):
            _fail("snapshot_callback_multiset_invalid")
        for index, (worker_callback, artifact_callback_value) in enumerate(
            zip(group, artifact_callbacks)
        ):
            artifact_callback = _exact_dict(artifact_callback_value, "snapshot_callback_invalid")
            _require_keys(artifact_callback, _ARTIFACT_CALLBACK_KEYS, "snapshot_callback_invalid")
            if artifact_callback["is_last"] is not (index == len(group) - 1):
                _fail("snapshot_callback_terminal_order_invalid")
            for worker_key, artifact_key in (
                ("callback_name", "callback_name"),
                ("request_id", "request_id"),
                ("error_id", "error_id"),
                ("rsp_info_present", "rsp_info_present"),
                ("error_semantics", "error_semantics"),
                ("is_last", "is_last"),
                ("request_generation", "request_generation"),
                ("local_sequence", "local_sequence"),
                ("arrived_at_utc", "arrived_at_utc"),
                ("arrived_monotonic_ns", "arrived_monotonic_ns"),
                ("row_present", "row_present"),
            ):
                if _canonical_json_bytes(
                    worker_callback[worker_key], "snapshot_callback_invalid"
                ) != _canonical_json_bytes(
                    artifact_callback[artifact_key], "snapshot_callback_invalid"
                ):
                    _fail("snapshot_callback_multiset_invalid")
            _positive_int(artifact_callback["request_id"], "snapshot_callback_invalid")
            _positive_int(artifact_callback["request_generation"], "snapshot_callback_invalid")
            _positive_int(artifact_callback["local_sequence"], "snapshot_callback_invalid")
            _positive_int(artifact_callback["arrived_monotonic_ns"], "snapshot_callback_invalid")
            if type(artifact_callback["error_id"]) is not int or artifact_callback["error_id"] != 0:
                _fail("snapshot_callback_invalid")
            if (
                artifact_callback["rsp_info_present"] is not True
                or type(artifact_callback["is_last"]) is not bool
                or artifact_callback["error_semantics"] != RSP_INFO_ERROR_ID_PRESENT
            ):
                _fail("snapshot_callback_invalid")
            _utc_ns(artifact_callback["arrived_at_utc"], "snapshot_callback_invalid")
            if type(artifact_callback["row_present"]) is not bool:
                _fail("snapshot_callback_row_invalid")
            row = artifact_callback["row"]
            if artifact_callback["row_present"]:
                if type(row) is not dict:
                    _fail("snapshot_callback_row_invalid")
                _json_value(row, "snapshot_callback_row_invalid")
            elif row is not None:
                _fail("snapshot_callback_row_invalid")

        sdk_result = request["sdk_query_result"]
        detached_rows = [item["row"] for item in artifact_callbacks if item["row_present"] is True]
        records_sha256 = _canonical_query_rows_sha256(detached_rows)
        if (
            sdk_result["record_count"] != len(detached_rows)
            or records_sha256 != sdk_result["records_sha256"]
            or records_sha256 != sdk_result["callback_records_sha256"]
            or records_sha256 != sdk_result["query_source"]["records_sha256"]
        ):
            _fail("snapshot_query_rows_binding_invalid")

        summary_queries = _exact_dict(summary["queries"], "snapshot_summary_queries_invalid")
        if set(summary_queries) != {"orders", "positions", "funds"}:
            _fail("snapshot_summary_queries_invalid")
        detail = _exact_dict(summary_queries[family], "snapshot_summary_query_invalid")
        _require_keys(detail, _SNAPSHOT_QUERY_SUMMARY_KEYS, "snapshot_summary_query_invalid")
        detail_request_id = _positive_int(detail["request_id"], "snapshot_summary_query_invalid")
        detail_callback_count = _positive_int(
            detail["callback_count"], "snapshot_summary_query_invalid"
        )
        detail_row_count = _nonnegative_int(detail["row_count"], "snapshot_summary_query_invalid")
        detail_first_sequence = _positive_int(
            detail["first_sequence"], "snapshot_summary_query_invalid"
        )
        detail_terminal_sequence = _positive_int(
            detail["terminal_sequence"], "snapshot_summary_query_invalid"
        )
        if (
            detail_request_id != request["request_id"]
            or detail_callback_count != len(artifact_callbacks)
            or detail_row_count != len(detached_rows)
            or detail_first_sequence != artifact_callbacks[0]["local_sequence"]
            or detail_terminal_sequence != artifact_callbacks[-1]["local_sequence"]
        ):
            _fail("snapshot_summary_query_binding_invalid")

    projections = _exact_dict(document["projections"], "snapshot_projection_invalid")
    _require_keys(projections, _PROJECTION_KEYS, "snapshot_projection_invalid")
    _json_value(projections, "snapshot_projection_invalid")
    for projection_key, summary_key in _SUMMARY_PROJECTION_DIGESTS:
        if (
            _sha256_bytes(
                _canonical_json_bytes(projections[projection_key], "snapshot_projection_invalid")
            )
            != summary[summary_key]
        ):
            _fail("snapshot_projection_digest_invalid")

    query_rows = {
        family: [
            callback["row"]
            for callback in queries[family]["callbacks"]
            if callback["row_present"] is True
        ]
        for family in ("orders", "positions", "funds")
    }
    if len(query_rows["funds"]) != 1:
        _fail("snapshot_projection_not_recomputable")
    try:
        expected_projections = {
            "open_order_refs": worker_module.project_open_order_refs(query_rows["orders"]),
            "order_economics": worker_module.project_order_economics(
                query_rows["orders"],
                protocol_module,
                expected_broker_id=expected_broker_id,
                expected_user_id=expected_investor_id,
                trading_day=trading_day,
            ),
            "positions": worker_module.project_gross_positions(
                query_rows["positions"],
                expected_broker_id=expected_broker_id,
                expected_user_id=expected_investor_id,
                trading_day=trading_day,
            ),
            "funds": worker_module.project_funds(
                query_rows["funds"][0],
                expected_broker_id=expected_broker_id,
                expected_account_id=expected_investor_id,
                trading_day=trading_day,
            ),
        }
    except C01LedgerContentError:
        raise
    except Exception:
        _fail("snapshot_projection_not_recomputable")
    if any(projections[key] != expected for key, expected in expected_projections.items()):
        _fail("snapshot_projection_rows_mismatch")


def _validate_sdk_query_result(
    value: Any, *, family: Optional[str], request_id: int, arrival_generation: int
) -> Tuple[str, str, str, str]:
    result = _exact_dict(value, "sdk_query_result_invalid")
    _require_keys(result, _QUERY_RESULT_KEYS, "sdk_query_result_invalid")
    expected_request_type = {"orders": "orders", "positions": "positions", "funds": "account"}.get(
        family
    )
    if (
        result["result_type"] != SDK_QUERY_RESULT_TYPE
        or result["request_type"] != expected_request_type
        or _positive_int(result["request_id"], "sdk_query_result_invalid") != request_id
        or _positive_int(result["connection_generation"], "sdk_query_result_invalid")
        != arrival_generation
        or result["complete"] is not True
        or result["evidence_complete"] is not True
        or result["is_last_seen"] is not True
        or result["timed_out"] is not False
        or result["unsupported"] is not False
        or result["error_code"] is not None
        or type(result["submit_code"]) is not int
        or result["submit_code"] != 0
        or type(result["record_count"]) is not int
        or result["record_count"] < 0
        or type(result["late_callback_count"]) is not int
        or result["late_callback_count"] != 0
        or result["error_message"] != ""
        or result["error_semantics"] != SDK_QUERY_ERROR_SEMANTICS
    ):
        _fail("sdk_query_result_incomplete")
    account_fingerprint = _nonempty_string(
        result["account_fingerprint"], "sdk_query_result_invalid", maximum=256
    )
    started_at = _nonempty_string(result["started_at_utc"], "sdk_query_result_invalid", maximum=40)
    completed_at = _nonempty_string(
        result["completed_at_utc"], "sdk_query_result_invalid", maximum=40
    )
    started_ns = _utc_ns(started_at, "sdk_query_result_invalid")
    completed_ns = _utc_ns(completed_at, "sdk_query_result_invalid")
    if completed_ns < started_ns:
        _fail("sdk_query_result_time_invalid")
    records_digest = _sha256(result["records_sha256"], "sdk_query_result_invalid")
    callback_digest = _sha256(result["callback_records_sha256"], "sdk_query_result_invalid")
    source = _exact_dict(result["query_source"], "sdk_query_source_invalid")
    _require_keys(source, _QUERY_SOURCE_KEYS, "sdk_query_source_invalid")
    if (
        source["source_type"] != "bt_api_ctp.query._QuerySource"
        or source["seal_valid"] is not True
        or source["issuer_is_client_query_lane"] is not True
        or source["request_type"] != result["request_type"]
        or _positive_int(source["request_id"], "sdk_query_source_invalid") != request_id
        or source["account_fingerprint"] != account_fingerprint
        or _positive_int(source["connection_generation"], "sdk_query_source_invalid")
        != arrival_generation
        or source["started_at_utc"] != started_at
        or source["completed_at_utc"] != completed_at
        or source["clock_domain_id"] != "python.time.monotonic"
        or source["explicit_request_filters"] != []
    ):
        _fail("sdk_query_source_binding_invalid")
    # These names and booleans are part of the V3 wire shape only. They are
    # never treated here as evidence that the SDK issuer or source is trusted.
    trading_day = _nonempty_string(source["trading_day"], "sdk_query_source_invalid", maximum=8)
    if not _TRADING_DAY_RE.fullmatch(trading_day):
        _fail("sdk_query_source_invalid")
    broker_id = _nonempty_string(source["broker_id"], "sdk_query_source_invalid", maximum=10)
    investor_id = _nonempty_string(source["investor_id"], "sdk_query_source_invalid", maximum=32)
    expected_filter_names = (
        ("BrokerID", "ExchangeID", "InstrumentID", "InvestorID", "OrderSysID")
        if family == "orders"
        else ("BrokerID", "InvestorID")
    )
    filters = source["request_filters"]
    if type(filters) is not list:
        _fail("sdk_query_source_filters_invalid")
    parsed_filters = []
    for item in filters:
        if type(item) is not list or len(item) != 2:
            _fail("sdk_query_source_filters_invalid")
        name = _nonempty_string(item[0], "sdk_query_source_filters_invalid", maximum=32)
        filter_value = item[1]
        if type(filter_value) is not str:
            _fail("sdk_query_source_filters_invalid")
        parsed_filters.append((name, filter_value))
    if tuple(name for name, _ in parsed_filters) != expected_filter_names:
        _fail("sdk_query_source_filters_invalid")
    filter_map = dict(parsed_filters)
    if (
        filter_map.get("BrokerID") != broker_id
        or filter_map.get("InvestorID") != investor_id
        or any(
            filter_map.get(name) != ""
            for name in ("ExchangeID", "InstrumentID", "OrderSysID")
            if name in filter_map
        )
    ):
        _fail("sdk_query_source_filters_invalid")
    source_started_ns = _utc_ns(source["started_at_utc"], "sdk_query_source_invalid")
    source_completed_ns = _utc_ns(source["completed_at_utc"], "sdk_query_source_invalid")
    expiry_ns = _utc_ns(source["trusted_expires_at_utc"], "sdk_query_source_invalid")
    if (
        source_started_ns != started_ns
        or source_completed_ns != completed_ns
        or expiry_ns != completed_ns + int(QUERY_EVIDENCE_TTL_SECONDS * 1_000_000_000)
    ):
        _fail("sdk_query_source_time_invalid")
    started_mono = _finite_hex_float(source["started_monotonic_hex"], "sdk_query_source_invalid")
    completed_mono = _finite_hex_float(
        source["completed_monotonic_hex"], "sdk_query_source_invalid"
    )
    expiry_mono = _finite_hex_float(
        source["trusted_expires_monotonic_hex"], "sdk_query_source_invalid"
    )
    if (
        started_mono >= completed_mono
        or expiry_mono != completed_mono + QUERY_EVIDENCE_TTL_SECONDS
        or source["records_sha256"] != records_digest
        or callback_digest != records_digest
    ):
        _fail("sdk_query_source_digest_or_clock_invalid")
    return broker_id, investor_id, trading_day, account_fingerprint


def _parse_snapshot(raw: bytes, phase: str, *, protocol_module: ModuleType) -> Dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_PRIVATE_SNAPSHOT_BYTES:
        _fail("snapshot_bytes_invalid")
    try:
        parsed = protocol_module.parse_private_snapshot_artifact(raw)
        if type(parsed) is not protocol_module.C01PrivateSnapshot or parsed.phase != phase:
            _fail("snapshot_protocol_invalid")
    except C01LedgerContentError:
        raise
    except Exception:
        _fail("snapshot_protocol_invalid")
    if not raw.endswith(b"\n") or raw.count(b"\n") != 1:
        _fail("snapshot_frame_invalid")
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object_pairs,
            parse_constant=_reject_json_constant,
        )
    except Exception:
        _fail("snapshot_json_invalid")
    if type(document) is not dict:
        _fail("snapshot_json_invalid")
    _json_value(document, "snapshot_json_invalid")
    canonical = _canonical_json_bytes(document, "snapshot_json_invalid") + b"\n"
    if canonical != raw:
        _fail("snapshot_not_canonical")
    if document.get("phase") != phase:
        _fail("snapshot_phase_invalid")
    return document


def _canonical_query_rows_sha256(rows: List[Any]) -> str:
    _json_value(rows, "query_rows_invalid")
    try:
        payload = json.dumps(
            rows,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        _fail("query_rows_invalid")
    return _sha256_bytes(payload)


def _canonical_json_bytes(value: Any, code: str) -> bytes:
    _json_value(value, code)
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        _fail(code)


def _json_value(value: Any, code: str) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if math.isfinite(value):
            return
        _fail(code)
    if type(value) is list:
        for item in value:
            _json_value(item, code)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                _fail(code)
            _json_value(item, code)
        return
    _fail(code)


def _unique_object_pairs(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    value: Dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            _fail("snapshot_duplicate_key")
        value[key] = item
    return value


def _reject_json_constant(_value: str) -> None:
    _fail("snapshot_nonstandard_constant")


def _exact_dict(value: Any, code: str) -> Dict[str, Any]:
    if type(value) is not dict:
        _fail(code)
    return value


def _require_keys(value: Dict[str, Any], keys: Iterable[str], code: str) -> None:
    if set(value) != set(keys):
        _fail(code)


def _positive_int(value: Any, code: str) -> int:
    if type(value) is not int or value <= 0:
        _fail(code)
    return value


def _nonnegative_int(value: Any, code: str) -> int:
    if type(value) is not int or value < 0:
        _fail(code)
    return value


def _nonempty_string(value: Any, code: str, *, maximum: int) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        _fail(code)
    return value


def _sha256(value: Any, code: str) -> str:
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        _fail(code)
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc_ns(value: Any, code: str) -> int:
    if type(value) is not str:
        _fail(code)
    match = _UTC_RE.fullmatch(value)
    if match is None:
        _fail(code)
    try:
        base = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        _fail(code)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = base - epoch
    seconds = delta.days * 86_400 + delta.seconds
    fraction = (match.group(2) or "").ljust(9, "0")
    return seconds * 1_000_000_000 + (int(fraction) if fraction else 0)


def _finite_hex_float(value: Any, code: str) -> float:
    if type(value) is not str or not _HEX_FLOAT_RE.fullmatch(value):
        _fail(code)
    try:
        result = float.fromhex(value)
    except ValueError:
        _fail(code)
    if not math.isfinite(result) or result <= 0 or result.hex() != value:
        _fail(code)
    return result


def _validate_pair_ref(value: Dict[str, Any]) -> None:
    _require_keys(
        value,
        {
            "selected_index",
            "selection_sha256",
            "md_front_sha256",
            "td_front_sha256",
            "selected_at_utc",
        },
        "pair_binding_invalid",
    )
    _nonnegative_int(value["selected_index"], "pair_binding_invalid")
    for key in ("selection_sha256", "md_front_sha256", "td_front_sha256"):
        _sha256(value[key], "pair_binding_invalid")
    _utc_ns(value["selected_at_utc"], "pair_binding_invalid")


def _validate_snapshot_summary_queries(value: Any) -> None:
    queries = _exact_dict(value, "snapshot_summary_queries_invalid")
    if set(queries) != {"orders", "positions", "funds"}:
        _fail("snapshot_summary_queries_invalid")
    for family in ("orders", "positions", "funds"):
        detail = _exact_dict(queries[family], "snapshot_summary_query_invalid")
        _require_keys(detail, _SNAPSHOT_QUERY_SUMMARY_KEYS, "snapshot_summary_query_invalid")
        _positive_int(detail["request_id"], "snapshot_summary_query_invalid")
        _positive_int(detail["callback_count"], "snapshot_summary_query_invalid")
        _nonnegative_int(detail["row_count"], "snapshot_summary_query_invalid")
        first = _positive_int(detail["first_sequence"], "snapshot_summary_query_invalid")
        terminal = _positive_int(detail["terminal_sequence"], "snapshot_summary_query_invalid")
        if terminal < first:
            _fail("snapshot_summary_query_invalid")


def _trading_day(value: Any, code: str) -> str:
    day = _nonempty_string(value, code, maximum=8)
    if not _TRADING_DAY_RE.fullmatch(day):
        _fail(code)
    try:
        datetime.strptime(day, "%Y%m%d")
    except ValueError:
        _fail(code)
    return day


def _fail(code: str) -> None:
    raise C01LedgerContentError(code)


__all__ = [
    "AUTHORITY",
    "CONTENT_STATUS",
    "SCHEMA",
    "C01CallbackFact",
    "C01LedgerContentError",
    "C01QueryReceiptContent",
    "C01RequestFact",
    "C01ValidatedContent",
    "validate_c01_ledger_content_v1",
]
