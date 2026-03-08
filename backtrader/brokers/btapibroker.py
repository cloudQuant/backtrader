#!/usr/bin/env python
"""Unified bt_api_py-backed live broker."""

from __future__ import annotations

import collections
import time

from .livebroker import LiveBrokerBase
from ..broker import BrokerBase
from ..order import BuyOrder, SellOrder
from ..position import Position


class BtApiBroker(BrokerBase, LiveBrokerBase):
    """Broker implementation that routes live orders through BtApiStore."""

    params = (
        ("store", None),
        ("provider", "btapi"),
        ("cash", 0.0),
        ("value", None),
        ("account_refresh_interval", 1.0),
        ("positions_refresh_interval", 1.0),
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
        except Exception:
            order.reject(self)
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
