"""Canonical certification scenario mapping for Hongyuan penetration cases."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CertificationScenario:
    """Canonical scenario metadata used by certification reports."""

    case_id: str
    scenario_id: str
    name: str
    category: str
    required_events: tuple[str, ...]
    evidence_fields: tuple[str, ...]
    optional: bool = False
    pass_conditions: tuple[str, ...] = (
        "required_events_present",
        "evidence_fields_present",
    )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_events"] = list(self.required_events)
        payload["evidence_fields"] = list(self.evidence_fields)
        payload["pass_conditions"] = list(self.pass_conditions)
        return payload


_SCENARIO_ROWS: tuple[CertificationScenario, ...] = (
    CertificationScenario("C01", "AUTH-01", "认证登录", "接口适应性", ("store_auth_success", "store_login_success"), ("front_id", "session_id", "trading_day")),
    CertificationScenario("T01", "TRADE-OPEN-01", "正常下达开仓指令", "基础交易", ("order_submit_request", "order_status_accepted"), ("order_ref", "external_order_id")),
    CertificationScenario("T02", "TRADE-CLOSE-01", "正常下达平仓指令", "基础交易", ("order_submit_request", "order_status_accepted"), ("order_ref", "external_order_id")),
    CertificationScenario("T03", "TRADE-CANCEL-01", "正常下达撤单指令", "基础交易", ("order_cancel_request", "order_status_canceled"), ("order_ref", "external_order_id")),
    CertificationScenario("M01", "MONITOR-CONN-01", "连接成功显示连接成功", "连接异常监测", ("store_connected",), ("gateway_key", "market_connection", "trade_connection")),
    CertificationScenario("M02", "MONITOR-CONN-02", "连接断开显示连接断开", "连接异常监测", ("store_disconnected",), ("gateway_key", "timestamp")),
    CertificationScenario("M03", "MONITOR-CONN-03", "断线后显示重连成功", "连接异常监测", ("store_reconnect_success",), ("gateway_key", "timestamp")),
    CertificationScenario("M04", "MONITOR-COUNT-01", "正常统计报单笔数", "报撤单监测", ("order_submit_request",), ("submitted_order_count",)),
    CertificationScenario("M05", "MONITOR-COUNT-02", "正常统计撤单笔数", "报撤单监测", ("order_cancel_request",), ("cancel_order_count",)),
    CertificationScenario("O01", "RISK-REPEAT-01", "重复开仓报单统计", "重复报单监测", ("risk_repeat_order_detected",), ("repeat_key", "repeat_count"), True),
    CertificationScenario("O02", "RISK-REPEAT-02", "重复平仓报单统计", "重复报单监测", ("risk_repeat_order_detected",), ("repeat_key", "repeat_count"), True),
    CertificationScenario("O03", "RISK-REPEAT-03", "重复撤单统计", "重复报单监测", ("risk_repeat_cancel_detected",), ("repeat_key", "repeat_count"), True),
    CertificationScenario("TH01", "RISK-THRESHOLD-01", "报单笔数阈值设置", "阈值管理", ("risk_threshold_configured",), ("order_threshold",)),
    CertificationScenario("TH02", "RISK-THRESHOLD-02", "报单笔数达到阈值预警", "阈值管理", ("risk_threshold_triggered",), ("order_threshold", "submitted_order_count")),
    CertificationScenario("TH03", "RISK-THRESHOLD-03", "报撤单笔数阈值设置", "阈值管理", ("risk_threshold_configured",), ("cancel_threshold",)),
    CertificationScenario("TH04", "RISK-THRESHOLD-04", "报撤单笔数达到阈值预警", "阈值管理", ("risk_threshold_triggered",), ("cancel_threshold", "cancel_order_count")),
    CertificationScenario("TH05", "RISK-THRESHOLD-05", "重复报单阈值设置", "阈值管理", ("risk_threshold_configured",), ("repeat_threshold", "repeat_window_sec"), True),
    CertificationScenario("TH06", "RISK-THRESHOLD-06", "重复报单达到阈值预警", "阈值管理", ("risk_threshold_triggered",), ("repeat_threshold", "repeat_count"), True),
    CertificationScenario("V01", "VALIDATION-01", "合约代码错误检查并拒绝报单", "错误防范", ("order_validation_rejected",), ("instrument", "error_msg")),
    CertificationScenario("V02", "VALIDATION-02", "价格最小变动价位错误检查", "错误防范", ("order_validation_rejected",), ("price", "price_tick", "error_msg")),
    CertificationScenario("V03", "VALIDATION-03", "单笔委托最大手数检查", "错误防范", ("order_validation_rejected",), ("size", "max_order_size", "error_msg")),
    CertificationScenario("E01", "ERROR-01", "资金不足错误展示", "错误提示", ("order_reject_remote",), ("ErrorID", "ErrorMsg", "StatusMsg")),
    CertificationScenario("E02", "ERROR-02", "持仓不足错误展示", "错误提示", ("order_reject_remote",), ("ErrorID", "ErrorMsg", "StatusMsg")),
    CertificationScenario("E03", "ERROR-03", "市场状态不允许错误展示", "错误提示", ("order_reject_remote",), ("ErrorID", "ErrorMsg", "StatusMsg")),
    CertificationScenario("EM01", "EMERGENCY-01", "限制账号交易权限暂停交易", "应急处理", ("account_trading_disabled",), ("account_id_masked", "reason")),
    CertificationScenario("EM02", "EMERGENCY-02", "暂停策略执行", "应急处理", ("strategy_trading_paused",), ("strategy_id", "reason")),
    CertificationScenario("EM03", "EMERGENCY-03", "强制账号退出", "应急处理", ("gateway_force_logout_requested",), ("gateway_key", "reason")),
    CertificationScenario("B01", "BATCH-CANCEL-01", "多笔部分成交报单批量撤单", "批量撤单", ("batch_cancel_requested",), ("order_refs", "partial_count")),
    CertificationScenario("B02", "BATCH-CANCEL-02", "多笔已报单批量撤单", "批量撤单", ("batch_cancel_requested",), ("order_refs", "open_order_count")),
    CertificationScenario("L01", "LOG-TRADE-01", "交易信息记录", "日志记录", ("order_submit_request", "trade_execution"), ("trace_id", "order_ref", "trade_id")),
    CertificationScenario("L02", "LOG-SYSTEM-01", "系统运行信息记录", "日志记录", ("store_connected", "store_ready"), ("trace_id", "gateway_key")),
    CertificationScenario("L03", "LOG-MONITOR-01", "监测信息记录", "日志记录", ("risk_monitor_event",), ("trace_id", "metric")),
    CertificationScenario("L04", "LOG-ERROR-01", "错误提示信息记录", "日志记录", ("order_validation_rejected",), ("trace_id", "error_code", "error_msg")),
)

SCENARIOS_BY_CASE_ID = {item.case_id: item for item in _SCENARIO_ROWS}
SCENARIOS_BY_SCENARIO_ID = {item.scenario_id: item for item in _SCENARIO_ROWS}

RECONCILIATION_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "C01": {"order_activity": "none", "trade_activity": "none", "account_position_change": "none"},
    "T01": {"order_activity": "required", "trade_activity": "allowed", "account_position_change": "allowed_if_trade", "no_open_orders_after": True},
    "T02": {"order_activity": "required", "trade_activity": "allowed", "account_position_change": "allowed_if_trade", "no_open_orders_after": True},
    "T03": {"order_activity": "required", "trade_activity": "none", "account_position_change": "none", "no_open_orders_after": True},
    "M01": {"order_activity": "none", "trade_activity": "none", "account_position_change": "none"},
    "M02": {"order_activity": "none", "trade_activity": "none", "account_position_change": "none"},
    "M03": {"order_activity": "none", "trade_activity": "none", "account_position_change": "none"},
    "M04": {"order_activity": "required", "trade_activity": "allowed", "account_position_change": "allowed_if_trade", "no_open_orders_after": True},
    "M05": {"order_activity": "required", "trade_activity": "none", "account_position_change": "none", "no_open_orders_after": True},
    "O01": {"order_activity": "required", "trade_activity": "allowed", "account_position_change": "allowed_if_trade", "no_open_orders_after": True},
    "O02": {"order_activity": "required", "trade_activity": "allowed", "account_position_change": "allowed_if_trade", "no_open_orders_after": True},
    "O03": {"order_activity": "required", "trade_activity": "none", "account_position_change": "none", "no_open_orders_after": True},
    "TH01": {"order_activity": "none", "trade_activity": "none", "account_position_change": "none"},
    "TH02": {"order_activity": "required", "trade_activity": "allowed", "account_position_change": "allowed_if_trade", "no_open_orders_after": True},
    "TH03": {"order_activity": "none", "trade_activity": "none", "account_position_change": "none"},
    "TH04": {"order_activity": "required", "trade_activity": "allowed", "account_position_change": "allowed_if_trade", "no_open_orders_after": True},
    "TH05": {"order_activity": "none", "trade_activity": "none", "account_position_change": "none"},
    "TH06": {"order_activity": "required", "trade_activity": "allowed", "account_position_change": "allowed_if_trade", "no_open_orders_after": True},
    "V01": {"order_activity": "none", "trade_activity": "none", "account_position_change": "none", "no_open_orders_after": True},
    "V02": {"order_activity": "none", "trade_activity": "none", "account_position_change": "none", "no_open_orders_after": True},
    "V03": {"order_activity": "none", "trade_activity": "none", "account_position_change": "none", "no_open_orders_after": True},
    "E01": {"order_activity": "required", "trade_activity": "none", "account_position_change": "none", "no_open_orders_after": True},
    "E02": {"order_activity": "required", "trade_activity": "none", "account_position_change": "none", "no_open_orders_after": True},
    "E03": {"order_activity": "none", "trade_activity": "none", "account_position_change": "none", "no_open_orders_after": True},
    "EM01": {"order_activity": "none", "trade_activity": "none", "account_position_change": "none", "no_open_orders_after": True},
    "EM02": {"order_activity": "none", "trade_activity": "none", "account_position_change": "none", "no_open_orders_after": True},
    "EM03": {"order_activity": "none", "trade_activity": "none", "account_position_change": "none", "no_open_orders_after": True},
    "B01": {"order_activity": "required", "trade_activity": "allowed", "account_position_change": "allowed_if_trade", "no_open_orders_after": True},
    "B02": {"order_activity": "required", "trade_activity": "none", "account_position_change": "none", "no_open_orders_after": True},
    "L01": {"order_activity": "required", "trade_activity": "required", "account_position_change": "allowed_if_trade", "no_open_orders_after": True},
    "L02": {"order_activity": "none", "trade_activity": "none", "account_position_change": "none"},
    "L03": {"order_activity": "required", "trade_activity": "allowed", "account_position_change": "allowed_if_trade", "no_open_orders_after": True},
    "L04": {"order_activity": "none", "trade_activity": "none", "account_position_change": "none", "no_open_orders_after": True},
}


def all_certification_scenarios() -> list[CertificationScenario]:
    """Return all canonical certification scenarios in spec order."""

    return list(_SCENARIO_ROWS)


def get_certification_scenario(case_id: str) -> CertificationScenario:
    """Return canonical scenario metadata for a legacy case id."""

    return SCENARIOS_BY_CASE_ID[case_id]


def get_reconciliation_expectation(case_id: str) -> dict[str, Any]:
    """Return expected real-account side effects for a certification case."""

    return dict(RECONCILIATION_EXPECTATIONS.get(case_id, {}))


def enrich_result_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Add canonical scenario fields to a result payload when missing."""

    case_id = str(payload.get("case_id") or "")
    scenario = SCENARIOS_BY_CASE_ID.get(case_id)
    if scenario is None:
        return payload

    enriched = dict(payload)
    enriched.setdefault("scenario_id", scenario.scenario_id)
    enriched.setdefault("scenario_name", scenario.name)
    enriched.setdefault("category", scenario.category)
    enriched.setdefault("required_events", list(scenario.required_events))
    enriched.setdefault("evidence_fields", list(scenario.evidence_fields))
    enriched.setdefault("pass_conditions", list(scenario.pass_conditions))
    enriched.setdefault("optional", scenario.optional)
    return enriched


def build_certification_coverage(
    *,
    case_order: list[str],
    case_registry: dict[str, Any],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a machine-readable coverage summary for the 33 scenarios."""

    missing_cases = [case_id for case_id in case_order if case_id not in case_registry]
    unmapped_cases = [case_id for case_id in case_order if case_id not in SCENARIOS_BY_CASE_ID]
    expected_ids = [SCENARIOS_BY_CASE_ID[case_id].scenario_id for case_id in case_order if case_id in SCENARIOS_BY_CASE_ID]
    duplicate_ids = sorted(
        scenario_id for scenario_id, count in Counter(expected_ids).items() if count > 1
    )
    result_ids = [
        str(enrich_result_payload(result).get("scenario_id") or "")
        for result in results
    ]
    covered_ids = [scenario_id for scenario_id in result_ids if scenario_id]
    status_by_scenario = {
        str(enrich_result_payload(result).get("scenario_id")): result.get("status", "?")
        for result in results
        if enrich_result_payload(result).get("scenario_id")
    }

    return {
        "total_scenarios": len(_SCENARIO_ROWS),
        "expected_cases": len(case_order),
        "covered_scenarios": len(set(covered_ids)),
        "scenario_ids": expected_ids,
        "missing_cases": missing_cases,
        "unmapped_cases": unmapped_cases,
        "duplicate_scenario_ids": duplicate_ids,
        "status_by_scenario": status_by_scenario,
    }
