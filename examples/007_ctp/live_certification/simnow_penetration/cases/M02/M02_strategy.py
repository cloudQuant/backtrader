"""Case-specific real evidence and action plan; descriptive data only."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import re
from types import MappingProxyType
from typing import Mapping

from common.case_engine import DescriptiveCasePlan
from common.decision_engine import (
    CASE_INTENT_SPECS,
    CaseIntentDecisionEngine,
    DecisionError,
    DecisionScope,
    EvidenceTrustDomain,
    NativeObservation,
    ObservationAuthenticator,
    ObservationKind,
)

CASE_ID = "M02"
CASE_NAME = "Controlled session disconnect display"
CASE_PLAN = {
    "evidence": (
        "Capture store_disconnected, its timestamp, source transport event, and the active provider session identity.",
        "Correlate the disconnect display with the observed TD/MD transport loss and retain supervised restoration evidence.",
    ),
    "actions": (
        "Under an approved supervised fault procedure, interrupt the active test session transport and observe store_disconnected; ordinary local stop is insufficient.",
        "Restore the transport under supervision and reconcile the session and zero residual orders; leave the case BLOCKED if controlled fault capability is unavailable.",
    ),
}


_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_CALLBACKS = (
    "OnFrontConnected",
    "OnRspAuthenticate",
    "OnRspUserLogin",
    "OnRspSubMarketData",
)


def _copy_event(event: NativeObservation) -> NativeObservation:
    if not isinstance(event.fields, Mapping):
        raise DecisionError("observation fields must be a mapping")
    copied = {}
    for key, value in event.fields.items():
        if not isinstance(key, str):
            raise DecisionError("observation field names must be strings")
        if isinstance(value, (str, bool, int, float, type(None))):
            copied[key] = value
        elif isinstance(value, (tuple, list)) and all(
            isinstance(item, (str, bool, int, float, type(None))) for item in value
        ):
            copied[key] = tuple(value)
        else:
            raise DecisionError("observation fields must contain immutable scalar facts")
    return replace(event, fields=MappingProxyType(copied))


class M02Strategy(CaseIntentDecisionEngine):
    """Require a supervised disconnect and a separate, successful recovery."""

    def __init__(self, plan, scope, authenticator):
        super().__init__(plan, scope, authenticator)
        kinds = (
            ObservationKind.FRONT_DISCONNECTED,
            ObservationKind.EXTERNAL_CONDITION,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.AUTH_SUCCESS,
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.MARKET_SUBSCRIPTION_ACK,
            ObservationKind.SYSTEM_LOG,
        )
        self.spec = replace(CASE_INTENT_SPECS[CASE_ID], required_kinds=kinds)

    def record(self, event: NativeObservation) -> bool:
        try:
            return self._record_observation(event)
        except Exception as exc:
            event_id = event.event_id if type(event) is NativeObservation else "invalid-event"
            self._rejected.append(f"{event_id}:record_rejected:{type(exc).__name__}")
            raise

    def _record_observation(self, event: NativeObservation) -> bool:
        event = _copy_event(event)
        self._validate_event(event)
        if event.event_id in self._event_ids:
            raise DecisionError("duplicate observation event_id")
        if event.kind is ObservationKind.SYSTEM_LOG:
            self._validate_lifecycle_log(event)
        if self._authenticator is None:
            self._rejected.append(f"{event.event_id}:authenticator_unavailable")
            return False
        receipt = self._authenticator.authenticate(event, self.scope)
        if receipt is None or (
            receipt.event_id != event.event_id
            or receipt.evidence_sha256.lower() != event.evidence_sha256.lower()
            or receipt.scope_sha256.lower() != self.scope.scope_sha256.lower()
            or not isinstance(receipt.account_identity_sha256, str)
            or receipt.account_identity_sha256.lower()
            != self.scope.account_identity_sha256.lower()
            or receipt.trust_domain is not event.source_domain
            or not receipt.verification_ref.strip()
        ):
            self._rejected.append(f"{event.event_id}:verification_receipt_mismatch")
            return False

        if event.source_domain is EvidenceTrustDomain.CTP_CALLBACK:
            generation = event.fields.get("connection_generation")
            if type(generation) is not int or generation < 1:
                raise DecisionError("provider callback requires a positive connection generation")
            if (
                not event.client_instance_id
                or event.arrival_generation != generation
                or event.sequence_origin != "local_sdk_callback_arrival"
                or event.timestamp_origin != "local_sdk_capture_clock"
                or event.event_id_origin != "local_sdk_callback_arrival"
                or event.provider_issued_event_id is not False
                or type(event.arrived_monotonic) not in {int, float}
                or isinstance(event.arrived_monotonic, bool)
                or event.arrived_monotonic <= 0
                or _utc(event.arrived_at_utc) != _utc(event.occurred_at_utc)
            ):
                raise DecisionError("CTP callback requires same-client local arrival metadata")
            if event.kind in {
                ObservationKind.FRONT_CONNECTED,
                ObservationKind.FRONT_DISCONNECTED,
            }:
                if event.connection_generation_origin != "local_connection_generation":
                    raise DecisionError("front callbacks require local connection-generation origin")
                if event.session_identity_origin != "unavailable_on_native_front_connection_callback":
                    raise DecisionError("payloadless front callbacks cannot establish provider identity")
            elif event.kind is ObservationKind.MARKET_SUBSCRIPTION_ACK:
                if event.session_identity_origin != "derived_from_same_client_generation_native_login":
                    raise DecisionError("subscription scope must be derived from a same-client login")
            elif event.kind not in {
                ObservationKind.AUTH_SUCCESS,
                ObservationKind.LOGIN_SUCCESS,
            } and event.session_identity_origin != "derived_from_same_client_generation_native_login":
                raise DecisionError("provider scope must be derived from a same-client native login")

        if event.source_domain is EvidenceTrustDomain.CTP_CALLBACK:
            sequence_key = (event.source_domain, event.client_instance_id, event.stream_id, "")
        else:
            sequence_key = (
                event.source_domain,
                event.stream_id,
                event.provider_session_id,
                event.trading_day,
            )
        if event.sequence <= self._sequences.get(sequence_key, 0):
            raise DecisionError("observation sequence must increase within a source stream")

        if event.source_domain is EvidenceTrustDomain.CTP_CALLBACK:
            provider_events = [
                item
                for item in self._events
                if item.source_domain is event.source_domain
                and item.client_instance_id == event.client_instance_id
                and item.stream_id == event.stream_id
            ]
            provider_logins = [
                item for item in provider_events if item.kind is ObservationKind.LOGIN_SUCCESS
            ]
            latest_login = provider_logins[-1] if provider_logins else None
            generation = event.fields["connection_generation"]
            if event.kind is ObservationKind.FRONT_DISCONNECTED:
                if latest_login is not None and (
                    latest_login.arrival_generation != generation
                    or latest_login.sequence >= event.sequence
                ):
                    raise DecisionError("disconnect must follow the active native login generation")
            elif event.kind is ObservationKind.FRONT_CONNECTED:
                if latest_login is not None:
                    old_generation = latest_login.arrival_generation
                    if generation < old_generation:
                        raise DecisionError("front connection generation cannot move backwards")
                    if generation > old_generation and not any(
                        item.kind is ObservationKind.FRONT_DISCONNECTED
                        and item.arrival_generation == old_generation
                        and item.sequence < event.sequence
                        for item in provider_events
                    ):
                        raise DecisionError("new front generation requires prior local disconnect")
                    if generation == old_generation and any(
                        item.kind is ObservationKind.FRONT_DISCONNECTED
                        and item.arrival_generation == old_generation
                        and item.sequence > latest_login.sequence
                        and item.sequence < event.sequence
                        for item in provider_events
                    ):
                        raise DecisionError("reconnected front must use a new local generation")
            elif event.kind is ObservationKind.AUTH_SUCCESS:
                if not any(
                    item.kind is ObservationKind.FRONT_CONNECTED
                    and item.arrival_generation == generation
                    and item.sequence < event.sequence
                    for item in provider_events
                ):
                    raise DecisionError("authentication requires prior same-generation front connection")
            elif event.kind is ObservationKind.LOGIN_SUCCESS:
                if latest_login is not None:
                    old_generation = latest_login.arrival_generation
                    new_scope = (event.provider_session_id, event.trading_day)
                    old_scope = (latest_login.provider_session_id, latest_login.trading_day)
                    if generation < old_generation:
                        raise DecisionError("login generation cannot move backwards")
                    if generation == old_generation and new_scope != old_scope:
                        raise DecisionError("same-generation login cannot change provider identity")
                    if generation > old_generation and not (
                        any(
                            item.kind is ObservationKind.FRONT_DISCONNECTED
                            and item.arrival_generation == old_generation
                            and latest_login.sequence < item.sequence < event.sequence
                            for item in provider_events
                        )
                        and any(
                            item.kind is ObservationKind.FRONT_CONNECTED
                            and item.arrival_generation == generation
                            and item.sequence < event.sequence
                            for item in provider_events
                        )
                    ):
                        raise DecisionError("new native login requires a new local connection generation")
            else:
                if latest_login is None:
                    raise DecisionError("session-scoped callback requires prior native user login")
                if (
                    latest_login.arrival_generation != generation
                    or (event.provider_session_id, event.trading_day)
                    != (latest_login.provider_session_id, latest_login.trading_day)
                    or event.sequence <= latest_login.sequence
                ):
                    raise DecisionError("provider callback scope must match prior same-generation login")

            if event.kind is ObservationKind.LOGIN_SUCCESS:
                provider_scope = (event.provider_session_id, event.trading_day)
                if self._provider_session is None:
                    self._provider_session = provider_scope
                elif provider_scope != self._provider_session:
                    if self.plan.case_id not in {"M02", "M03"}:
                        raise DecisionError(
                            "one case decision cannot mix provider sessions or trading days"
                        )
                    if latest_login is None or generation <= latest_login.arrival_generation:
                        raise DecisionError("provider identity may change only on a newer native login")
                    self._provider_session = provider_scope
            elif event.kind not in {
                ObservationKind.AUTH_SUCCESS,
                ObservationKind.FRONT_CONNECTED,
                ObservationKind.FRONT_DISCONNECTED,
            }:
                provider_scope = (event.provider_session_id, event.trading_day)
                if self._provider_session is None or provider_scope != self._provider_session:
                    raise DecisionError("provider callback does not match the latest native login")

        self._sequences[sequence_key] = event.sequence
        self._event_ids.add(event.event_id)
        self._events.append(event)
        return True

    def _validate_lifecycle_log(self, event: NativeObservation) -> None:
        name = event.fields.get("event_name")
        if name not in {"store_disconnected", "store_reconnect_success"}:
            raise DecisionError("M02 runtime log must be a disconnect or recovery summary")
        if (
            not isinstance(event.fields.get("session_id"), str)
            or type(event.fields.get("connection_generation")) is not int
            or event.fields.get("connection_generation") < 1
            or not isinstance(event.fields.get("provider_event_id"), str)
        ) and name == "store_disconnected":
            raise DecisionError("disconnect log must bind the old session generation and callback")
        if name == "store_reconnect_success":
            if (
                not isinstance(event.fields.get("session_id"), str)
                or type(event.fields.get("connection_generation")) is not int
                or event.fields.get("connection_generation") < 1
                or tuple(event.fields.get("callback_names", ())) != _CALLBACKS
                or len(tuple(event.fields.get("provider_event_ids", ()))) != 4
            ):
                raise DecisionError("recovery summary must name its four fresh native callbacks")
            for key in ("auth_error_id", "login_error_id", "subscription_error_id"):
                if type(event.fields.get(key)) is not int or event.fields[key] != 0:
                    raise DecisionError("recovery summary requires three zero provider error ids")
            for key in (
                "authentication_succeeded",
                "login_succeeded",
                "subscription_succeeded",
            ):
                if event.fields.get(key) is not True:
                    raise DecisionError(
                        "recovery summary requires successful auth/login/subscription"
                    )
            if (
                not _HEX64.fullmatch(str(event.fields.get("snapshot_sha256", "")))
                or not event.fields.get("external_event_id")
                or not event.fields.get("snapshot_event_id")
            ):
                raise DecisionError(
                    "recovery summary must bind the external condition and snapshot"
                )

    def _missing(self, now: datetime) -> tuple[str, ...]:
        missing = list(super()._missing(now))

        def exactly_one(kind):
            rows = self._all(kind)
            if len(rows) != 1:
                missing.append(f"exactly_one_{kind.value}_required")
                return None
            return rows[0]

        disconnected = exactly_one(ObservationKind.FRONT_DISCONNECTED)
        connected = exactly_one(ObservationKind.FRONT_CONNECTED)
        authentication = exactly_one(ObservationKind.AUTH_SUCCESS)
        subscribed = exactly_one(ObservationKind.MARKET_SUBSCRIPTION_ACK)
        control_disconnect = next(
            (
                item
                for item in self._all(ObservationKind.EXTERNAL_CONDITION)
                if item.fields.get("condition_id") == "external_disconnect"
                and item.fields.get("state") == "satisfied"
            ),
            None,
        )
        control_reconnect = next(
            (
                item
                for item in self._all(ObservationKind.EXTERNAL_CONDITION)
                if item.fields.get("condition_id") == "external_reconnect"
                and item.fields.get("state") == "satisfied"
            ),
            None,
        )
        if len(self._all(ObservationKind.EXTERNAL_CONDITION)) != 2 or not (
            control_disconnect and control_reconnect
        ):
            missing.append("one_disconnect_and_one_reconnect_control_receipt_required")
        logs = self._all(ObservationKind.SYSTEM_LOG)
        by_name = {item.fields.get("event_name"): item for item in logs}
        if len(logs) != 2 or set(by_name) != {"store_disconnected", "store_reconnect_success"}:
            missing.append("disconnect_and_recovery_runtime_summaries_required")

        old_login = new_login = None
        old_gen = new_gen = None
        if disconnected is not None and connected is not None:
            old_gen = disconnected.fields.get("connection_generation")
            new_gen = connected.fields.get("connection_generation")
            login_rows = self._all(ObservationKind.LOGIN_SUCCESS)
            old_candidates = [
                item
                for item in login_rows
                if item.session_identity_origin == "native_login_response_fields"
                and item.client_instance_id == disconnected.client_instance_id
                and item.stream_id == disconnected.stream_id
                and item.arrival_generation == old_gen
                and item.fields.get("connection_generation") == old_gen
                and item.sequence < disconnected.sequence
                and _utc(item.occurred_at_utc) < _utc(disconnected.occurred_at_utc)
            ]
            new_candidates = [
                item
                for item in login_rows
                if item.session_identity_origin == "native_login_response_fields"
                and item.client_instance_id == connected.client_instance_id
                and item.stream_id == connected.stream_id
                and item.arrival_generation == new_gen
                and item.fields.get("connection_generation") == new_gen
                and item.sequence > connected.sequence
                and _utc(item.occurred_at_utc) > _utc(connected.occurred_at_utc)
            ]
            if len(old_candidates) != 1:
                missing.append("one_pre_disconnect_native_login_binding_required")
            else:
                old_login = old_candidates[0]
            if len(new_candidates) != 1:
                missing.append("one_reconnect_native_login_binding_required")
            else:
                new_login = new_candidates[0]

        if not all((disconnected, connected, authentication, subscribed, old_login, new_login)):
            return tuple(dict.fromkeys(missing))

        old_id, old_day = old_login.provider_session_id, old_login.trading_day
        new_id, new_day = new_login.provider_session_id, new_login.trading_day
        callbacks = (connected, authentication, new_login, subscribed)
        if (
            old_id == new_id
            or old_day != new_day
            or type(old_gen) is not int
            or type(new_gen) is not int
            or new_gen <= old_gen
            or old_login.client_instance_id != disconnected.client_instance_id
            or old_login.client_instance_id != connected.client_instance_id
            or new_login.client_instance_id != old_login.client_instance_id
            or any(item.stream_id != old_login.stream_id for item in callbacks)
            or disconnected.stream_id != old_login.stream_id
            or any(item.arrival_generation != new_gen for item in callbacks)
            or any(item.fields.get("connection_generation") != new_gen for item in callbacks)
            or connected.provider_session_id
            or connected.trading_day
            or authentication.provider_session_id
            or authentication.trading_day
            or (new_login.provider_session_id, new_login.trading_day) != (new_id, new_day)
            or (subscribed.provider_session_id, subscribed.trading_day) != (new_id, new_day)
            or subscribed.session_identity_origin
            != "derived_from_same_client_generation_native_login"
            or connected.fields.get("gateway_key") != disconnected.fields.get("gateway_key")
        ):
            missing.append("recovery_must_bind_native_login_scopes_to_local_generations")
        ordered = (old_login, disconnected, connected, authentication, new_login, subscribed)
        times = [_utc(item.occurred_at_utc) for item in ordered]
        sequences = [item.sequence for item in ordered]
        if times != sorted(times) or sequences != sorted(sequences):
            missing.append("native_login_disconnect_reconnect_callbacks_must_follow_local_arrival_order")
        if (
            authentication.client_instance_id != new_login.client_instance_id
            or authentication.arrival_generation != new_login.arrival_generation
            or authentication.request_generation == new_login.request_generation
            or authentication.fields.get("request_id") == new_login.fields.get("request_id")
        ):
            missing.append("recovery_auth_login_must_use_distinct_same_client_requests")
        if control_disconnect:
            f = control_disconnect.fields
            if (
                f.get("provider_event_ref") != disconnected.event_id
                or f.get("session_id") != old_id
                or f.get("connection_generation") != old_gen
                or f.get("gateway_key") != disconnected.fields.get("gateway_key")
                or not f.get("snapshot_event_id")
                or not _HEX64.fullmatch(str(f.get("snapshot_sha256", "")))
                or _utc(control_disconnect.occurred_at_utc) < _utc(disconnected.occurred_at_utc)
                or _utc(control_disconnect.occurred_at_utc) >= _utc(connected.occurred_at_utc)
            ):
                missing.append("external_disconnect_must_bind_old_callback_and_snapshot")
        if control_reconnect:
            f = control_reconnect.fields
            if (
                f.get("disconnect_event_ref") != disconnected.event_id
                or f.get("reconnect_event_ref") != connected.event_id
                or f.get("previous_session_id") != old_id
                or f.get("new_session_id") != new_id
                or f.get("previous_connection_generation") != old_gen
                or f.get("new_connection_generation") != new_gen
                or f.get("gateway_key") != connected.fields.get("gateway_key")
                or not f.get("snapshot_event_id")
                or not _HEX64.fullmatch(str(f.get("snapshot_sha256", "")))
                or _utc(control_reconnect.occurred_at_utc) < _utc(subscribed.occurred_at_utc)
            ):
                missing.append("external_reconnect_must_bind_both_sessions_and_snapshot")
        disconnect_log = by_name.get("store_disconnected")
        summary = by_name.get("store_reconnect_success")
        if disconnect_log and (
            disconnect_log.fields.get("session_id") != old_id
            or disconnect_log.fields.get("connection_generation") != old_gen
            or disconnect_log.fields.get("provider_event_id") != disconnected.event_id
            or _utc(disconnect_log.occurred_at_utc) < _utc(disconnected.occurred_at_utc)
            or _utc(disconnect_log.occurred_at_utc) >= _utc(connected.occurred_at_utc)
        ):
            missing.append("store_disconnected_log_must_reference_old_native_callback")
        if summary and control_reconnect:
            f = summary.fields
            expected_ids = tuple(item.event_id for item in callbacks)
            if (
                f.get("session_id") != new_id
                or f.get("connection_generation") != new_gen
                or tuple(f.get("callback_names", ())) != _CALLBACKS
                or tuple(f.get("provider_event_ids", ())) != expected_ids
                or f.get("external_event_id") != control_reconnect.event_id
                or f.get("snapshot_event_id") != control_reconnect.fields.get("snapshot_event_id")
                or f.get("snapshot_sha256") != control_reconnect.fields.get("snapshot_sha256")
                or f.get("previous_session_id") != old_id
                or f.get("new_session_id") != new_id
                or f.get("previous_connection_generation") != old_gen
                or f.get("new_connection_generation") != new_gen
                or _utc(summary.occurred_at_utc)
                < max(_utc(item.occurred_at_utc) for item in callbacks)
                or _utc(summary.occurred_at_utc) < _utc(control_reconnect.occurred_at_utc)
            ):
                missing.append(
                    "recovery_summary_must_bind_fresh_callbacks_control_event_and_snapshot"
                )
        return tuple(dict.fromkeys(missing))



def _utc(value: str):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def create_strategy(
    plan: DescriptiveCasePlan,
    scope: DecisionScope,
    authenticator: ObservationAuthenticator | None,
) -> M02Strategy:
    return M02Strategy(plan, scope, authenticator)
