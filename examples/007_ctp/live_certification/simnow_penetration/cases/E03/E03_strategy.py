"""REAL evidence and action plan for E03."""

from common.decision_engine import CaseIntentDecisionEngine, DecisionError

CASE_ID = 'E03'
PLAN = {
    "case_id": "E03",
    "scenario_id": "ERROR-03",
    "evidence_mode": "REAL",
    "status": "PLANNED",
    "objective": "Capture a genuine counter response for an order rejected by the market state.",
    "actions": [
        "Observe the counter-reported market state and retain its timestamped source evidence.",
        "Proceed only if that real market state naturally provides the reviewed rejection condition; do not alter or synthesize it.",
        "Capture the counter response and reconcile any order or fill state."
    ],
    "evidence": [
        "order_reject_remote event with the counter ErrorID, ErrorMsg, and StatusMsg.",
        "Timestamped counter market-state evidence tied to the request.",
        "Final order and fill reconciliation."
    ],
    "completion_criteria": [
        "A genuine market-state rejection is recorded; if the condition is absent, retain the evidence and leave the case pending."
    ]
}


class E03ReadOnlyStrategy(CaseIntentDecisionEngine):
    """Bind E03 to observed market state and positive provider ErrorID."""

    def __init__(self, plan, scope, authenticator=None):
        if plan.case_id != CASE_ID:
            raise DecisionError("E03 strategy requires the E03 static plan")
        super().__init__(plan, scope, authenticator)
