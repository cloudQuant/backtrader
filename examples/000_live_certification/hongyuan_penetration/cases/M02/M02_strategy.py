"""Observe a supervised external disconnect for case M02."""
import backtrader as bt


class M02Strategy(bt.Strategy):
    params = (("case_config", None), ("allow_orders", False))

    def __init__(self):
        self.case_config = self.p.case_config
        self.case_events = []
        self.case_observed = False
        self.case_reason = "awaiting externally evidenced disconnect"
        self.bars_seen = 0

    @staticmethod
    def _capture(event):
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        keys = (
            "timestamp",
            "session_id",
            "connection_generation",
            "external_event_id",
            "source_transport_event_id",
            "operator_intervention_ref",
            "snapshot_sha256",
        )
        row = {"event_type": event.get("event_type")}
        for key in keys:
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
        if event.get("event_type") != "store_disconnected":
            return
        row = self._capture(event)
        self.case_events.append(row)
        evidenced = (
            all(
                row.get(key)
                for key in (
                    "session_id",
                    "external_event_id",
                    "source_transport_event_id",
                    "operator_intervention_ref",
                    "snapshot_sha256",
                )
            )
            and type(row.get("connection_generation")) is int
            and row["connection_generation"] > 0
        )
        if evidenced:
            self.case_observed = True
            self.case_reason = "disconnect and supervised intervention evidence observed; runner retains certification decision"
        else:
            self.case_reason = "disconnect signal lacks required external intervention evidence"

    def next(self):
        self.bars_seen += 1
