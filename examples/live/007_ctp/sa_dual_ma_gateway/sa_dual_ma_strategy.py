"""SA (soda ash) dual moving-average strategy for the CTP Gateway mode.

Signals (unchanged): fast SMA crossing above the slow SMA goes long, crossing
below goes short; at most one direction is held.

Gateway-mode rules this example demonstrates (iterations 62 and 63):

* the strategy shares one account with other strategies, so it only ever acts
  on what it holds itself: positions come from ``get_strategy_position()`` and
  the closable view from ``broker.get_closable()``, both answered by the
  Gateway's ledger of this strategy. The account-scope ``getposition()``,
  ``broker.getcash()`` and ``broker.getvalue()`` are not available in this
  mode (strategy cash and equity are not provided yet);
* a read that cannot be answered now (the Gateway is restarting, the ledger is
  not ready) skips the decision of that bar; nothing is assumed to be flat;
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
    """Dual moving average crossover for SA futures (Gateway mode).

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
        offset = self.p.slippage_ticks * self.p.price_tick
        return self.data.close[0] + offset if buy else self.data.close[0] - offset

    def _close_plan(self, side, quantity):
        """Explicit close offsets from the broker's closable view (D62-18/22/26)."""
        try:
            view = self.broker.get_closable(self.data, side)
        except RuntimeError as exc:
            self.log(f"closable view unavailable for {side} ({exc}); no close sent")
            return []
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
        try:
            order = method(data=self.data, size=size, exectype=bt.Order.Limit, price=price,
                           offset=offset)
        except RuntimeError as exc:
            # The Gateway-mode broker refuses, before anything is sent, an order
            # it cannot stand behind (feed not tradable, more than this strategy
            # can close, Gateway unreachable). The next signal plans again.
            self.log(f"SIGNAL {label}: refused before sending ({exc})")
            return None
        self.log(f"SIGNAL {label}: {'buy' if buy else 'sell'} {size} {offset} @ {price:.2f} "
                 f"ref={order.ref}")
        return order

    def prenext(self):
        self.bar_count += 1

    def _own_sizes(self):
        """(long, short) lots this strategy itself holds, or None when unknown now."""
        try:
            long_size = abs(self.get_strategy_position(self.data, side="long").size)
            short_size = abs(self.get_strategy_position(self.data, side="short").size)
        except RuntimeError as exc:
            self.log(f"own position unavailable ({exc}); no decision this bar")
            return None
        return long_size, short_size

    def next(self):
        self.bar_count += 1
        sizes = self._own_sizes()
        held = "unknown" if sizes is None else f"long={sizes[0]:g} short={sizes[1]:g}"
        self.log(
            f"bar#{self.bar_count} C={self.data.close[0]:.2f} fast={self.fast_ma[0]:.2f} "
            f"slow={self.slow_ma[0]:.2f} cross={self.crossover[0]:.0f} {held}"
        )
        if sizes is None or not self.live_data or self.crossover[0] == 0:
            return
        if self.close_orders or self.open_order is not None:
            return  # earlier orders still working; never duplicate exposure

        long_size, short_size = sizes
        size = self.p.order_size
        if self.crossover[0] > 0:  # golden cross: close short, open long
            for offset, qty in self._close_plan("short", short_size) if short_size else []:
                order = self._submit(True, qty, offset, "golden cross close short")
                if order is not None:
                    self.close_orders[order.ref] = order
            if long_size <= short_size:
                self.open_order = self._submit(True, size, "open", "golden cross open long")
        else:  # death cross: close long, open short
            for offset, qty in self._close_plan("long", long_size) if long_size else []:
                order = self._submit(False, qty, offset, "death cross close long")
                if order is not None:
                    self.close_orders[order.ref] = order
            if short_size <= long_size:
                self.open_order = self._submit(False, size, "open", "death cross open short")

    def stop(self):
        self.log(f"Strategy stopped. bars={self.bar_count}")
