#!/usr/bin/env python
"""Unified bt_api_py-backed live broker."""

from __future__ import annotations

import collections
import datetime as _dt
import logging
import time

from ..broker import BrokerBase
from ..order import BuyOrder, SellOrder
from ..position import Position

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
        self._orders_by_external_id = {}
        self._orders_by_client_ref = {}
        self._seen_trade_ids = set()

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
            order.addcomminfo(self.getcommissioninfo(order.data))
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
        self.store.cancel_order(order)
        order.cancel()
        self.notify(order)
        return order

    def next(self):
        """Refresh cached balances and positions."""
        self._drain_store_updates()
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
        except Exception as e:
            logger.debug("Failed to sync positions: %s", e)
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
                "price": order.price if order.price is not None else getattr(order.created, "price", None),
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
            "price": order.price if order.price is not None else getattr(order.created, "price", None),
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

    def _apply_order_update(self, update):
        """Apply a normalized remote order-status update."""
        order = self._lookup_order(update)
        if order is None:
            return

        external_id = update.get("external_order_id")
        order_ref = update.get("order_ref")
        if external_id not in (None, ""):
            order.addinfo(external_order_id=external_id)
            self._orders_by_external_id[str(external_id)] = order
        if order_ref not in (None, ""):
            order.addinfo(ctp_order_ref=order_ref)
            self._orders_by_client_ref[str(order_ref)] = order
        for key in ("front_id", "session_id", "exchange_id"):
            value = update.get(key)
            if value not in (None, ""):
                order.addinfo(**{key: value})

        status = str(update.get("status") or "").lower()
        status_msg = str(update.get("status_msg") or "")
        if status_msg:
            order.addinfo(error_msg=status_msg)

        if status == "accepted" and order.status < order.Accepted:
            order.accept(self)
            self.notify(order)
        elif status == "canceled" and order.status != order.Canceled:
            order.cancel()
            self.notify(order)
        elif status == "rejected" and order.status != order.Rejected:
            if status_msg:
                order.addinfo(error_code="remote_reject", error_msg=status_msg)
            order.reject(self)
            self.notify(order)

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
            closedcomm=commission if closed_qty else 0.0,
            opened=opened,
            openedvalue=opened_value,
            openedcomm=commission if opened_qty and not closed_qty else 0.0,
            margin=0.0,
            pnl=pnl,
            psize=psize,
            pprice=pprice,
        )

        external_id = update.get("external_order_id")
        if external_id not in (None, ""):
            order.addinfo(external_order_id=external_id)
            self._orders_by_external_id[str(external_id)] = order
        if update.get("order_ref") not in (None, ""):
            self._orders_by_client_ref[str(update["order_ref"])] = order

        if order.executed.remsize:
            order.partial()
        else:
            order.completed()
        self.notify(order)

    def _lookup_order(self, update):
        """Resolve a local order object from normalized broker update identifiers."""
        external_id = update.get("external_order_id")
        if external_id not in (None, ""):
            order = self._orders_by_external_id.get(str(external_id))
            if order is not None:
                return order

        order_ref = update.get("order_ref")
        if order_ref not in (None, ""):
            order = self._orders_by_client_ref.get(str(order_ref))
            if order is not None:
                return order

        details = update.get("details") or {}
        bt_order_ref = details.get("bt_order_ref") or update.get("bt_order_ref")
        if bt_order_ref in self.orders:
            return self.orders[bt_order_ref]

        return None

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
