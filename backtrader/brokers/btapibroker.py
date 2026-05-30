#!/usr/bin/env python
"""Unified bt_api_py-backed live broker."""

from __future__ import annotations

import collections
import datetime as _dt
import logging
import time
from copy import deepcopy

from ..broker import BrokerBase
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

logger = logging.getLogger(__name__)


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
        ("position_mode", "net"),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.store = self.p.store
        self.provider = self.p.provider
        self.notifs = collections.deque()
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
        self._sync_remote_open_orders(force=True)
        self.startingcash = self._cash
        self.startingvalue = self._value
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

    def supports_position_mode(self, mode):
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
        if self.store is not None and self.store.is_connected:
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
        validation_error = self._validate_order(order)
        if validation_error is not None:
            code, message = validation_error
            return self._reject_order(order, code, message)

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
            order.accept(self)

            external_order_id = None
            if isinstance(response, dict):
                external_order_id = (
                    response.get("id") or response.get("order_id") or response.get("orderId")
                )

            if external_order_id is not None:
                order.addinfo(external_order_id=external_order_id)
                self._orders_by_external_id[str(external_order_id)] = order
            order_ref = response.get("order_ref") if isinstance(response, dict) else None
            if order_ref not in (None, ""):
                order.addinfo(ctp_order_ref=order_ref)
                self._orders_by_client_ref[str(order_ref)] = order
            if isinstance(response, dict):
                for key in ("front_id", "session_id", "exchange_id"):
                    if key in response and response[key] not in (None, ""):
                        order.addinfo(**{key: response[key]})

            self.orders[order.ref] = order
            self.notify(order)
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

        if bool(getattr(order.info, "cancel_requested_remote", False)):
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
        return self._sync_remote_open_orders(force=True, raise_errors=True)

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
            "force_logout_requested",
            details={"reason": reason},
            status="disconnecting",
        )
        self._live_started = False
        if self.store is not None and self.store.is_connected:
            self.store.stop()

    def batch_cancel(self, orders=None):
        """Cancel a batch of live orders and return the canceled order objects."""
        candidates = list(orders if orders is not None else self.get_orders_open())
        requested = [self._order_runtime_details(order) for order in candidates]
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
        for order in candidates:
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

        summary = {
            "requested_count": len(candidates),
            "cancelled_count": len(cancelled),
            "failure_count": len(failures),
            "cancelled_orders": [self._order_runtime_details(order) for order in cancelled],
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
            synced = collections.defaultdict(Position)
            long_synced = collections.defaultdict(Position)
            short_synced = collections.defaultdict(Position)
            for item in self.store.get_positions():
                key = (
                    item.get("instrument")
                    or item.get("symbol")
                    or item.get("dataname")
                    or item.get("name")
                )
                if not key:
                    continue

                size = item.get("volume", item.get("size", item.get("position", 0)))
                size = float(size or 0.0)
                direction = str(item.get("direction", "")).lower()

                price = item.get("price", item.get("avg_price", item.get("average_price", 0.0)))
                price = float(price or 0.0)

                if self._is_dual_side_mode():
                    if size and direction not in {"long", "buy", "short", "sell"}:
                        raise ValueError(
                            "dual_side mode requires provider positions with explicit direction"
                        )
                    if direction in {"short", "sell"}:
                        short_synced[key] = Position(size=abs(size), price=price)
                    else:
                        long_synced[key] = Position(size=abs(size), price=price)
                else:
                    if direction in {"short", "sell"} and size > 0:
                        size = -size
                    synced[key] = Position(size=size, price=price)

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

    def _validate_order(self, order):
        """Run lightweight local validation before the order reaches the store."""
        if not bool(self.p.validation_enabled):
            return None

        data_name = self._position_key(order.data)
        rules = self._contract_rules_for(data_name)

        if rules.get("valid") is False or rules.get("exists") is False:
            return "invalid_contract", f"Contract {data_name} is not valid for trading"

        if rules.get("tradable") is False:
            return "contract_not_tradable", f"Contract {data_name} is currently not tradable"

        max_order_size = rules.get("max_order_size", self.p.max_order_size)
        if max_order_size and abs(float(order.size or 0.0)) > float(max_order_size):
            return (
                "max_order_size_exceeded",
                f"Order size {order.size} exceeds the max allowed size {max_order_size}",
            )

        if self._is_dual_side_mode() and getattr(order.info, "offset", None) == "close":
            position_side = normalize_position_side(getattr(order.info, "position_side", None))
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

        return None

    def _reject_order(self, order, error_code, error_msg):
        """Reject an order locally and emit a structured runtime event."""
        order.addinfo(error_code=error_code, error_msg=error_msg)
        order.reject(self)
        self.orders[order.ref] = order
        self.notify(order)
        self._emit_runtime_event(
            "order_reject_local",
            level="ERROR",
            order_ref=order.ref,
            error_code=error_code,
            error_msg=error_msg,
            status="rejected",
            details={
                "data_name": self._position_key(order.data),
                "side": "buy" if order.isbuy() else "sell",
                "size": abs(float(order.size or 0.0)),
                "price": (
                    order.price
                    if order.price is not None
                    else getattr(order.created, "price", None)
                ),
            },
        )
        return order

    def _contract_rules_for(self, data_name):
        """Resolve contract metadata from the broker and store configuration."""
        rules = {}
        rules.update(self._contract_metadata.get(str(data_name), {}))
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
        external_order_id = getattr(order.info, "external_order_id", None)
        ctp_order_ref = getattr(order.info, "ctp_order_ref", None)
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
            update = self.store.poll_broker_update()
            if update is None:
                break

            kind = str(update.get("kind") or "").lower()
            if kind == "order":
                self._apply_order_update(update)
            elif kind == "trade":
                self._apply_trade_update(update)
            elif kind == "error":
                self._apply_error_update(update)

    def _apply_order_update(self, update):
        """Apply a normalized remote order-status update."""
        order = self._lookup_order(update)
        if order is None:
            return

        self._cache_order_identifiers(order, update)

        status = str(update.get("status") or "").lower()
        status_msg = str(update.get("status_msg") or "")
        if status_msg:
            order.addinfo(error_msg=status_msg)

        if status == "accepted" and order.status < order.Accepted:
            order.accept(self)
            self.notify(order)
        elif status == "canceled":
            if order.status not in (order.Canceled, order.Completed):
                order.cancel()
                self.notify(order)
            self._clear_order_mappings(order)
        elif status == "rejected":
            if status_msg:
                order.addinfo(error_code="remote_reject", error_msg=status_msg)
            if order.status not in (order.Rejected, order.Completed):
                order.reject(self)
                self.notify(order)
            self._clear_order_mappings(order)

    def _apply_trade_update(self, update):
        """Apply a normalized remote trade fill to the local order/position state."""
        trade_id = str(update.get("trade_id") or "").strip()
        if trade_id and trade_id in self._seen_trade_ids:
            return
        if trade_id:
            self._seen_trade_ids.add(trade_id)

        order = self._lookup_order(update)
        if order is None:
            return

        fill_qty = abs(float(update.get("size") or 0.0))
        if fill_qty <= 0:
            return

        fill_price = float(update.get("price") or 0.0)
        if self._is_dual_side_mode():
            self._apply_dual_side_trade_update(order, update, fill_qty, fill_price)
            return

        signed_fill = fill_qty if str(update.get("side") or "buy").lower() == "buy" else -fill_qty

        key = self._position_key(order.data)
        position = self.positions[key]
        old_size = position.size
        old_price = position.price
        psize, pprice, opened, closed = position.update(
            signed_fill,
            fill_price,
            dt=self._execution_datetime(update),
        )

        comminfo = order.comminfo or self.getcommissioninfo(order.data)
        commission = comminfo.getcommission(fill_qty, fill_price) if comminfo is not None else 0.0
        closed_qty = abs(closed)
        opened_qty = abs(opened)
        closed_commission, opened_commission = self._split_execution_commission(
            commission,
            fill_qty,
            opened_qty,
            closed_qty,
        )
        closed_value = closed_qty * abs(old_price or fill_price)
        opened_value = opened_qty * abs(fill_price)
        pnl = 0.0
        if closed_qty:
            if old_size > 0:
                pnl = closed_qty * (fill_price - old_price)
            elif old_size < 0:
                pnl = closed_qty * (old_price - fill_price)

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

        if order.executed.remsize:
            order.partial()
        else:
            order.completed()
            self._clear_order_mappings(order)
        self.notify(order)

    def _apply_dual_side_trade_update(self, order, update, fill_qty, fill_price):
        isbuy = str(update.get("side") or "buy").lower() == "buy"
        offset = getattr(order.info, "offset", None) or update.get("offset")
        position_side = (
            getattr(order.info, "position_side", None)
            or update.get("position_side")
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

        comminfo = order.comminfo or self.getcommissioninfo(order.data)
        commission = comminfo.getcommission(fill_qty, fill_price) if comminfo is not None else 0.0
        closed_qty = abs(closed)
        opened_qty = abs(opened)
        closed_commission, opened_commission = self._split_execution_commission(
            commission,
            fill_qty,
            opened_qty,
            closed_qty,
        )
        closed_value = closed_qty * abs(pprice_orig or fill_price)
        opened_value = opened_qty * abs(fill_price)
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

        if order.executed.remsize:
            order.partial()
        else:
            order.completed()
            self._clear_order_mappings(order)
        self.notify(order)

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
        external_order_id = getattr(order.info, "external_order_id", None)
        ctp_order_ref = getattr(order.info, "ctp_order_ref", None)

        if external_order_id not in (None, ""):
            self._orders_by_external_id.pop(str(external_order_id), None)
        if ctp_order_ref not in (None, ""):
            self._orders_by_client_ref.pop(str(ctp_order_ref), None)

    def _lookup_order(self, update):
        """Resolve a local order object from normalized broker update identifiers."""
        external_id = self._extract_update_value(
            update, "external_order_id", "order_id", "OrderSysID"
        )
        if external_id not in (None, ""):
            order = self._orders_by_external_id.get(str(external_id))
            if order is not None:
                return order

        order_ref = self._extract_update_value(update, "order_ref", "ctp_order_ref", "OrderRef")
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
        external_id = self._extract_update_value(
            update, "external_order_id", "order_id", "OrderSysID"
        )
        order_ref = self._extract_update_value(update, "order_ref", "ctp_order_ref", "OrderRef")
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

    @staticmethod
    def _split_execution_commission(total_commission, fill_qty, opened_qty, closed_qty):
        """Split a fill commission between the closing and opening legs of a reversal."""
        total_commission = float(total_commission or 0.0)
        fill_qty = abs(float(fill_qty or 0.0))
        opened_qty = abs(float(opened_qty or 0.0))
        closed_qty = abs(float(closed_qty or 0.0))
        if total_commission == 0.0 or fill_qty <= 0.0:
            return 0.0, 0.0
        if opened_qty <= 0.0:
            return total_commission if closed_qty > 0.0 else 0.0, 0.0
        if closed_qty <= 0.0:
            return 0.0, total_commission

        closed_ratio = min(closed_qty / fill_qty, 1.0)
        closed_commission = total_commission * closed_ratio
        opened_commission = total_commission - closed_commission
        return closed_commission, opened_commission

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
        return _dt.datetime.utcnow()

    @staticmethod
    def _order_execution_dt(order):
        """Pick a stable execution dt compatible with backtrader order bookkeeping."""
        try:
            if len(order.data):
                return order.data.datetime[0]
        except Exception as e:
            logger.debug("Failed to get order execution datetime: %s", e)
        return 0.0
