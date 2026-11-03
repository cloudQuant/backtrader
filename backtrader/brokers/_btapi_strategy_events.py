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
# journals one Strategy's standard notifications in ONE ordered, bounded
# ``StrategyNotificationJournal`` (``backtrader.execution``) and acknowledges
# each only after the Strategy's callback returned:
#
# * an order notification is journaled when this Broker queues it
#   (``notify``), before Cerebro can deliver it, and only if the Strategy will
#   deliver it (not simulated, not Historical without ``histnotify``);
# * a trade notification is journaled when the Strategy creates it from an
#   order's executions (right after ``_addnotification``), before
#   ``notify_trade`` can run; a quick-notify trade is journaled right before
#   its delivery;
# * a late-fee correction (F5) is journaled before the Strategy moves it onto
#   its Trade and calls ``notify_fee_correction``; it is acknowledged when that
#   dispatch returned.
#
# Stable ids. Every journaled notification has a deterministic
# ``notification_id`` derived from the journal generation and neutral
# identities: the order's strategy-ledger intent id (else its SDK client or
# external order id, else a per-process local ref), its status, cumulative
# executed size/price/commission and fee-correction count; a trade id derives
# from the id of the order notification that produced it; a fee correction id
# from the order identity and correction sequence. A provider redelivering the
# same fact after a restart therefore maps to the same id. Delivered objects
# carry ``notification_id`` and ``replayed`` (``True`` when that id was
# journaled before this delivery: a replay after a restart or a duplicate);
# key idempotent side effects by ``notification_id``. Delivery is at least
# once, never exactly once.
#
# Generation. Direct mode binds the journal to the strategy ledger's journal
# generation; any other path passes ``generation=`` explicitly (for a Gateway
# account stream: its journal/service generation). A journal of another
# generation raises ``StrategyNotificationRecoveryError("RESYNC_REQUIRED")``
# and nothing is replayed onto the new generation; ``resync=True`` moves the
# old journal aside (``<file>.resync-<n>``, never deleted) and starts empty.
#
# Rebuilt objects. Real ``Order``/``Trade`` objects of a dead process cannot be
# rebuilt faithfully (data feeds, comminfo, parents, execution bits and history
# are gone): a replay is a read-only ``RecoveredOrder``/``RecoveredTrade`` with
# status, side, size, price, exectype, executed size/price/value/comm, ref,
# ledger intent/provider ids and ``recovered = replayed = True``. Not
# reconstructed: ``data`` (only ``data_name``), ``comminfo``, ``executed.exbits``,
# ``created``, parent/children/OCO links, trade ``history`` and ``barlen``; a
# replayed order cannot be cancelled. A ``RecoveredOrder.ref`` is the dead
# process's ref and may equal a new order's ref: correlate by
# ``notification_id`` or ``info["strategy_ledger_intent_id"]``. Fee
# corrections are replayed to the Strategy's ``notify_fee_correction`` only
# (analyzers and observers restart empty).
#
# Bounds. Append and acknowledge are O(1) SQLite operations; acknowledged rows
# beyond ``retain_acked`` are compacted (see the journal). A crash after an
# order notification was journaled but before its Trade was journaled replays
# the order (with its executions) but no Trade.

import hashlib as _hashlib
import json as _json
import math as _math
import os as _os
import uuid as _uuid
from pathlib import Path as _Path
from types import MappingProxyType as _MappingProxyType
from types import SimpleNamespace as _SimpleNamespace

_PAYLOAD_VERSION = 2
_ROUTE_DIRECT = "direct"
_ROUTE_EXPLICIT = "explicit-generation"


class StrategyNotificationRecoveryError(RuntimeError):
    """Finite, value-free notification-recovery failure (``code``)."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if _math.isfinite(number) else None


def _canonical(value) -> bytes:
    return _json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _stable_id(prefix, *parts) -> str:
    return f"{prefix}-" + _hashlib.sha256(_canonical(list(parts))).hexdigest()[:40]


def _data_name(data):
    name = getattr(data, "_name", None)
    return name if type(name) is str and name else "unknown"


def _info_get(obj, key):
    get = getattr(getattr(obj, "info", None), "get", None)
    if not callable(get):
        return None
    value = get(key)
    return value if type(value) is str and value else None


def _order_identity(order, nonce):
    """The most durable neutral identity of ``order`` (not a credential)."""
    for key in ("strategy_ledger_intent_id", "client_order_id", "external_order_id"):
        value = _info_get(order, key)
        if value is not None:
            return f"{key}:{value}"
    return f"local:{nonce}:{int(order.ref)}"


def _fee_corrections(order):
    get = getattr(getattr(order, "info", None), "get", None)
    corrections = get("fee_corrections") if callable(get) else None
    return tuple(corrections or ())


def _order_record(order, identity):
    from ..order import Order

    executed = getattr(order, "executed", None)
    # A Gateway-rebuilt order (R2-C) keeps journaling under the ref of the
    # process that created it, so a re-applied event yields the same payload.
    original_ref = getattr(getattr(order, "info", None), "get", lambda _key: None)(
        "notification_ref"
    )
    return {
        "v": _PAYLOAD_VERSION,
        "identity": identity,
        "ref": int(order.ref if type(original_ref) is not int else original_ref),
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
        "fee_corrections": len(_fee_corrections(order)),
        "strategy_ledger_intent_id": _info_get(order, "strategy_ledger_intent_id"),
        "client_order_id": _info_get(order, "client_order_id"),
        "external_order_id": _info_get(order, "external_order_id"),
    }


def _jsonable_id(value):
    """A trade id as JSON (int, or a list for composite ids)."""
    if type(value) is int:
        return value
    if isinstance(value, (tuple, list)):
        return [_jsonable_id(item) for item in value]
    return None if value is None else str(value)


def _trade_record(trade, *, commission_delta=0.0):
    commission = _finite(trade.commission)
    pnl = _finite(trade.pnl)
    if commission is not None:
        commission += commission_delta
    return {
        "v": _PAYLOAD_VERSION,
        "ref": int(trade.ref),
        "status": int(trade.status),
        "tradeid": _jsonable_id(getattr(trade, "tradeid", 0)),
        "data_name": _data_name(getattr(trade, "data", None)),
        "size": _finite(trade.size),
        "price": _finite(trade.price),
        "value": _finite(trade.value),
        "commission": commission,
        "pnl": pnl,
        "pnlcomm": (
            _finite(trade.pnlcomm)
            if not commission_delta or pnl is None or commission is None
            else pnl - commission
        ),
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
    replayed = True

    def __init__(self, record, event_id):
        self.notification_id = event_id
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
                "notification_id": event_id,
                "recovery_event_id": event_id,
                "strategy_ledger_intent_id": record.get("strategy_ledger_intent_id"),
                "client_order_id": record.get("client_order_id"),
                "external_order_id": record.get("external_order_id"),
                "fee_corrections_count": record.get("fee_corrections", 0),
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
    replayed = True

    def __init__(self, record, event_id):
        for name, value in record.items():
            if name != "v":
                setattr(self, name, value)
        self.notification_id = event_id
        self.event_id = event_id


def _install_constants():
    from ..order import Order
    from ..trade import Trade

    for name in list(Order.Status) + list(Order.ExecTypes):
        setattr(RecoveredOrder, name, getattr(Order, name))
    for name in ("Created", "Open", "Closed"):
        setattr(RecoveredTrade, name, getattr(Trade, name))


class _NotificationRecovery:
    """One Strategy's journal and its callback wrappers."""

    def __init__(self, broker, strategy, journal, generation):
        self.broker = broker
        self.strategy = strategy
        self.journal = journal
        self.generation = generation
        self.nonce = _uuid.uuid4().hex
        self.state = "ACTIVE"
        self.original_order = strategy.notify_order
        self.original_trade = strategy.notify_trade
        self.original_add = strategy._addnotification
        # Entries below this sequence were journaled by an earlier process;
        # ids of such entries met again are kept for the Gateway projection.
        self.session_floor = journal.stats()["next_seq"]
        self.previous_process_ids = set()

    # -- journal / ack ---------------------------------------------------

    def append(self, event_id, kind, record):
        entry, created = self.journal.append(event_id, kind, _canonical(record))
        if not created and entry.seq < self.session_floor:
            self.previous_process_ids.add(event_id)
        return entry.acked or not created

    def fail(self, error, what):
        self.state = "FAILED"
        _logger.error(
            "strategy notification %s failed; trading disabled (%s)",
            what,
            getattr(error, "code", type(error).__name__),
        )
        self.broker._trading_enabled = False

    def acknowledge(self, event_id):
        try:
            self.journal.acknowledge(event_id)
        except Exception as error:  # fail closed: a duplicate would follow
            self.fail(error, "acknowledgement")

    def journal_order(self, order):
        """Journal one queued order notification; return ``(id, replayed)``."""
        identity = _order_identity(order, self.nonce)
        record = _order_record(order, identity)
        event_id = _stable_id(
            "o",
            self.generation,
            identity,
            record["status"],
            record["executed"]["size"],
            record["executed"]["price"],
            record["executed"]["comm"],
            record["fee_corrections"],
        )
        return event_id, self.append(event_id, "order", record)

    def journal_trade(self, trade, order_id, index):
        record = _trade_record(trade)
        record["order_notification_id"] = order_id
        event_id = _stable_id(
            "t",
            self.generation,
            order_id or f"local:{self.nonce}:{record['ref']}",
            index,
            record["tradeid"],
            record["data_name"],
            record["status"],
            record["size"],
        )
        trade.notification_id = event_id
        trade.replayed = self.append(event_id, "trade", record)
        return event_id

    def journal_fee_corrections(self, order):
        """Journal the corrections the Strategy is about to apply; return ids."""
        corrections = _fee_corrections(order)
        if not corrections:
            return ()
        applied = self.strategy.__dict__.get("_fee_corrections_applied", {}).get(order.ref, 0)
        trade = self.strategy._order_last_trade().get(order.ref)
        identity = _order_identity(order, self.nonce)
        ids = []
        pending_delta = 0.0
        for entry in corrections:
            sequence = entry.get("sequence")
            if type(sequence) is not int or sequence <= applied:
                continue
            delta = float(entry["delta"])
            pending_delta += delta
            record = {
                "v": _PAYLOAD_VERSION,
                "sequence": sequence,
                "delta": entry["delta"],
                "cumulative": entry.get("cumulative"),
                "currency": entry.get("currency"),
                "order": _order_record(order, identity),
                "trade": (
                    None
                    if trade is None
                    else _trade_record(trade, commission_delta=pending_delta)
                ),
            }
            event_id = _stable_id("f", self.generation, identity, sequence, entry.get("cumulative"))
            self.append(event_id, "fee_correction", record)
            ids.append(event_id)
        return tuple(ids)

    # -- wrappers ----------------------------------------------------------

    def addnotification(self, order, quicknotify=False, *args, **kwargs):
        strategy = self.strategy
        try:
            fee_ids = self.journal_fee_corrections(order)
        except Exception as error:
            self.fail(error, "journal")
            fee_ids = ()
        pending = strategy._tradespending
        before = len(pending)
        result = self.original_add(order, quicknotify, *args, **kwargs)
        for event_id in fee_ids:
            self.acknowledge(event_id)
        if strategy._tradespending is pending:
            order_id = getattr(order, "notification_id", None)
            for index, trade in enumerate(pending[before:]):
                try:
                    self.journal_trade(trade, order_id, index)
                except Exception as error:
                    self.fail(error, "journal")
        return result

    def notify_order(self, order, *args, **kwargs):
        result = self.original_order(order, *args, **kwargs)
        event_id = getattr(order, "notification_id", None)
        if event_id is not None and not getattr(order, "recovered", False):
            self.acknowledge(event_id)
        return result

    def notify_trade(self, trade, *args, **kwargs):
        recovered = getattr(trade, "recovered", False)
        if not recovered and getattr(trade, "notification_id", None) is None:
            try:  # a quick-notify trade, delivered inside _addnotification
                self.journal_trade(trade, None, 0)
            except Exception as error:
                self.fail(error, "journal")
        result = self.original_trade(trade, *args, **kwargs)
        event_id = getattr(trade, "notification_id", None)
        if event_id is not None and not recovered:
            self.acknowledge(event_id)
        return result

    # -- replay ------------------------------------------------------------

    def redeliver(self):
        """Deliver every journaled, unacknowledged notification in order."""

        delivered = 0
        while True:
            entries = self.journal.pending()
            if not entries:
                return delivered
            for entry in entries:
                record = _json.loads(entry.payload)
                if entry.kind == "order":
                    self.original_order(RecoveredOrder(record, entry.event_id))
                elif entry.kind == "trade":
                    self.original_trade(RecoveredTrade(record, entry.event_id))
                else:
                    trade = record.get("trade")
                    hook = getattr(self.strategy, "notify_fee_correction", None)
                    if callable(hook):
                        hook(
                            RecoveredOrder(record["order"], entry.event_id),
                            None if trade is None else RecoveredTrade(trade, entry.event_id),
                            float(record["delta"]),
                            record.get("currency"),
                        )
                self.journal.acknowledge(entry.event_id)  # only after a normal return
                delivered += 1

    def restore(self):
        strategy = self.strategy
        for name in ("notify_order", "notify_trade", "_addnotification"):
            strategy.__dict__.pop(name, None)

    def close(self):
        self.journal.close()


def _move_aside(path):
    """Rename a journal of another generation (and its WAL files); never delete."""
    for index in range(1, 10000):
        target = path.with_name(f"{path.name}.resync-{index}")
        if not _os.path.lexists(target):
            break
    else:  # pragma: no cover - 10k resyncs of one strategy
        raise StrategyNotificationRecoveryError("RESYNC_TARGET_UNAVAILABLE")
    for suffix in ("-wal", "-shm"):
        side = path.with_name(path.name + suffix)
        if _os.path.lexists(side):
            _os.replace(side, target.with_name(target.name + suffix))
    _os.replace(path, target)
    return target


class StrategyNotificationRecoveryBrokerMixin:
    """Journal and recover a Strategy's standard notifications."""

    _strategy_notification_recovery = None
    _strategy_notification_recovery_states = None

    def bind_strategy_notification_recovery(
        self,
        strategy,
        directory,
        *,
        deployment_ref,
        generation=None,
        resync=False,
        retain_acked=1024,
    ):
        """Journal ``strategy``'s notify_order/notify_trade durably; redeliver pending ones.

        ``strategy`` is bound to this Broker's strategy ledger (direct mode; the
        journal generation is the ledger's), or ``generation`` names the
        upstream journal generation explicitly (for example a Gateway account
        stream) and ``strategy.p.strategy_ref``/``account_ref`` name the scope.
        ``directory`` holds this Strategy's journal; ``deployment_ref`` names
        the deployment and must be the same after a restart. Returns how many
        journaled notifications from before were redelivered (as
        ``RecoveredOrder``/``RecoveredTrade`` or ``notify_fee_correction``). A
        callback exception propagates and leaves that notification pending.
        A journal of another generation raises ``RESYNC_REQUIRED`` unless
        ``resync=True`` (the old journal is moved aside, not replayed).
        """

        from ..execution.strategy_notification_outbox import (
            NotificationOutboxError,
            NotificationScope,
            StrategyNotificationJournal,
        )

        ledger = getattr(self, "_direct_strategy_ledger", None)
        strategy_ref = self._bound_strategy_ref(strategy) if ledger is not None else None
        if strategy_ref is not None:
            ledger_generation = ledger.read_events(strategy_ref, limit=1).generation
            if generation is not None and generation != ledger_generation:
                raise ValueError("generation differs from the strategy ledger's generation")
            generation, account_ref, route = ledger_generation, ledger.account_ref, _ROUTE_DIRECT
        elif generation is None:
            raise ValueError(
                "notification recovery needs a strategy bound to the ledger or an explicit "
                "generation"
            )
        else:
            params = getattr(strategy, "p", None)
            strategy_ref = getattr(params, "strategy_ref", None)
            account_ref = getattr(params, "account_ref", None)
            route = _ROUTE_EXPLICIT
            if not all(type(v) is str and v for v in (strategy_ref, account_ref, generation)):
                raise ValueError("explicit generation needs strategy_ref and account_ref params")
        recoveries = self._strategy_notification_recovery
        if recoveries is None:
            recoveries = self._strategy_notification_recovery = {}
        states = self._strategy_notification_recovery_states
        if states is None:
            states = self._strategy_notification_recovery_states = {}
        if id(strategy) in recoveries:
            raise ValueError("this strategy already has notification recovery")
        _install_constants()
        folder = _Path(directory)
        folder.mkdir(parents=True, exist_ok=True)
        stem = _hashlib.sha256(f"{account_ref}\0{strategy_ref}".encode()).hexdigest()[:24]
        path = folder / f"{stem}.notifications.sqlite3"
        scope = NotificationScope(
            account_ref=account_ref,
            route_ref=route,
            strategy_ref=strategy_ref,
            run_id=deployment_ref,
            source_epoch=generation,
        )
        try:
            journal = StrategyNotificationJournal(path, scope, retain_acked=retain_acked)
        except NotificationOutboxError as error:
            if error.code != "RESYNC_REQUIRED":
                states[id(strategy)] = "FAILED"
                raise StrategyNotificationRecoveryError(error.code) from None
            if not resync:
                states[id(strategy)] = "RESYNC_REQUIRED"
                raise StrategyNotificationRecoveryError("RESYNC_REQUIRED") from None
            _move_aside(path)
            try:
                journal = StrategyNotificationJournal(path, scope, retain_acked=retain_acked)
            except NotificationOutboxError as again:
                states[id(strategy)] = "FAILED"
                raise StrategyNotificationRecoveryError(again.code) from None
        recovery = _NotificationRecovery(self, strategy, journal, generation)
        try:
            delivered = recovery.redeliver()
        except BaseException:
            recovery.close()
            raise
        strategy.notify_order = recovery.notify_order
        strategy.notify_trade = recovery.notify_trade
        strategy._addnotification = recovery.addnotification
        recoveries[id(strategy)] = recovery
        states[id(strategy)] = "ACTIVE"
        return delivered

    def strategy_notification_recovery_state(self, strategy):
        """``ACTIVE``, ``RESYNC_REQUIRED``, ``FAILED`` or ``None`` (not bound)."""
        recovery = (self._strategy_notification_recovery or {}).get(id(strategy))
        if recovery is not None:
            return recovery.state
        return (self._strategy_notification_recovery_states or {}).get(id(strategy))

    def _journal_strategy_notification(self, order):
        """Journal one queued order notification; return ``(id, replayed)`` or ``None``."""

        recoveries = self._strategy_notification_recovery
        owner = getattr(order, "owner", None)
        recovery = recoveries.get(id(owner)) if recoveries else None
        if recovery is None:
            return None
        if getattr(getattr(order, "p", None), "simulated", False):
            return None  # never queued for the Strategy
        if order.exectype == order.Historical and not order.histnotify:
            return None  # never delivered to notify_order
        try:
            return recovery.journal_order(order)
        except Exception as error:  # fail closed: recovery would have a hole
            recovery.fail(error, "journal")
            return None

    def close_strategy_notification_recovery(self) -> None:
        for recovery in (self._strategy_notification_recovery or {}).values():
            recovery.restore()
            recovery.close()
        self._strategy_notification_recovery = None
