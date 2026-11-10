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
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, localcontext

from ..utils.dateintern import date2num
from ..utils.log_message import get_logger

_logger = get_logger(__name__)


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
    sequence: object = None
    state: str = "ACTIVE"
    local_deferred: list = field(default_factory=list)
    # Request keys whose dispatch the Gateway acknowledged in this process; any
    # other RESERVED reservation (earlier process, or an uncertain dispatch) is
    # read back and withdrawn, decided atomically by version at the Gateway.
    dispatched: set = field(default_factory=set)
    # Reservations this session sent without learning the outcome, with the
    # monotonic time of the attempt (see _gateway_reservation_absent).
    reserve_unknown: dict = field(default_factory=dict)


# A reserve whose reply was lost may still be waiting for the Gateway's owner
# thread. This long after the attempt it can no longer be committed: the
# service bounds the call and the owner's longest native wait is far shorter.
_RESERVE_ABSENT_AFTER_SECONDS = 20.0


def _bt_terminal(order):
    """Completed, Canceled, Rejected, Expired or Margin in BT (status is final)."""
    return order.status in (order.Completed, order.Canceled, order.Rejected, order.Expired,
                            order.Margin)


def _fail(code):
    raise GatewayExecutionStreamError("GATEWAY_STREAM_" + code)


class GatewayExecutionStreamBrokerMixin:
    def _gateway_auto_bind(self, strategy=None):
        if self.__dict__.get("_gateway_stream_binding") is not None:
            current = self._gateway_stream_binding.strategy
            if strategy is not None and strategy is not current:
                _fail("STRATEGY_SCOPE")
            return current
        store = self.store
        if store is None or not getattr(store, "_gateway_mode", False):
            return None
        if strategy is None:
            cerebro = getattr(self, "cerebro", None)
            strategies = getattr(cerebro, "runningstrats", None) or []
            if len(strategies) != 1:
                _fail("STRATEGY_SCOPE")
            strategy = strategies[0]
        if getattr(strategy, "broker", None) is not self:
            _fail("STRATEGY_SCOPE")
        config = getattr(store, "gateway_strategy_config", None)
        configured = getattr(config, "instruments_by_ref", None)
        if not isinstance(configured, Mapping) or not configured:
            _fail("CONFIG_UNAVAILABLE")
        data_by_ref = {}
        for ref, instrument in configured.items():
            candidates = [data for data in strategy.datas
                          if self._position_key(data) in (ref, instrument.native_symbol)]
            if len(candidates) != 1 or candidates[0] in data_by_ref.values():
                _fail("INSTRUMENT_SCOPE")
            data_by_ref[ref] = candidates[0]
        # Framework snapshot/restore requires every bound feed to have its
        # first bar.  Wait without installing a partial binding or falling
        # back to direct while live feeds are starting or disconnected.
        if any(len(data) < 1 for data in data_by_ref.values()):
            self._gateway_waiting_for_feed = True
            return None
        sequence = getattr(store, "gateway_sequence", None)
        if sequence is None:
            _fail("SEQUENCE_SCOPE")
        store.bind_gateway_strategy(strategy, data_by_ref=data_by_ref, sequence=sequence)
        self._gateway_waiting_for_feed = False
        return strategy

    def bind_gateway_execution_events(self, *args, **kwargs):
        if self.__dict__.get("_gateway_stream_binding") is not None:
            _fail("MODE_CONFLICT")
        return super().bind_gateway_execution_events(*args, **kwargs)

    def bind_gateway_execution_stream(
        self, strategy, *, api, host, data_by_ref, orders_by_key, time_policy, instrument_by_ref,
        page_limit=128, timeout_seconds=1.0, sequence=None,
    ):
        """Bind a real SDK facade and its exact durable host to one strategy."""
        from bt_api_py.gateway_api import GatewayBtApi
        from bt_api_py.gateway_execution_stream_client import GatewayExecutionStreamClient
        from bt_api_py.gateway_execution_time import GatewayExecutionTimePolicy
        from bt_api_base.market_protocol import MarketInstrumentKey
        from ..live_state.gateway_pending import GatewayPendingHost
        from ..live_state.sequence import SequenceAllocator

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
        if sequence is not None:
            if (type(sequence) is not SequenceAllocator
                    or sequence.strategy_uuid != host._store.strategy_uuid
                    or sequence.paths.strategy_dir != host._store.paths.strategy_dir):
                _fail("SEQUENCE_SCOPE")
            sequence.restore_ref_basis()
            host.upgrade_for_local_notifications()
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
                                 float(timeout_seconds), os.getpid(), threading.current_thread(), sequence)
        self._gateway_stream_binding = binding
        try:
            if checkpoint.projection is not None:
                self.restore_gateway_notification_state(strategy)
            notices = self._gateway_binding(strategy, required=True)
            if sequence is not None:
                from ._btapi_gateway_projection import restore_framework_state
                def queue_local(order):
                    if notices.restored is not None or notices.receipt is not None:
                        binding.local_deferred.append(order)
                    else:
                        self.notifs.append(order)
                for current in notices.orders.values():
                    sequence.observe_ref(current.ref)
                for key, envelope in host.iter_order_snapshots().items():
                    restored = restore_framework_state(envelope["snapshot"], data_by_ref=binding.feeds,
                        owner=strategy, broker=self, commission_for_data=self.getcommissioninfo)
                    old = restored.orders[key]
                    sequence.observe_ref(old.ref)
                    if key not in notices.orders:
                        self._gateway_register_order(notices, key, old)
                        self.orders[old.ref] = old
                    local = host.local_order_notifications().get(key)
                    if local is not None and local["status"] == "pending":
                        current = notices.orders[key]
                        if current.executed.size != 0:
                            _fail("LOCAL_NOTIFICATION_CONFLICT")
                        old.ref = current.ref
                        old.notification_id, old.replayed = local["notification_id"], True
                        queue_local(old.clone())
                    cancel = host.local_order_notifications().get("cancel:" + key)
                    reject = host.local_order_notifications().get("reject:" + key)
                    current = notices.orders[key]
                    if reject is not None:
                        rejected = restore_framework_state(reject["snapshot"], data_by_ref=binding.feeds,
                            owner=strategy, broker=self, commission_for_data=self.getcommissioninfo).orders[key]
                        sequence.observe_ref(rejected.ref)
                        if (cancel is not None or current.executed.size != 0
                                or rejected.status != rejected.Rejected):
                            _fail("LOCAL_NOTIFICATION_CONFLICT")
                        current.status, current.executed.dt = rejected.status, rejected.executed.dt
                        if reject["status"] == "pending":
                            rejected.ref = current.ref
                            rejected.notification_id, rejected.replayed = reject["notification_id"], True
                            queue_local(rejected)
                    elif cancel is not None:
                        canceled = restore_framework_state(cancel["snapshot"], data_by_ref=binding.feeds,
                            owner=strategy, broker=self, commission_for_data=self.getcommissioninfo).orders[key]
                        sequence.observe_ref(canceled.ref)
                        if current.executed.size != 0 or canceled.status != canceled.Canceled:
                            _fail("LOCAL_NOTIFICATION_CONFLICT")
                        current.status, current.executed.dt = canceled.status, canceled.executed.dt
                        if cancel["status"] == "pending":
                            canceled.ref = current.ref
                            canceled.notification_id, canceled.replayed = cancel["notification_id"], True
                            queue_local(canceled)
                    elif (host.load_record(key) is not None
                          and host.load_record(key).state in ("RELEASED", "EXPIRED")):
                        self._gateway_finalize_release(binding, current, key)
            for key, order in notices.orders.items():
                self._gateway_stream_order(binding, key, order, allow_unreserved=sequence is not None)
                feed_ref = next(ref for ref, data in binding.feeds.items() if data is order.data)
                if not binding.restored and order.info.get("gateway_original_bt_ref") is None:
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
            return "WAITING_FEED" if self.__dict__.get("_gateway_waiting_for_feed") else "UNBOUND"
        if self._gateway_unreachable() or self._gateway_session_stale(binding):
            self._gateway_stream_check(binding, connected_required=False)
            return "GATEWAY_UNAVAILABLE"
        self._gateway_stream_check(binding)
        return binding.state

    def _gateway_notify_local(self, binding, order):
        notice = self._gateway_binding(binding.strategy, required=True)
        before = len(self.notifs)
        self.notify(order)
        if (notice.armed is not None or notice.receipt is not None or notice.restored is not None):
            if len(self.notifs) != before + 1:
                _fail("LOCAL_NOTIFICATION_QUEUE")
            binding.local_deferred.append(self.notifs.pop())

    def _gateway_require_trade_qualification(self, data, instrument):
        """Ask the exact Gateway feed to qualify its latest delivered live tick."""
        from ..feed import DataClone
        from ..feeds.btapifeed import BtApiFeed, FeedTradeQualification

        source = data.data if isinstance(data, DataClone) else data
        if (not isinstance(source, BtApiFeed) or getattr(data, "replaying", False)
                or getattr(source, "replaying", False)):
            _fail("FEED_NOT_TRADABLE")
        try:
            if BtApiFeed.historical_warmup_active(source):
                _fail("FEED_NOT_TRADABLE")
            verdict = BtApiFeed.gateway_trade_qualification(
                source, expected_store=self.store, expected_instrument=instrument
            )
        except Exception:
            _fail("FEED_NOT_TRADABLE")
        if (type(verdict) is not FeedTradeQualification or verdict.ok is not True
                or verdict.live is not True or verdict.reasons != ()
                or type(verdict.expires_monotonic_ns) is not int
                or time.monotonic_ns() >= verdict.expires_monotonic_ns):
            _fail("FEED_NOT_TRADABLE")
        from bt_api_base.market_protocol import MarketSubscriptionKey
        ref = verdict.dispatch_market_ref
        try:
            if not isinstance(ref, Mapping) or set(ref) != {"key", "epoch", "sequence", "message_id"}:
                raise ValueError
            key = dict(ref["key"])
            key["instrument"] = dict(key["instrument"])
            subscription = MarketSubscriptionKey.from_dict(key)
            if (subscription.instrument != instrument
                    or type(ref["epoch"]) is not str or not ref["epoch"]
                    or type(ref["sequence"]) is not int or ref["sequence"] <= 0
                    or type(ref["message_id"]) is not str or not ref["message_id"]):
                raise ValueError
            return {"key": subscription.to_dict(), "epoch": ref["epoch"],
                    "sequence": ref["sequence"], "message_id": ref["message_id"]}
        except (TypeError, ValueError, KeyError):
            _fail("FEED_NOT_TRADABLE")

    def _gateway_strategy_position_observation(self, binding, instrument, unit, *, order=None):
        """Read a freshly authenticated observation for this exact strategy."""
        from bt_api_py.gateway_strategy_position import (
            GatewayStrategyPositionObservation, GatewayStrategyPositionResult,
        )

        try:
            if order is None:
                result = binding.api.get_strategy_position(binding.policy.route, instrument,
                    quantity_unit=unit, timeout_seconds=binding.timeout)
            else:
                result = binding.api.get_strategy_close_capacity(binding.policy.route, instrument,
                    quantity_unit=unit, side="buy" if order.isbuy() else "sell",
                    offset=order.info.get("offset"), quantity=Decimal(str(abs(order.size))),
                    position_side=order.info.get("position_side"), timeout_seconds=binding.timeout)
            if type(result) is not GatewayStrategyPositionResult or result.outcome != "OBSERVED":
                _fail("STRATEGY_POSITION_UNAVAILABLE")
            observation = result.observation
            if (type(observation) is not GatewayStrategyPositionObservation
                    or observation.binding != binding.host._binding
                    or observation.instrument != instrument or observation.quantity_unit != unit
                    or not binding.api.strategy_position_is_current(
                        binding.policy.route, observation, max_age_seconds=1.0)):
                _fail("STRATEGY_POSITION_UNAVAILABLE")
            if order is not None and (observation.strategy_close_available is None
                    or observation.strategy_close_available < Decimal(str(abs(order.size)))):
                _fail("STRATEGY_CLOSE_UNAVAILABLE")
            return observation
        except GatewayExecutionStreamError:
            raise
        except Exception:
            _fail("STRATEGY_POSITION_UNAVAILABLE")

    def _gateway_position_view(self, data, side=None):
        from bt_api_base.market_protocol import MarketInstrumentKey
        from ..position import Position

        binding = self.__dict__.get("_gateway_stream_binding")
        if binding is None:
            _fail("FEED_NOT_READY")
        self._gateway_stream_check(binding)
        refs = [ref for ref, feed in binding.feeds.items() if feed is data]
        if len(refs) != 1:
            _fail("INSTRUMENT_SCOPE")
        instrument = binding.instruments[refs[0]]
        metadata = getattr(self.store, "contract_metadata", None) or {}
        row = metadata.get(instrument.native_symbol) if isinstance(metadata, Mapping) else None
        if not isinstance(row, Mapping):
            _fail("STRATEGY_POSITION_UNIT_UNAVAILABLE")
        declared = row.get("instrument_key")
        if isinstance(declared, Mapping):
            try:
                declared = MarketInstrumentKey.from_dict(dict(declared))
            except (TypeError, ValueError):
                _fail("INSTRUMENT_RULE_SCOPE")
        unit = row.get("quantity_unit")
        if (type(declared) is not MarketInstrumentKey or declared != instrument
                or row.get("exchange_name") != binding.policy.route
                or type(unit) is not str or unit not in {"base", "contracts", "lots", "native"}):
            _fail("STRATEGY_POSITION_UNIT_UNAVAILABLE")
        observation = self._gateway_strategy_position_observation(binding, instrument, unit)
        with localcontext() as context:
            context.prec = 160
            long_size = observation.long_today + observation.long_yesterday
            short_size = observation.short_today + observation.short_yesterday
            if side is None:
                if long_size and short_size:
                    _fail("STRATEGY_POSITION_SIDE_REQUIRED")
                size = long_size - short_size
            elif side == "long":
                size = long_size
            elif side == "short":
                size = short_size
            else:
                _fail("STRATEGY_POSITION_SIDE_REQUIRED")
        try:
            value = float(size)
        except (ValueError, OverflowError):
            _fail("STRATEGY_POSITION_PRECISION_UNAVAILABLE")
        if not math.isfinite(value) or Decimal(str(value)) != size:
            _fail("STRATEGY_POSITION_PRECISION_UNAVAILABLE")
        return Position(size=value, price=float("nan") if value else 0.0)

    def _gateway_submit_order(self, order):
        from bt_api_py._contracts.models import OrderRequest, OrderType, Side
        from bt_api_py.gateway_direct_client import build_gateway_order_intent
        from ._btapi_gateway_projection import capture_framework_state
        from ..order import Order

        binding = self._gateway_stream_binding
        if binding is None:
            _fail("FEED_NOT_READY")
        self._gateway_stream_check(binding)
        notice = self._gateway_binding(binding.strategy, required=True)
        if binding.sequence is None:
            raise RuntimeError("GATEWAY_WRITE_ADAPTER_UNAVAILABLE")
        if (binding.state == "RESTART_REQUIRED" or notice.fault is not None
                or order.owner is not binding.strategy or order.exectype != Order.Limit
                or order.parent is not None or order.oco is not None or not order.transmit
                or order.valid is not None or getattr(order.p, "simulated", False)
                or order.status != order.Created or order.executed.size != 0
                or order.executed.exbits or order.ref in self.orders):
            _fail("ORDER_UNSUPPORTED")
        if not self._trading_enabled:
            _fail("TRADING_DISABLED")
        refs = [key for key, data in binding.feeds.items() if data is order.data]
        if len(refs) != 1 or self._position_key(order.data) != binding.instruments[refs[0]].native_symbol:
            _fail("INSTRUMENT_SCOPE")
        key = binding.instruments[refs[0]]
        # Configured rules are usable only when they name the exact instrument
        # and route. A symbol alone is not an instrument identity.
        metadata = getattr(self.store, "contract_metadata", None) or {}
        row = metadata.get(key.native_symbol) if isinstance(metadata, Mapping) else None
        if not isinstance(row, Mapping):
            _fail("INSTRUMENT_RULES_UNAVAILABLE")
        from bt_api_base.market_protocol import MarketInstrumentKey
        instrument = row.get("instrument_key")
        if isinstance(instrument, Mapping):
            try:
                instrument = MarketInstrumentKey.from_dict(dict(instrument))
            except (TypeError, ValueError):
                _fail("INSTRUMENT_RULE_SCOPE")
        if (type(instrument) is not MarketInstrumentKey or instrument != key
                or row.get("exchange_name") != binding.policy.route):
            _fail("INSTRUMENT_RULE_SCOPE")
        declared = row
        fields = {}
        for name in ("quantity_unit", "time_in_force"):
            chosen = order.info.get(name)
            rule = declared.get(name)
            if type(rule) is not str or not rule or rule != rule.strip():
                _fail("INSTRUMENT_RULES_UNAVAILABLE")
            if chosen is not None and rule is not None and chosen != rule:
                _fail("INSTRUMENT_RULE_CONFLICT")
            chosen = chosen if chosen is not None else rule
            if type(chosen) is not str or not chosen or chosen != chosen.strip():
                _fail("ORDER_" + name.upper() + "_REQUIRED")
            fields[name] = chosen
        if fields["quantity_unit"] not in {"base", "contracts", "lots", "native"}:
            _fail("ORDER_QUANTITY_UNIT_INVALID")
        offset = order.info.get("offset")
        # Unknown product labels must not silently inherit Base's OPEN default.
        if offset is None and key.product_type.casefold() not in {"spot", "cash"}:
            _fail("ORDER_OFFSET_REQUIRED")
        if offset is not None and offset not in {"open", "close", "close_today", "close_yesterday"}:
            _fail("ORDER_OFFSET_INVALID")
        exchange = order.info.get("exchange_id")
        if exchange is not None and exchange != key.venue:
            _fail("INSTRUMENT_SCOPE")
        reduce_only = order.info.get("reduce_only", False)
        if type(reduce_only) is not bool or (reduce_only and offset in (None, "open")):
            _fail("ORDER_REDUCE_ONLY_INVALID")
        local_notices = binding.host.local_order_notifications()
        for prior_key, prior_order in notice.orders.items():
            if (prior_order.data is not order.data or "reject:" + prior_key in local_notices
                    or "cancel:" + prior_key in local_notices):
                continue  # finalized locally (never sent)
            if _bt_terminal(prior_order):
                continue  # its outcome is known; a stale local record cannot block
            record = binding.host.load_record(prior_key)
            context = binding.host.load_context(prior_key)
            if (record is None or record.state == "UNKNOWN" or not record.generation_current
                    or (record.state == "RESERVED" and context.marker_id is None)):
                _fail("ORDER_RECONCILE_REQUIRED")
        if offset in {"close", "close_today", "close_yesterday"}:
            self._gateway_strategy_position_observation(binding, key, fields["quantity_unit"], order=order)
        self._gateway_require_trade_qualification(order.data, key)
        seq = binding.sequence.allocate(order.ref)
        request_key = "bt-" + binding.sequence.strategy_uuid.replace("-", "") + "-" + str(seq)
        request = OrderRequest(symbol=key.native_symbol, side=Side.BUY if order.isbuy() else Side.SELL,
            order_type=OrderType.LIMIT, quantity=Decimal(str(abs(order.size))),
            account_id=binding.host._binding.account_scope, client_order_id=request_key,
            idempotency_key=request_key, price=Decimal(str(order.price)),
            quantity_unit=fields["quantity_unit"], time_in_force=fields["time_in_force"],
            offset=offset, position_side=order.info.get("position_side"),
            position_mode=order.info.get("position_mode"), reduce_only=reduce_only,
            position_id=order.info.get("position_id"), hedge_flag=order.info.get("hedge_flag"),
            hedge_class=order.info.get("hedge_class"), exchange_id=key.venue)
        from bt_api_base.order_intent import position_intent
        position_intent(request)
        intent = build_gateway_order_intent(binding.host._binding, binding.stream._route, request)
        if order.comminfo is None:
            order.addcomminfo(self.getcommissioninfo(order.data))
        try:
            order.addinfo(gateway_original_bt_ref=order.ref, gateway_instrument_key=key.to_dict(),
                          gateway_execution_time_policy=binding.policy.to_mapping(),
                          gateway_execution_time_policy_digest=binding.policy.digest,
                          gateway_request_key=request_key, gateway_quantity_unit=fields["quantity_unit"],
                          gateway_time_in_force=fields["time_in_force"], gateway_offset=offset,
                          gateway_reduce_only=reduce_only, gateway_exchange_id=key.venue,
                          local_seq=seq)
            order.submit(self)
            snapshot = capture_framework_state(orders={request_key: order}, positions={}, trades={},
                data_by_ref=binding.feeds, owner=binding.strategy, broker=self)
            binding.host.save_submitted_order_intent(intent, local_seq=seq, bt_ref=order.ref,
                                                    snapshot=snapshot)
            self._gateway_register_order(notice, request_key, order)
            self.orders[order.ref] = order
            local = binding.host.local_order_notifications()[request_key]
            order.notification_id, order.replayed = local["notification_id"], False
            self._gateway_notify_local(binding, order)
        except BaseException:
            binding.state = "RESTART_REQUIRED"
            raise
        try:
            binding.reserve_unknown[request_key] = time.monotonic()
            result = binding.api.reserve_order(binding.policy.route, request, timeout_seconds=binding.timeout)
            if result.outcome in ("REQUEST_DENIED", "OBSERVED"):
                binding.reserve_unknown.pop(request_key, None)  # the outcome is known
            if result.outcome == "REQUEST_DENIED":
                # A validated denial: the Gateway created no reservation.
                self._gateway_finalize_rejection(binding, order, request_key, result.code)
                return order
            if result.outcome == "OBSERVED" and result.record is not None and result.record.state == "RESERVED":
                try:
                    market_ref = self._gateway_require_trade_qualification(order.data, key)
                    if not isinstance(market_ref, dict):
                        _fail("FEED_NOT_TRADABLE")
                except Exception:
                    # Nothing was dispatched: withdraw the reservation.
                    binding.state = "FEED_NOT_TRADABLE_AFTER_RESERVE"
                    self._gateway_release_unsent(binding, order, request_key)
                    return order
                result = binding.api.dispatch_order(binding.policy.route, request_key, market_ref=market_ref,
                                                    timeout_seconds=binding.timeout)
                if result.outcome in ("QUEUED", "OBSERVED"):
                    # Only an acknowledged dispatch keeps its reservation; an
                    # uncertain one is read back and withdrawn by version.
                    binding.dispatched.add(request_key)
                if result.outcome == "REQUEST_DENIED":
                    # Refused before the owner queue or any marker: never sent.
                    binding.state = "DISPATCH_DENIED"
                    order.addinfo(gateway_dispatch_denied=result.code)
                    self._gateway_release_unsent(binding, order, request_key)
                    return order
        except BaseException:
            if binding.state != "RESTART_REQUIRED":
                binding.state = "SUBMIT_UNKNOWN"
            raise
        if result.outcome not in ("OBSERVED", "QUEUED"):
            binding.state = "SUBMIT_UNKNOWN"
        return order

    def _gateway_reservation_absent(self, binding, key):
        """Whether "not found" at the Gateway is final for this request key.

        It is for a reserve sent by an earlier process or an earlier session
        (that connection is gone, so the request cannot arrive any more), and
        for one sent by this session long enough ago. A dispatch outcome that
        is unknown is a different case and is never decided here.
        """
        sent = binding.reserve_unknown.get(key)
        return sent is None or time.monotonic() - sent >= _RESERVE_ABSENT_AFTER_SECONDS

    def _gateway_release_unsent(self, binding, order, key):
        """Release a reservation BT never dispatched (or that was refused)."""
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        try:
            result = binding.api.release_order(binding.policy.route, key,
                operation_id="release-" + digest, timeout_seconds=binding.timeout)
        except Exception as error:
            # Unclear outcome: the waiting loop re-reads status and retries the
            # same release operation id, so the order is never left orphaned.
            _logger.warning("gateway release of an unsent reservation failed: %s",
                            type(error).__name__)
            result = None
        if (result is not None and result.outcome == "OBSERVED" and result.record is not None
                and result.record.state == "RELEASED"):
            self._gateway_finalize_release(binding, order, key)
            return True
        # The Gateway may already have expired it (TTL or owner generation): a
        # release reply then carries no release identity; read the status.
        try:
            status = binding.api.command_status(binding.policy.route, key,
                                                timeout_seconds=binding.timeout)
        except Exception as error:
            _logger.warning("gateway status after release failed: %s", type(error).__name__)
            status = None
        if (status is not None and status.outcome == "OBSERVED" and status.record is not None
                and status.record.state == "EXPIRED"):
            self._gateway_finalize_release(binding, order, key)
            return True
        binding.state = "RELEASE_PENDING"
        return False

    def _gateway_finalize_rejection(self, binding, order, key, code):
        from ._btapi_gateway_projection import capture_framework_state

        if order.status == order.Rejected:
            return
        if order.status != order.Submitted or order.executed.size != 0:
            _fail("REJECTION_SCOPE")
        try:
            order.reject(self)
            order.addinfo(gateway_request_denied=code)
            snapshot = capture_framework_state(orders={key: order}, positions={}, trades={},
                data_by_ref=binding.feeds, owner=binding.strategy, broker=self)
            notice = binding.host.save_rejected_order_notification(
                key, bt_ref=order.ref, snapshot=snapshot, code=code)
            order.notification_id, order.replayed = notice["notification_id"], False
            self._gateway_notify_local(binding, order)
        except BaseException:
            binding.state = "RESTART_REQUIRED"
            raise

    def _gateway_cancel_order(self, order):
        binding = self._gateway_stream_binding
        self._gateway_stream_check(binding)
        if binding.sequence is None:
            raise RuntimeError("GATEWAY_WRITE_ADAPTER_UNAVAILABLE")
        notice = self._gateway_binding(binding.strategy, required=True)
        key = self._gateway_request(notice, order)
        order = notice.orders[key]
        record = binding.host.load_record(key)
        if record is None:
            result = binding.api.command_status(binding.policy.route, key, timeout_seconds=binding.timeout)
            if result.outcome != "OBSERVED" or result.record is None:
                binding.state = "CANCEL_UNKNOWN"
                return order
            record = result.record
        if record.state == "RELEASED":
            self._gateway_finalize_release(binding, order, key)
            return order
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        try:
            if record.state == "RESERVED":
                result = binding.api.release_order(binding.policy.route, key,
                    operation_id="release-" + digest, timeout_seconds=binding.timeout)
                if (result.outcome == "OBSERVED" and result.record is not None
                        and result.record.state == "RELEASED"):
                    self._gateway_finalize_release(binding, order, key)
            else:
                result = binding.api.cancel_order(binding.policy.route, key,
                    operation_id="cancel-" + digest, timeout_seconds=binding.timeout)
        except BaseException:
            if binding.state != "RESTART_REQUIRED":
                binding.state = "CANCEL_UNKNOWN"
            raise
        if result.outcome not in ("OBSERVED", "QUEUED"):
            binding.state = "CANCEL_UNKNOWN"
        return order

    def _gateway_finalize_release(self, binding, order, key):
        from ._btapi_gateway_projection import capture_framework_state

        if order.status == order.Canceled:
            return
        if order.status != order.Submitted or order.executed.size != 0:
            _fail("RELEASE_SCOPE")
        try:
            order.cancel()
            snapshot = capture_framework_state(orders={key: order}, positions={}, trades={},
                data_by_ref=binding.feeds, owner=binding.strategy, broker=self)
            notice = binding.host.save_released_order_notification(key, bt_ref=order.ref,
                                                                   snapshot=snapshot)
            order.notification_id, order.replayed = notice["notification_id"], False
            self._gateway_notify_local(binding, order)
        except BaseException:
            binding.state = "RESTART_REQUIRED"
            raise

    def _gateway_stop_working_orders(self):
        """Stopping a Gateway-mode strategy: cancel its own working orders (D62-19).

        Only this strategy's orders are named, each by its original identity
        (an unsent reservation is released instead); nothing is flattened and
        no other strategy's order can be reached through this session. The
        stop then waits up to ``stop_cancel_timeout`` for the venue's answer.

        The summary never calls an order cancelled that was not observed so:
        ``confirmed_terminal`` are orders this process saw end,
        ``awaiting_confirmation`` are cancels that were requested but whose
        answer was not applied before the stop ended (the durable stream
        delivers it at the next start), ``refused`` are cancels that could not
        even be requested (for example while the Gateway is unreachable).
        Returns ``None`` when no Gateway stream is bound.
        """
        binding = self.__dict__.get("_gateway_stream_binding")
        if binding is None:
            return None
        summary = {"cancel_requested": 0, "confirmed_terminal": 0, "awaiting_confirmation": 0,
                   "refused": {}, "unresolved_working_orders": 0}
        try:
            notice = self._gateway_binding(binding.strategy, required=True)
            working = [order for order in notice.orders.values() if order.alive()]
        except Exception as exc:
            summary["refused"][type(exc).__name__] = 1
            summary["unresolved_working_orders"] = None  # the working set could not be read
            return summary
        requested = []
        for order in working:
            try:
                self._gateway_cancel_order(order)
            except Exception as exc:
                code = str(exc) if type(exc) is GatewayExecutionStreamError else type(exc).__name__
                summary["refused"][code] = summary["refused"].get(code, 0) + 1
            else:
                requested.append(order)
        summary["cancel_requested"] = len(requested)
        timeout = getattr(self.p, "stop_cancel_timeout", 10.0)
        timeout = float(timeout) if type(timeout) in (int, float) and math.isfinite(timeout) else 0.0
        deadline = time.monotonic() + max(timeout, 0.0)
        while time.monotonic() < deadline and any(order.alive() for order in requested):
            try:
                self._gateway_stream_next()
            except Exception:
                break
            time.sleep(0.05)
        summary["confirmed_terminal"] = sum(1 for order in requested if not order.alive())
        summary["awaiting_confirmation"] = len(requested) - summary["confirmed_terminal"]
        summary["unresolved_working_orders"] = sum(1 for order in working if order.alive())
        if summary["unresolved_working_orders"]:
            _logger.warning("Gateway stop left %d of this strategy's working orders unresolved "
                         "(%d cancel(s) awaiting confirmation, %d not requested)",
                         summary["unresolved_working_orders"], summary["awaiting_confirmation"],
                         len(working) - len(requested))
        return summary

    def _gateway_unreachable(self, *, reconnect=False):
        """The Gateway session is not usable now: the strategy waits (D63-03).

        A strategy does not stop because its Gateway is paused, restarted or
        unreachable, and never falls back to a direct connection. A session
        that is only momentarily unhealthy comes back by itself. A lost one
        (lease expired, Gateway restarted with a new service epoch) is replaced
        by a new registration; only the per-step path asks for that
        (``reconnect=True``), spaced by the Store's backoff. The strategy ends
        with ``GATEWAY_STREAM_SESSION_LOST`` only when the Store itself was
        stopped or lost its run lock.
        """
        store = self.store
        if not getattr(store, "_gateway_mode", False) or store.is_connected:
            return False
        if store.gateway_session_state() == "LOST":
            if not store.gateway_session_recoverable():
                _fail("SESSION_LOST")
            if reconnect and store.gateway_reconnect():
                return False
        return True

    def _gateway_session_stale(self, binding):
        """The binding still holds a session the Store replaced or is closing."""
        store = self.store
        if not getattr(store, "_gateway_mode", False):
            return False
        return binding.api is not store.gateway_api or binding.api.lifecycle_state != "open"

    def _gateway_rebind_session(self, binding):
        """Adopt the Store's new SDK session after a reconnect (D63-03).

        Only the connection objects change. The durable host, its consumer
        cursor and every order stay; reading resumes after the stored
        sequence. Reservations whose dispatch the old session acknowledged are
        no longer trusted as queued (a restarted Gateway lost its queue): each
        is read back by its original identity and withdrawn or continued as
        the Gateway decides, never re-sent.
        """
        from bt_api_py.gateway_api import GatewayBtApi
        from bt_api_py.gateway_execution_stream_client import GatewayExecutionStreamClient

        api = self.store.gateway_api
        try:
            stream = api.gateway_execution_stream(binding.policy.route)
            valid = (
                type(api) is GatewayBtApi and api._host is binding.host
                and api._exchange_name == binding.policy.route
                and type(stream) is GatewayExecutionStreamClient
                and stream._binding == binding.host._binding
                and stream._consumer_ref == binding.host.load_execution_checkpoint().consumer_ref
            )
        except Exception:
            valid = False
        if not valid:
            binding.state = "RESTART_REQUIRED"
            _fail("SCOPE")
        binding.api, binding.stream = api, stream
        binding.dispatched.clear()
        binding.reserve_unknown.clear()  # requests of the old connection cannot arrive any more

    def _gateway_stream_check(self, binding, *, connected_required=True):
        if binding.pid != os.getpid() or binding.thread is not threading.current_thread():
            _fail("SCOPE")
        if self._gateway_session_stale(binding):
            # The session is being replaced (D63-03): its facade is closed, so
            # only the durable identity can be checked until the per-step path
            # adopts the new one. Nothing may be sent through it.
            if (binding.api._host is not binding.host
                    or binding.stream._binding != binding.host._binding
                    or binding.stream._consumer_ref
                    != binding.host.load_execution_checkpoint().consumer_ref):
                _fail("SCOPE")
            if connected_required:
                _fail("GATEWAY_UNAVAILABLE")
        elif (binding.api._host is not binding.host
                or binding.api.gateway_execution_stream(binding.policy.route) is not binding.stream
                or binding.stream._binding != binding.host._binding
                or binding.stream._consumer_ref != binding.host.load_execution_checkpoint().consumer_ref):
            _fail("SCOPE")
        if connected_required and self._gateway_unreachable():
            # Submits and cancels are refused while the Gateway is unreachable;
            # the per-step path waits instead (I63-E112).
            _fail("GATEWAY_UNAVAILABLE")
        self._gateway_binding(binding.strategy, required=True)
        if self.__dict__.get("_gateway_execution_bindings"):
            _fail("MODE_CONFLICT")

    def _gateway_stream_order(self, binding, key, order, *, allow_unreserved=False):
        from bt_api_py.gateway_order_contract import decode_gateway_order_request

        intent = binding.host.load_intent(key)
        record = binding.host.load_record(key)
        context = binding.host.load_context(key)
        if (intent is None or (record is None and not allow_unreserved) or context is None
                or intent.binding != binding.host._binding
                or intent.route != binding.stream._route
                or (record is not None and (record.binding != intent.binding or record.request_key != key
                or record.digest != intent.digest))
                or type(context.bt_ref) is not int or context.bt_ref !=
                    order.info.get("gateway_original_bt_ref", order.ref)):
            _fail("ORDER_BINDING")
        request = decode_gateway_order_request(json.loads(intent.canonical_payload), intent.binding.account_scope)
        side = "buy" if order.isbuy() else "sell"
        if (request.side.value.lower() != side
                or Decimal(str(abs(order.size))) != request.quantity
                or self._position_key(order.data) != request.symbol):
            _fail("ORDER_BINDING")
        if order.info.get("gateway_request_key") is not None:
            if (order.info.get("gateway_request_key") != key
                    or request.order_type.value != "limit"
                    or Decimal(str(order.price)) != request.price
                    or order.info.get("gateway_quantity_unit") != request.quantity_unit
                    or order.info.get("gateway_time_in_force") != request.time_in_force
                    or order.info.get("gateway_offset") != request.offset
                    or order.info.get("gateway_reduce_only") != request.reduce_only
                    or order.info.get("gateway_exchange_id") != request.exchange_id
                    or order.info.get("position_side") != request.position_side
                    or order.info.get("position_mode") != request.position_mode
                    or order.info.get("position_id") != request.position_id
                    or order.info.get("hedge_flag") != request.hedge_flag
                    or order.info.get("hedge_class") != request.hedge_class):
                _fail("ORDER_BINDING")
        refs = [ref for ref, data in binding.feeds.items() if data is order.data]
        if len(refs) != 1 or binding.instruments[refs[0]].native_symbol != request.symbol:
            _fail("INSTRUMENT_SCOPE")
        saved_key = order.info.get("gateway_instrument_key")
        expected_key = binding.instruments[refs[0]].to_dict()
        original_ref = order.info.get("gateway_original_bt_ref")
        restored = binding.restored or original_ref is not None
        if ((restored and (saved_key != expected_key or type(original_ref) is not int))
                or (not binding.restored and saved_key is not None and saved_key != expected_key)):
            _fail("INSTRUMENT_SCOPE")
        old_policy = order.info.get("gateway_execution_time_policy")
        old_digest = order.info.get("gateway_execution_time_policy_digest")
        if ((restored or old_policy is not None or old_digest is not None)
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
        from ..live_state.gateway_execution_state import verify_gateway_trade_attribution

        intent, record, request = self._gateway_stream_order(binding, event.request_key, order)
        obs = event.observation
        feed_ref = next(ref for ref, data in binding.feeds.items() if data is order.data)
        matched_identity = bool(set(record.strong_identity_key_digests).intersection(obs.binding_key_digests))
        bridged_identity = verify_gateway_trade_attribution(event, record, binding.host._binding)
        request_error = (
            (obs.kind is DirectExecutionEventKind.ORDER_ERROR and event.place_attribution is not None)
            or (obs.kind is DirectExecutionEventKind.CANCEL_ERROR and event.cancel_attribution is not None)
        )
        if (event.reservation_id != record.reservation_id or event.command_digest != intent.digest
                or event.command_principal != intent.binding.principal
                or obs.account_scope != intent.binding.account_scope
                or obs.route != binding.policy.route
                or not (matched_identity or bridged_identity or request_error)
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
        if self._gateway_unreachable(reconnect=True):
            # I63-E112 / D63-03: the Gateway is paused, restarting or
            # unreachable. Wait: no read, ack or local finalization this step
            # (the strategy keeps running; submits are refused). Identity
            # checks still apply.
            self._gateway_stream_check(binding, connected_required=False)
            if binding.state == "RESTART_REQUIRED":
                _fail("RESTART_REQUIRED")
            binding.state = "GATEWAY_UNAVAILABLE"
            return
        if self._gateway_session_stale(binding):
            if binding.state == "RESTART_REQUIRED":
                _fail("RESTART_REQUIRED")
            self._gateway_rebind_session(binding)
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
        if binding.local_deferred:
            self.notifs.extend(binding.local_deferred)
            binding.local_deferred.clear()
        if any(item["status"] == "pending" for item in binding.host.local_order_notifications().values()):
            binding.state = "WAITING_NOTIFICATIONS"
            return
        local_notices = binding.host.local_order_notifications()
        for key in notice.orders:
            if "reject:" + key in local_notices or _bt_terminal(notice.orders[key]):
                # Terminal in BT: nothing left to drive. Skipping them keeps a
                # step O(open orders), not O(all orders) full state loads (E108).
                continue
            record = binding.host.load_record(key)
            if "cancel:" + key in local_notices:
                continue
            if record is not None and record.state in ("RELEASED", "EXPIRED"):
                self._gateway_finalize_release(binding, notice.orders[key], key)
                binding.state = "WAITING_NOTIFICATIONS"
                return
            if record is None or record.state == "UNKNOWN":
                result = binding.api.command_status(binding.policy.route, key,
                                                    timeout_seconds=binding.timeout)
                if (record is None and result.outcome == "REQUEST_DENIED"
                        and result.code == "NOT_FOUND"
                        and self._gateway_reservation_absent(binding, key)):
                    # The reserve reply was lost and the Gateway has no command
                    # under this request key: nothing was reserved, so nothing
                    # can have been sent. The order ends Rejected and is never
                    # re-sent; without this it blocked the strategy for good
                    # (SimNow 2026-11-10, after a Gateway that died mid-reserve).
                    order = notice.orders[key]
                    if order.status == order.Submitted and order.executed.size == 0:
                        self._gateway_finalize_rejection(binding, order, key, "RESERVATION_NOT_FOUND")
                        binding.reserve_unknown.pop(key, None)
                        binding.state = "WAITING_NOTIFICATIONS"
                        return
                if result.outcome != "OBSERVED" or result.record is None:
                    binding.state = "RECOVERY_PENDING"
                    return
                record = result.record
            context = binding.host.load_context(key)
            if record.state == "RESERVED" and (context.marker_id is None
                                               or key not in binding.dispatched):
                # No marker: BT never asked to dispatch. Not dispatched by this
                # process: an earlier process left it; its outcome is settled at
                # the Gateway by version (a dispatch that already won makes the
                # release fail and the order proceeds normally).
                result = binding.api.command_status(binding.policy.route, key,
                                                    timeout_seconds=binding.timeout)
                if result.outcome != "OBSERVED" or result.record is None:
                    binding.state = "RECOVERY_PENDING"
                    return
                if result.record.state == "EXPIRED":
                    self._gateway_finalize_release(binding, notice.orders[key], key)
                    binding.state = "WAITING_NOTIFICATIONS"
                    return
                if result.record.state == "RESERVED":
                    # Never sent (still RESERVED at the Gateway): withdraw it.
                    order = notice.orders[key]
                    if (order.status == order.Submitted and order.executed.size == 0
                            and self._gateway_release_unsent(binding, order, key)):
                        binding.state = "WAITING_NOTIFICATIONS"
                        return
                    binding.state = "RESERVATION_RECOVERY_PENDING"
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
            # A dispatch may return QUEUED while the service already publishes
            # execution events.  Refresh only previously registered request
            # keys; the SDK verifies and persists their command identities.
            # Do not advance the stream cursor until the original key has a
            # durable native identity against which the page can be checked.
            from bt_api_base.gateway_execution_stream_protocol import GatewayExecutionStreamPage
            if type(result.page) is GatewayExecutionStreamPage:
                for event in result.page.events:
                    key = event.request_key
                    if key not in notice.orders:
                        continue  # normal page validation will reject the orphan
                    record = binding.host.load_record(key)
                    if record is None or record.native_identity is None:
                        try:
                            observed = binding.api.command_status(
                                binding.policy.route, key, timeout_seconds=binding.timeout)
                        except Exception:
                            binding.state = "RECOVERY_PENDING"
                            return False
                        record = binding.host.load_record(key)
                        if (observed.outcome != "OBSERVED" or observed.record is None
                                or record != observed.record or record.native_identity is None):
                            binding.state = "RECOVERY_PENDING"
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
        if binding.host.load_record(event.request_key) is None:
            result = binding.api.command_status(binding.policy.route, event.request_key,
                                                timeout_seconds=binding.timeout)
            if result.outcome != "OBSERVED" or result.record is None:
                binding.state = "ORDER_UNAVAILABLE"
                return
        request = self._gateway_stream_event_binding(binding, event, order)
        obs = event.observation
        if obs.kind is DirectExecutionEventKind.TRADE:
            def trade_facts():
                prior, dates, times = [], [], []
                for candidate in self._gateway_stream_events(binding.host):
                    other = candidate.observation
                    if (candidate.request_key == event.request_key
                            and other.trade_key_digest == obs.trade_key_digest):
                        if candidate.sequence < event.sequence and not other.trade_metadata_only:
                            prior.append(candidate)
                        if other.trade_date is not None:
                            dates.append((other.trade_date, candidate.fact_digest))
                        if other.trade_time is not None:
                            times.append((other.trade_time, candidate.fact_digest))
                if len({value for value, _ in dates}) > 1:
                    _fail("TRADE_DATE_CONFLICT")
                if len({value for value, _ in times}) > 1:
                    _fail("TRADE_TIME_CONFLICT")
                return prior, dates, times

            prior, dates, times = trade_facts()
            if (not obs.trade_metadata_only
                    and ((obs.trade_date is None and not dates)
                         or (obs.trade_time is None and not times))
                    and not did_read):
                if not read_once():
                    return
                prior, dates, times = trade_facts()
        if obs.kind is DirectExecutionEventKind.TRADE and not obs.trade_metadata_only:
            if obs.offset != request.offset:
                binding.state = "TRADE_INCOMPLETE"
                return
            date = obs.trade_date or (dates[0][0] if dates else None)
            trade_time = obs.trade_time or (times[0][0] if times else None)
            try:
                stamp = binding.policy.project(date, trade_time)
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
                facts[obs.trade_key_digest] = {"trade_date": date, "trade_time": trade_time,
                    "date_fact_digest": next((f for d, f in dates if d == date), None),
                    "time_fact_digest": next((f for t, f in times if t == trade_time), None)}
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
