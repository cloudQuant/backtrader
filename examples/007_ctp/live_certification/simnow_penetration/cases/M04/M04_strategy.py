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
    NativeObservation,
    ObservationAuthenticator,
    ObservationKind,
)

CASE_ID = "M04"
CASE_NAME = "Order-submission count"
CASE_PLAN = {
    "evidence": (
        "Count real monitor.log order_submit_request records and distinct provider order references; retain monitoring_summary and provider acknowledgements.",
        "Reconcile each submitted order with its cancellation/terminal status and the final open-order and position snapshots.",
    ),
    "actions": (
        "Under the reviewed per-case budget, submit up to three separately identified minimum-size open limit orders at bounded quote-relative prices.",
        "Cancel each acknowledged order and compare the durable monitor count with provider order records; stop on any fill or risk-limit event.",
    ),
}


_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


class _FrozenRefs(set):
    """Read-only empty set accepted by the shared empty-order-query contract."""

    def _deny(self, *args, **kwargs):
        raise TypeError("provider reference snapshot is immutable")

    add = clear = difference_update = discard = intersection_update = pop = remove = (
        symmetric_difference_update
    ) = update = _deny
    __iand__ = __ior__ = __isub__ = __ixor__ = _deny


def _copy_event(event: NativeObservation) -> NativeObservation:
    if not isinstance(event.fields, Mapping):
        raise DecisionError("observation fields must be a mapping")
    fields = {}
    for key, value in event.fields.items():
        if not isinstance(key, str):
            raise DecisionError("observation field names must be strings")
        if isinstance(value, (str, bool, int, float, type(None))):
            fields[key] = value
        elif key == "open_order_refs" and isinstance(value, (tuple, list, set)) and not value:
            fields[key] = _FrozenRefs()
        elif isinstance(value, (tuple, list, set)) and all(
            isinstance(item, (str, bool, int, float, type(None))) for item in value
        ):
            fields[key] = tuple(value)
        else:
            raise DecisionError("observation fields must contain immutable scalar facts")
    return replace(event, fields=MappingProxyType(fields))


class M04Strategy(CaseIntentDecisionEngine):
    """Require monitor request counts to reconcile to runtime and provider facts."""

    def __init__(self, plan, scope, authenticator):
        super().__init__(plan, scope, authenticator)
        kinds = (
            ObservationKind.AUTH_SUCCESS,
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_SUBSCRIPTION_ACK,
            ObservationKind.MARKET_TICK,
            ObservationKind.ORDER_ADMISSION,
            ObservationKind.ORDER_SUBMIT_RECEIPT,
            ObservationKind.ORDER_ACCEPTED,
            ObservationKind.ORDER_CANCELED,
            ObservationKind.ORDER_QUERY,
            ObservationKind.POSITION_QUERY,
            ObservationKind.MONITOR_LOG,
        )
        self.spec = replace(
            CASE_INTENT_SPECS[CASE_ID],
            required_kinds=kinds,
            rule="local_submit_count",
        )

    def record(self, event: NativeObservation) -> bool:
        return super().record(_copy_event(event))

    def _missing(self, now: datetime) -> tuple[str, ...]:
        missing = list(super()._missing(now))
        if not self._session_ready():
            missing.append("provider_auth_login_front_and_subscription_success_required")
        if not self._fresh_tick(now):
            missing.append("fresh_valid_market_tick_required")
        admission = self._last(ObservationKind.ORDER_ADMISSION)
        if not admission or admission.fields.get("maximum_quantity") != 1:
            missing.append("one_lot_review_only_case_admission_required")

        receipts = self._all(ObservationKind.ORDER_SUBMIT_RECEIPT)
        logs = self._all(ObservationKind.MONITOR_LOG)
        accepted = self._all(ObservationKind.ORDER_ACCEPTED)
        canceled = self._all(ObservationKind.ORDER_CANCELED)
        if not 1 <= len(receipts) <= 3:
            missing.append("one_to_three_bounded_submit_request_receipts_required")
        request_ids = [item.fields.get("request_id") for item in receipts]
        order_refs = [item.fields.get("order_ref") for item in receipts]
        if (
            any(not isinstance(value, str) or not value for value in request_ids)
            or len(set(request_ids)) != len(request_ids)
            or any(not isinstance(value, str) or not value for value in order_refs)
            or len(set(order_refs)) != len(order_refs)
        ):
            missing.append("submit_receipts_must_have_distinct_request_and_provider_refs")
        logs_by_request = {item.fields.get("request_id"): item for item in logs}
        accepted_by_ref = {item.fields.get("order_ref"): item for item in accepted}
        canceled_by_ref = {item.fields.get("order_ref"): item for item in canceled}
        for index, receipt in enumerate(receipts, 1):
            request_id = receipt.fields.get("request_id")
            ref = receipt.fields.get("order_ref")
            trace = receipt.fields.get("trace_id")
            monitor = logs_by_request.get(request_id)
            ack = accepted_by_ref.get(ref)
            terminal = canceled_by_ref.get(ref)
            if (
                receipt.fields.get("dispatch_state") != "submitted"
                or not trace
                or not monitor
                or monitor.fields.get("event_name") != "order_submit_request"
                or monitor.fields.get("metric") != "submit_count"
                or monitor.fields.get("count") != index
                or monitor.fields.get("request_receipt_event_id") != receipt.event_id
                or monitor.fields.get("order_ref") != ref
                or monitor.fields.get("trace_id") != trace
                or not _HEX64.fullmatch(str(monitor.fields.get("monitor_digest", "")))
            ):
                missing.append(f"submit_request_{index}_must_match_typed_monitor_receipt")
            if not ack or ack.fields.get("status") not in {"accepted", "working"}:
                missing.append(f"submit_request_{index}_must_match_native_order_acknowledgement")
            if (
                monitor
                and ack
                and not (
                    _utc(receipt.occurred_at_utc)
                    <= _utc(monitor.occurred_at_utc)
                    <= _utc(ack.occurred_at_utc)
                )
            ):
                missing.append(f"submit_request_{index}_receipt_monitor_and_ack_order_invalid")
            if not terminal or terminal.fields.get("status") not in {"canceled", "cancelled"}:
                missing.append(f"submit_request_{index}_must_have_native_cancel_reconciliation")
            if terminal and ack and terminal.sequence <= ack.sequence:
                missing.append(f"submit_request_{index}_cancel_must_follow_native_acceptance")
        if (
            len(logs) != len(receipts)
            or len(accepted) != len(receipts)
            or len(canceled) != len(receipts)
        ):
            missing.append("submit_monitor_ack_and_cancel_cardinalities_must_match")
        order_queries = self._all(ObservationKind.ORDER_QUERY)
        position_queries = self._all(ObservationKind.POSITION_QUERY)
        if not order_queries or (
            order_queries[-1].fields.get("open_order_refs")
            or order_queries[-1].sequence <= max((item.sequence for item in canceled), default=0)
        ):
            missing.append("final_provider_order_query_must_be_empty_after_all_cancels")
        if not position_queries or (
            position_queries[-1].fields.get("phase") != "final"
            or position_queries[-1].fields.get("closeable_quantity") != 0
            or (order_queries and position_queries[-1].sequence <= order_queries[-1].sequence)
        ):
            missing.append("final_provider_position_snapshot_must_be_zero_after_order_query")
        return tuple(dict.fromkeys(missing))


def create_strategy(
    plan: DescriptiveCasePlan,
    scope: DecisionScope,
    authenticator: ObservationAuthenticator | None,
) -> M04Strategy:
    return M04Strategy(plan, scope, authenticator)


def _utc(value: str):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
