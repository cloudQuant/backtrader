"""Queue-position models for maker order fills in HFT simulation.

Defines :class:`NoQueueModel` (and probabilistic variants like
``ProbQueueModel``) that estimate how much volume sits ahead of a resting limit
order and how it gets consumed by trades/depth updates, driving realistic maker
fill timing in the tick matching engine.
"""


class NoQueueModel:
    """No-op queue model: resting orders fill instantly on a matching trade."""

    def estimate_queue_position(self, order, ob_snapshot):
        """Return a fixed zero queue-ahead for the resting order."""
        _ = (order, ob_snapshot)
        return 0.0

    def on_new_order(self, order, ob_snapshot):
        """Initialize the order's queue state to a no-queue configuration."""
        order._queue_ahead = self.estimate_queue_position(order, ob_snapshot)
        order._queue_initial_ahead = float(getattr(order, "_queue_ahead", 0.0))
        order._queue_trade_qty = 0.0
        order._queue_fillable = 0.0

    def update_on_trade(self, order, trade_event):
        """Mark the order fully fillable up to the available trade volume."""
        remaining = getattr(getattr(order, "executed", None), "remsize", None)
        if remaining is None:
            remaining = getattr(order, "size", 0.0)
        trade_volume = abs(getattr(trade_event, "volume", 0.0))
        fillable = min(abs(remaining), trade_volume)
        order._queue_fillable = fillable
        return fillable

    def update_on_depth(self, order, prev_qty, new_qty):
        """Clamp the queue-ahead to the latest depth at the order's price."""
        _ = prev_qty
        order._queue_ahead = min(
            max(0.0, float(getattr(order, "_queue_ahead", 0.0))), float(new_qty)
        )
        order._queue_trade_qty = 0.0

    def is_filled(self, order):
        """Return True when the no-queue model has any fillable volume."""
        return float(getattr(order, "_queue_fillable", 0.0)) > 0.0


class ProbQueueModel:
    """Probabilistic queue-position model for maker order fills.

    Estimates the volume that sits ahead of a resting limit order based on the
    displayed size at the order's price, then probabilistically consumes that
    volume as trades and depth updates arrive. The ``power`` argument
    parameterizes the front-vs-back-of-queue probability ratio (a value of 2
    approximates the classical Cont/Stoikov-style weighting), and ``lot_size``
    sets the discrete fill granularity.

    Attributes:
        power (float): Exponent used in the front/back probability ratio. A
            higher value biases fills toward the back of the queue, making
            position-dependent fill probability more pronounced.
        lot_size (float): Default lot size used when the order does not expose
            its own ``_queue_lot_size`` attribute, controlling the granularity
            of partial fills.
    """

    def __init__(self, power: float = 2.0, lot_size: float = 1.0):
        """Initialize the probabilistic queue model.

        Args:
            power: Exponent applied to the front/back-of-queue volumes when
                computing the probability that an incoming aggressor
                consumes a unit behind the resting order. Must be non-negative.
            lot_size: Fallback lot size used by :meth:`is_filled` to round
                fills to a discrete quantity. Must be strictly positive.
        """
        self.power = float(power)
        self.lot_size = float(lot_size)

    def estimate_queue_position(self, order, ob_snapshot):
        """Estimate the volume sitting ahead of ``order`` in its price level.

        Walks the appropriate side of the order book (``bids`` for buys,
        ``asks`` for sells) and returns the displayed quantity at the order's
        price level. If the order has no price or the price is not present in
        the snapshot, returns ``0.0``.

        Args:
            order: The resting order being modeled. Must expose ``price`` and
                an ``isbuy()`` method that returns ``True`` for buy orders.
            ob_snapshot: Order book snapshot providing ``bids`` and ``asks``
                as iterables of ``(price, quantity)`` tuples sorted with the
                best price first.

        Returns:
            float: Quantity (in base asset units) ahead of the order at its
            price level, or ``0.0`` when no price match is found.
        """
        price = getattr(order, "price", None)
        if price is None:
            return 0.0
        levels = ob_snapshot.bids if order.isbuy() else ob_snapshot.asks
        for level_price, level_qty in levels:
            if level_price == price:
                return float(level_qty)
        return 0.0

    def on_new_order(self, order, ob_snapshot):
        """Initialize the queue-tracking state on a freshly placed order.

        Records the initial queue-ahead (from
        :meth:`estimate_queue_position`), captures it as the baseline
        ``_queue_initial_ahead`` for later comparison, and resets the
        running trade-volume accumulator.

        Args:
            order: The newly accepted resting order that will participate in
                queue dynamics.
            ob_snapshot: Order book snapshot taken at the moment the order
                was accepted by the matching engine.
        """
        order._queue_ahead = self.estimate_queue_position(order, ob_snapshot)
        order._queue_initial_ahead = float(getattr(order, "_queue_ahead", 0.0))
        order._queue_trade_qty = 0.0

    def _probability(self, front: float, back: float) -> float:
        """Compute the probability that a consumed unit is behind this order.

        Uses the front/back ratio raised to ``self.power`` so that a small
        ``back`` (i.e. the order sits near the back of the queue) yields a
        low probability and a small ``front`` yields a high probability.

        Args:
            front: Quantity sitting ahead of this order at its price level.
            back: Quantity sitting behind this order at its price level.

        Returns:
            float: Probability in ``[0.0, 1.0]`` that the next consumed unit
            passes behind the resting order. Returns ``1.0`` if both
            quantities are zero.
        """
        front = max(0.0, float(front))
        back = max(0.0, float(back))
        denominator = back**self.power + front**self.power
        if denominator <= 0.0:
            return 1.0
        return back**self.power / denominator

    def update_on_trade(self, order, trade_event):
        """Consume a trade event and update the order's queue-ahead.

        Subtracts the absolute trade volume from the queue-ahead and
        accumulates it into ``_queue_trade_qty`` so the subsequent depth
        update can reconcile the displayed quantity against the volume
        that was already attributed to trades.

        Args:
            order: The resting order being tracked. The method mutates
                ``_queue_ahead``, ``_queue_trade_qty`` and ``_queue_fillable``
                on the order in place.
            trade_event: The trade event to consume. Must expose a
                ``volume`` attribute (absolute trade size).

        Returns:
            float: The fillable volume computed via :meth:`is_filled` after
            the trade has been applied (``0.0`` when nothing filled).
        """
        queue_ahead = float(getattr(order, "_queue_ahead", 0.0))
        trade_qty = abs(float(getattr(trade_event, "volume", 0.0)))
        if trade_qty <= 0.0:
            order._queue_fillable = 0.0
            return 0.0
        queue_ahead -= trade_qty
        order._queue_ahead = queue_ahead
        order._queue_trade_qty = float(getattr(order, "_queue_trade_qty", 0.0)) + trade_qty
        fillable = self.is_filled(order)
        order._queue_fillable = fillable
        return fillable

    def update_on_depth(self, order, prev_qty, new_qty):
        """Reconcile the order's queue-ahead against an updated depth value.

        The order book manager reports the new total size at the order's
        price level. The model first removes the volume already attributed
        to trades (kept in ``_queue_trade_qty``) and then estimates the new
        queue-ahead as a probabilistic blend of the previous front/back
        split.

        Args:
            order: The resting order being tracked. The method mutates
                ``_queue_ahead`` and ``_queue_trade_qty`` in place.
            prev_qty: Displayed quantity at the order's price level before
                the depth update.
            new_qty: Displayed quantity at the order's price level after
                the depth update.
        """
        change = float(prev_qty) - float(new_qty)
        queue_ahead = float(getattr(order, "_queue_ahead", 0.0))
        trade_qty = float(getattr(order, "_queue_trade_qty", 0.0))
        change -= trade_qty
        order._queue_trade_qty = 0.0
        if change < 0.0:
            order._queue_ahead = min(queue_ahead, float(new_qty))
            return
        front = queue_ahead
        back = float(prev_qty) - front
        probability = self._probability(front, back)
        estimate = front - (1.0 - probability) * change + min(back - probability * change, 0.0)
        order._queue_ahead = min(estimate, float(new_qty))

    def is_filled(self, order):
        """Compute the lot-rounded fillable volume for the order.

        When the queue-ahead has gone non-positive, the order has been
        fully consumed and the method returns the number of whole lots that
        would have filled, rescaled to absolute volume. Otherwise returns
        ``0.0``. The order's ``_queue_ahead`` is reset to zero when a
        positive fill is produced.

        Args:
            order: The resting order being tracked. The method mutates
                ``_queue_ahead`` when a positive fill is detected.

        Returns:
            float: Fillable volume rounded to whole lots (or ``0.0`` if the
            order has not been fully consumed).
        """
        queue_ahead = float(getattr(order, "_queue_ahead", 0.0))
        lot_size = abs(float(getattr(order, "_queue_lot_size", self.lot_size)))
        if lot_size <= 0.0:
            lot_size = 1.0
        exec_lots = int(round((-queue_ahead) / lot_size))
        if exec_lots > 0:
            order._queue_ahead = 0.0
            return exec_lots * lot_size
        return 0.0
