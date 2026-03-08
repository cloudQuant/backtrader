#!/usr/bin/env python
"""Unified bt_api_py-backed live broker."""

from __future__ import annotations

import collections
import time

from ..broker import BrokerBase
from ..order import BuyOrder, SellOrder
from ..position import Position


class BtApiBroker(BrokerBase):
    """Broker implementation that routes live orders through BtApiStore."""

    params = (
        ("store", None),
        ("provider", "btapi"),
        ("cash", 0.0),
        ("value", None),
        ("account_refresh_interval", 1.0),
        ("positions_refresh_interval", 1.0),
        ("validation_enabled", True),
        ("contract_metadata", None),
        ("max_order_size", 0),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.store = self.p.store
        self.provider = self.p.provider
        self.notifs = collections.deque()
        self.orders = collections.OrderedDict()
        self.positions = collections.defaultdict(Position)
        self._cash = float(self.p.cash or 0.0)
        self._value = float(self.p.value if self.p.value is not None else self._cash)
        self._live_started = False
        self.startingcash = self._cash
        self.startingvalue = self._value
        self._last_account_refresh = 0.0
        self._last_positions_refresh = 0.0
        self._trading_enabled = True
        self._strategy_paused = False
        self._contract_metadata = {
            str(key): dict(value or {}) for key, value in (self.p.contract_metadata or {}).items()
        }

    def start(self):
        """Start the broker and hydrate account state from the store."""
        super().start()

        if self.store is None:
            raise ValueError("BtApiBroker requires a BtApiStore instance")

        self.store.start(broker=self)
        self._live_started = True
        self._refresh_account(force=True, raise_errors=True)
        self._sync_positions(force=True, raise_errors=True)
        self.startingcash = self._cash
        self.startingvalue = self._value

    def stop(self):
        """Stop the broker."""
        self._live_started = False
        if self.store is not None and self.store.is_connected:
            self.store.stop()

    def getcash(self) -> float:
        """Return current available cash."""
        self._refresh_account(force=True, raise_errors=True)
        return self._cash

    def getvalue(self, datas=None) -> float:
        """Return current portfolio value."""
        self._refresh_account(force=True, raise_errors=True)
        return self._value

    def getposition(self, data, clone=True):
        """Return the cached position for a given data feed."""
        self._sync_positions(force=True, raise_errors=True)
        key = self._position_key(data)
        position = self.positions[key]
        return position.clone() if clone else position

    def submit(self, order):
        """Submit an order through the store."""
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
            response = self.store.submit_order(order)
            order.accept(self)

            external_order_id = None
            if isinstance(response, dict):
                external_order_id = (
                    response.get("id")
                    or response.get("order_id")
                    or response.get("orderId")
                )

            if external_order_id is not None:
                order.addinfo(external_order_id=external_order_id)

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
        self.store.cancel_order(order)
        order.cancel()
        self.notify(order)
        return order

    def next(self):
        """Refresh cached balances and positions."""
        self._refresh_account()
        self._sync_positions()

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
        order.addinfo(**kwargs)
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
        order.addinfo(**kwargs)
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
        cancelled = []
        for order in candidates:
            if not order.alive():
                continue
            self.cancel(order)
            cancelled.append(order)
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
        except Exception:
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
                if direction in {"short", "sell"} and size > 0:
                    size = -size

                price = item.get("price", item.get("avg_price", item.get("average_price", 0.0)))
                synced[key] = Position(size=size, price=float(price or 0.0))

            self.positions = synced
            self._last_positions_refresh = time.monotonic()
        except Exception:
            if raise_errors:
                raise

    @staticmethod
    def _should_refresh(last_refresh, interval):
        """Return whether a throttled live refresh should run now."""
        if interval <= 0:
            return True

        return (time.monotonic() - last_refresh) >= interval

    @staticmethod
    def _position_key(data):
        """Extract a stable position key from a data feed."""
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

        min_price_tick = rules.get("min_price_tick") or rules.get("price_tick")
        price = order.price or getattr(order.created, "price", None)
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
                "price": order.price or getattr(order.created, "price", None),
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
