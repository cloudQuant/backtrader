"""L03: case-specific real-evidence and action plan."""

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

CASE_ID = "L03"
CASE_NAME = "日志记录：运行监测信息"
CASE_PLAN = {
    "evidence_basis": "real_runtime",
    "scenario": "验证监测日志记录真实会话状态及经授权交易请求的观察事件。",
    "preconditions": (
        "已批准的真实会话及监控事件和日志字段定义。",
        "如需观察报撤单指标，须另行批准对应交易操作和账户额度。",
    ),
    "actions": (
        "记录运行、连接和监控计数器基线。",
        "观察真实会话中的监控事件，并关联已批准请求的请求标识。",
        "核对监控日志与运行日志、前置回报的时间及状态一致性。",
    ),
    "evidence": (
        "带时间戳的连接、就绪及监控日志原文。",
        "获准请求的请求标识、前置回报和计数器变化。",
        "日志采集范围及完整性摘要。",
    ),
    "dependency": "若范围包含委托或撤单计数，需真实交易授权；监控记录不能替代柜台回报。",
}


_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


def _copy_event(event: NativeObservation) -> NativeObservation:
    if not isinstance(event.fields, Mapping):
        raise DecisionError("observation fields must be a mapping")
    fields = {}
    for key, value in event.fields.items():
        if not isinstance(key, str):
            raise DecisionError("observation field names must be strings")
        if isinstance(value, (str, bool, int, float, type(None))):
            fields[key] = value
        elif isinstance(value, (tuple, list)) and all(
            isinstance(item, (str, bool, int, float, type(None))) for item in value
        ):
            fields[key] = tuple(value)
        else:
            raise DecisionError("observation fields must contain immutable scalar facts")
    return replace(event, fields=MappingProxyType(fields))


class L03Strategy(CaseIntentDecisionEngine):
    """Bind monitor log events to authorized request and provider evidence."""

    def __init__(self, plan, scope, authenticator):
        super().__init__(plan, scope, authenticator)
        kinds = (
            ObservationKind.AUTH_SUCCESS,
            ObservationKind.LOGIN_SUCCESS,
            ObservationKind.FRONT_CONNECTED,
            ObservationKind.MARKET_SUBSCRIPTION_ACK,
            ObservationKind.ORDER_ADMISSION,
            ObservationKind.ORDER_SUBMIT_RECEIPT,
            ObservationKind.ORDER_ACCEPTED,
            ObservationKind.MONITOR_LOG,
            ObservationKind.SYSTEM_LOG,
        )
        self.spec = replace(
            CASE_INTENT_SPECS[CASE_ID],
            required_kinds=kinds,
            rule="local_monitor_log",
            admission_kind="open",
        )

    def record(self, event: NativeObservation) -> bool:
        return super().record(_copy_event(event))

    def _missing(self, now: datetime) -> tuple[str, ...]:
        missing = list(super()._missing(now))
        if not self._session_ready():
            missing.append("provider_auth_login_front_and_subscription_success_required")
        admission = self._last(ObservationKind.ORDER_ADMISSION)
        if not admission or admission.fields.get("maximum_quantity") != 1:
            missing.append("one_lot_review_only_request_admission_required")

        receipts = self._all(ObservationKind.ORDER_SUBMIT_RECEIPT)
        accepted = self._all(ObservationKind.ORDER_ACCEPTED)
        monitor_logs = self._all(ObservationKind.MONITOR_LOG)
        system_logs = self._all(ObservationKind.SYSTEM_LOG)
        if (
            len(receipts) != 1
            or len(accepted) != 1
            or len(monitor_logs) != 1
            or len(system_logs) != 1
        ):
            missing.append("one_correlated_request_provider_ack_monitor_and_runtime_log_required")
            return tuple(dict.fromkeys(missing))

        receipt, order, monitor, runtime = receipts[0], accepted[0], monitor_logs[0], system_logs[0]
        ref = receipt.fields.get("order_ref")
        request_id = receipt.fields.get("request_id")
        trace_id = receipt.fields.get("trace_id")
        if (
            receipt.fields.get("dispatch_state") != "submitted"
            or not isinstance(request_id, str)
            or not request_id
            or not isinstance(trace_id, str)
            or not trace_id
            or order.fields.get("order_ref") != ref
            or order.fields.get("status") not in {"accepted", "working"}
        ):
            missing.append("managed_request_receipt_must_match_native_provider_acknowledgement")
        if (
            monitor.fields.get("event_name") != "order_submit_request"
            or monitor.fields.get("metric") != "submit_count"
            or monitor.fields.get("count") != 1
            or monitor.fields.get("request_id") != request_id
            or monitor.fields.get("request_receipt_event_id") != receipt.event_id
            or monitor.fields.get("order_ref") != ref
            or monitor.fields.get("trace_id") != trace_id
            or not _HEX64.fullmatch(str(monitor.fields.get("monitor_digest", "")))
        ):
            missing.append("monitor_log_must_bind_the_exact_authorized_request_receipt")
        if (
            runtime.fields.get("event_name") != "monitor_observation"
            or runtime.fields.get("monitor_event_id") != monitor.event_id
            or runtime.fields.get("request_id") != request_id
            or runtime.fields.get("order_ref") != ref
            or runtime.fields.get("trace_id") != trace_id
            or runtime.fields.get("session_id") != order.provider_session_id
            or runtime.fields.get("gateway_key") != order.fields.get("gateway_key")
            or not _HEX64.fullmatch(str(runtime.fields.get("log_digest", "")))
        ):
            missing.append("runtime_log_must_bind_monitor_request_and_provider_session")
        if (
            monitor.fields.get("session_id") != order.provider_session_id
            or monitor.fields.get("gateway_key") != order.fields.get("gateway_key")
            or monitor.fields.get("trading_day") != order.trading_day
            or runtime.fields.get("trading_day") != order.trading_day
            or runtime.fields.get("connection_generation")
            != order.fields.get("connection_generation")
            or monitor.fields.get("connection_generation")
            != order.fields.get("connection_generation")
        ):
            missing.append("monitor_and_runtime_logs_must_match_provider_session_generation")
        if not (
            _time(receipt.occurred_at_utc)
            <= _time(monitor.occurred_at_utc)
            <= _time(runtime.occurred_at_utc)
            and _time(receipt.occurred_at_utc) <= _time(order.occurred_at_utc)
            and _time(order.occurred_at_utc) <= _time(runtime.occurred_at_utc)
        ):
            missing.append("monitor_and_runtime_log_timestamps_must_follow_request_and_ack")
        return tuple(dict.fromkeys(missing))


def _time(value: str):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def create_strategy(
    plan: DescriptiveCasePlan,
    scope: DecisionScope,
    authenticator: ObservationAuthenticator | None,
) -> L03Strategy:
    return L03Strategy(plan, scope, authenticator)
