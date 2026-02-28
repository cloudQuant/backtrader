"""OrderBook depth broker for precise order matching against order book levels.

OrderBookBroker extends TickBroker with the ability to match orders against
full order book depth, supporting partial fills based on available liquidity
at each price level and optional market impact models.

Example:
    Using OrderBookBroker::

        from backtrader.brokers.obbroker import OrderBookBroker
        from backtrader.brokers.impact_models import SquareRootImpactModel

        broker = OrderBookBroker(
            cash=100000,
            impact_model=SquareRootImpactModel(coefficient=0.1)
        )
"""

import logging

from backtrader.order import Order
from backtrader.brokers.tickbroker import TickBroker
from backtrader.parameters import ParameterDescriptor

logger = logging.getLogger(__name__)

__all__ = ["OrderBookBroker"]


class OrderBookBroker(TickBroker):
    """Broker that matches orders against order book depth levels.

    Traverses order book levels to fill orders, supporting:
    - Partial fills based on available depth
    - Market impact model integration
    - Realistic slippage from depth consumption

    Params:
        max_depth_levels: Maximum depth levels to traverse (default: 20).
        enable_impact: Enable market impact model (default: False).
    """

    max_depth_levels = ParameterDescriptor(default=20, doc="Max depth levels to traverse")
    enable_impact = ParameterDescriptor(default=False, doc="Enable market impact model")

    def __init__(self, impact_model=None, **kwargs):
        """Initialize the OrderBookBroker.

        Args:
            impact_model: Optional market impact model for price adjustments.
            **kwargs: Additional arguments passed to TickBroker.
        """
        super().__init__(**kwargs)
        self._impact_model = impact_model
        self._last_orderbook = {}

    def process_orderbook(self, ob_event, data=None):
        """Process an order book snapshot and match pending orders.

        Args:
            ob_event: OrderBookSnapshot event.
            data: Associated data feed (optional).
        """
        data_name = ob_event.symbol
        self._last_orderbook[data_name] = ob_event

        matched = []
        for order in list(self._pending_orders):
            order_data_name = getattr(order.data, "_name", None) or getattr(order.data, "symbol", str(order.data))
            if order_data_name != data_name:
                continue

            result = self._try_match_ob(order, ob_event)
            if result is not None:
                fill_price, fill_size = result
                if fill_size > 0:
                    self._execute_ob(order, fill_price, fill_size, ob_event)
                    remaining = abs(order.size) - fill_size
                    if remaining <= 0 or not self.get_param("allow_partial"):
                        matched.append(order)

        for order in matched:
            try:
                self._pending_orders.remove(order)
            except ValueError:
                pass

    def _try_match_ob(self, order, ob):
        """Try to match an order against order book depth.

        For buy orders, traverses ask levels. For sell orders, traverses
        bid levels. Returns weighted average fill price and total fill size.

        Args:
            order: The order to match.
            ob: OrderBookSnapshot with current depth.

        Returns:
            Tuple of (avg_fill_price, total_fill_size) or None.
        """
        exectype = order.exectype
        target_size = abs(order.remaining_size if hasattr(order, "remaining_size") else order.size)
        max_levels = self.get_param("max_depth_levels")

        if exectype == Order.Market:
            if order.isbuy():
                return self._match_buy_order(ob.asks, target_size, max_levels, None)
            else:
                return self._match_sell_order(ob.bids, target_size, max_levels, None)

        elif exectype == Order.Limit:
            limit_price = order.price
            if order.isbuy():
                if ob.asks and ob.asks[0][0] <= limit_price:
                    return self._match_buy_order(ob.asks, target_size, max_levels, limit_price)
            else:
                if ob.bids and ob.bids[0][0] >= limit_price:
                    return self._match_sell_order(ob.bids, target_size, max_levels, limit_price)

        elif exectype == Order.Stop:
            stop_price = order.price
            if order.isbuy():
                if ob.asks and ob.asks[0][0] >= stop_price:
                    return self._match_buy_order(ob.asks, target_size, max_levels, None)
            else:
                if ob.bids and ob.bids[0][0] <= stop_price:
                    return self._match_sell_order(ob.bids, target_size, max_levels, None)

        return None

    def _match_buy_order(self, asks, target_size, max_levels, limit_price):
        """Match a buy order against ask levels.

        Args:
            asks: List of (price, qty) ask levels in ascending order.
            target_size: Target fill size.
            max_levels: Maximum levels to traverse.
            limit_price: Maximum price to fill at (None for no limit).

        Returns:
            Tuple of (weighted_avg_price, total_filled) or None.
        """
        total_filled = 0.0
        total_cost = 0.0

        for i, (price, qty) in enumerate(asks):
            if i >= max_levels:
                break
            if limit_price is not None and price > limit_price:
                break

            remaining = target_size - total_filled
            fill_at_level = min(qty, remaining)

            # Apply market impact if enabled
            if self.get_param("enable_impact") and self._impact_model:
                price = self._apply_market_impact(price, fill_at_level, is_buy=True)

            total_cost += price * fill_at_level
            total_filled += fill_at_level

            if total_filled >= target_size:
                break

        if total_filled <= 0:
            return None

        avg_price = total_cost / total_filled
        return (avg_price, total_filled)

    def _match_sell_order(self, bids, target_size, max_levels, limit_price):
        """Match a sell order against bid levels.

        Args:
            bids: List of (price, qty) bid levels in descending order.
            target_size: Target fill size.
            max_levels: Maximum levels to traverse.
            limit_price: Minimum price to fill at (None for no limit).

        Returns:
            Tuple of (weighted_avg_price, total_filled) or None.
        """
        total_filled = 0.0
        total_revenue = 0.0

        for i, (price, qty) in enumerate(bids):
            if i >= max_levels:
                break
            if limit_price is not None and price < limit_price:
                break

            remaining = target_size - total_filled
            fill_at_level = min(qty, remaining)

            if self.get_param("enable_impact") and self._impact_model:
                price = self._apply_market_impact(price, fill_at_level, is_buy=False)

            total_revenue += price * fill_at_level
            total_filled += fill_at_level

            if total_filled >= target_size:
                break

        if total_filled <= 0:
            return None

        avg_price = total_revenue / total_filled
        return (avg_price, total_filled)

    def _apply_market_impact(self, price, size, is_buy):
        """Apply market impact model to adjust price.

        Args:
            price: Original price level.
            size: Fill size at this level.
            is_buy: Whether this is a buy fill.

        Returns:
            Adjusted price after market impact.
        """
        if self._impact_model is None:
            return price
        impact = self._impact_model.calculate_impact(price, size)
        if is_buy:
            return price + impact
        else:
            return price - impact

    def _execute_ob(self, order, fill_price, fill_size, ob):
        """Execute an order fill from order book depth matching.

        Updates the broker's cash, positions, and order status based on the
        fill. Calculates commission using the commission info associated with
        the order's data feed. Records the fill in order history with depth
        source tracking.

        Args:
            order: The Order instance being filled.
            fill_price: The weighted average execution price.
            fill_size: The number of shares/contracts filled.
            ob: OrderBookSnapshot containing timestamp and symbol info.
        """
        data_name = getattr(order.data, "_name", None) or getattr(order.data, "symbol", str(order.data))
        pos = self._positions[data_name]

        if order.isbuy():
            cost = fill_price * fill_size
            comminfo = self.getcommissioninfo(order.data)
            commission = comminfo.getcommission(fill_size, fill_price)
            self._cash -= cost + commission
            pos.update(fill_size, fill_price)
        else:
            revenue = fill_price * fill_size
            comminfo = self.getcommissioninfo(order.data)
            commission = comminfo.getcommission(fill_size, fill_price)
            self._cash += revenue - commission
            pos.update(-fill_size, fill_price)

        order.execute(
            dt=ob.timestamp,
            size=fill_size if order.isbuy() else -fill_size,
            price=fill_price,
            closed=0,
            closedvalue=0.0,
            closedcomm=0.0,
            opened=fill_size,
            openedvalue=fill_price * fill_size,
            openedcomm=0.0,
            margin=0,
            pnl=0,
            psize=pos.size,
            pprice=pos.price,
        )
        order.completed()
        self.notify(order)

        self._order_history.append(
            {
                "timestamp": ob.timestamp,
                "symbol": data_name,
                "side": "buy" if order.isbuy() else "sell",
                "price": fill_price,
                "size": fill_size,
                "source": "orderbook_depth",
            }
        )
