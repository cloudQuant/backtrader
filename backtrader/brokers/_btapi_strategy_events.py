"""At-least-once strategy ledger events for ``BtApiBroker`` (iteration 60, G5).

In direct mode the SDK strategy ledger's event table is the single source of
a strategy's order/fill events (``SqliteStrategyLedger.read_events``). A
Backtrader process that crashes loses its in-memory order notifications; this
mixin lets a ledger-bound Strategy receive every event of its own ledger
book, after a restart too, through the SDK ``StrategyEventFeed`` and its
durable ``SqliteEventCursorStore`` (no cursor logic lives here).

* Opt in with ``bind_direct_strategy_ledger(..., event_cursor_path=path)``.
  Pending events (for example those not delivered before a crash) are
  delivered at bind time, then after every ledger update this Broker makes,
  and whenever ``deliver_strategy_ledger_events()`` is called.
* Each event goes to ``Strategy.notify_ledger_event(event)``. ``event`` is the
  SDK ``LedgerEvent``: stable ``event_id`` (``generation:cursor``), ``cursor``,
  ``intent_id``, ``action`` and ``detail``.
* **At least once.** The cursor advances only after the hook returned. A
  crash or an exception in the hook redelivers the same event (same
  ``event_id``) later. A side effect that must not repeat has to be
  idempotent or keyed by ``event_id`` in the same durable transaction (see
  ``bt_api_py.strategy_event_feed.DeliveredEventFilter``); anything else is
  at-least-once, not exactly-once.
* **Own scope only.** A Strategy only receives its own book's events.
* **One ledger generation.** A cursor saved for another (rebuilt) ledger is
  refused with ``RESYNC_REQUIRED`` instead of being mapped onto new events.
"""

from __future__ import annotations

from ..utils.log_message import get_logger

_logger = get_logger(__name__)


class StrategyLedgerEventError(RuntimeError):
    """Finite, value-free event-delivery failure (``code`` from the SDK)."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class StrategyLedgerEventsBrokerMixin:
    """Deliver each bound Strategy's ledger events at least once."""

    _direct_strategy_event_feeds = None

    def _bind_strategy_ledger_events(self, strategy, ledger, strategy_ref, cursor_path):
        from bt_api_py.strategy_event_feed import SqliteEventCursorStore, StrategyEventFeed

        if self._direct_strategy_event_feeds is None:
            self._direct_strategy_event_feeds = {}
        store = SqliteEventCursorStore(cursor_path, f"backtrader:{strategy_ref}")
        feed = StrategyEventFeed(ledger, strategy_ref, store)
        self._direct_strategy_event_feeds[id(strategy)] = (strategy, feed, store)
        try:
            self.deliver_strategy_ledger_events(strategy)
        except BaseException:
            del self._direct_strategy_event_feeds[id(strategy)]
            store.close()
            raise

    def deliver_strategy_ledger_events(self, strategy=None):
        """Deliver pending ledger events; return how many were delivered.

        ``strategy=None`` delivers for every bound Strategy. An exception from
        a hook propagates after the events before it were committed; the
        failing event is delivered again next time. ``RESYNC_REQUIRED`` and
        other feed failures raise ``StrategyLedgerEventError``.
        """

        from bt_api_py.strategy_event_feed import StrategyEventFeedError

        feeds = self._direct_strategy_event_feeds or {}
        targets = (
            list(feeds.values())
            if strategy is None
            else [feeds[id(strategy)]] if id(strategy) in feeds else []
        )
        delivered = 0
        for owner, feed, _store in targets:
            hook = getattr(owner, "notify_ledger_event", None)
            try:
                delivered += feed.poll(hook)
            except StrategyEventFeedError as error:
                raise StrategyLedgerEventError(error.code) from None
        return delivered

    def _deliver_after_ledger_update(self, order) -> None:
        """Called after each ledger update; never breaks order processing."""

        strategy = getattr(order, "owner", None)
        if strategy is None or id(strategy) not in (self._direct_strategy_event_feeds or {}):
            return
        try:
            self.deliver_strategy_ledger_events(strategy)
        except Exception as error:  # redelivered on the next cycle
            _logger.error(
                "strategy ledger event delivery failed; will retry (%s)",
                getattr(error, "code", type(error).__name__),
            )

    def close_strategy_ledger_events(self) -> None:
        for _owner, _feed, store in (self._direct_strategy_event_feeds or {}).values():
            store.close()
        self._direct_strategy_event_feeds = None


# ---------------------------------------------------------------------------
# Durable recovery of the standard notify_order / notify_trade (re-verification G3)
# ---------------------------------------------------------------------------
#
# ``bind_strategy_notification_recovery(strategy, directory, deployment_ref=...)``
# journals a ledger-bound Strategy's standard notifications in the local
# ``backtrader.execution.strategy_notification_outbox`` (one outbox for
# orders, one for trades) and acknowledges each only after the Strategy's
# callback returned:
#
# * an order notification is journaled when this Broker queues it (before
#   Cerebro can deliver it), and only if the Strategy will deliver it (not a
#   simulated order, not a Historical one without ``histnotify``);
# * a trade notification is journaled when Backtrader delivers it, right
#   before ``notify_trade`` runs;
# * an instance-level wrapper on ``notify_order``/``notify_trade``
#   acknowledges the oldest pending entry after a normal return when it is
#   that notification (same order ref and status / trade ref and status). An
#   exception from the callback leaves it pending.
#
# After a restart (same ``directory`` and ``deployment_ref``), pending entries
# are redelivered at bind time, in order, through the same callbacks. Real
# ``Order``/``Trade`` objects of a dead process cannot be rebuilt faithfully
# (data feeds, comminfo, parents and history are gone), so a redelivered
# notification is a read-only ``RecoveredOrder``/``RecoveredTrade`` record
# with the commonly used attributes and ``recovered = True``; a strategy tells
# them apart with ``getattr(order, "recovered", False)``. Delivery is at least
# once: the same ``event_id`` (``order.info["recovery_event_id"]``) can be
# delivered again after a crash between the callback and the ACK.
#
# Limits: a trade produced by Backtrader after a fill but before the process
# crashed (before the Strategy's next notification cycle) is not journaled;
# that fill is recovered through its order notification (executed size,
# price, value, commission). The outbox scans its retained history on each
# operation (see its module docstring): this is not tuned for high-frequency
# order flow.


import hashlib as _hashlib
import json as _json
import math as _math
import uuid as _uuid
from pathlib import Path as _Path
from types import MappingProxyType as _MappingProxyType
from types import SimpleNamespace as _SimpleNamespace

_ORDER_SCHEMA = "backtrader.notify_order.recovery"
_TRADE_SCHEMA = "backtrader.notify_trade.recovery"
_SOURCE_EPOCH = "backtrader.standard_notifications.v1"


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if _math.isfinite(number) else None


def _canonical(value) -> bytes:
    return _json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _data_name(data):
    name = getattr(data, "_name", None)
    return name if type(name) is str and name else "unknown"


def _order_record(order):
    from ..order import Order

    executed = getattr(order, "executed", None)
    info = getattr(order, "info", None)
    get = getattr(info, "get", None)
    return {
        "ref": int(order.ref),
        "status": int(order.status),
        "status_name": Order.Status[order.status],
        "side": "buy" if order.isbuy() else "sell",
        "size": _finite(order.size),
        "price": _finite(order.price),
        "exectype": None if order.exectype is None else int(order.exectype),
        "data_name": _data_name(getattr(order, "data", None)),
        "executed": {
            "size": _finite(getattr(executed, "size", None)),
            "price": _finite(getattr(executed, "price", None)),
            "value": _finite(getattr(executed, "value", None)),
            "comm": _finite(getattr(executed, "comm", None)),
        },
        "strategy_ledger_intent_id": (
            get("strategy_ledger_intent_id") if callable(get) else None
        ),
    }


def _jsonable_id(value):
    """A trade id as JSON (int, or a list for composite ids)."""
    if type(value) is int:
        return value
    if isinstance(value, (tuple, list)):
        return [_jsonable_id(item) for item in value]
    return None if value is None else str(value)


def _trade_record(trade):
    return {
        "ref": int(trade.ref),
        "status": int(trade.status),
        "tradeid": _jsonable_id(getattr(trade, "tradeid", 0)),
        "data_name": _data_name(getattr(trade, "data", None)),
        "size": _finite(trade.size),
        "price": _finite(trade.price),
        "value": _finite(trade.value),
        "commission": _finite(trade.commission),
        "pnl": _finite(trade.pnl),
        "pnlcomm": _finite(trade.pnlcomm),
        "isopen": bool(trade.isopen),
        "isclosed": bool(trade.isclosed),
    }


class RecoveredOrder:
    """Read-only replay of an order notification journaled before a restart.

    Not a live ``Order``: it cannot be cancelled or resubmitted and has no
    data feed. Status constants and ``getstatusname()``/``isbuy()``/
    ``issell()``/``alive()`` match ``Order``.
    """

    recovered = True

    def __init__(self, record, event_id):
        self.ref = record["ref"]
        self.status = record["status"]
        self.size = record["size"]
        self.price = record["price"]
        self.exectype = record["exectype"]
        self.data_name = record["data_name"]
        self._side = record["side"]
        self.executed = _SimpleNamespace(**record["executed"])
        self.info = _MappingProxyType(
            {
                "recovered": True,
                "recovery_event_id": event_id,
                "strategy_ledger_intent_id": record.get("strategy_ledger_intent_id"),
            }
        )

    def getstatusname(self, status=None):
        from ..order import Order

        return Order.Status[self.status if status is None else status]

    def isbuy(self):
        return self._side == "buy"

    def issell(self):
        return self._side == "sell"

    def alive(self):
        return self.status in (
            self.Created,
            self.Submitted,
            self.Accepted,
            self.Partial,
        )


class RecoveredTrade:
    """Read-only replay of a trade notification journaled before a restart."""

    recovered = True

    def __init__(self, record, event_id):
        for name, value in record.items():
            setattr(self, name, value)
        self.event_id = event_id


def _install_constants():
    from ..order import Order
    from ..trade import Trade

    for name in list(Order.Status) + list(Order.ExecTypes):
        setattr(RecoveredOrder, name, getattr(Order, name))
    for name in ("Created", "Open", "Closed"):
        setattr(RecoveredTrade, name, getattr(Trade, name))


class _NotificationRecovery:
    """One Strategy's two outboxes and its callback wrappers."""

    def __init__(self, broker, strategy, orders, trades):
        self.broker = broker
        self.strategy = strategy
        self.orders = orders
        self.trades = trades
        self.revisions = {
            id(orders): orders.checkpoint().revision,
            id(trades): trades.checkpoint().revision,
        }
        self.original_order = strategy.notify_order
        self.original_trade = strategy.notify_trade

    def journal(self, outbox, kind, schema, record, *, order_ref, trade_ref=None):
        from ..execution.strategy_notification_outbox import (
            NotificationSnapshot,
            ProjectionCheckpoint,
        )

        event_id = _uuid.uuid4().hex
        revision = self.revisions[id(outbox)]
        commit = outbox.commit(
            source_id=f"{kind}:{event_id}",
            expected_revision=revision,
            checkpoint=ProjectionCheckpoint(schema, 1, _canonical({"revision": revision + 1})),
            notifications=(
                NotificationSnapshot(
                    event_id,
                    kind,
                    record["data_name"],
                    str(order_ref),
                    None if trade_ref is None else str(trade_ref),
                    schema,
                    1,
                    _canonical(record),
                ),
            ),
        )
        self.revisions[id(outbox)] = commit.revision
        return event_id

    @staticmethod
    def acknowledge_if_head(outbox, *, kind, ref, status):
        pending = outbox.pending()
        if pending is None or pending.kind != kind:
            return False
        record = _json.loads(pending.payload)
        if record.get("ref") != ref or record.get("status") != status:
            return False
        outbox.acknowledge(pending.event_id)
        return True

    def notify_order(self, order, *args, **kwargs):
        result = self.original_order(order, *args, **kwargs)
        if not getattr(order, "recovered", False):
            self.acknowledge_if_head(
                self.orders, kind="order", ref=int(order.ref), status=int(order.status)
            )
        return result

    def notify_trade(self, trade, *args, **kwargs):
        if not getattr(trade, "recovered", False):
            record = _trade_record(trade)
            self.journal(
                self.trades,
                "trade",
                _TRADE_SCHEMA,
                record,
                order_ref=f"trade:{record['ref']}",
                trade_ref=record["ref"],
            )
        result = self.original_trade(trade, *args, **kwargs)
        if not getattr(trade, "recovered", False):
            self.acknowledge_if_head(
                self.trades, kind="trade", ref=int(trade.ref), status=int(trade.status)
            )
        return result

    def redeliver(self):
        """Deliver every journaled, unacknowledged notification once; return the count."""

        delivered = 0
        for outbox, original, factory in (
            (self.orders, self.original_order, RecoveredOrder),
            (self.trades, self.original_trade, RecoveredTrade),
        ):
            while True:
                pending = outbox.pending()
                if pending is None:
                    break
                original(factory(_json.loads(pending.payload), pending.event_id))
                outbox.acknowledge(pending.event_id)  # only after a normal return
                delivered += 1
        return delivered

    def close(self):
        for outbox in (self.orders, self.trades):
            outbox.close()


class StrategyNotificationRecoveryBrokerMixin:
    """Journal and recover a ledger-bound Strategy's standard notifications."""

    _strategy_notification_recovery = None

    def bind_strategy_notification_recovery(self, strategy, directory, *, deployment_ref):
        """Journal ``strategy``'s notify_order/notify_trade durably; redeliver pending ones.

        ``strategy`` must already be bound to this Broker's strategy ledger.
        ``directory`` holds this Strategy's two outbox files; ``deployment_ref``
        names the deployment and must be the same after a restart (a different
        one refuses the existing outbox). Returns how many journaled
        notifications from before were redelivered (as ``RecoveredOrder``/
        ``RecoveredTrade``). A callback exception propagates and leaves that
        notification pending.
        """

        from ..execution.strategy_notification_outbox import (
            NotificationScope,
            StrategyNotificationOutbox,
        )

        ledger = getattr(self, "_direct_strategy_ledger", None)
        strategy_ref = self._bound_strategy_ref(strategy) if ledger is not None else None
        if strategy_ref is None:
            raise ValueError("notification recovery needs a strategy bound to the ledger")
        recoveries = self._strategy_notification_recovery
        if recoveries is None:
            recoveries = self._strategy_notification_recovery = {}
        if id(strategy) in recoveries:
            raise ValueError("this strategy already has notification recovery")
        _install_constants()
        folder = _Path(directory)
        folder.mkdir(parents=True, exist_ok=True)
        stem = _hashlib.sha256(strategy_ref.encode()).hexdigest()[:24]

        def scope(kind):
            return NotificationScope(
                account_ref=ledger.account_ref,
                route_ref=f"direct:{kind}",
                strategy_ref=strategy_ref,
                run_id=deployment_ref,
                source_epoch=_SOURCE_EPOCH,
            )

        orders = StrategyNotificationOutbox(folder / f"{stem}.orders.sqlite3", scope("orders"))
        try:
            trades = StrategyNotificationOutbox(
                folder / f"{stem}.trades.sqlite3", scope("trades")
            )
        except BaseException:
            orders.close()
            raise
        recovery = _NotificationRecovery(self, strategy, orders, trades)
        try:
            delivered = recovery.redeliver()
        except BaseException:
            recovery.close()
            raise
        strategy.notify_order = recovery.notify_order
        strategy.notify_trade = recovery.notify_trade
        recoveries[id(strategy)] = recovery
        return delivered

    def _journal_strategy_notification(self, order) -> None:
        """Journal one queued order notification of a recovery-bound Strategy."""

        recoveries = self._strategy_notification_recovery
        owner = getattr(order, "owner", None)
        recovery = recoveries.get(id(owner)) if recoveries else None
        if recovery is None:
            return
        if getattr(getattr(order, "p", None), "simulated", False):
            return  # never queued for the Strategy
        if order.exectype == order.Historical and not order.histnotify:
            return  # never delivered to notify_order
        try:
            recovery.journal(
                recovery.orders,
                "order",
                _ORDER_SCHEMA,
                _order_record(order),
                order_ref=order.ref,
            )
        except Exception as error:  # fail closed: recovery would have a hole
            _logger.error(
                "strategy notification journal failed; trading disabled (%s)",
                getattr(error, "code", type(error).__name__),
            )
            self._trading_enabled = False

    def close_strategy_notification_recovery(self) -> None:
        for recovery in (self._strategy_notification_recovery or {}).values():
            recovery.close()
        self._strategy_notification_recovery = None
