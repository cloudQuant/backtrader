"""REAL evidence and action plan for TH02."""

from _typed_scenario_state_candidate import TypedScenarioStateCandidate

CASE_ID = "TH02"
PLAN = {
    "case_id": "TH02",
    "scenario_id": "RISK-THRESHOLD-02",
    "evidence_mode": "REAL",
    "status": "PLANNED",
    "objective": "Observe an order-count warning at the configured submission threshold.",
    "actions": [
        "Set the submit-count warning threshold to 2 in the approved sandbox runtime.",
        "Submit two individually permitted orders using the reviewed scenario and bounded quantities.",
        "Capture the threshold event, then cancel any remaining open orders and reconcile the final order list.",
    ],
    "evidence": [
        "risk_threshold_triggered monitor event with order threshold and submitted count.",
        "Order request references and final broker order state.",
        "Evidence that no order remains open when the run ends.",
    ],
    "completion_criteria": [
        "The monitor event corresponds to the observed order count and all remaining orders are reconciled."
    ],
}


# Unregistered typed review candidate; the structured PLAN remains static.
class TH02TypedScenarioState(TypedScenarioStateCandidate):
    CASE_ID = "TH02"
