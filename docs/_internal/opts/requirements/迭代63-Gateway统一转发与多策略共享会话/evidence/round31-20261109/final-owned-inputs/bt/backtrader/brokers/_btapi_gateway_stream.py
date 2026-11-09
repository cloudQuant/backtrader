"""Explicit sparse Gateway execution stream consumer for a single BT strategy.

The pending host owns the durable cursor.  Network observations do not by
itself establish venue provenance; callbacks remain on the framework path.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from dataclasses import dataclass
from decimal import Decimal

from ..utils.dateintern import date2num


class GatewayExecutionStreamError(RuntimeError):
    """Finite, value-free consumer error."""


@dataclass
class _StreamBinding:
    strategy: object
    api: object
    host: object
    stream: object
    policy: object
    instruments: dict
    feeds: dict
    restored: bool
    limit: int
    timeout: float
    pid: int
    thread: object
    state: str = "ACTIVE"


def _fail(code):
    raise GatewayExecutionStreamError("GATEWAY_STREAM_" + code)


class GatewayExecutionStreamBrokerMixin:
    def bind_gateway_execution_events(self, *args, **kwargs):
        if self.__dict__.get("_gateway_stream_binding") is not None:
            _fail("MODE_CONFLICT")
        return super().bind_gateway_execution_events(*args, **kwargs)

    def bind_gateway_execution_stream(
        self, strategy, *, api, host, data_by_ref, orders_by_key, time_policy, instrument_by_ref,
        page_limit=128, timeout_seconds=1.0,
    ):
        """Bind a real SDK facade and its exact durable host to one strategy."""
        from bt_api_py.gateway_api import GatewayBtApi
        from bt_api_py.gateway_execution_stream_client import GatewayExecutionStreamClient
        from bt_api_py.gateway_execution_time import GatewayExecutionTimePolicy
        from bt_api_base.market_protocol import MarketInstrumentKey
        from ..live_state.gateway_pending import GatewayPendingHost

        if self.__dict__.get("_gateway_stream_binding") is not None:
            _fail("ALREADY_BOUND")
        if (
            type(api) is not GatewayBtApi or type(host) is not GatewayPendingHost
            or type(time_policy) is not GatewayExecutionTimePolicy
            or type(page_limit) is not int or not 1 <= page_limit <= 256
            or type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30
            or self.__dict__.get("_gateway_execution_bindings")
            or self.__dict__.get("_gateway_notification_bindings")
            or getattr(self, "factor_execution_coordinator", None) is not None
            or type(data_by_ref) is not dict or type(instrument_by_ref) is not dict
            or instrument_by_ref.keys() != data_by_ref.keys()
            or any(type(key) is not MarketInstrumentKey for key in instrument_by_ref.values())
        ):
            _fail("BINDING_INVALID")
        if time_policy.route != api._exchange_name or api._host is not host:
            _fail("SCOPE")
        stream = api.gateway_execution_stream(time_policy.route)
        checkpoint = host.load_execution_checkpoint()
        if (
            type(stream) is not GatewayExecutionStreamClient
            or stream._binding != host._binding
            or stream._consumer_ref != checkpoint.consumer_ref
        ):
            _fail("SCOPE")
        if checkpoint.projection is not None and orders_by_key:
            _fail("RESTORE_REQUIRES_EMPTY_ORDERS")
        self.bind_gateway_notification_state(
            strategy, host=host, data_by_ref=data_by_ref, orders_by_key=orders_by_key
        )
        binding = _StreamBinding(strategy, api, host, stream, time_policy, dict(instrument_by_ref),
                                 dict(data_by_ref), checkpoint.projection is not None, page_limit,
                                 float(timeout_seconds), os.getpid(), threading.current_thread())
        self._gateway_stream_binding = binding
        try:
            if checkpoint.projection is not None:
                self.restore_gateway_notification_state(strategy)
            notices = self._gateway_binding(strategy, required=True)
            for key, order in notices.orders.items():
                self._gateway_stream_order(binding, key, order)
                feed_ref = next(ref for ref, data in binding.feeds.items() if data is order.data)
                if not binding.restored:
                    order.addinfo(gateway_instrument_key=binding.instruments[feed_ref].to_dict(),
                                  gateway_execution_time_policy=binding.policy.to_mapping(),
                                  gateway_execution_time_policy_digest=binding.policy.digest,
                                  gateway_original_bt_ref=order.ref)
                existing = self.orders.get(order.ref)
                if existing is not None and existing is not order:
                    _fail("ORDER_CONFLICT")
                self.orders[order.ref] = order
        except BaseException:
            # Binding may have restored framework objects. Never permit legacy fallback.
            binding.state = "RESTART_REQUIRED"
            raise
        return host.load_execution_checkpoint()

    def gateway_execution_stream_status(self):
        binding = self.__dict__.get("_gateway_stream_binding")
        if binding is None:
            return "UNBOUND"
        self._gateway_stream_check(binding)
        return binding.state

    def _gateway_stream_check(self, binding):
        if (binding.pid != os.getpid() or binding.thread is not threading.current_thread()
                or binding.api._host is not binding.host
                or binding.api.gateway_execution_stream(binding.policy.route) is not binding.stream
                or binding.stream._binding != binding.host._binding
                or binding.stream._consumer_ref != binding.host.load_execution_checkpoint().consumer_ref):
            _fail("SCOPE")
        self._gateway_binding(binding.strategy, required=True)
        if self.__dict__.get("_gateway_execution_bindings"):
            _fail("MODE_CONFLICT")

    def _gateway_stream_order(self, binding, key, order):
        from bt_api_py.gateway_order_contract import decode_gateway_order_request

        intent = binding.host.load_intent(key)
        record = binding.host.load_record(key)
        context = binding.host.load_context(key)
        if (intent is None or record is None or context is None
                or intent.binding != binding.host._binding
                or intent.route != binding.stream._route
                or record.binding != intent.binding or record.request_key != key
                or record.digest != intent.digest
                or type(context.bt_ref) is not int or context.bt_ref != (
                    order.info.get("gateway_original_bt_ref") if binding.restored else order.ref)):
            _fail("ORDER_BINDING")
        request = decode_gateway_order_request(json.loads(intent.canonical_payload), intent.binding.account_scope)
        side = "buy" if order.isbuy() else "sell"
        if (request.side.value.lower() != side
                or Decimal(str(abs(order.size))) != request.quantity
                or self._position_key(order.data) != request.symbol):
            _fail("ORDER_BINDING")
        refs = [ref for ref, data in binding.feeds.items() if data is order.data]
        if len(refs) != 1 or binding.instruments[refs[0]].native_symbol != request.symbol:
            _fail("INSTRUMENT_SCOPE")
        saved_key = order.info.get("gateway_instrument_key")
        expected_key = binding.instruments[refs[0]].to_dict()
        original_ref = order.info.get("gateway_original_bt_ref")
        if ((binding.restored and (saved_key != expected_key or type(original_ref) is not int))
                or (not binding.restored and saved_key is not None and saved_key != expected_key)):
            _fail("INSTRUMENT_SCOPE")
        old_policy = order.info.get("gateway_execution_time_policy")
        old_digest = order.info.get("gateway_execution_time_policy_digest")
        if ((binding.restored or old_policy is not None or old_digest is not None)
                and (old_policy != binding.policy.to_mapping() or old_digest != binding.policy.digest)):
            _fail("TIME_POLICY_CONFLICT")
        return intent, record, request

    def _gateway_stream_events(self, host, after=0):
        # Bound total scanning to avoid unbounded per-tick CPU/memory use.
        count = 0
        while True:
            page = host.read_execution_events(after_sequence=after, limit=256)
            if not page:
                return
            for event in page:
                count += 1
                if count > 10000:
                    _fail("SCAN_LIMIT")
                yield event
            after = page[-1].sequence
            if len(page) < 256:
                return

    def _gateway_stream_event_binding(self, binding, event, order):
        from bt_api_base.direct_write_protocol import DirectExecutionEventKind

        intent, record, request = self._gateway_stream_order(binding, event.request_key, order)
        obs = event.observation
        feed_ref = next(ref for ref, data in binding.feeds.items() if data is order.data)
        matched_identity = bool(set(record.strong_identity_key_digests).intersection(obs.binding_key_digests))
        request_error = (
            (obs.kind is DirectExecutionEventKind.ORDER_ERROR and event.place_attribution is not None)
            or (obs.kind is DirectExecutionEventKind.CANCEL_ERROR and event.cancel_attribution is not None)
        )
        if (event.reservation_id != record.reservation_id or event.command_digest != intent.digest
                or event.command_principal != intent.binding.principal
                or obs.account_scope != intent.binding.account_scope
                or obs.route != binding.policy.route
                or not (matched_identity or request_error)
                or request.symbol != obs.instrument.native_symbol
                or obs.instrument != binding.instruments[feed_ref]
                or (request.instrument is not None and request.instrument != obs.instrument)
                or (obs.side is not None and obs.side != request.side.value.lower())
                or (obs.offset is not None and obs.offset != request.offset)
                or (obs.order_quantity is not None
                    and Decimal(obs.order_quantity) != request.quantity)):
            _fail("EVENT_BINDING")
        return request

    def _gateway_stream_next(self):
        from bt_api_base.direct_write_protocol import DirectExecutionEventKind, DirectOrderStatus

        binding = self._gateway_stream_binding
        self._gateway_stream_check(binding)
        if binding.state == "RESTART_REQUIRED":
            _fail("RESTART_REQUIRED")
        notice = self._gateway_binding(binding.strategy, required=True)
        if notice.restored is not None or notice.fault == "retryable":
            binding.state = "WAITING_NOTIFICATIONS"
            return
        if notice.fault is not None:
            binding.state = "RESTART_REQUIRED"
            _fail("RESTART_REQUIRED")
        checkpoint = binding.host.load_execution_checkpoint()
        if checkpoint.applied_sequence > checkpoint.acknowledged_sequence:
            try:
                self.assert_gateway_notifications_ackable(binding.strategy, checkpoint.applied_sequence)
            except ValueError:
                binding.state = "WAITING_NOTIFICATIONS"
                return
            result = binding.stream.ack(checkpoint.applied_sequence, expected_epoch=checkpoint.epoch,
                                        timeout_seconds=binding.timeout)
            if result.outcome != "OBSERVED" or result.progress is None:
                binding.state = "ACK_UNAVAILABLE"
                return
            if result.progress.acknowledged_sequence != checkpoint.applied_sequence:
                binding.state = "ACK_UNAVAILABLE"
                return
            checkpoint = binding.host.record_execution_ack(result.progress)
        if notice.armed is not None or notice.receipt is not None:
            binding.state = "WAITING_NOTIFICATIONS"
            return
        did_read = False

        def read_once():
            nonlocal checkpoint, did_read
            did_read = True
            result = binding.stream.read_after(checkpoint.stored_sequence, checkpoint.epoch,
                                               binding.limit, timeout_seconds=binding.timeout)
            if result.outcome != "OBSERVED":
                binding.state = "READ_UNAVAILABLE"
                return False
            checkpoint = binding.host.ingest_execution_result(result, expected_revision=checkpoint.revision)
            return True

        events = binding.host.read_execution_events(limit=1)
        if not events:
            if not read_once():
                return
            events = binding.host.read_execution_events(limit=1)
            if not events:
                binding.state = "ACTIVE"
                return
        event = events[0]
        order = notice.orders.get(event.request_key)
        if order is None:
            binding.state = "ORDER_UNAVAILABLE"
            return
        request = self._gateway_stream_event_binding(binding, event, order)
        obs = event.observation
        if obs.kind is DirectExecutionEventKind.TRADE:
            def trade_facts():
                prior, dates, times = [], [], set()
                for candidate in self._gateway_stream_events(binding.host):
                    other = candidate.observation
                    if (candidate.request_key == event.request_key
                            and other.trade_key_digest == obs.trade_key_digest):
                        if candidate.sequence < event.sequence and not other.trade_metadata_only:
                            prior.append(candidate)
                        if other.trade_date is not None:
                            dates.append((other.trade_date, candidate.fact_digest))
                        if other.trade_time is not None:
                            times.add(other.trade_time)
                if len({value for value, _ in dates}) > 1:
                    _fail("TRADE_DATE_CONFLICT")
                if len(times) > 1:
                    _fail("TRADE_TIME_CONFLICT")
                return prior, dates

            prior, dates = trade_facts()
            if (not obs.trade_metadata_only and obs.trade_date is None and not dates
                    and not did_read):
                if not read_once():
                    return
                prior, dates = trade_facts()
        if obs.kind is DirectExecutionEventKind.TRADE and not obs.trade_metadata_only:
            if obs.offset != request.offset:
                binding.state = "TRADE_INCOMPLETE"
                return
            date = obs.trade_date or (dates[0][0] if dates else None)
            try:
                stamp = binding.policy.project(date, obs.trade_time)
            except ValueError:
                binding.state = "TIME_INVALID"
                return
            if stamp is None:
                binding.state = "TIME_UNAVAILABLE"
                return
            if obs.side is None or obs.trade_key_digest is None or obs.trade_quantity is None or obs.trade_price is None:
                binding.state = "TRADE_INCOMPLETE"
                return
        elif obs.kind is DirectExecutionEventKind.ORDER:
            allowed = {DirectOrderStatus.SUBMITTED, DirectOrderStatus.ACCEPTED,
                       DirectOrderStatus.PARTIALLY_FILLED, DirectOrderStatus.FILLED,
                       DirectOrderStatus.CANCELLED, DirectOrderStatus.REJECTED,
                       DirectOrderStatus.UNKNOWN}
            if obs.status not in allowed or (obs.status in {DirectOrderStatus.FILLED,
                    DirectOrderStatus.CANCELLED, DirectOrderStatus.REJECTED} and obs.filled_quantity is None):
                binding.state = "ORDER_INCOMPLETE"
                return
            if obs.status in {DirectOrderStatus.FILLED, DirectOrderStatus.CANCELLED,
                              DirectOrderStatus.REJECTED}:
                filled = Decimal(obs.filled_quantity)
                executed = Decimal(str(abs(order.executed.size)))
                if (filled < executed or filled > request.quantity
                        or (obs.status is DirectOrderStatus.FILLED and filled != request.quantity)
                        or (obs.status is DirectOrderStatus.REJECTED and filled != 0)):
                    binding.state = "ORDER_INCOMPLETE"
                    return
        elif obs.kind is DirectExecutionEventKind.ORDER_ERROR:
            if obs.status not in (None, DirectOrderStatus.UNKNOWN, DirectOrderStatus.REJECTED):
                binding.state = "ORDER_INCOMPLETE"
                return
            if obs.status is DirectOrderStatus.REJECTED and (
                    obs.filled_quantity is None or Decimal(obs.filled_quantity) != 0
                    or order.executed.size != 0 or not obs.binding_key_digests):
                binding.state = "ORDER_INCOMPLETE"
                return
        elif obs.kind not in (DirectExecutionEventKind.ORDER_ERROR, DirectExecutionEventKind.CANCEL_ERROR,
                              DirectExecutionEventKind.TRADE):
            binding.state = "EVENT_UNSUPPORTED"
            return
        self.arm_gateway_notification_state(binding.strategy, event.sequence)
        try:
            if obs.kind is DirectExecutionEventKind.TRADE and obs.trade_metadata_only:
                self.commit_gateway_trade_metadata(binding.strategy, event.sequence)
            elif obs.kind is DirectExecutionEventKind.TRADE:
                order.addinfo(gateway_execution_time_policy=binding.policy.to_mapping(),
                              gateway_execution_time_policy_digest=binding.policy.digest)
                facts = dict(order.info.get("gateway_execution_time_facts") or {})
                facts[obs.trade_key_digest] = {"trade_date": date, "trade_time": obs.trade_time,
                                               "date_fact_digest": next((f for d, f in dates if d == date), None)}
                order.info["gateway_execution_time_facts"] = facts
                if not prior:
                    order.addinfo(quantity_unit=request.quantity_unit, position_side=request.position_side,
                                  offset=request.offset, gateway_position_fields_source="request")
                    self._order_execution_contracts.pop(order.ref, None)
                    self._freeze_order_execution_contract(order)
                    row = {"kind": "trade", "local_ref": order.ref, "data_name": request.symbol,
                           "side": obs.side, "quantity": obs.trade_quantity, "price": obs.trade_price,
                           "quantity_unit": request.quantity_unit, "position_side": request.position_side,
                           "offset": request.offset, "timestamp": stamp,
                           "trade_id": "gateway:" + hashlib.sha256((event.request_key + "\0" + obs.trade_key_digest).encode()).hexdigest()}
                    self._gateway_stream_execution_time = (order, float(date2num(stamp)))
                    try:
                        outcome = self._apply_trade_update(row, defer_unmatched=False)
                    finally:
                        self.__dict__.pop("_gateway_stream_execution_time", None)
                    if outcome != "applied":
                        _fail("TRADE_PROJECTION")
                else:
                    self.notify(order)
            elif obs.kind is DirectExecutionEventKind.ORDER:
                statuses = {DirectOrderStatus.ACCEPTED: "accepted",
                            DirectOrderStatus.PARTIALLY_FILLED: "partial", DirectOrderStatus.FILLED: "completed",
                            DirectOrderStatus.CANCELLED: "canceled", DirectOrderStatus.REJECTED: "rejected",
                            DirectOrderStatus.UNKNOWN: "unknown"}
                before = len(self.notifs)
                if obs.status is DirectOrderStatus.SUBMITTED:
                    if order.status < order.Submitted:
                        order.submit(self)
                else:
                    status = statuses[obs.status]
                    self._apply_order_update({"local_ref": order.ref, "status": status,
                        "terminal_confirmed": status in {"completed", "canceled", "rejected"},
                        "filled_quantity": obs.filled_quantity, "execution_source": "trades"})
                if len(self.notifs) == before:
                    self.notify(order)
            else:
                # Request errors are observations, not proof of order rejection/cancellation.
                order.addinfo(gateway_request_error_kind=obs.kind.value,
                              gateway_request_error_observed=obs.error_code is not None)
                if (obs.kind is DirectExecutionEventKind.ORDER_ERROR
                        and obs.status is DirectOrderStatus.REJECTED):
                    self._apply_order_update({"local_ref": order.ref, "status": "rejected",
                        "terminal_confirmed": True, "filled_quantity": obs.filled_quantity,
                        "execution_source": "trades"})
                else:
                    self.notify(order)
            binding.state = "ACTIVE"
        except BaseException:
            binding.state = "RESTART_REQUIRED"
            raise
