"""Explicit local Gateway notification transactions; no network or ACK calls.

The caller applies each already persisted event using the ordinary framework
algorithms. This coordinator snapshots the resulting objects before callbacks.
"""

from __future__ import annotations

import collections
import copy
import hashlib
import json
import math
import os
import threading
from dataclasses import dataclass, field
from types import MappingProxyType

from ..order import BuyOrder, SellOrder
from ..position import Position
from ..trade import Trade
from ..utils.autodict import AutoDictList


def _error(code):
    raise ValueError("GATEWAY_NOTIFICATION_" + code)


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
    ).encode("utf-8", errors="strict")


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _text(value):
    return type(value) is str and bool(value) and value == value.strip() and len(value) <= 512


@dataclass(eq=False, frozen=True)
class _Receipt:
    binding: object
    phase: str
    checkpoint: object
    batch_id: str


@dataclass(eq=False)
class _Binding:
    strategy: object
    host: object
    feeds: dict
    orders: dict
    pid: int = field(default_factory=os.getpid)
    thread: int = field(default_factory=threading.get_ident)
    thread_object: object = field(default_factory=threading.current_thread)
    armed: object = None
    arm_checkpoint: object = None
    receipt: object = None
    fee_receipt: object = None
    fee_ready: bool = False
    restored: object = None
    replaying: bool = False
    replay_phase: object = None
    active: object = None
    candidate: object = None
    fault: object = None


class GatewayNotificationsBrokerMixin:
    """One explicitly bound local stream and strategy per notification scope."""

    def _gateway_binding(self, strategy, *, required=False, check_live=True):
        binding = self.__dict__.get("_gateway_notification_bindings", {}).get(id(strategy))
        if binding is None:
            if required:
                _error("NOT_BOUND")
            return None
        if (
            binding.strategy is not strategy
            or strategy.broker is not self
            or binding.pid != os.getpid()
            or binding.thread != threading.get_ident()
            or binding.thread_object is not threading.current_thread()
        ):
            _error("SCOPE")
        if check_live:
            self._gateway_check_live_scope(binding)
        return binding

    def _gateway_check_live_scope(self, binding):
        names = {self._position_key(data) for data in binding.feeds.values()}
        conflict = (
            self._direct_selected()
            or getattr(self, "_direct_on", False)
            or getattr(self, "_direct_attempted", False)
            or getattr(self, "_managed_runtime_session", None) is not None
            or getattr(self, "_service_execution_session", None) is not None
            or getattr(self, "_service_execution_recovery_strategy", None) is not None
            or id(binding.strategy)
            in (getattr(self, "_strategy_notification_recovery", None) or {})
            or any(
                getattr(order, "owner", None) is not binding.strategy
                and self._position_key(getattr(order, "data", None)) in names
                for order in self.orders.values()
            )
            or any(
                other is not binding
                and bool(names & {self._position_key(data) for data in other.feeds.values()})
                for other in self.__dict__.get("_gateway_notification_bindings", {}).values()
            )
        )
        if conflict:
            binding.fault = "restart_required"
            _error("MODE_OR_POSITION_CONFLICT")

    def bind_gateway_notification_state(self, strategy, *, host, data_by_ref, orders_by_key):
        from ..live_state.gateway_pending import GatewayPendingHost
        from ..strategy import Strategy

        if (
            type(host) is not GatewayPendingHost
            or not isinstance(strategy, Strategy)
            or getattr(strategy, "broker", None) is not self
        ):
            _error("SCOPE")
        if (
            self._direct_selected()
            or getattr(self, "_direct_on", False)
            or getattr(self, "_direct_attempted", False)
            or getattr(self, "_managed_runtime_session", None) is not None
            or getattr(self, "_service_execution_session", None) is not None
            or getattr(self, "_service_execution_recovery_strategy", None) is not None
            or id(strategy) in (getattr(self, "_strategy_notification_recovery", None) or {})
        ):
            _error("MODE_CONFLICT")
        if type(data_by_ref) is not dict or not data_by_ref or type(orders_by_key) is not dict:
            _error("BINDING_INVALID")
        if any(not _text(key) for key in data_by_ref) or len(
            {id(v) for v in data_by_ref.values()}
        ) != len(data_by_ref):
            _error("FEED_SCOPE")
        # The existing codec establishes the exact DataBase contract.
        from ._btapi_gateway_projection import _sources

        _sources(data_by_ref)
        bindings = self.__dict__.setdefault("_gateway_notification_bindings", {})
        if id(strategy) in bindings:
            _error("ALREADY_BOUND")
        names = {self._position_key(data) for data in data_by_ref.values()}
        if len(names) != len(data_by_ref) or any(not _text(name) for name in names):
            _error("FEED_SCOPE")
        for other in bindings.values():
            if other.host._store.path == host._store.path:
                _error("SHARED_HOST")
            if names & {self._position_key(data) for data in other.feeds.values()}:
                _error("SHARED_POSITION")
        for order in self.orders.values():
            if (
                getattr(order, "owner", None) is not strategy
                and self._position_key(getattr(order, "data", None)) in names
            ):
                _error("SHARED_POSITION")
        host.load_execution_checkpoint()
        binding = _Binding(strategy, host, dict(data_by_ref), {})
        for request_key, order in orders_by_key.items():
            self._gateway_register_order(binding, request_key, order)
        bindings[id(strategy)] = binding
        return host.load_execution_checkpoint()

    def _gateway_register_order(self, binding, request_key, order):
        if not _text(request_key) or type(order) not in (BuyOrder, SellOrder):
            _error("ORDER_SCOPE")
        if (
            order.owner is not binding.strategy
            or not any(order.data is x for x in binding.feeds.values())
            or getattr(order.p, "simulated", False)
        ):
            _error("ORDER_SCOPE")
        info = order.info
        if info.get("service_execution_recovery_receipt_id") or info.get(
            "service_execution_recovery_managed"
        ):
            _error("MODE_CONFLICT")
        if (
            binding.host.load_intent(request_key) is None
            or binding.host.load_record(request_key) is None
        ):
            _error("ORDER_BINDING")
        current = binding.orders.get(request_key)
        if current is not None:
            if current is order:
                return
            _error("ORDER_BINDING")
        if any(x is order or x.ref == order.ref for x in binding.orders.values()):
            _error("ORDER_BINDING")
        binding.orders[request_key] = order

    def register_gateway_notification_order(self, strategy, request_key, order):
        binding = self._gateway_binding(strategy, required=True)
        if binding.armed is not None or binding.receipt is not None:
            _error("BUSY")
        self._gateway_register_order(binding, request_key, order)

    def bind_strategy_notification_recovery(self, strategy, *args, **kwargs):
        if self._gateway_binding(strategy) is not None:
            _error("MODE_CONFLICT")
        return super().bind_strategy_notification_recovery(strategy, *args, **kwargs)

    def arm_gateway_notification_state(self, strategy, through_sequence):
        binding = self._gateway_binding(strategy, required=True)
        if type(through_sequence) is not int or through_sequence <= 0:
            _error("SEQUENCE")
        if (
            binding.armed is not None
            or binding.receipt is not None
            or binding.restored is not None
            or binding.fault is not None
        ):
            _error("BUSY")
        if strategy._orderspending or strategy._tradespending:
            _error("PENDING_FRAMEWORK_NOTIFICATIONS")
        checkpoint = binding.host.load_execution_checkpoint()
        batch = binding.host.load_execution_notification_batch()
        if batch is not None and batch["status"] == "pending":
            _error("PENDING")
        events = binding.host.read_execution_events(limit=1)
        if not events or events[0].sequence != through_sequence:
            _error("SEQUENCE")
        event = events[0]
        if event.request_key not in binding.orders or checkpoint.epoch is None:
            _error("ORDER_BINDING")
        binding.armed, binding.arm_checkpoint = event, checkpoint
        return event

    def _gateway_request(self, binding, order):
        if type(order) not in (BuyOrder, SellOrder) or order.owner is not binding.strategy:
            _error("ORDER_SCOPE")
        if order.info.get("service_execution_recovery_receipt_id") or order.info.get(
            "service_execution_recovery_managed"
        ):
            _error("MODE_CONFLICT")
        found = [
            (key, original) for key, original in binding.orders.items() if original.ref == order.ref
        ]
        if len(found) != 1 or found[0][1].data is not order.data:
            _error("ORDER_BINDING")
        return found[0][0]

    def _gateway_graph(self, binding, qorders, qtrades):
        from ._btapi_gateway_projection import _tradeid_encode, capture_framework_state

        strategy = binding.strategy
        orders, trades, positions = {}, {}, {}
        order_ids, trade_ids, position_ids = {}, {}, {}
        feeds = {id(data): ref for ref, data in binding.feeds.items()}
        seq = binding.armed.sequence

        def add_order(order, role, index):
            if order is None:
                return None
            request = self._gateway_request(binding, order)
            ident = id(order)
            if ident not in order_ids:
                key = "order/%d/%s/%d/%s" % (seq, role, index, _hash(request))
                order_ids[ident] = key
                orders[key] = order
            return order_ids[ident]

        def add_trade(trade, role, index):
            if type(trade) is not Trade or id(trade.data) not in feeds:
                _error("TRADE_SCOPE")
            ident = id(trade)
            if ident not in trade_ids:
                key = "trade/%d/%s/%d/%s" % (seq, role, index, _hash(feeds[id(trade.data)]))
                trade_ids[ident] = key
                trades[key] = trade
            return trade_ids[ident]

        originals = {
            key: add_order(order, "original", i)
            for i, (key, order) in enumerate(sorted(binding.orders.items()))
        }
        order_history = [add_order(o, "history", i) for i, o in enumerate(strategy._orders)]
        order_pending = [add_order(o, "pending", i) for i, o in enumerate(strategy._orderspending)]
        order_quick = [add_order(o, "quick", i) for i, o in enumerate(qorders)]
        trade_groups = []
        for data, groups in strategy._trades.items():
            if id(data) not in feeds or not hasattr(groups, "items"):
                _error("TRADE_SCOPE")
            for tradeid, values in groups.items():
                if type(values) is not list:
                    _error("TRADE_SCOPE")
                trade_groups.append(
                    {
                        "feed": feeds[id(data)],
                        "tradeid": _tradeid_encode(tradeid),
                        "items": [
                            add_trade(t, "group", len(trades) + j) for j, t in enumerate(values)
                        ],
                    }
                )
        trade_pending = [add_trade(t, "pending", i) for i, t in enumerate(strategy._tradespending)]
        trade_quick = [add_trade(t, "quick", i) for i, t in enumerate(qtrades)]
        for ref, trade in strategy.__dict__.get("_fee_correction_trades", {}).items():
            add_trade(trade, "fee_trade", len(trades))
        # Include each exact history clone, and then each parent/OCO reference.
        for trade in list(trades.values()):
            for row in trade.history:
                add_order(row.event.order, "trade_history", len(orders))
        index = 0
        info_seen = set()

        def add_info_orders(value, depth=0):
            if depth > 16 or len(info_seen) > 100_000:
                _error("ORDER_SCOPE")
            if type(value) in (BuyOrder, SellOrder):
                add_order(value, "info", len(orders))
            elif isinstance(value, dict):
                if id(value) in info_seen:
                    return
                info_seen.add(id(value))
                for item in value.values():
                    add_info_orders(item, depth + 1)
            elif type(value) in (list, tuple):
                if id(value) in info_seen:
                    return
                info_seen.add(id(value))
                for item in value:
                    add_info_orders(item, depth + 1)

        while index < len(orders):
            order = list(orders.values())[index]
            add_order(order.parent, "parent", len(orders))
            add_order(order.oco, "oco", len(orders))
            add_info_orders(order.info)
            index += 1
        position_slots = []
        for slot in ("positions", "long_positions", "short_positions"):
            container = getattr(self, slot)
            for feed_ref, data in binding.feeds.items():
                name = self._position_key(data)
                if name not in container:
                    continue
                position = container[name]
                if type(position) is not Position:
                    _error("POSITION_SCOPE")
                if id(position) in position_ids:
                    key = position_ids[id(position)]
                else:
                    key = "position/%s/%s" % (slot, _hash(feed_ref))
                    positions[key] = position
                    position_ids[id(position)] = key
                position_slots.append({"slot": slot, "feed": feed_ref, "key": key})
        for order in orders.values():
            if type(order.position) is Position and id(order.position) not in position_ids:
                _error("POSITION_SCOPE")
        applied, last_trade = [], []
        for ref, count in strategy.__dict__.get("_fee_corrections_applied", {}).items():
            matches = [key for key, order in binding.orders.items() if order.ref == ref]
            if len(matches) != 1 or type(count) is not int or count < 0:
                _error("FEE_SCOPE")
            applied.append([matches[0], count])
        for ref, trade in strategy.__dict__.get("_fee_correction_trades", {}).items():
            matches = [key for key, order in binding.orders.items() if order.ref == ref]
            if len(matches) != 1:
                _error("FEE_SCOPE")
            last_trade.append([matches[0], trade_ids[id(trade)]])
        metadata = {
            "version": 1,
            "through_sequence": seq,
            "originals": originals,
            "orders": order_history,
            "orders_pending": order_pending,
            "orders_quick": order_quick,
            "trade_groups": trade_groups,
            "trades_pending": trade_pending,
            "trades_quick": trade_quick,
            "position_slots": position_slots,
            "fee_applied": applied,
            "fee_trades": last_trade,
            "quick": bool(strategy._quicknotify),
            "fee": None,
        }
        snapshot = capture_framework_state(
            orders=orders,
            positions=positions,
            trades=trades,
            data_by_ref=binding.feeds,
            owner=strategy,
            broker=self,
        )
        snapshot["state"]["_gateway_strategy"] = metadata
        return snapshot, orders, trades, order_quick, trade_quick, order_pending, trade_pending

    def _gateway_notice(self, binding, kind, ordinal, object_key, payload):
        checkpoint = binding.arm_checkpoint
        ident = _hash(
            {
                "domain": "backtrader.gateway.notification.v1",
                "consumer_ref": checkpoint.consumer_ref,
                "epoch": checkpoint.epoch,
                "sequence": binding.armed.sequence,
                "kind": kind,
                "ordinal": ordinal,
                "object_key": object_key,
            }
        )
        return {
            "notification_id": ident,
            "kind": kind,
            "object_key": object_key,
            "payload": payload,
        }

    def _gateway_commit(self, binding, orders, trades, *, fee=None):
        if binding.armed is None:
            _error("NOT_ARMED")
        binding.fault = "restart_required"
        if not orders:
            _error("EVENT_SCOPE")
        if any(self._gateway_request(binding, o) != binding.armed.request_key for o in orders):
            _error("EVENT_SCOPE")
        # Build once to resolve stable object keys, then attach notification identities
        # and recapture the actual objects including those attributes.
        graph = self._gateway_graph(binding, orders, trades)
        _, order_map, trade_map, qorders, qtrades, _, _ = graph
        notices = []
        if fee is not None:
            fee_order, fee_trade, delta, currency, sequence = fee
            matches = [key for key, order in order_map.items() if order is fee_order]
            trade_matches = [key for key, trade in trade_map.items() if trade is fee_trade]
            if len(matches) != 1 or (fee_trade is not None and len(trade_matches) != 1):
                _error("FEE_SCOPE")
            payload = {
                "trade_key": None if fee_trade is None else trade_matches[0],
                "delta": delta,
                "currency": currency,
                "sequence": sequence,
            }
            notices.append(self._gateway_notice(binding, "fee", 0, matches[0], payload))
        for i, key in enumerate(qorders):
            item = self._gateway_notice(binding, "order", i, key, {})
            order_map[key].notification_id, order_map[key].replayed = item["notification_id"], False
            notices.append(item)
        for i, key in enumerate(qtrades):
            item = self._gateway_notice(binding, "trade", i, key, {})
            trade_map[key].notification_id, trade_map[key].replayed = item["notification_id"], False
            notices.append(item)
        if not notices:
            _error("EMPTY")
        snapshot, *_ = self._gateway_graph(binding, orders, trades)
        snapshot["state"]["_gateway_strategy"]["fee"] = None if fee is None else notices[0]
        binding.candidate = (snapshot, notices, list(orders), list(trades))
        binding.fault = "retryable"
        checkpoint = binding.host.commit_execution_notification_batch(
            binding.armed.sequence,
            snapshot,
            notices,
            expected_revision=binding.arm_checkpoint.revision,
            expected_applied_sequence=binding.arm_checkpoint.applied_sequence,
        )
        batch = binding.host.load_execution_notification_batch()
        receipt = _Receipt(
            binding, "fee" if fee else "notifications", checkpoint, batch["batch_id"]
        )
        binding.receipt = receipt
        binding.fault = None
        return receipt

    def _gateway_prepare_notifications(self, strategy, orders, trades):
        binding = self._gateway_binding(strategy)
        if binding is None:
            return None
        if binding.active is not None:
            _error("BUSY")
        if binding.fault is not None:
            _error("FAULT")
        if not orders and not trades:
            if binding.armed is not None:
                _error("EMPTY")
            return None
        if binding.replaying:
            if binding.receipt is None or binding.replay_phase != "notifications":
                _error("RECEIPT")
            binding.replay_phase = "in_callback"
            binding.active = binding.receipt
            return binding.receipt
        if binding.fee_receipt is not None:
            if not binding.fee_ready or binding.receipt is not binding.fee_receipt:
                _error("FEE_PHASE")
            current = binding.host.load_execution_checkpoint()
            if current.projection_digest != binding.receipt.checkpoint.projection_digest:
                _error("PROJECTION_CONFLICT")
            if (
                len(orders) != len(binding.candidate[2])
                or any(a is not b for a, b in zip(orders, binding.candidate[2]))
                or len(trades) != len(binding.candidate[3])
                or any(a is not b for a, b in zip(trades, binding.candidate[3]))
            ):
                _error("FEE_PHASE")
            current_snapshot, *_ = self._gateway_graph(binding, orders, trades)
            current_snapshot["state"]["_gateway_strategy"]["fee"] = binding.candidate[0]["state"][
                "_gateway_strategy"
            ]["fee"]
            if _canonical(current_snapshot) != _canonical(binding.candidate[0]):
                _error("PROJECTION_CONFLICT")
            object.__setattr__(binding.receipt, "phase", "notifications")
            binding.active = binding.receipt
            return binding.receipt
        if binding.receipt is not None:
            _error("PENDING")
        receipt = self._gateway_commit(binding, orders, trades)
        binding.active = receipt
        return receipt

    def _gateway_validate_fee_notifications(self, strategy, order, corrections, done):
        binding = self.__dict__.get("_gateway_notification_bindings", {}).get(id(strategy))
        try:
            binding = self._gateway_binding(strategy)
            if binding is None:
                return None
            return self._gateway_validate_fee_inner(binding, order, corrections, done)
        except BaseException:
            if binding is not None and binding.strategy is strategy:
                binding.fault = "restart_required"
            raise

    def _gateway_validate_fee_inner(self, binding, order, corrections, done):
        if binding.fault is not None or binding.receipt is not None:
            _error("FAULT")
        if (
            binding.armed is None
            or self._gateway_request(binding, order) != binding.armed.request_key
        ):
            _error("EVENT_SCOPE")
        if type(corrections) not in (list, tuple) or type(done) is not int or done < 0:
            _error("FEE_INVALID")
        if list(order.executed.iterpending()):
            _error("FEE_WITH_EXECUTION")
        pending = []
        for entry in corrections:
            if (
                type(entry) is not dict
                or type(entry.get("sequence")) is not int
                or entry["sequence"] <= 0
            ):
                _error("FEE_INVALID")
            if entry["sequence"] > done:
                pending.append(entry)
        if len(pending) > 1:
            _error("FEE_INVALID")
        if pending:
            entry = pending[0]
            try:
                delta = float(entry["delta"])
            except (TypeError, ValueError, OverflowError, KeyError):
                _error("FEE_INVALID")
            if (
                type(entry["delta"]) is bool
                or not math.isfinite(delta)
                or not _text(entry.get("currency"))
                or entry["sequence"] != done + 1
            ):
                _error("FEE_INVALID")
            return (
                MappingProxyType(
                    {"sequence": entry["sequence"], "delta": delta, "currency": entry["currency"]}
                ),
            )
        return ()

    def _gateway_prepare_fee_notification(self, strategy, order, trade, delta, currency, sequence):
        binding = self._gateway_binding(strategy)
        if binding is None:
            return None
        if binding.active is not None or binding.receipt is not None or binding.armed is None:
            _error("FEE_PHASE")
        receipt = self._gateway_commit(
            binding, [order], [], fee=(order, trade, delta, currency, sequence)
        )
        binding.fee_receipt = receipt
        order.notification_id = binding.candidate[1][0]["notification_id"]
        order.replayed = False
        binding.active = receipt
        return receipt

    def _gateway_confirm_notifications(self, strategy, receipt):
        binding = self._gateway_binding(strategy, required=True)
        if (
            type(receipt) is not _Receipt
            or receipt is not binding.receipt
            or receipt.binding is not binding
            or receipt is not binding.active
        ):
            _error("RECEIPT")
        if binding.fault is not None:
            _error("FAULT")
        if receipt.phase == "fee":
            binding.fee_ready = True
            binding.candidate[2][0].notification_id = binding.candidate[1][1]["notification_id"]
            binding.active = None
            return
        if receipt.phase != "notifications":
            _error("RECEIPT")
        checkpoint = receipt.checkpoint
        binding.host.confirm_execution_notification_batch(
            receipt.batch_id,
            expected_revision=checkpoint.revision,
            expected_applied_sequence=checkpoint.applied_sequence,
            expected_projection_digest=checkpoint.projection_digest,
        )
        binding.armed = binding.arm_checkpoint = binding.receipt = binding.fee_receipt = None
        binding.fee_ready = False
        binding.restored = None
        binding.candidate = None
        binding.active = None

    def _gateway_abort_notifications(self, strategy, receipt):
        binding = self._gateway_binding(strategy, required=True, check_live=False)
        if (
            type(receipt) is not _Receipt
            or receipt is not binding.receipt
            or receipt is not binding.active
            or receipt.binding is not binding
        ):
            _error("RECEIPT")
        binding.active = None

    def assert_gateway_notifications_ackable(self, strategy, sequence):
        binding = self._gateway_binding(strategy, required=True)
        checkpoint = binding.host.load_execution_checkpoint()
        batch = binding.host.load_execution_notification_batch()
        if (
            type(sequence) is not int
            or sequence != checkpoint.applied_sequence
            or batch is None
            or batch["through_sequence"] != sequence
            or batch["status"] != "confirmed"
            or binding.receipt is not None
            or binding.fault is not None
            or binding.active is not None
        ):
            _error("ACK_BLOCKED")
        return checkpoint

    def restore_gateway_notification_state(self, strategy):
        from ._btapi_gateway_projection import _tradeid_decode, restore_framework_state

        binding = self._gateway_binding(strategy, required=True)
        if (
            binding.orders
            or binding.armed is not None
            or binding.receipt is not None
            or strategy._orders
            or strategy._orderspending
            or strategy._tradespending
            or strategy._trades
            or binding.fault is not None
        ):
            _error("RESTORE_NOT_EMPTY")
        checkpoint = binding.host.load_execution_checkpoint()
        batch = binding.host.load_execution_notification_batch()
        if batch is None or checkpoint.projection is None:
            _error("RESTORE_MISSING")
        snapshot = copy.deepcopy(checkpoint.projection)
        metadata = snapshot["state"].pop("_gateway_strategy", None)
        snapshot["state"].pop("_gateway_notifications", None)
        fields = {
            "version",
            "through_sequence",
            "originals",
            "orders",
            "orders_pending",
            "orders_quick",
            "trade_groups",
            "trades_pending",
            "trades_quick",
            "position_slots",
            "fee_applied",
            "fee_trades",
            "quick",
            "fee",
        }
        if (
            type(metadata) is not dict
            or set(metadata) != fields
            or type(metadata["version"]) is not int
            or metadata["version"] != 1
            or type(metadata["through_sequence"]) is not int
            or metadata["through_sequence"] != checkpoint.applied_sequence
            or type(metadata["quick"]) is not bool
            or metadata["quick"] != bool(strategy._quicknotify)
            or type(metadata["originals"]) is not dict
            or not metadata["originals"]
        ):
            _error("RESTORE_INVALID")
        restored = restore_framework_state(
            snapshot,
            data_by_ref=binding.feeds,
            owner=strategy,
            broker=self,
            commission_for_data=self.getcommissioninfo,
        )

        def order_list(keys):
            if type(keys) is not list or any(
                type(k) is not str or k not in restored.orders for k in keys
            ):
                _error("RESTORE_INVALID")
            return [restored.orders[k] for k in keys]

        def trade_list(keys):
            if type(keys) is not list or any(
                type(k) is not str or k not in restored.trades for k in keys
            ):
                _error("RESTORE_INVALID")
            return [restored.trades[k] for k in keys]

        originals = {}
        for request_key, object_key in metadata["originals"].items():
            if (
                not _text(request_key)
                or type(object_key) is not str
                or object_key not in restored.orders
                or binding.host.load_intent(request_key) is None
                or binding.host.load_record(request_key) is None
            ):
                _error("RESTORE_INVALID")
            originals[request_key] = restored.orders[object_key]
        if len({o.ref for o in originals.values()}) != len(originals):
            _error("RESTORE_INVALID")
        orders = order_list(metadata["orders"])
        orders_pending = order_list(metadata["orders_pending"])
        qorders = order_list(metadata["orders_quick"])
        trades_pending = trade_list(metadata["trades_pending"])
        qtrades = trade_list(metadata["trades_quick"])
        if metadata["orders_pending"] != metadata["orders_quick"]:
            _error("RESTORE_INVALID")
        if metadata["quick"]:
            if len(trades_pending) != len(qtrades) or any(
                pending.ref != quick.ref for pending, quick in zip(trades_pending, qtrades)
            ):
                _error("RESTORE_INVALID")
        elif metadata["trades_pending"] != metadata["trades_quick"]:
            _error("RESTORE_INVALID")
        trade_groups = collections.defaultdict(AutoDictList)
        if type(metadata["trade_groups"]) is not list:
            _error("RESTORE_INVALID")
        for row in metadata["trade_groups"]:
            if (
                type(row) is not dict
                or set(row) != {"feed", "tradeid", "items"}
                or row["feed"] not in binding.feeds
            ):
                _error("RESTORE_INVALID")
            data = binding.feeds[row["feed"]]
            tradeid = _tradeid_decode(row["tradeid"])
            try:
                duplicate = tradeid in trade_groups[data]
            except TypeError:
                _error("RESTORE_INVALID")
            group = trade_list(row["items"])
            if duplicate or any(t.data is not data or t.tradeid != tradeid for t in group):
                _error("RESTORE_INVALID")
            trade_groups[data][tradeid] = group
        slots = []
        seen_slots = set()
        if type(metadata["position_slots"]) is not list:
            _error("RESTORE_INVALID")
        for row in metadata["position_slots"]:
            if (
                type(row) is not dict
                or set(row) != {"slot", "feed", "key"}
                or row["slot"] not in ("positions", "long_positions", "short_positions")
                or row["feed"] not in binding.feeds
                or row["key"] not in restored.positions
            ):
                _error("RESTORE_INVALID")
            container = getattr(self, row["slot"])
            name = self._position_key(binding.feeds[row["feed"]])
            if (row["slot"], name) in seen_slots or name in container:
                _error("RESTORE_NOT_EMPTY")
            seen_slots.add((row["slot"], name))
            slots.append((container, name, restored.positions[row["key"]]))
        if {id(position) for position in restored.positions.values()} != {
            id(position) for _, _, position in slots
        }:
            _error("RESTORE_INVALID")
        fee_applied, fee_trades = {}, {}
        for name, target in (("fee_applied", fee_applied), ("fee_trades", fee_trades)):
            rows = metadata[name]
            if type(rows) is not list:
                _error("RESTORE_INVALID")
            for row in rows:
                if type(row) is not list or len(row) != 2 or row[0] not in originals:
                    _error("RESTORE_INVALID")
                ref = originals[row[0]].ref
                if ref in target:
                    _error("RESTORE_INVALID")
                if name == "fee_applied":
                    if type(row[1]) is not int or row[1] < 0:
                        _error("RESTORE_INVALID")
                    target[ref] = row[1]
                else:
                    if type(row[1]) is not str or row[1] not in restored.trades:
                        _error("RESTORE_INVALID")
                    target[ref] = restored.trades[row[1]]
        if any(order.ref in self.orders for order in originals.values()):
            _error("RESTORE_NOT_EMPTY")
        events = binding.host.read_execution_events(
            after_sequence=checkpoint.applied_sequence - 1, limit=1
        )
        if (
            not events
            or events[0].sequence != checkpoint.applied_sequence
            or events[0].request_key not in originals
        ):
            _error("RESTORE_INVALID")
        # Validate notification identities, order, exact object references and fee metadata.
        binding.armed, binding.arm_checkpoint = events[0], checkpoint
        try:
            notices = batch["notifications"]
            expected = []
            if metadata["fee"] is not None:
                fee = metadata["fee"]
                if (
                    type(fee) is not dict
                    or fee != notices[0]
                    or fee["kind"] != "fee"
                    or fee["object_key"] not in restored.orders
                    or type(fee["payload"]) is not dict
                    or set(fee["payload"]) != {"trade_key", "delta", "currency", "sequence"}
                ):
                    _error("RESTORE_INVALID")
                payload = fee["payload"]
                if payload["trade_key"] is not None and payload["trade_key"] not in restored.trades:
                    _error("RESTORE_INVALID")
                if (
                    type(payload["delta"]) not in (int, float)
                    or not math.isfinite(payload["delta"])
                    or not _text(payload["currency"])
                    or type(payload["sequence"]) is not int
                    or payload["sequence"] <= 0
                ):
                    _error("RESTORE_INVALID")
                fee_order = restored.orders[fee["object_key"]]
                fee_trade = (
                    None if payload["trade_key"] is None else restored.trades[payload["trade_key"]]
                )
                if (
                    not any(fee_order is order for order in qorders)
                    or fee_applied.get(fee_order.ref) != payload["sequence"]
                    or fee_trades.get(fee_order.ref) is not fee_trade
                ):
                    _error("RESTORE_INVALID")
                expected.append(self._gateway_notice(binding, "fee", 0, fee["object_key"], payload))
            for index, key in enumerate(metadata["orders_quick"]):
                expected.append(self._gateway_notice(binding, "order", index, key, {}))
            for index, key in enumerate(metadata["trades_quick"]):
                expected.append(self._gateway_notice(binding, "trade", index, key, {}))
            if expected != notices:
                _error("RESTORE_INVALID")
            for item in notices:
                if item["kind"] == "order":
                    if (
                        restored.orders[item["object_key"]].notification_id
                        != item["notification_id"]
                    ):
                        _error("RESTORE_INVALID")
                elif item["kind"] == "trade":
                    if (
                        restored.trades[item["object_key"]].notification_id
                        != item["notification_id"]
                    ):
                        _error("RESTORE_INVALID")
            for order in restored.orders.values():
                if not any(
                    original.ref == order.ref and original.data is order.data
                    for original in originals.values()
                ):
                    _error("RESTORE_INVALID")
            for order in qorders:
                if order.ref != originals[events[0].request_key].ref:
                    _error("RESTORE_INVALID")
        except BaseException:
            binding.armed = binding.arm_checkpoint = None
            raise
        # No mutation of Strategy or Broker collections occurs until all checks pass.
        binding.orders = originals
        strategy._orders, strategy._orderspending = orders, orders_pending
        strategy._trades, strategy._tradespending = trade_groups, trades_pending
        strategy.__dict__["_fee_corrections_applied"] = fee_applied
        strategy.__dict__["_fee_correction_trades"] = fee_trades
        for container, name, position in slots:
            container[name] = position
        for order in originals.values():
            self.orders[order.ref] = order
        if batch["status"] == "confirmed":
            strategy.clear()
            binding.armed = binding.arm_checkpoint = None
            return checkpoint
        binding.restored = (metadata, notices, restored, qorders, qtrades)
        binding.receipt = _Receipt(binding, "notifications", checkpoint, batch["batch_id"])
        return checkpoint

    def replay_gateway_notifications(self, strategy):
        binding = self._gateway_binding(strategy, required=True)
        if binding.replaying or binding.active is not None:
            _error("BUSY")
        if binding.fault == "restart_required":
            _error("RESTART_REQUIRED")
        if binding.fault == "retryable":
            snapshot, notices, _, _ = binding.candidate
            checkpoint = binding.host.commit_execution_notification_batch(
                binding.armed.sequence,
                snapshot,
                notices,
                expected_revision=binding.arm_checkpoint.revision,
                expected_applied_sequence=binding.arm_checkpoint.applied_sequence,
            )
            batch = binding.host.load_execution_notification_batch()
            binding.receipt = _Receipt(binding, "notifications", checkpoint, batch["batch_id"])
            binding.fault = None
        if binding.restored is not None:
            metadata, notices, objects, qorders, qtrades = binding.restored
            orders, trades = objects.orders, objects.trades
        elif binding.receipt is not None and binding.candidate is not None:
            snapshot, notices, qorders, qtrades = binding.candidate
            metadata = snapshot["state"]["_gateway_strategy"]
            try:
                _, orders, trades, *_ = self._gateway_graph(binding, qorders, qtrades)
                saved = []
                try:
                    for item in notices:
                        if item["kind"] not in ("order", "trade"):
                            continue
                        objects = orders if item["kind"] == "order" else trades
                        obj = objects[item["object_key"]]
                        saved.append((obj, obj.notification_id, obj.replayed))
                        obj.notification_id, obj.replayed = item["notification_id"], False
                    current, *_ = self._gateway_graph(binding, qorders, qtrades)
                    current["state"]["_gateway_strategy"]["fee"] = metadata["fee"]
                    if _canonical(current) != _canonical(snapshot):
                        _error("PROJECTION_CONFLICT")
                finally:
                    for obj, notification_id, replayed in saved:
                        obj.notification_id, obj.replayed = notification_id, replayed
            except BaseException:
                binding.fault = "restart_required"
                raise
        else:
            _error("NO_PENDING")
        for item in notices:
            if item["kind"] == "order":
                obj = orders[item["object_key"]]
                obj.notification_id, obj.replayed = item["notification_id"], True
            elif item["kind"] == "trade":
                obj = trades[item["object_key"]]
                obj.notification_id, obj.replayed = item["notification_id"], True
        binding.replaying = True
        binding.replay_phase = "fee"
        try:
            fee = metadata["fee"]
            if fee is not None:
                order = orders[fee["object_key"]]
                payload = fee["payload"]
                trade = None if payload["trade_key"] is None else trades[payload["trade_key"]]
                order.notification_id, order.replayed = fee["notification_id"], True
                binding.active = binding.receipt
                try:
                    strategy._notify_fee_correction_inner(
                        order, trade, payload["delta"], payload["currency"]
                    )
                finally:
                    if binding.active is binding.receipt:
                        binding.active = None
                order_id = next(
                    item["notification_id"]
                    for item in notices
                    if item["kind"] == "order" and item["object_key"] == fee["object_key"]
                )
                order.notification_id = order_id
            object.__setattr__(binding.receipt, "phase", "notifications")
            binding.replay_phase = "notifications"
            if metadata["quick"]:
                strategy._notify(qorders=qorders, qtrades=qtrades)
            else:
                strategy._notify()
        finally:
            binding.replaying = False
            binding.replay_phase = None
        return binding.host.load_execution_checkpoint()
