"""Gateway-mode execution events for ``BtApiBroker`` (iteration 60, R2-C).

In Gateway mode the account owner process publishes each strategy's typed
terminal-order and per-fill observations into the Gateway account journal.
This mixin reads them with the SDK
``bt_api_py.service_execution_event_consumer.ServiceExecutionEventConsumer``
and drives the Broker's *existing* direct-mode projection: each observation is
converted to the neutral update row the Store would produce and applied
through the same ``_apply_broker_update_row`` path, so ``Strategy.notify_order``
/ ``notify_trade``, the strategy ledger and the standard notification journal
(``bind_strategy_notification_recovery``) behave exactly as in direct mode.

Exactly-once *effect* across process restarts:

* **Order of commits.** For each page: apply every event (Broker state,
  ledger update, notification journal append - all durable before the next
  step), record the event's fact id and the order's projected state in this
  module's SQLite store, then commit the SDK cursor locally and ACK the
  Gateway. The remote ACK never runs ahead of a durable effect.
* **Re-arrival.** Events after the last committed cursor re-arrive after a
  crash. An event whose fact id is recorded is skipped. An event applied but
  not yet recorded (crash between the two writes) is applied again onto the
  same persisted order state, so it yields the same notification ids: the
  notification journal recognises them as written by an earlier process and
  this Broker does not deliver them again (they were either delivered and
  acknowledged, or replayed at ``bind_strategy_notification_recovery``). The
  ledger takes cumulative quantities, so re-application is idempotent.
* **Orders of a dead process.** Every order of a bound Strategy with a client
  order id is recorded before events for it are read. After a restart its
  non-terminal orders are rebuilt as real ``Order`` objects (same data feed,
  side, size, price, ledger intent and executed state) so later events keep
  projecting. Not rebuilt: parent/OCO links, ``executed.exbits`` history and
  the Broker's in-memory ``Position`` (the ledger is the durable position).
* **Fills before their order.** A fill whose provider order id is not linked
  yet is kept durably and applied right before the order observation that
  links it, as the direct path's deferred fills are.

Remaining at-least-once windows (documented, not hidden): a Strategy callback
that ran but whose notification-journal ACK was lost is replayed once with
the same ``notification_id`` (as in direct mode); a crash after an order
notification was journaled but before its Trade was journaled replays the
order only. Fees (iteration 60 R3): a Gateway trade observation carries the
provider fee of the fill when the provider supplies it (Base execution event
v2); the row then has ``fee``/``fee_currency``/``fee_unit`` like a direct fill
row, and a later event for the same fill with a higher fee is the repeated-fill
fee correction of the direct path (``notify_fee_correction``). A fill without a
fee is booked with ``commission_source="unavailable"`` exactly as a fee-less
direct fill. The terminal order of a previous process is not rebuilt, so a fee
correction that arrives only after a restart is counted as orphaned.
"""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path

from ..utils.log_message import get_logger

_logger = get_logger(__name__)

_STORE_SCHEMA = "backtrader.gateway_execution_projection.v1"
_MAX_DEFERRED = 10_000
_RETAIN_FACTS = 100_000

# Neutral ``ExecutionOrderRecord.status`` -> (canonical Broker status, terminal).
_STATUS = {
    "open": ("accepted", False),
    "trigger_pending": ("accepted", False),
    "triggered": ("accepted", False),
    "partially_filled": ("partial", False),
    "filled": ("completed", True),
    "canceled": ("canceled", True),
    "partially_filled_canceled": ("canceled", True),
    "partially_filled_terminal": ("canceled", True),
    "terminal_unfilled": ("canceled", True),
    "rejected": ("rejected", True),
    "unknown": ("unknown", False),
}


class GatewayExecutionEventsError(RuntimeError):
    """Finite, value-free failure of the Gateway execution projection."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _decimal_text(value) -> str:
    number = Decimal(str(value))
    return "0" if number == 0 else format(number.normalize(), "f")


def order_update_row(observation, *, data_name, local_ref=None):
    """The neutral Broker update row for one ``AccountExecutionOrderObservation``."""

    record = observation.order
    status, terminal = _STATUS[record.status]
    if status == "accepted" and Decimal(record.filled_quantity) > 0:
        status = "partial"
    row = {
        "kind": "order",
        "status": status,
        "terminal_confirmed": terminal,
        "execution_unknown": status == "unknown",
        "execution_source": "trades",
        "external_order_id": record.order_id,
        "order_id": record.order_id,
        "data_name": data_name,
        "side": record.side,
        "quantity": _decimal_text(record.quantity),
        "filled_quantity": _decimal_text(record.filled_quantity),
        "quantity_unit": record.qty_unit,
    }
    if record.intent_binding == "verified":
        row["client_order_id"] = record.client_order_id
    if local_ref is not None:
        row["local_ref"] = local_ref
    return row


def trade_update_row(observation, *, data_name, local_ref=None):
    """The neutral Broker update row for one ``AccountExecutionTradeObservation``."""

    record = observation.trade
    row = {
        "kind": "trade",
        "trade_id": record.trade_id,
        "data_name": data_name,
        "side": record.side,
        "quantity": _decimal_text(record.quantity),
        "price": _decimal_text(record.price),
        "quantity_unit": record.qty_unit,
    }
    if record.order_id is not None:
        row["external_order_id"] = record.order_id
        row["order_id"] = record.order_id
    if record.traded_at_utc is not None:
        row["timestamp"] = record.traded_at_utc
    fee = getattr(observation, "fee", None)
    if fee is not None:
        # The provider fee of this fill, in its explicit currency (direct parity).
        row["fee"] = fee
        row["fee_currency"] = observation.fee_currency
        row["fee_unit"] = "currency"
    if local_ref is not None:
        row["local_ref"] = local_ref
    return row


class GatewayExecutionProjectionStore:
    """One Strategy's durable projection: order bindings, applied facts, deferred fills."""

    def __init__(self, path, binding):
        self._binding = json.dumps(binding, sort_keys=True, separators=(",", ":"))
        try:
            self._db = sqlite3.connect(str(path), isolation_level=None)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS meta (
                    id INTEGER PRIMARY KEY CHECK (id = 1), schema TEXT NOT NULL,
                    binding TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS orders (
                    client_order_id TEXT PRIMARY KEY, record TEXT NOT NULL,
                    alive INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS external_orders (
                    order_id TEXT PRIMARY KEY, client_order_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS facts (
                    fact_id TEXT PRIMARY KEY, cursor INTEGER NOT NULL, outcome TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS deferred (
                    fact_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, cursor INTEGER NOT NULL,
                    row TEXT NOT NULL);
                """)
            self._db.execute("BEGIN IMMEDIATE")
            row = self._db.execute("SELECT schema, binding FROM meta WHERE id=1").fetchone()
            if row is None:
                self._db.execute(
                    "INSERT INTO meta VALUES (1, ?, ?)", (_STORE_SCHEMA, self._binding)
                )
            elif row != (_STORE_SCHEMA, self._binding):
                self._db.execute("ROLLBACK")
                self._db.close()
                raise GatewayExecutionEventsError("PROJECTION_STORE_BINDING_MISMATCH")
            self._db.execute("COMMIT")
        except sqlite3.Error:
            raise GatewayExecutionEventsError("PROJECTION_STORE_UNAVAILABLE") from None

    def _write(self, statements):
        try:
            self._db.execute("BEGIN IMMEDIATE")
            for sql, args in statements:
                self._db.execute(sql, args)
            self._db.execute("COMMIT")
        except sqlite3.Error:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise GatewayExecutionEventsError("PROJECTION_STORE_FAILED") from None

    @staticmethod
    def _order_statement(client_order_id, record):
        return (
            "INSERT INTO orders VALUES (?, ?, ?) ON CONFLICT(client_order_id) DO UPDATE SET "
            "record=excluded.record, alive=excluded.alive",
            (client_order_id, json.dumps(record, sort_keys=True), int(record["alive"])),
        )

    def put_order(self, client_order_id, record):
        self._write([self._order_statement(client_order_id, record)])

    def has_order(self, client_order_id):
        return (
            self._db.execute(
                "SELECT 1 FROM orders WHERE client_order_id=?", (client_order_id,)
            ).fetchone()
            is not None
        )

    def alive_orders(self):
        rows = self._db.execute(
            "SELECT client_order_id, record FROM orders WHERE alive=1 ORDER BY rowid"
        ).fetchall()
        return [(cid, json.loads(record)) for cid, record in rows]

    def link_external(self, order_id, client_order_id):
        current = self.client_for_external(order_id)
        if current not in (None, client_order_id):
            raise GatewayExecutionEventsError("EXTERNAL_ORDER_ID_CONFLICT")
        if current is None:
            self._write(
                [("INSERT INTO external_orders VALUES (?, ?)", (order_id, client_order_id))]
            )

    def client_for_external(self, order_id):
        row = self._db.execute(
            "SELECT client_order_id FROM external_orders WHERE order_id=?", (order_id,)
        ).fetchone()
        return None if row is None else row[0]

    def has_fact(self, fact_id):
        return (
            self._db.execute("SELECT 1 FROM facts WHERE fact_id=?", (fact_id,)).fetchone()
            is not None
        )

    def record_fact(self, fact_id, cursor, outcome, orders=(), undefer=None):
        statements = [
            (
                "INSERT OR IGNORE INTO facts VALUES (?, ?, ?)",
                (fact_id, cursor, outcome),
            ),
            ("DELETE FROM facts WHERE cursor < ?", (cursor - _RETAIN_FACTS,)),
        ]
        statements.extend(self._order_statement(cid, record) for cid, record in orders)
        if undefer is not None:
            statements.append(("DELETE FROM deferred WHERE fact_id=?", (undefer,)))
        self._write(statements)

    def defer(self, fact_id, order_id, cursor, row):
        count = self._db.execute("SELECT COUNT(*) FROM deferred").fetchone()[0]
        if count >= _MAX_DEFERRED:
            raise GatewayExecutionEventsError("DEFERRED_FILLS_CAPACITY")
        self._write(
            [
                (
                    "INSERT OR IGNORE INTO deferred VALUES (?, ?, ?, ?)",
                    (fact_id, order_id, cursor, json.dumps(row, sort_keys=True)),
                )
            ]
        )

    def deferred_for(self, order_id):
        rows = self._db.execute(
            "SELECT fact_id, cursor, row FROM deferred WHERE order_id=? ORDER BY cursor",
            (order_id,),
        ).fetchall()
        return [(fact_id, cursor, json.loads(row)) for fact_id, cursor, row in rows]

    def is_deferred(self, fact_id):
        return (
            self._db.execute("SELECT 1 FROM deferred WHERE fact_id=?", (fact_id,)).fetchone()
            is not None
        )

    def close(self):
        self._db.close()


def _order_record(broker, order, strategy_ref, client_order_id):
    info = broker._order_info_get
    executed = order.executed
    original_ref = info(order, "notification_ref")
    return {
        "client_order_id": client_order_id,
        "strategy_ref": strategy_ref,
        "ref": int(order.ref if type(original_ref) is not int else original_ref),
        "data_name": broker._position_key(order.data),
        "side": "buy" if order.isbuy() else "sell",
        "size": float(order.size),
        "price": None if order.price is None else float(order.price),
        "exectype": None if order.exectype is None else int(order.exectype),
        "status": int(order.status),
        "alive": bool(order.alive()),
        "executed": {
            "size": float(executed.size or 0.0),
            "price": float(executed.price or 0.0),
            "value": float(executed.value or 0.0),
            "comm": float(executed.comm or 0.0),
        },
        "info": {
            key: info(order, key)
            for key in (
                "strategy_ledger_intent_id",
                "external_order_id",
                "quantity_unit",
                "position_side",
                "offset",
                "remote_terminal_status",
                "remote_terminal_filled",
            )
            if info(order, key) is not None
        },
    }


class _GatewayExecutionBinding:
    def __init__(self, strategy, strategy_ref, consumer, store, data_names, acknowledge):
        self.strategy = strategy
        self.strategy_ref = strategy_ref
        self.consumer = consumer
        self.store = store
        self.data_names = data_names
        self.acknowledge = acknowledge
        self.live = {}
        self.state = "ACTIVE"
        self.counters = {"applied": 0, "skipped": 0, "orphaned": 0, "deferred": 0}


class GatewayExecutionEventsBrokerMixin:
    """Project a Strategy's Gateway execution stream through the direct-mode path."""

    _gateway_execution_bindings = None

    def bind_gateway_execution_events(
        self,
        strategy,
        consumer,
        directory,
        *,
        data_names=None,
        acknowledge="after_apply",
    ):
        """Consume ``strategy``'s Gateway execution stream; return rebuilt order count.

        ``consumer`` is the SDK ``ServiceExecutionEventConsumer`` of this
        Strategy's execution stream. ``bind_strategy_notification_recovery``
        must be bound first (its journal is how a re-applied event is
        recognised). ``data_names`` maps the neutral ``instrument_id`` to the
        Backtrader data name (default: a data whose name equals the
        ``instrument_id`` or ``native_symbol``). ``acknowledge="after_apply"``
        ACKs each page right after it was applied; ``"manual"`` leaves the
        ACK to ``acknowledge_gateway_execution_events()`` (the committed
        cursor is ACKed first on the next poll anyway).
        """

        from bt_api_py.service_execution_event_consumer import ServiceExecutionEventConsumer

        if type(consumer) is not ServiceExecutionEventConsumer:
            raise ValueError("a bt_api_py ServiceExecutionEventConsumer is required")
        if acknowledge not in ("after_apply", "manual"):
            raise ValueError("acknowledge must be 'after_apply' or 'manual'")
        recoveries = getattr(self, "_strategy_notification_recovery", None) or {}
        if id(strategy) not in recoveries:
            raise ValueError("bind_strategy_notification_recovery must be bound first")
        params = getattr(strategy, "p", None)
        strategy_ref = getattr(params, "strategy_ref", None)
        account_ref = getattr(params, "account_ref", None)
        if not all(type(value) is str and value for value in (strategy_ref, account_ref)):
            raise ValueError("the strategy needs strategy_ref and account_ref params")
        bindings = self._gateway_execution_bindings
        if bindings is None:
            bindings = self._gateway_execution_bindings = {}
        if id(strategy) in bindings:
            raise ValueError("this strategy already consumes Gateway execution events")
        folder = Path(directory)
        folder.mkdir(parents=True, exist_ok=True)
        import hashlib

        stem = hashlib.sha256(f"{account_ref}\0{strategy_ref}".encode()).hexdigest()[:24]
        store = GatewayExecutionProjectionStore(
            folder / f"{stem}.gateway-execution.sqlite3",
            {
                "account_ref": account_ref,
                "strategy_ref": strategy_ref,
                "consumer": consumer.binding_digest,
            },
        )
        binding = _GatewayExecutionBinding(
            strategy, strategy_ref, consumer, store, dict(data_names or {}), acknowledge
        )
        try:
            rebuilt = self._rehydrate_gateway_orders(binding)
        except BaseException:
            store.close()
            raise
        bindings[id(strategy)] = binding
        return rebuilt

    # -- polling -----------------------------------------------------------------

    def poll_gateway_execution_events(self, strategy=None):
        """Read, apply and commit one page per bound Strategy; return applied events.

        A failure disables trading and raises ``GatewayExecutionEventsError``;
        nothing after the failing event is committed, so it is read again.
        """

        applied = 0
        for binding in self._gateway_targets(strategy):
            applied += self._poll_gateway_binding(binding)
        return applied

    def acknowledge_gateway_execution_events(self, strategy=None):
        """ACK the committed cursor of each bound Strategy (``acknowledge="manual"``)."""

        from bt_api_py.service_execution_event_consumer import ServiceExecutionEventConsumerError

        for binding in self._gateway_targets(strategy):
            try:
                binding.consumer.acknowledge()
            except ServiceExecutionEventConsumerError as error:
                raise GatewayExecutionEventsError(error.code) from None

    def gateway_execution_events_state(self, strategy):
        binding = (self._gateway_execution_bindings or {}).get(id(strategy))
        if binding is None:
            return None
        return {"state": binding.state, **binding.counters}

    def remember_gateway_order(self, order):
        """Record ``order``'s binding now (otherwise done before every read)."""

        binding = (self._gateway_execution_bindings or {}).get(id(getattr(order, "owner", None)))
        if binding is not None:
            self._remember_gateway_order(binding, order)

    def close_gateway_execution_events(self):
        for binding in (self._gateway_execution_bindings or {}).values():
            binding.store.close()
        self._gateway_execution_bindings = None

    def _poll_gateway_execution_events(self):
        """``next()`` hook: never raises; a failure has already disabled trading."""

        if not self._gateway_execution_bindings:
            return
        try:
            self.poll_gateway_execution_events()
        except GatewayExecutionEventsError as error:
            _logger.error("gateway execution events failed (%s); will retry", error.code)

    def _gateway_targets(self, strategy):
        bindings = self._gateway_execution_bindings or {}
        if strategy is None:
            return [b for b in bindings.values() if b.state == "ACTIVE"]
        binding = bindings.get(id(strategy))
        return [] if binding is None or binding.state != "ACTIVE" else [binding]

    def _poll_gateway_binding(self, binding):
        from bt_api_py.service_execution_event_consumer import ServiceExecutionEventConsumerError

        try:
            for order in list(self.orders.values()):
                if getattr(order, "owner", None) is binding.strategy:
                    self._remember_gateway_order(binding, order)
            page = binding.consumer.read()
            applied = 0
            for event in page.events:
                if binding.store.has_fact(event.event_id) or binding.store.is_deferred(
                    event.event_id
                ):
                    binding.counters["skipped"] += 1
                    continue
                applied += self._apply_gateway_event(binding, event)
            binding.consumer.commit(page)
            if binding.acknowledge == "after_apply":
                binding.consumer.acknowledge()
            return applied
        except ServiceExecutionEventConsumerError as error:
            self._fail_gateway_binding(binding, error.code)
            raise GatewayExecutionEventsError(error.code) from None
        except GatewayExecutionEventsError as error:
            self._fail_gateway_binding(binding, error.code)
            raise

    def _fail_gateway_binding(self, binding, code):
        binding.state = "FAILED"
        self._trading_enabled = False
        _logger.error("gateway execution projection failed; trading disabled (%s)", code)

    # -- projection ----------------------------------------------------------------

    def _gateway_data_name(self, binding, instrument):
        mapped = binding.data_names.get(instrument.instrument_id)
        if mapped is not None:
            return mapped
        for data in getattr(binding.strategy, "datas", ()) or ():
            if getattr(data, "_name", None) in (instrument.instrument_id, instrument.native_symbol):
                return data._name
        return None

    def _remember_gateway_order(self, binding, order):
        client_order_id = self._order_info_get(order, "client_order_id")
        if client_order_id in (None, ""):
            return
        client_order_id = str(client_order_id)
        known = binding.live.get(client_order_id)
        if known is order and binding.store.has_order(client_order_id):
            return
        if known is not None and known is not order:
            raise GatewayExecutionEventsError("CLIENT_ORDER_ID_REUSED")
        binding.live[client_order_id] = order
        if not binding.store.has_order(client_order_id):
            binding.store.put_order(
                client_order_id,
                _order_record(self, order, binding.strategy_ref, client_order_id),
            )

    def _apply_gateway_event(self, binding, event):
        from bt_api_base.execution_row_observation_protocol import EXECUTION_ORDER_EVENT_KIND

        observation = event.observation
        if event.kind == EXECUTION_ORDER_EVENT_KIND:
            return self._apply_gateway_order(binding, event, observation)
        return self._apply_gateway_trade(binding, event, observation)

    def _apply_gateway_order(self, binding, event, observation):
        record = observation.order
        client_order_id = record.client_order_id if record.intent_binding == "verified" else None
        order = binding.live.get(client_order_id) if client_order_id is not None else None
        if order is None:
            # Not an order of this Strategy that this process can project
            # (unknown binding or terminal before a restart): counted only,
            # and so are its fills, now and later.
            if client_order_id is not None:
                binding.store.link_external(record.order_id, client_order_id)
            for fact_id, cursor, _row in binding.store.deferred_for(record.order_id):
                binding.counters["orphaned"] += 1
                binding.store.record_fact(fact_id, cursor, "orphaned", undefer=fact_id)
            binding.counters["orphaned"] += 1
            binding.store.record_fact(event.event_id, event.cursor, "orphaned")
            return 0
        data_name = self._gateway_data_name(binding, record.instrument)
        if data_name is None or data_name != self._position_key(order.data):
            raise GatewayExecutionEventsError("EXECUTION_INSTRUMENT_MISMATCH")
        binding.store.link_external(record.order_id, client_order_id)
        # Fills reported before this order observation go first (direct parity).
        for fact_id, cursor, row in binding.store.deferred_for(record.order_id):
            row["local_ref"] = order.ref
            self._apply_broker_update_row(row)
            binding.store.record_fact(
                fact_id,
                cursor,
                "applied",
                orders=[self._gateway_order_snapshot(binding, client_order_id, order)],
                undefer=fact_id,
            )
            binding.counters["applied"] += 1
        self._apply_broker_update_row(
            order_update_row(observation, data_name=data_name, local_ref=order.ref)
        )
        binding.store.record_fact(
            event.event_id,
            event.cursor,
            "applied",
            orders=[self._gateway_order_snapshot(binding, client_order_id, order)],
        )
        binding.counters["applied"] += 1
        return 1

    def _apply_gateway_trade(self, binding, event, observation):
        record = observation.trade
        data_name = self._gateway_data_name(binding, record.instrument)
        if data_name is None:
            raise GatewayExecutionEventsError("EXECUTION_INSTRUMENT_MISMATCH")
        client_order_id = (
            binding.store.client_for_external(record.order_id)
            if record.order_id is not None
            else None
        )
        order = binding.live.get(client_order_id) if client_order_id is not None else None
        if order is None:
            if record.order_id is None or client_order_id is not None:
                # No provider order identity, or an order this process cannot
                # rebuild (terminal or unknown): never applied, only counted.
                binding.counters["orphaned"] += 1
                binding.store.record_fact(event.event_id, event.cursor, "orphaned")
                return 0
            binding.store.defer(
                event.event_id,
                record.order_id,
                event.cursor,
                trade_update_row(observation, data_name=data_name),
            )
            binding.counters["deferred"] += 1
            return 0
        self._apply_broker_update_row(
            trade_update_row(observation, data_name=data_name, local_ref=order.ref)
        )
        binding.store.record_fact(
            event.event_id,
            event.cursor,
            "applied",
            orders=[self._gateway_order_snapshot(binding, client_order_id, order)],
        )
        binding.counters["applied"] += 1
        return 1

    def _gateway_order_snapshot(self, binding, client_order_id, order):
        # A terminal order stays in this process's map, as it stays in
        # ``self.orders``: later rows still reach it (direct parity). Only
        # non-terminal orders are rebuilt after a restart.
        return client_order_id, _order_record(self, order, binding.strategy_ref, client_order_id)

    # -- restart -----------------------------------------------------------------

    def _rehydrate_gateway_orders(self, binding):
        from ..order import BuyOrder, SellOrder

        datas = {
            getattr(data, "_name", None): data
            for data in (getattr(binding.strategy, "datas", ()) or ())
        }
        rebuilt = 0
        for client_order_id, record in binding.store.alive_orders():
            data = datas.get(record["data_name"])
            if data is None or record.get("strategy_ref") != binding.strategy_ref:
                raise GatewayExecutionEventsError("ORDER_REHYDRATION_UNAVAILABLE")
            kind = BuyOrder if record["side"] == "buy" else SellOrder
            order = kind(
                owner=binding.strategy,
                data=data,
                size=abs(record["size"]),
                price=record["price"],
                exectype=record["exectype"],
                simulated=False,
            )
            order.addcomminfo(self.getcommissioninfo(data))
            order.broker = self
            executed = record["executed"]
            order.executed.size = executed["size"]
            order.executed.price = executed["price"]
            order.executed.value = executed["value"]
            order.executed.comm = executed["comm"]
            order.executed.remsize = order.size - executed["size"]
            order.status = record["status"]
            order.addinfo(
                client_order_id=client_order_id,
                gateway_rehydrated=True,
                notification_ref=int(record["ref"]),
            )
            order.addinfo(**record.get("info", {}))
            self.orders[order.ref] = order
            external = record.get("info", {}).get("external_order_id")
            if external:
                self._orders_by_external_id[str(external)] = order
            binding.live[client_order_id] = order
            rebuilt += 1
        return rebuilt

    def _gateway_previous_process_duplicate(self, order, event_id):
        """Whether ``event_id`` is a re-applied Gateway event journaled by an earlier process."""

        owner = getattr(order, "owner", None)
        if id(owner) not in (self._gateway_execution_bindings or {}):
            return False
        recovery = (getattr(self, "_strategy_notification_recovery", None) or {}).get(id(owner))
        return recovery is not None and event_id in recovery.previous_process_ids


__all__ = (
    "GatewayExecutionEventsBrokerMixin",
    "GatewayExecutionEventsError",
    "GatewayExecutionProjectionStore",
    "order_update_row",
    "trade_update_row",
)
