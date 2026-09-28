"""Case plan and typed read-only authentication/login evidence strategy."""

from common.read_only_case_strategy import create_read_only_strategy

CASE_ID = "C01"
CASE_NAME = "Counter authentication and account login"
CASE_PLAN = {
    "evidence": (
        "Archive the native authentication and login callbacks with their request IDs, ErrorID, callback-local capture times, and order. Bind FrontID, SessionID, and TradingDay only from the login callback; redact account identifiers.",
        "Correlate the session lifecycle with clean shutdown records and confirm there were no order or cancel requests.",
    ),
    "actions": (
        "Start one reviewed read-only SimNow session through the managed route and observe broker authentication and account-login callbacks.",
        "Close the session cleanly and retain the locally observed callback sequence with private account fields redacted; do not label local sequence or time as provider-issued facts.",
    ),
}


def create_strategy(plan, scope, authenticator):
    """Build the no-I/O event state machine for an injected managed adapter."""

    return create_read_only_strategy(CASE_ID, plan, scope, authenticator)
