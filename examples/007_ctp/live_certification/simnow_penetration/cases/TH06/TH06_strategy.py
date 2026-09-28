"""REAL evidence and action plan for TH06."""

from _typed_scenario_state_candidate import TypedScenarioStateCandidate

CASE_ID = "TH06"
PLAN = {
    "case_id": "TH06",
    "scenario_id": "RISK-THRESHOLD-06",
    "evidence_mode": "REAL",
    "status": "PLANNED",
    "objective": "Observe a repeated-order warning within the configured observation window.",
    "actions": [
        "Set duplicate_order_warn_threshold to 2 in the approved sandbox runtime.",
        "Submit the same reviewed order intent twice within the configured repeat window using bounded quantities.",
        "Capture the risk warning and repeat count, then cancel any remaining open orders and reconcile the order list.",
    ],
    "evidence": [
        "Native OnRspUserLogin FrontID/SessionID/TradingDay bound to the local connection generation before order callbacks.",
        "risk_threshold_triggered event and duplicate_order_threshold_reached signal.",
        "Repeated intent key, effective threshold, repeat count, and timestamps.",
        "Final broker order state showing no unresolved open order.",
    ],
    "completion_criteria": [
        "The warning is supported by the observed repeated intent and all orders are reconciled."
    ],
}


# Unregistered typed review candidate; the structured PLAN remains static.
class TH06TypedScenarioState(TypedScenarioStateCandidate):
    CASE_ID = "TH06"
