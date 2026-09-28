"""Unregistered, review-only typed state checks for selected 007 cases.

This candidate consumes already normalized observations and managed-runtime
receipts. It performs no provider, SDK, network, config, Store, or order work.
It requires an injected authenticator and always returns a non-authorizing
snapshot; fake authenticators used by tests do not establish source authority.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_MAX_PROVIDER_EVENT_AGE = timedelta(minutes=5)
_POLICY = {
    "auth_success": ("ctp_provider_callback", "OnRspAuthenticate"),
    "login_success": ("ctp_provider_callback", "OnRspUserLogin"),
    "front_connected": ("ctp_provider_callback", "OnFrontConnected"),
    "market_subscription_ack": ("ctp_provider_callback", "OnRspSubMarketData"),
    "market_tick": ("ctp_provider_callback", "OnRtnDepthMarketData"),
    "position_query": ("ctp_provider_callback", "OnRspQryInvestorPosition"),
    "order_accepted": ("ctp_provider_callback", "OnRtnOrder"),
    "order_canceled": ("ctp_provider_callback", "OnRtnOrder"),
    "order_query": ("ctp_provider_callback", "OnRspQryOrder"),
    "order_admission": ("managed_runtime_receipt", ""),
    "order_submit_receipt": ("managed_runtime_receipt", ""),
    "order_cancel_receipt": ("managed_runtime_receipt", ""),
    "repeat_guard": ("runtime_monitor_receipt", ""),
    "monitor_configuration": ("runtime_monitor_receipt", ""),
    "monitor_trigger": ("runtime_monitor_receipt", ""),
}
_REQUIRED_FIELDS = {
    "order_accepted": (
        "order_ref",
        "external_order_id",
        "instrument_id",
        "status",
        "remaining_quantity",
    ),
    "order_canceled": (
        "order_ref",
        "external_order_id",
        "instrument_id",
        "status",
        "remaining_quantity",
    ),
}


@dataclass(frozen=True)
class ManagedIntentReceipt:
    """Typed receipt shape required from a managed runtime producer."""

    request_id: str
    intent_id: str
    action: str
    dispatch_state: str
    order_ref: str
    instrument_id: str
    repeat_key: str
    account_identity_sha256: str
    configuration_digest: str
    threshold: int
    window_seconds: float
    occurred_at_utc: str
    sequence: int
    evidence_sha256: str
    source: str = "managed_runtime_receipt"


@dataclass(frozen=True)
class ScenarioStateSnapshot:
    case_id: str
    status: str
    certification_pass: bool
    dispatch_permitted: bool
    source_authenticity_verified: bool
    missing_conditions: tuple[str, ...]
    rejected_evidence: tuple[str, ...]


_PROFILES: dict[str, dict[str, Any]] = {
    "O01": {
        "action": "open",
        "receipt_actions": {"open"},
        "repeat_metric": "repeat_order_count",
        "repeat": True,
    },
    "O02": {
        "action": "close",
        "receipt_actions": {"close"},
        "repeat_metric": "repeat_order_count",
        "repeat": True,
    },
    "O03": {
        "action": "cancel",
        "receipt_actions": {"cancel"},
        "repeat_metric": "repeat_cancel_count",
        "repeat": True,
    },
    "TH02": {
        "action": "open",
        "receipt_actions": {"open"},
        "threshold_metric": "submitted_order_count",
        "threshold": 2,
        "count_actions": {"open"},
    },
    "TH04": {
        "action": "cancel",
        "receipt_actions": {"open", "cancel"},
        "threshold_metric": "combined_order_cancel_count",
        "threshold": 3,
        "count_actions": {"open", "cancel"},
    },
    "TH06": {
        "action": "open",
        "receipt_actions": {"open"},
        "threshold_metric": "repeat_order_count",
        "threshold": 2,
        "repeat": True,
        "count_actions": {"open"},
    },
}


def _value(item: Any) -> str:
    value = getattr(item, "value", item)
    return str(value)


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        return None
    return result.astimezone(timezone.utc)


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


class TypedScenarioStateCandidate:
    """Case-specific checks layered over the unregistered typed decision API."""

    CASE_ID = ""

    def __init__(self, decision_engine: Any, authenticator: Any):
        if self.CASE_ID not in _PROFILES:
            raise ValueError("unsupported read-only scenario case")
        if getattr(getattr(decision_engine, "plan", None), "case_id", None) != self.CASE_ID:
            raise ValueError("decision engine plan does not match this case")
        if getattr(getattr(decision_engine, "scope", None), "case_id", None) != self.CASE_ID:
            raise ValueError("decision scope does not match this case")
        self.engine = decision_engine
        self.authenticator = authenticator
        self.profile = _PROFILES[self.CASE_ID]
        self._events: list[Any] = []
        self._receipts: list[ManagedIntentReceipt] = []
        self._event_ids: set[str] = set()
        self._sequences: dict[tuple[str, str, str, str], int] = {}
        self._receipt_ids: set[str] = set()
        self._receipt_sequence = 0
        self._rejected: list[str] = []

    def record(self, event: Any) -> bool:
        return self._with_rejection_latch(self._record_unlatched, event)

    def _record_unlatched(self, event: Any) -> bool:
        """Record a required event through the decision engine's verifier."""
        kind = _value(getattr(event, "kind", ""))
        if kind not in _POLICY or kind == "monitor_configuration":
            raise ValueError("event kind is not a native decision-engine observation")
        self._check_identity_and_sequence(event)
        if _value(getattr(event, "source_domain", "")) == "ctp_provider_callback":
            account_problem = self._provider_account_identity_problem(event)
            if account_problem:
                self._rejected.append(f"{event.event_id}:{account_problem}")
                return False
        if kind in {"order_accepted", "order_canceled"}:
            problems = _native_order_mismatches(kind, getattr(event, "fields", {}))
            if problems:
                self._rejected.extend(
                    f"{getattr(event, 'event_id', '')}:{problem}" for problem in problems
                )
                return False
        accepted = self.engine.record(event)
        if accepted:
            self._remember_event(event)
        else:
            self._rejected.append(f"{getattr(event, 'event_id', '')}:decision_engine_denied")
        return accepted

    def record_monitor_configuration(self, event: Any) -> bool:
        return self._with_rejection_latch(self._record_monitor_configuration_unlatched, event)

    def _record_monitor_configuration_unlatched(self, event: Any) -> bool:
        """Authenticate the case-local configuration event not admitted by the shared spec."""
        kind = _value(getattr(event, "kind", ""))
        if kind != "monitor_configuration":
            raise ValueError("only monitor_configuration is auxiliary evidence")
        self._check_identity_and_sequence(event)
        domain, callback = _POLICY[kind]
        if _value(getattr(event, "source_domain", "")) != domain:
            raise ValueError("monitor configuration must have monitor source domain")
        if getattr(event, "callback_name", None) != callback:
            raise ValueError("monitor configuration must not claim a provider callback")
        fields = getattr(event, "fields", {})
        if not isinstance(fields, Mapping):
            raise TypeError("monitor configuration fields must be a mapping")
        if (
            not _nonempty(fields.get("metric"))
            or not _is_positive_int(fields.get("threshold"))
            or not _sha256(fields.get("configuration_digest"))
            or not _sha256(fields.get("monitor_digest"))
        ):
            raise ValueError("monitor configuration is missing typed threshold/digest fields")
        if self.profile.get("repeat") and not _is_positive_number(fields.get("window_seconds")):
            raise ValueError("repeat configuration requires a positive observation window")
        if event.kind in self.engine.spec.required_kinds:
            if not self.engine.record(event):
                self._rejected.append(f"{event.event_id}:decision_engine_denied")
                return False
        elif not self._authenticate_event(event):
            self._rejected.append(f"{event.event_id}:monitor_configuration_auth_denied")
            return False
        self._remember_event(event)
        return True

    def record_supporting_observation(self, event: Any) -> bool:
        return self._with_rejection_latch(self._record_supporting_observation_unlatched, event)

    def _record_supporting_observation_unlatched(self, event: Any) -> bool:
        """Record an authenticated native order fact required by this candidate."""
        kind = _value(getattr(event, "kind", ""))
        if self.CASE_ID not in {"O01", "O02", "TH04", "TH06"} or kind != "order_accepted":
            raise ValueError("case does not permit this auxiliary native observation")
        self._check_identity_and_sequence(event)
        domain, callback = _POLICY[kind]
        if _value(getattr(event, "source_domain", "")) != domain:
            raise ValueError("supporting order fact must have provider callback source")
        if getattr(event, "callback_name", None) != callback:
            raise ValueError("supporting order fact has incorrect callback name")
        fields = getattr(event, "fields", {})
        if not isinstance(fields, Mapping) or any(
            not _nonempty(fields.get(name)) for name in _REQUIRED_FIELDS[kind]
        ):
            raise ValueError("supporting native order fact is missing required fields")
        generation = fields.get("connection_generation")
        if not _is_positive_int(generation):
            self._rejected.append(f"{event.event_id}:provider_connection_generation_required")
            return False
        previous_generations = {
            row.fields.get("connection_generation")
            for row in self._events
            if _value(getattr(row, "source_domain", "")) == "ctp_provider_callback"
            and isinstance(getattr(row, "fields", None), Mapping)
            and _is_positive_int(row.fields.get("connection_generation"))
        }
        if len(previous_generations) != 1 or generation not in previous_generations:
            self._rejected.append(
                f"{event.event_id}:provider_evidence_must_share_one_connection_generation"
            )
            return False
        account_problem = self._provider_account_identity_problem(event)
        if account_problem:
            self._rejected.append(f"{event.event_id}:{account_problem}")
            return False
        problems = _native_order_mismatches(kind, fields)
        if problems:
            self._rejected.extend(f"{event.event_id}:{problem}" for problem in problems)
            return False
        if event.kind in self.engine.spec.required_kinds:
            if not self.engine.record(event):
                self._rejected.append(f"{event.event_id}:decision_engine_denied")
                return False
        elif not self._authenticate_event(event):
            self._rejected.append(f"{event.event_id}:supporting_native_auth_denied")
            return False
        self._remember_event(event)
        return True

    def record_managed_receipt(self, receipt: ManagedIntentReceipt) -> bool:
        return self._with_rejection_latch(self._record_managed_receipt_unlatched, receipt)

    def _record_managed_receipt_unlatched(self, receipt: ManagedIntentReceipt) -> bool:
        """Accept only an authenticated managed-runtime request receipt."""
        if not isinstance(receipt, ManagedIntentReceipt):
            raise TypeError("managed request receipt must use ManagedIntentReceipt")
        if not _sha256(receipt.account_identity_sha256):
            self._rejected.append(
                f"{receipt.request_id}:managed_receipt_account_identity_sha256_required"
            )
            return False
        if (
            receipt.source != "managed_runtime_receipt"
            or not _nonempty(receipt.request_id)
            or not _nonempty(receipt.intent_id)
            or receipt.action not in self.profile["receipt_actions"]
            or receipt.dispatch_state not in {"dispatched", "blocked_pre_dispatch"}
            or not _nonempty(receipt.order_ref)
            or not _nonempty(receipt.instrument_id)
            or not _nonempty(receipt.repeat_key)
            or not _sha256(receipt.configuration_digest)
            or not _is_positive_int(receipt.threshold)
            or not _is_positive_number(receipt.window_seconds)
            or not _utc(receipt.occurred_at_utc)
            or not _is_positive_int(receipt.sequence)
            or not _sha256(receipt.evidence_sha256)
        ):
            raise ValueError("managed receipt shape or provenance is invalid")
        scope_account_digest = self._scope_account_identity_sha256()
        if scope_account_digest is None:
            self._rejected.append(f"{receipt.request_id}:account_identity_scope_binding_required")
            return False
        if receipt.account_identity_sha256.lower() != scope_account_digest:
            self._rejected.append(
                f"{receipt.request_id}:managed_receipt_account_identity_scope_mismatch"
            )
            return False
        if receipt.request_id in self._receipt_ids:
            raise ValueError("managed receipt request_id must be unique")
        if receipt.sequence <= self._receipt_sequence:
            raise ValueError("managed receipt sequence must increase")
        authenticate = getattr(self.authenticator, "authenticate_managed_receipt", None)
        if not callable(authenticate):
            self._rejected.append(f"{receipt.request_id}:managed_receipt_verifier_unavailable")
            return False
        proof = authenticate(receipt, self.engine.scope)
        if (
            proof is None
            or getattr(proof, "request_id", None) != receipt.request_id
            or str(getattr(proof, "evidence_sha256", "")).lower() != receipt.evidence_sha256.lower()
            or str(getattr(proof, "scope_sha256", "")).lower()
            != str(self.engine.scope.scope_sha256).lower()
            or getattr(proof, "source", None) != receipt.source
            or str(getattr(proof, "account_identity_sha256", "")).lower() != scope_account_digest
            or not _nonempty(getattr(proof, "verification_ref", None))
        ):
            self._rejected.append(f"{receipt.request_id}:managed_receipt_auth_denied")
            return False
        self._receipt_ids.add(receipt.request_id)
        self._receipt_sequence = receipt.sequence
        self._receipts.append(receipt)
        return True

    def evaluate(self, *, now_utc: datetime) -> ScenarioStateSnapshot:
        """Return REVIEW_REQUIRED at best; this API can never pass or dispatch."""
        missing: list[str] = []
        if self.authenticator is None:
            missing.append("trusted_authenticator_not_configured")
        if self._rejected:
            missing.append("rejected_evidence_present")
        base = self.engine.evaluate(now_utc=now_utc)
        allowed_inapplicable = set()
        if self.CASE_ID == "O03":
            # The shared spec omits login/front/tick kinds despite the generic
            # repeat-cancel rule requiring them; O03's static plan is order scoped.
            allowed_inapplicable.update(
                {"provider_session_not_ready", "fresh_valid_market_tick_required"}
            )
        if self.CASE_ID == "TH04":
            # The static plan defines a combined submit+cancel threshold, while
            # the generic engine currently counts canceled refs only.
            allowed_inapplicable.add("threshold_trigger_not_correlated_to_native_activity")
        missing.extend(item for item in base.missing_conditions if item not in allowed_inapplicable)
        if base.status == "BLOCKED" and not missing:
            missing.append("decision_engine_blocked")
        if not any(event.kind.value == "monitor_configuration" for event in self._events):
            missing.append("authenticated_monitor_configuration_required")
        if self._scope_account_identity_sha256() is None:
            missing.append("account_identity_scope_binding_required")
        config = self._last_event("monitor_configuration")
        if config is not None:
            missing.extend(self._configuration_mismatches(config))
        missing.extend(self._provider_coherence_mismatches(now_utc, config))
        if self.profile.get("repeat"):
            missing.extend(self._repeat_mismatches(config))
            if self.CASE_ID in {"O01", "O02", "O03"}:
                missing.extend(self._admission_mismatches())
        else:
            missing.extend(self._threshold_mismatches(config))
        status = "INCOMPLETE" if missing else "REVIEW_REQUIRED"
        return ScenarioStateSnapshot(
            case_id=self.CASE_ID,
            status=status,
            certification_pass=False,
            dispatch_permitted=False,
            source_authenticity_verified=False,
            missing_conditions=tuple(dict.fromkeys(missing)),
            rejected_evidence=tuple(self._rejected),
        )

    def _provider_coherence_mismatches(self, now_utc: datetime, config: Any) -> list[str]:
        provider_events = [
            event
            for event in self._events
            if _value(getattr(event, "source_domain", "")) == "ctp_provider_callback"
        ]
        if not provider_events:
            return ["native_provider_evidence_required"]

        problems: list[str] = []
        scope_account_digest = self._scope_account_identity_sha256()
        if scope_account_digest is None:
            problems.append("account_identity_scope_binding_required")
        identity_events = [
            event
            for event in provider_events
            if _value(getattr(event, "kind", ""))
            not in {"front_connected", "auth_success"}
        ]
        sessions = {getattr(event, "provider_session_id", "") for event in identity_events}
        trading_days = {getattr(event, "trading_day", "") for event in identity_events}
        if len(sessions) != 1 or not next(iter(sessions), ""):
            problems.append("provider_evidence_must_share_one_session")
        if len(trading_days) != 1 or not next(iter(trading_days), ""):
            problems.append("provider_evidence_must_share_one_trading_day")

        has_front = any(
            _value(getattr(event, "kind", "")) == "front_connected"
            for event in provider_events
        )
        has_auth = any(
            _value(getattr(event, "kind", "")) == "auth_success"
            for event in provider_events
        )
        login = self._last_event("login_success")
        if (has_front or has_auth) and login is None:
            problems.append("native_login_identity_required_after_front_or_auth")
        if login is not None:
            login_scope = (login.provider_session_id, login.trading_day)
            if not all(login_scope) or any(
                (event.provider_session_id, event.trading_day) != login_scope
                for event in identity_events
            ):
                problems.append("provider_callback_scope_must_match_native_login")

        generations = []
        for event in provider_events:
            fields = getattr(event, "fields", {})
            # AUTH/FRONT callbacks have no native account identity field. Their
            # account-scope pseudonym is local receive metadata with an explicit
            # local_ prefix; other legacy callback projections use the same
            # pseudonym under account_identity_sha256, which is compared only
            # with the sealed case scope and is never treated as provider proof.
            kind = _value(getattr(event, "kind", ""))
            digest_field = (
                "local_account_identity_sha256"
                if kind in {"auth_success", "front_connected", "front_disconnected"}
                else "account_identity_sha256"
            )
            account_digest = (
                fields.get(digest_field) if isinstance(fields, Mapping) else None
            )
            if not _sha256(account_digest):
                problems.append("local_account_scope_fingerprint_required")
            elif scope_account_digest and account_digest.lower() != scope_account_digest:
                problems.append("local_account_scope_fingerprint_mismatch")
            generation = (
                fields.get("connection_generation") if isinstance(fields, Mapping) else None
            )
            if not _is_positive_int(generation):
                problems.append("provider_connection_generation_required")
                continue
            generations.append(generation)
        if len(set(generations)) > 1:
            problems.append("provider_evidence_must_share_one_connection_generation")

        cutoff = _as_utc_datetime(now_utc)
        if cutoff is None:
            problems.append("evaluation_time_must_be_utc")
        else:
            event_times = [
                _utc(getattr(event, "occurred_at_utc", None)) for event in provider_events
            ]
            if any(item is None for item in event_times):
                problems.append("provider_event_timestamp_required")
            else:
                normalized_times = [item for item in event_times if item is not None]
                if any(item > cutoff for item in normalized_times):
                    problems.append("provider_event_from_future")
                if any(cutoff - item > _MAX_PROVIDER_EVENT_AGE for item in normalized_times):
                    problems.append("provider_event_stale_at_evaluation")
                if max(normalized_times) - min(normalized_times) > _MAX_PROVIDER_EVENT_AGE:
                    problems.append("provider_evidence_exceeds_five_minute_window")

        if self.CASE_ID in {"O01", "O02", "TH02"}:
            problems.extend(self._subscribed_instrument_mismatches())

        problems.extend(self._receipt_instrument_mismatches())

        receipts = sorted(self._receipts, key=lambda row: row.sequence)
        if cutoff is not None:
            receipt_times = [_utc(row.occurred_at_utc) for row in receipts]
            if any(item is None for item in receipt_times):
                problems.append("managed_receipt_timestamp_required")
            elif any(item > cutoff for item in receipt_times if item is not None):
                problems.append("managed_receipt_from_future")
            elif any(
                cutoff - item > _MAX_PROVIDER_EVENT_AGE
                for item in receipt_times
                if item is not None
            ):
                problems.append("managed_receipt_stale_at_evaluation")

        problems.extend(self._case_event_time_mismatches(config, receipts, cutoff))
        return problems

    def _subscribed_instrument_mismatches(self) -> list[str]:
        subscription = self._last_event("market_subscription_ack")
        tick = self._last_event("market_tick")
        accepted = [event for event in self._events if event.kind.value == "order_accepted"]
        if subscription is None or tick is None:
            return ["current_subscription_and_market_tick_required"]
        instrument = subscription.fields.get("instrument_id")
        if (
            not _nonempty(instrument)
            or tick.fields.get("instrument_id") != instrument
            or any(event.fields.get("instrument_id") != instrument for event in accepted)
        ):
            return ["native_order_must_match_current_subscribed_tick_instrument"]

        front = self._last_event("front_connected")
        login = self._last_event("login_success")
        auth = self._last_event("auth_success")
        if front is None or login is None or auth is None:
            return ["current_authenticated_provider_session_required"]
        auth_time = _utc(auth.occurred_at_utc)
        login_time = _utc(login.occurred_at_utc)
        front_time = _utc(front.occurred_at_utc)
        subscription_time = _utc(subscription.occurred_at_utc)
        tick_time = _utc(tick.occurred_at_utc)
        if any(
            item is None
            for item in (auth_time, login_time, front_time, subscription_time, tick_time)
        ):
            return ["provider_session_event_timestamps_required"]
        if not front_time <= auth_time <= login_time <= subscription_time <= tick_time:
            return ["provider_auth_login_front_subscription_tick_order_invalid"]
        if any(_utc(event.occurred_at_utc) < tick_time for event in accepted):
            return ["native_order_must_follow_current_market_tick"]
        return []

    def _receipt_instrument_mismatches(self) -> list[str]:
        provider_orders = [
            event
            for event in self._events
            if event.kind.value in {"order_accepted", "order_canceled"}
        ]
        problems: list[str] = []
        subscription = self._last_event("market_subscription_ack")
        tick = self._last_event("market_tick")
        subscribed_instrument = (
            subscription.fields.get("instrument_id")
            if subscription is not None and tick is not None
            else None
        )
        for receipt in self._receipts:
            matching = [
                event
                for event in provider_orders
                if event.fields.get("order_ref") == receipt.order_ref
            ]
            if not matching:
                problems.append("managed_receipt_native_order_instrument_unresolved")
                continue
            if any(
                event.fields.get("instrument_id") != receipt.instrument_id for event in matching
            ):
                problems.append("managed_receipt_instrument_must_match_native_order_ref")
            if subscribed_instrument is not None and receipt.instrument_id != subscribed_instrument:
                problems.append("managed_receipt_instrument_must_match_current_subscription")
        return problems

    def _scope_account_identity_sha256(self) -> str | None:
        value = getattr(self.engine.scope, "account_identity_sha256", "")
        return value.lower() if _sha256(value) else None

    def _with_rejection_latch(self, operation: Any, evidence: Any) -> bool:
        try:
            return operation(evidence)
        except Exception as exc:
            evidence_id = self._safe_evidence_identifier(evidence)
            rejection = f"{evidence_id or 'unknown-evidence'}:rejected_{type(exc).__name__}"
            if rejection not in self._rejected:
                self._rejected.append(rejection)
            raise

    @staticmethod
    def _safe_evidence_identifier(evidence: Any) -> str | None:
        for attribute in ("event_id", "request_id"):
            try:
                value = getattr(evidence, attribute, None)
            except Exception:
                continue
            if type(value) is str and value.strip():
                return value
        return None

    def _provider_account_identity_problem(self, event: Any) -> str | None:
        scope_digest = self._scope_account_identity_sha256()
        if scope_digest is None:
            return "account_identity_scope_binding_required"
        fields = getattr(event, "fields", {})
        kind = _value(getattr(event, "kind", ""))
        digest_field = (
            "local_account_identity_sha256"
            if kind in {"auth_success", "front_connected", "front_disconnected"}
            else "account_identity_sha256"
        )
        event_digest = (
            fields.get(digest_field) if isinstance(fields, Mapping) else None
        )
        if not _sha256(event_digest):
            return "local_account_scope_fingerprint_required"
        if event_digest.lower() != scope_digest:
            return "local_account_scope_fingerprint_mismatch"
        return None

    def _case_event_time_mismatches(
        self, config: Any, receipts: list[ManagedIntentReceipt], cutoff: datetime | None
    ) -> list[str]:
        if cutoff is None:
            return []
        problems: list[str] = []
        by_kind: dict[str, list[Any]] = {}
        for event in self._events:
            by_kind.setdefault(event.kind.value, []).append(event)

        def when(event: Any) -> datetime | None:
            return _utc(getattr(event, "occurred_at_utc", None))

        receipt_times = [_utc(row.occurred_at_utc) for row in receipts]
        valid_receipt_times = [item for item in receipt_times if item is not None]
        earliest_receipt = min(valid_receipt_times) if valid_receipt_times else None
        latest_receipt = max(valid_receipt_times) if valid_receipt_times else None

        if self.CASE_ID in {"O01", "O02", "TH06"} and receipts:
            accepted = by_kind.get("order_accepted", [])
            if not accepted or not valid_receipt_times:
                problems.append("repeat_order_requires_fresh_native_acceptance_and_receipts")
            elif not any(
                row.order_ref in {event.fields.get("order_ref") for event in accepted}
                and earliest_receipt <= when(event) <= latest_receipt
                for row in receipts
                for event in accepted
                if when(event) is not None
            ):
                problems.append("native_order_acceptance_must_fall_within_managed_repeat_window")

        if self.CASE_ID == "O02":
            position = self._last_event("position_query")
            if (
                position is None
                or earliest_receipt is None
                or when(position) is None
                or when(position) > earliest_receipt
            ):
                problems.append("baseline_position_must_precede_close_intent_receipts")

        if self.CASE_ID == "O03":
            accepted = by_kind.get("order_accepted", [])
            query = self._last_event("order_query")
            if (
                not accepted
                or query is None
                or earliest_receipt is None
                or any(when(row) is None or when(row) > when(query) for row in accepted)
                or when(query) is None
                or when(query) > earliest_receipt
            ):
                problems.append("open_order_acceptance_and_query_must_precede_cancel_intents")

        if self.CASE_ID == "TH02":
            for receipt in receipts:
                matches = [
                    event
                    for event in by_kind.get("order_accepted", [])
                    if event.fields.get("order_ref") == receipt.order_ref
                ]
                if (
                    receipt.action == "open"
                    and receipt.dispatch_state == "dispatched"
                    and not any(
                        when(event) is not None and when(event) >= _utc(receipt.occurred_at_utc)
                        for event in matches
                    )
                ):
                    problems.append(
                        "threshold_order_acceptance_must_follow_matching_submit_receipt"
                    )

        if self.CASE_ID == "TH04":
            native_by_kind = {
                "open": by_kind.get("order_accepted", []),
                "cancel": by_kind.get("order_canceled", []),
            }
            for receipt in receipts:
                matching = [
                    event
                    for event in native_by_kind.get(receipt.action, [])
                    if event.fields.get("order_ref") == receipt.order_ref
                ]
                if receipt.dispatch_state == "dispatched" and not any(
                    when(event) is not None and when(event) >= _utc(receipt.occurred_at_utc)
                    for event in matching
                ):
                    problems.append(
                        "combined_threshold_native_event_must_follow_matching_managed_receipt"
                    )

        if self.CASE_ID in {"TH02", "TH04", "TH06"}:
            trigger = self._last_event("monitor_trigger")
            evidence_times = [
                item
                for item in [*valid_receipt_times]
                + [
                    when(event)
                    for event in self._events
                    if event.kind.value in {"order_accepted", "order_canceled"}
                ]
                if item is not None
            ]
            if trigger is None or (
                evidence_times and when(trigger) is not None and when(trigger) < max(evidence_times)
            ):
                problems.append("threshold_trigger_must_follow_its_managed_and_native_sources")
        elif receipts:
            guard = self._last_event("repeat_guard")
            if (
                guard is None
                or latest_receipt is None
                or when(guard) is None
                or when(guard) < latest_receipt
            ):
                problems.append("repeat_guard_must_follow_managed_repeat_receipts")

        if config is not None:
            config_time = when(config)
            monitor = self._last_event("monitor_trigger") or self._last_event("repeat_guard")
            monitor_time = when(monitor) if monitor is not None else None
            if config_time is not None and monitor_time is not None and config_time > monitor_time:
                problems.append("monitor_configuration_must_precede_its_observation")
        return problems

    def _configuration_mismatches(self, config: Any) -> list[str]:
        fields = config.fields
        expected_metric = self.profile.get("repeat_metric", self.profile.get("threshold_metric"))
        problems = []
        if fields.get("metric") != expected_metric:
            problems.append("case_specific_monitor_metric_mismatch")
        expected_threshold = self.profile.get("threshold")
        if expected_threshold is not None and fields.get("threshold") != expected_threshold:
            problems.append("configured_threshold_does_not_match_static_case_plan")
        if self.profile.get("repeat") and not _is_positive_number(fields.get("window_seconds")):
            problems.append("configured_repeat_window_missing")
        return problems

    def _repeat_mismatches(self, config: Any) -> list[str]:
        if config is None:
            return ["authenticated_monitor_configuration_required"]
        guard = self._last_event("repeat_guard")
        problems: list[str] = []
        receipts = sorted(self._receipts, key=lambda row: row.sequence)
        threshold = config.fields.get("threshold") if config else None
        window = config.fields.get("window_seconds") if config else None
        config_digest = config.fields.get("configuration_digest") if config else None
        if len(receipts) < 2:
            problems.append("two_managed_intent_receipts_required")
            return problems
        if not guard:
            return [*problems, "authenticated_repeat_guard_required"]
        fields = guard.fields
        expected_action = self.profile["action"]
        if fields.get("action_kind") != expected_action:
            problems.append("repeat_guard_action_mismatch")
        intent_ids = {row.intent_id for row in receipts}
        order_refs = {row.order_ref for row in receipts}
        repeat_keys = {row.repeat_key for row in receipts}
        if len(intent_ids) != 1 or fields.get("intent_id") not in intent_ids:
            problems.append("repeat_guard_not_bound_to_one_managed_intent")
        if len(order_refs) != 1 or tuple(fields.get("order_refs", ())) != tuple(sorted(order_refs)):
            problems.append("repeat_guard_order_ref_mismatch")
        if len(repeat_keys) != 1 or fields.get("repeat_key") not in repeat_keys:
            problems.append("repeat_guard_key_not_bound_to_receipts")
        request_ids = tuple(row.request_id for row in receipts)
        if tuple(fields.get("source_request_ids", ())) != request_ids:
            problems.append("repeat_guard_request_source_mismatch")
        if fields.get("repeat_count") != len(receipts) or len(receipts) < threshold:
            problems.append("repeat_guard_count_does_not_match_receipt_count")
        if fields.get("threshold") != threshold or fields.get("window_seconds") != window:
            problems.append("repeat_guard_threshold_or_window_mismatch")
        if fields.get("configuration_digest") != config_digest:
            problems.append("repeat_guard_configuration_digest_mismatch")
        if not _sha256(fields.get("monitor_digest")) or fields.get(
            "monitor_digest"
        ) != config.fields.get("monitor_digest"):
            problems.append("repeat_guard_monitor_digest_mismatch")
        if any(row.configuration_digest != config_digest for row in receipts):
            problems.append("managed_receipt_configuration_digest_mismatch")
        if any(row.threshold != threshold or row.window_seconds != window for row in receipts):
            problems.append("managed_receipt_threshold_or_window_mismatch")
        times = [_utc(row.occurred_at_utc) for row in receipts]
        if None in times or max(times) - min(times) > timedelta(seconds=float(window)):
            problems.append("managed_receipts_exceed_repeat_window")
        states = {row.dispatch_state for row in receipts}
        if not {"dispatched", "blocked_pre_dispatch"}.issubset(states):
            problems.append("repeat_requires_dispatched_and_pre_dispatch_blocked_receipts")
        if self.CASE_ID in {"O01", "O02", "O03", "TH06"} and len(order_refs) != 1:
            problems.append("repeat_attempts_must_target_same_order_ref")
        problems.extend(self._native_receipt_correlation(receipts))
        return problems

    def _native_receipt_correlation(self, receipts: list[ManagedIntentReceipt]) -> list[str]:
        problems: list[str] = []
        refs = {row.order_ref for row in receipts}
        accepted = {
            event.fields.get("order_ref")
            for event in self._events
            if event.kind.value == "order_accepted"
        }
        canceled = {
            event.fields.get("order_ref")
            for event in self._events
            if event.kind.value == "order_canceled"
        }
        if self.CASE_ID in {"O01", "O02", "TH06"} and not refs.intersection(accepted):
            problems.append("managed_submit_receipt_not_correlated_to_native_order")
        if self.CASE_ID == "O02":
            position = self._last_event("position_query")
            if not position or position.fields.get("phase") != "baseline":
                problems.append("close_repeat_requires_native_baseline_position")
            elif any(
                event.kind.value == "order_accepted"
                and event.fields.get("instrument_id") != position.fields.get("instrument_id")
                for event in self._events
            ):
                problems.append("close_receipt_and_position_instrument_mismatch")
        if self.CASE_ID == "O03":
            query = self._last_event("order_query")
            open_refs = set(query.fields.get("open_order_refs", ())) if query else set()
            if not refs.intersection(accepted) or not refs.intersection(open_refs):
                problems.append("repeat_cancel_target_not_native_open_order")
            if not refs.intersection(canceled) and not any(
                row.dispatch_state == "dispatched" for row in receipts
            ):
                # A provider cancel callback may be absent when the monitor
                # blocks a retry; at least the dispatched receipt is required.
                problems.append("repeat_cancel_has_no_dispatched_managed_request")
        return problems

    def _admission_mismatches(self) -> list[str]:
        admission = self._last_event("order_admission")
        if admission is None:
            return ["authenticated_case_bound_admission_required"]
        fields = admission.fields
        intents = {row.intent_id for row in self._receipts}
        if (
            fields.get("case_id") != self.CASE_ID
            or fields.get("intent_kind") != self.profile["action"]
            or fields.get("intent_id") not in intents
            or len(intents) != 1
            or fields.get("approval_state") != "REVIEW_ONLY"
            or fields.get("dispatch_permitted") is not False
            or not _nonempty(fields.get("approval_ref"))
        ):
            return ["managed_admission_not_bound_to_the_receipt_intent"]
        try:
            if float(fields.get("maximum_quantity")) <= 0:
                return ["managed_admission_quantity_must_be_positive"]
        except (TypeError, ValueError, OverflowError):
            return ["managed_admission_quantity_must_be_positive"]
        return []

    def _threshold_mismatches(self, config: Any) -> list[str]:
        trigger = self._last_event("monitor_trigger")
        receipts = sorted(self._receipts, key=lambda row: row.sequence)
        if config is None or trigger is None:
            return ["authenticated_threshold_configuration_and_trigger_required"]
        problems: list[str] = []
        cfg, observed = config.fields, trigger.fields
        dispatched = [row for row in receipts if row.dispatch_state == "dispatched"]
        expected_actions = self.profile["count_actions"]
        if self.CASE_ID == "TH06":
            counted = receipts
        else:
            counted = [row for row in dispatched if row.action in expected_actions]
        if not counted:
            problems.append("managed_dispatched_receipts_required_for_threshold_count")
        request_ids = tuple(row.request_id for row in counted)
        if observed.get("metric") != cfg.get("metric"):
            problems.append("threshold_trigger_metric_mismatch")
        if observed.get("threshold") != cfg.get("threshold"):
            problems.append("threshold_trigger_threshold_mismatch")
        if observed.get("observed_value") != len(counted):
            problems.append("threshold_count_does_not_match_managed_receipts")
        if (
            observed.get("source_request_ids") is None
            or tuple(observed.get("source_request_ids", ())) != request_ids
        ):
            problems.append("threshold_trigger_request_source_mismatch")
        if observed.get("configuration_digest") != cfg.get("configuration_digest"):
            problems.append("threshold_trigger_configuration_digest_mismatch")
        if observed.get("monitor_digest") != cfg.get("monitor_digest"):
            problems.append("threshold_trigger_monitor_digest_mismatch")
        if not _sha256(observed.get("monitor_digest")):
            problems.append("threshold_trigger_monitor_digest_invalid")
        if any(row.configuration_digest != cfg.get("configuration_digest") for row in counted):
            problems.append("threshold_receipt_configuration_digest_mismatch")
        if any(row.threshold != cfg.get("threshold") for row in counted):
            problems.append("threshold_receipt_effective_threshold_mismatch")
        native_ids = tuple(
            event.event_id
            for event in self._events
            if event.kind.value
            in (
                {"order_accepted"}
                if self.CASE_ID == "TH02"
                else {"order_accepted", "order_canceled"}
            )
        )
        source_ids_field = (
            "source_native_event_ids" if self.CASE_ID == "TH04" else "source_event_ids"
        )
        expected_native_ids = tuple(observed.get(source_ids_field, ()))
        if expected_native_ids != native_ids:
            problems.append("threshold_trigger_native_event_source_mismatch")
        if self.CASE_ID == "TH02":
            native_refs = {
                event.fields.get("order_ref")
                for event in self._events
                if event.kind.value == "order_accepted"
            }
            if native_refs != {row.order_ref for row in counted}:
                problems.append("submit_threshold_refs_do_not_match_native_orders")
        elif self.CASE_ID == "TH04":
            if len(counted) != self.profile["threshold"]:
                problems.append("combined_submit_cancel_count_does_not_reach_configured_threshold")
            if not any(event.kind.value == "order_canceled" for event in self._events):
                problems.append("combined_threshold_requires_native_cancel_callback")
            submit_refs = {row.order_ref for row in counted if row.action == "open"}
            cancel_refs = {row.order_ref for row in counted if row.action == "cancel"}
            native_submit_refs = {
                event.fields.get("order_ref")
                for event in self._events
                if event.kind.value == "order_accepted"
            }
            native_cancel_refs = {
                event.fields.get("order_ref")
                for event in self._events
                if event.kind.value == "order_canceled"
            }
            if submit_refs != native_submit_refs or cancel_refs != native_cancel_refs:
                problems.append("combined_threshold_receipts_do_not_match_native_order_refs")
        elif self.CASE_ID == "TH06":
            # Repeat counts are based on attempted managed requests; a blocked
            # retry must remain in the monitor's source set, unlike normal
            # dispatched order-count thresholds.
            repeat_ids = tuple(row.request_id for row in receipts)
            guard = self._last_event("repeat_guard")
            if tuple(observed.get("source_request_ids", ())) != repeat_ids:
                problems.append("repeat_threshold_source_must_include_all_managed_attempts")
            if not guard or guard.fields.get("repeat_count") != len(receipts):
                problems.append("repeat_threshold_count_not_bound_to_repeat_guard")
            if observed.get("observed_value") != len(receipts):
                problems.append("repeat_threshold_value_not_bound_to_attempt_count")
        return problems

    def _authenticate_event(self, event: Any) -> bool:
        authenticate = getattr(self.authenticator, "authenticate", None)
        if not callable(authenticate):
            return False
        proof = authenticate(event, self.engine.scope)
        return bool(
            proof is not None
            and getattr(proof, "event_id", None) == event.event_id
            and str(getattr(proof, "evidence_sha256", "")).lower()
            == str(event.evidence_sha256).lower()
            and str(getattr(proof, "scope_sha256", "")).lower()
            == str(self.engine.scope.scope_sha256).lower()
            and _value(getattr(proof, "trust_domain", "")) == _value(event.source_domain)
            and str(getattr(proof, "account_identity_sha256", "")).lower()
            == (self._scope_account_identity_sha256() or "")
            and _nonempty(getattr(proof, "verification_ref", None))
        )

    def _check_identity_and_sequence(self, event: Any) -> None:
        kind = _value(getattr(event, "kind", ""))
        event_id = getattr(event, "event_id", None)
        digest = getattr(event, "evidence_sha256", None)
        stream = getattr(event, "stream_id", None)
        sequence = getattr(event, "sequence", None)
        if kind not in _POLICY or not _nonempty(event_id) or not _sha256(digest):
            raise ValueError("observation id, kind, or evidence digest is invalid")
        if not _nonempty(stream) or not _is_positive_int(sequence):
            raise ValueError("observation stream and sequence are required")
        if event_id in self._event_ids:
            raise ValueError("observation event_id must be unique")
        domain = _value(getattr(event, "source_domain", ""))
        provider_session = getattr(event, "provider_session_id", "")
        trading_day = getattr(event, "trading_day", "")
        fields = getattr(event, "fields", {})
        provider_identity_fields = (
            "provider_front_id",
            "provider_session_id",
            "trading_day",
        )
        is_payloadless_front = (
            domain == "ctp_provider_callback"
            and kind == "front_connected"
            and getattr(event, "callback_name", None) == "OnFrontConnected"
        )
        is_auth_callback = (
            domain == "ctp_provider_callback"
            and kind == "auth_success"
            and getattr(event, "callback_name", None) == "OnRspAuthenticate"
        )
        if is_payloadless_front or is_auth_callback:
            has_impossible_identity = (
                getattr(event, "provider_front_id", None) is not None
                or bool(provider_session)
                or bool(trading_day)
                or not isinstance(fields, Mapping)
                or any(fields.get(name) not in (None, "") for name in provider_identity_fields)
            )
            if has_impossible_identity:
                callback = "OnFrontConnected" if is_payloadless_front else "OnRspAuthenticate"
                raise ValueError(f"{callback} cannot claim native login identity fields")
        elif domain == "ctp_provider_callback" and (not provider_session or not trading_day):
            raise ValueError("native callback requires provider session and trading day")
        if domain == "ctp_provider_callback" and kind not in {
            "front_connected",
            "auth_success",
            "login_success",
        }:
            login = self._last_event("login_success")
            if login is not None and (provider_session, trading_day) != (
                login.provider_session_id,
                login.trading_day,
            ):
                raise ValueError("native callback session/day must match native login identity")
        if _utc(getattr(event, "occurred_at_utc", None)) is None:
            raise ValueError("observation timestamp must be UTC")
        key = (domain, stream, provider_session, trading_day)
        if sequence <= self._sequences.get(key, 0):
            raise ValueError("observation sequence must increase within source stream")

    def _remember_event(self, event: Any) -> None:
        domain = _value(event.source_domain)
        key = (domain, event.stream_id, event.provider_session_id, event.trading_day)
        self._sequences[key] = event.sequence
        self._event_ids.add(event.event_id)
        self._events.append(event)

    def _last_event(self, kind: str) -> Any | None:
        return next((row for row in reversed(self._events) if row.kind.value == kind), None)


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_positive_number(value: Any) -> bool:
    if not isinstance(value, (int, float, Decimal)) or isinstance(value, bool):
        return False
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return False
    return number.is_finite() and number > 0


def _as_utc_datetime(value: Any) -> datetime | None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        return None
    return value.astimezone(timezone.utc)


def _native_order_mismatches(kind: str, fields: Any) -> list[str]:
    if not isinstance(fields, Mapping):
        return ["native_order_fields_must_be_mapping"]
    status = fields.get("status")
    remaining = fields.get("remaining_quantity")
    if not _nonempty(status):
        return ["native_order_status_required"]
    try:
        remaining_quantity = Decimal(str(remaining))
    except (InvalidOperation, TypeError, ValueError):
        return ["native_order_remaining_quantity_must_be_finite_decimal"]
    if not remaining_quantity.is_finite():
        return ["native_order_remaining_quantity_must_be_finite_decimal"]
    normalized_status = status.strip().lower()
    if kind == "order_accepted":
        problems = []
        if normalized_status not in {"accepted", "working"}:
            problems.append("native_order_accepted_status_invalid")
        if remaining_quantity <= 0:
            problems.append("native_order_accepted_remaining_quantity_must_be_positive")
        return problems
    if kind == "order_canceled":
        problems = []
        if normalized_status not in {"canceled", "cancelled"}:
            problems.append("native_order_cancelled_status_invalid")
        if remaining_quantity < 0:
            problems.append("native_order_cancelled_remaining_quantity_must_not_be_negative")
        return problems
    return []
