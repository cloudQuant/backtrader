"""Read-only typed strategies for a first set of 007 certification cases.

The strategies consume normalized ``NativeObservation`` envelopes only. They
perform no provider I/O, configuration reads, file writes, order dispatch, or
session shutdown. A future managed adapter must supply an accepted
``ObservationAuthenticator``. Even complete evidence returns REVIEW_REQUIRED;
the source-authentication port and test authenticators do not establish real
provider acceptance or grant runtime authority.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .case_engine import (
    CertificationEvidence,
    DescriptiveCasePlan,
    EvidenceSource,
    validate_issued_request_receipt,
)
from .certification import SCENARIOS_BY_CASE_ID
from .completion_invariants import (
    AccountReconciliationSnapshot,
    CompletionEvidence,
    CompletionEvidenceError,
    DispatchState,
    ManagedOrderRequest,
    NativeOrderFact,
    NativeOrderFactKind,
    NativeTradeFact,
    RequestAction,
    SnapshotPhase,
    evaluate_case_completion,
)
from .decision_engine import (
    AuthenticationReceipt,
    DecisionError,
    DecisionScope,
    EvidenceTrustDomain,
    NativeObservation,
    ObservationAuthenticator,
    ObservationKind,
    validate_payloadless_callback_fields,
)

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_MAX_CANDIDATE_EVIDENCE_AGE = timedelta(minutes=5)
_MAX_CANDIDATE_FUTURE_SKEW = timedelta(seconds=30)


class ReadOnlyStrategyError(ValueError):
    """Raised when an envelope does not match a selected case contract."""


class ReadOnlyState(str, Enum):
    BLOCKED = "BLOCKED"
    INCOMPLETE = "INCOMPLETE"
    EXTERNAL_CONDITION_UNAVAILABLE = "EXTERNAL_CONDITION_UNAVAILABLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass(frozen=True)
class ReadOnlyCaseSpec:
    case_id: str
    required_kinds: Tuple[ObservationKind, ...]
    requires_store_connected: bool = False
    requires_store_ready: bool = False
    requires_start_log: bool = False
    requires_process_identity: bool = False
    expected_metric: str = ""
    expected_threshold: int = 0
    requires_repeat_window: bool = False
    order_profile: str = ""


@dataclass(frozen=True)
class ReadOnlyCaseResult:
    case_id: str
    scenario_id: str
    state: ReadOnlyState
    certification_pass: bool
    dispatch_permitted: bool
    source_authenticity_verified: bool
    evidence_event_ids: Tuple[str, ...]
    missing_conditions: Tuple[str, ...]
    rejected_events: Tuple[str, ...]
    unavailable_conditions: Tuple[str, ...] = ()


_ORDER_FLOW_KINDS = (
    ObservationKind.FRONT_CONNECTED,
    ObservationKind.LOGIN_SUCCESS,
    ObservationKind.MARKET_SUBSCRIPTION_ACK,
    ObservationKind.MARKET_TICK,
    ObservationKind.ORDER_ADMISSION,
    ObservationKind.ORDER_SUBMIT_RECEIPT,
    ObservationKind.ORDER_ACCEPTED,
    ObservationKind.ORDER_PARTIAL,
    ObservationKind.ORDER_CANCELED,
    ObservationKind.ORDER_FILLED,
    ObservationKind.ORDER_REJECTED,
    ObservationKind.TRADE_EXECUTION,
    ObservationKind.ORDER_QUERY,
    ObservationKind.POSITION_QUERY,
    ObservationKind.EXTERNAL_CONDITION,
    ObservationKind.SYSTEM_LOG,
)


READ_ONLY_CASE_SPECS: Dict[str, ReadOnlyCaseSpec] = {
    "C01": ReadOnlyCaseSpec(
        "C01",
        (
            ObservationKind.AUTH_SUCCESS,
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.SYSTEM_LOG,
        ),
    ),
    "M01": ReadOnlyCaseSpec(
        "M01",
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_SUBSCRIPTION_ACK,
            ObservationKind.SYSTEM_LOG,
        ),
        requires_store_connected=True,
        requires_store_ready=True,
    ),
    "L02": ReadOnlyCaseSpec(
        "L02",
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_SUBSCRIPTION_ACK,
            ObservationKind.SYSTEM_LOG,
        ),
        requires_store_connected=True,
        requires_store_ready=True,
        requires_start_log=True,
        requires_process_identity=True,
    ),
    "TH01": ReadOnlyCaseSpec(
        "TH01",
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_SUBSCRIPTION_ACK,
            ObservationKind.MARKET_TICK,
            ObservationKind.MONITOR_CONFIGURATION,
            ObservationKind.MONITOR_LOG,
            ObservationKind.SYSTEM_LOG,
        ),
        requires_store_connected=True,
        requires_store_ready=True,
        requires_start_log=True,
        expected_metric="submit_count",
        expected_threshold=5,
    ),
    "TH03": ReadOnlyCaseSpec(
        "TH03",
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_SUBSCRIPTION_ACK,
            ObservationKind.MARKET_TICK,
            ObservationKind.MONITOR_CONFIGURATION,
            ObservationKind.MONITOR_LOG,
            ObservationKind.SYSTEM_LOG,
        ),
        requires_store_connected=True,
        requires_store_ready=True,
        requires_start_log=True,
        expected_metric="submit_cancel_total",
        expected_threshold=10,
    ),
    "TH05": ReadOnlyCaseSpec(
        "TH05",
        (
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_SUBSCRIPTION_ACK,
            ObservationKind.MARKET_TICK,
            ObservationKind.MONITOR_CONFIGURATION,
            ObservationKind.MONITOR_LOG,
            ObservationKind.SYSTEM_LOG,
        ),
        requires_store_connected=True,
        requires_store_ready=True,
        requires_start_log=True,
        expected_metric="duplicate_order",
        expected_threshold=3,
        requires_repeat_window=True,
    ),
    "T01": ReadOnlyCaseSpec("T01", _ORDER_FLOW_KINDS, order_profile="open_cancel"),
    "T02": ReadOnlyCaseSpec("T02", _ORDER_FLOW_KINDS, order_profile="close_position"),
    "T03": ReadOnlyCaseSpec("T03", _ORDER_FLOW_KINDS, order_profile="cancel"),
    "B01": ReadOnlyCaseSpec("B01", _ORDER_FLOW_KINDS, order_profile="batch_partials"),
    "B02": ReadOnlyCaseSpec("B02", _ORDER_FLOW_KINDS, order_profile="batch_open"),
    "L01": ReadOnlyCaseSpec("L01", _ORDER_FLOW_KINDS, order_profile="trade_log"),
}

_SOURCE_POLICY = {
    ObservationKind.AUTH_SUCCESS: (EvidenceTrustDomain.CTP_CALLBACK, "OnRspAuthenticate"),
    ObservationKind.LOGIN_SUCCESS: (EvidenceTrustDomain.CTP_CALLBACK, "OnRspUserLogin"),
    ObservationKind.FRONT_CONNECTED: (EvidenceTrustDomain.CTP_CALLBACK, "OnFrontConnected"),
    ObservationKind.MARKET_SUBSCRIPTION_ACK: (
        EvidenceTrustDomain.CTP_CALLBACK,
        "OnRspSubMarketData",
    ),
    ObservationKind.MARKET_TICK: (
        EvidenceTrustDomain.CTP_CALLBACK,
        "OnRtnDepthMarketData",
    ),
    ObservationKind.ORDER_ADMISSION: (EvidenceTrustDomain.MANAGED_RUNTIME, ""),
    ObservationKind.ORDER_SUBMIT_RECEIPT: (EvidenceTrustDomain.MANAGED_RUNTIME, ""),
    ObservationKind.ORDER_ACCEPTED: (EvidenceTrustDomain.CTP_CALLBACK, "OnRtnOrder"),
    ObservationKind.ORDER_PARTIAL: (EvidenceTrustDomain.CTP_CALLBACK, "OnRtnOrder"),
    ObservationKind.ORDER_CANCELED: (EvidenceTrustDomain.CTP_CALLBACK, "OnRtnOrder"),
    ObservationKind.ORDER_FILLED: (EvidenceTrustDomain.CTP_CALLBACK, "OnRtnOrder"),
    ObservationKind.ORDER_REJECTED: (EvidenceTrustDomain.CTP_CALLBACK, "OnRspOrderInsert"),
    ObservationKind.TRADE_EXECUTION: (EvidenceTrustDomain.CTP_CALLBACK, "OnRtnTrade"),
    ObservationKind.ORDER_QUERY: (EvidenceTrustDomain.CTP_CALLBACK, "OnRspQryOrder"),
    ObservationKind.POSITION_QUERY: (EvidenceTrustDomain.CTP_CALLBACK, ""),
    ObservationKind.EXTERNAL_CONDITION: (EvidenceTrustDomain.CONTROL_PLANE, ""),
    ObservationKind.SYSTEM_LOG: (EvidenceTrustDomain.MANAGED_RUNTIME, ""),
    ObservationKind.MONITOR_CONFIGURATION: (EvidenceTrustDomain.MONITOR, ""),
    ObservationKind.MONITOR_LOG: (EvidenceTrustDomain.MONITOR, ""),
}


class ReadOnlyCaseStrategy:
    """Collect source-verified evidence and evaluate one bounded read-only case."""

    case_id = ""

    def __init__(
        self,
        plan: DescriptiveCasePlan,
        scope: DecisionScope,
        authenticator: Optional[ObservationAuthenticator],
    ) -> None:
        spec = READ_ONLY_CASE_SPECS.get(self.case_id)
        if spec is None or plan.case_id != self.case_id:
            raise ReadOnlyStrategyError("strategy case id does not match its static plan")
        scope.validate(plan)
        self.plan = plan
        self.scope = scope
        self.spec = spec
        self._authenticator = authenticator
        # C01 cannot be promoted by a caller-provided verifier. No code-owned
        # issuer-ledger verifier is installed in this candidate.
        self._c01_unverified_receipt = self.case_id == "C01"
        self._c01_receipt_ids = set()
        self._c01_request_ids = set()
        self._events: List[NativeObservation] = []
        self._event_ids = set()
        self._stream_state: Dict[
            Tuple[EvidenceTrustDomain, str, str, str], Tuple[int, datetime]
        ] = {}
        self._provider_scope: Optional[Tuple[str, str]] = None
        self._rejected: List[str] = []
        self._unavailable_conditions: List[str] = []

    def on_envelope(self, event: NativeObservation) -> bool:
        """Consume one normalized source envelope; never execute its contents."""

        if not isinstance(event, NativeObservation):
            raise ReadOnlyStrategyError("future adapter must provide a NativeObservation envelope")
        if not isinstance(event.fields, Mapping):
            raise ReadOnlyStrategyError("observation fields must be a mapping")
        field_snapshot = dict(event.fields)
        if any(
            not isinstance(name, str)
            or not isinstance(value, (str, bool, int, float, Decimal, type(None)))
            for name, value in field_snapshot.items()
        ):
            raise ReadOnlyStrategyError("observation fields must contain only scalar facts")
        event = NativeObservation(
            kind=event.kind,
            source_domain=event.source_domain,
            event_id=event.event_id,
            evidence_sha256=event.evidence_sha256,
            occurred_at_utc=event.occurred_at_utc,
            sequence=event.sequence,
            stream_id=event.stream_id,
            callback_name=event.callback_name,
            provider_session_id=event.provider_session_id,
            trading_day=event.trading_day,
            fields=MappingProxyType(field_snapshot),
            provider_front_id=event.provider_front_id,
            client_instance_id=event.client_instance_id,
            request_generation=event.request_generation,
            request_id_origin=event.request_id_origin,
            request_generation_origin=event.request_generation_origin,
            arrival_generation=event.arrival_generation,
            session_identity_origin=event.session_identity_origin,
            arrived_at_utc=event.arrived_at_utc,
            arrived_monotonic=event.arrived_monotonic,
            sequence_origin=event.sequence_origin,
            timestamp_origin=event.timestamp_origin,
            event_id_origin=event.event_id_origin,
            provider_issued_event_id=event.provider_issued_event_id,
            connection_generation_origin=event.connection_generation_origin,
            issued_request_receipt=event.issued_request_receipt,
        )
        self._validate_event(event)
        if event.event_id in self._event_ids:
            raise ReadOnlyStrategyError("duplicate source event id")
        if self._authenticator is None:
            self._rejected.append(f"{event.event_id}:trusted_authenticator_unavailable")
            return False
        receipt = self._authenticator.authenticate(event, self.scope)
        if not self._receipt_matches(receipt, event, self.scope):
            self._rejected.append(f"{event.event_id}:source_verification_denied")
            return False
        if self.case_id == "C01" and self._is_c01_request_callback(event):
            issued = event.issued_request_receipt
            if issued is not None:
                if issued.receipt_id in self._c01_receipt_ids:
                    raise ReadOnlyStrategyError("C01 request receipt cannot be replayed")
                native_id = event.fields.get("request_id")
                if native_id in self._c01_request_ids:
                    raise ReadOnlyStrategyError("C01 native RequestID cannot be reused")
                self._c01_receipt_ids.add(issued.receipt_id)
                self._c01_request_ids.add(native_id)

        occurred_at = _parse_utc(event.occurred_at_utc)
        key = (
            event.source_domain,
            event.stream_id,
            event.provider_session_id,
            event.trading_day,
        )
        previous = self._stream_state.get(key)
        if previous and (event.sequence <= previous[0] or occurred_at < previous[1]):
            raise ReadOnlyStrategyError("source sequence and time must increase per stream")
        sessionless_callback = event.kind in {
            ObservationKind.AUTH_SUCCESS, ObservationKind.FRONT_CONNECTED
        }
        if event.source_domain is EvidenceTrustDomain.CTP_CALLBACK and not sessionless_callback:
            observed_scope = (event.provider_session_id, event.trading_day)
            if self._provider_scope is not None and observed_scope != self._provider_scope:
                raise ReadOnlyStrategyError(
                    "case evidence cannot mix provider sessions or trading days"
                )
            self._provider_scope = observed_scope
        self._stream_state[key] = (event.sequence, occurred_at)
        self._event_ids.add(event.event_id)
        self._events.append(event)
        return True

    def evaluate(self, *, now_utc: Optional[datetime] = None) -> ReadOnlyCaseResult:
        """Return a review state against an explicitly injectable UTC clock.

        The five-minute order-evidence window is a conservative candidate
        policy, not an acceptance time source. It compares evidence to
        ``now_utc`` supplied by the managed caller (or the system clock when
        omitted); event timestamps never define the current time.
        """

        evaluation_time = now_utc or datetime.now(timezone.utc)
        if (
            not isinstance(evaluation_time, datetime)
            or evaluation_time.tzinfo is None
            or evaluation_time.utcoffset() != timedelta(0)
        ):
            raise ReadOnlyStrategyError("evaluation clock must be an aware UTC datetime")
        evaluation_time = evaluation_time.astimezone(timezone.utc)
        scenario = SCENARIOS_BY_CASE_ID[self.case_id]
        missing = self._missing_conditions(now_utc=evaluation_time)
        if self._authenticator is None or not self._events:
            state = ReadOnlyState.BLOCKED
        elif self._rejected or missing:
            state = ReadOnlyState.INCOMPLETE
        elif self._unavailable_conditions:
            state = ReadOnlyState.EXTERNAL_CONDITION_UNAVAILABLE
        else:
            state = ReadOnlyState.REVIEW_REQUIRED
        return ReadOnlyCaseResult(
            case_id=self.case_id,
            scenario_id=scenario.scenario_id,
            state=state,
            certification_pass=False,
            dispatch_permitted=False,
            source_authenticity_verified=False,
            evidence_event_ids=tuple(event.event_id for event in self._events),
            missing_conditions=tuple(missing),
            rejected_events=tuple(self._rejected),
            unavailable_conditions=tuple(self._unavailable_conditions),
        )

    def _validate_event(self, event: NativeObservation) -> None:
        if not isinstance(event.kind, ObservationKind):
            raise ReadOnlyStrategyError("observation kind must use the typed enum")
        if event.kind in {
            ObservationKind.AUTH_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.FRONT_DISCONNECTED,
        }:
            try:
                validate_payloadless_callback_fields(
                    event,
                    scope_account_identity_sha256=self.scope.account_identity_sha256,
                )
            except DecisionError as exc:
                raise ReadOnlyStrategyError(str(exc)) from exc
        if event.kind is ObservationKind.AUTH_SUCCESS and (
            event.provider_front_id is not None
            or event.provider_session_id
            or event.trading_day
            or any(
                event.fields.get(name) not in (None, "")
                for name in (
                    "provider_front_id", "provider_session_id", "trading_day",
                    "provider_timestamp_utc", "provider_sequence", "provider_event_id",
                    "source_sequence", "source_timestamp_utc"
                )
            )
        ):
            raise ReadOnlyStrategyError(
                "OnRspAuthenticate cannot claim provider front/session/day/time/sequence"
            )
        c01_account_query = self.case_id == "C01" and event.kind in {
            ObservationKind.ORDER_QUERY, ObservationKind.POSITION_QUERY
        }
        if event.kind not in self.spec.required_kinds and not c01_account_query:
            raise ReadOnlyStrategyError(
                f"{event.kind.value} is outside this case's read-only contract"
            )
        expected_domain, expected_callback = _SOURCE_POLICY[event.kind]
        if event.kind is ObservationKind.POSITION_QUERY:
            query_family = event.fields.get("query_family")
            expected_callback = {
                "positions": "OnRspQryInvestorPosition",
                "funds": "OnRspQryTradingAccount",
            }.get(query_family, "")
        if event.source_domain is not expected_domain or event.callback_name != expected_callback:
            raise ReadOnlyStrategyError(
                "source domain or native callback does not match event kind"
            )
        if (
            not isinstance(event.event_id, str)
            or not event.event_id
            or not isinstance(event.stream_id, str)
            or not event.stream_id
            or not isinstance(event.evidence_sha256, str)
            or not _SHA256_RE.fullmatch(event.evidence_sha256)
        ):
            raise ReadOnlyStrategyError("event id, stream id, and SHA-256 digest are required")
        if (
            not isinstance(event.sequence, int)
            or isinstance(event.sequence, bool)
            or event.sequence < 1
        ):
            raise ReadOnlyStrategyError("source sequence must be a positive integer")
        if _parse_utc(event.occurred_at_utc) is None:
            raise ReadOnlyStrategyError("event timestamp must be UTC")
        is_auth_callback = event.kind is ObservationKind.AUTH_SUCCESS
        is_payloadless_front = event.kind is ObservationKind.FRONT_CONNECTED
        if expected_domain is EvidenceTrustDomain.CTP_CALLBACK and not (
            is_auth_callback or is_payloadless_front
        ):
            if (
                not isinstance(event.provider_session_id, str)
                or not event.provider_session_id
                or not isinstance(event.trading_day, str)
                or not event.trading_day
            ):
                raise ReadOnlyStrategyError(
                    "native callback requires provider session and trading day"
                )
        elif expected_domain is not EvidenceTrustDomain.CTP_CALLBACK and event.callback_name:
            raise ReadOnlyStrategyError("managed/monitor events must not claim a native callback")
        if not isinstance(event.provider_session_id, str) or not isinstance(event.trading_day, str):
            raise ReadOnlyStrategyError("session and trading-day identifiers must be strings")

        fields = event.fields
        provider_identity_names = ("provider_front_id", "provider_session_id", "trading_day")
        if event.kind is ObservationKind.AUTH_SUCCESS:
            if (
                event.provider_front_id is not None
                or event.provider_session_id
                or event.trading_day
                or any(fields.get(name) not in (None, "") for name in provider_identity_names)
                or any(
                    fields.get(name) not in (None, "")
                    for name in (
                        "provider_timestamp_utc", "provider_sequence", "provider_event_id",
                        "source_sequence", "source_timestamp_utc"
                    )
                )
            ):
                raise ReadOnlyStrategyError(
                    "OnRspAuthenticate cannot claim provider front/session/day/time/sequence"
                )
        if event.kind is ObservationKind.FRONT_CONNECTED and (
            event.provider_front_id is not None
            or event.provider_session_id
            or event.trading_day
            or any(fields.get(name) not in (None, "") for name in provider_identity_names)
        ):
            raise ReadOnlyStrategyError(
                "OnFrontConnected has no native provider FrontID, SessionID, or TradingDay"
            )
        if event.kind is ObservationKind.FRONT_CONNECTED and (
            not event.client_instance_id
            or type(event.arrival_generation) is not int
            or event.arrival_generation < 1
            or fields.get("connection_generation") != event.arrival_generation
            or event.connection_generation_origin != "local_connection_generation"
        ):
            raise ReadOnlyStrategyError(
                "OnFrontConnected requires local client and connection-generation metadata"
            )
        if event.kind in {ObservationKind.AUTH_SUCCESS, ObservationKind.LOGIN_SUCCESS}:
            if fields.get("success") is not True or _integer(fields.get("error_id")) != 0:
                raise ReadOnlyStrategyError("authentication/login callback is not successful")
            self._validate_c01_auth_login_callback(event)
        elif event.kind is ObservationKind.FRONT_CONNECTED:
            if not fields.get("gateway_key"):
                raise ReadOnlyStrategyError("front connection requires gateway identity")
        elif event.kind is ObservationKind.MARKET_SUBSCRIPTION_ACK:
            if fields.get("success") is not True or not fields.get("instrument_id"):
                raise ReadOnlyStrategyError("market subscription is not provider-acknowledged")
        elif event.kind is ObservationKind.MARKET_TICK:
            tick_values = (
                _decimal(fields.get("bid")),
                _decimal(fields.get("ask")),
                _decimal(fields.get("last")),
                _decimal(fields.get("price_tick")),
            )
            if not fields.get("instrument_id") or any(value is None for value in tick_values):
                raise ReadOnlyStrategyError("market tick lacks typed price and instrument evidence")
            if tick_values[-1] <= 0:
                raise ReadOnlyStrategyError("market tick price increment must be positive")
        elif event.kind is ObservationKind.ORDER_ADMISSION:
            maximum = _decimal(fields.get("maximum_quantity"))
            expected_intent = {
                "open_cancel": "open",
                "close_position": "close",
                "cancel": "open",
                "batch_partials": "open",
                "batch_open": "open",
                "trade_log": "open",
            }[self.spec.order_profile]
            if (
                fields.get("case_id") != self.case_id
                or fields.get("intent_kind") != expected_intent
                or not fields.get("approval_ref")
                or maximum is None
                or maximum <= 0
            ):
                raise ReadOnlyStrategyError("order admission is not a bounded case-specific review")
        elif event.kind is ObservationKind.ORDER_SUBMIT_RECEIPT:
            required = (
                "request_id",
                "order_ref",
                "dispatch_state",
                "quantity",
                "instrument_id",
                "direction",
                "offset",
                "trace_id",
                "invocation_id",
            )
            quantity = _decimal(fields.get("quantity"))
            if any(not fields.get(name) for name in required) or quantity is None or quantity <= 0:
                raise ReadOnlyStrategyError("managed submit receipt lacks bounded order identity")
            if fields.get("action") != "submit" or fields.get("dispatch_state") not in {
                "dispatched",
                "blocked_pre_dispatch",
            }:
                raise ReadOnlyStrategyError("managed submit receipt has an unknown dispatch state")
            if fields.get("direction") not in {"buy", "sell"} or fields.get("offset") not in {
                "open",
                "close",
            }:
                raise ReadOnlyStrategyError("managed submit receipt has an unknown side/offset")
        elif event.kind in {
            ObservationKind.ORDER_ACCEPTED,
            ObservationKind.ORDER_PARTIAL,
            ObservationKind.ORDER_CANCELED,
            ObservationKind.ORDER_FILLED,
            ObservationKind.ORDER_REJECTED,
        }:
            self._validate_order_status(event)
        elif event.kind is ObservationKind.TRADE_EXECUTION:
            trade = event.fields
            if (
                not trade.get("trade_id")
                or not trade.get("order_ref")
                or not trade.get("external_order_id")
                or not trade.get("instrument_id")
                or trade.get("direction") not in {"buy", "sell"}
                or _decimal(trade.get("quantity")) is None
                or _decimal(trade.get("quantity")) <= 0
                or _decimal(trade.get("price")) is None
                or _decimal(trade.get("price")) <= 0
            ):
                raise ReadOnlyStrategyError("native trade callback lacks typed execution facts")
        elif event.kind is ObservationKind.ORDER_QUERY:
            if fields.get("query_family") != "orders":
                raise ReadOnlyStrategyError("order callback query family must be orders")
            self._validate_query_event(event, "orders")
            self._validate_c01_query_receipt(event)
        elif event.kind is ObservationKind.POSITION_QUERY:
            self._validate_query_event(event, str(fields.get("query_family", "")))
            self._validate_c01_query_receipt(event)
        elif event.kind is ObservationKind.EXTERNAL_CONDITION:
            required = ("condition_id", "state", "evidence_ref")
            if any(not fields.get(name) for name in required):
                raise ReadOnlyStrategyError("external condition receipt lacks identity")
            if fields.get("state") not in {"satisfied", "unavailable"}:
                raise ReadOnlyStrategyError(
                    "external condition state must be satisfied/unavailable"
                )
            if fields.get("state") == "unavailable" and not fields.get("reason"):
                raise ReadOnlyStrategyError("unavailable external condition requires a reason")
        elif event.kind is ObservationKind.SYSTEM_LOG:
            required = ("trace_id", "gateway_key", "log_digest", "event_name", "session_id")
            if any(not fields.get(name) for name in required):
                raise ReadOnlyStrategyError(
                    "system lifecycle log lacks required identity/evidence fields"
                )
            if not _SHA256_RE.fullmatch(str(fields.get("log_digest"))):
                raise ReadOnlyStrategyError("system log digest must be SHA-256")
            if (
                self.spec.requires_process_identity
                and fields.get("event_name")
                in {
                    "session_started",
                    "session_stopped",
                }
                and not fields.get("process_id")
            ):
                raise ReadOnlyStrategyError("system lifecycle log lacks process identity")
            if self.case_id == "C01" and fields.get("event_name") in {
                "store_auth_success",
                "store_login_success",
            }:
                local_fields = (
                    "callback_event_id",
                    "callback_received_at_utc",
                    "client_instance_id",
                    "arrival_generation",
                )
                if any(not fields.get(name) for name in local_fields):
                    raise ReadOnlyStrategyError(
                        "authentication system log lacks local callback correlation"
                    )
                if _parse_utc(str(fields.get("callback_received_at_utc"))) is None:
                    raise ReadOnlyStrategyError("local callback receive timestamp must be UTC")
                if fields.get("provider_issued_event_id") is not False:
                    raise ReadOnlyStrategyError("callback event id must be marked local")
                if fields.get("event_name") == "store_auth_success" and any(
                    fields.get(name) not in (None, "")
                    for name in (
                        "provider_session_id",
                        "trading_day",
                        "provider_timestamp_utc",
                        "provider_front_id",
                    )
                ):
                    raise ReadOnlyStrategyError(
                        "authentication log claims unavailable native provider identity"
                    )
            if self.spec.order_profile and fields.get("event_name") == "order_cancel_request":
                required_cancel = (
                    "request_id",
                    "invocation_id",
                    "order_ref",
                    "dispatch_state",
                )
                if any(not fields.get(name) for name in required_cancel):
                    raise ReadOnlyStrategyError("managed cancel receipt lacks request correlation")
                if fields.get("dispatch_state") not in {"dispatched", "blocked_pre_dispatch"}:
                    raise ReadOnlyStrategyError(
                        "managed cancel receipt has an unknown dispatch state"
                    )
            if self.spec.order_profile and fields.get("event_name") == "batch_cancel_requested":
                required_batch = (
                    "request_id",
                    "invocation_id",
                    "order_refs_json",
                    "dispatch_state",
                )
                if any(not fields.get(name) for name in required_batch):
                    raise ReadOnlyStrategyError("managed batch cancel receipt lacks correlation")
                refs = _json_load(fields.get("order_refs_json"), "batch cancel order refs")
                if not isinstance(refs, list) or any(
                    not isinstance(ref, str) or not ref for ref in refs
                ):
                    raise ReadOnlyStrategyError("batch cancel receipt requires a typed ref list")
                if fields.get("dispatch_state") not in {"dispatched", "blocked_pre_dispatch"}:
                    raise ReadOnlyStrategyError(
                        "managed batch cancel has an unknown dispatch state"
                    )
        elif event.kind is ObservationKind.MONITOR_CONFIGURATION:
            required = ("metric", "threshold", "configuration_digest", "monitor_digest")
            if any(fields.get(name) in (None, "") for name in required):
                raise ReadOnlyStrategyError("monitor configuration lacks threshold provenance")
            if not _SHA256_RE.fullmatch(
                str(fields.get("configuration_digest"))
            ) or not _SHA256_RE.fullmatch(str(fields.get("monitor_digest"))):
                raise ReadOnlyStrategyError("monitor configuration digests must be SHA-256")
        elif event.kind is ObservationKind.MONITOR_LOG:
            required = ("trace_id", "metric", "monitor_digest", "event_name")
            if any(not fields.get(name) for name in required):
                raise ReadOnlyStrategyError("monitor log lacks event identity or digest")
            if not _SHA256_RE.fullmatch(str(fields.get("monitor_digest"))):
                raise ReadOnlyStrategyError("monitor log digest must be SHA-256")

    @staticmethod
    def _validate_order_status(event: NativeObservation) -> None:
        fields = event.fields
        expected_status = {
            ObservationKind.ORDER_ACCEPTED: {"accepted", "working"},
            ObservationKind.ORDER_PARTIAL: {"partial"},
            ObservationKind.ORDER_CANCELED: {"canceled", "cancelled"},
            ObservationKind.ORDER_FILLED: {"filled"},
            ObservationKind.ORDER_REJECTED: {"rejected"},
        }[event.kind]
        if (
            not fields.get("order_ref")
            or not fields.get("instrument_id")
            or fields.get("status") not in expected_status
        ):
            raise ReadOnlyStrategyError(
                "native order callback identity/status does not match its fact"
            )
        if event.kind is not ObservationKind.ORDER_REJECTED and not fields.get("external_order_id"):
            raise ReadOnlyStrategyError("native order callback requires exchange order identity")
        traded = _decimal(fields.get("traded_quantity"))
        remaining = _decimal(fields.get("remaining_quantity"))
        if traded is None or remaining is None or traded < 0 or remaining < 0:
            raise ReadOnlyStrategyError("native order quantities must be finite and non-negative")
        if event.kind is ObservationKind.ORDER_ACCEPTED and remaining <= 0:
            raise ReadOnlyStrategyError("accepted order must still have remaining quantity")
        if event.kind is ObservationKind.ORDER_PARTIAL and (traded <= 0 or remaining <= 0):
            raise ReadOnlyStrategyError("partial order must show traded and remaining quantity")
        if (
            event.kind in {ObservationKind.ORDER_CANCELED, ObservationKind.ORDER_FILLED}
            and remaining
        ):
            raise ReadOnlyStrategyError("terminal native order callback must have zero remainder")
        if event.kind is ObservationKind.ORDER_REJECTED and _integer(fields.get("error_id")) in {
            None,
            0,
        }:
            raise ReadOnlyStrategyError("provider rejection requires a nonzero ErrorID")

    def _validate_c01_auth_login_callback(self, event: NativeObservation) -> None:
        """Validate native CTP callback facts separately from local arrival facts."""

        if self.case_id != "C01":
            return
        fields = event.fields
        is_auth = event.kind is ObservationKind.AUTH_SUCCESS
        request_id = fields.get("request_id")
        error_id = fields.get("error_id")
        if type(request_id) is not int or request_id <= 0:
            raise ReadOnlyStrategyError("CTP callback requires its native positive request_id")
        if (
            type(fields.get("request_generation")) is not int
            or fields.get("request_generation") != event.request_generation
            or type(fields.get("arrival_generation")) is not int
            or fields.get("arrival_generation") != event.arrival_generation
        ):
            raise ReadOnlyStrategyError("CTP callback local generation bindings do not match")
        if type(error_id) is not int or error_id != 0 or fields.get("is_last") is not True:
            raise ReadOnlyStrategyError("CTP callback ErrorID/IsLast facts are invalid")
        if (
            not isinstance(event.client_instance_id, str)
            or not event.client_instance_id
            or type(event.request_generation) is not int
            or event.request_generation < 1
            or event.request_id_origin != "native_callback_argument"
            or event.request_generation_origin != "local_request_generation_binding"
            or type(event.arrival_generation) is not int
            or event.arrival_generation < 1
            or event.sequence_origin != "local_sdk_callback_arrival"
            or event.timestamp_origin != "local_sdk_capture_clock"
            or event.event_id_origin != "local_sdk_callback_arrival"
            or event.provider_issued_event_id is not False
            or type(event.sequence) is not int
            or event.sequence < 1
            or _parse_utc(event.arrived_at_utc) is None
            or _parse_utc(event.arrived_at_utc) != _parse_utc(event.occurred_at_utc)
            or isinstance(event.arrived_monotonic, bool)
            or not isinstance(event.arrived_monotonic, (int, float))
            or event.arrived_monotonic <= 0
        ):
            raise ReadOnlyStrategyError("CTP callback lacks correctly attributed local arrival metadata")
        receipt = event.issued_request_receipt
        if receipt is not None and not validate_issued_request_receipt(
            receipt,
            request_kind="authenticate" if is_auth else "login",
            phase="",
            request_id=request_id,
            request_generation=event.request_generation,
            client_instance_id=event.client_instance_id,
            arrival_generation=event.arrival_generation,
            arrived_at_utc=event.arrived_at_utc,
            arrived_monotonic=event.arrived_monotonic,
        ):
            raise ReadOnlyStrategyError("C01 auth/login receipt does not match native callback")

        provider_only_fields = (
            "provider_timestamp_utc",
            "provider_sequence",
            "provider_event_id",
            "source_sequence",
            "source_timestamp_utc",
        )
        if any(fields.get(name) not in (None, "") for name in provider_only_fields):
            raise ReadOnlyStrategyError(
                "auth/login callback cannot claim provider time, sequence, or event ID"
            )
        if is_auth:
            if (
                event.provider_front_id is not None
                or event.provider_session_id != ""
                or event.trading_day != ""
                or event.session_identity_origin
                != "unavailable_on_native_authentication_response"
                or any(fields.get(name) not in (None, "") for name in provider_only_fields)
                or any(
                    fields.get(name) not in (None, "")
                    for name in (
                        "provider_front_id",
                        "provider_session_id",
                        "trading_day",
                    )
                )
            ):
                raise ReadOnlyStrategyError(
                    "OnRspAuthenticate cannot claim provider front/session/day/time/sequence"
                )
            return

        front_id = fields.get("provider_front_id")
        session_id = fields.get("provider_session_id")
        trading_day = fields.get("trading_day")
        if (
            event.session_identity_origin != "native_login_response_fields"
            or type(front_id) is not int
            or front_id <= 0
            or not isinstance(session_id, str)
            or not session_id.isdigit()
            or not isinstance(trading_day, str)
            or not re.fullmatch(r"\d{8}", trading_day)
            or event.provider_front_id != front_id
            or event.provider_session_id != session_id
            or event.trading_day != trading_day
            or any(fields.get(name) not in (None, "") for name in provider_only_fields)
        ):
            raise ReadOnlyStrategyError(
                "OnRspUserLogin requires native FrontID/SessionID/TradingDay fields"
            )

    @staticmethod
    def _is_c01_request_callback(event: NativeObservation) -> bool:
        return event.kind in {
            ObservationKind.AUTH_SUCCESS,
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.ORDER_QUERY,
            ObservationKind.POSITION_QUERY,
        }

    def _validate_c01_query_receipt(self, event: NativeObservation) -> None:
        if self.case_id != "C01":
            return
        fields = event.fields
        family = str(fields.get("query_family", ""))
        if family not in {"orders", "positions", "funds"}:
            raise ReadOnlyStrategyError("C01 query callback family is invalid")
        if (
            not fields.get("query_round_id")
            or fields.get("query_round_id_origin") != "local_query_coordinator"
            or not fields.get("query_id")
            or fields.get("query_id_origin") != "local_query_coordinator"
        ):
            raise ReadOnlyStrategyError("C01 query callback needs local query coordinator IDs")
        if (
            type(fields.get("request_id")) is not int
            or fields.get("request_id") <= 0
            or type(fields.get("error_id")) is not int
            or fields.get("error_id") != 0
            or type(fields.get("is_last")) is not bool
            or fields.get("is_last") is not True
            or type(event.request_generation) is not int
            or event.request_generation < 1
            or fields.get("request_generation") != event.request_generation
            or event.request_generation_origin != "local_request_generation_binding"
            or fields.get("arrival_generation") != event.arrival_generation
            or event.request_id_origin != "native_callback_argument"
            or type(event.arrival_generation) is not int
            or event.arrival_generation < 1
            or event.sequence_origin != "local_sdk_callback_arrival"
            or event.timestamp_origin != "local_sdk_capture_clock"
            or event.event_id_origin != "local_sdk_callback_arrival"
            or event.provider_issued_event_id is not False
            or _parse_utc(event.arrived_at_utc) is None
            or _parse_utc(event.arrived_at_utc) != _parse_utc(event.occurred_at_utc)
            or isinstance(event.arrived_monotonic, bool)
            or not isinstance(event.arrived_monotonic, (int, float))
            or event.arrived_monotonic <= 0
        ):
            raise ReadOnlyStrategyError("C01 query callback native/local facts are malformed")
        if (
            event.provider_front_id is not None
            or any(
                fields.get(name) not in (None, "")
                for name in (
                    "provider_front_id", "provider_session_id", "trading_day",
                    "provider_timestamp_utc", "provider_sequence", "provider_event_id",
                    "source_sequence", "source_timestamp_utc", "provider_query_id"
                )
            )
            or event.session_identity_origin
            != "derived_from_same_client_generation_native_login"
        ):
            raise ReadOnlyStrategyError(
                "C01 query callback cannot claim provider query/time metadata; scope is login-derived"
            )
        receipt = event.issued_request_receipt
        if receipt is not None and not validate_issued_request_receipt(
            receipt,
            request_kind=family,
            phase=str(fields.get("phase", "")),
            request_id=fields.get("request_id"),
            request_generation=event.request_generation,
            client_instance_id=event.client_instance_id,
            arrival_generation=event.arrival_generation,
            arrived_at_utc=event.arrived_at_utc,
            arrived_monotonic=event.arrived_monotonic,
        ):
            raise ReadOnlyStrategyError("C01 query receipt does not match native callback")

    @staticmethod
    def _validate_query_event(event: NativeObservation, query_family: str) -> None:
        fields = event.fields
        if query_family not in {"orders", "positions", "funds"}:
            raise ReadOnlyStrategyError("native query family is not recognized")
        if (
            fields.get("phase") not in {"baseline", "final"}
            or not fields.get("snapshot_id")
            or not fields.get("query_id")
            or fields.get("complete") is not True
            or fields.get("is_last") is not True
            or _integer(fields.get("error_id")) != 0
        ):
            raise ReadOnlyStrategyError("native account query must be complete and error-free")
        if query_family == "orders":
            value = _json_load(fields.get("open_order_refs_json"), "open order refs")
            if not isinstance(value, list) or any(
                not isinstance(item, str) or not item for item in value
            ):
                raise ReadOnlyStrategyError("order query must contain a typed open-reference list")
        elif query_family == "positions":
            _json_decimal_map(fields.get("positions_json"), "position snapshot")
            _json_decimal_map(fields.get("closeable_quantities_json"), "closeable snapshot")
        else:
            funds = _json_decimal_map(fields.get("funds_json"), "funds snapshot")
            if set(funds) != {"cash", "available_funds", "equity"}:
                raise ReadOnlyStrategyError(
                    "account query requires cash, available funds, and equity"
                )

    @staticmethod
    def _receipt_matches(
        receipt: Optional[AuthenticationReceipt],
        event: NativeObservation,
        scope: DecisionScope,
    ) -> bool:
        return bool(
            isinstance(receipt, AuthenticationReceipt)
            and isinstance(receipt.event_id, str)
            and isinstance(receipt.evidence_sha256, str)
            and isinstance(receipt.scope_sha256, str)
            and isinstance(receipt.account_identity_sha256, str)
            and isinstance(receipt.verification_ref, str)
            and receipt.event_id == event.event_id
            and receipt.evidence_sha256.lower() == event.evidence_sha256.lower()
            and receipt.scope_sha256.lower() == scope.scope_sha256.lower()
            and receipt.account_identity_sha256.lower() == scope.account_identity_sha256.lower()
            and receipt.trust_domain is event.source_domain
            and receipt.verification_ref.strip()
        )

    def _missing_conditions(self, *, now_utc: datetime) -> List[str]:
        if self.spec.order_profile:
            return self._missing_order_conditions(now_utc=now_utc)
        by_kind = {
            kind: [item for item in self._events if item.kind is kind]
            for kind in self.spec.required_kinds
        }
        missing = [kind.value for kind, events in by_kind.items() if not events]
        if missing:
            return missing
        for kind, events in by_kind.items():
            if kind not in {
                ObservationKind.SYSTEM_LOG, ObservationKind.ORDER_QUERY, ObservationKind.POSITION_QUERY
            } and len(events) != 1:
                missing.append(f"exactly_one_observation_required:{kind.value}")
        provider_events = [
            event
            for event in self._events
            if event.source_domain is EvidenceTrustDomain.CTP_CALLBACK
        ]
        provider_session = self._provider_scope[0] if self._provider_scope else ""
        latest_provider_time = max(_parse_utc(event.occurred_at_utc) for event in provider_events)

        if self.case_id == "C01":
            auth = self._one(ObservationKind.AUTH_SUCCESS)
            login = self._one(ObservationKind.LOGIN_SUCCESS)
            if auth.client_instance_id != login.client_instance_id:
                missing.append("authentication_and_login_must_use_same_client_instance")
            if auth.arrival_generation != login.arrival_generation:
                missing.append("authentication_and_login_must_share_connection_generation")
            if auth.request_generation == login.request_generation:
                missing.append("authentication_and_login_request_generations_must_differ")
            auth_request_id = auth.fields.get("request_id")
            login_request_id = login.fields.get("request_id")
            if (
                type(auth_request_id) is not int
                or type(login_request_id) is not int
                or auth_request_id == login_request_id
            ):
                missing.append("authentication_and_login_native_request_ids_must_differ")
            if self._c01_unverified_receipt:
                missing.append("trusted_c01_issued_request_ledger_verifier_required")
            required_queries = {
                (phase, family)
                for phase in ("baseline", "final")
                for family in ("orders", "positions", "funds")
            }
            query_rows = [
                event
                for event in self._events
                if event.kind in {ObservationKind.ORDER_QUERY, ObservationKind.POSITION_QUERY}
            ]
            observed_queries = {
                (str(event.fields.get("phase")), str(event.fields.get("query_family")))
                for event in query_rows
            }
            if len(query_rows) != 6 or observed_queries != required_queries:
                missing.append("c01_requires_baseline_and_final_native_order_position_account_queries")
            for phase in ("baseline", "final"):
                phase_rows = [event for event in query_rows if event.fields.get("phase") == phase]
                if len(phase_rows) == 3 and (
                    len({event.fields.get("query_round_id") for event in phase_rows}) != 1
                    or len({event.fields.get("snapshot_id") for event in phase_rows}) != 1
                ):
                    missing.append(f"c01_{phase}_queries_must_share_local_round_and_snapshot")
            query_ids = [event.fields.get("request_id") for event in query_rows]
            if (
                len(query_ids) != 6
                or any(type(item) is not int or item <= 0 for item in query_ids)
                or len(set(query_ids)) != 6
            ):
                missing.append("c01_query_callbacks_require_six_distinct_native_request_ids")
            if any(
                event.issued_request_receipt is None
                or not validate_issued_request_receipt(
                    event.issued_request_receipt,
                    request_kind=str(event.fields.get("query_family", "")),
                    phase=str(event.fields.get("phase", "")),
                    request_id=event.fields.get("request_id"),
                    request_generation=event.request_generation,
                    client_instance_id=event.client_instance_id,
                    arrival_generation=event.arrival_generation,
                    arrived_at_utc=event.arrived_at_utc,
                    arrived_monotonic=event.arrived_monotonic,
                )
                for event in query_rows
            ):
                missing.append("c01_query_callbacks_require_matching_typed_issued_request_receipts")
            for query in query_rows:
                if (
                    query.client_instance_id != login.client_instance_id
                    or query.arrival_generation != login.arrival_generation
                    or query.provider_session_id != login.provider_session_id
                    or query.trading_day != login.trading_day
                    or query.sequence <= login.sequence
                ):
                    missing.append("c01_query_callbacks_must_follow_native_login_same_client_generation")
                    break
            if (
                auth.sequence >= login.sequence
                or _parse_utc(auth.arrived_at_utc) >= _parse_utc(login.arrived_at_utc)
                or _parse_utc(auth.occurred_at_utc) >= _parse_utc(login.occurred_at_utc)
            ):
                missing.append("authentication_must_precede_login")
        else:
            front = self._one(ObservationKind.FRONT_CONNECTED)
            login = self._one(ObservationKind.LOGIN_SUCCESS)
            subscribed = self._one(ObservationKind.MARKET_SUBSCRIPTION_ACK)
            if not (
                _parse_utc(front.occurred_at_utc)
                <= _parse_utc(login.occurred_at_utc)
                <= _parse_utc(subscribed.occurred_at_utc)
            ):
                missing.append("front_login_market_ack_order_invalid")
            if self.spec.expected_metric:
                tick = self._one(ObservationKind.MARKET_TICK)
                if _parse_utc(tick.occurred_at_utc) < _parse_utc(
                    subscribed.occurred_at_utc
                ) or tick.fields.get("instrument_id") != subscribed.fields.get("instrument_id"):
                    missing.append("threshold_case_requires_subscribed_instrument_market_tick")

        system_rows = by_kind.get(ObservationKind.SYSTEM_LOG, [])
        for row in system_rows:
            if self.case_id != "C01" and row.fields.get("session_id") != provider_session:
                missing.append("system_log_provider_session_mismatch")
        system_gateway_keys = {str(row.fields.get("gateway_key", "")) for row in system_rows}
        provider_gateway_keys = {
            str(event.fields.get("gateway_key", ""))
            for event in provider_events
            if event.kind is ObservationKind.FRONT_CONNECTED
        }
        if len(system_gateway_keys) > 1 or (
            provider_gateway_keys and system_gateway_keys != provider_gateway_keys
        ):
            missing.append("system_logs_must_match_provider_gateway_identity")
        system_by_name: Dict[str, NativeObservation] = {}
        for row in system_rows:
            event_name = str(row.fields.get("event_name", ""))
            if event_name in system_by_name:
                missing.append(f"duplicate_lifecycle_event:{event_name}")
            system_by_name[event_name] = row
        required_system_events = ["session_stopped", "write_activity_summary"]
        if self.case_id == "C01":
            required_system_events.extend(("store_auth_success", "store_login_success"))
        if self.spec.requires_start_log:
            required_system_events.insert(0, "session_started")
        if self.spec.requires_store_ready:
            required_system_events.append("store_ready")
        if self.spec.requires_store_connected:
            required_system_events.append("store_connected")
        for event_name in required_system_events:
            if event_name not in system_by_name:
                missing.append(f"system_log:{event_name}")

        if self.case_id == "C01":
            auth = self._one(ObservationKind.AUTH_SUCCESS)
            login = self._one(ObservationKind.LOGIN_SUCCESS)
            auth_log = system_by_name.get("store_auth_success")
            login_log = system_by_name.get("store_login_success")
            for log, callback_event, missing_key in (
                (auth_log, auth, "authentication"),
                (login_log, login, "login"),
            ):
                if log is None:
                    continue
                if log.fields.get("callback_event_id") != callback_event.event_id:
                    missing.append(f"{missing_key}_log_must_reference_native_callback")
                if (
                    _parse_utc(str(log.fields.get("callback_received_at_utc", "")))
                    != _parse_utc(callback_event.arrived_at_utc)
                    or log.fields.get("client_instance_id")
                    != callback_event.client_instance_id
                    or log.fields.get("arrival_generation")
                    != callback_event.arrival_generation
                    or log.fields.get("provider_issued_event_id") is not False
                ):
                    missing.append("authentication_logs_must_bind_local_callback_arrival")
            if (
                login_log
                and (
                    login_log.fields.get("provider_front_id") != login.provider_front_id
                    or login_log.fields.get("provider_session_id")
                    != login.provider_session_id
                    or login_log.fields.get("trading_day") != login.trading_day
                )
            ):
                missing.append("login_log_must_match_native_login_identity")
            if auth_log and any(
                auth_log.fields.get(name) not in (None, "")
                for name in (
                    "provider_front_id",
                    "provider_session_id",
                    "trading_day",
                    "provider_timestamp_utc",
                    "provider_sequence",
                )
            ):
                missing.append("authentication_log_must_not_claim_unavailable_provider_identity")
            if (
                auth_log
                and login_log
                and _parse_utc(auth_log.occurred_at_utc) >= _parse_utc(login_log.occurred_at_utc)
            ):
                missing.append("authentication_log_must_precede_login_log")
        stopped = system_by_name.get("session_stopped")
        if stopped:
            fields = stopped.fields
            if (
                fields.get("clean_shutdown") is not True
                or fields.get("gateway_released") is not True
                or _integer(fields.get("exit_code")) != 0
            ):
                missing.append("clean_gateway_release_and_zero_exit_required")
            if _parse_utc(stopped.occurred_at_utc) < latest_provider_time:
                missing.append("session_shutdown_must_follow_provider_evidence")

        write_summary = system_by_name.get("write_activity_summary")
        if write_summary:
            fields = write_summary.fields
            counts = ("order_submit_count", "order_cancel_count", "broker_write_count")
            if (
                fields.get("snapshot_complete") is not True
                or not _SHA256_RE.fullmatch(str(fields.get("snapshot_digest", "")))
                or any(_integer(fields.get(name)) != 0 for name in counts)
            ):
                missing.append("complete_zero_order_cancel_and_broker_write_summary_required")
            if self.case_id != "C01" and fields.get("session_id") != provider_session:
                missing.append("write_activity_session_mismatch")
            if stopped and _parse_utc(write_summary.occurred_at_utc) < _parse_utc(
                stopped.occurred_at_utc
            ):
                missing.append("write_activity_summary_must_follow_session_shutdown")

        if self.spec.requires_start_log:
            started = system_by_name.get("session_started")
            if started and _parse_utc(started.occurred_at_utc) > min(
                _parse_utc(event.occurred_at_utc) for event in provider_events
            ):
                missing.append("session_start_log_must_precede_provider_session")
        if self.spec.requires_store_ready:
            ready = system_by_name.get("store_ready")
            if ready:
                if (
                    ready.fields.get("market_connection") is not True
                    or ready.fields.get("trade_connection") is not True
                    or ready.fields.get("session_id") != provider_session
                ):
                    missing.append("store_ready_log_must_confirm_both_provider_fronts")
                if _parse_utc(ready.occurred_at_utc) < max(
                    _parse_utc(event.occurred_at_utc)
                    for event in provider_events
                    if event.kind is not ObservationKind.AUTH_SUCCESS
                ):
                    missing.append("store_ready_log_must_follow_provider_readiness")
                connected = system_by_name.get("store_connected")
                if connected and _parse_utc(ready.occurred_at_utc) < _parse_utc(
                    connected.occurred_at_utc
                ):
                    missing.append("store_ready_log_must_follow_store_connected")
        if self.spec.requires_store_connected:
            connected = system_by_name.get("store_connected")
            if connected:
                if (
                    connected.fields.get("market_connection") is not True
                    or connected.fields.get("trade_connection") is not True
                    or connected.fields.get("session_id") != provider_session
                ):
                    missing.append("store_connected_log_must_confirm_both_provider_fronts")
                ready_events = [
                    event
                    for event in provider_events
                    if event.kind
                    in {
                        ObservationKind.FRONT_CONNECTED,
                        ObservationKind.LOGIN_SUCCESS,
                        ObservationKind.MARKET_SUBSCRIPTION_ACK,
                    }
                ]
                if ready_events and _parse_utc(connected.occurred_at_utc) < max(
                    _parse_utc(event.occurred_at_utc) for event in ready_events
                ):
                    missing.append("store_connected_log_must_follow_provider_readiness")

        if self.spec.expected_metric:
            self._check_threshold(by_kind, missing)
            started = system_by_name.get("session_started")
            stopped = system_by_name.get("session_stopped")
            if started and stopped:
                for kind in (
                    ObservationKind.MONITOR_CONFIGURATION,
                    ObservationKind.MONITOR_LOG,
                ):
                    for event in by_kind.get(kind, []):
                        if not (
                            _parse_utc(started.occurred_at_utc)
                            <= _parse_utc(event.occurred_at_utc)
                            <= _parse_utc(stopped.occurred_at_utc)
                        ):
                            missing.append("monitor_evidence_must_be_within_runtime_session")
        if self.spec.requires_process_identity:
            started = system_by_name.get("session_started")
            stopped = system_by_name.get("session_stopped")
            if (
                started
                and stopped
                and started.fields.get("process_id") != stopped.fields.get("process_id")
            ):
                missing.append("session_start_and_stop_must_match_process_identity")
        return list(dict.fromkeys(missing))

    def _missing_order_conditions(self, *, now_utc: datetime) -> List[str]:
        self._unavailable_conditions = []
        event_times = [_parse_utc(event.occurred_at_utc) for event in self._events]
        if any(
            occurred_at is None
            or now_utc - occurred_at > _MAX_CANDIDATE_EVIDENCE_AGE
            or occurred_at - now_utc > _MAX_CANDIDATE_FUTURE_SKEW
            for occurred_at in event_times
        ):
            return ["evidence_outside_candidate_freshness_window"]

        unavailable = [
            event
            for event in self._events
            if event.kind is ObservationKind.EXTERNAL_CONDITION
            and event.fields.get("state") == "unavailable"
        ]
        submitted_events = [
            event for event in self._events if event.kind is ObservationKind.ORDER_SUBMIT_RECEIPT
        ]
        allowed_unavailable = {
            "close_position": {"closeable_position_confirmed"},
            "cancel": {"cancel_window_available"},
            "batch_partials": {
                "provider_partial_fill_opportunity",
                "provider_batch_cancel_capability",
            },
            "batch_open": {"multiple_open_orders_available", "provider_batch_cancel_capability"},
        }.get(self.spec.order_profile, set())
        if unavailable and not submitted_events:
            for event in unavailable:
                condition_id = str(event.fields.get("condition_id", ""))
                if condition_id not in allowed_unavailable:
                    return [f"unexpected_unavailable_external_condition:{condition_id}"]
            self._unavailable_conditions.extend(
                f"{event.fields['condition_id']}:{event.fields['reason']}" for event in unavailable
            )
            return []

        missing: List[str] = []
        if unavailable:
            missing.append("external_condition_unavailable_after_order_activity")
        events_by_kind = {
            kind: [event for event in self._events if event.kind is kind]
            for kind in self.spec.required_kinds
        }
        required_singletons = (
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.MARKET_SUBSCRIPTION_ACK,
            ObservationKind.MARKET_TICK,
            ObservationKind.ORDER_ADMISSION,
        )
        for kind in required_singletons:
            if len(events_by_kind[kind]) != 1:
                missing.append(f"exactly_one_{kind.value}_required")
        if not submitted_events:
            missing.append("managed_submit_receipt_required")

        account_fingerprint = self.scope.account_identity_sha256
        if not _SHA256_RE.fullmatch(account_fingerprint):
            missing.append("sealed_account_identity_fingerprint_required")
        account_bound_events = list(submitted_events)
        account_bound_events.extend(
            event
            for event in self._events
            if event.kind in {ObservationKind.ORDER_QUERY, ObservationKind.POSITION_QUERY}
        )
        for event in account_bound_events:
            # Raw account IDs are deliberately not an identity authority.
            # Only a SHA-256 fingerprint bound into DecisionScope/auth receipts
            # can correlate managed submits and provider account queries.
            event_fingerprint = event.fields.get("account_identity_sha256")
            if (
                not isinstance(event_fingerprint, str)
                or not account_fingerprint
                or event_fingerprint.lower() != account_fingerprint.lower()
            ):
                missing.append("account_identity_scope_mismatch")
                break

        minimum_orders = 2 if self.spec.order_profile in {"batch_partials", "batch_open"} else 1
        if len(submitted_events) < minimum_orders:
            missing.append(f"minimum_managed_order_receipts:{minimum_orders}")
        if (
            self.spec.order_profile in {"open_cancel", "close_position", "cancel", "trade_log"}
            and len(submitted_events) != 1
        ):
            missing.append("single_order_scenario_requires_exactly_one_submit")

        provider_events = [
            event
            for event in self._events
            if event.source_domain is EvidenceTrustDomain.CTP_CALLBACK
        ]
        if provider_events:
            if len({event.stream_id for event in provider_events}) != 1:
                missing.append("native_order_workflow_requires_one_case_event_stream")
            sequences = [event.sequence for event in provider_events]
            if len(sequences) != len(set(sequences)):
                missing.append("native_order_workflow_requires_unique_source_sequences")
            ordered_provider_events = sorted(provider_events, key=lambda item: item.sequence)
            if any(
                _parse_utc(later.occurred_at_utc) < _parse_utc(earlier.occurred_at_utc)
                for earlier, later in zip(ordered_provider_events, ordered_provider_events[1:])
            ):
                missing.append("native_order_workflow_source_time_moved_backwards")

        front = (
            self._one(ObservationKind.FRONT_CONNECTED)
            if events_by_kind[ObservationKind.FRONT_CONNECTED]
            else None
        )
        login = (
            self._one(ObservationKind.LOGIN_SUCCESS)
            if events_by_kind[ObservationKind.LOGIN_SUCCESS]
            else None
        )
        subscription = (
            self._one(ObservationKind.MARKET_SUBSCRIPTION_ACK)
            if events_by_kind[ObservationKind.MARKET_SUBSCRIPTION_ACK]
            else None
        )
        tick = (
            self._one(ObservationKind.MARKET_TICK)
            if events_by_kind[ObservationKind.MARKET_TICK]
            else None
        )
        if front and login and subscription and tick:
            times = [
                _parse_utc(event.occurred_at_utc) for event in (front, login, subscription, tick)
            ]
            if times != sorted(times):
                missing.append("provider_front_login_subscription_tick_order_invalid")
            if tick.fields.get("instrument_id") != subscription.fields.get("instrument_id"):
                missing.append("market_tick_must_match_subscribed_instrument")

        submit_by_ref = {
            str(event.fields.get("order_ref", "")): event for event in submitted_events
        }
        subscribed_instrument = (
            str(subscription.fields.get("instrument_id", "")) if subscription is not None else ""
        )
        market_instrument = str(tick.fields.get("instrument_id", "")) if tick is not None else ""
        for submit in submitted_events:
            instrument = str(submit.fields.get("instrument_id", ""))
            if subscribed_instrument and instrument != subscribed_instrument:
                missing.append("managed_submit_instrument_must_match_market_subscription")
            if market_instrument and instrument != market_instrument:
                missing.append("managed_submit_instrument_must_match_market_tick")
        native_order_kinds = {
            ObservationKind.ORDER_ACCEPTED,
            ObservationKind.ORDER_PARTIAL,
            ObservationKind.ORDER_CANCELED,
            ObservationKind.ORDER_FILLED,
            ObservationKind.ORDER_REJECTED,
            ObservationKind.TRADE_EXECUTION,
        }
        for event in self._events:
            if event.kind not in native_order_kinds:
                continue
            order_ref = str(event.fields.get("order_ref", ""))
            submit = submit_by_ref.get(order_ref)
            if submit is None:
                missing.append("native_order_fact_must_match_managed_submit")
            elif event.fields.get("instrument_id") != submit.fields.get("instrument_id"):
                missing.append("native_order_fact_instrument_must_match_managed_submit")

        admission = (
            self._one(ObservationKind.ORDER_ADMISSION)
            if events_by_kind[ObservationKind.ORDER_ADMISSION]
            else None
        )
        if admission:
            admission_maximum = _decimal(admission.fields.get("maximum_quantity"))
            if admission_maximum is not None:
                for event in submitted_events:
                    quantity = _decimal(event.fields.get("quantity"))
                    if quantity is not None and quantity > admission_maximum:
                        missing.append("submit_quantity_exceeds_case_admission_limit")
            expected_offset = "close" if self.spec.order_profile == "close_position" else "open"
            if any(event.fields.get("offset") != expected_offset for event in submitted_events):
                missing.append("submit_offset_does_not_match_case_plan")
        order_refs = [str(event.fields.get("order_ref", "")) for event in submitted_events]
        if len(order_refs) != len(set(order_refs)):
            missing.append("each_managed_submit_requires_a_distinct_order_ref")

        lifecycle = {
            str(event.fields.get("event_name", "")): event
            for event in self._events
            if event.kind is ObservationKind.SYSTEM_LOG
        }
        for name in (
            "session_started",
            "store_connected",
            "store_ready",
            "session_stopped",
            "write_activity_summary",
        ):
            if name not in lifecycle:
                missing.append(f"system_log:{name}")
        system_events = [
            event for event in self._events if event.kind is ObservationKind.SYSTEM_LOG
        ]
        if len(lifecycle) != len(system_events):
            missing.append("duplicate_managed_lifecycle_event_name")
        provider_session = self._provider_scope[0] if self._provider_scope else ""
        gateway = front.fields.get("gateway_key") if front else None
        for event in system_events:
            if event.fields.get("session_id") != provider_session or (
                gateway and event.fields.get("gateway_key") != gateway
            ):
                missing.append("managed_lifecycle_must_match_provider_session_and_gateway")
        started = lifecycle.get("session_started")
        connected = lifecycle.get("store_connected")
        ready = lifecycle.get("store_ready")
        stopped = lifecycle.get("session_stopped")
        summary = lifecycle.get("write_activity_summary")
        if (
            started
            and provider_events
            and _parse_utc(started.occurred_at_utc)
            > min(_parse_utc(event.occurred_at_utc) for event in provider_events)
        ):
            missing.append("managed_process_start_must_precede_provider_callbacks")
        if connected and ready:
            if _parse_utc(ready.occurred_at_utc) < _parse_utc(connected.occurred_at_utc):
                missing.append("store_ready_must_follow_store_connected")
            for row in (connected, ready):
                if (
                    row.fields.get("market_connection") is not True
                    or row.fields.get("trade_connection") is not True
                ):
                    missing.append("both_provider_fronts_must_be_confirmed_connected")
        if (
            ready
            and subscription
            and _parse_utc(ready.occurred_at_utc) < _parse_utc(subscription.occurred_at_utc)
        ):
            missing.append("store_ready_must_follow_provider_market_subscription")
        if (
            connected
            and subscription
            and _parse_utc(connected.occurred_at_utc) < _parse_utc(subscription.occurred_at_utc)
        ):
            missing.append("store_connected_must_follow_provider_market_subscription")
        if (
            ready
            and submitted_events
            and any(
                _parse_utc(event.occurred_at_utc) <= _parse_utc(ready.occurred_at_utc)
                for event in submitted_events
            )
        ):
            missing.append("managed_submit_must_follow_store_ready")
        if stopped:
            if (
                stopped.fields.get("clean_shutdown") is not True
                or stopped.fields.get("gateway_released") is not True
                or _integer(stopped.fields.get("exit_code")) != 0
            ):
                missing.append("clean_gateway_release_and_zero_exit_required")
        if (
            stopped
            and summary
            and _parse_utc(summary.occurred_at_utc) < _parse_utc(stopped.occurred_at_utc)
        ):
            missing.append("write_summary_must_follow_session_stop")

        cancel_rows = [
            event
            for event in self._events
            if event.kind is ObservationKind.SYSTEM_LOG
            and event.fields.get("event_name") in {"order_cancel_request", "batch_cancel_requested"}
        ]
        required_cancel_name = (
            "batch_cancel_requested"
            if self.spec.order_profile in {"batch_partials", "batch_open"}
            else "order_cancel_request"
        )
        if self.spec.order_profile in {
            "open_cancel",
            "cancel",
            "batch_partials",
            "batch_open",
        } and not any(
            event.fields.get("event_name") == required_cancel_name for event in cancel_rows
        ):
            missing.append(f"managed_{required_cancel_name}_receipt_required")
        if (
            self.spec.order_profile in {"batch_partials", "batch_open"}
            and len(
                [
                    event
                    for event in cancel_rows
                    if event.fields.get("event_name") == required_cancel_name
                ]
            )
            != 1
        ):
            missing.append("exactly_one_managed_batch_cancel_receipt_required")
        if self.spec.order_profile not in {"batch_partials", "batch_open", "trade_log"}:
            single_cancels = [
                event
                for event in cancel_rows
                if event.fields.get("event_name") == "order_cancel_request"
            ]
            if len(single_cancels) > 1:
                missing.append("exactly_one_managed_order_cancel_receipt_allowed")
        if (
            self.spec.order_profile in {"open_cancel", "cancel"}
            and len(
                [
                    event
                    for event in cancel_rows
                    if event.fields.get("event_name") == "order_cancel_request"
                ]
            )
            != 1
        ):
            missing.append("single_order_cancel_case_requires_one_cancel_receipt")

        phases = {
            str(event.fields.get("phase", ""))
            for event in self._events
            if event.kind in {ObservationKind.ORDER_QUERY, ObservationKind.POSITION_QUERY}
        }
        if phases != {"baseline", "final"}:
            missing.append("complete_baseline_and_final_native_account_queries_required")
        for phase in ("baseline", "final"):
            query_rows = [
                event
                for event in self._events
                if event.kind is ObservationKind.ORDER_QUERY and event.fields.get("phase") == phase
            ]
            position_rows = [
                event
                for event in self._events
                if event.kind is ObservationKind.POSITION_QUERY
                and event.fields.get("phase") == phase
            ]
            if (
                len(query_rows) != 1
                or len(position_rows) != 2
                or {event.fields.get("query_family") for event in position_rows}
                != {"positions", "funds"}
            ):
                missing.append(f"{phase}_requires_one_order_position_and_funds_query")
        baseline_query_events = [
            event
            for event in self._events
            if event.kind in {ObservationKind.ORDER_QUERY, ObservationKind.POSITION_QUERY}
            and event.fields.get("phase") == "baseline"
        ]
        final_query_events = [
            event
            for event in self._events
            if event.kind in {ObservationKind.ORDER_QUERY, ObservationKind.POSITION_QUERY}
            and event.fields.get("phase") == "final"
        ]
        if (
            len(baseline_query_events) == 3
            and submitted_events
            and max(_parse_utc(event.occurred_at_utc) for event in baseline_query_events)
            >= min(_parse_utc(event.occurred_at_utc) for event in submitted_events)
        ):
            missing.append("baseline_order_position_and_funds_queries_must_precede_submit")
        if (
            len(final_query_events) == 3
            and stopped
            and max(_parse_utc(event.occurred_at_utc) for event in final_query_events)
            >= _parse_utc(stopped.occurred_at_utc)
        ):
            missing.append("final_order_position_and_funds_queries_must_precede_shutdown")

        status_kinds = {
            ObservationKind.ORDER_ACCEPTED,
            ObservationKind.ORDER_PARTIAL,
            ObservationKind.ORDER_CANCELED,
            ObservationKind.ORDER_FILLED,
            ObservationKind.ORDER_REJECTED,
        }
        statuses_by_ref: Dict[str, List[NativeObservation]] = {}
        for event in self._events:
            if event.kind in status_kinds:
                statuses_by_ref.setdefault(str(event.fields["order_ref"]), []).append(event)
        cancel_by_ref: Dict[str, NativeObservation] = {}
        batch_cancel = next(
            (
                event
                for event in cancel_rows
                if event.fields.get("event_name") == "batch_cancel_requested"
            ),
            None,
        )
        for event in cancel_rows:
            if event.fields.get("event_name") == "order_cancel_request":
                cancel_by_ref[str(event.fields.get("order_ref", ""))] = event
        for order_ref in order_refs:
            facts = sorted(statuses_by_ref.get(order_ref, []), key=lambda item: item.sequence)
            if not any(item.kind is ObservationKind.ORDER_ACCEPTED for item in facts):
                missing.append(f"provider_acceptance_callback:{order_ref}")
            terminal_indexes = [
                index
                for index, item in enumerate(facts)
                if item.kind
                in {
                    ObservationKind.ORDER_CANCELED,
                    ObservationKind.ORDER_FILLED,
                    ObservationKind.ORDER_REJECTED,
                }
            ]
            if len(terminal_indexes) > 1 or (
                terminal_indexes and terminal_indexes[0] != len(facts) - 1
            ):
                missing.append(f"provider_terminal_state_must_be_unique_and_latest:{order_ref}")
            if (
                self.spec.order_profile == "open_cancel"
                and facts
                and facts[-1].kind is not ObservationKind.ORDER_CANCELED
            ):
                missing.append(f"open_order_case_requires_cancel_terminal:{order_ref}")
            if self.spec.order_profile in {"open_cancel", "cancel"} and facts:
                cancel = cancel_by_ref.get(order_ref)
                accepted = next(
                    (item for item in facts if item.kind is ObservationKind.ORDER_ACCEPTED), None
                )
                if (
                    cancel
                    and accepted
                    and not (
                        _parse_utc(accepted.occurred_at_utc)
                        < _parse_utc(cancel.occurred_at_utc)
                        < _parse_utc(facts[-1].occurred_at_utc)
                    )
                ):
                    missing.append(
                        f"cancel_request_must_follow_acceptance_and_precede_terminal:{order_ref}"
                    )
            if self.spec.order_profile == "close_position" and facts:
                cancel = cancel_by_ref.get(order_ref)
                if facts[-1].kind is ObservationKind.ORDER_CANCELED and cancel is None:
                    missing.append(
                        f"canceled_close_order_requires_managed_cancel_receipt:{order_ref}"
                    )
                if cancel and _parse_utc(cancel.occurred_at_utc) >= _parse_utc(
                    facts[-1].occurred_at_utc
                ):
                    missing.append(f"close_cancel_receipt_must_precede_terminal:{order_ref}")
        if self.spec.order_profile in {"batch_partials", "batch_open"} and batch_cancel:
            batch_refs = _json_load(batch_cancel.fields.get("order_refs_json"), "batch cancel refs")
            if set(batch_refs) != set(order_refs):
                missing.append("batch_cancel_must_target_each_managed_submit_exactly_once")
            if self.spec.order_profile == "batch_partials":
                partial_refs = {
                    str(event.fields["order_ref"])
                    for event in self._events
                    if event.kind is ObservationKind.ORDER_PARTIAL
                }
                if partial_refs != set(order_refs):
                    missing.append("every_batch_partial_order_requires_partial_callback")
                if _integer(batch_cancel.fields.get("partial_count")) != len(partial_refs):
                    missing.append("batch_partial_count_must_match_native_partial_orders")
                if any(
                    not any(
                        event.kind is ObservationKind.ORDER_PARTIAL
                        and event.fields.get("order_ref") == order_ref
                        and _parse_utc(event.occurred_at_utc)
                        < _parse_utc(batch_cancel.occurred_at_utc)
                        for event in self._events
                    )
                    for order_ref in order_refs
                ):
                    missing.append("batch_partial_cancel_must_follow_each_partial_callback")
            else:
                accepted_before_batch = {
                    str(event.fields["order_ref"])
                    for event in self._events
                    if event.kind is ObservationKind.ORDER_ACCEPTED
                    and _parse_utc(event.occurred_at_utc) < _parse_utc(batch_cancel.occurred_at_utc)
                }
                if accepted_before_batch != set(order_refs):
                    missing.append("batch_cancel_requires_each_order_provider_accepted_first")
                if _integer(batch_cancel.fields.get("open_order_count")) != len(order_refs):
                    missing.append("batch_open_order_count_must_match_provider_acceptances")
        if self.spec.order_profile == "close_position" and submitted_events:
            baseline_position = next(
                (
                    event
                    for event in self._events
                    if event.kind is ObservationKind.POSITION_QUERY
                    and event.fields.get("phase") == "baseline"
                    and event.fields.get("query_family") == "positions"
                ),
                None,
            )
            if baseline_position:
                positions = _json_decimal_map(
                    baseline_position.fields.get("positions_json"), "baseline positions"
                )
                closeable = _json_decimal_map(
                    baseline_position.fields.get("closeable_quantities_json"),
                    "baseline closeable quantities",
                )
                request = submitted_events[0]
                instrument = str(request.fields["instrument_id"])
                net = positions.get(instrument, Decimal(0))
                available = closeable.get(instrument, Decimal(0))
                quantity = _decimal(request.fields.get("quantity")) or Decimal(0)
                expected_direction = "sell" if net > 0 else "buy" if net < 0 else ""
                if (
                    net == 0
                    or available <= 0
                    or quantity > available
                    or request.fields.get("direction") != expected_direction
                ):
                    missing.append("close_submit_must_be_within_opposite_side_closeable_position")
                trades = [
                    event
                    for event in self._events
                    if event.kind is ObservationKind.TRADE_EXECUTION
                    and event.fields.get("order_ref") == request.fields.get("order_ref")
                ]
                if any(
                    event.fields.get("direction") != expected_direction for event in trades
                ) or sum(
                    (_decimal(event.fields.get("quantity")) or Decimal(0)) for event in trades
                ) > min(abs(net), available):
                    missing.append("close_trade_must_reduce_position_without_reversal")
        if any(event.kind is ObservationKind.ORDER_REJECTED for event in self._events):
            missing.append("normal_order_scenario_provider_rejection_is_incomplete")

        if missing:
            return list(dict.fromkeys(missing))
        try:
            completion = self._build_completion_evidence()
            report = evaluate_case_completion(completion)
        except (CompletionEvidenceError, ValueError, TypeError, KeyError) as exc:
            return [f"completion_invariant_input_invalid:{exc}"]
        missing.extend(report.missing_invariants)
        missing.extend(report.contradictions)

        if summary:
            dispatched_submits = sum(
                event.fields.get("dispatch_state") == "dispatched" for event in submitted_events
            )
            dispatched_cancels = sum(
                event.fields.get("dispatch_state") == "dispatched" for event in cancel_rows
            )
            summary_fields = summary.fields
            if (
                summary_fields.get("snapshot_complete") is not True
                or not _SHA256_RE.fullmatch(str(summary_fields.get("snapshot_digest", "")))
                or _integer(summary_fields.get("order_submit_count")) != dispatched_submits
                or _integer(summary_fields.get("order_cancel_count")) != dispatched_cancels
                or _integer(summary_fields.get("broker_write_count"))
                != dispatched_submits + dispatched_cancels
            ):
                missing.append("write_summary_counts_must_match_managed_order_receipts")
        if stopped and provider_events:
            last_provider_time = max(_parse_utc(event.occurred_at_utc) for event in provider_events)
            if _parse_utc(stopped.occurred_at_utc) < last_provider_time:
                missing.append("managed_session_stop_must_follow_all_native_queries_and_callbacks")
        return list(dict.fromkeys(missing))

    def _build_completion_evidence(self) -> CompletionEvidence:
        requests: List[ManagedOrderRequest] = []
        order_facts: List[NativeOrderFact] = []
        trade_facts: List[NativeTradeFact] = []
        scenario_evidence: List[CertificationEvidence] = []
        for event in self._events:
            fields = dict(event.fields)
            if event.kind is ObservationKind.ORDER_SUBMIT_RECEIPT:
                request = ManagedOrderRequest(
                    request_id=str(fields["request_id"]),
                    action=RequestAction.SUBMIT,
                    dispatch_state=_dispatch_state(fields["dispatch_state"]),
                    order_refs=(str(fields["order_ref"]),),
                    occurred_at_utc=event.occurred_at_utc,
                    sequence=event.sequence,
                    evidence_sha256=event.evidence_sha256,
                    quantity=str(fields["quantity"]),
                )
                requests.append(request)
                scenario_evidence.append(
                    _certification_row(
                        event,
                        "order_submit_request",
                        EvidenceSource.MANAGED_RUNTIME,
                        {
                            "trace_id": fields["trace_id"],
                            "invocation_id": fields["invocation_id"],
                            "order_ref": fields["order_ref"],
                            "dispatch_state": fields["dispatch_state"],
                        },
                    )
                )
            elif event.kind in {
                ObservationKind.ORDER_ACCEPTED,
                ObservationKind.ORDER_PARTIAL,
                ObservationKind.ORDER_CANCELED,
                ObservationKind.ORDER_FILLED,
                ObservationKind.ORDER_REJECTED,
            }:
                fact_kind = {
                    ObservationKind.ORDER_ACCEPTED: NativeOrderFactKind.ACCEPTED,
                    ObservationKind.ORDER_PARTIAL: NativeOrderFactKind.PARTIAL,
                    ObservationKind.ORDER_CANCELED: NativeOrderFactKind.CANCELED,
                    ObservationKind.ORDER_FILLED: NativeOrderFactKind.FILLED,
                    ObservationKind.ORDER_REJECTED: NativeOrderFactKind.REJECTED,
                }[event.kind]
                order_facts.append(
                    NativeOrderFact(
                        event_id=event.event_id,
                        fact=fact_kind,
                        callback_name=event.callback_name,
                        source="ctp_provider_callback",
                        order_ref=str(fields["order_ref"]),
                        external_order_id=str(fields.get("external_order_id", "")),
                        instrument_id=str(fields["instrument_id"]),
                        status=str(fields["status"]),
                        traded_quantity=str(fields["traded_quantity"]),
                        remaining_quantity=str(fields["remaining_quantity"]),
                        session_id=event.provider_session_id,
                        trading_day=event.trading_day,
                        source_sequence=event.sequence,
                        occurred_at_utc=event.occurred_at_utc,
                        evidence_sha256=event.evidence_sha256,
                        error_id=_integer(fields.get("error_id")) or 0,
                    )
                )
                canonical_event_kind = {
                    ObservationKind.ORDER_ACCEPTED: "order_status_accepted",
                    ObservationKind.ORDER_CANCELED: "order_status_canceled",
                }.get(event.kind)
                if canonical_event_kind in SCENARIOS_BY_CASE_ID[self.case_id].required_events:
                    scenario_evidence.append(
                        _certification_row(
                            event,
                            canonical_event_kind,
                            EvidenceSource.PROVIDER_CALLBACK,
                            {
                                "order_ref": fields["order_ref"],
                                "external_order_id": fields.get("external_order_id", ""),
                                "provider_status": fields["status"],
                            },
                        )
                    )
            elif event.kind is ObservationKind.TRADE_EXECUTION:
                trade_facts.append(
                    NativeTradeFact(
                        event_id=event.event_id,
                        trade_id=str(fields["trade_id"]),
                        order_ref=str(fields["order_ref"]),
                        instrument_id=str(fields["instrument_id"]),
                        quantity=str(fields["quantity"]),
                        direction=str(fields["direction"]),
                        price=str(fields["price"]),
                        callback_name=event.callback_name,
                        source="ctp_provider_callback",
                        session_id=event.provider_session_id,
                        trading_day=event.trading_day,
                        source_sequence=event.sequence,
                        occurred_at_utc=event.occurred_at_utc,
                        evidence_sha256=event.evidence_sha256,
                        external_order_id=str(fields["external_order_id"]),
                    )
                )
                if "trade_execution" in SCENARIOS_BY_CASE_ID[self.case_id].required_events:
                    scenario_evidence.append(
                        _certification_row(
                            event,
                            "trade_execution",
                            EvidenceSource.PROVIDER_CALLBACK,
                            {
                                "order_ref": fields["order_ref"],
                                "trade_id": fields["trade_id"],
                                "external_order_id": fields["external_order_id"],
                                "instrument_id": fields["instrument_id"],
                                "quantity": fields["quantity"],
                                "direction": fields["direction"],
                                "price": fields["price"],
                            },
                        )
                    )
            elif event.kind is ObservationKind.SYSTEM_LOG:
                event_name = fields.get("event_name")
                if event_name == "order_cancel_request":
                    requests.append(
                        ManagedOrderRequest(
                            request_id=str(fields["request_id"]),
                            action=RequestAction.CANCEL,
                            dispatch_state=_dispatch_state(fields["dispatch_state"]),
                            order_refs=(str(fields["order_ref"]),),
                            occurred_at_utc=event.occurred_at_utc,
                            sequence=event.sequence,
                            evidence_sha256=event.evidence_sha256,
                        )
                    )
                    if "order_cancel_request" in SCENARIOS_BY_CASE_ID[self.case_id].required_events:
                        scenario_evidence.append(
                            _certification_row(
                                event,
                                "order_cancel_request",
                                EvidenceSource.MANAGED_RUNTIME,
                                {
                                    "trace_id": fields["trace_id"],
                                    "invocation_id": fields["invocation_id"],
                                    "order_ref": fields["order_ref"],
                                    "dispatch_state": fields["dispatch_state"],
                                },
                            )
                        )
                elif event_name == "batch_cancel_requested":
                    refs = _json_load(fields.get("order_refs_json"), "batch cancel order refs")
                    if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
                        raise CompletionEvidenceError(
                            "batch cancel refs must be a JSON string list"
                        )
                    requests.append(
                        ManagedOrderRequest(
                            request_id=str(fields["request_id"]),
                            action=RequestAction.BATCH_CANCEL,
                            dispatch_state=_dispatch_state(fields["dispatch_state"]),
                            order_refs=tuple(refs),
                            occurred_at_utc=event.occurred_at_utc,
                            sequence=event.sequence,
                            evidence_sha256=event.evidence_sha256,
                        )
                    )
                    batch_fields = {
                        "trace_id": fields["trace_id"],
                        "invocation_id": fields["invocation_id"],
                        "order_refs": refs,
                        "dispatch_state": fields["dispatch_state"],
                    }
                    count_name = "partial_count" if self.case_id == "B01" else "open_order_count"
                    if count_name in fields:
                        batch_fields[count_name] = fields[count_name]
                    scenario_evidence.append(
                        _certification_row(
                            event,
                            "batch_cancel_requested",
                            EvidenceSource.MANAGED_RUNTIME,
                            batch_fields,
                        )
                    )

        snapshots = self._build_query_snapshots()
        return CompletionEvidence(
            case_id=self.case_id,
            scenario_evidence=tuple(scenario_evidence),
            managed_requests=tuple(requests),
            order_facts=tuple(order_facts),
            trade_facts=tuple(trade_facts),
            snapshots=tuple(snapshots),
        )

    def _build_query_snapshots(self) -> List[AccountReconciliationSnapshot]:
        snapshots: List[AccountReconciliationSnapshot] = []
        callback_by_family = {
            "orders": "OnRspQryOrder",
            "positions": "OnRspQryInvestorPosition",
            "funds": "OnRspQryTradingAccount",
        }
        for phase_text in ("baseline", "final"):
            rows = {
                str(event.fields.get("query_family")): event
                for event in self._events
                if event.kind in {ObservationKind.ORDER_QUERY, ObservationKind.POSITION_QUERY}
                and event.fields.get("phase") == phase_text
            }
            if set(rows) != {"orders", "positions", "funds"}:
                raise CompletionEvidenceError(
                    f"{phase_text} native snapshot has incomplete query families"
                )
            events = tuple(rows[family] for family in ("orders", "positions", "funds"))
            if len({event.fields.get("snapshot_id") for event in events}) != 1:
                raise CompletionEvidenceError(
                    f"{phase_text} query families do not share snapshot id"
                )
            order_event = rows["orders"]
            position_event = rows["positions"]
            funds_event = rows["funds"]
            open_refs = _json_load(order_event.fields["open_order_refs_json"], "open order refs")
            positions = _json_decimal_map(
                position_event.fields["positions_json"], "position snapshot"
            )
            funds = _json_decimal_map(funds_event.fields["funds_json"], "funds snapshot")
            callbacks = tuple(
                callback_by_family[family] for family in ("orders", "positions", "funds")
            )
            digest_material = "".join(event.evidence_sha256 for event in events).encode("ascii")
            snapshots.append(
                AccountReconciliationSnapshot(
                    phase=SnapshotPhase(phase_text),
                    session_id=order_event.provider_session_id,
                    trading_day=order_event.trading_day,
                    occurred_at_utc=max(
                        (event.occurred_at_utc for event in events),
                        key=_parse_utc,
                    ),
                    order_query_id=str(order_event.fields["query_id"]),
                    position_query_id=str(position_event.fields["query_id"]),
                    account_query_id=str(funds_event.fields["query_id"]),
                    order_query_sequence=order_event.sequence,
                    position_query_sequence=position_event.sequence,
                    account_query_sequence=funds_event.sequence,
                    open_order_refs=tuple(open_refs),
                    positions=positions,
                    funds=funds,
                    callback_names=callbacks,
                    source="ctp_provider_callback",
                    evidence_sha256=sha256(digest_material).hexdigest(),
                    query_error_ids={
                        callback_by_family[family]: _integer(rows[family].fields["error_id"])
                        for family in ("orders", "positions", "funds")
                    },
                    query_is_last={
                        callback_by_family[family]: rows[family].fields["is_last"]
                        for family in ("orders", "positions", "funds")
                    },
                    client_instance_id=(order_event.client_instance_id if self.case_id == "C01" else ""),
                    arrival_generation=(order_event.arrival_generation if self.case_id == "C01" else 0),
                    query_native_request_ids=(
                        {callback_by_family[family]: rows[family].fields["request_id"] for family in ("orders", "positions", "funds")}
                        if self.case_id == "C01" else {}
                    ),
                    query_round_id=(str(order_event.fields["query_round_id"]) if self.case_id == "C01" else ""),
                    query_id_origin=("local_query_coordinator" if self.case_id == "C01" else ""),
                    query_round_id_origin=("local_query_coordinator" if self.case_id == "C01" else ""),
                    sequence_origin=("local_sdk_callback_arrival" if self.case_id == "C01" else ""),
                    timestamp_origin=("local_sdk_capture_clock" if self.case_id == "C01" else ""),
                    session_identity_origin=(
                        "derived_from_same_client_generation_native_login" if self.case_id == "C01" else ""
                    ),
                    query_issued_request_receipts=(
                        {callback_by_family[family]: rows[family].issued_request_receipt for family in ("orders", "positions", "funds")}
                        if self.case_id == "C01" else {}
                    ),
                    query_request_generations=(
                        {callback_by_family[family]: rows[family].request_generation for family in ("orders", "positions", "funds")}
                        if self.case_id == "C01" else {}
                    ),
                    query_arrival_times_utc=(
                        {callback_by_family[family]: rows[family].arrived_at_utc for family in ("orders", "positions", "funds")}
                        if self.case_id == "C01" else {}
                    ),
                    query_arrival_monotonic=(
                        {callback_by_family[family]: rows[family].arrived_monotonic for family in ("orders", "positions", "funds")}
                        if self.case_id == "C01" else {}
                    ),
                )
            )
        return snapshots

    def _check_threshold(
        self,
        by_kind: Mapping[ObservationKind, List[NativeObservation]],
        missing: List[str],
    ) -> None:
        configurations = by_kind.get(ObservationKind.MONITOR_CONFIGURATION, [])
        monitor_logs = by_kind.get(ObservationKind.MONITOR_LOG, [])
        if len(configurations) != 1:
            missing.append("exactly_one_runtime_threshold_configuration_required")
            return
        if len(monitor_logs) != 1:
            missing.append("exactly_one_runtime_threshold_log_required")
        config = configurations[0]
        fields = config.fields
        if (
            fields.get("metric") != self.spec.expected_metric
            or _integer(fields.get("threshold")) != self.spec.expected_threshold
        ):
            missing.append("runtime_threshold_does_not_match_case_plan")
        window = (
            _decimal(fields.get("window_seconds")) if self.spec.requires_repeat_window else None
        )
        if self.spec.requires_repeat_window and (window is None or window <= 0):
            missing.append("positive_repeat_window_required")
        matching_logs = [
            event
            for event in monitor_logs
            if event.fields.get("event_name") == "risk_threshold_configured"
            and event.fields.get("metric") == self.spec.expected_metric
            and _integer(event.fields.get("threshold")) == self.spec.expected_threshold
            and event.fields.get("configuration_digest") == fields.get("configuration_digest")
            and event.fields.get("monitor_digest") == fields.get("monitor_digest")
            and (
                not self.spec.requires_repeat_window
                or _decimal(event.fields.get("window_seconds")) == window
            )
            and _parse_utc(event.occurred_at_utc) >= _parse_utc(config.occurred_at_utc)
        ]
        if not matching_logs:
            missing.append("matching_timestamped_monitor_log_required")

    def _one(self, kind: ObservationKind) -> NativeObservation:
        events = [item for item in self._events if item.kind is kind]
        # A missing event is detected before this helper is used.
        return events[-1]


class C01Strategy(ReadOnlyCaseStrategy):
    case_id = "C01"


class M01Strategy(ReadOnlyCaseStrategy):
    case_id = "M01"


class L02Strategy(ReadOnlyCaseStrategy):
    case_id = "L02"


class TH01Strategy(ReadOnlyCaseStrategy):
    case_id = "TH01"


class TH03Strategy(ReadOnlyCaseStrategy):
    case_id = "TH03"


class TH05Strategy(ReadOnlyCaseStrategy):
    case_id = "TH05"


class T01Strategy(ReadOnlyCaseStrategy):
    case_id = "T01"


class T02Strategy(ReadOnlyCaseStrategy):
    case_id = "T02"


class T03Strategy(ReadOnlyCaseStrategy):
    case_id = "T03"


class B01Strategy(ReadOnlyCaseStrategy):
    case_id = "B01"


class B02Strategy(ReadOnlyCaseStrategy):
    case_id = "B02"


class L01Strategy(ReadOnlyCaseStrategy):
    case_id = "L01"


def create_read_only_strategy(
    case_id: str,
    plan: DescriptiveCasePlan,
    scope: DecisionScope,
    authenticator: Optional[ObservationAuthenticator],
) -> ReadOnlyCaseStrategy:
    strategy_types = {
        "C01": C01Strategy,
        "M01": M01Strategy,
        "L02": L02Strategy,
        "TH01": TH01Strategy,
        "TH03": TH03Strategy,
        "TH05": TH05Strategy,
        "T01": T01Strategy,
        "T02": T02Strategy,
        "T03": T03Strategy,
        "B01": B01Strategy,
        "B02": B02Strategy,
        "L01": L01Strategy,
    }
    strategy_type = strategy_types.get(case_id)
    if strategy_type is None:
        raise ReadOnlyStrategyError(f"unsupported read-only strategy case {case_id!r}")
    return strategy_type(plan, scope, authenticator)


def _integer(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    return result


def _decimal(value: Any) -> Optional[Decimal]:
    if isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _dispatch_state(value: Any) -> DispatchState:
    try:
        return {
            "dispatched": DispatchState.DISPATCHED,
            "blocked_pre_dispatch": DispatchState.BLOCKED_PRE_DISPATCH,
        }[value]
    except (KeyError, TypeError) as exc:
        raise CompletionEvidenceError("managed request has invalid dispatch state") from exc


def _certification_row(
    event: NativeObservation,
    event_kind: str,
    source: EvidenceSource,
    fields: Mapping[str, Any],
) -> CertificationEvidence:
    provider = event.source_domain is EvidenceTrustDomain.CTP_CALLBACK
    return CertificationEvidence(
        event_kind=event_kind,
        source=source,
        event_id=event.event_id,
        evidence_sha256=event.evidence_sha256,
        occurred_at_utc=event.occurred_at_utc,
        fields=dict(fields),
        callback_names=(event.callback_name,) if provider else (),
        provider_session_id=event.provider_session_id if provider else "",
        trading_day=event.trading_day if provider else "",
        source_sequence=event.sequence if provider else 0,
    )


def _json_load(value: Any, description: str) -> Any:
    if not isinstance(value, str):
        raise CompletionEvidenceError(f"{description} must be JSON text")
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise CompletionEvidenceError(f"{description} is not valid JSON") from exc


def _json_decimal_map(value: Any, description: str) -> Dict[str, Decimal]:
    parsed = _json_load(value, description)
    if not isinstance(parsed, dict) or any(not isinstance(key, str) or not key for key in parsed):
        raise CompletionEvidenceError(f"{description} must be a JSON object keyed by identifiers")
    result = {}
    for key, raw_value in parsed.items():
        decimal_value = _decimal(raw_value)
        if decimal_value is None:
            raise CompletionEvidenceError(f"{description} values must be finite decimals")
        result[key] = decimal_value
    return result


def _parse_utc(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(timezone.utc)
