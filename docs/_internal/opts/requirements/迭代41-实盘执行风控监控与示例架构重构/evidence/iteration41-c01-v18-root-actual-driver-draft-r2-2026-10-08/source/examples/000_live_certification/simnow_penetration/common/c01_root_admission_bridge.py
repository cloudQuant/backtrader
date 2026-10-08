"""Typed in-memory projection for Root-owned SimNow C01 admission.

This module is a narrow bridge from the fixed C01 native TD worker receipt and
the two snapshot byte strings already held by the issuer.  It opens no files,
does no provider or SDK work, and grants no authority by itself.  The caller
must supply the exact module objects from the active verified source bundle;
the Root integration must also bind those objects and this call to one current
invocation before it can consume the returned projection.

Only the two already-read snapshot byte strings are parsed.  No paths, account
values, credential values, or source hashes are returned in the projection.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType, ModuleType
from typing import Any, Mapping

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
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
    "orders": "OnRspQryOrder",
    "positions": "OnRspQryInvestorPosition",
    "funds": "OnRspQryTradingAccount",
}
_LEDGER_MARKER = (
    "scenario_correlation:C01 requires a trusted issuer-side request ledger verifier; "
    "none is wired here"
)
_TRACKER_LEDGER_MARKER = (
    "scenario_correlation:C01 trusted issuer-side request ledger verifier "
    "is not wired into this tracker"
)
_LEDGER_MARKERS = (_LEDGER_MARKER, _TRACKER_LEDGER_MARKER)
_AUTHENTICITY_REVIEW = (
    "provider source authenticity and account ownership require independent verification"
)


class C01RootBridgeError(ValueError):
    """A fixed, non-sensitive failure from the C01 evidence projection."""

    def __init__(self, code: str):
        if type(code) is not str or not code or any(ord(char) < 32 for char in code):
            code = "candidate_evidence_invalid"
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class C01RootCandidateProjection:
    """Bounded output of the pure C01 receipt and completion checks.

    ``completion_report`` is the existing common checker result.  It remains
    INCOMPLETE on the exact two trusted-ledger markers and has
    ``certification_pass=False``; the Root actor must separately verify source,
    native, account, artifact custody, lifecycle, and the request ledger before
    it can finalize a case result.
    """

    completion_report: Any
    receipt_auth_login_callback_count: int
    receipt_request_count: int
    receipt_query_callback_count: int
    receipt_snapshot_count: int
    worker_reported_write_invocations: int
    biz_type_state: str

    def __repr__(self) -> str:
        return "C01RootCandidateProjection(<private values redacted; no authority>)"


def project_c01_root_candidate(
    *,
    protocol: ModuleType,
    contract: ModuleType,
    supervisor: ModuleType,
    owner: ModuleType,
    helpers: Mapping[str, Any],
    admission: Any,
    pair_binding: Any,
    process: Any,
    validation: Any,
    artifacts: dict[str, bytes],
    expected_worker_source_sha256: str,
) -> C01RootCandidateProjection:
    """Check the fixed V3 C01 evidence path and build existing typed evidence.

    The source bundle and invocation owner are deliberately caller-owned.  In
    production this function is called only by the fixed Root V15 integration
    while that bundle and the issuer's ExitStack are active.  This function
    does not treat an ordinary call as authenticated custody.
    """

    try:
        return _project_c01_root_candidate(
            protocol=protocol,
            contract=contract,
            supervisor=supervisor,
            owner=owner,
            helpers=helpers,
            admission=admission,
            pair_binding=pair_binding,
            process=process,
            validation=validation,
            artifacts=artifacts,
            expected_worker_source_sha256=expected_worker_source_sha256,
        )
    except C01RootBridgeError:
        raise
    except Exception:
        # Never expose native objects, account rows, exception text, or paths.
        raise C01RootBridgeError("candidate_evidence_invalid") from None


def _project_c01_root_candidate(
    *,
    protocol: ModuleType,
    contract: ModuleType,
    supervisor: ModuleType,
    owner: ModuleType,
    helpers: Mapping[str, Any],
    admission: Any,
    pair_binding: Any,
    process: Any,
    validation: Any,
    artifacts: dict[str, bytes],
    expected_worker_source_sha256: str,
) -> C01RootCandidateProjection:
    _require_module(protocol, "C01PairBinding", "C01WorkerReceipt")
    _require_module(contract, "validate_c01_candidate")
    _require_module(supervisor, "C01SupervisorResult")
    if type(owner) is not ModuleType or type(helpers) not in (dict, MappingProxyType):
        raise C01RootBridgeError("candidate_source_binding_invalid")
    if helpers.get("protocol") is not protocol:
        raise C01RootBridgeError("candidate_source_binding_invalid")
    if helpers.get("contract") is not contract:
        raise C01RootBridgeError("candidate_source_binding_invalid")
    if helpers.get("supervisor") is not supervisor:
        raise C01RootBridgeError("candidate_source_binding_invalid")
    if (
        type(expected_worker_source_sha256) is not str
        or not _SHA256_RE.fullmatch(expected_worker_source_sha256)
    ):
        raise C01RootBridgeError("candidate_source_binding_invalid")

    if type(pair_binding) is not protocol.C01PairBinding:
        raise C01RootBridgeError("candidate_pair_binding_invalid")
    if type(process) is not supervisor.C01SupervisorResult:
        raise C01RootBridgeError("candidate_process_receipt_invalid")
    if type(validation) is not protocol.C01CandidateValidation:
        raise C01RootBridgeError("candidate_validation_invalid")
    if type(validation) is not protocol.C01CandidateValidation:
        raise C01RootBridgeError("candidate_validation_invalid")
    if type(artifacts) is not dict or set(artifacts) != {
        "snapshots/baseline.json",
        "snapshots/final.json",
    }:
        raise C01RootBridgeError("candidate_artifacts_invalid")
    if any(type(raw) is not bytes or not raw for raw in artifacts.values()):
        raise C01RootBridgeError("candidate_artifacts_invalid")

    receipt = getattr(process, "worker_receipt", None)
    lifecycle = getattr(process, "process_lifecycle", None)
    if type(receipt) is not protocol.C01WorkerReceipt:
        raise C01RootBridgeError("candidate_worker_receipt_invalid")
    if type(lifecycle) is not protocol.C01ProcessLifecycleReceipt:
        raise C01RootBridgeError("candidate_lifecycle_receipt_invalid")
    if not _candidate_validation_is_exact(contract, validation):
        raise C01RootBridgeError("candidate_validation_ineligible")

    bindings = getattr(admission, "bindings", None)
    if not isinstance(bindings, Mapping):
        raise C01RootBridgeError("candidate_admission_binding_invalid")
    account_scope = bindings.get("account_scope_sha256")
    credential_binding = bindings.get("credential_binding_sha256")
    if (
        type(account_scope) is not str
        or not _SHA256_RE.fullmatch(account_scope)
        or type(credential_binding) is not str
        or not _SHA256_RE.fullmatch(credential_binding)
    ):
        raise C01RootBridgeError("candidate_admission_binding_invalid")

    worker = receipt.to_dict()
    if type(worker) is not dict:
        raise C01RootBridgeError("candidate_worker_receipt_invalid")
    _verify_fixed_worker_receipt(
        protocol=protocol,
        worker=worker,
        expected_worker_source_sha256=expected_worker_source_sha256,
        expected_account_scope_sha256=account_scope,
        expected_credential_binding_sha256=credential_binding,
        expected_pair_binding=pair_binding,
    )
    _verify_process_completion(
        owner=owner,
        helpers=helpers,
        process=process,
        pair_binding=pair_binding,
        account_scope_sha256=account_scope,
        credential_binding_sha256=credential_binding,
    )

    snapshots = _parse_and_bind_snapshots(
        protocol=protocol,
        worker=worker,
        artifacts=artifacts,
        expected_account_scope_sha256=account_scope,
        expected_credential_binding_sha256=credential_binding,
    )
    evidence = _build_completion_evidence(protocol=protocol, worker=worker, snapshots=snapshots)
    from common.completion_invariants import CompletionStatus, evaluate_case_completion

    report = evaluate_case_completion(evidence)
    if (
        report.case_id != "C01"
        or report.certification_pass is not False
        or report.dispatch_permitted is not False
        or report.source_authenticity_verified is not False
        or report.status is not CompletionStatus.INCOMPLETE
        or report.missing_invariants != _LEDGER_MARKERS
        or report.contradictions
        or report.unavailable_dependencies
        or report.review_reasons != (_AUTHENTICITY_REVIEW,)
    ):
        raise C01RootBridgeError("candidate_completion_incomplete")

    biz_states = tuple(
        _biz_type_state(item.payload["projections"]["funds"]["dimensions"]["BizType"])
        for item in snapshots
    )
    if len(set(biz_states)) != 1:
        raise C01RootBridgeError("candidate_biz_type_state_mismatch")
    return C01RootCandidateProjection(
        completion_report=report,
        receipt_auth_login_callback_count=2,
        receipt_request_count=8,
        receipt_query_callback_count=sum(
            1
            for callback in worker["callbacks"]
            if callback["kind"] == "query"
        ),
        receipt_snapshot_count=2,
        worker_reported_write_invocations=0,
        biz_type_state=biz_states[0],
    )


def _require_module(module: Any, *names: str) -> None:
    if type(module) is not ModuleType or any(not hasattr(module, name) for name in names):
        raise C01RootBridgeError("candidate_source_binding_invalid")


def _candidate_validation_is_exact(contract: ModuleType, validation: Any) -> bool:
    marker = getattr(contract, "_PROTECTED_ADMISSION_REQUIRED", None)
    return (
        type(marker) is str
        and bool(marker)
        and type(validation.eligible_for_protected_admission) is bool
        and validation.eligible_for_protected_admission is True
        and validation.status == "BLOCKED"
        and type(validation.reasons) is tuple
        and validation.reasons == (marker,)
        and type(validation.checked_request_count) is int
        and validation.checked_request_count == 8
        and type(validation.checked_query_callback_count) is int
        and validation.checked_query_callback_count >= 6
        and type(validation.checked_snapshot_count) is int
        and validation.checked_snapshot_count == 2
    )


def _verify_fixed_worker_receipt(
    *,
    protocol: ModuleType,
    worker: dict[str, Any],
    expected_worker_source_sha256: str,
    expected_account_scope_sha256: str,
    expected_credential_binding_sha256: str,
    expected_pair_binding: Any,
) -> None:
    validate_shape = getattr(protocol, "_validate_worker_shape", None)
    if not callable(validate_shape):
        raise C01RootBridgeError("candidate_worker_receipt_invalid")
    try:
        validate_shape(worker)
    except Exception:
        raise C01RootBridgeError("candidate_worker_receipt_invalid") from None
    if (
        worker.get("protocol") != protocol.PROTOCOL_NAME
        or worker.get("version") != protocol.PROTOCOL_VERSION
        or worker.get("case_id") != "C01"
        or worker.get("terminal_state") != "normal"
        or worker.get("worker_source_sha256") != expected_worker_source_sha256
        or worker.get("account_scope_sha256") != expected_account_scope_sha256
        or worker.get("credential_binding_sha256") != expected_credential_binding_sha256
    ):
        raise C01RootBridgeError("candidate_worker_receipt_binding_invalid")
    if worker.get("pair_binding") != expected_pair_binding.to_receipt_ref().to_dict():
        raise C01RootBridgeError("candidate_worker_receipt_binding_invalid")

    requests = worker.get("requests")
    if type(requests) is not list or len(requests) != len(_REQUEST_PLAN):
        raise C01RootBridgeError("candidate_request_ledger_invalid")
    request_by_key: dict[tuple[str, Any, Any], dict[str, Any]] = {}
    request_ids = set()
    prior_sequence = 0
    for request, expected in zip(requests, _REQUEST_PLAN):
        if type(request) is not dict:
            raise C01RootBridgeError("candidate_request_ledger_invalid")
        key = (request.get("kind"), request.get("phase"), request.get("family"))
        if (
            key != expected[:3]
            or request.get("method") != expected[3]
            or type(request.get("request_id")) is not int
            or request["request_id"] <= 0
            or request["request_id"] in request_ids
            or type(request.get("request_generation")) is not int
            or request["request_generation"] <= 0
            or type(request.get("local_sequence")) is not int
            or request["local_sequence"] <= prior_sequence
            or type(request.get("issued_monotonic_ns")) is not int
            or request["issued_monotonic_ns"] <= 0
            or type(request.get("return_code")) is not int
            or request["return_code"] != 0
            or request.get("receipt_origin") != "local_native_invocation"
            or request.get("account_scope_sha256") != expected_account_scope_sha256
            or request.get("credential_binding_sha256") != expected_credential_binding_sha256
        ):
            raise C01RootBridgeError("candidate_request_ledger_invalid")
        request_ids.add(request["request_id"])
        prior_sequence = request["local_sequence"]
        if key in request_by_key:
            raise C01RootBridgeError("candidate_request_ledger_invalid")
        request_by_key[key] = request
        if key[0] == "query":
            result = request.get("sdk_query_result")
            if (
                not isinstance(result, Mapping)
                or result.get("complete") is not True
                or result.get("evidence_complete") is not True
                or result.get("is_last_seen") is not True
                or result.get("timed_out") is not False
                or result.get("unsupported") is not False
                or result.get("error_code") is not None
                or type(result.get("submit_code")) is not int
                or result.get("submit_code") != 0
                or type(result.get("late_callback_count")) is not int
                or result.get("late_callback_count") != 0
            ):
                raise C01RootBridgeError("candidate_query_receipt_invalid")
        elif request.get("sdk_query_result") is not None:
            raise C01RootBridgeError("candidate_request_ledger_invalid")

    callbacks = worker.get("callbacks")
    if type(callbacks) is not list:
        raise C01RootBridgeError("candidate_callback_ledger_invalid")
    callback_groups: dict[tuple[str, Any, Any], list[dict[str, Any]]] = {}
    callback_kinds = {"authenticate": 0, "login": 0}
    for callback in callbacks:
        if type(callback) is not dict:
            raise C01RootBridgeError("candidate_callback_ledger_invalid")
        kind = callback.get("kind")
        if kind in {"order_activity", "trade_activity"}:
            raise C01RootBridgeError("candidate_write_activity_present")
        if kind in callback_kinds:
            callback_kinds[kind] += 1
        if kind not in {"authenticate", "login", "query"}:
            raise C01RootBridgeError("candidate_callback_ledger_invalid")
        key = (kind, callback.get("phase"), callback.get("family"))
        if key not in request_by_key:
            raise C01RootBridgeError("candidate_callback_ledger_invalid")
        request = request_by_key[key]
        if (
            callback.get("request_id") != request.get("request_id")
            or callback.get("request_generation") != request.get("request_generation")
            or callback.get("account_scope_sha256") != expected_account_scope_sha256
            or callback.get("credential_binding_sha256") != expected_credential_binding_sha256
            or type(callback.get("local_sequence")) is not int
            or callback["local_sequence"] <= request["local_sequence"]
            or callback.get("client_instance_id") != worker.get("client", {}).get("instance_id")
            or callback.get("arrival_generation")
            != worker.get("client", {}).get("arrival_generation")
        ):
            raise C01RootBridgeError("candidate_callback_ledger_invalid")
        if kind in {"authenticate", "login"}:
            expected_name = "OnRspAuthenticate" if kind == "authenticate" else "OnRspUserLogin"
            if (
                callback.get("callback_name") != expected_name
                or callback.get("rsp_info_present") is not True
                or type(callback.get("error_id")) is not int
                or callback.get("error_id") != 0
                or callback.get("error_semantics") != protocol.RSP_INFO_ERROR_ID_PRESENT
                or callback.get("is_last") is not True
            ):
                raise C01RootBridgeError("candidate_callback_ledger_invalid")
        else:
            family = callback.get("family")
            if (
                family not in _QUERY_CALLBACKS
                or callback.get("callback_name") != _QUERY_CALLBACKS[family]
                or callback.get("rsp_info_present") is not True
                or type(callback.get("error_id")) is not int
                or callback.get("error_id") != 0
                or callback.get("error_semantics") != protocol.RSP_INFO_ERROR_ID_PRESENT
                or type(callback.get("is_last")) is not bool
            ):
                raise C01RootBridgeError("candidate_callback_ledger_invalid")
            callback_groups.setdefault(key, []).append(callback)
    if callback_kinds != {"authenticate": 1, "login": 1}:
        raise C01RootBridgeError("candidate_callback_ledger_invalid")
    for phase in ("baseline", "final"):
        for family in ("orders", "positions", "funds"):
            key = ("query", phase, family)
            group = callback_groups.get(key, [])
            if not group or any(
                item.get("is_last") is not (index == len(group) - 1)
                for index, item in enumerate(group)
            ):
                raise C01RootBridgeError("candidate_callback_ledger_invalid")

    counters = worker.get("write_counters")
    if (
        type(counters) is not dict
        or set(counters) != {"ReqOrderInsert", "ReqOrderAction"}
        or any(type(value) is not int or value != 0 for value in counters.values())
    ):
        raise C01RootBridgeError("candidate_write_activity_present")
    native_close = worker.get("native_close")
    if (
        not isinstance(native_close, Mapping)
        or native_close.get("receipt_type") != "CtpNativeStopReceipt"
        or native_close.get("lifecycle_mode") != "NO_JOIN_RELEASE_RETURNED"
        or type(native_close.get("join_required")) is not bool
        or native_close.get("join_required") is not False
        or type(native_close.get("join_completed")) is not bool
        or native_close.get("join_completed") is not True
        or type(native_close.get("native_released")) is not bool
        or native_close.get("native_released") is not True
        or type(native_close.get("thread_alive")) is not bool
        or native_close.get("thread_alive") is not False
        or type(native_close.get("timed_out")) is not bool
        or native_close.get("timed_out") is not False
    ):
        raise C01RootBridgeError("candidate_native_lifecycle_invalid")


def _verify_process_completion(
    *,
    owner: ModuleType,
    helpers: Mapping[str, Any],
    process: Any,
    pair_binding: Any,
    account_scope_sha256: str,
    credential_binding_sha256: str,
) -> None:
    receipt = process.worker_receipt
    lifecycle = process.process_lifecycle
    bool_fields = (
        "assigned_before_resume",
        "stdin_fully_sent",
        "stdout_eof",
        "stderr_eof",
        "process_exit_observed",
        "handles_closed",
        "timed_out",
        "forced_kill",
    )
    if any(type(getattr(lifecycle, field, None)) is not bool for field in bool_fields):
        raise C01RootBridgeError("candidate_lifecycle_receipt_invalid")
    if (
        process.status != "BLOCKED"
        or process.reason != "candidate_transport_complete"
        or lifecycle.status != "BLOCKED"
        or lifecycle.assigned_before_resume is not True
        or lifecycle.stdin_fully_sent is not True
        or lifecycle.stdout_eof is not True
        or lifecycle.stderr_eof is not True
        or lifecycle.process_exit_observed is not True
        or type(lifecycle.process_exit_code) is not int
        or lifecycle.process_exit_code != 0
        or type(lifecycle.job_active_count) is not int
        or lifecycle.job_active_count != 0
        or lifecycle.handles_closed is not True
        or lifecycle.timed_out is not False
        or lifecycle.forced_kill is not False
        or lifecycle.containment != "windows_job"
        or lifecycle.reason != "normal_exit"
        or type(lifecycle.parent_pid) is not int
        or lifecycle.parent_pid <= 0
        or type(lifecycle.worker_pid) is not int
        or lifecycle.worker_pid <= 0
        or lifecycle.run_nonce != receipt.run_nonce
        or lifecycle.parent_pid != receipt.parent_pid
        or lifecycle.worker_pid != receipt.worker_pid
        or lifecycle.worker_source_sha256 != receipt.worker_source_sha256
    ):
        raise C01RootBridgeError("candidate_lifecycle_incomplete")
    worker = receipt.to_dict()
    if (
        type(worker.get("parent_pid")) is not int
        or type(worker.get("worker_pid")) is not int
        or worker.get("worker_pid") == worker.get("parent_pid")
        or worker.get("run_nonce") != lifecycle.run_nonce
        or worker.get("account_scope_sha256") != account_scope_sha256
        or worker.get("credential_binding_sha256") != credential_binding_sha256
    ):
        raise C01RootBridgeError("candidate_lifecycle_binding_invalid")
    try:
        process_complete = owner._worker_process_complete(helpers, process)
        receipt_matches = owner._worker_receipt_matches(
            helpers,
            process,
            pair_binding,
            account_scope_sha256,
            credential_binding_sha256,
        )
    except Exception:
        raise C01RootBridgeError("candidate_lifecycle_binding_invalid") from None
    if process_complete is not True or receipt_matches is not True:
        raise C01RootBridgeError("candidate_lifecycle_binding_invalid")


def _parse_and_bind_snapshots(
    *,
    protocol: ModuleType,
    worker: dict[str, Any],
    artifacts: dict[str, bytes],
    expected_account_scope_sha256: str,
    expected_credential_binding_sha256: str,
) -> tuple[Any, Any]:
    summaries = worker.get("snapshots")
    if type(summaries) is not list or len(summaries) != 2:
        raise C01RootBridgeError("candidate_snapshot_binding_invalid")
    parsed = []
    for index, phase in enumerate(("baseline", "final")):
        ref = f"snapshots/{phase}.json"
        raw = artifacts[ref]
        summary = summaries[index]
        if (
            type(summary) is not dict
            or summary.get("phase") != phase
            or summary.get("artifact_ref") != ref
            or summary.get("artifact_sha256") != hashlib.sha256(raw).hexdigest()
        ):
            raise C01RootBridgeError("candidate_snapshot_binding_invalid")
        try:
            snapshot = protocol.parse_private_snapshot_artifact(raw)
        except Exception:
            raise C01RootBridgeError("candidate_snapshot_invalid") from None
        document = snapshot.to_dict()
        if (
            document.get("phase") != phase
            or document.get("account_scope_sha256") != expected_account_scope_sha256
            or document.get("credential_binding_sha256")
            != expected_credential_binding_sha256
            or document.get("client") != worker.get("client")
            or summary.get("client_instance_id") != document["client"].get("instance_id")
            or summary.get("client_generation") != document["client"].get("client_generation")
            or summary.get("arrival_generation") != document["client"].get("arrival_generation")
            or summary.get("session_id") != document["scope"].get("session_id")
            or summary.get("trading_day") != document["scope"].get("trading_day")
        ):
            raise C01RootBridgeError("candidate_snapshot_binding_invalid")
        _verify_snapshot_receipt_links(protocol, worker, summary, document, phase)
        parsed.append(snapshot)
    if (
        parsed[0].payload["scope"] != parsed[1].payload["scope"]
        or parsed[0].payload["client"] != parsed[1].payload["client"]
        or parsed[0].payload["projections"] != parsed[1].payload["projections"]
    ):
        raise C01RootBridgeError("candidate_snapshot_reconciliation_failed")
    return parsed[0], parsed[1]


def _verify_snapshot_receipt_links(
    protocol: ModuleType,
    worker: dict[str, Any],
    summary: dict[str, Any],
    document: Mapping[str, Any],
    phase: str,
) -> None:
    requests = {
        (item.get("kind"), item.get("phase"), item.get("family")): item
        for item in worker["requests"]
    }
    callbacks = [
        item
        for item in worker["callbacks"]
        if item.get("kind") == "query" and item.get("phase") == phase
    ]
    for family in ("orders", "positions", "funds"):
        key = ("query", phase, family)
        request = requests.get(key)
        artifact_query = document["queries"][family]
        artifact_request = artifact_query["request"]
        if request is None or any(
            artifact_request.get(field) != request.get(field)
            for field in (
                "method",
                "request_id",
                "request_generation",
                "local_sequence",
                "issued_at_utc",
                "issued_monotonic_ns",
                "return_code",
                "sdk_query_result",
            )
        ):
            raise C01RootBridgeError("candidate_snapshot_binding_invalid")
        worker_callbacks = [
            item
            for item in callbacks
            if item.get("family") == family
        ]
        artifact_callbacks = artifact_query["callbacks"]
        if len(worker_callbacks) != len(artifact_callbacks):
            raise C01RootBridgeError("candidate_snapshot_binding_invalid")
        for source, artifact in zip(worker_callbacks, artifact_callbacks):
            for left, right in (
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
                if source.get(left) != artifact.get(right):
                    raise C01RootBridgeError("candidate_snapshot_binding_invalid")
        detail = summary["queries"][family]
        if (
            detail.get("request_id") != request["request_id"]
            or detail.get("callback_count") != len(artifact_callbacks)
            or detail.get("row_count")
            != sum(item.get("row_present") is True for item in artifact_callbacks)
            or detail.get("first_sequence") != artifact_callbacks[0]["local_sequence"]
            or detail.get("terminal_sequence") != artifact_callbacks[-1]["local_sequence"]
        ):
            raise C01RootBridgeError("candidate_snapshot_binding_invalid")
    projections = document["projections"]
    for projection_name, summary_name in (
        ("open_order_refs", "open_order_refs_sha256"),
        ("order_economics", "order_economics_sha256"),
        ("positions", "positions_sha256"),
        ("funds", "funds_sha256"),
    ):
        if protocol.canonical_value_sha256(projections[projection_name]) != summary.get(
            summary_name
        ):
            raise C01RootBridgeError("candidate_snapshot_binding_invalid")


def _build_completion_evidence(*, protocol: ModuleType, worker: dict[str, Any], snapshots):
    from common.case_engine import (
        CertificationEvidence,
        EvidenceSource,
        IssuedRequestReceipt,
        LocalCallbackArrival,
    )
    from common.completion_invariants import (
        AccountReconciliationSnapshot,
        CompletionEvidence,
        SnapshotPhase,
    )

    request_by_key = {
        (request["kind"], request["phase"], request["family"]): request
        for request in worker["requests"]
    }
    auth_login = []
    for kind, event_kind, callback_name in (
        ("authenticate", "store_auth_success", "OnRspAuthenticate"),
        ("login", "store_login_success", "OnRspUserLogin"),
    ):
        request = request_by_key[(kind, None, None)]
        callback = next(
            item
            for item in worker["callbacks"]
            if item["kind"] == kind and item["callback_name"] == callback_name
        )
        issued = _issue_receipt(
            IssuedRequestReceipt, protocol, request, "", worker["client"]
        )
        arrived_monotonic = callback["arrived_monotonic_ns"] / 1_000_000_000
        arrival = LocalCallbackArrival(
            client_instance_id=callback["client_instance_id"],
            request_generation=callback["request_generation"],
            arrival_generation=callback["arrival_generation"],
            source_sequence=callback["local_sequence"],
            arrived_at_utc=callback["arrived_at_utc"],
            arrived_monotonic=arrived_monotonic,
            issued_request_receipt=issued,
        )
        fields = {
            "request_id": callback["request_id"],
            "request_generation": callback["request_generation"],
            "arrival_generation": callback["arrival_generation"],
            "is_last": callback["is_last"],
            "error_id": callback["error_id"],
        }
        provider_front_id = None
        session_id = ""
        trading_day = ""
        if kind == "authenticate":
            fields["authentication_succeeded"] = callback["error_id"] == 0
        else:
            provider_front_id = callback["front_id"]
            session_id = callback["session_id"]
            trading_day = callback["trading_day"]
            fields.update(
                {
                    "front_id": provider_front_id,
                    "session_id": session_id,
                    "provider_front_id": provider_front_id,
                    "provider_session_id": session_id,
                    "trading_day": trading_day,
                    "login_succeeded": callback["error_id"] == 0,
                }
            )
        callback_digest = hashlib.sha256(protocol.canonical_json_bytes(callback)).hexdigest()
        auth_login.append(
            CertificationEvidence(
                event_kind=event_kind,
                source=EvidenceSource.PROVIDER_CALLBACK,
                event_id=hashlib.sha256(
                    (event_kind + callback_digest).encode("ascii")
                ).hexdigest(),
                evidence_sha256=callback_digest,
                occurred_at_utc=callback["arrived_at_utc"],
                fields=fields,
                callback_names=(callback_name,),
                provider_session_id=session_id,
                trading_day=trading_day,
                provider_front_id=provider_front_id,
                source_sequence=0,
                callback_arrival=arrival,
            )
        )

    account_snapshots = []
    for phase, snapshot in zip(("baseline", "final"), snapshots):
        document = snapshot.to_dict()
        query_ids = {}
        query_sequences = {}
        query_errors = {}
        query_last = {}
        issued_receipts = {}
        request_generations = {}
        query_times = {}
        query_monotonic = {}
        query_callbacks = []
        query_arrival_utc = []
        for family, callback_name in _QUERY_CALLBACKS.items():
            query = document["queries"][family]
            request = query["request"]
            terminal = query["callbacks"][-1]
            query_ids[callback_name] = terminal["request_id"]
            query_sequences[callback_name] = terminal["local_sequence"]
            query_errors[callback_name] = terminal["error_id"]
            query_last[callback_name] = terminal["is_last"]
            query_callbacks.append(callback_name)
            query_arrival_utc.append(terminal["arrived_at_utc"])
            key = ("query", phase, family)
            worker_request = request_by_key[key]
            issued_receipts[callback_name] = _issue_receipt(
                IssuedRequestReceipt, protocol, worker_request, phase, worker["client"]
            )
            request_generations[callback_name] = request["request_generation"]
            query_times[callback_name] = terminal["arrived_at_utc"]
            query_monotonic[callback_name] = (
                terminal["arrived_monotonic_ns"] / 1_000_000_000
            )
        latest_arrival = max(query_arrival_utc, key=_utc_sort_key)
        projections = document["projections"]
        open_refs = tuple(
            hashlib.sha256(protocol.canonical_json_bytes(ref)).hexdigest()
            for ref in projections["open_order_refs"]
        )
        positions = {
            hashlib.sha256(
                protocol.canonical_json_bytes(
                    {
                        name: bucket[name]
                        for name in (
                            "exchange_id",
                            "instrument_id",
                            "position_direction",
                            "hedge_flag",
                            "position_date",
                        )
                    }
                )
            ).hexdigest(): Decimal(bucket["quantity"])
            for bucket in projections["positions"]["buckets"]
        }
        diagnostics = projections["funds"]["diagnostics"]
        funds = {
            "cash": Decimal(diagnostics["cash"]),
            "available_funds": Decimal(diagnostics["available_funds"]),
            "equity": Decimal(diagnostics["equity"]),
        }
        account_snapshots.append(
            AccountReconciliationSnapshot(
                phase=SnapshotPhase(phase),
                session_id=document["scope"]["session_id"],
                trading_day=document["scope"]["trading_day"],
                occurred_at_utc=latest_arrival,
                order_query_id=f"c01-root:{worker['run_nonce']}:{phase}:orders",
                position_query_id=f"c01-root:{worker['run_nonce']}:{phase}:positions",
                account_query_id=f"c01-root:{worker['run_nonce']}:{phase}:funds",
                order_query_sequence=query_sequences["OnRspQryOrder"],
                position_query_sequence=query_sequences["OnRspQryInvestorPosition"],
                account_query_sequence=query_sequences["OnRspQryTradingAccount"],
                open_order_refs=open_refs,
                positions=positions,
                funds=funds,
                callback_names=tuple(query_callbacks),
                source="ctp_provider_callback",
                evidence_sha256=hashlib.sha256(
                    # The private snapshot bytes remain held by the caller; this
                    # value is an internal typed reference only.
                    protocol.canonical_json_bytes(document)
                ).hexdigest(),
                query_error_ids=query_errors,
                query_is_last=query_last,
                client_instance_id=document["client"]["instance_id"],
                arrival_generation=document["client"]["arrival_generation"],
                query_native_request_ids=query_ids,
                query_round_id=f"c01-root-round:{worker['run_nonce']}:{phase}",
                query_id_origin="local_query_coordinator",
                query_round_id_origin="local_query_coordinator",
                sequence_origin="local_sdk_callback_arrival",
                timestamp_origin="local_sdk_capture_clock",
                query_issued_request_receipts=issued_receipts,
                query_request_generations=request_generations,
                query_arrival_times_utc=query_times,
                query_arrival_monotonic=query_monotonic,
                session_identity_origin="derived_from_same_client_generation_native_login",
            )
        )
    return CompletionEvidence(
        case_id="C01",
        scenario_evidence=tuple(auth_login),
        snapshots=tuple(account_snapshots),
    )


def _issue_receipt(
    receipt_type,
    protocol: ModuleType,
    request: Mapping[str, Any],
    phase: str,
    client: Mapping[str, Any],
):
    if type(request.get("return_code")) is not int or request["return_code"] != 0:
        raise C01RootBridgeError("candidate_request_ledger_invalid")
    canonical = protocol.canonical_json_bytes(dict(request))
    digest = hashlib.sha256(canonical).hexdigest()
    return receipt_type(
        request_kind=(request["family"] if request["kind"] == "query" else request["kind"]),
        phase=phase,
        request_id=request["request_id"],
        request_generation=request["request_generation"],
        client_instance_id=client["instance_id"],
        arrival_generation=client["arrival_generation"],
        issued_at_utc=request["issued_at_utc"],
        issued_monotonic=request["issued_monotonic_ns"] / 1_000_000_000,
        receipt_id=digest,
        ledger_entry_sha256=digest,
        send_return_code=request["return_code"],
    )


def _biz_type_state(value: Any) -> str:
    if type(value) is str:
        # Older pinned schemas expose a scalar that the bridge does not
        # interpret. It remains unclassified rather than becoming a known type.
        return "unclassified"
    if type(value) is dict:
        if value.get("state") == "unknown" and value.get("reason") == "nul_only":
            return "unknown_nul_only"
        if value.get("state") == "observed" and type(value.get("value")) is str:
            return "observed"
    raise C01RootBridgeError("candidate_biz_type_state_invalid")


def _utc_sort_key(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00"))
