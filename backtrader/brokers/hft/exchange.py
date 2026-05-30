"""Exchange matching models for HFT simulation.

Defines :class:`ExchangeModel` and concrete variants that decide how an order
interacts with an order book / trade stream (maker vs taker fills, rejections),
plus :class:`FillRole` and :class:`OrderResult`. Used by the tick broker's
matching core.
"""

from dataclasses import dataclass, field
from enum import Enum

from backtrader.order import Order

from .queue import ProbQueueModel


class FillRole(Enum):
    MAKER = "maker"
    TAKER = "taker"


@dataclass
class OrderResult:
    action: str
    fills: list = field(default_factory=list)
    reject_reason: str = ""


class ExchangeModel:
    def on_new_order(self, order, ob_snapshot):
        raise NotImplementedError

    def on_trade(self, trade_event, pending_orders):
        raise NotImplementedError

    def on_depth_update(self, ob_event, pending_orders):
        _ = (ob_event, pending_orders)
        return []


class SimpleExchangeModel(ExchangeModel):
    def on_new_order(self, order, ob_snapshot):
        if order.exectype == Order.Market:
            return self._match_against_depth(order, ob_snapshot, FillRole.TAKER)
        if order.exectype == Order.Limit and self._crosses_spread(order, ob_snapshot):
            return self._match_against_depth(order, ob_snapshot, FillRole.TAKER)
        return OrderResult(action="PENDING")

    def on_trade(self, trade_event, pending_orders):
        _ = (trade_event, pending_orders)
        return []

    def _crosses_spread(self, order, ob_snapshot):
        if order.isbuy():
            best_ask = ob_snapshot.asks[0][0] if ob_snapshot.asks else None
            return best_ask is not None and order.price >= best_ask
        best_bid = ob_snapshot.bids[0][0] if ob_snapshot.bids else None
        return best_bid is not None and order.price <= best_bid

    def _match_against_depth(self, order, ob_snapshot, role):
        levels = ob_snapshot.asks if order.isbuy() else ob_snapshot.bids
        remaining = abs(getattr(order, "size", 0.0))
        fills = []
        for price, qty in levels:
            if order.exectype == Order.Limit:
                if order.isbuy() and price > order.price:
                    break
                if not order.isbuy() and price < order.price:
                    break
            fill_qty = min(remaining, qty)
            if fill_qty <= 0:
                continue
            fills.append((price, fill_qty, role))
            remaining -= fill_qty
            if remaining <= 0:
                break
        if not fills:
            return OrderResult(action="PENDING")
        return OrderResult(action="FILL", fills=fills)


class QueueExchangeModel(SimpleExchangeModel):
    def __init__(
        self,
        queue_model=None,
        queue_model_power: float = 2.0,
        lot_size: float = 1.0,
        tick_size: float = None,
    ):
        self._queue_model = queue_model or ProbQueueModel(
            power=queue_model_power, lot_size=lot_size
        )
        self._tick_size = float(tick_size) if tick_size is not None else None

    def on_new_order(self, order, ob_snapshot):
        if order.exectype == Order.Market:
            return self._match_against_depth(order, ob_snapshot, FillRole.TAKER)

        if order.exectype == Order.Limit:
            if self._crosses_spread(order, ob_snapshot):
                tif = getattr(order, "time_in_force", "GTC")
                taker_result = self._match_against_depth(order, ob_snapshot, FillRole.TAKER)
                filled_qty = sum(fill[1] for fill in taker_result.fills)
                order_qty = abs(getattr(order, "size", 0.0))
                if tif == "GTX":
                    return OrderResult(action="REJECT", reject_reason="GTX_CROSSED")
                if tif == "FOK" and filled_qty < order_qty:
                    return OrderResult(action="REJECT", reject_reason="FOK_INSUFFICIENT")
                return taker_result

            self._queue_model.on_new_order(order, ob_snapshot)
            order._fill_role = FillRole.MAKER
            return OrderResult(action="PENDING")

        return OrderResult(action="PENDING")

    def on_trade(self, trade_event, pending_orders):
        fills = []
        for order in pending_orders:
            if getattr(order, "_fill_role", None) != FillRole.MAKER:
                continue
            trade_price = getattr(trade_event, "price", None)
            order_price = getattr(order, "price", None)
            if trade_price is None or order_price is None:
                continue
            if self._tick_size is not None and self._tick_size > 0:
                if round(float(trade_price) / self._tick_size) != round(
                    float(order_price) / self._tick_size
                ):
                    continue
            elif float(trade_price) != float(order_price):
                continue
            fillable = self._queue_model.update_on_trade(order, trade_event)
            if fillable > 0:
                fills.append((order, trade_price, fillable, FillRole.MAKER))
        return fills

    def on_depth_update(self, ob_event, pending_orders):
        fills: list = []
        prev_bids = getattr(ob_event, "previous_bids", None) or []
        prev_asks = getattr(ob_event, "previous_asks", None) or []
        curr_bids = getattr(ob_event, "bids", None) or []
        curr_asks = getattr(ob_event, "asks", None) or []

        def level_qty(levels, price):
            for level_price, level_qty_value in levels:
                if self._tick_size is not None and self._tick_size > 0:
                    if round(float(level_price) / self._tick_size) == round(
                        float(price) / self._tick_size
                    ):
                        return float(level_qty_value)
                elif float(level_price) == float(price):
                    return float(level_qty_value)
            return 0.0

        for order in pending_orders:
            if getattr(order, "_fill_role", None) != FillRole.MAKER:
                continue
            price = getattr(order, "price", None)
            if price is None:
                continue
            prev_qty = level_qty(prev_bids if order.isbuy() else prev_asks, price)
            new_qty = level_qty(curr_bids if order.isbuy() else curr_asks, price)
            if abs(prev_qty - new_qty) <= 1e-12:
                continue
            self._queue_model.update_on_depth(order, prev_qty, new_qty)
        return fills
