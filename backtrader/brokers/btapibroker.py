#!/usr/bin/env python
"""Unified bt_api_py-backed live broker."""

from __future__ import annotations

import collections
import datetime as _dt
import time
from copy import deepcopy
from typing import Any

from ..broker import BrokerBase
from ..comminfo import (
    ComminfoFuturesFixed,
    ComminfoFuturesInverse,
    ComminfoFuturesMixed,
    ComminfoFuturesPercent,
)
from ..order import BuyOrder, SellOrder
from ..position import Position
from ..position_modes import (
    POSITION_MODE_DUAL_SIDE,
    infer_position_side,
    normalize_order_position_meta,
    normalize_position_mode,
    normalize_position_side,
    signed_position_size,
)
from ..utils.log_message import get_logger

logger = get_logger(__name__)

_REMOTE_ORDER_ID_KEYS = (
    "external_order_id",
    "externalOrderId",
    "venue_order_id",
    "venueOrderId",
    "ordId",
    "orderID",
    "order_id",
    "orderId",
    "OrderID",
    "OrderSysID",
    "id",
    "ticket",
)
_REMOTE_TRADE_ORDER_ID_KEYS = (
    "external_order_id",
    "externalOrderId",
    "venue_order_id",
    "venueOrderId",
    "ordId",
    "orderID",
    "order_id",
    "orderId",
    "OrderID",
    "OrderSysID",
    "order",
    "ticket",
)
_REMOTE_CLIENT_ORDER_REF_KEYS = (
    "order_ref",
    "orderRef",
    "ctp_order_ref",
    "OrderRef",
    "client_order_id",
    "clientOrderId",
    "newClientOrderId",
    "origClientOrderId",
    "clOrdId",
    "origClOrdId",
    "orderLinkId",
    "origOrderLinkId",
)
_DATA_NAME_KEYS = (
    "data_name",
    "dataname",
    "symbol",
    "instrument",
    "instId",
    "inst_id",
    "InstrumentID",
    "instrument_id",
    "name",
)
_CTP_EXCHANGES = frozenset({"SHFE", "DCE", "CZCE", "CFFEX", "INE", "GFEX"})
_POSITION_SIZE_KEYS = (
    "volume",
    "size",
    "position",
    "position_size",
    "positionSize",
    "position_qty",
    "positionQty",
    "positionAmt",
    "position_amt",
    "qty",
    "quantity",
    "pos",
    "Position",
    "Volume",
    "Qty",
    "Quantity",
)
_POSITION_DIRECTION_KEYS = (
    "direction",
    "Direction",
    "side",
    "Side",
    "position_side",
    "positionSide",
    "positionIdx",
    "position_idx",
    "posSide",
    "PositionSide",
    "position_direction",
    "positionDirection",
    "PosiDirection",
    "posi_direction",
)
_POSITION_PRICE_KEYS = (
    "price",
    "Price",
    "avg_price",
    "avgPrice",
    "avgPx",
    "average_price",
    "averagePrice",
    "entry_price",
    "entryPrice",
    "open_price",
    "openAvgPx",
)
_FILL_QTY_KEYS = (
    "size",
    "volume",
    "trade_volume",
    "last_qty",
    "lastQty",
    "exec_qty",
    "execQty",
    "execution_qty",
    "fill_size",
    "fillSize",
    "fill_qty",
    "fillQty",
    "fillSz",
    "lastSz",
    "qty",
    "quantity",
    "sz",
)
_CUMULATIVE_FILL_QTY_KEYS = (
    "filled",
    "cum_qty",
    "cumQty",
    "cum_filled_qty",
    "cumFilledQty",
    "cum_quantity",
    "cumulative_qty",
    "cumulative_quantity",
    "filled_qty",
    "filled_quantity",
    "filledVolume",
    "FilledVolume",
    "traded",
    "traded_volume",
    "volume_traded",
    "VolumeTraded",
    "accFillSz",
    "acc_fill_sz",
    "accFillSize",
    "acc_fill_size",
)
_SUBMIT_FILL_QTY_KEYS = (
    *_CUMULATIVE_FILL_QTY_KEYS,
    "volume",
    "fillSz",
    "fill_size",
    "fillSize",
    "fill_qty",
    "fillQty",
    "qty",
    "quantity",
    "sz",
)
_FILL_PRICE_KEYS = (
    "price",
    "Price",
    "fill_price",
    "fillPrice",
    "fill_px",
    "fillPx",
    "exec_price",
    "execPrice",
    "execution_price",
    "executionPrice",
    "trade_price",
    "tradePrice",
    "avg_price",
    "avgPrice",
    "avgPx",
    "average_price",
    "averagePrice",
    "last_price",
    "lastPrice",
    "lastPx",
    "px",
)


class BtApiBroker(BrokerBase):
    """Broker implementation that routes live orders through BtApiStore."""

    params = (
        ("store", None),
        ("provider", "btapi"),
        ("cash", 0.0),
        ("value", None),
        ("account_refresh_interval", 1.0),
        ("positions_refresh_interval", 1.0),
        ("open_orders_refresh_interval", 1.0),
        ("cancel_wait_remote", False),
        ("force_refresh_queries", True),
        ("validation_enabled", True),
        ("contract_metadata", None),
        ("max_order_size", 0),
        ("cash_check_enabled", True),
        ("cash_buffer", 0.0),
        ("cash_check_safety_factor", 1.0),
        ("pending_trade_update_limit", 256),
        ("position_mode", "net"),
    )

    def __init__(self, **kwargs):
        """Initialize the broker, set up order/position state and freeze position mode.

        The constructor wires the broker to its underlying
        :class:`BtApiStore`, allocates the in-memory collections used to
        track orders, positions (split by long/short leg in dual-side
        mode) and outbound notifications, and seeds the cash/value
        snapshots that :meth:`getcash` / :meth:`getvalue` will report
        before the first :meth:`start`.

        Args:
            **kwargs: Parameter overrides. Any key matching a name in
                :attr:`params` overrides the corresponding default; unknown
                keys are forwarded to the :class:`BrokerBase` constructor.
        """
        super().__init__(**kwargs)
        self.store = self.p.store
        self.provider = self.p.provider
        self.notifs: collections.deque = collections.deque()
        self.orders = collections.OrderedDict()
        self.positions = collections.defaultdict(Position)
        self.long_positions = collections.defaultdict(Position)
        self.short_positions = collections.defaultdict(Position)
        self._cash = float(self.p.cash or 0.0)
        self._value = float(self.p.value if self.p.value is not None else self._cash)
        self._live_started = False
        self.startingcash = self._cash
        self.startingvalue = self._value
        self._last_account_refresh = 0.0
        self._last_positions_refresh = 0.0
        self._last_open_orders_refresh = 0.0
        self._trading_enabled = True
        self._strategy_paused = False
        self._contract_metadata = {
            str(key): dict(value or {}) for key, value in (self.p.contract_metadata or {}).items()
        }
        self._orders_by_external_id = {}
        self._orders_by_client_ref = {}
        self._remote_open_orders_snapshot = []
        self._seen_trade_ids = set()
        self._pending_trade_updates: collections.deque[Any] = collections.deque()
        self._status_fill_fingerprints: collections.Counter[Any] = collections.Counter()
        self._position_mode_frozen = False
        self._position_mode_frozen_reason = None
        BrokerBase.set_param(
            self, "position_mode", normalize_position_mode(self.get_param("position_mode"))
        )

    def start(self):
        """Start the broker and hydrate account state from the store."""
        super().start()

        if self.store is None:
            raise ValueError("BtApiBroker requires a BtApiStore instance")

        if self._live_started and self.store.is_connected:
            return

        if not self.supports_position_mode(self.get_param("position_mode")):
            raise ValueError(
                f"Provider {self.provider!r} does not advertise support for "
                f"position_mode={self.get_param('position_mode')!r}"
            )

        self.store.start(broker=self)
        self._live_started = True
        self._refresh_account(force=True, raise_errors=True)
        self._sync_positions(force=True, raise_errors=True)
        self._warm_contract_metadata()
        self._sync_remote_open_orders(force=True)
        self.startingcash = self._cash
        self.startingvalue = self._value
        self._freeze_position_mode("start()")

    def set_param(self, name, value, validate=True):
        """Override :meth:`BrokerBase.set_param` to guard ``position_mode`` changes.

        The ``position_mode`` parameter is treated specially: it is
        immutable once :meth:`start` has run (frozen via
        :meth:`_freeze_position_mode`), and its raw value is normalized
        through :func:`normalize_position_mode` so that the broker
        always stores one of the canonical ``"net"`` /
        ``"dual_side"`` strings.

        Args:
            name: Name of the parameter to set.
            value: New value for the parameter. For ``position_mode`` the
                value is normalized before being applied.
            validate: When ``True`` (default), delegate to the base class
                so that the registered validator runs. Set to ``False``
                to bypass validation (used internally when applying
                normalized values).

        Returns:
            The return value of :meth:`BrokerBase.set_param` after the
            value has been applied.

        Raises:
            ValueError: If ``name == "position_mode"`` and the parameter
                has already been frozen by :meth:`start`.
        """
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

    def supports_position_mode(self, mode):
        """Return whether the broker can operate in the requested position mode.

        Any non-dual-side mode (``"net"`` or its aliases) is always
        supported because it does not require special handling from the
        underlying store. Dual-side mode is supported when:

        * the underlying store advertises it via
          ``store.supports_position_mode("dual_side")``, or
        * the broker-level contract metadata declares
          ``supports_dual_side`` / ``position_mode == "dual_side"``.

        Args:
            mode: Position mode to check. Any value accepted by
                :func:`normalize_position_mode` may be passed.

        Returns:
            bool: ``True`` if the broker can run in ``mode``, ``False``
            otherwise.
        """
        mode = normalize_position_mode(mode)
        if mode != POSITION_MODE_DUAL_SIDE:
            return True
        if self.store is not None and hasattr(self.store, "supports_position_mode"):
            try:
                return bool(self.store.supports_position_mode(mode))
            except Exception as exc:
                logger.debug("Failed to query store position mode capability: %s", exc)
        broker_meta = self._contract_metadata.get("__broker__", {})
        return bool(
            broker_meta.get("supports_dual_side")
            or str(broker_meta.get("position_mode", "")).lower() == POSITION_MODE_DUAL_SIDE
        )

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
        if position_side == "long":
            return self.long_positions
        if position_side == "short":
            return self.short_positions
        raise ValueError(f"Unsupported position_side {position_side!r}")

    def _get_leg_position(self, data, position_side):
        return self._get_leg_store(position_side)[self._position_key(data)]

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

    def _sync_net_position(self, data):
        key = self._position_key(data)
        long_pos = self.long_positions[key]
        short_pos = self.short_positions[key]
        net_pos = self.positions[key]
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
        """Stop the broker."""
        self._live_started = False
        if (
            self.store is not None
            and self.store.is_connected
            and getattr(self.store, "_cerebro_managed_lifecycle", True) is not False
        ):
            self.store.stop()

    def getcash(self) -> float:
        """Return current available cash."""
        self._refresh_account(force=bool(self.p.force_refresh_queries), raise_errors=True)
        return self._cash

    def getvalue(self, datas=None) -> float:
        """Return current portfolio value."""
        self._refresh_account(force=bool(self.p.force_refresh_queries), raise_errors=True)
        return self._value

    def getposition(self, data, clone=True, side=None):
        """Return the cached position for a given data feed."""
        self._sync_positions(force=bool(self.p.force_refresh_queries), raise_errors=True)
        if side is not None:
            if not self._is_dual_side_mode():
                raise ValueError("side-specific getposition() is only available in dual_side mode")
            position = self._get_leg_position(data, side)
        else:
            key = self._position_key(data)
            position = (
                self._sync_net_position(data) if self._is_dual_side_mode() else self.positions[key]
            )
        return position.clone() if clone else position

    def submit(self, order):
        """Submit an order through the store."""
        self._freeze_position_mode("first order submission")
        try:
            offset_error = self._ensure_required_net_offset(order)
            if offset_error is not None:
                code, message = offset_error
                return self._reject_order(order, code, message)
            validation_error = self._validate_order(order)
            if validation_error is not None:
                code, message = validation_error
                return self._reject_order(order, code, message)
        except Exception as exc:
            return self._reject_order(
                order,
                "pre_trade_state_refresh_failed",
                f"Pre-trade account/position refresh failed: {exc}",
            )

        if not self._trading_enabled:
            return self._reject_order(
                order,
                "trading_disabled",
                "Trading is currently disabled for this broker session",
            )

        if self._strategy_paused:
            return self._reject_order(
                order,
                "strategy_paused",
                "Strategy order routing is currently paused",
            )

        try:
            order.submit(self)
            order.addcomminfo(self.getcommissioninfo(order.data))
            if self.store is None:
                raise ValueError("BtApiBroker requires a BtApiStore instance")
            response = self.store.submit_order(order)
            submit_error = self._submit_response_error(response)
            if submit_error is not None:
                error_code, error_msg = submit_error
                return self._reject_order(order, error_code, error_msg)
            order.accept(self)

            external_order_id = (
                self._remote_external_order_id(response) if isinstance(response, dict) else None
            )

            if external_order_id is not None:
                order.addinfo(external_order_id=external_order_id)
                self._orders_by_external_id[str(external_order_id)] = order
            order_ref = (
                self._remote_client_order_ref(response) if isinstance(response, dict) else None
            )
            if order_ref not in (None, ""):
                order.addinfo(ctp_order_ref=order_ref)
                self._orders_by_client_ref[str(order_ref)] = order
            if isinstance(response, dict):
                for key in ("front_id", "session_id", "exchange_id"):
                    if key in response and response[key] not in (None, ""):
                        order.addinfo(**{key: response[key]})

            self.orders[order.ref] = order
            self.notify(order)
            self._apply_submit_response_fill(order, response)
            return order
        except Exception as exc:
            order.addinfo(error_code="remote_submit_failed", error_msg=str(exc))
            order.reject(self)
            self.orders[order.ref] = order
            self.notify(order)
            raise

    def cancel(self, order):
        """Cancel an existing order through the store."""
        if order is None:
            return None

        if not order.alive():
            return order

        if bool(self._order_info_get(order, "cancel_requested_remote", False)):
            return order

        if self.store is None:
            raise ValueError("BtApiBroker requires a BtApiStore instance")

        self.store.cancel_order(order)

        if bool(self.p.cancel_wait_remote):
            order.addinfo(cancel_requested_remote=True)
            return order

        order.cancel()
        self._clear_order_mappings(order)
        self.notify(order)
        return order

    def next(self):
        """Refresh cached balances and positions."""
        self._drain_store_updates()
        self._refresh_account()
        self._sync_positions()
        self._sync_remote_open_orders()

    def get_notification(self):
        """Return the next pending order notification."""
        if self.notifs:
            return self.notifs.popleft()
        return None

    def orderstatus(self, order):
        """Return the status for an order or order reference."""
        if hasattr(order, "status"):
            return order.status

        if order in self.orders:
            return self.orders[order].status

        return None

    def get_orders_open(self, safe=False):
        """Return still-open orders."""
        orders = [order for order in self.orders.values() if order.alive()]
        if safe:
            return [order.clone() for order in orders]
        return orders

    def fetch_open_orders(self):
        """Fetch provider-side open orders through the bound store."""
        return self._sync_remote_open_orders(force=True, raise_errors=False)

    def get_open_orders(self):
        """Alias for fetch_open_orders()."""
        return self.fetch_open_orders()

    def getopenorders(self):
        """Compatibility alias for fetch_open_orders()."""
        return self.fetch_open_orders()

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
        parent=None,
        transmit=True,
        histnotify=False,
        _checksubmit=True,
        **kwargs,
    ):
        """Create and submit a buy order."""
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
            trailamount=trailamount,
            trailpercent=trailpercent,
            parent=parent,
            transmit=transmit,
            histnotify=histnotify,
        )
        self._attach_position_meta(
            order, position_side=position_side, offset=offset, **order_kwargs
        )
        if oco is not None:
            order.addinfo(oco=oco)
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
        parent=None,
        transmit=True,
        histnotify=False,
        _checksubmit=True,
        **kwargs,
    ):
        """Create and submit a sell order."""
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
            trailamount=trailamount,
            trailpercent=trailpercent,
            parent=parent,
            transmit=transmit,
            histnotify=histnotify,
        )
        self._attach_position_meta(
            order, position_side=position_side, offset=offset, **order_kwargs
        )
        if oco is not None:
            order.addinfo(oco=oco)
        return self.submit(order)

    def notify(self, order):
        """Queue an order notification."""
        self.notifs.append(order.clone())

    def data_started(self, data):
        """Hook called when a feed starts."""

    def disable_trading(self, reason="manual"):
        """Disable new order submissions while keeping cancel support available."""
        self._trading_enabled = False
        self._emit_runtime_event(
            "trading_disabled",
            details={"reason": reason},
            status="disabled",
        )
        self._emit_runtime_event(
            "account_trading_disabled",
            details={"reason": reason},
            status="disabled",
        )

    def enable_trading(self, reason="manual"):
        """Re-enable order submissions."""
        self._trading_enabled = True
        self._emit_runtime_event(
            "trading_enabled",
            details={"reason": reason},
            status="enabled",
        )

    def pause_strategy(self, reason="manual"):
        """Pause strategy-driven order routing without disconnecting the store."""
        self._strategy_paused = True
        self._emit_runtime_event(
            "strategy_paused",
            details={"reason": reason},
            status="paused",
        )
        self._emit_runtime_event(
            "strategy_trading_paused",
            details={"reason": reason},
            status="paused",
        )

    def resume_strategy(self, reason="manual"):
        """Resume strategy-driven order routing."""
        self._strategy_paused = False
        self._emit_runtime_event(
            "strategy_resumed",
            details={"reason": reason},
            status="running",
        )

    def force_logout(self, reason="manual"):
        """Force the underlying store session to disconnect."""
        self._emit_runtime_event(
            "gateway_force_logout_requested",
            details={"reason": reason},
            status="disconnecting",
        )
        self._emit_runtime_event(
            "force_logout_requested",
            details={"reason": reason},
            status="disconnecting",
        )
        self._live_started = False
        if self.store is not None and self.store.is_connected:
            self.store.stop()

    def batch_cancel(self, orders=None):
        """Cancel a batch of live orders and return the canceled order objects."""
        candidates = self._batch_cancel_candidates(orders)
        requested = [
            (
                self._order_runtime_details(item)
                if kind == "local"
                else self._remote_order_details(item)
            )
            for kind, item in candidates
        ]
        self._emit_runtime_event(
            "batch_cancel_requested",
            status="submitted",
            details={
                "requested_count": len(candidates),
                "orders": requested,
            },
        )

        cancelled = []
        failures = []
        for kind, item in candidates:
            if kind == "local":
                order = item
                if not order.alive():
                    continue

                try:
                    self.cancel(order)
                except Exception as exc:
                    details = self._order_runtime_details(order)
                    details.update(
                        error_code=type(exc).__name__,
                        error_msg=str(exc),
                    )
                    failures.append(details)
                    continue

                cancelled.append(order)
                continue

            try:
                self._cancel_remote_open_order(item)
            except Exception as exc:
                details = self._remote_order_details(item)
                details.update(
                    error_code=type(exc).__name__,
                    error_msg=str(exc),
                )
                failures.append(details)
                continue

            cancelled.append(item)

        summary = {
            "requested_count": len(candidates),
            "cancelled_count": len(cancelled),
            "failure_count": len(failures),
            "cancelled_orders": [
                (
                    self._order_runtime_details(item)
                    if hasattr(item, "alive")
                    else self._remote_order_details(item)
                )
                for item in cancelled
            ],
            "failed_orders": failures,
        }
        if failures:
            self._emit_runtime_event(
                "batch_cancel_failed",
                level="ERROR",
                status="partial" if cancelled else "failed",
                details=summary,
            )
        else:
            self._emit_runtime_event(
                "batch_cancel_completed",
                status="completed",
                details=summary,
            )

        return cancelled

    def _batch_cancel_candidates(self, orders=None):
        """Return local and remote-open orders that should be cancelled."""
        if orders is not None:
            return [("local", order) for order in orders]

        local_orders = self.get_orders_open()
        candidates = [("local", order) for order in local_orders]
        local_remote_ids = {
            str(value)
            for order in local_orders
            for value in (
                self._order_info_get(order, "external_order_id"),
                self._order_info_get(order, "ctp_order_ref"),
                getattr(order, "ref", None),
            )
            if value not in (None, "")
        }

        remote_orders = self._sync_remote_open_orders(force=True, raise_errors=False)
        for item in remote_orders:
            remote_id = self._remote_order_id(item)
            if remote_id in (None, "") or str(remote_id) in local_remote_ids:
                continue
            candidates.append(("remote", item))
        return candidates

    @classmethod
    def _remote_order_id(cls, item):
        if not isinstance(item, dict):
            return None
        return cls._remote_external_order_id(item) or cls._remote_client_order_ref(item)

    @classmethod
    def _remote_external_order_id(cls, update):
        if not isinstance(update, dict):
            return None
        unwrapped = cls._unwrap_submit_response(update)
        if isinstance(unwrapped, dict):
            update = unwrapped
        kind = str(update.get("kind") or "").strip().lower()
        keys = _REMOTE_TRADE_ORDER_ID_KEYS if kind == "trade" else _REMOTE_ORDER_ID_KEYS
        return cls._extract_update_value(update, *keys)

    @classmethod
    def _remote_client_order_ref(cls, update):
        if not isinstance(update, dict):
            return None
        unwrapped = cls._unwrap_submit_response(update)
        if isinstance(unwrapped, dict):
            update = unwrapped
        return cls._extract_update_value(update, *_REMOTE_CLIENT_ORDER_REF_KEYS)

    @staticmethod
    def _remote_order_data_name(item):
        if not isinstance(item, dict):
            return None
        return BtApiBroker._extract_update_value(item, *_DATA_NAME_KEYS)

    def _remote_order_details(self, item):
        remote_id = self._remote_order_id(item)
        external_order_id = None
        ctp_order_ref = None
        side = None
        size = None
        price = None
        status = None
        if isinstance(item, dict):
            external_order_id = self._remote_external_order_id(item)
            ctp_order_ref = self._remote_client_order_ref(item)
            side = self._extract_update_value(item, "side", "Side", "direction", "Direction")
            size = self._extract_update_value(item, "size", "volume", "sz", "qty", "quantity")
            price = self._extract_update_value(item, "price", "Price", "px", "avgPx")
            status = self._extract_update_value(item, "status", "state", "Status")

        details = {
            "order_ref": remote_id,
            "external_order_id": external_order_id,
            "ctp_order_ref": ctp_order_ref,
            "data_name": self._remote_order_data_name(item),
            "side": side,
            "size": size,
            "price": price,
            "status": status,
            "source": "remote_open_orders",
        }
        return {key: value for key, value in details.items() if value not in (None, "")}

    def _cancel_remote_open_order(self, item):
        """Cancel a provider-side open order that has no local Order object."""
        if self.store is None:
            raise ValueError("BtApiBroker requires a BtApiStore instance")
        order_ref = self._remote_order_id(item)
        if order_ref in (None, ""):
            raise ValueError("Remote open order is missing an order reference")
        dataname = self._remote_order_data_name(item)
        if hasattr(self.store, "cancel_order_ref"):
            return self.store.cancel_order_ref(order_ref, dataname=dataname)
        raise ValueError("BtApiStore does not support cancelling remote order references")

    def _refresh_account(self, force=False, raise_errors=False):
        """Refresh cached cash and value from the store."""
        if self.store is None or not self._live_started or not self.store.is_connected:
            return
        if not force and not self._should_refresh(
            self._last_account_refresh,
            float(self.p.account_refresh_interval or 0.0),
        ):
            return

        try:
            try:
                balance = self.store.get_balance(force=force, raise_errors=raise_errors)
            except TypeError:
                balance = self.store.get_balance()
            self._cash = float(balance.get("cash", self._cash))
            self._value = float(balance.get("value", self._value))
            self._last_account_refresh = time.monotonic()
        except Exception as e:
            logger.debug("Failed to refresh account: %s", e)
            if raise_errors:
                raise

    def _sync_positions(self, force=False, raise_errors=False):
        """Refresh cached positions from the store."""
        if self.store is None or not self._live_started or not self.store.is_connected:
            return
        if not force and not self._should_refresh(
            self._last_positions_refresh,
            float(self.p.positions_refresh_interval or 0.0),
        ):
            return

        try:
            synced: "collections.defaultdict[str, Position]" = collections.defaultdict(Position)
            long_synced: "collections.defaultdict[str, Position]" = collections.defaultdict(
                Position
            )
            short_synced: "collections.defaultdict[str, Position]" = collections.defaultdict(
                Position
            )
            try:
                position_rows = self.store.get_positions(
                    force=force,
                    raise_errors=raise_errors,
                )
            except TypeError:
                position_rows = self.store.get_positions()
            tracked_aliases = self._tracked_position_alias_map()
            for item in position_rows:
                key = self._position_row_canonical_key(item, tracked_aliases)
                if tracked_aliases and key is None:
                    continue
                self._sync_one_position(item, synced, long_synced, short_synced, key=key)

            if self._is_dual_side_mode():
                self.long_positions = long_synced
                self.short_positions = short_synced
                self.positions = collections.defaultdict(Position)
                for key in set(long_synced) | set(short_synced):
                    self._sync_net_position(key)
            else:
                self.positions = synced
            self._last_positions_refresh = time.monotonic()
        except Exception as e:
            logger.debug("Failed to sync positions: %s", e)
            if raise_errors:
                raise

    def _sync_one_position(
        self,
        item,
        synced: "collections.defaultdict[str, Position]",
        long_synced: "collections.defaultdict[str, Position]",
        short_synced: "collections.defaultdict[str, Position]",
        key=None,
    ):
        """Parse a single provider position dict into the right cache bucket.

        Extracted from ``_sync_positions``' loop body; behavior unchanged.
        Mutates the supplied ``synced`` / ``long_synced`` / ``short_synced``
        defaultdicts in place and returns nothing.
        """
        key = key or self._position_row_key(item)
        if not key:
            return

        size = self._extract_update_value(item, *_POSITION_SIZE_KEYS)
        size = float(size or 0.0)
        direction = self._extract_position_direction(item)

        price = self._extract_update_value(item, *_POSITION_PRICE_KEYS)
        price = float(price or 0.0)

        if self._is_dual_side_mode():
            if size and direction not in {"long", "short"}:
                raise ValueError(
                    "dual_side mode requires provider positions with explicit direction"
                )
            if direction == "short" or size < 0:
                short_synced[key] = Position(size=abs(size), price=price)
            else:
                long_synced[key] = Position(size=abs(size), price=price)
        else:
            if direction == "short" and size > 0:
                size = -size
            synced[key] = Position(size=size, price=price)

    def _tracked_position_alias_map(self):
        """Return aliases for symbols that belong to this broker instance."""
        tracked_keys = []

        def add_symbol(value):
            if value in (None, ""):
                return
            symbol = str(value).strip()
            if symbol and symbol not in tracked_keys:
                tracked_keys.append(symbol)

        store = self.store
        if store is not None:
            for data in getattr(store, "_data_feeds", []) or []:
                add_symbol(self._position_key(data))
            for dataname in getattr(store, "_subscribed_datanames", set()) or set():
                add_symbol(dataname)

        for order in self.orders.values():
            data = getattr(order, "data", None)
            if data is not None:
                add_symbol(self._position_key(data))

        alias_map: dict[str, str] = {}
        for key in tracked_keys:
            for alias in self._symbol_aliases(key):
                alias_map.setdefault(alias, key)
        return alias_map

    @classmethod
    def _position_row_canonical_key(cls, item, alias_map):
        key = cls._position_row_key(item)
        if not alias_map:
            return key
        if key in (None, ""):
            return None
        for alias in cls._symbol_aliases(key):
            if alias in alias_map:
                return alias_map[alias]
        return None

    @staticmethod
    def _position_row_key(item):
        if not isinstance(item, dict):
            return None
        return BtApiBroker._extract_update_value(item, *_DATA_NAME_KEYS)

    @staticmethod
    def _normalise_code_text(value):
        text = str(value).strip().lower().replace("-", "_")
        numeric_text = text.replace(",", "")
        try:
            number = float(numeric_text)
        except (TypeError, ValueError, OverflowError):
            return text
        if number.is_integer():
            return str(int(number))
        return text

    @staticmethod
    def _normalise_position_direction(value):
        if value in (None, ""):
            return ""
        text = BtApiBroker._normalise_code_text(value)
        if text in {"long", "buy", "b", "bid", "2"}:
            return "long"
        if text in {"short", "sell", "s", "ask", "3"}:
            return "short"
        return text

    @classmethod
    def _extract_position_direction(cls, item):
        if not isinstance(item, dict):
            return ""
        details = item.get("details")
        if not isinstance(details, dict):
            details = {}
        for key in _POSITION_DIRECTION_KEYS:
            value = item.get(key)
            if value in (None, ""):
                value = details.get(key)
            if value in (None, ""):
                continue
            if key in {"positionIdx", "position_idx"}:
                text = cls._normalise_code_text(value)
                if text == "1":
                    return "long"
                if text == "2":
                    return "short"
                if text == "0":
                    return ""
            return cls._normalise_position_direction(value)
        return ""

    def _sync_remote_open_orders(self, force=False, raise_errors=False):
        """Refresh the cached provider-side open-order snapshot."""
        if self.store is None or not self._live_started or not self.store.is_connected:
            return deepcopy(self._remote_open_orders_snapshot)
        if not force and not self._should_refresh(
            self._last_open_orders_refresh,
            float(self.p.open_orders_refresh_interval or 0.0),
        ):
            return deepcopy(self._remote_open_orders_snapshot)

        try:
            try:
                orders = list(
                    self.store.fetch_open_orders(force=force, raise_errors=raise_errors) or []
                )
            except TypeError:
                orders = list(self.store.fetch_open_orders() or [])
            self._remote_open_orders_snapshot = orders
            self._last_open_orders_refresh = time.monotonic()
            self._emit_runtime_event(
                "open_orders_sync_completed",
                status="completed",
                details={
                    "open_order_count": len(orders),
                    "orders": list(orders),
                },
            )
            return deepcopy(self._remote_open_orders_snapshot)
        except Exception as e:
            logger.debug("Failed to sync remote open orders: %s", e)
            self._emit_runtime_event(
                "open_orders_sync_failed",
                level="ERROR",
                status="failed",
                error_code=type(e).__name__,
                error_msg=str(e),
                details={
                    "open_order_count": len(self._remote_open_orders_snapshot),
                    "orders": list(self._remote_open_orders_snapshot),
                },
            )
            if raise_errors:
                raise
            return deepcopy(self._remote_open_orders_snapshot)

    @staticmethod
    def _should_refresh(last_refresh, interval):
        """Return whether a throttled live refresh should run now."""
        if interval <= 0:
            return True

        return (time.monotonic() - last_refresh) >= interval

    @staticmethod
    def _position_key(data):
        """Extract a stable position key from a data feed."""
        if isinstance(data, str):
            return data
        return (
            getattr(data, "_name", None)
            or getattr(data, "_dataname", None)
            or getattr(getattr(data, "p", None), "dataname", None)
            or repr(data)
        )

    @staticmethod
    def _symbol_aliases(symbol):
        """Return common aliases for matching configured contract metadata."""
        raw = str(symbol or "").strip()
        aliases = [raw]
        if "." in raw:
            head, tail = (part.strip() for part in raw.split(".", 1))
            head_upper = head.upper()
            tail_upper = tail.upper()
            if head_upper in _CTP_EXCHANGES:
                aliases.extend([tail, tail.upper(), tail.lower()])
            elif tail_upper in _CTP_EXCHANGES:
                aliases.extend([head, head.upper(), head.lower()])
            else:
                aliases.extend([tail, tail.upper(), tail.lower()])
        if "_" in raw:
            head, tail = raw.split("_", 1)
            if head.upper() in {"SHFE", "DCE", "CZCE", "CFFEX", "INE", "GFEX"}:
                aliases.extend([tail, tail.upper(), tail.lower()])
            elif tail.upper() in _CTP_EXCHANGES:
                aliases.extend([head, head.upper(), head.lower()])
        aliases.extend([raw.upper(), raw.lower()])
        compact = "".join(ch for ch in raw if ch.isalnum())
        aliases.extend([compact, compact.upper(), compact.lower()])
        result = []
        seen = set()
        for alias in aliases:
            if alias and alias not in seen:
                result.append(alias)
                seen.add(alias)
        return result

    def _warm_contract_metadata(self):
        """Materialize comminfo for known live symbols at broker startup."""
        names: set[str] = set()
        for container in (self.positions, self.long_positions, self.short_positions):
            try:
                names.update(str(key) for key in container.keys() if key not in (None, ""))
            except Exception:
                continue

        data_feeds = getattr(self.store, "_data_feeds", []) if self.store is not None else []
        for data in data_feeds:
            try:
                names.add(str(self._position_key(data)))
            except Exception:
                continue

        for data_name in sorted(names):
            self._materialize_contract_comminfo(data_name)

    def _materialize_contract_comminfo(self, data_name):
        """Create and cache a symbol-specific comminfo when metadata is available."""
        if not data_name:
            return None
        for alias in self._symbol_aliases(data_name):
            if alias in self.comminfo:
                return self.comminfo[alias]
        comminfo = self._metadata_to_comminfo(self._contract_rules_for(data_name))
        if comminfo is not None:
            self.addcommissioninfo(comminfo, name=data_name)
        return comminfo

    @staticmethod
    def _first_number(*values, default=None):
        for value in values:
            if value in (None, ""):
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return default

    @classmethod
    def _normalise_rate(cls, value, default=0.0):
        number = cls._first_number(value, default=default)
        if number is None:
            return default
        if number > 1.0:
            return number / 100.0
        return max(number, 0.0)

    @classmethod
    def _normalise_signed_rate(cls, value, default=0.0):
        number = cls._first_number(value, default=default)
        if number is None:
            return default
        if abs(number) > 1.0:
            return number / 100.0
        return number

    @classmethod
    def _metadata_commission_rate(cls, metadata, *keys):
        method = str(metadata.get("commission_method") or "").strip().lower()
        for key in keys:
            value = cls._first_number(metadata.get(key))
            if value is None:
                continue
            key_text = str(key or "")
            if (
                method == "percent_10k"
                or (key_text.startswith("COMMISSION_") and key_text.endswith("_RATIO"))
                or (
                    key_text
                    in {
                        "OpenRatioByMoney",
                        "CloseRatioByMoney",
                        "CloseTodayRatioByMoney",
                        "CloseYesterdayRatioByMoney",
                    }
                    and value > 0.01
                )
            ):
                value = max(value, 0.0)
                return value / 10000.0 if value > 0.01 else value
            return cls._normalise_rate(value, 0.0)
        return None

    @classmethod
    def _metadata_open_commission_rate(cls, metadata):
        return cls._metadata_commission_rate(
            metadata,
            "commission",
            "commission_rate",
            "fee_rate",
            "open_fee_rate",
            "open_commission_rate",
            "OpenRatioByMoney",
            "COMMISSION_OPEN_RATIO",
        )

    @classmethod
    def _metadata_close_commission_rate(cls, metadata):
        return cls._metadata_commission_rate(
            metadata,
            "close_fee_rate",
            "close_commission_rate",
            "CloseRatioByMoney",
            "COMMISSION_CLOSE_RATIO",
        )

    @classmethod
    def _metadata_close_today_commission_rate(cls, metadata):
        return cls._metadata_commission_rate(
            metadata,
            "close_today_fee_rate",
            "close_today_commission_rate",
            "CloseTodayRatioByMoney",
            "COMMISSION_CLOSE_TODAY_RATIO",
        )

    @classmethod
    def _metadata_close_yesterday_commission_rate(cls, metadata):
        return cls._metadata_commission_rate(
            metadata,
            "close_yesterday_fee_rate",
            "close_yesterday_commission_rate",
            "CloseYesterdayRatioByMoney",
            "COMMISSION_CLOSE_YESTERDAY_RATIO",
        )

    @classmethod
    def _metadata_maker_commission_rate(cls, metadata):
        return cls._metadata_role_commission_rate(
            metadata,
            "maker_commission_rate",
            "maker_fee_rate",
        )

    @classmethod
    def _metadata_taker_commission_rate(cls, metadata):
        return cls._metadata_role_commission_rate(
            metadata,
            "taker_commission_rate",
            "taker_fee_rate",
        )

    @classmethod
    def _metadata_role_commission_rate(cls, metadata, *keys):
        for key in keys:
            value = cls._first_number(metadata.get(key))
            if value is not None:
                return cls._normalise_signed_rate(value, 0.0)
        return None

    @classmethod
    def _metadata_commission_amount(cls, metadata, *keys):
        return cls._first_number(*(metadata.get(key) for key in keys))

    @classmethod
    def _metadata_text(cls, metadata, *keys):
        for key in keys:
            value = metadata.get(key)
            if value in (None, ""):
                continue
            return cls._normalise_code_text(value)
        return ""

    @classmethod
    def _metadata_currency(cls, metadata, *keys):
        text = cls._metadata_text(metadata, *keys)
        return text.replace("_", "")

    @classmethod
    def _metadata_bool(cls, metadata, *keys):
        for key in keys:
            value = metadata.get(key)
            if value in (None, ""):
                continue
            if isinstance(value, bool):
                return value
            text = cls._normalise_code_text(value)
            if text in {"1", "true", "yes", "y", "inverse"}:
                return True
            if text in {"0", "false", "no", "n", "linear"}:
                return False
        return None

    @classmethod
    def _metadata_is_inverse_contract(cls, metadata):
        explicit = cls._metadata_bool(
            metadata,
            "inverse",
            "is_inverse",
            "isInverse",
            "inverse_contract",
            "inverseContract",
        )
        if explicit is not None:
            return explicit

        type_texts = [
            cls._metadata_text(metadata, key)
            for key in (
                "contract_type",
                "contractType",
                "ctType",
                "type",
                "instrument_type",
                "instrumentType",
                "category",
            )
        ]
        type_texts = [text for text in type_texts if text]
        if any("inverse" in text or "coin_margined" in text for text in type_texts):
            return True
        if any(
            "linear" in text or "usdt_margined" in text or "usdc_margined" in text
            for text in type_texts
        ):
            return False

        base_ccy = cls._metadata_currency(
            metadata,
            "base_currency",
            "baseCurrency",
            "base_ccy",
            "baseCcy",
            "base_asset",
            "baseAsset",
        )
        quote_ccy = cls._metadata_currency(
            metadata,
            "quote_currency",
            "quoteCurrency",
            "quote_ccy",
            "quoteCcy",
            "quote_asset",
            "quoteAsset",
        )
        contract_value_ccy = cls._metadata_currency(
            metadata,
            "contract_value_currency",
            "contractValueCurrency",
            "contract_value_ccy",
            "contractValueCcy",
            "ctValCcy",
        )
        settle_ccy = cls._metadata_currency(
            metadata,
            "settle_currency",
            "settleCurrency",
            "settle_ccy",
            "settleCcy",
            "margin_currency",
            "marginCurrency",
            "margin_ccy",
            "marginCcy",
        )
        fee_ccy = cls._metadata_currency(
            metadata,
            "fee_currency",
            "feeCurrency",
            "fee_ccy",
            "feeCcy",
        )

        if contract_value_ccy and quote_ccy and contract_value_ccy == quote_ccy:
            if not base_ccy or contract_value_ccy != base_ccy:
                return True
        if contract_value_ccy and base_ccy and contract_value_ccy == base_ccy:
            return False
        if base_ccy and quote_ccy and settle_ccy == base_ccy and settle_ccy != quote_ccy:
            return True
        if (
            (contract_value_ccy or settle_ccy)
            and base_ccy
            and quote_ccy
            and fee_ccy == base_ccy
            and fee_ccy != quote_ccy
        ):
            return True
        return False

    @classmethod
    def _metadata_open_commission_amount(cls, metadata):
        return cls._metadata_commission_amount(
            metadata,
            "commission_amount",
            "fee_amount",
            "commission_per_lot",
            "open_fee_amount",
            "open_commission_amount",
            "OpenRatioByVolume",
            "COMMISSION_OPEN_AMOUNT",
        )

    @classmethod
    def _metadata_close_commission_amount(cls, metadata):
        return cls._metadata_commission_amount(
            metadata,
            "close_fee_amount",
            "close_commission_amount",
            "CloseRatioByVolume",
            "COMMISSION_CLOSE_AMOUNT",
        )

    @classmethod
    def _metadata_close_today_commission_amount(cls, metadata):
        return cls._metadata_commission_amount(
            metadata,
            "close_today_fee_amount",
            "close_today_commission_amount",
            "CloseTodayRatioByVolume",
            "COMMISSION_CLOSE_TODAY_AMOUNT",
        )

    @classmethod
    def _metadata_close_yesterday_commission_amount(cls, metadata):
        return cls._metadata_commission_amount(
            metadata,
            "close_yesterday_fee_amount",
            "close_yesterday_commission_amount",
            "CloseYesterdayRatioByVolume",
            "COMMISSION_CLOSE_YESTERDAY_AMOUNT",
        )

    @classmethod
    def _metadata_to_comminfo(cls, metadata):
        """Build a Backtrader comminfo object from normalized contract metadata."""
        if not metadata:
            return None
        inverse_contract = cls._metadata_is_inverse_contract(metadata)
        multiplier_values = (
            (
                metadata.get("contract_value"),
                metadata.get("contractValue"),
                metadata.get("contract_value_amount"),
                metadata.get("contractValueAmount"),
                metadata.get("ctVal"),
                metadata.get("ct_value"),
                metadata.get("multiplier"),
                metadata.get("mult"),
                metadata.get("contract_multiplier"),
                metadata.get("contract_size"),
                metadata.get("ctMult"),
                metadata.get("VolumeMultiple"),
            )
            if inverse_contract
            else (
                metadata.get("multiplier"),
                metadata.get("mult"),
                metadata.get("contract_multiplier"),
                metadata.get("contract_size"),
                metadata.get("contract_value"),
                metadata.get("contractValue"),
                metadata.get("ctVal"),
                metadata.get("ctMult"),
                metadata.get("VolumeMultiple"),
            )
        )
        multiplier = cls._first_number(*multiplier_values, default=1.0)
        margin_value = cls._first_number(
            metadata.get("margin"),
            metadata.get("margin_rate"),
            metadata.get("margin_ratio"),
            metadata.get("long_margin_rate"),
            metadata.get("LongMarginRatioByMoney"),
            metadata.get("MARGIN_BUY"),
        )
        margin_amount = cls._first_number(
            metadata.get("margin_amount"),
            metadata.get("initial_margin_per_lot"),
            metadata.get("margin_initial"),
            metadata.get("initial_margin_amount"),
            metadata.get("SYMBOL_MARGIN_INITIAL"),
        )
        leverage = cls._first_number(
            metadata.get("leverage"),
            metadata.get("lever"),
            metadata.get("max_leverage"),
        )
        margin_rate = (
            1.0 / leverage if leverage and leverage > 0 else cls._normalise_rate(margin_value, 1.0)
        )
        margin_amount_param = (
            max(margin_amount, 0.0) if margin_amount is not None and margin_amount > 0 else None
        )
        commission_rate = cls._metadata_open_commission_rate(metadata)
        close_commission_rate = cls._metadata_close_commission_rate(metadata)
        close_today_commission_rate = cls._metadata_close_today_commission_rate(metadata)
        close_yesterday_commission_rate = cls._metadata_close_yesterday_commission_rate(metadata)
        maker_commission_rate = cls._metadata_maker_commission_rate(metadata)
        taker_commission_rate = cls._metadata_taker_commission_rate(metadata)
        if commission_rate is None:
            commission_rate = (
                taker_commission_rate
                if taker_commission_rate is not None
                else maker_commission_rate
            )
        commission_amount = cls._metadata_open_commission_amount(metadata)
        close_commission_amount = cls._metadata_close_commission_amount(metadata)
        close_today_commission_amount = cls._metadata_close_today_commission_amount(metadata)
        close_yesterday_commission_amount = cls._metadata_close_yesterday_commission_amount(
            metadata
        )
        commission_method = str(metadata.get("commission_method") or "").strip().lower()
        has_commission_amount = any(
            value is not None
            for value in (
                commission_amount,
                close_commission_amount,
                close_today_commission_amount,
                close_yesterday_commission_amount,
            )
        )
        has_commission_rate = any(
            value is not None
            for value in (
                commission_rate,
                close_commission_rate,
                close_today_commission_rate,
                close_yesterday_commission_rate,
                maker_commission_rate,
                taker_commission_rate,
            )
        )
        if inverse_contract:
            return ComminfoFuturesInverse(
                commission=commission_rate if commission_rate is not None else 0.0,
                open_commission=commission_rate,
                close_commission=close_commission_rate,
                close_today_commission=close_today_commission_rate,
                close_yesterday_commission=close_yesterday_commission_rate,
                maker_commission=maker_commission_rate,
                taker_commission=taker_commission_rate,
                commission_amount=max(commission_amount or 0.0, 0.0),
                open_commission_amount=(
                    max(commission_amount, 0.0) if commission_amount is not None else None
                ),
                close_commission_amount=(
                    max(close_commission_amount, 0.0)
                    if close_commission_amount is not None
                    else None
                ),
                close_today_commission_amount=(
                    max(close_today_commission_amount, 0.0)
                    if close_today_commission_amount is not None
                    else None
                ),
                close_yesterday_commission_amount=(
                    max(close_yesterday_commission_amount, 0.0)
                    if close_yesterday_commission_amount is not None
                    else None
                ),
                margin=max(margin_rate, 0.0),
                margin_amount=margin_amount_param,
                mult=max(multiplier or 1.0, 1e-12),
            )
        if has_commission_amount and commission_method != "fixed_per_lot" and has_commission_rate:
            return ComminfoFuturesMixed(
                commission=commission_rate if commission_rate is not None else 0.0,
                open_commission=commission_rate,
                close_commission=close_commission_rate,
                close_today_commission=close_today_commission_rate,
                close_yesterday_commission=close_yesterday_commission_rate,
                maker_commission=maker_commission_rate,
                taker_commission=taker_commission_rate,
                commission_amount=max(commission_amount or 0.0, 0.0),
                open_commission_amount=(
                    max(commission_amount, 0.0) if commission_amount is not None else None
                ),
                close_commission_amount=(
                    max(close_commission_amount, 0.0)
                    if close_commission_amount is not None
                    else None
                ),
                close_today_commission_amount=(
                    max(close_today_commission_amount, 0.0)
                    if close_today_commission_amount is not None
                    else None
                ),
                close_yesterday_commission_amount=(
                    max(close_yesterday_commission_amount, 0.0)
                    if close_yesterday_commission_amount is not None
                    else None
                ),
                margin=max(margin_rate, 0.0),
                margin_amount=margin_amount_param,
                mult=max(multiplier or 1.0, 1e-12),
            )
        if commission_amount is not None and (
            commission_method == "fixed_per_lot" or not has_commission_rate
        ):
            return ComminfoFuturesFixed(
                commission=max(commission_amount, 0.0),
                open_commission=max(commission_amount, 0.0),
                close_commission=(
                    max(close_commission_amount, 0.0)
                    if close_commission_amount is not None
                    else None
                ),
                close_today_commission=(
                    max(close_today_commission_amount, 0.0)
                    if close_today_commission_amount is not None
                    else None
                ),
                close_yesterday_commission=(
                    max(close_yesterday_commission_amount, 0.0)
                    if close_yesterday_commission_amount is not None
                    else None
                ),
                margin=max(margin_rate, 0.0),
                margin_amount=margin_amount_param,
                mult=max(multiplier or 1.0, 1e-12),
            )
        return ComminfoFuturesPercent(
            commission=commission_rate if commission_rate is not None else 0.0,
            open_commission=commission_rate,
            close_commission=close_commission_rate,
            close_today_commission=close_today_commission_rate,
            close_yesterday_commission=close_yesterday_commission_rate,
            maker_commission=maker_commission_rate,
            taker_commission=taker_commission_rate,
            margin=max(margin_rate, 0.0),
            margin_amount=margin_amount_param,
            mult=max(multiplier or 1.0, 1e-12),
        )

    def getcommissioninfo(self, data):
        """Return symbol-specific comminfo, deriving it from contract metadata if needed."""
        for name in self._commission_lookup_keys(data):
            if name in self.comminfo:
                return self.comminfo[name]

        data_name = self._position_key(data)
        comminfo = self._metadata_to_comminfo(self._contract_rules_for(data_name))
        if comminfo is not None:
            self.addcommissioninfo(comminfo, name=data_name)
            return comminfo
        return super().getcommissioninfo(data)

    def _validate_order(self, order):
        """Run lightweight local validation before the order reaches the store."""
        if not bool(self.p.validation_enabled):
            return None

        data_name = self._position_key(order.data)
        rules = self._contract_rules_for(data_name)
        size_error = self._validate_order_size(
            order,
            rules,
            default_max_order_size=self.p.max_order_size,
        )
        if size_error is not None:
            return size_error

        if rules.get("valid") is False or rules.get("exists") is False:
            return "invalid_contract", f"Contract {data_name} is not valid for trading"

        if rules.get("tradable") is False:
            return "contract_not_tradable", f"Contract {data_name} is currently not tradable"

        type_error = self._validate_order_type(order, rules)
        if type_error is not None:
            return type_error

        if self._is_dual_side_mode() and self._order_info_get(order, "offset") == "close":
            position_side = normalize_position_side(self._order_info_get(order, "position_side"))
            available = abs(float(self._get_leg_position(order.data, position_side).size or 0.0))
            requested = abs(float(order.size or 0.0))
            if requested > available + 1e-12:
                return (
                    "insufficient_position_to_close",
                    "Close order size exceeds the available leg position",
                )

        min_price_tick = rules.get("min_price_tick") or rules.get("price_tick")
        price = order.price if order.price is not None else getattr(order.created, "price", None)
        if min_price_tick and price not in (None, 0):
            tick = float(min_price_tick)
            scaled = float(price) / tick
            if abs(round(scaled) - scaled) > 1e-9:
                return (
                    "invalid_price_tick",
                    f"Order price {price} does not align with tick size {tick}",
                )

        cash_error = self._validate_order_cash(order, rules)
        if cash_error is not None:
            return cash_error

        return None

    @classmethod
    def _metadata_size_rule(cls, rules, *keys, default=None):
        return cls._first_number(*(rules.get(key) for key in keys), default=default)

    @classmethod
    def _validate_order_size(cls, order, rules, default_max_order_size=0):
        """Validate order quantity against exchange/local lot-size rules."""
        requested = abs(float(order.size or 0.0))
        if requested <= 0.0:
            return "invalid_order_size", "Order size must be positive"

        min_order_size = cls._metadata_size_rule(
            rules,
            "min_order_size",
            "min_order_qty",
            "min_size",
            "min_qty",
            "minQty",
            "minSz",
            "min_volume",
            "volume_min",
            "min_lot",
            "lot_min",
            "SYMBOL_VOLUME_MIN",
        )
        if min_order_size and requested + 1e-12 < min_order_size:
            return (
                "min_order_size_not_met",
                f"Order size {order.size} is below the minimum allowed size {min_order_size}",
            )

        step = cls._metadata_size_rule(
            rules,
            "order_size_step",
            "size_step",
            "qty_step",
            "qty_unit",
            "quantity_step",
            "volume_step",
            "lot_step",
            "step_size",
            "stepSize",
            "lotSz",
            "SYMBOL_VOLUME_STEP",
        )
        if step and step > 0:
            scaled = requested / step
            if abs(round(scaled) - scaled) > 1e-9:
                return (
                    "invalid_order_size_step",
                    f"Order size {order.size} does not align with size step {step}",
                )

        order_type = cls._order_type_name(order)
        max_order_size = None
        if order_type == "market":
            max_order_size = cls._metadata_size_rule(
                rules,
                "market_max_order_size",
                "max_market_order_size",
                "max_mkt_order_size",
                "maxMktSz",
            )
        elif order_type == "limit":
            max_order_size = cls._metadata_size_rule(
                rules,
                "limit_max_order_size",
                "max_limit_order_size",
                "max_lmt_order_size",
                "maxLmtSz",
            )
        if max_order_size is None:
            max_order_size = cls._metadata_size_rule(
                rules,
                "max_order_size",
                "max_order_qty",
                "max_size",
                "max_qty",
                "maxQty",
                "max_volume",
                "volume_max",
                "max_lot",
                "lot_max",
                "SYMBOL_VOLUME_MAX",
                default=default_max_order_size,
            )
        if max_order_size and requested > max_order_size + 1e-12:
            return (
                "max_order_size_exceeded",
                f"Order size {order.size} exceeds the max allowed size {max_order_size}",
            )

        return None

    @staticmethod
    def _order_type_name(order):
        try:
            return str(order.getordername() or "").strip().lower()
        except Exception:
            return ""

    def _supported_order_types_for(self, order, rules):
        configured = rules.get("supported_order_types") or rules.get("order_types")
        if isinstance(configured, str):
            configured = [item.strip() for item in configured.split(",")]
        if configured:
            return {str(item or "").strip().lower() for item in configured if item}
        if self._requires_explicit_offset(order.data):
            return {"market", "limit"}
        return None

    def _validate_order_type(self, order, rules):
        """Reject order execution types that the live venue cannot represent."""
        order_type = self._order_type_name(order)
        supported = self._supported_order_types_for(order, rules)
        if supported is not None and order_type not in supported:
            return (
                "unsupported_order_type",
                f"Order type {order_type or '<unknown>'} is not supported by this live broker",
            )
        return None

    def _opening_size_for_order(self, order):
        """Return the portion of an order that opens or increases exposure."""
        requested = abs(float(order.size or 0.0))
        if requested <= 0.0:
            return 0.0

        offset = self._order_info_get(order, "offset")
        if offset in {"close", "close_today", "close_yesterday"}:
            return 0.0

        if self._is_dual_side_mode():
            return requested

        position = self.getposition(order.data, clone=False)
        current_size = float(position.size or 0.0)
        if order.isbuy():
            return max(requested - abs(current_size), 0.0) if current_size < 0.0 else requested
        return max(requested - current_size, 0.0) if current_size > 0.0 else requested

    def _order_price_for_risk(self, order, rules):
        """Resolve a usable price for cash and margin checks."""
        price = self._first_number(
            getattr(order, "price", None),
            getattr(getattr(order, "created", None), "price", None),
            getattr(getattr(order, "created", None), "pricelimit", None),
            rules.get("current_price"),
            rules.get("latest_price"),
            rules.get("last_price"),
            rules.get("mark_price"),
        )
        if price and price > 0:
            return price

        close = getattr(getattr(order, "data", None), "close", None)
        if close is not None:
            try:
                price = float(close[0])
            except Exception:
                price = 0.0
            if price > 0:
                return price
        return None

    def _validate_order_cash(self, order, rules):
        """Reject opening orders whose required cash or margin is unavailable."""
        if not bool(rules.get("cash_check_enabled", self.p.cash_check_enabled)):
            return None

        opening_size = self._opening_size_for_order(order)
        if opening_size <= 0.0:
            return None

        self._refresh_account(force=bool(self.p.force_refresh_queries), raise_errors=True)

        price = self._order_price_for_risk(order, rules)
        if price is None:
            return (
                "risk_price_unavailable",
                "Opening order requires a current price for cash/margin validation",
            )

        comminfo = self.getcommissioninfo(order.data)
        if comminfo is None:
            return None

        required = float(comminfo.getoperationcost(opening_size, price) or 0.0)
        required += float(comminfo.getcommission(opening_size, price, role="open") or 0.0)
        safety_factor = self._first_number(
            rules.get("cash_check_safety_factor"),
            rules.get("margin_safety_factor"),
            self.p.cash_check_safety_factor,
            default=1.0,
        )
        required *= max(safety_factor or 1.0, 0.0)
        cash_buffer = self._first_number(
            rules.get("cash_buffer"),
            rules.get("min_cash_buffer"),
            self.p.cash_buffer,
            default=0.0,
        )
        available = max(float(self._cash or 0.0) - max(cash_buffer or 0.0, 0.0), 0.0)
        if required > available + 1e-12:
            return (
                "insufficient_cash",
                "Order requires "
                f"{required:.2f} cash/margin but only {available:.2f} is available",
            )
        return None

    def _reject_order(self, order, error_code, error_msg):
        """Reject an order locally and emit a structured runtime event."""
        order.addinfo(error_code=error_code, error_msg=error_msg)
        order.reject(self)
        self.orders[order.ref] = order
        self.notify(order)
        details = {
            "data_name": self._position_key(order.data),
            "side": "buy" if order.isbuy() else "sell",
            "size": abs(float(order.size or 0.0)),
            "price": (
                order.price if order.price is not None else getattr(order.created, "price", None)
            ),
        }
        self._emit_runtime_event(
            "order_reject_local",
            level="ERROR",
            order_ref=order.ref,
            error_code=error_code,
            error_msg=error_msg,
            status="rejected",
            details=details,
        )
        self._emit_runtime_event(
            "order_validation_rejected",
            level="ERROR",
            order_ref=order.ref,
            error_code=error_code,
            error_msg=error_msg,
            status="rejected",
            details=details,
        )
        return order

    @classmethod
    def _submit_response_error(cls, response):
        """Return a structured error when a submit response is not confirmed."""
        result = cls._unwrap_submit_response(response)
        if result is None:
            return "remote_submit_rejected", "empty remote submit response"
        if not isinstance(result, dict):
            return cls._non_mapping_submit_response_error(result)
        if not result:
            return "remote_submit_rejected", "empty remote submit response"

        status = str(result.get("status") or result.get("order_status") or "").strip().lower()
        if status in {
            "error",
            "failed",
            "fail",
            "rejected",
            "reject",
            "cancelled",
            "canceled",
            "expired",
        }:
            return "remote_submit_rejected", cls._submit_response_message(
                result, f"remote order status: {status}"
            )
        if status in {
            "ok",
            "success",
            "submitted",
            "accepted",
            "completed",
            "complete",
            "partial",
            "filled",
            "open",
            "placed",
        }:
            return None

        retcode = result.get("retcode") or result.get("ret_code")
        if retcode not in (None, ""):
            try:
                retcode_int = int(retcode)
            except (TypeError, ValueError):
                retcode_int = None
            if retcode_int in {10008, 10009, 10010}:
                return None
            if retcode_int in {
                10004,
                10006,
                10007,
                10013,
                10014,
                10015,
                10016,
                10017,
                10018,
                10019,
                10030,
                10031,
            }:
                return "remote_submit_rejected", cls._submit_response_message(
                    result,
                    f"remote retcode: {retcode}",
                )

        code = result.get("code")
        if code not in (None, "", 0, "0"):
            return "remote_submit_rejected", cls._submit_response_message(
                result,
                f"remote code: {code}",
            )

        success_value = result.get("success")
        if isinstance(success_value, bool):
            if success_value:
                return None
            return "remote_submit_rejected", cls._submit_response_message(
                result,
                "remote submit success flag is false",
            )
        if cls._submit_response_has_identity(result):
            return None
        return "remote_submit_rejected", "invalid remote submit response"

    @staticmethod
    def _non_mapping_submit_response_error(result):
        if isinstance(result, bool):
            return "remote_submit_rejected", "invalid remote submit response"
        if isinstance(result, str):
            if result.strip():
                return None
            return "remote_submit_rejected", "empty remote submit response"
        if isinstance(result, (int, float)):
            if result != 0:
                return None
            return "remote_submit_rejected", "invalid remote submit response"
        return "remote_submit_rejected", "invalid remote submit response"

    @staticmethod
    def _submit_response_has_identity(result):
        for key in (
            "id",
            "order_id",
            "orderId",
            "OrderID",
            "ordId",
            "external_order_id",
            "externalOrderId",
            "venue_order_id",
            "venueOrderId",
            "order_ref",
            "orderRef",
            "OrderRef",
            "client_order_id",
            "clientOrderId",
            "newClientOrderId",
            "origClientOrderId",
            "clOrdId",
            "origClOrdId",
            "orderLinkId",
            "origOrderLinkId",
            "ticket",
            "order",
            "deal",
            "deal_id",
            "dealId",
            "DealID",
        ):
            if result.get(key) not in (None, ""):
                return True
        return False

    @staticmethod
    def _unwrap_submit_response(response):
        current = response
        for _ in range(5):
            if isinstance(current, (list, tuple)):
                if len(current) == 1 and isinstance(current[0], dict):
                    current = current[0]
                    continue
                return current
            if not isinstance(current, dict):
                return current
            status = str(current.get("status") or "").strip().lower()
            code = str(current.get("code") or "").strip()
            success = current.get("success")
            wrapper_ok = status in {"ok", "success"} or code in {"0", "00000"} or success is True
            if wrapper_ok:
                nested = current.get("data", current.get("result"))
                if isinstance(nested, dict):
                    current = nested
                    continue
                if (
                    isinstance(nested, (list, tuple))
                    and len(nested) == 1
                    and isinstance(nested[0], dict)
                ):
                    current = nested[0]
                    continue
            return current
        return current

    @staticmethod
    def _submit_response_message(result, fallback):
        return str(
            result.get("retcode_external")
            or result.get("comment")
            or result.get("message")
            or result.get("error")
            or result.get("reason")
            or fallback
        )

    def _requires_explicit_offset(self, data):
        """Return whether the provider needs open/close offset metadata."""
        provider_values = {
            str(self.provider or "").strip().lower(),
            (
                str(getattr(self.store, "provider", "") or "").strip().lower()
                if self.store is not None
                else ""
            ),
        }
        if provider_values & {"ctp", "ctp_gateway"}:
            return True

        config_values = []
        if self.store is not None:
            config_values.extend(
                [
                    getattr(self.store, "_config", {}),
                    getattr(self.store, "_api_kwargs", {}),
                ]
            )
        config_values.append(self._contract_rules_for(self._position_key(data)))
        for config in config_values:
            if not isinstance(config, dict):
                continue
            exchange = str(
                config.get("exchange_type")
                or config.get("exchange")
                or config.get("exchange_id")
                or ""
            ).upper()
            if exchange == "CTP":
                return True
        return False

    def _ensure_required_net_offset(self, order):
        """Infer safe CTP-style offsets for net-position orders."""
        if self._is_dual_side_mode() or not self._requires_explicit_offset(order.data):
            return None

        explicit_offset = self._order_info_get(order, "offset")
        if explicit_offset not in (None, ""):
            return self._validate_explicit_net_offset(order, explicit_offset)

        size = abs(float(order.size or 0.0))
        if size <= 0.0:
            return None

        position = self.getposition(order.data, clone=False)
        current_size = float(position.size or 0.0)
        if order.isbuy():
            if current_size < 0.0:
                if size > abs(current_size) + 1e-12:
                    return (
                        "net_reversal_requires_split",
                        "CTP net-position reversal orders must be split into close and open legs",
                    )
                order.addinfo(offset="close")
            else:
                order.addinfo(offset="open")
        else:
            if current_size > 0.0:
                if size > current_size + 1e-12:
                    return (
                        "net_reversal_requires_split",
                        "CTP net-position reversal orders must be split into close and open legs",
                    )
                order.addinfo(offset="close")
            else:
                order.addinfo(offset="open")
        return None

    def _validate_explicit_net_offset(self, order, offset):
        offset_text = str(offset or "").strip().lower()
        if offset_text not in {"close", "close_today", "close_yesterday"}:
            return None

        size = abs(float(order.size or 0.0))
        if size <= 0.0:
            return None

        position = self.getposition(order.data, clone=False)
        current_size = float(position.size or 0.0)
        if order.isbuy():
            closable = abs(current_size) if current_size < 0.0 else 0.0
        else:
            closable = current_size if current_size > 0.0 else 0.0
        if size > closable + 1e-12:
            return (
                "close_size_exceeds_position",
                "CTP close order size exceeds the available position",
            )
        return None

    def _contract_rules_for(self, data_name):
        """Resolve contract metadata from the broker and store configuration."""
        rules = {}
        aliases = self._symbol_aliases(data_name)
        for alias in aliases:
            rules.update(self._contract_metadata.get(alias, {}))
        alias_set = set(aliases)
        for key, value in self._contract_metadata.items():
            if key in aliases:
                continue
            if alias_set.intersection(self._symbol_aliases(key)):
                rules.update(value)
        if self.store is not None and hasattr(self.store, "get_contract_metadata"):
            rules.update(self.store.get_contract_metadata(data_name) or {})
        return rules

    def _emit_runtime_event(self, event_type, **kwargs):
        """Proxy runtime events through the store notification queue when available."""
        if self.store is not None and hasattr(self.store, "emit_runtime_event"):
            return self.store.emit_runtime_event(event_type, **kwargs)
        return None

    def _order_runtime_details(self, order):
        """Build a stable runtime-event payload for an order object."""
        external_order_id = self._order_info_get(order, "external_order_id")
        ctp_order_ref = self._order_info_get(order, "ctp_order_ref")
        return {
            "order_ref": getattr(order, "ref", None),
            "external_order_id": external_order_id,
            "ctp_order_ref": ctp_order_ref,
            "data_name": self._position_key(order.data),
            "side": "buy" if order.isbuy() else "sell",
            "size": abs(float(order.size or 0.0)),
            "price": (
                order.price if order.price is not None else getattr(order.created, "price", None)
            ),
            "status": order.getstatusname(),
        }

    def _drain_store_updates(self):
        """Consume remote broker updates from the store and reflect them locally."""
        if self.store is None or not hasattr(self.store, "poll_broker_update"):
            return

        while True:
            raw_update = self.store.poll_broker_update()
            if raw_update is None:
                break

            for update in self._iter_broker_update_rows(raw_update):
                kind = str(update.get("kind") or "").lower()
                if kind == "order":
                    self._apply_order_update(update)
                elif kind == "trade":
                    self._apply_trade_update(update)
                elif kind == "error":
                    self._apply_error_update(update)

    @classmethod
    def _iter_broker_update_rows(cls, update):
        """Yield flat broker updates from exchange envelopes such as WS data lists."""
        if not isinstance(update, dict):
            return

        data = update.get("data")
        if isinstance(data, dict):
            rows = [data]
        elif isinstance(data, (list, tuple)):
            rows = [item for item in data if isinstance(item, dict)]
        else:
            yield update
            return

        if not rows:
            yield update
            return

        envelope = {key: value for key, value in update.items() if key not in {"data", "id"}}
        if update.get("id") not in (None, ""):
            envelope["message_id"] = update.get("id")
        for row in rows:
            flat = dict(envelope)
            flat.update(row)
            if "kind" not in flat and update.get("kind") not in (None, ""):
                flat["kind"] = update.get("kind")
            yield flat

    def _trade_dedupe_key(self, update, order=None):
        """Build a stable trade dedupe key when the provider exposes a fill id."""
        trade_id = self._extract_update_value(
            update,
            "trade_id",
            "tradeId",
            "TradeID",
            "exec_id",
            "execId",
            "execID",
            "execution_id",
            "executionId",
            "fill_id",
            "fillId",
        )
        if trade_id in (None, ""):
            return None

        order_key = (
            self._remote_external_order_id(update)
            or self._remote_client_order_ref(update)
            or self._extract_update_value(update, "bt_order_ref")
        )
        if order_key in (None, "") and order is not None:
            order_key = getattr(order, "ref", None)
        if order_key in (None, "") and order is None:
            return None

        data_name = self._extract_update_value(update, *_DATA_NAME_KEYS)
        if data_name in (None, "") and order is not None:
            data_name = self._position_key(order.data)

        return (str(order_key), str(data_name or ""), str(trade_id))

    def _trade_update_details(self, update, order=None, **extra):
        """Return a compact runtime-event payload for a remote trade update."""
        details = {
            key: update.get(key)
            for key in (
                "kind",
                "trade_id",
                "execID",
                "external_order_id",
                "externalOrderId",
                "venue_order_id",
                "venueOrderId",
                "ordId",
                "order_id",
                "orderId",
                "OrderID",
                "OrderSysID",
                "order_ref",
                "orderRef",
                "client_order_id",
                "clientOrderId",
                "clOrdId",
                "bt_order_ref",
                "data_name",
                "dataname",
                "symbol",
                "instrument",
                "instId",
                "exchange_id",
                "side",
                "Side",
                "position_side",
                "positionSide",
                "posSide",
                "offset",
                "size",
                "execQty",
                "fillSz",
                "accFillSz",
                "price",
                "execPrice",
                "execFee",
                "fillPx",
                "avgPx",
                "px",
                "timestamp",
            )
            if update.get(key) not in (None, "")
        }
        if order is not None:
            details["local_order"] = self._order_runtime_details(order)
        details.update(extra)
        return details

    @staticmethod
    def _order_remaining_qty(order):
        """Return absolute local remaining quantity for a live order."""
        try:
            return abs(float(order.executed.remsize or 0.0))
        except (TypeError, ValueError):
            return 0.0

    def _pending_trade_update_limit(self):
        try:
            return max(int(self.p.pending_trade_update_limit or 0), 0)
        except (TypeError, ValueError):
            return 0

    def _defer_trade_update(self, update):
        """Temporarily hold a trade update until a later order update maps it."""
        limit = self._pending_trade_update_limit()
        if limit <= 0:
            self._emit_runtime_event(
                "trade_update_dropped",
                level="ERROR",
                error_code="unmatched_trade_update",
                error_msg=(
                    "Remote trade update could not be matched to a local order and "
                    "pending trade caching is disabled"
                ),
                status="dropped",
                details=self._trade_update_details(update),
            )
            return

        while len(self._pending_trade_updates) >= limit:
            dropped = self._pending_trade_updates.popleft()
            self._emit_runtime_event(
                "trade_update_dropped",
                level="ERROR",
                error_code="pending_trade_update_limit_exceeded",
                error_msg="Dropped the oldest unmatched remote trade update",
                status="dropped",
                details=self._trade_update_details(dropped),
            )

        self._pending_trade_updates.append(deepcopy(update))
        self._emit_runtime_event(
            "trade_update_deferred",
            level="WARNING",
            error_code="unmatched_trade_update",
            error_msg=(
                "Remote trade update was deferred until a matching order identifier arrives"
            ),
            status="deferred",
            details=self._trade_update_details(update),
        )

    def _retry_pending_trade_updates(self):
        """Retry deferred trade updates after order identifiers are refreshed."""
        if not self._pending_trade_updates:
            return

        pending = self._pending_trade_updates
        self._pending_trade_updates = collections.deque()
        while pending:
            update = pending.popleft()
            status = self._apply_trade_update(update, defer_unmatched=False)
            if status == "unmatched":
                self._pending_trade_updates.append(update)

    def _apply_submit_response_fill(self, order, response):
        """Apply immediate fill details returned by a synchronous submit call."""
        if not isinstance(response, dict):
            return "ignored"
        status = self._normalize_remote_order_status(response.get("status"))
        if status not in {"partial", "completed"}:
            return "ignored"

        filled = self._extract_update_value(response, *_SUBMIT_FILL_QTY_KEYS)
        price = self._extract_update_value(response, *_FILL_PRICE_KEYS)
        if filled in (None, "") or price in (None, ""):
            return "ignored"

        update = dict(response)
        update["kind"] = "order"
        update["status"] = status
        update["filled"] = filled
        update["price"] = price
        update.setdefault("bt_order_ref", getattr(order, "ref", None))
        update.setdefault("data_name", self._position_key(order.data))
        update.setdefault("side", "buy" if order.isbuy() else "sell")
        deal_id = update.get("deal")
        if deal_id not in (None, ""):
            update.setdefault("trade_id", deal_id)
        return self._apply_order_update(update)

    def _apply_order_update(self, update):
        """Apply a normalized remote order-status update."""
        order = self._lookup_order(update)
        if order is None:
            return

        self._cache_order_identifiers(order, update)
        self._retry_pending_trade_updates()

        status = self._normalize_remote_order_status(update.get("status"))
        status_msg = str(update.get("status_msg") or "")
        if status_msg:
            order.addinfo(error_msg=status_msg)

        if status == "accepted" and order.status < order.Accepted:
            order.accept(self)
            self.notify(order)
        elif status in {"partial", "completed"}:
            self._apply_trade_from_order_update(order, update)
        elif status == "canceled":
            self._apply_trade_from_order_update(order, update)
            if order.status not in (order.Canceled, order.Completed):
                order.cancel()
                self.notify(order)
            self._clear_order_mappings(order)
        elif status == "cancel_rejected":
            if bool(self._order_info_get(order, "cancel_requested_remote", False)):
                order.addinfo(
                    cancel_requested_remote=False,
                    cancel_reject_msg=status_msg,
                    cancel_reject_code=str(update.get("error_code") or ""),
                )
                self.notify(order)
        elif status == "rejected":
            if status_msg:
                order.addinfo(error_code="remote_reject", error_msg=status_msg)
            if order.status not in (order.Rejected, order.Completed):
                order.reject(self)
                self.notify(order)
            self._clear_order_mappings(order)
        elif status == "expired":
            self._apply_trade_from_order_update(order, update)
            if order.status not in (order.Expired, order.Completed):
                order.expire()
                self.notify(order)
            self._clear_order_mappings(order)

    @staticmethod
    def _normalize_remote_order_status(status):
        text = str(status or "").strip().lower().replace("-", "_").replace(" ", "_")
        if text in {"accepted", "new", "open", "live", "working", "pre_submitted"}:
            return "accepted"
        if text in {"partial", "partial_filled", "partially_filled"}:
            return "partial"
        if text in {"filled", "completed", "complete", "done", "closed", "fully_filled"}:
            return "completed"
        if text in {
            "canceled",
            "cancelled",
            "cancel",
            "mmp_canceled",
            "partial_canceled",
            "partial_cancelled",
            "partial_filled_canceled",
            "partial_filled_cancelled",
            "part_filled_canceled",
            "part_filled_cancelled",
            "partially_filled_canceled",
            "partially_filled_cancelled",
            "filled_canceled",
            "filled_cancelled",
        }:
            return "canceled"
        if text in {
            "cancel_rejected",
            "cancel_reject",
            "cancel_failed",
            "cancel_error",
            "cancel_denied",
            "cancel_request_rejected",
            "cancel_request_failed",
        }:
            return "cancel_rejected"
        if text in {"rejected", "reject", "failed", "error"}:
            return "rejected"
        if text in {"expired", "expired_in_match"}:
            return "expired"
        return text

    def _apply_trade_from_order_update(self, order, update):
        """Apply fill details embedded in a remote order-status update."""
        filled_value = self._extract_update_value(update, *_CUMULATIVE_FILL_QTY_KEYS)
        if filled_value in (None, ""):
            return "ignored"
        try:
            cumulative_filled = abs(float(filled_value))
            already_filled = abs(float(order.executed.size or 0.0))
        except (TypeError, ValueError):
            return "ignored"
        incremental_fill = cumulative_filled - already_filled
        if incremental_fill <= 1e-12:
            return "ignored"

        price_value = self._extract_update_value(update, *_FILL_PRICE_KEYS)
        if price_value in (None, ""):
            return "ignored"
        try:
            price = float(price_value)
        except (TypeError, ValueError):
            return "ignored"
        if price <= 0:
            return "ignored"

        trade_update = dict(update)
        trade_update["kind"] = "trade"
        trade_update["size"] = incremental_fill
        trade_update["price"] = price
        trade_update.setdefault("side", "buy" if order.isbuy() else "sell")
        status = self._apply_trade_update(trade_update, defer_unmatched=False)
        if status == "applied" and self._trade_dedupe_key(update, order=order) is None:
            self._remember_status_fill_fingerprint(order, trade_update, incremental_fill, price)
        return status

    def _fill_fingerprint(self, order, update, fill_qty, fill_price):
        order_key = (
            self._remote_external_order_id(update)
            or self._remote_client_order_ref(update)
            or self._extract_update_value(update, "bt_order_ref")
        )
        if order_key in (None, ""):
            order_key = getattr(order, "ref", None)
        data_name = self._extract_update_value(update, *_DATA_NAME_KEYS)
        if data_name in (None, ""):
            data_name = self._position_key(order.data)
        side = "buy" if self._trade_update_is_buy(update, order) else "sell"
        try:
            qty = round(abs(float(fill_qty)), 12)
            price = round(float(fill_price), 12)
        except (TypeError, ValueError):
            return None
        if qty <= 0 or price <= 0:
            return None
        return (str(order_key), str(data_name or ""), side, qty, price)

    def _remember_status_fill_fingerprint(self, order, update, fill_qty, fill_price):
        fingerprint = self._fill_fingerprint(order, update, fill_qty, fill_price)
        if fingerprint is not None:
            self._status_fill_fingerprints[fingerprint] += 1

    def _consume_status_fill_fingerprint(self, order, update, fill_qty, fill_price):
        fingerprint = self._fill_fingerprint(order, update, fill_qty, fill_price)
        if fingerprint is None:
            return False
        count = self._status_fill_fingerprints.get(fingerprint, 0)
        if count <= 0:
            return False
        if count == 1:
            self._status_fill_fingerprints.pop(fingerprint, None)
        else:
            self._status_fill_fingerprints[fingerprint] = count - 1
        return True

    def _apply_trade_update(self, update, *, defer_unmatched=True):
        """Apply a normalized remote trade fill to the local order/position state."""
        trade_key = self._trade_dedupe_key(update)
        if trade_key and trade_key in self._seen_trade_ids:
            return "ignored"

        order = self._lookup_order(update)
        if order is None:
            if defer_unmatched:
                self._defer_trade_update(update)
            return "unmatched"

        if trade_key is None:
            trade_key = self._trade_dedupe_key(update, order=order)
        if trade_key and trade_key in self._seen_trade_ids:
            return "ignored"

        fill_qty_value = self._extract_update_value(update, *_FILL_QTY_KEYS)
        try:
            fill_qty = abs(float(fill_qty_value or 0.0))
        except (TypeError, ValueError):
            fill_qty = 0.0
        if fill_qty <= 0:
            return "ignored"
        fill_price_value = self._extract_update_value(update, *_FILL_PRICE_KEYS)
        try:
            fill_price = float(fill_price_value or 0.0)
        except (TypeError, ValueError):
            fill_price = 0.0
        if fill_price <= 0:
            self._emit_runtime_event(
                "trade_update_ignored",
                level="ERROR",
                order_ref=getattr(order, "ref", None),
                error_code="invalid_trade_price",
                error_msg=(
                    "Remote trade update ignored because it did not include a positive fill price"
                ),
                status=order.getstatusname(),
                details=self._trade_update_details(update, order, fill_price=fill_price_value),
            )
            return "ignored"

        if self._consume_status_fill_fingerprint(order, update, fill_qty, fill_price):
            self._emit_runtime_event(
                "trade_update_ignored",
                level="WARNING",
                order_ref=getattr(order, "ref", None),
                error_code="duplicate_order_status_fill",
                error_msg=(
                    "Remote trade update ignored because the same fill was already "
                    "applied from an order-status update"
                ),
                status=order.getstatusname(),
                details=self._trade_update_details(update, order),
            )
            if trade_key:
                self._seen_trade_ids.add(trade_key)
            return "ignored"

        remaining_qty = self._order_remaining_qty(order)
        if remaining_qty <= 1e-12:
            self._emit_runtime_event(
                "trade_update_ignored",
                level="WARNING",
                order_ref=getattr(order, "ref", None),
                error_code="no_order_remaining",
                error_msg="Remote trade update ignored because the local order is already filled",
                status=order.getstatusname(),
                details=self._trade_update_details(update, order, remaining_qty=remaining_qty),
            )
            if trade_key:
                self._seen_trade_ids.add(trade_key)
            return "ignored"

        if fill_qty > remaining_qty + 1e-12:
            self._emit_runtime_event(
                "trade_update_size_clipped",
                level="ERROR",
                order_ref=getattr(order, "ref", None),
                error_code="trade_size_exceeds_remaining",
                error_msg=(
                    "Remote trade update size exceeds the local order remaining size; "
                    "only the remaining size was applied"
                ),
                status=order.getstatusname(),
                details=self._trade_update_details(
                    update,
                    order,
                    remaining_qty=remaining_qty,
                    requested_fill_qty=fill_qty,
                    applied_fill_qty=remaining_qty,
                ),
            )
            fill_qty = remaining_qty

        if self._is_dual_side_mode():
            self._apply_dual_side_trade_update(order, update, fill_qty, fill_price)
            if trade_key:
                self._seen_trade_ids.add(trade_key)
            return "applied"

        signed_fill = fill_qty if self._trade_update_is_buy(update, order) else -fill_qty

        key = self._position_key(order.data)
        position = self.positions[key]
        old_size = position.size
        old_price = position.price
        psize, pprice, opened, closed = position.update(
            signed_fill,
            fill_price,
            dt=self._execution_datetime(update),
        )

        closed_qty = abs(closed)
        opened_qty = abs(opened)
        comminfo = order.comminfo or self.getcommissioninfo(order.data)
        closed_commission, opened_commission = self._execution_commissions(
            comminfo,
            fill_price,
            opened_qty,
            closed_qty,
            self._order_info_get(order, "offset") or update.get("offset"),
            actual_commission=self._remote_commission(update),
            fill_role=self._fill_commission_role(update),
        )
        closed_value = self._execution_value(comminfo, closed, old_price or fill_price)
        opened_value = self._execution_value(comminfo, opened, fill_price)
        pnl = 0.0
        if closed_qty:
            pnl = (
                comminfo.profitandloss(-closed, old_price, fill_price)
                if comminfo is not None
                else closed_qty
                * (fill_price - old_price if old_size > 0 else old_price - fill_price)
            )

        order.execute(
            dt=self._order_execution_dt(order),
            size=signed_fill,
            price=fill_price,
            closed=closed,
            closedvalue=closed_value,
            closedcomm=closed_commission,
            opened=opened,
            openedvalue=opened_value,
            openedcomm=opened_commission,
            margin=0.0,
            pnl=pnl,
            psize=psize,
            pprice=pprice,
        )

        self._cache_order_identifiers(order, update)

        if self._order_remaining_qty(order) > 1e-12:
            order.partial()
        else:
            order.completed()
            self._clear_order_mappings(order)
        self.notify(order)
        if trade_key:
            self._seen_trade_ids.add(trade_key)
        return "applied"

    def _apply_dual_side_trade_update(self, order, update, fill_qty, fill_price):
        isbuy = self._trade_update_is_buy(update, order)
        offset = self._order_info_get(order, "offset") or update.get("offset")
        position_side = (
            self._order_info_get(order, "position_side")
            or update.get("position_side")
            or update.get("positionSide")
            or update.get("posSide")
            or infer_position_side(isbuy, offset)
        )
        position_side = normalize_position_side(position_side)
        exec_size = fill_qty if isbuy else -fill_qty

        leg_position = self._get_leg_position(order.data, position_side)
        signed_position = self._make_signed_position(position_side, leg_position)
        pprice_orig = signed_position.price
        psize, pprice, opened, closed = signed_position.update(
            exec_size,
            fill_price,
            dt=self._execution_datetime(update),
        )

        closed_qty = abs(closed)
        opened_qty = abs(opened)
        comminfo = order.comminfo or self.getcommissioninfo(order.data)
        closed_commission, opened_commission = self._execution_commissions(
            comminfo,
            fill_price,
            opened_qty,
            closed_qty,
            offset,
            actual_commission=self._remote_commission(update),
            fill_role=self._fill_commission_role(update),
        )
        closed_value = self._execution_value(comminfo, closed, pprice_orig or fill_price)
        opened_value = self._execution_value(comminfo, opened, fill_price)
        pnl = comminfo.profitandloss(-closed, pprice_orig, fill_price) if closed else 0.0

        self._apply_signed_position(position_side, leg_position, signed_position)
        self._sync_net_position(order.data)

        order.execute(
            dt=self._order_execution_dt(order),
            size=exec_size,
            price=fill_price,
            closed=closed,
            closedvalue=closed_value,
            closedcomm=closed_commission,
            opened=opened,
            openedvalue=opened_value,
            openedcomm=opened_commission,
            margin=0.0,
            pnl=pnl,
            psize=psize,
            pprice=pprice,
        )

        order.addinfo(position_side=position_side)
        if offset is not None:
            order.addinfo(offset=offset)
        self._cache_order_identifiers(order, update)

        if self._order_remaining_qty(order) > 1e-12:
            order.partial()
        else:
            order.completed()
            self._clear_order_mappings(order)
        self.notify(order)
        return "applied"

    def _apply_error_update(self, update):
        """Apply a normalized remote error update to a tracked order when possible."""
        order = self._lookup_order(update)
        if order is None or not order.alive():
            return

        self._cache_order_identifiers(order, update)
        error_code = str(update.get("error_code") or "remote_error")
        error_msg = str(update.get("error_msg") or update.get("status_msg") or "")
        order.addinfo(error_code=error_code, error_msg=error_msg)
        if order.status != order.Rejected:
            order.reject(self)
            self._clear_order_mappings(order)
            self.notify(order)

    def _clear_order_mappings(self, order):
        """Drop cached identifier mappings once an order reaches a terminal state."""
        for key, mapped_order in list(self._orders_by_external_id.items()):
            if mapped_order is order:
                self._orders_by_external_id.pop(key, None)
        for key, mapped_order in list(self._orders_by_client_ref.items()):
            if mapped_order is order:
                self._orders_by_client_ref.pop(key, None)

    def _lookup_order(self, update):
        """Resolve a local order object from normalized broker update identifiers."""
        external_id = self._remote_external_order_id(update)
        if external_id not in (None, ""):
            order = self._orders_by_external_id.get(str(external_id))
            if order is not None:
                return order

        order_ref = self._remote_client_order_ref(update)
        if order_ref not in (None, ""):
            order = self._orders_by_client_ref.get(str(order_ref))
            if order is not None:
                return order
            try:
                normalized_order_ref = int(str(order_ref).strip())
            except (TypeError, ValueError):
                normalized_order_ref = None
            if normalized_order_ref in self.orders:
                return self.orders[normalized_order_ref]
            if order_ref in self.orders:
                return self.orders[order_ref]

        details = update.get("details") or {}
        bt_order_ref = details.get("bt_order_ref") or update.get("bt_order_ref")
        if bt_order_ref in self.orders:
            return self.orders[bt_order_ref]
        if bt_order_ref not in (None, ""):
            try:
                normalized_ref = int(bt_order_ref)
            except (TypeError, ValueError):
                normalized_ref = None
            if normalized_ref in self.orders:
                return self.orders[normalized_ref]

        return None

    def _cache_order_identifiers(self, order, update):
        """Attach provider identifiers from a remote update to a local order."""
        external_id = self._remote_external_order_id(update)
        order_ref = self._remote_client_order_ref(update)
        if external_id not in (None, ""):
            order.addinfo(external_order_id=external_id)
            self._orders_by_external_id[str(external_id)] = order
        if order_ref not in (None, ""):
            order.addinfo(ctp_order_ref=order_ref)
            self._orders_by_client_ref[str(order_ref)] = order
        for key in ("front_id", "session_id", "exchange_id"):
            value = self._extract_update_value(update, key)
            if value not in (None, ""):
                order.addinfo(**{key: value})

    @staticmethod
    def _order_info_get(order, key, default=None):
        """Read order.info without triggering AutoOrderedDict auto-vivification."""
        info = getattr(order, "info", None)
        if info is None:
            return default
        getter = getattr(info, "get", None)
        if callable(getter):
            value = getter(key, default)
            return default if value in (None, "") else value
        value = getattr(info, key, default)
        return default if value in (None, "") else value

    @classmethod
    def _trade_update_is_buy(cls, update, order=None):
        side = cls._extract_update_value(
            update,
            "side",
            "Side",
            "direction",
            "Direction",
            "trade_side",
            "tradeSide",
        )
        if side in (None, ""):
            return bool(order.isbuy()) if order is not None else True

        text = cls._normalise_code_text(side)
        if text in {"buy", "long", "b", "bid", "0"}:
            return True
        if text in {"sell", "short", "s", "ask", "1"}:
            return False
        return bool(order.isbuy()) if order is not None else True

    @staticmethod
    def _extract_update_value(update, *keys):
        """Read a top-level or detail payload field from a broker update."""
        details = update.get("details") or {}
        for key in keys:
            value = update.get(key)
            if value not in (None, ""):
                return value
            value = details.get(key)
            if value not in (None, ""):
                return value
        return None

    @classmethod
    def _uses_okx_fee_sign(cls, update):
        values = [
            cls._extract_update_value(
                update,
                "exchange",
                "exchange_id",
                "exchange_name",
                "provider",
                "gateway",
                "broker",
            )
        ]
        details = update.get("details") or {}
        values.extend(
            details.get(key)
            for key in (
                "exchange",
                "exchange_id",
                "exchange_name",
                "provider",
                "gateway",
                "broker",
            )
        )
        return any("OKX" in str(value or "").upper() for value in values)

    @classmethod
    def _remote_commission(cls, update):
        keys = (
            "commission",
            "comm",
            "fee",
            "fees",
            "exec_fee",
            "execFee",
            "execFeeV2",
            "fill_fee",
            "fillFee",
            "trade_fee",
            "trade_commission",
            "commission_amount",
            "n",
        )
        details = update.get("details") or {}
        for key in keys:
            for source in (update, details):
                value = source.get(key)
                if value in (None, ""):
                    continue
                try:
                    commission = float(value)
                except (TypeError, ValueError):
                    continue
                if cls._truthy(cls._extract_update_value(update, "commission_signed")):
                    return commission
                if key in {"fee", "trade_fee", "trade_commission"} and cls._uses_okx_fee_sign(
                    update
                ):
                    return -commission
                return abs(commission)
        return None

    @classmethod
    def _execution_commissions(
        cls,
        comminfo,
        price,
        opened_qty,
        closed_qty,
        offset=None,
        actual_commission=None,
        fill_role=None,
    ):
        """Return closed/opened commissions using offset-specific futures fees."""
        opened_qty = abs(float(opened_qty or 0.0))
        closed_qty = abs(float(closed_qty or 0.0))
        if actual_commission is not None:
            total_commission = float(actual_commission or 0.0)
            total_qty = opened_qty + closed_qty
            if total_qty <= 0.0:
                return 0.0, 0.0
            if closed_qty <= 0.0:
                return 0.0, total_commission
            if opened_qty <= 0.0:
                return total_commission, 0.0
            closed_commission = total_commission * (closed_qty / total_qty)
            return closed_commission, total_commission - closed_commission
        if comminfo is None:
            return 0.0, 0.0
        fill_role = cls._normalise_fill_commission_role(fill_role)
        close_role = cls._close_commission_role(offset)
        closed_role = close_role
        if close_role not in {"close_today", "close_yesterday"}:
            closed_role = fill_role or close_role
        opened_role = fill_role or "open"
        closed_commission = (
            cls._commission_for_role(
                comminfo,
                closed_qty,
                price,
                closed_role,
            )
            if closed_qty > 0.0
            else 0.0
        )
        opened_commission = (
            cls._commission_for_role(comminfo, opened_qty, price, opened_role)
            if opened_qty > 0.0
            else 0.0
        )
        return closed_commission, opened_commission

    @classmethod
    def _fill_commission_role(cls, update):
        role = cls._normalise_fill_commission_role(
            cls._extract_update_value(
                update,
                "commission_role",
                "fill_role",
                "liquidity_role",
                "liquidity",
                "trade_type",
                "tradeType",
                "exec_type",
                "execType",
                "match_type",
                "maker_taker",
            )
        )
        if role is not None:
            return role

        for key in ("is_maker", "isMaker", "maker", "m"):
            value = cls._extract_update_value(update, key)
            if value in (None, ""):
                continue
            return "maker" if cls._truthy(value) else "taker"
        return None

    @staticmethod
    def _normalise_fill_commission_role(value):
        if value in (None, ""):
            return None
        text = str(value).strip().lower().replace("-", "_")
        if text in {"maker", "m", "make", "post_only", "postonly", "liquidity_maker"}:
            return "maker"
        if text in {"taker", "t", "take", "liquidity_taker"}:
            return "taker"
        if "maker" in text:
            return "maker"
        if "taker" in text:
            return "taker"
        return None

    @staticmethod
    def _truthy(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        text = BtApiBroker._normalise_code_text(value)
        return text in {"1", "true", "yes", "y", "maker", "m"}

    @staticmethod
    def _close_commission_role(offset):
        offset_text = str(offset or "").strip().lower()
        if offset_text in {"close_today", "closetoday"}:
            return "close_today"
        if offset_text in {"close_yesterday", "closeyesterday"}:
            return "close_yesterday"
        return "close"

    @staticmethod
    def _commission_for_role(comminfo, size, price, role):
        try:
            return float(comminfo.getcommission(size, price, role=role) or 0.0)
        except TypeError:
            return float(comminfo.getcommission(size, price) or 0.0)

    @staticmethod
    def _execution_value(comminfo, size, price):
        """Return an execution value using the commission scheme's contract rules."""
        size = float(size or 0.0)
        price = float(price or 0.0)
        if not size:
            return 0.0
        if comminfo is None:
            return abs(size) * abs(price)
        try:
            return abs(float(comminfo.getoperationcost(size, price) or 0.0))
        except Exception:
            return abs(size) * abs(price)

    @staticmethod
    def _execution_datetime(update):
        """Convert a remote broker update timestamp into a best-effort datetime."""
        stamp = update.get("timestamp")
        if isinstance(stamp, _dt.datetime):
            return stamp
        if isinstance(stamp, str) and stamp:
            today = _dt.date.today()
            for fmt in ("%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d %H:%M:%S"):
                try:
                    parsed = _dt.datetime.strptime(stamp, fmt)
                except ValueError:
                    continue
                if fmt == "%H:%M:%S":
                    return _dt.datetime.combine(today, parsed.time())
                return parsed
        # Naive UTC fallback (consistent with the naive datetimes returned above,
        # used for backtrader order bookkeeping). utcnow() is deprecated in 3.12+.
        return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _order_execution_dt(order):
        """Pick a stable execution dt compatible with backtrader order bookkeeping."""
        try:
            if len(order.data):
                return order.data.datetime[0]
        except Exception as e:
            logger.debug("Failed to get order execution datetime: %s", e)
        return 0.0
