"""Case-specific real evidence and action plan; descriptive data only."""

from _typed_scenario_state_candidate import TypedScenarioStateCandidate

CASE_ID = "O03"
CASE_NAME = "Repeated cancel-request monitoring"
CASE_PLAN = {
    "evidence": (
        "Capture the real order_cancel_request, its broker order reference and provider response, plus the required risk_repeat_cancel_detected monitor record for the repeated intent.",
        "Retain terminal order states and a final provider query proving no case order remains open.",
    ),
    "actions": (
        "Create one bounded pending order and confirm its real provider order reference and working state.",
        "Issue a cancel intent, then repeat the cancel intent for that same order reference inside the configured repeat window; require the second intent to be stopped by the reviewed risk monitor before provider dispatch.",
        "Require risk_repeat_cancel_detected with that repeat key/count, verify at most one provider cancel request, and reconcile the final order and fill state.",
    ),
}


# Unregistered typed review candidate; the literal CASE_PLAN remains static.
class O03TypedScenarioState(TypedScenarioStateCandidate):
    CASE_ID = "O03"
