"""Case-specific real evidence and action plan; descriptive data only."""

from _typed_scenario_state_candidate import TypedScenarioStateCandidate

CASE_ID = "O02"
CASE_NAME = "Repeated close-intent monitoring"
CASE_PLAN = {
    "evidence": (
        "Capture real close order requests, broker order references, provider status/rejections, and monitor details for repeated close intents.",
        "Require a risk_repeat_order_detected record with the exact repeat key, count, configured window, and source request references; attach provider position snapshots before each action and after final reconciliation.",
    ),
    "actions": (
        "Proceed only with a provider-confirmed position and a reviewed repeat-action budget; present bounded one-lot close intents in sequence.",
        "Stop before any request could exceed confirmed closeable quantity, then reconcile every provider order and position update.",
    ),
}


# Unregistered typed review candidate; the literal CASE_PLAN remains static.
class O02TypedScenarioState(TypedScenarioStateCandidate):
    CASE_ID = "O02"
