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

CASE_ID = "M05"
CASE_NAME = "Cancel-request count"
CASE_PLAN = {
    "evidence": (
        "Count real monitor.log order_cancel_request records by broker order reference; retain provider cancel acknowledgements and monitoring_summary.",
        "Reconcile all case orders against a final provider open-order query and position snapshot.",
    ),
    "actions": (
        "Submit up to three separately identified minimum-size open limit orders within the approved budget.",
        "Cancel each only after a real provider order reference is available, then reconcile the recorded request count and terminal states.",
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


class M05Strategy(CaseIntentDecisionEngine):
    """Correlate cancel monitor receipts to prior opens and native terminal state."""

    def __init__(self, plan, scope, authenticator):
        super().__init__(plan, scope, authenticator)
        kinds = (
            ObservationKind.AUTH_SUCCESS,
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_SUBSCRIPTION_ACK,
            ObservationKind.ORDER_ACCEPTED,
            ObservationKind.ORDER_QUERY,
            ObservationKind.ORDER_ADMISSION,
            ObservationKind.ORDER_SUBMIT_RECEIPT,
            ObservationKind.ORDER_CANCELED,
            ObservationKind.POSITION_QUERY,
            ObservationKind.MONITOR_LOG,
        )
        self.spec = replace(
            CASE_INTENT_SPECS[CASE_ID],
            required_kinds=kinds,
            rule="local_cancel_count",
        )

    def record(self, event: NativeObservation) -> bool:
        return super().record(_copy_event(event))

    def _missing(self, now: datetime) -> tuple[str, ...]:
        missing = list(super()._missing(now))
        if not self._session_ready():
            missing.append("provider_auth_login_front_and_subscription_success_required")
        admission = self._last(ObservationKind.ORDER_ADMISSION)
        if not admission or admission.fields.get("maximum_quantity") != 1:
            missing.append("one_lot_review_only_cancel_admission_required")

        submissions = self._all(ObservationKind.ORDER_SUBMIT_RECEIPT)
        accepted = self._all(ObservationKind.ORDER_ACCEPTED)
        queries = self._all(ObservationKind.ORDER_QUERY)
        cancel_logs = [
            item
            for item in self._all(ObservationKind.MONITOR_LOG)
            if item.fields.get("event_name") == "order_cancel_request"
        ]
        canceled = self._all(ObservationKind.ORDER_CANCELED)
        if not 1 <= len(cancel_logs) <= 3:
            missing.append("one_to_three_bounded_cancel_monitor_receipts_required")
        submission_by_ref = {item.fields.get("order_ref"): item for item in submissions}
        accepted_by_ref = {item.fields.get("order_ref"): item for item in accepted}
        if len(submissions) != len(accepted) or any(
            item.fields.get("dispatch_state") != "submitted"
            or not item.fields.get("request_id")
            or not item.fields.get("trace_id")
            for item in submissions
        ):
            missing.append("every_cancel_target_must_have_a_managed_submit_receipt_and_native_ack")
        if len(queries) != 2:
            missing.append("pre_cancel_and_final_native_order_queries_required")
            baseline = final_query = None
        else:
            baseline, final_query = queries[-2], queries[-1]
        if baseline and (
            baseline.fields.get("complete") is not True
            or not set(accepted_by_ref).issubset(set(baseline.fields.get("open_order_refs", ())))
            or baseline.sequence <= max((item.sequence for item in accepted), default=0)
        ):
            missing.append("pre_cancel_query_must_confirm_all_accepted_targets_open")
        if final_query and (
            final_query.fields.get("complete") is not True
            or final_query.fields.get("open_order_refs")
            or final_query.sequence <= max((item.sequence for item in canceled), default=0)
        ):
            missing.append("final_native_order_query_must_be_empty_after_cancels")

        request_ids = [item.fields.get("request_id") for item in cancel_logs]
        target_refs = [item.fields.get("order_ref") for item in cancel_logs]
        if (
            any(not isinstance(value, str) or not value for value in request_ids)
            or len(set(request_ids)) != len(request_ids)
            or any(not isinstance(value, str) or not value for value in target_refs)
            or len(set(target_refs)) != len(target_refs)
        ):
            missing.append("cancel_receipts_must_use_unique_request_ids_and_order_refs")
        canceled_by_ref = {item.fields.get("order_ref"): item for item in canceled}
        for index, receipt in enumerate(cancel_logs, 1):
            ref = receipt.fields.get("order_ref")
            order = accepted_by_ref.get(ref)
            origin = submission_by_ref.get(ref)
            terminal = canceled_by_ref.get(ref)
            if (
                receipt.fields.get("metric") != "cancel_count"
                or receipt.fields.get("count") != index
                or not _HEX64.fullmatch(str(receipt.fields.get("monitor_digest", "")))
                or not receipt.fields.get("trace_id")
                or not receipt.fields.get("request_receipt_ref")
                or not baseline
                or receipt.fields.get("source_query_event_id") != baseline.event_id
                or not order
                or not origin
                or origin.fields.get("trace_id") != receipt.fields.get("origin_trace_id")
                or ref not in set(baseline.fields.get("open_order_refs", ()))
            ):
                missing.append(
                    f"cancel_request_{index}_must_bind_monitor_receipt_to_open_provider_order"
                )
            if order and origin and not _utc(origin.occurred_at_utc) <= _utc(order.occurred_at_utc):
                missing.append(f"cancel_request_{index}_origin_receipt_must_precede_provider_ack")
            if (
                baseline
                and order
                and not _utc(order.occurred_at_utc) <= _utc(baseline.occurred_at_utc)
            ):
                missing.append(f"cancel_request_{index}_baseline_query_must_follow_provider_ack")
            if baseline and not _utc(baseline.occurred_at_utc) <= _utc(receipt.occurred_at_utc):
                missing.append(
                    f"cancel_request_{index}_monitor_receipt_must_follow_open_order_query"
                )
            if (
                not terminal
                or terminal.fields.get("status") not in {"canceled", "cancelled"}
                or terminal.fields.get("cancel_request_id") != receipt.fields.get("request_id")
                or (order and terminal.sequence <= order.sequence)
                or (terminal and _utc(terminal.occurred_at_utc) < _utc(receipt.occurred_at_utc))
            ):
                missing.append(f"cancel_request_{index}_must_match_native_cancel_acknowledgement")
        if len(canceled) != len(cancel_logs):
            missing.append("cancel_monitor_receipt_and_native_ack_cardinalities_must_match")
        positions = self._all(ObservationKind.POSITION_QUERY)
        if not positions or (
            positions[-1].fields.get("phase") != "final"
            or positions[-1].fields.get("closeable_quantity") != 0
            or (final_query and positions[-1].sequence <= final_query.sequence)
        ):
            missing.append("final_provider_position_snapshot_must_be_zero")
        return tuple(dict.fromkeys(missing))


def create_strategy(
    plan: DescriptiveCasePlan,
    scope: DecisionScope,
    authenticator: ObservationAuthenticator | None,
) -> M05Strategy:
    return M05Strategy(plan, scope, authenticator)


def _utc(value: str):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
