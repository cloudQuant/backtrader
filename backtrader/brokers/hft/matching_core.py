from dataclasses import dataclass, field
from backtrader.order import Order
from .exchange import FillRole


@dataclass
class FillReport:
    order: object
    fill_price: float
    fill_size: float
    role: str = "taker"
    timestamp: float = 0.0
    source: str = "tick"


@dataclass
class MatchResult:
    action: str
    fills: list = field(default_factory=list)
    reject_reason: str = ""


@dataclass
class CancelResult:
    success: bool
    reason: str = ""


class MatchingCore:
    def __init__(self, latency_engine=None, exchange_model=None):
        self._latency = latency_engine
        self._exchange_model = exchange_model
        self._pending_by_symbol = {}
        self._order_to_symbol = {}

    def _get_symbol(self, order):
        data = getattr(order, "data", None)
        if data is None:
            return ""
        return getattr(data, "_name", None) or getattr(data, "symbol", str(data))

    def _bucket(self, symbol):
        if symbol not in self._pending_by_symbol:
            self._pending_by_symbol[symbol] = []
        return self._pending_by_symbol[symbol]

    def _add_pending(self, order, symbol=None):
        symbol = symbol or self._get_symbol(order)
        bucket = self._bucket(symbol)
        if order not in bucket:
            bucket.append(order)
        self._order_to_symbol[id(order)] = symbol

    def submit_order(self, order, current_ts=0.0):
        symbol = self._get_symbol(order)
        if self._latency is not None:
            visible_ts = self._latency.delay_order(order, current_ts, symbol)
            if visible_ts is not None:
                self._order_to_symbol[id(order)] = symbol
                return MatchResult(action="ACCEPTED")
        self._add_pending(order, symbol)
        return MatchResult(action="ACCEPTED")

    def modify_order(self, order, replacement_order, current_ts=0.0):
        cancel_result = self.cancel_order(order)
        if not cancel_result.success:
            return MatchResult(action="REJECT", reject_reason=cancel_result.reason)
        if replacement_order is None:
            return MatchResult(action="CANCELED")
        self.submit_order(replacement_order, current_ts=current_ts)
        return MatchResult(action="MODIFIED")

    def activate_orders(self, current_ts):
        if self._latency is None:
            return []
        activated = []
        for order, symbol in self._latency.get_visible_orders(current_ts):
            self._add_pending(order, symbol)
            activated.append(order)
        return activated

    def cancel_order(self, order):
        symbol = self._order_to_symbol.get(id(order), self._get_symbol(order))
        bucket = self._pending_by_symbol.get(symbol, [])
        try:
            bucket.remove(order)
            self._order_to_symbol.pop(id(order), None)
            if not bucket and symbol in self._pending_by_symbol:
                del self._pending_by_symbol[symbol]
            return CancelResult(success=True)
        except ValueError:
            if self._latency is not None:
                self._latency.cancel_order(order)
                self._order_to_symbol.pop(id(order), None)
                return CancelResult(success=True)
        return CancelResult(success=False, reason="ORDER_NOT_FOUND")

    def remove_order(self, order):
        symbol = self._order_to_symbol.pop(id(order), self._get_symbol(order))
        bucket = self._pending_by_symbol.get(symbol, [])
        try:
            bucket.remove(order)
        except ValueError:
            return
        if not bucket and symbol in self._pending_by_symbol:
            del self._pending_by_symbol[symbol]

    def pending_for_symbol(self, symbol):
        return list(self._pending_by_symbol.get(symbol, []))

    def pending_orders(self):
        result = []
        for bucket in self._pending_by_symbol.values():
            result.extend(bucket)
        return result

    def on_tick(self, tick_event):
        symbol = getattr(tick_event, "symbol", "")
        fills = []
        pending = list(self.pending_for_symbol(symbol))
        if self._exchange_model is not None:
            for order, price, size, role in self._exchange_model.on_trade(tick_event, pending):
                fills.append(self._build_fill(order, price, size, tick_event.timestamp, source=role.value, role=role.value))

        for order in pending:
            if self._exchange_model is not None and getattr(order, "_fill_role", None) == FillRole.MAKER:
                continue
            result = self._match_tick_order(order, tick_event)
            if result is None:
                continue
            price, size = result
            fills.append(self._build_fill(order, price, size, tick_event.timestamp))

        return MatchResult(action="FILL" if fills else "PENDING", fills=fills)

    def on_orderbook(self, ob_event):
        symbol = getattr(ob_event, "symbol", "")
        fills = []
        for order in list(self.pending_for_symbol(symbol)):
            if self._exchange_model is not None and order.exectype in (Order.Market, Order.Limit):
                exchange_result = self._exchange_model.on_new_order(order, ob_event)
                if exchange_result.action == "REJECT":
                    return MatchResult(action="REJECT", reject_reason=exchange_result.reject_reason)
                if exchange_result.action == "FILL":
                    price, size = self._aggregate_exchange_fills(exchange_result.fills)
                    if size > 0:
                        fills.append(
                            self._build_fill(order, price, size, ob_event.timestamp, source="orderbook_depth")
                        )
                    continue
                if getattr(order, "_fill_role", None) == FillRole.MAKER:
                    continue

            result = self._match_orderbook_order(order, ob_event)
            if result is None:
                continue
            price, size = result
            fills.append(
                self._build_fill(order, price, size, ob_event.timestamp, source="orderbook_depth")
            )

        return MatchResult(action="FILL" if fills else "PENDING", fills=fills)

    def _build_fill(self, order, price, size, timestamp, source="tick", role="taker"):
        return FillReport(
            order=order,
            fill_price=price,
            fill_size=size,
            role=role,
            timestamp=timestamp,
            source=source,
        )

    @staticmethod
    def _remaining_size(order):
        remaining = getattr(getattr(order, "executed", None), "remsize", None)
        if remaining is None:
            remaining = getattr(order, "size", 0.0)
        return abs(remaining)

    @staticmethod
    def _aggregate_exchange_fills(fills):
        total_size = 0.0
        total_value = 0.0
        for price, size, _role in fills:
            total_value += price * size
            total_size += size
        if total_size <= 0.0:
            return (0.0, 0.0)
        return (total_value / total_size, total_size)

    def _match_tick_order(self, order, tick_event):
        exectype = self._effective_exectype(order, tick_event.price)
        size = self._remaining_size(order)
        price = tick_event.price

        if exectype == Order.Market:
            return (price, size)

        if exectype == Order.Limit:
            limit_price = order.pricelimit if getattr(order, "_stop_triggered", False) and order.exectype == Order.StopLimit else order.price
            if order.isbuy() and price <= limit_price:
                return (min(price, limit_price), size)
            if not order.isbuy() and price >= limit_price:
                return (max(price, limit_price), size)
        return None

    def _match_orderbook_order(self, order, ob_event):
        exectype = self._effective_exectype(order, self._trigger_reference_price(order, ob_event))
        size = self._remaining_size(order)

        if exectype == Order.Market:
            if order.isbuy():
                return self._match_buy_depth(ob_event.asks, size, None)
            return self._match_sell_depth(ob_event.bids, size, None)

        if exectype == Order.Limit:
            limit_price = order.pricelimit if getattr(order, "_stop_triggered", False) and order.exectype == Order.StopLimit else order.price
            if order.isbuy() and ob_event.asks and ob_event.asks[0][0] <= limit_price:
                return self._match_buy_depth(ob_event.asks, size, limit_price)
            if (not order.isbuy()) and ob_event.bids and ob_event.bids[0][0] >= limit_price:
                return self._match_sell_depth(ob_event.bids, size, limit_price)
        return None

    def _effective_exectype(self, order, reference_price):
        exectype = order.exectype
        if exectype == Order.Stop:
            if self._check_stop_trigger(order, reference_price):
                return Order.Market
            return None
        if exectype == Order.StopLimit:
            if self._check_stop_trigger(order, reference_price):
                return Order.Limit
            return None
        return exectype

    def _check_stop_trigger(self, order, reference_price):
        if getattr(order, "_stop_triggered", False):
            return True
        stop_price = getattr(order, "price", None)
        if stop_price is None or reference_price is None:
            return False
        if order.isbuy() and reference_price >= stop_price:
            order._stop_triggered = True
            return True
        if (not order.isbuy()) and reference_price <= stop_price:
            order._stop_triggered = True
            return True
        return False

    @staticmethod
    def _trigger_reference_price(order, ob_event):
        if order.isbuy():
            return ob_event.asks[0][0] if ob_event.asks else None
        return ob_event.bids[0][0] if ob_event.bids else None

    @staticmethod
    def _match_buy_depth(asks, target_size, limit_price):
        total_filled = 0.0
        total_cost = 0.0
        for price, qty in asks:
            if limit_price is not None and price > limit_price:
                break
            fill = min(target_size - total_filled, qty)
            if fill <= 0:
                continue
            total_cost += price * fill
            total_filled += fill
            if total_filled >= target_size:
                break
        if total_filled <= 0:
            return None
        return (total_cost / total_filled, total_filled)

    @staticmethod
    def _match_sell_depth(bids, target_size, limit_price):
        total_filled = 0.0
        total_value = 0.0
        for price, qty in bids:
            if limit_price is not None and price < limit_price:
                break
            fill = min(target_size - total_filled, qty)
            if fill <= 0:
                continue
            total_value += price * fill
            total_filled += fill
            if total_filled >= target_size:
                break
        if total_filled <= 0:
            return None
        return (total_value / total_filled, total_filled)
