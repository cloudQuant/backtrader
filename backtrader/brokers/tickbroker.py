"""Tick-level broker for unified tick and order book matching.

Provides TickBroker which matches orders against tick data and order book
snapshots instead of bar data, supporting realistic slippage, partial fills,
depth-aware matching, and all standard order types (Market, Limit, Stop,
StopLimit).

Example:
    Using TickBroker with Cerebro::

        cerebro = bt.Cerebro()
        cerebro.setbroker(TickBroker(cash=100000))
        cerebro.run(mode='TICK')
"""

import collections

from backtrader.broker import BrokerBase
from backtrader.brokers.hft import FillRole, LatencyEngine, MatchingCore, Recorder, StateTracker
from backtrader.order import BuyOrder, Order, SellOrder
from backtrader.parameters import ParameterDescriptor
from backtrader.position import Position
from backtrader.position_modes import (
    POSITION_MODE_DUAL_SIDE,
    POSITION_SIDE_LONG,
    POSITION_SIDE_SHORT,
    normalize_order_position_meta,
    normalize_position_mode,
    normalize_position_side,
    signed_position_size,
)

from ..utils.log_message import get_logger

logger = get_logger(__name__)

__all__ = ["TickBroker"]


class TickBroker(BrokerBase):
    """Broker that matches orders against tick-level data.

    Unlike BackBroker which processes orders at bar boundaries, TickBroker
    evaluates orders on every tick, enabling precise fill prices and
    realistic partial fill simulation.

    Params:
        cash: Starting cash (default: 100000.0).
        slippage_perc: Slippage as fraction of price (default: 0.0).
        slippage_fixed: Fixed slippage amount per trade (default: 0.0).
        allow_partial: Allow partial fills (default: True).
        checksubmit: Check cash before accepting orders (default: True).
        coo: Execute on Close-of-Order (default: False).
        coc: Execute on Close-of-Cancel (default: False).
        max_depth_levels: Maximum order book levels to traverse (default: 20).
        enable_impact: Enable market impact adjustments (default: False).
        shortcash: Increase cash when shorting stock-like assets (default: True).
        int2pnl: Assign generated interest to profit and loss (default: True).
    """

    cash = ParameterDescriptor(default=100000.0, doc="Starting cash")
    slippage_perc = ParameterDescriptor(default=0.0, doc="Slippage as fraction of price")
    slippage_fixed = ParameterDescriptor(default=0.0, doc="Fixed slippage amount")
    allow_partial = ParameterDescriptor(default=True, doc="Allow partial fills")
    checksubmit = ParameterDescriptor(default=True, doc="Check cash before accepting")
    coo = ParameterDescriptor(default=False, doc="Close-on-Open")
    coc = ParameterDescriptor(default=False, doc="Close-on-Close")
    max_depth_levels = ParameterDescriptor(default=20, doc="Max depth levels to traverse")
    enable_impact = ParameterDescriptor(default=False, doc="Enable market impact model")
    shortcash = ParameterDescriptor(
        default=True, doc="Increase cash when shorting stock-like assets"
    )
    int2pnl = ParameterDescriptor(default=True, doc="Assign generated interest to profit and loss")
    position_mode = ParameterDescriptor(default="net", doc="net | dual_side")

    def __init__(
        self,
        impact_model=None,
        latency_model=None,
        state_tracker=None,
        exchange_model=None,
        recorder=None,
        **kwargs,
    ):
        """Initialize the TickBroker.

        Sets up internal state for cash, positions, orders, and notifications.
        Uses default cash value from the 'cash' parameter.

        Args:
            impact_model: Optional market impact model for order book matching.
            latency_model: Optional latency model for order visibility.
            state_tracker: Optional state tracker instance.
            exchange_model: Optional exchange model for maker/taker and TIF semantics.
            recorder: Optional recorder used for timeline snapshots.
            **kwargs: Additional arguments passed to BrokerBase.
        """
        super().__init__(**kwargs)
        self._cash = self.get_param("cash")
        self._value = self._cash
        self._orders = []
        self._pending_orders = []
        self._order_history = []
        self._positions = collections.defaultdict(Position)
        self.positions = self._positions
        self.long_positions = collections.defaultdict(Position)
        self.short_positions = collections.defaultdict(Position)
        self._notifs = collections.deque()
        self._fundval = self._cash
        self._fundshares = 1.0
        self._fundmode = False
        self._last_tick = {}
        self._last_orderbook = {}
        self._impact_model = impact_model
        self._latency_model = latency_model
        self._exchange_model = exchange_model
        self._state_tracker_factory = state_tracker
        self._recorder_factory = recorder
        self._latency_engine = LatencyEngine(latency_model=latency_model)
        self._matching_core = MatchingCore(
            latency_engine=self._latency_engine,
            exchange_model=self._exchange_model,
        )
        self._state_tracker = state_tracker or StateTracker()
        self._recorder = recorder or Recorder()
        self._orders_by_symbol = collections.defaultdict(list)
        self._last_event_ts = 0.0
        self._tick_count = 0
        self._position_mode_frozen = False
        self._position_mode_frozen_reason = None
        BrokerBase.set_param(
            self, "position_mode", normalize_position_mode(self.get_param("position_mode"))
        )

    def start(self):
        """Initialize the broker state for a new backtesting run.

        Resets cash to the starting value and clears any previous state
        to ensure clean backtesting across multiple runs.
        """
        super().start()
        self._cash = self.get_param("cash")
        self._value = self._cash
        self._pending_orders = []
        self._order_history = []
        self._positions = collections.defaultdict(Position)
        self.positions = self._positions
        self.long_positions = collections.defaultdict(Position)
        self.short_positions = collections.defaultdict(Position)
        self._notifs = collections.deque()
        self._last_tick = {}
        self._last_orderbook = {}
        self._orders_by_symbol = collections.defaultdict(list)
        self._latency_engine = LatencyEngine(latency_model=self._latency_model)
        self._matching_core = MatchingCore(
            latency_engine=self._latency_engine,
            exchange_model=self._exchange_model,
        )
        self._state_tracker = self._state_tracker_factory or StateTracker()
        self._recorder = self._recorder_factory or Recorder()
        self._last_event_ts = 0.0
        self._tick_count = 0
        self._freeze_position_mode("start()")

    def set_param(self, name, value, validate=True):
        if name == "position_mode":
            self._ensure_position_mode_mutable()
            value = normalize_position_mode(value)
        return super().set_param(name, value, validate=validate)

    def _freeze_position_mode(self, reason):
        self._position_mode_frozen = True
        self._position_mode_frozen_reason = reason

    def _ensure_position_mode_mutable(self):
        if getattr(self, "_position_mode_frozen", False):
            raise ValueError(
                "position_mode is frozen after "
                f"{self._position_mode_frozen_reason} and cannot be changed at runtime"
            )

    def _is_dual_side_mode(self):
        return normalize_position_mode(self.get_param("position_mode")) == POSITION_MODE_DUAL_SIDE

    def _normalize_order_meta(self, isbuy, kwargs):
        local_kwargs = dict(kwargs)
        position_side = local_kwargs.pop("position_side", None)
        offset = local_kwargs.pop("offset", None)
        position_side, offset = normalize_order_position_meta(
            self.get_param("position_mode"),
            isbuy,
            position_side=position_side,
            offset=offset,
        )
        return position_side, offset, local_kwargs

    @staticmethod
    def _attach_position_meta(order, position_side=None, offset=None, **kwargs):
        if position_side is not None:
            order.addinfo(position_side=position_side)
        if offset is not None:
            order.addinfo(offset=offset)
        if kwargs:
            order.addinfo(**kwargs)
        return order

    def _get_leg_store(self, position_side):
        position_side = normalize_position_side(position_side)
        if position_side == POSITION_SIDE_LONG:
            return self.long_positions
        if position_side == POSITION_SIDE_SHORT:
            return self.short_positions
        raise ValueError(f"Unsupported position_side {position_side!r}")

    def _get_leg_position(self, symbol, position_side):
        return self._get_leg_store(position_side)[symbol]

    def _make_signed_position(self, position_side, position):
        signed_position = position.clone()
        signed_position.size = signed_position_size(position_side, position.size)
        if not signed_position.size:
            signed_position.price = 0.0
            signed_position.price_orig = 0.0
        return signed_position

    def _apply_signed_position(self, position_side, leg_position, signed_position):
        leg_position.size = abs(float(signed_position.size or 0.0))
        leg_position.price = signed_position.price if leg_position.size else 0.0
        leg_position.price_orig = signed_position.price_orig if leg_position.size else 0.0
        leg_position.adjbase = signed_position.adjbase
        leg_position.datetime = signed_position.datetime
        leg_position.updt = signed_position.updt
        leg_position.upopened = abs(float(signed_position.upopened or 0.0))
        leg_position.upclosed = abs(float(signed_position.upclosed or 0.0))
        return leg_position

    def _sync_net_position(self, symbol):
        long_pos = self.long_positions[symbol]
        short_pos = self.short_positions[symbol]
        net_pos = self._positions[symbol]
        net_size = long_pos.size - short_pos.size
        if net_size > 0:
            net_price = long_pos.price
        elif net_size < 0:
            net_price = short_pos.price
        else:
            net_price = 0.0
        net_pos.fix(net_size, net_price)
        if long_pos.datetime is not None and short_pos.datetime is not None:
            net_pos.datetime = max(long_pos.datetime, short_pos.datetime)
        else:
            net_pos.datetime = long_pos.datetime or short_pos.datetime
        net_pos.adjbase = long_pos.adjbase if long_pos.size else short_pos.adjbase
        return net_pos

    def stop(self):
        """Stop the broker and perform cleanup.

        Called at the end of a backtesting run. Override in subclasses
        to implement custom cleanup logic.
        """
        pass

    def getcash(self):
        """Get current available cash."""
        return self._cash

    def getvalue(self, datas=None):
        """Get portfolio value including open positions."""
        val = self._cash
        if self._is_dual_side_mode():
            symbols = set(self.long_positions) | set(self.short_positions) | set(self._positions)
            for symbol in symbols:
                last_tick = self._last_tick.get(symbol)
                if last_tick is None:
                    continue
                val += self.long_positions[symbol].size * last_tick.price
                val -= self.short_positions[symbol].size * last_tick.price
            return val

        for data_name, pos in self._positions.items():
            if pos.size != 0:
                last_tick = self._last_tick.get(data_name)
                if last_tick is not None:
                    val += pos.size * last_tick.price
        return val

    def getposition(self, data, side=None):
        """Get current position for a data feed."""
        name = getattr(data, "_name", None) or getattr(data, "symbol", str(data))
        if side is not None:
            if not self._is_dual_side_mode():
                raise ValueError("side-specific getposition() is only available in dual_side mode")
            return self._get_leg_position(name, side)
        if self._is_dual_side_mode():
            return self._sync_net_position(name)
        return self._positions[name]

    def submit(self, order):
        """Submit an order for execution.

        Overrides the default submit to handle tick-mode orders that
        don't have LineSeries data (avoids len(data) call in Order.submit).
        """
        self._freeze_position_mode("first order submission")
        order.status = Order.Submitted
        order.broker = self
        order.plen = 0
        self._matching_core.submit_order(order, current_ts=self._last_event_ts)
        if order in self._matching_core.pending_for_symbol(self._get_data_name(order.data)):
            self._queue_pending_order(order)
        self.notify(order)
        return order

    def cancel(self, order):
        """Cancel a pending order.

        Removes the order from the pending orders queue and updates its
        status to Cancelled. If the order is not found in the pending
        queue, the method returns silently.

        Args:
            order: The Order instance to cancel.
        """
        result = self._matching_core.cancel_order(order)
        if not result.success:
            return
        self._remove_pending_order(order)
        order.cancel()
        self.notify(order)

    def modify(self, order, size=None, price=None, plimit=None, exectype=None, **kwargs):
        """Modify an order by canceling it and submitting a replacement order."""
        if order not in self._pending_orders and not order.alive():
            return None

        tif = kwargs.pop("time_in_force", getattr(order, "time_in_force", None))
        replacement = order.__class__(
            owner=order.p.owner,
            data=order.data,
            size=size if size is not None else self._get_remaining_size(order),
            price=price if price is not None else order.price,
            pricelimit=plimit if plimit is not None else order.pricelimit,
            exectype=exectype if exectype is not None else order.exectype,
            valid=order.valid,
            tradeid=order.tradeid,
            oco=order.oco,
            trailamount=order.trailamount,
            trailpercent=order.trailpercent,
            simulated=True,
            **kwargs,
        )
        if tif is not None:
            replacement.time_in_force = tif

        for key, value in getattr(order, "info", {}).items():
            replacement.addinfo(**{key: value})

        self.cancel(order)
        order.addinfo(cancel_reason="MODIFY_REPLACED")
        replacement.addinfo(modified_from=order.ref)
        return self.submit(replacement)

    def buy(
        self,
        owner,
        data,
        size,
        price=None,
        plimit=None,
        exectype=None,
        valid=None,
        tradeid=0,
        oco=None,
        trailamount=None,
        trailpercent=None,
        **kwargs,
    ):
        """Create and submit a buy order.

        Args:
            owner: The strategy or object creating the order.
            data: The data feed for this order.
            size: Number of shares/contracts (positive for buy).
            price: Limit price for Limit orders.
            plimit: Limit price for StopLimit orders.
            exectype: Order execution type (Market, Limit, Stop, etc.).
            valid: Order validity period.
            tradeid: User-defined trade identifier.
            oco: One-Cancels-Other order group.
            trailamount: Trailing stop amount.
            trailpercent: Trailing stop percentage.
            **kwargs: Additional order parameters.

        Returns:
            The submitted BuyOrder instance.
        """
        position_side, offset, order_kwargs = self._normalize_order_meta(True, kwargs)
        order = BuyOrder(
            owner=owner,
            data=data,
            size=size,
            price=price,
            pricelimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            oco=oco,
            trailamount=trailamount,
            trailpercent=trailpercent,
            simulated=True,
        )
        self._attach_position_meta(
            order, position_side=position_side, offset=offset, **order_kwargs
        )
        return self.submit(order)

    def sell(
        self,
        owner,
        data,
        size,
        price=None,
        plimit=None,
        exectype=None,
        valid=None,
        tradeid=0,
        oco=None,
        trailamount=None,
        trailpercent=None,
        **kwargs,
    ):
        """Create and submit a sell order.

        Args:
            owner: The strategy or object creating the order.
            data: The data feed for this order.
            size: Number of shares/contracts (positive for sell).
            price: Limit price for Limit orders.
            plimit: Limit price for StopLimit orders.
            exectype: Order execution type (Market, Limit, Stop, etc.).
            valid: Order validity period.
            tradeid: User-defined trade identifier.
            oco: One-Cancels-Other order group.
            trailamount: Trailing stop amount.
            trailpercent: Trailing stop percentage.
            **kwargs: Additional order parameters.

        Returns:
            The submitted SellOrder instance.
        """
        position_side, offset, order_kwargs = self._normalize_order_meta(False, kwargs)
        order = SellOrder(
            owner=owner,
            data=data,
            size=size,
            price=price,
            pricelimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            oco=oco,
            trailamount=trailamount,
            trailpercent=trailpercent,
            simulated=True,
        )
        self._attach_position_meta(
            order, position_side=position_side, offset=offset, **order_kwargs
        )
        return self.submit(order)

    def notify(self, order):
        """Queue a notification for an order status change.

        Stores the order in an internal queue for later retrieval by
        strategies via get_notification().

        Args:
            order: The Order instance with updated status.
        """
        self._notifs.append(order.clone())

    def get_notification(self):
        """Get the next pending notification from the queue.

        Strategies call this method to check for order status updates.

        Returns:
            Order if a notification is available, None otherwise.
        """
        try:
            return self._notifs.popleft()
        except IndexError:
            return None

    def set_fundmode(self, fundmode, fundstartval=None):
        """Enable or disable fund mode for portfolio management.

        Fund mode allows treating the portfolio as a fund with shares
        that can be bought/sold by investors.

        Args:
            fundmode: Boolean to enable/disable fund mode.
            fundstartval: Initial fund value (optional).
        """
        self._fundmode = fundmode
        if fundstartval is not None:
            self._fundval = fundstartval

    def get_fundmode(self):
        """Check if fund mode is enabled.

        Returns:
            bool: True if fund mode is active, False otherwise.
        """
        return self._fundmode

    def get_fundshares(self):
        """Get the current number of fund shares.

        Returns:
            float: Number of outstanding fund shares.
        """
        return self._fundshares

    def get_fundvalue(self):
        """Get the current net asset value of the fund.

        Returns:
            float: Current fund NAV.
        """
        return self._fundval

    def process_tick(self, tick_event, data=None):
        """Process a tick event and attempt to match pending orders.

        This is the core method called by Cerebro on each tick. It evaluates
        all pending orders against the current tick data.

        Args:
            tick_event: TickEvent with current price/volume.
            data: The data feed associated with this tick (optional).
        """
        tick_event = self._latency_engine.apply_feed_latency(tick_event)
        data_name = tick_event.symbol
        current_ts = getattr(tick_event, "local_time", tick_event.timestamp)
        self._last_event_ts = current_ts
        self._last_tick[data_name] = tick_event
        self._tick_count += 1
        self._activate_visible_orders(current_ts)

        active_orders = [
            order
            for order in list(self._orders_by_symbol.get(data_name, []))
            if self._order_is_active_for_event(order, tick_event)
        ]

        matched = []
        if self._exchange_model is not None:
            for fill_order, fill_price, fill_size, fill_role in self._exchange_model.on_trade(
                tick_event, active_orders
            ):
                self._execute(fill_order, fill_price, fill_size, tick_event, source=fill_role.value)
                if not fill_order.alive() or not self.get_param("allow_partial"):
                    matched.append(fill_order)

        event_timestamp_ns = int(getattr(tick_event, "timestamp_ns", 0) or 0)
        for order in active_orders:
            if order in matched or getattr(order, "_fill_role", None) != FillRole.MAKER:
                continue
            if (
                float(getattr(order, "_queue_initial_ahead", 0.0)) > 1e-12
                and float(getattr(order, "_queue_ahead", 0.0)) <= 1e-12
                and float(getattr(order, "_queue_fillable", 0.0)) <= 1e-12
                and float(getattr(order, "_queue_trade_qty", 0.0)) > 1e-12
            ):
                order._queue_front_trade_timestamp_ns = event_timestamp_ns
                order._queue_front_trade_persisted_depth = False
            elif float(getattr(order, "_queue_ahead", 0.0)) > 1e-12:
                order._queue_front_trade_timestamp_ns = None
                order._queue_front_trade_persisted_depth = False

        for order in active_orders:
            if order in matched:
                continue
            if getattr(order, "_fill_role", None) == FillRole.MAKER:
                continue
            result = self._try_match(order, tick_event)
            if result is not None:
                fill_price, fill_size = result
                self._execute(order, fill_price, fill_size, tick_event)
                if not order.alive() or not self.get_param("allow_partial"):
                    matched.append(order)

        for order in matched:
            self._remove_pending_order(order)

    def process_orderbook(self, ob_event, data=None):
        """Process an order book snapshot and match pending orders.

        Args:
            ob_event: OrderBookSnapshot with current depth.
            data: The data feed associated with this snapshot (optional).
        """
        ob_event = self._latency_engine.apply_feed_latency(ob_event)
        data_name = ob_event.symbol
        current_ts = getattr(ob_event, "local_time", ob_event.timestamp)
        self._last_event_ts = current_ts
        previous_orderbook = self._last_orderbook.get(data_name)
        ob_event.previous_bids = list(getattr(previous_orderbook, "bids", []) or [])
        ob_event.previous_asks = list(getattr(previous_orderbook, "asks", []) or [])
        self._last_orderbook[data_name] = ob_event
        self._activate_visible_orders(current_ts)

        active_orders = [
            order
            for order in list(self._orders_by_symbol.get(data_name, []))
            if self._order_is_active_for_event(order, ob_event)
        ]
        for order in active_orders:
            order._queue_trade_qty_before_depth_update = float(
                getattr(order, "_queue_trade_qty", 0.0)
            )

        matched = []
        if self._exchange_model is not None:
            for (
                fill_order,
                fill_price,
                fill_size,
                fill_role,
            ) in self._exchange_model.on_depth_update(ob_event, active_orders):
                self._execute(fill_order, fill_price, fill_size, ob_event, source=fill_role.value)
                if not fill_order.alive() or not self.get_param("allow_partial"):
                    matched.append(fill_order)

        for order in active_orders:
            if order in matched:
                continue
            if self._exchange_model is not None and order.exectype in (Order.Market, Order.Limit):
                exchange_result = self._exchange_model.on_new_order(order, ob_event)
                if exchange_result.action == "REJECT":
                    order.addinfo(reject_reason=exchange_result.reject_reason)
                    order.reject(self)
                    self.notify(order)
                    self._order_history.append(
                        {
                            "timestamp": ob_event.timestamp,
                            "symbol": data_name,
                            "side": "buy" if order.isbuy() else "sell",
                            "status": "rejected",
                            "reason": exchange_result.reject_reason,
                            "source": "orderbook_depth",
                        }
                    )
                    matched.append(order)
                    continue
                if exchange_result.action == "FILL":
                    fill_price, fill_size = self._aggregate_exchange_fills(exchange_result.fills)
                    if fill_size > 0:
                        self._execute(
                            order, fill_price, fill_size, ob_event, source="orderbook_depth"
                        )
                    tif = getattr(order, "time_in_force", "GTC")
                    if tif == "IOC" and order.alive():
                        order.addinfo(cancel_reason="IOC_REMAINDER_CANCELLED")
                        order.cancel()
                        self.notify(order)
                        self._order_history.append(
                            {
                                "timestamp": ob_event.timestamp,
                                "symbol": data_name,
                                "side": "buy" if order.isbuy() else "sell",
                                "status": "canceled",
                                "reason": "IOC_REMAINDER_CANCELLED",
                                "source": "orderbook_depth",
                            }
                        )
                        matched.append(order)
                        continue
                    if not order.alive() or not self.get_param("allow_partial"):
                        matched.append(order)
                    continue

                if getattr(order, "_fill_role", None) == FillRole.MAKER:
                    if (
                        float(getattr(order, "_queue_initial_ahead", 0.0)) > 1e-12
                        and float(getattr(order, "_queue_ahead", 0.0)) > 1e-12
                    ):
                        event_timestamp_ns = int(getattr(ob_event, "timestamp_ns", 0) or 0)
                        if order.isbuy():
                            same_side_moved_away = not ob_event.bids or float(
                                ob_event.bids[0][0]
                            ) < float(order.price)
                            if (
                                same_side_moved_away
                                and getattr(
                                    order, "_queue_trade_remainder_confirmed_timestamp_ns", None
                                )
                                is not None
                                and event_timestamp_ns
                                == int(
                                    getattr(
                                        order, "_queue_trade_remainder_confirmed_timestamp_ns", None
                                    )
                                )
                            ):
                                fill_size = self._get_remaining_size(order)
                                if fill_size > 0:
                                    self._execute(
                                        order,
                                        float(order.price),
                                        fill_size,
                                        ob_event,
                                        source="orderbook_depth",
                                    )
                                    if not order.alive() or not self.get_param("allow_partial"):
                                        matched.append(order)
                                continue
                            if (
                                float(getattr(order, "_queue_trade_qty_before_depth_update", 0.0))
                                > 1e-12
                                and ob_event.bids
                                and float(ob_event.bids[0][0]) == float(order.price)
                                and abs(
                                    float(ob_event.bids[0][1])
                                    - float(getattr(order, "_queue_ahead", 0.0))
                                )
                                <= 1e-12
                            ):
                                order._queue_trade_remainder_confirmed_timestamp_ns = (
                                    event_timestamp_ns
                                )
                            elif getattr(
                                order, "_queue_trade_remainder_confirmed_timestamp_ns", None
                            ) is not None and event_timestamp_ns == int(
                                getattr(
                                    order, "_queue_trade_remainder_confirmed_timestamp_ns", None
                                )
                            ):
                                pass
                            else:
                                order._queue_trade_remainder_confirmed_timestamp_ns = None
                        else:
                            same_side_moved_away = not ob_event.asks or float(
                                ob_event.asks[0][0]
                            ) > float(order.price)
                            if (
                                same_side_moved_away
                                and getattr(
                                    order, "_queue_trade_remainder_confirmed_timestamp_ns", None
                                )
                                is not None
                                and event_timestamp_ns
                                == int(
                                    getattr(
                                        order, "_queue_trade_remainder_confirmed_timestamp_ns", None
                                    )
                                )
                            ):
                                fill_size = self._get_remaining_size(order)
                                if fill_size > 0:
                                    self._execute(
                                        order,
                                        float(order.price),
                                        fill_size,
                                        ob_event,
                                        source="orderbook_depth",
                                    )
                                    if not order.alive() or not self.get_param("allow_partial"):
                                        matched.append(order)
                                continue
                            if (
                                float(getattr(order, "_queue_trade_qty_before_depth_update", 0.0))
                                > 1e-12
                                and ob_event.asks
                                and float(ob_event.asks[0][0]) == float(order.price)
                                and abs(
                                    float(ob_event.asks[0][1])
                                    - float(getattr(order, "_queue_ahead", 0.0))
                                )
                                <= 1e-12
                            ):
                                order._queue_trade_remainder_confirmed_timestamp_ns = (
                                    event_timestamp_ns
                                )
                            elif getattr(
                                order, "_queue_trade_remainder_confirmed_timestamp_ns", None
                            ) is not None and event_timestamp_ns == int(
                                getattr(
                                    order, "_queue_trade_remainder_confirmed_timestamp_ns", None
                                )
                            ):
                                pass
                            else:
                                order._queue_trade_remainder_confirmed_timestamp_ns = None
                        order._queue_depleted_move_away_timestamp_ns = None
                        continue
                    event_timestamp_ns = int(getattr(ob_event, "timestamp_ns", 0) or 0)
                    queue_tracked = float(getattr(order, "_queue_initial_ahead", 0.0)) > 1e-12
                    if not queue_tracked:
                        order._queue_depleted_move_away_timestamp_ns = None
                        order._queue_front_trade_timestamp_ns = None
                        order._queue_front_trade_persisted_depth = False
                        order._queue_trade_remainder_confirmed_timestamp_ns = None
                        result = self._try_match_orderbook(order, ob_event)
                        if result is None:
                            continue
                        fill_price, fill_size = result
                        if fill_size <= 0:
                            continue
                        self._execute(
                            order, float(order.price), fill_size, ob_event, source="orderbook_depth"
                        )
                        if not order.alive() or not self.get_param("allow_partial"):
                            matched.append(order)
                        continue
                    same_side_moved_away = False
                    if order.isbuy():
                        same_side_moved_away = not ob_event.bids or float(
                            ob_event.bids[0][0]
                        ) < float(order.price)
                        front_trade_timestamp_ns = getattr(
                            order, "_queue_front_trade_timestamp_ns", None
                        )
                        if (
                            front_trade_timestamp_ns is not None
                            and event_timestamp_ns == int(front_trade_timestamp_ns)
                            and not same_side_moved_away
                        ):
                            order._queue_front_trade_persisted_depth = True
                            if (
                                ob_event.bids
                                and float(ob_event.bids[0][0]) == float(order.price)
                                and abs(
                                    float(ob_event.bids[0][1])
                                    - float(getattr(order, "_queue_ahead", 0.0))
                                )
                                <= 1e-12
                                and float(getattr(order, "_queue_ahead", 0.0)) > 1e-12
                            ):
                                order._queue_front_trade_remainder_confirmed_timestamp_ns = (
                                    event_timestamp_ns
                                )
                        if not same_side_moved_away:
                            if (
                                float(getattr(order, "_queue_trade_qty_before_depth_update", 0.0))
                                > 1e-12
                                and ob_event.bids
                                and float(ob_event.bids[0][0]) == float(order.price)
                                and abs(
                                    float(ob_event.bids[0][1])
                                    - float(getattr(order, "_queue_ahead", 0.0))
                                )
                                <= 1e-12
                                and float(getattr(order, "_queue_ahead", 0.0)) > 1e-12
                            ):
                                order._queue_trade_remainder_confirmed_timestamp_ns = (
                                    event_timestamp_ns
                                )
                        if not ob_event.asks or float(ob_event.asks[0][0]) >= float(order.price):
                            if queue_tracked and same_side_moved_away:
                                moved_away_timestamp_ns = getattr(
                                    order, "_queue_depleted_move_away_timestamp_ns", None
                                )
                                front_trade_timestamp_ns = getattr(
                                    order, "_queue_front_trade_timestamp_ns", None
                                )
                                front_trade_persisted_depth = bool(
                                    getattr(order, "_queue_front_trade_persisted_depth", False)
                                )
                                remainder_confirmed_timestamp_ns = getattr(
                                    order,
                                    "_queue_front_trade_remainder_confirmed_timestamp_ns",
                                    None,
                                )
                                trade_remainder_confirmed_timestamp_ns = getattr(
                                    order, "_queue_trade_remainder_confirmed_timestamp_ns", None
                                )
                                result = self._try_match_orderbook(order, ob_event)
                                if (
                                    result is not None
                                    and moved_away_timestamp_ns is not None
                                    and event_timestamp_ns == int(moved_away_timestamp_ns)
                                ):
                                    fill_price, fill_size = result
                                    if fill_size > 0:
                                        self._execute(
                                            order,
                                            float(order.price),
                                            fill_size,
                                            ob_event,
                                            source="orderbook_depth",
                                        )
                                        if not order.alive() or not self.get_param("allow_partial"):
                                            matched.append(order)
                                    continue
                                if (
                                    trade_remainder_confirmed_timestamp_ns is not None
                                    and event_timestamp_ns
                                    == int(trade_remainder_confirmed_timestamp_ns)
                                ):
                                    fill_size = self._get_remaining_size(order)
                                    if fill_size > 0:
                                        self._execute(
                                            order,
                                            float(order.price),
                                            fill_size,
                                            ob_event,
                                            source="orderbook_depth",
                                        )
                                        if not order.alive() or not self.get_param("allow_partial"):
                                            matched.append(order)
                                    continue
                                if (
                                    front_trade_timestamp_ns is not None
                                    and front_trade_persisted_depth
                                ):
                                    if (
                                        remainder_confirmed_timestamp_ns is not None
                                        and event_timestamp_ns
                                        == int(remainder_confirmed_timestamp_ns)
                                    ):
                                        fill_size = self._get_remaining_size(order)
                                        if fill_size > 0:
                                            self._execute(
                                                order,
                                                float(order.price),
                                                fill_size,
                                                ob_event,
                                                source="orderbook_depth",
                                            )
                                            if not order.alive() or not self.get_param(
                                                "allow_partial"
                                            ):
                                                matched.append(order)
                                        continue
                                    order._queue_depleted_move_away_timestamp_ns = None
                                    continue
                                if moved_away_timestamp_ns is None:
                                    if (
                                        front_trade_timestamp_ns is not None
                                        and event_timestamp_ns == int(front_trade_timestamp_ns)
                                        and not front_trade_persisted_depth
                                    ):
                                        fill_size = self._get_remaining_size(order)
                                        if fill_size > 0:
                                            self._execute(
                                                order,
                                                float(order.price),
                                                fill_size,
                                                ob_event,
                                                source="orderbook_depth",
                                            )
                                            if not order.alive() or not self.get_param(
                                                "allow_partial"
                                            ):
                                                matched.append(order)
                                        continue
                                    order._queue_depleted_move_away_timestamp_ns = (
                                        event_timestamp_ns
                                    )
                                    continue
                                if event_timestamp_ns <= int(moved_away_timestamp_ns):
                                    continue
                                fill_size = self._get_remaining_size(order)
                                if fill_size > 0:
                                    self._execute(
                                        order,
                                        float(order.price),
                                        fill_size,
                                        ob_event,
                                        source="orderbook_depth",
                                    )
                                    if not order.alive() or not self.get_param("allow_partial"):
                                        matched.append(order)
                                continue
                            order._queue_depleted_move_away_timestamp_ns = None
                            continue
                    else:
                        same_side_moved_away = not ob_event.asks or float(
                            ob_event.asks[0][0]
                        ) > float(order.price)
                        front_trade_timestamp_ns = getattr(
                            order, "_queue_front_trade_timestamp_ns", None
                        )
                        if (
                            front_trade_timestamp_ns is not None
                            and event_timestamp_ns == int(front_trade_timestamp_ns)
                            and not same_side_moved_away
                        ):
                            order._queue_front_trade_persisted_depth = True
                            if (
                                ob_event.asks
                                and float(ob_event.asks[0][0]) == float(order.price)
                                and abs(
                                    float(ob_event.asks[0][1])
                                    - float(getattr(order, "_queue_ahead", 0.0))
                                )
                                <= 1e-12
                                and float(getattr(order, "_queue_ahead", 0.0)) > 1e-12
                            ):
                                order._queue_front_trade_remainder_confirmed_timestamp_ns = (
                                    event_timestamp_ns
                                )
                        if not same_side_moved_away:
                            if (
                                float(getattr(order, "_queue_trade_qty_before_depth_update", 0.0))
                                > 1e-12
                                and ob_event.asks
                                and float(ob_event.asks[0][0]) == float(order.price)
                                and abs(
                                    float(ob_event.asks[0][1])
                                    - float(getattr(order, "_queue_ahead", 0.0))
                                )
                                <= 1e-12
                                and float(getattr(order, "_queue_ahead", 0.0)) > 1e-12
                            ):
                                order._queue_trade_remainder_confirmed_timestamp_ns = (
                                    event_timestamp_ns
                                )
                        if not ob_event.bids or float(ob_event.bids[0][0]) <= float(order.price):
                            if queue_tracked and same_side_moved_away:
                                moved_away_timestamp_ns = getattr(
                                    order, "_queue_depleted_move_away_timestamp_ns", None
                                )
                                front_trade_timestamp_ns = getattr(
                                    order, "_queue_front_trade_timestamp_ns", None
                                )
                                front_trade_persisted_depth = bool(
                                    getattr(order, "_queue_front_trade_persisted_depth", False)
                                )
                                remainder_confirmed_timestamp_ns = getattr(
                                    order,
                                    "_queue_front_trade_remainder_confirmed_timestamp_ns",
                                    None,
                                )
                                trade_remainder_confirmed_timestamp_ns = getattr(
                                    order, "_queue_trade_remainder_confirmed_timestamp_ns", None
                                )
                                result = self._try_match_orderbook(order, ob_event)
                                if (
                                    result is not None
                                    and moved_away_timestamp_ns is not None
                                    and event_timestamp_ns == int(moved_away_timestamp_ns)
                                ):
                                    fill_price, fill_size = result
                                    if fill_size > 0:
                                        self._execute(
                                            order,
                                            float(order.price),
                                            fill_size,
                                            ob_event,
                                            source="orderbook_depth",
                                        )
                                        if not order.alive() or not self.get_param("allow_partial"):
                                            matched.append(order)
                                    continue
                                if (
                                    trade_remainder_confirmed_timestamp_ns is not None
                                    and event_timestamp_ns
                                    == int(trade_remainder_confirmed_timestamp_ns)
                                ):
                                    fill_size = self._get_remaining_size(order)
                                    if fill_size > 0:
                                        self._execute(
                                            order,
                                            float(order.price),
                                            fill_size,
                                            ob_event,
                                            source="orderbook_depth",
                                        )
                                        if not order.alive() or not self.get_param("allow_partial"):
                                            matched.append(order)
                                    continue
                                if (
                                    front_trade_timestamp_ns is not None
                                    and front_trade_persisted_depth
                                ):
                                    if (
                                        remainder_confirmed_timestamp_ns is not None
                                        and event_timestamp_ns
                                        == int(remainder_confirmed_timestamp_ns)
                                    ):
                                        fill_size = self._get_remaining_size(order)
                                        if fill_size > 0:
                                            self._execute(
                                                order,
                                                float(order.price),
                                                fill_size,
                                                ob_event,
                                                source="orderbook_depth",
                                            )
                                            if not order.alive() or not self.get_param(
                                                "allow_partial"
                                            ):
                                                matched.append(order)
                                        continue
                                    order._queue_depleted_move_away_timestamp_ns = None
                                    continue
                                if moved_away_timestamp_ns is None:
                                    if (
                                        front_trade_timestamp_ns is not None
                                        and event_timestamp_ns == int(front_trade_timestamp_ns)
                                        and not front_trade_persisted_depth
                                    ):
                                        fill_size = self._get_remaining_size(order)
                                        if fill_size > 0:
                                            self._execute(
                                                order,
                                                float(order.price),
                                                fill_size,
                                                ob_event,
                                                source="orderbook_depth",
                                            )
                                            if not order.alive() or not self.get_param(
                                                "allow_partial"
                                            ):
                                                matched.append(order)
                                        continue
                                    order._queue_depleted_move_away_timestamp_ns = (
                                        event_timestamp_ns
                                    )
                                    continue
                                if event_timestamp_ns <= int(moved_away_timestamp_ns):
                                    continue
                                fill_size = self._get_remaining_size(order)
                                if fill_size > 0:
                                    self._execute(
                                        order,
                                        float(order.price),
                                        fill_size,
                                        ob_event,
                                        source="orderbook_depth",
                                    )
                                    if not order.alive() or not self.get_param("allow_partial"):
                                        matched.append(order)
                                continue
                            order._queue_depleted_move_away_timestamp_ns = None
                            continue
                    order._queue_depleted_move_away_timestamp_ns = None

            result = self._try_match_orderbook(order, ob_event)
            if result is None:
                continue

            fill_price, fill_size = result
            if fill_size <= 0:
                continue

            if getattr(order, "_fill_role", None) == FillRole.MAKER:
                fill_price = float(order.price)

            self._execute(order, fill_price, fill_size, ob_event, source="orderbook_depth")
            if not order.alive() or not self.get_param("allow_partial"):
                matched.append(order)

        for order in matched:
            self._remove_pending_order(order)

    def _try_match(self, order, tick):
        """Try to match an order against a tick.

        Args:
            order: The order to match.
            tick: The current TickEvent.

        Returns:
            Tuple of (fill_price, fill_size) if matched, None otherwise.
        """
        exectype = order.exectype
        price = tick.price
        size = order.remaining_size if hasattr(order, "remaining_size") else order.size

        if exectype == Order.Market:
            fill_price = self._apply_slippage(price, order.isbuy())
            return (fill_price, abs(size))

        elif exectype == Order.Limit:
            limit_price = order.price
            if order.isbuy():
                if price <= limit_price:
                    return (min(price, limit_price), abs(size))
            else:
                if price >= limit_price:
                    return (max(price, limit_price), abs(size))

        elif exectype == Order.Stop:
            stop_price = order.price
            if order.isbuy():
                if price >= stop_price:
                    fill_price = self._apply_slippage(price, True)
                    return (fill_price, abs(size))
            else:
                if price <= stop_price:
                    fill_price = self._apply_slippage(price, False)
                    return (fill_price, abs(size))

        elif exectype == Order.StopLimit:
            stop_price = order.price
            limit_price = order.pricelimit

            if not getattr(order, "_stop_triggered", False):
                if order.isbuy() and price >= stop_price:
                    order._stop_triggered = True
                elif not order.isbuy() and price <= stop_price:
                    order._stop_triggered = True

            if getattr(order, "_stop_triggered", False):
                if order.isbuy():
                    if price <= limit_price:
                        return (min(price, limit_price), abs(size))
                else:
                    if price >= limit_price:
                        return (max(price, limit_price), abs(size))

        return None

    def _try_match_orderbook(self, order, ob_event):
        """Try to match an order against order book depth levels.

        Args:
            order: The order to match.
            ob_event: The current OrderBookSnapshot.

        Returns:
            Tuple of (avg_fill_price, fill_size) or None.
        """
        exectype = order.exectype
        target_size = self._get_remaining_size(order)
        max_levels = self.get_param("max_depth_levels")

        if exectype == Order.Market:
            if order.isbuy():
                return self._match_buy_orderbook(ob_event.asks, target_size, max_levels, None)
            return self._match_sell_orderbook(ob_event.bids, target_size, max_levels, None)

        if exectype == Order.Limit:
            limit_price = order.price
            if order.isbuy():
                if ob_event.asks and ob_event.asks[0][0] <= limit_price:
                    return self._match_buy_orderbook(
                        ob_event.asks, target_size, max_levels, limit_price
                    )
            elif ob_event.bids and ob_event.bids[0][0] >= limit_price:
                return self._match_sell_orderbook(
                    ob_event.bids, target_size, max_levels, limit_price
                )

        if exectype == Order.Stop:
            stop_price = order.price
            if order.isbuy():
                if ob_event.asks and ob_event.asks[0][0] >= stop_price:
                    return self._match_buy_orderbook(ob_event.asks, target_size, max_levels, None)
            elif ob_event.bids and ob_event.bids[0][0] <= stop_price:
                return self._match_sell_orderbook(ob_event.bids, target_size, max_levels, None)

        return None

    def _match_buy_orderbook(self, asks, target_size, max_levels, limit_price):
        """Match a buy order against ask depth."""
        total_filled = 0.0
        total_cost = 0.0

        for level_index, (price, qty) in enumerate(asks):
            if level_index >= max_levels:
                break
            if limit_price is not None and price > limit_price:
                break

            remaining = target_size - total_filled
            fill_at_level = min(qty, remaining)

            if self.get_param("enable_impact") and self._impact_model:
                price = self._apply_market_impact(price, fill_at_level, is_buy=True)

            total_cost += price * fill_at_level
            total_filled += fill_at_level
            if total_filled >= target_size:
                break

        if total_filled <= 0:
            return None

        return (total_cost / total_filled, total_filled)

    def _match_sell_orderbook(self, bids, target_size, max_levels, limit_price):
        """Match a sell order against bid depth."""
        total_filled = 0.0
        total_revenue = 0.0

        for level_index, (price, qty) in enumerate(bids):
            if level_index >= max_levels:
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

        return (total_revenue / total_filled, total_filled)

    def _apply_slippage(self, price, is_buy):
        """Apply slippage to a fill price.

        Args:
            price: Base execution price.
            is_buy: True for buy orders, False for sell.

        Returns:
            Price with slippage applied.
        """
        perc = self.get_param("slippage_perc")
        fixed = self.get_param("slippage_fixed")

        slip = price * perc + fixed
        if is_buy:
            return price + slip
        else:
            return price - slip

    def _apply_market_impact(self, price, size, is_buy):
        """Apply a market impact model if enabled."""
        if self._impact_model is None:
            return price

        impact = self._impact_model.calculate_impact(price, size)
        if is_buy:
            return price + impact
        return price - impact

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

    @staticmethod
    def _resolve_commission_role(source):
        if source in {"maker", "taker"}:
            return source
        return "taker"

    def _execute(self, order, fill_price, fill_size, event, source="tick"):
        """Execute a fill on an order.

        Args:
            order: The order being filled.
            fill_price: The execution price.
            fill_size: The execution size.
            event: The event that triggered the fill.
            source: Source tag for order history.
        """
        if self._is_dual_side_mode():
            return self._execute_dual_side(order, fill_price, fill_size, event, source=source)
        data_name = self._get_data_name(order.data)
        position = self._positions[data_name]
        exec_size = fill_size if order.isbuy() else -fill_size
        comminfo = self.getcommissioninfo(order.data)
        commission_role = self._resolve_commission_role(source)
        pprice_orig = position.price
        psize, pprice, opened, closed = position.pseudoupdate(exec_size, fill_price)
        pnl = comminfo.profitandloss(-closed, pprice_orig, fill_price) if closed else 0.0

        cash = self._cash
        if closed:
            if self.get_param("shortcash"):
                closedvalue = comminfo.getvaluesize(-closed, pprice_orig)
            else:
                closedvalue = comminfo.getoperationcost(closed, pprice_orig)

            closecash = closedvalue
            if closedvalue > 0:
                closecash /= comminfo.get_leverage()
            cash += closecash + pnl * comminfo.stocklike
            closedcomm = comminfo.getcommission(closed, fill_price, role=commission_role)
            cash -= closedcomm
            if position.adjbase is not None:
                cash += comminfo.cashadjust(-closed, position.adjbase, fill_price)
        else:
            closedvalue = 0.0
            closedcomm = 0.0

        popened = opened
        if opened:
            if self.get_param("shortcash"):
                openedvalue = comminfo.getvaluesize(opened, fill_price)
            else:
                openedvalue = comminfo.getoperationcost(opened, fill_price)

            opencash = openedvalue
            if openedvalue > 0:
                opencash /= comminfo.get_leverage()
            cash -= opencash
            openedcomm = comminfo.getcommission(opened, fill_price, role=commission_role)
            cash -= openedcomm

            if cash < 0.0:
                opened = 0
                openedvalue = 0.0
                openedcomm = 0.0
            else:
                if abs(psize) > abs(opened) and position.adjbase is not None:
                    adjsize = psize - opened
                    cash += comminfo.cashadjust(adjsize, position.adjbase, fill_price)
                position.adjbase = fill_price
        else:
            openedvalue = 0.0
            openedcomm = 0.0

        self._cash = cash
        executed_size = closed + opened
        if not executed_size:
            if popened and not opened:
                order.margin()
                self.notify(order)
            return

        comminfo.confirmexec(executed_size, fill_price, role=commission_role)
        position.update(executed_size, fill_price, event.timestamp)
        order.execute(
            dt=event.timestamp,
            size=executed_size,
            price=fill_price,
            closed=closed,
            closedvalue=closedvalue,
            closedcomm=closedcomm,
            opened=opened,
            openedvalue=openedvalue,
            openedcomm=openedcomm,
            margin=comminfo.margin,
            pnl=pnl,
            psize=psize,
            pprice=pprice,
        )
        order.addcomminfo(comminfo)
        self.notify(order)
        self._state_tracker.on_fill(
            data_name,
            fill_price,
            executed_size,
            closedcomm + openedcomm,
            role=source,
        )

        self._order_history.append(
            {
                "timestamp": event.timestamp,
                "timestamp_ns": getattr(
                    event, "timestamp_ns", int(round(float(event.timestamp) * 1_000_000_000.0))
                ),
                "symbol": data_name,
                "side": "buy" if order.isbuy() else "sell",
                "status": order.getstatusname(),
                "price": fill_price,
                "size": abs(executed_size),
                "opened": opened,
                "closed": closed,
                "pnl": pnl,
                "commission": closedcomm + openedcomm,
                "source": source,
                "role": commission_role,
                "reference_price": getattr(event, "price", None),
                "order_ref": getattr(order, "ref", None),
            }
        )

        self._recorder.record(event.timestamp, data_name, self._order_history[-1])

        if popened and not opened:
            order.margin()
            self.notify(order)

    def _execute_dual_side(self, order, fill_price, fill_size, event, source="tick"):
        data_name = self._get_data_name(order.data)
        position_side = normalize_position_side(getattr(order.info, "position_side", None))
        leg_position = self._get_leg_position(data_name, position_side)
        signed_position = self._make_signed_position(position_side, leg_position)
        exec_size = fill_size if order.isbuy() else -fill_size
        offset = getattr(order.info, "offset", None)

        if offset == "close":
            available = abs(float(signed_position.size or 0.0))
            if available <= 1e-12:
                order.reject()
                self.notify(order)
                self._remove_pending_order(order)
                return
            if abs(float(exec_size or 0.0)) > available + 1e-12:
                exec_size = available if order.isbuy() else -available

        comminfo = self.getcommissioninfo(order.data)
        commission_role = self._resolve_commission_role(source)
        pprice_orig = signed_position.price
        psize, pprice, opened, closed = signed_position.pseudoupdate(exec_size, fill_price)
        pnl = comminfo.profitandloss(-closed, pprice_orig, fill_price) if closed else 0.0

        cash = self._cash
        if closed:
            if self.get_param("shortcash"):
                closedvalue = comminfo.getvaluesize(-closed, pprice_orig)
            else:
                closedvalue = comminfo.getoperationcost(closed, pprice_orig)

            closecash = closedvalue
            if closedvalue > 0:
                closecash /= comminfo.get_leverage()
            cash += closecash + pnl * comminfo.stocklike
            closedcomm = comminfo.getcommission(closed, fill_price, role=commission_role)
            cash -= closedcomm
            if signed_position.adjbase is not None:
                cash += comminfo.cashadjust(-closed, signed_position.adjbase, fill_price)
        else:
            closedvalue = 0.0
            closedcomm = 0.0

        popened = opened
        if opened:
            if self.get_param("shortcash"):
                openedvalue = comminfo.getvaluesize(opened, fill_price)
            else:
                openedvalue = comminfo.getoperationcost(opened, fill_price)

            opencash = openedvalue
            if openedvalue > 0:
                opencash /= comminfo.get_leverage()
            cash -= opencash
            openedcomm = comminfo.getcommission(opened, fill_price, role=commission_role)
            cash -= openedcomm

            if cash < 0.0:
                opened = 0
                openedvalue = 0.0
                openedcomm = 0.0
            else:
                if abs(psize) > abs(opened) and signed_position.adjbase is not None:
                    adjsize = psize - opened
                    cash += comminfo.cashadjust(adjsize, signed_position.adjbase, fill_price)
                signed_position.adjbase = fill_price
        else:
            openedvalue = 0.0
            openedcomm = 0.0

        self._cash = cash
        executed_size = closed + opened
        if not executed_size:
            if popened and not opened:
                order.margin()
                self.notify(order)
            return

        comminfo.confirmexec(executed_size, fill_price, role=commission_role)
        signed_position.update(executed_size, fill_price, event.timestamp)
        self._apply_signed_position(position_side, leg_position, signed_position)
        self._sync_net_position(data_name)
        order.execute(
            dt=event.timestamp,
            size=executed_size,
            price=fill_price,
            closed=closed,
            closedvalue=closedvalue,
            closedcomm=closedcomm,
            opened=opened,
            openedvalue=openedvalue,
            openedcomm=openedcomm,
            margin=comminfo.margin,
            pnl=pnl,
            psize=psize,
            pprice=pprice,
        )
        order.addcomminfo(comminfo)
        self.notify(order)
        self._state_tracker.on_fill(
            data_name,
            fill_price,
            executed_size,
            closedcomm + openedcomm,
            role=source,
        )

        self._order_history.append(
            {
                "timestamp": event.timestamp,
                "timestamp_ns": getattr(
                    event,
                    "timestamp_ns",
                    int(round(float(event.timestamp) * 1_000_000_000.0)),
                ),
                "symbol": data_name,
                "side": "buy" if order.isbuy() else "sell",
                "position_side": position_side,
                "offset": offset,
                "status": order.getstatusname(),
                "price": fill_price,
                "size": abs(executed_size),
                "opened": opened,
                "closed": closed,
                "pnl": pnl,
                "commission": closedcomm + openedcomm,
                "source": source,
                "role": commission_role,
                "reference_price": getattr(event, "price", None),
                "order_ref": getattr(order, "ref", None),
            }
        )

        self._recorder.record(event.timestamp, data_name, self._order_history[-1])

        if (
            offset == "close"
            and abs(self._get_leg_position(data_name, position_side).size) <= 1e-12
            and order.alive()
        ):
            order.cancel()
            order.addinfo(cancel_reason="POSITION_DEPLETED")
            self.notify(order)

        if popened and not opened:
            order.margin()
            self.notify(order)

    @staticmethod
    def _get_remaining_size(order):
        """Return remaining absolute size for an order."""
        remaining = getattr(getattr(order, "executed", None), "remsize", None)
        if remaining is None:
            remaining = order.size
        return abs(remaining)

    def next(self):
        """Called by Cerebro on each iteration.

        This is a no-op in tick mode since order matching happens via
        process_tick() instead. Provided for compatibility with bar mode.
        """
        pass

    def add_order_history(self, orders, notify=False):
        """Add historical orders to the broker.

        Allows preloading order history for replay scenarios.

        Args:
            orders: Iterable of Order instances to add.
            notify: Whether to trigger notifications for added orders.
        """
        pass

    def set_fund_history(self, fund):
        """Set historical fund data for replay scenarios.

        Args:
            fund: Historical fund value data.
        """
        pass

    @property
    def pending_orders(self):
        """List of currently pending orders."""
        return list(self._pending_orders)

    def state_values(self, data=None):
        """Return aggregated state values for one data feed or all symbols."""
        if data is not None:
            symbol = self._get_data_name(data)
            mid_price = getattr(self._last_tick.get(symbol), "price", None)
            return self._state_tracker.snapshot(
                symbol,
                self._positions[symbol].size,
                self._cash,
                mid_price,
            )

        positions = {symbol: pos.size for symbol, pos in self._positions.items()}
        mid_prices = {
            symbol: getattr(self._last_tick.get(symbol), "price", None)
            for symbol in set(self._state_tracker._states) | set(self._positions)
        }
        balances = {symbol: self._cash for symbol in mid_prices}
        return self._state_tracker.snapshot_all(positions, balances, mid_prices)

    @property
    def order_history(self):
        """Complete order execution history."""
        return list(self._order_history)

    @property
    def tick_count(self):
        """Number of ticks processed."""
        return self._tick_count

    def _get_data_name(self, data):
        return getattr(data, "_name", None) or getattr(data, "symbol", str(data))

    @staticmethod
    def _event_timestamp_ns(event):
        return int(
            getattr(
                event,
                "timestamp_ns",
                int(round(float(getattr(event, "timestamp", 0.0)) * 1_000_000_000.0)),
            )
        )

    def _order_is_active_for_event(self, order, event):
        active_after_ts = getattr(order, "_active_after_timestamp_ns", None)
        if active_after_ts is None:
            return True
        return self._event_timestamp_ns(event) > int(active_after_ts)

    def _order_is_queue_active_for_event(self, order, event):
        active_after_seq = getattr(order, "_active_after_event_seq", None)
        event_seq = getattr(event, "event_seq", None)
        if active_after_seq is not None and event_seq is not None:
            return int(event_seq) > int(active_after_seq)
        active_after_ts = getattr(order, "_active_after_timestamp_ns", None)
        if active_after_ts is None:
            return True
        return self._event_timestamp_ns(event) > int(active_after_ts)

    def _queue_pending_order(self, order):
        if order not in self._pending_orders:
            self._pending_orders.append(order)
        data_name = self._get_data_name(order.data)
        if order not in self._orders_by_symbol[data_name]:
            self._orders_by_symbol[data_name].append(order)

    def _remove_pending_order(self, order):
        try:
            self._pending_orders.remove(order)
        except ValueError:
            pass

        data_name = self._get_data_name(order.data)
        bucket = self._orders_by_symbol.get(data_name)
        if bucket is not None:
            try:
                bucket.remove(order)
            except ValueError:
                pass
            if not bucket:
                del self._orders_by_symbol[data_name]

        self._matching_core.remove_order(order)

    def _activate_visible_orders(self, current_ts):
        for order in self._matching_core.activate_orders(current_ts):
            self._queue_pending_order(order)

    @property
    def recorder(self):
        return self._recorder
