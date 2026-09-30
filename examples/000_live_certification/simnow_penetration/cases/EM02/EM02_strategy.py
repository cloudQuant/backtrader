"""Observe an externally authorized strategy pause for case EM02."""
import backtrader as bt


class EM02Strategy(bt.Strategy):
    params = (("case_config", None), ("allow_orders", False))

    def __init__(self):
        self.case_config = self.p.case_config
        self.case_events = []
        self.case_observed = False
        self.case_reason = "awaiting an authorized external pause event"
        self.bars_seen = 0
        self._paused = False

    def notify_store(self, msg, *args, **kwargs):
        event = kwargs.get("event")
        if msg != "runtime_event" or not isinstance(event, dict):
            return
        if event.get("event_type") != "strategy_trading_paused":
            return
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        row = {"event_type": "strategy_trading_paused"}
        for key in (
            "timestamp",
            "strategy_id",
            "reason",
            "authorization_ref",
            "operator_action_ref",
        ):
            value = event.get(key)
            if value is None:
                value = details.get(key)
            if isinstance(value, (str, int, float, bool)):
                row[key] = value
        self.case_events.append(row)
        self._paused = True
        if all(
            row.get(key)
            for key in ("strategy_id", "reason", "authorization_ref", "operator_action_ref")
        ):
            self.case_observed = True
            self.case_reason = (
                "authorized pause evidence observed; runner retains certification decision"
            )
        else:
            self.case_reason = "pause notification lacks external authorization evidence"

    def next(self):
        self.bars_seen += 1
        if self._paused:
            return
