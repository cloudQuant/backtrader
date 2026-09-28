"""REAL evidence and action plan for V02."""

from common.decision_engine import CaseIntentDecisionEngine, DecisionError

CASE_ID = 'V02'
PLAN = {
    "case_id": "V02",
    "scenario_id": "VALIDATION-02",
    "evidence_mode": "REAL",
    "status": "PLANNED",
    "objective": "Capture local rejection evidence for an order price that does not align with the contract tick.",
    "actions": [
        "Read the approved runtime contract tick and record its source.",
        "Submit one bounded request at a price that violates that tick and record the local validation response.",
        "Reconcile the broker order list and retain the validation log."
    ],
    "evidence": [
        "order_validation_rejected event containing requested price, contract tick, and error_msg.",
        "Contract metadata source and request timestamp.",
        "Evidence that no corresponding order was dispatched or left open."
    ],
    "completion_criteria": [
        "The rejection cites the observed tick mismatch and no corresponding order remains open."
    ]
}


class V02ReadOnlyStrategy(CaseIntentDecisionEngine):
    """Bind V02 to tick-reference and local price-step rejection evidence."""

    def __init__(self, plan, scope, authenticator=None):
        if plan.case_id != CASE_ID:
            raise DecisionError("V02 strategy requires the V02 static plan")
        super().__init__(plan, scope, authenticator)
