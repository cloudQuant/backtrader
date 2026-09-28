"""REAL evidence and action plan for E01."""

from common.decision_engine import CaseIntentDecisionEngine, DecisionError

CASE_ID = 'E01'
PLAN = {
    "case_id": "E01",
    "scenario_id": "ERROR-01",
    "evidence_mode": "REAL",
    "status": "PLANNED",
    "objective": "Capture the counter response for an insufficient-funds rejection under an approved sandbox condition.",
    "actions": [
        "Record the current account funds and the authorized bounded test condition before any request.",
        "Submit one reviewed request only when the sandbox account owner has approved the resulting margin exposure.",
        "Capture the counter response, cancel any remaining order, and reconcile fills and account state."
    ],
    "evidence": [
        "order_reject_remote event with the counter ErrorID, ErrorMsg, and StatusMsg.",
        "Request reference, timestamp, and redacted pre-request account-state evidence.",
        "Final order and fill reconciliation showing no unresolved order."
    ],
    "completion_criteria": [
        "A genuine counter-side insufficient-funds response is recorded and order/account state is reconciled."
    ]
}


class E01ReadOnlyStrategy(CaseIntentDecisionEngine):
    """Bind E01 to an external funds condition and positive provider ErrorID."""

    def __init__(self, plan, scope, authenticator=None):
        if plan.case_id != CASE_ID:
            raise DecisionError("E01 strategy requires the E01 static plan")
        super().__init__(plan, scope, authenticator)
