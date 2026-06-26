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
    """Side of liquidity the order provided when it got filled.

    Attributes:
        MAKER: The order was resting on the book and provided liquidity.
        TAKER: The order aggressed against the book and consumed liquidity.
    """

    MAKER = "maker"
    TAKER = "taker"


@dataclass
class OrderResult:
    """Outcome of an exchange model's processing of an order.

    Attributes:
        action: High-level outcome keyword. One of ``"FILL"`` (the order was
            fully or partially filled), ``"PENDING"`` (the order is resting on
            the book and may fill later) or ``"REJECT"`` (the order was
            rejected, see ``reject_reason`` for the reason code).
        fills: List of fill tuples produced for this order. Each tuple's
            shape is model-specific; for example,
            :class:`SimpleExchangeModel` uses ``(price, quantity, role)``
            while :class:`QueueExchangeModel` prepends the originating
            ``order`` object.
        reject_reason: Short code explaining the rejection, populated when
            ``action == "REJECT"``. Empty otherwise.
    """

    action: str
    fills: list = field(default_factory=list)
    reject_reason: str = ""


class ExchangeModel:
    """Abstract interface for exchange matching behavior.

    Subclasses describe how an incoming order interacts with the current
    order book and trade stream, and how subsequent market data updates
    drive fills. All three hook methods receive a snapshot/pending-orders
    view from the matching core.
    """

    def on_new_order(self, order, ob_snapshot):
        """Handle a newly accepted order against ``ob_snapshot``.

        Subclasses must implement this and return an :class:`OrderResult`
        describing whether the order was filled, pended, or rejected.

        Args:
            order: The newly accepted order. Provides ``exectype``,
                ``isbuy()``, ``price`` and ``size`` accessors.
            ob_snapshot: Order book snapshot at the time the order was
                accepted. Provides ``bids`` and ``asks``.

        Returns:
            OrderResult: Outcome of the matching attempt.
        """
        raise NotImplementedError

    def on_trade(self, trade_event, pending_orders):
        """Process a trade event for any resting pending orders.

        Subclasses may consume the trade and emit maker-style fills when
        one of the ``pending_orders`` was at the trade price.

        Args:
            trade_event: The trade event to consume. Provides ``price`` and
                ``volume``.
            pending_orders: Iterable of resting orders that may be filled by
                this trade.

        Returns:
            list: Fill tuples produced by the subclass (possibly empty).
        """
        raise NotImplementedError

    def on_depth_update(self, ob_event, pending_orders):
        """Process a depth update to refresh queue-ahead estimates.

        The default implementation is a no-op. Models that track per-order
        queue position (e.g. :class:`QueueExchangeModel`) override this to
        reconcile each resting order's queue-ahead against the new depth.

        Args:
            ob_event: Depth update event. May carry ``previous_bids`` /
                ``previous_asks`` and ``bids`` / ``asks``.
            pending_orders: Iterable of resting orders that may be affected
                by the depth update.

        Returns:
            list: Fill tuples produced by the subclass (possibly empty).
        """
        _ = (ob_event, pending_orders)
        return []


class SimpleExchangeModel(ExchangeModel):
    """Exchange model that walks the book level-by-level with no queueing.

    Market orders sweep liquidity against the opposite side of the book.
    Limit orders either fill immediately if they cross the spread or sit
    pending without any queue-position tracking. This model is the right
    choice when queue dynamics are not needed (e.g. fast smoke tests).
    """

    def on_new_order(self, order, ob_snapshot):
        """Match a new order against the current book with no queueing.

        Market orders are filled against the opposite side; limit orders
        that cross the spread are matched as takers. Limit orders that do
        not cross the spread are returned as ``PENDING``.

        Args:
            order: The newly accepted order.
            ob_snapshot: Order book snapshot at acceptance.

        Returns:
            OrderResult: ``"FILL"`` with taker fills when the order matches
            against depth, otherwise ``"PENDING"``.
        """
        if order.exectype == Order.Market:
            return self._match_against_depth(order, ob_snapshot, FillRole.TAKER)
        if order.exectype == Order.Limit and self._crosses_spread(order, ob_snapshot):
            return self._match_against_depth(order, ob_snapshot, FillRole.TAKER)
        return OrderResult(action="PENDING")

    def on_trade(self, trade_event, pending_orders):
        """Ignore trade events (queueing is not simulated).

        Args:
            trade_event: The trade event (unused).
            pending_orders: The resting orders (unused).

        Returns:
            list: Always empty for this model.
        """
        _ = (trade_event, pending_orders)
        return []

    def _crosses_spread(self, order, ob_snapshot):
        """Return True when the order's limit price crosses the best quote.

        A buy limit crosses when its price is greater than or equal to the
        best ask; a sell limit crosses when its price is less than or equal
        to the best bid.

        Args:
            order: The order being evaluated. Must expose ``isbuy()`` and
                ``price``.
            ob_snapshot: Order book snapshot providing ``bids`` and
                ``asks``.

        Returns:
            bool: ``True`` if the limit order can be filled immediately.
        """
        if order.isbuy():
            best_ask = ob_snapshot.asks[0][0] if ob_snapshot.asks else None
            return best_ask is not None and order.price >= best_ask
        best_bid = ob_snapshot.bids[0][0] if ob_snapshot.bids else None
        return best_bid is not None and order.price <= best_bid

    def _match_against_depth(self, order, ob_snapshot, role):
        """Walk the book and fill the order as a taker up to its size.

        Market orders consume every level until the size is met; limit
        orders stop when the next level's price is on the wrong side of
        ``order.price``.

        Args:
            order: The aggressive order to fill. Provides ``isbuy()``,
                ``size`` and, for limits, ``price``.
            ob_snapshot: Order book snapshot to consume.
            role: The :class:`FillRole` to attach to each fill produced
                (typically :attr:`FillRole.TAKER`).

        Returns:
            OrderResult: ``"FILL"`` with the per-level fills when at least
            one level matched, otherwise ``"PENDING"``.
        """
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
    """Exchange model that maintains per-order queue position for maker fills.

    Limit orders that cross the spread follow :class:`SimpleExchangeModel`'s
    taker semantics (with extra handling for ``GTX``/``FOK`` time-in-force
    flags). Limit orders that do not cross the spread are parked as maker
    orders and their queue-ahead is tracked via the injected queue model
    as trades and depth updates arrive.
    """

    def __init__(
        self,
        queue_model=None,
        queue_model_power: float = 2.0,
        lot_size: float = 1.0,
        tick_size: float = None,
    ):
        """Initialize the queue-aware exchange model.

        Args:
            queue_model: Optional pre-built queue model. When ``None``, a
                :class:`backtrader.brokers.hft.queue.ProbQueueModel` is
                constructed from ``queue_model_power`` and ``lot_size``.
            queue_model_power: Power exponent forwarded to the default
                :class:`ProbQueueModel` when ``queue_model`` is ``None``.
            lot_size: Default lot size forwarded to the default
                :class:`ProbQueueModel` when ``queue_model`` is ``None``.
            tick_size: Optional price tick size. When provided, price
                equality is computed after rounding to this granularity so
                floating-point noise does not break maker/trade matching.
                ``None`` disables tick-based matching.
        """
        self._queue_model = queue_model or ProbQueueModel(
            power=queue_model_power, lot_size=lot_size
        )
        self._tick_size = float(tick_size) if tick_size is not None else None

    def on_new_order(self, order, ob_snapshot):
        """Park the order as a maker or fill it as a taker.

        Market orders are filled against depth. Crossing limit orders
        follow the taker path and honor ``GTX`` (reject when crossing)
        and ``FOK`` (reject when the full size cannot be filled) flags.
        Non-crossing limit orders are recorded by the queue model and
        returned as ``PENDING`` with the ``_fill_role`` tag set to
        :attr:`FillRole.MAKER`.

        Args:
            order: The newly accepted order.
            ob_snapshot: Order book snapshot at acceptance.

        Returns:
            OrderResult: ``"FILL"`` for takers, ``"PENDING"`` for resting
            makers, or ``"REJECT"`` for ``GTX``/``FOK`` violations.
        """
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
        """Drive maker fills from incoming trade events.

        For each resting maker order, check whether the trade price
        matches the order's price (within ``_tick_size`` if configured) and,
        if so, delegate to the queue model's ``update_on_trade``. Any
        resulting fill is appended in the form
        ``(order, price, quantity, role)``.

        Args:
            trade_event: The trade event to consume. Provides ``price`` and
                ``volume``.
            pending_orders: Resting orders that may be filled by this trade.

        Returns:
            list: ``(order, price, fillable_qty, FillRole.MAKER)`` tuples
            for orders that filled, possibly empty.
        """
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
        """Refresh each maker order's queue-ahead from the new depth.

        For every resting maker order, compute the previous and current
        depth at the order's price (respecting ``_tick_size``) and forward
        the pair to the queue model's ``update_on_depth``.

        Args:
            ob_event: Depth update event providing ``previous_bids`` /
                ``previous_asks`` (or empty) and ``bids`` / ``asks``.
            pending_orders: Resting orders to reconcile.

        Returns:
            list: Always empty in the current implementation; the method
            is called for its side effect of updating queue-ahead state.
        """
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
