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
        for key in ("timestamp", "session_id", "front_id", "trading_day", "request_id", "status"):
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
            self.case_reason = (
                "authentication and login events observed; runner retains certification decision"
            )

    def next(self):
        self.bars_seen += 1
