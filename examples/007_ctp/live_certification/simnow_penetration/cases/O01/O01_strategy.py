"""Case-specific real evidence and action plan; descriptive data only."""

from _typed_scenario_state_candidate import TypedScenarioStateCandidate

CASE_ID = "O01"
CASE_NAME = "Repeated open-intent monitoring"
CASE_PLAN = {
    "evidence": (
        "Capture each real order_submit_request, broker order reference, provider status, and monitor details that identify repeated open intents.",
        "Require a risk_repeat_order_detected record with the exact repeat key, count, configured window, and source request references; reconcile all resulting orders and positions.",
    ),
    "actions": (
        "Within a separately reviewed repeat-action budget, present the same bounded one-lot open intent in a controlled sequence.",
        "Observe the configured duplicate/risk behavior without bypassing it; cancel acknowledged live orders and stop on a fill or guard event.",
    ),
}


# Unregistered typed review candidate; the literal CASE_PLAN remains static.
class O01TypedScenarioState(TypedScenarioStateCandidate):
    CASE_ID = "O01"
