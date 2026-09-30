"""Observe externally evidenced disconnect and recovery events for case M03."""
import backtrader as bt


class M03Strategy(bt.Strategy):
    params = (("case_config", None), ("allow_orders", False))

    def __init__(self):
        self.case_config = self.p.case_config
        self.case_events = []
        self.case_observed = False
        self.case_reason = "awaiting externally evidenced disconnect and recovery"
        self.bars_seen = 0
        self._disconnect = None
        self._recovery = None
        self._disconnect_position = None
        self._recovery_position = None

    @staticmethod
    def _capture(event):
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        keys = (
            "timestamp",
            "external_event_id",
            "operator_intervention_ref",
            "snapshot_sha256",
            "session_id",
            "connection_generation",
            "previous_session_id",
            "new_session_id",
            "previous_connection_generation",
            "new_connection_generation",
            "authentication_succeeded",
            "login_succeeded",
            "subscription_succeeded",
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
        kind = event.get("event_type")
        if kind not in ("store_disconnected", "store_reconnect_success"):
            return
        row = self._capture(event)
        self.case_events.append(row)
        if kind == "store_disconnected":
            self._disconnect = row
            self._disconnect_position = len(self.case_events) - 1
        else:
            self._recovery = row
            self._recovery_position = len(self.case_events) - 1
        old, new = self._disconnect, self._recovery
        if not old or not new:
            return
        recovered = (
            self._disconnect_position < self._recovery_position
            and old.get("external_event_id")
            and old.get("operator_intervention_ref")
            and new.get("external_event_id")
            and new.get("operator_intervention_ref")
            and new.get("snapshot_sha256")
            and new.get("previous_session_id")
            and new.get("new_session_id")
            and new.get("previous_session_id") == old.get("session_id")
            and new.get("previous_connection_generation") == old.get("connection_generation")
            and new.get("previous_session_id") != new.get("new_session_id")
            and type(new.get("previous_connection_generation")) is int
            and type(new.get("new_connection_generation")) is int
            and new["new_connection_generation"] > new["previous_connection_generation"]
            and new.get("authentication_succeeded") is True
            and new.get("login_succeeded") is True
            and new.get("subscription_succeeded") is True
        )
        self.case_observed = bool(recovered)
        self.case_reason = (
            "disconnect and supervised recovery evidence observed; runner retains certification decision"
            if recovered
            else "lifecycle events lack required intervention or recovery evidence"
        )

    def next(self):
        self.bars_seen += 1
