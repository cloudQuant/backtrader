"""Root-owned C01 admission bridge for the V16 Root integration.

The bridge stages one typed candidate from the exact active V18 source bundle
and produces a bounded pending result.  Staging grants no case authority.  A
formal result can be issued only after the fixed Root custody producer has
verified the same source bundle, native result, account binding, artifacts,
and post-run source cleanup. Source-fake tests never execute that producer.

This module does not open files, read configuration, import an SDK, or invoke a
provider/native API.  The Root entry is responsible for loading this module
and the projection module from its held source bytes in the same invocation.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import time
import uuid
from types import MappingProxyType, ModuleType
from typing import Any, Iterator, Mapping


_BRIDGE_MODULE_NAME = "common.c01_root_admission_bridge"
_BRIDGE_SHA256 = "ad8cab9db917ebdadc5fbfb28ee26ca485746b7c8e6c4e4e2501d033fdb956f8"
_FRONT_MODULE_NAME = "backtrader_runtime.certification_simnow_c01_front_transport_v12"
_FRONT_MODULE_SHA256 = "f23d1488c29366f040df3bf98fbdc94fc17dc1a58886f269faaf30650d449091"
_CERTIFICATION_MODULE_NAME = "common.certification"
_CERTIFICATION_MODULE_SHA256 = "1604afa4dba946cd1d1fbd327c6d47057f0380d766e42d9a4614c3369851d020"
_ROOT_CUSTODY_MODULE_NAME = "backtrader_runtime.certification_simnow_c01_root_custody_v16"
_ROOT_CUSTODY_MODULE_SHA256 = "571036d79815f7791bc6917f7afbf87ff8acd9806dc0556a80b9b39d34553f26"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EXPECTED_LEDGER_MARKERS = (
    "scenario_correlation:C01 requires a trusted issuer-side request ledger verifier; none is wired here",
    "scenario_correlation:C01 trusted issuer-side request ledger verifier is not wired into this tracker",
)
_AUTHENTICITY_REVIEW = (
    "provider source authenticity and account ownership require independent verification",
)
_SCOPE_FACTORY = object()
_PENDING_FACTORY = object()
_POSTVERIFY_FACTORY = object()
_CASE_RESULT_FACTORY = object()
_CURRENT_SCOPE: ContextVar["_C01RootInvocationScope | None"] = ContextVar(
    "c01_root_v16_current_scope", default=None
)


class C01RootV16Error(ValueError):
    """Fixed, non-sensitive local failure from the C01 Root bridge."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code or any(ord(char) < 32 for char in code):
            code = "root_candidate_invalid"
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class C01RootCandidateStage:
    """Finite stage summary; never includes account or artifact values."""

    request_count: int
    auth_login_callback_count: int
    query_callback_count: int
    snapshot_count: int
    write_invocation_count: int
    biz_type_state: str

    def __repr__(self) -> str:
        return "C01RootCandidateStage(<bounded typed candidate; no authority>)"


class C01NativeTdReadV16CandidatePendingRootAdmission:
    """A BLOCKED source result correlated to one staged Root invocation.

    The nonce and staged native objects are available only as private in-memory
    fields.  They are omitted from repr and serialization.  This type is not a
    PASS receipt and can never be constructed from caller JSON.
    """

    __slots__ = ("status", "reason", "profile", "case_id", "writes", "case_receipt_authority", "_scope", "_nonce", "_factory")

    def __init__(self, scope: "_C01RootInvocationScope", nonce: object, *, _factory: Any = None) -> None:
        if _factory is not _PENDING_FACTORY:
            raise C01RootV16Error("pending_result_factory_required")
        if type(scope) is not _C01RootInvocationScope or not scope.issuer_returned:
            raise C01RootV16Error("candidate_pending_unavailable")
        if nonce is not scope.nonce or scope.pending is not None or scope.consumed:
            raise C01RootV16Error("candidate_pending_binding_invalid")
        self.status = "BLOCKED"
        self.reason = "candidate_complete_pending_root_admission"
        self.profile = "C01_NATIVE_TD_READ_V18"
        self.case_id = "C01"
        self.writes = 0
        self.case_receipt_authority = "none"
        self._scope = scope
        self._nonce = nonce
        self._factory = _PENDING_FACTORY
        scope.pending = self

    def __repr__(self) -> str:
        return "C01NativeTdReadV16CandidatePendingRootAdmission(<BLOCKED; nonce redacted>)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": "C01",
            "profile": "C01_NATIVE_TD_READ_V18",
            "status": "BLOCKED",
            "reason": "candidate_complete_pending_root_admission",
            "writes": 0,
            "case_receipt_authority": "none",
        }


class C01RootPhysicalPostverifyProof:
    """Closed one-use proof minted only by the fixed Root custody producer."""

    __slots__ = (
        "scope",
        "pending",
        "source_bundle",
        "issuer",
        "owner",
        "helpers",
        "admission",
        "pair_binding",
        "process",
        "validation",
        "artifacts",
        "source_postverify_receipt",
        "runtime_postverify_receipt",
        "artifact_postverify_receipt",
        "account_binding_receipt",
        "native_ledger_receipt",
        "_root_custody_module",
        "_factory",
    )

    def __init__(
        self,
        *,
        scope: "_C01RootInvocationScope",
        pending: C01NativeTdReadV16CandidatePendingRootAdmission,
        receipts: tuple[Any, Any, Any, Any],
        native_ledger_receipt: Any,
        root_custody_module: ModuleType,
        _factory: Any = None,
    ) -> None:
        if _factory is not _POSTVERIFY_FACTORY:
            raise C01RootV16Error("root_postverify_factory_required")
        if (
            type(scope) is not _C01RootInvocationScope
            or scope.pending is not pending
            or scope.verification is not native_ledger_receipt
            or type(receipts) is not tuple
            or len(receipts) != 4
            or any(receipt is None for receipt in receipts)
            or root_custody_module is not scope.root_custody_module
        ):
            raise C01RootV16Error("root_postverify_binding_invalid")
        if not _root_native_ledger_receipt_matches(
            root_custody_module, native_ledger_receipt, scope, pending
        ):
            raise C01RootV16Error("root_postverify_binding_invalid")
        self.scope = scope
        self.pending = pending
        self.source_bundle = scope.bundle
        self.issuer = scope.issuer
        self.owner = scope.owner
        self.helpers = scope.helpers
        self.admission, self.pair_binding, self.process, self.validation, self.artifacts = (
            scope.candidate_refs
        )
        (
            self.source_postverify_receipt,
            self.runtime_postverify_receipt,
            self.artifact_postverify_receipt,
            self.account_binding_receipt,
        ) = receipts
        self.native_ledger_receipt = native_ledger_receipt
        self._root_custody_module = root_custody_module
        self._factory = _POSTVERIFY_FACTORY

    def __repr__(self) -> str:
        return "C01RootPhysicalPostverifyProof(<Root custody checked; refs redacted>)"


class C01RootCaseResultReceipt:
    """One-use Root-issued C01 CaseResult output.

    The contained common ``CaseResult`` is private.  Serialization here uses
    the immutable V16 receipt payload directly; it does not call the legacy
    fail-closed common serializer.  Construction is reserved for the fixed
    Root postverify path.
    """

    __slots__ = ("_payload", "_factory")

    def __init__(self, payload: Mapping[str, Any], *, _factory: Any = None):
        if _factory is not _CASE_RESULT_FACTORY:
            raise C01RootV16Error("case_result_factory_required")
        if type(payload) is not dict or payload.get("case_id") != "C01" or payload.get("status") != "PASS":
            raise C01RootV16Error("case_result_payload_invalid")
        self._payload = json.dumps(
            payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self._factory = _CASE_RESULT_FACTORY

    def __repr__(self) -> str:
        return "C01RootCaseResultReceipt(<Root verified; one issuance>)"

    def to_dict(self) -> dict[str, Any]:
        if self._factory is not _CASE_RESULT_FACTORY:
            raise C01RootV16Error("case_result_receipt_invalid")
        value = json.loads(self._payload.decode("utf-8"))
        if type(value) is not dict or value.get("case_id") != "C01" or value.get("status") != "PASS":
            raise C01RootV16Error("case_result_receipt_invalid")
        return value

    def exit_code(self) -> int:
        return 0


class _C01RootInvocationScope:
    __slots__ = (
        "bundle",
        "front",
        "root_custody_module",
        "issuer",
        "owner",
        "helpers",
        "protocol",
        "contract",
        "supervisor",
        "bridge",
        "certification_module",
        "worker_sha256",
        "nonce",
        "started_at",
        "started_at_utc",
        "active",
        "stage_count",
        "stage",
        "projection",
        "candidate_refs",
        "verification",
        "issuer_returned",
        "pending",
        "consumed",
        "_factory",
    )

    def __init__(
        self,
        front: ModuleType,
        bundle: Any,
        bridge: ModuleType,
        certification_module: ModuleType,
        root_custody_module: ModuleType,
        *,
        _factory: Any = None,
    ):
        if _factory is not _SCOPE_FACTORY:
            raise C01RootV16Error("root_scope_factory_required")
        _validate_front_module(front)
        _validate_v18_bundle(front, bundle)
        _validate_projection_module(bridge)
        _validate_certification_module(certification_module)
        _validate_root_custody_module(root_custody_module)
        self.bundle = bundle
        self.front = front
        self.root_custody_module = root_custody_module
        self.issuer = bundle.issuer
        self.owner = bundle.owner
        self.helpers = bundle.helpers
        self.protocol = bundle.helpers["protocol"]
        self.contract = bundle.helpers["contract"]
        self.supervisor = bundle.helpers["supervisor"]
        self.bridge = bridge
        self.certification_module = certification_module
        self.worker_sha256 = self.issuer._WORKER_SHA256
        self.nonce = object()
        self.started_at = time.monotonic()
        self.started_at_utc = datetime.now(timezone.utc).isoformat()
        self.active = True
        self.stage_count = 0
        self.stage = None
        self.projection = None
        self.candidate_refs = None
        self.verification = None
        self.issuer_returned = False
        self.pending = None
        self.consumed = False
        self._factory = _SCOPE_FACTORY

    def __repr__(self) -> str:
        return "_C01RootInvocationScope(<active; private custody refs redacted>)"


@contextmanager
def c01_root_invocation_scope(
    front_module: ModuleType,
    bundle: Any,
    bridge: ModuleType,
    certification_module: ModuleType,
    root_custody_module: ModuleType,
) -> Iterator[_C01RootInvocationScope]:
    """Bind hooks to one active exact V18 bundle and held bridge module.

    The Root entry must supply every module and bundle from exact same-call
    held bytes. This scope does not itself prove physical custody or account
    ownership; those are checked by the fixed Root custody producer after
    issuer cleanup.
    """

    if _CURRENT_SCOPE.get() is not None:
        raise C01RootV16Error("root_invocation_already_active")
    scope = _C01RootInvocationScope(
        front_module,
        bundle,
        bridge,
        certification_module,
        root_custody_module,
        _factory=_SCOPE_FACTORY,
    )
    token = _CURRENT_SCOPE.set(scope)
    try:
        yield scope
    finally:
        scope.active = False
        _CURRENT_SCOPE.reset(token)


def stage_current_c01_candidate(
    *, admission: Any, pair_binding: Any, process: Any, validation: Any, artifacts: dict[str, bytes]
) -> C01RootCandidateStage:
    """Validate and retain exactly one candidate while the issuer ExitStack lives."""

    scope = _CURRENT_SCOPE.get()
    if type(scope) is not _C01RootInvocationScope or not scope.active or not scope.bundle._active:
        raise C01RootV16Error("root_invocation_not_active")
    if scope.stage_count != 0 or scope.consumed:
        raise C01RootV16Error("candidate_stage_reused")
    if (
        type(admission) is not getattr(scope.issuer, "_C01V18Admission", None)
        or type(pair_binding) is not scope.protocol.C01PairBinding
        or type(process) is not scope.supervisor.C01SupervisorResult
        or type(validation) is not scope.protocol.C01CandidateValidation
        or type(artifacts) is not dict
        or set(artifacts) != {"snapshots/baseline.json", "snapshots/final.json"}
    ):
        raise C01RootV16Error("candidate_typed_binding_invalid")
    if any(type(value) is not bytes or not value for value in artifacts.values()):
        raise C01RootV16Error("candidate_artifacts_invalid")
    try:
        projection = scope.bridge.project_c01_root_candidate(
            protocol=scope.protocol,
            contract=scope.contract,
            supervisor=scope.supervisor,
            owner=scope.owner,
            helpers=scope.helpers,
            admission=admission,
            pair_binding=pair_binding,
            process=process,
            validation=validation,
            artifacts=artifacts,
            expected_worker_source_sha256=scope.worker_sha256,
        )
    except Exception as exc:
        code = str(exc) if type(exc) is C01RootV16Error else "candidate_evidence_invalid"
        raise C01RootV16Error(code) from None
    stage = C01RootCandidateStage(
        request_count=projection.receipt_request_count,
        auth_login_callback_count=projection.receipt_auth_login_callback_count,
        query_callback_count=projection.receipt_query_callback_count,
        snapshot_count=projection.receipt_snapshot_count,
        write_invocation_count=projection.worker_reported_write_invocations,
        biz_type_state=projection.biz_type_state,
    )
    scope.stage_count = 1
    scope.stage = stage
    scope.projection = projection
    # Keep the exact current admission, native process result, and artifact
    # byte mapping alive until the Root postverify path consumes or retains it.
    scope.candidate_refs = (admission, pair_binding, process, validation, artifacts)
    return stage


def current_c01_root_invocation_nonce() -> object:
    """Return the opaque current-call correlation object to the fixed issuer."""

    scope = _CURRENT_SCOPE.get()
    if (
        type(scope) is not _C01RootInvocationScope
        or not scope.active
        or scope.consumed
        or type(scope.stage_count) is not int
        or scope.stage_count not in (0, 1)
    ):
        raise C01RootV16Error("root_invocation_nonce_unavailable")
    return scope.nonce


def pending_root_admission_result(
    nonce: object, issuer_result: Any
) -> C01NativeTdReadV16CandidatePendingRootAdmission:
    """Create the fixed BLOCKED pending result after the issuer returns cleanly."""

    scope = _CURRENT_SCOPE.get()
    if (
        type(scope) is not _C01RootInvocationScope
        or not scope.active
        or scope.stage_count != 1
        or nonce is not scope.nonce
        or type(issuer_result) is not getattr(scope.issuer, "C01NativeTdReadV18Result", None)
        or scope.verification is not None
    ):
        raise C01RootV16Error("candidate_pending_binding_invalid")
    if (
        issuer_result.status != "PASS"
        or issuer_result.reason != "read_only_candidate_complete"
        or issuer_result.profile != "C01_NATIVE_TD_READ_V18"
        or issuer_result.case_id != "C01"
        or type(issuer_result.writes) is not int
        or issuer_result.writes != 0
        or issuer_result.admission_failure_stage != "none"
        or issuer_result.admission_failure_class != "none"
        or issuer_result.post_worker_failure_stage != "none"
        or issuer_result.post_worker_failure_code != "none"
    ):
        raise C01RootV16Error("issuer_candidate_not_complete")
    _verify_staged_candidate(scope)
    scope.issuer_returned = True
    return C01NativeTdReadV16CandidatePendingRootAdmission(
        scope, nonce, _factory=_PENDING_FACTORY
    )


def verify_current_c01_request_ledger(
    scope: _C01RootInvocationScope,
    pending: C01NativeTdReadV16CandidatePendingRootAdmission,
) -> None:
    """Run the finite current-call ledger check for the fixed Root entry.

    This is a validator only: it returns no truth value, receipt, or authority.
    The fixed Root custody producer must call it, then create its exact typed
    ``C01RootNativeLedgerReceipt`` from the same scope if physical checks pass.
    """

    if (
        type(scope) is not _C01RootInvocationScope
        or not scope.active
        or not scope.issuer_returned
        or scope.pending is not pending
        or pending._scope is not scope
        or pending._nonce is not scope.nonce
        or scope.verification is not None
    ):
        raise C01RootV16Error("candidate_pending_binding_invalid")
    _verify_staged_candidate(scope)
    _verify_root_request_ledger(scope)


def record_root_native_ledger_receipt(
    scope: _C01RootInvocationScope,
    pending: C01NativeTdReadV16CandidatePendingRootAdmission,
    *,
    root_custody_module: ModuleType,
    receipt: Any,
) -> None:
    """Bind the fixed producer's receipt to this exact scope and pending result."""

    if (
        type(scope) is not _C01RootInvocationScope
        or not scope.active
        or not scope.issuer_returned
        or scope.pending is not pending
        or pending._scope is not scope
        or pending._nonce is not scope.nonce
        or scope.verification is not None
        or root_custody_module is not scope.root_custody_module
        or not _root_custody_module_is_pinned(root_custody_module)
        or not _root_native_ledger_receipt_matches(
            root_custody_module, receipt, scope, pending
        )
    ):
        raise C01RootV16Error("root_postverify_unconfigured")
    scope.verification = receipt


def _mint_root_postverify_proof(
    *,
    scope: _C01RootInvocationScope,
    pending: C01NativeTdReadV16CandidatePendingRootAdmission,
    source_postverify_receipt: Any,
    runtime_postverify_receipt: Any,
    artifact_postverify_receipt: Any,
    account_binding_receipt: Any,
    native_ledger_receipt: Any,
) -> C01RootPhysicalPostverifyProof:
    """Root-only mint seam, called after physical postverify and ledger checks."""

    if (
        type(scope) is not _C01RootInvocationScope
        or not scope.active
        or scope.pending is not pending
        or not scope.issuer_returned
        or scope.consumed
        or pending._scope is not scope
        or pending._nonce is not scope.nonce
    ):
        raise C01RootV16Error("root_postverify_binding_invalid")
    if not _root_custody_module_is_pinned(scope.root_custody_module):
        raise C01RootV16Error("root_postverify_unconfigured")
    if (
        scope.verification is not native_ledger_receipt
        or not _root_native_ledger_receipt_matches(
            scope.root_custody_module, native_ledger_receipt, scope, pending
        )
    ):
        raise C01RootV16Error("root_postverify_binding_invalid")
    receipts = (
        source_postverify_receipt,
        runtime_postverify_receipt,
        artifact_postverify_receipt,
        account_binding_receipt,
    )
    for receipt, class_name in zip(
        receipts,
        (
            "C01RootSourcePostverifyReceipt",
            "C01RootRuntimePostverifyReceipt",
            "C01RootArtifactPostverifyReceipt",
            "C01RootAccountBindingReceipt",
        ),
    ):
        if not _root_receipt_matches(
            scope.root_custody_module, receipt, class_name, scope, pending
        ):
            raise C01RootV16Error("root_postverify_binding_invalid")
    return C01RootPhysicalPostverifyProof(
        scope=scope,
        pending=pending,
        receipts=receipts,
        native_ledger_receipt=native_ledger_receipt,
        root_custody_module=scope.root_custody_module,
        _factory=_POSTVERIFY_FACTORY,
    )


def finalize_c01_root_case_result(
    pending: C01NativeTdReadV16CandidatePendingRootAdmission,
    *,
    root_custody_module: ModuleType,
    postverify_proof: Any,
) -> C01RootCaseResultReceipt:
    """Finalize one PASS only from the exact frozen Root custody producer.

    The exact Root-owned custody producer module is pinned above. Calls with
    caller booleans, dicts, strings, source-fake objects, or any differently
    pinned module stay blocked.
    """

    if type(pending) is not C01NativeTdReadV16CandidatePendingRootAdmission:
        raise C01RootV16Error("candidate_pending_invalid")
    scope = pending._scope
    if (
        scope.consumed
        or not scope.issuer_returned
        or scope.pending is not pending
        or pending._nonce is not scope.nonce
    ):
        raise C01RootV16Error("candidate_pending_binding_invalid")
    if root_custody_module is not scope.root_custody_module:
        raise C01RootV16Error("root_postverify_unconfigured")
    if not _root_custody_module_is_pinned(root_custody_module):
        raise C01RootV16Error("root_postverify_unconfigured")
    if scope.verification is None:
        raise C01RootV16Error("candidate_pending_binding_invalid")
    if (
        type(postverify_proof) is not C01RootPhysicalPostverifyProof
        or getattr(postverify_proof, "_factory", None) is not _POSTVERIFY_FACTORY
        or getattr(postverify_proof, "_root_custody_module", None) is not root_custody_module
        or getattr(postverify_proof, "scope", None) is not scope
        or getattr(postverify_proof, "pending", None) is not pending
        or getattr(postverify_proof, "source_bundle", None) is not scope.bundle
        or getattr(postverify_proof, "issuer", None) is not scope.issuer
        or getattr(postverify_proof, "owner", None) is not scope.owner
        or getattr(postverify_proof, "helpers", None) is not scope.helpers
        or getattr(postverify_proof, "admission", None) is not scope.candidate_refs[0]
        or getattr(postverify_proof, "pair_binding", None) is not scope.candidate_refs[1]
        or getattr(postverify_proof, "process", None) is not scope.candidate_refs[2]
        or getattr(postverify_proof, "validation", None) is not scope.candidate_refs[3]
        or getattr(postverify_proof, "artifacts", None) is not scope.candidate_refs[4]
        or not _root_receipt_matches(root_custody_module, postverify_proof.source_postverify_receipt, "C01RootSourcePostverifyReceipt", scope, pending)
        or not _root_receipt_matches(root_custody_module, postverify_proof.runtime_postverify_receipt, "C01RootRuntimePostverifyReceipt", scope, pending)
        or not _root_receipt_matches(root_custody_module, postverify_proof.artifact_postverify_receipt, "C01RootArtifactPostverifyReceipt", scope, pending)
        or not _root_receipt_matches(root_custody_module, postverify_proof.account_binding_receipt, "C01RootAccountBindingReceipt", scope, pending)
        or not _root_native_ledger_receipt_matches(root_custody_module, postverify_proof.native_ledger_receipt, scope, pending)
        or getattr(postverify_proof, "native_ledger_receipt", None) is not scope.verification
    ):
        raise C01RootV16Error("root_postverify_binding_invalid")
    # Scope-level one-use consumption prevents duplicate result minting. The
    # Root proof itself remains owned by its fixed producer and is not mutated.
    scope.consumed = True
    payload = _build_case_result_payload(scope)
    return C01RootCaseResultReceipt(payload, _factory=_CASE_RESULT_FACTORY)


def _verify_staged_candidate(scope: _C01RootInvocationScope) -> None:
    if (
        scope.stage_count != 1
        or scope.projection is None
        or scope.candidate_refs is None
        or scope.stage.request_count != 8
        or scope.stage.auth_login_callback_count != 2
        or scope.stage.query_callback_count < 6
        or scope.stage.snapshot_count != 2
        or scope.stage.write_invocation_count != 0
        or scope.stage.biz_type_state not in {"unclassified", "unknown_nul_only", "observed"}
    ):
        raise C01RootV16Error("candidate_ledger_incomplete")
    report = scope.projection.completion_report
    if (
        report.case_id != "C01"
        or report.status.value != "INCOMPLETE"
        or report.certification_pass is not False
        or report.dispatch_permitted is not False
        or report.source_authenticity_verified is not False
        or report.missing_invariants != _EXPECTED_LEDGER_MARKERS
        or report.contradictions
        or report.unavailable_dependencies
        or report.review_reasons != _AUTHENTICITY_REVIEW
    ):
        raise C01RootV16Error("candidate_completion_incomplete")


def _verify_root_request_ledger(scope: _C01RootInvocationScope) -> None:
    """Recheck the fixed eight-request ledger against same-process callbacks."""

    admission, pair_binding, process, _validation, _artifacts = scope.candidate_refs
    try:
        receipt = process.worker_receipt
        worker = receipt.to_dict()
        requests = worker["requests"]
        callbacks = worker["callbacks"]
        expected = (
            ("authenticate", None, None, "ReqAuthenticate"),
            ("login", None, None, "ReqUserLogin"),
            ("query", "baseline", "orders", "ReqQryOrder"),
            ("query", "baseline", "positions", "ReqQryInvestorPosition"),
            ("query", "baseline", "funds", "ReqQryTradingAccount"),
            ("query", "final", "orders", "ReqQryOrder"),
            ("query", "final", "positions", "ReqQryInvestorPosition"),
            ("query", "final", "funds", "ReqQryTradingAccount"),
        )
        if type(requests) is not list or len(requests) != len(expected):
            raise ValueError
        if type(callbacks) is not list:
            raise ValueError
        previous_sequence = 0
        request_ids: set[int] = set()
        request_by_key: dict[tuple[Any, Any, Any], Mapping[str, Any]] = {}
        expected_account = admission.bindings["account_scope_sha256"]
        expected_credential = admission.bindings["credential_binding_sha256"]
        for row, (kind, phase, family, method) in zip(requests, expected):
            if type(row) is not dict:
                raise ValueError
            key = (row.get("kind"), row.get("phase"), row.get("family"))
            if (
                key != (kind, phase, family)
                or row.get("method") != method
                or type(row.get("request_id")) is not int
                or row["request_id"] <= 0
                or row["request_id"] in request_ids
                or type(row.get("request_generation")) is not int
                or row["request_generation"] <= 0
                or type(row.get("local_sequence")) is not int
                or row["local_sequence"] <= previous_sequence
                or type(row.get("return_code")) is not int
                or row["return_code"] != 0
                or row.get("receipt_origin") != "local_native_invocation"
                or row.get("account_scope_sha256") != expected_account
                or row.get("credential_binding_sha256") != expected_credential
            ):
                raise ValueError
            request_ids.add(row["request_id"])
            previous_sequence = row["local_sequence"]
            request_by_key[key] = row
        if worker.get("pair_binding") != pair_binding.to_receipt_ref().to_dict():
            raise ValueError
        if worker.get("account_scope_sha256") != expected_account:
            raise ValueError
        if worker.get("credential_binding_sha256") != expected_credential:
            raise ValueError
        if worker.get("worker_source_sha256") != scope.worker_sha256:
            raise ValueError
        write_counters = worker.get("write_counters")
        if (
            type(write_counters) is not dict
            or set(write_counters) != {"ReqOrderInsert", "ReqOrderAction"}
            or any(type(value) is not int or value != 0 for value in write_counters.values())
        ):
            raise ValueError
        callback_keys: set[tuple[Any, Any, Any]] = set()
        for callback in callbacks:
            if type(callback) is not dict:
                raise ValueError
            key = (callback.get("kind"), callback.get("phase"), callback.get("family"))
            request = request_by_key.get(key)
            if request is None:
                raise ValueError
            if (
                callback.get("request_id") != request.get("request_id")
                or callback.get("request_generation") != request.get("request_generation")
                or callback.get("account_scope_sha256") != expected_account
                or callback.get("credential_binding_sha256") != expected_credential
                or type(callback.get("local_sequence")) is not int
                or callback["local_sequence"] <= request["local_sequence"]
            ):
                raise ValueError
            callback_keys.add(key)
        if callback_keys != set(request_by_key):
            raise ValueError
        lifecycle = process.process_lifecycle
        if (
            type(lifecycle) is not scope.protocol.C01ProcessLifecycleReceipt
            or lifecycle.process_exit_observed is not True
            or type(lifecycle.process_exit_code) is not int
            or lifecycle.process_exit_code != 0
            or type(lifecycle.job_active_count) is not int
            or lifecycle.job_active_count != 0
            or lifecycle.handles_closed is not True
            or lifecycle.timed_out is not False
            or lifecycle.forced_kill is not False
        ):
            raise ValueError
    except Exception:
        # No request, account, callback, or exception contents leave this check.
        raise C01RootV16Error("candidate_ledger_incomplete") from None


def _build_case_result_payload(scope: _C01RootInvocationScope) -> dict[str, Any]:
    """Create the ordinary C01 result shape after Root proof consumption."""

    try:
        scenario = scope.certification_module.get_certification_scenario("C01")
        worker = scope.candidate_refs[2].worker_receipt.to_dict()
        login = next(
            row for row in worker["callbacks"] if row.get("kind") == "login"
        )
        required_events = list(scenario.required_events)
        evidence_fields = list(scenario.evidence_fields)
        now = datetime.now(timezone.utc).isoformat()
        trace_id = f"ctp-cert-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        duration = round(max(0.0, time.monotonic() - scope.started_at), 2)
        details = {
            "certification_evidence": {
                "front_id": login["front_id"],
                "session_id": login["session_id"],
                "trading_day": login["trading_day"],
            },
            "root_admission": {
                "receipt_type": "C01RootPhysicalPostverifyProof",
                "request_count": scope.stage.request_count,
                "query_callback_count": scope.stage.query_callback_count,
                "snapshot_count": scope.stage.snapshot_count,
                "write_invocation_count": 0,
                "biz_type_state": scope.stage.biz_type_state,
            },
        }
        audit_event = {
            "event_type": "certification_case_result",
            "event_id": str(uuid.uuid4()),
            "trace_id": trace_id,
            "case_id": "C01",
            "scenario_id": scenario.scenario_id,
            "scenario_name": scenario.name,
            "category": scenario.category,
            "status": "PASS",
            "severity": "INFO",
            "timestamp": now,
            "simnow_env": "simulation",
            "message": "case passed",
            "required_events": required_events,
            "evidence_fields": evidence_fields,
            "observed_events": required_events,
            "missing_required_events": [],
            "missing_evidence_fields": [],
            "required_events_present": True,
            "evidence_fields_present": True,
            "evidence": [],
            "details": details,
        }
        return {
            "case_id": "C01",
            "case_name": scenario.name,
            "status": "PASS",
            "scenario_id": scenario.scenario_id,
            "scenario_name": scenario.name,
            "category": scenario.category,
            "trace_id": trace_id,
            "started_at": scope.started_at_utc,
            "finished_at": now,
            "duration_seconds": duration,
            "simnow_env": "simulation",
            "required_events": required_events,
            "evidence_fields": evidence_fields,
            "pass_conditions": list(scenario.pass_conditions),
            "optional": scenario.optional,
            "observed_events": required_events,
            "missing_required_events": [],
            "required_events_present": True,
            "missing_evidence_fields": [],
            "evidence_fields_present": True,
            "evidence": [],
            "failure_reason": "",
            "next_action": "",
            "details": details,
            "audit_events": [audit_event],
        }
    except C01RootV16Error:
        raise
    except Exception:
        raise C01RootV16Error("case_result_build_failed") from None


def _validate_front_module(front: ModuleType) -> None:
    if (
        type(front) is not ModuleType
        or front.__name__ != _FRONT_MODULE_NAME
        or getattr(front, "__c01_source_sha256__", None) != _FRONT_MODULE_SHA256
        or not callable(getattr(front, "verified_c01_v18_sources", None))
    ):
        raise C01RootV16Error("source_front_binding_invalid")


def _validate_v18_bundle(front: ModuleType, bundle: Any) -> None:
    if (
        type(front) is not ModuleType
        or type(bundle) is not getattr(front, "VerifiedC01V18SourceBundle", None)
        or getattr(bundle, "_active", None) is not True
        or getattr(bundle, "_factory", None) is not getattr(front, "_BUNDLE_FACTORY", None)
        or type(getattr(bundle, "issuer", None)) is not ModuleType
        or type(getattr(bundle, "owner", None)) is not ModuleType
        or type(getattr(bundle, "helpers", None)) not in (dict, type(MappingProxyType({})))
    ):
        raise C01RootV16Error("source_bundle_invalid")
    issuer = bundle.issuer
    if (
        issuer.__name__ != getattr(front, "_V18_MODULE_NAME", None)
        or getattr(issuer, "__c01_source_sha256__", None) != getattr(front, "_V18_SHA256", None)
        or getattr(issuer, "PROFILE_ID", None) != "C01_NATIVE_TD_READ_V18"
        or type(getattr(issuer, "_WORKER_SHA256", None)) is not str
        or not _SHA256_RE.fullmatch(issuer._WORKER_SHA256)
        or getattr(issuer, "_OWNER_MODULE_NAME", None) != bundle.owner.__name__
    ):
        raise C01RootV16Error("source_bundle_invalid")
    expected_keys = getattr(front, "_EXPECTED_BUNDLE_HELPERS", None)
    if type(expected_keys) is not frozenset or set(bundle.helpers) != expected_keys:
        raise C01RootV16Error("source_bundle_invalid")
    if (
        bundle.helpers.get("protocol") is None
        or bundle.helpers.get("contract") is None
        or bundle.helpers.get("supervisor") is None
        or not callable(bundle.helpers.get("owner_now_utc"))
    ):
        raise C01RootV16Error("source_bundle_invalid")


def _validate_projection_module(module: ModuleType) -> None:
    if (
        type(module) is not ModuleType
        or module.__name__ != _BRIDGE_MODULE_NAME
        or getattr(module, "__c01_source_sha256__", None) != _BRIDGE_SHA256
        or not callable(getattr(module, "project_c01_root_candidate", None))
    ):
        raise C01RootV16Error("projection_source_invalid")


def _validate_certification_module(module: ModuleType) -> None:
    if (
        type(module) is not ModuleType
        or module.__name__ != _CERTIFICATION_MODULE_NAME
        or getattr(module, "__c01_source_sha256__", None)
        != _CERTIFICATION_MODULE_SHA256
        or not callable(getattr(module, "get_certification_scenario", None))
    ):
        raise C01RootV16Error("certification_source_invalid")


def _validate_root_custody_module(module: ModuleType) -> None:
    if (
        type(module) is not ModuleType
        or module.__name__ != _ROOT_CUSTODY_MODULE_NAME
        or type(getattr(module, "__c01_source_sha256__", None)) is not str
        or not _SHA256_RE.fullmatch(module.__c01_source_sha256__)
    ):
        raise C01RootV16Error("root_custody_source_invalid")


def _root_custody_module_is_pinned(module: ModuleType) -> bool:
    expected = _ROOT_CUSTODY_MODULE_SHA256
    return (
        type(expected) is str
        and _SHA256_RE.fullmatch(expected) is not None
        and type(module) is ModuleType
        and module.__name__ == _ROOT_CUSTODY_MODULE_NAME
        and getattr(module, "__c01_source_sha256__", None) == expected
    )


def _root_receipt_matches(
    module: ModuleType,
    receipt: Any,
    class_name: str,
    scope: _C01RootInvocationScope,
    pending: C01NativeTdReadV16CandidatePendingRootAdmission,
) -> bool:
    receipt_type = getattr(module, class_name, None)
    factory = getattr(module, "_C01_ROOT_POSTVERIFY_FACTORY", None)
    return (
        type(receipt_type) is type
        and type(receipt) is receipt_type
        and getattr(receipt, "_factory", None) is factory
        and getattr(receipt, "_scope", None) is scope
        and getattr(receipt, "_pending", None) is pending
        and getattr(receipt, "_nonce", None) is scope.nonce
    )


def _root_native_ledger_receipt_matches(
    module: ModuleType,
    receipt: Any,
    scope: _C01RootInvocationScope,
    pending: C01NativeTdReadV16CandidatePendingRootAdmission,
) -> bool:
    if not _root_receipt_matches(
        module, receipt, "C01RootNativeLedgerReceipt", scope, pending
    ):
        return False
    candidate_refs = scope.candidate_refs
    receipt_refs = getattr(receipt, "_candidate_refs", None)
    if (
        type(candidate_refs) is not tuple
        or len(candidate_refs) != 5
        or type(receipt_refs) is not tuple
        or len(receipt_refs) != 5
    ):
        return False
    return (
        getattr(receipt, "_projection", None) is scope.projection
        and getattr(receipt, "_source_bundle", None) is scope.bundle
        and getattr(receipt, "_issuer", None) is scope.issuer
        and getattr(receipt, "_owner", None) is scope.owner
        and getattr(receipt, "_helpers", None) is scope.helpers
        and all(actual is expected for actual, expected in zip(receipt_refs, candidate_refs))
        and type(getattr(receipt, "request_count", None)) is int
        and receipt.request_count == 8
        and type(getattr(receipt, "auth_login_callback_count", None)) is int
        and receipt.auth_login_callback_count == 2
        and type(getattr(receipt, "query_callback_count", None)) is int
        and receipt.query_callback_count == scope.stage.query_callback_count
        and receipt.query_callback_count >= 6
        and type(getattr(receipt, "snapshot_count", None)) is int
        and receipt.snapshot_count == 2
        and type(getattr(receipt, "write_invocation_count", None)) is int
        and receipt.write_invocation_count == 0
    )


__all__ = [
    "C01NativeTdReadV16CandidatePendingRootAdmission",
    "C01RootCandidateStage",
    "C01RootCaseResultReceipt",
    "C01RootV16Error",
    "c01_root_invocation_scope",
    "current_c01_root_invocation_nonce",
    "finalize_c01_root_case_result",
    "pending_root_admission_result",
    "record_root_native_ledger_receipt",
    "stage_current_c01_candidate",
    "verify_current_c01_request_ledger",
]
