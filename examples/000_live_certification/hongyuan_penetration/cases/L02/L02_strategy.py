"""Correlate system connection and readiness log events for case L02."""
import backtrader as bt


class L02Strategy(bt.Strategy):
    params = (("case_config", None), ("allow_orders", False))

    def __init__(self):
        self.case_config = self.p.case_config
        self.case_events = []
        self.case_observed = False
        self.case_reason = "awaiting correlated system lifecycle logs"
        self.bars_seen = 0
        self._connected = None
        self._ready = None

    @staticmethod
    def _capture(event):
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        row = {"event_type": event.get("event_type")}
        for key in ("timestamp", "session_id", "gateway_key", "trace_id", "status"):
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
            self.case_reason = (
                "correlated system lifecycle events observed; runner retains certification decision"
            )

    def next(self):
        self.bars_seen += 1
