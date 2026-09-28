"""TH05 plan and typed read-only duplicate-threshold evidence strategy."""

from common.read_only_case_strategy import create_read_only_strategy

CASE_ID = "TH05"
PLAN = {
    "case_id": "TH05",
    "scenario_id": "RISK-THRESHOLD-05",
    "evidence_mode": "REAL",
    "status": "PLANNED",
    "objective": "Record the configured repeated-order threshold and its observation window.",
    "actions": [
        "Start the approved sandbox runtime with duplicate_order_warn_threshold set to 3.",
        "Allow monitor initialization and one normal market-data bar without submitting or cancelling orders.",
        "Collect the monitor summary and retain the threshold and repeat-window values.",
    ],
    "evidence": [
        "Runtime-resolved repeat threshold value.",
        "monitoring_summary event containing the repeat threshold and repeat window.",
        "Timestamped monitor log and runtime configuration identity.",
    ],
    "completion_criteria": [
        "The threshold and observation window are visible in runtime evidence; no order activity occurred."
    ],
}


def create_strategy(plan, scope, authenticator):
    """Build the no-I/O event state machine for an injected managed adapter."""

    return create_read_only_strategy(CASE_ID, plan, scope, authenticator)
