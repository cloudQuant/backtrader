"""Framework Broker projection of SDK-verified reconciliation observations.

SDK owns account and reconciliation facts; the mixin owns framework order,
position and callback state projected into the running Broker.
"""
from __future__ import annotations

import collections
import math
from collections.abc import Mapping
from copy import deepcopy
from decimal import Decimal


class BrokerReconciliationMixin:
    """Bind neutral reconciliation results to Backtrader objects and state."""

    def _begin_execution_reconciliation(self, reason):
        """Latch the generic reopen barrier until two SDK-proven snapshots agree."""
        self._execution_reconciliation_required = True
        self._execution_reconciliation_rounds = 0
        self._execution_reconciliation_consistency_digest = None
        self._execution_reconciliation_snapshot_id = None
        self._execution_reconciliation_event_epoch = 0
        self._execution_reconciliation_round_event_epoch = None
        self._execution_reconciliation_reason = str(reason or "reconciliation_required")

    def _reset_execution_reconciliation_rounds(self, reason):
        self._execution_reconciliation_rounds = 0
        self._execution_reconciliation_consistency_digest = None
        self._execution_reconciliation_snapshot_id = None
        self._execution_reconciliation_round_event_epoch = None
        self._execution_reconciliation_reason = str(reason or "reconciliation_incomplete")

    @staticmethod
    def _neutral_record_value(record, name, default=None):
        """Read one neutral DTO field without inspecting its raw provider payload."""
        from bt_api_py.broker_event_envelope import neutral_record_value

        return neutral_record_value(record, name, default)

    @staticmethod
    def _neutral_decimal(value, *, positive=False):
        from bt_api_py.broker_event_envelope import neutral_decimal

        return neutral_decimal(value, positive=positive)

    @classmethod
    def _neutral_side_value(cls, record):
        from bt_api_py.broker_event_envelope import neutral_record_side

        return neutral_record_side(record, read_value=cls._neutral_record_value)

    @classmethod
    def _order_observation_parts(cls, observation):
        """Return the local envelope fields and neutral SDK order snapshot."""
        local_ref = cls._neutral_record_value(observation, "local_ref")
        client_order_id = cls._neutral_record_value(observation, "client_order_id")
        intent_ref = cls._neutral_record_value(observation, "intent_ref")
        data_name = cls._neutral_record_value(observation, "data_name")
        order_snapshot = cls._neutral_record_value(observation, "order")
        if order_snapshot is None:
            order_snapshot = cls._neutral_record_value(observation, "snapshot")
        if order_snapshot is None:
            order_snapshot = observation
        if (
            type(client_order_id) is not str
            or not client_order_id
            or client_order_id != client_order_id.strip()
            or type(intent_ref) is not str
            or not intent_ref
            or intent_ref != intent_ref.strip()
            or type(data_name) is not str
            or not data_name
            or data_name != data_name.strip()
        ):
            return None, None, None, None, None
        return local_ref, client_order_id, intent_ref, data_name, order_snapshot

    @classmethod
    def _neutral_order_update(cls, observation):
        local_ref, client_order_id, intent_ref, data_name, record = cls._order_observation_parts(
            observation
        )
        if client_order_id is None:
            return None
        try:
            from bt_api_py.broker_event_envelope import neutral_reconciliation_order_fields
        except ImportError:
            return None
        fields = neutral_reconciliation_order_fields(
            record, read_value=cls._neutral_record_value, read_side=cls._neutral_side_value
        )
        if fields is None:
            return None
        status = {
            "open": "accepted",
            "partially_filled": "partial",
        }.get(fields["status"], fields["status"])
        return {
            "kind": "order",
            "local_ref": local_ref,
            "bt_order_ref": local_ref,
            "client_order_id": client_order_id,
            "intent_ref": intent_ref,
            "order_id": fields["order_id"],
            "symbol": fields["symbol"],
            "data_name": data_name,
            "status": status,
            "terminal_confirmed": fields["terminal_confirmed"],
            "side": fields["side"],
            "size": fields["quantity"],
            "quantity": fields["quantity"],
            "filled_quantity": fields["filled_quantity"],
            "quantity_unit": fields["quantity_unit"],
            "price": fields["price"],
            "average_price": cls._neutral_record_value(record, "average_price"),
        }

    @classmethod
    def _neutral_fill_update(cls, fill, local_ref, client_order_id, intent_ref, data_name):
        if (
            cls._neutral_record_value(fill, "local_ref") != local_ref
            or cls._neutral_record_value(fill, "client_order_id") != client_order_id
            or cls._neutral_record_value(fill, "intent_ref") != intent_ref
            or cls._neutral_record_value(fill, "data_name") != data_name
        ):
            return None
        try:
            from bt_api_py.broker_event_envelope import neutral_reconciliation_fill_fields
        except ImportError:
            return None
        fields = neutral_reconciliation_fill_fields(
            fill, read_value=cls._neutral_record_value, read_side=cls._neutral_side_value
        )
        if fields is None:
            return None
        return {
            "kind": "trade",
            "local_ref": local_ref,
            "bt_order_ref": local_ref,
            "client_order_id": client_order_id,
            "intent_ref": intent_ref,
            "order_id": fields["order_id"],
            "trade_id": fields["fill_id"],
            "symbol": fields["symbol"],
            "data_name": data_name,
            "side": fields["side"],
            "size": fields["quantity"],
            "quantity": fields["quantity"],
            "quantity_unit": fields["quantity_unit"],
            "price": fields["price"],
            "fee": fields["fee"],
            "fee_currency": fields["fee_currency"],
            "fee_unit": fields["fee_unit"],
            "timestamp": cls._neutral_record_value(fill, "timestamp"),
        }

    def _reconciliation_positions_match(self, rows):
        if type(rows) not in (list, tuple):
            return False
        expected = {}
        instruments_by_data = {}
        data_by_instrument = {}
        for row in rows:
            try:
                from bt_api_py.broker_event_envelope import neutral_reconciliation_position_fields
            except ImportError:
                return False
            fields = neutral_reconciliation_position_fields(
                row, read_value=self._neutral_record_value, read_decimal=self._neutral_decimal
            )
            if fields is None:
                return False
            data_name, instrument_ref, side, quantity, unit, average_price = fields
            previous_instrument = instruments_by_data.setdefault(data_name, instrument_ref)
            previous_data = data_by_instrument.setdefault(instrument_ref, data_name)
            if previous_instrument != instrument_ref or previous_data != data_name:
                return False
            known_unit = self._position_quantity_units.get(data_name)
            if known_unit is None or known_unit != unit:
                return False
            price = self._neutral_decimal(average_price)
            if quantity != 0 and (price is None or price <= 0):
                return False
            key = (data_name, side)
            if key in expected:
                return False
            expected[key] = (quantity, price or Decimal("0"), unit)

        if self._is_dual_side_mode():
            if any(side == "net" for _, side in expected):
                return False
            local = {}
            for side, store in (("long", self.long_positions), ("short", self.short_positions)):
                for data_name, position in store.items():
                    local[(str(data_name), side)] = (
                        self._neutral_decimal(position.size or 0) or Decimal("0"),
                        self._neutral_decimal(position.price or 0) or Decimal("0"),
                        self._position_quantity_units.get(str(data_name)),
                    )
        else:
            if any(side != "net" for _, side in expected):
                return False
            local = {
                (str(data_name), "net"): (
                    self._neutral_decimal(position.size or 0) or Decimal("0"),
                    self._neutral_decimal(position.price or 0) or Decimal("0"),
                    self._position_quantity_units.get(str(data_name)),
                )
                for data_name, position in self.positions.items()
            }

        for key in set(expected) | set(local):
            wanted = expected.get(key, (Decimal("0"), Decimal("0"), self._position_quantity_units.get(key[0])))
            actual = local.get(key, (Decimal("0"), Decimal("0"), self._position_quantity_units.get(key[0])))
            if wanted[2] is None or actual[2] != wanted[2]:
                return False
            if not math.isclose(float(wanted[0]), float(actual[0]), rel_tol=1e-10, abs_tol=1e-10):
                return False
            if wanted[0] != 0 and not math.isclose(
                float(wanted[1]), float(actual[1]), rel_tol=1e-9, abs_tol=1e-9
            ):
                return False
        return True

    def _apply_neutral_reconciliation_records(self, snapshot):
        """Map SDK-verified records to BT orders and compare the position book."""
        observations = snapshot.get("orders")
        fills = snapshot.get("fills")
        positions = snapshot.get("positions")
        if (
            type(observations) not in (list, tuple)
            or type(fills) not in (list, tuple)
            or type(positions) not in (list, tuple)
        ):
            return False, "reconciliation_records_missing"

        order_bindings = {}
        updates = []
        for observation in observations:
            update = self._neutral_order_update(observation)
            local_ref, client_order_id, intent_ref, data_name, order_record = (
                self._order_observation_parts(observation)
            )
            if update is None:
                return False, "order_observation_incomplete"
            if type(local_ref) is not int or local_ref <= 0:
                if update["terminal_confirmed"] is not True:
                    return False, "order_correlation_unresolved"
                order = None
            else:
                order = self.orders.get(local_ref)
                if order is None:
                    if update["terminal_confirmed"] is not True:
                        return False, "order_correlation_unresolved"
                elif self._position_key(order.data) != data_name:
                    return False, "order_feed_binding_mismatch"
                elif update["side"] != ("buy" if order.isbuy() else "sell"):
                    return False, "order_side_mismatch"
                elif self._neutral_decimal(update["quantity"], positive=True) != self._neutral_decimal(
                    abs(order.size), positive=True
                ):
                    return False, "order_quantity_mismatch"
            neutral_order_id = self._neutral_record_value(order_record, "order_id")
            instrument_ref = self._neutral_record_value(order_record, "instrument_ref")
            intent_order_id = (str(instrument_ref or ""), str(neutral_order_id or ""))
            if not intent_order_id[0] or not intent_order_id[1] or intent_order_id in order_bindings:
                return False, "order_observation_ambiguous"
            update["intent_ref"] = intent_ref
            update["instrument_ref"] = self._neutral_record_value(order_record, "instrument_ref")
            order_bindings[intent_order_id] = {
                "order": order,
                "client_order_id": client_order_id,
                "intent_ref": intent_ref,
                "local_ref": local_ref,
                "data_name": data_name,
                "record": order_record,
                "update": update,
            }
            if order is not None:
                updates.append((order, update))

        fill_updates = []
        filled_totals = collections.defaultdict(Decimal)
        seen_fill_ids = set()
        for fill in fills:
            fill_order_id = self._neutral_record_value(fill, "order_id")
            fill_instrument_ref = self._neutral_record_value(fill, "instrument_ref")
            fill_key = (str(fill_instrument_ref or ""), str(fill_order_id or ""))
            binding = (
                order_bindings.get(fill_key)
                if fill_order_id not in (None, "")
                else None
            )
            if binding is None:
                return False, "fill_correlation_unresolved"
            fill_id = self._neutral_record_value(fill, "fill_id")
            fill_quantity = self._neutral_decimal(self._neutral_record_value(fill, "quantity"), positive=True)
            fill_price = self._neutral_decimal(self._neutral_record_value(fill, "price"), positive=True)
            parent = binding["record"]
            if (
                type(fill_id) is not str
                or not fill_id
                or fill_id in seen_fill_ids
                or self._neutral_record_value(fill, "client_order_id") != binding["client_order_id"]
                or self._neutral_record_value(fill, "intent_ref") != binding["intent_ref"]
                or self._neutral_record_value(fill, "local_ref") != binding["local_ref"]
                or self._neutral_record_value(fill, "data_name") != binding["data_name"]
                or self._neutral_record_value(fill, "instrument_ref")
                != self._neutral_record_value(parent, "instrument_ref")
                or self._neutral_record_value(fill, "symbol")
                != self._neutral_record_value(parent, "symbol")
                or self._neutral_record_value(fill, "side") != self._neutral_record_value(parent, "side")
                or self._neutral_record_value(fill, "quantity_unit")
                != self._neutral_record_value(parent, "quantity_unit")
                or fill_quantity is None
                or fill_price is None
            ):
                return False, "fill_identity_or_quantity_mismatch"
            seen_fill_ids.add(fill_id)
            filled_totals[fill_key] += fill_quantity
            update = self._neutral_fill_update(
                fill,
                binding["local_ref"],
                binding["client_order_id"],
                binding["intent_ref"],
                binding["data_name"],
            )
            if update is None:
                return False, "fill_observation_incomplete"
            if binding["order"] is not None:
                fill_updates.append((binding["order"], update))

        for order_id, binding in order_bindings.items():
            expected = self._neutral_decimal(
                self._neutral_record_value(binding["record"], "filled_quantity")
            )
            if expected is None or expected != filled_totals[order_id]:
                return False, "order_fill_coverage_mismatch"
            status = binding["update"]["status"]
            quantity = self._neutral_decimal(binding["update"]["quantity"], positive=True)
            if status == "accepted" and expected != 0:
                return False, "open_order_has_fill"
            if status == "partial" and not (0 < expected < quantity):
                return False, "partial_order_fill_mismatch"
            if status == "completed" and expected != quantity:
                return False, "completed_order_fill_mismatch"

        for order, update in fill_updates:
            outcome = self._apply_trade_update(update, defer_unmatched=False)
            if outcome not in {"applied", "ignored"}:
                return False, "fill_projection_unresolved"
        for order, update in updates:
            self._apply_order_update(update, from_query=True)
        if self._pending_trade_updates:
            return False, "pending_trade_updates"
        if any(
            order.alive() and bool(self._order_info_get(order, "execution_unknown", False))
            for order in self.orders.values()
        ):
            return False, "local_order_not_terminal"
        if not self._reconciliation_positions_match(positions):
            return False, "position_snapshot_mismatch"
        return True, None

    def get_execution_reconciliation_state(self):
        """Return the provider-neutral execution reconciliation barrier state."""
        return {
            "required": bool(self._execution_reconciliation_required),
            "complete": not self._execution_reconciliation_required,
            "consecutive_complete_rounds": int(self._execution_reconciliation_rounds),
            "required_rounds": 2,
            "consistency_digest": self._execution_reconciliation_consistency_digest,
            "snapshot_id": self._execution_reconciliation_snapshot_id,
            "event_epoch": self._execution_reconciliation_event_epoch,
            "reason": self._execution_reconciliation_reason,
        }

    def record_reconciliation(self, snapshot):
        """Advance the reopen barrier only from SDK-proven neutral snapshots."""
        if not isinstance(snapshot, Mapping) or snapshot.get("complete") is not True:
            self._reset_execution_reconciliation_rounds("reconciliation_evidence_incomplete")
            return self.get_execution_reconciliation_state()
        if snapshot.get("safe_to_resume") is not True:
            reason = snapshot.get("reason")
            self._reset_execution_reconciliation_rounds(
                reason if isinstance(reason, str) and reason else "reconciliation_not_safe"
            )
            return self.get_execution_reconciliation_state()
        consistency_digest = snapshot.get("consistency_digest")
        snapshot_id = snapshot.get("snapshot_id")
        if (
            type(consistency_digest) is not str
            or not consistency_digest
            or consistency_digest != consistency_digest.strip()
            or type(snapshot_id) is not str
            or not snapshot_id
            or snapshot_id != snapshot_id.strip()
        ):
            self._reset_execution_reconciliation_rounds("reconciliation_proof_incomplete")
            return self.get_execution_reconciliation_state()
        if self._pending_trade_updates:
            self._reset_execution_reconciliation_rounds("pending_trade_updates")
            return self.get_execution_reconciliation_state()

        same_snapshot = (
            self._execution_reconciliation_consistency_digest == consistency_digest
            and self._execution_reconciliation_round_event_epoch == self._execution_reconciliation_event_epoch
        )
        if same_snapshot and self._execution_reconciliation_snapshot_id == snapshot_id:
            self._execution_reconciliation_reason = "reconciliation_snapshot_replayed"
            return self.get_execution_reconciliation_state()
        self._execution_reconciliation_rounds = self._execution_reconciliation_rounds + 1 if same_snapshot else 1
        self._execution_reconciliation_consistency_digest = consistency_digest
        self._execution_reconciliation_snapshot_id = snapshot_id
        self._execution_reconciliation_round_event_epoch = self._execution_reconciliation_event_epoch
        self._execution_reconciliation_reason = "awaiting_second_consistent_snapshot"
        if self._execution_reconciliation_rounds < 2:
            return self.get_execution_reconciliation_state()

        mapped, reason = self._apply_neutral_reconciliation_records(snapshot)
        if not mapped:
            self._reset_execution_reconciliation_rounds(reason or "reconciliation_mapping_failed")
            return self.get_execution_reconciliation_state()
        self._execution_reconciliation_required = False
        self._execution_reconciliation_reason = "two_sdk_verified_snapshots_agree"
        return self.get_execution_reconciliation_state()

    def reconcile_execution(self, *, timeout=5.0):
        """Read one provider-neutral, SDK-verified execution snapshot."""
        method = getattr(self.store, "reconciliation_snapshot", None)
        if not callable(method):
            self._reset_execution_reconciliation_rounds("reconciliation_unsupported")
            return self.get_execution_reconciliation_state()
        try:
            snapshot = method(timeout=timeout)
        except Exception as exc:
            from .btapibroker import _safe_log

            _safe_log("warning", "btapibroker: execution snapshot failed")
            self._sanitize_exception(exc)
            self._reset_execution_reconciliation_rounds(
                self._safe_exception_code(exc, "reconciliation_failed")
            )
            return self.get_execution_reconciliation_state()
        state = self.record_reconciliation(snapshot)
        if isinstance(snapshot, Mapping):
            state["snapshot"] = deepcopy(self._redact_runtime_value(snapshot))
        return state

    def request_reconciliation(self, callback=None, *, correlation=None, timeout=5.0):
        """Queue provider-neutral reconciliation and deliver on the Broker thread."""
        if callback is not None and not callable(callback):
            return {"queued": False, "error_code": "reconciliation_callback_not_callable"}
        callbacks = [callback] if callback is not None else []
        if callback is None:
            cerebro = getattr(self, "cerebro", None)
            for strategy in getattr(cerebro, "runningstrats", ()) or ():
                notifier = getattr(strategy, "notify_reconciliation", None)
                if callable(notifier):
                    callbacks.append(notifier)
        for notifier in callbacks:
            if notifier not in self._execution_reconciliation_callbacks:
                self._execution_reconciliation_callbacks.append(notifier)
        if self._execution_reconciliation_pending:
            return {"queued": True, "status": "already_pending"}
        method = getattr(self.store, "enqueue_reconciliation", None)
        if not callable(method):
            self._execution_reconciliation_callbacks.clear()
            return {"queued": False, "error_code": "reconciliation_unsupported"}
        try:
            receipt = method(correlation=correlation, timeout=max(float(timeout), 0.0))
        except Exception as exc:
            from .btapibroker import _safe_log

            _safe_log("warning", "btapibroker: reconciliation enqueue failed")
            self._sanitize_exception(exc)
            self._execution_reconciliation_callbacks.clear()
            return {
                "queued": False,
                "error_code": self._safe_exception_code(exc, "reconciliation_request_failed"),
            }
        safe_receipt = deepcopy(self._redact_runtime_value(receipt))
        self._execution_reconciliation_pending = bool(
            isinstance(safe_receipt, dict) and safe_receipt.get("queued") is True
        )
        if not self._execution_reconciliation_pending:
            self._execution_reconciliation_callbacks.clear()
        return safe_receipt

    def get_last_reconciliation_result(self):
        """Return the most recent callback-safe result without issuing a read."""
        return deepcopy(self._redact_runtime_value(self._last_execution_reconciliation_result))

    def _reconciliation_callback_snapshot(self, snapshot, state):
        """Attach BT-local diagnostics without adding provider-specific evidence."""
        result = deepcopy(self._redact_runtime_value(snapshot))
        local_active = sum(1 for order in self.orders.values() if order.alive())
        local_unknown = sum(
            1
            for order in self.orders.values()
            if bool(self._order_info_get(order, "execution_unknown", False))
        )
        result.update(
            local_active_order_count=local_active,
            local_unknown_order_count=local_unknown,
            broker_reconciliation_state=deepcopy(state),
        )
        return result
