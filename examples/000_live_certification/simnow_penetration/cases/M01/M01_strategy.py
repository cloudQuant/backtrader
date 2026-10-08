"""Typed read-only evidence contracts with a lazy offline smoke strategy."""
from __future__ import annotations

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


def _load_smoke_strategy():
    """Observe connection and readiness notifications for case M01."""

    import backtrader as bt

    class M01Strategy(bt.Strategy):
        params = (("case_config", None), ("allow_orders", False))

        def __init__(self):
            self.case_config = self.p.case_config
            self.case_events = []
            self.case_observed = False
            self.case_reason = "awaiting connected and ready notifications"
            self.bars_seen = 0
            self._connected = None
            self._ready = None

        @staticmethod
        def _capture(event):
            details = event.get("details") if isinstance(event.get("details"), dict) else {}
            row = {"event_type": event.get("event_type")}
            for key in ("timestamp", "session_id", "gateway_key", "status"):
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
            if kind not in ("store_connected", "store_ready"):
                return
            row = self._capture(event)
            self.case_events.append(row)
            if kind == "store_connected":
                self._connected = row
            else:
                self._ready = row
            session = (self._connected or {}).get("session_id")
            if (
                self._connected
                and self._ready
                and session
                and session == self._ready.get("session_id")
                and self._connected.get("timestamp")
                and self._ready.get("timestamp")
            ):
                self.case_observed = True
                self.case_reason = "matching connection and readiness events observed; runner retains certification decision"

        def next(self):
            self.bars_seen += 1

    return M01Strategy


def __getattr__(name):
    if name == "M01Strategy":
        strategy = _load_smoke_strategy()
        globals()[name] = strategy
        return strategy
    raise AttributeError(name)
