"""REAL evidence and action plan for V03."""

from common.decision_engine import CaseIntentDecisionEngine, DecisionError

CASE_ID = 'V03'
PLAN = {
    "case_id": "V03",
    "scenario_id": "VALIDATION-03",
    "evidence_mode": "REAL",
    "status": "PLANNED",
    "objective": "Capture local rejection evidence for a quantity above the contract maximum per order.",
    "actions": [
        "Read the approved runtime contract maximum order size and record its source.",
        "Submit one validation request with a quantity above that limit, subject to the reviewed sandbox bound.",
        "Reconcile the broker order list and retain the validation log."
    ],
    "evidence": [
        "order_validation_rejected event containing requested size, maximum order size, and error_msg.",
        "Contract metadata source and request timestamp.",
        "Evidence that no corresponding order was dispatched or left open."
    ],
    "completion_criteria": [
        "The rejection cites the observed size limit and no corresponding order remains open."
    ]
}


class V03ReadOnlyStrategy(CaseIntentDecisionEngine):
    """Bind V03 to review-only admission and local size validation evidence."""

    def __init__(self, plan, scope, authenticator=None):
        if plan.case_id != CASE_ID:
            raise DecisionError("V03 strategy requires the V03 static plan")
        super().__init__(plan, scope, authenticator)
