"""SA (soda ash) dual moving-average strategy for the CTP direct mode.

Signals (unchanged): fast SMA crossing above the slow SMA goes long, crossing
below goes short; at most one direction is held.

Direct-mode rules this example demonstrates (iteration 62):

* every CTP order carries an explicit ``offset`` (D62-26): ``open``, or the
  close offsets the venue allows; closes are planned from the broker's closable
  view and submitted separately for today's and yesterday's positions on
  SHFE/INE, never by a fixed ``close_today`` (D62-18/22);
* the closing order and the reverse opening order are tracked separately and
  may be in flight together (D62-24); a rejected close is not retried
  automatically - the next signal re-plans with fresh facts;
* orders are marketable limit orders with an explicit price (D62-33); the
  broker refuses orders while the target feed is not LIVE (D62-15a) and keeps
  orders created during a trusted market closure waiting for the next session
  (D62-30);
* orders recovered at startup are taken over in ``start()`` (R-6/7).
"""

import backtrader as bt

_SPLIT_VENUES = ("SHFE", "INE")


class DualMAStrategy(bt.Strategy):
    """Dual moving average crossover for SA futures (direct mode).

    Params:
        fast_period: fast SMA period.
        slow_period: slow SMA period.
        order_size: lots per signal.
        price_tick: minimum price increment of the instrument.
        slippage_ticks: ticks added to the last price for a marketable limit.
        print_log: print bar / order logs.
    """

    params = {
        "fast_period": 5,
        "slow_period": 20,
        "order_size": 1,
        "price_tick": 1.0,
        "slippage_ticks": 2,
        "print_log": True,
    }

    def __init__(self):
        self.live_data = False
        self.bar_count = 0
        self.close_orders = {}  # ref -> order (one per close offset)
        self.open_order = None
        self.fast_ma = bt.ind.SMA(self.data.close, period=self.p.fast_period)
        self.slow_ma = bt.ind.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.ind.CrossOver(self.fast_ma, self.slow_ma)

    # ------------------------------------------------------------------
    def log(self, msg):
        if self.p.print_log:
            dt = self.data.datetime.datetime(0) if len(self.data) else "-"
            print(f"[{dt}] {msg}", flush=True)

    def start(self):
        # Orders restored by the direct broker (working venue orders and
        # orders waiting for the next session) belong to this strategy
        # directory: take them over before sending anything new.
        take_over = getattr(self.broker, "take_over_restored_orders", None)
        restored = take_over(self) if callable(take_over) else []
        for order in restored:
            if order.info.get("offset") == "open":
                self.open_order = order
            else:
                self.close_orders[order.ref] = order
        if restored:
            self.log(f"took over {len(restored)} restored orders")

    def notify_data(self, data, status, *args, **kwargs):
        status_name = data._getstatusname(status)
        self.log(f"DATA STATUS: {data._name} -> {status_name}")
        self.live_data = status_name == "LIVE"

    def notify_order(self, order):
        tag = "restored " if order.info.get("restored") else ""
        if order.info.get("restored") and order.alive():
            # Restored after start() (its feed had no bar yet): take it over.
            if order.info.get("offset") == "open":
                self.open_order = order
            else:
                self.close_orders[order.ref] = order
        if order.status in (order.Submitted, order.Accepted):
            waiting = " (waiting for next session)" if order.info.get("waiting_session") else ""
            self.log(f"{tag}order {order.ref} {order.getstatusname()}{waiting}")
            return
        if order.status == order.Partial:
            self.log(f"order {order.ref} partial {order.executed.size}@{order.executed.price:.2f}")
            return
        if order.status == order.Completed:
            side = "BUY" if order.isbuy() else "SELL"
            self.log(
                f"{side} {order.info.get('offset')} EXECUTED: price={order.executed.price:.2f} "
                f"size={order.executed.size} comm={order.executed.comm:.2f}"
            )
        else:
            reason = order.info.get("error_code") or ""
            self.log(f"order {order.ref} {order.getstatusname()} {reason}")
        if self.open_order is not None and order.ref == self.open_order.ref:
            self.open_order = None
        self.close_orders.pop(order.ref, None)

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f"TRADE CLOSED: pnl={trade.pnl:.2f} net_pnl={trade.pnlcomm:.2f}")

    # ------------------------------------------------------------------
    def _limit_price(self, buy):
        tick = float(self.p.price_tick)
        offset = self.p.slippage_ticks * tick
        price = self.data.close[0] + offset if buy else self.data.close[0] - offset
        # Stay on the price grid (a fractional tick leaves binary rounding dust).
        return round(round(price / tick) * tick, 10) if tick > 0 else price

    def _close_plan(self, side, quantity):
        """Explicit close offsets from the broker's closable view (D62-18/22/26)."""
        view_reader = getattr(self.broker, "get_closable", None)
        if not callable(view_reader):
            return [("close", quantity)]
        view = view_reader(self.data, side)
        if view.get("venue") in _SPLIT_VENUES:
            plan = []
            today = view.get("closable_today")
            yesterday = view.get("closable_yesterday")
            if today is None or yesterday is None:
                self.log(f"closable split unknown for {side}; no close sent")
                return []
            if yesterday:
                plan.append(("close_yesterday", min(yesterday, quantity)))
            rest = quantity - sum(qty for _, qty in plan)
            if rest > 0 and today:
                plan.append(("close_today", min(today, rest)))
            return plan
        closable = view.get("closable") or 0
        return [("close", min(closable, quantity))] if closable else []

    def _submit(self, buy, size, offset, label):
        price = self._limit_price(buy)
        method = self.buy if buy else self.sell
        order = method(data=self.data, size=size, exectype=bt.Order.Limit, price=price,
                       offset=offset)
        self.log(f"SIGNAL {label}: {'buy' if buy else 'sell'} {size} {offset} @ {price:.2f} "
                 f"ref={order.ref}")
        return order

    def prenext(self):
        self.bar_count += 1

    def next(self):
        self.bar_count += 1
        pos = self.getposition(self.data)
        self.log(
            f"bar#{self.bar_count} C={self.data.close[0]:.2f} fast={self.fast_ma[0]:.2f} "
            f"slow={self.slow_ma[0]:.2f} cross={self.crossover[0]:.0f} pos={pos.size} "
            f"cash={self.broker.getcash():.2f} value={self.broker.getvalue():.2f}"
        )
        if not self.live_data or self.crossover[0] == 0:
            return
        if self.close_orders or self.open_order is not None:
            return  # earlier orders still working; never duplicate exposure

        size = self.p.order_size
        if self.crossover[0] > 0:  # golden cross: close short, open long
            short = abs(self.getposition(self.data, side="short").size) if self._dual() else max(
                -pos.size, 0
            )
            for offset, qty in self._close_plan("short", short) if short else []:
                order = self._submit(True, qty, offset, "golden cross close short")
                self.close_orders[order.ref] = order
            if pos.size <= 0:
                self.open_order = self._submit(True, size, "open", "golden cross open long")
        else:  # death cross: close long, open short
            long_size = abs(self.getposition(self.data, side="long").size) if self._dual() else max(
                pos.size, 0
            )
            for offset, qty in self._close_plan("long", long_size) if long_size else []:
                order = self._submit(False, qty, offset, "death cross close long")
                self.close_orders[order.ref] = order
            if pos.size >= 0:
                self.open_order = self._submit(False, size, "open", "death cross open short")

    def _dual(self):
        mode = getattr(getattr(self.broker, "p", None), "position_mode", "net")
        return str(mode) == "dual_side"

    def stop(self):
        self.log(f"Strategy stopped. bars={self.bar_count} value={self.broker.getvalue():.2f}")
