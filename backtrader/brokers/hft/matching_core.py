"""Order-matching core for the tick-level broker.

Defines the fill/match data structures (:class:`FillReport`, :class:`MatchResult`)
and the matching engine that turns tick/depth events plus pending orders into
fills, applying the configured exchange and queue models.
"""

from dataclasses import dataclass, field

from backtrader.order import Order

from .exchange import FillRole


@dataclass
class FillReport:
    """Single execution report produced by the matching engine.

    Attributes:
        order: The :class:`backtrader.order.Order` instance that was
            filled (kept by reference so callers can correlate the fill
            back to the originating strategy order).
        fill_price: Trade price at which this fill leg executed.
        fill_size: Signed quantity executed on this fill leg. Always
            positive; the side (buy/sell) is carried by ``order``.
        role: Whether this fill came from a taker or maker execution.
            ``"taker"`` for liquidity-taking orders and ``"maker"`` for
            passive orders that were resting in the book.
        timestamp: Simulation timestamp at which the fill happened
            (typically the upstream exchange or local-receive timestamp).
        source: Origin tag of the event that triggered the fill — usually
            ``"tick"`` for trade prints or ``"orderbook_depth"`` for
            top-of-book updates.
    """

    order: object
    fill_price: float
    fill_size: float
    role: str = "taker"
    timestamp: float = 0.0
    source: str = "tick"


@dataclass
class MatchResult:
    """Outcome of an operation against the matching engine.

    Attributes:
        action: One of ``"ACCEPTED"``, ``"REJECT"``, ``"MODIFIED"``,
            ``"CANCELED"``, ``"FILL"`` or ``"PENDING"`` describing what
            the matching engine did with the request/event.
        fills: List of :class:`FillReport` entries produced by this
            operation. Empty when no fill happened (e.g. an order was
            accepted but no market data was available yet).
        reject_reason: Human-readable explanation populated when
            ``action == "REJECT"``. Empty otherwise.
    """

    action: str
    fills: list = field(default_factory=list)
    reject_reason: str = ""


@dataclass
class CancelResult:
    """Outcome of an order cancellation request.

    Attributes:
        success: ``True`` if the order was found and removed from the
            matching engine's pending book; ``False`` otherwise.
        reason: Human-readable explanation populated when ``success`` is
            ``False`` (currently ``"ORDER_NOT_FOUND"`` when the order
            is not in the pending set). Empty for successful cancels.
    """

    success: bool
    reason: str = ""


class MatchingCore:
    """Tick/depth matching engine for the HFT broker.

    The matching core owns the pending-order book (per symbol) and
    reacts to incoming tick and order-book events by matching them
    against pending orders. The actual fill logic (price-time priority,
    slippage, queue position, etc.) is delegated to two pluggable
    helpers:

    * ``latency_engine`` — when provided, decides when a freshly
      submitted order becomes "visible" to the matching engine. While
      invisible the order is parked in the latency engine rather than
      in the core's pending buckets, and :meth:`activate_orders`
      promotes it once it becomes visible.
    * ``exchange_model`` — when provided, decides whether an incoming
      tick or order-book event actually triggers a fill for a pending
      order. The default internal matcher (``_match_tick_order`` /
      ``_match_orderbook_order``) implements a simple limit/market
      price-time matching, which is bypassed when the exchange model
      returns ``"FILL"`` or ``"REJECT"`` for the order.

    Attributes:
        _latency: Pluggable latency engine (``None`` to skip latency).
        _exchange_model: Pluggable exchange model (``None`` to use the
            built-in matcher).
        _pending_by_symbol: Mapping ``symbol -> list[Order]`` of orders
            that are currently sitting in the matching engine's book.
        _order_to_symbol: Mapping ``id(order) -> symbol`` used to look
            up the symbol of an order that the caller hands back via
            :meth:`cancel_order` / :meth:`remove_order` (the order
            itself does not always expose its symbol).
    """

    def __init__(self, latency_engine=None, exchange_model=None):
        """Initialize the matching core.

        Args:
            latency_engine: Optional pluggable latency engine. When
                supplied, freshly submitted orders are routed through it
                and only become visible to the matcher after the
                configured entry latency elapses (see
                :meth:`activate_orders`).
            exchange_model: Optional pluggable exchange model. When
                supplied, ``on_tick`` and ``on_orderbook`` delegate the
                fill decision to ``exchange_model.on_trade`` /
                ``exchange_model.on_new_order`` instead of using the
                built-in limit/market matcher.
        """
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
        """Submit a new order to the matching engine.

        If a latency engine is configured the order is first routed
        through it; orders that have not yet become visible (latency
        still pending) are kept inside the latency engine and will
        be promoted to the matching book later via
        :meth:`activate_orders`. Orders that are immediately visible —
        or for which no latency engine is configured — are appended
        to the per-symbol pending bucket.

        Args:
            order: Order object to submit. ``order.data`` is consulted
                to derive its trading symbol.
            current_ts: Simulation timestamp at which the submission
                happens. Forwarded to ``latency_engine.delay_order``
                when a latency engine is configured.

        Returns:
            MatchResult: ``MatchResult(action="ACCEPTED")``. The result
            is always ``ACCEPTED`` — rejections are signalled by the
            caller (e.g. broker) after inspecting fill notifications.
        """
        symbol = self._get_symbol(order)
        if self._latency is not None:
            visible_ts = self._latency.delay_order(order, current_ts, symbol)
            if visible_ts is not None:
                self._order_to_symbol[id(order)] = symbol
                return MatchResult(action="ACCEPTED")
        self._add_pending(order, symbol)
        return MatchResult(action="ACCEPTED")

    def modify_order(self, order, replacement_order, current_ts=0.0):
        """Replace ``order`` with ``replacement_order``.

        Modification is implemented as "cancel + resubmit": the original
        order is removed from the matching book and, if a replacement
        was supplied, it is re-submitted using the same
        :meth:`submit_order` path so that latency-engine rules apply
        uniformly.

        Args:
            order: Existing order to replace. Looked up in the pending
                book (and the latency engine when relevant).
            replacement_order: New order to submit in place of
                ``order``. ``None`` means "cancel only" — the operation
                succeeds but no replacement is queued.
            current_ts: Simulation timestamp at which the modification
                is being applied. Forwarded to :meth:`submit_order` for
                the replacement.

        Returns:
            MatchResult: ``MODIFIED`` when the original was successfully
            cancelled and the replacement was queued, ``CANCELED`` when
            no replacement was supplied, ``REJECT`` if the original
            could not be found in either the pending book or the
            latency engine.
        """
        cancel_result = self.cancel_order(order)
        if not cancel_result.success:
            return MatchResult(action="REJECT", reject_reason=cancel_result.reason)
        if replacement_order is None:
            return MatchResult(action="CANCELED")
        self.submit_order(replacement_order, current_ts=current_ts)
        return MatchResult(action="MODIFIED")

    def activate_orders(self, current_ts):
        """Promote orders whose entry latency has elapsed into the matching book.

        For every order that the latency engine reports as having
        become visible at ``current_ts``, the order is moved into the
        per-symbol pending bucket and returned in the activation list
        so that the caller (typically the broker) can run post-activation
        hooks (queue-position computation, etc.).

        Args:
            current_ts: Current simulation timestamp. Compared against
                the visibility timestamp returned by the latency
                engine.

        Returns:
            list[Order]: Orders that were activated at ``current_ts``.
            Empty when no latency engine is configured or when nothing
            has yet become visible.
        """
        if self._latency is None:
            return []
        activated = []
        for order, symbol in self._latency.get_visible_orders(current_ts):
            self._add_pending(order, symbol)
            activated.append(order)
        return activated

    def cancel_order(self, order):
        """Remove ``order`` from the matching engine (pending book or latency engine).

        The method first looks up the order's symbol via the
        ``_order_to_symbol`` cache (falling back to deriving it from
        ``order.data``), then attempts to remove it from the per-symbol
        pending bucket. If the order is not in the pending bucket but a
        latency engine is configured, the latency engine is asked to
        cancel it instead — useful for orders that have been submitted
        but not yet become visible.

        Args:
            order: Order to cancel. Must be the same object that was
                passed to :meth:`submit_order` / :meth:`modify_order`,
                because the engine identifies orders by ``id(order)``.

        Returns:
            CancelResult: ``CancelResult(success=True)`` when the order
            was removed from either the pending book or the latency
            engine; ``CancelResult(success=False,
            reason="ORDER_NOT_FOUND")`` otherwise.
        """
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
        """Silently drop ``order`` from the matching book without raising.

        Used by the broker when an order transitions to a terminal state
        (rejected, expired, margin-called) and the matching engine
        should forget about it. Unlike :meth:`cancel_order`, this method
        never returns a result and never raises — the absence of the
        order is not an error condition.

        Args:
            order: Order to forget. Looked up by ``id(order)`` first and
                falls back to deriving the symbol from ``order.data``.
        """
        symbol = self._order_to_symbol.pop(id(order), self._get_symbol(order))
        bucket = self._pending_by_symbol.get(symbol, [])
        try:
            bucket.remove(order)
        except ValueError:
            return
        if not bucket and symbol in self._pending_by_symbol:
            del self._pending_by_symbol[symbol]

    def pending_for_symbol(self, symbol):
        """Return a copy of the pending book for ``symbol``.

        The returned list is a snapshot; mutating it does not affect
        the engine's internal state.

        Args:
            symbol: Trading symbol to look up.

        Returns:
            list[Order]: Pending orders in arrival order for ``symbol``.
            Empty list if the symbol has no pending orders.
        """
        return list(self._pending_by_symbol.get(symbol, []))

    def pending_orders(self):
        """Return a flat snapshot of every pending order across all symbols.

        Returns:
            list[Order]: Pending orders across all symbols, in an
            unspecified but stable order (one bucket after another, in
            ``_pending_by_symbol`` insertion order).
        """
        result = []
        for bucket in self._pending_by_symbol.values():
            result.extend(bucket)
        return result

    def on_tick(self, tick_event):
        """Match a single trade tick against the pending book of its symbol.

        When an exchange model is configured, its
        ``on_trade(tick_event, pending_orders)`` is consulted first to
        generate fills; when no exchange model is set, the built-in
        limit/market matcher (:meth:`_match_tick_order`) is used
        instead. Orders whose ``_fill_role`` is :data:`FillRole.MAKER`
        are skipped from the built-in matcher because the exchange
        model is expected to drive their lifecycle.

        Args:
            tick_event: Tick-like object exposing ``symbol``,
                ``timestamp`` and ``price``. The exact type is not
                enforced — the engine only relies on these three
                attributes.

        Returns:
            MatchResult: ``MatchResult(action="FILL", fills=[...])`` if
            at least one fill was produced; otherwise
            ``MatchResult(action="PENDING", fills=[])``. The fills list
            holds one :class:`FillReport` per matched order.
        """
        symbol = getattr(tick_event, "symbol", "")
        fills = []
        pending = list(self.pending_for_symbol(symbol))
        if self._exchange_model is not None:
            for order, price, size, role in self._exchange_model.on_trade(tick_event, pending):
                fills.append(
                    self._build_fill(
                        order, price, size, tick_event.timestamp, source=role.value, role=role.value
                    )
                )

        for order in pending:
            if (
                self._exchange_model is not None
                and getattr(order, "_fill_role", None) == FillRole.MAKER
            ):
                continue
            result = self._match_tick_order(order, tick_event)
            if result is None:
                continue
            price, size = result
            fills.append(self._build_fill(order, price, size, tick_event.timestamp))

        return MatchResult(action="FILL" if fills else "PENDING", fills=fills)

    def on_orderbook(self, ob_event):
        """Match a single order-book snapshot against the pending book of its symbol.

        For each pending order of ``ob_event.symbol`` the method first
        consults the configured exchange model (``on_new_order``). If
        the model reports ``"REJECT"`` the engine short-circuits and
        returns a :class:`MatchResult` with that reject reason; if it
        reports ``"FILL"`` the aggregated fill price/size is recorded
        and the loop continues with the next order. Otherwise the
        built-in order-book matcher (:meth:`_match_orderbook_order`)
        runs and may produce a fill.

        Args:
            ob_event: Order-book event exposing ``symbol``,
                ``timestamp``, ``asks`` and ``bids``. ``asks``/``bids``
                are expected to be sequences of ``(price, qty)`` tuples
                sorted from best to worst.

        Returns:
            MatchResult: ``MatchResult(action="FILL", fills=[...])``
            when at least one fill was produced;
            ``MatchResult(action="REJECT", reject_reason=...)`` when
            the exchange model rejected an order;
            ``MatchResult(action="PENDING", fills=[])`` when no fill
            happened. The ``"REJECT"`` path returns immediately, so any
            remaining orders are not processed in the same call.
        """
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
                            self._build_fill(
                                order, price, size, ob_event.timestamp, source="orderbook_depth"
                            )
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
            limit_price = (
                order.pricelimit
                if getattr(order, "_stop_triggered", False) and order.exectype == Order.StopLimit
                else order.price
            )
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
            limit_price = (
                order.pricelimit
                if getattr(order, "_stop_triggered", False) and order.exectype == Order.StopLimit
                else order.price
            )
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
