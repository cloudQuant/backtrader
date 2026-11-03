"""Backtrader order and position projection for service recovery.

The SDK owns neutral recovery contracts and the durable journal. This mixin
owns only Broker order/position restoration and notification bindings.
"""
from __future__ import annotations

import datetime as _dt
import math
from collections.abc import Mapping
from copy import copy
from decimal import Decimal, InvalidOperation

from ..order import BuyOrder, OrderBase, OrderData, SellOrder
from ..position import Position
from ..utils.dateintern import date2num


class ServiceRecoveryBrokerMixin:
    """Restore framework orders and dispatch durable recovery notifications."""

    def _bind_live_recovery_order(self, order):
        """Bind this live Strategy order to its durable intent identity."""

        intent_id = self._order_info_get(order, "managed_intent_id")
        if not isinstance(intent_id, str) or not intent_id:
            self._fence_service_execution_recovery(order, "recovery_intent_identity_missing")
        order.addinfo(service_execution_recovery_managed=True)
        self._recovery_orders_by_intent[intent_id] = order

    def _defer_service_execution_recovery_snapshot_notification(self, order):
        """Hold the snapshot notice until older durable receipts are queued."""

        intent_id = self._order_info_get(order, "managed_intent_id")
        if not isinstance(intent_id, str) or not intent_id:
            self._fence_service_execution_recovery(order, "recovery_intent_identity_missing")
        pending = self._recovery_pending_snapshot_notifications
        existing = pending.get(intent_id)
        if existing is not None:
            if existing.ref != order.ref:
                self._fence_service_execution_recovery(
                    order, "recovery_duplicate_order_binding"
                )
            return
        snapshot = order.clone()
        snapshot.info = copy(order.info)
        pending[intent_id] = snapshot

    def _flush_service_execution_recovery_snapshot_notifications(
        self, *, before_sequence=None, startup_cursor=None
    ):
        """Queue snapshots only after receipts at or before each order's cut."""

        pending = self._recovery_pending_snapshot_notifications
        startup_threshold = startup_cursor if type(startup_cursor) is int else 0
        eligible = []
        for insertion_order, (intent_id, snapshot) in enumerate(tuple(pending.items())):
            if intent_id not in self._recovery_orders_by_intent:
                continue
            threshold = startup_threshold
            snapshot_sequence = self._order_info_get(
                snapshot, "service_execution_recovery_snapshot_sequence"
            )
            if type(snapshot_sequence) is int and snapshot_sequence >= 0:
                threshold = max(threshold, snapshot_sequence)
            if before_sequence is not None and before_sequence <= threshold:
                continue
            eligible.append((threshold, insertion_order, intent_id, snapshot))
        for _threshold, _insertion_order, intent_id, snapshot in sorted(eligible):
            self.notify(snapshot, recovery_restore_only=True)
            pending.pop(intent_id, None)

    def _restore_service_execution_order(self, order, response):
        """Restore only order scalars; never replay snapshot fills into Broker state."""

        adapter = getattr(self._service_execution_session, "adapter", None)
        intent_id = self._order_info_get(order, "managed_intent_id")
        row = response.get("order_state") if isinstance(response, Mapping) else None
        if (
            adapter is None
            or not isinstance(intent_id, str)
            or not isinstance(row, Mapping)
            or response.get("intent_id") != intent_id
            or row.get("intent_id") != intent_id
            or response.get("submit_fingerprint") != row.get("submit_fingerprint")
        ):
            self._fence_service_execution_recovery(order, "recovery_order_binding_invalid")
        if type(row.get("review_required")) is not bool:
            self._fence_service_execution_recovery(
                order, "recovery_order_review_requirement_unavailable"
            )
        try:
            manifest = adapter.recovery_manifest(intent_id)
        except Exception:
            self._fence_service_execution_recovery(order, "recovery_order_manifest_unavailable")
        if (
            not isinstance(manifest, Mapping)
            or manifest.get("submit_fingerprint") != row.get("submit_fingerprint")
            or manifest.get("recovery_binding")
            != {
                "tradeid": getattr(order, "tradeid", None),
                "data_name": self._position_key(order.data),
            }
        ):
            self._fence_service_execution_recovery(order, "recovery_order_manifest_mismatch")
        quantity = self._recovery_number(row.get("quantity"), nonnegative=True)
        if quantity is None or abs(quantity - abs(float(order.size))) > 1e-12:
            self._fence_service_execution_recovery(order, "recovery_order_quantity_mismatch")
        manifest_payload = manifest.get("submit_payload")
        expected_side = "BUY" if order.isbuy() else "SELL"
        if not isinstance(manifest_payload, Mapping) or manifest_payload.get("side") != expected_side:
            self._fence_service_execution_recovery(order, "recovery_order_side_mismatch")
        snapshot_sequence = row.get("latest_source_sequence")
        if type(snapshot_sequence) is not int or snapshot_sequence < 0:
            self._fence_service_execution_recovery(order, "recovery_order_snapshot_cut_invalid")
        self._bind_live_recovery_order(order)
        self._set_service_recovery_order_scalars(order, row)
        order.addinfo(service_execution_recovery_snapshot_sequence=snapshot_sequence)

    @staticmethod
    def _recovery_number(value, *, nonnegative=False):
        if isinstance(value, bool) or value in (None, ""):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(number) or (nonnegative and number < 0):
            return None
        return number

    def _set_service_recovery_order_scalars(self, order, row):
        """Apply safe snapshot/event facts without creating execution bits."""

        states = {
            "PENDING_ADMISSION": order.Submitted,
            "PENDING_DISPATCH": order.Submitted,
            "DISPATCHING": order.Submitted,
            "ACKED": order.Accepted,
            "PARTIALLY_FILLED": order.Partial,
            "FILLED": order.Completed,
            "CANCELLED": order.Canceled,
            "REJECTED": order.Rejected,
            "BLOCKED": order.Rejected,
            "UNKNOWN": order.Submitted,
        }
        state = row.get("state")
        if state not in states:
            self._fence_service_execution_recovery(order, "recovery_order_state_invalid")
        filled = self._recovery_number(row.get("filled_quantity"), nonnegative=True)
        quantity = self._recovery_number(row.get("quantity"), nonnegative=True)
        if filled is None or quantity is None or filled > quantity + 1e-12:
            self._fence_service_execution_recovery(order, "recovery_order_fill_invalid")
        if getattr(order.executed, "exbits", ()):
            self._fence_service_execution_recovery(order, "recovery_restore_order_has_local_fills")
        sign = 1.0 if order.isbuy() else -1.0
        order.status = states[state]
        order.broker = self
        order.executed.size = sign * filled
        order.executed.remsize = float(order.size) - order.executed.size
        average_price = self._recovery_number(row.get("average_price"), nonnegative=True)
        # Always replace the scalar. In a historical notification clone, a
        # missing as-of-event average must not inherit the later snapshot's
        # execution price.
        order.executed.price = average_price if average_price is not None else 0.0
        commission = self._recovery_number(row.get("cumulative_commission"))
        order.executed.comm = commission if commission is not None else 0.0
        order.addinfo(
            service_execution_recovery_managed=True,
            service_execution_recovery_state=state,
            service_execution_recovery_trade_history_unavailable=bool(filled),
            service_execution_recovery_average_price=average_price,
            execution_time_unavailable=bool(filled),
            execution_price_unavailable=bool(filled and average_price is None),
            execution_commission_unavailable=bool(filled and commission is None),
            execution_pnl_unavailable=bool(filled),
            recovery_review_required=row.get("review_required") is True,
            execution_unknown=(
                state in ("UNKNOWN", "BLOCKED")
                or row.get("review_required") is True
            ),
            recovery_latest_source_sequence=row.get("latest_source_sequence"),
            recovery_latest_source_event_id=row.get("latest_source_event_id"),
        )
        provider_order_id = row.get("provider_order_id")
        if isinstance(provider_order_id, str) and provider_order_id:
            order.addinfo(external_order_id=provider_order_id)
        else:
            order.info.pop("external_order_id", None)
        commission_currency = row.get("cumulative_commission_currency")
        if isinstance(commission_currency, str) and commission_currency:
            order.addinfo(cumulative_commission_currency=commission_currency)
        else:
            order.info.pop("cumulative_commission_currency", None)
        reason = row.get("unknown_reason_code")
        if isinstance(reason, str) and reason:
            order.addinfo(error_code=reason)
        else:
            order.info.pop("error_code", None)
        # Recovery pages carry reason codes, never free-form error messages.
        order.info.pop("error_msg", None)

    def _process_service_execution_recovery(self):
        """Project only matched, pending durable receipts onto rebound Orders."""

        if getattr(self, "_service_execution_recovery_failed", False):
            return
        session = self._service_execution_session
        adapter = getattr(session, "adapter", None)
        if adapter is None:
            self._fence_service_execution_recovery(None, "recovery_adapter_unavailable")
        startup_cursor = adapter.recovery_startup_cursor
        if type(startup_cursor) is not int or startup_cursor < 0:
            self._fence_service_execution_recovery(None, "recovery_startup_cursor_invalid")
        ordered_history = []
        for receipt in adapter.recovery_history():
            if not isinstance(receipt, Mapping) or receipt.get("matched_manifest") is not True:
                continue
            receipt_id = receipt.get("receipt_id")
            event = receipt.get("event")
            sequence = receipt.get("sequence")
            if (
                not isinstance(receipt_id, str)
                or not isinstance(event, Mapping)
                or type(sequence) is not int
                or sequence < 0
            ):
                self._fence_service_execution_recovery(None, "recovery_receipt_invalid")
            ordered_history.append((sequence, receipt_id, receipt))
        ordered_history.sort(key=lambda item: (item[0], item[1]))
        if len({sequence for sequence, _receipt_id, _receipt in ordered_history}) != len(
            ordered_history
        ):
            self._fence_service_execution_recovery(None, "recovery_receipt_sequence_duplicate")
        ordered_receipts = []
        event_facts_by_receipt = {}
        cumulative_by_intent = {}
        for sequence, receipt_id, receipt in ordered_history:
            event = receipt["event"]
            intent_id = event.get("intent_id")
            if not isinstance(intent_id, str) or not intent_id:
                self._fence_service_execution_recovery(None, "recovery_receipt_intent_invalid")
            facts = dict(
                cumulative_by_intent.get(
                    intent_id,
                    {
                        "filled_quantity": "0",
                        "average_price": None,
                        "cumulative_commission": "0",
                        "cumulative_commission_currency": None,
                        "provider_order_id": None,
                    },
                )
            )
            details = event.get("details")
            if isinstance(details, Mapping) and "filled_quantity" in details:
                facts.update(
                    filled_quantity=details.get("filled_quantity"),
                    average_price=details.get("average_price"),
                    cumulative_commission=details.get("cumulative_commission"),
                    cumulative_commission_currency=details.get(
                        "cumulative_commission_currency"
                    ),
                    provider_order_id=details.get("provider_order_id"),
                )
                cumulative_by_intent[intent_id] = facts
            event_facts_by_receipt[receipt_id] = facts
            if receipt.get("callback_pending") is not True:
                continue
            if receipt_id not in self._recovery_queued_receipts:
                ordered_receipts.append((sequence, receipt_id, receipt))
        for sequence, receipt_id, receipt in ordered_receipts:
            self._flush_service_execution_recovery_snapshot_notifications(
                before_sequence=sequence, startup_cursor=startup_cursor
            )
            event = receipt.get("event")
            intent_id = event.get("intent_id")
            order = self._recovery_orders_by_intent.get(intent_id)
            if order is None and self._uses_service_execution_recovery_v2():
                # A fresh process never re-submits the durable intent, so the
                # pending callback outlives its live Strategy Order. Rebuild the
                # durable order identity; the V2 replay branch below remains the
                # only path that projects the already-checkpointed Trade.
                order = self._reconstruct_service_execution_recovery_order(
                    intent_id, receipt
                )
            if order is None:
                continue
            if self._order_info_get(order, "managed_intent_id") != intent_id:
                self._fence_service_execution_recovery(order, "recovery_order_intent_mismatch")
            callback = adapter.claim_recovery_callback(receipt_id)
            if callback is None:
                continue
            if (
                callback.receipt_id != receipt_id
                or callback.intent_id != intent_id
                or callback.sequence != sequence
                or callback.event != event
            ):
                self._fence_service_execution_recovery(order, "recovery_callback_claim_mismatch")
            try:
                if self._uses_service_execution_recovery_v2():
                    projection = adapter.recovery_fill_projection(receipt_id)
                    if not isinstance(projection, Mapping):
                        self._fence_service_execution_recovery(
                            order, "recovery_v2_fill_projection_missing"
                        )
                    projection_status = projection.get("status")
                    if projection_status == "READY_TO_PROJECT":
                        if receipt_id in self._recovery_applied_receipts:
                            self._fence_service_execution_recovery(
                                order, "recovery_v2_uncheckpointed_fill_replay"
                            )
                        self._apply_service_execution_recovery_v2_event(
                            order, receipt_id, event, projection
                        )
                        self._recovery_applied_receipts.add(receipt_id)
                        notification = order
                    elif projection_status == "READY":
                        notification = order.clone()
                        notification.info = copy(order.info)
                        self._set_service_recovery_order_scalars(
                            notification,
                            self._recovery_order_row_from_event(
                                order, event, event_facts_by_receipt[receipt_id]
                            ),
                        )
                        fill = projection.get("fill")
                        if not isinstance(fill, Mapping):
                            self._fence_service_execution_recovery(
                                order, "recovery_v2_ready_fill_missing"
                            )
                        match_time_ns = fill.get("match_time_ns")
                        match_datenum = date2num(
                            self._service_recovery_match_datetime(match_time_ns)
                        )
                        event_context = projection.get("event_context")
                        if (
                            not isinstance(event_context, Mapping)
                            or type(event_context.get("bar_index")) is not int
                            or event_context.get("bar_index") < 1
                            or not math.isfinite(match_datenum)
                            or match_datenum <= 0.0
                        ):
                            self._fence_service_execution_recovery(
                                order, "recovery_v2_ready_time_invalid"
                            )
                        notification.executed.dt = match_datenum
                        notification.addinfo(
                            service_execution_recovery_trade_history_unavailable=False,
                            service_execution_recovery_receipt_id=receipt_id,
                            service_execution_recovery_fill_id=fill.get("fill_id"),
                            service_execution_recovery_match_time_ns=match_time_ns,
                            service_execution_recovery_v2_match_datenum=match_datenum,
                            service_execution_recovery_v2_trade_bar_index=event_context[
                                "bar_index"
                            ],
                            service_execution_recovery_v2_trade_time_verified=True,
                            execution_time_unavailable=False,
                            execution_pnl_unavailable=False,
                        )
                    else:
                        self._fence_service_execution_recovery(
                            order, "recovery_v2_trade_projection_unavailable"
                        )
                    self._recovery_queued_receipts.add(receipt_id)
                    self.notify(
                        notification,
                        recovery_receipt_id=receipt_id,
                        recovery_fill_projection=projection,
                    )
                    continue
                snapshot_sequence = self._order_info_get(
                    order, "service_execution_recovery_snapshot_sequence"
                )
                order_cut = max(
                    startup_cursor,
                    snapshot_sequence
                    if type(snapshot_sequence) is int and snapshot_sequence >= 0
                    else 0,
                )
                if sequence <= order_cut or receipt_id in self._recovery_applied_receipts:
                    notification = order.clone()
                    notification.info = copy(order.info)
                    self._set_service_recovery_order_scalars(
                        notification,
                        self._recovery_order_row_from_event(
                            order, event, event_facts_by_receipt[receipt_id]
                        ),
                    )
                else:
                    self._apply_service_execution_recovery_event(order, event)
                    self._recovery_applied_receipts.add(receipt_id)
                    notification = order
                self._recovery_queued_receipts.add(receipt_id)
                self.notify(
                    notification,
                    recovery_receipt_id=receipt_id,
                    recovery_restore_only=True,
                )
            except Exception:
                self._fence_service_execution_recovery(
                    order, "recovery_receipt_projection_failed"
                )
        self._flush_service_execution_recovery_snapshot_notifications(
            startup_cursor=startup_cursor
        )

    def _reconstruct_service_execution_recovery_order(self, intent_id, receipt):
        """Rebuild the durable identity of one pending V2 callback's order.

        A restart can hold a pending fill callback for an intent whose Strategy
        never re-submitted it in this process. The replay order carries only
        immutable identity plus the manifest economics; the fill projection
        stays the sole authority for what the Strategy projects.
        """

        adapter = getattr(self._service_execution_session, "adapter", None)
        binding = receipt.get("binding")
        if (
            adapter is None
            or not isinstance(binding, Mapping)
            or frozenset(binding) != {"data_name", "tradeid"}
        ):
            self._fence_service_execution_recovery(
                None, "recovery_v2_replay_binding_invalid"
            )
        data_name = binding.get("data_name")
        tradeid = binding.get("tradeid")
        if (
            not isinstance(data_name, str)
            or not data_name
            or type(tradeid) is not int
            or tradeid < 0
        ):
            self._fence_service_execution_recovery(
                None, "recovery_v2_replay_binding_invalid"
            )
        feed = self.service_execution_recovery_feed(data_name)
        if feed is None or getattr(feed, "_compensate", None) is not None:
            self._fence_service_execution_recovery(
                None, "recovery_v2_replay_feed_unavailable"
            )
        try:
            manifest = adapter.recovery_manifest(intent_id)
        except Exception:
            self._fence_service_execution_recovery(
                None, "recovery_v2_replay_manifest_unavailable"
            )
        payload = manifest.get("submit_payload") if isinstance(manifest, Mapping) else None
        if (
            not isinstance(payload, Mapping)
            or payload.get("intent_id") != intent_id
            or payload.get("order_type") != "MARKET"
            or payload.get("time_in_force") != "FOK"
            or payload.get("price") is not None
            or payload.get("position_effect") != "OPEN"
            or payload.get("reduce_only") is not False
            or payload.get("side") not in {"BUY", "SELL"}
            or not isinstance(payload.get("instrument"), str)
            or not payload.get("instrument")
        ):
            self._fence_service_execution_recovery(
                None, "recovery_v2_replay_manifest_invalid"
            )
        manifest_binding = manifest.get("recovery_binding")
        if (
            not isinstance(manifest_binding, Mapping)
            or manifest_binding.get("data_name") != data_name
            or manifest_binding.get("tradeid") != tradeid
        ):
            self._fence_service_execution_recovery(
                None, "recovery_v2_replay_binding_mismatch"
            )
        try:
            quantity = Decimal(str(payload.get("quantity")))
        except (InvalidOperation, TypeError, ValueError):
            self._fence_service_execution_recovery(
                None, "recovery_v2_replay_quantity_invalid"
            )
        if not quantity.is_finite() or quantity <= 0:
            self._fence_service_execution_recovery(
                None, "recovery_v2_replay_quantity_invalid"
            )
        strategy = self._service_execution_recovery_strategy
        if strategy is None:
            self._fence_service_execution_recovery(
                None, "recovery_v2_replay_strategy_missing"
            )
        is_buy = payload.get("side") == "BUY"
        order_class = BuyOrder if is_buy else SellOrder
        order = order_class(
            owner=strategy,
            data=feed,
            size=float(quantity) if is_buy else -float(quantity),
            exectype=OrderBase.Market,
            tradeid=tradeid,
        )
        order.broker = self
        order.addcomminfo(self.getcommissioninfo(feed))
        order.addinfo(
            managed_intent_id=intent_id,
            managed_instrument=payload.get("instrument"),
            service_execution_recovery_managed=True,
        )
        self._recovery_orders_by_intent[intent_id] = order
        return order

    @staticmethod
    def _service_recovery_match_datetime(match_time_ns):
        if type(match_time_ns) is not int or match_time_ns <= 0:
            raise ValueError("managed paper match time is invalid")
        seconds, remainder = divmod(match_time_ns, 1_000_000_000)
        value = _dt.datetime.fromtimestamp(seconds, _dt.timezone.utc).replace(tzinfo=None)
        return value + _dt.timedelta(microseconds=remainder // 1_000)

    def _apply_service_execution_recovery_v2_event(
        self, order, receipt_id, event, projection
    ):
        """Apply one exact managed-paper fill to a Backtrader Order once."""

        adapter = self._service_execution_session.adapter
        intent_id = self._order_info_get(order, "managed_intent_id")
        if not isinstance(intent_id, str) or not intent_id or event.get("intent_id") != intent_id:
            self._fence_service_execution_recovery(order, "recovery_v2_intent_mismatch")
        if (
            projection.get("status") != "READY_TO_PROJECT"
            or projection.get("reason") is not None
            or projection.get("trade_state") is not None
            or projection.get("trade_notification") is not None
            or event.get("event_type") != "provider_observation"
            or event.get("state") != "FILLED"
        ):
            self._fence_service_execution_recovery(order, "recovery_v2_source_not_projectable")
        fill = projection.get("fill")
        intent_context = projection.get("intent_context")
        event_context = projection.get("event_context")
        details = event.get("details")
        if not all(isinstance(value, Mapping) for value in (fill, intent_context, event_context, details)):
            self._fence_service_execution_recovery(order, "recovery_v2_source_incomplete")

        from bt_api_py.service_recovery import (
            paper_recovery_fill_identity_matches,
            paper_recovery_fill_shape_matches,
        )
        from bt_api_py.service_recovery_quote import recovery_quote_fill_matches

        expected_event_context_fields = {
            "data_name", "instrument", "bar_index", "datetime_hex", "comminfo",
            "commission_currency", "quote_source_ref", "quote_generation", "quote_cursor",
            "quote_instrument", "quote_as_of_ns",
        }
        if (
            not paper_recovery_fill_shape_matches(fill)
            or frozenset(event_context) != expected_event_context_fields
            or not paper_recovery_fill_identity_matches(fill, event, intent_id)
            or type(event_context.get("bar_index")) is not int
            or event_context.get("bar_index") < 1
            or type(event_context.get("datetime_hex")) is not str
            or not isinstance(event_context.get("comminfo"), Mapping)
            or type(event_context.get("quote_as_of_ns")) is not int
            or event_context.get("quote_as_of_ns") <= 0
        ):
            self._fence_service_execution_recovery(order, "recovery_v2_source_binding_invalid")

        manifest = adapter.recovery_manifest(intent_id)
        stored_context = adapter.recovery_intent_execution_context(intent_id)
        if (
            not isinstance(manifest, Mapping)
            or not isinstance(stored_context, Mapping)
            or dict(stored_context) != dict(intent_context)
        ):
            self._fence_service_execution_recovery(order, "recovery_v2_manifest_unavailable")
        binding = manifest.get("recovery_binding")
        payload = manifest.get("submit_payload")
        quote_binding = intent_context.get("quote_binding")
        if (
            not isinstance(binding, Mapping)
            or not isinstance(payload, Mapping)
            or not isinstance(quote_binding, Mapping)
            or frozenset(quote_binding)
            != {
                "source_ref",
                "generation",
                "cursor",
                "instrument",
                "as_of_ns",
                "data_name",
                "bar_index",
                "datetime_hex",
            }
            or binding.get("data_name") != event_context.get("data_name")
            or binding.get("tradeid") != order.tradeid
            or event_context.get("instrument") != payload.get("instrument")
            or event_context.get("quote_instrument") != payload.get("instrument")
            or not recovery_quote_fill_matches(quote_binding, fill)
            or quote_binding.get("as_of_ns") != event_context.get("quote_as_of_ns")
            or quote_binding.get("data_name") != event_context.get("data_name")
            or quote_binding.get("bar_index") != event_context.get("bar_index")
            or quote_binding.get("datetime_hex") != event_context.get("datetime_hex")
            or event_context.get("quote_source_ref") != fill.get("quote_source_ref")
            or event_context.get("quote_generation") != fill.get("quote_generation")
            or event_context.get("quote_cursor") != fill.get("quote_cursor")
            or event_context.get("commission_currency") != fill.get("commission_currency")
            or event_context.get("comminfo") != intent_context.get("comminfo")
            or intent_context.get("feed", {}).get("data_name") != event_context.get("data_name")
            or intent_context.get("feed", {}).get("instrument") != event_context.get("instrument")
        ):
            self._fence_service_execution_recovery(order, "recovery_v2_binding_changed")

        side = "BUY" if order.isbuy() else "SELL"
        quantity = self._service_recovery_decimal(fill.get("quantity"), positive=True)
        price = self._service_recovery_decimal(fill.get("price"), positive=True)
        commission = self._service_recovery_decimal(fill.get("commission"))
        requested_quantity = self._service_recovery_decimal(payload.get("quantity"), positive=True)
        order_quantity = self._service_recovery_local_decimal(
            abs(order.size), positive=True
        )
        detail_quantity = self._service_recovery_decimal(
            details.get("filled_quantity"), positive=True
        )
        detail_price = self._service_recovery_decimal(details.get("average_price"), positive=True)
        detail_commission = self._service_recovery_decimal(details.get("cumulative_commission"))
        provider_order_id = details.get("provider_order_id")
        adapter_baseline = adapter.recovery_baseline()
        cash_by_currency = (
            adapter_baseline.get("cash_by_currency")
            if isinstance(adapter_baseline, Mapping)
            else None
        )
        actual_comminfo = self._service_recovery_comminfo_context(
            getattr(order, "comminfo", None) or self.getcommissioninfo(order.data)
        )
        if (
            payload.get("side") != side
            or payload.get("position_effect") != "OPEN"
            or payload.get("order_type") != "MARKET"
            or payload.get("time_in_force") != "FOK"
            or payload.get("price") is not None
            or payload.get("reduce_only") is not False
            or quantity != requested_quantity
            or quantity != order_quantity
            or quantity != detail_quantity
            or order.exectype != order.Market
            or order.price is not None
            or price != detail_price
            or commission != detail_commission
            or details.get("cumulative_commission_currency") != fill.get("commission_currency")
            or details.get("source") != "provider"
            or not isinstance(provider_order_id, str)
            or not provider_order_id
            or not isinstance(cash_by_currency, Mapping)
            or fill.get("commission_currency") not in cash_by_currency
            or event_context.get("comminfo") != actual_comminfo
            or event_context.get("data_name") != self._position_key(order.data)
            or event_context.get("instrument")
            != self._order_info_get(order, "managed_instrument")
            or self._is_dual_side_mode()
            or bool(self._order_info_get(order, "reduce_only", False))
            or self._order_info_get(order, "managed_position_effect") != "OPEN"
            or type(quote_binding.get("as_of_ns")) is not int
            or quote_binding.get("as_of_ns") <= 0
            or fill.get("match_time_ns") < quote_binding.get("as_of_ns")
        ):
            self._fence_service_execution_recovery(order, "recovery_v2_order_contract_mismatch")

        positions = adapter_baseline.get("positions")
        if not isinstance(positions, Mapping):
            self._fence_service_execution_recovery(order, "recovery_v2_position_baseline_missing")
        baseline_instrument = self._service_recovery_decimal(
            positions.get(event_context["instrument"], "0")
        )
        signed_quantity = quantity if order.isbuy() else -quantity
        if baseline_instrument != 0:
            self._fence_service_execution_recovery(order, "recovery_v2_trade_baseline_nonflat")

        position_key = self._position_key(order.data)
        live_position = self.positions.get(position_key)
        current_size = (
            Decimal(0)
            if live_position is None
            else self._service_recovery_local_decimal(live_position.size or 0.0)
        )
        position_override = None
        if current_size == signed_quantity:
            if live_position is None or Decimal(str(live_position.price)) != price:
                self._fence_service_execution_recovery(
                    order, "recovery_v2_position_snapshot_conflict"
                )
            # The account snapshot already includes this one fill. Build the
            # OrderExecutionBit from an isolated zero position so the Broker
            # does not book that same owner position a second time.
            position_override = Position()
        elif current_size != 0:
            self._fence_service_execution_recovery(
                order, "recovery_v2_position_snapshot_conflict"
            )

        if getattr(order.executed, "exbits", ()):
            self._fence_service_execution_recovery(order, "recovery_v2_order_has_execution_bits")
        existing_fill = self._service_recovery_local_decimal(
            abs(order.executed.size or 0.0), nonnegative=True
        )
        if existing_fill not in (Decimal(0), quantity):
            self._fence_service_execution_recovery(order, "recovery_v2_order_snapshot_conflict")
        # A snapshot row contains only cumulative scalars. The durable V2
        # receipt is the one authoritative source for the single Trade bit.
        order.executed = OrderData(remsize=order.size)
        order.accept(self)
        match_dt = self._service_recovery_match_datetime(fill["match_time_ns"])
        match_datenum = date2num(match_dt)
        order.addinfo(
            service_execution_recovery_v2_match_datenum=match_datenum,
            service_execution_recovery_v2_trade_bar_index=event_context["bar_index"],
            service_execution_recovery_v2_trade_time_verified=True,
            service_execution_recovery_match_time_ns=fill["match_time_ns"],
            external_order_id=provider_order_id,
        )
        update = {
            "kind": "trade",
            "trade_id": fill["fill_id"],
            "external_order_id": provider_order_id,
            "bt_order_ref": order.ref,
            "data_name": event_context["data_name"],
            "instrument": event_context["instrument"],
            "side": "buy" if order.isbuy() else "sell",
            "position_effect": "OPEN",
            "position_mode": self.get_param("position_mode"),
            "offset": "open",
            "size": float(quantity),
            "price": float(price),
            "commission": float(commission),
            "commission_normalized": True,
            "timestamp": match_dt,
        }
        self._service_execution_recovery_suppress_notifications = True
        try:
            result = self._apply_trade_update(
                update,
                defer_unmatched=False,
                position_override=position_override,
            )
        finally:
            self._service_execution_recovery_suppress_notifications = False
        if result != "applied" or len(order.executed.exbits) != 1:
            self._fence_service_execution_recovery(order, "recovery_v2_fill_not_applied")
        bit = order.executed.exbits[0]
        if (
            Decimal(str(abs(bit.opened))) != quantity
            or Decimal(str(abs(bit.closed))) != 0
            or Decimal(str(abs(order.executed.size))) != quantity
            or abs(float(order.executed.remsize)) > 1e-12
            or order.status != order.Completed
        ):
            self._fence_service_execution_recovery(order, "recovery_v2_fill_projection_invalid")
        order.executed.dt = match_datenum
        bit.dt = match_datenum
        order.addinfo(
            service_execution_recovery_state="FILLED",
            service_execution_recovery_trade_history_unavailable=False,
            service_execution_recovery_receipt_id=receipt_id,
            service_execution_recovery_fill_id=fill["fill_id"],
            service_execution_recovery_match_time_ns=fill["match_time_ns"],
            execution_time_unavailable=False,
            execution_pnl_unavailable=False,
            cumulative_commission_currency=fill["commission_currency"],
        )
        return order

    def _recovery_order_row_from_event(self, order, event, event_facts):
        details = event.get("details") or {}
        return {
            "intent_id": event.get("intent_id"),
            "state": event.get("state"),
            "quantity": str(abs(float(order.size))),
            "filled_quantity": event_facts["filled_quantity"],
            "average_price": event_facts["average_price"],
            "cumulative_commission": event_facts["cumulative_commission"],
            "provider_order_id": event_facts["provider_order_id"],
            "cumulative_commission_currency": details.get(
                "cumulative_commission_currency",
                event_facts["cumulative_commission_currency"],
            ),
            "unknown_reason_code": details.get("reason_code"),
            "review_required": event.get("event_type") == "manual_review_required",
            "latest_source_sequence": event.get("sequence"),
            "latest_source_event_id": event.get("event_id"),
        }

    def _apply_service_execution_recovery_event(self, order, event):
        event_type = event.get("event_type")
        state = event.get("state")
        details = event.get("details") or {}
        fill_event_types = {
            "provider_observation",
            "reconciled_observation",
            "provider_commission_evidence",
            "cancelled_by_cancel_intent",
        }
        states = {
            "PENDING_ADMISSION": order.Submitted,
            "PENDING_DISPATCH": order.Submitted,
            "DISPATCHING": order.Submitted,
            "ACKED": order.Accepted,
            "PARTIALLY_FILLED": order.Partial,
            "FILLED": order.Completed,
            "CANCELLED": order.Canceled,
            "REJECTED": order.Rejected,
            "BLOCKED": order.Rejected,
            "UNKNOWN": order.Submitted,
        }
        if state not in states:
            self._fence_service_execution_recovery(order, "recovery_event_state_invalid")
        if event_type not in fill_event_types:
            order.status = states[state]
            order.broker = self
            order.addinfo(
                service_execution_recovery_state=state,
                execution_unknown=(
                    state == "UNKNOWN"
                    or state == "BLOCKED"
                    or event_type == "manual_review_required"
                ),
                recovery_review_required=(event_type == "manual_review_required"),
                error_code=details.get("reason_code"),
                execution_time_unavailable=True,
            )
            return
        filled = self._recovery_number(details.get("filled_quantity"), nonnegative=True)
        prior_filled = abs(float(order.executed.size or 0.0))
        if filled is None or filled > abs(float(order.size)) + 1e-12 or filled < prior_filled - 1e-12:
            self._fence_service_execution_recovery(order, "recovery_event_fill_regression")
        cumulative_commission = self._recovery_number(details.get("cumulative_commission"))
        previous_commission = self._recovery_number(order.executed.comm)
        currency = details.get("cumulative_commission_currency") or self._order_info_get(
            order, "cumulative_commission_currency"
        )
        if filled > prior_filled + 1e-12:
            average_price = self._recovery_number(details.get("average_price"), nonnegative=True)
            if (
                average_price is None
                or average_price <= 0
                or cumulative_commission is None
                or previous_commission is None
                or self._order_info_get(order, "execution_commission_unavailable", False)
                or not isinstance(currency, str)
                or not currency
            ):
                self._fence_service_execution_recovery(
                    order, "recovery_fill_economics_incomplete"
                )
            adapter = self._service_execution_session.adapter
            baseline = adapter.recovery_baseline()
            cash_by_currency = baseline.get("cash_by_currency") if isinstance(baseline, Mapping) else None
            if not isinstance(cash_by_currency, Mapping) or currency not in cash_by_currency:
                self._fence_service_execution_recovery(
                    order, "recovery_fill_fee_currency_unproven"
                )
            status_by_state = {
                "ACKED": "accepted",
                "PARTIALLY_FILLED": "partial",
                "FILLED": "completed",
                "CANCELLED": "canceled",
                "REJECTED": "rejected",
            }
            status = status_by_state.get(state)
            if status not in {"partial", "completed", "canceled"}:
                self._fence_service_execution_recovery(
                    order, "recovery_fill_state_incompatible"
                )
            update = {
                "kind": "order",
                "bt_order_ref": order.ref,
                "data_name": self._position_key(order.data),
                "side": "buy" if order.isbuy() else "sell",
                "status": status,
                "filled_quantity": details["filled_quantity"],
                "average_price": details["average_price"],
                "cumulative_commission": details["cumulative_commission"],
                "fee_currency": currency,
                "execution_source": "cumulative",
            }
            prior_count = len(order.executed.exbits)
            self._service_execution_recovery_suppress_notifications = True
            try:
                self._apply_order_update(update)
            finally:
                self._service_execution_recovery_suppress_notifications = False
            if (
                abs(float(order.executed.size or 0.0)) + 1e-12 < filled
                or bool(self._order_info_get(order, "ledger_mismatch", False))
                or len(order.executed.exbits) == prior_count
            ):
                self._fence_service_execution_recovery(
                    order, "recovery_fill_not_projected"
                )
            # The v1 SDK does not provide provider execution time. Zero is
            # Backtrader's missing-date sentinel; the strategy is told this
            # receipt is restore-only and no Trade callback is synthesized.
            order.executed.dt = 0.0
            for execution_bit in list(order.executed.exbits)[prior_count:]:
                execution_bit.dt = 0.0
            order.addinfo(
                service_execution_recovery_state=state,
                service_execution_recovery_trade_history_unavailable=True,
                cumulative_commission_currency=currency,
                execution_time_unavailable=True,
                execution_pnl_unavailable=True,
            )
        elif details.get("cumulative_commission") not in (None, ""):
            self._apply_fee_only_correction(order, details["cumulative_commission"], currency)
            order.status = states[state]
        else:
            order.status = states[state]
        order.broker = self
        order.addinfo(
            service_execution_recovery_state=state,
            recovery_latest_source_sequence=event.get("sequence"),
            recovery_latest_source_event_id=event.get("event_id"),
            execution_time_unavailable=True,
        )

    def _apply_fee_only_correction(self, order, cumulative_fee, currency):
        """Apply a late fee: same cumulative quantity, higher provider fee.

        Contract (acceptance report F5): the provider's cumulative fee for
        ``order`` is ``cumulative_fee`` in ``currency``. When it is valid, in
        the order's fee currency and higher than what was booked, the delta
        is added to ``order.executed.comm``, to the provider fee totals the
        strategy ledger books (a fee-only ``apply_execution``), and recorded
        as the next numbered entry of ``order.info["fee_corrections"]``; the
        owning Strategy then moves the delta onto the Trade and calls
        ``notify_fee_correction``. No fill is created. An identical fee is a
        no-op (idempotent redelivery). A lower fee, another currency or an
        unusable value keeps the existing fence. Returns ``"corrected"``,
        ``"unchanged"`` or raises through the fence.
        """
        reported = self._neutral_decimal(cumulative_fee)
        previous = self._neutral_decimal(order.executed.comm)
        prior_currency = self._order_info_get(order, "cumulative_commission_currency")
        valid = (
            reported is not None
            and previous is not None
            and reported >= 0
            and previous >= 0
            and type(currency) is str
            and bool(currency)
            and currency == currency.strip()
            and (prior_currency == currency or (prior_currency is None and previous == 0))
        )
        if not valid or reported < previous:
            self._fence_unprojectable_recovery_fee(order)
        if reported == previous:
            return "unchanged"
        self._book_fee_correction(order, reported - previous, reported, currency)
        order.addinfo(cumulative_commission_currency=currency)
        return "corrected"

    def _book_fee_correction(self, order, delta, cumulative, currency):
        """Record one fee-only correction of ``delta`` on ``order`` (no fill).

        ``order.executed.comm`` moves by ``delta``; the next numbered entry of
        ``order.info["fee_corrections"]`` (``sequence``, ``delta``,
        ``cumulative``, ``currency``) is what the owning Strategy moves onto its
        Trade exactly once; the provider fee totals the strategy ledger books
        grow by ``delta``. ``cumulative`` is the provider's corrected cumulative
        fee of the corrected unit (order or fill).
        """
        order.executed.comm = float(Decimal(str(order.executed.comm or 0)) + delta)
        corrections = list(self._order_info_get(order, "fee_corrections") or ())
        corrections.append(
            {
                "sequence": len(corrections) + 1,
                "delta": str(delta),
                "cumulative": str(cumulative),
                "currency": currency,
            }
        )
        order.addinfo(fee_corrections=tuple(corrections))
        record = getattr(self, "_record_provider_fee", None)
        if callable(record):
            record(order, {"fee_currency": currency}, delta)

    def _fence_unprojectable_recovery_fee(self, order):
        """Fence fee-only corrections until Trade economics can be reconciled."""
        order.addinfo(
            execution_commission_unavailable=True,
            execution_pnl_unavailable=True,
            service_execution_recovery_trade_history_unavailable=True,
            pnl_status="PNL_INCOMPLETE",
        )
        self._fence_service_execution_recovery(
            order, "recovery_fee_correction_without_fill_unsupported"
        )

    def _fence_service_execution_recovery(self, order, reason):
        self._service_execution_recovery_failed = True
        self._trading_enabled = False
        self._startup_ready = False
        if order is not None:
            order.addinfo(
                service_execution_recovery_managed=True,
                service_execution_recovery_error=str(reason),
                execution_unknown=True,
            )
        freeze = getattr(self.store, "freeze_openings", None)
        if callable(freeze):
            freeze("service_execution_recovery_projection_unavailable")
        raise RuntimeError("service execution recovery projection unavailable") from None

    def fail_service_execution_recovery_projection(self, order, reason):
        """Latch the managed recovery fence after a Strategy projection failure."""

        if not self._uses_service_execution_recovery():
            raise RuntimeError("service execution recovery is not active")
        self._fence_service_execution_recovery(order, reason)

    def acknowledge_service_execution_recovery_receipt(self, receipt_id):
        if not self._uses_service_execution_recovery():
            raise RuntimeError("service execution recovery is not active")
        self._service_execution_session.adapter.acknowledge_recovery_callback(receipt_id)
        self._recovery_queued_receipts.discard(receipt_id)

    def release_service_execution_recovery_receipt(self, receipt_id):
        """Permit at-least-once callback retry after a strategy callback fails."""

        self._recovery_queued_receipts.discard(receipt_id)

    def _uses_service_execution_recovery(self):
        session = self._service_execution_session
        return bool(
            session is not None
            and getattr(session, "recovery_journal", None) is not None
            and callable(getattr(getattr(session, "adapter", None), "recovery_history", None))
        )

    def _uses_service_execution_recovery_v2(self):
        return bool(
            self._uses_service_execution_recovery()
            and getattr(self._service_execution_session, "recovery_event_version", None) == 2
        )

    @staticmethod
    def _service_recovery_feed_name(data):
        for attribute in ("_name", "dataname", "name"):
            value = getattr(data, attribute, None)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _service_recovery_context_scalar(value):
        from bt_api_py.service_recovery import recovery_context_scalar

        return recovery_context_scalar(value)

    @classmethod
    def _service_recovery_comminfo_context(cls, comminfo):
        if comminfo is None:
            raise ValueError("recovery commission information is unavailable")
        params = getattr(comminfo, "p", None)
        if params is None:
            raise ValueError("recovery commission parameters are unavailable")
        names = (
            "commission",
            "mult",
            "margin",
            "commtype",
            "stocklike",
            "percabs",
            "interest",
            "interest_long",
            "leverage",
            "automargin",
        )
        values = {}
        for name in names:
            try:
                value = getattr(params, name)
            except Exception as error:
                raise ValueError("recovery commission parameter is unavailable") from error
            values[name] = cls._service_recovery_context_scalar(value)
        cls_name = type(comminfo)
        return {
            "class_module": cls_name.__module__,
            "class_name": cls_name.__qualname__,
            "params": values,
        }

    @classmethod
    def _service_recovery_feed_context(cls, data, data_name, instrument):
        timeframe = getattr(data, "_timeframe", None)
        compression = getattr(data, "_compression", None)
        if type(timeframe) is not int or type(compression) is not int:
            raise ValueError("recovery feed timeframe is not exact")
        raw_dataname = getattr(data, "_dataname", None)
        dataname = raw_dataname if isinstance(raw_dataname, str) else None
        timezone = getattr(data, "_tz", None)
        timezone = None if timezone is None else str(timezone)
        if timezone == "":
            timezone = None
        feed_type = type(data)
        feed_name = cls._service_recovery_feed_name(data)
        if not isinstance(feed_name, str) or not feed_name:
            raise ValueError("recovery feed name is unavailable")
        return {
            "data_name": data_name,
            "instrument": instrument,
            "feed_class": f"{feed_type.__module__}.{feed_type.__qualname__}",
            "feed_name": feed_name,
            "dataname": dataname,
            "timeframe": timeframe,
            "compression": compression,
            "timezone": timezone,
        }

    @classmethod
    def _service_recovery_quote_binding(
        cls, data, *, data_name, instrument, bar_index, datetime_hex
    ):
        """Capture the feed's explicit quote cursor for this exact decision bar.

        The feed adapter owns the quote-source mapping.  Broker recovery never
        derives a quote revision from a bar index, timestamp, or later fill.
        """

        reader = getattr(data, "service_execution_recovery_quote_binding", None)
        if not callable(reader):
            raise ValueError("recovery feed has no trusted quote binding")
        from bt_api_py.service_recovery_quote import validate_recovery_quote_binding

        binding = validate_recovery_quote_binding(reader(), instrument=instrument)
        if (
            type(data_name) is not str
            or not data_name
            or type(bar_index) is not int
            or bar_index < 1
            or type(datetime_hex) is not str
        ):
            raise ValueError("recovery feed quote binding is invalid")
        return {
            **binding,
            "data_name": data_name,
            "bar_index": bar_index,
            "datetime_hex": datetime_hex,
        }

    def configure_service_execution_recovery_feeds(self, feeds):
        """Bind stable configured feed names before a V2 recovery run starts."""

        if not self._uses_service_execution_recovery_v2():
            raise RuntimeError("service execution recovery v2 is not active")
        if not isinstance(feeds, (tuple, list)) or not feeds:
            raise ValueError("recovery feed set is empty")
        by_name = {}
        by_identity = {}
        for data in feeds:
            data_name = self._service_recovery_feed_name(data)
            if not isinstance(data_name, str) or not data_name or data_name in by_name:
                raise ValueError("recovery feed name is missing or ambiguous")
            by_name[data_name] = data
            by_identity[id(data)] = data_name
        if self._service_execution_recovery_feeds:
            if (
                tuple(self._service_execution_recovery_feeds.items())
                != tuple(by_name.items())
            ):
                raise RuntimeError("service execution recovery feeds already bound")
            return None
        self._service_execution_recovery_feeds = by_name
        self._service_execution_recovery_feed_names = by_identity
        return None

    def service_execution_recovery_feed(self, data_name):
        """Resolve only a feed from the frozen V2 composition map."""

        if not isinstance(data_name, str):
            return None
        return self._service_execution_recovery_feeds.get(data_name)

    def bind_service_execution_recovery_strategy(self, strategy):
        """Bind the single Strategy whose empty ledger is covered by V2 genesis."""

        if not self._uses_service_execution_recovery_v2():
            raise RuntimeError("service execution recovery v2 is not active")
        if getattr(strategy, "broker", None) is not self:
            raise ValueError("recovery Strategy is not bound to this Broker")
        current = self._service_execution_recovery_strategy
        if current is not None and current is not strategy:
            raise ValueError("service execution recovery supports one Strategy")
        self._service_execution_recovery_strategy = strategy
        return self._service_execution_session.adapter

    @staticmethod
    def _service_recovery_decimal(value, *, positive=False, nonnegative=False):
        from bt_api_py.service_recovery import recovery_exact_decimal

        return recovery_exact_decimal(value, positive=positive, nonnegative=nonnegative)

    @staticmethod
    def _service_recovery_local_decimal(value, *, positive=False, nonnegative=False):
        """Read a Backtrader numeric projection without accepting bool/NaN."""

        if type(value) is float:
            if not math.isfinite(value):
                raise ValueError("recovery local number is not finite")
            text = repr(value)
        elif type(value) is int:
            text = str(value)
        elif type(value) is Decimal:
            if not value.is_finite():
                raise ValueError("recovery local number is not finite")
            text = format(value, "f")
        else:
            raise ValueError("recovery local number has an unsupported type")
        from .btapibroker import BtApiBroker

        return BtApiBroker._service_recovery_decimal(
            text, positive=positive, nonnegative=nonnegative
        )

    def recovery_intent_context(self, order):
        """Capture the immutable configured-feed/bar/comminfo facts for one intent."""

        try:
            if not self._uses_service_execution_recovery_v2():
                raise ValueError("service execution recovery v2 is not active")
            strategy = self._service_execution_recovery_strategy
            if strategy is None or getattr(strategy, "broker", None) is not self:
                raise ValueError("recovery Strategy is unavailable")
            if bool(getattr(strategy, "_tradehistoryon", False)):
                raise ValueError("recovery Trade history is unsupported")
            if any(
                trades
                for by_trade_id in getattr(strategy, "_trades", {}).values()
                for trades in by_trade_id.values()
            ):
                raise ValueError("recovery intent requires an empty Strategy Trade ledger")
            data = getattr(order, "data", None)
            data_name = self._service_execution_recovery_feed_names.get(id(data))
            if data_name is None or self._service_execution_recovery_feeds.get(data_name) is not data:
                raise ValueError("recovery order feed is not the configured feed")
            info = getattr(order, "info", None)
            instrument = info.get("managed_instrument") if callable(getattr(info, "get", None)) else None
            if not isinstance(instrument, str) or not instrument:
                raise ValueError("recovery order instrument is unavailable")
            if (
                info.get("managed_position_effect") != "OPEN"
                or bool(info.get("reduce_only", False))
                or self._is_dual_side_mode()
            ):
                raise ValueError("only net-mode OPEN recovery orders are supported")
            feed = self._service_recovery_feed_context(data, data_name, instrument)
            bar_index = len(data)
            if type(bar_index) is not int or bar_index < 1:
                raise ValueError("recovery decision bar is unavailable")
            decision_time = data.datetime[0]
            if isinstance(decision_time, bool):
                raise ValueError("recovery decision datetime is invalid")
            decision_time = float(decision_time)
            if not math.isfinite(decision_time) or decision_time <= 0:
                raise ValueError("recovery decision datetime is invalid")
            decision_datetime_hex = decision_time.hex()
            quote_binding = self._service_recovery_quote_binding(
                data,
                data_name=data_name,
                instrument=instrument,
                bar_index=bar_index,
                datetime_hex=decision_datetime_hex,
            )
            comminfo = getattr(order, "comminfo", None) or self.getcommissioninfo(data)
            return {
                "feed": feed,
                "decision": {
                    "bar_index": bar_index,
                    "datetime_hex": decision_datetime_hex,
                },
                "comminfo": self._service_recovery_comminfo_context(comminfo),
                "quote_binding": quote_binding,
            }
        except Exception:
            self._fence_service_execution_recovery(order, "recovery_intent_context_unavailable")

    def resolve_service_execution_recovery_event_context(
        self, namespace, event, manifest, execution_context
    ):
        """Bind the validated paper fill to its stored bar and configured feed facts."""

        try:
            if not self._uses_service_execution_recovery_v2():
                raise ValueError("service execution recovery v2 is not active")
            if not all(isinstance(value, Mapping) for value in (event, manifest, execution_context)):
                raise ValueError("recovery event context source is incomplete")
            binding = manifest.get("recovery_binding")
            submit = manifest.get("submit_payload")
            feed_context = execution_context.get("feed")
            decision = execution_context.get("decision")
            comminfo = execution_context.get("comminfo")
            quote_binding = execution_context.get("quote_binding")
            if not all(
                isinstance(value, Mapping)
                for value in (binding, submit, feed_context, decision, comminfo, quote_binding)
            ):
                raise ValueError("recovery event context binding is incomplete")
            data_name = binding.get("data_name")
            data = self._service_execution_recovery_feeds.get(data_name)
            if data is None:
                raise ValueError("recovery event feed is not configured")
            instrument = submit.get("instrument")
            current_feed_context = self._service_recovery_feed_context(data, data_name, instrument)
            if dict(current_feed_context) != dict(feed_context):
                raise ValueError("recovery feed identity changed")
            current_comminfo = self._service_recovery_comminfo_context(
                getattr(data, "comminfo", None) or self.getcommissioninfo(data)
            )
            if current_comminfo != dict(comminfo):
                raise ValueError("recovery commission mapping changed")
            details = event.get("details")
            fill = details.get("paper_fill_v2") if isinstance(details, Mapping) else None
            if not isinstance(fill, Mapping):
                raise ValueError("managed paper V2 fill is unavailable")
            from bt_api_py.service_recovery import (
                validate_paper_recovery_fill_binding,
                validate_paper_recovery_fill_economics,
            )
            from bt_api_py.service_recovery_quote import recovery_quote_fill_matches

            validate_paper_recovery_fill_binding(
                namespace, event, submit, details, fill, instrument
            )
            if (
                frozenset(quote_binding)
                != {
                    "source_ref",
                    "generation",
                    "cursor",
                    "instrument",
                    "as_of_ns",
                    "data_name",
                    "bar_index",
                    "datetime_hex",
                }
                or not recovery_quote_fill_matches(quote_binding, fill)
                or quote_binding.get("data_name") != data_name
                or quote_binding.get("bar_index") != decision.get("bar_index")
                or quote_binding.get("datetime_hex") != decision.get("datetime_hex")
                or type(quote_binding.get("as_of_ns")) is not int
                or quote_binding.get("as_of_ns") <= 0
            ):
                raise ValueError("managed paper quote is not bound to the persisted feed bar")
            validate_paper_recovery_fill_economics(
                fill, submit, details, decimal=self._service_recovery_decimal
            )
            currency = fill.get("commission_currency")
            baseline = self._service_execution_session.adapter.recovery_baseline()
            cash = baseline.get("cash_by_currency") if isinstance(baseline, Mapping) else None
            if not isinstance(currency, str) or not currency or not isinstance(cash, Mapping) or currency not in cash:
                raise ValueError("managed paper fee currency is not in the owner baseline")
            match_ns = fill.get("match_time_ns")
            if (
                type(match_ns) is not int
                or match_ns <= 0
                or match_ns < quote_binding["as_of_ns"]
            ):
                raise ValueError("managed paper match time is invalid")
            return {
                "data_name": data_name,
                "instrument": instrument,
                "bar_index": decision.get("bar_index"),
                "datetime_hex": decision.get("datetime_hex"),
                "comminfo": dict(comminfo),
                "commission_currency": currency,
                "quote_source_ref": fill.get("quote_source_ref"),
                "quote_generation": fill.get("quote_generation"),
                "quote_cursor": fill.get("quote_cursor"),
                "quote_instrument": fill.get("quote_instrument"),
                "quote_as_of_ns": quote_binding.get("as_of_ns"),
            }
        except Exception:
            # The journal turns mapper errors into REPLAY_UNAVAILABLE.  Do not
            # replace a missing or changed source fact with the current bar.
            return None

