"""TH01 plan and typed read-only submit-threshold evidence strategy."""

from common.read_only_case_strategy import create_read_only_strategy

CASE_ID = "TH01"
PLAN = {
    "case_id": "TH01",
    "scenario_id": "RISK-THRESHOLD-01",
    "evidence_mode": "REAL",
    "status": "PLANNED",
    "objective": "Record the configured order-submission warning threshold from the runtime monitor.",
    "actions": [
        "Start the approved sandbox runtime with the TradeLogger submit-count threshold set to 5.",
        "Allow initialization and one normal market-data bar without submitting or cancelling orders.",
        "Collect the monitor summary emitted by that runtime and retain its effective threshold value.",
    ],
    "evidence": [
        "Runtime-resolved TradeLogger threshold configuration.",
        "monitoring_summary event containing submit_threshold or its documented thresholds.submit field.",
        "Timestamped monitor log and runtime configuration identity.",
    ],
    "completion_criteria": [
        "The configured value is visible in runtime evidence; no order activity occurred."
    ],
}


def create_strategy(plan, scope, authenticator):
    """Build the no-I/O event state machine for an injected managed adapter."""

    return create_read_only_strategy(CASE_ID, plan, scope, authenticator)
