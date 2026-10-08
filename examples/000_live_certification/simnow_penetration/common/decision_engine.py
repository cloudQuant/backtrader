"""Typed review-only decisions for the 007 SimNow certification cases.

This module is unregistered and has no provider, SDK, network, config, Store,
Broker, or write dependency. It does not execute or interpret descriptive plan
text. A case-specific rule can produce only a typed candidate for independent
review. Candidates permanently have dispatch_permitted=False.

ObservationAuthenticator is an integration port, not a production verifier.
Without an injected trusted verifier, observations are rejected and decisions
remain BLOCKED. Test verifiers establish interface behavior only; they do not
represent real provider evidence or certification PASS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping, Protocol

from .case_engine import (
    DescriptiveCasePlan,
    IssuedRequestReceipt,
    validate_issued_request_receipt,
)
from .certification import SCENARIOS_BY_CASE_ID

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class DecisionError(ValueError):
    """Raised when an observation or scope violates the decision contract."""


class DecisionStatus(str, Enum):
    BLOCKED = "BLOCKED"
    INCOMPLETE = "INCOMPLETE"
    EXTERNAL_CONDITION_UNAVAILABLE = "EXTERNAL_CONDITION_UNAVAILABLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class ObservationKind(str, Enum):
    AUTH_SUCCESS = "auth_success"
    LOGIN_SUCCESS = "login_success"
    FRONT_CONNECTED = "front_connected"
    FRONT_DISCONNECTED = "front_disconnected"
    MARKET_SUBSCRIPTION_ACK = "market_subscription_ack"
    MARKET_TICK = "market_tick"
    ORDER_ACCEPTED = "order_accepted"
    ORDER_PARTIAL = "order_partial"
    ORDER_CANCELED = "order_canceled"
    ORDER_FILLED = "order_filled"
    ORDER_REJECTED = "order_rejected"
    TRADE_EXECUTION = "trade_execution"
    ORDER_QUERY = "order_query"
    POSITION_QUERY = "position_query"
    ORDER_ADMISSION = "order_admission"
    ORDER_SUBMIT_RECEIPT = "order_submit_receipt"
    ORDER_CANCEL_RECEIPT = "order_cancel_receipt"
    MONITOR_CONFIGURATION = "monitor_configuration"
    MONITOR_TRIGGER = "monitor_trigger"
    REPEAT_GUARD = "repeat_guard"
    VALIDATION_REJECTION = "validation_rejection"
    DISPATCH_ABSENCE = "dispatch_absence"
    EXTERNAL_CONDITION = "external_condition"
    ACCOUNT_PERMISSION_DISABLED = "account_permission_disabled"
    ACCOUNT_PERMISSION_RESTORED = "account_permission_restored"
    STRATEGY_PAUSED = "strategy_paused"
    GATEWAY_LOGOUT_AUTHORIZED = "gateway_logout_authorized"
    POST_DISCONNECT_WRITE_BLOCKED = "post_disconnect_write_blocked"
    SYSTEM_LOG = "system_log"
    MONITOR_LOG = "monitor_log"


_PAYLOADLESS_CALLBACK_FIELD_ALLOWLIST = {
    ObservationKind.FRONT_CONNECTED: frozenset(
        {"gatewaykey", "connectiongeneration", "arrivalgeneration"}
    ),
    ObservationKind.FRONT_DISCONNECTED: frozenset(
        {"gatewaykey", "reason", "nreason", "connectiongeneration", "arrivalgeneration"}
    ),
    ObservationKind.AUTH_SUCCESS: frozenset(
        {
            "requestid",
            "requestgeneration",
            "arrivalgeneration",
            "connectiongeneration",
            "errorid",
            "islast",
            "success",
            "brokerid",
            "userid",
            "userproductinfo",
            "appid",
            "apptype",
        }
    ),
}
_PAYLOADLESS_CALLBACK_LOCAL_FIELD_ALLOWLIST = {
    kind: frozenset(
        {
            "localaccountidentitysha256",
            "localclientid",
            "clientid",
            "localconnectiongeneration",
        }
    )
    for kind in _PAYLOADLESS_CALLBACK_FIELD_ALLOWLIST
}


def validate_payloadless_callback_fields(
    event: "NativeObservation", *, scope_account_identity_sha256: str
) -> None:
    """Reject fields outside the native callback shape and named local metadata.

    The small local-field allowlist covers only the adapter's scope fingerprint,
    client binding, and connection generation. Those values are checked against
    the already-bound scope and callback metadata; they never supply provider
    login identity.
    """
    if event.kind not in _PAYLOADLESS_CALLBACK_FIELD_ALLOWLIST:
        return
    fields = event.fields
    if not isinstance(fields, Mapping):
        raise DecisionError("payloadless front/auth callback fields must be a mapping")
    allowed_fields = _PAYLOADLESS_CALLBACK_FIELD_ALLOWLIST[event.kind]
    allowed_local_fields = _PAYLOADLESS_CALLBACK_LOCAL_FIELD_ALLOWLIST[event.kind]
    for key, value in fields.items():
        if not isinstance(key, str):
            raise DecisionError("payloadless front/auth callback field names must be strings")
        normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
        if normalized in allowed_fields:
            if normalized in {"connectiongeneration", "arrivalgeneration"} and (
                type(value) is not int or value != event.arrival_generation
            ):
                raise DecisionError("local callback generation field does not match arrival metadata")
            continue
        if normalized not in allowed_local_fields:
            raise DecisionError(
                f"{event.callback_name} cannot carry login identity alias {key!r}"
            )
        if normalized == "localaccountidentitysha256":
            if (
                not isinstance(value, str)
                or not _SHA256_RE.fullmatch(value)
                or not isinstance(scope_account_identity_sha256, str)
                or value.casefold() != scope_account_identity_sha256.casefold()
            ):
                raise DecisionError(
                    "local account scope fingerprint must exactly match the bound decision scope"
                )
        elif normalized in {"localclientid", "clientid"}:
            if (
                not isinstance(value, str)
                or not value
                or not isinstance(event.client_instance_id, str)
                or value != event.client_instance_id
            ):
                raise DecisionError("local client field must match callback client metadata")
        elif normalized == "localconnectiongeneration":
            if type(value) is not int or value != event.arrival_generation:
                raise DecisionError(
                    "local connection generation field does not match arrival metadata"
                )


class IntentKind(str, Enum):
    AUTH_SESSION_AUDIT = "auth_session_audit"
    OPEN_ORDER_CANDIDATE = "open_order_candidate"
    CLOSE_ORDER_CANDIDATE = "close_order_candidate"
    CANCEL_ORDER_CANDIDATE = "cancel_order_candidate"
    CONNECTION_AUDIT = "connection_audit"
    EXTERNAL_DISCONNECT_AUDIT = "external_disconnect_audit"
    RECONNECT_AUDIT = "reconnect_audit"
    SUBMIT_COUNT_PROBE = "submit_count_probe"
    CANCEL_COUNT_PROBE = "cancel_count_probe"
    REPEAT_OPEN_GUARD_PROBE = "repeat_open_guard_probe"
    REPEAT_CLOSE_GUARD_PROBE = "repeat_close_guard_probe"
    REPEAT_CANCEL_GUARD_PROBE = "repeat_cancel_guard_probe"
    SET_ORDER_THRESHOLD = "set_order_threshold"
    TRIGGER_ORDER_THRESHOLD = "trigger_order_threshold"
    SET_CANCEL_THRESHOLD = "set_cancel_threshold"
    TRIGGER_CANCEL_THRESHOLD = "trigger_cancel_threshold"
    SET_REPEAT_THRESHOLD = "set_repeat_threshold"
    TRIGGER_REPEAT_THRESHOLD = "trigger_repeat_threshold"
    INVALID_INSTRUMENT_VALIDATION = "invalid_instrument_validation"
    INVALID_TICK_VALIDATION = "invalid_tick_validation"
    OVERSIZE_VALIDATION = "oversize_validation"
    REMOTE_REJECTION_REVIEW = "remote_rejection_review"
    ACCOUNT_PERMISSION_REVIEW = "account_permission_review"
    STRATEGY_PAUSE_REVIEW = "strategy_pause_review"
    FORCE_LOGOUT_REVIEW = "force_logout_review"
    BATCH_CANCEL_PARTIALS_CANDIDATE = "batch_cancel_partials_candidate"
    BATCH_CANCEL_OPEN_ORDERS_CANDIDATE = "batch_cancel_open_orders_candidate"
    TRADE_AUDIT = "trade_audit"
    SYSTEM_AUDIT = "system_audit"
    MONITOR_AUDIT = "monitor_audit"
    VALIDATION_ERROR_AUDIT = "validation_error_audit"


class EvidenceTrustDomain(str, Enum):
    CTP_CALLBACK = "ctp_provider_callback"
    MANAGED_RUNTIME = "managed_runtime_receipt"
    MONITOR = "runtime_monitor_receipt"
    LOCAL_VALIDATOR = "local_validator_receipt"
    CONTROL_PLANE = "control_plane_receipt"


@dataclass(frozen=True)
class DecisionScope:
    """Binding supplied by a future managed scope adapter, not created here.

    ``account_identity_sha256`` is optional for source compatibility only. An
    order-case review requires the managed scope producer and authenticator to
    provide and bind it; a raw account identifier or observation field is not
    an authority source. No current production adapter supplies this binding.
    """

    case_id: str
    scenario_id: str
    plan_source_sha256: str
    scope_sha256: str
    account_identity_sha256: str = ""

    @classmethod
    def for_plan(
        cls,
        plan: DescriptiveCasePlan,
        scope_sha256: str,
        account_identity_sha256: str = "",
    ) -> "DecisionScope":
        scenario = SCENARIOS_BY_CASE_ID.get(plan.case_id)
        if scenario is None:
            raise DecisionError(f"unknown certification case {plan.case_id!r}")
        return cls(
            plan.case_id,
            scenario.scenario_id,
            plan.source_sha256,
            scope_sha256,
            account_identity_sha256,
        )

    def validate(self, plan: DescriptiveCasePlan) -> None:
        scenario = SCENARIOS_BY_CASE_ID.get(self.case_id)
        if scenario is None or self.case_id != plan.case_id:
            raise DecisionError("decision scope case does not match the static plan")
        if self.scenario_id != scenario.scenario_id:
            raise DecisionError("decision scope scenario does not match canonical mapping")
        if self.plan_source_sha256 != plan.source_sha256:
            raise DecisionError("decision scope is not bound to this strategy source digest")
        if not _SHA256_RE.fullmatch(self.plan_source_sha256):
            raise DecisionError("strategy source digest must be SHA-256")
        if not _SHA256_RE.fullmatch(self.scope_sha256):
            raise DecisionError("sealed scope digest must be SHA-256")
        if self.account_identity_sha256 != "" and (
            not isinstance(self.account_identity_sha256, str)
            or not _SHA256_RE.fullmatch(self.account_identity_sha256)
        ):
            raise DecisionError("account identity binding must be SHA-256 when present")


@dataclass(frozen=True)
class NativeObservation:
    """Normalized fact from a source event; it contains no operation command.

    For native CTP callbacks, ``event_id`` is local. C01 authenticate/login
    ``sequence`` and ``occurred_at_utc`` are local SDK arrival metadata, as
    identified by the origin fields; CTP does not issue those values.
    """

    kind: ObservationKind
    source_domain: EvidenceTrustDomain
    event_id: str
    evidence_sha256: str
    occurred_at_utc: str
    sequence: int
    stream_id: str
    callback_name: str = ""
    provider_session_id: str = ""
    trading_day: str = ""
    fields: Mapping[str, Any] = field(default_factory=dict)
    provider_front_id: int | None = None
    client_instance_id: str = ""
    request_generation: int = 0
    request_id_origin: str = ""
    request_generation_origin: str = ""
    arrival_generation: int = 0
    session_identity_origin: str = ""
    event_id_origin: str = ""
    provider_issued_event_id: bool = False
    arrived_at_utc: str = ""
    arrived_monotonic: float = 0.0
    sequence_origin: str = ""
    timestamp_origin: str = ""
    connection_generation_origin: str = ""
    issued_request_receipt: IssuedRequestReceipt | None = None


@dataclass(frozen=True)
class AuthenticationReceipt:
    event_id: str
    evidence_sha256: str
    scope_sha256: str
    trust_domain: EvidenceTrustDomain
    verification_ref: str
    account_identity_sha256: str = ""


class ObservationAuthenticator(Protocol):
    """Trusted verification port; this package supplies no production adapter."""

    def authenticate(
        self, observation: NativeObservation, scope: DecisionScope
    ) -> AuthenticationReceipt | None:
        """Verify source signature/provenance and bind evidence to this scope."""


@dataclass(frozen=True)
class IntentSpec:
    case_id: str
    intent_kind: IntentKind
    required_kinds: tuple[ObservationKind, ...]
    rule: str
    admission_kind: str = ""


@dataclass(frozen=True)
class IntentCandidate:
    case_id: str
    scenario_id: str
    intent_kind: IntentKind
    evidence_event_ids: tuple[str, ...]
    correlation_refs: tuple[str, ...]
    dispatch_permitted: bool = field(default=False, init=False)


@dataclass(frozen=True)
class DecisionSnapshot:
    case_id: str
    scenario_id: str
    status: DecisionStatus
    certification_pass: bool
    dispatch_permitted: bool
    intent_candidate: IntentCandidate | None
    missing_conditions: tuple[str, ...]
    rejected_observations: tuple[str, ...]
    external_unavailability: tuple[str, ...]


def _spec(
    case: str,
    intent: IntentKind,
    kinds: tuple[ObservationKind, ...],
    rule: str,
    admission: str = "",
) -> IntentSpec:
    return IntentSpec(case, intent, kinds, rule, admission)


# One explicit, typed intent and fact rule for every case. Descriptive strings
# in *_strategy.py do not select or alter these definitions.
CASE_INTENT_SPECS: dict[str, IntentSpec] = {
    "C01": _spec(
        "C01",
        IntentKind.AUTH_SESSION_AUDIT,
        (ObservationKind.AUTH_SUCCESS, ObservationKind.LOGIN_SUCCESS),
        "auth_login",
    ),
    "T01": _spec(
        "T01",
        IntentKind.OPEN_ORDER_CANDIDATE,
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_SUBSCRIPTION_ACK,
            ObservationKind.MARKET_TICK,
            ObservationKind.ORDER_ADMISSION,
        ),
        "open_order",
        "open",
    ),
    "T02": _spec(
        "T02",
        IntentKind.CLOSE_ORDER_CANDIDATE,
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_SUBSCRIPTION_ACK,
            ObservationKind.MARKET_TICK,
            ObservationKind.POSITION_QUERY,
            ObservationKind.ORDER_ADMISSION,
        ),
        "close_order",
        "close",
    ),
    "T03": _spec(
        "T03",
        IntentKind.CANCEL_ORDER_CANDIDATE,
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_TICK,
            ObservationKind.ORDER_ACCEPTED,
            ObservationKind.ORDER_QUERY,
            ObservationKind.ORDER_ADMISSION,
        ),
        "cancel_order",
        "cancel",
    ),
    "M01": _spec(
        "M01",
        IntentKind.CONNECTION_AUDIT,
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_SUBSCRIPTION_ACK,
        ),
        "connected",
    ),
    "M02": _spec(
        "M02",
        IntentKind.EXTERNAL_DISCONNECT_AUDIT,
        (ObservationKind.EXTERNAL_CONDITION, ObservationKind.FRONT_DISCONNECTED),
        "disconnected",
    ),
    "M03": _spec(
        "M03",
        IntentKind.RECONNECT_AUDIT,
        (
            ObservationKind.FRONT_DISCONNECTED,
            ObservationKind.EXTERNAL_CONDITION,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.MARKET_SUBSCRIPTION_ACK,
        ),
        "reconnected",
    ),
    "M04": _spec(
        "M04",
        IntentKind.SUBMIT_COUNT_PROBE,
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_TICK,
            ObservationKind.ORDER_ADMISSION,
        ),
        "submit_count",
        "open",
    ),
    "M05": _spec(
        "M05",
        IntentKind.CANCEL_COUNT_PROBE,
        (
            ObservationKind.ORDER_ACCEPTED,
            ObservationKind.ORDER_QUERY,
            ObservationKind.ORDER_ADMISSION,
        ),
        "cancel_count",
        "cancel",
    ),
    "O01": _spec(
        "O01",
        IntentKind.REPEAT_OPEN_GUARD_PROBE,
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_TICK,
            ObservationKind.ORDER_ADMISSION,
            ObservationKind.REPEAT_GUARD,
        ),
        "repeat_open",
        "open",
    ),
    "O02": _spec(
        "O02",
        IntentKind.REPEAT_CLOSE_GUARD_PROBE,
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_TICK,
            ObservationKind.POSITION_QUERY,
            ObservationKind.ORDER_ADMISSION,
            ObservationKind.REPEAT_GUARD,
        ),
        "repeat_close",
        "close",
    ),
    "O03": _spec(
        "O03",
        IntentKind.REPEAT_CANCEL_GUARD_PROBE,
        (
            ObservationKind.ORDER_ACCEPTED,
            ObservationKind.ORDER_QUERY,
            ObservationKind.ORDER_ADMISSION,
            ObservationKind.REPEAT_GUARD,
        ),
        "repeat_cancel",
        "cancel",
    ),
    "TH01": _spec(
        "TH01",
        IntentKind.SET_ORDER_THRESHOLD,
        (ObservationKind.MONITOR_CONFIGURATION,),
        "configure_order",
    ),
    "TH02": _spec(
        "TH02",
        IntentKind.TRIGGER_ORDER_THRESHOLD,
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_TICK,
            ObservationKind.ORDER_ACCEPTED,
            ObservationKind.MONITOR_CONFIGURATION,
            ObservationKind.MONITOR_TRIGGER,
        ),
        "trigger_order",
    ),
    "TH03": _spec(
        "TH03",
        IntentKind.SET_CANCEL_THRESHOLD,
        (ObservationKind.MONITOR_CONFIGURATION,),
        "configure_cancel",
    ),
    "TH04": _spec(
        "TH04",
        IntentKind.TRIGGER_CANCEL_THRESHOLD,
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.ORDER_ACCEPTED,
            ObservationKind.ORDER_CANCELED,
            ObservationKind.ORDER_SUBMIT_RECEIPT,
            ObservationKind.ORDER_CANCEL_RECEIPT,
            ObservationKind.MONITOR_CONFIGURATION,
            ObservationKind.MONITOR_TRIGGER,
        ),
        "trigger_cancel",
    ),
    "TH05": _spec(
        "TH05",
        IntentKind.SET_REPEAT_THRESHOLD,
        (ObservationKind.MONITOR_CONFIGURATION,),
        "configure_repeat",
    ),
    "TH06": _spec(
        "TH06",
        IntentKind.TRIGGER_REPEAT_THRESHOLD,
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.MONITOR_CONFIGURATION,
            ObservationKind.REPEAT_GUARD,
            ObservationKind.MONITOR_TRIGGER,
        ),
        "trigger_repeat",
    ),
    "V01": _spec(
        "V01",
        IntentKind.INVALID_INSTRUMENT_VALIDATION,
        (ObservationKind.VALIDATION_REJECTION, ObservationKind.DISPATCH_ABSENCE),
        "validate_instrument",
    ),
    "V02": _spec(
        "V02",
        IntentKind.INVALID_TICK_VALIDATION,
        (
            ObservationKind.MARKET_TICK,
            ObservationKind.VALIDATION_REJECTION,
            ObservationKind.DISPATCH_ABSENCE,
        ),
        "validate_tick",
    ),
    "V03": _spec(
        "V03",
        IntentKind.OVERSIZE_VALIDATION,
        (
            ObservationKind.ORDER_ADMISSION,
            ObservationKind.VALIDATION_REJECTION,
            ObservationKind.DISPATCH_ABSENCE,
        ),
        "validate_size",
        "validation",
    ),
    "E01": _spec(
        "E01",
        IntentKind.REMOTE_REJECTION_REVIEW,
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_TICK,
            ObservationKind.ORDER_ADMISSION,
            ObservationKind.EXTERNAL_CONDITION,
            ObservationKind.ORDER_SUBMIT_RECEIPT,
            ObservationKind.ORDER_REJECTED,
        ),
        "reject_funds",
        "remote_reject",
    ),
    "E02": _spec(
        "E02",
        IntentKind.REMOTE_REJECTION_REVIEW,
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_TICK,
            ObservationKind.ORDER_ADMISSION,
            ObservationKind.EXTERNAL_CONDITION,
            ObservationKind.ORDER_SUBMIT_RECEIPT,
            ObservationKind.ORDER_REJECTED,
        ),
        "reject_position",
        "remote_reject",
    ),
    "E03": _spec(
        "E03",
        IntentKind.REMOTE_REJECTION_REVIEW,
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_TICK,
            ObservationKind.ORDER_ADMISSION,
            ObservationKind.EXTERNAL_CONDITION,
            ObservationKind.ORDER_SUBMIT_RECEIPT,
            ObservationKind.ORDER_REJECTED,
        ),
        "reject_market",
        "remote_reject",
    ),
    "EM01": _spec(
        "EM01",
        IntentKind.ACCOUNT_PERMISSION_REVIEW,
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_TICK,
            ObservationKind.ORDER_ADMISSION,
            ObservationKind.ACCOUNT_PERMISSION_DISABLED,
            ObservationKind.ORDER_SUBMIT_RECEIPT,
            ObservationKind.ORDER_REJECTED,
            ObservationKind.ACCOUNT_PERMISSION_RESTORED,
            ObservationKind.ORDER_QUERY,
        ),
        "account_permission",
        "remote_reject",
    ),
    "EM02": _spec(
        "EM02",
        IntentKind.STRATEGY_PAUSE_REVIEW,
        (ObservationKind.STRATEGY_PAUSED, ObservationKind.ORDER_QUERY),
        "strategy_paused",
    ),
    "EM03": _spec(
        "EM03",
        IntentKind.FORCE_LOGOUT_REVIEW,
        (
            ObservationKind.GATEWAY_LOGOUT_AUTHORIZED,
            ObservationKind.FRONT_DISCONNECTED,
            ObservationKind.POST_DISCONNECT_WRITE_BLOCKED,
        ),
        "force_logout",
    ),
    "B01": _spec(
        "B01",
        IntentKind.BATCH_CANCEL_PARTIALS_CANDIDATE,
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_TICK,
            ObservationKind.ORDER_ADMISSION,
            ObservationKind.ORDER_ACCEPTED,
            ObservationKind.ORDER_PARTIAL,
            ObservationKind.TRADE_EXECUTION,
            ObservationKind.ORDER_QUERY,
        ),
        "batch_partials",
        "batch_cancel",
    ),
    "B02": _spec(
        "B02",
        IntentKind.BATCH_CANCEL_OPEN_ORDERS_CANDIDATE,
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_TICK,
            ObservationKind.ORDER_ADMISSION,
            ObservationKind.ORDER_ACCEPTED,
            ObservationKind.ORDER_QUERY,
        ),
        "batch_open",
        "batch_cancel",
    ),
    "L01": _spec(
        "L01",
        IntentKind.TRADE_AUDIT,
        (ObservationKind.ORDER_ACCEPTED, ObservationKind.TRADE_EXECUTION),
        "trade_log",
    ),
    "L02": _spec(
        "L02",
        IntentKind.SYSTEM_AUDIT,
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_SUBSCRIPTION_ACK,
            ObservationKind.SYSTEM_LOG,
        ),
        "system_log",
    ),
    "L03": _spec(
        "L03",
        IntentKind.MONITOR_AUDIT,
        (ObservationKind.ORDER_ACCEPTED, ObservationKind.MONITOR_LOG),
        "monitor_log",
    ),
    "L04": _spec(
        "L04",
        IntentKind.VALIDATION_ERROR_AUDIT,
        (ObservationKind.VALIDATION_REJECTION, ObservationKind.DISPATCH_ABSENCE),
        "validation_log",
    ),
}


_SESSION_REQUIRED_RULES = frozenset(
    {
        "open_order",
        "close_order",
        "cancel_order",
        "submit_count",
        "cancel_count",
        "repeat_open",
        "repeat_close",
        "repeat_cancel",
        "connected",
        "reconnected",
        "system_log",
        "reject_funds",
        "reject_position",
        "reject_market",
        "account_permission",
        "batch_partials",
        "batch_open",
        "trigger_order",
    }
)
_TICK_REQUIRED_RULES = frozenset(
    {
        "open_order",
        "close_order",
        "cancel_order",
        "submit_count",
        "repeat_open",
        "repeat_close",
        "reject_funds",
        "reject_position",
        "reject_market",
        "account_permission",
        "batch_partials",
        "batch_open",
        "trigger_order",
    }
)

_POLICY: dict[ObservationKind, tuple[EvidenceTrustDomain, str, tuple[str, ...]]] = {
    ObservationKind.AUTH_SUCCESS: (
        EvidenceTrustDomain.CTP_CALLBACK,
        "OnRspAuthenticate",
        (
            "request_id",
            "request_generation",
            "arrival_generation",
            "is_last",
            "error_id",
            "success",
        ),
    ),
    ObservationKind.LOGIN_SUCCESS: (
        EvidenceTrustDomain.CTP_CALLBACK,
        "OnRspUserLogin",
        (
            "request_id",
            "request_generation",
            "arrival_generation",
            "is_last",
            "error_id",
            "provider_front_id",
            "provider_session_id",
            "trading_day",
            "success",
        ),
    ),
    ObservationKind.FRONT_CONNECTED: (
        EvidenceTrustDomain.CTP_CALLBACK,
        "OnFrontConnected",
        ("gateway_key",),
    ),
    ObservationKind.FRONT_DISCONNECTED: (
        EvidenceTrustDomain.CTP_CALLBACK,
        "OnFrontDisconnected",
        ("gateway_key", "reason"),
    ),
    ObservationKind.MARKET_SUBSCRIPTION_ACK: (
        EvidenceTrustDomain.CTP_CALLBACK,
        "OnRspSubMarketData",
        ("instrument_id", "success"),
    ),
    ObservationKind.MARKET_TICK: (
        EvidenceTrustDomain.CTP_CALLBACK,
        "OnRtnDepthMarketData",
        ("instrument_id", "bid", "ask", "last", "price_tick"),
    ),
    ObservationKind.ORDER_ACCEPTED: (
        EvidenceTrustDomain.CTP_CALLBACK,
        "OnRtnOrder",
        ("order_ref", "external_order_id", "instrument_id", "status", "remaining_quantity"),
    ),
    ObservationKind.ORDER_PARTIAL: (
        EvidenceTrustDomain.CTP_CALLBACK,
        "OnRtnOrder",
        (
            "order_ref",
            "external_order_id",
            "instrument_id",
            "status",
            "traded_quantity",
            "remaining_quantity",
        ),
    ),
    ObservationKind.ORDER_CANCELED: (
        EvidenceTrustDomain.CTP_CALLBACK,
        "OnRtnOrder",
        ("order_ref", "external_order_id", "instrument_id", "status", "remaining_quantity"),
    ),
    ObservationKind.ORDER_FILLED: (
        EvidenceTrustDomain.CTP_CALLBACK,
        "OnRtnOrder",
        (
            "order_ref",
            "external_order_id",
            "instrument_id",
            "status",
            "traded_quantity",
            "remaining_quantity",
        ),
    ),
    ObservationKind.ORDER_REJECTED: (
        EvidenceTrustDomain.CTP_CALLBACK,
        "OnRspOrderInsert",
        ("order_ref", "instrument_id", "error_id", "error_message", "rejection_class"),
    ),
    ObservationKind.TRADE_EXECUTION: (
        EvidenceTrustDomain.CTP_CALLBACK,
        "OnRtnTrade",
        ("order_ref", "trade_id", "quantity"),
    ),
    ObservationKind.ORDER_QUERY: (
        EvidenceTrustDomain.CTP_CALLBACK,
        "OnRspQryOrder",
        ("query_id", "complete", "open_order_refs"),
    ),
    ObservationKind.POSITION_QUERY: (
        EvidenceTrustDomain.CTP_CALLBACK,
        "OnRspQryInvestorPosition",
        ("query_id", "complete", "instrument_id", "phase", "closeable_quantity"),
    ),
    ObservationKind.ORDER_ADMISSION: (
        EvidenceTrustDomain.MANAGED_RUNTIME,
        "",
        ("case_id", "intent_kind", "approval_ref", "maximum_quantity"),
    ),
    ObservationKind.ORDER_SUBMIT_RECEIPT: (
        EvidenceTrustDomain.MANAGED_RUNTIME,
        "",
        ("order_ref", "trace_id", "dispatch_state"),
    ),
    ObservationKind.ORDER_CANCEL_RECEIPT: (
        EvidenceTrustDomain.MANAGED_RUNTIME,
        "",
        ("order_ref", "trace_id", "dispatch_state", "request_id", "action"),
    ),
    ObservationKind.MONITOR_CONFIGURATION: (
        EvidenceTrustDomain.MONITOR,
        "",
        ("metric", "threshold", "configuration_digest", "monitor_digest"),
    ),
    ObservationKind.MONITOR_TRIGGER: (
        EvidenceTrustDomain.MONITOR,
        "",
        ("metric", "threshold", "observed_value", "monitor_digest"),
    ),
    ObservationKind.REPEAT_GUARD: (
        EvidenceTrustDomain.MONITOR,
        "",
        ("action_kind", "repeat_key", "repeat_count", "monitor_digest"),
    ),
    ObservationKind.VALIDATION_REJECTION: (
        EvidenceTrustDomain.LOCAL_VALIDATOR,
        "",
        ("order_ref", "rule", "error_message", "validator_digest", "reference_data_digest"),
    ),
    ObservationKind.DISPATCH_ABSENCE: (
        EvidenceTrustDomain.MANAGED_RUNTIME,
        "",
        ("order_ref", "dispatch_count", "audit_digest"),
    ),
    ObservationKind.EXTERNAL_CONDITION: (
        EvidenceTrustDomain.CONTROL_PLANE,
        "",
        ("condition_id", "state", "evidence_ref"),
    ),
    ObservationKind.ACCOUNT_PERMISSION_DISABLED: (
        EvidenceTrustDomain.CONTROL_PLANE,
        "",
        ("account_id_masked", "authorization_ref", "independent_evidence_ref"),
    ),
    ObservationKind.ACCOUNT_PERMISSION_RESTORED: (
        EvidenceTrustDomain.CONTROL_PLANE,
        "",
        ("account_id_masked", "restoration_ref"),
    ),
    ObservationKind.STRATEGY_PAUSED: (
        EvidenceTrustDomain.CONTROL_PLANE,
        "",
        ("strategy_id", "authorization_ref", "reason"),
    ),
    ObservationKind.GATEWAY_LOGOUT_AUTHORIZED: (
        EvidenceTrustDomain.CONTROL_PLANE,
        "",
        ("gateway_key", "authorization_ref", "operator_evidence_ref"),
    ),
    ObservationKind.POST_DISCONNECT_WRITE_BLOCKED: (
        EvidenceTrustDomain.MANAGED_RUNTIME,
        "",
        ("gateway_key", "guard_ref", "blocked_attempt_count"),
    ),
    ObservationKind.SYSTEM_LOG: (
        EvidenceTrustDomain.MANAGED_RUNTIME,
        "",
        ("trace_id", "gateway_key", "log_digest"),
    ),
    ObservationKind.MONITOR_LOG: (
        EvidenceTrustDomain.MONITOR,
        "",
        ("trace_id", "metric", "monitor_digest"),
    ),
}


class CaseIntentDecisionEngine:
    """Evaluate source-verified observations into review-only candidates."""

    def __init__(
        self,
        plan: DescriptiveCasePlan,
        scope: DecisionScope,
        authenticator: ObservationAuthenticator | None = None,
    ) -> None:
        scope.validate(plan)
        self.plan = plan
        self.scope = scope
        self.spec = CASE_INTENT_SPECS[plan.case_id]
        self._authenticator = authenticator
        self._events: list[NativeObservation] = []
        self._event_ids: set[str] = set()
        self._sequences: dict[tuple[EvidenceTrustDomain, str, str, str], int] = {}
        self._provider_session: tuple[str, str] | None = None
        self._rejected: list[str] = []

    def record(self, event: NativeObservation) -> bool:
        """Record one authenticated observation and poison the review on rejection."""
        try:
            return self._record_observation(event)
        except Exception as exc:
            event_id = event.event_id if type(event) is NativeObservation else "invalid-event"
            self._rejected.append(f"{event_id}:record_rejected:{type(exc).__name__}")
            raise

    def _record_observation(self, event: NativeObservation) -> bool:
        """Internal recorder shared by typed case-specific evidence policies."""
        self._validate_event(event)
        if event.event_id in self._event_ids:
            raise DecisionError("duplicate observation event_id")
        if self._authenticator is None:
            self._rejected.append(f"{event.event_id}:authenticator_unavailable")
            return False
        receipt = self._authenticator.authenticate(event, self.scope)
        if receipt is None:
            self._rejected.append(f"{event.event_id}:verification_denied")
            return False
        if (
            receipt.event_id != event.event_id
            or receipt.evidence_sha256.lower() != event.evidence_sha256.lower()
            or receipt.scope_sha256.lower() != self.scope.scope_sha256.lower()
            or not isinstance(receipt.account_identity_sha256, str)
            or receipt.account_identity_sha256.lower() != self.scope.account_identity_sha256.lower()
            or receipt.trust_domain is not event.source_domain
            or not receipt.verification_ref.strip()
        ):
            self._rejected.append(f"{event.event_id}:verification_receipt_mismatch")
            return False
        key = (
            (event.source_domain, event.client_instance_id, event.stream_id, "")
            if event.source_domain is EvidenceTrustDomain.CTP_CALLBACK
            and self.plan.case_id in {"M02", "M03"}
            else (
                event.source_domain,
                event.stream_id,
                event.provider_session_id,
                event.trading_day,
            )
        )
        if event.sequence <= self._sequences.get(key, 0):
            raise DecisionError("observation sequence must increase within a source stream")

        if event.source_domain is EvidenceTrustDomain.CTP_CALLBACK:
            provider_events = [
                item for item in self._events if item.source_domain is EvidenceTrustDomain.CTP_CALLBACK
            ]
            if self.plan.case_id in {"M02", "M03"}:
                previous_logins = [
                    item for item in provider_events if item.kind is ObservationKind.LOGIN_SUCCESS
                ]
                previous_login = previous_logins[-1] if previous_logins else None
                generation = event.fields.get("connection_generation")
                if event.kind is ObservationKind.LOGIN_SUCCESS:
                    if previous_login is not None:
                        old_generation = previous_login.arrival_generation
                        new_scope = (event.provider_session_id, event.trading_day)
                        old_scope = (previous_login.provider_session_id, previous_login.trading_day)
                        if event.client_instance_id != previous_login.client_instance_id:
                            raise DecisionError("native login cannot splice provider clients")
                        if type(generation) is not int or generation < old_generation:
                            raise DecisionError("native login generation cannot move backwards")
                        if generation == old_generation and new_scope != old_scope:
                            raise DecisionError("same-generation native login cannot change provider identity")
                        if generation > old_generation and not (
                            any(
                                item.kind is ObservationKind.FRONT_DISCONNECTED
                                and item.client_instance_id == event.client_instance_id
                                and item.arrival_generation == old_generation
                                and previous_login.sequence < item.sequence < event.sequence
                                for item in provider_events
                            )
                            and any(
                                item.kind is ObservationKind.FRONT_CONNECTED
                                and item.client_instance_id == event.client_instance_id
                                and item.arrival_generation == generation
                                and item.sequence < event.sequence
                                for item in provider_events
                            )
                        ):
                            raise DecisionError(
                                "provider identity may change only on a later native login after reconnect"
                            )
                    self._provider_session = (event.provider_session_id, event.trading_day)
                elif event.kind not in {
                    ObservationKind.AUTH_SUCCESS,
                    ObservationKind.FRONT_CONNECTED,
                    ObservationKind.FRONT_DISCONNECTED,
                }:
                    if previous_login is None:
                        raise DecisionError("session-scoped callback requires a prior native user login")
                    if (
                        event.client_instance_id != previous_login.client_instance_id
                        or (event.provider_session_id, event.trading_day)
                        != (previous_login.provider_session_id, previous_login.trading_day)
                        or (
                            type(generation) is int
                            and generation != previous_login.arrival_generation
                        )
                    ):
                        raise DecisionError(
                            "provider callback scope must match the latest native login for this client"
                        )
                    if event.session_identity_origin != "derived_from_same_client_generation_native_login":
                        raise DecisionError(
                            "provider callback identity must be locally derived from native login"
                        )
                    if event.sequence <= previous_login.sequence:
                        raise DecisionError("provider callback must follow its native login")
            elif event.kind not in {
                ObservationKind.AUTH_SUCCESS,
                ObservationKind.FRONT_CONNECTED,
                ObservationKind.FRONT_DISCONNECTED,
            }:
                provider_scope = (event.provider_session_id, event.trading_day)
                if self._provider_session is None:
                    self._provider_session = provider_scope
                elif provider_scope != self._provider_session and self.plan.case_id != "M03":
                    raise DecisionError(
                        "one case decision cannot mix provider sessions or trading days"
                    )
        self._sequences[key] = event.sequence
        self._event_ids.add(event.event_id)
        self._events.append(event)
        return True

    def evaluate(self, *, now_utc: datetime | None = None) -> DecisionSnapshot:
        scenario_id = SCENARIOS_BY_CASE_ID[self.plan.case_id].scenario_id
        if self._authenticator is None:
            return self._snapshot(
                DecisionStatus.BLOCKED, ("trusted_authenticator_not_configured",), None
            )
        if not self._events:
            return self._snapshot(DecisionStatus.BLOCKED, ("no_authenticated_observations",), None)
        unavailable = tuple(
            f"{item.fields.get('condition_id')}:{item.fields.get('reason', 'unavailable')}"
            for item in self._all(ObservationKind.EXTERNAL_CONDITION)
            if item.fields.get("state") == "unavailable"
        )
        if unavailable:
            return self._snapshot(
                DecisionStatus.EXTERNAL_CONDITION_UNAVAILABLE, (), None, unavailable
            )
        evaluation_time = now_utc or datetime.now(timezone.utc)
        if self._rejected:
            missing = self._missing(evaluation_time)
            poisoned = tuple(
                dict.fromkeys(("rejected_observation_poisoned_review", *missing))
            )
            return self._snapshot(DecisionStatus.INCOMPLETE, poisoned, None)
        missing = self._missing(evaluation_time)
        if missing:
            return self._snapshot(DecisionStatus.INCOMPLETE, missing, None)
        candidate = IntentCandidate(
            self.plan.case_id,
            scenario_id,
            self.spec.intent_kind,
            tuple(item.event_id for item in self._events),
            self._correlation_refs(),
        )
        return self._snapshot(DecisionStatus.REVIEW_REQUIRED, (), candidate)

    def _snapshot(
        self,
        status: DecisionStatus,
        missing: tuple[str, ...],
        candidate: IntentCandidate | None,
        unavailable: tuple[str, ...] = (),
    ) -> DecisionSnapshot:
        return DecisionSnapshot(
            self.plan.case_id,
            SCENARIOS_BY_CASE_ID[self.plan.case_id].scenario_id,
            status,
            False,
            False,
            candidate,
            missing,
            tuple(self._rejected),
            unavailable,
        )

    def _validate_event(self, event: NativeObservation) -> None:
        policy = _POLICY[event.kind]
        domain, callback, required_fields = policy
        if event.source_domain is not domain or event.callback_name != callback:
            raise DecisionError(f"{event.kind.value} has incorrect source domain/callback")
        if (
            domain is EvidenceTrustDomain.CTP_CALLBACK
            and event.kind
            in {
                ObservationKind.AUTH_SUCCESS,
                ObservationKind.FRONT_CONNECTED,
                ObservationKind.FRONT_DISCONNECTED,
            }
        ):
            self._validate_no_login_identity_aliases(event)
        if event.kind not in self.spec.required_kinds and not (
            self.spec.rule in _SESSION_REQUIRED_RULES
            and event.kind
            in {
                ObservationKind.AUTH_SUCCESS,
                ObservationKind.MARKET_SUBSCRIPTION_ACK,
            }
        ):
            raise DecisionError(f"{event.kind.value} is not required by case {self.plan.case_id}")
        if not event.event_id or not _SHA256_RE.fullmatch(event.evidence_sha256):
            raise DecisionError("event id and SHA-256 evidence digest are required")
        if not event.stream_id:
            raise DecisionError("source stream_id is required")
        if (
            not isinstance(event.sequence, int)
            or isinstance(event.sequence, bool)
            or event.sequence < 1
        ):
            raise DecisionError("source sequence must be a positive integer")
        timestamp = _parse_utc(event.occurred_at_utc)
        if timestamp is None:
            raise DecisionError("event timestamp must carry UTC offset")
        is_auth_callback = event.kind is ObservationKind.AUTH_SUCCESS
        is_payloadless_front = event.kind in {
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.FRONT_DISCONNECTED,
        }
        if is_auth_callback or is_payloadless_front:
            if (
                event.provider_front_id is not None
                or event.provider_session_id
                or event.trading_day
                or any(
                    event.fields.get(name) not in (None, "")
                    for name in ("provider_front_id", "provider_session_id", "trading_day")
                )
            ):
                callback = "OnRspAuthenticate" if is_auth_callback else event.callback_name
                raise DecisionError(
                    f"{callback} cannot claim provider FrontID, SessionID, or TradingDay"
                )
        elif domain is EvidenceTrustDomain.CTP_CALLBACK and (
            not event.provider_session_id or not event.trading_day
        ):
            raise DecisionError("native provider events require session and trading day")
        if event.kind is ObservationKind.FRONT_CONNECTED and (
            not event.client_instance_id
            or type(event.arrival_generation) is not int
            or event.arrival_generation < 1
            or event.connection_generation_origin != "local_connection_generation"
        ):
            raise DecisionError(
                "OnFrontConnected requires local client and connection-generation metadata"
            )
        missing = [name for name in required_fields if _missing(event.fields.get(name))]
        if self.plan.case_id == "TH04":
            extra_fields = {
                ObservationKind.ORDER_SUBMIT_RECEIPT: ("request_id", "action"),
                ObservationKind.ORDER_CANCEL_RECEIPT: ("request_id", "action"),
                ObservationKind.MONITOR_TRIGGER: (
                    "configuration_digest",
                    "source_request_ids",
                    "source_native_event_ids",
                ),
            }.get(event.kind, ())
            missing.extend(name for name in extra_fields if _missing(event.fields.get(name)))
        if missing:
            raise DecisionError(f"{event.kind.value} missing fields: {', '.join(missing)}")
        if event.kind in {ObservationKind.AUTH_SUCCESS, ObservationKind.LOGIN_SUCCESS}:
            self._validate_c01_auth_login_callback(event)
        if self.plan.case_id == "TH04" and event.kind in {
            ObservationKind.ORDER_SUBMIT_RECEIPT,
            ObservationKind.ORDER_CANCEL_RECEIPT,
        }:
            expected_action = (
                "submit" if event.kind is ObservationKind.ORDER_SUBMIT_RECEIPT else "cancel"
            )
            if (
                event.fields.get("action") != expected_action
                or not isinstance(event.fields.get("request_id"), str)
                or not event.fields["request_id"].strip()
                or event.fields.get("dispatch_state") not in {"dispatched", "blocked_pre_dispatch"}
            ):
                raise DecisionError("TH04 managed receipt action/id/dispatch state is invalid")
        _validate_values(event)

    def _validate_no_login_identity_aliases(self, event: NativeObservation) -> None:
        validate_payloadless_callback_fields(
            event,
            scope_account_identity_sha256=self.scope.account_identity_sha256,
        )

    def _validate_c01_auth_login_callback(self, event: NativeObservation) -> None:
        fields = event.fields
        is_auth = event.kind is ObservationKind.AUTH_SUCCESS
        if type(fields.get("request_id")) is not int or fields.get("request_id") <= 0:
            raise DecisionError("native auth/login callback requires positive echoed request_id")
        if type(fields.get("request_generation")) is not int or (
            fields.get("request_generation") != event.request_generation
            or event.request_generation < 1
            or event.request_generation_origin != "local_request_generation_binding"
        ):
            raise DecisionError("native request_id requires matching local request_generation")
        if event.request_id_origin != "native_callback_argument":
            raise DecisionError("request_id origin must be the native CTP callback argument")
        if type(fields.get("arrival_generation")) is not int or (
            fields.get("arrival_generation") != event.arrival_generation
            or event.arrival_generation < 1
        ):
            raise DecisionError("native callback requires matching local arrival_generation")
        if not isinstance(event.client_instance_id, str) or not event.client_instance_id.strip():
            raise DecisionError("C01 callback requires local client_instance_id")
        if type(fields.get("is_last")) is not bool or fields.get("is_last") is not True:
            raise DecisionError("auth/login native response requires exact is_last=True")
        if type(fields.get("error_id")) is not int or fields.get("error_id") != 0:
            raise DecisionError("auth/login native ErrorID must be integer zero")
        if event.sequence_origin != "local_sdk_callback_arrival":
            raise DecisionError("auth/login source sequence must be local callback arrival")
        if event.timestamp_origin != "local_sdk_capture_clock":
            raise DecisionError("auth/login timestamp must be local SDK capture time")
        if _parse_utc(event.arrived_at_utc) is None or _parse_utc(event.occurred_at_utc) != _parse_utc(
            event.arrived_at_utc
        ):
            raise DecisionError("auth/login occurred_at_utc must mirror local arrived_at_utc")
        if (
            type(event.arrived_monotonic) not in {int, float}
            or isinstance(event.arrived_monotonic, bool)
            or event.arrived_monotonic <= 0
        ):
            raise DecisionError("auth/login requires positive local arrived_monotonic")
        if fields.get("success") is not True:
            raise DecisionError("auth/login provider callback must report success")
        if (
            event.event_id_origin != "local_sdk_callback_arrival"
            or event.provider_issued_event_id is not False
        ):
            raise DecisionError("auth/login event id must be explicitly local")
        impossible_provider_metadata = (
            "provider_timestamp_utc",
            "provider_sequence",
            "provider_event_id",
            "source_sequence",
            "source_timestamp_utc",
        )
        if any(fields.get(name) not in (None, "") for name in impossible_provider_metadata):
            raise DecisionError("auth/login callback cannot claim provider time, sequence, or event ID")
        if is_auth:
            if event.provider_front_id is not None or event.provider_session_id or event.trading_day:
                raise DecisionError(
                    "OnRspAuthenticate cannot claim login-only provider identity fields"
                )
            if any(
                fields.get(name) not in (None, "")
                for name in (
                    "provider_front_id",
                    "provider_session_id",
                    "trading_day",
                    "provider_timestamp_utc",
                    "provider_sequence",
                    "provider_event_id",
                    "source_sequence",
                    "source_timestamp_utc",
                )
            ):
                raise DecisionError("OnRspAuthenticate evidence contains impossible provider fields")
            if (
                event.session_identity_origin
                != "unavailable_on_native_authentication_response"
            ):
                raise DecisionError("authentication identity origin must remain unavailable")
            return
        front_id = fields.get("provider_front_id")
        session_id = fields.get("provider_session_id")
        trading_day = fields.get("trading_day")
        if type(front_id) is not int or front_id < 1:
            raise DecisionError("OnRspUserLogin requires native positive provider_front_id")
        if not isinstance(session_id, str) or not session_id.isdigit():
            raise DecisionError("OnRspUserLogin requires native provider_session_id")
        if not isinstance(trading_day, str) or not re.fullmatch(r"[0-9]{8}", trading_day):
            raise DecisionError("OnRspUserLogin requires native YYYYMMDD trading_day")
        if (
            event.provider_front_id != front_id
            or event.provider_session_id != session_id
            or event.trading_day != trading_day
            or event.session_identity_origin != "native_login_response_fields"
        ):
            raise DecisionError("OnRspUserLogin scope must match native provider identity fields")

    def _all(self, kind: ObservationKind) -> list[NativeObservation]:
        return [item for item in self._events if item.kind is kind]

    def _last(self, kind: ObservationKind) -> NativeObservation | None:
        events = self._all(kind)
        return events[-1] if events else None

    def _missing(self, now: datetime) -> tuple[str, ...]:
        missing = [kind.value for kind in self.spec.required_kinds if not self._all(kind)]
        rule = self.spec.rule

        def require(condition: bool, label: str) -> None:
            if not condition:
                missing.append(label)

        if rule in _SESSION_REQUIRED_RULES:
            require(self._session_ready(), "provider_session_not_ready")
        if rule in _TICK_REQUIRED_RULES:
            require(self._fresh_tick(now), "fresh_valid_market_tick_required")

        admission = self._last(ObservationKind.ORDER_ADMISSION)
        if self.spec.admission_kind:
            require(
                bool(
                    admission
                    and admission.fields.get("case_id") == self.plan.case_id
                    and admission.fields.get("intent_kind") == self.spec.admission_kind
                    and admission.fields.get("approval_state") == "REVIEW_ONLY"
                    and admission.fields.get("dispatch_permitted") is False
                    and _positive(admission.fields.get("maximum_quantity"))
                    and str(admission.fields.get("approval_ref", "")).strip()
                ),
                "case_bound_review_only_admission_required",
            )

        if rule == "auth_login":
            missing.append("trusted_c01_issued_request_ledger_verifier_required")
            missing.append("c01_baseline_final_query_receipt_path_not_wired")
            require(self._success(ObservationKind.AUTH_SUCCESS), "authentication_success_required")
            require(self._success(ObservationKind.LOGIN_SUCCESS), "login_success_required")
            auth_events = self._all(ObservationKind.AUTH_SUCCESS)
            login_events = self._all(ObservationKind.LOGIN_SUCCESS)
            if len(auth_events) != 1 or len(login_events) != 1:
                missing.append("one_auth_and_one_login_callback_required")
            else:
                auth, login = auth_events[0], login_events[0]
                if (
                    auth.stream_id != login.stream_id
                    or auth.client_instance_id != login.client_instance_id
                    or auth.arrival_generation != login.arrival_generation
                    or auth.request_generation == login.request_generation
                ):
                    missing.append("auth_login_same_client_generation_and_distinct_requests_required")
                auth_request_id = auth.fields.get("request_id")
                login_request_id = login.fields.get("request_id")
                if (
                    type(auth_request_id) is not int
                    or type(login_request_id) is not int
                    or auth_request_id == login_request_id
                ):
                    missing.append("auth_login_native_request_ids_must_be_distinct")
                if (
                    auth.sequence >= login.sequence
                    or _parse_utc(auth.arrived_at_utc) >= _parse_utc(login.arrived_at_utc)
                ):
                    missing.append("authentication_must_arrive_before_login_on_same_client")
                for event, request_kind in ((auth, "authenticate"), (login, "login")):
                    if not validate_issued_request_receipt(
                        event.issued_request_receipt,
                        request_kind=request_kind,
                        phase="",
                        request_id=event.fields.get("request_id"),
                        request_generation=event.request_generation,
                        client_instance_id=event.client_instance_id,
                        arrival_generation=event.arrival_generation,
                        arrived_at_utc=event.arrived_at_utc,
                        arrived_monotonic=event.arrived_monotonic,
                    ):
                        missing.append(f"{request_kind}_issued_request_receipt_required")
        elif rule in {"connected", "system_log"}:
            require(self._session_ready(), "provider_connection_not_fully_ready")
            if rule == "system_log":
                require(bool(self._all(ObservationKind.SYSTEM_LOG)), "managed_system_log_required")
        elif rule == "disconnected":
            require(
                self._disconnected(),
                "correlated_native_disconnect_and_control_receipt_required",
            )
        elif rule == "reconnected":
            require(self._reconnected(), "different_authenticated_provider_session_required")
            require(
                self._external_satisfied("external_reconnect"),
                "external_reconnect_condition_not_confirmed",
            )
        elif rule == "close_order":
            require(self._positive_position(), "provider_closeable_position_required")
            require(self._tick_matches_position(), "position_and_tick_instrument_mismatch")
        elif rule in {"cancel_order", "cancel_count"}:
            require(self._target_open_orders(1), "provider_confirmed_open_order_required")
            if rule == "cancel_order":
                require(
                    bool(admission and admission.fields.get("cancel_window_open") is True),
                    "provider_cancel_window_not_confirmed",
                )
                require(self._tick_matches_open_order(), "order_and_tick_instrument_mismatch")
        elif rule.startswith("repeat_"):
            expected = {"repeat_open": "open", "repeat_close": "close", "repeat_cancel": "cancel"}[
                rule
            ]
            repeat = self._last(ObservationKind.REPEAT_GUARD)
            require(
                bool(
                    repeat
                    and repeat.fields.get("action_kind") == expected
                    and _integer(repeat.fields.get("repeat_count"), minimum=2)
                    and str(repeat.fields.get("repeat_key", "")).strip()
                ),
                "matching_repeat_monitor_count_at_least_two_required",
            )
            if rule == "repeat_close":
                require(self._positive_position(), "provider_closeable_position_required")
            if rule == "repeat_cancel":
                require(self._target_open_orders(1), "provider_confirmed_open_order_required")
        elif rule.startswith("configure_"):
            metric = {
                "configure_order": "submitted_order_count",
                "configure_cancel": "cancel_order_count",
                "configure_repeat": "repeat_order_count",
            }[rule]
            config = self._last(ObservationKind.MONITOR_CONFIGURATION)
            require(
                bool(
                    config
                    and config.fields.get("metric") == metric
                    and _integer(config.fields.get("threshold"), minimum=1)
                ),
                "case_specific_monitor_configuration_required",
            )
            if rule == "configure_repeat":
                require(
                    bool(config and _positive(config.fields.get("window_seconds"))),
                    "repeat_window_must_be_positive",
                )
        elif rule.startswith("trigger_"):
            require(
                self._trigger_correlated(rule),
                "threshold_trigger_not_correlated_to_native_activity",
            )
        elif rule.startswith("validate_") or rule == "validation_log":
            require(
                self._validation_proof(rule),
                "matching_validator_rejection_and_zero_dispatch_required",
            )
        elif rule.startswith("reject_"):
            require(
                self._remote_rejection_proof(rule),
                "external_condition_and_correlated_native_rejection_required",
            )
        elif rule == "account_permission":
            require(
                self._account_permission_proof(),
                "permission_disable_reject_restore_and_empty_query_required",
            )
        elif rule == "strategy_paused":
            query = self._last(ObservationKind.ORDER_QUERY)
            require(
                bool(
                    query
                    and query.fields.get("complete") is True
                    and not query.fields.get("open_order_refs")
                ),
                "final_query_must_show_no_open_orders",
            )
        elif rule == "force_logout":
            require(self._force_logout_proof(), "operator_ack_disconnect_and_write_guard_required")
        elif rule == "batch_partials":
            require(
                self._batch_partials_ready(),
                "two_partial_orders_trade_reconciliation_and_batch_capability_required",
            )
        elif rule == "batch_open":
            require(
                self._batch_open_ready(),
                "two_current_native_open_orders_and_batch_capability_required",
            )
        elif rule == "trade_log":
            require(self._trade_correlated(), "trade_must_correlate_to_provider_order")
        elif rule == "monitor_log":
            require(
                bool(self._all(ObservationKind.ORDER_ACCEPTED)), "native_order_activity_required"
            )
        return tuple(dict.fromkeys(missing))

    def _success(self, kind: ObservationKind) -> bool:
        event = self._last(kind)
        return bool(
            event
            and event.fields.get("success") is True
            and _integer(event.fields.get("error_id")) == 0
        )

    def _session_ready(self) -> bool:
        return (
            self._success(ObservationKind.AUTH_SUCCESS)
            and self._success(ObservationKind.LOGIN_SUCCESS)
            and bool(
                self._all(ObservationKind.FRONT_CONNECTED)
                and self._success(ObservationKind.MARKET_SUBSCRIPTION_ACK)
            )
        )

    def _fresh_tick(self, now: datetime) -> bool:
        tick = self._last(ObservationKind.MARKET_TICK)
        if tick is None or now.tzinfo is None or now.utcoffset() != timedelta(0):
            return False
        occurred = _parse_utc(tick.occurred_at_utc)
        if occurred is None or not timedelta(0) <= now - occurred <= timedelta(seconds=2):
            return False
        bid, ask, last, price_tick = (
            _decimal(tick.fields.get(key)) for key in ("bid", "ask", "last", "price_tick")
        )
        return bool(
            bid
            and ask
            and last
            and price_tick
            and bid > 0
            and ask >= bid
            and last > 0
            and price_tick > 0
        )

    def _positive_position(self) -> bool:
        snapshots = [
            event
            for event in self._all(ObservationKind.POSITION_QUERY)
            if event.fields.get("complete") is True and event.fields.get("phase") == "baseline"
        ]
        quantity = _decimal(snapshots[-1].fields.get("closeable_quantity")) if snapshots else None
        return quantity is not None and quantity > 0

    def _tick_matches_position(self) -> bool:
        tick, positions = (
            self._last(ObservationKind.MARKET_TICK),
            [
                event
                for event in self._all(ObservationKind.POSITION_QUERY)
                if event.fields.get("phase") == "baseline"
            ],
        )
        return bool(
            tick
            and positions
            and tick.fields.get("instrument_id") == positions[-1].fields.get("instrument_id")
        )

    def _target_open_orders(self, minimum: int) -> bool:
        query = self._last(ObservationKind.ORDER_QUERY)
        accepted = {
            str(event.fields.get("order_ref"))
            for event in self._all(ObservationKind.ORDER_ACCEPTED)
        }
        open_refs = set(query.fields.get("open_order_refs", ())) if query else set()
        return bool(
            query and query.fields.get("complete") is True and len(accepted & open_refs) >= minimum
        )

    def _tick_matches_open_order(self) -> bool:
        tick, query = (
            self._last(ObservationKind.MARKET_TICK),
            self._last(ObservationKind.ORDER_QUERY),
        )
        if not tick or not query:
            return False
        open_refs = set(query.fields.get("open_order_refs", ()))
        return any(
            event.fields.get("order_ref") in open_refs
            and event.fields.get("instrument_id") == tick.fields.get("instrument_id")
            for event in self._all(ObservationKind.ORDER_ACCEPTED)
        )

    def _disconnected(self) -> bool:
        for disconnected in self._all(ObservationKind.FRONT_DISCONNECTED):
            old_generation = _integer(disconnected.fields.get("connection_generation"), minimum=1)
            if (
                old_generation is None
                or not disconnected.client_instance_id
                or disconnected.provider_session_id
                or disconnected.trading_day
                or disconnected.provider_front_id is not None
                or disconnected.arrival_generation != old_generation
                or disconnected.connection_generation_origin != "local_connection_generation"
            ):
                continue
            disconnected_at = _parse_utc(disconnected.occurred_at_utc)
            old_logins = [
                item
                for item in self._all(ObservationKind.LOGIN_SUCCESS)
                if item.client_instance_id == disconnected.client_instance_id
                and item.stream_id == disconnected.stream_id
                and item.arrival_generation == old_generation
                and item.fields.get("connection_generation") == old_generation
                and item.session_identity_origin == "native_login_response_fields"
                and item.sequence < disconnected.sequence
                and _parse_utc(item.occurred_at_utc) < disconnected_at
            ]
            if len(old_logins) != 1:
                continue
            old_login = old_logins[0]
            if any(
                item.fields.get("condition_id") == "external_disconnect"
                and item.fields.get("state") == "satisfied"
                and item.fields.get("gateway_key") == disconnected.fields.get("gateway_key")
                and item.fields.get("session_id") == old_login.provider_session_id
                and item.fields.get("connection_generation") == old_generation
                and item.fields.get("provider_event_ref") == disconnected.event_id
                and _parse_utc(item.occurred_at_utc) >= disconnected_at
                for item in self._all(ObservationKind.EXTERNAL_CONDITION)
            ):
                return True
        return False

    def _reconnected(self) -> bool:
        disconnects = self._all(ObservationKind.FRONT_DISCONNECTED)
        if not disconnects:
            return False
        disconnected = disconnects[-1]
        disconnected_at = _parse_utc(disconnected.occurred_at_utc)
        old_generation = _integer(disconnected.fields.get("connection_generation"), minimum=1)
        if (
            old_generation is None
            or not disconnected.client_instance_id
            or not disconnected.stream_id
            or disconnected.provider_session_id
            or disconnected.trading_day
            or disconnected.provider_front_id is not None
            or disconnected.arrival_generation != old_generation
            or disconnected.connection_generation_origin != "local_connection_generation"
        ):
            return False
        old_logins = [
            item
            for item in self._all(ObservationKind.LOGIN_SUCCESS)
            if item.client_instance_id == disconnected.client_instance_id
            and item.stream_id == disconnected.stream_id
            and item.arrival_generation == old_generation
            and item.fields.get("connection_generation") == old_generation
            and item.session_identity_origin == "native_login_response_fields"
            and item.sequence < disconnected.sequence
            and _parse_utc(item.occurred_at_utc) < disconnected_at
        ]
        if len(old_logins) != 1:
            return False
        old_login = old_logins[0]
        old_scope = (old_login.provider_session_id, old_login.trading_day)
        for connected in self._all(ObservationKind.FRONT_CONNECTED):
            connected_at = _parse_utc(connected.occurred_at_utc)
            new_generation = _integer(connected.fields.get("connection_generation"), minimum=1)
            if (
                connected.provider_session_id
                or connected.trading_day
                or connected.provider_front_id is not None
                or connected.client_instance_id != disconnected.client_instance_id
                or connected.stream_id != disconnected.stream_id
                or connected.fields.get("gateway_key") != disconnected.fields.get("gateway_key")
                or connected_at <= disconnected_at
                or connected.sequence <= disconnected.sequence
                or new_generation is None
                or new_generation <= old_generation
                or connected.arrival_generation != new_generation
                or connected.connection_generation_origin != "local_connection_generation"
            ):
                continue
            login_bindings = [
                item
                for item in self._all(ObservationKind.LOGIN_SUCCESS)
                if item.client_instance_id == connected.client_instance_id
                and item.arrival_generation == new_generation
                and item.stream_id == connected.stream_id
                and item.sequence > connected.sequence
                and item.fields.get("connection_generation") == new_generation
                and item.session_identity_origin == "native_login_response_fields"
                and item.provider_session_id
                and item.trading_day
                and _parse_utc(item.occurred_at_utc) >= connected_at
            ]
            if len(login_bindings) != 1:
                continue
            login_binding = login_bindings[0]
            new_scope = (login_binding.provider_session_id, login_binding.trading_day)
            if new_scope[0] == old_scope[0] or new_scope[1] != old_scope[1]:
                continue

            auth_rows = [
                item
                for item in self._all(ObservationKind.AUTH_SUCCESS)
                if item.stream_id == connected.stream_id
                and item.client_instance_id == connected.client_instance_id
                and item.arrival_generation == new_generation
                and item.sequence > connected.sequence
                and item.sequence < login_binding.sequence
                and item.fields.get("connection_generation") == new_generation
                and item.session_identity_origin
                == "unavailable_on_native_authentication_response"
                and item.fields.get("success") is True
                and _integer(item.fields.get("error_id")) == 0
                and (arrived_at := _parse_utc(item.occurred_at_utc)) is not None
                and connected_at <= arrived_at <= _parse_utc(login_binding.occurred_at_utc)
            ]
            market_rows = [
                item
                for item in self._all(ObservationKind.MARKET_SUBSCRIPTION_ACK)
                if item.stream_id == connected.stream_id
                and item.client_instance_id == connected.client_instance_id
                and item.arrival_generation == new_generation
                and item.sequence > login_binding.sequence
                and item.fields.get("connection_generation") == new_generation
                and (item.provider_session_id, item.trading_day) == new_scope
                and item.session_identity_origin
                == "derived_from_same_client_generation_native_login"
                and item.fields.get("success") is True
                and _integer(item.fields.get("error_id")) == 0
                and _parse_utc(item.occurred_at_utc)
                >= _parse_utc(login_binding.occurred_at_utc)
            ]
            if not auth_rows or not market_rows:
                continue
            authentication = auth_rows[0]
            subscribed = market_rows[0]
            if not (
                connected.sequence < authentication.sequence
                < login_binding.sequence < subscribed.sequence
                and _parse_utc(connected.occurred_at_utc)
                <= _parse_utc(authentication.occurred_at_utc)
                <= _parse_utc(login_binding.occurred_at_utc)
                <= _parse_utc(subscribed.occurred_at_utc)
            ):
                continue
            if any(
                item.fields.get("condition_id") == "external_reconnect"
                and item.fields.get("state") == "satisfied"
                and item.fields.get("previous_session_id") == old_scope[0]
                and item.fields.get("new_session_id") == new_scope[0]
                and item.fields.get("gateway_key") == connected.fields.get("gateway_key")
                and item.fields.get("previous_connection_generation") == old_generation
                and item.fields.get("new_connection_generation") == new_generation
                and item.fields.get("disconnect_event_ref") == disconnected.event_id
                and item.fields.get("reconnect_event_ref") == connected.event_id
                and _parse_utc(item.occurred_at_utc) >= _parse_utc(subscribed.occurred_at_utc)
                for item in self._all(ObservationKind.EXTERNAL_CONDITION)
            ):
                return True
        return False

    def _trigger_correlated(self, rule: str) -> bool:
        if rule == "trigger_cancel" and self.plan.case_id == "TH04":
            return self._th04_combined_request_trigger_correlated()
        trigger = self._last(ObservationKind.MONITOR_TRIGGER)
        if not trigger:
            return False
        metric = {
            "trigger_order": "submitted_order_count",
            "trigger_cancel": "cancel_order_count",
            "trigger_repeat": "repeat_order_count",
        }[rule]
        threshold = _integer(trigger.fields.get("threshold"), minimum=1)
        observed = _integer(trigger.fields.get("observed_value"), minimum=1)
        if (
            trigger.fields.get("metric") != metric
            or threshold is None
            or observed is None
            or observed < threshold
        ):
            return False
        config = self._last(ObservationKind.MONITOR_CONFIGURATION)
        if (
            not config
            or config.fields.get("metric") != metric
            or _integer(config.fields.get("threshold"), minimum=1) != threshold
        ):
            return False
        if rule == "trigger_order":
            count = len(
                {
                    event.fields.get("order_ref")
                    for event in self._all(ObservationKind.ORDER_ACCEPTED)
                }
            )
            return count >= threshold and observed <= count
        if rule == "trigger_cancel":
            count = len(
                {
                    event.fields.get("order_ref")
                    for event in self._all(ObservationKind.ORDER_CANCELED)
                }
            )
            return count >= threshold and observed <= count
        guard = self._last(ObservationKind.REPEAT_GUARD)
        return bool(guard and _integer(guard.fields.get("repeat_count")) == observed)

    def _th04_combined_request_trigger_correlated(self) -> bool:
        """Bind TH04's combined count to managed requests, not callback refs."""
        config = self._last(ObservationKind.MONITOR_CONFIGURATION)
        trigger = self._last(ObservationKind.MONITOR_TRIGGER)
        if config is None or trigger is None:
            return False
        config_fields, trigger_fields = config.fields, trigger.fields
        threshold = _integer(config_fields.get("threshold"), minimum=1)
        observed = _integer(trigger_fields.get("observed_value"), minimum=1)
        if (
            config_fields.get("metric") != "combined_order_cancel_count"
            or trigger_fields.get("metric") != "combined_order_cancel_count"
            or threshold != 3
            or trigger_fields.get("threshold") != threshold
            or observed is None
            or observed < threshold
            or not _SHA256_RE.fullmatch(str(config_fields.get("configuration_digest", "")))
            or trigger_fields.get("configuration_digest")
            != config_fields.get("configuration_digest")
            or not _SHA256_RE.fullmatch(str(config_fields.get("monitor_digest", "")))
            or trigger_fields.get("monitor_digest") != config_fields.get("monitor_digest")
        ):
            return False

        receipts = [
            *self._all(ObservationKind.ORDER_SUBMIT_RECEIPT),
            *self._all(ObservationKind.ORDER_CANCEL_RECEIPT),
        ]
        request_ids = [event.fields.get("request_id") for event in receipts]
        if any(
            not isinstance(request_id, str) or not request_id.strip() for request_id in request_ids
        ) or len(set(request_ids)) != len(request_ids):
            return False
        dispatched = [
            event for event in receipts if event.fields.get("dispatch_state") == "dispatched"
        ]
        if (
            not any(event.kind is ObservationKind.ORDER_SUBMIT_RECEIPT for event in dispatched)
            or not any(event.kind is ObservationKind.ORDER_CANCEL_RECEIPT for event in dispatched)
            or observed != len(dispatched)
        ):
            return False
        expected_request_ids = tuple(
            sorted(str(event.fields["request_id"]) for event in dispatched)
        )
        supplied_request_ids = trigger_fields.get("source_request_ids")
        if (
            not isinstance(supplied_request_ids, (tuple, list))
            or tuple(supplied_request_ids) != expected_request_ids
        ):
            return False

        submit_refs = {
            str(event.fields.get("order_ref"))
            for event in dispatched
            if event.kind is ObservationKind.ORDER_SUBMIT_RECEIPT
        }
        dispatched_submits = sum(
            event.kind is ObservationKind.ORDER_SUBMIT_RECEIPT for event in dispatched
        )
        cancel_refs = {
            str(event.fields.get("order_ref"))
            for event in dispatched
            if event.kind is ObservationKind.ORDER_CANCEL_RECEIPT
        }
        accepted = {
            str(event.fields.get("order_ref"))
            for event in self._all(ObservationKind.ORDER_ACCEPTED)
        }
        canceled_events = self._all(ObservationKind.ORDER_CANCELED)
        canceled_refs = {str(event.fields.get("order_ref")) for event in canceled_events}
        if (
            not submit_refs
            or len(submit_refs) != dispatched_submits
            or submit_refs != accepted
            or not cancel_refs
            or not cancel_refs.issubset(accepted)
            or not canceled_refs
            or not canceled_refs.issubset(cancel_refs)
        ):
            return False
        native_event_ids = tuple(
            sorted(
                event.event_id
                for event in (*self._all(ObservationKind.ORDER_ACCEPTED), *canceled_events)
            )
        )
        supplied_native_ids = trigger_fields.get("source_native_event_ids")
        return bool(
            isinstance(supplied_native_ids, (tuple, list))
            and tuple(supplied_native_ids) == native_event_ids
        )

    def _validation_proof(self, rule: str) -> bool:
        expected = {
            "validate_instrument": "instrument",
            "validate_tick": "price_tick",
            "validate_size": "max_order_size",
            "validation_log": None,
        }[rule]
        audits = {
            event.fields.get("order_ref"): event
            for event in self._all(ObservationKind.DISPATCH_ABSENCE)
        }
        for event in self._all(ObservationKind.VALIDATION_REJECTION):
            ref = event.fields.get("order_ref")
            if expected is not None and event.fields.get("rule") != expected:
                continue
            audit = audits.get(ref)
            if not audit or _integer(audit.fields.get("dispatch_count")) != 0:
                continue
            if any(
                item.fields.get("order_ref") == ref
                for item in self._events
                if item.kind
                in {
                    ObservationKind.ORDER_ACCEPTED,
                    ObservationKind.ORDER_PARTIAL,
                    ObservationKind.ORDER_REJECTED,
                }
            ):
                continue
            if rule == "validate_tick" and not self._all(ObservationKind.MARKET_TICK):
                continue
            if rule == "validate_instrument":
                if (
                    not str(event.fields.get("instrument_id", "")).strip()
                    or event.fields.get("instrument_lookup_found") is not False
                ):
                    continue
            if rule == "validate_tick":
                tick = self._last(ObservationKind.MARKET_TICK)
                proposed = _decimal(event.fields.get("proposed_price"))
                price_tick = _decimal(tick.fields.get("price_tick")) if tick else None
                if proposed is None or price_tick is None or price_tick <= 0:
                    continue
                if proposed % price_tick == 0:
                    continue
            if rule == "validate_size":
                admission = self._last(ObservationKind.ORDER_ADMISSION)
                requested = _decimal(event.fields.get("requested_size"))
                maximum = _decimal(event.fields.get("maximum_order_size"))
                admitted_maximum = (
                    _decimal(admission.fields.get("maximum_order_size")) if admission else None
                )
                if (
                    requested is None
                    or maximum is None
                    or requested <= maximum
                    or admitted_maximum != maximum
                ):
                    continue
            return True
        return False

    def _remote_rejection_proof(self, rule: str) -> bool:
        expected = {
            "reject_funds": "insufficient_funds",
            "reject_position": "insufficient_position",
            "reject_market": "market_state",
        }[rule]
        condition = next(
            (
                event
                for event in reversed(self._all(ObservationKind.EXTERNAL_CONDITION))
                if event.fields.get("condition_id") == expected
                and event.fields.get("state") == "satisfied"
            ),
            None,
        )
        submits = {
            event.fields.get("order_ref")
            for event in self._all(ObservationKind.ORDER_SUBMIT_RECEIPT)
        }
        rejected = [
            event
            for event in self._all(ObservationKind.ORDER_REJECTED)
            if event.fields.get("rejection_class") == expected
            and _integer(event.fields.get("error_id"), minimum=1)
        ]
        if not condition or not any(event.fields.get("order_ref") in submits for event in rejected):
            return False
        if rule == "reject_funds":
            available = _decimal(condition.fields.get("available_funds"))
            required = _decimal(condition.fields.get("required_margin"))
            if available is None or required is None or available >= required:
                return False
        if rule == "reject_position":
            closeable = _decimal(condition.fields.get("available_closeable_quantity"))
            requested = _decimal(condition.fields.get("requested_close_quantity"))
            if (
                closeable is None
                or requested is None
                or closeable >= requested
                or not str(condition.fields.get("instrument_id", "")).strip()
            ):
                return False
        if rule == "reject_market":
            tick = self._last(ObservationKind.MARKET_TICK)
            return bool(
                tick
                and tick.fields.get("market_state") in {"closed", "halted", "non_trading"}
                and condition.fields.get("source_event_id")
                and condition.fields.get("market_state") == tick.fields.get("market_state")
            )
        return True

    def _account_permission_proof(self) -> bool:
        disabled, restored = (
            self._last(ObservationKind.ACCOUNT_PERMISSION_DISABLED),
            self._last(ObservationKind.ACCOUNT_PERMISSION_RESTORED),
        )
        if (
            not disabled
            or not restored
            or disabled.fields.get("account_id_masked") != restored.fields.get("account_id_masked")
        ):
            return False
        submits = {
            event.fields.get("order_ref")
            for event in self._all(ObservationKind.ORDER_SUBMIT_RECEIPT)
        }
        rejected = any(
            event.fields.get("order_ref") in submits
            and event.fields.get("rejection_class") == "account_permission_denied"
            and _integer(event.fields.get("error_id"), minimum=1)
            for event in self._all(ObservationKind.ORDER_REJECTED)
        )
        query = self._last(ObservationKind.ORDER_QUERY)
        return bool(
            rejected
            and query
            and query.fields.get("complete") is True
            and not query.fields.get("open_order_refs")
        )

    def _force_logout_proof(self) -> bool:
        auth, disconnect, blocked = (
            self._last(kind)
            for kind in (
                ObservationKind.GATEWAY_LOGOUT_AUTHORIZED,
                ObservationKind.FRONT_DISCONNECTED,
                ObservationKind.POST_DISCONNECT_WRITE_BLOCKED,
            )
        )
        return bool(
            auth
            and disconnect
            and blocked
            and auth.fields.get("gateway_key")
            == disconnect.fields.get("gateway_key")
            == blocked.fields.get("gateway_key")
            and _integer(blocked.fields.get("blocked_attempt_count"), minimum=1)
        )

    def _batch_partials_ready(self) -> bool:
        admission, query = (
            self._last(ObservationKind.ORDER_ADMISSION),
            self._last(ObservationKind.ORDER_QUERY),
        )
        if (
            not admission
            or admission.fields.get("batch_cancel_supported") is not True
            or not query
            or query.fields.get("complete") is not True
        ):
            return False
        partials = {
            event.fields.get("order_ref"): event
            for event in self._all(ObservationKind.ORDER_PARTIAL)
        }
        if len(partials) < 2:
            return False
        accepted_by_ref = {
            event.fields.get("order_ref"): event
            for event in self._all(ObservationKind.ORDER_ACCEPTED)
        }
        if any(
            ref not in accepted_by_ref or accepted_by_ref[ref].sequence >= partial.sequence
            for ref, partial in partials.items()
        ):
            return False
        traded: dict[str, Decimal] = {}
        for event in self._all(ObservationKind.TRADE_EXECUTION):
            quantity = _decimal(event.fields.get("quantity"))
            if quantity and quantity > 0:
                ref = str(event.fields.get("order_ref"))
                traded[ref] = traded.get(ref, Decimal(0)) + quantity
        if any(
            (_decimal(event.fields.get("traded_quantity")) or Decimal(0))
            > traded.get(str(ref), Decimal(0))
            for ref, event in partials.items()
        ):
            return False
        provider_activity = (
            *self._all(ObservationKind.ORDER_PARTIAL),
            *self._all(ObservationKind.TRADE_EXECUTION),
        )
        if not provider_activity or query.sequence <= max(
            event.sequence for event in provider_activity
        ):
            return False
        return len(set(partials) & set(query.fields.get("open_order_refs", ()))) >= 2

    def _batch_open_ready(self) -> bool:
        admission, query = (
            self._last(ObservationKind.ORDER_ADMISSION),
            self._last(ObservationKind.ORDER_QUERY),
        )
        if (
            not admission
            or admission.fields.get("batch_cancel_supported") is not True
            or not query
            or query.fields.get("complete") is not True
        ):
            return False
        accepted_events = self._all(ObservationKind.ORDER_ACCEPTED)
        if not accepted_events or query.sequence <= max(
            event.sequence for event in accepted_events
        ):
            return False
        accepted = {event.fields.get("order_ref") for event in accepted_events}
        # A fill/cancel race is allowed; the latest complete native query is
        # the source for which accepted orders are still open.
        return len(accepted & set(query.fields.get("open_order_refs", ()))) >= 2

    def _trade_correlated(self) -> bool:
        accepted = {
            event.fields.get("order_ref") for event in self._all(ObservationKind.ORDER_ACCEPTED)
        }
        return any(
            event.fields.get("order_ref") in accepted
            for event in self._all(ObservationKind.TRADE_EXECUTION)
        )

    def _external_satisfied(self, condition_id: str) -> bool:
        return any(
            event.fields.get("condition_id") == condition_id
            and event.fields.get("state") == "satisfied"
            for event in self._all(ObservationKind.EXTERNAL_CONDITION)
        )

    def _correlation_refs(self) -> tuple[str, ...]:
        if self.plan.case_id == "TH04":
            return tuple(
                sorted(
                    {
                        str(event.fields.get("order_ref"))
                        for event in (
                            *self._all(ObservationKind.ORDER_ACCEPTED),
                            *self._all(ObservationKind.ORDER_CANCELED),
                        )
                    }
                )
            )
        if self.spec.rule == "batch_partials":
            return tuple(
                sorted(
                    {
                        str(event.fields.get("order_ref"))
                        for event in self._all(ObservationKind.ORDER_PARTIAL)
                    }
                )
            )
        if self.spec.rule == "batch_open":
            query = self._last(ObservationKind.ORDER_QUERY)
            accepted = {
                str(event.fields.get("order_ref"))
                for event in self._all(ObservationKind.ORDER_ACCEPTED)
            }
            return tuple(
                sorted(accepted & set(query.fields.get("open_order_refs", ())) if query else ())
            )
        if self.spec.rule in {"cancel_order", "cancel_count", "repeat_cancel"}:
            query = self._last(ObservationKind.ORDER_QUERY)
            return tuple(sorted(query.fields.get("open_order_refs", ())) if query else ())
        if self.spec.rule.startswith("reject_"):
            return tuple(
                str(event.fields.get("order_ref"))
                for event in self._all(ObservationKind.ORDER_REJECTED)
            )
        return ()


def _validate_values(event: NativeObservation) -> None:
    fields = event.fields
    if event.kind in {
        ObservationKind.AUTH_SUCCESS,
        ObservationKind.LOGIN_SUCCESS,
        ObservationKind.MARKET_SUBSCRIPTION_ACK,
    }:
        if fields.get("success") is not True or _integer(fields.get("error_id")) != 0:
            raise DecisionError("provider acknowledgement is not successful")
    if event.kind is ObservationKind.MARKET_TICK:
        if any(_decimal(fields.get(key)) is None for key in ("bid", "ask", "last", "price_tick")):
            raise DecisionError("tick numeric fields must be finite decimals")
    if event.kind in {
        ObservationKind.ORDER_ACCEPTED,
        ObservationKind.ORDER_PARTIAL,
        ObservationKind.ORDER_CANCELED,
        ObservationKind.ORDER_FILLED,
    }:
        allowed_statuses = {
            ObservationKind.ORDER_ACCEPTED: {"accepted", "working"},
            ObservationKind.ORDER_PARTIAL: {"partial"},
            ObservationKind.ORDER_CANCELED: {"canceled", "cancelled"},
            ObservationKind.ORDER_FILLED: {"filled"},
        }
        if fields.get("status") not in allowed_statuses[event.kind]:
            raise DecisionError("provider order status does not match typed observation kind")
        remaining, traded = (
            _decimal(fields.get("remaining_quantity")),
            _decimal(fields.get("traded_quantity", 0)),
        )
        if remaining is None or traded is None or remaining < 0 or traded < 0:
            raise DecisionError("provider order quantities must be finite and non-negative")
        if event.kind is ObservationKind.ORDER_ACCEPTED and remaining <= 0:
            raise DecisionError("accepted order must remain working")
        if event.kind is ObservationKind.ORDER_PARTIAL and (remaining <= 0 or traded <= 0):
            raise DecisionError("partial order needs positive traded and remaining quantity")
        if (
            event.kind in {ObservationKind.ORDER_CANCELED, ObservationKind.ORDER_FILLED}
            and remaining != 0
        ):
            raise DecisionError("terminal order must have zero remaining quantity")
    if event.kind is ObservationKind.TRADE_EXECUTION and not _positive(fields.get("quantity")):
        raise DecisionError("trade quantity must be positive")
    if (
        event.kind is ObservationKind.ORDER_REJECTED
        and _integer(fields.get("error_id"), minimum=1) is None
    ):
        raise DecisionError("native rejection requires positive provider error id")
    if event.kind is ObservationKind.ORDER_QUERY:
        refs = fields.get("open_order_refs")
        if (
            fields.get("complete") is not True
            or not isinstance(refs, (list, tuple, set))
            or any(not isinstance(ref, str) or not ref for ref in refs)
        ):
            raise DecisionError("order query must be complete and contain valid open refs")
    if event.kind is ObservationKind.POSITION_QUERY:
        quantity = _decimal(fields.get("closeable_quantity"))
        if (
            fields.get("complete") is not True
            or fields.get("phase") not in {"baseline", "final"}
            or quantity is None
            or quantity < 0
        ):
            raise DecisionError("position query must be complete, phase-tagged, and non-negative")
    if event.kind is ObservationKind.EXTERNAL_CONDITION:
        if fields.get("state") not in {"satisfied", "unavailable"}:
            raise DecisionError("external condition state must be satisfied/unavailable")
        if fields.get("state") == "unavailable" and not str(fields.get("reason", "")).strip():
            raise DecisionError("unavailable condition requires sourced reason")
    if event.kind is ObservationKind.ORDER_ADMISSION:
        if (
            fields.get("approval_state") != "REVIEW_ONLY"
            or fields.get("dispatch_permitted") is not False
        ):
            raise DecisionError("order admission must be review-only with dispatch disabled")
    if (
        event.kind is ObservationKind.DISPATCH_ABSENCE
        and _integer(fields.get("dispatch_count")) != 0
    ):
        raise DecisionError("dispatch absence must prove zero dispatches")


def _missing(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == ()


def _integer(value: Any, *, minimum: int | None = None) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    if minimum is not None and result < minimum:
        return None
    return result


def _decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _positive(value: Any) -> bool:
    result = _decimal(value)
    return result is not None and result > 0


def _parse_utc(value: str) -> datetime | None:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        return None
    return result.astimezone(timezone.utc)
