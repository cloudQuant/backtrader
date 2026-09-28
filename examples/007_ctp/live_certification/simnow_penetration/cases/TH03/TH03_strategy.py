"""TH03 plan and typed read-only combined-threshold evidence strategy."""

from common.read_only_case_strategy import create_read_only_strategy

CASE_ID = "TH03"
PLAN = {
    "case_id": "TH03",
    "scenario_id": "RISK-THRESHOLD-03",
    "evidence_mode": "REAL",
    "status": "PLANNED",
    "objective": "Record the configured combined submit-and-cancel warning threshold.",
    "actions": [
        "Start the approved sandbox runtime with submit_cancel_total_warn_threshold set to 10.",
        "Allow monitor initialization and one normal market-data bar without order activity.",
        "Collect the monitor summary and retain the effective threshold and cancellation-counter fields.",
    ],
    "evidence": [
        "Runtime-resolved combined threshold value.",
        "monitoring_summary event and its documented cancel threshold/count fields.",
        "Timestamped monitor log and runtime configuration identity.",
    ],
    "completion_criteria": [
        "The combined threshold is visible in runtime evidence and no order activity occurred."
    ],
}


def create_strategy(plan, scope, authenticator):
    """Build the no-I/O event state machine for an injected managed adapter."""

    return create_read_only_strategy(CASE_ID, plan, scope, authenticator)
