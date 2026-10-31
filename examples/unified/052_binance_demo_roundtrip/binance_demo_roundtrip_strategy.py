"""One bounded Binance Demo LIMIT open/cancel (or flatten) round trip.

The strategy is an ordinary Backtrader strategy.  Provider selection, account
environment and authorization live in ``config.yaml`` and ``run.py``; this file
contains only the business decision: rest a small limit order below the market,
cancel it after a short window, and flatten any partial fill reduce-only.
"""

from __future__ import annotations

import time

import backtrader as bt


class BinanceDemoRoundTripStrategy(bt.Strategy):
    params = (
        ("notional_usdt", 150.0),
        ("step_size", 0.001),
        ("tick_size", 0.10),
        ("offset_bps", 200.0),
        ("cancel_after_seconds", 6.0),
        ("hard_timeout_seconds", 45.0),
    )

    def __init__(self):
        self._phase = "waiting"
        self._open_order = None
        self._close_order = None
        self._cancel_at = None
        self._hard_deadline = time.monotonic() + float(self.p.hard_timeout_seconds)
        self._cancel_requested = False
        self._events = []
        self._idle_calls = 0
        self._maintenance_calls = 0
        self._cancel_error = None
        self._maintenance_state = None

    def nextstart(self):
        self._place_open()

    def next(self):
        if self._phase == "waiting":
            self._place_open()
        self._maintenance()

    def notify_idle(self):
        self._idle_calls += 1
        self._maintenance()

    def _maintenance(self):
        self._maintenance_calls += 1
        now = time.monotonic()
        self._maintenance_state = {
            "now": round(now, 3),
            "phase": self._phase,
            "cancel_at": self._cancel_at,
            "alive": bool(self._open_order.alive()) if self._open_order is not None else None,
        }
        if now >= self._hard_deadline:
            if self._phase not in ("canceled", "closed", "rejected"):
                self._phase = "timeout"
            self.env.runstop()
            return
        if (
            self._phase == "resting"
            and self._cancel_at is not None
            and now >= self._cancel_at
            and not self._cancel_requested
            and self._open_order is not None
            and self._open_order.alive()
        ):
            self._cancel_requested = True
            self._record("cancel_requested", self._open_order)
            try:
                self.cancel(self._open_order)
            except Exception as exc:  # noqa: BLE001 - bounded diagnostic
                self._cancel_error = type(exc).__name__[:60]

    def _place_open(self):
        if self._phase != "waiting":
            return
        try:
            market_price = float(self.data.close[0])
        except (IndexError, TypeError, ValueError):
            return
        if market_price <= 0:
            return
        step = float(self.p.step_size)
        tick = float(self.p.tick_size)
        quantity = max(step, round((float(self.p.notional_usdt) / market_price) / step) * step)
        offset = float(self.p.offset_bps) / 10000.0
        limit = round((market_price * (1.0 - offset)) / tick) * tick
        if limit <= 0:
            return
        self._open_order = self.buy(
            size=quantity,
            price=round(limit, 2),
            exectype=bt.Order.Limit,
            time_in_force="GTC",
            position_side="long",
            offset="open",
        )
        self._phase = "submitted"
        self._record("open_submitted", self._open_order)

    def _close_filled(self):
        order = self._open_order
        filled = abs(float(order.executed.size)) if order is not None else 0.0
        if filled <= 0:
            self._phase = "filled_without_size"
            self.env.runstop()
            return
        self._phase = "flattening"
        self._close_order = self.sell(
            size=filled,
            price=None,
            exectype=bt.Order.Market,
            reduce_only=True,
            position_side="long",
            offset="close",
        )
        self._record("close_submitted", self._close_order)

    def notify_order(self, order):
        status = order.getstatusname()
        self._record("order_" + status.lower(), order)
        open_ref = self._open_order.ref if self._open_order is not None else None
        close_ref = self._close_order.ref if self._close_order is not None else None
        if open_ref is not None and order.ref == open_ref:
            self._open_order = order
            if status == "Submitted":
                return
            if status == "Accepted":
                self._phase = "resting"
                self._cancel_at = time.monotonic() + float(self.p.cancel_after_seconds)
                return
            if status == "Partial":
                self._phase = "partially_filled"
                return
            if status == "Completed":
                self._phase = "filled"
                self._close_filled()
                return
            if status == "Canceled":
                self._phase = "canceled"
                if abs(float(order.executed.size)) > 0:
                    self._close_filled()
                else:
                    self.env.runstop()
                return
            if status in ("Rejected", "Margin", "Expired"):
                self._phase = "rejected"
                self.env.runstop()
            return
        if close_ref is not None and order.ref == close_ref and status in (
            "Completed",
            "Canceled",
            "Rejected",
            "Margin",
            "Expired",
        ):
            self._close_order = order
            self._phase = "closed" if status == "Completed" else "close_failed"
            self.env.runstop()

    def session_facts(self):
        return {
            "phase": self._phase,
            "cancel_requested": self._cancel_requested,
            "idle_calls": self._idle_calls,
            "maintenance_calls": self._maintenance_calls,
            "maintenance_state": self._maintenance_state,
            "cancel_error": self._cancel_error,
            "open_order": self._order_fact(self._open_order),
            "close_order": self._order_fact(self._close_order),
            "events": tuple(self._events),
        }

    def _order_fact(self, order):
        if order is None:
            return None
        info = {}
        for key, value in dict(order.info).items():
            if not isinstance(key, str):
                continue
            if isinstance(value, (bool, int, float)) or value is None:
                info[key] = value
            else:
                info[key] = str(value)[:200]
        return {
            "ref": order.ref,
            "status": order.getstatusname(),
            "alive": bool(order.alive()),
            "executed_size": float(order.executed.size),
            "executed_price": float(order.executed.price or 0.0),
            "executed_value": float(order.executed.value or 0.0),
            "commission": float(order.executed.comm or 0.0),
            "info": info,
        }

    def _record(self, name, order):
        if len(self._events) >= 64:
            return
        self._events.append(
            {
                "event": name,
                "at_monotonic": round(time.monotonic(), 3),
                "ref": order.ref if order is not None else None,
                "status": order.getstatusname() if order is not None else None,
            }
        )
