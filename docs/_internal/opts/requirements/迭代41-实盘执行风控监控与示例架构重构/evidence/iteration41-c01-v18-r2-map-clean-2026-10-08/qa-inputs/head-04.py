"""Offline contract for evidence collected from real CTP provider callbacks.

This module deliberately has no Store, Broker, SDK, network, or configuration
dependency.  It is not registered as a case runner and has no order-writing
surface.  A future adapter may call :meth:`CaseEvidenceEngine.record_callback`
directly from the named CTP SPI callback after attaching its redacted evidence
digest.  The state ``EVIDENCE_COMPLETE_REQUIRES_REVIEW`` is not a certification
PASS; an in-process caller can always forge data, so this module is not an
authorization or authenticity boundary.
"""

from __future__ import annotations

import ast
import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .certification import SCENARIOS_BY_CASE_ID, all_certification_scenarios


class PlanContractError(ValueError):
    """Raised when a descriptive case plan is not statically checkable."""


class EvidenceContractError(ValueError):
    """Raised when callback evidence fails the provider event contract."""


class EngineState(str, Enum):
    WAITING_EXTERNAL = "WAITING_EXTERNAL"
    COLLECTING = "COLLECTING_PROVIDER_EVIDENCE"
    EXTERNAL_CONDITION_UNAVAILABLE = "EXTERNAL_CONDITION_UNAVAILABLE"
    STOP_AND_RECONCILE = "STOP_AND_RECONCILE"
    EVIDENCE_COMPLETE_REQUIRES_REVIEW = "EVIDENCE_COMPLETE_REQUIRES_REVIEW"


class DependencyState(str, Enum):
    UNKNOWN = "UNKNOWN"
    SATISFIED = "SATISFIED"
    UNAVAILABLE = "UNAVAILABLE"


class EvidenceSource(str, Enum):
    PROVIDER_CALLBACK = "provider_callback"
    MANAGED_RUNTIME = "managed_runtime_receipt"
    RUNTIME_MONITOR = "runtime_monitor_receipt"
    LOCAL_VALIDATOR = "local_validator_receipt"
    CONTROL_PLANE = "control_plane_receipt"


class CertificationState(str, Enum):
    BLOCKED = "BLOCKED"
    INCOMPLETE = "INCOMPLETE"
    EXTERNAL_CONDITION_UNAVAILABLE = "EXTERNAL_CONDITION_UNAVAILABLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class ProviderFact(str, Enum):
    ORDER_ACCEPTED = "order_accepted"
    ORDER_PARTIAL = "order_partial"
    ORDER_CANCELED = "order_canceled"
    ORDER_FILLED = "order_filled"
    ORDER_REJECTED = "order_rejected"
    TRADE_EXECUTION = "trade_execution"
    POSITION_SNAPSHOT = "position_snapshot"
    ORDER_SNAPSHOT = "order_snapshot"


@dataclass(frozen=True)
class DescriptiveCasePlan:
    case_id: str
    name: str
    values: Mapping[str, Any]
    source_path: str
    source_sha256: str


def load_descriptive_case_plan(
    source_path: str | Path,
    *,
    expected_case_id: str | None = None,
    expected_scenario_id: str | None = None,
) -> DescriptiveCasePlan:
    """Read a legacy ``CASE_PLAN`` or structured ``PLAN`` without importing it.

    Python source is parsed as an AST and only literal assignments are accepted;
    no strategy module code is executed.  This provides a common static check
    for all 33 case directories while the callback state model below covers the
    first five order scenarios in detail.
    """

    path = Path(source_path)
    try:
        source_bytes = path.read_bytes()
        source_text = source_bytes.decode("utf-8")
        tree = ast.parse(source_text, filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise PlanContractError(f"cannot parse plan source: {path}") from exc

    assignments: dict[str, Any] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in {
            "CASE_ID",
            "CASE_NAME",
            "CASE_PLAN",
            "PLAN",
        }:
            continue
        try:
            assignments[target.id] = ast.literal_eval(node.value)
        except (ValueError, TypeError) as exc:
            raise PlanContractError(f"{target.id} must be a static literal in {path}") from exc

    case_id = assignments.get("CASE_ID")
    if not isinstance(case_id, str) or not case_id:
        raise PlanContractError(f"missing static CASE_ID in {path}")
    if expected_case_id is not None and case_id != expected_case_id:
        raise PlanContractError(f"CASE_ID {case_id!r} does not match {expected_case_id!r}")

    plan = assignments.get("CASE_PLAN", assignments.get("PLAN"))
    if not isinstance(plan, dict):
        raise PlanContractError(f"missing static CASE_PLAN/PLAN mapping in {path}")
    plan_case_id = plan.get("case_id", case_id)
    if plan_case_id != case_id:
        raise PlanContractError(f"plan case_id {plan_case_id!r} does not match {case_id!r}")

    name = assignments.get("CASE_NAME") or str(plan.get("objective") or case_id)
    if not isinstance(name, str) or not name.strip():
        raise PlanContractError(f"case name must be non-empty in {path}")
    _require_text_sequence(plan, "actions", path)
    evidence_key = "evidence" if "evidence" in plan else "completion_criteria"
    _require_text_sequence(plan, evidence_key, path)

    if "evidence_mode" in plan and plan["evidence_mode"] != "REAL":
        raise PlanContractError(f"structured plan must declare evidence_mode=REAL in {path}")
    if "status" in plan and plan["status"] != "PLANNED":
        raise PlanContractError(f"structured plan must remain PLANNED in {path}")
    scenario_id = plan.get("scenario_id")
    if expected_scenario_id is not None:
        if scenario_id is not None and scenario_id != expected_scenario_id:
            raise PlanContractError(
                f"scenario_id {scenario_id!r} does not match {expected_scenario_id!r}"
            )
        if scenario_id is None and expected_case_id is not None:
            # The old descriptive form gets its authoritative scenario mapping
            # from common.certification, passed by the caller for comparison.
            scenario_id = expected_scenario_id
    if scenario_id is not None and not isinstance(scenario_id, str):
        raise PlanContractError(f"scenario_id must be a string in {path}")

    return DescriptiveCasePlan(
        case_id=case_id,
        name=name,
        values=dict(plan),
        source_path=str(path),
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
    )


def _require_text_sequence(plan: Mapping[str, Any], key: str, path: Path) -> None:
    value = plan.get(key)
    if isinstance(value, str):
        items = (value,)
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        raise PlanContractError(f"{key} must be a non-empty text sequence in {path}")
    if not items or any(not isinstance(item, str) or not item.strip() for item in items):
        raise PlanContractError(f"{key} must contain non-empty text items in {path}")


@dataclass(frozen=True)
class EventProvenancePolicy:
    source: EvidenceSource
    callbacks: tuple[str, ...] = ()
    required_fields: tuple[str, ...] = ()
    requires_provider_scope: bool = False
    requires_control_attestation: bool = False


# These rules cover every canonical event in common.certification.  A local
# event name cannot satisfy a native callback rule; runtime intent/monitor and
# control-plane events each have a distinct evidence source contract.
EVENT_PROVENANCE_POLICIES: dict[str, EventProvenancePolicy] = {
    "store_auth_success": EventProvenancePolicy(
        EvidenceSource.PROVIDER_CALLBACK,
        ("OnRspAuthenticate",),
        ("request_id", "is_last", "error_id", "authentication_succeeded"),
    ),
    "store_login_success": EventProvenancePolicy(
        EvidenceSource.PROVIDER_CALLBACK,
        ("OnRspUserLogin",),
        (
            "request_id",
            "is_last",
            "error_id",
            "provider_front_id",
            "provider_session_id",
            "trading_day",
            "login_succeeded",
        ),
    ),
    "store_connected": EventProvenancePolicy(
        EvidenceSource.PROVIDER_CALLBACK,
        ("OnFrontConnected", "OnRspUserLogin", "OnRspSubMarketData"),
        requires_provider_scope=True,
    ),
    "store_disconnected": EventProvenancePolicy(
        EvidenceSource.PROVIDER_CALLBACK, ("OnFrontDisconnected",), requires_provider_scope=True
    ),
    "store_reconnect_success": EventProvenancePolicy(
        EvidenceSource.PROVIDER_CALLBACK,
        (
            "OnFrontConnected",
            "OnRspAuthenticate",
            "OnRspUserLogin",
            "OnRspSubMarketData",
        ),
        (
            "previous_session_id",
            "new_session_id",
            "auth_error_id",
            "login_error_id",
            "subscription_error_id",
            "authentication_succeeded",
            "login_succeeded",
            "subscription_succeeded",
        ),
        requires_provider_scope=True,
    ),
    "store_ready": EventProvenancePolicy(
        EvidenceSource.PROVIDER_CALLBACK,
        ("OnRspUserLogin", "OnRspSubMarketData"),
        requires_provider_scope=True,
    ),
    "order_submit_request": EventProvenancePolicy(
        EvidenceSource.MANAGED_RUNTIME,
        required_fields=("trace_id", "invocation_id", "order_ref", "dispatch_state"),
    ),
    "order_cancel_request": EventProvenancePolicy(
        EvidenceSource.MANAGED_RUNTIME,
        required_fields=("trace_id", "invocation_id", "order_ref", "dispatch_state"),
    ),
    "batch_cancel_requested": EventProvenancePolicy(
        EvidenceSource.MANAGED_RUNTIME,
        required_fields=("trace_id", "invocation_id", "order_refs", "dispatch_state"),
    ),
    "order_status_accepted": EventProvenancePolicy(
        EvidenceSource.PROVIDER_CALLBACK,
        ("OnRtnOrder",),
        ("order_ref", "external_order_id", "provider_status"),
        True,
    ),
    "order_status_canceled": EventProvenancePolicy(
        EvidenceSource.PROVIDER_CALLBACK,
        ("OnRtnOrder",),
        ("order_ref", "external_order_id", "provider_status"),
        True,
    ),
    "trade_execution": EventProvenancePolicy(
        EvidenceSource.PROVIDER_CALLBACK,
        ("OnRtnTrade",),
        ("order_ref", "trade_id", "external_order_id"),
        True,
    ),
    "order_reject_remote": EventProvenancePolicy(
        EvidenceSource.PROVIDER_CALLBACK,
        ("OnRspOrderInsert", "OnErrRtnOrderInsert", "OnRtnOrder"),
        ("order_ref", "ErrorID", "ErrorMsg", "StatusMsg"),
        True,
    ),
    "risk_repeat_order_detected": EventProvenancePolicy(
        EvidenceSource.RUNTIME_MONITOR,
        required_fields=("trace_id", "repeat_key", "repeat_count", "monitor_digest"),
    ),
    "risk_repeat_cancel_detected": EventProvenancePolicy(
        EvidenceSource.RUNTIME_MONITOR,
        required_fields=("trace_id", "repeat_key", "repeat_count", "monitor_digest"),
    ),
    "risk_threshold_configured": EventProvenancePolicy(
        EvidenceSource.RUNTIME_MONITOR,
        required_fields=("trace_id", "configuration_digest", "monitor_digest"),
    ),
    "risk_threshold_triggered": EventProvenancePolicy(
        EvidenceSource.RUNTIME_MONITOR,
        required_fields=("trace_id", "threshold", "observed_value", "monitor_digest"),
    ),
    "risk_monitor_event": EventProvenancePolicy(
        EvidenceSource.RUNTIME_MONITOR,
        required_fields=("trace_id", "metric", "monitor_digest"),
    ),
    "order_validation_rejected": EventProvenancePolicy(
        EvidenceSource.LOCAL_VALIDATOR,
        required_fields=(
            "trace_id",
            "validator_digest",
            "reference_data_digest",
            "validation_rule",
            "error_msg",
            "dispatch_absent",
        ),
    ),
    "account_trading_disabled": EventProvenancePolicy(
        EvidenceSource.CONTROL_PLANE,
        ("OnRspOrderInsert",),
        required_fields=(
            "account_id_masked",
            "reason",
            "authorization_ref",
            "independent_account_permission_evidence_ref",
            "blocked_order_ref",
            "ErrorID",
            "ErrorMsg",
            "permission_restored_ref",
        ),
        requires_provider_scope=True,
        requires_control_attestation=True,
    ),
    "strategy_trading_paused": EventProvenancePolicy(
        EvidenceSource.CONTROL_PLANE,
        required_fields=("strategy_id", "reason", "authorization_ref"),
        requires_control_attestation=True,
    ),
    "gateway_force_logout_requested": EventProvenancePolicy(
        EvidenceSource.CONTROL_PLANE,
        ("OnFrontDisconnected",),
        (
            "gateway_key",
            "reason",
            "authorization_ref",
            "gateway_released",
            "operator_termination_evidence_ref",
            "post_disconnect_write_guard_evidence_ref",
        ),
        True,
        True,
    ),
}

_EXTRA_REQUIRED_EVENTS_BY_CASE: dict[str, tuple[str, ...]] = {
    # Historical certification rows omit the triggering submit intent from
    # these scenarios.  The current real plans require it for correlation.
    "T03": ("order_submit_request",),
    "E01": ("order_submit_request",),
    "E02": ("order_submit_request",),
    "E03": ("order_submit_request",),
    "EM01": ("order_submit_request", "order_reject_remote"),
    "B01": ("order_submit_request",),
    "B02": ("order_submit_request",),
    # M02's supervised fault plan restores transport before its final account
    # queries; the restored provider session needs its own callback evidence.
    "M02": ("store_reconnect_success",),
    "M03": ("store_disconnected",),
}
_EXPECTED_PROVIDER_REJECTION_CLASS = {
    "E01": "insufficient_funds",
    "E02": "insufficient_position",
    "E03": "market_state",
    "EM01": "account_permission_denied",
}
_EXPECTED_VALIDATION_RULE = {
    "V01": "instrument",
    "V02": "price_tick",
    "V03": "max_order_size",
}


@dataclass(frozen=True)
class IssuedRequestReceipt:
    """Typed local receipt for a request issued through the SDK boundary.

    This is a correlation record, not provider-issued evidence. A future trusted
    adapter must verify it against its actual issuer-side ledger before admitting
    C01 evidence.
    """

    request_kind: str
    phase: str
    request_id: int
    request_generation: int
    client_instance_id: str
    arrival_generation: int
    issued_at_utc: str
    issued_monotonic: float
    receipt_id: str
    ledger_entry_sha256: str
    send_return_code: int = 0
    ledger_origin: str = "local_sdk_request_ledger"
    issued_at_origin: str = "local_sdk_call_boundary"


@dataclass(frozen=True)
class LocalCallbackArrival:
    """Collector metadata kept separate from native callback payload fields.

    CTP does not supply a timestamp or monotonic event sequence for the C01
    authenticate/login responses. These values describe local SDK capture and
    the client/connection that received the callback; they are never provider
    issued identity or time. ``request_id`` is the echoed native nRequestID;
    ``request_generation`` and ``arrival_generation`` are local correlators.
    """

    client_instance_id: str
    request_generation: int
    arrival_generation: int
    source_sequence: int
    arrived_at_utc: str
    arrived_monotonic: float
    issued_request_receipt: IssuedRequestReceipt | None = None
    sequence_origin: str = "local_sdk_callback_arrival"
    timestamp_origin: str = "local_sdk_capture_clock"


@dataclass(frozen=True)
class CertificationEvidence:
    event_kind: str
    source: EvidenceSource
    event_id: str
    evidence_sha256: str
    occurred_at_utc: str
    fields: Mapping[str, Any]
    callback_names: tuple[str, ...] = ()
    provider_session_id: str = ""
    trading_day: str = ""
    provider_front_id: int | None = None
    source_sequence: int = 0
    actor_id_hash: str = ""
    signature_sha256: str = ""
    callback_arrival: LocalCallbackArrival | None = None


class CertificationEvidenceTracker:
    """Validate provenance for canonical evidence across all 33 case plans.

    Its best terminal state is REVIEW_REQUIRED.  This tracker only validates
    evidence shape and source lineage; it cannot authenticate the source or
    declare a real provider result.
    """

    def __init__(self, case_id: str):
        try:
            self.scenario = SCENARIOS_BY_CASE_ID[case_id]
        except KeyError as exc:
            raise ValueError(f"unknown certification case {case_id!r}") from exc
        self._events: list[CertificationEvidence] = []
        self._event_ids: set[str] = set()
        self._sequences: dict[str, int] = {}
        self._callback_arrivals: dict[tuple[str, int], int] = {}
        self._provider_scope: tuple[str, str] | None = None
        self._unavailable: dict[str, str] = {}
        self._case_engine = CaseEvidenceEngine(case_id) if case_id in CASE_PLANS else None

    @property
    def required_events(self) -> tuple[str, ...]:
        extras = _EXTRA_REQUIRED_EVENTS_BY_CASE.get(self.scenario.case_id, ())
        return tuple(dict.fromkeys((*self.scenario.required_events, *extras)))

    def record(self, evidence: CertificationEvidence) -> None:
        if evidence.event_kind not in self.required_events:
            raise EvidenceContractError(
                f"event {evidence.event_kind!r} is not required by {self.scenario.case_id}"
            )
        policy = EVENT_PROVENANCE_POLICIES.get(evidence.event_kind)
        if policy is None:
            raise EvidenceContractError(f"no provenance policy for {evidence.event_kind!r}")
        if evidence.source is not policy.source:
            raise EvidenceContractError(
                f"{evidence.event_kind} requires source {policy.source.value}"
            )
        if not evidence.event_id or not _SHA256_RE.fullmatch(evidence.evidence_sha256):
            raise EvidenceContractError("evidence requires an event id and SHA-256 digest")
        if evidence.event_id in self._event_ids:
            raise EvidenceContractError("duplicate evidence event_id")
        try:
            observed_at = datetime.fromisoformat(evidence.occurred_at_utc.replace("Z", "+00:00"))
        except ValueError as exc:
            raise EvidenceContractError("occurred_at_utc must be ISO-8601") from exc
        if observed_at.tzinfo is None or observed_at.utcoffset() != timezone.utc.utcoffset(
            observed_at
        ):
            raise EvidenceContractError("occurred_at_utc must carry a UTC offset")
        missing_fields = [
            field_name
            for field_name in policy.required_fields
            if _is_missing(evidence.fields.get(field_name))
        ]
        if missing_fields:
            raise EvidenceContractError(
                f"{evidence.event_kind} lacks source fields: {', '.join(missing_fields)}"
            )
        if evidence.event_kind == "order_reject_remote":
            callback_present = bool(set(policy.callbacks) & set(evidence.callback_names))
        else:
            callback_present = set(policy.callbacks).issubset(evidence.callback_names)
        if policy.callbacks and not callback_present:
            missing = sorted(set(policy.callbacks) - set(evidence.callback_names))
            raise EvidenceContractError(
                f"{evidence.event_kind} lacks native callbacks: {', '.join(missing)}"
            )
        if evidence.event_kind in {"store_auth_success", "store_login_success"}:
            _validate_c01_callback_evidence(evidence)
            arrival = evidence.callback_arrival
            arrival_key = (arrival.client_instance_id, arrival.arrival_generation)
            previous_arrival = self._callback_arrivals.get(arrival_key, 0)
            if arrival.source_sequence <= previous_arrival:
                raise EvidenceContractError(
                    "C01 local callback arrival sequence must strictly increase per connection"
                )
            self._callback_arrivals[arrival_key] = arrival.source_sequence
        if policy.requires_provider_scope:
            if not evidence.provider_session_id or not evidence.trading_day:
                raise EvidenceContractError("provider evidence requires session_id and trading_day")
            current_scope = (evidence.provider_session_id, evidence.trading_day)
            if (
                self.scenario.case_id in {"M02", "M03"}
                and evidence.event_kind == "store_reconnect_success"
            ):
                disconnects = [
                    item for item in self._events if item.event_kind == "store_disconnected"
                ]
                if len(disconnects) != 1 or any(
                    item.event_kind == "store_reconnect_success" for item in self._events
                ):
                    raise EvidenceContractError("restoration requires one prior disconnect")
                disconnected = disconnects[0]
                disconnected_at = datetime.fromisoformat(
                    disconnected.occurred_at_utc.replace("Z", "+00:00")
                )
                if (
                    evidence.provider_session_id == disconnected.provider_session_id
                    or evidence.trading_day != disconnected.trading_day
                    or evidence.fields.get("previous_session_id")
                    != disconnected.provider_session_id
                    or evidence.fields.get("new_session_id") != evidence.provider_session_id
                    or evidence.fields.get("gateway_key") != disconnected.fields.get("gateway_key")
                    or observed_at <= disconnected_at
                ):
                    raise EvidenceContractError(
                        "restoration does not match the disconnected provider session"
                    )
            if self._provider_scope is not None and current_scope != self._provider_scope:
                if not (
                    self.scenario.case_id in {"M02", "M03"}
                    and evidence.event_kind == "store_reconnect_success"
                ):
                    raise EvidenceContractError(
                        "one certification case cannot mix provider sessions"
                    )
            self._provider_scope = current_scope
            if evidence.source_sequence < 1:
                raise EvidenceContractError("provider evidence requires positive source_sequence")
            previous = self._sequences.get(evidence.provider_session_id, 0)
            if evidence.source_sequence <= previous:
                raise EvidenceContractError("provider source_sequence must strictly increase")
            self._sequences[evidence.provider_session_id] = evidence.source_sequence
        if policy.requires_control_attestation:
            if not evidence.actor_id_hash or not _SHA256_RE.fullmatch(evidence.signature_sha256):
                raise EvidenceContractError(
                    "control-plane evidence requires actor hash and signed receipt digest"
                )
        if evidence.event_kind == "order_validation_rejected":
            if evidence.fields.get("dispatch_absent") is not True:
                raise EvidenceContractError(
                    "local validation rejection requires evidence that provider dispatch was absent"
                )
            if evidence.fields.get("validation_rule") != _EXPECTED_VALIDATION_RULE.get(
                self.scenario.case_id
            ):
                raise EvidenceContractError("validation rejection does not match this case's rule")
        if evidence.event_kind == "order_reject_remote":
            try:
                error_id = int(evidence.fields.get("ErrorID"))
            except (TypeError, ValueError) as exc:
                raise EvidenceContractError(
                    "provider rejection ErrorID must be an integer"
                ) from exc
            if error_id <= 0:
                raise EvidenceContractError("provider rejection ErrorID must be positive")
            expected_class = _EXPECTED_PROVIDER_REJECTION_CLASS.get(self.scenario.case_id)
            if expected_class and evidence.fields.get("verified_rejection_class") != expected_class:
                raise EvidenceContractError(
                    f"provider response is not verified as {expected_class}"
                )
            if expected_class and _is_missing(evidence.fields.get("error_mapping_evidence_ref")):
                raise EvidenceContractError(
                    "provider error classification needs its review evidence"
                )
            if self.scenario.case_id == "E03":
                if _is_missing(evidence.fields.get("market_state_evidence_ref")):
                    raise EvidenceContractError(
                        "E03 requires independent provider market-state evidence"
                    )
                if _is_missing(evidence.fields.get("market_state_source_event_id")):
                    raise EvidenceContractError(
                        "E03 market-state evidence must correlate to a source event"
                    )
        if evidence.event_kind == "store_connected":
            if evidence.fields.get("market_connection") is not True:
                raise EvidenceContractError("market connection must be provider-confirmed")
            if evidence.fields.get("trade_connection") is not True:
                raise EvidenceContractError("trade connection must be provider-confirmed")
        if evidence.event_kind == "order_status_accepted":
            if evidence.fields.get("provider_status") not in {"accepted", "working"}:
                raise EvidenceContractError("provider order status is not accepted/working")
        if evidence.event_kind == "order_status_canceled":
            if evidence.fields.get("provider_status") not in {"canceled", "cancelled"}:
                raise EvidenceContractError("provider order status is not canceled")
        if evidence.event_kind == "store_auth_success":
            if evidence.fields.get("authentication_succeeded") is not True:
                raise EvidenceContractError("authentication callback does not report success")
            if _integer_value(evidence.fields.get("error_id")) != 0:
                raise EvidenceContractError("authentication ErrorID must be zero")
        if evidence.event_kind == "store_login_success":
            if evidence.fields.get("login_succeeded") is not True:
                raise EvidenceContractError("login callback does not report success")
            if _integer_value(evidence.fields.get("error_id")) != 0:
                raise EvidenceContractError("login ErrorID must be zero")
        if evidence.event_kind == "store_reconnect_success":
            if evidence.fields.get("previous_session_id") == evidence.fields.get("new_session_id"):
                raise EvidenceContractError(
                    "reconnect evidence must identify a new provider session"
                )
            if (
                any(
                    type(evidence.fields.get(key)) is not int or evidence.fields.get(key) != 0
                    for key in ("auth_error_id", "login_error_id", "subscription_error_id")
                )
                or any(
                    key in evidence.fields
                    and (type(evidence.fields.get(key)) is not int or evidence.fields.get(key) != 0)
                    for key in ("ErrorID", "error_id")
                )
                or any(
                    evidence.fields.get(key) is not True
                    for key in (
                        "authentication_succeeded",
                        "login_succeeded",
                        "subscription_succeeded",
                    )
                )
            ):
                raise EvidenceContractError(
                    "restored provider authentication, login, and subscription must succeed"
                )
        if evidence.event_kind == "gateway_force_logout_requested":
            if evidence.fields.get("gateway_released") is not True:
                raise EvidenceContractError(
                    "force logout requires completed gateway release evidence"
                )
        self._events.append(evidence)
        self._event_ids.add(evidence.event_id)


    def mark_external_unavailable(self, event_kind: str, reason: str, evidence_ref: str) -> None:
        """Record a sourced external condition that prevents this plan from running."""

        if event_kind not in self.required_events:
            raise EvidenceContractError(f"unexpected unavailable event {event_kind!r}")
        if not reason.strip() or not evidence_ref.strip():
            raise EvidenceContractError("external unavailability requires reason and evidence_ref")
        self._unavailable[event_kind] = reason

    def record_provider_callback(self, evidence: "ProviderCallbackEvidence") -> None:
        """Feed selected order scenarios into the stricter per-order model."""

        if self._case_engine is None:
            raise EvidenceContractError(
                f"{self.scenario.case_id} has no specialized order callback model"
            )
        self._case_engine.record_callback(evidence)

    def record_order_dependency(
        self,
        dependency_id: str,
        state: DependencyState,
        *,
        source: str,
        evidence_ref: str,
        reason: str = "",
    ) -> None:
        if self._case_engine is None:
            raise EvidenceContractError(
                f"{self.scenario.case_id} has no specialized order callback model"
            )
        self._case_engine.record_dependency(
            dependency_id, state, source=source, evidence_ref=evidence_ref, reason=reason
        )

    def snapshot(self) -> dict[str, Any]:
        event_kinds = {event.event_kind for event in self._events}
        event_fields: dict[str, set[str]] = {}
        for event in self._events:
            event_fields.setdefault(event.event_kind, set()).update(
                key for key, value in event.fields.items() if not _is_missing(value)
            )
        present_fields = set().union(*event_fields.values()) if event_fields else set()
        missing_events = [event for event in self.required_events if event not in event_kinds]
        missing_fields = [
            name for name in self.scenario.evidence_fields if name not in present_fields
        ]
        missing_policy_events = [
            event for event in self.required_events if event not in EVENT_PROVENANCE_POLICIES
        ]
        missing_correlations = self._missing_order_correlations()
        missing_correlations.extend(self._missing_c01_correlations())
        if self.scenario.case_id == "C01":
            missing_correlations.append(
                "C01 trusted issuer-side request ledger verifier is not wired into this tracker"
            )
        order_snapshot = self._case_engine.snapshot() if self._case_engine is not None else None
        if self._unavailable or (
            order_snapshot
            and order_snapshot["state"] == EngineState.EXTERNAL_CONDITION_UNAVAILABLE.value
        ):
            state = CertificationState.EXTERNAL_CONDITION_UNAVAILABLE
        elif not self._events and not (
            order_snapshot and order_snapshot["provider_callback_count"]
        ):
            state = CertificationState.BLOCKED
        elif (
            missing_events
            or missing_fields
            or missing_policy_events
            or missing_correlations
            or (
                order_snapshot
                and order_snapshot["state"] != EngineState.EVIDENCE_COMPLETE_REQUIRES_REVIEW.value
            )
        ):
            state = CertificationState.INCOMPLETE
        else:
            state = CertificationState.REVIEW_REQUIRED
        return {
            "case_id": self.scenario.case_id,
            "scenario_id": self.scenario.scenario_id,
            "state": state.value,
            "certification_pass": False,
            "required_events": list(self.required_events),
            "observed_events": sorted(event_kinds),
            "missing_events": missing_events,
            "required_evidence_fields": list(self.scenario.evidence_fields),
            "missing_evidence_fields": missing_fields,
            "missing_provenance_policies": missing_policy_events,
            "missing_event_correlations": missing_correlations,
            "unavailable_conditions": dict(self._unavailable),
            "evidence_sha256": [event.evidence_sha256.lower() for event in self._events],
            "order_callback_model": order_snapshot,
            "missing_order_callback_facts": (
                list(order_snapshot["missing_facts"]) if order_snapshot else []
            ),
        }

    def _missing_c01_correlations(self) -> list[str]:
        if self.scenario.case_id != "C01":
            return []
        auth = [item for item in self._events if item.event_kind == "store_auth_success"]
        login = [item for item in self._events if item.event_kind == "store_login_success"]
        if len(auth) != 1 or len(login) != 1:
            return []
        auth_row, login_row = auth[0], login[0]
        auth_arrival, login_arrival = auth_row.callback_arrival, login_row.callback_arrival
        if auth_arrival is None or login_arrival is None:
            return ["C01 auth/login require local callback arrival and issued receipts"]
        request_ids = (auth_row.fields.get("request_id"), login_row.fields.get("request_id"))
        if (
            auth_arrival.client_instance_id != login_arrival.client_instance_id
            or auth_arrival.arrival_generation != login_arrival.arrival_generation
            or auth_arrival.request_generation == login_arrival.request_generation
        ):
            return ["C01 auth/login must share client generation and use distinct requests"]
        if (
            type(request_ids[0]) is not int
            or type(request_ids[1]) is not int
            or request_ids[0] == request_ids[1]
        ):
            return ["C01 auth/login must use distinct native RequestIDs"]
        auth_receipt_ok = validate_issued_request_receipt(
            auth_arrival.issued_request_receipt,
            request_kind="authenticate",
            phase="",
            request_id=request_ids[0],
            request_generation=auth_arrival.request_generation,
            client_instance_id=auth_arrival.client_instance_id,
            arrival_generation=auth_arrival.arrival_generation,
            arrived_at_utc=auth_arrival.arrived_at_utc,
            arrived_monotonic=auth_arrival.arrived_monotonic,
        )
        login_receipt_ok = validate_issued_request_receipt(
            login_arrival.issued_request_receipt,
            request_kind="login",
            phase="",
            request_id=request_ids[1],
            request_generation=login_arrival.request_generation,
            client_instance_id=login_arrival.client_instance_id,
            arrival_generation=login_arrival.arrival_generation,
            arrived_at_utc=login_arrival.arrived_at_utc,
            arrived_monotonic=login_arrival.arrived_monotonic,
        )
        if not auth_receipt_ok or not login_receipt_ok:
            return ["C01 auth/login require matching typed issued-request receipts"]
        ledger_gate = "C01 requires a trusted issuer-side request ledger verifier; none is wired here"
        if (
            auth_arrival.issued_request_receipt.receipt_id
            == login_arrival.issued_request_receipt.receipt_id
        ):
            return ["C01 auth/login issued-request receipts must be distinct"]
        if (
            auth_arrival.source_sequence >= login_arrival.source_sequence
            or _utc_timestamp(auth_arrival.arrived_at_utc) is None
            or _utc_timestamp(login_arrival.arrived_at_utc) is None
            or _utc_timestamp(auth_arrival.arrived_at_utc)
            >= _utc_timestamp(login_arrival.arrived_at_utc)
        ):
            return ["C01 auth/login local callback arrival order is invalid"]
        return [ledger_gate]

    def _missing_order_correlations(self) -> list[str]:
        submitted = {
            str(event.fields.get("order_ref"))
            for event in self._events
            if event.event_kind == "order_submit_request"
            and not _is_missing(event.fields.get("order_ref"))
        }
        if not submitted:
            return []
        required_refs = set(submitted)
        if self._case_engine is not None:
            required_refs.update(self._case_engine.accepted_order_refs)
        provider_refs = {
            str(event.fields.get("order_ref"))
            for event in self._events
            if event.event_kind
            in {
                "order_reject_remote",
                "order_cancel_request",
                "trade_execution",
            }
            and not _is_missing(event.fields.get("order_ref"))
        }
        provider_refs.update(
            str(event.fields.get("blocked_order_ref"))
            for event in self._events
            if event.event_kind == "account_trading_disabled"
            and not _is_missing(event.fields.get("blocked_order_ref"))
        )
        missing = [f"order_ref:{ref}" for ref in sorted(provider_refs - submitted)]
        if self.scenario.case_id in {
            "T01",
            "T02",
            "T03",
            "E01",
            "E02",
            "E03",
            "EM01",
            "L01",
        }:
            if self._case_engine is not None:
                missing.extend(
                    f"provider_order_ref:{ref}"
                    for ref in sorted(self._case_engine.accepted_order_refs - submitted)
                )
        if self.scenario.case_id in {"B01", "B02"}:
            batch_refs = {
                str(ref)
                for event in self._events
                if event.event_kind == "batch_cancel_requested"
                for ref in (event.fields.get("order_refs") or [])
            }
            if required_refs - batch_refs:
                missing.append("batch_cancel_refs_match_submitted_orders")
        return missing


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == ()


def _integer_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def unmapped_required_events() -> list[str]:
    """Return canonical required events lacking an explicit source policy."""

    required = {
        event for scenario in all_certification_scenarios() for event in scenario.required_events
    }
    return sorted(required - EVENT_PROVENANCE_POLICIES.keys())


@dataclass(frozen=True)
class CasePlan:
    case_id: str
    scenario_id: str
    minimum_orders: int
    dependencies: tuple[str, ...]


CASE_PLANS: dict[str, CasePlan] = {
    "T01": CasePlan(
        "T01",
        "TRADE-OPEN-01",
        1,
        ("reviewed_order_admission", "active_provider_session", "provider_acceptance"),
    ),
    "T02": CasePlan(
        "T02",
        "TRADE-CLOSE-01",
        1,
        (
            "reviewed_order_admission",
            "active_provider_session",
            "closeable_position_confirmed",
            "provider_acceptance",
        ),
    ),
    "T03": CasePlan(
        "T03",
        "TRADE-CANCEL-01",
        1,
        ("reviewed_order_admission", "active_provider_session", "cancel_window_available"),
    ),
    "B01": CasePlan(
        "B01",
        "BATCH-CANCEL-01",
        2,
        (
            "reviewed_order_admission",
            "active_provider_session",
            "provider_partial_fill_opportunity",
            "provider_batch_cancel_capability",
        ),
    ),
    "B02": CasePlan(
        "B02",
        "BATCH-CANCEL-02",
        2,
        (
            "reviewed_order_admission",
            "active_provider_session",
            "multiple_open_orders_available",
            "provider_batch_cancel_capability",
        ),
    ),
}

_CALLBACK_FOR_FACT = {
    ProviderFact.ORDER_ACCEPTED: "OnRtnOrder",
    ProviderFact.ORDER_PARTIAL: "OnRtnOrder",
    ProviderFact.ORDER_CANCELED: "OnRtnOrder",
    ProviderFact.ORDER_FILLED: "OnRtnOrder",
    ProviderFact.ORDER_REJECTED: "OnRspOrderInsert",
    ProviderFact.TRADE_EXECUTION: "OnRtnTrade",
    ProviderFact.POSITION_SNAPSHOT: "OnRspQryInvestorPosition",
    ProviderFact.ORDER_SNAPSHOT: "OnRspQryOrder",
}
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_ALLOWED_DEPENDENCY_SOURCES = {
    "provider_callback",
    "provider_query",
    "reviewed_operator_evidence",
}


@dataclass(frozen=True)
class ProviderCallbackEvidence:
    """Redacted normalized fact emitted by a real provider callback adapter.

    ``evidence_sha256`` must identify the retained, redacted callback artifact.
    Raw account credentials or callback objects must not be stored here.
    """

    fact: ProviderFact
    callback_name: str
    source: str
    event_id: str
    session_id: str
    trading_day: str
    sequence: int
    observed_at_utc: str
    evidence_sha256: str
    order_ref: str = ""
    external_order_id: str = ""
    instrument_id: str = ""
    status: str = ""
    traded_quantity: float = 0.0
    remaining_quantity: float = 0.0
    trade_id: str = ""
    query_id: str = ""
    query_complete: bool = False
    position_phase: str = ""
    closeable_quantity: float = 0.0
    open_order_refs: tuple[str, ...] = ()
    error_id: int = 0
    error_message: str = ""


@dataclass(frozen=True)
class DependencyEvidence:
    dependency_id: str
    state: DependencyState
    source: str
    evidence_ref: str
    reason: str = ""


class CaseEvidenceEngine:
    """Accumulate provider callback facts for T01-T03/B01-B02.

    The engine can report missing or externally unavailable conditions and
    evidence ready for independent review.  It intentionally has no PASS state.
    """

    def __init__(self, case_id: str):
        try:
            self.plan = CASE_PLANS[case_id]
        except KeyError as exc:
            raise ValueError(f"no callback state model for case {case_id!r}") from exc
        self._events: list[ProviderCallbackEvidence] = []
        self._event_ids: set[str] = set()
        self._last_sequence: dict[tuple[str, str], int] = {}
        self._dependency_evidence: dict[str, DependencyEvidence] = {}
        self._order_ids: dict[str, str] = {}

    def record_dependency(
        self,
        dependency_id: str,
        state: DependencyState,
        *,
        source: str,
        evidence_ref: str,
        reason: str = "",
    ) -> None:
        """Attach external evidence; the engine cannot satisfy dependencies itself."""

        if dependency_id not in self.plan.dependencies:
            raise EvidenceContractError(f"unexpected external dependency {dependency_id!r}")
        if state is DependencyState.UNKNOWN:
            raise EvidenceContractError("UNKNOWN is implicit; provide SATISFIED or UNAVAILABLE")
        if source not in _ALLOWED_DEPENDENCY_SOURCES:
            raise EvidenceContractError(f"unsupported dependency evidence source {source!r}")
        if not evidence_ref.strip():
            raise EvidenceContractError("external dependency evidence_ref is required")
        if state is DependencyState.UNAVAILABLE and not reason.strip():
            raise EvidenceContractError("unavailable external conditions require a reason")
        self._dependency_evidence[dependency_id] = DependencyEvidence(
            dependency_id=dependency_id,
            state=state,
            source=source,
            evidence_ref=evidence_ref,
            reason=reason,
        )

    def record_callback(self, event: ProviderCallbackEvidence) -> None:
        """Record one normalized provider fact from its named native callback."""

        self._validate_callback(event)
        session_scope = (event.session_id, event.trading_day)
        if self._events:
            first = self._events[0]
            if session_scope != (first.session_id, first.trading_day):
                raise EvidenceContractError(
                    "one case run cannot mix provider sessions or trading days"
                )
        prior_sequence = self._last_sequence.get(session_scope, 0)
        if event.sequence <= prior_sequence:
            raise EvidenceContractError("provider callback sequence must strictly increase")
        if event.event_id in self._event_ids:
            raise EvidenceContractError("duplicate provider callback event_id")
        if event.order_ref and event.external_order_id:
            prior_external_id = self._order_ids.get(event.order_ref)
            if prior_external_id and prior_external_id != event.external_order_id:
                raise EvidenceContractError("provider order identity changed for an order_ref")
            self._order_ids[event.order_ref] = event.external_order_id
        elif event.fact in {
            ProviderFact.ORDER_ACCEPTED,
            ProviderFact.ORDER_PARTIAL,
            ProviderFact.ORDER_CANCELED,
            ProviderFact.ORDER_FILLED,
        }:
            raise EvidenceContractError(
                "order status callback requires order_ref and external_order_id"
            )
        self._last_sequence[session_scope] = event.sequence
        self._event_ids.add(event.event_id)
        self._events.append(event)

    def snapshot(self) -> dict[str, Any]:
        """Return a machine-readable state without granting certification."""

        unavailable = [
            item
            for item in self._dependency_evidence.values()
            if item.state is DependencyState.UNAVAILABLE
        ]
        unresolved = [
            dep
            for dep in self.plan.dependencies
            if self._dependency_evidence.get(
                dep, DependencyEvidence(dep, DependencyState.UNKNOWN, "", "")
            ).state
            is DependencyState.UNKNOWN
        ]
        missing_facts = self._missing_facts()
        state = self._derive_state(unavailable, unresolved, missing_facts)
        return {
            "case_id": self.plan.case_id,
            "scenario_id": self.plan.scenario_id,
            "state": state.value,
            "certification_pass": False,
            "accepted_order_count": len(self._accepted_orders()),
            "provider_callback_count": len(self._events),
            "missing_facts": missing_facts,
            "unresolved_external_dependencies": unresolved,
            "unavailable_external_dependencies": [
                {"dependency_id": item.dependency_id, "reason": item.reason} for item in unavailable
            ],
            "evidence_digests": [event.evidence_sha256.lower() for event in self._events],
        }

    def _validate_callback(self, event: ProviderCallbackEvidence) -> None:
        if event.source != "ctp_provider_callback":
            raise EvidenceContractError("provider facts must originate from a CTP callback adapter")
        if event.callback_name != _CALLBACK_FOR_FACT[event.fact]:
            raise EvidenceContractError(
                f"{event.fact.value} requires {_CALLBACK_FOR_FACT[event.fact]}"
            )
        if not event.event_id or not event.session_id or not event.trading_day:
            raise EvidenceContractError(
                "callback event_id, session_id, and trading_day are required"
            )
        if (
            not isinstance(event.sequence, int)
            or isinstance(event.sequence, bool)
            or event.sequence < 1
        ):
            raise EvidenceContractError("callback sequence must be a positive integer")
        if not _SHA256_RE.fullmatch(event.evidence_sha256):
            raise EvidenceContractError("redacted provider evidence must include a SHA-256 digest")
        try:
            observed_at = datetime.fromisoformat(event.observed_at_utc.replace("Z", "+00:00"))
        except ValueError as exc:
            raise EvidenceContractError("observed_at_utc must be an ISO-8601 timestamp") from exc
        if observed_at.tzinfo is None or observed_at.utcoffset() != timezone.utc.utcoffset(
            observed_at
        ):
            raise EvidenceContractError("observed_at_utc must carry a UTC offset")

        order_facts = {
            ProviderFact.ORDER_ACCEPTED,
            ProviderFact.ORDER_PARTIAL,
            ProviderFact.ORDER_CANCELED,
            ProviderFact.ORDER_FILLED,
        }
        if event.fact in order_facts and (
            not event.order_ref or not event.external_order_id or not event.instrument_id
        ):
            raise EvidenceContractError(
                "order callback must identify ref, provider id, and instrument"
            )
        if event.fact is ProviderFact.ORDER_REJECTED and (
            not event.order_ref or not event.instrument_id
        ):
            raise EvidenceContractError("rejected insert callback must identify ref and instrument")
        if event.fact in order_facts | {ProviderFact.ORDER_REJECTED}:
            if not _nonnegative_finite(event.traded_quantity) or not _nonnegative_finite(
                event.remaining_quantity
            ):
                raise EvidenceContractError(
                    "order callback quantities must be finite and non-negative"
                )
        expected_status = {
            ProviderFact.ORDER_ACCEPTED: {"accepted", "working"},
            ProviderFact.ORDER_PARTIAL: {"partial"},
            ProviderFact.ORDER_CANCELED: {"canceled"},
            ProviderFact.ORDER_FILLED: {"filled"},
            ProviderFact.ORDER_REJECTED: {"rejected"},
        }
        if event.fact in expected_status and event.status not in expected_status[event.fact]:
            raise EvidenceContractError(f"status does not match provider fact {event.fact.value}")
        if event.fact is ProviderFact.ORDER_PARTIAL:
            if not _positive_finite(event.traded_quantity) or not _positive_finite(
                event.remaining_quantity
            ):
                raise EvidenceContractError(
                    "partial order callback requires traded and remaining quantity"
                )
        if event.fact is ProviderFact.ORDER_ACCEPTED and not _positive_finite(
            event.remaining_quantity
        ):
            raise EvidenceContractError(
                "accepted working order must have positive remaining quantity"
            )
        if event.fact is ProviderFact.ORDER_CANCELED and event.remaining_quantity != 0:
            raise EvidenceContractError("canceled order callback must have zero remaining quantity")
        if event.fact is ProviderFact.ORDER_FILLED and event.remaining_quantity != 0:
            raise EvidenceContractError("filled order callback must have zero remaining quantity")
        if event.fact is ProviderFact.ORDER_FILLED and not _positive_finite(event.traded_quantity):
            raise EvidenceContractError(
                "filled order callback must report positive traded quantity"
            )
        if event.fact is ProviderFact.ORDER_REJECTED and (
            event.error_id <= 0 or not event.error_message
        ):
            raise EvidenceContractError("provider rejection requires ErrorID and ErrorMsg")
        if event.fact is ProviderFact.TRADE_EXECUTION:
            if (
                not event.order_ref
                or not event.trade_id
                or not _positive_finite(event.traded_quantity)
            ):
                raise EvidenceContractError(
                    "trade callback requires order_ref, trade_id, and positive quantity"
                )
        if event.fact is ProviderFact.POSITION_SNAPSHOT:
            if (
                not event.instrument_id
                or not event.query_id
                or not event.query_complete
                or event.position_phase not in {"baseline", "final"}
                or not _nonnegative_finite(event.closeable_quantity)
            ):
                raise EvidenceContractError(
                    "position evidence must be a complete tagged provider query"
                )
        if event.fact is ProviderFact.ORDER_SNAPSHOT:
            if not event.query_id or not event.query_complete:
                raise EvidenceContractError(
                    "order evidence must be a complete provider order query"
                )
            if any(not isinstance(ref, str) or not ref for ref in event.open_order_refs):
                raise EvidenceContractError("open_order_refs must contain non-empty order refs")

    def _accepted_orders(self) -> set[str]:
        return {
            event.order_ref for event in self._events if event.fact is ProviderFact.ORDER_ACCEPTED
        }

    @property
    def accepted_order_refs(self) -> set[str]:
        return self._accepted_orders()

    def _facts_by_order(self) -> dict[str, set[ProviderFact]]:
        facts: dict[str, set[ProviderFact]] = {}
        for event in self._events:
            if event.order_ref:
                facts.setdefault(event.order_ref, set()).add(event.fact)
        return facts

    def _missing_facts(self) -> list[str]:
        by_order = self._facts_by_order()
        accepted = self._accepted_orders()
        if any(event.fact is ProviderFact.ORDER_REJECTED for event in self._events):
            return ["provider_rejected_request"]
        final_order_snapshots = [
            event for event in self._events if event.fact is ProviderFact.ORDER_SNAPSHOT
        ]
        final_position_snapshots = [
            event
            for event in self._events
            if event.fact is ProviderFact.POSITION_SNAPSHOT and event.position_phase == "final"
        ]
        missing_reconciliation: list[str] = []
        if not final_order_snapshots:
            missing_reconciliation.append("final_provider_order_query")
        elif final_order_snapshots[-1].open_order_refs:
            missing_reconciliation.append("provider_open_orders_remain")
        provider_order_events = [
            event
            for event in self._events
            if event.fact
            in {
                ProviderFact.ORDER_ACCEPTED,
                ProviderFact.ORDER_PARTIAL,
                ProviderFact.ORDER_CANCELED,
                ProviderFact.ORDER_FILLED,
                ProviderFact.ORDER_REJECTED,
                ProviderFact.TRADE_EXECUTION,
            }
        ]
        if final_order_snapshots and provider_order_events:
            if final_order_snapshots[-1].sequence <= max(
                event.sequence for event in provider_order_events
            ):
                missing_reconciliation.append("final_order_query_must_follow_provider_events")
        any_fill = any(
            event.fact in {ProviderFact.TRADE_EXECUTION, ProviderFact.ORDER_FILLED}
            for event in self._events
        )
        if any_fill and not final_position_snapshots:
            missing_reconciliation.append("final_provider_position_query")
        if any_fill and final_position_snapshots and provider_order_events:
            if final_position_snapshots[-1].sequence <= max(
                event.sequence
                for event in provider_order_events
                if event.fact in {ProviderFact.TRADE_EXECUTION, ProviderFact.ORDER_FILLED}
            ):
                missing_reconciliation.append("final_position_query_must_follow_fills")
        if self.plan.case_id in {"T01", "T03"}:
            if len(accepted) > self.plan.minimum_orders:
                return ["unexpected_order_count_requires_reconciliation", *missing_reconciliation]
            if not accepted:
                return ["order_accepted", *missing_reconciliation]
            if self.plan.case_id == "T03" and any(
                by_order.get(ref, set()) & {ProviderFact.ORDER_FILLED} for ref in accepted
            ):
                return ["cancel_window_unavailable", *missing_reconciliation]
            terminal = {ProviderFact.ORDER_CANCELED, ProviderFact.ORDER_FILLED}
            terminal_events = [
                event
                for event in self._events
                if event.order_ref in accepted and event.fact in terminal
            ]
            accepted_events = [
                event
                for event in self._events
                if event.order_ref in accepted and event.fact is ProviderFact.ORDER_ACCEPTED
            ]
            if not terminal_events:
                return ["order_canceled_or_filled", *missing_reconciliation]
            if min(event.sequence for event in accepted_events) >= min(
                event.sequence for event in terminal_events
            ):
                return ["provider_order_transition_out_of_order", *missing_reconciliation]
            if any(self._trade_quantity_mismatch(ref) for ref in accepted):
                return ["trade_quantity_reconciliation", *missing_reconciliation]
            return missing_reconciliation
        if self.plan.case_id == "T02":
            if len(accepted) > self.plan.minimum_orders:
                return ["unexpected_order_count_requires_reconciliation", *missing_reconciliation]
            position_events = [
                event for event in self._events if event.fact is ProviderFact.POSITION_SNAPSHOT
            ]
            phases = {event.position_phase for event in position_events}
            required = []
            if "baseline" not in phases:
                required.append("baseline_position_snapshot")
            if "final" not in phases:
                required.append("final_position_snapshot")
            if not accepted:
                required.append("order_accepted")
            if accepted and not any(
                by_order.get(ref, set()) & {ProviderFact.ORDER_CANCELED, ProviderFact.ORDER_FILLED}
                for ref in accepted
            ):
                required.append("order_terminal")
            baseline = next(
                (event for event in position_events if event.position_phase == "baseline"), None
            )
            if baseline and accepted:
                first_acceptance = min(
                    event.sequence
                    for event in self._events
                    if event.fact is ProviderFact.ORDER_ACCEPTED
                )
                if baseline.sequence >= first_acceptance:
                    required.append("baseline_position_snapshot_must_precede_order")
            if any(self._trade_quantity_mismatch(ref) for ref in accepted):
                required.append("trade_quantity_reconciliation")
            if "baseline" in phases and not any(
                event.position_phase == "baseline" and event.closeable_quantity > 0
                for event in position_events
            ):
                return ["closeable_position_unavailable"]
            return [*required, *missing_reconciliation]
        if self.plan.case_id == "B01":
            qualified = {
                ref
                for ref in accepted
                if {
                    ProviderFact.ORDER_PARTIAL,
                    ProviderFact.TRADE_EXECUTION,
                    ProviderFact.ORDER_CANCELED,
                }.issubset(by_order.get(ref, set()))
            }
            required = (
                []
                if len(qualified) >= self.plan.minimum_orders and len(qualified) == len(accepted)
                else ["every_test_order_must_be_partially_filled_then_canceled"]
            )
            for ref in qualified:
                sequence_by_fact = {
                    fact: min(
                        event.sequence
                        for event in self._events
                        if event.order_ref == ref and event.fact is fact
                    )
                    for fact in (
                        ProviderFact.ORDER_ACCEPTED,
                        ProviderFact.ORDER_PARTIAL,
                        ProviderFact.ORDER_CANCELED,
                    )
                }
                if not (
                    sequence_by_fact[ProviderFact.ORDER_ACCEPTED]
                    < sequence_by_fact[ProviderFact.ORDER_PARTIAL]
                    < sequence_by_fact[ProviderFact.ORDER_CANCELED]
                ):
                    required.append(f"provider_order_transition_out_of_order:{ref}")
                if self._trade_quantity_mismatch(ref):
                    required.append(f"trade_quantity_reconciliation:{ref}")
                accepted_sequence = sequence_by_fact[ProviderFact.ORDER_ACCEPTED]
                if any(
                    event.order_ref == ref
                    and event.fact is ProviderFact.TRADE_EXECUTION
                    and event.sequence <= accepted_sequence
                    for event in self._events
                ):
                    required.append(f"provider_trade_precedes_acceptance:{ref}")
            if any_fill and not final_position_snapshots:
                required.append("final_provider_position_query")
            return [*required, *missing_reconciliation]
        if any(
            ProviderFact.ORDER_PARTIAL in by_order.get(ref, set())
            and ProviderFact.TRADE_EXECUTION not in by_order.get(ref, set())
            for ref in accepted
        ):
            return ["partial_order_missing_trade_callback", *missing_reconciliation]
        if any(
            ProviderFact.ORDER_FILLED in by_order.get(ref, set())
            and ProviderFact.TRADE_EXECUTION not in by_order.get(ref, set())
            for ref in accepted
        ):
            return ["filled_order_missing_trade_callback", *missing_reconciliation]
        for ref in accepted:
            if self._trade_quantity_mismatch(ref):
                return [f"trade_quantity_reconciliation:{ref}", *missing_reconciliation]
        for ref in accepted:
            acceptance = min(
                event.sequence
                for event in self._events
                if event.order_ref == ref and event.fact is ProviderFact.ORDER_ACCEPTED
            )
            terminal_sequences = [
                event.sequence
                for event in self._events
                if event.order_ref == ref
                and event.fact in {ProviderFact.ORDER_CANCELED, ProviderFact.ORDER_FILLED}
            ]
            if terminal_sequences and acceptance >= min(terminal_sequences):
                return [f"provider_order_transition_out_of_order:{ref}", *missing_reconciliation]
            if any(
                event.order_ref == ref
                and event.fact is ProviderFact.TRADE_EXECUTION
                and event.sequence <= acceptance
                for event in self._events
            ):
                return [f"provider_trade_precedes_acceptance:{ref}", *missing_reconciliation]
        qualified = {
            ref
            for ref in accepted
            if by_order.get(ref, set()) & {ProviderFact.ORDER_CANCELED, ProviderFact.ORDER_FILLED}
        }
        required = (
            []
            if len(qualified) >= self.plan.minimum_orders and len(qualified) == len(accepted)
            else ["every_test_order_must_reach_terminal_state"]
        )
        return [*required, *missing_reconciliation]

    def _trade_quantity_mismatch(self, order_ref: str) -> bool:
        trades = [
            event
            for event in self._events
            if event.order_ref == order_ref and event.fact is ProviderFact.TRADE_EXECUTION
        ]
        if not trades:
            return False
        terminal = [
            event
            for event in self._events
            if event.order_ref == order_ref
            and event.fact in {ProviderFact.ORDER_CANCELED, ProviderFact.ORDER_FILLED}
        ]
        if not terminal:
            return False
        reported = max(terminal, key=lambda event: event.sequence)
        return not math.isclose(
            sum(event.traded_quantity for event in trades),
            reported.traded_quantity,
            rel_tol=0.0,
            abs_tol=1e-9,
        )

    def _derive_state(
        self,
        unavailable: list[DependencyEvidence],
        unresolved: list[str],
        missing_facts: list[str],
    ) -> EngineState:
        if unavailable or "closeable_position_unavailable" in missing_facts:
            return EngineState.EXTERNAL_CONDITION_UNAVAILABLE
        if {"provider_rejected_request", "cancel_window_unavailable"} & set(missing_facts):
            return EngineState.EXTERNAL_CONDITION_UNAVAILABLE
        if "unexpected_fill_requires_reconciliation" in missing_facts:
            return EngineState.STOP_AND_RECONCILE
        if not missing_facts and not unresolved:
            return EngineState.EVIDENCE_COMPLETE_REQUIRES_REVIEW
        if self._events:
            return EngineState.COLLECTING
        return EngineState.WAITING_EXTERNAL


def sha256_redacted_payload(payload: bytes) -> str:
    """Return a digest for a caller-supplied redacted callback artifact."""

    if not isinstance(payload, bytes) or not payload:
        raise ValueError("payload must be non-empty redacted bytes")
    return hashlib.sha256(payload).hexdigest()


def _positive_finite(value: Any) -> bool:
    return _finite_number(value) and float(value) > 0


def _nonnegative_finite(value: Any) -> bool:
    return _finite_number(value) and float(value) >= 0


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def validate_issued_request_receipt(
    receipt: Any,
    *,
    request_kind: str,
    phase: str,
    request_id: int,
    request_generation: int,
    client_instance_id: str,
    arrival_generation: int,
    arrived_at_utc: str,
    arrived_monotonic: float,
) -> bool:
    """Check receipt shape and callback correlation, without authenticating it."""

    if not isinstance(receipt, IssuedRequestReceipt):
        return False
    if (receipt.request_kind, receipt.phase) != (request_kind, phase):
        return False
    if (
        type(receipt.request_id) is not int
        or receipt.request_id <= 0
        or receipt.request_id != request_id
        or type(receipt.request_generation) is not int
        or receipt.request_generation <= 0
        or receipt.request_generation != request_generation
        or not isinstance(receipt.client_instance_id, str)
        or not receipt.client_instance_id
        or receipt.client_instance_id != client_instance_id
        or type(receipt.arrival_generation) is not int
        or receipt.arrival_generation <= 0
        or receipt.arrival_generation != arrival_generation
        or type(receipt.send_return_code) is not int
        or receipt.send_return_code != 0
        or receipt.ledger_origin != "local_sdk_request_ledger"
        or receipt.issued_at_origin != "local_sdk_call_boundary"
        or not isinstance(receipt.receipt_id, str)
        or not receipt.receipt_id.strip()
        or not _SHA256_RE.fullmatch(str(receipt.ledger_entry_sha256))
    ):
        return False
    issued_at = _utc_timestamp(receipt.issued_at_utc)
    arrived_at = _utc_timestamp(arrived_at_utc)
    if (
        issued_at is None
        or arrived_at is None
        or issued_at > arrived_at
        or type(receipt.issued_monotonic) not in {int, float}
        or isinstance(receipt.issued_monotonic, bool)
        or receipt.issued_monotonic <= 0
        or type(arrived_monotonic) not in {int, float}
        or isinstance(arrived_monotonic, bool)
        # Windows monotonic clocks can return the same tick for an inline
        # callback. Strict local callback-sequence checks establish event
        # ordering separately; this check only rejects an earlier clock value.
        or arrived_monotonic < receipt.issued_monotonic
    ):
        return False
    return True


def _validate_c01_callback_evidence(evidence: CertificationEvidence) -> None:
    """Validate native C01 fields and explicitly local callback-arrival data."""

    arrival = evidence.callback_arrival
    if not isinstance(arrival, LocalCallbackArrival):
        raise EvidenceContractError("C01 callback requires local callback-arrival metadata")
    if not isinstance(arrival.client_instance_id, str) or not arrival.client_instance_id.strip():
        raise EvidenceContractError("C01 callback requires local client_instance_id")
    if type(arrival.request_generation) is not int or arrival.request_generation < 1:
        raise EvidenceContractError("C01 callback requires positive local request_generation")
    if type(arrival.arrival_generation) is not int or arrival.arrival_generation < 1:
        raise EvidenceContractError("C01 callback requires positive local arrival_generation")
    if type(arrival.source_sequence) is not int or arrival.source_sequence < 1:
        raise EvidenceContractError("C01 callback requires positive local source_sequence")
    if (
        type(arrival.arrived_monotonic) not in {int, float}
        or isinstance(arrival.arrived_monotonic, bool)
        or arrival.arrived_monotonic <= 0
    ):
        raise EvidenceContractError("C01 callback requires positive local arrived_monotonic")
    if arrival.sequence_origin != "local_sdk_callback_arrival":
        raise EvidenceContractError("C01 callback sequence must be local SDK arrival metadata")
    if arrival.timestamp_origin != "local_sdk_capture_clock":
        raise EvidenceContractError("C01 callback timestamp must be local capture metadata")
    if not _is_utc_timestamp(arrival.arrived_at_utc):
        raise EvidenceContractError("C01 callback arrived_at_utc must carry UTC offset")
    if not _is_utc_timestamp(evidence.occurred_at_utc) or (
        _utc_timestamp(evidence.occurred_at_utc) != _utc_timestamp(arrival.arrived_at_utc)
    ):
        raise EvidenceContractError(
            "C01 occurred_at_utc must mirror local callback arrival, not provider event time"
        )

    fields = evidence.fields
    request_id = fields.get("request_id")
    if type(request_id) is not int or request_id <= 0:
        raise EvidenceContractError("C01 native callback requires positive integer nRequestID")
    request_kind = "authenticate" if evidence.event_kind == "store_auth_success" else "login"
    if arrival.issued_request_receipt is not None and not validate_issued_request_receipt(
        arrival.issued_request_receipt,
        request_kind=request_kind,
        phase="",
        request_id=request_id,
        request_generation=arrival.request_generation,
        client_instance_id=arrival.client_instance_id,
        arrival_generation=arrival.arrival_generation,
        arrived_at_utc=arrival.arrived_at_utc,
        arrived_monotonic=arrival.arrived_monotonic,
    ):
        raise EvidenceContractError("C01 callback issued-request receipt does not match callback")
    if type(fields.get("is_last")) is not bool or fields.get("is_last") is not True:
        raise EvidenceContractError("C01 native response callback must carry IsLast=True")
    if type(fields.get("error_id")) is not int or fields.get("error_id") != 0:
        raise EvidenceContractError("C01 native callback ErrorID must be integer zero")
    if type(fields.get("request_generation")) is not int or (
        fields.get("request_generation") != arrival.request_generation
    ):
        raise EvidenceContractError(
            "native callback request_id must bind to local request_generation"
        )
    if type(fields.get("arrival_generation")) is not int or (
        fields.get("arrival_generation") != arrival.arrival_generation
    ):
        raise EvidenceContractError(
            "native callback must bind to local arrival_generation"
        )

    if evidence.event_kind == "store_auth_success":
        if evidence.provider_front_id is not None or evidence.provider_session_id or evidence.trading_day:
            raise EvidenceContractError(
                "OnRspAuthenticate has no provider session or TradingDay fields"
            )
        invented_auth_fields = {
            "FrontID",
            "front_id",
            "provider_front_id",
            "SessionID",
            "session_id",
            "provider_session_id",
            "TradingDay",
            "trading_day",
            "provider_timestamp_utc",
            "provider_sequence",
        }
        if any(fields.get(key) not in (None, "") for key in invented_auth_fields):
            raise EvidenceContractError(
                "OnRspAuthenticate evidence cannot claim login-only or provider-time fields"
            )
        if fields.get("authentication_succeeded") is not True:
            raise EvidenceContractError("authentication callback does not report success")
        if evidence.source_sequence != 0:
            raise EvidenceContractError(
                "C01 auth source_sequence is not provider-issued; use callback_arrival"
            )
        return

    impossible_provider_metadata = (
        "provider_timestamp_utc",
        "provider_sequence",
        "provider_event_id",
        "source_sequence",
        "source_timestamp_utc",
    )
    if any(fields.get(key) not in (None, "") for key in impossible_provider_metadata):
        raise EvidenceContractError(
            "C01 auth/login callback cannot claim provider timestamp, sequence, or event id"
        )

    front_id = fields.get("provider_front_id")
    session_id = fields.get("provider_session_id")
    trading_day = fields.get("trading_day")
    if type(front_id) is not int or front_id < 1:
        raise EvidenceContractError("OnRspUserLogin requires native positive FrontID")
    if not isinstance(session_id, str) or not session_id.isdigit():
        raise EvidenceContractError("OnRspUserLogin requires native non-negative SessionID")
    if not isinstance(trading_day, str) or not re.fullmatch(r"[0-9]{8}", trading_day):
        raise EvidenceContractError("OnRspUserLogin requires native YYYYMMDD TradingDay")
    if (
        evidence.provider_front_id != front_id
        or evidence.provider_session_id != session_id
        or evidence.trading_day != trading_day
    ):
        raise EvidenceContractError(
            "login scope aliases must match native FrontID, SessionID, and TradingDay"
        )
    if fields.get("login_succeeded") is not True:
        raise EvidenceContractError("login callback does not report success")
    if evidence.source_sequence != 0:
        raise EvidenceContractError(
            "C01 login source_sequence is not provider-issued; use callback_arrival"
        )


def _utc_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        return None
    return parsed


def _is_utc_timestamp(value: str) -> bool:
    return _utc_timestamp(value) is not None
