"""Fixed, backend-neutral v2 live certification obligations.

READ cases inspect externally generated evidence; backends must not mutate state.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Risk


@dataclass(frozen=True)
class CaseSpec:
    action: str
    event: str
    risk: Risk
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()


_ORDER = ("symbol", "side", "quantity", "price")
_ORDER_OPT = ("order_type", "reduce_only")
_EXT = ("external_ref", "evidence_window_id")
_REQUEST = ("source_request_id", "evidence_window_id")
_SESSION = ("source_session_id", "evidence_window_id")
_TH_INSPECT = (*_EXT, "expected_threshold", "config_snapshot_id")
_TH_PROBE = (*_ORDER, "repeat_count", "expected_threshold", "config_snapshot_id", "baseline_count")

CASES: dict[str, CaseSpec] = {
    "B01": CaseSpec(
        "batch_cancel_partial",
        "batch_cancelled_partial",
        Risk.DANGEROUS,
        (*_ORDER, "order_count"),
        _ORDER_OPT,
    ),
    "B02": CaseSpec(
        "batch_cancel_open",
        "batch_cancelled_open",
        Risk.DANGEROUS,
        (*_ORDER, "order_count"),
        _ORDER_OPT,
    ),
    "C01": CaseSpec("inspect_authentication", "authenticated", Risk.READ, _SESSION),
    "E01": CaseSpec(
        "inspect_rejection", "provider_rejection", Risk.READ, (*_REQUEST, "reason_code")
    ),
    "E02": CaseSpec(
        "inspect_rejection", "provider_rejection", Risk.READ, (*_REQUEST, "reason_code")
    ),
    "E03": CaseSpec(
        "inspect_rejection", "provider_rejection", Risk.READ, (*_REQUEST, "reason_code")
    ),
    "EM01": CaseSpec(
        "inspect_permission_restriction",
        "permission_rejected",
        Risk.READ,
        (*_EXT, "operator_ref", "authorization_ref", "restriction_ref", "restoration_ref"),
    ),
    "EM02": CaseSpec(
        "inspect_strategy_pause",
        "strategy_paused",
        Risk.READ,
        (*_EXT, "operator_ref", "authorization_ref", "strategy_ref"),
    ),
    "EM03": CaseSpec(
        "inspect_logout",
        "disconnected",
        Risk.READ,
        (*_EXT, "operator_ref", "authorization_ref", "source_session_id"),
    ),
    "L01": CaseSpec(
        "inspect_trade_log",
        "trade_log_correlated",
        Risk.READ,
        (*_EXT, "trace_ref", "order_ref", "trade_ref"),
    ),
    "L02": CaseSpec("inspect_system_log", "system_log_correlated", Risk.READ, _SESSION),
    "L03": CaseSpec(
        "inspect_monitor_log", "monitor_log_correlated", Risk.READ, (*_EXT, "trace_ref")
    ),
    "L04": CaseSpec(
        "inspect_validation_log", "validation_rejected", Risk.READ, (*_REQUEST, "rule_ref")
    ),
    "M01": CaseSpec("inspect_monitor_connect", "monitor_ready", Risk.READ, _SESSION),
    "M02": CaseSpec(
        "inspect_monitor_disconnect",
        "monitor_disconnected",
        Risk.READ,
        (*_EXT, "operator_ref", "authorization_ref", "source_session_id"),
    ),
    "M03": CaseSpec(
        "inspect_monitor_recovery",
        "monitor_recovered",
        Risk.READ,
        (*_EXT, "operator_ref", "authorization_ref", "source_session_id", "new_session_id"),
    ),
    "M04": CaseSpec("monitor_submit", "monitor_submitted", Risk.WRITE, _ORDER, _ORDER_OPT),
    "M05": CaseSpec("monitor_cancel", "monitor_cancelled", Risk.WRITE, _ORDER, _ORDER_OPT),
    "O01": CaseSpec(
        "repeated_open",
        "repeated_open_observed",
        Risk.DANGEROUS,
        (*_ORDER, "repeat_count"),
        _ORDER_OPT,
    ),
    "O02": CaseSpec(
        "repeated_close",
        "repeated_close_observed",
        Risk.DANGEROUS,
        (*_ORDER, "repeat_count", "position_id", "position_snapshot_id"),
        _ORDER_OPT,
    ),
    "O03": CaseSpec(
        "repeated_cancel",
        "repeated_cancel_observed",
        Risk.DANGEROUS,
        ("remote_id", "symbol", "order_snapshot_id", "repeat_count"),
    ),
    "T01": CaseSpec("open_order", "order_accepted", Risk.WRITE, _ORDER, _ORDER_OPT),
    "T02": CaseSpec(
        "close_position",
        "close_observed",
        Risk.WRITE,
        (*_ORDER, "position_id", "position_snapshot_id"),
        _ORDER_OPT,
    ),
    "T03": CaseSpec(
        "cancel_order", "order_cancelled", Risk.WRITE, ("remote_id", "symbol", "order_snapshot_id")
    ),
    "TH01": CaseSpec(
        "inspect_submit_threshold", "submit_threshold_observed", Risk.READ, _TH_INSPECT
    ),
    "TH02": CaseSpec(
        "probe_submit_threshold",
        "submit_threshold_triggered",
        Risk.DANGEROUS,
        _TH_PROBE,
        _ORDER_OPT,
    ),
    "TH03": CaseSpec(
        "inspect_combined_threshold", "combined_threshold_observed", Risk.READ, _TH_INSPECT
    ),
    "TH04": CaseSpec(
        "probe_combined_threshold",
        "combined_threshold_triggered",
        Risk.DANGEROUS,
        _TH_PROBE,
        _ORDER_OPT,
    ),
    "TH05": CaseSpec(
        "inspect_repeated_threshold",
        "repeated_threshold_observed",
        Risk.READ,
        (*_TH_INSPECT, "window_seconds"),
    ),
    "TH06": CaseSpec(
        "probe_repeated_threshold",
        "repeated_threshold_triggered",
        Risk.DANGEROUS,
        _TH_PROBE,
        _ORDER_OPT,
    ),
    "V01": CaseSpec(
        "inspect_validation", "invalid_instrument_rejected", Risk.READ, (*_REQUEST, "rule_ref")
    ),
    "V02": CaseSpec(
        "inspect_validation", "invalid_price_tick_rejected", Risk.READ, (*_REQUEST, "rule_ref")
    ),
    "V03": CaseSpec(
        "inspect_validation", "oversized_order_rejected", Risk.READ, (*_REQUEST, "rule_ref")
    ),
}
