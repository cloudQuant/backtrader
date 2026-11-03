#!/usr/bin/env python
"""Unified bt_api_py-backed live store.

This module centralizes live trading integrations behind a single store
implementation. Venue-specific adapters such as CTP, CCXT, IB, Oanda,
Futu, and VC are intentionally removed from the public surface.
"""

from __future__ import annotations

import asyncio
import collections
import contextvars
import datetime as _dt
import functools
import math
import threading
import time
import uuid
from collections.abc import Mapping, Sequence
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, cast

from ..utils.coercion import coerce_float as _coerce_float
from ..utils.coercion import coerce_text as _coerce_text
from ..utils.log_message import get_logger
from ..utils.redaction import masked_copy as _masked_copy_impl
from ..utils.redaction import redact_diagnostic as _redact_diagnostic
from ..utils.runtime_redaction import credential_values as _runtime_credential_values
from ..utils.runtime_redaction import is_sensitive_key as _runtime_is_sensitive_key
from ..utils.runtime_redaction import redact_runtime_value as _runtime_redact_value
from ..utils.runtime_redaction import replace_secret_values as _runtime_replace_secrets
from ..utils.runtime_redaction import sanitize_exception as _runtime_sanitize_exception
from ..utils.bar_projection import normalize_bar as _normalize_bar
from ..utils.tick_snapshot import snapshot_tick as _snapshot_tick
from .livestore import LiveStoreBase
from ._btapi_errors import (
    BtApiStoreError,
    LegacyGatewayMigrationRequiredError,
    _ApprovalLeaseRejected,
    BtApiMissingDependencyError,
    BtApiProviderNotImplementedError,
)
from ..service._store_managed_bridge import StoreManagedExecutionBridgeMixin
from ..execution.managed_execution import (
    ManagedExecutionAdapter,
    ManagedExecutionAdapterError,
    require_managed_cancel,
    require_managed_execution_adapter,
)
from ..execution.sdk_execution import SdkExecutionCoordinator
from ..execution.store_reconciliation_bridge import StoreReconciliationBridgeMixin
from ..execution._store_execution_binding_registry import StoreExecutionBindingRegistry
from ..execution.order_preflight import _StoreOrderPreflightContext
from ..execution.sdk_correlated_order_adapter import (
    SdkCorrelatedOrderAdapter,
    prepare_store_order_correlation as _prepare_store_order_correlation,
    resolve_store_order_request_context as _resolve_store_order_request_context,
)
from ..execution.store_route_policy import StoreRouteIdentityPolicy
from ..execution.store_order_projection import (
    extract_dataname as _project_dataname,
    order_to_payload as _project_order_to_payload,
    order_type_to_payload as _project_order_type_to_payload,
    project_broker_runtime_event as _project_broker_runtime_event,
)
from ..execution.command_completion_projection import unsent_command_completion as _project_unsent_completion
from ._account_position_projection import (
    project_store_account_positions as _project_store_account_positions,
)
from ._account_balance_projection import (
    project_account_balance_snapshot as _project_account_balance_snapshot,
    project_venue_balance_snapshot as _project_venue_balance_snapshot,
    project_sdk_account_push_values as _project_sdk_account_push_values,
    require_single_balance_currency as _require_single_balance_currency,
)
from ..execution.unverified_order_projection import (
    project_store_unverified_order_event as _project_store_unverified_order_event,
    record_store_unverified_execution_event as _record_store_unverified_execution_event,
)
from ..service.store_event_dispatch import drain_store_sdk_events_locked as _drain_store_sdk_events_locked
from ..execution.account_risk_state import (
    read_store_account_risk_snapshot as _read_store_account_risk_snapshot,
)
from ..service.bounded_metadata_probe import (
    run_store_metadata_probe as _run_store_metadata_probe,
)
from ..service.store_event_notifier import StoreEventNotifier
from ..service.store_lifecycle import (
    ensure_store_api_ready as _ensure_store_api_ready,
    prepare_store_sdk_start as _prepare_store_sdk_start,
    start_store as _start_store,
    stop_store as _stop_store,
    stop_synchronous_store_sdk as _stop_synchronous_store_sdk,
)
from ..service.sdk_reconciliation_adapter import SdkReconciliationAdapter
from ..execution.sdk_command_runtime import SdkCommandRuntime
from ..execution.reconciliation_projection import (
    apply_reconcile_snapshot as _apply_reconcile_snapshot,
    verify_order_reconciliation as _verify_order_reconciliation,
    verify_reconciliation_snapshot as _verify_reconciliation_snapshot,
)
from ._live_bar_queue import StoreLiveBarQueue
from ._bar_history_cache import StoreBarHistoryCache, history_timeframe
from ._market_delivery_state import StoreMarketDeliveryState

logger = get_logger(__name__)

_LOGGING_HEALTH: "collections.Counter[str]" = collections.Counter()


async def _run_in_thread(func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """Run synchronous SDK work off the event loop on Python 3.8 and later.

    ``asyncio.to_thread`` was added in Python 3.9. Its fallback preserves the
    default executor and ``ContextVar`` propagation used by that API.
    """
    to_thread = getattr(asyncio, "to_thread", None)
    if to_thread is not None:
        return await to_thread(func, *args, **kwargs)

    loop = asyncio.get_running_loop()
    context = contextvars.copy_context()
    call = functools.partial(context.run, func, *args, **kwargs)
    return await loop.run_in_executor(None, call)


def _safe_log(level: str, message: str, *args: Any) -> None:
    """Write a diagnostic without allowing a broken sink into trading control flow."""
    try:
        getattr(logger, level)(_redact_diagnostic(message), *map(_redact_diagnostic, args))
    except Exception:
        # No logging here by design: the sink itself just failed; calling the
        # logger again would raise before the health counter is incremented.
        _LOGGING_HEALTH["logging_errors"] += 1


_COMMAND_PRIORITY = {
    "reconcile": 0,
    "cancel": 1,
    "close": 2,
    "open": 3,
}

def _contract_mapping(value: Any, contract_name: str) -> Dict[str, Any]:
    """Convert a public SDK mapping/dataclass without importing venue schemas."""
    from bt_api_py.contract_mapping import contract_mapping as _project_contract_mapping

    return _project_contract_mapping(
        value,
        contract_name,
        error_type=BtApiStoreError,
    )


def _sdk_cross_venue_contracts():
    """Load public SDK validation primitives without a core import dependency.

    Backtrader's generic Store remains importable without the optional SDK.
    When it is configured for ``provider='btapi'``, validation comes from the
    SDK's public cross-venue contract rather than a local venue-schema copy.
    """

    try:
        from bt_api_py.cross_venue import (
            CrossVenueValueError,
            coerce_funding_snapshot,
            normalize_orderbook_evidence,
        )
    except ImportError as exc:
        _safe_log("error", "btapistore:323 re-raising ImportError")
        raise BtApiMissingDependencyError(
            "BtApiStore cross-venue validation requires bt_api_py"
        ) from exc
    return CrossVenueValueError, coerce_funding_snapshot, normalize_orderbook_evidence


_PLACEHOLDER_PROVIDERS = frozenset({"futu", "oanda", "vc"})
_BACKENDS = frozenset({"direct"})
_UTC = _dt.timezone.utc
_WRITE_ROUTE_API_UNSET = object()


def _is_supported_api_facade(api: Any) -> Tuple[bool, bool]:
    """Return ``(is_bt_api, is_read_proxy)`` for the public Store entrypoints.

    The SDK protocol validates the provider-neutral call shape only.  It does
    not attest route authority or grant write capability; SDK typed command
    methods retain those checks.  The separate Backtrader ``ServiceReadProxy``
    remains available for its documented read-only use.
    """
    if api is None:
        return False, False
    try:
        from ..service.service_read_proxy import ServiceReadProxy
    except ImportError:
        ServiceReadProxy = None
    if ServiceReadProxy is not None and type(api) is ServiceReadProxy:
        return False, True
    try:
        from bt_api_py.facade_protocol import is_unified_bt_api_facade
    except ImportError as exc:
        raise BtApiMissingDependencyError(
            "bt_api_py.facade_protocol.UnifiedBtApiFacade is required"
        ) from exc
    return bool(is_unified_bt_api_facade(api)), False


def _contract_metadata_aliases(symbol: Any) -> List[str]:
    """Return symbol aliases used when matching configured contract metadata."""
    from bt_api_py.instrument_metadata_aliases import contract_metadata_aliases

    return contract_metadata_aliases(_coerce_text(symbol))


def _is_gateway_provider(provider: Any) -> bool:
    text = str(provider or "").strip().lower()
    return text == "gateway" or text.endswith("_gateway")


def _legacy_gateway_entrypoint(provider: Any, backend: Any = None) -> Optional[str]:
    backend_text = str(backend or "").strip().lower()
    provider_text = str(provider or "").strip().lower()
    if backend_text in {"gateway", "forwarding"}:
        return f"backend={backend_text!r}"
    if provider_text == "forwarding":
        return "provider='forwarding'"
    if _is_gateway_provider(provider_text):
        return f"provider={provider_text!r}"
    return None


def _resolve_backend(provider: Any, backend: Any = None) -> str:
    legacy_entrypoint = _legacy_gateway_entrypoint(provider, backend)
    if legacy_entrypoint is not None:
        raise LegacyGatewayMigrationRequiredError(legacy_entrypoint)
    text = str(backend or "").strip().lower()
    if text:
        if text not in _BACKENDS:
            raise ValueError(f"Unsupported BtApiStore backend {backend!r}")
        return text
    return "direct"


class BtApiStore(StoreManagedExecutionBridgeMixin, StoreReconciliationBridgeMixin, LiveStoreBase):
    """Backtrader lifecycle and projection facade over the bt_api_py API."""

    BrokerCls = None
    DataCls = None

    @property
    def _broker(self):
        """Compatibility alias for the inherited single broker field."""
        return self.broker

    @_broker.setter
    def _broker(self, broker):
        self.broker = broker

    @property
    def _data_feeds(self):
        """Compatibility alias for the inherited Store data list."""
        if self.datas is None:
            self.datas = []
        return self.datas

    @_data_feeds.setter
    def _data_feeds(self, feeds):
        self.datas = feeds

    def __init__(
        self,
        provider: str = "btapi",
        api: Any = None,
        api_cls: Any = None,
        config: Optional[Dict[str, Any]] = None,
        api_kwargs: Optional[Dict[str, Any]] = None,
        cash: float = 0.0,
        value: Optional[float] = None,
        account_cache_ttl: float = 0.0,
        positions_cache_ttl: float = 0.0,
        open_orders_cache_ttl: float = 0.0,
        positions: Optional[Iterable[Dict[str, Any]]] = None,
        historical_bars: Optional[Dict[str, Iterable[Any]]] = None,
        live_bars: Optional[Dict[str, Iterable[Any]]] = None,
        preserve_raw_bars: bool = False,
        contract_metadata: Optional[Dict[str, Dict[str, Any]]] = None,
        backend: Optional[str] = None,
        managed_execution_adapter: Optional[ManagedExecutionAdapter] = None,
        execution_authorization: Any = None,
        settlement_authorization: Any = None,
        autostart: bool = False,
        **kwargs: Any,
    ):
        """Initialize the BtApiStore.

        Args:
            provider: Optional route label. Non-``btapi`` labels must match
                an explicitly configured facade exchange-name root.
            api: Optional object implementing the public provider-neutral
                ``UnifiedBtApiFacade`` shape, or a read-only ``ServiceReadProxy``.
                The facade shape does not itself grant route or write authority.
            api_cls: Optional callable which constructs a facade implementing
                ``UnifiedBtApiFacade``. The constructed object is validated
                against that public shape before use.
            config: Optional configuration dictionary. ``live_bar_queue_size``
                sets the bounded completed-bar queue capacity per symbol. It
                defaults to ``book_queue_size`` (256); overflow is sticky for
                this Store lifetime and requires a new Store before a cohort
                can start.
            api_kwargs: Optional API keyword arguments.
            cash: Initial cash amount (default: 0.0).
            value: Initial portfolio value (default: same as cash).
            account_cache_ttl: Time-to-live for account cache in seconds.
            positions_cache_ttl: Retired legacy setting; typed position reads are fresh.
            open_orders_cache_ttl: Retired legacy setting; open orders use reconciliation.
            positions: Initial positions list.
            historical_bars: Pre-seeded historical bars by symbol.
            live_bars: Pre-seeded live bars by symbol. The completed-bar queue
                is bounded by ``config['live_bar_queue_size']`` (defaulting to
                ``book_queue_size``, or 256). Every eviction is counted and
                marks this Store's stream stale; create a new Store to begin a
                clean source epoch after any bar loss.
            preserve_raw_bars: Preserve raw bar fields for strict opt-in consumers.
            contract_metadata: Contract metadata by symbol.
            backend: Runtime backend. Only ``direct`` remains supported here.
            managed_execution_adapter: A trusted Iteration 41 adapter attached
                only after configuration-first capability resolution.  The
                Store never discovers or constructs this from user config.
            execution_authorization: Optional opaque SDK-issued authorization
                supplied by the managed execution composition. It is passed
                unchanged to the SDK correlated claim and dispatch methods;
                the Store does not construct, inspect, serialize, or log it.
            settlement_authorization: Optional opaque SDK-issued one-shot
                settlement authorization supplied by the managed composition.
                It remains separate from order authorization and is passed
                unchanged to the SDK settlement claim and confirmation methods.
            autostart: Whether to start the store on initialization.
            **kwargs: Additional SDK configuration values.
        """
        super().__init__()
        if type(preserve_raw_bars) is not bool:
            raise TypeError("preserve_raw_bars must be bool")
        self._history_cache = StoreBarHistoryCache(
            preserve_raw_bars=preserve_raw_bars,
            normalize_bar=_normalize_bar,
        )
        self.provider = self._resolve_provider(provider)
        self.backend = _resolve_backend(self.provider, backend)
        self._sdk_route_policy = StoreRouteIdentityPolicy(
            self,
            error_type=BtApiStoreError,
            is_supported_api_facade=_is_supported_api_facade,
            api_unset=_WRITE_ROUTE_API_UNSET,
        )
        self._managed_execution_adapter = require_managed_execution_adapter(
            managed_execution_adapter
        )
        self._execution_authorization = execution_authorization
        self._settlement_authorization = settlement_authorization
        self._service_execution_group_adapter = None
        if api_cls is not None:
            if not callable(api_cls):
                raise BtApiStoreError(
                    "api_cls must be a callable that constructs the public "
                    "bt_api_py unified facade"
                )
        api_is_bt_api = False
        api_is_read_proxy = False
        if api is not None:
            api_is_bt_api, api_is_read_proxy = _is_supported_api_facade(api)
            if not (api_is_bt_api or api_is_read_proxy):
                raise BtApiStoreError(
                    "api must implement the public bt_api_py unified facade shape "
                    "or be a read-only ServiceReadProxy"
                )
        self._api = api
        self._api_cls = api_cls
        self._sdk_custom_api_factory = api_cls is not None
        self._config = dict(config or {})
        self._api_kwargs = dict(api_kwargs or {})
        # Merge extra SDK settings into _api_kwargs.
        if kwargs:
            self._api_kwargs.update(kwargs)
        sdk_options = {**self._config, **self._api_kwargs}
        self._service_read_only = api_is_read_proxy
        self._sdk_mode = bool(
            not self._service_read_only
            and self.backend == "direct"
            and (
                isinstance(sdk_options.get("exchange_kwargs"), Mapping)
                or api_is_bt_api
                or api_cls is not None
            )
        )
        self._service_read_only_stopped = False
        configured_exchanges = sdk_options.get("exchange_kwargs")
        if isinstance(configured_exchanges, Mapping):
            self._sdk_direct_exchange_kwargs = dict(configured_exchanges)
            self._sdk_exchanges = {name: {} for name in configured_exchanges}
        elif api_is_bt_api:
            # The facade exposes route names only; Store never reads credentials
            # or endpoint values back out of the API object.
            self._sdk_direct_exchange_kwargs = None
            self._sdk_exchanges = {name: {} for name in self._facade_exchange_names(api)}
        else:
            self._sdk_direct_exchange_kwargs = None
            self._sdk_exchanges = {}
        self._sdk_direct_api_assembly = None
        self._sdk_routes = dict(sdk_options.get("symbol_routes") or {})
        configured_route_names = self._sdk_route_policy.write_route_names(
            self._sdk_exchanges, error_type=BtApiStoreError
        )
        symbol_route_names = self._sdk_route_policy.write_route_names(
            self._sdk_routes.values(), error_type=BtApiStoreError
        )
        if not self._service_read_only and not self._sdk_exchanges:
            raise BtApiStoreError(
                "BtApiStore requires explicit routes through the bt_api_py unified facade"
            )
        if symbol_route_names - configured_route_names:
            raise BtApiStoreError(
                "symbol_routes must refer only to exchanges explicitly present in exchange_kwargs"
            )
        if self.provider != "btapi" and not self._service_read_only:
            if configured_route_names != {self.provider.upper()}:
                raise BtApiStoreError(
                    "provider label must exactly match the root of explicit exchange_kwargs routes"
                )

        from bt_api_py.direct_api_assembly import direct_execution_config_snapshot

        self._sdk_execution_config = direct_execution_config_snapshot(sdk_options)
        self._sdk_require_account_risk = bool(sdk_options.get("require_account_risk", False))
        from bt_api_py.execution_identity_fence import ExecutionIdentityFence

        self._sdk_execution_identity_fence = ExecutionIdentityFence(
            error_type=BtApiStoreError,
        )
        self._sdk_owned_api = api is None
        self._managed_runtime_borrowed_api = None
        self._managed_runtime_stopped = False
        self._sdk_configured = False
        self._last_execution_summary = None
        try:
            from bt_api_py.account_risk_state import AccountRiskState
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py account-risk state is required"
            ) from exc
        self._account_risk_state = AccountRiskState(
            float(sdk_options.get("account_risk_refresh_interval", 0.5)),
            redact_snapshot=self.redact_runtime_value,
        )
        from bt_api_py.funding_refresh import normalize_funding_refresh_options

        funding_max_age, funding_refresh_interval = normalize_funding_refresh_options(sdk_options)
        # The execution owner atomically binds exact API/facade identity,
        # SDK-issued neutral correlations, BT references and one-shot proofs.
        # It owns its indexes; Store never mirrors a second mutable copy.
        self._sdk_execution_bindings = StoreExecutionBindingRegistry()
        self._sdk_correlated_order_adapter = SdkCorrelatedOrderAdapter(
            error_type=BtApiStoreError,
            bindings=self._sdk_execution_bindings,
        )
        from bt_api_py.order_preflight import OrderPreflightCoordinator

        self._execution_preflight = OrderPreflightCoordinator(
            _StoreOrderPreflightContext(self),
            store_error_type=BtApiStoreError,
            missing_dependency_error_type=BtApiMissingDependencyError,
        )
        queue_size = max(int(sdk_options.get("book_queue_size", 256)), 1)
        self._market_channels = self._normalize_market_channels(
            sdk_options.get("market_channels", ("tick",))
        )
        self._configured_orderbook_depth = self._normalize_orderbook_depth(
            sdk_options.get("orderbook_depth")
        )
        # Completed bars are consumed by one Feed per symbol. Keep this queue
        # finite even for legacy seed/push callers; using the existing book
        # capacity by default keeps the new bound explicit and predictable.
        self._live_bar_queue_size = max(int(sdk_options.get("live_bar_queue_size", queue_size)), 1)
        self._market_stream_queue_size = min(queue_size, 65536)
        # The SDK session owns this Store's exact subscription handles; the
        # callbacks retain Store route, lifecycle and Feed delivery projection.
        try:
            from bt_api_py.market_stream_session import MarketStreamSession
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py market-stream session is required"
            ) from exc
        self._market_stream_adapter = MarketStreamSession(
            self._market_stream_queue_size,
            configured_orderbook_depth=self._configured_orderbook_depth,
            error_type=BtApiStoreError,
            missing_dependency_error_type=BtApiMissingDependencyError,
            resolve_route_context=self._resolve_market_stream_route_context,
            assert_route_current=self._assert_market_stream_route_current,
            mark_unavailable=self._mark_market_stream_unavailable,
            observe_queue_depth=self._observe_market_stream_queue_depth,
            on_binding_closed=self._project_market_stream_binding_closed,
            on_close_failure=self._project_market_stream_close_failure,
            sanitize_exception=self.sanitize_exception,
            safe_exception_code=self._safe_exception_code,
        )
        update_queue_size = max(int(sdk_options.get("broker_update_queue_size", 2048)), 1)
        self._sdk_event_drain_lock = threading.Lock()
        self._event_notifier = StoreEventNotifier()
        self._market_delivery_state = StoreMarketDeliveryState(
            delivery_id_limit=max(int(sdk_options.get("strategy_delivery_id_limit", 8192)), 1),
            drop_record_limit=max(int(sdk_options.get("market_drop_record_limit", 256)), 1),
        )
        self._stream_generation = 0
        self._sdk_event_batch_size = max(int(sdk_options.get("event_batch_size", 1024)), 1)
        configured_coalescing = sdk_options.get("coalesce_market_snapshots", ())
        if isinstance(configured_coalescing, str):
            configured_coalescing = (configured_coalescing,)
        self._sdk_coalesce_market_snapshots = tuple(configured_coalescing or ())

        from bt_api_py.queued_command_runtime import normalize_command_queue_options

        (
            self._command_queue_size,
            self._command_reserved_capacity,
            self._command_shutdown_timeout,
        ) = normalize_command_queue_options(sdk_options)
        self._sdk_execution_arming = False
        self._restart_blocked_by_close = False
        self._sdk_close_lock = threading.RLock()
        self._sdk_close_controller = None
        self._command_health: "collections.Counter[str]" = collections.Counter()
        self._shutdown_state = "NOT_STARTED"
        self._cash = _coerce_float(cash)
        self._value = _coerce_float(value, self._cash)
        self._account_cache_ttl = max(_coerce_float(account_cache_ttl), 0.0)
        self._venue_balance_cache: Dict[str, Any] = {}
        from bt_api_py.account_balance_read import SdkAccountReadAdapter

        self._sdk_account_read_adapter = SdkAccountReadAdapter(
            error_type=BtApiStoreError,
            missing_dependency_error_type=BtApiMissingDependencyError,
            sanitize_exception=self.sanitize_exception,
        )
        from bt_api_py.account_position_read import SdkPositionReadAdapter

        self._sdk_position_read_adapter = SdkPositionReadAdapter(
            error_type=BtApiStoreError,
            missing_dependency_error_type=BtApiMissingDependencyError,
        )
        self._sdk_reconciliation_adapter = SdkReconciliationAdapter(
            error_type=BtApiStoreError,
            missing_dependency_error_type=BtApiMissingDependencyError,
        )
        self._positions_cache = list(positions or [])
        self._open_orders_cache: list = []
        seeded_at = time.monotonic() if positions or value is not None or cash else 0.0
        self._last_balance_refresh = seeded_at
        self._last_positions_refresh = seeded_at if positions else 0.0
        self._last_open_orders_refresh = 0.0
        self._connected = False
        self._started = False
        from bt_api_py.bounded_metadata_probe import BoundedMetadataProbeService

        self._metadata_probe_service = BoundedMetadataProbeService(
            worker_name="BtApiStoreReadOnlyMetadataProbe"
        )
        self._data_feeds: list = []
        self._tick_consumers: Dict[str, Any] = {}
        self._latest_ticks: Dict[str, Any] = {}
        self._latest_tick_lock = threading.Lock()
        self._broker = None
        # The Store owns Backtrader's bounded completed-bar handoff. SDK
        # subscriptions and their tick/orderbook queues remain SDK-owned.
        self._live_bar_queue = StoreLiveBarQueue(
            self._live_bar_queue_size,
            on_evicted=self._record_live_bar_queue_eviction,
            on_stale=self._project_live_bar_queue_stale,
            on_enqueued=self._record_live_bar_enqueued,
        )
        self._subscribed_datanames: set = set()
        self._successful_connect_count = 0
        self.contract_metadata = {
            str(key): dict(value or {}) for key, value in (contract_metadata or {}).items()
        }
        self.session_id = (
            f"{self.provider}-"
            f"{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%d%H%M%S')}-"
            f"{uuid.uuid4().hex[:8]}"
        )

        self._execution_coordinator = SdkExecutionCoordinator(
            invoke_command=self._invoke_sdk_command,
            invoke_account_risk=self._invoke_account_risk_command,
            set_accept_openings=lambda enabled: self._command_runtime.set_accept_openings(
                enabled
            ),
            set_last_error=lambda code: self._command_runtime.set_last_error(code),
            clear_account_risk_refresh=self._clear_account_risk_refresh_pending,
            update_correlation_state=self._update_sdk_correlation_state,
            force_market_data_only=lambda reason: self._force_sdk_market_data_only(
                reason, clear_authorization=False
            ),
            exception_code=self._safe_exception_code,
            redact_runtime_value=self.redact_runtime_value,
            observe_execution_error=self._observe_sdk_execution_error,
        )

        self._command_runtime = SdkCommandRuntime(
            queue_capacity=self._command_queue_size,
            reserved_capacity=self._command_reserved_capacity,
            completion_capacity=update_queue_size,
            drop_record_limit=max(int(sdk_options.get("command_drop_record_limit", 256)), 1),
            shutdown_timeout=self._command_shutdown_timeout,
            worker_name=f"BtApiStoreCommand-{self.session_id}",
            priorities=_COMMAND_PRIORITY,
            make_unsent_completion=self._unsent_command_completion,
            on_command_drop=self._execution_coordinator.on_command_drop,
            on_admission_rejected=self._execution_coordinator.on_admission_rejected,
            prepare_update=self.redact_runtime_value,
            on_completion_drop=self._execution_coordinator.on_completion_drop,
            signal_update=self._signal_live_bar_event,
            worker_error=lambda exc: self._safe_exception_code(
                exc, type(exc).__name__
            ),
            on_worker_failure=self._on_sdk_command_worker_failure,
            is_execution_unknown=lambda update: update.get("execution_unknown") is True,
            on_execution_unknown=self._execution_coordinator.on_execution_unknown,
        )

        from bt_api_py.funding_refresh import FundingRefreshController

        self._funding_refresh = FundingRefreshController(
            read_snapshot=self._read_funding_snapshot_from_api,
            cache_key=self._funding_cache_key,
            api_getter=lambda: self._api,
            ensure_api_ready=self._ensure_api_ready,
            can_queue_refresh=lambda: self._started and self._connected,
            session_active=lambda: self._started or self._connected,
            typed_snapshot_required=lambda: self._sdk_mode,
            max_age_seconds=funding_max_age,
            refresh_interval_seconds=funding_refresh_interval,
            shutdown_timeout=self._command_shutdown_timeout,
            error_code=self._safe_exception_code,
            observe_error=self._observe_funding_refresh_error,
            validate_snapshot=self._validate_funding_snapshot_contract,
            on_stale_worker_restart=self._close_stale_api_after_funding_timeout,
            worker_name=f"BtApiStoreFunding-{self.session_id}",
            error_factory=BtApiStoreError,
            cache_source="btapistore_cache",
            inactive_status="store_not_running",
        )
        self._history_cache.seed(historical_bars)
        self._seed_live_bar_queue(live_bars)

        if autostart:
            self.start()

    def _resolve_provider(self, provider: str) -> str:
        provider_label = str(provider or "btapi").strip().lower()
        return provider_label or "btapi"

    @property
    def is_connected(self) -> bool:
        """Return whether the store is connected and ready."""
        return self._connected

    @property
    def sdk_api(self) -> Any:
        """Return no raw API for retired gateway/forwarding routes.

        Store query methods continue to use the managed client internally.
        """
        if _legacy_gateway_entrypoint(self.provider, self.backend) is not None:
            return None
        return self._api

    def _bind_managed_runtime_api(self, api: Any) -> None:
        """Mark the exact injected SDK API as borrowed by a managed runtime."""
        if (
            api is None
            or not self._sdk_mode
            or self._service_read_only
            or self._sdk_owned_api
            or self.sdk_api is not api
        ):
            raise BtApiStoreError("managed_runtime_api_binding_unavailable")
        if self._started or self._connected or self._managed_runtime_stopped:
            raise BtApiStoreError("managed_runtime_api_binding_too_late")
        if self._managed_runtime_borrowed_api is not None:
            raise BtApiStoreError("managed_runtime_api_already_bound")
        if (
            self._sdk_api_close_state is not None
            or self._sdk_close_thread is not None
            or self._restart_blocked_by_close
            or self._last_successfully_closed_api is api
        ):
            raise BtApiStoreError("managed_runtime_api_close_state_unavailable")
        command_state = self._command_runtime.snapshot()
        funding_state = self._funding_refresh.get_health()
        if (
            command_state.worker_alive
            or command_state.has_active_work
            or command_state.restart_blocked_by_worker
            or funding_state.get("worker_alive")
            or funding_state.get("inflight")
            or funding_state.get("queue_depth")
            or funding_state.get("pending")
            or funding_state.get("restart_blocked_by_worker")
            or funding_state.get("restart_preparing")
            or funding_state.get("restart_api_pending")
            or self._metadata_probe_service.is_active()
            or self._market_stream_adapter.has_subscriptions
            or self._event_notifier.has_wakers
            or self._event_notifier.has_sdk_binding
        ):
            raise BtApiStoreError("managed_runtime_store_work_already_active")
        self._managed_runtime_borrowed_api = api
        return None

    def requires_account_risk(self) -> bool:
        """Return whether startup must establish durable account-loss evidence."""
        return bool(self._sdk_mode and self._sdk_require_account_risk)

    def _require_async_sdk_commands(self, *, require_writes: bool = False) -> None:
        """Require the correlated SDK write contract when preparing writes."""
        if not self._sdk_mode:
            return
        if require_writes:
            try:
                self._sdk_correlated_order_adapter.require_facade(self._api)
            except BtApiStoreError as exc:
                raise BtApiStoreError(
                    "SDK trading requires the reservation-bound correlated order contract"
                ) from exc

    # Credential keys that must never appear in repr/str/logs in cleartext.
    def __repr__(self) -> str:
        """Return a repr with credential fields masked.

        The store keeps live-trading credentials inside ``_api_kwargs``/``_config``. A naive repr would
        leak them into logs, tracebacks and debugger output, so this method
        masks any sensitive key before rendering.
        """
        return (
            f"{type(self).__name__}(provider={self.provider!r}, "
            f"backend={self.backend!r}, "
            f"connected={self._connected}, started={self._started}, "
            f"account={self._masked_account_id()!r})"
        )

    __str__ = __repr__

    @classmethod
    def _is_sensitive_key(cls, key: Any) -> bool:
        """Return whether ``key`` conventionally names a credential value."""
        return _runtime_is_sensitive_key(key)

    @classmethod
    def _masked_copy(cls, value: Any, _active: Optional[set[int]] = None) -> Any:
        """Build a cycle-safe diagnostic copy without invoking arbitrary repr methods."""
        return _masked_copy_impl(value, _active)

    @classmethod
    def _credential_values(
        cls,
        value: Any,
        sensitive_parent: bool = False,
        _active: Optional[set[int]] = None,
    ) -> set[str]:
        """Collect configured credential values for exact substring redaction."""
        return _runtime_credential_values(value, sensitive_parent, _active)

    @staticmethod
    def _replace_secret_values(value: Any, secret_values: Iterable[str]) -> Any:
        """Replace configured secret strings inside an already copied value."""
        return _runtime_replace_secrets(value, secret_values)

    def redact_runtime_value(self, value: Any) -> Any:
        """Return a recursive, credential-safe copy for events and order diagnostics."""
        projected = _runtime_redact_value(
            value,
            secret_sources=(self._config, self._api_kwargs, self._sdk_exchanges),
        )
        assembly = self._sdk_direct_api_assembly
        if assembly is not None:
            try:
                return assembly.redact_runtime_value(projected)
            except Exception:
                return {"redaction_error": "DIRECT_API_REDACTION_FAILED"}
        return projected

    def sanitize_exception(self, exc: BaseException) -> BaseException:
        """Redact exception args and attached diagnostic fields in place."""
        projected = _runtime_sanitize_exception(
            exc,
            secret_sources=(self._config, self._api_kwargs, self._sdk_exchanges),
            warning_sink=lambda phase_code: _safe_log(
                "warning",
                "btapistore: runtime exception redaction projection failed (%s)",
                phase_code,
            ),
        )
        assembly = self._sdk_direct_api_assembly
        if assembly is not None:
            try:
                return assembly.sanitize_exception(projected)
            except Exception:
                try:
                    projected.args = ("DIRECT_API_EXCEPTION_REDACTION_FAILED",)
                except Exception:
                    pass
        return projected

    def _sdk_execution_config_snapshot(self) -> Dict[str, Any]:
        """Read SDK-owned execution settings without retaining their owner map."""
        assembly = self._sdk_direct_api_assembly
        if assembly is not None:
            return assembly.execution_config_snapshot()
        pending = getattr(self, "_sdk_execution_config", None)
        return dict(pending) if isinstance(pending, Mapping) else {}

    def _sdk_execution_config_value(self, name: str, default: Any = None) -> Any:
        assembly = self._sdk_direct_api_assembly
        if assembly is not None:
            return assembly.execution_config_value(name, default)
        pending = getattr(self, "_sdk_execution_config", None)
        return pending.get(name, default) if isinstance(pending, Mapping) else default

    def _update_sdk_execution_config(self, updates: Mapping[str, Any]) -> None:
        assembly = self._sdk_direct_api_assembly
        if assembly is not None:
            assembly.update_execution_config(updates)
            return
        self._sdk_execution_config.update(updates)

    @classmethod
    def _mask_sensitive(cls, mapping: Optional[Mapping[Any, Any]]) -> Dict[Any, Any]:
        """Return a recursive copy with sensitive credential values masked.

        Use this whenever store kwargs/config need to be logged or surfaced for
        debugging so that secrets inside nested provider configuration are
        never written out in cleartext. Mappings, lists, and tuples are copied;
        the input object is not modified.
        """
        return cls._masked_copy(mapping or {})

    @staticmethod
    def _safe_exception_code(exc: Exception, default: str) -> str:
        """Return a bounded error identifier without copying vendor text or URLs."""
        value = getattr(exc, "code", None)
        if value in (None, ""):
            return default
        text = str(value).strip()
        if not text or len(text) > 128:
            return default
        if not all(character.isalnum() or character in "._:-" for character in text):
            return default
        return text

    def _force_sdk_market_data_only(
        self,
        reason: str,
        *,
        clear_authorization: bool = False,
    ) -> None:
        """Ask the SDK execution owner to revoke its lease and freeze openings."""
        self._update_sdk_execution_config({"market_data_only": True})
        self._command_runtime.set_accept_openings(False)
        if clear_authorization:
            self._execution_authorization = None
        api = self._api
        disarm = getattr(api, "disarm_execution", None) if api is not None else None
        if callable(disarm):
            try:
                disarm(str(reason or "store_market_data_only"))
            except Exception as exc:
                _safe_log("warning", "btapistore:3882 fallback on Exception")
                self.sanitize_exception(exc)
                self._command_runtime.set_last_error(
                    self._safe_exception_code(exc, "execution_disarm_failed")
                )

    def _prepare_sdk_execution_authorization(self, reason: str) -> Dict[str, Any]:
        """Enter a reusable read-only state without revoking the next arm.

        ``disarm_execution`` is an irreversible fence for the current SDK
        generation.  Authorization preparation therefore uses the distinct
        public SDK transition and refuses to emulate it for older clients.
        """
        self._update_sdk_execution_config({"market_data_only": True})
        self._command_runtime.set_accept_openings(False)
        api = self._ensure_api_ready()
        from bt_api_py.direct_api_assembly import (
            DirectApiAssemblyError,
            prepare_direct_execution_authorization,
        )

        try:
            return prepare_direct_execution_authorization(api, reason)
        except DirectApiAssemblyError as exc:
            if exc.code == "DIRECT_AUTH_PREPARATION_UNAVAILABLE":
                raise BtApiStoreError(
                    "Public SDK reusable execution-authorization preparation is unavailable"
                ) from None
            if exc.code == "DIRECT_AUTH_PREPARATION_FAILED":
                _safe_log("error", "btapistore:3906 exception before re-raise (Exception)")
                self.sanitize_exception(exc.__cause__)
                raise BtApiStoreError("SDK execution-authorization preparation failed") from None
            raise BtApiStoreError("SDK execution-authorization preparation is not reusable") from None

    def _live_bar_event_snapshot(self):
        """Return the current generation for the opt-in live-cohort waiter."""
        return self._event_notifier.snapshot()

    def _wait_live_bar_event(self, generation, timeout):
        """Wait only when no real Store event has arrived since the snapshot."""
        return self._event_notifier.wait(generation, timeout)

    def _register_live_bar_event_waker(self, callback):
        """Register an engine-owned shared condition notifier for one run."""
        return self._event_notifier.register(
            callback,
            api=self._api,
            signal_callback=self._signal_live_bar_event,
        )

    def _unregister_live_bar_event_waker(self, token):
        """Remove one engine notifier without changing queued Store events."""
        self._event_notifier.unregister(token)

    def _signal_live_bar_event(self):
        """Publish a market, broker-update, or Store-stop transition."""
        self._event_notifier.signal()

    def _bind_live_bar_event_notifier(self, api, callback):
        """Bind the engine wake callback to the active public SDK event source."""
        self._event_notifier.bind_api_notifier(api, callback)

    def _unbind_live_bar_event_notifier(self):
        """Unbind SDK callbacks after the final engine waiter leaves."""
        self._event_notifier.unbind_api_notifier()

    def start(self, data=None, broker=None):
        """Start the Store and attach framework objects through its lifecycle bridge."""
        return _start_store(
            self, data, broker, error_type=BtApiStoreError,
            gateway_entrypoint=_legacy_gateway_entrypoint,
            gateway_error_type=LegacyGatewayMigrationRequiredError,
        )

    @staticmethod
    def _bounded_metadata_probe_shutdown_proven(health: Any) -> bool:
        """Return whether a one-shot probe has no live Store work left behind."""

        return bool(
            isinstance(health, Mapping)
            and health.get("shutdown_state") == "PASS"
            and int(health.get("queue_depth", 0) or 0) == 0
            and not health.get("inflight")
            and not health.get("worker_alive")
            and not health.get("close_thread_alive")
            and health.get("broker_update_conservation") is True
            and not health.get("last_error_code")
        )

    def _configure_bounded_metadata_probe_sdk_market_data_only(self) -> None:
        """Require the SDK assembly to apply the probe's zero-write settings."""
        try:
            # Reapply the same identity contract used to create the owned
            # client.  The probe has already forced ``market_data_only`` in
            # that mapping; dropping required environments here would make a
            # second idempotency check fail before public metadata is read.
            assembly = self._sdk_direct_api_assembly
            if assembly is None:
                raise BtApiStoreError("direct SDK assembly is unavailable")
            assembly.reapply_execution_config()
        except Exception as exc:
            _safe_log("error", "btapistore:4070 exception before re-raise (Exception)")
            self.sanitize_exception(exc)
            raise BtApiStoreError(
                "bounded read-only metadata probe could not configure SDK market-data-only mode"
            ) from None

        self._verify_bounded_metadata_probe_sdk_market_data_only()

    def _verify_bounded_metadata_probe_sdk_market_data_only(self) -> None:
        """Require public SDK state after every probe lifecycle transition."""

        api = self._api
        get_execution_summary = getattr(api, "get_execution_summary", None)
        if not callable(get_execution_summary):
            raise BtApiStoreError(
                "bounded read-only metadata probe cannot verify SDK market-data-only mode"
            )
        try:
            summary = get_execution_summary()
        except Exception as exc:
            _safe_log("error", "btapistore:4089 exception before re-raise (Exception)")
            self.sanitize_exception(exc)
            raise BtApiStoreError(
                "bounded read-only metadata probe cannot verify SDK market-data-only mode"
            ) from None
        try:
            from bt_api_py.bounded_metadata_probe import is_market_data_only_execution_summary
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py metadata probe summary contract is required"
            ) from exc
        if not is_market_data_only_execution_summary(summary):
            raise BtApiStoreError(
                "bounded read-only metadata probe cannot verify SDK market-data-only mode"
            )

    def run_bounded_read_only_metadata_probe(
        self,
        *,
        datanames: Sequence[str],
        timeout_seconds: float,
    ) -> Dict[str, Any]:
        """Delegate Store-bound metadata probing to the lifecycle bridge."""
        return _run_store_metadata_probe(
            self, datanames=datanames, timeout_seconds=timeout_seconds,
            error_type=BtApiStoreError, safe_log=_safe_log,
        )

    def _reset_sdk_stream_generation(self) -> None:
        """Discard every market-event identity from the previous SDK generation."""
        self._stream_generation += 1
        self._account_risk_state.reset_generation()
        self._sdk_execution_identity_fence.clear_session()
        self._market_delivery_state.reset_generation()

    def _prepare_sdk_start(self) -> None:
        """Check Store-local restart fences through its lifecycle bridge."""
        return _prepare_store_sdk_start(self, error_type=BtApiStoreError)

    def _prepare_funding_refresh_start(self) -> None:
        """Delegate stale-reader restart fencing to the funding controller."""
        self._funding_refresh.prepare_start()

    def _begin_funding_refresh_generation(self) -> None:
        """Start a cache generation owned by the funding controller."""
        self._funding_refresh.begin_generation()
    def freeze_openings(self, reason: str = "shutdown") -> None:
        """Reject future opening placements while preserving risk-reducing capacity."""
        self._command_runtime.set_accept_openings(False)
        self.emit_runtime_event(
            "order_openings_frozen",
            status="frozen",
            details={"reason": str(reason)},
        )

    def latch_execution_evidence_loss(self, reason: str) -> Dict[str, Any]:
        """Freeze exposure after Broker detects a ledger-identity contradiction."""
        epoch = self._latch_risk_state_unknown(reason)
        rejected = self._reject_pending_openings_after_unknown(reason, reserve_publications=True)
        try:
            for completion in rejected:
                self._append_sdk_update(completion)
        finally:
            if rejected:
                self._command_runtime.release_publications(len(rejected))
        self.emit_runtime_event(
            "execution_evidence_lost",
            level="ERROR",
            status="frozen",
            error_code=str(reason),
            details={
                "risk_incident_epoch": epoch,
                "rejected_pending_openings": len(rejected),
            },
        )
        return {
            "risk_incident_epoch": epoch,
            "rejected_pending_openings": len(rejected),
            "accepting_openings": False,
        }

    def enable_openings_after_account_risk(self) -> Dict[str, Any]:
        """Unlock SDK openings only after a fresh identity-bound durable baseline."""
        if not self.requires_account_risk:
            self._enable_openings_after_safety_gate()
            return {"enabled": True, "account_risk_required": False}
        snapshot = self._read_account_risk_snapshot(self._ensure_api_ready())
        if (
            snapshot.get("evidence_complete") is not True
            or snapshot.get("durable") is not True
            or snapshot.get("trading_blocked") is not False
            or not snapshot.get("identity_binding_sha256")
        ):
            self._command_runtime.set_accept_openings(False)
            raise BtApiStoreError("account_risk_baseline_not_proven")
        self._enable_openings_after_safety_gate()
        self.emit_runtime_event(
            "order_openings_enabled",
            status="enabled",
            details={"reason": "account_risk_baseline_proven"},
        )
        return {"enabled": True, "account_risk_required": True}

    def _enable_openings_after_safety_gate(self) -> None:
        """Enable openings only from one idle, conserved and reconciled state."""
        def safety_check() -> bool:
            return bool(
                not self._execution_coordinator.risk_state_unknown
                and not self._sdk_execution_arming
            )

        if not self._command_runtime.enable_openings_if(safety_check):
            raise BtApiStoreError("risk_state_reconcile_required")

    def _signal_funding_refresh_stop(self) -> None:
        """Fence funding publications and discard queued reads."""
        self._funding_refresh.signal_stop()

    def _stop_funding_refresh_worker(self, timeout: float) -> bool:
        """Wait boundedly for the controller's direct and queued reads."""
        return self._funding_refresh.stop_worker(timeout)

    def _start_command_worker(self) -> None:
        """Start the one SDK command runtime worker generation."""
        try:
            self._command_runtime.start(self._execute_sdk_command)
        except Exception as exc:
            self.sanitize_exception(exc)
            raise BtApiStoreError("SDK command runtime could not start") from None

    def _update_sdk_correlation_state(
        self, command: Mapping[str, Any], state: str
    ) -> None:
        """Update only the exact Store binding for a command correlation."""
        correlation = command.get("correlation")
        if correlation is None:
            return
        self._sdk_execution_bindings.set_state_by_correlation(correlation, state)

    def _observe_sdk_execution_error(self, exc: BaseException) -> None:
        _safe_log("warning", "btapistore:6063 fallback on Exception")
        self.sanitize_exception(exc)

    def _on_sdk_command_worker_failure(self, exc: BaseException, code: str) -> None:
        _safe_log("warning", "btapistore:sdk_command_worker_failed")
        self.sanitize_exception(exc)

    @staticmethod
    def _unsent_command_completion(command: Mapping[str, Any], reason: str) -> Dict[str, Any]:
        """Project a local no-send completion using the Store-owned clock."""
        return _project_unsent_completion(
            command,
            reason,
            completed_monotonic_ns=time.monotonic_ns(),
        )

    def _reject_pending_openings_after_unknown(
        self, reason: str, *, reserve_publications: bool = False
    ) -> List[Dict[str, Any]]:
        """Freeze exposure and project queued openings as local completions."""
        self.freeze_openings(reason)
        removed = self._command_runtime.reject_matching(
            lambda command: command.get("priority") == "open",
            "openings_frozen_after_unknown",
            reserve_publications=reserve_publications,
        )
        return [
            self._unsent_command_completion(command, "openings_frozen_after_unknown")
            for command in removed
        ]

    def _latch_risk_state_unknown(self, reason: str) -> int:
        """Delegate exposure fencing to the execution service owner."""
        return self._execution_coordinator.latch_unknown(reason)

    def _current_risk_incident_epoch(self) -> int:
        return self._execution_coordinator.risk_incident_epoch()

    def wait_for_commands(
        self, timeout: Optional[float] = None, *, stop_on_timeout: bool = False
    ) -> bool:
        """Wait for the single-owner runtime's queue and publication drain."""
        return self._command_runtime.wait_for_commands(
            timeout, stop_on_timeout=stop_on_timeout
        )

    def _stop_command_worker(self, timeout: float, *, discard_pending: bool = False) -> bool:
        return self._command_runtime.stop(timeout, discard_pending=discard_pending)

    @property
    def _sdk_close_thread(self):
        closer = self._sdk_close_controller
        return None if closer is None else closer.thread

    @property
    def _sdk_close_generation(self):
        closer = self._sdk_close_controller
        return 0 if closer is None else closer.generation

    @property
    def _sdk_api_close_state(self):
        closer = self._sdk_close_controller
        return None if closer is None else closer.state

    @property
    def _last_successfully_closed_api(self):
        closer = self._sdk_close_controller
        return None if closer is None else closer.last_successful_api

    def _get_sdk_close_controller(self):
        """Construct the SDK-owned closer once without importing it for other Store paths."""
        with self._sdk_close_lock:
            closer = self._sdk_close_controller
            if closer is not None:
                return closer
            try:
                from bt_api_py.bounded_api_close import BoundedApiCloser
            except ImportError as exc:
                raise BtApiMissingDependencyError(
                    "bt_api_py bounded API close lifecycle is required"
                ) from exc
            closer = BoundedApiCloser(
                error_type=BtApiStoreError,
                on_pending=self._mark_sdk_close_pending,
                on_failure=self._record_sdk_close_failure,
                on_timeout=self._record_sdk_close_timeout,
                on_success=self._record_sdk_close_success,
                on_worker_error=self._log_sdk_close_worker_error,
                thread_name="BtApiStoreClose",
            )
            self._sdk_close_controller = closer
            return closer

    def _mark_sdk_close_pending(self):
        self._restart_blocked_by_close = True

    def _record_sdk_close_failure(self, error, sanitize, type_only):
        if sanitize:
            self.sanitize_exception(error)
        self._command_health["close_failures"] += 1
        code = type(error).__name__ if type_only else self._safe_exception_code(
            error, type(error).__name__
        )
        self._command_runtime.set_last_error(code)
        self._shutdown_state = "FAIL"
        self._restart_blocked_by_close = True

    def _record_sdk_close_timeout(self):
        self._command_health["close_timeouts"] += 1
        self._shutdown_state = "INCOMPLETE"
        self._restart_blocked_by_close = True

    def _record_sdk_close_success(self):
        self._restart_blocked_by_close = False

    @staticmethod
    def _log_sdk_close_worker_error():
        _safe_log("warning", "btapistore:bounded_sdk_close_failed")

    def _bounded_sdk_close(self, api: Any, timeout: float) -> Tuple[bool, Optional[BaseException]]:
        """Bind Store ownership and health to the SDK-owned close lifecycle."""
        if self._managed_runtime_borrowed_api is not None:
            self._shutdown_state = "INCOMPLETE"
            return False, BtApiStoreError("managed runtime owns SDK API close")

        def select_close():
            assembly = self._sdk_direct_api_assembly
            if assembly is not None and assembly.api is api and assembly.owns_api:
                return assembly.close_api
            return getattr(api, "close", None)

        return self._get_sdk_close_controller().close(
            api,
            timeout,
            select_close=select_close,
            generation=lambda: self._command_runtime.generation,
        )

    def stop(self, timeout: Optional[float] = None):
        """Coordinate shutdown through the Backtrader lifecycle bridge."""
        return _stop_store(self, timeout, safe_log=_safe_log)

    def _stop_synchronous_sdk(self, timeout: Optional[float] = None):
        """Coordinate synchronous SDK shutdown through the lifecycle bridge."""
        return _stop_synchronous_store_sdk(self, timeout)

    def getbroker(self, *args, **kwargs):
        """Return a BtApiBroker bound to this store."""
        broker_cls = kwargs.pop("broker_cls", self.BrokerCls)
        if broker_cls is None:
            from ..brokers.btapibroker import BtApiBroker

            broker_cls = BtApiBroker

        broker = broker_cls(store=self, provider=self.provider, *args, **kwargs)
        self._broker = broker
        return broker

    def getdata(self, *args, **kwargs):
        """Return a BtApiFeed bound to this store."""
        data_cls = kwargs.pop("data_cls", self.DataCls)
        if data_cls is None:
            from ..feeds.btapifeed import BtApiFeed

            data_cls = BtApiFeed

        kwargs.setdefault("store", self)
        kwargs.setdefault("provider", self.provider)
        data = data_cls(*args, **kwargs)
        data._store = self
        return data

    def set_source_stop_callback(self, callback) -> bool:
        """Register an optional fixture/source exhaustion callback.

        Live ``BtApi`` transports normally stop through broker/store lifecycle
        events. Deterministic replay clients may expose this small hook so a
        runner never reaches through the Store's private client attribute.
        """
        setter = getattr(self._api, "set_stop_callback", None)
        if not callable(setter):
            return False
        setter(callback)
        return True

    def get_cash(self) -> float:
        """Return cached available cash."""
        self.get_balance()
        return self._cash

    def get_value(self) -> float:
        """Return cached account value."""
        self.get_balance()
        return self._value

    def supports_position_mode(self, mode: str) -> bool:
        """Return whether this Store can represent the requested local position mode.

        This is a Backtrader ledger capability check.  The remote account's
        actual mode is queried separately through :meth:`get_account_config`;
        callers must validate that result before submitting live or demo orders.
        """
        mode = str(mode or "net").strip().lower()
        if self._service_read_only:
            supports = getattr(self._api, "supports_position_mode", None)
            return bool(callable(supports) and supports(mode))
        if mode != "dual_side":
            return True

        # Local SDK-backed projection can represent explicit long/short legs.
        # The routed account's configured mode remains a separate SDK fact.
        return self._sdk_mode

    def _clear_sdk_balance_snapshot(self) -> None:
        """Revoke query-port and snapshot identities for the old SDK session."""
        self._sdk_account_read_adapter.clear()

    def _sdk_balance_snapshot_for_route(self, api, route, *, force):
        """Read one full-scope balance snapshot from one exact retained port."""
        return self._sdk_account_read_adapter.snapshot_for_route(
            api,
            route,
            force=force,
            cache_ttl=self._account_cache_ttl,
        )

    def _project_sdk_venue_balance_snapshot(self, route, snapshot):
        """Project one verified neutral snapshot without combining accounts."""
        return _project_venue_balance_snapshot(
            route,
            snapshot,
            error_type=BtApiStoreError,
            missing_dependency_error_type=BtApiMissingDependencyError,
        )

    def get_balance(self, force: bool = False, raise_errors: bool = False):
        """Refresh cached provider-available cash and reported account equity.

        The unified SDK path uses ``AccountValuation.available_cash`` for the
        Backtrader cash value and ``AccountValuation.equity`` for value. The
        cash amount does not imply settlement, transferability, or withdrawal
        availability.
        """
        if self._service_read_only:
            api = self._ensure_api_ready()
            balance = api.get_balance()
            if type(balance) is not dict or set(balance) != {"cash", "value"}:
                raise BtApiStoreError("read-only service valuation contract is invalid")
            cash = balance["cash"]
            value = balance["value"]
            if (
                type(cash) is not float
                or type(value) is not float
                or not math.isfinite(cash)
                or not math.isfinite(value)
            ):
                raise BtApiStoreError("read-only service valuation is incomplete")
            self._cash = cash
            self._value = value
            self._last_balance_refresh = time.monotonic()
            return {"cash": self._cash, "value": self._value}
        if self._sdk_mode:
            api = self._ensure_api_ready()
            try:
                live_names = self._facade_exchange_names(api)
                configured_names = list(self._sdk_exchanges)
                route = self._sdk_account_read_adapter.single_configured_route(
                    live_names, configured_names
                )
                snapshot = self._sdk_balance_snapshot_for_route(
                    api, route, force=force
                )
            except BtApiStoreError:
                raise
            except Exception as exc:
                self.sanitize_exception(exc)
                error = BtApiStoreError("SDK account balance snapshot is unavailable")
                error.code = "account_balance_snapshot_unavailable"
                raise error from None

            # Keep this guard before the lazy SDK type import to preserve the
            # established failure order for ambiguous account snapshots. The
            # standalone projector repeats the same checks defensively.
            _require_single_balance_currency(snapshot, error_type=BtApiStoreError)
            try:
                from bt_api_py.account_balance_contracts import AccountValuation
            except ImportError as exc:
                raise BtApiMissingDependencyError(
                    "bt_api_py.account_balance_contracts.AccountValuation is required"
                ) from exc
            projected = _project_account_balance_snapshot(
                snapshot,
                account_valuation_type=AccountValuation,
                error_type=BtApiStoreError,
            )
            self._cash = projected["cash"]
            self._value = projected["value"]
            self._last_balance_refresh = time.monotonic()
            return {"cash": self._cash, "value": self._value}
        error = BtApiStoreError(
            "cash and value require the unified typed account valuation facade"
        )
        error.code = "legacy_account_valuation_unavailable"
        raise error

    def getcash(self) -> float:
        """Get current cash balance."""
        self.get_balance()
        return self._cash

    def getvalue(self, datas=None) -> float:
        """Get total portfolio value."""
        self.get_balance()
        return self._value

    def get_positions(
        self,
        force: bool = False,
        raise_errors: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return positions from the selected read path without fabricating freshness."""
        if self._service_read_only:
            api = self._ensure_api_ready()
            positions = api.get_positions()
            if type(positions) is not list or any(
                not isinstance(row, Mapping) for row in positions
            ):
                raise BtApiStoreError("read-only service positions are incomplete")
            self._positions_cache = [dict(row) for row in positions]
            self._last_positions_refresh = time.monotonic()
            return deepcopy(self._positions_cache)
        if self._sdk_mode:
            # SDK position reads are always obtained from and revalidated
            # against a fresh, complete account snapshot. The legacy Store
            # cache is not evidence that a new account snapshot was read.
            return self._get_sdk_account_positions()
        raise BtApiStoreError("position reads require the unified SDK or read-only service facade")

    def _get_sdk_account_positions(self) -> List[Dict[str, Any]]:
        """Read and project independent current snapshots for configured routes."""
        return _project_store_account_positions(
            self,
            error_type=BtApiStoreError,
            missing_dependency_error_type=BtApiMissingDependencyError,
            contract_metadata_aliases=_contract_metadata_aliases,
        )

    def getpositions(self) -> List[Dict[str, Any]]:
        """Alias for get_positions()."""
        return self.get_positions()

    def register(self, feed):
        """Register a feed instance with this store."""
        if feed not in self._data_feeds:
            self._data_feeds.append(feed)

    @property
    def uses_sdk_market_streams(self) -> bool:
        """Whether this Store routes live tick/book channels through BtApi."""
        return self._sdk_mode and not self._service_read_only

    def claim_tick_consumer(self, dataname: str, feed: Any) -> None:
        """Reserve a symbol's destructive tick cursor for one authoritative Feed."""
        key = str(dataname)
        owner = self._tick_consumers.get(key)
        if owner is not None and owner is not feed:
            raise BtApiStoreError(
                f"Live ticks for {key!r} already have an authoritative Feed consumer"
            )
        self._tick_consumers[key] = feed

    def release_tick_consumer(self, dataname: str, feed: Any) -> None:
        """Release a tick cursor only when it is still owned by *feed*."""
        key = str(dataname)
        if self._tick_consumers.get(key) is feed:
            self._tick_consumers.pop(key, None)

    @staticmethod
    def _normalize_market_channels(channels: Any) -> Tuple[str, ...]:
        """Validate explicit provider-neutral live market channel selection."""
        from bt_api_py.market_stream_contracts import normalize_market_channels

        return normalize_market_channels(channels)

    @staticmethod
    def _normalize_orderbook_depth(depth: Any) -> Optional[int]:
        """Accept only an explicitly configured provider-neutral depth."""
        from bt_api_py.market_stream_contracts import normalize_orderbook_depth

        return normalize_orderbook_depth(depth)

    def _mark_market_stream_unavailable(self, symbol: str, channel: str, code: str) -> None:
        self._market_delivery_state.mark_unavailable(symbol, channel, code)

    def _resolve_market_stream_route_context(self, api, symbol: str):
        """Project a BT data name to the SDK's selected route and instrument."""
        route = self._resolve_sdk_route_name(api, self._sdk_exchange(symbol))
        instrument = self.get_market_instrument_key(symbol)
        return route, instrument

    def _assert_market_stream_route_current(self, api) -> None:
        self._assert_write_route_identity(expected_api=api, require_live_route=True)

    def _observe_market_stream_queue_depth(
        self,
        symbol: str,
        channel: str,
        depth: int,
        clear_unavailable: bool,
    ) -> None:
        self._market_delivery_state.observe_queue_depth(
            symbol, channel, depth, clear_unavailable
        )

    def _project_market_stream_binding_closed(self, symbol: str, channel: str) -> None:
        self._market_delivery_state.project_binding_closed(symbol, channel)

    def _project_market_stream_close_failure(
        self, symbol: str, channel: str, code: str
    ) -> None:
        self._command_health["market_stream_unsubscribe_failures"] += 1
        if channel == "tick":
            self._mark_market_stream_unavailable(
                symbol, channel, "sdk_market_stream_close_incomplete"
            )
        else:
            self._market_delivery_state.update_state(
                symbol,
                orderbook_stale=True,
                orderbook_stale_reason="sdk_market_stream_close_incomplete",
                orderbook_continuity_status="disconnected",
            )
        _safe_log("warning", "btapistore: market stream unsubscribe failed (%s)", code)

    def _start_sdk_market_stream_subscription(
        self,
        dataname: str,
        channel: str = "tick",
        depth: Optional[int] = None,
        api=None,
    ) -> bool:
        """Bind one exact SDK-owned market stream subscription."""
        if not self._sdk_mode or self._service_read_only:
            raise BtApiStoreError("typed market streams require the unified SDK Store")
        if channel not in {"tick", "orderbook"}:
            raise BtApiStoreError("unsupported SDK market stream channel")
        depth = self._normalize_orderbook_depth(depth)
        if channel == "tick" and depth is not None:
            raise BtApiStoreError("tick market streams cannot request depth")
        if channel == "orderbook" and depth is None:
            self._mark_market_stream_unavailable(
                str(dataname), channel, "MARKET_STREAM_DEPTH_UNCONFIGURED"
            )
            return False
        api = self._ensure_api_ready() if api is None else api
        return self._market_stream_adapter.start_subscription(
            dataname,
            channel=channel,
            depth=depth,
            api=api,
        )

    def market_stream_identity(
        self, dataname: str, channel: str = "tick", depth: Optional[int] = None
    ):
        """Return identity facts from one exact SDK stream subscription."""
        if type(dataname) is not str or not dataname or dataname != dataname.strip():
            raise ValueError("dataname must be non-empty trimmed text")
        if channel not in {"tick", "orderbook"}:
            raise ValueError("channel must be tick or orderbook")
        depth = self._normalize_orderbook_depth(depth)
        if channel == "tick" and depth is not None:
            raise ValueError("tick market streams cannot request depth")
        api = self._api
        if self._market_stream_adapter.has_binding(dataname, channel, depth) and (
            not self._sdk_mode or api is None
        ):
            raise BtApiStoreError("market stream identity is not bound to the active Store API")
        return self._market_stream_adapter.identity(
            dataname,
            channel=channel,
            depth=depth,
            api=api,
        )

    def market_session_resolver(self, dataname: str):
        """Select an SDK-owned neutral session resolver for one exact feed key."""
        try:
            from bt_api_py.facade_protocol import (
                MarketSessionResolver,
                MarketSessionResolverSelector,
            )
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py market-session resolver contracts are required"
            ) from exc
        if type(dataname) is not str or not dataname or dataname != dataname.strip():
            raise ValueError("dataname must be non-empty trimmed text")
        if not self._sdk_mode or self._service_read_only:
            raise BtApiStoreError("market-session resolution requires the unified SDK Store")

        api = self._ensure_api_ready()
        route = self._resolve_sdk_route_name(api, self._sdk_exchange(dataname))
        instrument = self.get_market_instrument_key(dataname)
        self._assert_write_route_identity(expected_api=api, require_live_route=True)
        if not isinstance(api, MarketSessionResolverSelector):
            raise BtApiStoreError("SDK facade lacks the optional market-session resolver selector")
        resolver = api.market_session_resolver(route, instrument)
        if not isinstance(resolver, MarketSessionResolver):
            raise BtApiStoreError("SDK market-session selector returned an invalid resolver")
        return resolver

    def _record_market_stream_queue_state(
        self, dataname: str, channel: str, result: Any, previous: int
    ) -> bool:
        """Project one SDK queue's depth and loss into channel health."""
        return self._market_delivery_state.record_queue_state(
            dataname,
            channel,
            result,
            previous,
            stream_generation=self._stream_generation,
            error_type=BtApiStoreError,
        )

    def _poll_sdk_market_stream(
        self,
        dataname: str,
        api=None,
        *,
        channel: str = "tick",
        depth: Optional[int] = None,
        pump_only: bool = False,
    ):
        """Poll or non-consumingly pump one SDK-owned channel queue."""
        symbol = str(dataname)
        api = self._api if api is None else api
        result, route, is_active, cleanup_unverified, previous_dropped = (
            self._market_stream_adapter.poll_result(
                symbol,
                api,
                channel=channel,
                depth=depth,
                pump_only=pump_only,
            )
        )
        return self._market_delivery_state.project_polled_event(
            symbol, channel, result, route, is_active, cleanup_unverified,
            previous_dropped, pump_only=pump_only,
            record_queue_state=self._record_market_stream_queue_state,
            record_drop=self._record_market_drop,
        )

    def _sdk_market_stream_queue_depth(
        self, dataname: str, channel: str = "tick", depth: Optional[int] = None
    ) -> int:
        """Observe, but never mirror, one SDK-owned channel queue depth."""
        return self._market_stream_adapter.queue_depth(dataname, channel, depth)

    def _close_sdk_market_stream_subscriptions(self) -> bool:
        """Unsubscribe Store tokens on the SDK owner thread before API close."""
        return self._market_stream_adapter.close_all()

    def subscribe(
        self,
        dataname: str,
        *,
        channels: Optional[Sequence[str]] = None,
        orderbook_depth: Optional[int] = None,
    ):
        """Subscribe selected market channels without inferring book depth."""
        api = self._ensure_api_ready()
        dataname = str(dataname)

        if self._service_read_only:
            if dataname in self._subscribed_datanames:
                return
            api.subscribe(dataname)
            self._subscribed_datanames.add(dataname)
            self.emit_runtime_event(
                "market_data_subscribe_request",
                details={"data_name": dataname},
                status="submitted",
            )
            return

        selected_channels = self._normalize_market_channels(
            self._market_channels if channels is None else channels
        )
        selected_depth = self._normalize_orderbook_depth(
            self._configured_orderbook_depth
            if orderbook_depth is None
            else orderbook_depth
        )
        channel_status = {}
        for channel in selected_channels:
            if channel == "orderbook" and selected_depth is None:
                self._mark_market_stream_unavailable(
                    dataname, channel, "MARKET_STREAM_DEPTH_UNCONFIGURED"
                )
                channel_status[channel] = "unavailable"
                continue
            subscribed = self._start_sdk_market_stream_subscription(
                dataname,
                channel=channel,
                depth=selected_depth if channel == "orderbook" else None,
                api=api,
            )
            channel_status[channel] = "subscribed" if subscribed else "unavailable"
        self._subscribed_datanames.add(dataname)
        self.emit_runtime_event(
            "market_data_subscribe_request",
            details={
                "data_name": dataname,
                "channels": selected_channels,
                "channel_status": channel_status,
                "orderbook_depth": (
                    selected_depth if "orderbook" in selected_channels else None
                ),
            },
            status="submitted",
        )

    def fetch_history(
        self,
        dataname: str,
        timeframe=None,
        compression: int = 1,
        since=None,
        limit: Optional[int] = None,
    ) -> List[Any]:
        """Fetch historical bars through the configured route and local BT cache."""
        if self._service_read_only:
            return self._fetch_service_history(dataname, timeframe, compression, since, limit)

        if compression is None:
            history_compression = 1
        elif type(compression) is int and compression > 0:
            history_compression = compression
        else:
            raise BtApiStoreError("history compression must be a positive integer")
        return self._history_cache.fetch(
            dataname, timeframe, history_compression, since, limit,
            lambda default_request: self._fetch_sdk_history(
                dataname, timeframe, history_compression, since, limit, default_request,
            ),
        )

    def _fetch_service_history(self, dataname, timeframe, compression, since, limit):
        api = self._ensure_api_ready()
        bars = api.fetch_bars(
            dataname, timeframe=timeframe, compression=compression,
            since=since, limit=limit,
        )
        if type(bars) is not list:
            raise BtApiStoreError("read-only service history is incomplete")
        return [self._copy_or_normalize_bar(bar) for bar in bars]

    def _fetch_sdk_history(self, dataname, timeframe, compression, since, limit, default_request):
        cache = self._history_cache
        api = self._ensure_api_ready()
        try:
            from bt_api_py.facade_protocol import is_market_history_facade
            from bt_api_py.market_history_composition import (
                MarketHistoryCompositionError,
                market_history_collection_invalid,
            )
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py market-history facade contracts are required"
            ) from exc

        if not is_market_history_facade(api):
            fallback, bars = cache.default_fallback(dataname, default_request)
            if fallback:
                return bars, False
            raise BtApiStoreError("SDK facade does not expose typed market history")

        neutral_timeframe = history_timeframe(timeframe, compression)
        exchange_name = self._sdk_exchange(dataname)
        instrument = self.get_market_instrument_key(dataname)
        try:
            bars = api.fetch_market_history(
                exchange_name, instrument, neutral_timeframe, since=since,
                limit=limit, preserve_raw_bars=cache.preserve_raw_bars,
            )
        except MarketHistoryCompositionError as exc:
            if exc.code == "MARKET_HISTORY_PROVIDER_CAPABILITY_UNAVAILABLE":
                fallback, bars = cache.default_fallback(dataname, default_request)
                if fallback:
                    return bars, False
            raise

        if market_history_collection_invalid(bars):
            raise BtApiStoreError("SDK market history returned an invalid typed bar collection")
        if cache.preserve_raw_bars:
            # Typed MarketBar rows do not retain provider-specific fields.
            raise BtApiStoreError("SDK market history does not preserve raw source fields")

        return bars, True

    def fetch_open_orders(
        self,
        force: bool = False,
        raise_errors: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch the provider's currently open orders, if supported."""
        if self._service_read_only:
            api = self._ensure_api_ready()
            orders = api.fetch_open_orders()
            if type(orders) is not list or any(not isinstance(order, Mapping) for order in orders):
                raise BtApiStoreError("read-only service open-order snapshot is incomplete")
            self._open_orders_cache = [dict(order) for order in orders]
            self._last_open_orders_refresh = time.monotonic()
            return deepcopy(self._open_orders_cache)
        if self._sdk_mode:
            snapshot = self.reconciliation_snapshot()
            if snapshot.get("complete") is not True or snapshot.get("safe_to_resume") is not True:
                raise BtApiStoreError("SDK open-order snapshot is incomplete or unverified")
            orders = snapshot.get("open_orders")
            if type(orders) is not list or any(not isinstance(item, Mapping) for item in orders):
                raise BtApiStoreError("SDK open-order projection is incomplete")
            self._open_orders_cache = [dict(order) for order in orders]
            self._last_open_orders_refresh = time.monotonic()
            return deepcopy(self._open_orders_cache)
        raise BtApiStoreError("open-order reads require the unified SDK or read-only service facade")

    def get_open_orders(self) -> List[Dict[str, Any]]:
        """Alias for fetch_open_orders()."""
        return self.fetch_open_orders()

    def getopenorders(self) -> List[Dict[str, Any]]:
        """Compatibility alias for fetch_open_orders()."""
        return self.fetch_open_orders()

    def poll_live(self, dataname: str) -> Optional[Any]:
        """Poll a live bar, preserving source fields when explicitly requested."""
        if self._service_read_only:
            api = self._ensure_api_ready()
            bar = api.poll_bar(dataname)
            return None if bar is None else self._copy_or_normalize_bar(bar)
        has_queued_bar, bar = self._live_bar_queue.pop(dataname)
        if has_queued_bar:
            return cast(Optional[Dict[str, Any]], bar)

        self._ensure_api_ready()
        self._drain_sdk_events()
        _has_queued_bar, bar = self._live_bar_queue.pop(dataname)

        if bar is None:
            return None

        return self._copy_or_normalize_bar(bar)

    def has_pending_live_bar(self, dataname: str) -> bool:
        """Return whether a Backtrader completed-bar handoff is queued."""
        return self._live_bar_queue.snapshot(dataname)[0] > 0

    def poll_tick(self, dataname: str):
        """Poll a single live tick from the API."""
        if not self._connected:
            return None

        api = self._ensure_api_ready()
        if self._sdk_mode:
            tick = self._poll_sdk_market_stream(dataname, api)
            if tick is not None:
                self._mark_feed_inflight(tick)
        elif hasattr(api, "poll_tick"):
            tick = api.poll_tick(dataname)
        elif hasattr(api, "get_next_tick"):
            tick = api.get_next_tick(dataname)
        else:
            tick = None
        if tick is not None:
            with self._latest_tick_lock:
                self._latest_ticks[dataname] = _snapshot_tick(tick)
        return tick

    def get_latest_tick_snapshot(self, dataname: str):
        """Return the last consumed tick without issuing market-data I/O."""
        from bt_api_py.instrument_metadata_aliases import find_alias_match

        aliases = _contract_metadata_aliases(dataname)
        with self._latest_tick_lock:
            found, tick = find_alias_match(
                self._latest_ticks, aliases,
                alias_fn=_contract_metadata_aliases, require_truthy=False,
            )
            return _snapshot_tick(tick) if found else None

    def poll_orderbook(self, dataname: str, *, depth: Optional[int] = None):
        """Poll a single live orderbook snapshot from the API."""
        if not self._connected:
            return None

        api = self._ensure_api_ready()
        if self._sdk_mode:
            book = self._poll_sdk_market_stream(
                dataname,
                api,
                channel="orderbook",
                depth=depth,
            )
            if book is not None:
                self._mark_feed_inflight(book)
            return book
        if hasattr(api, "poll_orderbook"):
            return api.poll_orderbook(dataname)
        if hasattr(api, "get_next_orderbook"):
            return api.get_next_orderbook(dataname)
        return None

    def has_pending_tick(self, dataname: str) -> bool:
        """Return whether the API has queued live ticks for a symbol."""
        if not self._connected:
            return False

        api = self._ensure_api_ready()
        if self._sdk_mode:
            self._poll_sdk_market_stream(dataname, api, pump_only=True)
            if not self._market_stream_adapter.has_binding(str(dataname), "tick"):
                return False
            depth = self._sdk_market_stream_queue_depth(dataname, "tick")
            self._market_delivery_state.set_state(str(dataname), "tick_queue_depth", depth)
            return depth > 0
        if hasattr(api, "has_pending_tick"):
            return bool(api.has_pending_tick(dataname))

        live_ticks = getattr(api, "live_ticks", None)
        if live_ticks is not None:
            return bool(live_ticks.get(dataname))

        return False

    def is_source_exhausted(self, dataname: str) -> bool:
        """Return explicit EOF for a finite fixture/replay source.

        Absence of the capability always means "still live".  Network clients
        therefore retain their existing idle behavior, while a deterministic
        source can let a feed end naturally after all buffered bars have been
        delivered.
        """

        if not self._connected:
            return False
        api = self._ensure_api_ready()
        method = getattr(api, "is_source_exhausted", None)
        return bool(method(dataname)) if callable(method) else False

    def get_source_event_time_watermark(self, dataname: str):
        """Return a finite source's final event-time watermark, if declared."""

        if not self._connected:
            return None
        api = self._ensure_api_ready()
        method = getattr(api, "get_source_event_time_watermark", None)
        return method(dataname) if callable(method) else None

    def has_pending_orderbook(self, dataname: str) -> bool:
        """Return whether the API has queued live orderbooks for a symbol."""
        if not self._connected:
            return False

        api = self._ensure_api_ready()
        if self._sdk_mode:
            self._poll_sdk_market_stream(
                dataname, api, channel="orderbook", pump_only=True
            )
            if not self._market_stream_adapter.has_binding(dataname, "orderbook"):
                return False
            return self._sdk_market_stream_queue_depth(dataname, "orderbook") > 0
        if hasattr(api, "has_pending_orderbook"):
            return bool(api.has_pending_orderbook(dataname))

        live_orderbooks = getattr(api, "live_orderbooks", None)
        if live_orderbooks is not None:
            return bool(live_orderbooks.get(dataname))

        return False

    def supports_live_ticks(self, dataname: str) -> bool:
        """Return whether a symbol is configured for live tick streaming."""
        if not self._connected:
            return False

        api = self._ensure_api_ready()
        if self._sdk_mode:
            return self._market_stream_adapter.supports_channel(
                str(dataname), api, channel="tick", depth=None
            )
        if hasattr(api, "supports_live_ticks"):
            return bool(api.supports_live_ticks(dataname))

        live_ticks = getattr(api, "live_ticks", None)
        if live_ticks is not None:
            return dataname in live_ticks

        return False

    def supports_live_orderbook(self, dataname: str) -> bool:
        """Return whether a symbol is configured for live orderbook streaming."""
        if not self._connected:
            return False

        api = self._ensure_api_ready()
        if self._sdk_mode:
            return self._market_stream_adapter.supports_channel(
                str(dataname), api, channel="orderbook", depth=None
            )
        if hasattr(api, "supports_live_orderbook"):
            return bool(api.supports_live_orderbook(dataname))

        live_orderbooks = getattr(api, "live_orderbooks", None)
        if live_orderbooks is not None:
            return dataname in live_orderbooks

        return False

    def accept_market_stream_resync(
        self,
        dataname: str,
        channel: str = "tick",
        depth: Optional[int] = None,
        *,
        acknowledge_data_loss: bool,
    ):
        """Accept one SDK recovery only after an explicit data-loss decision.

        The exact SDK poll result is returned because the SDK may deliver a
        recovery snapshot as part of this call. This method never acknowledges
        recovery implicitly and never converts its event into a bar.
        """
        if type(acknowledge_data_loss) is not bool or acknowledge_data_loss is not True:
            raise BtApiStoreError(
                "market-stream recovery requires explicit data-loss acknowledgement"
            )
        if channel not in {"tick", "orderbook"}:
            raise ValueError("channel must be tick or orderbook")
        depth = self._normalize_orderbook_depth(depth)
        if channel == "tick" and depth is not None:
            raise ValueError("tick market streams cannot request depth")
        api = self._ensure_api_ready()
        result, previous_dropped = self._market_stream_adapter.accept_resync(
            dataname,
            api,
            channel=channel,
            depth=depth,
            acknowledge_data_loss=True,
        )
        self._record_market_stream_queue_state(
            str(dataname), channel, result, previous_dropped
        )
        return result

    def poll_execution_maintenance(self):
        """Drain the Store's one SDK event queue into Broker updates.

        Reconciliation uses its typed SDK facade and is not emulated by an
        optional provider method. The event queue remains available so SDK
        completions are not silently discarded while a Feed is idle.
        """
        if not self._sdk_mode or self._api is None:
            return
        self._drain_sdk_events()

    def poll_broker_update(self):
        """Poll a normalized broker-side order/trade/error update from the API."""
        if not self._connected:
            return None

        replay_reader = getattr(
            self._managed_execution_adapter, "poll_managed_provider_outbox_update", None
        )
        if callable(replay_reader):
            try:
                replay_update = replay_reader()
            except Exception as exc:
                self.sanitize_exception(exc)
                return None
            if isinstance(replay_update, Mapping):
                return dict(replay_update)

        api = self._ensure_api_ready()
        if self._sdk_mode:
            self._drain_sdk_events()
            update = self._command_runtime.pop_update()
        elif hasattr(api, "poll_broker_update"):
            update = api.poll_broker_update()
        else:
            return None
        if update is None:
            return None

        update = self.redact_runtime_value(update)
        self._emit_broker_runtime_event(update)
        return update

    def _append_sdk_update(self, update: Dict[str, Any]) -> None:
        """Publish a broker update through the single-owner runtime inbox."""
        self._command_runtime.publish_update(update)

    def _clear_sdk_updates(self, reason: str) -> int:
        """Drop queued broker updates through the runtime-owned inbox."""
        return self._command_runtime.clear_updates(reason)

    def _enqueue_sdk_command(
        self,
        command: Dict[str, Any],
        *,
        priority_name: str,
        emit_event: bool = True,
    ) -> Dict[str, Any]:
        """Insert one command without waiting for transport or the SDK worker."""
        operation = str(command.get("operation") or "").strip().lower()
        if operation in {"submit", "cancel"}:
            self._assert_write_route_identity()

        if self._restart_blocked_by_close:
            self._command_runtime.set_accepting_commands(False)
        receipt = self._command_runtime.enqueue(command, priority_name=priority_name)

        if emit_event:
            self.emit_runtime_event(
                "sdk_command_queued" if receipt["queued"] else "sdk_command_rejected",
                level="INFO" if receipt["queued"] else "ERROR",
                status=receipt["status"],
                order_ref=command.get("bt_order_ref"),
                error_code=receipt.get("error_code", ""),
                error_msg=receipt.get("error_msg", ""),
                details={
                    "command": command["operation"],
                    "receipt_id": receipt.get("receipt_id"),
                    "priority": priority_name,
                    "queue_depth": receipt["queue_depth"],
                },
            )
        return receipt

    def _is_sdk_market_data_only(self) -> bool:
        """Return whether the managed SDK session must reject every write."""
        return bool(
            self._sdk_mode
            and self._sdk_execution_config_value("market_data_only") is True
        )

    def _reject_market_data_only_command(
        self,
        operation: str,
        *,
        bt_order_ref: Any = None,
        client_order_id: Any = None,
    ) -> Dict[str, Any]:
        """Return a local rejection without creating or dispatching a command.

        Broker-level guards are useful for strategy code, but Store is also a
        public integration boundary. A caller holding a Store reference must
        not be able to enqueue a cancel or risk-reducing close while an SDK
        session is explicitly market-data-only.
        """
        receipt_id = uuid.uuid4().hex
        self._command_runtime.increment_health("rejected")
        self._command_runtime.increment_health("rejected_market_data_only")
        depth = self._command_runtime.snapshot().queue_depth
        receipt = {
            "kind": "command_receipt",
            "command": operation,
            "receipt_id": receipt_id,
            "bt_order_ref": bt_order_ref,
            "client_order_id": client_order_id,
            "status": "rejected",
            "queued": False,
            "priority": "blocked",
            "queue_depth": depth,
            "error_code": "market_data_only",
            "error_msg": "SDK command is disabled for this market-data-only session",
        }
        self.emit_runtime_event(
            "sdk_command_rejected_local",
            level="ERROR",
            order_ref=bt_order_ref,
            error_code="market_data_only",
            error_msg="SDK command is disabled for this market-data-only session",
            status="rejected",
            details={"operation": operation},
        )
        return receipt

    def record_market_data_only_broker_rejection(self, operation: str) -> None:
        """Record a Broker-local write rejection against this Store's audit.

        A single live Store can be reached through more than one
        :class:`BtApiBroker`.  In an observation-only session those Brokers
        reject writes before creating a Store command, so the Store must own
        the aggregate counter used by a preflight-to-strategy transfer.  This
        is local accounting only; it never dispatches a provider request.
        """

        if operation not in {"submit", "cancel", "batch_cancel"}:
            raise ValueError("unsupported market-data-only Broker operation")
        self._command_runtime.increment_health("rejected_market_data_only")

    async def _invoke_account_risk_command(self, command: Mapping[str, Any]) -> Any:
        """Adapt the account-risk SDK getter for the execution service worker."""

        del command
        return await _run_in_thread(
            self._read_account_risk_snapshot,
            self._ensure_api_ready(),
        )

    async def _execute_sdk_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """Delegate command outcome orchestration to the execution service."""

        return await self._execution_coordinator.execute_command(command)

    async def _invoke_sdk_command(self, operation: str, command: Dict[str, Any]):
        """Delegate correlated SDK writes to the existing execution adapter."""
        if operation in {"reconcile", "reconciliation"}:
            return await self._invoke_sdk_reconciliation(command)
        return await self._sdk_correlated_order_adapter.dispatch_command(
            operation,
            command,
            api=self._api,
            authorization=self._execution_authorization,
            current_authorization=lambda: self._execution_authorization,
            assert_write_route_identity=self._assert_write_route_identity,
            validate_approval_lease_command=self._validate_approval_lease_command,
            sanitize_exception=self.sanitize_exception,
            owner_fence=self._account_owner_fence,
        )

    #: ``() -> bool`` installed by ``bind_account_owner_fence``; ``None`` = unfenced.
    _account_owner_fence = None

    #: Subscribed account positions (``subscribe_account_positions``), or ``None``.
    _account_position_subscription = None

    def subscribe_account_positions(self, account_ref, *, baseline_interval_seconds=10.0):
        """Observe ``account_ref``'s position snapshots and subsequent pushes.

        A baseline is attempted at subscription and later refreshed according
        to ``baseline_interval_seconds`` and interruption state. Without a
        provider-verified snapshot/stream watermark, a report cannot prove an
        atomic cut or authorize reconciliation solely from its completeness
        flag. The returned subscription exposes an ``AccountPositionReport``.
        """

        from ._account_position_subscription import StoreAccountPositionSubscription

        current = self._account_position_subscription
        if current is not None:
            if current.account_ref != account_ref:
                raise ValueError("this store already subscribes another account's positions")
            return current
        subscription = StoreAccountPositionSubscription(
            self, account_ref, baseline_interval_seconds=baseline_interval_seconds
        )
        subscription.baseline()
        self._account_position_subscription = subscription
        return subscription

    def bind_account_owner_fence(self, allows_dispatch):
        """Install a diagnostic owner-generation check before SDK dispatch.

        The command worker invokes ``allows_dispatch()`` for queued writes.
        Its result is only as trustworthy as the supplied callback: the check
        and provider dispatch are not atomic, and this does not prove that an
        old owner is unable to write. Dispatch-edge fencing remains to be
        verified. A fence cannot be replaced once bound.
        """

        if not callable(allows_dispatch):
            raise ValueError("an account-owner fence callable is required")
        if self._account_owner_fence is not None:
            raise ValueError("this store is already bound to an account-owner fence")
        self._account_owner_fence = allows_dispatch

    @staticmethod
    def _validate_approval_lease_command(command: Mapping[str, Any]) -> None:
        """Map BT command fields to the SDK's pre-dispatch lease check."""
        try:
            from bt_api_py.approval_lease import ApprovalLeaseRejected, validate_approval_lease
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py approval lease contract is required"
            ) from exc
        try:
            validate_approval_lease(
                expires_at=command.get("approval_expires_at_utc"),
                operation_count=command.get("approval_operation_count"),
                maximum_count=command.get("approval_max_order_count"),
                risk_reducing=command.get("approval_risk_reducing"),
            )
        except ApprovalLeaseRejected as exc:
            raise _ApprovalLeaseRejected(exc.code) from None

    @staticmethod
    def _public_sdk_venue(venue: Any) -> str:
        """Return the stable provider key used by strategy-facing snapshots."""
        from bt_api_py.account_risk_state import public_venue_key

        return public_venue_key(venue)

    def _sdk_identity_expectations(self):
        """Delegate neutral configuration projection to SDK identity composition."""
        try:
            from bt_api_py.execution_identity_assurance_composition import (
                ExecutionIdentityExpectationError,
                build_execution_identity_expectations,
            )
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py identity expectation composition is required"
            ) from exc
        def configured_environment(route):
            assembly = self._sdk_direct_api_assembly
            return assembly.configured_environment(route) if assembly is not None else None

        try:
            return build_execution_identity_expectations(
                self._sdk_exchanges,
                strategy_id=self._sdk_execution_config_value("strategy_id"),
                account_aliases=self._sdk_execution_config_value("account_ids") or {},
                required_environments=self._sdk_execution_config_value("required_environments") or {},
                configured_environment=configured_environment,
            )
        except ExecutionIdentityExpectationError as exc:
            raise BtApiStoreError(exc.code) from None

    def _capture_sdk_identity_binding(self, api, expectations, *, stream_generation):
        """Capture an SDK vector and bind it to this Store's current generation."""
        try:
            from bt_api_py.execution_identity_assurance_composition import (
                ExecutionIdentityExpectationError,
                capture_execution_identity_binding,
            )
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py identity evidence contracts are required"
            ) from exc
        if (
            api is None
            or api is not self._api
            or type(stream_generation) is not int
            or stream_generation < 0
            or self._stream_generation != stream_generation
        ):
            raise BtApiStoreError("execution_identity_evidence_route_changed")
        routes = tuple(sorted(self._sdk_exchanges))
        try:
            binding = capture_execution_identity_binding(
                api,
                expectations,
                expected_routes=routes,
                sanitize_exception=self.sanitize_exception,
                exception_code=self._safe_exception_code,
            )
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py identity evidence contracts are required"
            ) from exc
        except ExecutionIdentityExpectationError as exc:
            raise BtApiStoreError(exc.code) from None
        self._sdk_execution_identity_fence.bind_vector(
            api,
            binding,
            expected_routes=routes,
            stream_generation=stream_generation,
            is_current_api=lambda candidate: (
                self._api is candidate
                and self._stream_generation == stream_generation
            ),
        )
        if not self._validate_sdk_identity_binding(
            api,
            binding,
            expectations,
            stream_generation=stream_generation,
        ):
            raise BtApiStoreError("execution_identity_evidence_not_current")
        return binding

    def _validate_sdk_identity_binding(
        self, api, binding, expectations, *, stream_generation
    ) -> bool:
        """Ask SDK to validate its identity vector, then enforce the BT fence."""
        try:
            from bt_api_py.execution_identity_assurance_composition import (
                validate_execution_identity_binding,
            )
        except ImportError:
            return False
        if (
            api is None
            or api is not self._api
            or type(stream_generation) is not int
            or stream_generation < 0
            or self._stream_generation != stream_generation
        ):
            return False
        routes = tuple(sorted(self._sdk_exchanges))
        try:
            valid = validate_execution_identity_binding(
                api,
                binding,
                expectations,
                expected_routes=routes,
                sanitize_exception=self.sanitize_exception,
            )
        except ImportError:
            return False
        if (
            valid is not True
            or self._api is not api
            or self._stream_generation != stream_generation
        ):
            return False
        return self._sdk_execution_identity_fence.validate_vector(
            api,
            binding,
            expected_routes=routes,
            stream_generation=stream_generation,
            is_current_api=lambda candidate: (
                self._api is candidate
                and self._stream_generation == stream_generation
            ),
        )

    def prepare_order_correlation(self, order):
        """Bind a Backtrader order through the correlated-execution adapter."""
        return _prepare_store_order_correlation(self, order, error_type=BtApiStoreError)

    def verify_order_response(self, correlation, response) -> bool:
        """Verify a sanitized submit completion against its SDK proof."""
        return self._verify_correlated_response(correlation, response, "submit")

    def verify_cancel_response(self, correlation, response) -> bool:
        """Verify a sanitized cancellation completion against its SDK proof."""
        return self._verify_correlated_response(correlation, response, "cancel")

    def _verify_correlated_response(self, correlation, response, expected_operation) -> bool:
        """Match the one-time Store receipt to an exact SDK acknowledgement."""
        try:
            command_types = self._sdk_correlated_order_adapter.warm_command_types()
            return self._sdk_execution_bindings.verify_order_response_once(
                correlation,
                response,
                expected_operation=expected_operation,
                current_api=self._api,
                correlation_type=command_types["OrderCorrelation"],
                acknowledgement_type=command_types["VerifiedOrderAcknowledgement"],
                validate_current_api=self._validate_order_response_route,
            )
        except Exception:
            return False

    def _validate_order_response_route(self) -> bool:
        try:
            self._assert_write_route_identity(
                expected_api=self._api, require_live_route=True
            )
        except Exception:
            return False
        return True

    def _clear_sdk_order_correlations(self) -> None:
        """Drop session-bound order correlations and preflight decisions."""
        self._sdk_execution_bindings.clear()
        self._execution_preflight.clear()

    def enqueue_order(self, order) -> Dict[str, Any]:
        """Queue a typed order through the unified SDK facade."""

        if self._service_read_only:
            raise BtApiStoreError("read-only service proxy cannot enqueue orders")
        self._assert_write_route_identity()

        if self._is_sdk_market_data_only():
            return self._reject_market_data_only_command(
                "submit",
                bt_order_ref=getattr(order, "ref", None),
            )

        try:
            receipt = self._enqueue_order_command(order)
        except Exception:
            _safe_log("error", "btapistore:6641 exception before re-raise (Exception)")
            raise
        return deepcopy(receipt)

    def _enqueue_order_command(self, order) -> Dict[str, Any]:
        """Build and queue one typed SDK order."""
        self._assert_write_route_identity()
        payload = self._order_to_payload(order)
        self._ensure_api_ready()
        self._require_async_sdk_commands(require_writes=True)
        api = self._api
        self._assert_write_route_identity(expected_api=api, require_live_route=True)
        venue = self._sdk_exchange(payload["symbol"])
        reference = getattr(order, "ref", None)
        if type(reference) is not int:
            raise BtApiStoreError("Backtrader order reference is unavailable")
        correlation_entry = self._sdk_execution_bindings.by_ref(reference)
        if correlation_entry is None or not self._sdk_execution_bindings.binding_matches(
            correlation_entry,
            api=api,
            exchange_name=venue,
            symbol=payload.get("symbol"),
            states={"prepared"},
            require_all_indexes=True,
        ) or correlation_entry.get("order") is not order:
            raise BtApiStoreError(
                "order requires a current SDK-issued correlation before dispatch"
            )
        correlation = correlation_entry.get("correlation")
        order_info = getattr(order, "info", {})
        get_info = getattr(order_info, "get", lambda *_args: None)
        request = self._sdk_order_request(
            venue,
            payload,
            correlation=correlation,
            framework_order=order,
        )
        client_id = request.client_order_id
        binding = self._sdk_execution_bindings.by_client_id(venue, str(client_id)) or {}
        execution_contract = deepcopy(binding.get("execution_contract") or {})
        if hasattr(order, "addinfo"):
            order.addinfo(
                client_order_id=client_id,
                sdk_execution_contract=execution_contract,
                quantity_unit=execution_contract.get("quantity_unit"),
                position_mode=execution_contract.get("position_mode"),
            )
        elif isinstance(getattr(order, "info", None), dict):
            order.info["client_order_id"] = client_id
            order.info["sdk_execution_contract"] = execution_contract
            order.info["quantity_unit"] = execution_contract.get("quantity_unit")
            order.info["position_mode"] = execution_contract.get("position_mode")
        from bt_api_py.queued_command_runtime import submission_priority

        priority_name = submission_priority(payload)
        approval_fields = {
            key: getattr(order_info, "get", lambda *_args: None)(key)
            for key in (
                "approval_expires_at_utc",
                "approval_operation_count",
                "approval_max_order_count",
                "approval_risk_reducing",
            )
        }
        command = {
            "operation": "submit",
            "venue": venue,
            "symbol": payload["symbol"],
            "request": request,
            "correlation": correlation,
            "bt_order_ref": payload.get("bt_order_ref"),
            "client_order_id": client_id,
            **approval_fields,
        }
        if not self._sdk_execution_bindings.set_state(
            correlation_entry, "queued", expected_states={"prepared"}
        ):
            raise BtApiStoreError("SDK order correlation changed before queueing")
        try:
            receipt = self._enqueue_sdk_command(command, priority_name=priority_name)
        except Exception:
            self._sdk_execution_bindings.set_state(
                correlation_entry, "prepared", expected_states={"queued"}
            )
            raise
        if receipt.get("queued") is not True:
            self._sdk_execution_bindings.set_state(
                correlation_entry, "prepared", expected_states={"queued"}
            )
        return receipt

    def enqueue_cancel(self, order_ref, dataname: Optional[str] = None) -> Dict[str, Any]:
        """Queue a typed cancellation while preserving its reserved capacity."""
        if self._service_read_only:
            raise BtApiStoreError("read-only service proxy cannot enqueue cancellations")
        self._assert_write_route_identity()
        if self._is_sdk_market_data_only():
            return self._reject_market_data_only_command(
                "cancel",
                bt_order_ref=order_ref,
            )
        self._ensure_api_ready()
        self._require_async_sdk_commands(require_writes=True)
        self._start_command_worker()
        venue, request, binding, correlation = self._sdk_cancel_request(order_ref, dataname)
        local_receipt = self._cancel_queued_opening_before_send(venue, request, binding)
        if local_receipt is not None:
            return local_receipt
        return self._enqueue_sdk_command(
            {
                "operation": "cancel",
                "venue": venue,
                "symbol": request.symbol,
                "request": request,
                "correlation": correlation,
                "bt_order_ref": binding.get("bt_order_ref", order_ref),
                "client_order_id": request.client_order_id,
            },
            priority_name="cancel",
        )

    def _cancel_queued_opening_before_send(
        self,
        venue: str,
        request: Any,
        binding: Mapping[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Locally terminalize an exact opening still queued but not dispatched."""
        client_order_id = str(getattr(request, "client_order_id", None) or "")
        bt_order_ref = binding.get("bt_order_ref")
        if not client_order_id or bt_order_ref is None:
            return None

        from bt_api_py.queued_command_runtime import matches_unsent_opening

        def matches(command: Mapping[str, Any]) -> bool:
            return matches_unsent_opening(
                command,
                venue=venue,
                request=request,
                current_generation=lambda: self._command_runtime.generation,
                client_order_id=client_order_id,
                local_ref=bt_order_ref,
                local_ref_field="bt_order_ref",
            )

        def mark_cancelled(opening: Mapping[str, Any]) -> None:
            correlation = opening.get("correlation")
            if correlation is not None:
                self._sdk_execution_bindings.set_state_by_correlation(
                    correlation, "cancelled_before_dispatch"
                )

        opening = self._command_runtime.remove_one(
            matches,
            "cancelled_before_send",
            on_remove=mark_cancelled,
        )
        if opening is None:
            return None
        completion = self._unsent_command_completion(opening, "cancelled_before_send")
        completion["status"] = "canceled"
        completion["response"] = {
            "kind": "order",
            "status": "canceled",
            "execution_unknown": False,
            "terminal_confirmed": True,
            "local_terminal": True,
            "remote_write_attempted": False,
            "error_code": "opening_cancelled_before_send",
            "error_msg": "Opening command was cancelled before remote transport",
        }

        try:
            self._append_sdk_update(completion)
        finally:
            self._command_runtime.release_publications()
        receipt = {
            "kind": "command_receipt",
            "command": "cancel",
            "receipt_id": uuid.uuid4().hex,
            "bt_order_ref": bt_order_ref,
            "client_order_id": client_order_id,
            "status": "cancelled_before_send",
            "queued": False,
            "priority": "cancel",
            "queue_depth": self._command_runtime.snapshot().queue_depth,
            "local_cancelled_before_send": True,
            "remote_write_attempted": False,
            "submit_receipt_id": opening.get("receipt_id"),
        }
        self.emit_runtime_event(
            "sdk_opening_cancelled_before_send",
            status="canceled",
            order_ref=bt_order_ref,
            details={"client_order_id": client_order_id},
        )
        return receipt

    def enqueue_query(self, order_ref, dataname: Optional[str] = None) -> Dict[str, Any]:
        """Reject provider-shaped order lookup without an SDK request handle."""
        raise BtApiStoreError(
            "order reconciliation requires an SDK-issued opaque request handle"
        )


    def _prepare_account_risk_refresh(self) -> Tuple[bool, Dict[str, Any], Optional[int]]:
        """Reserve one callback-safe account-risk refresh without dispatching it."""
        return self._account_risk_state.prepare_refresh(
            required=bool(self.requires_account_risk),
            store_started=self._started,
            store_connected=self._connected,
        )

    def _clear_account_risk_refresh_pending(self, refresh_token: Any) -> None:
        """Clear only the matching refresh reservation from a Store worker."""

        self._account_risk_state.clear_refresh_pending(refresh_token)

    def _dispatch_prepared_account_risk_refresh(self, refresh_token: int) -> Dict[str, Any]:
        """Queue an already-reserved refresh and undo only its own failed lease."""

        try:
            receipt = self._enqueue_sdk_command(
                {"operation": "account_risk", "account_risk_refresh_token": refresh_token},
                priority_name="reconcile",
            )
        except Exception:
            _safe_log("warning", "btapistore:account-risk refresh queue failed")
            self._clear_account_risk_refresh_pending(refresh_token)
            raise
        if not isinstance(receipt, Mapping) or receipt.get("queued") is not True:
            self._clear_account_risk_refresh_pending(refresh_token)
            if isinstance(receipt, Mapping):
                return dict(receipt)
            return {"queued": False, "status": "invalid_refresh_queue_receipt"}
        return dict(receipt)

    def enqueue_account_risk_refresh(self) -> Dict[str, Any]:
        """Queue a non-blocking SDK account-risk refresh for strategy callbacks."""

        should_dispatch, reservation, refresh_token = self._prepare_account_risk_refresh()
        if not should_dispatch:
            return reservation
        if refresh_token is None:  # pragma: no cover - guarded by the reservation contract
            raise BtApiStoreError("account-risk refresh reservation has no token")
        return self._dispatch_prepared_account_risk_refresh(refresh_token)

    def get_command_health(self) -> Dict[str, Any]:
        """Return queue and worker health without exposing command payloads."""
        read_only_metadata_probe_active = self._metadata_probe_service.is_active()
        runtime_health = self._command_runtime.health()
        execution_health = self._execution_coordinator.health()
        result = {
            **runtime_health,
            **dict(self._command_health),
            **execution_health,
            # A read-only observation needs a stable zero baseline before it
            # hands a Store from preflight to a strategy graph.  ``Counter``
            # omits never-incremented keys when converted to ``dict``; expose
            # this Store-scoped audit counter explicitly.  It includes Store
            # commands and Broker-local write rejections from every Broker
            # bound to this Store, so a replacement Broker cannot evade the
            # transfer's final zero-write check.
            "rejected_market_data_only": int(
                runtime_health.get("rejected_market_data_only", 0)
            ),
            "shutdown_state": self._shutdown_state,
            "close_thread_alive": bool(
                self._sdk_close_thread and self._sdk_close_thread.is_alive()
            ),
            "close_generation": self._sdk_close_generation,
            "restart_blocked_by_close": self._restart_blocked_by_close,
            "logging_errors": _LOGGING_HEALTH["logging_errors"],
            "read_only_metadata_probe_active": read_only_metadata_probe_active,
        }
        funding_health = self.get_funding_refresh_health()
        result.update(
            {
                "funding_worker_alive": funding_health["worker_alive"],
                "funding_queue_depth": funding_health["queue_depth"],
                "funding_inflight": funding_health["inflight"],
                "funding_pending": funding_health["pending"],
                "funding_generation": funding_health["generation"],
                "funding_restart_blocked_by_worker": funding_health["restart_blocked_by_worker"],
                "funding_last_refresh_error": funding_health["last_refresh_error"],
            }
        )
        return result

    def submit_order(self, order):
        """Submit through the sealed managed adapter or unified SDK queue.

        A managed adapter receives the private SDK dispatcher as an
        injected port.  The Store never catches an adapter failure and retries
        it directly: that would turn a missing journal, permit, or monitor
        fact into an accidental provider write.
        """

        legacy_entrypoint = _legacy_gateway_entrypoint(self.provider, self.backend)
        if legacy_entrypoint is not None:
            raise LegacyGatewayMigrationRequiredError(legacy_entrypoint)
        if self._service_read_only:
            raise BtApiStoreError("read-only service proxy cannot submit orders")
        self._assert_write_route_identity()
        adapter = self._managed_execution_adapter
        if adapter is None:
            return self._dispatch_sdk_order(order)
        order_ref = getattr(order, "ref", None)
        self.emit_runtime_event(
            "managed_execution_intent_requested",
            order_ref=order_ref,
            status="admission_pending",
        )
        try:
            response = adapter.submit_order(order, self._dispatch_sdk_order)
        except Exception as exc:
            _safe_log("error", "btapistore:managed execution adapter rejected submit")
            self.sanitize_exception(exc)
            self.emit_runtime_event(
                "managed_execution_submit_rejected",
                level="ERROR",
                order_ref=order_ref,
                status="rejected",
                error_code=self._safe_exception_code(exc, "managed_execution_submit_failed"),
                error_msg="Managed execution rejected the order before a direct fallback.",
            )
            raise
        if response is None:
            error = BtApiStoreError("managed execution adapter returned no submission projection")
            self.emit_runtime_event(
                "managed_execution_submit_rejected",
                level="ERROR",
                order_ref=order_ref,
                status="rejected",
                error_code="managed_execution_projection_missing",
                error_msg="Managed execution did not return a submission projection.",
            )
            raise error
        self.emit_runtime_event(
            "managed_execution_submit_projected",
            order_ref=order_ref,
            status="projected",
        )
        return response

    def _dispatch_sdk_order(self, order):
        """Submit through the unified SDK command queue."""
        if self._service_read_only:
            raise BtApiStoreError("read-only service proxy cannot submit orders")
        self._assert_write_route_identity()
        if not self._sdk_mode:
            raise BtApiStoreError(
                "order submission requires the bt_api_py.BtApi command facade"
            )
        if self._is_sdk_market_data_only():
            return self._reject_market_data_only_command(
                "submit",
                bt_order_ref=getattr(order, "ref", None),
            )
        self._ensure_api_ready()
        self._require_async_sdk_commands(require_writes=True)
        return self.enqueue_order(order)

    def refresh_managed_order_projection(self, order):
        """Return the current durable projection for one managed order.

        This is a read: it asks the attached adapter for the service journal's
        current state and never dispatches, cancels or falls back to the
        direct SDK route. A store without a managed adapter, or an adapter that
        cannot refresh, fails explicitly instead of returning a guess.
        """

        adapter = self._managed_execution_adapter
        if adapter is None:
            raise BtApiStoreError("managed execution adapter is not attached")
        refresh = getattr(adapter, "refresh_projection", None)
        if not callable(refresh):
            raise BtApiStoreError("managed execution adapter does not support refresh")
        info = getattr(order, "info", None)
        info_get = getattr(info, "get", None)
        intent_id = info_get("managed_intent_id") if callable(info_get) else None
        if not isinstance(intent_id, str) or not intent_id:
            raise BtApiStoreError("managed order has no intent identity to refresh")
        self._assert_write_route_identity()
        return refresh(intent_id)

    def cancel_order(self, order):
        """Cancel only with the Store's neutral SDK order identity."""
        legacy_entrypoint = _legacy_gateway_entrypoint(self.provider, self.backend)
        if legacy_entrypoint is not None:
            raise LegacyGatewayMigrationRequiredError(legacy_entrypoint)
        if self._service_read_only:
            raise BtApiStoreError("read-only service proxy cannot cancel orders")
        info = getattr(order, "info", None)
        info_get = getattr(info, "get", None)
        external_order_id = info_get("external_order_id") if callable(info_get) else None
        order_ref = external_order_id or getattr(order, "ref", None)
        dataname = self._extract_dataname(getattr(order, "data", None))
        if self._managed_execution_adapter is None:
            return self._dispatch_sdk_cancel(order_ref, dataname=dataname)
        return self._cancel_managed(order, dataname=dataname)
    def cancel_order_ref(self, order_ref, dataname: Optional[str] = None):
        """Cancel through managed execution or the unified SDK queue."""

        legacy_entrypoint = _legacy_gateway_entrypoint(self.provider, self.backend)
        if legacy_entrypoint is not None:
            raise LegacyGatewayMigrationRequiredError(legacy_entrypoint)
        if self._service_read_only:
            raise BtApiStoreError("read-only service proxy cannot cancel orders")
        adapter = self._managed_execution_adapter
        if adapter is None:
            return self._dispatch_sdk_cancel(order_ref, dataname=dataname)
        return self._cancel_managed(order_ref, dataname=dataname)

    def _cancel_managed(self, order_or_ref, dataname: Optional[str] = None):
        """Delegate cancellation through the configured managed adapter only."""

        self._assert_write_route_identity()
        adapter = self._managed_execution_adapter
        if adapter is None:
            raise BtApiStoreError("managed execution adapter is not attached")
        order_ref = getattr(order_or_ref, "ref", order_or_ref)
        self.emit_runtime_event(
            "managed_execution_cancel_requested",
            order_ref=order_ref,
            status="admission_pending",
        )
        try:
            cancel = require_managed_cancel(adapter)
        except ManagedExecutionAdapterError as error:
            self.emit_runtime_event(
                "managed_execution_cancel_rejected",
                level="ERROR",
                order_ref=order_ref,
                status="rejected",
                error_code="managed_execution_cancel_not_supported",
                error_msg="Managed execution has no cancellation projection.",
            )
            raise BtApiStoreError("managed_execution_cancel_not_supported") from error
        try:
            response = cancel(order_or_ref, dataname, self._dispatch_sdk_cancel)
        except Exception as exc:
            _safe_log("error", "btapistore:managed execution adapter rejected cancel")
            self.sanitize_exception(exc)
            self.emit_runtime_event(
                "managed_execution_cancel_rejected",
                level="ERROR",
                order_ref=order_ref,
                status="rejected",
                error_code=self._safe_exception_code(exc, "managed_execution_cancel_failed"),
                error_msg="Managed execution rejected cancellation without a direct fallback.",
            )
            raise
        if response is None:
            self.emit_runtime_event(
                "managed_execution_cancel_rejected",
                level="ERROR",
                order_ref=order_ref,
                status="rejected",
                error_code="managed_execution_cancel_projection_missing",
                error_msg="Managed execution did not return a cancellation projection.",
            )
            raise BtApiStoreError("managed execution adapter returned no cancellation projection")
        self.emit_runtime_event(
            "managed_execution_cancel_projected",
            order_ref=order_ref,
            status="projected",
        )
        return response
    def _dispatch_sdk_cancel(
        self,
        order_ref,
        dataname: Optional[str] = None,
    ):
        """Dispatch a cancellation through the unified SDK command queue."""
        if self._service_read_only:
            raise BtApiStoreError("read-only service proxy cannot cancel orders")
        if not self._sdk_mode:
            raise BtApiStoreError(
                "order cancellation requires the bt_api_py.BtApi command facade"
            )
        self._assert_write_route_identity()
        if self._is_sdk_market_data_only():
            return self._reject_market_data_only_command("cancel", bt_order_ref=order_ref)
        self._ensure_api_ready()
        self._require_async_sdk_commands(require_writes=True)
        return self.enqueue_cancel(order_ref, dataname=dataname)

    def push_live_bar(self, dataname: str, bar: Any):
        """Push a live bar into the local queue, primarily for tests."""
        self._enqueue_live_bar(str(dataname), self._copy_or_normalize_bar(bar))
        self._signal_live_bar_event()

    def set_history(self, dataname: str, bars: Iterable[Any]):
        """Replace the local historical bar cache, primarily for tests."""
        self._history_cache.set_history(dataname, bars)

    def emit_runtime_event(
        self,
        event_type: str,
        *,
        level: str = "INFO",
        status: str = "",
        details: Optional[Dict[str, Any]] = None,
        order_ref: Any = None,
        error_code: str = "",
        error_msg: str = "",
        **extra: Any,
    ) -> Dict[str, Any]:
        """Emit a structured runtime event into the store notification queue."""
        payload = {
            "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds"),
            "event_type": str(event_type),
            "level": str(level).upper(),
            "status": status,
            "provider": self.provider,
            "backend": self.backend,
            "session_id": self.session_id,
            "account_id_masked": self._masked_account_id(),
            "order_ref": order_ref,
            "error_code": error_code,
            "error_msg": error_msg,
            "details": dict(details or {}),
        }
        payload.update(extra)
        safe_payload = self.redact_runtime_value(payload)
        self.put_notification("runtime_event", event=safe_payload)
        return safe_payload

    def _facade_exchange_names(self, api: Any) -> List[str]:
        """Delegate the public SDK route-name projection to the BT route policy."""
        return self._sdk_route_policy.facade_exchange_names(api)

    def _assert_write_route_identity(
        self,
        *,
        require_live_route: bool = False,
        expected_api: Any = _WRITE_ROUTE_API_UNSET,
    ) -> None:
        """Delegate Store-local route/config checks without granting authority."""
        return self._sdk_route_policy.assert_identity(
            require_live_route=require_live_route,
            expected_api=expected_api,
        )


    def get_contract_metadata(self, dataname: Optional[str] = None):
        """Return configured or SDK-normalized metadata; missing SDK contracts fail closed."""
        if dataname is None:
            return {key: dict(value) for key, value in self.contract_metadata.items()}

        from bt_api_py.instrument_metadata_aliases import find_alias_match

        aliases = _contract_metadata_aliases(dataname)
        found, value = find_alias_match(
            self.contract_metadata, aliases,
            alias_fn=_contract_metadata_aliases, require_truthy=True,
        )
        if found:
            self.contract_metadata.setdefault(str(dataname), dict(value))
            return dict(value)

        if not self._sdk_mode:
            raise BtApiStoreError(
                "provider-neutral InstrumentSpec contract unavailable"
            )
        return self.get_symbol_info(str(dataname))

    def get_instrument_spec(self, dataname: str):
        """Return typed SDK instrument rules as a Backtrader-compatible mapping."""
        api = self._ensure_api_ready()
        if self._service_read_only:
            return self.get_contract_metadata(dataname)
        if not self._sdk_mode or not callable(getattr(api, "get_instrument_spec", None)):
            raise BtApiStoreError(
                "The configured SDK facade has no typed InstrumentSpec contract"
            )
        metadata = _contract_mapping(
            api.get_instrument_spec(self._sdk_exchange(dataname), dataname),
            "InstrumentSpec",
        )
        from bt_api_py.instrument_metadata_aliases import legacy_instrument_spec_fields

        legacy_instrument_spec_fields(metadata)
        self.contract_metadata[str(dataname)] = deepcopy(metadata)
        return deepcopy(metadata)

    def get_typed_instrument_spec(self, dataname: str):
        """Return the public SDK ``InstrumentSpec`` without compatibility aliases.

        Strategy runners that need cross-venue sizing use this method so they
        do not rebuild contract semantics from Backtrader's legacy mapping.
        """

        api = self._ensure_api_ready()
        if not self._sdk_mode or not callable(getattr(api, "get_instrument_spec", None)):
            raise BtApiStoreError("The configured provider has no typed InstrumentSpec contract")
        return api.get_instrument_spec(self._sdk_exchange(dataname), dataname)

    def get_symbol_info(self, dataname: str):
        """Compatibility alias for :meth:`get_instrument_spec`."""
        return self.get_instrument_spec(dataname)

    def _funding_cache_key(self, dataname: str) -> Tuple[str, str]:
        """Return the route-qualified identity used by the funding cache."""
        symbol = str(dataname)
        if self._sdk_mode:
            route = self._sdk_exchange(symbol)
        else:
            route = self._sdk_routes.get(symbol, self.provider)
        return str(route), symbol

    def _read_funding_snapshot_from_api(self, api: Any, dataname: str) -> Dict[str, Any]:
        """Perform exactly one typed SDK funding read without cache policy."""
        if not self._sdk_mode or not callable(getattr(api, "get_funding_snapshot", None)):
            raise BtApiStoreError("The SDK does not expose typed funding snapshots")
        return _contract_mapping(
            api.get_funding_snapshot(self._sdk_exchange(dataname), dataname),
            "FundingSnapshot",
        )

    def _observe_funding_refresh_error(self, exc: BaseException) -> None:
        """Redact a funding read failure before emitting a finite diagnostic."""
        self.sanitize_exception(exc)
        _safe_log("warning", "btapistore: funding refresh failed")

    def _validate_funding_snapshot_contract(
        self, snapshot: Mapping[str, Any], now_epoch: float, key: Tuple[str, str]
    ) -> str:
        """Apply the SDK's typed cross-venue funding contract validation."""
        if not self._sdk_mode:
            return ""
        try:
            _, coerce_funding_snapshot, _ = _sdk_cross_venue_contracts()
            coerce_funding_snapshot(
                snapshot,
                now_epoch=Decimal(str(now_epoch)),
                expected_exchange_name=key[0],
                expected_symbol=key[1],
            )
        except (BtApiStoreError, TypeError, ValueError, InvalidOperation) as exc:
            return self._safe_exception_code(exc, "funding_snapshot_invalid")
        return ""

    def _assert_sdk_api_lanes_quiescent(
        self, expected_api: Any, *, allow_store_stopping: bool = False
    ) -> None:
        """Require every Store-owned user of a shared SDK client to be stopped."""
        if self._api is not expected_api:
            raise BtApiStoreError("The stale SDK API is no longer the active Store API")
        if not allow_store_stopping and (self._started or self._connected):
            raise BtApiStoreError("Cannot close the SDK API while the Store session is active")

        if self._metadata_probe_service.is_active() and not self._metadata_probe_service.owns_current_thread():
            raise BtApiStoreError("Cannot close the SDK API while a metadata probe is active")

        command_state = self._command_runtime.snapshot()
        if (
            command_state.worker_alive
            or command_state.queue_depth
            or command_state.inflight
            or command_state.publications_pending
        ):
            raise BtApiStoreError("Cannot close the SDK API while command work is active")

        if self._market_stream_adapter.has_subscriptions:
            raise BtApiStoreError("Cannot close the SDK API while a market-stream subscription is open")

        close_thread = self._sdk_close_thread
        if close_thread is not None and close_thread.is_alive():
            raise BtApiStoreError("Cannot close the SDK API while a previous close is still active")

    def _close_stale_api_after_funding_timeout(
        self,
        stale_api: Any,
        *,
        allow_store_stopping: bool = False,
        timeout: Optional[float] = None,
    ) -> None:
        """Close the exact owned API through the shared retained close state."""
        if not self._sdk_owned_api:
            return
        if self._last_successfully_closed_api is stale_api:
            if self._api is stale_api:
                self._api = None
                self._sdk_configured = False
            elif self._api is not None:
                raise BtApiStoreError("A different SDK API replaced the closed client")
            return
        if stale_api is not self._api:
            raise BtApiStoreError("The stale funding API is no longer the active Store API")
        self._assert_sdk_api_lanes_quiescent(
            stale_api, allow_store_stopping=allow_store_stopping
        )
        closed, close_error = self._bounded_sdk_close(
            stale_api,
            self._command_shutdown_timeout if timeout is None else timeout,
        )
        if not closed or close_error is not None:
            raise BtApiStoreError("The stale SDK client close is not verified") from None
        if self._api is not None and self._api is not stale_api:
            raise BtApiStoreError("A different SDK API replaced the stale client during close")
        self._api = None
        self._sdk_configured = False

    def _read_funding_snapshot(self, dataname: str) -> Dict[str, Any]:
        """Read one mapping through the controller's serialized transport lane."""
        return self._funding_refresh.read_direct(dataname)

    def request_funding_refresh(self, dataname: str, *, force: bool = False) -> Dict[str, Any]:
        """Request a coalesced asynchronous funding refresh."""
        return self._funding_refresh.request(dataname, force=force)

    def enqueue_funding_refresh(self, dataname: str, *, force: bool = False) -> Dict[str, Any]:
        """Compatibility spelling for :meth:`request_funding_refresh`."""
        return self.request_funding_refresh(dataname, force=force)

    def wait_for_funding_refreshes(self, timeout: Optional[float] = None) -> bool:
        """Wait boundedly for controller-owned funding reads."""
        return self._funding_refresh.wait(timeout)

    def get_cached_funding_snapshot(
        self,
        dataname: str,
        *,
        max_age_seconds: Optional[float] = None,
        request_refresh: bool = True,
    ) -> Dict[str, Any]:
        """Return a pure-local funding cache view and optionally enqueue a read."""
        return self._funding_refresh.get_cached(
            dataname,
            max_age_seconds=max_age_seconds,
            request_refresh=request_refresh,
        )

    def get_funding_refresh_health(self, dataname: Optional[str] = None) -> Dict[str, Any]:
        """Return the controller's consistent worker, cache, and health view."""
        return self._funding_refresh.get_health(dataname)

    def get_funding_snapshot(self, dataname: str):
        """Synchronously read funding and preserve the historical Unix-time API."""
        return self._funding_refresh.get_snapshot(dataname)

    def get_funding_rate(self, dataname: str):
        """Compatibility alias returning the normalized funding snapshot mapping."""
        return self.get_funding_snapshot(dataname)
    def get_typed_funding_snapshot(self, dataname: str):
        """Read the exact SDK FundingSnapshot through the serialized lane."""
        if not self._sdk_mode:
            raise BtApiStoreError("The configured provider has no typed FundingSnapshot contract")

        def read_typed_snapshot(api, symbol):
            if not callable(getattr(api, "get_funding_snapshot", None)):
                raise BtApiStoreError(
                    "The configured provider has no typed FundingSnapshot contract"
                )
            return api.get_funding_snapshot(self._sdk_exchange(symbol), symbol)

        return self._funding_refresh.read_direct_value(dataname, read_typed_snapshot)
    def get_fee_schedule(self, dataname: str, account_id: Optional[str] = None):
        """Return account fee rates with explicit availability and freshness."""
        api = self._ensure_api_ready()
        if not self._sdk_mode or not callable(getattr(api, "get_fee_schedule", None)):
            raise BtApiStoreError("The SDK does not expose a fee schedule")
        venue = self._sdk_exchange(dataname)
        resolved_account_id = self._sdk_account_id(venue, account_id)
        return _contract_mapping(
            api.get_fee_schedule(venue, dataname, resolved_account_id),
            "FeeSchedule",
        )

    def get_typed_fee_schedule(self, dataname: str, account_id: Optional[str] = None):
        """Return the public SDK account ``FeeSchedule`` without remapping it."""

        api = self._ensure_api_ready()
        venue = self._sdk_exchange(dataname) if self._sdk_mode else None
        if not self._sdk_mode or not callable(getattr(api, "get_fee_schedule", None)):
            raise BtApiStoreError("The configured provider has no typed FeeSchedule contract")
        return api.get_fee_schedule(venue, dataname, self._sdk_account_id(venue, account_id))

    def get_account_config(self, dataname: str):
        """Return routed account mode and explicit trading permission."""
        api = self._ensure_api_ready()
        if not self._sdk_mode or not callable(getattr(api, "get_account_config", None)):
            raise BtApiStoreError("The SDK does not expose account configuration")
        return _contract_mapping(
            api.get_account_config(self._sdk_exchange(dataname), normalized=True),
            "account configuration",
        )

    def get_environment_info(self, dataname: str):
        """Return the public SDK's credential-free routed environment proof."""
        api = self._ensure_api_ready()
        if not self._sdk_mode or not hasattr(api, "get_environment_info"):
            raise BtApiStoreError("The provider does not expose environment information")
        return dict(api.get_environment_info(self._sdk_exchange(dataname)))

    def get_trading_readiness(
        self,
        dataname: str,
        quantity_native,
        *,
        margin_mode: str = "cross",
        expected_position_mode: Optional[str] = None,
        account_id: Optional[str] = None,
    ):
        """Return the unified typed readiness contract as a compatibility mapping."""
        api = self._ensure_api_ready()
        if not self._sdk_mode:
            raise BtApiStoreError("The SDK does not expose order readiness")
        from bt_api_py.order_readiness_composition import read_sdk_trading_readiness

        venue = self._sdk_exchange(dataname)
        return read_sdk_trading_readiness(
            api, venue, dataname, quantity_native,
            margin_mode=margin_mode,
            position_mode=expected_position_mode,
            resolve_account_id=lambda: self._sdk_account_id(venue, account_id),
            contract_mapping=_contract_mapping,
            error_type=BtApiStoreError,
        )

    def get_order_readiness(
        self,
        dataname: str,
        quantity_native,
        *,
        margin_mode: str = "cross",
        position_mode: Optional[str] = None,
    ):
        """Compatibility alias for :meth:`get_trading_readiness`."""
        return self.get_trading_readiness(
            dataname,
            quantity_native,
            margin_mode=margin_mode,
            expected_position_mode=position_mode,
        )

    def _resolve_sdk_route_name(self, api: Any, exchange_name: str) -> str:
        """Resolve one explicit request to the exact configured live route key."""
        if type(exchange_name) is not str or not exchange_name or exchange_name != exchange_name.strip():
            raise ValueError("exchange_name must be non-empty trimmed text")
        if not self._sdk_mode or self._service_read_only:
            raise BtApiStoreError("route selection requires the unified SDK facade")
        self._assert_write_route_identity(require_live_route=True, expected_api=api)
        live_names = self._facade_exchange_names(api)
        from bt_api_py.route_identity_projection import select_exact_live_route

        return select_exact_live_route(live_names, exchange_name, error_type=BtApiStoreError)

    def query_facade(self, exchange_name: str):
        """Return the SDK's neutral query facade for one exact configured route.

        The returned object implements bounded typed query/receipt/lease
        operations. Store never returns or unwraps the selected provider client.
        """
        api = self._ensure_api_ready()
        selected = self._resolve_sdk_route_name(api, exchange_name)
        try:
            from bt_api_py.query_composition import select_query_facade
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py.query_composition.select_query_facade is required"
            ) from exc
        return select_query_facade(
            api, selected,
            error_type=BtApiStoreError,
            missing_dependency_error_type=BtApiMissingDependencyError,
            safe_exception_code=self._safe_exception_code,
        )

    def get_futures_contracts(self, route, exchange_id, product_id, *, environment,
                              allow_reference=False, **limits):
        """Delegate a bounded reference lookup to the configured SDK route.

        Each call refreshes; use the combined result for both ranks. The
        Store's existing SDK is reused without creating an account connection.
        """
        try:
            from bt_api_py.futures_contract_lookup import (
                FuturesContractLookupUnavailable, lookup_futures_contracts,
            )
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py futures contract lookup is required"
            ) from exc
        if type(allow_reference) is not bool:
            raise TypeError("allow_reference must be bool")
        if not allow_reference:
            raise FuturesContractLookupUnavailable("FUTURES_MARKET_FRESHNESS_UNAVAILABLE")
        api = self._ensure_api_ready()
        selected = self._resolve_sdk_route_name(api, route)
        query = self.query_facade(selected)
        self._assert_write_route_identity(require_live_route=True, expected_api=api)
        calendar_port = api.futures_expected_calendar(selected)
        result = lookup_futures_contracts(
            query, calendar_port, route=selected, exchange_id=exchange_id,
            product_id=product_id, environment=environment,
            allow_reference=allow_reference, **limits,
        )
        self._assert_write_route_identity(require_live_route=True, expected_api=api)
        return result

    def order_capacity_facts(self, exchange_name: Optional[str] = None):
        """Return SDK-owned order-capacity facts for one exact route.

        With no explicit route, this selects only a single live Store route.
        Missing or ambiguous routes and absent capacity capability produce a
        typed unavailable snapshot; Store order lists are never used to invent
        SDK capacity evidence.
        """
        try:
            from bt_api_py.execution_capacity import (
                read_order_capacity_facts,
                unavailable_order_capacity_snapshot,
            )
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py execution-capacity contracts are required"
            ) from exc

        if not self._sdk_mode or self._service_read_only:
            return unavailable_order_capacity_snapshot(
                None, "order_capacity_capability_unavailable"
            )
        api = self._api
        if api is None or not self._connected:
            return unavailable_order_capacity_snapshot(
                None, "order_capacity_route_unavailable"
            )
        try:
            self._assert_write_route_identity(
                expected_api=api, require_live_route=True
            )
            if exchange_name is None:
                live_names = self._facade_exchange_names(api)
                if len(live_names) != 1:
                    return unavailable_order_capacity_snapshot(
                        None, "order_capacity_route_resolution_failed"
                    )
                selected = self._resolve_sdk_route_name(api, live_names[0])
            else:
                selected = self._resolve_sdk_route_name(api, exchange_name)
        except Exception:
            return unavailable_order_capacity_snapshot(
                None, "order_capacity_route_resolution_failed"
            )

        return read_order_capacity_facts(api, selected)

    def get_market_instrument_key(self, dataname: str):
        """Return an explicitly configured exact neutral instrument key.

        Store does not construct instrument identity from a ticker.  The SDK
        route-bound rules and market selectors remain responsible for checking
        the key against their selected provider and environment.
        """
        try:
            from bt_api_py.facade_protocol import MarketInstrumentKey
            from bt_api_py.instrument_metadata_aliases import configured_market_instrument_key
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py.facade_protocol.MarketInstrumentKey is required"
            ) from exc
        if type(dataname) is not str or not dataname or dataname != dataname.strip():
            raise ValueError("dataname must be non-empty trimmed text")
        if not self._sdk_mode or self._service_read_only:
            raise BtApiStoreError("neutral instrument keys require the unified SDK Store")
        self._sdk_exchange(dataname)
        return configured_market_instrument_key(
            self.contract_metadata,
            dataname,
            instrument_type=MarketInstrumentKey,
            error_type=BtApiStoreError,
        )

    def evaluate_order_rules(
        self,
        order,
        *,
        market_instrument_key=None,
        current_position=None,
    ):
        """Delegate SDK-bound order-rule evaluation to the execution owner."""
        return self._execution_preflight.evaluate_order_rules(
            order,
            market_instrument_key=market_instrument_key,
            current_position=current_position,
        )

    def verify_order_rules(self, order, decision) -> bool:
        """Verify an order-rule decision through the execution owner."""
        return self._execution_preflight.verify_order_rules(order, decision)

    def evaluate_order_economics(self, order, rules_decision):
        """Delegate SDK-bound economics evaluation to the execution owner."""
        return self._execution_preflight.evaluate_order_economics(order, rules_decision)

    def verify_order_economics(self, order, decision) -> bool:
        """Verify an economics decision through the execution owner."""
        return self._execution_preflight.verify_order_economics(order, decision)

    def account_session_snapshot(self, exchange_name: str):
        """Return an SDK-typed account/session observation for one explicit route.

        Connection, authentication, trading readiness, and settlement status
        are observations; none grants write authority.
        """
        try:
            from bt_api_py.facade_protocol import (
                AccountSessionSnapshot,
                AccountSessionWorkflowFacade,
            )
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py account-session workflow contracts are required"
            ) from exc

        api = self._ensure_api_ready()
        if not self._sdk_mode or self._service_read_only:
            raise BtApiStoreError(
                "account-session capabilities require the unified SDK facade"
            )
        selected = self._resolve_sdk_route_name(api, exchange_name)
        if not isinstance(api, AccountSessionWorkflowFacade):
            raise BtApiStoreError(
                "SDK facade does not expose AccountSessionWorkflowFacade"
            )
        snapshot = api.account_session_snapshot(selected)
        if type(snapshot) is not AccountSessionSnapshot:
            raise BtApiStoreError(
                "SDK account-session workflow returned an invalid snapshot"
            )
        return snapshot

    def account_preflight(self, request):
        """Return request-bound neutral readiness evidence from the SDK.

        The SDK workflow owns receipt, lease, and route-currentness checks.
        Readiness never substitutes for execution authorization.
        """
        try:
            from bt_api_py.facade_protocol import (
                AccountPreflightRequest,
                AccountPreflightSnapshot,
                AccountSessionWorkflowFacade,
            )
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py.facade_protocol AccountPreflightRequest is required"
            ) from exc
        if type(request) is not AccountPreflightRequest:
            raise TypeError("request must be an exact AccountPreflightRequest")
        api = self._ensure_api_ready()
        if not self._sdk_mode or self._service_read_only:
            raise BtApiStoreError(
                "account-session capabilities require the unified SDK facade"
            )
        selected = self._resolve_sdk_route_name(api, request.exchange_name)
        if request.exchange_name != selected:
            raise BtApiStoreError("account preflight route does not match the selected SDK route")
        if not isinstance(api, AccountSessionWorkflowFacade):
            raise BtApiStoreError(
                "SDK facade does not expose AccountSessionWorkflowFacade"
            )
        snapshot = api.account_preflight(request)
        if type(snapshot) is not AccountPreflightSnapshot:
            raise BtApiStoreError("SDK account-session workflow returned an invalid preflight")
        return snapshot

    def verify_account_settlement(self, exchange_name: str, *, deadline):
        """Perform an SDK-owned active, read-only settlement server readback."""
        try:
            from bt_api_py.facade_protocol import (
                AccountSessionWorkflowFacade,
                SettlementVerificationReceipt,
            )
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py account-session workflow contracts are required"
            ) from exc

        if (
            type(deadline) is not _dt.datetime
            or deadline.tzinfo is None
            or deadline.utcoffset() != _dt.timedelta(0)
        ):
            raise ValueError("deadline must be a timezone-aware UTC datetime")
        if deadline <= _dt.datetime.now(_UTC):
            raise ValueError("deadline must be in the future")
        api = self._ensure_api_ready()
        if not self._sdk_mode or self._service_read_only:
            raise BtApiStoreError(
                "account-session capabilities require the unified SDK facade"
            )
        selected = self._resolve_sdk_route_name(api, exchange_name)
        if not isinstance(api, AccountSessionWorkflowFacade):
            raise BtApiStoreError(
                "SDK facade does not expose AccountSessionWorkflowFacade"
            )
        receipt = api.verify_account_settlement(selected, deadline=deadline)
        if type(receipt) is not SettlementVerificationReceipt:
            raise BtApiStoreError(
                "SDK account-session workflow returned an invalid settlement receipt"
            )
        return receipt

    def confirm_account_settlement(self, request):
        """Attempt one separately authorized settlement confirmation.

        The SDK owns the one-shot claim, command, and readback workflow. This
        Store passes through its injected authorization unchanged and never
        derives authority from a preflight, route, mode, or order token.
        """
        try:
            from bt_api_py.facade_protocol import (
                SettlementConfirmationOutcome,
                SettlementConfirmationRequest,
                SettlementConfirmationWorkflowFacade,
            )
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py.facade_protocol settlement confirmation workflow is required"
            ) from exc
        if type(request) is not SettlementConfirmationRequest:
            raise TypeError("request must be an exact SettlementConfirmationRequest")
        authorization = self._settlement_authorization
        if authorization is None:
            raise BtApiStoreError("SDK settlement confirmation authorization is unavailable")
        api = self._ensure_api_ready()
        if not self._sdk_mode or self._service_read_only:
            raise BtApiStoreError("settlement confirmation requires the unified SDK facade")
        selected = self._resolve_sdk_route_name(api, request.exchange_name)
        if request.exchange_name != selected:
            raise BtApiStoreError("settlement confirmation route does not match the SDK route")
        if not isinstance(api, SettlementConfirmationWorkflowFacade):
            raise BtApiStoreError(
                "SDK facade does not expose SettlementConfirmationWorkflowFacade"
            )
        confirm_once = getattr(api, "confirm_settlement_once", None)
        if not callable(confirm_once):
            raise BtApiStoreError("SDK facade lacks optional confirm_settlement_once() capability")
        try:
            outcome = confirm_once(
                selected,
                request,
                authorization=authorization,
            )
        except Exception:
            raise BtApiStoreError("SDK settlement confirmation claim was rejected") from None
        if (
            type(outcome) is not SettlementConfirmationOutcome
            or outcome.receipt.request is not request
        ):
            raise BtApiStoreError("SDK settlement confirmation projection is invalid")
        return outcome

    def get_venue_balances(self, force: bool = False):
        """Return verified balances and valuation separately for each route."""
        if self._sdk_mode:
            api = self._ensure_api_ready()
            routes = tuple(self._sdk_exchanges)
            try:
                live_names = self._facade_exchange_names(api)
                snapshots = self._sdk_account_read_adapter.snapshots_for_live_routes(
                    api,
                    routes,
                    live_names,
                    force=force,
                    cache_ttl=self._account_cache_ttl,
                )
                balances = {
                    route: self._project_sdk_venue_balance_snapshot(
                        route, snapshots[route]
                    )
                    for route in routes
                }
            except BtApiStoreError:
                raise
            except Exception as exc:
                self.sanitize_exception(exc)
                error = BtApiStoreError(
                    "SDK per-route account balance snapshots are unavailable"
                )
                error.code = "account_balance_snapshot_unavailable"
                raise error from None
            return deepcopy(balances)

        raise BtApiStoreError("Per-venue balances require the unified SDK snapshot interface")

    def get_venue_balance(self, dataname: str, force: bool = False):
        """Return the account snapshot for the route bound to ``dataname``.

        Each SDK route is independently read and lease-validated; rows and any
        valuation remain scoped to that route and are never cross-aggregated.
        """
        if self._sdk_mode:
            api = self._ensure_api_ready()
            venue = self._sdk_exchange(dataname)
            route = self._resolve_sdk_route_name(api, venue)
            snapshot = self._sdk_balance_snapshot_for_route(
                api,
                route,
                force=force,
            )
            return deepcopy(
                self._project_sdk_venue_balance_snapshot(route, snapshot)
            )

        raise BtApiStoreError("Per-venue balances require the unified SDK snapshot interface")

    def get_cached_venue_balance(self, dataname: str):
        """Return a previously hydrated venue balance without transport I/O."""
        if self._sdk_mode:
            # The generic SDK lease verifier may perform provider I/O (for
            # example, authenticated identity readback). Without a separate
            # SDK contract that guarantees local-only currentness validation,
            # this Store cannot promise that a cache-only getter stays offline.
            error = BtApiStoreError(
                "SDK cached venue balance cannot be validated without transport"
            )
            error.code = "account_balance_snapshot_unavailable"
            raise error

        venue = self._sdk_routes.get(dataname)
        if venue not in self._venue_balance_cache:
            raise BtApiStoreError(f"No cached account balance is available for venue {venue!r}")
        return deepcopy(self._venue_balance_cache[venue])

    def apply_reconcile_snapshot(self, snapshot: Mapping[str, Any]) -> None:
        """Apply a Store-bound reconciliation through the execution adapter."""
        return _apply_reconcile_snapshot(self, snapshot, error_type=BtApiStoreError)

    def verify_reconciliation_snapshot(self, snapshot) -> bool:
        """Revalidate a queued account projection through the execution adapter."""
        return _verify_reconciliation_snapshot(self, snapshot)

    def verify_order_reconciliation(self, correlation, response) -> bool:
        """Revalidate a queued order projection through the execution adapter."""
        return _verify_order_reconciliation(self, correlation, response)

    def get_execution_summary(self):
        """Read the active session, or its stop snapshot without reconnecting."""
        if self._last_execution_summary is not None:
            source_summary = self._last_execution_summary
        else:
            api = self._ensure_api_ready()
            if not hasattr(api, "get_execution_summary"):
                raise BtApiStoreError("The provider does not expose execution audit counts")
            source_summary = api.get_execution_summary()
        # The public SDK boundary permits read-only Mapping implementations,
        # including nested diagnostic mappings.  Normalize mappings recursively
        # before copying so the local marker never mutates a provider object and
        # ``deepcopy`` never attempts to pickle a nested mapping proxy.
        summary = self._copy_execution_summary_value(source_summary)

        # A callback read queues account-risk refresh work on the Store worker.
        # It must not wait for that work or imply that the old snapshot remains
        # complete while the authoritative read is unsettled.  Publish the
        # local pending state as a separate field instead of mutating the SDK's
        # evidence-error shape; the broker converts it to a fail-closed risk
        # result for strategy callbacks.
        account_risk_refresh_pending = self._account_risk_state.refresh_pending
        if isinstance(summary, Mapping) and account_risk_refresh_pending:
            # The SDK may return a read-only Mapping.  The pending marker is
            # Store-local diagnostic state, so never mutate that provider object.
            summary = dict(summary)
            summary["account_risk_refresh_in_progress"] = True
        return summary

    @staticmethod
    def _copy_execution_summary_value(value: Any) -> Any:
        """Copy a public summary while normalizing nested read-only mappings.

        Execution summaries are normalized SDK data, but the public boundary
        permits any ``Mapping`` implementation.  Preserve non-mapping leaves
        with ``deepcopy`` so this diagnostic read retains its historic values.
        """
        from bt_api_py.contract_mapping import copy_mapping_tree

        return copy_mapping_tree(value)

    def _cache_account_risk_snapshot_before_shutdown(self) -> None:
        """Retain an existing safe view without starting shutdown-time network I/O.

        Account-risk reads can require several authenticated venue requests.  A
        fresh read here would consume the caller's shutdown deadline before the
        SDK transports are closed.  When no identity-bound SDK account-risk
        snapshot is already cached, post-stop callers receive the explicit
        unavailable contract instead of a guessed snapshot.
        """
        if not self._sdk_owned_api or self._api is None:
            return
        cached = self._account_risk_state.has_cached_snapshot(self._stream_generation)
        if cached:
            return
        try:
            snapshot = self._read_account_risk_snapshot(self._api)
        except Exception as exc:
            # Shutdown must still close a synchronous compatibility client if
            # its optional risk diagnostic violates the public contract.
            _safe_log("warning", "btapistore:13461 fallback on Exception")
            self.sanitize_exception(exc)
            return
        self._cache_account_risk_snapshot(snapshot)

    def _cache_account_risk_snapshot(self, snapshot: Mapping[str, Any]) -> Dict[str, Any]:
        """Publish one validated, redacted account-risk snapshot for callback reads."""
        return self._account_risk_state.cache_snapshot(snapshot, self._stream_generation)

    def _cached_account_risk_unavailable(self) -> Dict[str, Any]:
        from bt_api_py.account_risk_state import unavailable_account_risk_snapshot

        routes = sorted(str(venue) for venue in self._sdk_exchanges)
        snapshot = unavailable_account_risk_snapshot(
            routes,
            configured_loss_limit=self._sdk_execution_config_value(
                "account_maximum_loss_bps"
            ),
            error_code="account_risk_cache_unavailable",
        )
        snapshot["blocked_reasons"] = ["account_risk_cache_unavailable"]
        return snapshot

    def get_callback_account_risk_state(self) -> Dict[str, Any]:
        """Return a local risk snapshot and its refresh state without SDK I/O.

        The cached snapshot and refresh reservation are read and created under
        one lock.  This deliberately makes a callback conservative: if the
        worker completes immediately after that critical section, callers still
        observe ``refresh_pending`` for this read instead of accepting an older
        complete snapshot.  Queue dispatch happens after the lock is released
        and never calls an SDK method on the strategy callback thread.
        """

        return self._account_risk_state.callback_state(
            generation=self._stream_generation,
            required=bool(self.requires_account_risk),
            store_started=self._started,
            store_connected=self._connected,
            dispatch_refresh=self._dispatch_prepared_account_risk_refresh,
            unavailable_snapshot=self._cached_account_risk_unavailable,
        )

    def get_cached_account_risk_snapshot(self) -> Dict[str, Any]:
        """Return callback-safe risk evidence and schedule refresh without network I/O."""

        return self.get_callback_account_risk_state()["snapshot"]

    def get_account_risk_snapshot(self) -> Dict[str, Any]:
        """Return SDK-owned durable account-loss evidence or an explicit blocker.

        The Store deliberately does not synthesize a durable baseline or
        realised PnL from Backtrader's process-local cash/value fields.  A
        provider without the public SDK contract therefore returns a complete
        fail-closed shape with ``evidence_complete=False``.
        """
        cached = self._account_risk_state.cached_snapshot(self._stream_generation)
        if cached is not None and (self._started or self._api is None):
            return cached
        return self._read_account_risk_snapshot(self._api)

    def initialize_account_risk_baseline(self) -> Dict[str, Any]:
        """Ask the SDK to initialize its baseline under its authoritative flatness gate."""
        if not self.requires_account_risk:
            raise BtApiStoreError("account_risk_not_required")
        snapshot = self._read_account_risk_snapshot(
            self._ensure_api_ready(), initialize_baseline=True
        )
        if (
            snapshot.get("evidence_complete") is not True
            or snapshot.get("durable") is not True
            or snapshot.get("trading_blocked") is not False
        ):
            raise BtApiStoreError("account_risk_baseline_not_proven")
        return snapshot

    def get_reconcile_snapshot(self) -> Dict[str, Any]:
        """Keep startup fail-closed until SDK exposes the account risk proof it needs."""
        return self._incomplete_reconciliation_snapshot(
            "startup_account_risk_proof_unavailable"
        )

    def _read_account_risk_snapshot(
        self, api: Any, *, initialize_baseline: bool = False
    ) -> Dict[str, Any]:
        """Delegate Store-bound risk fencing to the Backtrader bridge."""
        return _read_store_account_risk_snapshot(
            self, api, initialize_baseline=initialize_baseline,
            error_type=BtApiStoreError, safe_log=_safe_log,
        )

    def _sdk_exchange(self, dataname):
        """Resolve a Backtrader feed binding to an SDK exchange name."""
        venue = self._sdk_routes.get(str(dataname))
        if venue is None and len(self._sdk_exchanges) == 1:
            venue = next(iter(self._sdk_exchanges))
        if venue not in self._sdk_exchanges:
            raise BtApiStoreError("A symbol_routes entry is required for this feed")
        return venue

    def _sdk_account_id(self, venue, supplied=None):
        """Resolve the explicitly configured neutral account request label."""
        from bt_api_py.account_request_labels import (
            AccountRequestLabelError,
            validate_supplied_account_request_label,
        )

        account_id = self._configured_sdk_account_id(venue)
        try:
            return validate_supplied_account_request_label(account_id, supplied)
        except AccountRequestLabelError:
            raise BtApiStoreError(
                "The requested account_id differs from explicit SDK execution config"
            ) from None

    def _configured_sdk_account_id(self, venue):
        """Return only an explicitly configured neutral account request label."""
        from bt_api_py.account_request_labels import (
            AccountRequestLabelError,
            configured_account_request_label,
        )

        configured = self._sdk_execution_config_value("account_ids")
        try:
            return configured_account_request_label(configured, venue)
        except AccountRequestLabelError as exc:
            if exc.code == "account_labels_missing":
                raise BtApiStoreError(
                    "correlated order writes require explicit account_ids configuration"
                ) from None
            raise BtApiStoreError(
                "correlated order writes require an explicit account_ids entry for the exchange"
            ) from None

    def get_symbol_routes(self) -> Dict[str, str]:
        """Return a copy of the framework symbol-to-SDK venue bindings."""
        return dict(self._sdk_routes)

    def _sdk_order_request(self, venue, payload, *, correlation, framework_order=None):
        """Project Store config and instrument facts through the order adapter."""

        def resolve_request_context():
            return _resolve_store_order_request_context(
                self, venue, payload,
                contract_metadata_aliases=_contract_metadata_aliases,
                error_type=BtApiStoreError,
            )

        return self._sdk_correlated_order_adapter.build_order_request(
            venue,
            payload,
            correlation=correlation,
            framework_order=framework_order,
            api=self._api,
            resolve_request_context=resolve_request_context,
        )

    def _sdk_broker_event(self, venue, event):
        """Project an unverified SDK execution event through the BT adapter."""
        return _project_store_unverified_order_event(self, venue, event)

    def _record_unverified_sdk_execution_event(self, venue, event) -> None:
        """Record an unverified execution event through the BT adapter."""
        return _record_store_unverified_execution_event(self, venue, event)

    def _sdk_cancel_request(self, reference, dataname):
        """Resolve an exact SDK correlation and delegate typed request assembly."""
        return self._sdk_correlated_order_adapter.build_cancel_request(
            reference,
            dataname,
            api=self._api,
            sdk_exchange=self._sdk_exchange,
            configured_account_id=self._configured_sdk_account_id,
        )

    def _apply_sdk_account_push(self, venue, event):
        """Refresh cached venue cash/value from a partial WSS account push.

        Single-denomination pushes carry top-level ``cash``/``value`` and may
        replace the stale REST snapshot for this venue only; multi-coin pushes
        stay audit-only. Local order/position accounting is never touched.
        """
        projected = _project_sdk_account_push_values(event)
        if projected is None:
            self.emit_runtime_event("venue_account_update", venue=venue)
            return
        cash, value = projected
        cache = dict(self._venue_balance_cache.get(venue) or {})
        cache.update(cash=cash, value=value)
        self._venue_balance_cache[venue] = cache
        self.emit_runtime_event("venue_account_update", venue=venue)

    def get_orderbook_drop_counts(self):
        """Return per-symbol SDK-reported orderbook queue drop counts."""
        return self._market_delivery_state.book_drop_counts()

    @staticmethod
    def _market_event_kind(event: Any) -> str:
        """Return the canonical market kind without interpreting venue payloads."""
        return StoreMarketDeliveryState.event_kind(event)

    def _mark_feed_inflight(self, event: Any) -> None:
        self._market_delivery_state.mark_feed_inflight(event)

    def _record_market_drop(
        self,
        event: Any,
        reason: str,
        *,
        safety_impact: str = "stream_marked_stale",
        mark_stale: bool = True,
        symbol: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> None:
        """Record one canonical market event as explicitly discarded."""
        self._market_delivery_state.record_drop(
            event,
            reason,
            stream_generation=self._stream_generation,
            safety_impact=safety_impact,
            mark_stale=mark_stale,
            symbol=symbol,
            kind=kind,
        )

    def _mark_live_bar_queue_stale(self, symbol: str, reason: str) -> None:
        """Latch bar-queue loss and project it into the Store health view."""
        self._live_bar_queue.mark_stale(symbol, str(reason))

    def _project_live_bar_queue_stale(self, symbol: str, reason: str) -> None:
        """Mirror Backtrader queue continuity into the common health projection."""
        self._market_delivery_state.update_state(
            symbol,
            stale=True,
            stale_reason=reason,
            continuity_status="gap",
        )

    def _record_live_bar_queue_eviction(self, symbol: str, bar: Any) -> None:
        self._record_market_drop(
            bar,
            "store_live_bar_queue_overflow",
            safety_impact="oldest_live_bar_evicted_newest_retained_but_stream_marked_stale",
            symbol=symbol,
            kind="bar",
        )

    def _record_live_bar_enqueued(self, symbol: str, event_id: str) -> None:
        self._market_delivery_state.set_state(symbol, "last_enqueued_event_id", event_id)

    def _seed_live_bar_queue(self, live_bars: Optional[Dict[str, Iterable[Any]]]) -> None:
        """Seed completed bars through the same bounded path as live delivery."""
        if not live_bars:
            return
        for dataname, bars in live_bars.items():
            for bar in bars:
                self._enqueue_live_bar(str(dataname), self._copy_or_normalize_bar(bar))

    def _enqueue_live_bar(self, symbol: str, bar: Any) -> None:
        """Append one copied bar to the Backtrader-owned bounded queue."""
        self._live_bar_queue.enqueue(symbol, bar)

    def mark_feed_dropped(self, event: Any, reason: str) -> None:
        """Close a polled event's accounting when the Feed cannot dispatch it."""
        self._market_delivery_state.mark_feed_dropped(
            event, reason, stream_generation=self._stream_generation
        )

    def mark_strategy_delivered(self, event: Any) -> None:
        """Account for a standard event after its strategy callback returns."""
        self._market_delivery_state.mark_strategy_delivered(event)

    def get_stream_health(self, dataname: Optional[str] = None) -> Dict[str, Any]:
        """Return causal stream counters and the current fail-closed state."""
        return self._market_delivery_state.stream_health(
            dataname,
            stream_generation=self._stream_generation,
            live_bar_queue=self._live_bar_queue,
            live_bar_queue_size=self._live_bar_queue_size,
            market_stream_adapter=self._market_stream_adapter,
        )

    def is_stream_ready(self, dataname: str) -> bool:
        """Return false after an explicit gap, stale event, disconnect, or drop."""
        return self._market_delivery_state.is_stream_ready(
            dataname, live_bar_queue=self._live_bar_queue
        )

    def _record_sdk_market_event(self, venue: str, raw_event: Mapping[str, Any]):
        """Attach Store-side continuity evidence without decoding venue protocols."""
        return self._market_delivery_state.record_sdk_market_event(
            venue,
            raw_event,
            stream_generation=self._stream_generation,
        )

    def _accept_sdk_market_event(self, event: Mapping[str, Any], native_event: Any) -> None:
        """Commit sequence and recovery state only after native validation succeeds."""
        self._market_delivery_state.accept_sdk_market_event(event, native_event)

    def _mark_stream_disconnected(self, venue: str, event: Mapping[str, Any]) -> None:
        symbol = event.get("symbol")
        symbols = (
            [str(symbol)]
            if symbol
            else [name for name, route in self._sdk_routes.items() if route == venue]
        )
        for name in symbols:
            self._market_delivery_state.mark_disconnected(name)

    def _drain_sdk_events(self):
        with self._sdk_event_drain_lock:
            self._drain_sdk_events_locked()

    def _drain_sdk_events_locked(self):
        """Dispatch SDK events while the Store's drain lock is held."""
        return _drain_store_sdk_events_locked(
            self, error_type=BtApiStoreError,
            missing_dependency_error_type=BtApiMissingDependencyError,
        )

    def _copy_or_normalize_bar(self, bar):
        """Preserve raw values only for callers that explicitly opt in."""
        return self._history_cache.copy_or_normalize_bar(bar)

    def _copy_history_bar_sequence(self, bars):
        """Return independent history rows while preserving opted-in immutable PIT maps."""
        return self._history_cache.copy_history_sequence(bars)

    @property
    def preserve_raw_bars(self) -> bool:
        """Whether this Store preserves source bar fields for strict consumers."""
        return self._history_cache.preserve_raw_bars

    @staticmethod
    def _is_default_history_request(timeframe, compression, since, limit) -> bool:
        return StoreBarHistoryCache.is_default_request(timeframe, compression, since, limit)

    @staticmethod
    def _history_request_key(dataname, timeframe, compression, since, limit):
        return StoreBarHistoryCache.request_key(dataname, timeframe, compression, since, limit)

    def _clear_history_query_cache(self, dataname: str) -> None:
        self._history_cache.clear_query_cache(dataname)

    def _recover_sdk_startup_journal(self) -> None:
        """Ask the SDK to recover its local journal before transport startup."""
        try:
            from bt_api_py.startup_recovery import (
                StartupRecoveryError,
                recover_local_startup_journal,
            )
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py startup journal recovery is required"
            ) from exc
        try:
            recover_local_startup_journal(self._api)
        except StartupRecoveryError:
            _safe_log("warning", "btapistore:sdk_startup_recovery_failed")
            raise BtApiStoreError("SDK local journal recovery is unproven") from None

    def _ensure_sdk_direct_api_assembly(self) -> Any:
        """Transfer direct SDK construction/configuration to its single owner."""
        assembly = self._sdk_direct_api_assembly
        if assembly is not None:
            return assembly
        try:
            from bt_api_py.direct_api_assembly import (
                DIRECT_EXECUTION_CONFIG_KEYS,
                DirectApiAssembly,
            )
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py.direct_api_assembly.DirectApiAssembly is required"
            ) from exc

        options = {**self._config, **self._api_kwargs}
        execution_config = self._sdk_execution_config_snapshot()
        assembly = DirectApiAssembly.from_options(
            options=options,
            exchange_kwargs=self._sdk_direct_exchange_kwargs,
            execution_config=execution_config,
            api_factory=self._api_cls,
            api=self._api,
            expected_exchange_names=tuple(self._sdk_exchanges),
            execution_option_keys=DIRECT_EXECUTION_CONFIG_KEYS,
            market_data_only=self._metadata_probe_service.requires_market_data_only,
        )
        self._sdk_direct_api_assembly = assembly

        # The assembly now owns the exact factory configuration and execution
        # mapping. Store retains only its route-name projection and the
        # execution policy reads it needs through the adapter below.
        self._api_cls = None
        self._sdk_direct_exchange_kwargs = None
        self._sdk_execution_config = {}
        for key in (
            "exchange_kwargs",
            "execution_config",
            "debug",
            "transport_mode",
            "forwarding_config",
            "event_bus",
            *DIRECT_EXECUTION_CONFIG_KEYS,
        ):
            self._config.pop(key, None)
            self._api_kwargs.pop(key, None)
        options.clear()
        execution_config.clear()
        return assembly

    def _ensure_api_ready(self):
        """Ensure the Store-bound SDK is ready through its lifecycle bridge."""
        return _ensure_store_api_ready(
            self, error_type=BtApiStoreError,
            gateway_entrypoint=_legacy_gateway_entrypoint,
            gateway_error_type=LegacyGatewayMigrationRequiredError,
            placeholder_providers=_PLACEHOLDER_PROVIDERS,
            provider_not_implemented_error_type=BtApiProviderNotImplementedError,
            safe_log=_safe_log,
        )

    def _order_to_payload(self, order) -> Dict[str, Any]:
        """Convert a backtrader order into a generic bt_api_py payload."""
        return _project_order_to_payload(order)

    @staticmethod
    def _order_type_to_payload(order) -> str:
        """Return the canonical bt_api_py order type for a backtrader order."""
        return _project_order_type_to_payload(order)

    @staticmethod
    def _extract_dataname(data) -> str:
        """Extract a stable symbol name from a data feed."""
        return _project_dataname(data)

    def _masked_account_id(self) -> str:
        """Return a masked explicitly configured neutral SDK account ID."""
        accounts = self._sdk_execution_config_value("account_ids")
        if not isinstance(accounts, Mapping) or not accounts:
            return ""
        values = sorted(str(value) for value in accounts.values() if value not in (None, ""))
        if len(values) != 1:
            return "<multiple>" if values else ""
        account_id = values[0]
        if len(account_id) <= 4:
            return "*" * len(account_id)
        return f"{account_id[:2]}***{account_id[-2:]}"
    def _emit_broker_runtime_event(self, update: Dict[str, Any]):
        """Translate a projected Broker update into Store-owned notifications."""
        projected = _project_broker_runtime_event(update)
        if projected is None:
            return
        event_type, event_kwargs = projected
        self.emit_runtime_event(event_type, **event_kwargs)
