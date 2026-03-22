class NoQueueModel:
    def estimate_queue_position(self, order, ob_snapshot):
        _ = (order, ob_snapshot)
        return 0.0

    def on_new_order(self, order, ob_snapshot):
        order._queue_ahead = self.estimate_queue_position(order, ob_snapshot)
        order._queue_initial_ahead = float(getattr(order, "_queue_ahead", 0.0))
        order._queue_trade_qty = 0.0
        order._queue_fillable = 0.0

    def update_on_trade(self, order, trade_event):
        remaining = getattr(getattr(order, "executed", None), "remsize", None)
        if remaining is None:
            remaining = getattr(order, "size", 0.0)
        trade_volume = abs(getattr(trade_event, "volume", 0.0))
        fillable = min(abs(remaining), trade_volume)
        order._queue_fillable = fillable
        return fillable

    def update_on_depth(self, order, prev_qty, new_qty):
        _ = prev_qty
        order._queue_ahead = min(max(0.0, float(getattr(order, "_queue_ahead", 0.0))), float(new_qty))
        order._queue_trade_qty = 0.0

    def is_filled(self, order):
        return float(getattr(order, "_queue_fillable", 0.0)) > 0.0


class ProbQueueModel:
    def __init__(self, power: float = 2.0, lot_size: float = 1.0):
        self.power = float(power)
        self.lot_size = float(lot_size)

    def estimate_queue_position(self, order, ob_snapshot):
        price = getattr(order, "price", None)
        if price is None:
            return 0.0
        levels = ob_snapshot.bids if order.isbuy() else ob_snapshot.asks
        for level_price, level_qty in levels:
            if level_price == price:
                return float(level_qty)
        return 0.0

    def on_new_order(self, order, ob_snapshot):
        order._queue_ahead = self.estimate_queue_position(order, ob_snapshot)
        order._queue_initial_ahead = float(getattr(order, "_queue_ahead", 0.0))
        order._queue_trade_qty = 0.0

    def _probability(self, front: float, back: float) -> float:
        front = max(0.0, float(front))
        back = max(0.0, float(back))
        denominator = back**self.power + front**self.power
        if denominator <= 0.0:
            return 1.0
        return back**self.power / denominator

    def update_on_trade(self, order, trade_event):
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
        queue_ahead = float(getattr(order, "_queue_ahead", 0.0))
        lot_size = abs(float(getattr(order, "_queue_lot_size", self.lot_size)))
        if lot_size <= 0.0:
            lot_size = 1.0
        exec_lots = int(round((-queue_ahead) / lot_size))
        if exec_lots > 0:
            order._queue_ahead = 0.0
            return exec_lots * lot_size
        return 0.0
