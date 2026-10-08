"""Typed read-only evidence contracts with a lazy offline smoke strategy."""
from __future__ import annotations

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


def _load_smoke_strategy():
    """Observe authentication and account-login events for case C01."""

    import backtrader as bt

    class C01Strategy(bt.Strategy):
        params = (("case_config", None), ("allow_orders", False))

        def __init__(self):
            self.case_config = self.p.case_config
            self.case_events = []
            self.case_observed = False
            self.case_reason = "awaiting authentication and login evidence"
            self.bars_seen = 0
            self._auth = None
            self._login = None

        @staticmethod
        def _capture(event):
            details = event.get("details") if isinstance(event.get("details"), dict) else {}
            row = {"event_type": event.get("event_type")}
            for key in (
                "timestamp",
                "session_id",
                "front_id",
                "trading_day",
                "request_id",
                "status",
            ):
                value = event.get(key)
                if value is None:
                    value = details.get(key)
                if isinstance(value, (str, int, float, bool)):
                    row[key] = value
            return row

        def notify_store(self, msg, *args, **kwargs):
            event = kwargs.get("event")
            if msg != "runtime_event" or not isinstance(event, dict):
                return
            kind = event.get("event_type")
            if kind not in ("store_auth_success", "store_login_success"):
                return
            row = self._capture(event)
            self.case_events.append(row)
            if kind == "store_auth_success":
                self._auth = row
            else:
                self._login = row
            session = (self._login or {}).get("session_id")
            if (
                self._auth
                and self._login
                and session
                and session == self._auth.get("session_id")
                and self._login.get("front_id")
                and self._login.get("trading_day")
            ):
                self.case_observed = True
                self.case_reason = "authentication and login events observed; runner retains certification decision"

        def next(self):
            self.bars_seen += 1

    return C01Strategy


def __getattr__(name):
    if name == "C01Strategy":
        strategy = _load_smoke_strategy()
        globals()[name] = strategy
        return strategy
    raise AttributeError(name)
