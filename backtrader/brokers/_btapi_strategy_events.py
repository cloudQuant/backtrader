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
#
# Late fee corrections across a restart (iteration 60, post-acceptance). The
# journal also keeps an applied-fill index (schema v3): with each order
# notification it stores, in the same transaction, the order's state and
# provider fee totals and the fills applied to it (stable fill fact -> booked
# fee, only for fills identified by a provider or client order id), plus the
# fee corrections the Broker booked since the last notification (journaled at
# the Broker, before Cerebro hands the order to the Strategy). The Strategy
# side stores the Trade each order last updated. When a fill an *earlier
# process* applied is reported again with a higher fee and no live order can
# take it (a terminal order, or any order in direct mode after a restart),
# ``_apply_durable_fill_fee`` books it exactly once: the strategy ledger's
# per-(intent, currency) fee total moves to the corrected total (compared with
# ``SqliteStrategyLedger.execution_totals`` first, so a re-delivery is a no-op
# and a divergence fails closed), then one transaction journals the correction
# and the corrected order notification and updates the index. The Strategy
# receives ``notify_fee_correction(order, trade, delta, currency)`` with a
# read-only ``RecoveredOrder`` (original ref and intent id, last status,
# executed size/price, corrected commission; ``replayed=False``) and a
# ``RecoveredTrade`` of the Trade that order last updated (commission and
# ``pnlcomm`` corrected), or ``None`` when no Trade was recorded for it, then
# ``notify_order`` with the same order snapshot. Both are acknowledged after
# the callback returned and replayed after a crash. Only the Strategy is
# called: analyzers and observers restarted empty, never counted the earlier
# process's Trades, and Trade refs restart per process. The same correction
# re-delivered is ignored; a lower fee, another currency or a fill booked
# without a fee disables trading and freezes openings (``fee_correction_fence``)
# as in the live path.

import hashlib as _hashlib
import json as _json
import math as _math
import os as _os
import uuid as _uuid
from decimal import Decimal as _Decimal
from pathlib import Path as _Path
from types import MappingProxyType as _MappingProxyType
from types import SimpleNamespace as _SimpleNamespace

_PAYLOAD_VERSION = 2
_INDEX_VERSION = 1
_ROUTE_DIRECT = "direct"
_ROUTE_EXPLICIT = "explicit-generation"
_MAX_CACHE = 8192


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


def _info_int(obj, key):
    get = getattr(getattr(obj, "info", None), "get", None)
    value = get(key) if callable(get) else None
    return value if type(value) is int and value > 0 else 0


def _durable(identity):
    """Whether an order identity survives a restart (not a per-process ref)."""
    return not identity.startswith("local:")


def fill_index_key(trade_key):
    """The applied-fill index key of a Broker fill dedupe key (order id, data, fill id)."""
    return _canonical([str(part) for part in trade_key]).decode()


def _text_decimal(value):
    return None if value is None else str(_Decimal(str(value)))


def _order_index_record(order, record):
    """The durable state of ``order`` kept with its journaled notification ``record``."""
    get = getattr(getattr(order, "info", None), "get", None)
    totals = (get("provider_fee_totals") if callable(get) else None) or {}
    return {
        "v": _INDEX_VERSION,
        "order": record,
        "fee_totals": {str(currency): str(total) for currency, total in totals.items()},
    }


def _fill_index_record(trade_key, quantity, price, fee, currency):
    return {
        "v": _INDEX_VERSION,
        "data_name": str(trade_key[1]),
        "quantity": _text_decimal(quantity),
        "price": _text_decimal(price),
        "fee": _text_decimal(fee),
        "currency": currency if type(currency) is str and currency else None,
    }


class JournaledOrderNotification:
    """What journaling one order notification produced (``BtApiBroker.notify``)."""

    __slots__ = ("event_id", "replayed", "fee_ids", "fee_created")

    def __init__(self, event_id, replayed, fee_ids=(), fee_created=False):
        self.event_id = event_id
        self.replayed = replayed
        self.fee_ids = tuple(fee_ids)
        self.fee_created = fee_created


class DurableFeeCorrectionDelivery:
    """Journaled notifications of a fee correction booked without a live order.

    Queued on the Broker like an order notification (``owner`` is the
    Strategy) so Cerebro hands it over at the usual point; the notification
    recovery wrapper of ``Strategy._addnotification`` delivers each entry and
    acknowledges it after the callback returned.
    """

    def __init__(self, owner, entries):
        self.owner = owner
        self.entries = tuple(entries)


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
    ``issell()``/``alive()`` match ``Order``. ``replayed`` is ``False`` for
    the first delivery of a fee correction booked after a restart (the order
    is rebuilt from the journal, the notification itself is new).
    """

    recovered = True
    replayed = True

    def __init__(self, record, event_id, *, replayed=True):
        if replayed is not True:
            self.replayed = False
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

    def __init__(self, record, event_id, *, replayed=True):
        for name, value in record.items():
            if name != "v":
                setattr(self, name, value)
        if replayed is not True:
            self.replayed = False
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
        # Applied-fill index writes already made by this process (skip repeats).
        self.trade_cache = {}
        self.link_cache = {}

    # -- journal / ack ---------------------------------------------------

    def append(self, event_id, kind, record):
        entry, created = self.journal.append(event_id, kind, _canonical(record))
        if not created and entry.seq < self.session_floor:
            self.previous_process_ids.add(event_id)
        return entry.acked or not created

    def append_many(self, entries, index=None):
        """Append ``(event_id, kind, payload[, keep_existing])`` in one transaction."""
        results = self.journal.append_many(tuple(entries), index=index)
        for entry, created in results:
            if not created and entry.seq < self.session_floor:
                self.previous_process_ids.add(entry.event_id)
        return results

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

    @staticmethod
    def order_event_id(generation, identity, record):
        return _stable_id(
            "o",
            generation,
            identity,
            record["status"],
            record["executed"]["size"],
            record["executed"]["price"],
            record["executed"]["comm"],
            record["fee_corrections"],
        )

    def journal_order(self, order):
        """Journal one queued order notification; return ``(id, replayed)``."""
        journaled = self.journal_order_notification(order)
        return journaled.event_id, journaled.replayed

    def _last_trades(self):
        last = getattr(self.strategy, "_order_last_trade", None)
        return last() if callable(last) else {}

    def journal_order_notification(self, order, fills=None):
        """Journal one order notification with its new fee corrections and index state.

        One transaction: the fee corrections the Broker booked on ``order``
        since its last journaled notification (each before the notification,
        in sequence order), the order notification, and the applied-fill
        index (the order's state and fee totals, ``fills``: ``{trade_key:
        (quantity, price, fee, currency)}`` applied or corrected since).
        """
        identity = _order_identity(order, self.nonce)
        record = _order_record(order, identity)
        event_id = self.order_event_id(self.generation, identity, record)
        entries = []
        corrections = _fee_corrections(order)
        journaled = _info_int(order, "fee_corrections_journaled")
        last = journaled
        if corrections:
            applied = self.strategy.__dict__.get("_fee_corrections_applied", {}).get(order.ref, 0)
            trade = self._last_trades().get(order.ref)
            pending_delta = 0.0
            for entry in corrections:
                sequence = entry.get("sequence")
                if type(sequence) is not int or sequence <= applied:
                    continue
                pending_delta += float(entry["delta"])
                if sequence <= journaled:
                    continue
                entries.append(
                    self._fee_entry(identity, record, entry, trade, pending_delta)
                )
                last = max(last, sequence)
        entries.append((event_id, "order", _canonical(record)))
        index = None
        if _durable(identity) and (fills or record["executed"]["size"]):
            index = self._order_index(order, identity, record, fills or {})
        results = self.append_many(entries, index=index)
        if last > journaled:
            order.addinfo(fee_corrections_journaled=last)
        entry, created = results[-1]
        return JournaledOrderNotification(
            event_id,
            entry.acked or not created,
            [item[0] for item in entries[:-1]],
            any(created for _entry, created in results[:-1]),
        )

    def _fee_entry(self, identity, record, entry, trade, pending_delta):
        payload = {
            "v": _PAYLOAD_VERSION,
            "sequence": entry["sequence"],
            "delta": entry["delta"],
            "cumulative": entry.get("cumulative"),
            "currency": entry.get("currency"),
            "order": record,
            "trade": (
                None if trade is None else _trade_record(trade, commission_delta=pending_delta)
            ),
        }
        event_id = _stable_id(
            "f", self.generation, identity, entry["sequence"], entry.get("cumulative")
        )
        # The id identifies the correction; a re-application keeps the first snapshot.
        return event_id, "fee_correction", _canonical(payload), True

    def index_order_fills(self, order, fills):
        """Index ``fills`` with ``order``'s current (just journaled) state, no notification."""
        identity = _order_identity(order, self.nonce)
        if _durable(identity):
            record = _order_record(order, identity)
            self.journal.update_index(self._order_index(order, identity, record, fills))

    def _order_index(self, order, identity, record, fills):
        from ..execution.strategy_notification_outbox import JournalIndexUpdate

        return JournalIndexUpdate(
            orders=((identity, _canonical(_order_index_record(order, record))),),
            fills=tuple(
                (
                    fill_index_key(trade_key),
                    identity,
                    _canonical(_fill_index_record(trade_key, *values)),
                )
                for trade_key, values in fills.items()
            ),
        )

    def _trade_entry(self, trade, order_id, index):
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
        return event_id, "trade", _canonical(record)

    def journal_trade(self, trade, order_id, index):
        event_id, kind, payload = self._trade_entry(trade, order_id, index)
        ((entry, created),) = self.append_many(((event_id, kind, payload),))
        trade.notification_id = event_id
        trade.replayed = entry.acked or not created
        return event_id

    def _trade_index(self, order):
        """Index update linking ``order`` to the Trade it last updated (if it changed)."""
        trade = self._last_trades().get(getattr(order, "ref", None))
        if trade is None:
            return None, None
        identity = _order_identity(order, self.nonce)
        if not _durable(identity):
            return None, None
        from ..execution.strategy_notification_outbox import JournalIndexUpdate

        trade_key = f"{self.nonce}:{int(trade.ref)}"
        record = _canonical(_trade_record(trade))
        if self.trade_cache.get(trade_key) == record and self.link_cache.get(identity) == trade_key:
            return None, None
        update = JournalIndexUpdate(links=((identity, trade_key),), trades=((trade_key, record),))
        return update, (identity, trade_key, record)

    def remember_trade_index(self, cached):
        identity, trade_key, record = cached
        for cache in (self.trade_cache, self.link_cache):
            if len(cache) >= _MAX_CACHE:
                cache.clear()
        self.trade_cache[trade_key] = record
        self.link_cache[identity] = trade_key

    def journal_fee_corrections(self, order):
        """Journal corrections the Broker did not journal yet; return their ids."""
        corrections = _fee_corrections(order)
        if not corrections:
            return ()
        applied = self.strategy.__dict__.get("_fee_corrections_applied", {}).get(order.ref, 0)
        journaled = _info_int(order, "fee_corrections_journaled")
        trade = self._last_trades().get(order.ref)
        identity = _order_identity(order, self.nonce)
        record = _order_record(order, identity)
        entries = []
        pending_delta = 0.0
        for entry in corrections:
            sequence = entry.get("sequence")
            if type(sequence) is not int or sequence <= applied:
                continue
            pending_delta += float(entry["delta"])
            if sequence <= journaled:
                continue
            entries.append(self._fee_entry(identity, record, entry, trade, pending_delta))
        if entries:
            self.append_many(entries)
        return tuple(item[0] for item in entries)

    # -- wrappers ----------------------------------------------------------

    def addnotification(self, order, quicknotify=False, *args, **kwargs):
        if type(order) is DurableFeeCorrectionDelivery:
            return self.deliver_durable(order)
        strategy = self.strategy
        fee_ids = tuple(getattr(order, "fee_correction_ids", ()) or ())
        try:
            fee_ids += self.journal_fee_corrections(order)
        except Exception as error:
            self.fail(error, "journal")
        pending = strategy._tradespending
        before = len(pending)
        result = self.original_add(order, quicknotify, *args, **kwargs)
        for event_id in fee_ids:
            self.acknowledge(event_id)
        trades = pending[before:] if strategy._tradespending is pending else []
        try:
            index, cached = self._trade_index(order)
        except Exception as error:
            self.fail(error, "journal")
            index = cached = None
        if not trades and index is None:
            return result
        order_id = getattr(order, "notification_id", None)
        entries = [self._trade_entry(trade, order_id, i) for i, trade in enumerate(trades)]
        try:
            results = self.append_many(entries, index=index)
        except Exception as error:
            self.fail(error, "journal")
            return result
        for trade, (event_id, _kind, _payload), (entry, created) in zip(trades, entries, results):
            trade.notification_id = event_id
            trade.replayed = entry.acked or not created
        if cached is not None:
            self.remember_trade_index(cached)
        return result

    def deliver_durable(self, delivery):
        """Deliver a fee correction booked without a live order (ACK after each callback)."""
        for event_id, kind, record in delivery.entries:
            if kind == "fee_correction":
                hook = getattr(self.strategy, "notify_fee_correction", None)
                if callable(hook):
                    trade = record.get("trade")
                    hook(
                        RecoveredOrder(record["order"], event_id, replayed=False),
                        None if trade is None else RecoveredTrade(trade, event_id, replayed=False),
                        float(record["delta"]),
                        record.get("currency"),
                    )
            else:
                self.original_order(RecoveredOrder(record, event_id, replayed=False))
            self.acknowledge(event_id)

    # -- late fee of a fill an earlier process applied -------------------------

    def durable_fill(self, fill_key):
        """``(order_key, fill record)`` from the applied-fill index, or ``None``."""
        found = self.journal.indexed_fill(fill_key)
        if found is None:
            return None
        order_key, record = found
        return order_key, _json.loads(record)

    def book_durable_correction(self, fill_key, order_key, fill, reported, currency, ledger):
        """Book one late fee of an indexed fill; return the delivery or a fence reason.

        ``reported`` is the corrected fee of the fill in ``currency`` (higher
        than the booked fee, same currency: checked by the caller). Ledger
        first, as ``BtApiBroker.notify`` does for a live order: the intent's
        fee total in ``currency`` moves to the corrected total unless it is
        already there; any other ledger total is a divergence (fail closed).
        Then one journal transaction stores the correction, the corrected
        order notification and the index update.
        """
        from ..execution.strategy_notification_outbox import JournalIndexUpdate

        order_bytes, trade_key, trade_bytes = self.journal.indexed_order(order_key)
        if order_bytes is None:
            return "fill_order_state_unavailable"
        state = _json.loads(order_bytes)
        record = dict(state["order"])
        record["executed"] = dict(record["executed"])
        totals = {name: _Decimal(total) for name, total in state.get("fee_totals", {}).items()}
        unattributed = {
            name: _Decimal(total) for name, total in state.get("unattributed_fees", {}).items()
        }
        delta = reported - _Decimal(fill["fee"])
        # A correction reconciled from the ledger at startup (the earlier process
        # booked it but crashed before journaling, see reconcile_ledger_fees) is
        # already in ``totals`` and was already notified: consume it first.
        consumed = min(unattributed.get(currency, _Decimal("0")), delta)
        if consumed:
            unattributed[currency] = unattributed[currency] - consumed
            delta -= consumed
        if not delta:
            from ..execution.strategy_notification_outbox import JournalIndexUpdate

            self.journal.update_index(
                JournalIndexUpdate(
                    orders=(
                        (
                            order_key,
                            _canonical(
                                {
                                    **{k: v for k, v in state.items() if k != "pending_ledger_fees"},
                                    "unattributed_fees": {
                                        name: str(value)
                                        for name, value in unattributed.items()
                                        if value
                                    },
                                }
                            ),
                        ),
                    ),
                    fills=(
                        (fill_key, order_key, _canonical(dict(fill, fee=str(reported)))),
                    ),
                )
            )
            return DurableFeeCorrectionDelivery(self.strategy, ())
        before = totals.get(currency, _Decimal("0"))
        target = before + delta
        intent_id = record.get("strategy_ledger_intent_id")
        if ledger is not None and intent_id is not None:
            try:
                filled, fees = ledger.execution_totals(intent_id)
                current = fees.get(currency, _Decimal("0"))
                if current == before:
                    self.write_ledger_fee_intent(order_key, {**totals, currency: target})
                    ledger.apply_execution(
                        intent_id, cumulative_quantity=filled, fee=target, fee_currency=currency
                    )
                elif current != target:
                    return "ledger_fee_diverged"
            except Exception as error:
                _logger.error(
                    "strategy ledger fee correction failed (%s)",
                    getattr(error, "code", type(error).__name__),
                )
                return "ledger_fee_unavailable"
        totals[currency] = target
        comm = record["executed"].get("comm") or 0.0
        record["executed"]["comm"] = float(_Decimal(str(comm)) + delta)
        sequence = int(record.get("fee_corrections") or 0) + 1
        record["fee_corrections"] = sequence
        trade = None if trade_bytes is None else dict(_json.loads(trade_bytes))
        if trade is not None:
            trade.pop("order_notification_id", None)
            if trade.get("commission") is not None:
                trade["commission"] = float(_Decimal(str(trade["commission"])) + delta)
                if trade.get("pnl") is not None:
                    trade["pnlcomm"] = trade["pnl"] - trade["commission"]
        correction = {
            "v": _PAYLOAD_VERSION,
            "sequence": sequence,
            "delta": str(delta),
            "cumulative": str(reported),
            "currency": currency,
            "order": record,
            "trade": trade,
        }
        identity = record["identity"]
        fee_id = _stable_id("f", self.generation, identity, sequence, str(reported))
        order_id = self.order_event_id(self.generation, identity, record)
        corrected_fill = dict(fill, fee=str(reported), currency=currency)
        index = JournalIndexUpdate(
            orders=(
                (
                    order_key,
                    _canonical(
                        {
                            "v": _INDEX_VERSION,
                            "order": record,
                            "fee_totals": {name: str(v) for name, v in totals.items()},
                            **(
                                {
                                    "unattributed_fees": {
                                        name: str(value)
                                        for name, value in unattributed.items()
                                        if value
                                    }
                                }
                                if any(unattributed.values())
                                else {}
                            ),
                        }
                    ),
                ),
            ),
            fills=((fill_key, order_key, _canonical(corrected_fill)),),
            trades=() if trade is None else ((trade_key, _canonical(trade)),),
        )
        results = self.append_many(
            (
                (fee_id, "fee_correction", _canonical(correction), True),
                (order_id, "order", _canonical(record)),
            ),
            index=index,
        )
        entries = [
            (event_id, kind, payload)
            for (event_id, kind, payload), (_entry, created) in zip(
                ((fee_id, "fee_correction", correction), (order_id, "order", record)), results
            )
            if created
        ]
        return DurableFeeCorrectionDelivery(self.strategy, entries)

    def write_ledger_fee_intent(self, order_key, targets):
        """Write-ahead before a fee correction moves the strategy ledger.

        ``targets`` (``{currency: corrected total}``) are provider facts the
        Broker is about to book. Stored in the order's index state; the
        journal write that follows rewrites that state without them. A crash
        in between leaves them for :meth:`reconcile_ledger_fees`.
        """
        from ..execution.strategy_notification_outbox import JournalIndexUpdate

        order_bytes, _trade_key, _trade_bytes = self.journal.indexed_order(order_key)
        if order_bytes is None:
            return False
        state = _json.loads(order_bytes)
        state["pending_ledger_fees"] = {str(c): str(_Decimal(str(v))) for c, v in targets.items()}
        self.journal.update_index(
            JournalIndexUpdate(orders=((order_key, _canonical(state)),))
        )
        return True

    def reconcile_ledger_fees(self, ledger):
        """Startup: close the crash window between a fee's ledger write and its journal.

        Every fee correction first records its target totals in the order's
        index state (:meth:`write_ledger_fee_intent`), then books the ledger,
        then journals. For each indexed order whose ledger fill quantity equals
        the journaled executed size, per currency with ledger fee ``L``,
        journaled fee ``J`` and write-ahead target ``P``:

        * ``L == J`` and ``P > J``: the crash came before the ledger write; the
          ledger is moved to ``P`` (once: compared first) and the correction
          journaled and notified;
        * ``L == P > J``: the crash came after the ledger write; the correction
          ``L - J`` is journaled and notified;
        * ``L != J`` otherwise (no write-ahead, or another value): not this
          window - fail closed (``ledger_fee_diverged``), nothing is invented.

        A correction reconciled here is kept as ``unattributed_fees`` so a
        later per-fill re-report of it is neither booked nor notified twice.
        Returns ``(deliveries, fence reasons)``.
        """
        from ..execution.strategy_notification_outbox import JournalIndexUpdate

        deliveries, fences = [], []
        for order_key in self.journal.indexed_order_keys():
            order_bytes, trade_key, trade_bytes = self.journal.indexed_order(order_key)
            if order_bytes is None:
                continue
            state = _json.loads(order_bytes)
            pending = {
                name: _Decimal(total)
                for name, total in (state.get("pending_ledger_fees") or {}).items()
            }
            record = dict(state["order"])
            record["executed"] = dict(record["executed"])
            intent_id = record.get("strategy_ledger_intent_id")
            if type(intent_id) is not str or not intent_id:
                continue
            try:
                filled, fees = ledger.execution_totals(intent_id)
            except Exception as error:
                if getattr(error, "code", None) == "INTENT_NOT_FOUND":
                    continue
                return [], ["ledger_fee_unavailable"]
            executed = abs(_Decimal(str(record["executed"].get("size") or 0)))
            if _Decimal(filled) != executed:
                # A fill the journal never saw: outside this window (see the
                # module notes); fees of this order are not reconciled here.
                continue
            totals = {
                name: _Decimal(total) for name, total in state.get("fee_totals", {}).items()
            }
            unattributed = {
                name: _Decimal(total)
                for name, total in state.get("unattributed_fees", {}).items()
            }
            trade = None if trade_bytes is None else dict(_json.loads(trade_bytes))
            if trade is not None:
                trade.pop("order_notification_id", None)
            entries = []
            diverged = False
            for currency in sorted(set(fees) | set(totals) | set(pending)):
                ledger_fee = _Decimal(fees.get(currency, 0))
                journal_fee = totals.get(currency, _Decimal("0"))
                target = pending.get(currency)
                if ledger_fee == journal_fee:
                    if target is None or target <= journal_fee:
                        continue
                    try:  # crashed before the ledger write: book the recorded fact
                        ledger.apply_execution(
                            intent_id,
                            cumulative_quantity=filled,
                            fee=target,
                            fee_currency=currency,
                        )
                    except Exception as error:
                        _logger.error(
                            "strategy ledger fee reconciliation failed (%s)",
                            getattr(error, "code", type(error).__name__),
                        )
                        return [], ["ledger_fee_unavailable"]
                    ledger_fee = target
                elif target is None or ledger_fee != target or ledger_fee < journal_fee:
                    diverged = True
                    break
                delta = ledger_fee - journal_fee
                totals[currency] = ledger_fee
                unattributed[currency] = unattributed.get(currency, _Decimal("0")) + delta
                comm = record["executed"].get("comm") or 0.0
                record["executed"]["comm"] = float(_Decimal(str(comm)) + delta)
                sequence = int(record.get("fee_corrections") or 0) + 1
                record["fee_corrections"] = sequence
                if trade is not None and trade.get("commission") is not None:
                    trade["commission"] = float(_Decimal(str(trade["commission"])) + delta)
                    if trade.get("pnl") is not None:
                        trade["pnlcomm"] = trade["pnl"] - trade["commission"]
                correction = {
                    "v": _PAYLOAD_VERSION,
                    "sequence": sequence,
                    "delta": str(delta),
                    "cumulative": str(ledger_fee),
                    "currency": currency,
                    "order": dict(record, executed=dict(record["executed"])),
                    "trade": None if trade is None else dict(trade),
                }
                fee_id = _stable_id(
                    "f", self.generation, record["identity"], sequence, "ledger:" + str(ledger_fee)
                )
                entries.append((fee_id, "fee_correction", correction))
            if diverged:
                fences.append("ledger_fee_diverged")
                continue
            if not entries and not pending:
                continue
            order_state = {
                "v": _INDEX_VERSION,
                "order": record,
                "fee_totals": {n: str(v) for n, v in totals.items()},
            }
            if any(unattributed.values()):
                order_state["unattributed_fees"] = {
                    n: str(v) for n, v in unattributed.items() if v
                }
            index = JournalIndexUpdate(
                orders=((order_key, _canonical(order_state)),),
                trades=() if trade is None or not entries else ((trade_key, _canonical(trade)),),
            )
            if not entries:  # a write-ahead that was booked and journaled already
                self.journal.update_index(index)
                continue
            order_id = self.order_event_id(self.generation, record["identity"], record)
            entries.append((order_id, "order", record))
            results = self.append_many(
                [
                    (event_id, kind, _canonical(payload), True)
                    if kind == "fee_correction"
                    else (event_id, kind, _canonical(payload))
                    for event_id, kind, payload in entries
                ],
                index=index,
            )
            created = [item for item, (_e, made) in zip(entries, results) if made]
            if created:
                deliveries.append(DurableFeeCorrectionDelivery(self.strategy, created))
        return deliveries, fences

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
        retain_fee_orders=10_000,
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
        ``retain_fee_orders`` bounds the applied-fill index (the most recently
        updated orders whose late fee corrections are still recognised after
        a restart).
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
            journal = StrategyNotificationJournal(
                path, scope, retain_acked=retain_acked, retain_orders=retain_fee_orders
            )
        except NotificationOutboxError as error:
            if error.code != "RESYNC_REQUIRED":
                states[id(strategy)] = "FAILED"
                raise StrategyNotificationRecoveryError(error.code) from None
            if not resync:
                states[id(strategy)] = "RESYNC_REQUIRED"
                raise StrategyNotificationRecoveryError("RESYNC_REQUIRED") from None
            _move_aside(path)
            try:
                journal = StrategyNotificationJournal(
                    path, scope, retain_acked=retain_acked, retain_orders=retain_fee_orders
                )
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
        if route == _ROUTE_DIRECT:
            # Close the "ledger booked, journal not written" crash window of a
            # live fee correction (iteration 60, post-acceptance follow-up).
            try:
                deliveries, fences = recovery.reconcile_ledger_fees(ledger)
            except Exception as error:  # fail closed: the index cannot be trusted
                recovery.fail(error, "index")
                deliveries, fences = [], ["applied_fill_index_unavailable"]
            for delivery in deliveries:
                self.notifs.append(delivery)
            if fences:
                self._fence_durable_fee(fences[0])
        return delivered

    def strategy_notification_recovery_state(self, strategy):
        """``ACTIVE``, ``RESYNC_REQUIRED``, ``FAILED`` or ``None`` (not bound)."""
        recovery = (self._strategy_notification_recovery or {}).get(id(strategy))
        if recovery is not None:
            return recovery.state
        return (self._strategy_notification_recovery_states or {}).get(id(strategy))

    def _journal_strategy_notification(self, order):
        """Journal one queued order notification; ``JournaledOrderNotification`` or ``None``."""

        stash = self.__dict__.get("_durable_fill_rows")
        fills = stash.pop(getattr(order, "ref", None), None) if stash else None
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
            return recovery.journal_order_notification(order, fills)
        except Exception as error:  # fail closed: recovery would have a hole
            recovery.fail(error, "journal")
            return None

    def _stash_durable_fill(self, trade_key, order, quantity, price, fee, currency, update):
        """Keep one applied (or fee-corrected) fill for the order's next journaled notification.

        Only fills identified by a provider or client order id are indexed: a
        per-process order ref does not identify the fill after a restart.
        """
        if not self._strategy_notification_recovery or not trade_key:
            return
        if not (self._remote_external_order_id(update) or self._remote_client_order_id(update)):
            return
        rows = self.__dict__.setdefault("_durable_fill_rows", {})
        rows.setdefault(order.ref, {})[trade_key] = (quantity, price, fee, currency)

    def _flush_durable_fills(self, order):
        """Index stashed fills of ``order`` now (its notification was journaled before)."""
        stash = self.__dict__.get("_durable_fill_rows")
        fills = stash.pop(getattr(order, "ref", None), None) if stash else None
        recoveries = self._strategy_notification_recovery
        recovery = recoveries.get(id(getattr(order, "owner", None))) if recoveries else None
        if not fills or recovery is None:
            return
        try:
            recovery.index_order_fills(order, fills)
        except Exception as error:  # fail closed: a later correction would be missed
            recovery.fail(error, "index")

    def _mark_fee_corrections_delivered(self, order):
        """An earlier process delivered (or replayed) ``order``'s corrections."""
        sequences = [
            entry.get("sequence")
            for entry in _fee_corrections(order)
            if type(entry.get("sequence")) is int
        ]
        owner = getattr(order, "owner", None)
        if sequences and owner is not None:
            applied = owner.__dict__.setdefault("_fee_corrections_applied", {})
            applied[order.ref] = max(applied.get(order.ref, 0), max(sequences))

    def _journal_ledger_fee_intent(self, order):
        """Before ``_sync_direct_ledger`` books an unjournaled fee correction."""
        recoveries = self._strategy_notification_recovery
        if not recoveries or getattr(self, "_direct_strategy_ledger", None) is None:
            return
        recovery = recoveries.get(id(getattr(order, "owner", None)))
        if recovery is None or recovery.state != "ACTIVE":
            return
        journaled = _info_int(order, "fee_corrections_journaled")
        if not any(
            type(entry.get("sequence")) is int and entry["sequence"] > journaled
            for entry in _fee_corrections(order)
        ):
            return
        identity = _order_identity(order, recovery.nonce)
        if not _durable(identity):
            return
        get = getattr(getattr(order, "info", None), "get", None)
        totals = (get("provider_fee_totals") if callable(get) else None) or {}
        try:
            recovery.write_ledger_fee_intent(identity, totals)
        except Exception as error:  # fail closed: the window would stay open
            recovery.fail(error, "journal")

    def fee_correction_fence(self):
        """Why a late fee correction without a live order fenced trading, or ``None``."""
        return self.__dict__.get("_durable_fee_correction_fence")

    def _fence_durable_fee(self, reason):
        self.__dict__["_durable_fee_correction_fence"] = reason
        self._trading_enabled = False
        freeze = getattr(getattr(self, "store", None), "freeze_openings", None)
        if callable(freeze):
            freeze("fill_fee_correction_unprojectable")
        _logger.error("late fee correction cannot be projected; trading disabled (%s)", reason)
        return "fee_fenced"

    def _apply_durable_fill_fee(self, trade_key, update):
        """A fill an earlier process applied, reported again: at most a fee correction.

        Used when no live order takes the report (``_lookup_order`` found
        none). Returns ``None`` when no bound journal indexes the fill (the
        caller keeps its unmatched handling), else ``"ignored"`` (same fee,
        or another quantity/price/no fee: never a new fill), ``"fee_fenced"``
        (lower fee, another currency, a fill booked without a fee, or a
        ledger divergence) or ``"fee_corrected"``.
        """
        recoveries = self._strategy_notification_recovery
        if not recoveries or not trade_key:
            return None
        if not (self._remote_external_order_id(update) or self._remote_client_order_id(update)):
            return None
        fill_key = fill_index_key(trade_key)
        misses = self.__dict__.setdefault("_durable_fill_misses", set())
        if fill_key in misses:
            return None
        for recovery in list(recoveries.values()):
            if recovery.state != "ACTIVE":
                continue
            try:
                found = recovery.durable_fill(fill_key)
            except Exception as error:  # fail closed: the index cannot be trusted
                recovery.fail(error, "index")
                return self._fence_durable_fee("applied_fill_index_unavailable")
            if found is not None:
                return self._correct_durable_fill(recovery, fill_key, *found, update)
        if len(misses) >= _MAX_CACHE:
            misses.clear()
        misses.add(fill_key)
        return None

    def _correct_durable_fill(self, recovery, fill_key, order_key, fill, update):
        amount, _error = self._normalized_commission(update)
        if amount is None:
            return "ignored"
        value = self._extract_update_value
        quantity = self._neutral_decimal(value(update, "quantity"), positive=True)
        price = self._neutral_decimal(value(update, "price"), positive=True)
        if (
            fill.get("quantity") is None
            or quantity != _Decimal(fill["quantity"])
            or price != _Decimal(fill["price"])
        ):
            return "ignored"
        reported = _Decimal(str(amount))
        currency = self._extract_update_value(update, "fee_currency")
        currency = currency if type(currency) is str and currency else None
        booked = None if fill.get("fee") is None else _Decimal(fill["fee"])
        if booked is not None and reported == booked and currency == fill.get("currency"):
            return "ignored"
        if booked is None or currency is None or currency != fill.get("currency"):
            return self._fence_durable_fee("fee_currency_or_basis_mismatch")
        if reported < booked:
            return self._fence_durable_fee("fee_regressed")
        try:
            outcome = recovery.book_durable_correction(
                fill_key,
                order_key,
                fill,
                reported,
                currency,
                getattr(self, "_direct_strategy_ledger", None),
            )
        except Exception as error:  # the ledger may have moved: a re-delivery completes it
            recovery.fail(error, "journal")
            return self._fence_durable_fee("fee_correction_journal_failed")
        if type(outcome) is str:
            return self._fence_durable_fee(outcome)
        if outcome.entries:
            self.notifs.append(outcome)
        return "fee_corrected"

    def close_strategy_notification_recovery(self) -> None:
        notifs = getattr(self, "notifs", None)
        if notifs:
            # Journaled and unacknowledged: replayed when recovery is bound again.
            kept = [n for n in notifs if type(n) is not DurableFeeCorrectionDelivery]
            if len(kept) != len(notifs):
                notifs.clear()
                notifs.extend(kept)
        for recovery in (self._strategy_notification_recovery or {}).values():
            recovery.restore()
            recovery.close()
        self._strategy_notification_recovery = None
