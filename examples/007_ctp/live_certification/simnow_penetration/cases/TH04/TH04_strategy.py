"""REAL evidence and action plan for TH04."""

from _typed_scenario_state_candidate import TypedScenarioStateCandidate

CASE_ID = "TH04"
PLAN = {
    "case_id": "TH04",
    "scenario_id": "RISK-THRESHOLD-04",
    "evidence_mode": "REAL",
    "status": "PLANNED",
    "objective": "Observe the combined order and cancellation warning at its configured threshold.",
    "actions": [
        "Set the combined submit-and-cancel warning threshold to 3 in the approved sandbox runtime.",
        "Issue a bounded sequence of permitted order requests and cancellations until the recorded total reaches 3.",
        "Capture the warning and both counters, then reconcile and cancel any remaining open orders.",
    ],
    "evidence": [
        "Native OnRspUserLogin FrontID/SessionID/TradingDay bound to the local connection generation before order callbacks.",
        "risk_threshold_triggered event with the effective threshold and observed combined count.",
        "Order and cancel request references with timestamps.",
        "Final broker order state showing no unresolved open order.",
    ],
    "completion_criteria": [
        "The warning is tied to the observed combined count and remaining orders are reconciled."
    ],
}


# Unregistered typed review candidate; the structured PLAN remains static.
class TH04TypedScenarioState(TypedScenarioStateCandidate):
    CASE_ID = "TH04"
