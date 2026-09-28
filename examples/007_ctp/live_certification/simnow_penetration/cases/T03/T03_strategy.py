"""Case-specific real evidence and action plan; descriptive data only."""

from common.read_only_case_strategy import create_read_only_strategy

CASE_ID = "T03"
CASE_NAME = "Cancel request and terminal order state"
CASE_PLAN = {
    "evidence": (
        "Correlate the real broker order reference with order_submit_request, order_cancel_request, provider cancel acknowledgement/status, and a final open-order query.",
        "Retain the position reconciliation and provider timestamps for the submit/cancel sequence.",
    ),
    "actions": (
        "Submit one minimum-size bounded open limit under the reviewed order admission.",
        "After the provider returns the real order reference, issue one cancel request and verify the provider terminal state and absence from open orders.",
    ),
}


def create_strategy(plan, scope, authenticator):
    """Construct the no-I/O typed order lifecycle observer for an injected adapter."""

    return create_read_only_strategy(CASE_ID, plan, scope, authenticator)
