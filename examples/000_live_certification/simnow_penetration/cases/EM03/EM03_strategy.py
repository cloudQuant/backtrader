"""Observe operator initiated logout and matching disconnect evidence for EM03."""
import backtrader as bt


class EM03Strategy(bt.Strategy):
    params = (("case_config", None), ("allow_orders", False))

    def __init__(self):
        self.case_config = self.p.case_config
        self.case_events = []
        self.case_observed = False
        self.case_reason = "awaiting operator termination and disconnect evidence"
        self.bars_seen = 0
        self._logout = None
        self._disconnected = None

    @staticmethod
    def _capture(event):
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        keys = (
            "timestamp",
            "gateway_key",
            "reason",
            "authorization_ref",
            "operator_termination_evidence_ref",
            "post_disconnect_write_guard_evidence_ref",
            "gateway_released",
            "status",
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
        if kind not in ("gateway_force_logout_requested", "store_disconnected"):
            return
        row = self._capture(event)
        self.case_events.append(row)
        if kind == "gateway_force_logout_requested":
            self._logout = row
        else:
            self._disconnected = row
        request, disconnect = self._logout, self._disconnected
        if not request or not disconnect:
            return
        evidenced = (
            request.get("gateway_key")
            and request.get("gateway_key") == disconnect.get("gateway_key")
            and request.get("reason")
            and request.get("authorization_ref")
            and request.get("operator_termination_evidence_ref")
            and request.get("post_disconnect_write_guard_evidence_ref")
            and request.get("gateway_released") is True
        )
        if evidenced:
            self.case_observed = True
            self.case_reason = "operator termination and matching disconnect observed; runner retains certification decision"
        else:
            self.case_reason = (
                "logout or disconnect lacks required operator and write-guard evidence"
            )

    def next(self):
        self.bars_seen += 1
        if self._logout is not None:
            return
