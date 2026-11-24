"""Explicit sparse Gateway execution stream consumer for a single BT strategy.

The pending host owns the durable cursor.  Network observations do not by
itself establish venue provenance; callbacks remain on the framework path.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import os
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal, localcontext
from types import MethodType

from ..utils.dateintern import date2num
from ..utils.log_message import get_logger

_logger = get_logger(__name__)


class GatewayExecutionStreamError(RuntimeError):
    """Finite, value-free consumer error."""


@dataclass
class _TradeFactEntry:
    min_non_metadata_seq: int | None = None
    date: str | None = None
    date_digest: str | None = None
    date_conflict: bool = False
    time: str | None = None
    time_digest: str | None = None
    time_conflict: bool = False


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
    # Request keys whose dispatch was acknowledged as queued while the command
    # was still RESERVED, with the monotonic time of the next status read
    # (see _DISPATCH_RECHECK_SECONDS).
    dispatch_recheck: dict = field(default_factory=dict)
    execution_cancel_attempted: set = field(default_factory=set)
    # Earliest monotonic time of the next step after one that found nothing to
    # do (see _IDLE_READ_INTERVAL_SECONDS); a local submit or cancel clears it.
    next_idle_read: float = 0.0
    # Incremental trade-fact cursor and index bound to (host, epoch) so long
    # sessions do not rescan from sequence 0 on every TRADE event.
    trade_fact_host: object = None
    trade_fact_epoch: object = None
    trade_fact_last_sequence: int = 0
    trade_fact_index: dict = field(default_factory=dict)


_STREAM_EVENT_PAGE_SIZE = 256
_STREAM_EVENT_SCAN_LIMIT = 10000


# A stream step that found nothing to do (no Gateway event, no local work) is
# followed by the next one after this pause. A Cerebro live loop can step the
# broker hundreds of times per second, and one step reads the durable local
# state several times and asks the Gateway for events: a single idle strategy
# kept one core busy, starved its own SDK threads and loaded the Gateway enough
# to delay every strategy's market data (SimNow 2026-11-10). A step that
# delivered an event, a local submit and a local cancel are followed by the
# next step at once; while the Gateway is unreachable the wait is paced too.
_IDLE_READ_INTERVAL_SECONDS = 0.2

# A reserve whose reply was lost may still be waiting for the Gateway's owner
# thread. This long after the attempt it can no longer be committed: the
# service bounds the call and the owner's longest native wait is far shorter.
_RESERVE_ABSENT_AFTER_SECONDS = 20.0

# The Gateway acknowledges a dispatch request as queued; the owner then runs it.
# An attempt that ends before the dispatch marker sends nothing and leaves the
# command RESERVED, and nothing reports that to the strategy (I63-E136). While a
# dispatched order is still RESERVED its status is read this often.
_DISPATCH_RECHECK_SECONDS = 2.0


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
        if not store.is_connected:
            # D63-03 before a binding exists (a bar feed binds at its first
            # bar): the bound per-step path is not running yet, so this is the
            # only place that can ask for a new registration. Wait instead of
            # failing; SimNow 2026-11-10: a Gateway restart in the first minute
            # of a 1-minute strategy ended it with GATEWAY_SESSION_UNAVAILABLE.
            self._gateway_waiting_for_session = True
            if store.gateway_session_state() == "LOST":
                if not store.gateway_session_recoverable():
                    _fail("SESSION_LOST")
                store.gateway_reconnect()
            if not store.is_connected:
                return None
        self._gateway_waiting_for_session = False
        config = getattr(store, "gateway_strategy_config", None)
        configured = getattr(config, "instruments_by_ref", None)
        if not isinstance(configured, Mapping) or not configured:
            _fail("CONFIG_UNAVAILABLE")
        data_by_ref = {}
        for ref, instrument in configured.items():
            candidates = [data for data in strategy.datas
                          if self._position_key(data) in (ref, instrument.native_symbol)]
            if len(candidates) != 1 or any(
                existing is candidates[0] for existing in data_by_ref.values()
            ):
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
            if getattr(api, "risk_selected", False) is True:
                # Pending state v7 (delegated command records) only with Risk.
                host.upgrade_for_risk_routing()
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
                    elif (not self._is_market_data_only() and host.load_record(key) is not None
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

    def gateway_risk_summary(self):
        """Risk section of the Gateway execution summary (local view, no RPC).

        ``selected`` follows the strategy's configuration (D64-01).
        ``available`` is the SDK client's local reserve-route registration
        and runtime health observation. It is None when Risk is not selected,
        the facade is absent, or it has no boolean observation; a selected
        route whose local registration check fails reports False. It does not
        verify remote risk sources, order admission, or trading safety.
        ``refusals`` counts the Risk-path refusal codes this process projected.
        """
        store = self.store
        config = getattr(store, "gateway_strategy_config", None)
        selected = getattr(config, "risk_selection", None) is not None
        available = None
        if selected:
            api = getattr(store, "gateway_api", None)
            value = getattr(api, "risk_available", None) if api is not None else None
            available = value if type(value) is bool else None
        refusals = dict(self.__dict__.get("_gateway_risk_refusals") or {})
        return {"selected": selected, "available": available, "refusals": refusals}

    def gateway_execution_stream_status(self):
        binding = self.__dict__.get("_gateway_stream_binding")
        if binding is None:
            if self.__dict__.get("_gateway_waiting_for_session"):
                return "GATEWAY_UNAVAILABLE"
            return "WAITING_FEED" if self.__dict__.get("_gateway_waiting_for_feed") else "UNBOUND"
        if self._gateway_unreachable() or self._gateway_session_stale(binding):
            self._gateway_stream_check(binding, connected_required=False)
            return "GATEWAY_UNAVAILABLE"
        self._gateway_stream_check(binding)
        return binding.state

    def _gateway_notify_local(self, binding, order):
        binding.next_idle_read = 0.0  # local work: the next step runs at once
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
        from ..feeds.base_btapi_feed import BaseBtApiFeed
        from ..feeds.btapifeed import FeedTradeQualification
        from ..feeds.direct_btapi_feed import DirectBtApiFeed

        source = data.data if isinstance(data, DataClone) else data
        if (not isinstance(source, BaseBtApiFeed) or isinstance(source, DirectBtApiFeed)
                or getattr(data, "replaying", False)
                or getattr(source, "replaying", False)):
            _fail("FEED_NOT_TRADABLE")
        try:
            if BaseBtApiFeed.check_historical_warmup_active(source):
                _fail("FEED_NOT_TRADABLE")
            verdict = BaseBtApiFeed.check_gateway_trade_qualification(
                source, expected_store=self.store, expected_instrument=instrument
            )
        except Exception:
            _fail("FEED_NOT_TRADABLE")
        if (type(verdict) is not FeedTradeQualification or verdict.ok is not True
                or verdict.live is not True or verdict.reasons != ()
                or type(verdict.expires_monotonic_ns) is not int
                or time.monotonic_ns() >= verdict.expires_monotonic_ns):
            _logger.warning(
                "gateway trade qualification failed: ok=%s live=%s reasons=%s",
                getattr(verdict, "ok", None),
                getattr(verdict, "live", None),
                getattr(verdict, "reasons", None),
            )
            logging.getLogger("bt_api_ctp").warning(
                "gateway trade qualification failed: ok=%s live=%s reasons=%s",
                getattr(verdict, "ok", None),
                getattr(verdict, "live", None),
                getattr(verdict, "reasons", None),
            )
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

    def _gateway_strategy_position_observation(self, binding, instrument, unit, *, order=None,
                                               close=None):
        """Read a freshly authenticated observation for this exact strategy.

        ``order`` asks for the close capacity of that order; ``close`` is
        ``(order side, offset)`` and asks for the capacity of that bucket
        without an order (the closable view).
        """
        from bt_api_py.gateway_strategy_position import (
            GatewayStrategyPositionObservation, GatewayStrategyPositionResult,
        )

        try:
            if order is None and close is None:
                result = binding.api.get_strategy_position(binding.policy.route, instrument,
                    quantity_unit=unit, timeout_seconds=binding.timeout)
            elif order is None:
                # The Gateway's capacity does not depend on the asked quantity.
                result = binding.api.get_strategy_close_capacity(binding.policy.route, instrument,
                    quantity_unit=unit, side=close[0], offset=close[1], quantity=Decimal(1),
                    position_side=None, timeout_seconds=binding.timeout)
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
                        binding.policy.route, observation, max_age_seconds=5.0)):
                _fail("STRATEGY_POSITION_UNAVAILABLE")
            if order is not None and (observation.strategy_close_available is None
                    or observation.strategy_close_available < Decimal(str(abs(order.size)))):
                _fail("STRATEGY_CLOSE_UNAVAILABLE")
            return observation
        except GatewayExecutionStreamError:
            raise
        except Exception:
            _fail("STRATEGY_POSITION_UNAVAILABLE")

    def _gateway_position_scope(self, data):
        """(binding, instrument, quantity unit) of a bound feed, from its declared rules."""
        from bt_api_base.market_protocol import MarketInstrumentKey

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
        return binding, instrument, unit

    @staticmethod
    def _gateway_exact_float(size):
        try:
            value = float(size)
        except (ValueError, OverflowError):
            _fail("STRATEGY_POSITION_PRECISION_UNAVAILABLE")
        if not math.isfinite(value) or Decimal(str(value)) != size:
            _fail("STRATEGY_POSITION_PRECISION_UNAVAILABLE")
        return value

    def get_closable(self, data, side):
        """Closable view of one side; in Gateway mode from this strategy's own ledger.

        Same keys as the direct view (``None`` means unknown, never zero), so a
        strategy plans explicit close offsets the same way in both modes
        (D62-18/22/26). ``total``/``today``/``yesterday`` are what the strategy
        itself holds on that side. ``closable_today``/``closable_yesterday``
        and ``closable`` are what the Gateway would let it close with
        ``close_today``/``close_yesterday``/``close`` now, after its own
        working close orders; an offset the venue's rule does not accept (a
        plain ``close`` on SHFE/INE, a bucket close while the buckets are only
        projected) is unknown. Nothing here is an account total, and none of it
        reserves capacity: the Gateway decides again when the order arrives.
        """
        if not getattr(self.store, "_gateway_mode", False):
            return super().get_closable(data, side)
        if side not in ("long", "short"):
            _fail("STRATEGY_POSITION_SIDE_REQUIRED")
        if self.__dict__.get("_gateway_stream_binding") is None:
            self._gateway_auto_bind()
        binding, instrument, unit = self._gateway_position_scope(data)
        observation = self._gateway_strategy_position_observation(binding, instrument, unit)
        with localcontext() as context:
            context.prec = 160
            today = getattr(observation, side + "_today")
            yesterday = getattr(observation, side + "_yesterday")
            total = today + yesterday
        view = {"total": self._gateway_exact_float(total), "today": self._gateway_exact_float(today),
                "yesterday": self._gateway_exact_float(yesterday), "frozen_close": None,
                "closable": None, "closable_today": None, "closable_yesterday": None,
                "venue": instrument.venue}
        order_side = "sell" if side == "long" else "buy"
        for name, offset in (("closable", "close"), ("closable_today", "close_today"),
                             ("closable_yesterday", "close_yesterday")):
            try:
                capacity = self._gateway_strategy_position_observation(
                    binding, instrument, unit, close=(order_side, offset))
            except GatewayExecutionStreamError:
                continue  # this offset is not usable now: unknown, never zero
            if (capacity.strategy_close_available is None or capacity.strategy_close_reserved is None
                    or getattr(capacity, side + "_today") != today
                    or getattr(capacity, side + "_yesterday") != yesterday):
                continue  # the position moved between the reads: unknown
            view[name] = self._gateway_exact_float(capacity.strategy_close_available)
            view["frozen_close"] = self._gateway_exact_float(capacity.strategy_close_reserved)
        return view

    def _gateway_position_view(self, data, side=None):
        from ..position import Position

        binding, instrument, unit = self._gateway_position_scope(data)
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
        value = self._gateway_exact_float(size)
        return Position(size=value, price=float("nan") if value else 0.0)

    def _gateway_submit_order(self, order):
        if self._is_market_data_only():
            return self._market_data_only_submit(order)
        from bt_api_py._contracts.models import OrderRequest, OrderType, Side
        from bt_api_py.gateway_direct_client import build_gateway_order_intent
        from ._btapi_gateway_projection import capture_framework_state
        from ..order import Order

        binding = self._gateway_stream_binding
        if binding is None:
            _fail("FEED_NOT_READY")
        if any(len(data) < 1 for data in binding.feeds.values()):
            _fail("FEED_NOT_READY")
        binding.next_idle_read = 0.0  # local work: the next step runs at once
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
        # This is a local call-contract check, not a source or admission proof.
        # Preserve the returned bound callable so a later attribute lookup
        # cannot silently select a different reserve implementation.
        execution_selected = getattr(binding.api, "execution_selected", False)
        if type(execution_selected) is not bool:
            _fail("EXECUTION_CONFIGURATION_UNAVAILABLE")
        try:
            config = getattr(self.store, "gateway_strategy_config", None)
            configured_risk = None
            if config is not None:
                configured_risk = getattr(config, "risk_selection") is not None
            elif getattr(self.store, "_gateway_mode", False) is True:
                raise ValueError
            missing = object()
            risk_routed = getattr(binding.api, "risk_selected", missing)
            if (type(risk_routed) is not bool
                    or (configured_risk is not None and configured_risk != risk_routed)):
                raise ValueError
            risk_reserve = None
            risk_save = None
            if risk_routed and not execution_selected:
                capability = getattr(binding.api, "risk_first_send_reserve_contract", None)
                contract = capability() if callable(capability) else None
                if (type(contract) is not tuple or len(contract) != 3
                        or type(contract[0]) is not str
                        or contract[0] != "local-first-send-ticket-v1"
                        or type(contract[1]) is not MethodType
                        or contract[1].__self__ is not binding.api):
                    raise ValueError
                host_contract = contract[2]
                if (type(host_contract) is not tuple or len(host_contract) != 4
                        or type(host_contract[0]) is not str
                        or host_contract[0] != "local-first-send-host-v1"
                        or any(type(method) is not MethodType or method.__self__ is not binding.host
                               for method in host_contract[1:])):
                    raise ValueError
                risk_reserve = contract[1]
                risk_save = host_contract[1]
        except Exception:
            _fail("RISK_TICKET_CONTRACT_UNSUPPORTED")
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
            if prior_order.data is not order.data:
                continue
            if "reject:" + prior_key in local_notices or "cancel:" + prior_key in local_notices:
                continue  # finalized locally (never sent)
            if _bt_terminal(prior_order):
                continue  # its outcome is known; a stale local record cannot block
            prior_route = binding.host.load_execution_route(prior_key)
            if prior_route is not None and prior_route.kind in ("PENDING", "EXECUTION_PARENT"):
                _fail("ORDER_RECONCILE_REQUIRED")
            if ((prior_route is not None and prior_route.kind == "RISK")
                    or (prior_route is None and prior_order.info.get("gateway_risk_routed") is True)):
                # A local status or notice does not prove all prior hosts and
                # in-flight commands are covered. A trusted cross-generation
                # contract is required before another order on this feed.
                _fail("ORDER_RECONCILE_REQUIRED")
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
        # D64-01: with Risk selected this PLACE goes through Risk only (the SDK
        # facade never falls back to the Gateway). The durable marker keeps the
        # order off the own-command paths after a restart, in any selection.
        configuration_id = None
        if execution_selected:
            try:
                configuration_id = binding.api.execution_configuration_id
            except Exception:
                _fail("EXECUTION_CONFIGURATION_UNAVAILABLE")
            if type(configuration_id) is not str or not configuration_id:
                _fail("EXECUTION_CONFIGURATION_UNAVAILABLE")
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
            if risk_routed:
                order.addinfo(gateway_risk_routed=True)
            order.submit(self)
            snapshot = capture_framework_state(orders={request_key: order}, positions={}, trades={},
                data_by_ref=binding.feeds, owner=binding.strategy, broker=self)
            if execution_selected:
                first_send_ticket = binding.host.save_execution_routing_intent(
                    intent, local_seq=seq, bt_ref=order.ref, snapshot=snapshot,
                    configuration_id=configuration_id)
            else:
                save_submitted = risk_save if risk_routed else binding.host.save_submitted_order_intent
                first_send_ticket = save_submitted(intent, local_seq=seq, bt_ref=order.ref, snapshot=snapshot)
            self._gateway_register_order(notice, request_key, order)
            self.orders[order.ref] = order
            local = binding.host.local_order_notifications()[request_key]
            order.notification_id, order.replayed = local["notification_id"], False
            self._gateway_notify_local(binding, order)
        except BaseException:
            binding.state = "RESTART_REQUIRED"
            raise
        if execution_selected:
            from bt_api_py.execution_routing import ExecutionRoutingOutcome, ExecutionRoutingResult
            try:
                routed = binding.api.route_execution_order(
                    binding.policy.route, intent,
                    before_submit=lambda prepared: binding.host.bind_execution_parent_route(request_key, prepared))
                if type(routed) is not ExecutionRoutingResult:
                    raise ValueError("EXECUTION_RESULT_INVALID")
                if routed.outcome is ExecutionRoutingOutcome.DIRECT_PATH:
                    if getattr(self, "_strict_gateway_no_direct_path", False):
                        # D62S-05 (Scheme A2): strict GatewayBtApiBroker forbids DIRECT_PATH bypass.
                        order.reject(self)
                        order.addinfo(
                            execution_routing_outcome="EXECUTION_REJECTED",
                            execution_rejection_code="GATEWAY_DIRECT_PATH_BYPASS_FORBIDDEN",
                        )
                        self._gateway_notify_local(binding, order)
                        return order
                    if risk_routed:
                        contract = binding.api.risk_first_send_reserve_contract()
                        if (type(contract) is not tuple or len(contract) != 3
                                or contract[0] != "local-first-send-ticket-v1"
                                or type(contract[1]) is not MethodType
                                or contract[1].__self__ is not binding.api
                                or type(contract[2]) is not tuple or len(contract[2]) != 4
                                or contract[2][0] != "local-first-send-host-v1"
                                or any(type(method) is not MethodType or method.__self__ is not binding.host
                                       for method in contract[2][1:])):
                            raise ValueError("RISK_TICKET_CONTRACT_UNSUPPORTED")
                        risk_reserve = contract[1]
                    if binding.host.bind_execution_direct_route(
                            request_key, route_kind="RISK" if risk_routed else "GATEWAY",
                            direct_decision=routed.direct_decision) is not True:
                        raise ValueError("EXECUTION_ROUTE_BIND_FAILED")
                elif routed.outcome is ExecutionRoutingOutcome.EXECUTION_REJECTED:
                    # The opaque SDK token is consumed by the host in the same
                    # transaction that persists the rejection and its notice.
                    rejected = order.clone()
                    rejected.info = copy.copy(order.info)
                    rejected.reject(self)
                    rejected.addinfo(execution_routing_outcome="EXECUTION_REJECTED",
                                     execution_rejection_code=routed.code)
                    rejected_snapshot = capture_framework_state(
                        orders={request_key: rejected}, positions={}, trades={},
                        data_by_ref=binding.feeds, owner=binding.strategy, broker=self)
                    local = binding.host.reject_execution_before_submit(
                        request_key, bt_ref=order.ref, snapshot=rejected_snapshot,
                        code=routed.code, rejection_decision=routed.rejection_decision)
                    order.reject(self)
                    order.addinfo(execution_routing_outcome="EXECUTION_REJECTED",
                                  execution_rejection_code=routed.code)
                    order.notification_id, order.replayed = local["notification_id"], False
                    self._gateway_notify_local(binding, order)
                    return order
                else:
                    saved_route = binding.host.load_execution_route(request_key)
                    if (routed.outcome is ExecutionRoutingOutcome.EXECUTION_LOCAL_RECEIPT
                            and (routed.source != "SDK_LOCAL" or routed.code is not None
                                 or routed.execution_state is not None
                                 or saved_route is None or saved_route.kind != "EXECUTION_PARENT"
                                 or routed.request_id != saved_route.request_id
                                 or routed.request_sha256 != saved_route.request_sha256
                                 or routed.parent_ref != saved_route.parent_ref)):
                        raise ValueError("EXECUTION_RECEIPT_MISMATCH")
                    order.addinfo(execution_routing_outcome=routed.outcome.value)
                    binding.state = "EXECUTION_RECOVERY_PENDING"
                    return order
            except Exception:
                binding.state = "EXECUTION_RECOVERY_PENDING"
                order.addinfo(execution_routing_outcome="EXECUTION_UNKNOWN")
                return order
        try:
            binding.reserve_unknown[request_key] = time.monotonic()
            if risk_routed:
                result = risk_reserve(
                    binding.policy.route, request, timeout_seconds=binding.timeout,
                    first_send_ticket=first_send_ticket)
            else:
                result = binding.api.reserve_order(
                    binding.policy.route, request, timeout_seconds=binding.timeout)
            if result.outcome in ("REQUEST_DENIED", "OBSERVED"):
                binding.reserve_unknown.pop(request_key, None)  # the outcome is known
            if result.outcome == "REQUEST_DENIED":
                # A validated denial: the Gateway created no reservation. With
                # Risk selected (D64-01) the refusal may be Risk's own, or Risk
                # being unavailable (D64-02); nothing reached the Gateway then.
                risk_code = getattr(result, "risk_code", None)
                if type(risk_code) is str:
                    refusals = self.__dict__.setdefault("_gateway_risk_refusals", {})
                    refusals[risk_code] = refusals.get(risk_code, 0) + 1
                risk_denied = getattr(result, "risk_denied", None)
                self._gateway_finalize_rejection(
                    binding, order, request_key, result.code,
                    info=None if risk_denied is None else {"risk_denied": risk_denied})
                return order
            if (risk_routed and result.outcome == "OBSERVED" and result.record is not None
                    and result.record.state == "RESERVED"):
                # PREPARED: Risk's permit and the Gateway reservation it holds
                # for this strategy are durable before anything else, then the
                # delegate principal is read once from the Gateway.
                self._gateway_risk_prepare(binding, request_key, result.record)
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
                if risk_routed:
                    # Durable "asked to dispatch" before the request (the own
                    # path's pre-dispatch marker): never released blindly later.
                    prepared = binding.host.load_delegated_command(request_key)
                    binding.host.save_delegated_command(request_key,
                        reservation_id=prepared.reservation_id, digest=prepared.digest,
                        dispatch_requested=True)
                result = binding.api.dispatch_order(binding.policy.route, request_key, market_ref=market_ref,
                                                    timeout_seconds=binding.timeout)
                if result.outcome in ("QUEUED", "OBSERVED"):
                    # Only an acknowledged dispatch keeps its reservation; an
                    # uncertain one is read back and withdrawn by version.
                    binding.dispatched.add(request_key)
                    if risk_routed:
                        self._gateway_risk_learn(binding, request_key)
                if result.outcome == "REQUEST_DENIED":
                    # Refused before the owner queue or any marker: never sent.
                    binding.state = "DISPATCH_DENIED"
                    order.addinfo(gateway_dispatch_denied=result.code)
                    risk_denied = getattr(result, "risk_denied", None)
                    if risk_denied is not None:
                        order.addinfo(risk_denied=risk_denied)
                    risk_code = getattr(result, "risk_code", None)
                    if type(risk_code) is str:
                        refusals = self.__dict__.setdefault("_gateway_risk_refusals", {})
                        refusals[risk_code] = refusals.get(risk_code, 0) + 1
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
        if self._is_market_data_only():
            binding.state = "OBSERVATION_ONLY_RECOVERY_PENDING"
            return False
        if order.info.get("gateway_risk_routed") is True:
            return self._gateway_risk_release_unsent(binding, order, key)
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

    def _gateway_finalize_rejection(self, binding, order, key, code, info=None):
        from ._btapi_gateway_projection import capture_framework_state

        if self._is_market_data_only():
            binding.state = "OBSERVATION_ONLY_RECOVERY_PENDING"
            return
        if order.status == order.Rejected:
            return
        if order.status != order.Submitted or order.executed.size != 0:
            _fail("REJECTION_SCOPE")
        try:
            order.reject(self)
            # A Risk refusal names itself (risk_denied, lowercase) instead of
            # gateway_request_denied; the persisted notice keeps ``code``.
            order.addinfo(**(info if info is not None else {"gateway_request_denied": code}))
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
        if self._is_market_data_only():
            return self._market_data_only_cancel(order)
        binding = self._gateway_stream_binding
        binding.next_idle_read = 0.0  # local work: the next step runs at once
        self._gateway_stream_check(binding)
        if binding.sequence is None:
            raise RuntimeError("GATEWAY_WRITE_ADAPTER_UNAVAILABLE")
        notice = self._gateway_binding(binding.strategy, required=True)
        key = self._gateway_request(notice, order)
        order = notice.orders[key]
        route = binding.host.load_execution_route(key)
        if route is not None and route.kind == "EXECUTION_REJECTED":
            return order
        if route is not None and route.kind in ("PENDING", "EXECUTION_PARENT"):
            if route.kind == "EXECUTION_PARENT":
                try:
                    if (binding.api.execution_selected is True
                            and binding.api.execution_configuration_id == route.configuration_id):
                        intent = binding.host.load_intent(key)
                        if intent is not None:
                            binding.execution_cancel_attempted.add(key)
                            binding.api.cancel_execution_order(binding.policy.route, intent)
                except Exception:
                    pass
            binding.state = "EXECUTION_RECOVERY_PENDING"
            return order
        if (route is not None and route.kind == "RISK") or (route is None and order.info.get("gateway_risk_routed") is True):
            return self._gateway_risk_cancel(binding, order, key)
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

        if self._is_market_data_only():
            binding.state = "OBSERVATION_ONLY_RECOVERY_PENDING"
            return
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

    # --- Orders placed through the Risk service (iteration 64, pending state v7) ---
    #
    # The Gateway holds such an order as a command of the Risk delegate on
    # behalf of this strategy and writes its returns into this strategy's own
    # stream. Backtrader keeps a delegated command record per request key and
    # binds a return only to a key it recorded as Risk-routed, under the
    # delegate principal the Gateway reported for that key.

    def _gateway_risk_prepare(self, binding, key, permit):
        if self._is_market_data_only():
            _fail("MARKET_DATA_ONLY")
        intent = binding.host.load_intent(key)
        binding.host.save_delegated_command(key, reservation_id=permit.reservation_id,
            digest=intent.digest, permit_id=permit.permit_id, view_digest=permit.view_digest)
        self._gateway_risk_learn(binding, key)

    def _gateway_risk_observation(self, binding, key):
        """One direct.delegated_command_status read, checked against this strategy."""
        try:
            result = binding.api.delegated_command_status(binding.policy.route, key,
                                                          timeout_seconds=binding.timeout)
        except Exception as error:
            _logger.warning("delegated command status failed: %s", type(error).__name__)
            return None
        observation = getattr(result, "observation", None)
        if result.outcome != "OBSERVED" or observation is None:
            return None
        own = binding.host._binding
        intent = binding.host.load_intent(key)
        if (intent is None or observation.request_key != key
                or observation.account_scope != own.account_scope
                or observation.strategy_scope != own.strategy_scope
                or observation.digest != intent.digest
                or observation.actor_principal == own.principal):
            binding.state = "RISK_BINDING_CONFLICT"
            return None
        return observation

    def _gateway_risk_learn(self, binding, key):
        """Persist the delegate principal (once) and the observed command state."""
        record = binding.host.load_delegated_command(key)
        if record is None:
            return None
        observation = self._gateway_risk_observation(binding, key)
        if observation is None:
            return None
        if (observation.reservation_id != record.reservation_id
                or (record.actor_principal is not None
                    and observation.actor_principal != record.actor_principal)):
            # Never bind under another principal or reservation than recorded.
            binding.state = "RISK_BINDING_CONFLICT"
            return None
        if observation.state in ("RELEASED", "EXPIRED", "NOT_SENT", "UNKNOWN"):
            # A status from any generation does not prove earlier commands
            # were drained. Preserve the durable record and occupied order.
            binding.state = "RISK_RECOVERY_PENDING"
            return None
        try:
            binding.host.save_delegated_command(key, reservation_id=record.reservation_id,
                digest=record.digest, actor_principal=observation.actor_principal,
                gateway_state=observation.state, gateway_version=observation.version)
        except ValueError:
            binding.state = "RISK_BINDING_CONFLICT"
            return None
        return observation

    def _gateway_risk_release_unsent(self, binding, order, key):
        """Keep an unsent claim until cross-generation absence is established."""
        # No available contract proves a prior host cannot still dispatch this
        # key. Do not send release or infer a terminal order from its status.
        binding.state = "RELEASE_PENDING"
        return False

    def _gateway_risk_cancel(self, binding, order, key):
        """Cancel through this strategy's delegated Gateway operations, never via Risk."""
        if self._is_market_data_only():
            return self._market_data_only_cancel(order)
        record = binding.host.load_delegated_command(key)
        if record is None:
            # Risk's reserve outcome is not known yet: nothing to name.
            binding.state = "CANCEL_UNKNOWN"
            return order
        if record.gateway_state in ("RELEASED", "EXPIRED", "NOT_SENT"):
            # Retain the stored record; its terminal status is not proof that
            # an earlier generation was drained.
            binding.state = "CANCEL_UNKNOWN"
            return order
        self._gateway_risk_learn(binding, key)
        record = binding.host.load_delegated_command(key)
        if record.gateway_state in (None, "RESERVED"):
            # Not dispatched: withdraw it through Risk, which decides against a
            # concurrent dispatch atomically; a dispatch that won proceeds.
            if not self._gateway_risk_release_unsent(binding, order, key):
                binding.state = "CANCEL_UNKNOWN"
            return order
        if record.actor_principal is None:
            binding.state = "CANCEL_UNKNOWN"
            return order
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        try:
            result = binding.api.cancel_order(binding.policy.route, key,
                operation_id="cancel-" + digest, timeout_seconds=binding.timeout)
        except BaseException:
            if binding.state != "RESTART_REQUIRED":
                binding.state = "CANCEL_UNKNOWN"
            raise
        if result.outcome not in ("OBSERVED", "QUEUED"):
            binding.state = "CANCEL_UNKNOWN"
        return order

    def _gateway_risk_recover(self, binding, order, key):
        """A Risk-routed key without a record: Risk's reserve outcome was not learned.

        Read Risk (risk.order.status) and the Gateway
        (direct.delegated_command_status) for diagnostics; nothing is resent.
        Neither observation can establish the missing cross-generation binding.
        The outcome stays UNKNOWN and blocks new orders on the instrument until
        a trusted recovery contract is available (D63-04).
        """
        if order.status != order.Submitted or order.executed.size != 0:
            return
        observation = self._gateway_risk_observation(binding, key)
        answer = None
        status = getattr(binding.api, "risk_order_status", None)
        if callable(status):
            try:
                call = status(binding.policy.route, key, timeout_seconds=binding.timeout)
                answer = call.answer if call.outcome == "ANSWERED" else None
            except Exception as error:
                _logger.warning("risk order status failed: %s", type(error).__name__)
        if observation is not None:
            if answer is not None and answer.outcome == "DENIED":
                # Both claims name this key but disagree about whether a
                # command exists. Without a cross-generation proof neither
                # may make this order terminal or free its instrument.
                binding.state = "RISK_BINDING_CONFLICT"
                return
        # A later non-denial cannot clear an earlier conflict: neither status
        # source proves it covers every prior host or in-flight request. Do not
        # create a local delegated record from these observations.
        if binding.state != "RISK_BINDING_CONFLICT":
            binding.state = "RISK_RECOVERY_PENDING"

    def _gateway_risk_step(self, binding, notice, key):
        """Drive one open Risk-routed order; True stops this step (like the own path)."""
        order = notice.orders[key]
        record = binding.host.load_delegated_command(key)
        if record is None:
            # A missing local record does not exclude an earlier host's command.
            # Wait without holding up the other orders' returns.
            self._gateway_risk_recover(binding, order, key)
            if order.status == order.Rejected:
                binding.state = "WAITING_NOTIFICATIONS"
                return True
            return False
        undispatched = not record.dispatch_requested or key not in binding.dispatched
        if record.actor_principal is None or (record.gateway_state in (None, "RESERVED")
                                              and undispatched):
            if self._gateway_risk_learn(binding, key) is None:
                if binding.state != "RISK_BINDING_CONFLICT":
                    binding.state = "RISK_RECOVERY_PENDING"
                # Still read other orders and matching execution events; the
                # event path checks its binding before applying or ACKing.
                return False
            record = binding.host.load_delegated_command(key)
        if record.gateway_state in ("RELEASED", "EXPIRED", "NOT_SENT", "UNKNOWN"):
            binding.state = "RISK_RECOVERY_PENDING"
            return False
        if record.gateway_state == "RESERVED" and undispatched:
            # A prior host may still have an in-flight dispatch. Keep the
            # reservation and continue processing independently bound events.
            if (order.status == order.Submitted and order.executed.size == 0
                    and self._gateway_risk_release_unsent(binding, order, key)):
                binding.state = "WAITING_NOTIFICATIONS"
                return True
            binding.state = "RISK_RECOVERY_PENDING"
            return False
        if record.gateway_state in (None, "RESERVED"):
            # Dispatched by this process and still RESERVED: read it back now
            # and then, without treating a terminal status as not-sent proof.
            now = time.monotonic()
            due = binding.dispatch_recheck.get(key)
            if due is None:
                binding.dispatch_recheck[key] = now + _DISPATCH_RECHECK_SECONDS
            elif now >= due:
                binding.dispatch_recheck[key] = now + _DISPATCH_RECHECK_SECONDS
                self._gateway_risk_learn(binding, key)
        return False

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
        if self._is_market_data_only():
            summary["unresolved_working_orders"] = len(working)
            if working:
                summary["refused"]["market_data_only"] = len(working)
            return summary
        requested = []
        attempted_unknown = []
        for order in working:
            try:
                key = self._gateway_request(notice, order)
                binding.execution_cancel_attempted.discard(key)
                self._gateway_cancel_order(order)
            except Exception as exc:
                code = str(exc) if type(exc) is GatewayExecutionStreamError else type(exc).__name__
                summary["refused"][code] = summary["refused"].get(code, 0) + 1
            else:
                route = binding.host.load_execution_route(key)
                if route is not None and route.kind in ("PENDING", "EXECUTION_PARENT"):
                    if key in binding.execution_cancel_attempted:
                        attempted_unknown.append(order)
                    else:
                        summary["refused"]["EXECUTION_CANCEL_UNRESOLVED"] = (
                            summary["refused"].get("EXECUTION_CANCEL_UNRESOLVED", 0) + 1)
                else:
                    requested.append(order)
        summary["cancel_requested"] = len(requested)
        if attempted_unknown:
            summary["cancel_attempted_unknown"] = len(attempted_unknown)
        timeout = getattr(self.p, "stop_cancel_timeout", 10.0)
        timeout = float(timeout) if type(timeout) in (int, float) and math.isfinite(timeout) else 0.0
        deadline = time.monotonic() + max(timeout, 0.0)
        while time.monotonic() < deadline and any(order.alive() for order in requested + attempted_unknown):
            try:
                self._gateway_stream_next()
            except Exception:
                break
            time.sleep(0.05)
        summary["confirmed_terminal"] = sum(1 for order in requested + attempted_unknown if not order.alive())
        summary["awaiting_confirmation"] = sum(1 for order in requested + attempted_unknown if order.alive())
        summary["unresolved_working_orders"] = sum(1 for order in working if order.alive())
        if summary["unresolved_working_orders"]:
            _logger.warning("Gateway stop left %d of this strategy's working orders unresolved "
                         "(%d cancel(s) awaiting confirmation, %d not requested)",
                         summary["unresolved_working_orders"], summary["awaiting_confirmation"],
                         len(working) - len(requested) - len(attempted_unknown))
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
        self._reset_gateway_trade_facts(binding)

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
        delegated = None
        route = binding.host.load_execution_route(key)
        risk_route = ((route is not None and route.kind == "RISK")
                      or (route is None and order.info.get("gateway_risk_routed") is True))
        if record is None and risk_route:
            # A Risk-placed order: its delegated command record stands in.
            delegated = binding.host.load_delegated_command(key)
        historical_execution = False
        if (allow_unreserved and intent is not None and route is not None
                and route.kind in ("PENDING", "EXECUTION_PARENT", "EXECUTION_REJECTED")
                and intent.route != binding.stream._route):
            # Project a durable Execution order under a new run, without
            # changing the saved intent or authorizing a write. A parent also
            # needs its original SDK journal binding, checked read-only.
            try:
                snapshot = binding.host.load_order_snapshot(key)
                same_route = replace(intent.route, scope=replace(
                    intent.route.scope, run_id=binding.stream._route.scope.run_id)) == binding.stream._route
                historical_execution = (same_route and type(snapshot) is dict and context is not None
                    and snapshot.get("bt_ref") == context.bt_ref
                    and snapshot.get("local_seq") == context.local_seq
                    and route.request_key == key and route.intent_digest == intent.digest
                    and binding.host.load_intent(key) == intent)
                if historical_execution and route.kind == "EXECUTION_PARENT":
                    from bt_api_py.execution_routing import ExecutionPreparedRoute
                    prepared = ExecutionPreparedRoute(
                        account=route.account, strategy=route.strategy, request_key=route.request_key,
                        intent_digest=route.intent_digest, request_id=route.request_id,
                        request_sha256=route.request_sha256, configuration_id=route.configuration_id,
                        execution_domain_ref=route.execution_domain_ref, parent_ref=route.parent_ref)
                    historical_execution = binding.api.verify_execution_parent_route(intent, prepared) is True
            except Exception:
                historical_execution = False
        if (intent is None or (record is None and delegated is None and not allow_unreserved)
                or context is None
                or intent.binding != binding.host._binding
                or (intent.route != binding.stream._route and not historical_execution)
                or (record is not None and (record.binding != intent.binding or record.request_key != key
                or record.digest != intent.digest))
                or (delegated is not None and (delegated.request_key != key
                    or delegated.digest != intent.digest))
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
        return intent, (record if record is not None else delegated), request

    def _gateway_stream_events(self, host, after=0, *, page_size=None, max_events=None):
        # Bound each incremental scan to avoid unbounded per-tick CPU/memory use
        # and guard against non-advancing page sources.
        page_limit = _STREAM_EVENT_PAGE_SIZE if page_size is None else page_size
        scan_limit = _STREAM_EVENT_SCAN_LIMIT if max_events is None else max_events
        count = 0
        while True:
            page = host.read_execution_events(after_sequence=after, limit=page_limit)
            if not page:
                return
            last_seq = after
            for event in page:
                if event.sequence <= last_seq:
                    _fail("SCAN_LIMIT")
                last_seq = event.sequence
                count += 1
                if count > scan_limit:
                    _fail("SCAN_LIMIT")
                yield event
            after = last_seq
            if len(page) < page_limit:
                return

    @staticmethod
    def _ensure_gateway_trade_facts(binding):
        if not hasattr(binding, "trade_fact_index"):
            binding.trade_fact_host = None
            binding.trade_fact_epoch = None
            binding.trade_fact_last_sequence = 0
            binding.trade_fact_index = {}

    @staticmethod
    def _reset_gateway_trade_facts(binding):
        binding.trade_fact_host = None
        binding.trade_fact_epoch = None
        binding.trade_fact_last_sequence = 0
        index = getattr(binding, "trade_fact_index", None)
        if index is None:
            binding.trade_fact_index = {}
        else:
            index.clear()

    @staticmethod
    def _index_gateway_trade_fact(binding, candidate):
        other = candidate.observation
        key = (candidate.request_key, other.trade_key_digest)
        entry = binding.trade_fact_index.get(key)
        if entry is None:
            entry = _TradeFactEntry()
            binding.trade_fact_index[key] = entry
        if not other.trade_metadata_only and (
            entry.min_non_metadata_seq is None
            or candidate.sequence < entry.min_non_metadata_seq
        ):
            entry.min_non_metadata_seq = candidate.sequence
        if other.trade_date is not None:
            if entry.date is None:
                entry.date = other.trade_date
                entry.date_digest = candidate.fact_digest
            elif entry.date != other.trade_date:
                entry.date_conflict = True
        if other.trade_time is not None:
            if entry.time is None:
                entry.time = other.trade_time
                entry.time_digest = candidate.fact_digest
            elif entry.time != other.trade_time:
                entry.time_conflict = True

    def _refresh_gateway_trade_facts(self, binding, checkpoint, *, target_sequence=0):
        self._ensure_gateway_trade_facts(binding)
        if (
            binding.trade_fact_host is not binding.host
            or binding.trade_fact_epoch != checkpoint.epoch
            or checkpoint.stored_sequence < binding.trade_fact_last_sequence
        ):
            self._reset_gateway_trade_facts(binding)
            binding.trade_fact_host = binding.host
            binding.trade_fact_epoch = checkpoint.epoch
        ceiling = max(checkpoint.stored_sequence, target_sequence)
        if binding.trade_fact_last_sequence >= ceiling:
            return
        for candidate in self._gateway_stream_events(
            binding.host, after=binding.trade_fact_last_sequence
        ):
            self._index_gateway_trade_fact(binding, candidate)
            binding.trade_fact_last_sequence = candidate.sequence

    @staticmethod
    def _gateway_host_pass_snapshot(host):
        """Read durable pending state once for one ``_gateway_stream_next`` pass.

        Falls back to individual host methods if any of them was overridden on
        the instance or class (for example by test doubles).
        """
        from ..live_state.gateway_execution_route import GatewayExecutionRoute
        from ..live_state.gateway_pending import GatewayPendingHost

        if type(host) is not GatewayPendingHost:
            return None
        inst_dict = vars(host)
        for name in (
            "local_order_notifications",
            "load_execution_route",
            "load_record",
            "load_context",
        ):
            if name in inst_dict:
                return None
            func = GatewayPendingHost.__dict__.get(name)
            if func is None or getattr(func, "__module__", None) != GatewayPendingHost.__module__:
                return None

        with host._store._lock():
            state = host._store._load()
            entries = host._check_state(state)
            version = state["version"]
            gateway = state["gateway"]
            local_notices = (
                gateway["local_notifications"] if version in (6, 7, 8) else {}
            )
            routes = gateway["execution_routes"] if version == 8 else {}
            has_pending_local = any(
                item["status"] == "pending" for item in local_notices.values()
            )
            notice_keys = frozenset(local_notices)
            execution_routes = {
                key: GatewayExecutionRoute(**value) for key, value in routes.items()
            }
            return {
                "has_pending_local": has_pending_local,
                "notice_keys": notice_keys,
                "execution_routes": execution_routes,
                "entries": entries,
            }

    @staticmethod
    def _gateway_snapshot_record(host, pass_snapshot, key):
        from ..live_state.gateway_pending import _record

        entry = pass_snapshot["entries"].get(key)
        return (
            None
            if entry is None or entry["record"] is None
            else _record(entry["record"], host._binding)
        )

    @staticmethod
    def _gateway_snapshot_context(pass_snapshot, key):
        from ..live_state.gateway_pending import GatewayPendingContext

        entry = pass_snapshot["entries"].get(key)
        if entry is None:
            return None
        return GatewayPendingContext(entry["marker_id"], entry["local_seq"], entry["bt_ref"])

    @staticmethod
    def _resolve_execution_parent_child_key(binding, notice, request_key):
        if request_key in notice.orders:
            return None
        if type(request_key) is not str or not request_key.startswith("exec-child-"):
            return None
        from ..live_state.gateway_execution_state import _execution_parent_child_key

        for parent_key in notice.orders:
            route = binding.host.load_execution_route(parent_key)
            if (
                route is not None
                and route.kind == "EXECUTION_PARENT"
                and type(route.parent_ref) is str
                and route.parent_ref
                and _execution_parent_child_key(route.parent_ref) == request_key
            ):
                return parent_key
        return None

    def _gateway_execution_parent_event_binding(self, binding, event, order, parent_key):
        from ..live_state.gateway_execution_state import _expected_execution_parent_child_digest

        intent, _, request = self._gateway_stream_order(
            binding, parent_key, order, allow_unreserved=True
        )
        obs = event.observation
        feed_ref = next(ref for ref, data in binding.feeds.items() if data is order.data)
        payload = json.loads(intent.canonical_payload)
        expected_digest = _expected_execution_parent_child_digest(payload, event.request_key)
        if (
            type(event.command_principal) is not str
            or not event.command_principal
            or event.command_principal == intent.binding.principal
            or type(event.reservation_id) is not str
            or not event.reservation_id
            or event.command_digest != expected_digest
            or obs.account_scope != intent.binding.account_scope
            or obs.route != binding.policy.route
            or request.symbol != obs.instrument.native_symbol
            or obs.instrument != binding.instruments[feed_ref]
            or (request.instrument is not None and request.instrument != obs.instrument)
            or (obs.side is not None and obs.side != request.side.value.lower())
            or (obs.offset is not None and obs.offset != request.offset)
            or (
                obs.order_quantity is not None
                and Decimal(obs.order_quantity) != request.quantity
            )
        ):
            _fail("EVENT_BINDING")
        return request

    def _gateway_stream_event_binding(self, binding, event, order):
        from bt_api_base.direct_write_protocol import DirectExecutionEventKind
        from ..live_state.gateway_execution_state import verify_gateway_trade_attribution

        from ..live_state.gateway_order_state import GatewayDelegatedCommandRecord

        intent, record, request = self._gateway_stream_order(binding, event.request_key, order)
        obs = event.observation
        feed_ref = next(ref for ref, data in binding.feeds.items() if data is order.data)
        if type(record) is GatewayDelegatedCommandRecord:
            # Placed through Risk: bound by request key, reservation, digest and
            # the delegate principal persisted for this key (the delegate's own
            # identity keys are not visible to this strategy).
            principal = record.actor_principal
            identified = principal is not None and principal != intent.binding.principal
        else:
            principal = intent.binding.principal
            matched_identity = bool(set(record.strong_identity_key_digests).intersection(obs.binding_key_digests))
            bridged_identity = verify_gateway_trade_attribution(event, record, binding.host._binding)
            request_error = (
                (obs.kind is DirectExecutionEventKind.ORDER_ERROR and event.place_attribution is not None)
                or (obs.kind is DirectExecutionEventKind.CANCEL_ERROR and event.cancel_attribution is not None)
            )
            identified = matched_identity or bridged_identity or request_error
        if (event.reservation_id != record.reservation_id or event.command_digest != intent.digest
                or event.command_principal != principal
                or obs.account_scope != intent.binding.account_scope
                or obs.route != binding.policy.route
                or not identified
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
        if time.monotonic() < binding.next_idle_read:
            return  # the previous step found nothing to do; the state stands
        if self._gateway_unreachable(reconnect=True):
            # I63-E112 / D63-03: the Gateway is paused, restarting or
            # unreachable. Wait: no read, ack or local finalization this step
            # (the strategy keeps running; submits are refused). Identity
            # checks still apply.
            self._gateway_stream_check(binding, connected_required=False)
            if binding.state == "RESTART_REQUIRED":
                _fail("RESTART_REQUIRED")
            binding.state = "GATEWAY_UNAVAILABLE"
            binding.next_idle_read = time.monotonic() + _IDLE_READ_INTERVAL_SECONDS
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
        if any(len(data) < 1 for data in binding.feeds.values()):
            # Multi-feed live Cerebro can temporarily rewind a secondary feed
            # on bar 1 (di.rewind() -> len(data) == 0). Defer local/stream
            # notifications until every bound feed holds at least one bar so
            # capture_framework_state() sees valid feed snapshots.
            binding.next_idle_read = 0.0
            binding.state = "WAITING_FEEDS"
            return
        if binding.local_deferred:
            self.notifs.extend(binding.local_deferred)
            binding.local_deferred.clear()
        pass_snapshot = self._gateway_host_pass_snapshot(binding.host)
        if pass_snapshot is not None:
            if pass_snapshot["has_pending_local"]:
                binding.state = "WAITING_NOTIFICATIONS"
                return
            local_notice_keys = pass_snapshot["notice_keys"]
        else:
            local_notices = binding.host.local_order_notifications()
            if any(item["status"] == "pending" for item in local_notices.values()):
                binding.state = "WAITING_NOTIFICATIONS"
                return
            local_notice_keys = local_notices
        snapshot_dirty = False
        risk_recovery_state = None
        for key, order in notice.orders.items():
            if snapshot_dirty:
                if pass_snapshot is not None:
                    pass_snapshot = self._gateway_host_pass_snapshot(binding.host)
                    local_notice_keys = (
                        pass_snapshot["notice_keys"]
                        if pass_snapshot is not None
                        else binding.host.local_order_notifications()
                    )
                else:
                    local_notice_keys = binding.host.local_order_notifications()
                snapshot_dirty = False
            if self._is_market_data_only() and order.alive():
                # Keep restored work untouched. Stream observations can still
                # be consumed, but recovery must not release or infer a local
                # terminal result from a missing reservation.
                risk_recovery_state = "OBSERVATION_ONLY_RECOVERY_PENDING"
                continue
            if pass_snapshot is not None:
                execution_route = pass_snapshot["execution_routes"].get(key)
            else:
                execution_route = binding.host.load_execution_route(key)
            if execution_route is not None and execution_route.kind in ("PENDING", "EXECUTION_PARENT"):
                if _bt_terminal(order):
                    continue
                # Query the original intent only. Missing records and NOT_FOUND
                # never establish that a parent was not sent.
                try:
                    if (binding.api.execution_selected is True
                            and binding.api.execution_configuration_id == execution_route.configuration_id):
                        from bt_api_py.execution_routing import ExecutionRoutingStatus
                        status = binding.api.execution_order_status(
                            binding.policy.route, binding.host.load_intent(key))
                        if type(status) is not ExecutionRoutingStatus:
                            raise ValueError("EXECUTION_STATUS_INVALID")
                        if (execution_route.kind == "EXECUTION_PARENT" and status.routed
                                and (status.request_id != execution_route.request_id
                                     or status.request_sha256 != execution_route.request_sha256
                                     or status.parent_ref != execution_route.parent_ref)):
                            raise ValueError("EXECUTION_STATUS_MISMATCH")
                except Exception:
                    pass
                risk_recovery_state = "EXECUTION_RECOVERY_PENDING"
                continue
            is_risk = (
                (execution_route is not None and execution_route.kind == "RISK")
                or (execution_route is None and order.info.get("gateway_risk_routed") is True)
            )
            if "reject:" + key in local_notice_keys or _bt_terminal(order):
                # Historical Risk terminal state lacks a cross-host proof.
                # Keep processing the stream, but do not label it healthy.
                if is_risk:
                    risk_recovery_state = risk_recovery_state or "RISK_RECOVERY_PENDING"
                continue
            if is_risk:
                # Placed through Risk: driven by its delegated command record,
                # never by the own-command paths below.
                # Re-evaluate stale state for this order; retain the most
                # restrictive unresolved state across this entire pass.
                if binding.state in ("RISK_RECOVERY_PENDING", "RISK_BINDING_CONFLICT"):
                    binding.state = "ACTIVE"
                if self._gateway_risk_step(binding, notice, key):
                    return
                snapshot_dirty = True
                if binding.state == "RISK_BINDING_CONFLICT":
                    risk_recovery_state = "RISK_BINDING_CONFLICT"
                elif (binding.state == "RISK_RECOVERY_PENDING"
                      and risk_recovery_state is None):
                    risk_recovery_state = "RISK_RECOVERY_PENDING"
                continue
            if "cancel:" + key in local_notice_keys:
                continue
            if pass_snapshot is not None:
                record = self._gateway_snapshot_record(binding.host, pass_snapshot, key)
            else:
                record = binding.host.load_record(key)
            if record is not None and record.state in ("RELEASED", "EXPIRED"):
                self._gateway_finalize_release(binding, order, key)
                binding.state = "WAITING_NOTIFICATIONS"
                return
            if record is None or record.state == "UNKNOWN":
                result = binding.api.command_status(binding.policy.route, key,
                                                    timeout_seconds=binding.timeout)
                snapshot_dirty = True
                if (record is None and result.outcome == "REQUEST_DENIED"
                        and result.code == "NOT_FOUND"
                        and self._gateway_reservation_absent(binding, key)):
                    # The reserve reply was lost and the Gateway has no command
                    # under this request key: nothing was reserved, so nothing
                    # can have been sent. The order ends Rejected and is never
                    # re-sent; without this it blocked the strategy for good
                    # (SimNow 2026-11-10, after a Gateway that died mid-reserve).
                    if order.status == order.Submitted and order.executed.size == 0:
                        self._gateway_finalize_rejection(binding, order, key, "RESERVATION_NOT_FOUND")
                        binding.reserve_unknown.pop(key, None)
                        binding.state = "WAITING_NOTIFICATIONS"
                        return
                if result.outcome != "OBSERVED" or result.record is None:
                    binding.state = "RECOVERY_PENDING"
                    return
                record = result.record
            if record.state == "RESERVED":
                if pass_snapshot is not None and not snapshot_dirty:
                    context = self._gateway_snapshot_context(pass_snapshot, key)
                else:
                    context = binding.host.load_context(key)
                if context.marker_id is None or key not in binding.dispatched:
                    # No marker: BT never asked to dispatch. Not dispatched by this
                    # process: an earlier process left it; its outcome is settled at
                    # the Gateway by version (a dispatch that already won makes the
                    # release fail and the order proceeds normally).
                    result = binding.api.command_status(binding.policy.route, key,
                                                        timeout_seconds=binding.timeout)
                    snapshot_dirty = True
                    if result.outcome != "OBSERVED" or result.record is None:
                        binding.state = "RECOVERY_PENDING"
                        return
                    if result.record.state == "EXPIRED":
                        self._gateway_finalize_release(binding, order, key)
                        binding.state = "WAITING_NOTIFICATIONS"
                        return
                    if result.record.state == "RESERVED":
                        # Never sent (still RESERVED at the Gateway): withdraw it.
                        if (order.status == order.Submitted and order.executed.size == 0
                                and self._gateway_release_unsent(binding, order, key)):
                            binding.state = "WAITING_NOTIFICATIONS"
                            return
                        binding.state = "RESERVATION_RECOVERY_PENDING"
                        return
                else:
                    # Dispatched by this process and acknowledged as queued, yet still
                    # RESERVED. Once the Gateway says the reservation can no longer be
                    # dispatched (its time is over, or it belongs to an older owner
                    # generation) it is withdrawn like any unsent one. A dispatch that
                    # won meanwhile makes the release fail and the order proceeds.
                    now = time.monotonic()
                    due = binding.dispatch_recheck.get(key)
                    if due is None:
                        binding.dispatch_recheck[key] = now + _DISPATCH_RECHECK_SECONDS
                    elif now >= due:
                        binding.dispatch_recheck[key] = now + _DISPATCH_RECHECK_SECONDS
                        result = binding.api.command_status(binding.policy.route, key,
                                                            timeout_seconds=binding.timeout)
                        snapshot_dirty = True
                        if result.outcome != "OBSERVED" or result.record is None:
                            binding.state = "RECOVERY_PENDING"
                            return
                        current = result.record
                        if current.state == "EXPIRED":
                            binding.dispatch_recheck.pop(key, None)
                            self._gateway_finalize_release(binding, order, key)
                            binding.state = "WAITING_NOTIFICATIONS"
                            return
                        # expiry_pending also covers a reservation of an older owner
                        # generation: the record carries no remaining time for one.
                        if current.state == "RESERVED" and current.expiry_pending:
                            if (order.status == order.Submitted and order.executed.size == 0
                                    and self._gateway_release_unsent(binding, order, key)):
                                binding.dispatch_recheck.pop(key, None)
                                binding.dispatched.discard(key)
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
                    if self._resolve_execution_parent_child_key(binding, notice, key) is not None:
                        continue
                    if key not in notice.orders:
                        continue  # normal page validation will reject the orphan
                    route = binding.host.load_execution_route(key)
                    if route is not None and route.kind in ("PENDING", "EXECUTION_PARENT", "EXECUTION_REJECTED"):
                        binding.state = "EXECUTION_EVENT_UNBOUND"
                        return False
                    if (route is not None and route.kind == "RISK") or (route is None and notice.orders[key].info.get("gateway_risk_routed") is True):
                        # A Risk-placed order's returns bind only under the
                        # delegate principal persisted for its key.
                        delegated = binding.host.load_delegated_command(key)
                        if delegated is not None and delegated.actor_principal is None:
                            self._gateway_risk_learn(binding, key)
                            delegated = binding.host.load_delegated_command(key)
                        if delegated is None or delegated.actor_principal is None:
                            if binding.state != "RISK_BINDING_CONFLICT":
                                binding.state = "RECOVERY_PENDING"
                            return False
                        continue
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
            self._ensure_gateway_trade_facts(binding)
            if (
                checkpoint.stored_sequence - binding.trade_fact_last_sequence
                >= max(1, _STREAM_EVENT_SCAN_LIMIT // 2)
            ):
                self._refresh_gateway_trade_facts(binding, checkpoint)
            return True

        events = binding.host.read_execution_events(limit=1)
        if not events:
            if not read_once():
                return
            events = binding.host.read_execution_events(limit=1)
            if not events:
                binding.next_idle_read = time.monotonic() + _IDLE_READ_INTERVAL_SECONDS
                binding.state = risk_recovery_state or "ACTIVE"
                return
        binding.next_idle_read = 0.0
        event = events[0]
        parent_key = self._resolve_execution_parent_child_key(binding, notice, event.request_key)
        order_key = parent_key if parent_key is not None else event.request_key
        order = notice.orders.get(order_key)
        if order is None:
            binding.state = "ORDER_UNAVAILABLE"
            return
        route = binding.host.load_execution_route(order_key)
        if route is not None and route.kind in ("PENDING", "EXECUTION_REJECTED"):
            binding.state = "EXECUTION_EVENT_UNBOUND"
            return
        if route is not None and route.kind == "EXECUTION_PARENT":
            if parent_key is None:
                binding.state = "EXECUTION_EVENT_UNBOUND"
                return
            request = self._gateway_execution_parent_event_binding(
                binding, event, order, parent_key
            )
        else:
            if (route is not None and route.kind == "RISK") or (
                route is None and order.info.get("gateway_risk_routed") is True
            ):
                delegated = binding.host.load_delegated_command(event.request_key)
                if delegated is None or delegated.actor_principal is None:
                    binding.state = "ORDER_UNAVAILABLE"
                    return
            elif binding.host.load_record(event.request_key) is None:
                result = binding.api.command_status(
                    binding.policy.route, event.request_key, timeout_seconds=binding.timeout
                )
                if result.outcome != "OBSERVED" or result.record is None:
                    binding.state = "ORDER_UNAVAILABLE"
                    return
            request = self._gateway_stream_event_binding(binding, event, order)
        obs = event.observation
        if obs.kind is DirectExecutionEventKind.TRADE:
            def trade_facts():
                self._refresh_gateway_trade_facts(
                    binding, checkpoint, target_sequence=event.sequence
                )
                entry = binding.trade_fact_index.get(
                    (event.request_key, obs.trade_key_digest)
                )
                if entry is None:
                    return False, [], []
                if entry.date_conflict:
                    _fail("TRADE_DATE_CONFLICT")
                if entry.time_conflict:
                    _fail("TRADE_TIME_CONFLICT")
                has_prior = (
                    entry.min_non_metadata_seq is not None
                    and entry.min_non_metadata_seq < event.sequence
                )
                dates = [] if entry.date is None else [(entry.date, entry.date_digest)]
                times = [] if entry.time is None else [(entry.time, entry.time_digest)]
                return has_prior, dates, times

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
            binding.state = risk_recovery_state or "ACTIVE"
        except BaseException:
            binding.state = "RESTART_REQUIRED"
            raise
