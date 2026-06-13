"""Latency models for HFT simulation.

Defines :class:`LatencyModel` and implementations (e.g.
:class:`ConstantLatencyModel`) that model feed, order-entry and order-response
delays so the tick matching engine can simulate realistic exchange round-trips.
"""

import bisect
import heapq


class LatencyModel:
    """Abstract interface for exchange round-trip latency models.

    A latency model returns, in seconds, how much delay a market-data feed,
    an order entry or an order response should incur. The three methods are
    kept separate so models can differentiate feed jitter from order-entry
    latency from exchange ack latency.
    """

    def feed_latency(self, exch_ts, symbol):
        """Return the feed latency (in seconds) for ``symbol`` at ``exch_ts``.

        Args:
            exch_ts: Exchange-side timestamp of the market-data event.
            symbol: Symbol the event is for.

        Returns:
            float: Latency in seconds to be added to ``exch_ts`` to obtain
            the local time at which the event is observed.
        """
        raise NotImplementedError

    def order_entry_latency(self, local_ts, symbol):
        """Return the order-entry latency (in seconds) for ``symbol``.

        Args:
            local_ts: Local time at which the order is submitted.
            symbol: Symbol the order is for.

        Returns:
            float: Latency in seconds between local submission and the
            order being visible to the exchange.
        """
        raise NotImplementedError

    def order_response_latency(self, exch_ts, symbol):
        """Return the order-response latency (in seconds) for ``symbol``.

        Args:
            exch_ts: Exchange-side timestamp of the acknowledgement.
            symbol: Symbol the response is for.

        Returns:
            float: Latency in seconds between the exchange producing the
            response and it being received locally.
        """
        raise NotImplementedError


class ConstantLatencyModel(LatencyModel):
    """Constant-latency model: a single value per stage, regardless of time.

    All three stages (feed, order entry, order response) use fixed
    per-stage values supplied in milliseconds at construction time. This
    is the simplest model and is typically used for deterministic tests.
    """

    def __init__(self, feed_latency_ms=0, order_entry_latency_ms=0, order_response_latency_ms=0):
        """Initialize the constant-latency model.

        Args:
            feed_latency_ms: Feed latency in milliseconds (default ``0``).
            order_entry_latency_ms: Order-entry latency in milliseconds
                (default ``0``).
            order_response_latency_ms: Order-response latency in
                milliseconds (default ``0``).
        """
        self._feed_lat = feed_latency_ms / 1000.0
        self._entry_lat = order_entry_latency_ms / 1000.0
        self._resp_lat = order_response_latency_ms / 1000.0

    def feed_latency(self, exch_ts, symbol):
        """Return the configured constant feed latency in seconds."""
        _ = (exch_ts, symbol)
        return self._feed_lat

    def order_entry_latency(self, local_ts, symbol):
        """Return the configured constant order-entry latency in seconds."""
        _ = (local_ts, symbol)
        return self._entry_lat

    def order_response_latency(self, exch_ts, symbol):
        """Return the configured constant order-response latency in seconds."""
        _ = (exch_ts, symbol)
        return self._resp_lat


class IntpLatencyModel(LatencyModel):
    """Time-varying latency model that linearly interpolates measured samples.

    Accepts a sequence of ``(timestamp, feed, entry, resp)`` rows. The
    rows are sorted by timestamp at construction time and lookups for an
    arbitrary query time are performed via linear interpolation between
    the two surrounding samples. The optional ``latency_offset`` is added
    to the query timestamp before lookup, so the same data set can be
    time-shifted without rebuilding the model.
    """

    def __init__(self, latency_data, latency_offset=0.0):
        """Initialize the interpolated latency model.

        Args:
            latency_data: Iterable of ``(timestamp, feed_latency,
                entry_latency, resp_latency)`` rows. The first column is
                the exchange-side timestamp (in seconds), the other three
                are the corresponding stage latencies in seconds.
            latency_offset: Optional offset (in seconds) added to the
                query timestamp before the binary search; useful for
                time-shifting an existing profile.
        """
        self._offset = float(latency_offset)
        rows = sorted(
            (float(row[0]), float(row[1]), float(row[2]), float(row[3])) for row in latency_data
        )
        self._ts = [row[0] for row in rows]
        self._feed = [row[1] for row in rows]
        self._entry = [row[2] for row in rows]
        self._resp = [row[3] for row in rows]

    def _interp(self, ts, values):
        """Linearly interpolate ``values`` at the time-shifted query time.

        Returns the first sample for queries before the first row, the
        last sample for queries past the last row, and a clamped linear
        interpolation in between. Returns ``0.0`` when the model has no
        samples at all.

        Args:
            ts: Query timestamp (will be offset by ``_offset``).
            values: Per-sample list of latencies (in seconds) sorted in
                the same order as ``_ts``.

        Returns:
            float: Interpolated latency in seconds.
        """
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
        """Return the interpolated feed latency for ``exch_ts``."""
        _ = symbol
        return self._interp(exch_ts, self._feed)

    def order_entry_latency(self, local_ts, symbol):
        """Return the interpolated order-entry latency for ``local_ts``."""
        _ = symbol
        return self._interp(local_ts, self._entry)

    def order_response_latency(self, exch_ts, symbol):
        """Return the interpolated order-response latency for ``exch_ts``."""
        _ = symbol
        return self._interp(exch_ts, self._resp)


class LatencyEngine:
    """Drives the per-stage latencies for orders and events.

    Holds the priority queue of in-flight orders (sorted by the time at
    which they should become visible to the exchange) and the set of
    order ids that have been cancelled before they became visible. When
    no latency model is supplied, the engine degenerates to a pass-through
    that returns events and orders without applying any delay.
    """

    def __init__(self, latency_model=None):
        """Initialize the latency engine.

        Args:
            latency_model: Optional :class:`LatencyModel` used to compute
                per-stage delays. ``None`` disables all delays.
        """
        self._model = latency_model
        self._pending_orders = []
        self._cancelled_order_ids = set()
        self._seq = 0

    def delay_order(self, order, submit_ts, symbol):
        """Park an order in the visibility queue based on entry latency.

        Args:
            order: The order that was just submitted locally.
            submit_ts: Local timestamp of the submission.
            symbol: Symbol the order is for.

        Returns:
            float | None: The exchange-visible timestamp the order will
            become visible at, or ``None`` if latency is disabled
            (``latency_model is None``) or the computed delay is
            non-positive.
        """
        if self._model is None:
            return None
        visible_ts = float(submit_ts) + float(self._model.order_entry_latency(submit_ts, symbol))
        if visible_ts <= float(submit_ts):
            return None
        heapq.heappush(self._pending_orders, (visible_ts, self._seq, order, symbol))
        self._seq += 1
        return visible_ts

    def cancel_order(self, order):
        """Mark an in-flight order as cancelled.

        Cancelled orders are removed from the pending queue the next time
        they would have become visible, so the matching engine never sees
        them.

        Args:
            order: The order to cancel (identified by ``id(order)``).
        """
        self._cancelled_order_ids.add(id(order))

    def get_visible_orders(self, current_ts):
        """Pop and return all orders whose visibility time has been reached.

        The order heap is sorted by ``(visible_ts, sequence)``, so equal
        timestamps are popped in submission order. Any order whose id was
        previously passed to :meth:`cancel_order` is discarded and its id
        is removed from the cancelled set.

        Args:
            current_ts: Current local time used to determine which orders
                have become visible.

        Returns:
            list[tuple]: ``(order, symbol)`` tuples for the orders that
            should be released to the matching engine.
        """
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
        """Set ``local_time`` on ``event`` after applying feed latency.

        The event is mutated in place by setting a ``local_time`` attribute
        equal to the exchange timestamp plus the model's feed latency. If
        no model is configured, ``local_time`` is set to the event's
        ``timestamp`` (i.e. no delay).

        Args:
            event: The market-data event to adjust. Must expose
                ``timestamp`` and (optionally) ``symbol``.

        Returns:
            object: The same event object, for convenient chaining.
        """
        if self._model is None:
            setattr(event, "local_time", getattr(event, "timestamp", 0.0))
            return event
        exch_ts = getattr(event, "timestamp", 0.0)
        symbol = getattr(event, "symbol", "")
        setattr(event, "local_time", exch_ts + float(self._model.feed_latency(exch_ts, symbol)))
        return event

    def get_response_time(self, exch_ts, symbol):
        """Return the local time at which an exchange ack is received.

        Args:
            exch_ts: Exchange-side timestamp of the acknowledgement.
            symbol: Symbol the response is for.

        Returns:
            float: ``exch_ts`` plus the model's order-response latency, or
            ``exch_ts`` itself when no model is configured.
        """
        if self._model is None:
            return float(exch_ts)
        return float(exch_ts) + float(self._model.order_response_latency(exch_ts, symbol))
