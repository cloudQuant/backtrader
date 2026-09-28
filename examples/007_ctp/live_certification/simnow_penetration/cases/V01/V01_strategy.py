"""REAL evidence and action plan for V01."""

from common.decision_engine import CaseIntentDecisionEngine, DecisionError

CASE_ID = 'V01'
PLAN = {
    "case_id": "V01",
    "scenario_id": "VALIDATION-01",
    "evidence_mode": "REAL",
    "status": "PLANNED",
    "objective": "Capture local rejection evidence for an invalid instrument identifier.",
    "actions": [
        "Resolve the approved sandbox contract metadata and select an instrument identifier that is demonstrably invalid for that runtime.",
        "Submit one bounded validation request and record whether local order validation rejects it before dispatch.",
        "Reconcile the broker order list and retain the validation log."
    ],
    "evidence": [
        "order_validation_rejected event with instrument and error_msg fields.",
        "Contract metadata source and request timestamp.",
        "Evidence that no corresponding order was dispatched or left open."
    ],
    "completion_criteria": [
        "The local rejection is tied to the invalid instrument and no corresponding order remains open."
    ]
}


class V01ReadOnlyStrategy(CaseIntentDecisionEngine):
    """Bind V01 to local invalid-instrument rejection evidence only."""

    def __init__(self, plan, scope, authenticator=None):
        if plan.case_id != CASE_ID:
            raise DecisionError("V01 strategy requires the V01 static plan")
        super().__init__(plan, scope, authenticator)
