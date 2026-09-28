"""Case-specific real evidence and action plan; descriptive data only."""

from common.read_only_case_strategy import create_read_only_strategy

CASE_ID = "T02"
CASE_NAME = "Close-order request against confirmed position"
CASE_PLAN = {
    "evidence": (
        "Capture the authoritative position snapshot before and after the close request, order_submit_request, broker order reference, and provider acknowledgement or rejection reason.",
        "Retain the final order and position queries; do not infer a fill from local submission.",
    ),
    "actions": (
        "Require a provider-confirmed closeable position before acting; submit at most one minimum-size close limit within that position.",
        "Reconcile the terminal provider order state and resulting position; stop without submitting if the position is absent or insufficient.",
    ),
}


def create_strategy(plan, scope, authenticator):
    """Construct the no-I/O typed order lifecycle observer for an injected adapter."""

    return create_read_only_strategy(CASE_ID, plan, scope, authenticator)
