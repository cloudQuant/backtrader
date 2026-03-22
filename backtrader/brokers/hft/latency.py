import bisect
import heapq


class LatencyModel:
    def feed_latency(self, exch_ts, symbol):
        raise NotImplementedError

    def order_entry_latency(self, local_ts, symbol):
        raise NotImplementedError

    def order_response_latency(self, exch_ts, symbol):
        raise NotImplementedError


class ConstantLatencyModel(LatencyModel):
    def __init__(self, feed_latency_ms=0, order_entry_latency_ms=0, order_response_latency_ms=0):
        self._feed_lat = feed_latency_ms / 1000.0
        self._entry_lat = order_entry_latency_ms / 1000.0
        self._resp_lat = order_response_latency_ms / 1000.0

    def feed_latency(self, exch_ts, symbol):
        _ = (exch_ts, symbol)
        return self._feed_lat

    def order_entry_latency(self, local_ts, symbol):
        _ = (local_ts, symbol)
        return self._entry_lat

    def order_response_latency(self, exch_ts, symbol):
        _ = (exch_ts, symbol)
        return self._resp_lat


class IntpLatencyModel(LatencyModel):
    def __init__(self, latency_data, latency_offset=0.0):
        self._offset = float(latency_offset)
        rows = sorted((float(row[0]), float(row[1]), float(row[2]), float(row[3])) for row in latency_data)
        self._ts = [row[0] for row in rows]
        self._feed = [row[1] for row in rows]
        self._entry = [row[2] for row in rows]
        self._resp = [row[3] for row in rows]

    def _interp(self, ts, values):
        if not self._ts:
            return 0.0
        lookup_ts = float(ts) + self._offset
        idx = bisect.bisect_left(self._ts, lookup_ts)
        if idx <= 0:
            return values[0]
        if idx >= len(self._ts):
            return values[-1]
        left_ts = self._ts[idx - 1]
        right_ts = self._ts[idx]
        left_val = values[idx - 1]
        right_val = values[idx]
        if right_ts == left_ts:
            return right_val
        ratio = (lookup_ts - left_ts) / (right_ts - left_ts)
        return left_val + (right_val - left_val) * ratio

    def feed_latency(self, exch_ts, symbol):
        _ = symbol
        return self._interp(exch_ts, self._feed)

    def order_entry_latency(self, local_ts, symbol):
        _ = symbol
        return self._interp(local_ts, self._entry)

    def order_response_latency(self, exch_ts, symbol):
        _ = symbol
        return self._interp(exch_ts, self._resp)


class LatencyEngine:
    def __init__(self, latency_model=None):
        self._model = latency_model
        self._pending_orders = []
        self._cancelled_order_ids = set()
        self._seq = 0

    def delay_order(self, order, submit_ts, symbol):
        if self._model is None:
            return None
        visible_ts = float(submit_ts) + float(self._model.order_entry_latency(submit_ts, symbol))
        if visible_ts <= float(submit_ts):
            return None
        heapq.heappush(self._pending_orders, (visible_ts, self._seq, order, symbol))
        self._seq += 1
        return visible_ts

    def cancel_order(self, order):
        self._cancelled_order_ids.add(id(order))

    def get_visible_orders(self, current_ts):
        visible = []
        now = float(current_ts)
        while self._pending_orders and self._pending_orders[0][0] <= now:
            _, _, order, symbol = heapq.heappop(self._pending_orders)
            if id(order) in self._cancelled_order_ids:
                self._cancelled_order_ids.discard(id(order))
                continue
            visible.append((order, symbol))
        return visible

    def apply_feed_latency(self, event):
        if self._model is None:
            setattr(event, "local_time", getattr(event, "timestamp", 0.0))
            return event
        exch_ts = getattr(event, "timestamp", 0.0)
        symbol = getattr(event, "symbol", "")
        setattr(event, "local_time", exch_ts + float(self._model.feed_latency(exch_ts, symbol)))
        return event

    def get_response_time(self, exch_ts, symbol):
        if self._model is None:
            return float(exch_ts)
        return float(exch_ts) + float(self._model.order_response_latency(exch_ts, symbol))
