"""Case-specific real evidence and action plan; descriptive data only."""

from common.read_only_case_strategy import create_read_only_strategy

CASE_ID = "T01"
CASE_NAME = "Bounded open-order request and cleanup"
CASE_PLAN = {
    "evidence": (
        "Capture monitor and order records for order_submit_request, the actual broker order reference, provider acknowledgement/status, and final order/position reconciliation.",
        "Record the one-lot intent, limit price, timestamps, and cancellation or terminal result from the provider.",
    ),
    "actions": (
        "Under a reviewed order admission and account budget, submit one minimum-size open limit order using a current provider quote.",
        "Cancel after the provider acknowledges the order; reconcile that no order remains open and no unintended position was created.",
    ),
}


def create_strategy(plan, scope, authenticator):
    """Construct the no-I/O typed order lifecycle observer for an injected adapter."""

    return create_read_only_strategy(CASE_ID, plan, scope, authenticator)
