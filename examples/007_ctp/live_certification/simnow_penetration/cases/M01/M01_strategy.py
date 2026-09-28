"""Case plan and typed read-only connection/readiness evidence strategy."""

from common.read_only_case_strategy import create_read_only_strategy

CASE_ID = "M01"
CASE_NAME = "Connection and readiness display"
CASE_PLAN = {
    "evidence": (
        "Capture store_connected and store_ready records with callback-local capture times and independently observed login/session/front identities; do not label local times as provider timestamps.",
        "Correlate both events to the same authenticated session and a clean shutdown record; redact account identifiers.",
    ),
    "actions": (
        "Start the reviewed sandbox session and wait for the provider-backed ready event.",
        "Record the connection/readiness event sequence, then close cleanly without sending orders.",
    ),
}


def create_strategy(plan, scope, authenticator):
    """Build the no-I/O event state machine for an injected managed adapter."""

    return create_read_only_strategy(CASE_ID, plan, scope, authenticator)
