"""Observe external permission restriction and its provider rejection for EM01."""
import backtrader as bt


class EM01Strategy(bt.Strategy):
    params = (("case_config", None), ("allow_orders", False))

    def __init__(self):
        self.case_config = self.p.case_config
        self.case_events = []
        self.case_observed = False
        self.case_reason = "awaiting external permission evidence and provider rejection"
        self.bars_seen = 0
        self._permission = None
        self._probe_order = None
        self._probe_sent = False
        self._cancel_sent = False

    @staticmethod
    def _capture(event):
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        keys = (
            "timestamp",
            "account_id_masked",
            "reason",
            "authorization_ref",
            "independent_account_permission_evidence_ref",
            "permission_restored_ref",
            "blocked_order_ref",
            "order_ref",
            "ErrorID",
            "ErrorMsg",
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
        if kind not in ("account_trading_disabled", "order_reject_remote"):
            return
        row = self._capture(event)
        self.case_events.append(row)
        if kind == "account_trading_disabled":
            self._permission = row
        permission = self._permission or {}
        rejected = (
            kind == "order_reject_remote"
            and row.get("order_ref") == permission.get("blocked_order_ref")
            and row.get("ErrorID") not in (None, "", 0, "0")
            and row.get("ErrorMsg")
        )
        evidenced = all(
            permission.get(key)
            for key in (
                "account_id_masked",
                "reason",
                "authorization_ref",
                "independent_account_permission_evidence_ref",
                "permission_restored_ref",
                "blocked_order_ref",
            )
        )
        if evidenced and rejected:
            self.case_observed = True
            self.case_reason = "external restriction and matching provider rejection observed; runner retains certification decision"
        elif kind == "account_trading_disabled" and not evidenced:
            self.case_reason = "permission status lacks independent external intervention evidence"

    def notify_order(self, order):
        status = order.getstatusname() if hasattr(order, "getstatusname") else str(order.status)
        self.case_events.append({"source": "backtrader_order_callback", "status": status})
        if (
            self.p.allow_orders is True
            and self._probe_order is not None
            and not self._cancel_sent
            and order.ref == self._probe_order.ref
            and order.status == bt.Order.Accepted
        ):
            self._cancel_sent = True
            self.cancel(order)

    def next(self):
        self.bars_seen += 1
        evidence = self._permission or {}
        if (
            self.p.allow_orders is not True
            or self._probe_sent
            or self.data is None
            or not evidence.get("authorization_ref")
            or not evidence.get("independent_account_permission_evidence_ref")
            or not evidence.get("permission_restored_ref")
            or not evidence.get("blocked_order_ref")
        ):
            return
        close = float(self.data.close[0])
        if not (close > 0 and close == close and close < float("inf")):
            return
        self._probe_sent = True
        self._probe_order = self.buy(
            size=1, exectype=bt.Order.Limit, price=max(round(close * 0.25, 2), 0.01)
        )
