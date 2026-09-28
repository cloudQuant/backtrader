"""REAL evidence and action plan for E02."""

from common.decision_engine import CaseIntentDecisionEngine, DecisionError

CASE_ID = 'E02'
PLAN = {
    "case_id": "E02",
    "scenario_id": "ERROR-02",
    "evidence_mode": "REAL",
    "status": "PLANNED",
    "objective": "Capture the counter response for an insufficient-position rejection under an approved sandbox condition.",
    "actions": [
        "Read and record the account position and available closeable quantity for the selected contract.",
        "Proceed only with a sandbox-owner-approved bounded close request that is expected to exceed available quantity.",
        "Capture the counter response and reconcile positions, fills, and all remaining orders."
    ],
    "evidence": [
        "order_reject_remote event with the counter ErrorID, ErrorMsg, and StatusMsg.",
        "Redacted pre-request position and available closeable quantity with source timestamp.",
        "Final position, fill, and order reconciliation."
    ],
    "completion_criteria": [
        "A genuine counter-side insufficient-position response is recorded and the account state is reconciled."
    ]
}


class E02ReadOnlyStrategy(CaseIntentDecisionEngine):
    """Bind E02 to an external position condition and positive provider ErrorID."""

    def __init__(self, plan, scope, authenticator=None):
        if plan.case_id != CASE_ID:
            raise DecisionError("E02 strategy requires the E02 static plan")
        super().__init__(plan, scope, authenticator)
