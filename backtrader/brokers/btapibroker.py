#!/usr/bin/env python
"""Unified bt_api_py-backed live broker."""

from __future__ import annotations

import collections
import datetime as _dt
import math
import re
import threading
import time
from collections.abc import Mapping
from copy import copy, deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, DefaultDict, Dict, List, Optional

from ..broker import BrokerBase
from ..comminfo import (
    ComminfoFuturesFixed,
    ComminfoFuturesInverse,
    ComminfoFuturesMixed,
    ComminfoFuturesPercent,
)
from ..commissions.ctpoption import CtpOptionPremium, OptionAccountingError
from ..order import BuyOrder, OrderBase, OrderData, OrderExecutionBit, SellOrder
from ..position import Position
from ..position_modes import (
    POSITION_MODE_DUAL_SIDE,
    infer_position_side,
    normalize_order_position_meta,
    normalize_position_mode,
    normalize_position_offset,
    normalize_position_side,
    signed_position_size,
)
from ..stores.btapistore import _redact_diagnostic
from ..stores.managed_execution import (
    CtpManagedProjectionState,
    ManagedExecutionAdapterError,
    parse_ctp_managed_execution_projection,
)
from ..stores.service_execution_adapter import ServiceExecutionReadError
from ..utils.dateintern import date2num
from ..utils.log_message import get_logger

logger = get_logger(__name__)
_LOGGING_HEALTH: "collections.Counter[str]" = collections.Counter()


def _safe_log(level, message, *args):
    """Write diagnostics without letting a log sink alter broker semantics."""
    try:
        getattr(logger, level)(_redact_diagnostic(message), *map(_redact_diagnostic, args))
    except Exception:
        # No logging here by design: the sink itself just failed; calling the
        # logger again would raise before the health counter is incremented.
        _LOGGING_HEALTH["logging_errors"] += 1


_REMOTE_ORDER_ID_KEYS = (
    "external_order_id",
    "externalOrderId",
    "venue_order_id",
    "venueOrderId",
    "ordId",
    "orderID",
    "order_id",
    "orderId",
    "OrderID",
    "OrderSysID",
    "id",
    "ticket",
)
_REMOTE_TRADE_ORDER_ID_KEYS = (
    "external_order_id",
    "externalOrderId",
    "venue_order_id",
    "venueOrderId",
    "ordId",
    "orderID",
    "order_id",
    "orderId",
    "OrderID",
    "OrderSysID",
    "order",
    "ticket",
)
_REMOTE_CLIENT_ORDER_REF_KEYS = (
    "order_ref",
    "orderRef",
    "ctp_order_ref",
    "OrderRef",
    "client_order_id",
    "clientOrderId",
    "newClientOrderId",
    "origClientOrderId",
    "clOrdId",
    "origClOrdId",
    "orderLinkId",
    "origOrderLinkId",
)
_DATA_NAME_KEYS = (
    "data_name",
    "dataname",
    "symbol",
    "instrument",
    "instId",
    "inst_id",
    "InstrumentID",
    "instrument_id",
    "name",
)
_CTP_EXCHANGES = frozenset({"SHFE", "DCE", "CZCE", "CFFEX", "INE", "GFEX"})
_POSITION_SIZE_KEYS = (
    "volume",
    "size",
    "position",
    "position_size",
    "positionSize",
    "position_qty",
    "positionQty",
    "positionAmt",
    "position_amt",
    "qty",
    "quantity",
    "pos",
    "Position",
    "Volume",
    "Qty",
    "Quantity",
)
_POSITION_DIRECTION_KEYS = (
    "direction",
    "Direction",
    "side",
    "Side",
    "position_side",
    "positionSide",
    "positionIdx",
    "position_idx",
    "posSide",
    "PositionSide",
    "position_direction",
    "positionDirection",
    "PosiDirection",
    "posi_direction",
)
_POSITION_PRICE_KEYS = (
    "price",
    "Price",
    "avg_price",
    "avgPrice",
    "avgPx",
    "average_price",
    "averagePrice",
    "entry_price",
    "entryPrice",
    "open_price",
    "openAvgPx",
)
_FILL_QTY_KEYS = (
    "size",
    "volume",
    "trade_volume",
    "last_qty",
    "lastQty",
    "exec_qty",
    "execQty",
    "execution_qty",
    "fill_size",
    "fillSize",
    "fill_qty",
    "fillQty",
    "fillSz",
    "lastSz",
    "qty",
    "quantity",
    "sz",
)
_CUMULATIVE_FILL_QTY_KEYS = (
    "filled",
    "cum_qty",
    "cumQty",
    "cum_filled_qty",
    "cumFilledQty",
    "cum_quantity",
    "cumulative_qty",
    "cumulative_quantity",
    "filled_qty",
    "filled_quantity",
    "filledVolume",
    "FilledVolume",
    "traded",
    "traded_volume",
    "volume_traded",
    "VolumeTraded",
    "accFillSz",
    "acc_fill_sz",
    "accFillSize",
    "acc_fill_size",
)
_SUBMIT_FILL_QTY_KEYS = (
    *_CUMULATIVE_FILL_QTY_KEYS,
    "volume",
    "fillSz",
    "fill_size",
    "fillSize",
    "fill_qty",
    "fillQty",
    "qty",
    "quantity",
    "sz",
)
_FILL_PRICE_KEYS = (
    "price",
    "Price",
    "fill_price",
    "fillPrice",
    "fill_px",
    "fillPx",
    "exec_price",
    "execPrice",
    "execution_price",
    "executionPrice",
    "trade_price",
    "tradePrice",
    "avg_price",
    "avgPrice",
    "avgPx",
    "average_price",
    "averagePrice",
    "last_price",
    "lastPrice",
    "lastPx",
    "px",
)


class BtApiBroker(BrokerBase):
    """Broker implementation that routes live orders through BtApiStore."""

    # Remote order updates do not depend on the arrival of a market-data bar.
    next_without_bar = True

    params = (
        ("store", None),
        ("provider", "btapi"),
        ("cash", 0.0),
        ("value", None),
        ("account_refresh_interval", 1.0),
        ("positions_refresh_interval", 1.0),
        ("position_sync_policy", "periodic"),
        ("position_audit_interval", 0.0),
        ("open_orders_refresh_interval", 1.0),
        ("cancel_wait_remote", False),
        ("cancel_confirmation_timeout", 1.0),
        ("cancel_retry_max_attempts", 3),
        ("reconcile_retry_max_attempts", 3),
        ("reconcile_retry_backoff", 0.05),
        ("force_refresh_queries", True),
        ("validation_enabled", True),
        ("contract_metadata", None),
        ("max_order_size", 0),
        ("cash_check_enabled", True),
        ("cash_buffer", 0.0),
        ("cash_check_safety_factor", 1.0),
        ("pending_trade_update_limit", 256),
        ("position_mode", "net"),
        ("sdk_preflight", True),
        ("shutdown_timeout", 2.0),
        ("flatten_on_stop", True),
        # A read-only observation session may hydrate an account that already
        # has exposure.  It must never route any order mutation, including a
        # risk-reducing close or a cancellation during shutdown.
        ("market_data_only", False),
        # Optional, provider-neutral summary collected before the broker
        # starts.  Observation shutdown reports its validation separately
        # from any final remote reconciliation.
        ("startup_account_state", None),
        ("approval_expires_at_utc", None),
        ("approval_max_order_count", None),
        ("require_complete_ctp_evidence", False),
        ("ctp_quote_max_age_seconds", 2.0),
        ("execution_recovery", None),
    )

    def __init__(self, **kwargs):
        """Initialize the broker, set up order/position state and freeze position mode.

        The constructor wires the broker to its underlying
        :class:`BtApiStore`, allocates the in-memory collections used to
        track orders, positions (split by long/short leg in dual-side
        mode) and outbound notifications, and seeds the cash/value
        snapshots that :meth:`getcash` / :meth:`getvalue` will report
        before the first :meth:`start`.

        Args:
            **kwargs: Parameter overrides. Any key matching a name in
                :attr:`params` overrides the corresponding default; unknown
                keys are forwarded to the :class:`BrokerBase` constructor.
        """
        super().__init__(**kwargs)
        self.store = self.p.store
        self.provider = self.p.provider
        self.notifs: collections.deque = collections.deque()
        self.orders = collections.OrderedDict()
        self._service_execution_session = None
        self._recovery_queued_receipts = set()
        self._recovery_applied_receipts = set()
        self._recovery_orders_by_intent = {}
        self._recovery_pending_snapshot_notifications = {}
        self._service_execution_recovery_feeds = {}
        self._service_execution_recovery_feed_names = {}
        self._service_execution_recovery_strategy = None
        self._service_execution_recovery_suppress_notifications = False
        self._managed_refresh_order_queue = collections.deque()
        self.positions = collections.defaultdict(Position)
        self.long_positions = collections.defaultdict(Position)
        self.short_positions = collections.defaultdict(Position)
        self._cash = float(self.p.cash or 0.0)
        self._value = float(self.p.value if self.p.value is not None else self._cash)
        self._live_started = False
        self._startup_ready = False
        self.startingcash = self._cash
        self.startingvalue = self._value
        self._last_account_refresh = 0.0
        self._last_positions_refresh = 0.0
        self._positions_snapshot_loaded = False
        if self.p.position_sync_policy not in {"periodic", "startup"}:
            raise ValueError("position_sync_policy must be periodic or startup")
        self._last_open_orders_refresh = 0.0
        self._last_position_audit = 0.0
        self._position_audit_mismatch = None
        self._position_audit_error = None
        self._position_audit_blocked = False
        self._trading_enabled = not bool(self.p.market_data_only)
        self._startup_account_state_evidence = self._normalise_startup_account_state(
            self.p.startup_account_state
        )
        self._strategy_paused = False
        # Market-data-only is a hard local write boundary.  Keep a public,
        # credential-free audit of rejected strategy write attempts so a
        # bounded observation can distinguish "no attempt" from "attempted
        # but stopped before reaching the Store".
        self._market_data_only_rejections: collections.Counter[str] = collections.Counter()
        self._approval_lock = threading.Lock()
        self._approval_operation_count = 0
        self._approval_expires_at_utc = self._parse_approval_expiry(self.p.approval_expires_at_utc)
        maximum_approved_orders = self.p.approval_max_order_count
        if maximum_approved_orders is None:
            self._approval_max_order_count = None
        elif (
            isinstance(maximum_approved_orders, bool)
            or not isinstance(maximum_approved_orders, int)
            or maximum_approved_orders <= 0
        ):
            raise ValueError("approval_max_order_count must be a positive integer")
        else:
            self._approval_max_order_count = maximum_approved_orders
        if (self._approval_expires_at_utc is None) != (self._approval_max_order_count is None):
            raise ValueError(
                "approval_expires_at_utc and approval_max_order_count must be configured together"
            )
        self._contract_metadata = {
            str(key): dict(value or {}) for key, value in (self.p.contract_metadata or {}).items()
        }
        self._orders_by_external_id = {}
        self._orders_by_client_ref = {}
        self._remote_open_orders_snapshot = []
        self._seen_trade_ids = set()
        self._quarantined_trade_ids = set()
        self._order_execution_contracts = {}
        self._pending_trade_updates: collections.deque[Any] = collections.deque()
        self._position_mode_frozen = False
        self._position_mode_frozen_reason = None
        self._sdk_readiness = {}
        self._last_reconcile_result: Optional[Dict[str, Any]] = None
        self._periodic_reconcile_pending = False
        self._ctp_reconciliation_required = False
        self._ctp_reconciliation_rounds = 0
        self._ctp_reconciliation_fingerprint = None
        self._ctp_reconciliation_generation = None
        self._ctp_reconciliation_account_fingerprint = None
        self._ctp_reconciliation_request_ids = None
        self._ctp_reconciliation_unknown_intent_count = None
        self._ctp_reconciliation_unmatched_trade_count = None
        self._ctp_reconciliation_event_epoch = 0
        self._ctp_reconciliation_round_event_epoch = None
        self._ctp_reconciliation_reason = ""
        self._ctp_reconciliation_pending = False
        self._ctp_reconciliation_callbacks = []
        self._last_ctp_reconciliation_result = None
        self._execution_recovery_completion_pending = False
        self._execution_recovery_completion_callbacks = []
        self._execution_recovery_completion_lock = threading.RLock()
        self._execution_recovery_completion_receipt = None
        self._last_execution_recovery_completion = None
        self._execution_recovery_close_attempted = False
        self._execution_recovery_aborted = False
        self._execution_recovery_abort_result = None
        self._shutdown_summary = {"status": "NOT_STARTED"}
        self._execution_recovery = deepcopy(self.p.execution_recovery)
        BrokerBase.set_param(
            self, "position_mode", normalize_position_mode(self.get_param("position_mode"))
        )

    def _validate_execution_recovery_startup(self, remote_open_orders):
        """Bind hydrated broker state to the SDK-owned recovery plan."""

        recovery = self._execution_recovery
        getter = getattr(self.store, "get_execution_recovery_snapshot", None)
        current = getter() if callable(getter) else None
        if not isinstance(recovery, dict) or current != recovery:
            raise ValueError("SDK recovery plan is missing or changed before broker startup")
        if not bool(getattr(self.store, "execution_recovery_armed", False)):
            raise ValueError("SDK recovery-only execution lease is not armed")
        if (
            recovery.get("status") != "RECOVERABLE"
            or recovery.get("can_arm_recovery") is not True
            or type(recovery.get("allowed_closes")) is not list
            or not recovery.get("allowed_closes")
            or recovery.get("allowed_cancels") != []
        ):
            raise ValueError("SDK recovery plan is not ready for position closure")
        if remote_open_orders:
            raise ValueError("SDK recovery closure requires canceled remote orders")

        instrument = str(recovery.get("instrument") or "").upper().split(".")[-1]
        long_lots = 0
        short_lots = 0
        for key, position in self.long_positions.items():
            quantity = abs(float(position.size or 0.0))
            if quantity and str(key).upper().split(".")[-1] != instrument:
                raise ValueError("SDK recovery broker position is outside the proven instrument")
            long_lots += quantity
        for key, position in self.short_positions.items():
            quantity = abs(float(position.size or 0.0))
            if quantity and str(key).upper().split(".")[-1] != instrument:
                raise ValueError("SDK recovery broker position is outside the proven instrument")
            short_lots += quantity
        owned = recovery.get("owned_position") or {}
        expected_long = int(owned.get("long_today", -1)) + int(owned.get("long_yesterday", -1))
        expected_short = int(owned.get("short_today", -1)) + int(owned.get("short_yesterday", -1))
        if (
            not float(long_lots).is_integer()
            or not float(short_lots).is_integer()
            or int(long_lots) != expected_long
            or int(short_lots) != expected_short
        ):
            raise ValueError("SDK recovery broker position differs from the owned position")
        if long_lots and short_lots:
            raise ValueError("SDK recovery does not support simultaneous long and short legs")
        return deepcopy(recovery)

    def start(self):
        """Start the broker and hydrate account state from the store."""
        session = self._service_execution_session
        if session is not None:
            session.broker_starting(self)
        super().start()

        if self.store is None:
            raise ValueError("BtApiBroker requires a BtApiStore instance")

        if self._live_started and self._startup_ready and self.store.is_connected:
            return

        is_service_read_only = bool(getattr(self.store, "_service_read_only", False))
        if not self.supports_position_mode(self.get_param("position_mode")):
            raise ValueError(
                f"Provider {self.provider!r} does not advertise support for "
                f"position_mode={self.get_param('position_mode')!r}"
            )

        is_sdk = bool(getattr(self.store, "_sdk_mode", False))
        service_recovery = self._uses_service_execution_recovery()
        service_recovery_v2 = self._uses_service_execution_recovery_v2()
        market_data_only = self._is_market_data_only()
        if is_service_read_only and not market_data_only:
            raise ValueError("service read proxy requires market_data_only=True")
        self._startup_account_state_evidence = self._normalise_startup_account_state(
            self.get_param("startup_account_state")
        )
        recovery_requested = self._execution_recovery is not None
        if market_data_only and recovery_requested:
            raise ValueError("market_data_only cannot be combined with execution_recovery")
        if recovery_requested and not is_sdk:
            raise ValueError("Execution recovery requires the managed SDK broker")
        self._startup_ready = False
        if is_sdk or market_data_only:
            # A connected Store is insufficient authority for opening orders.
            # Keep the route locked until every account, position, order, and
            # durable-risk startup proof below has completed.
            self._trading_enabled = False
        try:
            self.store.start(broker=self)
            self._live_started = True
            if market_data_only:
                freeze_openings = getattr(self.store, "freeze_openings", None)
                if callable(freeze_openings):
                    freeze_openings("market_data_only")
            if is_sdk and not market_data_only and not self._uses_async_commands():
                raise ValueError(
                    "SDK trading requires async_make_order, async_cancel_order, "
                    "and async_query_order"
                )
            self._warm_contract_metadata()
            if not market_data_only and bool(self.p.sdk_preflight) and self._uses_async_commands():
                self._run_sdk_preflight()
            self._refresh_account(force=True, raise_errors=True)
            self._sync_positions(force=True, raise_errors=True)
            # Position hydration can reveal symbols that were not registered
            # as feeds, so materialize their commission rules as well.
            self._warm_contract_metadata()
            remote_open_orders = self._sync_remote_open_orders(
                force=True,
                raise_errors=is_sdk or is_service_read_only,
            )
            if (
                is_sdk
                and remote_open_orders
                and not recovery_requested
                and not service_recovery
                and not market_data_only
            ):
                raise ValueError("SDK startup requires a proven empty remote open-order set")
            if (
                not market_data_only
                and bool(getattr(self.store, "requires_account_risk", False))
                and not recovery_requested
                and not service_recovery
            ):
                initialize_risk = getattr(self.store, "initialize_account_risk_baseline", None)
                if not callable(initialize_risk):
                    raise ValueError("SDK account-risk baseline capability is unavailable")
                risk_snapshot = initialize_risk()
                if not isinstance(risk_snapshot, dict) or (
                    risk_snapshot.get("evidence_complete") is not True
                    or risk_snapshot.get("durable") is not True
                    or risk_snapshot.get("trading_blocked") is not False
                    or not risk_snapshot.get("identity_binding_sha256")
                ):
                    raise ValueError("SDK account-risk baseline is not proven")
            if is_sdk and not market_data_only:
                if service_recovery:
                    # ServiceExecutionSession bound and reconciled the
                    # authenticated recovery cut before entering Cerebro.
                    if service_recovery_v2:
                        adapter = session.adapter
                        reconciliation = adapter.recovery_owner_position_reconciliation
                        if (
                            not isinstance(reconciliation, Mapping)
                            or reconciliation.get("trade_projection_available") is not True
                            or not self._service_execution_recovery_feeds
                        ):
                            raise ValueError(
                                "managed paper recovery does not have a complete Trade projection"
                            )
                        baseline = adapter.recovery_baseline()
                        if (
                            not isinstance(baseline, Mapping)
                            or type(baseline.get("baseline_cursor")) is not int
                            or not baseline.get("journal_generation")
                        ):
                            raise ValueError("managed paper recovery baseline is unavailable")
                elif recovery_requested:
                    self._execution_recovery = self._validate_execution_recovery_startup(
                        remote_open_orders
                    )
                else:
                    get_reconcile_snapshot = getattr(self.store, "get_reconcile_snapshot", None)
                    if not callable(get_reconcile_snapshot):
                        raise ValueError("SDK startup reconciliation capability is unavailable")
                    startup_reconcile = get_reconcile_snapshot()
                    if not self._reconcile_proves_flat(startup_reconcile):
                        raise ValueError("SDK startup execution state is not proven clean and flat")
                    self._last_reconcile_result = deepcopy(startup_reconcile)
            self.startingcash = self._cash
            self.startingvalue = self._value
            self._freeze_position_mode("start()")
            if market_data_only:
                # Keep the broker locked even after its read-only account
                # snapshot has hydrated.  The Store gate above is defensive
                # for callers that retain a reference to it directly.
                self._trading_enabled = False
            elif is_sdk:
                if service_recovery:
                    self._trading_enabled = True
                elif recovery_requested:
                    freeze_openings = getattr(self.store, "freeze_openings", None)
                    if callable(freeze_openings):
                        freeze_openings("execution_recovery_only")
                    self._trading_enabled = False
                else:
                    enable_store_openings = getattr(
                        self.store, "enable_openings_after_account_risk", None
                    )
                    if not callable(enable_store_openings):
                        raise ValueError("SDK opening-admission capability is unavailable")
                    enable_store_openings()
                    self._trading_enabled = True
            self._startup_ready = True
        except Exception:
            # A partially hydrated broker must not look live.  The Store may
            # remain connected so a transient account query can be retried.
            _safe_log("error", "btapibroker:545 exception before re-raise (Exception)")
            self._live_started = False
            self._startup_ready = False
            if is_sdk or is_service_read_only:
                if recovery_requested:
                    try:
                        self.abort_execution_recovery("execution_recovery_startup_failed")
                    except Exception as exc:
                        _safe_log("warning", "btapibroker:554 fallback on Exception")
                        self._sanitize_exception(exc)
                self._trading_enabled = False
                self._positions_snapshot_loaded = False
                self._last_positions_refresh = 0.0
                self.positions = collections.defaultdict(Position)
                self.long_positions = collections.defaultdict(Position)
                self.short_positions = collections.defaultdict(Position)
                self._remote_open_orders_snapshot = []
                self._last_open_orders_refresh = 0.0
                self._last_reconcile_result = None
                self._periodic_reconcile_pending = False
                self._position_audit_mismatch = None
                self._position_audit_error = None
                self._position_audit_blocked = False
                if is_sdk:
                    freeze_openings = getattr(self.store, "freeze_openings", None)
                    if callable(freeze_openings):
                        freeze_openings("broker_start_failed")
            raise

    def get_execution_recovery(self):
        """Return the SDK-validated recovery plan bound at broker startup."""

        return deepcopy(self._execution_recovery)

    def abort_execution_recovery(self, reason="execution_recovery_aborted"):
        """Revoke the current recovery lease once and keep routing read-only."""

        self._trading_enabled = False
        self._strategy_paused = True
        self._execution_recovery_close_attempted = True
        if self._execution_recovery_aborted:
            return deepcopy(self._execution_recovery_abort_result)
        abort = getattr(self.store, "abort_execution_recovery", None)
        if not callable(abort):
            raise ValueError("SDK execution recovery abort capability is unavailable")
        result = abort(str(reason or "execution_recovery_aborted"))
        if not isinstance(result, dict) or not (
            result.get("aborted") is True
            and result.get("market_data_only") is True
            and result.get("recovery_only") is False
        ):
            raise ValueError("SDK execution recovery abort was not proven")
        self._execution_recovery_aborted = True
        self._execution_recovery_abort_result = deepcopy(result)
        return deepcopy(result)

    def _abort_recovery_dispatch(self, order, reason):
        if self._execution_recovery is None:
            return
        try:
            self.abort_execution_recovery(reason)
        except Exception as exc:
            _safe_log("warning", "btapibroker:606 fallback on Exception")
            self._sanitize_exception(exc)
            self._emit_runtime_event(
                "execution_recovery_abort_failed",
                level="ERROR",
                error_code=self._safe_exception_code(exc, "execution_recovery_abort_failed"),
            )

    def complete_execution_recovery(self, *, recovery_token_sha256):
        """Delegate final two-round recovery reconciliation to the SDK."""

        if self._is_market_data_only():
            raise ValueError("execution recovery is unavailable for a market_data_only broker")

        recovery = self._execution_recovery
        if not isinstance(recovery, dict) or (
            recovery.get("recovery_token_sha256") != recovery_token_sha256
        ):
            raise ValueError("Execution recovery token does not match the broker plan")
        complete = getattr(self.store, "complete_execution_recovery", None)
        if not callable(complete):
            raise ValueError("SDK execution recovery completion capability is unavailable")
        result = complete(recovery_token_sha256=recovery_token_sha256)
        if not isinstance(result, dict) or result.get("completed") is not True:
            raise ValueError("SDK execution recovery completion was not proven")
        with self._execution_recovery_completion_lock:
            self._last_execution_recovery_completion = {
                "completed": True,
                "status": "completed",
                "error_code": None,
            }
        return deepcopy(result)

    def _reject_execution_recovery_completion(self, error_code):
        with self._execution_recovery_completion_lock:
            self._execution_recovery_completion_pending = False
            self._execution_recovery_completion_receipt = None
            self._execution_recovery_completion_callbacks.clear()
        try:
            self.abort_execution_recovery(error_code)
        except Exception as exc:
            _safe_log("warning", "btapibroker:646 fallback on Exception")
            self._sanitize_exception(exc)
        return {"queued": False, "error_code": error_code}

    def request_execution_recovery_completion(self, callback, *, recovery_token_sha256):
        """Queue SDK-owned recovery completion and notify on the Cerebro thread."""
        if self._is_market_data_only():
            return {"queued": False, "error_code": "market_data_only"}
        with self._execution_recovery_completion_lock:
            if not callable(callback):
                return self._reject_execution_recovery_completion("recovery_callback_not_callable")
            recovery = self._execution_recovery
            if not isinstance(recovery, dict) or (
                recovery.get("recovery_token_sha256") != recovery_token_sha256
            ):
                return self._reject_execution_recovery_completion("recovery_token_mismatch")
            if callback not in self._execution_recovery_completion_callbacks:
                self._execution_recovery_completion_callbacks.append(callback)
            if self._execution_recovery_completion_pending:
                return deepcopy(
                    self._execution_recovery_completion_receipt
                    or {"queued": True, "status": "already_pending"}
                )
            enqueue = getattr(self.store, "enqueue_execution_recovery_completion", None)
            if not callable(enqueue):
                return self._reject_execution_recovery_completion("recovery_completion_unavailable")
            try:
                receipt = enqueue(recovery_token_sha256=recovery_token_sha256)
            except Exception as exc:
                _safe_log("warning", "btapibroker:674 fallback on Exception")
                self._sanitize_exception(exc)
                return self._reject_execution_recovery_completion(
                    self._safe_exception_code(exc, "recovery_completion_failed")
                )
            self._execution_recovery_completion_pending = bool(
                isinstance(receipt, dict) and receipt.get("queued") is True
            )
            if not self._execution_recovery_completion_pending:
                return self._reject_execution_recovery_completion(
                    str(receipt.get("error_code") or "recovery_completion_not_queued")
                    if isinstance(receipt, dict)
                    else "recovery_completion_not_queued"
                )
            self._execution_recovery_completion_receipt = deepcopy(receipt)
            return deepcopy(self._redact_runtime_value(receipt))

    def _run_sdk_preflight(self):
        """Prove account permission, routed position mode, and order readiness."""
        routes_method = getattr(self.store, "get_symbol_routes", None)
        routes = (
            routes_method()
            if callable(routes_method)
            else dict(getattr(self.store, "_sdk_routes", {}) or {})
        )
        if not routes:
            raise ValueError("SDK trading preflight requires at least one symbol route")
        expected_mode = normalize_position_mode(self.get_param("position_mode"))
        readiness = {}
        for symbol, venue in routes.items():
            account = self.store.get_account_config(symbol)
            if not isinstance(account, dict):
                raise ValueError(f"Account configuration is not proven for {venue!r}")
            if account.get("can_trade") is not True:
                raise ValueError(f"API trading permission is not proven for {venue!r}")
            raw_mode = account.get("position_mode")
            if raw_mode in (None, ""):
                raise ValueError(f"Account position mode is not proven for {venue!r}")
            try:
                actual_mode = normalize_position_mode(raw_mode)
            except Exception as exc:
                _safe_log("error", "btapibroker:715 re-raising Exception")
                raise ValueError(f"Account position mode is not proven for {venue!r}") from exc
            if actual_mode != expected_mode:
                raise ValueError(
                    f"Account {venue!r} uses position mode={actual_mode!r}; "
                    f"expected {expected_mode!r}"
                )

            rules = dict(getattr(self.store, "contract_metadata", {}).get(symbol, {}) or {})
            quantity = next(
                (
                    rules[key]
                    for key in ("min_size", "min_qty", "lot_size", "qty_step")
                    if rules.get(key) not in (None, "", 0, "0")
                ),
                1,
            )
            snapshot = self.store.get_trading_readiness(
                symbol,
                quantity,
                margin_mode=str(rules.get("margin_mode") or "cross"),
                expected_position_mode=expected_mode,
                # The Store resolves an omitted id through the SDK's durable
                # authenticated ledger identity.  A venue name is not an
                # account id and must never be invented as one.
                account_id=(
                    str(account["account_id"])
                    if account.get("account_id") not in (None, "")
                    else None
                ),
            )
            if not isinstance(snapshot, dict):
                raise ValueError(f"Order readiness is not proven for {venue!r}")
            reasons = snapshot.get("reasons")
            if not isinstance(reasons, list):
                raise ValueError(f"Order readiness reasons are invalid for {venue!r}")
            returned_mode = snapshot.get("position_mode")
            if returned_mode not in (None, ""):
                try:
                    readiness_mode = normalize_position_mode(returned_mode)
                except Exception as exc:
                    _safe_log("error", "btapibroker:755 re-raising Exception")
                    raise ValueError(f"Order readiness mode is invalid for {venue!r}") from exc
                if readiness_mode != expected_mode:
                    raise ValueError(f"Order readiness position mode mismatches for {venue!r}")
            if snapshot.get("ready") is not True or snapshot.get("definite_failure") is True:
                reason = ",".join(str(item) for item in reasons) or "readiness_not_proven"
                raise ValueError(f"Order readiness failed for {venue!r}: {reason}")
            readiness[symbol] = {"venue": venue, "account": account, "readiness": snapshot}
        self._sdk_readiness = readiness

    def set_param(self, name, value, validate=True):
        """Override :meth:`BrokerBase.set_param` for runtime safety parameters.

        The ``position_mode`` parameter is treated specially: it is
        immutable once :meth:`start` has run (frozen via
        :meth:`_freeze_position_mode`), and its raw value is normalized
        through :func:`normalize_position_mode` so that the broker
        always stores one of the canonical ``"net"`` /
        ``"dual_side"`` strings.

        Args:
            name: Name of the parameter to set.
            value: New value for the parameter. For ``position_mode`` the
                value is normalized before being applied.
            validate: When ``True`` (default), delegate to the base class
                so that the registered validator runs. Set to ``False``
                to bypass validation (used internally when applying
                normalized values).

        Returns:
            The return value of :meth:`BrokerBase.set_param` after the
            value has been applied.

        Raises:
            ValueError: If a startup-frozen safety parameter is changed after
                :meth:`start`.
        """
        if name == "position_mode":
            self._ensure_position_mode_mutable()
            value = normalize_position_mode(value)
        if name == "market_data_only":
            if not isinstance(value, bool):
                raise ValueError("market_data_only must be a boolean")
            if getattr(self, "_startup_ready", False):
                raise ValueError("market_data_only is frozen after broker startup")
        if name == "startup_account_state" and getattr(self, "_startup_ready", False):
            raise ValueError("startup_account_state is frozen after broker startup")
        if name == "position_sync_policy":
            if value not in {"periodic", "startup"}:
                raise ValueError("position_sync_policy must be periodic or startup")
            if getattr(self, "_positions_snapshot_loaded", False):
                raise ValueError("position_sync_policy is frozen after initial position sync")
        result = super().set_param(name, value, validate=validate)
        if name == "market_data_only" and value:
            self._trading_enabled = False
        if name == "startup_account_state":
            self._startup_account_state_evidence = self._normalise_startup_account_state(value)
        return result

    def _freeze_position_mode(self, reason):
        self._position_mode_frozen = True
        self._position_mode_frozen_reason = reason

    def _ensure_position_mode_mutable(self):
        if getattr(self, "_position_mode_frozen", False):
            raise ValueError(
                "position_mode is frozen after "
                f"{self._position_mode_frozen_reason} and cannot be changed at runtime"
            )

    def _is_dual_side_mode(self):
        return normalize_position_mode(self.get_param("position_mode")) == POSITION_MODE_DUAL_SIDE

    def _uses_async_commands(self):
        return bool(getattr(self.store, "uses_async_commands", False))

    def _is_market_data_only(self):
        """Return whether this broker instance must remain observation-only."""
        return bool(self.get_param("market_data_only"))

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
        if value is None or type(value) in (str, bool, int):
            return value
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError("recovery context decimal is not finite")
            return format(value, "f")
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("recovery context float is not finite")
            return value.hex()
        raise ValueError("recovery context value is not a supported scalar")

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
        binding = reader()
        required = {"source_ref", "generation", "cursor", "instrument", "as_of_ns"}
        if not isinstance(binding, Mapping) or frozenset(binding) != required:
            raise ValueError("recovery feed quote binding has an invalid shape")
        source_ref = binding.get("source_ref")
        generation = binding.get("generation")
        quote_instrument = binding.get("instrument")
        cursor = binding.get("cursor")
        as_of_ns = binding.get("as_of_ns")
        if (
            type(source_ref) is not str
            or not source_ref
            or type(generation) is not str
            or not generation
            or type(quote_instrument) is not str
            or quote_instrument != instrument
            or type(cursor) is not int
            or cursor < 0
            or type(as_of_ns) is not int
            or as_of_ns <= 0
            or type(data_name) is not str
            or not data_name
            or type(bar_index) is not int
            or bar_index < 1
            or type(datetime_hex) is not str
        ):
            raise ValueError("recovery feed quote binding is invalid")
        return {
            "source_ref": source_ref,
            "generation": generation,
            "cursor": cursor,
            "instrument": quote_instrument,
            "as_of_ns": as_of_ns,
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
        if type(value) not in (str, Decimal, int):
            raise ValueError("recovery decimal source is not exact text")
        try:
            number = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValueError("recovery decimal source is invalid") from error
        if (
            not number.is_finite()
            or (positive and number <= 0)
            or (nonnegative and number < 0)
        ):
            raise ValueError("recovery decimal source is outside its bounds")
        return number

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
            if (
                event.get("event_type") != "provider_observation"
                or event.get("state") != "FILLED"
                or details.get("source") != "provider"
                or submit.get("position_effect") != "OPEN"
                or submit.get("reduce_only") is not False
                or submit.get("order_type") != "MARKET"
                or submit.get("time_in_force") != "FOK"
                or submit.get("price") is not None
                or fill.get("commission_model_id") != "quote_notional_rate"
                or fill.get("commission_model_version") != "1"
                or fill.get("instrument") not in (None, instrument)
                or fill.get("scope_key") != event.get("scope_key")
                or fill.get("event_id") != event.get("event_id")
                or fill.get("event_sequence") != event.get("sequence")
                or fill.get("journal_generation") != event.get("journal_generation")
                or fill.get("intent_id") != event.get("intent_id")
                or fill.get("intent_fingerprint") != event.get("intent_fingerprint")
                or fill.get("account_ref") != getattr(namespace, "account_ref", None)
                or fill.get("strategy_ref") != getattr(namespace, "strategy_ref", None)
                or fill.get("quote_instrument") != instrument
            ):
                raise ValueError("managed paper V2 fill binding is inconsistent")
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
                or quote_binding.get("source_ref") != fill.get("quote_source_ref")
                or quote_binding.get("generation") != fill.get("quote_generation")
                or quote_binding.get("cursor") != fill.get("quote_cursor")
                or quote_binding.get("instrument") != fill.get("quote_instrument")
                or quote_binding.get("data_name") != data_name
                or quote_binding.get("bar_index") != decision.get("bar_index")
                or quote_binding.get("datetime_hex") != decision.get("datetime_hex")
                or type(quote_binding.get("as_of_ns")) is not int
                or quote_binding.get("as_of_ns") <= 0
            ):
                raise ValueError("managed paper quote is not bound to the persisted feed bar")
            quantity = self._service_recovery_decimal(fill.get("quantity"), positive=True)
            price = self._service_recovery_decimal(fill.get("price"), positive=True)
            commission = self._service_recovery_decimal(fill.get("commission"))
            if (
                self._service_recovery_decimal(submit.get("quantity"), positive=True) != quantity
                or self._service_recovery_decimal(details.get("filled_quantity"), nonnegative=True) != quantity
                or self._service_recovery_decimal(details.get("average_price"), positive=True) != price
                or self._service_recovery_decimal(details.get("cumulative_commission")) != commission
            ):
                raise ValueError("managed paper V2 economics do not match the order event")
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

    @staticmethod
    def _normalise_startup_account_state(value):
        """Return a safe, non-final-state observation summary for shutdown.

        This accepts only provider-neutral aggregate counts.  It deliberately
        does not turn the supplied startup snapshot into a final remote query:
        absent evidence remains absent, while unknown or malformed supplied
        evidence is retained as a conservative non-flat shutdown condition.
        """
        keys = (
            "nonzero_position_record_count",
            "gross_position_lots",
            "active_orders_count",
        )
        evidence = {
            "provided": value is not None,
            "validation_status": "not_provided",
            "is_final_state": False,
            "proves_nonflat": False,
            "requires_nonflat": False,
            "nonzero_position_record_count": None,
            "gross_position_lots": None,
            "active_orders_count": None,
            "validation_errors": [],
        }
        if value is None:
            return evidence
        if not isinstance(value, Mapping):
            evidence.update(
                validation_status="malformed",
                requires_nonflat=True,
                validation_errors=["startup_account_state_not_mapping"],
            )
            return evidence

        raw_values = {}
        missing = []
        unknown = []
        malformed = []
        for key in keys:
            try:
                raw_value = value[key]
            except KeyError:
                missing.append(key)
                continue
            except Exception:
                _safe_log("warning", "btapibroker:881 fallback on Exception")
                malformed.append(f"unreadable_{key}")
                continue
            if raw_value is None:
                unknown.append(key)
                continue
            raw_values[key] = raw_value

        if missing:
            malformed.extend(f"missing_{key}" for key in missing)
        if not missing and not unknown and not malformed:
            for key in ("nonzero_position_record_count", "active_orders_count"):
                number = raw_values[key]
                if isinstance(number, bool) or not isinstance(number, int) or number < 0:
                    malformed.append(f"invalid_{key}")
                    continue
                evidence[key] = number

            gross_lots = raw_values["gross_position_lots"]
            if (
                isinstance(gross_lots, bool)
                or not isinstance(gross_lots, (int, float))
                or not math.isfinite(float(gross_lots))
                or float(gross_lots) < 0.0
            ):
                malformed.append("invalid_gross_position_lots")
            else:
                evidence["gross_position_lots"] = float(gross_lots)

        if malformed:
            evidence.update(
                validation_status="malformed",
                requires_nonflat=True,
                validation_errors=sorted(set(malformed)),
                nonzero_position_record_count=None,
                gross_position_lots=None,
                active_orders_count=None,
            )
            return evidence
        if unknown:
            evidence.update(
                validation_status="unknown",
                requires_nonflat=True,
                validation_errors=sorted(f"unknown_{key}" for key in unknown),
                nonzero_position_record_count=None,
                gross_position_lots=None,
                active_orders_count=None,
            )
            return evidence

        proves_nonflat = bool(
            evidence["nonzero_position_record_count"]
            or evidence["gross_position_lots"]
            or evidence["active_orders_count"]
        )
        evidence.update(
            validation_status="valid",
            proves_nonflat=proves_nonflat,
            requires_nonflat=proves_nonflat,
        )
        return evidence

    def supports_position_mode(self, mode):
        """Return whether the broker can operate in the requested position mode.

        Any non-dual-side mode (``"net"`` or its aliases) is always
        supported because it does not require special handling from the
        underlying store. Dual-side mode is supported when:

        * the underlying store advertises it via
          ``store.supports_position_mode("dual_side")``, or
        * the broker-level contract metadata declares
          ``supports_dual_side`` / ``position_mode == "dual_side"``.

        Args:
            mode: Position mode to check. Any value accepted by
                :func:`normalize_position_mode` may be passed.

        Returns:
            bool: ``True`` if the broker can run in ``mode``, ``False``
            otherwise.
        """
        mode = normalize_position_mode(mode)
        if bool(getattr(self.store, "_service_read_only", False)):
            supports = getattr(self.store, "supports_position_mode", None)
            return bool(callable(supports) and supports(mode))
        if mode != POSITION_MODE_DUAL_SIDE:
            return True
        if self.store is not None and hasattr(self.store, "supports_position_mode"):
            try:
                return bool(self.store.supports_position_mode(mode))
            except Exception as exc:
                _safe_log("warning", "btapibroker:969 fallback on Exception")
                _safe_log("debug", "Failed to query store position mode capability: %s", exc)
        broker_meta = self._contract_metadata.get("__broker__", {})
        return bool(
            broker_meta.get("supports_dual_side")
            or str(broker_meta.get("position_mode", "")).lower() == POSITION_MODE_DUAL_SIDE
        )

    def _normalize_order_meta(self, isbuy, kwargs):
        local_kwargs = dict(kwargs)
        position_side = local_kwargs.pop("position_side", None)
        offset = local_kwargs.pop("offset", None)
        broker_mode = normalize_position_mode(self.get_param("position_mode"))
        requested_mode = local_kwargs.pop("position_mode", None)
        if (
            requested_mode not in (None, "")
            and normalize_position_mode(requested_mode) != broker_mode
        ):
            raise ValueError("Per-order position_mode conflicts with the broker session")
        position_side, offset = normalize_order_position_meta(
            broker_mode,
            isbuy,
            position_side=position_side,
            offset=offset,
        )
        local_kwargs["position_mode"] = broker_mode
        if str(offset or "open").lower() != "open":
            local_kwargs.setdefault("reduce_only", True)
        return position_side, offset, local_kwargs

    @staticmethod
    def _attach_position_meta(order, position_side=None, offset=None, **kwargs):
        if position_side is not None:
            order.addinfo(position_side=position_side)
        if offset is not None:
            order.addinfo(offset=offset)
        if kwargs:
            order.addinfo(**kwargs)
        return order

    def _get_leg_store(self, position_side):
        position_side = normalize_position_side(position_side)
        if position_side == "long":
            return self.long_positions
        if position_side == "short":
            return self.short_positions
        raise ValueError(f"Unsupported position_side {position_side!r}")

    def _get_leg_position(self, data, position_side):
        return self._get_leg_store(position_side)[self._position_key(data)]

    def _make_signed_position(self, position_side, position):
        signed_position = position.clone()
        signed_position.size = signed_position_size(position_side, position.size)
        if not signed_position.size:
            signed_position.price = 0.0
            signed_position.price_orig = 0.0
        return signed_position

    def _apply_signed_position(self, position_side, leg_position, signed_position):
        leg_position.size = abs(float(signed_position.size or 0.0))
        leg_position.price = signed_position.price if leg_position.size else 0.0
        leg_position.price_orig = signed_position.price_orig if leg_position.size else 0.0
        leg_position.adjbase = signed_position.adjbase
        leg_position.datetime = signed_position.datetime
        leg_position.updt = signed_position.updt
        leg_position.upopened = abs(float(signed_position.upopened or 0.0))
        leg_position.upclosed = abs(float(signed_position.upclosed or 0.0))
        return leg_position

    def _sync_net_position(self, data):
        key = self._position_key(data)
        long_pos = self.long_positions[key]
        short_pos = self.short_positions[key]
        net_pos = self.positions[key]
        net_size = long_pos.size - short_pos.size
        if net_size > 0:
            net_price = long_pos.price
        elif net_size < 0:
            net_price = short_pos.price
        else:
            net_price = 0.0
        net_pos.fix(net_size, net_price)
        if long_pos.datetime is not None and short_pos.datetime is not None:
            net_pos.datetime = max(long_pos.datetime, short_pos.datetime)
        else:
            net_pos.datetime = long_pos.datetime or short_pos.datetime
        net_pos.adjbase = long_pos.adjbase if long_pos.size else short_pos.adjbase
        return net_pos

    def attach_service_execution_session(self, session):
        """Attach one explicit managed-execution owner before startup."""
        from ..stores.service_execution_session import ServiceExecutionSession

        if not isinstance(session, ServiceExecutionSession):
            raise TypeError("session must be a ServiceExecutionSession")
        if self._service_execution_session is not None:
            raise RuntimeError("service execution session is already attached")
        if (
            self.store is None
            or self._live_started
            or self._startup_ready
            or bool(getattr(self.store, "_started", False))
            or bool(self.store.is_connected)
            or bool(self.store.managed_execution_active)
        ):
            raise RuntimeError("service execution session must attach before startup")
        session._bind_broker(self)
        self._service_execution_session = session
        return None

    @staticmethod
    def _store_shutdown_reserve(store, shutdown_timeout):
        """Return a bounded Store shutdown reserve when its bound is verifiable."""
        configured_timeout = getattr(store, "_command_shutdown_timeout", None)
        if isinstance(configured_timeout, bool) or not isinstance(configured_timeout, (int, float)):
            return None
        try:
            configured_timeout = float(configured_timeout)
        except (OverflowError, ValueError):
            return None
        if (
            not math.isfinite(configured_timeout)
            or configured_timeout <= 0
            or not math.isfinite(shutdown_timeout)
            or shutdown_timeout <= 0
        ):
            return None
        return min(configured_timeout, shutdown_timeout / 2.0)

    def stop(self):
        """Run the existing shutdown path and report its result to an owner."""
        session = self._service_execution_session
        if session is None:
            return self._stop_live_resources()

        session.broker_stopping(self)
        try:
            result = self._stop_live_resources()
        except BaseException as error:
            session.broker_stop_failed(self, error)
            raise
        session.broker_stopped(self, result)
        return result

    def _stop_live_resources(self):
        """Freeze exposure, reduce known risk, reconcile, and stop as before."""
        self._startup_ready = False
        if self.store is None:
            self._live_started = False
            return None
        if self._is_market_data_only():
            if not self._live_started and not self.store.is_connected:
                return dict(self._shutdown_summary)
            return self._stop_market_data_only()
        if self._uses_service_execution_recovery():
            return self._stop_service_execution_recovery()
        is_sdk = self._uses_async_commands()
        if not is_sdk or not self._live_started:
            self._live_started = False
            if (
                self.store.is_connected
                and getattr(self.store, "_cerebro_managed_lifecycle", True) is not False
            ):
                return self.store.stop()
            return None

        timeout = max(float(self.p.shutdown_timeout or 0.0), 0.0)
        if not math.isfinite(timeout):
            timeout = 0.0
        shutdown_deadline = time.monotonic() + timeout
        store_reserve = self._store_shutdown_reserve(self.store, timeout)
        # The Broker and Store share one total deadline. Reserve at most half
        # of it (and never more than the Store's configured shutdown bound) so
        # both shutdown phases retain time without extending the caller budget.
        deadline = (
            shutdown_deadline - store_reserve if store_reserve is not None else shutdown_deadline
        )
        self._trading_enabled = False
        freeze = getattr(self.store, "freeze_openings", None)
        if callable(freeze):
            freeze("broker_stop")
        summary = {
            "status": "INCOMPLETE",
            "cancel_requested": 0,
            "close_requested": 0,
            "unknown_orders": 0,
            "reason": "shutdown_not_converged",
        }
        self._emit_runtime_event("broker_winddown_started", status="running")

        recovery_session = self._execution_recovery is not None
        with self._execution_recovery_completion_lock:
            recovery_completion_proven = bool(
                isinstance(self._last_execution_recovery_completion, dict)
                and self._last_execution_recovery_completion.get("completed") is True
            )
        if recovery_session:
            summary["recovery_completion_proven"] = recovery_completion_proven
        if recovery_session and not recovery_completion_proven:
            try:
                self.abort_execution_recovery("execution_recovery_broker_stop")
            except Exception:
                _safe_log("warning", "btapibroker:1105 fallback on Exception")
                summary.update(status="FAIL", reason="execution_recovery_abort_failed")
        active = list(self.get_orders_open())
        if not recovery_session:
            for order in active:
                try:
                    self.cancel(order)
                    summary["cancel_requested"] += 1
                except Exception:
                    _safe_log("warning", "btapibroker:1113 fallback on Exception")
                    summary["reason"] = "cancel_request_failed"

        if self._wait_and_drain(deadline):
            # Cancel completions queue identity-preserving order queries. Drain
            # those before deciding whether a locally known leg is safe to close.
            self._wait_and_drain(deadline)

        uncertain = [
            order
            for order in self.get_orders_open()
            if bool(self._order_info_get(order, "execution_unknown", False))
            or bool(self._order_info_get(order, "cancel_execution_unknown", False))
        ]
        summary["unknown_orders"] = len(uncertain)
        if (
            not recovery_session
            and bool(self.p.flatten_on_stop)
            and not uncertain
            and not self.get_orders_open()
            and not self._position_audit_blocked
        ):
            close_orders, missing_data = self._submit_known_position_closes()
            summary["close_requested"] = len(close_orders)
            if missing_data:
                summary["reason"] = "known_position_has_no_feed_binding"
            self._wait_and_drain(deadline)

        reconcile = getattr(self.store, "enqueue_reconcile", None)
        self._last_reconcile_result = None
        result = None
        if callable(reconcile):
            attempts = 3
            while attempts and time.monotonic() < deadline:
                attempts -= 1
                receipt = reconcile()
                if isinstance(receipt, dict) and receipt.get("queued") is True:
                    self._wait_and_drain(deadline)
                candidate = self._last_reconcile_result
                if candidate is not None:
                    result = candidate
                    if self._reconcile_proves_flat(result):
                        break
                if not uncertain and time.monotonic() < deadline:
                    # A final snapshot can race the terminal confirmation of
                    # an order that closed during this shutdown (its next
                    # reconciliation poll has not ticked yet).  Re-enqueue a
                    # bounded retry within the remaining budget instead of
                    # failing the flat proof on the first snapshot.
                    time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))

        flat_proven = result is not None and self._reconcile_proves_flat(result)
        remote_open_orders = result.get("open_orders") if isinstance(result, dict) else None
        remote_positions = result.get("positions") if isinstance(result, dict) else None
        execution_summary = result.get("execution_summary") if isinstance(result, dict) else None
        local_active_order_count = sum(1 for order in self.orders.values() if order.alive())
        local_position_count = sum(
            1
            for position_store in (
                (self.long_positions, self.short_positions)
                if self._is_dual_side_mode()
                else (self.positions,)
            )
            for position in position_store.values()
            if abs(float(position.size or 0.0)) > 1e-12
        )
        summary.update(
            remote_flat_proven=bool(flat_proven),
            active_order_count=(
                max(local_active_order_count, len(remote_open_orders))
                if isinstance(remote_open_orders, list)
                else None
            ),
            local_position_count=local_position_count,
            remote_position_count=(
                len(remote_positions) if isinstance(remote_positions, list) else None
            ),
            unknown_intent_count=(
                len(execution_summary.get("unknown_ids"))
                if isinstance(execution_summary, dict)
                and type(execution_summary.get("unknown_ids")) is list
                else None
            ),
            unmatched_trade_count=(
                execution_summary.get("unmatched_trade_count")
                if isinstance(execution_summary, dict)
                and type(execution_summary.get("unmatched_trade_count")) is int
                else None
            ),
        )
        if isinstance(result, dict) and result.get("error_code"):
            summary.update(status="BLOCKED", reason="final_reconcile_unavailable")
        elif time.monotonic() >= deadline:
            summary.update(status="INCOMPLETE", reason="shutdown_timeout")
        elif uncertain:
            summary.update(status="INCOMPLETE", reason="unknown_execution_exposure")

        self._live_started = False
        store_health = None
        if (
            self.store.is_connected
            and getattr(self.store, "_cerebro_managed_lifecycle", True) is not False
        ):
            try:
                store_health = self.store.stop(
                    timeout=max(shutdown_deadline - time.monotonic(), 0.0)
                )
            except Exception as exc:
                _safe_log("warning", "btapibroker:1203 fallback on Exception")
                self._sanitize_exception(exc)
                summary.update(status="FAIL", reason="store_shutdown_failed")
        store_state = store_health.get("shutdown_state") if isinstance(store_health, dict) else None
        summary["store_shutdown_state"] = store_state or "UNPROVEN"
        if summary["status"] != "FAIL":
            strict_shutdown_evidence = bool(
                self.p.require_complete_ctp_evidence or recovery_session
            )
            shutdown_counts_clear = True
            if strict_shutdown_evidence:
                exact_zero_fields = (
                    "active_order_count",
                    "local_position_count",
                    "remote_position_count",
                    "unknown_intent_count",
                    "unmatched_trade_count",
                )
                shutdown_counts_clear = all(
                    type(summary.get(field)) is int and summary[field] == 0
                    for field in exact_zero_fields
                )
            if store_state == "FAIL":
                summary.update(status="FAIL", reason="store_shutdown_failed")
            elif recovery_session and not recovery_completion_proven:
                summary.update(status="INCOMPLETE", reason="execution_recovery_completion_unproven")
            elif flat_proven and shutdown_counts_clear and store_state == "PASS":
                summary.update(status="PASS", reason="remote_flat_proven")
            elif not shutdown_counts_clear:
                summary.update(status="INCOMPLETE", reason="shutdown_state_not_flat")
            elif store_state != "PASS":
                summary.update(status="INCOMPLETE", reason="store_shutdown_incomplete")

        self._shutdown_summary = summary
        self._emit_runtime_event(
            "broker_winddown_finished",
            level="INFO" if summary["status"] == "PASS" else "ERROR",
            status=summary["status"],
            details=dict(summary),
        )
        return dict(summary)

    def _stop_service_execution_recovery(self):
        """Close the Store without canceling or flattening recovered orders."""

        self._startup_ready = False
        self._trading_enabled = False
        self._live_started = False
        freeze = getattr(self.store, "freeze_openings", None)
        if callable(freeze):
            freeze("service_execution_recovery_broker_stop")
        store_result = None
        if (
            self.store.is_connected
            and getattr(self.store, "_cerebro_managed_lifecycle", True) is not False
        ):
            store_result = self.store.stop(
                timeout=max(float(self.p.shutdown_timeout or 0.0), 0.0)
            )
        shutdown_state = (
            store_result.get("shutdown_state")
            if isinstance(store_result, dict)
            else ("PASS" if not self.store.is_connected else "UNPROVEN")
        )
        summary = {
            "status": "PASS" if shutdown_state == "PASS" else "FAIL",
            "shutdown_state": shutdown_state,
            "recovery_orders_retained": True,
            "flat_proven": False,
            "reason": "service_execution_recovery_orders_are_not_cancelled_on_shutdown",
        }
        self._shutdown_summary = dict(summary)
        return summary

    def _stop_market_data_only(self):
        """Disconnect an observation-only broker without mutating account state.

        The cached account, order and position snapshots are deliberately kept
        for callers such as status observers.  They cannot prove a final flat
        account because this path neither cancels nor closes external state.
        """
        timeout = max(float(self.p.shutdown_timeout or 0.0), 0.0)
        self._trading_enabled = False
        freeze = getattr(self.store, "freeze_openings", None)
        if callable(freeze):
            freeze("market_data_only_stop")

        local_active_order_count = sum(1 for order in self.orders.values() if order.alive())
        local_position_count = sum(
            1
            for position_store in (
                (self.long_positions, self.short_positions)
                if self._is_dual_side_mode()
                else (self.positions,)
            )
            for position in position_store.values()
            if abs(float(position.size or 0.0)) > 1e-12
        )
        observed_remote_open_order_count = len(self._remote_open_orders_snapshot)
        startup_account_state = deepcopy(self._startup_account_state_evidence)
        startup_state_requires_nonflat = bool(startup_account_state.get("requires_nonflat"))
        external_state_observed = bool(
            local_active_order_count
            or local_position_count
            or observed_remote_open_order_count
            or startup_state_requires_nonflat
        )
        startup_validation_status = startup_account_state["validation_status"]
        if startup_validation_status in {"unknown", "malformed"}:
            observation_reason = "market_data_only_startup_account_state_unproven"
        elif startup_account_state["proves_nonflat"]:
            observation_reason = "market_data_only_startup_account_state_nonflat"
        elif external_state_observed:
            observation_reason = "market_data_only_external_state_observed"
        else:
            observation_reason = "market_data_only_no_order_mutation"
        summary = {
            "status": "OBSERVATION_ONLY_NONFLAT" if external_state_observed else "OBSERVATION_ONLY",
            "market_data_only": True,
            "cancel_requested": 0,
            "close_requested": 0,
            "unknown_orders": 0,
            # Do not turn a startup/periodic cache into a claim that the
            # account was flat at shutdown.  A regular execution session owns
            # the stricter reconciliation proof.
            "remote_flat_proven": False,
            "active_order_count": local_active_order_count,
            "local_position_count": local_position_count,
            "remote_position_count": None,
            "unknown_intent_count": None,
            "unmatched_trade_count": None,
            "observed_remote_open_order_count": observed_remote_open_order_count,
            # This is the normalized, startup-only caller evidence.  It must
            # never be interpreted as a final remote reconciliation result.
            "startup_account_state": startup_account_state,
            "startup_account_state_requires_nonflat": startup_state_requires_nonflat,
            "reason": observation_reason,
        }
        self._emit_runtime_event("broker_observation_shutdown_started", status="running")

        self._live_started = False
        # Store.stop() deliberately discards session-bound CTP evidence before
        # it closes the SDK.  Preserve its cached, credential-redacted terminal
        # state immediately before that teardown so a caller can independently
        # judge a read-only observation without treating it as reconciliation.
        terminal_session_state = {}
        terminal_session_capture_status = "UNAVAILABLE"
        terminal_getter = getattr(self.store, "get_ctp_session_state", None)
        if callable(terminal_getter):
            try:
                terminal_state = terminal_getter()
            except Exception as exc:
                _safe_log("warning", "btapibroker:1322 fallback on Exception")
                self._sanitize_exception(exc)
                terminal_session_capture_status = "ERROR"
            else:
                if isinstance(terminal_state, Mapping):
                    terminal_session_state = deepcopy(
                        self._redact_runtime_value(dict(terminal_state))
                    )
                    terminal_session_capture_status = "CAPTURED"
                else:
                    terminal_session_capture_status = "INVALID"
        summary["terminal_session_state"] = terminal_session_state
        summary["terminal_session_capture_status"] = terminal_session_capture_status
        store_health = None
        if (
            self.store.is_connected
            and getattr(self.store, "_cerebro_managed_lifecycle", True) is not False
        ):
            try:
                store_health = self.store.stop(timeout=timeout)
            except Exception as exc:
                _safe_log("warning", "btapibroker:1342 fallback on Exception")
                self._sanitize_exception(exc)
                summary.update(status="FAIL", reason="store_shutdown_failed")

        store_state = store_health.get("shutdown_state") if isinstance(store_health, dict) else None
        summary["store_shutdown_state"] = store_state or "UNPROVEN"
        if summary["status"] != "FAIL" and store_state == "FAIL":
            summary.update(status="FAIL", reason="store_shutdown_failed")
        elif summary["status"] != "FAIL" and store_state != "PASS":
            summary.update(status="INCOMPLETE", reason="store_shutdown_incomplete")

        self._shutdown_summary = summary
        self._emit_runtime_event(
            "broker_observation_shutdown_finished",
            level="INFO" if summary["status"].startswith("OBSERVATION_ONLY") else "ERROR",
            status=summary["status"],
            details=dict(summary),
        )
        return dict(summary)

    def _wait_and_drain(self, deadline):
        waiter = getattr(self.store, "wait_for_commands", None)
        if not callable(waiter):
            return False
        completed = waiter(max(deadline - time.monotonic(), 0.0))
        self._drain_store_updates()
        return completed

    @staticmethod
    def _quote_value(quote, *names):
        for name in names:
            value = quote.get(name) if isinstance(quote, dict) else getattr(quote, name, None)
            if value not in (None, ""):
                return value
        return None

    @staticmethod
    def _quote_datetime_utc(value):
        """Parse an explicitly UTC quote timestamp without trusting local time."""
        if isinstance(value, bool) or value in (None, ""):
            return None
        if isinstance(value, _dt.datetime):
            parsed = value
        elif isinstance(value, (int, float)):
            try:
                timestamp = float(value)
                if not math.isfinite(timestamp):
                    return None
                if abs(timestamp) > 10_000_000_000:
                    timestamp /= 1000.0
                parsed = _dt.datetime.fromtimestamp(timestamp, _dt.timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
        elif isinstance(value, str):
            try:
                parsed = _dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(_dt.timezone.utc)

    def _current_ctp_instrument_row(self, health, data_name):
        """Select a currently tradable instrument row bound to this data feed."""
        if not isinstance(health, dict) or health.get("evidence_complete") is not True:
            return None
        aliases = set(self._symbol_aliases(data_name))
        snapshot_instrument = str(health.get("instrument_id") or "").strip()
        if snapshot_instrument and not aliases.intersection(
            self._symbol_aliases(snapshot_instrument)
        ):
            return None
        rows = health.get("instruments")
        if not isinstance(rows, list):
            return None
        for row in rows:
            if not isinstance(row, dict):
                continue
            instrument = row.get("instrument_id") or row.get("InstrumentID")
            exchange = row.get("exchange_id") or row.get("ExchangeID")
            candidates = set(self._symbol_aliases(instrument))
            if instrument and exchange:
                candidates.update(self._symbol_aliases(f"{exchange}.{instrument}"))
            if not aliases.intersection(candidates):
                continue
            raw_trading = row.get("is_trading", row.get("IsTrading"))
            trading = raw_trading is True or (
                type(raw_trading) in {int, float} and raw_trading == 1
            )
            if isinstance(raw_trading, str):
                trading = raw_trading.strip().lower() in {"1", "true", "yes"}
            return row if trading else None
        return None

    def _ctp_shutdown_limit_price(self, data, is_buy):
        """Return a fresh opponent-price close limit protected by at most one tick."""
        getter = getattr(self.store, "get_latest_tick_snapshot", None)
        if not callable(getter):
            return None
        data_name = self._position_key(data)
        quote = getter(data_name)
        if quote is None:
            return None
        if str(self._quote_value(quote, "schema_version") or "") != "ctp.quote.v2":
            return None
        if str(self._quote_value(quote, "quality") or "").strip().upper() != "GOOD":
            return None
        raw_flags = self._quote_value(quote, "quality_flags") or ()
        if isinstance(raw_flags, str):
            raw_flags = (raw_flags,)
        try:
            blocking_flags = {
                str(flag) for flag in raw_flags if str(flag) not in {"NO_TRADE", "VOLUME_BASELINE"}
            }
        except TypeError:
            return None
        if blocking_flags:
            return None
        health_getter = getattr(self.store, "get_ctp_query_health", None)
        health = health_getter() if callable(health_getter) else {}
        instrument = self._current_ctp_instrument_row(health, data_name)
        if instrument is None:
            return None
        ready = getattr(self.store, "is_stream_ready", None)
        if callable(ready) and ready(data_name) is not True:
            return None
        if bool(self._quote_value(quote, "stale")):
            return None
        continuity = str(self._quote_value(quote, "continuity_status", "continuity") or "")
        if continuity in {"gap", "disconnected", "stale", "invalid"}:
            return None

        bid = self._first_number(self._quote_value(quote, "bid_price", "BidPrice1"))
        ask = self._first_number(self._quote_value(quote, "ask_price", "AskPrice1"))
        bid_size = self._first_number(
            self._quote_value(quote, "bid_volume", "bid_size", "BidVolume1")
        )
        ask_size = self._first_number(
            self._quote_value(quote, "ask_volume", "ask_size", "AskVolume1")
        )
        if (
            not all(
                value is not None and math.isfinite(value) and 0 < value < 1.0e50
                for value in (bid, ask, bid_size, ask_size)
            )
            or bid > ask
        ):
            return None

        received_ns = self._quote_value(quote, "recv_monotonic_ns", "received_monotonic_ns")
        maximum_age = float(self.p.ctp_quote_max_age_seconds)
        if not math.isfinite(maximum_age) or maximum_age < 0:
            return None
        if type(received_ns) is not int or received_ns <= 0:
            return None
        age = max(time.monotonic_ns() - received_ns, 0) / 1_000_000_000.0
        if age > maximum_age:
            return None

        event_time = self._quote_datetime_utc(self._quote_value(quote, "event_time_utc"))
        recv_time = self._quote_datetime_utc(self._quote_value(quote, "recv_time_utc"))
        if event_time is None or recv_time is None:
            return None
        event_age = (recv_time - event_time).total_seconds()
        recv_wall_age = (_dt.datetime.now(_dt.timezone.utc) - recv_time).total_seconds()
        if (
            event_age < -0.5
            or event_age > maximum_age
            or recv_wall_age < -0.5
            or recv_wall_age > maximum_age
        ):
            return None

        session_getter = getattr(self.store, "get_ctp_session_state", None)
        if not callable(session_getter):
            return None
        try:
            session = session_getter()
            quote_generation = int(
                self._quote_value(quote, "connection_generation", "stream_generation") or 0
            )
            session_generation = int(session.get("connection_generation") or 0)
        except (TypeError, ValueError):
            return None
        if quote_generation <= 0 or quote_generation != session_generation:
            return None

        rules = self._contract_rules_for(data_name)
        price_tick = self._first_number(
            self._quote_value(quote, "price_tick", "PriceTick"),
            instrument.get("price_tick"),
            instrument.get("PriceTick"),
            rules.get("min_price_tick"),
            rules.get("price_tick"),
            rules.get("tick_size"),
        )
        lower = self._first_number(
            self._quote_value(quote, "lower_limit_price", "LowerLimitPrice"),
            instrument.get("lower_limit_price"),
            instrument.get("LowerLimitPrice"),
            rules.get("lower_limit_price"),
            rules.get("LowerLimitPrice"),
        )
        upper = self._first_number(
            self._quote_value(quote, "upper_limit_price", "UpperLimitPrice"),
            instrument.get("upper_limit_price"),
            instrument.get("UpperLimitPrice"),
            rules.get("upper_limit_price"),
            rules.get("UpperLimitPrice"),
        )
        if (
            not all(
                value is not None and math.isfinite(value) and 0 < value < 1.0e50
                for value in (price_tick, lower, upper)
            )
            or lower > upper
        ):
            return None

        def on_grid(value):
            scaled = value / price_tick
            return math.isfinite(scaled) and abs(scaled - round(scaled)) <= 1e-8

        if not all(on_grid(value) for value in (bid, ask, lower, upper)):
            return None
        opponent = ask if is_buy else bid
        protected = min(ask + price_tick, upper) if is_buy else max(bid - price_tick, lower)
        if (
            protected < lower
            or protected > upper
            or not on_grid(protected)
            or (is_buy and (protected < opponent or protected - opponent > price_tick + 1e-12))
            or (not is_buy and (protected > opponent or opponent - protected > price_tick + 1e-12))
        ):
            return None
        return protected

    def _submit_known_position_closes(self):
        """Generate typed reduce-only orders only for locally proven position legs."""
        data_by_key = {
            self._position_key(data): data for data in getattr(self.store, "_data_feeds", []) or []
        }
        orders = []
        missing_data = []

        def submit_leg(key, position_side, size, is_buy):
            if abs(float(size or 0.0)) <= 1e-12:
                return
            data = data_by_key.get(key)
            if data is None:
                missing_data.append((key, position_side))
                return
            method = self.buy if is_buy else self.sell
            kwargs: "Dict[str, Any]" = {}
            if self._requires_explicit_offset(data):
                price = self._ctp_shutdown_limit_price(data, is_buy)
                if price is None:
                    missing_data.append((key, position_side, "ctp_close_quote_unproven"))
                    return
                kwargs.update(exectype=OrderBase.Limit, price=price)
            else:
                kwargs["exectype"] = OrderBase.Market
            orders.append(
                method(
                    None,
                    data,
                    size=abs(float(size)),
                    position_side=position_side,
                    offset="close",
                    reduce_only=True,
                    shutdown_order=True,
                    **kwargs,
                )
            )

        if self._is_dual_side_mode():
            for key, position in list(self.long_positions.items()):
                submit_leg(key, "long", position.size, False)
            for key, position in list(self.short_positions.items()):
                submit_leg(key, "short", position.size, True)
        else:
            for key, position in list(self.positions.items()):
                size = float(position.size or 0.0)
                submit_leg(key, None, size, size < 0)
        return orders, missing_data

    def _reconcile_proves_flat(self, result):
        if not self._reconcile_proves_clean_execution(result):
            return False
        positions = result.get("positions")
        if type(positions) is not list:
            return False
        for row in positions:
            if not isinstance(row, dict) or "quantity" not in row:
                return False
            if "quantity_known" in row and row.get("quantity_known") is not True:
                return False
            value = row["quantity"]
            if isinstance(value, bool):
                return False
            try:
                quantity = float(value)
                if not math.isfinite(quantity) or abs(quantity) > 1e-12:
                    return False
            except (TypeError, ValueError, OverflowError):
                return False
        return type(result.get("open_orders")) is list

    @staticmethod
    def _is_sha256_hex(value):
        text = str(value or "").strip().lower()
        return len(text) == 64 and all(character in "0123456789abcdef" for character in text)

    def _reconcile_proves_clean_execution(self, result):
        """Require a current, fenced and fully settled SDK execution snapshot."""
        if not isinstance(result, dict):
            return False
        if (
            result.get("evidence_complete") is not True
            or result.get("evidence_errors")
            or result.get("error_code")
        ):
            return False
        configured_value = result.get("configured_venues")
        reconciled_value = result.get("reconciled_venues")
        if type(configured_value) is not list or type(reconciled_value) is not list:
            return False
        configured = {str(item) for item in configured_value if item}
        reconciled = {str(item) for item in reconciled_value if item}
        if (
            not configured
            or len(configured) != len(configured_value)
            or len(reconciled) != len(reconciled_value)
            or reconciled != configured
        ):
            return False
        execution_summary = result.get("execution_summary")
        if not isinstance(execution_summary, dict):
            return False
        try:
            active_orders = execution_summary["active_orders"]
            generation = result["generation"]
            session_generation = result["session_generation"]
            summary_generation = execution_summary["generation"]
            summary_session_generation = execution_summary["session_generation"]
            fencing_epoch = result["fencing_epoch"]
            summary_fencing_epoch = execution_summary["fencing_epoch"]
            as_of_monotonic_ns = result["as_of_monotonic_ns"]
            summary_as_of_monotonic_ns = execution_summary["as_of_monotonic_ns"]
        except KeyError:
            return False
        exact_positive_ints = (
            generation,
            session_generation,
            summary_generation,
            summary_session_generation,
            fencing_epoch,
            summary_fencing_epoch,
            as_of_monotonic_ns,
            summary_as_of_monotonic_ns,
        )
        if any(type(value) is not int or value <= 0 for value in exact_positive_ints):
            return False
        if (
            type(active_orders) is not int
            or active_orders != 0
            or generation != session_generation
            or generation != summary_generation
            or generation != summary_session_generation
            or fencing_epoch != summary_fencing_epoch
            or as_of_monotonic_ns > time.monotonic_ns()
            or summary_as_of_monotonic_ns > as_of_monotonic_ns
            or execution_summary.get("session_enabled") is not True
            or execution_summary.get("evidence_complete") is not True
            or execution_summary.get("evidence_errors")
            or execution_summary.get("error_code")
        ):
            return False
        reconciliation_errors = execution_summary.get("reconciliation_errors")
        if type(reconciliation_errors) is not dict or reconciliation_errors:
            return False
        for key in ("unknown_ids", "fee_unresolved_orders", "funding_unresolved_orders"):
            value = execution_summary.get(key)
            if type(value) is not list or value:
                return False
        if type(result.get("unknown_ids")) is not list or result["unknown_ids"]:
            return False
        if (
            result.get("trading_blocked") is not False
            or execution_summary.get("trading_blocked") is not False
        ):
            return False
        open_orders = result.get("open_orders")
        positions = result.get("positions")
        if type(open_orders) is not list or open_orders:
            return False
        if type(positions) is not list:
            return False
        identity_hash = result.get("identity_binding_sha256")
        summary_identity_hash = execution_summary.get("identity_binding_sha256")
        return self._is_sha256_hex(identity_hash) and identity_hash == summary_identity_hash

    def get_shutdown_state(self):
        """Return the last bounded winddown result."""
        return deepcopy(self._shutdown_summary)

    def get_shutdown_summary(self):
        """Return the public bounded winddown evidence used by run acceptance."""
        return self.get_shutdown_state()

    def get_market_data_only_audit(self):
        """Return local rejected-write counts for an observation-only Broker.

        The counts do not attest provider-side state; they only record calls
        rejected before any Store command can be routed.  They are useful to a
        strategy observation that must fail closed if callback logic attempts
        submit/cancel behavior despite its read-only contract.
        """

        counts = self._market_data_only_rejections
        submit_rejected = int(counts["submit"])
        cancel_rejected = int(counts["cancel"])
        batch_cancel_rejected = int(counts["batch_cancel"])
        return {
            "submit_rejected": submit_rejected,
            "cancel_rejected": cancel_rejected,
            "batch_cancel_rejected": batch_cancel_rejected,
            "total_rejected": submit_rejected + cancel_rejected + batch_cancel_rejected,
        }

    def _record_market_data_only_rejection(self, operation: str) -> None:
        """Record a local rejection on this Broker and its owning Store.

        The Store-level increment makes a bounded observation's audit cover
        every Broker attached to the same Store, including one created later
        through ``store.getbroker()``.  Older/custom Store doubles remain
        compatible because they need not expose the optional recorder.
        """

        self._market_data_only_rejections[operation] += 1
        recorder = getattr(self.store, "record_market_data_only_broker_rejection", None)
        if callable(recorder):
            recorder(operation)

    def get_last_reconcile_result(self):
        """Return a credential-safe copy of the latest remote risk snapshot."""
        return deepcopy(self._redact_runtime_value(self._last_reconcile_result))

    def request_reconcile(self):
        """Queue a public, read-only remote reconciliation request."""
        if self._periodic_reconcile_pending:
            return {"queued": True, "status": "already_pending"}
        method = getattr(self.store, "enqueue_reconcile", None)
        if not callable(method):
            return {
                "queued": False,
                "error_code": "reconcile_capability_unavailable",
            }
        try:
            receipt = method()
        except Exception as exc:
            _safe_log("warning", "btapibroker:1804 fallback on Exception")
            self._sanitize_exception(exc)
            return {
                "queued": False,
                "error_code": self._safe_exception_code(exc, "reconcile_request_failed"),
            }
        safe_receipt = deepcopy(self._redact_runtime_value(receipt))
        self._periodic_reconcile_pending = bool(
            isinstance(safe_receipt, dict) and safe_receipt.get("queued") is True
        )
        return safe_receipt

    def _begin_ctp_reconciliation(self, reason):
        """Latch the CTP reopen barrier until two stable complete reads agree."""
        self._ctp_reconciliation_required = True
        self._ctp_reconciliation_rounds = 0
        self._ctp_reconciliation_fingerprint = None
        self._ctp_reconciliation_generation = None
        self._ctp_reconciliation_account_fingerprint = None
        self._ctp_reconciliation_request_ids = None
        self._ctp_reconciliation_unknown_intent_count = None
        self._ctp_reconciliation_unmatched_trade_count = None
        self._ctp_reconciliation_round_event_epoch = None
        self._ctp_reconciliation_reason = str(reason or "ctp_reconciliation_required")

    def _reset_ctp_reconciliation_rounds(self, reason):
        self._ctp_reconciliation_rounds = 0
        self._ctp_reconciliation_fingerprint = None
        self._ctp_reconciliation_generation = None
        self._ctp_reconciliation_account_fingerprint = None
        self._ctp_reconciliation_request_ids = None
        self._ctp_reconciliation_unknown_intent_count = None
        self._ctp_reconciliation_unmatched_trade_count = None
        self._ctp_reconciliation_round_event_epoch = None
        self._ctp_reconciliation_reason = str(reason or "ctp_reconciliation_incomplete")

    def _ctp_local_positions_flat(self):
        stores = (
            (self.long_positions, self.short_positions)
            if self._is_dual_side_mode()
            else (self.positions,)
        )
        return all(
            abs(float(position.size or 0.0)) <= 1e-12
            for position_store in stores
            for position in position_store.values()
        )

    @staticmethod
    def _ctp_query_row_identifiers(row):
        return {
            str(row.get(key))
            for key in (
                "external_order_id",
                "order_id",
                "id",
                "order_ref",
                "OrderSysID",
                "OrderRef",
                "client_order_id",
            )
            if row.get(key) not in (None, "")
        }

    @classmethod
    def _ctp_order_query_identity_complete(cls, row):
        if not isinstance(row, dict):
            return False
        order_ref = cls._extract_update_value(row, "order_ref", "OrderRef")
        order_sys_id = cls._extract_update_value(
            row, "external_order_id", "order_sys_id", "OrderSysID"
        )
        front_id = cls._extract_update_value(row, "front_id", "FrontID")
        session_id = cls._extract_update_value(row, "session_id", "SessionID")
        exchange_id = (
            str(cls._extract_update_value(row, "exchange_id", "ExchangeID") or "").strip().upper()
        )
        instrument_id = (
            str(cls._extract_update_value(row, "instrument_id", "InstrumentID") or "")
            .strip()
            .upper()
        )
        trading_day = str(cls._extract_update_value(row, "trading_day", "TradingDay") or "").strip()
        try:
            valid_session = int(front_id) > 0 and int(session_id) > 0
        except (TypeError, ValueError):
            valid_session = False
        status = cls._normalize_remote_order_status(row.get("status"))
        order_sys_required = status not in {"rejected"}
        return bool(
            order_ref not in (None, "")
            and (order_sys_id not in (None, "") or not order_sys_required)
            and valid_session
            and exchange_id in {"SHFE", "DCE", "CZCE", "CFFEX", "INE", "GFEX"}
            and re.fullmatch(r"[A-Z][A-Z0-9]{2,30}", instrument_id)
            and re.fullmatch(r"\d{8}", trading_day)
        )

    @classmethod
    def _ctp_trade_query_identity_complete(cls, row):
        if not isinstance(row, dict):
            return False
        required = (
            cls._extract_update_value(row, "trade_id", "TradeID"),
            cls._extract_update_value(row, "order_sys_id", "OrderSysID"),
            cls._extract_update_value(row, "order_ref", "OrderRef"),
            cls._extract_update_value(row, "exchange_id", "ExchangeID"),
            cls._extract_update_value(row, "instrument_id", "InstrumentID"),
            cls._extract_update_value(row, "trading_day", "TradingDay", "TradeDate"),
            cls._extract_update_value(row, "connection_generation", "ConnectionGeneration"),
        )
        if any(value in (None, "") for value in required):
            return False
        exchange = str(required[3]).strip().upper()
        instrument = str(required[4]).strip().upper()
        trading_day = str(required[5]).strip()
        try:
            generation = int(required[6])
        except (TypeError, ValueError):
            generation = 0
        return bool(
            generation > 0
            and exchange in {"SHFE", "DCE", "CZCE", "CFFEX", "INE", "GFEX"}
            and re.fullmatch(r"[A-Z][A-Z0-9]{2,30}", instrument)
            and re.fullmatch(r"\d{8}", trading_day)
        )

    @staticmethod
    def _ctp_empty_sequence(value):
        return isinstance(value, (list, tuple)) and not value

    def _ctp_normalized_unmatched_trade_count(self, snapshot):
        """Return the execution count, allowing zero only for proven pre-start state."""
        summary = snapshot.get("execution_summary")
        if not isinstance(summary, Mapping):
            return None
        if "unmatched_trade_count" in summary:
            value = summary.get("unmatched_trade_count")
            return value if type(value) is int and value >= 0 else None

        query_results = snapshot.get("query_results")
        trade_query = query_results.get("trades") if isinstance(query_results, Mapping) else None
        trades = snapshot.get("trades")
        submit_calls = summary.get("submit_calls")
        safe_start = (
            summary.get("market_data_only") is True
            and summary.get("armed") is False
            and type(submit_calls) is int
            and submit_calls == 0
            and self._ctp_empty_sequence(summary.get("unknown_ids"))
            and not self._pending_trade_updates
            and isinstance(trades, list)
            and not trades
            and isinstance(trade_query, Mapping)
            and trade_query.get("complete") is True
            and trade_query.get("is_last_seen") is True
            and isinstance(trade_query.get("records"), list)
            and not trade_query.get("records")
        )
        return 0 if safe_start else None

    def _ctp_local_trade_binding(self, row, generation):
        """Resolve one CTP trade row to exactly one locally known order."""
        order_sys_id = str(self._extract_update_value(row, "order_sys_id", "OrderSysID") or "")
        order_ref = str(self._extract_update_value(row, "order_ref", "OrderRef") or "")
        instrument_id = (
            str(self._extract_update_value(row, "instrument_id", "InstrumentID") or "")
            .strip()
            .upper()
        )
        try:
            row_generation = int(
                self._extract_update_value(row, "connection_generation", "ConnectionGeneration")
            )
        except (TypeError, ValueError):
            return None, "trade_row_generation_invalid"
        if row_generation != generation:
            return None, "trade_row_generation_mismatch"

        matches = []
        for order in self.orders.values():
            local_sys_id = str(self._order_info_get(order, "external_order_id") or "")
            local_refs = {
                str(value)
                for value in (
                    self._order_info_get(order, "ctp_order_ref"),
                    self._order_info_get(order, "client_order_id"),
                    getattr(order, "ref", None),
                )
                if value not in (None, "")
            }
            local_instruments = {
                str(value).strip().upper()
                for value in (
                    self._order_info_get(order, "instrument_id"),
                    self._order_info_get(order, "ctp_instrument_id"),
                    self._position_key(order.data),
                )
                if value not in (None, "")
            }
            if (
                local_sys_id == order_sys_id
                and order_ref in local_refs
                and instrument_id in local_instruments
            ):
                local_generation = self._order_info_get(order, "connection_generation")
                try:
                    local_generation = int(local_generation)
                except (TypeError, ValueError):
                    return None, "trade_order_generation_missing"
                if local_generation != generation:
                    return None, "trade_order_generation_mismatch"
                matches.append(order)
        if not matches:
            return None, "foreign_trade_row"
        if len(matches) != 1:
            return None, "ambiguous_trade_row"
        return matches[0], None

    def _ctp_validate_trade_reconciliation(self, snapshot, generation):
        """Validate remote CTP trades against the current local execution ledger."""
        trades = snapshot.get("trades")
        if not isinstance(trades, list):
            return "trade_query_invalid"
        if self._pending_trade_updates:
            return "pending_trade_updates"
        seen_trade_ids = set()
        matched_orders = set()
        for row in trades:
            if not self._ctp_trade_query_identity_complete(row):
                return "trade_row_identity_incomplete"
            trade_id = str(self._extract_update_value(row, "trade_id", "TradeID"))
            if trade_id in seen_trade_ids:
                return "duplicate_trade_row"
            seen_trade_ids.add(trade_id)
            order, reason = self._ctp_local_trade_binding(row, generation)
            if reason is not None:
                return reason
            matched_orders.add(id(order))

        for order in self.orders.values():
            if bool(self._order_info_get(order, "execution_pending_trades", False)):
                return "missing_local_expected_trade"
        return None

    def _ctp_terminal_query_row(self, order, rows):
        identifiers = {
            str(value)
            for value in (
                getattr(order, "ref", None),
                self._order_info_get(order, "external_order_id"),
                self._order_info_get(order, "ctp_order_ref"),
                self._order_info_get(order, "client_order_id"),
            )
            if value not in (None, "")
        }
        for row in rows:
            if not self._ctp_order_query_identity_complete(row) or not identifiers.intersection(
                self._ctp_query_row_identifiers(row)
            ):
                continue
            row_instrument = self._extract_update_value(row, "instrument_id", "InstrumentID")
            row_exchange = self._extract_update_value(row, "exchange_id", "ExchangeID")
            row_aliases = set(self._symbol_aliases(row_instrument))
            row_aliases.update(self._symbol_aliases(f"{row_exchange}.{row_instrument}"))
            if not set(self._symbol_aliases(self._position_key(order.data))).intersection(
                row_aliases
            ):
                continue
            status = self._normalize_remote_order_status(row.get("status"))
            if status in {"canceled", "rejected", "expired"}:
                return {**row, "status": status}
        return None

    def get_ctp_reconciliation_state(self):
        """Return the public two-round CTP reopen-barrier state."""
        return {
            "required": bool(self._ctp_reconciliation_required),
            "complete": not self._ctp_reconciliation_required,
            "consecutive_complete_rounds": int(self._ctp_reconciliation_rounds),
            "required_rounds": 2,
            "connection_generation": self._ctp_reconciliation_generation,
            "account_fingerprint": self._ctp_reconciliation_account_fingerprint,
            "request_ids": deepcopy(self._ctp_reconciliation_request_ids),
            "unknown_intent_count": self._ctp_reconciliation_unknown_intent_count,
            "unmatched_trade_count": self._ctp_reconciliation_unmatched_trade_count,
            "reconciliation_fingerprint": self._ctp_reconciliation_fingerprint,
            "event_epoch": self._ctp_reconciliation_event_epoch,
            "reason": self._ctp_reconciliation_reason,
        }

    def record_ctp_reconciliation(self, snapshot):
        """Advance the reopen barrier only for two unchanged complete flat snapshots."""
        if not isinstance(snapshot, dict) or snapshot.get("evidence_complete") is not True:
            self._reset_ctp_reconciliation_rounds("query_evidence_incomplete")
            return self.get_ctp_reconciliation_state()
        if snapshot.get("flat") is not True:
            self._reset_ctp_reconciliation_rounds("remote_exposure_not_flat")
            return self.get_ctp_reconciliation_state()
        unknown_intent_count = snapshot.get("unknown_intent_count")
        unmatched_trade_count = snapshot.get("unmatched_trade_count")
        summary = snapshot.get("execution_summary")
        unmatched_field_missing = isinstance(summary, Mapping) and (
            "unmatched_trade_count" not in summary
        )
        if (
            "unmatched_trade_count" not in snapshot
            and not unmatched_field_missing
            and isinstance(summary, Mapping)
        ):
            unmatched_trade_count = summary.get("unmatched_trade_count")
        if unmatched_trade_count is None and unmatched_field_missing:
            unmatched_trade_count = self._ctp_normalized_unmatched_trade_count(snapshot)
        strict_trade_path = False
        if unmatched_trade_count is None and unmatched_field_missing:
            # The actual-trade path is resolved only after all query and row
            # identity checks below.  Do not turn an empty/non-binding query
            # into zero merely because the SDK omitted this field.
            strict_trade_path = True
        counts_complete = all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (unknown_intent_count, unmatched_trade_count)
        )
        if not counts_complete and not (
            strict_trade_path
            and unmatched_trade_count is None
            and isinstance(snapshot.get("trades"), list)
            and snapshot.get("trades")
        ):
            self._reset_ctp_reconciliation_rounds("execution_summary_incomplete")
            return self.get_ctp_reconciliation_state()
        unmatched_trade_pending_binding = (
            strict_trade_path and unmatched_trade_count is None and bool(snapshot.get("trades"))
        )
        if unknown_intent_count != 0 or (
            unmatched_trade_count != 0 and not unmatched_trade_pending_binding
        ):
            self._reset_ctp_reconciliation_rounds("execution_summary_not_clear")
            self._ctp_reconciliation_unknown_intent_count = unknown_intent_count
            self._ctp_reconciliation_unmatched_trade_count = unmatched_trade_count
            return self.get_ctp_reconciliation_state()
        fingerprint = str(snapshot.get("reconciliation_fingerprint") or "")
        account = str(snapshot.get("account_fingerprint") or "")
        try:
            generation = int(snapshot.get("connection_generation") or 0)
        except (TypeError, ValueError):
            generation = 0
        if len(fingerprint) != 64 or not account or generation <= 0:
            self._reset_ctp_reconciliation_rounds("query_identity_incomplete")
            return self.get_ctp_reconciliation_state()
        query_results = snapshot.get("query_results")
        required_queries = ("account", "positions", "orders", "trades")
        if not isinstance(query_results, dict):
            self._reset_ctp_reconciliation_rounds("query_request_ids_incomplete")
            return self.get_ctp_reconciliation_state()
        try:
            request_ids = tuple(
                int(query_results[name].get("request_id") or 0) for name in required_queries
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            request_ids = ()
        if len(request_ids) != len(required_queries) or any(value <= 0 for value in request_ids):
            self._reset_ctp_reconciliation_rounds("query_request_ids_incomplete")
            return self.get_ctp_reconciliation_state()
        if len(set(request_ids)) != len(request_ids):
            self._reset_ctp_reconciliation_rounds("query_request_ids_not_independent")
            return self.get_ctp_reconciliation_state()
        if self._pending_trade_updates:
            self._reset_ctp_reconciliation_rounds("unmatched_trade_updates")
            return self.get_ctp_reconciliation_state()

        rows = snapshot.get("orders")
        if not isinstance(rows, list):
            self._reset_ctp_reconciliation_rounds("order_query_invalid")
            return self.get_ctp_reconciliation_state()
        trades = snapshot.get("trades")
        if not all(self._ctp_order_query_identity_complete(row) for row in rows):
            self._reset_ctp_reconciliation_rounds("order_query_identity_incomplete")
            return self.get_ctp_reconciliation_state()
        if not isinstance(trades, list) or not all(
            self._ctp_trade_query_identity_complete(row) for row in trades
        ):
            self._reset_ctp_reconciliation_rounds("trade_query_identity_incomplete")
            return self.get_ctp_reconciliation_state()
        trade_error = self._ctp_validate_trade_reconciliation(snapshot, generation)
        if trade_error is not None:
            self._reset_ctp_reconciliation_rounds(trade_error)
            return self.get_ctp_reconciliation_state()
        if unmatched_trade_count is None:
            if strict_trade_path and trades:
                unmatched_trade_count = 0
            else:
                self._reset_ctp_reconciliation_rounds("execution_summary_incomplete")
                return self.get_ctp_reconciliation_state()
        alive = [order for order in self.orders.values() if order.alive()]
        terminal_unknowns = {}
        for order in alive:
            if bool(self._order_info_get(order, "execution_unknown", False)):
                terminal = self._ctp_terminal_query_row(order, rows)
                if terminal is not None:
                    terminal_unknowns[order.ref] = terminal
                    continue
            self._reset_ctp_reconciliation_rounds("local_order_not_terminal")
            return self.get_ctp_reconciliation_state()
        if not self._ctp_local_positions_flat():
            self._reset_ctp_reconciliation_rounds("local_position_not_flat")
            return self.get_ctp_reconciliation_state()

        same_round = bool(
            self._ctp_reconciliation_fingerprint == fingerprint
            and self._ctp_reconciliation_generation == generation
            and self._ctp_reconciliation_account_fingerprint == account
            and self._ctp_reconciliation_round_event_epoch == self._ctp_reconciliation_event_epoch
        )
        if same_round and self._ctp_reconciliation_request_ids is not None:
            if set(request_ids).intersection(self._ctp_reconciliation_request_ids):
                self._ctp_reconciliation_reason = "query_snapshot_replayed"
                return self.get_ctp_reconciliation_state()
        self._ctp_reconciliation_rounds = self._ctp_reconciliation_rounds + 1 if same_round else 1
        self._ctp_reconciliation_fingerprint = fingerprint
        self._ctp_reconciliation_generation = generation
        self._ctp_reconciliation_account_fingerprint = account
        self._ctp_reconciliation_request_ids = request_ids
        self._ctp_reconciliation_unknown_intent_count = unknown_intent_count
        self._ctp_reconciliation_unmatched_trade_count = unmatched_trade_count
        self._ctp_reconciliation_round_event_epoch = self._ctp_reconciliation_event_epoch
        self._ctp_reconciliation_reason = (
            "strict_bound_trade_reconciliation_awaiting_second_snapshot"
            if strict_trade_path
            else "awaiting_second_complete_snapshot"
        )
        if self._ctp_reconciliation_rounds < 2:
            return self.get_ctp_reconciliation_state()

        for ref, update in terminal_unknowns.items():
            resolved = dict(update)
            resolved.setdefault("kind", "order")
            resolved["bt_order_ref"] = ref
            resolved["terminal_confirmed"] = True
            self._apply_order_update(resolved, from_query=True)
        if (
            any(order.alive() for order in self.orders.values())
            or not self._ctp_local_positions_flat()
        ):
            self._reset_ctp_reconciliation_rounds("local_state_did_not_converge")
            return self.get_ctp_reconciliation_state()
        self._ctp_reconciliation_required = False
        self._ctp_reconciliation_reason = (
            "two_complete_snapshots_agree_strict_bound_trades"
            if strict_trade_path
            else "two_complete_snapshots_agree"
        )
        return self.get_ctp_reconciliation_state()

    def reconcile_ctp_execution(self, *, timeout=5.0):
        """Perform one public, read-only CTP reconciliation round."""
        method = getattr(self.store, "get_ctp_reconciliation_snapshot", None)
        if not callable(method):
            self._reset_ctp_reconciliation_rounds("query_capability_unavailable")
            return self.get_ctp_reconciliation_state()
        try:
            snapshot = method(timeout=timeout)
        except Exception:
            _safe_log("warning", "btapibroker:2266 fallback on Exception")
            self._reset_ctp_reconciliation_rounds("query_failed")
            return self.get_ctp_reconciliation_state()
        state = self.record_ctp_reconciliation(snapshot)
        state["snapshot"] = deepcopy(self._redact_runtime_value(snapshot))
        return state

    def request_ctp_reconciliation(self, callback=None, *, timeout=5.0):
        """Queue one complete CTP query round and deliver it from :meth:`next`."""
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
            if notifier not in self._ctp_reconciliation_callbacks:
                self._ctp_reconciliation_callbacks.append(notifier)
        if self._ctp_reconciliation_pending:
            return {"queued": True, "status": "already_pending"}
        method = getattr(self.store, "enqueue_ctp_reconciliation", None)
        if not callable(method):
            self._ctp_reconciliation_callbacks.clear()
            return {"queued": False, "error_code": "ctp_query_capability_unavailable"}
        try:
            receipt = method(timeout=max(float(timeout), 0.0))
        except Exception as exc:
            _safe_log("warning", "btapibroker:2295 fallback on Exception")
            self._sanitize_exception(exc)
            self._ctp_reconciliation_callbacks.clear()
            return {
                "queued": False,
                "error_code": self._safe_exception_code(exc, "ctp_reconcile_request_failed"),
            }
        safe_receipt = deepcopy(self._redact_runtime_value(receipt))
        self._ctp_reconciliation_pending = bool(
            isinstance(safe_receipt, dict) and safe_receipt.get("queued") is True
        )
        if not self._ctp_reconciliation_pending:
            self._ctp_reconciliation_callbacks.clear()
        return safe_receipt

    def get_last_ctp_reconciliation_result(self):
        """Return the most recent callback-safe result without issuing network I/O."""
        return deepcopy(self._redact_runtime_value(self._last_ctp_reconciliation_result))

    def _ctp_reconciliation_callback_snapshot(self, snapshot, state):
        """Attach main-thread ledger evidence to one complete-query snapshot."""
        result = deepcopy(self._redact_runtime_value(snapshot))
        local_unknown = sum(
            1
            for order in self.orders.values()
            if order.alive() and bool(self._order_info_get(order, "execution_unknown", False))
        )
        remote_unknown = result.get("unknown_intent_count")
        unknown_count = (
            max(int(remote_unknown), local_unknown)
            if isinstance(remote_unknown, int) and not isinstance(remote_unknown, bool)
            else local_unknown
        )
        remote_unmatched = result.get("unmatched_trade_count")
        unmatched_count = len(self._pending_trade_updates)
        if isinstance(remote_unmatched, int) and not isinstance(remote_unmatched, bool):
            unmatched_count = max(remote_unmatched, unmatched_count)
        local_active = sum(1 for order in self.orders.values() if order.alive())
        remote_active = result.get("active_order_count")
        active_count = local_active
        if isinstance(remote_active, int) and not isinstance(remote_active, bool):
            active_count = max(remote_active, local_active)
        local_position_lots = sum(
            abs(float(position.size or 0.0))
            for position_store in (
                (self.long_positions, self.short_positions)
                if self._is_dual_side_mode()
                else (self.positions,)
            )
            for position in position_store.values()
        )
        remote_position_lots = result.get("position_lots")
        position_lots = local_position_lots
        if isinstance(remote_position_lots, (int, float)) and not isinstance(
            remote_position_lots, bool
        ):
            position_lots = max(abs(float(remote_position_lots)), local_position_lots)
        result.update(
            position_lots=position_lots,
            active_order_count=active_count,
            unknown_intent_count=unknown_count,
            unmatched_trade_count=unmatched_count,
            broker_reconciliation_state=deepcopy(state),
        )
        return result

    def get_execution_summary(self):
        """Return the SDK execution-session summary through a safe public view."""
        reconcile = self._last_reconcile_result
        if isinstance(reconcile, dict) and isinstance(reconcile.get("execution_summary"), dict):
            return deepcopy(self._redact_runtime_value(reconcile["execution_summary"]))
        method = getattr(self.store, "get_execution_summary", None)
        if not callable(method):
            return {
                "unknown_ids": ["execution_summary_unavailable"],
                "fee_unresolved_orders": ["execution_summary_unavailable"],
                "active_orders": None,
                "trading_blocked": True,
                "evidence_complete": False,
                "error_code": "execution_summary_unavailable",
            }
        try:
            summary = method()
        except Exception as exc:
            _safe_log("warning", "btapibroker:2378 fallback on Exception")
            self._sanitize_exception(exc)
            return {
                "unknown_ids": ["execution_summary_failed"],
                "fee_unresolved_orders": ["execution_summary_failed"],
                "active_orders": None,
                "trading_blocked": True,
                "evidence_complete": False,
                "error_code": self._safe_exception_code(exc, "execution_summary_failed"),
            }
        if not isinstance(summary, dict):
            return {
                "unknown_ids": ["execution_summary_invalid"],
                "fee_unresolved_orders": ["execution_summary_invalid"],
                "active_orders": None,
                "trading_blocked": True,
                "evidence_complete": False,
                "error_code": "execution_summary_invalid",
            }
        try:
            generation = int(summary.get("generation", summary.get("session_generation", 0)) or 0)
            fencing_epoch = int(summary.get("fencing_epoch", 0) or 0)
        except (TypeError, ValueError):
            generation = 0
            fencing_epoch = 0
        if self._uses_async_commands() and (generation <= 0 or fencing_epoch <= 0):
            summary = {
                **summary,
                "trading_blocked": True,
                "evidence_complete": False,
                "evidence_errors": ["reconcile_snapshot_required"],
                "error_code": "reconcile_snapshot_required",
            }
        return deepcopy(self._redact_runtime_value(summary))

    @staticmethod
    def _account_risk_snapshot_incomplete(snapshot, error_code):
        """Return a non-loss fail-closed view while retaining existing risk values."""

        result = deepcopy(snapshot)
        errors = result.get("evidence_errors")
        if isinstance(errors, (Mapping, list, tuple, set, frozenset)):
            existing = [item for item in errors if isinstance(item, str)]
        elif isinstance(errors, str) and errors:
            existing = [errors]
        else:
            existing = []
        if error_code not in existing:
            existing.append(error_code)
        result["evidence_complete"] = False
        result["evidence_errors"] = existing
        result["error_code"] = error_code
        return result

    def _account_risk_snapshot_unavailable(self, error_code="account_risk_snapshot_unavailable"):
        """Build the stable fail-closed shape when no callback snapshot is usable."""

        routes_method = getattr(self.store, "get_symbol_routes", None)
        try:
            routes = routes_method() if callable(routes_method) else {}
        except Exception as exc:
            _safe_log("warning", "btapibroker:account-risk route lookup failed")
            self._sanitize_exception(exc)
            routes = {}
        if not isinstance(routes, Mapping):
            routes = {}
        venues = sorted(
            {
                str(venue).partition("___")[0].strip().lower()
                for venue in (routes or {}).values()
                if str(venue).strip()
            }
        )
        return {
            "baseline_equity": None,
            "current_equity": None,
            "realized_net": None,
            "configured_venues": venues,
            "generation": 0,
            "fencing_epoch": 0,
            "as_of_monotonic_ns": 0,
            "identity_binding_sha256": "",
            "durable": False,
            "trading_blocked": True,
            "evidence_complete": False,
            "evidence_errors": [error_code],
            "error_code": error_code,
        }

    def _get_callback_account_risk_snapshot(self):
        """Read the Store's atomic callback state, without inspecting SDK summary.

        Returns ``None`` only for a legacy Store that has not implemented the
        combined local-state API.  Any malformed or failed combined read is
        itself a fail-closed result, so callers must not fall back to a possibly
        blocking ``get_execution_summary`` read.
        """

        method = getattr(self.store, "get_callback_account_risk_state", None)
        if not callable(method):
            return None
        try:
            callback_state = method()
        except Exception as exc:
            _safe_log("warning", "btapibroker:callback account-risk state read failed")
            self._sanitize_exception(exc)
            return self._account_risk_snapshot_unavailable(
                "account_risk_callback_state_read_failed"
            )
        if not isinstance(callback_state, Mapping):
            return self._account_risk_snapshot_unavailable("account_risk_callback_state_invalid")

        snapshot = callback_state.get("snapshot")
        if not isinstance(snapshot, Mapping):
            return self._account_risk_snapshot_unavailable("account_risk_callback_snapshot_invalid")
        safe_snapshot = deepcopy(self._redact_runtime_value(dict(snapshot)))
        refresh_state = callback_state.get("refresh_state")
        entry_allowed = callback_state.get("entry_allowed")
        if type(entry_allowed) is not bool:
            return self._account_risk_snapshot_incomplete(
                safe_snapshot, "account_risk_callback_state_invalid"
            )
        if refresh_state == "current":
            if (
                entry_allowed is False
                and safe_snapshot.get("evidence_complete") is True
                and safe_snapshot.get("trading_blocked") is False
            ):
                return self._account_risk_snapshot_incomplete(
                    safe_snapshot, "account_risk_callback_entry_not_allowed"
                )
            return safe_snapshot

        state_errors = {
            "refresh_pending": "account_risk_refresh_in_progress",
            "refresh_rejected": "account_risk_refresh_queue_rejected",
            "refresh_failed": "account_risk_refresh_queue_failed",
            "refresh_unavailable": "account_risk_refresh_unavailable",
        }
        error_code = state_errors.get(refresh_state, "account_risk_callback_state_invalid")
        return self._account_risk_snapshot_incomplete(safe_snapshot, error_code)

    def get_account_risk_snapshot(self):
        """Return durable SDK account-loss evidence without local synthesis."""
        use_callback_cache = self._uses_async_commands() and bool(
            getattr(self.store, "_started", False)
        )
        if use_callback_cache:
            combined_snapshot = self._get_callback_account_risk_snapshot()
            if combined_snapshot is not None:
                return combined_snapshot
        method_name = (
            "get_cached_account_risk_snapshot"
            if use_callback_cache
            else "get_account_risk_snapshot"
        )
        method = getattr(self.store, method_name, None)
        if callable(method):
            try:
                snapshot = method()
            except Exception as exc:
                _safe_log("warning", "btapibroker:2424 fallback on Exception")
                self._sanitize_exception(exc)
                snapshot = None
            if isinstance(snapshot, dict):
                safe_snapshot = deepcopy(self._redact_runtime_value(snapshot))
                if not use_callback_cache:
                    return safe_snapshot

                summary_method = getattr(self.store, "get_execution_summary", None)
                if not callable(summary_method):
                    return self._account_risk_snapshot_incomplete(
                        safe_snapshot, "execution_summary_unavailable"
                    )
                try:
                    summary = self._redact_runtime_value(summary_method())
                except Exception as exc:
                    _safe_log("warning", "btapibroker:2473 fallback on Exception")
                    self._sanitize_exception(exc)
                    return self._account_risk_snapshot_incomplete(
                        safe_snapshot, "execution_summary_read_failed"
                    )
                if not isinstance(summary, Mapping):
                    return self._account_risk_snapshot_incomplete(
                        safe_snapshot, "execution_summary_invalid"
                    )

                refresh_marker = "account_risk_refresh_in_progress"
                refresh_pending = summary.get(refresh_marker) is True
                if "evidence_errors" not in summary:
                    return self._account_risk_snapshot_incomplete(
                        safe_snapshot,
                        refresh_marker if refresh_pending else "execution_summary_invalid",
                    )

                error_values = summary["evidence_errors"]
                if isinstance(error_values, Mapping):
                    has_refresh_marker = refresh_pending or refresh_marker in error_values or any(
                        value == refresh_marker for value in error_values.values()
                    )
                elif isinstance(error_values, str):
                    has_refresh_marker = refresh_pending or error_values == refresh_marker
                elif isinstance(error_values, (list, tuple, set, frozenset)):
                    if any(not isinstance(value, str) for value in error_values):
                        return self._account_risk_snapshot_incomplete(
                            safe_snapshot, "execution_summary_invalid"
                        )
                    has_refresh_marker = refresh_pending or refresh_marker in error_values
                else:
                    return self._account_risk_snapshot_incomplete(
                        safe_snapshot, "execution_summary_invalid"
                    )

                if has_refresh_marker:
                    return self._account_risk_snapshot_incomplete(
                        safe_snapshot, refresh_marker
                    )
                return safe_snapshot

        return self._account_risk_snapshot_unavailable()

    def get_order_reconciliation_state(self, order_or_ref):
        """Return the public unknown/cancel convergence state for one local order."""
        order = order_or_ref
        if not hasattr(order_or_ref, "info"):
            order = self.orders.get(order_or_ref)
        if order is None:
            return None
        return deepcopy(
            self._redact_runtime_value(
                {
                    "bt_order_ref": getattr(order, "ref", None),
                    "exchange_name": self._order_info_get(order, "exchange_name"),
                    "client_order_id": self._order_info_get(order, "client_order_id"),
                    "execution_unknown": bool(
                        self._order_info_get(order, "execution_unknown", False)
                    ),
                    "cancel_execution_unknown": bool(
                        self._order_info_get(order, "cancel_execution_unknown", False)
                    ),
                    "cancel_intent_active": bool(
                        self._order_info_get(order, "cancel_intent_active", False)
                    ),
                    "reconcile_requested": bool(
                        self._order_info_get(order, "reconcile_requested", False)
                    ),
                    "reconcile_attempts": int(
                        self._order_info_get(order, "reconcile_attempts", 0) or 0
                    ),
                    "reconcile_exhausted": bool(
                        self._order_info_get(order, "reconcile_exhausted", False)
                    ),
                    "cancel_retry_attempts": int(
                        self._order_info_get(order, "cancel_retry_attempts", 0) or 0
                    ),
                    "cancel_retry_exhausted": bool(
                        self._order_info_get(order, "cancel_retry_exhausted", False)
                    ),
                }
            )
        )

    def get_logging_health(self):
        """Return broker log-sink failure counters."""
        return dict(_LOGGING_HEALTH)

    def get_approval_lease_status(self):
        """Return non-secret counters for the signed demo execution lease."""
        with self._approval_lock:
            operation_count = self._approval_operation_count
        return {
            "enabled": self._approval_expires_at_utc is not None,
            "expires_at_utc": self.p.approval_expires_at_utc,
            "maximum_order_count": self._approval_max_order_count,
            "operation_count": operation_count,
        }

    def get_strategy_allocation(self, strategy_id: str):
        """Return a local managed risk snapshot for advisory strategy sizing.

        This read never refreshes cash, positions, or provider balances.
        ``getcash`` and ``getvalue`` retain their account-level semantics.
        """

        reader = getattr(self.store, "get_strategy_allocation", None)
        if not callable(reader):
            raise ValueError("managed strategy allocation reader is unavailable")
        return reader(strategy_id)

    def get_strategy_account_book_view(self, *, strategy_ref: str, account_ref: str):
        """Return a service-authorized, explicitly bound strategy book view.

        The ordinary Broker getters remain account-level. A caller that needs
        strategy attribution must name both identities, and the active
        service query route must grant that exact strategy/account pair.
        """

        session = self._service_execution_session
        if session is None:
            raise ValueError("strategy account-book view requires an active service session")
        return session.strategy_account_book_view(
            strategy_ref=strategy_ref,
            account_ref=account_ref,
        )

    def bind_strategy_account_book(
        self,
        strategy,
        *,
        strategy_ref: str,
        account_ref: str,
    ):
        """Attach one configured read-only book view to its actual Strategy.

        The Strategy must supply matching ``strategy_ref`` and ``account_ref``
        parameters and must already use this Broker. This operation does not
        change order routing or the account-level Broker getters.
        """

        session = self._service_execution_session
        if session is None:
            raise ValueError("strategy account-book binding requires an active service session")
        return session.bind_strategy_account_book(
            strategy,
            strategy_ref=strategy_ref,
            account_ref=account_ref,
        )

    def bind_strategy_execution_group(self, strategy):
        """Bind this real Strategy to an explicitly configured group route."""

        session = self._service_execution_session
        if session is None or self.store is None:
            raise ValueError("strategy group binding requires an active service session")
        return self.store.bind_strategy_execution_group(strategy, self)

    def submit_group_order(self, strategy, intent):
        """Submit one typed group intent without degrading it to ordinary orders."""

        session = self._service_execution_session
        if session is None or self.store is None:
            raise ValueError("group submission requires an active service session")
        return self.store.submit_group_order(strategy, self, intent)

    def query_group_order(self, strategy, group_id):
        """Read the coordinator snapshot for one existing group ID."""

        session = self._service_execution_session
        if session is None or self.store is None:
            raise ValueError("group query requires an active service session")
        return self.store.query_group_order(strategy, self, group_id)

    def submit_group_roll_exit(
        self, strategy, group_id, source_leg_id, limit_price
    ):
        """Request a source-bound group CLOSE through the coordinator."""

        session = self._service_execution_session
        if session is None or self.store is None:
            raise ValueError("group roll-exit requires an active service session")
        return self.store.submit_group_roll_exit(
            strategy, self, group_id, source_leg_id, limit_price
        )

    def query_group_roll_exit(self, strategy, action_id):
        """Read a roll-exit status projection without creating or submitting work."""

        session = self._service_execution_session
        if session is None or self.store is None:
            raise ValueError("group roll-exit query requires an active service session")
        return self.store.query_group_roll_exit(strategy, self, action_id)

    def recover_group_order(self, strategy, group_id, cursor=None, *, limit=32):
        """Query the original group ID and continue the durable Monitor cursor."""

        session = self._service_execution_session
        if session is None or self.store is None:
            raise ValueError("group recovery requires an active service session")
        return self.store.recover_group_order(
            strategy, self, group_id, cursor, limit=limit
        )

    def read_group_residuals(self, strategy, cursor=None, *, limit=32):
        """Read a repeatable residual page without mutating Monitor delivery state."""

        session = self._service_execution_session
        if session is None or self.store is None:
            raise ValueError("group residual read requires an active service session")
        return self.store.read_group_residuals(
            strategy, self, cursor, limit=limit
        )

    def getcash(self) -> float:
        """Return current available cash."""
        if not self._uses_async_commands():
            self._refresh_account(force=bool(self.p.force_refresh_queries), raise_errors=True)
        return self._cash

    def getvalue(self, datas=None) -> float:
        """Return current portfolio value."""
        if not self._uses_async_commands():
            self._refresh_account(force=bool(self.p.force_refresh_queries), raise_errors=True)
        return self._value

    def getposition(self, data, clone=True, side=None):
        """Return the cached position for a given data feed."""
        if not self._uses_async_commands():
            self._sync_positions(force=bool(self.p.force_refresh_queries), raise_errors=True)
        if side is not None:
            if not self._is_dual_side_mode():
                raise ValueError("side-specific getposition() is only available in dual_side mode")
            position = self._get_leg_position(data, side)
        else:
            key = self._position_key(data)
            position = (
                self._sync_net_position(data) if self._is_dual_side_mode() else self.positions[key]
            )
        return position.clone() if clone else position

    def execution_position_snapshot(self, data):
        """Return the Broker's cached position without a provider refresh."""

        from ..stores.factor_execution import execution_position_snapshot

        return execution_position_snapshot(self, data)

    def execution_order_snapshot(self):
        """Return alive local orders without querying the Store or provider."""

        from ..stores.factor_execution import execution_order_snapshot

        return execution_order_snapshot(self)

    def get_cached_report_state(self):
        """Return the already-synchronized local account state without I/O.

        ``getcash``, ``getvalue``, and ``getposition`` may intentionally
        refresh their provider-side values.  Runtime observers use this method
        so a status snapshot cannot introduce an extra account request.
        """
        positions = dict(self.positions)
        position_legs = {}
        if self._is_dual_side_mode():
            for key in set(self.long_positions) | set(self.short_positions):
                positions[key] = self._sync_net_position(key)
                position_legs[key] = {
                    "long": self.long_positions.get(key),
                    "short": self.short_positions.get(key),
                }
        return {
            "cash": self._cash,
            "value": self._value,
            "positions": positions,
            "position_legs": position_legs,
        }

    def submit(self, order):
        """Submit an order through the store."""
        factor_scope = None
        if (
            self.store is not None
            and getattr(self.store, "registered_sim_route_id", None) == "simnow-registered-v1"
            and getattr(self.store, "allow_writes", False) is True
        ):
            coordinator = getattr(self, "factor_execution_coordinator", None)
            if coordinator is None or getattr(coordinator, "broker", None) is not self:
                return self._reject_order(
                    order,
                    "factor_execution_coordinator_required",
                    "Registered-sim writes require a durable Strategy decision scope.",
                )
            try:
                factor_scope = coordinator.active_scope_for_order(order)
            except Exception as exc:
                code = getattr(exc, "code", "order_outside_durable_decision_scope")
                return self._reject_order(
                    order,
                    code,
                    "Registered-sim writes require a matching durable Strategy decision scope.",
                )
        session = self._service_execution_session
        route_error = (
            session.strategy_order_route_error(order)
            if session is not None
            else None
        )
        if route_error is not None:
            return self._reject_order(
                order,
                route_error,
                "This Strategy does not match the active execution writer scope.",
            )
        if getattr(self, "_managed_provider_projection_failed", False):
            return self._reject_order(
                order,
                "managed_provider_projection_session_fenced",
                "Managed provider fill projection is uncertain; this Broker session is fenced.",
            )
        if self._is_market_data_only():
            self._record_market_data_only_rejection("submit")
            return self._reject_order(
                order,
                "market_data_only",
                "Order routing is disabled for this observation-only broker session",
            )
        if (
            bool(getattr(self.store, "_sdk_mode", False))
            and not self._startup_ready
            and not self._is_risk_reducing_order(order)
        ):
            return self._reject_order(
                order,
                "startup_preflight_incomplete",
                "SDK opening orders remain locked until startup evidence is complete",
            )
        try:
            # Option input and capability gates run before all optional local
            # validation and placement helpers.  This preserves raw CTP
            # evidence and prevents validation_enabled/cash settings from
            # turning an unsupported seller or malformed option into a write.
            option_input_error = self._validate_option_order_inputs(order)
            if option_input_error is not None:
                code, message = option_input_error
                return self._reject_order(order, code, message)
            seller_capability_error = self._validate_option_seller_capability(order)
            if seller_capability_error is not None:
                code, message = seller_capability_error
                return self._reject_order(order, code, message)
            option_fee_error = self._validate_option_order_fee(order)
            if option_fee_error is not None:
                code, message = option_fee_error
                return self._reject_order(order, code, message)
            self._freeze_position_mode("first order submission")
            safety_error = self._placement_safety_error(order)
            if safety_error is not None:
                code, message = safety_error
                return self._reject_order(order, code, message)
            audit_error = self._position_audit_order_error(order)
            if audit_error is not None:
                code, message = audit_error
                return self._reject_order(order, code, message)
            offset_error = self._ensure_required_net_offset(order)
            if offset_error is not None:
                code, message = offset_error
                return self._reject_order(order, code, message)
            validation_error = self._validate_order(order)
            if validation_error is not None:
                code, message = validation_error
                return self._reject_order(order, code, message)
        except Exception as exc:
            _safe_log("warning", "btapibroker:2614 fallback on Exception")
            return self._reject_order(
                order,
                "pre_trade_state_refresh_failed",
                f"Pre-trade account/position refresh failed: {exc}",
            )

        risk_reducing = self._is_risk_reducing_order(order)
        if not self._trading_enabled and not risk_reducing:
            return self._reject_order(
                order,
                "trading_disabled",
                "Trading is currently disabled for this broker session",
            )

        if self._strategy_paused and not risk_reducing:
            return self._reject_order(
                order,
                "strategy_paused",
                "Strategy order routing is currently paused",
            )

        approval_error = self._consume_approval_operation(
            order,
            risk_reducing=risk_reducing,
            operation="submit",
        )
        if approval_error is not None:
            code, message = approval_error
            return self._reject_order(order, code, message)

        if (
            self._execution_recovery is not None
            and self._order_info_get(order, "execution_role") == "recovery_exit"
        ):
            # The recovery token authorizes one exact action.  Any rejected,
            # timed-out, or ambiguous remote attempt requires a fresh SDK plan.
            self._execution_recovery_close_attempted = True

        factor_attempt = None
        factor_dispatch_completed = False
        try:
            order.submit(self)
            order.addcomminfo(self.getcommissioninfo(order.data))
            self._freeze_order_execution_contract(order, replace=True)
            if self.store is None:
                raise ValueError("BtApiBroker requires a BtApiStore instance")
            if factor_scope is not None:
                from ..stores.factor_execution import FactorExecutionError

                try:
                    factor_attempt = factor_scope.begin_order(order, action="SUBMIT")
                except FactorExecutionError as exc:
                    return self._reject_order(
                        order,
                        exc.code,
                        "Order did not match its durable execution decision.",
                    )
                # The CTP insert is synchronous and may enqueue a trade/order
                # callback before Store.submit_order returns. Bind the exact
                # native OrderRef before crossing that boundary so the first
                # callback is correlated to this same ordinary Backtrader Order.
                self.orders[order.ref] = order
                self._remember_client_ref(order, factor_attempt.order_ref, None)
            response = self.store.submit_order(order)
            if factor_attempt is not None:
                factor_dispatch_completed = True
                try:
                    factor_intent = factor_scope.complete_order(
                        order, factor_attempt, response=response
                    )
                except Exception:
                    # The native call already returned. A failed journal write
                    # is uncertain, so preserve this exact local identity and
                    # never fall through to normal acceptance/fill handling.
                    order.accept(self)
                    order.addinfo(
                        execution_unknown=True,
                        factor_dispatch_state="UNKNOWN",
                        error_code="dispatch_result_not_durable",
                        error_msg="Dispatch result could not be recorded durably.",
                    )
                    self.orders[order.ref] = order
                    self.notify(order)
                    return order
                if factor_intent.state != "KNOWN":
                    return self._accept_unknown_submission(
                        order,
                        RuntimeError("registered_sim_dispatch_evidence_unobserved"),
                        "registered_sim_dispatch_evidence_unobserved",
                    )
                # A registered direct-SimNow return proves only that the
                # synchronous native insert was acknowledged. It does not
                # prove that the order is working, filled, or terminal, so
                # keep the ordinary Backtrader order alive until the source
                # order/trade projections report that state.
                order.accept(self)
                order.addinfo(
                    execution_unknown=False,
                    factor_dispatch_state="KNOWN",
                    factor_dispatch_outcome="native_ack",
                )
                self._remember_client_ref(order, factor_attempt.order_ref, response)
                # Preserve the provider-owned connection identity returned by
                # the synchronous CTP insert.  The native order reference is
                # already bound before dispatch; FrontID/SessionID are needed
                # for a later exact active-order join and safe cancel request.
                if isinstance(response, dict):
                    for key in (
                        "front_id",
                        "session_id",
                        "exchange_id",
                        "order_sys_id",
                    ):
                        value = response.get(key)
                        if value not in (None, ""):
                            order.addinfo(**{key: value})
                self.orders[order.ref] = order
                self.notify(order)
                return order
            self._freeze_order_execution_contract(order, replace=True)
            if (
                isinstance(response, dict)
                and response.get("kind") == "service_execution_recovery_restore"
            ):
                self.orders[order.ref] = order
                self._restore_service_execution_order(order, response)
                intent_id = self._order_info_get(order, "managed_intent_id")
                if isinstance(intent_id, str):
                    self._recovery_orders_by_intent[intent_id] = order
                self._defer_service_execution_recovery_snapshot_notification(order)
                return order
            try:
                managed_projection = parse_ctp_managed_execution_projection(
                    response, expected_operation="submit"
                )
            except ManagedExecutionAdapterError:
                # A malformed durable projection does not prove that a queued
                # action failed. Keep the original framework order nonterminal
                # and mark it unknown; never let the Broker accept or fill it.
                order.addinfo(
                    execution_unknown=True,
                    error_code="invalid_managed_execution_projection",
                    error_msg="Managed execution projection is invalid; reconcile the original intent",
                )
                self.orders[order.ref] = order
                self.notify(order)
                return order
            queued_receipt = bool(
                isinstance(response, dict) and response.get("kind") == "command_receipt"
            )
            if queued_receipt and response.get("queued") is not True:
                return self._reject_order(
                    order,
                    str(response.get("error_code") or "command_queue_rejected"),
                    str(response.get("error_msg") or "SDK command queue rejected the order"),
                )
            if (
                managed_projection is not None
                and managed_projection.state is CtpManagedProjectionState.LOCAL_REJECTED
            ):
                return self._reject_order(
                    order,
                    managed_projection.error_code or "managed_ctp_local_rejection",
                    "Managed CTP action was rejected locally before provider acknowledgement.",
                )
            submit_error = self._submit_response_error(response)
            if submit_error is not None:
                error_code, error_msg = submit_error
                self._attach_remote_error_code(order, response)
                return self._reject_order(order, error_code, error_msg)
            managed_replay_error = self._managed_execution_replay_projection_error(response, order)
            if managed_replay_error is not None:
                error_code, error_msg = managed_replay_error
                return self._reject_order(order, error_code, error_msg)
            managed_framework_projection = self._managed_framework_projection_active(response, order)
            managed_projection_pending = bool(
                managed_projection is not None
                and managed_projection.state
                in (CtpManagedProjectionState.PENDING, CtpManagedProjectionState.UNKNOWN)
            )
            if managed_projection_pending:
                order.addinfo(
                    managed_execution_projection_id=managed_projection.durable_projection_id,
                    managed_execution_projection_state=managed_projection.state.value,
                )
            if not queued_receipt and not managed_projection_pending:
                order.accept(self)

            external_order_id = (
                self._remote_external_order_id(response) if isinstance(response, dict) else None
            )

            if external_order_id is not None:
                order.addinfo(external_order_id=external_order_id)
                self._orders_by_external_id[str(external_order_id)] = order
            order_ref = (
                self._remote_client_order_ref(response) if isinstance(response, dict) else None
            )
            if order_ref not in (None, ""):
                order.addinfo(ctp_order_ref=order_ref)
                self._remember_client_ref(order, order_ref, response)
            if isinstance(response, dict):
                for key in ("front_id", "session_id", "exchange_id"):
                    if key in response and response[key] not in (None, ""):
                        order.addinfo(**{key: response[key]})
                if response.get("execution_unknown") is True:
                    order.addinfo(execution_unknown=True)

            self.orders[order.ref] = order
            if (
                isinstance(response, dict)
                and response.get("service_execution_recovery_required") is True
            ):
                self._bind_live_recovery_order(order)
                # The submit reply is acceptance-only. A later durable
                # event-page receipt is the only authority for a fill.
                self.notify(order, recovery_restore_only=True)
                return order
            self.notify(order)
            if not queued_receipt and not managed_projection_pending:
                self._apply_submit_response_fill(order, response)
                if managed_framework_projection:
                    try:
                        self.store.complete_managed_framework_projection(response, order)
                    except Exception as exc:
                        self._sanitize_exception(exc)
                        self.store.fail_managed_framework_projection(
                            response, "post_submit_apply_receipt_failure"
                        )
                        self._managed_provider_projection_failed = True
                        self._mark_managed_provider_projection_failure(
                            order, "post_submit_apply_receipt_failure"
                        )
                        return order
            if risk_reducing and self._requires_explicit_offset(order.data):
                self._begin_ctp_reconciliation("risk_reducing_order_submitted")
            return order
        except TimeoutError as exc:
            if factor_attempt is not None and not factor_dispatch_completed:
                factor_dispatch_completed = True
                try:
                    factor_intent = factor_scope.complete_order(order, factor_attempt, error=exc)
                except Exception:
                    _safe_log("warning", "btapibroker:factor dispatch journal write failed")
                    factor_intent = None
            self._sanitize_exception(exc)
            if factor_attempt is not None:
                return self._accept_unknown_submission(
                    order,
                    exc,
                    self._safe_exception_code(exc, "registered_sim_execution_unknown"),
                )
            # A timeout cannot prove that the venue rejected the order. Keep
            # its identity alive for read-only reconciliation; never resubmit.
            return self._accept_unknown_submission(order, exc, "submit_timeout")
        except Exception as exc:
            if factor_attempt is not None and not factor_dispatch_completed:
                factor_dispatch_completed = True
                try:
                    factor_intent = factor_scope.complete_order(order, factor_attempt, error=exc)
                except Exception:
                    _safe_log("warning", "btapibroker:factor dispatch journal write failed")
                    factor_intent = None
            _safe_log("error", "btapibroker:2710 exception before re-raise (Exception)")
            self._sanitize_exception(exc)
            if factor_attempt is not None:
                if factor_intent is not None and factor_intent.state == "KNOWN":
                    order.accept(self)
                    order.addinfo(
                        execution_unknown=False,
                        factor_dispatch_state="KNOWN",
                        factor_dispatch_outcome=factor_intent.outcome_code,
                    )
                    self._remember_client_ref(order, factor_attempt.order_ref, None)
                    self.orders[order.ref] = order
                    self.notify(order)
                    return order
                return self._accept_unknown_submission(
                    order,
                    exc,
                    self._safe_exception_code(exc, "registered_sim_execution_unknown"),
                )
            if bool(getattr(exc, "managed_local_reject", False)):
                code = self._safe_exception_code(exc, "managed_ctp_local_rejection")
                return self._reject_order(
                    order,
                    code,
                    "Managed CTP action was rejected locally before SDK dispatch.",
                )
            if bool(getattr(exc, "managed_projection_pending", False)):
                return self._preserve_managed_submit_pending(order, exc)
            if bool(getattr(exc, "execution_unknown", False)) or (
                bool(getattr(self.store, "_sdk_mode", False))
                and not bool(getattr(exc, "definite_reject", False))
            ):
                return self._accept_unknown_submission(
                    order,
                    exc,
                    self._safe_exception_code(exc, "remote_execution_unknown"),
                )
            if bool(getattr(exc, "definite_reject", False)):
                remote_code = self._safe_exception_code(exc, "remote_submit_rejected")
                order.addinfo(remote_error_code=remote_code)
                return self._reject_order(
                    order,
                    "remote_submit_rejected",
                    f"Remote submission was definitely rejected ({remote_code})",
                )
            error_msg = (
                "Remote submission failed before its outcome could be classified"
                if bool(getattr(self.store, "_sdk_mode", False))
                else str(self._redact_runtime_value(exc))
            )
            order.addinfo(error_code="remote_submit_failed", error_msg=error_msg)
            order.reject(self)
            self.orders[order.ref] = order
            self.notify(order)
            raise

    def refresh_managed_orders(self, *, limit: int = 32):
        """Apply current durable service records to live managed orders.

        The caller owns the schedule; this method performs one bounded pass and
        returns the framework order refs whose state was applied.  ``limit``
        bounds every adapter refresh attempt, including missing, replayed, or
        unchanged projections.  Live managed orders rotate fairly between
        passes so an unchanged early order cannot consume an unbounded pass or
        starve later orders.  Each application goes through the ordinary update
        path, and an unchanged durable revision is skipped so the same state is
        never booked twice.  A store or adapter without refresh support raises
        instead of silently doing nothing.
        """

        if type(limit) is not int or limit <= 0:
            raise ValueError("refresh limit must be a positive integer")
        if self.store is None:
            raise ValueError("BtApiBroker requires a BtApiStore instance")
        refresh = getattr(self.store, "refresh_managed_order_projection", None)
        if not callable(refresh):
            raise ValueError("store does not support managed order refresh")

        eligible_orders = []
        eligible_order_ids = set()
        for order in list(self.orders.values()):
            if not order.alive() or not self._order_info_get(order, "managed_intent_id"):
                continue
            order_id = id(order)
            if order_id not in eligible_order_ids:
                eligible_order_ids.add(order_id)
                eligible_orders.append(order)

        # Keep the current round-robin position while pruning orders that were
        # removed, became terminal, or stopped being managed between passes.
        # Identity keys avoid relying on framework-order equality semantics.
        eligible_by_id = {id(order): order for order in eligible_orders}
        queue = collections.deque()
        queued_order_ids = set()
        for order in self._managed_refresh_order_queue:
            order_id = id(order)
            if order_id in eligible_by_id and order_id not in queued_order_ids:
                queue.append(eligible_by_id[order_id])
                queued_order_ids.add(order_id)
        for order in eligible_orders:
            order_id = id(order)
            if order_id not in queued_order_ids:
                queue.append(order)
                queued_order_ids.add(order_id)
        self._managed_refresh_order_queue = queue

        applied = []
        visits_remaining = len(queue)
        attempts = 0
        while visits_remaining and attempts < limit:
            order = queue.popleft()
            queue.append(order)
            visits_remaining -= 1

            # An update earlier in this pass, or another caller, may have made
            # this candidate terminal before its turn arrives.
            if not order.alive() or not self._order_info_get(order, "managed_intent_id"):
                continue

            # Rotate before entering Store/adapter code. If refresh raises, the
            # following pass still begins with the next managed order.
            attempts += 1
            try:
                projection = refresh(order)
            except ServiceExecutionReadError as error:
                error.applied_refs = tuple(applied)
                order.addinfo(
                    execution_unknown=True,
                    service_refresh_error_code=error.code,
                    service_read_unavailable=True,
                )
                raise
            if not isinstance(projection, dict):
                continue

            # A successful durable read resolves the read failure even when
            # the service returns the same revision and the projection is
            # otherwise skipped below. A successful UNKNOWN or an unrecognized
            # never-seen record remains a business uncertainty and keeps
            # execution_unknown; a known record that disappeared raises above.
            service_read_unavailable = bool(
                self._order_info_get(order, "service_read_unavailable", False)
            )
            if service_read_unavailable:
                order.addinfo(
                    service_refresh_error_code=None,
                    service_read_unavailable=False,
                )
                has_known_non_unknown_state = (
                    projection.get("service_execution_state") not in (None, "UNKNOWN")
                    and projection.get("execution_unknown") is not True
                )
                if has_known_non_unknown_state:
                    order.addinfo(execution_unknown=False)
            if projection.get("managed_execution_replayed") is True:
                continue
            # A repeat projection of the same durable revision must not be
            # applied again: applying it would notify the strategy a second
            # time for a state it already saw.
            fingerprint = (
                projection.get("service_execution_state"),
                projection.get("service_record_revision"),
                projection.get("status"),
                projection.get("execution_unknown"),
                projection.get("filled"),
                projection.get("price"),
                projection.get("avg_price"),
            )
            if self._order_info_get(order, "service_refresh_applied") == fingerprint:
                continue
            update = dict(projection)
            update.setdefault("bt_order_ref", getattr(order, "ref", None))
            update.setdefault("data_name", self._position_key(order.data))
            update.setdefault("side", "buy" if order.isbuy() else "sell")
            self._apply_order_update(update)
            order.addinfo(service_refresh_applied=fingerprint)
            applied.append(getattr(order, "ref", None))
        return tuple(applied)

    def cancel(self, order):
        """Cancel an existing order through the store."""
        if order is None:
            return None

        factor_scope = None
        if (
            self.store is not None
            and getattr(self.store, "registered_sim_route_id", None) == "simnow-registered-v1"
            and getattr(self.store, "allow_writes", False) is True
        ):
            coordinator = getattr(self, "factor_execution_coordinator", None)
            if coordinator is None or getattr(coordinator, "broker", None) is not self:
                order.addinfo(
                    cancel_requested_remote=False,
                    cancel_rejected_local=True,
                    error_code="factor_execution_coordinator_required",
                    error_msg="Registered-sim writes require a durable Strategy decision scope.",
                )
                self.notify(order)
                return order
            try:
                factor_scope = coordinator.active_scope_for_order(order)
            except Exception as exc:
                order.addinfo(
                    cancel_requested_remote=False,
                    cancel_rejected_local=True,
                    error_code=getattr(exc, "code", "order_outside_durable_decision_scope"),
                    error_msg="Registered-sim writes require a matching durable Strategy scope.",
                )
                self.notify(order)
                return order

        session = self._service_execution_session
        route_error = (
            session.strategy_order_route_error(order)
            if session is not None
            else None
        )
        if route_error is not None:
            order.addinfo(
                cancel_requested_remote=False,
                cancel_rejected_local=True,
                error_code=route_error,
                error_msg="This Strategy does not match the active execution writer scope.",
            )
            self.notify(order)
            self._emit_runtime_event(
                "order_cancel_rejected_local",
                level="ERROR",
                order_ref=getattr(order, "ref", None),
                error_code=route_error,
                error_msg="This Strategy does not match the active execution writer scope.",
                status="rejected",
                details={"data_name": self._position_key(order.data)},
            )
            return order

        if getattr(self, "_managed_provider_projection_failed", False):
            order.addinfo(
                cancel_requested_remote=False,
                cancel_rejected_local=True,
                error_code="managed_provider_projection_session_fenced",
                error_msg="Managed provider fill projection is uncertain; this Broker session is fenced.",
            )
            self.notify(order)
            return order

        if not order.alive():
            return order

        if self._is_market_data_only():
            self._record_market_data_only_rejection("cancel")
            order.addinfo(
                cancel_requested_remote=False,
                cancel_rejected_local=True,
                error_code="market_data_only",
                error_msg="Order cancellation is disabled for this observation-only broker session",
            )
            self.notify(order)
            self._emit_runtime_event(
                "order_cancel_rejected_local",
                level="ERROR",
                order_ref=getattr(order, "ref", None),
                error_code="market_data_only",
                error_msg="Order cancellation is disabled for this observation-only broker session",
                status="rejected",
                details={"data_name": self._position_key(order.data)},
            )
            return order

        if (
            self._execution_recovery is not None
            and self._order_info_get(order, "execution_role") == "recovery_exit"
        ):
            self._abort_recovery_dispatch(order, "execution_recovery_cancel_requires_refresh")
            order.addinfo(
                execution_unknown=True,
                recovery_refresh_required=True,
                cancel_requested_remote=False,
            )
            self.notify(order)
            return order

        if bool(self._order_info_get(order, "cancel_requested_remote", False)) or bool(
            self._order_info_get(order, "managed_execution_cancel_pending", False)
        ):
            return order

        if self.store is None:
            raise ValueError("BtApiBroker requires a BtApiStore instance")

        self._ensure_cancel_deadline(order)
        if self._uses_async_commands():
            attempts = int(self._order_info_get(order, "cancel_retry_attempts", 0) or 0)
            maximum = max(int(self.p.cancel_retry_max_attempts or 0), 1)
            if attempts >= maximum:
                order.addinfo(
                    cancel_retry_exhausted=True,
                    cancel_intent_active=True,
                    execution_unknown=True,
                )
                self.notify(order)
                return order
            order.addinfo(
                cancel_retry_attempts=attempts + 1,
                cancel_retry_max_attempts=maximum,
                cancel_retry_exhausted=False,
                cancel_reconcile_confirmed_live=False,
                cancel_retry_due_monotonic_ns=None,
            )
        self._consume_approval_operation(
            order,
            risk_reducing=True,
            operation="cancel",
        )
        factor_attempt = None
        factor_dispatch_completed = False
        try:
            if factor_scope is not None:
                from ..stores.factor_execution import FactorExecutionError

                try:
                    factor_attempt = factor_scope.begin_order(order, action="CANCEL")
                except FactorExecutionError as exc:
                    order.addinfo(
                        cancel_requested_remote=False,
                        cancel_rejected_local=True,
                        error_code=exc.code,
                        error_msg="Cancellation did not match its durable execution decision.",
                    )
                    self.notify(order)
                    return order
            response = self.store.cancel_order(order)
            if factor_attempt is not None:
                factor_dispatch_completed = True
                try:
                    factor_intent = factor_scope.complete_order(
                        order, factor_attempt, response=response
                    )
                except Exception:
                    order.addinfo(
                        cancel_requested_remote=True,
                        cancel_execution_unknown=True,
                        cancel_intent_active=True,
                        execution_unknown=True,
                        factor_dispatch_state="UNKNOWN",
                        cancel_error_code="dispatch_result_not_durable",
                    )
                    self.orders[order.ref] = order
                    self.notify(order)
                    return order
                if factor_intent.state != "KNOWN":
                    order.addinfo(
                        cancel_requested_remote=True,
                        cancel_execution_unknown=True,
                        cancel_intent_active=True,
                        execution_unknown=True,
                    )
                    self.orders[order.ref] = order
                    self.notify(order)
                    return order
                # Native cancel success is an acknowledgement only. Keep the
                # original order alive and mapped until an authoritative
                # terminal order observation arrives.
                order.addinfo(
                    cancel_requested_remote=True,
                    cancel_execution_unknown=False,
                    cancel_intent_active=True,
                    cancel_acknowledged=True,
                    factor_cancel_dispatch_state="KNOWN",
                    factor_cancel_intent_id=factor_intent.intent_id,
                    execution_unknown=False,
                )
                self.orders[order.ref] = order
                self.notify(order)
                return order
        except Exception as exc:
            if factor_attempt is not None and not factor_dispatch_completed:
                factor_dispatch_completed = True
                try:
                    factor_scope.complete_order(order, factor_attempt, error=exc)
                except Exception:
                    _safe_log("warning", "btapibroker:factor cancel journal write failed")
            _safe_log("warning", "btapibroker:2813 fallback on Exception")
            self._sanitize_exception(exc)
            if bool(getattr(exc, "managed_local_reject", False)):
                order.addinfo(
                    cancel_requested_remote=False,
                    cancel_execution_unknown=False,
                    cancel_intent_active=False,
                    managed_execution_cancel_state="LOCAL_REJECTED",
                    managed_execution_cancel_pending=False,
                    managed_execution_cancel_reconciliation_required=False,
                    managed_execution_cancel_freeze_required=False,
                    cancel_error_code=self._safe_exception_code(
                        exc, "managed_ctp_local_rejection"
                    ),
                    cancel_error_msg="Managed CTP cancellation was rejected before SDK dispatch.",
                )
                self.orders[order.ref] = order
                self.notify(order)
                return order
            if bool(getattr(exc, "managed_projection_pending", False)):
                state = str(
                    getattr(exc, "managed_execution_state", None)
                    or ("UNKNOWN" if getattr(exc, "execution_unknown", False) else "PENDING")
                ).upper()
                if state not in ("PENDING", "UNKNOWN"):
                    state = "UNKNOWN"
                unknown = state == "UNKNOWN"
                order.addinfo(
                    cancel_requested_remote=unknown,
                    cancel_execution_unknown=unknown,
                    cancel_intent_active=True,
                    managed_execution_cancel_state=state,
                    managed_execution_cancel_pending=True,
                    managed_execution_cancel_reconciliation_required=True,
                    managed_execution_cancel_freeze_required=unknown,
                    cancel_error_code=self._safe_exception_code(
                        exc, "managed_ctp_cancel_handoff_unresolved"
                    ),
                    cancel_error_msg="Managed CTP cancellation handoff is unresolved.",
                )
                if unknown:
                    order.addinfo(execution_unknown=True)
                self.orders[order.ref] = order
                self.notify(order)
                return order
            if not bool(getattr(exc, "execution_unknown", False)) and not isinstance(
                exc, TimeoutError
            ):
                raise
            # The cancel command may have reached the venue. Keep the original
            # order live and mapped, and never issue a blind second cancel.
            order.addinfo(
                cancel_requested_remote=True,
                cancel_execution_unknown=True,
                cancel_intent_active=True,
                cancel_error_code=self._safe_exception_code(exc, "cancel_execution_unknown"),
                cancel_error_msg="Remote cancellation outcome is unknown",
            )
            self.orders[order.ref] = order
            self.notify(order)
            if self._uses_async_commands():
                self._request_order_reconcile(order)
            return order

        if (
            isinstance(response, dict)
            and response.get("local_cancelled_before_send") is True
            and response.get("remote_write_attempted") is False
        ):
            # The Store atomically removed this exact opening from its unsent
            # queue and publishes the original submit's local terminal update.
            # Do not enqueue a remote cancel or reconcile a nonexistent order.
            order.addinfo(
                cancel_requested_remote=False,
                cancel_intent_active=False,
                cancel_deadline_monotonic_ns=None,
                cancel_deadline_unknown_marked=False,
                cancel_retry_due_monotonic_ns=None,
                cancel_retry_exhausted=False,
                local_cancelled_before_send=True,
            )
            self.notify(order)
            return order

        if (
            isinstance(response, dict)
            and response.get("kind") == "command_receipt"
            and response.get("queued") is not True
        ):
            order.addinfo(
                cancel_requested_remote=False,
                cancel_intent_active=True,
                cancel_deadline_monotonic_ns=None,
                cancel_deadline_unknown_marked=False,
                cancel_error_code=str(
                    self._redact_runtime_value(
                        response.get("error_code") or "command_queue_rejected"
                    )
                ),
                cancel_error_msg=str(
                    self._redact_runtime_value(
                        response.get("error_msg") or "SDK command queue rejected cancellation"
                    )
                ),
            )
            self._schedule_cancel_retry(order, "cancel_enqueue_rejected")
            self._request_order_reconcile(order)
            self.notify(order)
            return order

        if self._preserve_managed_cancel_pending(order, response):
            return order

        if (
            factor_attempt is not None
            or bool(self.p.cancel_wait_remote)
            or bool(getattr(self.store, "_sdk_mode", False))
        ):
            order.addinfo(
                cancel_requested_remote=True,
                cancel_execution_unknown=False,
                cancel_intent_active=True,
            )
            if self._is_confirmed_terminal_order_response(response):
                update = dict(response)
                update.setdefault("kind", "order")
                update.setdefault("bt_order_ref", getattr(order, "ref", None))
                update.setdefault("data_name", self._position_key(order.data))
                update.setdefault("side", "buy" if order.isbuy() else "sell")
                self._apply_order_update(update)
            return order

        order.cancel()
        self._clear_order_mappings(order)
        self.notify(order)
        return order

    def _preserve_managed_submit_pending(self, order, exc):
        """Keep an unresolved managed handoff submitted without implying ACK."""

        self._abort_recovery_dispatch(order, "managed_execution_handoff_unresolved")
        state = str(
            getattr(exc, "managed_execution_state", None)
            or ("UNKNOWN" if getattr(exc, "execution_unknown", False) else "PENDING")
        ).upper()
        if state not in ("PENDING", "UNKNOWN"):
            state = "UNKNOWN"
        error_code = self._safe_exception_code(exc, "managed_ctp_handoff_unresolved")
        order.addinfo(
            managed_execution_projection_state=state,
            execution_unknown=state == "UNKNOWN",
            error_code=error_code,
            error_msg="Managed execution handoff is unresolved; reconcile the original intent.",
        )
        self.orders[order.ref] = order
        self.notify(order)
        return order

    def _preserve_managed_cancel_pending(self, order, response):
        """Keep a managed cancellation live until a terminal cancel is proven.

        Legacy direct Store paths historically cancel locally as soon as their
        synchronous call returns.  A managed cancellation ``ACKED`` record only
        proves dispatch, while ``UNKNOWN`` and rejected records prove even less.
        The trusted bridge marks these projections explicitly; retain all order
        identifiers so an authoritative late fill or reconciliation update can
        still be matched.  Only the bridge's explicit terminal ``cancelled``
        response reaches the ordinary local-terminal branch below.
        """

        try:
            projection = parse_ctp_managed_execution_projection(
                response, expected_operation="cancel"
            )
        except ManagedExecutionAdapterError:
            order.addinfo(
                cancel_requested_remote=True,
                cancel_execution_unknown=True,
                cancel_intent_active=True,
                execution_unknown=True,
                managed_execution_cancel_state="UNKNOWN",
                managed_execution_cancel_pending=True,
                managed_execution_cancel_reconciliation_required=True,
                managed_execution_cancel_freeze_required=True,
                cancel_error_code="invalid_managed_execution_projection",
            )
            self.orders[order.ref] = order
            self.notify(order)
            return True

        if projection is not None:
            state = projection.state.value
            if state == CtpManagedProjectionState.LOCAL_REJECTED.value:
                order.addinfo(
                    cancel_requested_remote=False,
                    cancel_execution_unknown=False,
                    cancel_intent_active=False,
                    managed_execution_cancel_state=state,
                    managed_execution_cancel_pending=False,
                    managed_execution_cancel_reconciliation_required=False,
                    managed_execution_cancel_freeze_required=False,
                    cancel_error_code=projection.error_code,
                )
                self.orders[order.ref] = order
                self.notify(order)
                return True
            unknown = state == CtpManagedProjectionState.UNKNOWN.value
            order.addinfo(
                cancel_requested_remote=unknown,
                cancel_execution_unknown=unknown,
                cancel_intent_active=True,
                managed_execution_cancel_state=state,
                managed_execution_cancel_pending=True,
                managed_execution_cancel_reconciliation_required=True,
            )
            if unknown:
                order.addinfo(
                    execution_unknown=True,
                    managed_execution_cancel_freeze_required=True,
                )
            self.orders[order.ref] = order
            self.notify(order)
            return True

        if (
            not isinstance(response, dict)
            or response.get("managed_execution_cancel_pending") is not True
        ):
            return False

        state = str(response.get("managed_execution_cancel_state") or "UNKNOWN").strip().upper()
        unknown = state == "UNKNOWN" or response.get("execution_unknown") is True
        order.addinfo(
            cancel_requested_remote=state == "ACKED" or unknown,
            cancel_execution_unknown=unknown,
            cancel_intent_active=True,
            managed_execution_cancel_state=state,
            managed_execution_cancel_pending=True,
            managed_execution_cancel_reconciliation_required=True,
        )
        if unknown:
            order.addinfo(
                execution_unknown=True,
                managed_execution_cancel_freeze_required=True,
            )
        error_code = response.get("error_code")
        if error_code not in (None, ""):
            order.addinfo(cancel_error_code=str(self._redact_runtime_value(error_code)))
        error_msg = response.get("error_msg")
        if error_msg not in (None, ""):
            order.addinfo(cancel_error_msg=str(self._redact_runtime_value(error_msg)))
        self.orders[order.ref] = order
        self.notify(order)
        return True

    def _accept_unknown_submission(self, order, exc, error_code):
        """Keep an ambiguously submitted order alive under its original identity."""
        self._abort_recovery_dispatch(order, "execution_recovery_dispatch_unknown")
        order.accept(self)
        order.addinfo(
            execution_unknown=True,
            error_code=error_code,
            error_msg="Remote submission outcome is unknown; reconcile the original client id",
        )
        remote_code = self._safe_exception_code(exc, None)
        if remote_code:
            order.addinfo(remote_error_code=remote_code)
        self.orders[order.ref] = order
        client_ref = self._order_info_get(order, "client_order_id")
        if client_ref not in (None, ""):
            self._remember_client_ref(order, client_ref)
        if self._requires_explicit_offset(order.data):
            self._begin_ctp_reconciliation("unknown_order_submission")
        self.notify(order)
        return order

    @staticmethod
    def _safe_exception_code(exc, default):
        """Return a bounded identifier without copying a vendor message or URL."""
        value = getattr(exc, "code", None)
        if value in (None, ""):
            return default
        text = str(value).strip()
        if not text or len(text) > 128:
            return default
        if not all(character.isalnum() or character in "._:-" for character in text):
            return default
        return text

    @staticmethod
    def _is_risk_reducing_order(order):
        info = getattr(order, "info", {})
        offset = str(getattr(info, "get", lambda *_: None)("offset") or "open").lower()
        reduce_only = bool(getattr(info, "get", lambda *_: False)("reduce_only"))
        return reduce_only or offset != "open"

    def _managed_execution_order_error(self, order):
        """Bind and validate the identity carried by managed CTP writes."""

        identity_reader = getattr(self.store, "get_strategy_identity_sha256", None)
        strategy_identity = str(identity_reader() if callable(identity_reader) else "")
        recovery = self._execution_recovery
        if not strategy_identity and recovery is None:
            return None
        if re.fullmatch(r"[0-9a-f]{64}", strategy_identity) is None:
            return (
                "strategy_identity_unproven",
                "Managed execution requires the configured strategy identity",
            )
        supplied_identity = str(self._order_info_get(order, "strategy_identity_sha256") or "")
        if supplied_identity and supplied_identity != strategy_identity:
            return (
                "strategy_identity_mismatch",
                "Order strategy identity differs from the managed execution session",
            )
        order.addinfo(strategy_identity_sha256=strategy_identity)

        cycle_id = self._order_info_get(order, "execution_cycle_id")
        role = str(self._order_info_get(order, "execution_role") or "")
        offset = str(self._order_info_get(order, "offset") or "open").lower()
        if (
            not isinstance(cycle_id, str)
            or cycle_id != cycle_id.strip()
            or not cycle_id
            or len(cycle_id) > 128
            or role not in {"entry", "exit", "recovery_exit"}
        ):
            return (
                "execution_identity_incomplete",
                "Managed execution requires an explicit cycle and role",
            )
        if role == "entry" and offset != "open":
            return "execution_role_mismatch", "Entry role requires an opening order"
        if role in {"exit", "recovery_exit"} and offset != "close":
            return "execution_role_mismatch", "Exit role requires a generic CZCE close"

        if recovery is None:
            if role == "recovery_exit":
                return (
                    "execution_recovery_not_active",
                    "Recovery exit requires an SDK-issued recovery plan",
                )
            return None
        if role != "recovery_exit":
            return (
                "execution_recovery_only",
                "This broker session accepts only the SDK-issued recovery close",
            )
        if self._execution_recovery_close_attempted:
            return (
                "execution_recovery_close_consumed",
                "The SDK-issued recovery close was already attempted",
            )

        data_name = self._position_key(order.data).upper().split(".")[-1]
        side = "buy" if order.isbuy() else "sell"
        position_side = str(self._order_info_get(order, "position_side") or "").lower()
        exchange_id = str(self._order_info_get(order, "exchange_id") or "").upper()
        quantity_unit = str(self._order_info_get(order, "quantity_unit") or "").lower()
        requested = abs(float(order.size or 0.0))
        action_matches = False
        if math.isfinite(requested) and requested > 0 and requested.is_integer():
            for action in recovery.get("allowed_closes") or ():
                if not isinstance(action, dict):
                    continue
                try:
                    action_quantity = int(action.get("quantity"))
                except (TypeError, ValueError):
                    _safe_log("debug", "btapibroker:2987 ignored TypeError,ValueError")
                    continue
                action_matches = bool(
                    action.get("execution_cycle_id") == cycle_id
                    and str(action.get("symbol") or "").upper().split(".")[-1] == data_name
                    and str(action.get("exchange_id") or "").upper() == exchange_id
                    and str(action.get("position_side") or "").lower() == position_side
                    and str(action.get("side") or "").lower() == side
                    and str(action.get("offset") or "").lower() == "close"
                    and action_quantity == int(requested)
                    and action.get("quantity") == str(action_quantity)
                    and str(action.get("quantity_unit") or "").lower() == "contracts"
                    and quantity_unit == "contracts"
                )
                if action_matches:
                    break
        if not action_matches:
            return (
                "execution_recovery_action_mismatch",
                "Order differs from the SDK-issued recovery close",
            )
        return None

    @staticmethod
    def _parse_approval_expiry(value):
        """Parse the signed UTC approval expiry without local-time ambiguity."""
        if value is None:
            return None
        if not isinstance(value, str) or not value.endswith("Z"):
            raise ValueError("approval_expires_at_utc must be an RFC3339 UTC timestamp")
        try:
            parsed = _dt.datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError as exc:
            _safe_log("error", "btapibroker:3019 re-raising ValueError")
            raise ValueError("approval_expires_at_utc must be an RFC3339 UTC timestamp") from exc
        if parsed.utcoffset() != _dt.timedelta(0):
            raise ValueError("approval_expires_at_utc must be an RFC3339 UTC timestamp")
        return parsed

    def _consume_approval_operation(self, order, *, risk_reducing, operation):
        """Atomically enforce the opening lease and audit each remote operation."""
        if self._approval_expires_at_utc is None:
            return None
        with self._approval_lock:
            next_count = self._approval_operation_count + 1
            if not risk_reducing:
                if _dt.datetime.now(_dt.timezone.utc) >= self._approval_expires_at_utc:
                    return (
                        "demo_approval_expired",
                        "Demo approval expired before the opening order could be submitted",
                    )
                if next_count > self._approval_max_order_count:
                    return (
                        "demo_approval_order_limit",
                        "Demo approval order-operation limit is exhausted",
                    )
            self._approval_operation_count = next_count
            if hasattr(order, "addinfo"):
                order.addinfo(
                    approval_expires_at_utc=self.p.approval_expires_at_utc,
                    approval_operation_count=next_count,
                    approval_max_order_count=self._approval_max_order_count,
                    approval_risk_reducing=bool(risk_reducing),
                    approval_operation=str(operation),
                )
        return None

    def _placement_safety_error(self, order):
        """Fail closed for new exposure after unknown execution or bad market data."""
        managed_error = self._managed_execution_order_error(order)
        if managed_error is not None:
            return managed_error
        if self._is_risk_reducing_order(order):
            return None
        is_ctp_order = self._requires_explicit_offset(order.data)
        uses_async_commands = self._uses_async_commands()
        if is_ctp_order and self._ctp_reconciliation_required:
            return (
                "ctp_reconciliation_required",
                "New CTP exposure is blocked until two complete reconciliation snapshots agree",
            )
        # The legacy synchronous non-CTP adapters predate Store command/stream
        # health and keep their existing pre-trade audit path.  Native CTP must
        # still pass the stricter gates below even on a synchronous adapter.
        if not is_ctp_order and not uses_async_commands:
            return None
        unknown_orders = [
            candidate
            for candidate in self.orders.values()
            if candidate.alive()
            and (
                bool(self._order_info_get(candidate, "execution_unknown", False))
                or bool(self._order_info_get(candidate, "cancel_execution_unknown", False))
            )
        ]
        if unknown_orders:
            return (
                "unknown_execution_exposure",
                "New exposure is blocked until unknown orders reconcile",
            )
        pending_cancels = [
            candidate
            for candidate in self.orders.values()
            if candidate.alive()
            and bool(self._order_info_get(candidate, "cancel_intent_active", False))
        ]
        if pending_cancels:
            return (
                "cancel_intent_active",
                "New exposure is blocked until the pending cancellation reaches a terminal state",
            )
        if is_ctp_order:
            capability = getattr(self.store, "supports_complete_ctp_queries", None)
            capability_ready = bool(
                callable(capability) and capability(include_reference_data=True)
            )
            if self.p.require_complete_ctp_evidence and not capability_ready:
                return (
                    "ctp_query_capability_unavailable",
                    "New CTP exposure requires the typed startup-query capability",
                )
            if capability_ready:
                getter = getattr(self.store, "get_ctp_query_health", None)
                health = getter() if callable(getter) else {}
                if not isinstance(health, dict) or health.get("evidence_complete") is not True:
                    return (
                        "ctp_query_evidence_incomplete",
                        "New CTP exposure is blocked until typed startup queries complete",
                    )
                if self.p.require_complete_ctp_evidence:
                    if (
                        self._current_ctp_instrument_row(health, self._position_key(order.data))
                        is None
                    ):
                        return (
                            "ctp_instrument_state_unproven",
                            "New CTP exposure requires current tradable-instrument evidence",
                        )
                    unknown_count = health.get("unknown_intent_count")
                    unmatched_count = health.get("unmatched_trade_count")
                    counts_complete = all(
                        isinstance(value, int) and not isinstance(value, bool)
                        for value in (unknown_count, unmatched_count)
                    )
                    if not counts_complete:
                        return (
                            "ctp_execution_summary_incomplete",
                            "New CTP exposure requires complete execution-ledger counts",
                        )
                    if unknown_count != 0 or unmatched_count != 0:
                        return (
                            "ctp_execution_summary_not_clear",
                            "New CTP exposure is blocked by unresolved execution evidence",
                        )
        if not uses_async_commands:
            return None
        health_method = getattr(self.store, "get_command_health", None)
        if callable(health_method):
            health = health_method()
            if health.get("risk_state_latched") or health.get("risk_state_unknown"):
                return (
                    "execution_health_unproven",
                    "New exposure is blocked because execution command evidence was lost",
                )
            if health.get("broker_update_conservation") is not True:
                return (
                    "execution_health_unproven",
                    "New exposure is blocked because execution update conservation is unproven",
                )
        stream_method = getattr(self.store, "get_stream_health", None)
        if callable(stream_method):
            health = stream_method(self._position_key(order.data))
            if health.get("stale"):
                reason = str(health.get("stale_reason") or "market_data_stale")
                return reason, "New exposure is blocked until market data continuity recovers"
        return None

    def next(self):
        """Refresh cached balances and positions."""
        session = self._service_execution_session
        if session is not None:
            session.poll(self)
        self._drain_store_updates()
        service_recovery = self._uses_service_execution_recovery()
        if service_recovery:
            self._process_service_execution_recovery()
        self._process_order_deadlines()
        if self._uses_async_commands():
            if not service_recovery:
                self._schedule_sdk_reconcile()
            return
        self._refresh_account()
        self._sync_positions()
        self._sync_remote_open_orders()
        self._maybe_audit_positions()

    def _ensure_cancel_deadline(self, order):
        """Attach an independent local deadline for remote cancel confirmation."""
        existing = self._order_info_get(order, "cancel_deadline_monotonic_ns")
        if existing not in (None, ""):
            try:
                if int(existing) > 0:
                    return int(existing)
            except (TypeError, ValueError):
                _safe_log("debug", "btapibroker:3182 ignored TypeError,ValueError")

        timeout_ns = self._order_info_get(order, "cancel_confirmation_timeout_ns")
        if timeout_ns in (None, ""):
            timeout_ns = self._order_info_get(order, "cancel_timeout_ns")
        if timeout_ns in (None, ""):
            timeout_seconds = self._order_info_get(order, "cancel_timeout_seconds")
            if timeout_seconds in (None, ""):
                timeout_seconds = self.p.cancel_confirmation_timeout
            try:
                timeout_ns = int(max(float(timeout_seconds), 0.0) * 1_000_000_000)
            except (TypeError, ValueError):
                timeout_ns = 0
        try:
            timeout_ns = max(int(timeout_ns), 0)
        except (TypeError, ValueError):
            timeout_ns = 0
        deadline = time.monotonic_ns() + timeout_ns
        order.addinfo(
            cancel_deadline_monotonic_ns=deadline,
            cancel_confirmation_timeout_ns=timeout_ns,
            cancel_deadline_unknown_marked=False,
        )
        return deadline

    def _execution_deadline(self, order):
        """Read a supported explicit local execution deadline from order info."""
        for key in (
            "execution_deadline_monotonic_ns",
            "order_deadline_monotonic_ns",
            "deadline_monotonic_ns",
        ):
            value = self._order_info_get(order, key)
            if value in (None, ""):
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        return None

    def _process_order_deadlines(self):
        """Advance execution and cancel timeouts independently of market-data bars."""
        now_ns = time.monotonic_ns()
        for order in list(self.orders.values()):
            if not order.alive():
                continue
            if bool(self._order_info_get(order, "service_execution_recovery_managed", False)):
                # Recovery v1 does not authorize local deadline-driven retry
                # or cancel of durable remote intent state.
                continue
            self._retry_due_order_actions(order, now_ns)
            execution_deadline = self._execution_deadline(order)
            cancel_triggered = bool(
                self._order_info_get(order, "execution_deadline_cancel_requested", False)
            )
            if (
                execution_deadline is not None
                and execution_deadline > 0
                and now_ns >= execution_deadline
                and not cancel_triggered
            ):
                order.addinfo(
                    execution_deadline_cancel_requested=True,
                    execution_deadline_triggered_monotonic_ns=now_ns,
                )
                self.cancel(order)

            if not order.alive():
                continue
            cancel_deadline = self._order_info_get(order, "cancel_deadline_monotonic_ns")
            if cancel_deadline in (None, ""):
                continue
            try:
                cancel_deadline = int(cancel_deadline)
            except (TypeError, ValueError):
                _safe_log("debug", "btapibroker:3254 ignored TypeError,ValueError")
                continue
            if now_ns < cancel_deadline:
                continue
            if not bool(self._order_info_get(order, "cancel_requested_remote", False)):
                continue
            if bool(self._order_info_get(order, "cancel_deadline_unknown_marked", False)):
                continue
            order.addinfo(
                execution_unknown=True,
                cancel_execution_unknown=True,
                cancel_intent_active=True,
                cancel_deadline_unknown_marked=True,
                cancel_error_code="cancel_confirmation_timeout",
                cancel_error_msg="Remote cancellation was not confirmed before its deadline",
            )
            self.notify(order)
            self._request_order_reconcile(order)

    def _retry_due_order_actions(self, order, now_ns):
        """Retry only identity-preserving reads and confirmed-live cancellations."""
        reconcile_due = self._order_info_get(order, "reconcile_next_monotonic_ns")
        if reconcile_due not in (None, ""):
            try:
                if now_ns >= int(reconcile_due):
                    self._request_order_reconcile(order)
            except (TypeError, ValueError):
                order.addinfo(reconcile_next_monotonic_ns=None)

        cancel_due = self._order_info_get(order, "cancel_retry_due_monotonic_ns")
        if cancel_due in (None, ""):
            return
        try:
            due = int(cancel_due)
        except (TypeError, ValueError):
            order.addinfo(cancel_retry_due_monotonic_ns=None)
            return
        if now_ns < due or bool(self._order_info_get(order, "cancel_requested_remote", False)):
            return
        if not bool(self._order_info_get(order, "cancel_reconcile_confirmed_live", False)):
            return
        order.addinfo(cancel_retry_due_monotonic_ns=None)
        self.cancel(order)

    def _schedule_sdk_reconcile(self):
        """Schedule throttled SDK reads without network I/O on this thread."""
        if self._periodic_reconcile_pending or not self._live_started:
            return
        startup_policy = self.p.position_sync_policy == "startup"
        if startup_policy:
            if self.get_orders_open() or self._pending_trade_updates:
                return
            interval = float(self.p.position_audit_interval or 0.0)
            if interval <= 0 or not self._should_refresh(self._last_position_audit, interval):
                return
        else:
            intervals = (
                (self._last_account_refresh, float(self.p.account_refresh_interval or 0.0)),
                (self._last_positions_refresh, float(self.p.positions_refresh_interval or 0.0)),
                (
                    self._last_open_orders_refresh,
                    float(self.p.open_orders_refresh_interval or 0.0),
                ),
            )
            if not any(self._should_refresh(last, interval) for last, interval in intervals):
                return
        method = getattr(self.store, "enqueue_reconcile", None)
        if not callable(method):
            return
        receipt = method()
        self._periodic_reconcile_pending = bool(
            isinstance(receipt, dict) and receipt.get("queued") is True
        )
        if startup_policy and self._periodic_reconcile_pending:
            self._last_position_audit = time.monotonic()

    def _maybe_audit_positions(self):
        """Compare remote positions with the local ledger without importing.

        ``startup`` sessions keep confirmed fills as the accounting authority
        and never re-import snapshots. A low-frequency audit compares both
        views while nothing is in flight. Drift or an inconclusive query blocks
        new exposure until a later audit fully matches the local ledger.
        """
        interval = float(self.p.position_audit_interval or 0.0)
        if interval <= 0:
            return
        if self.store is None or not self._live_started or not self.store.is_connected:
            return
        if self.p.position_sync_policy != "startup" or not self._positions_snapshot_loaded:
            return
        if self.get_orders_open() or self._pending_trade_updates:
            return
        if not self._should_refresh(self._last_position_audit, interval):
            return
        self._last_position_audit = time.monotonic()
        try:
            try:
                rows = self.store.get_positions(force=True, raise_errors=True)
            except TypeError:
                rows = self.store.get_positions()
            mismatches = self._position_audit_diff(rows)
        except Exception as exc:
            _safe_log("warning", "btapibroker:3347 fallback on Exception")
            self._position_audit_error = str(self._redact_runtime_value(exc))
            self._position_audit_blocked = True
            self._emit_runtime_event(
                "position_audit_failed",
                level="ERROR",
                error_code=type(exc).__name__,
                error_msg=self._position_audit_error,
            )
            _safe_log("warning", "position_audit_failed: %s", exc)
            return

        was_blocked = self._position_audit_blocked
        self._position_audit_mismatch = mismatches or None
        self._position_audit_error = None
        self._position_audit_blocked = bool(mismatches)
        if mismatches:
            self._emit_runtime_event(
                "position_audit_mismatch", level="ERROR", mismatches=mismatches
            )
            _safe_log("warning", "position_audit_mismatch: %s", mismatches)
        elif was_blocked:
            self._emit_runtime_event("position_audit_recovered", status="recovered")

    def _position_audit_diff(self, rows):
        """Return ledger-vs-remote differences for tracked symbols, or None."""
        synced: "collections.defaultdict[str, Position]" = collections.defaultdict(Position)
        long_synced: "collections.defaultdict[str, Position]" = collections.defaultdict(Position)
        short_synced: "collections.defaultdict[str, Position]" = collections.defaultdict(Position)
        tracked = self._tracked_position_alias_map()
        for item in rows or []:
            key = self._position_row_canonical_key(item, tracked)
            if tracked and key is None:
                continue
            try:
                self._sync_one_position(item, synced, long_synced, short_synced, key=key)
            except ValueError as exc:
                _safe_log("error", "btapibroker:3379 re-raising ValueError")
                raise ValueError("Remote position audit returned an unusable row") from exc
        local_maps = (
            [
                ("long", long_synced, self.long_positions),
                ("short", short_synced, self.short_positions),
            ]
            if self._is_dual_side_mode()
            else [("net", synced, self.positions)]
        )
        mismatches = []
        for label, remote_map, local_map in local_maps:
            for key in set(remote_map) | set(local_map):
                remote_size = float(remote_map.get(key, Position()).size or 0.0)
                local_size = float(local_map.get(key, Position()).size or 0.0)
                if label != "net":
                    remote_size = abs(remote_size)
                    local_size = abs(local_size)
                if abs(remote_size - local_size) <= 1e-9:
                    continue
                mismatches.append(
                    {
                        "symbol": key,
                        "leg": label,
                        "local_size": local_size,
                        "remote_size": remote_size,
                    }
                )
        return mismatches or None

    def _position_audit_order_error(self, order):
        """Block exposure increases after an inconclusive or mismatched audit."""
        if not self._position_audit_blocked:
            return None

        offset = str(self._order_info_get(order, "offset") or "").strip().lower()
        if offset not in {"close", "close_today", "close_yesterday"}:
            return (
                "position_audit_blocked",
                "Opening orders are blocked until a position audit fully matches the local ledger",
            )

        requested = abs(float(order.size or 0.0))
        if requested <= 0.0:
            return (
                "position_audit_close_not_reducing",
                "Audit-blocked close size must be positive",
            )
        key = self._position_key(order.data)
        if self._is_dual_side_mode():
            position_side = normalize_position_side(self._order_info_get(order, "position_side"))
            if position_side not in {"long", "short"}:
                return (
                    "position_audit_close_not_reducing",
                    "Audit-blocked close orders require an explicit position side",
                )
            if (position_side == "long" and order.isbuy()) or (
                position_side == "short" and not order.isbuy()
            ):
                return (
                    "position_audit_close_not_reducing",
                    "Audit-blocked close order direction would increase the selected leg",
                )
            available = abs(float(self._get_leg_store(position_side)[key].size or 0.0))
        else:
            current_size = float(self.positions[key].size or 0.0)
            available = (
                abs(current_size)
                if (order.isbuy() and current_size < 0.0)
                or (not order.isbuy() and current_size > 0.0)
                else 0.0
            )

        if requested > available + 1e-12:
            return (
                "position_audit_close_not_reducing",
                "Audit-blocked close size exceeds the locally confirmed position",
            )
        return None

    def get_notification(self):
        """Return the next pending order notification."""
        if self.notifs:
            return self.notifs.popleft()
        return None

    def orderstatus(self, order):
        """Return the status for an order or order reference."""
        if hasattr(order, "status"):
            return order.status

        if order in self.orders:
            return self.orders[order].status

        return None

    def get_orders_open(self, safe=False):
        """Return still-open orders."""
        orders = [order for order in self.orders.values() if order.alive()]
        if safe:
            return [order.clone() for order in orders]
        return orders

    def fetch_open_orders(self):
        """Fetch provider-side open orders through the bound store."""
        return self._sync_remote_open_orders(force=True, raise_errors=False)

    def get_open_orders(self):
        """Alias for fetch_open_orders()."""
        return self.fetch_open_orders()

    def getopenorders(self):
        """Compatibility alias for fetch_open_orders()."""
        return self.fetch_open_orders()

    def buy(
        self,
        owner,
        data,
        size,
        price=None,
        plimit=None,
        exectype=None,
        valid=None,
        tradeid=0,
        oco=None,
        trailamount=None,
        trailpercent=None,
        parent=None,
        transmit=True,
        histnotify=False,
        _checksubmit=True,
        **kwargs,
    ):
        """Create and submit a buy order."""
        position_side, offset, order_kwargs = self._normalize_order_meta(True, kwargs)
        order = BuyOrder(
            owner=owner,
            data=data,
            size=size,
            price=price,
            pricelimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            trailamount=trailamount,
            trailpercent=trailpercent,
            parent=parent,
            transmit=transmit,
            histnotify=histnotify,
        )
        # OrderBase keeps a signed/normalized size and may substitute a data
        # close for a missing price.  Retain the caller's raw option inputs so
        # the option gate can reject booleans and non-finite values before any
        # float/abs conversion.
        order._btapi_raw_order_size = size
        order._btapi_raw_order_price = price
        self._attach_position_meta(
            order, position_side=position_side, offset=offset, **order_kwargs
        )
        if oco is not None:
            order.addinfo(oco=oco)
        return self.submit(order)

    def sell(
        self,
        owner,
        data,
        size,
        price=None,
        plimit=None,
        exectype=None,
        valid=None,
        tradeid=0,
        oco=None,
        trailamount=None,
        trailpercent=None,
        parent=None,
        transmit=True,
        histnotify=False,
        _checksubmit=True,
        **kwargs,
    ):
        """Create and submit a sell order."""
        position_side, offset, order_kwargs = self._normalize_order_meta(False, kwargs)
        order = SellOrder(
            owner=owner,
            data=data,
            size=size,
            price=price,
            pricelimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            trailamount=trailamount,
            trailpercent=trailpercent,
            parent=parent,
            transmit=transmit,
            histnotify=histnotify,
        )
        order._btapi_raw_order_size = size
        order._btapi_raw_order_price = price
        self._attach_position_meta(
            order, position_side=position_side, offset=offset, **order_kwargs
        )
        if oco is not None:
            order.addinfo(oco=oco)
        return self.submit(order)

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

        if getattr(self, "_managed_provider_projection_failed", False):
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

        expected_fill_fields = {
            "schema", "time_source", "fill_id", "match_time_ns", "quantity", "price",
            "commission", "commission_currency", "commission_model_id",
            "commission_model_version", "event_id", "event_sequence", "journal_generation",
            "scope_key", "intent_id", "intent_fingerprint", "account_ref", "strategy_ref",
            "quote_source_ref", "quote_generation", "quote_cursor", "quote_instrument",
            "receipt_sha256",
        }
        expected_event_context_fields = {
            "data_name", "instrument", "bar_index", "datetime_hex", "comminfo",
            "commission_currency", "quote_source_ref", "quote_generation", "quote_cursor",
            "quote_instrument", "quote_as_of_ns",
        }
        if (
            frozenset(fill) != expected_fill_fields
            or frozenset(event_context) != expected_event_context_fields
            or fill.get("schema") != "managed_paper_fill.v2"
            or fill.get("time_source") != "MANAGED_PAPER_MATCH"
            or fill.get("commission_model_id") != "quote_notional_rate"
            or fill.get("commission_model_version") != "1"
            or fill.get("event_id") != event.get("event_id")
            or fill.get("event_sequence") != event.get("sequence")
            or fill.get("journal_generation") != event.get("journal_generation")
            or fill.get("scope_key") != event.get("scope_key")
            or fill.get("intent_id") != intent_id
            or fill.get("intent_fingerprint") != event.get("intent_fingerprint")
            or fill.get("fill_id") != f"paper:{fill.get('journal_generation')}:{fill.get('event_id')}"
            or type(fill.get("match_time_ns")) is not int
            or fill.get("match_time_ns") <= 0
            or type(fill.get("quote_cursor")) is not int
            or fill.get("quote_cursor") < 0
            or type(fill.get("event_sequence")) is not int
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
            or quote_binding.get("source_ref") != fill.get("quote_source_ref")
            or quote_binding.get("generation") != fill.get("quote_generation")
            or quote_binding.get("cursor") != fill.get("quote_cursor")
            or quote_binding.get("instrument") != fill.get("quote_instrument")
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
                "filled": details["filled_quantity"],
                "price": details["average_price"],
                "avg_price": details["average_price"],
                "cumulative_commission": details["cumulative_commission"],
                "commission_normalized": True,
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
        elif cumulative_commission is not None and previous_commission is not None:
            if abs(cumulative_commission - previous_commission) > 1e-12:
                self._fence_service_execution_recovery(
                    order, "recovery_fee_correction_without_fill_unsupported"
                )
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

    def _fence_service_execution_recovery(self, order, reason):
        self._managed_provider_projection_failed = True
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

    def notify(
        self,
        order,
        *,
        recovery_receipt_id=None,
        recovery_restore_only=False,
        recovery_fill_projection=None,
    ):
        """Queue an order notification, optionally bound to one recovery receipt."""
        if self._service_execution_recovery_suppress_notifications:
            return
        # ``Order.clone`` deliberately clones execution state but retains the
        # original ``info`` mapping.  A later broker update can otherwise
        # rewrite a queued Accepted/UNKNOWN notification before Cerebro
        # dispatches it (for example UNKNOWN -> Completed in one drain pass).
        # Keep the top-level metadata snapshot independent while preserving
        # user-provided object identities stored as values such as OCO links.
        snapshot = order.clone()
        snapshot.info = copy(order.info)
        if recovery_receipt_id is not None:
            snapshot.addinfo(service_execution_recovery_receipt_id=recovery_receipt_id)
        if recovery_restore_only:
            snapshot.addinfo(service_execution_recovery_restore_only=True)
        if recovery_fill_projection is not None:
            snapshot.addinfo(
                service_execution_recovery_fill_projection=deepcopy(
                    recovery_fill_projection
                )
            )
        self.notifs.append(snapshot)

    def data_started(self, data):
        """Hook called when a feed starts."""

    def disable_trading(self, reason="manual"):
        """Disable new order submissions while keeping cancel support available."""
        self._trading_enabled = False
        self._emit_runtime_event(
            "trading_disabled",
            details={"reason": reason},
            status="disabled",
        )
        self._emit_runtime_event(
            "account_trading_disabled",
            details={"reason": reason},
            status="disabled",
        )

    def enable_trading(self, reason="manual"):
        """Re-enable order submissions."""
        if self._is_market_data_only():
            self._trading_enabled = False
            self._emit_runtime_event(
                "trading_enable_blocked",
                details={"reason": reason, "market_data_only": True},
                status="disabled",
            )
            return
        self._trading_enabled = True
        self._emit_runtime_event(
            "trading_enabled",
            details={"reason": reason},
            status="enabled",
        )

    def pause_strategy(self, reason="manual"):
        """Pause strategy-driven order routing without disconnecting the store."""
        self._strategy_paused = True
        self._emit_runtime_event(
            "strategy_paused",
            details={"reason": reason},
            status="paused",
        )
        self._emit_runtime_event(
            "strategy_trading_paused",
            details={"reason": reason},
            status="paused",
        )

    def resume_strategy(self, reason="manual"):
        """Resume strategy-driven order routing."""
        self._strategy_paused = False
        self._emit_runtime_event(
            "strategy_resumed",
            details={"reason": reason},
            status="running",
        )

    def force_logout(self, reason="manual"):
        """Force the underlying store session to disconnect."""
        self._emit_runtime_event(
            "gateway_force_logout_requested",
            details={"reason": reason},
            status="disconnecting",
        )
        self._emit_runtime_event(
            "force_logout_requested",
            details={"reason": reason},
            status="disconnecting",
        )
        self._live_started = False
        self._startup_ready = False
        if self.store is not None and self.store.is_connected:
            self.store.stop()

    def batch_cancel(self, orders=None):
        """Cancel a batch of live orders and return the canceled order objects."""
        if self._is_market_data_only():
            self._record_market_data_only_rejection("batch_cancel")
            # Do not even refresh remote orders here.  Observation sessions
            # may see account-owned orders, but cannot establish authority to
            # mutate them through this convenience path.
            self._trading_enabled = False
            self._emit_runtime_event(
                "batch_cancel_rejected_local",
                level="ERROR",
                status="rejected",
                error_code="market_data_only",
                error_msg="Batch cancellation is disabled for this observation-only broker session",
                details={"orders_supplied": orders is not None},
            )
            return []
        candidates = self._batch_cancel_candidates(orders)
        requested = [
            (
                self._order_runtime_details(item)
                if kind == "local"
                else self._remote_order_details(item)
            )
            for kind, item in candidates
        ]
        self._emit_runtime_event(
            "batch_cancel_requested",
            status="submitted",
            details={
                "requested_count": len(candidates),
                "orders": requested,
            },
        )

        cancelled = []
        failures = []
        for kind, item in candidates:
            if kind == "local":
                order = item
                if not order.alive():
                    continue

                try:
                    self.cancel(order)
                except Exception as exc:
                    _safe_log("warning", "btapibroker:3724 fallback on Exception")
                    details = self._order_runtime_details(order)
                    details.update(
                        error_code=type(exc).__name__,
                        error_msg=str(self._redact_runtime_value(exc)),
                    )
                    failures.append(details)
                    continue

                cancelled.append(order)
                continue

            try:
                self._cancel_remote_open_order(item)
            except Exception as exc:
                _safe_log("warning", "btapibroker:3738 fallback on Exception")
                details = self._remote_order_details(item)
                details.update(
                    error_code=type(exc).__name__,
                    error_msg=str(self._redact_runtime_value(exc)),
                )
                failures.append(details)
                continue

            cancelled.append(item)

        summary = {
            "requested_count": len(candidates),
            "cancelled_count": len(cancelled),
            "failure_count": len(failures),
            "cancelled_orders": [
                (
                    self._order_runtime_details(item)
                    if hasattr(item, "alive")
                    else self._remote_order_details(item)
                )
                for item in cancelled
            ],
            "failed_orders": failures,
        }
        if failures:
            self._emit_runtime_event(
                "batch_cancel_failed",
                level="ERROR",
                status="partial" if cancelled else "failed",
                details=summary,
            )
        else:
            self._emit_runtime_event(
                "batch_cancel_completed",
                status="completed",
                details=summary,
            )

        return cancelled

    def _batch_cancel_candidates(self, orders=None):
        """Return local and remote-open orders that should be cancelled."""
        if orders is not None:
            return [("local", order) for order in orders]

        local_orders = self.get_orders_open()
        candidates = [("local", order) for order in local_orders]
        local_remote_ids = {
            str(value)
            for order in local_orders
            for value in (
                self._order_info_get(order, "external_order_id"),
                self._order_info_get(order, "ctp_order_ref"),
                getattr(order, "ref", None),
            )
            if value not in (None, "")
        }

        remote_orders = self._sync_remote_open_orders(force=True, raise_errors=False)
        for item in remote_orders:
            remote_id = self._remote_order_id(item)
            if remote_id in (None, "") or str(remote_id) in local_remote_ids:
                continue
            candidates.append(("remote", item))
        return candidates

    @classmethod
    def _remote_order_id(cls, item):
        if not isinstance(item, dict):
            return None
        return cls._remote_external_order_id(item) or cls._remote_client_order_ref(item)

    @classmethod
    def _remote_external_order_id(cls, update):
        if not isinstance(update, dict):
            return None
        unwrapped = cls._unwrap_submit_response(update)
        if isinstance(unwrapped, dict):
            update = unwrapped
        kind = str(update.get("kind") or "").strip().lower()
        keys = _REMOTE_TRADE_ORDER_ID_KEYS if kind == "trade" else _REMOTE_ORDER_ID_KEYS
        return cls._extract_update_value(update, *keys)

    @classmethod
    def _remote_client_order_ref(cls, update):
        if not isinstance(update, dict):
            return None
        unwrapped = cls._unwrap_submit_response(update)
        if isinstance(unwrapped, dict):
            update = unwrapped
        return cls._extract_update_value(update, *_REMOTE_CLIENT_ORDER_REF_KEYS)

    @staticmethod
    def _remote_order_data_name(item):
        if not isinstance(item, dict):
            return None
        return BtApiBroker._extract_update_value(item, *_DATA_NAME_KEYS)

    def _remote_order_details(self, item):
        remote_id = self._remote_order_id(item)
        external_order_id = None
        ctp_order_ref = None
        side = None
        size = None
        price = None
        status = None
        if isinstance(item, dict):
            external_order_id = self._remote_external_order_id(item)
            ctp_order_ref = self._remote_client_order_ref(item)
            side = self._extract_update_value(item, "side", "Side", "direction", "Direction")
            size = self._extract_update_value(item, "size", "volume", "sz", "qty", "quantity")
            price = self._extract_update_value(item, "price", "Price", "px", "avgPx")
            status = self._extract_update_value(item, "status", "state", "Status")

        details = {
            "order_ref": remote_id,
            "external_order_id": external_order_id,
            "ctp_order_ref": ctp_order_ref,
            "data_name": self._remote_order_data_name(item),
            "side": side,
            "size": size,
            "price": price,
            "status": status,
            "source": "remote_open_orders",
        }
        return {key: value for key, value in details.items() if value not in (None, "")}

    def _cancel_remote_open_order(self, item):
        """Cancel a provider-side open order that has no local Order object."""
        if self.store is None:
            raise ValueError("BtApiBroker requires a BtApiStore instance")
        order_ref = self._remote_order_id(item)
        if order_ref in (None, ""):
            raise ValueError("Remote open order is missing an order reference")
        dataname = self._remote_order_data_name(item)
        if hasattr(self.store, "cancel_order_ref"):
            return self.store.cancel_order_ref(order_ref, dataname=dataname)
        raise ValueError("BtApiStore does not support cancelling remote order references")

    def _refresh_account(self, force=False, raise_errors=False):
        """Refresh cached cash and value from the store."""
        service_read_only = bool(getattr(self.store, "_service_read_only", False))
        if service_read_only:
            force = True
            raise_errors = True
        if self.store is None or not self._live_started or not self.store.is_connected:
            if service_read_only:
                raise RuntimeError("read-only service account snapshot is unavailable")
            return
        if not force and not self._should_refresh(
            self._last_account_refresh,
            float(self.p.account_refresh_interval or 0.0),
        ):
            return

        try:
            try:
                balance = self.store.get_balance(force=force, raise_errors=raise_errors)
            except TypeError:
                if service_read_only:
                    raise
                balance = self.store.get_balance()
            self._cash = float(balance.get("cash", self._cash))
            self._value = float(balance.get("value", self._value))
            self._last_account_refresh = time.monotonic()
        except Exception as e:
            _safe_log("warning", "btapibroker:3896 fallback on Exception")
            _safe_log("debug", "Failed to refresh account: %s", e)
            if raise_errors:
                raise

    def _sync_positions(self, force=False, raise_errors=False):
        """Import provider positions according to the explicit accounting policy.

        Startup-only sessions keep actual fills as their accounting authority.
        A later remote snapshot may already contain an unreported execution,
        so neither a timed refresh nor ``force`` may replace that baseline.
        Remote audit reads remain available directly on the store.
        """
        service_read_only = bool(getattr(self.store, "_service_read_only", False))
        if service_read_only:
            force = True
            raise_errors = True
        if self.store is None or not self._live_started or not self.store.is_connected:
            if service_read_only:
                raise RuntimeError("read-only service positions are unavailable")
            return
        if (
            self.p.position_sync_policy == "startup"
            and self._positions_snapshot_loaded
            and not service_read_only
        ):
            return
        if not force and not self._should_refresh(
            self._last_positions_refresh,
            float(self.p.positions_refresh_interval or 0.0),
        ):
            return

        try:
            synced: "collections.defaultdict[str, Position]" = collections.defaultdict(Position)
            long_synced: "collections.defaultdict[str, Position]" = collections.defaultdict(
                Position
            )
            short_synced: "collections.defaultdict[str, Position]" = collections.defaultdict(
                Position
            )
            try:
                position_rows = self.store.get_positions(
                    force=force,
                    raise_errors=raise_errors,
                )
            except TypeError:
                if service_read_only:
                    raise
                position_rows = self.store.get_positions()
            tracked_aliases = self._tracked_position_alias_map()
            for item in position_rows:
                key = self._position_row_canonical_key(item, tracked_aliases)
                # An execution broker tracks feed-bound positions only so it
                # cannot accidentally act on unrelated account exposure.  An
                # observation-only broker has no mutation path and therefore
                # retains every hydrated account position for reporting.
                if tracked_aliases and key is None and not self._is_market_data_only():
                    continue
                self._sync_one_position(item, synced, long_synced, short_synced, key=key)

            if self._is_dual_side_mode():
                self.long_positions = long_synced
                self.short_positions = short_synced
                self.positions = collections.defaultdict(Position)
                for key in set(long_synced) | set(short_synced):
                    self._sync_net_position(key)
            else:
                self.positions = synced
            self._last_positions_refresh = time.monotonic()
            self._positions_snapshot_loaded = True
        except Exception as e:
            _safe_log("warning", "btapibroker:3955 fallback on Exception")
            _safe_log("debug", "Failed to sync positions: %s", e)
            if raise_errors:
                raise

    def _sync_one_position(
        self,
        item,
        synced: "collections.defaultdict[str, Position]",
        long_synced: "collections.defaultdict[str, Position]",
        short_synced: "collections.defaultdict[str, Position]",
        key=None,
    ):
        """Parse a single provider position dict into the right cache bucket.

        Extracted from ``_sync_positions``' loop body; behavior unchanged.
        Mutates the supplied ``synced`` / ``long_synced`` / ``short_synced``
        defaultdicts in place and returns nothing.
        """
        key = key or self._position_row_key(item)
        if not key:
            return

        size = self._extract_update_value(item, *_POSITION_SIZE_KEYS)
        size = float(size or 0.0)
        direction = self._extract_position_direction(item)

        price = self._extract_update_value(item, *_POSITION_PRICE_KEYS)
        price = float(price or 0.0)

        if self._is_dual_side_mode():
            if size and direction not in {"long", "short"}:
                raise ValueError(
                    "dual_side mode requires provider positions with explicit direction"
                )
            if direction == "short" or size < 0:
                short_synced[key].update(abs(size), price)
            else:
                long_synced[key].update(abs(size), price)
        else:
            if direction == "short" and size > 0:
                size = -size
            current = synced[key]
            if current.size and size and (current.size > 0) != (size > 0):
                raise ValueError(
                    "net mode received opposing position rows for one instrument; "
                    "verify the remote account position mode"
                )
            current.update(size, price)

    def _tracked_position_alias_map(self):
        """Return aliases for symbols that belong to this broker instance."""
        tracked_keys = []

        def add_symbol(value):
            if value in (None, ""):
                return
            symbol = str(value).strip()
            if symbol and symbol not in tracked_keys:
                tracked_keys.append(symbol)

        store = self.store
        if store is not None:
            for data in getattr(store, "_data_feeds", []) or []:
                add_symbol(self._position_key(data))
            for dataname in getattr(store, "_subscribed_datanames", set()) or set():
                add_symbol(dataname)

        for order in self.orders.values():
            data = getattr(order, "data", None)
            if data is not None:
                add_symbol(self._position_key(data))

        alias_map: dict[str, str] = {}
        for key in tracked_keys:
            for alias in self._symbol_aliases(key):
                alias_map.setdefault(alias, key)
        return alias_map

    @classmethod
    def _position_row_canonical_key(cls, item, alias_map):
        key = cls._position_row_key(item)
        if not alias_map:
            return key
        if key in (None, ""):
            return None
        for alias in cls._symbol_aliases(key):
            if alias in alias_map:
                return alias_map[alias]
        return None

    @staticmethod
    def _position_row_key(item):
        if not isinstance(item, dict):
            return None
        return BtApiBroker._extract_update_value(item, *_DATA_NAME_KEYS)

    @staticmethod
    def _normalise_code_text(value):
        text = str(value).strip().lower().replace("-", "_")
        numeric_text = text.replace(",", "")
        try:
            number = float(numeric_text)
        except (TypeError, ValueError, OverflowError):
            return text
        if number.is_integer():
            return str(int(number))
        return text

    @staticmethod
    def _normalise_position_direction(value):
        if value in (None, ""):
            return ""
        text = BtApiBroker._normalise_code_text(value)
        if text in {"long", "buy", "b", "bid", "2"}:
            return "long"
        if text in {"short", "sell", "s", "ask", "3"}:
            return "short"
        return text

    @classmethod
    def _extract_position_direction(cls, item):
        if not isinstance(item, dict):
            return ""
        details = item.get("details")
        if not isinstance(details, dict):
            details = {}
        for key in _POSITION_DIRECTION_KEYS:
            value = item.get(key)
            if value in (None, ""):
                value = details.get(key)
            if value in (None, ""):
                continue
            if key in {"positionIdx", "position_idx"}:
                text = cls._normalise_code_text(value)
                if text == "1":
                    return "long"
                if text == "2":
                    return "short"
                if text == "0":
                    return ""
            return cls._normalise_position_direction(value)
        return ""

    def _sync_remote_open_orders(self, force=False, raise_errors=False):
        """Refresh the cached provider-side open-order snapshot."""
        service_read_only = bool(getattr(self.store, "_service_read_only", False))
        if service_read_only:
            force = True
            raise_errors = True
        if self.store is None or not self._live_started or not self.store.is_connected:
            if service_read_only:
                raise RuntimeError("read-only service open-order snapshot is unavailable")
            return deepcopy(self._remote_open_orders_snapshot)
        if not force and not self._should_refresh(
            self._last_open_orders_refresh,
            float(self.p.open_orders_refresh_interval or 0.0),
        ):
            return deepcopy(self._remote_open_orders_snapshot)

        try:
            try:
                orders = list(
                    self.store.fetch_open_orders(force=force, raise_errors=raise_errors) or []
                )
            except TypeError:
                if service_read_only:
                    raise
                orders = list(self.store.fetch_open_orders() or [])
            self._remote_open_orders_snapshot = orders
            self._last_open_orders_refresh = time.monotonic()
            self._emit_runtime_event(
                "open_orders_sync_completed",
                status="completed",
                details={
                    "open_order_count": len(orders),
                    "orders": list(orders),
                },
            )
            return deepcopy(self._remote_open_orders_snapshot)
        except Exception as e:
            _safe_log("warning", "btapibroker:4127 fallback on Exception")
            _safe_log("debug", "Failed to sync remote open orders: %s", e)
            self._emit_runtime_event(
                "open_orders_sync_failed",
                level="ERROR",
                status="failed",
                error_code=type(e).__name__,
                error_msg=str(self._redact_runtime_value(e)),
                details={
                    "open_order_count": len(self._remote_open_orders_snapshot),
                    "orders": list(self._remote_open_orders_snapshot),
                },
            )
            if raise_errors:
                raise
            return deepcopy(self._remote_open_orders_snapshot)

    @staticmethod
    def _should_refresh(last_refresh, interval):
        """Return whether a throttled live refresh should run now."""
        if interval <= 0 or last_refresh <= 0:
            return True

        return (time.monotonic() - last_refresh) >= interval

    @staticmethod
    def _position_key(data):
        """Extract a stable position key from a data feed."""
        if isinstance(data, str):
            return data
        return (
            getattr(data, "_name", None)
            or getattr(data, "_dataname", None)
            or getattr(getattr(data, "p", None), "dataname", None)
            or repr(data)
        )

    @staticmethod
    def _symbol_aliases(symbol):
        """Return common aliases for matching configured contract metadata."""
        raw = str(symbol or "").strip()
        aliases = [raw]
        if "." in raw:
            head, tail = (part.strip() for part in raw.split(".", 1))
            head_upper = head.upper()
            tail_upper = tail.upper()
            if head_upper in _CTP_EXCHANGES:
                aliases.extend([tail, tail.upper(), tail.lower()])
            elif tail_upper in _CTP_EXCHANGES:
                aliases.extend([head, head.upper(), head.lower()])
            else:
                aliases.extend([tail, tail.upper(), tail.lower()])
        if "_" in raw:
            head, tail = raw.split("_", 1)
            if head.upper() in {"SHFE", "DCE", "CZCE", "CFFEX", "INE", "GFEX"}:
                aliases.extend([tail, tail.upper(), tail.lower()])
            elif tail.upper() in _CTP_EXCHANGES:
                aliases.extend([head, head.upper(), head.lower()])
        aliases.extend([raw.upper(), raw.lower()])
        compact = "".join(ch for ch in raw if ch.isalnum())
        aliases.extend([compact, compact.upper(), compact.lower()])
        result = []
        seen = set()
        for alias in aliases:
            if alias and alias not in seen:
                result.append(alias)
                seen.add(alias)
        return result

    def _warm_contract_metadata(self):
        """Materialize comminfo for known live symbols at broker startup."""
        names: set[str] = set()
        for container in (self.positions, self.long_positions, self.short_positions):
            try:
                names.update(str(key) for key in container.keys() if key not in (None, ""))
            except Exception:
                _safe_log("warning", "btapibroker:4197 suppressed Exception")
                continue

        data_feeds = getattr(self.store, "_data_feeds", []) if self.store is not None else []
        for data in data_feeds:
            try:
                names.add(str(self._position_key(data)))
            except Exception:
                _safe_log("warning", "btapibroker:4204 suppressed Exception")
                continue

        routes = {}
        if self._uses_async_commands():
            routes_method = getattr(self.store, "get_symbol_routes", None)
            if callable(routes_method):
                routes = dict(routes_method() or {})
            else:
                routes = dict(getattr(self.store, "_sdk_routes", {}) or {})

        for data_name in sorted(names):
            if routes:
                aliases = set(self._symbol_aliases(data_name))
                routed_symbol = next(
                    (
                        symbol
                        for symbol in routes
                        if aliases.intersection(self._symbol_aliases(symbol))
                    ),
                    None,
                )
                if routed_symbol is not None:
                    metadata = getattr(self.store, "contract_metadata", {})
                    if not any(
                        metadata.get(alias) for alias in self._symbol_aliases(routed_symbol)
                    ):
                        # Fetch typed rules during the bounded startup phase.  Order
                        # submission itself remains an enqueue-only hot path.
                        self.store.get_instrument_spec(routed_symbol)
            self._materialize_contract_comminfo(data_name)

    def _materialize_contract_comminfo(self, data_name):
        """Create and cache a symbol-specific comminfo when metadata is available."""
        if not data_name:
            return None
        for alias in self._symbol_aliases(data_name):
            if alias in self.comminfo:
                return self.comminfo[alias]
        comminfo = self._metadata_to_comminfo(self._contract_rules_for(data_name))
        if comminfo is not None:
            self.addcommissioninfo(comminfo, name=data_name)
        return comminfo

    @staticmethod
    def _first_number(*values, default=None):
        for value in values:
            if value is None or value == "":
                continue
            if isinstance(value, bool):
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                _safe_log("debug", "btapibroker:4257 ignored TypeError,ValueError")
                continue
            if math.isfinite(number):
                return number
        if default is None or isinstance(default, bool) or default == "":
            return None
        try:
            number = float(default)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @classmethod
    def _normalise_rate(cls, value, default=0.0):
        number = cls._first_number(value, default=default)
        if number is None:
            return default
        if number > 1.0:
            return number / 100.0
        return max(number, 0.0)

    @classmethod
    def _normalise_signed_rate(cls, value, default=0.0):
        number = cls._first_number(value, default=default)
        if number is None:
            return default
        if abs(number) > 1.0:
            return number / 100.0
        return number

    @classmethod
    def _metadata_commission_rate(cls, metadata, *keys):
        method = str(metadata.get("commission_method") or "").strip().lower()
        for key in keys:
            value = cls._first_number(metadata.get(key))
            if value is None:
                continue
            key_text = str(key or "")
            if (
                method == "percent_10k"
                or (key_text.startswith("COMMISSION_") and key_text.endswith("_RATIO"))
                or (
                    key_text
                    in {
                        "OpenRatioByMoney",
                        "CloseRatioByMoney",
                        "CloseTodayRatioByMoney",
                        "CloseYesterdayRatioByMoney",
                    }
                    and value > 0.01
                )
            ):
                value = max(value, 0.0)
                return value / 10000.0 if value > 0.01 else value
            return cls._normalise_rate(value, 0.0)
        return None

    @classmethod
    def _metadata_open_commission_rate(cls, metadata):
        return cls._metadata_commission_rate(
            metadata,
            "commission",
            "commission_rate",
            "fee_rate",
            "open_fee_rate",
            "open_commission_rate",
            "OpenRatioByMoney",
            "COMMISSION_OPEN_RATIO",
        )

    @classmethod
    def _metadata_close_commission_rate(cls, metadata):
        return cls._metadata_commission_rate(
            metadata,
            "close_fee_rate",
            "close_commission_rate",
            "CloseRatioByMoney",
            "COMMISSION_CLOSE_RATIO",
        )

    @classmethod
    def _metadata_close_today_commission_rate(cls, metadata):
        return cls._metadata_commission_rate(
            metadata,
            "close_today_fee_rate",
            "close_today_commission_rate",
            "CloseTodayRatioByMoney",
            "COMMISSION_CLOSE_TODAY_RATIO",
        )

    @classmethod
    def _metadata_close_yesterday_commission_rate(cls, metadata):
        return cls._metadata_commission_rate(
            metadata,
            "close_yesterday_fee_rate",
            "close_yesterday_commission_rate",
            "CloseYesterdayRatioByMoney",
            "COMMISSION_CLOSE_YESTERDAY_RATIO",
        )

    @classmethod
    def _metadata_maker_commission_rate(cls, metadata):
        return cls._metadata_role_commission_rate(
            metadata,
            "maker_commission_rate",
            "maker_fee_rate",
        )

    @classmethod
    def _metadata_taker_commission_rate(cls, metadata):
        return cls._metadata_role_commission_rate(
            metadata,
            "taker_commission_rate",
            "taker_fee_rate",
        )

    @classmethod
    def _metadata_role_commission_rate(cls, metadata, *keys):
        for key in keys:
            value = cls._first_number(metadata.get(key))
            if value is not None:
                return cls._normalise_signed_rate(value, 0.0)
        return None

    @classmethod
    def _metadata_commission_amount(cls, metadata, *keys):
        return cls._first_number(*(metadata.get(key) for key in keys))

    @classmethod
    def _metadata_text(cls, metadata, *keys):
        for key in keys:
            value = metadata.get(key)
            if value in (None, ""):
                continue
            return cls._normalise_code_text(value)
        return ""

    @classmethod
    def _metadata_currency(cls, metadata, *keys):
        text = cls._metadata_text(metadata, *keys)
        return text.replace("_", "")

    @classmethod
    def _metadata_bool(cls, metadata, *keys):
        for key in keys:
            value = metadata.get(key)
            if value in (None, ""):
                continue
            if isinstance(value, bool):
                return value
            text = cls._normalise_code_text(value)
            if text in {"1", "true", "yes", "y", "inverse"}:
                return True
            if text in {"0", "false", "no", "n", "linear"}:
                return False
        return None

    @classmethod
    def _metadata_is_inverse_contract(cls, metadata):
        explicit = cls._metadata_bool(
            metadata,
            "inverse",
            "is_inverse",
            "isInverse",
            "inverse_contract",
            "inverseContract",
        )
        if explicit is not None:
            return explicit

        type_texts = [
            cls._metadata_text(metadata, key)
            for key in (
                "contract_type",
                "contractType",
                "ctType",
                "type",
                "instrument_type",
                "instrumentType",
                "category",
            )
        ]
        type_texts = [text for text in type_texts if text]
        if any("inverse" in text or "coin_margined" in text for text in type_texts):
            return True
        if any(
            "linear" in text or "usdt_margined" in text or "usdc_margined" in text
            for text in type_texts
        ):
            return False

        base_ccy = cls._metadata_currency(
            metadata,
            "base_currency",
            "baseCurrency",
            "base_ccy",
            "baseCcy",
            "base_asset",
            "baseAsset",
        )
        quote_ccy = cls._metadata_currency(
            metadata,
            "quote_currency",
            "quoteCurrency",
            "quote_ccy",
            "quoteCcy",
            "quote_asset",
            "quoteAsset",
        )
        contract_value_ccy = cls._metadata_currency(
            metadata,
            "contract_value_currency",
            "contractValueCurrency",
            "contract_value_ccy",
            "contractValueCcy",
            "ctValCcy",
        )
        settle_ccy = cls._metadata_currency(
            metadata,
            "settle_currency",
            "settleCurrency",
            "settle_ccy",
            "settleCcy",
            "margin_currency",
            "marginCurrency",
            "margin_ccy",
            "marginCcy",
        )
        fee_ccy = cls._metadata_currency(
            metadata,
            "fee_currency",
            "feeCurrency",
            "fee_ccy",
            "feeCcy",
        )

        if contract_value_ccy and quote_ccy and contract_value_ccy == quote_ccy:
            if not base_ccy or contract_value_ccy != base_ccy:
                return True
        if contract_value_ccy and base_ccy and contract_value_ccy == base_ccy:
            return False
        if base_ccy and quote_ccy and settle_ccy == base_ccy and settle_ccy != quote_ccy:
            return True
        if (
            (contract_value_ccy or settle_ccy)
            and base_ccy
            and quote_ccy
            and fee_ccy == base_ccy
            and fee_ccy != quote_ccy
        ):
            return True
        return False

    @classmethod
    def _metadata_open_commission_amount(cls, metadata):
        return cls._metadata_commission_amount(
            metadata,
            "commission_amount",
            "fee_amount",
            "commission_per_lot",
            "open_fee_amount",
            "open_commission_amount",
            "OpenRatioByVolume",
            "COMMISSION_OPEN_AMOUNT",
        )

    @classmethod
    def _metadata_close_commission_amount(cls, metadata):
        return cls._metadata_commission_amount(
            metadata,
            "close_fee_amount",
            "close_commission_amount",
            "CloseRatioByVolume",
            "COMMISSION_CLOSE_AMOUNT",
        )

    @classmethod
    def _metadata_close_today_commission_amount(cls, metadata):
        return cls._metadata_commission_amount(
            metadata,
            "close_today_fee_amount",
            "close_today_commission_amount",
            "CloseTodayRatioByVolume",
            "COMMISSION_CLOSE_TODAY_AMOUNT",
        )

    @classmethod
    def _metadata_close_yesterday_commission_amount(cls, metadata):
        return cls._metadata_commission_amount(
            metadata,
            "close_yesterday_fee_amount",
            "close_yesterday_commission_amount",
            "CloseYesterdayRatioByVolume",
            "COMMISSION_CLOSE_YESTERDAY_AMOUNT",
        )

    @classmethod
    def _metadata_is_option(cls, metadata):
        """Return whether metadata explicitly identifies an option contract."""
        type_keys = (
            "asset_type",
            "asset_class",
            "product_class",
            "productClass",
            "ProductClass",
            "contract_type",
            "contractType",
            "instrument_type",
            "instrumentType",
            "security_type",
            "securityType",
            "kind",
        )
        type_values = [
            (key, metadata.get(key)) for key in type_keys if metadata.get(key) not in (None, "")
        ]
        type_kinds = {cls._metadata_asset_kind(value) for _, value in type_values}
        known_type_kinds = {kind for kind in type_kinds if kind in {"option", "non_option"}}
        if len(known_type_kinds) > 1:
            raise OptionAccountingError(
                "option_metadata_asset_type_conflict",
                "option_metadata_asset_type_conflict: contradictory asset/product classes",
            )

        option_type = cls._metadata_option_type_text(metadata)
        premium_style = cls._metadata_consistent_text(
            metadata,
            (
                "premium_style",
                "premiumStyle",
                "settlement_style",
                "option_settlement_style",
                "option_style",
            ),
            "option_metadata_premium_style_conflict",
        )
        option_marked = bool(option_type or premium_style) or any(
            key in metadata for key in ("seller_margin_evidence", "seller_total_margin")
        )
        if known_type_kinds == {"non_option"} and option_marked:
            raise OptionAccountingError(
                "option_metadata_asset_type_conflict",
                "option_metadata_asset_type_conflict: option fields disagree with asset class",
            )
        return known_type_kinds == {"option"} or option_marked

    @classmethod
    def _metadata_consistent_text(cls, metadata, keys, code):
        """Return one normalized text value while rejecting conflicting aliases."""
        values = [
            cls._normalise_code_text(metadata.get(key))
            for key in keys
            if metadata.get(key) not in (None, "")
        ]
        if not values:
            return ""
        if len(set(values)) != 1:
            raise OptionAccountingError(code, f"{code}: contradictory aliases")
        return values[0]

    @classmethod
    def _metadata_option_type_text(cls, metadata):
        """Normalize CTP call/put codes while rejecting contradictory aliases."""
        keys = ("option_type", "optionType", "OptionsType", "options_type")
        values = []
        option_type_aliases = {
            "1": "call",
            "call": "call",
            "c": "call",
            "2": "put",
            "put": "put",
            "p": "put",
        }
        for key in keys:
            value = metadata.get(key)
            if value in (None, ""):
                continue
            text = cls._normalise_code_text(value)
            values.append(option_type_aliases.get(text, text))
        if not values:
            return ""
        if len(set(values)) != 1:
            raise OptionAccountingError(
                "option_metadata_option_type_conflict",
                "option_metadata_option_type_conflict: contradictory option type aliases",
            )
        return values[0]

    @classmethod
    def _metadata_asset_kind(cls, value):
        """Classify raw CTP and normalized asset labels for conflict checks."""
        text = cls._normalise_code_text(value)
        if text in {"2", "6", "option", "options", "spot_option", "spotoption"}:
            return "option"
        if "option" in text:
            return "option"
        if text in {
            "1",
            "future",
            "futures",
            "swap",
            "perpetual",
            "linear",
            "inverse",
            "spot",
            "stock",
            "crypto",
        } or any(token in text for token in ("future", "swap", "perpetual")):
            return "non_option"
        return f"unknown:{text}"

    @classmethod
    def _metadata_option_scope(cls, metadata):
        """Extract only explicit identity fields used to fence seller evidence."""
        scope = metadata.get("seller_margin_scope")
        if scope is not None and not isinstance(scope, Mapping):
            raise OptionAccountingError(
                "option_metadata_scope_invalid",
                "option_metadata_scope_invalid: seller margin scope must be a mapping",
            )
        aliases = {
            "account_fingerprint": ("account_fingerprint", "account_id", "account"),
            "trading_day": ("trading_day", "trade_date", "TradingDay", "date"),
            "connection_generation": (
                "connection_generation",
                "generation",
                "connectionGeneration",
            ),
            "instrument_id": ("instrument_id", "InstrumentID", "instrument", "symbol"),
            "exchange_id": ("exchange_id", "ExchangeID", "exchange"),
            "hedge_flag": ("hedge_flag", "HedgeFlag", "hedge", "hedge_mode"),
            "currency": ("currency", "margin_currency", "settle_currency"),
            "price_basis": ("price_basis", "pricebasis", "price_basis_evidence"),
            "expiry": ("expiry", "option_expiry", "expiry_date", "ExpireDate"),
            "source_hash": ("source_hash", "source_hash_sha256", "sourcehash"),
        }
        result = {}
        for canonical, keys in aliases.items():
            values: "List[Any]" = []
            for source in (metadata, scope or {}):
                values.extend(
                    (key, source[key]) for key in keys if source.get(key) not in (None, "")
                )
            value = values[0][1] if values else None
            if values and any(item[1] != value for item in values[1:]):
                raise OptionAccountingError(
                    "option_metadata_scope_alias_conflict",
                    "option_metadata_scope_alias_conflict: contradictory scope aliases",
                )
            if value not in (None, ""):
                result[canonical] = value
        return result

    @classmethod
    def _metadata_option_fee_rate(cls, metadata, *keys):
        """Read only the option's explicit ByMoney fee dimension."""
        return cls._metadata_option_fee_dimension(metadata, keys)

    @classmethod
    def _metadata_option_fee_amount(cls, metadata, *keys):
        """Read only the option's explicit ByVolume fee dimension."""
        return cls._metadata_option_fee_dimension(metadata, keys)

    @classmethod
    def _metadata_option_fee_dimension(cls, metadata, keys):
        """Read a CTP option fee dimension without changing its wire units."""
        key_text = " ".join(str(key).lower() for key in keys)
        if "close_today" in key_text or "closetoday" in key_text:
            code = "option_fee_close_today_invalid"
        elif "close_yesterday" in key_text or "closeyesterday" in key_text:
            code = "option_fee_close_yesterday_invalid"
        elif "close" in key_text:
            code = "option_fee_close_invalid"
        else:
            code = "option_fee_open_invalid"
        values = [(key, metadata.get(key)) for key in keys if metadata.get(key) not in (None, "")]
        if not values:
            return None
        numbers = []
        for key, value in values:
            if isinstance(value, bool):
                raise OptionAccountingError(
                    code,
                    f"{code}: {key} must be a finite non-negative number",
                )
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                _safe_log("error", "btapibroker:4744 re-raising TypeError,ValueError")
                raise OptionAccountingError(
                    code,
                    f"{code}: {key} must be a finite non-negative number",
                ) from exc
            if not math.isfinite(number) or number < 0.0:
                raise OptionAccountingError(
                    code,
                    f"{code}: {key} must be a finite non-negative number",
                )
            numbers.append((key, number))
        first = numbers[0][1]
        if any(number != first for _, number in numbers[1:]):
            raise OptionAccountingError(
                code,
                f"{code}: contradictory fee aliases",
            )
        return first

    @classmethod
    def _metadata_option_multiplier(cls, metadata):
        """Resolve one finite positive option multiplier without coercing bools."""
        keys = (
            "multiplier",
            "mult",
            "contract_multiplier",
            "contract_size",
            "VolumeMultiple",
        )
        values = [(key, metadata.get(key)) for key in keys if metadata.get(key) not in (None, "")]
        if not values:
            raise OptionAccountingError(
                "option_multiplier_missing",
                "option_multiplier_missing: explicit option multiplier is required",
            )
        numbers = []
        for key, value in values:
            if isinstance(value, bool):
                raise OptionAccountingError(
                    "option_multiplier_invalid",
                    f"option_multiplier_invalid: {key} must be positive and finite",
                )
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                _safe_log("error", "btapibroker:4788 re-raising TypeError,ValueError")
                raise OptionAccountingError(
                    "option_multiplier_invalid",
                    f"option_multiplier_invalid: {key} must be positive and finite",
                ) from exc
            if not math.isfinite(number) or number <= 0.0:
                raise OptionAccountingError(
                    "option_multiplier_invalid",
                    f"option_multiplier_invalid: {key} must be positive and finite",
                )
            numbers.append((key, number))
        first = numbers[0][1]
        if any(number != first for _, number in numbers[1:]):
            raise OptionAccountingError(
                "option_multiplier_conflict",
                "option_multiplier_conflict: contradictory multiplier aliases",
            )
        return first

    @classmethod
    def _metadata_to_comminfo(cls, metadata):
        """Build a Backtrader comminfo object from normalized contract metadata."""
        if not metadata:
            return None
        if cls._metadata_is_option(metadata):
            style = cls._metadata_text(
                metadata,
                "premium_style",
                "premiumStyle",
                "settlement_style",
                "option_settlement_style",
                "option_style",
            )
            multiplier = cls._metadata_option_multiplier(metadata)
            seller_evidence = metadata.get("seller_margin_evidence")
            if seller_evidence is None:
                seller_evidence = metadata.get("seller_total_margin_evidence")
            return CtpOptionPremium(
                mult=multiplier,
                premium_style=style or None,
                option_type=cls._metadata_option_type_text(metadata) or None,
                open_commission_by_money=cls._metadata_option_fee_rate(
                    metadata,
                    "open_commission_by_money",
                    "open_fee_rate",
                    "open_commission_rate",
                    "OpenRatioByMoney",
                    "COMMISSION_OPEN_RATIO",
                ),
                open_commission_by_volume=cls._metadata_option_fee_amount(
                    metadata,
                    "open_commission_by_volume",
                    "open_fee_amount",
                    "open_commission_amount",
                    "OpenRatioByVolume",
                    "COMMISSION_OPEN_AMOUNT",
                ),
                close_commission_by_money=cls._metadata_option_fee_rate(
                    metadata,
                    "close_commission_by_money",
                    "close_fee_rate",
                    "close_commission_rate",
                    "CloseRatioByMoney",
                    "COMMISSION_CLOSE_RATIO",
                ),
                close_commission_by_volume=cls._metadata_option_fee_amount(
                    metadata,
                    "close_commission_by_volume",
                    "close_fee_amount",
                    "close_commission_amount",
                    "CloseRatioByVolume",
                    "COMMISSION_CLOSE_AMOUNT",
                ),
                close_today_commission_by_money=cls._metadata_option_fee_rate(
                    metadata,
                    "close_today_commission_by_money",
                    "close_today_fee_rate",
                    "close_today_commission_rate",
                    "CloseTodayRatioByMoney",
                    "COMMISSION_CLOSE_TODAY_RATIO",
                ),
                close_today_commission_by_volume=cls._metadata_option_fee_amount(
                    metadata,
                    "close_today_commission_by_volume",
                    "close_today_fee_amount",
                    "close_today_commission_amount",
                    "CloseTodayRatioByVolume",
                    "COMMISSION_CLOSE_TODAY_AMOUNT",
                ),
                close_yesterday_commission_by_money=cls._metadata_option_fee_rate(
                    metadata,
                    "close_yesterday_commission_by_money",
                    "close_yesterday_fee_rate",
                    "close_yesterday_commission_rate",
                    "CloseYesterdayRatioByMoney",
                    "COMMISSION_CLOSE_YESTERDAY_RATIO",
                ),
                close_yesterday_commission_by_volume=cls._metadata_option_fee_amount(
                    metadata,
                    "close_yesterday_commission_by_volume",
                    "close_yesterday_fee_amount",
                    "close_yesterday_commission_amount",
                    "CloseYesterdayRatioByVolume",
                    "COMMISSION_CLOSE_YESTERDAY_AMOUNT",
                ),
                seller_margin_evidence=seller_evidence,
                evidence_scope=cls._metadata_option_scope(metadata),
            )
        inverse_contract = cls._metadata_is_inverse_contract(metadata)
        multiplier_values = (
            (
                metadata.get("contract_value"),
                metadata.get("contractValue"),
                metadata.get("contract_value_amount"),
                metadata.get("contractValueAmount"),
                metadata.get("ctVal"),
                metadata.get("ct_value"),
                metadata.get("multiplier"),
                metadata.get("mult"),
                metadata.get("contract_multiplier"),
                metadata.get("contract_size"),
                metadata.get("ctMult"),
                metadata.get("VolumeMultiple"),
            )
            if inverse_contract
            else (
                metadata.get("multiplier"),
                metadata.get("mult"),
                metadata.get("contract_multiplier"),
                metadata.get("contract_size"),
                metadata.get("contract_value"),
                metadata.get("contractValue"),
                metadata.get("ctVal"),
                metadata.get("ctMult"),
                metadata.get("VolumeMultiple"),
            )
        )
        multiplier = cls._first_number(*multiplier_values, default=1.0)
        margin_value = cls._first_number(
            metadata.get("margin"),
            metadata.get("margin_rate"),
            metadata.get("margin_ratio"),
            metadata.get("long_margin_rate"),
            metadata.get("LongMarginRatioByMoney"),
            metadata.get("MARGIN_BUY"),
        )
        margin_amount = cls._first_number(
            metadata.get("margin_amount"),
            metadata.get("initial_margin_per_lot"),
            metadata.get("margin_initial"),
            metadata.get("initial_margin_amount"),
            metadata.get("SYMBOL_MARGIN_INITIAL"),
        )
        leverage = cls._first_number(
            metadata.get("leverage"),
            metadata.get("lever"),
            metadata.get("max_leverage"),
        )
        margin_rate = (
            1.0 / leverage if leverage and leverage > 0 else cls._normalise_rate(margin_value, 1.0)
        )
        margin_amount_param = (
            max(margin_amount, 0.0) if margin_amount is not None and margin_amount > 0 else None
        )
        commission_rate = cls._metadata_open_commission_rate(metadata)
        close_commission_rate = cls._metadata_close_commission_rate(metadata)
        close_today_commission_rate = cls._metadata_close_today_commission_rate(metadata)
        close_yesterday_commission_rate = cls._metadata_close_yesterday_commission_rate(metadata)
        maker_commission_rate = cls._metadata_maker_commission_rate(metadata)
        taker_commission_rate = cls._metadata_taker_commission_rate(metadata)
        if commission_rate is None:
            commission_rate = (
                taker_commission_rate
                if taker_commission_rate is not None
                else maker_commission_rate
            )
        commission_amount = cls._metadata_open_commission_amount(metadata)
        close_commission_amount = cls._metadata_close_commission_amount(metadata)
        close_today_commission_amount = cls._metadata_close_today_commission_amount(metadata)
        close_yesterday_commission_amount = cls._metadata_close_yesterday_commission_amount(
            metadata
        )
        commission_method = str(metadata.get("commission_method") or "").strip().lower()
        has_commission_amount = any(
            value is not None
            for value in (
                commission_amount,
                close_commission_amount,
                close_today_commission_amount,
                close_yesterday_commission_amount,
            )
        )
        has_commission_rate = any(
            value is not None
            for value in (
                commission_rate,
                close_commission_rate,
                close_today_commission_rate,
                close_yesterday_commission_rate,
                maker_commission_rate,
                taker_commission_rate,
            )
        )
        if inverse_contract:
            return ComminfoFuturesInverse(
                commission=commission_rate if commission_rate is not None else 0.0,
                open_commission=commission_rate,
                close_commission=close_commission_rate,
                close_today_commission=close_today_commission_rate,
                close_yesterday_commission=close_yesterday_commission_rate,
                maker_commission=maker_commission_rate,
                taker_commission=taker_commission_rate,
                commission_amount=max(commission_amount or 0.0, 0.0),
                open_commission_amount=(
                    max(commission_amount, 0.0) if commission_amount is not None else None
                ),
                close_commission_amount=(
                    max(close_commission_amount, 0.0)
                    if close_commission_amount is not None
                    else None
                ),
                close_today_commission_amount=(
                    max(close_today_commission_amount, 0.0)
                    if close_today_commission_amount is not None
                    else None
                ),
                close_yesterday_commission_amount=(
                    max(close_yesterday_commission_amount, 0.0)
                    if close_yesterday_commission_amount is not None
                    else None
                ),
                margin=max(margin_rate, 0.0),
                margin_amount=margin_amount_param,
                mult=max(multiplier or 1.0, 1e-12),
            )
        if has_commission_amount and commission_method != "fixed_per_lot" and has_commission_rate:
            return ComminfoFuturesMixed(
                commission=commission_rate if commission_rate is not None else 0.0,
                open_commission=commission_rate,
                close_commission=close_commission_rate,
                close_today_commission=close_today_commission_rate,
                close_yesterday_commission=close_yesterday_commission_rate,
                maker_commission=maker_commission_rate,
                taker_commission=taker_commission_rate,
                commission_amount=max(commission_amount or 0.0, 0.0),
                open_commission_amount=(
                    max(commission_amount, 0.0) if commission_amount is not None else None
                ),
                close_commission_amount=(
                    max(close_commission_amount, 0.0)
                    if close_commission_amount is not None
                    else None
                ),
                close_today_commission_amount=(
                    max(close_today_commission_amount, 0.0)
                    if close_today_commission_amount is not None
                    else None
                ),
                close_yesterday_commission_amount=(
                    max(close_yesterday_commission_amount, 0.0)
                    if close_yesterday_commission_amount is not None
                    else None
                ),
                margin=max(margin_rate, 0.0),
                margin_amount=margin_amount_param,
                mult=max(multiplier or 1.0, 1e-12),
            )
        if commission_amount is not None and (
            commission_method == "fixed_per_lot" or not has_commission_rate
        ):
            return ComminfoFuturesFixed(
                commission=max(commission_amount, 0.0),
                open_commission=max(commission_amount, 0.0),
                close_commission=(
                    max(close_commission_amount, 0.0)
                    if close_commission_amount is not None
                    else None
                ),
                close_today_commission=(
                    max(close_today_commission_amount, 0.0)
                    if close_today_commission_amount is not None
                    else None
                ),
                close_yesterday_commission=(
                    max(close_yesterday_commission_amount, 0.0)
                    if close_yesterday_commission_amount is not None
                    else None
                ),
                margin=max(margin_rate, 0.0),
                margin_amount=margin_amount_param,
                mult=max(multiplier or 1.0, 1e-12),
            )
        return ComminfoFuturesPercent(
            commission=commission_rate if commission_rate is not None else 0.0,
            open_commission=commission_rate,
            close_commission=close_commission_rate,
            close_today_commission=close_today_commission_rate,
            close_yesterday_commission=close_yesterday_commission_rate,
            maker_commission=maker_commission_rate,
            taker_commission=taker_commission_rate,
            margin=max(margin_rate, 0.0),
            margin_amount=margin_amount_param,
            mult=max(multiplier or 1.0, 1e-12),
        )

    def getcommissioninfo(self, data):
        """Return symbol-specific comminfo, deriving it from contract metadata if needed."""
        for name in self._commission_lookup_keys(data):
            if name in self.comminfo:
                return self.comminfo[name]

        data_name = self._position_key(data)
        comminfo = self._metadata_to_comminfo(self._contract_rules_for(data_name))
        if comminfo is not None:
            self.addcommissioninfo(comminfo, name=data_name)
            return comminfo
        return super().getcommissioninfo(data)

    @staticmethod
    def _strict_option_input_number(value, code, *, integer=False, positive=True):
        """Validate one raw CTP option order/fill number before normalization."""
        if isinstance(value, bool):
            raise OptionAccountingError(code, f"{code}: boolean is not a numeric value")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            _safe_log("error", "btapibroker:5113 re-raising TypeError,ValueError")
            raise OptionAccountingError(code, f"{code}: expected a finite numeric value") from exc
        if not math.isfinite(number) or (positive and number <= 0.0):
            raise OptionAccountingError(code, f"{code}: expected a positive finite number")
        if integer and not number.is_integer():
            raise OptionAccountingError(
                code, f"{code}: CTP option quantity must be whole contracts"
            )
        return number

    def _option_comminfo_for_order(self, order):
        """Resolve an option comminfo while keeping validation errors explicit."""
        try:
            comminfo = order.comminfo or self.getcommissioninfo(order.data)
        except OptionAccountingError as exc:
            return None, (exc.code, str(exc))
        return comminfo, None

    @staticmethod
    def _raw_order_input(order, name):
        missing = object()
        value = getattr(order, f"_btapi_raw_order_{name}", missing)
        if value is not missing:
            return value
        return getattr(order, name, None)

    def _validate_option_order_inputs(self, order):
        """Reject malformed option order inputs before OrderBase conversions."""
        comminfo, error = self._option_comminfo_for_order(order)
        if error is not None:
            return error
        if not isinstance(comminfo, CtpOptionPremium):
            return None

        try:
            size = self._strict_option_input_number(
                self._raw_order_input(order, "size"),
                "option_order_size_invalid",
                integer=True,
                positive=False,
            )
            if size == 0.0:
                raise OptionAccountingError(
                    "option_order_size_invalid",
                    "option_order_size_invalid: order quantity must be non-zero",
                )
            raw_price = self._raw_order_input(order, "price")
            if raw_price not in (None, ""):
                self._strict_option_input_number(raw_price, "option_order_price_invalid")
        except OptionAccountingError as exc:
            return exc.code, str(exc)
        return None

    def _validate_option_seller_capability(self, order):
        """Enforce the trusted SDK seller-margin capability for opening shorts."""
        comminfo, error = self._option_comminfo_for_order(order)
        if error is not None:
            return error
        if not isinstance(comminfo, CtpOptionPremium) or order.isbuy():
            return None
        try:
            opening_size = self._opening_size_for_order(order)
        except (TypeError, ValueError) as exc:
            return "option_order_size_invalid", f"option_order_size_invalid: {exc}"
        if opening_size <= 0.0:
            return None
        return (
            "option_seller_margin_blocked",
            "Seller option orders require a trusted SDK total-margin issuer; "
            f"current evidence status is {comminfo.seller_margin_status()}",
        )

    def _validate_option_order_fee(self, order):
        """Require the complete fee pair for the order's actual CTP offset."""
        comminfo, error = self._option_comminfo_for_order(order)
        if error is not None:
            return error
        if not isinstance(comminfo, CtpOptionPremium):
            return None
        offset = self._order_info_get(order, "offset")
        role, offset_error = self._option_fee_role(offset)
        if offset_error is not None:
            return offset_error
        try:
            comminfo._fee_pair(role)
        except OptionAccountingError as exc:
            return exc.code, str(exc)
        return None

    @staticmethod
    def _option_fee_role(offset):
        """Resolve the exact option fee role without treating unknown offsets as close."""
        if offset is None:
            return "open", None
        try:
            offset_text = str(offset).strip().lower().replace("-", "_")
        except Exception:
            _safe_log("warning", "btapibroker:5220 fallback on Exception")
            return None, (
                "option_offset_unknown",
                "option_offset_unknown: CTP option offset is not a recognized value",
            )
        if not offset_text:
            return "open", None
        role_aliases = {
            "open": "open",
            "close": "close",
            "close_today": "close_today",
            "closetoday": "close_today",
            "close_yesterday": "close_yesterday",
            "closeyesterday": "close_yesterday",
        }
        role = role_aliases.get(offset_text)
        if role is None:
            return None, (
                "option_offset_unknown",
                f"option_offset_unknown: unsupported CTP option offset {offset!r}",
            )
        return role, None

    def _validate_order(self, order):
        """Run lightweight local validation before the order reaches the store."""
        option_input_error = self._validate_option_order_inputs(order)
        if option_input_error is not None:
            return option_input_error
        seller_capability_error = self._validate_option_seller_capability(order)
        if seller_capability_error is not None:
            return seller_capability_error
        option_fee_error = self._validate_option_order_fee(order)
        if option_fee_error is not None:
            return option_fee_error
        if self._requires_explicit_offset(order.data) and self._order_type_name(order) != "limit":
            return (
                "unsupported_order_type",
                "CTP orders require an explicit limit price and cannot use Market execution",
            )
        if not bool(self.p.validation_enabled):
            return None

        data_name = self._position_key(order.data)
        rules = self._contract_rules_for(data_name)
        size_error = self._validate_order_size(
            order,
            rules,
            default_max_order_size=self.p.max_order_size,
        )
        if size_error is not None:
            return size_error

        if rules.get("valid") is False or rules.get("exists") is False:
            return "invalid_contract", f"Contract {data_name} is not valid for trading"

        if rules.get("tradable") is False:
            return "contract_not_tradable", f"Contract {data_name} is currently not tradable"

        type_error = self._validate_order_type(order, rules)
        if type_error is not None:
            return type_error

        tif_error = self._validate_time_in_force(order)
        if tif_error is not None:
            return tif_error

        if self._is_dual_side_mode() and self._order_info_get(order, "offset") in {
            "close",
            "close_today",
            "close_yesterday",
        }:
            position_side = normalize_position_side(self._order_info_get(order, "position_side"))
            available = abs(float(self._get_leg_position(order.data, position_side).size or 0.0))
            requested = abs(float(order.size or 0.0))
            if requested > available + 1e-12:
                return (
                    "insufficient_position_to_close",
                    "Close order size exceeds the available leg position",
                )

        min_price_tick = (
            rules.get("min_price_tick") or rules.get("price_tick") or rules.get("tick_size")
        )
        price = order.price if order.price is not None else getattr(order.created, "price", None)
        if min_price_tick and price not in (None, 0):
            tick = float(min_price_tick)
            scaled = float(price) / tick
            # Same degenerate-metadata guard as the size step check above.
            if math.isfinite(scaled) and abs(round(scaled) - scaled) > 1e-9:
                return (
                    "invalid_price_tick",
                    f"Order price {price} does not align with tick size {tick}",
                )

        cash_error = self._validate_order_cash(order, rules)
        if cash_error is not None:
            return cash_error

        return None

    def _validate_time_in_force(self, order):
        """Freeze the first CTP strategy contract to explicit GFD orders."""
        if not self._requires_explicit_offset(order.data):
            return None
        value = self._order_info_get(order, "time_in_force")
        if value in (None, ""):
            order.addinfo(time_in_force="GFD")
            return None
        normalized = str(value).strip().upper().replace("-", "_")
        if normalized not in {"GFD", "GOOD_FOR_DAY"}:
            return (
                "unsupported_time_in_force",
                f"CTP first-version orders require GFD; received {normalized or '<unknown>'}",
            )
        order.addinfo(time_in_force="GFD")
        return None

    @classmethod
    def _metadata_size_rule(cls, rules, *keys, default=None):
        return cls._first_number(*(rules.get(key) for key in keys), default=default)

    @classmethod
    def _validate_order_size(cls, order, rules, default_max_order_size=0):
        """Validate order quantity against exchange/local lot-size rules."""
        requested = abs(float(order.size or 0.0))
        if requested <= 0.0:
            return "invalid_order_size", "Order size must be positive"

        min_order_size = cls._metadata_size_rule(
            rules,
            "min_order_size",
            "min_order_qty",
            "min_size",
            "min_qty",
            "minQty",
            "minSz",
            "min_volume",
            "volume_min",
            "min_lot",
            "lot_min",
            "SYMBOL_VOLUME_MIN",
        )
        if min_order_size and requested + 1e-12 < min_order_size:
            return (
                "min_order_size_not_met",
                f"Order size {order.size} is below the minimum allowed size {min_order_size}",
            )

        step = cls._metadata_size_rule(
            rules,
            "order_size_step",
            "lot_size",
            "size_step",
            "qty_step",
            "qty_unit",
            "quantity_step",
            "volume_step",
            "lot_step",
            "step_size",
            "stepSize",
            "lotSz",
            "SYMBOL_VOLUME_STEP",
        )
        if step and step > 0:
            scaled = requested / step
            # Degenerate metadata (uninitialized CTP struct reads can yield
            # ~1e-314 steps) produces an infinite scale; treat it as absent
            # instead of raising OverflowError in round().
            if math.isfinite(scaled) and abs(round(scaled) - scaled) > 1e-9:
                return (
                    "invalid_order_size_step",
                    f"Order size {order.size} does not align with size step {step}",
                )

        order_type = cls._order_type_name(order)
        max_order_size = None
        if order_type == "market":
            max_order_size = cls._metadata_size_rule(
                rules,
                "market_max_order_size",
                "max_market_order_size",
                "max_mkt_order_size",
                "maxMktSz",
            )
        elif order_type == "limit":
            max_order_size = cls._metadata_size_rule(
                rules,
                "limit_max_order_size",
                "max_limit_order_size",
                "max_lmt_order_size",
                "maxLmtSz",
            )
        if max_order_size is None:
            max_order_size = cls._metadata_size_rule(
                rules,
                "max_order_size",
                "max_order_qty",
                "max_size",
                "max_qty",
                "maxQty",
                "max_volume",
                "volume_max",
                "max_lot",
                "lot_max",
                "SYMBOL_VOLUME_MAX",
                default=default_max_order_size,
            )
        if max_order_size and requested > max_order_size + 1e-12:
            return (
                "max_order_size_exceeded",
                f"Order size {order.size} exceeds the max allowed size {max_order_size}",
            )

        return None

    @staticmethod
    def _order_type_name(order):
        try:
            return str(order.getordername() or "").strip().lower()
        except Exception:
            _safe_log("warning", "btapibroker:5439 fallback on Exception")
            return ""

    def _supported_order_types_for(self, order, rules):
        configured = rules.get("supported_order_types") or rules.get("order_types")
        if isinstance(configured, str):
            configured = [item.strip() for item in configured.split(",")]
        if configured:
            return {str(item or "").strip().lower() for item in configured if item}
        if self._requires_explicit_offset(order.data):
            return {"limit"}
        return None

    def _validate_order_type(self, order, rules):
        """Reject order execution types that the live venue cannot represent."""
        order_type = self._order_type_name(order)
        supported = self._supported_order_types_for(order, rules)
        if supported is not None and order_type not in supported:
            return (
                "unsupported_order_type",
                f"Order type {order_type or '<unknown>'} is not supported by this live broker",
            )
        return None

    def _opening_size_for_order(self, order):
        """Return the portion of an order that opens or increases exposure."""
        requested = abs(float(order.size or 0.0))
        if requested <= 0.0:
            return 0.0

        offset = self._order_info_get(order, "offset")
        if offset in {"close", "close_today", "close_yesterday"}:
            return 0.0

        if self._is_dual_side_mode():
            return requested

        position = self.getposition(order.data, clone=False)
        current_size = float(position.size or 0.0)
        if order.isbuy():
            return max(requested - abs(current_size), 0.0) if current_size < 0.0 else requested
        return max(requested - current_size, 0.0) if current_size > 0.0 else requested

    def _order_price_for_risk(self, order, rules):
        """Resolve a usable price for cash and margin checks."""
        price = self._first_number(
            getattr(order, "price", None),
            getattr(getattr(order, "created", None), "price", None),
            getattr(getattr(order, "created", None), "pricelimit", None),
            rules.get("current_price"),
            rules.get("latest_price"),
            rules.get("last_price"),
            rules.get("mark_price"),
        )
        if price and price > 0:
            return price

        close = getattr(getattr(order, "data", None), "close", None)
        if close is not None:
            try:
                price = float(close[0])
            except Exception:
                _safe_log("warning", "btapibroker:5500 fallback on Exception")
                price = 0.0
            if price > 0:
                return price
        return None

    def _option_safety_factor(self, rules):
        """Return a conservative option cash factor and reject bad config."""
        values = []
        for key in ("cash_check_safety_factor", "margin_safety_factor"):
            value = rules.get(key) if isinstance(rules, Mapping) else None
            if value not in (None, ""):
                values.append((key, value))
        if not values:
            values.append(("cash_check_safety_factor", self.p.cash_check_safety_factor))

        numbers = []
        for key, value in values:
            if isinstance(value, bool):
                return None, (
                    "option_safety_factor_invalid",
                    f"option_safety_factor_invalid: {key} must be finite and numeric",
                )
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None, (
                    "option_safety_factor_invalid",
                    f"option_safety_factor_invalid: {key} must be finite and numeric",
                )
            if not math.isfinite(number):
                return None, (
                    "option_safety_factor_invalid",
                    f"option_safety_factor_invalid: {key} must be finite and numeric",
                )
            numbers.append((key, number))
        first = numbers[0][1]
        if any(number != first for _, number in numbers[1:]):
            return None, (
                "option_safety_factor_conflict",
                "option_safety_factor_conflict: contradictory safety factor aliases",
            )
        # A factor below one can only erase a known obligation.  Clamp it to
        # the conservative floor while preserving the legacy non-option path.
        return max(first, 1.0), None

    def _validate_order_cash(self, order, rules):
        """Reject opening orders whose required cash or margin is unavailable."""
        opening_size = self._opening_size_for_order(order)
        if opening_size <= 0.0:
            return None

        try:
            comminfo = self.getcommissioninfo(order.data)
        except OptionAccountingError as exc:
            return exc.code, str(exc)

        # No current public SDK contract proves account-bound seller total
        # margin.  This capability gate must run before the optional cash
        # check so configuration cannot turn a seller opening into a write.
        if isinstance(comminfo, CtpOptionPremium) and not order.isbuy():
            return (
                "option_seller_margin_blocked",
                "Seller option orders require a trusted SDK total-margin issuer; "
                f"current evidence status is {comminfo.seller_margin_status()}",
            )

        if not bool(rules.get("cash_check_enabled", self.p.cash_check_enabled)):
            return None

        force_refresh = bool(self.p.force_refresh_queries)
        if bool(getattr(self.store, "_sdk_mode", False)):
            if self._uses_async_commands():
                cached_balance = getattr(self.store, "get_cached_venue_balance", None)
                if not callable(cached_balance):
                    return (
                        "account_cache_unavailable",
                        "Opening order requires a preflighted local account cache",
                    )
                try:
                    venue_balance = cached_balance(self._position_key(order.data))
                except Exception:
                    _safe_log("warning", "btapibroker:5581 fallback on Exception")
                    return (
                        "account_cache_unavailable",
                        "Opening order requires a preflighted local account cache",
                    )
            else:
                venue_balance = self.store.get_venue_balance(
                    self._position_key(order.data),
                    force=force_refresh,
                )
            available_cash = self._first_number(
                venue_balance.get("cash") if isinstance(venue_balance, Mapping) else None,
                default=None if isinstance(comminfo, CtpOptionPremium) else 0.0,
            )
        else:
            self._refresh_account(force=force_refresh, raise_errors=True)
            available_cash = self._first_number(
                self._cash,
                default=None if isinstance(comminfo, CtpOptionPremium) else 0.0,
            )

        if isinstance(comminfo, CtpOptionPremium) and available_cash is None:
            return (
                "option_cash_invalid",
                "Option order requires a finite authoritative account cash snapshot",
            )

        price = self._order_price_for_risk(order, rules)
        if price is None:
            return (
                "risk_price_unavailable",
                "Opening order requires a current price for cash/margin validation",
            )

        try:
            if comminfo is None:
                return None

            if isinstance(comminfo, CtpOptionPremium):
                is_buy = bool(order.isbuy())
                required = float(
                    comminfo.getoperationcost(opening_size, price, is_buy=is_buy) or 0.0
                )
                required += float(comminfo.getcommission(opening_size, price, role="open") or 0.0)
            else:
                required = float(comminfo.getoperationcost(opening_size, price) or 0.0)
                required += float(comminfo.getcommission(opening_size, price, role="open") or 0.0)
        except OptionAccountingError as exc:
            return exc.code, str(exc)
        if not math.isfinite(required):
            return (
                (
                    "option_required_invalid"
                    if isinstance(comminfo, CtpOptionPremium)
                    else "required_invalid"
                ),
                "Order cash/margin requirement is not finite",
            )
        if isinstance(comminfo, CtpOptionPremium):
            safety_factor, safety_error = self._option_safety_factor(rules)
            if safety_error is not None:
                return safety_error
        else:
            safety_factor = self._first_number(
                rules.get("cash_check_safety_factor"),
                rules.get("margin_safety_factor"),
                self.p.cash_check_safety_factor,
                default=1.0,
            )
        required *= safety_factor
        if not math.isfinite(required):
            return (
                (
                    "option_required_invalid"
                    if isinstance(comminfo, CtpOptionPremium)
                    else "required_invalid"
                ),
                "Order cash/margin requirement is not finite",
            )
        cash_buffer = self._first_number(
            rules.get("cash_buffer"),
            rules.get("min_cash_buffer"),
            self.p.cash_buffer,
            default=0.0,
        )
        available = max(float(available_cash or 0.0) - max(cash_buffer or 0.0, 0.0), 0.0)
        if not math.isfinite(available):
            return (
                "option_cash_invalid" if isinstance(comminfo, CtpOptionPremium) else "cash_invalid",
                "Available account cash is not finite",
            )
        if required > available + 1e-12:
            return (
                "insufficient_cash",
                "Order requires "
                f"{required:.2f} cash/margin but only {available:.2f} is available",
            )
        return None

    def _reject_order(self, order, error_code, error_msg):
        """Reject an order locally and emit a structured runtime event."""
        self._abort_recovery_dispatch(order, "execution_recovery_dispatch_failed")
        error_code = str(self._redact_runtime_value(error_code))
        error_msg = str(self._redact_runtime_value(error_msg))
        order.addinfo(error_code=error_code, error_msg=error_msg)
        order.reject(self)
        self.orders[order.ref] = order
        self.notify(order)
        details = {
            "data_name": self._position_key(order.data),
            "side": "buy" if order.isbuy() else "sell",
            "size": abs(float(order.size or 0.0)),
            "price": (
                order.price if order.price is not None else getattr(order.created, "price", None)
            ),
        }
        self._emit_runtime_event(
            "order_reject_local",
            level="ERROR",
            order_ref=order.ref,
            error_code=error_code,
            error_msg=error_msg,
            status="rejected",
            details=details,
        )
        self._emit_runtime_event(
            "order_validation_rejected",
            level="ERROR",
            order_ref=order.ref,
            error_code=error_code,
            error_msg=error_msg,
            status="rejected",
            details=details,
        )
        return order

    @classmethod
    def _attach_remote_error_code(cls, order, response):
        """Retain the SDK's specific code alongside the broker's generic code."""
        result = cls._unwrap_submit_response(response)
        if isinstance(result, dict) and result.get("error_code") not in (None, ""):
            order.addinfo(remote_error_code=str(result["error_code"]))

    @classmethod
    def _submit_response_error(cls, response):
        """Return a structured error when a submit response is not confirmed."""
        result = cls._unwrap_submit_response(response)
        if result is None:
            return "remote_submit_rejected", "empty remote submit response"
        if not isinstance(result, dict):
            return cls._non_mapping_submit_response_error(result)
        if not result:
            return "remote_submit_rejected", "empty remote submit response"
        if result.get("kind") == "managed_execution_projection":
            # Exact shape/state echoes were already checked by the typed
            # parser in submit(); these non-provider projections never enter
            # generic remote ACK/rejection inference.
            return None
        if result.get("execution_unknown") is True:
            return None

        status = str(result.get("status") or result.get("order_status") or "").strip().lower()
        if status in {
            "error",
            "failed",
            "fail",
            "rejected",
            "reject",
        }:
            return "remote_submit_rejected", cls._submit_response_message(
                result, f"remote order status: {status}"
            )
        if status in {
            "ok",
            "success",
            "submitted",
            "accepted",
            "completed",
            "complete",
            "partial",
            "filled",
            "open",
            "placed",
            "cancelled",
            "canceled",
            "expired",
        }:
            return None

        retcode = result.get("retcode") or result.get("ret_code")
        if retcode not in (None, ""):
            try:
                retcode_int = int(retcode)
            except (TypeError, ValueError):
                retcode_int = None
            if retcode_int in {10008, 10009, 10010}:
                return None
            if retcode_int in {
                10004,
                10006,
                10007,
                10013,
                10014,
                10015,
                10016,
                10017,
                10018,
                10019,
                10030,
                10031,
            }:
                return "remote_submit_rejected", cls._submit_response_message(
                    result,
                    f"remote retcode: {retcode}",
                )

        code = result.get("code")
        if code not in (None, "", 0, "0"):
            return "remote_submit_rejected", cls._submit_response_message(
                result,
                f"remote code: {code}",
            )

        success_value = result.get("success")
        if isinstance(success_value, bool):
            if success_value:
                return None
            return "remote_submit_rejected", cls._submit_response_message(
                result,
                "remote submit success flag is false",
            )
        if cls._submit_response_has_identity(result):
            return None
        return "remote_submit_rejected", "invalid remote submit response"

    def _managed_execution_replay_projection_error(self, response, order):
        """Block a durable replay from becoming a second framework execution.

        A durable execution record alone proves a provider dispatch, not
        permission to mutate the current in-memory Broker.  A fully composed
        direct managed runtime may supply a live, private framework receipt;
        that narrow recovery path is checked below.  Every other replay is
        rejected, because applying its cumulative fill could book a second
        local position/commission event.  Direct first-dispatch responses have
        no replay marker and continue through the ordinary fill path.
        """

        result = self._unwrap_submit_response(response)
        if not isinstance(result, Mapping) or result.get("managed_execution_replayed") is not True:
            return None
        if self._managed_framework_projection_active(result, order):
            return None
        state = str(result.get("managed_execution_state") or "CONFIRMED").strip().upper()
        return (
            "managed_execution_projection_replay_blocked",
            "Managed execution {0} was recovered from durable state; "
            "framework fill projection requires an audited recovery receipt.".format(state),
        )

    def _managed_framework_projection_active(self, response, order):
        """Return a bridge-validated fill-recovery receipt, never a raw flag."""

        if not isinstance(response, Mapping) or self.store is None:
            return False
        validate = getattr(self.store, "validate_managed_framework_projection", None)
        if not callable(validate):
            return False
        try:
            return validate(response, order) is True
        except Exception as exc:
            _safe_log("warning", "btapibroker:managed framework projection receipt invalid")
            self._sanitize_exception(exc)
            return False

    @staticmethod
    def _non_mapping_submit_response_error(result):
        if isinstance(result, bool):
            return "remote_submit_rejected", "invalid remote submit response"
        if isinstance(result, str):
            if result.strip():
                return None
            return "remote_submit_rejected", "empty remote submit response"
        if isinstance(result, (int, float)):
            if result != 0:
                return None
            return "remote_submit_rejected", "invalid remote submit response"
        return "remote_submit_rejected", "invalid remote submit response"

    @staticmethod
    def _submit_response_has_identity(result):
        for key in (
            "id",
            "order_id",
            "orderId",
            "OrderID",
            "ordId",
            "external_order_id",
            "externalOrderId",
            "venue_order_id",
            "venueOrderId",
            "order_ref",
            "orderRef",
            "OrderRef",
            "client_order_id",
            "clientOrderId",
            "newClientOrderId",
            "origClientOrderId",
            "clOrdId",
            "origClOrdId",
            "orderLinkId",
            "origOrderLinkId",
            "ticket",
            "order",
            "deal",
            "deal_id",
            "dealId",
            "DealID",
        ):
            if result.get(key) not in (None, ""):
                return True
        return False

    @staticmethod
    def _unwrap_submit_response(response):
        current = response
        for _ in range(5):
            if isinstance(current, (list, tuple)):
                if len(current) == 1 and isinstance(current[0], dict):
                    current = current[0]
                    continue
                return current
            if not isinstance(current, dict):
                return current
            status = str(current.get("status") or "").strip().lower()
            code = str(current.get("code") or "").strip()
            success = current.get("success")
            wrapper_ok = status in {"ok", "success"} or code in {"0", "00000"} or success is True
            if wrapper_ok:
                nested = current.get("data", current.get("result"))
                if isinstance(nested, dict):
                    current = nested
                    continue
                if (
                    isinstance(nested, (list, tuple))
                    and len(nested) == 1
                    and isinstance(nested[0], dict)
                ):
                    current = nested[0]
                    continue
            return current
        return current

    @staticmethod
    def _submit_response_message(result, fallback):
        return str(
            result.get("retcode_external")
            or result.get("comment")
            or result.get("message")
            or result.get("error")
            or result.get("reason")
            or fallback
        )

    def _requires_explicit_offset(self, data):
        """Return whether the provider needs open/close offset metadata."""
        provider_values = {
            str(self.provider or "").strip().lower(),
            (
                str(getattr(self.store, "provider", "") or "").strip().lower()
                if self.store is not None
                else ""
            ),
        }
        if provider_values & {"ctp", "ctp_gateway"}:
            return True

        config_values = []
        if self.store is not None:
            config_values.extend(
                [
                    getattr(self.store, "_config", {}),
                    getattr(self.store, "_api_kwargs", {}),
                ]
            )
        config_values.append(self._contract_rules_for(self._position_key(data)))
        for config in config_values:
            if not isinstance(config, dict):
                continue
            exchange = str(
                config.get("exchange_type")
                or config.get("exchange")
                or config.get("exchange_id")
                or ""
            ).upper()
            if exchange == "CTP":
                return True
        return False

    def _ensure_required_net_offset(self, order):
        """Infer safe CTP-style offsets for net-position orders."""
        if self._is_dual_side_mode() or not self._requires_explicit_offset(order.data):
            return None

        explicit_offset = self._order_info_get(order, "offset")
        if explicit_offset not in (None, ""):
            return self._validate_explicit_net_offset(order, explicit_offset)

        size = abs(float(order.size or 0.0))
        if size <= 0.0:
            return None

        position = self.getposition(order.data, clone=False)
        current_size = float(position.size or 0.0)
        if order.isbuy():
            if current_size < 0.0:
                if size > abs(current_size) + 1e-12:
                    return (
                        "net_reversal_requires_split",
                        "CTP net-position reversal orders must be split into close and open legs",
                    )
                order.addinfo(offset="close")
            else:
                order.addinfo(offset="open")
        else:
            if current_size > 0.0:
                if size > current_size + 1e-12:
                    return (
                        "net_reversal_requires_split",
                        "CTP net-position reversal orders must be split into close and open legs",
                    )
                order.addinfo(offset="close")
            else:
                order.addinfo(offset="open")
        return None

    def _validate_explicit_net_offset(self, order, offset):
        offset_text = str(offset or "").strip().lower()
        if offset_text not in {"close", "close_today", "close_yesterday"}:
            return None

        size = abs(float(order.size or 0.0))
        if size <= 0.0:
            return None

        position = self.getposition(order.data, clone=False)
        current_size = float(position.size or 0.0)
        if order.isbuy():
            closable = abs(current_size) if current_size < 0.0 else 0.0
        else:
            closable = current_size if current_size > 0.0 else 0.0
        if size > closable + 1e-12:
            return (
                "close_size_exceeds_position",
                "CTP close order size exceeds the available position",
            )
        return None

    def _contract_rules_for(self, data_name):
        """Resolve contract metadata from the broker and store configuration."""
        rules = {}
        aliases = self._symbol_aliases(data_name)
        for alias in aliases:
            rules.update(self._contract_metadata.get(alias, {}))
        alias_set = set(aliases)
        for key, value in self._contract_metadata.items():
            if key in aliases:
                continue
            if alias_set.intersection(self._symbol_aliases(key)):
                rules.update(value)
        # SDK metadata is startup-cached even when a compatibility adapter
        # executes commands synchronously.  Do not turn an order-type check
        # into a synchronous SDK metadata request on the strategy thread.
        if bool(getattr(self.store, "_sdk_mode", False)) or self._uses_async_commands():
            store_metadata = getattr(self.store, "contract_metadata", {})
            for alias in aliases:
                rules.update(store_metadata.get(alias, {}))
        elif self.store is not None and hasattr(self.store, "get_contract_metadata"):
            rules.update(self.store.get_contract_metadata(data_name) or {})
        return rules

    def _emit_runtime_event(self, event_type, **kwargs):
        """Proxy runtime events through the store notification queue when available."""
        if self.store is not None and hasattr(self.store, "emit_runtime_event"):
            return self.store.emit_runtime_event(event_type, **self._redact_runtime_value(kwargs))
        return None

    def _redact_runtime_value(self, value):
        """Use Store credential context when available and remain safe standalone."""
        sanitizer = getattr(self.store, "redact_runtime_value", None)
        if callable(sanitizer):
            try:
                return sanitizer(value)
            except Exception:
                _safe_log("warning", "btapibroker:6018 suppressed Exception")
        return _redact_diagnostic(value)

    def _sanitize_exception(self, exc):
        """Preserve exception type while removing credential-bearing fields."""
        sanitizer = getattr(self.store, "sanitize_exception", None)
        if callable(sanitizer):
            try:
                return sanitizer(exc)
            except Exception:
                _safe_log("warning", "btapibroker:6028 suppressed Exception")
        try:
            exc.args = tuple(_redact_diagnostic(item) for item in exc.args)
        except Exception:
            _safe_log("warning", "btapibroker:6032 suppressed Exception")
        return exc

    def _order_runtime_details(self, order):
        """Build a stable runtime-event payload for an order object."""
        external_order_id = self._order_info_get(order, "external_order_id")
        ctp_order_ref = self._order_info_get(order, "ctp_order_ref")
        return {
            "order_ref": getattr(order, "ref", None),
            "external_order_id": external_order_id,
            "ctp_order_ref": ctp_order_ref,
            "data_name": self._position_key(order.data),
            "side": "buy" if order.isbuy() else "sell",
            "size": abs(float(order.size or 0.0)),
            "price": (
                order.price if order.price is not None else getattr(order.created, "price", None)
            ),
            "status": order.getstatusname(),
        }

    def _drain_store_updates(self):
        """Consume remote broker updates from the store and reflect them locally."""
        if getattr(self, "_managed_provider_projection_failed", False):
            return
        if self.store is not None and bool(
            getattr(self.store, "managed_provider_projection_blocked", False)
        ):
            self._managed_provider_projection_failed = True
            for pending_order in self.orders.values():
                if self._order_info_get(pending_order, "managed_intent_id"):
                    self._mark_managed_provider_projection_failure(
                        pending_order, "managed_provider_projection_session_fenced"
                    )
            return
        if self.store is None or not hasattr(self.store, "poll_broker_update"):
            return

        while True:
            raw_update = self.store.poll_broker_update()
            if raw_update is None:
                if bool(getattr(self.store, "managed_provider_projection_blocked", False)):
                    self._managed_provider_projection_failed = True
                    for pending_order in self.orders.values():
                        if self._order_info_get(pending_order, "managed_intent_id"):
                            self._mark_managed_provider_projection_failure(
                                pending_order, "managed_provider_projection_session_fenced"
                            )
                break

            for update in self._iter_broker_update_rows(raw_update):
                kind = str(update.get("kind") or "").lower()
                managed_projection_receipt = False
                managed_projection_order = None
                if (
                    kind in {"order", "trade"}
                    and bool(
                        getattr(self.store, "managed_provider_projection_enabled", False)
                    )
                ):
                    managed_projection_order = self._lookup_order(update)
                    if managed_projection_order is None:
                        self._managed_provider_projection_failed = True
                        return
                    if bool(
                        self._order_info_get(
                            managed_projection_order, "managed_provider_projection_blocked", False
                        )
                    ):
                        continue
                    try:
                        prepared = self.store.prepare_managed_provider_projection(
                            update, managed_projection_order
                        )
                    except Exception as exc:
                        self._sanitize_exception(exc)
                        retryable = bool(
                            getattr(exc, "provider_projection_retryable", False)
                        )
                        if not retryable:
                            managed_projection_order.addinfo(
                                managed_provider_projection_blocked=True
                            )
                        managed_projection_order.addinfo(
                            execution_unknown=True,
                            managed_provider_projection_error=(
                                "cumulative_fee_pending"
                                if retryable
                                else "durable_provider_observation_unavailable"
                            ),
                        )
                        self.notify(managed_projection_order)
                        if bool(
                            getattr(self.store, "managed_provider_projection_blocked", False)
                        ):
                            self._managed_provider_projection_failed = True
                            return
                        continue
                    if prepared is None:
                        # The facade reported an exact duplicate or no new
                        # durable observation. It grants no Broker mutation.
                        continue
                    update = dict(prepared)
                    kind = str(update.get("kind") or "").lower()
                    managed_projection_order = self._lookup_order(update)
                    if (
                        managed_projection_order is None
                        or not self.store.validate_managed_provider_projection(
                            update, managed_projection_order
                        )
                    ):
                        self.store.fail_managed_provider_projection(
                            update, "receipt_validation_failed"
                        )
                        self._managed_provider_projection_failed = True
                        if managed_projection_order is not None:
                            self._mark_managed_provider_projection_failure(
                                managed_projection_order, "receipt_validation_failed"
                            )
                        return
                    managed_projection_receipt = True
                command = str(update.get("command") or "")
                ctp_query_completion = bool(
                    kind == "command_completion" and command == "ctp_reconcile"
                )
                execution_evidence_update = bool(
                    kind in {"order", "trade", "error"}
                    or (
                        kind == "command_completion"
                        and command in {"submit", "cancel", "query", "reconcile"}
                    )
                )
                if not ctp_query_completion:
                    self._ctp_reconciliation_event_epoch += 1
                    if self._ctp_reconciliation_required:
                        self._reset_ctp_reconciliation_rounds("broker_update_between_snapshots")
                    elif self._ctp_reconciliation_rounds >= 2 and execution_evidence_update:
                        # A late execution-side event makes the last flat
                        # snapshot obsolete even when the two-round gate had
                        # already opened.
                        self._begin_ctp_reconciliation("broker_update_after_reconciliation")
                try:
                    if kind == "order":
                        self._apply_order_update(update)
                    elif kind == "trade":
                        self._apply_trade_update(update)
                    elif kind == "error":
                        self._apply_error_update(update)
                    elif kind == "command_completion":
                        self._apply_command_completion(update)
                    if managed_projection_receipt:
                        if bool(
                            self._order_info_get(
                                managed_projection_order, "ledger_mismatch", False
                            )
                        ) or bool(
                            self._order_info_get(
                                managed_projection_order, "execution_unknown", False
                            )
                        ):
                            raise RuntimeError(
                                "Broker rejected managed cumulative provider facts"
                            )
                        self.store.complete_managed_provider_projection(
                            update, managed_projection_order
                        )
                except Exception as exc:
                    if not managed_projection_receipt:
                        raise
                    self._sanitize_exception(exc)
                    self.store.fail_managed_provider_projection(
                        update, "broker_apply_or_receipt_failure"
                    )
                    self._managed_provider_projection_failed = True
                    self._mark_managed_provider_projection_failure(
                        managed_projection_order, "broker_apply_or_receipt_failure"
                    )
                    return

    def _mark_managed_provider_projection_failure(self, order, reason):
        """Mark an already uncertain managed Broker projection without continuing it."""

        if order is None:
            return
        order.addinfo(
            execution_unknown=True,
            ledger_mismatch=True,
            managed_provider_projection_blocked=True,
            managed_provider_projection_error=str(reason),
        )
        self.notify(order)

    def _apply_command_completion(self, update):
        """Apply worker results on the Cerebro thread without treating REST ACKs as fills."""
        command = str(update.get("command") or "")
        if command == "execution_recovery_complete":
            response = update.get("response")
            completed = bool(
                update.get("success") is True
                and isinstance(response, dict)
                and response.get("completed") is True
                and response.get("armed") is False
                and response.get("market_data_only") is True
                and response.get("recovery_only") is False
                and response.get("requires_new_preflight") is True
            )
            notification = {
                "completed": completed,
                "status": "completed" if completed else "failed",
                "error_code": (
                    None
                    if completed
                    else (update.get("error_code") or "recovery_completion_unproven")
                ),
            }
            with self._execution_recovery_completion_lock:
                self._execution_recovery_completion_pending = False
                self._execution_recovery_completion_receipt = None
                callbacks = tuple(self._execution_recovery_completion_callbacks)
                self._execution_recovery_completion_callbacks.clear()
                prior = self._last_execution_recovery_completion
                if not (
                    isinstance(prior, dict)
                    and prior.get("completed") is True
                    and notification["completed"] is False
                ):
                    self._last_execution_recovery_completion = deepcopy(notification)
            for callback in callbacks:
                try:
                    callback(deepcopy(notification))
                except Exception as exc:
                    _safe_log("warning", "btapibroker:6143 fallback on Exception")
                    self._sanitize_exception(exc)
                    self._emit_runtime_event(
                        "execution_recovery_completion_callback_failed",
                        level="ERROR",
                        error_code=type(exc).__name__,
                    )
            return
        if command == "ctp_reconcile":
            self._ctp_reconciliation_pending = False
            callbacks = tuple(self._ctp_reconciliation_callbacks)
            self._ctp_reconciliation_callbacks.clear()
            response = update.get("response")
            if update.get("success") is True and isinstance(response, dict):
                # Build the callback view first: it reflects the already-applied
                # main-thread trade ledger.  The gate must consume that view,
                # rather than advancing before local evidence is attached.
                callback_snapshot = self._ctp_reconciliation_callback_snapshot(response, None)
                state = self.record_ctp_reconciliation(callback_snapshot)
                notification = self._ctp_reconciliation_callback_snapshot(callback_snapshot, state)
            else:
                self._reset_ctp_reconciliation_rounds("query_failed")
                state = self.get_ctp_reconciliation_state()
                notification = {
                    "schema_version": "backtrader.ctp.reconciliation.v1",
                    "complete": False,
                    "is_last_seen": False,
                    "timed_out": False,
                    "error_code": update.get("error_code") or "ctp_reconciliation_failed",
                    "evidence_complete": False,
                    "broker_reconciliation_state": state,
                }
            self._last_ctp_reconciliation_result = deepcopy(notification)
            for callback in callbacks:
                try:
                    callback(deepcopy(notification))
                except Exception as exc:
                    _safe_log("warning", "btapibroker:6179 fallback on Exception")
                    self._sanitize_exception(exc)
                    self._emit_runtime_event(
                        "ctp_reconciliation_callback_failed",
                        level="ERROR",
                        error_code=type(exc).__name__,
                    )
            return
        if command == "reconcile":
            self._periodic_reconcile_pending = False
            if update.get("success") is True and isinstance(update.get("response"), dict):
                self._last_reconcile_result = deepcopy(update["response"])
                self._apply_reconcile_read_model(update["response"])
            else:
                self._last_reconcile_result = {
                    "error_code": update.get("error_code"),
                    "execution_unknown": bool(update.get("execution_unknown")),
                }
            return

        order = self.orders.get(update.get("bt_order_ref"))
        if order is None and update.get("client_order_id") not in (None, ""):
            order = self._lookup_order(update)
        if order is None:
            return
        response = update.get("response")

        if command == "query":
            if update.get("success") is True and isinstance(response, dict):
                self._apply_order_update(response, from_query=True)
                if order.alive() and bool(
                    self._order_info_get(order, "cancel_reconcile_confirmed_live", False)
                ):
                    self._schedule_cancel_retry(order, "query_confirmed_order_live", immediate=True)
                elif order.alive() and (
                    bool(self._order_info_get(order, "execution_unknown", False))
                    or bool(self._order_info_get(order, "cancel_execution_unknown", False))
                ):
                    self._schedule_order_reconcile_retry(order, "query_result_inconclusive")
            else:
                order.addinfo(
                    execution_unknown=True,
                    reconcile_requested=False,
                    error_code=(
                        "query_execution_unknown"
                        if update.get("execution_unknown") is True
                        else "query_failed"
                    ),
                )
                self.notify(order)
                self._schedule_order_reconcile_retry(order, "query_command_failed")
            return

        if command == "cancel":
            if update.get("success") is True:
                order.addinfo(
                    cancel_requested_remote=True,
                    cancel_intent_active=True,
                    cancel_command_completed=True,
                    cancel_receipt_id=update.get("receipt_id"),
                )
                if isinstance(response, dict):
                    self._cache_order_identifiers(order, response)
                self._request_order_reconcile(order)
            elif update.get("execution_unknown") is True:
                order.addinfo(
                    cancel_requested_remote=True,
                    cancel_execution_unknown=True,
                    cancel_intent_active=True,
                    execution_unknown=True,
                    cancel_error_code=update.get("error_code"),
                )
                self._request_order_reconcile(order)
            else:
                order.addinfo(
                    cancel_requested_remote=False,
                    cancel_intent_active=True,
                    cancel_deadline_monotonic_ns=None,
                    cancel_deadline_unknown_marked=False,
                    cancel_error_code=update.get("error_code") or "remote_cancel_failed",
                )
            self.notify(order)
            return

        if command != "submit":
            return
        if (
            isinstance(response, dict)
            and response.get("local_terminal") is True
            and response.get("remote_write_attempted") is False
            and response.get("terminal_confirmed") is True
        ):
            local_update = dict(response)
            for key in (
                "bt_order_ref",
                "client_order_id",
                "data_name",
                "exchange_name",
            ):
                if update.get(key) not in (None, ""):
                    local_update.setdefault(key, update[key])
            self._apply_order_update(local_update)
            return
        if isinstance(response, dict) and response.get("execution_unknown") is True:
            self._abort_recovery_dispatch(order, "execution_recovery_dispatch_unknown")
            if order.status < order.Accepted:
                order.accept(self)
            order.addinfo(
                execution_unknown=True,
                error_code=response.get("error_code") or "remote_execution_unknown",
                error_msg="Remote submission outcome is unknown; reconcile the original id",
            )
            self.notify(order)
            self._request_order_reconcile(order)
            return
        if (
            isinstance(response, dict)
            and response.get("definite_reject") is True
            and response.get("terminal_confirmed") is True
        ):
            self._abort_recovery_dispatch(order, "execution_recovery_dispatch_failed")
            self._apply_order_update(response)
            return
        if update.get("success") is True:
            if isinstance(response, dict):
                self._cache_order_identifiers(order, response)
            order.addinfo(
                submit_command_completed=True,
                submit_receipt_id=update.get("receipt_id"),
            )
            # A transport ACK is evidence that the command returned, not an
            # authoritative Accepted/Partial/Completed transition.
            self.notify(order)
            return
        if update.get("execution_unknown") is True:
            self._abort_recovery_dispatch(order, "execution_recovery_dispatch_unknown")
            if order.status < order.Accepted:
                order.accept(self)
            order.addinfo(
                execution_unknown=True,
                error_code=update.get("error_code") or "remote_execution_unknown",
                error_msg="Remote submission outcome is unknown; reconcile the original id",
            )
            self.notify(order)
            self._request_order_reconcile(order)
            return
        if order.alive():
            self._abort_recovery_dispatch(order, "execution_recovery_dispatch_failed")
            order.addinfo(
                error_code=(
                    "remote_submit_rejected"
                    if update.get("definite_reject")
                    else "remote_submit_failed"
                ),
                remote_error_code=update.get("error_code"),
                error_msg=update.get("error_msg") or "SDK submission command failed",
            )
            order.reject(self)
            self.notify(order)
            self._clear_order_mappings(order)

    def _apply_reconcile_read_model(self, snapshot):
        """Apply worker query results while keeping startup fills authoritative."""
        cache_updater = getattr(self.store, "apply_reconcile_snapshot", None)
        if callable(cache_updater):
            cache_updater(snapshot)
        balance = snapshot.get("balance")
        if isinstance(balance, dict):
            self._cash = float(balance.get("cash", self._cash))
            self._value = float(balance.get("value", self._value))
        self._remote_open_orders_snapshot = list(snapshot.get("open_orders") or [])
        now = time.monotonic()
        self._last_account_refresh = now
        self._last_open_orders_refresh = now
        rows = list(snapshot.get("positions") or [])
        if self.p.position_sync_policy == "startup":
            if not self.get_orders_open() and not self._pending_trade_updates:
                try:
                    mismatches = self._position_audit_diff(rows)
                except Exception as exc:
                    _safe_log("warning", "btapibroker:6341 fallback on Exception")
                    self._position_audit_error = type(exc).__name__
                    self._position_audit_blocked = True
                else:
                    self._position_audit_error = None
                    self._position_audit_mismatch = mismatches or None
                    self._position_audit_blocked = bool(mismatches)
            return

        synced: "DefaultDict[Any, Position]" = collections.defaultdict(Position)
        long_synced: "DefaultDict[Any, Position]" = collections.defaultdict(Position)
        short_synced: "DefaultDict[Any, Position]" = collections.defaultdict(Position)
        tracked = self._tracked_position_alias_map()
        for row in rows:
            key = self._position_row_canonical_key(row, tracked)
            if tracked and key is None:
                continue
            self._sync_one_position(row, synced, long_synced, short_synced, key=key)
        if self._is_dual_side_mode():
            self.long_positions = long_synced
            self.short_positions = short_synced
            self.positions = collections.defaultdict(Position)
            for key in set(long_synced) | set(short_synced):
                self._sync_net_position(key)
        else:
            self.positions = synced
        self._last_positions_refresh = now

    def _retry_delay_ns(self, attempts):
        base = max(float(self.p.reconcile_retry_backoff or 0.0), 0.0)
        return int(base * (2 ** max(int(attempts) - 1, 0)) * 1_000_000_000)

    def _schedule_order_reconcile_retry(self, order, reason):
        """Schedule a bounded read retry while preserving the original order identity."""
        attempts = int(self._order_info_get(order, "reconcile_attempts", 0) or 0)
        maximum = max(int(self.p.reconcile_retry_max_attempts or 0), 1)
        if attempts >= maximum:
            order.addinfo(
                reconcile_requested=False,
                reconcile_exhausted=True,
                reconcile_last_reason=str(reason),
                reconcile_next_monotonic_ns=None,
                execution_unknown=True,
            )
            return
        order.addinfo(
            reconcile_requested=False,
            reconcile_exhausted=False,
            reconcile_last_reason=str(reason),
            reconcile_next_monotonic_ns=time.monotonic_ns() + self._retry_delay_ns(attempts),
        )

    def _schedule_cancel_retry(self, order, reason, *, immediate=False):
        """Retry cancel only after a query proved that the same order remains live."""
        attempts = int(self._order_info_get(order, "cancel_retry_attempts", 0) or 0)
        maximum = max(int(self.p.cancel_retry_max_attempts or 0), 1)
        if attempts >= maximum:
            order.addinfo(
                cancel_retry_exhausted=True,
                cancel_retry_due_monotonic_ns=None,
                cancel_intent_active=True,
                execution_unknown=True,
            )
            return
        delay_ns = 0 if immediate else self._retry_delay_ns(attempts)
        order.addinfo(
            cancel_retry_exhausted=False,
            cancel_retry_last_reason=str(reason),
            cancel_retry_due_monotonic_ns=time.monotonic_ns() + delay_ns,
            cancel_intent_active=True,
        )

    def _request_order_reconcile(self, order):
        """Queue a bounded identity-preserving query for an unknown SDK order."""
        if bool(self._order_info_get(order, "reconcile_requested", False)):
            return
        due = self._order_info_get(order, "reconcile_next_monotonic_ns")
        if due not in (None, ""):
            try:
                if time.monotonic_ns() < int(due):
                    return
            except (TypeError, ValueError):
                _safe_log("debug", "btapibroker:6411 ignored TypeError,ValueError")
        attempts = int(self._order_info_get(order, "reconcile_attempts", 0) or 0)
        maximum = max(int(self.p.reconcile_retry_max_attempts or 0), 1)
        if attempts >= maximum:
            order.addinfo(
                reconcile_requested=False,
                reconcile_exhausted=True,
                reconcile_next_monotonic_ns=None,
                execution_unknown=True,
            )
            return
        method = getattr(self.store, "enqueue_query", None)
        if not callable(method):
            self._schedule_order_reconcile_retry(order, "query_capability_unavailable")
            return
        order.addinfo(
            reconcile_attempts=attempts + 1,
            reconcile_max_attempts=maximum,
            reconcile_next_monotonic_ns=None,
        )
        try:
            receipt = method(order.ref, dataname=self._position_key(order.data))
        except Exception:
            _safe_log("warning", "btapibroker:6445 fallback on Exception")
            self._schedule_order_reconcile_retry(order, "query_enqueue_failed")
            return
        if isinstance(receipt, dict) and receipt.get("queued") is True:
            order.addinfo(
                reconcile_requested=True,
                reconcile_receipt_id=receipt.get("receipt_id"),
            )
            return
        self._schedule_order_reconcile_retry(order, "query_enqueue_rejected")

    @classmethod
    def _iter_broker_update_rows(cls, update):
        """Yield flat broker updates from exchange envelopes such as WS data lists."""
        if not isinstance(update, dict):
            return

        data = update.get("data")
        if isinstance(data, dict):
            rows = [data]
        elif isinstance(data, (list, tuple)):
            rows = [item for item in data if isinstance(item, dict)]
        else:
            yield update
            return

        if not rows:
            yield update
            return

        envelope = {key: value for key, value in update.items() if key not in {"data", "id"}}
        if update.get("id") not in (None, ""):
            envelope["message_id"] = update.get("id")
        for row in rows:
            flat = dict(envelope)
            flat.update(row)
            if "kind" not in flat and update.get("kind") not in (None, ""):
                flat["kind"] = update.get("kind")
            yield flat

    def _trade_dedupe_key(self, update, order=None):
        """Build a stable trade dedupe key when the provider exposes a fill id."""
        trade_id = self._extract_update_value(
            update,
            "trade_id",
            "tradeId",
            "TradeID",
            "exec_id",
            "execId",
            "execID",
            "execution_id",
            "executionId",
            "fill_id",
            "fillId",
        )
        if trade_id in (None, ""):
            return None

        order_key = (
            self._remote_external_order_id(update)
            or self._remote_client_order_ref(update)
            or self._extract_update_value(update, "bt_order_ref")
        )
        if order_key in (None, "") and order is not None:
            order_key = getattr(order, "ref", None)
        if order_key in (None, "") and order is None:
            return None

        data_name = self._extract_update_value(update, *_DATA_NAME_KEYS)
        if data_name in (None, "") and order is not None:
            data_name = self._position_key(order.data)

        return (str(order_key), str(data_name or ""), str(trade_id))

    def _trade_update_details(self, update, order=None, **extra):
        """Return a compact runtime-event payload for a remote trade update."""
        detail_keys = (
            "kind",
            "trade_id",
            "execID",
            "external_order_id",
            "externalOrderId",
            "venue_order_id",
            "venueOrderId",
            "ordId",
            "order_id",
            "orderId",
            "OrderID",
            "OrderSysID",
            "order_ref",
            "orderRef",
            "client_order_id",
            "clientOrderId",
            "clOrdId",
            "bt_order_ref",
            "data_name",
            "dataname",
            "symbol",
            "instrument",
            "instId",
            "exchange_id",
            "side",
            "Side",
            "direction",
            "Direction",
            "trade_side",
            "tradeSide",
            "position_side",
            "positionSide",
            "posSide",
            "offset",
            "position_effect",
            "positionEffect",
            "position_mode",
            "positionMode",
            "posMode",
            "quantity_unit",
            "quantityUnit",
            "qty_unit",
            "qtyUnit",
            "size",
            "execQty",
            "fillSz",
            "accFillSz",
            "price",
            "execPrice",
            "execFee",
            "fillPx",
            "avgPx",
            "px",
            "timestamp",
        )
        details = {
            key: value
            for key in detail_keys
            if (value := self._extract_update_value(update, key)) not in (None, "")
        }
        if order is not None:
            details["local_order"] = self._order_runtime_details(order)
            contract = self._order_execution_contracts.get(order.ref)
            if contract is None:
                contract = self._freeze_order_execution_contract(order)
            details["expected_execution_contract"] = dict(contract)
        actual_remote_identity = {}
        for canonical, aliases in (
            ("side", ("side", "Side", "direction", "Direction", "trade_side", "tradeSide")),
            ("position_side", ("position_side", "positionSide", "posSide")),
            ("offset", ("offset", "position_effect", "positionEffect")),
            ("position_mode", ("position_mode", "positionMode", "posMode")),
            ("quantity_unit", ("quantity_unit", "quantityUnit", "qty_unit", "qtyUnit")),
        ):
            value = self._extract_update_value(update, *aliases)
            if value not in (None, ""):
                actual_remote_identity[canonical] = value
        if actual_remote_identity:
            details["actual_remote_identity"] = actual_remote_identity
        details.update(extra)
        return details

    @staticmethod
    def _order_remaining_qty(order):
        """Return absolute local remaining quantity for a live order."""
        try:
            return abs(float(order.executed.remsize or 0.0))
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _is_confirmed_terminal_order_response(cls, response):
        """Return whether a normalized cancel response confirms an order terminal state."""
        if (
            not isinstance(response, dict)
            or response.get("terminal_confirmed") is not True
            or response.get("execution_unknown") is True
        ):
            return False
        return cls._normalize_remote_order_status(response.get("status")) in {
            "completed",
            "canceled",
            "expired",
            "rejected",
        }

    def _pending_trade_update_limit(self):
        try:
            return max(int(self.p.pending_trade_update_limit or 0), 0)
        except (TypeError, ValueError):
            return 0

    def _defer_trade_update(self, update):
        """Temporarily hold a trade update until a later order update maps it."""
        limit = self._pending_trade_update_limit()
        if limit <= 0:
            self._emit_runtime_event(
                "trade_update_dropped",
                level="ERROR",
                error_code="unmatched_trade_update",
                error_msg=(
                    "Remote trade update could not be matched to a local order and "
                    "pending trade caching is disabled"
                ),
                status="dropped",
                details=self._trade_update_details(update),
            )
            return

        while len(self._pending_trade_updates) >= limit:
            dropped = self._pending_trade_updates.popleft()
            self._emit_runtime_event(
                "trade_update_dropped",
                level="ERROR",
                error_code="pending_trade_update_limit_exceeded",
                error_msg="Dropped the oldest unmatched remote trade update",
                status="dropped",
                details=self._trade_update_details(dropped),
            )

        self._pending_trade_updates.append(deepcopy(update))
        self._emit_runtime_event(
            "trade_update_deferred",
            level="WARNING",
            error_code="unmatched_trade_update",
            error_msg=(
                "Remote trade update was deferred until a matching order identifier arrives"
            ),
            status="deferred",
            details=self._trade_update_details(update),
        )

    def _retry_pending_trade_updates(self):
        """Retry deferred trade updates after order identifiers are refreshed."""
        if not self._pending_trade_updates:
            return

        pending = self._pending_trade_updates
        self._pending_trade_updates = collections.deque()
        while pending:
            update = pending.popleft()
            status = self._apply_trade_update(update, defer_unmatched=False)
            if status == "unmatched":
                self._pending_trade_updates.append(update)

    def _apply_submit_response_fill(self, order, response):
        """Apply immediate fill details returned by a synchronous submit call."""
        if not isinstance(response, dict):
            return "ignored"
        if response.get("execution_unknown") is True:
            return "ignored"
        status = self._normalize_remote_order_status(response.get("status"))
        if status not in {"partial", "completed", "canceled", "expired"}:
            return "ignored"

        filled = self._extract_update_value(response, *_SUBMIT_FILL_QTY_KEYS)
        price = self._extract_update_value(response, *_FILL_PRICE_KEYS)
        if status in {"partial", "completed"} and (filled in (None, "") or price in (None, "")):
            return "ignored"

        update = dict(response)
        update["kind"] = "order"
        update["status"] = status
        update["filled"] = filled
        update["price"] = price
        update.setdefault("bt_order_ref", getattr(order, "ref", None))
        update.setdefault("data_name", self._position_key(order.data))
        update.setdefault("side", "buy" if order.isbuy() else "sell")
        deal_id = update.get("deal")
        if deal_id not in (None, ""):
            update.setdefault("trade_id", deal_id)
        return self._apply_order_update(update)

    def _apply_order_update(self, update, *, from_query=False):
        """Apply a normalized remote order-status update."""
        order = self._lookup_order(update)
        if order is None:
            return None

        self._cache_order_identifiers(order, update)
        self._retry_pending_trade_updates()

        status = self._normalize_remote_order_status(update.get("status"))
        was_unknown = bool(self._order_info_get(order, "execution_unknown", False))
        if update.get("execution_unknown") is True:
            if order.alive() and not was_unknown:
                order.addinfo(execution_unknown=True)
                self.notify(order)
                self._request_order_reconcile(order)
            return None
        if status in {
            "accepted",
            "partial",
            "completed",
            "canceled",
            "rejected",
            "expired",
        } and not bool(self._order_info_get(order, "ledger_mismatch", False)):
            order.addinfo(
                execution_unknown=False,
                reconcile_requested=False,
                reconcile_exhausted=False,
                reconcile_next_monotonic_ns=None,
            )
            if status in {"completed", "canceled", "rejected", "expired"}:
                order.addinfo(
                    cancel_requested_remote=False,
                    cancel_execution_unknown=False,
                    cancel_intent_active=False,
                    cancel_deadline_monotonic_ns=None,
                    cancel_deadline_unknown_marked=False,
                    cancel_retry_due_monotonic_ns=None,
                    cancel_retry_exhausted=False,
                    managed_execution_cancel_pending=False,
                    managed_execution_cancel_reconciliation_required=False,
                    managed_execution_cancel_freeze_required=False,
                )
            elif from_query and bool(
                self._order_info_get(order, "cancel_execution_unknown", False)
            ):
                # A read after an ambiguous cancel can prove that the order is
                # still live. It is then safe to retry the same cancel, but the
                # user's cancellation intent continues to block new exposure.
                order.addinfo(
                    cancel_requested_remote=False,
                    cancel_execution_unknown=False,
                    cancel_intent_active=True,
                    cancel_reconcile_confirmed_live=True,
                    cancel_deadline_monotonic_ns=None,
                    cancel_deadline_unknown_marked=False,
                )
        source = update.get("execution_source")
        if source in {"trades", "cumulative"}:
            order.addinfo(execution_source=source)
        status_msg = str(self._redact_runtime_value(update.get("status_msg") or ""))
        if status_msg:
            order.addinfo(error_msg=status_msg)

        if self._order_info_get(order, "execution_source") == "trades" and status in {
            "completed",
            "canceled",
            "expired",
        }:
            return self._apply_trade_terminal_status(order, update, status)

        if status == "accepted" and order.status < order.Accepted:
            order.accept(self)
            self.notify(order)
        elif status == "accepted" and was_unknown:
            self.notify(order)
        elif status in {"partial", "completed"}:
            self._apply_trade_from_order_update(order, update)
        elif status == "canceled":
            order.addinfo(remote_terminal_status="canceled")
            self._apply_trade_from_order_update(order, update)
            if order.status not in (order.Canceled, order.Completed):
                order.cancel()
                self.notify(order)
            self._clear_order_mappings(order)
        elif status == "cancel_rejected":
            if bool(self._order_info_get(order, "cancel_requested_remote", False)):
                order.addinfo(
                    cancel_requested_remote=False,
                    cancel_execution_unknown=False,
                    cancel_intent_active=False,
                    reconcile_requested=False,
                    cancel_reject_msg=status_msg,
                    cancel_reject_code=str(
                        self._redact_runtime_value(update.get("error_code") or "")
                    ),
                )
                self.notify(order)
        elif status == "rejected":
            self._attach_remote_error_code(order, update)
            order.addinfo(error_code="remote_reject")
            if status_msg:
                order.addinfo(error_msg=status_msg)
            if order.status not in (order.Rejected, order.Completed):
                order.reject(self)
                self.notify(order)
            self._clear_order_mappings(order)
        elif status == "expired":
            order.addinfo(remote_terminal_status="expired")
            self._apply_trade_from_order_update(order, update)
            if order.status not in (order.Expired, order.Completed):
                # Exchange IOC expiry is authoritative even without a local
                # ``valid`` deadline (Order.expire only checks that deadline).
                order.status = order.Expired
                order.executed.dt = self._order_execution_dt(order)
                self.notify(order)
            self._clear_order_mappings(order)

    def _apply_trade_terminal_status(self, order, update, status):
        """Wait for actual deals up to the terminal report's cumulative volume."""
        raw = self._extract_update_value(update, *_CUMULATIVE_FILL_QTY_KEYS)
        comminfo, option_error = self._option_comminfo_for_order(order)
        if option_error is not None:
            code, message = option_error
            return self._quarantine_option_fill(order, update, code, message)
        if isinstance(comminfo, CtpOptionPremium) and raw not in (None, ""):
            try:
                expected_quantity = self._strict_option_input_number(
                    raw,
                    "option_fill_size_invalid",
                    integer=True,
                    positive=False,
                )
                if expected_quantity < 0.0:
                    raise OptionAccountingError(
                        "option_fill_size_invalid",
                        "option_fill_size_invalid: cumulative quantity cannot be negative",
                    )
            except OptionAccountingError as exc:
                return self._quarantine_option_fill(order, update, exc.code, str(exc))
        try:
            expected = float(raw)
        except (TypeError, ValueError):
            expected = float("nan")
        total = abs(float(order.size))
        if (
            not math.isfinite(expected)
            or expected < 0
            or expected > total + 1e-12
            or (status == "completed" and abs(expected - total) > 1e-12)
        ):
            order.addinfo(execution_unknown=True, error_code="invalid_terminal_fill_quantity")
            self.notify(order)
            return "ignored"
        order.addinfo(
            execution_fill_source="trade",
            remote_terminal_status=status,
            remote_terminal_filled=max(
                expected, float(self._order_info_get(order, "remote_terminal_filled", 0))
            ),
        )
        self._set_status_after_fill(order)
        self.notify(order)
        return "pending_trades" if order.alive() else "terminal"

    @staticmethod
    def _normalize_remote_order_status(status):
        text = str(status or "").strip().lower().replace("-", "_").replace(" ", "_")
        if text in {"accepted", "new", "open", "live", "working", "pre_submitted"}:
            return "accepted"
        if text in {"partial", "partial_filled", "partially_filled"}:
            return "partial"
        if text in {"filled", "completed", "complete", "done", "closed", "fully_filled"}:
            return "completed"
        if text in {
            "canceled",
            "cancelled",
            "cancel",
            "mmp_canceled",
            "partial_canceled",
            "partial_cancelled",
            "partial_filled_canceled",
            "partial_filled_cancelled",
            "part_filled_canceled",
            "part_filled_cancelled",
            "partially_filled_canceled",
            "partially_filled_cancelled",
            "filled_canceled",
            "filled_cancelled",
        }:
            return "canceled"
        if text in {
            "cancel_rejected",
            "cancel_reject",
            "cancel_failed",
            "cancel_error",
            "cancel_denied",
            "cancel_request_rejected",
            "cancel_request_failed",
        }:
            return "cancel_rejected"
        if text in {"rejected", "reject", "failed", "error"}:
            return "rejected"
        if text in {"expired", "expired_in_match"}:
            return "expired"
        return text

    def _apply_trade_from_order_update(self, order, update):
        """Book a cumulative checkpoint, separately from incremental trade events.

        A priced cumulative checkpoint becomes this order's accounting authority.
        Later trades without a reliable cumulative position may overlap any part
        of that checkpoint, so only later checkpoints can advance accounting.
        Providers without actual cumulative fill prices remain trade-driven.
        """
        if bool(self._order_info_get(order, "ledger_mismatch", False)):
            return "quarantined"
        comminfo, option_error = self._option_comminfo_for_order(order)
        if option_error is not None:
            code, message = option_error
            return self._quarantine_option_fill(order, update, code, message)
        if isinstance(comminfo, CtpOptionPremium):
            cumulative_value = self._extract_update_value(update, *_CUMULATIVE_FILL_QTY_KEYS)
            if cumulative_value not in (None, ""):
                try:
                    cumulative_quantity = self._strict_option_input_number(
                        cumulative_value,
                        "option_fill_size_invalid",
                        integer=True,
                        positive=False,
                    )
                    if cumulative_quantity < 0.0:
                        raise OptionAccountingError(
                            "option_fill_size_invalid",
                            "option_fill_size_invalid: cumulative quantity cannot be negative",
                        )
                    if cumulative_quantity > 0.0:
                        self._strict_option_input_number(
                            self._extract_update_value(update, *_FILL_PRICE_KEYS),
                            "option_fill_price_invalid",
                        )
                except OptionAccountingError as exc:
                    return self._quarantine_option_fill(order, update, exc.code, str(exc))
        if self._order_info_get(order, "execution_source") == "trades":
            # CTP order reports provide volume and limit price; only its deal
            # events supply the actual prices and incremental fill identities.
            return "ignored"
        filled_value = self._extract_update_value(update, *_CUMULATIVE_FILL_QTY_KEYS)
        if filled_value in (None, ""):
            return "ignored"
        try:
            cumulative_filled = abs(float(filled_value))
            already_filled = abs(float(order.executed.size or 0.0))
        except (TypeError, ValueError):
            return "ignored"
        if not math.isfinite(cumulative_filled) or cumulative_filled <= 0:
            return "ignored"
        incremental_fill = cumulative_filled - already_filled
        if incremental_fill < -1e-12:
            return "ignored"

        price_value = self._extract_update_value(update, *_FILL_PRICE_KEYS)
        if price_value in (None, ""):
            return "ignored"
        try:
            price = float(price_value)
        except (TypeError, ValueError):
            return "ignored"
        if not math.isfinite(price) or price <= 0:
            return "ignored"
        if incremental_fill > 1e-12 and update.get("avg_price") not in (None, ""):
            # A cumulative average is not the price of this incremental fill.
            price = (
                cumulative_filled * float(update["avg_price"])
                - already_filled * float(order.executed.price or 0.0)
            ) / incremental_fill
        if not math.isfinite(price) or price <= 0:
            return "ignored"

        order.addinfo(
            execution_fill_source="cumulative", cumulative_fill_quantity=cumulative_filled
        )
        if incremental_fill <= 1e-12:
            return "ignored"

        trade_update = dict(update)
        trade_update["kind"] = "trade"
        trade_update["size"] = incremental_fill
        trade_update["price"] = price
        if update.get("cumulative_commission") not in (None, ""):
            raw_commission = update["cumulative_commission"]
            if isinstance(self._option_comminfo_for_order(order)[0], CtpOptionPremium):
                if isinstance(raw_commission, bool):
                    trade_update["_option_commission_error"] = "option_commission_boolean"
                else:
                    try:
                        cumulative_commission = float(raw_commission)
                    except (TypeError, ValueError):
                        cumulative_commission = None
                    if cumulative_commission is None or not math.isfinite(cumulative_commission):
                        trade_update["_option_commission_error"] = "option_commission_nonfinite"
                    else:
                        trade_update["commission"] = cumulative_commission - float(
                            order.executed.comm or 0.0
                        )
                        trade_update["commission_normalized"] = True
            else:
                trade_update["commission"] = float(raw_commission) - float(
                    order.executed.comm or 0.0
                )
                trade_update["commission_normalized"] = True
        trade_update.setdefault("side", "buy" if order.isbuy() else "sell")
        return self._apply_trade_update(
            trade_update, defer_unmatched=False, from_cumulative_status=True
        )

    def _validate_option_fill_inputs(self, order, update):
        """Validate raw option fill quantity and price before any normalization."""
        comminfo, error = self._option_comminfo_for_order(order)
        if error is not None:
            return error
        if not isinstance(comminfo, CtpOptionPremium):
            return None
        quantity = self._extract_update_value(update, *_FILL_QTY_KEYS)
        price = self._extract_update_value(update, *_FILL_PRICE_KEYS)
        try:
            self._strict_option_input_number(
                quantity,
                "option_fill_size_invalid",
                integer=True,
            )
            self._strict_option_input_number(price, "option_fill_price_invalid")
        except OptionAccountingError as exc:
            return exc.code, str(exc)
        return None

    def _apply_trade_update(
        self,
        update,
        *,
        defer_unmatched=True,
        from_cumulative_status=False,
        position_override=None,
    ):
        """Durably project factor fills before applying them to the local Broker."""

        order = self._lookup_order(update) if isinstance(update, dict) else None
        coordinator = getattr(self, "factor_execution_coordinator", None)
        is_registered_route = bool(
            self.store is not None
            and getattr(self.store, "registered_sim_route_id", None)
            == "simnow-registered-v1"
        )
        factor_intent_id = (
            self._order_info_get(order, "factor_intent_id") if order is not None else None
        )
        if (
            is_registered_route
            and coordinator is not None
            and getattr(coordinator, "broker", None) is self
            and isinstance(factor_intent_id, str)
            and factor_intent_id
            and not from_cumulative_status
        ):
            try:
                receipt, _projection, already_acknowledged = coordinator.record_trade_callback(
                    update, order
                )
            except Exception as error:
                order.addinfo(
                    execution_unknown=True,
                    ledger_mismatch=True,
                    factor_callback_error=getattr(error, "code", "trade_callback_unresolved"),
                )
                self._position_audit_blocked = True
                self._position_audit_error = "factor_trade_callback_unresolved"
                self.notify(order)
                return "quarantined"
            if already_acknowledged:
                return "ignored"
            trade_key = self._trade_dedupe_key(update, order=order)
            was_already_applied = bool(trade_key and trade_key in self._seen_trade_ids)
            result = self._apply_trade_update_impl(
                update,
                defer_unmatched=defer_unmatched,
                from_cumulative_status=from_cumulative_status,
                position_override=position_override,
            )
            if result == "applied" or (was_already_applied and result == "ignored"):
                try:
                    coordinator.journal.acknowledge_callback(receipt.receipt_id)
                except Exception:
                    order.addinfo(
                        execution_unknown=True,
                        ledger_mismatch=True,
                        factor_callback_error="callback_acknowledgement_not_durable",
                    )
                    self._position_audit_blocked = True
                    self._position_audit_error = "factor_callback_acknowledgement_not_durable"
                    self.notify(order)
                    return "applied_unacknowledged"
            elif result not in ("unmatched", "quarantined"):
                order.addinfo(
                    execution_unknown=True,
                    ledger_mismatch=True,
                    factor_callback_error="broker_fill_projection_not_applied",
                )
                self._position_audit_blocked = True
                self._position_audit_error = "factor_broker_fill_projection_not_applied"
                self.notify(order)
                return "quarantined"
            return result
        return self._apply_trade_update_impl(
            update,
            defer_unmatched=defer_unmatched,
            from_cumulative_status=from_cumulative_status,
            position_override=position_override,
        )

    def _apply_trade_update_impl(
        self,
        update,
        *,
        defer_unmatched=True,
        from_cumulative_status=False,
        position_override=None,
    ):
        """Apply a normalized remote trade fill to local Broker state."""
        trade_key = None if from_cumulative_status else self._trade_dedupe_key(update)
        if trade_key and trade_key in self._seen_trade_ids:
            return "ignored"

        order = self._lookup_order(update)
        if order is None:
            if defer_unmatched:
                self._defer_trade_update(update)
            return "unmatched"

        if bool(self._order_info_get(order, "ledger_mismatch", False)):
            if trade_key:
                self._quarantined_trade_ids.add(trade_key)
                self._seen_trade_ids.add(trade_key)
            return "quarantined"

        if trade_key is None and not from_cumulative_status:
            trade_key = self._trade_dedupe_key(update, order=order)
        if trade_key and trade_key in self._seen_trade_ids:
            return "ignored"

        side_present, remote_is_buy = self._explicit_trade_side(update)
        if side_present and (remote_is_buy is None or remote_is_buy != bool(order.isbuy())):
            error_code = (
                "trade_side_unrecognized" if remote_is_buy is None else "trade_side_mismatch"
            )
            error_msg = (
                "Remote trade side is not recognized for the matched local order"
                if remote_is_buy is None
                else "Remote trade side conflicts with the matched local order"
            )
            return self._block_trade_identity_mismatch(order, update, error_code, error_msg)

        identity_error = self._trade_position_identity_error(order, update)
        if identity_error is not None:
            return self._block_trade_identity_mismatch(order, update, *identity_error)

        option_input_error = self._validate_option_fill_inputs(order, update)
        if option_input_error is not None:
            code, message = option_input_error
            return self._quarantine_option_fill(order, update, code, message)

        fill_qty_value = self._extract_update_value(update, *_FILL_QTY_KEYS)
        try:
            fill_qty = abs(float(fill_qty_value or 0.0))
        except (TypeError, ValueError):
            fill_qty = 0.0
        if fill_qty <= 0:
            return "ignored"
        fill_price_value = self._extract_update_value(update, *_FILL_PRICE_KEYS)
        try:
            fill_price = float(fill_price_value or 0.0)
        except (TypeError, ValueError):
            fill_price = 0.0
        if fill_price <= 0:
            self._emit_runtime_event(
                "trade_update_ignored",
                level="ERROR",
                order_ref=getattr(order, "ref", None),
                error_code="invalid_trade_price",
                error_msg=(
                    "Remote trade update ignored because it did not include a positive fill price"
                ),
                status=order.getstatusname(),
                details=self._trade_update_details(update, order, fill_price=fill_price_value),
            )
            return "ignored"

        if (
            not from_cumulative_status
            and self._order_info_get(order, "execution_fill_source") == "cumulative"
        ):
            self._emit_runtime_event(
                "trade_update_ignored",
                level="WARNING",
                order_ref=getattr(order, "ref", None),
                error_code="duplicate_order_status_fill",
                error_msg=(
                    "Incremental trade not booked because cumulative order snapshots are "
                    "authoritative; a later cumulative checkpoint must confirm new fills"
                ),
                status=order.getstatusname(),
                details=self._trade_update_details(update, order),
            )
            if trade_key:
                self._seen_trade_ids.add(trade_key)
            return "ignored"

        if not from_cumulative_status:
            order.addinfo(execution_fill_source="trade")

        remaining_qty = self._order_remaining_qty(order)
        if remaining_qty <= 1e-12:
            self._emit_runtime_event(
                "trade_update_ignored",
                level="WARNING",
                order_ref=getattr(order, "ref", None),
                error_code="no_order_remaining",
                error_msg="Remote trade update ignored because the local order is already filled",
                status=order.getstatusname(),
                details=self._trade_update_details(update, order, remaining_qty=remaining_qty),
            )
            if trade_key:
                self._seen_trade_ids.add(trade_key)
            return "ignored"

        if fill_qty > remaining_qty + 1e-12:
            error_code = "trade_size_exceeds_remaining"
            error_msg = (
                "Remote trade update size exceeds the local order remaining size; "
                "only the remaining size was applied"
            )
            order.addinfo(
                execution_unknown=True,
                ledger_mismatch=True,
                error_code=error_code,
                error_msg=error_msg,
            )
            self._position_audit_blocked = True
            self._position_audit_error = error_code
            self._emit_runtime_event(
                "trade_update_size_clipped",
                level="ERROR",
                order_ref=getattr(order, "ref", None),
                error_code=error_code,
                error_msg=error_msg,
                status=order.getstatusname(),
                details=self._trade_update_details(
                    update,
                    order,
                    remaining_qty=remaining_qty,
                    requested_fill_qty=fill_qty,
                    applied_fill_qty=remaining_qty,
                ),
            )
            fill_qty = remaining_qty

        if self._is_dual_side_mode():
            result = self._apply_dual_side_trade_update(order, update, fill_qty, fill_price)
            if result != "applied":
                return result
            if trade_key:
                self._seen_trade_ids.add(trade_key)
            return result

        signed_fill = fill_qty if self._trade_update_is_buy(update, order) else -fill_qty

        key = self._position_key(order.data)
        position = (
            position_override if position_override is not None else self.positions[key]
        )
        old_size = position.size
        old_price = position.price
        comminfo = None
        is_option = False
        try:
            comminfo = order.comminfo or self.getcommissioninfo(order.data)
            is_option = isinstance(comminfo, CtpOptionPremium)
            preview = position.clone() if is_option else position
            psize, pprice, opened, closed = preview.update(
                signed_fill,
                fill_price,
                dt=self._execution_datetime(update),
            )

            closed_qty = abs(closed)
            opened_qty = abs(opened)
            if is_option:
                actual_commission, commission_error = self._remote_option_commission(update)
            else:
                actual_commission = self._remote_commission(update)
                commission_error = None
            closed_commission, opened_commission = self._execution_commissions(
                comminfo,
                fill_price,
                opened_qty,
                closed_qty,
                self._order_info_get(order, "offset") or update.get("offset"),
                actual_commission=actual_commission,
                fill_role=self._fill_commission_role(update),
            )
            closed_value = self._execution_value(
                comminfo,
                closed,
                old_price or fill_price,
                role="close",
            )
            opened_value = self._execution_value(
                comminfo,
                opened,
                fill_price,
                is_buy=order.isbuy(),
                role="open",
            )
            pnl = 0.0
            if closed_qty:
                pnl = (
                    comminfo.profitandloss(-closed, old_price, fill_price)
                    if comminfo is not None
                    else closed_qty
                    * (fill_price - old_price if old_size > 0 else old_price - fill_price)
                )
        except Exception as exc:
            _safe_log("error", "btapibroker:7251 exception before re-raise (Exception)")
            if is_option:
                error_code = getattr(exc, "code", "option_fill_accounting_failed")
                return self._quarantine_option_fill(order, update, error_code, str(exc))
            raise

        if is_option:
            position.__dict__.update(preview.__dict__)
            self._annotate_option_commission(
                order,
                comminfo,
                actual_commission,
                fill_qty=fill_qty,
                commission_error=commission_error,
                raw_update=update,
            )

        order.execute(
            dt=self._order_execution_dt(order),
            size=signed_fill,
            price=fill_price,
            closed=closed,
            closedvalue=closed_value,
            closedcomm=closed_commission,
            opened=opened,
            openedvalue=opened_value,
            openedcomm=opened_commission,
            margin=0.0,
            pnl=pnl,
            psize=psize,
            pprice=pprice,
        )

        self._cache_order_identifiers(order, update)

        self._set_status_after_fill(order)
        self.notify(order)
        if trade_key:
            self._seen_trade_ids.add(trade_key)
        return "applied"

    def _quarantine_option_fill(self, order, update, error_code, error_msg):
        """Quarantine an invalid option fill without mutating position facts."""
        try:
            raw_evidence = deepcopy(update)
        except Exception:
            _safe_log("warning", "btapibroker:7296 fallback on Exception")
            raw_evidence = dict(update) if isinstance(update, Mapping) else update
        order.addinfo(
            execution_unknown=True,
            ledger_mismatch=True,
            commission_source="estimated",
            actual_commission_known=False,
            pnl_status="PNL_INCOMPLETE",
            error_code=error_code,
            error_msg=error_msg,
            invalid_fill_evidence=raw_evidence,
        )
        self._position_audit_blocked = True
        self._position_audit_error = error_code
        trade_key = self._trade_dedupe_key(update, order=order)
        if trade_key:
            self._quarantined_trade_ids.add(trade_key)
            self._seen_trade_ids.add(trade_key)
        latch_evidence_loss = getattr(self.store, "latch_execution_evidence_loss", None)
        if callable(latch_evidence_loss):
            latch_evidence_loss(error_code)
        else:
            freeze_openings = getattr(self.store, "freeze_openings", None)
            if callable(freeze_openings):
                freeze_openings(error_code)
        self._request_order_reconcile(order)
        self.request_reconcile()
        self._emit_runtime_event(
            "option_fill_quarantined",
            level="ERROR",
            order_ref=getattr(order, "ref", None),
            error_code=error_code,
            error_msg=error_msg,
            status=order.getstatusname(),
            details=self._trade_update_details(update, order),
        )
        self.notify(order)
        return "quarantined"

    def _block_trade_identity_mismatch(self, order, update, error_code, error_msg):
        """Reject a fill whose explicit remote identity conflicts with its local intent."""
        order.addinfo(
            execution_unknown=True,
            ledger_mismatch=True,
            error_code=error_code,
            error_msg=error_msg,
        )
        self._position_audit_blocked = True
        self._position_audit_error = error_code
        trade_key = self._trade_dedupe_key(update, order=order)
        if trade_key:
            self._quarantined_trade_ids.add(trade_key)
            self._seen_trade_ids.add(trade_key)
        latch_evidence_loss = getattr(self.store, "latch_execution_evidence_loss", None)
        if callable(latch_evidence_loss):
            latch_evidence_loss(error_code)
        else:
            freeze_openings = getattr(self.store, "freeze_openings", None)
            if callable(freeze_openings):
                freeze_openings(error_code)
        self._request_order_reconcile(order)
        self.request_reconcile()
        self._emit_runtime_event(
            "trade_update_identity_mismatch",
            level="ERROR",
            order_ref=getattr(order, "ref", None),
            error_code=error_code,
            error_msg=error_msg,
            status=order.getstatusname(),
            details=self._trade_update_details(update, order),
        )
        self.notify(order)
        return "mismatch"

    @staticmethod
    def _normalise_quantity_unit(value):
        text = str(value or "").strip().lower().replace("-", "_")
        return {
            "contract": "contracts",
            "cont": "contracts",
            "coin": "base_asset",
            "base": "base_asset",
            "quote": "quote_asset",
        }.get(text, text)

    def _freeze_order_execution_contract(self, order, *, replace=False):
        """Capture the actual outbound identity once, outside later fill callbacks."""
        existing = self._order_execution_contracts.get(order.ref)
        if existing is not None and not replace:
            return existing
        sdk_contract = self._order_info_get(order, "sdk_execution_contract")
        if isinstance(sdk_contract, dict) and sdk_contract:
            raw = dict(sdk_contract)
            source = "sdk_request"
        else:
            quantity_unit = self._order_info_get(order, "quantity_unit")
            if quantity_unit in (None, "") and self._uses_async_commands():
                quantity_unit = (
                    self._contract_rules_for(self._position_key(order.data)).get("quantity_unit")
                    or "native"
                )
            raw = {
                "side": "buy" if order.isbuy() else "sell",
                "position_side": self._order_info_get(order, "position_side"),
                "offset": self._order_info_get(order, "offset"),
                "position_mode": self._order_info_get(
                    order, "position_mode", self.get_param("position_mode")
                ),
                "quantity_unit": quantity_unit,
                "requested_quantity": str(abs(float(order.size or 0.0))),
                "reduce_only": bool(self._order_info_get(order, "reduce_only", False)),
            }
            source = "broker_intent"
        contract = {
            "side": self._normalise_code_text(raw.get("side")),
            "position_side": normalize_position_side(raw.get("position_side")),
            "offset": normalize_position_offset(raw.get("offset")),
            "position_mode": normalize_position_mode(raw.get("position_mode")),
            "quantity_unit": self._normalise_quantity_unit(raw.get("quantity_unit")),
            "requested_quantity": str(raw.get("requested_quantity") or ""),
            "reduce_only": bool(raw.get("reduce_only", False)),
            "source": source,
        }
        self._order_execution_contracts[order.ref] = contract
        return contract

    def _trade_position_identity_error(self, order, update):
        """Compare every explicit normalized fill dimension with the local order intent."""
        contract = self._order_execution_contracts.get(order.ref)
        if contract is None:
            contract = self._freeze_order_execution_contract(order)
        fields = (
            (
                "position_side",
                ("position_side", "positionSide", "posSide"),
                contract.get("position_side"),
                normalize_position_side,
            ),
            (
                "offset",
                ("offset", "position_effect", "positionEffect"),
                contract.get("offset"),
                normalize_position_offset,
            ),
            (
                "position_mode",
                ("position_mode", "positionMode", "posMode"),
                contract.get("position_mode"),
                normalize_position_mode,
            ),
            (
                "quantity_unit",
                ("quantity_unit", "quantityUnit", "qty_unit", "qtyUnit"),
                contract.get("quantity_unit"),
                self._normalise_quantity_unit,
            ),
        )
        for name, aliases, expected_value, normalizer in fields:
            remote_value = self._extract_update_value(update, *aliases)
            if remote_value in (None, ""):
                continue
            try:
                remote = normalizer(remote_value)
            except (TypeError, ValueError):
                remote = None
            try:
                expected = normalizer(expected_value) if expected_value not in (None, "") else None
            except (TypeError, ValueError):
                expected = None
            if remote in (None, ""):
                return (
                    f"trade_{name}_unrecognized",
                    f"Remote trade {name} is not recognized for the matched local order",
                )
            if expected is not None and remote != expected:
                return (
                    f"trade_{name}_mismatch",
                    f"Remote trade {name} conflicts with the matched local order",
                )
        return None

    def _set_status_after_fill(self, order):
        """Account for late fills without reviving a remotely canceled remainder."""
        expected = float(self._order_info_get(order, "remote_terminal_filled", 0))
        executed = abs(float(order.executed.size or 0))
        if executed < expected - 1e-12:
            order.addinfo(execution_pending_trades=True)
            if executed > 0:
                order.partial()
            else:
                order.accept(self)
            return
        order.addinfo(execution_pending_trades=False)
        if self._order_remaining_qty(order) <= 1e-12:
            order.completed()
        else:
            terminal = self._order_info_get(order, "remote_terminal_status")
            if terminal == "canceled":
                order.cancel()
            elif terminal == "expired":
                order.status = order.Expired
                order.executed.dt = self._order_execution_dt(order)
            else:
                order.partial()
        if not order.alive():
            self._clear_order_mappings(order)

    def _apply_dual_side_trade_update(self, order, update, fill_qty, fill_price):
        isbuy = self._trade_update_is_buy(update, order)
        offset = self._order_info_get(order, "offset") or update.get("offset")
        position_side = (
            self._order_info_get(order, "position_side")
            or update.get("position_side")
            or update.get("positionSide")
            or update.get("posSide")
            or infer_position_side(isbuy, offset)
        )
        position_side = normalize_position_side(position_side)
        exec_size = fill_qty if isbuy else -fill_qty

        leg_position = self._get_leg_position(order.data, position_side)
        signed_position = self._make_signed_position(position_side, leg_position)
        pprice_orig = signed_position.price
        psize, pprice, opened, closed = signed_position.update(
            exec_size,
            fill_price,
            dt=self._execution_datetime(update),
        )

        closed_qty = abs(closed)
        opened_qty = abs(opened)
        comminfo = None
        is_option = False
        try:
            comminfo = order.comminfo or self.getcommissioninfo(order.data)
            is_option = isinstance(comminfo, CtpOptionPremium)
            if is_option:
                actual_commission, commission_error = self._remote_option_commission(update)
            else:
                actual_commission = self._remote_commission(update)
                commission_error = None
            closed_commission, opened_commission = self._execution_commissions(
                comminfo,
                fill_price,
                opened_qty,
                closed_qty,
                offset,
                actual_commission=actual_commission,
                fill_role=self._fill_commission_role(update),
            )
            closed_value = self._execution_value(
                comminfo,
                closed,
                pprice_orig or fill_price,
                role="close",
            )
            opened_value = self._execution_value(
                comminfo,
                opened,
                fill_price,
                is_buy=order.isbuy(),
                role="open",
            )
            pnl = comminfo.profitandloss(-closed, pprice_orig, fill_price) if closed else 0.0
        except Exception as exc:
            _safe_log("error", "btapibroker:7560 exception before re-raise (Exception)")
            if is_option:
                error_code = getattr(exc, "code", "option_fill_accounting_failed")
                return self._quarantine_option_fill(order, update, error_code, str(exc))
            raise

        self._apply_signed_position(position_side, leg_position, signed_position)
        self._sync_net_position(order.data)
        if is_option:
            self._annotate_option_commission(
                order,
                comminfo,
                actual_commission,
                fill_qty=fill_qty,
                commission_error=commission_error,
                raw_update=update,
            )

        order.execute(
            dt=self._order_execution_dt(order),
            size=exec_size,
            price=fill_price,
            closed=closed,
            closedvalue=closed_value,
            closedcomm=closed_commission,
            opened=opened,
            openedvalue=opened_value,
            openedcomm=opened_commission,
            margin=0.0,
            pnl=pnl,
            psize=psize,
            pprice=pprice,
        )

        order.addinfo(position_side=position_side)
        if offset is not None:
            order.addinfo(offset=offset)
        self._cache_order_identifiers(order, update)

        self._set_status_after_fill(order)
        self.notify(order)
        return "applied"

    def _apply_error_update(self, update):
        """Apply a normalized remote error update to a tracked order when possible."""
        order = self._lookup_order(update)
        if order is None or not order.alive():
            return

        self._cache_order_identifiers(order, update)
        error_code = str(self._redact_runtime_value(update.get("error_code") or "remote_error"))
        error_msg = str(
            self._redact_runtime_value(update.get("error_msg") or update.get("status_msg") or "")
        )
        order.addinfo(error_code=error_code, error_msg=error_msg)
        if order.status != order.Rejected:
            order.reject(self)
            self._clear_order_mappings(order)
            self.notify(order)

    def _clear_order_mappings(self, order):
        """Drop cached identifier mappings once an order reaches a terminal state."""
        for key, mapped_order in list(self._orders_by_external_id.items()):
            if mapped_order is order:
                self._orders_by_external_id.pop(key, None)
        for key, mapped_order in list(self._orders_by_client_ref.items()):
            if mapped_order is order:
                self._orders_by_client_ref.pop(key, None)

    def _client_ref_scope(self, *, order=None, update=None):
        """Return the venue scope used by SDK client-order identifiers."""
        if isinstance(update, dict):
            scope = self._extract_update_value(
                update,
                "exchange_name",
                "venue",
            )
            if scope not in (None, ""):
                return str(scope)
        if order is None or not bool(getattr(self.store, "_sdk_mode", False)):
            return None
        resolver = getattr(self.store, "_sdk_exchange", None)
        if not callable(resolver):
            return None
        try:
            return str(resolver(self._position_key(order.data)))
        except Exception:
            _safe_log("warning", "btapibroker:7646 fallback on Exception")
            return None

    def _remember_client_ref(self, order, order_ref, update=None):
        """Index SDK references by venue while preserving legacy raw aliases."""
        reference = str(order_ref)
        scope = self._client_ref_scope(order=order, update=update)
        key = (scope, reference) if scope is not None else reference
        self._orders_by_client_ref[key] = order

    def _order_for_client_ref(self, order_ref, update=None):
        """Resolve a client id only when its venue binding is unambiguous."""
        reference = str(order_ref)
        scope = self._client_ref_scope(update=update)
        sdk_mode = bool(getattr(self.store, "_sdk_mode", False))
        if sdk_mode and scope is not None:
            return self._orders_by_client_ref.get((scope, reference))
        if not sdk_mode and scope is not None:
            order = self._orders_by_client_ref.get((scope, reference))
            if order is not None:
                return order
        raw = self._orders_by_client_ref.get(reference)
        if raw is not None and not sdk_mode:
            return raw
        matches = {
            id(mapped): mapped
            for key, mapped in self._orders_by_client_ref.items()
            if isinstance(key, tuple) and len(key) == 2 and key[1] == reference
        }
        if scope is None and len(matches) == 1:
            return next(iter(matches.values()))
        return None

    def _lookup_order(self, update):
        """Resolve a local order object from normalized broker update identifiers."""
        # SDK events have already been correlated by BtApiStore with a local
        # Backtrader reference. Prefer that collision-free identity before any
        # provider-supplied id, which may be reused by another venue.
        details = update.get("details") or {}
        bt_order_ref = details.get("bt_order_ref") or update.get("bt_order_ref")
        if bt_order_ref in self.orders:
            return self.orders[bt_order_ref]
        if bt_order_ref not in (None, ""):
            try:
                normalized_ref = int(bt_order_ref)
            except (TypeError, ValueError):
                normalized_ref = None
            if normalized_ref in self.orders:
                return self.orders[normalized_ref]

        order_ref = self._remote_client_order_ref(update)
        sdk_mode = bool(getattr(self.store, "_sdk_mode", False))
        if sdk_mode and order_ref not in (None, ""):
            order = self._order_for_client_ref(order_ref, update)
            if order is not None:
                return order
            # A scoped SDK client id that does not match is stronger evidence
            # than an unscoped venue order id. Fail closed on the mismatch.
            return None

        external_id = self._remote_external_order_id(update)
        if external_id not in (None, ""):
            order = self._orders_by_external_id.get(str(external_id))
            if order is not None:
                return order

        if order_ref not in (None, "") and not sdk_mode:
            order = self._order_for_client_ref(order_ref, update)
            if order is not None:
                return order
            try:
                normalized_order_ref = int(str(order_ref).strip())
            except (TypeError, ValueError):
                normalized_order_ref = None
            if normalized_order_ref in self.orders:
                return self.orders[normalized_order_ref]
            if order_ref in self.orders:
                return self.orders[order_ref]

        return None

    def _cache_order_identifiers(self, order, update):
        """Attach provider identifiers from a remote update to a local order."""
        external_id = self._remote_external_order_id(update)
        order_ref = self._remote_client_order_ref(update)
        if external_id not in (None, ""):
            order.addinfo(external_order_id=external_id)
            self._orders_by_external_id[str(external_id)] = order
        if order_ref not in (None, ""):
            order.addinfo(ctp_order_ref=order_ref)
            self._remember_client_ref(order, order_ref, update)
        for key in ("front_id", "session_id", "exchange_id"):
            value = self._extract_update_value(update, key)
            if value not in (None, ""):
                order.addinfo(**{key: value})

        # Evidence fields are cached only when the native update supplied the
        # complete tuple.  Never derive them from a Backtrader ref or session
        # state: missing native values must remain missing.
        native_sys_id = self._extract_update_value(update, "order_sys_id", "OrderSysID")
        native_order_ref = self._extract_update_value(update, "order_ref", "OrderRef")
        native_trade_id = self._extract_update_value(update, "trade_id", "TradeID")
        native_generation = self._extract_update_value(
            update, "connection_generation", "ConnectionGeneration"
        )
        try:
            native_generation = int(native_generation)
        except (TypeError, ValueError):
            native_generation = 0
        if (
            native_sys_id not in (None, "")
            and native_order_ref not in (None, "")
            and native_generation > 0
        ):
            order.addinfo(
                order_sys_id=native_sys_id,
                connection_generation=native_generation,
            )
            if native_trade_id not in (None, ""):
                order.addinfo(trade_id=native_trade_id)

    @staticmethod
    def _order_info_get(order, key, default=None):
        """Read order.info without triggering AutoOrderedDict auto-vivification."""
        info = getattr(order, "info", None)
        if info is None:
            return default
        getter = getattr(info, "get", None)
        if callable(getter):
            value = getter(key, default)
            return default if value in (None, "") else value
        value = getattr(info, key, default)
        return default if value in (None, "") else value

    @classmethod
    def _trade_update_is_buy(cls, update, order=None):
        side_present, is_buy = cls._explicit_trade_side(update)
        if not side_present or is_buy is None:
            return bool(order.isbuy()) if order is not None else True
        return is_buy

    @classmethod
    def _explicit_trade_side(cls, update):
        """Return whether a trade supplied a side and its normalized direction."""
        side = cls._extract_update_value(
            update,
            "side",
            "Side",
            "direction",
            "Direction",
            "trade_side",
            "tradeSide",
        )
        if side in (None, ""):
            return False, None

        text = cls._normalise_code_text(side)
        if text in {"buy", "long", "b", "bid", "0"}:
            return True, True
        if text in {"sell", "short", "s", "ask", "1"}:
            return True, False
        return True, None

    @staticmethod
    def _extract_update_value(update, *keys):
        """Read a top-level or detail payload field from a broker update."""
        details = update.get("details") or {}
        for key in keys:
            value = update.get(key)
            if value not in (None, ""):
                return value
            value = details.get(key)
            if value not in (None, ""):
                return value
        return None

    @classmethod
    def _uses_okx_fee_sign(cls, update):
        values = [
            cls._extract_update_value(
                update,
                "exchange",
                "exchange_id",
                "exchange_name",
                "provider",
                "gateway",
                "broker",
            )
        ]
        details = update.get("details") or {}
        values.extend(
            details.get(key)
            for key in (
                "exchange",
                "exchange_id",
                "exchange_name",
                "provider",
                "gateway",
                "broker",
            )
        )
        return any("OKX" in str(value or "").upper() for value in values)

    @classmethod
    def _remote_commission(cls, update):
        keys = (
            "commission",
            "comm",
            "fee",
            "fees",
            "exec_fee",
            "execFee",
            "execFeeV2",
            "fill_fee",
            "fillFee",
            "trade_fee",
            "trade_commission",
            "commission_amount",
            "n",
        )
        details = update.get("details") or {}
        for key in keys:
            for source in (update, details):
                value = source.get(key)
                if value in (None, ""):
                    continue
                try:
                    commission = float(value)
                except (TypeError, ValueError):
                    _safe_log("debug", "btapibroker:7863 ignored TypeError,ValueError")
                    continue
                if not math.isfinite(commission):
                    continue
                # Explicit SDK normalization uses signed costs/rebates. Keep
                # unmarked legacy commission and raw fee conventions intact.
                if cls._truthy(cls._extract_update_value(update, "commission_normalized")):
                    return commission
                if key in {"fee", "trade_fee", "trade_commission"} and cls._uses_okx_fee_sign(
                    update
                ):
                    return -commission
                return abs(commission)
        return None

    @classmethod
    def _remote_option_commission(cls, update):
        """Parse option commission evidence without bool/coercion fallthrough."""
        forced_error = update.get("_option_commission_error")
        if forced_error not in (None, ""):
            return None, str(forced_error)
        keys = (
            "commission",
            "comm",
            "fee",
            "fees",
            "exec_fee",
            "execFee",
            "execFeeV2",
            "fill_fee",
            "fillFee",
            "trade_fee",
            "trade_commission",
            "commission_amount",
            "n",
        )
        details = update.get("details") or {}
        values = []
        for key in keys:
            for source_name, source in (("update", update), ("details", details)):
                if key not in source or source[key] in (None, ""):
                    continue
                value = source[key]
                if isinstance(value, bool):
                    return None, "option_commission_boolean"
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    return None, "option_commission_invalid"
                if not math.isfinite(number):
                    return None, "option_commission_nonfinite"
                values.append((f"{source_name}.{key}", number))
        if not values:
            return None, "option_commission_missing"
        first = values[0][1]
        if any(number != first for _, number in values[1:]):
            return None, "option_commission_conflict"
        return first, None

    @classmethod
    def _execution_commissions(
        cls,
        comminfo,
        price,
        opened_qty,
        closed_qty,
        offset=None,
        actual_commission=None,
        fill_role=None,
    ):
        """Return closed/opened commissions using offset-specific futures fees."""
        opened_qty = abs(float(opened_qty or 0.0))
        closed_qty = abs(float(closed_qty or 0.0))
        if actual_commission is not None:
            total_commission = float(actual_commission or 0.0)
            total_qty = opened_qty + closed_qty
            if total_qty <= 0.0:
                return 0.0, 0.0
            if closed_qty <= 0.0:
                return 0.0, total_commission
            if opened_qty <= 0.0:
                return total_commission, 0.0
            closed_commission = total_commission * (closed_qty / total_qty)
            return closed_commission, total_commission - closed_commission
        if comminfo is None:
            return 0.0, 0.0
        fill_role = cls._normalise_fill_commission_role(fill_role)
        close_role = cls._close_commission_role(offset)
        if isinstance(comminfo, CtpOptionPremium):
            # CTP option fee dimensions are tied to open/close/close-today.
            # A generic maker/taker liquidity label must never replace that
            # accounting role.  Futures/crypto keep their existing fallback.
            closed_role = close_role
            opened_role = "open"
        else:
            closed_role = close_role
            if close_role not in {"close_today", "close_yesterday"}:
                closed_role = fill_role or close_role
            opened_role = fill_role or "open"
        closed_commission = (
            cls._commission_for_role(
                comminfo,
                closed_qty,
                price,
                closed_role,
            )
            if closed_qty > 0.0
            else 0.0
        )
        opened_commission = (
            cls._commission_for_role(comminfo, opened_qty, price, opened_role)
            if opened_qty > 0.0
            else 0.0
        )
        return closed_commission, opened_commission

    @classmethod
    def _fill_commission_role(cls, update):
        role = cls._normalise_fill_commission_role(
            cls._extract_update_value(
                update,
                "commission_role",
                "fill_role",
                "liquidity_role",
                "liquidity",
                "trade_type",
                "tradeType",
                "exec_type",
                "execType",
                "match_type",
                "maker_taker",
            )
        )
        if role is not None:
            return role

        for key in ("is_maker", "isMaker", "maker", "m"):
            value = cls._extract_update_value(update, key)
            if value in (None, ""):
                continue
            return "maker" if cls._truthy(value) else "taker"
        return None

    @staticmethod
    def _normalise_fill_commission_role(value):
        if value in (None, ""):
            return None
        text = str(value).strip().lower().replace("-", "_")
        if text in {"maker", "m", "make", "post_only", "postonly", "liquidity_maker"}:
            return "maker"
        if text in {"taker", "t", "take", "liquidity_taker"}:
            return "taker"
        if "maker" in text:
            return "maker"
        if "taker" in text:
            return "taker"
        return None

    @staticmethod
    def _truthy(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        text = BtApiBroker._normalise_code_text(value)
        return text in {"1", "true", "yes", "y", "maker", "m"}

    @staticmethod
    def _close_commission_role(offset):
        offset_text = str(offset or "").strip().lower()
        if offset_text in {"close_today", "closetoday"}:
            return "close_today"
        if offset_text in {"close_yesterday", "closeyesterday"}:
            return "close_yesterday"
        return "close"

    @staticmethod
    def _commission_for_role(comminfo, size, price, role):
        try:
            return float(comminfo.getcommission(size, price, role=role) or 0.0)
        except TypeError:
            return float(comminfo.getcommission(size, price) or 0.0)

    @staticmethod
    def _execution_value(comminfo, size, price, is_buy=None, role="open"):
        """Return an execution value using the commission scheme's contract rules."""
        if isinstance(comminfo, CtpOptionPremium):
            # Keep option raw inputs intact until the option validator sees
            # them.  In particular, bool is an int subclass and must not turn
            # into one contract or one unit of premium.
            if isinstance(size, bool) or isinstance(price, bool):
                raise OptionAccountingError(
                    "option_execution_value_invalid",
                    "option_execution_value_invalid: boolean is not a numeric execution input",
                )
            if size is None or size == 0:
                return 0.0
            try:
                return abs(float(comminfo.getpremiumvalue(size, price) or 0.0))
            except OptionAccountingError:
                _safe_log("error", "btapibroker:8062 re-raising OptionAccountingError")
                raise
            except Exception as exc:
                _safe_log("error", "btapibroker:8064 re-raising Exception")
                raise OptionAccountingError(
                    "option_execution_value_invalid",
                    "option_execution_value_invalid: option transaction value is unavailable",
                ) from exc
        try:
            size = float(size or 0.0)
            price = float(price or 0.0)
        except Exception as exc:
            _safe_log("error", "btapibroker:8086 exception before re-raise (Exception)")
            if isinstance(comminfo, CtpOptionPremium):
                raise OptionAccountingError(
                    "option_execution_value_invalid",
                    "option_execution_value_invalid: option transaction value is unavailable",
                ) from exc
            raise
        if not size:
            return 0.0
        if comminfo is None:
            return abs(size) * abs(price)
        try:
            return abs(float(comminfo.getoperationcost(size, price) or 0.0))
        except OptionAccountingError:
            _safe_log("error", "btapibroker:8085 re-raising OptionAccountingError")
            raise
        except Exception as exc:
            _safe_log("warning", "btapibroker:8102 fallback on Exception")
            if isinstance(comminfo, CtpOptionPremium):
                raise OptionAccountingError(
                    "option_execution_value_invalid",
                    "option_execution_value_invalid: option transaction value is unavailable",
                ) from exc
            return abs(size) * abs(price)

    @staticmethod
    def _annotate_option_commission(
        order,
        comminfo,
        actual_commission,
        *,
        fill_qty=0.0,
        commission_error=None,
        raw_update=None,
    ):
        """Keep cumulative actual-versus-estimated option fee provenance."""
        if not isinstance(comminfo, CtpOptionPremium):
            return
        info = getattr(order, "info", None)
        known_qty = float(info.get("option_fee_known_quantity", 0.0) or 0.0)
        unknown_qty = float(info.get("option_fee_unknown_quantity", 0.0) or 0.0)
        quantity = abs(float(fill_qty or 0.0))
        if actual_commission is None:
            unknown_qty += quantity
        else:
            known_qty += quantity
        order.addinfo(
            option_fee_known_quantity=known_qty,
            option_fee_unknown_quantity=unknown_qty,
        )
        if actual_commission is None or unknown_qty > 1e-12:
            if raw_update is not None:
                prior = info.get("option_commission_evidence")
                evidence = list(prior) if isinstance(prior, list) else []
                evidence.append(deepcopy(raw_update))
                order.addinfo(option_commission_evidence=evidence)
            if commission_error:
                order.addinfo(option_commission_error=commission_error)
            order.addinfo(
                commission_source="estimated",
                actual_commission_known=False,
                pnl_status="PNL_INCOMPLETE",
            )
            return
        order.addinfo(
            commission_source="actual",
            actual_commission_known=True,
            pnl_status="COMPLETE",
        )

    @staticmethod
    def _execution_datetime(update):
        """Convert a remote broker update timestamp into a best-effort datetime."""
        stamp = update.get("timestamp")
        if isinstance(stamp, _dt.datetime):
            return stamp
        if isinstance(stamp, str) and stamp:
            today = _dt.date.today()
            for fmt in ("%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d %H:%M:%S"):
                try:
                    parsed = _dt.datetime.strptime(stamp, fmt)
                except ValueError:
                    _safe_log("debug", "btapibroker:8151 ignored ValueError")
                    continue
                if fmt == "%H:%M:%S":
                    return _dt.datetime.combine(today, parsed.time())
                return parsed
        # Naive UTC fallback (consistent with the naive datetimes returned above,
        # used for backtrader order bookkeeping). utcnow() is deprecated in 3.12+.
        return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _order_execution_dt(order):
        """Pick a stable execution dt compatible with backtrader order bookkeeping."""
        if BtApiBroker._order_info_get(
            order, "service_execution_recovery_v2_trade_time_verified", False
        ) is True:
            match_datenum = BtApiBroker._order_info_get(
                order, "service_execution_recovery_v2_match_datenum"
            )
            if (
                type(match_datenum) is not float
                or not math.isfinite(match_datenum)
                or match_datenum <= 0.0
            ):
                raise ValueError("managed paper execution time projection is invalid")
            return match_datenum
        try:
            if len(order.data):
                return order.data.datetime[0]
        except Exception as e:
            _safe_log("warning", "btapibroker:8182 fallback on Exception")
            _safe_log("debug", "Failed to get order execution datetime: %s", e)
        return 0.0
