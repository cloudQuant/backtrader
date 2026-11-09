#!/usr/bin/env python
"""Unified bt_api_py-backed live broker."""

from __future__ import annotations

import collections
import datetime as _dt
import math
import threading
import time
from collections.abc import Mapping
from copy import copy, deepcopy
from decimal import Decimal
from typing import Any, DefaultDict, Dict, List, Optional

from ..broker import BrokerBase
from ._btapi_recovery import ServiceRecoveryBrokerMixin
from ._btapi_reconciliation import BrokerReconciliationMixin
from ._btapi_owner_fence import AccountOwnerFenceBrokerMixin
from ._btapi_owner_fence import finish_dispatch_lease as _finish_owner_lease
from ._btapi_owner_fence import lease_outcome_for_error as _owner_lease_error_outcome
from ._btapi_owner_fence import lease_outcome_for_response as _owner_lease_response_outcome
from ._btapi_gateway_events import GatewayExecutionEventsBrokerMixin
from ._btapi_gateway_notifications import GatewayNotificationsBrokerMixin
from ._btapi_strategy_events import StrategyNotificationRecoveryBrokerMixin
from ._btapi_strategy_ledger import StrategyLedgerBrokerMixin
from ._btapi_direct_mode import BtApiDirectModeMixin, direct_params
from ..order import BuyOrder, OrderBase, OrderExecutionBit, SellOrder
from ..position import (
    Position,
    POSITION_MODE_DUAL_SIDE,
    infer_position_side,
    normalize_order_position_meta,
    normalize_position_mode,
    normalize_position_offset,
    normalize_position_side,
    signed_position_size,
)
from ..utils.redaction import redact_diagnostic as _redact_diagnostic
from ..service.service_execution_adapter import ServiceExecutionReadError
from ..utils.log_message import get_logger

logger = get_logger(__name__)
_LOGGING_HEALTH: "collections.Counter[str]" = collections.Counter()


class _OrderCorrelationUnavailableError(RuntimeError):
    """A write cannot be dispatched without an SDK-bound neutral identity."""

    code = "order_correlation_unsupported"
    definite_reject = True


def _safe_log(level, message, *args):
    """Write diagnostics without letting a log sink alter broker semantics."""
    try:
        getattr(logger, level)(_redact_diagnostic(message), *map(_redact_diagnostic, args))
    except Exception:
        # No logging here by design: the sink itself just failed; calling the
        # logger again would raise before the health counter is incremented.
        _LOGGING_HEALTH["logging_errors"] += 1


_DATA_NAME_KEYS = (
    "data_name",
)
_CONFIRMED_TERMINAL_STATUSES = frozenset({"completed", "canceled", "rejected", "expired"})


class BtApiBroker(
    GatewayNotificationsBrokerMixin,
    BtApiDirectModeMixin,
    AccountOwnerFenceBrokerMixin,
    StrategyLedgerBrokerMixin,
    StrategyNotificationRecoveryBrokerMixin,
    GatewayExecutionEventsBrokerMixin,
    ServiceRecoveryBrokerMixin,
    BrokerReconciliationMixin,
    BrokerBase,
):
    """Broker implementation that routes live orders through BtApiStore."""

    def get_futures_contracts(self, route, exchange_id, product_id, *, environment,
                              allow_reference=False, **limits):
        """Refresh both ranks once through Store; no automatic bar refresh.

        ``route`` is the SDK route. ``exchange_id`` and ``product_id`` must
        match the provider's venue and product identifiers. The default fails
        closed because market freshness is unavailable. Reference-only use
        requires explicit opt-in and does not establish real-time data or
        trading authority.
        """
        if self.store is None:
            raise RuntimeError("futures contract lookup requires a configured Store")
        return self.store.get_futures_contracts(
            route, exchange_id, product_id, environment=environment,
            allow_reference=allow_reference, **limits,
        )

    def get_main_contract(self, *args, **kwargs):
        """Refresh and return rank one; use the combined result for both ranks."""
        return self.get_futures_contracts(*args, **kwargs).main

    def get_secondary_contract(self, *args, **kwargs):
        """Refresh and return rank two, or None when no second rank exists."""
        return self.get_futures_contracts(*args, **kwargs).secondary

    # Remote order updates do not depend on the arrival of a market-data bar.
    next_without_bar = True

    params = (
        ("store", None),
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
        ("max_order_size", 0),
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
        ("execution_recovery", None),
    ) + direct_params()

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
        self.notifs: collections.deque = collections.deque()
        self.orders = collections.OrderedDict()
        self._direct_init_state()
        self._service_execution_session = None
        self._managed_runtime_session = None
        self._recovery_queued_receipts = set()
        self._recovery_applied_receipts = set()
        self._recovery_orders_by_intent = {}
        self._recovery_pending_snapshot_notifications = {}
        self._service_execution_recovery_feeds = {}
        self._service_execution_recovery_feed_names = {}
        self._service_execution_recovery_strategy = None
        self._service_execution_recovery_suppress_notifications = False
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
        self._orders_by_external_id = {}
        self._orders_by_client_ref = {}
        self._order_correlations = {}
        self._verified_risk_reducing_orders = set()
        self._position_quantity_units = {}
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
        self._execution_reconciliation_required = False
        self._execution_reconciliation_rounds = 0
        self._execution_reconciliation_consistency_digest = None
        self._execution_reconciliation_snapshot_id = None
        self._execution_reconciliation_event_epoch = 0
        self._execution_reconciliation_round_event_epoch = None
        self._execution_reconciliation_reason = ""
        self._execution_reconciliation_pending = False
        self._execution_reconciliation_callbacks = []
        self._last_execution_reconciliation_result = None
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
        session = self._managed_runtime_session
        if session is None:
            session = self._service_execution_session
        if session is not None:
            session.broker_starting(self)
        super().start()

        if self.store is None:
            raise ValueError("BtApiBroker requires a BtApiStore instance")

        if self._direct_active():
            return
        if self._direct_selected():
            # Iteration 62 direct mode: no execution component (see
            # ``_btapi_direct_mode``); live_state reconciliation gates writes.
            return self._direct_start()

        if self._live_started and self._startup_ready and self.store.is_connected:
            return

        is_service_read_only = bool(getattr(self.store, "_service_read_only", False))
        if not self.supports_position_mode(self.get_param("position_mode")):
            raise ValueError("The SDK Store does not support the requested position mode")

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
            if is_sdk and not market_data_only:
                required_store_methods = (
                    "prepare_order_correlation",
                    "submit_order",
                    "cancel_order",
                    "verify_order_response",
                    "verify_cancel_response",
                    "enqueue_order_reconciliation",
                )
                if any(
                    not callable(getattr(self.store, name, None))
                    for name in required_store_methods
                ):
                    raise ValueError(
                        "SDK trading requires correlated write and typed reconciliation ports"
                    )
            if not market_data_only and bool(self.p.sdk_preflight) and self._uses_async_commands():
                self._run_sdk_preflight()
            self._refresh_account(force=True, raise_errors=True)
            self._sync_positions(force=True, raise_errors=True)
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

            quantity = 1
            snapshot = self.store.get_trading_readiness(
                symbol,
                quantity,
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

    @staticmethod
    def _normalise_startup_account_state(value):
        from bt_api_py.startup_recovery import normalise_startup_account_state

        return normalise_startup_account_state(
            value, on_unreadable=lambda: _safe_log("warning", "btapibroker:881 fallback on Exception")
        )

    def supports_position_mode(self, mode):
        """Return whether the broker can operate in the requested position mode.

        Any non-dual-side mode (``"net"`` or its aliases) is always
        supported because it does not require special handling from the
        underlying store. Dual-side mode is supported when:

        * the underlying store advertises it via
          ``store.supports_position_mode("dual_side")``, or
        * the broker can maintain separate long and short Backtrader ledgers.

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
        return True

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
        from ..service.service_execution_session import ServiceExecutionSession

        if not isinstance(session, ServiceExecutionSession):
            raise TypeError("session must be a ServiceExecutionSession")
        if self._managed_runtime_session is not None:
            raise RuntimeError("managed runtime session is already attached")
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

    def attach_managed_runtime_session(self, session):
        """Attach the generic SDK host before Store/Broker startup."""
        from ..service.managed_runtime_host import ManagedRuntimeCerebroSession

        if not isinstance(session, ManagedRuntimeCerebroSession):
            raise TypeError("session must be a ManagedRuntimeCerebroSession")
        if self._service_execution_session is not None:
            raise RuntimeError("managed runtime and service execution sessions are exclusive")
        if self._managed_runtime_session is not None:
            raise RuntimeError("managed runtime session is already attached")
        store = self.store
        composition = getattr(session, "composition", None)
        composition_api = getattr(composition, "api", None)
        store_api = getattr(store, "sdk_api", None)
        if (
            store is None
            or store_api is None
            or composition_api is None
            or store_api is not composition_api
        ):
            raise RuntimeError("managed runtime API must be the exact BtApiStore sdk_api")
        if (
            self._live_started
            or self._startup_ready
            or bool(getattr(store, "_started", False))
            or bool(store.is_connected)
            or bool(getattr(store, "managed_execution_active", False))
        ):
            raise RuntimeError("managed runtime session must attach before startup")
        session.bind_broker(self)
        bind_store_api = getattr(store, "_bind_managed_runtime_api", None)
        if not callable(bind_store_api):
            error = RuntimeError("managed runtime Store ownership hook unavailable")
            session.broker_binding_failed(self, error)
            raise error
        try:
            bind_store_api(composition_api)
        except BaseException as error:
            session.broker_binding_failed(self, error)
            raise
        self._managed_runtime_session = session
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
        if self._direct_owns_stop():
            return self._direct_stop()
        session = self._managed_runtime_session
        if session is None:
            session = self._service_execution_session
        if session is None:
            return self._stop_live_resources()

        try:
            session.broker_stopping(self)
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
                try:
                    store_result = self.store.stop()
                except Exception:
                    self._shutdown_summary = {
                        "status": "FAIL",
                        "store_shutdown_state": "UNPROVEN",
                        "flat_proven": False,
                        "live_winddown_started": False,
                        "reason": "store_shutdown_failed",
                    }
                    raise
                store_state = (
                    store_result.get("shutdown_state")
                    if isinstance(store_result, Mapping)
                    else None
                )
                if store_state == "PASS":
                    status = "PASS"
                    reason = "store_shutdown_complete"
                elif store_state == "FAIL":
                    status = "FAIL"
                    reason = "store_shutdown_failed"
                else:
                    status = "INCOMPLETE"
                    reason = "store_shutdown_incomplete"
                self._shutdown_summary = {
                    "status": status,
                    "store_shutdown_state": store_state or "UNPROVEN",
                    "flat_proven": False,
                    "live_winddown_started": False,
                    "reason": reason,
                }
                # Preserve the historical stop() return value; the Broker's
                # public summary separately records what the Store proved.
                return store_result
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
            strict_shutdown_evidence = True
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
            if self._requires_explicit_offset(data):
                # Provider-specific close-price and offset selection belongs
                # to the SDK execution owner.  This Broker has no typed
                # managed-position-close capability yet.
                missing_data.append((key, position_side, "managed_close_unsupported"))
                return
            method = self.buy if is_buy else self.sell
            kwargs: "Dict[str, Any]" = {"exectype": OrderBase.Market}
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
        from bt_api_py.reconciliation_projection_inputs import has_flat_execution_projection

        return has_flat_execution_projection(
            result, is_clean=self._reconcile_proves_clean_execution, zero_tolerance=1e-12
        )

    def _reconcile_proves_clean_execution(self, result):
        from bt_api_py.reconciliation_projection_inputs import has_clean_execution_projection

        return has_clean_execution_projection(result)

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
        from bt_api_py.account_risk_projection import incomplete_account_risk_projection

        return incomplete_account_risk_projection(snapshot, error_code)

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

    def bind_direct_strategy_account_book(self, strategy, reader):
        """Attach a direct-mode strategy book view to its actual Strategy.

        ``reader`` is an SDK direct reader (for example
        ``bt_api_py.strategy_ledger.StrategyLedgerReader``)
        exposing ``strategy_ref``, ``account_ref`` and ``snapshot()``. The
        Strategy's ``strategy_ref``/``account_ref`` parameters must match the
        reader, the Strategy must use this Broker, and one Strategy can bind
        one view only. A service session, when active, stays the sole owner of
        strategy books, so direct binding is refused there. Ordinary Broker
        getters keep their account-level semantics.
        """

        from backtrader.service.service_strategy_account_book import (
            DirectStrategyAccountBookView,
        )
        from backtrader.strategy import Strategy

        if self._service_execution_session is not None:
            raise ValueError("strategy books are owned by the active service session")
        if not isinstance(strategy, Strategy):
            raise ValueError("a real Strategy instance is required")
        if getattr(strategy, "broker", None) is not self:
            raise ValueError("strategy does not use this broker")
        view = DirectStrategyAccountBookView(reader)
        params = getattr(strategy, "p", None)
        if (
            getattr(params, "strategy_ref", None) != view.strategy_ref
            or getattr(params, "account_ref", None) != view.account_ref
        ):
            raise ValueError("strategy identity does not match the account-book reader")
        existing = getattr(strategy, "account_book", None)
        if existing is not None:
            raise ValueError("strategy already has an account book")
        bound = getattr(self, "_direct_strategy_books", None)
        if bound is None:
            bound = {}
            self._direct_strategy_books = bound
        key = (view.strategy_ref, view.account_ref)
        owner = bound.get(key)
        if owner is not None and owner is not strategy:
            raise ValueError("strategy account book is already bound to another strategy")

        def _refuse_rebinding(current):
            if current is not None:
                raise ValueError("strategy already has an account book")

        # Iteration 60 G4: bind under the financial scope lock, so the bind
        # cannot interleave with an Analyzer financial callback tree.
        from ..analyzers._strategy_scope import bind_account_book

        bind_account_book(strategy, view, check=_refuse_rebinding)
        bound[key] = strategy
        return view

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
        if self._direct_active():
            return self._cash
        if not self._uses_async_commands():
            self._refresh_account(force=bool(self.p.force_refresh_queries), raise_errors=True)
        return self._cash

    def getvalue(self, datas=None) -> float:
        """Return current portfolio value."""
        if self._direct_active():
            return self._value
        if not self._uses_async_commands():
            self._refresh_account(force=bool(self.p.force_refresh_queries), raise_errors=True)
        return self._value

    def getposition(self, data, clone=True, side=None):
        """Return the cached position for a given data feed."""
        if self._direct_active():
            return self._direct_getposition(data, clone=clone, side=side)
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

        from ..factor_execution.factor_execution import execution_position_snapshot

        return execution_position_snapshot(self, data)

    def execution_order_snapshot(self):
        """Return alive local orders without querying the Store or provider."""

        from ..factor_execution.factor_execution import execution_order_snapshot

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
        if self._direct_active():
            return self._direct_submit(order)
        if getattr(self, "factor_execution_coordinator", None) is not None:
            return self._reject_order(
                order,
                "managed_execution_authorization_unavailable",
                "Managed execution requires the SDK authorization and completion contract.",
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
            self._freeze_position_mode("first order submission")
            safety_error = self._placement_safety_error(order)
            if safety_error is not None:
                code, message = safety_error
                return self._reject_order(order, code, message)
            audit_error = self._position_audit_order_error(order)
            if audit_error is not None:
                code, message = audit_error
                return self._reject_order(order, code, message)
            rules_error = self._execution_rules_error(order)
            if rules_error is not None:
                code, message = rules_error
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

        # Iteration 60 (P0-3): a ledger-gated account admits each order
        # against the strategy's own book before anything is dispatched.
        ledger_error = self._direct_ledger_admission_error(order)
        if ledger_error is not None:
            code, message = ledger_error
            return self._reject_order(order, code, message)

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

        correlation = None
        try:
            order.submit(self)
            order.addcomminfo(self.getcommissioninfo(order.data))
            self._freeze_order_execution_contract(order, replace=True)
            if self.store is None:
                raise ValueError("BtApiBroker requires a BtApiStore instance")
            # A managed route (ServiceExecutionSession, managed runtime) owns
            # the write identity and verifies its typed result itself; the
            # direct SDK correlation applies only to Store-dispatched writes.
            # (Iteration 60: the iteration-53 split required it for every
            # SDK-mode write, so every managed order became UNKNOWN.)
            managed_route = bool(getattr(self.store, "managed_execution_active", False))
            if not managed_route:
                correlation = self._prepare_order_correlation(order)
                self._order_correlations[order.ref] = correlation
            # Iteration 60 (G1): early owner pre-check, then a synchronous
            # Store write runs under an SDK dispatch lease (queued Stores
            # take the lease in their command worker).
            fence_error = self._account_owner_fence_error()
            owner_lease = None
            if fence_error is None:
                owner_lease, fence_error = self._acquire_account_owner_lease("submit", order)
            if fence_error is not None:
                self._order_correlations.pop(order.ref, None)
                code, message = fence_error
                return self._reject_order(order, code, message)
            try:
                response = self.store.submit_order(order)
            except BaseException as exc:
                _finish_owner_lease(owner_lease, _owner_lease_error_outcome(exc))
                raise
            _finish_owner_lease(owner_lease, _owner_lease_response_outcome(response))
            queued_receipt = bool(
                isinstance(response, Mapping)
                and response.get("kind") == "command_receipt"
                and response.get("queued") is True
            )
            if queued_receipt:
                # Store queue admission is only a handoff receipt.  The order
                # remains Submitted until the worker posts an SDK-verified
                # acknowledgement through command_completion.
                self.orders[order.ref] = order
                order.addinfo(submit_command_queued=True)
                self.notify(order)
                return order
            if not managed_route and not self._verify_order_response(correlation, response):
                return self._accept_unknown_submission(
                    order,
                    RuntimeError("sdk_order_response_unverified"),
                    "sdk_order_response_unverified",
                )
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
            if managed_route:
                return self._apply_managed_submit_projection(order, response)
            if (
                isinstance(response, Mapping)
                and response.get("kind") == "command_receipt"
                and response.get("queued") is not True
            ):
                return self._reject_order(
                    order,
                    str(response.get("error_code") or "command_queue_rejected"),
                    str(response.get("error_msg") or "SDK command queue rejected the order"),
                )
            submit_error = self._submit_response_error(response)
            if submit_error is not None:
                error_code, error_msg = submit_error
                self._attach_remote_error_code(order, response)
                return self._reject_order(order, error_code, error_msg)
            order.accept(self)

            if isinstance(response, Mapping):
                self._cache_order_identifiers(order, response)

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
            return order
        except TimeoutError as exc:
            self._sanitize_exception(exc)
            # Once a write call may have reached the SDK, a timeout is UNKNOWN.
            return self._accept_unknown_submission(order, exc, "submit_timeout")
        except Exception as exc:
            _safe_log("error", "btapibroker: submit failed")
            self._sanitize_exception(exc)
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
                code = self._safe_exception_code(exc, "remote_submit_rejected")
                order.addinfo(remote_error_code=code)
                return self._reject_order(
                    order,
                    code,
                    "The unified SDK facade rejected the order before dispatch.",
                )
            order.addinfo(
                error_code="remote_submit_failed",
                error_msg="Remote submission failed before its outcome could be classified",
            )
            order.reject(self)
            self.orders[order.ref] = order
            self.notify(order)
            raise
    def cancel(self, order):
        """Cancel an existing order through the store."""
        if order is None:
            return None
        if self._direct_active():
            return self._direct_cancel(order)

        if getattr(self, "factor_execution_coordinator", None) is not None:
            order.addinfo(
                cancel_requested_remote=False,
                cancel_rejected_local=True,
                error_code="managed_execution_authorization_unavailable",
                error_msg="Managed cancellation requires the SDK authorization and completion contract.",
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

        if bool(self._order_info_get(order, "cancel_requested_remote", False)):
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
        fence_error = self._account_owner_fence_error()
        owner_lease = None
        if fence_error is None:
            owner_lease, fence_error = self._acquire_account_owner_lease("cancel", order)
        if fence_error is not None:
            code, _message = fence_error
            order.addinfo(cancel_error_code=code, cancel_requested_remote=False)
            self.notify(order)
            return order
        try:
            self._consume_approval_operation(
                order,
                risk_reducing=True,
                operation="cancel",
            )
        except BaseException:
            _finish_owner_lease(owner_lease, "NOT_SENT")
            raise
        try:
            try:
                response = self.store.cancel_order(order)
            except BaseException as exc:
                _finish_owner_lease(owner_lease, _owner_lease_error_outcome(exc))
                raise
            _finish_owner_lease(owner_lease, _owner_lease_response_outcome(response))
        except Exception as exc:
            _safe_log("warning", "btapibroker:2813 fallback on Exception")
            self._sanitize_exception(exc)
            if not bool(getattr(exc, "execution_unknown", False)) and not isinstance(
                exc, TimeoutError
            ):
                if bool(getattr(exc, "definite_reject", False)):
                    order.addinfo(
                        cancel_requested_remote=False,
                        cancel_execution_unknown=False,
                        cancel_intent_active=False,
                        cancel_error_code=self._safe_exception_code(
                            exc, "remote_cancel_rejected"
                        ),
                        cancel_error_msg="The SDK rejected cancellation before dispatch.",
                    )
                    self.notify(order)
                    return order
                raise
            order.addinfo(
                cancel_requested_remote=True,
                cancel_execution_unknown=True,
                cancel_intent_active=True,
                execution_unknown=True,
                cancel_error_code=self._safe_exception_code(
                    exc, "cancel_execution_unknown"
                ),
                cancel_error_msg="Remote cancellation outcome is unknown",
            )
            self.orders[order.ref] = order
            self.notify(order)
            if self._uses_async_commands():
                self._request_order_reconcile(order)
            return order

        local_cancelled_before_send = bool(
            isinstance(response, Mapping)
            and response.get("local_cancelled_before_send") is True
            and response.get("remote_write_attempted") is False
        )
        queued_receipt = bool(
            isinstance(response, Mapping)
            and response.get("kind") == "command_receipt"
            and response.get("queued") is True
        )
        # Iteration 62 (62.08): like submit (iteration 60), a managed route
        # (ServiceExecutionSession, managed runtime) verifies its own typed
        # cancel result; the direct SDK correlation never exists for it, so
        # re-checking made every managed cancel UNKNOWN.
        if (
            not local_cancelled_before_send
            and not queued_receipt
            and bool(getattr(self.store, "managed_execution_active", False))
        ):
            return self._apply_managed_cancel_projection(order, response)
        if not local_cancelled_before_send and not queued_receipt:
            correlation = self._order_correlations.get(order.ref)
            if not self._verify_cancel_response(correlation, response):
                order.addinfo(
                    cancel_requested_remote=True,
                    cancel_execution_unknown=True,
                    cancel_intent_active=True,
                    execution_unknown=True,
                    cancel_error_code="sdk_cancel_response_unverified",
                )
                self.orders[order.ref] = order
                self.notify(order)
                return order

        if (
            local_cancelled_before_send
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
            isinstance(response, Mapping)
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

        if (
            bool(self.p.cancel_wait_remote)
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

    def _accept_unknown_submission(self, order, exc, error_code):
        """Keep an ambiguously submitted order alive under its original identity."""
        self._abort_recovery_dispatch(order, "execution_recovery_dispatch_unknown")
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
        self._begin_execution_reconciliation("unknown_order_submission")
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

    def _is_risk_reducing_order(self, order):
        """Return true only after Store-verified rules and economics prove a close."""
        return id(order) in self._verified_risk_reducing_orders

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
        """Block exposure while execution state or account evidence is uncertain."""
        if self._execution_recovery is not None:
            return (
                "execution_recovery_contract_unavailable",
                "Legacy recovery dispatch lacks the unified SDK authorization contract",
            )
        if self._is_risk_reducing_order(order):
            return None
        if self._execution_reconciliation_required:
            return (
                "execution_reconciliation_required",
                "New exposure is blocked until SDK reconciliation proves the execution state",
            )
        if not self._uses_async_commands():
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
                "pending_cancel_exposure",
                "New exposure is blocked while a cancellation intent is unresolved",
            )
        return None

    def next(self):
        """Refresh cached balances and positions."""
        if self._direct_active():
            return self._direct_next()
        session = self._managed_runtime_session
        if session is None:
            session = self._service_execution_session
        if session is not None:
            session.poll(self)
        self._drain_store_updates()
        self._poll_gateway_execution_events()  # R2-C, no-op unless bound
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
        from bt_api_py.account_risk_projection import position_audit_close_error

        return position_audit_close_error(
            offset=lambda: self._order_info_get(order, "offset"),
            order_size=lambda: order.size,
            position_key=lambda: self._position_key(order.data),
            dual_side=lambda: self._is_dual_side_mode(),
            position_side=lambda: normalize_position_side(
                self._order_info_get(order, "position_side")
            ),
            is_buy=lambda: order.isbuy(),
            leg_size=lambda side, key: self._get_leg_store(side)[key].size,
            net_size=lambda key: self.positions[key].size,
        )

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
        self._attach_position_meta(
            order, position_side=position_side, offset=offset, **order_kwargs
        )
        if oco is not None:
            order.addinfo(oco=oco)
        self._direct_tag_order(order, valid, offset)
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
        self._attach_position_meta(
            order, position_side=position_side, offset=offset, **order_kwargs
        )
        if oco is not None:
            order.addinfo(oco=oco)
        self._direct_tag_order(order, valid, offset)
        return self.submit(order)

    def notify(
        self,
        order,
        *,
        recovery_receipt_id=None,
        recovery_restore_only=False,
        recovery_fill_projection=None,
    ):
        """Queue an order notification, optionally bound to one recovery receipt."""
        # Write-ahead of a fee correction's ledger update (closed at restart by
        # reconcile_ledger_fees if the process dies before it is journaled).
        self._journal_ledger_fee_intent(order)
        self._sync_direct_ledger(order)
        if self._service_execution_recovery_suppress_notifications:
            return
        # Re-verification G3: a recovery-bound Strategy's notification is
        # journaled durably before it can be delivered (ACK after its callback).
        journaled = self._journal_strategy_notification(order)
        if (
            journaled is not None
            and journaled.replayed
            and not journaled.fee_created
            and self._gateway_previous_process_duplicate(order, journaled.event_id)
        ):
            # R2-C: a re-applied Gateway event a previous process journaled;
            # its fee corrections were delivered (or replayed) there too.
            self._mark_fee_corrections_delivered(order)
            return
        # ``Order.clone`` deliberately clones execution state but retains the
        # original ``info`` mapping.  A later broker update can otherwise
        # rewrite a queued Accepted/UNKNOWN notification before Cerebro
        # dispatches it (for example UNKNOWN -> Completed in one drain pass).
        # Keep the top-level metadata snapshot independent while preserving
        # user-provided object identities stored as values such as OCO links.
        snapshot = order.clone()
        snapshot.info = copy(order.info)
        if journaled is not None:
            snapshot.notification_id = journaled.event_id
            snapshot.replayed = journaled.replayed
            snapshot.fee_correction_ids = journaled.fee_ids  # ACKed after the dispatch
            snapshot.addinfo(notification_id=journaled.event_id)
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
        if self._direct_active():
            self._direct_data_started(data)

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
                self._order_info_get(order, "client_order_id"),
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
        return cls._remote_external_order_id(item) or cls._remote_client_order_id(item)

    @classmethod
    def _remote_external_order_id(cls, update):
        from bt_api_py.broker_event_envelope import broker_event_external_order_id

        return broker_event_external_order_id(update, extract_value=cls._extract_update_value)

    @classmethod
    def _remote_client_order_id(cls, update):
        from bt_api_py.broker_event_envelope import broker_event_client_order_id

        return broker_event_client_order_id(update, extract_value=cls._extract_update_value)

    @staticmethod
    def _remote_order_data_name(item):
        if not isinstance(item, dict):
            return None
        return BtApiBroker._extract_update_value(item, *_DATA_NAME_KEYS)

    def _remote_order_details(self, item):
        order_id = None
        client_order_id = None
        side = None
        quantity = None
        price = None
        status = None
        if isinstance(item, dict):
            order_id = item.get("order_id")
            client_order_id = self._remote_client_order_id(item)
            side = self._extract_update_value(item, "side")
            quantity = self._extract_update_value(item, "quantity")
            price = self._extract_update_value(item, "limit_price")
            status = self._extract_update_value(item, "status")

        details = {
            "order_id": order_id,
            "client_order_id": client_order_id,
            "data_name": self._remote_order_data_name(item),
            "side": side,
            "quantity": quantity,
            "price": price,
            "status": status,
            "source": "remote_open_orders",
        }
        return {key: value for key, value in details.items() if value not in (None, "")}

    def _cancel_remote_open_order(self, item):
        """Cancel only a neutral order observation accepted by the SDK facade."""
        if self.store is None:
            raise ValueError("BtApiBroker requires a BtApiStore instance")
        if not isinstance(item, Mapping):
            raise ValueError("Remote order observation is not neutral")
        method = getattr(self.store, "cancel_order_id", None)
        if not callable(method):
            raise NotImplementedError(
                "Remote order cancellation requires an SDK-verified neutral target"
            )
        order_id = item.get("order_id")
        client_order_id = item.get("client_order_id")
        symbol = item.get("symbol")
        if (
            type(order_id) is not str
            or not order_id
            or order_id != order_id.strip()
            or type(symbol) is not str
            or not symbol
            or symbol != symbol.strip()
        ):
            raise ValueError("Remote order observation lacks neutral cancellation identity")
        return method(
            order_id=order_id,
            symbol=str(symbol),
            client_order_id=client_order_id,
        )

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
            quantity_units = {}
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
                if key is None:
                    raise ValueError("SDK position lacks a unique typed instrument binding")
                self._sync_one_position(
                    item,
                    synced,
                    long_synced,
                    short_synced,
                    key=key,
                    quantity_units=quantity_units,
                )

            if any(
                self._position_quantity_units.get(key) not in (None, unit)
                for key, unit in quantity_units.items()
            ):
                raise ValueError("SDK position quantity units changed without a new session")
            if self._is_dual_side_mode():
                self.long_positions = long_synced
                self.short_positions = short_synced
                self.positions = collections.defaultdict(Position)
                for key in set(long_synced) | set(short_synced):
                    self._sync_net_position(key)
            else:
                self.positions = synced
            self._position_quantity_units = quantity_units
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
        quantity_units=None,
    ):
        """Map one SDK-neutral position snapshot into a Backtrader Position.

        Extracted from ``_sync_positions``' loop body; behavior unchanged.
        Mutates the supplied ``synced`` / ``long_synced`` / ``short_synced``
        defaultdicts in place and returns nothing.
        """
        key = key or self._position_row_key(item)
        if not key:
            return

        size_value = self._neutral_record_value(item, "quantity")
        unit = self._neutral_record_value(item, "quantity_unit")
        account_position_unit = self._neutral_record_value(item, "qty_unit")
        if unit not in (None, "") and account_position_unit not in (None, ""):
            if unit != account_position_unit:
                raise ValueError("SDK position row has conflicting quantity units")
        if type(unit) is not str or not unit or unit != unit.strip():
            unit = account_position_unit
        if type(unit) is not str or not unit or unit != unit.strip():
            raise ValueError("SDK position quantity unit is unavailable")
        if quantity_units is not None:
            prior_unit = quantity_units.get(key)
            if prior_unit is not None and prior_unit != unit:
                raise ValueError("SDK position rows use conflicting quantity units")
            quantity_units[key] = unit
        prior_unit = self._position_quantity_units.get(key)
        if prior_unit is not None and prior_unit != unit:
            raise ValueError("SDK position quantity unit changed")
        try:
            size = float(size_value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("SDK position quantity is invalid") from exc
        if not math.isfinite(size):
            raise ValueError("SDK position quantity is invalid")
        from bt_api_py.broker_event_envelope import neutral_position_direction

        direction = neutral_position_direction(item)

        price_value = self._neutral_record_value(item, "average_price")
        if price_value in (None, ""):
            price = 0.0
            if size:
                raise ValueError("SDK position average price is unavailable")
        else:
            try:
                price = float(price_value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("SDK position average price is invalid") from exc
            if not math.isfinite(price) or price < 0:
                raise ValueError("SDK position average price is invalid")

        if self._is_dual_side_mode():
            if direction not in {"long", "short"} or size < 0:
                raise ValueError(
                    "dual_side mode requires non-negative typed long/short quantities"
                )
            if direction == "short":
                short_synced[key].update(abs(size), price)
            else:
                long_synced[key].update(abs(size), price)
        else:
            if direction != "net":
                raise ValueError("net mode requires a signed net position quantity")
            current = synced[key]
            if current.size and size and (current.size > 0) != (size > 0):
                raise ValueError(
                    "net mode received opposing position rows for one instrument; "
                    "verify the remote account position mode"
                )
            current.update(size, price)

    def _tracked_position_alias_map(self):
        """Bind exact configured feed names to SDK-typed instrument identities."""
        from bt_api_py.broker_event_envelope import neutral_instrument_identity

        identities_by_route = collections.defaultdict(set)
        alias_routes = collections.defaultdict(set)
        identity_routes = collections.defaultdict(set)

        def add_route(route, symbols, instrument_key=None):
            if not isinstance(route, str) or not route.strip():
                return
            route = route.strip()
            for value in symbols:
                if isinstance(value, str) and value.strip():
                    alias_routes[value.strip()].add(route)
            identity = neutral_instrument_identity(instrument_key)
            if identity is not None:
                identities_by_route[route].add(identity)
                identity_routes[identity].add(route)

        store = self.store
        for data in getattr(store, "_data_feeds", ()) or ():
            route = self._position_key(data)
            symbols = (
                route,
                getattr(data, "_dataname", None),
                getattr(getattr(data, "p", None), "dataname", None),
            )
            instrument_key = None
            resolver = getattr(store, "get_market_instrument_key", None)
            if callable(resolver):
                try:
                    instrument_key = resolver(route)
                except Exception as exc:
                    _safe_log("warning", "btapibroker: instrument key lookup failed")
                    self._sanitize_exception(exc)
            add_route(route, symbols, instrument_key)

        for order in self.orders.values():
            data = getattr(order, "data", None)
            if data is not None:
                route = self._position_key(data)
                add_route(route, (route,), self._order_info_get(order, "instrument_key"))

        for dataname in getattr(store, "_subscribed_datanames", ()) or ():
            if not isinstance(dataname, str):
                continue
            routes = alias_routes.get(dataname.strip(), ())
            if len(routes) == 1:
                add_route(next(iter(routes)), (dataname,))

        return {
            "aliases": {key: frozenset(routes) for key, routes in alias_routes.items()},
            "identities": {
                identity: frozenset(routes) for identity, routes in identity_routes.items()
            },
            "route_identities": {
                route: frozenset(identities)
                for route, identities in identities_by_route.items()
            },
        }

    @classmethod
    def _position_row_canonical_key(cls, item, alias_map):
        """Resolve a position row against the Store's configured feed bindings."""
        from bt_api_py.broker_event_envelope import resolve_neutral_position_route

        return resolve_neutral_position_route(item, alias_map)

    @classmethod
    def _position_row_key(cls, item):
        """Return only an explicit Store-bound data name."""
        if isinstance(item, Mapping):
            data_name = item.get("data_name")
            if isinstance(data_name, str) and data_name.strip():
                return data_name
        return None

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
    def _rule_position_quantity(position, *, absolute=False):
        size = BtApiBroker._neutral_decimal(getattr(position, "size", None))
        if size is None:
            return None
        if absolute:
            size = abs(size)
        return format(size, "f")

    def _execution_rule_position_facts(self, order):
        """Project BT-local positions as context, never as provider authority."""
        mode = normalize_position_mode(self.get_param("position_mode"))
        if mode == POSITION_MODE_DUAL_SIDE:
            long_position = self._get_leg_position(order.data, "long")
            short_position = self._get_leg_position(order.data, "short")
            net_size = None
            long_size = self._rule_position_quantity(long_position, absolute=True)
            short_size = self._rule_position_quantity(short_position, absolute=True)
        else:
            position = self.getposition(order.data, clone=False)
            net_size = self._rule_position_quantity(position)
            long_size = None
            short_size = None
        return {
            "position_mode": mode,
            "net_position_size": net_size,
            "long_position_size": long_size,
            "short_position_size": short_size,
            "long_close_today_size": None,
            "long_close_yesterday_size": None,
            "short_close_today_size": None,
            "short_close_yesterday_size": None,
        }

    @staticmethod
    def _bounded_decision_code(value, default):
        if type(value) is not str or not value or len(value) > 128:
            return default
        if not all(character.isalnum() or character in "._:-" for character in value):
            return default
        return value

    def _execution_rules_error(self, order):
        """Require SDK rule and affordability decisions bound by the Store."""
        if self.store is None:
            return "order_rules_unavailable", "The SDK order-rules port is unavailable"
        evaluate_rules = getattr(self.store, "evaluate_order_rules", None)
        verify_rules = getattr(self.store, "verify_order_rules", None)
        evaluate_economics = getattr(self.store, "evaluate_order_economics", None)
        verify_economics = getattr(self.store, "verify_order_economics", None)
        if not all(
            callable(method)
            for method in (evaluate_rules, verify_rules, evaluate_economics, verify_economics)
        ):
            return (
                "execution_preflight_unavailable",
                "SDK order rules and economic evidence are required before dispatch",
            )

        current_position = self._execution_rule_position_facts(order)
        try:
            rules = evaluate_rules(
                order,
                market_instrument_key=None,
                current_position=current_position,
            )
            verified_rules = verify_rules(order, rules)
        except Exception as exc:
            self._sanitize_exception(exc)
            return (
                "order_rules_unavailable",
                "The SDK could not verify current instrument execution rules",
            )
        if type(verified_rules) is not bool or verified_rules is not True:
            return (
                "order_rules_unverified",
                "The SDK order-rules decision is not bound to this order and session",
            )
        status = getattr(rules, "status", None)
        if status != "accepted":
            code = self._bounded_decision_code(
                getattr(rules, "reason_code", None),
                "order_rules_unavailable" if status == "unavailable" else "order_rules_rejected",
            )
            return code, "The SDK execution rules did not accept this order"

        offset = getattr(rules, "normalized_offset", None)
        position_side = getattr(rules, "normalized_position_side", None)
        time_in_force = getattr(rules, "normalized_time_in_force", None)
        if (
            offset not in {"open", "close", "close_today", "close_yesterday"}
            or position_side not in {"long", "short"}
            or type(time_in_force) is not str
            or not time_in_force
        ):
            return (
                "order_rules_projection_invalid",
                "The verified SDK decision has no supported neutral order projection",
            )

        try:
            economics = evaluate_economics(order, rules)
            verified_economics = verify_economics(order, economics)
        except Exception as exc:
            self._sanitize_exception(exc)
            return (
                "order_economics_unavailable",
                "The SDK could not verify current account affordability",
            )
        if type(verified_economics) is not bool or verified_economics is not True:
            return (
                "order_economics_unverified",
                "The SDK affordability decision is not bound to this order and account session",
            )
        economics_status = getattr(economics, "status", None)
        if economics_status != "accepted":
            code = self._bounded_decision_code(
                getattr(economics, "reason_code", None),
                "order_economics_unavailable"
                if economics_status == "unavailable"
                else "order_economics_rejected",
            )
            return code, "The SDK affordability decision did not accept this order"

        order.addinfo(
            offset=offset,
            position_side=position_side,
            time_in_force=time_in_force,
        )
        if offset in {"close", "close_today", "close_yesterday"}:
            self._verified_risk_reducing_orders.add(id(order))
        return None

    @staticmethod
    def _order_type_name(order):
        """Lower-case Backtrader order type name (``limit``, ``market``, ...)."""
        try:
            return str(order.getordername() or "").strip().lower()
        except Exception:
            _safe_log("warning", "btapibroker: order type name unavailable")
            return ""

    def _validate_order(self, order):
        """Validate Backtrader order shape without interpreting venue rules."""
        size = self._neutral_decimal(getattr(order, "size", None))
        if size is None or size == 0:
            return "invalid_order_size", "Order size must be a finite non-zero amount"
        if self.p.max_order_size:
            if abs(size) > Decimal(str(self.p.max_order_size)):
                return "max_order_size_exceeded", "Order exceeds the configured local size cap"
        if self._order_type_name(order) == "limit":
            raw_price = (
                getattr(order, "price", None)
                if getattr(order, "price", None) is not None
                else getattr(getattr(order, "created", None), "price", None)
            )
            price = self._neutral_decimal(raw_price)
            if price is None or price <= 0:
                return "invalid_order_price", "Limit order price must be finite and positive"
        return None

    def _reject_order(self, order, error_code, error_msg):
        """Reject an order locally and emit a structured runtime event."""
        self._verified_risk_reducing_orders.discard(id(order))
        self._abort_recovery_dispatch(order, "execution_recovery_dispatch_failed")
        error_code = str(self._redact_runtime_value(error_code))
        error_msg = str(self._redact_runtime_value(error_msg))
        order.addinfo(error_code=error_code, error_msg=error_msg)
        order.reject(self)
        self._clear_order_mappings(order)
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
        """Retain a bounded code from a verified neutral rejection envelope."""
        from bt_api_py.broker_event_envelope import verified_submit_rejection_code

        value = verified_submit_rejection_code(response)
        if value is not None:
            order.addinfo(remote_error_code=value)

    @classmethod
    def _submit_response_error(cls, response):
        """Project only the Store's already-verified neutral submit result."""
        from bt_api_py.broker_event_envelope import verified_submit_ack_error

        return verified_submit_ack_error(response)

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
        client_order_id = self._order_info_get(order, "client_order_id")
        return {
            "backtrader_order_ref": getattr(order, "ref", None),
            "external_order_id": external_order_id,
            "client_order_id": client_order_id,
            "data_name": self._position_key(order.data),
            "side": "buy" if order.isbuy() else "sell",
            "size": abs(float(order.size or 0.0)),
            "price": (
                order.price if order.price is not None else getattr(order.created, "price", None)
            ),
            "status": order.getstatusname(),
        }

    def _drain_store_updates(self):
        """Apply provider-neutral Store projections on the Cerebro thread."""
        if self.store is None or not hasattr(self.store, "poll_broker_update"):
            return

        while True:
            raw_update = self.store.poll_broker_update()
            if raw_update is None:
                return
            for update in self._iter_broker_update_rows(raw_update):
                self._apply_broker_update_row(update)

    def _apply_broker_update_row(self, update):
        """Apply one neutral update row (Store drain and Gateway execution events)."""
        kind = str(update.get("kind") or "").lower()
        command = str(update.get("command") or "")
        reconciliation_completion = kind == "command_completion" and command == "reconciliation"
        execution_evidence_update = bool(
            kind in {"order", "trade", "error"}
            or (
                kind == "command_completion"
                and command
                in {
                    "submit",
                    "cancel",
                    "query",
                    "reconcile",
                    "order_reconciliation",
                }
            )
        )
        if not reconciliation_completion:
            self._execution_reconciliation_event_epoch += 1
            if self._execution_reconciliation_required:
                self._reset_execution_reconciliation_rounds("broker_update_between_snapshots")
            elif self._execution_reconciliation_rounds >= 2 and execution_evidence_update:
                self._begin_execution_reconciliation("broker_update_after_reconciliation")
        if kind == "order":
            self._apply_order_update(update, from_store_callback=True)
        elif kind == "trade":
            self._apply_trade_update(update)
        elif kind == "error":
            self._apply_error_update(update)
        elif kind == "command_completion":
            self._apply_command_completion(update)

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
        if command == "reconciliation":
            self._execution_reconciliation_pending = False
            callbacks = tuple(self._execution_reconciliation_callbacks)
            self._execution_reconciliation_callbacks.clear()
            response = update.get("response")
            verified_snapshot = bool(
                update.get("success") is True
                and isinstance(response, dict)
                and self._verify_reconciliation_snapshot(response)
            )
            if verified_snapshot:
                # Build the callback view first: it reflects the already-applied
                # main-thread trade ledger.  The gate must consume that view,
                # rather than advancing before local evidence is attached.
                callback_snapshot = self._reconciliation_callback_snapshot(response, None)
                state = self.record_reconciliation(callback_snapshot)
                notification = self._reconciliation_callback_snapshot(callback_snapshot, state)
            else:
                error_code = (
                    "reconciliation_snapshot_unverified"
                    if update.get("success") is True and isinstance(response, dict)
                    else (update.get("error_code") or "execution_reconciliation_failed")
                )
                self._reset_execution_reconciliation_rounds(error_code)
                state = self.get_execution_reconciliation_state()
                notification = {
                    "schema_version": "backtrader.execution.reconciliation.v1",
                    "complete": False,
                    "is_last_seen": False,
                    "timed_out": False,
                    "error_code": error_code,
                    "evidence_complete": False,
                    "broker_reconciliation_state": state,
                }
            self._last_execution_reconciliation_result = deepcopy(notification)
            for callback in callbacks:
                try:
                    callback(deepcopy(notification))
                except Exception as exc:
                    _safe_log("warning", "btapibroker:6179 fallback on Exception")
                    self._sanitize_exception(exc)
                    self._emit_runtime_event(
                        "execution_reconciliation_callback_failed",
                        level="ERROR",
                        error_code=type(exc).__name__,
                    )
            return
        if command == "order_reconciliation":
            self._apply_order_reconciliation_completion(update)
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

    def _apply_order_reconciliation_completion(self, update):
        """Apply one verified order snapshot without advancing the account barrier."""
        local_ref = update.get("bt_order_ref")
        if type(local_ref) is not int or local_ref <= 0:
            local_ref = update.get("local_ref")
        order = self.orders.get(local_ref) if type(local_ref) is int else None
        if order is None:
            return

        expected_receipt = self._order_info_get(order, "reconcile_receipt_id")
        completion_receipt = update.get("receipt_id")
        if (
            type(expected_receipt) is not str
            or not expected_receipt
            or type(completion_receipt) is not str
            or completion_receipt != expected_receipt
        ):
            return
        order.addinfo(reconcile_requested=False, reconcile_receipt_id=None)

        # An order-scoped snapshot can resolve this local Order, but it cannot
        # establish account-wide position equality or clear the recovery gate.
        self._begin_execution_reconciliation("order_reconciliation_not_account_wide")

        def fail(reason):
            order.addinfo(
                execution_unknown=True,
                reconcile_requested=False,
                reconcile_receipt_id=None,
                reconcile_last_reason=reason,
            )
            self.notify(order)
            self._schedule_order_reconcile_retry(order, reason)

        response = update.get("response")
        correlation = self._order_correlations.get(order.ref)
        outer_refs = (update.get("local_ref"), update.get("bt_order_ref"))
        if (
            update.get("success") is not True
            or type(response) is not dict
            or correlation is None
            or type(response.get("schema_version")) is not str
            or response.get("schema_version")
            != "backtrader.execution.order_reconciliation.v1"
            or response.get("kind") != "order_reconciliation"
            or response.get("complete") is not True
            or response.get("evidence_complete") is not True
            or response.get("safe_to_resume") is not False
            or response.get("reason") != "reconciliation_order_verified"
            or type(response.get("local_ref")) is not int
            or response.get("local_ref") != order.ref
            or type(response.get("bt_order_ref")) is not int
            or response.get("bt_order_ref") != order.ref
            or (local_ref != order.ref)
            or any(
                value is not None and (type(value) is not int or value != order.ref)
                for value in outer_refs
            )
            or update.get("data_name") not in (None, response.get("data_name"))
        ):
            fail("order_reconciliation_incomplete")
            return

        if not self._verify_order_reconciliation(correlation, response):
            fail("order_reconciliation_unverified")
            return

        client_order_id = response.get("client_order_id")
        intent_ref = response.get("intent_ref")
        data_name = response.get("data_name")
        snapshot_id = response.get("snapshot_id")
        consistency_digest = response.get("consistency_digest")
        if any(
            type(value) is not str or not value or value != value.strip()
            for value in (
                client_order_id,
                intent_ref,
                data_name,
                snapshot_id,
                consistency_digest,
            )
        ):
            fail("order_reconciliation_identity_invalid")
            return
        known_client_order_id = self._order_info_get(order, "client_order_id")
        if (
            known_client_order_id not in (None, client_order_id)
            or update.get("client_order_id") not in (None, client_order_id)
            or data_name != self._position_key(order.data)
        ):
            fail("order_reconciliation_local_binding_mismatch")
            return

        order_record = response.get("order")
        observation = {
            "local_ref": local_ref,
            "bt_order_ref": order.ref,
            "client_order_id": client_order_id,
            "intent_ref": intent_ref,
            "data_name": data_name,
            "order": order_record,
        }
        order_update = self._neutral_order_update(observation)
        fills = response.get("fills")
        if order_update is None or type(fills) is not list:
            fail("order_reconciliation_records_invalid")
            return

        order_instrument_ref = self._neutral_record_value(order_record, "instrument_ref")
        order_id = self._neutral_record_value(order_record, "order_id")
        order_symbol = self._neutral_record_value(order_record, "symbol")
        order_quantity_unit = self._neutral_record_value(order_record, "quantity_unit")
        quantity = self._neutral_decimal(order_update.get("quantity"), positive=True)
        expected_filled = self._neutral_decimal(order_update.get("filled_quantity"))
        if (
            type(order_instrument_ref) is not str
            or not order_instrument_ref
            or type(order_id) is not str
            or not order_id
            or type(order_symbol) is not str
            or not order_symbol
            or quantity is None
            or expected_filled is None
            or expected_filled < 0
            or expected_filled > quantity
            or quantity
            != self._neutral_decimal(abs(order.size), positive=True)
            or order_update.get("side") != ("buy" if order.isbuy() else "sell")
        ):
            fail("order_reconciliation_order_mismatch")
            return
        known_quantity_unit = self._order_info_get(order, "quantity_unit")
        if known_quantity_unit not in (None, order_quantity_unit):
            fail("order_reconciliation_quantity_unit_mismatch")
            return

        fill_updates = []
        filled_total = Decimal("0")
        seen_fill_ids = set()
        for fill in fills:
            fill_id = self._neutral_record_value(fill, "fill_id")
            fill_quantity = self._neutral_decimal(
                self._neutral_record_value(fill, "quantity"), positive=True
            )
            if (
                type(fill_id) is not str
                or not fill_id
                or fill_id in seen_fill_ids
                or self._neutral_record_value(fill, "order_id") != order_id
                or self._neutral_record_value(fill, "instrument_ref")
                != order_instrument_ref
                or self._neutral_record_value(fill, "symbol") != order_symbol
                or self._neutral_side_value(fill) != order_update.get("side")
                or self._neutral_record_value(fill, "quantity_unit") != order_quantity_unit
                or fill_quantity is None
            ):
                fail("order_reconciliation_fill_binding_mismatch")
                return
            seen_fill_ids.add(fill_id)
            filled_total += fill_quantity
            fill_update = self._neutral_fill_update(
                fill,
                local_ref,
                client_order_id,
                intent_ref,
                data_name,
            )
            if fill_update is None:
                fail("order_reconciliation_fill_invalid")
                return
            fill_updates.append(fill_update)

        status = order_update.get("status")
        if (
            filled_total != expected_filled
            or (status == "accepted" and expected_filled != 0)
            or (status == "partial" and not (0 < expected_filled < quantity))
            or (status == "completed" and expected_filled != quantity)
            or (status == "rejected" and expected_filled != 0)
        ):
            fail("order_reconciliation_fill_coverage_mismatch")
            return

        for fill_update in fill_updates:
            outcome = self._apply_trade_update(fill_update, defer_unmatched=False)
            if outcome not in {"applied", "ignored"}:
                fail("order_reconciliation_fill_projection_failed")
                return
        if self._pending_trade_updates:
            fail("order_reconciliation_pending_trade_updates")
            return

        order_update["remote_order_id"] = order_id
        self._apply_order_update(order_update, from_query=True)

        order = self.orders.get(update.get("bt_order_ref"))
        if order is None and update.get("client_order_id") not in (None, ""):
            order = self._lookup_order(update)
        if order is None:
            return
        response = update.get("response")

        if command == "query":
            # The legacy query worker returns an untyped mapping.  It is not
            # evidence that can safely transition an Order in this facade.
            order.addinfo(
                execution_unknown=True,
                reconcile_requested=False,
                error_code="typed_order_observation_unavailable",
            )
            self._begin_execution_reconciliation("typed_order_observation_unavailable")
            self.notify(order)
            self._schedule_order_reconcile_retry(order, "typed_order_observation_unavailable")
            return

        if command not in {"submit", "cancel"}:
            return

        if (
            command == "submit"
            and isinstance(response, Mapping)
            and response.get("local_terminal") is True
            and response.get("remote_write_attempted") is False
            and response.get("terminal_confirmed") is True
        ):
            local_update = dict(response)
            for key in ("bt_order_ref", "client_order_id", "data_name", "exchange_name"):
                if update.get(key) not in (None, ""):
                    local_update.setdefault(key, update[key])
            self._apply_order_update(local_update)
            return

        local_rejection = bool(
            isinstance(response, Mapping)
            and response.get("remote_write_attempted") is False
            and response.get("definite_reject") is True
            and response.get("terminal_confirmed") is True
        )
        if local_rejection:
            error_code = str(response.get("error_code") or "local_execution_rejected")
            if command == "submit":
                order.addinfo(error_code=error_code, error_msg=response.get("error_msg"))
                order.reject(self)
                self._clear_order_mappings(order)
            else:
                order.addinfo(
                    cancel_requested_remote=False,
                    cancel_execution_unknown=False,
                    cancel_intent_active=False,
                    cancel_deadline_monotonic_ns=None,
                    cancel_deadline_unknown_marked=False,
                    cancel_error_code=error_code,
                    cancel_error_msg=response.get("error_msg"),
                )
            self.notify(order)
            return

        correlation = self._order_correlations.get(order.ref)
        verified = (
            self._verify_order_response(correlation, response)
            if command == "submit"
            else self._verify_cancel_response(correlation, response)
        )
        ack_status = (
            response.get("status")
            if isinstance(response, Mapping)
            and response.get("kind") == "verified_order_ack"
            and response.get("verified_order_ack") is True
            and response.get("operation") == command
            else None
        )
        if not verified or ack_status not in {"accepted", "rejected"}:
            self._abort_recovery_dispatch(order, "execution_dispatch_outcome_unverified")
            if command == "submit":
                order.addinfo(
                    execution_unknown=True,
                    error_code="sdk_order_ack_unverified",
                    error_msg="SDK acknowledgement is unverified; reconcile the original order",
                )
            else:
                order.addinfo(
                    cancel_requested_remote=True,
                    cancel_execution_unknown=True,
                    cancel_intent_active=True,
                    execution_unknown=True,
                    cancel_error_code="sdk_cancel_ack_unverified",
                )
            self._begin_execution_reconciliation("sdk_ack_unverified")
            self.notify(order)
            self._request_order_reconcile(order)
            return

        if ack_status == "rejected":
            error_code = str(response.get("error_code") or f"remote_{command}_rejected")
            error_msg = response.get("error_msg")
            if command == "submit":
                order.addinfo(error_code=error_code, error_msg=error_msg)
                order.reject(self)
                self._clear_order_mappings(order)
            else:
                order.addinfo(
                    cancel_requested_remote=False,
                    cancel_execution_unknown=False,
                    cancel_intent_active=False,
                    cancel_deadline_monotonic_ns=None,
                    cancel_deadline_unknown_marked=False,
                    cancel_error_code=error_code,
                    cancel_error_msg=error_msg,
                )
            self.notify(order)
            return

        if command == "submit":
            if order.status < order.Accepted:
                order.accept(self)
            order.addinfo(
                execution_unknown=False,
                submit_command_completed=True,
                submit_receipt_id=update.get("receipt_id"),
            )
            self._cache_order_identifiers(order, response)
        else:
            order.addinfo(
                cancel_requested_remote=True,
                cancel_execution_unknown=False,
                cancel_intent_active=True,
                cancel_command_completed=True,
                cancel_receipt_id=update.get("receipt_id"),
            )
            self._cache_order_identifiers(order, response)
            self._request_order_reconcile(order)
        self.notify(order)

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
        method = getattr(self.store, "enqueue_order_reconciliation", None)
        if not callable(method):
            self._schedule_order_reconcile_retry(order, "order_reconciliation_unavailable")
            return
        order.addinfo(
            reconcile_attempts=attempts + 1,
            reconcile_max_attempts=maximum,
            reconcile_next_monotonic_ns=None,
        )
        try:
            receipt = method(order.ref)
        except Exception:
            _safe_log("warning", "btapibroker:6445 fallback on Exception")
            self._schedule_order_reconcile_retry(order, "order_reconciliation_enqueue_failed")
            return
        if isinstance(receipt, dict) and receipt.get("queued") is True:
            order.addinfo(
                reconcile_requested=True,
                reconcile_receipt_id=receipt.get("receipt_id"),
            )
            return
        self._schedule_order_reconcile_retry(order, "order_reconciliation_enqueue_rejected")

    @classmethod
    def _iter_broker_update_rows(cls, update):
        """Delegate legacy event-envelope projection to the SDK."""
        from bt_api_py.broker_event_envelope import iter_broker_event_rows

        yield from iter_broker_event_rows(update)

    def _trade_dedupe_key(self, update, order=None):
        """Build a stable dedupe key from a normalized SDK fill id."""
        trade_id = self._extract_update_value(update, "trade_id", "fill_id")
        if trade_id in (None, ""):
            return None

        order_key = (
            self._remote_external_order_id(update)
            or self._remote_client_order_id(update)
            or self._extract_update_value(update, "local_ref", "bt_order_ref")
        )
        if order_key in (None, "") and order is not None:
            order_key = getattr(order, "ref", None)
        if order_key in (None, "") and order is None:
            return None

        data_name = self._extract_update_value(update, "data_name")
        if data_name in (None, "") and order is not None:
            data_name = self._position_key(order.data)

        return (str(order_key), str(data_name or ""), str(trade_id))

    def _trade_update_details(self, update, order=None, **extra):
        """Return a compact runtime-event payload from normalized SDK fields."""
        detail_keys = (
            "kind",
            "trade_id",
            "fill_id",
            "external_order_id",
            "order_id",
            "client_order_id",
            "local_ref",
            "bt_order_ref",
            "data_name",
            "symbol",
            "side",
            "position_side",
            "offset",
            "position_mode",
            "quantity_unit",
            "quantity",
            "filled_quantity",
            "price",
            "average_price",
            "fee",
            "fee_currency",
            "fee_unit",
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
        for canonical in ("side", "position_side", "offset", "position_mode", "quantity_unit"):
            value = self._extract_update_value(update, canonical)
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
        return (
            cls._normalize_remote_order_status(response.get("status"))
            in _CONFIRMED_TERMINAL_STATUSES
        )

    def _order_is_uncertain(self, order):
        """Return whether a local order still carries an unresolved execution fate."""
        return bool(
            self._order_info_get(order, "execution_unknown", False)
            or self._order_info_get(order, "cancel_execution_unknown", False)
        )

    def _apply_managed_submit_projection(self, order, response):
        """Project a managed route's submit result (iteration 60 restoration).

        The managed adapter (``ServiceExecutionAdapter`` and the SDK typed
        client behind it) has already verified its typed result; it is not an
        SDK direct acknowledgement and is not re-verified as one. A definite
        rejection rejects the order; an UNKNOWN keeps it Submitted and marked
        ``execution_unknown`` (never accepted or filled); anything else accepts
        it, and a fill already in the record is applied through the ordinary
        update path exactly as ``refresh_managed_orders`` would.
        """
        if not isinstance(response, Mapping):
            order.addinfo(
                execution_unknown=True,
                error_code="invalid_managed_execution_projection",
                error_msg="Managed execution projection is invalid; reconcile the original intent",
            )
            self.orders[order.ref] = order
            self.notify(order)
            return order
        unknown = (
            response.get("execution_unknown") is True
            or response.get("service_execution_state") == "UNKNOWN"
        )
        if response.get("status") == "rejected" and not unknown:
            self._attach_remote_error_code(order, response)
            return self._reject_order(
                order,
                str(response.get("error_code") or "managed_submit_rejected"),
                str(response.get("error_msg") or "The managed route rejected the order"),
            )
        for key in ("managed_intent_id", "service_execution_state", "service_record_revision"):
            value = response.get(key)
            if value is not None:
                order.addinfo(**{key: value})
        self._bind_managed_external_order_id(order, response)
        unit = response.get("quantity_unit")
        if type(unit) is str and unit:
            # Fills of this order are bound to the typed route's unit.
            order.addinfo(quantity_unit=unit)
            self._freeze_order_execution_contract(order, replace=True)
        self._cache_order_identifiers(order, response)
        self.orders[order.ref] = order
        if unknown:
            order.addinfo(
                execution_unknown=True,
                error_code=str(response.get("error_code") or "managed_submit_unknown"),
                error_msg=str(
                    response.get("error_msg")
                    or "The managed submit outcome is unknown; reconcile the original intent"
                ),
            )
            self.notify(order)
            return order
        order.accept(self)
        self.notify(order)
        if response.get("filled") is not None and response.get("managed_execution_replayed") is not True:
            self._apply_managed_record(order, response)
            order.addinfo(
                service_refresh_applied=(
                    response.get("service_execution_state"),
                    response.get("service_record_revision"),
                    response.get("status"),
                    response.get("execution_unknown"),
                    response.get("filled"),
                    response.get("price"),
                    response.get("avg_price"),
                )
            )
        return order

    def refresh_managed_orders(self, *, limit: int = 32):
        """Apply current durable service records to managed orders.

        Live managed orders go through the ordinary update path.  A managed order
        that already terminated locally is read too, but only while it still
        carries an uncertainty marker, and its record is projected through
        :meth:`apply_confirmed_terminal_observation`.

        The caller owns the schedule; this method performs one bounded pass and
        returns the framework order refs whose state was applied.  ``limit``
        bounds every adapter refresh attempt, including missing, replayed, or
        unchanged projections.  Live managed orders rotate fairly between
        passes so an unchanged early order cannot consume an unbounded pass or
        starve later orders.  Each application goes through the ordinary update
        path, and an unchanged durable revision is skipped so the same state is
        never booked twice.  A store or adapter without refresh support raises
        instead of silently doing nothing.
        Restored in iteration 60: the iteration-53 split had dropped it, so
        ``ServiceExecutionSession`` could not start its refresh loop
        (``BROKER_CANNOT_REFRESH``).
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
            if not self._order_info_get(order, "managed_intent_id"):
                continue
            if not order.alive() and not self._order_is_uncertain(order):
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
        for order in getattr(self, "_managed_refresh_order_queue", ()):
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
            # this candidate terminal before its turn arrives; a terminal order
            # stays eligible only while its own fate remains unresolved.
            if not self._order_info_get(order, "managed_intent_id"):
                continue
            if not order.alive() and not self._order_is_uncertain(order):
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
            if not order.alive():
                # The strategy already saw this order terminate, so re-entering
                # the update path here would notify the same state a second time.
                if self.apply_confirmed_terminal_observation(
                    order, projection, source="managed_service_projection"
                ):
                    applied.append(getattr(order, "ref", None))
                continue
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
            self._bind_managed_external_order_id(order, projection)
            if self._apply_managed_record(order, projection):
                order.addinfo(service_refresh_applied=fingerprint)
                applied.append(getattr(order, "ref", None))
                continue
            update = dict(projection)
            update.setdefault("bt_order_ref", getattr(order, "ref", None))
            update.setdefault("data_name", self._position_key(order.data))
            update.setdefault("side", "buy" if order.isbuy() else "sell")
            self._apply_order_update(update)
            order.addinfo(service_refresh_applied=fingerprint)
            applied.append(getattr(order, "ref", None))
        return tuple(applied)

    def _bind_managed_external_order_id(self, order, projection):
        """Record the provider order id a managed durable record evidences.

        The service projection names it ``external_order_id`` (not the direct
        SDK ``order_id`` envelope key), and the managed cancel needs it. The
        first evidenced id is kept; a record never rewrites a bound id.
        (Iteration 62, 62.08: it was never bound, so every managed cancel was
        refused with ``managed_cancel_provider_identity_missing``.)
        """
        if not isinstance(projection, Mapping):
            return
        external_id = projection.get("external_order_id")
        if type(external_id) is not str or not external_id:
            return
        if self._order_info_get(order, "external_order_id") not in (None, ""):
            return
        order.addinfo(external_order_id=external_id)
        self._orders_by_external_id[external_id] = order

    def _apply_managed_cancel_projection(self, order, response):
        """Project a managed route's cancel result (iteration 62, 62.08).

        The managed adapter has already verified its typed cancel result; it is
        not re-verified as a direct SDK cancel. A definite rejection leaves the
        order alive without an active cancel; an UNKNOWN (or an invalid
        projection) keeps the cancel intent active and the order marked
        ``execution_unknown``; an accepted request stays pending until the
        execution owner's durable order record reports the terminal state
        through ``refresh_managed_orders``. The order is never cancelled
        locally on the strength of the request alone.
        """
        if not isinstance(response, Mapping):
            response = {
                "execution_unknown": True,
                "error_code": "invalid_managed_cancel_projection",
            }
        unknown = (
            response.get("execution_unknown") is True
            or response.get("service_execution_cancel_state") == "UNKNOWN"
        )
        cancel_id = response.get("managed_cancel_intent_id")
        if isinstance(cancel_id, str) and cancel_id:
            order.addinfo(managed_cancel_intent_id=cancel_id)
        if response.get("status") == "rejected" and not unknown:
            order.addinfo(
                cancel_requested_remote=False,
                cancel_execution_unknown=False,
                cancel_intent_active=False,
                cancel_error_code=str(response.get("error_code") or "managed_cancel_rejected"),
                cancel_error_msg="The managed route rejected the cancellation.",
            )
            self.notify(order)
            return order
        if unknown:
            order.addinfo(
                cancel_requested_remote=True,
                cancel_execution_unknown=True,
                cancel_intent_active=True,
                execution_unknown=True,
                cancel_error_code=str(response.get("error_code") or "cancel_execution_unknown"),
                cancel_error_msg="Remote cancellation outcome is unknown",
            )
            self.orders[order.ref] = order
            self.notify(order)
            if self._uses_async_commands():
                self._request_order_reconcile(order)
            return order
        order.addinfo(
            cancel_requested_remote=True,
            cancel_execution_unknown=False,
            cancel_intent_active=True,
        )
        self.orders[order.ref] = order
        return order

    def _apply_managed_record(self, order, projection):
        """Project one durable managed-route record of a live order; ``True`` if handled.

        Only for a live managed route without the recovery journal (the
        recovery variant keeps its own receipts). The execution owner's
        durable record is the authority for its managed order: a cumulative
        fill is booked once through the cumulative-checkpoint rule (an
        unpriced or fee-less fill is not booked; no fill is invented), and a
        definite terminal state ends the order with the recorded fill size.
        """
        if (
            projection.get("kind") != "service_execution_record"
            or self._uses_service_execution_recovery()
            or not bool(getattr(self.store, "managed_execution_active", False))
            or projection.get("execution_unknown") is True
        ):
            return False
        status = projection.get("status")
        if projection.get("filled") is not None:
            update = {
                "kind": "order",
                "execution_source": "cumulative",
                "status": status,
                "filled_quantity": projection.get("filled"),
                "average_price": projection.get("avg_price") or projection.get("price"),
                "cumulative_commission": projection.get("cumulative_commission"),
                "fee_currency": projection.get("fee_currency"),
                "bt_order_ref": getattr(order, "ref", None),
                "data_name": self._position_key(order.data),
                "side": "buy" if order.isbuy() else "sell",
                "managed_intent_id": projection.get("managed_intent_id"),
                "quantity_unit": (self._order_execution_contracts.get(order.ref) or {}).get(
                    "quantity_unit"
                ),
            }
            self._apply_trade_from_order_update(order, update, managed_route=True)
            return True
        if status in {"rejected", "canceled", "expired"}:
            update = dict(projection)
            update.update(
                terminal_confirmed=True,
                filled_quantity=format(abs(float(order.executed.size or 0.0)), "f"),
                bt_order_ref=getattr(order, "ref", None),
                data_name=self._position_key(order.data),
                side="buy" if order.isbuy() else "sell",
            )
            self._apply_order_update(update)
            return True
        return False

    def apply_confirmed_terminal_observation(self, order, observation, *, source=None):
        """Resolve uncertainty markers from a late provider-confirmed terminal fact.

        The ordinary update path only projects orders the Broker still treats as
        live, so a confirmation that arrives after the framework order reached its
        local terminal state used to be dropped and left ``execution_unknown``
        stale on ``order.info``.  This projection is deliberately narrower: it
        writes the two uncertainty markers and the confirming origin, never a
        status transition, a fill or a second strategy notification.
        """
        if order is None:
            return False
        if not self._order_is_uncertain(order):
            return False
        if bool(self._order_info_get(order, "ledger_mismatch", False)):
            return False
        from bt_api_py.broker_event_envelope import confirmed_terminal_observation_status

        status = confirmed_terminal_observation_status(observation)
        if status is None:
            return False
        order.addinfo(
            execution_unknown=False,
            cancel_execution_unknown=False,
            confirmation_source=str(source or "provider_terminal_observation"),
            confirmed_terminal_status=status,
        )
        return True

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

    def _apply_order_update(self, update, *, from_query=False, from_store_callback=False):
        """Project a normalized SDK order observation into a Backtrader Order."""
        order = self._lookup_order(update)
        if order is None:
            return None

        self._cache_order_identifiers(
            order, update, from_store_callback=from_store_callback and not from_query
        )
        self._retry_pending_trade_updates()

        status = self._normalize_remote_order_status(update.get("status"))
        was_unknown = bool(self._order_info_get(order, "execution_unknown", False))
        if update.get("execution_unknown") is True or status == "unknown":
            if order.alive() and not was_unknown:
                order.addinfo(execution_unknown=True)
                self.notify(order)
                self._request_order_reconcile(order)
            return None

        status_msg = str(self._redact_runtime_value(update.get("status_msg") or ""))
        if status_msg:
            order.addinfo(error_msg=status_msg)

        if (
            self._uses_service_execution_recovery()
            and bool(self._order_info_get(order, "service_execution_recovery_managed", False))
            and update.get("execution_source") == "cumulative"
            and status in {"partial", "completed", "canceled"}
        ):
            if status in {"completed", "canceled"}:
                order.addinfo(
                    remote_terminal_status=status,
                    remote_terminal_filled=update.get("filled_quantity"),
                )
            return self._apply_trade_from_order_update(order, update)

        if status in {"accepted", "partial", "completed", "canceled", "rejected", "expired"}:
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
                )
            elif from_query and bool(
                self._order_info_get(order, "cancel_execution_unknown", False)
            ):
                order.addinfo(
                    cancel_requested_remote=False,
                    cancel_execution_unknown=False,
                    cancel_intent_active=True,
                    cancel_reconcile_confirmed_live=True,
                    cancel_deadline_monotonic_ns=None,
                    cancel_deadline_unknown_marked=False,
                )

        if status == "accepted":
            if order.status < order.Accepted or was_unknown:
                order.accept(self)
                self.notify(order)
            return None

        if status == "partial":
            order.addinfo(execution_pending_trades=True)
            if order.status < order.Accepted:
                order.accept(self)
            if order.executed.size:
                order.partial()
            self.notify(order)
            return "pending_fills"

        if status in {"completed", "canceled", "rejected", "expired"}:
            # Only the SDK's canonical terminal observation and its cumulative
            # filled quantity can close a local order. Order snapshots never
            # create execution bits; those come from separately correlated fills.
            return self._apply_trade_terminal_status(order, update, status)

        if status == "cancel_rejected":
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
        return None

    def _apply_trade_terminal_status(self, order, update, status):
        """Apply a terminal order state only after its reported fills are accounted for."""
        expected = self._neutral_decimal(update.get("filled_quantity"))
        total = self._neutral_decimal(abs(float(order.size or 0.0)))
        executed = self._neutral_decimal(abs(float(order.executed.size or 0.0)))
        if (
            update.get("terminal_confirmed") is not True
            or expected is None
            or expected < 0
            or total is None
            or executed is None
            or expected > total + Decimal("0.000000000001")
            or (status == "completed" and abs(expected - total) > Decimal("0.000000000001"))
            or expected < executed - Decimal("0.000000000001")
        ):
            order.addinfo(execution_unknown=True, error_code="terminal_order_observation_unproven")
            self.notify(order)
            self._request_order_reconcile(order)
            return "unknown"

        if status == "rejected":
            if expected != 0 or executed != 0:
                order.addinfo(execution_unknown=True, error_code="rejected_order_has_fills")
                self.notify(order)
                self._request_order_reconcile(order)
                return "unknown"
            self._attach_remote_error_code(order, update)
            order.addinfo(error_code="remote_reject")
            order.reject(self)
            self._clear_order_mappings(order)
            self.notify(order)
            return "terminal"

        order.addinfo(
            remote_terminal_status=status,
            remote_terminal_filled=format(expected, "f"),
        )
        self._set_status_after_fill(order)
        self.notify(order)
        if not order.alive():
            return "terminal"
        return "pending_fills"

    @staticmethod
    def _normalize_remote_order_status(status):
        """Accept only the SDK facade's canonical order-state vocabulary."""
        from bt_api_py.broker_event_envelope import canonical_broker_order_status

        return canonical_broker_order_status(status)

    def _apply_trade_from_order_update(self, order, update, *, managed_route=False):
        """Apply a service cumulative checkpoint (recovery, or a live managed route)."""
        if update.get("execution_source") != "cumulative":
            return "ignored"
        if not managed_route and (
            not self._uses_service_execution_recovery()
            or not bool(self._order_info_get(order, "service_execution_recovery_managed", False))
        ):
            return "ignored"
        if bool(self._order_info_get(order, "ledger_mismatch", False)):
            return "quarantined"

        filled_value = update.get("filled_quantity")
        try:
            cumulative_filled = float(filled_value)
            already_filled = abs(float(order.executed.size or 0.0))
        except (TypeError, ValueError):
            return "ignored"
        if not math.isfinite(cumulative_filled) or cumulative_filled <= 0:
            return "ignored"
        incremental_fill = cumulative_filled - already_filled
        if incremental_fill < -1e-12:
            return "ignored"

        if incremental_fill <= 1e-12:
            # Same cumulative quantity: at most a late fee (F5). It is applied
            # as a fee-only correction (no fill is fabricated); an unusable,
            # lower or foreign-currency fee keeps the recovery fence.
            fee = update.get("cumulative_commission")
            if fee not in (None, ""):
                outcome = self._apply_fee_only_correction(
                    order, fee, update.get("fee_currency")
                )
                if outcome == "corrected":
                    self.notify(order)  # also books the fee in the strategy ledger
            try:
                previous_average = float(update.get("average_price"))
            except (TypeError, ValueError, OverflowError):
                return "ignored"
            if not math.isfinite(previous_average) or previous_average <= 0:
                return "ignored"
            self._set_status_after_fill(order)
            return "ignored"

        average_price = update.get("average_price")
        try:
            average_price = float(average_price)
        except (TypeError, ValueError):
            return "ignored"
        if not math.isfinite(average_price) or average_price <= 0:
            return "ignored"
        currency = update.get("fee_currency")
        fee_known = update.get("cumulative_commission") not in (None, "") and (
            type(currency) is str and bool(currency)
        )
        if not fee_known and not managed_route:
            return "ignored"
        fee_fields = {}
        if fee_known:
            try:
                cumulative_commission = float(update["cumulative_commission"])
                prior_commission = float(order.executed.comm or 0.0)
            except (TypeError, ValueError):
                return "ignored"
            if not math.isfinite(cumulative_commission) or not math.isfinite(prior_commission):
                return "ignored"
            fee_fields = {
                "fee": cumulative_commission - prior_commission,
                "fee_currency": currency,
                "fee_unit": "currency",
            }
        else:
            # A managed record without a fee currency (the SDK service order
            # record carries none): the fill is a recorded fact, its fee is
            # unknown - booked without a fee, never as zero.
            order.addinfo(managed_commission_currency_unavailable=True)

        incremental_price = (
            cumulative_filled * average_price
            - already_filled * float(order.executed.price or 0.0)
        ) / incremental_fill
        if not math.isfinite(incremental_price) or incremental_price <= 0:
            return "ignored"
        trade_update = dict(update)
        for name in ("fee", "fee_currency", "fee_unit", "cumulative_commission"):
            trade_update.pop(name, None)
        trade_update.update(
            kind="trade",
            quantity=incremental_fill,
            price=incremental_price,
            **fee_fields,
        )
        trade_update.setdefault("side", "buy" if order.isbuy() else "sell")
        result = self._apply_trade_update(
            trade_update, defer_unmatched=False, from_cumulative_status=True
        )
        if result == "applied":
            self._set_status_after_fill(order)
        return result

    def _apply_trade_update(
        self,
        update,
        *,
        defer_unmatched=True,
        from_cumulative_status=False,
        position_override=None,
    ):
        """Project a Store-normalized execution event into Backtrader state."""
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
        """Project one Store-correlated fill into Backtrader order and position state."""
        trade_key = None if from_cumulative_status else self._trade_dedupe_key(update)
        if trade_key and trade_key in self._seen_trade_ids:
            return self._apply_repeated_fill_fee(trade_key, update)

        order = self._lookup_order(update)
        if order is None:
            # A fill an earlier process applied (restart): at most a late fee.
            durable = self._apply_durable_fill_fee(trade_key, update)
            if durable is not None:
                return durable
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
            return self._apply_repeated_fill_fee(trade_key, update)

        side_present, remote_is_buy = self._explicit_trade_side(update)
        if not side_present or remote_is_buy is None or remote_is_buy != bool(order.isbuy()):
            error_code = "trade_side_unrecognized" if remote_is_buy is None else "trade_side_mismatch"
            return self._block_trade_identity_mismatch(
                order,
                update,
                error_code,
                "SDK fill side is missing, unrecognized, or conflicts with the local order",
            )

        identity_error = self._trade_position_identity_error(order, update)
        if identity_error is not None:
            return self._block_trade_identity_mismatch(order, update, *identity_error)

        fill_qty = self._neutral_decimal(self._extract_update_value(update, "quantity"), positive=True)
        fill_price = self._neutral_decimal(self._extract_update_value(update, "price"), positive=True)
        if fill_qty is None or fill_price is None:
            return self._block_trade_identity_mismatch(
                order,
                update,
                "fill_quantity_or_price_invalid",
                "SDK fill quantity and price must be finite positive neutral values",
            )

        remaining_qty = self._neutral_decimal(self._order_remaining_qty(order))
        if remaining_qty is None or fill_qty > remaining_qty + Decimal("0.000000000001"):
            return self._block_trade_identity_mismatch(
                order,
                update,
                "trade_size_exceeds_remaining",
                "SDK fill quantity exceeds the locally remaining order quantity",
            )

        fill_quantity = float(fill_qty)
        price = float(fill_price)
        if self._is_dual_side_mode():
            result = self._apply_dual_side_trade_update(order, update, fill_quantity, price)
            if result != "applied":
                return result
            if trade_key:
                self._seen_trade_ids.add(trade_key)
                self._remember_applied_fill(trade_key, order, fill_qty, fill_price, update)
                self._flush_durable_fills(order)  # its notification was journaled already
            return result

        signed_fill = fill_quantity if remote_is_buy else -fill_quantity
        position = (
            position_override
            if position_override is not None
            else self.positions[self._position_key(order.data)]
        )
        preview = position.clone()
        old_size = preview.size
        old_price = preview.price
        comminfo = order.comminfo or self.getcommissioninfo(order.data)
        psize, pprice, opened, closed = preview.update(
            signed_fill,
            price,
            dt=self._execution_datetime(update),
        )

        actual_commission, commission_error = self._normalized_commission(update)
        allow_local_estimate = not (
            bool(getattr(self.store, "_sdk_mode", False)) or self._uses_async_commands()
        )
        # Keywords: the helper takes (opened_qty, closed_qty); a positional
        # (closed, opened) call booked an opening fill's fee as closed (F5).
        closed_commission, opened_commission = self._execution_commissions(
            comminfo,
            price,
            opened_qty=abs(opened),
            closed_qty=abs(closed),
            actual_commission=actual_commission,
            allow_local_estimate=allow_local_estimate,
        )
        closed_value = self._execution_value(comminfo, closed, old_price or price)
        opened_value = self._execution_value(comminfo, opened, price)
        pnl = 0.0
        if closed:
            pnl = (
                comminfo.profitandloss(-closed, old_price, price)
                if comminfo is not None
                else abs(closed)
                * (price - old_price if old_size > 0 else old_price - price)
            )

        position.__dict__.update(preview.__dict__)
        if not allow_local_estimate:
            order.addinfo(
                commission_source="sdk" if actual_commission is not None else "unavailable",
                actual_commission_known=actual_commission is not None,
                commission_error=(
                    "fee_currency_not_account_bound"
                    if actual_commission is not None
                    else commission_error or "sdk_fee_unavailable"
                ),
                pnl_status="PNL_INCOMPLETE",
                observed_fee_amount=self._extract_update_value(update, "fee"),
                observed_fee_currency=self._extract_update_value(update, "fee_currency"),
                observed_fee_unit=self._extract_update_value(update, "fee_unit"),
            )
        elif actual_commission is not None:
            order.addinfo(
                commission_source="sdk",
                actual_commission_known=True,
                pnl_status="COMPLETE",
            )
        else:
            order.addinfo(
                commission_source="backtrader_comminfo",
                actual_commission_known=False,
            )

        order.execute(
            dt=self._order_execution_dt(order),
            size=signed_fill,
            price=price,
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
        if actual_commission is not None:
            self._record_provider_fee(order, update, actual_commission)
        self._cache_order_identifiers(order, update)
        self._set_status_after_fill(order)
        if trade_key:
            self._remember_applied_fill(trade_key, order, fill_qty, fill_price, update)
        self.notify(order)
        if trade_key:
            self._seen_trade_ids.add(trade_key)
        return "applied"

    # -- late fee on an already applied fill (re-verification F5, direct) ------

    def _remember_applied_fill(self, trade_key, order, quantity, price, update):
        """Keep the fee booked for one applied fill, to recognise a late correction.

        With notification recovery bound the fill is also indexed durably
        with the order's next journaled notification, so a correction that
        reaches a restarted process is still recognised.
        """
        fills = self.__dict__.setdefault("_applied_fill_fees", {})
        amount, _error = self._normalized_commission(update)
        currency = self._extract_update_value(update, "fee_currency")
        booked = None if amount is None else Decimal(str(amount))
        currency = currency if type(currency) is str and currency else None
        fills[trade_key] = (order, quantity, price, booked, currency)
        self._stash_durable_fill(trade_key, order, quantity, price, booked, currency, update)

    def _apply_repeated_fill_fee(self, trade_key, update):
        """Handle a fill id seen before: at most a fee-only correction.

        Contract: the provider re-reports an applied fill (same fill id, same
        quantity and price) with its corrected fee for that fill. A higher fee
        in the same currency is a fee-only correction of the difference
        (``_book_fee_correction``: order commission, ledger fee totals, then
        the Strategy's Trade and ``notify_fee_correction``); no fill is
        created. The same fee is an idempotent duplicate (``"ignored"``). A
        lower fee, another currency, or a fee for a fill booked without one
        cannot be projected: the order is marked ``PNL_INCOMPLETE`` and new
        openings and trading are fenced (``"fee_fenced"``). A different
        quantity or price, or a fill without a fee, stays an ignored duplicate.
        """
        if trade_key in self._quarantined_trade_ids:
            return "ignored"
        record = (self.__dict__.get("_applied_fill_fees") or {}).get(trade_key)
        if record is None:
            return "ignored"
        order, quantity, price, booked, booked_currency = record
        amount, error = self._normalized_commission(update)
        if amount is None:
            return "ignored"
        if (
            self._neutral_decimal(self._extract_update_value(update, "quantity"), positive=True)
            != quantity
            or self._neutral_decimal(self._extract_update_value(update, "price"), positive=True)
            != price
        ):
            return "ignored"
        reported = Decimal(str(amount))
        currency = self._extract_update_value(update, "fee_currency")
        if booked is not None and reported == booked and currency == booked_currency:
            return "ignored"
        if booked is None or currency != booked_currency or reported < booked:
            order.addinfo(
                execution_commission_unavailable=True,
                execution_pnl_unavailable=True,
                pnl_status="PNL_INCOMPLETE",
                fee_correction_error=(
                    "fee_regressed"
                    if booked is not None and currency == booked_currency
                    else "fee_currency_or_basis_mismatch"
                ),
            )
            self._trading_enabled = False
            freeze = getattr(self.store, "freeze_openings", None)
            if callable(freeze):
                freeze("fill_fee_correction_unprojectable")
            self.notify(order)
            return "fee_fenced"
        self._book_fee_correction(order, reported - booked, reported, currency)
        self.__dict__["_applied_fill_fees"][trade_key] = (
            order, quantity, price, reported, currency
        )
        self._stash_durable_fill(trade_key, order, quantity, price, reported, currency, update)
        self.notify(order)
        return "fee_corrected"

    def _record_provider_fee(self, order, update, amount):
        """Keep the provider-reported cumulative fee of ``order`` per currency.

        The strategy ledger books fees by (intent, currency) from these totals
        (acceptance report F4); a fee without an explicit currency is not kept.
        """
        currency = self._extract_update_value(update, "fee_currency")
        if type(currency) is not str or not currency:
            return
        totals = dict(self._order_info_get(order, "provider_fee_totals") or {})
        prior = Decimal(totals.get(currency, "0"))
        totals[currency] = str(prior + Decimal(str(amount)))
        order.addinfo(provider_fee_totals=totals)

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

    def _freeze_order_execution_contract(self, order, *, replace=False):
        """Capture the neutral order identity used to correlate later SDK fills."""
        existing = self._order_execution_contracts.get(order.ref)
        if existing is not None and not replace:
            return existing
        from bt_api_py.broker_event_envelope import (
            normalize_neutral_code_text,
            normalize_neutral_quantity_unit,
        )

        sdk_contract = self._order_info_get(order, "sdk_execution_contract")
        if isinstance(sdk_contract, dict) and sdk_contract:
            raw = dict(sdk_contract)
            source = "sdk_request"
        else:
            raw = {
                "side": "buy" if order.isbuy() else "sell",
                "position_side": self._order_info_get(order, "position_side"),
                "offset": self._order_info_get(order, "offset"),
                "position_mode": self._order_info_get(
                    order, "position_mode", self.get_param("position_mode")
                ),
                "quantity_unit": self._order_info_get(order, "quantity_unit"),
                "requested_quantity": str(abs(float(order.size or 0.0))),
            }
            source = "broker_intent"
        contract = {
            "side": normalize_neutral_code_text(raw.get("side")),
            "position_side": normalize_position_side(raw.get("position_side")),
            "offset": normalize_position_offset(raw.get("offset")),
            "position_mode": normalize_position_mode(raw.get("position_mode")),
            "quantity_unit": normalize_neutral_quantity_unit(raw.get("quantity_unit")),
            "requested_quantity": str(raw.get("requested_quantity") or ""),
            "source": source,
        }
        self._order_execution_contracts[order.ref] = contract
        return contract

    def _trade_position_identity_error(self, order, update):
        """Check only neutral fill fields against the frozen local order identity."""
        contract = self._order_execution_contracts.get(order.ref)
        if contract is None:
            contract = self._freeze_order_execution_contract(order)
        expected_unit = contract.get("quantity_unit")
        remote_unit = self._extract_update_value(update, "quantity_unit")
        if expected_unit is None:
            if bool(getattr(self.store, "_sdk_mode", False)):
                return (
                    "fill_quantity_unit_unavailable",
                    "The SDK order request has no bound neutral quantity unit",
                )
            return None
        if remote_unit in (None, ""):
            return (
                "fill_quantity_unit_unavailable",
                "The SDK fill omitted its neutral quantity unit",
            )
        from bt_api_py.broker_event_envelope import normalize_neutral_quantity_unit

        normalized = normalize_neutral_quantity_unit(remote_unit)
        if normalized is None:
            return (
                "fill_quantity_unit_unrecognized",
                "The SDK fill quantity unit is not a neutral string",
            )
        if normalized != expected_unit:
            return (
                "fill_quantity_unit_mismatch",
                "The SDK fill quantity unit conflicts with the local order",
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
        """Project a neutral fill into the configured long/short BT position book."""
        isbuy = self._trade_update_is_buy(update, order)
        position_side = normalize_position_side(
            self._order_info_get(order, "position_side")
        )
        if position_side not in {"long", "short"}:
            return self._block_trade_identity_mismatch(
                order,
                update,
                "fill_position_side_unavailable",
                "A dual-side order has no bound Backtrader position side",
            )
        offset = self._order_info_get(order, "offset")
        exec_size = fill_qty if isbuy else -fill_qty

        leg_position = self._get_leg_position(order.data, position_side)
        signed_position = self._make_signed_position(position_side, leg_position)
        pprice_orig = signed_position.price
        psize, pprice, opened, closed = signed_position.update(
            exec_size,
            fill_price,
            dt=self._execution_datetime(update),
        )

        comminfo = order.comminfo or self.getcommissioninfo(order.data)
        actual_commission, commission_error = self._normalized_commission(update)
        allow_local_estimate = not (
            bool(getattr(self.store, "_sdk_mode", False)) or self._uses_async_commands()
        )
        # Keywords: the helper takes (opened_qty, closed_qty); a positional
        # (closed, opened) call booked an opening fill's fee as closed (F5).
        closed_commission, opened_commission = self._execution_commissions(
            comminfo,
            fill_price,
            opened_qty=abs(opened),
            closed_qty=abs(closed),
            actual_commission=actual_commission,
            allow_local_estimate=allow_local_estimate,
        )
        closed_value = self._execution_value(comminfo, closed, pprice_orig or fill_price)
        opened_value = self._execution_value(comminfo, opened, fill_price)
        pnl = comminfo.profitandloss(-closed, pprice_orig, fill_price) if closed else 0.0

        self._apply_signed_position(position_side, leg_position, signed_position)
        self._sync_net_position(order.data)
        if not allow_local_estimate:
            order.addinfo(
                commission_source="sdk" if actual_commission is not None else "unavailable",
                actual_commission_known=actual_commission is not None,
                commission_error=(
                    "fee_currency_not_account_bound"
                    if actual_commission is not None
                    else commission_error or "sdk_fee_unavailable"
                ),
                pnl_status="PNL_INCOMPLETE",
                observed_fee_amount=self._extract_update_value(update, "fee"),
                observed_fee_currency=self._extract_update_value(update, "fee_currency"),
                observed_fee_unit=self._extract_update_value(update, "fee_unit"),
            )
        elif actual_commission is not None:
            order.addinfo(
                commission_source="sdk",
                actual_commission_known=True,
                pnl_status="COMPLETE",
            )
        else:
            order.addinfo(
                commission_source="backtrader_comminfo",
                actual_commission_known=False,
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
        self._verified_risk_reducing_orders.discard(id(order))
        self._order_execution_contracts.pop(getattr(order, "ref", None), None)
        for key, mapped_order in list(self._orders_by_external_id.items()):
            if mapped_order is order:
                self._orders_by_external_id.pop(key, None)
        for key, mapped_order in list(self._orders_by_client_ref.items()):
            if mapped_order is order:
                self._orders_by_client_ref.pop(key, None)
        self._order_correlations.pop(getattr(order, "ref", None), None)

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
        resolver = getattr(self.store, "get_market_instrument_key", None)
        if not callable(resolver):
            return None
        try:
            instrument = resolver(self._position_key(order.data))
            venue = self._neutral_record_value(instrument, "venue")
            return venue if type(venue) is str and venue else None
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
        local_ref = details.get("local_ref") or update.get("local_ref")
        if type(local_ref) is int and local_ref in self.orders:
            return self.orders[local_ref]
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

        order_ref = self._remote_client_order_id(update)
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

    def _prepare_order_correlation(self, order):
        """Bind a provider-neutral write identity through the SDK-backed Store."""
        method = getattr(self.store, "prepare_order_correlation", None)
        if not callable(method):
            raise _OrderCorrelationUnavailableError(
                "The unified SDK facade does not support order-correlation preparation"
            )
        correlation = method(order)
        if correlation is None:
            raise _OrderCorrelationUnavailableError(
                "The unified SDK facade did not return a bound order correlation"
            )
        return correlation

    def _verify_order_response(self, correlation, response):
        """Accept only an SDK-verified response for the prepared correlation."""
        method = getattr(self.store, "verify_order_response", None)
        if not callable(method):
            return False
        try:
            return method(correlation, response) is True
        except Exception as exc:
            _safe_log("warning", "btapibroker: order response verification failed")
            self._sanitize_exception(exc)
            return False

    def _verify_order_reconciliation(self, correlation, response):
        """Accept one Store projection only after its SDK snapshot is revalidated."""
        method = getattr(self.store, "verify_order_reconciliation", None)
        if not callable(method):
            return False
        try:
            result = method(correlation, response)
        except Exception as exc:
            _safe_log("warning", "btapibroker: order reconciliation verification failed")
            self._sanitize_exception(exc)
            return False
        return type(result) is bool and result is True

    def _verify_reconciliation_snapshot(self, response):
        """Revalidate an account snapshot's SDK lease before advancing the barrier."""
        method = getattr(self.store, "verify_reconciliation_snapshot", None)
        if not callable(method):
            return False
        try:
            result = method(response)
        except Exception as exc:
            _safe_log("warning", "btapibroker: reconciliation snapshot verification failed")
            self._sanitize_exception(exc)
            return False
        return type(result) is bool and result is True

    def _verify_cancel_response(self, correlation, response):
        """Accept only an SDK-verified cancellation result for a known order."""
        method = getattr(self.store, "verify_cancel_response", None)
        if not callable(method):
            return False
        try:
            return method(correlation, response) is True
        except Exception as exc:
            _safe_log("warning", "btapibroker: cancel response verification failed")
            self._sanitize_exception(exc)
            return False

    def _cache_order_identifiers(self, order, update, *, from_store_callback=False):
        """Attach only SDK-normalized identifiers to a local Backtrader order."""
        external_id = self._remote_external_order_id(update)
        client_order_id = self._remote_client_order_id(update)
        if external_id not in (None, ""):
            order.addinfo(external_order_id=external_id)
            self._orders_by_external_id[str(external_id)] = order
        if client_order_id not in (None, ""):
            order.addinfo(client_order_id=client_order_id)
            self._remember_client_ref(order, client_order_id, update)

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
        from bt_api_py.broker_event_envelope import broker_event_trade_side

        return broker_event_trade_side(update, extract_value=cls._extract_update_value)

    @staticmethod
    def _extract_update_value(update, *keys):
        """Read a top-level or detail payload field from a broker update."""
        from bt_api_py.broker_event_envelope import broker_event_value

        return broker_event_value(update, *keys)

    @classmethod
    def _normalized_commission(cls, update):
        """Return an SDK-projected fee only when its denomination is explicit."""
        amount = cls._extract_update_value(update, "fee")
        currency = cls._extract_update_value(update, "fee_currency")
        unit = cls._extract_update_value(update, "fee_unit")
        try:
            from bt_api_py.reconciliation import parse_reported_commission
        except ImportError:
            return None, "fee_contract_unavailable"
        commission, error = parse_reported_commission(amount, currency, unit)
        if error is not None:
            return None, error
        return float(commission.amount), None

    @classmethod
    def _execution_commissions(
        cls,
        comminfo,
        price,
        opened_qty,
        closed_qty,
        offset=None,
        actual_commission=None,
        allow_local_estimate=True,
    ):
        """Project an SDK fee or an explicitly configured Backtrader comminfo."""
        opened_qty = abs(float(opened_qty or 0.0))
        closed_qty = abs(float(closed_qty or 0.0))
        if actual_commission is not None:
            total_commission = float(actual_commission)
            total_qty = opened_qty + closed_qty
            if total_qty <= 0.0:
                return 0.0, 0.0
            if closed_qty <= 0.0:
                return 0.0, total_commission
            if opened_qty <= 0.0:
                return total_commission, 0.0
            closed_commission = total_commission * (closed_qty / total_qty)
            return closed_commission, total_commission - closed_commission
        if not allow_local_estimate or comminfo is None:
            return 0.0, 0.0
        closed_commission = (
            float(comminfo.getcommission(closed_qty, price) or 0.0)
            if closed_qty > 0.0
            else 0.0
        )
        opened_commission = (
            float(comminfo.getcommission(opened_qty, price) or 0.0)
            if opened_qty > 0.0
            else 0.0
        )
        return closed_commission, opened_commission

    @staticmethod
    def _execution_value(comminfo, size, price):
        """Project value through an explicitly configured Backtrader comminfo."""
        size = float(size or 0.0)
        price = float(price or 0.0)
        if not math.isfinite(size) or not math.isfinite(price):
            raise ValueError("execution value requires finite size and price")
        if not size:
            return 0.0
        if comminfo is None:
            return abs(size) * abs(price)
        return abs(float(comminfo.getoperationcost(size, price) or 0.0))

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
