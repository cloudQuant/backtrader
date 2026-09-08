"""Mid-frequency cross-product pair arbitrage (soybean meal m vs rapeseed meal RM).

策略完全基于 Backtrader 原生构件：``bt.indicators.SpreadZScore`` 提供双腿价差
z-score（指标在 next() 中就绪），限价参考 ``notify_tick`` 缓存的买卖一档。
执行为逐腿顺序限价 IOC：先空腿、确认终态后按实际成交量提交多腿；第二腿
未成交立即反向平掉裸腿；任一腿超时或未知状态即停机留痕，由人工对账。
"""

import math

import backtrader as bt
import backtrader.indicators as btind

# SHFE requires an explicit close_today; DCE/CZCE close plain.
CLOSE_TODAY_PREFIXES = ("rb", "hc")


def close_offset(symbol):
    """Best-effort CTP close offset for an intraday round trip."""
    letters = "".join(ch for ch in str(symbol) if ch.isalpha()).lower()
    return "close_today" if letters in CLOSE_TODAY_PREFIXES else "close"


class PairArbitrageStrategy(bt.Strategy):
    """Two-leg mean-reversion pair arbitrage driven by SpreadZScore."""

    params = (
        ("period", 180),
        ("entry_z", 2.0),
        ("exit_z", 0.5),
        ("confirmations", 3),
        ("min_interval", 5.0),
        ("order_lots", 1),
        ("max_position_lots", 2),
        ("max_pairs", 3),
        ("max_loss", 2000.0),
        ("max_holding_seconds", 1800.0),
        ("order_timeout", 8.0),
        ("slippage_ticks", 2.0),
        ("tick_size", 1.0),
        ("commission_rate", 0.0001),
        ("margin_rate", 0.1),
        ("multiplier", 10.0),
    )

    def __init__(self):
        self.spread = btind.SpreadZScore(self.data0, self.data1, period=self.p.period)
        self.symbols = [data._name for data in self.datas]
        self.close_offsets = {symbol: close_offset(symbol) for symbol in self.symbols}
        self._quotes = {}
        self.initial_value = None
        self.halted, self.halt_reason = False, ""
        self.current_pair = None
        self.pending_order = None
        self.active_pair = None
        self.stage = None
        self.orders = {}
        self.results = []
        self.open_attempts = 0
        self.ticks_seen = 0
        self._terminal_refs = set()
        self._direction = None
        self._confirmations = 0
        self._last_evaluation = -math.inf
        self._started_at = None
        self._final_report = None

    def start(self):
        self.initial_value = self.broker.getvalue()
        for data in self.datas:
            if abs(self.broker.getposition(data).size) > 1e-12:
                self.halt("Dedicated SimNow strategy requires initially flat positions")
                break

    def halt(self, reason):
        self.halted, self.halt_reason = True, reason

    # ---------------- market data ----------------

    def notify_tick(self, tick):
        symbol = getattr(tick, "symbol", None)
        if symbol not in self.symbols:
            return
        self.ticks_seen += 1
        bid = getattr(tick, "bid_price", None) or tick.price
        ask = getattr(tick, "ask_price", None) or tick.price
        if bid and ask and ask >= bid:
            self._quotes[symbol] = (float(bid), float(ask))

    def _now(self):
        return bt.num2date(self.data0.datetime[0]).timestamp()

    def _zscore(self):
        # A perfectly stable spread is a 0.0 z-score by construction.
        return self.spread.l.zscore[0]

    def _limit(self, symbol, side):
        quote = self._quotes.get(symbol)
        if quote:
            bid, ask = quote
        else:
            mid = self.getdatabyname(symbol).close[0]
            bid, ask = mid, mid
        pad = self.p.slippage_ticks * self.p.tick_size
        return (ask + pad) if side == "buy" else (bid - pad)

    # ---------------- main loop ----------------

    def next(self):
        if self.halted:
            return
        now = self._now()
        if self._started_at is None:
            self._started_at = now
        if self.pending_order is not None:
            if now - self.current_pair["last_submit"] > self.p.order_timeout:
                try:
                    self.cancel(self.pending_order)
                finally:
                    self.halt("Order deadline exceeded; reconcile remaining exposure")
            return
        if self.current_pair is not None:
            self._advance_pair(now)
            return
        if self.active_pair is not None:
            self._manage_open_pair(now)
            return
        self._try_open(now)

    def _try_open(self, now):
        if self.open_attempts >= self.p.max_pairs:
            return
        if now - self._last_evaluation < self.p.min_interval:
            return
        if self.broker.getvalue() <= self.initial_value - self.p.max_loss:
            self.halt("Maximum equity loss exceeded")
            return
        self._last_evaluation = now
        z = self._zscore()
        if abs(z) < self.p.entry_z:
            self._direction, self._confirmations = None, 0
            return
        first, second = self.symbols
        direction = (second, first) if z > 0 else (first, second)
        if direction != self._direction:
            self._direction, self._confirmations = direction, 0
        self._confirmations += 1
        if self._confirmations < self.p.confirmations:
            return
        self._confirmations = 0
        self.open_attempts += 1
        self._begin_legs(
            [
                {"symbol": direction[0], "side": "sell", "lots": self.p.order_lots},
                {"symbol": direction[1], "side": "buy", "lots": self.p.order_lots},
            ],
            "open",
        )

    def _manage_open_pair(self, now):
        pair = self.active_pair
        timed_out = now - pair["opened_at"] >= self.p.max_holding_seconds
        loss = self.broker.getvalue() <= self.initial_value - self.p.max_loss
        reverted = abs(self._zscore()) <= self.p.exit_z
        if timed_out or loss or reverted:
            self._close_positions("loss_stop" if loss else "timeout" if timed_out else "revert")

    # ---------------- leg execution ----------------

    def _begin_legs(self, legs, action):
        self.current_pair = {
            "legs": [dict(leg, filled=0) for leg in legs],
            "index": 0,
            "action": action,
            "reason": None,
            "order_refs": [],
            "last_submit": self._now(),
        }
        self.stage = "legs"
        self._submit_next_leg()

    def _submit_next_leg(self):
        pair = self.current_pair
        while pair["index"] < len(pair["legs"]):
            leg = pair["legs"][pair["index"]]
            if leg["lots"] >= 1:
                self._submit(leg["symbol"], leg["side"], int(leg["lots"]))
                return
            pair["index"] += 1
        self.stage = "reconcile"
        self._advance_pair(self._now())

    def _submit(self, symbol, side, lots):
        # bt.Strategy.sell takes a positive size and derives the short side.
        reduce_only = self.current_pair["action"] == "close"
        submit = self.buy if side == "buy" else self.sell
        order = submit(
            data=self.getdatabyname(symbol),
            size=lots,
            price=self._limit(symbol, side),
            exectype=bt.Order.Limit,
            time_in_force="IOC",
            offset=self.close_offsets[symbol] if reduce_only else "open",
        )
        if order is None:
            self.halt("Broker returned no order; reconciliation required")
            return
        self.current_pair["last_submit"] = self._now()
        self.current_pair["order_refs"].append(order.ref)
        self.pending_order = order

    def notify_order(self, order):
        self.orders[order.ref] = {
            "ref": order.ref,
            "symbol": order.data._name,
            "status": order.getstatusname(),
            "side": "buy" if order.isbuy() else "sell",
            "size": abs(order.size),
            "executed_size": order.executed.size,
            "executed_price": order.executed.price,
            "commission": order.executed.comm,
            "offset": order.info.get("offset"),
            # Remote status text is only meaningful on rejections; CTP
            # success reports ("全部成交报单已提交") must not pose as errors.
            "error_code": (
                order.info.get("error_code") if order.getstatusname() == "Rejected" else None
            ),
            "error_msg": (
                order.info.get("error_msg") if order.getstatusname() == "Rejected" else None
            ),
        }
        if self.halted or not self.current_pair or self.pending_order is None:
            return
        if order.ref != self.pending_order.ref or order.alive():
            return
        if order.ref in self._terminal_refs:
            return
        self._terminal_refs.add(order.ref)
        self.pending_order = None
        pair = self.current_pair
        leg = pair["legs"][pair["index"]]
        leg["filled"] = int(abs(order.executed.size))
        pair["index"] += 1
        if pair["action"] == "open" and pair["index"] == 1 and len(pair["legs"]) > 1:
            pair["legs"][1]["lots"] = leg["filled"]
        self._submit_next_leg()

    def _advance_pair(self, now):
        if self.stage != "reconcile":
            return
        positions = {data._name: self.broker.getposition(data).size for data in self.datas}
        opened = {symbol: size for symbol, size in positions.items() if abs(size) > 1e-12}
        if self.current_pair["action"] == "open":
            if len(opened) == 2:
                longs = [s for s, v in opened.items() if v > 0]
                shorts = [s for s, v in opened.items() if v < 0]
                if len(longs) == 1 and len(shorts) == 1:
                    self.active_pair = {
                        "long": longs[0],
                        "short": shorts[0],
                        "opened_at": now,
                    }
                    self._finish_pair()
                    return
            if not opened:
                self._finish_pair()
                return
            # A naked single leg: flatten it immediately as a close pair.
            self._close_positions("flatten_naked_leg")
            return
        if opened:
            self.halt("Close left residual exposure; reconcile manually")
        elif self.current_pair.get("reason") == "loss_stop":
            self.halt("Maximum equity loss exceeded")
        self._finish_pair()

    def _close_positions(self, reason):
        legs = []
        for data in self.datas:
            size = self.broker.getposition(data).size
            if size < -1e-12:
                legs.append({"symbol": data._name, "side": "buy", "lots": int(-size)})
            elif size > 1e-12:
                legs.append({"symbol": data._name, "side": "sell", "lots": int(size)})
        self.active_pair = None
        if not legs:
            return
        self._begin_legs(legs, "close")
        self.current_pair["reason"] = reason

    def _finish_pair(self):
        self.results.append(
            {
                "action": self.current_pair["action"],
                "reason": self.current_pair.get("reason"),
                "order_refs": self.current_pair["order_refs"],
            }
        )
        self.current_pair, self.stage = None, None

    # ---------------- reporting ----------------

    def stop(self):
        if not self.halted and any(
            abs(self.broker.getposition(data).size) > 1e-12 for data in self.datas
        ):
            self.halt("Data exhausted with open exposure; reconcile manually")
        self._final_report = self._make_report()

    def _make_report(self):
        positions = {data._name: float(self.broker.getposition(data).size) for data in self.datas}
        return {
            "strategy_class": type(self).__name__,
            "ticks_seen": self.ticks_seen,
            "initial_value": self.initial_value,
            "net_pnl": (
                (self.broker.getvalue() - self.initial_value)
                if self.initial_value is not None
                else 0.0
            ),
            "fees_paid": sum(o["commission"] for o in self.orders.values()),
            "positions": positions,
            "orders": list(self.orders.values()),
            "results": self.results,
            "pair_actions": len(self.results),
            "open_attempts": self.open_attempts,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
        }

    def report(self):
        return self._final_report or self._make_report()
